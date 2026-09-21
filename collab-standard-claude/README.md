# Claude 协作标准包(纯通用,去业务化)

> 这是一套**与具体项目业务无关**的「Claude Code 多角色协作」标准,从实际项目长期磨合中提炼。已**去业务化 + 占位符化**:不含任何项目特定实体(域名/数据产物/定时任务/模型提供方/算法名),项目特定值全部用 `<占位符>` 标注,移植到新项目时替换即可。
>
> **双 agent 对等**:Claude 版(本目录)+ Codex 版(`../collab-standard-codex/`)内容内核一致,仅机制表述按各工具的落地方式区分。两套目录都是纯新增标准,不是任何项目的备份包。
>
> 参考来源:本规范提炼自一个长期多人协作战术落地项目(含 Claude + Codex 双 agent、subagent 调度、数据产品与回测),通用方法论已剥离业务外壳。

## 完整工作模式拓扑

```
┌──────────────────────────────────────────────────────────────┐
│  Claude 协作标准(三分类方法论)                                 │
├──────────────────────────────────────────────────────────────┤
│  C 共享核心 → CLAUDE.md(根)                                  │
│    = 所有角色(主控 + 4 子 agent)启动自动注入,删不掉躲不开      │
│    = 数据一致性/算法公示同步/git 绝不静默/外部先查社区/         │
│      验收铁律/防重犯索引/token 行为层/中文口语化               │
├──────────────────────────────────────────────────────────────┤
│  B 角色执行层 → .claude/agents/*.md(4 角色定义)               │
│               .claude/skills/role-*/SKILL.md(4 角色规范全文)   │
│    = 经 agent 定义 frontmatter 的 skills 字段,启动全文注入     │
│      对应角色子 agent(确定性,不依赖主动读)                    │
│    = implementer(修 bug 三铁律/举一反三/7 级阶梯/上线操作)      │
│      researcher(调研方法论/防前视/穷举回测/同构对账)           │
│      reviewer(回归三层/改动分级/置信度过滤/trace+verifier)     │
│      tester(验证门四步/懒但安全/curl 三查)                    │
├──────────────────────────────────────────────────────────────┤
│  A 主控/调度层 → docs/main-governance.md                      │
│    = 主控按需 Read,子 agent 永不读(不为这些 token 买单)        │
│    = 只调度不实施/派单三件套/上线三查/改动分级/冻结契约/        │
│      任务 4 态/自我成长机制                                    │
├──────────────────────────────────────────────────────────────┤
│  docs/role-based-context-design.md = 为什么三分类 + 机制实证   │
│  docs/lessons-index.md             = 防重犯锚点索引(通用教训)  │
│  templates/PROJECT-SPECIFIC.template.md = 项目专项填占位符骨架 │
└──────────────────────────────────────────────────────────────┘
```

## 🚀 快速启动(可直接复制粘贴给主会话的一段话)

> **怎么给新 agent**:新项目装好 Claude Code 后,把下面这段**带 git 链接的话整段发**给新项目的 Claude 主会话即可。agent 会先打开 git 链接读完整 README(拓扑 / 部署四件套 / 文件清单),再按说明就位。占位符按新项目实际值替换。

---
你是一套「Claude 多角色协作标准」的唯一入口。完整说明(拓扑 / 部署四件套 / 文件清单)先看这个 git 链接:
📄 https://github.com/xp13465/trade-data-signal/blob/main/collab-standard-claude/README.md
(网页打不开说明是私有仓库,改用 `git clone git@github.com:xp13465/trade-data-signal.git` 拉取后读 `collab-standard-claude/README.md`)

开工第一步:先读根 `CLAUDE.md`(共享核心,所有角色都得无条件守:数据一致性/公示同步/git 绝不静默/验收铁律/防重犯索引),再读 `docs/main-governance.md`(主控专属:只调度不实施/派单三件套/改动分级),最后读本项目的 `PROJECT-SPECIFIC.md`(项目特定值:域名/数据产物/定时任务/测试基准)。角色子 agent 不用你手动注入——`.claude/agents/*.md` 已通过 skills 字段把对应角色规范(`.claude/skills/role-*/SKILL.md`)启动全文注入。多 agent 协作时:每次派子 agent 必齐三件(run_in_background + 进度文件 `/tmp/agent-progress-<名>.md` 每步 echo + 巡检兜底 cron),merge/push main 走统一入口,只 push feat 分支。遇到问题先查 `docs/lessons-index.md` 防重犯索引。开始。
---

## 三分类方法论(A / B / C)

| 分类 | 文件 | 内容 | 注入方式 |
|---|---|---|---|
| **A 主控/调度层** | `docs/main-governance.md` | 只调度不实施、派单三件套(进度文件+巡检兜底)、上线三查、改动分级 A/B/C、冻结契约、方案不偷懒、任务 4 态、自我成长 | 主控按需 Read(会话开头一次) |
| **B 角色执行层** | `.claude/skills/role-*/SKILL.md` | implementer / researcher / reviewer / tester 四角色专属规范 + 专属教训蒸馏 | 经 `.claude/agents/*.md` 的 `skills` 字段**启动全文注入** |
| **C 共享核心** | 根 `CLAUDE.md` | 所有角色都该无条件知道:数据一致性、公示同步、git 绝不静默、外部先查社区、验收铁律、防重犯索引、token 行为层、中文口语化 | 对主控 + 所有子 agent 无条件全量注入 |

**为什么这么拆**:Claude Code 机制现实——根 `CLAUDE.md` 对子 agent **无条件全量注入**(删不掉),所以根文件只留「所有角色都该知道」的共享核心;角色专属规范进 role skill(经 agent 定义 `skills` 字段**启动全文注入**,确定性);主控专属进 governance(子 agent 永不读)。业界共识一致:指令文件要小、按需加载、按角色/目录拆分。详见 `docs/role-based-context-design.md`。

## 怎么装到新项目(四件套,缺一不可)

> ⚠️ **只拷根文件 = 子 agent 无角色执行层**。子 agent 靠 `.claude/agents/` + `.claude/skills/role-*/` 注入角色规范,执行层必须整体拷贝。

**① 共享核心** —— 根 `CLAUDE.md` 拷到新项目根

```bash
cp collab-standard-claude/CLAUDE.md <新项目根>/CLAUDE.md
```

**② 角色执行层** —— agents 定义 + 角色 skill 整体拷

```bash
cp -r collab-standard-claude/.claude/agents <新项目根>/.claude/
cp -r collab-standard-claude/.claude/skills <新项目根>/.claude/
```

**③ 主控层 + 教训索引** —— 主控按需读,子 agent 不读

```bash
cp collab-standard-claude/docs/main-governance.md <新项目根>/docs/
cp collab-standard-claude/docs/lessons-index.md <新项目根>/docs/
cp collab-standard-claude/docs/role-based-context-design.md <新项目根>/docs/
```

**④ 项目专项** —— 用模板填本项目特定值

```bash
cp collab-standard-claude/templates/PROJECT-SPECIFIC.template.md <新项目根>/docs/PROJECT-SPECIFIC.md
```

把占位符(`<主域名>` `<数据产物A>` `<定时任务时点>` `<模型提供方>` `<DB名>` `<部署脚本>` `<bump版本脚本>` 等)替换为该项目实际值;不适用的章节可删。根 `CLAUDE.md` 的「开工先读」节指向该 `PROJECT-SPECIFIC.md`。

## 双 agent 对等(Codex 版)

本目录是 **Claude 版**(机制:`CLAUDE.md` 全量注入 + `.claude/agents` 角色定义 + skills 字段注入 + 内置 subagent)。Codex 版在 `../collab-standard-codex/`,机制不同但**方法论内核完全一致**:

| 层 | Claude 版(本目录) | Codex 版(../collab-standard-codex) |
|---|---|---|
| 共享核心 | 根 `CLAUDE.md` 对子 agent 全量注入 | 根 `AGENTS.md` 嵌套就近生效,按需加载 |
| 角色定义 | `.claude/agents/*.md`(frontmatter + skills 字段) | 无 per-agent 文件,靠 `.codex/skills/role-*` + 主会话约定 |
| 角色 skill | `.claude/skills/role-*/SKILL.md` | `.codex/skills/role-*/SKILL.md`(Agent Skills 标准) |
| 多 agent | 内置 subagent(Agent 工具) | multi_agent feature / 并发 codex exec 会话 |

迁移到新项目时按需要取一套,或两套都装(Claude 管 Claude 侧、Codex 管 Codex 侧)。

## 包内文件清单

```
collab-standard-claude/
├── README.md                                   # 本说明
├── CLAUDE.md                                   # C 共享核心(去业务化根 CLAUDE.md)
├── .claude/
│   ├── agents/                                 # 4 角色定义(frontmatter + body)
│   │   ├── implementer.md
│   │   ├── researcher.md
│   │   ├── reviewer.md
│   │   └── tester.md
│   └── skills/
│       ├── role-implementer/SKILL.md           # B 角色层 4 个 skill(全文注入)
│       ├── role-researcher/SKILL.md
│       ├── role-reviewer/SKILL.md
│       └── role-tester/SKILL.md
├── docs/
│   ├── main-governance.md                      # A 主控层(按需 Read)
│   ├── role-based-context-design.md            # 为什么三分类 + 机制实证
│   └── lessons-index.md                        # 防重犯索引(通用教训)
└── templates/
    └── PROJECT-SPECIFIC.template.md            # 项目专项占位符骨架
```
