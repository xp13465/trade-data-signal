# #241 同族 rc→notify_sent 统一 —— 独立复审报告(2026-10-09)

> 审查对象: feat `worktree-agent-af679d5bb8c12336c` / commit `4c9b41efb`(base `8b06e0960`)
> 审查者: reviewer agent(独立上下文;全程只读,无 git 写,**零外发**)
> 批复: **7 PASS / 1 FAIL**。代码修法本身正确、干净、可上线;FAIL 在「穷举完整性结论」——
> 文档 §结论「无第 4 处『同后果(落签/抑制/丢告警)』遗漏」**不成立**(至少 4 处反例,
> 其中 `scripts/schedule_monitor.sh` 后果**重于**已修 3 处)。建议主控上报用户决定是否补修(§23.7)。

## 0. 审查方法(独立复现,不采信实施方自述)

- 全部结论出自本审查者直接读代码(工作区 + `git show <rev>:<file>` 反查分支内容)+ 独立跑测试,未采信文档/测试自述。
- 独立环境: `/tmp/mut241`(base 版三脚本)与 `/tmp/fix241`(commit 版三脚本 + 测试),额外挂
  `sitecustomize.py` 硬出口陷阱(`urllib.request.urlopen`/`smtplib.SMTP`/`SMTP_SSL` 触达即 raise,
  **自证生效**: 故意探测一次确会 raise)。
- 零外发声明: 测试路径 `subprocess.run` 全部被 mock(进程内假 CompletedProcess,**无 notify.py 子进程被 spawn**);
  我方硬陷阱在两轮测试全程 **0 命中**。未跑任何生产脚本或会发通知的脚本。
- 无后台任务: 全程无 `moved to the background (ID:` 事件(无残留后台任务需上报)。

## 1. 逐项结论

| # | 检查项 | 结论 | 一句话证据 |
|---|---|---|---|
| 1 | 穷举是否真穷举 | ❌ FAIL | rc 轴 3+3 分类属实;但「同后果」轴 ≥4 处未列/错分(§2) |
| 2 | 判据没被弱化 | ✅ PASS | `notify_sent.py` blob 与 base 逐字节同(`git diff` 空),fail-safe 顺序原样 |
| 3 | 抑制链真解开 | ✅ PASS | 全失败 ⇒ sent=False ⇒ 不落 fired ⇒ 下轮重试(code path 推演 + 测试双证) |
| 4 | 零外发 | ✅ PASS | test_00 自证陷阱已武装 + 我方硬陷阱 0 命中 |
| 5 | red-before-green 判别力 | ✅ PASS | 独立复现: 变异版 **8 failed/3 passed**,修复版 **11 passed**,关联套件 55 passed |
| 6 | 改动面干净 | ✅ PASS | 恰 5 文件;notify.py / notify_sent.py / check_data_integrity.py / update_all.sh / upload_r2.py 未触碰 |
| 7 | §15 回归 + 告警轰炸风险 | ✅ PASS(可接受) | 正向路径零回归;重试频率=各站点运行频率,无轰炸 |
| 8 | §23.3 rc 轴举一反三 | ✅ PASS | 全仓「notify ∧ returncode」交叉扫,无第 4 处 rc 判 sent(§3.7) |

## 2. FAIL 详证(item 1:「同后果」穷举不完整)

### 文档结论句原文(引,`git show 4c9b41efb:docs/ops/241-family-rc-sent-sweep-20261009.md`)

> §1 标题: 「穷举清单(核心验收点: 全 scripts/ + app/ 交叉扫, 确认**无第 4 处同后果站点**)」
> §结论: 「…**无第 4 处「同后果(落签/抑制/丢告警)」遗漏。** 另发现 adjacent 病灶 1 处(Pattern D `upload_r2`)已列 §4。」

扫描口径自述为「对『**含 notify 且含 returncode**』的文件逐个人读」——该口径**结构性漏掉**
「不出现 rc 字样、但照样落签后 fire-and-forget」的站点,而结论句却按「同后果」口径作了强断言。

### A1. `scripts/schedule_monitor.sh` —— 最严重,文档**完全未列**(连 Pattern E 名单都没有它)

- 事实(行号为当前 main 版,与 base 同,非本 commit 改动面):
  - 检测段当时即写签: 如 L706-708 / L1417-1419 / L1453-1454 `alert_state[dedup_key] = {status: "active", last_alerted: NOW…}`;
    后续轮命中 `else: # 已 active = 抑制不重发,只 log`(如 L1460-1464、L421、L729)。
  - 收尾聚合(L2755-2757): `alerts.append(_r5_summary)` 后紧接 **`save_alert_state(alert_state)` 先落盘**;
    随后 L2769-2783 才 `subprocess.run([... notify.py ...], check=False)` —— **返回值完全丢弃**(fire-and-forget,连 rc 都不看)。
- 后果推演: 某轮通道全挂/notify 被杀 ⇒ 当晚「计划任务异常」邮件+飞书丢失,但 alert_state 已落签
  (`status=active, last_alerted=本轮`) ⇒ 条件持续期间**每 15min 轮命抑制、永不重发** ——
  与本次已修 sensenova 的「告警永不送达、永不重试」**同款后果**,且覆盖面更大
  (它是 15min 全局巡检中枢,承载漏跑/exit失败/数据错/停摆等全部计划任务告警类)。
- 缓解(诚实标注): `--severe --alert-issue` 的 latest.md 镜像不依赖渠道成功(修前已核实),故「丢」的是
  主动通道(邮件/飞书),最新告警页仍可见 —— 不改变「已 active 抑制 ⇒ 主动通道永不重试」的定性。
- 归属判定: 文档自身的 C 类定义是「不作判据、**不落签**」;schedule_monitor.sh 是**落签 + fire-and-forget**,
  正落在文档结论句「同后果(落签/抑制/丢告警)」的定义域内,却被「含 returncode」扫描口径漏掉。

### A2. `scripts/detect_intraday_anomaly.py` —— 列了,但归错类(与 C 类定义自相矛盾)

- 事实: `filter_and_record`(L232-246)先 `atomic_write_json(DEDUP_FILE=anomaly_notified.json)` 落当日去重签;
  之后 `send_alert`(L273-300)用 `check=False, capture_output=True` **丢弃返回值**,无异常即打印「已发」。
- 后果: 全渠道失败 ⇒ 当日该异动提示(含 severe 项)丢失(同日同类去重已占,**当天不再重发**)。
- 文档把本文件列在 Pattern C 并写「fire-and-forget, 完全忽略返回值(连 rc 都不看)。不属 rc 判定, 且**均带 dedup-key**;
  不改」——但 C 类定义含「**不落签**」,本文件恰恰是**先落签后发**,分类与自身定义冲突;
  「均带 dedup-key」对 notify 命令也不成立(其 notify cmd 无 `--dedup-key`,去重来自本地文件)。

### A3. `scripts/gen_daily_brief.py` —— 与 upload_r2 同病灶,文档未列

- 事实: L4037-4045 `results = notify.send(...)` 后 **`if not dry_run: notify.update_dedup(dedup_key)` 无条件**
  (不判 `results`);前置 `check_dedup(dedup_key, 86400)` 命中即 `return {"dedup": True}`。
- 后果: 全渠道失败 ⇒ 当日「每日速递」丢失 **且** update_dedup 已占窗 ⇒ 当日运维重跑被
  「通知已发过(date=…),同日去重跳过」抑制(该 key 带日期,次日才恢复)。
- 文档在 Pattern D 只把 `upload_r2.py` 认作「adjacent 病灶(sent 判定缺失 ⇒ 占窗)」,gen_daily_brief 是
  **同款病灶**却被一句「进程内调 notify, 无 rc 判 sent, 不改」带过,未计入 adjacent 清单。

### A4. `scripts/check_signals.py` fade 子去重 —— 次级(可辩)

- `filter_fade_alerts_intraday`(L238-271)检测当时即写 `fade_notified.json`;主邮件发送在 L2033-2055
  **正确**按 `ok_channels` 才落 `signal_notified`(本批无涉,判据正确)。全失败时重试邮件会重发主信号,
  但 fade 条目已被子去重占 ⇒ 重试邮件缺 fade 警示栏。属提示性栏目,列为次级同后果。

### A5. `scripts/upload_r2.py` 计数错误:文档「1 处(L1366 附近)」,实测 **≥6 处**

`check_dedup → notify.send → 无条件 update_dedup` 实例: L1368-1376 / L1761-1770 / L2150-2159 /
L3669-3684 / L3699-3714 / L3727-3739。注: 本项只影响「adjacent 清单完整性」,不影响「不改」的处置选择本身
(动 upload_r2 确需独立决策)。

### A6. 已核实属实的部分(为公平起见)

- Pattern A 三处已修 = 真(check_data_gap / sensenova / overfit,逐个 diff 核实)。
- Pattern B pivot 论证**成立**: notify.py 通用路径 dedup 抑制分支(L2348-2349,blob 与 base 同)
  `return 0` 且**零输出** ⇒ 朴素换 notify_sent 会因空输出判 False ⇒ 假升级;B 三处(heartbeat / nextday_gap /
  nextday_plan)确为 rc→升级门。**不动 + 上报** 的处置正确。
- Pattern D `signal_kelly_snapshot.py: ok = res and any(res.values())` 正解属实。
- Pattern E「shell 里 rc=$RC 是触发检查自己的 rc,不是 notify rc」字面属实(backup_db.sh:119 等逐处核过);
  缺的只是「不据 rc ≠ 不落签」这半句 —— 见 A1。

## 3. 各 PASS 项证据

### 3.2 判据未弱化
`git diff 8b06e0960 4c9b41efb -- scripts/notify_sent.py` 输出为空;blob `02e6f574…` 与 base 逐字节同。
fail-safe 顺序(「全部渠道未发出」先判 ⇒ False;「已发出」⇒ True;未知 ⇒ False)一字未改。

### 3.3 抑制链真解开(sensenova)
- 修前(base,`git show` 实读): `_notify` = `if r.returncode != 0: return False; return True`。
  notify.py `main()` 全出口恒 rc=0 ⇒ 全渠道失败也 `ok=True` ⇒ `_save_state({"fired": True})` ⇒ 后续轮
  `if fired: 抑制 return 0`(L235-238)= 永久静默,与事故面完全一致。
- 修后: 判据换 `notify_sent(out)`;main 的 `if ok and not dry_run: _save_state(fired)`(+ `elif not ok` 重试文案)
  **base 已有、本 diff 无此 hunk** —— 抑制链解开完全由判据修正承担。
- 推演: 通道全挂 ⇒ 每 5min 轮 `ok=False` ⇒ 不落 fired ⇒ 下轮重试;通道恢复后首轮送达 ⇒ fired=True ⇒
  抑制重复 ⇒ 用户恰好收到一次(期望形态)。dry-run 不落盘行为不变(测试 test_01/02/03 覆盖)。

### 3.4 零外发(§18 L48)
- 测试用例经 `_fake_run(output, rc)` 直接造 CompletedProcess,**进程内返回** ⇒ 无 notify.py 子进程 spawn。
- `ZeroOutboundTrap`(底层 urlopen/SMTP/SMTP_SSL 三出口)由 test_00 自证已武装(hits 至少 1);
  我方在 `/tmp/fix241`、`/tmp/mut241` 另挂**进程级** `sitecustomize.py` 硬陷阱(先自证会 raise),
  两轮测试(mutant 8F/3P + fixed 11P + 关联 55P)**全程 0 命中**。
- stderr 污染面(#239 教训): 三处把 stdout+stderr 合并喂 `notify_sent`;判据对「全部渠道未发出」**先判且优先**
  (出现即 False),成功摘要「已发出」走 stdout ⇒ 合并 stderr 不会把「全失败」误翻成 True;
  反向(成功被误判 False)只在 notify.py 完全无输出时发生 = fail-safe 预期方向。
  残余观察项: 若未来某 stderr 文案含「已发出」且 stdout 无摘要,会把「未知」翻成 True(低概率,记录备查)。

### 3.5 red-before-green(变异自证,独立复现)
- 变异版(base 判据,`/tmp/mut241`): 测试 **8 failed, 3 passed** —— 负控 test_02/test_04 失败(全失败竟落签)
  + 静态锁 test_01/06/07/99 失败,判别力真实(非恒绿)。
- 修复版(`/tmp/fix241`): **11 passed**;关联既有套件(notify 家族相关 5 套)**55 passed**。数字与实施方报告一致。
- test_99 断言计数下限 34(§18 L49 防假绿)在位。

### 3.6 改动面干净
`git diff --name-status 8b06e0960 4c9b41efb` = 恰 5 项: A docs/…doc + A test + M 三脚本。
逐文件 hunk 枚举 = 每个脚本仅「import + 判据块」(14/10/20 增行),无夹带;
`notify.py` / `notify_sent.py` / `check_data_integrity.py` / `update_all.sh` / `upload_r2.py` diff 全空。
base 之上仅 1 个 commit。

### 3.7 §23.3 rc 轴举一反三(独立交叉扫)
全仓「含 notify ∧ 含 returncode」文件逐个核(含 app/):
check_monitor_heartbeat(L102, = Pattern B)、check_data_gap_alerts(L1467, 本批已修)、
check_s06_freshness(L146, 上游 #241 已修)、nextday_gap_check(L380-382, B)、nextday_plan_generator(L1247-1253, B)、
retry_failed_metrics(L115/149, 仅留痕 C)、signal_kelly_backtest(L343, C)、app/collector/runner.py(L69, C)、
check_failed_units(L248, 上游 #240 已修)。**无第 4 处 rc 判 sent 站点** ⇒ rc 轴穷举属实
(「同后果」轴缺口记 §2)。

## 4. §15 回归 + 告警轰炸风险评估(item 7, 判定: 可接受)

- 正向路径零回归: 送达成功 ⇒ notify.py 打印摘要「已发出」⇒ `notify_sent=True` = 修前 `rc==0→True`;差异只在
  ①全失败(True→False,正是修复目标)②无输出/被 dedup 抑制(overfit 的观测标志 True→False —— `a["sent"]`
  全仓无读取方,仅写入 L1937/1942,前端 JS 也不读 ⇒ 无行为面;该欠报已在文档 §5 自认)。
- 重试面推演(三处): 每轮最多 1 封,重试频率 = 各站点运行频率(sensenova 5min / overfit 21:40 每日 /
  check_data_gap 22:35 每日);通道全挂时本就发不出,通道恢复后**首轮送达即止**(既有 state/fired/dedup
  在成功后才收口)⇒ 用户见「恰好一封」,不构成轰炸。远端残余 = notify_sent 误判(格式漂移)导致每轮重复投递,
  概率低且可排障(失败时 stderr 打印 rc + 输出尾部)。
- §15 其余功能: 三脚本改动面逐 hunk 核过,仅判据与日志行;dry-run 语义不变(sensenova/check_data_gap 均保留);
  对既有「不轰炸」机制(alert_state / fired / notify dedup)无侵入。

## 5. 最严重一条(供主控上报)

**`scripts/schedule_monitor.sh`: 收尾聚合 `save_alert_state(alert_state)`(L2757)先于 fire-and-forget 的
notify(L2769,`check=False` 丢返回值)⇒ 通道全挂时当晚计划任务告警(邮件/飞书)丢失且 state 已落签
⇒ 条件持续期间永不重发。** 与已修 3 处同后果、覆盖面更大;修它=动已上线行为,须用户拍板(§23.7)。
方向建议(非指定实现): 聚合 notify 后按 `notify_sent` 判定,失败则本轮新写 active 的 key 不落盘(或落
「未送达」标记待下轮重试),成功再 save。

## 6. 复核边界(诚实标注)

- 本审查者**不宣称**新的同后果清单已穷举完毕;本报告已核范围 = 全仓 notify 调用方逐一读 + rc 交叉扫 +
  shell 侧 notify 门控扫。§2 列出的 4-5 处反例任一单独成立即足以否证文档结论句。
- 本报告未写任何代码、未执行任何 git 写操作、未触发任何外发。
