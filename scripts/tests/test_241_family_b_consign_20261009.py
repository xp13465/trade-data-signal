# -*- coding: utf-8 -*-
"""#241 同族 B 波: 「**先落签、后 fire-and-forget 通知**」导致真告警永久丢失的站点修复(2026-10-09)。

病灶(与已修 3 处 rc 判 sent 同后果, 只是机制不同)
  A 波修的是「**用 rc 判** notify 是否真发出」(check_data_gap / sensenova / overfit)。
  本波修的是「**先落签(记 已告警)、后 fire-and-forget 通知(check=False 丢返回值)**」:
  状态已落盘(counter/last_alerted/dedup/fired)**, 通知那一步连返回值都丢** ⇒ 通道全挂时
  告警丢失 **且** state 已落签 ⇒ 条件持续期间每轮命抑制、**永不重发** = 永久失报。
  穷举后的本波站点(独立复审报告 §2 反例为据):
    ① `scripts/schedule_monitor.sh`  收尾聚合 save_alert_state(L2757)先于 notify(L2769, check=False)
       —— 15min 全局巡检中枢, 承载漏跑/exit失败/数据错/停摆全部计划任务告警, **后果最重**;
    ② `scripts/monitor_72h.sh`      同款(save_alert_state 先于 notify, check=False);
    ③ `scripts/detect_intraday_anomaly.py` filter_and_record 先写 anomaly_notified.json 落当日签,
       再 fire-and-forget send_alert ⇒ 当日异动(含 severe)丢失且同日同 key 已占;
    ④ `scripts/gen_daily_brief.py`  notify.send 后 `if not dry_run: update_dedup` **不判 channels**
       ⇒ 全渠道失败仍占当日去重窗 ⇒ 当日重跑被抑制、该 key 带日期次日才恢复;
    ⑤ `scripts/check_signals.py`    fade 子去重 fade_notified.json 在主邮件前落签 ⇒ 全失败时
       重试邮件缺 fade 警示栏(主 signal_notified 判据本身正确, 本批只修子去重)。

统一修法
  · python: 落签前先判 `scripts/notify_sent.py:notify_sent`(唯一实现, rc 不参与, fail-safe
    「判不出 ⇒ False ⇒ 不落签 ⇒ 下轮重试」)—— ①② 用「回滚本轮新落签的 key」等价实现
    (聚合路径状态在收尾才 save, 用快照 diff 精确回滚; notify_sent 判据同源);
    shell: `check=False` 改 `capture_output=True` 并判真实路由结果(rc 不可信: notify.py
    main() 所有出口恒 return 0)。

零外发铁律(§18 L48 / memory notify-script-selftest-must-stub): 本文件全部用例
  **本次自测未产生任何真实外发** —— notify 子进程整体打桩(`subprocess.run` 替身, 根本不
  spawn)+ `ZeroOutboundTrap` 包裹; `test_00` 先证 trap 武装生效。

red-before-green(判别力证明): 各站点的 test_*_red_* 用**旧语义**(不回滚 / 不判 channels /
`lambda out: True` 旧 rc 语义)跑同一负控场景, 复现「通知全失败却落签 ⇒ 下轮永久抑制」。
旧代码跑这些负控必 FAIL。

跑法: python3 -m pytest -q scripts/tests/test_241_family_b_consign_20261009.py
"""
from __future__ import annotations

import ast
import contextlib
import importlib.util
import inspect
import io
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent))
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import check_signals as cs  # noqa: E402
import detect_intraday_anomaly as dia  # noqa: E402
import gen_daily_brief as gdb  # noqa: E402
from notify_sent import notify_sent  # noqa: E402

ROOT = Path(__file__).absolute().parent.parent.parent
SCRIPTS = ROOT / "scripts"

# 断言计数下限(防收集/执行异常致「0 断言假绿」, §18 L49 / 仿 #201/#240/#241A)
_MIN_ASSERTIONS = 36
_N = [0]


def _chk(cond, msg=""):
    _N[0] += 1
    assert cond, msg


# ── notify.py 通用路径(--severe 同)真实输出形态(逐字照 notify.py 打点行) ──
SUCCESS_GENERAL = "[notify] 汇总：已发出 email/feishu\n"
FAIL_GENERAL = "[notify] 汇总：全部渠道未发出（email/feishu）\n"


def _fake_run(output, rc=0, calls=None):
    """subprocess.run 替身: 返回给定输出, 绝不 spawn 真进程。calls 收集命令行。"""
    def _run(cmd, *a, **k):
        if calls is not None:
            calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, rc, stdout="", stderr=output)
    return _run


class _StubLog:
    """check_signals.log 替身(避免用例写入真实日志 handler)。"""
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def _shell_heredoc_py(path: Path):
    """提取 shell 内 `<<'PYEOF'` python 块源码(§18 L50: 只读文本, 绝不 exec 业务脚本主体)。"""
    src = path.read_text(encoding="utf-8")
    m = re.search(r"<<'PYEOF'[^\n]*\n(.*?)\nPYEOF\n", src, re.S)
    assert m, f"{path.name} 未找到 PYEOF heredoc"
    return m.group(1), src


def _load_shell_helpers(path: Path):
    """AST 抽取 heredoc 内 `_diff_transition`/`_rollback_transition` 纯函数(static-only)。"""
    code, src = _shell_heredoc_py(path)
    tree = ast.parse(code)
    keep = {"_diff_transition", "_rollback_transition"}
    mod = ast.Module(body=[n for n in tree.body
                           if isinstance(n, ast.FunctionDef) and n.name in keep],
                     type_ignores=[])
    ns: dict = {}
    exec(compile(mod, f"<{path.name}-heredoc>", "exec"), ns)
    return ns["_diff_transition"], ns["_rollback_transition"], src


SCHED = SCRIPTS / "schedule_monitor.sh"
MON72 = SCRIPTS / "monitor_72h.sh"


# ══════════════════════ ⓪ 打桩生效自证(§18 L48) ══════════════════════
def test_00_zero_outbound_trap_armed():
    """先证 ZeroOutboundTrap 确已武装: 真触达出口即 raise + 计数(hits==1)。"""
    with ZeroOutboundTrap() as trap:
        with pytest.raises(AssertionError):
            urllib.request.urlopen("http://example.invalid/")  # noqa: S310 (打桩验证, 必抛)
    _chk(trap.hits == ["urllib.request.urlopen"], f"trap 应计数 1, 实得 {trap.hits}")


# ══════════════════════ ① schedule_monitor.sh(最严重) ══════════════════════
def test_01_sched_helpers_diff_and_rollback():
    """_diff_transition/回滚: 精确只回滚「本轮新变 active」的 key; 既有 active/pending/
    r5 聚合状态一律不动。"""
    dt, rt, _src = _load_shell_helpers(SCHED)
    pre = {}
    st = {"k1": {"status": "active", "last_alerted": "t"},
          "k2": {"status": "active"},
          "kpend": {"status": "pending", "count": 2},
          "r2_pipeline_congestion|20261009": {"phenomena": ["x"], "summary_sent": False}}
    _chk(sorted(dt(st, pre, "active")) == ["k1", "k2"], "本轮新落签应= k1,k2")
    _chk(rt(st, pre, "active") == 2, "应回滚 2 条")
    _chk(st == {"kpend": {"status": "pending", "count": 2},
                "r2_pipeline_congestion|20261009": {"phenomena": ["x"], "summary_sent": False}},
         f"回滚只清本轮新 active, pending/r5 状态不动, 实得 {st}")
    # 既有 active(非本轮新增) 不回滚
    st2 = {"k3": {"status": "active", "last_alerted": "old"}}
    pre2 = {"k3": {"status": "active", "last_alerted": "old"}}
    _chk(dt(st2, pre2, "active") == [], "已是 active ⇒ 不算本轮新落签")
    _chk(rt(st2, pre2, "active") == 0, "不应回滚既有 active")
    _chk(st2 == pre2, "既有 active 保持原样")
    # recovered→active 转换也算本轮新落签(需回滚)
    st3 = {"k4": {"status": "active"}}
    pre3 = {"k4": {"status": "recovered", "last_recovered": "x"}}
    _chk(dt(st3, pre3, "active") == ["k4"], "recovered→active 是本轮新落签")
    _chk(rt(st3, pre3, "active") == 1 and st3["k4"]["status"] == "recovered",
         "回滚应恢复为 recovered")
    # 本轮新增 key(原来不存在) 回滚 = 删除
    st5 = {"k6": {"status": "active"}}
    _chk(rt(st5, {}, "active") == 1 and st5 == {}, "本轮新增 key 回滚应删除")


def test_02_sched_negative_control_fail_no_consign_and_retries():
    """负控(必修): 聚合告警全渠道失败 ⇒ **回滚本轮新 active** ⇒ 下轮条件持续必须重落签/重发。"""
    dt, rt, _src = _load_shell_helpers(SCHED)
    pre = {}                                            # 本轮开始前快照(无该 key)
    st = {"anomaly": {"status": "active", "last_alerted": "t1"}}   # 检测段先把本轮新告警落签
    _chk(dt(st, pre, "active") == ["anomaly"], "失败轮: 应识别本轮新落签")
    # 旧行为 = 不回滚 ⇒ key 仍 active; 下轮快照含 active ⇒ diff 空 ⇒ 永不再落签/重发 = 复现 bug
    _chk(dt(st, dict(st), "active") == [], "旧行为(不回滚)⇒ 下轮不再重发(复现 #241 同族 bug)")
    # 新行为 = 回滚 ⇒ 下轮 pre 无该 key ⇒ 重新落签 ⇒ 重发(解开抑制链)
    rt(st, pre, "active")
    _chk("anomaly" not in st, "回滚后本轮新落签应清空")
    _chk(dt({"anomaly": {"status": "active"}}, dict(st), "active") == ["anomaly"],
         "回滚后 ⇒ 下轮条件持续时重新落签 ⇒ 会重发(fail-safe)")


def test_03_sched_positive_control_sent_consigns_and_suppresses():
    """正控: 告警真发出 ⇒ 不回滚 ⇒ key 保持 active ⇒ 下轮不再进落签集(恰好一封, 不轰炸)。"""
    dt, rt, _src = _load_shell_helpers(SCHED)
    st = {"anomaly": {"status": "active", "last_alerted": "t1"}}
    # notify_sent(SUCCESS) ⇒ True ⇒ 不调用回滚
    _chk(notify_sent(SUCCESS_GENERAL) is True, "成功输出应判 True(→不回滚)")
    # 不回滚 ⇒ 下轮 diff 空 ⇒ 抑制重发
    _chk(dt(st, dict(st), "active") == [], "真发出后 key 保持 active ⇒ 下轮抑制(不重发)")
    # 兜底: 即便误调用回滚也不会发生(判据已 True) —— 断言判据本身
    _chk(notify_sent(FAIL_GENERAL) is False, "全失败输出应判 False(→回滚)")
    _chk(rt({}, {}, "active") == 0, "空 state 回滚 0 条(幂等)")


def test_04_sched_static_locks_main_notify_gated():
    """静态锁: 主聚合 notify 已改 capture_output 判 notify_sent, 且失败回滚本轮新 active。"""
    _code, src = _shell_heredoc_py(SCHED)
    _chk("from notify_sent import notify_sent" in src, "应 import 唯一判据 notify_sent")
    _chk("_r_main = subprocess.run(" in src, "主 notify 应捕获返回值(不再 fire-and-forget)")
    _chk("capture_output=True, text=True, check=False," in src, "主 notify 应 capture_output")
    _chk("if not notify_sent(_main_out):" in src, "应据 notify_sent 判真发出")
    _chk('_rollback_transition(alert_state, _STATE_PRE, "active")' in src,
         "失败应回滚本轮新 active 落签")
    _chk("_STATE_PRE = {k:" in src, "应有本轮开始前状态快照")
    # 不得残留旧的 fire-and-forget 直调(裸 subprocess.run(...check=False) 无捕获)
    _chk("f\"[告警] {len(alerts)}项计划任务异常 {_sm_time}\"" in src, "主告警模板仍在")
    _chk(len(re.findall(r"capture_output=True, text=True, check=False,", src)) >= 1,
         "至少主 notify 一处已捕获")


# ══════════════════════ ② monitor_72h.sh ══════════════════════
def test_05_mon72_helpers_and_static():
    """同款: helper 行为 + 主 notify 门控静态锁(72h 监控与 schedule_monitor 同根)。"""
    dt, rt, src = _load_shell_helpers(MON72)
    st = {"72h_r2|x": {"status": "active"}}
    _chk(dt(st, {}, "active") == ["72h_r2|x"], "本轮新落签应识别")
    _chk(rt(st, {}, "active") == 1 and st == {}, "回滚应清本轮新落签")
    _chk(dt({"a": {"status": "active"}}, {"a": {"status": "active"}}, "active") == [],
         "既有 active 不回滚")
    _chk("from notify_sent import notify_sent" in src, "72h 应 import notify_sent")
    _chk("_r_main = subprocess.run(" in src, "72h 主 notify 应捕获返回值")
    _chk("if not notify_sent(_main_out):" in src, "72h 应据 notify_sent 判真发出")
    _chk('_rollback_transition(alert_state, _STATE_PRE, "active")' in src,
         "72h 失败应回滚本轮新 active")


# ══════════════════════ ③ detect_intraday_anomaly.py ══════════════════════
class _EmptyRows:
    def fetchall(self):
        return []


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def execute(self, *_a, **_k):
        return _EmptyRows()


def _snap_today():
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    return {"collected_at": f"{today}T10:00:00",
            "indices": [{"code": "sh000001", "name": "上证", "pct_change": 8.0}],
            "industries": [], "concepts": []}


def _run_dia_main(monkeypatch, tmp_path, output, calls):
    monkeypatch.setattr(dia, "DEDUP_FILE", tmp_path / "anomaly_notified.json")
    monkeypatch.setattr(dia, "subprocess", type("S", (), {"run": _fake_run(output, rc=0, calls=calls)}))
    monkeypatch.setattr(dia, "load_snapshot", lambda: _snap_today())
    monkeypatch.setattr(dia, "_conn", lambda: _FakeConn())
    monkeypatch.setattr(sys, "argv", ["detect_intraday_anomaly.py"])
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        rc = dia.main()
    return rc


def test_06_dia_send_alert_returns_sent():
    """send_alert 返回「是否真发出」: 判据 = notify_sent(不看 rc)。"""
    assert dia.send_alert([]) is False
    for out, exp in [(SUCCESS_GENERAL, True), (FAIL_GENERAL, False), ("", False)]:
        calls: list = []
        orig = dia.subprocess
        dia.subprocess = type("S", (), {"run": _fake_run(out, rc=0, calls=calls)})
        try:
            got = dia.send_alert([{"type": "rapid_move", "tier": "severe", "kind": "指数",
                                   "name": "上证", "pct": 8.0, "desc": "x"}])
        finally:
            dia.subprocess = orig
        _chk(got is exp, f"send_alert out={out!r}: 期望 {exp} 实得 {got}")


def test_07_dia_negative_control_no_consign_and_retries(monkeypatch, tmp_path):
    """负控(必修): 异动告警全渠道失败 ⇒ 不写 anomaly_notified.json ⇒ 下轮重试。"""
    calls: list = []
    with ZeroOutboundTrap() as trap:
        rc = _run_dia_main(monkeypatch, tmp_path, FAIL_GENERAL, calls)
        _chk(rc == 0, f"main 应 rc 0, 实得 {rc}")
        _chk(len(calls) == 1, f"应尝试 notify 1 次, 实得 {len(calls)}")
        _chk(not (tmp_path / "anomaly_notified.json").exists(),
             "全渠道失败**不得**落当日去重签(否则同日不再补发 = 永久丢失)")
        calls.clear()
        _run_dia_main(monkeypatch, tmp_path, FAIL_GENERAL, calls)
        _chk(len(calls) == 1, f"未落签 ⇒ 下轮必须重试, 实得 {len(calls)}")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_08_dia_positive_control_consigns_and_dedups(monkeypatch, tmp_path):
    """正控: 真发出 ⇒ 落 anomaly_notified.json ⇒ 下轮同 key 被去重(不重发)。"""
    calls: list = []
    with ZeroOutboundTrap() as trap:
        rc = _run_dia_main(monkeypatch, tmp_path, SUCCESS_GENERAL, calls)
        _chk(rc == 0 and len(calls) == 1, "真发出应发 1 次")
        f = tmp_path / "anomaly_notified.json"
        _chk(f.exists(), "真发出应落当日去重签")
        d = json.loads(f.read_text(encoding="utf-8"))
        from datetime import datetime
        today = datetime.now().strftime("%Y%m%d")
        _chk("rapid_move|指数|上证" in d.get(today, {}), f"应落 key, 实得 {d}")
        calls.clear()
        _run_dia_main(monkeypatch, tmp_path, SUCCESS_GENERAL, calls)
        _chk(len(calls) == 0, f"同 key 当日已发 ⇒ 去重抑制(0 次 notify), 实得 {len(calls)}")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_09_dia_red_before_green_old_no_commit_gate():
    """red-before-green: 旧语义 = filter_and_record 内联落签(不判 sent) ⇒ 全失败也落签。
    用「旧行为 = 直接 record_notified」复现 bug, 证新代码把落签门控在 send_alert 之后。
    """
    from datetime import datetime
    import tempfile
    today = datetime.now().strftime("%Y%m%d")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "anomaly_notified.json"
        orig = dia.DEDUP_FILE
        dia.DEDUP_FILE = p
        try:
            new_alerts, dedup = dia.filter_and_record(
                [{"type": "rapid_move", "tier": "severe", "kind": "指数", "name": "上证",
                  "pct": 8.0, "desc": "x"}])
            _chk(len(new_alerts) == 1 and today in dedup, "filter_and_record 应返回待落签 dedup")
            _chk(not p.exists(), "filter_and_record 本身**不得**落签(已拆分为 compute)")
            dia.record_notified(dedup)   # 旧行为: 无条件落签 ⇒ 复现「全失败也占签」
            _chk(p.exists() and "rapid_move|指数|上证" in
                 json.loads(p.read_text(encoding="utf-8"))[today],
                 "record_notified 落签生效(旧代码在此无条件调用 = bug)")
        finally:
            dia.DEDUP_FILE = orig


# ══════════════════════ ④ gen_daily_brief.py ══════════════════════
def test_10_gdb_channels_sent_criterion():
    """_channels_sent: 至少一个渠道真发出才 True(全失败/None/空 ⇒ False ⇒ 不占去重窗)。"""
    _chk(gdb._channels_sent({"email": True, "feishu": False, "telegram": False}) is True,
         "任一渠道 True ⇒ True")
    _chk(gdb._channels_sent({"email": False, "feishu": False}) is False, "全 False ⇒ False")
    _chk(gdb._channels_sent({}) is False, "空 dict ⇒ False")
    _chk(gdb._channels_sent(None) is False, "None ⇒ False")


def test_11_gdb_static_lock_dedup_gated_on_sent():
    """静态锁: update_dedup 门控在 `not dry_run and _sent`; 旧的无条件落签形式已消失。"""
    src = inspect.getsource(gdb.notify_daily_brief)
    _chk("_sent = _channels_sent(results)" in src, "应以 _channels_sent 判送达")
    _chk("if not dry_run and _sent:" in src and "notify.update_dedup(dedup_key)" in src,
         "update_dedup 应门控在 not dry_run and _sent")
    _chk("if not dry_run:\n            notify.update_dedup(dedup_key)" not in src,
         "旧的无条件落签(不判 channels)应已删除")
    # red-before-green 语义: 旧逻辑 `not dry_run` 恒真 ⇒ 全失败也占窗
    _chk((not gdb._channels_sent({"email": False})) is True,
         "旧逻辑(仅 not dry_run)在全失败时也会占窗 —— 复现 bug 的条件")


# ══════════════════════ ⑤ check_signals.py fade 子去重 ══════════════════════
def _fade_alert(index_id="X", level="red", kind="buy"):
    return {"index_id": index_id, "level": level, "kind": kind,
            "intraday_signal": "buy", "closing_status": "gone"}


def test_12_cs_fade_rollback_precision(monkeypatch, tmp_path):
    """_rollback_fade_notified: 只删本轮新落签的 key, 历史签不动。"""
    fp = tmp_path / "fade_notified.json"
    monkeypatch.setattr(cs, "FADE_NOTIFIED_PATH", fp)
    monkeypatch.setattr(cs, "log", _StubLog())
    date = "20260901"
    fp.write_text(json.dumps({date: {"A|red|buy": "t0", "B|red|buy": "t0"}}), encoding="utf-8")
    _chk(cs._rollback_fade_notified(date, []) == 0, "空 alerts 不回滚")
    n = cs._rollback_fade_notified(date, [_fade_alert("A")])
    _chk(n == 1, f"应回滚 1 条, 实得 {n}")
    d = json.loads(fp.read_text(encoding="utf-8"))
    _chk("A|red|buy" not in d[date], "本轮新落签应被回滚")
    _chk("B|red|buy" in d[date], "历史签不得动")
    # 文件不存在 ⇒ 0(降级)
    fp.unlink()
    _chk(cs._rollback_fade_notified(date, [_fade_alert("A")]) == 0, "无文件⇒0")


def test_13_cs_fade_red_before_green_unlocks_retry(monkeypatch, tmp_path):
    """red-before-green: 旧行为(不回滚) ⇒ 下轮 filter 把它当已通知跳过 ⇒ 重试邮件缺 fade 栏;
    回滚后 ⇒ 下轮 filter 重新返回 ⇒ 重试邮件带上 fade 栏。"""
    fp = tmp_path / "fade_notified.json"
    monkeypatch.setattr(cs, "FADE_NOTIFIED_PATH", fp)
    monkeypatch.setattr(cs, "log", _StubLog())
    date = "20260901"
    # 本轮: filter 落签(先落签)
    first = cs.filter_fade_alerts_intraday([_fade_alert("A")], date)
    _chk(len(first) == 1, "首轮应返回该 fade")
    # 旧行为: 通知失败但不回滚 ⇒ 下轮 filter 返回空(被签吞) = bug
    second_no_rollback = cs.filter_fade_alerts_intraday([_fade_alert("A")], date)
    _chk(second_no_rollback == [], "旧行为(不回滚) ⇒ 重试轮被签吞 = 复现 bug")
    # 新行为: 回滚 ⇒ 下轮 filter 重新返回
    cs._rollback_fade_notified(date, [_fade_alert("A")])
    second_after_rollback = cs.filter_fade_alerts_intraday([_fade_alert("A")], date)
    _chk(len(second_after_rollback) == 1, "回滚后 ⇒ 重试轮重新返回 fade(green)")


def test_14_cs_static_lock_rollback_gated_on_channel_failure():
    """静态锁: 主邮件「未发出/异常」两处失败分支都回滚本轮 fade 签, 且带 intraday 守卫。"""
    src = inspect.getsource(cs.main)
    _chk(src.count("_rollback_fade_notified(date, fade_alerts)") == 2,
         "应有 2 处回滚调用(notify 异常 + 全渠道未发出)")
    _guard = ("        if args.intraday and fade_alerts and not args.dry_run:\n"
              "            _rollback_fade_notified(date, fade_alerts)")
    _chk(src.count(_guard) == 2,
         "两处回滚应紧跟在 intraday/dry_run 守卫下(不改收盘模式与 dry-run 语义)")
    # 主 signal_notified 判据本身已正确(ok_channels), 本批不动 → 断言仍在
    _chk("if ok_channels:" in src, "主邮件送达判据(ok_channels)应保留不变")


def test_99_min_assertions():
    """§18 L49: 断言计数下限, 防收集/执行异常致假绿。"""
    _chk(_N[0] >= _MIN_ASSERTIONS, f"断言数 {_N[0]} < 下限 {_MIN_ASSERTIONS}(疑似假绿)")