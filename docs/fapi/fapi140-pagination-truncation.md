# #140 调研:FAPI 涨停池固定分页静默截断(采集侧)

- 日期:2026-09-30
- 类型:采集侧 bug 调研(researcher,只读,未改业务代码)
- 任务:#140(采集侧固定分页截断)
- 结论一句话:**截断真实存在但从未触发过(fapi-fallback 从上线至今未被调用),属「潜伏高危」;同源病灶另发现 fetch_news.py 东财单页低危 1 处;历史数据零污染,修复不改变历史口径。**

---

## 1. 链路到底是什么(答问 1)

`app/collector/fapi_fallback.py` 是**东财涨停/跌停/炸板池 + 龙虎榜的空值异源兜底**(2026-09-02 P1 实施):

```
fetchers.py collect_snapshot 空值分支(fetchers.py:606-625)
  → fapi_fallback.try_fallback()(fapi_fallback.py:130-136)
    → GET https://fuyao.aicubes.cn/api/a-share/special-data/{limit-up|limit-down|limit-break}-pool
      params: date_ms=<ms>&page=1&size=200   ← 病灶(fapi_fallback.py:97-98)
    → 响应 data.item[](仅第 1 页)+ data.pagination.total/pages(存在但代码不读)
  → _zt_df() 转东财兼容 df → 复用 _apply_transform(count_rows/max/ratio_count)→ daily_metric
```

- 接口:**同花顺金融开放平台(FAPI,fuyao.aicubes.cn)special-data 三池端点,日频数据**(date_ms 指某交易日,每页单位=行,每行=1 只股票)。
- 触发条件:东财 index 对应 func(如 `stock_zt_pool_em`)返回空且 cross_check 也空时才走 FAPI;**东财活着时 FAPI 绝不触发**(fapi-p1 报告 §0)。
- 龙虎榜 `dragon-tiger-list`(fapi_fallback.py:116-117)**不分页**(board_type+date 一次全量,返回 stock_items 数组)——无分页病灶,不受本案影响。

## 2. 截断是否真实发生(答问 2)——两个独立证据,实锤

### 证据 A:服务端强制 size 上限 200(实测 2026-09-30,脚本 docs/fapi/scripts/probe_fapi140_pagination.py)

```
[up 20241008 size200] http=200 code=0 msg=success   total=711 pages=4 page=1 size=200 返回条数=200
[up 20241008 size500] http=200 code=1003 msg=Parameter value out of range: size must be between 1 and 200
[up 20241008 page2]   http=200 code=0 msg=success   total=711 pages=4 page=2 size=200 返回条数=200
[up 20240930 size200] http=200 code=0 msg=success   total=664 pages=4 page=1 size=200 返回条数=200
```

- size=500 直接被服务端拒(编码 1003),**不存在「一次传大 size 拿全」的绕法**;
- 服务端支持翻页(page=2 正常返回),**只是代码没翻**。

### 证据 B:pagination.total > 返回条数的真实历史日期(同样实测)

| 日期 | FAPI total | page=1 实际返回 | 静默丢失 |
|---|---|---|---|
| 20241008 | 711 | 200 | 511(71.9%) |
| 20240930 | 664 | 200 | 464(69.9%) |

### 连板高度(max_lianban)同样受影响(实测脚本 probe_fapi140_maxlianban.py)

```
20241008: page=1 max连板=6;page=2 max连板=13;全量 max=13 → 截断影响 max_lianban=True
```

只取第 1 页时 `a_width_max_lianban` 会返回 **6** 而真值是 **13**——不仅涨停数低估 71.9%,连板高度也直接判错。

### 结论

- **截断真实发生**:条件=「东财涨停/跌停/炸板池挂(返回空)且当日池子 >200 条」时,采集侧静默只记 200 条,不报错、无日志、无告警。
- **触发概率非零**:历史 7 天涨停 >=200(20240930=862、20241008=806、20240208=525、20240417=227、20240219=222、20190225=204、20241028=203,数据:本地 data/sentiment.db daily_metric a_width_zt_count)。
- FAPI total 与东财口径有差(FAPI 711 vs 东财 806,差 95,含北交所/ST 等口径差,见 fapi-p1 报告),但截断量级远大于口径差,不影响本结论。

## 3. 影响面:消费方清单(答问 3,逐个)

fapi-fallback 兜底写入 daily_metric 的 6 个指标:`a_width_zt_count` / `a_width_dt_count` / `a_width_zhaban_rate` / `a_width_max_lianban` / `lhb_count` / `lhb_inst_net`(lhb 两指标不分页,不受截断)。**截断只影响前三池 4 指标**(zt/dt/zhaban/lianban)。消费方:

| # | 消费方 | 位置 | 截断影响 |
|---|---|---|---|
| 1 | **a_sentiment 情绪分(score_daily)** | app/compute/sentiment.py:13-15(zt 权重 0.20,zhaban 0.15,lianban 0.15,**合计 50%**) | 涨停数 200 vs 实际 711 → 情绪分严重低估;影响恐贪指数/情绪分卡/前端信号 |
| 2 | **涨停潮通知** | scripts/export_notifications.py:286-310(count/avg/spike 判定)→ 前端 app.js:14565-14569 推送「涨停潮」 | count 数字错(200 vs 711),spike 判定可能误判 |
| 3 | **盘后速递文案** | app/compute/market_summary.py:333-341,549-593(zt_count/dt_count → summary) | 文案涨停X家数字错 |
| 4 | **AI 每日预测 context** | scripts/gen_daily_brief.py:1173,1264-1265,1947-1948 | 涨停数/龙虎榜进提示词,数字错 → 预测质量降 |
| 5 | **首页 KPI 卡 + sparkline** | app/queries.py:1641-1649(KPI_SPARK_METRIC_IDS)→ static-site/app.js:10753-10759,10886-10888,11805-11831 | 首页直显涨停数错 |
| 6 | **全信号表/行情卡展示** | app/queries.py:36-48 指标集 → 前端 | 同上 |

## 4. 历史数据是否被污染(答问 4)——零污染,双登记点验证

- 登记点 1:collect_log(10671 条,20260703~20260917)`message LIKE '%fapi%'` **零命中**;
- 登记点 2:daily_metric 6 指标 source 分布 = akshare(intraday/mootdx)**无 fapi-fallback**;
- 结论:**fapi-fallback 自 2026-09-02 上线至今从未被触发过**(东财从没断过档)→ 历史数据无截断指纹,无污染。

## 5. 同源病灶扫描(答问 5,重点产出)

全仓 grep `page/size/limit/per_page/分页` 类写法,逐个判定:

| 位置 | 写法 | 判定 |
|---|---|---|
| **app/collector/fapi_fallback.py:97-98** | page=1&size=200 单页 | **🔴 本案病灶(未翻页)** |
| scripts/fetch_news.py:175-199 | 东财 page_size=50 单页 | **🟡 低危同类病灶**(见下) |
| app/collector/etf_national_team.py:784 | page=1,`while page<=5` | ✅ 有翻页循环 |
| scripts/_etf_spot_fallback.py:76-104 | `while True` 翻页 + fail-closed 下限 | ✅ 无病灶(正面样板) |
| app/collector/direct.py:706 | for page in range(1,6) | ✅ 有翻页循环 |
| app/collector/direct.py:276 | page=1&num=30 新浪板块资金 | ✅ 目标取 30 日内最新,覆盖充分 |
| app/collector/multisource.py:174 | pageNum=1&ps=5000 国债收益率 | ✅ ps=5000 远超历史条数 |
| app/collector/multisource.py:288 | pageSize=1200 期货列表 | ✅ 全市场期货不足 1200 |
| scripts/feishu_missed_fetch.py:147-163 | 自动翻页(page_token) | ✅ 有翻页循环 |
| fapi_daily.py 全量 dump | 预签名 URL 全量下载 | ✅ 无分页 |

### 次级病灶:fetch_news.py 东财单页(低危)

- 实测(2026-09-30 15:20 前后):50 条只覆盖 **17 分钟**(15:03:26→15:20:05),全天密度远超 50 条;
- fetch_news 每 30 分钟 :01/:31 增量采集 + 当日归档 union(_merge_new_into_archive,fetch_news.py:465-467)——**漏掉的新闻只在「本次拿到的窗口」内,窗口之外(上轮终点→本轮 50 条起点)的条目永久丢失,union 只合并已拉到的、不重翻页**;
- 但属快讯精选(低精确度要求)+ 30 分钟重采有部分自愈,严重度远低于涨停池 count 口径 → 判定低危,修复可后续排期。

## 6. 修复方案(答问 6,只给方案不改代码)

### 方案 A(推荐,最小正确):按 pagination.pages 翻页循环

fapi_fallback.py `fetch_zt_fallback` 改为(伪码):

```
page = 1; items = []
while True:
    data = _api(path, {date_ms, page, size:200})
    if data is None: break/降级
    batch = data.get("item") or []
    items += batch
    pag = data.get("pagination") or {}
    if page >= (pag.get("pages") or 1): break   # 翻完
    if len(batch) < 200: break                   # 兜底:服务端没给 pages 时按 batch 大小判末页
    page += 1
```

外加**安全上限 + 超限告警**(防服务端异常翻页死循环,最多 10 页=2000 条,超限记 warn 日志)。

### 方案 B(备选):改造后用 count_rows 可直接读 pagination.total 做机检

`fetch_zt_fallback` 返回前加断言:`len(df) == pagination.total`,不等则 msg 带 `TRUNCATED total=X got=Y`(沿用现有 msg 链路可查可告警)。

### 修复会不会改变历史口径?

- **不会**(关键结论):历史 daily_metric 该 6 指标 source 全部是 akshare/intraday/mootdx(东财主源),fapi-fallback 从未写入过任何历史行;
- 修复只影响**未来**东财故障日的兜底数值(200→实际总数),且兜底数字按口径本与东财有差(实测涨停 80 vs 83 量级),修复后只是「不再 200 截断」,不重写历史任何一行;
- 唯一注意:未来某日若东财挂→FAPI 兜底入库,该日数字与前后东财数字口径差约 ±3%(20260901 实测 80 vs 83),需在监控/巡检时留意大跳变(spike_guard 已有,见 fetchers.py:636-640)。

## 7. 验收要点

1. 服务端 size 上限:`.venv/bin/python docs/fapi/scripts/probe_fapi140_pagination.py` → size=500 报 code=1003;
2. 翻页可取全:20241008 page1..4 总条数 = 711 = pagination.total;
3. 修复后:`fetch_zt_fallback("stock_zt_pool_em","20241008")` 返回 len=711 且 msg 无 TRUNCATED。
   (此修复属实现侧,待主控派 implementer;本调研只读未改业务代码)

## 复现段

- 调研本体:本文件
- 生成脚本(归档):docs/fapi/scripts/probe_fapi140_pagination.py(分页 clamp 验证)、docs/fapi/scripts/probe_fapi140_maxlianban.py(连板截断验证)
- 数据来源:生产 FAPI 接口(只读 GET,2026-09-30 三次调用,间隔数秒,无频率压力)+ 本地 data/sentiment.db(只读查询)
- 关键口径:limit-up-pool 单页上限 200 由服务端强制(code=1003);pagination.total 为当日全量;daily_metric.source 无 fapi=历史未被兜底覆盖
- 测试基准说明:本案不涉回测口径,无需对齐 test-baseline-v112-anchor(未触碰任何「AI 推荐/降亏过滤」数字)
