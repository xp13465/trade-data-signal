# D2 定时任务逐个可靠性体检(2026-10-03)

- 日期:2026-10-03(researcher 只读体检,云上零写入、本仓除本文件零提交)
- 角色:researcher | 维度:37 个定时任务逐个可靠性(迁云 2026-09-12 后首次全量体检)
- 观察窗口:最近 7 天(09-26~10-03)+ 上一交易日 **09-30**;10-01~10-08 国庆休市,10-03 为非交易日,休市跳过属正常
- 基线清单:`docs/deploy/systemd-units-20260912.md` 37 周期任务 + backup-db 独立备份(149d 云上实测为 38 个 trade timer,含 backup-db)
- 结论前置:全部 38 个 timer 在位、38 个 service 最近结果 Result=success、`systemctl list-units --state=failed` 为 0;**未发现真正的「exit 0 假成功/静默失败」**;发现 2 个需跟进异常(nextday-plan 09-30 R2 超时失败、schedule_monitor 对 s06 的状态残留 hold)与若干观察项。

## 0 结论速览

1. **38 个 timer 全在位,OnCalendar 真值与文档/149d 采集一致(无漂移)**;时区 Asia/Shanghai 正确(`timedatectl` 实测)。
2. **38 个 service 最近执行 Result 全 success,0 failed**(`systemctl list-units --state=failed` = 0 loaded)。
3. **休市跳过全部有日志证据**:10 个「1 秒极短」任务(etf/futures/lhb/rzhb/s06/turnover/public-fund-full/overfit/check-data-gap/nextday-gap-check/lab-auto)日志尾部均含「非交易日,跳过」文案,**不是假成功**。
4. **未发现 exit 0 静默失败**:所有任务日志尾部有实际输出,关键产物 mtime 与触发时点吻合(见 §1 表「产物新鲜度实测」列)。
5. **已定位 2 个异常点**(无 P0):
   - **P1-a nextday-plan 09-30 失败 exit=1**:根因 R2 上传超时(300s,149 锁队列/R2 弱网期),**产物已全部落盘**(nextday_plan.json 等 7 文件 mtime=09-30 22:30),告警已发(email+飞书+latest.md 镜像),**失败后无重试**——下次 10-07 22:30 自动重跑补。
   - **P1-b schedule_monitor 对 s06 的状态残留 hold**:s06 09-28 一次 exit=143(600s 超时杀,旧锁/R2 慢期),09-29/09-30 机检六项全 PASS 已恢复(schedule_stats.json 显示 last_exit=0),但 schedule_monitor 巡查日志仍持续 `[hold] s06_snapshot|exit!=0|143 仍在进行中`,与「OK 所有任务按计划执行」判定矛盾——监控数据源不同步(见 §6 P1-b)。
6. **已知问题现状核实**:149 锁拆分根治已落地云上(deploy.sh `--git-phase` 两段式、futures/etf/index_backfill 改自包装 `--nb` 锁、rsync exclude 4 种子均在);149d 错峰待办**未执行**(OnCalendar 无变化,需写授权)。
7. **观察项**(P2):fetch-news 10-01 单日 2 次 600s timeout(旧锁期,10-02 起零复发);backfill-evening 休市日每次触发 30~38min deploy 段1;update-all 休市日 23min 补推;journald 未持久化(09-28 前失败记录溯源只能靠 schedule_monitor 状态)。

## 1 37 个任务总表(38 行:37 周期 + backup-db)

> 数据来源:云上 `systemctl list-timers --all`(2026-10-03 18:12 采集)、`systemctl show <unit> -p ...`、`journalctl -u <unit> --since "7 days ago"`、`data/logs/` 各任务 STAMP 日志 + 产物 `stat`。列说明:最近触发=最近一次触发时间;最近结果=systemd Result/ExitStatus;产物新鲜度=核心产物 stat mtime 与触发对账。

| # | 任务 | 时点 | timer在位 | 最近触发 | 最近结果 | 产物新鲜度实测 | 接告警 | 判定 |
|---|---|---|---|---|---|---|---|---|
| 1 | trade-update-all | 17:50 | ✓ | 10-03 17:50:01→18:13:47 | success/0 | overview.json 18:10、board_etf_map 17:55、sentiment.db 18:10 均随触发 | ✓ | 正常(休市补推分支 23m46s,设计行为) |
| 2 | trade-intraday-snapshot | 09:25-15:35 30档+20:35 | ✓ | 10-03 15:35:01→02 | success/0 | 09-30 交易日 29/30 档 STAMP 日志在位 | ✓ | 正常(休市 1s 跳过) |
| 3 | trade-kelly-intraday-rerun | 09:40 | ✓ | 10-03 09:40:01→02 | success/0 | —(非阻塞,锁在位跳过) | — | 正常 |
| 4 | trade-backfill-evening | 16:35/21:00/02:00 | ✓ | 10-03 16:35:01→17:12:37 | success/0 | etf_national_team.db 16:39、指数/序列全 ok | ✓ | 正常(休市补采 38min,负载重=观察项) |
| 5 | trade-etf-national-team | 20:07/21:30 | ✓ | 10-02 21:30:01→02 | success/0 | 09-30 22:14 跑 166s exit=0 | ✓ | 正常(休市跳过) |
| 6 | trade-etf-track-index | Sun 03:30 | ✓ | 09-27 03:30:00→03:30:59 | success/0 | 周任务,上周末成功 | — | 正常 |
| 7 | trade-lof-track-index | Sun 04:00 | ✓ | 09-27 04:00:01→04:02:53 | success/0 | 周任务,上周末成功 | — | 正常 |
| 8 | trade-fapi-daily | 18:10 | ✓ | 10-03 18:10:00→18:13:32 | success/0 | 今天跑 3m32s,10-01/10-02 均成功 | — | 正常 |
| 9 | trade-futures-backfill | 20:05/21:00 | ✓ | 10-02 21:00:01→02 | success/0 | 09-30 20:05 排队超时跳过(149 已覆盖) | ✓ | 正常(休市跳过;旧锁问题已根治) |
| 10 | trade-gold-night | 02:40 | ✓ | 10-03 02:40:01→02 | success/0 | 「昨日非交易日,无夜盘,跳过」 | ✓ | 正常 |
| 11 | trade-lhb-backfill | 18:30/19:30 | ✓ | 10-02 19:30:01→02 | success/0 | 09-30 排队超时跳过(149 已覆盖) | ✓ | 正常 |
| 12 | trade-rzhb-backfill | 08:00/19:15 | ✓ | 10-03 08:00:01→05 | success/0 | T+1 早晨 4s 正常(见 memory rzhb-dur-1s-t1-normal) | ✓ | 正常 |
| 13 | trade-turnover-backfill | Mon-Fri 21:10 | ✓ | 10-02 21:10:00→00 | success/0 | 10-01/10-02 非交易日 0s 跳过 | — | 正常 |
| 14 | trade-ab-direction-anchor | 21:15 | ✓ | 10-02 21:15:01→02 | success/0 | 休市跳过 | — | 正常 |
| 15 | trade-nextday-plan | Mon-Fri 22:30 | ✓ | **09-30 22:30:01→22:35:19** | **exit=1** | nextday_plan.json mtime 09-30 22:30:03(已落盘) | ✓(severe告警已发) | **异常 P1-a**:R2 上传超时 300s 判失败,产物已落盘,无重试 |
| 16 | trade-nextday-gap-check | Mon-Fri 09:26 | ✓ | 09-30 09:26:01→07 | success/0 | 「1 笔无伪跳空,无标记」 | — | 正常 |
| 17 | trade-s06-snapshot | Mon-Fri 20:35 | ✓ | 09-30 20:35:01 | success/0(**09-28 exit=143**) | kelly_mode_s06_state.json 09-30 20:35 两树一致,机检六项全 PASS | ✓(SEVERE已发) | 观察 P2:09-28 一次 600s 超时,09-30 恢复;monitor hold 残留见 P1-b |
| 18 | trade-check-data-gap | Mon-Fri 22:35 | ✓ | 09-30 22:35:01→13 | success/0 | 有 warn(12 个入样信号无交易),退出码 0 | ✓ | 正常(warn 是数据提示) |
| 19 | trade-daily-brief | 20:40 | ✓ | 09-30 20:40(交易日) | success | daily_brief.log:邮件+飞书已发(🔴 偏强 把握度50) | ✓ | 正常(L38 教训:休市跳过已防) |
| 20 | trade-daily-summary-supplement | 20:30 | ✓ | 09-30 20:30:05 | success | .err 日志:9-28/29/30「✓邮件已发送」;10-01/02「非交易日跳过」 | — | 正常(一度误判停更=查错文件,.log 是 stdout,实际在 .err) |
| 21 | trade-brief-push | 20:45 | ✓ | 10-02 20:45:01→02 | success/0 | 休市跳过 | — | 正常 |
| 22 | trade-fetch-news | 每小时 :01/:45 | ✓ | 10-03 18:01:00→23 | success/0 | news_digest.json 18:01:03 更新 | ✓(R2 skip 计数,3轮阈值) | 基本正常(10-01 单日 2 次 timeout,见 P2) |
| 23 | trade-pf-score-daily | 16:00 | ✓ | 10-03 16:00:01→16:08:09 | success/0 | 8 分钟,休市也跑 | — | 正常 |
| 24 | trade-pf-score-weekly | Sun 03:17 | ✓ | 09-27 03:17:01→03:42:21 | success/0 | 25 分钟,周任务成功 | — | 正常 |
| 25 | trade-pf-stage0-nav | Fri 01:43 | ✓ | 10-02 01:43:01→07:44:10 | success/0 | 6h 大任务,周五成功 | — | 正常 |
| 26 | trade-pf-stage0-overview | Sun 02:17 | ✓ | 09-27 02:17:00→02 | success/0 | 数据就绪快速完成 | — | 正常 |
| 27 | trade-pf-stage0-risk | 每月15日 02:33 | ✓ | 09-15 02:33:01→01 | success/0 | 月任务,9-15 完成 | — | 正常 |
| 28 | trade-pf-stage0-manager | 每月1日 02:47 | ✓ | 10-01 02:47:00→08:01:44 | success/0 | 5.3h,10-01 完成 | — | 正常 |
| 29 | trade-public-fund-daily | 16:30/17:00 | ✓ | 10-03 17:00:00→01 | success/0 | 休市跳过 | ✓ | 正常 |
| 30 | trade-public-fund-estimation | 10:00/11:00/13:30/14:30 | ✓ | 10-03 14:30:01→02 | success/0 | 休市跳过 | — | 正常 |
| 31 | trade-public-fund-full | 22:00 | ✓ | 10-02 22:00:01→02 | success/0 | 休市跳过 | ✓ | 正常 |
| 32 | trade-public-fund-quarterly | 03:00/04:00/07:00 | ✓ | 10-03 07:00:01→02 | success/0 | 休市跳过 | — | 正常 |
| 33 | trade-overfit-monitor | Mon-Fri 21:40 | ✓ | 09-30 21:40(74s) | success/0 | push_schedule_stats PASS;10-01/02 跳过 | ✓ | 正常 |
| 34 | trade-lab-auto | 19:00 | ✓ | 10-02 19:00:01→02 | success/0 | lab JSON mtime 09-30 19:01(最后交易日) | — | 正常 |
| 35 | trade-us-stock-morning | 05:00 | ✓ | 10-03 05:00:01→05:22:50 | success/0 | 22 分钟,采集=0 deploy=0,美股数据仍推 | — | 正常 |
| 36 | trade-self-heal | 每15分 | ✓ | 10-03 18:07:00→01 | success/0 | 每 15 分钟稳定在跑 | ✓ | 正常 |
| 37 | trade-schedule-monitor | 每15分 | ✓ | 10-03 18:15:06 | success/0 | schedule_stats.json 18:15:02 更新;巡查「无漏跑无失败」 | ✓ | 正常(s06 hold 见 P1-b) |
| 38 | trade-backup-db | 21:00 | ✓ | 10-02 21:00:01→21:05:03 | success/0 | backups/ 10-02 21:00 两份 DB 备份在位 | ✓ | 正常 |

## 2 静默失败清单(exit 0 但产物没更新)

**排查方法**:逐任务取「最新 STAMP 日志 mtime」+「核心数据产物 stat mtime」与触发时点对账;对「1 秒极短」任务逐个 tail 日志尾部验证跳过文案;对关键产物(overview.json/board_etf_map.json/news_digest.json/kelly_mode_s06_state.json/nextday_plan.json/schedule_stats.json/DB/backups)stat 实测。

**结论:未发现真正的静默失败案例。** 下表为排查过的「疑似 → 排除」项:

| # | 疑似项 | 对账结果 | 证据 |
|---|---|---|---|
| 1 | daily-summary-supplement `.log` mtime 停在 09-13 | **排除(查错文件)**。脚本 logging 走 stderr,`.log`(stdout)本就不更新;真实日志 `.err` 文件 09-28/29/30 连续「✓ 邮件已发送」 | `ls -la daily_summary_supplement_launchd.err` → mtime Oct 2 20:30,尾部 9-28/29/30 三条「✓ 邮件已发送至 234058394@qq.com」 |
| 2 | s06_snapshot schedule_monitor 报 `exit!=0|143` | **监控状态残留,任务本体已恢复**。s06 09-29/09-30 机检六项全 PASS 且产品 mtime 09-30 20:35;schedule_stats.json 显示 last_exit=0 | schedule_monitor 日志 `[hold] s06_snapshot\|exit!=0\|143 仍在进行中` vs schedule_stats.json `"last_exit": 0` |
| 3 | 「1 秒极短」10 任务(怀疑假成功) | **排除**。全部有「非交易日,跳过」文案 | 见 §5 反证项证据 |
| 4 | lab JSON mtime 停在 09-30(10-02 19:00 触发) | **排除**。update_lab.sh 判非交易日跳过(IS_TRADING=0),休市不跑 lab 回测 | `update_lab_20261002_1900.log`:「非交易日,跳过 lab 回测(无新日线)」 |
| 5 | nextday_plan.json mtime 09-30 22:30(10-01/02 触发未更新) | **排除**。10-01/02 休市跳过;09-30 产物已落盘(但那次任务 exit=1,见 P1-a) | journal:10-01/02 22:30 Deactivated 1s;sched 检查在任务本体 |

**静默失败面结论**:38 个任务全部「日志有输出或跳过有文案」+「产物 mtime 吻合」,无 exit0 假成功。唯二真正的异常(nextday-plan R2 超时、s06 09-28 超时)都**有告警**,不是静默。

## 3 时点冲突与依赖顺序

### 3.1 时点冲突(云上 OnCalendar 真值 = 149d 采集一致,现行冲突 5 组)

| # | 重叠组 | 性质 | 149d 建议 |
|---|---|---|---|
| 1 | 20:05 futures-1 vs 20:07 etf-1(错 2 分钟) | 双 deploy 段1 同刻并发(R2 带宽/写中间态) | futures 挪 19:45 或 etf 挪 20:25(未执行) |
| 2 | 16:30 public-fund-1 vs 16:35 backfill-1 | public-fund 段1 实测 13m20s,大概率交叠 | public-fund 挪 16:20(未执行) |
| 3 | 18:30 lhb-1 vs update-all 主链尾段(实测到 18:35) | 双段1 交叠约 5min | lhb 挪 18:50(未执行) |
| 4 | 21:00 backfill-2 + futures-2 + backup-db 三连 | 双全量段1 + R2 备份同刻 | futures 点2 挪 21:20(未执行) |
| 5 | 20:30 supplement + 20:35 s06 + 20:40 brief + 20:45 push | 密集但非段1,伤害小 | 可不动 |

> 判定:149 锁拆分落地后,旧根因「排队饿死」已拆除,错峰价值降级为「减少双段1 R2 带宽竞争/写中间态」;**149d 错峰当前未执行**(纯待办,需写授权),10-08 开市后首个交易日可观察双段1 并发实测再决策。

### 3.2 依赖顺序

| 依赖链 | 顺序保证 | 前序失败后果 |
|---|---|---|
| update-all(17:50)→deploy all | deploy.sh 内部段1 锁外 + 段2 `exec with_lock.py` git 锁(149a) | 段1 失败→段2 不跑,推送缺失,次日 deploy 全量追平(149 兜底链) |
| backfill → deploy(各自的 mode) | 同 update-all 两段式 | 09-30 nextday-plan R2 超时失败→**无重试**,下次 22:30 自动重跑 |
| fetch-news → staticdata_sync news-fetch | subprocess timeout=600,排队最久 10min 被杀 | 06-30 单日 2 次超时后 30min 重试兜底自愈 |
| daily-brief → staticdata_sync daily-brief | 阻塞等锁,秒级 | — |
| self-heal → 可触发 update_all force | 149d 记录 | — |
| 盘后 deploy 链末端 | deploy.sh L963-1005 `systemd-run staticdata-backup-<ts>.service` 触发 async | async 独立 `trade_backup_r2.lock` 非阻塞,抢不到跳过不排队(149a 已落地) |

**依赖面结论**:跨任务无显式编排(靠时点 + 各任务自身兜底);唯一缺「失败重试」的是 nextday-plan(见 P1-a)。hint:从 10-02/10-03 实际运行看,锁拆分后 async 与段1 并行无排队异常(10-03 update-all 18:13:46 完成,verify-r2 补传 35 个即常态对账)。

## 4 已知问题现状核实(149 锁系列 / 149d 错峰)

### 4.1 #149 锁队列结构性积压 — **根治已落地(149a,2026-10-02)**
云上代码 grep 实测(脚本路径 `/home/ubuntu/code/trade-data-signal/scripts/`):
- `deploy.sh` 两段式:`grep -n "git-phase" deploy.sh` → L39-45「首次进入(不带 --git-phase)= 段1...段1 末尾 exec with_lock.py 重入本脚本(带 --git-phase)= 段2」且 L751 `exec "$PY" "$GIT_REPO/scripts/with_lock.py" --block-timeout "${GIT_LOCK_TIMEOUT:-3600}" "$LOCK" bash "$0" --git-phase "$@"` **在**。
- 10 处外层锁拆除:futures_backfill.sh L37-40、etf_national_team_backfill.sh L40-43 均为自包装 `with_lock.py --nb` 自锁重跑自己,不再包 deploy;index_backfill.py L1138 `["bash", "scripts/deploy.sh", "backfill"]`(无外层锁)。
- #119 rsync exclude:deploy.sh L559-560 `--exclude=index_etf_map.json --exclude=stock_codes.json --exclude=trade.db --exclude=trade_dates.txt` **在**。
- 锁文件拓扑:`/tmp/` 下 17 个自锁(各 backfill/snapshot/lab/turnover/fund_nav_upload 等)+ `trade_deploy.lock` + `trade_backup_r2.lock`,与 149d §1.3 一致。
- **生效证据**:10-02/10-03 无任何「排队等锁超时」日志(149 报告 09-28/29/30 每天都有);10-03 18:13 update-all 段1 锁外并发完成,verify-r2 自动补传 35 个(常态对账,非排队)。
- **未验证部分**:锁拆分后**无交易日样本**(10-01 起全国庆休市),「17:50 主链不再排队」「双段1 并发实测」需 10-08 开市后首个交易日验证(149a §8 云上验证命令未执行,需写权限/交易日)。诚实标注:本维度对锁拆分的判定 = 「代码形态已落地 + 非交易日无竞争样本」,结论覆盖范围有限。

### 4.2 #149d 错峰计划 — **未执行(纯待办)**
- 云上全部 38 timer OnCalendar 真值已逐一遍历,与 149d §1.2 表**逐项一致**:futures 仍 20:05/21:00、public-fund-daily 仍 16:30/17:00、lhb 仍 18:30/19:30、daily-summary-supplement 仍 20:30——149d 五条建议均未落到 timer(需写授权,systemctl daemon-reload 未发生)。

### 4.3 省 token 说明
本体检为只读,未执行任何 `systemctl start/stop/enable/disable/daemon-reload`,无状态变更。

## 5 反证项(逐一查过、确认正常)

| # | 任务 | 证据(命令 + 输出片段) |
|---|---|---|
| 1 | trade-daily-summary-supplement | `.err` 日志 9-28/29/30「✓ 邮件已发送至 234058394@qq.com:[补充速递·T日]...」;10-01/02「supplement 模式:非交易日,跳过不发邮件」 |
| 2 | trade-etf-national-team | `etf_national_team_backfill_20261002_2130.log`:「交易日判断: IS_TRADING=0 / 非交易日，跳过ETF汪汪队采集（force 可绕过）/ 结束（非交易日）」 |
| 3 | trade-futures-backfill | 同上格式「非交易日，跳过期货采集」 |
| 4 | trade-lhb-backfill | 同上「非交易日，跳过龙虎榜采集」 |
| 5 | trade-s06-snapshot | 09-30 日志段「✓ S06 快照机检全 PASS(独立复算/时序/键集/阈值单源/锁死不变式/前段元数据六项)」+ kelly_mode_s06_state.json mtime 09-30 20:35 两树一致 |
| 6 | trade-turnover-backfill | 10-01/10-02「结束（非交易日）」0s |
| 7 | trade-public-fund-full | 「非交易日，跳过公募基金全量补充」 |
| 8 | trade-overfit-monitor | 09-30 21:40 `push_schedule_stats.sh 结束...退出码=0`;10-01/02「非交易日, 跳过过拟合监控打点」 |
| 9 | trade-check-data-gap | 09-30 22:35:13 exit=0(带 warn 提示);10-01/02 跳过 |
| 10 | trade-nextday-gap-check | 09-30「执行日 20260930 全部 1 笔无伪跳空, 无标记」exit=0;10-01/02 跳过 |
| 11 | trade-update-all(今天) | `update_all_20261003_1750.log` 头:「交易日判断: IS_TRADING=0 FORCE=0 / 非交易日，跳过采集，仅 deploy 补推数据」→ 段1 补推,18:13:47 完成 exit=0 |
| 12 | trade-gold-night | `gold_night_20261003_0240.log`:「昨日 2026-10-02 非交易日, 无夜盘, 跳过/结束(闸门跳过, 非交易日)」 |
| 13 | trade-daily-brief | `daily_brief.log` 9-30「邮件已发送...🔴 偏强（把握度 50/100）」;10-01/02「非交易日,跳过(不生成不覆盖不通知)」 |
| 14 | trade-backup-db | backups/ `etf_national_team_20261002_2100.db` + `sentiment_20261002_2100.db` 在位(10-02 21:00,今天 21:00 未到) |
| 15 | trade-pf-stage0-nav / manager | 10-02 01:43→07:44、10-01 02:47→08:01,大任务成功 |
| 16 | trade-intraday-snapshot(09-30 交易日) | 09-30 盘中 29/30 档 STAMP 日志在位(0925~1535),单档日志含「Cache purge 完成」 |

## 6 分级问题表

### P0(立即处理)— 无
本次体检未发现需要立即处理的事故级问题:0 failed service、无静默失败、无数据断供中(休市期数据链路正常)。

### P1(本周)— 2 条

#### P1-a nextday-plan 09-30 失败(exit=1)且无重试
- **现象**:09-30 22:30:01 启动,22:35:19 退出码=1;`journalctl -u trade-nextday-plan.service` 尾部:
  ```
  [nextday_plan] ⚠ R2 上传超时(300s, 将告警)
  ✗ 次日买入计划生成失败 rc=1
  [notify] 邮件已发送至 234058394@qq.com：[告警] [cloud] 次日买入计划生成失败 09-30 22:35
  [notify] Feishu 已发送...次日买入计划生成失败 09-30 22:35
  ```
- **证据命令**:`journalctl -u trade-nextday-plan.service --since "7 days ago"` + `awk "/nextday_plan.sh 开始 2026-09-30/{f=1} /nextday_plan.sh 结束 2026-09-30/{f=0} f" nextday_plan_launchd.log | tail -20`
- **根因**:R2 上传 300s 超时(149 锁队列/R2 弱网期 09-30 晚的残留影响),`upload_r2.py upload-data-files` 超时被判失败。**产物已全部落盘**(nextday_plan.json/auto_trade_steps.json/signal_kelly_day_snapshot.json 三处 mtime=09-30 22:30)。
- **影响**:10-01 的计划生成失败;10-01~10-07 休市期前端计划数据靠 09-30 落盘产物(今天 update-all 补推已把 R2 同步,verify-r2 自动补传 35 个),影响可控;10-07 22:30 自动重跑。
- **建议**:①给 nextday-plan 的 R2 上传段加失败重试(如重试 2 次 + 超时放宽);②或在失败时把「产物已落盘但 R2 未上传」标记交给次日 update-all 补推兜底(现状其实已有此兜底,但脚本仍判 exit=1,建议失败语义改为「产物已落盘则非致命,仅告警不 exit 1」,避免告警噪音)。需要 implementer 评估。

#### P1-b schedule_monitor 对 s06 的状态残留 hold(监控数据源不同步)
- **现象**:s06 09-28 一次 exit=143(600s 超时被杀,R2 段,旧锁/R2 慢期),09-29/09-30 已恢复正常(机检六项全 PASS、schedule_stats.json `"last_exit": 0`);但 `schedule_monitor_launchd.log` 每 15 分钟持续输出:
  ```
  [hold] s06_snapshot|exit!=0|143 任务仍在进行中(dur=null), 不判恢复(保持 active)
  ```
  且同时输出 `[2026-10-03 18:15:01] OK 所有任务按计划执行，无漏跑，无退出失败`——**两句话矛盾**。
- **证据命令**:`grep -a "s06.*143" schedule_monitor_launchd.log`;`grep -aA8 '"s06_snapshot"' schedule_stats.json`(last_exit=0)。
- **影响**:①s06 的失败状态(09-28)未随 09-30 成功清除,监控展示位持续报旧异常;②若 s06 再失败,suppress 逻辑可能因为「已告警过」而不重发,造成漏报(需 implementer 核实 schedule_monitor 的 s06 判定数据源与 last_exit 更新路径)。
- **建议**:核查 schedule_monitor 中 s06 的「exit/dur」读取来源(schedule_stats.json?独立状态文件?),确认 09-30 成功为何没清 hold;修好后 s06 状态应显示 09-30 exit=0。开市前(10-08 前)处理。

### P2(观察)— 5 条

| # | 现象 | 证据 | 建议 |
|---|---|---|---|
| 1 | fetch-news 10-01 16:45、17:01 两次 `Failed with result 'timeout'`(600s 被 systemd 杀),10-02 起零复发 | `journalctl -u trade-fetch-news.service --since "2026-10-01 16:00" --until "2026-10-02 00:00"` 显示 4 条 timeout;10-02/10-03 grep -c "Failed" = 0 | 归因旧锁队列期 staticdata_sync 排队等锁超时;10-08 开市后观察是否复发,若复发则需给 news-fetch 的锁排队单独调短 timeout |
| 2 | backfill-evening 休市日每次触发 30~38min deploy 段1(02:00→02:29:39、16:35→17:12:37) | service show `ExecMainExitTimestamp=17:13:03`;日志尾部 `deploy.sh 结束 ... 退出码=0` | 设计行为(休市补采+补推),但一天 3 点各 30min deploy 是盘后 R2 带宽主要来源;可评估 02:00 点是否必须跑 deploy 或改为仅补采 |
| 3 | s06 09-28 exit=143 单次超时(机检 PASS 后 R2/评级段被杀),09-29/30 已恢复 | 日志 09-28 段「机检全 PASS」后中断;schedule_monitor SEVERE 告警 09-28 23:45 | 已告警覆盖;10-08 后 s06 每个交易日 20:35 重跑,观察不再复发即可关闭 |
| 4 | update-all 休市日跑完整补推分支(今天 17:50→18:13:47,23m46s) | `update_all_20261003_1750.log`「非交易日,仅 deploy 补推数据」 | 设计行为;若考虑省带宽可在休市且无数据变化时跳过,需用户拍板 |
| 5 | systemd journal 未持久化(journal 只保留约 2 天,09-28 前 s06/nextday 失败原记录已不可查) | `journalctl -u trade-s06-snapshot.service --no-pager` 最早仅 10-01 | 建议 `Storage=persistent`(需写 /etc/systemd/journald.conf,写权限项),防故障溯源困难 |

## 复现段(全部只读命令,可照跑)

```bash
# 云上登录(只读)
ssh -i ~/tdsignal.pem -o BatchMode=yes -o ConnectTimeout=15 ubuntu@122.51.111.173 '...'

# 1. 时区 + 全量 timers + failed services
timedatectl
systemctl list-timers --all --no-pager
systemctl list-units --type=service --state=failed --no-pager

# 2. 38 个 trade service 最近结果(Result/ExecMainStatus/起止/ActiveState)
for u in $(systemctl list-timers --all --no-pager | awk '$NF ~ /^trade-/ {print $NF}' | sed "s/\.timer/.service/"); do
  echo "=== $u ==="; systemctl show $u -p Result,ExecMainStatus,ExecMainStartTimestamp,ExecMainExitTimestamp,ActiveState | tr "\n" " "; echo
done

# 3. journal 全量异常扫描(最近7天)
journalctl --since "7 days ago" --no-pager | grep -iE "timeout|Failed|fail|status=1|status=127" | head -40

# 4. nextday-plan 09-30 失败点
awk "/nextday_plan.sh 开始 2026-09-30/{f=1} /nextday_plan.sh 结束 2026-09-30/{f=0} f" /home/ubuntu/code/trade-data/data/logs/nextday_plan_launchd.log | tail -25

# 5. fetch-news 10-01 timeout
journalctl -u trade-fetch-news.service --since "2026-10-01 16:00" --until "2026-10-02 00:00" --no-pager | grep -E "Starting|timeout|TERM|Failed"

# 6. s06 状态残留对比(monitor vs stats)
grep -a "s06.*143" /home/ubuntu/code/trade-data/data/logs/schedule_monitor_launchd.log | tail -3
grep -aA8 '"s06_snapshot"' /home/ubuntu/code/trade-data/static-site/data/schedule_stats.json

# 7. 149a 锁拆分落地核实
grep -n "git-phase\|GIT_PHASE" /home/ubuntu/code/trade-data-signal/scripts/deploy.sh | head -5
grep -n "with_lock" /home/ubuntu/code/trade-data-signal/scripts/futures_backfill.sh | head -3
grep -n "exclude=index_etf_map\|exclude=trade_dates" /home/ubuntu/code/trade-data-signal/scripts/deploy.sh

# 8. 休市跳过文案抽查(10 个任务)
for pair in "etf_national_team_backfill:etf_national_team_backfill_20261002_2130.log" "futures_backfill:futures_backfill_20261002_2100.log" "s06_snapshot:s06_snapshot_launchd.log" "turnover_backfill:turnover_backfill_launchd.log" "overfit_monitor:overfit_monitor_launchd.log" "nextday_gap_check:nextday_gap_check_launchd.log"; do
  echo "--- ${pair%%:*}"; tail -4 /home/ubuntu/code/trade-data/data/logs/${pair##*:}
done

# 9. 关键产物 mtime 对账
stat -c "%y %n" /home/ubuntu/code/trade-data/static-site/data/overview.json /home/ubuntu/code/trade-data/static-site/data/news_digest.json /home/ubuntu/code/trade-data/static-site/data/kelly_mode_s06_state.json /home/ubuntu/code/trade-data/static-site/data/nextday_plan.json /home/ubuntu/code/trade-data/data/sentiment.db /home/ubuntu/code/trade-data/data/backups/*.db

# 10. daily-summary-supplement 真实日志(.err)
tail -12 /home/ubuntu/code/trade-data/data/logs/daily_summary_supplement_launchd.err
```

## 维度清单完成度自检

| 维度 | 状态 |
|---|---|
| 38 个 timer 在位 + OnCalendar 真值与文档比对 | ✅ 全量遍历,一致 |
| 38 个 service 最近结果(Result/ExitStatus) | ✅ 全量,0 failed |
| journal 最近 7 天异常扫描(timeout/fail/status) | ✅ fetch-news 2 处、fund_nav/signal_kelly HEAD 重试 |
| 静默失败对账(产物 mtime vs 触发) | ✅ 关键产物全对账,未发现静默失败 |
| 休市跳过 vs 假成功判定(10 任务抽查) | ✅ 全有跳过文案 |
| 已知问题现状核实(149/149a/149d) | ✅ 149 根治落地、149d 未执行 |
| 时点冲突与依赖顺序 | ✅ 5 组重叠 + 依赖链表 |
| 反证项 | ✅ 16 条 |
| 分级建议(P0/P1/P2) | ✅ 无 P0,2 P1,5 P2 |
| 观察窗口说明 | ✅ 最近 7 天 + 09-30 交易日 + 10-03 非交易日 |
| 诚实标注 | ✅ 锁拆分无交易日样本、nextday-plan R2 补传为推断(verify-r2 补传证据)、journal 保留期限制 |
