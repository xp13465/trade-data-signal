# 站点 console 告警根因：Report-Only CSP 白名单漏配

- 日期：2026-09-30
- 现象：线上 console 大量告警刷屏（用户报告「很多告警，把真告警淹没了」）
- 定位方法：Playwright 真实加载 overview/market/lab 多 tab，采集 console（error/warning/pageerror/CSP）+ 源码侧外连域名核实

## 结论
站点用的是 `Content-Security-Policy-Report-Only`（只报告、**不拦截**），但其 `connect-src` 白名单**漏了实际在用的行情数据源域名**。页面每次轮询行情，浏览器就记一条 `Connecting to '...' violates the following Content Security Policy directive: "connect-src ..."` 告警。30 秒内点 3 个 tab 抓到 **48 条**；盘中 60s 轮询长时间挂着会累积成百上千条，**淹没真正的错误**。

## 证据
- 当前 connect-src 白名单：`'self' https://web.ifzq.gtimg.cn https://hm.baidu.com https://*.tradingview.com wss://*.tradingview.com`
- 实际外连（均为 `fetch()`，命中 connect-src 违规）：

| 域名 | 用途 | 违规数(30s) |
|---|---|---|
| `push2delay.eastmoney.com`（+ `push2/2.push2/10.push2/20.push2.eastmoney.com` 多主机兜底 `_EM_HOSTS`） | 东财实时行情 | 46 |
| `d.10jqka.com.cn` | 同花顺盘中 JSONP（fetch 包装） | 2 |
| `qt.gtimg.cn` | 腾讯批量行情 | 未白名单 |
| `open.er-api.com` | 汇率 | 未白名单 |
| `api.gold-api.com` | 黄金 | 未白名单 |

## 根因
白名单没跟上功能演进：eastmoney / 10jqka / 腾讯 qt / 汇率 / 黄金数据源是后续加入的，CSP `connect-src` 一直未同步补全。

## 修法（一行级别，两处都要改）
`worker/headers.js`（`run_worker_first=true` 时生效）与 `static-site/_headers`（回退），connect-src 追加：

```
https://*.eastmoney.com https://qt.gtimg.cn https://d.10jqka.com.cn https://open.er-api.com https://api.gold-api.com
```
- `https://*.eastmoney.com` 一次覆盖 push2 / push2delay / 2.push2 / 10.push2 / 20.push2 多主机兜底。
- 效果：console 消噪，**零功能影响**（Report-Only 本就不拦）。
- 附加：`worker/headers.js` 的 connect-src 比 `_headers` 少 `https://ssd.fx8.store`，请确认该域是否还在用（现走 `/r2/*` 代理，可能已不需要）。

## 非 CSP 的真实错误（1 条，非本次修因）
`net::ERR_EMPTY_RESPONSE` ← `push2delay.eastmoney.com/api/qt/stock/trends2/get?secid=1.000016`。上游偶发空响应，代码已有 `_EM_HOSTS` 多主机故障转移兜底，会自愈，属一次性抖动。

## 验收哨兵
`scripts/playwright-accept/accept_console_clean.mjs`：断言「0 条 CSP 违规 + 0 个 pageerror」，让真告警不再被噪音淹没。当前对线上应 FAIL（CSP>0）；补白名单后应 PASS。
