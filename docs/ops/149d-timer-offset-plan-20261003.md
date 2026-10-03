# 149d 云上定时任务错峰 待办清单(只读调研,未执行任何云上写入)

- 日期:2026-10-03
- 角色:researcher(只读,云上零写入)
- 关联:149 根因调研 docs/ops/149-deploy-lock-queue-rootcause-20261001.md;锁粒度拆分、async 锁分离、large-json 增量已落地,本文基于落地后的新时序重新规划错峰。
- 本文为待办清单与建议,不含任何 timer 改动;执行需云上 systemd 写授权(当前无)。

## 0. 结论一句话

锁拆分(deploy 段1 锁外、backfill 外层锁去掉、async 上传移出主锁)落定后,旧根因的「排队雪崩、锁 5.6 小时不空」已被结构性拆除,不再需要为「避免排队饿死」错峰;剩余错峰价值 = 多个 deploy 段1(全量 export 357 JSON/410MB + 多通道 R2)若同时并发,会造成 R2 带宽竞争与 static-site 数据文件写中间态(数据一致性)与上传总量放大;其次是密集段的观测告警观感,以及为失败重试与手动操作留余量。盘后真实紧邻重叠共 5 组(见第 4 节),其中 2 组是「双 deploy 段1 几乎同刻启动」(20:05 对 20:07、21:00 三连),最值得挪。

## 1. 云上实测证据(原始命令输出摘录)

### 1.1 systemctl list-timers(2026-10-03 采集,只读)

53 timers listed.

trade- 前缀 38 个,系统级 15 个(man-db、apt-daily、apt-daily-upgrade、logrotate、dpkg-db-backup、e2scrub_all、fstrim、fwupd-refresh、motd-news、systemd-tmpfiles-clean、update-notifier-download、update-notifier-motd、apport-autoreport、snapd.snap-repair、ua-timer)。

### 1.2 OnCalendar 真值(38 个 trade timer 全部采集自云上单元文件)

| timer unit | OnCalendar 真值 | 交易日限定 |
|---|---|---|
| trade-public-fund-daily | 16:30 / 17:00 | 否 |
| trade-backfill-evening | 16:35 / 21:00 / 02:00 | 否 |
| trade-update-all | 17:50 | 否 |
| trade-fapi-daily | 18:10 | 否 |
| trade-lhb-backfill | 18:30 / 19:30 | 否 |
| trade-lab-auto | 19:00 | 否 |
| trade-rzhb-backfill | 19:15 | 否 |
| trade-futures-backfill | 20:05 / 21:00 | 否 |
| trade-etf-national-team | 20:07 / 21:30 | 否 |
| trade-daily-summary-supplement | 20:30 | 否 |
| trade-s06-snapshot | 20:35 | Mon..Fri |
| trade-daily-brief | 20:40 | 否 |
| trade-brief-push | 20:45 | 否 |
| trade-backup-db | 21:00 | 否 |
| trade-turnover-backfill | 21:10 | Mon..Fri |
| trade-ab-direction-anchor | 21:15 | 否 |
| trade-overfit-monitor | 21:40 | Mon..Fri |
| trade-public-fund-full | 22:00 | 否 |
| trade-nextday-plan | 22:30 | Mon..Fri |
| trade-check-data-gap | 22:35 | Mon..Fri |
| trade-intraday-snapshot | 09:25 至 15:35 共 30 档(含 15:35、20:35 两盘后档) | 否 |
| trade-pf-score-daily | 16:00 | 否 |
| trade-kelly-intraday-rerun | 09:40 | 否 |
| trade-fetch-news | 每小时 :01 与 :45 | 否 |

凌晨与低频组(无盘后竞争,错峰意义低):gold-night 02:40、us-stock-morning 05:00、public-fund-quarterly 03:00/04:00/07:00、public-fund-estimation 10:00/11:00/13:30/14:30、pf-stage0-overview 周日 02:17、pf-score-weekly 周日 03:17、etf-track-index 周日 03:30、lof-track-index 周日 04:00、pf-stage0-nav 周五 01:43、pf-stage0-risk 每月15日 02:33、pf-stage0-manager 每月1日 02:47、nextday-gap-check 交易日 09:26、schedule-monitor 每 15 分钟、self-heal 每 :07/:22/:37/:52。

### 1.3 锁拓扑(锁拆分后,云上脚本 grep 采集)

- trade_deploy.lock(fcntl.flock,with_lock.py):仅持 git 写段,即 deploy.sh 段2(git add/commit/push)、staticdata_sync.sh(默认阻塞)、staticdata_backup_async.sh 段2(git)。秒至分钟级,不再是长跑锁。
- trade_backup_r2.lock:async 的 step3.5b(3.1 万对象 HEAD 比对的 R2 大通道)独立锁,非阻塞,抢不到跳过不排队。
- upload_r2.py 内部 trade_r2_upload.lock(skip-if-locked 或排队,R2_UPLOAD_LOCK_TIMEOUT 默认 7300s)。
- 各 backfill 自锁(非阻塞防重入,不复用 deploy 锁):trade_update_all、trade_etf_nt、trade_rzhb、trade_futures、trade_lhb、trade_public_fund_daily、trade_public_fund_full、trade_intraday_snapshot、trade_lab、trade_turnover、trade_fund_nav_upload、trade_retry_failed_metrics(self-heal)。

### 1.4 deploy 段实测时长(09-30 交易日,旧实现整段持锁;段1/段2 拆分后段1 无锁时长近似,git 段秒级)

| 日志 | 起止(实测) | 时长 | 说明 |
|---|---|---|---|
| deploy_1630(public-fund-daily 点1) | 16:30:41 至 16:44:01 | 13m20s | 段1 export+R2 |
| deploy_1644(backfill-evening 点1) | 16:44:01 至 17:01:04 | 17m00s | |
| deploy_1701(public-fund-daily 点2) | 17:01:04 至 17:58:46 | 57m42s | 含 update_all 触发后旧排队 |
| deploy_1758(update-all 的 deploy all) | 17:58:46 至 18:35:07 | 36m21s | 全量 357 JSON/410MB |
| deploy_1835(lhb 18:30 触发) | 18:35:08 至 19:23:00 | 47m52s | 旧实现排队至 18:35 才拿锁 |
| deploy_2108(backfill-evening 21:00) | 21:08:51 至 21:40:00 | 31m09s | |
| deploy_2140 | 21:40:01 至 22:14:39 | 34m38s | |
| deploy_2214 | 22:14:40 至 23:02:18 | 47m38s | |
| deploy_2302 | 23:02:20 至 23:40:37 | 38m17s | |
| update_all 主链总长(09-30) | 17:50:01 至约 18:41 | 约51min | 采集约8min + 段1 约36min + 收尾 |
| staticdata_backup_async(10-03 非交易日) | 09:40:11 至 09:45:46 | 5m35s | rsync 1s + git 18s + R2 段 |

结论:盘后任意时刻「deploy 段1 在位」都是 13 至 48 分钟量级;update_all 主链段1 窗口约为 17:58 至 18:35(采集 17:50-17:58)。

## 2. 逐 timer 表(38 个 trade timer:干什么、涉不涉 deploy 段1、持不持主锁、是否触发 async 备份、预计耗时)

| timer (unit) | OnCalendar | 干什么(ExecStart 脚本) | 涉 deploy 段1 | 持主锁 | 触发 async | 预计耗时 |
|---|---|---|---|---|---|---|
| trade-fetch-news | :01/:45 每小时 | fetch_news.py 采集+upload-data-files+staticdata_sync news-fetch | 否 | 是(sync 阻塞,秒级) | 否 | 小于5min |
| trade-schedule-monitor | 每15min | schedule_monitor.sh 定时任务巡查 | 否 | 否 | 否 | 秒级 |
| trade-self-heal | :07/:22/:37/:52 | self_heal.sh 自愈(非阻塞 retry 锁) | 可能触发 update_all force | 否 | 否 | 分钟级 |
| trade-intraday-snapshot | 09:25-15:35 30档+20:35 | intraday_snapshot.sh 盘中快照+upload R2 | 否(非阻塞跳过) | 否 | 否 | 分钟级 |
| trade-kelly-intraday-rerun | 09:40 | kelly_intraday_rerun.sh(非阻塞 deploy 锁跳过) | 若跑=deploy | 否 | 否 | 分钟级 |
| trade-nextday-gap-check | 交易日 09:26 | nextday_gap_check.sh 伪跳空剔除 | 否 | 否 | 否 | 约6s |
| trade-public-fund-estimation | 10:00/11:00/13:30/14:30 | public_fund_estimation.sh 估值(自锁) | 否 | 否 | 否 | 分钟级 |
| trade-us-stock-morning | 05:00 | us_stock_morning.sh 美股晨数据 | 否 | 否 | 否 | 分钟级 |
| trade-gold-night | 02:40 | gold_night.sh 黄金夜间数据 | 是(低竞争) | 是(149 根因记录) | 是 | 未知(推断分钟级) |
| trade-public-fund-quarterly | 03:00/04:00/07:00 | public_fund_quarterly.sh(自锁) | 否 | 否 | 否 | 分钟级 |
| trade-pf-stage0-overview | 周日 02:17 | stage0_overview.sh(自锁) | 否 | 否 | 否 | 分钟级 |
| trade-pf-score-weekly | 周日 03:17 | pf_score_weekly.sh(自锁) | 否 | 否 | 否 | 分钟级 |
| trade-etf-track-index | 周日 03:30 | fetch_etf_track_index.py | 否 | 否 | 否 | 分钟级 |
| trade-lof-track-index | 周日 04:00 | fetch_lof_track_index.py | 否 | 否 | 否 | 分钟级 |

| timer (unit) | OnCalendar | 干什么(ExecStart 脚本) | 涉 deploy 段1 | 持主锁 | 触发 async | 预计耗时 |
|---|---|---|---|---|---|---|
| trade-pf-stage0-nav | 周五 01:43 | stage0_nav.sh(自锁) | 待定 | 待定 | 待定 | 未确证见第6节 |
| trade-pf-stage0-risk | 每月15日 02:33 | stage0_risk.sh | 待定 | 待定 | 待定 | 同上 |
| trade-pf-stage0-manager | 每月1日 02:47 | stage0_manager.sh | 待定 | 待定 | 待定 | 同上 |
| trade-pf-score-daily | 16:00 | pf_score_daily.sh 上传 fund score(R2) | 否(仅 R2) | 否 | 否 | 分钟级 |
| trade-public-fund-daily | 16:30/17:00 | public_fund_daily.sh 调 deploy.sh public-fund | 是 | 段2 秒级 | 是 | 实测 13m20s(点1) |
| trade-backfill-evening | 16:35/21:00/02:00 | backfill_metrics.sh 调 index_backfill + deploy | 是 | 段2 秒级 | 是 | 实测 17m(点1)/31m(点2 旧排队) |
| trade-update-all | 17:50 | update_all.sh pipeline 采集 + deploy.sh all | 是(主链) | 段2 秒级 | 是 | 实测采集约8min+段1 36m21s |
| trade-fapi-daily | 18:10 | fapi_daily_syn.sh 最小 export + upload-data-files(7 文件) | 部分(最小 export 非全量) | 否 | 否 | 分钟级 |
| trade-lhb-backfill | 18:30/19:30 | lhb_backfill.sh 调 deploy.sh lhb | 是 | 段2 秒级 | 是 | 实测 47m52s(18:30,旧排队后) |
| trade-lab-auto | 19:00 | update_lab.sh 上传 lab 与 trade-sim JSON(R2) | 否(仅 R2) | 否 | 否 | 分钟至小时级 |
| trade-rzhb-backfill | 19:15 | rzhb_backfill.sh 调 deploy.sh rzhb | 是 | 段2 秒级 | 是 | 推断 15-40min |
| trade-futures-backfill | 20:05/21:00 | futures_backfill.sh 调 deploy.sh futures | 是 | 段2 秒级 | 是 | 推断 15-40min |
| trade-etf-national-team | 20:07/21:30 | etf_national_team_backfill.sh 调 deploy.sh etf-national-team | 是 | 段2 秒级 | 是 | 推断 15-40min |

| timer (unit) | OnCalendar | 干什么(ExecStart 脚本) | 涉 deploy 段1 | 持主锁 | 触发 async | 预计耗时 |
|---|---|---|---|---|---|---|
| trade-daily-summary-supplement | 20:30 | daily_summary_email.py 邮件(只读数据) | 否 | 否 | 否 | 秒级 |
| trade-s06-snapshot | 交易日 20:35 | s06_snapshot.sh 快照+upload-data-files+latest_posrating(R2) | 否(仅 R2) | 否 | 否 | 分钟级 |
| trade-daily-brief | 20:40 | run_daily_brief.sh 加 staticdata_sync daily-brief | 否(仅 R2+sync) | 是(sync 阻塞,秒级) | 否 | 分钟级(模型生成) |
| trade-brief-push | 20:45 | brief_push_wrapper.sh 邮件推送 | 否 | 否 | 否 | 秒级 |
| trade-backup-db | 21:00 | backup_db.sh sqlite 热备+upload-db(R2) | 否(仅 R2) | 否 | 否 | 分钟级 |
| trade-turnover-backfill | 交易日 21:10 | turnover_backfill.sh 上传 intraday 与 data-large(R2) | 否(仅 R2) | 否 | 否 | 分钟级 |
| trade-ab-direction-anchor | 21:15 | run_ab_direction_anchor.sh | 否 | 否 | 否 | 秒级 |
| trade-overfit-monitor | 交易日 21:40 | overfit_monitor.sh 打点 parity 自检 | 否 | 否 | 否 | 分钟级 |
| trade-public-fund-full | 22:00 | public_fund_full.sh 调 deploy.sh public-fund | 是 | 段2 秒级 | 是 | 推断 15-40min |
| trade-nextday-plan | 交易日 22:30 | nextday_plan.sh 生成+R2 upload-data-files | 否(仅 R2) | 否 | 否 | 分钟级 |
| trade-check-data-gap | 交易日 22:35 | check_data_gap_alerts.sh 检查 | 否 | 否 | 否 | 秒级 |

说明:「涉 deploy」者每次调用都会触发 deploy.sh 段1(全量 export+多通道 R2,段2 git 秒级),并在结束时 systemd-run 一个 staticdata-backup async(已升格为独立非阻塞 R2 锁,不再排主队)。

## 3. 盘后时间轴(新时序,交易日)

```
16:00 pf-score(R2)       16:30 public-fund-1(段1约13m)     16:35 backfill-1(段1约17m)
17:00 public-fund-2(段1) 17:50 update_all 主链(采集约8m,段1 17:58-18:35)
18:10 fapi(R2 小)        18:30 lhb-1(段1)                 19:00 lab(R2)    19:15 rzhb(段1)
19:30 lhb-2(段1)         20:05 futures-1(段1)             20:07 etf-1(段1)  20:30 supplement(邮件)
20:35 s06(R2)            20:40 daily-brief(R2+sync)       20:45 push
21:00 backfill-2 + futures-2 + backup-db(段1x2 + R2)      21:10 turnover(R2) 21:15 ab
21:30 etf-2(段1)         21:40 overfit                    22:00 public-fund-full(段1)
22:30 nextday-plan(R2)   22:35 check-gap
```

## 4. 真实重叠分析(5 组,新时序)

1. 20:05 futures-1 对 20:07 etf-1(错 2 分钟,双 deploy 段1 同刻启动)。唯一一组「两个全量 deploy 段1 背靠背 2 分钟内先后启动」。全量 export 覆盖同一批 static-site JSON 与同一批 R2 key,并发窗口内互相覆盖写中间态(数据一致性);R2 多通道双倍并发。09-30 旧实现它俩未留日志(排队到 21:00),新实现直接并发。最值得挪。
2. 16:30 public-fund-1 对 16:35 backfill-1(错 5 分钟)。public-fund 段1 实测 13m20s,backfill-1 16:35 启动时 public-fund 段1 大概率仍在跑(重叠约 10 分钟)。与 16:00 pf-score 相距 30 分钟无碍。
3. 18:30 lhb-1 对 update_all 主链尾段(实测主链段1 到 18:35)。主链段1 与 lhb-1 段1 重叠约 5 分钟;主链更长(失败重试)时重叠更大。09-30 旧实现 lhb 排队到 18:35 才拿锁等于串联,新实现改并发。
4. 21:00 backfill-2 + futures-2 + backup-db 三连(同刻)。backfill-2(实测段1 31 分钟以上)与 futures-2 两个全量 deploy 段1 同时启动,外加 backup-db 的 R2 上传。21:00 至 21:30 另有 turnover、ab、etf-2 紧随,是盘后最拥挤一小时。第二值得挪。
5. 20:30 supplement + 20:35 s06 + 20:40 brief + 20:45 push 密集段。s06(R2 上传)与 daily-brief(模型生成+staticdata_sync 持主锁秒级)紧邻;无全量段1,性质宽松,重叠伤害小。

另注意:每个 deploy 调用方结束触发 1 个 staticdata-backup async,盘后 deploy 调用方 8 个以上(16:30/16:35/17:00/17:50/18:30/19:15/19:30/20:05/20:07/21:00x2/21:30/22:00),盘后 cascade 最高 8 至 10 个 async;async 已非阻塞不排主队,但 step3.5b 大通道(3.1 万对象)与前台段1 的 R2 并发,带宽放大仍是实际支出。

## 5. 错峰建议清单(纯建议,未执行)

适配标准:优先错开「双 deploy 段1 并发」(组1/组2/组4);挪动目标避开交易日盘中(09:30-15:30,deploy 时段闸门拒跑)与数据源发布时间,并与两侧任务保持至少 20 分钟间距。需要改的文件 = 云上 /etc/systemd/system/trade-XXX.timer 的 OnCalendar 行(改后 systemctl daemon-reload,需写授权)。

1. trade-futures-backfill 20:05 挪到 19:45(或对侧 etf 20:07 挪到 20:25)。消除组1「20:05 与 20:07 双段1 同刻启动」。挪 futures 到 19:45 后与 19:30 lhb-2 隔 15 分钟、与 19:15 rzhb 隔 30 分钟,19:15/19:30/19:45 成 15 分钟步进,仍可能边界交叠但不再同刻。风险:19:45 撞 lhb-2 尾段概率低(lhb-2 若 40 分钟则到 20:10);备选挪 etf 20:07 到 20:25(与 20:05 futures 隔 20 分钟、20:30 supplement 前 5 分钟、20:35 s06 前 10 分钟,偏挤)。二选一,推荐挪 futures(futures 点1 无兜底点,点2 21:00 又与 backfill 同刻;etf 有 21:30 兜底点)。需改:trade-futures-backfill.timer(或 trade-etf-national-team.timer)。
2. trade-public-fund-daily 16:30 挪到 16:20。消除组2「16:30 与 16:35 双段1 紧邻」。public-fund-1 16:20 启动(约 16:20 至 16:33 段1),16:30 槽腾空,backfill-1 16:35 启动时 public-fund 段1 已退。风险:16:20 在盘中闸门(15:30)后 50 分钟,安全;与既定点 16:00/17:50 不冲突。需改:trade-public-fund-daily.timer。
3. trade-lhb-backfill 18:30 挪到 18:50。消除组3「lhb-1 与 update_all 主链尾段重叠」。主链段1 实测到 18:35,18:50 启动留 15 分钟余量;与 19:00 lab 隔 10 分钟(仅 R2 非段1)、19:15 rzhb 隔 25 分钟。风险:低;18:50 若撞主链失败重试窗口(概率低,09-30 段1 一次过),段1 并发危害小于旧排队饿死。需改:trade-lhb-backfill.timer。

4. trade-futures-backfill 21:00(点2)挪到 21:20。消除组4「21:00 backfill-2 与 futures-2 双段1 同刻加 backup-db」。futures 点2 挪 21:20 后与 21:15 ab 隔 5 分钟、21:30 etf-2 隔 10 分钟,仍是拥挤段但不再同刻双段1。风险:21:20 至 21:40 相邻偏密;备选是 backfill-evening 点2 21:00 挪 20:15(与 20:07 etf-1 仅隔 8 分钟,不优)。推荐挪 futures 点2;或接受「21:00 并发段1 上限 2 个」不动。需改:trade-futures-backfill.timer。
5. trade-daily-summary-supplement 20:30 挪到 20:25(顺手项)。与 20:35 s06 仅隔 5 分钟,但两者都非段1(邮件与 R2 小),伤害低,可不做。需改(若做):trade-daily-summary-supplement.timer。

### 5.0 核实后「不建议挪」清单(6 条,含依据)

- trade-s06-snapshot 20:35:既定盘后时点(20:35),且交易日 20:35 至 20:40 至 20:45 数据递进链(快照、brief、push)已成格局;不涉段1(仅 R2 小),与 20:30 supplement 交错无实害。不建议挪。
- trade-public-fund-full 22:00:既定盘后时点(22:00);挪早撞 21:40 overfit 与 21:30 etf-2 尾段,挪晚撞 22:30 nextday-plan 与 22:35 check-gap,且 22:00 后无后续段1,实际已最优。不建议挪。
- trade-daily-brief 20:40:既定点(20:40 跑 AI 预测,低峰时点);20:40 后接 20:45 brief-push,链路成立;挪动需同步改 brief-push 与邮件等待语义。不建议挪。
- trade-backup-db 21:00:sqlite 热备+upload-db(R2 小),与 21:00 双段1 同刻但性质轻;21:00 是当日数据齐后备份的最早可靠点,挪走破坏备份语义。不建议挪。
- 非段1 小任务群(turnover、overfit、nextday-plan、check-data-gap、ab-direction-anchor):仅 R2 小或纯检查,对错峰无贡献,挪动引入新交错。不建议挪。
- 凌晨与低频组(gold-night 02:40、backfill-evening 02:00、pf-stage0 系列、quarterly 03:00/04:00/07:00、us-stock 05:00、track-index 周日组):竞争极低,gold-night(02:40 唯一凌晨持主锁者)与 02:00 backfill-3 差 40 分钟。不建议挪。

## 6. 诚实标注

- 实测 vs 推断:timer 清单、OnCalendar、ExecStart、锁文件清单、systemd-run 触发点 = 云上只读实测(第 1.1 至 1.3 节);各 backfill 段1 时长 = 实测(09-30 旧实现)或推断(第 2 节标注)。
- 锁拆分后无交易日样本:10-01 至 10-08 国庆休市,10-02/10-03 非交易日日志均为「跳过采集」极短(update_all 17:50 至 17:56 共 6m29s、async 5m35s),「锁拆分后 deploy 段1 实际时长」无交易日实测,表中沿用 09-30 旧实现实测 13 至 48 分钟(段1/段2 拆分对持锁段总时长影响仅秒级 git 段,差值可忽略),标注为推断。
- pf-stage0-nav / risk / manager 三项未确证(凌晨低频):只读了 ExecStart 行,未展开脚本内部调用链(是否持 deploy 锁、触发 async),因需写权限或大量读码,标注待定。
- 09-30 日志为本报告时长结论的唯一交易日样本;10-02/10-03 为非交易日样本。

## 7. 建议执行顺序(供后续有写授权后参考,非本单动作)

1. 按第 5 节建议 1 至 4 顺序(先解 20:05/20:07 双段1,再 16:30/16:35,再 18:30,再 21:00 三连)逐个改 OnCalendar,每次 systemctl daemon-reload,观察两晚。
2. 每次改后对照 schedule_stats.json(17 tasks 的 last 与 dur)与 149 锁观察器确认无新排队。
3. 若 20:05/20:07 组风险实测过高,回退成本等于改回一行,无需动脚本。

## 复现段(可重跑完整命令,全部只读)

```bash
# 1. 云上 timer 全量(只读)
ssh -i ~/tdsignal.pem -o BatchMode=yes ubuntu@122.51.111.173 'systemctl list-timers --all --no-pager; ls -l /etc/systemd/system/*.timer'

# 2. 38 个 trade timer 的 OnCalendar 真值(只读)
ssh -i ~/tdsignal.pem -o BatchMode=yes ubuntu@122.51.111.173 'for f in /etc/systemd/system/trade-*.timer; do echo "=== $(basename $f) ==="; grep -E "OnCalendar|Description|Unit=" "$f"; done'

# 3. trade service 的 ExecStart(只读)
ssh -i ~/tdsignal.pem -o BatchMode=yes ubuntu@122.51.111.173 'for f in /etc/systemd/system/trade-*.service; do echo "=== $(basename $f) ==="; grep -E "ExecStart|Description|WorkingDirectory" "$f" | head -5; done'

# 4. 锁文件与 systemd-run 痕迹(只读)
ssh -i ~/tdsignal.pem -o BatchMode=yes ubuntu@122.51.111.173 'ls -l /tmp/*.lock 2>/dev/null; grep -rn "systemd-run" /home/ubuntu/code/trade-data/scripts/deploy.sh /home/ubuntu/code/trade-data/scripts/update_all.sh | head'

# 5. 持锁脚本清单(只读)
ssh -i ~/tdsignal.pem -o BatchMode=yes ubuntu@122.51.111.173 'grep -rl "trade_deploy.lock" /home/ubuntu/code/trade-data/scripts/ | head -25'

# 6. 09-30 交易日 deploy 各段起止(只读)
ssh -i ~/tdsignal.pem -o BatchMode=yes ubuntu@122.51.111.173 'cd /home/ubuntu/code/trade-data/data/logs && for f in deploy_20260930_*.log update_all_20260930_1750.log; do s=$(grep -m1 "开始" "$f" | grep -oE "2026-09-30 [0-9:]+" | head -1); t=$(tail -12 "$f" | grep -E "deploy.sh 结束|段2" | tail -1 | grep -oE "2026-09-30 [0-9:]+"); echo "$f | $s | $t"; done'
```
