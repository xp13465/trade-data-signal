# 云上 systemd TimeoutStartSec 收口 + 本机↔云上逐 key 对账（task #36）

> 日期：2026-09-16
> 对象：云上 `/etc/systemd/system/trade-*.service`（37 个）+ 本机 `~/Library/LaunchAgents/com.trade.*.plist`（41 个）

## 一、背景根因

- 本机 launchd 的 `ExitTimeOut` 语义 = **退出宽限**（launchd 停 job 时 SIGTERM→SIGKILL 的等待时间），**不是**「运行超时」。
- 迁移到云上 systemd 时，把本机 `ExitTimeOut` 值**错映射**成了 systemd 的 `TimeoutStartSec`（这才是「运行超时」，跑超 N 秒即 SIGTERM/SIGKILL 强杀），还拍脑袋给了 14 档值。
- 后果：慢任务被强杀。已确认两例（exit code=2 / status=15 = SIGTERM）：
  - `turnover_backfill`：逐只拉 5200 只 baostock，原 `TimeoutStartSec=300`，5min 被杀（迁移时已临时修 300→0，本次保留 0）。
  - `public_fund_daily`：本应 ~15s 的日更任务，2026-09-15 17:00 那次挂死 30min，被原 `TimeoutStartSec=1800` 强杀（是「挂死」不是「慢任务」，见 §三 分类依据）。
  - 另有 `us_stock_morning` 在 schedule_monitor 日志留过 `exit!=0|143`（SIGTERM）痕迹。
- 拍脑袋的 14 档值（实际 14 档，任务书列了 13 档漏了 10800）：`0 / 120 / 200 / 300 / 600 / 900 / 1800 / 7200 / 10800 / 12600 / 14400 / 18000 / 21600 / 25200`。

## 二、收口原则（分类依据 = 真实耗时，不拍脑袋）

真实耗时来源（三源互证）：
1. `schedule_stats.json`（schedule_monitor 调度表，`last_duration_sec`，14 个核心任务）
2. systemd `ExecMainStartTimestamp`/`ExecMainExitTimestamp` 起止差（37 个全量）
3. 各脚本头部注释的「预期耗时」（最权威，能区分「真慢」vs「挂死/撞锁跳过/非季报月跳过」的假象）

> 关键教训：ExecMain 起止差会反映「被强杀」「撞锁跳过」「非季报月跳过」的假象，不能直接当真实耗时。典型：
> - `public_fund_daily` ExecMain=1800s（是被 1800s 超时强杀的挂死），脚本注释真实耗时 ~15s → 应按快任务给 600s 防死锁，不是给 0。
> - `stage0_risk` ExecMain=0s（9 月非季报月 `exit 0` 跳过），脚本注释真实耗时 ~4.5h → 慢任务给 0。
> - `public_fund_full` ExecMain=5s（撞 public_fund.lock 跳过），脚本注释真实耗时 ~5.25h → 慢任务给 0。

收口规则：
- **慢任务 → `TimeoutStartSec=0`（无限，回归 launchd「无运行超时」语义）**：真实耗时 ≥1min，或当前值在 7200+ 档，或无实测耗时的采集/回填/计算类任务（保守）。
- **快任务 → `TimeoutStartSec=600`（10min，防死锁兜底，远超正常）**：真实耗时 <1min 且为秒级任务。

## 三、修改清单（29 个改动 + 8 个不变）

### 改 TimeoutStartSec=0（慢任务，19 个）

| service | 原值 | 新值 | 真实耗时依据 |
|---|---|---|---|
| backup-db | 7200 | 0 | 265s（4.4min），sqlite 热备 |
| etf-national-team | 7200 | 0 | 883s（14.7min），ETF 汪汪队 |
| fapi-daily | 600 | 0 | 69s，FAPI 采集+北交所宽度重算链式 |
| futures-backfill | 7200 | 0 | 447s（7.4min），期货机构持仓 |
| gold-night | 600 | 0 | 429s（7.1min），黄金原油夜盘补采，已逼近 600s 阈值 |
| intraday-snapshot | 1800 | 0 | 968s（16min），盘中快照 |
| lab-auto | 7200 | 0 | 1526s（25min），策略实验室 |
| lhb-backfill | 7200 | 0 | 467s（7.8min），龙虎榜 |
| lof-track-index | 1800 | 0 | 无实测（周频首跑未触发），回填采集类保守取 0 |
| overfit-monitor | 900 | 0 | 160s（2.7min），过拟合监控（schedule 表「约3分钟」） |
| pf-score-weekly | 14400 | 0 | 1837s（30.6min），公募评分周频 |
| pf-stage0-manager | 12600 | 0 | ~3h（脚本注释：fundf10 任职历史） |
| pf-stage0-nav | 21600 | 0 | 5 年净值历史 27409 只断点续采（脚本注释） |
| pf-stage0-overview | 25200 | 0 | 11726s（3h15m）实测 |
| pf-stage0-risk | 18000 | 0 | ~4.5h（脚本注释：risk+fee 逐只 xq），9 月非季报月跳过 |
| public-fund-full | 21600 | 0 | ~5.25h（脚本注释：全量 9000 只×2 子页） |
| public-fund-quarterly | 7200 | 0 | ~35min（脚本注释：5 汇总+top1000+8 指标） |
| update-all | 10800 | 0 | 2405s（40min），收盘全量 |
| us-stock-morning | 7200 | 0 | 297s（5min），美股早采，曾有 exit=143 痕迹 |

### 改 TimeoutStartSec=600（快任务，10 个）

| service | 原值 | 新值 | 真实耗时依据 |
|---|---|---|---|
| ab-direction-anchor | 900 | 600 | 1s |
| brief-push | 300 | 600 | 2s |
| daily-brief | 900 | 600 | 25s |
| etf-track-index | 1800 | 600 | 29s |
| kelly-intraday-rerun | 200 | 600 | 33s |
| pf-score-daily | 1800 | 600 | 24s |
| public-fund-daily | 1800 | 600 | ~15s（脚本注释），9-15 是挂死 30min 被强杀，非慢任务 |
| public-fund-estimation | 120 | 600 | 7s |
| rzhb-backfill | 7200 | 600 | 6s（schedule 表「约2秒」），两融单采轻量 |
| self-heal | 10800 | 600 | 13s，每 15min 自愈监控 |

### 保持不变（8 个，已正确）

| service | 值 | 说明 |
|---|---|---|
| backfill-evening | 0 | 迁移时已临时修 0，本次保留 |
| turnover-backfill | 0 | 迁移时已临时修 0，本次保留 |
| check-data-gap | 600 | 27s 快任务 |
| daily-summary-supplement | 600 | 6s 快任务 |
| fetch-news | 600 | 8s 快任务 |
| nextday-plan | 600 | 10s 快任务 |
| s06-snapshot | 600 | 19s 快任务 |
| schedule-monitor | 600 | 3s 快任务 |

## 四、daemon-reload + TimeoutStartUSec 验证结果

所有文件改完执行 `sudo systemctl daemon-reload` 后，逐个 `systemctl show -p TimeoutStartUSec` 验证：

- `TimeoutStartSec=0` → `TimeoutStartUSec=infinity`：**21 个**（19 改动 + backfill-evening/turnover-backfill 两个已 0）
- `TimeoutStartSec=600` → `TimeoutStartUSec=10min`：**16 个**（10 改动 + 6 个原本就 600）
- 合计 37 个 service，全部与目标一致，无遗漏、无错值。

## 五、逐 key 对账表

本机 plist key 与云上 service/timer 的映射关系及错映射清单：

| 本机 plist key | 云上对应 | 对账结论 |
|---|---|---|
| Label | service 名 + Description「源 com.trade.X」 | 一致（命名对应） |
| ProgramArguments | ExecStart | 脚本路径平台差异（`/Users/linhuichen/code/trade[-data]` vs `/home/ubuntu/code/trade-data`），trade-data/scripts 是 symlink 指 trade/scripts，实际一致 |
| StartCalendarInterval | timer OnCalendar | 见下方「调度时点漂移」 |
| EnvironmentVariables | Environment=/EnvironmentFile= | 见下方「环境变量差异」 |
| WorkingDirectory | WorkingDirectory= | 一致（平台路径差异，预期） |
| StandardOutPath | StandardOutput=append: | 见下方「日志重定向缺失」 |
| StandardErrorPath | StandardError=append: | 见下方「日志重定向缺失」 |
| RunAtLoad | （无直接对应，用 timer Persistent=true 表达错过补跑） | 合理迁移，非错映射 |
| **ExitTimeOut** | **TimeoutStartSec** | **核心错映射（语义级）** |

### 5.1 核心错映射（语义级）

**`ExitTimeOut`（退出宽限）→ `TimeoutStartSec`（运行超时）**：两者语义完全不同，云上把值直接搬了过去。这是本次 root cause。

### 5.2 数值漂移（本机 ExitTimeOut vs 云原 TimeoutStartSec 对不上）

| service | 本机 ExitTimeOut | 云原 TimeoutStartSec |
|---|---|---|
| etf-national-team | 3600 | 7200 |
| futures-backfill | 3600 | 7200 |
| lhb-backfill | 3600 | 7200 |
| rzhb-backfill | 3600 | 7200 |
| public-fund-daily | 300 | 1800 |
| public-fund-quarterly | 3600 | 7200 |
| self-heal | 1800 | 10800 |
| update-all | 7200 | 10800 |
| us-stock-morning | 1800 | 7200 |
| fetch-news | 无 ExitTimeOut | 600（凭空加） |

### 5.3 调度时点漂移（StartCalendarInterval vs OnCalendar）

| service | 本机 StartCalendarInterval | 云 OnCalendar | 差异 |
|---|---|---|---|
| fetch-news | 每小时 :01 和 :31（48 点/日） | `*:01,45:00`（每小时 :01 和 :45） | **分钟 :31 → :45 错映射** |

其余多时点任务（backfill-evening 3 点、etf-national-team 2 点、futures-backfill 2 点、lhb-backfill 2 点、rzhb-backfill 2 点、public-fund-daily 2 点、public-fund-estimation 4 点、public-fund-quarterly 3 点、intraday-snapshot 30 点）逐一核对一致。

### 5.4 日志重定向缺失（本机有 StandardOut/ErrorPath，云上缺）

云上 4 个 service 缺 `StandardOutput`/`StandardError`（本机对应 plist 都有），输出会落到 systemd journal 而非既有日志文件，影响日志可查性：

- nextday-plan、overfit-monitor、s06-snapshot、turnover-backfill

（backup-db 也缺，但它是云上独有，本机无对应，不算对比缺失。）

### 5.5 本机有但云上未迁移的 plist（6 个）

| plist | 类型 | 说明 |
|---|---|---|
| agent-inbox-watcher | KeepAlive 长驻 | 收件监听，未迁移 |
| env | launchctl setenv | mac 特有 TRADE_HOST_TAG=mac |
| feishu-listener | KeepAlive 长驻 | 飞书监听，TRADE_HOST_TAG=mac |
| monitor-72h | 定时 :10/:40 | **未迁移，可能是 gap（每 30min 监控）** |
| sensenova-healthcheck | StartInterval=300 | 商汤代理健康检查 |
| token-cache-stats | 定时 23:30 | **未迁移，可能是 gap（每日 token 统计）** |

### 5.6 云上独有 service（本机无对应 plist，2 个）

| service | 说明 |
|---|---|
| backup-db | 从 update_all.sh 内嵌拆出（sqlite .backup 热备 + 推 R2 + verify） |
| check-data-gap | 数据缺口检测（Mon..Fri 22:35），本机无对应 plist |

### 5.7 其他对账差异（说明性，非错映射）

1. **环境变量 PATH**：本机 `/opt/homebrew/bin`（mac），云 `/usr/local/bin`（ubuntu）——预期平台差异。
2. **PURGE_SECRET**：本机散落在各 plist 的 EnvironmentVariables，云统一 `EnvironmentFile=/home/ubuntu/code/trade-data/.env`——迁移方式合理，但需确认 `.env` 含 PURGE_SECRET（未在本任务范围内逐一核验 .env 内容）。
3. **ab-direction-anchor 的 TRADE_DIR**：本机 `TRADE_DIR=/Users/linhuichen/code/trade`（主仓），云 `TRADE_DIR=/home/ubuntu/code/trade-data-signal`（signal 仓）——路径语义不同，需确认是否有意（云上 GIT_REPO 也指 signal 仓）。
4. **pf-score-daily 等 StandardError 指向 .log**（stdout/stderr 同文件）：本机即如此，云忠实复制，一致。
5. **self-heal KillMode=process**：云上额外加（本机无对应概念），控制 kill 行为，合理。
6. **RunAtLoad=false 定时任务 → timer Persistent=true**：错过时点补跑语义，合理迁移。

## 六、遗留 / 待跟进（超出本次收口范围）

1. `fetch-news` 调度分钟 :31→:45 漂移：是否对齐本机，需用户拍板（改了触发频率）。
2. `monitor-72h` / `token-cache-stats` 未迁移到云上：确认是否应迁移。
3. 云上 4 个 service（nextday-plan/overfit-monitor/s06-snapshot/turnover-backfill）缺 StandardOutput/StandardError：可补 append 到既有日志文件。
4. `public_fund_daily` 9-15 挂死 30min 的根因（非本任务 TimeoutStartSec 范畴，属脚本挂死 bug），建议单独排查。
5. `ab-direction-anchor` 云上 TRADE_DIR 指向 signal 仓的语义确认。
