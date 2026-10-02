# 首页「分析参考点AI监控走势图停 9-09」+「首页数据/角标停 09-17」根因调研报告

> 调研时间:2026-10-02 22:xx-23:xx · 调研 agent(researcher) · 全程只读(本机+云上 ssh 均未写任何文件)
> 症状①「AI监控走势图只到 9-09」、症状②「首页不少数据和角标显示在异常 09-17」合并调查

---

## 一、结论速览(先给结论)

| # | 问题 | 结论 | 证据 |
|---|---|---|---|
| 1 | 症状①走势图停 9-09 是哪条曲线 | 上曲线「实盘 vs 回测准确率」和下曲线「综合过拟合风险分」**同一条数据源**,两条都停(数据源本身停) | 两条曲线都读 `overfit_monitor.json` 的 accuracy.rolling / overfit.daily_by_dim(app.js:2283-2302) |
| 2 | 数据来自哪个产物 | `static-site/data/overfit_monitor.json`(主)+`overfit_monitor_ext.json`;生成脚本 `scripts/overfit_monitor.py`(每日 21:40 打点);R2 key `data/overfit_monitor.json` | app.js:1644/2286-2290 |
| 3 | 为什么停在 9-09 | **线上 R2 上的 overfit_monitor.json 是 9-16 23:01 旧版**(rolling 曲线末点=20260909);云上数据树有 9-30 21:40 新版(rolling 到 9-29)但未同步到 R2;且今天 16:41 本机旧数据上传又覆盖/保持了 R2 旧版 | 见 §三 证据链 |
| 4 | 症状②角标 09-17 | 线上 `boot.json` 是今天 16:36 本机 export 生成、16:41 上传的**旧版**(内嵌 overview/summary/intraday 全 9-17);前端首屏单 fetch boot 分发,方案A只保护 overview,其余 10 个内嵌 JSON 直接采信 → 09-17 角标散布 | 见 §四 |
| 5 | 9-09 与 09-17 是否同源 | **同源(同一事故的两次体现)**——都是「今天 16:36-16:41 本机跑 export 自动上传 R2,用本机旧数据覆盖线上」造成;但停点不同:9-09=overfit 文件本身 9-16 版(rolling 末点 9-09),09-17=boot 内嵌的 overview/summary 等是 9-17 版 | 见 §六 同源性判据 |
| 6 | 归因三选一 | **归因②「三处文件版本不一致」为主,叠加归因①「上游数据真停更」为辅**。线上读到的不是最新产物(R2 旧版/boot 旧版),云上数据树有新版但 deploy 链一直失败推不上 | 见 §五 |

**一句话根因**:10-02 冰点功能上线闭环的 iceexport agent 在本机(trade-data 侧)重跑 export,未设 `EXPORT_SKIP_R2=1`,`export.py` L1420 自动上传 R2,把**本机旧数据**(本机 DB 停 9-17、overfit 停 9-16)覆盖到线上;叠加云上 4 次 deploy 因 fund_nav 校验失败全部终止,云上 10-01 新版从未上线 → 线上用户看到旧数据(overfit 9-09 / boot 09-17)。

---

## 二、数据链路与读取路径(背景)

- **overfit_monitor.json**(3.8MB,R2 大文件):每日 21:40 由 `scripts/overfit_monitor.py` 打点(交易日),主文件 + `_ext.json`(by_k/filtered_by_k 拆分)。前端 `dataUrl()` 对非 `-all/-5y/-3y` 后缀走 `./data/`(备站重写主站 `/data/` rewrite → R2),app.js:9555-9610。
- **boot.json**(2MB):`static-site/export.py` export_boot() 合并 11 个首屏 JSON(overview/signal_stats/intraday_snapshot/summary/alert/ma_alignment/position/ad_line/volume_ratio/new_high_low/trade_sim_indices),前端首屏单 fetch `./data/boot.json`(app.js:9723-9730、9786)。
- **R2 上传链**:`upload_r2.py` upload-data-large(overfit 前缀必传);`export.py` L1419-1420 `EXPORT_SKIP_R2 != "1"` 时自动跑 10 个上传命令;deploy.sh L22 会设 `EXPORT_SKIP_R2=1` 避免重复。

---

## 三、症状①证据链(走势图停 9-09)

### 3.1 线上(用户看到)的实际数据
```
$ curl -s -A "<浏览器UA>" https://ss.fx8.store/data/overfit_monitor.json | grep generated_at
generated_at: 2026-09-16 23:01
rolling 末点: 20260909 (buy win_rates 序列末点)
```
- ss.fx8.store / ssd.fx8.store(R2 直读)两处**完全一致**:`generated_at=2026-09-16 23:01`,rolling 停 `20260909`,etag=`52523f125dc249ed70ac3b4398be4711`,R2 last-modified=`Fri, 02 Oct 2026 08:41:06 GMT`(=北京 16:41)。
- config 里 `trades_generated_at=2026-09-13 05:10`、`signal_daily_max_date=20260911` —— 文件整体是 9 月中版本。

### 3.2 云上数据树(应有的新版)未被同步
```
云上三棵树(写盘树/两棵 git 树)overfit_monitor.json 均为 9-30 21:40 版:
  generated_at="2026-09-30 21:40", rolling 末点=20260929, md5=5948d1f751db572c23e7675773381464
```
- 云上 `overfit_monitor_launchd.log`:9-16~9-30 每天 21:40 打点 rc=0;R2 上传段:9-17/9-30「上传完成」,9-18/9-21/9-22/9-23「timed out」,9-24/9-28/9-29「SKIPPED_LOCKED」。
- 云上状态文件 `.r2_data_large_state.json` `updated_at=2026-10-01T21:26:40` 记录 overfit md5=5948d1f(9-30 版)—— 与云上树一致,但 **R2 实际 etag=52523f(9-16 版)**,状态文件与 R2 实际矛盾。

### 3.3 实锤:今天 16:41 本机上传旧数据覆盖 R2
```
R2 overfit last-modified: Fri, 02 Oct 2026 08:41:06 GMT = 北京 16:41
本机 /Users/linhuichen/code/trade-data/data/.r2_data_large_state.json updated_at=2026-10-02T16:41:30  ← 实锤今天 16:41 本机跑过 upload-data-large
本机 /Users/linhuichen/code/trade-data/static-site/data/overfit_monitor.json md5=52523f125dc249ed70ac3b4398be4711 ← 与 R2 etag 逐位一致
本机 trade-data/static-site/data/overfit_monitor.json generated_at="2026-09-16 23:01" mtime=09-16 23:01:58 ← 本机这份本来就是 9-16 旧版
```
- 本机 iceexport agent(16:47 完成)进度文件 `/tmp/agent-progress-iceexport.md` 记录:「步骤2 本机重跑 export: trade-data 侧 --incremental」。
- `export.py` L1419-1420:未设 `EXPORT_SKIP_R2` 时自动上传 R2。iceexport 在本机跑 export 未设该变量 → 16:41 自动上传,用本机旧 overfit(9-16)覆盖 R2。

### 3.4 rolling 末点为何是 9-09(曲线停在哪的机理)
`scripts/overfit_monitor.py` L1113-1136 rolling_win_rates:**n=0 的桶 continue 跳过**(只输出「有样本」的日期点);L1003-1083 bucket_actual 今日信号(d>=latest_date)不计。因此 9-16 版文件里,9-10 无买类样本被跳过、末点落在 20260909。曲线「看起来停在 9-09」= 数据文件末点 9-09。

---

## 四、症状②证据链(首页角标 09-17)

### 4.1 线上 boot.json 是今天本机生成上传的旧版
```
线上 ss.fx8.store/data/boot.json:
  _meta.generated_at = 2026-10-02 16:36:55
  boot.overview.date = 20260917, collected_at = 20260917 21:00:01
  boot.summary.date = 20260917
  boot.intraday_snapshot.collected_at = 2026-09-17T20:35:01
  boot.alert.date = 20260911
  etag = d6d395637bfe77adfd466add2150a186, R2 last-modified = Fri, 02 Oct 2026 08:41:01 GMT(=北京16:41)
本机 /Users/linhuichen/code/trade-data/static-site/data/boot.json: md5=d6d395637bfe77adfd466add2150a186 ← 与线上 etag 逐位一致
本机 trade-data/static-site/data/boot.json mtime=10-02 16:36:55 ← 今天 16:36 本机生成
```

### 4.2 前端如何把 09-17 散布到多张卡
- 首页首屏单 fetch `./data/boot.json`(app.js:9786),分发到 11 个模块(app.js:9723-9730)。
- **方案A(2026-08-06 防「成交额卡显示昨日值」)只保护 overview**:app.js:9792-9797 `boot.overview.date >= _bjTodayStr()` 才 setCachedOverview;boot 内嵌 overview=9-17 < 今天 10-02 → **不缓存**,renderOverview 独立 fetch `overview.json`(线上独立 overview 是 10-01 新版 386d7f9)。
- **其余 10 个内嵌 JSON 无日期保护直接采信 `_bootData`**:app.js:9800 `state.signalStats = boot.signal_stats`、app.js:9803 boot.intraday_snapshot、app.js:15529 boot.alert、app.js:15663 boot.summary、app.js:17320/17354/17394/17395/17396 boot.ma_alignment/position/ad_line/volume_ratio/new_high_low → 全部显示 9-17 版数据 → 用户看到「不少数据和角标 09-17」。

### 4.3 为什么云上 10-01 新版从未上线
云上今天 4 次 deploy(02:05/05:00/16:40/17:50)日志尾部全部是:
```
=== 汇总: 38 ok / 3 warn / 1 fail ===
✗ 数据产物校验失败(退出码 1)，终止部署（4 类事故拦截）
✗ fund_nav: DB↔产物不一致: ... DB 领先产物 6 天
```
- deploy.sh 结构:段1 锁外 export+R2+rsync,`check_data_integrity.py --deploy-mode`(deploy.sh L324)在 R2 上传前,**fund_nav FAIL 直接 exit 1,到不了 R2 上传段(deploy.sh L679 run_r2_upload)**。
- 云上 16:40 deploy 的 export 已生成新版 boot(generated_at=16:45:23,boot.overview.date=20261001),但校验失败终止未上传 → 线上 boot 仍是 16:36 本机旧版。

---

## 五、归因判断(三选一)

**归因②「三处文件版本不一致(前端读到旧文件)」为主 + 归因①「上游数据真停更」为辅:**

| 文件 | 线上(用户看到) | 云上数据树(应有) | 本机 | 状态 |
|---|---|---|---|---|
| overfit_monitor.json | 9-16 23:01(rolling 停 9-09) | 9-30 21:40(rolling 到 9-29) | 9-16 23:01(今天 16:41 上传者) | **不一致** |
| boot.json | 16:36 生成、内嵌全 9-17 | 10-01 新版(17:50 生成,未上线) | 16:36 生成(今天 16:41 上传者) | **不一致** |
| overview.json(独立) | 10-01 新版(386d7f9,18:10 上传) | 10-01/10-02 | 9-17 旧版(d3fb7d7a) | 线上 vs boot 内嵌不一致 |

- 线上**独立 overview.json**(386d7f9,date=20261001,collected_at=20261002 16:48:04,last-modified 18:10 GMT+8)与线上 **boot 内嵌 overview**(9-17)不一致 —— §22 一致性违反的活体例子。
- 云上数据树整体是 9-30/10-01 新版,并非上游真停更;但**本机数据树(DB 停 9-17)是真旧**,是本机 export 产物旧的原因。

---

## 六、9-09 与 09-17 同源性判据

**同源**。判据:
1. 两者同一时刻同一进程产生:R2 last-modified 今天 16:41(boot=08:41:01 GMT,overfit=08:41:06 GMT),本机状态文件 16:41:30,iceexport 进度 16:47 完成 —— 同一窗口。
2. 两者都来自本机 trade-data 旧树:线上 boot etag=本机 boot md5,线上 overfit etag=本机 overfit md5,逐位一致。
3. 两者都是本机数据树陈旧导致:本机 sentiment.db/etf_national_team.db max_date=20260917(本机纯开发不跑采集),overfit 文件本身停在 9-16。
4. 停点不同是因为文件不同:overfit 文件 9-16 版 → rolling 末点 9-09;boot 内嵌的 overview/summary 等来自本机 9-17 DB → 09-17。

---

## 七、影响面清单(消费方)

### overfit_monitor.json(9-09 症状)
- 「分析参考点AI监控卡」双曲线(实盘/回测准确率 + 综合过拟合风险分)主图(app.js:1643-1661)
- 首页「AI 建议」枯竭 chip 共享数据源(app.js:2640-2641, 共享 promise 防 27MB 双拉)
- T3-2 recent 明细逐信号键命中标注(app.js:2016, 7 模式组集聚合)

### boot.json(09-17 症状,首屏单 fetch 分发 11 模块)
- overview 卡(情绪分/恐贪/成交额/热力图)—— **方案A保护,实际独立 fetch overview.json(10-01 新版),此卡不受 09-17 影响**
- signal_stats(信号统计)、summary(收盘分析)、intraday_snapshot(盘中快照初始值)、alert(告警)、ma_alignment(均线)、position(仓位)、ad_line(涨跌线)、volume_ratio(量比)、new_high_low(新高新低)、trade_sim_indices(模拟回测品种)
- **这 10 个直接采信 _bootData → 显示 9-17 旧数据**

### overview.json(独立,386d7f9)
- 方案A fallback 路径 + 独立 fetch 场景(线上为 10-01 新版,正常)

### 受影响定时任务链路(判断因果)
- 云上 deploy 从 10-02 起 4 次全失败(fund_nav 校验):`deploy_20261002_0205/0500/1640/1750.log` 尾部均「✗ fund_nav DB↔产物不一致: DB 领先产物 6 天」。**与 9-09/09-17 无直接因果,但它是云上新版推不上去的原因**,使「本机旧数据覆盖」成为唯一改变线上数据的动作 → 放大事故。
- 云上「两棵树 data/ 写读分离」盲区:本次 R2 状态文件(云上树记 9-30 版)与 R2 实际(9-16 版)矛盾,体现该盲区;但**主根因仍是本机 16:41 上传**。

---

## 八、修复方向建议(供主控验收,不含实施)

1. **止血(立即)**:用云上 9-30/10-01 新版数据重传 R2 —— 云上跑 `upload_r2.py upload-data-large`(或先修 fund_nav 校验让 deploy 通过)。线上 overfit/boot 应恢复为云上树版本。
2. **根因(防再犯)**:
   - `export.py` 自动上传 R2 的默认行为在本机场景很危险:本机数据树陈旧时,本机 export 会覆盖线上。建议本机开发跑 export 一律显式 `EXPORT_SKIP_R2=1`,只有 deploy 链(校验通过后)才允许写 R2(类似 deploy.sh L22 的做法下放到所有本机入口)。
   - 本机 trade-data 数据树应定期同步或明确标记「只读开发镜像,禁止作为 R2 上传源」。
3. **§22 一致性**:boot 内嵌 overview 与独立 overview.json 脱节(boot 16:36 版内嵌 9-17,独立 18:10 版 10-01)——修复后需机检 boot.overview.date == overview.date。
4. **上游真停更的确认**:云上数据树为 9-30/10-01 新版,上游并未真停更;若用户之前(10-01 前)看到 9-09,则与 R2 上传链 9-17~9-29 期间 timed out/SKIPPED_LOCKED 相关,属另一问题(R2 上传可靠性),本次未深挖,标注待查。

---

## 九、证据文件清单

| 类型 | 位置 | 关键值 |
|---|---|---|
| 前端取数 | static-site/app.js:1644, 2283-2302, 9555-9610 | dataUrl()/fetchJSON |
| 前端方案A | static-site/app.js:9792-9803 | 只保护 overview |
| boot 分发 | static-site/app.js:9723-9730, 15529, 15663, 17320/17354/17394 | _bootData 采信点 |
| 打点脚本 | scripts/overfit_monitor.py:1003-1136, 1841-1878 | bucket_actual/rolling 跳过/R2 上传 |
| 自动上传 | static-site/export.py:1419-1420 | EXPORT_SKIP_R2 开关 |
| deploy 校验 | scripts/deploy.sh:324(fund_nav FAIL exit), 679(run_r2_upload) | 校验在 R2 前 |
| 本机证据 | /Users/linhuichen/code/trade-data/static-site/data/{boot,overfit_monitor,overview}.json | md5/etag 逐位一致 |
| 本机状态 | /Users/linhuichen/code/trade-data/data/.r2_data_large_state.json | updated_at=16:41:30 |
| 云上日志 | /home/ubuntu/code/trade-data/data/logs/{deploy_*,overfit_monitor_launchd}.log | fund_nav FAIL / 上传段 |
| 云上树 | /home/ubuntu/code/trade-data(-signal/-staticdata)/static-site/data/overfit_monitor.json | 9-30 21:40, md5 5948d1f |
| agent 进度 | /tmp/agent-progress-iceexport.md / icelive.md | 本机重跑 export / 线上 overview=d3fb7d7a |

> 诚实标注:
> - 线上独立 overview 386d7f9(10-01 新版)的**上传来源未 100% 钉死**(last-modified 18:10 GMT+8,内容 collected_at=16:48:04,疑似 icelive 验收后某进程上传),但它与 boot 内嵌 9-17 的不一致是本报告归因②的活证据。
> - 「R2 上传链 9-17~9-29 timed out/SKIPPED_LOCKED 是否让用户在 10-01 前就看到 9-09」未深挖(R2 上传可靠性问题,与本次主根因正交),标注待查。
