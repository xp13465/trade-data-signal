# 站点加载速度审计终审报告(opencode 测量 + codex 预审 + 主控终审)

> 日期:2026-08-31。触发:用户让 opencode 做站点加载速度统计与建议,codex 做了预审,主控(我)做终审并落档。
> 方法:主控不轻信任何一方结论,逐个磁盘实测 + 线上 curl 实测 + 读 worker/headers.js 缓存分层源码交叉验证。
> 三源:①opencode 响应时间报告 ②codex 预审意见 ③本终审(权威)。

## 〇、一句话结论

**opencode 的测量数字基本属实,但它的「P0 分片/压缩」建议方向对、落点错(它没搞清哪些是首屏、压缩已开);codex 预审抓数据真实性大方向对,但它在两个关键事实上错了(position.json 说成不存在、总数据量口径误判)。真正的瓶颈既不是文件大小也不是压缩,而是「中国→CF 远端边缘节点 + 盘中文件 no-store 每次回源」的网络往返延迟——这是唯一真实、可优化的核心问题。**

---

## 一、数据真实性三方核验表

| opencode 声称 | codex 预审判定 | **主控实测** | 终审判定 |
|---|---|---|---|
| etf_score_list_hold=7.8MB | 属实 7.8MB | **7.07MB** | opencode 约+10%,codex 也没核实准;均轻微偏高,非关键 |
| overfit_monitor=3.8MB | 属实 | **3.89MB** | ✓ 属实 |
| overview=1.6MB | 属实 | **1.60MB** | ✓ 属实 |
| boot=2.3MB | 属实 | **2.29MB** | ✓ 属实 |
| position.json=1.4KB | **「磁盘不存在此文件,不属实」** | **存在,1440B** | ⚠️ **codex 误判**。position.json 真实存在(1.44KB)。它属于 HIGH_FREQ ttl=60 组(worker/headers.js L200) |
| 总数据量 22.7MB | 「实测 1.7GB,严重不属实」 | data/ 目录 **1.6GB** | ⚠️ **口径不同非撒谎**。22.7MB=opencode 实际请求的 38 个端点合计;1.6GB 含 fund_nav(567M)/trade_sim(371M)/signal_kelly_trades_parts(159M) 等懒加载/按需分片目录。两者不是同一个数,不是矛盾 |
| 0 端点 <500ms | 「测试脚本有问题,可疑」 | **实测确认:最小文件也慢** | ✓ opencode 属实。position.json 393B(压缩后) 仍 **2.36s** |
| 平均 1774ms / P90 3106ms | 未直接质疑 | 实测:overview 3.24s / boot 2.35s / hold 3.85s / position 2.36s | ✓ **量级吻合**,opencode 测量可信 |

**核验结论:**
- **opencode 的测量数据可信**(我的线上实测和它量级一致,连 position.json 这个最可疑的"小文件也慢"都复现了)。
- **codex 的两处核心质疑(假端点/数据量撒谎)都站不住**——position.json 真实存在,总数据量是口径差非造假。codex 在「数据真实性」这个它声称要纠错的点上,自己反而错了。

---

## 二、关键架构事实(主控读源码确认)

**worker/headers.js 缓存分层(dataCacheTtl):**
- `overview.json` → **ttl=0(no-store,每次回源 R2)**。盘中高频实时数据,刻意不缓存防旧版(2026-08-09 事故根治)。代价=每次回源。
- `boot.json` → **ttl=60**(HIGH_FREQ 盘中 60s)。
- `overfit_monitor.json` → **ttl=600**(MED_FREQ,2026-08-24 拆分优化后从 no-store 挪到 600s)。
- `etf_score_list_hold/buy.json` → **ttl=3600**(LOW_FREQ 默认)。
- `position.json` → **ttl=60**(HIGH_FREQ,盘中实时)。

**压缩:已全量开启 brotli。** 实测 `content-encoding: br`:
- overview.json 1.6MB → **131KB 传输**(~92% 压缩)
- etf_score_list_hold.json 7MB → **713KB 传输**
- boot.json 2.3MB → **264KB 传输**

**加载归属:**
- **首屏**:boot.json(单 fetch 合并 11 个 JSON,P1-8)+ overview.json。
- **懒加载(tab 点击才拉,非首屏)**:etf_score_list_hold.json(app.js L24614「初次调用 fetch」,~13MB br~783KB,走 R2 路由 1h 缓存)、overfit_monitor.json(AI 监控卡 tab,ttl=600)。
- **R2 路由(/r2/)** 单独 1h 边缘缓存,与 /data/ 分层不同。

---

## 三、为什么慢——真正的根因(实测证据)

**瓶颈 = 网络往返延迟,不是字节数。** 铁证:
- position.json 压缩后 **393B**,耗时 **2.36s** —— 393 字节不可能"下载慢",纯粹是「中国客户端 → CF 边缘节点 → 回源 R2」的往返延迟。
- cf-ray 显示请求落在 **CDG(法国巴黎)** 边缘节点 —— 从中国大陆到欧洲边缘的跨洋 RTT 就是 ~300-500ms,且 no-store/首拉 miss 都要回源,几个往返叠加出 2-3s。
- 因此 opencode/codex 的「P0 分片/压缩」作为**降延迟**手段是无效的:分片只减少每次传输字节,减少不了「中国→CF 往返」这个常数。

---

## 四、建议逐条裁决(opencode 7 条 + codex 复述)

| # | 建议 | 优先级(opencode) | **终审判定** | 理由(实测依据) |
|---|---|---|---|---|
| 1 | overview.json 分片(首屏只拉摘要) | P0 | ⚠️ **方向对落点偏** | 它是首屏且 no-store 每次回源,是真首屏成本。但 1.6MB→131KB 已压缩,分片省的是回源后的解析,不省往返延迟;真正可做的是**首屏延迟加载非首屏字段**或**把 no-store 降为 short-TTL+purge 补偿**(见方案) |
| 2 | etf_score_list_hold 压缩/分页 | P0 | ✗ **误判(懒加载非首屏)** | 已 br 压缩 7MB→713KB;**且是 tab 点击懒加载,不是首屏阻塞**。opencode/codex 都没确认加载归属就标 P0,落点错。分页可做但非 P0 |
| 3 | boot.json 瘦身 | P1 | ⚠️ **部分可做** | 首屏真实。但它是 11 文件合并的 P1-8 优化产物,拆分=回退优化。可做的是把真正非首屏字段移出 boot |
| 4 | CDN 边缘优化(Argo Smart Routing) | P1 | ✅ **最有价值的一条** | 直击真根因(跨洋往返)。但 Argo 要付费;免费替代=CF 大陆优化/优选 IP/hosts 固定 CF IP(memory dns-hijack-hosts-rootfix 已有先例) |
| 5 | 数据预加载(点 tab 前预取) | P2 | ✅ **真有效** | 对懒加载的 etf_score/overfit 最有效,感知提速明显 |
| 6 | gzip/brotli 确认 | P2 | ✗ **已做完** | 实测 br 已全量开启,1.6MB→131KB。这条无活可干 |
| 7 | SW 缓存策略(SWR) | P3 | ⚠️ **次访问提速** | 对二次访问有效;需小心与 no-store 关键文件的一致性(§22)冲突 |

---

## 五、我的优化方案(按真实根因排序)

**核心矛盾:首屏成本 = overview/boot 的「no-store 每次回源 × 跨洋往返」。**

**方案 A(推荐,低成本高收益):针对真根因的 3 件**
1. **盘后 overview 降级 short-TTL + purge 补偿**(替代无脑 no-store):盘后 15:00 收盘后 overview 数据定型,盘中才高频变。盘中维持 no-store(防旧版),**盘后(用户高峰前)切 60-300s TTL + 上传后 purge**——省掉盘后每次回源。预估首屏盘后提速 1.5-2s。
2. **首屏字段拆分**:overview 拆「首屏摘要字段」+「详情字段」,首屏只拉摘要(小),详情等交互。这个才是 opencode 建议的正确落点。
3. **CF 大陆路径优化**:优选 IP 或固定 CF 边缘(hosts 已先例),减少跨洋 RTT。Argo 若可接受付费则更直接。

**方案 B(体验层,成本低)**
4. **tab 预取**:在用户 hover/靠近 etf_score、AI 监控卡 tab 时预取 hold/overfit 数据,点击即显。
5. **SW 二次访问缓存**:对低频懒加载文件(etf_score_list_hold 等 ttl=3600)做 SW 缓存,二次访问零回源。

**明确不做(误判或已做完):**
- ❌ etf_score_list_hold 当 P0 首屏阻塞处理(它懒加载,已压缩)。
- ❌ 再做 gzip/brotli(已全量 br)。
- ❌ boot 拆分回退 P1-8 合并优化。

---

## 五.5、终审后用户拍板(2026-08-31 二次会议)

用户决策:**只做第一件(tab 预取),免费,低风险;第二件(overview 拆分)与第三件(CF 路径)不做。**
- 第三件(CF 路径优化)= 影响所有用户,顾此失彼,用户明确不做。
- 第二件(overview 首屏字段拆分)主控补做了**量化好处估算**(见下),结论=好处很小,不建议,用户采纳。

### 第二件好处量化估算(为什么不做,数据说话)
拆 `overview.json` 各顶层 key 字节占比:
- **`signals_today` = 86.1%(1,513KB)**,443 条,近30交易日全量信号。
- 其余所有字段合计仅 **13.9%(~245KB)**(6m 走势/KPI 等次要字段)。

**结论:overview 拆分好处几乎不可感知**,因为 86% 的 signals_today 本身就是首页首屏本体:
- 今日信号网格(今日 10 条)+「近期技术分析参考点近30交易日」+ 近30交易日 AI建议 top-K(L5509 扩展到整个信号列表)均首屏。
- `app.js L1578` 确认:每日期全部显示不做折叠,同步渲染,DOM 全量(仅 max-height+overflow 滚动兜底)——数据必须首屏一次全拿,无法懒。
- 能拆出去的只有 13.9%(~245KB, 压缩后约 20KB 传输),这点节省完全被「跨洋往返 2-3s」常数淹没。
- **性价比**:中等风险(动数据层/§22 一致性)+ 收益不可感知 = 全表最差,不做。opencode/codex 均标 P0 大推,但真实数据证明是伪优化(他们未意识到 signals_today 86% 即首屏本体)。

### 第一件(tab 预取)落点与方案
- `etf_score_list_hold.json`:tab 首次渲染才拉(app.js L24614),R2 路由 1h 缓存。
- `overfit_monitor.json`:AI 监控卡 tab(app.js L2153 已有共享 promise)。
- 方案:tab 切换/hover 时后台预取(不阻塞渲染),点击即显;纯前端、不改数据、不碰 §22,可回滚。

## 六、真问题 vs 误判总结

**真问题(建议修):**
1. **overview/boot 首屏 no-store 每次回源 × 跨洋往返 = 2-3s 首屏延迟**(最真实、最可优化)。
2. **首屏字段未拆分**(overview 详情字段拖首屏)。
3. **懒加载大文件无预取**(etf_score hold/overfit 首次点击体验差)。

**误判/不重要(可不管):**
1. ❌ etf_score_list_hold "P0 首屏阻塞" —— 实际懒加载。
2. ❌ "gzip/brotli 压缩确认" —— 已全量 br 开启。
3. ❌ codex 说 position.json 不存在 —— 实际存在。
4. ❌ codex 说总数据量撒谎 —— 口径不同非造假。
5. ❌ boot 拆分(回退既有 P1-8 优化)。

---

## 复现(本报告)

- **磁盘文件核验**:`cd static-site/data && ls -la etf_score_list_hold.json overfit_monitor.json overview.json boot.json position.json` 与 `du -sh .`。
- **线上压缩+耗时**:`curl -A "Mozilla/5.0" -s -D - -o /dev/null -H "Accept-Encoding: gzip, br" https://ss.fx8.store/data/overview.json`(看 content-encoding:br 与 time_total)。
- **缓存分层源码**:`worker/headers.js` `dataCacheTtl()` L168-205。
- **懒加载归属**:`static-site/app.js` L24614(etf_score_list_hold 初次调用 fetch)。
- **数据截止**:2026-08-31 盘中,CF 边缘=CDG(巴黎)。
