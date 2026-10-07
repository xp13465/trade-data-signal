# -*- coding: utf-8 -*-
"""#232 `schedule_monitor.sh` `marker_buffer` degrade 连续轮计数 —— seen 缺失根因修复回归测试(2026-10-07)。

背景(只读定性 `docs/ops/232-markerbuffer-qualitative-20261007.md`):`marker_buffer` 计数桶
   `{task}|marker_buffer` **从未 `seen_keys_this_run.add`** ⇒ 主恢复循环(schedule_monitor.sh
   L1676-1684)每 tick 对「pending 且未 seen 且非 `r2_`/`72h_` 前缀」的桶键翻 recovered ⇒ 下
   tick L768 `else` 分支把 count 重置恒 1 ⇒ **SEVERE 结构性不可达(零报/假阴性)**。生产两桶
   `first_seen == last_recovered` 同秒(09-29 09:30:00 / 10-06 02:00:01)为物证。
   **修法 = 候选 A(计数桶补 seen,1 行)**;候选 C(照抄 #181 轮去重)**禁用**(会把单 run 长跑
   压成 1 次,45min 卡死哨彻底消失 —— 本链计数对象是 **tick 轮**,与 r2_skip 的 run 轮语义不同)。

取用方式(防第二份实现漂移,memory repro-script-second-implementation-drift):
   从 `scripts/schedule_monitor.sh` 的内嵌 python heredoc 里 **ast 提取** ① `_recurrence_suppressed`
   真函数 + ② `if s.get("log_anomaly"):` / `if not s.get("log_anomaly"):` 两整块(含 degrade 计数桶
   + inline 复位)**真源码**后 exec(同一份实现,不抄副本),与 test_181/test_228 同法。

零外发铁律(§18 L48/L50):static-only —— 只读文件 + exec 提取出的**纯逻辑块**(该块只 append 到
   `alerts` list、改 alert_state dict,**无任何 notify/网络/子进程**);本测试用 subprocess/urllib/
   socket 打桩「一调用即 AssertionError」+ 调用计数兜底证明本次自测零真实外发。

红先验可复现(§18 L49 检出力):本测试支持 `SCHEDULE_MONITOR_SH` 环境变量覆盖被读脚本路径。
   `git show HEAD:scripts/schedule_monitor.sh > /tmp/pre232.sh; SCHEDULE_MONITOR_SH=/tmp/pre232.sh
   python3 -m pytest -q scripts/tests/test_232_marker_buffer_20261007.py` ⇒ 源码断言 + 可达性用例
   必须 FAIL;换回修复版 ⇒ PASS。**修复前不可达 / 修复后可达** 的成对证据同时以
   `test_negative_control_without_seen_unreachable`(运行期剥掉 seen 行)永久钉在文件内。
"""
import ast
import copy
import datetime
import hashlib
import os
import socket
import subprocess
import textwrap
import urllib.request
from collections import namedtuple
from pathlib import Path

import pytest

ROOT = Path(__file__).absolute().parent.parent.parent
# 支持 red-先验覆盖(默认读工作树真文件; 覆盖仅改"读哪个文件", 不改变任何逻辑)
MONITOR = Path(os.environ.get("SCHEDULE_MONITOR_SH", str(ROOT / "scripts" / "schedule_monitor.sh")))

TASK = "fetch_news"
BUCKET = f"{TASK}|marker_buffer"
Rec = namedtuple("Rec", "T alerts seen bucket state")

# 断言下限(仿 #201/#193/test_181 薄包装范式, 防收集/执行异常致「0 断言假绿」)
_MIN_ASSERTIONS = 40
_N = [0]


def _chk(cond, msg=""):
    _N[0] += 1
    assert cond, msg


# ══════════════════════ 提取真源码块 + 常量(static-only, 不 exec 业务脚本主体) ══════════════════════

def _heredoc_lines():
    text = MONITOR.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    h0 = next(i for i, l in enumerate(lines) if "<<'PYEOF'" in l)
    h1 = next(i for i, l in enumerate(lines) if i > h0 and l.strip() == "PYEOF")
    return lines[h0 + 1:h1]


def _extract_parts():
    """返回 (block_src, func_src, consts)。block_src = 两整块去缩进拼接(纯逻辑, 无外发出口)。"""
    slines = _heredoc_lines()
    src = "".join(slines)
    tree = ast.parse(src)
    loop = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.For) and isinstance(n.iter, ast.Name) and n.iter.id == "stats"
        and any(isinstance(st, ast.If) and "log_anomaly_severity" in (ast.get_source_segment(src, st) or "")
                for st in ast.walk(n))
    )

    def _seg_raw(node):
        return "".join(slines[node.lineno - 1:node.end_lineno])

    if_a = next(st for st in loop.body
                if isinstance(st, ast.If) and ast.get_source_segment(src, st.test) == 's.get("log_anomaly")')
    if_b = next(st for st in loop.body
                if isinstance(st, ast.If) and ast.get_source_segment(src, st.test) == 'not s.get("log_anomaly")')
    block_src = textwrap.dedent(_seg_raw(if_a)) + textwrap.dedent(_seg_raw(if_b))
    ast.parse(block_src)  # 提取块须为合法 python(防 heredoc 结构漂移)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_recurrence_suppressed")
    func_src = ast.get_source_segment(src, fn)
    consts = {}
    for name in ("TRANSIENT_TIMEOUT_THRESHOLD", "STALE_EXIT_THRESHOLD", "RECOVERY_COOLDOWN"):
        node = next((n for n in ast.walk(tree)
                     if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == name), None)
        assert node is not None, f"schedule_monitor.sh 缺常量 {name}(被改名/删除? 本测试锚点需同步)"
        exec(ast.get_source_segment(src, node), {"timedelta": datetime.timedelta}, consts)  # noqa: S102
    assert set(consts) == {"TRANSIENT_TIMEOUT_THRESHOLD", "STALE_EXIT_THRESHOLD", "RECOVERY_COOLDOWN"}
    return block_src, func_src, consts


_PARTS = None


def _parts():
    global _PARTS
    if _PARTS is None:
        _PARTS = _extract_parts()
    return _PARTS


def _compile(block_src, func_src):
    return compile(func_src + "\n" + block_src, "<mb-block>", "exec")


@pytest.fixture(scope="module")
def extracted():
    return _parts()


@pytest.fixture(scope="module")
def code(extracted):
    block_src, func_src, _ = extracted
    return _compile(block_src, func_src)


@pytest.fixture(scope="module")
def consts(extracted):
    return extracted[2]


# ══════════════════════ 驱动:逐 tick exec 真块 + 模拟通用恢复循环 ══════════════════════

def _degrade(anomaly=True, severity="degrade", keyword="ConnectionError", line="X" * 90, last_run=None):
    """构造一条 stats 条目(贴近 gen_schedule_stats 真实字段)。"""
    s = {"task": TASK}
    if anomaly:
        s["log_anomaly"] = True
        if severity is not None:
            s["log_anomaly_severity"] = severity
        s["log_anomaly_keyword"] = keyword
        s["log_anomaly_line"] = line
        s["last_run"] = last_run
    return s


def _simulate_recovery_loop(st, seen, T, in_progress=frozenset()):
    """忠实复刻 schedule_monitor.sh L1670-1737 的**状态翻转**语义(不发邮件, 邮件与断言无关):
      pending 未 seen 且非 r2_/72h_ 前缀 ⇒ recovered;  active 未 seen 且非特殊前缀 ⇒ recovered。
    前两个 continue 是 L1673 的 merge/congestion 豁免。"""
    for k, info in list(st.items()):
        if k.startswith("merge|") or k.startswith("r2_pipeline_congestion|"):
            continue
        if info.get("status") == "pending":
            if k.startswith("r2_") or k.startswith("72h_"):
                continue
            if k not in seen:
                info["status"] = "recovered"
                info["last_recovered"] = T.strftime("%Y-%m-%d %H:%M:%S")
            continue
        if info.get("status") != "active":
            continue
        if (k == "overview_lag_3domain" or k.startswith("r2_") or k.startswith("72h_")
                or k.startswith("feishu_")):
            continue
        if "|" in k and k.split("|", 1)[0] in in_progress:
            continue
        if k not in seen:
            info["status"] = "recovered"
            info["last_recovered"] = T.strftime("%Y-%m-%d %H:%M:%S")


def _drive(block_code, ticks, consts, pre_state=None, in_progress=frozenset()):
    """ticks = list[(datetime, stats_entry)]; 返回 list[Rec]。每 tick 后模拟恢复循环(真语义)。"""
    st = dict(pre_state or {})
    recs = []
    for T, entry in ticks:
        seen = set()
        run = {
            "datetime": datetime.datetime, "timedelta": datetime.timedelta, "hashlib": hashlib,
            "TRANSIENT_TIMEOUT_THRESHOLD": consts["TRANSIENT_TIMEOUT_THRESHOLD"],
            "STALE_EXIT_THRESHOLD": consts["STALE_EXIT_THRESHOLD"],
            "RECOVERY_COOLDOWN": consts["RECOVERY_COOLDOWN"],
            "alerts": [], "alert_state": st, "seen_keys_this_run": seen,
            "NOW": T, "print": (lambda *a, **k: None), "s": entry,
            "exit_code": entry.get("last_exit"),
        }
        exec(block_code, run)  # noqa: S102
        before = dict(st.get(BUCKET) or {})  # 本 tick 计数分支刚写入的桶(恢复循环前)
        _simulate_recovery_loop(st, seen, T, in_progress)
        # Rec.bucket = 恢复循环后的桶状态(反映"存活到下一 tick"的真值); state = 恢复循环后全量
        recs.append(Rec(T, list(run["alerts"]), set(seen), before, copy.deepcopy(st)))
    return recs


def _t(hm, day="2026-11-02", last_run=None, **kw):
    T = datetime.datetime.strptime(f"{day} {hm}", "%Y-%m-%d %H:%M")
    lr = last_run if last_run is not None else T.strftime("%Y-%m-%d %H:%M")
    return (T, _degrade(last_run=lr, **kw))


def _clean(hm, day="2026-11-02"):
    T = datetime.datetime.strptime(f"{day} {hm}", "%Y-%m-%d %H:%M")
    return (T, _degrade(anomaly=False))


# ══════════════════════ t1 源码断言(§23.2 防误移植 + 阈值不动) ══════════════════════

def test_source_has_seen_and_no_round_dedup(extracted, consts):
    """修复标记:计数块含 `seen_keys_this_run.add(_bk)`; 且**不含**候选 C 的轮去重特征
    (`last_round`/`skip_rounds`) —— 本链计数对象是 tick 轮, 照抄 #181 会换种方式废掉该链。"""
    block_src, _, _ = extracted
    _chk("seen_keys_this_run.add(_bk)" in block_src, "缺计数桶 seen 补全(候选 A 未落地)")
    _chk("last_round" not in block_src, "误移植候选 C 轮去重(last_round)")
    _chk("skip_rounds" not in block_src, "误移植候选 C 轮去重(skip_rounds)")
    _chk('"consecutive_count": 0' in block_src, "inline 复位未显式清 count")
    _chk(consts["TRANSIENT_TIMEOUT_THRESHOLD"] == 3, "阈值被改动(应保持 3)")
    _chk(consts["RECOVERY_COOLDOWN"] == datetime.timedelta(hours=6), "RECOVERY_COOLDOWN 漂移")


def test_generic_recovery_loop_untouched():
    """不串味前置:通用恢复循环的 pending 分支必须仍带 r2_/72h_ 前缀豁免 + 未 seen 判据
    (本任务只动 marker_buffer 局部, 不得碰这条 30 天 121 次 silent recovery 的公共路径)。"""
    src = MONITOR.read_text(encoding="utf-8")
    _chk('if _key.startswith("r2_") or _key.startswith("72h_"):' in src, "恢复循环前缀豁免被删")
    _chk("if _key not in seen_keys_this_run:" in src, "恢复循环未 seen 判据被删")
    # 本任务不得给 marker_buffer 加前缀豁免(应靠 seen 局部解决, 而非动通用代码)
    _chk('.startswith("marker_buffer")' not in src, "marker_buffer 被加前缀豁免(越界动通用代码)")


# ══════════════════════ t2 可达性:修复后可达 / 修复前不可达(成对) ══════════════════════

def test_reachability_three_degrade_ticks_fire_severe(code, consts):
    """可达性(修复后):连续 3 个 degrade tick ⇒ count 1→2→3, 第 3 tick append SEVERE 恰 1 次。"""
    recs = _drive(code, [_t("10:00"), _t("10:15"), _t("10:30")], consts)
    _chk(recs[0].bucket.get("consecutive_count") == 1, f"t1 count={recs[0].bucket}")
    _chk(recs[0].bucket.get("status") == "pending")
    _chk(recs[1].bucket.get("consecutive_count") == 2, f"t2 count={recs[1].bucket}")
    _chk(recs[2].bucket.get("consecutive_count") == 3, f"t3 count={recs[2].bucket}")
    _chk(recs[2].bucket.get("status") == "alerted", f"t3 status={recs[2].bucket}")
    _chk(all(not r.alerts for r in recs[:2]), "阈值前不得告警")
    _chk(len(recs[2].alerts) == 1, f"第3 tick 应恰好 1 封 SEVERE, got {recs[2].alerts}")
    msg = recs[2].alerts[0]
    _chk(msg.startswith(f"SEVERE: {TASK} log异常关键词<ConnectionError>"), f"告警正文头部: {msg}")
    _chk("已连续3轮未自愈" in msg, f"告警正文轮数不符: {msg}")
    _chk("(阈值3)" in msg, f"告警正文阈值不符: {msg}")


def test_negative_control_without_seen_unreachable(extracted, consts):
    """**检出力/红先验(文件内永久版)**:运行期剥掉 `seen_keys_this_run.add(_bk)` 行(还原修复前
    语义)⇒ 主恢复循环每 tick 误翻桶 ⇒ count 恒 1、SEVERE 结构性不可达。证明该 1 行是承重的。"""
    block_src, func_src, _ = extracted
    stripped = "".join(l for l in block_src.splitlines(keepends=True)
                       if "seen_keys_this_run.add(_bk)" not in l)
    _chk(stripped != block_src, "未见行可剥(源码结构漂移)")
    code_old = _compile(stripped, func_src)
    recs = _drive(code_old, [_t("10:00"), _t("10:15"), _t("10:30")], consts)
    for i, r in enumerate(recs):
        _chk(r.bucket.get("consecutive_count") == 1, f"修复前 tick{i} count={r.bucket} (应恒1)")
        _chk(r.state.get(BUCKET, {}).get("status") == "recovered",
             f"修复前 tick{i} 桶应被恢复循环翻 recovered: {r.state.get(BUCKET)}")
    _chk(all(not r.alerts for r in recs), "修复前不得有 SEVERE(结构性不可达)")


def test_suppress_after_threshold_no_repeat(code, consts):
    """达阈后持续 degrade ⇒ dedup_key 持续 active(seen 保护)⇒ 不重发(SUPPRESS)。"""
    recs = _drive(code, [_t("10:00"), _t("10:15"), _t("10:30"), _t("10:45"), _t("11:00")], consts)
    _chk(len(recs[2].alerts) == 1, "第3 tick 首报")
    for i in (3, 4):
        _chk(not recs[i].alerts, f"tick{i} 达阈后不得重发 SEVERE")
        _chk(recs[i].bucket.get("status") == "alerted", f"tick{i} 桶应保持 alerted")
    dedup_active = [k for k, v in recs[4].state.items() if v.get("status") == "active"]
    _chk(len(dedup_active) == 1, f"dedup_key active 数={len(dedup_active)} (feeder 每任务仅1 active)")
    _chk(dedup_active[0].startswith(f"{TASK}|ConnectionError|"), f"dedup_key 形态漂移: {dedup_active}")
    _chk(dedup_active[0] in recs[4].seen, "dedup_key 须 mark seen(防假恢复)")


# ══════════════════════ t3 复位语义:真复位 + 复位后仍可再达阈 ══════════════════════

def test_reset_on_clean_tick(code, consts):
    """复位:本轮无 log_anomaly ⇒ inline 块把桶翻 recovered 且 count 归 0(真复位)。"""
    recs = _drive(code, [_t("10:00"), _t("10:15"), _clean("10:30")], consts)
    _chk(recs[1].bucket.get("consecutive_count") == 2)
    _chk(recs[2].bucket.get("status") == "recovered", f"clean tick 应复位: {recs[2].bucket}")
    _chk(recs[2].bucket.get("consecutive_count") == 0, f"复位应清 count: {recs[2].bucket}")
    _chk(all(not r.alerts for r in recs), "两轮 degrade 不足阈 + 复位不得告警")


def test_reset_then_reaccumulate_fires(code, consts):
    """复位后再次累积仍能到 3:degrade x2 → clean → degrade x3 ⇒ 仅第二条链第3 tick 告警
    (证明无「残留续数」假升级 —— 复位真生效, 不是「只加不减、永不复位」)。"""
    ticks = [_t("10:00"), _t("10:15"), _clean("10:30"),
             _t("10:45"), _t("11:00"), _t("11:15")]
    recs = _drive(code, ticks, consts)
    _chk(recs[3].bucket.get("consecutive_count") == 1, f"复位后应重新从1起: {recs[3].bucket}")
    _chk(all(not r.alerts for r in recs[:5]), "前5 tick(含复位)不得告警")
    _chk(len(recs[5].alerts) == 1, f"第二条链第3 tick 应告警: {recs[5].alerts}")
    _chk(recs[5].bucket.get("consecutive_count") == 3)


def test_single_degrade_never_fires_no_residue(code, consts):
    """单 tick degrade(±复位)⇒ 永不 SEVERE、无残留(防抖语义保持)。"""
    recs = _drive(code, [_t("10:00"), _clean("10:15"), _clean("10:30")], consts)
    _chk(all(not r.alerts for r in recs), "单次瞬态不得告警")
    _chk(recs[0].bucket.get("consecutive_count") == 1)
    _chk(recs[2].bucket.get("consecutive_count") == 0, "复位后归 0")


def test_two_ticks_then_break_no_false_positive(code, consts):
    """边界:恰好 2 tick(30min)degrade 后链断 ⇒ 不得 SEVERE(45min 哨未被提前触发)。"""
    recs = _drive(code, [_t("10:00"), _t("10:15"), _clean("10:30"), _clean("10:45")], consts)
    _chk(all(not r.alerts for r in recs), "2 轮不足 3 轮阈值不得告警")


# ══════════════════════ t4 判别力/不误报:非 degrade / 无异常任务不被计数 ══════════════════════

def test_clean_task_never_counted(code, consts):
    """无 anomaly 的任务:桶根本不创建, 且不产生任何告警。"""
    recs = _drive(code, [_clean("10:00"), _clean("10:15"), _clean("10:30")], consts)
    for r in recs:
        _chk(r.bucket == {}, f"无异常任务不得建桶: {r.bucket}")
        _chk(not r.alerts, "无异常任务不得告警")


def test_non_degrade_anomaly_not_counted(code, consts):
    """critical(真失败)severity:走既有直报通道, **不进 marker_buffer 计数**(不拖 45min);
    连续 3 tick critical ⇒ 直报 1 封(既有 dedup active 抑制), 桶始终为空。"""
    recs = _drive(code, [_t("10:00", severity=None), _t("10:15", severity=None), _t("10:30", severity=None)],
                  consts)
    _chk(len(recs[0].alerts) == 1, "critical 首报零延迟")
    _chk(all(not r.alerts for r in recs[1:]), "critical 持续不重发")
    for r in recs:
        _chk(r.bucket == {}, f"critical 不得进 marker_buffer 桶: {r.bucket}")


def test_boundary_two_vs_three_ticks(code, consts):
    """阈值边界钉死:2 tick=30min 不报 / 3 tick=45min 报(与 r2_lag「连续>=3轮≈45min」同族口径)。"""
    r2 = _drive(code, [_t("10:00"), _t("10:15")], consts)
    _chk(all(not r.alerts for r in r2), "30min 不得报")
    r3 = _drive(code, [_t("10:00"), _t("10:15"), _t("10:30")], consts)
    _chk(len(r3[2].alerts) == 1, "45min 必报")


# ══════════════════════ t5 不与其他链串味 ══════════════════════

def test_seen_set_contains_only_own_keys(code, consts):
    """seen 集合不泄漏:一次 degrade tick 只标记 本桶 key + log_anomaly dedup_key, 别无他物。"""
    recs = _drive(code, [_t("10:00")], consts)
    seen = recs[0].seen
    _chk(BUCKET in seen, f"桶未 mark seen: {seen}")
    others = [k for k in seen if k != BUCKET]
    _chk(all("|marker_buffer" not in k for k in others), f"误标记其他桶: {others}")
    _chk(len(others) == 1 and others[0].startswith(f"{TASK}|ConnectionError|"),
         f"degrade tick 的 seen 应=桶+log_anomaly dedup: {seen}")


def test_r2_and_72h_prefix_protection_holds(code, consts):
    """前缀保护边界:恢复循环模拟下, pending 的 r2_*/72h_* key 不被翻; 本桶照常被处理。"""
    pre = {"r2_something|buffer|20261102": {"status": "pending", "consecutive_count": 2},
           "72h_r2_prefix_demo": {"status": "pending"},
           BUCKET: {"status": "pending", "consecutive_count": 1}}
    recs = _drive(code, [_t("10:00")], consts, pre_state=pre)
    end = recs[-1].state
    _chk(end["r2_something|buffer|20261102"]["status"] == "pending", "r2_ 前缀被误翻")
    _chk(end["72h_r2_prefix_demo"]["status"] == "pending", "72h_ 前缀被误翻")
    _chk(end[BUCKET]["consecutive_count"] == 2, f"本桶应正常累积: {end[BUCKET]}")
    _chk(end[BUCKET]["status"] == "pending")


# ══════════════════════ t6 零真实外发自证(§18 L48/L50) ══════════════════════

def test_zero_real_outbound(code, consts, monkeypatch):
    """打桩 subprocess/urllib/socket「一调用即 AssertionError」+ 调用计数 ⇒ 证明本次自测零真实
    外发(该块结构上无外发出口; 此断言为硬闸兜底)。"""
    calls = {"n": 0}

    def _boom(*a, **k):
        calls["n"] += 1
        raise AssertionError("自测发生真实外发/子进程 —— 违反 §18 L48 零外发约束")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)
    recs = _drive(code, [_t("10:00"), _t("10:15"), _t("10:30")], consts)
    _chk(calls["n"] == 0, f"发生外发调用 {calls['n']} 次")
    _chk(len([1 for r in recs if r.alerts]) == 1)


# ══════════════════════ 断言下限守卫(防 0 断言假绿) ══════════════════════

def test_min_assertions_guard():
    """末位执行:确认上面确实跑了足量断言(收集/执行异常会让 _N 停在低位)。"""
    assert _N[0] >= _MIN_ASSERTIONS, \
        f"#232 自验仅 {_N[0]} 条断言(下限 {_MIN_ASSERTIONS}), 疑似收集/执行异常"