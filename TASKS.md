# TASKS.md - 情绪看板迭代任务清单（监管 + loop 工作模式）

> 这是「监管 + loop」工作模式的唯一共享任务文件。子进程开工前**必读本文件** + `REQUIREMENTS.md`（需求真实来源）+ `NOTES.md`（调研笔记）。监管（主进程）不直接干活，派子进程领任务循环。

> **历史已完成/关闭/远期项已按 2026-08-20 任务治理归档(4 态/4 文件流转,非删)**:①真完成 → [docs/tasks-done-list.md](docs/tasks-done-list.md)(**完成文件**,53 条标注完成态 = 43 TASKS治理 + 10 费率改造;呆满 7 天自动归档到 docs/archive/TASKS-done.md)②用户关闭 → [docs/archive/TASKS-done.md](docs/archive/TASKS-done.md)「2026-08-20 任务治理归档段」留关闭记录;③早期历史交接/旧需求 → [docs/archive/TASKS-history-archive-20260820.md](docs/archive/TASKS-history-archive-20260820.md);④远期/搁置待办(场外方案C/性能P2/管理端看板/场外阶段) + 8 项被归档的活跃需求(留言箱/ETF485扩采/公募筛选器/板块轮动/真pin/PWA/订阅推送/overlap delta) → [docs/pending-features-index.md](docs/pending-features-index.md) **模块十六 #79-90**,用户要远期明说再捞回。**本文件只留活跃待办 + 大纲 + 工作约定 + 最新交接**。治理报告:docs/tasks-active-only-clean-20260820.md。前序瘦身归档指针见 [docs/archive/TASKS-done.md](docs/archive/TASKS-done.md)。

## 📍 当前会话状态（compact 恢复用,每次状态变化后 Edit 更新）

> compact 后第一动作:读本小节恢复 transient 状态(活跃 agent/cron/commit 链/正在等什么)。详见 memory `compact-recovery-checklist`。

**最后更新**:2026-08-27 23:45(v1.1.7 收官:全批次上线+a466+双闸自愈闭环).本轮:
- **✅ 全部批次上线**:七支(见下块)→ 韧性批+fundnav 止血 ea670309e → severe 扩面 012ee47f21 → xcount 五处对齐 703076de3(**a466**,sw v6 统一 bump,A/B 双检 PASS)。23:38 public_fund_full deploy rc=0 = §24⑤+§23.6 双闸自愈闭环(sw_801030 修复 49a644d21 生效)。
- **✅ X计数五处对齐上线**:内审 PASS 零必修+F1/F2 追加批 81d99fcef(前缀「K1终审」→「当日认可」+冒烟 S6 逐条比对);主推=当日票数最多唯一支(平票取跟踪分高)。**待办:明天 tester 跑 xcount-consensus-smoke.js 上线冒烟**(需 HEAD 新源 build_min)。
- **✅ H档卖法拍板维持现状**(用户两轮拍板;首报误标"现役默认NEW14+1"已纠正,实际默认=S06);PK 产物 cc/+h-ext/+codex 壳(445B 无数字待其补卷)落档;价源残差 ~+9.7元/笔(raw 高估 8%~40%,adjusted 权威)入 memory。
- **✅ codex 三报告消化(§23.14 参考性质)**:001 共识票/008 fundnav 止血=PASS 追认;002 FAIL 4问题(假经理名 P1/重采风暴 P1/2×P2)→ **#14 明天 researcher 核实后修**。
- **✅ fundfull 虚惊结案**(22:00 链零故障,exit1=防白屏闸正确拦)+ **#6 场外走势图实证已完成销账**(8-25 落地,线上实证)+ **#10 韧性批标完成**(T4 东财拍板落地)。
- **📋 新观察项待拍板**:①update_all 吞 deploy 退出码(launchctl 永远全绿)②pipeline 直传 R2 绕 deploy 闸(§22 一致性窗口)③汪汪队 schedule_stats exit=2 与实链 rc=0 错位 ④FRESH_MSG 秒级时间戳致 SEVERE dedup key 漂移(多发不漏发)⑤deploy_1120.log 214B 待查。另:公募 4 问题见 #14;#103-105 已登记 pending-index 等用户启动。
- **⏳ 明天**:#14 公募核实修 + stock_daily 补采(~1.5h 盘前)+ xcount 上线冒烟 + 验 GH Actions 发 a466 + codex PK 补卷合表。

**前次更新**:2026-08-27 午前(v1.1.7 前端三bug修复+审计).本轮:
- **✅ S06 AI降亏灰标不生效修复(a274d3ffb)**:app.js:5047 降亏 badge 判定用 `_aiOnMembers[fk]`（S06 下永远空）→ 改用 `_tdsS06FiltersForDate(it.date)` 按日期取基座键集。重渲染机制(tds-s06-state-ready)确保首次加载后灰标生效。
- **✅ TDZ "Cannot access before initialization" 根治(三连修)**:`_isDayFull` 函数在 let 变量声明前被调用→删除独立函数 inline 到 filter；groups/dates 移到 posCap 前。
- **✅ 「仅显示可用信号」Step2 当日已满过滤失效(e54eeb565)**:根因=`_posCapKeptMap` 存对象引用，多次 re-render 创建新对象→`.has()` 引用比较永远 false。修复=全部 key 化（`index_id|date|signal`），6 处消费点统一改 key 比较。
- **✅ S06 默认切站(fb13dbde8)**:`_KELLY_FADE_DEFAULT_MODE` 改 s06，new14 去(默认)标注。
- **✅ v1.1.7 审计追踪表已产出**(用户整理，含 3 个 P1/4 个 P2/1 个 P3 待排期)。
- **⏳ 待排期**:P1-1 X/Y 共识 fail-open 契约不一致；P1-2 X 共识快照未就绪 fail-closed；P1-3 北向增量截断丢日；P2 公募 UPSERT 竞态×3+checkpoint。

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

- [x] T0 调研完成(2026-08-23,报告 docs/kelly/toggle/ai-mode-dropdown-research-20260823.md):四消费点=①首页参考点③AI监控卡沿**后端预计算**延伸(queries.py `_ai_macro_hit_filters` L764/overfit bank),②sim弹窗④lab 沿**前端重放**延伸;三处独立化已就绪(a389)沿用。⚠️ **5 套模式(A/B/C/NEW14/NEW18)规则键在生产前后端零实现**:20 条新谓词需 Python+JS 双实现,15 条依赖特征数据通道(mine10_features 12 特征,gzip~300KB R2 懒加载)+分位阈值快照固化;9键零成本现成。
- [x] T1 完成并上 main(2026-08-23,feat/ai-loss-keys-20 c54eb89a6→merge 5a299d243 + 收尾 feat/t1-followup→69b1a88c5):20 键规格单源 scripts/loss_rules.py RULE_SPECS+特征 JSON(kelly_loss_features.json 已上线 R2+主站 curl 200)+双端谓词(lab/app)+37 标签链扩展+§21 公示+check_data_integrity 兜底断言;reviewer PASS 零阻断;一致性抽查 89,100 判定 0 不一致、默认行为零漂移
- [x] T2 完成并上 main(2026-08-23,c3f214a99→merge e1b4440c6):lab 凯利区新增「🧩 AI 降亏组成对比」折叠区(默认收起+展开态持久化),7 方案卡=短标语+口径红字标注+97 键构成 chip(金基座/绿叠加/蓝重构)+权威数字尾行+§23.9 三档 tooltip;顺手纠速查卡 B_on9 恢复天数笔误(约200→json 权威 267 天)
- [x] T3-1 前端重放侧完成并上 main(2026-08-23,c7a9bdf82+B1修复 40ed3d5d9→merge 241a89d08):lab 页+sim 弹窗改「总开关+模式下拉 7 种」(默认 p8≡现网逐位一致),57 标签保留为自定义态(手动勾→⚙️自定义,点下拉→回预设);老 37 键迁 common.js `_KELLY_FADE_LEGACY_SPECS` 规格单源,parity 两步法 30098 行×115 集合 diff=0;reviewer PASS(B1 循环体错位已修)
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
