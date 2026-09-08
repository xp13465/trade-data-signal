# 盘中补跑 signal_kelly_backtest 可行性调研 + 设计(2026-09-08)

> 调研方:researcher(只读,未改任何代码/未写库/未写产物)
> 背景:交易记录 signal_kelly_trades.json 由 scripts/signal_kelly_backtest.py 全量回测生成(export.py L1204-1213 subprocess 调用,launchd 17:50 update-all 一天一次)。定价机制=信号次日开盘价,9/7 信号需 9/8 开盘价,当前要等 9/8 17:50 才入账。用户已拍板方向 A(开盘后补跑一轮,候选时点 9:40)。本报告回答「能不能跑、怎么跑才不污染历史」。

---

## 0 可行性结论(一句话)

**方向 A 可行,但绝不能盘中裸跑全量回测**——盘中 etf_daily 当天行是占位态(1540 只占位价),信号库里还有 9/8 当天盘中临时信号,裸跑会污染/消失已入账历史交易。**唯一安全形态 = 增量追加「只算 T 日信号」档,历史交易零改动,并加数据就绪闸**(9/8 真实开盘价能拿到才发,拿不到跳过本轮等 17:50)。

---

## 1 逐条调研证据

### 1.1 开盘价就绪度(问题 1)——9:40 时 9/8 真实开盘价不在 etf_daily,不可用

**实况(读主库 etf_national_team.db,2026-09-08 盘中 10:2x):**

```
按日统计占位特征(date | 总行 | accum_nav=1.5 | open=1.49 | close NULL | etf_name=etf_code):
20260901 | 1484 | 0 | 0 | 0 | 0
20260902 | 1487 | 0 | 0 | 0 | 0
20260903 | 1488 | 0 | 2 | 0 | 0
20260904 | 1490 | 0 | 1 | 0 | 0
20260907 | 1491 | 0 | 1 | 0 | 0     ← 收盘日无占位
20260908 | 1552 | 1540 | 1540 | 1540 | 1540  ← 盘中 1540 只全占位
```

- 9/8 共 1552 行,其中 **1540 行占位**:`accum_nav=1.5` / `open=1.49` / `high/low/close/amount=NULL` / `etf_name=etf_code`(全同值,与真实采集不同价)。
- 仅 510300/510500/512100 等极少数宽基 9/8 有真实 `close`(如 510300=4.634),`accum_nav` 仍空。
- 逐只佐证:516660 真价沿革 9/4 open=0.959/close=0.939/nav=0.94,9/7 open=0.94/close=0.944/nav=0.9432,**9/8 却 open=1.49/close=NULL/nav=1.5**——与真价完全无关,纯哨兵占位。
- 全局最新非占位 accum_nav 日 = 20260907(9/8 盘中 accum_nav 全假/空)。

**写入来源(部分定位 + 诚实标注缺口):**
- `_upsert_daily`(app/collector/etf_national_team.py L949-969)是全仓唯一写 etf_daily 的 UPSERT 入口(除 backfill_etf_daily.py L136 独立 INSERT);`INSERT INTO etf_daily` 语句全仓 grep 只有这两处。
- **具体触发脚本未完全定位**:9/8 09:08 deploy 的 backtest 产物(09:15)里 9/7 信号零交易,证明 09:08 时 9/8 有效价(accum_nav 非 NULL)尚不存在;10:2x 已占位 → **占位行在 09:08-10:2x 窗口内写入**,且是每个交易日盘中常态(reviewer 观察一致:9/4/9/7 收盘日无占位,盘中写入、收盘后被真实数据覆盖)。
- 占位值全同为 1.5/1.49,符合「数据源未开盘哨兵价」特征而非真实采集;真实 open/close/accum_nav 收盘后覆盖(17:50 update-all 的 pipeline_daily L1159 写 OHLC + update_accum_nav L2120 写 nav;20:07 etf-national-team backfill 兜底)。
- **实施前建议**:盘中复现一次,逐链路定位写占位的那个脚本(候选:盘中全市场 OHLC 采集经 `_upsert_daily` + 数据源返回哨兵价;`universe_etf_codes` 名称取不到时 `etf_name` 回落 code,见 etf_national_team.py L242)。

**结论:9:40 时 9/8 真实开盘价不在 etf_daily。**

### 1.2 信号就绪度(问题 2)——9/7 信号 9:40 已在库,但盘中会混入 9/8 临时信号

- `signal_daily` 表在 **sentiment.db**(app/db.py L5 `DB_PATH=.../data/sentiment.db`,表 L47-52)。盘中 9:40 读实况:
  - **9/7 信号 10 条已固化**:`buy_aux ×3(csi_399976/csi_930632/csi_930997)` + `buy_special ×2(sw_801140/sw_801210)` + `sell ×3 + band_hold ×2`。9/7 17:50 update-all 已写入,盘中在库。
  - **9/8 当天盘中临时信号也在**:9/8 已有 9 条(含 **6 条 buy 系** `buy_special`),由盘中每 10 分钟 intraday-snapshot 的 `recompute_all_signals`(etf_national_team.py L1105-1112,DELETE+INSERT 覆盖)+ check_signals 生成——盘中临时态,收盘后会被 17:50 最终信号覆盖/消失。
- 盘中 9/7 信号的评级(10d score)取自 signal_stats(盘后算,盘中不变),所以 9/7 信号 + 评级在 9:40 与盘后一致;但 **9/8 盘中信号是污染源**。

### 1.3 盘中 close 缺失对全量回测的影响(问题 3,最关键)——裸跑必污染历史

证据链(scripts/signal_kelly_backtest.py 行号):

1. **占位价被当成真价读进来**:读价 SQL(L482-493)
   ```sql
   SELECT etf_code, date, accum_nav, open, close FROM etf_daily
   WHERE etf_code IN (...) AND accum_nav IS NOT NULL   -- 占位 accum_nav=1.5 非 NULL → 被选入!
   ```
   → `nav_map[code][20260908]=1.5`、`open_map[code][20260908]=1.49`,且 9/8 进 `sorted_dates`。

2. **9/7 信号买入定价被 9/8 假价接管**(L561-568,KELLY_BUY_NEXTDAY=1):
   - `nxt_open = open_map[code][next_trading_day(9/7)]` → next_trading_day=9/8(L506-511,因 9/8 已进 sorted_dates)→ **nxt_open=1.49 假价**。
   - `gap = 1.49 / (9/7真close) - 1`;`PSEUDO_GAP_EXCLUDE=0.20`(L77):
     - `|gap| > 20%` → 整笔剔除(L567-568)→ **9/7 该入账的交易消失**(如 516660 gap≈0.585→剔除);
     - `|gap| < 20%`(信号 ETF 昨收接近 1.24-1.87 时)→ **以假买入价 `1.5×(1.49/close)` 入账**。

3. **「持有中」交易 current_price 用 9/8 假 nav**(L593-601 + L1129):`today_str = max(各 ETF sorted_dates)` → 9/8;`current_nav = prices.get(9/8) = 1.5` → 近 hold_days 内(≤15 个交易日)的所有持仓交易盈亏被假价重估,浮盈/浮亏跳变。

4. **止盈/卖出价污染**(L641-652):A/B/C/D/E/F 模式的 `future_dates` 若含 9/8,止盈检查用 1.5 假 nav;卖出价 `prices[sell_date]` 同样可能取到 9/8 占位。

5. **大盘择时被盘中态改变**(额外污染):intraday-snapshot 每轮「index_daily 反哺完成」(日志实证)把 9/8 盘中实时指数写入 index_daily → 回测 `_load_market_state`(L335-353,hs300 MA60)与 `_load_market_tiers`(L355-398)读到 9/8 盘中态 → **历史 A 股信号的牛市/熊市过滤判定被盘中未收盘状态改变**。

6. **9/8 盘中临时信号不产生交易但进统计**:9/8 信号次日(9/9)无价 → `_next_trading_day` 返回 None → `return None` 跳过;但会污染「跳过」统计与信号入样判定。

**一句话:盘中裸跑全量 = 已入账历史交易被改价/消失/假盈亏 + 大盘择时过滤被盘中态改变。必须增量追加或盘前快照对账。**

### 1.4 单独跑耗时(问题 4)

- export.py 调用超时 **timeout=180s**(static-site/export.py L1212)——单档全量设计上限 3 分钟。
- 规模(9/7 日志):all/A 总样本 **109.7 万**,trades **72MB**(update_all_20260907_1750.log L1536/1590;注意任务背景「6MB」已过时,现 69-72MB)。
- 实测证据:9/8 09:08 deploy(全量,含主档+sdc 双档+分片+gzip+snapshot)成功在 09:15 产出产物;deploy 全程 22.5min,export 段约 8-10min(含几十个 JSON),backtest 单档在其内完成。
- **合理估计:单档 1-3 分钟,双档(主+sdc)2-6 分钟。建议实施前单独实测一次**(直接 `python scripts/signal_kelly_backtest.py --output /tmp/sk.json --trades-output /tmp/sk_trades.json --skip-parts`,记录 wall time,不落生产)。
- **撞车表(9:40 候选时点)**:
  | 任务 | 时点 | 与 9:40 冲突 |
  |---|---|---|
  | intraday-snapshot | 9:25/9:35/9:45/9:55/10:05...每10分 | **紧邻**:9:40 起跑 ≤3min 可在 9:45 前完;≥4min 撞 9:45 |
  | check_signals | 每10分(9:36/9:46...) | 错开 4min,轻量(~s) |
  | public-fund-estimation | 10:00 | 错开 20min |
  | fapi-daily | 18:10 | 不撞 |
  | update-all | 17:50 | 不撞 |

### 1.5 产物刷新链路(问题 5)

- 产物:signal_kelly_backtest.json(**513KB**,非 40KB)+ signal_kelly_trades.json(**72MB**,R2)+ `signal_kelly_trades_parts/` 分片 + lab slices + `.gz` + sdc 档(`signal_kelly_trades_sdc*`,#91 买入口径对比档,deploy 也跑)。
- deploy.sh 上传链(L422-426):`upload-data-large`(72MB trades)→ `upload-kelly-parts`(分片)→ `upload-all-data`(513KB backtest + 小 JSON)→ `upload-kelly-parts-sdc`;upload_r2.py 内含 `purge_cache` 调 `/api/purge-cache` 清 CF edge。
- 前端读:
  - app.js `_simTradesUrl`(L3515-3518)→ `https://ss.fx8.store/data/<name>?v=<cachebust>`,分片优先(失败回退 72MB 全量);`_simSummaryName` 读 backtest.json(L3611 `./data/...`)。
  - lab.js 凯利区读 `signal_kelly_trades*`/`signal_kelly_backtest*`(L8420-8423)。
- **盘中刷新 = 重跑 backtest → upload_r2 上传(72MB + 分片 + 513KB)→ purge CF edge**;`?v=` 版本串破缓存。
- 盘中用户影响:purge 短暂清 edge(重拉几百 ms);前端优先分片(小,几 MB),72MB 全量仅兜底;72MB 上传 R2 几十秒带宽。可控,但**需与 intraday-snapshot 的 R2 上传避让**(快照每 10 分钟也上传 R2)。

---

## 2 建议排班表(候选)

| 项 | 建议 |
|---|---|
| 新 launchd | `com.trade.kelly-intraday-rerun.plist`,`StartCalendarInterval` 交易日 **9:40** |
| 任务边界 | 只重跑 signal_kelly_backtest.py(**增量档**,见 §3),不跑 deploy/export 全量、不 git push、不重导全量 JSON |
| 锁 | 复用 `scripts/with_lock.py` 独立锁 `/tmp/trade_kelly_rerun.lock`;**deploy 锁 `/tmp/trade_deploy.lock` 在位则跳过本轮**(防与 intraday-snapshot 的 R2/export 竞争) |
| 防撞车 | 单档限时 3min(9:40-9:43 完,避开 9:45 快照);超时/锁忙 → 跳过本轮,留给 17:50 |
| 交易日闸门 | 非交易日跳过(同 intraday_snapshot.sh `is_trading_day`) |
| 观测 | 日志 data/logs/kelly_intraday_rerun_YYYYMMDD_HHMM.log;失败 SEVERE notify |

---

## 3 防污染设计(核心,可操作)

### 方案 A(推荐):增量追加「T 日信号」档,历史交易零改动

1. **新增独立增量入口**(如 `signal_kelly_backtest.py --intraday-rerun <DATE>`),逻辑:
   - 只处理 **T 日信号(9/7)**,不跑全部历史 buy_rows;
   - 对 T 日信号按既有 `_resolve_etf`/评级/象限归类,调 `_backtest_one`;
   - **关键:`sorted_dates` 与 `today` 都截断到 T 日(9/7)收盘**,不引入 9/8 占位;`next_trading_day` 用手工传入的真实 9/8 开盘价,而不是从 etf_daily 读(etf_daily 9/8 是占位);
   - 买入定价 = 信号日 accum_nav × (9/8 真实开盘 / 9/7 真实 close),即既有次日开盘口径,只是 9/8 开盘价改从盘中实时行情源取。
2. **9/8 真实开盘价来源(盘中)**:~~akshare `fund_etf_fund_daily_em`~~(设计稿原方案,落地时勘误,见下方「实现勘误」)。**落地前须实测一次确认盘中该源 9:40 已返回真实开盘价**(数据就绪闸,拿不到 → 跳过本轮)。

> **⚠ 实现勘误(2026-09-08 implementer 落地时发现)**:`fund_etf_fund_daily_em` 无「开盘价」列,不能作开盘价源;已改为 **`fund_etf_spot_em`**(东财 ETF 实时行情,37 列含「开盘价」),实测 9/8 返回真实开盘价(516660=0.937 / 510300=4.638 / 159920=1.483),数据就绪闸=该表取不到真价则本轮跳过。
3. **产物独立**:增量档写入独立文件(如 `signal_kelly_trades_intraday.json` + 前端新增当日卡片或并入现有「持仓中」展示),**不覆盖** `signal_kelly_trades.json` 的历史交易;17:50 全量回测照常,自然用真实收盘数据覆盖当日。
4. **对账机检(§5.4⑦ 同构对账)**:增量档中 9/7 之前的任何字段不得出现;发布前将增量档叠加到「盘前快照」(signal_kelly_snapshot.py 已有,9/4 断链根治配套)上,与盘前版本中 9/7 之前交易逐位比对,零漂移才发。
5. **9/8 盘中临时信号隔离**:增量档只处理固定 T 日(= 上一交易日 9/7)信号,`BUY_SIGNALS` 过滤仅针对 9/7 当日行,天然不引入 9/8 盘中信号。
6. **17:50 覆盖对齐**:17:50 全量回测用真实 9/8 收盘数据重算,增量档当日交易若与 17:50 最终版价格不同(盘中开盘价 vs 收盘覆盖),**以 17:50 版为准**(前端当日卡片在 17:50 后自动切换到全量版,增量档降级为盘中临时视图)。

### 方案 B(不推荐,记录理由):盘中全量重算 + 盘前快照对账

- 盘中跑全量,发布前与盘前快照对账:9/7 之前已入账交易逐位一致才发。
- **判死**:盘中占位导致 9/7 交易必然不同(剔除或假价),对账必 FAIL → 等于白跑;且大盘择时盘中态会让 9/7 之前的历史过滤判定也可能变,对账范围不可控。**不采用。**

### 结论

**方案 A(增量档 + 数据就绪闸 + 独立产物 + 对账机检)是唯一安全形态。** 核心原则:盘中补跑只做「加法」(新增当日交易),绝不做「覆盖」(重算历史)。

---

## 4 风险清单

| # | 风险 | 等级 | 缓解 |
|---|---|---|---|
| 1 | 占位价污染历史交易(改价/消失/假盈亏) | P0 | 增量档只算 T 日信号,不覆盖全量(§3 方案 A) |
| 2 | 9/8 盘中临时信号混入 | P0 | 增量档固定只处理 9/7 当日行 |
| 3 | index_daily 盘中态改变大盘择时过滤 | P1 | 增量档的 market_state 用 T 日收盘态(截断 9/7),或从盘前快照注入 |
| 4 | 撞 intraday-snapshot(9:45) / 9:40+4min | P1 | 限时 3min;deploy 锁在位跳过;错峰候选 9:50 |
| 5 | 72MB trades 上传带宽 + purge 影响盘中用户 | P2 | 增量档产物小(仅当日,几十 KB),不重传 72MB;前端分片优先 |
| 6 | 盘中开盘价源不可靠(fund_etf_fund_daily_em 未出真价) | P1 | 数据就绪闸:取不到真价跳过本轮等 17:50 |
| 7 | 口径差异:盘中开盘价入账 vs 17:50 收盘覆盖后价格跳变 | P2 | 前端 17:50 后以全量版为准,增量档仅盘中临时视图(需用户拍板口径语义) |
| 8 | 占位行写入脚本未定位,盘中链路可能有未知动作 | P2 | 实施前盘中复现定位写入者(§1.1) |
| 9 | 非交易日误触发 | P2 | is_trading_day 闸门 |

---

## 5 未决事项(需用户拍板)

1. **增量档的口径**:盘中入账用「9/8 真实开盘价」(与 17:50 全量同日,跳变小)还是「信号日收盘价近似」(简单但口径与既有默认不同)?→ 推荐前者(与 KELLY_BUY_NEXTDAY=1 同口径,仅价格源不同)。
2. **增量档的展示**:前端当日新增一张卡片/并入持仓中预估,还是只在盘中临时覆盖?17:50 后如何切换回全量版?
3. **是否同时做 sdc 档(当日收盘对比)**:盘中做 sdc 无意义(9/8 close 未出),建议只做主档。

---

## 6 用户拍板定案(2026-09-08 盘中,主控记录)

三项全部按推荐拍板:
1. **定价口径 = 真实开盘价**:盘中 9:40 轮用 9/8 真实开盘价(akshare `fund_etf_fund_daily_em` 东财盘中实时源,与 intraday-realtime 同源);取不到真价 → 数据就绪闸跳过本轮,留给 17:50。
2. **展示 = 独立盘中视图**:当日 9/7 交易进独立小文件(如 `signal_kelly_trades_intraday.json`),前端以独立当日视图展示(标注盘中价);17:50 后前端自动以全量版为准,盘中视图降级为历史临时视图。不合并进 72MB 主档。
3. **只做主档**,不跑 sdc 档(盘中 9/8 close 未出,sdc 无意义,省耗时)。

**实施规格由本报告 §3 方案 A + §2 排班表 + 本定案综合构成;实施前两个实测前置(§4 风险 1/6):①盘中复现定位占位行写入脚本 ②实测 akshare 源 9:40 已返真实开盘价 + 单档耗时。前置不过→按数据就绪闸不挂载。**

---

## 复现

- **生成脚本**:`scripts/signal_kelly_backtest.py`(全量回测,本报告只读其代码未运行)
- **输入依赖**:
  - `trade-data/data/etf_national_team.db`(etf_daily 价格;本报告已实读其 9/4-9/8 实况)
  - `trade-data/data/sentiment.db`(signal_daily 信号;已实读 9/1-9/8 实况)
  - `data/board_etf_map.json`、`static-site/data/signal_kelly_backtest.json`(读 generated_at 与 9/7 交易验证)
  - `data/signal_kelly_etf_freeze.json`(换标冻结,回测逻辑)
- **验证命令**(只读,无副作用):
  ```bash
  # 占位行实况(结果见 §1.1)
  sqlite3 trade-data/data/etf_national_team.db "SELECT date, COUNT(*), SUM(CASE WHEN accum_nav=1.5 THEN 1 ELSE 0 END), SUM(CASE WHEN open=1.49 THEN 1 ELSE 0 END), SUM(CASE WHEN etf_name=etf_code THEN 1 ELSE 0 END) FROM etf_daily WHERE date>='20260901' GROUP BY date ORDER BY date"
  # 9/7 信号实况(结果见 §1.2)
  sqlite3 trade-data/data/sentiment.db "SELECT signal, COUNT(*) FROM signal_daily WHERE date='20260907' GROUP BY signal"
  # 线上产物中 9/7 信号交易数为 0(§1.1 佐证:9:08 时 9/8 有效价不存在)
  python3 -c "import json,collections; d=json.load(open('static-site/data/signal_kelly_trades.json')); c=collections.Counter(t[0] for qv in d['quadrants'].values() if isinstance(qv,dict) for ts in qv.values() for t in ts); print({k:c[k] for k in ['20260903','20260904','20260907','20260908']})"
  ```
- **数据截止日期**:2026-09-08 盘中(约 10:2x 快照)。
- **关键口径一句话**:买入定价 = 信号日 accum_nav × (次日原始 open / 信号日原始 close),伪跳空 >20% 剔除;盘中占位行(accum_nav=1.5/open=1.49/close NULL)会被 `WHERE accum_nav IS NOT NULL` 选入并污染定价,故盘中不可裸跑全量回测。
