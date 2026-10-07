# #232 `marker_buffer` 计数桶 seen 修复 —— 独立审报告(merge 前硬门槛,2026-10-07)

- **审查对象**:`feat/232-markerbuffer-seen-20261007` @ `91bea3778`(merge-base(origin/main, branch) = `0e061eb6f`,与派单声明 base-fresh 一致;origin/main 现 tip `e177f07a4` 为纯文档 commit 只动 TASKS.md)。
- **边界**:static-only —— 全程未 checkout 分支到主工作树、未运行 `scripts/schedule_monitor.sh` 本体(§18 L48)、未 ssh、未改仓库任何文件;判读用 `git show` 导出副本(/tmp/232-review/,md5 与 worktree/commit 逐位一致:脚本 `0291c26b44efc08e9815560eaf201350`、测试 `e6ae02e9c1fb1832c66ad430990ade1a`)。所有命令工具级 timeout 等效(macOS 无 coreutils `timeout`)。进度文件 `/tmp/agent-progress-232-review.md`。
- **结论**:**merge 资格成立**(10/10 必审项 PASS;低分项 4 条见文末,均不阻断)。

## 1. 改动面独立复算 —— PASS
- `git diff --stat main...feat`:4 文件 555+/1-。`scripts/schedule_monitor.sh` **+12 纯新增(0 删除)**:tip L777-784(7 注释+`seen_keys_this_run.add(_bk)`)、L837-840(3 注释+`"consecutive_count": 0`);两处外无任何 diff 行。
- 无夹带:通用恢复循环 L1682-1735 逐位未动;阈值未动(`TRANSIENT_TIMEOUT_THRESHOLD = 3`,tip L511);无候选 C 痕迹(`last_round`/`skip_rounds` 不在新增块)。
- `docs/pending-features-index.md` 分支净改动 = **仅 #232 一行**(单 hunk L354,1 行替换,逐字核)。
- merge 冲突面:main 新 commit `e177f07a4` 只动 `TASKS.md`(分支不碰该文件)、`git diff 0e061eb6f e177f07a4 -- scripts/` = 0 行 ⇒ 无冲突面(§23.11 不适用)。

## 2. 承重性(核心)—— PASS(独立变异,不采信执行者负控)
在 /tmp 副本四组独立变异(未动仓库):
| 变异 | 内容 | 结果 |
|---|---|---|
| mut_strip | 删 L784 seen 行 | **12 failed/4 passed**;test_reachability 直接证据:t2 `count` 卡 1(应 2),断言原文 `t2 count={...'consecutive_count': 1...}` ⇒ count 恒 1 复现 |
| mut_key | `add(_bk)` → `add(_bk + "_x")` | **12 failed/4 passed** ⇒ 检出的键正确性,非"行存在" |
| mut_incr | L764 `+ 1` → `+ 2`(真源码判据) | **7 failed/9 passed** ⇒ 测试 exec 的是真源码,非副本 |
| mut_reset | L840 `0` → `9` | **3 failed/13 passed** |
还原(=commit 版)= **16 passed**。执行者文件内负控(strip→count 恒 1/桶每 tick 翻 recovered/0 SEVERE)在修复版下 PASS,与我的独立剥离互相印证。

## 3. 复位语义反例 —— PASS
- 代码:inline 复位 L830-844 把桶翻 recovered;下轮 degrade 读 `status=recovered` → L768 `else` → `_c = 1` 重新起 ⇒ 无「残留续数」假升级。degrade×2→clean→degrade×3 仅第二条链 tick3 告警(test_reset_then_reaccumulate_fires)。
- 「只加 seen 不减」不存在:seen 只在 degrade 分支 add;`_bk` 全出现点复扫 = L760/761/770/784 + inline L831/832/834,无第二处 add;链断/无 anomaly/critical 轮桶未被标记 → 恢复循环 L1692 照旧翻 recovered(silent),不会永久 pending。
- L840 `"consecutive_count": 0` = **冗余但无害**(status=recovered 已使下轮重置为 1;全脚本无非 pending 状态读 count 的读者;与 r2_intraday_lag L2219-2223 同款;被测试钉住)。保留合理,**不引入新风险**。
- 注:恢复循环对非 pending/active 状态 continue(L1697),`alerted` 桶只由 inline clean tick 复位 —— 与修复语义一致(§10.6 删除视角:该 4 行可删但代价=测试语义弱化,判不值)。

## 4. 判别力与新误报面 —— PASS
- 无 anomaly 任务不建桶(代码 L708 门控 + test_clean_task_never_counted);critical/None severity 走 L805-818 直报不进桶(test_non_degrade_anomaly_not_counted);2 tick 不报/3 tick 报(test_boundary_two_vs_three_ticks)。
- **新误报面独立评估**:生产日志 `/tmp/181-monitor-full.log`(实测 **14,999 行 / 1.59MB**,日期 09-11→10-07 **连续 26 天**,逐日直方图可数)→ `marker_buffer` 全部命中 **4 行 = 2 组**(同 tick 建 pending + silent recovery 连打,行号 10366/10370、14217/14219,逐字复现),`连续2/3|3/3` 命中 **0** ⇒ 「≥3 tick 连续 degrade 生产 0 例」在我可核窗口内成立。
- 反例路径(有但受设计约束):post-fix 激活「alerted 桶 + 行逐 tick 变化 → 逐 tick SEVERE」(L765-767+L792,修复前为死代码;设计注释自述「换脸→直接升级可见」)。触发需 ≥3 连续 tick degrade 且行 md5 每 tick 变化;degrade 供给链(gen_schedule_stats.py L643-662 未定论窗口 / L753-791 EXTRA 轮作用域窗口)下,单 round 的 ⚠ 至多存活到窗口滚出/下一 round 起点,3 tick 连续 ≈ 真持续性降级(45min 未定论哨的**设计语义**)。判定:结论可信、残余理论面已被定性 §5.2a + impl 报告 §④ 诚实标注并给出 2 周观察期,承接满足,不阻断。
- 备注(低分项):定性报告称该日志「157 万行」与实测不符(疑 1.57MB 误写);其 grep 结论本身我已逐条复现,窗口连续,不影响结论。

## 5. 测试真伪(防第二份实现 / §18 L49)—— PASS
- ast 提取 heredoc 真代码块 exec:已证(mut_incr 改真源码判据 → 测试红;还原 → 绿)。
- `_MIN_ASSERTIONS=40`;**实测 `_N=69`**(进程内 pytest 后读 `test232._N[0]`,与执行者自报 69 一致)。
- §18 L49:fixture 字段逐一对照**真生产者**——`gen_schedule_stats.py:1044-1052`(log_anomaly/log_anomaly_keyword/log_anomaly_line/log_anomaly_severity 四字段名)、值 `"degrade"` 见 `:661`/`:788`、last_run 格式 `%Y-%m-%d %H:%M` 与 monitor 解析(tip L723/L1166)一致 ⇒ 无「现实不存在字段」。真 SEVERE 样本生产不存在(零报 bug),但测试不依赖真样本:用真实字段最小构造 + 生产日志已证的行为(同上 4 行)复现;桶 pre-state 形态=本代码 L770-776 自身产出形态(与 missed/not_loaded 既有 pending 桶同构)。云上两桶(first_seen==last_recovered 同秒)本次未再独立拉取(无 ssh),诊断价值已由日志复现替代。
- 红先验独立复现:pre-fix(`0e061eb6f` 版脚本)**12 failed / 4 passed**;4 个 pre-fix 通过 = `test_generic_recovery_loop_untouched` + clean/non-degrade/2-tick 三个不误报用例 —— 与执行者解释**逐条一致**,且这三个本属"两版都应绿"的负向用例,不是检出力的载体;min_assertions_guard pre-fix FAIL(37<40,早停),合理。
- CI 收集面:`.github/workflows/ci.yml` L109-112 = Job 1 `quality-gate-static`(**FAIL 阻断**)`python3 -m pytest -q scripts/tests/`,路径相交 ✓;测试仅 stdlib+pytest,CI(py3.11)可直接跑。

## 6. 零真实外发自证 —— PASS
- 哨兵拦截力变异:测试副本 `_drive` 注入 `socket.create_connection` 门控 → `MUT_SENTINEL=1` 跑 `test_zero_real_outbound` = **RED**(AssertionError「自测发生真实外发…」);去掉 env = GREEN ⇒ 哨兵真会拦。
- 提取块结构核读(alerts.append / alert_state 读写 / print / hashlib / 纯函数 `_recurrence_suppressed`)无外发出口;未运行 monitor 本体。

## 7. 回归面 —— PASS
- diff 仅两处新增 ⇒ r2_/72h_ 前缀保护、missed/extra_stale/_ri_key/exit 分支**逐位不变**(diff 即证);main 自 merge-base 未动该脚本(0 行 diff)。
- `seen_keys_this_run` 读取点全量枚举 = 仅 L1692/L1718(恢复循环);新增仅 `_bk` 一键 ⇒ 无「顺带加键致新假阴性」;test_seen_set_contains_only_own_keys 钉死(一次 degrade tick 的 seen = 桶 + log_anomaly dedup,恰 2 键)。
- 同族测试回归:7 个引用本脚本的测试文件(worktree 版,对修复版脚本)**175 passed / 1 skipped** ⇒ +12 行不破坏同族断言。

## 8. 同类面复核 —— PASS
- 独立重数:全脚本写 `"status": "pending"` = 5 处(missed L407 / marker_buffer L771 / not_loaded L1358 / r2_unreachable L2016 / r2_intraday_lag|buffer L2168)+ judge 消费 2 键(alert_denoise_rules.py,消费点 tip L1893/L2068)= **7 处**,与执行者 §⑥ 表一致。
- 口径差异核清:定性「13 条链」= 全部计数/状态链;「7 处」= 写 pending 状态的子集;差集 6 条(extra_stale/round_incomplete/exit!=0/dur/in_progress_timeout/r2_skip)逐点核实**均非 pending 写状态**(in_progress_timeout 写 active L1193-1199;r2_skip 计数键用 `skip_rounds` 字段 L1029-1034)→ 同集合不同粒度,无漏。
- 免疫机制核:5 个 pending 写点各有 seen(missed L381 / not_loaded L1353 / r2_unreachable L2012 / r2_intraday_lag L2154 / 本次 marker_buffer L784)+ judge 键 count 不依赖 status + 复位清 count + 日期维度 ⇒ 唯一病态=marker_buffer,复核一致,未发现第二条病态链。

## 9. git 纪律 —— PASS
单 commit(rev-list=1,无 merge)、线性、base-fresh(merge-base=`0e061eb6f`)、远端 `refs/heads/feat/232-...` == tip(`ls-remote` 91bea3778)、无强推迹象(全新分支 ref)、trailer 在(Co-Authored-By: Claude Code)、无大文件夹带(4 个文本文件)。
低分备注:impl 报告 §base 与分支上 pending-index 行文写"(base c233e63af)",实际 merge-base=0e061eb6f(c233e63af 为其父;两 commit 间该脚本逐位相同)——文档不精确,不阻断。

## 10. 可逆性 —— PASS
- `git revert 91bea3778` 干净:单 commit;main 未动该脚本/pending-index 行(e177f07a4 只动 TASKS.md)⇒ 无回滚冲突;恢复路径 = revert 或 `git checkout <base> -- scripts/schedule_monitor.sh` + 删测试文件。
- 无新字段/无 schema:inline reset 字段名未变(仅加既有字段的显式值);桶新态(pending/alerted 存活)对旧代码字面兼容(旧 else 分支照常重置为 1)——回滚后既有桶由旧逻辑正常自愈。

## 低分项(<80 已滤,防黑箱,4 条均不阻断)
1. (50) 定性报告「157 万行」vs 实测 14,999 行/1.59MB;结论未受影响(全部 grep 已复现)。
2. (50) impl 报告/pending-index 的 base 标注 `c233e63af`,实际 `0e061eb6f`(父提交,内容同)。
3. (50) test 的 `_simulate_recovery_loop` 是恢复循环第二实现(pending 分支与真源码逐字一致;missed/in_progress 分支有偏差但全部用例不触及)——未来若动 tip L1682-1735,须同步核对该测试。
4. (60) post-fix 新激活「alerted 桶 + 行逐 tick 变化 → 逐 tick SEVERE」路径(设计语义,与 r2_lag 单告警键有别);26 天窗口 0 例,观察期建议已在 impl §④,不阻断。

**merge 资格:成立。** 上线后按 impl 报告 §④ 执行 2 周观察期复核该链 SEVERE 数量与真伪。

---
**编制**:reviewer 子 agent(fresh context,2026-10-07)。方法与边界:static-only + 独立变异(4 组)+ 红先验复现 + 同族测试回归;未运行 monitor 本体、未外发、未改仓库代码。
