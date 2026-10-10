# 下一步全面建议方案 v1 事实性复审(复审2 · fact · researcher 只读)

- 复审对象:`docs/ops/next-steps-plan-20261011.md`(v1,124 行)+ 辅助 `docs/ops/next-steps-inventory-20261011.md`
- 复审角色:researcher(只读;未改任何 repo 文件(本报告除外);未 commit;禁跑业务脚本(notify/feishu 链零执行);禁云上写(ssh 仅 `systemctl cat/list-timers` 只读);R2 仅 LIST(零写,产物落 /tmp);禁 WebFetch 未用)
- 复审日期:2026-10-11(周日)06:5x~07:0x;**残留后台任务:无**(全部命令前台完成)
- 方法:断言逐条对实物 —— 本地码逐行读 + index/memory/报告逐行对读 + `git worktree/branch/rev-list` 实测 + 云上只读 ssh(`systemctl list-timers|cat`)+ R2 只读 LIST(`scripts/r2_list_prefix.py`,工具自述硬红线仅 LIST 零写,复现:`…/.venv/bin/python scripts/r2_list_prefix.py signal-data "fund_nav/" /tmp/fund_nav_list_20261011.json`)

**一句话结论**:14 项清单 24 条断言中 **一致 19 条 / 不一致 4 条(1 高 2 中 1 低 系)/ 口径待改 3 条**;**最重 finding = F1:#220「首实战 19:30 核查点」与周日实际排程(22:30 起跑)冲突 —— 核查点落在事件前 3 小时,且周一 09:40 综合核查不含 #220,首实战大概率无人核**(证据=云上 timer 实测,`OnCalendar=Mon..Sat 17:50 / Sun 22:30`;相关 cron `6e0ca4bc` 已按 19:30 建出,建议改)。其余为数字口径问题(D3 引用已撤回推算+口径混用;fund_nav ~578MB vs R2 实测 556.8MB;每日 PUT 256 判据过时)。

---

## 1. 断言核实表(断言 → 实测(含来源) → 判定)

| # | 方案断言(v1) | 实测证据(来源) | 判定 |
|---|---|---|---|
| 1 | 时点「2026-10-11 周日休市 / 10-12 周一;main tip `8e19ed24e`;在跑 agent=0」 | `date "+%F %A"`=2026-10-11 星期日(10-12=星期一);`git rev-parse main origin/main` 均=`8e19ed24e68…` | ✅ 一致(agent 数=时点值,不可回溯,标「无法核」) |
| 2 | B1 周例行「上次 9-27,已满 14 天含一周空缺」 | memory `memory-weekly-review-20260927.md`(modified 2026-09-27T11:49 ✓);9-27→10-11=14 天 ✓ | ✅ 一致 |
| 3 | B2-1/#229 病灶「`--tier info --dry-run` 仍写 `info_log.jsonl`」 | `scripts/notify.py` 现码:`send_tiered` L2501-2503 TIER_INFO 分支 `log_info(subject, body)` **不透传 dry_run**;`log_info` L1697 **无条件** `_append_jsonl(INFO_LOG_FILE, rec)` | ✅ 病灶成立(行号注:index L354 记 2070-2071/1424,已漂移) |
| 4 | B2-2/#230 病灶「`--flush-warnings --dry-run` 建 0 字节 flushlock」 | `flush_warning_batch`(L2124)函数头后 **L2141-2143 无条件** `WARNING_FLUSH_LOCK_FILE.parent.mkdir(...)` + `open(...,"a+")`(在任何 dry_run 判定之前) | ✅ 病灶成立 |
| 5 | B2-3 #245⑩/#247-R1「sh 兜底句文案失真」 | index L377 尾:「决策项 10 …R2 失败时 py 先发+sh 无条件再发=秒级双封;sh 兜底句**「计划未生成」**在 R2 失败场景失真…待用户拍板」;L379 尾:「残余非阻断:R1 notify-fail 分支 sh「未生成」残差(pre-existing,已报备)」 | ✅ 一致 |
| 6 | B2-4 #226 conftest tempdir | index L351:tempdir 无显式清理、待排期(加 atexit/finally) | ✅ 一致 |
| 7 | B2-5 #236「update_all.sh 注释旧数 211s」 | index L364 尾:「残余:`scripts/update_all.sh` 注释仍写旧数 211s」;脚本实文 L203/265/269 =「10-08 实测 ≈211s」;同行「报告数字订正 211s→222s」 | ✅ 一致 |
| 8 | B2-6 #240「残余 5 条文书」 | index L372 尾:「残余 5 条低级(docstring 行号 / 报告文件数等,不阻塞)」 | ✅ 一致 |
| 9 | B2-7 #245-卫生/#247-残余 | L377 尾「卫生项(留档):worktree 合成残留(低)+ 主仓 legacy 包装套件不隔离 REPO」;L379 尾「R2 legacy 套件 REPO 隔离既存项」 | ✅ 一致 |
| 10 | B2-8 #115-遗留② style.css 注释 | index L81 尾:「遗留② style.css #74 注释另行排期,不阻塞本项」 | ✅ 一致 |
| 11 | B2-9「本地 7 worktree-agent-* + 6 feat/* 全 merged;§25 证据=origin/main 即备份」 | `git worktree list` 仅 main;`git branch` 实测 **7 + 6 = 13 支**;逐支 `git rev-list --count main..<b>` **全 0**;origin/main=main=`8e19ed24e` | ✅ 一致(详见 F7:TASKS L41⑤ 旧文案写「5 个」) |
| 12 | B3 #111「26,458 文件(~578MB R2);窗口 10-07~10-14,剩 3 天;前置三项」 | memory `fund-nav-bucket-p3-followups`(26458 只/~578MB/窗口/前置三项)✓;index L77(26458/531MB/待执行约 10-07~10-14)✓;**R2 只读 LIST 实测:26,458 obj / 556,807,260 B = 531.0 MiB(0.557GB),全 .json,mtime 冻结 09-20~09-22** ⇒ 文件数逐位 ✓ | ⚠️ 数字对一半:文件数 ✅ 逐位一致;「~578MB」与实测 556.8MB 偏差(F4);剩 3 天算术 ✓ |
| 13 | B3「app.js 有 fund_nav/ 回退双读逻辑」 | `static-site/app.js` L27770 注释「桶缺失/桶内无该 code → 回退旧 per-code fund_nav/{code}.json(过渡期…§24 防撕裂)」;L27838-27841 实现;L27840 `fetchJSON('https://ss.fx8.store/r2/fund_nav/${code}.json')` | ✅ 实物存在(补:回退 404→结构校验抛错→catch 显示「净值历史数据加载失败」,其他区块不受影响 ⇒「无害回退」成立) |
| 14 | B3① 前置「每日 PUT 256 / 无 severe / check_r2_consistency;窗口数据可从云上日志取」 | 云上 `data/logs/fund_nav_upload_async_*.log` 在(最新 10-09 18:15:21:「共上传 **7/7** …(较全量少传 249 个)✓ 完成 33.3s」);256=全量基数(7+249) | ⚠️ 「每日 PUT 256」判据与现行为不符(F5);数据可取 ✅ |
| 15 | #220「6 条 severe=5 真 1 误报;修 b4c5ff5ff/69803a006;651/655s;今晚 force_full 首实战」+ §4「今晚 19:30 核查」 | 220 报告 L18-30 ✓(5 真 1 误报、两 commit、651/655s、首个周日 10-11);**云上实测 timer:`OnCalendar=Mon..Sat 17:50:00` + `Sun 22:30:00`,NEXT=Sun 2026-10-11 22:30、LAST=Sat 10-10 17:50** | ❌ 19:30 核查时点错误 → **F1(高)** |
| 16 | #227「五条候选全 0 生产触发、不偏紧;audit 扩 Python subprocess 轴」 | 报告 L8「全部 0 生产触发、全部不偏紧…建议不动」;L82-86 §1 附2=扩轴建议(三类:内层>外层/==/外层∞) | ✅ 一致 |
| 17 | #237「relay 已上线 9ae8c50cc;C 开关未开;A 观测前置;10-11 全量验证/10-12 首观察日」 | `git merge-base --is-ancestor 9ae8c50cc main`=YES;index L366 尾「未开项:①C 级 fail-fast(须 A 观测≥1 交易日 failed≈0 后拍板)②retention 7→3~5 拍板」「首个真实观察点=下个上传窗口(10-11 全量验证/10-12 首个观察日)」 | ✅ 一致 |
| 18 | D3「retention 缩到 5 天;届时数字:10-12 老账号≈7.23GB 已自然达标,10-26→≈5.93GB」 | index L358 含「修正 #233 §5 推算链偏高…**修正后 10-12 pre-upload 全清 ≈4.37GB 即达 <6GB…终值(11-03 后)≈3.05GB**;老账号合计 10.46GB→10-12 后≈7.23GB 自然达标」;`r2-backup-bucket-release-20261010.md` L104 更正留痕:「~7.56/6.24/5.93 均…整链偏高」 | ❌ 引用已撤回推算+口径混用 → **F2(中)** |
| 19 | §4 cron 六项(fd456d7a/6e0ca4bc/a443dff9/541d860f/72c2bd8b/a7654a3b)+「e7a38b38 重排为综合版」 | `.claude/scheduled_tasks.json` 六条全在:fd456d7a(32 8 11 10)/6e0ca4bc(30 19 11 10)/a443dff9(40 9 12 10,prompt 原文「替代原 e7a38b38」)/541d860f(7 19 30 10)/72c2bd8b(3 10 1 11)/a7654a3b(recurring `3,18,33,48`) | ✅ 一致(6e0ca4bc 时点问题见 F1;今日 06:50 实测 fd456d7a 尚未到点,符合) |
| 20 | W 批「已定案未动工」:#215/#182/#161/#216/#225;「#182 参照 #154 先例」 | L340 #215 待实施 ✓;L307 #182 待办+「可参照 #154 已上线 check_monitor_heartbeat 模式」✓;L250 #154=「告警链 4 漏点加固+check_monitor_heartbeat 挂载(已上线,7ee2c33ee/3d2fa44e6 在 main)」;L257 #161 待办(含「最长 7 天」✓);L341 #216/L350 #225 待排期 ✓ | ✅ 一致 |
| 21 | W1-W4 锚点(W1 两事实核查 / W3 #222 ≈173MB/轮 / W4 #142/#148) | `r2-publish-arch-industry-research-20261005.md` 在位(26,896B)✓;index L347 #222「≈173MB/轮(≈1GB/天)…风险高于 parts…先派 researcher 只读定性」✓;L238 #142 已 merge main e4b960fc7 ✓、L244 #148「观察中(节后复测)」✓ | ✅ 一致 |
| 22 | B4②「#218 六条建议/#205 裸调用/#149④ timer 错峰(待授权)」;附录A「存疑 2 → B4①(#221)+ 登记待决①(B4②核)」 | L343 #218 尾「报告 §7 含 6 条建议」✓;L331 #205 部分实施(修前须逐脚本归因)✓;L245 #149 尾「④timer 错峰(需云上 systemd 写授权,仅出待办清单)」✓;**但「登记待决①(rzhb 登记漂移,需云上只读核)」在 B4①/B4② 明细均未列** | ⚠️ 附录A 与 B4 明细不一致 → F3(中/低) |
| 23 | #234-残余「hold_sweep 27M 实删 + 云上日志压缩」 | 本机+云上 `docs/kelly/hold-days-sweep/hold_sweep_trades.json` 均=`28,234,546 B`(同 size/mtime,两树都在位);云上日志 3056 文件 0 个 .gz | ✅ 一致 |
| 24 | B2-1/2「与已上线 #184 同族同法可小改」可行性 | #184 修复已在 main(#184 行「tip 8997c6300」;单点守卫模式);notify.py 现有契约:send/defer_warning 透传 dry_run(L1161-1194/L2511),log_info/flush_warning_batch 未接 ⇒ 补门控=小改、模式现成 | ✅ 同族成立、可行 |

## 2. Findings(严重度 / 证据 / 建议)

### F1(高)#220「首实战 19:30 核查点」时点与周日实际排程冲突,首实战大概率无人核
- 证据(4 源交叉):
  ① 云上只读实测(本轮):`systemctl cat trade-update-all.timer` = `OnCalendar=Mon..Sat 17:50:00` + `Sun 22:30:00`;`systemctl list-timers` = **NEXT `Sun 2026-10-11 22:30:00 CST`、LAST `Sat 2026-10-10 17:50:01`**(即周日在 22:30 前无 update_all 运行);
  ② `b4c5ff5ff` commit 原文:「任务 C:trade-update-all.timer **周日错峰到 22:30(周一~周六维持 17:50)**」;
  ③ 220 报告 §5.2:「异步解耦 + **周日错峰(Sun 22:30 档)**」「首个完整周日(10-11)」;
  ④ 自家盘点 inventory L87/L159:「#220 首个周日 force_full 实战(**今晚 22:30 档**)」。
- 影响:方案 §0/§4 的「今晚 19:30 核查点」+ 已建 cron `6e0ca4bc`(`30 19 11 10 *`)在事件前 ~3h 触发 —— 届时只会看到 10-10(周六)旧 run,极易得出「正常/无异常」假结论;且 §4 的 10-12 09:40 综合核查(`a443dff9`)四项(gap-check/patrol/#233 D③/#237 A)不含 #220 ⇒ 这场「异步版首次周日全量实战」落空无人核。附录B 轮 2 自称「修正 #220 核查点」,实际把正确值(22:30)改错了。
- 建议(二选一,推荐 b):a) 重排 `6e0ca4bc` → 10-12 凌晨(220 报告:22:30 起最长 ~3h 止于 ~01:30);b) **删除 `6e0ca4bc`,把 #220 核查项并入 `a443dff9`(10-12 09:40 综合核查,一次在事件后核完,免半夜跑)**。

### F2(中)D3 引用已撤回的推算值 + 两个口径串链
- 证据:index L358 同段含 10-10 复核「**修正 #233 §5 推算链偏高**(「~7.56GB」与字节口径不符…**6.24/5.93 均沿用该起点故整链偏高**)→ 修正后 10-12 pre-upload 全清 ≈4.37GB 即达 <6GB,终值≈3.05GB;老账号合计 10.46GB → 10-12 后 ≈7.23GB」;`r2-backup-bucket-release-20261010.md` §5.2 里程碑表(10-12=4.37GB / 10-18/19=3.38GB / 10-26=3.07GB / 终值 3.05GB)+ L104 更正留痕。
- 问题:「10-12 老账号≈7.23GB」=**老账号合计**(老桶+主桶)且 ✓ 未过期;「5.93GB」=**老桶单项**且已被同源修正作废 ⇒ 两值不同口径、后者失效,串成一条「老账号 7.23→5.93」轨迹不成立。
- 建议:D3 改引「10-12 老账号合计≈7.23GB(达标);老桶终值≈3.05GB(11-03 后)」;并补 retention 决策的真实驱动=**新账号 pre-upload 稳态**(7 天≈7.7GiB+主≈4.23GiB≈12GiB 越线;3 天≈3.3GiB ⇒ 合计≈7.5GiB —— 237 设计稿 L187),避免用户按「老账号已达标」误判 retention 可不动。

### F3(中/低)附录A「登记待决①→B4②核」与 B4 明细不一致
- 证据:附录A「存疑 2 → B4①(#221)+ 登记待决①(B4②核)」;但 B4① 列项(#221/#185④+#186/#239/#198·#200·#202/#124)与 B4② 列项(#218/#205/#149④)**均不含 rzhb 登记漂移**;且 inventory 标它「**需云上只读核**」,与 B4②「本地对账」性质不符。
- 建议:rzhb 19:15 槽核对并入 B4①(云上只读 tester)。

### F4(低)B3 尺寸「~578MB」与 R2 实测不符
- 证据:R2 只读 LIST 实测 `fund_nav/` = **26,458 obj / 556,807,260 B = 531.0 MiB(0.557GB)**;「~578MB」源=`fund_nav_upload_async.sh:4` 注释旧估;index L77 的「531MB」实为 531MiB,与实测吻合。
- 建议:B3 改「26,458 obj / 556.8MB(531.0 MiB),mtime 冻结 09-22」。

### F5(低)B3① 判据「每日 PUT 256」过时
- 证据:云上 10-09 日志「共上传 **7/7**(较全量少传 249 个)」= 现行为增量上传;256=全量基数。
- 建议:判据改「上传成功 + 失败=0 + `check_r2_consistency` 通过 + 检查器(pre-upload backup)无 FAIL」。

### F6(低)B3 清理范围只写 R2,未含本地镜像/备份仓携带
- 证据:memory 动因含「仍残留 static-site/data/,…占盘且 rsync 继续带进备份仓库」;实测本地 `static-site/data/fund_nav` = 26,370 文件 / 553.0MB(apparent)/du 574MiB;方案 B3 仅写「删 fund_nav/ 旧前缀 26,458 文件(~578MB R2)」。
- 附注(无风险):桶化后 `upload-fund-nav` 通道只写 `nav_bucket/`(fund_nav_upload_async.sh:6-7 及失败文案),删旧前缀不会被重传 ✓。
- 建议:B3 注明本地镜像与备份仓携带如何处置(或写明只动 R2 的理由)。

### F7(低)TASKS L41⑤ 旧文案「5 个 worktree-agent-*」与实际 7 个不符
- 证据:TASKS「⑤5 个 worktree-agent-* 本地分支独有 commit=0」;实测 7 个(计划 B2-9 已用 7 ✓)。建议 B2-9 执行时同步订正 TASKS。

### F8(信息)index 行号漂移(病灶语义与记录一致,仅行号)
- #229 记 2070-2071/1424 → 现 L2501-2503/L1697;#230 现 L2141-2143。建议顺手更新登记,防后续派单锚点失效。

## 3. 检查清单覆盖
任务 14 项清单 + 3 项可行性抽查(notify 小改 / 前端双读下线影响 / #197 §25 前置)全部覆盖:清单 1→表#12、2→#15、3→#18、4→#17、5→#16、6→#5-11、7→#3-4+#24、8→#13、9→#11、10→#23、11→#2、12→#20、13→#1、14→#19;可行性:notify 小改=#24 ✓、前端双读(删除数据后回退 404=错误提示降级、无崩溃/无跨区块影响)✓、#197 prune 前置(§25 备份→实测→删,详见 W5 表述,未见事实性偏差)✓。

## 4. 只读合规与残留声明
- 未跑任何业务脚本(notify/feishu 零执行);ssh 仅 systemctl 只读两命令;R2 仅 LIST(零写);未改 repo 文件(本报告除外);未 commit。
- 残留后台任务:**无**。
