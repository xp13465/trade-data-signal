# 告警降噪 #264 包2(件 C 故障域聚合层 + 件 E 预算/摘要扩容)实施报告

- **分支**: `feat/264b-alert-aggregate-budget`
- **基准依据**: `docs/ops/alert-noise-rca-20261015.md`(§1.4 单日解剖 / §1.5 / §2.2 / §4.0 业界对照 / §4.1 C+E 三件套 / §4.2 验收口径)+ `docs/ops/alert-convergence-plan-20261010.md`(降噪铁律 L10、不变式)
- **用户拍板**: 2026-10-15「按建议修复」= A+B+C+E+F 打包、D 单独议;本包只做 **C+E**
- **零真实外发声明(§18 L48)**: 本次全部自测/重放**零真实外发**。打桩方式 = ① 三个渠道函数(`_send_email`/`send_telegram`/`send_feishu`)整体替换为「只记录、返回 True」的假函数;② 外层 `ZeroOutboundTrap`(`scripts/tests/_zero_outbound.py`)包裹最底层 `urllib.request.urlopen`/`smtplib.SMTP`/`SMTP_SSL`,任何未打桩出口立即 AssertionError;③ 收尾断言 `trap.hits == []`(命中即测试失败)。**沙箱生效正控** = `test_00_zero_outbound_trap_really_works` 故意触发未打桩出口,证明陷阱真能抓住(不是「因为没跑才没外发」的假绿,§18 L49)。全部落盘面(台账/buffer/state/dedup/latest.md)重定向到 `tmp_path`,绝不碰生产 `data/alerts/`。
- **区段声明(避开包1 主战区)**: 本包主战区 = `notify.py` 发送/摘要层(恢复留痕 L1196-1212 / 域 gate L1239-1272 / E 层 gate L1273-1302 附近 / `_absorb_to_digest` L1851 / `_bump_digest_hits` L1921 / 状态读写 L1792-1845 / `_flush_digest_locked` L2651+)+ `alert_denoise_rules.py` 新段 + `notify_sent.py` 登记表。**未触碰** `notify.py` L2810-2845 升级分支区(包1 主战区):已核实该区经 `send_tiered(tier=critical)` → `send(..., budget_exempt=True)`,天然被本包两道 gate 的 `not budget_exempt` 豁免,无需改动即正交。触碰的其它函数清单见 §⑧。

---

## ① 改动清单(文件:行号)

| 文件 | 位置 | 内容 |
|---|---|---|
| `scripts/alert_denoise_rules.py` | L907-1046 新段 | 件C: `ALERT_DOMAIN_STATE_FILENAME`/`ALERT_DOMAIN_GROUP_INTERVAL=7200`/`DOMAIN_ABSORB_REASON`/`DOMAIN_R2_RC_RE`/`DOMAIN_LABELS` + `domain_of()`(L939) + `domain_inhibit_judge()`(L986) + `domain_aggregate_summary()`(L1026) —— 全部纯函数 |
| 同上 | L1049-1136 新段 | 件E: `ALERT_NOTICE_BUDGET`(L1055)/`NOTICE_OVER_BUDGET_REASON`/`ROLLOVER_ABSORB_REASON`/`ALERT_DIGEST_SEEN_FILENAME`/`ALERT_DIGEST_ROLLOVER_DAYS=3` + `ledger_day_notice_index()`(L1065) + `rollover_absorb_judge()`(L1104) + `rollover_prune()`(L1125) |
| `scripts/notify.py` | L278-289 | 新常量: 域状态文件名 / 摘要 seen 文件名 / `ALERT_AGGREGATE_SUBJECT_RE` / `DIGEST_RECOVERY_TRACE_REASON` / `DIGEST_REASON_LABELS`(人读中文标签) |
| 同上 | L1196-1212 | 恢复类**留痕**(件E「恢复类入摘要且可见」): 恢复消息照发后在当日摘要登记一条 `recovery-trace\|<sig>`(reason=`recovery_closure`) |
| 同上 | L1239-1272 | **件C 域 gate**: 域映射 → `domain_inhibit_judge` → absorb ⇒ `_absorb_to_digest(reason=domain_inhibited, domain=…, bump_hits=True)` + commit 域状态 + early return;append 失败 ⇒ fail-open 落直发 |
| 同上 | L1273-1302 | **件E gate**: `not severe` 结构性豁免 critical;`_grp == "alert"` 限群;`_dup_today or _roll` 且额度用尽 ⇒ absorb(reason=notice_over_budget / rollover_digested,mark_seen=True) |
| 同上 | L1330-1331 | 域「首报」只在**真发出后**写域状态(`any((email_ok, tg_ok, fs_ok))`)= 发送成功才占窗(P1-1) |
| 同上 | L1771-1845 | 新 helper: `_budget_today_notice_count/keys`(独立 notice 台账口径)+ `_state_path/_read_state_obj/_write_state_obj`(原子写)+ `_domain_state/_commit_domain_state` + `_rollover_seen/_commit_rollover_seen` |
| 同上 | L1851-1913 | `_absorb_to_digest` 新增 `reason/domain/mark_seen/bump_hits` 四个**默认值=老行为**的 kwarg(既有 L2 调用方逐字节不变) |
| 同上 | L1921-1947 新 | `_bump_digest_hits`: 幂等命中时 hits+1(flock 读改写),使摘要可显示 `xN` |
| 同上 | L2651-2810 | `_flush_digest_locked` 渲染重写: 「被合并 N 条」措辞 + 原因中文标签 + 【故障域 X】汇总段(C-③ 通道/脚本判别维度)+ 逐条可检索明细 + 【闭环信号(恢复)】段(留痕单列、不计入被合并数) |
| `scripts/notify_sent.py` | L110-113 | 抑制签名表新增 2 行(域并入/notice 并入)⇒ 三态判据把「已并入」判为 `suppressed`(成功且已知),不误判 `failed` 触发重试/重复告警 |
| `scripts/tests/test_264_alert_domain_budget_20261015.py` | 新增 824 行 | 58 断言组用例(域表表驱动/域 gate 12 面/E 层 8 面/摘要渲染 4 面/机检不变式/三态/10-15 重放/时钟无关性) |
| `scripts/tests/fixtures/alert_264_ledger_20261015.jsonl` | 新增 | 真实 10-15 台账样本(10-10~10-15 滚动窗原件 271 行, 含 10-15 全天 86 行) |
| `scripts/tests/repro_264_alert_domain_20261015.py` | 新增 | 前后逐条对照重放器(§⑥ 数字可独立复现) |

---

## ② 三验证(问题真实 / 根因定位 / 修复可行)

**a. 问题真实(实测)**
- RCA §1.4 + 本次用**真实台账原件**核实:10-15 单日 86 条外发,其中**告警群 51 条**;同一 R2 链路故障在 18:25→23:30 被 7~8 个脚本各自独立播报 = 域内 **37 条**(r2_deploy 域)⇒ 用户「一天 1~2 条」目标被单域淹没。
- 件E 面: `merged_in_digest` 容量小、被吸收事件跨日重新计数再发、恢复类(闭环信号)在摘要里**零痕迹**(RCA §4.1 E / §2.2④b)。
- 证据: `scripts/tests/fixtures/alert_264_ledger_20261015.jsonl` 为云上 `data/alerts/alert_ledger.jsonl` 原件(只读取回,未修改),`repro_264_alert_domain_20261015.py` 逐条重放。

**b. 根因定位(代码级)**
- 全站**无 domain 概念**(RCA §4.0 对照 Alertmanager `group_by`/`inhibit_rules`):每个脚本各自调 `notify.send(severe=True)`,`send()` 里只有「写盘前 dedup 窗口(signature 级)」+「L2 类别日预算」两层,**没有「同一故障域的派生播报」这一层** ⇒ 7 个脚本 7 个签名,窗口/dedup 各自为政,叠加必然 7 条。
- 恢复类: `send()` 在恢复分支只做 `clear_warning_dedup_for_recovery`,不写任何摘要可见面 ⇒ 闭环信号不可见。

**c. 修复可行(最小侵入)**
- 全部新逻辑收在**新增 gate + 新增纯函数模块段 + 默认值不变的 kwarg**里:既有 L2 预算/摘要/warning flush 路径**逐字节不变**(`_absorb_to_digest` 新参数默认值 = 老行为;`send()` 只在原 L2 gate 之后插入两道新 gate)。
- 三层独立 env 开关可逐层回滚: `ALERT_DOMAIN_DISABLE=1`(域层单停)/`ALERT_NOTICE_BUDGET_DISABLE=1`(E 层单停)/`ALERT_BUDGET_DISABLE=1`(两层齐停,逐字节回现状)。

---

## ③ 域表定稿 + 理由

| 域 | 中文标签 | 命中规则(key 优先, subject 兜底; 首命中胜出) |
|---|---|---|
| `data_gap` | 数据缺口 | ①`[数据缺口]`/「数据缺口」 |
| `gap_check` | 伪跳空/次日计划 | ①「伪跳空」/`nextday_gap_check` |
| `r2_deploy` | R2/双树/部署链路 | ②`r2_*` 前缀 / `r2_fail`/`r2_consistency`/`r2_pipeline` / `deploy_*` 前缀 / `update_all_severe*`;subject 含「R2 上传」「R2上传」「ssd.fx8.store」「双树」「三站一致性」「锁跳过」「计划任务异常」「统一deploy」「数据产物校验失败」;**subject 内 `r2=値≠0`**(如 S06 `r2=124`)也归此域(派生告警归根因域) |
| `snapshot` | 快照/S06 | ③`s06`/`snapshot`/「S06」/「快照」 |
| `unit` | 云上 systemd 单元 | ③`unit_patrol`/`failed_units`/`cloud_unit_patrol`/「failed unit」 |
| `kelly` | 信号凯利 | ③`kelly`/「凯利」 |
| `fund_nav` | 公募基金净值 | ③`fund_nav*`/「公募基金」 |
| `collect` | 采集/回补 | ③`backfill`/「采集」 |

**定稿理由(逐条,依据 10-15 真实台账 + RCA §1.4 事件域表)**
1. **`r2_deploy` 合一(不拆 r2 / deploy)**:RCA §1.4 把 10-15 那坨按**一个域**计 28 条;「部署→上传→校验」是同一条流水线的三个可观测症状,拆开就复现「同一根因 3 条播报」。首选 SRE 原则:并**症状**同一根因,不按脚本分。
2. **优先级顺序 = 类别标记(数据缺口/伪跳空) > R2 域 > 单脚本域**:类别标记是人工定义的事件类(RCA §1.4 明确区分);`data_gap` 里也可能带「deploy 无成功标记」字样,若 R2 域优先会被吞进 R2 大域,故类别标记必须最先判。实测 `[告警][数据缺口] 最近 deploy(...)无成功标记` → 正确落 `data_gap`。
3. **`r2=値≠0` 归 r2_deploy**:S06 快照链路异常本身是 R2 上传失败导致的派生(每 15min 重试告警),归根因域而非 `snapshot` 域;`snapshot` 只留「与 R2 无关的快照自身故障」。这条是把 10-15 21:00 的 S06 告警拉进同一条 R2 时间线的关键(否则域外发会变 3 条,破 C-①)。
4. **`history_overwrite` 故意不并入:每次出现的表/条数不同(index_daily 1 条 vs signal_daily 997/1000 条)= 无法判定「同一事实」⇒ 宁漏不误并,保持直发**(已在代码注释与测试用例 `test_02m` 里双向固化)。
5. **聚合/摘要消息自身永不入域**(`ALERT_AGGREGATE_SUBJECT_RE`):机制自身绝不产生元噪声(降噪铁律⑤)。
6. 域窗口 `ALERT_DOMAIN_GROUP_INTERVAL = 7200`(2h = RCA 建议 group_interval,可配);**窗口不跨自然日** ⇒ 「持续未清」每自然日仍有 1 次直发(留一条分页通道, 与 §4.0 SRE「分页 vs 工单」分级精神一致),同时把「跨日 rollover 重复播报」压到 ≤1 条/日/域。

---

## ④ 预期 vs 实测

| 证据用例 | 预期 | 实测 | 判定 |
|---|---|---|---|
| C-① 重放 10-15 R2 时间线 | 域级外发 **1~2 条**(现状 28/37) | **2 条**(18:25 域首报 + 20:15 恢复豁免),域内总 37 条 | ✅ |
| C-② 真故障反例 | 同时段第二个**不同域**故障仍独立首报 | `test_02e`:21:00 R2 派生被并 / 21:00 unit 真故障直发;10-15 全天 unit 域 2 次首报(00:00/18:45)照发 | ✅ |
| C-③ 「多少通道受影响」维度保留 | 合并消息内保留脚本数/通道清单 | 摘要正文含「【故障域 R2/双树/部署链路】共 30 条, 涉及 N 个来源脚本: …」 | ✅ |
| E-① 摘要含「被合并 N 条」 | 非 critical 重复类超预算入摘要并注明条数 | 摘要正文含「被合并 32 条」+ 原因构成中文标签 | ✅ |
| E-② 恢复类入摘要且可见 | 恢复消息在摘要里有痕迹 | 【闭环信号(恢复)】段 + `[恢复留痕·已直发]` 标注(10-15 有 1 条) | ✅ |
| E-③ 全部被合并条目可检索 | 静默仅限「同一事实的当日重复」 | 重放机检:41 条被并条目**逐条**在摘要正文命中(去重键+来源脚本+主题),`_missing == []` | ✅ |
| critical 永不入预算(不变式) | 结构上不可达 | 机检 `not severe` 在 gate 首位(`test_05a`);`test_03d`(notice 额度用尽后 critical 仍直发);变异 D 去掉 `not severe` ⇒ 用例立即变红 | ✅ |
| 首报必达 | 域首条/跨日首条/窗外复发/新签名/恢复/聚合自身/未映射域 一律直发 | 10-15 全天 10 条直发**逐条可解释**(见 §⑥) | ✅ |

---

## ⑤ C / E 用例逐条结果

**跑法(可独立复现)**
```
/tmp/ci-venv/bin/python3 -m pytest -q scripts/tests/test_264_alert_domain_budget_20261015.py   # 58 passed
/tmp/ci-venv/bin/python3 -m pytest -q scripts/tests/                                          # 955 passed, 2 skipped
/tmp/ci-venv/bin/python3 scripts/tests/repro_264_alert_domain_20261015.py                     # 前后逐条对照表
```
- **件C**(12 面): 域表表驱动(23 条真实样本, 含 8 个域命中 + 4 类「故意不并」负例)/ 窗口语义(无历史=first、窗内=absorb+计数累加、=2h 边界=first、跨日=first、坏时间戳=fail-open、窗口可配、2h 口径钉死 119min并/121min直发)/ 域汇总(条数·来源去重·首条时刻)/ gate 真实路径(首报直发并占窗、窗内并入零外发、窗外直发、跨日直发、真故障反例、report 群照发、恢复照发+留痕、dry-run 零落盘、budget_exempt 直发、开关全停、发送失败不占窗、append 失败 fail-open、未映射永不并)。
- **件E**(8 面): 独立台账口径(只数 notice/warning 且 group=alert, critical 口径不受影响, 两套额度键集同形)/ 首现直发+同签名第二次并入(reason=notice_over_budget + 登记 rollover 记忆)/ 新签名直发 / critical 不受本层影响 / rollover 纯函数 6 面 / rollover 吸收路径(reason=rollover_digested)/ 层开关单停 / 限群判别力(report 群必须照发)。
- **摘要渲染**(4 面): 「被合并 N 条」+ 逐条可检索 + `xN` 次数 / 域汇总段保留通道维度 / 恢复留痕单列且不计入被合并数 / 只有留痕时 subject 措辞不撒谎(「当日无合并告警」而非「合并 0 条」)。
- **机检不变式**(2 面): 结构锚点(`not severe` 前置、开关在位、域 gate 在 subject 改写前、digested 早退在 ok 判定前、`_commit_domain_state` 在发送成功后、notify_sent 登记在位、纯函数单实现)+ 三态判据(新并入行 suppressed、反向用例含 `suppressed` 子串的 tier 路由完成行必须 sent)。
- **10-15 重放 + 时钟无关性**(2 面): 见 §⑥;同一序列在虚拟 2026-10-15 与 2027-03-08 两日下判定逐位一致(§18 L51 隔天仍绿机检)。

**判别力关(§18 L49,变异测试)**: 6 个变异逐个就地改坏 → 跑用例 → 复原校验 sha256 逐字节一致。结果 **A~F 全部「有判别力」**:

| 变异 | 效果 | 被触发的失败用例 |
|---|---|---|
| A 关掉域层吸收(absorb 分支短路) | 域聚合失效 | `test_02b`/`test_02e`/`test_06`/`test_07` |
| B 去掉域层限群 `_grp=="alert"` | 业务流被并 | `test_02f` |
| C 去掉 E 层限群 `_grp=="alert"` | 业务流被并 | `test_03h` |
| D 去掉 E 层 `not severe` 结构性豁免 | critical 可被吞 | `test_03d`/`test_05a` |
| E 域窗口 2h→1h | 窗口口径漂移 | `test_01e` |
| F 摘要丢掉「被合并 N 条」措辞 | 验收口径文案丢失 | `test_04a`/`test_04c`/`test_06` |

> ⚠️ 变异关卡的一个坑(如实记录): 变异 E 的改动是**同尺寸**文本(7200→3600),复原发生在**同一秒**内 ⇒ `__pycache__/*.pyc` 的新旧判定(mtime 秒级 + 文件大小)双双命中 ⇒ **导入到旧(变异)字节码, 出现「复原后仍红」的假失败**。处置: 删 `scripts/__pycache__/{alert_denoise_rules,notify}.cpython-311.pyc` 后复跑 ⇒ 58 passed。结论: 变异/复原类自验必须清 pyc 或用尺寸会变的变异点(本报告 A~D/F 均尺寸变化, 不受影响)。同类面: memory `trade-data-code-dirs-are-symlinks`(镜像/缓存导致假通过/假失败)。

---

## ⑥ 10-15 前后对照(83 → 46,逐条归因)

**口径**: 台账原件 10-15 共 **86 行**外发(RCA 记 83 为同一量级;差 3 行属台账滚动窗/统计口径微差,如实标注)。重放只取 10-15 单日行(域状态/预算从 00:00 空态起算),由 `repro_264_alert_domain_20261015.py` 产出下表。

| 类别 | 前 | 后 | 归因 |
|---|---|---|---|
| 非告警群业务流(买卖点/异动/订阅/agent_done 等) | 34 | 34 | **照发**(不在本包作用面;域层与 E 层均限 `_grp == "alert"`) |
| 告警群 · 域层聚合 | 41 | **1 条摘要**(含 32 个条目行) | 被聚合(故障域) —— 域内距离上一条同域 < 2h 的派生播报 |
| 告警群 · 直发 | 10 | 10 | 见下「10 条直发逐条归因」 |
| 台账自身/摘要行 | 1 | 1 | 跳过(元消息, 机制自身绝不入聚合) |
| **合计外发** | **86** | **46** | **净减 40 条(−46.5%)** |

**R2 故障域(18:00 后)**: 域内 **37 条 → 域级外发 2 条**(18:25 域首报直发 + 20:15 恢复豁免直发;其余 35 条并入当日摘要)= C-① 目标 1~2 条 ✅。

**10 条直发逐条归因(全部属于设计的「必达」类)**

| 时刻 | 域/类别 | 直发理由 |
|---|---|---|
| 00:00:06 | unit | 域首报(critical, 跨日首报必达 = 每日分页通道) |
| 16:37:45 | (未映射) | `history_overwrite:index_daily` —— 域未映射(每次条数不同, 宁漏不误并) |
| 16:45:00 | (未映射) | `history_overwrite:signal_daily` 997 条 —— 同上 |
| 17:58:40 | (未映射) | `history_overwrite:signal_daily` 1000 条 —— 同上 |
| 18:25:19 | r2_deploy | R2 域当日(18:00 后)首报(前一次同域直发在 16:xx 已出窗) |
| 18:45:06 | unit | unit 域距上一条(00:00)已 > 2h ⇒ 新事件 |
| 20:15:10 | r2_deploy | **恢复类**(闭环信号)豁免, 必直达 |
| 21:40:10 | kelly | kelly 域首报 |
| 21:45:16 | (聚合自身) | `[告警·聚合]` warning 汇总 —— 机制自身绝不入聚合(防元噪声) |
| 22:35:22 | data_gap | data_gap 域首报 |

**被聚合 41 条的域分布**: r2_deploy 35 / unit 5 / data_gap 1。

**诚实标注(不选择性隐瞒)**: ① 10-15 单日 **E 层贡献 0 条**——被域层前置吸收(域层条件更宽: 同域即并;E 层要求同签名+额度用尽);E 层的价值在**域窗外复发/跨日 rollover/恢复可见性**三面,由 `test_03b/03f/02g` 单测证据覆盖,本日真实样本里体现为**恢复留痕 1 条**(摘要里可见)。若后续观察到域层过宽(把「同域不同根因」并掉),可把 E 层排到域层之前以提高归因精度(改一行顺序),本报告不改。 ② 摘要 `被合并 32 条` < 被聚合 41 条:同签名重复并入只留 1 行并 `hits+1`(渲染为 `xN`),这是刻意设计(不丢「被并了多少次」的事实,同时避免 buffer 无限膨胀);口径 = 「N 条」按**去重后的告警行**计。

---

## ⑦ 零外发声明

见报告头部「零真实外发声明」。补充证据: 全量跑(955 passed)与重放脚本(exit 0)**均未产生任何邮件/飞书/Telegram 外发**——渠道函数已整体打桩,且外层 `ZeroOutboundTrap` 收尾断言 `trap.hits == []` 未触发;未调用任何云上写操作(`ssh` 仅用于只读取回台账原件一次,未写云上任何文件)。**本次无残留后台任务**(未出现 `moved to the background`)。

---

## ⑧ 区段/影响面声明 + §23.2 同类错误面 + §23.3 举一反三

**触碰的函数清单(除 §① 所示新段/新 helper 外的既有函数)**: `send()`(仅在原 L2 gate 之后插入两道新 gate + 恢复留痕 + 域状态提交一行)、`_absorb_to_digest()`(加 4 个默认值不变的 kwarg)、`_flush_digest_locked()`(渲染段重写, 触发/清理/state 契约未动)、`notify_sent._SUPPRESS_SIGNATURES`(加 2 行)。**未触碰**: `send_tiered`/升级分支区(L2810-2845)、`defer_warning`、`flush_warning_batch`、`_send_email/send_telegram/send_feishu`、`_record_ledger`、`write_alert`、`_mirror_severe`。

### §23.2 同类错误面清单(修/改一处先列同类,逐项自测)

| 同类面 | 是否受影响 | 证据 |
|---|---|---|
| **其它「会吞消息」的层**(L2 预算 / warning defer / 30min 聚合 / dedup 窗口) | 新增 gate 全部走「无法判定 ⇒ 直发」fail-open;append 失败落直发 | `test_02l`(append 失败 fail-open)/`test_02k`(发送失败不占窗) |
| **同一事实在多处登记**(suppress 签名表 / 三态判据 / ledger tier 口径) | 新并入行已登记进 `notify_sent`;新增独立 notice 台账口径, 不动 critical 口径(B1 不破) | `test_05b` + `test_03a`(两套额度并行隔离) |
| **开关/回滚面**(每层独立 env) | 3 个开关全部就位并有测试 | `test_02j`/`test_03g`/`test_03h` |
| **状态文件写坏的容错**(域状态/rollover 记忆) | 全部 `_read_state_obj` fail-open(坏=当无历史) + `_write_state_obj` tmp+os.replace 原子写, 写失败仅不占窗 | `test_01c`(坏时间戳)/`test_03e`(坏日期) |
| **业务流被误并**(report/follow 群) | 两层 gate 都显式限 `_grp == "alert"` | `test_02f`(域层判别力)/`test_03h`(E 层判别力) |
| **跨日/时区/时钟**(按日过滤 + 窗口) | 一律虚拟时钟注入;窗口不跨自然日 | `test_07`(两日判定逐位一致) |
| **dry-run 落盘**(§18 同族历史事故: `--dry-run` 仍落盘) | 新 gate 与留痕均以 `not dry_run` 前置,dry-run 零落盘 | `test_02h` |

### §23.3 举一反三清单(同模式/同数据源/同组件还被谁用 + 相关展示位,逐项覆盖结果)

| 同类对象 | 还被谁用 | 处置 |
|---|---|---|
| **同模式: `send()` 的其它调用方**(check_*.py / schedule_monitor.sh / signal_kelly_*.py / upload_r2 等 in-process 直调) | 全部经 `send()` 单点 ⇒ 自动受本包覆盖 | 逐条重放 10-15 真实台账已验证(域 gate 在 `send()` 内, 无旁路) |
| **同模式: `send_tiered(tier=critical)` 升级链**(#196/#7 升级档, 包1 主战区) | `budget_exempt=True` 路径 | **不聚合**(设计: critical 升级档永不入预算), 由包1 决定其自身演进;本包零改动 |
| **同模式: `--defer-digest` 直并 buffer**(schedule_monitor 的 monitor 行吸收/恢复补列) | `_absorb_to_digest` 默认 kwarg = 老行为 | 既有 `[notify][digest] 已并入摘要 buffer` 行为逐字节不变;与恢复留痕**不双计**(D5 补的是「未发出」的恢复, 本包留痕是「已发出」的恢复) |
| **同数据源: 台账 `alert_ledger.jsonl`** | W1 度量层 / L2 预算计数 / 本轮两套新口径 / 监控看板 | 新增 `ledger_day_notice_index` 与既有 `ledger_day_direct_index` **并行不互扰**;既有读取方零改动 |
| **同组件: 摘要 buffer `alert_digest.jsonl` + state** | 23:25 flush / `--flush-digest` / 监控面板 | 条目新增 `reason`/`domain`/`hits` 字段(向后兼容, 旧条目无这些字段时渲染走默认值);flush 触发与清理契约未动 |
| **相关展示位: 用户可见的告警面**(邮箱/飞书告警群/latest.md 流水/摘要消息) | 4 处 | 全部经受影响面覆盖:告警群见 §⑥ 对照;`latest.md` 由 `_mirror_severe` 不变;摘要消息本身经 `ALERT_AGGREGATE_SUBJECT_RE` 防自吞 |
| **相关展示位: 前端/数据产物** | 无 | 本包纯后端通知链路,**不改前端、不改数据产物、不推 R2**,§24 四项不适用(已在报告说明) |
| **邻区登记点 `docs/pending-features-index.md` 告警区**(#257 `fund_index_daily` 停更零告警 / #258-#260 夜间告警分流收口) | 检查侧盲区(补检查器/回填), 与降噪层不同面、不同文件 | 无冲突、无依赖;本包不触碰 `check_*.py`/monitor 侧 |
| **同一批任务的并发面**(#264 包1 升级链 = notify.py L2810-2845; #264 包3 治理 = `alert_weekly_review.py`) | 与包1 共享 `notify.py` 文件 | 已避让包1 区段(见区段声明);**merge 冲突风险提示主控**: 包1 与包2 同文件, merge 时按区段逐块核对, 不静默取一边(§23.11) |

---

## 附: runbook / 回滚

- **一键回滚(逐字节回现状)**: `ALERT_BUDGET_DISABLE=1`(两层齐停;域状态/buffer 零写入)。逐层单停: `ALERT_DOMAIN_DISABLE=1`(域层)/ `ALERT_NOTICE_BUDGET_DISABLE=1`(E 层)/ `ALERT_DIGEST_DISABLE=1`(仅停摘要出线, **注意**: 单独置它会只停 flush 而 gate 仍吸收 ⇒ 完整回滚须用 `ALERT_BUDGET_DISABLE=1`, 该注释已写在常量区)。
- **新增运行时状态文件**: `data/alerts/alert_domains.json`(各域 last_seen/当日计数)、`data/alerts/alert_digest_seen.json`(rollover 记忆表, 3 天窗内自动裁剪)。二者均为 best-effort, 删掉即回到「无历史」的自然直发状态。
- **调参**: 域窗口 `ALERT_DOMAIN_GROUP_INTERVAL`(秒, 默认 7200);域表 = `DOMAIN_LABELS`/`domain_of()`;E 层额度 = `ALERT_NOTICE_BUDGET`(默认各类别 1)。