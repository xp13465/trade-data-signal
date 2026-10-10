# #245 批2 独立审查报告(reviewer, 2026-10-10)

- 审查对象: `feat/245-batch2` tip `a2d962a82`(代码 commit `5a92e6f81` + 报告 commit),已 rebase 到 main `78322d943`(#246 已并入);worktree `/Users/linhuichen/code/trade/.claude/worktrees/agent-a8b3594621d289375`
- 权威规格: `docs/ops/245-batch2-impl-spec-20261010.md`;实施报告: worktree `docs/ops/245-batch2-impl-20261010.md`
- 方法: 只读 + 独立复跑(禁改代码/禁 push/禁云上写);探针 static-only(§18 L50);改动分级 = C 级(告警数据层)按全量口径审
- 实测规模: `git diff --shortstat main..HEAD` = **25 文件 +1831/-60**(代码 commit 单独 = 24 文件 +1536/-60;报告表「22 文件」= 代码+测试文件,不含 TASKS/pending-index/报告本体 3 件文书 —— 对账口径已核,无内容差)

## 结论

**FAIL —— 阻断 1 项**(F1 回滚面不完整:`ALERT_BUDGET_DISABLE=1` 不覆盖 monitor 批吸收层与 `--defer-digest`,与报告「L2 总开关,逐字节回现状」/规格 N15「全链回现状」不符;两开关同置会**静默吞掉**被吸收的批次告警)。核心机制(L2 gate/摘要缓冲/flush/D5/L3c/B4-3/W1)本身行为正确,默认路径(不置开关)无风险;修复量约 3~6 行。

## 一、12 项必查逐项

| # | 项 | 判定 | 证据点 |
|---|---|---|---|
| 1 | spec §0.2 七不变量 | **⑥ FAIL,余 PASS** | ①类别首条直发/②critical 升级档豁免(send_tiered `budget_exempt=(tier==TIER_CRITICAL)`,notify.py:2517)/③未映射直发/④被合并条目以 `[告警·摘要] 当日合并 N 条(含前日遗留 k 条)(cat a/...) MM-DD HH:MM` 出线 + 台账行 `tier=digest, merged_count=N`(notify.py:2402-2423,逐字对 spec §1.5 L147-149)/⑤ledger 机制自身不告警(alert_meter 只读)/⑦回滚开关=**FAIL 见 F1**;真实样本对照表 10-08 19→17、10-09 11→8 已按「演算非实测」诚实标注(报告 §五) |
| 2 | L2 核心机制 | PASS | gate 挂在 `send()` 单点入口(notify.py:1173),CLI 与 in-process 调用方全覆盖;计数=台账当日 group=alert 且 tier!=digest 行(`ledger_day_direct_counts`,adr.py:779-818,逐条核对口径),与 alert_meter 展示同源(§22);buffer 机械复用 warning 先例(`_append_jsonl`/`_stable_rid`/flushlock/write-then-truncate+fsync);`--flush-digest` 23:25 自门控 + 跨日 stale 兜底 + 状态仅成功发送后写;恢复闭环 D5 三路(窗过直发/当日摘要补列 `--defer-digest recovery`/次日 stale)均在(monitor L3012-3090、L3161-3195),`--defer-digest` 失败 `return 1` → 补列保留(notify.py `defer_digest` CLI 段);W2 两条签名已登记(notify_sent.py:107-109,行首锚定核过) |
| 3 | 红先验独立复现 | PASS | 主仓基线树(`/tmp/red245`,git archive main 的 scripts)—— ①直接跑: 34/34 全红(fixture 缺常量);②注入 3 个常量占位后按**行为差异**重跑: **26 红 / 8 绿**;8 绿=守卫型不变量(02b 首条直发/02c 未映射/02d 非 severe/02e dry_run/02f 台账缺失/02g 开关/02h critical/08 pending 不翻 recovered),26 红含全部机制判别(02 超预算吸收、03/03b 幂等、04b-e flush、05 digested 早退、06 W2、07b-e budget_process、08b-d、09);分支侧 34/34 绿。断言未放宽:test_181 21 处删除逐条核过:其中 3 处为断言行,全为等价/变严替换(常量断言 2 条→**4 条**更严;fetch_news 字面量断言→同语义 TASK_MECH 参数化,且 fetch_news 新行为另设 5 条 L3c 专测;零外发 `calls==0` 断言保留并**新增** transient warn 计数断言),其余删除为参数/文档头适配;test_245 为新文件无可放宽 |
| 4 | 负控 N1-N15 | PASS(2 处虚标见 F3) | 映射表逐项对 spec §6 核过;独立探针复核 N15(见 F1)与 gate 主链;N1/N2/N3/N4/N5/N7/N9 有真实行为用例且 main 侧红;N8 三路逐行读码确认;N11 由 `test_l3c_nontransient_unchanged` 逐字节断言;N14 = repo_paths.sh export + 13 py 行机检 |
| 5 | #246 交叠段 | PASS | 机检: #246 新增行在分支侧保留率 —— nextday_gap_check.py 56/56、schedule_monitor.sh 3/3、signal_kelly_backtest.py 110/110 全在;nextday_gap_check.sh 唯一「缺失」行=**刻意改写**(保留 main 的「双源兜底多轮退避」整句 + 修正「不同 dedup key 不互吞」为「py 已发时本条被抑制;py 未发时本条兜底」,与 B4-3 统一 key 后的真实语义一致);基=78322d943 核实 |
| 6 | 零外发铁律(#18 L48) | PASS | 打桩链先核后跑: test_245 fixture 三渠道整体打桩 + `ZeroOutboundTrap`(urllib/smtplib 最底层) + 收尾 `trap.hits==[]` 硬断言;test_181 `_FakeSub` + 真 subprocess/urllib/socket「一调用即 AssertionError」桩;**本次审查全部运行零真实外发**(见 §五 审计) |
| 7 | 测试独立复跑 | PASS | worktree: 全量 **723 passed/2 skipped**(92.18s);test_245 **34 passed**;test_181 **28 passed**。算术闭合: 主仓基线 **684/2** + 5(test_181 新增 L3c) + 34(test_245) = 723;2 个 skip = 既存基线(`test_212:386` 已提交态静态对照、`test_monitor_resource_inprogress:183` macOS APFS df 口径),与本批无关 |
| 8 | 报告数字对账 | PASS(2 处措辞夸大, 见 F2/F3) | 723/2、34、28、rebase 基线 684 全部实证一致;「22 文件」口径差为文书排除(见头部对账);§八 残余物归因措辞应从「非 pytest legacy helpers」订正为「pytest 薄包装套件在 pytest 进程内跑 legacy 模块」(见 §五) |
| 9 | §23.7 冻结面审计 | PASS | 全批删除行逐条归类: notify.py 仅 2 行(send 签名 + `_record_ledger` 调用点)、adr 仅 1 行(「no newline at EOF」重写)、alert_meter 6 行(件5 --week 输出/argparse 文案)、schedule_monitor 26 行(r5 调用/R2 块/恢复块/import 行,全为批内改写)、其余 13 个 py 均**一行式** NOTIFY_SOURCE(feishu_missed_fetch 另加 `import os`)+ repo_paths.sh 契约段与 export;无越权「顺手优化」;`--week --json` 输出 schema 变更(list→object)消费者仅 repro 脚本(文本模式),无生产消费方;不动前端/不动 AI 推荐默认组合,§5.4⑥ 免升基准、§21 公示不涉及 |
| 10 | 决策项:nextday_plan 同型分歧 | **需用户拍板(建议改)** | 见 §四 |
| 11 | worktree `data/alerts/` 合成残留 | PASS(非生产) | 残留=`alert_ledger.jsonl` 41850B + `latest.md` 1326B(18:33, 本次 worktree 全量跑所致),被 `data/.gitignore` 覆盖(git status 干净、`git ls-tree HEAD` 无 `data/alerts`,未 commit/未 push)⇒ 零生产影响 |
| 12 | 其他发现 | 见 §二/§三 | — |

## 二、阻断发现 F1(评分 82):回滚面不完整 —— `ALERT_BUDGET_DISABLE=1` 不是「全链」总开关

**声明 vs 实测**:
- 报告 §四 L120: 「回滚(零代码改): `ALERT_BUDGET_DISABLE=1`(**L2 总开关,逐字节回现状**)」
- 规格 N15: 「`ALERT_BUDGET_DISABLE=1` → **全链回现状(逐字节)**」

**实测(static-only 探针, REPO=tmp, 不碰生产)**:

| 层 | 开关置 1 后行为 | 判定 |
|---|---|---|
| ① notify.py `send()` gate | 短路跳过 → 直发(`digested` 键不出现, 渠道被调用) | 逐字节=现状 ✓ |
| ② monitor 批吸收 `adr.alert_budget_process` | **照旧全吸收**(2 条同类行 kept=[] 全 absorbed) | ✗ 未回滚 |
| ③ `--defer-digest` CLI(monitor 行级吸收/恢复补列用) | **照旧写入 buffer**(rc=0, 1 行) | ✗ 未回滚 |

探针实测输出(macOS venv, worktree 库代码):
```
A) monitor 层 alert_budget_process 在 ALERT_BUDGET_DISABLE=1 下:
   kept = []   absorbed = ['SEVERE: r2_upload_fail 上传失败', 'SEVERE: r2_unreachable 不可达']
B) --defer-digest 在 ALERT_BUDGET_DISABLE=1 下: rc = 0 | buffer 行数 = 1
C) send() gate 在开关下: digested 键存在? False | res = {'email': False, 'telegram': False, 'feishu': False}
```
根因: 开关只写在 notify.py 的 gate 条件里(notify.py:1172-1173);`alert_budget_process`(adr.py:828-864)与 `--defer-digest` CLI(notify.py:2608-2617)**无任何开关检查**。

**影响**:
1. 按文档「置 `ALERT_BUDGET_DISABLE=1` = 完整回滚」操作 → monitor 侧**仍在改变行为**(批次行被抽走、摘要仍外发),回滚声明不成立(应急场景最忌这个)。
2. 报告/规格指引的另一层(`ALERT_DIGEST_DISABLE=1`,文档明说「需配合总开关才是完整回滚」)与**未被总开关覆盖的 monitor 吸收**叠加 → 被吸收的批次行进了 buffer 但 flush 被停 → **这些告警永远不出线 = 静默丢失**(批次消息里已没有它们)。这正是本批要根治的"静默吞告警"类事故,出现在**自己的回滚路径**上。
3. N15 被实施自验标为 PASS(`test_02g` 只测 gate 层) → 负控表在这一点上是**虚标**(与 F3 同病)。

**修复建议(3~6 行, 二选一)**:
- 首选: `alert_budget_process` 开头加 `if os.environ.get("ALERT_BUDGET_DISABLE") == "1": return list(alerts), []`;`--defer-digest` CLI 开头加同款短路(返回 0 并打一行说明)⇒ 总开关=全链回现状,与文档一致。
- 备选(若刻意想分层回滚): 文档改为「总开关只回滚 gate 层;monitor 层吸收需 XX 开关(新增)」,并把 N15 声明改窄 + 在 digest-disable 文档处**加粗警告**「与 monitor 吸收叠加会吞告警」。但按 spec N15「全链」原意,首选才是合规格解。

## 三、非阻断低分清单(评分过滤: <75 仅记 0 条, 下 3 条 76~78 供主控裁量)

- F2(76) 报告 §3.3 组⑨「**全部调用方** ok 判定已适配」夸大: `test_09_consumption_points_adapted` 只静态检查 `notify.py` 自身两处(早退顺序 + r4 白名单),未核任何外部调用方。实查: in-process 消费方 `signal_kelly_snapshot.py:354` 仍为 `any(res.values())`(digested=True 会计入 ok → `update_dedup`;语义上**无害**——digested 本就该算「成功且已知」)、`check_nt_signals.py:161` 与本批无关。建议: 报告措辞改「notify.py 自身两处已核;外部 1 处 any() 形态经核无害」。
- F3(78) 负控 N12/N13(B4-3)无行为级用例: 映射表指向「规格 §3.2③ + test_09」——设计文档不是机检;monitor 侧新增的 exit 段 elif(nextday_gate 已发则抑制)与关键词段 `_r8_ngc_skip` 没有任何测试驱动(全 tests 目录仅 test_196 覆盖 `wrapper_channel_alerted` helper 本体)。`wrapper_channel_alerted` fail-open 语义我逐分支核过(repo None/last_run 不可解析/dedup 文件缺失/键缺失/JSON 坏 → 均 False=照发),代码正确,但「能抓坏」缺证据。建议后续批补 monitor 段行为用例(同 _absorb_loop_code 的 ast 提取法)。
- F4(76) 恢复消息文案: `notify_state` 判「suppressed」时 monitor 仍把该批 recoveries 入 pending 桶重试(monitor L3073-3084)——设计如此(suppressed=6h 窗吞,条目需走补列),但状态命名易误读;属提示级,不改亦可(已有 tail 补列 + stale 兜底三路)。

### trivia(不进评分)
- 报告 §二「22 文件」与 `git diff --stat main HEAD`(25)口径差 3 件文书,建议加「不含 TASKS/pending-index/本报告」限定词。
- ngc.sh 新文案「需人工核查」出现两次(照抄 main 句 + 批2 尾句),可精简一次。
- 报告 §八 残余物归因措辞见上 §一#8。

## 四、决策项 10 独立核查:py `nextday_plan_gen_fail` vs sh `nextday_plan_fail`

**结论: B4-3 式「重复告警缺陷」判定成立;「双保险不互吞」的论证站不住 → 建议改,但改法落入已发布告警行为 → 需用户拍板后实施(不建议本批顺手改,避免越权)。**

证据链(逐环可复现):
1. py 侧: R2 上传失败/超时/异常 → `_severe_alert`(key=`nextday_plan_gen_fail`,窗 3600)后 `r2_rc=1` → `return 1`(nextday_plan_generator.py:1191-1220、1272)→ 进程非零退出。
2. sh 侧: RC!=0 → 无条件 `notify.py --severe --dedup-key nextday_plan_fail --dedup-window 3600`(nextday_plan.sh:70-77)。
3. notify dedup 按 **key** 判 → 两键互不抑制 ⇒ **同一事件(秒级内)两封 SEVERE**:py 带明细 stderr,sh 带「次日买入计划未生成」汇总。
4. 同型先例 = 本批 B4-3(nextday_gap_check py/sh 同病,已按「统一 key」修):修复后 sh 段文案自己写明了新语义——「py 已发时本条被抑制;py 未发时本条兜底」。**兜底性不依赖「不同 key」**:py 未发(崩溃/超时/notify 挂)时统一 key 下无已发记录 → sh 照发。⇒ 升级为双保险不需要牺牲去重。
5. 额外失真: R2 失败时 py 的 `return 1` 带上来的 sh 文案说「次日买入计划**未生成**」——实际本地已落盘仅 R2 未同步,sh 兜底句误导;统一 key 抑制它反而减少错误信息。
6. 反对改的理由(如实列): ①nextday_plan 不在本批用户点头范围(「一起排」=L2/L3c/B4-3/W1+件5),B4-3 只点到 gap_check 对;②已发布告警行为属冻结面(§23.7),改动需用户确认。

**建议**: 主控带本证据上报用户,二选一: (a) 推荐——补一个小改动(与 B4-3 同法:py key 改 `nextday_plan_fail` 或 sh 侧同键),并在 py docstring 去掉「不同 key 不互吞=双保险」的过时论证,标注新语义; (b) 暂不改——则至少把 py docstring 那半句改成「双保险;已知与 sh 键不同 ⇒ 两类失败会双发,待收敛(同 B4-3 型)」,避免后人误信「不互吞」是刻意正确设计。

## 五、本次审查自身运行证据(零外发审计, 含一次主仓跑披露)

- worktree 内: `test_245` 34 passed(fixture 内 `trap.hits==[]` 硬断言通过)+ 全量 723 passed ⇒ 全部子集在打桩+trap 下运行。
- **披露(§23.2 自查)**: 为拿「rebase 后基线计数」我在**主仓**(checkout main, 与该批无关)跑了一次全量(pytest 脚本在 worktree 侧已先在白名单内审过),该主仓含真实凭据(`config/email.json` 等)。跑后取证: 主仓 `data/alerts/alert_ledger.jsonl` 新增 22 行(18:41:28-35, `source=__main__.py`),逐行溯源 = 4 个 legacy 薄包装套件(`test_notify_dedup_pytest`/`test_notify_flush_race_pytest`/`test_notify_reply_pytest`/`test_feishu_post_pytest`)在 pytest 进程内驱动 legacy 模块,其渠道**全部在进程内/子进程内 mock 或注入 `feishu_post`**(dedup L69-83 + 子进程 re-mock L424-431;flush_race L137-156 + 子进程 `_patch_channels` L54/115);`email:true/feishu:true` 为 mock 返回值 ⇒ **本次审查未产生真实外发**(数据面 = 主仓 ledger/latest.md 被写 22 行 mock 记录,已如实披露,不删改)。根因是薄包装套件不隔离 REPO(既存卫生问题,非本批引入);建议后续批给这批包装加 REPO/tmp 隔离(否则本地全套件跑都会污染主仓 alerts 页)。
- 我的全部探针: static-only、REPO=tmp、不跑业务脚本、不触渠道(探针 C 的渠道无凭据自然失败)。

## 六、复现命令(判据可重跑)

```bash
# 红先验(main 基线)
git -C <worktree> archive main scripts | tar -x -C /tmp/red245 && cp <worktree>/scripts/tests/test_245_*.py /tmp/red245/scripts/tests/
python -m pytest /tmp/red245/scripts/tests/test_245_*.py   # 34 红(再注入 3 常量占位 → 26 红/8 绿)
# 分支侧
python -m pytest scripts/tests/test_245_*.py               # 34 passed
python -m pytest scripts/tests/                            # 723 passed, 2 skipped
# F1 回滚探针
python /tmp/probe_245_rollback.py                          # A/B/C 三段见 §二
# #246 交叠机检: #246 commit 新增行 in 分支文件 的逐行比对(§一#5)
```

## 七、附:批2 订正定点复验(reviewer 续跑, 2026-10-10, tip `18149cd69`)

- 范围: F1 回滚面 / F3 N12N13 行为级真伪 / 报告订正抽查 / 快速回归 —— **4/4 PASS, 无新阻断, 原 F1 阻断闭环**。
- 证据: test_245 **38 passed**、test_181 **28 passed**、全量 **727 passed/2 skipped**(两次复跑同数, 与实施报告逐位一致); 变异对照 = 移除真源码 suppress 后 n12/n13 **双红**(能抓坏); ast 选择器各命中 1 段真源码(L703/L828)。
- F1 闭环: `ALERT_BUDGET_DISABLE=1` 三处短路齐(gate `notify.py:1172-1174`、`adr.py:842-843`、defer CLI `notify.py:2612-2615`); buffer 写路径**全集**(gate L1179 / CLI L2620)均被覆盖; 07hh/07hh2 反证半边在位。
- 残余(非阻断): digest-disable 单独置 = 积压不外发属规格明示行为(L152); legacy 套件不隔离 REPO 卫生项待后续批; 决策项 10 维持「同 B4-3 统一 key」建议待用户拍板。
- git 复核: 订正 commit `6d49df4f3` 范围干净(5 文件); merge 非 force(`a2d962a82` 仍为第一亲); 复验**未写主仓、未产生真实外发、无残留后台任务**。
- 主控收尾(补记): 本附录落档时已合 main(ff 至 `18149cd69`, CI run 787 绿)+ 云上同步 + §0 云上核验 PASS(云上 HEAD 全等 + 五文件 md5 5/5)。
