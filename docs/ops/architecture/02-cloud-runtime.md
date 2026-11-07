# 02 云端当前运行与调度基线

本页是2026-11-07的只读运行观察，不替代[systemd专题权威文档](../../deploy/systemd-units-20260912.md)或[迁移清单](../../deploy/migration-inventory-20260912.md)。基线代码`d4238f5b24aa1aa5632dd5fed1098ce9fbdb3620`；实际云端HEAD`d4238f5b24aa1aa5632dd5fed1098ce9fbdb3620`。观察窗口2026-11-07T14:16:11.903980+08:00至2026-11-07T14:28:13.549907+08:00，统一Asia/Shanghai；分字段时间另存。连接地址、登录身份及密钥位置不入库；这里只使用`host:cloud`别名。

## 已核实范围与计数

枚举44个trade服务、44个trade timer；显式show补齐全部88个对象。44个timer为active，43个服务为inactive、1个failed。**这些都是运行态，全部业务health=unknown**。周期服务inactive/dead可以是正常等待下一次运行；failed原值保留但不等于已证明业务损害。

- 失败运行态：`trade-turnover-backfill.service`，`Result=exit-code`，`ExecMainStatus=124`；业务影响、最后成功及恢复未核。
- 可见cron共8条：当前运行身份2条Node作业、可读系统cron6条。其他身份及2个不可读cron.d文件未覆盖。
- 旧专题文档42对是历史口径；本次当前实测44对，未修改旧权威文件，也未把新增/删除历史来源强行推断出来。
- 运行入口从ExecStart只抽脚本/模块路径，未保留完整参数、内联代码或Environment。当前44个服务均抽到脚本路径，但内联包装中的多个引用不等于完整执行链。

完整单元ID清单、当前完整calendar表达式列表及安全运行属性见[inventory/runtime_cloud.json](inventory/runtime_cloud.json)；修正取证经历和各字段观察时间见下文。每个服务/timer/cron的输入、输出、锁、脚本内层timeout/retry、日历门控、业务失败/恢复判据及运行手册未逐项核实时均为unknown；systemd层Type/timeout/Restart和timer持久化/延迟属性已补充观察。

## 主机、目录及数据角色

`$CODE`=代码checkout，`$DATA`=权威运行数据树，`$OTHER_APP`=其他应用目录（未核归属）；这些为脱敏别名，不是可直接执行的路径。观察到DATA与CODE各有实体data/static-site-data目录；实际输入身份仍需按任务核对，不能因目录都存在就认定内容相同。

| 入口路径 | 实际指向或状态 | 软链 |
| --- | --- | --- |
| $DATA | $DATA | no |
| $CODE | $CODE | no |
| $DATA/app | $CODE/app | yes |
| $DATA/config | $CODE/config | yes |
| $DATA/scripts | $CODE/scripts | yes |
| $DATA/web | FileNotFoundError | unknown |
| $DATA/docs | $CODE/docs | yes |
| $DATA/.venv | $CODE/.venv | yes |
| $DATA/static-site | $DATA/static-site | no |
| $DATA/static-site/data | $DATA/static-site/data | no |
| $DATA/data | $DATA/data | no |
| $DATA/data/logs | $DATA/data/logs | no |
| $CODE/data | $CODE/data | no |
| $CODE/static-site/data | $CODE/static-site/data | no |

特别是`$DATA/web`本次不存在；旧迁移文档曾声明该软链，本页保留当前事实，不据此推断服务缺失或修复动作。

已知库只做文件stat：

| 文件 | 字节 | 边界 |
| --- | --- | --- |
| $DATA/data/sentiment.db | 235139072 | stat only;no content |
| $DATA/data/etf_national_team.db | 260448256 | stat only;no content |
| $DATA/data/stock_daily.db | 203055104 | stat only;no content |
| $DATA/data/stock.db | unknown | FileNotFoundError |

未查数据库内容，缺失的候选stock库路径也不证明股票数据不存在于别处。

## 资源与监听能力

- CPU逻辑核数4；MemTotal=3808588 kB，MemAvailable=3216308 kB；SwapTotal=5242872 kB，SwapFree=5033848 kB。
- 1/5/15分钟loadavg=1.02, 1.01, 1.00。单点快照不说明趋势、容量瓶颈或业务健康。
- `/`、`$DATA`、`$CODE`各自查询的容量值相同：total=63290032128B、used=42371399680B、free=18217885696B；未额外读取挂载配置，不扩推存储身份。
- `ss -lntH`只展示TCP监听能力：22为wildcard（IPv4/IPv6各1条），53有非公开原地址已脱敏。无80/443记录只代表这次本机TCP观察，不能推断外部静态站/Cloudflare故障。未用-p，未查进程argv或归属。

## 服务全表（运行观察）

核心Active/Sub/Result/exit与入口观察时间仍为原probe3；下列Type/timeout/Restart安全属性于2026-11-07T14:28:13.549907+08:00追加确认。44个Type均为oneshot；正常周期oneshot的inactive/dead不标业务故障，failed原值仍保留。TimeoutStart/StopUSec是systemd规范化属性名，展示值可为秒/分钟/infinity字符串；不是脚本内层超时。Restart不等于脚本重试。User与路径仍使用脱敏别名。

| service | 脚本/模块入口摘要 | Type | Active/Sub | Result/exit | TimeoutStartUSec | TimeoutStopUSec | Restart/RestartUSec |
| --- | --- | --- | --- | --- | --- | --- | --- |
| trade-ab-direction-anchor.service | $DATA/scripts/run_ab_direction_anchor.sh | oneshot | inactive/dead | success/0 | 10min | 30s | no/100ms |
| trade-alert-weekly-review.service | $DATA/scripts/alert_weekly_review.py | oneshot | inactive/dead | success/0 | 10min | 30s | no/100ms |
| trade-backfill-evening.service | $DATA/scripts/backfill_metrics.sh | oneshot | inactive/dead | success/0 | infinity | 30s | no/100ms |
| trade-backup-db.service | $DATA/scripts/backup_db.sh | oneshot | inactive/dead | success/0 | 3h 30min | 30s | no/100ms |
| trade-brief-push.service | $DATA/scripts/brief_push_wrapper.sh | oneshot | inactive/dead | success/0 | 10min | 30s | no/100ms |
| trade-check-data-gap.service | $DATA/scripts/check_data_gap_alerts.sh | oneshot | inactive/dead | success/0 | 10min | 30s | no/100ms |
| trade-check-monitor-heartbeat.service | $DATA/scripts/check_monitor_heartbeat.py | oneshot | inactive/dead | success/0 | 10min | 30s | no/100ms |
| trade-cloud-unit-patrol.service | $DATA/scripts/cloud_unit_patrol.sh | oneshot | inactive/dead | success/0 | 10min | 30s | no/100ms |
| trade-daily-brief.service | $DATA/scripts/run_daily_brief.sh | oneshot | inactive/dead | success/0 | 29min | 30s | no/100ms |
| trade-daily-summary-supplement.service | $DATA/scripts/daily_summary_email.py | oneshot | inactive/dead | success/0 | 10min | 30s | no/100ms |
| trade-etf-national-team.service | $DATA/scripts/etf_national_team_backfill.sh | oneshot | inactive/dead | success/0 | infinity | 30s | no/100ms |
| trade-etf-track-index.service | $DATA/scripts/fetch_etf_track_index.py | oneshot | inactive/dead | success/0 | 10min | 30s | no/100ms |
| trade-fapi-daily.service | $DATA/scripts/fapi_daily_syn.sh | oneshot | inactive/dead | success/0 | 30min | 30s | no/100ms |
| trade-fetch-news.service | $DATA/scripts/fetch_news.py | oneshot | inactive/dead | success/0 | 18min | 30s | no/100ms |
| trade-fof-nav-collect.service | $DATA/scripts/run_fof_nav_collect.sh | oneshot | inactive/dead | success/0 | 15min | 30s | no/100ms |
| trade-freeze-orphan-cleanup.service | $DATA/scripts/signal_kelly_freeze_cleanup.py | oneshot | inactive/dead | success/0 | 10min | 30s | no/100ms |
| trade-futures-backfill.service | $DATA/scripts/futures_backfill.sh | oneshot | inactive/dead | success/0 | infinity | 30s | no/100ms |
| trade-gold-night.service | $DATA/scripts/gold_night.sh | oneshot | inactive/dead | success/0 | 45min | 30s | no/100ms |
| trade-intraday-snapshot.service | $DATA/scripts/intraday_snapshot.sh | oneshot | inactive/dead | success/0 | infinity | 30s | no/100ms |
| trade-kelly-intraday-rerun.service | $DATA/scripts/kelly_intraday_rerun.sh | oneshot | inactive/dead | success/0 | 10min | 30s | no/100ms |
| trade-lab-auto.service | $DATA/scripts/update_lab.sh | oneshot | inactive/dead | success/0 | infinity | 30s | no/100ms |
| trade-lhb-backfill.service | $DATA/scripts/lhb_backfill.sh | oneshot | inactive/dead | success/0 | infinity | 30s | no/100ms |
| trade-lof-track-index.service | $DATA/scripts/fetch_lof_track_index.py | oneshot | inactive/dead | success/0 | 6min | 30s | no/100ms |
| trade-nextday-gap-check.service | $DATA/scripts/nextday_gap_check.sh | oneshot | inactive/dead | success/0 | 30min | 30s | no/100ms |
| trade-nextday-plan.service | $DATA/scripts/nextday_plan.sh | oneshot | inactive/dead | success/0 | 10min | 30s | no/100ms |
| trade-overfit-monitor.service | $DATA/scripts/overfit_monitor.sh | oneshot | inactive/dead | success/0 | 32min | 30s | no/100ms |
| trade-pf-score-daily.service | $DATA/scripts/pf_score_daily.sh | oneshot | inactive/dead | success/0 | 30min | 30s | no/100ms |
| trade-pf-score-weekly.service | $DATA/scripts/pf_score_weekly.sh | oneshot | inactive/dead | success/0 | 1h 9min | 30s | no/100ms |
| trade-pf-stage0-manager.service | $DATA/scripts/stage0_manager.sh | oneshot | inactive/dead | success/0 | infinity | 30s | no/100ms |
| trade-pf-stage0-nav.service | $DATA/scripts/stage0_nav.sh | oneshot | inactive/dead | success/0 | infinity | 30s | no/100ms |
| trade-pf-stage0-overview.service | $DATA/scripts/stage0_overview.sh | oneshot | inactive/dead | success/0 | 7h 27min | 30s | no/100ms |
| trade-pf-stage0-risk.service | $DATA/scripts/stage0_risk.sh | oneshot | inactive/dead | success/0 | infinity | 30s | no/100ms |
| trade-public-fund-daily.service | $DATA/scripts/public_fund_daily.sh | oneshot | inactive/dead | success/0 | 35min | 30s | no/100ms |
| trade-public-fund-estimation.service | $DATA/scripts/public_fund_estimation.sh | oneshot | inactive/dead | success/0 | 10min | 30s | no/100ms |
| trade-public-fund-full.service | $DATA/scripts/public_fund_full.sh | oneshot | inactive/dead | success/0 | infinity | 30s | no/100ms |
| trade-public-fund-quarterly.service | $DATA/scripts/public_fund_quarterly.sh | oneshot | inactive/dead | success/0 | infinity | 30s | no/100ms |
| trade-r2-consistency.service | $DATA/scripts/check_r2_consistency.sh | oneshot | inactive/dead | success/0 | 30min | 30s | no/100ms |
| trade-rzhb-backfill.service | $DATA/scripts/rzhb_backfill.sh | oneshot | inactive/dead | success/0 | 10min | 30s | no/100ms |
| trade-s06-snapshot.service | $DATA/scripts/s06_snapshot.sh | oneshot | inactive/dead | success/0 | 1h 57min | 30s | no/100ms |
| trade-schedule-monitor.service | $DATA/scripts/schedule_monitor.sh | oneshot | inactive/dead | success/0 | 10min | 30s | no/100ms |
| trade-self-heal.service | $DATA/scripts/self_heal.sh | oneshot | inactive/dead | success/0 | 10min | 30s | no/100ms |
| trade-turnover-backfill.service | $DATA/scripts/turnover_backfill.sh | oneshot | failed/failed | exit-code/124 | infinity | 30s | no/100ms |
| trade-update-all.service | $DATA/scripts/update_all.sh | oneshot | inactive/dead | success/0 | infinity | 30s | no/100ms |
| trade-us-stock-morning.service | $DATA/scripts/us_stock_morning.sh | oneshot | inactive/dead | success/0 | infinity | 30s | no/100ms |

## timer全表（完整运行属性列表）

**calendar_observation_partial=false**：在2026-11-07T14:28:13.549907+08:00对已枚举44个timer显式补采，完整保留白名单原始文本；按空行分unit、同名键list追加，不再覆盖。共85个实际OnCalendar表达式，9个timer有多个表达式。准确列表字段为inventory记录的`calendar_expressions`（完整、systemd规范化表达式），原始完整值数组另在`runtime.TimersCalendar`，单调计时原值在`calendar_monotonic_values`/`runtime.TimersMonotonic`。空列表表示本次属性没有该种计时表达式，并非未采集。

主机时区Asia/Shanghai。AccuracyUSec/RandomizedDelayUSec/Persistent均为本次运行属性。LastTrigger/NextRealtime是较早probe3的独立观察，未与新calendar查询伪装成同一时点；各记录`field_observed_at`明确来源时间。实际调度器返回规范化的星期/日期表达式，不能只按字符串格式变化判漂移。

| timer | 全部OnCalendar表达式 | AccuracyUSec | RandomizedDelayUSec | Persistent | LastTrigger（probe3） | NextRealtime（probe3） |
| --- | --- | --- | --- | --- | --- | --- |
| trade-ab-direction-anchor.timer | *-*-* 21:15:00 | 1min | 0 | yes | Fri 2026-11-06 21:15:00 CST | Sat 2026-11-07 21:15:00 CST |
| trade-alert-weekly-review.timer | Mon *-*-* 08:20:00 | 1min | 0 | yes | Mon 2026-11-02 08:20:00 CST | Mon 2026-11-09 08:20:00 CST |
| trade-backfill-evening.timer | *-*-* 02:00:00<br>*-*-* 21:00:00<br>*-*-* 16:35:00 | 1min | 0 | yes | Sat 2026-11-07 02:00:00 CST | Sat 2026-11-07 16:35:00 CST |
| trade-backup-db.timer | *-*-* 21:00:00 | 1min | 0 | yes | Fri 2026-11-06 21:00:00 CST | Sat 2026-11-07 21:00:00 CST |
| trade-brief-push.timer | *-*-* 20:45:00 | 1min | 0 | yes | Fri 2026-11-06 20:45:00 CST | Sat 2026-11-07 20:45:00 CST |
| trade-check-data-gap.timer | Mon..Fri *-*-* 22:35:00 | 1min | 0 | yes | Fri 2026-11-06 22:35:00 CST | Mon 2026-11-09 22:35:00 CST |
| trade-check-monitor-heartbeat.timer | *-*-* *:11,26,41,56:00 | 1min | 0 | yes | Sat 2026-11-07 14:11:00 CST | Sat 2026-11-07 14:26:00 CST |
| trade-cloud-unit-patrol.timer | *-*-* 08:27:00 | 1min | 0 | yes | Sat 2026-11-07 08:27:00 CST | Sun 2026-11-08 08:27:00 CST |
| trade-daily-brief.timer | *-*-* 20:40:00 | 1min | 0 | yes | Fri 2026-11-06 20:40:00 CST | Sat 2026-11-07 20:40:00 CST |
| trade-daily-summary-supplement.timer | *-*-* 20:25:00 | 1min | 0 | yes | Fri 2026-11-06 20:25:00 CST | Sat 2026-11-07 20:25:00 CST |
| trade-etf-national-team.timer | *-*-* 21:30:00<br>*-*-* 20:07:00 | 1min | 0 | yes | Fri 2026-11-06 21:30:00 CST | Sat 2026-11-07 20:07:00 CST |
| trade-etf-track-index.timer | Sun *-*-* 03:30:00 | 1min | 0 | yes | Sun 2026-11-01 03:30:00 CST | Sun 2026-11-08 03:30:00 CST |
| trade-fapi-daily.timer | *-*-* 18:10:00 | 1min | 0 | yes | Fri 2026-11-06 18:10:00 CST | Sat 2026-11-07 18:10:00 CST |
| trade-fetch-news.timer | *-*-* *:01,45:00 | 1min | 0 | yes | Sat 2026-11-07 14:01:00 CST | Sat 2026-11-07 14:45:00 CST |
| trade-fof-nav-collect.timer | *-*-* 21:10:00 | 1min | 0 | yes | Fri 2026-11-06 21:10:00 CST | Sat 2026-11-07 21:10:00 CST |
| trade-freeze-orphan-cleanup.timer | *-*-* 21:50:00 | 1min | 0 | yes | Fri 2026-11-06 21:50:00 CST | Sat 2026-11-07 21:50:00 CST |
| trade-futures-backfill.timer | *-*-* 21:20:00<br>*-*-* 19:45:00 | 1min | 0 | yes | Fri 2026-11-06 21:20:00 CST | Sat 2026-11-07 19:45:00 CST |
| trade-gold-night.timer | *-*-* 02:40:00 | 1min | 0 | yes | Sat 2026-11-07 02:40:00 CST | Sun 2026-11-08 02:40:00 CST |
| trade-intraday-snapshot.timer | *-*-* 20:35:00<br>*-*-* 15:35:00<br>*-*-* 15:02:00<br>*-*-* 14:55:00<br>*-*-* 14:45:00<br>*-*-* 14:35:00<br>*-*-* 14:25:00<br>*-*-* 14:15:00<br>*-*-* 14:05:00<br>*-*-* 13:55:00<br>*-*-* 13:45:00<br>*-*-* 13:35:00<br>*-*-* 13:25:00<br>*-*-* 13:15:00<br>*-*-* 13:05:00<br>*-*-* 13:01:00<br>*-*-* 11:32:00<br>*-*-* 11:25:00<br>*-*-* 11:15:00<br>*-*-* 11:05:00<br>*-*-* 10:55:00<br>*-*-* 10:45:00<br>*-*-* 10:35:00<br>*-*-* 10:25:00<br>*-*-* 10:15:00<br>*-*-* 10:05:00<br>*-*-* 09:55:00<br>*-*-* 09:45:00<br>*-*-* 09:35:00<br>*-*-* 09:25:00 | 1min | 0 | yes | Sat 2026-11-07 14:15:00 CST | Sat 2026-11-07 14:25:00 CST |
| trade-kelly-intraday-rerun.timer | *-*-* 09:40:00 | 1min | 0 | yes | Sat 2026-11-07 09:40:00 CST | Sun 2026-11-08 09:40:00 CST |
| trade-lab-auto.timer | *-*-* 19:00:00 | 1min | 0 | yes | Fri 2026-11-06 19:00:00 CST | Sat 2026-11-07 19:00:00 CST |
| trade-lhb-backfill.timer | *-*-* 19:30:00<br>*-*-* 18:50:00 | 1min | 0 | yes | Fri 2026-11-06 19:30:00 CST | Sat 2026-11-07 18:50:00 CST |
| trade-lof-track-index.timer | Sun *-*-* 04:00:00 | 1min | 0 | yes | Sun 2026-11-01 04:00:01 CST | Sun 2026-11-08 04:00:00 CST |
| trade-nextday-gap-check.timer | Mon..Fri *-*-* 09:26:00 | 1min | 0 | yes | Fri 2026-11-06 09:26:00 CST | Mon 2026-11-09 09:26:00 CST |
| trade-nextday-plan.timer | Mon..Fri *-*-* 22:30:00 | 1min | 0 | yes | Fri 2026-11-06 22:30:00 CST | Mon 2026-11-09 22:30:00 CST |
| trade-overfit-monitor.timer | Mon..Fri *-*-* 21:40:00 | 1min | 0 | yes | Fri 2026-11-06 21:40:00 CST | Mon 2026-11-09 21:40:00 CST |
| trade-pf-score-daily.timer | *-*-* 16:00:00 | 1min | 0 | yes | Fri 2026-11-06 16:00:00 CST | Sat 2026-11-07 16:00:00 CST |
| trade-pf-score-weekly.timer | Sun *-*-* 03:17:00 | 1min | 0 | yes | Sun 2026-11-01 03:17:01 CST | Sun 2026-11-08 03:17:00 CST |
| trade-pf-stage0-manager.timer | *-*-01 02:47:00 | 1min | 0 | yes | Sun 2026-11-01 02:47:01 CST | Tue 2026-12-01 02:47:00 CST |
| trade-pf-stage0-nav.timer | Fri *-*-* 01:43:00 | 1min | 0 | yes | Fri 2026-11-06 01:43:00 CST | Fri 2026-11-13 01:43:00 CST |
| trade-pf-stage0-overview.timer | Sun *-*-* 02:17:00 | 1min | 0 | yes | Sun 2026-11-01 02:17:00 CST | Sun 2026-11-08 02:17:00 CST |
| trade-pf-stage0-risk.timer | *-*-15 02:33:00 | 1min | 0 | yes | Thu 2026-10-15 02:33:00 CST | Sun 2026-11-15 02:33:00 CST |
| trade-public-fund-daily.timer | *-*-* 17:00:00<br>*-*-* 16:20:00 | 1min | 0 | yes | Fri 2026-11-06 17:00:00 CST | Sat 2026-11-07 16:20:00 CST |
| trade-public-fund-estimation.timer | *-*-* 14:30:00<br>*-*-* 13:30:00<br>*-*-* 11:00:00<br>*-*-* 10:00:00 | 1min | 0 | yes | Sat 2026-11-07 13:30:00 CST | Sat 2026-11-07 14:30:00 CST |
| trade-public-fund-full.timer | *-*-* 22:00:00 | 1min | 0 | yes | Fri 2026-11-06 22:00:00 CST | Sat 2026-11-07 22:00:00 CST |
| trade-public-fund-quarterly.timer | *-*-* 07:00:00<br>*-*-* 04:00:00<br>*-*-* 03:00:00 | 1min | 0 | yes | Sat 2026-11-07 07:00:00 CST | Sun 2026-11-08 03:00:00 CST |
| trade-r2-consistency.timer | *-*-* 23:20:00 | 1min | 0 | yes | Fri 2026-11-06 23:20:00 CST | Sat 2026-11-07 23:20:00 CST |
| trade-rzhb-backfill.timer | *-*-* 08:00:00 | 1min | 0 | yes | Sat 2026-11-07 08:00:00 CST | Sun 2026-11-08 08:00:00 CST |
| trade-s06-snapshot.timer | Mon..Fri *-*-* 20:35:00 | 1min | 0 | yes | Fri 2026-11-06 20:35:00 CST | Mon 2026-11-09 20:35:00 CST |
| trade-schedule-monitor.timer | *-*-* *:00,15,30,45:00 | 1min | 0 | yes | Sat 2026-11-07 14:15:00 CST | Sat 2026-11-07 14:30:00 CST |
| trade-self-heal.timer | *-*-* *:07,22,37,52:00 | 1min | 0 | yes | Sat 2026-11-07 14:07:00 CST | Sat 2026-11-07 14:22:00 CST |
| trade-turnover-backfill.timer | Mon..Fri *-*-* 21:10:00 | 1min | 0 | yes | Fri 2026-11-06 21:10:00 CST | Mon 2026-11-09 21:10:00 CST |
| trade-update-all.timer | Sun *-*-* 22:30:00<br>Mon..Sat *-*-* 17:50:00 | 1min | 0 | yes | Fri 2026-11-06 17:50:00 CST | Sat 2026-11-07 17:50:00 CST |
| trade-us-stock-morning.timer | *-*-* 05:00:00 | 1min | 0 | yes | Sat 2026-11-07 05:00:00 CST | Sun 2026-11-08 05:00:00 CST |

### 取证修正经历

原probe2/3以`row[k]=v`解析重复属性，仅保留一值；原始systemctl文本当时未存储，旧数据无法离线恢复。发现后先明确标partial并停止漂移推断；用户随后授权必要的第4次只读补采，现已取得完整新文本与列表。旧“部分值”不再作为当前日历集合，失败解析经历保留在inventory coverage.collection_history及私有证据。

9个多表达式timer当前分别为：trade-backfill-evening.timer=3; trade-etf-national-team.timer=2; trade-futures-backfill.timer=2; trade-intraday-snapshot.timer=30; trade-lhb-backfill.timer=2; trade-public-fund-daily.timer=2; trade-public-fund-estimation.timer=4; trade-public-fund-quarterly.timer=3; trade-update-all.timer=2。这些是真实新运行观察，不是用旧专题配置填补；本次仍不独立判定与声明的日历漂移。全部health保持unknown。

## cron可见部分

只读当前身份`crontab -l`、`/etc/crontab`和最多32个`/etc/cron.d`普通文件；完整命令只在内存脱敏，未存储。当前身份两条Node脚本在OTHER_APP，不能默认属于Trade。系统条目的test/cd提示是shell门控，未解析为业务入口。

| 来源 | schedule | 安全入口摘要 |
| --- | --- | --- |
| current-user crontab | 7 * * * * | $OTHER_APP/crontab/run_job.js |
| current-user crontab | 37 * * * * | $OTHER_APP/crontab/run_job.js |
| /etc/crontab | 17 * * * * | unknown; shell/binary hint=cd |
| /etc/crontab | 25 6 * * * | unknown; shell/binary hint=test |
| /etc/crontab | 47 6 * * 7 | unknown; shell/binary hint=test |
| /etc/crontab | 52 6 1 * * | unknown; shell/binary hint=test |
| /etc/cron.d/e2scrub_all | 30 3 * * 0 | unknown; shell/binary hint=test |
| /etc/cron.d/e2scrub_all | 10 3 * * * | unknown; shell/binary hint=test |

`/etc/cron.d/sgagenttask`与`/etc/cron.d/yunjing`为PermissionError；没有提权或尝试其他身份crontab，也未读周期cron目录内容。

## coverage、差异与未覆盖

- 实际命令范围：list-unit-files、list-units --all、list-timers --all仅trade-*.service/timer；show仅白名单Id/LoadState/ActiveState/SubState/UnitFileState/Result/ExecMainStatus/User/WorkingDirectory/FragmentPath/Triggers/TriggeredBy/LastTriggerUSec/NextElapseUSecRealtime、TimersCalendar/Monotonic，以及只输出入口摘要的ExecStart。
- Probe2 show glob仅返回45对象，已在Probe3使用枚举得到的88个显式名字补齐；最终show与unit-file集合完全一致。系统命令无非零返回；文件权限失败保留上述2项。
- 本次未在有限仓内源读取中确认非trade前缀的web/CF应用unit名，未盲枚举它们；不能写成“云上没有web/CF服务”。Cloudflare Workers/Pages/R2/CDN/DNS、云厂商控制面、防火墙、外部可达性均unknown，未访问API。
- 不读.env/凭证/邮件账户/webhook，不采集全机进程argv，不start/reset/reload，不执行或import业务入口，不做DB内容扫描。
- 共4次只读SSH（初始3次及用户授权1次纠正性补采），remote20秒/outer28秒。每probe系统命令输出分别23001、23450、47651B，均低于128KiB；单文件读取上限128KiB、source累计2MiB预算。Probe4仅2条白名单systemctl show命令，额外输出16640B，未取ExecStart/Environment。私有证据留在任务报告目录，不复制连接参数或完整敏感命令。

与其他专题对账应按稳定ID`host:cloud`、`cloud-service:<unit>`、`cloud-timer:<unit>`、`cloud-cron:<source-and-schedule>`连接；依赖尚未追到源码/数据层的只标dependency_candidates，不编造完整业务DAG。
