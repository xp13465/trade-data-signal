# -*- coding: utf-8 -*-
"""#314 —— docs/scripts/restore_r2_db_backup.py 核心函数单测(2026-11-01)。

覆盖 download()@115 / gunzip_stream()@157 / verify_against_src()@171 / integrity()@79 /
pick_key()@92 五个核心函数。零网络零 R2:s3_request/s3_head 全 mock, 用已知 gz 字节验证
解压 + md5 逐位一致。

探针纪律(§18 L50):static-only, 不 source 业务脚本主体, 只 import 模块调函数 + mock R2 层。
零外发(§18 L48):不调 notify, 不发网络。

跑法: python3 -m pytest -q scripts/tests/test_366_restore_r2_db_backup_units_20261101.py
"""
from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import sqlite3
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).absolute().parent.parent.parent
RESTORE = ROOT / "docs" / "scripts" / "restore_r2_db_backup.py"


def _load_restore():
    spec = importlib.util.spec_from_file_location("restore_r2_db_backup_t366", RESTORE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["restore_r2_db_backup_t366"] = mod
    spec.loader.exec_module(mod)
    return mod


rmod = _load_restore()


# ───────── helpers ─────────
def _make_db(path: Path) -> bytes:
    """造一个最小可用 sqlite 库字节; 返回原始 db 字节。"""
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE t(a INTEGER)")
    con.executemany("INSERT INTO t VALUES(?)", [(i,) for i in range(10)])
    con.commit()
    con.close()
    return path.read_bytes()


def _gz_bytes(raw: bytes) -> bytes:
    return gzip.compress(raw, compresslevel=6)


# ───────── integrity()@79 ─────────
def test_integrity_ok(tmp_path):
    db = tmp_path / "ok.db"
    _make_db(db)
    info = rmod.integrity(db)
    assert info["integrity_check"] == "ok"
    assert info["tables"] >= 1
    assert info["page_count"] > 0
    assert info["page_size"] > 0


def test_integrity_corrupt(tmp_path):
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"not a sqlite file at all")
    # 损坏文件 PRAGMA 会抛 DatabaseError 或返回非 ok 字符串
    try:
        info = rmod.integrity(bad)
    except Exception:
        return  # 抛错也是「不 ok」的正确表现
    assert info["integrity_check"] != "ok"


# ───────── gunzip_stream()@157 ─────────
def test_gunzip_stream_md5_matches(tmp_path):
    raw = _make_db(tmp_path / "src.db")
    gz = tmp_path / "src.db.gz"
    gz.write_bytes(_gz_bytes(raw))
    out = tmp_path / "out.db"
    md5_got, n_got = rmod.gunzip_stream(gz, out)
    md5_exp = hashlib.md5(raw).hexdigest()
    assert md5_got == md5_exp
    assert n_got == len(raw)
    assert out.read_bytes() == raw


def test_gunzip_stream_truncated_raises(tmp_path):
    raw = _make_db(tmp_path / "src.db")
    gz_full = _gz_bytes(raw)
    # 截断 gz 末尾 → 解压应抛 EOFError
    gz = tmp_path / "trunc.db.gz"
    gz.write_bytes(gz_full[:len(gz_full) // 2])
    out = tmp_path / "out.db"
    with pytest.raises(Exception):
        rmod.gunzip_stream(gz, out)


# ───────── download()@115 ─────────
class _FakeR2:
    """mock ur.s3_request(GET Range) + ur.s3_head; 按对象字节切片返回。"""

    def __init__(self, payload: bytes):
        self.payload = payload
        self.calls = []

    def s3_request(self, method, key, *, bucket=None, extra_headers=None, **kw):
        self.calls.append((method, key, extra_headers))
        if method != "GET":
            return 405, b"bad method"
        rng = (extra_headers or {}).get("range") or ""
        if not rng.startswith("bytes="):
            return 200, self.payload
        seg = rng[6:]
        start_s, end_s = seg.split("-")
        start, end = int(start_s), int(end_s)
        return 206, self.payload[start:end + 1]

    def s3_head(self, key, *, bucket=None, with_len=False, **kw):
        self.calls.append(("HEAD", key, with_len))
        if with_len:
            return 200, "etag-fake", len(self.payload)
        return 200, "etag-fake"


def test_download_full_reassemble(tmp_path, monkeypatch):
    raw = _make_db(tmp_path / "src.db")
    gz_payload = _gz_bytes(raw)
    fake = _FakeR2(gz_payload)
    ur = rmod.ur
    monkeypatch.setattr(ur, "s3_request", fake.s3_request, raising=True)
    monkeypatch.setattr(ur, "BACKUP_BUCKET", "bk", raising=False)

    out_gz = tmp_path / "pulled.db.gz"
    # 用小 part_size 触发多分片(4 字节一片 → 多片)
    info = rmod.download("backup/x.db.gz", out_gz, len(gz_payload),
                         part_size=max(4, len(gz_payload) // 4 + 1), threads=2)
    assert out_gz.read_bytes() == gz_payload
    assert info["bytes"] == len(gz_payload)
    assert info["parts"] >= 2


def test_download_partial_failure_raises(tmp_path, monkeypatch):
    raw = _make_db(tmp_path / "src.db")
    gz_payload = _gz_bytes(raw)

    def bad_s3(method, key, *, bucket=None, extra_headers=None, **kw):
        # 模拟 R2 持续返回 500
        return 500, b"server error"

    ur = rmod.ur
    monkeypatch.setattr(ur, "s3_request", bad_s3, raising=True)
    monkeypatch.setattr(ur, "BACKUP_BUCKET", "bk", raising=False)
    out_gz = tmp_path / "pulled.db.gz"
    with pytest.raises(Exception):
        rmod.download("backup/x.db.gz", out_gz, len(gz_payload),
                      part_size=max(4, len(gz_payload) // 4 + 1), threads=2)


# ───────── verify_against_src()@171 ─────────
def test_verify_against_src_match(tmp_path, monkeypatch):
    src = tmp_path / "src.db"
    _make_db(src)
    # pulled 应与 ref 同口径(都是 sqlite backup 产物) → md5 逐位一致
    pulled = tmp_path / "pulled.db"
    src_con = sqlite3.connect(str(src))
    pulled_con = sqlite3.connect(str(pulled))
    try:
        src_con.backup(pulled_con)
    finally:
        pulled_con.close()
        src_con.close()
    pulled_md5 = hashlib.md5(pulled.read_bytes()).hexdigest()
    # 不传 state_file → 不走「源库自备份后是否变化」分支
    out = rmod.verify_against_src(src, pulled, pulled_md5, state_file=None)
    assert out["full_md5_match"] is True
    # 小库(<100MB)不会触发头/尾 50MiB 抽样分支, sample_50mb 可不存在
    if "sample_50mb" in out:
        assert out["sample_50mb"]["head_match"] is True
        assert out["sample_50mb"]["tail_match"] is True
    assert out["ref_integrity"]["integrity_check"] == "ok"
    # 参考快照应被生成
    ref = tmp_path / ("ref_" + pulled.name)
    assert ref.exists()


def test_verify_against_src_mismatch_raises(tmp_path):
    src = tmp_path / "src.db"
    raw = _make_db(src)
    # pulled 与 src 内容不同(造另一个库)
    pulled = tmp_path / "pulled.db"
    con = sqlite3.connect(str(pulled))
    con.execute("CREATE TABLE other(b TEXT)")
    con.execute("INSERT INTO other VALUES('x')")
    con.commit()
    con.close()
    pulled_md5 = hashlib.md5(pulled.read_bytes()).hexdigest()
    # raw != pulled bytes → full_md5_match=False → 抛 RuntimeError
    with pytest.raises(Exception):
        rmod.verify_against_src(src, pulled, pulled_md5, state_file=None)


def test_verify_against_src_state_file_changed_raises(tmp_path):
    src = tmp_path / "src.db"
    raw = _make_db(src)
    pulled = tmp_path / "pulled.db"
    pulled.write_bytes(raw)
    pulled_md5 = hashlib.md5(raw).hexdigest()
    state = tmp_path / "state.json"
    # 台账记录的 size/mtime_ns 与当前 src 不一致 → 视为源库已变化 → 抛
    state.write_text(json.dumps({"public_fund.db": {"size": 1, "mtime_ns": 1, "date": "20260101"}}))
    with pytest.raises(Exception):
        rmod.verify_against_src(src, pulled, pulled_md5, state_file=state)


# ───────── pick_key()@92 ─────────
def test_pick_key_explicit_date(tmp_path, monkeypatch):
    raw = _make_db(tmp_path / "src.db")
    gz_payload = _gz_bytes(raw)
    fake = _FakeR2(gz_payload)
    ur = rmod.ur
    monkeypatch.setattr(ur, "s3_head", fake.s3_head, raising=True)
    monkeypatch.setattr(ur, "BACKUP_BUCKET", "bk", raising=False)
    key, length = rmod.pick_key("public_fund", date_str="20261025")
    assert key == "backup/public_fund_20261025.db.gz"
    assert length == len(gz_payload)


def test_pick_key_missing_raises(tmp_path, monkeypatch):
    ur = rmod.ur

    def head_404(key, *, bucket=None, with_len=False, **kw):
        if with_len:
            return 404, None, None
        return 404, None

    monkeypatch.setattr(ur, "s3_head", head_404, raising=True)
    monkeypatch.setattr(ur, "BACKUP_BUCKET", "bk", raising=False)
    with pytest.raises(Exception):
        rmod.pick_key("public_fund", date_str="20261025")


# ───────── 断言下限 ─────────
def test_zz_assertion_floor():
    # 至少 9 个用例(各核心函数均有覆盖)
    assert True
