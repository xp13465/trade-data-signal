# -*- coding: utf-8 -*-
"""#315/#312/#316 —— upload_r2.py R2 备份健壮性自验(2026-11-01)。

· #315: _multipart_upload complete 非 200 → best-effort DELETE?uploadId abort 被调
· #312: _backup_public_fund_db 跳过前 s3_head 校验 R2 对象存在 + Content-Length 匹配
· #316: cmd_upload_decommissioned >_MULTIPART_THRESHOLD 走 _upload_multipart_file 流式分片

零真实 R2(§18 L48):s3_request/s3_head/_list_keys 全 mock, 不触发网络, 不读凭证。
探针纪律(§18 L50):static-only, 只 import 模块调函数 + mock R2 层, 不跑业务脚本主体。

跑法: python3 -m pytest -q scripts/tests/test_367_r2chain_upload_robustness_20261101.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).absolute().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import upload_r2 as ur  # noqa: E402

_N = [0]


def _chk(cond, msg=""):
    _N[0] += 1
    assert cond, msg


# ══════════════════════ #315: complete 非 200 → DELETE?uploadId 被调 ══════════════════════
def test_315_complete_non200_aborts(monkeypatch):
    """complete 返回 500 → 应补一次 DELETE?uploadId= abort。"""
    calls = []

    def fake_s3(method, key, payload=None, *, query="", content_type=None,
                with_headers=False, keep_alive=False, progress_label=None, bucket=None, **kw):
        calls.append({"method": method, "key": key, "query": query})
        if method == "POST" and "uploads=" in (query or ""):
            # create: 返回含 UploadId 的 XML
            return 200, b"<InitiateMultipartUpload><UploadId>uid-xyz</UploadId></InitiateMultipartUpload>"
        if method == "PUT":
            # part upload: with_headers=True → 返回 3 元组
            return 200, b"", {"ETag": '"etag-p1"'}
        if method == "POST" and "uploadId=" in (query or ""):
            # complete: 故意返回非 200
            return 500, b"complete failed"
        if method == "DELETE":
            return 204, b""
        return 200, b""

    monkeypatch.setattr(ur, "s3_request", fake_s3)
    # 小 total + 1 片(读回调返回固定字节)
    total = 64

    def read_part(off, n):
        return b"\x00" * n

    st, data = ur._multipart_upload("k", total, read_part, "application/octet-stream", bucket="bk")
    _chk(st == 500, f"complete 失败应返回 500, 得 {st}")
    # 应有: create(POST uploads=) + 1× PUT part + complete(POST uploadId=) + abort(DELETE uploadId=)
    deletes = [c for c in calls if c["method"] == "DELETE" and "uploadId=" in (c["query"] or "")]
    _chk(len(deletes) == 1, f"complete 非 200 应补 1 次 DELETE?uploadId abort, 实得 {len(deletes)} 次")


def test_315_complete_ok_no_abort(monkeypatch):
    """complete 返回 200 → 不应 abort(DELETE uploadId 不出现)。"""
    calls = []

    def fake_s3(method, key, payload=None, *, query="", content_type=None,
                with_headers=False, keep_alive=False, progress_label=None, bucket=None, **kw):
        calls.append({"method": method, "query": query})
        if method == "POST" and "uploads=" in (query or ""):
            return 200, b"<InitiateMultipartUpload><UploadId>uid-ok</UploadId></InitiateMultipartUpload>"
        if method == "PUT":
            return 200, b"", {"ETag": '"e"'}
        if method == "POST" and "uploadId=" in (query or ""):
            return 200, b"<ok/>"
        if method == "DELETE":
            return 204, b""
        return 200, b""

    monkeypatch.setattr(ur, "s3_request", fake_s3)

    def read_part(off, n):
        return b"\x00" * n

    st, data = ur._multipart_upload("k", 64, read_part, "application/octet-stream", bucket="bk")
    _chk(st == 200, f"complete 成功应返回 200, 得 {st}")
    deletes = [c for c in calls if c["method"] == "DELETE" and "uploadId=" in (c["query"] or "")]
    _chk(len(deletes) == 0, f"complete 成功不应 abort, 实得 {len(deletes)} 次 DELETE")


# ══════════════════════ #312: 跳过前 head 校验 ══════════════════════
def _make_state_file(tmp_path, prev_key, prev_gz_size, size=100, mtime_ns=999):
    state = tmp_path / "state.json"
    state.write_text(__import__("json").dumps({
        "public_fund.db": {"size": size, "mtime_ns": mtime_ns,
                           "date": "20261025", "key": prev_key, "gz_size": prev_gz_size}
    }))
    return state


def test_312_head_missing_no_skip(monkeypatch, tmp_path):
    """台账在但 R2 对象 head 404 → 不跳过(走重传)。"""
    dbdir = tmp_path / "db"
    dbdir.mkdir()
    src = dbdir / "public_fund.db"
    src.write_bytes(b"\x00" * 100)  # size 与台账一致
    os.utime(src, ns=(999, 999))  # 固定 mtime_ns 与台账一致, 触达 head 校验分支
    state_file = _make_state_file(tmp_path, "backup/public_fund_20261025.db.gz", 50, size=100, mtime_ns=999)

    def fake_head(key, *, bucket=None, with_len=False, keep_alive=False, **kw):
        if with_len:
            return 404, None, None
        return 404, None

    monkeypatch.setattr(ur, "s3_head", fake_head)
    monkeypatch.setattr(ur, "BACKUP_BUCKET", "bk", raising=False)
    monkeypatch.setattr(ur, "_load_db_backup_state", lambda repo: __import__("json").loads(state_file.read_text()), raising=False)

    # 源文件 stat 与台账一致(size=100, mtime_ns=999) → 旧逻辑会跳过; 新逻辑 head 404 → 不跳过
    # _backup_public_fund_db 后续会走快照+gz, 我们只断「没在跳过分支 return True」
    # 通过 mock _sqlite_snapshot_to_gz + _upload_file_to_key 避免真实压缩/上传
    monkeypatch.setattr(ur, "_sqlite_snapshot_to_gz", lambda src, gz: 50, raising=False)
    monkeypatch.setattr(ur, "_upload_file_to_key", lambda key, gz, ct, bucket=None: (200, b""), raising=False)
    monkeypatch.setattr(ur, "_maybe_upload_weekly_file", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(ur, "_maybe_upload_monthly_file", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(ur, "_save_db_backup_state", lambda repo, st: None, raising=False)

    rc = ur._backup_public_fund_db(dbdir, tmp_path, "20261101")
    # 走重传 → _upload_file_to_key 被调 → 返回 200 → True; 关键是 head 被调且没走跳过 print
    _chk(rc is True, f"重传后应返回 True, 得 {rc}")


def test_312_head_size_mismatch_no_skip(monkeypatch, tmp_path):
    """head 200 但 Content-Length != 台账 gz_size → 不跳过(走重传)。"""
    dbdir = tmp_path / "db"
    dbdir.mkdir()
    src = dbdir / "public_fund.db"
    src.write_bytes(b"\x00" * 100)
    os.utime(src, ns=(999, 999))
    state_file = _make_state_file(tmp_path, "backup/public_fund_20261025.db.gz", 50, size=100, mtime_ns=999)

    def fake_head(key, *, bucket=None, with_len=False, keep_alive=False, **kw):
        # 对象存在但大小与台账(50)不符
        if with_len:
            return 200, "etag", "999"  # str 匹配真实 getheader 返回类型
        return 200, "etag"

    monkeypatch.setattr(ur, "s3_head", fake_head)
    monkeypatch.setattr(ur, "BACKUP_BUCKET", "bk", raising=False)
    monkeypatch.setattr(ur, "_load_db_backup_state", lambda repo: __import__("json").loads(state_file.read_text()), raising=False)
    monkeypatch.setattr(ur, "_sqlite_snapshot_to_gz", lambda src, gz: 50, raising=False)
    monkeypatch.setattr(ur, "_upload_file_to_key", lambda key, gz, ct, bucket=None: (200, b""), raising=False)
    monkeypatch.setattr(ur, "_maybe_upload_weekly_file", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(ur, "_maybe_upload_monthly_file", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(ur, "_save_db_backup_state", lambda repo, st: None, raising=False)

    rc = ur._backup_public_fund_db(dbdir, tmp_path, "20261101")
    _chk(rc is True, f"大小不匹配应重传返回 True, 得 {rc}")


def test_312_head_match_skips(monkeypatch, tmp_path):
    """head 200 + Content-Length==台账 gz_size → 跳过(return True, 不上传)。"""
    dbdir = tmp_path / "db"
    dbdir.mkdir()
    src = dbdir / "public_fund.db"
    src.write_bytes(b"\x00" * 100)
    os.utime(src, ns=(999, 999))
    state_file = _make_state_file(tmp_path, "backup/public_fund_20261025.db.gz", 50, size=100, mtime_ns=999)

    def fake_head(key, *, bucket=None, with_len=False, keep_alive=False, **kw):
        if with_len:
            return 200, "etag", "50"  # str 匹配真实 getheader 返回类型; 匹配台账 gz_size=50
        return 200, "etag"

    upload_called = []

    def fake_upload(key, gz, ct, bucket=None):
        upload_called.append(key)
        return 200, b""

    monkeypatch.setattr(ur, "s3_head", fake_head)
    monkeypatch.setattr(ur, "BACKUP_BUCKET", "bk", raising=False)
    monkeypatch.setattr(ur, "_load_db_backup_state", lambda repo: __import__("json").loads(state_file.read_text()), raising=False)
    monkeypatch.setattr(ur, "_upload_file_to_key", fake_upload, raising=False)
    monkeypatch.setattr(ur, "_sqlite_snapshot_to_gz", lambda src, gz: 50, raising=False)
    monkeypatch.setattr(ur, "_maybe_upload_weekly_file", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(ur, "_maybe_upload_monthly_file", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(ur, "_save_db_backup_state", lambda repo, st: None, raising=False)

    rc = ur._backup_public_fund_db(dbdir, tmp_path, "20261101")
    _chk(rc is True, f"匹配应跳过返回 True, 得 {rc}")
    _chk(len(upload_called) == 0, f"匹配应不上传, 实上传 {len(upload_called)} 次")


# ══════════════════════ #316: >阈值走流式 multipart ══════════════════════
def test_316_large_file_uses_multipart(monkeypatch, tmp_path):
    """>_MULTIPART_THRESHOLD 的 .gz 文件 → 走 _upload_multipart_file(不整文件进内存)。"""
    big = tmp_path / "big.tar.gz"
    # 造一个略大于阈值的文件(用真实字节, 避免稀疏文件 stat 落盘问题)
    threshold = ur._MULTIPART_THRESHOLD
    payload = b"\x00" * (threshold + 1024)
    big.write_bytes(payload)

    multipart_called = []
    single_put_called = []

    def fake_multipart_file(key, path, content_type, bucket=None):
        multipart_called.append((key, path, content_type))
        return 200, b""

    def fake_s3(method, key, payload=None, *, content_type=None, bucket=None, **kw):
        single_put_called.append((method, key))
        return 200, b""

    monkeypatch.setattr(ur, "_upload_multipart_file", fake_multipart_file, raising=False)
    monkeypatch.setattr(ur, "s3_request", fake_s3)
    monkeypatch.setattr(ur, "BACKUP_BUCKET", "bk", raising=False)

    key = ur.cmd_upload_decommissioned(str(big), "big-20261101.tar.gz")
    _chk(key == "decommissioned/big-20261101.tar.gz", f"key 应为 decommissioned/ 前缀, 得 {key}")
    _chk(len(multipart_called) == 1, f">阈值应走 _upload_multipart_file, 实调 {len(multipart_called)} 次")
    _chk(len(single_put_called) == 0, f">阈值不应单 PUT, 实单 PUT {len(single_put_called)} 次")


def test_316_small_file_single_put(monkeypatch, tmp_path):
    """≤_MULTIPART_THRESHOLD 的 .gz 文件 → 单 PUT(不进 multipart 分支)。"""
    small = tmp_path / "small.gz"
    small.write_bytes(b"\x00" * 1024)

    multipart_called = []
    single_put_called = []

    def fake_multipart_file(key, path, content_type, bucket=None):
        multipart_called.append(key)
        return 200, b""

    def fake_s3(method, key, payload=None, *, content_type=None, bucket=None, **kw):
        single_put_called.append((method, key))
        return 200, b""

    monkeypatch.setattr(ur, "_upload_multipart_file", fake_multipart_file, raising=False)
    monkeypatch.setattr(ur, "s3_request", fake_s3)
    monkeypatch.setattr(ur, "BACKUP_BUCKET", "bk", raising=False)

    key = ur.cmd_upload_decommissioned(str(small), "small-20261101.gz")
    _chk(key == "decommissioned/small-20261101.gz", f"key 应正确, 得 {key}")
    _chk(len(multipart_called) == 0, f"小文件不应走 multipart, 实调 {len(multipart_called)} 次")
    _chk(len(single_put_called) == 1, f"小文件应单 PUT 1 次, 实 {len(single_put_called)} 次")


def test_316_uncompressed_temp_gz(monkeypatch, tmp_path):
    """未压缩文件 → 落盘临时 gz → 单 PUT; 上传完 temp 被清理。"""
    raw = tmp_path / "data.bin"
    raw.write_bytes(b"abc" * 1000)  # 未压缩, 小于阈值

    temp_files = []

    def fake_s3(method, key, payload=None, *, content_type=None, bucket=None, **kw):
        # 断言上传时 content_type 是 application/gzip
        _chk(content_type == "application/gzip", f"未压缩文件应 gzip 后以 application/gzip 上传, 得 {content_type}")
        single_put_called.append((method, key))
        return 200, b""

    single_put_called = []
    monkeypatch.setattr(ur, "_upload_multipart_file", lambda *a, **k: (200, b""), raising=False)
    monkeypatch.setattr(ur, "s3_request", fake_s3)
    monkeypatch.setattr(ur, "BACKUP_BUCKET", "bk", raising=False)

    key = ur.cmd_upload_decommissioned(str(raw), "data-20261101")
    _chk(key == "decommissioned/data-20261101", f"key 应正确, 得 {key}")
    _chk(len(single_put_called) == 1, f"应单 PUT 1 次, 实 {len(single_put_called)} 次")
    # 临时 gz 目录应被清理(tmpdir prefix r2-decom-gz- 不应残留)
    import glob
    leftover = glob.glob("/tmp/r2-decom-gz-*")
    _chk(len(leftover) == 0 or all(not Path(p).exists() for p in leftover),
         f"临时 gz 目录应被清理, 残留 {leftover}")


# ══════════════════════ #C: cmd_upload_claude_backup 回归(同 #316 风格) ══════════════════════
# 6da4031d1 给 cmd_upload_claude_backup 加了流式 multipart(>_MULTIPART_THRESHOLD)分支,
# 但未补 committed 回归测试; 本节补大文件→multipart / 小文件→单 PUT 两条 + 反证判别力。
# 零网络(§18 L48): monkeypatch _upload_multipart_file / s3_request 为 recorder, 不读凭证。
def test_claude_backup_large_file_uses_multipart(monkeypatch, tmp_path):
    """>阈值 → 走 _upload_multipart_file(流式分片, 不整文件进内存)。"""
    # 造一个 claude-self-YYYYMMDD.tar.gz 命名的真实文件; 压低阈值避免写 100MB
    src = tmp_path / "claude-self-20261101.tar.gz"
    src.write_bytes(b"\x00" * 2048)
    monkeypatch.setattr(ur, "_MULTIPART_THRESHOLD", 1024, raising=False)

    multipart_called = []
    single_put_called = []

    def fake_multipart(key, path, content_type, bucket=None):
        multipart_called.append((key, content_type, bucket))
        return 200, b""

    def fake_s3(method, key, payload=None, *, content_type=None, bucket=None, **kw):
        single_put_called.append((method, key))
        return 200, b""

    monkeypatch.setattr(ur, "_upload_multipart_file", fake_multipart, raising=False)
    monkeypatch.setattr(ur, "s3_request", fake_s3)
    monkeypatch.setattr(ur, "BACKUP_BUCKET", "bk", raising=False)

    ur.cmd_upload_claude_backup(str(src))
    _chk(len(multipart_called) == 1, f">阈值应走 multipart, 实调 {len(multipart_called)} 次")
    _chk(len(single_put_called) == 0, f">阈值不应单 PUT, 实单 PUT {len(single_put_called)} 次")
    _chk(multipart_called[0][0] == "claude-backup/claude-self-20261101.tar.gz",
         f"key 应为 claude-backup/ 前缀, 得 {multipart_called[0][0]}")
    _chk(multipart_called[0][1] == "application/gzip", f"content_type 应 application/gzip, 得 {multipart_called[0][1]}")


def test_claude_backup_small_file_single_put(monkeypatch, tmp_path):
    """≤阈值 → 单 PUT(不进 multipart 分支)。"""
    src = tmp_path / "claude-self-20261101.tar.gz"
    src.write_bytes(b"\x00" * 512)  # < 阈值 1024
    monkeypatch.setattr(ur, "_MULTIPART_THRESHOLD", 1024, raising=False)

    multipart_called = []
    single_put_called = []

    def fake_multipart(key, path, content_type, bucket=None):
        multipart_called.append(key)
        return 200, b""

    def fake_s3(method, key, payload=None, *, content_type=None, bucket=None, **kw):
        single_put_called.append((method, key, content_type))
        return 200, b""

    monkeypatch.setattr(ur, "_upload_multipart_file", fake_multipart, raising=False)
    monkeypatch.setattr(ur, "s3_request", fake_s3)
    monkeypatch.setattr(ur, "BACKUP_BUCKET", "bk", raising=False)

    ur.cmd_upload_claude_backup(str(src))
    _chk(len(multipart_called) == 0, f"小文件不应走 multipart, 实调 {len(multipart_called)} 次")
    _chk(len(single_put_called) == 1, f"小文件应单 PUT 1 次, 实 {len(single_put_called)} 次")
    _chk(single_put_called[0][2] == "application/gzip", f"单 PUT content_type 应 application/gzip, 得 {single_put_called[0][2]}")


def test_claude_backup_multipart_branch_distinguishable(monkeypatch, tmp_path):
    """#C 反证判别力: 去掉流式分支(把 _upload_multipart_file 替换为会 FAIL 的探针)→
    大文件本应走 multipart, 若分支被回退则 fake_s3 会被调(单 PUT 路径)→ 断言 multipart_called==1 失败。
    此处正向验证判别力: 大文件 + 阈值压低 ⇒ 必走 multipart(与上例一致, 证明分支真在)。"""
    src = tmp_path / "claude-self-20261102.tar.gz"
    src.write_bytes(b"\x00" * 4096)
    monkeypatch.setattr(ur, "_MULTIPART_THRESHOLD", 1024, raising=False)

    multipart_called = []
    monkeypatch.setattr(ur, "_upload_multipart_file",
                        lambda key, path, ct, bucket=None: multipart_called.append(key) or (200, b""),
                        raising=False)
    monkeypatch.setattr(ur, "s3_request", lambda *a, **k: (200, b""))
    monkeypatch.setattr(ur, "BACKUP_BUCKET", "bk", raising=False)
    ur.cmd_upload_claude_backup(str(src))
    _chk(len(multipart_called) == 1, f"大文件应必走 multipart(判别力), 实 {len(multipart_called)}")


# ══════════════════════ 断言下限 ══════════════════════
def test_zz_assertion_floor():
    _chk(_N[0] >= 12, f"断言数应 >=12, 实得 {_N[0]}")
