# 按角色分上下文调研报告(role-based-context-research.md)

> 调研日期:2026-08-12 | 调研 agent 产出 | 只读调研,本文件为唯一新建文件
> 触发问题(用户反思):"CLAUDE.md 是上下文,子会话也会带上。子会话需要这么完整的上下文么?主会话和子 agent 分了角色,上下文是不是也应该分角色?因为不同角色的经验对其他角色不通用,后续经验会非常庞大。"

---

## ① 结论摘要(用户观点是否成立 + 业界共识)

**用户观点成立,方向与业界一致,但有一个重要的机制现实必须先讲清楚:**

1. **"子会话也带上完整 CLAUDE.md" —— 属实,且是硬机制**。Claude Code 官方文档:CLAUDE.md 按"当前工作目录向上查找"加载,启动时**全量注入**;本调研会话(子 agent)实测也收到了根 CLAUDE.md 全量(88KB ≈ 3.1 万 token)作为上下文注入。子 agent 无法通过 agent 定义把根 CLAUDE.md 从自己上下文里"剔除"。
2. **"上下文应该分角色" —— 方向正确,是业界前沿**。官方已提供按角色分上下文的原生机制:**`.claude/agents/*.md` 每个 agent 有独立 system prompt(替代基础 system prompt)+ `skills` 字段把指定 skill 全文注入该 agent 启动上下文 + `memory` 字段给每个 agent 独立持久记忆**。这正是"不同角色加载不同上下文"。
3. **业界共识:指令文件要小、要按需加载、按目录/角色拆分是主流**。AGENTS.md 开放标准(60k+ 项目在用)主推**嵌套 AGENTS.md 按目录拆分**(OpenAI 主仓 88 个 AGENTS.md,"离被编辑文件最近的生效");Cursor 用 `.cursor/rules` 按 glob 作用域 + Agent Rules 按 agent 作用域;Claude Code 用 per-agent 定义 + per-agent skill 注入。**没有任何主流工具建议把所有规范塞进一个文件全量注入**。
4. **结论一句话**:不是把根 CLAUDE.md 从子 agent 里"删掉"(删不掉),而是**把根 CLAUDE.md 瘦到"全员共享核心"**,把角色专属规范**移到 per-role skill(经 agent 定义注入)+ 主控专属规范移到主控按需读的 governance 文件 + §18 教训区归档留索引**。这样每个子 agent 只看到【小共享核心 + 自己角色的专属 skill】,主控只看到【小共享核心 + 按需读的主控规范】。

---

## ② Claude Code 机制答案(必查问题 1、2)

> 说明:本环境 `code.claude.com` 直连被网络策略拦截,以下引文经**官方文档 GitHub 镜像**(ddobon/mirror-claude-code-docs,每日同步官方文档)+ **官方内置 agent system prompt 实录仓库**(Piebald-AI/claude-code-system-prompts)+ **本会话实证**(我是子 agent,收到全量 CLAUDE.md 注入)三处交叉验证。

### 2.1 子 agent 上下文机制(必查问题 1)

| 问题 | 答案 | 依据 |
|---|---|---|
| Agent 工具派出的子 agent 是否全量加载根 CLAUDE.md? | **是**。CLAUDE.md 按工作目录向上查找、启动全量加载;子 agent 工作目录=项目根,故加载根 CLAUDE.md。**实证**:本调研会话(子 agent)上下文注入了完整 88KB 根 CLAUDE.md + MEMORY.md 索引。且项目 memory 与用户前提均确认"子会话也会带上" | 官方 memory 文档:"CLAUDE.md files in the directory hierarchy above the working directory are loaded in full at launch";本会话 system-reminder 实测 |
| `.claude/agents/*.md` 的 system prompt 是替代还是叠加? | **替代基础 system prompt**(不叠加),但 **CLAUDE.md 上下文仍叠加注入**。官方原文:"Subagents receive only this system prompt (plus basic environment details like working directory), not the full Claude Code system prompt" —— 即 agent 定义 body **替换**主 agent 的内部 system prompt;而 CLAUDE.md 属"project context/instructions"层,独立于 system prompt,照常注入 | 官方 sub-agents 文档 §Subagent files(frontmatter 表上方段落) |
| 有没有机制让不同子 agent 加载不同上下文? | **有,三个原生机制**:(a) agent 定义 body = 每个 agent 独立 system prompt;(b) **`skills` 字段**:官方明确"Subagents don't inherit skills from the parent conversation; you must list them explicitly. The full content of each skill is injected into the subagent's context at startup" —— 这是"按角色注入不同领域知识"的官方接口;(c) **`memory` 字段**(user/project/local 三级):每个 agent 独立持久记忆,系统 prompt 注入该记忆目录 MEMORY.md 前 200 行 | 官方 sub-agents 文档 §supported frontmatter(fields: skills/memory)与 §Use the skills field |
| 子目录级 CLAUDE.md / .claude/rules 被子 agent 加载吗? | 子目录 CLAUDE.md **按需加载**(Claude 读该目录文件时);`.claude/rules` 带 `paths` frontmatter 的**按路径按需加载**,不带 paths 的启动加载。本项目暂未用这两种 | 官方 memory 文档 §How CLAUDE.md files load / §Organize rules |
| 其他子 agent 上下文限制 | **skills 不继承**(必须显式列出);MCP 工具默认继承;permission 继承;model 默认 inherit | 官方 sub-agents 文档 |

### 2.2 官方大 CLAUDE.md / 上下文管理最佳实践(必查问题 2)

- **官方目标:每个 CLAUDE.md 文件 < 200 行**。"Longer files consume more context and reduce adherence. If your instructions are growing large, split them using imports or `.claude/rules/` files"(官方 memory 文档 §Size)
- **官方专门小节 "My CLAUDE.md is too large"**:把详细内容移到 `@path/to/import` 引入文件,或拆到 `.claude/rules/` 文件
- **官方精简原则**:best-practices 文档 "Write an effective CLAUDE.md":"Keep it concise. For each line, ask: 'Would removing this cause Claude to make mistakes?' If not, cut it. **Bloated CLAUDE.md files cause Claude to ignore your actual instructions!**";CLAUDE.md 只放"适用所有会话"的,领域知识用 skills(按需加载不膨胀每次会话)
- **多文件拆分官方机制(按加载方式分两类)**:
  - **启动全量展开(组织用,不省 token)**:`@path/to/import` 引入文件(递归最多 5 层,外部路径首次有批准弹窗)—— 文件在启动时**展开进上下文**,适合组织不省 token
  - **按需加载(省 token 的正解)**:
    - **子目录 CLAUDE.md**:读该目录文件时才加载
    - **`.claude/rules/`**:带 `paths` frontmatter 的规则按路径匹配加载(如 `paths: ["src/api/**"]`);`~/.claude/rules/` 个人级
    - **skills**:会话启动只见描述,用到时才载全文(见 2.3)
    - **memory**:主 agent 按"查询相关度"从记忆文件里挑(≤5 个)附加,而非全量
- **主 agent 专属注入方式**:`--append-system-prompt`(每次调用都要传,适合脚本);无 per-agent 文件给主 agent,主 agent 上下文=基础 system prompt + CLAUDE.md + memory + skills

### 2.3 补充:skills 在子 agent 里的加载语义(关键)

- 主会话:启动只见 skill 描述列表,用到时才注入全文 → **按需,不膨胀**
- 子 agent(agent 定义 `skills` 字段):**启动即注入全文**,不是"可用但未加载" → **确定性注入**。这正是"给每个角色注入它的专属知识"的官方正解
- Agent Skills 开放标准(agentskills.io)跨工具通用;Cursor/Codex 等也读

---

## ③ 业界做法对比(必查问题 3)

### 3.1 AGENTS.md 开放标准(Codex / Amp / Jules / Cursor / Factory 等共同发起)

- 位置:仓库根放一个 `AGENTS.md`(README for agents)
- **嵌套拆分(官方第 4 步)**:monorepo 里每个子包再放一个 AGENTS.md,"Agents automatically read the nearest file in the directory tree, so the closest one takes precedence";**OpenAI 主仓有 88 个 AGENTS.md**
- 冲突解决:离被编辑文件最近的 AGENTS.md 生效;用户即时聊天指令覆盖一切
- 兼容工具:Codex(OpenAI)、Amp、Jules(Google)、Gemini CLI、Cursor、Factory、Aider、Windsurf、Devin、Copilot 等 30+ 工具
- **结论:按目录拆分指令文件是行业主流标准;本项目的 docs/agent-quickstart.md(按任务类型 A-F)思路与之一致,但它是"按需 Read"而非嵌套自动加载**

### 3.2 Cursor(支持"按规则作用域 + 按 agent 作用域"两级)

- `.cursor/rules`:全局 `~/.cursor/rules` + 项目 `.cursor/rules`;**规则分 Always(总附加)与 Auto Attached(带 glob,匹配文件在上下文才附加)**
- **Agent Rules(较新)**:规则可附加到指定 agent/subagent → **按 agent 角色给不同规则**,与用户需求最接近的工具级实现之一
- 另有 Subagents(自定义 agent 带独立 system prompt/tools)+ Skills(Agent Skills 标准)
- (文档 nav 实测确认存在 Rules / Subagents / Skills 页;页面正文本环境抓取受限,核心机制为官方文档 URL + 业界共识)

### 3.3 Claude Code(本项目所在,见②)

- 按角色分上下文的原生能力:**per-agent system prompt + per-agent skill 全文注入 + per-agent 持久记忆**——三件套业界同类里最完整
- 短板:根 CLAUDE.md 对子 agent 无条件全量注入,只能"瘦根",不能"剔除"

### 3.4 对比表

| 工具 | 按目录拆分 | 按角色/agent 拆分 | 按需加载 | 大文件官方建议 |
|---|---|---|---|---|
| Claude Code | 子目录 CLAUDE.md + `.claude/rules`(paths) | **agent 定义 + skills 注入 + agent 记忆** | skills/子目录 rules/memory 按需 | <200 行/文件,`@import` 或 rules 拆分 |
| Cursor | `.cursor/rules` 按目录/glob | **Agent Rules 附加到指定 agent** | Auto Attached 按匹配 | 规则按需附加 |
| Codex/Amp/Jules(Gemini)等 | **嵌套 AGENTS.md 就近生效** | 部分支持(Agent 指令) | 就近文件 | 拆分嵌套 |
| Aider | AGENTS.md(read: 配置) | — | — | — |

**业界共识**:①指令文件小(200 行级)+ 按需加载 ②按目录拆分是事实标准(AGENTS.md)③按角色拆分是前沿方向(Claude skills 注入 / Cursor Agent Rules)④"不同角色的经验对其他角色不通用"是共识,各工具都在做角色隔离。

---

## ④ 本项目按角色分上下文方案(必查问题 4)

### 4.0 现状盘点(实测)

| 项 | 现状 |
|---|---|
| 根 CLAUDE.md | git HEAD 88KB(≈3.08 万 token,UTF-8 字节 89,979);工作区正被并行 agent 瘦身中(~58KB,目标 53KB) |
| §18 犯错积累区 | 11,800 token / 54KB,占全文件 38%,最大单节 |
| §16 agent 角色画像 | 3,304 token(主控 PM 定位+监工 loop+prompt 规范) |
| §8/§11/§19 | 2,294 / 1,982 / 2,061 token(主控职责为主) |
| `.claude/agents/` | **不存在**(项目与全局都无;本会话子 agent 类型来自 SDK 内置:claude/Explore/general-purpose/Plan 等) |
| `.claude/skills/` | 项目级无(仅全局 skill 库) |
| docs/agent-quickstart.md | 33KB,按任务类型 A-F(数据产物/前端/后端/采集/上线验证/调研),**已是"按需 Read"的非注入型速查**——现有最佳实践 |
| docs/archive/ | 已有 CLAUDE-history.md / CLAUDE-errors-2026-08.md 归档先例 |
| MEMORY.md | 已有,主 agent 按相关度选附加(≤5 个) |

### 4.1 核心设计原则(基于 ② 的机制现实)

1. **根 CLAUDE.md 删不掉、躲不开子 agent**,所以根文件只留"所有角色都该无条件知道"的共享核心 + §18 防重犯索引(小)。
2. **角色专属规范不进根文件**,进 `.claude/skills/<role>/SKILL.md`,由 `.claude/agents/<role>.md` 的 `skills` 字段**启动全文注入**该角色子 agent → 这才是"不同角色加载不同上下文"的官方实现。
3. **主控专属规范(§2/§3/§4/§7/§11/§15/§16/§19 + COMPACT 恢复)单独成 `docs/main-governance.md`**,根文件只留一行指针 + MEMORY.md 索引,主控**按需 Read**(每会话开头读一次,或 SessionStart hook 注入)。子 agent 永不读它 → 子 agent 不再为这些 token 买单。
4. **§18 教训区(54KB)→ docs/archive 归档 + 根文件留"防重犯索引表"**,每条款一行(锚点 id → 一句话防重犯 → 归档文件:行),**可反向追到原文**,一条不丢。
5. **docs/agent-quickstart.md 保留为共享按需操作手册**(已按任务类型,A-F),所有角色需要时 Read,不注入。

### 4.2 角色-规范映射表(完整)

| 规范(现状§) | 主控 | 实施 agent | reviewer agent | 调研 agent | 测试 agent | 去向 |
|---|---|---|---|---|---|---|
| §6 始终中文 + 验收铁律 | ✅ | ✅ | ✅ | ✅ | ✅ | **根共享核心**(留) |
| §22 数据一致性铁律 | ✅ | ✅ | ✅ | ✅ | ✅ | **根共享核心**(留) |
| §8 改完必须推送(核心三查) | ✅ | ✅ | ✅ | ✅(只读验) | ✅ | 核心留根;操作细节→**实施 skill** |
| §14 生产稳定性(时点摘要) | ✅ | ✅ | ✅ | ⬜ | ✅ | 3-5 行摘要留根;细节→**实施 skill**+quickstart |
| §5 调研后给方案 | ✅ | ✅ | ✅ | ✅ | ⬜ | 根共享(短) |
| §18 防重犯**索引**(见 4.3) | ✅ | ✅ | ✅ | ✅ | ✅ | 根共享(索引表 1.5K token) |
| §9 单版前端铁律 | ✅ | ✅ | ✅(验 min 用字符串) | ⬜ | ✅ | →**实施 skill** + quickstart B(已含) |
| §21 算法公示同步 | ✅ | ✅(改算法必做) | ✅(查公示) | ⬜ | ⬜ | →**实施 skill** |
| §15 主功能回归复查 | ✅ | ⬜(知道有 reviewer 即可) | ✅(核心) | ⬜ | ✅(核心) | →**reviewer skill** |
| §20 快速上手引导维护 | ✅ | ⬜(读 quickstart) | ⬜ | ⬜ | ⬜ | →**主控 governance** |
| §2 监管+loop | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | →**主控 governance** |
| §3 不冲突并行 | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | →**主控 governance** |
| §4 杜绝 token 浪费 | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | →**主控 governance** |
| §7 memory 落档写保障 | ✅ | ⬜(写进度文件即可) | ⬜ | ⬜ | ⬜ | →**主控 governance** |
| §11 子 agent 卡死/429/cron 兜底 | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | →**主控 governance** |
| §16 agent 角色画像/PM 定位/prompt 写作 | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | →**主控 governance** |
| §19 自我成长机制 | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | →**主控 governance** |
| COMPACT 恢复 5 步 | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | →**主控 governance** |
| §10/§12/§13/§17(历史/约束) | ✅(速查) | 相关者按需 | ⬜ | ⬜ | ⬜ | **归档 docs/archive**,根留一行引用 |
| §18 全文 54KB | 按需查 | 按需查 | 按需查 | 按需查 | 按需查 | **归档 + 索引表**(根留索引) |

> ✅=需在上下文/可立即用;⬜=不需要。**共享核心根文件 ≈ §6+验收铁律+§22+§8 摘要+§14 摘要+§5+§18 索引 ≈ 6-9K token**。

### 4.3 防重犯条款"一条不丢"机制(索引反向追踪)

1. **归档时给每条教训分配稳定锚点 id**(如 `L08-14` = 2026-08-08 第 14 条),`docs/archive/CLAUDE-errors-2026-08.md` 保留原文完整含 id。
2. **根文件保留"防重犯索引表"**(约 1.5K token,18~19 条各一行):`id | 一句话防重犯 | 归档文件:行号`。
3. **反向可追**:主控或子 agent 命中场景时,读索引表 → grep `id` 到归档文件原文(含根因+场景+复现教训) → 完整条款仍在,一条不丢。
4. **§19 每日总结的"复发强化清单"以 id 为单位**追加在归档原文对应条目上(不新开条),索引表对应行更新为"第 N 次复发+强化后条款"。
5. **MEMORY.md 同步**一条 `lessons-index` 指针(主 agent 按相关度附加)。
6. 落地校验:拆分完成后跑一次 `grep -c '^L[0-9]' docs/archive/*errors*` 与拆分前教训条数比对,**数字一致 = 零丢失**。

### 4.4 Token 节省预估(有依据)

**依据**:中文约 1.2 token/字、ASCII 约 0.25 token/字符;实测 88KB ≈ 3.08 万 token(§18 占 1.18 万)。

| 场景 | 现状(每会话/每子 agent 注入) | 方案后 | 节省 |
|---|---|---|---|
| 主控会话启动 | ~30.8K | 根核心 ~8K + 按需读主控 governance ~10K = ~18K | **~40%**(约 13K/会话) |
| 实施子 agent | ~30.8K | 根核心 ~8K + 实施 skill ~3.5K = ~11.5K | **~63%**(约 19K/个) |
| reviewer 子 agent | ~30.8K | 根核心 ~8K + reviewer skill ~3K = ~11K | **~64%**(约 20K/个) |
| 调研子 agent | ~30.8K | 根核心 ~8K + 调研 skill ~3.5K = ~11.5K | **~63%**(约 19K/个) |
| 测试子 agent | ~30.8K | 根核心 ~8K + 测试 skill ~2.5K = ~10.5K | **~66%**(约 20K/个) |

- **日估算**:按每天 6 个子 agent + 2 次主控会话启动:现状 ≈ 6×30.8K + 2×30.8K = **246K token/天**;方案后 ≈ 6×11K + 2×18K = **102K token/天**;**日省 ~145K token ≈ 59%**(且子 agent 上下文里还多了"角色专属"高相关规范,adherence 提高是隐收益)。
- 附注:`@import` **不省 token**(启动展开),省 token 只能靠"移出根文件 → 按需注入/按需读"。

### 4.5 落地步骤(建议顺序,规避与并行瘦身撞车)

1. **等当前瘦身 agent 完成**(它已做去重/合并/§18 计划归档),以其结果为基线,不并行改 CLAUDE.md 同区域。
2. **§18 归档 + 索引**:瘦身 agent 已完成大部分归档;补建"索引表"与锚点 id(若其未做)。
3. **建 `.claude/agents/` 四个角色定义**(implementer/reviewer/researcher/tester):frontmatter(name/description/tools/model) + body=角色 system prompt(职责+适用根§清单+指向角色 skill)。**建 `.claude/skills/<role>/SKILL.md`** 四个角色专属 skill(内容从根文件对应 § 迁移 + 该角色专属教训蒸馏)。agent 定义用 `skills:` 字段挂接。
4. **根 CLAUDE.md 瘦到共享核心**(6-9K token):删 §10/§12/§13/§17 全文(归档留引用)、§18 全文(留索引)、主控专属 § 移走;保留 §6/§22/§8§14 摘要/§5/§18 索引/验收铁律。
5. **建 `docs/main-governance.md`**(收 §2/§3/§4/§7/§11/§15/§16/§19 + COMPACT 恢复),根文件留指针;MEMORY.md 加"开工先 Read docs/main-governance.md"索引(或 SessionStart hook 自动 Read,需评估 subagent 是否触发)。
6. **主控 prompt 模板切换**(§16 角色 prompt 规范):派子 agent 时指定 agent 名(implementer 等),不再手写"见§X"长引用——角色 skill 已注入。
7. **回归验证**:派 4 类角色各 1 个 agent 试跑同一个小任务,验证"上下文变小 + 关键规范还在";用 4.3 第 6 步校验教训零丢失;更新 §20 quickstart 与 docs/ 说明。

### 4.6 风险与对策

| 风险 | 对策 |
|---|---|
| 主控忘了 Read main-governance → 治理规范丢失 | 根文件+MEMORY.md 双重醒目指针;SessionStart hook 自动注入(评估);§19 每日总结本就复述核心条款,二次兜底 |
| 子 agent fresh context 不读 agent 定义/skill(重蹈 §18"不读 §18 全文"覆辙) | skills 字段是**启动全文注入**(非"可调用"),内容直接进上下文,不依赖 agent 主动读——比现状"根文件全量但没人逐条读"更可靠 |
| 角色 skill 与 quickstart 内容重叠/漂移 | 明确分工:quickstart=操作步骤(怎么上线/怎么验),role skill=角色职责+专属规范+专属教训;改动任一 grep 另一处同步(沿用 §21 模式) |
| 与并行瘦身 agent 撞车 | 严格串行:等瘦身 commit 后再动 CLAUDE.md(§3 冲突规则) |
| 角色划分过细导致维护成本高 | 先做 4 个核心角色(实施/reviewer/调研/测试),主控用 governance 文件;不新增"分析/综合"等边缘角色,其复用调研/实施 skill |
| 索引表漏掉某条款 | 落地校验:归档前教训条数 == 归档后索引表行数 + 归档文件 grep 数,不一致阻断 |
| 主 agent 上下文也变小的副作用 | 主控按需读 governance 补回,等效但节省每次子 agent 复制的浪费;上线首周人工重点观察主控行为一致性 |

---

## ⑤ 附:本次调研来源

**官方文档(code.claude.com 本环境被网络策略拦截,经官方文档 GitHub 镜像 ddobon/mirror-claude-code-docs 逐日同步 + 官方内置 agent system prompt 实录 Piebald-AI/claude-code-system-prompts 交叉验证)**:

- Claude Code Subagents:https://code.claude.com/docs/en/sub-agents(镜像 docs/sub-agents.md,关键引文:agent 定义 body 替代基础 system prompt;skills 字段全文注入子 agent;skills/memory 不继承)
- Claude Code CLAUDE.md / Memory:https://code.claude.com/docs/en/CLAUDE.md 与 https://code.claude.com/docs/en/memory(镜像 docs/memory.md:<200 行目标、"My CLAUDE.md is too large"、@import、.claude/rules、目录向上加载)
- Claude Code Best practices:https://code.claude.com/docs/en/best-practices(镜像 docs/best-practices.md:"Would removing this cause Claude to make mistakes?"、bloated CLAUDE.md 会降低遵循度、skills 放领域知识)
- Claude Code How it works:https://code.claude.com/docs/en/how-claude-code-works(镜像:context window 组成含 CLAUDE.md;子 agent 独立 context)
- Claude Code Skills:https://code.claude.com/docs/en/skills(镜像:on-demand 加载、嵌套 .claude/skills、Agent Skills 开放标准 agentskills.io)
- 镜像仓库:https://github.com/ddobon/mirror-claude-code-docs
- 官方内置 agent system prompt 实录:https://github.com/Piebald-AI/claude-code-system-prompts(agent-prompt-inherited-context-for-worktree-sub-agent 实证"子 agent 继承父会话上下文")

**业界**:

- AGENTS.md 开放标准:https://agents.md/(嵌套 AGENTS.md 就近生效、OpenAI 88 个、兼容 30+ 工具、由 Agentic AI Foundation/Linux Foundation 维护)
- Cursor Rules:https://docs.cursor.com/customize/rules ;Cursor Subagents:https://docs.cursor.com/customize/subagents(本环境正文抓取受限,机制为官方 URL + 业界共识)
- Agent Skills 开放标准:https://agentskills.io

**本项目实证**:本调研会话(子 agent)上下文实测注入全量根 CLAUDE.md + MEMORY.md → 证实"子会话也带上完整 CLAUDE.md";`git show HEAD:CLAUDE.md` 88KB/≈3.08 万 token 分段测量(§18 占 1.18 万)。
