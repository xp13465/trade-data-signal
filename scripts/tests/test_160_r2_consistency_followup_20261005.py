#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
#160 收口(preflight 假阳抑制 + 同实例双通道去重 + 连续 2 天升级)真代码断言 —— pytest 版
(2026-10-05, 配套报告 docs/ops/160-r2-consistency-gate-wiring-20261005.md「收口」段)

被验对象(全部打**真实生产函数/脚本**, 不做逻辑模拟):
  - adr.r7_r2_consistency_escalate          (scripts/alert_denoise_rules.py, notify.py 调用侧分级)
  - adr.r7_r2_consistency_wrapper_alerted   (schedule_monitor.sh exit!=0 通道去重判据)
  - check_r2_consistency.sh preflight       (update-all 在跑 → 跳过 + rc=0 + 不告警)

跑法: python3 -m pytest -q scripts/tests/test_160_r2_consistency_followup_20261005.py
"""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

import alert_denoise_rules as adr  # conftest 已注入 scripts/

REPO_ROOT = Path(__file__).absolute().parent.parent.parent
WRAPPER = REPO_ROOT / "scripts" / "check_r2_consistency.sh"


def _dt(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


# ============================================================
# R7① 连续失败天数分级(首日 severe / 连续第 2 日及以后 critical)
# ============================================================
def test_r7_escalate_day1_is_severe(tmp_path):
    """首日失败 → severe(与历史行为一致, 单次失败照发不降噪)。"""
    st = tmp_path / "state.json"
    tier, days, reason = adr.r7_r2_consistency_escalate(st, _dt("2026-10-05 23:21:00"))
    assert (tier, days) == ("severe", 1), reason
    saved = json.loads(st.read_text(encoding="utf-8"))
    assert saved["last_fail_date"] == "2026-10-05"
    assert saved["consecutive_days"] == 1


def test_r7_escalate_day2_is_critical(tmp_path):
    """连续第 2 天失败 → critical(用户拍板「连续 2 天 FAIL 升 critical」)。"""
    st = tmp_path / "state.json"
    adr.r7_r2_consistency_escalate(st, _dt("2026-10-04 23:21:00"))
    tier, days, reason = adr.r7_r2_consistency_escalate(st, _dt("2026-10-05 23:21:00"))
    assert (tier, days) == ("critical", 2), reason
    assert "连续 2 天" in reason


def test_r7_escalate_day3_still_critical(tmp_path):
    """连续第 3 天 → 仍 critical, 天数递增(不回落 severe)。"""
    st = tmp_path / "state.json"
    adr.r7_r2_consistency_escalate(st, _dt("2026-10-03 23:21:00"))
    adr.r7_r2_consistency_escalate(st, _dt("2026-10-04 23:21:00"))
    tier, days, _ = adr.r7_r2_consistency_escalate(st, _dt("2026-10-05 23:21:00"))
    assert (tier, days) == ("critical", 3)


def test_r7_escalate_gap_resets_to_day1(tmp_path):
    """间隔 >1 自然日(中间夹成功日/未跑日)= 连续链中断 → 从 1 重计(反例: 不虚升 critical)。"""
    st = tmp_path / "state.json"
    adr.r7_r2_consistency_escalate(st, _dt("2026-10-01 23:21:00"))
    adr.r7_r2_consistency_escalate(st, _dt("2026-10-02 23:21:00"))
    # 10-03 未失败(成功日: 不调用本函数) → 10-04 再失败应回到第 1 天
    tier, days, _ = adr.r7_r2_consistency_escalate(st, _dt("2026-10-04 23:21:00"))
    assert (tier, days) == ("severe", 1)


def test_r7_escalate_same_day_repeat_no_double_count(tmp_path):
    """同日重复(手动重跑/重试)→ 天数不变(不因重跑虚升)。"""
    st = tmp_path / "state.json"
    adr.r7_r2_consistency_escalate(st, _dt("2026-10-05 23:21:00"))
    tier, days, _ = adr.r7_r2_consistency_escalate(st, _dt("2026-10-05 23:59:00"))
    assert (tier, days) == ("severe", 1)


def test_r7_escalate_state_write_fail_still_returns(tmp_path):
    """状态写失败(父路径是文件)→ 不抛异常, 退回首日 severe(只丢「升级」不丢「告警本身」)。"""
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")     # 文件占了本该是目录的位置
    st = blocker / "state.json"                   # mkdir(parents=True) 必失败
    tier, days, _ = adr.r7_r2_consistency_escalate(st, _dt("2026-10-05 23:21:00"))
    assert (tier, days) == ("severe", 1)


def test_r7_escalate_corrupt_state_treated_as_first_day(tmp_path):
    """状态文件损坏 → 保守当首日(不虚升)。"""
    st = tmp_path / "state.json"
    st.write_text("{not json", encoding="utf-8")
    tier, days, _ = adr.r7_r2_consistency_escalate(st, _dt("2026-10-05 23:21:00"))
    assert (tier, days) == ("severe", 1)


# ============================================================
# R7② 同实例双通道去重判据(包装器已发 → monitor 汇总通道不复述)
# ============================================================
def _write_dedup(repo: Path, last_alerted: str, key=adr.R2_CONSISTENCY_DEDUP_KEY):
    d = repo / "data"
    d.mkdir(parents=True, exist_ok=True)
    (d / "notify_dedup.json").write_text(
        json.dumps({key: {"last_alerted": last_alerted}}), encoding="utf-8")


def test_r7_wrapper_alerted_same_instance_true(tmp_path):
    """包装器告警(23:21)晚于本次运行起点(23:20)→ 已覆盖本次实例 → 抑制(main 场景)。"""
    _write_dedup(tmp_path, "2026-10-05 23:21:10")
    assert adr.r7_r2_consistency_wrapper_alerted(tmp_path, "2026-10-05 23:20") is True


def test_r7_wrapper_alerted_yesterday_still_covers_same_run(tmp_path):
    """失败持续到次日: 昨日告警(last_alerted=昨 23:21)仍 >= 昨日 last_run → 次日全天不复述。

    防「用今天日期判据」的漏洞: 若按「今天」判, 次日早上 monitor 会把同一实例再报一封。
    """
    _write_dedup(tmp_path, "2026-10-04 23:21:10")
    assert adr.r7_r2_consistency_wrapper_alerted(tmp_path, "2026-10-04 23:20") is True


def test_r7_wrapper_alerted_older_than_run_false(tmp_path):
    """反例(真故障不吞): 去重状态是更早一次告警(早于本次 last_run)→ 本次包装器**没发**
    (发送失败 / notify 前被杀) → 返回 False → monitor 汇总通道照发(双保险)。"""
    _write_dedup(tmp_path, "2026-10-04 23:21:10")
    assert adr.r7_r2_consistency_wrapper_alerted(tmp_path, "2026-10-05 23:20") is False


def test_r7_wrapper_alerted_missing_file_false(tmp_path):
    """notify_dedup.json 缺失 → False(fail-open: 宁多告警不漏)。"""
    assert adr.r7_r2_consistency_wrapper_alerted(tmp_path, "2026-10-05 23:20") is False


def test_r7_wrapper_alerted_key_missing_false(tmp_path):
    """去重文件在但无本 key → False。"""
    _write_dedup(tmp_path, "2026-10-05 23:21:10", key="some_other_key")
    assert adr.r7_r2_consistency_wrapper_alerted(tmp_path, "2026-10-05 23:20") is False


def test_r7_wrapper_alerted_corrupt_false(tmp_path):
    """去重文件损坏 → False(fail-open)。"""
    d = tmp_path / "data"
    d.mkdir(parents=True, exist_ok=True)
    (d / "notify_dedup.json").write_text("@@not-json@@", encoding="utf-8")
    assert adr.r7_r2_consistency_wrapper_alerted(tmp_path, "2026-10-05 23:20") is False


def test_r7_wrapper_alerted_bad_last_run_false(tmp_path):
    """last_run 格式异常 → False(fail-open, 不因解析问题吞真告警)。"""
    _write_dedup(tmp_path, "2026-10-05 23:21:10")
    assert adr.r7_r2_consistency_wrapper_alerted(tmp_path, "not-a-time") is False
    assert adr.r7_r2_consistency_wrapper_alerted(tmp_path, "") is False


# ============================================================
# P1-1 preflight 两态(真实脚本周到, 用 R2_CONSISTENCY_PREFLIGHT_STUB 注入判据;
# 云上是生产, 不真 start/stop update-all)
# ============================================================
def _run_wrapper(tmp_path, stub, py=None, path_prefix=None):
    """跑真实包装器: REPO 指向 tmp(日志落 tmp/data/logs), PY 换成 noop 桩(免网络/免真发告警)。

    py=None → 用 tmp 里现造的 `#!/bin/sh exit 0` 桩(忽略参数、恒 rc=0, 绝不触网络/notify)。
    stub: "active"/"inactive"/None(不设 → 走真实判据分支)。
    path_prefix: 把某目录塞到 PATH 最前(用于注入假 systemctl, 走**真实判据代码路径**)。
    """
    if py is None:
        py = tmp_path / "noop_py.sh"
        py.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        py.chmod(0o755)
        py = str(py)
    env = dict(os.environ)
    env["REPO"] = str(tmp_path)
    env["PY"] = py
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env.get('PATH', '')}"
    if stub is None:
        env.pop("R2_CONSISTENCY_PREFLIGHT_STUB", None)
    else:
        env["R2_CONSISTENCY_PREFLIGHT_STUB"] = stub
    p = subprocess.run(["bash", str(WRAPPER)], env=env, capture_output=True, text=True, timeout=120)
    log = tmp_path / "data" / "logs" / "r2_consistency_launchd.log"
    return p, (log.read_text(encoding="utf-8") if log.exists() else "")


def _fake_systemctl(tmp_path, active_state="activating", is_active_rc=3):
    """造一个假 systemctl 注入 PATH: `show -p ActiveState --value` 回 active_state,
    `is-active --quiet` 回 is_active_rc(真实 systemd v249 对运行中 oneshot 就是 3)。

    用途: 让真实脚本的**真实判据分支**(非 stub)在注入态下跑, 而非绕过判据。
    """
    d = tmp_path / "fakebin"
    d.mkdir(exist_ok=True)
    s = d / "systemctl"
    s.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        f'  show) echo "{active_state}"; exit 0 ;;\n'
        f'  is-active) exit {is_active_rc} ;;\n'
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    s.chmod(0o755)
    return d


def test_preflight_active_skips_no_alert(tmp_path):
    """态①: update-all 在跑 → 跳过, rc=0, 日志留 [preflight-skip], 不触发 notify。"""
    p, log = _run_wrapper(tmp_path, "active")
    assert p.returncode == 0, p.stderr
    assert "[preflight-skip]" in log
    assert "trade-update-all 仍在运行" in log
    assert "退出码=0" in log, log
    # 跳过时**不**调用 check_r2_consistency.py(不打网络): log 里无 python 检查输出
    assert "项问题" not in log


def test_preflight_inactive_runs_check(tmp_path):
    """态②: update-all 不在跑 → 照跑(rc=0, 无 [preflight-skip], 有开始/结束行)。"""
    p, log = _run_wrapper(tmp_path, "inactive")
    assert p.returncode == 0, p.stderr
    assert "[preflight-skip]" not in log
    assert "=== check_r2_consistency.sh 开始" in log
    assert "退出码=0" in log, log


def test_preflight_real_judge_activating_skips(tmp_path):
    """改后判据(真实代码路径, 注入 ActiveState=activating): 必须 **跳过**(=return 0)。

    这是 P0 修复的核心证明: oneshot 运行中 ActiveState=activating, 判据须吃到它。
    """
    fake = _fake_systemctl(tmp_path, active_state="activating", is_active_rc=3)
    p, log = _run_wrapper(tmp_path, None, path_prefix=str(fake))
    assert p.returncode == 0, p.stderr
    assert "[preflight-skip]" in log, "activating 态未被判为在跑(P0 未修)"


def test_preflight_real_judge_active_skips(tmp_path):
    """改后判据: ActiveState=active(长驻服务运行中)同样跳过。"""
    fake = _fake_systemctl(tmp_path, active_state="active", is_active_rc=0)
    p, log = _run_wrapper(tmp_path, None, path_prefix=str(fake))
    assert p.returncode == 0, p.stderr
    assert "[preflight-skip]" in log


def test_preflight_old_judge_would_miss_activating(tmp_path):
    """改前对照(证明 P0 机制非臆测): 同一注入态下旧判据 `is-active --quiet` rc=3
    ⇒ 旧写法 `&& return 0` 恒不成立 ⇒ 跳过分支是死代码。"""
    fake = _fake_systemctl(tmp_path, active_state="activating", is_active_rc=3)
    env = dict(os.environ)
    env["PATH"] = f"{fake}{os.pathsep}{env.get('PATH', '')}"
    old = subprocess.run(
        ["bash", "-c", "systemctl is-active --quiet trade-update-all.service; echo rc=$?"],
        env=env, capture_output=True, text=True)
    assert "rc=3" in old.stdout, old.stdout
    # 旧写法语义复现: rc!=0 → 不 return 0 → 「不在跑」
    newstyle = subprocess.run(
        ["bash", "-c",
         'st=$(systemctl show -p ActiveState --value trade-update-all.service); echo "st=$st"'],
        env=env, capture_output=True, text=True)
    assert "st=activating" in newstyle.stdout, newstyle.stdout


def test_preflight_inactive_state_runs_check(tmp_path):
    """改后判据: ActiveState=inactive → 不跳过, 照跑(不误跳)。"""
    fake = _fake_systemctl(tmp_path, active_state="inactive", is_active_rc=3)
    p, log = _run_wrapper(tmp_path, None, path_prefix=str(fake))
    assert "[preflight-skip]" not in log
    assert "退出码=0" in log


def test_preflight_real_judge_branch_runs_on_non_systemd(tmp_path):
    """不注入 stub / 无 systemctl(本机 mac)→ 回退 pgrep 探测判定非在跑 → 照跑(不误跳)。"""
    if shutil_which("systemctl"):
        pytest.skip("本机有 systemctl, 走真实 systemd 判据(云上两态证据见报告)")
    p, log = _run_wrapper(tmp_path, None)
    assert "[preflight-skip]" not in log
    assert "退出码=0" in log


def shutil_which(name):
    from shutil import which
    return which(name)


def test_wrapper_preflight_end_line_matches_stats_regex(tmp_path):
    """preflight 跳过写的开始/结束行必须仍被 gen_schedule_stats 的 START_RE/END_RE 解析
    (否则跳过会被误判漏跑 / 读不到退出码)。"""
    import re
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import importlib
    gss = importlib.import_module("gen_schedule_stats")
    p, log = _run_wrapper(tmp_path, "active")
    assert p.returncode == 0
    assert gss.START_RE.search(log), "preflight 跳过的开始行未被 START_RE 解析"
    m = gss.END_RE.search(log)
    assert m, "preflight 跳过的结束行未被 END_RE 解析"
    assert m.group(3) == "0", f"结束行退出码应=0, 实得 {m.group(3)}"


# ============================================================
# notify.py R7① 拦截端到端(真实 notify.main, 打桩渠道; 生产隔离: REPO 指 tmp + 不真发)
# ============================================================
def _run_notify_main(tmp_path, monkeypatch, grade=("severe", 1, "首日失败"),
                     send_tiered=None, check_dedup=None, update_dedup=None,
                     subject="[告警] §22 三站一致性校验失败", body="明细"):
    """跑真实 notify.main(拦截逻辑走真实代码), 只把「渠道」与「分级函数」打桩。

    分级函数打桩理由(同 test_notify_r4_dedup 先例): r7_r2_consistency_escalate 的日期
    推演已由本文件独立单测覆盖; 此处要验的是 notify.py 的**拦截接线**(首日落回 / 升级走
    critical / 窗口抑制), 若用它真实日期逻辑则测试结果绑定"今天", 跨日必坏。
    """
    import notify
    monkeypatch.setenv("REPO", str(tmp_path))
    captured = {"tiered": [], "generic": [], "dedup": [], "grade_calls": []}
    monkeypatch.setattr(notify.adr, "r7_r2_consistency_escalate",
                        lambda state_path, now:
                            captured["grade_calls"].append(str(state_path)) or grade)
    if send_tiered is not None:
        monkeypatch.setattr(notify, "send_tiered",
                            lambda s, b, tier=notify.TIER_CRITICAL, **kw:
                                captured["tiered"].append((s, b, tier)) or send_tiered(s, b, tier, **kw))
    if check_dedup is not None:
        monkeypatch.setattr(notify, "check_dedup", check_dedup)
    if update_dedup is not None:
        monkeypatch.setattr(notify, "update_dedup",
                            lambda k: captured["dedup"].append(k) or update_dedup(k))
    monkeypatch.setattr(notify, "send",
                        lambda s, b, **kw: captured["generic"].append((s, b, kw)) or
                        {"email": True, "telegram": False, "feishu": False})
    rc = notify.main([subject, body, "--severe", "--from-prefix", "[告警]",
                      "--dedup-key", adr.R2_CONSISTENCY_DEDUP_KEY, "--dedup-window", "21600"])
    return rc, captured


def test_notify_r7_day1_falls_through_to_severe(tmp_path, monkeypatch):
    """首日 FAIL: R7 块不拦截 → 走通用 --severe 路径(与历史行为一字不差, 只发 1 封)。"""
    rc, cap = _run_notify_main(
        tmp_path, monkeypatch, grade=("severe", 1, "首日失败"),
        send_tiered=lambda s, b, t, **kw: {"email": True, "feishu": True},
        check_dedup=lambda k, w: False, update_dedup=lambda k: None)
    assert rc == 0
    assert len(cap["grade_calls"]) == 1, "首日也应调分级函数(写连续天数状态)"
    assert cap["tiered"] == [], "首日不应走 critical 升级档"
    assert len(cap["generic"]) == 1, "首日应走通用 severe 通道 1 封"


def test_notify_r7_day2_escalates_to_critical(tmp_path, monkeypatch):
    """连续第 2 天 FAIL: 升 critical(独立 key + 同步占首日 key) 且只发 1 封。"""
    rc, cap = _run_notify_main(
        tmp_path, monkeypatch, grade=("critical", 2, "连续 2 天一致性校验失败"),
        send_tiered=lambda s, b, t, **kw: {"email": True, "feishu": True},
        check_dedup=lambda k, w: False, update_dedup=lambda k: None)
    assert rc == 0
    assert len(cap["tiered"]) == 1, "第 2 天应走 critical 升级档 1 封"
    assert cap["tiered"][0][2] == "critical"
    assert "连续 2 天" in cap["tiered"][0][0], cap["tiered"][0][0]
    assert cap["generic"] == [], "升级日不应再走通用通道(否则双发)"
    assert adr.R2_CONSISTENCY_ESCALATED_DEDUP_KEY in cap["dedup"]
    assert adr.R2_CONSISTENCY_DEDUP_KEY in cap["dedup"], "升级日须同步占首日 key(供 monitor 去重)"


def test_notify_r7_escalated_window_suppresses(tmp_path, monkeypatch):
    """升 critical 档在独立窗口内已发 → suppress(不重复轰炸)。"""
    rc, cap = _run_notify_main(
        tmp_path, monkeypatch, grade=("critical", 2, "连续 2 天一致性校验失败"),
        send_tiered=lambda s, b, t, **kw: {"email": True, "feishu": True},
        check_dedup=lambda k, w: k == adr.R2_CONSISTENCY_ESCALATED_DEDUP_KEY,  # 升级档窗口内
        update_dedup=lambda k: None)
    assert rc == 0
    assert cap["tiered"] == [] and cap["generic"] == [], "窗口内应 suppress, 不发任何档"


# ============================================================
# R7② 同实例去重「两态实测」: 同一 FAIL 走两通道 → 只 1 封(不吞真故障的另一态)
# ============================================================
def test_two_channels_one_alert_normal_state(tmp_path):
    """态①(正常): 包装器通道发成功(写 notify_dedup) → monitor 汇总通道抑制 → 合计 1 封。"""
    alerts = []
    # 通道①: 包装器发出 severe(成功 → update_dedup 写 last_alerted)
    _write_dedup(tmp_path, "2026-10-05 23:21:10")
    alerts.append("wrapper")
    # 通道②: monitor exit!=0 汇总(判据 = R7② 真实函数)
    if not adr.r7_r2_consistency_wrapper_alerted(tmp_path, "2026-10-05 23:20"):
        alerts.append("monitor")
    assert alerts == ["wrapper"], "同实例应只 1 封(monitor 复述被抑制)"


def test_two_channels_one_alert_wrapper_send_failed(tmp_path):
    """态②(反例): 包装器告警发送失败(未写 notify_dedup) → monitor 汇总通道照发 → 仍 1 封。

    证明抑制只砍「重复的第二条通道」, 真故障判别维度不被削弱(L46/降噪铁律)。
    """
    alerts = []
    # 通道①: 包装器发送失败 → update_dedup 不调用 → notify_dedup 无记录
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    alerts.append("wrapper_intent")     # 意图发了但没成功 = 用户没收到
    # 通道②: monitor exit!=0 汇总
    if not adr.r7_r2_consistency_wrapper_alerted(tmp_path, "2026-10-05 23:20"):
        alerts.append("monitor")
    assert "monitor" in alerts, "包装器没发成功时 monitor 必须兜底(不吞真故障)"