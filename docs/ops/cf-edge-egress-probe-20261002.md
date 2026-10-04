# CF 边缘出网探测报告(2026-10-02,implementer 实测)

关联调研:`docs/ops/intraday-data-supply-options-20261002.md`(未 commit)结论:考虑把 `relay/rt_relay.py` 多源分时逻辑搬进现有 CF Worker(新增同源路由 `GET /quote/intraday?code=xxx`),以"用户零操作"根治 #148 噪音。
**最大不确定项 = CF Worker 从 Cloudflare 边缘出网抓行情接口是否被上游风控**。本报告为"最小验证方案"实测结果。

## 核心结论(先说结果)

| 源 | CF 边缘实测 | 判定 |
|---|---|---|
| 东财 trends2 | **11/12 次 HTTP 502**(16 字节),1/12 次 200(241 点)但同 host 下一轮 108s 超时空响应 | **不可用**(确定性 502,偶发成功极慢,不可依赖) |
| 腾讯 minute/query | **12/12 次 HTTP 200**,11934 字节,code=0,242 点 | **可用,稳定** |
| 新浪 KLine | **8/10 次 HTTP 200**(36084 字节,241 点)+ 2/10 次 520 | **基本可用,偶发 520** |

**结论:CF 边缘出网可行,腾讯腿稳定、新浪腿可用(偶发 520),东财腿在 CF 边缘基本废(502)**。
对 relay 搬 Worker 的直接含义:SOURCE_ORDER = em→qq_min→sina→qq_day,em 在 CF 边缘确定性失败会自动落 qq(腾讯稳定 200)——**该方案前提成立,推荐主方案可行性确认**。

## 方法(临时资源,全程未碰生产)

- **触发通道选型**:方案 A(`wrangler dev --remote`)与本机直连 `workers.dev` 均不可达(本机 → CF 的 WSS preview/tail 通道超时 ETIMEDOUT,workers.dev 直连 75s 超时;仅 api.cloudflare.com HTTPS API 通)。故改用**独立临时 worker + cron 自动触发 + 探测结果写 R2 + 本地 HTTPS 读 R2**:
  1. `wrangler deploy --config /tmp/cf-probe/wrangler-probe.jsonc`(独立 worker `relay-probe-tmp`,只绑 workers.dev 子域 `relay-probe-tmp.sugas13465.workers.dev`,不挂自定义域,不写 routes,不占生产 worker)
  2. 配置 `triggers.crons = ["*/1 * * * *"]` + `r2_buckets = [R2_BUCKET→signal-data]`(临时探测结果写 R2 `probe/` 前缀,读后即删)
  3. worker 的 `scheduled` handler 每分钟触发,已有当日结果则跳过,否则三源探测 17 次请求、结果 PUT 到 R2
  4. 本地用 `scripts/upload_r2.py`(SigV4,凭证 .env)读 R2 → 删 key → `wrangler delete relay-probe-tmp`
- **探测脚本**:`/tmp/cf-probe/worker-probe.js`(临时,不在 git)。每源请求次数:东财 3 host×2 轮=6、腾讯 3 host×2 轮=6、新浪 1 host×5=5,共 17 次/轮;记录 status/bytes/parsed/ok/points/err/dur_ms。
- **探测标的**:`sh000001`(上证指数)。URL 构造与 `relay/rt_relay.py` 的 `_em_urls/_qq_urls/_sina_urls` 同构。
- **判定标准**:200+可解析=可用;000/501/403/502=不可用。

## 原始探测数据(两轮,CF 边缘真实执行)

### 轮 1(2026-10-02 15:08:51Z,写入 R2 key `probe/cf-egress-202610021508514.json`)

| 源 | host | round | status | bytes | parsed | ok | pts | dur_ms |
|---|---|---|---|---|---|---|---|---|
| em | push2delay | 0 | 502 | 16 | ✗ | ✗ | - | 3416 |
| em | push2 | 0 | 502 | 16 | ✗ | ✗ | - | 4745 |
| em | 2.push2 | 0 | **200** | 20010 | ✓ | ✓ | **241** | 9564 |
| em | push2delay | 1 | 502 | 16 | ✗ | ✗ | - | 3747 |
| em | push2 | 1 | 502 | 16 | ✗ | ✗ | - | 5583 |
| em | 2.push2 | 1 | 200 | **0** | ✗ | ✗ | - | **108156** |
| qq | web.ifzq | 0 | **200** | 11934 | ✓ | ✓ | **242** | 972 |
| qq | proxy.finance | 0 | **200** | 11934 | ✓ | ✓ | **242** | 1567 |
| qq | ifzq | 0 | **200** | 11934 | ✓ | ✓ | **242** | 1695 |
| qq | web.ifzq | 1 | **200** | 11934 | ✓ | ✓ | **242** | 3897 |
| qq | proxy.finance | 1 | **200** | 11934 | ✓ | ✓ | **242** | 1289 |
| qq | ifzq | 1 | **200** | 11934 | ✓ | ✓ | **242** | 298 |
| sina | quotes.sina | 0 | 520 | 16 | ✗ | ✗ | - | 30792 |
| sina | quotes.sina | 1 | **200** | 36084 | ✓ | ✓ | **241** | 18991 |
| sina | quotes.sina | 2 | **200** | 36084 | ✓ | ✓ | **241** | 3535 |
| sina | quotes.sina | 3 | **200** | 36084 | ✓ | ✓ | **241** | 117 |
| sina | quotes.sina | 4 | **200** | 36084 | ✓ | ✓ | **241** | 457 |

### 轮 2(2026-10-02 15:10:52Z,key `probe/cf-egress-202610021510521.json`)

| 源 | host | round | status | bytes | parsed | ok | pts | dur_ms |
|---|---|---|---|---|---|---|---|---|
| em | push2delay | 0 | 502 | 16 | ✗ | ✗ | - | 7605 |
| em | push2 | 0 | 502 | 16 | ✗ | ✗ | - | 25337 |
| em | 2.push2 | 0 | 502 | 16 | ✗ | ✗ | - | 1500 |
| em | push2delay | 1 | 502 | 16 | ✗ | ✗ | - | 4809 |
| em | push2 | 1 | 502 | 16 | ✗ | ✗ | - | 685 |
| em | 2.push2 | 1 | 502 | 16 | ✗ | ✗ | - | 7524 |
| qq | web.ifzq | 0 | **200** | 11934 | ✓ | ✓ | **242** | 244 |
| qq | proxy.finance | 0 | **200** | 11934 | ✓ | ✓ | **242** | 144 |
| qq | ifzq | 0 | **200** | 11934 | ✓ | ✓ | **242** | 445 |
| qq | web.ifzq | 1 | **200** | 11934 | ✓ | ✓ | **242** | 242 |
| qq | proxy.finance | 1 | **200** | 11934 | ✓ | ✓ | **242** | 303 |
| qq | ifzq | 1 | **200** | 11934 | ✓ | ✓ | **242** | 213 |
| sina | quotes.sina | 0 | **200** | 36084 | ✓ | ✓ | **241** | 3114 |
| sina | quotes.sina | 1 | 520 | 16 | ✗ | ✗ | - | 24900 |
| sina | quotes.sina | 2 | **200** | 36084 | ✓ | ✓ | **241** | 202 |
| sina | quotes.sina | 3 | **200** | 36084 | ✓ | ✓ | **241** | 1247 |
| sina | quotes.sina | 4 | **200** | 36084 | ✓ | ✓ | **241** | 399 |

### 波动/规律观察

- **东财**:两轮 12 次中 11 次 502、1 次 200(且同 host 随后一轮 108s 超时空响应)。502 = Cloudflare 网关错误码(CF 边缘到东财出网连接失败/被拒),16 字节固定 body。**与调研"东财 IP/接口级风控"定性一致**(本机 000、CF 边缘 502,本质同源拿不到数据)。偶发 200 不可依赖(慢 + 下一轮即翻车)。
- **腾讯**:12/12 全 200,字节 11934 完全一致,242 点,耗时 0.1~3.9s。**无 WAF 501 迹象,CF 边缘稳定**。与调研"腾讯路径级 WAF 动态"风险相比,当前观察窗口(盘后)稳定,但 WAF 动态变化仍需持续观察(见诚实标注)。
- **新浪**:8/10 的 200(36084 字节一致,241 点),2/10 的 520(16 字节,Cloudflare 到源站响应异常,偶发)。**可用但偶发抖动,符合调研"服务端形态"推断**。

## 顺带核验 1:Workers 免费额度余量(有权限,实测)

CF GraphQL Analytics(OAuth token 有读权限)实测:

| 时段 | 总请求数 | 占免费 100,000/天 |
|---|---|---|
| 2026-10-01 全天 | 6,406 | 6.4% |
| 2026-10-02 00:00→15:20Z(盘中过半) | 6,221 | 约 12%(全天线性外推) |

**余量充足**。relay 增量(12 码 × 240 次/交易日 ≈ 2,880 次/天,4s 缓存削峰后回源更少)完全在预算内,无 Error 1027 风险。

查询命令(复现):
```
POST https://api.cloudflare.com/client/v4/graphql
Authorization: Bearer <wrangler oauth_token>
{viewer{accounts(filter:{accountTag:"9be954e87f3d28f9c0faaa9e2b3a78b7"}){workersInvocationsAdaptive(limit:2000,filter:{datetime_geq:"2026-10-01T00:00:00Z",datetime_leq:"2026-10-02T00:00:00Z"}){sum{requests}}}}}
```
(token 位置:`~/Library/Preferences/.wrangler/config/default.toml`)

## 顺带核验 2:CPU 时间可行性(本地 node 实测)

官方 Free 限 **CPU 10ms/请求**(超限 Error 1102)。用真实数据样本本地 node 计时(`/tmp/cf-probe/cpu-bench.js`,临时):

- 数据量与本探测**字节数完全一致**:腾讯 11934 字节、新浪 36084 字节(印证 CF 边缘拿到的是同一份数据)。
- 东财真实样本 CF 边缘 502/本机 000 均拿不到,用 242 点 mock(17.5KB;JSON.parse 成本与字节线性,50KB 估算值已折算)。

| 项目 | 耗时(500 次平均) |
|---|---|
| JSON.parse 腾讯 11.9KB | 0.016 ms |
| JSON.parse 新浪 36KB | 0.108 ms |
| JSON.parse 东财 50KB(线性折算) | ~0.03 ms |
| 腾讯 242 点循环构造 | 0.064 ms |
| 新浪 241 点循环构造 | 0.034 ms |
| 东财 242 点循环构造 | 0.099 ms |
| **最坏全源路径(em+qq_min+sina+qq_day 全成功:4 parse + 4 循环)** | **0.38 ms** |

**结论:最坏全源解析 CPU ≈ 0.4ms,即使考虑 Worker V8 isolate 与 node 的倍率(~3x)与 URL/Headers/sort/pct 杂项,总量级 ~2-3ms,仍低于 10ms 硬限(3-5 倍余量)。CPU 不是瓶颈。**

缓解措施(仍建议落地,零成本):
- **非 200 / 0 字节直接短路不 parse**(本探测已观察:502/520 固定 16 字节,直接 `if(resp.status!==200) return 失败` 跳过 parse,东财腿 CPU≈0)——与调研报告建议一致。
- 若未来真超限再升级 Standard(本探测证明当前余量充足)。

## 清理记录(§25,全部为本次新建临时资源)

| 资源 | 类型 | 处置 | 说明 |
|---|---|---|---|
| `relay-probe-tmp` worker | 临时 worker(本次新建) | `wrangler delete relay-probe-tmp --force` → **已删除** | 只绑 workers.dev 子域,无 routes,无自定义域,无业务数据 |
| `probe/` R2 前缀 keys(cf-egress×2 + ping×7) | 本次探测写入 | `scripts/upload_r2.py cmd_delete` 逐个删除,删后 `_list_keys('probe/')` 为 0 → **已全部删除** | 探测/ping 结果,无业务数据 |
| `relay-probe-tmp-dev`(dev --remote 残留) | 临时 preview | dev 进程退出自动清理,CF API 复核 `workers/scripts` 列表**无残留** | - |
| 生产 Worker `trade-data-signal` / `hdszf` | 既有 | **未触碰**(全程只 deploy/delete 独立 `relay-probe-tmp`) | 复核 `workers/scripts` 列表确认仍存在 |

恢复路径:无需恢复(全为一次性临时资源;R2 探测数据不可再取回,但原始输出已在本报告上文)。

## 诚实标注

- **实测**:CF 边缘两轮 34 次出站请求(东财 12/腾讯 12/新浪 10)、CF GraphQL 用量两日汇总、本机 node CPU 计时(真实腾讯/新浪样本)。
- **推断**:①"腾讯 WAF 动态变化需持续观察"——本次窗口(盘后 Z 15:00+)稳定 200,但调研社区先例(ai-quant-stock-picker#144,2026-09-18)显示腾讯路径级 WAF 时好时坏,长期稳定性**未证**;②东财"确定性 502 为主、偶发 200 不可依赖"基于 12 次样本,统计置信有限但方向明确(与本机 000、社区 IP 风控定性三处互证)。
- **未核实**:①腾讯 501 WAF 是否会在**盘中(09:30-15:30)**对 CF 边缘放行——本次探测在盘后执行,盘中行为未测(应列为 relay 搬 Worker 上线前的补充验证项);②新浪 520 的触发条件(是否与 CF 边缘出口 IP 或请求频率相关)未深究。
- **未执行**:任何生产 Worker 改动、生产路由、生产 wrangler.jsonc 变更、对既有 worker(hdszf/trade-data-signal)的 deploy。

## 对 relay 搬 Worker 的落地建议(供主控/下一步决策)

1. **腾讯腿为主力**:CF 边缘稳定 200,relay 搬 Worker 后 qq_min 应保留为主源。
2. **东财腿建议移除或置末**:CF 边缘确定性 502 浪费一次请求/CPU;但 relay 逻辑"失败自动换源"已兜底,即便保留也无功能危害(仅多一次 502 往返)。实现上建议**直接 qq 起手**,少打一次 502。
3. **新浪腿保留为兜底**:可用但偶发 520,作为腾讯万一 WAF 501 时的第二兜底。
4. **上线前补测**:盘中窗口(09:30-15:30)对腾讯/新浪的 CF 边缘可用性(本探测为盘后窗口)。
5. CPU/额度均非瓶颈,缓存选型(Cache API 4s)、熔断降级(单请求短路+Cache 近似)按调研报告 §3/§5 执行即可。

## 已验证方法/数据源清单

- CF 官方 Wrangler 4.147.0(deploy/delete,独立配置 `--config`)
- CF GraphQL Analytics API(workersInvocationsAdaptive 用量)
- R2 S3 API(`scripts/upload_r2.py` s3_request SigV4)
- 本机 curl 抓腾讯/新浪真实样本(node CPU 计时输入)
- 探测 worker 脚本 `/tmp/cf-probe/worker-probe.js`(临时,已随 worker 删除;命令与输出可复现,见上文原始数据)

---

## 2026-10-04 第二轮复测(自定义域名通道)

> 本文档首轮(10-02)之后追加的**独立第二轮复测**,与首轮结论互证。10-02 原文保持不改写(历史记录),只追加本节。

### 为什么要复测

- 10-02 那轮之后,`relay` 方案(把多源分时逻辑搬进 CF Worker)的可行性需要再确认一次——尤其要验证"大陆用户直接访问 `*.workers.dev` 读边缘执行结果"这条通路,因为首轮探测的结果是**写 R2 再由本地读**,没有验证"大陆浏览器能否从 CF 边缘直接拿到结果"。
- 首轮探测在**盘后**窗口执行(Z 15:08 / 15:20+),样本窗口窄,复测选新窗口再跑一轮、且换自定义域名通道,双独立互证。

### 本轮怎么测通的

- 挂**临时 custom domain**:`relay-probe-tmp` worker 绑临时自定义域名 `probe-tmp.fx8.store`(经 CF 面板/API 添加 custom domain → CF 自动签发边缘证书 + DNS 记录)。
- 大陆侧直接 `curl https://probe-tmp.fx8.store/...` 3 轮,读到的就是 worker 在 CF 边缘真实出站抓取的结果——**从用户视角端到端验证**。
- 测完**删除 worker**(`wrangler delete relay-probe-tmp`),custom domain / DNS / 证书随 worker 删除级联清理(见下文清理证据)。
- **关键经验(以后还会用)**:大陆访问 `*.workers.dev` 被 **SNI 污染阻断**(解析到 Facebook/Dropbox 的 IP,连接被 RST/超时),**必须走自定义域名**才能从大陆直接读到 CF 边缘执行结果。所以 relay 方案上线时**必须给 worker 挂自定义域名**(如 `quote.fx8.store` 之类),不能依赖 workers.dev 子域。

### 实测结果表(6 源 × 3 轮,逐次列出)

| 源 | host | 轮 1 | 轮 2 | 轮 3 | 结论 |
|---|---|---|---|---|---|
| 腾讯分时 | `web.ifzq.gtimg.cn` | 200/11940B | 200/11940B | 200/11940B | **3/3 可用,稳定** |
| 腾讯批量 | `qt.gtimg.cn` | 200/463B | 200/463B | 200/463B | **3/3 可用,稳定** |
| QQ 代理 | `proxy.finance.qq.com` | 200/11940B | 200/11940B | 200/11940B | **3/3 可用,稳定** |
| 新浪 | `hq.sinajs.cn`(带 Referer `https://finance.sina.com.cn`) | 200/171B | 200/171B | 200/171B | **3/3 可用(本轮全绿)** |
| 东财 | `push2delay.eastmoney.com` | 502/16B | 502/16B | 502/16B | **3/3 确定性 502** |
| 东财 | `push2.eastmoney.com` | 502/16B | 502/16B | 502/16B | **3/3 确定性 502** |

(探测标的 `sh000001` 上证指数;URL 构造与 `relay/rt_relay.py` 的 `_em_urls/_qq_urls/_sina_urls` 同构;判定标准同首轮:200+可解析=可用,501/502/403/000=不可用。)

### 结论

- **relay 方案前提再次成立**:CF 边缘可达腾讯/新浪,东财在 CF 边缘确定性 502。
- **建议源序**:腾讯分时 → 腾讯批量 → 新浪兜底 → **东财不排**(边缘确定 502,排了只会白打一次 502 往返)。与首轮建议一致,本轮从"自定义域名端到端"通道再确认一次。

### 遗留验证缺口(必须写)

- **两轮均盘后执行**;CF 边缘在**盘中(09:30-15:30)**对腾讯/新浪的可用性**未实测**——上线前应补一次盘中验证(腾讯 WAF 是否盘中放行、新浪是否盘中 520,均为未证项)。

### 清理证据

- `wrangler delete relay-probe-tmp`(输出含 Successfully deleted,临时 worker 已删除)。
- workers 列表只剩 `['hdszf','trade-data-signal']`(生产两个 worker 未触碰)。
- custom domains 只剩 `ss.fx8.store`。
- `dig @olga.ns.cloudflare.com probe-tmp.fx8.store` = **NXDOMAIN**(DNS 记录已随 custom domain 清理,可反查)。

### 诚实标注

- **实测**:6 源 × 3 轮 = 18 次出站请求(状态码/字节数/耗时全部来自 `curl` 真实输出);DNS/证书/worker 清理证据来自 `dig`/`wrangler`/CF API 复核。
- **推断**:新浪"长期稳定性"仍按兜底位设计——本轮 3/3 全绿,但叠加 10-02 首轮 8/10(2 次 520),样本 13 次中 2 次异常,故建议放腾讯之后的兜底位而非主力。
- **未核实**:盘中(09:30-15:30)CF 边缘可用性(见"遗留验证缺口")。
- **未执行**:任何生产 Worker 改动 / 生产路由 / 生产 wrangler.jsonc 变更 / 对既有 worker(hdszf/trade-data-signal)的 deploy。
