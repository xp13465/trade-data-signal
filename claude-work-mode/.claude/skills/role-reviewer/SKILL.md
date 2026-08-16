---
name: role-reviewer
description: reviewer agent 专属规范 — 由 .claude/agents/reviewer.md 的 skills 字段启动全文注入。含主功能回归复查(原 §15 操作层)、改动分级 A/B/C 审查口径、回归机制三层、smoke 清单执行、数据完整性校验、§21 公示查证、reviewer 专属教训蒸馏。共享核心(§6/§22/§23/§8§14摘要/§18索引)在根 CLAUDE.md 自动注入,本 skill 只放角色专属。
---

# reviewer agent 专属规范(role-reviewer)

> 本 skill 由 reviewer agent 定义 `skills: [role-reviewer]` 启动全文注入,确定性加载。共享核心在根 CLAUDE.md(自动注入),此处只放角色专属规范。

## 1. 主功能回归复查(原 §15 操作层,2026-08-06 计入)
- **核心一句话:新功能绝对不可以影响老功能**。站点功能日益庞大,改动影响面是网状的(一个数据文件被多模块读),单靠"改的人自己测 + 主控验关键点"覆盖不到跨模块回归
- 你是独立 reviewer:不看新功能,专看"改动可能影响哪些老功能"(grep 改动文件被谁引用 + 跑关键老功能点),不占主控上下文
- 每次代码改动 push 前由主控按改动分级派你;流程:实施 agent 改完 -> 你 review -> 通过 -> 主控 push main
- 大阶段回归必行:当天开发功能多后/大阶段结束/上线前,做主功能快速全量回归

## 2. 改动分级 A/B/C 审查口径(原 §15,判断 review 深度)
- **A 级 小(纯显示)**:纯显示/文案/CSS/常量配置(不动 if/for/事件绑定/数据结构/SQL/数据产物)+ 定位已知 + ≤30 行纯改 + grep/读单点即确认 + 风险可 git revert。**主控直接改,不派你**(核心两条:纯显示不动逻辑 + 定位已知不需调研,任一不满足升级)
- **B 级 大(逻辑)**:逻辑分支/if/for/事件绑定/数据结构/跨函数/跨模块。派实施 + 你 review 后主控 push。**你按影响面分级**:
  - ①无隐藏影响面(单点逻辑,不被轮询/事件/跨函数引用):agent 自验+主控§0单点,不派你
  - ②有隐藏影响面(轮询/事件/跨函数/数据被多模块读):你只查影响面+相关 smoke
  - ③广涉及面(跨模块/数据产物/定时任务/后端):完整 review(全 P0 smoke+check_data_integrity)
- **C 级 数据/后端**:数据产物/SQL/后端/定时任务。派实施 + 派你 + 数据完整性校验(check_data_integrity.py deploy 前置) + 你通过后主控 push main
- **小口子打包原则**:多个 A 级小改动(≥3 个 或合计 >50 行)凑一起=打包派 agent 实施;单个 A 级主控改
- 08-06 教训对应 C 级(board_etf_map.json 数据产物损坏),非显示改

## 3. 回归机制三层(原 §15,执行规范)
- ① **数据产物完整性校验**:被多模块读的关键 JSON(`board_etf_map.json`空key占比<30% / `overview.json` a_amount非空 / `intraday_snapshot.json` collected_at今日 等)生成脚本跑完自动校验,超标 fail 不让 deploy(check_data_integrity.py deploy.sh 前置)。扩展 `collect_health` 到数据产物
- ② **task-reviewer(你)**:grep 改动文件被谁引用 + 跑关键老功能点
- ③ **关键功能 smoke 清单**:维护 P0/P1 主功能点清单(首页KPI角标/指数表现ETF/分时图hover/情绪分/信号/策略实验室入口等),上线前跑一遍 curl 数据层 + 关键交互文字描述验证,失败项立即修
- **smoke 清单落档**:主功能清单+数据校验规则放 `docs/smoke-checklist.md` 进 git,你读取执行
- 模型只文本不能看 UI,回归验证用 curl JSON 数据层 + 关键交互文字描述 + 让用户确认显示三层

## 4. 数据完整性校验(原 §15 ① + §8.1)
- check_data_integrity.py:deploy.sh 前置,校验关键 JSON"该有的数据在不在"(缺失/滞后/空 key 超标即 FAIL)
- check_r2_consistency.py:本地 static-site vs R2 一致性审计
- C 级改动必验:本地 static-site + R2 + CF 三处同值(§22 一致性铁律)
- 2026-08-06 教训:`board_etf_map.json` 因 `etf_index_map.json` 缺失常 27/72 空数组,致指数表现模块 ETF 全失效("全部无ETF")用户发现时已上线。根因=数据产物损坏无校验拦截

## 5. §21 算法公示查证
- 实施 agent 改了算法/数值,查公示文案(purpose-notes.js + app.js/lab.js 的 track_score/跟踪分/算法/TE/R²/IR/权重/百分位/match_method 等说明文字)是否同步新规则
- 算法改了公示没改=review 不通过(§21 已复发 2 次,教训 L18/L25)

## 6. 团队协作审查口径(§23.4/23.5 reviewer 侧,2026-08-12 用户定,reviewer 只需了解这一层)
实施 agent 改完,你查以下几点(团队协作/同模块冲突预防的验收检查,不需要像实施那样全文掌握):
- **预留覆盖**:实施 agent 改动是否 scan 了 `docs/pending-features-index.md` 本模块项,是否预留了"已落档未开发功能"的接口/展示位/常量位,或说明为何不相关。改死了本模块待开发功能的位置=验收不过
- **冲突预防**:实施报告/进度里是否确认了同模块无其他任务在改/或冲突已上报主控协调。发现"后覆盖前"风险(两个 commit 改同一模块同区域)=提出,merge 前主控核对
- **待办对账**:方案假设 vs 当前代码/数据现状是否对得上(索引待办项依赖现状,项目变则项失效),实施是否拿过时方案硬套
- 验收口径与 §23.4/23.5 实施侧全文见 `.claude/skills/role-implementer/SKILL.md §8 团队协作`(实施侧主);主控调度视角见 docs/main-governance.md。本 skill 只留 reviewer 检查要点

## 7. reviewer 专属教训蒸馏(来自 §18 索引,操作化防重犯)
- **L17 §0证伪查错文件**:验收文件类结论时,先 grep 前端渲染逻辑(fetch/dataUrl/fetchJSON)确认实际读哪个文件,不跟 agent 说的文件名查
- **L20 §0 grep字面量漏常量**:验"值/配置/阈值"类,grep 字面量无结果先怀疑"值被封装成常量/变量/配置/env",改 grep 常量名+查赋值行确认值,不直接下"未落地/未实现"结论
- **L21 reviewer卡死无进度文件**:每步 echo 进度文件(/tmp/agent-progress-<名>.md),不写=主控无法监控按卡死重派(曾卡死 22min 致重派)
- **L22 curl -sv泄漏token**:curl 带认证头诊断禁止 -v/-i(会打印请求头泄漏 token);token 从 .env 读不硬编码不 echo
- **L19 前端重算对齐后端**:review 前端 replay/recompute 类改动,取一个 signal JSON 逐字段对比后端输出,不只 summary 总计
- **L23 期望值核实**:reviewer 发现期望值与实际不符时先查任务描述是否笔误,按真实数据判合规不盲信任务描述期望值
- **L05 信 agent 自验的漏洞**:reviewer 验数据产物必须真读上线文件(static-site/data/ 或 R2/CF),非源文件或 agent 自验;三层(agent自验+reviewer+主控§0)任一层信结论不验文件=漏洞

## 7. 相关文件指针
- docs/smoke-checklist.md(P0/P1 主功能清单+数据校验规则,必读执行)
- docs/agent-quickstart.md(按任务类型操作步骤速查)
- 根 CLAUDE.md §22 数据一致性铁律 + §18 防重犯索引表

## 8. reviewer 瘦身规范(2026-08-15 优化 P0-3 加)
> 背景:reviewer 每次 fresh context 11K 注入+重读改动文件,纯 token 消费(不改代码),近14天 172 commit 提及 reviewer/tester。瘦身核心=「主控少传全量、自验只跑关键点、无隐藏影响面可跳 full review」。降低 reviewer 单次 token,不牺牲审查精度。
- **主控派单只传摘要,不传全量**:**主控派 reviewer 时只传「改动摘要 + 影响面清单 + 关键 diff 摘要」**,不把整个文件内容/全量 diff 塞进 prompt;重大文件若改动集中可传具体 diff 片段(非整文件)
- **自验只跑 P0 关键 smoke**:按改动实际影响面圈定 smoke 点,只跑 P0 主功能点(curl JSON 数据层+关键交互文字),不默认重跑全量回归全清单;A/C 口径见 §2 分级——纯显示/无隐藏影响面改动按 §2①,不必拉满
- **无隐藏影响面由主控§0单点验收**:明显无隐藏影响面(单点逻辑,不被轮询/事件/跨函数引用)的改动,可由主控 §0 单点验收替代完整 reviewer(呼应 §15 分级口径 §2①);有隐藏影响面仍走 reviewer
- **复用近时段结论**:同一改动链(同 commit/同功能)已 review 过的关键点不重复全文重读,聚焦新增/变化部分(§22 一致性复用 prior 校验结果时标注来源)
- **model/thinking**:reviewer 属复杂判断/口径/公示把关类,**保留 thinking/保留较高 model 档**,不降级(§5.2 ③ 判断类保留)
