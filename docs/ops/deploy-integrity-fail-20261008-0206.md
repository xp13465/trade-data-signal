# deploy 数据产物校验失败 — 事故定性报告(2026-10-08 02:06)

- 事故:云上 deploy.sh `check_data_integrity` FAIL(rc=1),已终止部署(4 类事故拦截)
- 日志:`/home/ubuntu/code/trade-data/data/logs/deploy_20261008_0206.log`(602 行,已全文读)
- 触发者:`trade-backfill-evening.timer` 02:00 档
- 定性:**长假后「自然日阈值」假阳性误拦;数据无损、线上未污染;P2,不影响今日开盘**
- 二次触发:10-08 05:00 档(`us-stock-morning` 链)再次同样 6 项 FAIL,被告警去重窗口抑制(未发第二条)

## 0. 一句话定性

2026 国庆假期(10-01~10-07 全部非交易日)后首个交易日 10-08 的**凌晨** deploy,6 项「日期滞后」校验用「自然日差 > 7 天」阈值判定;长假 7 天 + 凌晨(当日行情尚未产生)使自然日差=8 天,而**交易日差=0**(09-30 是最后交易日)→ 6 项全部误判 FAIL。deploy 在**任何写线上步骤(R2/rsync/git)之前**被拦截终止。**数据没有坏;线上用户看到的是上一版(09-30,假期前最后交易日)完好数据。** 属「阈值未适配 ≥7 天长假」的假阳性;「滞后>7天」类在近 4 周日志范围内**首犯**。

## 1. 拦的是哪一类(4 类事故拦截中具体哪条)

**本次拦截点 = 6 项「日期滞后(STALE)」类 FAIL**,全部断言「滞后 8 天 > 7 天」(deploy_20261008_0206.log 行号):

| 校验项 | 日志行 | 断言原文 | 实际值 |
|---|---|---|---|
| alert | L557 | `✗ alert: alert.json date=20260930 滞后 8 天 > 7 天` | date=20260930(查 R2 线上版) |
| notifications | L558 | `✗ notifications: notifications.json date=20260930 滞后 8 天 > 7 天` | date=20260930(查 R2 线上版) |
| ad_line | L561 | `✗ ad_line: ad_line.json 最后日期=20260930 滞后 8 天 > 7 天` | 最后=20260930(本地 static-site/data) |
| a_stock | L562 | `✗ a_stock: a_amount 最后日期=20260930 滞后 8 天 > 7 天` | 读 a-stock-1y.json 的 metrics.a_amount |
| accum_nav_map_fresh | L568 | `✗ accum_nav_map_fresh: accum_nav_map.json 最新 nav 日期=20260930 滞后 8 天 > 7 天(净资产曲线/强平日真价停更)` | 最新 nav=20260930 |
| s06_state | L580 | `✗ s06_state: 线上 S06 快照 coverage_end=20260930 滞后 8 天 > 7 天` | coverage_end=20260930(降级分支查 R2) |

- 汇总:`=== 汇总: 34 ok / 2 warn / 6 fail ===`(L595)→ `✗ 数据产物校验失败(退出码 1)，终止部署（4 类事故拦截）`(L596)。
- 阈值定义:`scripts/check_data_integrity.py` **L57-58** `STALE_DAYS_WARN = 3` / `STALE_DAYS_FAIL = 7`。
- 口径:`_days_ago()` **L156-162** = `(datetime.now() - d).days` = **自然日差,无交易日感知**。
- 各项 fail 判定代码:check_alert L432 / check_notifications L460 / check_ad_line L545 / check_a_stock L574-575(读 `a-stock-1y.json` metrics.a_amount,L552-577)/ check_accum_nav_map_fresh L999-1000 / check_s06_state_snapshot L2213-2214(降级分支②)。
- 旁证同一脚本里「交易日感知」的 2 项全 PASS:`✓ signal_accum_nav_lag: 信号日 20261001 vs accum_nav 日 20260930 滞后 0 交易日`(L566)、`✓ fapi_mutex: 共同日 20260930 重叠 5212 只 close 全部一致`(L567)——同一批数据在交易日口径下「滞后 0 交易日」。

## 2. 谁在 02:06 跑的(触发链,已逐级核实)

- 单元:`/etc/systemd/system/trade-backfill-evening.timer`,OnCalendar `*-*-* 16:35:00 / 21:00:00 / 02:00:00`,Persistent=true → `trade-backfill-evening.service`(ExecStart=`/home/ubuntu/code/trade-data/scripts/backfill_metrics.sh`,env REPO/GIT_REPO/MAIN_REPO 已注入)。
- journal 证据:`Oct 08 02:00:01 Starting Trade backfill-evening` … `02:16:47 Finished`(Consumed 11min12s)。launchd 日志 `backfill_evening_launchd.log` L38238:`=== deploy.sh 段1(锁外 export+R2+rsync)开始 2026-10-08 02:06:14 ===`。
- 脚本链:backfill_metrics.sh L29 跑 `index_backfill.main()`;deploy 由其内部触发(backfill_metrics.sh L85 注释「deploy.sh 在 backfill 内部(index_backfill.main L884)被触发(有新数据时)」;`app/collector/index_backfill.py` L1125-1138 subprocess 调 `bash scripts/deploy.sh backfill`)。
- 05:00 档(第二次):`trade-backfill-evening` 不含 05:00;05:00:01 启动的是 `trade-us-stock-morning.service`(ExecStart=`us_stock_morning.sh`),其 L9/L68-69「采集成功后跑 deploy.sh」→ `deploy_20261008_0500.log` 05:00:17 起跑,同 6 项 FAIL,`[notify][dedup] suppress ... age=10253s < window=21600s, 不重发`。
- 两树关系(云上实测 `ls -ld`,**非**整树 symlink):`/home/ubuntu/code/trade-data`(生产树,REPO)与 `/home/ubuntu/code/trade-data-signal`(git 仓,GIT_REPO)是**两个独立真实目录**;其中 `trade-data/scripts -> trade-data-signal/scripts`、`trade-data/docs -> trade-data-signal/docs` 为 symlink(代码单源),`trade-data/data`、`trade-data/static-site`、`trade-data-signal/data` 均为真实目录。deploy 由 trade-data 侧跑、rsync 到 signal 侧。

## 3. 数据到底坏没坏(严重度核心)

**结论:没坏。是校验的假阳性(阈值未适配 ≥7 天长假),不是上游采集失败/口径错/文件残缺。**

- **交易日历铁证**:云上 `data/trade_dates.txt`(源=akshare `tool_trade_date_hist_sina`)中 10 月上旬交易日=**20261008、20261009、20261012…**;10-01~10-07 **全部不在表**。即 09-30 收盘后到 10-08 凌晨之间**交易日差=0**,这 6 项「停更」是假期正常状态。
- **重复度特征**:6 项全部=同一天 20260930、同一滞后 8 天(系统一致停更,而非个别产物损坏)。
- **内容抽验(结构完好)**:
  - 线上 `alert.json`:`date=20260930, generated_at=2026-09-30 18:37:24`,high/dims 结构完整(curl ss.fx8.store 实测)。
  - 线上 `ad_line.json`:最后一条 `{"date":"20260930","up_count":2337,"down_count":2719,"ratio":0.4622,"ad_line":-141161,...}` 字段齐全(curl 实测)。
- **「T 日数据尚未生成」误报核查(用户特别关注项)= 是**:校验对「T 日(10-08)数据尚未生成」的凌晨正常状态误报。设计意图本就想兼容节假日(L986 注释「自然日 + 周末/节假日自然滞后不误报」),但 7 天上限覆盖不了 ≥7 天长假(国庆/春节后首日凌晨必然 8 天+)。**按机制推断:每逢 7 天长假后首日的凌晨档 deploy 都会重演(春节同)。**
- 另 10-07 对比证据:10-07 21:05 档同 6 项是 `⚠ 滞后 7 天`(warn,不拦),`=== 汇总: 34 ok / 8 warn / 0 fail ===`;10-07 时 s06 走本地分支 PASS(「R2 副本 coverage_end=20260930 与本地一致」)。跨入第 8 天(10-08)才 fail——完全是阈值边界,与数据无关。

## 4. 爆炸半径(拦在写之前 / 写之后?)

**结论:拦在写之前。线上未污染,用户看到的是上一版完好数据(09-30)。**

- `check_data_integrity` 位于 deploy.sh **L323-324**(段1,export 之后);FAIL → L326-331 notify + `exit`,**之后所有写线上/写仓步骤全部未执行**:
  - L523 rsync static-site/data → GIT_REPO(1.6)
  - L543 rsync data/(1.7)
  - L582 触发 R2 上传(1.8,r2_upload_async.sh,唯一 R2 数据通道)
  - L656 exec 段2(git add/commit/push)
- 日志证据:02:06 日志 602 行止于 notify+dedup(L597-602),**无任何 rsync/R2/git 行**;05:00 日志 grep rsync 仅 header 1 处(无「rsync 完成」)。对比 10-07 成功日志 84KB 含完整 rsync 段;本次 73KB/39KB 均在 check 处截断。
- 线上现状:线上版本 = 10-07 21:05 最近一次成功 deploy 所推(即 09-30 数据版本,假期后正确状态);curl 实测 alert/ad_line 均为 09-30 且结构完整(见 §3)。**不存在「半成品上线」**(数据发布=R2 批量上传,该段未跑)。
- 说明:02:06/05:00 未成功的 deploy 只在**云上本地 staging**(trade-data/static-site/data)重生成过产物(内容与线上同为 09-30 数据,因无新数据),不影响后续增量与线上。

## 5. 首犯还是复发

- **「日期滞后 > 7 天」类 = 首犯**:`grep -lE '> 7 天' deploy_*.log` 在全部历史日志(覆盖约 4 周,9-16 起)中**仅 10-08 的 2 个日志**。
- 「deploy 数据产物校验失败」这个闸门整体 = 复发(近 4 周 44 个日志含该失败),但**均为其它类别**:抽样 9-28/9-29/10-02 = `fund_nav: DB↔产物不一致`类;9-24 = `build_board_etf_map`类。这些类别现已自愈/修复(本次日志中 fund_nav ✓ PASS)。
- **告警实发 = 首次**:`grep -l '邮件已发送.*数据产物校验失败' deploy_*.log` 仅 `deploy_20261008_0206.log` 一个——历史失败发生在 2026-10-03 `export-guard L4`(deploy.sh L328 注释:升级 --severe 告警,「事故 5 次 deploy 失败无人知」)之前,未外发;10-08 02:16 是该告警升级后**第一次**真实外发(邮件+飞书,launchd 日志 L38380-38385 证实)。
- 去重机制:dedup key=`deploy_check_data_integrity_fail`、window=21600s(6h)。02:16 首告警;05:00 被 suppress;**今天 16:35 之后若再失败会再外发一条**(08:16 后窗口已过)。

## 6. 归因到近期改动(昨晚两个 commit)

**判定:两个 commit 均与本事故无关(逐条举证,非「大概无关」)。**

- `793015bee`(#213 CI 批,10-07 22:23):改动 19 文件 = `.github/workflows/ci.yml` + `docs/ops/213-batch12-impl` + `scripts/tests/*` + `scripts/test_188_s06_sync_blindspot.py`/`test_feishu_post.py`(测试/CI/文档)。不含 check_data_integrity.py / deploy.sh / 任何生产数据生成链;且上述二脚本最近一次改动为 `ba68ccca4`(10-06 02:46),昨晚未触碰(证据:`git log -4 -- scripts/check_data_integrity.py scripts/deploy.sh`)。
- `e4fecce2c`(restore 脚本修复,10-08 **07:21:55** 提交):只改 `restore-r2-backup.sh`(人工恢复通道,不被 deploy 链调用)+ 文档。**提交时间晚于事故(02:06/05:00)5 小时**,时间因果不成立。
- 正面归因:事故可由「10-01~10-07 无交易日 + 自然日阈值 7 天 + 凌晨档」三个事实完全解释,无需引入任何代码变更。

## 7. 恢复路径(命令均为建议文本,本次未执行任何一条)

**判定:不需要现在(盘前)人工恢复。** 理由:拦在写之前、线上完好、盘前本就无 10-08 数据可推;且**现在补跑必然同样 FAIL**(数据未变,仍是 8 天滞后)。

### 选项 A(推荐):不补跑,等今天盘后正常链自动恢复
- 时点:今天 15:35/16:00/17:50 正常采集链跑完后,数据更新到 10-08 → 6 项滞后归零 → 校验自然 PASS。
- 前置检查(云上):
```
systemctl list-timers 'trade-*' --no-pager | grep -E 'update-all|backfill-evening'
```
- 判定点:17:50 `trade-update-all` 完成后看最新 deploy 日志汇总行应为 `0 fail`:
```
ls -t /home/ubuntu/code/trade-data/data/logs/deploy_*.log | head -3
grep -E '汇总|校验失败' $(ls -t /home/ubuntu/code/trade-data/data/logs/deploy_*.log | head -1)
```
- 预期内噪音:今天 16:35 档 backfill-evening 若先跑且行情尚未更新完,可能再 FAIL 一次并**再发一条同类告警**(6h 去重窗口已过)——属预期,不必处理。

### 选项 B:盘后手动补跑(仅当正常链没跑/想立即验证;避开 §14 定时点)
```
# 云上执行,先确认无定时任务/残留进程在跑
pgrep -af 'update_all|deploy.sh' || echo "无残留"
# 方式 1(首选,等价 17:50 全量链):
sudo systemctl start trade-update-all.service
# 方式 2(数据已更新后仅重跑 deploy;env 与 systemd 单元一致):
cd /home/ubuntu/code/trade-data && REPO=/home/ubuntu/code/trade-data GIT_REPO=/home/ubuntu/code/trade-data-signal MAIN_REPO=/home/ubuntu/code/trade-data bash scripts/deploy.sh
# 验收同选项 A(看最新日志 0 fail + 线上 curl 字段更新)
```
风险:与盘后定时任务撞车(§14:15:35/16:00/17:50/20:35/22:00 不推 main 不等);盘中 09:30-15:30 禁跑(时段闸门会拒)。

### 回滚(本案不需要,仅备案)
- 线上未被污染,无需回滚。备案若未来发现 R2 污染:从 staticdata 备份桶恢复(4 层灾备),入口=`scripts/restore-r2-backup.sh`(今早 `e4fecce2c` 刚修复跨桶候选探测)+ 指引 `docs/decommissioned-backups.md`。

### 根治建议(修复项,待拍板)
把 6 项日期滞后判定从「自然日差」改为「交易日差」(复用交易日历 `app.calendar`,或加「区间内全为非交易日则豁免」逻辑),保留 warn/fail 分级。改动点:check_data_integrity.py 的 alert/notifications/ad_line/a_stock/accum_nav_map_fresh/s06_state 六处 + s06 的 `local_fresh` 判定(L2144)。

## 8. 是否符合「上线必须完整版」(§23.15)

**不涉及残缺上线。** 本次是闸门**保守拦截**了「假阳性+零新数据」场景;没有「该上的没上」(09-30 数据早已在线,10-08 数据正常上线时点=今天盘后)。无需标红。反之应留意:该 6 项若在**盘后数据已更新后**仍拦,才是真问题(不会发生,滞后归零)。

## 证据索引(可复核)

- 日志:`/home/ubuntu/code/trade-data/data/logs/deploy_20261008_0206.log`(L1 起跑 / L557-580 六项 fail / L595-596 汇总终止 / L597-602 告警+dedup);`deploy_20261008_0500.log`(同 6 项 + suppress);`deploy_20261007_2105.log`(对照:0 fail/8 warn);`backfill_evening_launchd.log` L38238/L38380-38385。
- 代码:`scripts/check_data_integrity.py`(L57-58 阈值、L156-162 自然日、L410-436 alert、L439-464 notifications、L522-549 ad_line、L552-579 a_stock、L979-1003 accum_nav、L2114-2214 s06);`scripts/deploy.sh`(L151-153 时段闸门、L319-331 校验+拦截、L523/L543 rsync、L582 R2 async、L656 段2)。
- 云上:`/etc/systemd/system/trade-backfill-evening.{timer,service}`;`data/trade_dates.txt`(10-08 起为交易日);`systemctl list-timers` 快照;`journalctl -u trade-backfill-evening`(02:00:01→02:16:47)。
- 线上实测:curl `https://ss.fx8.store/data/alert.json`、`/data/ad_line.json`(均 09-30、结构完整)。
- git:`793015bee`/`e4fecce2c` diff --stat;`git log -4 -- scripts/check_data_integrity.py scripts/deploy.sh`。

## 未决项

1. 根治口径改动(自然日→交易日)是否派单落地,待用户拍板。
2. 今天 16:35/21:00 档是否复现同类告警(dedup 已过窗口)——预期内,盘后 17:50 后以最新日志 0 fail 为恢复判据。
3. 报告文件本身未提交(按任务约定由主控处置)。
