# Karpathy Skills 开源项目评审 · 采纳/蒸馏评估落档(2026-09-01)

> 触发:用户给 codex 抛了一个问题——评估开源项目 `multica-ai/andrej-karpathy-skills`
> 对 tdsignal 项目是否有帮助,该直接用还是蒸馏下来用。本文件 = **Claude 对 codex 回答的
> 准确性校验 + 双方回答汇总成最终完整答复 + 落档**(§23.5)。
> 落档位置:`docs/codex-reviews/`(codex 评审归档目录,塞入即归类)。非正式 codex review 报告
> (未走 ref 通道,是用户直接问 codex 的对话式评审),故不建 git ref,仅正文落档。

---

## 一、原始问题(用户 → codex)

> "这有个开源项目 [andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills/blob/main/README.zh.md),
> 挺热门的,你看下对我们现在的项目有帮助么。直接用还是蒸馏下来用?"

---

## 二、codex 的回答(核心结论)

**既不建议直接用,也不建议按"四原则框架"蒸馏,但有 2 条具体规则值得直接抄过来。**

### 这份东西是什么
`multica-ai/andrej-karpathy-skills`(Multica 团队 fork 自 `forrestchang/andrej-karpathy-skills`,非 Karpathy 本人),核心 = **一份 CLAUDE.md + 四条原则**:
1. **Think Before Coding** — 别假设、暴露疑点、问清楚
2. **Simplicity First** — 能 50 行别写 200 行
3. **Surgical Changes** — 改什么就改什么,别顺带重构
4. **Goal-Driven Execution** — 任务必须能转成"写测试 → 跑过"的循环

外加 SKILL.md 包(Claude Code plugin 用) + EXAMPLES.md 案例。

### 不原样落地的 3 条理由
- **① 这套原则是"一个人写一个新项目"用的,与 tdsignal 的分布式多 Agent 协作模型错位**:
  项目已有 AGENTS.md / .agents/codex-reviewer/SKILL.md / codex-collab-protocol.md / watcher
  协议,review 协议、surgical changes 铁律已显式表达,直接落地 = 把 4 个 Agent 都按"单 LLM
  心法"训练,反而与现有 SKILL.md 的 review 契约冲突。
- **② 原则 4"Goal-Driven Execution"在此严重失真**:项目是 Python+SQLite+CF Workers+R2+原生 JS
  数据/交易系统,没有自动化测试套件,强行套"写测试→跑过" = 每次开工建空测试目录,噪音大于价值。
- **③ "蒸馏"这词是陷阱**:四条原则每条都能在现有文档里找到更强的本地化版本(见下)。

| Karpathy 原则 | 现有更强等价物 |
|---|---|
| Think Before Coding | AGENTS.md §23.13 三源对照 + review 协议 uncert的标签 |
| Simplicity First | review 报告 P0/P1/P2 严重度 + in-diff/pre-existing/uncertain 分类 |
| Surgical Changes | SKILL.md 铁律 #1 默认 read-only + finding 标 diff 范围 |
| Goal-Driven Execution | codex_review_complete.py 原子写 + verdict=PASS/FAIL/BLOCKED 闭环 |

### 值得直接抄的 2 条规则(写进 review checklist,不是新 CLAUDE.md)
- **规则 1:每条 finding 必须能回答"这一行能追溯到 user 的哪句话"** → 加 `trace` 字段
  `{user_request, diff_range, linkage}`,不填一律退回。
- **规则 2:每条 finding 必须有"verifiable check"** → 加 `verifier` 字段
  `{command, expected, observed}`,只说"逻辑有问题"不算 finding。

### codex 没做也不会做的
没 clone repo、没改文件、没 commit、没发 review 报告(无未处理 ref)、没飞书通知。

---

## 三、Claude 对 codex 回答的准确性校验(本文件核心价值)

> 校验方式:不轻信 codex 关于"我们项目内部"的论断,逐条核对项目真实文件与状态。

### ✅ 准确 1:四条原则归纳正确
Think Before Coding / Simplicity First / Surgical Changes / Goal-Driven Execution 是该 repo
广为流传的核心内容,符合公开认知。**注**:codex 自己说"没 clone 那个 repo,原文已在我缓存里",
即 codex 未实际抓取验证 repo 内容,仅凭已有认知——四条原则归纳与主流认知一致,可信,但
repo 具体文件结构(SKILL.md/EXAMPLES.md 是否真的在)codex 未实抓,存轻微不确定性。

### ✅ 准确 2:"不建议直接落地/蒸馏"判断成立
核实项目确实已有多 Agent 协作产物:AGENTS.md(27 行,codex 工作约定)、.agents/codex-reviewer/
SKILL.md(135 行)、docs/codex-collab-protocol.md(108 行)、role-reviewer/role-implementer SKILL.md
均真实存在且覆盖这些纪律。Karpathy 单 LLM 心法叠上去确实会与现有角色契约冲突。

### ⚠️ 部分不准确 3:"没有自动化测试套件"说过头了
实际 `scripts/` 和 `a-stock-data/` 里有 `test_*.py` 针对性单测:
`test_notify_feishu_retry.py` / `test_agent_inbox_watcher.py` / `test_ai_macro_hit_filters.py` /
`test_model_inherit_dispatch.py` / `test_notify_flush_race.py` / `test_notify_dedup.py` 等。
**方向对**(确实无覆盖交易/回测核心的完整套件,review 以手动为主),但"没有测试套件"是过度断言。
→ 修正:有针对性单测,无完整核心套件。

### ✅ 准确 4:report schema 确实缺 per-finding 字段(真实补漏点)
核实 `docs/codex-collab-protocol.md` 的 Report JSON Schema,`issues` 数组就是空的 `"issues": []`,
**未定义逐条 finding 的字段规范**。codex 建议加 `trace`/`verifier` 是真实补漏,非无中生有。

### ✅ 准确 5:"已有等价物"基本属实,但 codex 的 2 条建议仍是净新增
核实 .agents/codex-reviewer/SKILL.md L40 确有 `origin=in-diff|pre-existing|uncertain`、L46 确有
`path:line`+可复现场景。**但 codex 建议的 `trace`(追溯到 user 原话)和 `verifier`(可复现命令/
expected/observed)是现有协议未强制的新增约束,比现有更强**——从"标来源"升级为"必须可追溯
+ 必须可验证复现"。方向正确,能砍口水 finding。

### ⚠️ 建议修正 6:落地点有偏差(§23.3 举一反三)
codex 建议"直接改 docs/codex-collab-protocol.md 的 report schema 段,不新建 CLAUDE.md/AGENTS.md
追加段"。方向对(改协议文档),**但偏窄**:codex-collab-protocol.md 是**协作通道协议**(ref/信号/
生命周期),而 `trace`/`verifier` 是**逐条 review 质量标准**,应同时落在:
- `.agents/codex-reviewer/SKILL.md`(约束 codex 外部 reviewer)
- `.claude/skills/role-reviewer/SKILL.md`(约束 Claude 内部 reviewer,§23.8 skill 活资产同步)
- docs/codex-collab-protocol.md Report Schema 段(定义字段)

只改协议文档 = 只约束外部 codex,漏了 Claude 内部 reviewer 同标准(同模式消费点未全包)。
→ codex 建议需按 §23.3 举一反三扩到两个 reviewer skill。

### ✅ 准确 7:codex"没做任何事"属实
核实 git status 无代码改动、refs/codex 无未处理 req、/tmp/codex-reports 仅旧报告
(rev-20260830/31),codex 声明属实。

---

## 四、Claude 的最终完整答复(汇总双方)

### 结论(Claude 与 codex 一致)
**不直接用、不蒸馏整框架**。原因:项目已是分布式多 Agent 协作(Claude 实施 + codex 外部 review +
opencode 性能 + 飞书/watcher 异步回传 + 多角色 skill),Karpathy 这套"单 LLM 写新项目心法"的 4 条
原则在现有 AGENTS.md / SKILL.md / review 协议里都已有更强本地化版本,再叠一份只会让多个 Agent
指令互相打架。

### 但 codex 的 2 条规则建议值得采纳(我核实后认可)
针对 review 报告逐条 finding 的**可追溯 + 可验证**约束,确实是当前协议缺口:
1. **`trace` 字段**:每条 finding 必须能追溯到 user 的哪句话(`user_request` / `diff_range` / `linkage`),不填退回。
2. **`verifier` 字段**:每条 finding 必须给可复现命令(`command` / `expected` / `observed`),只说"逻辑有问题"不算 finding。

这两条能把 review 报告水分砍掉一大截(从"标来源"升级为"可追溯 + 可验证复现"),性价比远高于重新蒸馏框架。

### 与 codex 的两点差异(我补充/修正)
1. **"没有测试套件"修正**:实际有针对性单测(notify/feishu/watcher/ai_macro),只是无覆盖交易/回测核心的完整套件。不影响 codex 结论,但表述要准确。
2. **落地点扩围(§23.3 举一反三)**:不只改 codex-collab-protocol.md,应同步到
   `.agents/codex-reviewer/SKILL.md` + `.claude/skills/role-reviewer/SKILL.md`,让外部 codex 和
   Claude 内部 reviewer **同一标准**,避免只约束一方。

### 是否落地 → 需用户拍板(§23.7/§23.8)
改 review 协议 + 两个 reviewer skill 属"内部流程质量标准增强",非紧急 bug,且动到 skill(活资产)。
**需用户确认采纳后再动手**,不在本落档中擅自改码。

---

## 复现 / 校验命令

- 核实 codex 引用的项目文件存在:`ls AGENTS.md .agents/codex-reviewer/SKILL.md docs/codex-collab-protocol.md .claude/skills/role-reviewer/SKILL.md`
- 核实 report schema 缺 per-finding 字段:`grep -A2 '"issues"' docs/codex-collab-protocol.md`(见 `"issues": []` 空数组)
- 核实现有 review 已有 origin 标注:`grep -n 'in-diff|pre-existing|uncertain' .agents/codex-reviewer/SKILL.md`(L40)
- 核实测试套件现状:`find . -maxdepth 2 -name 'test_*.py' | grep -v worktrees`(有针对性单测,无完整核心套件)
- 核实 codex 未改文件/未发 report:`git status --porcelain | grep -v '^??'`(无代码改动);`git for-each-ref refs/codex/req`(空)

## 落档核对

- 本文件已建,入 `docs/codex-reviews/` 归档目录(§23.5 塞入即归类)。
- 索引:`docs/codex-reviews/README.md` 是否需追加本项(非正式 codex review,走对话式评审,可不入 ref 索引;若入可加一行备注)。
- 待用户拍板是否采纳 `trace`/`verifier` 规则去改协议/skill(见第四节末)。

---

## 落地实施(2026-09-01 用户拍板)

用户 2026-09-01 拍板采纳 **放宽版** 的 2 条规则(trace/verifier),落到项目三处。本次落地为纯文档/skill 改动(不动业务代码、不动线上功能、不新建 CLAUDE.md/AGENTS.md 追加段)。

### 采纳的放宽版(修正 codex 2 处)
1. **放宽点 A**:`user_request` 允许 `N/A` + `"origin": "reviewer_own"`,用于「reviewer 独立主动挖出的项目深层问题」;只对「声称与本次需求相关」的 finding 强制追溯 user_request,reviewer_own 放行但必须显式标注,不许用 `in-diff|pre-existing` 压没。
2. **放宽点 B**:回测/口径判断类 finding,`command` 允许「重跑 XXX 回测脚本 + 预期口径」或「口径依据:...」,不强制当场真跑几小时回测;禁止只说「逻辑有问题」不带任何 command/现象。

### 三处落点(全部已改)
| 落点 | 作用 | 改动位置 |
|---|---|---|
| `docs/codex-collab-protocol.md` | 定义字段(Report JSON Schema 段 `issues` 从空数组补全 trace/verifier + 放宽说明) | `## Report JSON Schema` 段 |
| `.agents/codex-reviewer/SKILL.md` | 约束 codex 外部 reviewer(per-finding 强制字段段,补充 L40 origin 为四值) | 「发现分级与输出契约」后新增段 |
| `.claude/skills/role-reviewer/SKILL.md` | 同步 Claude 内部 reviewer(§23.8 skill 活资产同步,§22 三处一致) | §10.5 新增节 |

不动 codex 的 Request/Report 通道机制(ref/信号/生命周期/原子写),只加 per-finding 字段定义。

### 2 周试运行验证计划
- 落地后未来 2 周(2026-09-01 ~ 2026-09-15),外部 codex review 与 Claude 内部 reviewer 的报告逐条 finding 强制带 trace/verifier。
- 到期评估 4 指标,决定是否正式固化(见下),不达标则按需收窄放宽点。

### 4 指标(试运行后评估)
1. **有效 finding 率**:进报告的 finding 中被实施方采纳/定位为真问题的比例(应较采纳前提升)。
2. **模糊 finding 数**:无 command/observed、只说「逻辑有问题」的 finding 数(应趋近 0)。
3. **误报率**:被实施方核为误报的 finding 占比(应下降)。
4. **被压没主动发现**:`reviewer_own` 类主动挖出的深层问题数量(应**不降反升**,验证放宽点 A 未把好 finding 压没)。
