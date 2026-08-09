# 72h 持续监控方案

> **用户需求原话**："72小时监控不是开盘后，而是这72小时一直监控着各个细节流程，比如采集，上传，发布，功能稳定性，功能及时性等"。
>
> 即 72h 持续监控（非开盘后一次性 curl），覆盖：采集 / 上传 / 发布 / 功能稳定性 / 功能及时性 5 类。
>
> **本文档为调研产物（只读不改代码），实施等主控确认后派 agent。**

---

## 一、现有 schedule_monitor 覆盖清单

### 1.1 schedule_monitor.sh（launchd 每15分钟，Minute=0/15/30/45）

**配置**：`~/Library/LaunchAgents/com.trade.schedule-monitor.plist`
**脚本**：`scripts/schedule_monitor.sh`（918行，python heredoc 内嵌）
**频率**：每15分钟，不依赖 session（launchd 持久）
**超时**：ExitTimeOut=600s

**覆盖 8 维度**：

| # | 维度 | 检查项 | 阈值 | 告警 | 去重 |
|---|------|--------|------|------|------|
| 1 | 采集-漏跑 | 9任务计划时点+30min窗口内 last_run<sch | 30min容忍 | SEVERE邮件 | alert_state.json (missed\|task\|sch\|date) |
| 2 | 采集-退出失败 | schedule_stats.json last_exit 非0非null | exit!=0 | SEVERE邮件 | alert_state.json (task\|exit!=0\|code) |
| 2b | 采集-log异常 | scan_log_anomaly 抓 Traceback/异常类名/FATAL | 关键词命中 | SEVERE邮件 | alert_state.json (task\|keyword\|md5) |
| 3 | 采集-耗时 | last_duration_sec 超阈值 | intraday>600s/update_all>1800s/backfill>1800s/us_stock>900s | SEVERE邮件 | alert_state.json (task\|dur>Ns) |
| 4 | launchd加载 | 11个 com.trade label 未加载 | launchctl print 无 state 行 | SEVERE邮件 | alert_state.json (label\|not_loaded) |
| 5 | ETF汪汪队耗时 | daily>300s / backfill>1800s | 2h内完成行 | SEVERE邮件 | 无去重(每次发) |
| 6 | 产物时效(Worker) | 线上 overview.json collected_at vs NOW | 交易日盘中<20min，3域名容错 | SEVERE邮件 | alert_state.json (overview_lag_3domain) |
| 7 | R2可达性 | ssd.fx8.store/data/overview.json curl | 不可达 | SEVERE邮件 | alert_state.json (r2_unreachable) |
| 8 | R2时效 | R2 overview/intraday collected_at | 交易日盘中 overview<20min/intraday<15min | SEVERE邮件 | alert_state.json (r2_overview_lag/r2_intraday_lag) |

**9个监控任务**（gen_schedule_stats.py TASKS）：
update_all(17:50) / backfill_evening(02:00,16:35,21:00) / intraday_snapshot(30时点盘中+15:35+20:35) / futures_backfill(20:05,21:00) / lhb_backfill(18:30,19:30) / rzhb_backfill(08:00,19:15) / etf_national_team(20:07,21:30) / lab_auto(19:00) / us_stock_morning(05:00)

### 1.2 self_heal.sh（launchd 每15分钟，Minute=7/22/37/52）

- force 重跑失败任务（白名单+每日3次上限+audit log）
- retry_failed_metrics.py 单项指标失败自动重采
- 与 schedule_monitor 错开7分钟（monitor先告警，heal后自愈）

### 1.3 check_data_integrity.py（deploy 前置 + 手动）

- 14个校验函数 + 关键文件存在性（详见 docs/smoke-checklist.md Part 1/2）
- deploy.sh L122-123 接入，fail 阻断 deploy
- **仅在 deploy 时跑，非持续监控**

### 1.4 notify.py 告警机制

- 邮件 + Telegram + data/alerts/latest.md（多渠道独立失败不阻塞）
- `--severe` 标记 + `--alert-issue` 写 latest.md + `--alert-log` 记日志路径
- `--from-prefix` 发件人名前缀（如 `[告警]`）
- `--dedup-key` + `--dedup-window` 去重（独立于 alert_state.json）

### 1.5 heartbeat 兜底

- schedule_monitor 每次跑完写 `/tmp/schedule-monitor-heartbeat.txt`（时间戳+告警数）
- 主控 cron 读此文件，>30min 未更新 = launchd 层可能挂了

---

## 二、5 类需求覆盖分析

| # | 用户需求 | 现有覆盖 | 缺口 | 补充方式 |
|---|----------|----------|------|----------|
| 1 | **采集** | ✅ 9任务漏跑/退出/log异常/耗时/launchctl加载 + self_heal force重跑 | ⚠️ public_fund系列(pf-stage0-*/pf-score-*/public-fund-daily等)不在9任务监控列表 | 扩展 gen_schedule_stats TASKS 或 72h脚本单独检查 |
| 2 | **上传R2** | ⚠️ R2可达性+overview/intraday时效 | ❌ index/industry/trade_sim/public_fund/signal_kelly 各前缀上传成功否 | 72h脚本 curl 各前缀代表性文件时效 |
| 3 | **发布push main** | ❌ 未覆盖 | ❌ deploy.sh push main 成功否 + 线上版本最新(sw.js CACHE_VERSION) | 72h脚本 curl 线上 sw.js vs 本地 + git log origin/main 时效 |
| 4 | **功能稳定性** | ❌ 未覆盖(check_data_integrity只在deploy跑) | ❌ 线上 P0 smoke(overview scores/index etfs/board_etf_map/alert/trade_sim_indices) | 72h脚本 curl P0 smoke 关键项 |
| 5 | **功能及时性** | ⚠️ overview/intraday 时效(盘中<20min/<15min) | ❌ signal_kelly backtest 口径非旧258% + 其他日频数据时效 | 72h脚本 curl signal_kelly_backtest 检查 annualized_return 口径 |

---

## 三、补充方案设计

### 3.1 方案选型：独立 `scripts/monitor_72h.sh` + 临时 launchd

**推荐方案A（独立脚本+临时launchd）**，不碰 schedule_monitor.sh（生产脚本零回归风险）。

| 方案 | 优点 | 缺点 | 推荐 |
|------|------|------|------|
| **A. 独立 monitor_72h.sh + 临时launchd** | 不碰生产脚本零回归 / 72h后launchctl unload即停 / 独立flag控制 | 多1个launchd任务(每30min) | ✅ |
| B. 扩展schedule_monitor.sh加72h块 | 不增launchd任务 | 改918行生产脚本有回归风险(§15) / flag混入主逻辑 | ✗ |

### 3.2 补充 5 类检查项

#### 检查1：采集补充 - public_fund 系列任务

现有 schedule_monitor 监控9任务，不含 public_fund 系列（13个 plist）。

**检查方式**：curl `https://ss.fx8.store/data/schedule_stats.json`，检查 public_fund 相关任务条目是否存在 + last_exit。

或检查 launchd log 时效：`data/logs/{pf-stage0-*,public-fund-*,pf-score-*}_launchd.log` 最近运行时间。

**public_fund 系列 plist 时点**：
- `public-fund-daily`: 16:30, 17:00
- `public-fund-estimation`: 10:00, 11:00, 13:30, 14:30（盘中实时估值）
- `public-fund-full`: 22:00
- `public-fund-quarterly`: 03:00, 04:00, 07:00
- `pf-stage0-manager`: 每月1日 02:47
- `pf-stage0-nav`: 每周五 01:43
- `pf-stage0-overview`: 每周日 02:17
- `pf-stage0-risk`: 每月15日 02:33
- `pf-score-daily`: 16:00
- `pf-score-weekly`: 每周日 03:17

**补充策略**：72h脚本检查这些任务的 launchd log 是否有当日"开始"行 + exit code。weekly/monthly 任务检查最近一次运行是否在预期周期内。

#### 检查2：上传R2各前缀

**检查方式**：curl R2 直连各前缀代表性文件，检查 HTTP 200 + 内容非空。

| 前缀 | 代表性文件 | R2 URL | 检查项 |
|------|-----------|--------|--------|
| index | `sh-all.json` | `https://ssd.fx8.store/index/sh-all.json` | 200 + etfs 非空 |
| industry | `industry-1m.json` | `https://ssd.fx8.store/industry/industry-1m.json` | 200 + concepts 非空 |
| trade_sim | `trade_sim_sh000001_stats.json` | `https://ssd.fx8.store/trade_sim_data/trade_sim_sh000001_stats.json` | 200 + keys 非空 |
| public_fund | `public_fund_summary.json` | `https://ssd.fx8.store/public_fund/public_fund_summary.json` | 200 |
| signal_kelly | `signal_kelly_backtest.json` | `https://ssd.fx8.store/data/signal_kelly_backtest.json` | 200 + quadrants 非空 |
| data(大range) | `overview.json` | `https://ssd.fx8.store/data/overview.json` | 200 + collected_at（已由schedule_monitor覆盖） |

**告警**：任一前缀 404/超时/内容空 = SEVERE（dedup-key=`r2_prefix_{prefix}_fail`）。

#### 检查3：发布 push main + 线上版本最新

**3a. git push main 时效**：
- `git -C /Users/linhuichen/code/trade log origin/main --oneline -1 --format=%ci` 检查最近 push 时间
- 交易日盘后(15:35/20:35 intraday + 17:50 update_all)应有 push
- 非交易日不强求（周末无 push 正常）
- **阈值**：交易日 last push >4h = WARN（可能 push 失败）

**3b. 线上 sw.js CACHE_VERSION 最新**：
- curl `https://ss.fx8.store/sw.js` 提取 `CACHE_VERSION = 'vX-YYYYMMDD-NN'`
- 和本地 `static-site/sw.js` 的 CACHE_VERSION 对比
- 不一致 = 线上版本滞后（push 失败或 CF cache 未 purge）
- **告警**：线上 != 本地 = SEVERE（dedup-key=`sw_version_mismatch`）

**3c. 线上 overview.json vs 本地一致**：
- curl `https://ss.fx8.store/data/overview.json` 提取 `date` 字段
- 和本地 `static-site/data/overview.json` 的 date 对比
- 不一致 = 线上滞后
- **告警**：线上 date < 本地 date = SEVERE（dedup-key=`overview_date_mismatch`）

#### 检查4：功能稳定性（P0 smoke 精简版）

从 docs/smoke-checklist.md Part 3 的 20 项 P0 中，选**最关键的 8 项**持续监控（curl 数据层，非全量 20 项省时）：

| # | P0项 | curl URL | 检查项 | 失败现象 |
|---|------|----------|--------|----------|
| S1 | KPI角标 | `ss.fx8.store/data/overview.json` | date==今日/最近交易日 + 9 scores 非null | KPI显示昨日/数值null |
| S2 | 分时图 | `ss.fx8.store/data/intraday_snapshot.json` | collected_at含今日 + indices len>=17 | 分时图无数据 |
| S3 | 指数ETF | `ssd.fx8.store/index/sh-all.json` | etfs 字段非空(len>0) | 全部无ETF |
| S4 | board_etf_map | (本地) `data/board_etf_map.json` | 空数组占比<30% | 全部无ETF根因 |
| S5 | 信号网格 | `ss.fx8.store/data/alert.json` | date非null + high.score非null | 信号不更新 |
| S6 | 首屏包 | `ss.fx8.store/data/boot.json` | overview.date==今日 + missing==[] | 成交额昨日值 |
| S7 | 策略实验室 | `ss.fx8.store/data/trade_sim_indices.json` | list len>=100 | 入口空 |
| S8 | 通知面板 | `ss.fx8.store/data/notifications.json` | date==今日 | 通知不更新 |

**告警**：任一项 fail = SEVERE（dedup-key=`p0_smoke_{id}_fail`）。

**注**：S4 board_etf_map 检查本地 `data/board_etf_map.json`（线上不暴露此文件），其余 curl 线上。非交易日 date 允许=最近交易日（周末取周五）。

#### 检查5：功能及时性（signal_kelly 口径 + 日频时效）

**5a. signal_kelly_backtest 口径**：
- curl `https://ssd.fx8.store/data/signal_kelly_backtest.json`
- 检查 quadrants 结构完整（16象限×5周期×6模式）
- 检查 `annualized_return` 字段存在且非旧 258% 口径
  - 旧口径：`total_return/单笔本金` 开方（y1 可达 258%，明显不合理）
  - 新口径：`return_pct_max_holding`（峰值资金收益率）开方（y1≈3% 合理）
  - **检查**：y1/A 的 annualized_return < 100% = OK；>100% = 旧口径 SEVERE
- **告警**：口径异常 = SEVERE（dedup-key=`signal_kelly_stale_formula`）

**5b. 日频数据时效**（check_data_integrity 的持续版）：
- overview.json date 滞后天数（交易日>1天=SEVERE）
- alert.json date 滞后天数（>2天=SEVERE）
- fund_score.json date 滞后天数（>3天=WARN）
- ad_line.json 最后日期滞后天数（>3天=SEVERE）
- **告警**：任一滞后 = SEVERE/WARN（dedup-key=`stale_{file}`）

### 3.3 轮询频率

| 检查类 | 频率 | 理由 |
|--------|------|------|
| 采集(public_fund) | 30min | 与schedule_monitor 15min错开，public_fund非核心交易数据 |
| 上传R2各前缀 | 30min | R2上传在export后触发，30min覆盖更新周期 |
| 发布push main | 30min | intraday每10min推，30min检测足够 |
| 功能稳定性P0 | 30min | 8项curl约30-60s，30min频率72h=144次≈72-144min总耗时 |
| 功能及时性 | 30min | 日频数据30min检查足够（非盘中实时） |

**总频率**：72h脚本每30分钟跑一次，72h=144次。每次约1-2分钟（8 curl + 解析）。

**与schedule_monitor不冲突**：schedule_monitor每15min（Minute=0/15/30/45），72h脚本每30min（Minute=10/40），错开不撞。

### 3.4 告警

- **复用 notify.py**：`python3 scripts/notify.py "<subject>" "<body>" --severe --from-prefix "[72h监控]" --alert-issue "72h持续监控告警" --alert-log <log_path>`
- **去重**：复用 alert_state.json 模式（72h脚本内嵌python，读写 alert_state.json），同一异常首次发 SEVERE + suppress，恢复发恢复邮件
- **Telegram**：notify.py 自动多渠道（邮件+Telegram），72h监控告警走同一链路

### 3.5 72h 后停机制

**方案**：临时 launchd plist + 脚本内超时自停

1. **launchd plist**：`com.trade.monitor-72h.plist`
   - StartCalendarInterval: Minute=10,40（每30min）
   - ExitTimeOut: 300s
   - WorkingDirectory: /Users/linhuichen/code/trade-data

2. **脚本内超时自停**：
   ```bash
   # monitor_72h.sh 开头检查
   START_FILE="/tmp/monitor-72h-start.txt"
   if [ ! -f "$START_FILE" ]; then
     date '+%Y-%m-%d %H:%M:%S' > "$START_FILE"
   fi
   START_TIME=$(cat "$START_FILE")
   # 超过72h(259200s)自动exit
   ELAPSED=$(python3 -c "from datetime import datetime; print(int((datetime.now()-datetime.strptime('$START_TIME','%Y-%m-%d %H:%M:%S')).total_seconds()))")
   if [ "$ELAPSED" -gt 259200 ]; then
     echo "[72h监控] 已运行${ELAPSED}s超72h，自动停止" >> data/logs/monitor_72h.log
     launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.trade.monitor-72h.plist 2>/dev/null
     rm -f "$START_FILE"
     exit 0
   fi
   ```

3. **手动提前停**：`launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.trade.monitor-72h.plist`

4. **72h后清理**：脚本自停后，主控确认 `launchctl list | grep monitor-72h` 无输出 + 删除 plist 文件

---

## 四、实施步骤

### 步骤1：写 scripts/monitor_72h.sh

- bash 脚本 + python heredoc（同 schedule_monitor.sh 模式）
- 5类检查项（3.2节）
- alert_state.json 去重（key前缀 `72h_` 避免与 schedule_monitor 冲突）
- notify.py 告警
- 72h超时自停
- heartbeat 写 `/tmp/monitor-72h-heartbeat.txt`

### 步骤2：写 com.trade.monitor-72h.plist

- StartCalendarInterval: Minute=10,40
- ExitTimeOut: 300s
- WorkingDirectory: /Users/linhuichen/code/trade-data
- EnvironmentVariables: REPO/GIT_REPO（同 schedule-monitor.plist）

### 步骤3：加载 + 验证

```bash
# 加载
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.trade.monitor-72h.plist
# 验证加载
launchctl list | grep monitor-72h
# 手动跑一次验证
bash /Users/linhuichen/code/trade-data/scripts/monitor_72h.sh
# 查日志
tail -20 /Users/linhuichen/code/trade-data/data/logs/monitor_72h.log
```

### 步骤4：72h后清理

```bash
# 脚本自停后确认
launchctl list | grep monitor-72h  # 应无输出
# 删 plist
rm ~/Library/LaunchAgents/com.trade.monitor-72h.plist
# 删 start file
rm /tmp/monitor-72h-start.txt
# 查 alert_state.json 清理 72h_ 前缀 key
```

### 步骤5：主控 cron 补充（可选）

- 主控 Claude Code 设 cron 每30min 查 `/tmp/monitor-72h-heartbeat.txt` mtime
- >60min 未更新 = 72h脚本可能挂了，SendMessage to main 提示
- 或查 `data/logs/monitor_72h.log` 最近运行时间

---

## 五、监控全景图（72h期间）

```
┌─────────────────────────────────────────────────────────┐
│  72h 持续监控全景                                         │
├──────────────┬──────────┬───────────────────────────────┤
│ 监控层        │ 频率     │ 覆盖项                         │
├──────────────┼──────────┼───────────────────────────────┤
│ schedule_     │ 15min    │ 9任务漏跑/退出/log异常/耗时    │
│ monitor.sh    │ (0/15/   │ launchctl加载/ETF耗时          │
│ (现有,不动)   │  30/45)  │ overview时效(Worker+R2)        │
├──────────────┼──────────┼───────────────────────────────┤
│ self_heal.sh  │ 15min    │ force重跑失败任务              │
│ (现有,不动)   │ (7/22/   │ retry_failed_metrics           │
│               │  37/52)  │                               │
├──────────────┼──────────┼───────────────────────────────┤
│ monitor_72h   │ 30min    │ ①public_fund系列任务          │
│ .sh           │ (10/40)  │ ②R2各前缀上传成功              │
│ (新增,临时)   │          │ ③push main+sw.js版本           │
│               │          │ ④P0功能稳定性(8项curl)         │
│               │          │ ⑤signal_kelly口径+日频时效     │
├──────────────┼──────────┼───────────────────────────────┤
│ check_data_   │ deploy时 │ 14校验函数(deploy前置阻断)     │
│ integrity.py  │ (现有)   │ (非持续,deploy时一次性)        │
├──────────────┼──────────┼───────────────────────────────┤
│ 主控 cron     │ 30min    │ 查heartbeat+进度文件           │
│ (补充)        │          │ (session层,依赖会话)           │
└──────────────┴──────────┴───────────────────────────────┘

告警链路(统一): notify.py 邮件+Telegram+alerts/latest.md
去重(统一): alert_state.json (72h脚本key前缀 72h_)
72h后停: 脚本超时自停 + launchctl bootout
```

---

## 六、注意事项

1. **§14 生产稳定性 P0**：72h脚本 Minute=10/40 与 schedule_monitor(0/15/30/45) + self_heal(7/22/37/52) 错开，不撞定时任务时点。72h脚本只读 curl + 本地文件检查，不 push main / 不写 DB / 不跑采集，零生产风险。

2. **§13 模型约束**：72h脚本是 bash+python（非 agent），不涉及图片操作。主控 cron 查 heartbeat 也不涉及图片。

3. **§8 不推 data/**：72h脚本写 `data/logs/monitor_72h.log` + `data/alert_state.json`，均不推 git（.gitignore 已忽略 data/）。

4. **告警不轰炸**：alert_state.json 去重（同一异常首次发 SEVERE + suppress），恢复发恢复邮件。72h期间同一异常最多发1次 SEVERE + 1次恢复。

5. **非交易日处理**：P0 smoke 项 date 允许=最近交易日（周末取周五），不误报。intraday/overview 时效检查非交易日跳过（schedule_monitor 已有 is_trading_day 判断，72h脚本同样处理）。

6. **R2 前缀检查代表性文件**：不检查全量（index有100+文件），只抽查代表性文件（sh-all.json等），省时且覆盖上传链路。

---

## 附：现有 launchd 定时任务完整时点表（23个plist）

| plist | 时点 | 类型 |
|-------|------|------|
| update-all | 17:50 | 交易日 |
| backfill-evening | 02:00, 16:35, 21:00 | 交易日 |
| intraday-snapshot | 30时点(09:25-15:02盘中+15:35+20:35) | 交易日 |
| futures-backfill | 20:05, 21:00 | 交易日 |
| lhb-backfill | 18:30, 19:30 | 交易日 |
| rzhb-backfill | 08:00, 19:15 | 交易日 |
| etf-national-team | 20:07, 21:30 | 交易日 |
| lab-auto | 19:00 | 交易日 |
| us-stock-morning | 05:00 | 每天 |
| self-heal | 07/22/37/52 min | 每天 |
| schedule-monitor | 00/15/30/45 min | 每天 |
| gold-night | 02:40 | 每天 |
| etf-track-index | 周日 03:30 | weekly |
| daily-summary-supplement | 20:30 | 每天 |
| public-fund-daily | 16:30, 17:00 | 交易日 |
| public-fund-estimation | 10:00, 11:00, 13:30, 14:30 | 交易日盘中 |
| public-fund-full | 22:00 | 每天 |
| public-fund-quarterly | 03:00, 04:00, 07:00 | 每天 |
| pf-stage0-manager | 每月1日 02:47 | monthly |
| pf-stage0-nav | 每周五 01:43 | weekly |
| pf-stage0-overview | 每周日 02:17 | weekly |
| pf-stage0-risk | 每月15日 02:33 | monthly |
| pf-score-daily | 16:00 | 每天 |
| pf-score-weekly | 周日 03:17 | weekly |

**注**：schedule_monitor 只监控前9个任务（update-all~us-stock-morning），public_fund 系列13个不在监控列表。72h脚本补充检查 public_fund 系列。
