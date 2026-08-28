# 备站 news_digest.json / overview.json 404 定性调研(2026-08-23 只读)

> 触发:备站 sss.sugas.site / s.sugas.site 上 news_digest.json、overview.json 返回 404,疑似违反 §24④。
> 结论:**设计如此**(R2 架构下备站磁盘本来就没有任何 data JSON,直接 URL 404 是预期形态;前端 fetchJSON 备站重写主站的 fallback 链对这两个文件全覆盖,主站通道实测健康)。非违规 bug、非新类别漏配。

## 一、定性

三选一判定:**设计如此**。

§24④ 原文:「盘后核心产物 overview.json 等必须随 §22 三步同步到备站(GH/Maozi)**或可靠 fallback 主站**」——「或可靠 fallback 主站」是并列合规路径,当前形态正是靠 fallback 主站,合规。

关键区分:
- **直接 curl 备站文件 URL → 404 = 设计内**。备站(GH Pages / MaoziYun)是从 git main 部署的纯静态镜像,R2 迁移阶段 4a(2026-08-08)后 `static-site/data/` 全量移出 git,备站磁盘上一份 data JSON 都没有(docs/bak-data-audit.md 2026-08-11 已审计过同一事实:"GH Pages backup has NO data JSON. 设计如此")。
- **浏览器里打开备站页面 → 不 404**。fetchJSON 对备站域名把 `./data/*` **主动重写**为 `https://ss.fx8.store/data/*`(不等 404 探测),失败再二级兜底 `/r2/data/*`,两文件均在覆盖内。

## 二、证据链

### 1. 前端真实请求路径(grep 确认,非猜测)
| 文件 | 路径 | 消费点 | 是否走 fetchJSON |
|---|---|---|---|
| news_digest.json | `./data/news_digest.json` | static-site/app.js:24680(`_loadNewsDigest`) | 是(app.js:24682) |
| 归档新闻 | `./data/news_digest/<YYYY>/<date>.json`(fallback 扁平旧结构) | app.js:24903-24904(`_loadHistNewsAsync`) | 是 |
| overview.json | `./data/overview.json` | app.js:2077 | 是 |
| boot.json(含 overview 快照) | `./data/boot.json` | app.js:6665(fetchBoot→fetchJSON) | 是 |

全前端裸 fetch 绕过点:`fetch("./data...` 在 app.js/lab.js/common.js 中 **0 处命中**,无绕过 fetchJSON 的消费点。

### 2. fetchJSON 备站重写逻辑(static-site/app.js)
- L6447-6453(2026-08-11 方案A):`_isBackupSite = !_isMainSite() && 非localhost`,备站上 `url.startsWith("./data/")` 即重写为 `_R2_FALLBACK_BASE + filename` = `https://ss.fx8.store/data/<name>`(L6438)。
- L6527-6539(2026-08-15 §24#47):重写后仍失败 → 二级兜底 `_R2_DATA_BASE` = `https://ss.fx8.store/r2/data/<name>`(R2 binding 直读,可用性独立于 /data/ rewrite)。
- `_isMainSite()`(app.js:28112)= `location.hostname === 'ss.fx8.store'`,sss/s 两备站域名均判为备站,重写必触发。

### 3. 主站通道实测健康(curl 带浏览器 UA,2026-08-23)
```
https://ss.fx8.store/data/news_digest.json   -> 200 31170B application/json acao=* cc=no-store
https://ss.fx8.store/data/overview.json      -> 200 506963B application/json acao=* cc=no-store
https://ss.fx8.store/r2/data/news_digest.json -> 200 acao=* cc=public,max-age=3600
```
ACAO=* 放行跨域(备站域名读主站不被 CORS 阻断);no-store 保证新鲜度(worker headers.js 对 news_digest/overview 等 TTL=0)。

### 4. 备站 404 形态与成因
```
https://sss.sugas.site/data/news_digest.json -> 404 text/html(GitHub Pages 404 页 "Page not found · GitHub Pages")
https://s.sugas.site/data/news_digest.json   -> 404 application/json {"code":"not_found","message":"File with such name does not exist."}
两者 /data/boot.json、/data/overview.json 同样 404(连 boot 都 404 = 整个 data 目录不存在,非个别文件漏传)
```
成因:两备站都从 git main 部署(site-deployment.md L597-599:sss=GH Actions deploy-pages 上传 ./static-site;s=MaoziYun 从 git main 拉),而 `.gitignore` 「R2 阶段4a(2026-08-08)」把 `static-site/data/` 全量移出 git——`git ls-files static-site/data/` 计数 = **0**,git 里只有代码没有数据。site-deployment.md L613 明示:「static-site/data/ 已移出 git(走 R2),不推 s.sugas.site」。

### 5. 备站代码层是新版(fallback 逻辑在线)
- sss(GH Pages):index.html 与 app.min.js last-modified = 2026-08-23 21:20(今晚部署成功),版本串 `?v=20260823-a394` 与本地一致;app.min.js etag size 段 e359d(hex)= 931229 B = git HEAD 的 app.min.js(md5 d558611b1fe5e17b2cc8265ffca61d21)完全一致。
- s(MaoziYun):index 引用同版本串 a394,app.min.js 完整下载 931229 B 一致。
- ⚠️ 排查过程自纠:最初三次分段下载 sss 的 min 得到 117KB/623KB/660KB 三种大小且 grep 不到 news_digest,**是我方代理链路对 github.io 大文件传输截断所致的假象**(四次下载四种大小即露馅),不是线上旧版。以 etag/Content-Length 元数据定版本,不以不稳定传输体定版本。

### 6. 上传链完整(两文件都在同步链里)
- overview.json:`scripts/upload_r2.py cmd_upload_intraday` 清单(L1049 附近,"intraday_snapshot.json", "overview.json", ...)随盘中链上传 R2 data/ 前缀 + purge。
- news_digest.json:`scripts/fetch_news.py` L636-729 当日文件+全部归档走「static-site/data 写入 → upload-data-files 上 R2 → staticdata_sync.sh 留档」三步(与 gen_daily_brief 同链路);worker headers.js TTL 规则(upload_r2.py L1113-1115 镜像)已含 news_digest(TTL=0 no-store)。
- R2 实际有对象:/r2/data/news_digest.json 200 即证。

## 三、是否需要修

**默认不需要修**:功能层(备站页面上的首页新闻两行/AI速递/信号灯)由 fallback 主站兜底,通道健康,备站用户体验不受影响。直接 URL 404 是 R2 架构(数据唯一源在 R2、git 只走代码)的自然结果,把它"修掉"(往 git/备站推 data JSON)反而违反 R2 迁移设计且撞 MaoziYun 300MB 限制(site-deployment.md L599/L613)。

可选增强(仅当确有"第三方/监控直接 curl 备站文件 URL"的场景才考虑,等用户拍板,不动手):
1. 监控/验收口径调整:凡验备站数据可用性,curl 目标改为「主站 fallback URL(带 Origin 头验 ACAO)」,不验备站直连 URL(本次 404 报警大概率源于验收口径用了备站直连)。零代码改动。
2. 若坚持备站直连也要 200:需在备站前置一层 rewrite(如 GH Pages 404.html fallback 到 JS 重定向主站),复杂度高收益低,不建议。

## 四、已验证方法/数据源清单
- curl 实测:主站 2 文件 + R2 通道 + 两备站 3 文件 × 各路径(带浏览器 UA,防 Worker/Pages 307 误判)
- grep:前端请求路径(app.js 24680/2077/6665/24903)、fetchJSON 重写逻辑(L6438-6539)、裸 fetch 绕过点(app/lab/common 三文件 0 命中)、upload_r2/fetch_news/gen_daily_brief 上传链
- 读码:worker/headers.js(dataRewriteHandler L152-206,/data/*.json → R2 binding,404 回退 ASSETS)、wrangler.jsonc(assets directory=./static-site)、deploy-pages.yml(push main → upload ./static-site)、.gitignore(阶段4a 段)、docs/site-deployment.md(L597-599 站点表/L613 瘦身注记)、docs/bak-data-audit.md(2026-08-11 同题审计先例)
- git:`git ls-files static-site/data/`=0;`git show HEAD:static-site/app.min.js` md5 对照线上 etag
- 未做(不影响定性):浏览器实操备站页面看 Network 面板(fallback 为静态代码逻辑 + 主站 CORS 实测通过,推理充分)

## 五、关联
- §24④(盘后核心产物备站同步或可靠 fallback)/ §22(N 展示位一致性:此处 N 展示位共享同一主站/R2 数据源,天然一致)
- docs/bak-data-audit.md(2026-08-11):备站可用性三要素(R2 完整性 × CORS × fallback 覆盖度)框架沿用
- memory live-index-curl-307-use-browser-ua(带 UA 防 307 误判)在本次 curl 中已遵守

## 复现

```bash
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"

# 1) 主站两文件 200 + ACAO=*(fallback 目标健康)
curl -s -o /dev/null -A "$UA" -H "Origin: https://sss.sugas.site" -w "%{http_code} acao=%header{access-control-allow-origin} cc=%header{cache-control}\n" https://ss.fx8.store/data/news_digest.json
curl -s -o /dev/null -A "$UA" -H "Origin: https://sss.sugas.site" -w "%{http_code} acao=%header{access-control-allow-origin}\n" https://ss.fx8.store/data/overview.json

# 2) 备站直连 URL 404(设计内;连 boot.json 都 404 = 整个 data 目录不在备站)
for h in sss.sugas.site s.sugas.site; do for f in boot.json overview.json news_digest.json; do
  echo "$h/$f -> $(curl -s -o /dev/null --max-time 25 -A "$UA" -w '%{http_code} %{content_type}' https://$h/data/$f)"; done; done

# 3) R2 通道有对象(二级兜底目标)
curl -s -o /dev/null -A "$UA" -w "%{http_code}\n" https://ss.fx8.store/r2/data/news_digest.json

# 4) 备站代码层为新版(etag 尾段 hex = 字节数,应 = 931229 = git HEAD min 大小;last-modified 应为最近部署时刻)
curl -s -o /dev/null --max-time 25 -A "$UA" -w "etag=%header{etag} lm=%header{last-modified}\n" "https://sss.sugas.site/app.min.js?v=$(grep -oE 'app\.min\.js\?v=[^"]*' /Users/linhuichen/code/trade/static-site/index.html | head -1 | cut -d= -f2)"
git -C /Users/linhuichen/code/trade show HEAD:static-site/app.min.js | wc -c

# 5) 数据不在 git(备站磁盘无 data 的根因)
git -C /Users/linhuichen/code/trade ls-files static-site/data/ | wc -l   # = 0
```

口径一句话:备站纯静态无数据层是 R2 架构设计,数据可用性=fallback 主站(news_digest/overview 均覆盖且主站 200+CORS 放行),直接 curl 备站文件 URL 的 404 不构成故障。
