# scripts/ 凯利回测运行脚本索引(23 脚本)

> 全部回测/复算脚本统一放本目录(互相 import 不拆散)。每个脚本头部含注释块(用途/日期/结论/依赖/复现)。
> **如何新增**:新脚本放本目录 + 头部注释块 + 在本索引追加一行;多个中间演进版标注"以最新版为准"。
> 脚本内含硬编码绝对路径(/tmp、/Users/linhuichen/code/trade),如需重跑请确认路径或改相对路径。

## A 组(策略A/B 对比 + K=3 分仓行为)

| 脚本 | 用途 | 复现 |
|---|---|---|
| strategyAB_compare.py | 策略A(固定拆K)vs 策略B(每日池等分)穷举对比,净利 B 恒优,K=1 A≡B | python3 strategyAB_compare.py |
| strategyAB_robust.py | 策略A/B 稳健性:G 模式空filter/4组合全开下结论一致 | python3 strategyAB_robust.py |
| amount_verify.js | K=3 分仓行为:1信号日=10000/49天、2=5000/12天、3=3333/4天 | node amount_verify.js |
| kelly_verify_amount.py | 金额口径另一验证(对照 amount_verify.js) | python3 kelly_verify_amount.py |

## B 组(每日池口径穷举重跑)

| 脚本 | 用途 | 复现 |
|---|---|---|
| dailypool_rerun_core.py | 每日池口径穷举重跑核心(08-13 权威基线) | python3 dailypool_rerun_core.py |
| dailypool_rerun_final.py | 每日池最优配置矩阵(AI宏7键±greedy15±a45) | python3 dailypool_rerun_final.py |
| dailypool_rerun_final2.py | 每日池最优穷举(演进版 final2,对应报告 §0.2) | python3 dailypool_rerun_final2.py |
| dailypool_rerun_opt.py | 最优组合穷举(LOO+单加+双加)+按年分解+B模式 | python3 dailypool_rerun_opt.py |
| dailypool_rerun_ratio.py | 每日池 standalone 减亏比值 vs 页面旧 ratio | python3 dailypool_rerun_ratio.py |

## C 组(认知差:按年收益率 vs 峰值资金回撤)

| 脚本 | 用途 | 复现 | 演进 |
|---|---|---|---|
| kelly_yearly_recalc.js | 按年收益率复算(-9.26% 来源) | node kelly_yearly_recalc.js | 最终版 |
| kelly_yearly_dd3.js | 2011 回撤 14.01% 复算(峰值→谷底) | node kelly_yearly_dd3.js | **最终版,以此为准** |
| kelly_yearly_dd.js | 回撤中间演进版1 | node kelly_yearly_dd.js | 演进版,以 dd3 为准 |
| kelly_yearly_dd2.js | 回撤中间演进版2 | node kelly_yearly_dd2.js | 演进版,以 dd3 为准 |
| dd_2011_curve.js | 2011 A 模式逐笔资金曲线(峰值/谷底标记,依赖 dd3) | node dd_2011_curve.js | |
| dd_2011_trace.js | 2011 A 模式逐笔资金曲线(复刻前端每日池+topK+费率) | node dd_2011_trace.js | |

## D 组(共享依赖,被大量脚本 import)

| 脚本 | 用途 | 依赖方 |
|---|---|---|
| kelly_combo_advice_analysis.py | passes_fade/fIdx/empty_filters/BUY_AMOUNT/compute_stats/to_row | strategyAB/dailypool 组 |
| kelly_posfilter_backtest.py | base_signals/get_by_date/base_key | strategyAB/dailypool 组 |

## E 组(债类纳入回测 probe,2026-08-14)

| 脚本 | 用途 | 复现 |
|---|---|---|
| signal_kelly_backtest_bond.py | 债类(self-ETF 兜底)纳入 vs 不纳入穷举对比(结论:纳入变差不建议)+ `--include-band` 波段(band_hold)纳入对比(更差,过度交易浪费仓位);报告 `analysis/kelly-bond-inclusion-probe.md`,数据 `analysis/data/bond_probe_comparison.json` | python3 scripts/signal_kelly_backtest_bond.py [--include-band] --output docs/kelly/analysis/data/bond_probe_comparison.json |

## 其他(组合分类/提取/AI 预测/4组合核验)

| 脚本 | 用途 | 复现 |
|---|---|---|
| rebackfill_daily_brief.py | AI 预测命中口径 0.1→0.5 后历史命中重刷(0/3→2/3) | python3 rebackfill_daily_brief.py <history.json> |
| classify_kelly_3pp.js | 3pp 组合分类分析(VM 加载 lab.js) | node classify_kelly_3pp.js |
| analyze_kelly_3pp.py | 3pp 组合分类(对照 JS 版) | python3 analyze_kelly_3pp.py |
| extract_kelly_v2.py | 组合提取(映射 toggle 集 + v2 结果提取) | python3 extract_kelly_v2.py |
| kelly-4combo-a45-backtest.js | 4组合+a45 回测复刻(pool vs fixed) | node kelly-4combo-a45-backtest.js |
| kelly-final-check.js | 4组合最终核验(读 4combo 输出) | node kelly-final-check.js |
