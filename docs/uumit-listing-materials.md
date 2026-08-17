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

## 形态 3:金融衍生数据历史数据包(知识商店,已上线,2026-08-17 换封面重发)

- **创建入口**:Skill API(`upload/file` → `quick-upload` → `publish`)。**当前活跃商品 = `81ba653b-3ac5-4227-9b51-e6e9f4fb96fb`**,状态 **`published`(已上线可售)**,2026-08-17 用 v5 封面(深蓝+青,平台审核 0.85 通过)替换原 v2 橙色封面(橙色大图表曾盖标题)。
- **详情链接**:`https://m.uumit.com/digital-assets/my/81ba653b-3ac5-4227-9b51-e6e9f4fb96fb`
- 封面:v5 数据清单版(covers/2026/08/16/43589afa02424828.png,平台 vision 审核 0.85:标题相关/排版清晰/无遮挡)
- **名称**:金融衍生数据历史数据包
- **计费模型**:one_time(买断)
- **定价**:112 UT(划线 150 UT;2026-08-17 按建议价发布)
- **交付**:`data_packs/<日期>/financial-data-pack-<日期>.zip`(含 README + SHA256SUMS)
- ⚠️ 旧资产 `088b8cfc-...`(1000 UT,旧封面)与 81ba653b 同名,建议后续下架或留作对照,避免同名前两个商品

## 形态 4:金融数据在线速递 · 每日更新(链接知识商品,2026-08-17 创建待发布)

- **创建入口**:Skill API `POST /api/v1/digital-assets/register-link`(typeLink:外部链接+访问信息交付;链接创建后不可修改),asset_id=`05c503cd-3462-4b04-97e2-aa11003c2ded`,状态 **`pending`(内容审核中,审核过即 publish)**
- **详情链接**:`https://m.uumit.com/digital-assets/my/05c503cd-3462-4b04-97e2-aa11003c2ded`
- 封面:深蓝+青数据速递风(covers/2026/08/16/b4d61ced7f224f8c.png,平台审核 0.85 通过)
- **名称**:金融数据在线速递 · 每日更新
- **交付**:在线速递页 `https://ss.fx8.store/databrief`(static-site/databrief.html,2026-08-17 上线,commit 7538705fd)+ 访问密码 **FX8-2026**(页面 JS 校验,localStorage 记解锁)
  - 内容:每日 AI 大盘预测(方向/区间/置信度)+ 四维解读(风险/资金/情绪/技术)+ 11 类数据速览 + 风险点/亮点/关注列表;数据源 daily_brief.json/overview.json 每日自动刷新(no-store),买家刷新即见最新 → 持续更新卖点
- **计费模型**:one_time(买断,持续可看)
- **定价**:建议 168 UT(划线 268 UT),待发布时确认
- **联系邮箱**:`support@fx8.store`

---

## 形态 5:金融情绪数据查询 API(数据广场,已上线 online,2026-08-17)

- **创建入口**:Skill API `POST /api/v1/data-marketplace/apis` → `POST /apis/{id}/test`(平台自动化连通测试)→ `POST /apis/{id}/submit`(**数据广场审核是自动化的,提交即过**——4 步 schema/connectivity/response/pricing 全 PASS,与能力市场人工审核不同,这就是当初"审核中列表空"的原因:数据广场根本没上架过)
- **api_id**:`75543d7f-510c-4dcb-8c2b-220a0312a048`,状态 **`online`(可售)**
- **管理页**:`https://m.uumit.com/data-marketplace/provider?tab=apis`(数据接口页,总调用/成功率从此看)
- **名称**:金融情绪数据查询 API
- **类别**:finance;标签 金融/情绪/每日更新
- **上游**:`GET https://ss.fx8.store/api/data/sentiment/latest`(恐贪+A股情绪+跨市场;响应约 400B)
- **认证**:`api_key` 型,key_name=`X-API-Key`,key_value=FX8 数据广场专用 key(**本地 trade-data/.env 的 FX8_DM_API_KEY,明文只落本地不入 git;hash 93c90a2b...**),位置 header。平台代理转发时用它鉴权 ss.fx8.store(已实测平台 test 200 + 真实数据)
- **定价**:60 UT/次(划线 100 UT),免费额度 none(无参数接口免额意义不大,后续可加)
- **限流**:FX8 worker 侧 120 req/min / 5000 req/day(专用 key 配额)
- **说明**:数据广场一个接口一个上游 URL(无路径模板),本次先上情绪聚合(sentiment/latest 信息量最大的轻量快照)。**用户新想法(2026-08-17):买入信号/AI预测/ETF评分/卖出警示 4 个更高价值接口待分析后增量上架,每类一个接口**

## 操作注意(降低 3005/重审风险)

- **先测试再提交审核**:上架前用我方测试 key 全链路自测一次(已验:latest/range/summary/错误路径/限流全通过)。
- **一次上架到位**:三个形态一次提交,不在 24h 内反复发布/修改;关键字段改动会使已上线接口重新进入快速审核。
- **审核时长不定**:提交后 pending_review,通过前不可被自动发现/调用;官方明示不承诺固定时长,提交后耐心等,不反复改。
- **3005(发布技能 24h≤10 次)**:三形态合计 3 次发布,远低于限制;但避免同日反复重发。
