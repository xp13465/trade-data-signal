# #236 F2「预警数据独立上传 R2」审查报告(reviewer,2026-10-09)

> 审查对象:分支 `worktree-agent-a89f83232097aef51` commit `19fd606a5`(基线 origin/main `8b06e0960`)。改动 = `scripts/update_all.sh`(+31/-1,F2 块 L187-218)+ 实施报告 `docs/ops/236-f2-alert-upload-decouple-20261009.md`。
> 实读点:`/Users/linhuichen/code/trade/.claude/worktrees/agent-a89f83232097aef51`(该 worktree 在 19fd606a5;主工作树在 main 不含 F2,已确认,勿混读)。
> 方法:只读(grep/read/git show/`curl --max-time`/ssh 只读);未写 R2 业务 key、未外发、未做任何 git 写、无残留后台任务。关键结论全部独立取证,不采信实施报告自述。
> 裁决:**9 项 → 7 PASS / 2 FAIL(item 6、item 8)**。

## 0. 裁决总表

| # | 审查项 | 裁决 | 一句话事实 |
|---|---|---|---|
| 1 | 死锁结构+唯一通道 | PASS | 拦截(deploy.sh L323-331 check→severe→`exit 1`)早于写入(L582 触发 async);alert.json 的 R2 唯一写入=r2_upload_async.sh L223 upload-all-data,而该脚本唯一调用方=deploy.sh(晚于 exit);无 git 旁路;10-08 实证全天 15 轮 deploy 全败、靠 10-08 22:4x 人工解锁 |
| 2 | F2 放置/就绪 | PASS | 紧邻 export_alert/export_alert_analyze 之后,读写同树 `$REPO/static-site/data`(云上 mtime 19:29:45/19:30);`cd` 仅解决 shell 侧 glob 展开,data_dir 由 REPO 决定 |
| 3 | 非阻塞+三态不静默 | PASS | 无 set -e、块内无 exit;三态各自 tee + 原始输出全文入 LOG。登记 1 处潜在假成功(零文件时 rc=0,需 alert.json 在 export 后不存在=现实不可达) |
| 4 | 互斥/无双重上传/锁语义 | PASS | 两路同 flock(`/tmp/trade_r2_upload.lock`,upload-data-files 不在豁免集);`--skip-if-locked` 只改等待语义(≤60s 有界重试→哨兵+exit 0),不削弱互斥;F2 先成后 all-data 可能重复 PUT 同字节(F2 不写 all-data 状态文件,代码已核),无害 |
| 5 | R2 实证复核+双向问题 | PASS | 四处 md5=65c60ad5…(备份/云本地/R2 直连/CF);LM 推进+etag 不变;skip=零写。**双向:本地新时会推**——upload-data-files 无条件 PUT(无增量跳过),唯一条件是 60s 内拿到锁 |
| 6 | §14 时点+关键一次跳过 | **FAIL** | 会跳过:**10-08 实证** F2 窗口(≈19:30-19:32)整体落在 fund_nav 异步长锁(18:28:38→19:36:48,4089.8s)内 → SKIPPED_LOCKED,当夜自解锁失效(详见 §1) |
| 7 | §15 回归(退出码/后续步骤/解析器) | PASS | 仅 `set -u`;末行 `exit "$RC_CORE"`(L426)不受 F2 影响;F2 只用新变量、subshell 内 cd 不外泄;schedule_monitor 走 schedule_stats.json+开始行(不 grep 日志内容),零解析回归;F2 块内无 notify=无新增告警噪声 |
| 8 | 诚实标注 | **FAIL** | 报告§3 与代码注释 ℹ 分支同称「锁被占=主链 upload-all-data 会覆盖同 key」——在 deploy 被拦日(锁主=fund_nav、主链 async 未跑)不成立;§0「不再需要人工解锁」未含此前提,过度宣称(详见 §1) |
| 9 | §23.3 泛化(同结构面) | PASS | 全部 5 处 R2 读取检查枚举完毕,10-08 21:45 实测 39 项唯一 fail=alert,其余各有独立/容错通道;F2 修的是该族唯一结构性死锁成员;先例核对通过(含 `--skip-if-locked upload-data-files` 同款先例) |

## 1. 两项 FAIL 详述

### FAIL-1(item 6):「最需要它的时候」会被锁跳过 —— 10-08 实证(核心发现)
- **时序重建**(全部证据可复核,见 §3):
  - fund_nav 异步上传:`=== 开始 2026-10-08 18:28:38 ===` + `上传完成 255/256, 耗时 4089.8s` → **锁连续持有至 ≈19:36:48**(单进程 flock 全程持有,非逐文件让锁;push_schedule_stats 19:23/19:28 两轮 SKIPPED 佐证、锁释放后 19:37/19:38 起成功)。
  - alert 导出完成:`generated_at=2026-10-08 19:29:45`,alert_analyze 段日志时间戳 19:30:32-19:30:46 → **F2 执行 ≈19:30:50,+≤60s 重试 ≈19:31:50** << 19:36:48 解锁点。
  - ⇒ **F2 当天必然 SKIPPED_LOCKED**。且跳过分支的兜底假设失效:当天锁主是 fund_nav(不是主链 upload-all-data),主链 async 因 deploy 被拦根本没跑 → alert.json 在 R2 整晚未被刷新(21:45 轮仍是唯一 fail 项)。
- **为什么这恰是关键时刻**:10-08 = 长假后首个交易日(本地 20261008 新版 19:29 才生成;R2 卡在 20260930 已 8 天);而长假后 fund_nav 首日全量重传(255/256 桶、562MB)必然最长——**「自锁最需要被解」的日子 = 「锁最被占」的日子**,二者结构性重合。对照:普通交易日 fund_nav 上传为增量(09-29/30:10-20 桶、43.5s/81.4s,远早于 F2 窗口完成),不冲突。
- **影响边界(诚实标定)**:自解锁**延后 ≤1 天**(次日更新窗口通常无锁竞争 → F2 成功;10-08 若不人工解锁,10-09 晚即会自解)。期间 deploy 侧 severe 告警持续可见(dedup ≤6h),无数据损坏、无生产安全隐患。⇒ 定性=「保证弱于宣称」,**非生产事故级**,但不支持「不再需要人工解锁」的绝对表述(极端连日长锁可再需人工)。
- **建议方向(交 implementer/主控,本审查不改码)**:同轮二次尝试——把 F2 复制一行放到 `etf_score_list` 块之后(10-08 该时点锁已在 19:36:48 释放,19:37 起他链成功可证,当夜即可自解);或把 `R2_UPLOAD_SKIP_RETRY_SECS` 重试窗拉长到覆盖典型长锁。二择一即可闭合本条。

### FAIL-2(item 8):诚实标注缺口(两处过度宣称/错误陈述)
- 实施报告 §3:「主链 R2 上传在跑 ⇒ 锁被占 ⇒ 本步跳过(且该 async 的 `upload-all-data` 会把同 key 覆盖,内容一致)」——**关键日不成立**:锁主可为 fund_nav 等非主链任务,此时无人覆盖同 key。
- 代码注释 ℹ 分支同病:「主链 R2 上传在跑, 其 upload-all-data 会覆盖 alert.json/alert_analyze, 无需干预」——按此文案,运维在最该介入的日子会被引导为「无需干预」。
- 报告 §0「不再需要人工解锁」应加前提(如「锁可得时」)或改为「把永久锁降级为下一轮自解锁(典型 ≤1 天)」。
- **计分说明(该 FAIL 限于上述措辞与缺项)**:报告其余诚实性达标——§2 已承认 F2 单修=降级为自解锁、长假「本地也旧」归 #235 F1(非本任务)✓;§4 备份先行(§25)+真锁 skip 测试+三态 harness+回滚段+范围外清单 ✓。

## 2. 影响面清单(grep 改动面:谁引用/谁消费)
- **调用方**:`update_all.sh` = 顶层编排器,调用方仅云上 `trade-update-all` timer(Mon..Sat 17:50)+ 手动;无脚本 source 它。非交易日 L75 提前 exit → F2 不跑(与 alert 不再重算一致,F1 口径问题另计)。
- **数据消费面**:F2 只写 R2 `data/alert.json` + `data/alert_analyze_*.json`(同批同源,§22 两展示位日期一致);消费方=前端预警条/预警分析弹窗 + `check_data_integrity.check_alert`;前端显示层代码/版本串零改动(§24 N/A)。
- **锁生态**:新增 1 个有界让步型竞争者(拿不到锁 ≤60s 即退,不排队 7300s);既有锁主(fund_nav async/deploy async/push_schedule_stats/intraday/s06/kelly_intraday_rerun 等)行为不变。
- **日志/监控面**:`schedule_monitor.sh` 监控口径=schedule_stats.json(last_exit/last_run/duration)+ 日志开始行正则,不按 ⚠/✗ 关键词 grep update_all 日志 → F2 新行零解析回归;update_all 自带 SEVERE 聚合(L330-347)未收 F2 rc(设计选择:可见性由 deploy 侧 check_alert 独立兜底,已核该告警键 `deploy_check_data_integrity_fail` 在位)。
- **退出码面**:分支脚本 L27 仅 `set -u`(无 `set -e`);L426 `exit "$RC_CORE"` → F2 不影响父退出码与后续步骤(check_signals/intraday/etf_score_list/notifications/fund_score/gen_stats/push_schedule_stats 全在 F2 之后照常)。

## 3. 七项 PASS 的证据锚点(复核用)
1. **死锁结构**:`deploy.sh` L323-331(check→notify severe→`exit 1`)< L582 触发 async;`r2_upload_async.sh` L223 upload-all-data(无 `--skip-if-locked`);`grep` 全仓 `r2_upload_async` 调用方仅 deploy.sh;`static-site/data/*` 全量 gitignore(0 tracked,无 git 旁路);`check_data_integrity.py` L417 读 `ss.fx8.store/data/alert.json`,L431 `>7` 自然日 FAIL。实证:10-08 共 15 轮 deploy(02:06…21:45)全败,末轮 21:45 `=== 汇总: 39 ok / 2 warn / 1 fail ===` 唯一 fail=alert(date=20260930 滞后 8 天),而 R2=20260930、本地=20261008(19:29:45)未上;10-08 整日 r2_upload_async 零日志;解除=10-08 22:4x 人工解锁(a409787ad 只读核查报告载明)。
2. **就绪/放置**:commit 实文 F2 块在 C6/C7 两 export 之后;云上 alert.json mtime=Oct 8 19:29、alert_analyze 最后一批 19:30;`upload_r2.py` L51 `STATIC_DIR=REPO/static-site/data`;实施报告 §1-1 的 exists() 预过滤坑(字面量 glob 会被静默丢)已用 shell `cd`+展开修正,复核实符。
3. **非阻塞/留痕**:F2 块无 set -e 语义依赖、无 exit/return;三分支(`RC≠0`/`SKIPPED_LOCKED`/else)全部 `tee -a "$LOG"`,且 `printf '%s\n' "$ALERT_R2_OUT" >> "$LOG"` 全文留痕;无虚假错误文案。登记:零文件时 `cmd_upload_data_files` L2374-2376 打「⚠ 无文件」后 rc=0 → 会走「✓ 完成」假成功分支(现实不可达:alert.json 刚被 export 写出)。
4. **互斥**:两路均经 `upload_r2.py` 内 `_acquire_r2_upload_lock` 取同一 flock;豁免集(list/delete/download-db/clean-data-backup/upload)不含二者;skip 语义=有界重试后 `SKIPPED_LOCKED:` + `_SKIP_R2_LOCKED` 哨兵 + `sys.exit(0)`(上传前退出=零写);F2 不写 `.r2_all_data_state.json`(L2359-2394 只写 `.r2_standalone_keys.json` + purge)→ 后续 all-data 重复 PUT 同字节,§22 一致无害。
5. **R2 实证**:备份 `/home/ubuntu/backup/f2-236-20261009/alert.json.before` = 云本地 = R2 直连(ssd)= CF(ss)md5 均 `65c60ad5378e4179a40bfacb69c08352`;HEAD etag 同值;真 PUT 后 LM 推进至 `Fri 09 Oct 2026 08:26:23 GMT` 且 etag 不变(字节未变);skip=零写(LM 不动)。双向问题=**会推**(见总表 #5);`worker/headers.js` L209 alert.json TTL=60s + `cmd_upload_data_files` L2393-2394 上传后 purge → CF 侧及时可见。残余登记:实机 PUT 为同字节,「内容变化→CF 可见」端到端未直接实证(路径=无条件 PUT+purge+60s TTL;同通道生产 11 个调用方长期在用)。
7. **§15 回归**:见 §2 三条面;另 update_all 完成邮件正文(L364)只列 core/width/futures/deploy_all/check_signals rc,不含 F2 → 无邮件文案回归。
9. **§23.3 泛化**:`check_data_integrity.py` 全部 `_fetch_r2_json` 读取点=alert(L417)/notifications(L446)/nextday_plan+auto_trade_steps(L1953/1992)/signal_kelly_day_snapshot(L2076)/kelly_mode_s06_state(L2175/2190),共 5 族;10-08 21:45 实测唯一 fail=alert,notifications=20261008、s06 R2 副本=20261008、nextday_plan=20260930 被交易日历容差判过(容忍上一交易日)→ 各有独立/容错通道,同结构死锁仅 alert 一家(本轮已修,家族含 alert.json+alert_analyze_* 全)。先例核对:`push_schedule_stats.sh` L67-85 现有 `--skip-if-locked upload-data-files` 同款(含 skip 文案与 3 轮告警升级)、`s06_snapshot.sh` L135 upload-data-files 同通道——F2 形态有先例、非新发明。
- **§14**:F2 执行窗 ≈18:3x-19:3x(云上 17:50 链),避开 15:35/16:00/17:50 禁区;20:35/22:00 只涉锁竞争(非阻断退出),无生产安全影响。**§21**:非算法改动(不动 track_score/评分/权重/口径),公示 N/A。**§24**:不触前端/版本串,N/A。**数据层 smoke**:ss/ssd 两域 alert.json GET md5 一致、date=20261008、generated_at 有效;ssd HEAD etag 一致。

## 4. 建议(给主控)
1. 本次改动相对现状**严格改善**(最坏情形=回落现状),无生产安全回归,可从功能面 merge;建议随 merge 或紧随其后闭合 FAIL-1 的最小缓解(同轮二次尝试一行级)或至少先订正 FAIL-2 的两处措辞/注释,避免关键日误导运维。
2. 与 #235 F1 保持同批/recon §4 互补关系:仅 F2 不覆盖「长假本地也旧」;两者叠加才等于「结构死锁消除 + 事件不发生」。
3. 状态登记:#236 的 pending 状态列归主控收口(不在本审查范围)。

## 5. 证据索引(可复核)
- 代码(分支 19fd606a5):`scripts/update_all.sh` L174-176/L187-218;`scripts/deploy.sh` L323-331/L582;`scripts/check_data_integrity.py` L410-436;`scripts/upload_r2.py` L51/L1947/L2164/L2359-2394/L3866;`scripts/r2_upload_async.sh` L200-226;`scripts/push_schedule_stats.sh` L67-85;`scripts/s06_snapshot.sh` L125-140;`worker/headers.js` L209。
- 云上日志(只读):`update_all_20261008_1750.log`(mtime 19:38:16);`deploy_20261008_2145.log`(39ok/2warn/1fail 全文块);`deploy_20261009_*.log`(00:13 起全 0 fail);`fund_nav_upload_async_20260923/24/28/29/30、20261002/03/08.log`(锁定持有窗口谱);`r2_upload_async_20261009_002208.log`;`alerts/latest.md`(10-09 各告警)。
- 制品:`/home/ubuntu/code/trade-data/static-site/data/alert.json`;`/home/ubuntu/backup/f2-236-20261009/alert.json.before`;`/home/ubuntu/code/trade-data/data/.r2_standalone_keys.json`。
- 交叉文档:`docs/ops/deploy-selflock-recon-20261009.md`(§2 死锁行号/§3 10-08 六项/§4 F1+F2 互补)、`docs/ops/236-f2-alert-upload-decouple-20261009.md`(实施报告)、a409787ad(只读核查提交,载「10-08 22:4x 人工解锁」)。

---
*reviewer agent 落档,2026-10-09;只读审查,唯一产出本文件;无 R2 写/无外发/无 git 写/无残留后台任务。*
