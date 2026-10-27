# s.sugas.site 未压缩:根因与开启方案(只读调研)

- 日期:2026-10-25
- 性质:只读调研 + 方案。**未改任何配置/代码/Worker,未 purge 缓存,未部署。**
- 任务书:`/tmp/task-s-compress-20261025.md`
- 测量口径:体积一律用 `curl -w '%{size_download}'` 实测。**压缩时 CF 会省略或改写 `Content-Length`,不能拿它当压缩后体积**;本报告已按此纠正(见附录 C)。
- 一句话结论:**s.sugas.site 的客户端边缘是第三方帽子云(MaoziYun 3.18.0),不是我们的 Cloudflare zone;帽子云静态托管链路对 9/9 资源不做内容编码/协商,把存储层原始字节原样回给浏览器。我们的 CF 压缩能力完全不在这条链路上。** 这不是"我们的 CF 开关没打开",也不能在 CF 控制台给 s 开压缩。

## 0. 摘要

### 0.1 根因一句话

s.sugas.site 前面没有我们的 Cloudflare:`server: MaoziYun/3.18.0`、客户端 IP 104.233.148.233(AS54600 PEG TECH)、`/cdn-cgi/trace` 返回帽子云自己的 JSON 404;9/9 首屏资源在 `Accept-Encoding: gzip, deflate, br, zstd` 下都没有 `Content-Encoding`、没有 `Vary`,原样输出 1,671,414 B。项目代码 `static-site/app.js:9688` 和 `NOTES.md` 小节 O/S 早已记录同一结论:"MaoziYun 不支持 Content-Encoding"。

### 0.2 收益实测(9 个首屏资源:index + app.min.js + common.min.js + i18n.js + inline-init.js + purpose-notes.min.js + qr.js + style.min.css + lab.min.css)

| 口径 | 合计字节 | 相对 s 原始 | 省下 |
|---|---:|---:|---:|
| s.sugas.site 原始(identity) | 1,671,414 | 100.0% | - |
| ss.fx8.store,Brotli(AE: br) | 465,452 | 27.8% | 1,205,962 |
| ss.fx8.store,Zstandard(Chrome 全 AE) | 481,538 | 28.8% | 1,189,876 |
| sss.sugas.site,Gzip | 484,677 | 29.0% | 1,186,737 |
| 本地 gzip -9 全量(理论上限参考) | 478,894 | 28.7% | 1,192,520 |
| 本地 brotli -q11 全量(理论上限参考) | 370,702 | 22.2% | 1,300,712 |

说明:

- 任务书的 `1,672,352 B` 用的是 **ss 侧 HTML(39,507 B,含 CF 注入的 bot 脚本)**;s 自己的 HTML 是 38,569 B,所以 s 侧 9 资源合计是 **1,671,414 B**,差 938 B 是 CF 注入的 HTML,不是资源内容差异。
- 任务书的 `481,573 B` 与本次 zstd 实测 481,538 B 只差 35 B,属动态压缩正常波动;br 口径更低(465,452 B),三个压缩口径都约 -71%~-72%。
- 本地 `brotli -q11` 的 370,702 B 是"构建期最高档"理论上限,不是 CF 动态压缩的实际值(CF 的 br 对 app.min.js 实测 318,665 B,本地 br11 是 254,386 B);不要拿 370,702 当线上承诺。

### 0.3 推荐(按优先级)

1. **首选:向帽子云申请开压缩(零代码、满收益)。** 请求它对静态托管的 `text/html`、`text/css`、`text/javascript`/`application/javascript` 开 gzip/brotli,并补 `Vary: Accept-Encoding`;或允许自定义响应头 / 预压缩 `.gz` + `Content-Encoding`。依据:同一批字节在 ss.fx8.store 压到 465,452 B;帽子云自己的官网(Next.js)就返回 `content-encoding: gzip`(server 同样是 MaoziYun/3.18.0),说明其边缘链路具备 gzip 能力,只是静态托管产品没给用户站点开/没暴露开关。其官方文档站检索不到"压缩/gzip/brotli/响应头"任何说明,支持入口是微信 `maozicdn`,必须问。
2. **若帽子云拒绝,且 s 站必须保留"独立于 CF 的备站"定位:客户端 `.gz` + `DecompressionStream`(方案 E)。** 项目已用同一套机制跑通过数据 JSON(NOTES 小节 S:`.json.gz` 返回 200 + 前端解压),可复用到 `app.min.js`。分三期:只压 app.min.js → 首屏 922,011 B(-44.8%);再压全部 6 个首屏 JS → 821,100 B(-50.9%);再压 2 个 CSS → 504,145 B(-69.8%)。CSS 需要注入 `<style>`,有 FOUC 风险,放第二期。
3. **若 s 站的定位可以改变、且愿意把 s 交给 CF:CF 前置(方案 B),满收益 465,452~481,538 B。** 但 s 会从"独立于 CF 的第三家备站"变成"CF 前置",与 ss 共因失效;CF for SaaS 的 custom origin/SNI rewrite 在非 Enterprise 有限制,zone move 又会影响 `sugas.site` 整个 zone(含 sss),必须先小号验证。
4. **不推荐:**
   - 方案 C(Worker 内压缩)单独用:要么依赖 B 的前置,要么只是给 ss 做资产代理;CF 本来就会自动压缩,手工 `CompressionStream` 只有 gzip/deflate,反而丢掉 br/zstd。
   - 方案 D(构建期 `.br/.gz` + `Content-Encoding`)单独用:帽子云不给我们设 `Content-Encoding`,浏览器不会解压,等于让用户下载一个二进制文件;CF 侧又不需要。
   - 方案 F(首屏裁剪)单独用:9 个资源首页都在用(purpose-notes 在 `app.js:16016` 首屏渲染时就要用,qr 在 `app.js:32980` 用,lab.min.css 里有 618 个 `lab-sigkelly/etf-pin` 选择器被首页 K 按钮/ETF 弹窗使用),裁剪需要拆 CSS/JS,收益远小于压缩。
   - 方案 G(整体迁走帽子云)单独用:能解决,但改变 s 的部署/线路/成本,不作为第一优先。

### 0.4 对任务书前提的修正(诚实标注)

- "开压缩可省约 1.19MB(-71%)"——**字节数成立**,三个压缩口径实测 -71.0%~-72.2%。
- "属成本低、风险低的第一优先性能项"——**只对 ss.fx8.store / sss.sugas.site 成立**(它们已经压缩了);对 s.sugas.site **不成立**:s 不在我们的 CF zone,没有"打开自动压缩"这个开关。对 s 来说,零代码路径只有"求帽子云";否则要么改架构(CF 前置),要么写客户端解压(中高工程风险)。
- 本报告不是实施单。任何一项落地前,按 §5.7 的"依据 + 实现预期 + 证据用例"逐条验;对不上判方案失败,不按"完成度打折"放过。

## 1. 架构实测:三个域名前面各是什么

### 1.1 测量方法

- 全部用 `curl -sS -o /dev/null -D -` / `-w` 取响应头与 `size_download`,**禁 `-v/-i`**(任务书铁律)。
- 统一浏览器 UA:`Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36`。
- s 站本机 DNS 被代理 fake-IP 到 `198.18.0.x`,所以对 s 用 `--resolve s.sugas.site:443:104.233.148.233` 直连真实 IP;ss/sss 的 `/etc/hosts` 已固定到 CF/GitHub IP(`/etc/hosts:19-23`),不受 fake-IP 影响。
- 用 DoH(`https://dns.google/resolve`)复核 CNAME/A,避开本机 fake-IP。
- 用 `/cdn-cgi/trace` 判定客户端边缘是不是 Cloudflare:CF 会返回自己的 trace;不是 CF 的站点会返回自己的 404/页面。
- 关键坑:`Content-Length` 在 CF 压缩时会被省略(实测 zstd/br/gzip 都没有 `content-length`),所以**压缩后体积必须用 `size_download`**,不能用 `content-length`。

### 1.2 三域名总表

| 项 | ss.fx8.store | sss.sugas.site | s.sugas.site |
|---|---|---|---|
| DNS | A 104.21.46.172 / 172.67.168.203(Cloudflare anycast) | CNAME `xp13465.github.io` → 185.199.108-111.153 | CNAME `cname.maozi-dns.com` → 104.233.148.233 |
| 客户端边缘 | Cloudflare(CF Workers Static Assets) | GitHub Pages(Fastly) | 帽子云 MaoziYun 3.18.0 |
| 边缘 IP/ASN | 104.21.46.172(CF) | 185.199.108.153(GitHub) | 104.233.148.233,AS54600 PEG TECH(本次 ipinfo 显示 San Jose) |
| `/cdn-cgi/trace` | 200,CF trace(`fl=... h=ss.fx8.store ...`) | 404,GitHub Pages 404 页面 | 307 + JSON `{"code":"not_found","message":"File with such name does not exist.","status":404}`(帽子云自己的 404) |
| `server` | `cloudflare` | `GitHub.com` | `MaoziYun/3.18.0` |
| `cf-ray` | 有(本次 `...-HKG`) | 无 | 有(`...-SJC`,上游透传,不代表客户端边缘是 CF) |
| `cf-cache-status` | assets `HIT`;HTML `no-store` | 无 | `MISS`(上游跳) |
| `my-cache-status` / `my-request-id` | 无 | 无 | `HIT` / `...-san-1` |
| `content-encoding`(全 AE) | `zstd`(Chrome 全 AE);AE 只给 br 时 `br`;只给 gzip 时 `gzip` | `gzip` | **无** |
| `vary` | 无(但 CF 内部按 AE 协商,仍压缩) | `Accept-Encoding` | **无** |
| `content-length` | 压缩时省略;`AE: identity` 时 1,090,838(app.min.js) | 343,877(app.min.js,gzip) | 1,090,838(app.min.js);HTML 无 content-length(分块) |
| `cache-control` | assets `public, max-age=31536000, immutable`;HTML `no-store, max-age=0` | `max-age=600` | `max-age=1200`(帽子云默认,`_headers` 被忽略) |
| `content-type` | `text/javascript` / `text/css` / `text/html` | `application/javascript; charset=utf-8` / `text/css; charset=utf-8` / `text/html; charset=utf-8` | `text/javascript;charset=utf-8` / `text/css;charset=utf-8` / `text/html;charset=utf-8` |
| 上游存储/回源 | CF Workers Static Assets(`wrangler.jsonc` assets directory `./static-site`)+ R2 binding | GitHub Pages | 上游疑似 Backblaze B2(响应带 `x-bz-server-side-encryption: AES256`),经一跳 Cloudflare(`cf-ray`/`cf-cache-status`/`nel: report_to cf-nel` 透传) |
| 9 资源合计 | 1,672,352(raw)/ 465,452(br)/ 481,538(zstd) | 1,671,414(raw)/ 484,677(gzip) | 1,671,414(raw)/ **无压缩** |

### 1.3 ss.fx8.store:CF Workers Static Assets

仓库证据:

- `wrangler.jsonc:11-15`:`main` = `worker/headers.js`,`assets.directory` = `./static-site`,`assets.binding` = `ASSETS`,`run_worker_first: true`。
- `worker/headers.js:359-364`:普通静态请求走 `const response = await env.ASSETS.fetch(request);` 然后 `new Response(response.body, { status, statusText, headers })`。**全文件没有 Content-Encoding/gzip/brotli 代码**(grep 为空),Worker 只是复制/覆盖 headers,不做压缩,也没有设 `Cache-Control: no-transform`。
- `worker/headers.js:23-39` 的 `SECURITY_HEADERS` 只有 HSTS / nosniff / X-Frame / Referrer / Permissions-Policy / CSP-Report-Only,没有 `no-transform`。
- `worker/headers.js:41+` 的 `CACHE_RULES`:版本化 JS/CSS 1 年 immutable,HTML `no-store`;路径匹配不含 query(`?v=` 只用于换 URL)。

实测 `app.min.js`:

```
HTTP/2 200
content-type: text/javascript
cf-cache-status: HIT
cache-control: public, max-age=31536000, immutable
content-encoding: zstd
server: cloudflare
cf-ray: ...-HKG
```

同一 URL 换 AE:

| Accept-Encoding | content-encoding | size_download |
|---|---|---:|
| `br` | br | 318,665 |
| `gzip` | gzip | 341,742 |
| `zstd`(Chrome 全 AE) | zstd | 326,983 |
| `identity` | 无 | 1,090,838 |

结论:ss 的压缩是 **Cloudflare 边缘自动压缩**,不是 Worker 做的;`run_worker_first` 和 Worker 重建 Response 都不会阻止 CF 压缩。这也直接证明"Worker 复制 body/headers"本身不是压缩失效的原因。

### 1.4 sss.sugas.site:GitHub Pages + Fastly

证据:

- DoH:CNAME `xp13465.github.io.` → A 185.199.108-111.153。
- 响应头:`server: GitHub.com`、`via: 1.1 varnish`、`x-cache: HIT`、`age: 0`、`vary: Accept-Encoding`、`content-encoding: gzip`、`content-length: 343877`、`cache-control: max-age=600`。
- `/cdn-cgi/trace` 返回 GitHub Pages 404,不是 CF trace。

结论:sss 的 gzip 是 GitHub Pages/Fastly 自带;没有 Worker,也没有 R2 逻辑;它的动态数据走 `fetchJSON` 的 `_R2_FALLBACK_BASE` 回主站(`app.js:9655-9678`)。

### 1.5 s.sugas.site:帽子云(MaoziYun),客户端边缘不是 CF

证据(直连 104.233.148.233,带浏览器 UA + 全 AE):

```
HTTP/2 200
content-type: text/javascript;charset=utf-8
content-length: 1090838
date: Sun, 25 Oct 2026 08:22:13 GMT
strict-transport-security: max-age=63072000
nel: {"report_to":"cf-nel","success_fraction":0.0,"max_age":604800}
cf-cache-status: MISS
cache-control: max-age=1200
x-bz-server-side-encryption: AES256
last-modified: Sun, 25 Oct 2026 08:22:13 GMT
cf-ray: ...-SJC
server: MaoziYun/3.18.0
my-request-id: ...-san-1
my-cache-status: HIT
accept-ranges: bytes
```

要点:

- **没有任何 `content-encoding`**,即使请求明确带了 `gzip, deflate, br, zstd`;明确只带 `gzip` 时也没有;带 `identity` 时体积仍是 1,090,838。
- **没有 `vary`**。
- `cf-ray`/`cf-cache-status`/`nel` 是**上游存储/CDN 跳的透传**(同响应同时有 `my-cache-status`/`my-request-id`/`server: MaoziYun`),不能据此说客户端边缘是 CF;`/cdn-cgi/trace` 返回帽子云 JSON 404 是决定性反证。
- `x-bz-server-side-encryption: AES256` 指向 Backblaze B2 风格的上游存储(未直连验证存储厂商,只作为链路线索)。
- `cache-control: max-age=1200` 是帽子云默认;仓库 `static-site/_headers` 里给 app.min.js 配的 `immutable` 没有生效。`_headers:5` 自己就写明:"MaoziYun 不解析本文件,仅对 CF Pages / sss.sugas.site 生效"。
- s 的更新机制:帽子云自动拉取 git main(`scripts/deploy.sh:1006`)。历史上曾因 300MB 超限于 2026-07-22 停止拉取,同月把 `trade_sim/` 400 文件(275M)迁出 git 后恢复(`NOTES.md:3368`);本次实测 s 的 app.min.js sha256 与本地/ss/sss 全等,证明当前同步正常。

`/cdn-cgi/trace` 三个域名的结果:

| 域名 | HTTP | 响应 |
|---|---:|---|
| ss.fx8.store | 200 | CF trace(`fl=... h=ss.fx8.store ...`) |
| sss.sugas.site | 404 | GitHub Pages 404 页面 |
| s.sugas.site | 307 | 帽子云 JSON `{"code":"not_found",...,"status":404}` |

### 1.6 9 个首屏资源逐项实测

| 资源 | s raw | ss zstd | sss gzip | 本地 gzip -9 | 本地 br -q11 |
|---|---:|---:|---:|---:|---:|
| `/`(index.html) | 38,569 | 14,841 | 13,338 | 13,318 | 11,043 |
| `/app.min.js` | 1,090,838 | 326,983 | 343,877 | 341,435 | 254,386 |
| `/common.min.js` | 64,434 | 24,335 | 22,291 | 22,205 | 19,220 |
| `/i18n.js` | 19,421 | 5,689 | 5,351 | 5,314 | 4,396 |
| `/inline-init.js` | 3,184 | 1,755 | 1,644 | 1,659 | 1,302 |
| `/purpose-notes.min.js` | 76,473 | 37,307 | 34,631 | 34,540 | 30,442 |
| `/qr.js` | 1,516 | 427 | 403 | 399 | 335 |
| `/style.min.css` | 257,569 | 48,282 | 44,042 | 41,834 | 34,005 |
| `/lab.min.css` | 119,410 | 21,919 | 19,100 | 18,190 | 15,573 |
| **合计** | **1,671,414** | **481,538** | **484,677** | **478,894** | **370,702** |

补充:ss 侧 index 是 39,507(含 CF 注入脚本),把这一项换进去就是任务书的 1,672,352;ss 侧 9 资源 br 口径合计 **465,452**(27.8%),这是任务书/前次实测的数字,本次复测 zstd 为 481,538,二者都可用,差异来自编码算法。

### 1.7 三域名内容一致性

`app.min.js` 的 sha256 在本地和三域名完全一致:

```
5503942c6bf30bb5b90991a2cd6630281cc294a6c85f496bea6ff4c4967c2a3e  local app.min.js
5503942c6bf30bb5b90991a2cd6630281cc294a6c85f496bea6ff4c4967c2a3e  s   (直连,identity)
5503942c6bf30bb5b90991a2cd6630281cc294a6c85f496bea6ff4c4967c2a3e  ss  (--compressed)
5503942c6bf30bb5b90991a2cd6630281cc294a6c85f496bea6ff4c4967c2a3e  sss (--compressed)
```

结论:字节内容相同,ss/sss 小、s 大,纯粹是**传输层有没有压缩**;不是 s 的文件版本不同,也不是 s 的文件本身有问题。

## 2. 未压缩的确切根因

### 2.1 四个候选逐条排除

| 候选 | 判定 | 证据 |
|---|---|---|
| ① 源站/R2 存的就没压 | **事实前提,但不是根因** | s 的 `content-length` 等于本地文件字节(app.min.js 1,090,838),sha256 与本地一致;但同一批字节在 ss/sss 能压到 27.8%~29.0%,所以"存储未压"只能解释"没有预压缩",不能解释"传输也不压"。 |
| ② Worker 原样透传没让 CF 压缩 | **字面不成立(我们的 Worker);"第三方边缘原样透传"成立** | 我们的 Worker 确实原样透传(`worker/headers.js:359-364`),但 ss 仍然被 CF 压到 zstd/br/gzip,证明 Worker 透传本身不阻止 CF 压缩。s 前面没有我们的 Worker;透传方是帽子云。 |
| ③ CF 自动压缩对某些 content-type/大小/状态码不生效 | **排除** | s 的 content-type 是 `text/html`、`text/css`、`text/javascript`,全部在 CF 官方可压缩清单内;状态 200;最小 1,516 B、最大 1,090,838 B,远超 48/50 B 阈值;同样字节在 ss/sss 都被压缩。更关键:s 不在我们的 CF zone(`/cdn-cgi/trace` 不是 CF),"CF 自动压缩不生效"这个提法对 s 不成立——CF 不在客户端链路上。 |
| ④ 响应头(no-transform / Content-Length 缺失)导致不压 | **排除** | s 响应没有 `Cache-Control: no-transform`;app.min.js/common/CSS 都有 `Content-Length`(1,090,838 等)仍不压;index.html 没有 `Content-Length`(分块)也不压——两种情况都不压,说明不是 Content-Length 的问题。CF 官方文档明确:`no-transform` 才会阻止压缩;压缩时 CF 反而可能省略 Content-Length。`Vary` 缺失是"没做内容协商"的伴随现象,不是压缩失效的原因(ss 也没有 `Vary: Accept-Encoding`,照样压缩)。 |

### 2.2 最终判定

**根因 = 第三方客户端边缘不具备/未启用内容编码:**
s.sugas.site 的客户端接入层是帽子云静态托管(`server: MaoziYun/3.18.0`,客户端 IP 104.233.148.233 AS54600 PEG TECH,`/cdn-cgi/trace` 返回帽子云 404),它对用户站点原样输出存储层字节,不发 `Content-Encoding`、不发 `Vary`,也不做 `Accept-Encoding` 协商。我们的 Cloudflare 自动压缩完全不在 s 的链路上,所以:

- 不能通过 CF 控制台 / Compression Rules 给 s 开压缩;
- 不能在 s 的 `_headers` 里写 `Content-Encoding`(帽子云不解析 `_headers`,实测 app.min.js 的 `immutable` 没生效,只有 `max-age=1200`);
- 只能从三条路里选:让帽子云开(方案 A)、把 s 前置到支持压缩的边缘(方案 B)、或者客户端自己解压(方案 E)。

### 2.3 项目内既有证据(不是本次新发现)

- `static-site/app.js:9688`(commit `1caee6414`,2026-07-21):`// JSON gz 方案B/Y: 优先 .json.gz + DecompressionStream 解压(MaoziYun 不支持 Content-Encoding,前端显式解压)`。
- `NOTES.md:277-349`(小节 O,2026-07-21 全站性能扫描):"压缩 1/5:完全无 Content-Encoding,MaoziYun/3.17.0 不做 gzip/br";"首屏 ~466KB 可压缩到 ~140KB 省 70%+";结论"最大痛点 = MaoziYun 零压缩 + 不读 _headers";当时建议"P0/M 迁 CF Workers 启用自动 br 压缩"。
- `NOTES.md:472-477`(小节 S,2026-07-21):"MaoziYun/3.17.0 不支持 `Content-Encoding: gzip`(curl `-H "Accept-Encoding: gzip"` 返回无 content-encoding),无法走标准 HTTP 压缩通道";方案 B = `.json.gz` + 前端 `DecompressionStream`;当时线上验证 `.json.gz` 返回 200、`content-type: application/gzip`,前端解压成功。
- `NOTES.md:1492`:"`ss.fx8.store` 支持 `_headers` + br 压缩;`s.sugas.site`/maozi.io `_headers` 不生效"。
- `NOTES.md:1488`:app.js/lab.js 拆 chunk 的前期评估结论是"拆 chunk ROI 低",这影响方案 F 的优先级。

这说明:本次不是重新发现,而是把既有结论量化到 2026-10-25 的资源规模(当时 app.min.js 251KB,现在 1,090,838 B,放大了 4.3 倍,所以省 1.19MB 现在才这么显眼)。

### 2.4 帽子云侧的能力与文档

- 帽子云官网(https://www.maoziyun.com/)自己的 Next.js 站点返回:`content-encoding: gzip`、`vary: ... Accept-Encoding`、`server: MaoziYun/3.18.0`。说明**其边缘链路支持 gzip**,不是协议上做不到。
- 帽子云文档站(https://www.maoziyun.com/docs/)检索"压缩 / gzip / brotli / 响应头 / 客服 / 微信 / maozicdn"均为 0 命中(2026-10-25 抓取);公开文档没有"静态站点压缩开关"或"自定义响应头"的说明。
- 官网"联系我们"给的入口是微信 `maozicdn`(备注"帽子云"),说明支持要走人工。
- 结论:帽子云静态托管**当前没有给用户站点开压缩/自定义头**;是否愿意开、是否只对某些套餐开,必须问,不能闭门推断。

### 2.5 为什么不是"我们的 Worker 没让它压"

`worker/headers.js` 里没有任何压缩代码,也没有 `no-transform`;`env.ASSETS.fetch` + `new Response(response.body, ...)` 只是重建响应。ss 实测被 CF 压到 zstd/br/gzip,证明这条路本身是通的。s 的问题是**前面根本没有我们的 Worker/CF zone**,不是 Worker 写法。

## 3. 开启方案候选(每个都给:改哪里 / 成本 / 风险 / 回滚 / 生效时间)

### 方案 A(首选):让帽子云开压缩 / 自定义响应头 / 预压缩 `.gz` + Content-Encoding

- **改哪里**:不改进我们的代码;向帽子云支持(微信 `maozicdn`)提工单/需求。请求三选一:
  1. 对静态托管的 `text/html`、`text/css`、`text/javascript`、`application/javascript`、`application/json` 开 gzip/brotli,并返回 `Vary: Accept-Encoding`;
  2. 允许用户设置自定义响应头(至少 `Content-Encoding` / `Vary` / `Cache-Control`),这样构建期 `.gz`/`.br` 才能用;
  3. 允许"预压缩文件 + 按 `Accept-Encoding` 自动选 `.gz`/`.br` 并加 `Content-Encoding`"。
- **成本**:0 行代码;一次沟通 + 等待。
- **风险**:厂商拒绝/排期不确定;若只开 br/zstd 不开 gzip,老浏览器没有回退;若压缩但不发 `Vary`,前面若有共享缓存,可能把压缩体发给不支持压缩的客户端;若只对部分 content-type 开,HTML/CSS 仍裸传。
- **回滚**:无需回滚;若效果异常,让厂商关掉即可。
- **生效时间**:取决于厂商(小时~天)。
- **预期收益**:满收益。按 ss 的 br 口径 465,452 B(-72.2%),按 gzip 口径 ~484,677 B(-71.0%);具体看帽子云用的算法/级别。**这是唯一"零代码、不动架构、拿满收益"的路径。**
- **给厂商的证据**(直接贴):s 站 9/9 资源无 `Content-Encoding`/`Vary`;同字节在 CF 上 br 465,452 B;帽子云自己的官网 gzip;`_headers` 不生效;app.min.js 单文件 1,090,838 B,压后 ~341KB(gzip)/~318KB(br);希望至少 gzip + Vary。

### 方案 B:把 s 前置到 Cloudflare(自动压缩)

两种落地:

**B1 zone move(改 `sugas.site` 的 NS 到 CF)**
- 改哪里:DNS 服务商把 `sugas.site` NS 切到 CF;在 CF 加 `s` 的 CNAME 到 `cname.maozi-dns.com`(橙云 proxied);`sss` 保持 DNS-only 以继续走 GitHub Pages;apex/www 按现状配置。
- 成本:M(改 DNS/SSL/回源配置 + 三站回归)。
- 风险:高。CF 成为 s 的客户端边缘,s 与 ss 共因失效(CF 故障/被墙/大陆路由差时,主站和备站一起挂);`sugas.site` 整个 zone 的 DNS 都迁到 CF,误配会影响 sss/apex;CF 到帽子云的回源 TLS/Host/SNI 要验证(帽子云是否接受 CF 的 SNI/Host);大陆用户体验未验证(本次本机经代理,不代表大陆)。
- 回滚:NS 切回原服务商;CNAME 恢复;TTL 内生效。
- 生效时间:NS 传播 0.5~24h(视 TTL)。
- 预期收益:满收益(CF 自动 br/zstd,按套餐;实测 ss 的 br 465,452 B)。

**B2 Cloudflare for SaaS(custom hostname)**
- 改哪里:在 `fx8.store` 这个 CF zone 开 Cloudflare for SaaS;把 `s.sugas.site` 作为 custom hostname;CNAME 指到 SaaS 提供的目标;fallback origin 配帽子云;证书由 CF 签。
- 成本:M(开通/证书/回源/验证)。
- 风险:中高。CF 官方套餐表:Free/Pro/Business 含 100 个 hostname,超出 $0.10/个;custom origin 三档都支持,但 **SNI Rewrite for Custom Origin 只有 Enterprise**;非 Enterprise 回源 SNI 可能不是 `s.sugas.site`,帽子云可能拒绝/证书不匹配,必须先小号验证;仍是 CF 边缘,s 与 ss 共因失效。
- 回滚:CNAME 改回;删除 custom hostname。
- 生效时间:证书签发分钟级,整体小时级。
- 预期收益:满收益。

**结论**:B 能拿满收益,但把 s 从"独立于 CF 的备站"变成"CF 前置",是否可接受要用户拍板;不作为默认推荐。

### 方案 C:Worker 内按 Accept-Encoding 预压缩 / 回源压

- **C1 让 s 走我们的 Worker**:前提是 B(把 s 的 DNS 指到 CF)。一旦走 CF,CF 会自动压缩,Worker 再手工压是重复;若在 Worker 里 `CompressionStream('gzip')`,只有 gzip/deflate(浏览器 `CompressionStream` 不支持 br/zstd),反而比 CF 自动的 br/zstd 差,还耗 CPU。**不推荐。**
- **C2 在 ss.fx8.store 做资产代理**:加 Worker 路由 `/s-assets/*`,回源 `https://s.sugas.site/*`,返回时让 CF 自动压缩并加 `Cache-Control: immutable`;s 的 index.html 把 `app.min.js`/CSS 指向 `https://ss.fx8.store/s-assets/...`,并加 `onerror` 回退本地。
  - 成本:S-M(Worker 路由 + index 条件改 + 回退)。
  - 风险:高。s 的壳(HTML)在帽子云,但核心 JS/CSS 依赖 CF;CF 被墙/故障时,s 的 fallback 只能在 `onerror` 后触发,慢网络下可能先卡几秒;跨域脚本/CSS 的缓存/SW 行为要测;与"备站独立"冲突。
  - 回滚:index 改回本地相对路径;删路由。
  - 生效时间:下次部署(帽子云拉取 + 20min 缓存)。
  - 收益:资产部分满收益(HTML 仍裸传 38,569 B,总 ~504KB)。
  - 结论:如果用户接受"备站资产依赖主站",这是代码量较小的满收益方案;否则不推荐。

### 方案 D:构建期预压缩(`.br`/`.gz`)+ `Content-Encoding`

- **D1 只生成 `.br/.gz` 并指望服务器按扩展名加 `Content-Encoding`**:
  - 在帽子云:**不可行**。它不解析 `_headers`,也没有自定义头;实测 `.gz` 请求当前 404(文件不存在),历史上 `.json.gz` 能 200 但 `content-type: application/gzip`,没有 `content-encoding`(NOTES 小节 S)。浏览器拿到的是二进制,不会当 JS/CSS 执行。
  - 在 CF:**不需要**。CF 已经自动 br/zstd;再放 `.br` 只会多一份存储,且 CF 可能对 `.br` 文件再处理(取决于 content-type)。
  - 结论:**单独用零效果**,不能作为方案。
- **D2 `.gz` + 客户端 `DecompressionStream`**:见方案 E。这是 D 唯一有意义的形态,但本质是 E(客户端解压),不是"服务端 Content-Encoding"。
- **与 `fetchJSON` 的 `.gz` 约定是否冲突**:
  - 数据 JSON 的 `.gz` 已经**退役**:`static-site/app.js:9711` `const tryGz = false;`(2026-08-01 起,"全部跳过 .gz,统一 .json + CF br",根因是 CF edge 对 `.gz` 有 4h 缓存滞后);`scripts/upload_r2.py:975` / `:2425` 明确"include_gz 参数已废弃(.gz 不再生成,CF 自动 br 压缩替代)";`export.py` 现在也不生成 `.gz`(只剩旧注释)。
  - 因此**不要再把数据 `.gz` 打开**(会把 4h 旧数据事故重新引入);资产 `.gz` 是另一个命名空间(只给 app.min.js/CSS/JS 用,不喂给 `fetchJSON`),两者不冲突,但必须在文档/代码里写清楚"数据 .gz 仍禁用,只有 s 站资产 .gz 启用"。
  - 如果未来要恢复数据 `.gz`,必须同时解决 CF edge 缓存键/滞后,不能只改前端。

### 方案 E:客户端 `.gz` + `DecompressionStream`(保留帽子云)

这是"不改托管、不依赖 CF"的唯一可行工程路径。项目已经有同样机制的线上先例(NOTES 小节 S:数据 `.json.gz` 200 + 前端解压),不是从零发明。

**E1 改哪里**

1. 构建期新增 `scripts/build_gz.py`(或并入 `build_min.py` 末尾):对 `app.min.js`(第一期)、`common.min.js`、`purpose-notes.min.js`、`i18n.js`、`inline-init.js`、`qr.js`(第二期)、`style.min.css`、`lab.min.css`(第三期)生成同名 `.gz`,`gzip -9 -n`(去时间戳,保证可复现);输出到 `static-site/` 同目录或 `static-site/gz/`。
2. `index.html`:把当前 `<script defer src="./app.min.js?v=...">` 改为一个小 loader(建议独立 `boot-app.js`,或内联);loader 只在 `location.hostname === 's.sugas.site'` 时走 `.gz`,其他域名(ss/sss)走原 `app.min.js`。**关键难点:三站共用同一份 index.html,不能让 ss/sss 也改成 fetch+inject。** 可选实现:
   - 在 index.html 里保留一个 `<script type="text/plain" data-app-src="./app.min.js?v=...">`(惰性,不会下载),再加一个 `defer` 的 `boot-app.js`;boot-app 读取 data-app-src,按 hostname 决定 fetch 原始还是 gz,解压后注入。这样不会让 ss/sss 预加载错文件,但 app 的下载会从"解析期并行"变成"boot-app 执行后",主站可能多 ~1 个 RTT;需要在 ss/sss 实测确认可接受。
   - 或者用顶部 inline 脚本按 hostname 创建 `<link rel=preload>` + 末尾 defer loader;更复杂,但能把下载提前。
   - 最干净的是给 s 单独一份 HTML 入口,但当前帽子云是从 git main 拉同一份 `static-site/`,没有公开的"按域名换入口"配置;不要假设可以。
3. loader 逻辑:
   - 支持 `DecompressionStream('gzip')` 且 hostname 是 s → `fetch('./app.min.js.gz?v=' + v)` → `new Response(resp.body.pipeThrough(new DecompressionStream('gzip'))).text()` → 创建 `<script>` 注入 `text`;
   - 任何失败(404/解压错/不支持/网络错) → 回退加载原始 `./app.min.js?v=`(原逻辑);
   - 提供 `?nogz=1` 或 `window.__NO_GZ` 调试开关,便于验证回退;
   - 版本串 v 从 `meta[name="lab-asset-url"]` 的 `?v=` 解析(该 meta 已被 `bump_asset_version.py` 改写),或新增一个 `meta[name="asset-version"]` 并扩展 bump;**不要直接把 `app.min.js.gz?v=` 写进 index.html 让现有 bump 正则处理**:`bump_asset_version.py:31` 的 ASSETS 里是 `app.min.js`,它的正则会把 `./app.min.js.gz?v=old` 里的 `./app.min.js` 前缀替换成 `./app.min.js?v=new`,留下 `.gz?v=old`,把 URL 拼坏。这是落地时最容易踩的坑。
4. `sw.js`:当前 `CORE_SHELL_URLS` 只含 `./`, `./index.html`, `./app.min.js`, `./common.min.js`(`sw.js:34-41`);`APP_SHELL_ASSET_PATTERN` 只匹配 css/js/svg/png/ico/woff/ttf(`sw.js:64`),**`.gz` 不匹配**,会落到默认分支 `fetch(req,{cache:'no-store'})`(`sw.js:157+`),即每次都回源、不进 SW 缓存。需要:
   - 给 `.gz` 加 cache-first 分支(或把 `gz` 加进 pattern);
   - 把 `.gz` 加进 `PRECACHE_URLS`(非 `CORE_SHELL_URLS`,避免 `.gz` 缺失导致 SW 不激活);
   - 保留原始 `app.min.js` 在 `CORE_SHELL_URLS` 作为离线/失败回退;
   - bump `CACHE_VERSION`(§24),并测更新路径。
5. `main-merge.sh` / `deploy.sh`:
   - `main-merge.sh:228-255` 现在跑 `build_min.py` + `bump_asset_version.py`;要加 `build_gz.py`,且顺序必须是 min → gz → bump;
   - `deploy.sh:758-770` 的 `DATA_FILES` 只精确 add 6 个 min 文件;要把 `.gz` 加进去,否则帽子云拉不到;
   - 加 CI/本地检查:`gzip -dc app.min.js.gz` 的 sha256 == `app.min.js` 的 sha256;版本串一致;`.gz` 与原文件同 commit。
6. 版本/缓存:帽子云 `max-age=1200`,query 参与缓存键(前次实测不同 query 首次 MISS、重复 HIT);用 `?v=` 换 URL 可行,但旧缓存最多 20min;HTML 也是 20min,发布后要等窗口。不要用同 URL 覆盖内容。

**E2 预期收益(实测/计算,不是估算)**

| 阶段 | 内容 | 原始 | gzip -9 后 | 首屏合计 | 相对原始 |
|---|---|---:|---:|---:|---:|
| 基线 | 9 资源 | 1,671,414 | - | 1,671,414 | 100% |
| E-1 | 只压 app.min.js | 1,090,838 | 341,435 | 922,011 | -44.8% |
| E-2 | 压 6 个首屏 JS(app/common/i18n/inline-init/purpose/qr) | 1,255,866 | 405,552 | 821,100 | -50.9% |
| E-3 | 再压 2 个 CSS(style/lab) | 1,632,845 | 465,576 | 504,145 | -69.8% |
| 理论全量(含 HTML) | 9 资源 | 1,671,414 | 478,894 | 478,894 | -71.3% |

注:HTML 38,569 B 不能客户端解压(loader 本身在 HTML 里,HTML 必须先到),所以 E 的实际天花板是 E-3 的 504,145 B;不要把 478,894 当可实现目标。

**E3 成本/风险/回滚/生效时间**

- **成本**:M(1 个构建脚本 + loader + sw.js + bump/deploy + 测试);如果只做 E-1,约 1 天;E-3 再加 CSS 注入,约 1.5~2 天。
- **风险**:中高。
  - 三站共用 index.html/sw.js,loader 写错 = **备站白屏**(P0);必须保留原始 app.min.js 作为回退,并先在 s 站灰度。
  - app 的加载从"defer 原生脚本"变成"fetch+注入",执行时机/`document.currentScript`/CSP/错误栈都会变;`app.min.js` 目前没有用 `document.currentScript`(grep 0),但未来新增代码要注意。
  - SW 的 `.gz` 缓存/版本/离线路径要同步改;不改 SW 则重复访问每次回源(.gz 341KB,比 1MB 好,但仍不理想);改了 SW 则要测旧 SW 升级/白屏。
  - CSS 注入有 FOUC;第三期必须配合关键 CSS 内联或 `<link rel=preload>` + 尽快注入,否则首屏会闪。
  - `.gz` 文件必须与 min 文件同版本;忘记生成/忘记 add = 404 → 回退原始(功能不坏,但省不到);要 CI 校验。
- **回滚**:index.html 改回原生 `<script defer src="./app.min.js">`;删除 boot loader;sw.js `CACHE_VERSION` bump;`.gz` 文件可保留但不再引用;一次 deploy 恢复。
- **生效时间**:下次 s deploy(帽子云拉 git main,通常几分钟 + `max-age=1200` 缓存窗口)。

**E4 为什么不是"低风险"**

任务书原以为开压缩是低风险开关;E 不是开关,是**改首屏 JS 的加载方式**,而且改的是三站共用的入口和 SW。对 s 这个"最后兜底"的站点,白屏的代价比省 1MB 大。必须:
- 先在 s 单独灰度(如果能做到按 hostname 分支),ss/sss 保持原生脚本;
- 保留原始 app.min.js 回退,并在 DevTools 里模拟 `.gz` 404/解压失败/无 DecompressionStream 三种失败;
- 测 SW 离线、旧 SW 升级、版本串切换;
- 用真实浏览器测首屏渲染,不只看 curl。

### 方案 F:首屏裁剪 / CSS 拆分(补充,不能替代压缩)

- 事实:9 个首屏资源首页都在用,不能简单删:
  - `purpose-notes.min.js` 在 `app.js:16016`、`:16033`、`:18102`、`:18165`、`:20850`、`:20997`、`:21102`、`:23776`、`:25769`、`:27410` 等首屏渲染路径里直接读 `PURPOSE_NOTES[...]`;
  - `qr.js` 在 `app.js:32980` 首屏右下角二维码绘制里用;
  - `lab.min.css` 里有 618 个 `.lab-sigkelly`/`.lab-etf-pin` 选择器(`lab.css`),而 `style.css` 只有 7 个;首页的 AI 仓位 K 按钮、ETF 走势弹窗都用这些 class(`app.js` 有 199 处 `lab-`),不能把 lab.css 整体懒加载到 lab tab;
  - `lab.min.js` 已经是懒加载(index.html L304/307 注释),不是首屏。
- 可做的:把 `lab.css` 按"首页用到的 sigkelly/etf-pin 子集"和"lab tab 专用"拆开,首页只加载小子集,lab tab 再加载全量;或把 `app.min.js` 里 lab 相关 UI 代码拆 chunk(NOTES:1488 评估 ROI 低)。收益:lab.css 最多 119,410 B 的一部分,远小于压缩的 1.19MB。
- 成本:M~L;风险:中(拆错 CSS 首页样式坏);回滚:恢复单文件;生效:下次部署。
- 结论:**作为压缩落地后的补充,不作为主方案。**

### 方案 G:换托管/加支持压缩的 CDN

- 把 s 迁到 Cloudflare Pages/Netlify/Vercel,或在帽子云前加一层支持 br 的反向代理 CDN(CNAME 切流)。
- 成本:M;风险:高(丢帽子云线路/新供应商/证书/大陆体验/成本);回滚:DNS 切回;生效:分钟~小时。
- 收益:满收益。
- 结论:能解决,但改变 s 的部署与线路,不作为第一优先;如果用户本来就想换掉帽子云,这是彻底解。

### 3.8 方案对比表

| 方案 | 改哪里 | 成本 | 风险 | 回滚 | 生效时间 | 预期首屏 | 推荐度 |
|---|---|---|---|---|---|---|---|
| A 帽子云开压缩 | 厂商 | 0 代码 | 低(取决于厂商) | 让厂商关 | 小时~天 | 465,452~484,677 | **首选** |
| B1 zone move 到 CF | DNS/CF | M | 高(共因失效/大陆/全 zone) | NS 切回 | 0.5~24h | 465,452~481,538 | 备选(角色可变时) |
| B2 CF for SaaS | CF SaaS | M | 中高(SNI/custom origin/共因) | CNAME 改回 | 分钟~小时 | 同上 | 备选(需小号验证) |
| C1 Worker 内压 | Worker | M | 中(依赖 B/丢 br/zstd) | 删路由 | 立即 | 同上 | 不推荐 |
| C2 ss 资产代理 | Worker+index | S-M | 高(备站依赖主站) | index/路由回退 | 下次部署 | ~504KB | 可选(接受依赖时) |
| D1 只生成 .br/.gz | 构建 | S | 低但**无效** | 删文件 | - | 无变化 | 不做 |
| E 客户端 .gz | 构建+index+SW | M | 中高(白屏/SW/版本) | 改回原生 script | 下次部署 | 922,011 / 821,100 / 504,145 | 备选(保留帽子云时) |
| F 首屏裁剪 | index/CSS/JS | M~L | 中(样式/渲染) | 恢复单文件 | 下次部署 | 省 0~119KB | 补充 |
| G 换托管/CDN | 迁移 | M | 高(线路/供应商) | DNS 切回 | 分钟~小时 | 满收益 | 最后 |

### 3.9 推荐结论(决策树)

1. **先做 A**:给帽子云提工单,要求 gzip/brotli + `Vary`,或自定义响应头/预压缩 `.gz`。这是唯一零代码、满收益、不动架构的路径。它自己的官网已经 gzip,谈判有依据。
2. **A 拒绝后,看 s 站的定位**:
   - 如果 s 必须保持"独立于 CF 的第三家备站" → 做 **E**,先 E-1(app.min.js,922,011 B,-44.8%),验证稳定后再 E-2/E-3;同时可做 F 的 CSS 子集拆分作为补充。
   - 如果 s 的定位可以变成"CF 前置"、且接受与 ss 共因失效 → 做 **B1 或 B2**,拿满收益;先小号验证帽子云回源 TLS/Host/SNI,再切 DNS。
3. **不建议**:C1(Worker 内压,依赖 B 且更差)、D1(单独 .gz 无效)、F 单独、G 单独。
4. **任何方案落地前**,按第 5 节证据用例验;不达标判方案失败,不按"完成度"放过。

## 4. 与 ss.fx8.store 的差异:为什么它能压,s 缺什么

### 4.1 逐字段 header 对比表

| 字段 | ss.fx8.store | sss.sugas.site | s.sugas.site | 差异说明 |
|---|---|---|---|---|
| `server` | `cloudflare` | `GitHub.com` | `MaoziYun/3.18.0` | s 的客户端边缘是帽子云,不是 CF |
| `cf-ray` | 有(`...-HKG`) | 无 | 有(`...-SJC`) | s 的 cf-ray 是上游透传,不是客户端边缘 |
| `cf-cache-status` | assets `HIT`;HTML `no-store` | 无 | `MISS`(上游) | s 的缓存由 `my-cache-status` 表示 |
| `my-cache-status` | 无 | 无 | `HIT` | 帽子云自己的缓存命中,但输出未压缩 |
| `content-encoding` | `zstd`/`br`/`gzip`(按 AE) | `gzip` | **无** | 核心差异 |
| `vary` | 无(CF 内部协商) | `Accept-Encoding` | **无** | s 没做内容协商;ss 也没有 Vary 但 CF 仍压,说明 Vary 不是必要条件 |
| `content-length` | 压缩时省略;identity 1,090,838 | 343,877(gzip) | 1,090,838(raw);HTML 无 | s 有 Content-Length 也不压,证明不是它挡的 |
| `cache-control` | assets `public, max-age=31536000, immutable`;HTML `no-store` | `max-age=600` | `max-age=1200` | s 的 `_headers` 不生效,只有帽子云默认 |
| `content-type` | `text/javascript`/`text/css`/`text/html` | `application/javascript; charset=utf-8` 等 | `text/javascript;charset=utf-8` 等 | 三类都在 CF 可压缩清单内 |
| `x-bz-server-side-encryption` | 无 | 无 | `AES256` | s 上游疑似 B2 存储 |
| 边缘/回源 | CF Workers Static Assets + R2 binding | GitHub Pages/Fastly | 帽子云 + 上游 B2/CF 跳 | s 没有我们的 Worker/CF zone |
| 9 资源 | 465,452(br)/481,538(zstd) | 484,677(gzip) | 1,671,414(raw) | 同一批字节,差在传输层 |

### 4.2 为什么 ss 能压

1. ss 的域名 `ss.fx8.store` 在 CF zone 内,DNS 指向 Cloudflare anycast;CF 是客户端边缘。
2. CF Workers Static Assets 的响应回到 CF 边缘后,CF 按 `Accept-Encoding`、content-type、状态码、大小、套餐自动压缩;`worker/headers.js` 没有 `no-transform`,也没有自己写 `Content-Encoding`,所以 CF 可以压。
3. 实测:同一 app.min.js,`AE: br` → 318,665;`gzip` → 341,742;`zstd` → 326,983;`identity` → 1,090,838。CF 文档也说明 status 200、可压缩 content-type、≥48/50 B 才会压,这些条件 ss 全满足。
4. CF 的 `Vary` 不一定出现在响应里,但 CF 内部按 AE 协商;所以"ss 没有 Vary 但能压"和"s 没有 Vary 且不压"并不矛盾——s 是根本没有压缩能力/开关,不是缺 Vary 这一个头。

### 4.3 s 缺什么

- 缺一个**我们控制的、支持自动压缩的客户端边缘**(CF zone / 支持压缩的 CDN)。
- 缺**内容协商**(`Accept-Encoding` → `Content-Encoding` + `Vary`)。
- 缺**自定义响应头能力**(`_headers` 不生效,`Content-Encoding`/`Cache-Control`/`ETag` 都设不了)。
- 缺**长缓存/immutable**(只有 `max-age=1200`),但这只是次要问题;核心还是压缩。
- 缺**ETag/强校验**(只有 `last-modified`,且看起来是动态生成),不影响压缩,但影响重复访问验证。

## 5. 验证方案(§5.7:依据 + 实现预期 + 证据用例)

### 5.1 改动前基线复现(任何人可独立跑)

```bash
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'

# 1) s 站核心资源:期望无 content-encoding,content-length=1090838
curl -sS --resolve s.sugas.site:443:104.233.148.233 \
  -D - -o /dev/null --max-time 20 -A "$UA" \
  -H 'Accept-Encoding: gzip, deflate, br, zstd' \
  https://s.sugas.site/app.min.js

# 2) s 站 9 资源合计(期望 1671414)
total=0
for p in / /app.min.js /common.min.js /i18n.js /inline-init.js /purpose-notes.min.js /qr.js /style.min.css /lab.min.css; do
  if [ "$p" = "/" ]; then u="https://s.sugas.site/"; else u="https://s.sugas.site$p?v=20261022-a649"; fi
  n=$(curl -sS --resolve s.sugas.site:443:104.233.148.233 -o /dev/null --max-time 15 -A "$UA" \
      -H 'Accept-Encoding: gzip, deflate, br, zstd' -w '%{size_download}' "$u")
  total=$((total+n))
done
echo "s_total=$total"   # 期望 1671414

# 3) 边缘归属:期望返回帽子云 JSON 404,不是 CF trace
curl -sS --resolve s.sugas.site:443:104.233.148.233 --max-time 20 -A "$UA" \
  -o /tmp/tr.out -w 'code=%{http_code}\n' https://s.sugas.site/cdn-cgi/trace
head -c 120 /tmp/tr.out

# 4) ss 对照:期望 content-encoding: zstd/br,size ~326983/318665
curl -sS -D - -o /dev/null --max-time 20 -A "$UA" \
  -H 'Accept-Encoding: gzip, deflate, br, zstd' \
  https://ss.fx8.store/app.min.js

# 5) 内容一致性:期望四个 sha256 相同
curl -sS --resolve s.sugas.site:443:104.233.148.233 --max-time 30 -A "$UA" \
  https://s.sugas.site/app.min.js | shasum -a 256
curl -sS --compressed --max-time 30 -A "$UA" https://ss.fx8.store/app.min.js | shasum -a 256
curl -sS --compressed --max-time 30 -A "$UA" https://sss.sugas.site/app.min.js | shasum -a 256
```

**基线断言(PASS/FAIL)**:
- s app.min.js:`HTTP/2 200`,`content-length: 1090838`,**无** `content-encoding`,**无** `vary`;
- s 9 资源合计 `1671414`(允许 ±0;Brotli/zstd 不参与 identity 请求);
- s `/cdn-cgi/trace` 不是 CF trace(本次是 307 + JSON 404);
- ss app.min.js 有 `content-encoding`,size 约为 `326983`(zstd)或 `318665`(br);
- 三域名 sha256 全等 `5503942c...`。

### 5.2 方案 A(帽子云开压缩)改完后的验收

**curl 证据(每个域名/每个资源都要跑)**:

```bash
# 期望:content-encoding: gzip 或 br;vary 含 Accept-Encoding;size 明显下降
curl -sS --resolve s.sugas.site:443:104.233.148.233 \
  -D - -o /dev/null --max-time 20 -A "$UA" \
  -H 'Accept-Encoding: gzip, deflate, br, zstd' \
  -w 'size=%{size_download}\n' \
  https://s.sugas.site/app.min.js
```

**期望值(实测口径)**:
- `content-encoding` 必须是 `gzip` / `br` / `zstd` 之一;
- `vary` 必须含 `Accept-Encoding`(否则共享缓存有错配风险);
- `size_download`:
  - gzip:约 341,435 B(本地 gzip -9;帽子云级别可能 341~344KB);
  - br:约 254,386~318,665 B(取决于级别;CF br 318,665);
  - zstd:约 326,983 B;
- 9 资源合计:gzip ≤ 484,677 B,br ≤ 465,452 B(与 ss 同口径),zstd ≤ 481,538 B;
- `content-type` 不变(仍是 text/javascript/css/html);
- `cache-control` 不变(不要因为开压缩把缓存策略改坏);
- 用 `AE: identity` 再测一次,size 应回到 1,090,838,证明压缩是按请求协商的,不是把源文件改了;
- 用 `AE: gzip` 和 `AE: br` 各测一次,确认老浏览器有 gzip 回退;
- 用 `curl --compressed` 取回内容,sha256 应仍等于 `5503942c...`,证明解压后内容一致。

**失败判据**:有 `content-encoding` 但浏览器报 `ERR_CONTENT_DECODING_FAILED`;或只有 br/zstd 没有 gzip;或 `vary` 缺失且前面有共享缓存;或 9 资源合计仍 > 600KB → 不算达标,回退/让厂商修。

### 5.3 方案 E(客户端 .gz)改完后的验收

**文件/构建证据**:
```bash
# 1) .gz 存在且可解压,内容与原文件逐位一致
curl -sS --resolve s.sugas.site:443:104.233.148.233 --max-time 20 -A "$UA" \
  "https://s.sugas.site/app.min.js.gz?v=<NEW_VER>" -o /tmp/app.min.js.gz
gzip -dc /tmp/app.min.js.gz | shasum -a 256   # 期望 5503942c...
wc -c < /tmp/app.min.js.gz                     # 期望 341435 左右(±1%)

# 2) 原文件仍在(回退路径)
curl -sS --resolve s.sugas.site:443:104.233.148.233 -o /dev/null --max-time 20 -A "$UA" \
  -w '%{http_code} %{size_download}\n' "https://s.sugas.site/app.min.js?v=<NEW_VER>"
# 期望 200 1090838
```

**浏览器证据(必须真实浏览器,不能只 curl)**:
1. Chrome 无痕窗口,DevTools → Network,勾选 Disable cache,打开 `https://s.sugas.site/`:
   - 应看到 `app.min.js.gz` 请求,`Content-Type: application/gzip`,`Transferred` 约 341KB,**没有** `Content-Encoding`(这是客户端解压,不是浏览器原生解压);
   - 页面正常渲染出首页情绪分/卡片,Console 无红错;
   - `performance.getEntriesByType('resource').filter(e=>e.name.includes('app.min')).map(e=>({name:e.name,transferSize:e.transferSize,encodedBodySize:e.encodedBodySize}))` 中 `app.min.js.gz` 的 transferSize 约 341KB。
2. 回退测试:
   - DevTools → Network → Request blocking,加 `*app.min.js.gz*`,硬刷新 → 应自动回退 `app.min.js`(1,090,838),页面仍正常;
   - 在 URL 加 `?nogz=1`(loader 需实现该调试开关) → 应直接走原始 app.min.js,页面正常;
   - 用 Safari 16.3 或不支持 `DecompressionStream` 的浏览器(或用 `window.DecompressionStream = undefined` 的测试页) → 回退原始,页面正常。
3. SW/离线:
   - Application → Service Workers,确认新 `CACHE_VERSION` 生效;
   - 勾 Offline,刷新 → 页面应能启动(原始 app.min.js 在 CORE_SHELL,`.gz` 若已 precache 也可走 gz;两条至少一条可用);
   - 再关 Offline,确认不出现旧版/新版混用。
4. 版本切换:
   - 改一次 `?v=`(模拟 bump),刷新两次:第一次应拉新 `.gz`/新 HTML,第二次命中缓存;`sw.js` 的 `CACHE_VERSION` 与 HTML 的 `?v=` 必须同源;旧缓存应被清掉。
5. 三站回归:
   - ss.fx8.store:仍走原生 `app.min.js`,zstd/br,不受 loader 影响;
   - sss.sugas.site:仍走原生 `app.min.js`,gzip;
   - s.sugas.site:走 `.gz`+解压;
   - 三站 `app.min.js` sha256 一致,页面功能一致。

**量化 PASS/FAIL**:
- E-1:首屏 9 资源总传输 ≤ 930,000 B(目标 922,011),app.min.js.gz 解压后 sha256 正确,页面正常 → PASS;若 > 1,000,000 B 或白屏 → FAIL。
- E-2:≤ 830,000 B(目标 821,100)。
- E-3:≤ 515,000 B(目标 504,145);若 CSS 注入导致首屏闪烁/无样式 → FAIL,退回 E-2。
- 任何阶段出现 Console 红错、白屏、lab tab/K 按钮/ETF 弹窗样式坏 → FAIL。

### 5.4 用户侧真实浏览器怎么确认(不只单点 curl)

- 用手机 Chrome/Safari 各开一次 `https://s.sugas.site/`(无痕/清缓存),看:
  - 首屏是否在 3 秒内出现情绪分/卡片(4G 网络模拟);
  - 页面底部/控制台无报错;
  - 切到 lab tab、点 AI 仓位 K 按钮、打开 ETF 走势弹窗(这些用到 `lab.min.css`/`lab.min.js`),确认样式/交互正常;
  - 断网后重开(已访问过)确认 SW 离线页不白屏。
- 用 DevTools Performance 的 LCP/FCP 对比改动前后(同一网络限速、同一设备),记录数值;不要只看 `size_download`。
- 在 ss/sss 也各开一次,确认没有被 s 的 loader 误伤。
- 记录证据:截图/性能面板数字/Console 无错,附在实施报告里。

### 5.5 §5.7 三件套对照

| 项 | 本方案 |
|---|---|
| 可修正依据 | 第 1/2 节的三域名 header、9 资源体积、sha256、CF/帽子云文档原文;每条带命令/行号/URL |
| 实现预期(X→Y) | A:s 9 资源 1,671,414 → 465,452~484,677,`content-encoding` 从无到有;E-1:→922,011;E-2:→821,100;E-3:→504,145 |
| 证据用例 | 5.1 基线命令 + 5.2/5.3 验收命令 + 5.4 浏览器/SW 测试;PASS/FAIL 阈值已写死 |
| 验收 | 对不上判方案失败,回 researcher/改方案,不按"完成度"放过 |

## 6. 风险清单

| # | 风险 | 影响 | 缓解/验收 |
|---|---|---|---|
| 1 | **三站共用 index.html/sw.js,loader 写错 = 备站白屏(§24)** | s 是最后兜底,白屏代价最大;可能同时影响 ss/sss | 按 hostname 只在 s 启用;保留原始 app.min.js 回退;先灰度;DevTools 模拟 `.gz` 404/解压失败/无 DecompressionStream;真实浏览器测;不达标不上 |
| 2 | **CF 前置后 s 与 ss 共因失效** | CF 故障/被墙/大陆路由差时,主站+备站一起挂,备站意义消失 | 只有用户确认 s 角色可变才做;保留帽子云原站可切回;先小号验证;不要默认做 |
| 3 | SW 缓存/版本撕裂(§24) | 旧 SW 返回旧 app/新 HTML 混用,白屏或功能坏 | `.gz` 加 cache-first 分支 + PRECACHE(非 core);保留 raw core shell;`CACHE_VERSION` bump;测旧 SW 升级/离线;index 与 sw 同 commit |
| 4 | 版本串坑:`bump_asset_version.py` 只认 ASSETS 里的 `app.min.js`,直接写 `app.min.js.gz?v=` 会被正则拼坏 | `.gz` URL 变成 `app.min.js?v=new.gz?v=old`,404/白屏 | 用 `meta[name=asset-version]`/`lab-asset-url` 解析版本;或给 bump 加专用 GZ_ASSETS 并改正则;CI 校验 URL 可访问 |
| 5 | `app.min.js` vs `lab.js` 加载顺序 | lab tab、首页 K 按钮/ETF 弹窗样式或交互坏 | app 仍是最后加载;lab.js 仍按 `meta[name=lab-asset-url]` 懒加载;测 lab tab/K 按钮/ETF 弹窗;不要动 lab.css 的首页子集 |
| 6 | 老浏览器不支持 br/zstd/DecompressionStream | 页面不启动/样式坏 | 厂商路径必须保留 gzip 回退 + `Vary`;客户端路径检测 `DecompressionStream`,不支持回退 raw;用 Safari 16.3/旧 Chrome 测 |
| 7 | CF 缓存键变化/旧缓存命中 | 新版本被旧缓存覆盖,或压缩/未压缩混用 | `.gz` 用新路径/新 query;CF 侧不要依赖 `?v=` 破 edge 缓存(项目注释称 CF 忽略 query);必要时 purge/换文件名;帽子云只有 max-age=1200,发布后等窗口;测 `my-cache-status`/`cf-cache-status` |
| 8 | 数据 `.gz` 误开 | 4h 旧数据事故复发 | 明确"数据 .gz 仍禁用,只有 s 站资产 .gz";`app.js:9711 tryGz=false` 不动;asset `.gz` 不喂 `fetchJSON` |
| 9 | 帽子云 300MB 限制 | 部署失败/404 | 只加资产 `.gz`(~0.47MB),不加数据 `.gz`;发布前算体积;保留原文件 |
| 10 | 压缩但不发 `Vary` | 共享缓存把 br/zstd 发给不支持的老客户端 | 验收强制要求 `Vary: Accept-Encoding`;没有就不算达标 |
| 11 | CSS 注入 FOUC(方案 E-3) | 首屏闪一下无样式 | 关键 CSS 内联/提前 preload;先做 E-1/E-2;E-3 单独灰度;LCP/视觉验收 |
| 12 | 跨域资产代理(C2)的 CSP/CORS/离线 | 脚本/CSS 不加载,备站坏 | 只对 script/link 做;不加 `crossorigin`(经典脚本);onerror 回退本地;SW 跨域不拦截;测离线 |

**风险最高的 2 条(报告口径)**:
1. **三站共用入口 + 备站白屏**:index.html/sw.js 是单文件,任何 loader/SW 改动都可能让 s 白屏,而 s 是最后兜底;必须按 hostname 隔离 + 原始回退 + 真实浏览器验收。
2. **CF 前置的共因失效**:把 s 交给 CF 能拿满收益,但 s 与 ss 同生共死,且 CF for SaaS 的 custom origin/SNI 在非 Enterprise 有限制;在用户确认 s 角色可变之前不做。

## 附录 A:外部门户依据(原文/URL)

1. Cloudflare 官方 "Content compression"(`https://developers.cloudflare.com/speed/optimization/content/compression/`,Last updated Apr 17, 2026):
   - "Cloudflare supports Gzip, Brotli, and Zstandard compression when delivering content to website visitors."
   - 可压缩 content-type 列表包含:`text/html`、`text/css`、`text/javascript`、`application/javascript`、`application/json` 等(本报告涉及的 3 类都在内)。
   - "For successful response status codes, Cloudflare will only compress responses if their status code is 200."
   - "For Gzip, responses must have a minimum size of 48 bytes. For Brotli and Zstandard, responses must have a minimum size of 50 bytes."
   - "When Cloudflare compresses a response sent to the website visitor, it may omit the Content-Length HTTP header..."
   - "To preserve the Content-Length header... add cache-control: no-transform... This directive prevents Cloudflare from altering compression..."
   - "Free Plan: Content is compressed by default using Zstandard. Pro and Business Plans: ... Brotli. Enterprise Plan: ... Gzip."(套餐默认;具体 zone 套餐未核,不影响"CF 会压"的结论)
   - "Cloudflare can receive content from your origin server with Brotli or Gzip compression and serve it to visitors uncompressed (or vice versa)..."
2. Cloudflare "Compression Rules"(`https://developers.cloudflare.com/rules/compression-rules/`):可通过规则禁用 Brotli、对指定路径只用 Gzip、为默认 content-type 开 Zstandard 等;**只能作用于本 zone 的流量**。
3. Cloudflare for SaaS "Plans"(`https://developers.cloudflare.com/cloudflare-for-platforms/cloudflare-for-saas/plans/`):Free/Pro/Business 含 100 个 hostname,超出 $0.10/个;custom origin 三档都支持;**SNI Rewrite for Custom Origin 只有 Enterprise**;这是 B2 方案的风险依据。
4. MDN "DecompressionStream"(`https://developer.mozilla.org/en-US/docs/Web/API/DecompressionStream`):Baseline widely available since May 2023;示例用 gzip;支持 `gzip`/`deflate`/`deflate-raw`(不支持 br/zstd,所以客户端解压只能选 gzip)。
5. 帽子云:
   - 官网 `https://www.maoziyun.com/`:联系我们微信 `maozicdn`;官网自身返回 `content-encoding: gzip`(Next.js,server 也是 MaoziYun/3.18.0)。
   - 文档站 `https://www.maoziyun.com/docs/`:搜索"压缩/gzip/brotli/响应头"0 命中;没有公开的静态站点压缩/自定义头说明。

## 附录 B:仓库内证据(文件:行号)

| 证据 | 位置 |
|---|---|
| ss = CF Workers Static Assets,`run_worker_first` | `wrangler.jsonc:11-15` |
| Worker 原样透传 assets、无压缩代码 | `worker/headers.js:359-364`;全文 grep `content-encoding|gzip|brotli` 为空 |
| Worker 安全头无 no-transform | `worker/headers.js:23-39` |
| s = 帽子云,`_headers` 不生效 | `docs/site-deployment.md:600-601`;`static-site/_headers:5` |
| s 自动拉 git main 部署(300MB 超限曾停拉取,迁出 trade_sim 后恢复) | `scripts/deploy.sh:1006`;`NOTES.md:3368`;`NOTES.md:6986`(历史停拉记录) |
| 数据 `.gz` 已退役 | `static-site/app.js:9711`;`scripts/upload_r2.py:975`、`:2425` |
| MaoziYun 不支持 Content-Encoding(历史) | `static-site/app.js:9688`;`NOTES.md:277-349`、`:472-477`、`:1492` |
| 首屏 9 资源的引用 | `static-site/index.html:49-53`、`:87`、`:301-306`、`:308` |
| SW 核心壳/资产正则 | `static-site/sw.js:34-41`、`:64`、`:157+`、`:237+` |
| bump 只改 HTML `?v=` | `scripts/bump_asset_version.py:31`、`:70-90` |
| build+bump 统一入口 | `scripts/main-merge.sh:228-255` |
| deploy 精确 add 清单 | `scripts/deploy.sh:758-770` |
| purpose-notes 首屏使用 | `static-site/app.js:16016`、`:18102`、`:20850` 等 |
| qr 首屏使用 | `static-site/app.js:32980` |
| lab.css 首页选择器 | `static-site/lab.css`(618 个 `lab-sigkelly/etf-pin`);`style.css` 仅 7 个 |
| lab.js 已懒加载 | `static-site/index.html:304/307` 注释 |
| 拆 chunk ROI 低(历史结论) | `NOTES.md:1488` |

## 附录 C:测量/口径诚实标注

- **压缩后体积不能用 `Content-Length`**:CF 压缩时会省略/改写它;本报告用 `curl -w '%{size_download}'`。早前一轮测量曾误用 content-length,导致 9 资源全部显示 100%,已用 `size_download` 纠正。
- **s 的直连 IP**:本机 DNS 被代理 fake-IP 到 `198.18.0.x`,所以用 `--resolve s.sugas.site:443:104.233.148.233`;该 IP 来自 DoH(CNAME `cname.maozi-dns.com`),ipinfo 显示 AS54600 PEG TECH / San Jose。**大陆用户的实际解析/边缘未验证**,不要拿本次结果推断大陆线路。
- **ss/sss 的 IP**:`/etc/hosts` 已固定(ss 104.21.46.172/172.67.168.203,sss 185.199.108.153),本次测量不受 fake-IP 影响。
- **ss 的 465,452 B 是 br 口径**:来自任务书/前次实测(9 资源,AE: br);本次复测的 zstd 是 481,538 B。两者不矛盾,只是编码算法不同;不要混用。
- **本地 gzip -9 / brotli -q11 是理论上限**:本地 `gzip -9` 478,894 B、`br -q11` 370,702 B;线上 CF 的 br 对 app.min.js 是 318,665 B(不是 254,386),所以不要把 370,702 当线上承诺。
- **任务书 1,672,352 B**:是 ss 侧 HTML(39,507)算出的; s 侧 HTML 38,569,合计 1,671,414;差 938 B 是 CF 注入脚本,不是资源差异。
- **未做**:未改任何配置/代码/Worker,未 purge,未部署;未上传 `.gz` 到帽子云;未做 CF for SaaS/zone move 实测;未在大陆真实网络测。
