# 按角色分上下文设计报告(role-based-context-design.md)

> 本文件是 **Claude 版**三分类(共享核心 / 角色执行层 / 主控层)设计依据 + Claude Code 机制实证。「为什么根 CLAUDE.md 只留共享核心」「为什么角色规范进 skill 启动注入」的完整原理,新项目团队理解这套标准为何这么设计时读本文件。Codex 版差异见 `../collab-standard-codex/docs/role-based-context-design.md`。

---

## ① 结论摘要

1. **"子 agent 会带上完整 CLAUDE.md"——属实,且是硬机制**。Claude Code 的 CLAUDE.md 按"当前工作目录向上查找"加载,启动时**全量注入**;子 agent 无法通过 agent 定义把根 CLAUDE.md 从自己上下文里"剔除"。
2. **"上下文应该分角色"——方向正确,是业界前沿**。官方已提供按角色分上下文的原生机制:**`.claude/agents/*.md`** 每个 agent 有独立 system prompt(替代基础 system prompt)+ `skills` 字段把指定 skill 全文注入该 agent 启动上下文。这正是"不同角色加载不同上下文"。
3. **业界共识:指令文件要小、要按需加载、按目录/角色拆分是主流**。AGENTS.md 开放标准(60k+ 项目在用)主推嵌套 AGENTS.md 按目录拆分("离被编辑文件最近的生效");Cursor 用 .cursor/rules 按 glob 作用域 + Agent Rules 按 agent 作用域;Claude Code 用 per-agent 定义 + per-agent skill 注入。**没有任何主流工具建议把所有规范塞进一个文件全量注入**。
4. **结论一句话**:不是把根 CLAUDE.md 从子 agent 里"删掉"(删不掉),而是**把根 CLAUDE.md 瘦到"全员共享核心"**,把角色专属规范**移到 per-role skill(经 agent 定义注入)+ 主控专属规范移到主控按需读的 governance 文件 + 教训归档留索引**。这样每个子 agent 只看到【小共享核心 + 自己角色的专属 skill】,主控只看到【小共享核心 + 按需读的主控规范】。

## ② Claude Code 机制答案

### 2.1 子 agent 上下文机制

| 问题 | 答案 | 依据 |
|---|---|---|
| Agent 工具派出的子 agent 是否全量加载根 CLAUDE.md? | **是**。CLAUDE.md 按工作目录向上查找、启动全量加载;子 agent 工作目录=项目根,故加载根 CLAUDE.md。**实证**:子 agent 上下文注入了完整根 CLAUDE.md | 官方文档:"CLAUDE.md files in the directory hierarchy above the working directory are loaded in full at launch" |
| `.claude/agents/*.md` 的 system prompt 是替代还是叠加? | **替代基础 system prompt**(不叠加),但 **CLAUDE.md 上下文仍叠加注入**。即 agent 定义 body **替换**主 agent 的内部 system prompt;而 CLAUDE.md 属"project context/instructions"层,独立于 system prompt,照常注入 | 官方 sub-agents 文档 |
| 有没有机制让不同子 agent 加载不同上下文? | **有,三个原生机制**:(a) agent 定义 body = 每个 agent 独立 system prompt;(b) **`skills` 字段**:官方明确"Subagents don't inherit skills from the parent conversation; you must list them explicitly. The full content of each skill is injected into the subagent's context at startup"——这是"按角色注入不同领域知识"的官方接口;(c) **`memory` 字段**:每个 agent 独立持久记忆 | 官方 sub-agents 文档 §supported frontmatter 与 §Use the skills field |
| 子目录级 CLAUDE.md 被子 agent 加载吗? | 子目录 CLAUDE.md **按需加载**(Claude 读该目录文件时);`.claude/rules` 带 `paths` frontmatter 的**按路径按需加载** | 官方 memory 文档 |
| 其他子 agent 上下文限制 | **skills 不继承**(必须显式列出);MCP 工具默认继承;permission 继承;model 默认 inherit | 官方 sub-agents 文档 |

### 2.2 官方大 CLAUDE.md 最佳实践

- **官方目标:每个 CLAUDE.md 文件 < 200 行**。"Longer files consume more context and reduce adherence. If your instructions are growing large, split them using imports or `.claude/rules/` files"(官方 §Size)
- **官方精简原则**:"Keep it concise. For each line, ask: 'Would removing this cause Claude to make mistakes?' If not, cut it. **Bloated CLAUDE.md files cause Claude to ignore your actual instructions!**"
- **多文件拆分官方机制(按加载方式分两类)**:
  - **启动全量展开(组织用,不省 token)**:`@path/to/import` 引入文件——文件在启动时**展开进上下文**,适合组织不省 token
  - **按需加载(省 token 的正解)**:子目录 CLAUDE.md(读该目录文件时才加载)、`.claude/rules/`(带 paths 匹配加载)、skills(会话启动只见描述,用到时才载全文)、memory(按相关度挑附加,而非全量)

### 2.3 补充:skills 在子 agent 里的加载语义(关键)

- 主会话:启动只见 skill 描述列表,用到时才注入全文 → **按需,不膨胀**
- 子 agent(agent 定义 `skills` 字段):**启动即注入全文**,不是"可用但未加载" → **确定性注入**。这正是"给每个角色注入它的专属知识"的官方正解
- Agent Skills 开放标准(agentskills.io)跨工具通用;Cursor/Codex 等也读

## ③ 业界做法对比

| 工具 | 按目录拆分 | 按角色/agent 拆分 | 按需加载 | 大文件官方建议 |
|---|---|---|---|---|
| Claude Code | 子目录 CLAUDE.md + `.claude/rules`(paths) | **agent 定义 + skills 注入 + agent 记忆** | skills/子目录 rules/memory 按需 | <200 行/文件,`@import` 或 rules 拆分 |
| Cursor | `.cursor/rules` 按目录/glob | **Agent Rules 附加到指定 agent** | Auto Attached 按匹配 | 规则按需附加 |
| Codex/Amp/Jules 等 | **嵌套 AGENTS.md 就近生效** | 部分支持 | 就近文件 | 拆分嵌套 |

**业界共识**:①指令文件小(200 行级)+ 按需加载 ②按目录拆分是事实标准(AGENTS.md)③按角色拆分是前沿方向(Claude skills 注入 / Cursor Agent Rules)④"不同角色的经验对其他角色不通用"是共识,各工具都在做角色隔离。

## ④ 本标准三分类落地方案

### 4.1 核心设计原则(基于 ② 的机制现实)

1. **根 CLAUDE.md 删不掉、躲不开子 agent**,所以根文件只留"所有角色都该无条件知道"的共享核心 + 防重犯索引(小)。
2. **角色专属规范不进根文件**,进 `.claude/skills/<role>/SKILL.md`,由 `.claude/agents/<role>.md` 的 `skills` 字段**启动全文注入**该角色子 agent → 这才是"不同角色加载不同上下文"的官方实现。
3. **主控专属规范(只调度不实施/派单三件套/上线三查/改动分级/冻结契约/任务4态/自我成长)单独成 `docs/main-governance.md`**,根文件留一行指针,主控**按需 Read**(每会话开头读一次)。子 agent 永不读它 → 子 agent 不再为这些 token 买单。
4. **教训区→归档 + 根文件留"防重犯索引"**,每条款一行(锚点 id → 一句话防重犯 → 归档文件),**可反向追到原文**,一条不丢。去业务化后的通用教训索引在本包 `docs/lessons-index.md`。
5. **docs/agent-quickstart.md 保留为共享按需操作手册**(按任务类型),所有角色需要时 Read,不注入。

### 4.2 角色-规范映射表

| 规范 | 主控 | 实施 | reviewer | 调研 | 测试 | 去向 |
|---|---|---|---|---|---|---|
| 中文口语化 + 验收铁律 | ✅ | ✅ | ✅ | ✅ | ✅ | **根共享核心** |
| 数据一致性铁律 | ✅ | ✅ | ✅ | ✅ | ✅ | **根共享核心** |
| 改完必须推送(三查) | ✅ | ✅ | ✅ | ✅(只读验) | ✅ | 核心留根;操作细节→**实施 skill** |
| 生产稳定性(时点摘要) | ✅ | ✅ | ✅ | ⬜ | ✅ | 摘要留根;细节→**实施 skill**+项目专项 |
| 调研后给方案 | ✅ | ✅ | ✅ | ✅ | ⬜ | 根共享 |
| 防重犯索引 | ✅ | ✅ | ✅ | ✅ | ✅ | 根共享+**lessons-index** |
| 算法公示同步 | ✅ | ✅(改算法必做) | ✅(查公示) | ⬜ | ⬜ | →**实施 skill** |
| 主功能回归复查/改动分级 | ✅ | ⬜(知道有 reviewer 即可) | ✅(核心) | ⬜ | ✅(核心) | →**reviewer skill** |
| 快速上手引导维护 | ✅ | ⬜(读 quickstart) | ⬜ | ⬜ | ⬜ | →**主控 governance** |
| 只调度不实施 / 派单三件套 / 任务4态 / 自我成长 | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | →**主控 governance** |

### 4.3 防重犯条款"一条不丢"机制(索引反向追踪)

1. **归档时给每条教训分配稳定锚点 id**,归档文件保留原文完整含 id
2. **根文件保留"防重犯索引表"**(各条款一行:`id | 一句话防重犯 | 归档文件`)
3. **反向可追**:主控或子 agent 命中场景时,读索引表 → grep id 到归档文件原文(含根因+场景+复现教训) → 完整条款仍在,一条不丢
4. **总结的"复发强化清单"以 id 为单位**追加在归档原文对应条目上(不新开条),索引表对应行更新为"第 N 次复发+强化后条款"
5. **落地校验**:归档前教训条数 == 归档后索引表行数 + 归档文件 grep 数,不一致=零丢失校验失败

### 4.4 Token 节省预估(有依据)

**依据**:中文约 1.2 token/字、ASCII 约 0.25 token/字符。

| 场景 | 现状(每会话/每子 agent 注入大文件) | 方案后 |
|---|---|---|
| 主控会话启动 | 大文件全量注入 | 根共享核心 + 按需读主控 governance |
| 实施子 agent | 大文件全量注入 | 根共享核心 + 实施 skill |
| reviewer 子 agent | 大文件全量注入 | 根共享核心 + review skill |
| 调研子 agent | 大文件全量注入 | 根共享核心 + 调研 skill |
| 测试子 agent | 大文件全量注入 | 根共享核心 + 测试 skill |

每个子 agent 会话省约 60%+,且子 agent 上下文里还多了"角色专属"高相关规范,遵循度提高是隐收益。附注:`@import` **不省 token**(启动展开),省 token 只能靠"移出根文件 → 按需注入/按需读"。

### 4.5 风险与对策

| 风险 | 对策 |
|---|---|
| 主控忘了 Read main-governance → 治理规范丢失 | 根文件+启动引导语双重指向;每日总结复述核心条款补救 |
| 子 agent fresh context 不读 agent 定义/skill | skills 字段是**启动全文注入**(非"可调用"),内容直接进上下文,不依赖主动读——比"根文件全量但没人逐条读"更可靠 |
| 角色 skill 与别的文档内容重叠/漂移 | 明确分工:quickstart=操作步骤,role skill=角色职责+专属规范+专属教训;改动任一 grep 另一处同步 |
| 索引表漏掉某条款 | 落地校验:归档前教训条数 == 归档后索引表行数 + 归档文件 grep 数,不一致阻断 |
| 主 agent 上下文也变小的副作用 | 主控按需读 governance 补回;上线首周人工重点观察主控行为一致性 |

## ⑤ 附:调研来源

- Claude Code Subagents 官方文档(sub-agents:agent 定义 body 替代基础 system prompt;skills 字段全文注入子 agent;skills/memory 不继承)
- Claude Code CLAUDE.md / Memory 官方文档(<200 行目标、"My CLAUDE.md is too large"、@import、.claude/rules、目录向上加载)
- Claude Code Best practices("Would removing this cause Claude to make mistakes?"、bloated CLAUDE.md 降低遵循度、skills 放领域知识)
- AGENTS.md 开放标准(嵌套 AGENTS.md 就近生效、兼容 30+ 工具、由 Agentic AI Foundation / Linux Foundation 维护)
- **本包实证**:子 agent 上下文实测注入完整根 CLAUDE.md → 证实"子 agent 会带上完整 CLAUDE.md",需要按角色瘦身