# UUMit 上架物料(2026-08-17 已上架)

> 三种售卖形态已通过 **Skill API 直接上架**(2026-08-17),无需网页端表单。状态:查询 API + 订阅 = `pending_review`(等平台审核),数据包 = `published`(已上线)。
> 定价依据:平台 `GET /api/v1/pricing/suggestion` 建议价(4615 个同类能力均价 7126 UT)。用户已确认按建议价上架。
> 上架原则:①先测试再提交审核(官方明确,查询 API 全链路已用测试 key 自测)②一次定稿不反复发布(24h≤10 次 + 关键字段改动会触发快速审核)③上架路径=Skill API(`POST /api/v1/capabilities` 创建草稿 → `submit-review`;数据包走 `upload/file` → `quick-upload` → `publish`)。

## 形态 1:金融数据查询 API(能力上架,已提交审核)

- **创建入口**:Skill API(`POST /api/v1/capabilities`),cap_id=`35403e99-f5f5-42da-9f46-026dfdd45e12`,状态 `pending_review`
- **能力详情**:`https://m.uumit.com/creator/capabilities`(能力上架管理页,可查审核状态)
- **名称**:金融情绪数据查询 API — 16 类衍生数据
- **类别**:finance(或 data)
- **描述**:
  > 金融衍生数据查询接口,覆盖 16 类自研加工数据,每日收盘后更新:
  > - 情绪类:恐贪指数 / A股综合情绪分 / 跨市场综合评分
  > - 预警类:大盘预警(过热/过冷维度分解)、8 类技术信号(按标的)
  > - 市场类:市场综合评分、板块轮动速度、均线排列(多头/空头/金叉死叉)、全市场量能、52周新高新低家数
  > - 资金类:期货机构多空持仓/多空比、国家队 ETF 持仓
  > - 评分类:公募基金评分、ETF 评分列表
  > 三种查询方式:`latest`(最新值快照,轻量)/ `range`(历史区间切片)/ `summary`(跨类别聚合)。API key 鉴权,带免费试用额度。
- **上游 URL**:`https://ss.fx8.store/api/data/`
  - 示例:`https://ss.fx8.store/api/data/sentiment/latest`(恐贪+A股情绪+跨市场今日值)
  - 示例:`https://ss.fx8.store/api/data/etf_score/latest?limit=20`(ETF评分 top)
  - 示例:`https://ss.fx8.store/api/data/rotation/range?start=20260801&end=20260814`(历史切片)
- **认证方式**:`Authorization: Bearer <api_key>`(API key 由我方发放)
- **请求参数/Schema**:
  - `GET /api/data/<category>/latest` — category ∈ sentiment/alert/signals/market/a_stock/rotation/position/ma_alignment/volume_ratio/new_high_low/futures/signal_freq/fund_score/etf_score/etf_national_team
  - `GET /api/data/<category>/range?start=YYYYMMDD&end=YYYYMMDD`
  - `GET /api/data/summary` — 跨类别聚合
- **测试参数**:`GET /api/data/sentiment/latest` 返回 `{"date":"20260814","fear_greed":{...},"a_sentiment":{...},"cross_market":{...}}`
- **单次价格**:6000 UT(data_api 档;区间 3000–10000)
- **免费额度**:建议「首次 N 次免费」(如 5–10 次),利于试用转化
- **限流**:60 次/分钟(worker 已实现,KV 计数)
- **联系邮箱**:`support@fx8.store`(技术支持)

## 形态 2:AI 每日金融速递订阅(能力上架,已提交审核)

- **创建入口**:Skill API(`POST /api/v1/capabilities`),cap_id=`4b3ac76f-e9eb-46c1-b382-72c669458a4a`,状态 `pending_review`
- **能力详情**:`https://m.uumit.com/creator/capabilities`(能力上架管理页,可查审核状态)
- **名称**:AI 每日金融速递订阅
- **类别**:finance / intelligence
- **描述**:
  > 每个交易日收盘后,自动推送 AI 生成的 A 股次日市场速递到订阅者邮箱/Webhook:含大盘涨跌方向预测与区间(如"向下 -0.8%~-0.3%")、市场情绪解读、板块观察。订阅期内每日定时送达,无需自行上站查看。非交易日不推送。
- **计费模型**:subscription(按月)
- **定价**:1500 UT/月(区间 500–5000)
- **交付**:daily_brief 内容(meta.date / meta.direction / meta.range / text)
- **联系邮箱**:`support@fx8.store`

## 形态 3:金融衍生数据历史数据包(知识商店,已上线)

- **创建入口**:Skill API(`upload/file` → `quick-upload` → `publish`),asset_id=`088b8cfc-f10c-4030-9ce3-0f45ac2e25fe`,状态 **`published`(已上线可售)**
- **详情链接**:`https://m.uumit.com/digital-assets/my/088b8cfc-f10c-4030-9ce3-0f45ac2e25fe`
- 封面:OSS 自动生成的数据可视化封面(covers/2026/08/16/fb97a8c26db64969.png)
- **名称**:金融衍生数据历史数据包
- **类别**:digital_asset
- **描述**:
  > 11 类自研金融衍生数据全史打包下载:恐贪指数、A股情绪分、跨市场评分、大盘预警、国家队 ETF 持仓、ETF 评分、信号频率、板块轮动、均线排列、量能、新高新低。含字段说明文档与数据口径,一次买断,定期出新版。
- **计费模型**:one_time(买断)
- **定价**:1000 UT(区间 500–2000)
- **交付**:`data_packs/<日期>/financial-data-pack-<日期>.zip`(含 README + SHA256SUMS)
- **联系邮箱**:`support@fx8.store`

---

## 操作注意(降低 3005/重审风险)

- **先测试再提交审核**:上架前用我方测试 key 全链路自测一次(已验:latest/range/summary/错误路径/限流全通过)。
- **一次上架到位**:三个形态一次提交,不在 24h 内反复发布/修改;关键字段改动会使已上线接口重新进入快速审核。
- **审核时长不定**:提交后 pending_review,通过前不可被自动发现/调用;官方明示不承诺固定时长,提交后耐心等,不反复改。
- **3005(发布技能 24h≤10 次)**:三形态合计 3 次发布,远低于限制;但避免同日反复重发。
