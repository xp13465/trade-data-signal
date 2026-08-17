# docs/market-state — 大盘当前状态四档研判体系

展示层「大盘状态」四档(牛市·主升/上升期/下降期/熊市·主跌)的调研与实施归档。

## 目录索引

- **报告**:`market-state-analysis.md` — 四档定义 + 区分度数据 + 当前状态 + 复现段
- **脚本**:`scripts/market_state_analysis*.py` — 6 个一次性调研脚本(1 分布+未来收益 / 2 信号区分度 / 3 组合稳定性 / 4 按年分解 / 5 状态切换稳定性 / 6 汇总评分)
- **数据**:复用 `data/sentiment.db`(index_daily hs300)+ `data/signal_kelly_trades.json`,无独立数据文件

## 相关代码

- 后端唯一权威源:`app/compute/market_summary.py` `generate_summary()` → `market_state` 字段
- 前端展示:`static-site/app.js` `renderSummaryChips` 首位「大盘」chip(tooltip = §21 公示位)
- 盘中昨收态对齐:`app/queries.py` `_ai_macro_build_market_state`(MA60 牛熊,凯利过滤用,与本四档展示独立)

## 约束

仅展示层,不参与任何过滤/回测/凯利默认组合(§5.4/§23.7 冻结)。
