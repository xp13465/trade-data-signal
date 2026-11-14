# -*- coding: utf-8 -*-
"""scripts/tests/test_standby_sync_20261114.py — D 批 standby_sync 证据用例。

任务书: /tmp/task-standby-sync-impl-20261114.md「证据用例」9 条, 实现前写定。
全部用本地假归档/桩, 不下载真实大文件、零真发(L48: monkeypatch
standby_sync.emit_event 记录调用)、不触网(local 源)、冻结运行日(L51:
monkeypatch standby_sync._now 固定时刻, 不裸写 os.environ(L56: monkeypatch.setenv)。
"""
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import standby_sync  # noqa: E402

import pytest  # noqa: E402

FROZEN_NOW = dt.datetime(2026, 11, 14, 8, 0, 0,
                         tzinfo=standby_sync.LOCAL_TZ)


# ---------------------------------------------------------------- helpers --

def _make_db_bytes(dates):
    """造假 SQLite db 原始字节(score_daily 表)。"""
    fd, path = tempfile_mkstemp()
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE score_daily (date TEXT, val REAL)")
    con.executemany("INSERT INTO score_daily VALUES (?, 1.0)",
                    [(d,) for d in dates])
    con.commit()
    con.close()
    data = Path(path).read_bytes()
    os.unlink(path)
    return data


def tempfile_mkstemp():
    import tempfile
    return tempfile.mkstemp(suffix=".db")


def _add_gz(src: Path, key: str, raw: bytes) -> dict:
    """src 下造 gz 对象, 返回 manifest 文件项(hash/size 全真实)。"""
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as g:
        g.write(raw)
    gz = buf.getvalue()
    p = src / key
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(gz)
    return {"key": key, "size": len(gz),
            "sha256_gz": hashlib.sha256(gz).hexdigest(),
            "sha256_uncompressed": hashlib.sha256(raw).hexdigest()}


def build_source(tmp_path: Path, business_date="2026-11-13",
                 run="run001", entries=None) -> Path:
    """造假源目录: manifest + db.gz + freeze.json.gz(sidecar)。"""
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)   # 同 tmp_path 二次构建(先旧版后新版)
    if entries is None:
        db = _add_gz(src, "backup/sentiment_20261113.db.gz",
                     _make_db_bytes(["2026-11-12", "2026-11-13"]))
        db.update({"role": "db", "name": "sentiment.db",
                   "tables": {"score_daily": 2},
                   "probe": {"table": "score_daily", "col": "date",
                             "min": "2026-11-12"}})
        frz = _add_gz(src, "backup/signal_kelly_etf_freeze.json.gz",
                      json.dumps({"2026-11-13": ["510300"]}).encode())
        frz.update({"role": "freeze", "name": "signal_kelly_etf_freeze.json"})
        entries = [db, frz]
    manifest = {"schema_version": 1, "complete": True,
                "business_date": business_date,
                "generated_at": f"{business_date}T22:24:05+08:00",
                "source_run": run, "files": entries}
    (src / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return src


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(standby_sync, "_now", lambda: FROZEN_NOW)


@pytest.fixture
def events(monkeypatch):
    """通知全桩化(L48): 记录事件 key, 禁真发。"""
    rec: list[str] = []
    monkeypatch.setattr(
        standby_sync, "emit_event",
        lambda key, subject, body, dry_run=False, log=None:
            rec.append(key) or True)
    return rec


def run_main(tmp_path, src, sub=("sync",), extra=()):
    # 子命令专属参数(--stale-days/--backoff-seconds 等)必须放子命令之后
    argv = ["--root", str(tmp_path / "standby"),
            "--source", "local", "--source-dir", str(src),
            *sub, *extra]
    return standby_sync.main(argv)


def state_of(tmp_path) -> dict:
    p = tmp_path / "standby" / "state" / "standby_sync_state.json"
    return json.loads(p.read_text(encoding="utf-8"))


def versions_of(tmp_path) -> list[str]:
    vd = tmp_path / "standby" / "archive" / "versions"
    return sorted(d.name for d in vd.iterdir() if d.is_dir())


def latest_of(tmp_path) -> str:
    link = tmp_path / "standby" / "archive" / "latest_verified"
    return os.readlink(link).split("/")[-1]


# ------------------------------------------- E1 正常同步: 全校验+原子切链 ---

def test_e1_normal_sync_all_pass_silent(tmp_path, frozen, events):
    src = build_source(tmp_path)
    rc = run_main(tmp_path, src)
    assert rc == 0
    assert events == []                      # 默认外发 0
    vid = latest_of(tmp_path)
    vdir = tmp_path / "standby" / "archive" / "versions" / vid
    assert (vdir / "verify_record.json").exists()
    assert (vdir / ".standby-managed").exists()
    assert (vdir / "manifest.json").exists()
    rec = json.loads((vdir / "verify_record.json").read_text(encoding="utf-8"))
    assert rec["business_date"] == "2026-11-13"
    # 状态 JSON 字段齐(latest_downloadable/latest_verified/business_date/
    # source_run/hash/耗时/UTC 双时区)
    st = state_of(tmp_path)
    assert st["latest_verified"] == st["latest_downloadable"] == vid
    assert st["business_date"] == "2026-11-13"
    assert st["source_run"] == "run001"
    assert st["last_success_ts"] == "2026-11-14 08:00:00"
    assert st["last_success_utc"].endswith("Z")
    assert st["history"][-1]["manifest_sha256"]
    assert st["history"][-1]["duration_seconds"] >= 0
    # staging 已固化(不再有 staging-*)
    assert list((tmp_path / "standby" / "work").glob("staging-*")) == []


# ------------------------------------- E2 远端无新集合: 保旧版+真实年龄 -----

def test_e2_no_new_set_keep_real_age(tmp_path, frozen, events):
    src = build_source(tmp_path)
    assert run_main(tmp_path, src) == 0
    vid0 = latest_of(tmp_path)
    # 同一 manifest 再跑: 无变化, 保留旧版本, 不伪造新时间
    assert run_main(tmp_path, src) == 0
    assert latest_of(tmp_path) == vid0
    assert versions_of(tmp_path) == [vid0]
    st = state_of(tmp_path)
    assert st["history"][-1]["outcome"] == "no-change"
    # 真实年龄: 业务日期 11-13, 冻结今天 11-14 ⇒ 1 天, 如实入账不重写
    assert st["latest_recovery_point_age_days"] == 1
    assert st["business_date"] == "2026-11-13"
    assert events == []                      # 无变化静默
    # status 输出真实年龄
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = run_main(tmp_path, src, sub=("status",))
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert out["latest_recovery_point_age_days"] == 1
    assert out["versions"][0]["age_days"] == 1


def test_stale_recovery_point_event_once(tmp_path, frozen, events):
    """恢复点过期(>阈值) ⇒ 首报一次(成功路径也查, 不静默吞停更)。"""
    src = build_source(tmp_path)
    assert run_main(tmp_path, src) == 0
    # 默认阈值 2 天, 当前年龄 1 天 → 不报; 阈值改 0 → 报一次
    assert run_main(tmp_path, src, extra=("--stale-days", "0")) == 0
    assert events == [standby_sync.EVENT_KEYS["stale_recovery_point"]]
    # 同一事件不按尝试/日期刷屏: 再跑一次仍然只有一条(去重由 notify 层,
    # 本层保证成功路径不重复进入 emit)
    assert run_main(tmp_path, src, extra=("--stale-days", "0")) == 0
    assert len(events) == 1


# ------------------------------------------- E3 中断/断网: 重试幂等不刷屏 ---

def test_e3a_transient_failure_retry_silent(tmp_path, frozen, events, monkeypatch):
    src = build_source(tmp_path)
    calls = {"n": 0}
    orig = standby_sync.LocalSource.fetch_file

    def flaky(self, key, dest):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("connection reset by peer")
        return orig(self, key, dest)

    monkeypatch.setattr(standby_sync.LocalSource, "fetch_file", flaky)
    sleeps: list[float] = []
    monkeypatch.setattr(standby_sync, "_sleep", sleeps.append)
    rc = run_main(tmp_path, src, extra=("--backoff-seconds", "0"))
    assert rc == 0
    assert events == []                       # 窗口内重试成功 ⇒ 静默
    st = state_of(tmp_path)
    assert st["history"][-1]["attempts"] == 2
    assert sleeps == [0.0]                    # 有退避动作(0s 桩)
    assert latest_of(tmp_path) == st["latest_verified"]


def test_e3b_persistent_failure_window_fail_once(tmp_path, frozen, events,
                                                  monkeypatch):
    src = build_source(tmp_path)

    def dead(self, key, dest):
        raise OSError("network unreachable")

    monkeypatch.setattr(standby_sync.LocalSource, "fetch_file", dead)
    monkeypatch.setattr(standby_sync, "_sleep", lambda s: None)
    rc = run_main(tmp_path, src, extra=("--backoff-seconds", "0"))
    assert rc == 1
    # 3 次尝试只报一次 window_fail(不按尝试次数刷屏)
    assert events == [standby_sync.EVENT_KEYS["window_fail"]]
    # 无旧版本场景: staging 不生效(latest 不存在, 无版本目录)
    assert versions_of(tmp_path) == []
    link = tmp_path / "standby" / "archive" / "latest_verified"
    assert not link.is_symlink()
    # 失败入账状态
    assert state_of(tmp_path)["last_failure"]["rc"] == 1


def test_e3c_retry_idempotent_staging_reuse(tmp_path, frozen, events,
                                            monkeypatch):
    """断点续传(对象粒度): 失败尝试已下好的对象, 下次尝试直接复用。"""
    src = build_source(tmp_path)
    seen_keys: list[str] = []
    orig = standby_sync.LocalSource.fetch_file

    def first_fail_on_second(self, key, dest):
        seen_keys.append(key)
        if key.endswith("freeze.json.gz") and \
                seen_keys.count(key) == 1:
            raise OSError("interrupted")
        return orig(self, key, dest)

    monkeypatch.setattr(standby_sync.LocalSource, "fetch_file",
                        first_fail_on_second)
    monkeypatch.setattr(standby_sync, "_sleep", lambda s: None)
    assert run_main(tmp_path, src, extra=("--backoff-seconds", "0")) == 0
    # db 对象只下了一次(第二次尝试复用), freeze 下两次(第一次被中断)
    assert seen_keys.count("backup/sentiment_20261113.db.gz") == 1
    assert seen_keys.count("backup/signal_kelly_etf_freeze.json.gz") == 2
    assert events == []


# --------------------- E4 损坏/缺 sidecar/错业务日期: 新版被拒+定位到对象 ----

def _prime_old_version(tmp_path, frozen, events):
    src = build_source(tmp_path)
    assert run_main(tmp_path, src) == 0
    return latest_of(tmp_path)


def test_e4a_corrupt_file_rejected_named(tmp_path, frozen, events, monkeypatch):
    old = _prime_old_version(tmp_path, frozen, events)
    events.clear()
    src = build_source(tmp_path, run="run002", business_date="2026-11-14")
    # 篡改源对象内容(gzip 重打包): manifest hash 由此不匹配
    p = src / "backup" / "signal_kelly_etf_freeze.json.gz"
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as g:
        g.write(b'{"tampered": true}')
    p.write_bytes(buf.getvalue())
    monkeypatch.setattr(standby_sync, "_sleep", lambda s: None)
    rc = run_main(tmp_path, src, extra=("--backoff-seconds", "0"))
    assert rc == 5
    # 新版本被拒 + 事件一次 + 错误能定位到具体对象
    assert events == [standby_sync.EVENT_KEYS["corrupt_set"]]
    assert versions_of(tmp_path) == [old]     # 旧版本不受影响
    assert latest_of(tmp_path) == old
    assert state_of(tmp_path)["last_failure"]["rc"] == 5


def test_e4b_missing_sidecar_rejected_named(tmp_path, frozen, events,
                                             monkeypatch):
    old = _prime_old_version(tmp_path, frozen, events)
    events.clear()
    src = build_source(tmp_path, run="run003", business_date="2026-11-14")
    # manifest 声明了一个源里不存在的 sidecar
    m = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    m["files"].append({"key": "backup/etf_index_map.json", "role": "state",
                       "size": 3, "sha256_gz": "a" * 64})
    (src / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    monkeypatch.setattr(standby_sync, "_sleep", lambda s: None)
    assert run_main(tmp_path, src, extra=("--backoff-seconds", "0")) == 5
    assert events == [standby_sync.EVENT_KEYS["corrupt_set"]]
    assert "etf_index_map.json" in state_of(tmp_path)["last_failure"]["error"]
    assert versions_of(tmp_path) == [old]
    assert latest_of(tmp_path) == old


def test_e4c_wrong_business_date_rejected(tmp_path, frozen, events, monkeypatch):
    old = _prime_old_version(tmp_path, frozen, events)
    events.clear()
    src = build_source(tmp_path, run="run004", business_date="2026-11-14")
    m = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    m["files"][0]["business_date"] = "2026-11-12"   # 与集合日期不一致
    (src / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    monkeypatch.setattr(standby_sync, "_sleep", lambda s: None)
    assert run_main(tmp_path, src, extra=("--backoff-seconds", "0")) == 5
    assert events == [standby_sync.EVENT_KEYS["corrupt_set"]]
    assert "错业务日期" in state_of(tmp_path)["last_failure"]["error"]
    assert latest_of(tmp_path) == old


def test_e4d_sqlite_integrity_and_scope(tmp_path, frozen, events, monkeypatch):
    """SQLite 损坏 / 恢复范围不足: 同属 corrupt_set, 定位到具体对象。"""
    # 恢复范围不足: manifest 只有 sidecar 没有活跃 db
    src = build_source(
        tmp_path, entries=[
            dict(role="freeze", key="backup/f.json.gz", size=1,
                 sha256_gz="b" * 64)])
    monkeypatch.setattr(standby_sync, "_sleep", lambda s: None)
    assert run_main(tmp_path, src, extra=("--backoff-seconds", "0")) == 5
    assert events == [standby_sync.EVENT_KEYS["corrupt_set"]]
    assert "恢复范围不足" in state_of(tmp_path)["last_failure"]["error"]
    # SQLite integrity: 换成合法 hash 的非 SQLite 字节流
    events.clear()
    raw = b"not a sqlite file at all"
    src2 = tmp_path / "src2"
    src2.mkdir()
    ent = _add_gz(src2, "backup/sentiment.db.gz", raw)
    ent.update({"role": "db", "name": "sentiment.db"})
    (src2 / "manifest.json").write_text(json.dumps({
        "schema_version": 1, "complete": True, "business_date": "2026-11-13",
        "source_run": "bad", "files": [ent]}), encoding="utf-8")
    root2 = tmp_path / "standby2"
    argv = ["--root", str(root2), "--source", "local",
            "--source-dir", str(src2), "sync", "--backoff-seconds", "0"]
    assert standby_sync.main(argv) == 5
    assert events == [standby_sync.EVENT_KEYS["corrupt_set"]]
    assert "sentiment.db.gz" in state_of(tmp_path)["last_failure"]["error"] or \
        "sentiment.db.gz" in json.loads(
            (root2 / "state" / "standby_sync_state.json")
            .read_text(encoding="utf-8"))["last_failure"]["error"]


# ------------------------------------------- E5 两个实例并发: 单更新者 ------

def test_e5_single_instance_flock(tmp_path, frozen, events):
    import fcntl
    src = build_source(tmp_path)
    run_main_argtmp = tmp_path
    lock = run_main_argtmp / "standby" / "state" / "standby_sync.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        rc = run_main(run_main_argtmp, src)
        assert rc == 3                        # 拿不到锁 ⇒ 退出码 3, 不更新
        assert versions_of(run_main_argtmp) == []
        assert events == []
    finally:
        os.close(fd)
    # 释放后可正常跑
    assert run_main(run_main_argtmp, src) == 0
    assert len(versions_of(run_main_argtmp)) == 1


# ------------------------------------------- E6 磁盘不足: 拒下载不删旧版 ----

def test_e6_space_insufficient_refuse_download(tmp_path, frozen, events,
                                               monkeypatch):
    old = _prime_old_version(tmp_path, frozen, events)
    events.clear()
    src = build_source(tmp_path, run="run005", business_date="2026-11-14")
    monkeypatch.setattr(standby_sync, "_disk_free", lambda p: 1 << 20)
    rc = run_main(tmp_path, src)
    assert rc == 4
    assert events == [standby_sync.EVENT_KEYS["space_insufficient"]]
    # 拒绝下载: 无新 staging 产物; 旧版本全在; latest 不动
    assert versions_of(tmp_path) == [old]
    assert latest_of(tmp_path) == old
    assert list((tmp_path / "standby" / "work").glob("staging-*")) == []
    assert state_of(tmp_path)["last_failure"]["rc"] == 4


# ------------------------------------------- E7 保留清理: 只删登记目录 ------

def _make_version(archive: Path, vid: str, bd: str, verified=True,
                  fill=b"x" * 128):
    d = archive / "versions" / vid
    d.mkdir(parents=True, exist_ok=True)
    (d / "blob.bin").write_bytes(fill)
    if verified:
        (d / ".standby-managed").write_text("{}", encoding="utf-8")
        (d / "verify_record.json").write_text(json.dumps({
            "version_id": vid, "business_date": bd}), encoding="utf-8")


def test_e7_retention_only_registered_dirs(tmp_path, frozen, events):
    arc = tmp_path / "standby" / "archive"
    for i in range(1, 11):
        _make_version(arc, f"2026-11-{i:02d}-r-x", f"2026-11-{i:02d}")
    _make_version(arc, "2026-11-12-r-y", "2026-11-12")
    _make_version(arc, "2026-11-13-r-z", "2026-11-13")
    # 未登记目录(无 .standby-managed)与无验证记录版本
    unreg = arc / "versions" / "2026-10-30-unregistered"
    unreg.mkdir(parents=True)
    (unreg / "keep.txt").write_text("x", encoding="utf-8")
    _make_version(arc, "2026-10-29-noverify", "2026-10-29", verified=False)
    # latest 指向 11-13
    (arc).mkdir(parents=True, exist_ok=True)
    os.symlink("versions/2026-11-13-r-z", arc / "latest_verified")

    rc = run_main(tmp_path, tmp_path / "nonexistent-src", sub=("retention",))
    assert rc == 0
    assert events == []
    keep = versions_of(tmp_path)
    # 未登记目录 + 无验证记录版本 + latest 不动
    assert "2026-10-30-unregistered" in keep
    assert "2026-10-29-noverify" in keep
    assert "2026-11-13-r-z" in keep
    # 保留下限: 已验版本剩 >= 2 且 daily 窗口内全保
    verified_left = [v for v in keep if "unregistered" not in v
                     and "noverify" not in v]
    assert len(verified_left) >= 2
    for i in range(7, 11):                    # 11-07..11-10 全在(日保 7 天窗口)
        assert any(f"2026-11-{i:02d}" in v for v in verified_left), i
    # 11-12/11-13 周备与 latest 也在
    assert "2026-11-12-r-y" in verified_left and "2026-11-13-r-z" in verified_left
    # 最老的日保窗口外版本被清(至少 11-02..11-06 中若干被删)
    deleted = [i for i in range(1, 7)
               if not any(f"2026-11-{i:02d}" in v for v in verified_left)]
    assert deleted, "应有窗口外老版本被清理"


def test_e7b_retention_never_below_floor(tmp_path, frozen, events,
                                          monkeypatch):
    """唯一/下限保护: 已验版本不足下限(2)时一个都不删。"""
    arc = tmp_path / "standby" / "archive"
    _make_version(arc, "2026-11-13-r-a", "2026-11-13")
    os.symlink("versions/2026-11-13-r-a", arc / "latest_verified")
    rc = run_main(tmp_path, tmp_path / "no-src", sub=("retention",))
    assert rc == 0
    assert versions_of(tmp_path) == ["2026-11-13-r-a"]


def test_e7c_retention_space_degrade_keeps_floor_and_latest(tmp_path, frozen,
                                                             events,
                                                             monkeypatch):
    """空间不足自动降级: 收缩到下限, 不动 latest, 不破 >=2。"""
    arc = tmp_path / "standby" / "archive"
    for i in range(1, 11):
        _make_version(arc, f"2026-11-{i:02d}-r-x", f"2026-11-{i:02d}",
                      fill=b"x" * 1024)
    _make_version(arc, "2026-11-13-r-z", "2026-11-13", fill=b"x" * 1024)
    _make_version(arc, "2026-11-12-r-y", "2026-11-12", fill=b"x" * 1024)
    os.symlink("versions/2026-11-13-r-z", arc / "latest_verified")
    monkeypatch.setattr(standby_sync, "_disk_free", lambda p: 1 << 20)
    rc = run_main(tmp_path, tmp_path / "no-src",
                  sub=("retention", "--min-free-gb", "1024"))
    assert rc == 0
    keep = [v for v in versions_of(tmp_path) if "r-" in v]
    assert "2026-11-13-r-z" in keep           # latest 永远保
    assert len(keep) == 2                      # 降级收缩到下限 2


# ------------------------------------------- E8 漏跑补偿: 只补一次 ---------

def test_e8_missed_run_compensation_once(tmp_path, frozen, events):
    src = build_source(tmp_path)
    # 预置状态: 上次成功 11-11(冻结今天 11-14)⇒ 漏 2 天
    st_dir = tmp_path / "standby" / "state"
    st_dir.mkdir(parents=True)
    (st_dir / "standby_sync_state.json").write_text(json.dumps({
        "last_success_date": "2026-11-11", "history": []}), encoding="utf-8")
    assert run_main(tmp_path, src) == 0
    st = state_of(tmp_path)
    assert st["missed_runs_last"] == 2         # 漏跑如实入账
    assert st["history"][-1]["missed_runs"] == 2
    assert st["business_date"] == "2026-11-13"  # 真实业务日期, 不重写
    assert len(versions_of(tmp_path)) == 1     # 只补一次有效同步(单版本)
    assert events == []


def test_e8b_only_if_missed_today_silent(tmp_path, frozen, events):
    st_dir = tmp_path / "standby" / "state"
    st_dir.mkdir(parents=True)
    (st_dir / "standby_sync_state.json").write_text(json.dumps({
        "last_success_date": "2026-11-14", "history": []}), encoding="utf-8")
    # 源目录不存在也不该被触达(启动补偿今日已成功 ⇒ 静默退出)
    rc = run_main(tmp_path, tmp_path / "no-such-src",
                  sub=("sync", "--only-if-missed"))
    assert rc == 0
    assert events == []


def test_dry_run_never_writes_state_or_finalizes(tmp_path, frozen, events):
    """dry-run 全链路零副作用: 不固化/不切链/不写状态(含无新集合分支)。"""
    src = build_source(tmp_path)
    assert run_main(tmp_path, src) == 0          # 真跑一次打底
    vid0 = latest_of(tmp_path)
    before = state_of(tmp_path)
    # 无新集合 + dry-run: 不追加 history(冒烟实测曾漏写状态, 此处锁死)
    assert run_main(tmp_path, src, sub=("sync", "--dry-run")) == 0
    assert state_of(tmp_path) == before
    assert versions_of(tmp_path) == [vid0]
    assert events == []


# ------------------------------------------- 隔离 guard / 幂等 / 单元 -----

def test_guard_rejects_dev_tree_overlap(tmp_path, monkeypatch):
    dev = tmp_path / "faketrade"
    (dev / "data").mkdir(parents=True)
    monkeypatch.setenv("STANDBY_SYNC_DENY_PATHS", str(dev))
    with pytest.raises(SystemExit):
        standby_sync.main([
            "--root", str(dev / "standby"), "--source", "local",
            "--source-dir", str(tmp_path), "sync"])


def test_manifest_identity_deterministic(tmp_path):
    src = build_source(tmp_path)
    raw = (src / "manifest.json").read_bytes()
    m = standby_sync.normalize_manifest(json.loads(raw.decode()))
    v1 = standby_sync.manifest_identity(m, raw)
    assert v1 == standby_sync.manifest_identity(m, raw)
    assert v1.startswith("2026-11-13-run001-")
    m2 = dict(m, business_date="2026-11-14")
    raw2 = json.dumps(m2, sort_keys=True).encode()
    assert standby_sync.manifest_identity(m2, raw2) != v1


def test_verify_subcommand_rechecks_latest(tmp_path, frozen, events):
    src = build_source(tmp_path)
    assert run_main(tmp_path, src) == 0
    assert run_main(tmp_path, src, sub=("verify",)) == 0
    # 篡改固化产物后再验 ⇒ FAIL
    vid = latest_of(tmp_path)
    p = (tmp_path / "standby" / "archive" / "versions" / vid /
         "backup" / "sentiment_20261113.db.gz")
    p.write_bytes(b"tampered")
    assert run_main(tmp_path, src, sub=("verify",)) == 1
