# 数据字典 · tdsignal 静态产物

> 本文件列出 `static-site/data/` 下主要 JSON 文件的字段说明，供外部使用者理解数据结构。
>
> 数据来源：[`app/queries.py`](../app/queries.py) 共享查询层从 SQLite (data/sentiment.db) 读取，由 [`static-site/export.py`](../static-site/export.py) 每日盘后导出。
>
> 所有日期字段格式均为 `YYYYMMDD` 字符串（如 `20260724`）。OHLC = 开/高/低/收。`pct_change` 为百分比小数（如 0.65 表示 +0.65%）。
>
> 采集时点：每交易日 17:50（CST）跑 [`scripts/update_all.sh`](../scripts/update_all.sh) 4 条并行 pipeline 后由 [`scripts/deploy.sh`](../scripts/deploy.sh) 导出推送。盘中 09:35–15:00 每 15 分钟跑 `intraday_snapshot` 推 `intraday_snapshot.json` 实时快照。详见 [data-sources.md](data-sources.md)。
>
> 时间窗口（range）：5 个 tab 端点（a-stock / hk / global / sentiment / industry）各预生成 `3m / 6m / 1y / 3y / 5y / all` 6 个 JSON 文件，前端按 range 直接读对应文件。`1m` 已废弃。

---

## 目录

- [1. overview.json · 今日快照](#1-overviewjson--今日快照)
- [2. sentiment-\*.json · 情绪指数历史](#2-sentiment-json--情绪指数历史)
- [3. a-stock-\*.json · A 股指标 + 指数](#3-a-stock-json--a-股指标--指数)
- [4. hk-\*.json · 港股](#4-hk-json--港股)
- [5. global-\*.json + global-extras-\*.json · 全球 + 商品/汇率/债券](#5-global-json--global-extras-json--全球--商品汇率债券)
- [6. industry-\*.json + industry-3y-indices/ · 行业](#6-industry-json--industry-3y-indices--行业)
- [7. etf_national_team-\*.json · 国家队 ETF 资金动向](#7-etf_national_team-json--国家队-etf-资金动向)
- [8. futures.json · 期货机构持仓](#8-futuresjson--期货机构持仓)
- [9. summary.json + summary_history.json · 收盘速递](#9-summaryjson--summary_historyjson--收盘速递)
- [10. signal_stats.json · 买卖点回测统计](#10-signal_statsjson--买卖点回测统计)
- [11. index/{id}-all.json · 单指数全历史](#11-indexid-alljson--单指数全历史)
- [12. position/ma_alignment/ad_line/new_high_low/volume_ratio/rotation · 大盘宽度](#12-positionma_alignmentad_linenew_high_lowvolume_ratiorotation--大盘宽度)
- [13. alert.json + alert_analyze_{id}.json · 风险预警](#13-alertjson--alert_analyzeidjson--风险预警)
- [14. intraday_snapshot.json · 盘中实时快照](#14-intraday_snapshotjson--盘中实时快照)
- [15. etf_score_list.json · ETF 评分榜单](#15-etf_score_listjson--etf-评分榜单)
- [16. lab/\*.json · 策略实验室回测](#16-labjson--策略实验室回测)
- [17. trade_sim/\*.json · 买卖点模拟交易](#17-trade_simjson--买卖点模拟交易)
- [18. schedule_stats.json + signal_freq.json · 调度统计与信号频率](#18-schedule_statsjson--signal_freqjson--调度统计与信号频率)
- [19. feed.xml · RSS 收盘速递](#19-feedxml--rss-收盘速递)

---

## 1. overview.json · 今日快照

首页一句话总结 + KPI 卡片数据。聚合当日所有核心指标的最小快照，前端首屏直接读它（无需拉 6 个 tab JSON）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `date` | string | 数据日期 `YYYYMMDD`（最近交易日） |
| `collected_at` | string | 采集完成时间 `YYYYMMDD HH:MM:SS` |
| `collect_health` | object | 采集健康度，见下 |
| `scores` | object | 当日各情绪分，见下 |
| `signals_today` | array | 今日触发买卖点信号列表，元素见下 |
| `recent_freeze` | array | 近期冰点日列表（score<20） |
| `today` | object | `{scores: 同 scores, metrics: array(20个a_*指标当日值)}` |
| `indices_sparkline` | object | 11 个核心指数 sparkline 数据 `{sh/sz/hs300/sz50/cyb/kc50/bj50/csi500/csi1000/hsi/hstech: [{date, close}]}` |
| `width_1m` | object | `{up: 上涨家数, down: 下跌家数}` |
| `cross_market_6m` | array | 跨市场综合评分 6 月序列 `[{date, value, is_freeze, is_overheat}]` |
| `a_sentiment_6m` | array | A 股综合情绪分 6 月序列，结构同上 |
| `fear_greed_6m` | array | 恐贪指数 6 月序列，结构同上 |
| `industry_heatmap` | array | 31 个申万一级行业涨跌幅热力图 `[{id, name, pct_1d, pct_5d, last_date}]` |
| `futures_date` | string | 期货持仓数据日期 |
| `etf_date` | string | ETF 份额数据日期 |
| `us_dji_date` | string | 美股数据日期（受时差影响可能 = T-1） |
| `csi_div_date` | string | 中证红利指数日期 |
| `nt_signals_today` | object | 国家队 ETF 当日信号，见下 |

`collect_health`:

```json
{
  "level": "ok|warn|error",
  "items": [{"metric_id": "a_fund_main", "status": "error", "message": "采集失败原因"}]
}
```

`scores`（11 个情绪分，每个 value=0-100）:

| score_id | 含义 |
|---|---|
| `a_sentiment` | A 股综合情绪分（6 项加权） |
| `cross_market` | 跨市场综合评分（去极值截尾均值） |
| `fear_greed` | 恐贪指数（8 分量等权） |
| `high_alert` | 高位预警分 |
| `low_alert` | 低位预警分（>77 触发冰点告警） |
| `sentiment_sz50` | 上证50 情绪分 |
| `sentiment_hs300` | 沪深300 情绪分 |
| `sentiment_csi500` | 中证500 情绪分 |
| `sentiment_csi1000` | 中证1000 情绪分 |
| `sentiment_cyb` | 创业板指 情绪分 |
| `sentiment_kc50` | 科创50 情绪分 |

`signals_today` 元素:

```json
{
  "date": "20260724",
  "index_id": "cgb_10y_future",
  "signal": "band_hold|buy|buy_aux|buy_special|sell|sell_stop_loss",
  "reason": "波段持有: 无超买超卖信号(RSI58,bias20 0.10%,BB位81%)"
}
```

`nt_signals_today`:

```json
{
  "date": "20260724",
  "signals": [{"code":"159915","name":"创业板ETF易方达","type":"share_surge|share_outflow|volume_surge","label":"进|出|量","share_change_yi":27.19,"amount_ratio":2.11,"intensity":5.31,"note":"极端异动"}],
  "n_surge": 3, "n_outflow": 0, "n_volume": 3,
  "resonance": "...", "is_resonance": true,
  "recent": {"days": 7, "total": 27, "surge": 18, "outflow": 0, "volume": 9, "resonance_days": 6, "daily": [...]}
}
```

---

## 2. sentiment-\*.json · 情绪指数历史

5 个时间窗口（`3m/6m/1y/3y/5y/all`）。9 个情绪分序列 + signals/stats/strategy。

| 字段 | 类型 | 说明 |
|---|---|---|
| `a_sentiment` | array | A 股综合情绪分历史 `[{date, value, is_freeze, is_overheat, components(JSON字符串)}]` |
| `cross_market` | array | 跨市场综合评分历史，结构同上 |
| `sentiment_sz50` | array | 上证50 情绪分历史，结构同上 |
| `sentiment_hs300` | array | 沪深300 情绪分历史 |
| `sentiment_csi500` | array | 中证500 情绪分历史 |
| `sentiment_csi1000` | array | 中证1000 情绪分历史 |
| `sentiment_cyb` | array | 创业板指 情绪分历史 |
| `sentiment_kc50` | array | 科创50 情绪分历史 |
| `fear_greed` | array | 恐贪指数历史 |
| `signals` | object | `{a_sentiment/cross_market/...: [{date, index_id, signal, reason}]}` 9 个分数各自的买卖点信号 |
| `stats` | object | `{a_sentiment/cross_market/...: {sell/buy/buy_aux: {5d/10d/20d: {win_rate, pl, mean, n}, frequency: {...}}}}` 回测统计 |
| `strategy` | object | `{a_sentiment/cross_market/...: {buy, buy_aux, sell, _detail:{buy/buy_aux/buy_special/sell: {desc, params, filter, enabled}}}}` 当前策略配置 |

`is_freeze=1` 表示当日该分数 < 20（冰点），`is_overheat=1` 表示 > 80（过热）。

`components` 字段是 JSON 字符串，记录该日打分的各分量值（如 `{"ratio":90.0,"zt":71.25,"amount":90.83}`），便于回溯打分构成。

---

## 3. a-stock-\*.json · A 股指标 + 指数

5 个时间窗口。32 个 A 股指标历史序列 + 12 个 A 股宽基指数 OHLC + 策略。

| 字段 | 类型 | 说明 |
|---|---|---|
| `metrics` | object | 32 个指标 `{id: {name, unit, data: [{date, value}]}}` |
| `indices` | object | 12 个宽基 `{id: {name, data:[{date, open, high, low, close, pct_change, amount}], strategy:{buy, buy_aux, sell, _detail}, etfs:[]}}` |

### 3.1 metrics（32 个指标，id -> name / unit）

| group | id | name | unit |
|---|---|---|---|
| a_width | `a_width_up_count` | 上涨家数 | 家 |
| a_width | `a_width_down_count` | 下跌家数 | 家 |
| a_width | `a_width_zt_count` | 涨停数(收盘封板) | 只 |
| a_width | `a_width_dt_count` | 跌停数(收盘封板) | 只 |
| a_width | `a_width_max_lianban` | 连板高度 | 板 |
| a_width | `a_width_zhaban_rate` | 炸板率 | % |
| a_width | `a_width_fengban_rate` | 封板率（=1-炸板率） | % |
| a_width | `a_width_daban_premium` | 打板溢价 | % |
| a_width | `a_width_zb_count` | 炸板数(收盘未封) | 只 |
| a_width | `a_width_seal_rate` | 封板率(zt/(zt+zb)) | % |
| a_fund | `a_fund_north` | 北向资金成交总额(HKEX官方源) | 亿元 |
| a_fund | `a_fund_north_quarterly` | 北向资金季度净买额(CCASS反算) | 亿元 |
| a_fund | `a_fund_margin` | 两融余额(沪市融资) | 亿元 |
| a_fund | `a_fund_main` | 主力净流入 | 亿元 |
| a_sentiment | `a_qvix_300` | 中国波指300 | 点 |
| a_sentiment | `a_qvix_1000` | 中国波指(50ETF期权) | 点 |
| a_sentiment | `a_amount` | 成交额(沪深京) | 亿元 |
| a_sentiment | `a_turnover_rate` | 换手率 | % |
| a_sentiment | `a_turnover_mean` | 全市场换手率均值 | % |
| a_sentiment | `a_turnover_median` | 全市场换手率中位数 | % |
| a_sentiment | `a_turnover_p90` | 换手率90分位 | % |
| a_sentiment | `a_turnover_p10` | 换手率10分位 | % |
| a_sentiment | `a_turnover_gt5_pct` | 换手率>5%家数占比 | - |
| a_sentiment | `a_div_yield` | 上证A股股息率 | % |
| lhb | `lhb_count` | 龙虎榜上榜家数 | 只 |
| lhb | `lhb_inst_net` | 机构净买入 | 亿元 |
| unlock | `unlock_amount` | 解禁规模 | 亿元 |
| unlock | `unlock_count` | 解禁家数 | 只 |
| ipo | `ipo_count` | IPO数量 | 只 |
| ipo | `ipo_amount` | IPO募资额 | 亿元 |
| cov | `cov_count` | 可转债数量 | 只 |
| cov | `cov_premium_median` | 转股溢价率中位数 | % |

> `a_width_zb_count`/`a_width_seal_rate`/`a_turnover_*` 由 [`app/collector/width_history.py`](../app/collector/width_history.py) 与 [`app/collector/cleanup_d3d2.py`](../app/collector/cleanup_d3d2.py) 从 mootdx/BaoStock 全 A 股日线聚合回填（10 年历史），scheduler 当日不采，仅查历史。其余指标每日 17:50 采。

### 3.2 indices（12 个 A 股宽基）

| id | 名称 |
|---|---|
| `sh` | 上证指数 |
| `sz` | 深成指 |
| `hs300` | 沪深300 |
| `sz50` | 上证50 |
| `csi500` | 中证500 |
| `csi1000` | 中证1000 |
| `cyb` | 创业板指 |
| `kc50` | 科创50 |
| `bj50` | 北证50 |
| `csi_div` | 中证红利 |
| `div_lowvol` | 红利低波 |
| `sz_div` | 深证红利 |

每指数 `data` 元素：`{date, open, high, low, close, pct_change, amount}`。`strategy` 含 `buy/buy_aux/sell` 当前生效规则字符串 + `_detail` 明细。

---

## 4. hk-\*.json · 港股

5 个时间窗口。3 港股宽基 + 港股通净买入 + 8 港股板块指数。

| 字段 | 类型 | 说明 |
|---|---|---|
| `indices` | object | 3 个宽基 `{hsi/hstech/hscei: {name, data:[{date, open, high, low, close, pct_change, amount}], strategy, etfs}}` |
| `hk_south` | array | 港股通南向资金历史 `[{date, value}]`（亿元） |
| `hk_industries` | object | 8 个港股板块 `{id: {name, data:[...], strategy, etfs}}` |

港股板块 id：`hk_cesg10`(中华博彩业)、`hk_hsmogi`(恒生内地油气)、`hk_hsmbi`(恒生内地银行)、`hk_hsmpi`(恒生内地地产)、`hk_cshklre`(中证香港地产)、`hk_cshklc`(中证香港消费)、`hk_hscci`(恒生中资企业)、`hk_cshkdiv`(中证香港红利)。

---

## 5. global-\*.json + global-extras-\*.json · 全球 + 商品/汇率/债券

5 个时间窗口。`global-*.json` 含全球指数 + 商品/汇率/债券 extras，`global-extras-*.json` 仅含 extras 单独导出（用于 R2 CDN 加速大文件拆分）。

`global-*.json` 字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `indices` | object | 全球指数 `{id: {name, data:[{date, open, high, low, close, pct_change, amount}], strategy, etfs}}` |
| `extras` | object | 10 个商品/汇率/债券 `{id: {name, unit, data:[{date, value}]}}` |
| `extras_signals` | object | 各 extras 的买卖点信号 |
| `extras_stats` | object | 各 extras 的回测统计 |
| `extras_strategy` | object | 各 extras 的策略配置 |

全球指数 id：`us_dji`(道琼斯) / `us_ixic`(纳斯达克) / `us_spx`(标普500) / `us_ndx`(纳斯达克100) / `nikkei225`(日经225) / `kospi`(韩国KOSPI) / `ftse100`(富时100) / `dax`(德国DAX) / `cac40`(法国CAC40) / `cgb_idx`(上证国债指数) / `cgb_10y_etf`(十年国债ETF) / `cgb_10y_future`(10年国债期货)。

extras id：`gold`(沪金) / `oil`(INE原油) / `wti_oil`(WTI) / `comex_silver`(COMEX白银) / `usdcnh`(离岸人民币) / `a_qvix_300`(中国波指300) / `a_qvix_1000`(50ETF期权波指) / `cn10y`(中国10年国债收益率) / `us10y`(美国10年国债收益率) / `cn_us_spread`(中美利差) / `brent`(布伦特原油)。

---

## 6. industry-\*.json + industry-3y-indices/ · 行业

5 个时间窗口的聚合文件 + 按行业拆分的单文件（用于 R2 CDN 加速 29MB 大文件）。

`industry-{range}.json`（range=3m/6m/1y/3y/5y/all）字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `indices` | object | 31 申万一级行业指数 `{sw_801xxx: {name, data:[{date, open, high, low, close, pct_change, amount}], signals, stats, strategy, fund_flow, turnover, width, etfs}}` |
| `heatmap` | array | 31 行业涨跌幅热力图 `[{id, name, pct_1d, pct_5d, last_date}]` |
| `concepts` | object | 27 同花顺概念板块 `{thsc_xxxxxx: 同上结构}` |

`industry-all-meta.json`：轻量元数据（`heatmap + index_ids[31] + concept_ids[27]`），前端首屏先读它做热力图渲染，再按需 fetch 各行业大文件。

`industry-3y-indices/sw_801xxx.json` / `industry-3y-concepts/thsc_xxxxxx.json`：按行业拆分的单文件，每个含该行业完整结构（与上方 indices 字段内单个对象同结构，便于 R2 单独 CDN 分发）。

单行业结构：

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | string | 行业名称 |
| `data` | array | OHLC `[{date, open, high, low, close, pct_change, amount}]` |
| `signals` | array | 买卖点信号 `[{date, index_id, signal, reason}]` |
| `stats` | object | `{buy, buy_aux, buy_backup, buy_special, sell, sell_stop_loss}` 各含 5d/10d/20d 回测 |
| `strategy` | object | `{buy, buy_aux, sell, _detail}` 策略配置 |
| `fund_flow` | array | 主力资金流 `[{date, value}]`（亿元） |
| `turnover` | array | 换手率 `[{date, value}]`（%） |
| `width` | array | 行业内宽度 `[{date, up_count, down_count, zt_count, dt_count, zb_count, seal_rate, amount}]` |
| `etfs` | array | 对应主流 ETF `[{code, name, amount}]` |

> 申万一级行业指数代码见 [`config/indicators.yaml`](../config/indicators.yaml)（`sw_801010` 农林牧渔 ~ `sw_801980` 美容护理，共 31 个）。同花顺概念板块 27 个（`thsc_300816` 机器人概念 等）。

---

## 7. etf_national_team-\*.json · 国家队 ETF 资金动向

5 个时间窗口 + holders（持有人）+ quarterly（季度机构占比）共 8 个文件。12 只宽基 ETF 的份额变动 + 信号。

> 口径声明：基于 ETF 每日份额变动 + 成交额放量 + 季度机构持仓占比校准的**代理推断**，非真实国家队席位数据。详见 [`app/collector/etf_national_team.py`](../app/collector/etf_national_team.py)。

`etf_national_team-{range}.json`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `updated_at` | string | ISO 时间戳 |
| `etfs` | array | 12 只 ETF 列表，结构见下 |

ETF 元素：

```json
{
  "code": "510050",
  "name": "50ETF华夏",
  "index": "上证50",
  "market": "sh",
  "daily": [
    {"date":"20250724","etf_name":"50ETF华夏","close":2.933,"amount":1576501117.0,"fund_share":58234266800.0,"share_change":173700000.0,"share_change_pct":0.299,"signals":["share_surge"],"fund_share_yi":582.34,"share_change_yi":1.74}
  ],
  "latest": {...}  // 末元素精简
}
```

`etf_national_team_holders.json`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `updated_at` | string | ISO 时间戳 |
| `source` | string | "cninfo 年报/半年报 PDF §9.2 期末上市基金前十名持有人" |
| `note` | string | 数据覆盖说明（沪市 7 只 cninfo 未收录 orgId 待补） |
| `etfs` | array | 12 只 ETF `{code, name, index, has_data, note}` 或含 holders 详情 |
| `events` | array | 国家队公开事件 `[{date, actor, action, note, source}]`（如汇金宣布增持） |

`etf_national_team_quarterly.json`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `updated_at` | string | ISO 时间戳 |
| `etfs` | array | 12 只 ETF `{code, name, index, history:[{report_date, inst_hold_pct, retail_hold_pct, internal_hold_pct, total_share}]}` |

12 只 ETF（code/name）：510050(50ETF华夏) / 510300(300ETF华泰柏瑞) / 510500(500ETF南方) / 512100(1000ETF南方) / 588000(科创50ETF华夏) / 588050(科创50ETF工银) / 159915(创业板ETF易方达) / 159919(300ETF嘉实) / 159922(500ETF嘉实) / 159952(创业板ETF广发) / 510310(300ETF易方达) / 510050 等。

---

## 8. futures.json · 期货机构持仓

中金所 IF/IC/IH/IM 前 20 会员持仓排名 + 机构/中信/国君三角色追踪。

| 字段 | 类型 | 说明 |
|---|---|---|
| `summary` | object | `{date, 品种:[...], roles:[机构(前20), 中信期货, 国泰君安]}` |
| `positions` | array | 每日净持仓 `[{date, 机构(前20):{中证500期货, 沪深300期货, 上证50期货, 中证1000期货, 综合}, 中信期货:{...}, 国泰君安:{...}}]`（手） |
| `positions_ratio` | array | 每日净持仓占比（持仓/总持仓），结构同上 |
| `accuracy` | object | `{角色: {30d/60d/120d: {follow, contrarian}}}` 同向/逆向准确率 |
| `accuracy_history` | array | 准确率时序 `[{date, 角色: {30d/60d/120d: {follow, contrarian}}}]` |
| `latest_bet` | object | 最新一期持仓方向 |

---

## 9. summary.json + summary_history.json · 收盘速递

`summary.json`：当日收盘速递（规则引擎 + 历史回看合成的一句话 + 短句）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `date` | string | YYYYMMDD |
| `generated_at` | string | "7月24日 收盘分析" |
| `summary` | string | 完整收盘速递文字 |
| `summary_short` | string | 短句 |
| `sentiment_label` | string | 情绪标签（如"情绪低迷"） |
| `sentiment_score` | number | A 股综合情绪分 |
| `fear_greed_value` | number | 恐贪指数 |
| `fear_greed_label` | string | 恐贪标签（如"恐惧"） |
| `is_freeze` | boolean | 是否触发冰点 |
| `freeze_info` | string | 冰点告警信息 |
| `volume_label` | string | 量能标签（如"温和缩量"） |
| `volume_amount` | number | 成交额（亿元） |
| `sh_pct` | number | 上证涨跌幅 |
| `sh_close` | number | 上证收盘点位 |
| `up_count`/`down_count` | number | 涨/跌家数 |
| `zt_count`/`dt_count` | number | 涨停/跌停数 |
| `buy_count`/`sell_count` | number | 买点/卖点触发数 |
| `nh_count`/`nl_count`/`nhnl` | number | 年度新高/新低/差 |
| `ma_bullish`/`ma_bearish` | number | 均线多头/空头排列家数 |
| `top_industries`/`bottom_industries` | array | 领涨/领跌板块 |

`summary_history.json`：历史收盘速递（分页）。

```json
{
  "items": [{"date","generated_at","summary","summary_short",...}],
  "total": 2555, "offset": 0, "limit": 90
}
```

---

## 10. signal_stats.json · 买卖点回测统计

113 个 index_id 的买卖点回测统计（5d/10d/20d forward 收益）。

```json
{
  "bj50": {
    "buy": {"5d": {"win_rate":0.6, "pl":4.12, "mean":5.18, "n":25}, "10d": {...}, "20d": {...}, "frequency": {"year_count":5, "monthly_avg":1.3, "total_count":26, "months":{"202308":1,...}}},
    "buy_aux": {...},
    "buy_backup": {...},
    "buy_special": {...},
    "sell": {...},
    "sell_stop_loss": {...}
  },
  "sh": {...},
  "sw_801010": {...},
  "thsc_300816": {...},
  "s.a_sentiment": {...},  // 情绪分序列
  "g.gold": {...}  // 全球 extras
}
```

字段含义：`win_rate`=胜率、`pl`=盈亏比、`mean`=平均收益、`n`=样本数、`frequency`=信号频率（按月分布）。样本不足自动标注（n<20 不参与策略决策）。

`index_id` 命名空间：
- A 股宽基：`sh/sz/hs300/sz50/csi500/csi1000/cyb/kc50/bj50/csi_div/div_lowvol/sz_div`
- 港股：`hsi/hstech/hscei/hk_cesg10/hk_hsmogi/...`
- 全球：`us_dji/us_ixic/us_spx/us_ndx/nikkei225/kospi/ftse100/dax/cac40/cgb_*`
- 申万行业：`sw_801010 ~ sw_801980`（31 个）
- 同花顺概念：`thsc_300816 ~ thsc_309128`（27 个）
- 情绪分序列：`s.a_sentiment/s.cross_market/s.fear_greed/s.sentiment_*`
- 全球 extras：`g.gold/g.oil/g.wti_oil/g.comex_silver/g.usdcnh/g.a_qvix_*/g.cn10y/g.us10y/g.cn_us_spread/g.brent`

---

## 11. index/{id}-all.json · 单指数全历史

44 个 index_id（与 signal_stats 相同命名空间，剔除情绪分序列和 extras），每只一个全历史 JSON。前端读后客户端切片 signals。

| 字段 | 类型 | 说明 |
|---|---|---|
| `ohlc` | array | OHLC `[{date, open, high, low, close, pct_change, amount}]`，全历史（最早 1990 起） |
| `signals` | array | 买卖点信号 `[{date, index_id, signal, reason}]` |
| `stats` | object | `{buy, buy_aux, buy_backup, buy_special, sell, sell_stop_loss}` 回测统计 |
| `strategy` | object | `{buy, buy_aux, sell, _detail}` 当前策略配置 |
| `etfs` | array | 关联主流 ETF `[{code, name, amount}]`（部分指数为空） |

文件清单见 [`static-site/data/index/`](../static-site/data/index/) 目录（93 个 = 44 个 JSON + 49 个 .gz）。

---

## 12. position/ma_alignment/ad_line/new_high_low/volume_ratio/rotation · 大盘宽度

辅助大盘宽度指标，均为轻量时序文件。

### 12.1 position.json · 大盘位置感

8 指数当前价格在历史区间的分位。

```json
{
  "positions": [
    {"index_id":"sh","name":"上证指数","current":3814.2,"current_date":"20260724","percentile_1y":14.8,"percentile_3y":71.6,"percentile_5y":83.0,"label":"低位","level":"low"}
  ]
}
```

`label`/`level`：`low`(低位) / `mid`(中位) / `high`(高位)。

### 12.2 ma_alignment.json · 均线排列

```json
{"data": [{"date":"20250715", " bullish_count":N, "bearish_count":M, ...}]}
```

每日全市场均线多头/空头排列统计。

### 12.3 ad_line.json · 腾落线

```json
{
  "data": [
    {"date":"20250715","up_count":1261.0,"down_count":3800.0,"ratio":0.249,"ad_line":-107603.0,"ad_line_ma5":-106543.4,"ad_line_ma20":-110187.3}
  ]
}
```

### 12.4 new_high_low.json · 新高新低

```json
{
  "data": [
    {"date":"20250715","nh_52w":0.0,"nl_52w":0.0,"nhnl_52w":0.0,"nh_20d":3.0,"nl_20d":0.0,"details":[]}
  ]
}
```

### 12.5 volume_ratio.json · 量能比

```json
{
  "data": [
    {"date":"20250715","amount":16098.55,"ma5":15538.2,"ma20":14120.71,"ratio":1.036,"signal":"正常","signal_code":0,"pct_change":-0.416}
  ]
}
```

`signal`：放量 / 缩量 / 正常；`signal_code`：1 / -1 / 0。

### 12.6 rotation.json · 板块轮动速度

```json
{
  "data": [
    {"date":"20250715","speed_5d":100.0,"speed_10d":100.0,"speed_20d":100.0,"speed_concept_5d":100.0,"speed_concept_10d":88.9,"speed_concept_20d":84.2}
  ],
  "latest": {"date":"20260724","sw":{...},"concept":{...}}
}
```

`speed_*` = 行业/概念轮动速度（0-100，越高轮动越快）。

---

## 13. alert.json + alert_analyze_{id}.json · 风险预警

### 13.1 alert.json · 大盘综合预警

```json
{
  "date": "20260724",
  "generated_at": "2026-07-24 18:24:34",
  "high": {"score":38.51, "level":"ok|warn|error", "triggered":false, "dims":[...], "reason":"..."},
  "low": {"score":77.43, "level":"warn", "triggered":true, "dims":[...], "reason":"❗low_alert冰点(77分)"},
  "history": []
}
```

### 13.2 alert_analyze_{index_id}.json · 单指数/标的预警分析

113 个 index_id 各一个文件。

```json
{
  "target_id": "hs300",
  "target_type": "index",
  "target_name": "沪深300",
  "alert": {"date":"20260724","target_id":"hs300","target_type":"index","high":{...},"low":{...},"high_level":"...","low_level":"...","dims":{...}},
  "reason": {"dim_hits":[...], "data_thresholds":{...}, "history_analogy":{...}, "human_text":"...", "compliance_footer":"...", "no_data_hint":null}
}
```

---

## 14. intraday_snapshot.json · 盘中实时快照

盘中 09:35–15:00 每 15 分钟更新一次，独立 push 到 main（不走 17:50 全量 deploy，避免覆盖实时版）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `collected_at` | string | ISO 时间戳 |
| `is_closed` | boolean | 是否已收盘 |
| `label` | string | "上一交易日收盘" 或 "盘中实时" |
| `prev_trading_day` | string | YYYYMMDD |
| `indices` | array | 12 指数实时 `{code, name, price, pre_close, change, pct_change, open, high, low, datetime, amount}` |
| `industries` | array | 31 行业实时 `{sw_code, sw_name, pct_change, net_inflow, amount, lead_stock}` |
| `concepts` | array | 27 概念实时 `{id, name, pct_change, close, open, high, low, amount}` |
| `us_futures` | object | `{hf_ES: {price, pct_change, ...}, hf_NQ: {...}}` 美股期货 ES/NQ（亚盘实时反映美股当晚预期方向） |

---

## 15. etf_score_list.json · ETF 评分榜单

全市场 A 股股票型 ETF 评分榜单（每日更新）。

```json
{
  "date": "20260723",
  "updated_at": "2026-07-24T18:44:48",
  "source": "全市场 A股股票型 ETF (1371 只) - 阶段2 扩采集 [ETF调权=off(待回测验证)]",
  "universe_count": 1371,
  "full_market": true,
  "etf_adjust": "off",
  "buy_top": [...], "sell_top": [...],
  "fetch_count": N, "skip_count": M,
  "buy_list": [{...}], "sell_list": [{...}]
}
```

---

## 16. lab/*.json · 策略实验室回测

`/lab` 页面的回测产物。每个文件含 `generated_at`/`desc`/`initial_capital`/`indexes`/`summary` 等字段。

| 文件 | 说明 |
|---|---|
| `lab/lab_backtest_{index_id}.json` | 单指数多策略回测（C1_RSI30/Donchian20/Donchian55/BB_lower_revert/BB_upper_break/Supertrend/MA_golden_5_20/MA_golden_10_60），含 `periods`(5)/`horizons`(4)/`strategies` |
| `lab_ablation.json` | 策略消融实验 |
| `lab_cost_compare.json` | 交易成本对比 |
| `lab_param_scan.json` | 参数扫描 |
| `lab_short_symmetry.json` | 多空对称性分析 |

---

## 17. trade_sim/*.json · 买卖点模拟交易

`{index_id}` 的买卖点模拟交易回测。

- `trade_sim_{index_id}_full.json`：完整路径
- `trade_sim_{index_id}_stats.json`：统计汇总

```json
{
  "generated_at": "2026-07-23 11:39",
  "index_id": "bj50",
  "index_name": "北证50",
  "initial_capital": 100000,
  "total_capital": 100000,
  "position_size": 10000,
  "windows": [...],
  "signal_first_date": "...",
  "signal_last_date": "...",
  "paths": [...],
  "scenarios": [...],
  "data": [...]
}
```

---

## 18. schedule_stats.json + signal_freq.json · 调度统计与信号频率

### 18.1 schedule_stats.json · launchd 任务执行统计

```json
[
  {"task":"update_all","name":"收盘全量","schedule":"17:50","est_text":"约31分钟","last_run":"2026-07-24 17:50","last_exit":0,"last_duration_sec":3283}
]
```

8 个任务：`update_all`(17:50) / `intraday_snapshot`(09:35起每15分) / `futures-backfill`(20:05,21:00) / `lhb-backfill`(18:30,19:30) / `rzhb-backfill`(19:15) / `etf-national-team`(20:07,21:30) / `backfill-evening`(16:35,02:00) / `lab-auto`(19:00)。

### 18.2 signal_freq.json · 信号频率统计

```json
{
  "buy": {"monthly_avg":N, "year_count":Y, "total_count":T, "active_months":{...}},
  "buy_aux": {...},
  "buy_special": {...},
  "buy_special_filtered": {...},
  "buy_backup": {...},
  "sell": {...},
  "sell_stop_loss": {...}
}
```

---

## 19. feed.xml · RSS 收盘速递

RSS 2.0 订阅源，供 RSS 阅读器订阅每日收盘速递。

```xml
<rss version="2.0">
  <channel>
    <title>A股情绪看板每日收盘</title>
    <link>https://ss.fx8.store/</link>
    <description>A股市场情绪、恐贪指数、涨跌家数、量能与板块轮动每日收盘速递</description>
    <item>...</item>
  </channel>
</rss>
```

---

## 数据时效说明

| 数据类型 | 时效 | 说明 |
|---|---|---|
| A 股盘中实时快照 | T 实时 | 09:35–15:00 每 15 分钟更新 `intraday_snapshot.json` |
| A 股宽度/资金/情绪分 | T+0 当日 | 17:50 收盘后约 31 分钟跑完 update_all，当日下午即可看到当日数据 |
| 港股指数 | T+0 | 收盘后 17:50 一起采 |
| 美股指数 | T+1 | 时差原因，美股开盘时北京已深夜，次日 17:50 才采到前一日数据 |
| 申万一级行业指数 | T+1 偶发 | 申万官方 trend API 偶尔 T+1 才发当日数据，未发则跳过下次补 |
| 北向资金季度净买额 | 季度 | 2024-08 港交所新规后改季度披露，CCASS 季度末+20 天后发布 |
| ETF 持有人结构 | 半年 | cninfo 年报/半年报 PDF，滞后 2-3 月 |
| 期货机构持仓 | T+0 | CFFEX 每日发布，17:50 一起采 |

---

## 相关文档

- [data-sources.md](data-sources.md) - 数据源说明（akshare/mootdx/baostock/HKEX/CCASS/东财/同花顺/新浪/腾讯等）
- [LICENSE-data.md](LICENSE-data.md) - 数据集 CC BY 4.0 授权
- [REQUIREMENTS.md](../REQUIREMENTS.md) - 需求 + 指标公式披露
- [../README.md](../README.md) - 项目总览
