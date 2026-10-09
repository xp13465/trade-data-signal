# #241 同族 B 波「先落签、后 fire-and-forget 通知」独立审查报告

> 审查者: role-reviewer(fresh context 独立复审) | 日期: 2026-10-09
> 被审: feat 分支 `worktree-agent-ac4081870ac044266` @ `47fbc42d4`; 基线 origin/main = `4325a27d5`
> 方式: 只读静态复核 + static-only 纯函数抽取实测(§18 L50) + 变异树红绿复现。**未运行任何告警/邮件/飞书链主体(零外发); 未 commit / 未 push; 未写 R2**
> 残留后台任务: 无(全部命令前台带超时返回, 本次审查无转后台事件)

## 0. 总结论(7 审查点)

| # | 审查点 | 判定 | 一句话 |
|---|---|---|---|
| ① | shell 快照+diff+回滚正确性 | **PASS** | 只回滚本轮新变 active 的 key, 边界逐条正确; 跨进程共享文件竞态=既有, 非本波引入 |
| ② | 重复告警/轰炸 | **PASS** | 全挂期重试均发不出; 恢复后首轮落签即抑制 = 用户恰收一次; 5 站点逐一核过 |
| ③ | notify_sent fail-safe / 未被改 | **PASS** | 文件未改; 空/未知/全失败→False; 5 站点调用形态与判据逐一对齐 |
| ④ | 6 类「不动+上报」理由 | **成立**(1 处措辞修正) | upload_r2 等理由复核有效; monitor_72h 恢复 notify 理由①不适用(其无 dedup-key) |
| ⑤ | 零外发自证 + 红绿复现 | **PASS**(计数差异标注) | trap 真武装且 E2E 收尾 hits==[]; 替身不 spawn; 红绿方向复现, 精确数 14/2 ≠ 报告 9/7 |
| ⑥ | 与 F1 分支 monitor_72h.sh 冲突 | **可自动 merge** | merge-tree EXIT=0; hunk 区间不重叠; 语义无打架 |
| ⑦ | §23.3 扫面可信度 | **发现 1 处漏网** | `retry_failed_metrics.py` 未列入(同族次型, 非永久); 抽查其余站点均无真型 |

**内审结论: PASS, 具备 merge 资格**(§23.14: 内审 PASS + §0 上线验证)。附 §2 三项发现/上报, 其中 F1 建议拍板。

## 1. 逐项证据

### ① 快照+diff+回滚正确性 —— PASS

实现逐行核对(`scripts/schedule_monitor.sh`):
- 快照 L330-334: `alert_state = load_alert_state()` + `_STATE_PRE = {k: (dict(v) if isinstance(v, dict) else v) ...}`(浅拷贝到值一级, 覆盖 status/first_seen/consecutive_count 等标量字段)
- `_diff_transition` L298-312: 只选 `isinstance(v, dict) and v.get("status")==status` 且 pre 中该 key 非同 status 的 ⇒ 既有 active(持续抑制态)/pending 计数/无 status 的 `r2_pipeline_congestion` 一律不动
- `_rollback_transition` L314-327: pre 中存在 → 还原(pre 值也拷一层); 不存在(本轮新 key)→ pop
- 调用 L2806-2831: `_r_main = subprocess.run([...notify.py...], check=False, capture_output=True)`; L2818 `_main_out = stdout + stderr`; L2827-2831 `if not notify_sent(_main_out): _rollback_transition(...); save_alert_state(...); print [warn] rc+回滚数`
- `scripts/monitor_72h.sh` 同构: helpers L178-206, 快照 L201-203, 主 notify L867-890(回滚 L887-890)

边界逐条:
- **空 key 集**: diff 返回 [] → save 无实质变化(测试 test_01 覆盖)✓
- **首个 key**: 走 pop 分支, 正确 ✓
- **key 前缀隔离/共享文件**: alert_state.json 与 monitor_72h 共享, 以 `72h_` 前缀隔离; schedule_monitor 内存态根本不持有 72h_ key ⇒ 回滚 diff 不可能回滚 72h 侧签 ✓; `r2_pipeline_congestion`(无 status)永不被回滚 ✓
- **重叠轮/并发**: 同进程无重叠(脚本串行); 跨进程(72h vs schedule_monitor)风险 = 整文件 load-modify-save 的**既有**写覆盖竞态, 与本波无关; 本波仅在失败分支**多一次 save**(schedule_monitor L2829 / monitor_72h L889), 竞态窗口略增、性质不变(低分注记 F3)
- **「通道全挂 ⇒ 不落签 ⇒ 下轮重试」语义成立**: 下轮 `_STATE_PRE` 里该 key 不在(或非 active) ⇒ 条件持续则重新进 alerts 复发, diff 再回滚, 直到送达 ✓
- **崩溃窗**: 轮内检查点先持久化(schedule_monitor L1910/2079/2351/2438/2579/2717/2796; monitor_72h L854), 若进程在「检查点后、回滚前」崩溃 ⇒ 磁盘短暂保留未送达 active。实现者报告 §6 已诚实登记, 复核成立(极端低概率)✓
- 判据输入合并 stdout+stderr, 与 notify_sent 要求一致 ✓
- 主 notify **不带 `--dedup-key`** ⇒ 不可能命中 notify.py L2182-2184 的 dedup 早退(其输出只有 suppress 行, 会被误判), 走通用汇总行(notify.py L2359 已发出 / L2362 全失败), 判据形态完整对齐 ✓ (微注: notify_sent.py docstring 引用行号 2368/2371 与现行 2359/2362 漂移 9 行, 纯注释漂移, 不影响字符串判据)

### ② 不轰炸 —— PASS(逐站点)

| 站点 | 全挂期行为 | 恢复后 | 判定 |
|---|---|---|---|
| B1 schedule_monitor(15min/轮) | 每轮 1 次 notify 尝试(聚合单封, 非逐条)+ 回滚, 发不出=用户无感 | 首轮送达→落签→下轮抑制 | 恰 1 封 ✓ |
| B2 monitor_72h(30min/轮) | 同上 | 同上 | ✓ |
| B3 dia(30min/轮) | 不落签→每轮重试(单封) | 首轮落签→同日去重 | ✓ |
| B4 brief(每日 20:40) | 无自动重试, 仅解「人工重跑被抑制」 | 重跑成功→占窗 | ✓ |
| B5 check_signals fade | fade 栏随 intraday 主邮件重试(主邮件本身有 ok_channels 语义, 改前即对) | 主邮件 Ok→落签 | ✓ |

反向残余(实现者已诚实标注): notify_sent 因输出格式漂移误判(成功→False)⇒ 重复投递; 概率低 + stderr 打印尾部 200 字可排障。复核: 方向正确, 标注成立 ✓

### ③ notify_sent fail-safe / 未改动 —— PASS

- `git diff 4325a27d5..47fbc42d4 -- scripts/notify_sent.py` = **空**(未改)✓
- fail-safe 逐分支(`scripts/notify_sent.py` L56-76): 空/未知→False; 命中「全部渠道未发出」→False(优先); 「已发出」→True; 「路由完成：…True…」→True; 未知→False(保守, 下轮重试)✓
- 5 站点调用形态对齐: B1/B2 主 notify 无 dedup-key(走通用汇总行); B3 `send_alert`(detect_intraday_anomaly.py L287-330)无 dedup-key; B4/B5 为 in-process `notify.send` 的 results dict 判据(不经文本解析, B4 `_channels_sent` L3814+4057-4061; B5 ok_channels L2090-2097); 均无「被 suppress 却被判未送达」路径 ✓
- notify.py 冻结面未触碰; 改动文件清单复核 = 7 文件(5 修 + 1 测试 + 1 报告), `--stat` 835+/18- ✓

### ④ 6 类「不动+上报」—— 成立(1 处措辞修正)

- **upload_r2.py(6 处, 逐点复核)**: 模式确为 `if not check_dedup(_k, W): notify.send(...); notify.update_dedup(_k)`(L1368-1376 / L1761-1770 / L2150-2159 / L3669-3684 / L3699-3714 / L3727-3739; W=1800/21600/86400), send 失败照占窗 ⇒ **真同族**(窗内抑制, 属「延迟型」, 非 B1/B2 的永久型)。报告把它归「冻结面 + 需拍板」而非「安全」, 分类准确; 「不本波动」成立, 建议并入上报包由用户拍板是否独立任务
- **两个 recovery notify**: 成立, 但**措辞修正**——理由①(带 dedup-key 时 notify.py 静默 suppress, 朴素换 notify_sent 会误判)只适用 schedule_monitor 侧(L2868-2876 带 `--dedup-key schedule_monitor_recovery --dedup-window 21600`; notify.py L2182-2184 抑制早退实测确认); **monitor_72h 侧恢复通知(L921-930)无 dedup-key**, 理由①不适用于它, 其「不动」依据应落理由②(回滚 recovered→active 致面板振荡/无自然重试点需新机制)与改造量。结论不变
- 其余 4 类复核成立: brief_push(部分成功语义)/ self_heal(info 级 dashboard)/ 72h 到期一次性通知(发完即停, 无持续重试语义)/ r7r4 计数(告警本体走 dedup-key=成功才落窗; 计数推进≠告警丢失)✓

### ⑤ 零外发自证 + 红绿 —— PASS(计数差异见下)

- trap 真武装: test_00(测试文件 L127-132)trap 内真触 `urlopen` ⇒ 命中 raise 且 `trap.hits == ["urllib.request.urlopen"]` ✓
- 替身不 spawn: `_fake_run`(L74-80)只返回 `CompletedProcess`, 不调真 run; `_run_dia_main`(L246-260)monkeypatch `dia.subprocess` / `dia.DEDUP_FILE` / `load_snapshot` / `_conn`; test_06 以命名空间桩替换 `dia.subprocess` ✓
- 收尾断言: test_07 L290 / test_08 L308 `trap.hits == []`。**措辞修正**: 报告 §5.1「各用例收尾断言」实为 2 个端到端用例; 其余 14 个为静态锁/纯函数/替身单测, 本无出网面 —— 实质不弱
- 防假绿: `_MIN_ASSERTIONS = 36`(L66) + test_99(L415-417)断言数下限 ✓
- 绿: 修复版实测复现 `16 passed in 0.13s` ✓
- 红: 我的变异树(worktree 全量 scripts/+app/ 复制, 5 目标文件换 `git show 4325a27d5:` 旧版, 保留新测试)⇒ **14 failed / 2 passed in 0.28s**; 报告称 **9 failed / 7 passed —— 精确计数不一致**(可能因变异树构造不同; 方向与判别力复现且更强)。2 个通过项 = test_00(trap 自证, 与代码版本无关)+ test_08(正控, 新旧语义下「成功⇒可观测落签相同」), 属预期正控, 非假绿

### ⑥ 与 F1 分支(3838f91fa)冲突 —— 可自动 merge, 无冲突

- `git merge-base 47fbc42d4 3838f91fa` = `4325a27d5`; `git merge-tree --write-tree 47fbc42d4 3838f91fa` **EXIT=0**, tree `157a6fcf33c0483566ab88fd6ea91e7a62497d73`, 无冲突段输出
- `monitor_72h.sh` hunk 区间不重叠: 本波 @@ -94,6 / -170,7 / -834,7 / -844,8(新行号 94+/175+/864+/874+); F1 @@ -769,7 / -779,16(新 769+/800+, ad_line 交易日口径区)
- 语义: F1 新增检查产出正常 active key, 与主 notify 聚合列表同流; 若 F1 先合, 其新 key 在全挂期同样被回滚重试 = 行为一致, 无语义打架。**结论: 自动 merge, 无冲突, 无需人工解冲突; 两分支合并先后无约束**

### ⑦ §23.3 扫面可信度 —— 发现 1 处漏网

抽查面(逐文件读 notify 调用点上下文): 壳侧 `verify_backup.sh` / `uptime_check.sh` / `s06_snapshot.sh`(dedup-key, 注释明示「发送成功才记 dedup」)/ `staticdata_backup_async.sh`(8 处: dedup-key 或纯 fire-and-forget 无落签; 心跳写 fail 不构成抑制)/ `update_all.sh`(dedup-key); Python 侧 `daily_summary_email.py`(无任何 sent 状态)/ `gen_schedule_stats.py`(仅注释)/ `codex_notify_bridge.py`(写 `.done` 信号先于通知, 但为 codex 完成 ping(开发群), 非真告警, 可忽略)。以上均无「真型」✓

**漏网 1 处**: `scripts/retry_failed_metrics.py` 未出现在报告任何清单 —— 见 F2(同族次型 + 更重的 pre-existing bug)。故「全 scripts/ + app/ 逐个读」口径**不完全成立**, 但主体清单(5 修 + 前序已修 + 安全 + 不动)复核可信。

## 2. 独立发现(上报, 非本波代码 FAIL)

**F1(B3 前端通道耦合 —— 建议拍板/解耦, 中)**
`anomaly_notified.json` 是共享件: 除 detect_intraday_anomaly 自身邮件去重外, 还是 `scripts/export_notifications.py`(`ANOMALY_NOTIFIED_PATH` L51; `_load_anomalies_today` L308-313; 汇入 notifications.json `anomalies` L383-392)的**唯一数据源** → 前端浏览器通知。B3 把落签门控在「邮件送达」后 ⇒ **邮件/飞书通道全挂期, 前端(独立通道)的异动弹窗也被一并抑制**(改前不受影响)。报告 §5.5 影响面清单只列 latest.md / alert_ack --list, 未列此展示位(§23.3 口径缺项)。建议: ①把「前端 feed 记录」与「邮件重试门控」解耦(如未送达时仍保留 pending 集合供 export 合并读); 或 ②主控/用户拍板接受, 并落 §6 残余 + 理由。
证据链: detect_intraday_anomaly.py L223-276(filter_and_record/record_notified)+ L348-357(main 门控) → export_notifications.py L308-313 → L383-392(anomalies 字段)。

**F2(`scripts/retry_failed_metrics.py` —— 非本波改动, 上报)**
① L136-145: L145 cmd 使用未定义名 `subj`(L138 定义的是 `subject`)⇒ `_notify_repeat_failure` 阈值告警路径**必 NameError**; 该行在 L146 try 之外 ⇒ 异常冒泡终止本轮(后续 metric 不重采/计数不落盘)。pre-existing(非本波 diff; `git log -S` 可溯源), 建议独立小修。
② L262-275: 先 `counts.pop(mid, None)` 清零 → fire-and-forget `_notify_repeat_failure`(仅查 rc 打印) = 同族**延迟型**(通道恢复需再累计 N 轮才重发, 非永久)。报告 §1 未列该文件 = §23.3 漏网(即 ⑦ 的发现)。

**F3(低分注记, 非阻断)**
- 跨进程 alert_state.json 整文件写竞态(既有; 本波失败分支 +1 次 save 略增窗)
- `_recurrence_suppressed`(6h 恢复冷却)本轮新 active 的 key 在全挂期会被回滚 ⇒ 仅日志噪声(下轮重现再抑制), 复核无邮件丢失/重复
- notify_sent.py docstring 行号引用漂移(2368/2371 vs 现行 2359/2362, 纯注释)

## 3. 复现记录

- 绿: `cd <worktree> && /Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/test_241_family_b_consign_20261009.py` → `16 passed in 0.13s`
- 红: 变异树 `/tmp/mutB_review`(worktree scripts/ 全量复制 + app/ + 新测试; 5 目标文件换 `git show 4325a27d5:` 旧版)同命令 → `14 failed, 2 passed in 0.28s`
- merge: `git merge-tree --write-tree 47fbc42d4 3838f91fa` → EXIT=0 / tree `157a6fcf33…`
- 禁跑遵守: 未执行任何告警链主体; 纯函数仅经测试 `_load_shell_helpers`(AST 抽取 heredoc 纯函数)在 pytest 命名空间内实测; 无 R2 写 / 无裸 pip / 无 Docker / 无 `find /` / 无 `grep -r` 出白名单

## 4. 供主控的 merge 前置

- 本报告 = 内审 **PASS**; merge 资格 = 内审 PASS + 主控 §0 上线验证(§23.14 无外审要求, 除非用户点名)
- 合并顺序: 与 F1(3838f91fa)先后无约束(双向自动 merge 已验)
- push main 后按 §8 自查 CI 结论; §0 三查照常
- F2 建议起独立小任务两连修(`subj` NameError + 清零后通知); F1 需拍板(用户可见通道取舍)后决定是否本轮补修或落残余

---

# 5. 增量复审(续跑 `192800415` vs `47fbc42d4`, 2026-10-09 18:xx)

> 范围: 只审增量。`git diff --stat 47fbc42d4 192800415` = 3 文件(`scripts/retry_failed_metrics.py` +39、新测试 201 行、实施报告 84 行);已 PASS 的主体不重审。
> 残留后台任务: 无。全部命令前台带超时;未跑 retry_failed_metrics.py 主体/任何告警链;测试文件无外发(替身+trap)直接跑。

| # | 审查点 | 判定 |
|---|---|---|
| ① | L300 送达才 pop / 未送达保留计数 | **PASS**(每轮重试成立、无泄漏、无阈值漂移) |
| ② | `subj`→`subject` 修复正确性 | **PASS**(正确变量名;原意图恢复;pre-existing 溯源成立) |
| ③ | 11 用例判别力 + 红绿复现 | **PASS**(9/2 精确复现;另加 iso 变异隔离证明) |
| ④ | `_notify_count_file_write_fail` 安全 | **PASS**(独立核 notify.py 契约) |
| ⑤ | `detect_intraday_anomaly.py` 行为未动 | **PASS**(空 diff) |
| ⑥ | 家族回归 | **PASS**(0 failed;计数差异见下) |

## 5.1 ① L296-303 新序 —— PASS

`main()` L300-303(新稿): `if _notify_repeat_failure(mid, n, today, msg): counts.pop(mid, None)  # 送达后清零暂歇` / `else: counts[mid] = n  # 未送达: 保留计数, 下轮重试`。
- **「通道全挂 ⇒ 每轮重试」成立**: 未送达时保留 `counts[mid]=n`(n=prev+1);下轮 `n+1 ≥ 3` 恒真 ⇒ 每轮都再试(实测: 变异/绿色两侧 test_06 calls==2)✓
- **无计数泄漏(永久保留)**: 送达→pop(L301);指标成功→pop(L285);配置类失败→pop(L307, 既有);未送达保留=「真实连续失败数」,通道恢复首轮送达即 pop,恢复后按 3 轮节奏重告警(与旧版一致),不轰炸 ✓
- **无阈值语义漂移**: 达标判定用同一个 `n`(prev+1)且保留写回同一值;送达分支行为与旧版逐位一致(仅注释更新)✓
- **fail-safe 链**: 异常→False→保留(L176-178);rc!=0 仍以输出为准返回 sent(defensive,notify.py rc 恒 0);`out = stdout+stderr`(L161-163)与 notify_sent 契约一致 ✓
- 边界: 送达后重累计路径不变;长故障期 n 递增仅使邮件文案「连续 N 轮」更真实 ✓

## 5.2 ② `subject` 修复 —— PASS

- L152 `subject = f"[告警][重采失败] {mid} 连续 {count} 轮重采失败"`;L159 `subject, body, "--from-prefix", "[告警]"]`(全文件 `\bsubj\b` grep 0 匹配)✓
- 原意图恢复: subject 文案与同类告警模板一致;body 引用 count/阈值;test_01 断言 cmd 含「连续 3 轮重采失败」+ mid ✓
- pre-existing 溯源(§23.7⑤ 证明链): `0a42e6bac`(2026-09-30 引入本函数)**同 commit 即写 `subj`** = 从出生起必 NameError ⇒ 修前阈值告警路径**完全不可达**,修复后路径真正可跑 ✓

## 5.3 ③ 测试判别力 —— PASS

- 绿: 新 11 + 旧 16 = **27 passed in 0.52s**
- 红(真旧版变异, /tmp/mutB_review md5==`47fbc42d4:` 版): **9 failed / 2 passed 精确复现**(2 通过 = test_00 trap 自证(版本无关)+ test_08 未达阈值路径两版相同);test_01/02/03/04 失败消息为 `NameError: name 'subj'`(旧版连 cmd 都组不出)
- **加做 iso 变异**(旧版仅 `subj`→`subject`、保留旧序,隔离 NameError 干扰): **8 failed / 3 passed**,test_05/06 失败消息正是目标断言: 「未送达必须保留计数(=3), got None(旧代码会 pop 掉)」/「通道全挂应每轮重试(=2 次), got 1」⇒ **排序修复的判别力被独立证明**,非 NameError 附带;3 通过 = test_00/test_07(正控,新旧语义成功路径相同,预期不可判别)/test_08 ✓
- 零外发: `_shim_run` 以 SimpleNamespace 替换 rfm 模块级 `subprocess`(不 spawn);trap 包裹用例收尾 `trap.hits == []` ✓

## 5.4 ④ `_notify_count_file_write_fail`(L93-140) 安全 —— PASS(独立核实)

- 无「先落签」: 该函数**不写任何本地状态**;去重完全委托 notify.py 的 `--tier warning --dedup-key retry_fm_count_file_write_fail --dedup-window 21600`
- notify.py 契约独立复核: L2183-2186 suppress 早退(文案「dedup 窗口内 suppress」与本函数判定串一致);L2192-2194 `update_dedup` 仅 `_tier_send_ok`(真入队/真抑制)才提交;append_failed 不提交 ⇒ 下轮可重试 ✓
- 调用点 L314-318: `_save_counts` 失败 → fail-loud `return 1` 兜底,不依赖本 notify 结果 ✓
- 同文件全量 notify 站点核查: 仅 2 处(L107 本处 / L145 已修),无第三处遗漏 ✓

## 5.5 ⑤ F1 未擅改 —— PASS

`git diff 47fbc42d4 192800415 -- scripts/detect_intraday_anomaly.py scripts/check_signals.py scripts/gen_daily_brief.py scripts/schedule_monitor.sh scripts/monitor_72h.sh scripts/notify_sent.py` = **空**;diff stat 仅 3 文件 ⇒ F1(待拍板项)只登记未改代码,符合指令 ✓

## 5.6 ⑥ 回归与报告诚实版 —— PASS(1 处计数口径注记)

- 两份 B 波测试 27 passed;notify/alert 家族 15 套实测 **172 passed / 0 failed**(报告称「13 套 = 144 passed」——套件集定义不同,实质一致: 0 failed)
- 实施报告增量复核: §0/§1 诚实版(漏网登记为 B6 + 「以复审为闭合点」)与 §5.6 F1/F2/F3 登记**与本次审查结论一致**;F1 明确「主控另呈用户拍板、本轮未擅改」§23.11 ✓
- 低分注记: 无新增(报告「各用例收尾 hits==[]」措辞与原报告同款,已在 §1.5 标注;套件计数差异属口径注释)

**增量结论: PASS;merge 资格维持;F1 仍待用户拍板(本轮无代码变化)。**
