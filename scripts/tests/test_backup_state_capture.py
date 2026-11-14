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
# 样例文件 mtime 固定成历史时点(否则 mtime 兜底业务日期随运行日漂移, 违反 L51 冻结运行日)。
FIXTURE_MTIME = __import__("time").mktime((2026, 11, 13, 15, 0, 0, 0, 0, -1))

SIDE_FILES = [
    "board_etf_map.json", "etf_index_map.json", "etf_track_index.json", "lof_track_index.json",
    "ab_direction_anchor.json", "alert_state.json", "notify_dedup.json", "signal_notified.json",
    "fade_notified.json", "anomaly_notified.json", "nt_signal_notified.json",
    "subscriptions_notified.json", "unit_exit_ledger.json", "brief_ledger.json",
    "brief_push_state.json", "r2_consistency_fail_state.json", "deploy_fail_state.json",
    "staticdata_backup_heartbeat.json",
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
    # 固定样例 mtime(历史时点), 让 mtime 兜底业务日期确定、不随运行日漂移。
    import os
    for p in sorted((tmp_path / "repo").rglob("*"), reverse=True):
        os.utime(p, (FIXTURE_MTIME, FIXTURE_MTIME))
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
    assert any(e["prefix"] == ".r2-protected/payloads" for e in m["declared_excludes"])
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

    def flaky(path, max_bytes=None):
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

    def always(path, max_bytes=None):
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


def test_f4_sidecar_missing_alone_marks_incomplete(tmp_path):
    """F4 独立锚(2026-11-14 审查): 其它全在位、只缺一个 sidecar ⇒ complete=False 且该文件
    记 missing。变异「complete 判定去掉 missing 子句」后本用例必须变红(旧用例由
    public_fund.db 缺失连带撑起, 无法独立锚住)。"""
    repo = make_repo(tmp_path)
    (repo / "data" / "notify_dedup.json").unlink()
    result = run_capture(repo, make_backups(tmp_path), tmp_path / "capture-sets")
    m = result["manifest"]
    assert [x for x in m["missing"] if x.get("rel") == "notify_dedup.json"]
    # 其余维度都干净 ⇒ False 只可能来自这条 missing(独立锚成立的前提)
    assert m["verification"]["status"] == "pass"
    assert not m["budget_excluded"]
    assert all(v.get("status") == "ok" and v.get("integrity_check") == "ok"
               for k, v in m["db_leg"]["databases"].items() if k in bsc.DB_LEG_NAMES)
    assert not [s for s in m["skipped"] if s["reason"] != "transient_lock_by_design"]
    assert m["complete"] is False


def test_f1_out_root_independent_from_c4_capture_sets(tmp_path):
    """F1(2026-11-14 审查): 默认出根 state-capture-sets 与 C4 的 capture-sets 分离,
    两开关同开不干扰; 集合目录名非纯 UUID(同根会让 C4 capture_admission 抛
    unaccounted_capture_entry); backup_db.sh 接线同批落地(F1 + F3 参数)。"""
    import uuid
    repo = make_repo(tmp_path)
    backup_dir = make_backups(tmp_path)
    out_root = bsc.default_out_root(backup_dir)
    assert out_root == backup_dir / "state-capture-sets"
    assert out_root != backup_dir / "capture-sets"
    result = run_capture(repo, backup_dir, out_root)
    name = result["set_dir"].name
    with pytest.raises(ValueError):
        uuid.UUID(name)  # 证明「同根必被 C4 判为 unaccounted_capture_entry」
    c4_root = backup_dir / "capture-sets"
    assert not c4_root.exists() or not any(p.name == name for p in c4_root.iterdir())
    sh = (ROOT / "scripts" / "backup_db.sh").read_text()
    assert '--out-root "$BACKUP_DIR/state-capture-sets"' in sh
    assert '--prune-days "$RETAIN_DAYS"' in sh


def test_f2_budget_exceeded_recorded_not_crash(tmp_path, monkeypatch):
    """F2(2026-11-14 审查): 单文件超 64MB 预算(用例收紧到 4B)⇒ 记 budget_excluded、
    不崩溃不缩表, complete=false; 不留 .pending-* 临时目录。"""
    repo = make_repo(tmp_path)
    out_root = tmp_path / "capture-sets"
    monkeypatch.setattr(bsc, "MAX_FILE_BYTES", 4)
    result = run_capture(repo, make_backups(tmp_path), out_root)
    m = result["manifest"]
    assert m["status"] == "captured"
    assert m["budget_excluded"], "超预算项必须如实入 manifest"
    assert any(x["rel"] == "notify_dedup.json" and x["reason"] == "file_exceeds_capture_budget"
               for x in m["budget_excluded"])
    assert all(x["limit"] == 4 for x in m["budget_excluded"])
    # 独立锚: 预算超限不重复记成 no_match(missing 必须为空), complete=False 只可能来自
    # budget_excluded 子句 ⇒ 去掉该子句本用例必红(变异已验)。
    assert m["missing"] == [], m["missing"]
    assert m["complete"] is False, "有已声明未捕获项不许宣称完整"
    assert not list(out_root.glob(".pending-*"))


def test_f2_disk_full_fails_cleanly_no_pending(tmp_path, monkeypatch):
    """F2(2026-11-14 审查): 写盘 OSError(磁盘满 ENOSPC)⇒ status=failed/uploadable=false,
    不 traceback 崩溃、不留 .pending-* 临时目录。"""
    repo = make_repo(tmp_path)
    out_root = tmp_path / "capture-sets"

    def disk_full(path, payload):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(bsc, "write_bytes_0600", disk_full)
    result = run_capture(repo, make_backups(tmp_path), out_root)
    m = result["manifest"]
    assert result["uploadable"] is False and result["set_dir"] is None
    assert m["status"] == "failed"
    assert m["reason"] == "io_failure_during_capture"
    assert m["error"]["type"] == "OSError" and "No space left" in m["error"]["detail"]
    assert not list(out_root.glob(".pending-*"))


def test_f2_vanished_before_read_marked_missing(tmp_path, monkeypatch):
    """F2(2026-11-14 审查): 展开后、读取前被轮转删除 ⇒ 记 missing(vanished_during_capture),
    不崩溃、complete=false。"""
    repo = make_repo(tmp_path)
    out_root = tmp_path / "capture-sets"
    orig = bsc.read_stable

    def vanish(path, max_bytes=None):
        if path.name == "alert_state.json":
            raise FileNotFoundError(str(path))
        return orig(path, max_bytes)

    monkeypatch.setattr(bsc, "read_stable", vanish)
    result = run_capture(repo, make_backups(tmp_path), out_root)
    m = result["manifest"]
    assert {"rel": "alert_state.json", "reason": "vanished_during_capture"} in m["missing"]
    assert m["complete"] is False


def test_f5_business_date_mixed_formats_normalized(tmp_path):
    """F5(2026-11-14 审查): 8 位 YYYYMMDD 与 10 位 YYYY-MM-DD 混排必须归一成 ISO 再比较
    (旧实现字典序让 8 位恒赢: '-'(45) < 数字)。"""
    p = tmp_path / "x.json"
    p.write_text('{"20261113|sh000001|buy":{"code":"510300"}}', encoding="utf-8")
    date, method = bsc.business_date_of(p.read_bytes(), p)
    assert (date, method) == ("2026-11-13", "json_freeze_key_prefix")
    p2 = tmp_path / "y.json"
    p2.write_text('{"generated_at":"2026-11-14T20:00:00"}', encoding="utf-8")
    assert bsc.business_date_of(p2.read_bytes(), p2) == ("2026-11-14", "json_field:generated_at")
    # 跨源比较: sidecar 2026-11-14(10位) vs DB MAX(date)=20261113(8位) ⇒ 取前者
    cutoff = bsc.common_cutoff({
        "files": [{"rel": "a.json", "business_date": "2026-11-14",
                   "business_date_method": "json_field:date"}],
        "db_leg": {"databases": {"sentiment": {"status": "ok", "max_date": "20261113"}}}})
    assert cutoff["date"] == "2026-11-14"
    assert cutoff["evidence"] == "a.json"


def _make_set(root: Path, name: str, archive_status: str, mtime: float) -> Path:
    import os
    d = root / name
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({
        "schema": "trade-state-capture-v1", "capture_set_id": name,
        "archive": {"status": archive_status}}))
    os.utime(d, (mtime, mtime))
    return d


def test_f3_prune_only_uploaded_expired_owned(tmp_path):
    """F3(2026-11-14 审查): 参数化保留天数 + 先验后删 + 只删本任务登记目录:
    - 已上传且超期 ⇒ 删(最新集合除外);
    - 未上传/未超期/非登记名(纯 UUID、陌生目录)一律不碰。"""
    import os
    out = tmp_path / "state-capture-sets"
    out.mkdir()
    now = 1_700_000_000.0
    old = now - 40 * 86400
    recent = now - 1 * 86400
    _make_set(out, "20260101_2100-abcdef01", "uploaded", old)       # 删
    _make_set(out, "20260102_2100-abcdef02", "not_uploaded", old)   # 留(未上传)
    _make_set(out, "20260103_2100-abcdef03", "uploaded", recent)    # 留(未超期)
    _make_set(out, "20260104_2100-abcdef04", "uploaded", old)       # 留(最新集合)
    foreign = out / "some-other-dir"
    foreign.mkdir()
    os.utime(foreign, (old, old))
    c4_uuid = out / "123e4567-e89b-12d3-a456-426614174000"
    c4_uuid.mkdir()
    os.utime(c4_uuid, (old, old))
    res = bsc.prune_capture_sets(out, 30, now=now)
    actions = {r["name"]: r["action"] for r in res}
    assert actions["20260101_2100-abcdef01"] == "deleted"
    assert not (out / "20260101_2100-abcdef01").exists()
    for keep in ("20260102_2100-abcdef02", "20260103_2100-abcdef03",
                 "20260104_2100-abcdef04"):
        assert actions[keep] == "keep"
        assert (out / keep).exists()
    # 陌生目录与 C4 的纯 UUID 目录: 不在登记面内, 一律不碰
    assert foreign.exists() and c4_uuid.exists()
    assert "some-other-dir" not in actions and str(c4_uuid.name) not in actions


def test_f3_prune_keeps_only_uploaded_restore_point(tmp_path):
    """F3: 唯一一个已上传集合即使超期也保留(始终留至少一个可恢复点)。"""
    out = tmp_path / "state-capture-sets"
    out.mkdir()
    now = 1_700_000_000.0
    _make_set(out, "20260101_2100-abcdef01", "uploaded", now - 90 * 86400)
    res = bsc.prune_capture_sets(out, 30, now=now)
    assert res[0]["action"] == "keep"
    assert (out / "20260101_2100-abcdef01").exists()


def test_f6_declared_excludes_cover_inventory_gaps():
    """F6(2026-11-14 审查): 盘点 38 项里未纳入的条目必须逐项显式声明(纳入或
    DECLARED_EXCLUDES 写明理由/待拍板), 不许静默缺席。"""
    prefixes = {e["prefix"]: e["reason"] for e in bsc.DECLARED_EXCLUDES}
    for p in ("signal_kelly_trades.json", "daily-k.parquet", "sw_components.json",
              "stock_codes.json", "trade_dates.txt", "baostock_logs"):
        assert p in prefixes, f"盘点项 {p} 既未纳入也未声明排除"
    for p in ("signal_kelly_trades.json", "daily-k.parquet", "baostock_logs"):
        assert "待主控拍板" in prefixes[p], f"{p} 必须写明待主控拍板"
    patterns = {p for _, p, _ in bsc.DECLARED_INVENTORY}
    assert "staticdata_backup_heartbeat.json" in patterns


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
