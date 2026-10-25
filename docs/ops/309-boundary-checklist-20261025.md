# #309 审查修复 · 边界维度清单(七轴)

> 任务:修 #309 独立审查的 2 个 P1 + 8 个 P2/P3。
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
| I2 | P1-1 读取层 | `.service` 块出现 timer 专属属性(假样本养绿 L49) | 测 | `test_fixture_service_timer_shape_matches_real_systemd`:三套 fixture 硬校验 43 service 仅 8 属性、43 timer 仅 4 属性、同名配对;变异「service 塞 NextElapse」必红 |
| I3 | P1-1 读取层 | `.timer` 块自带 `Result=success` 被当成任务结果 | 测 | `test_timer_result_never_leaks_into_service_truth`;`_merge_unit_props` 白名单只取 timer 的 2 个时间属性 |
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
| S9 | 真值采信 | stats 行已判真值不可信(unit_exit/start 空 + health=unknown) | 测 | `test_untrusted_state_in_stats_row_does_not_alert` |
| S10 | P2-6 | 结论层: unknown/never-ran/no-record/missing/unknown-result 一律不判 OK | 测 | 参数化 4 个诊断源均阻断 OK;`running` 例外不阻断 |
| S11 | P2-5 | CFU failed=0 / 有 failed | 测 | 全绿 7 天 + CFU=2 展示用例 |
| S12 | 全批 | 43 unit 全绿一轮 | 测 | `test_seven_green_days_produce_no_events_and_ok`(7 天参数化, 防空转恒红) |
| S13 | P2-2 | `last_exit_tier=warning` 才走 warning 分支;0/None 不走 | 测 | `test_deploy_branch_does_nothing_for_zero_exit`、`..._non_warning_tier` |
| S14 | 全批 | 未入表 3 个自监控 unit(include=False) | 测 | `test_systemd_mode_emits_40_rows_and_43_registry` + `_unit_alert_events` 覆盖 43 |
| S15 | 全批 | stats 文件整体陈旧(行仍 0, 不是明确 unknown) | 不测(设计即兜底) | 注释:`srow` 存在且明确 unknown 才静默;整文件陈旧正是 unit 通道要报的真失败, 已有 S6 覆盖等价输入 |
| S16 | P2-4 | `self_heal` 同轮同时产生 `{label}|failed` 与 `unit_exit!=0` | 测 | S3 + S4 成对;另 `test_self_heal_alerts_again_when_unit_channel_rolled_back` 验回滚时不静默 |

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
| T8 | P2-3 | 旧日志键 `{task}|exit!=0|{code}` 曾 active 时的收尾恢复 | 不测(既有恢复环) | 键切换首轮旧键未 seen → 走既有恢复检测发一次 recovered;是本批一次性的键迁移代价, 已在登记表 §2.3 注明 |

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

## 7. 并发

| # | 来源 | 边界项 | 判定 | 依据与理由 |
|---|---|---|---|---|
| C1 | P1-1 | 43 service+43 timer 一次 show vs 逐 unit 调用的竞态窗口 | 不测 | 单次快照比多次更一致, 不新增竞态;读失败走逐 unit 兜底 |
| C2 | 全批 | monitor 15min 周期重叠/两实例同时跑 | 不测(既有) | 新增键沿用既有 `alert_state`+`seen_keys_this_run` 单实例机制, 本批不新增共享写目标;多实例非本批引入 |
| C3 | P2-2/P2-4 | 同一轮多个 label 同时 failed | 测 | 循环级用例单 label 覆盖分支;`_unit_alert_events` 对 43 全绿/单失败覆盖(多 label 为同构循环, 无跨 label 状态) |
| C4 | 测试隔离 | mutation/用例改生产文件被并行读 | 测(收尾核) | 变异脚本逐项写→跑→还原并 sha256 校验;全量 pytest 在还原后单独跑 |

## 8. 结论与未测项处置

- 测:52 项;不测:14 项(每项已给理由:既有机制/不改文件/无生产路径/仅展示长度)。
- 「不测」项若 reviewer 独立推导出遗漏, 按 §10.8 差集报主控;本清单不代替 reviewer 自查。
- 验收证据:309 专项用例全绿(条数见实施报告)、全量 pytest 数字、10 个变异点全红(见实施报告)。