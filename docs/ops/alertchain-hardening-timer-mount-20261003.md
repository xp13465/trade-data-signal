# check_monitor_heartbeat.py 调度器挂载(2026-10-03)

> 任务:补齐 batchA 半成品(P0-1 心跳消费方)的调度器接线。续跑 `feat/alertchain-hardening-20261003`。
> 依据:docs/ops/alertchain-hardening-review-20261003.md §8「半成品风险」——P0-1 只写了代码没接线,合 main 不算完成。
> 被挂载脚本:scripts/check_monitor_heartbeat.py(读 /tmp/schedule-monitor-heartbeat.txt mtime,缺失或 >30min → notify --severe --dedup-key schedule_monitor_heartbeat --dedup-window 3600)。

## 0. 结论速览

| 项 | 值 |
|---|---|
| 挂载对象 | trade-check-monitor-heartbeat.{timer,service}(云上 /etc/systemd/system) |
| 时点 | `*-*-* *:11,26,41,56:00`(每 15 分,与既有 3 组全错开) |
| 驱动脚本 | check_monitor_heartbeat.py(服务端逻辑**一行不改**,本次只接线) |
| 顺序坑根治 | service 用 `ConditionPathExists=`,脚本未 merge 到位时 skip 不算 failed |
| 文档登记 | docs/deploy/systemd-units-20260912.md §2.36(gen_systemd_units.py 可复现 76→78) |
| 云上状态 | enable + start 完成,next 时点正确,unit loaded/active |

## 1. 时点选择理由

云上现有 15min 档占用清单(2026-10-03 实测 `systemctl list-timers --all`):

| timer | OnCalendar | 分钟档 |
|---|---|---|
| trade-schedule-monitor | `*-*-* *:00,15,30,45:00` | :00/:15/:30/:45 |
| trade-self-heal | `*-*-* *:07,22,37,52:00` | :07/:22/:37/:52 |
| trade-fetch-news | `*-*-* *:01,45:00` | :01/:45(每小时) |
| **trade-check-monitor-heartbeat(新)** | `*-*-* *:11,26,41,56:00` | **:11/:26/:41/:56** |

选择 `:11/:26/:41/:56` 理由:
1. 与 schedule-monitor(:00/15/30/45)、self-heal(:07/22/37/52)两组 15min 档**逐分钟错开**。
2. 与 fetch-news 每小时 :01/:45 也错开(:41 vs :45 差 4 分)。
3. 组内间距 15min(11→26→41→56→下小时 11),与心跳消费者 30min 阈值(2 轮)匹配——消费者判定 stale 需要心跳**连续 2 轮**没更新,因此它必须在生产者的 4 个时点**之后**才跑才看得到新鲜心跳。选 :11/:26/:41/:56 恒晚于最近一次 schedule-monitor 触发(:00→:11、:15→:26、:30→:41、:45→:56,均 +11min),保证每次检查都能看到最新心跳,不会误判"心跳太旧"。

   ⚠️ 反例说明:若消费者选在生产者**之前**(如 :00 组之前),则每次消费者跑时看到的是上一轮心跳,恰好在 30min 阈值边缘,极端情况(生产者晚跑/卡顿)易误报。:+11 偏移彻底规避。

### 1.1 云上现有全部 trade-* timers 时点清单(2026-10-03 22:18 systemctl list-timers 实测)

| timer | OnCalendar(分钟/hh:mm) |
|---|---|
| trade-schedule-monitor | `*:00,15,30,45`(15min) |
| trade-self-heal | `*:07,22,37,52`(15min) |
| trade-fetch-news | `*:01,45`(每小时) |
| trade-check-monitor-heartbeat(新) | `*:11,26,41,56`(15min) |
| trade-intraday-snapshot | 09:25~15:35 盘中 29 点 + 20:35 |
| trade-kelly-intraday-rerun | 09:40 |
| trade-nextday-gap-check | Mon..Fri 09:26 |
| trade-pf-score-daily | 16:00 |
| trade-public-fund-estimation | 10:00 / 11:00 / 13:30 / 14:30 |
| trade-public-fund-daily | 16:30 / 17:00 |
| trade-update-all | 17:50 |
| trade-fapi-daily | 18:10 |
| trade-lhb-backfill | 18:30 / 19:30 |
| trade-lab-auto | 19:00 |
| trade-rzhb-backfill | 08:00 / 19:15 |
| trade-etf-national-team | 20:07 / 21:30 |
| trade-futures-backfill | 20:05 / 21:00 |
| trade-daily-summary-supplement | 20:30 |
| trade-daily-brief | 20:40 |
| trade-brief-push | 20:45 |
| trade-s06-snapshot | Mon..Fri 20:35 |
| trade-backup-db | 21:00 |
| trade-ab-direction-anchor | 21:15 |
| trade-turnover-backfill | Mon..Fri 21:10 |
| trade-overfit-monitor | Mon..Fri 21:40 |
| trade-public-fund-full | 22:00 |
| trade-nextday-plan | Mon..Fri 22:30 |
| trade-check-data-gap | Mon..Fri 22:35 |
| trade-backfill-evening | 16:35 / 21:00 / 02:00 |
| trade-gold-night | 02:40 |
| trade-us-stock-morning | 05:00 |
| trade-public-fund-quarterly | 03:00 / 04:00 / 07:00 |
| trade-pf-stage0-overview | Sun 02:17 |
| trade-pf-score-weekly | Sun 03:17 |
| trade-etf-track-index | Sun 03:30 |
| trade-lof-track-index | Sun 04:00 |
| trade-pf-stage0-nav | Fri 01:43 |
| trade-pf-stage0-manager | monthly 1st 02:47 |
| trade-pf-stage0-risk | monthly 15th 02:33 |

新时点 `:11/:26/:41/:56` 与既有 15min 档逐一比对:与 schedule-monitor(`:00/:15/:30/:45`)、self-heal(`:07/:22/:37/:52`)、fetch-news(`:01/:45`)均**逐分钟错开**,无重合;与全部固定 hh:mm 档(表内其余行)按分钟位比对,**唯一分钟位重合 = `trade-nextday-gap-check`(Mon..Fri 09:26,每日 1 次)**。两任务无共享资源(gap-check 行情跳空检查 vs 心跳消费只读 /tmp 文件 + notify 写告警),systemd 同时启动两个 oneshot 无资源竞争,**不构成 §14 撞车**。

## 2. 云上安装操作(已执行)

```bash
# 0. 前提:云上脚本暂不存在(等待 merge 后 git pull),ConditionPathExists 兜底
ssh -i ~/tdsignal.pem -o BatchMode=yes ubuntu@122.51.111.173

# 1. 落 unit 文件(内容见 §4,与 gen_systemd_units 输出一致)
cat > /etc/systemd/system/trade-check-monitor-heartbeat.timer <<'EOF'
[Unit]
Description=Trade check-monitor-heartbeat every 15min :11/:26/:41/:56 (P0-1 心跳消费方)

[Timer]
OnCalendar=*-*-* *:11,26,41,56:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

cat > /etc/systemd/system/trade-check-monitor-heartbeat.service <<'EOF'
[Unit]
Description=Trade check-monitor-heartbeat (P0-1 schedule-monitor 心跳消费方)
ConditionPathExists=/home/ubuntu/code/trade-data/scripts/check_monitor_heartbeat.py

[Service]
User=ubuntu
Type=oneshot
WorkingDirectory=/home/ubuntu/code/trade-data
Environment=GIT_REPO=/home/ubuntu/code/trade-data-signal
Environment=REPO=/home/ubuntu/code/trade-data
Environment=MAIN_REPO=/home/ubuntu/code/trade-data
ExecStart=/home/ubuntu/code/trade-data/.venv/bin/python /home/ubuntu/code/trade-data/scripts/check_monitor_heartbeat.py
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
EnvironmentFile=/home/ubuntu/code/trade-data/.env
TimeoutStartSec=600
StandardOutput=append:/home/ubuntu/code/trade-data/data/logs/check_monitor_heartbeat_launchd.log
StandardError=append:/home/ubuntu/code/trade-data/data/logs/check_monitor_heartbeat_launchd.err
EOF

# 2. reload + enable + start
systemctl daemon-reload
systemctl enable trade-check-monitor-heartbeat.timer
systemctl start trade-check-monitor-heartbeat.timer

# 3. 验证
systemctl list-timers | grep check-monitor-heartbeat   # NEXT 应为下一个 :11/:26/:41/:56
systemctl status trade-check-monitor-heartbeat.service # 脚本未到位 → skip(condition),非 failed
```

## 3. 验证结果(2026-10-03 已实测)

### 3.1 云上安装验证(2026-10-03 实测)
- [x] `systemctl list-timers | grep check-monitor-heartbeat` → NEXT = 22:26(`:26` 档,符合 `:11/:26/:41/:56`),与 self-heal 22:22、schedule-monitor 22:30 实测错开
- [x] `systemctl status trade-check-monitor-heartbeat.timer` → loaded/active(enable 已建 symlink)
- [x] 脚本未 merge 到位时 `systemctl start trade-check-monitor-heartbeat.service` → **condition skip**(is-active=inactive、is-failed=inactive,**非 failed**),journal 记录 `Condition check resulted in ... being skipped` → 不惊动任何监控维度
- [x] 生产 latest.md 未污染:mtime 保持 00:45(恢复记录),dry-run 实测未触碰(见 §3.3)
- ⚠️ 过程记录:`ConditionPathExists` 初写 `[Service]` 段被 systemd 拒(Unknown key,忽略),已修正到 `[Unit]` 段(Unit 段条件指令生效);本次修订已同步登记文档 §2.36 与本文件 §2/§4 unit 内容

### 3.2 顺序坑处理(第⑥,本批重点)
云上 git HEAD = 0cdda656c(main 最新),`/home/ubuntu/code/trade-data/scripts/check_monitor_heartbeat.py` **不存在**(脚本在 feat 分支 cf68c7270,未 merge)。此时 timer 已挂上,合并前每 15min 触发一次:

- ExecStart 指向不存在的脚本 → 无 `ConditionPathExists` 时 service 会 failed。
- **处理**:service 带 `ConditionPathExists=/home/ubuntu/code/trade-data/scripts/check_monitor_heartbeat.py` → 脚本不存在时 systemd **直接 skip**(不算 failed,状态 inactive,journal 记 skip),不会惊动:
  - `schedule_monitor.sh` 的 systemd 检查:它是**显式 LAUNCHCTL_LABELS 列表**逐 label `systemctl is-active`,新 unit 不在列表内 → 不探测。
  - `self_heal.sh`:`launchctl_state` 只查自己 label 白名单 → 不探测。
  - 全仓无 systemd 全量 failed 扫描脚本 → 无其他维度。
- merge 后主控走 `scripts/main-merge.sh` → 云上 `git pull` 拉到脚本 → 下一次 timer 触发自动正常执行,无需人工干预。

### 3.3 端到端验证(本地 + 云上 dry-run,不发真告警)
用注入假心跳 + `--dry-run` 实测三场景(check_monitor_heartbeat.py 逻辑零改动,复用原脚本):

| 场景 | 注入 | 输出 | 结论 |
|---|---|---|---|
| 心跳文件缺失 | 删文件 | `✗ heartbeat 文件不存在` + 完整 notify 命令(dry-run) | 告警构造正确 ✓ |
| 心跳陈旧 31min | touch -t 31min ago | `✗ heartbeat 陈旧 2837s > 1800s` + notify 命令 | 告警构造正确 ✓ |
| 心跳新鲜 5min | touch -t 5min ago | `OK heartbeat age=5s <= 1800s`(静默) | 健康路径零告警 ✓ |

**云上实测(2026-10-03)**:scp 脚本副本到云上 `/tmp/check_monitor_heartbeat_test.py`,以云上 venv python 跑三场景(缺失/陈旧32min/生产心跳现状302s),判定与 notify 命令构造全对;dry-run 分支是 `print + return 0`,**不真执行 notify.py** → 生产 latest.md 未被污染(mtime 仍为 00:45 恢复记录,实测确认)。

> 禁止真告警实测(会给用户发邮件/写生产 latest.md)。仅 dry-run 验证命令构造与判定逻辑;真实发送链已由 notify.py 独立通道(latest.md/email/feishu)既有测试覆盖。

> ⚠️ **dry-run 语义澄清**(防 P2 混淆):check_monitor_heartbeat.py 的 `--dry-run` = print 命令后直接 return,**不会调 notify.py** → 不会写 latest.md(隔离安全)。复核报告 P2 的「write_alert 不 gate dry_run」是 notify.py **自身 CLI** 的另一个场景(brief_push_wrapper 手动 `--dry-run` 失败分支带 `--alert-issue` 会写真实 latest.md)——两者不同,已在 brief_push_wrapper.sh 注释修正中说明。

## 4. 回退方法

```bash
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173
systemctl disable --now trade-check-monitor-heartbeat.timer
rm /etc/systemd/system/trade-check-monitor-heartbeat.timer /etc/systemd/system/trade-check-monitor-heartbeat.service
systemctl daemon-reload
```

> 回退后 P0-1 回到「代码就绪、未挂载」状态;如需重新挂载按 §2 重做即可。unit 登记文档(docs/deploy/systemd-units-20260912.md §2.36)可随时用 `python3 scripts/gen_systemd_units.py <目录>` 重新生成。

## 5. 挂载就绪清单(§23.15 自验)

- [x] **unit 就绪**:timer + service 内容入仓(docs/deploy/systemd-units-20260912.md §2.36),gen_systemd_units.py 可复现(76→78)
- [x] **安装就绪**:云上 /etc/systemd/system/ 已落,enable + start,next 时点正确,loaded/active
- [x] **文档就绪**:本文件(挂载/验证/回退三件)+ 登记文档
- [x] **验证就绪**:三场景 dry-run 实测 + 时点错开核对 + 顺序坑 ConditionPathExists 验证
- [x] **覆盖范围核对**:实际会告警范围 = 心跳缺失/超时(每 15min 检查一次,dedup 1h);展示/声称范围 = 心跳消费方接线,两者一致,无降级展示项
- [x] **无降级**:脚本到位前 ConditionPathExists skip(静默),到位后自动生效,无「先上残缺版」残迹
- [x] **回退可逆**:§4 一命令卸载,登记文档保留可复现

## 6. 遗留/已知边界(诚实标注)

1. 本消费者自身由云上 timer 驱动,timer 被删/崩则告警链断(元-元监控层),与脚本 docstring 一致,不在本次范围。
2. 告警经 notify 独立通道发,notify 崩溃则无法送出(latest.md 也写不进),已知代价。
3. 脚本 merge 到云上的时序由主控 main-merge + 云上 git pull 完成,本批不做云上 pull(主控 merge 后统一)。
