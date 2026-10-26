# #309 审查修复 · 边界维度清单(七轴)

> 任务:修 #309 独立审查的 2 个 P1 + 8 个 P2/P3;第三轮追加「新 P1 双盲假 OK +
> 首轮假恢复 + defer 判据 + timer 真实键集」等(P1b/P2/P3),本清单同步扩四轴:
> **两次独立读取一致性 / fixture 键集忠实度 / 键迁移恢复语义 / ledger 新鲜度**。
> 第四轮追加 F1(必修)/F3/F4 三项:刷新返回码 / 账本 exit 未来时间 / 跑过信号全缺。
> 分支:`feat/fix-309-fake-ok-20261025`;日期:2026-10-25。
> 口径:按 role-tester skill §5.3.1 七轴(输入域 / 状态组合 / 时序 / 上下游 / 极端值 /
> 回退路径 / 并发)逐项列「来源 + 判定(测/不测)+ 依据与理由」,供 reviewer §10.8
> **先独立再推一份**后对账;差集由 reviewer 报主控处置。
> 全部用例 static-only:假 `systemctl`(runner 注入)、tmp 日志沙箱、`notify` /
> `subprocess.run` / `launchctl_loaded` 全打桩;不跑业务脚本、零真实外发。

## 1. 输入域

| # | 来源(需求点/改动点) | 边界项 | 判定 | 依据与理由(对应用例) |
|---|---|---|---|---|
| I1 | P1-1 读取层 | `systemctl show` 真实形状:多 unit 空行分块、`Id` 可排块中部 | 测 | `test_parse_multi_real_systemctl_shape` 内嵌 2026-10-25 云上实测字面量 |
| I2 | P1-1 读取层 | `.service` 块出现 timer 专属属性(假样本养绿 L49) | 测 | `test_fixture_service_timer_shape_matches_real_systemd`:三套 fixture 硬校验 43 service 仅 8 属性、43 timer 仅云上真实 6 属性、同名配对;变异「service 塞 NextElapse」必红 |
| I3 | P1-1 读取层 | `.timer` 块自带 `Result=success` 被当成任务结果 | 测 | `test_timer_result_never_leaks_into_service_truth`、`test_timer_result_success_never_washes_failed_service`(service=timeout + timer=success 仍得 124);`_merge_unit_props` 白名单只取 timer 的 2 个时间属性 |
| I4 | P1-1 读取层 | `LoadState=not-found` 但仍 `Result=success`(systemctl 返回 rc=0 陷阱) | 测 | `test_not_found_is_never_zero`、`test_not_found_unit_is_unknown_not_success`(保留 `missing` 诊断标签) |
| I5 | P2-6 诊断源 | `Result=""`(no-record)、无 start/invocation(never-ran)、unknown-result | 测 | `test_unknown_result_is_honest_none`、unit-only 参数化 `never-ran/no-record/missing/unknown-result` |
| I6 | P1-2 日志口径 | 真实行 `退出码=0 采集=0 deploy=1` | 测 | `test_zero_exit_with_deploy_failure_is_warning_not_zero`;实跑输出 `last_exit=1/log-deploy/warning/signals={0,0,1}` |
| I7 | P1-2 日志口径 | `退出码=0 采集=1`(采集失败优先) | 测 | `test_zero_exit_with_collect_failure_is_severe` |
| I8 | P1-2 日志口径 | `退出码=1 deploy=1`(主失败不被 deploy 降级, 但保留 deploy 信号) | 测 | `test_primary_failure_with_deploy_failure_keeps_deploy_signal` |
| I9 | P1-2 日志口径 | `退出码=3 采集=2 deploy=1`(三信号并存) | 测 | `test_collect_and_primary_both_fail_keeps_both_signals` |
| I10 | P1-2 日志口径 | 日志不存在 / 无配对结束行 | 测 | `test_rollback_log_mode_missing_log_is_none`、systemd 模式全绿/缺日志用例 |
| I11 | P2-5 CFU 文案 | `check_failed_units` 输出「N 项(类别数)」含 2 个 unit 名 | 测 | `test_ok_line_truth_20261025.py`:断言展示 2 个名字, 旧「N 个云上 unit failed」不出现 |
| I12 | P2-5 CFU 文案 | 输出无 unit 名(旧版/其他问题类型) | 测 | 同文件无名字 fallback 用例, 文案降级为「N 类巡检问题」不硬编 unit 数 |
| I13 | 全批 | systemctl 输出畸形(块无 `Id`、空行异常) | 不测(实现已防御) | `_parse_multi` 丢弃无 Id 残块;畸形输出不在 systemctl 契约内, 且只会退化为空随后逐 unit 兜底。补测成本低但无对应生产路径, 本轮不扩 |
| I14 | 全批 | 非 UTF-8 / 中文日志乱码 | 不测 | 与本次改动无关(既有 `read_text` 口径未动);新增判定只吃已解析的整数字段 |
| I15 | P3 fixture 键集忠实度 | fixture 的 timer 键集与云上真实形状不一致(旧 4 键缺 Result/InvocationID) | 测 | 云上实测原文 `/tmp/309-review2-show4.txt`(timer 6 键);`REAL_TIMER_KEYS` 4→6 + 三套 fixture 补齐;变异「退回 4 键」→3 条红;`test_309_gen_stats_exit_source.py` 的 `TIMER_KEYS` 同步 6 键(举手一反三) |
| I16 | P3 timer 属性 | `Result`/`InvocationID` 在 service 与 timer 上同名(两处都有), 是否串味 | 测 | `test_fixture_read_does_not_leak_timer_result_or_invocation`:逐 unit 对账 service Result/InvocationID;变异「timer 属性全量合并」→6 红 |
| I17 | F1 刷新返回码 | `gen_schedule_stats.py` 顶层未捕获异常 → 进程退出码 1(`subprocess.run` 不 raise) | 测 | `test_nonzero_rc_marks_refresh_failed`(rc=1 ⇒ `STATS_REFRESH_OK=False` + stderr 记退出码与尾部)+ 端到端 `test_nonzero_rc_conclusion_never_says_ok`(全绿 stats + rc=1 ⇒ 结论行不含「OK 所有任务」);变异注释判据 →3 条红 |
| I18 | F1 刷新返回码(反向) | rc=0 正常刷新 | 测 | `test_zero_rc_keeps_refresh_ok`、`test_zero_rc_all_green_still_says_ok`(全绿 + rc=0 ⇒ OK 必须回来, 防本次修复把结论打成恒不 OK) |
| I19 | F1 刷新返回码 | rc≠0 但 stderr 为空 / stderr 是超长 traceback | 测 | `test_nonzero_rc_with_empty_stderr_still_flags`(空 stderr 仍判失败)、`test_stderr_tail_is_truncated`(只留最后一行且截断 200 字, 防刷屏/带出无关内容) |

## 2. 状态组合

| # | 来源 | 边界项 | 判定 | 依据与理由 |
|---|---|---|---|---|
| S1 | P2-7 | 运行中 `active/activating/reloading` + 旧 start/旧 exit(可算出负 duration) | 测 | `test_running_unit_only_row_has_no_exit_and_no_duration` 三个 active 值全参数化;变异 guard 后 3 条必红 |
| S2 | P2-7 | 同 unit 结束后恢复 `systemd` 正常 exit/duration | 测 | `test_running_row_recovers_after_finish`:60s duration 正数 |
| S3 | P2-4 | `is-active=failed` + unit 真值码非 0(同轮双报) | 测 | `test_failed_no_exit_defers_to_unit_channel`;unit 通道只留 `self_heal|unit_exit!=0|1` |
| S4 | P2-4 | `is-active=failed` + unit 码读不到(降级兜底, 不许静默) | 测 | `test_self_heal_without_unit_truth_still_alerts`(`{label}|failed`) |
| S5 | P2-1 | label 在 stats 覆盖内 + stats 仍 0/未知(通道失效) | 测 | `test_failed_no_exit_raises_when_stats_channel_blind`(SEVERE + 键 `failed_no_exit` + notify 0 次) |
| S6 | P2-3 | stats 刷新失败轮(stats 仍 0)+ unit code 1 | 测 | `test_unit_channel_is_single_hop_across_stats_refresh` 第 1 轮 |
| S7 | P2-3 | 下轮 stats 已合并同 code + `exit_source=systemd` | 测 | 同用例第 2 轮:`_unit_channel_owns_row` True, 同 key 不新增 |
| S8 | P2-3 | 反向:`exit_source=log-deploy` 或 systemd 开关关 | 测 | 同用例反向对照 owns=False(不由 unit 通道接管) |
| S9 | 真值采信 | stats 行已判真值不可信(unit_exit/start 空 + health=unknown) + live 真值非 0 | 测 | `test_untrusted_stats_row_does_not_hide_live_failure`(旧用例已按 P1b 反向: stats 不可信 ≠ live 码是假的, 仍须出事件) |
| S10 | P2-6 | 结论层: unknown/never-ran/no-record/missing/unknown-result 一律不判 OK | 测 | 参数化 4 个诊断源均阻断 OK;`running` 例外不阻断 |
| S11 | P2-5 | CFU failed=0 / 有 failed | 测 | 全绿 7 天 + CFU=2 展示用例 |
| S12 | 全批 | 43 unit 全绿一轮 | 测 | `test_seven_green_days_produce_no_events_and_ok`(7 天参数化, 防空转恒红) |
| S13 | P2-2 | `last_exit_tier=warning` 才走 warning 分支;0/None 不走 | 测 | `test_deploy_branch_does_nothing_for_zero_exit`、`..._non_warning_tier` |
| S14 | 全批 | 未入表 3 个自监控 unit(include=False) | 测 | `test_systemd_mode_emits_40_rows_and_43_registry` + `_unit_alert_events` 覆盖 43 |
| S15 | 全批 | stats 文件整体陈旧(行仍 0, 不是明确 unknown) | 不测(设计即兜底) | 注释:`srow` 存在且明确 unknown 才静默;整文件陈旧正是 unit 通道要报的真失败, 已有 S6 覆盖等价输入 |
| S16 | P2-4 | `self_heal` 同轮同时产生 `{label}|failed` 与 `unit_exit!=0` | 测 | S3 + S4 成对;另 `test_self_heal_alerts_again_when_unit_channel_rolled_back` 验回滚时不静默 |
| S17 | P2 defer 判据 | unit 通道本次**不会**登记但 failed 循环仍 defer(ledger-stale live 码 / unit 不在 43 行注册表 / stats 码超 24h) | 测 | `test_ledger_stale_live_code_does_not_silence_failed_loop`、`test_unit_outside_registry_does_not_defer`、`test_stale_stats_failure_is_not_covered_by_exit_channel`;变异还原旧判据 →3 条红 |
| S18 | P2 defer 判据(反向) | unit 通道会登记(新鲜 stats 兜底码)⇒ 不重复报 | 测 | `test_fresh_stats_failure_is_covered_reverse_control` + `_unit_channel_will_register` 10 行参数化(含 systemd 通道关/注册表外/live=0 不采信 stats) |
| S19 | P3 ledger 新鲜度 | 重启补位码:24h 内=ledger(可发 SEVERE) / 超 24h / 无 exit 时间 / 本轮 start 更新=ledger-stale(不发, 结论可见) | 测 | `test_merge_ledger_old_exit_is_stale_with_now`、`..._fresh_exit_stays_ledger`、`..._missing_exit_is_stale_with_now`、`..._newer_start_marks_stale_without_last_trigger`、端到端 `test_old_ledger_filled_code_does_not_email_but_stays_visible`;变异删新鲜度分支 →3 条红 |
| S20 | F4 跑过信号全缺 | live `InvocationID` + `ExecMainStartTimestamp` + `LastTriggerUSec` 三样全缺 + 账本 exit 才 1h(旧逻辑判新鲜) | 测(stale) | 生产依据:2026-10-25 云上 `systemctl show` 43/43 unit 实测三样**都非空**(service 43/43 + timer 43/43)⇒ 全缺只出现在「restart 后还没跑过 / 本轮读取失败」这种没有运行证据的形态, 此时拿旧账本码当新鲜必误报。`test_merge_ledger_all_run_signals_missing_is_stale`(reason=`no_run_signal`);变异删该分支 → 1 红 |
| S21 | F4 跑过信号全缺(反向) | 只要有一个跑过信号(例:仅 `LastTriggerUSec` 有值且早于账本 exit) | 测(fresh) | `test_merge_ledger_one_run_signal_present_stays_ledger`:不许把「有证据」也打成 stale(防修复过度变静默) |
| S22 | F4 跑过信号全缺 | 调用方不传 `now`(离线/纯单测) | 测(旧行为) | `test_merge_ledger_no_run_signal_without_now_keeps_old_behavior`:不传 now = 不判新鲜度, 既有调用方语义不变 |

## 3. 时序

| # | 来源 | 边界项 | 判定 | 依据与理由 |
|---|---|---|---|---|
| T1 | 真值采信 | systemd start 早于日志 start 120s 边界(120 采信 / 121 残留) | 测 | `test_unit_truth_trust_window_is_120s` 三点参数化 |
| T2 | 漏跑 | `now > next_elapse + 10min` 边界(恰好 10min 不算漏) | 测 | `test_timer_health_exact_boundary_not_missed`、`test_timer_health_missed_after_grace` |
| T3 | 漏跑 | 运行中即使 next_elapse 已过期也不算漏 | 测 | `test_running_timer_is_not_missed` + P2-7 行级用例 |
| T4 | P2-3 一跳 | 跨两轮(stats 刷新失败→恢复)同一故障只一个 key | 测 | `test_unit_channel_is_single_hop_across_stats_refresh` |
| T5 | 全批 | 用例内部取「今天」导致隔天红(L51) | 测(静态核) | 全部 309 用例显式注入 `NOW`/`day`;`grep datetime.now()/date.today()` 于 `test_309_*` 零命中 |
| T6 | 漏跑 | timer 被停/改点/机器睡死导致 next_elapse 过期 | 测 | 漏跑真实样例:x3 快照把 ab-direction-anchor timer 改到 16:00, 结论「漏跑 1」+ SEVERE key `ab_direction_anchor|unit_missed` |
| T7 | P2-2 | deploy 告警 dedup window 21600 的跨轮抑制 | 不测(既有机制) | 本批只改分级/key 与分支可达性;`notify.py` 去重窗行为由既有告警测试与登记表覆盖, 不在 diff 内 |
| T8 | P2-3 键迁移恢复语义 | 旧日志键 `{task}|exit!=0|{code}` 仍 active + 本轮切到 unit 键, 同一轮同时有「恢复」和「新故障」 | 测 | `test_309_key_migration_20261025.py`:旧键进 seen 静默退休(reason=migrated_to_unit_key / 换码=superseded_by_new_code)+ 新键首报 ⇒ 同轮 `recoveries == []`;反向对照不迁移 → 必发 1 条假恢复(判别力) |
| T9 | P2-3 键迁移恢复语义 | 本轮有失败但通道不发事件(ledger-stale)且新键已 active | 测 | `test_failure_without_event_still_marked_seen`:新键仍标 seen, 不许被误判「已恢复」;旧键同时退休 |
| T10 | P1b 两次独立读取一致性 | stats 快照(gen_schedule_stats 读一次 systemd)与 monitor live(再读一次)在两个时刻读到的码不同: stats 124/live 0 或 stats 0/live 124 | 测 | 双盲穷举 #3(stats124/live0: 不邮件但结论不得 OK)与 #13(stats0/live124: 必邮件且不得 OK);两侧任一非 0 就不得打 OK(硬不变式) |
| T11 | P3 结论层 | 有失败时「退出码未知 N 个」被提前 return 吞掉 | 测 | `test_conclusion_does_not_truncate_unknown_when_failure_present`(1 失败 + 1 未知 同轮同时展示) |
| T12 | F3 账本 exit 未来时间 | 账本 exit = now + 1h(时钟回拨/账本写坏) | 测(stale) | 负差值会让「now - exit > 24h」恒假 ⇒ 旧码被当新鲜发 SEVERE。`test_merge_ledger_future_exit_is_stale`:source=ledger-stale, reason=`future_exit`, code 仍可见(只挡 SEVERE);变异注释判据 → 1 红(reason 退化成 no_run_signal) |
| T13 | F3 允许偏差 | 未来 1min(偏差内) / 恰好 now+5min(判据 `>` 不含等号) | 测(fresh) | `test_merge_ledger_slightly_future_exit_stays_ledger`、`test_merge_ledger_exact_tolerance_boundary_stays_ledger`:时钟微差不算账本损坏, 不许一律打死 |
| T14 | F3+F4 叠加 | exit 在未来 + 跑过信号全缺同时成立 | 不测(两者同判 stale) | 判据链 future_exit 在前、no_run_signal 在后, 结论都是 ledger-stale;差异只在 reason 诊断文案, 无告警行为差异, 不单列用例 |

## 4. 上下游

| # | 来源 | 边界项 | 判定 | 依据与理由 |
|---|---|---|---|---|
| U1 | P1-1 | `read_unit_states` 唯一生产调用方 `gen_schedule_stats.build` | 测 | 全量 grep:非测试代码仅 `gen_schedule_stats.py:1639`;读取层返回 key 仍为 service unit 名, 未改契约 |
| U2 | P1-2/P2-6 | `schedule_stats.json` 新增 `exit_signals`, 既有字段语义变化 | 测 | 40 行字段存在性断言;新增字段纯追加;`push_schedule_stats.sh` 只上传不解析 |
| U3 | P2-5 | `check_failed_units.py` 本体不改(任务明确) | 不测(不改) | 只解析其 stdout;`grep` diff 确认该文件零改动 |
| U4 | P2-4 | `self_heal_core.py` 本体不改(任务明确) | 不测(不改) | 改动只落 `schedule_monitor.sh`;diff 确认 |
| U5 | P2-8 | 告警登记文档与新 dedup key 对账 | 测(文档实文) | `docs/ops/alert-checker-registry-20261015.md` §2.3 新增 5 个键 + 行 16 指针;锚点行号实测 |
| U6 | P2-2 | `notify.py` 调用参数(`--tier warning`/`--dedup-key`/`--dedup-window`) | 测 | monitor 分支用例断言完整命令;`--severe` 不出现 |
| U7 | P2-4 | launchctl 分支在云上 systemd 生产是否可达 | 不测(环境既有) | 云上 `LOCAL_DEV=0` 时 launchctl 列表为空;分支为 mac 开发/兜底路径, 本批只保证两通道不双报 |
| U8 | P1-1 | 前端/其他页面消费 `schedule_stats.json` 新字段 | 不测(无展示改动) | 前端未消费 `exit_signals`;既有字段名与语义未破坏, 无需 UI 回归;上线后由结论行/告警验证 |
| U9 | P1-2 | 行格式白名单守卫(`test_log_gz_compat_20261010`)拒绝未申报新字段 | 测 | 全量 pytest 首跑即红(3 行 `白名单外新字段 ['exit_signals']`)⇒ 按新增字段申报进 `NEW_KEYS_309`, 旧字段逐键对账仍 PASS(L52 同类: 改 scripts 必跑全量) |
| U10 | F3/F4 下游消费方 | `merge_ledger_state` 的两个生产调用方(`gen_schedule_stats.py:1649` 生成 40 行 / `schedule_monitor.sh:610` live 扫描)都受新判据影响 | 测 | 全量 grep 确认只有这两个生产调用方(其余均在 `scripts/tests/`);两者都传 `now` ⇒ 新判据生效, 输出 `exit_source=ledger-stale` 走既有「不发 SEVERE、结论行可见」路径(`_unit_alert_events` L824 守卫);全量 pytest 无回归 |
| U11 | F1 同类调用面 | `schedule_monitor.sh` 内其它 `subprocess.run`(notify 发送 6 处 / sysctl-vm_stat / 心跳 pgrep)是否也丢返回码致假 OK | 不测(已逐处核) | 逐处读码:5 处 notify 丢弃返回值但**不参与 OK 判定**(属 F2「结论行不进邮件」范畴, 本批明确不动);其余把结果收进变量并有 rc/输出判据;唯一喂结论的 gen 刷新即 F1 修复点 |
| U12 | F1 同类调用面 | 其它任务脚本(`update_all.sh`/`gold_night.sh`/`public_fund_*.sh` 等 10+ 处)调 `gen_schedule_stats.py` 失败 | 不测(不改) | 这些调用失败只打「⚠ 失败, 不阻塞」进各自日志, **不参与任何 OK 判定**(monitor 每轮开头自己重生成);monitor 侧 F1 修复已覆盖「喂结论」唯一路径 |

## 5. 极端值

| # | 来源 | 边界项 | 判定 | 依据与理由 |
|---|---|---|---|---|
| E1 | P1-1 映射 | `Result=timeout`→124 / `signal`→128+sig / `core-dump` | 测 | `test_derive_exit_code_table` 7 项映射表 |
| E2 | P1-1 读取 | 单 unit 读取异常/返回空 dict | 测 | `test_read_unit_states_runner_exception_becomes_empty`;结论层 unknown 阻断 OK |
| E3 | P1-1 读取 | 86 unit(43×2)一次 show 的耗时 | 测(云上实测) | 2026-10-25 只读实测 0.093s;批量失败→逐个 `_read_one` 兜底 |
| E4 | P2-7 | duration 负值(exit < start) | 测 | guard 后强制 None(S1);无 guard 变异 3 条红 |
| E5 | 漏跑 | `next_elapse` 缺失/解析失败 → unknown 不误报漏跑 | 测 | `test_timer_health_unknown_without_next_or_missing` |
| E6 | P2-5 | failed unit 列表很长(43 个全 failed) | 不测 | 只影响结论行长度, 不改变判定;云上当前 failed=2;超长展示可读性归观察锚点 |
| E7 | P1-2 | 采集/退出码/deploy 同时缺(全 None) | 测 | `has_exit_code=False` + systemd 口径兜底, 全绿用例覆盖 |
| E8 | 全批 | stats 0 行 / 空 registry | 不测 | build 固定 40 行, 空 registry 属配置损坏;既有代码会抛错暴露, 不新增静默分支 |
| E9 | F3 允许偏差取值 | 为什么是 5min(不是 0、不是 1h) | 测(边界两点) | 账本与 monitor 同机同进程写/读, 大额未来时间只可能是写坏或时钟被大步拨;但 `ExecMainExitTimestamp` 来自 systemd、与读取时刻可能有 NTP 微调级抖动 ⇒ 留 5min 余量(远大于抖动, 远小于「旧账本」的 24h 窗口)。偏差内/外各有用例(T13/T12), 恰好 5min 边界也测 |

## 6. 回退路径

| # | 来源 | 边界项 | 判定 | 依据与理由 |
|---|---|---|---|---|
| R1 | 一行回滚 | `MONITOR_EXIT_SOURCE=log`:行数 19、deploy=1 当 0、不读 systemd | 测 | `test_rollback_log_mode_restores_old_caliber`、`test_rollback_log_mode_missing_log_is_none`(runner.calls==[]) |
| R2 | 一行回滚 | 非法/空 `MONITOR_EXIT_SOURCE` 不静默变 log | 测 | `test_exit_source_mode` 参数化 |
| R3 | 二行回滚 | `UNIT_REGISTRY include:False` 排除自监控 3 个 | 测 | 40 行/43 registry 用例 |
| R4 | P2-4 回滚 | unit 通道关闭(`SYSTEMD_TRUTH_ON=False`)时 self-heal failed 仍告警 | 测 | `test_self_heal_alerts_again_when_unit_channel_rolled_back` |
| R5 | P2-2 回滚 | 分支未命中时零 notify(不会误报) | 测 | 0/None tier 两条用例 |
| R6 | 全批 | 回滚后旧键与旧口径逐位一致(不再产生 unit 新键) | 测 | R1 断言 19 行 + `unit_exit is None`;`test_seven...` 不启用新口径时旧结论路径不变 |
| R7 | 部署回滚 | feat 分支 revert 后线上行为恢复 | 不测(部署操作) | 本批无数据产物/前端版本串改动, `git revert` 即恢复;上线由主控统一入口 |
| R8 | F1 回滚 | 去掉 rc 判据 = 回到「只看异常」的旧行为 | 测(判别力已证) | 注释掉 `if _stats_refresh.returncode != 0` → 3 条红(I17/I19), 还原 → 绿;无数据结构/接口改动, 回滚只删该判断块 |
| R9 | F3/F4 回滚 | 去掉 future_exit / no_run_signal 判据 = 回到「只看 24h」旧行为 | 测(判别力已证) | 分别注释 → 对应 1 条红(T12 / S20), 还原 → 绿;新增常量 `LEDGER_FUTURE_TOLERANCE` 只被本判据用, 回滚无残留依赖 |

## 7. 并发

| # | 来源 | 边界项 | 判定 | 依据与理由 |
|---|---|---|---|---|
| C1 | P1-1 | 43 service+43 timer 一次 show vs 逐 unit 调用的竞态窗口 | 不测 | 单次快照比多次更一致, 不新增竞态;读失败走逐 unit 兜底 |
| C2 | 全批 | monitor 15min 周期重叠/两实例同时跑 | 不测(既有) | 新增键沿用既有 `alert_state`+`seen_keys_this_run` 单实例机制, 本批不新增共享写目标;多实例非本批引入 |
| C3 | P2-2/P2-4 | 同一轮多个 label 同时 failed | 测 | 循环级用例单 label 覆盖分支;`_unit_alert_events` 对 43 全绿/单失败覆盖(多 label 为同构循环, 无跨 label 状态) |
| C4 | 测试隔离 | mutation/用例改生产文件被并行读 | 测(收尾核) | 变异脚本逐项写→跑→还原并 sha256 校验;全量 pytest 在还原后单独跑 |

## 8. 结论与未测项处置

- 测:73 项;不测:16 项(每项已给理由:既有机制/不改文件/无生产路径/仅展示长度/
  诊断文案差异)。
- 「不测」项若 reviewer 独立推导出遗漏, 按 §10.8 差集报主控;本清单不代替 reviewer 自查。
- 验收证据:309 专项用例全绿(条数见实施报告)、全量 pytest 数字;判别力自证覆盖
  双盲抑制判据 / 键迁移 recovered / defer 一致性 / timer 6 键与串味 / ledger 新鲜度
  五组 + 第四轮 F1 刷新返回码 / F3 未来时间 / F4 跑过信号全缺 三组
  (逐个改坏→红→还原→绿,证据见实施报告)。
- 四轴落点索引(第三轮新增):两次独立读取一致性 → T10;fixture 键集忠实度 → I15/I16;
  键迁移恢复语义 → T8/T9(登记表 §2.3.1);ledger 新鲜度 → S19。
- 第四轮落点索引:F1 刷新返回码 → I17/I18/I19 + U11/U12(同类调用面) + R8;
  F3 账本 exit 未来时间 → T12/T13/T14 + E9(偏差取值) + R9;
  F4 跑过信号全缺 → S20/S21/S22(选型依据=云上 43/43 实测)+ U10(两个生产调用方)。

## 9. 第五轮(#309 F2 结论「状态说明」邮件,2026-10-26)

> 分支 `feat/309-conclusion-email-20261026`;改动点=`scripts/schedule_monitor.sh` 的
> `_conclusion_status_*`/`_maybe_send_conclusion_status_email` + 结论调用点 + 恢复环跳过前缀。
> 需求 = 用户 2026-10-26 拍板:结论非 OK **且**本轮零告警邮件时补发一封「状态说明」,
> 不是每轮发;同一份结论只发一次。全程 static-only:notify 全 stub、零真实外发(§18 L48)。
> 用例文件 `scripts/tests/test_309_conclusion_email_20261026.py`(20 条)。

### 9.1 输入域

| # | 来源(需求点/改动点) | 边界项 | 判定 | 依据与理由(对应用例) |
|---|---|---|---|---|
| F2-I1 | 实现预期 C | 两种 OK 文案(「OK 所有任务…」/「OK(仅日志口径…」) | 测 | `test_scene_c_ok_never_sends` 参数化 2 种,断言 0 次调用 |
| F2-I2 | 实现预期 B | 非 OK 的三种真实形状:账本旧码不可信 / 有 N 条告警被去重吸收 / stats 刷新失败 | 测 | `test_scene_b_all_non_ok_text_variants_send_with_full_conclusion` 参数化 3 种;正文含原结论 + 「为什么」 |
| F2-I3 | 正文文案 | 结论含 `<`/`>`(HTML 注入/展示错乱) | 测 | `test_conclusion_html_special_chars_are_escaped` |
| F2-I4 | 防御 | 空结论(理论不可达) | 测 | `test_empty_conclusion_never_sends`:不发、不落签 |
| F2-I5 | 展示长度 | 超长结论行 | 不测(无判定影响) | `line_sample` 只截 200 字防 state 膨胀;正文照原样(结论行本身受 CFU 名单长度影响,E6 已说明) |

### 9.2 状态组合

| # | 来源 | 边界项 | 判定 | 依据与理由 |
|---|---|---|---|---|
| F2-S1 | 频率保护 | 同内容摘要 `active` ⇒ 不重发 | 测 | `test_frequency_same_conclusion_twice_only_first_sends`(第二轮 0 次、不落盘) |
| F2-S2 | 频率保护 | 内容变化 ⇒ 重新发 + 旧键退休(同一时刻最多 1 条) | 测 | `test_content_change_resends_and_retires_old_key`(state 长度恒 1) |
| F2-S3 | 恢复语义 | 结论 OK ⇒ 摘要键置 recovered、**不额外发信** | 测 | `test_recovery_releases_guard_without_mail_then_cooldown_blocks_flicker` |
| F2-S4 | 防抖动 | 恢复后 6h 内同内容复发 ⇒ 不重发 | 测 | 同用例 +1h ⇒ `recurrence_cooldown` |
| F2-S5 | 优先级 | 非 OK + 已有告警邮件 + 同内容键存在 ⇒ 以「已有告警邮件」为准,不发不改 state | 测 | `test_alert_mail_takes_precedence_over_same_content_state` |
| F2-S6 | 防御 | `state` 不是 dict | 不测(实现已 isinstance 防御) | 生产入口恒为 `load_alert_state()` 返回的 dict |
| F2-S7 | 恢复环交互 | `conclusion_status|` 键不参与恢复检测(否则被误判异常消失发假恢复邮件) | 测(源码形状守卫) | `test_recovery_loop_skips_conclusion_status_key`;`test_309_key_migration_20261025.py` 恢复环 harness 同步注入新常量 |

### 9.3 时序

| # | 来源 | 边界项 | 判定 | 依据与理由 |
|---|---|---|---|---|
| F2-T1 | 防抖动 | 恰好 6h(RECOVERY_COOLDOWN 判据 `>=`) | 测 | `..._cooldown_blocks_flicker` 第 3 段:now+6h ⇒ 重新发 |
| F2-T2 | 时序 | 跑用例取 `date.today()/datetime.now()` 致隔天红(L51) | 测(静态核) | 用例显式注入固定 `NOW=2026-10-26 09:42`;helper 内所有时间取自注入的 `now` |
| F2-T3 | 轮内时序 | 告警邮件计数须在结论补位判定**之前**完成(聚合批次/停摆直发/升级提醒都在前) | 不测(代码顺序已定) | 补位调用点在结论打印之后;`grep _ALERT_MAIL_COUNTER` 三处发送点均在前 |

### 9.4 上下游

| # | 来源 | 边界项 | 判定 | 依据与理由 |
|---|---|---|---|---|
| F2-U1 | 告警计数源 | 「本轮告警邮件数」只能数**真发出**(notify 确认送达),不能数 `len(alerts)`(含去重/吸收行) | 测(源码形状) | `test_severe_alert_paths_all_increment_alert_mail_counter`:3 个 severe 发送点都 +1 + 调用点传计数器 |
| F2-U2 | notify.py 接口 | 新主题/键被 notify 的域聚合或预算 gate 静默并入摘要 | 测 | `test_new_subject_and_key_are_not_absorbed_by_notify_gates` 直接调生产 `adr.domain_of/category_of`,均 None |
| F2-U3 | notify.py 调用形态 | 主题/正文/`--from-prefix`/`--alert-issue`/`--alert-log`;不打 `--severe` | 测 | `test_scene_b_...` 断言完整 cmd |
| F2-U4 | state 落盘 | 确认送达才落签;未送达/异常不落签(下轮重试) | 测 | `test_notify_not_confirmed_does_not_record_state`、`..._runner_exception_...` |
| F2-U5 | 既有 notify 调用面 | 部署 warning / R2 skip warning / 资源 warning / info 级不计入「告警邮件数」 | 不测(设计即如此) | 它们是入 30min 聚合 buffer 或仅 dashboard,本轮没有真正外发邮件;若计入会导致「用户其实没收到邮件也不补位」的漏洞 |
| F2-U6 | 前端/数据产物 | 无前端、无 data 产物、无版本串改动 | 不测 | diff 仅 `scripts/` + 测试 + 本清单 |
| F2-U7 | 恢复邮件同轮 | 结论补位与恢复邮件可同轮各发 1 封 | 不测(设计接受) | 恢复邮件不是告警邮件,语义不同(一个说「好了」一个说「结论仍异常」);频率保护保证结论邮件只发一次 |

### 9.5 极端值

| # | 来源 | 边界项 | 判定 | 依据与理由 |
|---|---|---|---|---|
| F2-E1 | 发送失败 | notify 全渠道未发出 | 测 | `test_notify_not_confirmed_does_not_record_state` |
| F2-E2 | 发送异常 | runner 抛异常(超时等) | 测 | `test_notify_runner_exception_is_swallowed_and_retried_next_round`(不外抛、不落签) |
| F2-E3 | 结论长度/内容 | 超长、含换行 | 不测(无判定影响) | 正文原样拼 HTML `<br>` 前缀;结论行本身是单行(dev 侧 `_build_conclusion` 用 `; ` 拼接) |
| F2-E4 | 摘要键膨胀 | 长期运行累积无数 `conclusion_status|` 键 | 测(设计保证) | 内容变化即退休旧键、同一时刻最多 1 条(S2 断言 state 长度=1);OK 轮保留单条 recovered 供 6h 抖动判定 |

### 9.6 回退路径

| # | 来源 | 边界项 | 判定 | 依据与理由 |
|---|---|---|---|---|
| F2-R1 | 一行关闭 | 删掉调用点(或让 `send` 恒 False)⇒ 回到「只打日志」旧行为 | 测(判别力已证) | 变异「零邮件判据」⇒ 6 条用例红(含 B 场景),还原 ⇒ 绿(sha256 一致) |
| F2-R2 | 回滚顺序 | 删恢复环 skip 前缀必须与删键写入同时做,否则残留键会触发假恢复邮件 | 不测(人工回滚约束,已写死在本表 + 代码注释) | 生产 `alert_state.json` 若残留 `conclusion_status|` 键,恢复环会把它们当异常发假恢复 ⇒ 回滚须同时清键或删 skip 一起删 |
| F2-R3 | 部署回滚 | feat revert 即恢复旧行为 | 不测(部署操作) | 无数据产物/版本串改动 |

### 9.7 并发

| # | 来源 | 边界项 | 判定 | 依据与理由 |
|---|---|---|---|---|
| F2-C1 | 计数器作用域 | 多轮之间计数不串(每轮独立进程) | 不测(结构性) | `_ALERT_MAIL_COUNTER` 是进程内模块级变量,monitor 每 15min 新进程 |
| F2-C2 | state 并发写 | 两个 monitor 实例同时写 `alert_state.json` | 不测(既有风险) | 沿用既有单实例 15min 机制,本批不新增共享写目标 |
| F2-C3 | 测试隔离 | 变异改生产文件与并行测试互扰 | 测(收尾核) | 变异脚本 try/finally 还原并 sha256 校验;全量 pytest 在还原后单独跑 |

### 9.8 本轮测/不测小结

- 测:20 条用例(含 3 类非 OK 输入参数化 / 6h 边界 / 发送失败与异常 / 两个源码形状守卫)。
- 不测:7 项,均给理由(无判定影响 / 实现已防御 / 环境既有 / 设计接受 / 人工回滚约束)。
- 判别力证据:把 `_conclusion_status_decision` 的「零告警邮件」判据改坏(`> 0` → `>= 0`)
  ⇒ B 场景及同族共 6 条红;还原 ⇒ 20 条全绿,文件 sha256 与改前一致。
## 10. 第六轮(#309 F2 P1 告警邮件计数补全,2026-10-26)

> 分支 `feat/309-conclusion-email-20261026`;审查阻塞项 D1(「本轮告警邮件数」漏计通道)。
> 改动点:`scripts/schedule_monitor.sh`(计数累计 + 判定点后移 + 环境开关 + 顺手修)、
> `scripts/check_failed_units.py`(`NOTIFY_SENT=<n>` 标记)、`scripts/notify.py`(两条批发
> 结果文件 status 如实标注,发送语义未动)。用例 `test_309_conclusion_email_20261026.py`
> 由 20 条扩到 51 条(原 20 条一字未删)。全程 static-only,零真实外发(§18 L48)。

### 10.1 输入域

| # | 来源(需求点/改动点) | 边界项 | 判定 | 依据与理由(对应用例) |
|---|---|---|---|---|
| P1-I1 | CFU 标记 | `NOTIFY_SENT=0` / `=1` / `=2` | 测 | `test_cfu_marker_zero_counts_as_no_mail`、`..._cfu_child_severe_counts_...`、`..._multiple_sends_counted` |
| P1-I2 | CFU 标记 | 标记缺失(子进程被杀/旧版)/格式坏(`=abc`)/非独立行(日志里出现同样字样) | 测 | `test_cfu_marker_missing_or_broken_is_conservative` 参数化 4 种,全部按 1 保守 |
| P1-I3 | 批发 status | `sent` / `noop` / `failed` / 空串(结果文件缺失或损坏) | 测 | `test_flush_status_mapping` 参数化 4 种;空串=判不出 ⇒ 保守 1 |
| P1-I4 | 判定入参 | `alert_mail_sent` 为 `None`/`""`/`object()`/非数字字符串/"  "(空白) | 测 | `test_non_numeric_alert_mail_sent_is_conservative` 参数化 5 种,一律保守不发 |
| P1-I5 | 判定入参 | 数字字符串(`"2"`)、布尔、整数 | 测 | `test_numeric_string_alert_mail_sent_still_parsed` + 既有 A 场景(整数 1) |

### 10.2 状态组合

| # | 来源 | 边界项 | 判定 | 依据与理由 |
|---|---|---|---|---|
| P1-S1 | 漏点 1 | CFU 真发 severe + 结论非 OK ⇒ 状态说明 0 次 | 测(行为) | `test_scene_a_cfu_child_severe_counts_and_blocks_status_mail`(不落签、state 无 `conclusion_status|`) |
| P1-S2 | 漏点 2 | 聚合批发真发 1 封 + 结论非 OK ⇒ 状态说明 0 次 | 测(行为) | `test_scene_a_flush_batch_sent_blocks_status_mail` 参数化 2 种 |
| P1-S3 | 反向 | CFU 明确回报 0 封 ⇒ 仍照常补发 1 封 | 测 | `test_cfu_marker_zero_counts_as_no_mail`(证明不是「一律不发」的假修) |
| P1-S4 | 子进程契约 | 子进程真发出时 stdout 有 `NOTIFY_SENT=1`;健康轮有 `NOTIFY_SENT=0` | 测(行为,真跑 `main()`) | `test_cfu_child_really_prints_marker`、`..._prints_zero_marker_...`(notify.py 用写 `--result-file` 的假 run 代替) |
| P1-S5 | 环境开关 | `MONITOR_CONCLUSION_STATUS_EMAIL=0/false/off/no/带空格` ⇒ 完全不发、不落签 | 测 | `test_env_switch_off_disables_everything` 参数化 5 种 |
| P1-S6 | 环境开关 | 变量未设 ⇒ 默认开(行为与上一版一致) | 测 | `test_env_switch_default_on` |
| P1-S7 | 优先级 | 已有告警邮件 + 同内容键存在 ⇒ 仍以「已有告警邮件」为准(不为省事改判) | 测(既有) | `test_alert_mail_takes_precedence_over_same_content_state` 保留 |

### 10.3 时序

| # | 来源 | 边界项 | 判定 | 依据与理由 |
|---|---|---|---|---|
| P1-T1 | 判定点位置 | 判定必须在 `--flush-warnings` **和** `--flush-digest` 之后(否则同轮 2 封) | 测(源码形状) | `test_decision_point_is_after_all_send_channels` 断言两条批发调用位置都早于判定调用 |
| P1-T2 | 计数点位置 | 六通道累计都在判定点之前,且批发计数真读自己的结果文件 | 测(源码形状) | 同用例:CFU/批发累加行位置 + `_read_notify_result_status(_flush_warn_rf/_flush_dig_rf)` 存在 |
| P1-T3 | 子进程时序 | CFU 子进程在结论合成之前跑完(标记已被读到) | 测(脚本顺序) | 累加行在 CFU 调用点之后、判定点之前;生产顺序固定 |
| P1-T4 | 用例时间 | 用 `datetime.now()` 致隔天红(L51) | 测(静态核) | 全部注入冻结 `NOW=2026-10-26 09:42`;子进程用例不依赖当天日期 |
| P1-T5 | 时钟回拨 | `now < last_recovered` ⇒ 冷却判定为「未过窗」⇒ 抑制重发(保守侧) | 不测(代码已如此) | `_conclusion_recurrence_ok`:`(now-last) >= 6h` 才放行,负数恒 False = 少发不多发 |

### 10.4 上下游(同类错误面:谁还会发告警邮件)

监控 heredoc 里全部 notify.py 调用点逐个核对(§23.3 举一反三):

| # | 调用点(行号=本批后) | 性质 | 计入? | 理由 |
|---|---|---|---|---|
| P1-U1 | 481 升级提醒 | 真发 severe | 计 1 | 原有计数点 |
| P1-U2 | 1530 deploy warning / 2055 R2 warning / 2777 资源预警 | `--tier warning` 入 30min 聚合缓冲 | 计(经 U11) | 本轮不直发,由尾部 flush 批发;按 flush 结果计,不按行计 |
| P1-U3 | 3780 飞书 ws 心跳陈旧 | `--tier info` | 不计 | info 只落 dashboard 不进群/邮件 |
| P1-U4 | 3941 停摆直发 | 真发 severe | sent 计 1;`suppressed` 计 0 | 去重窗内=本轮没发 |
| P1-U5 | 3990 批次行级预算 `--defer-digest` | 并入当日摘要,本轮不外发 | 不计 | 23:25 独立任务发摘要;状态说明文案说的是「**本轮**」,事实成立 |
| P1-U6 | 4025 收尾聚合批次 | 真发 severe | 按结果计 1 | 原有计数点 |
| P1-U7 | 4130 `[恢复]` 邮件 | 真发(非告警语义) | 不计 | 说「好了」不是告警;与 §9 F2-U7 口径一致 |
| P1-U8 | 4284 恢复补列 `--defer-digest` | 本轮不外发 | 不计 | 同 U5 |
| P1-U9 | **CFU 子进程**(`check_failed_units.py`) | 子进程自己发 severe | 计 n(`NOTIFY_SENT`) | **本轮修的主漏点** |
| P1-U10 | **4252 `--flush-warnings`** | 真发聚合批发 | sent 计 1 / noop·failed 计 0 / 判不出计 1 | **本轮修的主漏点** |
| P1-U11 | **4312 `--flush-digest`** | 真发当日摘要 | 同上 | 举一反三补的同类漏点 |
| P1-U12 | 1248 状态说明自身 | 真发 | 不计(自指) | 它就是判定结果,计入会自己压自己 |

其它上下游:

| # | 来源 | 边界项 | 判定 | 依据与理由 |
|---|---|---|---|---|
| P1-U13 | notify.py 接口 | 两条批发的结果文件 status 语义 | 测(用例+直读代码) | flush 分支:真发 ⇒ `sent`,没到期条目 ⇒ `noop`;发送逻辑一字未改 |
| P1-U14 | 子进程接口 | CFU 标记是 stdout 独立行,不是日志抠字 | 测 | 正则 `^NOTIFY_SENT=(\d+)$`(MULTILINE);`告警已发出 NOTIFY_SENT=1` 这种前缀行不算(I2) |
| P1-U15 | alert_ack.py | `--list/--ack` 会把 `conclusion_status|` 键当 active 列出/可 ack | 不测/不改(超范围) | 只是显示噪声:该键不触发告警邮件、不参与恢复环;ack 只写 `acknowledged`,本逻辑不读它 ⇒ 无行为影响 |
| P1-U16 | 前端/数据产物 | 无前端、无 data 产物、无版本串 | 不测 | diff 仅 `scripts/` + 测试 + 本清单 |

### 10.5 极端值

| # | 来源 | 边界项 | 判定 | 依据与理由 |
|---|---|---|---|---|
| P1-E1 | 标记值 | `NOTIFY_SENT=` 后接超大数(理论上) | 不测(无判定影响) | 只判 `> 0`;整数解析不溢出(任意精度) |
| P1-E2 | 结果文件 | 损坏 JSON / 不存在 / 无 `status` 字段 | 测 | `test_read_notify_result_status`(3 种) + `test_flush_status_mapping` 空串 |
| P1-E3 | 子进程 | 子进程超时/信号杀死 ⇒ 无标记 | 测(输入域) | I2 的 `""` 情形 ⇒ 1 保守 |
| P1-E4 | 计数溢出 | 一轮几千封邮件 | 不测(无判定影响) | 只判 `> 0` |
| P1-E5 | 子进程 rc | 子进程 rc 非 0 但确实发过(如 D1 通道 rc=4) | 测(设计) | 计数只认标记,不认 rc(标记在 `finally` 必打) |

### 10.6 回退路径

| # | 来源 | 边界项 | 判定 | 依据与理由 |
|---|---|---|---|---|
| P1-R1 | 运行时开关 | `MONITOR_CONCLUSION_STATUS_EMAIL=0` ⇒ 立即回到「只打日志」旧行为 | 测 | 开关用例 5 种取值;生产改 systemd environment 或脚本头部 export 即生效 |
| P1-R2 | 回滚顺序 | 开关置 0/删调用点**之前**必须先清生产 `data/alert_state.json` 的 `conclusion_status|*` 键 | 不测(人工约束) | 残留键会被恢复环当异常发假恢复邮件(上一轮 skip 前缀挡着;若本次连 skip 一起回滚,顺序必须先清键)。原文写死在代码注释 + 本节 |
| P1-R3 | 部署回滚 | feat revert 即恢复旧行为(无数据产物/版本串) | 不测(部署操作) | 三个脚本同 commit 部署,版本成对 |

### 10.7 并发

| # | 来源 | 边界项 | 判定 | 依据与理由 |
|---|---|---|---|---|
| P1-C1 | 计数器作用域 | `_ALERT_MAIL_COUNTER` 进程内模块级,多轮不串 | 不测(结构性) | monitor 每轮新进程;CFU 子进程有自己的一份 |
| P1-C2 | 子进程计数 | `_NOTIFY_SENT_COUNT` 若模块被同进程多次 `main()` | 测(设计) | 用例里显式清零;生产一次进程一次 main |
| P1-C3 | state 并发写 | 两个 monitor 实例同时写 `alert_state.json` | 不测(既有风险 D10) | 沿用既有单实例 15min 机制,本批不新增共享写目标;`save_alert_state` 原子性未动 |
| P1-C4 | 测试隔离 | 变异改生产文件与并行测试互扰 | 测(收尾核) | 3 次变异各自 `git checkout --` 还原,还原后 `git status --porcelain` 无输出 |

### 10.8 本轮测/不测小结 + 审查 D 项处置

- 测:51 条用例(原 20 条全保留 + 31 条新增);不测 9 项,均给理由(无判定影响 / 结构
  性 / 既有风险 / 人工回滚约束 / 超范围)。
- 判别力证据(3 次变异,每次改坏 → 跑目标文件 → 还原 → 复查):
  1. 删 CFU 累加行(`+= _cfu_alert_mail_delta(...)` → `pass`)⇒ 1 红
     (`test_decision_point_is_after_all_send_channels`)⇒ 还原 51 绿;
  2. 两条批发计数写死空串(不读结果文件 status)⇒ 1 红(同一条形状护栏)⇒ 还原 51 绿;
  3. 恢复环跳过前缀改 `if False:` ⇒ 2 红(形状 + **行为级**),日志实测打出
     `[recovery] conclusion_status ... 已消失`(= 真会发假恢复邮件)⇒ 还原 51 绿。
  三次还原后 `git status --porcelain` 无输出(无残留)。
- 全量回归:`python -m pytest -q scripts/tests/` ⇒ **1622 passed, 2 skipped**(基线
  1591 passed + 2 skipped,差额 31 = 本批新增用例数,零回归)。

审查 D1-D11 处置(逐条):

| D | 结论 | 说明 |
|---|---|---|
| D1 计数须覆盖全部真发通道 | 已修 | 六通道累计(U1/U4/U6/U9/U10/U11)+ 判定点后移;同类面 U1-U12 逐个核对 |
| D2 摘要键稳定性 | 保持现状 | 键=`conclusion_status|`+md5 前 8 位,内容变即换键;用例覆盖,无需改码 |
| D3 非数字/None 入参 | 已修 | `_alert_mail_count` 防御,4 类坏值按 1 保守,不抛异常 |
| D4 alert_ack 显示噪声 | 不改(记录) | 只是 `--list` 多一条;不触发邮件、不影响判定(U15) |
| D5 `--alert-issue` 覆盖 latest.md 详情区 | 超范围未改 | 任务书点名不做(P2),另行处理 |
| D6 `[状态说明]` 飞书群路由 | 超范围未改 | 任务书点名不做(P2 飞书路由) |
| D7 `&` 未转义 | 已修 | 转义顺序 `&` 最先,用例断言 `a && b &amp; c` → `a &amp;&amp; b &amp;amp; c` |
| D8 「只发一次」措辞不准 | 已修 | 改为「同一份结论内容只发一次;结论内容变了会再发一次」,用例钉死 |
| D9 无运行时开关 | 已加 | `MONITOR_CONCLUSION_STATUS_EMAIL`(默认开,0/false/off/no 关)+ 回滚顺序(R2) |
| D10 save_alert_state 非原子/并发双发 | 不改(记录) | 既有风险,独立任务;本批未动写盘逻辑(C3) |
| D11 时钟回拨 | 不改 | 冷却判定负数 ⇒ 抑制重发 = 保守侧(T5) |

## 11. 复审 F1-F7 定点修复(2026-10-26)

> 触发 = 第二轮独立审查 PASS 后的非阻塞项。改动面:`scripts/schedule_monitor.sh`(F2 加
> try/except 外壳 + F3/F4 注释订正)、`scripts/tests/test_309_conclusion_email_20261026.py`
> (F1 实参钉死 + F2 行为用例,51 → 53 条)、本清单(F6 回滚清单 + F5/F7 已知项)。
> 全程 static-only(不真发邮件/飞书,§18 L48);云上只读。F1/F2 各做一次「改坏 → 红 →
> 还原 → 绿」判别力实测,还原后文件 sha256 与改前一致。

### 11.1 输入域

| # | 来源 | 边界项 | 判定 | 依据与理由 |
|---|---|---|---|---|
| V1-I1 | F1 实参钉死 | 把 `_cfu_alert_mail_delta(_cfu_out)` 的实参改成空串 `""` | 测(判别力实测) | 变异后 `test_cfu_delta_receives_real_cfu_subprocess_output` 红(实参是 `ast.Constant(value='')` 而非 `ast.Name`);还原 53 绿 + sha256 一致 |
| V1-I2 | F1 实参来源 | 实参换成"另一个同名空变量"/常量/切片等绕法 | 测(结构全链) | 用例除「必须是变量」外,还钉死该变量 = `<子进程 stdout or ''>.strip()`,且该子进程命令常量含 `check_failed_units.py` ⇒ 换变量/改来源都红。比「断言实参含 NOTIFY_SENT= 片段」更严(直接钉生产者,不依赖样本长得像) |
| V1-I3 | F2 异常类型 | 恢复块内 `subprocess.run` 抛 `TimeoutExpired` | 测(行为) | `test_recovery_block_exception_does_not_block_status_mail`:AST 提取生产 try 块**原样 exec**(非第二份实现),注入抛超时的 subprocess 替身 ⇒ stderr 有「恢复邮件发送段异常 / TimeoutExpired / 状态说明心跳照常」,随后真的发出 1 封状态说明 |
| V1-I4 | F2 异常类型 | 其它 `Exception` 子类(AttributeError/KeyError/OSError…) | 不测(同一处理器) | 处理器是 `except Exception as _e_rec`,与 I3 同一路径;不另造第二份样本 |
| V1-I5 | F2 异常类型 | `BaseException`(KeyboardInterrupt/SystemExit/信号) | 不测(有意不捕获) | 进程被信号终止/系统退出应保留原有行为,不许伪装成"继续跑" |

### 11.2 状态组合

| # | 来源 | 边界项 | 判定 | 依据与理由 |
|---|---|---|---|---|
| V1-S1 | F2 | 异常发生在第一个批次(alert 批)发送时 | 测 | I3 即此形态(第一批 `_send_recovery_batch` 就抛) |
| V1-S2 | F2 | 异常发生在 warning 批 / 两批之间 / pending 落盘时 | 不测(同块处理器) | 整块同一个 try,处理动作相同(只打日志继续);任务书要求"只加外壳"不动发送/落签逻辑 |
| V1-S3 | F2 已知限制 | 异常轮已翻 recovered 的条目本轮不发恢复、也不进 pending ⇒ 该批恢复通知丢失 | 不测(与旧行为同向,不因外壳变差) | 旧代码整进程崩:恢复通知同样丢失,还额外丢状态说明与心跳。外壳只补回后者;任务书点名不改恢复语义 |
| V1-S4 | F3 | 环境开关置 0 时 `alert_state` 里残留 `conclusion_status|*` 键 | 测(读码确认) | 开关只停「判定/发信/写 state」;恢复环 `if _key.startswith(CONCLUSION_STATUS_KEY_PREFIX): continue` 仍在 ⇒ 残留键不会被当异常消失 ⇒ **不发假恢复**,无需先清键 |
| V1-S5 | F3 | 删代码/整块回滚(连 skip 行一起删)且残留键未清 | 测(既有行为用例) | `test_recovery_loop_behavior_skips_conclusion_status_key` 的反向即此:S4 的 continue 一旦没有,键会翻 recovered ⇒ 假恢复邮件 ⇒ 必须先清键 |

### 11.3 时序

| # | 来源 | 边界项 | 判定 | 依据与理由 |
|---|---|---|---|---|
| V1-T1 | F2 | 恢复块异常后,本轮结论判定与心跳仍执行 | 测(行为) | 用例断言 `_concl_email` 赋值行号 > try 块结束行,并真跑出状态说明(1 次 notify 调用) |
| V1-T2 | F1/F2 用例时间 | 用例取真实 `today()/now()` 致隔天红(L51) | 测(静态核) | 全部用冻结 `NOW=2026-10-26 09:42`;新增两条用例不取实时时间 |
| V1-T3 | F2 | 异常发生在 CFU/批发计数之后、判定之前 | 不测(顺序固定) | 计数点在恢复块之前;外壳没有移动任何调用点 |

### 11.4 上下游

| # | 来源 | 边界项 | 判定 | 依据与理由 |
|---|---|---|---|---|
| V1-U1 | F1 | `_cfu_out` 的生产者链 | 测(AST 三层) | 实参变量 → `<stdout or ''>.strip()` → `subprocess.run([...check_failed_units.py...])`,逐层断言,任何一环被替换都红 |
| V1-U2 | F2 | 下游 `_PEND_KEY` / `save_alert_state` | 不测(不改) | 成功路径原样;异常路径不写 pending(见 S3),外壳未新增写点 |
| V1-U3 | F3/F4 | 运行时判定行为 | 不测(纯注释/docstring) | 只改说明文字;`_conclusion_email_enabled` 取值逻辑一字未动(既有开/关用例仍绿) |
| V1-U4 | 同类错误面 | 尾部收尾序列里其它"块内异常会整轮静默"的位置 | 不测(已逐处核) | 逐个读码核 4183-4400:CFU/s06/preupload/心跳/flush-warnings/补列/flush-digest/alert_meter **都已有 try/except**;唯一裸块 = 恢复发送段 ⇒ 本次补齐。结论 helper 自身 try 在 `_maybe_send_conclusion_status_email` 内 |
| V1-U5 | F6 | 三文件成对契约 | 不测(人工回滚约束) | 见 11.6 R3 |

### 11.5 极端值

| # | 来源 | 边界项 | 判定 | 依据与理由 |
|---|---|---|---|---|
| V1-E1 | F2 | 异常消息超长/含命令全文 | 不测(不影响判定) | 只打 stderr(`{type}: {e}` 原样),无外发、不改状态 |
| V1-E2 | F1 | CFU 输出超长/多行/无标记 | 不测(无判定影响) | 用例只钉"实参来自真实 stdout",长度无关;标记缺失的保守语义由既有 I2 覆盖 |
| V1-E3 | F2 | 日志 `print` 本身失败 | 不测(理论不可达) | 写 stderr,无外发链路 |

### 11.6 回退路径(含 F6 三文件成对关系)

| # | 来源 | 边界项 | 判定 | 依据与理由 |
|---|---|---|---|---|
| V1-R1 | F1 回滚 | 新增用例删掉即回旧 | 测(性质) | 生产代码未因 F1 改动 ⇒ 回滚只影响测试覆盖 |
| V1-R2 | F2 回滚 | 去掉 try/except 外壳 | 测(判别力实测) | 变异整块去壳 ⇒ 1 红(`..._does_not_block_status_mail` 找不到 try);还原 53 绿 + sha256 一致 |
| V1-R3 | **F6 三文件成对** | `scripts/check_failed_units.py`(`NOTIFY_SENT=<n>` 标记)/ `scripts/notify.py`(两条批发的 `--result-file` status)/ `scripts/schedule_monitor.sh`(计数 + 判定点) | **不测(人工回滚约束,写死)** | **回滚必须三文件一起回,或整体 `git revert` 本批 commit;只回滚其中一处 = 语义错位(②永远不发状态说明 / ③少计 1 封 ⇒ 多发假「零外发」说明)。** 逐组合说明:①只回滚 monitor(另两处留新)⇒ 标记/结果文件没人读,无副作用但新功能也没了;②只回滚 CFU 标记 ⇒ 健康轮没有 `NOTIFY_SENT=0`,`_cfu_alert_mail_delta` 判不出 ⇒ 恒按 1 ⇒ 每轮都当"已发过" ⇒ **永远不发状态说明**;③只回滚 notify 结果标注(`--result-file` 机制 base 已有,base 的两条批发恒写 `status=noop`)⇒ flush **真发出也标 noop** ⇒ `_read_notify_result_status` 读到 `"noop"`(不是空)⇒ `_flush_alert_mail_delta("noop")=0` ⇒ **少计 1 封** ⇒ 若同轮结论异常且其余通道零外发,会误判「零告警邮件」⇒ **多发一封假称「本轮没有任何告警被真正外发」的状态说明 —— 正好是 P1 漏点 2 的复发形态**;**不是「永久静默」**。三处是同一契约的三个半边,拆开部署即语义错位 |
| V1-R4 | F3 开关回滚 | 开关置 0 与删代码的顺序 | 不测(人工约束) | 开关=0 **无需**清键(S4);删代码**必须**先清键(S5)。代码注释 + 本节双处写死 |
| V1-R5 | 部署回滚 | `git revert` 本批 commit | 不测(部署操作) | 无数据产物 / 前端版本串改动 |

### 11.7 并发与重入

| # | 来源 | 边界项 | 判定 | 依据与理由 |
|---|---|---|---|---|
| V1-C1 | 测试隔离 | 变异改生产文件与其它用例并发读 | 测(收尾核) | 每次变异前备份 `/tmp/sm-309-backup.sh`,变异后 `cp` 还原 + sha256 比对一致 |
| V1-C2 | 变量作用域 | 新增 `_e_rec` 与既有变量撞名 | 测(grep) | `grep -n _e_rec` 仅处理器内 3 处,无同名复用 |
| V1-C3 | state 并发写 | 两 monitor 实例同时写 `alert_state.json` | 不测(既有风险 D10) | 外壳不新增写点 |

### 11.8 F1-F7 逐条处置

| 项 | 处置 | 说明 |
|---|---|---|
| F1 测试假绿(实参没钉住) | 已修 | 新增 `test_cfu_delta_receives_real_cfu_subprocess_output`:AST 三层钉死「实参 = CFU 子进程真实 stdout」;判别力实测(改 `""` ⇒ 1 红 ⇒ 还原 53 绿) |
| F2 恢复块无 try/except | 已修 | 只加外壳(`try: if _combined: … except Exception as _e_rec:`),异常打日志含类型与原因并继续;发送/落签逻辑未动;行为用例证明异常后状态说明照发 |
| F3 回滚注释与实测不符 | 已改 | 注释改为两条路分开写:开关=0 跳过行还在 ⇒ 不清键也不会发假恢复;删代码/整块回滚必须先清键 |
| F4 开关取值口径没写明 | 已补 | `_conclusion_email_enabled` docstring 写明:除 0/false/off/no(忽略大小写与首尾空格)外,其它任何值(含空串/非法值)一律视为开启 |
| F5 rc=4 时 `[:240]` 可能带出 `NOTIFY_SENT=0` 进正文 | 不改(已知项) | 纯展示噪声:计数只认标记行,不影响判定;改正文截断属发送内容调整,超出本次"只加外壳/注释"范围 |
| F6 回滚清单 | 已写死 | 见 11.6 R3:三文件成对,只回滚一处 = 语义错位(②永远不发状态说明 / ③少计 1 封 ⇒ 多发假「零外发」说明) |
| F7 `monitor_72h.sh` 也 flush-warnings,云上无对应 timer | 不改(已知项) | 云上无该 timer ⇒ 不与主 monitor 的 flush 竞争;若将来上云需同步计数口径,记录在案 |

### 11.9 本轮测/不测小结 + 判别力

- 新增边界项:测 8 项、不测 9 项(每条给理由:同处理器 / 有意不捕获 / 不改逻辑 /
  既有风险 / 人工回滚约束 / 无判定影响 / 理论不可达)。
- 判别力 2 次(每次改坏 → 跑目标文件 → 还原 → sha256 核对):
  1. F1 实参改 `""` ⇒ 1 红(`test_cfu_delta_receives_real_cfu_subprocess_output`)⇒ 还原 53 绿;
  2. F2 整块去壳 ⇒ 1 红(`test_recovery_block_exception_does_not_block_status_mail`)⇒ 还原 53 绿。
  两次还原后 `git status --porcelain` 仅本批预期改动,无残留。
- 全量回归:`python -m pytest -q scripts/tests/` 数字见实施报告(基线 1622 passed, 2 skipped)。
