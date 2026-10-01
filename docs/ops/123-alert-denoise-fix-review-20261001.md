# #123 告警降噪修复第二轮独立复验(reviewer,2026-10-01)

> 审查对象:分支 `worktree-agent-af1e103df45f2939c`,HEAD `212e2a12b`(fix `c3256126d` + docs `212e2a12b` 重放在第一轮 `6ff3c0bad` 上)
> 审查者:独立 reviewer(非实施者),全只读不 commit 代码
> 判定:❌ **FAIL**(R5 双重致命 / R1 恢复循环误报 **两个缺陷本身修复成立**;FAIL 原因 = 必查项④补审 R4 拦截块 36 行发现 **update_dedup 无条件落盘**新静默风险,第一轮漏审,未修)
> 上级报告(第一轮 FAIL):docs/ops/123-alert-denoise-implementation-review-20261001.md;修复报告:docs/ops/123-alert-denoise-fix-r5-r1-20261001.md

## 结论(给主控)

- **① R5 双重致命:修复成立(PASS,亲手跨进程实测)**。无条件调用 + 调用后立即 save_alert_state 均按行号到位;模拟 systemd「每轮独立进程」(subprocess 新进程 + 真实 alert_state 文件落盘读回)实测:跨轮 3 种 R2 = 首条直发 + 第 2/3 种现象落盘累计 + 23:30 汇总必发;收尾轮空 alerts 汇总仍然发出。同一测试套旧版调用结构(`if alerts:` + 无 save)忠实复现第一轮 FAIL 两个症状,新版全消。
- **② R1 恢复循环误报:修复成立(PASS,正反例双实测)**。r1_buffer_judge 恢复路径支持 `"recovered"` 也清 consecutive_count(改在判定函数内,不在恢复循环,理由成立);带恢复循环真实执行序实测:滞后→恢复→再滞后 = `buffer/ok/buffer` 不回 alert;真连续 2 轮滞后 = 第 2 轮照常 alert(不吞真故障,§降噪头号判据保留)。旧版同测 = `buffer/ok/alert`(原误报复现)。
- **③ 测试盲区:补齐(PASS)**。26→35 项,R1 新增场景 F/G/H 插恢复循环、R5 新增 4 场景走真实文件读写(load→r5→save→下一轮 load),非直连判定函数;我的独立测试(不同实现路径,直接从 schedule_monitor.sh 提取真实行 + subprocess 独立进程)复现相同结果,排除假绿。
- **④ 举一反三:模式一/模式二成立,但 R4 36 行补审出一个第一轮漏审的静默风险(FAIL 点)**:
  - 模式一:我独立数出 39 处写入点(超出自述 23,含子键修改 `_info[...]`/`_bf[...]` 等),逐处核对其后第一个 save_alert_state 全部存在;R5 是唯一「修改后无落盘」点,已由新增 L2159 无条件 save 修复。**穷举无遗漏,唯一遗漏已修**。
  - 模式二:全文件 `if alerts:` 仅 R5 块一处(L2160),R5 确为唯一收尾汇总逻辑,修复后不再受 if 包裹。
  - **新增 finding(FAIL 依据)**:`scripts/notify.py` R4 分级拦截块 L2126 的 `update_dedup(args.dedup_key)` 无条件执行——不看 `send_tiered` 发送结果、不区分 tier,违背同文件通用路径 P1-1 契约(L2151 带 `and ok`)与 update_dedup docstring「发送成功才更新」。后果:发送全失败(邮件/飞书/TG 通道故障)时该 key 仍记 dedup → 6h 窗口内 staticdata 备份失败告警被 check_dedup suppression 不重试;且调用方(staticdata_backup_async.sh L410-414)不带 `--alert-issue`,dashboard 也无落盘 → **发送故障恢复后当天备份失败告警可能完全静默**(备份每日一轮,6h 后无下一次调用可重试)。另 info 级(不推送)也占用 6h 窗口,若 6h 内升级 severe(连续 2 天未追平)会被 suppress(跨天时点下触发概率低)。
- **⑤ rebase 无丢内容(PASS)**。`git diff 6ff3c0bad 212e2a12b` 仅 4 文件:alert_denoise_rules.py +9/-1、schedule_monitor.sh 单 hunk(@@ -2147,33 +2147,39 @@,即仅 R5 块一个改动区)、test +115、docs 新增 231 行;第一轮 9 个函数/常量逐字在位、全部 adr. 调用点(R1×3/R2×4/R3/R5/cleanup/跳过)在位;notify.py/check_signals.py 0 行。
- **⑥ 冻结契约(PASS)**。fix 对 notify.py/check_signals.py 零改动,邮件/飞书正文构造逐位未变;R4 拦截将调用方 subject/body 原样透传 send_tiered,不改造正文;§23.10 飞书与邮件同源(send_tiered 内 send() 全渠道)不受影响。

## 1 必查项①:R5 双重致命修复(实测 + 行号)

### 1.1 行号顺序核(c3256126d 后 schedule_monitor.sh)

```
L2155  _orig_has_alerts = bool(alerts)
L2156  alerts, _r5_summary = adr.r5_congestion_process(alert_state, alerts, NOW)
L2157  if _r5_summary:
L2158      alerts.append(_r5_summary)
L2159  save_alert_state(alert_state)          ← 调用后立即落盘 ✓
L2160  if alerts:                             ← 三分支,与旧 if 结构解耦
L2181  elif _orig_has_alerts:                 ← 保留「接管提示」语义
L2184  else:                                  ← 「OK」语义
```
与修复自述一致:无条件调用(不在 if alerts 内)、save 紧跟 R5 状态修改、`if not alerts:` 旧内层判空被三分支替代(else 分支处理「无告警+无接管」的 OK 行)。

### 1.2 独立跨进程实测(每轮 = 新 subprocess 进程,真实文件落盘读回)

脚本:`/tmp/rev123b/rev_indep_r5.py`(R5 调用点 + load/save 从 schedule_monitor.sh L207-228/L2155-2159 提取;每轮 `subprocess.run` 起独立 python 进程,与 systemd 15min/轮新进程同构)。关键输出:

```
========== 场景1: 跨轮 3 种 R2 告警(14:15/21:00/23:30) ==========
--- 轮 14:15 --- SEND:1 items ['SEVERE: r2_unreachable ...']
STATE_AFTER: {"phenomena": ["r2_unreachable ..."], "summary_sent": false}
--- 轮 21:00 --- [r5-congest] 第2种 R2 现象并入当日汇总(...)
TAKEN_OVER(提示不发, 现象已并入汇总状态)
STATE_AFTER: {"phenomena": [2 项], "summary_sent": false}   ← 跨进程读回 ✓
--- 轮 23:30 --- 生成当日拥堵汇总(23:30, 3 项现象)
SEND:1 items ['SEVERE: R2/部署链路拥堵日汇总 20260930 (3 项同根因现象...']
STATE_AFTER: {"phenomena": [3 项], "summary_sent": true}
========== 场景2: 前两轮聚合后, 23:30 收尾轮 alerts=[] ==========
--- 轮 23:30 alerts=[] --- 生成当日拥堵汇总(23:30, 2 项现象)  → 收尾轮空 alerts 汇总必发 ✓
SEND:1 items ['SEVERE: R2/部署链路拥堵日汇总 20260930 (2 项...']
========== 场景3: 同轮 3 种 R2 @14:15, 23:30 收尾轮出汇总 ==========
--- 轮 14:15 --- 第2/3种并入, SEND:1 (首条照发)
--- 轮 23:30 --- 生成当日拥堵汇总(23:30, 3 项现象), SEND:1
```

结论:跨轮现象落盘累计(1→2→3 种跨进程可见)、收尾轮空 alerts 汇总发出、同轮 3 种「首条直发 + 汇总全列」,无一条永久静默。

### 1.3 旧版调用结构对照(证明测试敏感,非假绿)

脚本:`/tmp/rev123b/rev_r5_old_vs_new.py`(旧版结构 = `if alerts:` 内调 + 无 save;新版结构 = 无条件 + save,函数本体同一 r5_congestion_process 依据各自版本):
```
旧版: (14:15, SEND, 1) / (21:00, TAKEN_OVER_NO_SEND, 0) / (23:30, NO_R5_RUN(alerts空, R5不跑), 0)
新版: (14:15, SEND, 1) / (21:00, TAKEN_OVER(提示), 0) / (23:30, SEND, 1)
```
第一轮 FAIL 两个症状(第 2+ 种静默 + 收尾汇总不发)在旧版结构下完整复现,新版全消。

## 2 必查项②:R1 恢复循环误报(正反例 + 旧版对照)

### 2.1 代码位

- 修复在 `alert_denoise_rules.py` r1_buffer_judge 恢复路径(约 L56-66):`if _bf and _bf.get("status") in ("pending", "alerted", "recovered")` 才清 consecutive_count(新增 "recovered")。
- 位置选择正确:不在恢复循环(L1185-1209)清——恢复循环每轮先跑,会把上一轮 pending 置 recovered 但不清 count;若在恢复循环清 count,真连续 2 轮滞后会被降级(轮2 滞后时 count 被清 0 → 轮2 误 buffer)。修复放判定函数恢复路径 = 只对「本轮确实恢复」清计数,不吞真故障。

### 2.2 独立实测(真实 r1_buffer_judge + 恢复循环真实逻辑提取)

脚本:`/tmp/rev123b/rev_indep_r1.py` + 旧版对比 `/tmp/rev123b/rev_old_new_compare.py`:
```
== 正例: 滞后->恢复->再滞后 三连 ==
新版: ['buffer', 'ok', 'buffer']  PASS(回 alert 才 FAIL)
旧版: ['buffer', 'ok', 'alert']   FAIL(第一轮误报完整复现)
== 反例: 真连续 2 轮滞后(24,25min), 第 2 轮必须 alert ==
新版: ['buffer', 'alert']  PASS(不吞真故障)
旧版: ['buffer', 'alert']  (旧版该场景本就不误伤)
== 反例延伸: 真连续2轮后恢复, 再滞后从0计 ==
新版: ['buffer', 'alert', 'recover', 'buffer']  PASS
== 对照组: 单轮滞后->恢复->再滞后(隔开恢复) ==
新版: ['buffer', 'ok', 'buffer', 'ok', 'buffer']  PASS
```
真故障反例对应代码行:`r1_buffer_judge` 滞后分支 `_c = (_bf.get("consecutive_count") or 0) + 1`(轮2 被恢复循环置 recovered 但 count 保留 1 → count=2 → alert 照常触发)。

## 3 必查项③:测试盲区补齐确认(非直连判定函数)

- 新测试 `scripts/tests/test_alert_denoise_20261001.py` R1 场景 F/G/H:`r1_with_recovery_loop` 逐轮先执行恢复循环真实逻辑精简版(pending 未 seen → recovered 不清 count),再调真实 r1_buffer_judge——**插入了恢复循环**,修复前此场景必 FAIL(断言含 `r_F[2] != "alert"` 等)。
- R5 场景 A-D:`r5_monitor_sim` 每轮 load 真实 alert_state 文件 → r5_congestion_process → 写回文件 → 下一轮重新 load,**走真实文件读写**,非直连。
- 假绿排除证据:修复前代码(6ff3c0bad)跑我的独立测试 R1 三连 = `['buffer','ok','alert']`、R5 旧调用结构 = 收尾轮不跑 → 证明测试方法能抓缺陷;修复后全过。
- 35 项断言实测全部 PASS(已跑)。

## 4 必查项④:举一反三核查结果(FINDING 所在)

### 4.1 模式一:写入点穷举(独立统计)

schedule_monitor.sh 全文件对 alert_state 的写入(含 `alert_state[...] =` 与子键 `_info[...]`/`_bf[...]` 修改)共 **39 处**,每一处的行号后都跟有 save_alert_state(6 处既有:1281/1450/1722/1809/1950/2088 + 新增 2159):
```
写 L332..1230(29 处)-> 后随 save L1281
写 L1414/1435/1436       -> L1449(overview 块内补存)
写 L1511..1715(6 处)     -> L1721(R2 块补存)
写 L1782                 -> L1808
写 L1918                 -> L1949
写 L2062                 -> L2087
R5 修改(r5_congestion_process 内部写 phenomena/summary_sent)-> L2159(修复新增)
```
结论:无遗漏写入点;R5 是唯一「修改后无落盘」已被修复。自述「23 个」少数了子键修改类(口径差异),不影响结论。

### 4.2 模式二:`if alerts:` 全文件唯一性

```
grep -n "if alerts\|elif _orig_has_alerts" → 仅 L2160 / L2181(R5 块)
```
R5 确为全仓唯一「收尾汇总被 if 包裹」逻辑;`--flush-warnings`(L2270)无条件调用,不属此模式。

### 4.3 ⚠️ FINDING:notify.py R4 拦截块 update_dedup 无条件落盘(静默风险,FAIL 依据)

**位置**:`scripts/notify.py` L2106-2132(R4 分级拦截块,第一轮 6ff3c0bad 新增 36 行,本次 fix c3256126d 未动)。
**证据(逐行)**:
```python
if args.dedup_key == "staticdata_backup_fail":
    _r4_tier, _r4_reason = adr.r4_staticdata_grade(...)
    if not args.dry_run and check_dedup(args.dedup_key, 21600):
        return 0
    ...
    if _r4_tier == "severe":
        results = send_tiered(... TIER_CRITICAL ...)
    else:
        results = send_tiered(... TIER_INFO ...)
    if args.dedup_key and not args.dry_run:
        update_dedup(args.dedup_key)        # ← L2126 无条件,不检查 results
```
对照同文件通用路径 L2149-2151(P1-1 契约,2026-08-11 修复「偶发失败致消息永久不发」):
```python
if args.dedup_key and not args.dry_run and ok:
    update_dedup(args.dedup_key)            # ← 带 and ok
```
update_dedup docstring:「发送**成功**后更新 dedup_key 的 last_alerted……调用方须在确认至少一个渠道发送成功后才调用本函数;发送失败不更新 dedup,下次调用可重发」。

**静默后果链**:
1. staticdata_backup_async.sh L410-414 调 notify.py `--dedup-key staticdata_backup_fail`(**不带 --alert-issue**,dashboard 无落盘);
2. 某轮发送全失败(邮件/TG/飞书通道故障,P1-1 历史证明该故障真实发生过)→ R4 块仍 update_dedup;
3. 后续 6h 内任何 staticdata_backup_fail 调用被 `check_dedup(21600)` suppression 直接 return 0 → 不重试;
4. 静态备份每日一轮(晚间),6h 后无下一次 fail 调用 → **当天备份失败告警完全静默,用户不可见**。
另:info 级(不推送,`log_info` 仅记 dashboard)也占 6h 窗口,若 6h 内升级 severe(连续 2 天未追平)会被 suppress(跨天时点下概率低,不单独计)。

**这不是本轮 fix(c3256126d)引入,是第一轮 feat(6ff3c0bad)R4 36 行引入而第一轮漏审**;但主控必查项④②明确要求审「R4 36 行有没有引入新的静默吞掉」→ 命中,须上报。
**修复建议(极简,与通用路径同构)**:
- L2126 改为 `if args.dedup_key and not args.dry_run and any(results.values()): update_dedup(args.dedup_key)`(severe/info 都只在真发送成功时占窗);或在 send_tiered 后取 `ok = [ch for ch, v in results.items() if v]` 再判。
- 可选:info 级不 update_dedup(避免 info 占 severe 窗)。

## 5 必查项⑤:rebase 无丢内容

```
git log --oneline 6ff3c0bad..212e2a12b → c3256126d(fix) + 212e2a12b(docs),仅 2 commit
git diff --stat 6ff3c0bad 212e2a12b:
  docs/ops/123-alert-denoise-fix-r5-r1-20261001.md | 231 +
  scripts/alert_denoise_rules.py                   |   9 +-
  scripts/schedule_monitor.sh                      |  58 +++---
  scripts/tests/test_alert_denoise_20261001.py     | 115 +
  (notify.py / check_signals.py 0 行)
```
- alert_denoise_rules.py 删除仅 1 行(status 判断被修复替换);9 个函数、全部常量与旧版逐字一致(diff 常量块 0 差异)。
- schedule_monitor.sh 仅 1 个 hunk(@@ -2147,33 +2147,39 @@,R5 块);删除行全部为第一轮 buggy 块,第一轮其他改动(R1 调用点 L1402/1578/1611、R2 L723/738/926/942、R3 L495、cleanup L1171、跳过 L1181)全在位。
- 结论:fix+docs 只含预期改动,零回退。

## 6 必查项⑥:冻结契约

- fix 对 notify.py / check_signals.py 0 行改动(§5 stat);第一轮 R4 只改「dedup_key==staticdata_backup_fail 时的分级/发送路由」,subject/body 原样透传 send_tiered → 正文构造逐位未变。
- §23.10:send_tiered → send() 全渠道(邮件+飞书同源),R4 无「邮件发飞书不发」分叉;info 级 log_info 只记 dashboard 不推送(设计内,第一轮已审)。
- schedule_monitor.sh 的 R5 汇总走通用 alerts 通道(notify.py 无 feishu 参数),与第一轮判定一致。

## 7 回归/影响面

- 本次 fix 改动面:alert_denoise_rules.py(R1 恢复路径)+ schedule_monitor.sh(R5 块)+ 测试 + docs。R5 块新结构与旧结构行为差异已实测覆盖(三分支各路径:发信/接管提示/OK 均验证)。
- 恢复邮件块(在 R5 块之后,`if recoveries:` 独立于 R5)不受影响,L2200-2xx 原样保留。
- alert_state.json 由 R5 新增无条件 save:仅是更频繁落盘(r5_congestion_process 无修改时原样写回,幂等),无新增风险;每轮多一次文件写,可忽略。

## 复现段

- 测试脚本(实施侧):`scripts/tests/test_alert_denoise_20261001.py` 35 项断言,PASS(实跑确认)。
- 本审查独立实测:`/tmp/rev123b/rev_indep_r5.py`(跨进程 R5,场景1/2/3)、`/tmp/rev123b/rev_indep_r1.py`(R1 正反例)、`/tmp/rev123b/rev_old_new_compare.py`(R1 旧版 FAIL 对照)、`/tmp/rev123b/rev_r5_old_vs_new.py`(R5 两版调用结构对照);临时目录 /tmp/rev123b(212e2a12b archive)。
- 关键代码位:schedule_monitor.sh L2155-2184(R5 修复块)/ L2159(新增 save)/ L1185-1209(恢复循环)/ L1402-1408(overview 块 R1 调用);alert_denoise_rules.py L56-66(R1 修复)/ L241-281(r5_congestion_process);notify.py L2106-2132(R4 拦截块,含 L2126 finding)/ L2149-2151(P1-1 通用路径)。
