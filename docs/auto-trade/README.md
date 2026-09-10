# auto-trade · 自动交易调研与设计

本目录承载「自动化交易」方向的调研报告/PRD/脚本。

## 文档

| 文件 | 内容 | 状态 |
|---|---|---|
| next-day-buy-prd-20260910.md | 自动化次日买入操作 PRD(细化): 两阶段总纲(阶段一=傻瓜式操作指南+操作步骤表格展示, 阶段二=同一 JSON 自动化)、S06+K=1+A 模式口径、每日时间轴、执行策略回测定稿(挂昨收价限价最优)、§6 实操步骤表格(字段/STATUS状态机/盘中发布链/手动指引/自动化衔接/1:1示例)、风控/记账/监控、分阶段路线 | 2026-09-10 v1.1, 待用户审阅拍板 |
| nextday-plan-backend-implement-20260910.md | 阶段一实施报告(后端): nextday_plan 计划生成器 + auto_trade_steps 状态机落档; 复用 kelly_posrating K=1 同构逻辑、双校验、R2/两树同步、20:55 launchd、复现段 | 2026-09-10 已实施(干跑 AUTO_EXEC_ON=false) |

## 计划生成器(scripts/ 根, 生产链路)

PRD 阶段一后端产物的生产入口在 `scripts/nextday_plan_generator.py`(每日 20:55 launchd
`com.trade.nextday-plan` 通过 `scripts/nextday_plan.sh` 触发), 生成
`data/nextday_plan.json` + `static-site/data/nextday_plan.json` + `auto_trade_steps.json`
并 R2 同步。详见实施报告 `nextday-plan-backend-implement-20260910.md`。

## 脚本(scripts/)

| 脚本 | 用途 | 复现 |
|---|---|---|
| nextday_buy_execution_backtest.py | 挂单折扣档位扫(E[综合买入价] 口径, 昨收基准, tail/skip 两 miss_action, 按年分解) | `python3 docs/auto-trade/scripts/nextday_buy_execution_backtest.py` |
| nextday_buy_full_loop_backtest.py | 完整环路对比(S0-baseline / 挂昨收 / 折扣 skip / 折扣 tail, 接入 A 模式卖出价) | `python3 docs/auto-trade/scripts/nextday_buy_full_loop_backtest.py` |
| nextday_buy_stability.py | 按年/分半稳定性 + 用户假设验证 | `python3 docs/auto-trade/scripts/nextday_buy_stability.py` |
| nextday_exec_manual.py | 实操步骤表格手动状态更新(阶段一跟单工具: --list / --status 状态机白名单校验) | `python3 docs/auto-trade/scripts/nextday_exec_manual.py --status <date> <seq> <new_status>` |

## 数据产物

- nextday_buy_exec.json / nextday_buy_full_loop.json(回测结果快照, 同目录 scripts/ 下)
- nextday_steps_example.json(实操步骤表格 1:1 示例: 2026-09-04 真实信号→2026-09-07 执行日, 159023 养殖ETF万家, 昨收 1.123 挂单, 含判断条件链)
- **nextday_plan.json**(生产, 生成器产出, 本地 data/ + static-site/data/ + R2: 当日计划 {date, plan:[{etf_code,etf_name,prev_close,amount,signal,track_score,signal_date,buy_date}]} / 空计划 {date,empty})
- **auto_trade_steps.json**(生产, 生成器产出, static-site/data/ + R2: 行为级状态机追加存档 {schema_version:"v1", steps:[...]}, seq1=9:15 挂单行为 pending, 幂等: 同执行日已存在则跳过)

核心结论速查: 次日买入执行 = 集合竞价挂「昨收价」限价单(85.3% 成交, 其中 60% 低开按更低开盘价成交); 挂昨收+尾盘兜底全史 +156,260 元(2026-09-10 口径修正, 真·放弃 +135,969 / 开盘直买 +158,397); 尾盘市价兜底为最优补充; 用户假设「-0.5% 85%成交」实测 60.2%, 已按数据修正。
