# D4 数据源与数据链路可靠性体检(2026-10-03)

> 云服务器系统性体检 D4 维度 · 只读诊断(未改任何代码/数据)
> 观察窗口:2026-09-20 ~ 2026-10-03(迁云后近 14 天;国庆休市,A 股 10-08 开市,港股 10-05~10-07 有市)
> 命令均以 `ssh -i ~/tdsignal.pem ubuntu@122.51.111.173` 或本地只读执行

## 0 结论速览

1. **⭐自动切换「真生效且有日志」**:近 14 天日志中两类切换实证齐全——①mootdx 主源空 → baostock fallback(9/21-9/28 每天命中,见 §2.1);②东财 ETF 行情被封 → 新浪+腾讯兜底(9/25、10/3 实锤命中,见 §2.2)。切换有告警打印,不是只写了代码。
2. **但 9/29-9/30 出现「双腿同死」窗口**:mootdx 主源空 + baostock fallback 登录失败(10002007)→ `mootdx_daily_raw` 缺 9/29、9/30 当日行(MAX 停在 9/28),`industry_width_daily` 断档 2 天(MAX 停 9/28)。**无人告警**(industry_width_daily 无 gap 检测,见 §4)。→ **P1 回填**
3. **单点无兜底清单**:baostock(全 A 日线唯一备份,被封即 mootdx_daily_raw 断)、akshare stock_daily(第三源,「skip no progress yet」伪兜底,迁云后依旧)、industry_width_daily(上游 mootdx_daily_raw 单点)、ETF close(sina+mootdx 双源,9/30 多只双空)、指数级 multisource 兜底覆盖面窄。
4. **R2 链路:增量已生效但未根除**——12 通道+large-json 增量状态文件云上每日活跃(§5.3),SKIPPED_LOCKED 从 9/24 高峰缓解,但 fetch_news 通道 10/1、10/3 仍触发 3/3 severe(§5.1);rc=28 直连不可达 9/20-9/22 高频、9/30 复发一次(§5.2)。
5. **迁云后可达性未重测**:`scripts/check_ds_resilience.py` 云上已同步,但无任何 self-test/resilience 日志(§6)。8-27 那份 38/38 PASS 是迁云前本机证据,出口(阿里云 vs 家宽)不同,结论不可沿用。
6. 反证项:核心指数链(新浪→baostock→腾讯补采)9/28-9/30 全齐(§7.1);gap-check 9 检查器 9/29-9/30 零 severe(§7.2);换源判据锚稳定标识,9/24 字段值过滤事故已修(§3.1);交易日历 9/25 判定经新浪独立 K 线验证正确(§7.3)。

## 1 数据源全景表(源/用途/调用点/兜底/是否异源)

> 调用点均本地/云上一致(main @ fc951666a)实际行号;★=单点无兜底或兜底不可用。

| 源 | 协议 | 用途 | 调用点(文件:行/函数) | 兜底 | 兜底异源? |
|---|---|---|---|---|---|
| **mootdx**(通达信 TCP) | TCP7709 | 全A日线 OHLC → mootdx_daily_raw → width_history/industry_width/bj_width | `app/collector/mootdx_daily.py` + `runner.py` width pipeline | baostock(同写 mootdx_daily_raw,带turnover) | ✅ 异源(baostock.com) |
| **baostock** | HTTPS | 全A日线(含turnover)+ 换手率分布源 | `baostock_daily.py`/`baostock_parallel.py`/`baostock_worker.py`;runner L387-402;21:00 backfill-evening | **★无**(被封即 mootdx_daily_raw 断;仅 21:00 槽写 baostock_daily_raw 表,不回填 mootdx_daily_raw) | — |
| **akshare stock_daily**(东财push2his) | HTTP | 全A日线第三源(T3,8-27 转正) | `stock_daily.py`(runner L434 调) | — | **★伪兜底**:9/21-9/30 日志每日 `[  ok] stock_daily skip (no progress yet, run stock_daily full manually)`(§2.4),从未初始化 |
| **东财 em_get**(push2his/push2) | HTTP | 主力净流入/行业资金流/涨停池/行业换手率 | `direct.py` `fetch_market_fund_flow`;`industry_extras.py`;`fetchers.py` | push2 clist 聚合(当日);multisource 指数级 | ✅ 同 host 多端点算弱异源 |
| **FAPI**(券商内部) | HTTP | 涨停/跌停/炸板/龙虎榜兜底 | `fapi_fallback.py` L107/L141 | 东财主源失败时 | ✅ 异源 |
| **腾讯 qt.gtimg.cn** | HTTP GBK | 9指数盘中实时/换手率/北证50/ETF全称/分时 | `tencent.py`;`intraday_snapshot.py` L39-62;`index_backfill.py` L52;`_etf_spot_fallback.py` | 新浪(指数逐个降级备) | ✅ 异源 |
| **新浪** | HTTP | 指数日线/宽度快照/ETF兜底/离岸/商品 | `fetchers.py` `collect_index`;`_etf_spot_fallback.py`;`intraday_snapshot.py` | 东财 push2delay(multisource) | ✅ 异源 |
| **申万 swsresearch** | HTTPS | 31申万行业指数 OHLC | `fetchers.py` `index_hist_sw` | 同花顺聚合(industry_extras) | ✅ 异源 |
| **同花顺 THS** | HTTP | 概念27/行业实时/申万OHLC兜底 | `fetchers.py`;`intraday_snapshot.py` | 东财概念(需映射,未上) | ⚠ 部分 |
| **中证 csindex** | HTTP | 中证红利/红利低波 | `fetchers.py` `stock_zh_index_hist_csindex` | 无(官方权威) | — |
| **HKEX 官方** | HTTPS JS | 北向成交总额 | `direct.py` `fetch_north_fund_total` | 东财 datacenter + kamt(2级) | ✅ 异源 |
| **HKEX CCASS** | HTTPS | 北向季度净买 | `hkex_ccass_quarterly.py` | 无(季度,低风险) | — |
| **CFFEX**(akshare) | HTTP | IF/IC/IH/IM 前20持仓 | `futures_position.py` | 双时点 20:05+21:00 重试 | 同源重试 |
| **cninfo** | HTTP/PDF | ETF持有人/IPO | `etf_national_team.py` | 无 | — |
| **legulegu** | HTTPS | 申万成分股映射 | `industry_width.py` | **★无**(31行业成分唯一源) | — |
| **ETF close**(sina主+mootdx备) | HTTP/TCP | 国家队ETF份额信号收盘价 | `etf_national_team.py` | mootdx | ⚠ **双源常同时空**(§2.3) |
| **R2/CF** | S3/边缘 | 产物发布/缓存 | `deploy.sh`/`scripts/upload_r2.py` | 三域名+双桶 | ✅ |

**空格/单点**:baostock、akshare stock_daily、industry_width_daily 上游、legulegu、ETF close(sina+mootdx 双源无第三备)、multisource 兜底仅覆盖指数级 6 组(us10y/cn10y/hk_south/a_turnover_rate/美股/全球),个股级/宽度级未覆盖。

## 2 ⭐近期降级切换实证(7~14 天日志)

### 2.1 mootdx → baostock fallback(9/21-9/28 每日命中)
命令:`grep -aE "疑似全停服|fallback" update_all_20260921_1750.log | head`
```
⚠ 连续15只失败(阈值15)，mootdx 疑似全停服，剩余5185只改用 baostock fallback
    [fallback 50/5185] 000338: +1 rows (baostock)
    [fallback 5000/5185] 688548: +1 rows (baostock)   # 9/22-9/28 尾进度到 5150+
```
逐日 fallback 进度行计数:`grep -ac "fallback .*5185"` → 9/21=2146(首日全量)、9/22-9/28 各 103(增量)。DB 实证 `SELECT date,COUNT(DISTINCT code) FROM mootdx_daily_raw WHERE date>=20260921 GROUP BY date` → `9/21-9/28 各 5185` 全齐。

**切换真生效**:mootdx 空 → fallback 大量成功,表内 9/21-9/28 全 A 5185 只齐全。**但有尾部残缺**:9/21 fallback 到 `[fallback 5000/5185] 688548: ERR RuntimeError: baostock login failed: 10002007`(688 段尾部几只失败;表内 688 段 9/21 覆盖 609 只,整体齐全)。9/22-9/28 尾部成功(`+1 rows`)。

### 2.2 东财 ETF 行情封 → 新浪+腾讯兜底(9/25、10/3 实锤)
命令:`grep -aE "etf-fallback|fund_etf_spot" deploy_20261003_1750.log`
```
-> 拉取 ETF 全量行情(东财主源 + 新浪兜底) ...
⚠ [etf-fallback] 东财主源 fund_etf_spot_em() 失败(ConnectionError: ('Connection aborted.', RemoteDisconnected(...)))，启用新浪+腾讯兜底 ...
✅ [etf-fallback] 新浪+腾讯兜底成功：2053 只(代码/名称全称/成交额口径)
```
9/25 deploy 同款命中(2045 只)。**结论:9/24 落地的新浪兜底,9/25 即首次真实命中,10/3(今日)仍在命中,board_etf_map 产物在修复后不再断档。**

### 2.3 ❌ 9/29-9/30「双腿同死」窗口(本维度最重实证)
命令:`grep -aE "mootdx|疑似全停|fallback|fail" update_all_20260929_1750.log`
```
=== 采集 20260929 完成 (steps=['mootdx', 'industry_width', 'width_history', 'bj_width']): ok=0 fail=1 ===
  [fail] mootdx_daily               baostock login failed: 10002007 网络接收错误。
```
9/30 同款。DB 实证(命令见 §8 P1-1):
```
mootdx_daily_raw -> [('20260921', 5185)...('20260928', 5185)]   # 无 9/29、9/30
baostock_daily_raw -> [('20260929', 5199), ('20260930', 5199)]   # 21:00 槽补到全量
industry_width_daily date 分布: [('20260921',31)...('20260928',31)]   # 断 9/29、9/30
```
**定性**:mootdx 主源 9/29/9/30 仍空 → fallback baostock 登录失败(10002007)→ width pipeline mootdx step 整体 fail。**baostock 21:00 槽(backfill-evening)成功补了 baostock_daily_raw 5199 只,但不写 mootdx_daily_raw** → 全A日线表与行业宽度链 9/29/9/30 断档。**换手率分布(a_turnover_*)9/29/9/30 有值**(来自 baostock_daily_raw 表,cleanup_d3d2 读它),未断。

### 2.4 akshare stock_daily 伪兜底依旧(迁云后 9/21-9/30 每日 skip)
命令:`grep -aE "stock_daily" update_all_20260929_1750.log`
```
  [  ok] stock_daily                skip (no progress yet, run `stock_daily full` manually)
```
9/21-9/30 每个交易日日志同款。8/27 报告已列「伪兜底:akshare stock_daily.py 从未 backfill,progress 空」——**迁云后该问题原样保留**,T3 转正未真正初始化。

### 2.5 ETF close 双源空(sina 主 + mootdx 备)
命令:`grep -aE "主源sina\+fallback mootdx 均返空|close 未采到" etf_national_team_launchd.log`
```
  [ohlc] WARNING 159915 主源sina+fallback mootdx 均返空，close/amount 将为 NULL
  [probe] 510050 50ETF华夏 当日(20260930) close 未就绪(sina/mootdx 未出),跳过 12 只批量采...
  159922 500ETF嘉实: 当日(20260930) close 未采到(sina/mootdx 未出,跳过)
```
按代码计数(561/562/589 QDII 段 5-10 次/只跨越多个交易日;9/30 当日 159915/159922/159845/159919/159952 深市集中双空)。**sina+mootdx 双源无第三备,深市 ETF 9/30 close 缺失。** 沪市(510300/510500)同日成功 → 问题集中在深市/QDII 段。

### 2.6 盘中分时东财腿失败(被 try-except 吞,不阻塞)
命令:`grep -ac "请求失败" intraday_snapshot_launchd.log` → 957 次;`grep -a "hkHSI" ... | grep 请求失败` → 240 次,host 全为东财(push2/push2delay/2.push2/10.push2/20.push2)。`intraday_snapshot.py` L2387 注释:「首选腾讯 day/query,失败退东财 trends2」;L2434 print 后 try-except 继续。**东财腿持续失败已多日,但被兜住不阻塞快照**(§8 P2-4 观察)。

## 3 换源判据可靠性

### 3.1 9/24「字段值过滤静默失效」事故已修,判据现锚稳定标识 ✅
memory `data-source-switch-field-filter-blindspot` 案例:东财 `fund_type=="lof"` 字段在新浪兜底源不存在 → LOF 混入 → assertion4 FAIL 阻断 deploy 5 小时。
当前代码:`scripts/build_board_etf_map.py` L693 `_is_lof_code(code)` 用**代码前缀**(501/502/16/15)判定,三源通吃;L605-624 注释明确「LOF 无 fund_type 字段,enrich 时 setdefault etf → track_index 层旧守卫对新浪 LOF 完全失效」已改。
实证:`grep -aE "assertion|BROAD_MUST_NONEMPTY|断言4" deploy_2026092*.log deploy_202610*.log` 近 14 天**无 assertion4 FAIL**(9/25 起新浪兜底命中后 board_etf_map 产物校验正常,见 §2.2)。

### 3.2 其余切换判据均为「返回空/异常 → 换源」✅
- `fetchers.py` collect_series:`if df is None or len(df)==0` → 切异源兜底(L356-369);`isinstance(df, Exception)` 同判。
- `index_backfill.py`:主源采后校验 8 核心指数今日缺失 → baostock → 腾讯(L1-10 docstring)。
- `multisource.py`:各 fetcher 返 `[(date,value)]` 或 `None(源不可用)`,主源 None 即换。
- **无「按字段值过滤」判据反例**残留(§3.1 唯一案例已修)。

## 4 数据产物缺口检测覆盖矩阵

`scripts/check_data_gap_alerts.py` 9 个检查器(L16-68 docstring):

| 产物 | 有检测? | 检查器 | 近 14 天表现 |
|---|---|---|---|
| a_fund_north(北向) | ✅ | north_hole/north_stale | 正常(未见发现) |
| ETF 累计净值 accum_nav | ✅ | etf_accum_nav_gap/accum_nav_new_gap | 9/24-9/30 每日 info/warn(QDII 时滞,非故障) |
| 宽度族 daily_metric(8+3 id) | ✅ | width_freshness(+mootdx_daily_raw 源对照) | 正常 |
| 交易记录 kelly | ✅ | kelly_coverage/kelly_stale/kelly_backtest_fail | 9/24-9/28 severe(交易记录停 9/22,9/29 恢复,见下) |
| a_fund_main/a_fund_margin | ✅ | fund_freshness | 9/30 补回 |
| fund_nav 公募净值 | ✅ | check_fund_nav_accnav/allnull | 正常 |
| **industry_width_daily(31行业宽度)** | ❌ **无** | — | **9/29/9/30 断档 2 天,零告警**(grep 证实无引用) |
| **mootdx_daily_raw 当日** | ⚠ 间接 | 仅 width_freshness 源对照(宽度族落后才查) | **9/29/9/30 当日缺 2 天,width_freshness 未报**(当日宽度族快照有值不触发源对照) |
| ETF close(etf_national_team) | ⚠ 部分 | accum_nav 窗口外 NULL 覆盖 | 9/30 双空 close 缺,**无专门检测器** |
| index_daily 核心指数 | ⚠ 兜底 | self_heal(retry_failed_metrics) | 9/15 曾 10 指数全败被捕获;9/20-10/3 正常 |
| intraday 盘中产物/news_digest | ❌ 无 | — | — |

**9/24-9/28 交易记录断档事件(gap 捕获到)**:kelly_coverage 9/24 `[severe] 交易记录最新信号日 20260922 落后(应≥20260923)`、9/28 同款(落后至应≥20260924);9/29 `[recovered] kelly_stale 发恢复通知`。**这是 gap 检测成功抓到的 4 天断档**,但根因未在本维度展开(疑信号凯利回测链数据供给,待 D5 或其他维度交叉)。

## 5 R2 上传/同步链路现状

### 5.1 SKIPPED_LOCKED:缓解但未根除(fetch_news 通道)
命令:`grep -aE "SKIPPED_LOCKED|上传锁" schedule_monitor_launchd.log`
```
[r2-skip] fetch_news R2 锁skip 连续1/3 轮(未达阈值, 不告警)
[r2-skip] fetch_news R2 锁skip 连续2/3 轮(未达阈值, 不告警)
```
告警侧(`data/alerts/latest.md`):`[SEVERE] fetch_news R2 上传锁连续 3 轮跳过(SKIPPED_LOCKED)` 出现在 **2026-10-01 18:30** 与 **2026-10-03 00:30**。`fetch_news_launchd.log` 尾部仍有 8+ 条 `[fetch_news] SKIPPED_LOCKED: R2 上传锁忙, 本轮跳过 news_digest 归档上传(缺口由下一轮 fetch_news 30min 后自动重试兜底)`。
**判定:149a lock-split 落地后 9/24 高峰缓解,但 fetch_news 通道 10/1、10/3 仍间歇触发 3/3 severe,未根除。**

### 5.2 R2 直连不可达(rc=28):9/20-9/22 高频,9/30 复发一次
命令:`grep -aE "R2 直连不可达" schedule_monitor_launchd.log | sed -E "s/^([0-9-]+).*/\1/" | sort | uniq -c`
```
1 SEVERE: R2 直连不可达 ssd.fx8.store/data/overview.json error<curl rc=28> now<2026-09-20 14:30:01>
1 ... 09-20 21:15:00 / 09-20 22:00:00 / 09-21 20:15:01 / 09-21 22:45:01 / 09-21 23:45:01 / 09-22 21:15:00
1 ... 09-30 23:00:00
```
**9/20-9/22 共 7 次、9/30 复发 1 次**;9/23-9/29 无。9/30 23:00 那次紧邻 `backfill_evening 执行耗时 7373s 超阈值 4500s`(21:00 槽长跑,见 §5.4)。

### 5.3 ✅ 增量上传已真实生效(12 通道 + large-json)
- `ls -la data/.r2_*_state.json` → 全部状态文件 **10-03 18:00-18:17 更新时间**(每次 deploy 都在刷新)。
- large-json 增量:`staticdata_backup_async_20261003_171237.log`
```
[large-json] 模式=增量 全集 31673 / 跳过 31637 / 待传 36 / 缺失 0(指纹扫描 85.4s, 纯本地)
```
**从 8-27 报告的 26-105min 跨境 HEAD 降为 85.4s 本地指纹扫描,增量机制在生产真实命中。**
- 9/29/10/1 有 `attempt 1 失败(TimeoutError: _ssl...), 1s 后重试` 零散超时,日志尾部均为 `✓ 上传完成`,**无最终失败**(重试成功)。

## 6 迁云后可达性是否重测

**没有重测。** 证据:
- 云上 `scripts/check_ds_resilience.py` 存在(与主仓同步),但 `ls logs/ | grep -iE "resilience|selftest|self_test"` → **无任何结果**;`data/` 下无 check_ds_resilience 输出。
- 唯一迁云前证据 = `docs/ops/ds-resilience-selftest-evidence-20260827.md`(38/38 PASS,分支 feat/datasource-resilience,本机家宽出口)。
- 迁云后无任何「出口 IP 更换后异源可达性」的重新测量(阿里云出口 vs 家宽;东财封禁、mootdx 停服等行为在云上表现不同——本报告 §2 实证已显示东财在云上持续 ConnectionError)。
- **缺口定性:8/27 结论不可沿用,异源兜底矩阵的「实测可达」标注全部需要迁云后重测**(尤其东财系 push2/push2his/trends2、新浪、腾讯)。

## 7 反证项(确认没问题的)

1. **核心指数链 9/28-9/30 全齐**:`index_daily(date≥20260921)` → 9/21-9/24 各 157、9/28-9/30 各 158 条。新浪主源 + baostock + 腾讯补采链正常,首页指数卡无缺口。
2. **gap-check 9/29-9/30 零 severe**:`check_data_gap_launchd.log` 9/29 3 条(severe=0)、9/30 3 条(severe=0),9/29 还有 `[recovered] kelly_backtest_fail/kelly_stale 发恢复通知`(断档恢复)。
3. **9/25 交易日判定正确**(初看像事故,独立源验证后排除):本地 `trade_dates.txt` 与新浪独立 K 线**均无 20260925**(新浪 K 线 9/24 直接跳 9/28),双源互证 9/25 为休市调休日,`is_trading_day('2026-09-25')=False` 正确。
4. **换手率分布链 9/29/9/30 未断**:`a_turnover_mean` 9/29=2.482、9/30=2.505 有值(baostock_daily_raw 表 21:00 槽补采后由 cleanup_d3d2 聚合)。
5. **全市场宽度(a_width_up/down/zt/amount)9/29/9/30 正常**:3471/1932、57、14213 等有值(akshare 新浪快照链,不依赖 mootdx_daily_raw)。
6. **news 采集/新闻看板正常**:`fetch_news_launchd.log` 持续运行,唯一问题是 R2 上传锁(§5.1)。

## 8 分级问题表

### P0(立即)——本次无确认 P0
未发现「线上主展示位当前断粮」级别的活性事故(国庆休市,9/29/9/30 缺口已沉淀)。**10-08 开市前必须清掉 P1-1,否则开市日宽度链延续断档。**

### P1(本周/10-08 开市前)
| # | 现象 | 证据命令 | 原始输出片段 | 影响 | 建议 |
|---|---|---|---|---|---|
| P1-1 | **mootdx_daily_raw + industry_width_daily 9/29/9/30 断档 2 天,需回填** | `sqlite3 stock_daily.db "SELECT date,COUNT(DISTINCT code) FROM mootdx_daily_raw WHERE date>=20260921 GROUP BY date"`;同法查 sentiment.db industry_width_daily | `mootdx_daily_raw -> ...('20260928', 5185)`(无 9/29/9/30);`industry_width_daily date 分布 -> ...('20260928',31)` | 全A日线/行业宽度历史序列缺 2 天;width_history run_recent(30天窗)10-08 开市后无法自愈(源表无当日行) | baostock_daily_raw 9/29/9/30 有 5199 只,10-08 前重跑 fallback 回填 mootdx_daily_raw 两日 + 补算 industry_width_daily |
| P1-2 | **baostock 间歇封禁/网络错误,fallback 每日 17:50 时不可用**(9/21 尾部 688 段、9/29/9/30 login 失败;21:00 槽却成功) | `grep -a "baostock login failed" update_all_20260929_1750.log update_all_20260921_1750.log` | `[fail] mootdx_daily  baostock login failed: 10002007 网络接收错误。`;`[fallback 5180/5185] 688816: ERR ... 10002007` | mootdx_daily_raw 依赖 baostock 补最后几段;封禁窗口整条宽度链断 | 8/27 T1 方案「封禁期间自动改走替代源(akshare/腾讯)」落地;baostock 恢复后单连接串行+限速;封禁期 17:50 槽直接跳过不空转 |
| P1-3 | **akshare stock_daily 第三源伪兜底(8/27 已报,迁云后依旧)** | `grep -a "stock_daily" update_all_20260929_1750.log` | `[  ok] stock_daily  skip (no progress yet, run stock_daily full manually)` | 全A日线真第三备不存在,双腿(bootdx+baostock)同死即断 | 手工 `stock_daily full` backfill 一次初始化 progress;此后 runner 自动增量(8/27 T3) |
| P1-4 | **R2 fetch_news SKIPPED_LOCKED 未根除**(10/1、10/3 3/3 severe) | `grep -a "SKIPPED_LOCKED" fetch_news_launchd.log \| tail` | `[fetch_news] SKIPPED_LOCKED: R2 上传锁忙, 本轮跳过 news_digest 归档上传` | news_digest 收盘/每日版可能滞留未上 R2,前端读旧 | 查 149a lock-split 后 fetch_news 与谁争锁(疑似 long 任务超时持锁);锁按任务拆分或加超时强制释放 |
| P1-5 | **ETF close 双源空无第三备**(深市/QDII 段 9/30 集中,561/562/589 段常发) | `grep -aE "主源sina\+fallback mootdx 均返空\|close 未采到" etf_national_team_launchd.log` | `159915 主源sina+fallback mootdx 均返空`;`510050 ... 跳过 12 只批量采省~170s,末日仍为昨日` | ETF 当日 close 缺失 → 份额/信号/前端卡 读昨日 | 给 ETF close 加腾讯 qt.gtimg 第三备(sina+mootdx+tencent 三源);缺失名单进 gap 检测 |

### P2(观察/本周内)
| # | 现象 | 证据 | 影响 | 建议 |
|---|---|---|---|---|
| P2-1 | **industry_width_daily / mootdx_daily_raw 当日无 gap 检测**(9/29/9/30 断档无人告警) | `grep -n "industry_width" check_data_gap_alerts.py` → 无引用;日志 9/29/9/30 gap 检测无相关 warn | 行业宽度断档静默 | gap-check 新增「mootdx_daily_raw MAX(date) ≥ 最近交易日」检查(已有 width_freshness 源对照可扩展为独立项) |
| P2-2 | **迁云后异源可达性未重测** | `ls logs/ \| grep -iE "resilience\|selftest"` 空;selftest 证据停留在 8/27 本机 | 异源兜底矩阵「实测可达」标注过时,云上东财系已见持续 ConnectionError | 迁云后跑 `check_ds_resilience.py` + 逐源 curl 探测,更新 docs/data-sources.md §15 标注 |
| P2-3 | **R2 rc=28 直连不可达 9/30 仍复发一次**(9/20-9/22 高频后缓解) | `grep -a "R2 直连不可达" schedule_monitor_launchd.log` | `now<2026-09-30 23:00:00> ... curl rc=28` | R2 上传/读取中断风险 | 若复现,查云上到 R2 网络 + 锁滞留;与 P1-4 同根排查 |
| P2-4 | **盘中东财分时腿失败多日**(957 次,港股 240 次) | `grep -ac "分时序列请求失败" intraday_snapshot_launchd.log` | `[intraday] hkHSI 分时序列请求失败(push2delay.eastmoney.com): ConnectionError` | 盘后快照分时注入/预估成交额缺东财腿(已 try-except 不阻塞) | 确认腾讯 day/query 腿命中率;东财腿失败数统计纳入监控 |
| P2-5 | **9/30 backfill_evening 超时 7373s**(21:00 槽 baostock_parallel 长跑) | `grep -a "backfill_evening 执行耗时" schedule_monitor_launchd.log` | `[SEVERE] backfill_evening 执行耗时 7373s 超阈值 4500s` | 回填槽与后续任务挤占 | baostock 补采与 21:00 其他任务错峰或限时 |
| P2-6 | **9/24-9/28 交易记录断档 4 天**(gap 已捕获,根因未定位) | `check_data_gap_launchd.log` 9/24/9/28 | `[severe] 交易记录最新信号日 20260922 落后(应≥20260924)` | 信号凯利产物 4 天未更新 | 转 D5/信号链维度交叉核查根因(mootdx_daily_raw 缺 9/25 前后?信号源缺?) |

## 复现段

```bash
# 0) SSH 前缀
S="ssh -i ~/tdsignal.pem -o BatchMode=yes ubuntu@122.51.111.173"

# 1) mootdx_daily_raw / baostock_daily_raw / industry_width_daily 9 月下旬分布
$S 'cd /home/ubuntu/code/trade-data/data && python3 -c "
import sqlite3
db=sqlite3.connect(\"file:stock_daily.db?mode=ro\",uri=True)
for t in [\"mootdx_daily_raw\",\"baostock_daily_raw\"]:
    print(t, db.execute(\"SELECT date,COUNT(DISTINCT code) FROM %s WHERE date>=20260921 GROUP BY date\"%t).fetchall())
s=sqlite3.connect(\"file:sentiment.db?mode=ro\",uri=True)
print(\"industry_width_daily\", s.execute(\"SELECT date,COUNT(*) FROM industry_width_daily WHERE date>=20260921 GROUP BY date\").fetchall())
"'

# 2) 降级切换实证(9/29/9/30 双腿同死 / 9/21 fallback 尾部)
$S 'cd /home/ubuntu/code/trade-data/data/logs && grep -aE "fail|fallback|疑似全停" update_all_20260929_1750.log update_all_20260921_1750.log | grep -avE "Please wait" | head -20'

# 3) 新浪兜底命中(9/25、10/3)
$S 'cd /home/ubuntu/code/trade-data/data/logs && grep -aE "etf-fallback|新浪" deploy_20261003_1750.log | head -6'

# 4) stock_daily 伪兜底
$S 'cd /home/ubuntu/code/trade-data/data/logs && grep -a "stock_daily" update_all_20260930_1750.log | head -3'

# 5) R2 增量生效 + SKIPPED_LOCKED 残留
$S 'ls -la /home/ubuntu/code/trade-data/data/.r2_large_json_state.json; grep -a "模式=增量" /home/ubuntu/code/trade-data/data/logs/staticdata_backup_async_20261003_171237.log | head -2; grep -a "SKIPPED_LOCKED" /home/ubuntu/code/trade-data/data/logs/fetch_news_launchd.log | tail -3'

# 6) 可达性重测缺口
$S 'ls /home/ubuntu/code/trade-data/data/logs/ | grep -iE "resilience|selftest"; ls /home/ubuntu/code/trade-data-signal/scripts/check_ds_resilience.py'

# 7) 9/25 交易日历双源互证
python3 -c "import sys; sys.path.insert(0,\"/Users/linhuichen/code/trade\"); from app.calendar import is_trading_day; print(\"9/25=\", is_trading_day(\"2026-09-25\"))"
curl -s 'https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData?symbol=sh000001&scale=240&len=12' -H 'Referer: https://finance.sina.com.cn' | python3 -m json.tool | grep -oE "\"day\": \"2026-09[0-9]+\"" | tail -8
# → 新浪 K 线 9/24 直接跳 9/28(无 9/25),与 trade_dates.txt 一致

# 8) gap 覆盖矩阵(grep 证实 industry_width 无检测)
grep -n "industry_width" /Users/linhuichen/code/trade/scripts/check_data_gap_alerts.py || echo "industry_width 无引用"
```
