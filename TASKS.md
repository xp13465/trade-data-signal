# TASKS.md - 情绪看板迭代任务清单（监管 + loop 工作模式）

> 这是「监管 + loop」工作模式的唯一共享任务文件。子进程开工前**必读本文件** + `REQUIREMENTS.md`（需求真实来源）+ `NOTES.md`（调研笔记）。监管（主进程）不直接干活，派子进程领任务循环。

> **历史已完成/关闭/远期项已按 2026-08-20 任务治理归档(4 态/4 文件流转,非删)**:①真完成 → [docs/tasks-done-list.md](docs/tasks-done-list.md)(**完成文件**,53 条标注完成态 = 43 TASKS治理 + 10 费率改造;呆满 7 天自动归档到 docs/archive/TASKS-done.md)②用户关闭 → [docs/archive/TASKS-done.md](docs/archive/TASKS-done.md)「2026-08-20 任务治理归档段」留关闭记录;③早期历史交接/旧需求 → [docs/archive/TASKS-history-archive-20260820.md](docs/archive/TASKS-history-archive-20260820.md);④远期/搁置待办(场外方案C/性能P2/管理端看板/场外阶段) + 8 项被归档的活跃需求(留言箱/ETF485扩采/公募筛选器/板块轮动/真pin/PWA/订阅推送/overlap delta) → [docs/pending-features-index.md](docs/pending-features-index.md) **模块十六 #79-90**,用户要远期明说再捞回。**本文件只留活跃待办 + 大纲 + 工作约定 + 最新交接**。治理报告:docs/tasks-active-only-clean-20260820.md。前序瘦身归档指针见 [docs/archive/TASKS-done.md](docs/archive/TASKS-done.md)。

## 📍 当前会话状态（compact 恢复用,每次状态变化后 Edit 更新）

> compact 后第一动作:读本小节恢复 transient 状态(活跃 agent/cron/commit 链/正在等什么)。详见 memory `compact-recovery-checklist`。

**最后更新(2026-10-05 12:05 周一·国庆休市)——新会话开工:并行派 4 agent 清交接待办**

> **权威任务状态以 [docs/pending-features-index.md](docs/pending-features-index.md) 为准**(§23.12-1),本节只写 transient 指针。
> **新会话(2026-10-05 12:05 起)已接手**;上一会话两个 agent(r2fix-review / bkt-audit)均已收工且产物归档,无遗留。

**在跑 agent:1 个(background + 进度文件;巡检 cron 兜底,完成即删)**
1. 🔄 `#178 备份桶迁账号` = **delta 复核 = 不 PASS**(代码硬化 A/B/C/E 全 PASS、无 P0/P1;**唯一问题 = 文档 D(a)**:误引「配置前」快照称老桶非 backup 前缀永久滞留 6.61GiB,与 #179「两桶 5 规则已配」矛盾)→ implementer 续跑修文案(进度 `/tmp/agent-progress-178.md`)→ 待快速复核 → main-merge。硬化=large-json state 加 `bucket` 字段,换桶自动退化全量(根治「≤6 天静默假完备」窗口)。合后**待办**:①空闲窗口触发首轮回填(≈3.1 万对象/≈450MB 灌新桶)②云上 `.env` 核无 `R2_BACKUP_BUCKET` 覆盖(rev1 实测已有 `R2_BACKUP2_*` 4 键,rev2 又说「需补」→切换时以实测为准)③**时序**:若切点早于 10-06,老桶 large-json legacy 27,673(≈0.27GiB)切走后无人清(不配 lifecycle)→ 切后按 §25 手动清。老桶 large-json 孤儿:新桶验证完整前不删(§25)。
2. ⏳ `#163 断档回填` = **已实施并上线 + 已合 main `90537c538`** → **reviewer 独立复核 PASS**(订正正确无需回滚;口径 5211/5212 应采用;备份库/日志/三源实物锁死)→ **待用户拍板**(保留 09-29/30 显示值订正 vs 回滚)。

> ⏳ **待用户拍板(#163 两点)**:①回填口径取 **5211/5212**(排除 348 只 920 北交所,依 #101 公示口径 + `bj_width.py` + `width_history.py:code NOT LIKE '920%'` 三源一致),非派单写的 5559/5560(含 920);②09-29/09-30 的 `a_width_*` **显示值被订正**(up 3471→3249 / down 1932→1819 / zt 57→53·52→56,其余 62 天逐位不变),因原 intraday 值含北交所、违反公示口径;**不拍则维持现状(已上线)**;回滚法见 pending-index #163 行。
> 🔎 **#163 顺带发现(待排 follow-up)**:`cmd_upload_all_data`/`purge-low-freq` 的 purge 只清 `/data/` 不清 `/r2/data/`,致 `/r2/data/a-stock-*.json` 边缘缓存残留(已手动 purge 修当前);根治=照 data-large 双前缀做法,**等 #178 收工后一起改 `upload_r2.py`**。另:`upload-etf-hist` 被看门狗 kill(severe 告警,05:10 同款,非本次引入,无数据缺口,force_full 未完成即被杀)。
> ✅ 本会话已完成:`#180 三项必改`(implementer + **reviewer PASS** → **已合 main `7d5f17b38`**,云上已同步)· `#163 断档回填`(implementer,补 9/29-9/30,已合 main `90537c538`,云上已同步)· `large-json 可配性核实`(researcher → **#179 定案不配**)· `陈旧 worktree 清理`(删 48 留 2,零丢失)。
> ✅ `陈旧 worktree 清理` **已完成**(2026-10-05 12:1x,general-purpose):删 **48 个**、留 2 个本会话 implementer、**零内容丢失**;§25 可逆性验证 6 个有改动项均无抢救价值(两份报告 md5 与 main 版逐位一致);`git worktree list` 现剩 4 项;残留空目录 `.claude/worktrees/refreeze` 已清。

> 上一会话已收工留档:✅ `r2fix-review` 有保留 PASS 已合 main(`4b88a1251`,9 项全审无 P0);✅ `bkt-audit` 报告已合 main(`docs/ops/r2-backup-prefix-lifecycle-audit-20261005.md`)。reviewer 报告 `/tmp/r2fix-review-report.md`(建议落 docs/ops/,已并入 #180 落档)。

**本会话已完成**
- R2 死循环**根因报告已合 main**(`9af15ec58`,`docs/ops/r2-export-guard-backup-timeout-rootcause-20261005.md`)。
- **备份桶新账号凭据双端落 `.env` 并实测通过**(本机 + 云上各 LIST/PUT/GET/DELETE/复查 五动作全过;云上须走 Python 通路,curl 7.81 的 `--aws-sigv4` 不可用)。
- pending-index:新增 **#178**(备份桶迁独立 CF 账号);**#174 / #176 / #177 / #163** 状态列全部更新(修复已实施·待审 / #163 方案已定案)。

**关键决定(2026-10-05)**
- 老桶存量**不搬**(用户拍板):只切今后新写,存量靠 lifecycle 自然回收。
- 备份桶走**独立 CF 账号**(独立免费额度),非本账号第二个桶。

**git 状态**:main `9af15ec58` 干净;`worktree-agent-a32eca2ef3e40884f` 已推 origin **未合 main**;本交接文档走分支 `docs/session-handoff-20261005`。

**下一步(按序,硬期限 2026-10-08 开市前 —— 10-05~10-07 假期窗口是唯一机会)**
1. ✅ **已完成** —— `r2fix-review` 有保留 PASS → 已合 main `4b88a1251` → 云上已同步。**遗留 = pending-index #180 三项必改项**(优先 ㈡ 大文件低速误杀回归)
2. 派 implementer 实施 **#178**:`upload_r2.py` 引入第二套 endpoint+凭据并按目标桶路由(**#176 已合 main;须等本批 #180 收尾再派 —— 同改 `upload_r2.py`,不可并发**)
3. 派 implementer 实施 **#163** 断档回填(首选 = `fapi_daily_raw` 库内搬移,分钟级;详见 pending-index #163)
4. ✅ **普查已完成,报告已归档**:`docs/ops/r2-backup-prefix-lifecycle-audit-20261005.md`(合 main)。**下一步 = 用户 dashboard 配规则**(我方 key 查 lifecycle 返回 403,配不了)。用户已拍板「**新老桶都补**」,定稿规则见 **pending-index #179**:`pre-upload/` 补 **7 天(最高优先,5,540 个 3.13 GiB、日增 ~1.08 GiB)** / `weekly/` 28 / `monthly/` 365 / `large-json/` legacy 补 7 天(**flat 31,673 严禁配删除规则,唯一副本**) / `claude-backup/` 30 / `backup/` 14 已配 / `decommissioned/` 与 `mac-backups/archive/` **不配**。**新桶 `signal-backup2` 已复核存在且为空,直接在它上面照配同一套。** **⚠️ 仍未解决的一处记录打架**:老桶 `backup/` 规则是 **14 天**(用户 10-05 dashboard)还是 **30 天**(本文件 #169 记的 10-04 dashboard)——直接影响存量回收速率,请用户下次开面板时顺手再核一眼
5. 清理 `.claude/worktrees/` 下 **~48 个陈旧 worktree** —— 🔴 **动手前必读(2026-10-05 主控逐个数过)**:里面 **6 个有未提交改动,全是 2026-10-03 的历史遗留**。~~其中两份是 untracked、从未进过 git 的 review 报告,删掉就永久找不回~~ **【2026-10-05 12:xx 主控核实更正:这两份报告早已在 main,且与 worktree 内那份 diff 逐位一致(IDENTICAL)→ 无"永久丢失"风险,无需抢救】**:
   - `.claude/worktrees/agent-a4769bc9343c0828a/.../docs/ops/help-dblclick-review-20261003.md`
   - `.claude/worktrees/agent-ab46344df19b9c206/.../docs/ops/futures-pos-replace-review-20261003.md`
   另 4 个:`a1129d3a97dfbb24c`(改 `static-site/app.min.js`=构建产物,低风险)、`a82d3e09efe0d0523`(改 3 个 `scripts/tests/test_132_*`)、`a0b7e692af78b2ef3`(删 `docs/ops/worktree-cleanup-verify-20261003.md`)、`a54d78abfef6c90f5`(untracked 同名文件,疑与前者重复)。**处置顺序:先把上面两份 review 报告捞出来落 `docs/ops/` 并 commit,再按 §25 验过可恢复性,最后才 `git worktree remove --force`。** 本会话新开的 5 个 `docs/*-20261005` 分支已确认全部进 main,可安全删。原始任务描述:(多为已完成 agent 残留,其中 3 个 `locked`)。**危害**:占着分支会让续跑同一任务的 agent `checkout` 报 `fatal: already checked out` → 只能 cherry-pick → 分支身份漂移(见 memory `resume-same-task-reuse-branch`)。**处置**:先确认对应分支已推 origin(worktree 删掉不影响 origin 上的分支),再 `git worktree remove --force <路径>`;**按 §25 先把备份/可恢复性验证做掉再删**。

**未决/待用户拍板**:fetch_news 周日夜 SEVERE 噪音是否接受;是否启用 CF R2 Local Uploads;`rzhb_backfill` 登记漂移(云上 timer 有 19:15 槽但 `schedule_monitor.sh` 只登记 08:00)。
**✅ 已拍板并执行(2026-10-05 用户)**:老桶 `backup/` = **14 天**(定案);**用户已在「新老两桶」配好 5 条 lifecycle**:`pre-upload` 7 / `weekly` 28 / `monthly` 365 / `claude-backup` 30 / `backup` 14;`decommissioned`、`mac-backups`、`large-json` **不配**(large-json **已定案**:CF prefix 无通配符,配 `large-json/` 必误删 flat 31,673 唯一副本)。老桶 `pre-upload` 3.13 GiB 存量预计 24h 内开始被 lifecycle 清。

**最后更新**(2026-09-15 周一 16:1x):✅ **外审 review 门禁链路恢复并端到端验证通过**。背景:v1.1.17/v1.1.18 外审被跳过(门禁 retry 风暴 + claude 回传静默断链)。本轮 fix 全在 main(main==origin/main==`c457a8b09`):①`07de081ff` 外审模型钉深(deepseek-v4-pro-0813)+重试风暴根治 +`fc18cc3be` 终态 request 的 git ref 泄漏清理 ②`c7077c37f` **PIPE 满死锁根治**(spawn stdout/stderr=PIPE 却只在退出后排水,子进程写满 64KB 永久卡死→改文件重定向)③`6e2c9dc20` **claude 回传静默断链 P1**(is_already_processed 误短路 claude 队列,消费者永不 spawn→短路仅对 codex 队列)④`a56be8e04` plist 单一事实源归位 launchd/(删 scripts/ 重复 + 补齐 CLAUDE_BIN/CODEX_REVIEWER_MODEL/PYTHONUNBUFFERED)⑤`c457a8b09` claude 消费者预算 0.50→5.00(deepseek 下不够烧,exit=1)。**mini test(2 commit)全链路验证全绿**:watcher 接单→codex 外审(deepseek)→报告落盘→claude 回传 spawn→**claude 消费者回执 exit=0**→ref 清理;外审 FAIL 的 4 findings(P1/P2x2/P3)经 claude 消费者逐条复核已全部修复。
**✅ codex 缓存命中修复(2026-09-15 实测)**:根因=非默认 `disable_response_storage=true`(关服务器 response storage,炸掉 Responses API 多轮前缀缓存);改回默认 `false` 后同 2-commit 外审 token **143,207→97,995(−32%)**、无接口报错、verdict/回传/ref 链路正常,已保留(bak: `~/.codex/config.toml.bak-cachetest-20260915-162351`)。进一步候选(未做):codex base_url 改走 thinking_proxy 127.0.0.1:8899 借 cache_control,可能再提命中,但需验 bailian 兼容性。
**前序**(2026-09-12,详见 docs/archive/TASKS-handoff-20260912.md):✅ 8 项 reviewer 非阻断小项打包上线(main-merge 20260912-a585)+README 角标 2.5 语义同步 + #91 次日开盘口径核销。
**待办指针**:#108 四档升级判定源 hs300→cyb 待拍板;#174/#175 + 模块十九登记项(rzhb_backfill 登记漂移 / notify.py --dry-run 写 latest.md 瑕疵 / 架构改造 A-B 档 待事实核查)均见 docs/pending-features-index.md 模块十九(2026-10-05);v1.1.16..v1.1.18 外审补审(263 commits)待定预算/范围;codex 缓存命中优化(上);`feat/lof-path-absolute-align` 分支 ahead of origin by 2(重复 commit)待 main-merge 收尾。

## 📋 待办（2026-08-20 治理后:全移 todolist,本文件无活跃 checkbox）

> **TASKS.md 已清空活跃待办**(2026-08-20 用户「task 只留交接/大纲/必要指针,无活跃 checkbox;待办全判远期移 todolist,等有真正在做再放」)。
> - 真完成 53 条 → [docs/tasks-done-list.md](docs/tasks-done-list.md)(完成文件:43 TASKS治理 + 10 费率;待 7 天自动归档)
> - 用户关闭 3 条 → [docs/archive/TASKS-done.md](docs/archive/TASKS-done.md) 关闭记录
> - **待办/远期全在 [docs/pending-features-index.md](docs/pending-features-index.md) 模块十六**:#79 场外方案C(8步)/#80 性能P2(含 P2-11 大盘 tab SVG/**#82-89 八项归档活跃需求**/#90 场外阶段/**#91 次日开盘口径** 已核销完成(2026-09-12,详见 pending-index #91)(#101 北交所宽度/#102 FAPI转正 已 2026-09-06 完成上线,从远期移除;#81 管理端看板已于 2026-08-20 用户拍板关闭,勿再列为远期;详情 TASKS-done.md 关闭记录)
> - 待安排指针(近期):excludeSpecialBearCyb 实测,见 pending-index 对应节。**#91 次日开盘口径已核销完成(2026-09-12),勿再列待安排**。#73 8宽基四档 / #74 邮件广播hit白名单 已完成 done-list 登记(2026-08-21 同步)。
> - 后续新增真实待办(有活在做)再写回本节。

### 🆕 信号凯利全信号卡「快照+每日演进+异常告警」(2026-09-04 用户新增,源自今日 P0 异常演进事故)

> **用户需求原文**:「补一个待办,内容就是信号凯利回测全信号卡的快照,并且可以从快照看出每日演进以及告警,像今天这个问题,就属于异常演进,一定是坏了」。
> **背景/判定标准(用户给的关键认知)**:H 档收益率正常演进曲线 = **230→226→224**(前几天下跌→昨天弄好最新 224%),渐进微调=正常;**今天一下子掉几十 pp(224.92→182.25,A 163→142.68,无隔日)= 异常演进=一定是 bug**。用户并指出:维护修了那么多条、且有 230→226→224 的正常演进过程,故**「数据一直坏」不成立,今天这次一定是 bug**,不是"一天演进/数据陈旧"能解释。
> **要做的事**:①给信号凯利全信号卡(A/H 等档位收益率等关键数字)加**每日快照存档**(历史留痕)②从快照可**看出每日演进**趋势③**异常演进告警**(突变量级超阈值,如单日掉 N pp 即告警,参考 §5.1 防前视/告警门控)——像今天 224.92→182.25 这种量级必须被自动抓到并告警,不等用户发现。
> **状态**:✅ **已完成(2026-09-04 当天实施上线)**——见 docs/kelly/analysis/kelly-sigkelly-advance-20260904.md「实施」段:F 快照+演进+告警全落地(signal_kelly_snapshot.py 每日快照+index+滚动窗突变/停滞告警+lab「📈演进」入口+check_signal_accum_nav_lag 监控补盲)。09-17 做过一次演进快照断更排查(历史文件迁云未带,已补齐14点),结论=快照链正常非断更。
> **关联**:本次 P0(信号凯利全信号卡收益骤变,排查链 docs/kelly/ 待落档)。

### 🔄 AI 降亏交互重构:单开关+模式下拉7种(2026-08-23 用户拍板,前期工作,校验后再谈 NEW 设默认)

> 构想(用户确认):AI 降亏保留 **1 个总开关**,模式改**下拉 7 种**(8键[默认]/9键/A/B/C/14键/18键 全封装);**四消费点接入且互相独立**(①首页近期技术分析参考点 ②首页模拟回测弹窗·全历史真实过滤 ③分析参考点 AI 监控 ④📊 信号凯利回测 lab);顺手做**3+1 处补漏**;**方法池 57→最新全量**(新键默认关+勾选联动,交互同现有 37 小标签);新增**「AI 降亏组成对比」展示区**(7 方案各由哪些逻辑条件叠加)。默认逻辑不动,用户手动切下拉对比明细校验。
> 短标语(已核报告):8键=现役地基·稳定参照(「长线友好」已被 mine25 可操作口径证伪)|9键=8+候选1·牛市辅备买拦截|A on9=进攻王·近端牛市吃满|B on9=均衡卡·K档最钝感(**双正王名头因 g2 bug 作废**)|C on9=保守防守·熊市少亏|NEW 14键=新防守王·全史第一+回撤最浅|NEW2 18键=NEW 影子·入选差31笔。⚠️ A/B/C=叠9键口径、14/18键=重构换基座,下拉项须标口径差异。
> 版本:发 v1.1.3/v1.1.4(默认组合不动但功能面大改,§5.4⑥ 精神);v1.1.5 留给将来 NEW 设默认。

- [x] **T0/T1/T2/T3-1 已完成上 main,已登记 [docs/tasks-done-list.md](docs/tasks-done-list.md)「2026-08-28 AI 降亏交互重构完成段」**(八连 commit c54eb89a6/5a299d243/69b1a88c5/c3f214a99/e1b4440c6/c7a9bdf82/40ed3d5d9/241a89d08 核实均在 origin/main)。综述:20 键规格单源 scripts/loss_rules.py+特征 JSON+双端谓词+37 标签链+§21 公示;lab 凯利区「AI 降亏组成对比」折叠区;sim 弹窗/首页 7 模式下拉重放(默认 p8≡现网)。细节见 done-list 段。
- [x] T3-2 完成待 merge(2026-08-23,feat/t3-2-home-monitor 四连 dd27520c5→cff2fb41f→e4d49d5ab→d4622bdec):首页参考点 7 模式下拉(tds_home_fade_mode)+AI 监控卡模式下拉+**「+1」开关**(tds_overfit_fade_mode/tds_overfit_bull_stop,_ovAggregateRecent 组集+banker's rounding,老 json 无 recent 回退 bank)+第三份谓词迁移(_isBullStopHit→_tdsFadeSpecHit);playwright 冒烟 12/12 抓出绑定 bug 已修(cff2fb41f);终审揪 new18 缺键(RECENT_KEYS 漏 n2NorthOutConcept)+实施上报 FIELD 错位历史 bug(FIELD 21 列 vs schema 24 列致 by_grade 恒空,**用户拍板修**)→收尾 d4622bdec 两单点:FIELD 21→24(by_grade 三桶出数 n=3/24/222,评级类回测键 janMidRating 从静默失效转生效,连带影响已如实报用户)/n2NorthOutConcept 补打标 707 行+H 断言根治未来漏同步;reviewer 复核 **PASS**(parity 18/18+fade_predicate 115 键 diff=0);⚠️ merge 后需重跑 overfit.json 上线(监控卡过滤视图/评级维度数字会变=预期修复非回归,§22 三步跟上)
- [x] ~~UI 修复批(P0 卡死+用户四连抓)已完成待 reviewer 终审~~(2026-09-01 销账:代码已 100% 完成并并 main,P0 根修 `7ea4f8272`+批本体 merge `1cd137e70`/`839b5d283`;reviewer 终审已实质完成;common.js 组件 `_tdsFadeModeSelectHTML` 冲突经 T3-2 收尾 `44d383620` 覆盖,无待处理冲突;见 done-list「2026-09-01 遗留对账销账」段)
- [x] ~~双 merge 收尾链~~(2026-09-01 销账:①② merge 全落地——T3-2 `673ebe2ef`+适配 `44d383620`/`8811295d6` 均在 main;③overfit.json 正式重跑上线已核实——`overfit_monitor.json` generated_at 2026-08-31 21:40 含 n2NorthOutConcept/janMidRating 新键,线上 ss.fx8.store 已到新版,deploy 链 check_overfit_split_parity/recent_parity 已挂;④T4 公示+README 属常规发版收尾;⑤T5 用户手动校验为用户侧动作;见 done-list「2026-09-01 遗留对账销账」段)

### 「3+1 处补漏」定案(2026-08-23 用户拍板,并入 T3/T4)
> 用户原话:「3处已有的 +1 就是这个ai监控量化里 现在还停留在ai降亏过滤开关 没有同步前面的+1多选 这次直接对齐其他3处做 一样的交互」+ 全选三项附加。
> ① **AI 监控卡补齐**(核心 +1):分析参考点 AI 监控卡现在只有 AI 降亏过滤总开关,缺「+1」(候选1/牛市辅备买全停)开关,这次对齐其他三处做一样的交互(新模式下同步支持下拉)
> ② 三处独立化模式复用到新下拉(lab/sim弹窗/首页各自独立 key)
> ③ 公示三处+README:purpose-notes/lab tooltip/首页 badge 同步 §21/§23.6 + README 功能描述
> ④ 谓词同源债清理:同一套过滤谓词现存三份拷贝(lab/_sim/sim_core)+后端两份硬编码(queries/overfit),收敛单一来源防口径漂移
- [x] ~~T4 公示 §21 同步(purpose-notes/lab tooltip)+README §23.1+版本号 bump+reviewer 审查(依赖 T1-T3)~~ **2026-09-27 销账**:随 v1.1.5 发版完成(2026-09-01 已定性「属常规发版收尾,归常规发版」,见上方销账段)
- [x] **2026-09-27 销账:目标全达成** —— NEW14 设默认 + v1.1.5 tag(@04144b269,08-24)+ 基准锚点 memory 升级(已升至 v1.1.5 再至 v1.1.7)+ 前端默认值/§21 公示/README 四件套均已随发版联动;AUTO 择时调研结论=**不成立**,故按「不成立则 NEW14 设默认」执行。以下为原始任务描述:T5 主控验收 merge 上线 → 用户手动切换校验 → **用户验收数据通过且 NEW 14键确实如预期**才走 NEW 设默认任务:届时打 **v1.1.5 tag**(2026-08-23 用户定)+ 同步把测试基准锚点 memory(`test-baseline-v112-anchor`)升级为 v1.1.5(未来一切回测/挖掘以 v1.1.5 为前提)+ 前端默认值 + §21 公示 + README 四件套联动。**⚠️ 2026-08-23 用户新定调:AUTO 择时切换模式调研(regime-mode-rotation-research,#94 已完成,见 pending-index ★)= v1.1.5 定稿「平台主推 AI 算法基座」的最后一次努力**——成立(样本外+平稳优先效用)则 v1.1.5 基座=AUTO 方向,不成立则 NEW14 设默认;调研结论出来前 NEW 设默认暂缓执行

### 📚 本轮降亏挖掘战役 README 总结导航(2026-08-23 用户点名,收尾必做)
> 背景:mine22/23/24 全员竞赛+mine25 可操作长线+g2 门审计修正+速查卡等扩容产物多,`docs/kelly/analysis/README.md` 只有平铺逐行索引,缺总览入口。
> 做法(等长线补录+T0 报告落定后一次做全):①README 顶部加「2026-08 降亏挖掘战役总结」段:总标语+七方案(8键/9键/A/B/C/NEW14/NEW2 18键)一句话定位+权威数字源(mine24_compare.json/mine25 json)+g2 失真修正说明;②每方案给索引链:速查卡→主报告章节锚点→数据 json→复现脚本;③toggle 目录(ai-filter-mode-dropdown 调研报告)入索引。验收=从一个入口能跳到任一方案的数字/论证/脚本三层。

## 总体大纲

A 股 / 港股 / 全球盘后复盘看板。Python 3.11 + FastAPI + SQLite + ECharts，Mac 本地。当前 27 个指标、13 指数、运行在 http://localhost:8000（`--reload`，改文件自动生效，**不要杀进程**）。本轮迭代目标：修回归问题 + 补国债 / 原油白银 / 红利 / A 股十年回溯 / 买卖点优化 / 行业看板 / 概览美化。

相关文件：`REQUIREMENTS.md`（需求 + 实现状态 + §9 变更史）、`NOTES.md`（调研 + 修复史）、`05-回归测试报告.md`（本轮回归）、`01-问题清单.md`（上轮 bug）、`config/indicators.yaml`（指标注册表）、`app/`（采集 + 计算 + API）、`web/`（前端）。

> ⚠ 开工先看 `data/alerts/latest.md` 是否有未处理严重告警，有则优先排查。

## 工作约定（子进程必读）

1. **领任务**：读本文件，找第一个 `状态: pending` 且 `依赖` 已满足的任务，把状态改 `in_progress`、填 `负责人`（你的标识）。
2. **干活**：按 `描述` 做，达到 `验收标准`。改动前先读相关源码。技术细节自己定；**碰到方向性分叉不要猜——停下、在 `结果备注` 写明、汇报给监管**。
3. **写结果**：做完（或失败）后在 `结果备注` 写：改了哪些文件、做了什么、成功 / 失败、遗留问题。状态改 `done` / `failed` / `blocked`。
4. **汇报**：你的最终消息就是汇报。说清：做了什么、改了哪些文件、验收标准是否达成、有无遗留、下一步建议。
5. **环境约束**（踩过的坑）：
   - pypi / github 用清华镜像；Clash 代理 `127.0.0.1:7890` 拦截东财 → 全局 `trust_env=False`。
   - 东财 push2 / clist / 板块端点反爬封 → 用 sina 源或直爬 + `em_get` 防封（1s 节流 + 0.1-0.5s jitter + HTTPAdapter Retry 429/5xx）。
   - 手动值保护：upsert 的 `ON CONFLICT DO UPDATE` 末尾必须 `WHERE daily_metric.source != 'manual'`（防日采集覆盖手动补录）。
   - NaN 过滤：`collect_series` 里 `if v != v: continue`（`float(NaN)` 不抛异常，必须显式判）。
   - 不要 `cd` 进 compound 命令（用绝对路径）；不要 commit / push（用户没让）。
6. **验收（2026-07-06 调整）**：监管**不自己跑命令验收**（curl/grep/DB 在监管上下文费 token）。改派**验收子进程**（fresh context）跑抽查（DB/curl/复跑/语法），结论写进任务条目「验收备注」+ 向监管汇报。监管读干活汇报 + 验收汇报决定放行。review gate 任务必派验收子进程；非 review gate 可省（信任干活子进程自验）。不暂停等用户，全部完成或卡住才通知。最终用户 + 外部测试整体验收。详见记忆 `supervisor-loop-mode`。
7. **测试**：API 改动用 `curl localhost:8000/...` 验；采集改动跑 `python -m app.collector.runner`；计算改动跑 `python -m app.compute.runner`；前端改动浏览器看。

---

## 归档/远期指针（4 态/4 文件流转,不占活跃区）

> 4 态 ↔ 文件(2026-08-20 用户定):①活跃→TASKS.md ②待办/远期→docs/pending-features-index.md ③**完成→docs/tasks-done-list.md** ④归档→docs/archive/(完成态呆满 7 天自动归档)。

- **真完成(完成态,待 7 天自动归档)**：43 条 → [docs/tasks-done-list.md](docs/tasks-done-list.md)「2026-08-20 任务治理移入」段(含飞书群处理/全球指数/accum_nav 前复权/费率前端/全站性能 P0-P1/降亏组合全信号表等逐条,呆满 7 天自动移入 docs/archive/TASKS-done.md)。
- **用户关闭(移除留记录)**：3 条(NIFTY50 / 159536 track_score / avg_dev)→ [docs/archive/TASKS-done.md](docs/archive/TASKS-done.md)「2026-08-20 任务治理归档段」。
- **远期/搁置(移 pending-index 模块十六)**：场外方案C 全量化（#79,step1-8 逐条）→ 性能 P2-10/11/15（#80）→ 场外阶段2/3（#90）。（管理端看板 #81 已于 2026-08-20 用户拍板关闭,勿再列远期;旧 memory kanban-board-design 待同步为已关闭）
- **8 项被归档活跃需求(pending-index #82-89)**：留言箱完整方案 → ETF485 扩采+OHLC → 公募基金筛选器实战版 → 板块轮动 → 真pin 复盘 → PWA 体验增强 → 订阅推送 → overlap delta 可比口径。
- **早期历史归档(留反查)**：[docs/archive/TASKS-history-archive-20260820.md](docs/archive/TASKS-history-archive-20260820.md)（07-21~08-16 旧交接/旧需求章节）+ [docs/archive/TASKS-done.md](docs/archive/TASKS-done.md)（07-06~07-20 交接 + 22 任务全 done + 综合AI风险预警）。

---
## 2026-09-03 Codex Watcher 修复（by Codex）

**问题**：7x24 自动外审链路断，原因两层：
1. `codex exec` 在 launchd 子进程中被 macOS 沙盒 App Sandbox 阻止（exit=127: `env: node: No such file or directory`）
2. `report_is_fresh()` 用错误的 mtime 方向检查（报告 mtime 永远 ≤ signaled_at，正确性必然误判）
3. claim 类型没有 review schema 的 `issues`/`impact_surface` 字段，但代码对所有类型强校验这两个字段

**修复**（已部署生效）：
- `call_openrouter_codex()` 直调 OpenRouter HTTP API，绕过 `codex exec`
- `report_is_fresh()` 去掉 mtime 检查，改为 `request_id` + `verdict` schema 验证
- `HEARTBEAT_PATH` → `/tmp/agent_inbox_watcher.heartbeat`
- plist log 路径 → `/tmp/codex-reports/agent-inbox-launchd.log`
- plist 重命名 `com.trade.codex-watcher`，替换旧的 `com.trade.agent-inbox-watcher`
- launchd PID 31774 已在运行（21:20 重启）

**git commit 准备**（沙盒写锁无法完成，待 Claude Code 用 merge 流程处理）：
- `scripts/agent_inbox_watcher.py` (141+ 行修改)
- `scripts/com.trade.codex-watcher.plist` (新 plist)
- `scripts/install-codex-watcher-launchd.sh` (日志路径修正)
- `scripts/com.trade.agent-inbox.plist` (删除)

**pending 外审信号**（CLAUDE 回消费）:
- `rev-20260903-001.done` → v1.1.14 review, PASS，schema 已补全 issues+impact_surface
- `claim-20260903-001.done` → 孤儿文件认领 PASS，所有文件确认归属或不存在
