# 告警 checker 四元组登记表 — 2026-10-15(#264 包3「治理」件F)

> 依据:`docs/ops/alert-noise-rca-20261015.md` §2.2③(告警面扩张快于降噪)+ §4.1 F。
> 目的:把「告警面扩张」纳入预算 —— **每个告警产生点必须声明四元组**「默认 tier / dedup window / 聚合域 / 首报策略」,缺一不上线。
> 盘点口径:仓内 `scripts/` 下**实际调用 notify.py 发外发告警**的脚本(读源码逐点取参,非文档推断)+ 云上 systemd timer 清单(`ssh 云上 systemctl list-timers`,只读)。
> 云上机器:`122.51.111.173`(`/home/ubuntu/code/trade-data`)。行号为 2026-10-15 仓内文件实测。
> **本表为「盘点快照」**:登表值取自各脚本当前源码;后续改 checker 须同步改本表。
> **盘点方法(可复现)**:`python3 scripts/alert_weekly_review.py --check-four-tuple --scripts-dir scripts`(静态扫,不执行任何脚本;2026-10-16 修扫描器「注释假 OK/`=0` 等号漏检」后实产 **49 候选 / 15 缺项**;**剔除 2 假阳性**(→47 真产生点)= `check_ds_resilience.py` 模块 load 非调用、`cloud_unit_patrol_selftest.sh` 自测桩。修前为 14 缺项,增量 +1 = #26 `r2_upload_skip_notify.sh`:其 `--severe` 只在注释里(真调用无 tier),旧版全文字串判定把它误判 `[OK ]`,修后如实检出「缺 tier」)。

## 0. 四元组定义(登记列口径)

| 列 | 含义 | 取值域 | 依据 |
|---|---|---|---|
| **默认 tier** | notify.py `--tier`/`--severe` 决定的告警档 | `critical`(--severe 或无 tier 走 send() 旧行为)/`warning`(入 30min 聚合 buffer)/`info`(只落 dashboard) | `notify.py` L2596/L2598 注释 |
| **dedup window** | `--dedup-key` + `--dedup-window` 去重窗(秒) | 秒数;`0`=**关死抑制**(每次必发,⚠️ 违规值);缺=未声明 | `notify.py` L2618/L2620;L1479 `window<=0 → 不抑制` |
| **聚合域** | 该告警归属的故障域(供 group_by / 域 inhibition 用) | 见 §1 建议域表 | RCA §4.1 C;**待 264b(aggregate-budget 包)定稿对齐** |
| **首报策略** | 当日**新 key 首报**是否必达 | `首报必达`(新 key 直发,不受预算/聚合吞)/`入聚合`(首报即进 warning buffer/摘要)/`业务流`(非故障,应分流) | 收敛计划不变式 1/3(首报必达、新 key 永远直发) |

## 1. 建议域表(聚合域取值域,`待 264b 定稿`)

> RCA §4.1 C 只给了「R2/双树、快照、部署、采集、kelly…」的示例域。下表是本次盘点据此**归并**的建议域集(每个告警点先归入一个域,供 264b 的 group_by 复用);**264b(aggregate-budget 包)定稿前,本列标注为「建议·待对齐」,不作为最终口径**。

| 域 key | 域名 | 覆盖 checker(示例) |
|---|---|---|
| `monitor` | 监控链(元监控) | schedule_monitor / check_monitor_heartbeat / check_failed_units / agent_inbox_watcher / uptime_check(孤儿) / monitor_72h(孤儿) |
| `r2` | R2 存储 / 多源一致性(双树) | check_r2_consistency / intraday_snapshot / r2_upload_async / r2_upload_skip_notify / fund_nav_upload_async |
| `snapshot` | 快照 | s06_snapshot / check_s06_freshness |
| `deploy` | 部署 / unit 漂移 / 版本一致性 | deploy / cloud_unit_patrol / pick_repo / update_lab / push_schedule_stats |
| `collect` | 采集 / 回采 / 锁跳过 | update_all / retry_failed_metrics / self_heal / gold_night / turnover_backfill / with_lock / feishu_missed_fetch / 锁跳过类 |
| `kelly` | 信号凯利(回测/冻结表/盘中闸) | kelly_intraday_gate_decider / kelly_intraday_rerun / signal_kelly_backtest |
| `plan` | 次日计划 / 缺口 | nextday_plan_generator / nextday_plan.sh / nextday_gap_check(.py/.sh) |
| `backup` | 备份(DB/staticdata/R2 演练) | backup_db / verify_backup / check_preupload_backup / staticdata_backup_async / staticdata_sync / alert_denoise_rules(R4) |
| `data-gap` | 数据缺口 | check_data_gap_alerts |
| `business` | 业务订阅(**非故障,应分流**) | brief_push_wrapper / detect_intraday_anomaly / 买卖点 / 速递 |
| `proxy` | 代理链路 | sensenova-proxy-healthcheck |

## 2. 四元组矩阵(F-① 实产)

> 「缺项」列:标注四元组中**未显式声明**或**取值违规**的项。`—` = 四列齐且取值合规。
> **口径**:本表覆盖**全部实调 notify.py 发外发告警**的产生点(47 个真实产生点 = 扫描 49 − 2 假阳性)。

### 2.1 故障告警 checker

| # | 脚本 | 触发方式 / 时点 | 默认 tier | dedup window | 聚合域(建议·待对齐) | 首报策略 | 缺项 |
|---|---|---|---|---|---|---|---|
| 1 | `check_failed_units.py`(#196 patrol) | `trade-cloud-unit-patrol.timer` 08:27 | critical(`--severe`) | **0** ⚠️ | `monitor` | 首报必达 | **2026-10-21 已修黑洞**:window=0 仍为「集合有变立即报」设计值(去重由脚本自管),升级档 72h 窗只抑制同一对象重复升级、suppress 时落回普通首报路径;落状态判据改为 notify `--result-file` 的 `status=sent`,未送达出口码=4。**2026-10-22(#280)**:新增可配置白名单 `docs/deploy/failed-unit-allowlist.txt`(命中只打 `[INFO] 白名单忽略`,不进告警);白名单禁含 trade-*;净 rc 可能与 D1 通道合并(见 1b) |
| 1b | `check_failed_units.py` 内 D1 同步失败通道(#275) | 同一巡逻(`trade-cloud-unit-patrol.timer` 08:27/15min 链) | critical(`--severe`) | **0**(自管:alerted 标记 = 每个连续失败段只报一次) | `collect` | 首报必达(连续 ≥2 次才报) | 无(四元组显式声明于代码 `d1_sync_state.py`;告警未送达 rc=4 不落 alerted,下轮重试;dry 不动状态) |
| 2 | `cloud_unit_patrol.sh` | `trade-cloud-unit-patrol.timer` 08:27 | critical(`--severe`) | 21600 | `deploy` | 首报必达 | 聚合域待对齐 |
| 3 | `check_data_gap_alerts.py` | `trade-check-data-gap.timer` 22:35 | critical(`--severe`)/warning(子项) | 86400 | `data-gap` | 首报必达 | 聚合域待对齐 |
| 4 | `check_monitor_heartbeat.py` | `trade-check-monitor-heartbeat.timer` 每 15min | critical(`--severe`) | 3600 | `monitor` | 首报必达 | — |
| 5 | `check_s06_freshness.py` | schedule_monitor 尾部(每 15min) | warning | **未声明**(自管 `_state_matches` 落签,无 `--dedup-key`) | `snapshot` | 入聚合 | **dedup window 未声明** |
| 6 | `check_preupload_backup.py` | schedule_monitor 尾部 | warning | 21600 | `backup` | 入聚合 | — |
| 7 | `check_r2_consistency.sh` | `trade-r2-consistency.timer` 23:20 | critical(`--severe`) | 21600 | `r2` | 首报必达 | — |
| 8 | `nextday_gap_check.py` | `trade-nextday-gap-check.timer` 09:26 | critical(`--severe`) | 3600 | `plan` | 首报必达 | — |
| 9 | `nextday_gap_check.sh`(包装层) | `trade-nextday-gap-check.timer` 09:26 | critical(`--severe`) | 3600 | `plan` | 首报必达 | — |
| 10 | `nextday_plan_generator.py` | `trade-nextday-plan.timer` 22:30 | critical(`--severe`) | 3600 | `plan` | 首报必达 | — |
| 11 | `nextday_plan.sh`(包装层) | `trade-nextday-plan.timer` 22:30 | critical(`--severe`) | 3600 | `plan` | 首报必达 | — |
| 12 | `overfit_monitor.py` | `trade-overfit-monitor.timer` 21:40 | WARN→notice / SEVERE→critical | 86400 | `monitor` | 首报必达 | 聚合域待对齐 |
| 13 | `kelly_intraday_gate_decider.py` | `trade-kelly-intraday-rerun.timer` 09:40 | warning | 1800 / 21600 / 86400 / 7d(按子类) | `kelly` | 首报必达 | — |
| 14 | `kelly_intraday_rerun.sh` | `trade-kelly-intraday-rerun.timer` 09:40 | warning / critical(`--severe`,失败分支) | 1800 | `kelly` | 首报必达 | — |
| 15 | `alert_denoise_rules.py`(R4 状态写失败) | 各调用点(备份链) | warning | 86400 | `backup` | 入聚合 | — |
| 16 | `schedule_monitor.sh` | `trade-schedule-monitor.timer` 每 15min | warning / critical | 21600(r2-skip/恢复各自键);进程内 `alert_state` 键见 §2.3 | `monitor` | 首报必达 | 聚合域待对齐 |
| 17 | `retry_failed_metrics.py` | schedule_monitor | warning | 21600 | `collect` | 入聚合 | — |
| 18 | `self_heal.sh` | `trade-self-heal.timer` 每 15min | info(达上限只落盘) | **未声明** | `collect` | — | **dedup window / 聚合域未声明** |
| 19 | `update_all.sh` | `trade-update-all.timer` 17:50 | critical(`--severe`) | 1800 | `collect` | 首报必达 | 聚合域待对齐 |
| 20 | `s06_snapshot.sh` | `trade-s06-snapshot.timer` 20:35 | critical(`--severe`) | 3600 | `snapshot` | 首报必达 | — |
| 21 | `intraday_snapshot.sh` | `trade-intraday-snapshot.timer`(交易日盘中 09:25 起) | critical(`--severe`) | 1800 | `r2` | 首报必达 | — |
| 22 | `backup_db.sh` | `trade-backup-db.timer` 21:00 | critical(`--severe`) | **未声明** | `backup` | 首报必达 | **dedup window 未声明** |
| 23 | `verify_backup.sh` | schedule_monitor / 备份链 | critical(`--severe`) | **未声明** | `backup` | 首报必达 | **dedup window 未声明** |
| 24 | `on_skip_notify.sh` | update_all 锁跳过 | critical(`--severe`) | **未声明** | `collect` | 首报必达 | **dedup window / 聚合域未声明** |
| 25 | `turnover_backfill_skip_notify.sh` | turnover 锁跳过 | critical(`--severe`) | **未声明** | `collect` | 首报必达 | **dedup window / 聚合域未声明** |
| 26 | `r2_upload_skip_notify.sh` | r2_upload_async 锁跳过 | **未声明**(无 `--tier`/`--severe`) | 21600 | `r2` | 首报必达 | **tier / 聚合域未声明** |
| 27 | `pick_repo.py`(写错树守卫) | 各调用点 | critical(`--severe`) | **未声明** | `deploy` | 首报必达 | **dedup window / 聚合域未声明** |
| 28 | `with_lock.py`(锁排队超时) | update_all / r2_upload 锁跳过 | warning | 21600 | `collect` | 首报必达 | 聚合域待对齐 |
| 29 | `agent_inbox_watcher.py`(状态写失败) | 本机 watcher(codex review 链) | warning | 86400 | `monitor` | 首报必达 | 聚合域待对齐 |
| 30 | `feishu_missed_fetch.py`(游标写失败) | 独立 CLI / 采集链 | warning | 86400 | `collect` | 首报必达 | 聚合域待对齐 |
| 31 | `gold_night.sh` | `trade-gold-night.timer` 02:40 | critical(`--severe`) | 3600 | `collect` | 首报必达 | 聚合域待对齐 |
| 32 | `turnover_backfill.sh` | `trade-turnover-backfill.timer` 21:10 | critical(`--severe`) | 3600 / 3600 | `collect` | 首报必达 | 聚合域待对齐;**2 个告警点**:链路失败 + 预算自检 FATAL(`turnover_backfill_budget_fatal`,2026-10-30 #364 补),同 tier/窗/域/首报 |
| 33 | `update_lab.sh` | `trade-lab-auto.timer` 19:00 | critical(`--severe`) | 1800 | `deploy` | 首报必达 | 聚合域待对齐 |
| 34 | `deploy.sh` | `trade-update-all.timer` 17:50(update_all 主链)+ main-merge | critical(`--severe`) | 21600 | `deploy` | 首报必达 | 聚合域待对齐 |
| 35 | `r2_upload_async.sh` | update_all 段1 异步任务 | critical(`--severe`) | 21600 / 1800 | `r2` | 首报必达 | 聚合域待对齐 |
| 36 | `fund_nav_upload_async.sh` | update_all 异步任务 | critical(`--severe`) | 3600 | `r2` | 首报必达 | 聚合域待对齐 |
| 37 | `staticdata_backup_async.sh` | update_all 异步任务 | **未声明**(守卫类告警路径 L223/L302/L329 无 tier;失败分支有 `--severe`、超阈值分支有 `--tier info`) | 21600 | `backup` | 首报必达 | **tier 未声明 / 聚合域待对齐** |
| 38 | `staticdata_sync.sh` | deploy / staticdata 链 | **未声明**(守卫类告警路径 L155/L174 无 tier;超阈值分支有 `--tier info`) | 21600 | `backup` | 首报必达 | **tier 未声明 / 聚合域待对齐** |
| 39 | `push_schedule_stats.sh` | deploy 链(独立推 schedule_stats) | critical(`--severe`) | 1800 | `deploy` | 首报必达 | 聚合域待对齐 |
| 40 | `brief_push_wrapper.sh` | `trade-brief-push.timer` 20:45 | critical(`--severe`) | 21600 | `business` | 首报必达 | 聚合域待对齐 |
| 41 | `sensenova-proxy-healthcheck.py` | mac launchd(本机,非云 timer) | critical(`--severe`,主告警 L144-146/177)/warning(`--tier warning`,状态写失败 L125-127) | 86400(状态写失败分支);主告警路径无 `--dedup-key`(靠状态机 fired/recovered 自管,类比 #5) | `proxy` | 首报必达 | 聚合域待对齐 |
| 42 | `signal_kelly_backtest.py` | kelly 盘中回测链 | critical(`--severe`,`_alert_frozen_missing` 大事件分支)/**未声明**(小缺口、`_alert_freeze_orphans` 孤儿买分支) | 3600(大事件)/86400(小缺口、孤儿买) | `kelly` | 首报必达 | 聚合域待对齐;⚠️ **孤儿买分支 2026-10-16 #252-A4 起在云上开启**(云 `.env` `SIGNAL_KELLY_FREEZE_ORPHAN_ALERT=1`), 只报到**未登记**的新孤儿 —— 已进 `config/signal_kelly_freeze_orphan_backfill.json` 补账登记表的孤儿不计入(防同一批每日重复报); 台账 `docs/ops/252-freeze-orphan-backfill-20261016.md` |
| 43 | `uptime_check.sh` ⚠️**孤儿** | **无触发链**(#210 观察盲区) | critical(`--severe`) | **未声明** | `monitor` | 首报必达 | **dedup window / 聚合域未声明 + 无触发=观察盲区** |
| 44 | `monitor_72h.sh` ⚠️**孤儿** | **无触发链**(#210;本机 launchd 已自卸载) | critical(`--severe`) | **未声明** | `monitor` | 首报必达 | **dedup window / 聚合域未声明 + 无触发=观察盲区** |
| 45※ | `check_sentiment_r2_upload.py`(#231 H1,**链尾收口**,2026-10-17 新增) | `intraday_snapshot.sh` 链尾(盘中每轮,非独立 timer) | critical(`--severe`) | 1800 | `r2` | 首报必达 | —(四元组自本表起线后首个全声明条目) |
| 46※ | `deploy.sh`(**连续部署失败聚合档**,2026-10-21 新增) | deploy.sh EXIT trap(每次部署结果;成功清零) | critical(`--severe`) | 21600 | `deploy` | 首报必达(跨过阈值那一次必发) | —(四元组全声明;状态 `data/deploy_fail_state.json`,阈值默认 2,env `DEPLOY_FAIL_ALERT_THRESHOLD` 可配) |
| 47※ | `deploy.sh`(**仅告警级校验失败**,2026-10-21 新增) | check_data_integrity rc=3(上游独立产物缺/滞后, deploy 不退出) | notice(send() 旧行为, **未加 `--severe`**) | 21600 | `deploy` | 首报必达 | tier 走 send() 旧行为(与 #46 刻意区分: 阻断级才 severe);清单见 `check_data_integrity.ALERT_ONLY_CHECKS` |

> ※ 编号说明:#45 在 §2.2(业务订阅表)已被 `detect_intraday_anomaly.py` 占用;本行属**故障告警表**(§2.1),两表独立计数,引用时请写「§2.1 #45※」以免混淆。#46※/#47※ 同此约定(§2.2 的 46/47 是 run_daily_brief / gen_daily_brief)。

> 说明:#43/#44 是**孤儿 checker**(脚本存在、能发告警,但云上无 timer/无调用方触发)——2026-10-06 #195 批2 已登记 #210;「有告警能力但从不跑」= 观察盲区,须一并纳入治理。

### 2.2 业务订阅/报告(非故障,`business` 域,应分流 — 不计入「告警面」扩张考核)

| # | 脚本 | 触发方式 / 时点 | 默认 tier | dedup window | 聚合域(建议) | 首报策略 | 缺项 |
|---|---|---|---|---|---|---|---|
| 45 | `detect_intraday_anomaly.py` | intraday_snapshot.sh(盘中) | warning(非 severe,提示性) | 86400(状态写失败分支) | `business` | **业务流** | 聚合域=业务(应分流) |
| 46 | `run_daily_brief.sh` | `trade-daily-brief.timer` 20:40 | **未声明**(`--from-prefix "[告警]"`,非 severe) | 1800 | `business` | 首报必达 | **tier 未声明(走 send() 旧行为)** |
| 47 | `gen_daily_brief.py` | trade-daily-brief 链 | **未声明**(同日 dedup) | 同日(自管) | `business` | 业务流 | tier / 聚合域未声明 |
| — | 买卖点/速递/计划等(notify.py subscribe 分支) | check_signals / brief_push 等 | subscribe(独立渠道) | 自管 | `business` | 业务流 | 归 `subscribe` tier(已独立) |

## 3. 缺项清单(汇总,供 264b/后续收口)

**A. dedup window 未声明(10 处)**:`check_s06_freshness`、`self_heal`、`backup_db`、`verify_backup`、`on_skip_notify`、`turnover_backfill_skip_notify`、`pick_repo`、`uptime_check`、`monitor_72h`、`sensenova-proxy-healthcheck`(其中 #5/#18 为自管落签、#22/#23 触发频次低、#41 主告警路径靠状态机自管)。
**B. dedup window 取值违规(=0 关死抑制,1 处)**:`check_failed_units.py`(RCA §2.2④.a 已立案 → A 包修复);其 2026-10-22 新增的 D1 通道同样用 0,但**去重由脚本自管(每连续失败段只报一次)**,属设计值而非关死抑制(见 §2.1 行 1b)。
**C. 默认 tier 未声明(走 send() 旧行为,5 处)**:`r2_upload_skip_notify`、`staticdata_backup_async`、`staticdata_sync`、`run_daily_brief`、`gen_daily_brief`。

> **A/C 判定口径(2026-10-16 复核订正,逐轴独立判)**:按「**默认告警路径**(常规、非降级、非 opt-in 的告警路径)是否显式声明」判定;**注释里提及不算声明**(旧版扫描器全文子串会把注释当声明 = 假 OK)。
> - 移出 A(2 处,dedup 实已声明):#26 `r2_upload_skip_notify`(L51 `--dedup-key ... --dedup-window 21600`)、#42 `signal_kelly_backtest`(L382/L385/L461 三处调用均已声明)。
> - 移出 C(2 处,tier 实已声明):#41 `sensenova-proxy-healthcheck`(L146 `--severe`、L125-127 `--tier warning`)、#42 `signal_kelly_backtest`(L381 `--severe`,小缺口/孤儿买为降级/opt-in 路径,不改变「默认告警路径已声明」判定)。
> - 保留入 C(守卫类告警路径确无 tier,属常规告警):#37 `staticdata_backup_async`、#38 `staticdata_sync`(其 `--severe`/`--tier info` 只覆盖失败/超阈值分支,守卫类告警路径仍走 send() 旧行为)。
> - **扫描器口径差异说明(对账 §2 复现命令 4)**:`alert_weekly_review.py --check-four-tuple` 按「脚本内**任一**真调用声明即算已声明」的**粗口径**,故 #37/#38 扫描器判 `[OK ]` 而本表判「缺 tier」(本表按告警路径细分,更严);对账时以本表为准,差异仅此 2 行。
**D. 聚合域未声明(全表)**:本项目**当前无域概念**(RCA §1.4/§4.1 C)⇒ 全表聚合域均为「建议·待对齐」,须 264b 定稿。
**E. 首报策略未声明(隐式)**:多数点靠「dedup 语义 = 首次无 key 记录即发出」隐式满足「首报必达」,但**未在代码/文档显式声明**,不满足「缺一不上线」的字面要求。
**F. 孤儿 checker 无触发链(2 处)**:`uptime_check.sh`、`monitor_72h.sh` —— 有告警能力但云上无触发(观察盲区,已登记 #210)。

> 说明:C/E 类在 264b(aggregate-budget)落地前属**已知缺口**,本表如实登记;新 checker 自本表起线后须显式声明四元组(见 §4)。F 类须在 264c 后续收口(补触发链或将「无触发」显式声明为不适用)。

## 4. review 强制落点(四元组缺失不上线)

**落点:`.claude/skills/role-reviewer/SKILL.md` 新增 §11(审查关硬门槛)+ `.claude/skills/role-implementer/SKILL.md` §0 清单新增第 9 条(实施侧前置声明)。**
选择理由与 diff 见实施报告 `docs/ops/alert-264c-governance-impl-20261015.md` §③。

## 5. 复现命令(只读)

```bash
# 1) 云上 timer 清单
ssh -i /Users/linhuichen/tdsignal.pem -4 -o ConnectTimeout=10 ubuntu@122.51.111.173 \
  'systemctl list-timers --all --no-pager; ls -1 /etc/systemd/system/trade-*.timer'
# 2) 仓内 notify.py 调用点
grep -rn "notify\.py" scripts/*.py scripts/*.sh | grep -vE "tests/|test_|notify_sent|^scripts/notify.py"
# 3) 各点四元组取值
grep -nE "\-\-tier|\-\-severe|\-\-dedup-key|\-\-dedup-window" scripts/<checker>
# 4) 一键静态扫描(四元组缺项,不执行任何脚本)
python3 scripts/alert_weekly_review.py --check-four-tuple --scripts-dir scripts
```

## 2.3 `schedule_monitor.sh` 进程内 `alert_state` 去重键清单(#309 同步,2026-10-25)

> 与 §2.1 的 `notify.py --dedup-key` 不是一层:这些键写在 monitor 自己的
> `alert_state`(每轮 seen/恢复检测),决定「同一故障跨轮只发一次 + 恢复发一次」。
> 改动键名/新增通道必须同步本表(否则 review 无法对账告警面)。
> 锚点 = 2026-10-25 `feat/fix-309-fake-ok-20261025` 仓内实测行号。

| 键 | tier | 产生条件 | 锚点 |
|---|---|---|---|
| `{task}\|unit_exit!=0\|{code}` | critical(SEVERE) | systemd 真值退出码非 0(覆盖全部 43 unit, 含 3 自监控);**systemd 真值失败的唯一权威通道** | 产生 `schedule_monitor.sh:1067`、消费于 `:1988` |
| `{task}\|unit_missed` | critical(SEVERE) | timer 的 `NextElapseUSecRealtime` 超 10min 宽限仍未触发;运行中(active/activating/reloading)不算 | `schedule_monitor.sh:1083` |
| `{label}\|failed_no_exit` | critical(SEVERE) | `is-active=failed` 但 stats 仍 0/未知(exit 通道失效兜底),只在 stats 覆盖的 label 上产生 | `schedule_monitor.sh:2232` |
| `{label}\|failed` | critical(SEVERE) | 自监控 label(如 self-heal)failed 且 unit 真值码读不到(降级告警);unit 通道**确实会登记**时让位给 `unit_exit!=0`(P2-4 合一) | `schedule_monitor.sh:2259`、defer 判据 `_unit_channel_will_register` `:2207-2216` |
| `{task}\|deploy_warn` | warning(聚合) | 日志 `deploy!=0` 而退出码/采集均为 0(P1-2 合并口径);直发 `notify.py --tier warning`,不进 SEVERE alerts | `schedule_monitor.sh:1264`、分级在 `gen_schedule_stats.py:_log_exit_evidence` |

> 一跳原则(P2-3):stats 刷新失败轮由 unit 通道报 `{task}|unit_exit!=0|{code}`;下轮
> stats 合并同一 code + `exit_source∈{systemd,ledger,ledger-stale}` 后,exit 通道跳过该行
> (`schedule_monitor.sh:_unit_channel_owns_row`,用例 `test_unit_channel_is_single_hop_across_stats_refresh`)。
> 旧日志键 `{task}|exit!=0|{code}` 仅保留给非 systemd 真值口径,不再与 unit 通道同轮双报。

### 2.3.1 恢复语义(2026-10-25 第三轮审查补)

> 为什么单列:去重键不只是「发不发」,还决定「恢复邮件会不会发」。恢复环的判据是
> **「alert_state 里 active 且本轮不在 `seen_keys_this_run` ⇒ 发已恢复」**。
> 键名迁移/通道让位时若忘了标 seen,就会发出与事实相反的恢复邮件(故障同轮还在)。
> 锚点:`schedule_monitor.sh:_migrate_unit_owned_keys`、恢复检测循环、用例
> `test_309_key_migration_20261025.py`。

1. **正常恢复**:故障消失 ⇒ 本轮该键不进 seen ⇒ 发「已恢复」并把状态改 `recovered`。
2. **键迁移(旧日志键 → unit 键,一次性)**:当 stats 行被 unit 通道接管
   (`_unit_channel_owns_row` 为真)时,`_migrate_unit_owned_keys` 把旧键
   `{task}|exit!=0|{旧code}` **标记为 seen 并静默退休**(状态 `recovered`,
   `recovery_reason=migrated_to_unit_key`;若码不同则 `superseded_by_new_code`),
   不再发恢复邮件;同轮由新键 `{task}|unit_exit!=0|{code}` 正常首报 SEVERE。
   验收用例断言「旧键 active + 新键首报」同轮 recovered 条数 = 0。
3. **有失败但本轮无事件**(如 `ledger-stale` 不发 SEVERE):新键仍必须标 seen,
   否则已 active 的新键会被误判「已恢复」;可见性由结论行标注兜底,不靠恢复邮件。
4. **只认 seen,不认时间**:恢复不看「多久没报」,只看本轮是否覆盖该键;因此每一轮
   所有仍然存在的故障都必须进 seen(新增通道时这是必查项)。

---
(报告完;本文件随 #264 包3 落档。生成:2026-10-15;§2.3 于 2026-10-25 #309 审查修复时同步。)
