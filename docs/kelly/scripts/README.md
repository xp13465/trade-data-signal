# scripts/ 凯利回测运行脚本索引(41 脚本)

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
| dailypool_rerun_ratio.py | 每日池 standalone 减亏比值 vs 页面旧 ratio(2026-08-16 扩展 K2C5/K3: K2C5 ALL9-K1 比值4.55, 详见 analysis/kelly-k2c5-dailypool-ratio.md) | python3 dailypool_rerun_ratio.py |

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


## F 组(次日分批挂单回测,2026-08-15;报告 position/kelly-nextday-batch-limit-sop.md,数据 position/data/kelly_nextday_batch_limit_data.json)

| 脚本 | 用途 | 复现 |
|---|---|---|
| kelly_batch_limit_engine.py | **核心引擎**(兜底/严格/完整/用户版 + gap 映射,每日池 vs 每笔1万,补单来源) | python3 docs/kelly/scripts/kelly_batch_limit_engine.py |
| kelly_batch_limit_matrix.py | 主矩阵:K=买全部/1/2/3/4 × N=1/2/3 × (严格不补/严格+池内补/严格+降级补/兜底) | python3 docs/kelly/scripts/kelly_batch_limit_matrix.py |
| kelly_batch_limit_depth.py | 挂单深度敏感性 -0.5%/-1%/-1.5%/-2%(结论:-1% 最优) | python3 docs/kelly/scripts/kelly_batch_limit_depth.py |
| kelly_batch_limit_ext1.py | 每笔固定1万 + toggle a45+exclBear(每笔1万峰值296-411万不可操作) | python3 docs/kelly/scripts/kelly_batch_limit_ext1.py |
| kelly_batch_limit_ext2.py | 9模式 + 按市场(⚠️ 按年段 zip 错位 bug,按年以 yearly.py 为准) | python3 docs/kelly/scripts/kelly_batch_limit_ext2.py |
| kelly_batch_limit_yearly.py | 按年分解修复版(按 next_date 分组,2011-2026 全正改善) | python3 docs/kelly/scripts/kelly_batch_limit_yearly.py |
| kelly_batch_limit_full_play.py | 完整玩法(严格优先-1%+降级补+开盘兜底)vs 兜底(兜底更优) | python3 docs/kelly/scripts/kelly_batch_limit_full_play.py |
| kelly_batch_limit_user.py | 用户原话版(固定top-N+缺额补挂):池内补≈兜底,降级补净利大降 | python3 docs/kelly/scripts/kelly_batch_limit_user.py |
| kelly_batch_limit_smooth.py | 均价平滑度(兜底均值-0.37%/中位0%/标准差0.43%) | python3 docs/kelly/scripts/kelly_batch_limit_smooth.py |
| kelly_batch_limit_final.py | 兜底 N=K 完整表(K1-N1 净+861,375/53.17% 最优) | python3 docs/kelly/scripts/kelly_batch_limit_final.py |
| kelly_batch_all.py | 综合汇总(**权威数据源**,产出报告引用 json) | python3 docs/kelly/scripts/kelly_batch_all.py |
| kelly_ksens.py | 基建:full_sort_key 排序 + keep_topk(被 engine 依赖) | - |
| kelly_dailypool.py | 基建:每日池等分 + compute_scaled(被 engine 依赖) | - |
| kelly_af_matrix_verify.py | A/F/G 三模式主矩阵验证(§四 补档,空filter+AI宏7键;A/F 峰值9-14倍可操作、G 162-173倍不可操作) | python3 docs/kelly/scripts/kelly_af_matrix_verify.py |
| kelly_ghi_g_scan.py | G 模式专项穷举(强平顺序矩阵/cap扫描/稳健性/利润结构;P≤3d 最优根因) | python3 docs/kelly/scripts/kelly_ghi_g_scan.py |
| kelly_combine_p3d2.py | 结合版 v2(次日分批×P≤3d,runcase 内核;被下两脚本 exec 加载) | python3 docs/kelly/scripts/kelly_combine_p3d2.py |
| kelly_p3d_open_ef.py | 空filter 三路 P≤3d 对照(§六.9 主表来源:@13万 当日172.19>次日分批170.89>次日开盘157.55) | python3 docs/kelly/scripts/kelly_p3d_open_ef.py |
| kelly_combine_k2.py | 结合版 K=1/2/3 全对比(§六.9 AI宏7键对照 + K 延伸) | python3 docs/kelly/scripts/kelly_combine_k2.py |

## 其他(组合分类/提取/AI 预测/4组合核验)

| 脚本 | 用途 | 复现 |
|---|---|---|
| rebackfill_daily_brief.py | AI 预测命中口径 0.1→0.5 后历史命中重刷(0/3→2/3) | python3 rebackfill_daily_brief.py <history.json> |
| classify_kelly_3pp.js | 3pp 组合分类分析(VM 加载 lab.js) | node classify_kelly_3pp.js |
| analyze_kelly_3pp.py | 3pp 组合分类(对照 JS 版) | python3 analyze_kelly_3pp.py |
| extract_kelly_v2.py | 组合提取(映射 toggle 集 + v2 结果提取) | python3 extract_kelly_v2.py |
| kelly-4combo-a45-backtest.js | 4组合+a45 回测复刻(pool vs fixed) | node kelly-4combo-a45-backtest.js |
| kelly-final-check.js | 4组合最终核验(读 4combo 输出) | node kelly-final-check.js |
