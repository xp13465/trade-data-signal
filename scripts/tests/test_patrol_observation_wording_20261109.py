"""Channel observation dates are not a current unit's outage duration (offline)."""
import ast
import json
from datetime import datetime
from pathlib import Path

import pytest

import alert_denoise_rules as adr


NOW = datetime(2026, 11, 8, 23, 0, 4)
CHANNELS = ("failed_units_patrol", "cloud_unit_patrol_drift")


def observe(repo, days, key="failed_units_patrol"):
    path = repo / "data" / f"{key}_state.json"
    for day in days:
        grade = adr.consecutive_days_escalate(
            path, NOW.replace(day=day), 3, rolling_window_days=7)
    return path, grade


def render(repo, key, body):
    return adr.format_stall_body(body, adr.stall_context(key, repo, now=NOW), key)


def legacy_upgrade(body):
    """Render the actual unchanged notify template, without running its CLI/main."""
    tree = ast.parse((Path(__file__).parents[1] / "notify.py").read_text())
    templates = [n.value for n in ast.walk(tree) if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "_esc_body"
                         for t in n.targets)]
    assert len(templates) == 1
    from types import SimpleNamespace
    return eval(compile(ast.Expression(templates[0]), "<notify-upgrade-template>", "eval"),
                {"__builtins__": {}},
                {"_esc_first": "2026-11-02", "_esc_days": 7, "adr": adr,
                 "args": SimpleNamespace(body=body)})


def assert_honest(body, days):
    assert f"近 7 个自然日有 {days} 日异常记录" in body
    assert "巡检通道" in body
    assert "当前对象首次发生: 未知" in body
    assert "当前对象连续失败时长: 未知" in body
    assert "连续失败: 7 天" not in body
    assert "连续失败: 3 天" not in body
    assert "该异常自" not in body
    assert "人工处置超时" not in body
    assert "天未清除" not in body


def test_cross_unit_inheritance_is_labelled_channel_history(tmp_path):
    # Old unit A appeared on Nov2-7. A healthy observation does not reset the
    # rolling channel history. A different unit B first fails on Nov8.
    path, _ = observe(tmp_path, range(2, 8))
    previous = path.read_bytes()
    assert adr.failed_units_identity([], []) == []
    assert path.read_bytes() == previous
    _, grade = observe(tmp_path, [8])
    assert grade == ("critical", 7, "2026-11-02")
    body = render(tmp_path, "failed_units_patrol", "本轮 failed: trade-new-b.service")
    assert_honest(body, 7)
    assert "窗口内最早记录: 2026-11-02" in body
    assert body.endswith("本轮 failed: trade-new-b.service")


@pytest.mark.parametrize("key", CHANNELS)
def test_nonadjacent_days_are_not_continuous_failure(tmp_path, key):
    path, grade = observe(tmp_path, [2, 4, 8], key)
    before = path.read_bytes()
    assert grade == ("critical", 3, "2026-11-02")
    assert_honest(render(tmp_path, key, "本轮异常对象详情"), 3)
    assert path.read_bytes() == before  # formatting never changes grading state


@pytest.mark.parametrize("key", CHANNELS)
@pytest.mark.parametrize("pre_rendered", [False, True])
def test_upgrade_after_optional_render_has_no_false_inner_claim(tmp_path, key, pre_rendered):
    observe(tmp_path, range(2, 9), key)
    payload = "本轮对象 trade-new-b.service；差异原文 &lt;actual&gt;"
    if pre_rendered:
        payload = render(tmp_path, key, payload)
    upgraded = legacy_upgrade(payload)
    assert "人工处置超时" in upgraded  # prove the real legacy template is exercised
    body = render(tmp_path, key, upgraded)
    assert_honest(body, 7)
    assert "达到既有升级条件" in body
    assert body.endswith("本轮对象 trade-new-b.service；差异原文 &lt;actual&gt;")


@pytest.mark.parametrize("state", [
    {}, {"first_fail_date": "2026-11-02", "consecutive_days": 7},
    {"seen_dates": "2026-11-02"}, {"seen_dates": ["bad", "2026-11-08"]},
    {"seen_dates": ["2026-11-08", "2026-11-31"]},
])
def test_missing_legacy_or_invalid_dates_are_unknown(tmp_path, state):
    path = tmp_path / "data" / "failed_units_patrol_state.json"
    path.parent.mkdir()
    path.write_text(json.dumps(state))
    # A generic alert_state is also channel-wide and cannot supply unit onset.
    (path.parent / "alert_state.json").write_text(json.dumps({
        "failed_units_patrol": {"first_seen": "2020-01-01", "consecutive_count": 99}}))
    body = render(tmp_path, "failed_units_patrol", "原始正文")
    assert "异常记录天数: 未知" in body
    assert "当前对象首次发生: 未知" in body
    assert "当前对象连续失败时长: 未知" in body
    assert "2020-01-01" not in body and "99" not in body


def test_view_window_filters_old_dates_without_mutating_counter(tmp_path):
    path, _ = observe(tmp_path, [2, 4, 8])
    before = path.read_bytes()
    ctx = adr.stall_context("failed_units_patrol", tmp_path,
                            now=NOW.replace(day=9))
    body = adr.format_stall_body("原始正文", ctx, "failed_units_patrol")
    assert "近 7 个自然日有 2 日异常记录" in body
    assert "窗口内最早记录: 2026-11-04" in body
    assert path.read_bytes() == before


def test_channels_are_separate_and_nonchannel_format_stays_compatible(tmp_path):
    observe(tmp_path, range(2, 9))
    observe(tmp_path, [8], "cloud_unit_patrol_drift")
    assert_honest(render(tmp_path, "failed_units_patrol", "单位异常"), 7)
    assert_honest(render(tmp_path, "cloud_unit_patrol_drift", "配置差异"), 1)
    ctx = {"first_seen": "2026-11-02", "consecutive": "7 天", "impact": "产物"}
    original = "<b>持续异常升级</b>: 不属于巡检通道的原文<br>详情"
    expected = ("<b>【停摆级告警】</b><br>· 首次发生: 2026-11-02<br>"
                "· 连续失败: 7 天<br>· 影响产物: 产物<br><br>" + original)
    assert adr.format_stall_body(original, ctx) == expected
    assert adr.format_stall_body(original, ctx, "deploy_consecutive_fail") == expected


def test_unrelated_upgrade_like_text_is_not_rewritten(tmp_path):
    observe(tmp_path, [8])
    original = "<b>持续异常升级</b>: 其他来源的原始证据；人工处置超时待核查<br>原始详情"
    assert render(tmp_path, "failed_units_patrol", original).endswith(original)


def test_repeated_render_and_upgrade_stays_honest(tmp_path):
    observe(tmp_path, range(2, 9), "cloud_unit_patrol_drift")
    ctx = adr.stall_context("cloud_unit_patrol_drift", tmp_path, now=NOW)
    body = adr.format_stall_body("原始配置差异", ctx)  # legacy two-argument caller
    for _ in range(2):
        body = adr.format_stall_body(legacy_upgrade(body), ctx)
        assert_honest(body, 7)
        assert "【停摆级告警】" not in body
        assert body.endswith("原始配置差异")


def test_invalid_json_and_deduplicated_dates_are_read_only(tmp_path):
    path = tmp_path / "data" / "failed_units_patrol_state.json"
    path.parent.mkdir()
    path.write_text('{"seen_dates":')
    assert "异常记录天数: 未知" in render(tmp_path, "failed_units_patrol", "详情")
    path.write_text(json.dumps({"seen_dates": ["2026-11-08", "2026-11-08", "2026-11-09"]}))
    before = path.read_bytes()
    assert_honest(render(tmp_path, "failed_units_patrol", "详情"), 1)
    assert path.read_bytes() == before


@pytest.mark.parametrize("key", CHANNELS)
def test_actual_critical_send_final_bodies_and_routes(tmp_path, monkeypatch, key):
    """Real in-process send_tiered/send, temporary state and trapped transports only."""
    import notify
    from _zero_outbound import ZeroOutboundTrap

    alerts = tmp_path / "data" / "alerts"
    alerts.mkdir(parents=True)
    monkeypatch.setenv("REPO", str(tmp_path))
    monkeypatch.setattr(notify, "REPO", tmp_path)
    monkeypatch.setattr(notify, "ALERTS_DIR", alerts)
    for name in ("ALERTS_FILE", "WARNING_BUFFER_FILE", "INFO_LOG_FILE",
                 "WARNING_DEDUP_STATE_FILE", "DEDUP_FILE", "ALERT_DIGEST_FILE",
                 "ALERT_DIGEST_LOCK_FILE", "ALERT_DIGEST_STATE_FILE",
                 "WARNING_DEDUP_LOCK_FILE", "WARNING_FLUSH_LOCK_FILE"):
        monkeypatch.setattr(notify, name, alerts / Path(getattr(notify, name)).name)
    for name in ("NOTIFY_RESULT_FILE", "NOTIFY_SOURCE", "ALERT_BUDGET_DISABLE",
                 "ALERT_DOMAIN_DISABLE", "ALERT_DIGEST_DISABLE", "ALERT_LEDGER_DISABLE"):
        monkeypatch.delenv(name, raising=False)

    class Clock(datetime):
        @classmethod
        def now(cls):
            return NOW

    monkeypatch.setattr(adr, "datetime", Clock)
    calls = []

    def capture(channel):
        def transport(subject, body, *args, **kwargs):
            calls.append((channel, subject, body, kwargs))
            return True
        return transport

    for attr, channel in [("_send_email", "email"), ("send_telegram", "telegram"),
                          ("send_feishu", "feishu")]:
        monkeypatch.setattr(notify, attr, capture(channel))
    state, _ = observe(tmp_path, range(2, 9), key)
    before = state.read_bytes()
    with ZeroOutboundTrap() as trap:
        for _ in range(2):  # window=0 still permits the caller's new-set reports
            result = notify.send_tiered(
                "[告警] 巡检异常", legacy_upgrade(render(tmp_path, key, "当前对象 new.service")),
                tier="critical", from_prefix="[告警]", ledger_key=key, dedup_window=0)
            assert result == {"tier": "critical", "email": True, "telegram": True, "feishu": True}
        assert trap.hits == []
    assert len(calls) == 6
    for channel, subject, body, kwargs in calls:
        assert subject.startswith(adr.stall_prefix_for(key))
        assert_honest(body, 7)
        assert body.endswith("当前对象 new.service")
        if channel == "feishu":
            assert kwargs["chat_key"] is None  # retain the original subject-based route
            assert notify._resolve_feishu_chat_key(
                subject, kwargs["from_prefix"], kwargs["severe"]) == "alert"
    assert state.read_bytes() == before
