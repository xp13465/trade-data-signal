# 信号凯利回测演进快照「断更」排查报告(2026-09-17)

> 排查背景:用户报告「线上最新快照日停在 20260915,缺 20260916(今天 09-17),导致演进曲线点少、按日快照表最新停 9-15」。
> 排查日期:2026-09-17 16:00-17:20。方式:只读,不改任何生产文件/数据。

## 一、结论(先给答案)

1. **快照每日生成链没有断更**:云上 09-13 至 09-17 每天一份快照都生成并上传 R2(文件 mtime 反证链完整),index.json 的 d(快照日)最新=20260917(今天凌晨 05:15 生成、05:25 传 R2)。用户报的「最新停在 09-15」实际是 **m 列(max_signal_date)与按日表格的买入日轴点停 09-15**,不是快照日。
2. **「曲线点少」的根因 = 生产切云上时历史快照文件没带过去**:快照体系 09-04 已上线,本机一直在生成(本地 index.json 有 10 天点,首点 20260904);09-13 生产迁云后云上目录从 09-13 空起步,rebuild index 时 glob 不到 09-04~09-12 的 9 个历史文件,index days 只剩 5 点。**历史数据没丢——R2 桶里 20260904/05/12 等文件都返回 200 且与本机文件 md5 完全一致**,只是没参与重建 index。
3. **「m 停 09-15」的根因 = KELLY_BUY_NEXTDAY=1 次日开盘定价的正常滞后,今晚 17:50 自愈**:09-16(周二)收盘产生的 29 条买信号,买入价=09-17 开盘价定价;09-17 凌晨 05:14 全量重跑时 09-17 未开盘(etf_daily 里 09-17 只有 12 行盘中占位、open 全空),29 条全部因「缺原始价,无法按次日开盘重定价」被跳过 → 主档 signal_kelly_trades.json max signal_date 停 09-15。probe 重跑复现(max=20260915、304960 笔与生产一致)。今天 17:50 trade-update-all 采集 09-17 真实行情(open 非空)后重跑,09-16 信号即入账,m→09-16,无需改代码。

## 二、线上实测(证据)

- R2(signals 数据走 R2,ssd.fx8.store 前缀)index.json 实测(curl 带浏览器 UA,主站 307 直接走 R2):
  - `updated_at = 2026-09-17 05:15`;last-modified `Wed, 16 Sep 2026 21:25:23 GMT`(GMT=北京时间 09-17 05:25,R2 上传时刻);http=200。
  - `days=[20260913, 20260914, 20260915, 20260916, 20260917]`,共 **5 点**,各点 m=[20260909, 20260911, 20260914, 20260915, 20260915]。**d 最大=09-17;m 最大=09-15**。
- 云上生产目录 `/home/ubuntu/code/trade-data/static-site/data/signal_kelly_snapshots/`(ls -la 反证):
  - `20260913.json 09-13 21:11`、`20260914.json 09-14 23:32`、`20260915.json 09-15 21:42`、`20260916.json 09-16 22:59:45`、`20260917.json 09-17 05:15:16`、`index.json 09-17 05:15:16` → 每天一份,链没断。
- 本机开发树 `/Users/linhuichen/code/trade/static-site/data/signal_kelly_snapshots/`:
  - 有 `20260904..20260912.json` 共 9 个历史文件(09-04 23:30 起,最晚 09-12 21:16),+`20260913.json`(本机版 05:10)。本地 `index.json updated_at=2026-09-13 05:10`,days=**10 点**,首点 20260904。
  - curl R2 抽查:20260904/20260905/20260912 均 http 200;`md5(R2 20260904.json)==md5(本地 20260904.json)==6bfaaf06132841552f671a199ad381b2` → **历史文件在 R2 没丢,件件与本地同源**。
- git 层面:snapshots 目录 0 个文件被 git track(数据产物,不走 git),所以切云无法靠 pull 带过去。

## 三、根因链(证据对齐)

### 根因 A:快照目录历史文件未随生产迁移(曲线点少)

- 时间线:本机最后一夜 09-13 05:10 生成(本地 index days=10,首点 09-04);此后生产全量在云(云上首份 09-13 21:11)。快照产物是「生成→目录 glob 重建 index→上传 R2」的本地目录驱动链(`signal_kelly_snapshot.py rebuild_index()` 从 `sd.glob("20*.json")` 排序重建),云上目录从 09-13 空起步 → index 从 09-13 计起,前端曲线只画 5 点。
- 与「按日快照表」的区分:表格视图(lab.js `_labKellyEvoTableBuild`)轴点=主档 trades 的 buy_date 并集(全历史 30 万+笔都在),表格不丢历史,只受 m 影响停 09-15;曲线/迷你图吃 index days,只受根因 A 影响。

### 根因 B:m 停 09-15 = 次日开盘定价 + 凌晨跑在开盘前(设计语义正常滞后)

- `signal_kelly_backtest.py` `_backtest_one()`(L680-693):KELLY_BUY_NEXTDAY=1,买入价=信号日 accum_nav × (次日 open/信号日 close);`nxt_open` 缺失 → return None(该信号不产生任何交易)→ `_classify_buy_rows` 计入 skipped_no_price(L1295-1308,打印「无ETF价格/未来不足」)。
- 全量档 open_map 数据源=`etf_daily` 表 open 列(`_batch_load_etf_prices` L507-551,WHERE accum_nav IS NOT NULL AND etf_name<>etf_code 排除占位行)。实测(sentiment 侧 etf_national_team.db,16:45):
  - 09-16 行:rows=1588,open_ok=1588 → 09-15 信号在 09-16 晚 22:59 全量时用 09-16 开盘价入账 ✓(所以 09-16 快照 m=09-15)。
  - 09-17 行:rows=12(盘中占位半成品),open_ok=0,nav_ok=0;样例 510300 有 09-17 占位行 open=NULL/close=4.55 假价(被 accum_nav 条件排除)→ 05:14 全量重跑时 09-16 信号 nxt_open 缺失 → 29 条全部跳过。
- 复盘各日 m 与日历完全自洽(次日开盘=下一个交易日 T+1 开盘价可得日):09-13(周日)m=09-09;09-14(周一)23:32 m=09-11(周五信号等周一开盘价);09-15 m=09-14;09-16 m=09-15;09-17 凌晨 m 未动(昨晚信号+今天信号都还没到它们的开盘日)。
- probe 复现(云上 16:15-16:30 后台重跑,--output/--trades-output 全走 /tmp,不改生产):`max_signal_date=20260915`,`generated_at=2026-09-17 16:30`,交易 304960 笔与生产主档完全一致;日志打印「42017 条买信号 / 分类完成 7624 信号有有效回测 / 无ETF价格/未来不足=20484」。
- 预期自愈:17:50 trade-update-all.timer(今日 17:50 排班,采集后 export 7.9.3 内跑 backtest+snapshot)。09-17 真实行入库后 09-16 信号入账,m→09-16,index 09-17 点 m 同步更新,今晚 R2 上传。

### 附带发现(不需修,备查)

- 今天 09:40 kelly 盘中增量补跑(kelly_intraday_rerun.sh)T=20260916 **FAIL 未发布**:①数据就绪闸「1 只 ETF 取不到真实开盘价 ['160717']」(akshare fund_etf_spot_em 今日缺该 ETF 行;09-16 早上同链 PASS)②对账机检 FAIL(含 20260915 行+主档 pre-T 哈希漂移)。SEVERE 邮件/飞书告警已发(09-17 09:40,laterd.md 已镜像)。该链只发布独立盘中视图(signal_kelly_trades_intraday.json),不影响主档与演进。若明日仍 FAIL 再排 implementer 修。

## 四、修复建议(待主控拍板派单)

1. **恢复演进曲线历史点(建议做,一步到位)**:历史 9 个快照文件无需重新生成——本机 `/Users/linhuichen/code/trade/static-site/data/signal_kelly_snapshots/20260904..20260912.json` 与 R2 桶内已有文件 md5 一致。派 implementer:把本机 9 个文件(或从 R2 拖回)放入云上 `trade-data/static-site/data/signal_kelly_snapshots/` → 云上跑 `python scripts/signal_kelly_snapshot.py --rebuild`(重建 index 得 14 点)→ `upload_r2.py upload-kelly-snapshots`。注意同日双版:20260913.json 以云上 21:11 版为准(较本机 05:10 版新),不覆盖。
2. **m/表格停 09-15:不用修**。今晚 17:50 自愈,可 18:15 后抽查 `data/logs/update_all_*.log` 内 snapshot 段 + 线上 index m 变 09-16。
3. 可选记录:用户预期「快照日=最新信号日」与现有「m 滞后 1 个交易日」语义有天然错位(次日开盘定价所以 m 永远比最新收盘信号晚 1 天进场)。前端可考虑在演进视图标注 m(数据截止信号日)+d(快照生成日)两者语义,避免再被读成断更。属文案/交互建议,需用户拍板。

## 五、已验证方法与数据源清单

- 线上:R2 `https://ssd.fx8.store/data/signal_kelly_snapshots/index.json`(curl 带浏览器 UA,读 header/内容实测)、R2 历史单文件 HEAD(20260904/05/12 均 200)+md5 比对。
- 云上(ssh -i ~/tdsignal.pem ubuntu@122.51.111.173):静态目录 ls 时间线;etf_daily 表 09-15/16/17 按日 open/nav 覆盖率 SQL;今日/昨日 kelly_intraday_rerun 日志;alerts/latest.md;systemctl list-timers。
- 本机:snapshots 目录全量 ls + index.json 内容;git ls-files(0 tracked)。
- 代码(只读):`scripts/signal_kelly_snapshot.py`(rebuild_index/append_to_index 日期替换排序)、`scripts/signal_kelly_backtest.py`(_backtest_one L649-800 定价大门等价线、_batch_load_etf_prices L507-551、_classify_buy_rows L1225-1320)、`static-site/lab.js`(演进入口 fetchJSON index.json)。
- 复现:云上后台 probe 重跑 backtest(全输出 /tmp,不改生产),max_signal_date==20260915 复现成功(304960 笔一致)。

## 六、修复执行记录(2026-09-17 16:47 实施完成,根因 A 补齐)

> 执行建议四.1「恢复演进曲线历史点」,只动数据产物 + R2,未碰前端代码,未 git add 任何文件(snapshots 目录 0 tracked,数据走 R2 链路)。

1. **补齐 9 个历史快照文件**:scp 本机 `static-site/data/signal_kelly_snapshots/202609{04..12}.json` → 云上 `/home/ubuntu/code/trade-data/static-site/data/signal_kelly_snapshots/`。9 文件 md5 云上与本机逐位一致(20260904=6bfaaf06…、20260912=e06f216a…等,全 9 个 PASS)。同日双版 20260913.json 保持云上 21:11 版未覆盖(mtime Sep 13 21:11 原样)。
2. **重建 index**:云上 `REPO=/home/ubuntu/code/trade-data .venv/bin/python scripts/signal_kelly_snapshot.py --rebuild --data-dir /home/ubuntu/code/trade-data/static-site/data` → `rebuild: 14 快照日 → 14 index 行,防污染拦截 3 个 mode`(20260908 G/H/I accum_nav 污染置 null,复用 09-10 P0 既有防护逻辑)。
3. **上传 R2**:云上 `REPO=/home/ubuntu/code/trade-data .venv/bin/python scripts/upload_r2.py upload-kelly-snapshots` → 增量传 10/16(9 历史 + index.json),其余 6 个 09-13~09-17+latest_posrating 内容未变跳过;Cache purge 10/10 keys 成功。
4. **线上实测**:`https://ssd.fx8.store/data/signal_kelly_snapshots/index.json` http=200 size=5756,updated_at=2026-09-17 16:47,`days` 共 14 点 = [20260904 … 20260917] 完整;抽查线上 20260904.json md5=6bfaaf06… 与本机一致。
