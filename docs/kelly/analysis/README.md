# analysis/ 凯利分析类报告索引

> 认知差/费率/收益线性/时机/卡间水印等分析类报告。**如何新增**:报告放本目录(`kelly-<主题>.md`),脚本放 `scripts/`,并同步更新本索引。

| 文档 | 说明 |
|---|---|
| kelly-ai-suggestion-wrong-entry-quantify.md | **量化「错进 AI 建议」:修复前历史次数 + 修复后干净验证**(2026-08-14,本轮新增;814 债类 self-ETF 错进候选 882 次/748 交易日,空数组/无key 仅全档位错进,修复后目标类别错进=0;脚本 `scripts/replay_candidate.py`+`scripts/full_sweep.py`) |
| kelly-bond-inclusion-probe.md | **债类指数纳入回测穷举对比:纳入债类收益率变差,不建议纳入**(2026-08-14,本轮新增;数据 `data/bond_probe_comparison.json`+脚本 `scripts/signal_kelly_backtest_bond.py`) |
| kelly-yearly-vs-drawdown-cognitive-gap.md | **认知差:按年收益率 vs 峰值资金回撤两把尺子**(2026-08-14,本轮新增) |
| kelly-ai-predict-hit-method.md | **AI 预测命中口径 0.1→0.5 说明**(2026-08-14,本轮新增) |
| kelly-analysis.md | 凯利分析总览 |
| kelly-card-comparison-watermark.md | 卡间比较水印(蓝★紫◆全局互比) |
| kelly-fee-adjust-sim-eval.md | 费率调整模拟评估 |
| kelly-fee-adjust.md | 费率调整 |
| kelly-fee-presets.md | 费率预设 |
| kelly-return-linear-analysis.md | 收益线性分析 |
| kelly-timing-analysis.md | 时机分析 |
