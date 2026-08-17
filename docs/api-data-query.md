# 统一数据查询 API（/api/data/*）

> 2026-08-17 上线 · B 级新功能 · 为 UUMit 平台上架售卖金融情绪数据查询服务做基础。
> 2026-08-17 第二批：一次性加满 12 个新类别（market/a_stock/rotation/position/ma_alignment/volume_ratio/new_high_low/futures/signal_freq/fund_score/etf_score/etf_national_team）。

## 定位

这是**结构化查询服务**：数据本体仍公开（走原 `/data/` URL，全量文件公开可下），本 API 卖的是 **latest / range / summary 三种加工能力**——不拉全量文件、只取最新快照、按时间区间切片、跨类别聚合今日值。因此需要 API key 鉴权 + 限流 + 计量（付费面），与公开数据 URL 不冲突。

**数据一致性（§22/§23.6）**：本 API 只做「读源 JSON + 取最新 / 切片 / 聚合」，**不加工出源文件没有的数字**。返回的每个数字都能从 `static-site/data/` 源文件逐位对上（自验已比对）。

## 鉴权

请求头二选一：

- `Authorization: Bearer <key>`
- `X-API-Key: <key>`

未带 key 或 key 无效 → `401`。**不降级为公开访问**。

key 只在 KV 存 SHA-256 hash（键 `api_key:<hash>`），真实 key 由 `scripts/api_key_mgmt.py gen` 生成、**只打印一次**，丢失只能 revoke 重发。

## 端点

### `GET /api/data/<category>/latest` — 最新一天快照（轻量，几百字节）

| category | 数据文件 | 返回 |
|---|---|---|
| `sentiment` | sentiment-3m.json | `{date, fear_greed, a_sentiment, cross_market}` 三字段今日值 |
| `alert` | alert.json | `{date, high, low}` 大盘预警今日值 |
| `signals` | alert_analyze_<target>.json | `?target=<标的id>`；缺 target 返回支持列表 |
| `market` | overview.json | `{date, scores, signals_today}` 综合评分+信号灯+今日信号 |
| `a_stock` | a-stock-3m.json | `{metrics}` 宽度指标今日值（上涨家数/涨停等）——**只开放 metrics，绝不开放 indices 原始行情** |
| `rotation` | rotation.json | `{date, latest}` 板块轮动速度（speed_5d/10d/20d） |
| `position` | position.json | `{positions}` 各大指数点位+分位数（全部 8 个） |
| `ma_alignment` | ma_alignment.json | `{date, latest}` 多头/空头/金叉死叉家数 |
| `volume_ratio` | volume_ratio.json | `{date, latest}` 全市场量能（amount/ma5/ma20/ratio） |
| `new_high_low` | new_high_low.json | `{date, latest}` 52周/20日新高新低家数 |
| `futures` | futures.json | `{summary, latest_positions, latest_positions_ratio}` 机构多空持仓/多空比 |
| `signal_freq` | signal_freq.json | 买卖信号频率聚合（monthly_avg/year_count/total_count 全字段） |
| `fund_score` | fund_score_top.json | `{date, count, method, data}` 基金评分 top 列表 |
| `etf_score` | etf_score_list_{buy,sell,hold}.json（P0-2 拆分后新产物） | `{date, updated_at, limit, total, buy_list, sell_list, hold_list}` ETF 评分（**hold 17MB 走头部切片，?limit=N 防读全量，默认 20 最大 100**） |
| `etf_national_team` | etf_national_team-1y.json | `{updated_at, etfs}` 国家队 ETF 持仓 |
| `ai_prediction` | daily_brief.json + news_digest/<date>.json | `{date, meta, text, disclaimer, generated_at, news, news_note}` AI 每日预测 + 预测基准日对应新闻（**新闻取 daily_brief.meta.date 基准日当天，非请求当天**；该日无归档则附最近历史一份并 `news_note` 标注） |
| `etf_pick` | etf_score_list_{buy,sell,hold}.json | `?count=N`（默认 5 上限 10）`{date, updated_at, count, total, picks}` 挑不同档位 ETF（buy 优先/sell 次之/hold 补充 × high/mid/low 评分档位 + 汪汪队） |

> 合规红线：`a_stock` 只开放 `metrics` 宽度指标（上涨家数/涨停/炸板率/量能等自研加工值），**绝不开放 `indices` 原始行情字段**（open/high/low/close 等第三方行情不可转售）。本次**不新增** global/hk/industry 类别（原始第三方行情，不合规）。两融(margin)/ETF跟踪(etf_track)二期数据上线后再加（见下文「待确认类别」）。

### `GET /api/data/<category>/range?start=YYYYMMDD&end=YYYYMMDD` — 时间区间切片

- start/end 缺省给合理默认（缺 start = 最早，缺 end = 最新）
- 支持 `YYYY-MM-DD` 与 `YYYYMMDD` 两种格式
- `sentiment` 返回三字段在区间内的历史数组；`alert` 返回 `history` 数组切片
- `rotation`/`ma_alignment`/`volume_ratio`/`new_high_low` 返回 `data` 数组按日期切片
- `a_stock` 返回 `{metrics}` 各指标在区间内的 data 数组
- `futures` 返回 `{positions, positions_ratio}` 双数组切片
- 快照类（market/position/signal_freq/fund_score/etf_score/etf_national_team/ai_prediction/etf_pick）range 等价 latest（数据非时间序列，返回最新快照，不报错）
- `signals` 是单标的快照（alert/reason 非时间序列），不支持 range

### `GET /api/data/<category>/range?start=YYYYMMDD&end=YYYYMMDD` — 时间区间切片

- start/end 缺省给合理默认（缺 start = 最早，缺 end = 最新）
- 支持 `YYYY-MM-DD` 与 `YYYYMMDD` 两种格式
- `sentiment` 返回三字段在区间内的历史数组；`alert` 返回 `history` 数组切片
- `signals` 是单标的快照（alert/reason 非时间序列），不支持 range

### `GET /api/data/<category>/summary` — 跨类别聚合今日值（按组聚合设计）

**按组聚合设计（2026-08-17）**：summary 只聚合「轻量状态组」小文件（sentiment + alert + market + signal_freq），一次请求拿到今日市场全景概览（`{sentiment, alert, market, signal_freq, group:"lightweight_status"}`）。**不拉大文件**（etf_score 17MB / etf_national_team / fund_score / futures 等走各自 `latest` 单独查），避免 summary 每次调用都读全量大数据文件拖慢+费带宽。分组由 `group` 字段标识，未来新增轻量类别可扩进本组。

⚠️ 注意：summary 是「按组聚合」，不返回全部 18 类的今日值；查单类别详情请用 `/<category>/latest`。

## 错误格式

统一 `{error: {code, message}}`：

| status | code | 含义 |
|---|---|---|
| 400 | `bad_request` / `method_not_allowed` | 参数/方法错误 |
| 401 | `unauthorized` | 未带 key / key 无效 |
| 404 | `not_found` | 未知类别 / 标的无数据 |
| 429 | `rate_limit` | 分钟或每日超限 |
| 503 | `data_unavailable` | 数据源暂不可用 |

## 限流

按 key 计数（KV 无 CAS，get+increment，允许少量误差）：
- **分钟**：默认 60 req/min（键 `api_usage_lim:<hash>:m:<yyyyMMddHHmm>`，90s 残留容忍）
- **每日**：默认 5000 req/day（键 `api_usage_lim:<hash>:d:<yyyyMMdd>`）
- 桶键统一用**北京时间（UTC+8）**（Worker `new Date()` 是 UTC，未设 `time_zone`，直接用它会在 08:00 北京时重置"每日"桶，与中国市场日界不符，故 worker 内 +8h 取 UTC 分量）
- ⚠️ Workers KV 是**最终一致**：毫秒级并发突发下限流计数可能读到旧值而少计（get+increment 无 CAS 的原生限制），对持续/顺序请求的客户端限流准确；付费 API 若需严格限流需换 Durable Objects 计数（二期可选）
- 配额可经 KV 覆盖：`api_quota:<hash>:minute` / `api_quota:<hash>:day`（`scripts/api_key_mgmt.py gen --quota-minute --quota-day` 可设默认）

超限返回 `429` + JSON 错误体。

## 计量（计费依据）

每次鉴权通过的请求，按每 5 分钟聚合写入 KV（键 `api_usage:<hash>:<yyyyMMddHH<5min桶>>`，值为 JSON 数组 `[{category, ts}]`，单桶截断 1000 条，TTL 90 天）。计量失败不阻断查询。

## 类别路由扩展

代码 `worker/dataQuery.js` 用 `CATEGORY_SOURCES` 路由表——**加类别 = 加一行**（声明源文件 R2 key + `shape` 提取器）。当前 18 类 = sentiment/alert/signals + 12 个新类别（market/a_stock/rotation/position/ma_alignment/volume_ratio/new_high_low/futures/signal_freq/fund_score/etf_score/etf_national_team）+ 2 个上架类别（ai_prediction/etf_pick）。每种 `shape` 对应一个提取函数（array 通用日期切片 / a_stock / market / futures / position / etf_score 等），加类别优先复用既有 shape。**多文件/组合类（etf_score/etf_pick/ai_prediction）走 `handleCategory` 特殊分支**（读多文件/组合数据，不依赖单一 obj），不入 `handleShaped` map；hold 17MB 大文件用 `readJsonListHead`（R2/ASSETS Range 头部读取 + JSON 数组前缀截断）只读高评分前 N 条，防超时/烧内存。

## 待确认类别（数据未上线，二期）

1. **margin（两融）**：前端 `static-site/app.js` 有 `rzhb`/`a_fund_margin` 引用，但**无独立 JSON 数据源文件**——两融数据（`stock_margin_sse/szse`）由 `scripts/rzhb_backfill.sh` 采集写入 **DB**（sentiment.db 序列指标，T+1 08:00），前端 app.js 内嵌 `next_day` 判断消费，且为原始第三方行情（SSE/SSZE 官方）。本 API 是「读 static-site/data/ JSON 文件」架构，两融无持久化 JSON 文件、非自研加工独立产物 → **本次跳过**。二期若需卖两融：先在 export 落 JSON 文件并 R2 上线，再加 `margin` 类别。
2. **etf_track（ETF 跟踪）**：`data/etf_track_index.json` 只在本地 data/ 根、**git untracked（未上线）**，`static-site/data/` 无对应文件 → **数据未上线，本次跳过**。二期先跑上线链路（static-site/data/ + R2 + staticdata 同步）再加 `etf_track` 类别。

## 合规说明

- **绝不暴露原始行情字段**：`a_stock` 只开放 `metrics` 宽度指标（上涨家数/涨停/炸板率/量能/换手/北向/两融余额等自研加工值），`indices` 的 open/high/low/close 等第三方原始行情**全部不开放**。
- **不新增 global/hk/industry 类别**（原始第三方行情，不合规转售）。
- 数据一致性（§22/§23.6）：本 API 只读源 JSON + 取最新/切片/聚合，不加工出源文件没有的数字，返回每个数字都能从 `static-site/data/` 源文件逐位对上（自验已比对，见复现）。

## 示例 curl

```bash
# 生成 key（只打印一次）
python3 scripts/api_key_mgmt.py gen

# latest
curl -s -H "Authorization: Bearer <key>" \
  https://ss.fx8.store/api/data/sentiment/latest

# range（20260801-20260810）
curl -s -H "Authorization: Bearer <key>" \
  "https://ss.fx8.store/api/data/sentiment/range?start=20260801&end=20260810"

# summary（按组聚合：sentiment+alert+market+signal_freq）
curl -s -H "Authorization: Bearer <key>" \
  https://ss.fx8.store/api/data/summary

# 新类别示例
curl -s -H "Authorization: Bearer <key>" \
  https://ss.fx8.store/api/data/market/latest
curl -s -H "Authorization: Bearer <key>" \
  https://ss.fx8.store/api/data/a_stock/latest
curl -s -H "Authorization: Bearer <key>" \
  "https://ss.fx8.store/api/data/rotation/range?start=20260801&end=20260814"
curl -s -H "Authorization: Bearer <key>" \
  "https://ss.fx8.store/api/data/etf_score/latest?limit=20"

# signals（按标的）
curl -s -H "Authorization: Bearer <key>" \
  "https://ss.fx8.store/api/data/signals/latest?target=159915"

# 未带 key -> 401
curl -s https://ss.fx8.store/api/data/sentiment/latest
```

## 复现

- 生成/吊销/列表 key：`python3 scripts/api_key_mgmt.py {gen|revoke|list|usage}`（需仓库根目录跑，wrangler 读 `wrangler.jsonc` 的 KV namespace id `7d373c3365314ec7a334ac47a73f1578`）
- 数据加工逻辑自验：`node /tmp/uqtest.mjs`（对 `static-site/data/` 源文件比对 latest/range/summary 输出与源文件逐位一致，覆盖全部 18 类 + 合规断言）
- 数据源文件：`static-site/data/sentiment-3m.json` / `alert.json` / `alert_analyze_*.json` / `overview.json` / `a-stock-3m.json` / `rotation.json` / `position.json` / `ma_alignment.json` / `volume_ratio.json` / `new_high_low.json` / `futures.json` / `signal_freq.json` / `fund_score_top.json` / `etf_score_list_{buy,sell,hold}.json` / `etf_national_team-1y.json` / `daily_brief.json` / `news_digest/*.json`（R2 key 同 `data/` 前缀，worker 复用 `dataRewriteHandler` 模式读取，R2 404 回退 ASSETS；hold 17MB 用 Range 头部切片读取）
- 合规自验：a_stock 提取只含 `metrics` 不含 `indices`（`node /tmp/uqtest.mjs` 含断言）

---

# AI 每日速递订阅服务（/api/subscribe/*）

> 2026-08-17 上线 · B 级新功能 · 为 UUMit 平台「AI 每日速递订阅推送服务」做订阅者管理端点。
> 每日 `daily_brief.json` 一生成（20:40），本地 `scripts/brief_push.py` 拉取 active 订阅者并推送（email/webhook + 飞书报告群）。

## 鉴权（两级）

- **管理员端点**（register/recipients）：`Authorization: Bearer <admin_key>` 或 `X-API-Key: <admin_key>`，
  复用 `scripts/api_key_mgmt.py gen` 生成的 api_key（KV `api_key:<hash>` 同一 key 池）。
- **订阅者端点**（status/unregister）：`?key=<sub_key>` 或 `X-Sub-Key` 头，比对 KV `sub:<key>` 是否存在。
- 错误统一 `{error:{code,message}}`。

## 端点

### `POST /api/subscribe/register` — 注册订阅（管理员鉴权）

body `{email 或 webhook_url}` → 生成 `sub_` 前缀 key + 写 KV（`sub:<key>` = `{email|webhook_url, created_at, status:"active"}`）。
返回 key（**只打印一次**，务必立即保存）。

```bash
# email 订阅者
curl -s -X POST -H "Authorization: Bearer <admin_key>" -H "Content-Type: application/json" \
  -d '{"email":"user@example.com"}' https://ss.fx8.store/api/subscribe/register

# webhook 订阅者
curl -s -X POST -H "Authorization: Bearer <admin_key>" -H "Content-Type: application/json" \
  -d '{"webhook_url":"https://example.com/hook"}' https://ss.fx8.store/api/subscribe/register
```

### `GET /api/subscribe/status?key=<sub_key>` — 查订阅状态（订阅者自鉴权）

返回 `{key, status: active|revoked, type, created_at}`。

### `POST /api/subscribe/unregister` — 退订（订阅者自鉴权）

`X-Sub-Key: <sub_key>` 或 body `{key}` → 置 `status:"revoked"`。

### `GET /api/subscribe/recipients` — 管理员鉴权，返回所有 active 订阅者

供本地 `scripts/brief_push.py` 拉取推送。

```bash
curl -s -H "Authorization: Bearer <admin_key>" https://ss.fx8.store/api/subscribe/recipients
```

## KV 键空间（SUBSCRIBE_KV）

- `sub:<key>` = 订阅记录 JSON（active/revoked）
- `api_key:<hash>` = 管理员 key（复用 api_key_mgmt）

## 推送链路（本地）

`scripts/brief_push_wrapper.sh` → `scripts/brief_push.py`：
- 读 `static-site/data/daily_brief.json` + 拉 recipients。
- email 订阅者：复用 `config/email.json` SMTP（smtp.163.com:465）；webhook 订阅者：POST 订阅者 URL。
- 飞书报告群：`notify.send_feishu`。
- 失败重试 1 次 + 按 date 防重复 + 非交易日跳过（复用 `app/calendar.py is_trading_day`）。
- 计费 hook：本期不做自动扣费，`brief_push.py` 留 `BILLING_HOOK` 注释，上架后接 UUMit 平台计费回调。

## 支持与反馈

- **API 问题 / 报错反馈**：[support@fx8.store](mailto:support@fx8.store)（技术支持邮箱，请在反馈中附上调用 URL、时间与返回的错误信息，便于定位）。
