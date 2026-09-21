# 双 agent 对等 + 为什么三分类(codex 版角色分上下文设计精要)

> 本文件是 **Codex 版**精简变体:重点讲两处——①为什么三分类(与 Claude 版同因,简述)②Codex vs Claude 双 agent 对等映射表 + 机制差异说明。完整原理(机制实证/业界对比/token 节省预估/风险对策)见 `../collab-standard-claude/docs/role-based-context-design.md`,两套共享同一套方法论依据。

## ① 为什么三分类(核心同因,两套标准一致)

- **子 agent(Claude)/并发 exec 会话(Codex)都会带上根规范文件**,且无法从自己上下文剔除 → 根文件只留「所有角色都该知道」的共享核心
- **角色专属规范进 role skill**(`.claude/agents/*.md` 的 skills 字段启动注入 / `.codex/skills/role-*` 按需加载或 config 注入) → 确定性为对应角色注入它的专属知识
- **主会话专属规范单独成 governance**(主会话按需 Read),并发执行会话不读 → 不为这些 token 买单
- **业界共识**:指令文件要小、按需加载、按角色/目录拆分(AGENTS.md 开放标准嵌套就近生效 / Cursor Agent Rules / Claude skills 注入同一精神)

## ② Codex vs Claude 双 agent 对等映射表

| 层 | Claude 版(collab-standard-claude/) | Codex 版(本目录) | 对等关系 |
|---|---|---|---|
| 共享核心 | 根 `CLAUDE.md`,对主会话+子 agent 无条件全量注入 | 根 `AGENTS.md`,嵌套就近生效,按需加载 | 内容内核一致;Claude 全量更重但强制纠偏能力更强,Codex 按需更省 token 但依赖主会话主动引用 |
| 角色定义 | `.claude/agents/*.md`(frontmatter + body,skills 字段注入) | 无 per-agent 文件,靠 `.codex/skills/role-*` + 主会话约定 | Codex 用 skill 文件承担全部角色规范,由主会话派单时显式传路径或 config skills 列注入 |
| 角色 skill | `.claude/skills/role-*/SKILL.md` | `.codex/skills/role-*/SKILL.md`(Agent Skills 开放标准 frontmatter) | 内容两版同源;机制上 Claude 启动全文注入,Codex 按需/flex 注入 |
| 多 agent 协调 | 内置 subagent(Agent 工具) | multi_agent feature / 并发 codex exec 会话 | 相同目标:主会话调度 + 并发角色执行 |
| 开工流程 | 主会话 Read main-governance + PROJECT-SPECIFIC | 主会话 Read main-governance + PROJECT-SPECIFIC | 一致 |
| 通知/监控 | SendMessage + task-notification + 巡检 cron | 完成通知 + 并发 exec mtime 巡检(见 governance §11) | 一致:通知不可靠,巡检兜底是唯一可靠残余 |
| 上线/merge | 主会话统一 merge 脚本(mechanism D) | 主会话统一 merge 脚本 | 一致:并发执行会话只 push feat,不 push main |
| 版本串/bump | 改前端源码同 commit bump + 重建 min | 同左(机制一致) | 一致 |

## ③ Codex 侧机制差异说明(只列差异,相同处不再重复)

1. **AGENTS.md 嵌套就近生效**:子目录的 AGENTS.md 优先级高于根,适合新项目按模块继续细化规范;根 AGENTS.md 放共享核心+指针
2. **role skill 加载方式**:主会话派并发 exec 时,在 prompt 里显式传对应 `.codex/skills/role-*/SKILL.md`(最可控、最省 token);需要默认注入就放 `.codex/config.toml` 的 `skills` 列——一次性全列=每次都会注入全部 skill,与"按需加载"冲突,推荐留空、派单时显式传
3. **multi_agent**:`.codex/config.toml` 已默认开启(`multi_agent = true`),主会话可把多个角色任务作为并发子会话派发;并发会话数/优先级等运行时策略按项目实际调;串行时关掉即可(skill 改走 prompt 显式引用)
4. **model 占位**:`.codex/config.toml` 的 `model = "<模型占位>"` 不写死,移植时按新项目实际提供方/档位填写——协作标准**不含任何具体模型绑定**,模型策略属于项目专项
5. **thinking/effort 分角色**:实施/测试类执行任务可关 thinking 提速省 token;reviewer/researcher/主会话保留(复杂判断/口径/公示把关)——与 Claude 版 agents 定义里 effort 分档同一精神,落地方式不同(Claude 在 agent 定义 frontmatter,Codex 在派单 prompt/config)

## ④ 迁移建议

- 只用一个 agent 体系:取对应一套(Claude 管 Claude 侧 / Codex 管 Codex 侧)即可,方法论完整
- 双 agent 混合:两套都装,按各自工具机制落地,共享同一份项目专项(PROJECT-SPECIFIC.template.md)和教训索引(lessons-index.md)——两份 templates/lessons 内容同源,保持一份为准即可
- 后续同步:两套内容以 Claude 版为源头持续演进,Codex 版按映射表机制翻译同步(改 Claude 版时对照映射表核 Codex 版是否需同步改动)