# -*- coding: utf-8 -*-
"""#181 `fetch_news` R2 skip SEVERE 告警降噪 —— r2_skip 状态机 ①d 回归测试(2026-10-07)。

背景(调研判决 `docs/ops/181-fetchnews-denoise-verdict-20261007.md`):fetch_news :01/:45 两轮 +
monitor 30min 新鲜窗 + :45 stale 三重叠加 ⇒ 同一个真 skip 轮被 3 个 tick 各计 1 次 ⇒
13/13 SEVERE 实为 `counted=3, distinctRounds=2`(消息自称「连续 3 轮」是假话);且 stale 分支
不 mark seen ⇒ 通用恢复循环 15min 后误判「恢复」→ 1h 后重报(7h 锁事件每小时 1 封 = 6 封)。
①d = 轮去重 + 去假清零 + seen 补全,单块改造。

取用方式(防第二份实现漂移, memory repro-script-second-implementation-drift):
  从 `scripts/schedule_monitor.sh` 的内嵌 python heredoc 里 **ast 提取** r2_skip 状态机那段真源码
  后 exec(同一份实现, 不抄副本), 与 test_228_round_incomplete_20261007.py 同法。

样本铁律(§18 L49「断言输入必须取真实生产实测样本」):fixtures/181/ticks.csv = 每 tick 输入表
  (NOW, stats.last_run, r2_skip_count>0),由**云上真实生产日志**(schedule_monitor 日志 +
  fetch_news 日志 + journal)经独立重放模型导出;该模型的**旧语义**输出与生产 monitor 日志里
  **真实事件行**(ground truth, 13 severe/20 stale/43 skip/13 recovery/4 clear = 93 事件)
  **逐条对账 93/93 零差集**才被采信(对齐用日期一致性独立搜得 o0=797 + 被杀轮 = 唯一无
  Deactivated 轮 j51, 未抄报告 b_of_j)。

零外发铁律(§18 L48/L50):static-only —— 只读文件 + exec 提取出的**纯逻辑块**(该块只 append
  到一个 `alerts` list、改 alert_state dict, **无任何 notify/网络/子进程**);本测试用
  subprocess/urllib/socket 打桩「一调用即 AssertionError」兜底证明本次自测零真实外发。
"""
import ast
import datetime
import socket
import textwrap
import urllib.request
from collections import namedtuple
from pathlib import Path

import pytest

ROOT = Path(__file__).absolute().parent.parent.parent
MONITOR = ROOT / "scripts" / "schedule_monitor.sh"
CSV = Path(__file__).absolute().parent / "fixtures" / "181" / "ticks.csv"

# 独立反事实复算(旧=13 封 → 新=5 封;时点/恢复点均为本测试驱动的期望, 非抄报告)
EXPECTED_FIRES = ["10-04 04:00", "10-04 07:00", "10-04 18:15", "10-05 04:00", "10-05 18:15"]
EXPECTED_RECOVERIES = ["10-04 05:00", "10-04 08:00", "10-05 01:15", "10-05 04:15", "10-05 19:00"]
ALERT_KEY = "fetch_news|r2_skip_alert"
CNT_KEY = "fetch_news|r2_skip_rounds"
TASK = "fetch_news"

Rec = namedtuple("Rec", "T alerts seen cnt recovered")

# 断言下限(仿 #201/#193 薄包装范式, 防收集/执行异常致「0 断言假绿」)
_MIN_ASSERTIONS = 30
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


def _raw_seg(slines, node):
    """取 node 覆盖的**原始行**(含行首缩进) —— 保留缩进后再 dedent, else 伙伴才不会错位。"""
    return "".join(slines[node.lineno - 1:node.end_lineno])


@pytest.fixture(scope="module")
def r2_src():
    slines = _heredoc_lines()
    src = "".join(slines)
    tree = ast.parse(src)
    loop = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.For) and isinstance(n.iter, ast.Name) and n.iter.id == "stats"
        and "_r2_skip_cnt" in ast.get_source_segment(src, n)
    )
    stmts = loop.body
    idx = next(
        i for i, st in enumerate(stmts)
        if isinstance(st, ast.Assign) and getattr(st.targets[0], "id", None) == "_r2_skip_cnt"
    )
    block = textwrap.dedent(_raw_seg(slines, stmts[idx]) + _raw_seg(slines, stmts[idx + 1]))
    consts = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) in (
                "R2_SKIP_CONTINUOUS_THRESHOLD", "R2_SKIP_OBS_WINDOW"):
            exec(ast.get_source_segment(src, node), {"timedelta": datetime.timedelta}, consts)  # noqa: S102
    assert set(consts) == {"R2_SKIP_CONTINUOUS_THRESHOLD", "R2_SKIP_OBS_WINDOW"}, \
        "schedule_monitor.sh 未找到两条常量(被改名/删除? 本测试锚点需同步)"
    return block, consts


@pytest.fixture(scope="module")
def code(r2_src):
    block, _ = r2_src
    return compile(block, "<r2skip-block>", "exec")


def _ticks():
    rows = []
    for ln in CSV.read_text(encoding="utf-8").splitlines():
        if not ln or ln.startswith("#"):
            continue
        now_s, lr_s, sk = ln.split(",")
        rows.append((datetime.datetime.strptime(now_s, "%Y-%m-%d %H:%M:%S"),
                     datetime.datetime.strptime(lr_s, "%Y-%m-%d %H:%M"), int(sk)))
    return rows


def _drive(code, consts, ticks):
    """逐 tick exec 真块, 并模拟通用恢复循环(L1644: active 且本轮未 seen ⇒ 判消失翻 recovered)。
    返回 list[Rec(T, alerts, seen_set, cnt_state, recovered_this_tick)]。"""
    st, alert, recs = {}, False, []
    for T, lr, sk in ticks:
        run = {
            "datetime": datetime.datetime, "timedelta": datetime.timedelta,
            "R2_SKIP_CONTINUOUS_THRESHOLD": consts["R2_SKIP_CONTINUOUS_THRESHOLD"],
            "R2_SKIP_OBS_WINDOW": consts["R2_SKIP_OBS_WINDOW"],
            "alerts": [], "alert_state": st, "seen_keys_this_run": set(), "NOW": T,
            "print": (lambda *a, **k: None),
            "s": {"task": TASK, "r2_skip_count": (1 if sk else 0),
                  "last_run": lr.strftime("%Y-%m-%d %H:%M")},
        }
        exec(code, run)  # noqa: S102
        seen = set(run["seen_keys_this_run"])
        if run["alerts"]:
            alert = True
        recovered = False
        # 通用恢复循环真语义(仅本 key): active 且未 seen ⇒ recovered
        if alert and ALERT_KEY not in seen:
            alert = False
            st[ALERT_KEY]["status"] = "recovered"
            recovered = True
        recs.append(Rec(T, list(run["alerts"]), seen, dict(st.get(CNT_KEY) or {}), recovered))
    return recs


# ══════════════════════ 常量漂移守卫 + 块形态 ══════════════════════

def test_constants_unchanged(r2_src):
    """阈值不动:THRESHOLD=3 / WINDOW=30min(用户只选 ①d, 未实现任何 dial)。"""
    _, consts = r2_src
    _chk(consts["R2_SKIP_CONTINUOUS_THRESHOLD"] == 3)
    _chk(consts["R2_SKIP_OBS_WINDOW"] == datetime.timedelta(minutes=30))


def test_block_is_1d_not_old(r2_src):
    """块必须含 ①d 三标记:轮去重(last_round)、seen 补全、保链(无 stale 清零)。"""
    block, _ = r2_src
    _chk("last_round" in block, "缺轮去重字段 last_round")
    _chk("seen_keys_this_run.add(_r2_alert_key)" in block, "缺 seen 补全")
    # 旧代码特征:stale 分支把 skip_rounds 清零。新代码不得再有。
    _chk('_r2_stale_prev["skip_rounds"] = 0' not in block, "仍残留 stale 假清零")


# ══════════════════════ 主场景:真实 4 天窗口 13→5 ══════════════════════

def test_real_window_fires_13_to_5(code, r2_src):
    """真实窗口:修复后 5 封, 时点逐一对上(独立复算)。"""
    _, consts = r2_src
    ticks = _ticks()
    _chk(len(ticks) == 372, f"fixture 行数漂移: {len(ticks)}")
    _chk(ticks[0][0].strftime("%Y-%m-%d %H:%M") == "2026-10-03 19:00")
    _chk(ticks[-1][0].strftime("%Y-%m-%d %H:%M") == "2026-10-07 15:45")
    recs = _drive(code, consts, ticks)
    fires = [r.T.strftime("%m-%d %H:%M") for r in recs if r.alerts]
    _chk(fires == EXPECTED_FIRES, f"fires={fires}")


def test_every_fire_is_real_3_distinct_rounds(code, r2_src):
    """每封「连续 3 轮」必须是真话:计数 = 3 个 distinct last_round(非同轮重复计)。"""
    _, consts = r2_src
    recs = _drive(code, consts, _ticks())
    chains, seen_rounds = [], []
    for r in recs:
        if r.cnt.get("skip_rounds", 0) == 0:
            seen_rounds = []
        rr = r.cnt.get("last_round")
        if rr and (not seen_rounds or seen_rounds[-1] != rr):
            seen_rounds.append(rr)
        if r.alerts:
            chains.append(list(seen_rounds))
    _chk(len(chains) == 5, f"fire chains={len(chains)}")
    for ch in chains:
        _chk(len(set(ch)) == 3, f"某封 distinct rounds={len(set(ch))} != 3: {ch}")
        _chk(len(ch) == 3, f"某封计数链长={len(ch)} != 3: {ch}")


def test_fire_message_says_3_rounds(code, r2_src):
    """告警正文「连续 3 轮」与实际一致(不再自称 3 实则 2)。"""
    _, consts = r2_src
    recs = _drive(code, consts, _ticks())
    msgs = [r.alerts[0] for r in recs if r.alerts]
    _chk(len(msgs) == 5)
    for m in msgs:
        _chk(m.startswith("SEVERE: fetch_news R2 上传锁连续 3 轮跳过(SKIPPED_LOCKED)"), m)
        _chk("上传缺口持续" in m)


def test_no_false_recovery_loop(code, r2_src):
    """「SEVERE→15min 假恢复→1h 重报」循环消失:恢复恰 5 次(每事件 1 次), 非 13 次。"""
    _, consts = r2_src
    recs = _drive(code, consts, _ticks())
    recov = [r.T.strftime("%m-%d %H:%M") for r in recs if r.recovered]
    _chk(recov == EXPECTED_RECOVERIES, f"recoveries={recov}")
    # 反向:12h 内同一事件不得重复报(旧语义 7h 大事件曾报 6 封)
    fires = [r.T for r in recs if r.alerts]
    for i in range(1, len(fires)):
        _chk((fires[i] - fires[i - 1]) > datetime.timedelta(hours=2),
             f"两封 SEVERE 间隔 {fires[i]-fires[i-1]} 过近 ⇒ 疑似重报循环残留")


def test_seen_completion_on_every_skip_tick_at_threshold(code, r2_src):
    """seen 补全机制级:达阈值后**每一** skip tick(新轮/重复/滞留)都 mark 告警 key seen ——
    这正是防通用恢复循环误判「恢复」的判据(L1644 `if key not in seen: recovered`)。"""
    _, consts = r2_src
    recs = _drive(code, consts, _ticks())
    ticks = _ticks()
    covered = 0
    for (T, lr, sk), r in zip(ticks, recs):
        if sk and r.cnt.get("skip_rounds", 0) >= 3:
            _chk(ALERT_KEY in r.seen, f"{T} n>=3 skip tick 未 mark seen ⇒ 会假恢复")
            covered += 1
    _chk(covered > 5, "窗口内达阈值的 skip tick 太少, 断言没覆盖到")  # 覆盖到重复/滞留轮


# ══════════════════════ 小用例:去重 / 保链 / 真恢复 / 负控 ══════════════════════

def _t(hm, day="2026-11-02", lr="2026-11-02 09:45", sk=True):
    return (datetime.datetime.strptime(f"{day} {hm}", "%Y-%m-%d %H:%M"),
            datetime.datetime.strptime(lr, "%Y-%m-%d %H:%M"), int(sk))


def test_dup_tick_same_round_not_double_counted(code, r2_src):
    """同一轮被 tick 3 次(dup) ⇒ 只计 1 次, 不告警(修掉「同轮重复消费」根因)。"""
    _, consts = r2_src
    recs = _drive(code, consts, [_t("10:00"), _t("10:15"), _t("10:30")])
    _chk(recs[-1].cnt.get("skip_rounds") == 1, f"count={recs[-1].cnt}")
    _chk(all(not r.alerts for r in recs), "同轮重复 tick 不得告警")


def test_new_rounds_accumulate_and_fire(code, r2_src):
    """三个不同真实轮(fresh) ⇒ 计数 1→2→3, 第 3 轮告警(真多轮事件仍响)。"""
    _, consts = r2_src
    ticks = [_t("10:00", lr="2026-11-02 09:45"),
             _t("10:30", lr="2026-11-02 10:15"),
             _t("11:00", lr="2026-11-02 10:45")]
    recs = _drive(code, consts, ticks)
    _chk(recs[0].cnt.get("skip_rounds") == 1)
    _chk(recs[1].cnt.get("skip_rounds") == 2)
    _chk(recs[2].cnt.get("skip_rounds") == 3)
    _chk(len(recs[2].alerts) == 1, "第 3 真轮必须告警")


def test_stale_keeps_chain_no_reset(code, r2_src):
    """② 去假清零:达阈值后进入滞留(本轮无新运行) —— 计数保链不归零, 且 mark seen(不假恢复)。"""
    _, consts = r2_src
    ticks = [_t("10:00", lr="2026-11-02 09:45"),
             _t("10:30", lr="2026-11-02 10:15"),
             _t("11:00", lr="2026-11-02 10:45"),   # fire at n=3
             _t("11:15", lr="2026-11-02 10:45"),   # dup
             _t("11:45", lr="2026-11-02 10:45"),   # stale(age 60min > 30)
             _t("12:15", lr="2026-11-02 10:45")]   # stale
    recs = _drive(code, consts, ticks)
    _chk(len(recs[2].alerts) == 1, "第 3 轮告警")
    for i in (3, 4, 5):
        _chk(recs[i].cnt.get("skip_rounds") == 3, f"tick{i} 滞留应保链=3, got {recs[i].cnt}")
        _chk(ALERT_KEY in recs[i].seen, f"tick{i} 滞留轮未 mark seen ⇒ 会假恢复")
        _chk(not recs[i].alerts, f"tick{i} 滞留轮不得重复告警")


def test_true_recovery_via_no_skip_branch(code, r2_src):
    """真恢复入口:本轮 r2_skip_count==0 ⇒ 计数清零 + last_round 清空 + 告警 key 不 mark seen
    (留给通用恢复循环判消失)。"""
    _, consts = r2_src
    ticks = [_t("10:00", lr="2026-11-02 09:45"),
             _t("10:30", lr="2026-11-02 10:15"),
             _t("11:00", lr="2026-11-02 10:45"),            # fire
             _t("11:30", lr="2026-11-02 11:15", sk=False)]  # 无 skip
    recs = _drive(code, consts, ticks)
    _chk(recs[-1].cnt.get("skip_rounds") == 0, f"未清零: {recs[-1].cnt}")
    _chk(recs[-1].cnt.get("last_round") is None, "last_round 未清空")
    _chk(ALERT_KEY not in recs[-1].seen, "清零点不应 mark seen(否则真恢复发不出)")
    _chk(recs[-1].recovered, "清零点应触发恢复(recovered 语义)")


def test_negative_control_sustained_gap_still_alerts(code, r2_src):
    """负控(§memory alert-denoise-keep-fault-discriminator):真持续缺口(每轮都是新轮且 skip)
    修复后**仍必须告警** —— 降噪不得把真故障判别维度一起豁免。"""
    _, consts = r2_src
    base = datetime.datetime(2026, 11, 3, 0, 0)
    ticks = []
    for k in range(10):
        T = base + datetime.timedelta(minutes=30 * k)
        ticks.append((T, (T - datetime.timedelta(minutes=15)).replace(second=0, microsecond=0), 1))
    recs = _drive(code, consts, ticks)
    fires = [r.T for r in recs if r.alerts]
    _chk(len(fires) == 1, f"真持续缺口应恰好首报 1 次, got {len(fires)}")
    _chk(bool(fires) and fires[0] == base + datetime.timedelta(hours=1), f"首报时点={fires}")


# ══════════════════════ 零真实外发自证(§18 L48/L50) ══════════════════════

def test_zero_real_outbound(code, r2_src, monkeypatch):
    """打桩 subprocess/urllib/socket「一调用即 AssertionError」+ 调用计数 ⇒ 证明本次自测
    零真实外发(该块结构上无外发出口, 此断言为硬闸兜底)。"""
    _, consts = r2_src
    calls = {"n": 0}

    def _boom(*a, **k):
        calls["n"] += 1
        raise AssertionError("自测发生真实外发/子进程 —— 违反 §18 L48 零外发约束")

    monkeypatch.setattr("subprocess.run", _boom, raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)
    recs = _drive(code, consts, _ticks())
    _chk(calls["n"] == 0, f"发生外发调用 {calls['n']} 次")
    _chk(len([1 for r in recs if r.alerts]) == 5)


# ══════════════════════ 断言下限守卫(防 0 断言假绿) ══════════════════════

def test_min_assertions_guard():
    """末位执行:确认上面确实跑了足量断言(收集/执行异常会让 _N 停在低位)。"""
    assert _N[0] >= _MIN_ASSERTIONS, \
        f"#181 自验仅 {_N[0]} 条断言(下限 {_MIN_ASSERTIONS}), 疑似收集/执行异常"