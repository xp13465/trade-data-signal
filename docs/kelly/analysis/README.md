# analysis/ 凯利分析类报告索引
| kelly-quadrant-loss-elimination.md | **亏损象限识别与剔除验证:用户假设 y1 成立/全周期不成立,细粒度子群降亏键是正解,候选 K2C5港股追涨/K3主关注×概念**(2026-08-15;数据 `data/kelly-quadrant-mining-data.json`+脚本 `scripts/quadrant_mining/`10个)。**§7 口径补测(2026-08-15)**:初版用裸 G(不可操作)测,用户质疑后按 v1.0.0 基准重测(G 用 13万 P≤3d 可操作口径 + F 等 9 模式全测),结论:降亏键对 A/F 短持正贡献、对可操作 G 转负(路径噪声),依玩法模式分裂,结论以 §7 为准。补测数据 `data/kelly-quadrant-opg-data.json`+脚本 `kelly_opg_engine.py`/`kelly_opg_yearly.py` |

> 认知差/费率/收益线性/时机/卡间水印等分析类报告。**如何新增**:报告放本目录(`kelly-<主题>.md`),脚本放 `scripts/`,并同步更新本索引。

| 文档 | 说明 |
|---|---|
| kelly-overfit-monitor-design.md | **过拟合监控系统设计方案(B档,2026-08-15 已实施)**:每日多维打点 + 4维过拟合指标(回测-实盘偏离/样本外/参数稳定/象限退化)+ 综合风险分(绿黄红)+ 综合预警邮件。实施 `scripts/overfit_monitor.py`(§7 实施说明,含与方案差异诚实标注) |
| kelly-ai-suggestion-wrong-entry-quantify.md | **量化「错进 AI 建议」:修复前历史次数 + 修复后干净验证**(2026-08-14,本轮新增;814 债类 self-ETF 错进候选 882 次/748 交易日,空数组/无key 仅全档位错进,修复后目标类别错进=0;脚本 `scripts/replay_candidate.py`+`scripts/full_sweep.py`) |
| kelly-bond-inclusion-probe.md | **债类指数纳入回测穷举对比:纳入债类收益率变差,不建议纳入**(2026-08-14,本轮新增;数据 `data/bond_probe_comparison.json`+脚本 `scripts/signal_kelly_backtest_bond.py`) |
| kelly-yearly-vs-drawdown-cognitive-gap.md | **认知差:按年收益率 vs 峰值资金回撤两把尺子**(2026-08-14,本轮新增) |
| kelly-ai-macro8-special-signal-exclusion.md | **AI宏4+3+1调研:债类/波段特殊信号不入样,不做「+1」,三重验证+#25已覆盖**(2026-08-14,本轮新增) |
| kelly-ai-predict-hit-method.md | **AI 预测命中口径 0.1→0.5 说明**(2026-08-14,本轮新增) |
| kelly-analysis.md | 凯利分析总览 |
| kelly-card-comparison-watermark.md | 卡间比较水印(蓝★紫◆全局互比) |
| kelly-fee-adjust-sim-eval.md | 费率调整模拟评估 |
| kelly-fee-adjust.md | 费率调整 |
| kelly-fee-presets.md | 费率预设 |
| kelly-return-linear-analysis.md | 收益线性分析 |
| kelly-timing-analysis.md | 时机分析 |
