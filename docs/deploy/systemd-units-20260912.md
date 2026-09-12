# systemd 单元配置(macOS launchd → 阿里云 Ubuntu 22.04 systemd)

> 生成日期:2026-09-12。**本文件只生成配置落档,不 enable/start、不改任何 .sh 脚本**(阶段4 才启动)。
> 配套:docs/deploy/migration-inventory-20260912.md(盘点)、migration-checklist-20260912.md(步骤清单)。
> 数据来源:`~/Library/LaunchAgents/com.trade.*.plist` 为主,`launchd/` 与 `scripts/plists/` 为辅,逐个 `plutil -p` 实测(2026-09-12)。

## 0. 结论速览

| 类别 | 数量 | 产物 |
|---|---|---|
| 周期任务(必迁) | 35 | 35 个 `.timer` + 35 个 `.service`(OnCalendar= 时点) |
| 飞书常驻 listener(已拍板不迁) | 1 | 无(留本机:需求入口依赖本机 Claude;云上飞书通知走 notify.py) |
| backup_db 独立备份 | 1 | 1 个 `.timer`(21:00)+ 1 个 `.service` |
| 本机 Claude 开发环境专属(不迁) | 5 | 见 §5(thinking-proxy / sensenova-healthcheck / agent-inbox-watcher / token-cache-stats / com.claude.self-backup) |
| plist 存在但未加载(不迁) | 3 | 见 §6(codex-watcher / monitor-72h / sentiment) |

## 1. 统一约定

### 1.1 服务器路径(单仓化,依据 inventory §4.3)
服务器只建一个 `/opt/trade`(REPO=GIT_REPO 同路径),本机双仓结构(trade 代码仓 + trade-data 数据仓)在服务器上合并。路径映射:

| 本机路径 | 服务器路径 |
|---|---|
| `/Users/linhuichen/code/trade-data`(REPO) | `/opt/trade` |
| `/Users/linhuichen/code/trade`(GIT_REPO) | `/opt/trade` |
| `/Users/linhuichen/code/trade-data/.venv/bin/python` | `/opt/trade/.venv/bin/python` |
| `/Users/linhuichen/code/trade-data/data/logs/...` | `/opt/trade/data/logs/...` |
| `/Users/linhuichen/code/trade/scripts/...` | `/opt/trade/scripts/...` |

### 1.2 时区
服务器必须设北京时间(§14 时点纪律不变):
```
timedatectl set-timezone Asia/Shanghai
```
全部 OnCalendar= 时点均为北京时间,与 launchd 的 StartCalendarInterval 数值完全一致(服务器设 Asia/Shanghai 后直接复用,依据 inventory §3/§5)。

### 1.3 单元命名
统一前缀 `trade-`:`trade-<name>.service` + `trade-<name>.timer`。

### 1.4 launchd → systemd 参数映射

| launchd 键 | systemd 键 | 说明 |
|---|---|---|
| StartCalendarInterval(Hour/Minute/Weekday/Day) | OnCalendar= | 时点直译;Weekday 0=周日→Sun、1..5=Mon..Fri、5=周五→Fri;Day=每月的几号 |
| StartInterval(秒) | OnUnitActiveSec= / OnCalendar= | 周期重复(本批仅 sensenova-healthcheck 用,该任务不迁) |
| EnvironmentVariables | Environment= | 逐项一行一个 KEY=VALUE |
| ExitTimeOut(秒) | TimeoutStartSec= | 任务整体超时 |
| WorkingDirectory | WorkingDirectory= | |
| StandardOutPath / StandardErrorPath | StandardOutput=append: / StandardError=append: | 保留原日志文件路径(监控/告警排查靠 `find data/logs -mmin` 扫描,路径不可变) |

### 1.5 PATH Linux 化
本机 plist 内嵌 `PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin`,其中 `/opt/homebrew/bin` 在 Linux 不存在。服务器统一为:
```
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
```

### 1.6 PURGE_SECRET 覆盖纠正(重要)
inventory §6.4 写「PURGE_SECRET 逐项迁移(backfill-evening/etf-national-team/etf-track-index 三任务)」——**实测 PURGE_SECRET 实际嵌在 24 个 plist 里**,不只 3 个。本节已逐项迁进对应 .service 的 Environment=。24 个任务清单:
backfill-evening / etf-national-team / etf-track-index / futures-backfill / gold-night / intraday-snapshot / kelly-intraday-rerun / lab-auto / lhb-backfill / pf-score-daily / pf-score-weekly / pf-stage0-manager / pf-stage0-nav / pf-stage0-overview / pf-stage0-risk / public-fund-daily / public-fund-estimation / public-fund-full / public-fund-quarterly / rzhb-backfill / schedule-monitor / self-heal / update-all / us-stock-morning。

PURGE_SECRET 值(本机全部 plist 一致):`2268f345ab8e8ee4a17ab015d199b14a12030bd13e169e319fa84d464ed983fd`。
> ⚠️ 这是敏感凭证。stage4 落地时可改为 `EnvironmentFile=/opt/trade/.env` 或单独 secret 文件,避免明文进 git。本文件按任务要求「逐项迁进 Environment=」以明文落档,勿把本文件推到公开仓库。

### 1.7 环境变量清单(通用)
多数任务共用下面 4 项环境(逐项以服务器路径重写):

| 变量 | 本机值 | 服务器值 |
|---|---|---|
| GIT_REPO | /Users/linhuichen/code/trade | /opt/trade |
| REPO | /Users/linhuichen/code/trade-data | /opt/trade |
| PATH | /opt/homebrew/bin:... | /usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin |
| PURGE_SECRET | 见 §1.6 | 同左 |

个别任务特殊 env:ab-direction-anchor 只有 `TRADE_DIR`(→ /opt/trade);check-data-gap / fapi-daily 只有 PATH+REPO(无 GIT_REPO、无 PURGE_SECRET);fetch-news 完全无 env。

## 2. 35 个周期任务完整对照表 + unit 内容

> 每个任务给出:源 plist 摘要(脚本/时点/env/超时)→ `.timer` 与 `.service` 完整内容。
> 统一模板:`Type=oneshot` + `Persistent=true`(服务器宕机错过时点后补跑,等价于保证数据完整)。

---

### 2.1 update-all(盘后主链 17:50)
- 脚本:`update_all.sh`(4 并行 pipeline + 末尾 deploy;内嵌 backup_db.sh L357——备份已另设 21:00 独立 timer,见 §4,阶段4 删 L357 段)
- 时点:每天 17:50 | ExitTimeOut=7200

`trade-update-all.timer`:
```ini
[Unit]
Description=Trade update-all daily 17:50 (源 com.trade.update-all)

[Timer]
OnCalendar=*-*-* 17:50:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-update-all.service`:
```ini
[Unit]
Description=Trade update-all (源 com.trade.update-all)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/update_all.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
Environment=PURGE_SECRET=2268f345ab8e8ee4a17ab015d199b14a12030bd13e169e319fa84d464ed983fd
TimeoutStartSec=7200
StandardOutput=append:/opt/trade/data/logs/update_all_launchd.log
StandardError=append:/opt/trade/data/logs/update_all_launchd.err
```

### 2.2 intraday-snapshot(盘中 30 时点 + 20:35)
- 脚本:`intraday_snapshot.sh`(flock 锁 /tmp/trade_intraday_snapshot.lock,Linux 兼容)
- 时点:30 个(09:25~15:35 盘中 + 20:35)| ExitTimeOut=1800

`trade-intraday-snapshot.timer`:
```ini
[Unit]
Description=Trade intraday-snapshot 30 points (源 com.trade.intraday-snapshot)

[Timer]
OnCalendar=*-*-* 09:25:00
OnCalendar=*-*-* 09:35:00
OnCalendar=*-*-* 09:45:00
OnCalendar=*-*-* 09:55:00
OnCalendar=*-*-* 10:05:00
OnCalendar=*-*-* 10:15:00
OnCalendar=*-*-* 10:25:00
OnCalendar=*-*-* 10:35:00
OnCalendar=*-*-* 10:45:00
OnCalendar=*-*-* 10:55:00
OnCalendar=*-*-* 11:05:00
OnCalendar=*-*-* 11:15:00
OnCalendar=*-*-* 11:25:00
OnCalendar=*-*-* 11:32:00
OnCalendar=*-*-* 13:01:00
OnCalendar=*-*-* 13:05:00
OnCalendar=*-*-* 13:15:00
OnCalendar=*-*-* 13:25:00
OnCalendar=*-*-* 13:35:00
OnCalendar=*-*-* 13:45:00
OnCalendar=*-*-* 13:55:00
OnCalendar=*-*-* 14:05:00
OnCalendar=*-*-* 14:15:00
OnCalendar=*-*-* 14:25:00
OnCalendar=*-*-* 14:35:00
OnCalendar=*-*-* 14:45:00
OnCalendar=*-*-* 14:55:00
OnCalendar=*-*-* 15:02:00
OnCalendar=*-*-* 15:35:00
OnCalendar=*-*-* 20:35:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-intraday-snapshot.service`:
```ini
[Unit]
Description=Trade intraday-snapshot (源 com.trade.intraday-snapshot)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/intraday_snapshot.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
Environment=PURGE_SECRET=2268f345ab8e8ee4a17ab015d199b14a12030bd13e169e319fa84d464ed983fd
TimeoutStartSec=1800
StandardOutput=append:/opt/trade/data/logs/intraday_snapshot_launchd.log
StandardError=append:/opt/trade/data/logs/intraday_snapshot_launchd.err
```

### 2.3 kelly-intraday-rerun(9:40)
- 脚本:`kelly_intraday_rerun.sh` | 时点:每天 9:40 | ExitTimeOut=200

`trade-kelly-intraday-rerun.timer`:
```ini
[Unit]
Description=Trade kelly-intraday-rerun daily 09:40 (源 com.trade.kelly-intraday-rerun)

[Timer]
OnCalendar=*-*-* 09:40:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-kelly-intraday-rerun.service`:
```ini
[Unit]
Description=Trade kelly-intraday-rerun (源 com.trade.kelly-intraday-rerun)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/kelly_intraday_rerun.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
Environment=PURGE_SECRET=2268f345ab8e8ee4a17ab015d199b14a12030bd13e169e319fa84d464ed983fd
TimeoutStartSec=200
StandardOutput=append:/opt/trade/data/logs/kelly_intraday_rerun_launchd.log
StandardError=append:/opt/trade/data/logs/kelly_intraday_rerun_launchd.err
```

### 2.4 backfill-evening(16:35 / 21:00 / 2:00)
- 脚本:`backfill_metrics.sh` | ExitTimeOut=7200

`trade-backfill-evening.timer`:
```ini
[Unit]
Description=Trade backfill-evening 3 points (源 com.trade.backfill-evening)

[Timer]
OnCalendar=*-*-* 16:35:00
OnCalendar=*-*-* 21:00:00
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-backfill-evening.service`:
```ini
[Unit]
Description=Trade backfill-evening (源 com.trade.backfill-evening)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/backfill_metrics.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
Environment=PURGE_SECRET=2268f345ab8e8ee4a17ab015d199b14a12030bd13e169e319fa84d464ed983fd
TimeoutStartSec=7200
StandardOutput=append:/opt/trade/data/logs/backfill_evening_launchd.log
StandardError=append:/opt/trade/data/logs/backfill_evening_launchd.err
```

### 2.5 etf-national-team(20:07 / 21:30)
- 脚本:`etf_national_team_backfill.sh` | ExitTimeOut=3600

`trade-etf-national-team.timer`:
```ini
[Unit]
Description=Trade etf-national-team 2 points (源 com.trade.etf-national-team)

[Timer]
OnCalendar=*-*-* 20:07:00
OnCalendar=*-*-* 21:30:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-etf-national-team.service`:
```ini
[Unit]
Description=Trade etf-national-team (源 com.trade.etf-national-team)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/etf_national_team_backfill.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
Environment=PURGE_SECRET=2268f345ab8e8ee4a17ab015d199b14a12030bd13e169e319fa84d464ed983fd
TimeoutStartSec=3600
StandardOutput=append:/opt/trade/data/logs/etf_national_team_launchd.log
StandardError=append:/opt/trade/data/logs/etf_national_team_launchd.err
```

### 2.6 etf-track-index(周日 3:30)
- 脚本:`fetch_etf_track_index.py`(venv python)| 时点:周日(Weekday 0)3:30 | ExitTimeOut=1800

`trade-etf-track-index.timer`:
```ini
[Unit]
Description=Trade etf-track-index weekly Sun 03:30 (源 com.trade.etf-track-index)

[Timer]
OnCalendar=Sun *-*-* 03:30:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-etf-track-index.service`:
```ini
[Unit]
Description=Trade etf-track-index (源 com.trade.etf-track-index)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/opt/trade/.venv/bin/python /opt/trade/scripts/fetch_etf_track_index.py
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
Environment=PURGE_SECRET=2268f345ab8e8ee4a17ab015d199b14a12030bd13e169e319fa84d464ed983fd
TimeoutStartSec=1800
StandardOutput=append:/opt/trade/data/logs/etf-track-index-launchd.log
StandardError=append:/opt/trade/data/logs/etf-track-index-launchd.err
```

### 2.7 fapi-daily(18:10)
- 脚本:`fapi_daily_syn.sh`(源路径在 trade/scripts,单仓后同 /opt/trade/scripts)| 时点:18:10 | ExitTimeOut=600
- env:仅 PATH + REPO(无 GIT_REPO、无 PURGE_SECRET)

`trade-fapi-daily.timer`:
```ini
[Unit]
Description=Trade fapi-daily daily 18:10 (源 com.trade.fapi-daily)

[Timer]
OnCalendar=*-*-* 18:10:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-fapi-daily.service`:
```ini
[Unit]
Description=Trade fapi-daily (源 com.trade.fapi-daily)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/fapi_daily_syn.sh
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
TimeoutStartSec=600
StandardOutput=append:/opt/trade/data/logs/fapi_daily_launchd.log
StandardError=append:/opt/trade/data/logs/fapi_daily_launchd.err
```

### 2.8 futures-backfill(20:05 / 21:00)
- 脚本:`futures_backfill.sh` | ExitTimeOut=3600

`trade-futures-backfill.timer`:
```ini
[Unit]
Description=Trade futures-backfill 2 points (源 com.trade.futures-backfill)

[Timer]
OnCalendar=*-*-* 20:05:00
OnCalendar=*-*-* 21:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-futures-backfill.service`:
```ini
[Unit]
Description=Trade futures-backfill (源 com.trade.futures-backfill)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/futures_backfill.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
Environment=PURGE_SECRET=2268f345ab8e8ee4a17ab015d199b14a12030bd13e169e319fa84d464ed983fd
TimeoutStartSec=3600
StandardOutput=append:/opt/trade/data/logs/futures_backfill_launchd.log
StandardError=append:/opt/trade/data/logs/futures_backfill_launchd.err
```

### 2.9 gold-night(2:40 黄金夜盘)
- 脚本:`gold_night.sh` | ExitTimeOut=600

`trade-gold-night.timer`:
```ini
[Unit]
Description=Trade gold-night daily 02:40 (源 com.trade.gold-night)

[Timer]
OnCalendar=*-*-* 02:40:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-gold-night.service`:
```ini
[Unit]
Description=Trade gold-night (源 com.trade.gold-night)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/gold_night.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
Environment=PURGE_SECRET=2268f345ab8e8ee4a17ab015d199b14a12030bd13e169e319fa84d464ed983fd
TimeoutStartSec=600
StandardOutput=append:/opt/trade/data/logs/gold_night_launchd.log
StandardError=append:/opt/trade/data/logs/gold_night_launchd.err
```

### 2.10 lhb-backfill(18:30 / 19:30 龙虎榜)
- 脚本:`lhb_backfill.sh` | ExitTimeOut=3600

`trade-lhb-backfill.timer`:
```ini
[Unit]
Description=Trade lhb-backfill 2 points (源 com.trade.lhb-backfill)

[Timer]
OnCalendar=*-*-* 18:30:00
OnCalendar=*-*-* 19:30:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-lhb-backfill.service`:
```ini
[Unit]
Description=Trade lhb-backfill (源 com.trade.lhb-backfill)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/lhb_backfill.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
Environment=PURGE_SECRET=2268f345ab8e8ee4a17ab015d199b14a12030bd13e169e319fa84d464ed983fd
TimeoutStartSec=3600
StandardOutput=append:/opt/trade/data/logs/lhb_backfill_launchd.log
StandardError=append:/opt/trade/data/logs/lhb_backfill_launchd.err
```

### 2.11 rzhb-backfill(8:00 / 19:15 融资融券)
- 脚本:`rzhb_backfill.sh` | ExitTimeOut=3600

`trade-rzhb-backfill.timer`:
```ini
[Unit]
Description=Trade rzhb-backfill 2 points (源 com.trade.rzhb-backfill)

[Timer]
OnCalendar=*-*-* 08:00:00
OnCalendar=*-*-* 19:15:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-rzhb-backfill.service`:
```ini
[Unit]
Description=Trade rzhb-backfill (源 com.trade.rzhb-backfill)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/rzhb_backfill.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
Environment=PURGE_SECRET=2268f345ab8e8ee4a17ab015d199b14a12030bd13e169e319fa84d464ed983fd
TimeoutStartSec=3600
StandardOutput=append:/opt/trade/data/logs/rzhb_backfill_launchd.log
StandardError=append:/opt/trade/data/logs/rzhb_backfill_launchd.err
```

### 2.12 turnover-backfill(周一~五 21:10)
- 脚本:`turnover_backfill.sh` | ExitTimeOut=300

`trade-turnover-backfill.timer`:
```ini
[Unit]
Description=Trade turnover-backfill Mon..Fri 21:10 (源 com.trade.turnover-backfill)

[Timer]
OnCalendar=Mon..Fri *-*-* 21:10:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-turnover-backfill.service`:
```ini
[Unit]
Description=Trade turnover-backfill (源 com.trade.turnover-backfill)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/turnover_backfill.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
TimeoutStartSec=300
StandardOutput=append:/opt/trade/data/logs/turnover_backfill_launchd.log
StandardError=append:/opt/trade/data/logs/turnover_backfill_launchd.err
```

### 2.13 ab-direction-anchor(21:15)
- 脚本:`run_ab_direction_anchor.sh` | 时点:21:15
- env:仅 `TRADE_DIR`(→ /opt/trade),无 REPO/GIT_REPO/PURGE_SECRET;无 ExitTimeOut、无 WorkingDirectory(源 plist 未设,此处补 WorkingDirectory=/opt/trade 保险)

`trade-ab-direction-anchor.timer`:
```ini
[Unit]
Description=Trade ab-direction-anchor daily 21:15 (源 com.trade.ab-direction-anchor)

[Timer]
OnCalendar=*-*-* 21:15:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-ab-direction-anchor.service`:
```ini
[Unit]
Description=Trade ab-direction-anchor (源 com.trade.ab-direction-anchor)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/run_ab_direction_anchor.sh
Environment=TRADE_DIR=/opt/trade
StandardOutput=append:/opt/trade/data/logs/ab_direction_anchor.out.log
StandardError=append:/opt/trade/data/logs/ab_direction_anchor.err.log
```

### 2.14 nextday-plan(周一~五 20:55 干跑)
- 脚本:`nextday_plan.sh` | ExitTimeOut=600

`trade-nextday-plan.timer`:
```ini
[Unit]
Description=Trade nextday-plan Mon..Fri 20:55 (源 com.trade.nextday-plan)

[Timer]
OnCalendar=Mon..Fri *-*-* 20:55:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-nextday-plan.service`:
```ini
[Unit]
Description=Trade nextday-plan (源 com.trade.nextday-plan)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/nextday_plan.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
TimeoutStartSec=600
StandardOutput=append:/opt/trade/data/logs/nextday_plan_launchd.log
StandardError=append:/opt/trade/data/logs/nextday_plan_launchd.err
```

### 2.15 s06-snapshot(周一~五 20:35)
- 脚本:`s06_snapshot.sh`(timeout 降级链阶段4 Linux 化)| ExitTimeOut=600

`trade-s06-snapshot.timer`:
```ini
[Unit]
Description=Trade s06-snapshot Mon..Fri 20:35 (源 com.trade.s06-snapshot)

[Timer]
OnCalendar=Mon..Fri *-*-* 20:35:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-s06-snapshot.service`:
```ini
[Unit]
Description=Trade s06-snapshot (源 com.trade.s06-snapshot)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/s06_snapshot.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
TimeoutStartSec=600
StandardOutput=append:/opt/trade/data/logs/s06_snapshot_launchd.log
StandardError=append:/opt/trade/data/logs/s06_snapshot_launchd.err
```

### 2.16 check-data-gap(周一~五 22:35)
- 脚本:`check_data_gap_alerts.sh` | ExitTimeOut=600
- env:仅 PATH + REPO(无 GIT_REPO、无 PURGE_SECRET);stdout 落 `.out` 文件

`trade-check-data-gap.timer`:
```ini
[Unit]
Description=Trade check-data-gap Mon..Fri 22:35 (源 com.trade.check-data-gap)

[Timer]
OnCalendar=Mon..Fri *-*-* 22:35:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-check-data-gap.service`:
```ini
[Unit]
Description=Trade check-data-gap (源 com.trade.check-data-gap)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/check_data_gap_alerts.sh
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
TimeoutStartSec=600
StandardOutput=append:/opt/trade/data/logs/check_data_gap_launchd.out
StandardError=append:/opt/trade/data/logs/check_data_gap_launchd.err
```

### 2.17 daily-brief(20:40,--multi)
- 脚本:`run_daily_brief.sh --multi`(deepseek 官方 API,§5.6 峰谷:20:40 低谷)| ExitTimeOut=900

`trade-daily-brief.timer`:
```ini
[Unit]
Description=Trade daily-brief daily 20:40 (源 com.trade.daily-brief)

[Timer]
OnCalendar=*-*-* 20:40:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-daily-brief.service`:
```ini
[Unit]
Description=Trade daily-brief --multi (源 com.trade.daily-brief)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/run_daily_brief.sh --multi
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
TimeoutStartSec=900
StandardOutput=append:/opt/trade/data/logs/daily_brief_launchd.log
StandardError=append:/opt/trade/data/logs/daily_brief_launchd.err
```

### 2.18 daily-summary-supplement(20:30)
- 脚本:`daily_summary_email.py --mode supplement`(venv python)| ExitTimeOut=600

`trade-daily-summary-supplement.timer`:
```ini
[Unit]
Description=Trade daily-summary-supplement daily 20:30 (源 com.trade.daily-summary-supplement)

[Timer]
OnCalendar=*-*-* 20:30:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-daily-summary-supplement.service`:
```ini
[Unit]
Description=Trade daily-summary-supplement (源 com.trade.daily-summary-supplement)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/opt/trade/.venv/bin/python /opt/trade/scripts/daily_summary_email.py --mode supplement
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
TimeoutStartSec=600
StandardOutput=append:/opt/trade/data/logs/daily_summary_supplement_launchd.log
StandardError=append:/opt/trade/data/logs/daily_summary_supplement_launchd.err
```

### 2.19 brief-push(20:45)
- 脚本:`brief_push_wrapper.sh` | ExitTimeOut=300

`trade-brief-push.timer`:
```ini
[Unit]
Description=Trade brief-push daily 20:45 (源 com.trade.brief-push)

[Timer]
OnCalendar=*-*-* 20:45:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-brief-push.service`:
```ini
[Unit]
Description=Trade brief-push (源 com.trade.brief-push)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/brief_push_wrapper.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
TimeoutStartSec=300
StandardOutput=append:/opt/trade/data/logs/brief_push_launchd.log
StandardError=append:/opt/trade/data/logs/brief_push_launchd.err
```

### 2.20 fetch-news(每小时 :01 与 :31,共 48 次)
- 脚本:`fetch_news.py`(venv python)| 源 plist **无任何 env**(依赖系统默认 PATH),无 ExitTimeOut

`trade-fetch-news.timer`:
```ini
[Unit]
Description=Trade fetch-news hourly :01/:31 (源 com.trade.fetch-news)

[Timer]
OnCalendar=*-*-* *:01,31:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-fetch-news.service`:
```ini
[Unit]
Description=Trade fetch-news (源 com.trade.fetch-news)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/opt/trade/.venv/bin/python /opt/trade/scripts/fetch_news.py
StandardOutput=append:/opt/trade/data/logs/fetch_news_launchd.log
StandardError=append:/opt/trade/data/logs/fetch_news_launchd.err
```
> 注:源 plist 无 Environment=,沿用系统 PATH。stage4 若脚本内部调用 git/curl 等系统工具,确认在 /usr/bin 可见即可。

### 2.21 pf-score-daily(16:00 场外基金评分)
- 脚本:`pf_score_daily.sh` | ExitTimeOut=1800
- 日志:stdout/stderr 同一文件 `pf-score-daily-launchd.log`

`trade-pf-score-daily.timer`:
```ini
[Unit]
Description=Trade pf-score-daily daily 16:00 (源 com.trade.pf-score-daily)

[Timer]
OnCalendar=*-*-* 16:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-pf-score-daily.service`:
```ini
[Unit]
Description=Trade pf-score-daily (源 com.trade.pf-score-daily)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/pf_score_daily.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
Environment=PURGE_SECRET=2268f345ab8e8ee4a17ab015d199b14a12030bd13e169e319fa84d464ed983fd
TimeoutStartSec=1800
StandardOutput=append:/opt/trade/data/logs/pf-score-daily-launchd.log
StandardError=append:/opt/trade/data/logs/pf-score-daily-launchd.log
```

### 2.22 pf-score-weekly(周日 3:17)
- 脚本:`pf_score_weekly.sh` | ExitTimeOut=14400 | stdout/stderr 同文件

`trade-pf-score-weekly.timer`:
```ini
[Unit]
Description=Trade pf-score-weekly Sun 03:17 (源 com.trade.pf-score-weekly)

[Timer]
OnCalendar=Sun *-*-* 03:17:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-pf-score-weekly.service`:
```ini
[Unit]
Description=Trade pf-score-weekly (源 com.trade.pf-score-weekly)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/pf_score_weekly.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
Environment=PURGE_SECRET=2268f345ab8e8ee4a17ab015d199b14a12030bd13e169e319fa84d464ed983fd
TimeoutStartSec=14400
StandardOutput=append:/opt/trade/data/logs/pf-score-weekly-launchd.log
StandardError=append:/opt/trade/data/logs/pf-score-weekly-launchd.log
```

### 2.23 pf-stage0-nav(周五 1:43)
- 脚本:`stage0_nav.sh` | ExitTimeOut=21600 | stdout/stderr 同文件

`trade-pf-stage0-nav.timer`:
```ini
[Unit]
Description=Trade pf-stage0-nav Fri 01:43 (源 com.trade.pf-stage0-nav)

[Timer]
OnCalendar=Fri *-*-* 01:43:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-pf-stage0-nav.service`:
```ini
[Unit]
Description=Trade pf-stage0-nav (源 com.trade.pf-stage0-nav)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/stage0_nav.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
Environment=PURGE_SECRET=2268f345ab8e8ee4a17ab015d199b14a12030bd13e169e319fa84d464ed983fd
TimeoutStartSec=21600
StandardOutput=append:/opt/trade/data/logs/stage0-nav-launchd.log
StandardError=append:/opt/trade/data/logs/stage0-nav-launchd.log
```

### 2.24 pf-stage0-overview(周日 2:17)
- 脚本:`stage0_overview.sh` | ExitTimeOut=25200 | stdout/stderr 同文件

`trade-pf-stage0-overview.timer`:
```ini
[Unit]
Description=Trade pf-stage0-overview Sun 02:17 (源 com.trade.pf-stage0-overview)

[Timer]
OnCalendar=Sun *-*-* 02:17:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-pf-stage0-overview.service`:
```ini
[Unit]
Description=Trade pf-stage0-overview (源 com.trade.pf-stage0-overview)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/stage0_overview.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
Environment=PURGE_SECRET=2268f345ab8e8ee4a17ab015d199b14a12030bd13e169e319fa84d464ed983fd
TimeoutStartSec=25200
StandardOutput=append:/opt/trade/data/logs/stage0-overview-launchd.log
StandardError=append:/opt/trade/data/logs/stage0-overview-launchd.log
```

### 2.25 pf-stage0-risk(每月 15 日 2:33)
- 脚本:`stage0_risk.sh` | ExitTimeOut=18000 | stdout/stderr 同文件

`trade-pf-stage0-risk.timer`:
```ini
[Unit]
Description=Trade pf-stage0-risk monthly 15th 02:33 (源 com.trade.pf-stage0-risk)

[Timer]
OnCalendar=*-*-15 02:33:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-pf-stage0-risk.service`:
```ini
[Unit]
Description=Trade pf-stage0-risk (源 com.trade.pf-stage0-risk)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/stage0_risk.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
Environment=PURGE_SECRET=2268f345ab8e8ee4a17ab015d199b14a12030bd13e169e319fa84d464ed983fd
TimeoutStartSec=18000
StandardOutput=append:/opt/trade/data/logs/stage0-risk-launchd.log
StandardError=append:/opt/trade/data/logs/stage0-risk-launchd.log
```

### 2.26 pf-stage0-manager(每月 1 日 2:47)
- 脚本:`stage0_manager.sh` | ExitTimeOut=12600 | stdout/stderr 同文件

`trade-pf-stage0-manager.timer`:
```ini
[Unit]
Description=Trade pf-stage0-manager monthly 1st 02:47 (源 com.trade.pf-stage0-manager)

[Timer]
OnCalendar=*-*-01 02:47:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-pf-stage0-manager.service`:
```ini
[Unit]
Description=Trade pf-stage0-manager (源 com.trade.pf-stage0-manager)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/stage0_manager.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
Environment=PURGE_SECRET=2268f345ab8e8ee4a17ab015d199b14a12030bd13e169e319fa84d464ed983fd
TimeoutStartSec=12600
StandardOutput=append:/opt/trade/data/logs/stage0-manager-launchd.log
StandardError=append:/opt/trade/data/logs/stage0-manager-launchd.log
```

### 2.27 public-fund-daily(16:30 / 17:00)
- 脚本:`public_fund_daily.sh` | ExitTimeOut=300

`trade-public-fund-daily.timer`:
```ini
[Unit]
Description=Trade public-fund-daily 2 points (源 com.trade.public-fund-daily)

[Timer]
OnCalendar=*-*-* 16:30:00
OnCalendar=*-*-* 17:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-public-fund-daily.service`:
```ini
[Unit]
Description=Trade public-fund-daily (源 com.trade.public-fund-daily)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/public_fund_daily.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
Environment=PURGE_SECRET=2268f345ab8e8ee4a17ab015d199b14a12030bd13e169e319fa84d464ed983fd
TimeoutStartSec=300
StandardOutput=append:/opt/trade/data/logs/public_fund_daily_launchd.log
StandardError=append:/opt/trade/data/logs/public_fund_daily_launchd.err
```

### 2.28 public-fund-estimation(10:00 / 11:00 / 13:30 / 14:30)
- 脚本:`public_fund_estimation.sh` | ExitTimeOut=120

`trade-public-fund-estimation.timer`:
```ini
[Unit]
Description=Trade public-fund-estimation 4 points (源 com.trade.public-fund-estimation)

[Timer]
OnCalendar=*-*-* 10:00:00
OnCalendar=*-*-* 11:00:00
OnCalendar=*-*-* 13:30:00
OnCalendar=*-*-* 14:30:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-public-fund-estimation.service`:
```ini
[Unit]
Description=Trade public-fund-estimation (源 com.trade.public-fund-estimation)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/public_fund_estimation.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
Environment=PURGE_SECRET=2268f345ab8e8ee4a17ab015d199b14a12030bd13e169e319fa84d464ed983fd
TimeoutStartSec=120
StandardOutput=append:/opt/trade/data/logs/public_fund_estimation_launchd.log
StandardError=append:/opt/trade/data/logs/public_fund_estimation_launchd.err
```

### 2.29 public-fund-full(22:00)
- 脚本:`public_fund_full.sh` | ExitTimeOut=21600

`trade-public-fund-full.timer`:
```ini
[Unit]
Description=Trade public-fund-full daily 22:00 (源 com.trade.public-fund-full)

[Timer]
OnCalendar=*-*-* 22:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-public-fund-full.service`:
```ini
[Unit]
Description=Trade public-fund-full (源 com.trade.public-fund-full)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/public_fund_full.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
Environment=PURGE_SECRET=2268f345ab8e8ee4a17ab015d199b14a12030bd13e169e319fa84d464ed983fd
TimeoutStartSec=21600
StandardOutput=append:/opt/trade/data/logs/public_fund_full_launchd.log
StandardError=append:/opt/trade/data/logs/public_fund_full_launchd.err
```

### 2.30 public-fund-quarterly(3:00 / 4:00 / 7:00)
- 脚本:`public_fund_quarterly.sh` | ExitTimeOut=3600

`trade-public-fund-quarterly.timer`:
```ini
[Unit]
Description=Trade public-fund-quarterly 3 points (源 com.trade.public-fund-quarterly)

[Timer]
OnCalendar=*-*-* 03:00:00
OnCalendar=*-*-* 04:00:00
OnCalendar=*-*-* 07:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-public-fund-quarterly.service`:
```ini
[Unit]
Description=Trade public-fund-quarterly (源 com.trade.public-fund-quarterly)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/public_fund_quarterly.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
Environment=PURGE_SECRET=2268f345ab8e8ee4a17ab015d199b14a12030bd13e169e319fa84d464ed983fd
TimeoutStartSec=3600
StandardOutput=append:/opt/trade/data/logs/public_fund_quarterly_launchd.log
StandardError=append:/opt/trade/data/logs/public_fund_quarterly_launchd.err
```

### 2.31 overfit-monitor(周一~五 21:40)
- 脚本:`overfit_monitor.sh` | ExitTimeOut=900

`trade-overfit-monitor.timer`:
```ini
[Unit]
Description=Trade overfit-monitor Mon..Fri 21:40 (源 com.trade.overfit-monitor)

[Timer]
OnCalendar=Mon..Fri *-*-* 21:40:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-overfit-monitor.service`:
```ini
[Unit]
Description=Trade overfit-monitor (源 com.trade.overfit-monitor)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/overfit_monitor.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
TimeoutStartSec=900
StandardOutput=append:/opt/trade/data/logs/overfit_monitor_launchd.log
StandardError=append:/opt/trade/data/logs/overfit_monitor_launchd.err
```

### 2.32 lab-auto(19:00 lab 页数据)
- 脚本:`update_lab.sh` | ExitTimeOut=7200 | 日志名 `update_lab_launchd.*`

`trade-lab-auto.timer`:
```ini
[Unit]
Description=Trade lab-auto daily 19:00 (源 com.trade.lab-auto)

[Timer]
OnCalendar=*-*-* 19:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-lab-auto.service`:
```ini
[Unit]
Description=Trade lab-auto (源 com.trade.lab-auto)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/update_lab.sh
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
Environment=PURGE_SECRET=2268f345ab8e8ee4a17ab015d199b14a12030bd13e169e319fa84d464ed983fd
TimeoutStartSec=7200
StandardOutput=append:/opt/trade/data/logs/update_lab_launchd.log
StandardError=append:/opt/trade/data/logs/update_lab_launchd.err
```

### 2.33 us-stock-morning(5:00 美股早盘)
- 脚本:`us_stock_morning.sh` | ExitTimeOut=1800

`trade-us-stock-morning.timer`:
```ini
[Unit]
Description=Trade us-stock-morning daily 05:00 (源 com.trade.us-stock-morning)

[Timer]
OnCalendar=*-*-* 05:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-us-stock-morning.service`:
```ini
[Unit]
Description=Trade us-stock-morning (源 com.trade.us-stock-morning)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/us_stock_morning.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
Environment=PURGE_SECRET=2268f345ab8e8ee4a17ab015d199b14a12030bd13e169e319fa84d464ed983fd
TimeoutStartSec=1800
StandardOutput=append:/opt/trade/data/logs/us_stock_morning_launchd.log
StandardError=append:/opt/trade/data/logs/us_stock_morning_launchd.err
```

### 2.34 self-heal(每 15 分 :07/:22/:37/:52)
- 脚本:`self_heal.sh`(源脚本依赖 launchctl state,阶段4 改 systemctl is-active/is-failed 或首期删检查)| ExitTimeOut=1800

`trade-self-heal.timer`:
```ini
[Unit]
Description=Trade self-heal every 15min :07/:22/:37/:52 (源 com.trade.self-heal)

[Timer]
OnCalendar=*-*-* *:07,22,37,52:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-self-heal.service`:
```ini
[Unit]
Description=Trade self-heal (源 com.trade.self-heal)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/self_heal.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
Environment=PURGE_SECRET=2268f345ab8e8ee4a17ab015d199b14a12030bd13e169e319fa84d464ed983fd
TimeoutStartSec=1800
StandardOutput=append:/opt/trade/data/logs/self_heal_launchd.log
StandardError=append:/opt/trade/data/logs/self_heal_launchd.err
```

### 2.35 schedule-monitor(每 15 分 :00/:15/:30/:45)
- 脚本:`schedule_monitor.sh`(源脚本 launchctl 加载检查需阶段4 Linux 适配)| ExitTimeOut=600

`trade-schedule-monitor.timer`:
```ini
[Unit]
Description=Trade schedule-monitor every 15min :00/:15/:30/:45 (源 com.trade.schedule-monitor)

[Timer]
OnCalendar=*-*-* *:00,15,30,45:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-schedule-monitor.service`:
```ini
[Unit]
Description=Trade schedule-monitor (源 com.trade.schedule-monitor)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/schedule_monitor.sh
Environment=GIT_REPO=/opt/trade
Environment=REPO=/opt/trade
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
Environment=PURGE_SECRET=2268f345ab8e8ee4a17ab015d199b14a12030bd13e169e319fa84d464ed983fd
TimeoutStartSec=600
StandardOutput=append:/opt/trade/data/logs/schedule_monitor_launchd.log
StandardError=append:/opt/trade/data/logs/schedule_monitor_launchd.err
```

## 3. 飞书常驻 listener(已拍板不迁)

决策(2026-09-12 用户拍板):feishu-listener **留本机不迁**。理由:飞书 WS 长连接的产出是 `append_todo_to_tasks` 落盘 TASKS.md,给本机 Claude 主控读需求清单,本质是"给本机 Claude 收需求"的入口,云上无 Claude Code 即无意义。云上需要"发飞书抄送通知"的能力由 `notify.py`(config/feishu.json + lark-oapi,已随迁)覆盖。

## 4. backup_db 独立 timer(21:00)

- 源:本机无独立 launchd 任务,由 `update_all.sh` L357 内嵌调用 `bash "$REPO/scripts/backup_db.sh"`。
- 改法(inventory §4.3):独立 systemd timer 21:00(update-all 17:50 完成后 DB 最新);阶段4 删 update_all.sh L357 段,备份单点管理。
- 参数:`REPO=/opt/trade`(Environment 注入,一行不改脚本默认值);`RETAIN_DAYS=7`(脚本 L23 默认 14 → 注入 7,改后 7 天约 2.1G)。

`trade-backup-db.timer`:
```ini
[Unit]
Description=Trade backup_db daily 21:00 (从 update_all.sh 内嵌拆出)

[Timer]
OnCalendar=*-*-* 21:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

`trade-backup-db.service`:
```ini
[Unit]
Description=Trade backup_db (sqlite .backup 热备 + 推 R2 signal-backup + verify)

[Service]
Type=oneshot
WorkingDirectory=/opt/trade
ExecStart=/bin/bash /opt/trade/scripts/backup_db.sh
Environment=REPO=/opt/trade
Environment=GIT_REPO=/opt/trade
Environment=RETAIN_DAYS=7
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
TimeoutStartSec=7200
```
> 注:backup_db.sh 自身写 `$LOG`(data/logs 下)并 `notify.py --severe` 告警,stdout/stderr 走 journal 即可;如要保留文件可加 `StandardOutput=append:/opt/trade/data/logs/backup_db_systemd.log`。

## 5. 不迁(本机 Claude 开发环境专属,5 个)

| 任务 | 源 plist | 判定 | 理由 |
|---|---|---|---|
| thinking-proxy | com.trade.thinking-proxy(scripts/ 下) | 不迁 | 商汤 5-7 把 key 轮换代理(127.0.0.1:8899),只服务本机 Claude Code 的 ANTHROPIC_BASE_URL;服务器不跑 Claude Code 即无用 |
| sensenova-healthcheck | com.trade.sensenova-healthcheck | 不迁 | 每 5 分 GET 127.0.0.1:8899/healthz;代理不迁则无监控对象 |
| agent-inbox-watcher | com.trade.agent-inbox-watcher | 不迁 | 轮询 Claude/codex inbox,env 依赖 CLAUDE_BIN/CODEX_BIN(nvm 路径)+ KeepAlive |
| token-cache-stats | com.trade.token-cache-stats | 不迁 | Claude token 缓存统计(23:30) |
| com.claude.self-backup | com.claude.self-backup | 不迁(或改法) | 备份 ~/.claude memory/skills 到 R2 claude-backup/,纯本机 Claude 环境;服务器也跑 Claude Code 才迁 |

## 6. plist 存在但未加载(不迁)

| 任务 | 源 plist | 说明 |
|---|---|---|
| codex-watcher | com.trade.codex-watcher(LaunchAgents 残留) | launchctl list 无此 label,历史遗留 |
| monitor-72h | com.trade.monitor-72h(LaunchAgents 残留) | 同上 |
| sentiment | com.trade.sentiment(launchd/ 目录) | 同上,历史遗留(旧 scheduler 入口) |

## 7. 落地注意事项(stage4 用)

1. **只生成配置,不 enable/start**:本文件是配置落档;`systemctl daemon-reload && systemctl enable --now trade-<name>.timer` 由阶段4 执行。
2. **时区**:先 `timedatectl set-timezone Asia/Shanghai`,否则 OnCalendar= 全部偏移。
3. **§14 时点纪律不变**:17:50 update-all、20:40 daily-brief、盘中 9:30-15:30 不跑全量 export+deploy;服务器同北京时间。
4. **§5.6 deepseek 峰谷**:daily-brief 20:40 低谷不变;key 在 trade-data/.env 随迁。
5. **PURGE_SECRET 明文**:§1.6 已纠正覆盖 24 任务;落地可改 EnvironmentFile 防泄漏,勿推公开仓库。
6. **macOS 专属点适配**(inventory §5,阶段4 改脚本,非本文件范围):pmset/caffeinate 删段、timeout→gtimeout 降级链、self-heal/schedule-monitor 的 launchctl 检查、/opt/homebrew/bin PATH。本文件只生成 systemd 配置,不动任何 .sh。
7. **单仓化**:服务器 `/opt/trade` 单仓;双份 DB/backups 问题自然消失(REPO=GIT_REPO=/opt/trade)。
8. **21:00 并发提示(§14 生产稳定性)**:21:00 现有 3 个 timer 并发——backfill-evening(backfill_metrics.sh)、futures-backfill(futures_backfill.sh)、backup-db(backup_db.sh)。backup_db 用 sqlite3 `.backup()` 在线热备(WAL 一致快照,不锁库,inventory §4.1.1),与另两者不冲突;本机 launchd 原本就有 backfill-evening@21:00 + futures-backfill@21:00 并发,新加 backup_db@21:00 是 inventory §4.3 指定的独立时点(update-all 17:50 完成后 DB 最新)。若 stage4 实测发现 DB 写竞争,可把 backup-db 顺延到 21:05。
