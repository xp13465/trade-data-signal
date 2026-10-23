# 稳定性 + 性能全项目评估(2026-10-23)

> **日期**:2026-10-23
> **评估范围**:近 30 天(2026-09-23 ~ 2026-10-23)
> **方法**:syslog 重建(5 周轮转)+ 台账聚合(alert_ledger / suppression_ledger / alert_domains)+ 云上实测(curl 单点、日志计时、文件清单)
> **数据源**:云上权威两棵树(`trade-data` 生产树 + `trade-data-signal-staticdata` 镜像树),**本机 mac 库未使用**(本机镜像会陈旧,不作为生产事实依据)
> **窗口**:主体近 30 天;告警同口径对比用 10-10~10-16 vs 10-17~10-23 两个 7 天窗;deploy 统计用 31 天 480 个日志
> **性质**:只读调研,零代码改动。数字原样保留,不作四舍五入。

---

## A. 告警降噪:做到了什么程度

1. **量级确实降了,但主要是 critical 降**:台账 10-10~10-23 共约 669 条。同口径 7 天对比:10-17~10-23 日均 46.4 条 vs 10-10~10-16 49.0 条(-5.2%);alert 组 23.0 vs 25.0(-8.0%);**critical 8.1 vs 17.0 条/天(-52.1%)**。注意 10-17 后还夹着 10-20/21 的 deploy 事故,说明降噪不是靠"没出事"撑出来的。
2. **构成**:alert 组 336(50.2%)/report 313(46.8%)/其它约 19;tier 为 notice 432、critical 176、warning 39、digest 15。按 RCA 口径,机制噪声 63 条(9.4%),重复冗余 111 条(16.6%,556 个唯一主题);单 key 单日最高 **8 次**(如 `cov_premium_median` 10-20/21、`a_fund_north_quarterly` 10-20);跨天最长 `signal_kelly_frozen_missing_small` **连续 13 天每天报**。
3. **抑制量**:`suppression_ledger` 只剩 10-22/10-23 两天 882 条 —— dedup 498(56.5%)、active 365(41.4%)、domain_aggregate 10、notice_budget 6、escalation_window 3。`alert_domains.json` 显示 `r2_deploy` 累计直发 20 条、吸收 284 条。30 天的代理口径是 `schedule_monitor` 日志 `[suppress]` **6,801 条/23 天**(峰值 10-16 887),但与台账口径不同,不能相加。
4. **漏报检查(最关键)**:
   - **告警黑洞 10-19 11:00:06 ~ 10-22 01:30:07,共 62.5 小时**:期间 17 个"unit 失败日"没有 unit 级告警(10-19 2 个、10-20 9 个、10-21 6 个),只有 deploy 域告警间接覆盖。修复后 10-22 01:30 起恢复(commit `42be1d60f` + `d12821cc6`)。
   - 10-17 02:46 `trade-gold-night` 失败,当天无具名告警,只有 03:45 的"1 条 warning 汇总";该汇总正文未留存 → **无法证实也无法证伪**,列入数据不足。
   - 当前 3 个 trade failed 都有告警:nextday 10-23 00:00 巡检、pf-score 16:15 巡检、s06 20:58 具名 critical。

## B. 脚本稳定:把握度

1. **30 天总盘**(syslog 5 周轮转重建,43 个 trade unit):**11,455 次运行 / 217 次失败 / 成功率 98.11%**。剔除 4 个高频监控循环后,**业务任务 2,701 次 / 216 失败 / 92.00%**;再剔除 fetch-news 为 1,219 次 / 121 失败 / **90.07%**;监控循环本身 8,754 次 / 1 失败 / 99.99%。分半月:09-23~09-30 95.41%,10-01~10-23 98.84%,趋势向好。
2. **失败高度集中**:前 6 个 unit 占 166/217 = **76.5%**(fetch-news 95、public-fund-daily 26、etf-national-team 13、lhb 12、futures 11、fund-quarterly 9)。按小时看,**16:00-23:59 占 154/217 = 71.0%**,集中在 R2 锁窗口和 deploy 闸门链,是系统性不是偶发。
3. **连续失败 ≥3**:fetch-news 20 次(09-29 起,已恢复)、public-fund-daily 6(09-28)、fund-quarterly 6(10-20 起,闸门修复后已停)、turnover 5(10-12)、lhb/futures/etf-nt/r2-consistency 各 4、s06/daily-brief/nextday 各 3。当前仍 failed 的 trade unit:**nextday-plan(10-22 22:38 exit 1)、pf-score-daily(10-23 16:10 timeout)、s06-snapshot(10-23 20:58 rc124)**,外加与本项目无关的 fwupd。
4. **自愈成效很差**:30 天触发 39 次,exit0 仅 **9 次 = 23.1%**;其中 `etf_national_team` **24 次全失败(0/24)**,13 天打满"每日 3 次"上限后停止。backfill_evening 4/9、lab_auto 5/6。结论:自愈对 deploy 闸门类根因无效,只是重跑;不算掩盖(告警仍在),但会消耗 3 次/天的重试额度。
5. **停摆检测**:43 个 trade timer 的 LastTrigger 全部落在预期周期内,**30 天未发现停摆**。但 `schedule_stats` 只跟踪 **19 个任务**,public-fund-daily/quarterly、pf-score-daily、kelly-intraday-rerun 等 **24 个 timer 不在"按计划执行"检查范围**;这 24 个"根本没跑"不会被发现,只能靠失败后的 failed-unit patrol 兜底。把握度建议表述:**"业务任务首次成功率约 90%,全 unit 98.1%;失败必告警的把握中高(黑洞刚修、假 OK 仍活);不出现静默停摆的把握,目前依赖人工巡检而非系统覆盖。"**

## C. 性能空间(实测)

1. **首屏体积**(腾讯云单点 curl,非真实用户 RUM):index + 8 个核心资源 = **1,672,352 B**;ss.fx8.store 压缩后 **481,573 B**;s.sugas.site **9/9 资源无压缩,原样 1,672,352 B**(app.min.js 单文件 1,090,838 B)。**s 站开压缩可省约 1.19MB(-71%),成本低、风险低 = 第一优先**。
2. **overview 轮询**:每 3 分钟拉全量 `overview.json`,实测 **1,867,758 B raw / 210,496 B gz**,且 `_NO_CACHE_URLS` 命中 → `?_=Date.now()` + no-store,无轻量端点。按盘中 20 次/小时算,**每标签页约 4.2MB/h(压缩后)**;目标 37.9KB 可再省约 82%。第二优先。
3. **overfit_monitor 首屏**:首页"枯竭 chip"会调 `_fetchOverfitMonitor`,实测 **3,993,184 B raw / 468,393 B gz**;`overfit_monitor_ext.json` 10.58MB 已按需。懒加载/只拆 `recent` 可省约 **468KB 首屏(-28%)**,第三优先。
4. **R2**:data-large 23 个文件 **2,574.8s(10-20)/1,420.8s(10-21)** vs 10-08 基线 472.2s,**慢 5.4x / 3.0x**;按已知 178.9MB 两文件算吞吐下界 **69.5KB/s**,小文件中位仍有 175,729~197,072 B/s。nextday 480s 内层超时必输锁;update_all 66~71 分钟。
5. **新发现的最大空间**:31 天 480 个 deploy 日志,其中 **337 次全量(≥5 分钟),累计 6,854 分钟 ≈ 114 小时**,平均 20.3 分钟/次;每次 export **357 个 JSON / 420.2MB**。合并部署或增量 export 是尚未列进待办的大头(需先核并发重叠,避免虚高)。另有 `static-site/data` **2.0GB / 269 文件 / 57 个 >200KB / 77 个 .gz 共 31.8MB 冗余**。

## 最严重的 3 个发现

1. **监控假 OK 仍在线(最严重)**:10-20 18:45、19:45 日志打印"OK 所有任务按计划执行,无漏跑,无退出失败",而 lhb-backfill 已在 18:38/19:38 failed;10-23 16:15 同样打印 OK,而 pf-score-daily 16:10 已 timeout。根因:`last_exit` 取自任务日志的 DONE 行(`schedule_monitor.sh:547/613`、`gen_schedule_stats.py:1071-1111`),systemd 真实退出码只在 pending 分支读;且只覆盖 19/43 个 timer。实锤:lhb 日志写 `lhb_backfill.sh 结束 2026-10-20 18:37:07 deploy=1`,同刻 `schedule_stats` 写 `last=2026-10-20 18:30 exit=0`。
2. **62.5 小时告警黑洞**:升级档 suppress 提前 return,导致 10-19 11:00~10-22 01:30 新 failed unit 首报被吞,17 个 unit-day 无 unit 级告警。已修复,但证明降噪存在"降过头"的真实窗口。
3. **R2 全局锁串行化**:data-large 单次持锁 25-43 分钟,nextday 480s 必输,337 次全量 deploy/114 小时,71% 失败集中在 16-23 点。稳定性和性能是同一个根因,现有治理项 #308 仍待拍板。

## 诚实标注:数据不足/无法判断

- **30 天完整逐日告警**:没有。`alert_ledger` 10-10 才上线,之前只有日志低估值(09-24~10-09 邮件行 256 条,口径不可比),不能拿来硬比。
- **30 天按域分布**:没有。`alert_daily` 只保当日,`alert_domains` 只有累计计数(重置窗口未知),`alert_digest.jsonl` 只保当日。
- **30 天精确抑制量**:没有。`suppression_ledger` 被 prune 到 2 天,6,801 是 `schedule_monitor` 日志代理口径。
- **10-17 gold-night 是否漏报**:无法判断,03:45 warning 汇总正文未留存。
- **用户侧真实加载体验**:无 RUM,p50/p95 给不出;本次只有腾讯云单点 curl,受线路波动影响。
- **deploy 6,854 分钟**:是运行时长求和,可能有并发重叠,需再核墙钟时间。
- **staticdata 备份 1,680s / 1.07MB**:只有一条心跳,疑似等锁,不能定因。
- **30 天 unit 成败**:来自 syslog(5 周轮转),只有终态没有开始时间;极端 kill 可能漏计。

## 关键复现命令(均在云上只读)

```bash
# 30天unit成败(解析 syslog.4.gz~syslog, 正则 systemd[1]: trade-*.service: Deactivated/Failed)
# 告警分类/重复度
python3 -c '...alert_ledger.jsonl 按 group/subject/key 聚合...'
# 监控假OK实证
grep -aE '^\[2026-10-20 (18:4|19:4)' data/logs/schedule_monitor_launchd.log
grep -aE '^\[2026-10-23 (16:0|16:1)' data/logs/schedule_monitor_launchd.log
# 首屏体积/压缩
curl -s -o /dev/null -w '%{size_download},%{time_total}' https://s.sugas.site/app.min.js
curl -s --compressed -o /dev/null -w '%{size_download}' https://ss.fx8.store/app.min.js
# 大文件清单
ls -S static-site/data | head -25
```

## 结论:三个核心问题的直接回答

- 告警降噪:**方向对但火候过了**。critical 日均降了一半多(-52.1%),可代价是中间出过 62.5 小时告警黑洞(10-19~10-22),17 个"任务失败日"没响起 unit 级告警。黑洞已经修了,但这条证明"降噪降过头"是真能发生的。
- 脚本稳定:**业务任务首次成功率约 90%,全部 unit 98.1%**,而且失败高度集中在 16:00-23:59 这一个窗口(71%),追下去都是 R2 锁和 deploy 闸门这一个根因。**对"不出静默故障"的把握还不能说很高**——监控会打"假 OK",24 个 timer 压根不在巡检范围里。
- 性能:**最大的便宜在 s 站没开压缩**(首屏 1.67MB → 0.48MB,省 71%);其次 overview 轮询每 3 分钟拉 1.87MB、overfit_monitor 首屏再拉 3.99MB。另外 31 天 deploy 累计跑了 114 小时,是还没列进待办的大头。