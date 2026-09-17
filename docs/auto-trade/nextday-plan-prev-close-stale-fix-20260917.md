# 次日买入计划「买入价用前日收盘价」时序倒挂根治(2026-09-17)

## 一、背景与根因

次日买入计划生成器 `scripts/nextday_plan_generator.py` 的 `prev_close` 字段 = 该 ETF 信号日 T
的收盘价(挂单价上限)。它由 `_prev_close(db, etf_code, T)` 取 `etf_daily` 中 `date <= T` 最近一天的
close。当 T 日收盘价还没入库时,SQL 静默退化为 T-1(前一日)收盘价 → 次日买入价用了前日收盘价(时序倒挂)。

实测根因链:
1. `etf_national_team` 20:07 采集 sina/mootdx OHLC 源对当日数据可能返空,21:47 第二批 backfill 才补上 T 日收盘价;
2. nextday_plan 原定 20:55 跑,此时 etf_daily 尚无 T 日收盘 → `_prev_close` 取前日价;
3. #38 就绪 gate `_plan_stale_codes` 已能逐只拦截「最新日 < T」,但 `NEXTDAY_PLAN_FORCE=1` 分支仍 fail-open
   继续用前日价 → 「门装了没关死」。

## 二、方案(双保险,一步到位)

1. **生成时点 20:55 → 22:30**:晚于 21:47 第二批 backfill,确保 etf_daily 当日收盘价已入库(治本);
2. **stale 检测改 fail-closed**:移除 `NEXTDAY_PLAN_FORCE=1` 强制继续分支,缺当日收盘价(最新日 < T)时
   阻塞(return 2)+ `notify.py --severe` 告警,不再产出用前日价的误导性计划(兜底)。

## 三、改动清单

| 文件 | 改动 |
|---|---|
| `scripts/nextday_plan_generator.py` | stale 分支移除 FORCE bypass;`_severe_alert` + `return 2`(fail-closed);docstring/注释同步 |
| `docs/auto-trade/com.trade.nextday-plan.plist` | StartCalendarInterval 5 个工作日 20:55 → 22:30 + 注释重写时点依据 |
| `scripts/nextday_plan.sh` | 头部注释 20:55 → 22:30 + 时点依据重写 |
| `scripts/gen_schedule_stats.py` | TASKS 表 nextday_plan schedule "20:55" → "22:30"(前端「数据更新规则」弹窗展示源) |
| `scripts/schedule_monitor.sh` | TASKS nextday_plan `schedules: ["20:55"]` → `["22:30"]`(漏跑检查时点) |
| `scripts/check_data_integrity.py` | 注释 20:55 → 22:30(周一 deploy 容忍口径说明) |
| `docs/deploy/systemd-units-20260912.md` | 云上 `trade-nextday-plan.timer` OnCalendar 20:55 → 22:30 |
| `docs/deploy/migration-inventory-20260912.md` | 迁移清单 #14 nextday-plan 20:55 → 22:30 |

## 四、自测结果

- `python3 -m py_compile` 三文件(nextday_plan_generator/gen_schedule_stats/check_data_integrity)全过;
- `bash -n` 两文件(nextday_plan.sh/schedule_monitor.sh)全过;
- `plutil -lint` plist OK,`plutil -p` 确认 5 个 Weekday 全部 Hour=22 Minute=30;
- **逻辑 dry-run(单元)**:构造 etf_daily 停在 20260915、T=20260916 的场景,
  `_prev_close` 退回 20260915(证明前日价退化根因),`_plan_stale_codes` 正确标 `['159880','513080']` stale;
- **main() stale 分支 dry-run(monkeypatch)**:stale 时 `main()` 返回码 = 2 + 发 severe 告警
  「次日买入计划数据未就绪(缺当日收盘价)」,不再 FORCE 继续 —— fail-closed 生效。
- `grep` 残留检查:`NEXTDAY_PLAN_FORCE` 仅剩注释(说明移除),代码零残留;scripts/docs/deploy 下
  无遗留「20:55」时点(仅 nextday_plan.sh 注释「20:55 后移到 22:30」的历史说明)。

## 五、§23.2 修 bug 三铁律自查

- **同类错误面清单**:`_prev_close` 全仓仅 2 处调用(`_build_plan_for_day` L500/L502,同一 ETF 同日取价,
  同属 prev_close/sig_close);无其他消费者。`NEXTDAY_PLAN_FORCE` 全仓仅生成器一处。同文件其他
  fail-open(s06 快照缺行放行)是与前端降级契约一致的设计,非本次 bug 面,不动。→ 单点根因修,未逐文件打补丁。
- **自测覆盖**:语法 + 逻辑 dry-run + main 分支 + grep 残留,逐项过。
- **排查同类**:本 bug 的「前日价 fallback」模式只在 nextday_plan 生成器存在;首页 `etf_close`/回测
  买卖价走的是别源(冻结表/board_etf_map 注入),不受 etf_daily 当日缺价影响。

## 六、§23.3 举一反三自查

- **同数据源(20:55 时点)还被谁用**:plist(定时器本体)、nextday_plan.sh(包装注释)、
  gen_schedule_stats.py(前端展示)、schedule_monitor.sh(漏跑检查)、check_data_integrity.py(注释)、
  云上 systemd-units + migration-inventory 两文档。→ 全量 7 处一并改 22:30。
- **同模式(fail-open FORCE)**:`NEXTDAY_PLAN_FORCE` 仅此一处,已移除。
- **相关展示位**:schedule_stats.json 是 gen_schedule_stats.py 的运行时产物(未进 git),
  下次 deploy/schedule_monitor 跑会随 TASKS 表刷新为 22:30,无额外动作。

## 七、部署注意事项(交主控 merge 后执行)

1. **本地 launchd**(仓库副本 `docs/auto-trade/com.trade.nextday-plan.plist` 已改,但运行时副本
   `~/Library/LaunchAgents/com.trade.nextday-plan.plist` 需同步 + 重载):`kickstart -k` 不重读 plist,
   须 `launchctl bootout gui/$(id -u)/com.trade.nextday-plan` + `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.trade.nextday-plan.plist`。
2. **云上 systemd**:`trade-nextday-plan.timer` OnCalendar 改 `Mon..Fri *-*-* 22:30:00` 后
   `systemctl daemon-reload && systemctl restart trade-nextday-plan.timer`。
3. **唤醒注意**:22:30 晚于原「机器活跃至 21:40 overfit-monitor」窗口,首晚需验是否漏跑;
   若机器睡眠导致漏跑,主控补 pmset 定时唤醒(StartCalendarInterval 标准行为本可唤醒,但需实测确认)。
4. 非交易日闸门(nextday_plan.sh 内置)不变,周末/节假日跳过。

## 八、相关 commit

- 本分支:`feat/nextday-prev-close-stale-fix`
- 参照修复:#38 先例 94d4e28f4(逐只 ETF gate)、692dbfe95(采集失败闸门 + 链路文档同步)
