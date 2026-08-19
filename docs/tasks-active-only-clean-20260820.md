# TASKS.md 任务治理报告(2026-08-20)

> 触发:#78 用户定 TASKS.md 瘦身=**任务治理**(逐个核状态:完成关闭/不要删除/活跃保留),非文字压缩。researcher(aade4fd 的 #28)全量盘核,用户过清单拍板,implementer 落地。
> 目标:TASKS.md 只留活跃待办,干净可快速定位;远期/搁置移独立 todolist(pending-features-index.md);完成的归档;关闭的移除。
> 治理依据与逐条核查:docs/tasks-governance-scan-20260819.md(researcher 扫描报告,untracked 主仓本地文件)+ 各 commit/上线证据。

## 摘要

- TASKS.md 227 行 → 72 行,**只留活跃待办 + 大纲 + 工作约定 + 最新交接**。
- **4 态/4 文件流转(2026-08-20 用户定)**:①活跃→TASKS.md ②待办/远期→docs/pending-features-index.md ③完成→**docs/tasks-done-list.md(完成文件)** ④归档→docs/archive/(完成态呆满 7 天自动归档)。
- **43 条真完成 → 落「完成文件」docs/tasks-done-list.md**(4 态③完成态落脚,标注完成态+出处,**待 7 天自动归档**到 docs/archive/TASKS-done.md;非直接扔归档)。
- **3 条用户拍板关闭 → 移除**(关闭态,不属完成待 7 天),docs/archive/TASKS-done.md 留关闭记录。
- **1 条误标待办 L42(SVG P1)** → 改回 `[ ]`,正文同步为「P0+P1 首页/KPI/分时图已上线,剩大盘 tab 30+ echarts 改 SVG(P2-11)未做」。
- **远期/搁置 11 条 checkbox** → 移 `docs/pending-features-index.md` 模块十六(场外方案C 8步 #79 + 全站性能 P2 3条 #80)。[待办(远期)态 ②]
- **8 项被 #27 归档的活跃需求** → 补登记 pending-index 模块十六 #82-89(留言箱/ETF485扩采/公募筛选器/板块轮动/真pin/PWA/订阅推送/overlap delta),出处指向 TASKS-history-archive-20260820.md 对应段。
- **活跃待办 23 条零丢失**:12 条留 TASKS.md + 11 条远期在 pending-index = 23(治理前 22 + L42 改回 = 23)。
- 管理端看板(远期,排期周末或下周)→ 已在 pending-index #33 已登记,本条为 TASKS L47 移出确认(#81 备注同一项)。
- 场外阶段2/3 远期子项 → pending-index #90(阶段3 原 #34 已登记)。

> **结构明示**:真完成落完成文件(待 7 天自动归档);完成文件 = 7 天自动归档候选池;未满 7 天的不进 docs/archive。本次 TASKS.md 尾部「归档/远期指针」段已按 4 态标注去处。

## 对照表一:完成/关闭了哪些(53 完成 → tasks-done-list.md 完成文件待 7 天归档;3 关闭 → TASKS-done.md 留记录)

> **费率 10 条(后端/全量重生,2026-08-20 用户「完成就按完成的走」核实)**:原留 task 的 10 条费率待办经代码 grep + 线上 R2 curl **逐条实测均已实现**(费率改造 #13/14/18/22 早已上线),全部移入完成文件 docs/tasks-done-list.md(43→53)。判据见该文件「2026-08-20 费率改造已实现(10条)」段(印花税 simulate_trade.py:57、过户费3模式 :58-59、抽核心 :45/73、修bug :40、对比 app.js feeCompare、API app/main.py:586、全量重生 trade_sim_hs300_stats.json generated_at 08-19 含 fee_config.stamp_tax/transfer_fee_mode、线上含印花税已 curl)。

| 类 | 数量 | 内容 |
|---|---|---|
| TASKS 治理完成(43 不含费率后端) | 43 | 飞书群处理5/全球指数盘中实时3/accum_nav前复权13/etf通知1/降亏组合+全信号表1/全站性能P0/P1 6/费率前端7/场外方案C step0 1(注:含费率前端7条,前端部分已在43内) |
| 费率改造后端/全量重生(新核,10 条) | 10 | 费率可配置后端/印花税/过户费3模式/对比函数/API路由/重新回测按钮/印花税+过户费bug/全量重生/验证R2含印花税/对比正确性 |
| 用户关闭(3) | 3 | NIFTY50(L59)/159536 track_score(L68)/avg_dev(L77) |
| **合计(完成文件)** | **53** | 43 TASKS治理 + 10 费率 = 53,落 docs/tasks-done-list.md;**另有 3 关闭**留 TASKS-done.md 记录 |

## 对照表二:移到 todolist 了哪些(远期/搁置 → pending-index 模块十六)

| # (pending) | 项 | 原 TASKS 位置 | 说明 |
|---|---|---|---|
| 79 | 场外方案C 全量化 step1-8 | TASKS.md「08-04 场外方案C」8 个 `[ ]` | 待排期(推周末/休盘至今搁置),step 逐条完整保留 |
| 80 | 全站性能 P2-10/11/15 | TASKS.md「08-04 性能」3 个 `[ ]` | 按需滚动优化;P2-11 = L42 SVG P1 未做部分 |
| 81 | 管理端任务看板 kanban | TASKS.md L47 | 远期(排期周末或下周),pending #33 已登记同项 |
| 90 | 场外阶段2/3 | TASKS.md L45-46 | 阶段3 远期(阶段1/2 已完成),#34 已登记同项 |
| 91 | 次日开盘口径确认 | TASKS.md「次日开盘口径」待办(2026-08-20 再收尾移出) | 🔶部分完成:②次日分批挂单SOP按钮已上线,①默认改次日开盘口径未改待用户拍板;报告 kelly-nextday-open-backtest.md |
| 92 | SVG 大盘 tab P2-11 | TASKS.md「SVG P1」待办未做部分(L42,2026-08-20 改判远期移出) | P1 全站扩展已上线(293b1d101+d9a465dc6),剩大盘 tab renderAStock 30+ echarts 改 SVG;= pending #80 P2-11 同项 |

> 8 项归档活跃需求补登记(pending #82-89)对照:留言箱(#82)/ETF485扩采+OHLC(#84)/公募筛选器实战版(#83)/板块轮动(#85)/真pin(#86)/PWA(#87)/订阅推送(#88)/overlap delta(#89)。出处均指向 TASKS-history-archive-20260820.md 对应行号(在每行「出处」列标出)。

## 对照表三:留 active 哪些(TASKS.md,0 条 checkbox + 即时待安排指针非checkbox)

> **2026-08-20 再收尾(user 拍板「task 剩的待办全判远期移 todolist,不留活跃」)**:原本站 12 条 checkbox 全部清零——次日开盘 + SVG 大盘 tab 两条也判远期移 pending-index 模块十六 **#91/#92**;费率 10 条早核实已实现移完成文件。**TASKS.md 无活跃 checkbox**。

| 类型 | 条数 | 内容 |
|---|---|---|
| 暂无活跃 checkbox | 0 | 全部待办已移 todolist(pending-index 模块十六)或完成文件,等有真正在做再放回 |
| 即时待安排(非checkbox,近期指针) | 若干 | #73 8宽基四档 / #74 邮件广播hit白名单 / excludeSpecialBearCyb 实测 / 次日开盘切默认待用户拍板(见 pending #91) |

## 关键校验

- **活 `[ ]` 待办数**:治理前 22 + L42 改回 = 23 → 完成文件 53 条(43 TASKS治理 + 10 费率)✓ → 关闭 3 条 ✓ → **远期全数移入 pending-index 模块十六 #79-92(含 22 条原始待办归类 + 8 归档需求补登记)** ✓ → **TASKS.md 活跃 checkbox = 0** ✓ 全链路零丢失
- **4 态/4 文件流转对齐**:53 真完成落完成文件 docs/tasks-done-list.md(③完成态,待 7 天归档)✓;3 关闭留 TASKS-done.md 记录(关闭态)✓;**全待办远期入 pending-index 模块十六 #79-92**(②待办态)✓;docs/archive 现仅为 7 天归档落点和关闭记录 ✓
- **完成文件可反查**:docs/tasks-done-list.md 含 53 条完整 `- [x]` 内容(43 TASKS治理 + 10 费率改造已实现证据)+ 完成态标注 ✓
- **远期逐条在**:pending #79(8步)/#80(3子项)/#81/#90 + **#91 次日开盘 / #92 SVG 大盘 tab** 完整保留 ✓
- **8 项需求补登记**:pending #82-89,出处可反查 archive ✓
- **L42 状态真实**:SVG 大盘 tab 由 `[ ]` 改判远期入 pending #92(「P0+P1 已上线剩 P2-11」正文同步)✓
- **L60 akshare 前置验证**:已 `[x]` 归完成文件(验证完成=akshare 不可用已换新浪源),尾部 `[待做]` 残留随整条移除 ✓
- **cron 兼容**:pending-index 新增「模块十六」用既有标准表格格式(#/项/出处/方案/依赖/状态),不破坏既有节结构,23:45 cron 重建可认 ✓

## 涉及文件

- `TASKS.md`(重写,只留活跃)
- `docs/tasks-done-list.md`(**新增完成文件**,53 条真完成 = 43 TASKS治理 + 10 费率,待 7 天自动归档)
- `docs/archive/TASKS-done.md`(本次追加「2026-08-20 任务治理归档段」= 3 关闭记录 + 完成文件指针)
- `docs/pending-features-index.md`(模块十六 range 扩为 **#79-92**,新增 #91 次日开盘 / #92 SVG 大盘 tab + 头部更新)
- `docs/tasks-active-only-clean-20260820.md`(本报告)

## ## 复现

- **活跃待办守恒(4 态,2026-08-20 再收尾)**:治理后 `grep -c '^\- \[ \]' TASKS.md` = **0**(活跃态①清零,非丢失,系用户拍板「task 剩的待办全判远期移 todolist」);原 23 条待办(22 原始 + L42 改回)去路 = 10 费率已核实实现→完成文件 + 11 远期→pending-index 模块十六 + **2(次日开盘/SVG 大盘 tab)→pending-index #91/#92**;**零丢失**。
- **完成文件**:`grep -c '^\- \[x\]' docs/tasks-done-list.md` = **53**(43 TASKS治理 + 10 费率改造已实现,完成态③,待 7 天自动归档)。
- 关闭记录:`sed -n '/### 二、3 条用户拍板关闭/,/^---/p' docs/archive/TASKS-done.md` = 3 条。
- 远期逐条:pending #79-92 节 `sed -n '/## 十六/,/已排除/p' docs/pending-features-index.md`(79/80/81/90/91/92 覆盖 11+2 条移出 + 82-89 补登记 8 项)。
- L42 去向:`grep -n 'SVG 大盘 tab\|#92' docs/pending-features-index.md` 确认在模块十六 #92(正文「P0+P1 已上线剩 P2-11」同步)。
- 依赖文件:docs/tasks-governance-scan-20260819.md(researcher 核验脚本/证据,untracked 主仓本地)、docs/archive/TASKS-history-archive-20260820.md(8 项需求出处)。
- 数据截止:2026-08-20(治理当日)。
- 关键口径:判「完成」= 代码 grep + 数据产物 + commit 三重至少两重(researcher);「远期/搁置」= 明确标待排期/周末或下周/按需滚动;「补登记」= 被 #27 归档但语义活跃/待排期需求,出处指 archive 对应段;「完成态 7 天归档」= 完成文件呆满 7 天自动移 docs/archive。
