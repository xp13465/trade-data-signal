# 分时数据供给路径调研与选型(2026-10-02,researcher 只读产出,未 commit)

关联遗留:#148(浏览器直连东财全失败 ERR_EMPTY_RESPONSE + console 噪音)、#142(腾讯 day/query 备用腿,已合 main)、#143(云机 relay 卡在用户侧配置)。

## 结论速览
1. **现状真相**:东财分时 = 服务端接口级拒绝(任意 IP 全 000),腾讯 = 本机实测 200 全通,新浪 = 200 可取但无 ACAO 头。前端"图出不来"已由腾讯兜底解决(零用户可见影响),**剩余用户可见问题 = console 噪音**。
2. **用户候选方案(relay 逻辑搬进现有 Worker /quote/intraday)= 可行,且是推荐主方案**,满足"用户零操作"。但有 3 个风险点:CF 边缘出网可能被上游风控(需最小验证)/ 免费版 CPU 10ms 偏紧 / Worker 无全局状态(熔断限速需降级为 Cache API 近似)。
3. **缓存选型 = Cache API**(非 KV):KV 最小 TTL 30s(实现不了 4s)+ Free 版写 1000/天不够 12 码轮询。
4. **minute_series 不能替代实时分时**(10min 粒度 vs 1min),但可作降级画图第 2 层。
5. **推荐实施顺序**:Step1 前端熔断跨轮记忆(噪音根治,今天可做,不依赖外部源)→ Step2 最小验证 CF 边缘出网 → Step3 若通过,relay 搬 Worker。

---

## 1. 现状摸清

### 1a. CF Worker 现状
- 路由(worker/headers.js:302-359 fetch 分发):`/r2/*`、`/api/purge-cache`、`/api/data/*`、`/api/fund_score`、`/api/subscribe/*`、`/api/*`、`/data/*.json`、`/feed.xml`、其余走 ASSETS。
- 绑定(wrangler.jsonc:19-41):SUBSCRIBE_KV(KV)、R2_BUCKET(R2)、FUND_SCORE_DB(D1)。**无 Cache API 显式绑定**(caches.default 即 Cache API,headers.js:146/230 已在用)。
- 部署机制:.github/workflows/deploy-cf.yml push main + 路径过滤(static-site/worker/wrangler.jsonc/app)→ `npx wrangler deploy`。改 worker/** 即触发自动部署(注意:是 GitHub Actions,不是 CF Builds;另有 CF Workers Git integration 兜底)。**用户说"push main 自动 wrangler deploy"属实,路径是 GH Actions。**
- 出网先例:worker/auth.js:559(api.github.com/user)、:540(github access_token)、:416(gitee token)、:890(api.resend.com/emails)—— **生产 Worker 已在出网第三方 API 且长期工作**。但这些是 API 形态服务;行情接口是浏览器形态、对数据中心 IP 风控更严。

### 1b. relay/rt_relay.py 逻辑(relay/rt_relay.py)
- 源顺序:SOURCE_ORDER = ["em","qq_min","sina","qq_day"](L113),首个成功即停。
- 每源多 host 轮流(_em_urls L93-99 5 host / _qq_urls L101-105 3 host / _sina_urls L107-111 单 host)。
- 熔断(Breaker L187-252):确定性拒绝连续 3 次→open 60s;抖动 6 次→open 45s;half-open 探测。
- 限速(RATE_LIMITS L117-123):em(40,10)/qq_min(30,8)/qq_day(20,6)/sina(40,10)/sina_day(10,4),全局 120/min(GLOBAL_LIMIT L124),并发上限 6。
- 缓存:MiniCache 4s(L46 CACHE_TTL,L584)+ stale 兜底;新浪昨收 6h 缓存(PRE_CLOSE_TTL L47)。
- in-flight 去重:InflightTable(L621),同 code 并发只放一个 owner。
- schema:{name,price,preClose,pct,date,source,points:[{time,price,volume,amount}]}(L650-653)。
- 异常:全源失败返回 503 + upstreams 尝试记录;有 stale 时返 200+stale 标记。
- 新浪解析器(fetch_sina L518):只 A 股(INDEX_SINA 无港股 L84-88);preClose 用独立 sina_day 源补(L646)。

### 1c. 前端现状(static-site/app.js)
- 三腿:东财 fetchTencentMinute(L12830,函数名历史遗留实际走东财)、腾讯 fetchQQMinute(L12960)、relay fetchRelayMinute(L13029)。
- relay 开关:RT_RELAY_BASE_URL="https://rt.fx8.store" + RT_RELAY_ENABLED=false(L12786-12787),_rtSetRelay 测试切换(L12791)。
- 调用链:_renderIntradayChart(L13677)→ _fetchIntradayRenderSource(L13663 东财→腾讯→relay)→ 全失败 _renderSnapMinuteSeries(快照 minute_series)→ _renderIntradayFail。
- 批量链:_fetchDynamicPcts(badge/chips)同样东财→腾讯→relay(L4)。
- console 噪音触发点:app.js:12892 东财全 host 失败 warn、13016 腾讯失败 warn、12957 day/query warn、13146 同花顺 warn、14029 连续失败降频 warn。**噪音来源 = 东财腿失败 warning 每轮每码刷**(#148 上下文:Playwright 拦到 ERR_EMPTY_RESPONSE 45 条;CSP 消噪哨兵 0 违规证明非 CSP 漏项)。
- CSP:worker/headers.js:31 与 static-site/_headers:17 两份 connect-src 逐字一致,均已含东财/腾讯 host(§22 两处同步,2026-09-30 #133 已修)。

### 1d. 后端分时快照 minute_series(核实结果)
- 定义:app/collector/intraday_snapshot.py:2314 `indices[].minute_series = [{time:"HH:MM", price}...]` **只有 time/price 两字段,无 volume/amount**。
- 注入时机:盘中每 10 分钟一轮 + 盘后(L2442-2444 注释,2026-09-30 #142 改盘中+盘后都注入),预算 60s(_MS_BUDGET_SEC L2336)。
- 覆盖:12 指数(9 A 股 + 3 港股,_SNAP_CODE_TO_SECID L2319)。
- 数据源:腾讯 day/query 首选(L2393,12/12 稳定)+ 东财 trends2 后备。
- 产物:static-site/data/intraday_snapshot.json(本地 09-11 盘后快照实测:17 indices,12 个带 minute_series,241-242 点,124KB)。
- **复用评估**:
  - 前端 _renderSnapMinuteSeries 已能画它(降级画图)。但它定位是"实时源全挂时画当日/昨日曲线"。
  - **不能替代实时分时**:10min 注入粒度 vs 前端 1min 轮询(实时性差);且盘中若实时源全挂,minute_series 也只是 10min 前到当前分钟的快照。
  - 若把注入频率提到 1min,采集侧 12 码请求量 ×6(10min→1min),与采集预算/生产 IP 风控面冲突(§14 生产 IP 保护)。
  - **结论:minute_series 保留作降级第 2 层;不作为实时供给主路径。**

## 2. ★ 关键技术风险:CF Worker 出网到第三方行情是否被风控

### 2a. 本地实测(2026-10-02,只读低频,1 req/源)
| 源 | 本机 curl 结果 |
|---|---|
| push2delay.eastmoney.com trends2 | **HTTP 000 空响应**(size=0),复现 #148 ERR_EMPTY_RESPONSE |
| push2.eastmoney.com / 2.push2.eastmoney.com | HTTP 000 空响应 |
| web.ifzq.gtimg.cn day/query | **HTTP 200,code=0,242 点** |
| web.ifzq.gtimg.cn minute/query | HTTP 200,code=0,242 点 |
| proxy.finance.qq.com/ifzq day | HTTP 200 |
| quotes.sina.cn KLine | HTTP 200,5 bars;Content-Type 谎报 gbk,**body 实际 UTF-8**;**无 ACAO 头**(浏览器被 CORS 拦) |

### 2b. 社区先例(§5.1 外部系统先查社区,WebSearch 今日空转改用 GitHub API 搜到)
- **ai-quant-stock-picker#144(2026-09-18)**:腾讯 `minute/query` 被 WAF 返 501(waf.tencent.com/501page.html),但**同域 kline 路径 200 正常** ⇒ **不是 IP 级封禁,是该路径被 WAF 拦**;新浪 `hq.sinajs.cn` 403。与本项目 2026-08-05 遇腾讯 501 同源。
- **FinAgent#4**:东财 push2/push2his 因 **IP 级风控**频繁不可用(RemoteDisconnected、空响应),社区换 cninfo/同花顺做 fallback 链。
- 关键推论:**东财 = IP/接口级风控(CF 边缘大概率也被拒);腾讯 = 路径级 WAF(动态,时好时坏);新浪 = 服务端 200 可取但浏览器被 CORS 拦**。

### 2c. 最小验证方案(设计,不执行)
不碰生产 Worker 的两条路:
1. `wrangler dev --remote`(远程预览,走真实 CF 边缘出网,不部署) —— 最安全,需本机登录 CF。
2. 独立 worker(名字如 `relay-probe-tmp`)`wrangler deploy --name relay-probe-tmp`,只绑 workers.dev 子域、不挂自定义域、不写 routes(不占生产 worker)。测完 `wrangler delete`。
- probe 代码:GET `/probe?src=em|qq|sina`,对对应源发 1 个请求,返回 HTTP 状态码 + 字节数 + 是否解析成功。
- **判定标准**:em→HTTP 200+rc=0+trends 数组 / qq→200+code=0 / sina→200+JSON list 即为"该源在 CF 边缘可用";出现 000/501/403 = 该源 CF 边缘不可用,对应风险落地。
- 每源打 5 次观察波动(腾讯 WAF 是动态的,时好时坏)。

### 2d. 出网风险结论(诚实标注)
- **东财**:CF 边缘大概率不可用(本机/云上全 000 + 社区定性 IP 级风控)。但 relay 逻辑里 em 是首个源,**失败会自动落 qq**,不影响整体——只是 em 腿在 Worker 里大概率永远失败(浪费一次请求/CPU)。
- **腾讯**:2026-08-05 被 WAF 501 → 2026-09-30 前后恢复(本机实测 200)。CF 边缘是否 200 **未知,需最小验证**。腾讯 WAF 动态变化是最不确定项。
- **新浪**:CF 边缘可能 200(服务端形态)或 403(社区 09-18 遇过)。需最小验证。
- **结论**:CF Worker 出网 relay 的价值前提 = **腾讯在 CF 边缘可用或新浪可用**。若两者都不可用,relay 只剩 503(此时现有腾讯直连 200 时 relay 本就不被调用,无损失)。

## 3. 缓存选型:Cache API vs KV(推荐 Cache API)
| 维度 | Cache API(caches.default) | KV |
|---|---|---|
| 4s TTL 实现 | Cache-Control: max-age=4 可精确实现 | **最小 cacheTtl=30s(官方 limits 表),4s 无法实现** |
| Free 版额度 | 无写入计数限制(用 zone CDN 缓存配额 512MB);写不额外计费 | 读 100k/天、**写不同 key 1k/天、写同 key 1/s**;12 码轮询日写入 ≈2880 > 1000,免费不够 |
| 一致性 | 各数据中心独立缓存(不强一致,但 4s 场景无感) | 最终一致(收敛较快) |
| 延迟 | 边缘本地,极快 | 需跨数据中心读(略慢) |
| 本 Worker 已有使用 | headers.js:146/230 已在用 caches.default | 已有 SUBSCRIBE_KV,但语义是订阅持久化非短 TTL |
| 缓存 key 细节 | **必须剥离 `_=Date.now()` cache-buster**(前端 fetchRelayMinute:13041 带该参数),否则永远 miss —— 同 dataRewriteHandler L144 做法 | 同 |

**推荐:Cache API**。理由:4s TTL 只有它做得到、免费额度无写入压力、Worker 已有成熟用法(剥离 query 的 cacheKey 模式现成)。
- 手动管理方案(推荐):cacheKey = new Request(url.origin + "/quote/intraday?code=" + code),响应带 `Cache-Control: public, max-age=4`,miss 时回源+`ctx.waitUntil(put)`。
- 备选:完全不用 TTL,靠前端 1min 轮询天然削峰(但多用户同时命中会重复回源;保留 4s 缓存仍值得)。

## 4. Worker 约束核对(官方 limits 页 /workers/platform/limits + /workers/platform/pricing,2026-10-02 抓取)
| 项 | Free | Standard($5/月) |
|---|---|---|
| 每日请求 | **100,000/天** | 无限制 |
| CPU/请求 | **10ms(硬限,超了 Error 1102)** | 默认 30s,最高 5min |
| 子请求 | 50/请求 | 10,000/请求 |
| 同请求并发出站连接 | 6 | 6 |
| 内存 | 128MB | 128MB |
| 计费 | 免费 | 10M 请求+30M CPU-ms 含,超量 +$0.30/M 请求 +$0.02/M CPU-ms |

- **CPU 10ms 评估**:fetch 等待不占 CPU(官方:CPU time 只算代码执行,网络等待不算)。relay 每请求 CPU 构成:JSON.parse(腾讯 11KB~0.5ms / 东财 50KB~1-2ms / 新浪 749B)+ 循环构造 points(242 点)+ Headers/URL 操作。最坏全源 parse ≈ 4ms,加杂项可能逼近 10ms。**缓解:HTTP 非 200 / 0 字节不 parse(东财 000 直接短路,0 CPU);实测超限再升级 Standard。**
- **免费 100k/天评估**:当前 Worker 已服务全站 /data/ 请求。relay 增量:12 码 × 240 次/交易日 ≈ 2,880 次/天(1min 轮询),有 4s 缓存削峰后回源更少。预算内。
- **子请求 50/req 评估**:relay 单请求最多 4 源串行,≤4 个 fetch,远低于 50。
- **并发出站连接 6/req**:串行 fetch 同时只有 1 个连接,无压力。
- ⚠️ **R2 Class A 计费踩坑类比**:本项目 Worker 免费额度(100k/天)是硬顶,超了返 Error 1027(页面提示 fail-open/fail-closed)。relay 量级小,但**上线前建议在 CF 控制台确认当前 Worker 的每日请求用量余量**(researcher 无 dashboard 权限,待主控/用户核实)。

## 5. Python→JS 迁移差异清单(rt_relay.py → Worker)
1. **异步模型**:Python ThreadingHTTPServer+阻塞 urllib → JS 单线程 await fetch。同 code 并发去重:前端 _inflightMinute(Map+Promise)是现成模式;Worker 每请求独立,无跨请求并发,天然不需 InflightTable。
2. **超时**:urlopen(timeout=8) → AbortController + setTimeout(前端 INTRADAY_FETCH_TIMEOUT_MS=8000 现成)。
3. **多 host 串行**:Python _host_loop(带主机冷却) → JS for + await;主机冷却跨请求不可靠(无全局态),简化为"单请求内每源多 host 串行,全败换源"。
4. **编码**:新浪 Content-Type 谎报 gbk、body 实际 UTF-8(实测) → JS resp.json() 按 UTF-8 解析可过;若未来真 GBK 需 TextDecoder('gbk')(Worker 支持全编码)。东财 0 字节 → fetch 抛 TypeError/空 body,短路不 parse。
5. **JSON 严格度**:Python json.loads 容忍宽;JS resp.json() 严格。解析失败 catch → 当作该 host 失败换源。
6. **全局状态(最大差异)**:Python 的 Breaker/TokenBucket/MiniCache 是进程内全局+线程锁;Worker 每请求可能不同 isolate,**全局状态不跨请求**。
   - 熔断:用 Cache API 存 `{src, until_ts}`(键 `breaker:<src>`)近似全局;或只做"单请求内连续确定性拒绝短路"(前端 _EM_TRIP_THRESHOLD 思路)。推荐后者+Cache 近似组合。
   - 令牌桶限速:Worker 分布式不可靠 → **放弃全局限速**,靠 ①前端 1min 轮询节奏(12 码/分,量小)②上游天然风控边界 ③4s 缓存削峰。若必须硬限,用 Cache API 计数(evict 后自动放宽,可接受)。
   - 4s 缓存:Cache API(cacheKey 剥 query)。
7. **新浪昨收补丁(sina_day)**:Python 额外请求 scale=240 日线补 preClose → **Worker 端省略**,返回 preClose:null,前端从 snap 补(_renderIntradayChart:13708 `const pc = preClose || result.preClose` 现成)。省 1 子请求 + 复杂度。
8. **pct**:Python L652-653 → JS 同公式;preClose null 时 pct=null。
9. **in-flight/并发上限**:Python 全局并发 6 → Worker 串行 fetch 单连接,天然 ≤1。
10. **cache-buster 剥离**:前端 fetchRelayMinute:13041 带 `&_=Date.now()`,Worker 路由内剥离后做 Cache API key(同 dataRewriteHandler:144 先例)。**漏做 = 4s 缓存永远 miss。**

## 6. 全局方案对比
| 方案 | 用户介入成本 | 技术风险 | 数据实时性 | 维护成本 | 根治噪音 | 备注 |
|---|---|---|---|---|---|---|
| ① 前端直连东财(现状) | 0 | 东财接口级拒绝(本机/云上全 000)→ 图靠腾讯兜底 | 1min | 已存在 | ✗(每轮刷 warning) | #148 已证不可依赖 |
| ② 后端 minute_series 复用 | 0 | 10min 粒度,实时性差;提频会加重采集侧(生产 IP 风控面,§14) | 10min | 已有(采集侧) | ✗(不能替代实时) | 仅作降级第 2 层 |
| ③ **CF Worker 同源 relay(用户候选)** | **0(无需开安全组/配子域/动 CSP)** | CF 边缘出网可能被上游风控(需最小验证);免费 CPU 10ms 偏紧;无全局态(熔断降级) | 1min(腾讯/新浪源) | 中(逻辑在 Worker,随 push main 部署) | **✓(前端不再直连东财/腾讯,WAF 噪音归零)** | **推荐主方案** |
| ④ 云机 relay(#143 原方案) | **高(开 8080 安全组 + 配 rt.fx8.store,用户明确不想点控制台)** | 云机 IP 是生产采集 IP,出网集中 = 扩大风控面(§14,主控已提示不宜无条件先开) | 1min | 中(云上 systemd 手动管理) | ✓ | 已实现+复审 PASS,卡用户侧配置 |
| ⑤ CF Tunnel(免安全组) | 中(仍要动 CF 控制台创建 tunnel 路由 rt.fx8.store) | 同 ④ 云机出网;cloudflared 进程多一个故障点 | 1min | 高(多一进程) | ✓ | 不满足"用户零操作" |
| ⑥ 纯前端直连腾讯(删东财腿) | 0 | **单点依赖腾讯**(2026-08-05 曾 WAF 501;社区 09-18 也 501)→ 腾讯一封图全挂 | 1min | 低 | ✓(不直连东财) | 可作为"今天就能做的过渡"+ 后续叠 relay 兜底 |

**推荐(结合现状 = 图已由腾讯兜底、剩余问题是噪音):**
- **今天可做(Step1)**:前端东财腿熔断**跨轮记忆**(连续确定性拒绝 N 次后 N 分钟内跳过东财腿,直接走腾讯;恢复探测)——噪音根治的最小改动,不依赖任何外部源状态,今天就能验收"console 不再刷东财失败"(正是 #148 验收点)。
- **中期(Step2+3)**:①最小验证 CF 边缘出网(2c)→ ②通过则按用户候选方案把 relay 搬 Worker(/quote/intraday 同源路由 + fetchRelayMinute 改相对路径 + 默认开 + Cache API 4s)。腾讯万一再被 WAF 501 时,relay 是服务端兜底(新浪/腾讯),且免用户操作。
- **兜底(若 CF 边缘出网验证失败)**:维持 #143 云机 relay(用户拍板开安全组)或 ⑥ 纯前端直连腾讯(牺牲兜底)。
- **保留 minute_series 为降级第 2 层**,不改采集频率。

## 7. 推荐方案实施步骤 + 验收(relay 搬 Worker 的落地拆解)
前置:Step1(熔断跨轮记忆)与 Step2(最小验证)可并行;Step2 通过才做 Step3。
1. **Step1 前端噪音根治**(独立小单):app.js fetchTencentMinute 加跨轮熔断记忆(用模块级变量或 localStorage 存 `em_breaker_until`,连续确定性拒绝≥3 次 → 置 until=now+60s,until 内直接跳过东财腿返回 null 不循环不打 warning)。验收:Playwright 断东财 host,页面 console 无 `[intraday] 东财分时失败` 刷屏;腾讯腿正常画图(§22 一致性:app.js/app.min.js/index.html 版本串同步,bump 走 main-merge)。
2. **Step2 最小验证 CF 边缘出网**(2c 方案):wrangler dev --remote 或独立 probe worker。验收:em/qq/sina 三源状态码+可解析性记录;判定"哪些源 CF 边缘可用"。**此步不碰生产 Worker、不 commit 生产代码。**
3. **Step3 relay 搬 Worker**(若 Step2 显示腾讯或新浪 CF 边缘可用):
   - worker 新文件 `worker/relay.js`(或并入 headers.js)新增 `/quote/intraday?code=` 同源路由,逻辑:源序 em→qq_min→sina→qq_day(可去掉 em,若 Step2 证明不可用则直接 qq 起);单请求内多源串行首成功即停;Cache API 4s(cacheKey 剥 `_=` 参数);全源失败返 503;熔断用 Cache API 近似或单请求短路。
   - 前端:fetchRelayMinute(L13029)base 改同源相对路径 `"/quote/intraday?code="`(同源免 CSP),RT_RELAY_ENABLED 默认 true;缓存剥离逻辑保持。
   - 部署走现有 deploy-cf.yml(push main 自动 deploy,worker/** 触发)。
   - 验收:① 线上 curl `/quote/intraday?code=sh` 200+242 点 ② Playwright 断东财+腾讯 host,断言 relay 渲染曲线 ③ console 零噪音 ④ 对照双腿正常路径零变化 ⑤ §22 一致性(两份 CSP 无需改——同源,但确认无旧 rt.fx8.store 残留)。
4. **兜底(Step2 失败)**:回到 #143 云机 relay(用户拍板)或 Step1+⑥(纯腾讯直连)。

## 8. 诚实标注
- **实测(本机)**:东财全 host 000、腾讯 day/minute 200(242 点)、新浪 200 无 ACAO+body 实为 UTF-8、KV 最小 TTL 30s/Free 写 1000 天、Workers Free 100k 天/10ms CPU、Standard 单价、deploy-cf.yml 机制、minute_series 产物 12 码 241 点、Worker 出网先例(auth.js github/gitee/resend)。
- **社区先例(查到)**:腾讯 WAF 501 路径级(ai-quant-stock-picker#144)、东财 IP 级风控(FinAgent#4)。
- **推断/待验证**:①CF 边缘访问腾讯/新浪的具体状态(需 Step2 最小验证,今天没部署)②本 Worker 免费额度当前余量(无 dashboard 权限)③relay 每请求 CPU 是否 <10ms(需实测,超限升级 Standard)④腾讯 WAF 未来的动态行为。
- 本次未执行:任何部署、生产 Worker 改动、云上操作(纯只读调研)。

## 已验证方法/数据源清单
- 本机 curl 实测 7 个上游端点(东财 3 host / 腾讯 3 端点 / 新浪 1 端点)
- CF 官方文档 4 页(limits/cache/KV/pricing)
- GitHub API 搜索社区先例 2 条(ai-quant-stock-picker#144 / FinAgent#4)
- 项目内:worker/headers.js、wrangler.jsonc、relay/rt_relay.py、relay/README.md、static-site/app.js(L12786-13066/13590-13760)、app/collector/intraday_snapshot.py(L2310-2500)、.github/workflows/deploy-cf.yml、static-site/_headers、docs/pending-features-index.md(#142/#143/#148 条目)
- WebSearch/Bing/DDG 今日均空转或无针对性结果(记录:搜索服务异常,改用 GitHub API + 直连文档)
