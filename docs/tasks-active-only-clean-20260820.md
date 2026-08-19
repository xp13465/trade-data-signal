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

## 对照表一:完成/关闭了哪些(43 完成 → tasks-done-list.md 完成文件待 7 天归档;3 关闭 → TASKS-done.md 留记录)

| 类 | 数量 | 内容 |
|---|---|---|
| 飞书群处理 | 5 | 漏收补拉/报告群/告警群/需求群硬编码/终端待办同步群 |
| 全球指数盘中实时 | 3(完成) | P1 采全球5指数实时/P2 港股板块8个盘中/前端配套角标 |
| accum_nav 前复权修正 | 13(完成) | accum_nav 除权不跳/1520只回填/10处计算层改用/159536 TE/TE用前复权/check_data/实时close未复权/92%覆盖率/<10s/board<700KB/双标签/降序/overview含track_score/sw bump |
| etf 通知 | 1 | 🐾 进/离/放量弹窗 |
| 降亏组合+全信号表 | 1 | L41 已上线(组合建议+quadMeta.all,lab.js L8503) |
| 全站性能 P0/P1 | 6 | P1-6 并行/P1-7 preconnect(半)/P1-8 boot合并/P2-12 rootMargin/P2-13 CSS transition/P2-14 分时SVG/P2-16 换源 |
| 费率前端已完成 | 7 | 滑点定比/面板/对比区/localStorage/upload_r2/deploy/双净值/3域名 |
| 场外方案C step0 | 1 | upload_r2 调用 bug 修复 |
| 用户关闭(3) | 3 | NIFTY50(L59)/159536 track_score(L68)/avg_dev(L77) |
| **合计** | **46** | 43 完成 + 3 关闭,追加 TASKS-done.md |

## 对照表二:移到 todolist 了哪些(远期/搁置 → pending-index 模块十六)

| # (pending) | 项 | 原 TASKS 位置 | 说明 |
|---|---|---|---|
| 79 | 场外方案C 全量化 step1-8 | TASKS.md「08-04 场外方案C」8 个 `[ ]` | 待排期(推周末/休盘至今搁置),step 逐条完整保留 |
| 80 | 全站性能 P2-10/11/15 | TASKS.md「08-04 性能」3 个 `[ ]` | 按需滚动优化;P2-11 = L42 SVG P1 未做部分 |
| 81 | 管理端任务看板 kanban | TASKS.md L47 | 远期(排期周末或下周),pending #33 已登记同项 |
| 90 | 场外阶段2/3 | TASKS.md L45-46 | 阶段3 远期(阶段1/2 已完成),#34 已登记同项 |

> 8 项归档活跃需求补登记(pending #82-89)对照:留言箱(#82)/ETF485扩采+OHLC(#84)/公募筛选器实战版(#83)/板块轮动(#85)/真pin(#86)/PWA(#87)/订阅推送(#88)/overlap delta(#89)。出处均指向 TASKS-history-archive-20260820.md 对应行号(在每行「出处」列标出)。

## 对照表三:留 active 哪些(TASKS.md,12 条 checkbox + 2 非checkbox活跃需求指针)

| 类型 | 条数 | 内容 |
|---|---|---|
| 次日开盘口径确认 | 1 | 真实跟信号操作口径确认(待用户确认是否切次日开盘默认),L36 |
| SVG 大盘 tab P2-11 | 1 | L42 改回 `[ ]`,剩大盘 tab 30+ echarts 改 SVG |
| 费率可配置后端/全量重生 | 10 | simulate_trade 抽核心/印花税/过户费3模式/对比函数/API路由/重新回测按钮/印花税+过户费bug/全量重生/验证R2含印花税/对比正确性 |
| 即时待安排(非checkbox,近期) | 若干 | #73 8宽基四档 / #74 邮件广播hit白名单 / excludeSpecialBearCyb 实测 |

## 关键校验

- **活 `[ ]` 待办数**:治理前 22 + L42 改回 = 23 → 治理后 12(本站)+ 11(pending 远期)= 23,**零丢失** ✓
- **4 态/4 文件流转对齐**:43 真完成落完成文件 docs/tasks-done-list.md(③完成态,待 7 天归档)✓;3 关闭留 TASKS-done.md 记录(关闭态)✓;11 远期 + 8 需求入 pending-index(②待办态)✓;docs/archive 现仅为 7 天归档落点和关闭记录 ✓
- **完成文件可反查**:docs/tasks-done-list.md 含 43 条完整 `- [x]` 内容 + 完成态标注 + 治理解释 ✓
- **远期逐条在**:pending #79(8步)/#80(3子项)/#81/#90 完整保留 ✓
- **8 项需求补登记**:pending #82-89,出处可反查 archive ✓
- **L42 状态真实**:改回 `[ ]`,正文同步「P0+P1 已上线剩 P2-11」✓
- **L60 akshare 前置验证**:已 `[x]` 归完成文件(验证完成=akshare 不可用已换新浪源),尾部 `[待做]` 残留随整条移除 ✓
- **cron 兼容**:pending-index 新增「模块十六」用既有标准表格格式(#/项/出处/方案/依赖/状态),不破坏既有节结构,23:45 cron 重建可认 ✓

## 涉及文件

- `TASKS.md`(重写,只留活跃)
- `docs/tasks-done-list.md`(**新增完成文件**,43 条真完成,待 7 天自动归档)
- `docs/archive/TASKS-done.md`(本次追加「2026-08-20 任务治理归档段」= 3 关闭记录 + 完成文件指针)
- `docs/pending-features-index.md`(新增模块十六 #79-90 + 头部更新)
- `docs/tasks-active-only-clean-20260820.md`(本报告)

## ## 复现

- 活跃待办守恒(4 态):治理后 `grep -c '^\- \[ \]' TASKS.md` = 12(活跃态①)+ pending 模块十六 #79(8)/#80(3)= 11(待办/远期态②)→ 总 23 = 治理前 22 + L42 改回;零丢失。
- 完成文件:`grep -c '^\- \[x\]' docs/tasks-done-list.md` = 43(完成态③,待 7 天自动归档)。
- 关闭记录:`sed -n '/### 二、3 条用户拍板关闭/,/^---/p' docs/archive/TASKS-done.md` = 3 条。
- 远期逐条:pending #79-90 节 `sed -n '/## 十六/,/已排除/p' docs/pending-features-index.md`(79/80/81/90 覆盖 11 条移出 + 82-89 补登记 8 项)。
- L42 改回:`grep -n 'SVG P1' TASKS.md` 确认 `[ ]`。
- 依赖文件:docs/tasks-governance-scan-20260819.md(researcher 核验脚本/证据,untracked 主仓本地)、docs/archive/TASKS-history-archive-20260820.md(8 项需求出处)。
- 数据截止:2026-08-20(治理当日)。
- 关键口径:判「完成」= 代码 grep + 数据产物 + commit 三重至少两重(researcher);「远期/搁置」= 明确标待排期/周末或下周/按需滚动;「补登记」= 被 #27 归档但语义活跃/待排期需求,出处指 archive 对应段;「完成态 7 天归档」= 完成文件呆满 7 天自动移 docs/archive。
