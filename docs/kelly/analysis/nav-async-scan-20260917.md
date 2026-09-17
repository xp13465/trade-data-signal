# 全站「同步 await 拉慢资源阻塞主链」扫描报告

日期: 2026-09-17 | 调研人: researcher | 关联: sigkelly 弱网卡死(sigkelly-webslow-y1-not-render-20260917.md)

## 0. 排查模式定义
前端 static-site/{app,lab,common}.js 中,`await fetchJSON(...)` / `await xxxEnsure(...)` 位于**用户交互响应链或首屏渲染主链**上的位置——拉不到就阻塞展示/收遮罩/出结果/卡交互,弱网被放大(强网无感、弱网卡几十秒~几分钟)。

## 1. fetchJSON 基础口径(app.js L9211-9354,判定所有风险的基准)
- **默认超时 15s**(L9262 `_timeoutMs = timeoutMs || 15000`),调用方可传 60000/120000 覆盖。
- **单轮无重试**;AbortController 到点 abort。
- 结果缓存 5min(L9196 `_CACHE_TTL`),时效敏感 URL(`_NO_CACHE_URLS` L9187)跳过缓存;in-flight 去重(L9181/L9230)。
- `.gz` 已弃用(tryGz=false,L9256),统一 .json + CF br 压缩。
- **`./data/` 前缀失败有三级兜底**(L9297-9346):主站 /data/ rewrite 独立 15s 超时 + 500ms 退避重试 2 次(~30s)→ 备站再加 R2 直链 1 次(~15s)。最坏 ~60s 才抛。
- **R2/外链直链(https:// 且非 ./data/)失败直接 throw,无兜底无重试**(L9348)——只受单次超时约束。
- lab.js L1744 `fetchJSONProgress`:带 onProgress+外部 signal+可选 timeout,超时 abort 并 throw;失败降级 fetchJSON(同额超时)。

## 2. 同类问题清单(风险等级:高=阻主链+大/慢资源;中=阻主链但资源中等/有 loading 态;低=后台预载/失败容错/已优化)

### 高风险
| 位置 | 资源 | 主链性质 | 超时/重试 | 风险 |
|---|---|---|---|---|
| app.js L4454 `await window._kkellyRealNavEnsure()` | accum_nav_map.json(R2, 19M 本地实证;common.js `_gihRealNavEnsure` 单例,双 URL 120s) | 首页「模拟回测」弹窗 G/H/I 模式重算主链,同步 await | 实现内 120s(common.js,implementer 改造中) | 高(与 sigkelly 同源第二消费点) |
| app.js L3579 `_fetchSimTrades` / L3678 `_loadSimKellyData` | recent 分片(≤3M)失败回退全量 signal_kelly_trades.json **75M(本地 ls 实证)** | 打开「模拟回测」弹窗一级加载主链(有 loading 文案) | 60s 双 URL 串联(主站 data→./data)最坏 ~120s/轮 | 高(全量回退路径 75M+120s) |
| app.js L25474 `_ensureHoldLoaded` | etf_score_list_hold.json(R2 直链,线上实测 10,290,856 字节≈10.3M) | 首页 ETF 评分点「持有」chip/按钮 → 列表才能出 | 60000ms,外链直链失败直接抛无兜底 | 高(点一次最坏挂 60s) |
| lab.js L6584 `_ensureLabHoldLoaded` | 同上 hold 10.3M | lab AI 评分页点「加载持有观察」按钮主链 | 60000ms | 高(与 L25474 同源兄弟点) |

### 中风险(主链 + R2 大 range/多文件 + 默认 15s;多数有 loading state 不会被"卡死"但弱网转圈久)
| 位置 | 资源 | 说明 |
|---|---|---|
| app.js L24514-24522 `_loadIndustryData` | range=all/5y/3y 时拉 `industry-{range}-concepts.json`(本地:all **31M** / 5y 15M / 3y 9.8M)+31 行业小文件 | renderIndustry 主链 await;默认 range=3m 不触发,用户切 range 才踩;concepts 未拆 |
| app.js L17119 renderNationalTeam | etf_national_team-all.json 7.8M | tab 主链,range=all 时 |
| app.js L19754 renderAStock | a-stock-all.json 7M | tab 主链,range=all 时 |
| app.js L20006 renderGlobal | global-all.json 5.2M | tab 主链,range=all 时 |
| app.js L19901 renderHK | hk-all.json 4.7M | tab 主链,range=all 时 |
| app.js L20078 renderGlobal 内部 | `Promise.all(9 × r2/index/{id}-all.json)` 并发 9 个 | 有「加载指数图表…」loading;每个 15s 单轮 |
| app.js L19848/19931 renderIndicesSection | 每指数 1 个 r2/index/{id}-all.json | A股/HK tab 指数折线粒 loading |
| app.js L10436/10450/10467 openSignalChartModal | global-extras-all 1.3M / sentiment-all 4.4M / index-all | 信号卡弹窗,弹窗已开+内部 async,数据到才画图;15s |
| app.js L10713/10755/10897 _loadKpiHistory | sentiment-{period}/a-stock-{period}(period=all→4.4M/7M)+index-all 叠加 | KPI 详情弹窗,period=all 时中 |
| app.js L15452 renderOverview 内部 | sentiment-all.json 4.4M R2 | 首屏主链,仅当日 ≥3 宽基冰点才触发的同步 await |
| lab.js L2723 renderLabDetail | r2/index/{state.labIndex}-all.json | lab 指数详情主链,15s |
| lab.js L3682 _labSignalModalRender | r2/index/{m.index}-all.json | lab 信号弹窗主链,15s |
| app.js L26174/26175 renderEtfScore | buy(线上 800K)+sell 双文件 Promise.all 60000ms | tab 主链有 loading;超长 60s 是保守给大文件 |
| lab.js L6496/6497 | 同上 lab 侧 buy/sell 60000ms | lab AI 评分页主链 |
| app.js L9435 fetchBoot / L15015-15078 renderOverview | boot.json 1.7M(本地);overview.json 1.2M | 首屏主链;overview 在 Promise.all 中且无 race 上限(signal_stats/intraday 有 1.5s race,overview 没有) |
| lab.js L1683/1851 fetchLabSimFullData | lab_sim_*_full.json(线上实测 6.5M)**带进度条+可 abort+60s** | lab 用户点详情;已有安全网,仅弱网转圈久 |
| app.js L20343 `_industryFundMapLoading` | public_fund_industry_fund_map.json 6.4M 60000ms | promise 懒加载,公共基金区内点击才 await;单例防重 |

### 低风险(已优化/后台/失败即降级)
- **已有 race 限时**:app.js L2595 `_ensureSigEtfCacheFromOverview`(race 1.5s)/ L15021 signal_stats(race 1.5s)/ L15036 intraday(race 1.5s)。
- **后台预载/非阻塞**:app.js L2891 `_sigTierMapLoading`、L2216/2226 overfit promise、L2239-2567 过拟合卡(`_appendOverfitCard` 不 await,fire-and-forget,注释明写"异步渲染,不阻塞 sigCard")、L3402 `_simLossFeatLoading`、L20231 appendHistoryPos(async IIFE 小文件)、L24141 `_preloadIndDetail`(IntersectionObserver 300px 预载,已有预热样板)、L5774/L6512/L6995 `_kkellyRealNavEnsure().then(...)` 非阻塞形态。
- **小文件本地 15s,失败有降级**:app.js L62(小)、L9651/L9692(alert_analyze 12K)、L7405 signal_stats 422K、L8807 market_tier_history 345K、L10831/10869 volume_ratio 46K、L14944 alert 2.9K、L16708-16784(boot 优先小文件 allSettled)、L17087 futures 693K、L14211 notifications、L13649 定时刷新、L11247 intraday(storage 兜底)。
- **lab 小文件有 state 缓存+失败置 null**:lab.js L1548-1727(lab_backtest 65K 等)、L5487-5507(ablation 17K 等)、L6328/6902/7055(alert_analyze)、L13502/14869(ETF pin 15s catch null)、L14014 `_atFetch`(15s catch null)。
- **已排除(implementer 正在改,不在本次范围)**:lab.js L8000-8860 重算链(L8043 `_kellyRealNavEnsure`、L8051/8052 双 URL 120s、L8777/8782/10437/10441/12739/12895 消费点)与 common.js L1240-1270 nav 链(L1246 `_gihRealNavEnsure`、L1319/1731 挂载点、L985 `_tdsS06StateEnsure`)。

## 3. 建议归类(哪些套 sigkelly 同一套修法)
sigkelly 修法三件:异步预热(去同步 await)/ 降超时 120s→15s / 失败兜底。

**可套用同一修法(列优先级):**
1. **app.js L4454**(高):与 sigkelly 真正同源的第二消费点(同一 common.js 单例)。common.js 实现修好后它自动受益;app.js 侧若想结构性解耦,参照同文件 L5774 已有的 `.then()` 非阻塞重渲染模式。
2. **app.js L3579 全量回退 75M**(高):recent 分片失败回退全量的兜底带 60s 双 URL;建议分片失败改为「重试 recent + 明确报错/降档」,而不是逼近 75M 长拉;或回退全量时把 60s 降至 15s 两档。
3. **hold 10.3M 双点(app.js L25474 + lab.js L6584)**:60s→建议 25-30s;或进入 ETF 评分 tab/评分区时先后台预取 hold(promise 挂起),点「持有」时大概率已就绪——这是最典型"异步预热"场景。
4. **tab range=all 大文件族**(renderAStock/HK/Global/NationalTeam/行业 concepts 31M):行业 31 拆分已做(历史优化),concepts 未拆是最大剩余大文件;rest 族属"切到才拉"且 15s 上限,优先级低于 1-3。
5. KPI/信号弹窗族:已有 per-curve 缓存+弹窗内 spinner,主要是弱网转圈 15s,非结构性卡死,可与 4 同批低优先。

## 4. 是否值得统一抽「资源预热」小工具:值得,但定位是"调用面收口"不是重造网络层
**判断:值得,收口 N 处重复 await 模式,约 50 行小工具,不动 fetchJSON 本体(§23.7 冻结)。**
理由(实证):
- fetchJSON 层已有 in-flight 去重+5min 缓存(基础能力现成);
- 重复模式已现 3 种且 N 处散落:
  a) `await Ensure()` 硬等主链(nav/hold/buy-sell/trades)—— 本次核心病灶;
  b) `Promise.race(fetch, 1500ms)` 写死 3 处(L2595/L15021/L15036) —— 时间常量各写各的;
  c) 点按钮才拉大 JSON 无预取(hold 10.3M 最典型)。
- 已有半成品样板可参考:_preloadIndDetail(L24141 IntersectionObserver 预载)、_appendOverfitCard(L2239 fire-and-forget)、L5774 .then 非阻塞。
- 建议形态:`preloadJSON(url, opts)` 返回单例 promise(复用 fetchJSON 的 inflight)+ `thenIdle(renderFn)` 完成后原地重渲染;加「预热注册表」按 tab 进入(而非按钮点击)提前挂 promise——把 sigkelly 修法沉淀为通用件,今后新增大 JSON 默认走预热模式。
- 不建议做重网络层(改 fetchJSON 超时策略/加全局队列):§23.7 冻结语义 + 各调用点超时差异是刻意的(15s 小文件 vs 60s 大文件)。

## 5. 附:实证数据源清单
- 本地 static-site/data: accum_nav_map.json 19M、signal_kelly_trades.json 75M、industry-all-concepts.json 31M、etf_national_team-all 7.8M、a-stock-all 7M、global-all 5.2M、hk-all 4.7M、sentiment-all 4.4M、boot.json 1.7M、overview.json 1.2M、global-extras-all 1.3M。
- 线上 curl --range 0-0 实测(R2):etf_score_list_hold.json 10,290,856B、etf_score_list_buy.json 799,958B、lab_sim_sh_full.json 6,520,581B、lab_backtest.json 65,487B、market_tier_history.json 345,927B、kelly_loss_features.json 1,121,943B。
- state.range 默认 "3m"(app.js L11),大 range 拉取仅在用户切换后踩。
- fetchJSON 基础口径:app.js L9181-9354(超时 L9262、兜底 L9297-9346、R2 直链直接抛 L9348)。
