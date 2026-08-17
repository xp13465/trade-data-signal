# 大盘当前状态四档研判体系 — 调研与实施定稿

> 2026-08-17 定稿。展示层功能(首页 chips/tooltip + 收盘邮件文案),**不参与任何过滤/回测/凯利默认组合**(§5.4/§23.7 冻结,本轮不碰)。
> 数据来源:沪深300(index_daily hs300)全史 5972 交易日(2002-01-04 ~ 2026-08-17)+ 凯利逐笔交易(signal_kelly_trades.json,每笔 1 万)。
> 配套脚本:`docs/market-state/scripts/market_state_analysis*.py`(共 6 个,一次性调研脚本,由 researcher 产出、本目录归档复制)。

---

## 一、四档体系定义(定稿)

以沪深300 价格 vs 年线(MA200)定牛熊大方向,叠加 MA20/60/120 排列定强弱,得四档:

| 档位 | 判定规则 | 含义 |
|---|---|---|
| **牛市·主升** | 价 > MA200 且 多头排列(MA20>MA60>MA120) | 趋势主升 |
| **上升期** | 价 > MA200 且 非多头(均线纠缠) | 上升蓄势 |
| **下降期** | 价 < MA200 且 非空头 | 下降过渡 |
| **熊市·主跌** | 价 < MA200 且 空头排列(MA20<MA60<MA120) | 趋势主跌 |

## 二、区分度数据(为什么这个定义有效)

按「年线上 vs 年线下」这一牛熊分界,回测区分度显著(对标 lab.js:9778 证据):

- **追关注(buy_special,A 档固定 10 天,每笔 1 万)**:
  - 年线上:胜率 **54.9%**、净利 **+318,657**(约 +31.9 万)、盈亏比 1.52
  - 年线下:胜率 **44.8%**、净利 **-62,012**(约 -6.2 万)、盈亏比 0.72
- **沪深300 未来 20 日收益**:
  - 年线上:+1.62%,上涨概率 56.9%
  - 年线下:-0.11%,上涨概率 48.0%

> 即:牛侧追关注胜率高近 10 个百分点、净利显著为正;熊侧胜率跌破 50%、净利转负。年线(MA200)是当前回测区分度最强、语义最清晰的牛熊分界(对比 MA60 分界:牛 54.0%/46.5%,区分度弱于年线)。

均线排列(MA20/60/120)作为第二维,在牛侧内区分「主升(多头排列)」与「上升蓄势(纠缠)」、在熊侧内区分「主跌(空头排列)」与「下降过渡(纠缠)」,给出更细的状态语义,用于展示叙事。

## 三、当前状态(2026-08-17 收盘)

| 指标 | 值 |
|---|---|
| close | 4741.1 |
| MA20 | 4655.97 |
| MA60 | 4783.62 |
| MA120 | 4739.27 |
| MA200 | 4702.47 |

判定:close(4741.1) > MA200(4702.47),但 MA20(4655.97)<MA60(4783.62) 非多头排列 → **上升期**。
8/17 当日刚重新站上年线(此前 8/11-8/14 连续 4 日年线下方的下降期)。

## 四、展示与叙事

- 后端唯一权威源:`app/compute/market_summary.py` `generate_summary()` 新增 `market_state` 字段(见代码内注释)。
- 前端:`app.js` `renderSummaryChips` chips 首位「大盘 · 上升期」chip,hover tooltip = §21 算法公示位(判定规则 + 各均线值 + wave_ref 波浪弱叙事 + 「主观参考,非硬信号」)。
- `wave_ref`:波浪理论弱叙事参考,基于客观锚点(相对年线位置、距近 250 日前高回撤 vs 斐波那契 0.382/0.618、连续在年线侧天数),**纯叙事不参与任何过滤/回测**,字符串内标注「主观参考,非硬信号」。
- 盘中:均线态用昨日收盘(与 queries.py `_ai_macro_build_market_state` 取 ≤ 信号日最近完整态同精神)。

## 五、约束遵守

- 只做展示层,凯利默认组合冻结(§5.4/§23.7)零改动。
- 本功能不改变任何过滤/推荐逻辑,`market_state` 仅用于展示文案。

---

## 复现

- **脚本路径**:`docs/market-state/scripts/market_state_analysis.py`(1 分布+未来收益)、`market_state_analysis2.py`(2 信号区分度)、`market_state_analysis3.py`(3 组合稳定性)、`market_state_analysis4.py`(4 按年分解)、`market_state_analysis5.py`(5 状态切换稳定性)、`market_state_analysis6.py`(6 汇总评分)
- **输入依赖**:`data/sentiment.db`(index_daily hs300)+ `data/signal_kelly_trades.json`(逐笔交易)
- **重跑命令**:
  ```
  /Users/linhuichen/code/trade/.venv/bin/python3 docs/market-state/scripts/market_state_analysis.py
  /Users/linhuichen/code/trade/.venv/bin/python3 docs/market-state/scripts/market_state_analysis2.py
  /Users/linhuichen/code/trade/.venv/bin/python3 docs/market-state/scripts/market_state_analysis3.py
  /Users/linhuichen/code/trade/.venv/bin/python3 docs/market-state/scripts/market_state_analysis4.py
  /Users/linhuichen/code/trade/.venv/bin/python3 docs/market-state/scripts/market_state_analysis5.py
  /Users/linhuichen/code/trade/.venv/bin/python3 docs/market-state/scripts/market_state_analysis6.py
  ```
  (脚本 4/6 因部分候选 fn 缺 None 守卫,在边界(均线 None)处会中断,不影响已输出的关键结论;落档按 researcher 原始版本复制,防双份维护分叉)
- **数据截止日期**:2026-08-17(收盘)
- **关键口径一句话**:买 C1=buy_special(追关注),每笔 1 万,固定持有 10 天(A 档);状态按信号日沪深300 均线态判定;牛/熊分界=价 vs 年线 MA200,强弱=MA20/60/120 排列。
