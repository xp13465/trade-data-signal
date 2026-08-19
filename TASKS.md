# TASKS.md - 情绪看板迭代任务清单（监管 + loop 工作模式）

> 这是「监管 + loop」工作模式的唯一共享任务文件。子进程开工前**必读本文件** + `REQUIREMENTS.md`（需求真实来源）+ `NOTES.md`（调研笔记）。监管（主进程）不直接干活，派子进程领任务循环。

> **历史已完成/关闭/远期项已按 2026-08-20 任务治理归档(4 态/4 文件流转,非删)**:①真完成 → [docs/tasks-done-list.md](docs/tasks-done-list.md)(**完成文件**,43 条标注完成态,呆满 7 天自动归档到 docs/archive/TASKS-done.md)②用户关闭 → [docs/archive/TASKS-done.md](docs/archive/TASKS-done.md)「2026-08-20 任务治理归档段」留关闭记录;③早期历史交接/旧需求 → [docs/archive/TASKS-history-archive-20260820.md](docs/archive/TASKS-history-archive-20260820.md);④远期/搁置待办(场外方案C/性能P2/管理端看板/场外阶段) + 8 项被归档的活跃需求(留言箱/ETF485扩采/公募筛选器/板块轮动/真pin/PWA/订阅推送/overlap delta) → [docs/pending-features-index.md](docs/pending-features-index.md) **模块十六 #79-90**,用户要远期明说再捞回。**本文件只留活跃待办 + 大纲 + 工作约定 + 最新交接**。治理报告:docs/tasks-active-only-clean-20260820.md。前序瘦身归档指针见 [docs/archive/TASKS-done.md](docs/archive/TASKS-done.md)。

## 📍 当前会话状态（compact 恢复用,每次状态变化后 Edit 更新）

> compact 后第一动作:读本小节恢复 transient 状态(活跃 agent/cron/commit 链/正在等什么)。详见 memory `compact-recovery-checklist`。

**最后更新**:2026-08-20(TASKS.md **任务治理已完成落地**)。本轮:
- **📌 #78 TASKS.md 任务治理已实施合并(2026-08-20)**:researcher 全量盘(aade4fd)核 47 个 `[x]` = 43 真完成 + 3 用户拍板关闭(L59 NIFTY50 / L68 159536 track_score / L77 avg_dev) + 1 误标待办(L42 SVG P1,剩大盘 tab P2-11 未做,改回 active)。处置:43 完成 + 3 关闭归档 TASKS-done.md「任务治理段」;L42 改回 `[ ]` 同步正文;远期/搁置 11 条(场外方案C 8步/性能P2 3条)移 pending-index 模块十六;8 项归档活跃需求(留言箱/ETF485扩采/公募筛选器/板块轮动/真pin/PWA/订阅推送/overlap delta)补登记 pending-index #82-89。**活跃待办 23 条零丢失**:12 条留本站(见下方)+ 11 条远期在 pending-index 模块十六。报告 docs/tasks-active-only-clean-20260820.md。
- **📌 归档/移出说明**:📍当前会话状态的历史交接轮次(L22-34 的 #69/excludeSpecialBearCyb 上线、818-fix、四档收窄、并行降级安全B、代理切官方等完成陈述)已精简,关键待办提炼到下方"待安排";细节可反查 TASKS-done.md 或对应 commit。
- **⏳ 待安排/待办(即时)**:①#73 8 宽基四档展示(sh/sz/csi500/cyb/sz50/csi1000/kc50 走势图四档色带,hs300 已完成,纯展示,用户 2026-08-19 拍板待安排,pending #73)②#74 邮件广播 ai_macro.hit 白名单二次过滤(pending #74,非阻断)③用户实测凯利区 excludeSpecialBearCyb 开关(数据/开关/公示已就绪,公示写「收益待用户实测」)④次日开盘口径待用户确认是否切默认(L36)⑤SVG 大盘 tab P2-11(L42)。
- **📋 活跃待办计数**:23 条 checkbox(12 留本站 + 11 远期在 pending-index #79/#80/#81 等),详见下方「活跃待办」。
- **📋 备注**:claude-work-mode/README.md、static-site/about.html/guide.html/privacy.html 有预先存在本地改动(非本任务,未 add 未 commit)。

## 📋 活跃待办（留本站,2026-08-20 治理后）

> 注:以下为**近期需跟进**的活跃待办。**远期/搁置**(场外方案C、性能P2-10/11/15、管理端看板、场外阶段)已移 [pending-features-index.md](docs/pending-features-index.md) 模块十六,不在此重复。8 项被归档活跃需求(留言箱/ETF485扩采/公募筛选器/板块轮动/真pin/PWA/订阅推送/overlap delta)亦在模块十六 #82-89。

### 次日开盘口径 / SVG 大盘 tab
- [ ] (次日开盘回测 2026-08-12 用户"弄好后落档报告放待办,我明天起床看") 真实跟信号操作口径确认【🔶 部分完成:②已做成「次日分批挂单SOP」按钮 lab.js(2026-08-15 SOP,「次日买入玩法」lab-sigkelly-nextday),①「前端展示/回测默认改次日开盘口径」未改——默认仍当日收盘口径,待用户确认是否切】:信号收盘后固化、次日开盘买入是真实可执行口径,成本极低(每日池净利差 -0.01%、每笔1万 -0.57%,"竞价高开吃掉利润"不成立,跳空均值 +0.031%/中位0/>1%仅6.2%)。建议①后续回测/前端展示默认改「次日开盘」口径(数据100%覆盖实现成本低)②操作:开盘不追,挂开盘下方 -1% 限价单(未触达按开盘价兜底)→K=1 +844,931/52.81%(+3.8pt)触达率39.8%,挂-2%更深处不划算。报告 docs/kelly/position/kelly-nextday-open-backtest.md(基线可复现/伪跳空剔除/覆盖率100%/A-F二阶近似诚实标注)
- [ ] (SVG P1 2026-08-11) 走势图轻量扩展——**剩大盘 tab 30+ echarts 改 SVG(P2-11)未做**【状态更新 2026-08-20:首页 sparkline 批 commit `293b1d101` 已上线;P0 site-config 框架 + ETF 评分弹窗近30日 + 皮肤弹窗切换已上线(d9a465dc6);**P1 全站扩展(首页/KPI/分时图)已上线**,剩大盘 tab renderAStock 30+ echarts 改 SVG 或 IntersectionObserver 懒渲染(P2-11,待排期,详见 pending 模块十六 #80)未做】。用户 2026-08-11 追问状态(此前质疑"首页没效果"即 P0 只接 1 消费点,举一反三规范要求覆盖全站走势图渲染点)。

### 模拟回测费率可配置(活跃,后端未完成)
> 需求:模拟回测弹窗费率可配 + bug 根治(印花税漏算/过户费旧规则)。用户决策已定(2026-08-04):印花税万5 / 滑点定比 / 全量重生 R2。**前端已完成已归档**,以下后端+全量重生未完成。完整方案见 NOTES §48 小节AC。

- [ ] simulate_trade.py 抽核心为可调用函数（传 fee_config 参数，去掉模块级常量依赖）
- [ ] 加印花税：卖出收 0.05%（万5，默认值，可配）
- [ ] 过户费3模式：沪市/深市/沪深统一（默认沪深统一 0.001% 买卖都收，2024 现行标准）
- [ ] 费率对比函数：默认配置 vs 自定义配置 双回测结果对比
- [ ] FastAPI 路由 `/api/trade_sim_recalc`（POST，body 含 index_id + fee_config，缓存5分钟+限流10次/分）
- [ ] "重新回测"按钮调 `/api/trade_sim_recalc` API
- [ ] 修正 simulate_trade.py 印花税万5 + 过户费沪深统一 bug
- [ ] 全量重生 103 个 trade_sim_{idx}_stats.json + _full.json（印花税万5+过户费沪深统一）
- [ ] 验证线上 R2 JSON 含印花税字段
- [ ] 默认配置 vs 自定义费率对比正确性

> ⚠️ **已完成归档**:费率前端 6 档预设面板/对比区/双净值/滑点定比、upload_r2、deploy、3 域名验证已实现归档 TASKS-done.md(2026-08-20 段)。上述后端项待派。

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
