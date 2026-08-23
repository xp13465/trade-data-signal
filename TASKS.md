# TASKS.md - 情绪看板迭代任务清单（监管 + loop 工作模式）

> 这是「监管 + loop」工作模式的唯一共享任务文件。子进程开工前**必读本文件** + `REQUIREMENTS.md`（需求真实来源）+ `NOTES.md`（调研笔记）。监管（主进程）不直接干活，派子进程领任务循环。

> **历史已完成/关闭/远期项已按 2026-08-20 任务治理归档(4 态/4 文件流转,非删)**:①真完成 → [docs/tasks-done-list.md](docs/tasks-done-list.md)(**完成文件**,53 条标注完成态 = 43 TASKS治理 + 10 费率改造;呆满 7 天自动归档到 docs/archive/TASKS-done.md)②用户关闭 → [docs/archive/TASKS-done.md](docs/archive/TASKS-done.md)「2026-08-20 任务治理归档段」留关闭记录;③早期历史交接/旧需求 → [docs/archive/TASKS-history-archive-20260820.md](docs/archive/TASKS-history-archive-20260820.md);④远期/搁置待办(场外方案C/性能P2/管理端看板/场外阶段) + 8 项被归档的活跃需求(留言箱/ETF485扩采/公募筛选器/板块轮动/真pin/PWA/订阅推送/overlap delta) → [docs/pending-features-index.md](docs/pending-features-index.md) **模块十六 #79-90**,用户要远期明说再捞回。**本文件只留活跃待办 + 大纲 + 工作约定 + 最新交接**。治理报告:docs/tasks-active-only-clean-20260820.md。前序瘦身归档指针见 [docs/archive/TASKS-done.md](docs/archive/TASKS-done.md)。

## 📍 当前会话状态（compact 恢复用,每次状态变化后 Edit 更新）

> compact 后第一动作:读本小节恢复 transient 状态(活跃 agent/cron/commit 链/正在等什么)。详见 memory `compact-recovery-checklist`。

**最后更新**:2026-08-22 深夜(降亏挖掘三轮+组合竞赛批次).本轮:
- **✅ 候选1「牛市·主升×辅备买全停」上线 a388**(第9键,默认关+NEW红标,sim弹窗/技术参考点同链开关);**开关三处独立化 a389**(e471f7fc8):lab=state-only刷新回默认/sim弹窗=UI态每次打开默认关/首页=独立键 `tds_home_bull_aux_backup_stop`,旧共享键全站零残留,diff 零谓词行(过滤行为未动)。
- **✅ 二轮+三轮挖掘全量落档 main(76a7b2b20)**:round2=22方法调研档案+25特征~4700规则全补位口径+扩容盘点18候选(11入池/7落池定性)+2047穷举+帕累托40非劣(mine10-21);round3=替补盲区地图+R2三键(buy×concept/special×global/low×Q3×ts<75)四重检验全过组合vs9键+28,515+2026年2-3月画像(与替补同源,R2后3月转正/2月改善27%)+主亏月Top20聚类(Q3×concept=-17,061恰为R2g射程)(mine12-17)。
- **✅ mine22 联合穷举+mine23 五项目对比+mine24 全员竞赛全部落档上 main(a7208e526,2026-08-23 凌晨按用户「push出去我看」提前 merge)**:mine22 新王 T1+Q1+M1+V1+R1+R2a+R2b+R2g=+46,007(vs9键);mine23 §15.11 五项目全维大表(基座对照:A叠9好/C叠8好应下线候选1/B不敏感);mine24 §15.12 57条全员竞赛搜出**14键新王牌 net+122,648/mdd-4,178 双指标支配 A**(弃候选1/excludeSpecialBear/r7/V1/R1/R2g 等,新增 r10May6NonMay/declinePhaseSpecial+N1/D1/H1/P1)。A/B/C 与新王牌均为回测理论值,**待用户按 §15.11 表逐格校验后拍板是否做成开关实测**。
- **✅ openrouter 三件处置完成(2026-08-23 凌晨,用户拍板后落地;报告 docs/openrouter-cost-opt-research-20260823.md 已纠偏 05f574c91)**:①**WebSearch 全局 deny**(根因纠偏=走 OpenRouter 时 WebSearch 是 server tool 按次计费,实际账单证伪"客户端独立"旧结论;调研改 WebFetch+curl 免费通路)②**安全项**:AUTH_TOKEN 存 macOS keychain(service=claude-code-openrouter,zshrc 取值),settings.json 明文已删+补 `ANTHROPIC_API_KEY:""` 占位;key 轮换待用户在 OR 页面操作(只更新 keychain 一处)③**CLAUDE_EFFORT high→max**(用户计次制下升智力,代价=变慢;implementer/tester frontmatter 钉 effort:medium 防拖慢执行类)。**重启会话生效;401 回滚=token 加回 settings.json;太慢降回 high**。后续观察:Activity 页 cached_tokens 基线/effort max 速度感受。
- **📌 本轮关键教训已固化 memory**:补位口径铁律(filter-backtest-position-fill-caliber);证伪存档=激进版牛主升全停-11,884/波动≥25%-8,636 均删笔口径幻觉,候选C下降期×备买补位反转-2,485 降级不支持,N1系被R2系全面取代(近端互斥)。

**前次更新**:2026-08-22(周末清账批次收官).本轮:
- **✅ 首页「模拟回测」弹窗上线+三轮迭代(a377→a385)**:全历史真实过滤+费后盈亏累积 13 列表;迭代=13列定宽+hover持仓格→ETF联动高亮+四列红正绿负(a383)→累积盈亏口径修正=÷(峰值持仓笔数×¥10000)+tooltip三档1:1公式(a385)→费率6档快捷+持仓中预估浮盈(b13d93592);§0 三站验证过。
- **✅ P2-11 大盘 tab 懒渲染上线(a384,e01de0423→af0fc35d6)**:IntersectionObserver+懒代理,首帧 canvas 23→5/长任务59ms→0/像素diff≈0;评审加固修切皮肤×懒加载交叉丢主题色时序 bug。遗留:板块分化 subtab spark 格 753ms 同根因待拍板。
- **✅ P2-15 offshore 定时链停用(4289d50a7)/ #82 留言箱收官(worker Resend 邮件通知+QQ实收验证)/ todolist 全量治理(20ab5ab9d,8关+2废+1留+#10刷新)** —— 详见 done-list 对应段。
- **✅ #95 ETF权重龙头回测完结(结论=无实际价值不推荐,维持 v1.1.3)**:A(买ETF)全面优于 B1/B2,B3 持平需3倍操作量;done-list「2026-08-21 回测结论落档」段+docs/kelly/backtest-ai/etf-weight-leader/。
- **⏳ 待用户拍板**:①板块分化 subtab spark 格懒渲染排不排(同 P2-11 根因)②main-merge.sh 销账提醒软提示(commit 含 #NN 时提醒顺手销账 pending)③#88 订阅推送启动时点(手中活清完后评估)。#10 ETF弹窗长历史阻塞解除可直派未启动。
- **🔍 opencode 端点调研落档(2026-08-21)**:两份报告 `docs/thinking-off-opencodego-research-20260821.md`:关思考不可用(cc-switch 丢弃 thinking 参数);缓存命中率差主因=主会话上下文抖动(提命中=/clear 固化前缀+长输出落盘+子agent只回结论)。→ memory `opencode-cache-think-findings`
- **✅ 状态同步 commit a40b21507(2026-08-21)**:done-list 补登记 9 条做了未标(#65/66/67/70/71/72/62/51/56)+ pending-index 同步 9 处 + TASKS 待安排移除 #73/#74。已 push main。
- **📌 #78 TASKS.md 任务治理已实施合并(2026-08-20)**:researcher 全量盘(aade4fd)核 47 个 `[x]` = 43 真完成 + 3 用户拍板关闭(L59 NIFTY50 / L68 159536 track_score / L77 avg_dev) + 1 误标待办(L42 SVG P1,剩大盘 tab P2-11 未做,改回 active)。处置:43 完成 + 3 关闭归档 TASKS-done.md「任务治理段」;L42 改回 `[ ]`;远期/搁置 11 条(场外方案C 8步/性能P2 3条)移 pending-index 模块十六;8 项归档活跃需求补登记 #82-89。报告 docs/tasks-active-only-clean-20260820.md。
- **📌 #18 费率修正(2026-08-20 用户「完成就按完成的走」)**:原留本站的 **10 条费率待办逐条实测均已实现**(费率改造 #13/14/18/22 早已上线)——印花税simulate_trade.py:57/stamp_tax 0.0005、过户费3模式:58-59+_transfer_applies、抽核心fee_config:45+_normalize_fee_config、修bug:40、对比函数app.js feeCompare、API路由app/main.py:586、全量重生+线上R2 trade_sim_hs300_stats.json(generated_at 08-19)含fee_config、验证线上含印花税已curl → **全部移入完成文件 docs/tasks-done-list.md**(完成文件 43→53)。
- **📌 待办清零(2026-08-20 用户「task 剩的待办全判远期移 todolist,不留活跃」)**:原留本站的次日开盘 + SVG 大盘 tab 两条 `[ ]` 也判远期 → 移入 pending-index 模块十六 **#91 次日开盘 / #92 SVG 大盘 tab**。**TASKS.md 活跃 checkbox = 0**,当前无活跃待办,后续有真正在做再放回。
- **📌 系统复核 v1.1.2→main 回测宇宙/推荐算法/信号口径(2026-08-20)**:reviewer 审逻辑 + tester Playwright 验线上两路全 PASS(默认组合8键+1类零改动/宇宙规则1:1/首页技术参考信号vs凯利回测同源/线上badge渲染正确)。**v1.1.3 tag 已打已 push**(8cb60a5a7,版本链 v1.0.0→v1.1.3 五连齐)。存量观察项=首页 AI建议N 无 `tds_poscap` key 时(首次访问)不显示,非回归,登记待办。
- **📌 pending-index 归位(2026-08-20,#30)**:researcher 全量盘 92 条→ implementer 归位 **done 37 条**(docs/tasks-done-list.md,带 commit 实证)/ **archive 3 条**(#23 飞书阶段3 + #33/#81 管理端看板)/ **远期 50 条全保留零丢失**,刷新 5 条过时状态列 + 处理 5 组重复登记,feat `docs-tasks-4state-tidy`@9eb250568 main-merge 上线。
- **📌 归档/移出说明**:📍当前会话状态的历史交接轮次(L22-34 的 #69/excludeSpecialBearCyb 上线、818-fix、四档收窄、并行降级安全B、代理切官方等完成陈述)已精简,关键待办提炼到下方"待安排";细节可反查 TASKS-done.md 或对应 commit。
- **⏳ 待安排/待办(即时)**:①用户实测凯利区 excludeSpecialBearCyb 开关(数据/开关/公示已就绪,公示写「收益待用户实测」)②次日开盘口径待用户确认是否切默认(#91)。**2026-08-21 状态同步**:原列 #73 8宽基四档 / #74 邮件广播hit白名单 均已核已完成(commit 7872cccbf@main / 41105d6a8@main),done-list 已登记(L107/108),从待安排移除。
- **📋 活跃待办计数**:0 条 checkbox(**已全移 todolist/pending-index**,本文件无活跃待办;次日后台+SVG 大盘 tab 在 pending #91/#92),详见下方「待办」。
- **📋 备注**:claude-work-mode/README.md、static-site/about.html/guide.html/privacy.html 有预先存在本地改动(非本任务,未 add 未 commit)。

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

- [ ] T0 调研:四消费点现状盘点+7套数据来源定案(后端预计算 vs 前端重放)+3+1 补漏清单对账+方法池/新键对账(researcher 进行中,报告→docs/kelly/toggle/)
- [ ] T1 方法池 57→最新全量:新键标签+默认关+勾选联动(implementer,依赖 T0)
- [ ] T2 「AI 降亏组成对比」展示区+七模式短标语落位(implementer,依赖 T1)
- [ ] T3 交互主体:单开关+模式下拉 7 种+四消费点接入+3+1 补漏(implementer worktree 隔离,依赖 T0 定案)
- [ ] T4 公示 §21 同步(purpose-notes/lab tooltip)+README §23.1+版本号 bump+reviewer 审查(依赖 T1-T3)
- [ ] T5 主控验收 merge 上线 → 用户手动切换校验 → 校验满意另立 NEW 设默认任务

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
