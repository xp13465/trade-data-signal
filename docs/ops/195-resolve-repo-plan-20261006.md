# #195 方案调研:全仓 57 个 shell 脚本「写死 mac 默认 REPO/GIT_REPO」——共享 resolve_repo 单点守卫 + 分批治理方案

> 日期 2026-10-06(调研 agent,全程只读:未改任何代码/脚本/配置,未跑任何生产脚本/unit,未发任何 R2/邮件/飞书;工作树 main,本报告为唯一新增文件)
> 关联:#194(patrol 单点已修,`a33efb9d2`)/ #191(同族静默)/ #188(s06 同步段盲区)/ #196(failed-unit 消费方,已上线 `351f63817`)/ #160(一致性巡检判据 P0)
> 报告性质:**调研结论 + 实施建议**(正解方向 = 抽共享 `resolve_repo` 单点守卫由各脚本 source;**禁止一次性改 57 个**,须分批,见 §4)

## 0. 结论速览

1. **病灶属实且面广**:全仓 **57 个 .sh** 以 `(REPO|GIT_REPO|TRADE_DIR):-/Users/linhuichen/...` 形式写死 mac 默认值(§1 与 reviewer 的 57 对账通过);**云上 41 个 trade service 全部**带 `Environment=REPO=/home/ubuntu/code/trade-data` + `Environment=GIT_REPO=...` 兜住(41/41,快照证据),**Environment 一丢**:脚本拿 mac 路径 cd/调 python → 失败,且 `$PY=$REPO/.venv/bin/python` 同源 → **notify 也调不动 = 连告警都发不出**(#194/#188 同族「失败恰是最没声音的时候」)。
2. **云上被 ExecStart 直调的 .sh 共 36 个**(云上实测,见 §1.3),其中在本 57 内 = **35 个**(差异 1 = `cloud_unit_patrol.sh`,已由 #194 修复、仍属同族)。
3. **正解确认可行**:抽 `scripts/lib/repo_paths.sh` 一个 `resolve_repo`,解析顺序 = **显式 env > $0 推导(两种布局) > fail-loud**;因云上/mac 的 `<REPO>/scripts` 都是指向 git 仓 scripts/ 的 **symlink**(两侧磁盘实测),$0 推导在云上推出来的值**与 unit env 逐字相同** ⇒ env 丢失时不仅"能报错",而是**直接自愈继续正确跑**;推导也不成立时才 fail-loud(exit 2 + journal + 固定日志),由 **#196 已上线的 failed-unit 巡检**(`check_failed_units.py`,挂 schedule-monitor 15min)兜底把"脚本没跑成"变成真实告警。
4. **分批 = 5 批**(§4):批1 = lib 本体 + 两个「已有现成测试」的巡检锚点(`check_r2_consistency.sh` + `cloud_unit_patrol.sh` 统一实现);批2 = 其余巡检/告警/通知本体 10 个;批3 = 每日发布主链 9 个;批4 = 低频采集/回填 unit 直调 21 个;批5 = 链内被调 + 变体 + 孤儿 16 个。每批边界/为什么/验收点/回归策略见 §4,机检(ratchet)设计见 §4.6。
5. **兼容性铁律**:env 有值 → 原样使用、不做任何改写 ⇒ **已配 env 的云上机器行为零变化**(值不变式,单测断言逐字相等);lib **绝不 notify**(解析失败时 notify 的 PY 同源于坏 REPO,发了也是哑弹——#194 F2 同款);**保持每脚本原有 export 语义**(6 个 export 脚本 + 2 个仓外,见 §3.6,py 侧有 51 处 `os.environ` 消费者,export 面变化=行为变化风险)。
6. **边界**:unit 侧/`.env`/python 侧**都不动**;python 侧同族 ≥51 个文件含 mac 字面量(12 处 env 默认取值),属二阶问题,建议另登记(§7)。

## 1. 数字对账(与 reviewer 的 57/36 逐一对账)

> reviewer 出处:`docs/ops/194-review-agent-aa1efa05fb78e5b8b.md` L54(「全仓 57 个 .sh 同款 `(REPO|GIT_REPO):-/Users/linhuichen`…其中 36 个正被云上 unit 以 ExecStart 调用」)与 #194 报告 L135。

### 1.1 口径对比表(全部可复现,命令见 §6)

| 口径 | 命令要点 | 结果 | 与 reviewer 对账 |
|---|---|---|---|
| **57 清单(本方案操作口径)** | `grep -rlE '(REPO\|GIT_REPO\|TRADE_DIR):-/Users/linhuichen' --include='*.sh'`(排 worktrees) | **57** | ✅ 与 reviewer 的 57 精确吻合 |
| 严格字面(仅 REPO/GIT_REPO) | 同上但去掉 TRADE_DIR | **56** | ⚠️ 差 1 = `run_ab_direction_anchor.sh`(变量名叫 `TRADE_DIR`,同族写法 `TRADE_DIR="${TRADE_DIR:-/Users/linhuichen/code/trade}"`,语义 = git 仓) |
| 全变量族 | `grep -rlE '[A-Za-z_]+:-/Users/linhuichen' --include='*.sh'` | **59** | +2 = `sensenova-rotate-proxy*.sh`(`SENSENOVA_ENV_FILE:-...`,工具类,非云上调用面) |
| 任意出现 mac 字面量 | `grep -rl '/Users/linhuichen' --include='*.sh'` | **66**(scripts/ 内 65 + `docs/ai-predict/scripts/dbbrief_interaction_smoke.sh` 1) | ✅ 与 reviewer「scripts/ 内 65、全仓 66」逐字一致 |
| **云上 ExecStart 直调 .sh 数** | 快照/云上 `ExecStart=` 提取 basename | **36** | ✅ 与 reviewer 的 36 精确吻合(口径=直调 .sh 总数,云上实测) |
| 57 ∩ ExecStart 直调 | 上两者求交 | **35** | 差 1 说明见 1.2 |

### 1.2 差异口径说明(诚实标注,不自造数字)

- **「57」的复现口径**:reviewer 文字写 `(REPO|GIT_REPO):-`,但其数字 57 只有把**同族 1 个 `TRADE_DIR` 变体**(`run_ab_direction_anchor.sh`)算进来才精确复现(严格二变量 = 56)。本报告以 **57** 为操作口径(把 TRADE_DIR 变体算病灶,理由:同样"env 丢了就静默用 mac 路径",且它的 unit 同样靠 `Environment=TRADE_DIR=` 兜住,快照实证),与 reviewer 数字对齐;同时给出 56/59 两个口径供反查。
- **「36」与「∩57=35」的差 1** = `cloud_unit_patrol.sh`:**属 ExecStart 直调(36 之列)但已于 #194 修复**,当前不再是病灶 → 不在 57 内 ⇒ 57∩ExecStart = 35。即:reviewer「其中 36 个」按「ExecStart 直调 .sh 总数」成立;按「∩57」口径为 35,差额已定位到具体文件,非数字矛盾。
- 扫描必须 **排除 `worktrees/`**(隔离工作树里同一批文件会重复计数:带 worktrees 时同命令出 112 命中)。

### 1.3 云上实时独立核对(2026-10-06 只读 ssh 一次,已实测)

```
$ ssh ... 'ls -ld /home/ubuntu/code/trade-data/scripts'
lrwxrwxrwx ... /home/ubuntu/code/trade-data/scripts -> /home/ubuntu/code/trade-data-signal/scripts
$ ssh ... 'ls /etc/systemd/system/trade-*.timer | wc -l; ls /etc/systemd/system/trade-*.service | wc -l'
41	41        # = 82 unit,与仓库快照 41+41 一致
$ ssh ... 'grep -h "^ExecStart=" /etc/systemd/system/trade-*.service | sed -E "s|.*/scripts/||; s| .*||" | sort -u | grep -c "\.sh$"'
36
$ ssh ... 'grep -E "Environment=(REPO|GIT_REPO)=" /etc/systemd/system/trade-r2-consistency.service'
Environment=GIT_REPO=/home/ubuntu/code/trade-data-signal
Environment=REPO=/home/ubuntu/code/trade-data
```

- symlink 布局实测成立(推导前提);41 service 全部带 REPO/GIT_REPO env(快照侧 41/41 同款,见 §6 命令)。
- mac 侧同款布局实测:`/Users/linhuichen/code/trade-data/scripts -> /Users/linhuichen/code/trade/scripts`;三个兄弟目录在两侧都存在(mac:`code/{trade,trade-data,trade-data-signal-staticdata}`;云上:`code/{trade-data,trade-data-signal,trade-data-signal-staticdata}`)——**推导的「兄弟目录」兜底两平台同式**(§3.2)。

## 2. 全量清单(57 个脚本逐个列)

### 2.1 列口径说明

- **硬编码变量**:该文件里以 `VAR:-/Users/linhuichen/...` 写死的变量(一个脚本可多个)。
- **export**:该脚本用 `export (REPO|GIT_REPO)=` 定义(有 = 其 python 子进程/被调子脚本靠 env 可见;迁移时必须保留 export 语义,见 §3.6)。
- **notify 链路**:文件内出现 `notify.py`(30/57)——这些脚本的"告警出口"与 `$PY`(=`$REPO/.venv/bin/python`)同源,REPO 坏 = 告警哑火。
- **云上 unit→定时时点**:云上快照 `ExecStart` 直调(case=unit 直调);空白为 `—` 者 = 非直调,调用面列其仓内调用方(含链内传递调用);「仓内无调用方」= 孤儿/手动/一次性(共 5 个:`build_echarts`/`fix_turnover_partial_20260814`/`stage0_full_manual`/`update_all_serial`/`uptime_check`)。
- **风险**:高 = 巡检/告警/通知本体(失效 = 静默盲区扩张);中 = 生产链脚本(unit 直调,失败有 unit-failed 通道**间接**可见,但自身 notify 哑火);低 = 链内被调/孤儿(失败靠父链 echo,或本就手动)。提醒:30/57 都含 notify,风险高低按「失效后有没有第二通道看见」分,不按"有没有 notify"分。
- **批次**:见 §4(每批边界/为什么/验收)。

### 2.2 主表(57 行,机检生成,命令见 §6.1)

| # | 脚本 | 硬编码变量 | export | notify链路 | 云上 unit→定时时点 | 调用面(其余) | 风险 | 批次 |
|---|---|---|---|---|---|---|---|---|
| 1 | scripts/backfill_indices.sh | REPO | 否 | 否 | — | 被链内调用: backfill_metrics.sh | 低 | 批5 |
| 2 | scripts/backfill_metrics.sh | REPO | 否 | 是 | trade-backfill-evening.service→*-*-* 16:35:00; *-*-* 21:00:00; *-*-* 02:00:00 | 云上 unit 直调 | 中 | 批4 |
| 3 | scripts/backup_db.sh | REPO+GIT_REPO | 否 | 是 | trade-backup-db.service→*-*-* 21:00:00 | 云上 unit 直调 | 中 | 批3 |
| 4 | scripts/brief_push_wrapper.sh | REPO | 否 | 是 | trade-brief-push.service→*-*-* 20:45:00 | 云上 unit 直调 | 中 | 批3 |
| 5 | scripts/build_echarts.sh | REPO | 否 | 否 | — | 仓内无调用方(孤儿/手动/一次性) | 低 | 批5 |
| 6 | scripts/check_data_gap_alerts.sh | REPO | 是 | 是 | trade-check-data-gap.service→Mon..Fri *-*-* 22:35:00 | 云上 unit 直调 | 高 | 批2 |
| 7 | scripts/check_r2_consistency.sh | REPO+GIT_REPO | 是 | 是 | trade-r2-consistency.service→*-*-* 23:20:00 | 云上 unit 直调 | 高 | 批1 |
| 8 | scripts/check_signals.sh | REPO | 否 | 否 | — | 被链内调用: intraday_snapshot.sh, update_all.sh, update_all_serial.sh | 低 | 批5 |
| 9 | scripts/collect.sh | REPO | 否 | 否 | — | 被链内调用: update_all_serial.sh | 低 | 批5 |
| 10 | scripts/deploy.sh | REPO+GIT_REPO | 否 | 是 | — | 被链内调用: backfill_metrics.sh, etf_national_team_backfill.sh, futures_backfill.sh, intraday_snapshot.sh, lhb_backfill.sh, main-merge.sh, overfit_monitor.sh, pipeline.sh, public_fund_daily.sh, public_fund_full.sh, public_fund_quarterly.sh, push_schedule_stats.sh, r2_upload_async.sh, r2_upload_skip_notify.sh, rzhb_backfill.sh, s06_snapshot.sh, schedule_monitor.sh, staticdata_backup_async.sh, staticdata_sync.sh, sync_dev_from_r2.sh, update_all.sh, update_all_serial.sh, update_lab.sh, us_stock_morning.sh | 中 | 批3 |
| 11 | scripts/etf_national_team_backfill.sh | REPO+GIT_REPO | 否 | 否 | trade-etf-national-team.service→*-*-* 20:07:00; *-*-* 21:30:00 | 云上 unit 直调 | 中 | 批4 |
| 12 | scripts/fapi_daily_syn.sh | REPO | 否 | 否 | trade-fapi-daily.service→*-*-* 18:10:00 | 云上 unit 直调 | 中 | 批4 |
| 13 | scripts/fix_turnover_partial_20260814.sh | REPO | 否 | 否 | — | 仓内无调用方(孤儿/手动/一次性) | 低 | 批5 |
| 14 | scripts/fund_nav_upload_async.sh | REPO+GIT_REPO | 否 | 是 | — | 被链内调用: r2_upload_async.sh, update_all.sh | 低 | 批5 |
| 15 | scripts/futures_backfill.sh | REPO | 否 | 否 | trade-futures-backfill.service→*-*-* 20:05:00; *-*-* 21:00:00 | 云上 unit 直调 | 中 | 批4 |
| 16 | scripts/gold_night.sh | REPO+GIT_REPO | 否 | 是 | trade-gold-night.service→*-*-* 02:40:00 | 云上 unit 直调 | 中 | 批4 |
| 17 | scripts/intraday_snapshot.sh | REPO+GIT_REPO | 否 | 是 | trade-intraday-snapshot.service→*-*-* 09:25:00; *-*-* 09:35:00; *-*-* 09:45:00; *-*-* 09:55:00; *-*-* 10:05:00; *-*-* 10:15:00; *-*-* 10:25:00; *-*-* 10:35:00; *-*-* 10:45:00; *-*-* 10:55:00; *-*-* 11:05:00; *-*-* 11:15:00; *-*-* 11:25:00; *-*-* 11:32:00; *-*-* 13:01:00; *-*-* 13:05:00; *-*-* 13:15:00; *-*-* 13:25:00; *-*-* 13:35:00; *-*-* 13:45:00; *-*-* 13:55:00; *-*-* 14:05:00; *-*-* 14:15:00; *-*-* 14:25:00; *-*-* 14:35:00; *-*-* 14:45:00; *-*-* 14:55:00; *-*-* 15:02:00; *-*-* 15:35:00; *-*-* 20:35:00 | 云上 unit 直调 | 中 | 批3 |
| 18 | scripts/kelly_intraday_rerun.sh | REPO+GIT_REPO | 否 | 是 | trade-kelly-intraday-rerun.service→*-*-* 09:40:00 | 云上 unit 直调 | 中 | 批3 |
| 19 | scripts/lhb_backfill.sh | REPO | 否 | 否 | trade-lhb-backfill.service→*-*-* 18:30:00; *-*-* 19:30:00 | 云上 unit 直调 | 中 | 批4 |
| 20 | scripts/migrate_large_json_out_of_git.sh | REPO+GIT_REPO+STATICDATA_REPO | 否 | 否 | — | 被链内调用: staticdata_backup_async.sh, staticdata_sync.sh | 低 | 批5 |
| 21 | scripts/monitor_72h.sh | REPO | 否 | 是 | — | 被链内调用: schedule_monitor.sh | 高 | 批2 |
| 22 | scripts/nextday_gap_check.sh | REPO+GIT_REPO | 是 | 是 | trade-nextday-gap-check.service→Mon..Fri *-*-* 09:26:00 | 云上 unit 直调 | 高 | 批2 |
| 23 | scripts/nextday_plan.sh | REPO+GIT_REPO | 是 | 是 | trade-nextday-plan.service→Mon..Fri *-*-* 22:30:00 | 云上 unit 直调 | 中 | 批3 |
| 24 | scripts/on_skip_notify.sh | REPO | 否 | 是 | — | 被链内调用: backup_db.sh, r2_upload_skip_notify.sh, turnover_backfill_skip_notify.sh, update_all.sh, update_lab.sh | 高 | 批2 |
| 25 | scripts/overfit_monitor.sh | REPO+GIT_REPO | 否 | 是 | trade-overfit-monitor.service→Mon..Fri *-*-* 21:40:00 | 云上 unit 直调 | 高 | 批2 |
| 26 | scripts/pf_score_daily.sh | REPO+GIT_REPO | 否 | 否 | trade-pf-score-daily.service→*-*-* 16:00:00 | 云上 unit 直调 | 中 | 批4 |
| 27 | scripts/pf_score_weekly.sh | REPO+GIT_REPO | 否 | 否 | trade-pf-score-weekly.service→Sun *-*-* 03:17:00 | 云上 unit 直调 | 中 | 批4 |
| 28 | scripts/pipeline.sh | REPO | 否 | 否 | — | 被链内调用: futures_backfill.sh, turnover_backfill.sh, update_all.sh | 低 | 批5 |
| 29 | scripts/public_fund_daily.sh | REPO | 否 | 否 | trade-public-fund-daily.service→*-*-* 16:30:00; *-*-* 17:00:00 | 云上 unit 直调 | 中 | 批4 |
| 30 | scripts/public_fund_estimation.sh | REPO | 否 | 否 | trade-public-fund-estimation.service→*-*-* 10:00:00; *-*-* 11:00:00; *-*-* 13:30:00; *-*-* 14:30:00 | 云上 unit 直调 | 中 | 批4 |
| 31 | scripts/public_fund_full.sh | REPO | 否 | 否 | trade-public-fund-full.service→*-*-* 22:00:00 | 云上 unit 直调 | 中 | 批4 |
| 32 | scripts/public_fund_quarterly.sh | REPO | 否 | 否 | trade-public-fund-quarterly.service→*-*-* 03:00:00; *-*-* 04:00:00; *-*-* 07:00:00 | 云上 unit 直调 | 中 | 批4 |
| 33 | scripts/push_schedule_stats.sh | REPO+GIT_REPO | 否 | 是 | — | 被链内调用: deploy.sh, etf_national_team_backfill.sh, futures_backfill.sh, gold_night.sh, lhb_backfill.sh, overfit_monitor.sh, public_fund_daily.sh, public_fund_full.sh, public_fund_quarterly.sh, rzhb_backfill.sh, update_all.sh, update_lab.sh, us_stock_morning.sh | 低 | 批5 |
| 34 | scripts/r2_upload_async.sh | REPO+GIT_REPO | 否 | 是 | — | 被链内调用: check_r2_consistency.sh, deploy.sh | 低 | 批5 |
| 35 | scripts/r2_upload_skip_notify.sh | REPO | 否 | 是 | — | 被链内调用: deploy.sh, r2_upload_async.sh | 高 | 批2 |
| 36 | scripts/run_ab_direction_anchor.sh | TRADE_DIR | 否 | 否 | trade-ab-direction-anchor.service→*-*-* 21:15:00 | 云上 unit 直调 | 中 | 批4 |
| 37 | scripts/run_daily_brief.sh | REPO+GIT_REPO | 否 | 是 | trade-daily-brief.service→*-*-* 20:40:00 | 云上 unit 直调 | 中 | 批3 |
| 38 | scripts/rzhb_backfill.sh | REPO | 否 | 否 | trade-rzhb-backfill.service→*-*-* 08:00:00; *-*-* 19:15:00 | 云上 unit 直调 | 中 | 批4 |
| 39 | scripts/s06_snapshot.sh | REPO+GIT_REPO | 是 | 是 | trade-s06-snapshot.service→Mon..Fri *-*-* 20:35:00 | 云上 unit 直调 | 中 | 批3 |
| 40 | scripts/schedule_monitor.sh | REPO | 否 | 是 | trade-schedule-monitor.service→*-*-* *:00,15,30,45:00 | 云上 unit 直调 | 高 | 批2 |
| 41 | scripts/self_heal.sh | REPO+GIT_REPO | 否 | 是 | trade-self-heal.service→*-*-* *:07,22,37,52:00 | 云上 unit 直调 | 高 | 批2 |
| 42 | scripts/stage0_full_manual.sh | REPO | 否 | 否 | — | 仓内无调用方(孤儿/手动/一次性) | 低 | 批5 |
| 43 | scripts/stage0_manager.sh | REPO | 否 | 否 | trade-pf-stage0-manager.service→*-*-01 02:47:00 | 云上 unit 直调 | 中 | 批4 |
| 44 | scripts/stage0_nav.sh | REPO | 否 | 否 | trade-pf-stage0-nav.service→Fri *-*-* 01:43:00 | 云上 unit 直调 | 中 | 批4 |
| 45 | scripts/stage0_overview.sh | REPO | 否 | 否 | trade-pf-stage0-overview.service→Sun *-*-* 02:17:00 | 云上 unit 直调 | 中 | 批4 |
| 46 | scripts/stage0_risk.sh | REPO | 否 | 否 | trade-pf-stage0-risk.service→*-*-15 02:33:00 | 云上 unit 直调 | 中 | 批4 |
| 47 | scripts/staticdata_backup_async.sh | REPO+GIT_REPO+STATICDATA_REPO | 否 | 是 | — | 被链内调用: deploy.sh, migrate_large_json_out_of_git.sh, staticdata_sync.sh | 低 | 批5 |
| 48 | scripts/staticdata_sync.sh | REPO+GIT_REPO+STATICDATA_REPO | 否 | 是 | — | 被链内调用: intraday_snapshot.sh, staticdata_backup_async.sh | 低 | 批5 |
| 49 | scripts/sync_fund_score_to_d1.sh | REPO | 否 | 否 | — | 被链内调用: pf_score_daily.sh, pf_score_weekly.sh | 低 | 批5 |
| 50 | scripts/turnover_backfill.sh | REPO+GIT_REPO | 是 | 是 | trade-turnover-backfill.service→Mon..Fri *-*-* 21:10:00 | 云上 unit 直调 | 中 | 批4 |
| 51 | scripts/turnover_backfill_skip_notify.sh | REPO | 否 | 是 | — | 被链内调用: turnover_backfill.sh | 高 | 批2 |
| 52 | scripts/update_all.sh | REPO+GIT_REPO | 否 | 是 | trade-update-all.service→Mon..Sat 17:50:00; Sun 22:30:00 | 云上 unit 直调 | 中 | 批3 |
| 53 | scripts/update_all_serial.sh | REPO | 否 | 否 | — | 仓内无调用方(孤儿/手动/一次性) | 低 | 批5 |
| 54 | scripts/update_lab.sh | REPO+GIT_REPO | 否 | 是 | trade-lab-auto.service→*-*-* 19:00:00 | 云上 unit 直调 | 中 | 批4 |
| 55 | scripts/uptime_check.sh | REPO | 否 | 是 | — | 仓内无调用方(孤儿/手动/一次性) | 高 | 批2 |
| 56 | scripts/us_stock_morning.sh | REPO+GIT_REPO | 否 | 否 | trade-us-stock-morning.service→*-*-* 05:00:00 | 云上 unit 直调 | 中 | 批4 |
| 57 | scripts/verify_backup.sh | REPO | 否 | 是 | — | 被链内调用: backup_db.sh | 低 | 批5 |

**数字自查**:表中 57 行;「云上 unit 直调」35 行(§1.1);notify 是 = 30 行;export 是 = 6 行(check_data_gap_alerts / check_r2_consistency / nextday_gap_check / nextday_plan / s06_snapshot / turnover_backfill);孤儿 5 行。

### 2.3 57 之外的同族(边界声明,防"清单只列 57 就下结论")

除 57 外,仓内还有 8 个 `scripts/*.sh`(共 9 个文件含 mac 字面量,含 docs 下 1 个)含 mac 路径,均**不在** reviewer 57 口径内,列此备查:

| 文件 | 形态 | 是否云上调用 | 处置建议 |
|---|---|---|---|
| scripts/cloud_unit_patrol.sh | 仅注释提及(第 36 行,病灶说明);**已由 #194 修复**($0 推导 + fail-fast) | 是(08:27) | 批1 统一到共享 lib(去重,非新修) |
| scripts/sync_dev_from_r2.sh:28-29,166-167 | **硬编码无 env 兜底**(`TRADE=/Users/...; REPO=/Users/...` + py heredoc setdefault) | 否 | 批5 可选(变体 B:比 `:-` 更硬) |
| scripts/backup_claude_self.sh:14 | `TRADE_DIR="/Users/linhuichen/code/trade"` 硬编码无 env | 否 | 批5 可选 |
| scripts/restore-large-json.sh:89,165 | python heredoc 内 mac 默认(`DEFAULT_PRODUCTION_REPO`/`STATICDATA_REPO` get 默认) | 否 | 批5 可选 |
| scripts/sensenova-rotate-proxy.sh / -kimi.sh:10,20-21 | `SENSENOVA_ENV_FILE:-/Users/...` + exec 绝对路径 | 否(mac 运维工具) | 批5 可选(低) |
| scripts/thinking-proxy-rollback.sh:64 | `PLIST=/Users/...`(launchd 遗留) | 否 | 不动(非本族语义) |
| scripts/install-agent-inbox-watcher-launchd.sh:21 | 仅 echo 文案 | 否 | 不动(纯文案,可选) |
| docs/ai-predict/scripts/dbbrief_interaction_smoke.sh:6 | 仅注释示例 | 否 | 不动 |

**二阶同族(不在本任务,建议另登记)**:`scripts/*.py` 内 **51 个文件**含 `/Users/linhuichen` 字面量,其中 ≥12 处以 `os.environ.get("REPO", "/Users/...")` 形式自带 mac 默认(如 `check_data_gap_alerts.py:125`、`nextday_gap_check.py:45-47`、`nextday_plan_generator.py:71-73`、`notify.py:2210/2249/2295`、`gen_daily_brief.py:61`、`check_failed_units.py:87`、`check_s06_state.py:52-53` 等)。shell 侧 lib 只解决 sh;py 侧的同类默认建议登记为独立任务(理据:py 侧多数在 unit env 下拿到正确值,风险面与 sh 不同,须单独盘点)。

## 3. 共享 resolve_repo 设计

### 3.1 放置位置与命名

- 位置:`scripts/lib/repo_paths.sh`(新建 `scripts/lib/`;理由:57 脚本全在 `scripts/` 下、`BASH_SOURCE` 相对路径一跳可达;`scripts/` 已是全仓脚本唯一入口区,不引入新顶层目录)。
- 提供函数:
  - `resolve_repo <调用者脚本的 BASH_SOURCE[0]>` — 主函数,解析并**赋值**(非 export,见 3.5)REPO / GIT_REPO。
  - `resolve_staticdata_repo` — 可选第二函数,推导姐妹目录 `trade-data-signal-staticdata`(mac `/Users/linhuichen/code/trade-data-staticdata`、云上 `/home/ubuntu/code/trade-data-signal-staticdata`;两平台均已存在),给 3 个含 STATICDATA_REPO 的脚本(migrate_large_json_out_of_git / staticdata_backup_async / staticdata_sync,均在批5,可选)。
  - 内部 `_resolve_repo_fatal <msg>` — fail-loud 出口(3.4)。

### 3.2 解析顺序(单一定义,env 优先零改写)

1. **显式 env 优先**:`REPO` / `GIT_REPO` 若已设置且**非空**,原样保留、**一个字节都不改写**(哪怕值可疑也不动——保证已配 `Environment=` 的 41 个 unit 行为完全不变;值合法性校验仍做,但只 warn 不 exit,见 3.3 的 §F 例外)。
2. **仓库根自动推导**(env 缺失/为空时),用调用者传入的脚本路径做两类布局推导(与 #194 patrol 同逻辑):
   - 取 `raw_dir=$(cd -- "$(dirname -- "$caller")" && pwd)`(逻辑路径)与 `real_dir=$(cd -- "$(dirname -- "$caller")" && pwd -P)`(物理路径)。
   - **case A(经 `<REPO>/scripts` symlink 调用,raw_dir ≠ real_dir)**:`REPO=dirname(raw_dir)`、`GIT_REPO=dirname(real_dir)`。
     - 实测两平台都成立:mac `<trade-data>/scripts -> <trade>/scripts`;云上 `<trade-data-signal>/scripts -> <trade-data>/scripts`。
   - **case B(仓内直跑,raw_dir == real_dir)**:`GIT_REPO=dirname(real_dir)`、`REPO=$(case B 的姐妹规则)`——即 `dirname(GIT_REPO)` 下的 `trade-data` 目录;**若不存在则回退 `GIT_REPO` 本身**(防有人 clone 成 trade-data 目录名直跑)。
3. **校验**(推导出值之后):`-d "$REPO"`、`-x "$REPO/.venv/bin/python"`、`-d "$GIT_REPO"` 三者全过才放行;任何一项不过 → fail-loud(3.4)。

**为何 env 优先于推导**:已配 env 的 41 unit 是当前生产基线;env 可能指向与推导不同的合法布局(如未来目录搬迁),推导只在 env 缺失(即"病灶暴露")时接管 = 只把"静默坏"变成"自愈或响铃",不改变任何已工作路径。

### 3.3 校验与告警分级

| 检查项 | env 提供值 | 推导值 |
|---|---|---|
| `-d REPO` | warn(不 exit) | FATAL(exit) |
| `-x REPO/.venv/bin/python` | warn(不 exit) | FATAL(exit) |
| `-d GIT_REPO` | warn(不 exit) | FATAL(exit) |
| `REPO` 值为 mac 风格而当前是云机(或反之)——不可靠推断,**不做** | — | — |

- 推导值失败 = FATAL:此刻脚本无论继续与否都必然坏(cd 失败/`$PY` 不存在),fail-loud 是唯一诚实选项。
- env 提供值失败 = warn 到 stderr(带 `resolve_repo:` 前缀)+ 继续:env 是显式指令,可能指向 NFS/延迟挂载等边界形态,lib 不越权判定其非法;同时不阻断 #196 通道之外的老行为。
- 校验输出恒定格式:`resolve_repo: REPO=<val> (source=env|derived)` 一行 info 到 stderr(便于 journalctl 反查,量小)。

### 3.4 失败语义:fail-loud 及出口

- 出口:`exit 2` + stderr `FATAL resolve_repo: ...` + 追加一行到 `${TMPDIR:-/tmp}/resolve_repo_fatal.$(id -un).log`(固定落点,防调用者 `2>/dev/null` 吞掉线索)。
- **绝不 notify**(lib 自身绝不发任何告警/邮件/飞书;理由:①notify 依赖 `$PY`=`$REPO/.venv/bin/python`,此刻 REPO 正不可信 → 发信链路自身就哑;②#194 教训:守卫自己发告警 = 在故障时制造第二故障面;③#196 `check_failed_units.py` 已提供"unit 进 failed → 由 env 完好的外部 unit 告警"的统一兜底通道,L15min 扫描,patrol 定向抑制白名单外一律报)。**fail-loud 的有效性建立在 #196 已上线这一事实上**(2026-10-05 #196 上线,证据:docs/ops/196-*.md + trade-schedule-monitor.timer);lib 不重复造通道。
- 为何不是 fail-open:fail-open = 恢复"cd 失败后继续跑"的静默错误 = 本任务要治的病本身;且 fail-open 下 57 脚本的坏法各不相同(有的 `cd || exit`、有的继续),一致性反而更差。
- 逃生阀:`RESOLVE_REPO_NO_EXIT=1` 时 FATAL 只 warn 不 exit(供单测/本机调试;生产 unit 不设此变量)。
- **与 `set -e` 交互**:lib 内部不做 `exit` 之外的流程控制;**调用方若在管道/set -e 环境 source,exit 2 语义仍成立**(exit 穿透管道子 shell 的问题由「source 在顶层」保证,lib 只支持顶层 source,文档写明)。

### 3.5 调用接口(source 机制):两行模板

```bash
#!/usr/bin/env bash
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/repo_paths.sh"
resolve_repo "${BASH_SOURCE[0]}"
# 原脚本若为 export REPO=/backup …行:保留 export 语义 —— 见 3.6
```

- 选「每脚本两行」而非「统一 wrapper 进程」:
  - wrapper(`exec bash -c 'source lib; exec $1'` 类)会让所有脚本 ParentProcessId/日志归属变更,且 copy-paste 给运维 ssh 手跑场景也变两层,排障成本上升;
  - 两行模板的 diff 面极小(只动 header 2~3 行,§4.6 可机检断言),与 #194 patrol 已修形态一致(patrol 已内联同逻辑,批1 改为 source lib 时 diff 也仅这几行);
  - 缺点(57 处重复两行)由机检 ratchet 消除:§4.6 断言每文件**有且仅有一行** `resolve_repo` 调用 + 有且仅有一行 lib source。
- source 路径用 `$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)` 绝对化:即使脚本以相对路径被调、cwd 任意,也能定位 lib(与 lib 内部对 caller 的取法同构,单向自洽)。

### 3.6 与既有 export 及 python 子进程的兼容(硬约束)

- **lib 只 assign,不 export**(`REPO=` 而非 `export REPO=`)。
- 6 个原 export 脚本(check_data_gap_alerts / check_r2_consistency / nextday_gap_check / nextday_plan / s06_snapshot / turnover_backfill):**保留原 `export REPO GIT_REPO` 行**(放在 resolve 之后;若原脚本是 `REPO=…; export REPO`,迁移后改为 `resolve_repo …; export REPO GIT_REPO`)。这样 python 子进程可见性与迁移前**逐字节一致**。
- 依据(为什么敢定 assign-only):python 侧 ≥12 处以 `os.environ.get("REPO", <mac默认>)` 读 REPO(notify.py:2210/2249/2295、check_failed_units.py:87、nextday_gap_check.py:45-47 等),`export` 与否直接影响这些子进程行为;**若 lib 擅自把 51 个非 export 脚本变成 export**,python 侧 `os.environ.get` 的取值优先级将整体改变(从"脚本内显式传参/默认"变成"env 全覆盖")——这属于静默行为变更,必须避免。保持原 export 集合 = 迁移对 python 侧零可见变化。
- 新增函数一律内部 `local`,不污染调用者命名空间;lib 只定义 `resolve_repo`/`resolve_staticdata_repo`/`_resolve_repo_fatal` 三个符号(机检可断言无其他全局定义)。

### 3.7 单测桩(设计内建,供批1 交付)

- `scripts/tests/test_resolve_repo.sh`(bash 单测,不依赖 pytest):
  - T1 env 优先:设 `REPO=X GIT_REPO=Y` → 值不变(逐字节 diff)。
  - T2 case A 推导:在 `mktemp -d` 里搭 `repo/scripts(真) + repo-data/scripts -> repo/scripts` 布局,source lib 用 symlink 路径调用 → REPO=repo-data、GIT_REPO=repo。
  - T3 case B 推导:仓内直跑 → GIT_REPO=仓、REPO=姐妹 trade-data。
  - T4 校验失败 fail-loud:推导出但 `.venv/bin/python` 缺失 → `RESOLVE_REPO_NO_EXIT` 不设时 rc=2,且 fatal 日志落 `TMPDIR`;设时 rc=0 且仅 warn。
  - T5 空值 env(`REPO=""`)视同缺失走推导(与 `${VAR:-}` 语义一致,防 env 里留空串)。
  - T6 无副作用:source 后调用者仅新增 REPO/GIT_REPO 两个变量(其余变量集合逐名 diff 不变);再对 6 个 export 脚本形态模拟「resolve + export」断言子 shell 可见性不变。

## 4. 分批方案(57 = 1 + 10 + 9 + 21 + 16,逐批断言见 §6.4)

### 4.0 切批原则(为什么不是按字母/目录切)

1. **先立 lib + 单点闭环**(批1):lib 每次改动代价最大(57 脚本共享),必须用**最小可验证面**先立住——1 个脚本 + lib 本体 + patrol 回迁统一,跑通「推导正确性单测 + 云上真实 unit 回归」全链,再放量。
2. **按"失效可见度"从低到高**:高组(失效 = 告警/巡检自身哑火,无言 = 盲区扩张)优先;中组(unit 直调,有 failed 通道)次之;低组(链内被调,失败有父链日志)最后。
3. **每批可独立上线/独立回滚**:批之间零依赖(除批1 立 lib),任一批出问题 `git revert` 只回该批 diff。
4. **云上时点保护**:每批合并/部署避开盘后任务时点(§14);批3 含 intraday_snapshot(盘中 30 档),**批3 的云上回归必须选非交易时段**。

### 4.1 批1 — 立 lib + check_r2_consistency + patrol 统一(1 脚本 + lib + patrol 去重)

- **内容**:新建 `scripts/lib/repo_paths.sh`(§3)+ `scripts/tests/test_resolve_repo.sh`(§3.7)+ 迁移 `scripts/check_r2_consistency.sh` 到两行模板 + 把 `scripts/cloud_unit_patrol.sh` 的内联推导块改回 source lib(去重,行为不变)。
- **为什么第一个是它**:①它是 57 中**最高风险款**(23:20 每日跑、R2 一致性巡检本体、自带 notify、另有 4 个 R2 兄弟巡检脚本同构);②有现成测试资产:`scripts/tests/test_160_r2_consistency_followup_20261005.py`、`cloud_unit_patrol_selftest.sh`(T4 已覆盖 symlink 推导)、`test_196_patrol_visibility_20261005.py`;③迁错时当晚 23:20 unit 即响(#196 通道),反馈窗口 ≤24h。
- **边界**:只动这 3 个文件 + 新增 2 个文件;**不碰 unit / 不碰 .env / 不碰 python**。
- **验收点(全绿才收)**:
  1. `bash scripts/tests/test_resolve_repo.sh` rc=0(§3.7 六测);
  2. `bash -n` 三个 shell 全过;`bash scripts/cloud_unit_patrol_selftest.sh` 8/8 全过(T4 由「内联推导」改判「lib 推导」,断言不变);
  3. `python3 -m pytest scripts/tests/test_160_r2_consistency_followup_20261005.py scripts/tests/test_196_patrol_visibility_20261005.py -q` 全过;
  4. 本机 fail-loud 验证走**单测 T4**(临时布局推导、无 .venv → rc=2、无 notify,§3.7);**不要**用「REPO=坏路径 跑 check_r2_consistency」当 fail-loud 断言——按 §3.3,env 提供值非法只 warn 不 exit,那条路不是本设计的 fail-loud 通路(判读原则见 §6.5);
  5. 云上只读回归(非 23:20 时点)见 §6.5:env 版 rc=0、`unset REPO GIT_REPO` 版**推导出与 env 逐字节相同的值**(打印 `resolve_repo: REPO=... (source=derived)` 佐证);
  6. 云上测后若人为制造过 failed:`systemctl reset-failed <unit>` 复原(§6.5)。
- **回归策略**:上线后 24h 内盯 `trade-r2-consistency` 当晚 23:20 正常日志 + `trade-schedule-monitor` 无新 failed;异常即 `git revert` 批1(单批单 revert)。

### 4.2 批2 — 巡检/告警本体 10 个(高组)

- **内容**:check_data_gap_alerts / monitor_72h / nextday_gap_check / on_skip_notify / overfit_monitor / r2_upload_skip_notify / schedule_monitor / self_heal / turnover_backfill_skip_notify / uptime_check。
- **为什么这批第二**:全是"失效时自身就是盲区"款(schedule_monitor 每 15min 是全局巡检中枢、self_heal :07/:22/:37/:52、三个 skip_notify 是上游"跳过通知"的唯一出口、uptime_check 是可用性告警)。本组 6/10 含 notify、3 个 export(check_data_gap_alerts / nextday_gap_check;turnover_backfill_skip_notify 非 export)。
- **边界**:10 文件,均只动 header 两行(export 类保留 export 行);不动其被调 python。
- **验收点**:
  1. 静态断言(§6.4):10/10 文件「有且仅 1 行 lib source + 有且仅 1 行 resolve_repo 调用 + 无 mac 默认残留」;
  2. `bash -n` 10/10;
  3. 本机 resolve-only probe(source lib + resolve_repo + echo,零业务)抽样 3 个脚本,断言推导值 == 期望;fail-loud 通路已由 T4 覆盖,不在业务脚本上制造坏 REPO;
  4. 云上只读抽样(取 schedule_monitor + self_heal + 一个 skip_notify,§6.5 同法:env 版 rc=0、unset 版推导值==env 值);
  5. 上线后 24h:`trade-schedule-monitor` failed 集合无新增(平时为空,空==PASS)。
- **回归策略**:这批多为每 15min 跑,反馈快;一旦 failed 新增,优先 revert 本批。

### 4.3 批3 — 生产主链 9 个(中组,含最高频 intraday)

- **内容**:backup_db / brief_push_wrapper / deploy / intraday_snapshot / kelly_intraday_rerun / nextday_plan / run_daily_brief / s06_snapshot / update_all。
- **为什么单列一批**:全部是"写生产数据/推 main/对外可见"的链主干(update_all Mon..Sat 17:50、intraday_snapshot 盘中 30 档、deploy 全站产物流水线)。迁错的爆炸半径远大于批2,故与批2 分开、单独收紧验收。
- **边界**:9 文件 header 两行;export 类 3 个(s06_snapshot / nextday_plan;另 check 类不含)保留 export。
  - ⚠️ **2026-10-06 订正(批3 实施 + 独立审实测)**:本节 export 计数**与代码现状不符** —— 实测带 `export REPO/GIT_REPO` 的是 **7 个**(backup_db / deploy / intraday_snapshot / kelly_intraday_rerun / nextday_plan / s06_snapshot / update_all)。**批2 §4.2 的「3 个 export」同样不符(实测 2 个)**。⇒ **§2.2 主表「export」列不可作为派单依据**;**后续批次(4/5)一律以「读代码现状」为准**(逐文件 `grep -nE '^\s*export (REPO|GIT_REPO|TRADE_DIR)'` 定基线,迁移后 before/after 逐文件相等)。
- **验收点**:
  1. 静态断言 + `bash -n` 同批2;
  2. **云上回归窗口选非交易时段**(避免 09:25-15:35 盘中档):env 版手跑 `intraday_snapshot.sh` 之一档 rc=0;unset 版推导一致;
  3. merge 时点避开 15:35/16:00/17:50/20:35/22:00 盘后时点与盘中(§14;merge 由主控统一入口执行);
  4. **叠加 §24 前端部署链检查**:deploy.sh 属敏感链,回归须含「版本串/哈希校验 PASS」沿用既有 deploy 自验,不新增口径。
- **回归策略**:上线后逐个链路盯一个自然周期(update_all 一个交易日、intraday 一个交易日、backup_db 一晚);任何链路异常 revert 本批并重查 python 侧可见性(export 三处)。

### 4.4 批4 — 其余 unit 直调单点任务 21 个(中组)

- **内容**:backfill_metrics / etf_national_team_backfill / fapi_daily_syn / futures_backfill / gold_night / lhb_backfill / pf_score_daily / pf_score_weekly / public_fund_daily / public_fund_estimation / public_fund_full / public_fund_quarterly / run_ab_direction_anchor / rzhb_backfill / stage0_manager / stage0_nav / stage0_overview / stage0_risk / turnover_backfill / update_lab / us_stock_morning。
- **为什么**:21 个同形态(unit 直调、失败有 failed 通道、多数无 notify),可批量机械迁移;`run_ab_direction_anchor` 是唯一 `TRADE_DIR` 变体,须注意变量名对齐(脚本内后续用法若为 `$TRADE_DIR`,迁移时把 `resolve_repo` 结果映射回 `TRADE_DIR` 或改脚本内引用,二选一并写进该文件 diff 说明)。
- **边界**:21 文件 header;turnover_backfill 为 export 类保留 export。
- **验收点**:静态断言 21/21 + `bash -n` 21/21 + 云上只读抽样 3 个(时间散点跨日:如 fapi_daily + pf_score_daily + gold_night)+ 上线后 48h 无新增 failed。
- **回归策略**:批量 commit 但按文件粒度写 message(脚本名列表),出问题可按文件名 revert。

> ⚠️ **2026-10-06 订正(批4 实施 + 独立审实测,第三次同款)**:本节「export 类 = 1(turnover_backfill)」**与代码现状不符** —— 实测本批带 export 的是 **6 个**(`etf_national_team_backfill` / `gold_night` / `pf_score_daily` / `pf_score_weekly` / `turnover_backfill` / `update_lab`),独立审用自建解析器复算同值;§2.2 主表另有 5 处误标「否」。⇒ **「export / 边界」列一律不可作派单依据,后续一律以「读代码现状」为准**(批2「3 个」实测 2 个、批3「3 个」实测 7 个、本批「1 个」实测 6 个)。

### 4.5 批5 — 链内被调 / 孤儿 16 个(低组,收尾)

- **内容**:backfill_indices / build_echarts / check_signals / collect / fix_turnover_partial_20260814 / fund_nav_upload_async / migrate_large_json_out_of_git / pipeline / push_schedule_stats / r2_upload_async / stage0_full_manual / staticdata_backup_async / staticdata_sync / sync_fund_score_to_d1 / update_all_serial / verify_backup。
- **为什么最后**:失败时有父链日志(update_all/deploy/r2_upload 链),自身多无 notify;孤儿 5 个中 4 个在此,**优先级最低但必须收**——不修则"链内传递"仍是 env 依赖翻版(父脚本迁移后子脚本若自算 REPO 仍是 mac 默认,反而暴露跨脚本 hash 不一致风险,见 §5.9)。
- **边界**:16 文件 header;migrate_large_json_out_of_git / staticdata_backup_async / staticdata_sync 三个含 STATICDATA_REPO,若采纳 `resolve_staticdata_repo` 则在这三个文件落地(或维持原样仅 REPO/GIT_REPO 迁移,STATICDATA_REPO 留待独立小批,记入 §7 待拍板)。
  - **2026-10-06 主控决定(随批5 落地,附实测依据)**:lib 里**只有** `resolve_repo` / `_resolve_repo_fatal` —— **`resolve_staticdata_repo` 从未实现**(§3.6 的提法不成立),故不新增 lib 函数;三个文件把 `STATICDATA_REPO` 的 **mac 字面量默认值**改为从 `$GIT_REPO` 推导:`STATICDATA_REPO="${STATICDATA_REPO:-$(dirname "$GIT_REPO")/trade-data-signal-staticdata}"`。**实测两机取值不变**:mac `GIT_REPO=/Users/linhuichen/code/trade` ⇒ `dirname`=`/Users/linhuichen/code` ⇒ `/Users/linhuichen/code/trade-data-signal-staticdata`(实测 `ls -d` 存在);云上 `GIT_REPO=/home/ubuntu/code/trade-data-signal` ⇒ `/home/ubuntu/code/trade-data-signal-staticdata`(实测存在)。**已排除的错解**:写成 `${GIT_REPO}-staticdata` —— mac 上 GIT_REPO 尾名是 `trade`(不是 `trade-data-signal`),会推出不存在的 `trade-staticdata`。实施须两机逐字节验证,**证不出就停手上报**;另需保 `staticdata_sync.sh` L36-37 既有 `${GIT_REPO}-staticdata` 兜底分支语义不被破坏。ratchet `PATTERN` 含 `STATICDATA_REPO` 且 R3 要求 MIGRATED 文件零残留 mac 字面量 ⇒ 这三处必须一起去。
- **验收点**:静态断言 16/16 + `bash -n` 16/16 + 本机干跑 verify_backup(设 REPO 不存在→rc=2 无外发)+ 上线后 48h 无新增 failed。
  - ⚠️ **2026-10-06 主控收紧(§18 L50)**:原文「本机**干跑** `verify_backup`」与本节下文「孤儿脚本本机 **dry-source** 一次(仅 source+打印 REPO)」**均会执行脚本主体,一律取消** —— 改用**静态 diff + 只 source `scripts/lib/repo_paths.sh` 的探针**覆盖同一断言。起因:批4 审查 harness 门控被真实形态绕过、**真跑了 `fapi_daily_syn.sh`**(L50)。
- **回归策略**:低风险批,异常按文件 revert;孤儿脚本(update_all_serial/build_echarts/stage0_full_manual/fix_turnover_partial)迁移后**只做静态 diff + lib 探针**(原「本机 dry-source」已按 §18 L50 取消,见上)。

### 4.6 机检 ratchet(防 58/59 号脚本回潮与新脚本漏接)

- 新增 `scripts/check_repo_paths_ratchet.py`(挂既有 deploy/CI 链或独立手动跑;提案,**本任务不实现**,挂链与否见 §7 待拍板):
  - 扫描 `scripts/*.sh` + `scripts/**/*.sh`(排除 `worktrees/`、排除 `docs/`):
    - 规则 R1:含 `(REPO|GIT_REPO|TRADE_DIR|STATICDATA_REPO):-/Users/linhuichen` 的文件必须(且仅允许)在白名单=「已迁移清单」中;白名单外命中 = FAIL(新脚本回潮)。
    - 规则 R2:白名单内文件必须含**恰好 1 行** `source ... repo_paths.sh` 且**恰好 1 行** `resolve_repo` 调用。
    - 规则 R3:白名单内文件**不得**残留 `:-?/Users/linhuichen` 默认写法(允许注释内提及;用行内 python 判)。**2026-10-06 返修**:原写作 `:/Users/linhuichen`,匹配不到全仓主流形态 `:-/Users/linhuichen` ⇒ 代码行命中恒 0 ⇒ R3 空转(批1 独立审复现,已修,并加 §6.4 同源修正 + ratchet 内置变异自测 `--selftest`)。
  - 输出「PASS n / FAIL m + 逐文件行号」;FAIL 阻断(与 §22 一致性机检同精神)。
  - 迁移推进期间 R1 白名单按批增长,ratchet 只收紧不放松。

## 5. 风险与反例(逐条「改错会怎样」+ 防呆)

| # | 反例 | 改错会怎样 | 防呆 |
|---|---|---|---|
| 1 | source 路径写错(如少一层 `lib/`) | `source` 失败 → `resolve_repo` 未定义 → `command not found` rc=127;无 `set -e` 脚本可能继续跑到 cd 才炸,线索难追 | source 行采用兜底形态:`source "$(…)/lib/repo_paths.sh" || { echo "FATAL: repo_paths.sh missing" >&2; exit 2; }`(批1 定稿时把 §3.5 基线模板升级为带兜底版);机检 R2 正则断言 source 行存在 |
| 2 | REPO 与 GIT_REPO 互相误推 | 推导出的错值可能仍通过校验:本机实测 `<trade>/.venv` 与 `<trade-data>/.venv` **都存在**,`.venv/bin/python` 检查对两者都会放行 → 静默跑错目录 | ①case B 姐妹目录规则写死(先试 `dirname(GIT_REPO)/trade-data`,不存在才回退);②校验加硬断言 `REPO != GIT_REPO`;③单测 T3 覆盖两个分支(含 trade-data 命名 clone 的容错回退) |
| 3 | env 值被改写/丢失 | 41 个已配 env 的 unit 行为漂移(如值被 `pwd -P` 归一化掉 softlink,或空串 env 被当缺失) | lib 只读 env:`${REPO:-}` 形态 + 非空即原样保留(零改写);单测 T1(逐字节)+ T5(空串走推导,与既有 `${VAR:-}` 语义一致);不设 `set -u` 依赖 |
| 4 | fail-loud 被吞(`2>/dev/null`、`\|\| echo`、unit `IgnoreOnFailure`) | 响铃变哑:看起来"没报错",实际静默坏 | fatal 双出口:exit 2 + `${TMPDIR:-/tmp}/resolve_repo_fatal.$(id -un).log` **固定文件**(不依赖 stderr 存活);验收含「文件已写入」比对 |
| 5 | export 语义漂移 | python 侧 ≥12 处 `os.environ.get("REPO", <mac默认>)`(notify.py:2210/2249/2295、check_failed_units.py:87 等)取值来源整体改变 = 51 文件级静默行为变更 | lib assign-only;6 个原 export 脚本保留 export 行;每批验收断言「export 行集合 before/after 逐行相同」(§6.4 扩展项) |
| 6 | 文件级/祖先级 symlink 导致 case A/B 误判(不是"目录 symlink"而是"某祖先目录是 symlink") | raw_dir≠real_dir 在非预期场景成立 → REPO 推错(如推成 home) | 推导后校验不过 → **尝试另一 case 候选**,仍不过才 FATAL(双候选回退);单测补 1 例「祖先 symlink」;校验三重(目录+.venv+REPO≠GIT_REPO)兜底 |
| 7 | fatal 日志属主冲突 | root/其他用户先创建同名文件 → `>>` 追加失败 → 日志丢(#194 F3 实测过这个坑:默认路径创建+追加权限) | 文件名带 `$(id -un)` 防撞 + 追加失败不做任何二次动作(不影响 exit 2);批验收含「文件可创建+可追加」实测(照抄 #194 F3 复核法) |
| 8 | lib 自己发告警 | 守卫在"REPO 不可信"时制造第二故障面(发信链路同样依赖 $PY/$REPO);可能告警风暴 | lib 代码级禁止 notify(`grep -n 'notify' scripts/lib/repo_paths.sh` 为空 = 机检项);响铃统一走 #196 `check_failed_units.py` 通道 |
| 9 | 部分迁移期链内传递断裂 | 父脚本若"迁移前 export、迁移后没 export",子脚本(未迁移)从 env 拿不到值 → 子脚本回退 mac 默认 = 新回归(此前靠父 export 能工作) | 批验收 export 集合断言(同 #5);跨批抽查链:`check_r2_consistency→r2_upload_async`、`deploy→r2_upload_async`、`backup_db→verify_backup` 各跑一次 resolve-only probe 断言子脚本可见值一致 |
| 10 | 越权重构(顺手改逻辑/格式化) | diff 面失控,回归无法按批隔离,reviewer 无法审 | 硬约束「仅头两行迁移」;reviewer 机检:`git diff -U0 -- <file>` 的 `+/-` 行全部命中白名单模式(source 行/resolve 行/export 行);不符 = 打回 |
| 11 | cwd 任意 / 手跑场景 | 运维 ssh 手跑、zsh 起 bash、相对路径调用时推导依赖 caller 路径而非 cwd——已在设计内,但**若有人用相对路径 `scripts/x.sh` 且中途 cd**,`BASH_SOURCE` 相对化会错 | source 行与 `resolve_repo` 参数均用 `BASH_SOURCE[0]` 原样传递(不依赖 cwd);文档写明「lib 只支持顶层 source」 |
| 12 | 云上回归手跑撞定时任务时点 | 盘中跑 intraday 相关、盘后跑 update_all 类 → 与 unit 竞争(§14 撞车事故面) | 批3 云上动作限非交易时段;resolve-only probe 无副作用随时可跑;业务脚本**不手跑**(见 §6.5 判读原则) |

**贯穿性防呆(4 条)**:①机检 ratchet(§4.6)从批1 起每批收紧白名单;②每批 diff 只含头两行(可 revert 粒度);③lib 单测六例(§3.7)任一改动必跑;④end-to-end 验收一律走「自然 unit 运行 + 日志/告警观察」,不以手跑业务脚本充数。

## 6. 复现段(本报告每个数字的复跑命令)

> 环境:本机 `/Users/linhuichen/code/trade`(分支 feat/silence-family-tails-20261006 之上的只读操作,未改任何被统计文件)。所有命令**排除 `worktrees/`**(本机 worktree 副本会重复计数:不排除时同款命中 112)。

### 6.1 计数与清单(§1/§2 的来源)

```bash
cd /Users/linhuichen/code/trade
# 57 口径(4 变量族:REPO/GIT_REPO/TRADE_DIR/STATICDATA_REPO 的 :-/Users/linhuichen 默认)
grep -rlE '(REPO|GIT_REPO|TRADE_DIR|STATICDATA_REPO):-/Users/linhuichen' --include='*.sh' scripts | grep -v '/worktrees/' | sort      # → 57 行
grep -rlE '(REPO|GIT_REPO):-/Users/linhuichen' --include='*.sh' scripts | grep -v '/worktrees/' | wc -l                                  # → 56(不含 TRADE_DIR 变体)
grep -rl 'SENSENOVA_ENV_FILE:-/Users/linhuichen' --include='*.sh' scripts | wc -l                                                       # → 2(全族 56+1+2=59)
grep -rl 'Users/linhuichen' --include='*.sh' scripts | grep -v worktrees | wc -l                                                        # → 65(scripts/ 全量 .sh)
git grep -l 'Users/linhuichen' -- '*.sh' | wc -l                                                                                        # → 66(全仓,=65+docs/1)
# 57 行主表三个派生列
while read f; do grep -q 'notify\.py' "$f" && echo "$f"; done < <(grep -rlE '(REPO|GIT_REPO|TRADE_DIR|STATICDATA_REPO):-/Users/linhuichen' --include='*.sh' scripts | grep -v '/worktrees/') | wc -l   # → 30(notify 链路)
while read f; do grep -qE '^export (REPO|GIT_REPO)=' "$f" && echo "$f"; done < <(…) | wc -l                                              # → 6(export 脚本)
```
实测输出(2026-10-06):`57 / 56 / 2 / 65 / 66 / 30 / 6`。

### 6.2 云上 unit 映射重建(=主表「云上 unit→定时时点」列)

数据源:`docs/deploy/systemd-units-cloud-snapshot.txt`(云上 82 unit 只读快照,41 service + 41 timer)。重生成脚本(`/tmp/195_mapgen.py`,含在下方):

```python
#!/usr/bin/env python3
import re, sys, collections
snap = open('docs/deploy/systemd-units-cloud-snapshot.txt', encoding='utf-8').read()
blocks = re.split(r'^@@@FILE:', snap, flags=re.M)[1:]
cal_by_stem = {}
for b in blocks:
    name = b.split('\n', 1)[0].strip()
    if not name.endswith('.timer'): continue
    cal_by_stem[name[:-6]] = re.findall(r'^OnCalendar=(.+)$', b, re.M)
mp = collections.defaultdict(list)
for b in blocks:
    name = b.split('\n', 1)[0].strip()
    if not name.endswith('.service'): continue
    exe = re.search(r'^ExecStart=(.+)$', b, re.M)
    if not exe: continue
    m = re.search(r'/scripts/([A-Za-z0-9_\-]+\.sh)', exe.group(1))
    if m:
        cal = cal_by_stem.get(name[:-8], [])
        mp[m.group(1)].append((name, '; '.join(cal) if cal else '-'))
for k in sorted(mp): print(k, '->', ' | '.join(f'{u}({c})' for u, c in mp[k]))
print('## scripts=', len(mp), file=sys.stderr)
```
实测:stdout 36 行(`## scripts= 36`)。与 57 清单交集:
```bash
comm -12 <(python3 /tmp/195_mapgen.py 2>/dev/null | awk '{print $1}' | sort) <(basename -a $(grep -rlE '(REPO|GIT_REPO|TRADE_DIR|STATICDATA_REPO):-/Users/linhuichen' --include='*.sh' scripts | grep -v '/worktrees/') | sort) | wc -l   # → 35
comm -23 <(…) <(…)   # 36 减 57 → 仅 cloud_unit_patrol.sh(#194 已修,不在 57)
```
= reviewer「36 被 unit 调用」与「∩57=35」的差 1 闭环;41/41 service 均含 `Environment=REPO=/home/ubuntu/code/trade-data`(快照 `grep -c '^Environment=REPO='`)与 `GIT_REPO=/home/ubuntu/code/trade-data-signal`。

### 6.3 reviewer 57/36 出处(对账锚点)

```bash
sed -n '54p' docs/ops/194-review-agent-aa1efa05fb78e5b8b.md
# → "精确总数=全仓 57 个 .sh 同款 (REPO|GIT_REPO):-/Users/linhuichen(scripts/ 内 65 个含 /Users/linhuichen、全仓 66);其中 36 个正被云上 unit 以 ExecStart 调用"
```

### 6.4 批验收静态断言(每批落地时跑,FAIL 即打回)

```bash
# 用法:批验收机检 <批清单文件(每行一个 scripts/*.sh)>
while read -r f; do
  n_src=$(grep -c 'lib/repo_paths\.sh' "$f")
  n_res=$(grep -cE '^resolve_repo ' "$f")
  n_mac=$(grep -cE ':-?/Users/linhuichen' "$f")   # 2026-10-06 返修:原 ':/Users/linhuichen' 匹配不到主流病灶 ':-/Users/linhuichen' ⇒ 恒 0 = 空转闸门(§4.6 R3 同源缺陷);':-?' 同时覆盖 ':-/' 与 ':/'
  n_exp=$(grep -cE '^export (REPO|GIT_REPO)=' "$f")
  [ "$n_src" = 1 ] && [ "$n_res" = 1 ] && [ "$n_mac" = 0 ] || echo "FAIL $f src=$n_src res=$n_res mac=$n_mac"
  echo "INFO $f export_lines=$n_exp"     # 与迁移前基线值逐文件比对(批验收记录 before/after)
done < 批清单.txt
# diff 面断言(仅头两行):git diff -U0 -- "$f" | grep '^[+-]' | grep -v '^[+-][+-]' 全部命中白名单模式
```

### 6.5 云上只读核对三项(§1.3 证据的复跑;全程零业务)

```bash
ssh -i ~/.ssh/tdsignal.pem ubuntu@122.51.111.173 \
  'readlink /home/ubuntu/code/trade-data/scripts; readlink -f /home/ubuntu/code/trade-data/scripts;
   ls -d /home/ubuntu/code/trade-data/.venv /home/ubuntu/code/trade-data-signal /home/ubuntu/code/trade-data-signal-staticdata;
   grep -c "^Environment=REPO=" /etc/systemd/system/trade-*.service | grep -v ":0" | wc -l;
   systemctl show trade-r2-consistency.service -p Environment'
```
- ①布局:scripts 为 symlink(`trade-data/scripts -> trade-data-signal/scripts`),`.venv` 在 trade-data,兄弟目录三件齐;
- ②41/41 service 带 Environment=REPO(与快照一致);
- ③env 值 vs 推导值对照:lib 落地后 probe = `bash -c 'source <...>/lib/repo_paths.sh; resolve_repo <...>/scripts/<x>.sh; echo $REPO $GIT_REPO'`(仅打印、不跑业务),与 `systemctl show … -p Environment` 逐字节对比。

**判读原则(§4.1/§4.2 验收引用)**:①fail-loud 断言只认单测 T4(推导路径),**不**用「env 给坏值跑业务脚本」——env 非法值在 §3.3 语义下只 warn;②end-to-end 验收 = 自然 unit 运行 + 当日 journalctl/告警观察,**不手跑业务脚本**(防脏数据/误告警/撞时点);③云上动作只读,人为制造 failed 才需 `systemctl reset-failed <unit>` 复原(本任务未制造,后续批如制造必须复原)。

### 6.6 零外发保证声明

本任务全程:未跑 `update_all.sh`/`deploy.sh`/任何 unit/任何 notify;运行过的 ssh 命令全为 `readlink/ls/grep/systemctl show/cat` 只读;报告写作前后 `git status --porcelain` 仅 `docs/ops/195-resolve-repo-plan-20261006.md` 一个 untracked 新文件。

```bash
cd /Users/linhuichen/code/trade && git status --porcelain
```
实测(收工时刻):仅 `?? docs/ops/195-resolve-repo-plan-20261006.md` 一行 —— 唯一新增;开工时刻快照另有 `M TASKS.md` / `M docs/pending-features-index.md` 两个既有 M(非本任务改动,调研期间由主线会话 commit `137b96433` 消化,与 195 无关)。分支事实:开工快照 = `feat/silence-family-tails-20261006`,收工实测 = `main`;本调研自身零 git 写操作(未 checkout/commit/push/切分支),收工时的分支差异来自主线会话在本工作树的并行活动(reflog 可见多次 merge/checkout 与 commit `137b96433`),与本任务无关;报告为 untracked 文件,分支变动不影响其存在。

## 7. 边界与未决

### 7.1 本任务边界(只读,不实施)

- 本报告 = 方案 + 证据;**未改任何被调研文件**,不 commit。实施拆两单:①lib 本体 + 单测 + 批1(建议同一 implementer 单,worktree 隔离);②批2~批5 按 §4 分批派单(每批独立可验收)。
- 不动对象:云上 unit 文件、`trade-data/.env`、python 侧任何 `.py`、`docs/deploy/systemd-units-cloud-snapshot.txt`(快照本身)。
- 与基准铁律(§5.4)关系:本任务不涉回测/测试基准,不适用声明免;但批验收机检(§6.4)属"改动即验"纪律,与 §22 登记点一致性同精神。

### 7.2 待拍板(4 项,均不阻塞批1)

| # | 事项 | 说明 | 倾向 |
|---|---|---|---|
| 1 | STATICDATA_REPO 纳入时机 | 3 脚本(migrate_large_json_out_of_git / staticdata_backup_async / staticdata_sync,均批5)带第三种变量;可随批5 一并 `resolve_staticdata_repo`,或另立小批 | 随批5(消尾巴,一次到位) |
| 2 | ratchet 闸门挂载点(§4.6) | 挂 deploy 链 = 自动防回潮但爆半径大(闸门位置教训 #201);独立手动 = 零爆半径但可能忘跑 | 先独立(`scripts/check_repo_paths_ratchet.py` 手动跑),观察一周再议挂链 |
| 3 | python 侧 51 文件同类默认 | 见 §2.3 二阶同族;≥12 处 `os.environ.get("REPO", mac默认)` | 建议主控在 `pending-features-index.md` 新登记一条独立任务(指派口径=先盘点再定批) |
| 4 | lib 单测进 pytest 全量 | `test_resolve_repo.sh` 是 bash 自测;可加一个 10 行 python wrapper 进 `scripts/tests/` 使 pytest 全量覆盖 | 加 wrapper(与既有 pytest 231 全量并轨) |

### 7.3 与既有治理单的关系

- #194:`cloud_unit_patrol.sh` 为**已修先例**,本方案把其内联块收敛为共享 lib(批1 去重;行为不变,selftest 8/8 为准)。
- #196:`check_failed_units.py`(15min,`trade-schedule-monitor.timer`)是 fail-loud 的**唯一响铃通道**,本方案不造第二通道(§3.4/§5.8)。
- #160:`check_r2_consistency` 的既有回归资产复用进批1 验收(§6.4)。
- §14:批3/批4 云上动作为零业务探针,时点约束只影响「批合并/部署」(避 15:35/16:00/17:50/20:35/22:00 与盘中)。

### 7.4 交付物清单(供派单直接引用)

1. `scripts/lib/repo_paths.sh`(§3.2-§3.5,含 `_resolve_repo_fatal`);
2. `scripts/tests/test_resolve_repo.sh`(§3.7 T1-T6);
3. 批1 迁移 diff(`check_r2_consistency.sh` 两行模板 + `cloud_unit_patrol.sh` 回迁 lib);
4. `scripts/check_repo_paths_ratchet.py`(§4.6,R1-R3);
5. 每批验收记录(§6.4 输出 + §6.5 probe 输出 + 24/48h 观察结论)。
