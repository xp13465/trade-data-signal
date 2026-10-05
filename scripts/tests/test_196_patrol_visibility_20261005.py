#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#196「巡检/链路自身死亡」可见性统一 —— pytest 自验(F1 族, 2026-10-05)。

覆盖(每条 = 真实判定代码 / 真实子进程实跑 + 反向测; **全程零真实外发**):
  ① failed-unit 解析 + 巡检者存活判定 + ExecStart 脚本路径解析(alert_denoise_rules 纯函数)
  ② 「连续 N 天仍异常 → 升 critical」通用判定 consecutive_days_escalate(含 R7 回归)
  ③ check_failed_units.py 端到端(注入样本, dry-run 不发通知; 非云上 rc=3; patrol 定向抑制;
     守护 unit 的脚本被删 → 报, 脚本在盘 → 不误报)
  ④ notify.py 的 #196 升档接线(monkeypatch 发送层 → 真跑 main(), 绝不真发邮件/飞书)
  ⑤ §22/§23.3 登记与覆盖一致性机检(gen_schedule_stats TASKS/LABEL_MAP vs schedule_monitor TASKS
     vs 云上 unit 快照; 凡带 ConditionPathExists 的 unit 必须进 WATCHMAN_UNITS)
     —— 「schedule_stats 三副本 grep -c patrol = 0」不再复发

⚠️ 通知自测安全(§18 L48 / memory notify-script-selftest-must-stub): 涉及 notify/告警链的用例
   **一律先打桩**(monkeypatch notify.send_tiered/send/check_dedup/update_dedup/write_alert,
   或子进程走 dry-run), 断言「本次自测未产生真实外发」。

跑法: python3 -m pytest -q scripts/tests/test_196_patrol_visibility_20261005.py
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest  # noqa: F401  (显式依赖声明)

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import alert_denoise_rules as adr  # noqa: E402
import notify  # noqa: E402  (conftest 已加 scripts/ 入 sys.path)

ROOT = Path(__file__).absolute().parent.parent.parent
SCRIPTS = ROOT / "scripts"
CFU = SCRIPTS / "check_failed_units.py"

# 全部巡检/监控 timer 健康样本(ActiveState=active / LoadState=loaded / UnitFileState=enabled);
# 由 adr.WATCHMAN_UNITS 推导, 清单增删自动跟随(不写死 5 个, 防两处清单漂移)
HEALTHY_SHOW = {u: {"ActiveState": "active", "LoadState": "loaded", "UnitFileState": "enabled"}
                for u, _ in adr.WATCHMAN_UNITS}


def _run_cfu(tmp_path, failed_text="", show_map=None, repo=None, extra=None):
    """子进程跑 check_failed_units.py(注入样本, 默认 dry → 绝不真发通知)。"""
    f = tmp_path / "failed.txt"
    f.write_text(failed_text, encoding="utf-8")
    s = tmp_path / "show.json"
    s.write_text(json.dumps(show_map if show_map is not None else HEALTHY_SHOW), encoding="utf-8")
    cmd = [sys.executable, str(CFU), "--repo", str(repo or tmp_path),
           "--failed-units-file", str(f), "--unit-show-json", str(s)]
    if extra:
        cmd += extra
    return subprocess.run(cmd, capture_output=True, text=True, timeout=90, check=False)


# ══════════════════════════════════════════════════════════════════
# ① 纯函数: parse_failed_units / judge_watchman_units
# ══════════════════════════════════════════════════════════════════
def test_parse_failed_units_real_format():
    """systemctl list-units --state=failed --no-legend --plain 的真实输出形态。"""
    out = ("trade-xxx.service loaded failed failed Some description\n"
           "trade-yyy.timer   loaded failed failed Another\n")
    assert adr.parse_failed_units(out) == ["trade-xxx.service", "trade-yyy.timer"]


def test_parse_failed_units_filters_junk_and_dedup():
    """空行/无 unit 后缀的描述行/重复行都要被过滤(--no-legend 下偶发的杂行)。"""
    out = ("\n  \n"
           "Some header without unit suffix\n"
           "trade-z.service loaded failed failed desc\n"
           "trade-z.service loaded failed failed desc\n")
    assert adr.parse_failed_units(out) == ["trade-z.service"]


def test_parse_failed_units_empty():
    assert adr.parse_failed_units("") == []
    assert adr.parse_failed_units(None) == []


def test_judge_watchman_units_healthy():
    rows = [{"unit": u, "kind": "timer", "active_state": "active",
             "load_state": "loaded", "unit_file_state": "enabled"}
            for u, _ in adr.WATCHMAN_UNITS]
    assert adr.judge_watchman_units(rows) == []


def test_judge_watchman_units_timer_stopped():
    rows = [{"unit": "trade-cloud-unit-patrol.timer", "kind": "timer",
             "active_state": "inactive", "load_state": "loaded", "unit_file_state": "enabled"}]
    probs = adr.judge_watchman_units(rows)
    assert len(probs) == 1 and "ActiveState='inactive'" in probs[0]


def test_judge_watchman_units_unit_file_disabled():
    rows = [{"unit": "trade-schedule-monitor.timer", "kind": "timer",
             "active_state": "active", "load_state": "loaded", "unit_file_state": "disabled"}]
    probs = adr.judge_watchman_units(rows)
    assert len(probs) == 1 and "UnitFileState='disabled'" in probs[0]


def test_judge_watchman_units_not_found():
    """unit 文件离盘(= 最彻底的「巡检被删」形态)必须报, 且不再叠加 timer 停摆噪声。"""
    rows = [{"unit": "trade-cloud-unit-patrol.timer", "kind": "timer",
             "active_state": None, "load_state": "not-found", "unit_file_state": ""}]
    probs = adr.judge_watchman_units(rows)
    assert len(probs) == 1 and "LoadState=not-found" in probs[0]


def test_judge_watchman_units_none_fields_fail_loud():
    """systemctl show 读不到(字段 None)= 异常, fail-loud 不静默。"""
    rows = [{"unit": "trade-self-heal.timer", "kind": "timer",
             "active_state": None, "load_state": None, "unit_file_state": None}]
    probs = adr.judge_watchman_units(rows)
    assert probs, "读不到状态必须报异常, 不得静默"


# ══════════════════════════════════════════════════════════════════
# ①b 纯函数: extract_script_paths(脚本存在性检查的解析层, §23.3 同模式面兜底)
# ══════════════════════════════════════════════════════════════════
def test_extract_script_paths_real_bash_format():
    """云上实测格式(systemd 249): ExecStart={ path=/bin/bash ; argv[]=/bin/bash /abs/x.sh ; ... }"""
    e = ("{ path=/bin/bash ; argv[]=/bin/bash /home/ubuntu/code/trade-data/scripts/cloud_unit_patrol.sh"
         " ; ignore_errors=no ; start_time=[Mon 2026-10-05 21:00:37 CST] ; pid=1 ; code=exited ; status=0 }")
    assert adr.extract_script_paths(e) == ["/home/ubuntu/code/trade-data/scripts/cloud_unit_patrol.sh"]


def test_extract_script_paths_real_python_format():
    e = ("{ path=/home/ubuntu/code/trade-data/.venv/bin/python ; argv[]=/home/ubuntu/code/trade-data/"
         ".venv/bin/python /home/ubuntu/code/trade-data/scripts/check_monitor_heartbeat.py ; status=0 }")
    assert adr.extract_script_paths([e]) == [
        "/home/ubuntu/code/trade-data/scripts/check_monitor_heartbeat.py"]


def test_extract_script_paths_ignores_non_script_argv():
    """解释器/flag/非 .sh|.py 的绝对路径一律不认(fail-open, 绝不误报「脚本被删」)。"""
    e = "{ path=/usr/bin/foo ; argv[]=/usr/bin/foo --config /etc/foo.conf -v ; status=1 }"
    assert adr.extract_script_paths([e]) == []


def test_extract_script_paths_fail_open_on_junk():
    assert adr.extract_script_paths(None) == []
    assert adr.extract_script_paths("") == []
    assert adr.extract_script_paths("ExecStart={ path=/bin/bash ; status=0 }") == []
    assert adr.extract_script_paths("garbage without marker") == []


# ══════════════════════════════════════════════════════════════════
# ② consecutive_days_escalate(+ R7 回归)
# ══════════════════════════════════════════════════════════════════
def _mk_state(tmp_path, name, last, days, first=None):
    p = tmp_path / name
    p.write_text(json.dumps({"last_fail_date": last, "consecutive_days": days,
                             "first_fail_date": first or last,
                             "last_grade_time": ""}), encoding="utf-8")
    return p


def test_consecutive_first_day_is_severe(tmp_path):
    from datetime import datetime
    p = tmp_path / "s.json"
    tier, days, first = adr.consecutive_days_escalate(p, datetime(2026, 10, 5), 3)
    assert (tier, days, first) == ("severe", 1, "2026-10-05")
    assert json.loads(p.read_text())["consecutive_days"] == 1


def test_consecutive_third_day_is_critical(tmp_path):
    from datetime import datetime
    p = _mk_state(tmp_path, "s.json", "2026-10-04", 2, first="2026-10-03")
    tier, days, first = adr.consecutive_days_escalate(p, datetime(2026, 10, 5), 3)
    assert (tier, days, first) == ("critical", 3, "2026-10-03")


def test_consecutive_second_day_still_severe_at_threshold_three(tmp_path):
    from datetime import datetime
    p = _mk_state(tmp_path, "s.json", "2026-10-04", 1, first="2026-10-04")
    tier, days, _ = adr.consecutive_days_escalate(p, datetime(2026, 10, 5), 3)
    assert (tier, days) == ("severe", 2)


def test_consecutive_gap_resets(tmp_path):
    """间隔 >1 自然日(中间有正常日/未跑日)= 连续链中断, 从 1 重新计。"""
    from datetime import datetime
    p = _mk_state(tmp_path, "s.json", "2026-10-01", 9, first="2026-09-23")
    tier, days, first = adr.consecutive_days_escalate(p, datetime(2026, 10, 5), 3)
    assert (tier, days, first) == ("severe", 1, "2026-10-05")


def test_consecutive_same_day_no_double_count(tmp_path):
    from datetime import datetime
    p = _mk_state(tmp_path, "s.json", "2026-10-05", 2, first="2026-10-04")
    tier, days, _ = adr.consecutive_days_escalate(p, datetime(2026, 10, 5, 23, 59), 3)
    assert (tier, days) == ("severe", 2), "同日重跑/重试不得重复计数"


def test_consecutive_state_persisted_atomically(tmp_path):
    from datetime import datetime
    p = tmp_path / "s.json"
    adr.consecutive_days_escalate(p, datetime(2026, 10, 5), 3)
    st = json.loads(p.read_text(encoding="utf-8"))
    assert set(st) == {"last_fail_date", "consecutive_days", "first_fail_date", "last_grade_time"}
    assert not (tmp_path / "s.json.tmp").exists(), "原子写: 不得残留 .tmp"


def test_r7_regression_two_days_and_message(tmp_path):
    """R7 重构为委托 consecutive_days_escalate 后, 行为/文案/档位一字不变(回归)。"""
    from datetime import datetime
    p = tmp_path / "r2.json"
    tier, days, reason = adr.r7_r2_consistency_escalate(p, datetime(2026, 10, 5))
    assert (tier, days) == ("severe", 1) and reason == "首日失败(2026-10-05, 当前连续 1 天)"
    p2 = _mk_state(tmp_path, "r2b.json", "2026-10-04", 1, first="2026-10-04")
    tier, days, reason = adr.r7_r2_consistency_escalate(p2, datetime(2026, 10, 5))
    assert (tier, days) == ("critical", 2)
    assert "连续 2 天一致性校验失败" in reason and "2026-10-04" in reason


def test_wrapper_channel_alerted(tmp_path):
    """通用 wrapper 判定 + R7 别名同源。"""
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "notify_dedup.json").write_text(json.dumps(
        {"cloud_unit_patrol_drift": {"last_alerted": "2026-10-05 08:28:00"}}), encoding="utf-8")
    assert adr.wrapper_channel_alerted(tmp_path, "2026-10-05 08:27", adr.PATROL_DRIFT_DEDUP_KEY)
    assert not adr.wrapper_channel_alerted(tmp_path, "2026-10-05 09:00", adr.PATROL_DRIFT_DEDUP_KEY)
    assert not adr.wrapper_channel_alerted(tmp_path, "2026-10-05 08:27", "unknown_key")
    # R7 别名 = 同一实现
    (tmp_path / "data" / "notify_dedup.json").write_text(json.dumps(
        {"r2_consistency_fail": {"last_alerted": "2026-10-05 23:25:00"}}), encoding="utf-8")
    assert adr.r7_r2_consistency_wrapper_alerted(tmp_path, "2026-10-05 23:20")


# ══════════════════════════════════════════════════════════════════
# ③ check_failed_units.py 端到端(注入样本, 零真通知)
# ══════════════════════════════════════════════════════════════════
def test_cfu_healthy_rc0(tmp_path):
    r = _run_cfu(tmp_path, failed_text="")
    assert r.returncode == 0 and "CHECK_FAILED_UNITS_OK" in r.stdout


def test_cfu_failed_unit_rc1_dry_no_notify(tmp_path):
    r = _run_cfu(tmp_path, failed_text="trade-xxx.service loaded failed failed desc\n")
    assert r.returncode == 1
    assert "CHECK_FAILED_UNITS_FAIL" in r.stdout and "trade-xxx.service" in r.stdout
    # 未真发通知(默认 dry): 证据点
    assert "dry-run: 未真发通知" in r.stderr


def test_cfu_watchman_stopped_rc1(tmp_path):
    show = dict(HEALTHY_SHOW)
    show["trade-cloud-unit-patrol.timer"] = {"ActiveState": "inactive", "LoadState": "loaded",
                                             "UnitFileState": "enabled"}
    r = _run_cfu(tmp_path, show_map=show)
    assert r.returncode == 1
    assert "ActiveState='inactive'" in r.stdout
    assert "巡检者自身存活异常" in r.stderr, "dry-run 必须打出将发送内容(自验留证)"


def test_cfu_watchman_script_missing_rc1(tmp_path):
    """§23.3 同模式暴击面: 守护 unit 的脚本被删 → systemd 静默跳过(不 failed/不写日志)也必须报。

    这是与注册(漏跑)无关的兜底: 直接查 ExecStart 里的脚本本体在不在盘。
    """
    show = dict(HEALTHY_SHOW)
    show["trade-check-monitor-heartbeat.timer"] = {
        "ActiveState": "active", "LoadState": "loaded", "UnitFileState": "enabled",
        "ExecStart": ("{ path=/home/ubuntu/code/trade-data/.venv/bin/python ; argv[]=.../python "
                      f"{tmp_path}/scripts/gone_heartbeat.py ; status=0 }}"),
    }
    r = _run_cfu(tmp_path, show_map=show)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "被执行的脚本已不在盘" in r.stdout
    assert "gone_heartbeat.py" in r.stdout


def test_cfu_watchman_script_present_rc0(tmp_path):
    """反向保证: 脚本在盘 → 不误报(该层必须零假阳性, 否则成告警噪音)。"""
    real = tmp_path / "real_patrol.sh"
    real.write_text("#!/bin/bash\ntrue\n", encoding="utf-8")
    show = dict(HEALTHY_SHOW)
    show["trade-cloud-unit-patrol.timer"] = {
        "ActiveState": "active", "LoadState": "loaded", "UnitFileState": "enabled",
        "ExecStart": f"{{ path=/bin/bash ; argv[]=/bin/bash {real} ; status=0 }}",
    }
    r = _run_cfu(tmp_path, show_map=show)
    assert r.returncode == 0, r.stdout + r.stderr


def shutil_which(name):
    from shutil import which
    return which(name)


def test_cfu_noncloud_rc3(tmp_path):
    """非云上(无 systemctl 且无注入)→ rc=3, 绝不把「本机没有 systemctl」误判成云上 unit 全挂。"""
    if shutil_which("systemctl"):
        pytest.skip("本机有 systemctl, 走真实 systemd 判据(云上 rc=3 证据见报告)")
    r = subprocess.run([sys.executable, str(CFU), "--repo", str(tmp_path)],
                       capture_output=True, text=True, timeout=60, check=False)
    assert r.returncode == 3 and "[skip]" in r.stdout


def test_cfu_patrol_unit_suppressed_when_wrapper_alerted(tmp_path):
    """patrol 漂移时包装器通道本次已发 → failed-unit 侧定向抑制, 不复述(rc=0)。"""
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "notify_dedup.json").write_text(json.dumps(
        {"cloud_unit_patrol_drift": {"last_alerted": "2026-10-05 08:28:00"}}), encoding="utf-8")
    stats = tmp_path / "stats.json"
    stats.write_text(json.dumps([{"task": "cloud_unit_patrol", "last_run": "2026-10-05 08:27"}]),
                     encoding="utf-8")
    r = _run_cfu(tmp_path, failed_text="trade-cloud-unit-patrol.service loaded failed failed d\n",
                 extra=["--stats-file", str(stats)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[suppress]" in r.stdout and "patrol 包装器通道本次已发" in r.stdout


def test_cfu_patrol_unit_reported_when_wrapper_silent(tmp_path):
    """反例保证: 包装器没发过(去重表缺失)→ 照报, 不吞真故障。"""
    r = _run_cfu(tmp_path, failed_text="trade-cloud-unit-patrol.service loaded failed failed d\n")
    assert r.returncode == 1 and "trade-cloud-unit-patrol.service" in r.stdout


# ══════════════════════════════════════════════════════════════════
# ④ notify.py #196 升档接线(打桩发送层 → 真跑 main(); 零真外发)
# ══════════════════════════════════════════════════════════════════
@pytest.fixture
def stubbed_notify(tmp_path, monkeypatch, capsys):
    """打桩 notify 的全部发送/去重/落盘出口; 返回 (sent[], monkeypatch)。"""
    sent = []
    monkeypatch.setenv("REPO", str(tmp_path))
    monkeypatch.setattr(notify, "send_tiered",
                        lambda subject, body, **kw: (sent.append(("tiered", subject)),
                                                     {"email": True, "feishu": True,
                                                      "telegram": False})[1])
    monkeypatch.setattr(notify, "send",
                        lambda subject, body, **kw: (sent.append(("send", subject)),
                                                     {"email": True, "feishu": True,
                                                      "telegram": False})[1])
    monkeypatch.setattr(notify, "check_dedup", lambda *a, **k: False)
    monkeypatch.setattr(notify, "update_dedup", lambda *a, **k: None)
    monkeypatch.setattr(notify, "write_alert", lambda *a, **k: None)
    return sent, tmp_path


def _seed_escalate_state(tmp_path, name, last, days, first):
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / name).write_text(json.dumps(
        {"last_fail_date": last, "consecutive_days": days, "first_fail_date": first,
         "last_grade_time": ""}), encoding="utf-8")


def test_notify_escalation_patrol_drift_third_day(stubbed_notify):
    """patrol 漂移连续第 3 天 → notify 拦截改发 critical(独立 key), 且同步占首日窗。"""
    sent, tmp_path = stubbed_notify
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    y1 = (datetime.now().replace(hour=0) - __import__("datetime").timedelta(days=1)).strftime("%Y-%m-%d")
    y2 = (datetime.now().replace(hour=0) - __import__("datetime").timedelta(days=2)).strftime("%Y-%m-%d")
    _seed_escalate_state(tmp_path, "cloud_unit_patrol_drift_state.json", y1, 2, first=y2)
    rc = notify.main(["漂移主题", "漂移正文", "--severe", "--from-prefix", "[告警]",
                      "--dedup-key", "cloud_unit_patrol_drift", "--dedup-window", "21600"])
    assert rc == 0
    tiered = [s for k, s in sent if k == "tiered"]
    assert tiered and "升级 critical" in tiered[0] and "连续 3 天" in tiered[0]
    assert not [s for k, s in sent if k == "send"], "升级档不得再走普通 severe 路径(不双发)"


def test_notify_escalation_failed_units_third_day(stubbed_notify):
    sent, tmp_path = stubbed_notify
    from datetime import datetime, timedelta
    y1 = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    y2 = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    _seed_escalate_state(tmp_path, "failed_units_patrol_state.json", y1, 2, first=y2)
    rc = notify.main(["failed 主题", "failed 正文", "--severe",
                      "--dedup-key", "failed_units_patrol", "--dedup-window", "21600"])
    assert rc == 0
    tiered = [s for k, s in sent if k == "tiered"]
    assert tiered and "failed unit 持续未清" in tiered[0] and "连续 3 天" in tiered[0]


def test_notify_escalation_first_day_falls_through(stubbed_notify, capsys):
    """首日/单次 → 不拦截, 落回普通 severe 路径(历史行为不变)。"""
    sent, tmp_path = stubbed_notify
    rc = notify.main(["首日主题", "首日正文", "--severe",
                      "--dedup-key", "cloud_unit_patrol_drift", "--dedup-window", "21600"])
    assert rc == 0
    assert [s for k, s in sent if k == "send"], "首日必须走普通 severe 路径"
    assert "分级=severe" in capsys.readouterr().err


def test_notify_escalation_dry_run_no_state_write(stubbed_notify, tmp_path):
    """--dry-run 一律不写状态(自测安全, 与 R7 同口径)。"""
    sent, tmp = stubbed_notify
    notify.main(["t", "b", "--severe", "--dedup-key", "cloud_unit_patrol_drift",
                 "--dedup-window", "21600", "--dry-run"])
    assert not (tmp / "data" / "cloud_unit_patrol_drift_state.json").exists()


# ══════════════════════════════════════════════════════════════════
# ⑤ §22 三副本登记一致性机检
# ══════════════════════════════════════════════════════════════════
def _gen_registry():
    import gen_schedule_stats as g
    return ({t["task"] for t in g.TASKS}, dict(g.LABEL_MAP))


def _monitor_registry():
    src = (SCRIPTS / "schedule_monitor.sh").read_text(encoding="utf-8")
    start = src.index("TASKS = [")
    end = src.index("\n]\n", start)
    return set(re.findall(r'"task":\s*"([^"]+)"', src[start:end]))


def _selfheal_registry():
    src = (SCRIPTS / "self_heal.sh").read_text(encoding="utf-8")
    return set(re.findall(r'^\s+"([a-z0-9_]+)":\s*\["bash"', src, re.M))


def test_registry_patrol_present_in_all_three():
    """#196② 核心机检: patrol 必须同时登记进 gen_schedule_stats(喂 schedule_stats)与
    schedule_monitor(喂漏跑), 否则「脚本被删(ConditionPathExists → unit 不启动)」永久静默。"""
    gen_tasks, label_map = _gen_registry()
    mon_tasks = _monitor_registry()
    assert "cloud_unit_patrol" in gen_tasks, "gen_schedule_stats.TASKS 缺 patrol(= 原病灶)"
    assert "cloud_unit_patrol" in mon_tasks, "schedule_monitor.TASKS 缺 patrol(= 原病灶)"
    assert label_map.get("cloud_unit_patrol") == "com.trade.cloud-unit-patrol"


def test_registry_patrol_label_matches_cloud_unit_name():
    """label→unit 映射(`com.trade.`→`trade-`)必须命中云上真实 unit 名(快照为准)。"""
    _, label_map = _gen_registry()
    unit = label_map["cloud_unit_patrol"].replace("com.trade.", "trade-") + ".service"
    assert unit == "trade-cloud-unit-patrol.service"
    snap = (ROOT / "docs" / "deploy" / "systemd-units-cloud-snapshot.txt").read_text(encoding="utf-8")
    assert f"@@@FILE:{unit}" in snap, "云上 unit 快照缺该 unit(三源不一致)"
    assert "@@@FILE:trade-cloud-unit-patrol.timer" in snap


def test_watchman_units_exist_in_cloud_snapshot():
    """WATCHMAN_UNITS 每个 unit 必须在云上 unit 快照里真实存在(防清单写了个不存在的 unit →
    check_failed_units 每轮把它判成 not-found 假告警)。"""
    snap = (ROOT / "docs" / "deploy" / "systemd-units-cloud-snapshot.txt").read_text(encoding="utf-8")
    cloud_timers = set(re.findall(r"@@@FILE:(trade-[a-z0-9-]+\.timer)", snap))
    missing = [u for u, _ in adr.WATCHMAN_UNITS if u not in cloud_timers]
    assert missing == [], f"WATCHMAN_UNITS 有快照里不存在的 unit(会恒假告警): {missing}"


def test_watchman_units_have_syslog_service_counterpart():
    """每个 .timer 都应有配套 .service(云上 unit 成对生成; 缺 = 快照不完整)。"""
    snap = (ROOT / "docs" / "deploy" / "systemd-units-cloud-snapshot.txt").read_text(encoding="utf-8")
    for u, _ in adr.WATCHMAN_UNITS:
        assert f"@@@FILE:{u.replace('.timer', '.service')}" in snap, f"{u} 缺配套 .service"


def test_conditionpathexists_units_all_watchman_covered():
    """§23.3 同模式暴击面机检: 云上凡带 `ConditionPathExists=<脚本>` 的 unit, 脚本被删时 systemd
    会**跳过不跑**(既不 failed 也无日志)——其 .timer 必须全部进 WATCHMAN_UNITS, 才能被
    check_failed_units 的「脚本存在性」层兜住(与是否注册漏跑无关)。

    快照里实测 3 个: check-monitor-heartbeat / cloud-unit-patrol / r2-consistency。
    """
    snap = (ROOT / "docs" / "deploy" / "systemd-units-cloud-snapshot.txt").read_text(encoding="utf-8")
    blocks = re.split(r"@@@FILE:", snap)[1:]
    cond_units = []
    for b in blocks:
        name = b.split("\n", 1)[0].strip()
        if name.endswith(".service") and re.search(r"^ConditionPathExists=/", b, re.M):
            cond_units.append(name)
    assert cond_units, "快照解析异常: 一个带 ConditionPathExists 的 service 都没找到"
    watchman = {u for u, _ in adr.WATCHMAN_UNITS}
    uncovered = [s for s in cond_units if s.replace(".service", ".timer") not in watchman]
    assert uncovered == [], f"ConditionPathExists unit 的 timer 未进 WATCHMAN_UNITS(脚本被删=静默): {uncovered}"


def test_registry_monitor_tasks_subset_of_gen():
    """schedule_monitor 漏跑表 ⊂ gen_schedule_stats(前者靠后者喂的 stats 判 exit!=0;
    若 monitor 有而 gen 无 = 该任务进不了 schedule_stats = 监控盲区, 正是本族病灶)。"""
    gen_tasks, _ = _gen_registry()
    mon_tasks = _monitor_registry()
    missing = sorted(mon_tasks - gen_tasks)
    assert missing == [], f"schedule_monitor 有但 gen_schedule_stats 无(监控盲区): {missing}"


def test_registry_selfheal_subset_of_gen():
    """self_heal 白名单任务 ⊂ gen_schedule_stats(自愈只处理已登记的失败任务)。"""
    gen_tasks, _ = _gen_registry()
    sh = _selfheal_registry()
    missing = sorted(sh - gen_tasks)
    assert missing == [], f"self_heal 有但 gen_schedule_stats 无: {missing}"