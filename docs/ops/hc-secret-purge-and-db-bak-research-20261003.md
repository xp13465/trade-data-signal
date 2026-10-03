# PURGE_SECRET 泄露危害复核 + public_fund.db.bak 10G 来源调研(2026-10-03)

> 触发:主控派单,两个独立只读调研——①独立复核 D7 报告「PURGE_SECRET 能力边界=仅可清缓存」结论 + 轮换方案 ②查明 public_fund.db.bak 双仓 10G 残留来源与可删性。
> 全程只读:云上零写、不 kill 进程、不执行轮换;本机仅写本报告。报告全文不含任何密钥明文(值以 hash 前 16 位指代,与 D7 同口径)。

## 0 结论速览

**问题 1(PURGE_SECRET)**
- 能力边界复核结论:**D7 结论成立且被我独立代码复核确认**——该值只能调 `/api/purge-cache` 清 CF 边缘缓存(任意路径,受 Worker 所在数据中心与域名限制),**无 R2 读写/删除/列举、无账户/配置查询、无数据篡改**能力。证据 = `worker/headers.js:279-300` 逐行。
- 计费影响:**不推高 R2 Class A 计费**。purge = Worker 运行时 `caches.default.delete`,不产生任何 R2 操作;后续回源 = R2 `GetObject`(官方 Class B,免费 10M/月,本项目当月仅 294.65k,余量 ~9.7M)。恶意反复 purge 理论可推高 Class B,但需海量请求(配合高频 GET),且 Worker 与 R2 免费额度余量极大,实际难触发收费。**与 9 月 $4.50 账单(Class A 超 1M)无因果关联**。
- **建议:今天轮换**(2026-10-03 周六国庆休市,无盘中任务,验证窗口安全)。值公开 21 天+仍在用,轮换成本低(4 处改动 + 验证),风险可控。

**问题 2(public_fund.db.bak)**
- 来源:**坐实为手工操作(用户本人),非脚本/定时任务,非安全事件**。10-03 10:46-10:47 用户本机(公网 IP 61.170.217.75,key 指纹与 `~/tdsignal.pem` 逐位一致)通过 ssh 发起多笔短会话,`.bak` 文件 mtime(10:47:13.75 / 10:47:38.37)与会话时点完美吻合。
- 可删性:**不可直接删**。D6 已确认 public_fund.db 无任何异地备份,这份 .bak 是当前唯一额外时间点快照(虽同机,仍双保险)。建议先补异地备份(D6 P0 修复,本是待办)→ 验证可恢复后再删;至少先删镜像仓 5G(与主仓逐位相同 sha256,纯冗余)。
- 恢复路径:`cp /home/ubuntu/code/trade-data-signal/data/public_fund.db.bak-20261003_104704 /home/ubuntu/code/trade-data-signal/data/public_fund.db`(先停写/确认无活动连接)。诚实标注:同机副本,盘毁不可防。

## 问题 1:PURGE_SECRET 能力边界独立复核

### 1.1 代码证据(不照抄 D7,逐行读 worker 实际代码)

**Purge Worker 端点 = `worker/headers.js:279-300`(唯一入口)**:

```js
// POST /api/purge-cache：主动清 CF 边缘缓存（upload_r2.py 上传新数据后调）。
// body: { secret: "xxx", keys: ["/data/overview.json", ...] }
async function purgeCacheHandler(request, env, url) {
  if (request.method !== 'POST') { return 405; }
  body = await request.json();                       // 400 on invalid JSON
  if (!body.secret || body.secret !== env.PURGE_SECRET) { return 403; }
  for (const keyPath of (Array.isArray(body.keys) ? body.keys : [])) {
    const cacheKey = new Request(url.origin + keyPath);
    await caches.default.delete(cacheKey);            // 唯一动作
    purged++;
  }
  return Response.json({ purged, total: keys.length });
}
```

逐行能力清单:

| 能做什么 | 证据 | 不能做什么 | 证据 |
|---|---|---|---|
| POST 携带正确 secret 后,对该 Worker 域(`url.origin`)下**任意路径**执行边缘缓存删除 | `headers.js:295-297` `new Request(url.origin + keyPath)` → `caches.default.delete` | 读/写/删/列举 **R2 对象** | `headers.js:279-300` 全文无 `env.R2_BUCKET`;`grep -n "env.R2_BUCKET"` 仅 2 处(`headers.js:157` dataRewriteHandler、`headers.js:241` r2ProxyHandler,均为公开读代理,**不校验 PURGE_SECRET**,与 purge 端点无关) |
| 清缓存后的自然效果 = 用户下次请求回源 R2 拉最新数据(数据本身不变化) | 同上 | 篡改/注入数据 | R2 是唯一数据源,缓存删除不改 R2 |
| 对不存在的 key 调 delete 也返回 `purged` 计数(幂等无害) | `headers.js:296-298` 不检查 delete 返回值 | 查账户信息/配置/其他 zone | Worker env 仅暴露 PURGE_SECRET 等 secret,无 API token 类凭据 |
| 指定任意 path(可指向其他域名同 worker 的路径,取决于请求 host) | `url.origin` = 被请求 hostname | 跨域清其他独立 Worker 的缓存 | 自定义域名需接入该 Worker 才有效 |

**调用方 `scripts/upload_r2.py:1684+`(purge_cache 函数)**:读本地/云上 `.env` 的 `PURGE_SECRET` → 分批 POST(每批 30 keys、批间 0.5s,防 Worker 超时)→ 失败不中断上传。证据 `upload_r2.py:1684-1730` 注释「Worker purgeCacheHandler 串行 await caches.default.delete 遍历所有 keys,一次性发 400+ keys 致 Worker 超时 500」→ 侧证 purge 动作 = 纯 Worker 运行时缓存操作,与 R2 计费操作(PUT/List)无交集。

**域名/部署**:wrangler.jsonc 无 routes 段(GH Actions `deploy-cf.yml` 跑 `npx wrangler deploy`,secrets 走 `wrangler secret put`,见 `docs/site-deployment.md:574-580`);`cache.delete` 只清「Worker 被调用所在数据中心」的边缘缓存(官方文档,见 1.2)——单次调用覆盖面有限,非全局。

### 1.2 官方文档佐证(§5.1 外部系统先查官方,curl 直连 2026-10-03)

| 项 | 官方原文 | 佐证意义 |
|---|---|---|
| purge 本身是缓存层操作,不碰存储 | Workers Cache API 文档(developers.cloudflare.com/workers/runtime-apis/cache/):`cache.delete(request)` 只删缓存中 Response 对象,返回 boolean | 能力边界=只清缓存 ✓ |
| cache.delete 单数据中心局限 | 同文档:「The cache.delete method only purges content of the cache in the data center that the Worker was invoked. For global purges, refer to Purging assets stored with the Cache API」 | 攻击者单次调用覆盖面小,需多数据中心逐次清 |
| 官方 purge API 需 Cache Purge 权限 token + 账号级 token bucket 限流(Free 5 req/min、桶 25 tokens) | cache/how-to/purge-cache/「Token bucket rate limiting」段 + cache/guides/invalidate-cache/「Permissions」段 | **本项目端点走 Worker Cache API 不走官方 API → 不受该限流**(自建端点的特征,攻击者可更高速调用,但受 Worker 请求额度限制) |
| R2 Class A/B 官方定义 | r2/pricing/:Class A = List/Put/Copy/multipart 等**变更为主的写列举操作**($4.50/M);Class B = GetObject/HeadObject 等**读操作**(免费 10M) | purge 不含且不触发 Class A;回源 GET 属 Class B |
| 回源计费口径 | r2/pricing/ 免费额度:Class A 1M/月、Class B 10M/月;取整规则按下一个计费单位 | 见 1.3 量化 |

**社区先例检索(诚实标注:未取得)**:WebSearch ×3、DuckDuckGo HTML、HN Algolia API、jina r.jina.ai、CF AI Search API 全部网络受限/返回空(与 r2-billing-20261002 报告 §④Q3 同况)。**判定完全基于官方一手文档 + 本仓代码证据**,不依赖社区先例。这也符合本仓已知的搜索受限环境,非调研遗漏。

### 1.3 计费影响专门查证(结合 9 月 $4.50 实收账单)

**结论:泄露的 PURGE_SECRET 不会推高 R2 Class A 计费,与 $4.50 账单无因果关联。**

推理链(全部有据):
1. **purge 动作本身不产生 R2 操作**:`caches.default.delete` 是 Worker 运行时行为,官方不计入 R2 任何操作类别(1.2 官方文档)。
2. **purge 后的回源 = R2 `GetObject` = Class B**(官方 r2/pricing Class B 清单含 GetObject),**Class B 免费额度 10M/月**(官方),本项目当月用量 294.65k(10-02 账单,r2-billing 报告 §①),余量 ~9.7M。
3. **要触发 Class B 收费**,需单月再产生 ~9.7M 次回源 GET。攻击者需「purge + 自己高频 GET」或诱导真实用户流量;即使按每请求 2 次操作(purge+GET)计算,也需 ~485 万次循环——受 Worker 免费请求额度(官方 Free 计划 10 万/天,workers/platform/pricing/)封顶,且本项目 Worker 走 CF 免费额度(10-02 账单仅 R2 一行费用,Worker 无计费行 → 在免费额度内)。
4. **$4.50 账单归因**(既有 r2-billing-4usd50-followup-20261002.md 结论):Class A 1.22M 主因 = 9-15 增量化前 deploy 全量上传模式(fund-nav per-code 单通道 ~2.4 万 PUT/次);9-15 起增量四箭落地后 10 月 Class A 预计降至十几万/月。**purge 不产生 PUT/List,与该账单无关**。

**真实影响面(攻击者拿到 secret 能干什么)**:
- 对 ss.fx8.store 等域做反复缓存清除 → 用户在缓存自然有效期(最长 4h,LOW_FREQ 档)内反复回到"刚清空"状态,首次访问回源变慢(可用性轻微影响)。
- 关键文件(overview/intraday_snapshot 等 NO_CACHE ttl=0)根本不进缓存(headers.js:192),**purge 对它们无效**——数据一致性核心文件不受影响。
- 无数据篡改、无数据泄露、无法读取任何私有数据(站点数据全部公开)。

### 1.4 轮换方案(只给方案,不执行)

**改动 4 处(全部登记点)**:

| # | 位置 | 动作 | 风险点 |
|---|---|---|---|
| 1 | CF Worker `env.PURGE_SECRET` | `npx wrangler secret put PURGE_SECRET`(本地 wrangler 或 GH Actions 手动 job;CLOUDFLARE_API_TOKEN 认证) | **必须最先做**:worker 认新值后,旧值即失效(旧值调 purge → 403 拒绝) |
| 2 | 本地 `/Users/linhuichen/code/trade/.env` | 改 `PURGE_SECRET=<新值>`(64 位 hex) | 改错=本地 upload_r2.py 调 purge 403;连带本地 deploy 流程告警 |
| 3 | 本地 `/Users/linhuichen/code/trade-data/.env` | 同上 | 同上(两处 .env 必须同步一致,§22 一致性铁律) |
| 4 | 云上 `/home/ubuntu/code/trade-data/.env` | 同上 | **云上才是生产运行时**:定时任务(deploy/upload)从这读;不同步=生产 purge 403 → 用户看旧数据窗口变长 |

**顺序铁律**:先 `wrangler secret put`(1),再同步三处 .env(2/3/4),最后验证。**反序(先改 .env)会在窗口期造成 upload_r2.py 用新值调 worker 旧值 → 全部 403 → 清缓存失败 → 用户读旧数据最长 4h**,并有严重告警邮件发出。

**额外注意**:
- 不改 wrangler.jsonc(secret 独立,`wrangler deploy` 不覆盖 secret;GH Actions 部署不会冲掉已 put 的 secret——官方 secret 生命周期独立)。
- 不删 git 历史(旧值仍在 public 仓历史可提取,但**轮换后旧值即失效,历史残留无害**,无需 force push)。
- 改前先备份 4 处旧值到安全位置(如本机 `~/Desktop/` 加密区或 `config/` 外文件),验证失败可逐处恢复(回滚路径)。
- 生成新值:64 位 hex,如 `openssl rand -hex 32`。
- **执行时机**:休市日/23:00 后安全窗口(§14)。2026-10-03(周六)全天休市,是理想窗口;10-08 前均无盘中任务。轮换本身约 10 分钟,一次 shutdown。

**验证方法(改完后必须做)**:
1. 新值生效:`curl -X POST https://ss.fx8.store/api/purge-cache -H 'Content-Type: application/json' -d '{"secret":"<新值>","keys":["/data/__hc_rotate_test__.json"]}'` → **期望 200 `{"purged":1}`**(不存在 key 也幂等返回 purged=1,无害,正好用于验证)。
2. 旧值失效:同命令带旧值 → **期望 403 `{"error":"Forbidden"}`**。
3. 业务链路:云上 `python3 scripts/upload_r2.py purge-low-freq`(或等下次 deploy)→ 日志「purged: N keys」无 403/告警。
4. 三查(§8):本地/云上 .env 新旧一致 + worker 新值 + 线上 purge 200,三处全对才算 done。

### 1.5 建议:今天轮换(理由)

| 选项 | 理由 | 结论 |
|---|---|---|
| **今天轮换(2026-10-03,国庆休市窗口)** | 值公开 21 天仍在用;轮换成本低(4 处改动+3 个验证,~10 分钟);休市窗口无盘中数据一致性压力;验证失败可回滚 | **推荐** |
| 本周内(10-08 前) | 若今天不便,休市期任何一天均可;10-09 开盘后轮换则多一次盘中风险窗口 | 次选 |
| 长期保留+定退役日 | 危害有限(仅清缓存+轻微回源成本),但「公开 21 天且仍在用」的凭证在 public 历史可提取,无必要持续承担;且 09-12 拍板「不轮换」至今已 21 天未执行,退役日难落地 | 不推荐(除非用户明确接受并给时点) |

**补充提示(报告外建议)**:`HEADERS/worker` 的 secret 不止 PURGE_SECRET——`SUBSCRIBE_PASSWORD/_SESSION_SECRET/GITEE_CLIENT_SECRET` 是否也在 public 历史泄漏过,本次未核查(超出任务范围),建议后续按 D7 同法(git log -S)扫一遍并纳入轮换评估。

## 问题 2:public_fund.db.bak 10G 残留来源

### 2.1 精确位置/大小/mtime/属主(云上实测 2026-10-03 20:17)

每仓 2 个大文件 + 2 个伴生,共 10G(非 D1 报告的「各 5G 单一文件」,实际为双仓 × 2 文件):

| 路径(两仓各一份) | 大小 | mtime(精确秒) | 属主 | sha256 |
|---|---|---|---|---|
| `trade-data/data/public_fund.db.bak-20261003_104704` | 2,670,219,264B(2.49G) | 10:47:13.75 | ubuntu | `dda553c3…` |
| `trade-data/data/public_fund.db.wal-20261003_104704.bak` | 2,670,219,264B(2.49G) | 10:47:38.37 | ubuntu | `8509b421…` |
| `trade-data-signal/data/public_fund.db.bak-20261003_104704` | 同左 | 同左 | ubuntu | `dda553c3…`(**与主仓逐位一致**) |
| `trade-data-signal/data/public_fund.db.wal-20261003_104704.bak` | 同左 | 同左 | ubuntu | `8509b421…`(与主仓逐位一致) |

另伴生:`public_fund.db.wal-…bak-shm`(32768B,16:31 仍被 touch)+ `-wal`(0B)。
内容验证(只读 python3 sqlite3):两文件均为合法 SQLite format 3;`fund_basic=27758`、`fund_score=354929`(两份一致);现行库(16:01 刷新)`fund_score=356929` → **备份是当天 10:47 的完整有效快照**。

### 2.2 来源:坐实手工操作(用户本人),非脚本,非安全事件

**判定依据链(全部实测)**:
1. **时间吻合**:`.bak` mtime 10:47:13.75 / 10:47:38.37,与云上 auth.log 同时段 ssh 会话严丝合缝:
   - `10:46:10 sshd[3884677] Accepted publickey for ubuntu from 61.170.217.75 (port 1568, RSA SHA256:AEfT73jpZzNWYT+c+DHewqyambe0Rjcm/v+aEiKlGrs)` → 10:46:39 断开,session-46604 消耗 **16.996s CPU**(重活:备份 2.5G db);
   - `10:47:04` session-46607 建立 → 10:47:13 断开(2.767s CPU)= 文件 1 mtime 10:47:13;
   - 10:47:28 session-46609 建立(下一笔)= 文件 2 mtime 10:47:38 前 10 秒内。
2. **来源 = 用户本人**:本机实测 `ssh-keygen -lf ~/tdsignal.pem` = `SHA256:AEfT73jpZzNWYT+c+DHewqyambe0Rjcm/v+aEiKlGrs` —— **与 auth.log 完全一致**;本机当前公网 IP curl 实测 = `61.170.217.75` —— **与会话来源 IP 相同**(上海电信家宽段)。即:该时段连接来自用户自己的 mac(用生产 key tdsignal.pem)。
3. **非脚本生成**:本地 + 云上全仓 grep `public_fund.db.bak` 命名模式 → 无生成者;`backup_db.sh`(云上+本地同源)明确只备 sentiment/etf_national_team 两表且命名风格为 `name_STAMP.db`(L47),与 `.bak-20261003_104704` 不符;当天 10:47 无任何定时任务(journal 仅 root CRON 心跳 + trade 常规 timer,10:45/10:46/10:47 无 trade 任务触发)。
4. **双仓逐位一致** = 用户对两仓分别执行相同备份命令(或备份后复制到镜像仓),符合手工一次性备份特征(命名 STAMP=`20261003_104704` 分钟级时间戳,手工风格)。
5. 生成方式推断:文件为合法 SQLite + 带 `-shm/-wal` 伴生 → 为 SQLite 在线备份(Python `Connection.backup()` 或 `VACUUM INTO`)产物,非 `cp`(cp 不产生伴生文件)。云上无 sqlite3 CLI(实测 `command not found`)→ 大概率是 python3 sqlite3 或用户本机脚本经 ssh 执行。
6. 云上 `~/.bash_history` 最后记录停在 09-30 11:07(无 10-03 记录)→ 用户或经非交互 ssh 单发命令,不写 bash_history(不矛盾)。

**结论:排除定时任务/脚本/入侵;坐实 2026-10-03 10:47 用户本人手工备份**。与 D1 报告「疑似手动备份,需人工确认来源」的悬置结论一致,本次已销案。

### 2.3 备份层覆盖判断

- D6 结论(10-03):**public_fund.db 无任何异地备份**(R2 两桶枚举 0 key、git 排除、云上 3 处副本同机、本机副本停 9-13)。
- 这份 `.bak` 是**当前唯一一份额外时间点快照**(10-47 点,与现行 16:01 库差 ~2000 行 fund_score)。
- 但它也在**同一台云机**上(双仓 + 静态仓副本都在 `/home/ubuntu/code/`),**不满足「异地」**,盘毁时与主库同毁。
- **磁盘含义**:可用 11G(10-03 18:25 实测)中 10G 被这 4 个文件占掉 → 保留则可用仅 ~1G,本周内写满风险(与 D1 结论一致)。

### 2.4 建议:不可直接删(先补异地备份再删);恢复路径

**判定:需先补备份再删(§25 触发)**。理由:删除对象(唯一额外快照)当前无任何异地等价物;直接删 = 把「双保险」降回「单保险」,而 D6 P0(public_fund.db 无异地备份)本来就是悬置待办的 P0。

**建议执行顺序**:
1. **先补异地备份(解决 D6 P0-1,本任务窗口内可做)**:将 public_fund.db 纳入 `upload-db` 目标(扩展 `scripts/backup_db.sh` 或走 R2 大文件通道;2.76G gz 后预计 15-25min,21:00 备份窗口可容纳,非交易日无冲突);或至少「云上→本机每日 rsync」建一份异地副本。备份后按 D6 方法实测取回+md5/行数对账,验证可恢复。
2. **异地备份验证 PASS 后,两仓 4 文件可安全删除**(10G 全释放;文件已无保留价值——内容是 10-47 快照,与现行 16:01 库差异仅 ~2000 行,且异地副本是最新的)。
3. **若暂时不做 1,至少先删冗余**(立即腾 5G):镜像仓两份(sha256 与主仓逐位一致 = 纯重复)→ 删 `trade-data-signal/data/public_fund.db.bak-20261003_104704` + `.wal-…bak`;主仓两份保留作同机回退。
4. **保留决定说明(§25⑤)**:本 .bak 与 staticdata-old-mirror(8.3G,保留至 10-30)性质不同——mirror 是拍板保留的回退保险,.bak 是无主残留;但删除前必须先解决「唯一额外快照」的空窗。

**恢复路径(§25④ 一行命令)**:
- 取回:`/home/ubuntu/code/trade-data-signal/data/public_fund.db.bak-20261003_104704`(任一仓,双仓逐位一致)。
- 恢复:`sudo systemctl stop <trade-写public_fund的service>` 后 `cp public_fund.db.bak-20261003_104704 public_fund.db`(或 python3 sqlite3 导入);数据 = 10-03 10:47 快照(比现行少 ~2000 行 fund_score,恢复后需重跑当日基金评分同步)。
- **诚实标注:同机副本,防不了盘毁;盘毁 = 与主库同失(除非先完成步骤 1 的异地备份)**。

## 复现段(本报告全部证据命令,可重跑)

```bash
# === 问题 1:代码证据 ===
sed -n '276,301p' worker/headers.js                    # purgeCacheHandler 全文(唯一 purge 入口)
grep -n "env.R2_BUCKET" worker/headers.js              # 仅 157/241 读代理,无写
grep -n "PURGE_SECRET" scripts/upload_r2.py | head -5  # purge_cache 读 .env + 分批 POST
# === 问题 1:官方文档(2026-10-03 curl 直连) ===
curl -s -H "Accept: text/markdown" https://developers.cloudflare.com/workers/runtime-apis/cache/ | grep -i "only purges content of the cache in the data center"
curl -s -H "Accept: text/markdown" https://developers.cloudflare.com/cache/how-to/purge-cache/ | grep -B2 -A6 "Token bucket rate limiting"
curl -s -H "Accept: text/markdown" https://developers.cloudflare.com/r2/pricing/ | grep -A8 "Class A operations\|Class B operations"
# === 问题 2:云上 .bak 实况(只读 ssh) ===
ls -la /home/ubuntu/code/trade-data/data/public_fund.db.bak* /home/ubuntu/code/trade-data-signal/data/public_fund.db.bak*
stat -c "%n %s %y" /home/ubuntu/code/trade-data/data/public_fund.db.bak-20261003_104704
sha256sum /home/ubuntu/code/trade-data/data/public_fund.db.bak-20261003_104704 /home/ubuntu/code/trade-data-signal/data/public_fund.db.bak-20261003_104704   # 双仓逐位一致
# python3 sqlite3 只读验证表行数(fund_basic=27758/fund_score=354929;现行=356929)
# === 问题 2:ssh 会话证据 ===
awk '/Oct  3 10:4[5-9]/{print}' /var/log/auth.log       # 10:46:10 Accepted publickey(61.170.217.75)
journalctl --since "2026-10-03 10:44:00" --until "2026-10-03 10:48:30" --no-pager | grep -iE "sshd|session"  # session 46604 16.996s CPU
ssh-keygen -lf ~/tdsignal.pem                            # SHA256:AEfT73jpZzNW...(与 auth.log 一致)
curl -s https://api.ipify.org                            # 61.170.217.75(=会话来源 IP)
```

## 诚实标注

1. **integrity_check 未完成**:2.5G×2 文件的 `PRAGMA integrity_check` 在 120s 超时后转后台,至本报告落笔未返回;表级验证(可连接、可读表、行数与现行可对比)已足够支撑「合法有效快照」结论,完整性为补充项,可后续复跑。
2. **社区先例未取得**:WebSearch/DDG/HN Algolia/jina/CF AI Search 全链路受限(与本仓 r2-billing 报告同况);「purge 凭证泄露滥用后果」判定完全基于 CF 官方文档一手原文 + 本仓代码证据,无第三方案例佐证——官方文档已覆盖限流/权限/能力边界/R2 计费口径,结论充分性不依赖社区。
3. **Worker 免费额度假设**:10-02 账单仅 R2 一行费用 → 推断 Worker 在免费额度内;未登录 CF 控制台核实具体计划(Free/Standard),不影响结论方向(两个计划免费请求额度分别为 10 万/天与 10M/月,均远高于攻击量级)。
4. **备份方式推断**:带 `-shm/-wal` 伴生 = SQLite 在线备份/`VACUUM INTO` 类,非 `cp`;具体命令无法从日志还原(非交互 ssh 无命令记录),为技术推断非实证。
5. **D1 报告口径修正**:D1 描述「双仓各 5G」,本报告细化 = 双仓各 2 文件(2.49G+2.49G);不影响 D1 处置结论。
6. 报告未含任何 secret 明文;PURGE_SECRET 值仅以 hash 指代(见 D7 同口径)。
