# 云服务器多源行情中转服务 rt_relay.py

**定位**: 前端「东财→腾讯」分时双腿之后的**替补第三腿**。浏览器直连东财被间歇性风控(实测 3/10 拒绝)、腾讯北交所分时只返 3 段、新浪接口无 ACAO 头浏览器取不到——这三类问题统一由服务端中转解决:服务端去各源抓,前端只连中转一个地址。

**上线前默认禁**(`RT_RELAY_ENABLED=false`),零副作用:前端假腿失败才走第三腿,现有成功路径逐位不变。

## 功能

- **多源聚合**: 单请求内按 `em → qq_min → sina → qq_day` 顺序试源,首个成功即返回(首个即停不浪费)。
- **熔断**: 区分为「确定性拒绝」(4xx/5xx/业务错误码/结构不对)vs「偶发抖动」(socket 超时/连接重置/SSL)。确定性拒绝累计 3 次→源 open 60s,半开后探测成功即恢复。「连续撞拒不铺张」。
- **限速(最优先安全项)**: 每源 TokenBucket 硬顶,60s 滑动窗口按 `(rate, burst)` 计数:
  - `em=(40,10)`、`qq_min=(30,8)`、`qq_day=(20,6)`、`sina=(40,10)`、`sina_day=(10,4)`,全局 120/min。
  - 目的:中转不管你帮谁抓,量级必须 < 生产采集 IP 被风控的边界(省得连累所有定时任务,§14 P0)。
- **4s 短缓存 + stale 兜底**: 同代码 4s 内命中缓存零上游;上游全挂时回 stale(带标记),再无则 503。
- **并发收敛**: 同 code 同时并发只放一个 owner 去上游,其余 in-flight 去重等待;全局并发上限 6。
- **CORS**: 预检 OPTIONS→204 + `Access-Control-Allow-Origin`(可白名单/`*`)+ Allow-Methods/Allow-Headers/Max-Age;GET 带 Origin 返对应 ACAO。部署后建议配 `RT_ORIGINS` 白名单收紧到 ss.fx8.store 等。
- **/health** 暴露各源 state/计数/缓存/并发,结构化 JSON lines 日志(`evt` 字段可 grep)。

## 接口

```
GET /intraday?code=bj50   # code: 前端 12 指数短码(sh/sz/hs300/sz50/cyb/kc50/bj50/csi500/csi1000/hsi/hstech/hscei)
                          # 200 → {name, price, preClose, pct, date, source, points:[{time,price,volume,amount}]}
                          # 503 → 全源失败(或熔断/限速跳过),json {error,...}+ 前面尝试的 upstreams
GET /health               # {ok, counters, sources 各源 state/used, cache, global, concurrency}
OPTIONS /                 # 204 + CORS 头
```

前端 `_INDEX_TO_TENCENT_MINUTE` (腾讯)与 `INDEX_EM`(东财 secid)与 `INDEX_SINA`(新浪)映射同构,relay 内三张表与前端逐位一致。

## 本地起服(开发/测试)

```bash
python3 relay/rt_relay.py            # 默认 0.0.0.0:8080
RT_PORT=8081 RT_ORIGINS="https://ss.fx8.store" python3 relay/rt_relay.py   # 可选覆盖
```

环境变量覆盖(全可配):`RT_PORT/BIND/CACHE_TTL/PRE_CLOSE_TTL/TIMEOUT/CONCURRENCY/ORIGINS/SOURCES/DET_N/NET_N/OPEN_DET/OPEN_NET`。`RT_SOURCES=em,qq_day,qq_min,sina` 可关源;`RT_TEST_DET_FAIL=em` 为测试注入确定性失败(验熔断用,生产禁)。

本地验证样例:

```bash
curl -s "http://127.0.0.1:8080/intraday?code=bj50" | python3 -m json.tool | head
curl -s "http://127.0.0.1:8080/health" | python3 -m json.tool
curl -s -X OPTIONS "http://127.0.0.1:8080/" -i
```

## 部署到云上(本次只写方案,不执行;由用户拍板后操作)

前端接入地址占位 `https://rt.fx8.store` + `RT_RELAY_ENABLED` 开关在 `static-site/app.js` 顶部常量(搜 `RT_RELAY_BASE_URL`),改这 2 处即切换。

1. **云上起服**: `rsync` 或 git 拉 `relay/rt_relay.py` 到云机,系统服务(systemd unit,`WantedBy=multi-user.target`,Restart=always)。
   - 上游 https 证书: 云上装了 ca-certificates 即可正常验证,本机 `ssl-insecure-fallback` 仅开发机无系统 CA 时触发。
   - ⚠️ **只听内网/云安全组** 只放 8080(tcp),其余关闭。中标云安全组开放 8080 给 CF 回源段(或任意需透传),再收紧。
2. **CF 子域名/反代**: 配 `rt.fx8.store` → origin `http://<云内网IP>:8080`,CF 项:
   - SSL/TLS 模式 Full(strict)或 Flexible(取决于云机证书)。
   - Caching(Assets)别缓存动态 `/intraday`(设 no-store 或绕过);或者直接让本服务 `Cache-Control: no-store` 已被响应头带出——CF 默认会尽力缓存天级 CDN,务必对 `/intraday` 添加 Cache Rule「不缓存」。**4s 缓存在中转服务内部实现,不是靠 CF。**
3. **前端切换**: `app.js` 顶部 `RT_RELAY_BASE_URL = "https://rt.fx8.store"`(默认值已是)+ `RT_RELAY_ENABLED = false` 翻 `true`,重新 build_min(由 main-merge.sh 统一 bump),上线。
   - 若想收紧 CORS:`RT_ORIGINS="https://ss.fx8.store,https://sss.sugas.site,https://s.sugas.site"`。
   - ⚠️ **翻开关必做**:两份 CSP `connect-src` 白名单(`static-site/_headers` + `worker/headers.js`)**都要**补 `https://rt.fx8.store`,且两处**逐字一致**。不补会在线上重开一轮 console CSP 刷屏(正是 #133 刚修掉的问题,留到基于 main 当天补 2 处并逐字核对——本 feat 分支 base 早于 #133,分支上两份 CSP 还是旧版,切勿在分支上动手,会与 #133 对同一行产生 merge 冲突)。
4. **上线前自验**(playwright): 断前两腿 host 断言 bj50 走中转渲染出曲线;对照正常双腿零变化;观察 `/health` 各源计数稳定、无超 bucket。

## 成本与风险核算(2026-09-30 实测)

| 场景 | 前端→relay | relay→上游 |
|---|---|---|
| 正常(双腿成功) | 0 请求(第三腿不进) | — |
| 补位失败走 relay | 12 码/轮(1min 轮询) | ≤12 码×(1~4 源) 但首个成功即停,缓存命中后≈1 次/60s |
| 全源失败逐一试(最坏) | 12/轮 | ≤48 次/60s,分摊到 4 源各自 bucket(em≤40/qq_min≤30/sina≤40/qq_day≤20),全局 120 硬顶 |

- 前端原双腿 12 码 = 24 次/min 直连浏览器 IP;走 relay 最少 12 次/min 到中转,上游量级持平或更低,且有 bucket 硬顶 + 熔断 + 缓存削峰。
- **生产 IP 保护断言**: 中转集中请求数与双腿持平、每源不超 bucket、4s 缓存削峰、熔断防连续撞拒——不会因为替前端抓数据把云机 IP 打爆牵连所有定时任务。
- 实测北交所 bj50 走 relay 返回 242 点全量(前端直连腾讯只 3 段的坑被解析层抹平);em 现场复现间歇拒绝后自动落 qq_min,弹得很顺。

## 测试牺牲与遗留

- 服务端 07 项自验全过(4 码全 200 / 只剩新浪场景 / 熔断触发·半开恢复 / 限速 80 连打不超 bucket / 5s 缓存命中 / CORS 204+完整头 / health)。
- Playwright 端到端:无痕浏览器拦截东财+腾讯全部 host,`_rtSetRelay(true, local)` 开启,断言 bj50 spark 真渲染(非快照标签) + relay 计数 +1,同时对照默认禁时 12 码全渲染零变化。测试脚本 `/tmp/rt_pw6.mjs`、`/tmp/rt_pw7.mjs`。
- 服务端测试注入点仅在 `_resolve` 编排层(`RT_TEST_DET_FAIL`,生产禁),不污染抓取逻辑。
- 已知边界: 新浪宽基(A股9码)无港股,`INDEX_SINA` 校验层放行 A 股;港股 hsi/hstech 依赖 em/qq/qq_day。新浪 `sina_day` 只用于补昨收,失败不回滚整体。

## 举一反三: 同链路可受益位(2026-09-30 清单)

已接入:
- 首页 spark-grid 12 码分时图(单卡 `_fetchIntradayRenderSource` 第三腿 + 批量 `_fetchDynamicPcts` L4 relay 兜底)。
- 首页批量动态 badge / spark-foot(`_fetchDynamicPcts` L4 复用同一 `fetchRelayMinute`)。
- 新闻弹窗当日大盘分时迷你图(`_ensureNewsModalSpark` 复用 `_fetchIntradayRenderSource("sh")`,同函数已自动带第三腿)。

可扩展(本次未做,留作 relay 后续端点,不占本次 scope):
- lab.js 盘中现价(`qt.gtimg.cn` 直连批量 ETF 价)——可加 `/quote?codes=...` 端点再前端切源,与 /intraday 同套熔断限速。
- 东财/腾讯其他实时(如行业/概念实时涨幅)——同套多源中转模式可复刻。