# -*- coding: utf-8 -*-
"""standby 启用前必修回归用例(F1 判龄交易日 / F2 TLS 三支 / F3 CA 探测)。

任务书: /tmp/task-standby-followup-20261115.md;来源审查 /tmp/review-standby-sync-fix-20261115.md
(审查方把 /etc/ssl/cert.pem 兜底分支改成 unverified,14 个用例仍全绿 = 覆盖缺口)。

纪律:
- L51 冻结时钟: _check_stale 用 monkeypatch _now 注入固定时刻, 不取真实 today。
- L48 通知全桩化(monkeypatch standby_sync.emit_event 记录), 零真发、零触网。
- F3 只读本机 CA 文件, 不写 R2、不碰生产。
"""
import ast
import datetime as dt
import json
import os
import ssl
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).absolute().parent.parent
sys.path.insert(0, str(REPO_ROOT))
import standby_sync  # noqa: E402
import upload_r2  # noqa: E402


def _real_ca_file() -> str:
    """取本机一个真实可读的 CA 束(测试只用它构造校验上下文, 不依赖具体发行版)。"""
    for cand in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt",
                 "/etc/pki/tls/certs/ca-bundle.crt"):
        if Path(cand).exists():
            return cand
    try:
        import certifi
        return certifi.where()
    except ImportError:  # pragma: no cover - 环境既无系统 CA 也无 certifi
        pytest.skip("本机没有可用 CA 束")


# ============================================================ F1 判龄口径 ===
# 交易日历 data/trade_dates.txt 实测: 2026-11-09~13 为交易周(11-14/15 周末),
# 2026-10-01~07 国庆休市, 节前最后交易日 09-30、节后首个交易日 10-08。

def _now(y, m, d, hour=0, minute=30):
    return dt.datetime(y, m, d, hour, minute, 0, tzinfo=standby_sync.LOCAL_TZ)


def _layout(tmp_path, business_date):
    layout = standby_sync.Layout(SimpleNamespace(
        root=str(tmp_path / "standby"), work_dir=None, data_dir=None,
        archive_dir=None, state_dir=None, log_dir=None))
    layout.ensure()
    vdir = layout.versions / "v-f1"
    vdir.mkdir(exist_ok=True)
    (vdir / "verify_record.json").write_text(
        json.dumps({"business_date": business_date}), encoding="utf-8")
    if not layout.latest.is_symlink():
        os.symlink("versions/v-f1", layout.latest)
    return layout, standby_sync.StateStore(layout.state_file)


def _run_stale(tmp_path, monkeypatch, now, business_date,
               stale_days=2, mode="trading"):
    monkeypatch.setattr(standby_sync, "_now", lambda: now)
    sent = []
    monkeypatch.setattr(
        standby_sync, "emit_event",
        lambda key, subject, body, *a, **k: sent.append((key, subject, body))
        or True)
    layout, store = _layout(tmp_path, business_date)
    state = {}
    args = SimpleNamespace(stale_days=stale_days, stale_mode=mode)
    standby_sync._check_stale(layout, store, state, args, log=lambda *_: None)
    return sent, state


def _stale_key():
    return standby_sync.EVENT_KEYS["stale_recovery_point"]


def test_f1_default_mode_is_trading():
    args = standby_sync.build_parser().parse_args(["sync"])
    assert args.stale_mode == "trading"
    assert args.stale_days == 2


def test_f1_saturday_with_friday_cutoff_no_alert(tmp_path, monkeypatch):
    # ① 周六跑、db_cutoff=周五 ⇒ 不告警(周末不计滞后)
    sent, st = _run_stale(tmp_path, monkeypatch, _now(2026, 11, 14, 8),
                          "2026-11-13")
    assert sent == []
    assert st["latest_recovery_point_age_days"] == 0
    # ①b 更强: 阈值 0 也不告警(自然日口径下周六会算 1 天 ⇒ 这里必须仍静默)
    sent, st = _run_stale(tmp_path, monkeypatch, _now(2026, 11, 14, 8),
                          "2026-11-13", stale_days=0)
    assert sent == []
    assert st["latest_recovery_point_age_days"] == 0


def test_f1_monday_with_friday_cutoff_no_alert(tmp_path, monkeypatch):
    # ② 周一跑、db_cutoff=上周五 ⇒ 不告警(旧自然日口径会算 3 天 ⇒ 周一误报)
    sent, st = _run_stale(tmp_path, monkeypatch, _now(2026, 11, 16),
                          "2026-11-13")
    assert sent == []
    assert st["latest_recovery_point_age_days"] == 1


def test_f1_monday_with_wednesday_cutoff_alerts(tmp_path, monkeypatch):
    # ③ 周一跑、db_cutoff=上周三 ⇒ 滞后 3 个交易日 > 2 ⇒ 告警
    sent, st = _run_stale(tmp_path, monkeypatch, _now(2026, 11, 16),
                          "2026-11-11")
    assert [s[0] for s in sent] == [_stale_key()]
    assert st["latest_recovery_point_age_days"] == 3
    assert "3 个交易日" in sent[0][2]


def test_f1_first_trading_day_after_holiday_no_alert(tmp_path, monkeypatch):
    # ④ 国庆长假后首个交易日(10-08)、db_cutoff=节前最后交易日(09-30) ⇒ 不告警
    sent, st = _run_stale(tmp_path, monkeypatch, _now(2026, 10, 8),
                          "2026-09-30")
    assert sent == []
    assert st["latest_recovery_point_age_days"] == 1


def test_f1_genuinely_behind_alerts_with_trading_count(tmp_path, monkeypatch):
    # ⑤ 真落后(5 个交易日)⇒ 告警且文案写实际落后交易日数
    sent, st = _run_stale(tmp_path, monkeypatch, _now(2026, 11, 16),
                          "2026-11-09")
    assert [s[0] for s in sent] == [_stale_key()]
    assert st["latest_recovery_point_age_days"] == 5
    assert "5 个交易日" in sent[0][1] + sent[0][2]


def test_f1_calendar_unavailable_falls_back_natural_and_labeled(tmp_path, monkeypatch):
    # 日历不可用(异常/超覆盖)⇒ 回退自然日, 但单位必须如实标注, 不假装交易日
    monkeypatch.setattr(standby_sync, "_trading_lag_days",
                        lambda bd, today: None)
    sent, st = _run_stale(tmp_path, monkeypatch, _now(2026, 11, 16),
                          "2026-11-13")
    assert [s[0] for s in sent] == [_stale_key()]     # 自然日 3 > 2
    assert st["latest_recovery_point_age_days"] == 3
    assert "天(日历不可用回退自然日)" in sent[0][2]


def test_f1_natural_mode_keeps_old_behavior(tmp_path, monkeypatch):
    # 显式 natural(旧口径)保留: 周一/上周五 = 3 自然日 ⇒ 告警(复现旧误报, 仅排障用)
    sent, st = _run_stale(tmp_path, monkeypatch, _now(2026, 11, 16),
                          "2026-11-13", mode="natural")
    assert [s[0] for s in sent] == [_stale_key()]
    assert st["latest_recovery_point_age_days"] == 3
    assert "3天" in sent[0][2] or "3 天" in sent[0][2]


# ============================================ D1/D2/D3 日历边界加固 ===
# 来源: /tmp/review-standby-followup-20261115.md 边界差集 D1/D2/D3。
# 一切都用 monkeypatch 注入日历, 零触网、零读生产状态。

def _app_calendar():
    """导入真实 app.calendar(仓库根加到 sys.path), 供 monkeypatch 其日历源。"""
    root = Path(__file__).absolute().parent.parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import app.calendar as cal
    return cal


def _patch_calendar_dates(monkeypatch, dates):
    cal = _app_calendar()
    monkeypatch.setattr(cal, "_load_trade_dates", lambda: set(dates))


def test_d1_empty_calendar_not_labeled_as_trading_days(monkeypatch):
    # D1 日历空集(文件缺失且 akshare 不可用) ⇒ 工作日启发式(09-30→10-08 算 6)
    # 不是交易日历, 判不可用, 不得输出「个交易日」。
    _patch_calendar_dates(monkeypatch, [])
    assert standby_sync._trading_lag_days(
        "2026-09-30", dt.date(2026, 10, 8)) is None


def test_d1_empty_calendar_flow_alerts_with_natural_label(tmp_path, monkeypatch):
    _patch_calendar_dates(monkeypatch, [])
    sent, st = _run_stale(tmp_path, monkeypatch, _now(2026, 10, 8),
                          "2026-09-30")
    # 自然日 8 > 2 ⇒ 必须告警(宁可响亮, 不静默/不误标交易日)
    assert [s[0] for s in sent] == [_stale_key()]
    assert st["latest_recovery_point_age_days"] == 8
    assert "天(日历不可用回退自然日)" in sent[0][2]
    assert "6 个交易日" not in sent[0][1] + sent[0][2]


def test_d2_stale_calendar_never_silent_zero(monkeypatch):
    # D2 日历只到 11-13、今天 11-27 ⇒ 旧实现返回 0(真实 10)永不告警。
    _patch_calendar_dates(monkeypatch, ["20261111", "20261112", "20261113"])
    assert standby_sync._trading_lag_days(
        "2026-11-17", dt.date(2026, 11, 27)) is None


def test_d2_stale_calendar_flow_alerts_not_green(tmp_path, monkeypatch):
    _patch_calendar_dates(monkeypatch, ["20261111", "20261112", "20261113"])
    sent, st = _run_stale(tmp_path, monkeypatch, _now(2026, 11, 27),
                          "2026-11-17")
    # 真过期 10 自然日(日历不可用) ⇒ 必须告警, 不许可绿
    assert [s[0] for s in sent] == [_stale_key()]
    assert st["latest_recovery_point_age_days"] == 10
    assert "天(日历不可用回退自然日)" in sent[0][2]


def test_d3_unreadable_calendar_direct_no_crash(monkeypatch):
    # D3 日历读取抛 PermissionError ⇒ 按不可用处理, 不抛到调用方
    cal = _app_calendar()

    def _boom():
        raise PermissionError("calendar unreadable")

    monkeypatch.setattr(cal, "_load_trade_dates", _boom)
    assert standby_sync._trading_lag_days(
        "2026-11-13", dt.date(2026, 11, 16)) is None


def test_d3_unreadable_calendar_flow_does_not_crash(tmp_path, monkeypatch):
    cal = _app_calendar()

    def _boom():
        raise PermissionError("calendar unreadable")

    monkeypatch.setattr(cal, "_load_trade_dates", _boom)
    sent, st = _run_stale(tmp_path, monkeypatch, _now(2026, 11, 16),
                          "2026-11-13")
    assert [s[0] for s in sent] == [_stale_key()]     # 自然日 3 > 2
    assert st["latest_recovery_point_age_days"] == 3
    assert "天(日历不可用回退自然日)" in sent[0][2]


def test_d3_unreadable_calendar_real_read_path(tmp_path, monkeypatch):
    # D3 真实读盘路径: 日历路径指向目录 ⇒ read_text 抛 IsADirectoryError(OSError),
    # 不 mock _load_trade_dates 本身, 验证 app.calendar 真实读文件异常被兜住。
    cal = _app_calendar()
    bad = tmp_path / "trade_dates_as_dir"
    bad.mkdir()
    monkeypatch.setattr(cal, "_CACHE_PATH", bad)
    cal._load_trade_dates.cache_clear()
    try:
        assert standby_sync._trading_lag_days(
            "2026-11-13", dt.date(2026, 11, 16)) is None
    finally:
        cal._load_trade_dates.cache_clear()


# ======================================================== F2 TLS 三支兜底 ===
# 原缺口: 把系统 CA 兜底分支改成 unverified, 14 个用例仍全绿。以下三支都断言
# verify_mode=CERT_REQUIRED 且 check_hostname=True, 任一支改 unverified 必红。

def _ctx_ok(ctx):
    return (ctx.verify_mode == ssl.CERT_REQUIRED
            and ctx.check_hostname is True
            and ctx.verify_flags is not None)


def test_f2_branch1_certifi_preferred(monkeypatch):
    real_ca = _real_ca_file()
    fake = SimpleNamespace(where=lambda: real_ca)
    monkeypatch.setitem(sys.modules, "certifi", fake)
    monkeypatch.setattr(standby_sync, "_file_exists", lambda p: p == real_ca)
    assert standby_sync.resolve_ca_file() == real_ca
    assert _ctx_ok(standby_sync.tls_context())


def test_f2_branch2_system_ca_when_certifi_missing(monkeypatch, tmp_path):
    real_ca = _real_ca_file()
    monkeypatch.setitem(sys.modules, "certifi", None)   # import certifi ⇒ ImportError
    monkeypatch.setattr(standby_sync, "SYSTEM_CA_CANDIDATES", (real_ca,))
    monkeypatch.setattr(standby_sync, "_file_exists", lambda p: p == real_ca)
    assert standby_sync.resolve_ca_file() == real_ca
    assert _ctx_ok(standby_sync.tls_context())


def test_f2_branch3_no_ca_falls_back_to_verified_default(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "certifi", None)
    monkeypatch.setattr(standby_sync, "SYSTEM_CA_CANDIDATES",
                        (str(tmp_path / "missing-ca.pem"),))
    monkeypatch.setattr(standby_sync, "_file_exists", lambda p: False)
    assert standby_sync.resolve_ca_file() is None
    ctx = standby_sync.tls_context()
    assert _ctx_ok(ctx)                    # 默认上下文仍校验, 绝不 unverified


# ========================================================= F3 CA 按序探测 ===
# 原 bug: upload_r2.py 只认 /etc/ssl/cert.pem, 云上 Ubuntu 无该文件 ⇒ 生产上传
# 实际走 _create_unverified_context()。现按 certifi → 3 条系统路径探测, 全缺
# fail-closed(RuntimeError), 不存在的全是 unverified 可达路径。

def test_f3_group1_certifi_available_selected(monkeypatch):
    real_ca = _real_ca_file()
    monkeypatch.setitem(sys.modules, "certifi",
                        SimpleNamespace(where=lambda: real_ca))
    picked = upload_r2._resolve_ca_bundle(
        candidates=("/nonexistent/a.pem",), exists=lambda p: p == real_ca)
    assert picked == real_ca
    assert _ctx_ok(upload_r2._make_tls_context(picked))


def test_f3_group2_certifi_file_missing_falls_to_system(monkeypatch):
    real_ca = _real_ca_file()
    monkeypatch.setitem(sys.modules, "certifi",
                        SimpleNamespace(where=lambda: "/nonexistent/certifi.pem"))
    picked = upload_r2._resolve_ca_bundle(
        candidates=(real_ca,), exists=lambda p: p == real_ca)
    assert picked == real_ca
    assert _ctx_ok(upload_r2._make_tls_context(picked))


def test_f3_group3_certifi_module_missing_falls_to_system(monkeypatch):
    real_ca = _real_ca_file()
    monkeypatch.setitem(sys.modules, "certifi", None)
    picked = upload_r2._resolve_ca_bundle(
        candidates=("/nope/1.pem", real_ca), exists=lambda p: p == real_ca)
    assert picked == real_ca
    assert _ctx_ok(upload_r2._make_tls_context(picked))


def test_f3_group4_all_missing_fail_closed(monkeypatch):
    monkeypatch.setitem(sys.modules, "certifi", None)
    with pytest.raises(RuntimeError, match="CA 束"):
        upload_r2._resolve_ca_bundle(candidates=("/nope/1.pem",),
                                     exists=lambda p: False)


def test_f3_no_unverified_reachable_in_module():
    # 函数级: 全缺时抛错, 不走 unverified(上面 group4 已断言)
    # 源码级: AST 扫源码, 不存在任何 ssl._create_unverified_context 调用
    src = (REPO_ROOT / "upload_r2.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Attribute)
             and n.attr == "_create_unverified_context"]
    assert calls == [], "upload_r2 不允许任何 _create_unverified_context 可达路径"
    assert upload_r2._CTX.verify_mode == ssl.CERT_REQUIRED
    assert upload_r2._CTX.check_hostname is True
