# r2_skip 告警误报修正 review(2026-09-24,reviewer 独立审查)

- 审查对象:分支 `worktree-agent-a4474317daa5a4a07`,commit `2912c0b03`(base `fd036824a`)
- 审查角色:reviewer agent(独立批判层,fresh context)
- 审查方式:全程只读——本地 worktree 临时 checkout 目标 commit 复验后还原,云上 ssh 只读查询,未 commit 未 push 未碰生产 R2 未改云上文件
- 结论:**PASS-with-conditions,可以 merge**(condition 见 F1/F2)

## 7 条钉死点逐条结论

### ① §14 命门(最重要)——不 FAIL,但有真实行为变化需用户知情
独立核实实施方声称的「低频任务真断已有独立告警覆盖」:
- overfit_monitor 在 schedule_monitor TASKS 表有漏跑检查(计划 21:40 + 30min 容忍窗口,`last_run < sch` 触发 SEVERE)+ DUR 900s(`DUR_THRESHOLDS`,只管"跑了但卡死",不管"彻底不跑")。
- 结论:任务真死最终会被漏跑检查发现,**但延迟从 r2_skip 的 45min(死前撞锁场景)变为次日 21:40 窗口(≤24h;周五死则跨周末更长,trading_day_only 设计)**。关键判断:r2_skip 对"任务死了"的覆盖本来就是条件性的(只有死前最后一次运行恰好撞锁 r2_skip_count>0 才响),它不是任务死亡的可靠告警源。改动没有让任何一类可靠真告警消失,但「死+死前撞锁」从快告警变慢告警,merge 时主控应向用户点明。

### ② 高频任务 SEVERE 一条没少——通过
独立复验(非 harness 输出):用 `git show 2912c0b03` 提取 NEW 代码,构造 intraday_snapshot 连续 5 轮 fresh last_run 场景,第 3 轮触发 SEVERE、计数终值 5,与 `git show fd036824a` 提取的 OLD 行为逐条一致。另云上 `alert_state.json` 有 `fetch_news|r2_skip_alert` recovered 记录(12:00 连续 3 轮真告警→22:00 恢复),证明中午真验改后仍有效。

### ③ §5.4⑦ 同构对账——声称成立,但 harness 设计脆弱
`verify_r2skip_fix.py` 的 `get_old_block()` 用 `git show HEAD:...`。独立实测:在 HEAD=2912c0b03(commit 后)复跑,OLD 块提取到的就是新代码,OLD/NEW 输出完全一样,且场景①②③全无 assert(只有存量过渡有),会假 PASS。报告表格里的 OLD 行为(22:15 SEVERE、终值 6)与用 `git show fd036824a` 提取 base 代码独立复验结果逐位一致——证明实施方确实是在 commit 前(HEAD=base)跑的,本次声称「从 git HEAD 逐字节提取」成立。但 harness 在 commit 后重跑即失效,建议后续把 `get_old_block` 显式 pin base commit 并给场景加断言。不阻断。

### ④ PIPESTATUS[0] 正确性——通过
本地 macOS bash 3.2 与云上 bash 5.1.16 双实测 `OUT=$(cmd | tee); rc=${PIPESTATUS[0]}` 结构:命令替换内管道时 PIPESTATUS[0] 可靠取到首命令真实退出码。三态沙箱:skip(rc=0+SKIPPED_LOCKED→⚠ 无✓)、成功(✓)、真失败(rc=3→✗+告警邮件+exit 1)全对。`set -uo pipefail` 无 `-e`,无意外退出。

### ⑤ 存量误报过渡不振荡——通过
云上现状:`overfit_monitor|r2_skip_alert` active(连续 7 轮,误报放大实证)、`r2_skip_rounds`=7、last_run=21:40(已超 30min 窗口)。改后第一轮即 stale 清零(7→0),alert key 本轮不 seen→主恢复循环发 1 封恢复邮件置 recovered;此后每日窗口内计数封顶 2<阈值 3 永不 SEVERE,加 6h 恢复 cooldown,三保险不振荡。

### ⑥ 同类错误面抽查 3 项——全部属实
- `scripts/overfit_monitor.py` L1822-1839:带 --skip-if-locked,returncode==0 时检查 stdout/stderr 含 SKIPPED_LOCKED 打显式标记,无假成功 ✓
- `scripts/fetch_news.py` L714-741:三态正确(skip 显式标记/成功 OK/失败 ⚠)✓
- `scripts/gen_schedule_stats.py`:普通路径 last_run 日志解析、EXTRA 路径 last_run=文件 mtime,last_run 供给在,生成端确实不用改 ✓

### ⑦ 分级+冻结契约(§23.7)——属用户已拍板的修复链收尾,非动历史功能
本次是用户拍板的 r2-false-success-rootfix 告警链(f200b14eb 起 24 日整条,含「用户拍板」commit)的收尾修 bug,针对当天上线几小时内的误报,不是"顺手优化老功能"。语义变更点(第①条)merge 时向用户汇报即可,不强制 pre-approval。

## 发现的问题(按严重度)

- **F1(中,不阻断 merge,需用户知情)**:低频任务「死+死前撞锁」的 r2_skip 快告警(45min)改为次日漏跑窗口告警(≤24h;周五死则跨周末)。现象:发现延迟;影响:任务死亡告警变慢但非静默(漏跑兜底在)。
- **F2(中低,不阻断,建议修)**:harness OLD 提取依赖 `git show HEAD`,commit 后重跑即 OLD=NEW 且场景①②③无断言仍 PASS。影响:复现段不可靠,同构对账声称有维护隐患。
- **F3(低,不阻断,观察项)**:`R2_SKIP_OBS_WINDOW=30min` 与 fetch_news 计划频率 30min 零余量。on-calendar 绝对时点下主场景正常,但 fetch_news 某轮延迟(卡住/排队)时 last_run 可能滑出窗口致连续计数被打断。建议观察期无回归后窗口可考虑放宽到 45min。
- **F4(信息)**:merge 上线后第一轮 monitor 会发 1 封「overfit_monitor r2_skip_alert 已恢复」邮件,这是误报解除通知,用户看到别误会成异常恢复。

## 硬约束确认
- 改后无任何 `except:pass`/静默吞错(消费块解析异常保守当 fresh,不吞真告警)
- 语法全通过(`/bin/bash -n` + python heredoc ast.parse)
- 未 commit 未 push 未碰生产 R2 未改云上文件
- commit 时点 23:16 在安全窗口内(盘后禁区 15:35/16:00/17:50/20:35/22:00 全避开)

## 审查过程关键实测(复现段)
1. 云上 bash 5.1.16 实测 PIPESTATUS 三态:`OUT=$(f 2>&1 | tee /dev/null); rc=${PIPESTATUS[0]}` → fail=3 / skip=0 / ok=0(与本地 bash 3.2 一致)
2. 独立复验 OLD vs NEW:`git show fd036824a` 提取 OLD 每日单次 skip → 22:15 SEVERE/终值 6;`git show 2912c0b03` 提取 NEW → 0 SEVERE/终值 0;高频两者都第 3 轮 SEVERE/终值 5
3. harness 脆弱性实证:HEAD=2912c0b03 复跑 `docs/ops/scripts/verify_r2skip_fix.py`,OLD(改前)与 NEW(改后)输出全同
4. 云上现状:alert_state.json 中 `overfit_monitor|r2_skip_alert` active(连续 7 轮)、schedule_stats.json overfit_monitor last_run=21:40 r2_skip_count=1
