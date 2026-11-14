"""backup_state_capture.py 单元用例(备份工作包二, 2026-11-14)。

覆盖任务书「证据用例」1-4(缺项不缩表 / sidecar 变化重试一次 / hash 篡改 FAIL /
secret 类文件不进集合), 外加 upload-state-capture 入口的最小拒绝守卫。
全部走临时目录, 不碰生产数据、不发通知(本模块本身也无通知链路, L48)。
不写死运行日(不 assert 今天日期; 冻结表样例数据用固定历史日期字面量, 与运行日无关, L51)。
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import backup_state_capture as bsc  # noqa: E402

STAMP = "20261113_2100"  # 样例备份戳(历史字面量, 非运行日推导)

SIDE_FILES = [
    "board_etf_map.json", "etf_index_map.json", "etf_track_index.json", "lof_track_index.json",
    "ab_direction_anchor.json", "alert_state.json", "notify_dedup.json", "signal_notified.json",
    "fade_notified.json", "anomaly_notified.json", "nt_signal_notified.json",
    "subscriptions_notified.json", "unit_exit_ledger.json", "brief_ledger.json",
    "brief_push_state.json", "r2_consistency_fail_state.json", "deploy_fail_state.json",
    "public_fund.fof-nav-progress.json", "baostock_progress.json", "mootdx_progress.json",
    "retry_failed_metrics_count.json",
]


def make_repo(tmp_path: Path, *, full: bool = True) -> Path:
    data = tmp_path / "repo" / "data"
    for d in ("alerts", "logs", "ops_delivery/pub", ".r2-protected"):
        (data / d).mkdir(parents=True)
    (data / "signal_kelly_etf_freeze.json").write_text(
        '{"20261110|sh000001|buy":{"code":"510300","frozen_at":"2026-11-10"},'
        '"20261113|sz399001|buy_aux":{"code":"159915","frozen_at":"2026-11-13"}}')
    if full:
        for name in SIDE_FILES:
            (data / name).write_text('{"ok":1}')
        (data / ".r2_index_state.json").write_text('{"ok":1}')
        (data / ".r2_lab_state.json").write_text('{"ok":1}')
        (data / "alerts" / "alert_ledger.jsonl").write_text('{"e":1}\n')
        (data / "logs" / "r2-db-source-x.json").write_text('{"run":1}')
        (data / "ops_delivery" / "pub" / "r.json").write_text('{"r":1}')
        (data / ".r2-protected" / "p.json").write_text('{"p":1}')
        (data / ".r2-protected" / "history").mkdir(parents=True, exist_ok=True)
        (data / ".r2-protected" / "history" / "w1.json").write_text('{"state":"confirmed"}')
        (data / "public_fund.db").write_bytes(b"reference-only")  # 只做源身份引用
    return tmp_path / "repo"


def make_backups(tmp_path: Path) -> Path:
    import sqlite3
    bdir = tmp_path / "backups"
    bdir.mkdir()
    for name in bsc.DB_LEG_NAMES:
        p = bdir / f"{name}_{STAMP}.db"
        con = sqlite3.connect(p)
        con.execute("CREATE TABLE score_daily(date TEXT, score REAL)")
        con.execute("INSERT INTO score_daily VALUES('20261113', 1.0)")
        con.commit()
        con.close()
    return bdir


def run_capture(repo: Path, backup_dir: Path, out_root: Path, with_db_leg=True):
    return bsc.capture(repo, out_root, backup_dir, STAMP, ROOT / "scripts",
                       with_db_leg=with_db_leg)


def test_full_capture_complete(tmp_path):
    repo = make_repo(tmp_path)
    out_root = tmp_path / "capture-sets"
    result = run_capture(repo, make_backups(tmp_path), out_root)
    m = result["manifest"]
    assert result["uploadable"] is True
    assert m["complete"] is True, {"missing": m["missing"], "skipped": m["skipped"],
                                   "verify": m["verification"]["status"]}
    assert m["sidecar_consistency"]["status"] == "consistent"
    # 清单声明先行: 全部声明条目都在 manifest 里(不许缩表)
    assert len(m["declared_inventory"]) == len(bsc.DECLARED_INVENTORY)
    # 声明排除: journal/history 状态 JSON 捕获, payloads 载荷不进集合(捕获前声明, 非事后缩表)
    assert all(e["prefix"] == ".r2-protected/payloads" for e in m["declared_excludes"])
    assert not any(r["rel"].startswith(".r2-protected/payloads/") for r in m["files"])
    assert not (result["set_dir"] / ".r2-protected" / "payloads").exists()
    # DB 腿: 引用而非复制(集合目录里没有任何 .db)
    assert not list(result["set_dir"].glob("*.db"))
    assert all(v["status"] == "ok" and v["integrity_check"] == "ok"
               for k, v in m["db_leg"]["databases"].items() if k in bsc.DB_LEG_NAMES)
    # 冻结表业务日期进入共同业务截止点
    assert m["common_business_cutoff"]["date"] in ("20261113", "2026-11-13")


def test_missing_recorded_not_shrunk(tmp_path):
    """证据用例1: 清单声明含缺失项 ⇒ manifest 记 missing 且整体判不完整(不静默缩表)。"""
    repo = make_repo(tmp_path, full=False)  # 只留冻结表, 其余全缺
    out_root = tmp_path / "capture-sets"
    result = run_capture(repo, make_backups(tmp_path), out_root)
    m = result["manifest"]
    assert m["complete"] is False
    assert m["missing"], "缺文件必须如实记 missing"
    missing_rels = {x.get("rel") or x.get("pattern") for x in m["missing"]}
    # 抽查若干声明条目缺了就出现在 missing(SIDE_FILES 抽前几个 + 空目录类)
    for rel in ("alert_state.json", "etf_track_index.json", "notify_dedup.json",
                ".r2_*_state.json", ".r2-protected"):
        assert rel in missing_rels, f"缺失声明项 {rel} 未记录"
    # 声明清单没有被缩小
    assert len(m["declared_inventory"]) == len(bsc.DECLARED_INVENTORY)
    assert result["uploadable"] is True  # 可上传但如实标不完整


def test_sidecar_changed_retry_once_then_ok(tmp_path):
    """证据用例2a: sidecar 捕获中被修改(仅第一次) ⇒ 重试一次后成功, retries=1。"""
    repo = make_repo(tmp_path)
    out_root = tmp_path / "capture-sets"
    orig = bsc.read_stable
    calls = {"n": 0}

    def flaky(path, max_bytes=64 << 20):
        payload, before = orig(path, max_bytes)
        if path.name == "alert_state.json":
            calls["n"] += 1
            if calls["n"] == 1:
                path.write_text('{"changed":1}')  # 读后改 ⇒ finalize 复查必不一致
        return payload, before

    bsc.read_stable = flaky
    try:
        result = run_capture(repo, make_backups(tmp_path), out_root)
    finally:
        bsc.read_stable = orig
    m = result["manifest"]
    assert calls["n"] == 2
    assert m["status"] == "captured"
    assert m["sidecar_consistency"] == {"checks": ["read_pre_post_stat", "finalize_stat_and_sha256"],
                                        "retries": 1, "status": "consistent"}
    # 重试后拿到的是修改后的内容(集合内与源逐位一致)
    src_hash = bsc.sha256_file(repo / "data" / "alert_state.json")
    rec = next(r for r in m["files"] if r["rel"] == "alert_state.json")
    assert rec["sha256"] == src_hash


def test_sidecar_keeps_changing_marks_inconsistent(tmp_path):
    """证据用例2b: 重试一次仍变 ⇒ 记 inconsistent, 拒绝宣称完整(不可上传)。"""
    repo = make_repo(tmp_path)
    out_root = tmp_path / "capture-sets"
    orig = bsc.read_stable
    calls = {"n": 0}

    def always(path, max_bytes=64 << 20):
        payload, before = orig(path, max_bytes)
        if path.name == "alert_state.json":
            calls["n"] += 1
            path.write_text('{"changed":%d}' % calls["n"])
        return payload, before

    bsc.read_stable = always
    try:
        result = run_capture(repo, make_backups(tmp_path), out_root, with_db_leg=False)
    finally:
        bsc.read_stable = orig
    assert calls["n"] == 2  # 恰好两次尝试(整体重试一次, 不是无限重试)
    m = result["manifest"]
    assert m["status"] == "inconsistent"
    assert m["reason"] == "sidecar_changed_across_capture_after_one_retry"
    assert result["uploadable"] is False
    assert result["set_dir"] is None
    # 不宣称完整: manifest 无 complete=true 字段
    assert "complete" not in m


def test_hash_tamper_fails_verification(tmp_path):
    """证据用例3: 集合内文件被篡改 ⇒ 自校验 FAIL。"""
    repo = make_repo(tmp_path)
    out_root = tmp_path / "capture-sets"
    result = run_capture(repo, make_backups(tmp_path), out_root)
    set_dir = result["set_dir"]
    # 篡改一个集合内文件(同长度改内容, 防 size 兜底)
    target = set_dir / "notify_dedup.json"
    target.write_text('{"ok":2}')
    v = bsc.verify_set(set_dir, result["manifest"])
    assert v["status"] == "fail"
    assert any(c["rel"] == "notify_dedup.json" and c["result"] == "fail"
               for c in v["checks"])


def test_secret_files_not_in_capture_set(tmp_path):
    """证据用例4: .env/token/PID 类文件与私钥内容不进捕获集合(记录原因, 不静默)。"""
    repo = make_repo(tmp_path)
    data = repo / "data"
    (data / "alerts" / ".env").write_text("SECRET=1\n")
    (data / "alerts" / "daemon.pid").write_text("12345\n")
    (data / "alerts" / "upload.lock").write_text("x")
    (data / ".r2_token_state.json").write_text('{"k":1}')  # 名含 token
    (data / "ops_delivery" / "pub" / "creds.pem").write_text("x")
    (data / "board_etf_map.json").write_text(
        "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----\n")  # 内容嗅探
    out_root = tmp_path / "capture-sets"
    result = run_capture(repo, make_backups(tmp_path), out_root)
    m = result["manifest"]
    set_dir = result["set_dir"]
    captured_rels = {r["rel"] for r in m["files"]}
    for rel in ("alerts/.env", "alerts/daemon.pid", "alerts/upload.lock",
                ".r2_token_state.json", "ops_delivery/pub/creds.pem", "board_etf_map.json"):
        assert rel not in captured_rels, f"{rel} 不应进捕获集合"
        assert not (set_dir / rel).exists(), f"{rel} 不应存在于集合目录"
    skipped_rels = {s["rel"] for s in m["skipped"]}
    for rel in ("alerts/.env", "alerts/daemon.pid", ".r2_token_state.json"):
        assert rel in skipped_rels
    assert any(s["reason"] == "secret_content_pattern" for s in m["skipped"])
    assert m["complete"] is False  # 有声明项被排除 ⇒ 如实不完整


def test_payloads_declared_excluded_but_journal_captured(tmp_path):
    """声明排除用例: .r2-protected/payloads 载荷(内容寻址, 预算 1.21GB/日)不进集合,
    journal/history 状态 JSON 全量捕获; 排除随清单同时声明(manifest.declared_excludes),
    不算 missing、不影响 complete(捕获前声明, 非发现缺文件后缩表)。"""
    repo = make_repo(tmp_path)
    payloads = repo / "data" / ".r2-protected" / "payloads"
    payloads.mkdir(parents=True)
    (payloads / ("a" * 64)).write_text('{"payload":1}')  # sha256 命名载荷
    out_root = tmp_path / "capture-sets"
    result = run_capture(repo, make_backups(tmp_path), out_root)
    m = result["manifest"]
    rels = {r["rel"] for r in m["files"]}
    assert not any(r.startswith(".r2-protected/payloads/") for r in rels)
    assert ".r2-protected/p.json" in rels and ".r2-protected/history/w1.json" in rels
    assert any(e["prefix"] == ".r2-protected/payloads" for e in m["declared_excludes"])
    # 排除不是缺口: complete 仍为 True(其余清单全捕获)
    assert m["complete"] is True
    assert not any(x.get("rel", "").startswith(".r2-protected/payloads") for x in m["missing"])


def test_transient_lock_skipped_but_not_incomplete(tmp_path):
    """瞬态锁记账: .lock 事务锁(云上 ops_delivery 实测 292 个)按设计排除, 记
    transient_lock_by_design, 不算缺口 ⇒ complete 不因锁文件变 False。"""
    repo = make_repo(tmp_path)
    (repo / "data" / "ops_delivery" / "pub" / ".abc123.lock").write_text("x")
    out_root = tmp_path / "capture-sets"
    result = run_capture(repo, make_backups(tmp_path), out_root)
    m = result["manifest"]
    skips = {s["rel"]: s["reason"] for s in m["skipped"]}
    assert skips.get("ops_delivery/pub/.abc123.lock") == "transient_lock_by_design"
    assert m["complete"] is True, {"skipped": m["skipped"], "missing": m["missing"]}
    assert not (result["set_dir"] / "ops_delivery/pub/.abc123.lock").exists()


def test_is_forbidden_name_unit():
    for name in (".env", ".env.production", "foo.pem", "foo.key", "foo.pid",
                 "x.sock", "y.lock", "id_rsa", "credentials", "my_token.json"):
        assert bsc.is_forbidden_name(name), name
    for name in (".env", ".env.production", "foo.pem", "foo.key", "foo.pid",
                 "x.sock", "y.lock", "id_rsa", "credentials", "my_token.json"):
        assert bsc.is_forbidden_name(name), name
    for name in ("alert_state.json", ".r2_index_state.json", "brief_ledger.json",
                 "notify_dedup.json", "signal_kelly_etf_freeze.json"):
        assert not bsc.is_forbidden_name(name), name


def test_upload_state_capture_rejects_non_set_dir(tmp_path):
    """upload-state-capture 最小守卫: 非集合目录(无 manifest)拒绝, 不触网。"""
    import upload_r2 as ur
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(SystemExit):
        ur.cmd_upload_state_capture(str(plain))
    fake = tmp_path / "fake-set"
    fake.mkdir()
    (fake / "manifest.json").write_text('{"schema":"other"}')
    with pytest.raises(SystemExit):
        ur.cmd_upload_state_capture(str(fake))
    # uploadable=false 的集合同样拒绝(不完整集合不上 R2 归档为「完整集合」)
    not_uploadable = tmp_path / "not-uploadable"
    not_uploadable.mkdir()
    (not_uploadable / "manifest.json").write_text(
        json.dumps({"schema": "trade-state-capture-v1", "uploadable": False, "status": "inconsistent"}))
    with pytest.raises(SystemExit):
        ur.cmd_upload_state_capture(str(not_uploadable))
