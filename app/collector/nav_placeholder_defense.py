"""etf_daily accum_nav=1.5 占位残留判定·单一来源(9/8 P0 防御,2026-09-06 reviewer F2 根治)。

9/8 事故形态: 盘中全市场 ETF 占位行(accum_nav=1.5/open=1.49/close=NULL/etf_name=etf_code),
盘后 backfill 把 open/close/etf_name 全覆盖成真实值, 仅 accum_nav 残留 1.5(COALESCE
不覆盖已有值) → 「真实名+真实close+残留1.5」混合行穿透所有现有检测。

原三处防御(检测器 check_nav_placeholder_residue / 补齐 update_accum_nav / 回测回退
_nav_skip_placeholder)全部用「accum_nav=1.5 AND open=1.49」双哨兵, 对真残留
(open 已被 backfill 覆盖成真实值, 无一等于 1.49)全漏检, 且会误判真实平滑行
(159303@20260721 open 恰 1.49, 前后日 1.4978→1.5→1.5089)。本模块为全部防御点共享的
判定单一来源, 防三处反复漂移。

判定口径:
  单哨兵 accum_nav ≈ NAV_PLACEHOLDER_VAL(1.5) 且「前后交易日不连续」→ 占位残留。
  连续判定: 与前日或后日相对变化 < NAV_PLACEHOLDER_JUMP(15%) 任一成立 = 真实平滑, 非残留。
  open=1.49 只作辅助线索(NAV_PLACEHOLDER_OPEN, 用作 detail 展示), 不作必要条件。
  真实平滑数据(588930@20260908 open=1.523 前后 1.5208→1.5; 159303@20260721 1.4978→1.5→1.5089)
  前后变化均 <15%, 不命中; 真残留(158000@20260908 前日 1.0564, 残留 1.5 = +42%)命中。

SQL 侧各防御点只做候选筛选(candidate_where), 最终判定统一走 is_placeholder_row(Python),
构成唯一逻辑来源。
"""
from __future__ import annotations

NAV_PLACEHOLDER_VAL = 1.5    # 占位哨兵值(单哨兵, 候选筛选)
NAV_PLACEHOLDER_OPEN = 1.49  # 辅助线索(旧双哨兵第二项), 只作 detail 不作必要条件
NAV_PLACEHOLDER_JUMP = 0.15  # 不连续阈值: |nav/邻日 - 1| >= 15% 视为占位残留跳变

# 候选筛选 WHERE(SQL 侧统一用, 只筛"可能是残留"的行, 最终判定走 is_placeholder_row)
CANDIDATE_WHERE = "accum_nav = 1.5 AND etf_name <> etf_code"


def is_placeholder_row(nav: float | None, prev_nav: float | None, next_nav: float | None) -> bool:
    """判定单日 accum_nav 是否为占位残留(调用方需提供该 ETF 前后交易日 nav)。

    nav≈1.5 且与前后交易日都不连续(相对变化 >= JUMP, 或邻日缺失时另一侧也不连续)
    → True(占位残留)。任一邻日连续 → False(真实平滑数据)。
    """
    if nav is None or abs(nav - NAV_PLACEHOLDER_VAL) >= 1e-9:
        return False
    if prev_nav is not None and prev_nav > 0 and abs(nav / prev_nav - 1) < NAV_PLACEHOLDER_JUMP:
        return False  # 与前日连续(平滑)=真实数据
    if next_nav is not None and next_nav > 0 and abs(next_nav / nav - 1) < NAV_PLACEHOLDER_JUMP:
        return False  # 与后日连续(平滑)=真实数据
    return True  # 孤立跳变到 1.5 = 占位残留