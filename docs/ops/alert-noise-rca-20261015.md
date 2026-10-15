# 告警噪声根因调研(RCA)— 2026-10-15

> 调研任务:用户「告警还是太多。帮我分析下根因到底在哪。为什么一直修不好」。researcher 只读调研:云上只读、零写操作;仓内除本报告外零写;未 commit(按任务要求)。
> 数据来源:全部取自**云上权威机** `122.51.111.173`(`/home/ubuntu/code/trade-data`,含 signal 树 `/home/ubuntu/code/trade-data-signal`);不采信本机 mac 残留数据。
> 验收基线:「告警群即时消息 一天 0~3 条」(`docs/ops/alert-convergence-plan-20261010.md` L4,用户 2026-10-10 拍板)。
> 全程无后台残留任务(未出现 moved to the background)。

## 0. 摘要(结论先行)

**根因不是「某个 bug 忘了修」,而是三层结构性缺口叠加;历次修复全部在修点、没有修面:**

1. **判据层:判据挂在「持久状态」而非「当日事件」**——failed-unit 连续天数挂在 systemd 的持久 failed 状态(只有人工 `reset-failed`/重跑成功才消)⇒ 连续天数单调递增 ⇒「升级 critical」天天发;`alert_state.json` 现有 14 个恒 active 挂账节点,其中 3 个挂了 ≥2 天(overfit_monitor 自 09-24 挂 3 周、nextday_gap_check 自 10-13、s06 dur>900s 自 10-13)。
2. **发送层:没有「按故障域聚合」与 inhibition**——10-15 一个真实 R2 故障被 7~8 个脚本各自独立告警(域内 28 条);升级通道的抑制窗被调用方 `--dedup-window 0` 关死(`notify.py` L1479:`window<=0 → 不抑制`),同一枚「连续 8 天, 升级 critical」主题 10-15 当天发了 **6 次**(6 天共 18 条)。
3. **流量层:业务订阅通知与故障告警混在同一出口**——买卖点 73 + 盘中异动 33 + 速递/计划等 ≈ 40% 的量,走同一个「告警群」。

**量化(近 6 天,云上台账)**:10-10~10-15 实发 **268 条**(逐日 3/10/69/56/47/83);10-15 单日 83 条、44 critical、82 条邮件+飞书双渠道(手机可见 ≈165 条),对「0~3/天」超标约 27 倍。10-15 背后的独立事件约 14 个:1 个 R2 域故障(28 条)+ 业务流 31 条 + 升级档 6 条 + 计划任务异常 8 条 + 历史行改写 3 条 + 其余 7 条。

**为什么一直修不好(复发结构)**:①历次修复全是「被点名单点」(a_fund 循环/冻结表/verify-r2/kelly rc5),修过的点确实归零,但结构(同事件多路播报、判据挂状态)没动;②判据挂持久状态(#259 已立案未修);③**降噪机制自身在产噪**(窗口 0 的升级通道 / 跨日 rollover 重发 / L2 预算吞 severe 到 10-14 才修);④告警面扩张速度(新 checker、新故障域)快于降噪速度;⑤业务流混流;⑥双树多出口。

## 1. 现状量化(Q1)

### 1.1 数据源与口径(先钉死「数从哪来」)

| # | 数据 | 云上位置 | 口径与边界 |
|---|---|---|---|
| 1 | 全量外发台账 | `data/alerts/alert_ledger.jsonl` | 每封实际外发 1 行 {ts,tree,tier,key,subject,channels,source,group};**10-10 08:27 上线** ⇒ 之前无此数据 |
| 2 | 日计数(幂等重算) | `data/alerts/alert_daily.json` | 由台账重算;含 by_tier/by_source/by_key/merged_in_digest |
| 3 | 抑制/恢复明细 | `data/logs/schedule_monitor_launchd.log` | `[suppress]` 行只覆盖 schedule_monitor 链;notify.py 通用去重的抑制无独立计数 |
| 4 | 台账前(9-13~10-09) | 各 `data/logs/*_launchd.log` 发送明细 | 只数「实际发送」行,**漏摘要/飞书 ⇒ 低估** |
| 5 | 判据状态 | `data/failed_units_patrol_state.json` / `data/alert_state.json` | 「挂账不消」证据 |

(本次数字均可在云上按 §6 只读复现;代码行号为 2026-10-15 云上文件实测。)

### 1.2 每日实发量(两个口径)

台账口径(10-10~10-15,合计 268):

| 日 | 总量 | critical | notice | 其它 | 备注 |
|---|---|---|---|---|---|
| 10-10 | 3 | 1 | 2 | - | 台账 08:27 上线,当日不完整 |
| 10-11 | 10 | 2 | 5 | warning 2 / digest 1 | 夜间盘点 17 条仅 1 真故障(alert-night-triage-20261012) |
| 10-12 | 69 | 13 | 54 | warning 1 / digest 1 | 周一起爆 |
| 10-13 | 56 | 14 | 39 | warning 1 / digest 1 / subscribe 1 | |
| 10-14 | 47 | 15 | 30 | warning 1 / digest 1 | |
| 10-15 | 83 | 44 | 36 | warning 1 / digest 1 / subscribe 1 | 单日峰值 |

台账前日志口径(**低估**,只数发送行):
- schedule_monitor 链邮件:9-13~9-24 每天 6~31 封(9-15 峰值 31),9-25~10-09 降到 2~14 封/天;
- intraday 链邮件:9-14~10-15 每天 6~30 封(9-18 峰值 30),几乎未降。

⇒ 结论:降噪对**被点名通道**有效(schedule_monitor 降 ~75%),但全量在 10-12 起重新爆表(47~83/天)——新故障域同期进场,修复被淹没。

### 1.3 构成(268 条,10-10~10-15)

按 group(机械精确):
- **alert(故障告警)134(50%)**:critical 89 / notice 34 / warning 6 / digest 5;
- **report(业务报告)125(47%)**:全部 notice;follow 4 / agent_done 3 / 无 group 2;
- **89 条 critical 全部出自 alert 组。**

按 source top:intraday_snapshot.sh 101(38%,几乎全是业务信号)、schedule_monitor.sh 57(21%)、backfill_metrics.sh 17、r2_upload_async.sh 16、update_all.sh 15、self_heal.sh 13、check_data_gap_alerts.sh 9、nextday_plan.sh 6、update_lab.sh 6、run_daily_brief.sh 4、brief_push_wrapper.sh 4、turnover_backfill.sh 4。

按主题(grep subject,可重叠):

| 主题 | 条数 | 性质 |
|---|---|---|
| 买卖点信号 | 73 | 业务订阅 |
| R2 相关(含锁跳过/恢复/上传失败) | 47 | 故障+重复 |
| 盘中异动 | 33 | 业务订阅 |
| 计划任务异常(N项) | 21 | 故障摘要 |
| failed unit 持续未清(升级) | 18 | **机制噪声** |
| 恢复 | 10 | 闭环信号 |
| 数据缺口 | 9 | 故障 |
| 信号凯利(冻结表/突变/停滞) | 9 | 故障+常态噪声 |
| 速递 | 8 | 业务订阅 |
| deploy(校验/失败) | 8 | 故障 |
| 快照 s06 | 4 | 故障 |

重复度:22 个主题出现 ≥2 次、组内共 66 行,**第二次及以后的多余行 44(16.4%)**。最刺眼:10-15 当天同主题「云上 failed unit 持续未清(连续 8 天, 升级 critical)」发了 **6 次**(00:00/18:45/20:15/20:30/21:15/22:15);另有 a_fund_main 重采失败 8 次、verify-r2 脱节 5 次。

时段(按小时聚合):盘中 9-11 时 + 13-14 时 ≈ 98 条(业务为主);盘后 16-23 时 ≈ 118 条(**故障类高发:18 时 20、20 时 32、21 时 29、22 时 28**);凌晨 0-8 时 30 条(含升级档零点日课)。

### 1.4 10-15 单日解剖(83 条 = 约 14 个独立事件)

渠道:82 条双渠道(email+feishu)+ 1 条飞书单发 ⇒ **手机可见 ≈165 条消息**。

| 事件域 | 条数 | 说明 |
|---|---|---|
| R2/deploy 故障域(**1 个真实故障**) | 28 | 18:25「deploy 数据产物校验失败」起,data-files/etf-score/fund-score/lab/trade-sim-json/trade_sim/lab_json/etf-hist/index/kelly-snapshots/nextday 各通道上传 rc=1/124;update_all/update_lab/self_heal/intraday_snapshot/s06/etf_national_team/nextday_plan 等 7~8 个脚本各自告警;self_heal 另发 update_all 锁跳过 4 条 |
| 业务订阅流 | 31 | 盘中异动 14 + 买卖点 14 + 速递 2 + 明日计划 1 |
| failed-unit 升级 critical | 6 | 同主题重复 6 次(见 §1.3) |
| 计划任务异常(聚合邮件) | 8 | 18:45/19:30/19:45/20:30/21:00/21:15/21:30/22:15;其中 6 条内容即 R2 故障衍生 |
| 历史行改写 | 3 | index_daily 1 条 + signal_daily 997/1000 条(每日常态事件被标 critical) |
| 其它 | 7 | kelly 冻结表 1、kelly 指标突变 1、数据缺口 2、摘要 1、warning 汇总 1、R2 恢复 1 |

真故障证据:`update_all_launchd.log` L8685-8727——18:32 R2 上传 rc=1(Cloudflare 错误页 JSON parse fail)+ ssd.fx8.store 直连不可达 + 多处超时 ⇒ **10-15 R2 故障是真的**(故障技术根因在网络/R2 侧,本 RCA 未展开)。

### 1.5 抑制挡掉多少

- schedule_monitor 日志:总 `[suppress]` 行 **5876**;10-15 当日抑制 **151** vs 当日实发 83 ⇒ 约 2/3 的重复候选被挡、**1/3 仍发出**。
- 分级抑制家族(日志计数):r2-skip-dup 420、r2-merge-suppress 367、r8-nextday-gap-suppress 262、196-patrol-suppress 192、r7-r2consistency-suppress 191、silent recovery 142、self_heal pending 129、dedup 88(总 suppress 口径见上)。
- 预算+摘要层:`merged_in_digest` 仅 **3 条/日**(容量太小 ⇒ 几乎不挡)。
- 判据挂账:`alert_state.json` 181 keys / **14 个恒 active**,其中 3 个挂了 ≥2 天(overfit_monitor|r2_skip_alert 自 09-24、nextday_gap_check|ConnectionError 自 10-13、s06_snapshot|dur>900s 自 10-13);`failed_units_patrol_state.json` `consecutive_days=8`(first_fail_date 10-08,即一个状态挂了 8 天)。
- `alert_daily.json` by_key 佐证:同一升级 key `73ad3acf51d2` 当日记 6 次。

## 2. 修复史复盘与复发结构(Q2)

### 2.1 历次修复做了什么、效果如何

| # | 时间 | 修复 | 实测效果 | 局限 |
|---|---|---|---|---|
| 1 | 09-29~10-09 | 降噪立项 + 全链审计(20 条真实样本逐条定性、5 层收敛方案) | 摸清结构 | 未动发送量 |
| 2 | 10-10 | #245 批2(5a92e6f81):W1 台账/日计数/meter + L2 日预算+摘要 + B6 看门狗 | **首次有了「一天几条」的权威数字** | 预算太松(merged 3/日) |
| 3 | 10-11 | 三项降噪(a7f6413ec:冻结表 accepted 仅表外告警、verify 脱节阈值、r2_skip 降 info)+ #247 nextday key(023d73929)+ batch3(6aa0411f7) | 冻结表 8 条/日→仅表外;verify 类下降 | 只治点名处 |
| 4 | 10-12 | a_fund_main 45min 同 key 循环修复 | 该 key 8 条→0 | 只治点名处 |
| 5 | 10-13 | kelly-rerun 降噪(548ee9bec / d2986ae6d:rc5 severe→warn) | kelly 类下降 | 只治点名处 |
| 6 | 10-14 | 修「按类别预算吞 severe」(440c9b8cd / 7b571dc9d)= 修**降噪自身产的新错**;夜间立案 #257~#260 | 预算不再吞 critical | **#259(挂持久状态)立案未修** |

对比:schedule_monitor 链 9 月中 25~31 封/天 → 10 月初 2~8 封/天(降 ~75%);但全渠道 10-12 起 47~83/天。**修复有效、面没修,被新面淹没。**

### 2.2 复发结构(按四条假设逐条验证)

① **只修单点?是。** 历次修复 100% 是「被点名的单点」;修过的点确实归零(a_fund 8→0、冻结表 8→1);但结构性问题(同事件多路播报、判据挂状态)一次没动。
② **判据挂持久状态?是(#259,已立案未修)。** consecutive_days=8 单调递增;单元集合 15 分钟一抖(日志 40+ 轮可见 trade-etf-national-team/lhb/futures/nextday-plan/r2-consistency/s06/turnover/public-fund-daily 反复出现-消失);alert_state 3 个 key 挂 2 天~3 周不消。
③ **修复覆盖面 vs 告警面 mismatch?是。** 告警面扩张(近月新增 failed-unit #196、patrol、heartbeat、data-gap、overfit-monitor、R2 通道;新故障域 R2/双树)速度快于降噪;每新增一个 checker 就新增一组出口。
④ **降噪机制自身制造新噪?是,3 个已证实例:**
   - a. **升级通道抑制窗被关死(最重)**:`check_failed_units.py` L277 外发时传 `--dedup-key failed_units_patrol --dedup-window 0`;`notify.py` L1479 `if not key or window <= 0: return False`(不抑制);升级分支 `notify.py` L2822 `check_dedup(_esc_escalated_key, args.dedup_window)` 复用调用方窗口 ⇒ **升级 critical 永远不被抑制**(L2837 虽写了 update_dedup,但检查端 window=0 恒放行)⇒ 集合每变化一次/每天零点就真发一封。实测 18 条/6 天、10-15 单日 6 条同主题。
   - b. **跨日 rollover**:被预算吸收的事件次日重新计数再发(alert-night-triage-20261012 已记录)。
   - c. **L2 预算吞 severe**:类别预算曾把 severe 吞进摘要,10-14 才修(440c9b8cd)。
   ⇒ 一句话:**该修的从来不是「再加一条降噪」,而是两条结构约束:判据必须事件化、发送必须域聚合。历次补丁全部绕开这两条。**

## 3. 根因判定(Q3,数字分解)

268 条按「消除该条所需动作」分解(边界重叠处按最大主因归类;百分比为近似):

| 分层 | 条数 | 占比 | 明细与证据 | 消除动作 |
|---|---|---|---|---|
| A 业务订阅/报告流 | ~127 | 47% | report 组 125 + subscribe 2(买卖点 73 + 异动 33 + 速递 8 + 计划等) | **分流**(独立渠道/批量),不是降噪 |
| B 同事件重复播报 | ~50 | ~19% | 完全同主题多余行 44 + 10-15 R2 域 28 条对应 1 个真故障;升级档同主题 6 次/日 | **域聚合 + inhibition + 抑制窗修复** |
| C 机制噪声(判据挂持久状态/常态事件) | ~24 | 9% | 升级档 18 + 历史行改写 6(每日常态) | **判据事件化**,可归零 |
| D 真故障首报(独立事件) | ~35 | ~13% | R2 真故障、任务失败、数据缺口、快照、deploy 校验 | **保持可达**(聚合后仍须出现) |
| E 其它(摘要/恢复/锁跳过/agent_done/未知) | ~32 | ~12% | 恢复 10、锁跳过 4、摘要/聚合/warning、agent_done 3、unknown 2 | 并入摘要/观察 |

判定:
- 「太多」= **47% 业务流 + ~19% 重复 + 9% 机制噪声 + 13% 真故障(未聚合) + 12% 杂项**;
- 真正该「减」的 = B+C(≈28%);该「分流」的 = A(47%);该「保」的 = D——聚合消息里必须保留全量明细,不吞真故障判别维度(内存 `alert-denoise-keep-fault-discriminator`);
- **44 critical/单日是手机震动主源**(failed-unit 升级 6 + R2 族与任务失败为多数);
- 10-15 的 83 条背后 ~14 个独立事件:2/3 的量是「1 个故障域放大 + 业务流 + 升级档日课」。

## 4. 方案(一步到位;业界对照 + 六件套,每件 §5.7 三件套)

### 4.0 业界对照(WebSearch 调研结论)
- **Alertmanager 模型**:`group_by` 按域聚合 + `group_wait/group_interval/repeat_interval` 控制节奏;`inhibit_rules` 根因告警抑制派生告警;silence;dedup。「同一故障域多脚本各自告警」正是 group_by 的标准场景,本项目完全没有这层。
- **SRE 实践**:alert on symptoms not causes;`for:` 窗口加迟滞反 flapping;分级路由(分页 vs 工单/摘要)——本项目把 critical 泛化到「历史行改写」等常态事件,分页通道失去意义。
- **业界统计**:约 30% 告警是重复;聚合分组可砍 ~65% 重复通知;inhibition 减冗余 42~65%。
- 对照结论:本项目有 dedup(被 window=0 局部关死)、有摘要(容量过小);**缺 inhibition/域聚合、缺判据事件化、缺通道分流、缺 flapping 迟滞**。

### 4.1 六件套

**A. 升级通道抑制窗修复(P0;最小改动面,针对 C 类 18 条/6 天)**
- 依据:`check_failed_units.py` L277(`--dedup-window 0`)+ `notify.py` L1479(`window<=0 → 不抑制`)+ L2822(升级检查复用调用方窗口)。
- 预期(X→Y):升级 critical 从「集合每变化/每天零点必发」→「独立窗口(建议 24h)内同档 ≤1 封」;6 天 18 条 → ≤2 条;10-15 同类 6 条 → 1 条。
- 证据用例:①改后连续 6 天 `alert_ledger.jsonl` 中「持续未清」行 ≤2;②构造「集合不变的一天」重放,零外发;③**真故障反例**:当日新增失败单元首报仍必发(critical 首报必达不破坏)。

**B. 判据事件化(#259 根治,P0;针对持久状态挂账)**
- 依据:`failed_units_patrol_state.json` consecutive_days=8/first_fail_date 10-08;alert_state 3 key 挂 2 天~3 周。
- 预期:「连续天数」改为滚动窗口(如近 N 天出现天数)或「当日新增/恶化才推进」;systemd failed 状态挂着不再单调推 critical;挂账 key 有到期自动降级/清理策略。
- 证据用例:①用 10-12~10-15 历史逐日重算,升级触发 ≤2 次(现 18);②**真故障反例**:新增失败单元首日仍 critical;③alert_state 恒 active 挂账 key 数 30 天内 ≤3(现 14)。

**C. 故障域聚合层(域 inhibition,P0;针对 B 类重复,最大减量)**
- 依据:10-15 一个 R2 故障 7~8 脚本各发(28 条);全站无 domain 概念(§1.4)。
- 预期:同域(如 R2/双树/快照)首条告警后,窗口内(建议 group_interval 2h)同域派生合并为 1 条摘要;正文保留全量明细(受影响脚本/通道逐一列出)——不吞真故障判别维度。
- 证据用例:①重放 10-15 R2 时间线:域级外发 1~2 条(现 28),正文含脚本清单可逐条检索;②**真故障反例**:同时段第二个不同域故障仍独立首报;③「多少通道受影响」判别维度在合并消息中保留。

**D. 业务订阅流分离(P1;针对 A 类 47%)**
- 依据:买卖点/异动/速递 ≈127 条/6 天混在 alert 出口(§1.3)。
- 预期:subscribe/report 类走独立渠道或批量摘要,不进「告警群」;告警群只留故障类。
- 证据用例:10-15 重放:告警群条目 83 → ≤45;业务类全部归位且**计数对账不丢**(106 条业务信号全在,只是换渠道)。

**E. 预算+摘要层扩容(P1)**
- 依据:merged_in_digest 仅 3 条/日,预算几乎不挡。
- 预期:非 critical 重复类超预算入摘要(摘要注明「被合并 N 条」),恢复类入摘要;critical 永不入预算(维持不变式)。
- 证据用例:10-15 重放:总量 ≤45 且摘要含被合并 N 条;恢复类出现在摘要;全部被合并条目在摘要内可检索。

**F. 防复发机制(把「告警面扩张」纳入预算,P1)**
- 依据:新 checker/新域扩张快于降噪(§2.2③)。
- 预期:新增 checker 必须声明四元组「默认 tier / dedup window / 聚合域 / 首报策略」,缺一不上线(review 清单强制);每周 review top-talkers + 被吞条目找回。
- 证据用例:①对现有全部 checker 产出四列矩阵,缺项清单上报;②连续 2 周 review 记录在档。

### 4.2 实施与验收
- 阶段 1(P0:A+B+C):直打 44 critical/天的爆发链;**验收 = 连续 7 天 P50 ≤3 且 critical ≤1**(对齐收敛计划 L5 预算验收),以 `alert_daily.json` + `alert_ledger.jsonl` 为准。
- 阶段 2(P1:D+E+F)。
- 流程:每件先派单(含 §5.7 三件套)→ 独立审 → `main-merge.sh` → §0 生产实证;每件重放 10-15 真实样本给「前/后逐条对照表」;所有降噪实装必须过「真故障反例」用例(不得吞掉真故障判别维度)。

## 5. 口径与边界(诚实标注)
1. 台账 10-10 08:27 上线,10-10 数据不完整;9-13~10-09 为日志口径(只数发送行、漏摘要/飞书 ⇒ 低估)。
2. 「重复 44 条(16.4%)」为完全字符串口径(22 组主题 66 行、多出 44 行);语义重复但措辞不同者未计 ⇒ **下限**。
3. 抑制计数 5876/151 只覆盖 schedule_monitor 日志;notify.py 通用 dedup 的抑制无独立计数(未全量入账)。
4. 「手机可见 ≈165」= 82 双渠道 ×2 + 1(渠道计,非台账 83)。
5. R2 故障技术根因(网络 vs R2 侧)未展开;「真故障」定性证据 = update_all_launchd.log L8685-8727 rc=1/JSON parse fail/超时。
6. §3 分解表 B/D 边界重叠,按最大主因归类;A 类占比高(47%)是「分流」问题不是「故障」问题。
7. 代码行号引用(notify.py L1479/L2822/L2837、check_failed_units.py L277、alert_denoise_rules.py L60/L148/L198)均为 2026-10-15 云上文件实测。
8. 本次调研全程只读;未做任何云上写操作(仓内仅本报告,未 commit);无后台残留任务。

## 6. 复现命令(全部只读)

```bash
SSH='ssh -i /Users/linhuichen/tdsignal.pem -4 -o ConnectTimeout=10 ubuntu@122.51.111.173'

# 1) 台账逐日/逐 tier/分组/来源/重复/主题分类/时段
$SSH "python3 - <<'PYEOF'
import json, collections, re
rows=[json.loads(l) for l in open('/home/ubuntu/code/trade-data/data/alerts/alert_ledger.jsonl')]
print('total',len(rows))
print(sorted(collections.Counter(r['ts'][:10] for r in rows).items()))
print(sorted(collections.Counter((r['ts'][:10],str(r.get('tier'))) for r in rows).items()))
print(collections.Counter(str(r.get('group')) for r in rows).most_common())
print(collections.Counter(str(r.get('source')) for r in rows).most_common(15))
sc=collections.Counter(r.get('subject') for r in rows)
dg={s:c for s,c in sc.items() if c>=2}
print('dup_groups',len(dg),'rows',sum(dg.values()),'extras',sum(dg.values())-len(dg))
print(sorted(collections.Counter(r['ts'][11:13] for r in rows).items()))
for p in ['买卖点','异动','R2|r2','持续未清','恢复','缺口','计划任务异常','速递','deploy','kelly|冻结']:
    print(p, sum(1 for r in rows if re.search(p, r.get('subject') or '')))
PYEOF"

# 2) 日计数 / failed 判据状态 / alert_state 挂账
$SSH 'cat /home/ubuntu/code/trade-data/data/alerts/alert_daily.json'
$SSH 'cat /home/ubuntu/code/trade-data/data/failed_units_patrol_state.json'
$SSH "python3 -c \"import json;d=json.load(open('/home/ubuntu/code/trade-data/data/alert_state.json'));print('keys',len(d));[print(k,v.get('first_seen'),v.get('last_alerted')) for k,v in d.items() if isinstance(v,dict) and v.get('status')=='active']\""

# 3) 抑制/升级计数
$SSH 'grep -c "\[suppress\]" /home/ubuntu/code/trade-data/data/logs/schedule_monitor_launchd.log'
$SSH 'grep "\[suppress\]" /home/ubuntu/code/trade-data/data/logs/schedule_monitor_launchd.log | grep -cE "10-15|20261015"'

# 4) 代码锚点(window=0 升级链)
$SSH 'grep -n "dedup-window" /home/ubuntu/code/trade-data/scripts/check_failed_units.py | head'
$SSH 'sed -n "1470,1485p;2800,2840p" /home/ubuntu/code/trade-data/scripts/notify.py'

# 5) 10-15 R2 真故障证据
$SSH 'sed -n "8685,8727p" /home/ubuntu/code/trade-data/data/logs/update_all_launchd.log'
```

---
(报告完;本文件未 commit。生成:2026-10-15,researcher 只读调研。)
