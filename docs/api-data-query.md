# 统一数据查询 API（/api/data/*）

> 2026-08-17 上线 · B 级新功能 · 为 UUMit 平台上架售卖金融情绪数据查询服务做基础。

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

| category | 返回 |
|---|---|
| `sentiment` | `{date, fear_greed, a_sentiment, cross_market}` 三字段今日值 |
| `alert` | `{date, high, low}` 大盘预警今日值 |
| `signals` | `?target=<标的id>` 读 `alert_analyze_<target>.json`；缺 target 返回支持列表 |

### `GET /api/data/<category>/range?start=YYYYMMDD&end=YYYYMMDD` — 时间区间切片

- start/end 缺省给合理默认（缺 start = 最早，缺 end = 最新）
- 支持 `YYYY-MM-DD` 与 `YYYYMMDD` 两种格式
- `sentiment` 返回三字段在区间内的历史数组；`alert` 返回 `history` 数组切片
- `signals` 是单标的快照（alert/reason 非时间序列），不支持 range

### `GET /api/data/<category>/summary` — 跨类别聚合今日值

一个请求返回恐贪 + A股情绪 + 跨市场 + 大盘预警的今日值（`{sentiment: {...}, alert: {...}}`）。未来可扩两融/ETF。

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
- 配额可经 KV 覆盖：`api_quota:<hash>:minute` / `api_quota:<hash>:day`（`scripts/api_key_mgmt.py gen --quota-minute --quota-day` 可设默认）

超限返回 `429` + JSON 错误体。

## 计量（计费依据）

每次鉴权通过的请求，按每 5 分钟聚合写入 KV（键 `api_usage:<hash>:<yyyyMMddHH<5min桶>>`，值为 JSON 数组 `[{category, ts}]`，单桶截断 1000 条，TTL 90 天）。计量失败不阻断查询。

## 类别路由扩展

代码 `worker/dataQuery.js` 用 `CATEGORY_SOURCES` 路由表——**加类别 = 加一行**（声明源文件 R2 key + 字段）。二期两融/ETF 在此加行即可。

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

# summary
curl -s -H "Authorization: Bearer <key>" \
  https://ss.fx8.store/api/data/summary

# signals（按标的）
curl -s -H "Authorization: Bearer <key>" \
  "https://ss.fx8.store/api/data/signals/latest?target=159915"

# 未带 key -> 401
curl -s https://ss.fx8.store/api/data/sentiment/latest
```

## 复现

- 生成/吊销/列表 key：`python3 scripts/api_key_mgmt.py {gen|revoke|list|usage}`（需仓库根目录跑，wrangler 读 `wrangler.jsonc` 的 KV namespace id `7d373c3365314ec7a334ac47a73f1578`）
- 数据加工逻辑自验：`node /tmp/uqtest.mjs`（对 `static-site/data/` 源文件比对 latest/range/summary 输出与源文件逐位一致）
- 数据源文件：`static-site/data/sentiment-3m.json` / `alert.json` / `alert_analyze_*.json`（R2 key 同 `data/` 前缀，worker 复用 `dataRewriteHandler` 模式读取，R2 404 回退 ASSETS）
