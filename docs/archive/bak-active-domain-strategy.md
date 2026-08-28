# 备站主动域名策略方案 (2026-08-11 调研, 只读)

> 背景问题: R2 迁移后 `static-site/data/` 移出 git(.gitignore L188-191), 备站(GH Pages sss.sugas.site / MaoziYun s.sugas.site)磁盘零 data。
> 现状备站每个 `./data/*.json` 都要先 404 探测 → 再 fallback 主站 `https://ss.fx8.store/data/` rewrite, 慢一拍。
> 用户要求"主动策略": JS 能监控域名, 非主站域名第一次加载就直接走主站 rewrite, 不等 404 探测; 现有 404 fallback 保留作网络异常兜底。
> 相关审计见 `docs/bak-data-audit.md`(2026-08-11 备站多模块异常根因=CORS + 无兜底)。

## 一、当前备站加载链路清单(现状 2026-08-11)

### 1.1 前端数据加载统一入口: `fetchJSON()`(app.js L3660)
- 所有 `./data/*` 与 `https://ss.fx8.store/r2/*` 请求都经 `fetchJSON`(app.js 定义, lab.js 动态注入后共用同一全局函数; lab.js 自身无独立 fetchJSON, 只有 fetchJSONProgress L1741)。
- 链路: ①`_resultCache` 命中(时效敏感 URL 跳过, `_CACHE_TTL`=5min) ②`_inflightFetch` 并发去重 ③AbortController 15s 超时 ④`.gz` 方案已全跳(`tryGz=false`, 2026-08-01) ⑤cache-busting(`_NO_CACHE_URLS` 匹配的时效 URL 加 `?_=Date.now()`, cache mode 用 no-store; 其余 no-cache) ⑥**fallback 块**(L3732-3752): `url.startsWith("./data/")` 失败 → `_R2_FALLBACK_BASE + 文件名 + _bustQuery` 主站 rewrite, 独立 15s 超时 + 500ms 退避重试 1 次。

### 1.2 两类 URL 的处理
| URL 类别 | dataUrl() 生成 | 当前主路径 | 备站现状 |
|---|---|---|---|
| **小文件**(`./data/{name}.json`) | L3657-3659 `return "./data/" + filename` | 同源 `./data/` → 备站 404 → fetchJSON fallback 主站 `/data/` | 每请求先 404 再 fallback, 慢一拍 |
| **大 range 历史序列**(`-all/-5y/-3y.json`) | `_R2_LARGE_RANGE_RE=/-(?:all\|5y\|3y)\.json$/` → `_R2_DATA_BASE="https://ss.fx8.store/r2/data/" + filename` | 直链主站 `/r2/` 代理(ACAO:*, 边缘 HIT ~50ms) | **已主动直链, 无 404 探测, 无需改** |
| **lab/industry/public_fund/fund_score/trade_sim/index 详情** | 硬编码 `https://ss.fx8.store/r2/...`(app.js L4672/11508/12028-12035/15805/16158-16164 等, lab.js L1548-1726/2544/3503 等) | 直链主站 `/r2/` | 已主动直链 |

### 1.3 `./data/` 走 fetchJSON 的完整调用面(改 fetchJSON 一处即全覆盖)
- **app.js**: 40 处 `fetchJSON("./data/...")`(含 `fetchBoot()` L3785 的 `./data/boot.json` 首请求、overview/summary/intraday_snapshot/alert_analyze/signal_stats/futures 等) + 16 处 `dataUrl(...)`(a-stock/hk/global/sentiment 周期、etf_national_team、global-extras-all)。
- **lab.js**: `./data/lab_cost_compare.json`(L1573)/`lab_ablation`(L5294)/`lab_short_symmetry`(L5300)/`lab_param_scan`(L5306)/`alert_analyze_{iid}.json`(L6132/6704/6857)/`signal_kelly_backtest.json`(L7808, 均经 fetchJSON)。
- **无绕过 fetchJSON 的裸 `fetch('./data/')`**(已 grep 确认 app.js/lab.js 均无)。
- 特例: lab.js L7512 `signal_kelly_trades.json` 是**裸 fetch** `r2Url="https://ss.fx8.store/data/..."` → `cfUrl="./data/..."` 双兜底(0fee64eb7 已由 ssd 直链改主站 /data/, 已修, 不在本次范围)。

### 1.4 大 range 直链例外(必须保留)
`dataUrl()` L3658: `_R2_LARGE_RANGE_RE.test(filename)` 命中时返回 `_R2_DATA_BASE + filename`(`https://ss.fx8.store/r2/data/`), 备站本就直连主站(ACAO 已验), **主动域名方案不得覆盖此分支**(否则大 range 改走 `/data/` rewrite 语义变差)。小 range(3m/6m/1y)留 `./data/` 本地(主站 Worker 对 `-1m/-3m/-6m/-1y.json` 有 60s TTL 边缘缓存, 备站走主站也 OK)。

## 二、主动域名判断方案(推荐: 改 fetchJSON 入口, 不改 dataUrl)

### 2.1 为什么改 fetchJSON 而非 dataUrl
- `dataUrl()` 只覆盖 app.js 16 处; lab.js 的 `./data/` 直调(alert_analyze/kelly/lab_*)和 app.js 其他 40 处裸 `fetchJSON("./data/...")` 不走 dataUrl。改 dataUrl 漏掉大半调用面。
- `fetchJSON` 是**唯一 choke point**(app.js+lab.js 所有 `./data/` 请求必经), 入口重写一处全覆盖, 且 `fetchBoot()` 首请求也生效(备站第一次加载即主动主站)。

### 2.2 判断条件(复用现有 `_isMainSite()` 模式, app.js L20370)
```
主站/本地开发(同源, 不变): location.hostname === 'ss.fx8.store' 或 'localhost' 或 '127.0.0.1'
备站(主动主站): 其余任意域名(sss.sugas.site / s.sugas.site / 未来新站) → ./data/{f} → https://ss.fx8.store/data/{f}
```
用"非白名单"判断而非枚举备站域名: 新增备站/换域名无需改代码。已有 `_isMainSite()`(L20370)仅判 `ss.fx8.store`, 需补 localhost 分支(或新写 `_isBackupSite()`), 注意 `_isMainSite()` 当前被 auth 用(`_authApiBase` L20374), 不要改动其语义。

### 2.3 改动点(fetchJSON 入口, ~3 行)
```js
// 主动域名策略: 备站直接走主站 /data/ rewrite, 不等 404 探测; 主站/localhost 同源不变; 大 range 已在 dataUrl 直链 R2 不走此路径
const _isBackupSite = !_isMainSite() && !/^localhost$|^127\.0\.0\.1$/.test(location.hostname);
if (_isBackupSite && url.startsWith("./data/")) {
  url = _R2_FALLBACK_BASE + url.slice("./data/".length);   // 重写后 url 即主站绝对 URL
}
```
- 放在 fetchJSON 第一行(`_resultCache`/`_inflightFetch`/`_NO_CACHE_URLS` 判断之前): 重写后 cache key/inflight key/时效判断(`_NO_CACHE_URLS` 正则带 `(?:^|\/)` 边界, 对 `https://ss.fx8.store/data/overview.json` 仍匹配)全部基于主站绝对 URL, 语义一致。
- 主站: `_isBackupSite=false` → url 不变 → **行为完全不变**(主站 `./data/` 同源本就经 Worker `/data/`→R2 rewrite)。
- 大 range: `dataUrl()` 返回 `https://ss.fx8.store/r2/data/...` 不以 `./data/` 开头, 不被重写, **例外保留**。
- lab.js: 共用 app.js 的 fetchJSON 全局, 入口重写自动覆盖 lab.js 的 `./data/` 请求。

### 2.4 404 fallback 兜底衔接点(保留网络异常兜底)
- 重写后备站 url 已不以 `./data/` 开头, 现有 fallback 块 `if (url.startsWith("./data/"))`(L3732)在备站不再触发。**需把该块条件放宽为 `if (url.startsWith("./data/") || _isBackupSite)`**, 使其成为"网络异常兜底": 备站主请求已是主站 URL, 失败(主站网络抖动/单次 404)→ 用同一 `_R2_FALLBACK_BASE + 文件名` 重试 1 次(500ms 退避)。逻辑=现有块的 retry 分支, 只是触发条件从"./data/ 前缀"扩为"备站"。
- 这样实现双保险: ①主动域名 = 备站首请求直连主站(消灭 404 慢一拍) ②主站请求偶发失败 → 现有 500ms 退避重试仍在(网络异常兜底保留)。
- 主站/本地: fallback 块行为原样(`_isBackupSite=false` 且 url 以 `./data/` 开头时才触发), 零变化。

## 三、影响面 + 风险

### 3.1 CORS 现状(已确认, 无需新改)
- 主站 Worker `dataRewriteHandler`(worker/headers.js L169)/`r2ProxyHandler`(L105)所有返回分支**均已加 ACAO:\***: R2 响应(L197)、**缓存命中分支补头**(L117-119/L181-183, 0fee64eb7 修)、ASSETS 回退(L209-210)。
- curl 实测(2026-08-11):
  - `https://ss.fx8.store/data/overview.json` → 200 + `access-control-allow-origin: *`(no-store, NO_CACHE ttl=0)
  - `https://ss.fx8.store/data/a-stock-all.json` → 200 + `cf-cache-status: HIT` + ACAO:* + content-length 7155441
  - `https://ss.fx8.store/r2/data/hk-all.json` → 200 + HIT + ACAO:*
  - 带 `Origin: https://sss.sugas.site` 头跨域请求 → 200 + ACAO:* 正常放行
  - 备站 `sss.sugas.site/data/overview.json` → 404(前提坐实)、`s.sugas.site/data/overview.json` → 404
- **结论: 备站跨域直连主站 /data/ rewrite 的 CORS 已就绪**, 主动域名方案零额外后端改动。

### 3.2 边缘缓存命中
- 主站 /data/ 走 Worker Cache API 分层 TTL(worker/headers.js `dataCacheTtl` L149-166): overview/intraday_snapshot/board_etf_map=NO_CACHE(ttl=0, 每次回源 R2 ~50ms, 防 purge 失败残留旧版) / boot|notifications|summary|alert_analyze 等 60s / signal_stats|futures_acc_*|fund_score_top|trade_sim_indices 600s / 其余 3600s。
- 备站主动直连后与主站读同一边缘缓存, **二次请求 HIT ~50ms, 冷缓存回源 R2 一次**, 比现状(备站 404 + fallback 主站)更快。缓存一致性与主站完全相同(同 URL 同缓存)。

### 3.3 风险点
1. **备站不可直连主站时的降级**: 若用户仅主站故障, 备站主动域名也会挂(同源 `./data/` 也没数据) → 2.4 的退避重试只解决抖动不解决主站宕机。可接受: 备站本就无数据依赖主站, 现状也依赖主站 rewrite; 主站宕机时备站无从加载是既定架构。
2. **`_isMainSite()` 复用**: 现有函数只判 `ss.fx8.store`; 新增 localhost 判断不能改坏 auth(`_authApiBase` L20374 依赖它返回 false 才走 Bearer)。建议新写 `_isBackupSite()` 或在 fetchJSON 内联判断, 不动 `_isMainSite()` 语义。
3. **cache 语义**: 备站主动直连后 `fetch(url, {cache:'no-store'})` 对 overview 等时效 URL 不读浏览器缓存每次发 GET → 与主站行为一致; 主站 no-store 已由 Worker 兜底(ttl=0), 无新增陈旧风险。
4. **`_resultCache` 键变化**: 备站 cache key 从 `./data/x.json` 变 `https://ss.fx8.store/data/x.json`; 同一 tab 内一致(所有请求都重写), 不影响正确性。

## 四、§22 数据一致性影响
- **无影响, 反而更一致**: 主动域名后备站所有 `./data/` 请求与主站走**同一 R2 源 + 同一边缘缓存 + 同一 cache-busting**。数据来源单一化(主站 rewrite 即 R2), 多展示位(overview/board_etf_map/concepts)在备站读到的就是主站同版本, 不存在备站本地旧文件/不一致缓存。
- 备站本来就走主站 rewrite fallback(同源 404), 数据与主站同源; 主动域名只是"提前直连"而非"换数据源", §22 一致性不新增风险面。
- 大 range(§22 关键展示位: 走势图 -all.json)已在 R2 直链且走同一 r2ProxyHandler, 无变化。

## 五、实施要点(后续实施 agent 参考, 本次只读未改)
1. 改动文件: 仅 `static-site/app.js`(fetchJSON 入口 ~3 行 + fallback 条件放宽 ~1 行)。
2. 上线流程(§9): `scripts/build_min.py`(terser) + `scripts/bump_asset_version.py`(md5 破缓存) + **bump sw.js CACHE_VERSION** 三步缺一不可。
3. 自验(§22/§16): ①主站 ss.fx8.store 打开 DevTools Network 确认所有请求仍 `./data/` 同源 ②备站 sss.sugas.site 打开确认首请求直接 `https://ss.fx8.store/data/...` 且无 404 探测 ③curl 验主站 /data/ 各 TTL 分支 ACAO 仍在。
4. 回归(§15): 改的是全站数据入口函数(fetchJSON), 有隐藏影响面(被 40+ 处 app.js + 4 处 lab.js 调用) → 需派 reviewer 查影响面 + P0 smoke。
5. min 版验证用字符串非变量名(§9: terser mangle, grep `ss.fx8.store/data` 或中文字符串, 非变量名)。
