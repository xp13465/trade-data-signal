# TASKS.md - 情绪看板迭代任务清单（监管 + loop 工作模式）

> 这是「监管 + loop」工作模式的唯一共享任务文件。子进程开工前**必读本文件** + `REQUIREMENTS.md`（需求真实来源）+ `NOTES.md`（调研笔记）。监管（主进程）不直接干活，派子进程领任务循环。

> **历史已完成/关闭/远期项已按 2026-08-20 任务治理归档(4 态/4 文件流转,非删)**:①真完成 → [docs/tasks-done-list.md](docs/tasks-done-list.md)(**完成文件**,53 条标注完成态 = 43 TASKS治理 + 10 费率改造;呆满 7 天自动归档到 docs/archive/TASKS-done.md)②用户关闭 → [docs/archive/TASKS-done.md](docs/archive/TASKS-done.md)「2026-08-20 任务治理归档段」留关闭记录;③早期历史交接/旧需求 → [docs/archive/TASKS-history-archive-20260820.md](docs/archive/TASKS-history-archive-20260820.md);④远期/搁置待办(场外方案C/性能P2/管理端看板/场外阶段) + 8 项被归档的活跃需求(留言箱/ETF485扩采/公募筛选器/板块轮动/真pin/PWA/订阅推送/overlap delta) → [docs/pending-features-index.md](docs/pending-features-index.md) **模块十六 #79-90**,用户要远期明说再捞回。**本文件只留活跃待办 + 大纲 + 工作约定 + 最新交接**。治理报告:docs/tasks-active-only-clean-20260820.md。前序瘦身归档指针见 [docs/archive/TASKS-done.md](docs/archive/TASKS-done.md)。

## 📍 当前会话状态（compact 恢复用,每次状态变化后 Edit 更新）

> compact 后第一动作:读本小节恢复 transient 状态(活跃 agent/cron/commit 链/正在等什么)。详见 memory `compact-recovery-checklist`。

**最后更新**:2026-09-01 13:4x(今日三条开发线收口 + 会话落档整理,§23.12 4态流转).本轮:
- **✅ 商汤代理 400/429 修复 + 日志裁剪**(→main **4e92cb3ef**/**3dd5b21c1**)— 修 thinking.type=adaptive+嵌套budget>1024 的 400(CLAMP 到 1024,probe 32768→400/1024→200);429 单key分层冷却(level0→30min/≥1→1h/上限5×1h,quota vs tpm/rpm 区分,4key 独立配额);日志超20MB 留尾截断10MB。代理重启加载新代码(PID 83100)。⚠️ 经验:该服务是 scripts/ plist + `launchctl load` 模式,非 bootstrap 到 ~/Library/LaunchAgents(bootout+bootstrap 会误停,bootout 后须用 load 恢复)
- **✅ AI 方向锚回测 5.1+5.2**(→main **00fad6654**/**2b26ac690**)— 5.1 全历史 642 样本:押方向 dir_win=0.5103≈随机;5.2 穷举子群全无一 |z|>=1.96 显著,阈值不翻天,无过拟合 → **方向锚自身无显著方向优势**。落档 docs/ai-predict/ai-predict-backtest-feasibility-20260831.md
- **✅ B方案:方向锚「开锚vs关锚」7日线上A/B**(→main **fe9ae452f**,feat/ab-direction-anchor-7d-ab)— 因 5.1/5.2 锚自身无优势但 8-28 开启注入依据=3样本前测,搭双通道严格验证注入帮不帮 AI:生产照旧(带锚20:40)+关锚参考(21:15 单prompt,唯一变量=注入),7真实交易日对比命中率定去留。脚本 ab_direction_anchor.py(幂等/7日停/交易日判断/只读零侵入)+launchd com.trade.ab-direction-anchor 21:15。⚠️ merge 赶在 21:15 前让 launchd 指向的脚本路径落 main
- **✅ Karpathy review 规则(放宽版)采纳**(→main **33c9c90ee**,feat/karpathy-review-rules)— codex 评估 andrej-karpathy-skills:不直接用不蒸馏,提 2 条 per-finding 规则(trace/verifier);主控校验 codex("无测试套件"过头/落地点应扩双 reviewer skill §23.3),用户拍板采纳放宽版(user_request 可 N/A+reviewer_own 不压没主动发现;verifier 回测/口径类可降级"口径依据"),落 5 文件(protocol+.agents codex-reviewer+role-reviewer+2 同内容副本)。评估落档 docs/codex-reviews/karpathy-skills-evaluation-20260901.md。**2周试运行(9-01~9-15)+4指标验证再定正式版**
- **✅ 落档外部系统先查社区教训 L47**(→main **e7f789c2a**)— 用户批评闭门造车,§5.1 强化触发词+§18①加行+archive+memory
- **🔄 B方案 A/B 7日累积进行中**:每日 21:15 自动跑,满 7 真实交易日(约2周)出两通道命中率对比表,数据定方向锚去留
- **🔄 Karpathy review 规则 2周试运行进行中**:至 9-15,用 4 指标(有效finding率/模糊finding数/误报率/被压没主动发现)评估是否正式固化
- **遗留(非本轮)**:旧 worktree 残留 11 个(agent-inbox-rev-*)下轮清理;UI 修复批 reviewer 终审+双 merge 链/kelly-lab P1 未动;zcode 等用户派活
**历史交接(≥2 轮前,已折叠)**:09-01 00:4x ZCode 代班轮(淘汰原因列 a522/sim-pin/zcode 角色/codex ref 链审计/v1.1.12 tag) + 08-31 compact 收尾链 + 08-30/08-29/08-28/08-27/08-26/08-22 及更早全部折叠,细节见 docs/tasks-done-list.md「2026-09-01 会话追加 1/2/3」与 docs/archive/TASKS-done.md / TASKS-history-archive-20260820.md。已上main的完成陈述不再在顶部重复陈列。
> **历史未决项清理(2026-08-28 主控核查,全已过时/已修复)**:①板块spark懒渲染=P2-11性能优化,非功能bug → 关闭②main-merge.sh销账提醒=Nice-to-have,从未阻塞 → 关闭③#88订阅推送=已完结销号 → 关闭④v1.1.7审计P1项=全已修复上main → 关闭⑤汪汪队stats等=大部分自愈,仅余宽度指标缺口(37天滞后)为独立数据问题 → 关闭,宽度缺口见data/alerts/latest.md 06-27条⑥首页AI建议N首次=真实残留小茬,但仅影响首次访问展示,不伤核心 → 暂时关闭,下轮顺手修。overfit.json 404=正常状态(下线,前端读overfit_monitor.json),不修。**🔥 信号凯利回测 lab tab 首屏加载 P1**(implementer ac359715ca0 修复中,feat/kelly-lab-lazy-load):裸 fetch 拉 69MB 全量,无分片/超时/缓存;修复=分片+骨架屏+localStorage 缓存三件套(recent.json 2.99MB 首开,按年 t{YYYY}.json 按需)

## 📋 待办（2026-08-20 治理后:全移 todolist,本文件无活跃 checkbox）

> **TASKS.md 已清空活跃待办**(2026-08-20 用户「task 只留交接/大纲/必要指针,无活跃 checkbox;待办全判远期移 todolist,等有真正在做再放」)。
> - 真完成 53 条 → [docs/tasks-done-list.md](docs/tasks-done-list.md)(完成文件:43 TASKS治理 + 10 费率;待 7 天自动归档)
> - 用户关闭 3 条 → [docs/archive/TASKS-done.md](docs/archive/TASKS-done.md) 关闭记录
> - **待办/远期全在 [docs/pending-features-index.md](docs/pending-features-index.md) 模块十六**:#79 场外方案C(8步)/#80 性能P2/#81 管理端看板/#82-89 八项归档活跃需求/#90 场外阶段/**#91 次日开盘口径**/**#92 SVG 大盘 tab P2-11**
> - 待安排指针(近期):excludeSpecialBearCyb 实测 / 次日开盘口径(#91),见 pending-index 对应节。#73 8宽基四档 / #74 邮件广播hit白名单 已完成 done-list 登记(2026-08-21 同步)。
> - 后续新增真实待办(有活在做)再写回本节。

### 🔄 AI 降亏交互重构:单开关+模式下拉7种(2026-08-23 用户拍板,前期工作,校验后再谈 NEW 设默认)

> 构想(用户确认):AI 降亏保留 **1 个总开关**,模式改**下拉 7 种**(8键[默认]/9键/A/B/C/14键/18键 全封装);**四消费点接入且互相独立**(①首页近期技术分析参考点 ②首页模拟回测弹窗·全历史真实过滤 ③分析参考点 AI 监控 ④📊 信号凯利回测 lab);顺手做**3+1 处补漏**;**方法池 57→最新全量**(新键默认关+勾选联动,交互同现有 37 小标签);新增**「AI 降亏组成对比」展示区**(7 方案各由哪些逻辑条件叠加)。默认逻辑不动,用户手动切下拉对比明细校验。
> 短标语(已核报告):8键=现役地基·稳定参照(「长线友好」已被 mine25 可操作口径证伪)|9键=8+候选1·牛市辅备买拦截|A on9=进攻王·近端牛市吃满|B on9=均衡卡·K档最钝感(**双正王名头因 g2 bug 作废**)|C on9=保守防守·熊市少亏|NEW 14键=新防守王·全史第一+回撤最浅|NEW2 18键=NEW 影子·入选差31笔。⚠️ A/B/C=叠9键口径、14/18键=重构换基座,下拉项须标口径差异。
> 版本:发 v1.1.3/v1.1.4(默认组合不动但功能面大改,§5.4⑥ 精神);v1.1.5 留给将来 NEW 设默认。

- [x] **T0/T1/T2/T3-1 已完成上 main,已登记 [docs/tasks-done-list.md](docs/tasks-done-list.md)「2026-08-28 AI 降亏交互重构完成段」**(八连 commit c54eb89a6/5a299d243/69b1a88c5/c3f214a99/e1b4440c6/c7a9bdf82/40ed3d5d9/241a89d08 核实均在 origin/main)。综述:20 键规格单源 scripts/loss_rules.py+特征 JSON+双端谓词+37 标签链+§21 公示;lab 凯利区「AI 降亏组成对比」折叠区;sim 弹窗/首页 7 模式下拉重放(默认 p8≡现网)。细节见 done-list 段。
- [x] T3-2 完成待 merge(2026-08-23,feat/t3-2-home-monitor 四连 dd27520c5→cff2fb41f→e4d49d5ab→d4622bdec):首页参考点 7 模式下拉(tds_home_fade_mode)+AI 监控卡模式下拉+**「+1」开关**(tds_overfit_fade_mode/tds_overfit_bull_stop,_ovAggregateRecent 组集+banker's rounding,老 json 无 recent 回退 bank)+第三份谓词迁移(_isBullStopHit→_tdsFadeSpecHit);playwright 冒烟 12/12 抓出绑定 bug 已修(cff2fb41f);终审揪 new18 缺键(RECENT_KEYS 漏 n2NorthOutConcept)+实施上报 FIELD 错位历史 bug(FIELD 21 列 vs schema 24 列致 by_grade 恒空,**用户拍板修**)→收尾 d4622bdec 两单点:FIELD 21→24(by_grade 三桶出数 n=3/24/222,评级类回测键 janMidRating 从静默失效转生效,连带影响已如实报用户)/n2NorthOutConcept 补打标 707 行+H 断言根治未来漏同步;reviewer 复核 **PASS**(parity 18/18+fade_predicate 115 键 diff=0);⚠️ merge 后需重跑 overfit.json 上线(监控卡过滤视图/评级维度数字会变=预期修复非回归,§22 三步跟上)
- [ ] UI 修复批(P0 卡死+用户四连抓)已完成待 reviewer 终审(feat/ui-fade-mode-fix@129c53e87):卡死根因=_ensureSimLossFeat().then() 缺就绪判断致微任务链无限自递归饿死主线程,修=跃迁合批补渲一次+_simRender busy/pending 合批+sim 池按 mode 缓存+特征未就绪⏳降级;实测 lab 最大长任务 988ms→0/超200ms 8次→0/sim 快切 frozen 5003ms→1ms;删 sim 弹窗旧两控件(用户授权 §23.7,p9 预设携带 bullAuxBackupStop 语义无损)/lab 下拉与「AI降亏过滤」同行(dy 28px→0)/统一下拉组件 common.js _tdsFadeModeSelectHTML/Mount+CSS 公共段;playwright verify_fade_mode_ui.mjs 9/9+截图;parity 复跑键数115 diff=0
- [ ] 双 merge 收尾链:①UI 批 reviewer PASS→main-merge.sh feat/ui-fade-mode-fix(P0 先上)②T3-2 按 UI 批适配清单 rebase/适配(common.js 组件签名调用点 ~L2111/L2672/style.css ~6993 区段 hunk/purpose-notes 段)→main-merge.sh③overfit.json 正式重跑上线④T4 公示 §21 终验+README §23.1+版本号 bump+「降亏挖掘战役 README 总结导航」段⑤T5 用户手动校验

### 「3+1 处补漏」定案(2026-08-23 用户拍板,并入 T3/T4)
> 用户原话:「3处已有的 +1 就是这个ai监控量化里 现在还停留在ai降亏过滤开关 没有同步前面的+1多选 这次直接对齐其他3处做 一样的交互」+ 全选三项附加。
> ① **AI 监控卡补齐**(核心 +1):分析参考点 AI 监控卡现在只有 AI 降亏过滤总开关,缺「+1」(候选1/牛市辅备买全停)开关,这次对齐其他三处做一样的交互(新模式下同步支持下拉)
> ② 三处独立化模式复用到新下拉(lab/sim弹窗/首页各自独立 key)
> ③ 公示三处+README:purpose-notes/lab tooltip/首页 badge 同步 §21/§23.6 + README 功能描述
> ④ 谓词同源债清理:同一套过滤谓词现存三份拷贝(lab/_sim/sim_core)+后端两份硬编码(queries/overfit),收敛单一来源防口径漂移
- [ ] T4 公示 §21 同步(purpose-notes/lab tooltip)+README §23.1+版本号 bump+reviewer 审查(依赖 T1-T3)
- [ ] T5 主控验收 merge 上线 → 用户手动切换校验 → **用户验收数据通过且 NEW 14键确实如预期**才走 NEW 设默认任务:届时打 **v1.1.5 tag**(2026-08-23 用户定)+ 同步把测试基准锚点 memory(`test-baseline-v112-anchor`)升级为 v1.1.5(未来一切回测/挖掘以 v1.1.5 为前提)+ 前端默认值 + §21 公示 + README 四件套联动。**⚠️ 2026-08-23 用户新定调:AUTO 择时切换模式调研(regime-mode-rotation-research,pending #94)= v1.1.5 定稿「平台主推 AI 算法基座」的最后一次努力**——成立(样本外+平稳优先效用)则 v1.1.5 基座=AUTO 方向,不成立则 NEW14 设默认;调研结论出来前 NEW 设默认暂缓执行

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
- **远期/搁置(移 pending-index 模块十六)**：场外方案C 全量化（#79,step1-8 逐条）→ 性能 P2-10/11/15（#80）→ 管理端看板 kanban（#81）→ 场外阶段2/3（#90）。
- **8 项被归档活跃需求(pending-index #82-89)**：留言箱完整方案 → ETF485 扩采+OHLC → 公募基金筛选器实战版 → 板块轮动 → 真pin 复盘 → PWA 体验增强 → 订阅推送 → overlap delta 可比口径。
- **早期历史归档(留反查)**：[docs/archive/TASKS-history-archive-20260820.md](docs/archive/TASKS-history-archive-20260820.md)（07-21~08-16 旧交接/旧需求章节）+ [docs/archive/TASKS-done.md](docs/archive/TASKS-done.md)（07-06~07-20 交接 + 22 任务全 done + 综合AI风险预警）。
