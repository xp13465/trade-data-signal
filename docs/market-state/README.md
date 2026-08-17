# docs/market-state — 大盘当前状态四档研判体系

展示层「大盘状态」四档(牛市·主升/上升期/下降期/熊市·主跌)的调研、实施与「接入凯利过滤」效用评估归档。

## 目录索引

- **报告**:
  - `market-state-analysis.md` — 四档定义 + 区分度数据 + 当前状态 + 复现段(展示层定稿)
  - `kelly-market-state-4tier-utility.md` — **四档接入凯利过滤效用评估(穷举回测)**:基线复现 PASS + 维度1 边际/维度2 仓位/维度3 按年稳定性/维度4 波浪不可回测 + 最终推荐(R1_all 替换式 +65,551 主推 / V4d_all 加法 +40,409 备选)
  - `kelly-4tier-extreme-windows-9mode.md` — 极端行情窗口验证+9模式明细(R1_all 救 94 笔 +7,883 未放真熊,2020 滞后带 1 笔 -570 是唯一放行)
  - `kelly-4tier-period-windows.md` — 分周期窗口 A/B 对比(四档状态段/大阶段/年度,增益集中下降期 +37,731)
  - `kelly-4tier-lagexempt-compare.md` — **R1_lag 滞后带豁免变体四口径全表**(基线/R1_all/V4d_all/R1_lag)+ 2026 滞后带专项 + 分周期三表四口径 | 脚本 `scripts/kelly_4tier_lagexempt.py` | 数据 `data/results_4tier_lagexempt.json`
- **脚本**:`scripts/` — 展示层调研 6 个(`market_state_analysis*.py`)+ 凯利接入回测 8 个(`kelly_4tier_*.py` + `kelly_engine.py`/`kelly_opg_engine.py` 依赖副本)
- **数据**:`data/results_4tier_variants.json`(基线+11 变体全模式)+ `results_4tier_replace.json`(R1/R1b/R1c+重叠度)+ `results_4tier_extreme.json`(9 模式明细 + 5 极端窗口 + 94 笔救回单明细 + 滞后带统计)+ `results_4tier_period.json`(分周期 A/B)+ `results_4tier_lagexempt.json`(四口径全表);展示层复用 `data/sentiment.db`(index_daily hs300)+ `signal_kelly_trades.json`

## 相关代码

- 后端唯一权威源:`app/compute/market_summary.py` `generate_summary()` → `market_state` 字段(展示层四档)
- 前端展示:`static-site/app.js` `renderSummaryChips` 首位「大盘」chip(tooltip = §21 公示位)
- 凯利过滤状态判定(现状 MA60 二进制):`app/queries.py` `_ai_macro_build_market_state`——本目录 `kelly-market-state-4tier-utility.md` 评估用四档替换它

## 约束

- 展示层四档**仅展示,不参与过滤/回测/凯利默认组合**(§5.4/§23.7 冻结)——接入凯利是**研究层结论 + B 级改动**,需用户拍板后才实施(见效用评估报告 §5 推荐)。
- 凯利回测数字基于**固化副本** `signal_kelly_trades.json` 批 2026-08-17 21:58,复现见报告「## 复现」段。
