# -*- coding: utf-8 -*-
"""S06 降亏动态模式状态机 pytest 套(P0-1, 架构评审 2026-09-03 §6.3/§6.5)。

【目的】锁死 S06 sticky 状态机(build_daily/current_block)语义, 防重构/参数改动/
  旧语义回退(codex008 F2: 旧语义 held 只在命中日 +1 → 持续非命中场景 a9 锁死 P0)。
  规格单一事实源 = scripts/gen_kelly_mode_s06_state.py。

【方法口径】
  ① 冻结快照重算层: 样本取自线上产物冻结快照 static-site/data/kelly_mode_s06_state.json
     (2026-09-04 收盘版, 2026-09-06 本地提取)——段A=pre 段开头 5 行(首日兜底)、
     段C=生产段 idx1158-1174(生产段首日独立 seed + 进入 a9)。用快照 daily 行的
     size_spread 反推 spread, 调 build_daily 同输入重算, 断言与快照逐位一致
     (date/premise/effective_mode/decision_date), 锁死实现不漂移(§5.4⑦ 同构对账精神)。
  ② 状态机单元层: 构造小序列断言 sticky 语义——T 日收盘判 T+1 生效 / 进入 a9 立即 /
     退出需连续破坏 CONFIRM_DAYS=15 且持满 MIN_HOLD_DAYS=10 / held 新语义每日 +1。

【输入依赖】无外部数据(样本硬编码, 固定输入→断言输出)。
【输出】pytest PASS/FAIL。CI 挂载: .github/workflows/ci.yml ⑧(scripts/tests/ 限定收集)。
【复现命令】cd /Users/linhuichen/code/trade && .venv/bin/python -m pytest -q scripts/tests/test_s06_state_machine.py
【关键参数种子】(⚠改任何一项必须同步 purpose-notes.js/app.js/lab.js 公示 + check_s06_state.py 机检)
  THRESHOLD=-3.524224785046781(2016-2020 选段 q30 冻结) / CONFIRM_DAYS=15 /
  MIN_HOLD_DAYS=10 / PRE_OFF=OFF_BASE="new14" / ON_BASE="a9"。
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).absolute().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from gen_kelly_mode_s06_state import (  # noqa: E402
    build_daily, current_block, THRESHOLD, CONFIRM_DAYS, MIN_HOLD_DAYS,
    ON_BASE, OFF_BASE,
)


# ────────────────────────────────────────────────────────────────────────────
# ① 冻结快照层样本(kelly_mode_s06_state.json 2026-09-04 收盘版, 2026-09-06 提取)
# ────────────────────────────────────────────────────────────────────────────
# 段A: pre 段开头 5 行(idx 0-4) —— 首日恒兜底 new14(decision_date=None)
SEG_A = [
    ("20100201", 6.848225577581347, False, "new14", None),
    ("20100202", 6.113316785116096, False, "new14", "20100201"),
    ("20100203", 4.667332253790323, False, "new14", "20100202"),
    ("20100204", 6.140740582998938, False, "new14", "20100203"),
    ("20100205", 4.897244474289897, False, "new14", "20100204"),
]

# 段C: 生产段 idx 1158-1174 —— 生产段首日独立 seed new14(dec=None, 不跨缝传),
#       次日进入 a9(20141114 收盘 premise=True → 20141117 生效)
SEG_C = [
    ("20141114", -6.519887825483983, True, "new14", None),
    ("20141117", -5.450861285712882, True, "a9", "20141114"),
    ("20141118", -3.8409832210523076, True, "a9", "20141117"),
    ("20141119", -2.147933824245718, False, "a9", "20141118"),
    ("20141120", -1.5845981353304284, False, "a9", "20141119"),
    ("20141121", -3.032949753658932, False, "a9", "20141120"),
    ("20141124", -7.073834574482606, True, "a9", "20141121"),
    ("20141125", -7.415704302655235, True, "a9", "20141124"),
    ("20141126", -8.064193222024297, True, "a9", "20141125"),
    ("20141127", -7.865404775750772, True, "a9", "20141126"),
    ("20141128", -7.639153098724738, True, "a9", "20141127"),
    ("20141201", -10.373361427089955, True, "a9", "20141128"),
    ("20141202", -12.722224458167931, True, "a9", "20141201"),
    ("20141203", -13.934316932955817, True, "a9", "20141202"),
    ("20141204", -18.84686412408465, True, "a9", "20141203"),
    ("20141205", -21.131974272883934, True, "a9", "20141204"),
    ("20141208", -23.405676355896297, True, "a9", "20141205"),
]


def _recompute(seg):
    dates = [r[0] for r in seg]
    spread = {r[0]: r[1] for r in seg}
    return build_daily(dates, spread)


def _assert_seg_equal(out, seg):
    assert len(out) == len(seg), f"重算行数 {len(out)} != 冻结 {len(seg)}"
    for row, (date, _sv, premise, mode, dec) in zip(out, seg):
        assert row["date"] == date
        assert row["premise"] is premise, f"{date}: premise 期望 {premise} 实得 {row['premise']}"
        assert row["effective_mode"] == mode, f"{date}: mode 期望 {mode} 实得 {row['effective_mode']}"
        assert row["decision_date"] == dec, f"{date}: decision_date 期望 {dec} 实得 {row['decision_date']}"


def test_recompute_frozen_seg_a():
    """冻结段A重算逐位一致: 首日兜底 new14 + decision_date 序列。"""
    _assert_seg_equal(_recompute(SEG_A), SEG_A)


def test_recompute_frozen_seg_c():
    """冻结段C重算逐位一致: 生产段首日独立 seed + 次日进入 a9 + 持续 a9。"""
    _assert_seg_equal(_recompute(SEG_C), SEG_C)


def test_hold_new_semantics_recompute_seg_c():
    """段C 隐含断言 held 新语义: 20141119 起 premise=False(破坏)但 a9 停留(held 递增, broken<15)。"""
    out = _recompute(SEG_C)
    # 20141119-20141121 premise=False 3 天破坏, a9 仍停留(confirm 期未满)
    assert out[3]["effective_mode"] == "a9"
    assert out[4]["effective_mode"] == "a9"
    assert out[5]["effective_mode"] == "a9"


# ────────────────────────────────────────────────────────────────────────────
# ② 状态机单元层: 构造序列断言 sticky 语义
# ────────────────────────────────────────────────────────────────────────────
def _mk_dates(spreads):
    """spreads: {date: spread} → (dates 升序, spread dict)。"""
    dates = sorted(spreads)
    return dates, spreads


def test_first_day_always_off_base():
    """首日恒兜底: 无决策日, effective_mode=OFF_BASE, decision_date=None。"""
    dates, spread = _mk_dates({"20260105": -10.0, "20260106": -11.0})
    out = build_daily(dates, spread)
    assert out[0]["effective_mode"] == OFF_BASE
    assert out[0]["decision_date"] is None
    # 首日 premise 不作用于当日(次日才生效)
    assert out[1]["decision_date"] == "20260105"


def test_enter_a9_next_day():
    """T 日收盘 premise=True → T+1 生效 a9(进入立即, 非当日)。"""
    dates, spread = _mk_dates({"20260105": 0.0, "20260106": -5.0, "20260107": -6.0})
    out = build_daily(dates, spread)
    assert out[0]["effective_mode"] == OFF_BASE   # 首日兜底
    assert out[1]["effective_mode"] == OFF_BASE   # 20260106 由 20260105(0.0, 非命中)决策
    assert out[2]["effective_mode"] == ON_BASE    # 20260107 由 20260106(-5.0<THR, 命中)决策
    assert out[2]["decision_date"] == "20260106"


def test_stay_a9_while_confirming():
    """进入 a9 后 premise 连续破坏但 confirm 期未满 → 仍停留 a9(锁死防护)。"""
    dates, spread = _mk_dates({
        "20260105": 0.0,   # 首日
        "20260106": -5.0,  # → 20260107 进 a9
        "20260107": -1.0,  # 破坏1
        "20260108": -1.0,  # 破坏2
        "20260109": -1.0,  # 破坏3
        "20260112": -1.0,  # 破坏4
    })
    out = build_daily(dates, spread)
    assert out[2]["effective_mode"] == ON_BASE
    for row in out[3:]:
        assert row["effective_mode"] == ON_BASE, f"{row['date']} 应停留 a9(confirm 期未满)"
    # held 新语义: 破坏日 held 也 +1(进入当日计 1)
    # 进入日 20260107=held1, 20260108=2, 20260109=3, 20260112=4


def test_exit_after_confirm_and_hold():
    """退出条件: 连续破坏 CONFIRM_DAYS=15 且 held>=MIN_HOLD_DAYS=10 → 下一交易日切回兜底。"""
    # 构造: 首日, 次日进 a9, 之后连续破坏 17 天
    spreads = {"20260105": 0.0, "20260106": -5.0}
    # 20260107 起连续破坏日(含首破坏日共需 ≥15 个破坏日)
    # 破坏日 = a9 生效后 premise=False 的日子; 进入日后第 k 天 broken=k
    day = "20260107"
    import datetime as _dt
    d = _dt.date(2026, 1, 7)
    for _ in range(20):
        spreads[day] = -1.0  # premise=False
        d = d + _dt.timedelta(days=1)
        while d.weekday() >= 5:  # 跳过周末, 模拟交易日
            d = d + _dt.timedelta(days=1)
        day = d.strftime("%Y%m%d")
    dates, spread = _mk_dates(spreads)
    out = build_daily(dates, spread)
    # out[0]=首日 new14; out[1]=20260106(new14, 由 20260105 决策); out[2]=20260107 进 a9
    assert out[2]["effective_mode"] == ON_BASE
    # 进入 a9 后: 20260108 起 premise=False 破坏。破坏日数 = index-2。
    # broken>=15 且 held>=10 后次日退出。
    exit_found = None
    for i in range(3, len(out)):
        if out[i]["effective_mode"] == OFF_BASE:
            exit_found = i
            break
    assert exit_found is not None, "应发生退出"
    # 退出日之前破坏日数应 >=15(退出的决策日就是第 15 个破坏日)
    broken_at_exit = exit_found - 2 - 1  # 决策日相对进入日的破坏日数
    # out[exit_found] 由 out[exit_found-1](第 broken 个破坏日)决策
    assert broken_at_exit >= CONFIRM_DAYS - 1, f"退出时破坏日 {broken_at_exit} 应 >= {CONFIRM_DAYS-1}"
    # 退出日当天仍是 new14 且之后持续(前提持续 False)
    assert out[exit_found]["decision_date"] is not None


def test_exit_not_triggered_before_confirm():
    """破坏日 < CONFIRM_DAYS → 不退出(即使已持满 MIN_HOLD_DAYS)。"""
    spreads = {"20260105": 0.0, "20260106": -5.0}
    day = "20260107"
    import datetime as _dt
    d = _dt.date(2026, 1, 7)
    for _ in range(8):  # 只破坏 8 天(<15)
        spreads[day] = -1.0
        d = d + _dt.timedelta(days=1)
        while d.weekday() >= 5:
            d = d + _dt.timedelta(days=1)
        day = d.strftime("%Y%m%d")
    dates, spread = _mk_dates(spreads)
    out = build_daily(dates, spread)
    assert out[2]["effective_mode"] == ON_BASE
    assert all(row["effective_mode"] == ON_BASE for row in out[2:]), "破坏<15 不应退出"


# ────────────────────────────────────────────────────────────────────────────
# ③ current_block
# ────────────────────────────────────────────────────────────────────────────
def test_current_block_frozen_seg_a():
    """current_block: 连续块起始日(since)回溯到段首。"""
    daily = _recompute(SEG_A)
    blk = current_block(daily)
    assert blk == {"date": "20100205", "mode": "new14", "since": "20100201"}


def test_current_block_frozen_seg_c():
    """current_block: 段C 以 a9 结束,since 回溯到 20141117。"""
    daily = _recompute(SEG_C)
    blk = current_block(daily)
    assert blk["date"] == "20141208"
    assert blk["mode"] == "a9"
    assert blk["since"] == "20141117"


def test_current_block_empty():
    """current_block: 空 daily → {date:None, mode:OFF_BASE, since:None}。"""
    assert current_block([]) == {"date": None, "mode": OFF_BASE, "since": None}


def test_params_are_frozen_constants():
    """参数冻结: THRESHOLD/CONFIRM_DAYS/MIN_HOLD_DAYS 与公示/机检锚点逐位一致。"""
    assert THRESHOLD == -3.524224785046781
    assert CONFIRM_DAYS == 15
    assert MIN_HOLD_DAYS == 10
    assert ON_BASE == "a9"
    assert OFF_BASE == "new14"