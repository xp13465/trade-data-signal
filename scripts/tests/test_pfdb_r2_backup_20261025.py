# -*- coding: utf-8 -*-
"""public_fund.db 纳入 R2 备份链的自测(2026-10-25)。

背景(实测): 云上 public_fund.db 2.9G 只有同盘三份拷贝, `upload-db` 原来只备份
sentiment.db + etf_national_team.db, 盘毁即全失; docs/r2-deployment.md 却写着「靠 R2 备份」。

覆盖:
  ① `cmd_upload_db` 清单包含 public_fund.db, 且 sentiment/etf 两项的 key 形态/上传方式不变;
  ② 大库链路「未变更跳过」: 源文件 size+mtime 未变 → 第二次不再上传(省 0.87GB/轮);
  ③ 大库链路源文件不存在 → 不计入分母(不误报失败), 原两项照常;
  ④ `_upload_multipart_file` 流式分片: 每片读到的字节拼回去 == 原文件(防分片偏移算错传坏);
  ⑤ `_upload_multipart`(内存入口)重构后行为不变;
  ⑥ WAL 一致性: 库有未 checkpoint 的 -wal 数据时, 快照仍包含已提交事务(这就是不能直接 cp 的理由);
  ⑦ 分层清理 per-name: public_fund 按缩短保留期清理, 小库保留期不受影响;
  ⑧ 上传失败(500) → 命令非零退出且**不写「已备份」台账**(下一轮会重传, 不会误跳过);
  ⑨ 备份期间源库被写入 → 不记台账(避免把旧快照记成最新, 下一轮重传)。

零网络 / 零外发: 全部 s3_request 打桩(§18 L48), 只用临时目录里的小 SQLite 文件。
"""
from __future__ import annotations

import gzip
import io
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import upload_r2 as ur  # noqa: E402


# ── 公共替身 ────────────────────────────────────────────────────────────────
class FakeS3:
    """记录所有请求的 s3_request 替身; 支持 multipart 三阶段与 HEAD/DELETE/list。"""

    def __init__(self):
        self.calls = []
        self.objects = {}
        self.fail_put = False

    def __call__(self, method, key, payload=b"", query="", bucket=None, content_type=None,
                 with_headers=False, keep_alive=False, extra_headers=None, progress_label=None):
        self.calls.append({"method": method, "key": key, "payload": payload, "query": query,
                           "bucket": bucket, "content_type": content_type,
                           "progress_label": progress_label})
        if method == "POST" and query == "uploads=":
            return 200, b"<InitiateMultipartUploadResult><UploadId>uid-1</UploadId></InitiateMultipartUploadResult>"
        if method == "PUT":
            if self.fail_put:
                return 500, b"boom"
            if "partNumber=" in query:
                pn = int(query.split("partNumber=")[1].split("&")[0])
                self.objects.setdefault(key, {})[pn] = payload
                return 200, b"", {"ETag": '"etag-%d"' % pn} if with_headers else (200, b"")
            self.objects[key] = payload
            return (200, b"", {"ETag": '"etag"', "Content-Length": str(len(payload))}) if with_headers else (200, b"")
        if method == "POST" and "uploadId=" in query:
            return 200, b"<CompleteMultipartUploadResult/>"
        if method == "DELETE":
            return 204, b""
        raise AssertionError(f"未预期的请求 {method} {key} {query}")


def _make_db(path, rows=3, table="t"):
    conn = sqlite3.connect(str(path))
    conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany(f"INSERT INTO {table} (v) VALUES (?)", [(f"v{i}",) for i in range(rows)])
    conn.commit()
    conn.close()
    return path


def _today():
    return datetime.now().strftime("%Y%m%d")


@pytest.fixture
def repo_dir(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    _make_db(data / "sentiment.db")
    _make_db(data / "etf_national_team.db")
    _make_db(data / "public_fund.db", rows=5)
    return tmp_path


@pytest.fixture
def quiet(monkeypatch):
    """拦掉周/月副本与分层清理(它们的网络面另有既有测试), 只观察日备份主链。"""
    calls = {"weekly": [], "monthly": [], "prune": []}
    monkeypatch.setattr(ur, "_maybe_upload_weekly", lambda *a, **k: calls["weekly"].append(a[:2]))
    monkeypatch.setattr(ur, "_maybe_upload_monthly", lambda *a, **k: calls["monthly"].append(a[:2]))
    monkeypatch.setattr(ur, "_maybe_upload_weekly_file", lambda *a, **k: calls["weekly"].append(a[:2]))
    monkeypatch.setattr(ur, "_maybe_upload_monthly_file", lambda *a, **k: calls["monthly"].append(a[:2]))
    monkeypatch.setattr(ur, "_prune_r2_backup", lambda *a, **k: calls["prune"].append(k))
    return calls


# ── ① 清单包含 public_fund, 原两项不变 ──────────────────────────────────────
def test_upload_db_includes_public_fund_and_keeps_old_two(repo_dir, monkeypatch, quiet):
    fake = FakeS3()
    monkeypatch.setattr(ur, "s3_request", fake)
    monkeypatch.setenv("REPO", str(repo_dir))

    ur.cmd_upload_db()

    generic_puts = [c for c in fake.calls if c["method"] == "PUT" and "partNumber=" not in c["query"]]
    keys = [c["key"] for c in generic_puts]
    today = _today()
    assert f"backup/sentiment_{today}.db.gz" in keys
    assert f"backup/etf_national_team_{today}.db.gz" in keys
    assert f"backup/public_fund_{today}.db.gz" in keys
    # 小库仍是内存 gzip 单 PUT(与改动前一致): payload 是合法 gzip, 解压后 == 原库字节
    for name in ("sentiment", "etf_national_team"):
        call = next(c for c in generic_puts if c["key"] == f"backup/{name}_{today}.db.gz")
        raw = gzip.decompress(call["payload"])
        assert raw == (repo_dir / "data" / f"{name}.db").read_bytes()
        assert call["bucket"] == ur.BACKUP_BUCKET


# ── ② 未变更跳过 ────────────────────────────────────────────────────────────
def test_public_fund_skips_when_source_unchanged(repo_dir, monkeypatch, quiet, capsys):
    fake = FakeS3()
    monkeypatch.setattr(ur, "s3_request", fake)
    monkeypatch.setenv("REPO", str(repo_dir))

    ur.cmd_upload_db()
    first = [c["key"] for c in fake.calls if c["method"] == "PUT" and c["key"].startswith("backup/public_fund_")]
    assert len(first) == 1
    state = json.loads((repo_dir / "data" / ur._DB_BACKUP_STATE_FILE).read_text())
    assert state["public_fund.db"]["size"] == (repo_dir / "data" / "public_fund.db").stat().st_size

    fake.calls.clear()
    ur.cmd_upload_db()
    second = [c for c in fake.calls if c["method"] == "PUT" and c["key"].startswith("backup/public_fund_")]
    assert second == [], "源库未变更时不应重复上传大库"
    assert "未变更, 跳过" in capsys.readouterr().out


# ── ③ 源库不存在: 不计入分母 ─────────────────────────────────────────────────
def test_missing_public_fund_not_counted_as_failure(repo_dir, monkeypatch, quiet, capsys):
    (repo_dir / "data" / "public_fund.db").unlink()
    fake = FakeS3()
    monkeypatch.setattr(ur, "s3_request", fake)
    monkeypatch.setenv("REPO", str(repo_dir))

    ur.cmd_upload_db()  # 不应 sys.exit(1)
    assert "DB 上传 2/2" in capsys.readouterr().out


# ── ⑧ 上传失败: 非零退出 + 不写台账 ─────────────────────────────────────────
def test_upload_failure_not_recorded_as_backed_up(repo_dir, monkeypatch, quiet):
    fake = FakeS3()
    monkeypatch.setattr(ur, "s3_request", fake)
    monkeypatch.setattr(ur, "_upload_file_to_key", lambda *a, **k: (500, b"boom"))
    monkeypatch.setenv("REPO", str(repo_dir))

    with pytest.raises(SystemExit) as ei:
        ur.cmd_upload_db()
    assert ei.value.code == 1
    state_file = repo_dir / "data" / ur._DB_BACKUP_STATE_FILE
    assert not state_file.exists(), "失败不应写「已备份」台账(否则下一轮误跳过)"


# ── ⑨ 备份期间源库被写: 不记台账 ────────────────────────────────────────────
def test_source_changed_during_backup_not_recorded(repo_dir, monkeypatch, quiet, capsys):
    fake = FakeS3()
    monkeypatch.setattr(ur, "s3_request", fake)
    monkeypatch.setenv("REPO", str(repo_dir))
    real = ur._sqlite_snapshot_to_gz

    def snapshot_then_touch(src_path, dst_gz_path):
        n = real(src_path, dst_gz_path)
        st = os.stat(src_path)
        os.utime(src_path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
        return n

    monkeypatch.setattr(ur, "_sqlite_snapshot_to_gz", snapshot_then_touch)
    ur.cmd_upload_db()

    state_file = repo_dir / "data" / ur._DB_BACKUP_STATE_FILE
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    assert "public_fund.db" not in state, "源库在备份期间变化时不得记「已备份」"
    assert "备份期间源库被写入" in capsys.readouterr().out


# ── ④ 流式分片: 拼回内容 == 原文件 ──────────────────────────────────────────
def test_upload_multipart_file_reads_correct_offsets(tmp_path, monkeypatch):
    payload = bytes(range(256)) * 500  # 128000B
    src = tmp_path / "blob.bin"
    src.write_bytes(payload)

    fake = FakeS3()
    monkeypatch.setattr(ur, "s3_request", fake)
    monkeypatch.setattr(ur, "_MULTIPART_PART_SIZE", 4096)
    monkeypatch.setattr(ur, "_MULTIPART_THRESHOLD", 1024)

    status, _ = ur._upload_file_to_key("backup/big.bin", str(src), "application/octet-stream",
                                       bucket=ur.BACKUP_BUCKET)
    assert status == 200
    parts = fake.objects["backup/big.bin"]
    assert len(parts) == 32  # 128000 / 4096 = 31.25 → 32 片
    rebuilt = b"".join(parts[i] for i in sorted(parts))
    assert rebuilt == payload


# ── ⑤ 内存入口重构后行为不变 ────────────────────────────────────────────────
def test_upload_multipart_bytes_path_unchanged(monkeypatch):
    payload = b"x" * 10000
    fake = FakeS3()
    monkeypatch.setattr(ur, "s3_request", fake)
    monkeypatch.setattr(ur, "_MULTIPART_PART_SIZE", 4096)

    status, _ = ur._upload_multipart("backup/mem.bin", payload, "application/octet-stream")
    assert status == 200
    rebuilt = b"".join(fake.objects["backup/mem.bin"][i]
                       for i in sorted(fake.objects["backup/mem.bin"]))
    assert rebuilt == payload


# ── ⑥ WAL 一致性: 未 checkpoint 的已提交事务必须进快照 ──────────────────────
def test_snapshot_includes_uncheckpointed_wal(tmp_path):
    src = tmp_path / "wal.db"
    writer = sqlite3.connect(str(src))
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    writer.execute("INSERT INTO t (v) VALUES ('committed-in-wal')")
    writer.commit()  # 已提交, 但连接不关 → 数据可能仍在 -wal 里
    try:
        out_gz = tmp_path / "wal.db.gz"
        ur._sqlite_snapshot_to_gz(src, out_gz)
        snap = tmp_path / "restored.db"
        snap.write_bytes(gzip.decompress(out_gz.read_bytes()))
        conn = sqlite3.connect(str(snap))
        try:
            rows = conn.execute("SELECT v FROM t").fetchall()
            assert ("committed-in-wal",) in rows
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            conn.close()
    finally:
        writer.close()


# ── ⑦b 分层清理总入口: 常量结构必须被 _prune_r2_backup 正确消费 ──────────────
def test_prune_r2_backup_consumes_public_fund_retention(monkeypatch):
    """回归: 常量曾是 {"backup/": 7,...}(int),总入口 .items() 崩(2026-10-25 云上首跑实证)。

    这条走真实入口 `_prune_r2_backup(per_name_days=常量)`, 不只测 `_prune_layer`,
    防止「常量结构错但单层测试绿」的假绿。
    """
    now = datetime.now()
    d10 = (now - timedelta(days=10)).strftime("%Y%m%d")
    d30 = (now - timedelta(days=30)).strftime("%Y%m%d")
    d100 = (now - timedelta(days=100)).strftime("%Y%m%d")
    d400 = (now - timedelta(days=400)).strftime("%Y%m%d")
    keys_by_prefix = {
        "backup/": [f"backup/public_fund_{d10}.db.gz", f"backup/sentiment_{d10}.db.gz"],
        "weekly/": [f"weekly/public_fund_{d30}.db.gz", f"weekly/sentiment_{d30}.db.gz"],
        "monthly/": [f"monthly/public_fund_{d100}.db.gz", f"monthly/sentiment_{d400}.db.gz"],
    }
    deleted = []
    monkeypatch.setattr(ur, "_list_keys", lambda prefix, bucket=None: keys_by_prefix[prefix])

    def fake_s3(method, key, payload=b"", query="", bucket=None, **kw):
        assert method == "DELETE"
        deleted.append(key)
        return 204, b""

    monkeypatch.setattr(ur, "s3_request", fake_s3)
    ur._prune_r2_backup(keep_days=14, per_name_days=ur._PUBLIC_FUND_RETENTION_DAYS)

    assert len(deleted) == 4
    assert f"backup/public_fund_{d10}.db.gz" in deleted       # 7 天 → 删
    assert f"backup/sentiment_{d10}.db.gz" not in deleted     # 小库 14 天 → 留
    assert f"weekly/public_fund_{d30}.db.gz" in deleted       # 28 天 → 删(边界同日)
    assert f"weekly/sentiment_{d30}.db.gz" in deleted         # 默认 28 天 → 删
    assert f"monthly/public_fund_{d100}.db.gz" not in deleted  # 180 天 → 留
    assert f"monthly/sentiment_{d400}.db.gz" in deleted       # 365 天 → 删


# ── ⑦ per-name 分层清理 ────────────────────────────────────────────────────
def test_prune_layer_per_name_days(monkeypatch):
    now = datetime.now()
    old_10d = (now - timedelta(days=10)).strftime("%Y%m%d")
    old_20d = (now - timedelta(days=20)).strftime("%Y%m%d")
    keys = [
        f"backup/public_fund_{old_10d}.db.gz",   # 大库保留 7 天 → 删
        f"backup/sentiment_{old_10d}.db.gz",     # 小库保留 14 天 → 留
        f"backup/public_fund_{old_20d}.db.gz",   # 双双超过 → 删
        f"backup/sentiment_{old_20d}.db.gz",
    ]
    deleted = []
    monkeypatch.setattr(ur, "_list_keys", lambda prefix, bucket=None: keys)

    def fake_s3(method, key, payload=b"", query="", bucket=None, **kw):
        if method == "DELETE":
            deleted.append(key)
            return 204, b""
        raise AssertionError(method)

    monkeypatch.setattr(ur, "s3_request", fake_s3)
    ur._prune_layer("backup/", 14, per_name_days={"public_fund": 7})

    assert f"backup/public_fund_{old_10d}.db.gz" in deleted
    assert f"backup/public_fund_{old_20d}.db.gz" in deleted
    assert f"backup/sentiment_{old_10d}.db.gz" not in deleted
    assert f"backup/sentiment_{old_20d}.db.gz" in deleted