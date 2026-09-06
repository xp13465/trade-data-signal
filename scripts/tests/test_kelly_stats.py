# -*- coding: utf-8 -*-
"""凯利三件套核心纯函数 pytest 套(P0-1, 架构评审 2026-09-03 §6.3/§6.5)。

【目的】锁死 signal_kelly_backtest.py 核心统计纯函数(_compute_kelly/_max_concurrent/
  _years_from_trades/_max_drawdown/_annualized_return/_compute_stats), 防重构/口径
  修正静默改变凯利卡/弹窗/回测表数字。前端 `_kellyRecomputeTrade`(lab.js L7039)为
  同构 JS 实现, 本套锁死后端 python 基准, 前端重构时以本套为对账锚点(§5.4⑦)。

【方法口径】固定输入→断言输出。
  ① 冻结快照层: _compute_stats 样本取自线上产物冻结快照 static-site/data/
     signal_kelly_trades.json quadrants.rating_high.A 前 5 行 + 1 笔持仓中(2026-09-06
     提取), 断言整本统计逐字段。
  ② 单元层: _compute_kelly 边界表 / _max_concurrent 扫描线 / _max_drawdown 回撤 /
     _annualized_return 各周期。

【依赖】import scripts/signal_kelly_backtest → 需 yaml + app.db(纯标准库链)。
  CI ⑧ 已 pip install pytest pyyaml; 环境缺依赖时 pytest.skip(不 FAIL)。

【已知设计观察(诚实标注, 不改行为)】_compute_kelly 中 f* clamp [0,1] → half_kelly max
  50.0, tier「激进」(half>=60)在当前口径下不可达(可达档为 保守/均衡)。本套锁定当前
  生产行为; 是否调整属历史功能变更, 按 §23.7 冻结契约需用户拍板, 不在本套范围内。

【输入依赖】无外部数据(样本硬编码)。
【输出】pytest PASS/FAIL。CI 挂载: .github/workflows/ci.yml ⑧(scripts/tests/ 限定收集)。
【复现命令】cd /Users/linhuichen/code/trade && .venv/bin/python -m pytest -q scripts/tests/test_kelly_stats.py
"""
import sys
from pathlib import Path

import pytest

pytest.importorskip("yaml", reason="CI 需 pip install pyyaml 才能 import signal_kelly_backtest")

ROOT = Path(__file__).absolute().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:
    import signal_kelly_backtest as sk
except Exception as _e:  # pragma: no cover - 环境缺依赖时降级 skip
    pytest.skip(f"signal_kelly_backtest 依赖不可用: {_e}", allow_module_level=True)


# ────────────────────────────────────────────────────────────────────────────
# ① _compute_kelly 边界表(期望值由 2026-09-06 实测输出冻结)
# ────────────────────────────────────────────────────────────────────────────
KELLY_TABLE = [
    # (win_rate, pl_ratio, expect_f, expect_half, expect_tier)
    (0.5, 1.0, 0.0, 0.0, "保守"),
    (0.6, 1.5, 0.3333, 16.67, "保守"),
    (0.7, 1.0, 0.4, 20.0, "保守"),
    (0.8, 1.0, 0.6, 30.0, "均衡"),
    (0.9, 0.5, 0.7, 35.0, "均衡"),
    (0.95, 0.5, 0.85, 42.5, "均衡"),
    (1.0, 1.0, 1.0, 50.0, "均衡"),
    (0.6, 0.1, 0.0, 0.0, "保守"),
    (0.5, 0.0, 0.0, 0.0, "保守"),
    (0.6, 2.0, 0.4, 20.0, "保守"),
]


@pytest.mark.parametrize("p,b,ef,eh,et", KELLY_TABLE,
                         ids=[f"p{p}_b{b}" for p, b, *_ in KELLY_TABLE])
def test_compute_kelly(p, b, ef, eh, et):
    assert sk._compute_kelly(p, b) == (ef, eh, et), f"kelly({p},{b})"


def test_compute_kelly_all_loss():
    """全败(win_rate=0): f*=0, 保守。"""
    assert sk._compute_kelly(0.0, 1.0) == (0.0, 0.0, "保守")


def test_compute_kelly_zero_pl_ratio():
    """pl_ratio 0/None: b=0 → f*=0。"""
    assert sk._compute_kelly(0.6, 0.0) == (0.0, 0.0, "保守")
    assert sk._compute_kelly(0.6, None) == (0.0, 0.0, "保守")


# ────────────────────────────────────────────────────────────────────────────
# ② _max_concurrent 扫描线
# ────────────────────────────────────────────────────────────────────────────
def test_max_concurrent_empty():
    assert sk._max_concurrent([]) == 0


def test_max_concurrent_no_overlap():
    trades = [
        {"buy_date": "20260101", "sell_date": "20260110"},
        {"buy_date": "20260111", "sell_date": "20260120"},
    ]
    assert sk._max_concurrent(trades) == 1


def test_max_concurrent_overlap():
    trades = [
        {"buy_date": "20260101", "sell_date": "20260110"},
        {"buy_date": "20260102", "sell_date": "20260105"},
        {"buy_date": "20260103", "sell_date": "20260106"},
    ]
    assert sk._max_concurrent(trades) == 3


def test_max_concurrent_same_day_buy_first_conservative():
    """同日先买后卖=保守(算占用): 同日 buy 先处理。"""
    trades = [
        {"buy_date": "20260101", "sell_date": "20260101"},
        {"buy_date": "20260101", "sell_date": "20260105"},
    ]
    assert sk._max_concurrent(trades) == 2


def test_max_concurrent_open_position_sentinel():
    """持仓中(sell_date 空)视为远期哨兵, 覆盖后续持仓。"""
    trades = [
        {"buy_date": "20260101"},  # 持仓中 → 99999999
        {"buy_date": "20260102", "sell_date": "20260103"},
    ]
    assert sk._max_concurrent(trades) == 2


# ────────────────────────────────────────────────────────────────────────────
# ③ _years_from_trades / _max_drawdown / _annualized_return
# ────────────────────────────────────────────────────────────────────────────
def test_years_from_trades_empty():
    assert sk._years_from_trades([]) == 1.0


def test_years_from_trades_single():
    assert abs(sk._years_from_trades([{"buy_date": "20260101"}]) - 1.0 / 365.25) < 1e-9


def test_years_from_trades_span():
    trades = [
        {"buy_date": "20260101"},
        {"buy_date": "20270101"},
    ]
    assert abs(sk._years_from_trades(trades) - 365.0 / 365.25) < 1e-6


def test_max_drawdown_empty():
    assert sk._max_drawdown([]) == (0.0, 0.0)


def test_max_drawdown_monotonic_profit():
    trades = [
        {"buy_date": "20260101", "sell_date": "20260110", "profit": 100.0},
        {"buy_date": "20260111", "sell_date": "20260120", "profit": 50.0},
    ]
    assert sk._max_drawdown(trades, buy_amount=10000) == (0.0, 0.0)


def test_max_drawdown_has_drawdown():
    trades = [
        {"buy_date": "20260101", "sell_date": "20260110", "profit": 100.0},
        {"buy_date": "20260111", "sell_date": "20260120", "profit": -150.0},
    ]
    # cumulative: 100 → peak 100; -50 → dd 150(peak-(-50)); total_invest=20000
    # pct = 150/20000*100 = 0.75
    assert sk._max_drawdown(trades, buy_amount=10000) == (150.0, 0.75)


def test_max_drawdown_open_position_last():
    """持仓中(sell_date 空)排时序末尾: 后实现盈亏。"""
    trades = [
        {"buy_date": "20260101", "sell_date": "20260110", "profit": 100.0},
        {"buy_date": "20260102", "profit": -200.0},  # 持仓中, 排末尾
    ]
    # 时序: +100 → cumulative 100 peak 100; 持仓中 -200 → cumulative -100, dd 200
    assert sk._max_drawdown(trades, buy_amount=10000) == (200.0, 1.0)


def test_annualized_return_y1():
    assert sk._annualized_return(50.0, "y1", []) == 50.0


def test_annualized_return_y3():
    # r=0.5 → (1.5)^(1/3)-1 = 0.144714 → *100, round 4 位 = 14.4714
    assert sk._annualized_return(50.0, "y3", []) == 14.4714


def test_annualized_return_y5():
    # r=0.5 → (1.5)^(1/5)-1 = 0.084472 → *100, round 4 位 = 8.4472
    assert sk._annualized_return(50.0, "y5", []) == 8.4472


def test_annualized_return_negative_le_minus_1():
    """r<=-1 时返回 0(无法开方)。"""
    assert sk._annualized_return(-150.0, "y1", []) == 0.0
    assert sk._annualized_return(-100.0, "all", [{"buy_date": "20260101"}]) == 0.0


# ────────────────────────────────────────────────────────────────────────────
# ④ _compute_stats 冻结快照层(样本=signal_kelly_trades.json rating_high/A 前 5 行)
# ────────────────────────────────────────────────────────────────────────────
FROZEN_TRADES_5 = [
    dict(buy_date="20210607", sell_date="20210622", profit=571.9436, return_pct=5.7194, hold_days=10),
    dict(buy_date="20210615", sell_date="20210629", profit=1187.6568, return_pct=11.8766, hold_days=10),
    dict(buy_date="20211109", sell_date="20211123", profit=481.8363, return_pct=4.8184, hold_days=10),
    dict(buy_date="20211111", sell_date="20211125", profit=215.6464, return_pct=2.1565, hold_days=10),
    dict(buy_date="20211117", sell_date="20211201", profit=375.6608, return_pct=3.7566, hold_days=10),
]

# 期望 stats 整本(2026-09-06 由 _compute_stats 实测输出冻结)
EXPECT_STATS_5 = {
    "n": 5, "win_count": 5, "lose_count": 0, "win_rate": 1.0, "pl_ratio": 999.0,
    "mean_return": 5.6655, "total_return": 28.3274, "avg_hold_days": 10.0,
    "kelly_f": 1.0, "half_kelly": 50.0, "kelly_tier": "均衡",
    "max_single_win": 11.8766, "max_single_loss": 2.1565,
    "win_streak_max": 5, "lose_streak_max": 0,
    "total_invest": 50000, "total_profit": 2832.7439, "total_return_pct": 5.6655,
    "max_concurrent": 3, "max_concurrent_capital": 30000,
    "return_pct_max_holding": 9.4425, "annualized_return": 22.4075, "sharpe": 1.5243,
    "max_drawdown": 0.0, "max_drawdown_pct": 0.0, "calmar": 0,
    "holding_count": 0, "holding_capital": 0,
}


def test_compute_stats_frozen_5():
    """冻结 5 行全胜: 整本统计逐字段锁定(防口径漂移)。"""
    stats = sk._compute_stats(FROZEN_TRADES_5, "all", buy_amount=10000)
    for k, v in EXPECT_STATS_5.items():
        assert stats[k] == v, f"字段 {k}: 期望 {v} 实得 {stats[k]}"


def test_compute_stats_frozen_6_with_holding_loss():
    """5 行 + 1 持仓中亏损: 持仓中计入 total_profit/胜率/回撤, holding_count 计数。"""
    trades6 = FROZEN_TRADES_5 + [dict(buy_date="20260820", profit=-123.45, return_pct=-1.2345, hold_days=12)]
    stats = sk._compute_stats(trades6, "all", buy_amount=10000)
    assert stats["n"] == 6
    assert stats["win_count"] == 5
    assert stats["lose_count"] == 1
    assert stats["win_rate"] == 0.8333
    assert stats["total_profit"] == 2709.2939
    assert stats["max_drawdown"] == 123.45
    assert stats["max_drawdown_pct"] == 0.2057
    assert stats["holding_count"] == 1
    assert stats["holding_capital"] == 10000
    assert stats["pl_ratio"] == 4.59
    assert stats["kelly_tier"] == "均衡"


def test_compute_stats_empty():
    """空 trades: 全零/保守空统计(不抛异常)。"""
    stats = sk._compute_stats([], "all", buy_amount=10000)
    assert stats["n"] == 0
    assert stats["win_rate"] == 0
    assert stats["kelly_tier"] == "保守"
    assert stats["max_concurrent"] == 0
    assert stats["holding_count"] == 0


def test_compute_stats_lose_all():
    """全败: pl_ratio None(无胜), kelly 保守。"""
    trades = [
        dict(buy_date="20260101", sell_date="20260110", profit=-100.0, return_pct=-1.0, hold_days=5),
        dict(buy_date="20260111", sell_date="20260120", profit=-50.0, return_pct=-0.5, hold_days=5),
    ]
    stats = sk._compute_stats(trades, "all", buy_amount=10000)
    assert stats["win_count"] == 0
    # 全败: lose_count>0 且 avg_loss_abs>0 → pl_ratio = avg_win(0)/avg_loss_abs = 0.0
    # (仅 avg_loss_abs==0 时才为 None)
    assert stats["pl_ratio"] == 0.0
    assert stats["kelly_f"] == 0
    assert stats["lose_streak_max"] == 2