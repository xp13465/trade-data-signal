# 首页历史信号弹窗走势图盘中缺「当日点」调研报告(2026-09-11)

> 调研 agent 产出(只读,未改任何代码)。任务来源:#107 首页点「历史信号」进走势图看不到当日点,点「当日信号」能看到。
> 调研方法:UI 渲染层 grep(app.js openSignalChartModal/_appendIntradayEstimate)→ 数据产物层 curl(R2 index/{iid}-all.json 逐个对比末日)→ 生成层查库(index_daily 当日覆盖 vs 历史信号宇宙缺口)→ 9/7 修复 diff 评估 → 腾讯 qt 实时源可行性实测。

## 一、根因结论(一句话 + 证据链)

**首页历史信号弹窗盘中无当日点 = 数据层缺 9/11 行:盘中只重导「今日 index_daily 有当日行的指数」(9/7 修复的 affected 交集),而历史信号宇宙 178 个指数中有 103 个(中证 csi_*/gz_*/外盘/港股行业等)今日盘中 index_daily 无当日行 → 不重导 → R2 index/{iid}-all.json 停在 20260910 → 前端无当日点可画。前端兜底补点 `_appendIntradayEstimate` 又只对 17 基础指数生效 → 补点失败 → 静默缺(且因该指数今日无信号,连滞后提示都不显示)。**

### 证据链

| # | 证据 | 位置/命令 |
|---|---|---|
| E1 | 首页信号弹窗数据源 = R2 直链 `index/{iid}-all.json`,走 fetchJSON(命中 `_NO_CACHE_URLS` no-store,不缓存) | static-site/app.js:10437 + L9157 正则实测 True |
| E2 | 盘中 affected 动态合并 = 17 基础 + 「index_daily 当日行 ∩ 历史信号宇宙」(9/7 修复) | app/collector/intraday_snapshot.py:2049-2055 |
| E3 | 前端补点只认 17 基础:非 `_SNAPSHOT_IID_TO_CODE` 直接 `return false` | static-site/app.js:31198-31199 |
| E4 | 今日(20260911)index_daily 仅 75 行(17 基础 + 31 sw_ + 27 thsc_);历史信号宇宙 178 个,缺口 103 个 | SQL:`SELECT index_id FROM index_daily WHERE date='20260911'` vs `SELECT DISTINCT index_id FROM signal_daily` |
| E5 | R2 实测:当日信号指数(9/11 有信号)thsc_308870/csi500/cgb_idx/hsi/bj50/cgb_10y_etf 末日全部 = 20260911;历史信号指数 csi_399986/csi_H30590/csi_930997/csi_000680/hk_cesg10/sz_div 末日全部 = 20260910(停昨) | `curl https://ss.fx8.store/r2/index/{id}-all.json` 取 ohlc[-1].date |
| E6 | sw_801130(9/8 有历史信号的申万行业)末日=20260911,但 9/10/9/11 行 open/high/low=None(盘中 `_backfill_industry_daily` 只写计算法 close) | curl R2 sw_801130-all.json 末尾 3 根 |

## 二、数据层 vs 展示层判定

**主症 = 数据层缺**(90%):103 个历史信号指数的 R2 `index/{iid}-all.json` 里根本没有 20260911 行(E5),前端无点可画。这不是前端过滤问题。
**次症 = 展示层可改进**(10%):`_appendIntradayEstimate` 补点只覆盖 17 基础(L31199);滞后提示 `_hasTodaySigB2` 只在「该指数今日有信号」时显示(L10517),历史信号指数今日无信号 → 缺当日点且**静默**(无任何提示)。

## 三、9/7 修复覆盖评估

- **9/7 修复 diff 仅 1 个文件**:`app/collector/intraday_snapshot.py`(17+/4-,仅改 affected 合并查询 SQL)。
- **首页信号前端链路(app.js openSignalChartModal L10437 / fetchJSON R2 直链 / intraday_snapshot.sh upload-index R2 通道)当时完全不在 diff 内**——9/7 是「生成侧依赖项」间接覆盖:依赖盘中反哺把当日行写入 index_daily,交集命中才重导。
- **覆盖结果**:sw_/thsc_/17 基础(75 个)盘中 R2 到 9/11 ✓;103 个(中证/港股行业/外盘等)**漏网**。
- **定性 = §23.3 举一反三盲区**:9/7 只修了「今日 index_daily 有行的老信号指数」,没覆盖「今日 index_daily 无行的」——但后者是常态(盘中实时采集只覆盖 17 基础 INDEX_CODES,intraday_snapshot.py:41-58;csi_/gz_/外盘盘中根本不采),故盲区覆盖面达 103/178≈58%。

## 四、同类展示位清单(§23.2 同类错误面)

| 展示位 | 数据源 | 当日点状态 | 原因 |
|---|---|---|---|
| 首页信号弹窗 openSignalChartModal | R2 index/{iid}-all.json | **缺(主诉)** | 103 个历史信号指数停 9/10 |
| 情绪分走势图叠指数曲线 _emotionIndexCurve | index/{base}-all.json(仅 6 宽基) | 不缺 | 6 宽基 ∈ 17 基础,盘中重导 |
| market tab 指数走势卡(_marketIndexCardLazy) | a-stock/hk/global-all.json(聚合链) | 同源风险(次要) | 聚合文件盘中重导范围同 index_daily 当日行,非 17 基础/反哺指数盘中同样缺;但展示清单 ≠ 历史信号宇宙,需单独核对 |
| 凯利卡交易记录弹窗 lab.js _openEtfTrendPinModal | R2 etf/{code}-all.json | **缺(更严重:停 9/9!)** | export_etf_hist 9/10 待传 0/1552(源未返 9/10 数据),R2 停 9/9,9/10/9/11 点均无 |
| 首页/凯利区 sim ETF 走势弹窗 app.js _openSimEtfTrendPinModal | R2 etf/{code}-all.json | **缺(同上)** | 同上,L4610 |
| 盘中增量表 common.js L1614(复用 lab 全局) | R2 etf/{code}-all.json | **缺(同上)** | 同上 |
| ETF 评分弹窗 period tab | R2 etf/{code}-all.json | **缺(同上)** | upload_r2.py:567-570 注释确认同一数据源 |

**etf/{code}-all.json 链路独立于本次主诉,但同类更严重**(R2 停在 9/9,9/10+9/11 全缺),9/10 17:50 的 export_etf_hist 生成内容与 9/9 逐字节相同(日志「待传 0/1552」),判定新浪 fund_etf_hist_sina 源未返回 9/10 数据(疑似源滞后/抓取异常),待 9/11 17:50 后观察是否自愈。

## 五、修复方案建议(最小改动 → 根治)

### 方案 A(生成侧根治,推荐,一步到位)
盘中 intraday_snapshot 把 affected 交集从「今日 index_daily 有行」扩为**「历史信号宇宙全量 ∩ 腾讯 qt/新浪有实时码」**,盘中批量采一次实时价 → UPSERT 写 index_daily 当日行(close 计算法或完整 OHLC)→ 9/7 修复的 affected 重导逻辑自动覆盖 → upload-index 传 R2 → 前端当日点。

- **可行性已实测**:腾讯 qt 实时支持 `sz399986`(中证银行 7619.79 实时)/`sh000680`(科创综指)/`r_hkCESG10`(中华博彩)/`r_hkHSI`,即 103 缺口中大部分 csi_/hk_ 可盘中采到实时价。
- 需建 index_id → 腾讯码映射(6 位代码前缀 sh/sz/r_hk 规则;csi_399986→sz399986、csi_000680→sh000680、hk_cesg10→r_hkCESG10;部分如 sh000330 腾讯无码,回落新浪或跳过)。
- 外盘(us_*/dax/cac40/kospi/nikkei):盘中(北京交易时段)外盘多已收盘,「当日点」按外盘最新交易日,需按 global 源口径判断是否纳入。
- 边界:非交易日 qt 返回旧价,index_daily 当日行无意义 → 补采前按交易日闸门;cgb_10y_future(T0 主连)实时源不支持(既有注释),保持缺 + 提示。

### 方案 B(展示层兜底,配合 A 或独立)
扩展 `_appendIntradayEstimate`:
- sw_/thsc_ → 从 intraday_snapshot.industries/concepts 当日涨跌幅 × 前收算当日 close 补点(可独立生效,覆盖 58 个);
- 滞后提示条件从「今日该指数有信号」扩为「末日<T 日且补点失败」即显示,杜绝静默缺。

### 推荐
**A 为主 + B 为兜底**:A 根治数据层(让历史信号指数盘中也有当日点,与当日信号一致),B 消灭静默缺(无源指数如 cgb_10y_future 至少给提示)。A 需动采集器(intraday_snapshot.py + 映射表),属于生成侧改动,涉及定时任务行为;若不改 A,仅 B 无法让 csi_/hk_ 有当日点(前端不能跨域拉腾讯 http 接口),只能加提示。

## 六、诚实标注

- **修复难度/风险**:方案 A 需新增盘中补采 100+ 指数实时价,单轮耗时估计 +2~5s(批量腾讯 qt),有反爬/限流风险(同 sw/ths 源需串行),建议 try/except 容错不阻断主链路(9/7 已采用单指数失败不阻断模式);映射表需逐一核对 103 个码可得性(部分腾讯无码)。
- **是否需动定时任务**:是——intraday_snapshot.sh 链路(盘中每 10 分钟)需含补采逻辑;17:50 update_all 不受影响(全量 export 已完整)。
- **etf/{code}-all.json 链路(R2 停 9/9)**:疑似新浪数据源 9/10 未返当日数据,需观察 9/11 17:50 update_all 是否自愈;未自愈则独立排查 akshare fund_etf_hist_sina 采集失败根因(与本次主诉独立)。
- **本地主仓 static-site/data/index 停 9/10**:盘中任务跑在 trade-data(REPO),主仓这份是 git/deploy 落盘,非用户所见;R2 才是前端实时源(已确认)。

## 复现

- **脚本/命令**:
  1. 查今日 index_daily 覆盖缺口:`python3 -c "import sqlite3; c=sqlite3.connect('/Users/linhuichen/code/trade-data/data/sentiment.db'); print(len(c.execute(\"SELECT DISTINCT index_id FROM index_daily WHERE date='20260911'\").fetchall())); print(len(c.execute('SELECT DISTINCT index_id FROM signal_daily').fetchall()))"` → 75 / 178
  2. 验 R2 末日:`curl -s https://ss.fx8.store/r2/index/{csi_399986|thsc_308870}-all.json | python3 -c "import json,sys; d=json.load(sys.stdin); o=d['ohlc']; print(o[-1][0] if isinstance(o[-1],(list,tuple)) else o[-1].get('date'))"` → csi_399986=20260910,thsc_308870=20260911
  3. 9/7 diff:`git show ac5d32b5f --stat` → 仅 app/collector/intraday_snapshot.py
- **输入依赖**:trade-data/data/sentiment.db(index_daily/signal_daily);R2(ss.fx8.store)index/*-all.json
- **数据截止**:2026-09-11 盘中 10:36(交易日)
- **关键口径**:前端走势图 = 折线(取 close,`_indexChartBuildOption` L8728-8739);盘中实时采集仅 17 个 INDEX_CODES(intraday_snapshot.py:41-58);反哺 sw_ 只写计算法 close(open/high/low=NULL,L1230)
