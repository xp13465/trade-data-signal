# auto-trade · 自动交易调研与设计

本目录承载「自动化交易」方向的调研报告/PRD/脚本。

## 文档

| 文件 | 内容 | 状态 |
|---|---|---|
| next-day-buy-prd-20260910.md | 自动化次日买入操作 PRD(细化): S06+K=1+A 模式口径、每日时间轴、执行策略回测定稿(挂昨收价限价最优)、风控/记账/监控、分阶段路线、用户操作指引 | 2026-09-10 初稿, 待用户审阅拍板 |

## 脚本(scripts/)

| 脚本 | 用途 | 复现 |
|---|---|---|
| nextday_buy_execution_backtest.py | 挂单折扣档位扫(E[综合买入价] 口径, 昨收基准, tail/skip 两 miss_action, 按年分解) | `python3 docs/auto-trade/scripts/nextday_buy_execution_backtest.py` |
| nextday_buy_full_loop_backtest.py | 完整环路对比(S0-baseline / 挂昨收 / 折扣 skip / 折扣 tail, 接入 A 模式卖出价) | `python3 docs/auto-trade/scripts/nextday_buy_full_loop_backtest.py` |
| nextday_buy_stability.py | 按年/分半稳定性 + 用户假设验证 | `python3 docs/auto-trade/scripts/nextday_buy_stability.py` |

## 数据产物

- nextday_buy_exec.json / nextday_buy_full_loop.json(回测结果快照, 同目录 scripts/ 下)

核心结论速查: 次日买入执行 = 集合竞价挂「昨收价」限价单(85.3% 成交, 其中 60% 低开按更低开盘价成交), 绝对收益全史 545 笔 +165,407 元 > 开盘直买 +158,397 元; 尾盘市价兜底为负优化; 用户假设「-0.5% 85%成交」实测 60.2%, 已按数据修正。
