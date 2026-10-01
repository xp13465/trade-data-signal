# #123 R4 拦截块 update_dedup 修复第三轮复验(reviewer,2026-10-01)

> 审查对象:分支 `worktree-agent-af1e103df45f2939c`,远端 HEAD `5a6439c2d`(R4 修复 commit,在 rebase 后新链顶部)
> 审查者:独立 reviewer(非实施者),只读审查,适用 `git archive` 取代码,不 checkout/不 push main
> 判定:✅ **PASS**(六项必查全部亲手复现且成立)
> 依据:① 后果链闭合实测 ② 药方偏离独立判定成立 ③ 举一反三独立核成立 ④ 强制回归+假绿排除 ⑤ no-loss 逐对 SAME ⑥ 冻结契约仅动 dedup 判据

## 结论(给主控)

- **① R4 后果链真闭合(PASS,独立构造实验 6 项 ALL PASS)**:不对 send_tiered 打桩,而是对最底层 `_send_email/send_telegram/send_feishu` 打桩,让真实 send() + send_tiered() + main() R4 块完整执行,验证:
  - 全渠道发送失败 → dedup **不写入**(key_present=False);下一次调用**真重试**(渠道函数被真调用,非 suppress)——当天备份失败告警不再被 21600s 窗静默吞掉;
  - 任一渠道成功(email) → dedup **照常写入**;窗口内二次调用被 suppress——去重语义保留,不引入告警轰炸;
  - info 级 → 不占窗(渠道全 False,`info_logged` 被过滤)。
- **② 偏离上一轮药方「and any(results.values())」——判定:偏离正确,不是偷懒**。`send_tiered` 返回结构实测:critical 形态 `{"tier", "email", "telegram", "feishu"}`(4 键);info 形态 `{"tier", "email":False, "telegram":False, "feishu":False, "info_logged":True}`(5 键);warning 形态同形含 `deferred:True`。`info_logged` 在「渠道全失败」时为 True(实测 `any(info返回.values())=True`)——药方字面 `any(values())` 在 info 级恒判「成功」→ info 级仍占窗,违背审查「可选:info 不占 severe 窗」且违背「发送成功才更新」契约。修复改按渠道字段白名单 `("email","telegram","feishu")` 过滤:完全覆盖 send() 返回的三个真渠道,**无漏渠道**(不会真发出却不占窗=轰炸)、**无多键**(tier/info_logged/deferred 被滤掉=不回旧 bug);与通用路径语义一致(通用路径 L1324/L1895 的 `any(values())` 针对 send() 返回恰三渠道,无需改)。
- **③ 举一反三独立核成立(PASS)**。4 处 `update_dedup(` 调用点逐处实读:L747(`ok = _send_email(...)` 带结果)、L1324(`any(results.values())`,send() 返回三渠道)、L2157(通用路径 `and ok`)三处均带发送成功判据;R4 块 L2133 是全文件唯一「不检查发送结果就 update_dedup」的点,已修。`defer_warning` 返回值忽略「不改」理由站得住(R4 块只走 critical/info 不触 warning;append 失败有 print 留痕非静默;warning 聚合有 flush 兜底+锁序;改返回结构=需求外改动)。自己再扫一遍:`send_tiered` 全文件仅 3 调用点(L2072 只 print 不消费返回值 / L2116+2121=R4 块已修);`flush_warning_batch` L1894-1898 带 `sent = any(results.values())` 判据;`notify_agent_done` 带 any() 判据;`write_alert` 无条件写 dashboard 但语义=「记录告警事件」与发送无关,属防静默的正确方向;`_mirror_severe`/`clear_warning_dedup_for_recovery` 均 best-effort 不影响发送。无其他「静默吞真故障」落盘点。
- **④ 强制回归(PASS,假绿排除成立)**:分支上 `test_alert_denoise_20261001.py` 实跑 **35 check 断言 0 FAIL**;`test_notify_r4_dedup_20261001.py` 实跑 **6 场景 ALL PASS**。假绿排除:把 R4 块回退为旧无条件 `update_dedup`(改 /tmp 副本非生产)再跑,两套测试均 FAIL(独立实验 A 全失败 key_present=True / A2 下次被 suppress / C info 占窗三症状完整复现;实施测试场景 3/4/5 FAIL),恢复后 ALL PASS——测试对旧 bug 敏感,非假绿。
- **⑤ force-with-lease no-loss(PASS)**。旧链(6ff3c0bad→c3256126d→212e2a12b)与新链(ff074d1a9→ca794a44e→4ec390ad0)三对 commit **patch-id 逐对 SAME**:6ff3c0bad≡ff074d1a9(7380ac8e)、c3256126d≡ca794a44e(7af21184)、212e2a12b≡4ec390ad0(0ed4e019)——同一 patch 重放,无内容回退/丢失。上一轮 review 引用的代码全部在位:notify.py R4 块(行号因本次 +8 行注释从 L2106-2132 下移至 L2106-2136)、通用路径 `and ok` L2157-2158、update_dedup docstring L1234-1241、staticdata_backup_async.sh 调用点 L456-460——行号平移是新增注释导致,非丢失。
- **⑥ 冻结契约(PASS)**。5a6439c2d 只动 3 文件:`scripts/notify.py`(+9/-1,仅 R4 块 dedup 判据一处)、新增 `test_notify_r4_dedup_20261001.py`、新增报告 docs。`check_signals.py` 0 改动;notify.py 邮件/飞书正文构造(send_tiered/send/正文模板)未动 → §23.10 一致性不受影响。

## 1 必查项①:后果链闭合(独立构造实验)

- **独立路径**:不对 send_tiered 打桩,对最底层渠道函数打桩(`_send_email/send_telegram/send_feishu` 返回由开关控制),让真实 send()→send_tiered()→main() R4 块完整执行;`DEDUP_FILE` 重定向 /tmp(生产隔离);`r4_staticdata_grade` 仅 stub 返回 tier。调用形态与 staticdata_backup_async.sh L457-460 完全一致(`--severe --dedup-key staticdata_backup_fail --dedup-window 3600`,不带 --tier/--alert-issue)。
- 脚本:`/tmp/rev123c/rev_r4_indep.py`,输出:
```
[PASS] A.全失败->不写dedup  |  tiered=1 ch_call=3 key_present=False
[PASS] A2.全失败后下次必重试  |  tiered=1 ch_call=3(>0=真重试非suppress)
[PASS] B.任一渠道成功->写dedup  |  tiered=1 key_present=True
[PASS] B2.窗口内二次调用suppress  |  tiered=0 ch_call=0(0=suppress不轰炸)
[PASS] C.info级->不占窗  |  tiered=1 ch_call=0(info不调渠道) key_present=False
[PASS] D.药方字面 any() 在 info 形态误判成立  |  any(info返回.values())=True
```
- 结论:审查后果链(全失败→占窗→6h 静默)被真闭合;发送成功时去重照常生效(不轰炸),正反双向都验过。

## 2 必查项②:药方偏离独立判定

- `send_tiered` 返回结构(L1988-2019 实读):
  - critical 形态(L2016-2019):`res = send(...)` + `return {"tier": tier, **res}` → `{tier, email, telegram, feishu}` 4 键;
  - info 形态(L2010-2012):`{tier, email:False, telegram:False, feishu:False, info_logged:True}` 5 键;
  - warning 形态(L2013-2015):`{tier, email:False, telegram:False, feishu:False, deferred:True}` 5 键。
- `send()`(L947-1002)返回 `{"email": email_ok, "telegram": tg_ok, "feishu": fs_ok}` 恰三渠道,无 info_logged 类键——这是通用路径 L1324/L1895 用 `any(values())` 安全的原因。
- `info_logged` 在「渠道全失败」时为 True:info 形态渠道恒 False(不调 send()),info_logged 恒 True → 药方字面 `any(values())` 在 info 级恒判成功 → info 占 severe 窗,违背审查建议本身。修复按渠道白名单过滤后,info 三渠道全 False → `_r4_sent` 空 → 不占窗,同时达成审查「主选+可选」两项。
- 白名单 `("email","telegram","feishu")` = send() 返回的全部渠道键 → 无漏渠道(不轰炸);tier/info_logged/deferred 全部非白名单 → 无多键(不静默)。**与通用路径 `ok = [ch for ch, v in results.items() if v]` 对 send() 返回的语义一致。**

## 3 必查项③:举一反三独立核

- 4 处 `update_dedup(` 实读:L747 `if ok and not dry_run`(ok=_send_email 结果)✓;L1324 `if not dry_run and any(results.values())`(send() 返回三渠道)✓;L2157 `if args.dedup_key and not args.dry_run and ok`(通用路径 P1-1)✓;L2133(R4 块,本次修复为 `and _r4_sent`)——修复前是唯一无条件点,已修。
- `defer_warning`(L1635-1747)「不改」理由逐条核实:
  - R4 块只走 critical/info,不触 warning(tier 判断 L2115-2123)✓;
  - append 失败路径 L1676-1680/L1728-1731 均 print 错误行(非静默)✓;
  - warning 聚合有 flush_warning_batch 兜底(sent 判据 L1894-1898)+ 锁序 fail-open ✓;
  - 改返回结构属需求外改动。理由成立。
- 自扫追加:`send_tiered` 调用点仅 3 处(L2072 显式 --tier 路由不消费返回值只 print;L2116/2121=R4 块已修)→ 无其他调用方对 send_tiered 返回做 `any(values())` 误判。`write_alert` 无条件写 latest.md 语义=记录事件,与发送成功无关,防静默方向正确。`_mirror_severe`/`clear_warning_dedup_for_recovery` best-effort 不影响发送。无同类「静默吞真故障」落盘点。

## 4 必查项④:强制回归 + 假绿排除

- `test_alert_denoise_20261001.py`:35 个 `check(` 断言实跑 0 FAIL(脚本尾部无 FAIL 即 sys.exit(0));实施报告称「34 项」,实际 count 35,口径差异不影响判定。
- `test_notify_r4_dedup_20261001.py`:6 场景(正例 all_ok/续跑 suppress/反例 all_fail 不更新/反例续跑重试/info 不占窗/tg_only 占窗)ALL PASS。
- **假绿排除(上一轮同款手法)**:把 /tmp 副本 notify.py R4 块回退为旧 `if args.dedup_key and not args.dry_run: update_dedup(...)`,再跑:
  - 独立实验:FAIL(A 全失败 key_present=True、A2 下次被 suppress、C info 占窗——旧 bug 三症状完整复现);
  - 实施测试:FAIL(场景 3/4/5)。恢复后两套均 ALL PASS。→ 测试对旧 bug 敏感,非假绿。

## 5 必查项⑤:force-with-lease no-loss

```
patch-id(逐对 SAME):
  6ff3c0bad  == ff074d1a9  (7380ac8e818a5fb7b030f538b1c60f3b8f0c569b)  feat 重放
  c3256126d  == ca794a44e  (7af211840c3019e7f700500b3f91f7c0871a4c34)  fix 重放
  212e2a12b  == 4ec390ad0  (0ed4e019c5cedafe931739c915a063e95f5e4cad)  docs 重放
```
patch-id 一致 = 同一改动逐字重放,无内容回退/丢失。上一轮 review 引用的行号/代码全部在位(R4 块行号因本次新增 8 行注释从 L2106-2132 下移至 L2106-2136,属平移非丢失)。

## 6 必查项⑥:冻结契约

- `git diff 4ec390ad0 5a6439c2d` 仅 3 文件:notify.py(+9/-1 只 R4 块 dedup 判据,见 §0 diff 摘录)/ 新增测试 / 新增报告。check_signals.py 0 改动。
- notify.py 邮件/飞书正文构造(send_tiered/send/正文模板/L947-1028 渠道函数)逐位未变 → §23.10 飞书与邮件同源一致性不受影响。

## 回归/影响面

- 本次修复改动面:notify.py R4 块单点 + 新增测试/报告;alert_denoise_rules.py / schedule_monitor.sh 0 改动(上轮 R5/R1 修复未被破坏,35 check 回归覆盖 R1 恢复循环/R5 跨轮场景全 PASS)。
- info 级不占窗的行为变化:info 状态每轮备份调用都会走一遍 send_tiered(info)→ log_info 记 dashboard。属设计内(info 只记 dashboard 不推送,可追溯),且是审查「可选」建议想要的结果;不引入用户可见轰炸。
- send_tiered 返回值在 L2072 分支只 print 不消费,无连带影响。

## 复现段

- 测试(实施侧):`scripts/tests/test_alert_denoise_20261001.py`(35 check PASS)、`scripts/tests/test_notify_r4_dedup_20261001.py`(6 场景 PASS)。
- 本审查独立实测:`/tmp/rev123c/rev_r4_indep.py`(真实 send/send_tiered 执行 + 底层渠道打桩,6 项 PASS)+ 回退对照(旧逻辑三症状复现 FAIL,恢复后 PASS)。
- 关键代码位:notify.py L2106-2136(R4 块)/ L2130-2133(修复后过滤判据)/ L2157-2158(通用路径 and ok)/ L1988-2019(send_tiered 返回结构)/ L947-1002(send() 三渠道返回);staticdata_backup_async.sh L456-460(调用方,不带 --alert-issue)。
- 分支:`worktree-agent-af1e103df45f2939c`,远端 HEAD 5a6439c2d。
