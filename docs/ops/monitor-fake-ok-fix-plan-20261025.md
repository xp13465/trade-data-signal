# 监控「假 OK」修复方案（#309，2026-10-25）

> **性质**：只读调研 + 可落地修复方案，**本文件不改任何代码/配置**。
> **代码基线**：本机 `main @550da3db4`；与云上生产树 `/home/ubuntu/code/trade-data-signal` 同源，关键脚本 md5 一致：
> `gen_schedule_stats.py = 5625f774e6e20cb8995a8e2a4de26b0a`、`schedule_monitor.sh = 0754cc359ca84ed6cfb83df0559860a1`、`check_failed_units.py = 0fccafa4ed41db8ed76109619ee3bd8c`。
> **实测环境**：云上 `ubuntu@122.51.111.173`（systemd 249，开机 2026-09-13，uptime 3,640,491s），全部命令只读。
> **取数时点**：2026-10-25 16:15–16:30（文中「今天」均指 2026-10-25）。

---

## 0. 一句话结论 + 今天最新的活证据

监控说「OK 所有任务按计划执行，无漏跑，无退出失败」时，它实际只看了 **19/43** 个任务的**日志文本**；日志里没写退出码就当 0（已产出的 3,986 条结束行里 1,340 条 = 33.6% 没写），systemd 明明记着失败也不读。

**今天 16:15:01 的同一轮日志（原文）**：

```
[196] 云上 unit 异常(巡检已处理: 告警发出或按设计静默, 交付结果见下轮 rc): [INFO] ...
CHECK_FAILED_UNITS_FAIL(1 项): 云上 failed unit: trade-pf-score-daily.service, trade-s06-snapshot.service
[2026-10-25 16:15:01] OK 所有任务按计划执行，无漏跑，无退出失败
```

上一行刚列出 2 个 failed unit，下一行就说「无退出失败」。而同刻 `systemctl show trade-pf-score-daily.service` 是 `Result=timeout / ExecMainCode=2 / ExecMainStatus=15 / 16:00:01 → 16:10:01`。这不是历史遗留，是**今天仍在发生**。

**量化**（`schedule_monitor_launchd.log` 全量，4.0MB）：
- 总轮次 4,228，其中打 OK 的 3,634 轮；
- **1,253 轮 OK 与 `CHECK_FAILED_UNITS_FAIL` 出现在同一轮**；
- 这样的日子 **连续 18 天**：2026-10-08 ~ 2026-10-25，每天至少一次。

---

## 1. 根因拆解：不是一个 bug，是四条独立机制 + 一个覆盖洞

> 只修其中任何一条都还会撒谎。方案必须按「机制」逐条堵，而不是改一行文案。

### 机制 A（主因）：解析器把「日志没写退出码」默认成 0

| 证据点 | 内容 |
|---|---|
| `scripts/gen_schedule_stats.py:225` | `END_RE = re.compile(r'=== (\S+\.sh) 结束.*?' + _TS + r'(?:.*?退出码=(\d+))?')` —— 退出码组是**可选**的 |
| `scripts/gen_schedule_stats.py:1000` | `code = int(m.group(3)) if m.group(3) is not None else 0` —— **没写就是 0** |
| `scripts/gen_schedule_stats.py:1048` | `parse_etf_nt` 同款默认 0 |
| `scripts/gen_schedule_stats.py:1092` | `s, e, code, dur = pairs[-1]` —— 直接用日志推导的 code 当 `last_exit` |
| `scripts/gen_schedule_stats.py:1101-1111` | 只有「有 start 没 end」的 pending 分支才读 systemd 真实码（`real_exit = launchctl_last_exit(...)`）；**正常跑完的任务永远不读 systemd** |

**日志侧现状实测**（`data/logs/*_launchd.log`）：
- 结束行合计 **3,986** 条，其中 **1,340 条（33.6%）没有 `退出码=`**；
- 分任务：`public_fund_estimation` **169/169 全缺**、`lhb_backfill` 83/155、`etf_national_team` 82/152、`futures_backfill` 80/151。

**三源对照实锤（2026-10-20 龙虎榜）**：

| 源 | 原文 |
|---|---|
| 业务日志 | `=== lhb_backfill.sh 结束 2026-10-20 18:37:07 deploy=1 ===`（无 `退出码=`） |
| systemd（syslog） | `Oct 20 18:38:08 ... trade-lhb-backfill.service: Main process exited, code=exited, status=1/FAILURE` + `Failed with result 'exit-code'` |
| 监控日志 | `[2026-10-20 18:45:00] OK 所有任务按计划执行，无漏跑，无退出失败` |
| 监控内部 | 同轮还有 `[skip] com.trade.lhb-backfill systemd is-active=failed ... 交给 exit!=0 通道登记` 和 `CHECK_FAILED_UNITS_FAIL ... lhb-backfill.service` |

systemd 知道、脚本写了 `deploy=1`、监控自己两个通道都看到了，最后的结论仍是 OK —— 因为 `last_exit` 被默认成 0。

### 机制 B：脚本自己把失败吞掉，systemd 也看到 0

| 脚本 | 证据 | 效果 |
|---|---|---|
| `scripts/us_stock_morning.sh:75` / `:77` | `echo "=== ... 退出码=0 采集=$COLLECT_RC deploy=$DEPLOY_RC ==="` + `exit 0` | 采集/部署失败也报 0，systemd 也是 0 |
| `scripts/intraday_snapshot.sh:220` / `:249` | `echo "=== ... 退出码=0 ==="` + `exit 0` | 硬编码成功 |
| `scripts/lhb_backfill.sh:113` / `:125` | 结束行只有 `deploy=$DEPLOY_RC`，没有 `退出码=`；`exit "$DEPLOY_RC"` | systemd 有真相，日志/解析器看不到 |
| `scripts/etf_national_team_backfill.sh:148` / `:158` | 结束行只有 `deploy=$DEPLOY_RC`；`exit "$FINAL_RC"` | 同上 |

**结论**：机制 A 可以靠「读 systemd」根治；机制 B 不行 —— systemd 也被骗成 0。B 必须靠**脚本侧字段诚实化**（`退出码=`/`deploy=`/`采集=` 全写全读）。

### 机制 C：`[skip]` 把 failed 转交给一条已经瞎掉的通道

`scripts/schedule_monitor.sh:1646-1662`：
```python
if _lstate == "failed":
    if _label in _schedule_stats_labels:
        print(f"[skip] {_label} systemd is-active=failed(已加载但运行失败), 交给 exit!=0 通道登记, 不重复 not_loaded")
        continue   # ← 不登记任何告警，完全依赖 schedule_stats.last_exit
```
`_schedule_stats_labels`（`:1578-1581`）来自 stats 的 19 行。也就是说：**unit 在 systemd 里已经 failed，监控知道，但它选择不说，把命交给那条会因为机制 A 报 0 的通道。**

### 机制 D：巡检发现了失败，但不进 `alerts`，所以 OK 照打

`scripts/schedule_monitor.sh:1980-2032`：
- `check_failed_units.py` 返回 `rc=1`（发现异常且「按契约处理」）→ **只 print `[196] ...`**；
- 只有 `rc=4`（告警未送达）或其它异常 → 才 `_cfu_report(...)` 追加 `SEVERE` 进 `alerts`；
- 最终 `:3181` 的 OK 行只在 `alerts` 为空时打印 → **`[196]` 的失败对它不可见**。

这就是今天 16:15 那三行的成因，也是 1,253 轮假 OK 的主通道。

### 覆盖洞：只跟踪 19/43

- 现有白名单：`gen_schedule_stats.py:63-152`（17 个 TASKS）+ `:163-217`（2 个 EXTRA：`gen_daily_brief` / `fetch_news`）= **19**；
- 云上 **43** 个 `trade-*.timer`（`systemctl list-timers --all` 实测），**24 个完全不在检查范围**；
- 这 24 个里 **5 个连日志文件都没有**（`freeze-orphan-cleanup`、`pf-stage0-manager/nav/overview/risk`），日志口径根本铺不到；其余多数只有 `.err` 或按日期命名的散文件，不是固定 append 的标准开始/结束行。
- 结论：**19→43 只能靠 systemd 口径**，不能靠「再补几个日志解析器」。

---

## 2. 第 1 项：真实退出码从哪取（逐源实测）

### 2.1 候选数据源全表（均在本机/云上只读实测）

| # | 数据源 / 命令 | 能取到什么 | 需要权限 | 单次耗时（实测） | 失败/边界时返回什么 | 判定 |
|---|---|---|---|---|---|---|
| S1 | `systemctl show <unit> -p LoadState -p Result -p ExecMainCode -p ExecMainStatus -p ExecMainStartTimestamp -p ExecMainExitTimestamp -p ExecMainExitTimestampMonotonic -p InvocationID -p ActiveState` | 上一次调用的**权威终态**：`Result`（success/exit-code/timeout/signal/core-dump）、退出码、起止墙钟、invocation id、是否在跑 | ubuntu 普通用户即可，无需 sudo | **0.003s / unit；43 个批量 0.125s** | 真失败示例：`Result=timeout ExecMainCode=2 ExecMainStatus=15`（今天 pf-score）；`Result=exit-code code=1 status=1`（10-20 lhb）；**单位不存在：`rc=0` + `LoadState=not-found` + `Result=success` + `ExecMainStatus=0`（陷阱：不能当成功）** | **主源** |
| S2 | `systemctl list-units --state=failed --no-legend --no-pager --plain` | 当前 failed 的 service 名单（无退出码、无历史） | 普通用户 | **0.002s** | 无失败时输出空、rc=0（空≠没查） | **第二道/交叉校验** |
| S3 | `journalctl -u <unit> -n N -o json` | 只有消息文本；**没有 `_EXIT_CODE`/`EXIT_STATUS` 结构化字段**（实测 300 行只出现 `_SYSTEMD_UNIT`/`SYSLOG_IDENTIFIER`/`INVOCATION_ID`/`_SYSTEMD_INVOCATION_ID`） | ubuntu 在 `adm` 组，可读 | 0.003s | 单位不存在：`rc=0` + `-- No entries --`（同款陷阱） | **仅取证**；保留期只有 **2026-10-23 07:11 起（约 2.5 天 / 72MB）** |
| S4 | `/var/lib/systemd/timers/stamp-*.timer` 的 mtime | **上次触发时间**，重启不丢；全系统 55 个（43 trade + 12 system） | 644 root:root，所有用户可读 | `stat` 微秒级 | 文件不存在 = timer 从未触发/未落盘 | **漏跑校验辅源**（实测 mtime `2026-10-24 19:30:01.875` == `LastTriggerUSec=Sat 2026-10-24 19:30:01`，逐秒吻合） |
| S5 | `/run/systemd/units/invocation:<unit>` 符号链接 | 当前 invocation id（判「是否在跑」） | 644 链接，可读（77 条） | 微秒级 | **易失**：重启即重建 | 辅源 |
| S6 | `/var/log/syslog*`（含 .1/.2.gz/.3.gz/.4.gz） | 5 周历史：`Failed with result 'exit-code'`、`Main process exited, code=exited, status=1/FAILURE` | `adm` 组可读 | `zgrep` 0.3–1s/文件 | 轮转边界外的查不到；时间格式 `Oct 20`（非 ISO），解析脆 | **仅取证/回溯** |
| S7 | `ExecMainExitTimestampMonotonic` + `/proc/uptime` | 单调时钟退出点（如 `3640045553098`） | 普通用户 | 微秒级 | `--timestamp=unix` 在 systemd 249 **不支持**（实测 `Invalid value: unix`）；跨重启不可比 | 不建议直接用；优先 S1 的墙钟 `ExecMainExitTimestamp` |
| S8 | 脚本结构化字段：`退出码=` / `deploy=` / `采集=` / `[etf_nt] daily 失败 exit=` | 任务内部子步骤的成败（systemd 看不到的那部分） | 读日志即可 | 与日志解析同价 | 33.6% 结束行没有 `退出码=`；`us_stock`/`intraday` 还硬编码 0 | **机制 B 必需** |
| S9 | 产物新鲜度（`check_s06_freshness`、`check_data_integrity`、`check_r2_consistency`） | 端到端「数据到底有没有更新」 | 既有链路 | 既有 | 已各自有告警 | 保留，不替代退出码 |

### 2.2 选型结论（直接给默认方案）

1. **主源 = S1 `systemctl show`**：唯一能同时给「成败 + 退出码 + 起止时间 + invocation」且 43 个只要 0.125s 的源；无需 sudo。
2. **必须配套两条护栏**：
   - `LoadState != loaded` 一律判「未知/未注册」，**绝不当成功**（否则拼错 unit 名 = 永久假 OK）；
   - 重启后 `ExecMain*` 会清空 → 必须把「上次已知终态」持久化（见 §7.2 W5 的 `unit_exit_ledger.json`）。
3. **漏跑用 S1 的 `NextElapseUSecRealtime` + S4**：43/43 都有 `NextElapseUSecRealtime`（实测 `empty_next=0`）；`now > next_elapse + 宽限` = timer 没按计划触发，与「任务跑了但失败」是两个维度。
4. **S3/S6 只做取证**，不进生产判定：journal 只有 2.5 天、syslog 解析脆。
5. **S8 补机制 B**：systemd 说 0 时，还要看 `deploy=`/`采集=` 子步骤字段；两者冲突要显式标 `exit_conflict=true`，而不是二选一悄悄吞掉。

> 代价核算：43 unit × S1 = 0.125s / 次；monitor 每 15 分钟一轮，预算 600s，**可忽略**；`gen_schedule_stats` 每个任务结束时也会跑一次，同样 <0.2s。

---

## 3. 第 2 项：覆盖面 19→43

### 3.1 现有数据源与白名单在哪（file:line）

| 角色 | 位置 | 内容 |
|---|---|---|
| 退出码/耗时白名单 | `scripts/gen_schedule_stats.py:63-152` | `TASKS` 17 条（update_all / backfill_evening / intraday_snapshot / futures_backfill / lhb_backfill / rzhb_backfill / us_stock_morning / etf_national_team / lab_auto / overfit_monitor / s06_snapshot / check_data_gap / r2_consistency / cloud_unit_patrol / turnover_backfill / nextday_plan / nextday_gap_check） |
| 仅异常扫描白名单 | `scripts/gen_schedule_stats.py:163-217` | `EXTRA_MARKER_SCANS` 2 条（gen_daily_brief / fetch_news），**没有标准结束行，只扫异常关键词/轮次** |
| label 映射 | `scripts/gen_schedule_stats.py:236-261` | `LABEL_MAP`（task → com.trade.*） |
| 漏跑/耗时白名单 | `scripts/schedule_monitor.sh:100-225` | `TASKS` 17 条 + 硬编码 schedules |
| 耗时阈值 | `scripts/schedule_monitor.sh:740-768` | `DUR_THRESHOLDS` |
| 加载态检查 | `scripts/schedule_monitor.sh:1556-1569` | `LAUNCHCTL_LABELS` 11 条 + self-heal（不含 monitor 自己） |
| 失败巡检 | `scripts/check_failed_units.py:256` | `systemctl list-units --state=failed`，白名单 `docs/deploy/failed-unit-allowlist.txt`（禁 `trade-*`） |
| 产出 | `static-site/data/schedule_stats.json`（list，19 行）+ R2（`push_schedule_stats.sh` / `intraday_snapshot.sh:232`） | 前端「执行统计」表读它 |

### 3.2 43 个 timer 全表（`systemctl list-timers --all` + `/etc/systemd/system/trade-*.timer` 实测，非旧清单）

> 「现状覆盖」：**有退出码** = 在 17 条 TASKS 里；**仅异常/轮次** = 在 EXTRA 里；**无** = 完全不在。
> 「当前态」= 2026-10-25 16:15 的 `Result/ExecMainStatus`。

| # | unit | OnCalendar（云上实文） | 当前态 | 现状覆盖 | 建议 | 理由 |
|---|---|---|---|---|---|---|
| 1 | trade-update-all | Mon..Sat 17:50 / Sun 22:30 | success/0 | 有退出码 | 纳入 | 收盘全量主链 |
| 2 | trade-backfill-evening | 16:35 / 21:00 / 02:00 | success/0 | 有退出码 | 纳入 | 指数补采兜底 |
| 3 | trade-intraday-snapshot | 09:25…15:35 / 20:35（30 槽） | success/0 | 有退出码 | 纳入 | 盘中快照主链 |
| 4 | trade-futures-backfill | **19:45 / 21:20** | success/0 | 有退出码（表里写 20:05/21:00，**已漂移**） | 纳入（时点改由 systemd 派生） | 期货持仓 |
| 5 | trade-lhb-backfill | **18:50 / 19:30** | success/0 | 有退出码（表里写 18:30，**已漂移**） | 纳入（同上） | 龙虎榜 |
| 6 | trade-rzhb-backfill | 08:00 | success/0 | 有退出码 | 纳入 | 两融 |
| 7 | trade-etf-national-team | 20:07 / 21:30 | success/0 | 有退出码 | 纳入 | ETF 汪汪队 |
| 8 | trade-lab-auto | 19:00 | success/0 | 有退出码 | 纳入 | 策略实验室 |
| 9 | trade-us-stock-morning | 05:00 | success/0 | 有退出码（但脚本硬编码 0，见机制 B） | 纳入 + 字段诚实化 | 美股早采 |
| 10 | trade-overfit-monitor | Mon..Fri 21:40 | success/0 | 有退出码 | 纳入 | 过拟合监控 |
| 11 | trade-s06-snapshot | Mon..Fri 20:35 | **exit-code/124**（10-23 20:35→20:58） | 有退出码 | 纳入 + 周末不静默 | S06 快照 |
| 12 | trade-check-data-gap | Mon..Fri 22:35 | success/0 | 有退出码 | 纳入 | 数据缺口检测 |
| 13 | trade-r2-consistency | 23:20 | success/0 | 有退出码 | 纳入 | 三站一致性 |
| 14 | trade-cloud-unit-patrol | 08:27 | success/0 | 有退出码 | 纳入 | 云上 unit 漂移巡检 |
| 15 | trade-turnover-backfill | Mon..Fri 21:10 | success/0 | 有退出码 | 纳入 | 换手率 |
| 16 | trade-nextday-plan | Mon..Fri 22:30 | success/0 | 有退出码 | 纳入 | 次日买入计划 |
| 17 | trade-nextday-gap-check | Mon..Fri 09:26 | success/0 | 有退出码 | 纳入 | 伪跳空剔除 |
| 18 | trade-daily-brief | 20:40 | success/0 | 仅异常/轮次（`last_exit=null`） | 纳入（补退出码） | AI 每日速递 |
| 19 | trade-fetch-news | 每小时 :01,:45 | success/0 | 仅异常/轮次（`last_exit=null`） | 纳入（补退出码） | 新闻采集 |
| 20 | trade-ab-direction-anchor | 21:15 | success/0 | **无** | 纳入 | 方向锚数据，影响前端 |
| 21 | trade-alert-weekly-review | Mon 08:20 | success/0 | **无** | 纳入 | 告警周报，失败=周报缺失 |
| 22 | trade-backup-db | 21:00 | success/0 | **无** | 纳入 | 数据库备份，失败=灾备缺口 |
| 23 | trade-brief-push | 20:45 | success/0 | **无** | 纳入 | 推送 AI 速递 |
| 24 | trade-daily-summary-supplement | 20:25 | success/0 | **无** | 纳入 | 摘要补采 |
| 25 | trade-etf-track-index | Sun 03:30 | success/0 | **无** | 纳入 | ETF 跟踪指数（周） |
| 26 | trade-fapi-daily | 18:10 | success/0 | **无** | 纳入 | fapi 日采集 |
| 27 | trade-freeze-orphan-cleanup | 21:50 | success/0 | **无**（无日志文件） | 纳入（只能 systemd 口径） | 冻结表清理 |
| 28 | trade-gold-night | 02:40 | success/0 | **无** | 纳入 | 黄金夜盘 |
| 29 | trade-kelly-intraday-rerun | 09:40 | success/0 | **无** | 纳入 | 凯利盘中重算 |
| 30 | trade-lof-track-index | Sun 04:00 | success/0 | **无** | 纳入 | LOF 跟踪指数（周） |
| 31 | trade-pf-score-daily | 16:00 | **timeout/15**（今天 16:00→16:10） | **无** | 纳入（**今天正失败的例子**） | 场外基金评分 |
| 32 | trade-pf-score-weekly | Sun 03:17 | success/0 | **无** | 纳入 | 周评分 |
| 33 | trade-pf-stage0-manager | 每月 1 日 02:47 | success/0 | **无**（无日志文件） | 纳入（只能 systemd 口径） | 基金经理底座 |
| 34 | trade-pf-stage0-nav | Fri 01:43 | success/0 | **无**（无日志文件） | 纳入（只能 systemd 口径） | 基金净值底座 |
| 35 | trade-pf-stage0-overview | Sun 02:17 | success/0 | **无**（无日志文件） | 纳入（只能 systemd 口径） | 基金基础底座 |
| 36 | trade-pf-stage0-risk | 每月 15 日 02:33 | success/0 | **无**（无日志文件） | 纳入（只能 systemd 口径） | 基金风险底座 |
| 37 | trade-public-fund-daily | 16:20 / 17:00 | success/0 | **无** | 纳入 | 公募日更 |
| 38 | trade-public-fund-estimation | 10:00 / 11:00 / 13:30 / 14:30 | success/0 | **无** | 纳入 | 盘中估值 |
| 39 | trade-public-fund-full | 22:00 | success/0 | **无** | 纳入 | 公募全量 |
| 40 | trade-public-fund-quarterly | 03:00 / 04:00 / 07:00 | success/0 | **无** | 纳入 | 季报采集 |
| 41 | trade-schedule-monitor | 每 15 分钟 :00,:15,:30,:45 | success/0 | **无** | **排除**（仍做 unit 级体检） | 自己监控自己会递归；由 heartbeat + failed-unit 通道兜底 |
| 42 | trade-self-heal | 每 15 分钟 :07,:22,:37,:52 | success/0 | **无** | **排除**（仍做 unit 级体检） | 自愈本体已有 `LAUNCHCTL_LABELS failed→SEVERE` 专用通道；入表每 15 分钟刷行会淹没业务 |
| 43 | trade-check-monitor-heartbeat | 每 15 分钟 :11,:26,:41,:56 | success/0 | **无** | **排除**（仍做 unit 级体检） | 它是看门狗；自身失败由 failed-unit 通道覆盖，入表无业务含义 |

**合计：40 纳入（17 已有 + 2 弱覆盖 + 21 新增）/ 3 排除（自监控，仍纳入 unit 级体检）= 43/43 全覆盖。**

### 3.3 两个必须写进方案的发现

1. **硬编码时点已经漂移，不能再靠人肉维护**：
   - `lhb_backfill`：本地表写 `18:30 + 19:30`，云上 unit 文件是 `18:50 + 19:30`；
   - `futures_backfill`：本地表写 `20:05 + 21:00`，云上 unit 文件是 `19:45 + 21:20`。
   继续照本地表做漏跑判定，会在错误时点报「漏跑」/漏掉真实时点。**新增的 21 个 unit 一律不硬编码 schedules，改用 `NextElapseUSecRealtime` + `LastTriggerUSec` 派生**（43/43 实测字段非空）。
2. **5 个 unit 没有任何日志文件**（`freeze-orphan-cleanup`、`pf-stage0-manager/nav/overview/risk`），日志解析路线对它们无解；只有 systemd 口径能覆盖 —— 这是「19→43 必须换源」而不是「多写几个 parser」的直接证据。

### 3.4 覆盖口径的推荐定义

- **业务/基础设施 unit**（40 个）：进 `schedule_stats.json` 表格，逐行展示 `last_run / last_exit / 源 / 耗时 / 漏跑`；
- **自监控 unit**（3 个）：不进表格，但每轮做 unit 级 `Result/ExecMainStatus/NextElapseUSecRealtime` 体检，汇总成一行 `自监控 3/3 正常`；
- 结论行必须写覆盖数：`覆盖 43/43（40 业务+基础，3 自监控）`；**本机 mac 无 systemd 时写 `仅日志口径 17/40`，不许直接说「全部正常」**。

---

## 4. 第 3 项：假 OK 的全出口（§23.3 举一反三）

> 全仓 grep 关键词：`全部正常|一切正常|无异常|无漏跑|所有任务|均正常|全绿`（排除 tests / docs / node_modules / min.js），逐个判定。

| # | 位置 | 原文 | 是否受数据源失真影响 | 说明 |
|---|---|---|---|---|
| 1 | `scripts/schedule_monitor.sh:3181` | `OK 所有任务按计划执行，无漏跑，无退出失败` | **直接受影响（核心）** | 唯一主 OK 行；`alerts` 空就打印，忽视 `[196]` 的失败 |
| 2 | `static-site/app.js:33951-33965`（`_renderScheduleStats`） | 行内 `⚠️` 判定 `r.last_exit != null && r.last_exit !== 0` | **直接受影响** | `last_exit` 被默认 0 → 前端不显 ⚠️，用户看到「正常」 |
| 3 | `scripts/self_heal.sh:297` | `OK 无需 heal 的任务（无失败/失败任务在跑/旧问题/配额已用尽）` | **间接影响** | 它靠 `schedule_stats.last_exit != 0` 选 heal 候选（`self_heal_core.py:471/520/529`），假 0 → 该 heal 的不 heal，还把这个状态叫「OK」 |
| 4 | `scripts/schedule_monitor.sh:1653` | `[skip] ... 交给 exit!=0 通道登记` | **是（帮凶文案）** | 不是结论句，但把「已 failed」转交给瞎掉的通道，是假 OK 的必经点 |
| 5 | `scripts/schedule_monitor.sh:1980` | `[196] 云上 unit 异常(巡检已处理: 告警发出或按设计静默...)` | **是（帮凶文案）** | rc=1 的「已处理」并不等于「送达」；且它不进 `alerts`，与 OK 行并存（今天 16:15 实证） |
| 6 | `scripts/monitor_72h.sh:925` | `PASS 所有检查正常（5类覆盖: 采集/R2/发布/稳定性/及时性）` | **不受本 bug 影响** | 实测无 `schedule_stats/last_exit` 依赖；5 类里 P0 smoke 是 curl 数据层。但它**也不覆盖任务退出码**，属于另一条平行链 |
| 7 | `scripts/check_monitor_heartbeat.py:74` | `[monitor-heartbeat] OK heartbeat age=...` | **不受影响（范围限定）** | 只判 monitor 心跳年龄；文案容易被当成全局 OK，建议加「(仅心跳)」前缀（小改，非必须） |
| 8 | `scripts/sensenova-proxy-healthcheck.py:232` | `心跳正常, 无异常不通知` | 不受 | 仅代理健康检查 |
| 9 | `scripts/d1_sync_state.py:311` | D1 同步状态打印 | 不受 | 单点同步 |
| 10 | `scripts/check_data_gap_alerts.py:1805` | `case B: 一切正常` | 不受 | 是 `self_test()` 的 fixture，不产出生产结论 |
| 11 | `scripts/cloud_unit_patrol_selftest.sh:33` | `造「一切正常」的沙箱布局` | 不受 | 测试 fixture |
| 12 | `static-site/app.js:34002`（`_renderFreshnessInModal`） | `✓ 全部正常` | **不受本 bug（另一套口径）** | 判的是「各数据源新鲜度」；自身有盲区（A股/港股推送 `closed/intraday` 类不计入、无日期的 EXTRA 源默认 `t1`），属独立问题，本方案只做「口径说明」不改逻辑 |
| 13 | 邮件 / 飞书（`scripts/notify.py`） | 没有「全部正常」模板 | **继承影响** | 告警正文由 `alerts` 拼装，假 OK 的后果是**该发的一封都不发**（静默），不是发错文案；飞书与邮件同体（§23.10） |

**结论**：必须同步修的是 #1、#2、#3、#4、#5；#6~#12 不受本 bug 影响（但 #7/#12 建议补范围说明）；#13 无需改模板，只要 `alerts` 真实，邮件/飞书自然正确。

---

## 5. 第 4 项：历史兼容与影响面（改 `last_exit` 语义会动到谁）

### 5.1 逐对象影响表

| 对象 | 现状（实测） | 改后 | 需要同步改？ | 处置 |
|---|---|---|---|---|
| `static-site/data/schedule_stats.json` | **list**，19 行；字段 `task/name/schedule/est_text/last_run/last_exit/last_duration_sec/log_anomaly/log_anomaly_keyword/log_anomaly_line/log_anomaly_severity/r2_skip_count`；EXTRA 行另有 `r2_round_id/round_state/round_start_ts/unit_active_state/unit_last_exit` | 40 行；新增 `unit/unit_result/unit_exit/unit_exit_ts/exit_source/exit_conflict/unit_missed/next_elapse` | **是（追加，不破坏旧字段）** | 旧消费方读旧字段不受影响；新字段灰度期允许缺失（`.get()`） |
| `data/alert_state.json` | 190 个 key；exit 键形如 `lhb_backfill|exit!=0|1`、`update_all|exit!=0|143`、`backfill_evening|exit!=0|143` | key **形状不变**，但真码变化会产生新 key / 旧 key 走恢复 | **需一次性说明，不需迁移脚本** | 旧 key（如错误的 143）在下一轮变为未 seen → 发一封 `[恢复]`（语义正确）；新 key 首报一次（当前真实 failed=2，预期首日 ≤2 封） |
| `data/alerts/alert_ledger.jsonl` | 每封实发通知一行（ts/subject/channel…），append-only | 结构不变；只是 subject 计数/正文多几行 | 否 | 无需迁移 |
| 告警分级 | 退出失败=SEVERE；耗时=SEVERE；漏跑=SEVERE | 保持；新增「systemd=0 但 `deploy!=0`」建议走 **warning 聚合**（不打 critical） | 需拍板（见 §8） | 见 §5.2 |
| 前端展示位 | `app.js:33951` 执行统计表（唯一读 `last_exit` 的前端位） | 增加 `unit_result/exit_source` 展示；⚠️ 判定改为 `(unit_exit ?? last_exit) != 0` | **是** | 改后必须走 §22：schedule_stats.json 进 `static-site/data/` + R2 上传 + purge，三处（R2 / CF / 本地）一致 |
| 邮件/飞书正文 | 由 `alerts` 列表拼装，无「正常」模板 | 正文多出任务名+source+code | 否 | 保持飞书=邮件同体（§23.10） |
| `scripts/self_heal_core.py:471/520/529` | 用 `last_exit != 0` + `last_run 24h 内` 选 heal 候选；每日配额 3 次/任务 | 变真后候选变多，可能挤占配额 | **是（行为变化，需评估）** | 建议：heal 候选增加「可自愈白名单」或按失败类型排序；至少加一条审计日志「候选来源=systemd/log」 |
| `scripts/check_failed_units.py` 的 `unit_last_exit` | 只在 EXTRA 轮次不完整判定里用（`schedule_monitor.sh:1450`） | 不受影响 | 否 | 保持 |
| `scripts/monitor_72h.sh` | 无 `schedule_stats/last_exit` 依赖（grep 实测 0 命中） | 不受影响 | 否 | 不碰 |
| 测试 | 8 个测试文件引用 `last_exit`（`test_228/232/240/245/test_log_gz_compat/test_monitor_resource_inprogress/test_selfheal_quota_verify/test_alert_denoise`） | 默认值从 0 → None/真码会让部分断言变化 | **是** | 逐个人工核对；按 L52 全量 `pytest -q scripts/tests/` |
| CI / 漂移守卫 | 无 43-unit 覆盖守卫 | 新增 registry 漂移机检 | **是** | 与 `cloud_unit_patrol` 同源（它已比对 `/etc/systemd/system/trade-*`） |

### 5.2 三个容易踩的兼容坑（必须写进实施单）

1. **`last_exit=null` 的语义是「进行中/无数据」**（`schedule_monitor.sh:609-613` 用它判 in-progress、`:779` 说 null 不算失败）。如果把「日志没写退出码」改成 null，**会把刚跑完的任务误判成进行中**。正确做法：`last_exit` 永远给数值（systemd 优先），另加 `exit_source` 标明来源；只有确实拿不到两边时才 null。
2. **`STALE_EXIT_THRESHOLD=24h` 会让周末失败静默**（`schedule_monitor.sh:572/787-800`）：s06 周五 20:58 失败，周六日 `last_run` 超 24h → 打印「旧告警已过期，等下次任务跑」，下次运行是周一 20:35（约 72h 后）。今天 16:15 日志里的 `[info] s06_snapshot ... 距今>24h` 就是这条。**完整修必须把「等下次跑」改成「按 unit 的 timer 周期判断」**（周五任务的下一次是周一，不是 24h）。
3. **去重键含退出码**（`{task}|exit!=0|{code}`）：码一变就是新 key。要保留这个形状（否则会破 `alert_state` 恢复语义），但要在上线说明里写清「首日可能出现 ≤N 封首报 + 若干封旧码恢复」。

---

## 6. 第 5 项：§5.7 三件套（依据 / 实现预期 / 证据用例）

### 6.1 依据清单（每条可复核）

| # | 依据 | 证据（file:line 或实测输出） |
|---|---|---|
| B1 | 结束行退出码是可选组，缺省=0 | `gen_schedule_stats.py:225`、`:1000`、`:1048` |
| B2 | 正常完成的路径永远不读 systemd | `gen_schedule_stats.py:1092`（`pairs[-1]`）vs `:1101-1111`（仅 pending 分支） |
| B3 | systemd 已提供现成的真码读取函数，只是没用 | `gen_schedule_stats.py:423-456` `_systemd_last_exit`（LoadState 护栏、CLD_EXITED/KILLED 映射都在） |
| B4 | 33.6% 的结束行没有 `退出码=` | 云上实测：3,986 条结束行 / 1,340 条缺失；`public_fund_estimation` 169/169、`lhb` 83/155、`etf_nt` 82/152、`futures` 80/151 |
| B5 | systemd 侧有真失败，监控仍打 OK | 2026-10-20 18:38:08 syslog `status=1/FAILURE`；18:45 监控 `OK 所有任务...`；同轮 `[skip] lhb` + `CHECK_FAILED_UNITS_FAIL` |
| B6 | 今天仍在发生 | 2026-10-25 16:15 同轮 `CHECK_FAILED_UNITS_FAIL ... pf-score-daily, s06-snapshot` 后紧接 OK；`systemctl show pf-score-daily` = `Result=timeout code=2 status=15 16:00:01→16:10:01` |
| B7 | `[skip]` 分支不登记任何告警 | `schedule_monitor.sh:1646-1662`（`continue`，无 `alerts.append`） |
| B8 | 巡检 rc=1 不进 `alerts` | `schedule_monitor.sh:1980-2032`（rc=1 仅 print；rc=4/其它才 `_cfu_report`）；`check_failed_units.py:759` 输出 `CHECK_FAILED_UNITS_FAIL(len(problems))`（注意：括号里是「问题类别数」，不是 unit 数） |
| B9 | OK 行只判 `alerts` 空 | `schedule_monitor.sh:3181`（`else` 分支） |
| B10 | 只覆盖 19/43 | `gen_schedule_stats.py:63-152`（17）+`:163-217`（2）；云上 `systemctl list-timers --all` 43 个 `trade-*.timer` |
| B11 | 5 个 unit 无日志文件，日志口径无解 | 云上 `data/logs` 实测：freeze-orphan-cleanup / pf-stage0-manager/nav/overview/risk 均 MISSING |
| B12 | 43/43 都能读 `NextElapseUSecRealtime`（漏跑可 unit 无关地判） | 云上实测 `total=43 empty_next=0`；示例 `trade-lhb-backfill.timer → Sun 2026-10-25 18:50:00` |
| B13 | systemd 读取代价可忽略 | 单 unit 0.003s；43 unit 批量 0.125s；`systemctl list-units --state=failed` 0.002s |
| B14 | not-found 陷阱真实存在 | 实测 `systemctl show trade-no-such-unit.service`：`rc=0`、`LoadState=not-found`、`Result=success`、`ExecMainStatus=0` |
| B15 | 重启后 `ExecMain*` 会丢，必须持久化 | `journalctl` 首条 2026-10-23 07:11（2.5 天）；`ExecMain*` 是运行时属性；`stamp-*.timer` 跨重启保留且 mtime==LastTrigger（实测 19:30:01.875 vs 19:30:01） |
| B16 | 硬编码时点已漂移 | lhb 本地 18:30 vs 云上 18:50；futures 本地 20:05/21:00 vs 云上 19:45/21:20 |
| B17 | 前端只有一处读 `last_exit`，但会直接误导用户 | `app.js:33951-33965`；`:34002` 是另一套新鲜度口径 |

### 6.2 实现预期（可观测 X→Y）

| # | 场景（可复现输入） | 现状输出 | 改后必须输出（逐字可断言） |
|---|---|---|---|
| X1 | 重放 2026-10-25 16:15 轮（fixture：当天 stats + `systemctl show` 快照） | `OK 所有任务按计划执行，无漏跑，无退出失败` | `2 个任务退出失败: pf-score-daily(Result=timeout, exit=124, 16:00:01→16:10:01); s06-snapshot(Result=exit-code, exit=124, 10-23 20:35:01→20:58:01); 漏跑 0; 覆盖 43/43(40 业务+基础, 3 自监控)` —— **且不得包含 `OK 所有任务`** |
| X2 | 重放 2026-10-20 18:45 轮（lhb 日志 `deploy=1`、无 `退出码=`；systemd `status=1`） | `OK 所有任务...` | `1 个任务退出失败: lhb-backfill(exit=1, 源=systemd; 日志 deploy=1 且无 退出码=, exit_conflict=true)` + `backfill_evening(exit=1)` |
| X3 | 重放 2026-10-24 21:00 轮（全绿正常轮） | `OK 所有任务...` | **仍然** `OK ... 覆盖 43/43`，且 `alerts` 为空（防「一改就全红」） |
| X4 | 前端「执行统计」表 lhb 行 | 无 ⚠️（`last_exit=0`） | `⚠️ 上次异常: exit=1（源 systemd）`，tooltip 显示 `systemctl status trade-lhb-backfill` |
| X5 | `[skip]` 场景：unit failed 但 stats 仍 0/None | 静默跳过 | `SEVERE: lhb-backfill systemd failed 但 exit 通道显示 0/未知（通道失效）` |
| X6 | 本机 mac 跑 monitor（无 systemd） | 打印 OK（基于 19 行日志） | `OK(仅日志口径, 覆盖 17/40; 本机无 systemd)` —— 不谎称 43/43 |
| X7 | 重启后首轮（ExecMain 清空、ledger 有上周五失败） | 可能静默 | 用 ledger 补位：`s06-snapshot 上次失败 exit=124（10-23 20:58，重启后尚未再跑）` |
| X8 | 新增失败首次出现（systemd 记录后下一轮） | 可能静默（日志无码） | ≤15 分钟内出现 `SEVERE`，key=`{task}|exit!=0|{code}` |
| X9 | 覆盖漂移：新增/删除一个 timer | 无人知 | registry 漂移机检 FAIL（CI）+ `cloud_unit_patrol` 告警 |

### 6.3 证据用例（独立复现，不依赖实施方口述）

> **打桩铁律（§18 L48/L50）**：所有用例一律 static-only —— 不跑任何业务脚本、不调用真 `notify.py`、不发邮件/飞书；`systemctl` 用 PATH 假二进制，日志/状态用 fixture 复制到 `/tmp` 沙箱。用例内若出现 `notify`，必须是记录调用的 stub，且断言「stub 被调用 0 次」或「只写沙箱 ledger」。

| # | 用例文件（建议路径） | 输入 | 断言（判别力） | 反向对照（必须一起跑） |
|---|---|---|---|---|
| E1 | `scripts/tests/test_309_unit_truth_20261025.py` | 7 个假 `systemctl show` 输出：success / exit-code 1 / timeout / signal / not-found / never-ran / 重启后空 | 映射表逐项相等；not-found → `(None,"missing")` 不返回 0 | 把 timeout 期望改成 0 → 用例必红 |
| E2 | `scripts/tests/test_309_gen_stats_exit_source.py` | 假日志：`结束 ... deploy=1`（无退出码）；假 systemd `status=0` | `last_exit==1`、`exit_source=="log-deploy"`、`exit_conflict==true` | 删掉 `deploy=` 字段 → 期望变为 `exit_source=="systemd"` 且 last_exit=0（证明判据真起作用） |
| E3 | `scripts/tests/test_309_ok_line_truth_20261025.py` | AST 抽取 `schedule_monitor.sh` 结论函数（不复制逻辑，沿用 `test_monitor_resource_inprogress_20261005.py` 的 `ast` 取用方式） | 输入「alerts 空 + CFU 有 failed」→ 不得输出 `OK 所有任务`；输入全绿 → 输出 OK 且带 `覆盖 43/43` | 去掉 CFU 失败输入 → OK 必须回来（防空转恒红） |
| E4 | `scripts/tests/test_309_replay_20261025.py` + `scripts/tests/fixtures/309/` | X1/X2/X3 三套 fixture（当天 stats、两份 `systemctl show` 快照、两段日志） | X1/X2 输出含对应任务名+code；X3 输出 OK；三套互不串扰 | 改 fixture 里 pf-score 的 `Result=success` → X1 变 OK（证明 X1 真依赖该字段） |
| E5 | `scripts/tests/test_309_registry_drift.py` | `docs/deploy/unit-registry.json`（43 条） vs 云上 `systemctl list-timers --all` 快照 fixture | 差集为空；每行有 `include/reason` | 从 registry 删一条 → 必红；多一条 → 必红 |
| E6 | `scripts/tests/test_309_no_false_alarm.py` | 过去 7 天全绿轮次抽样（从 `schedule_stats` 取 exit=0 且 systemd success） | 所有轮次 `alerts` 为空、OK 行出现 | 注入一条 exit=1 → 必出现 SEVERE（证明不是永远 OK） |
| E7 | 云上只读回放（人工/主控执行，非 CI） | `REPO` 指向 `/tmp/sandbox`（复制真实 logs + stats + 假 `scripts/notify.py`），PATH 前置假 `systemctl` | 输出与 X1 逐字一致；`notify` stub 调用 0 次 | 把沙箱 `systemctl` 去掉 → 输出降级为「仅日志口径 17/40」，不许 43/43 |

**执行命令（预期）**：
```bash
# 本机全量（L52：改 scripts/ 任何源码必须跑全量）
pytest -q scripts/tests/ -k "309 or unit_truth or ok_line"
pytest -q scripts/tests/
# 云上只读回放（避开 :00/:15/:30/:45 监控轮）
REPO=/tmp/sandbox309 bash scripts/schedule_monitor.sh   # 需 fixture 化 notify + systemctl
```
> 注意：E7 的 `schedule_monitor.sh` 会 `gen_schedule_stats.py`（沙箱内可跑，不碰生产）；必须保证 `REPO` 沙箱里的 `scripts/notify.py` 是 stub、`ALERT_LEDGER_DISABLE=1`、且时间避开真实监控轮（§14）。

---

## 7. 第 6 项：分级与建议

### 7.1 最小修（只让结论不撒谎）

**目标**：不改覆盖范围、不改业务脚本，只保证「监控的结论句不再与它自己看到的事实矛盾」。

**改动面（约 1 人日）**：

| 文件 | 改动 | 行数量级 |
|---|---|---|
| `scripts/gen_schedule_stats.py` | ① 17 条 TASKS：`last_exit` 优先取 systemd（`_systemd_last_exit` 已有，扩展读 `Result/ExecMainExitTimestamp/InvocationID`）；② `parse_standard/parse_etf_nt` 缺 `退出码=` 时读 `deploy=`/`采集=`，仍无则 `exit_source="unknown"`（**不再默认 0**）；③ 输出 `exit_source/exit_conflict/unit_result` | ~80 行 |
| `scripts/schedule_monitor.sh` | ① 退出通道同时消费 `unit_exit`；② `[skip]` 分支：unit failed 且 stats 显示 0/未知 → 直接 SEVERE（杀机制 C）；③ OK 行：`alerts` 空但 `CHECK_FAILED_UNITS_FAIL` 出现 → 打 `OK(除 N 个云上 unit failed, 详见 [196])`（**不允许再打「无退出失败」**）；④ 覆盖数写进结论（`覆盖 19/43`） | ~40 行 |
| 测试 | E1/E2/E3 + 全量 pytest | ~250 行 |

**明确不做**：24 个未覆盖 unit、账本持久化、前端字段、脚本侧硬编码 0。

**风险**：低-中。主要风险是「历史 8 个测试对 `last_exit` 默认 0 的断言」需要同步改；以及首日多出几封首报。

**回滚**：`MONITOR_EXIT_SOURCE=log`（新增开关，默认 systemd）一行切回旧口径；或直接 `git revert` 单 commit。

**残留问题（必须如实承认）**：
- 24 个 unit 仍然「根本没跑也没人知」；
- `us_stock_morning` / `intraday_snapshot` 这类**脚本自己写 0** 的失败，systemd 也看不见；
- 周末 s06 这类跨 24h 的失败仍会被「旧告警已过期」静默；
- 前端仍可能因为 `last_exit=0` 不显 ⚠️（只是监控日志不再撒谎）。

### 7.2 完整修（43 timer 全覆盖 + 假 OK 全出口）

**目标**：监控结论与 systemd/脚本/产物三层事实一致；43/43 无盲区；重启、周末、脚本吞异常都不再产生假 OK。

**工作流（约 4 人日，按依赖排序）**：

| W | 内容 | 关键设计 | 产出 |
|---|---|---|---|
| W1 | 新模块 `scripts/unit_truth.py`（单一事实源） | `read_unit_states(units)`：一次 `systemctl show` 读 9 属性；`derive_exit_code()`：`Result=timeout→124`、`exit-code→ExecMainStatus`、`signal/core-dump→128+sig`、`success→0`、`LoadState!=loaded→None("missing")`、never-ran→None；`timer_health()`：`now > NextElapseUSecRealtime + 10min` = missed | 纯函数 + 单测（E1） |
| W2 | `gen_schedule_stats.py` 扩到 40 行 | ① `UNIT_REGISTRY` 40 条（含 `unit/kind/include/display`）；② 每行合并 systemd 真值（invocation 时间 ≥ 日志 start 才采信，防重启后旧值）；③ 日志子步骤字段（`deploy=/采集=`）作为 B 类补充；④ `unit_missed/next_elapse` | stats 40 行 + 覆盖字段 |
| W3 | `schedule_monitor.sh` 三条新通道 | ① `unit_exit!=0`（与 last_exit 去重合并）；② `unit_missed`（key `{task}|unit_missed`）；③ `[skip]` 兜底 SEVERE；④ OK 行合成：`alerts + CFU failed + unknown_exit + missed` 全空才算 OK，并写覆盖数 | 不再假 OK |
| W4 | 脚本侧退出码诚实化 | 统一结束行格式 `=== <script> 结束 <ts> 退出码=<rc> deploy=<rc> ===`；重点：`us_stock_morning.sh:75-77`（deploy 失败不阻塞但必须写进字段）、`intraday_snapshot.sh:220`（改真 rc）、`lhb_backfill.sh:113`、`etf_national_team_backfill.sh:148`；加 CI lint「所有 `=== *.sh 结束` 必须含 `退出码=`」 | 机制 B 根治 |
| W5 | 持久化 `data/unit_exit_ledger.json` | monitor 单写者（避免 5 个脚本并发）；原子写（tmp+rename+flock）；字段 `{unit, invocation_id, result, code, start, exit, consecutive, first_bad_at}`；重启后 `ExecMain*` 空 → 用 ledger + `LastTriggerUSec` 补位 | 重启/跨天不丢 |
| W6 | 前端 + §22 | `app.js:33951` 用 `unit_exit ?? last_exit`；显示 `Result`/源；`schedule_stats.json` 走 `push_schedule_stats.sh` + R2 + purge；三处一致核验 | 用户侧不误导 |
| W7 | 测试 + CI + 灰度 | E1–E7；registry 漂移机检（与 `cloud_unit_patrol` 同源）；`MONITOR_EXIT_SOURCE` 开关；上线首日观察（≤2 封首报预期） | 可验收、可回滚 |

**风险**：中。风险点：① 40 行 stats 让前端/R2 体积增大（19→40 行，约 +8KB，可忽略）；② 首日告警量（当前真实 failed=2，但新增 21 unit 可能有历史残留 failed → 上线前先跑一次 `systemctl list-units --state=failed` 盘点，当前只有 2 个 trade failed）；③ `self_heal` 配额被新候选挤占；④ 40 行写盘/上传的原子性（沿用既有 `gen_schedule_stats` 原子写 + R2 上传）。

**回滚**：三层开关 —— ① `MONITOR_EXIT_SOURCE=log|systemd`；② `UNIT_REGISTRY` 每行 `include:false` 即退回 19 行；③ `git revert` 单 commit；ledger 可直接删（无迁移、无 DB）。

### 7.3 两档对比

| 维度 | 最小修 | 完整修 |
|---|---|---|
| 改动面 | 2 个脚本 + 测试（~370 行） | 3 个脚本 + 1 新模块 + 1 新账本 + 前端 + CI（~1,200 行） |
| 覆盖面 | 19/43（24 个仍盲） | 43/43（40 业务+基础，3 自监控） |
| 机制 A（日志默认 0） | 修 | 修 |
| 机制 B（脚本吞失败） | 部分（只读 `deploy=`，不改脚本） | 修（脚本字段诚实化 + lint） |
| 机制 C（`[skip]` 转交） | 修（兜底 SEVERE） | 修 |
| 机制 D（巡检不进 alerts） | 修（OK 行加限定） | 修（合成结论 + 去重） |
| 重启/周末 | 不解决 | 解决（ledger + 按 timer 周期判 stale） |
| 前端误导 | 不解决 | 解决 |
| 工期 | ~1 人日 | ~4 人日 |
| 风险 | 低-中 | 中（可分层回滚） |
| 回滚 | 1 个开关/revert | 3 层开关/revert |

### 7.4 推荐：**完整修**，但按「先止血、后根治」两阶段交付

**理由（按重要性）**：

1. **假 OK 是「信任级」故障，不是文案问题**：只要监控能在 unit 明确 failed 时打 OK（今天 16:15 仍在发生），所有告警的可信度都会被折价 —— 用户/agent 会学会忽略监控。这类问题必须一次修到「结论=事实」。
2. **19→43 的边际成本极低**：systemd 43 个 unit 批量 0.125s，且 5 个 unit 根本没有日志文件（日志路线无解）；这是**唯一**能补齐覆盖的方法，没有第二个选项。
3. **机制 B 不修，systemd 也会被骗**：`us_stock_morning` 部署失败仍 `exit 0`；只做监控侧，会得到「Systemd 说成功、实际推送没发出去」的新一层假 OK。
4. **改动风险可控**：全部是读 systemd + 追加字段 + 加开关，不动评分/回测/交易逻辑；回滚三层都简单。

**交付顺序（建议）**：
- **P0（当天）**：最小修的 ①②③ —— 让 OK 行先停止撒谎（今天 16:15 这种行必须消失）；
- **P1（本周内）**：W1–W3 + W5（43 覆盖 + ledger + 漏跑）；
- **P2（一周内）**：W4 + W6 + W7（脚本诚实化 + 前端 + CI/灰度）；
- **观察锚点（上线后 7 天）**：每日统计「OK 轮次中 CFU 非空的次数」= 0，且「新增首报 ≤ 每日 5 封」，否则回退。

### 7.5 为什么不是别的方案（备选否掉的理由）

| 备选 | 否掉理由 |
|---|---|
| 只把 `[skip]` 改掉（只修 C） | exit 通道仍读假 0，unit 照样「转交后静默」；B5 的 10-20 案例不会消失 |
| 只用 `systemctl --failed` 当唯一真相 | 只有「当前 failed」，无退出码/无历史/无法区分新老；且 `check_failed_units` 本身在 10-19~10-22 有过 62.5h 黑洞（评估报告 §A4），单点不可靠 |
| 只加日志解析器覆盖 24 个 unit | 5 个 unit 无日志文件；其余日志格式各异（`.err`、按日期命名）；工作量大且必然漂移 |
| 用 `journalctl` 当主源 | 无结构化退出码字段（实测）；只保 2.5 天；跨轮询重建历史不可行 |
| 直接把 `check_failed_units` 的 rc=1 全量塞进 `alerts` | 会与它自己的 notify 通道双响（它已经发过一封），造成告警轰炸；正确做法是「结论层合成 + 通道层去重」 |

---

## 8. 待用户拍板（最关键的两个）

### 拍板点 1：脚本侧「失败」的口径与分级
- **问题**：`deploy` 失败但采集成功（`us_stock_morning` 现状）算不算「任务失败」？如果算，是 **SEVERE（进主告警邮件）** 还是 **warning（日摘要聚合）**？
- **选项**：
  - A（推荐）：`采集=0 + deploy!=0` → **warning 聚合**（不进 critical）；`采集!=0` → SEVERE。理由：部署失败通常可被下一次 deploy 兜底，且 17:50 全量每天都会补；全按 critical 会重演 10-15「单日 6 封」的告警轰炸。
  - B：一律 SEVERE。更响亮，但会把现有 critical 日均抬高（需要先估量：近 30 天 deploy 失败集中在 16-23 点，71% 失败与 R2 锁相关）。
- **影响**：决定机制 B 的告警量和 `self_heal` 是否要把 deploy 失败纳入自愈候选。

### 拍板点 2：43 覆盖的范围与首日告警量
- **问题**：3 个自监控 unit（`schedule-monitor` / `self-heal` / `check-monitor-heartbeat`）是否排除出「执行统计」表（仍做 unit 级体检）？新增 21 个 unit 首日可能出现的历史残留 failed，是否接受一次性首报？
- **选项**：
  - A（推荐）：3 个自监控排除出表、保留 unit 级体检；21 个全部纳入；首日允许 ≤5 封首报（当前实测只有 2 个 trade failed，风险很低）。
  - B：43 个全部进表（包括 monitor 自己）。更「全」，但会每 15 分钟刷 3 行、且 monitor 监控自己存在递归语义问题。
- **影响**：决定 `UNIT_REGISTRY` 的 `include` 字段和前端表格行数（40 vs 43）。

---

## 9. 复现命令附录（全部只读，可逐条复核）

```bash
# 1) 43 个 timer 全集 + 当前终态（云上）
systemctl list-timers --all --no-legend --no-pager --plain | awk '{print $(NF-1)}' | grep '^trade-'
systemctl show trade-pf-score-daily.service -p Result -p ExecMainCode -p ExecMainStatus \
  -p ExecMainStartTimestamp -p ExecMainExitTimestamp -p InvocationID -p LoadState -p ActiveState

# 2) not-found 陷阱
systemctl show trade-no-such-unit.service -p LoadState -p Result -p ExecMainStatus   # rc=0, not-found, success, 0

# 3) 43 unit 批量耗时
time (for s in $(systemctl list-units 'trade-*.service' --all --no-legend --no-pager --plain | awk '{print $1}'); do
  systemctl show "$s" -p Result -p ExecMainStatus -p ExecMainExitTimestamp >/dev/null; done)   # ~0.125s

# 4) journal 保留期与结构化字段
journalctl --no-pager -o short-iso | head -1                     # 2026-10-23T07:11:50（约 2.5 天）
journalctl -u trade-lhb-backfill.service -n 300 -o json | python3 -c '...'  # 无 _EXIT_CODE/EXIT_STATUS

# 5) 漏跑判据可行性
for t in $(systemctl list-timers --all --no-legend --no-pager --plain | awk '{print $(NF-1)}' | grep '^trade-'); do
  systemctl show "$t" -p NextElapseUSecRealtime --value; done | grep -c .   # 43，无空值

# 6) 假 OK 量化（云上）
awk '/^\[[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}\]/ {
       if (tick>0) { n++; if (ok) o++; if (ok&&cfu) { bad++; d[day]=1 } }
       tick++; ok=0; cfu=0; day=substr($0,2,10);
       if ($0 ~ /OK 所有任务按计划执行/) ok=1; next }
     /CHECK_FAILED_UNITS_FAIL/ { cfu=1 }
     END { if (tick>0) { n++; if (ok) o++; if (ok&&cfu) {bad++; d[day]=1} }
           print "ticks="n, "ok="o, "ok_with_cfu="bad;
           for (k in d) nd++; print "days="nd }' \
  /home/ubuntu/code/trade-data/data/logs/schedule_monitor_launchd.log
# 实测：ticks=4228 ok=3634 ok_with_cfu=1253 days=18（2026-10-08 ~ 2026-10-25）

# 7) 结束行缺退出码比例
cd /home/ubuntu/code/trade-data/data/logs
grep -ha '=== .*\.sh 结束' *_launchd.log | wc -l                       # 3986
grep -ha '=== .*\.sh 结束' *_launchd.log | grep -v '退出码=' | wc -l    # 1340（33.6%）

# 8) 10-20 lhb 三源对照
grep -a 'lhb_backfill.sh 结束 2026-10-20' lhb_backfill_launchd.log
grep -h 'trade-lhb-backfill' /var/log/syslog.1 | grep '^Oct 20'       # status=1/FAILURE
sed -n '30055,30072p' schedule_monitor_launchd.log                     # 18:45 OK 原文

# 9) 今天 16:15 的三行矛盾
grep -an '^\[2026-10-25 16:15:01\]' schedule_monitor_launchd.log | head -1
# 取上一行：CHECK_FAILED_UNITS_FAIL(1 项): ... pf-score-daily.service, s06-snapshot.service
```

---

## 10. 诚实标注（本次调研没做到 / 不可断言的部分）

1. **历史 systemd 真值只能回溯 5 周**（syslog）：再早的 unit 成败无法逐条核对；`journal` 只有 2.5 天。10-20 的 lhb 能实证，纯属 syslog 还在保留期内。
2. **「1,253 轮 OK 与 CFU 同轮」不等于「1,253 次真漏报」**：其中有的是已经告警过、被 suppress 的持续失败；它证明的是「OK 行完全无视 CFU 结果」，不是每一次都漏了通知。真正漏没漏要逐轮看 `alert_state`/台账，本次未逐轮展开。
3. **`CHECK_FAILED_UNITS_FAIL(1 项)` 的「1」是问题类别数，不是 unit 数**（`check_failed_units.py:759` 用 `len(problems)`）；今天列了 2 个 unit 但括号写 1，不是计数 bug，是口径容易误读。
4. **43 unit 的当前态是 2026-10-25 16:15 的快照**：只有 2 个 failed（pf-score-daily、s06-snapshot）；历史失败分布见评估报告 §B，不在本次重算。
5. **未验证「脚本退出码诚实化」后的告警量**：`deploy!=0` 的历史频次未逐日统计（评估报告只说 31 天 480 个 deploy 日志、失败集中在 16-23 点），首日告警量是估算，不是实测。
6. **未做真实告警/邮件/飞书演练**（按铁律 §18 L48 禁止）：所有「改后会发 N 封」都是逻辑推演，证据用例全部用 stub。
7. **本机 mac 无 systemd**：所有 systemd 实测均在云上只读完成；本机只能跑 fixture/单测，不能复现 43 覆盖。

---

## 11. 事故记录(2026-10-26 补录):漏跑检测 NameError,静默 26 天

### 11.1 时间线

| 时间 | 事件 |
|---|---|
| 2026-09-29 | `3ae347e51` 给「漏跑」加降噪:单轮先 `pending`、连续 2 轮才 `SEVERE`。两个阈值常量被追加在 heredoc **模块尾部**(`schedule_monitor.sh:1444` `R2_LAG_CONTINUOUS_THRESHOLD = 3`、`:1445` `MISSED_CONTINUOUS_THRESHOLD = 2`),而漏跑循环在 `:557/:581` 已经使用它们 |
| 2026-09-29 ~ 10-25 | 只要某任务进入「漏跑」判定(真漏跑或日志解析假触发),`:557` 即 `NameError`,整个内嵌 Python 模块中止。生产共 **22 次**(13 次真漏跑 / 9 次假触发),因脚本末尾 `exit 0`,systemd 全程 `success` |
| 2026-10-26 | 本次「假 OK 出口」排查中,顺着「OK 行凭什么说无漏跑」追到该分支,发现检测链本身 26 天没跑通过 |

### 11.2 影响(比「漏跑没告警」更大)

- 漏跑循环位于内嵌 Python 的**前段**(模块级 `for` 循环);它一抛异常,后面同轮的全部模块级检查(退出码告警、unit 巡检结果归集、恢复/抑制逻辑)以及**末尾的告警发送**都没执行 ⇒ 这 22 轮是**整轮失明**,不是少一类告警。
- 22 轮之外正常:异常只在「有任务被判定漏跑」的轮次触发,所以平时监控看起来一切正常 —— 这正是它能藏 26 天的原因。
- 本形态**不在 §4 的 grep 表里**:§4 列的是「打印 OK 结论但结论失真」;本条是**连结论都不打印的静默死亡**(外加退出码 0)。归入机制 B(脚本自己把失败吞掉)的延伸出口。

### 11.3 根因(三层,缺一层都不会静默)

1. **顺序**:内嵌 heredoc 是普通 Python 模块,模块级语句顺序执行;常量定义在引用之后 ⇒ 首次命中即 NameError。
2. **吞错**:`set -uo pipefail`(无 `-e`)+ 末尾 `exit 0`(原注释:「总是 exit 0:告警已发邮件,避免 launchd 因非0退出重试」)⇒ Python 非 0 退出不影响 bash,unit 恒 success,日志里只剩 traceback。
3. **测试洞**:既有用例都是「AST 抽片段 + 手工把常量注入命名空间」,缺失的常量被测试自己补齐 ⇒ 代码再错也绿。没有一条用例按源码顺序执行真实前缀。

### 11.4 修法(同批 5 个 commit,feat 分支 `feat/monitor-nameerror-fix-20261026`)

| commit | 内容 |
|---|---|
| `b2853a0d6` | 阈值段整体上移到 `SELF_HEAL_THRESHOLD` 之后(定义 528/529;注释同行并补「必须在引用之前定义」);引用点全部复核:missed 577/601、R2_LAG 3419/3423/3429/3432/3438 |
| `3f99289c3` | 时点表与云上 systemd 实文对齐:futures `20:05/21:00 → 19:45/21:20`、lhb `18:30/19:30 → 18:50/19:30`(`schedule_monitor.sh:134-139`、`gen_schedule_stats.py:72,74`、两个 backfill 脚本头注释) |
| `7b66d1401` | 新增 `scripts/check_embedded_py_name_order.py`(扫 `.sh` 内嵌 Python 模块级先使用后定义;非 Python heredoc / 星号导入 / exec 必须显式允许名单)+ 15 条自测 + 机检登记表一行 |
| `2852ff578` | 新增 `scripts/tests/test_monitor_missed_run_20261026.py`:命名空间从真实源码按序 exec,**不注入任何常量**;覆盖首轮 pending / 第 2 轮 SEVERE / 已 active 不重复,并用「常量搬回尾部必须 NameError」钉判别力 |
| `2c0de0c8a` | #309 固化样本同步两条 `schedule` 文案(逐位对账不放宽),修掉任务 2 引起的 CI 红 |

### 11.5 验收(§5.7 三件套对照)

- **依据**:事故引入点 `3ae347e51` + 崩溃 22 次生产证据(任务书已核实);云上 timer 实文 `systemctl cat trade-futures-backfill.timer trade-lhb-backfill.timer`(只读复核两次,与任务表一致)。
- **实现预期**:①漏跑分支首轮打印 `[missed-buffer] … 连续1/2 轮` 且 state=pending,不抛异常;②连续第 2 轮出 1 条 `SEVERE: <task> 漏跑`;③全仓内嵌 Python「先使用后定义」= 0 条;④全量 pytest 不倒退。
- **证据**:上述三条用例实跑通过;判别力两处变异(常量搬回尾部)分别让守卫与用例变红;守卫 `--root .` 0 命中;全量 `pytest -q scripts/tests/` = **1644 passed, 2 skipped**(基线 1624 + 新增 20 条)。

### 11.6 本次未覆盖(另立任务,不在本批动手)

1. **monitor 自身异常的外层可见性**:本批只修根因 + 加静态守卫;「某轮 monitor 内嵌块异常 ⇒ 至少留一条可见告警」尚未做(与本文 §4 机制 B 同族,建议并入「脚本退出码诚实化」批)。
2. **同一时点表的其他展示位仍有旧值**(均为同一事实副本,改它们需要产品口径决定展示哪个值):
   - **已处理(2026-10-26,`feat/monitor-nameerror-fix-20261026`)**:`static-site/app.js:33882,33884`「更新时间表」弹窗里 futures/lhb 两行**硬编码**时点已对齐云上 systemd 实文与 `scripts/gen_schedule_stats.py:72,74` —— lhb `18:30 + 19:30(兜底)` → `18:50 + 19:30(兜底)`;futures `20:05 + 21:00(兜底)` → `19:45 + 21:20(兜底)`(同行说明里的「21:00二次槽」同步改为「21:20二次槽」,否则同一行内时点自相矛盾)。依据:同一弹窗另一张 `#schedule-stats-table` 由 `schedule_stats.json` 渲染、已是新值,同屏两表不能互相打脸(§22);`app.min.js` 同 commit 重建。
   - **仍待办**:`static-site/app.js` 该硬编码表其余行(盘中30分钟/15:33/20:00/23:00 等)与云上不符,需产品口径决定展示哪个值;`docs/data-sources.md:273,274,292`、`docs/data-dictionary.md:619`、`docs/site-deployment.md:632,635,657,658`、`docs/signal-finalize-time.md:55,72,77,103,113`、`docs/72h-monitor-plan.md:35,345,346` 仍是旧值(5 份活文档,含 futures `20:05/21:00`、lhb `18:30/19:30`)。

---

## 附：本次调研的关键原始数据（备查）

- 43 个 timer 全部 `Enabled`，43 个对应 service 全部 `Type=oneshot`，`ExecStart` 全部指向 `/home/ubuntu/code/trade-data/scripts/*`（`readlink -f` → `trade-data-signal`）。
- 当前 failed：`trade-pf-score-daily.service`（`Result=timeout, ExecMainCode=2, ExecMainStatus=15, 2026-10-25 16:00:01 → 16:10:01, InvocationID=0b79697870a94811895544a8c5b03684`）；`trade-s06-snapshot.service`（`Result=exit-code, 124, 2026-10-23 20:35:01 → 20:58:01`）。
- `schedule_stats.json` 当前 19 行；唯一非零 `s06_snapshot last_exit=124`；`gen_daily_brief` 有 `log_anomaly=true / R2_UPLOAD_TIMEOUT / critical`（已持续 112h，按设计每 24h 提醒一次）。
- `alert_state.json` 当前 190 key；exit 类 key 示例：`lhb_backfill|exit!=0|1`、`etf_national_team|exit!=0|1`、`update_all|exit!=0|143`、`backfill_evening|exit!=0|143`。
- 云上 uptime 3,640,491s（约 42 天），`ExecMain*` 在重启前可靠；重启后必须靠 ledger。
