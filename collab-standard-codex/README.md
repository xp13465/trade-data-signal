# Codex 协作标准包(纯通用,去业务化)

> 这是**与具体项目业务无关**的「Codex 多角色(主会话 + 并发 skill)协作」标准,从实际项目长期磨合中提炼。已**去业务化 + 占位符化**:不含任何项目特定实体(域名/数据产物/定时任务/模型提供方/算法名),项目特定值全部用 `<占位符>` 标注,移植到新项目时替换即可。
>
> **双 agent 对等**:Codex 版(本目录)+ Claude 版(`../collab-standard-claude/`)方法论内核完全一致,仅机制表述按各工具的落地方式区分。两套目录都是纯新增标准,不是任何项目的备份包。
>
> 参考来源:本规范提炼自一个长期多人协作战术落地项目(含 Claude + Codex 双 agent、subagent 调度、数据产品与回测),通用方法论已剥离业务外壳。

## 完整工作模式拓扑

```
┌──────────────────────────────────────────────────────────────┐
│  Codex 协作标准(三分类方法论)                                  │
├──────────────────────────────────────────────────────────────┤
│  A 共享核心 → AGENTS.md(根)                                   │
│    = 所有角色无条件遵守,嵌套就近生效                           │
│    = 数据一致性/git 绝不静默/外部先查社区/验收铁律/             │
│      防重犯索引/token 行为层/中文口语化                        │
├──────────────────────────────────────────────────────────────┤
│  B 角色执行层 → .codex/skills/role-*/SKILL.md(4 角色规范全文)   │
│    = 主会话调度并发 codex exec / multi_agent 时,按需加载        │
│    = implementer(修 bug 三铁律/举一反三/7 级阶梯/上线操作)      │
│      researcher(调研方法论/防前视/穷举回测/同构对账)           │
│      reviewer(回归三层/改动分级/置信度过滤/trace+verifier)     │
│      tester(验证门四步/懒但安全/curl 三查)                    │
├──────────────────────────────────────────────────────────────┤
│  C 主控/调度层 → docs/main-governance.md                      │
│    = 主会话按需读;角色执行时不读(不为这些 token 买单)          │
│    = 只调度不实施/派单三件套/上线三查/改动分级/冻结契约/        │
│      任务 4 态/自我成长机制                                    │
├──────────────────────────────────────────────────────────────┤
│  .codex/config.toml         = multi_agent 默认开启 + 注释说明   │
│  docs/role-based-context-design.md = 双 agent 差异 + 为什么三分类│
│  docs/lessons-index.md             = 防重犯锚点索引(通用教训)   │
│  templates/PROJECT-SPECIFIC.template.md = 项目专项填占位符骨架 │
└──────────────────────────────────────────────────────────────┘
```

## 🚀 快速启动(可直接复制粘贴给主会话的一段话)

> **怎么给新 agent**:新项目装好 Codex CLI 后,把下面这段**带 git 链接的话整段发**给新项目的 Codex 主会话即可。agent 会先打开 git 链接读完整 README(拓扑 / 部署四件套 / 文件清单),再按说明就位。占位符按新项目实际值替换。

---
你是一套「Codex 多角色协作标准」的唯一入口。完整说明(拓扑 / 部署四件套 / 文件清单)先看这个 git 链接:
📄 https://github.com/xp13465/trade-data-signal/blob/main/collab-standard-codex/README.md
(网页打不开说明是私有仓库,改用 `git clone git@github.com:xp13465/trade-data-signal.git` 拉取后读 `collab-standard-codex/README.md`)

开工第一步:先读根 `AGENTS.md`(共享核心,所有角色无条件守:数据一致性/git 绝不静默/验收铁律/防重犯索引),再读 `docs/main-governance.md`(主会话专属:只调度不实施/派单三件套/改动分级),最后读本项目的 `PROJECT-SPECIFIC.md`(项目特定值:域名/数据产物/定时任务/测试基准)。发并发角色任务(multi_agent / codex exec)+s flag 的会话内按需传 `.codex/skills/role-*/SKILL.md` 路径或由 TOML skills 列注入指令,让角色按各自规范执行。每次并发执行必带进度文件 `/tmp/agent-progress-<名>.md` 每步 echo(主会话据此巡检兜底),完成由主会话 merge/push。遇到问题先查 `docs/lessons-index.md` 防重犯索引。开始。
---

## 三分类方法论(Claude 版等价)

| 分类 | 文件 | 内容 | 注入方式 |
|---|---|---|---|
| **A 共享核心** | 根 `AGENTS.md` | 所有角色都该无条件知道:数据一致性、git 绝不静默、外部先查社区、验收铁律、防重犯索引、token 行为层、中文口语化 | 嵌套 AGENTS.md 就近生效,按需加载 |
| **B 角色执行层** | `.codex/skills/role-*/SKILL.md` | implementer / researcher / reviewer / tester 四角色专属规范 + 专属教训蒸馏 | multi_agent / 并发 exec 按需传 skill;TOML skills 列可默认注入 |
| **C 主控/调度层** | `docs/main-governance.md` | 只调度不实施、派单三件套、上线三查、改动分级 A/B/C、冻结契约、方案不偷懒、任务 4 态、自我成长 | 主会话按需 Read(会话开头一次) |

**为什么这么拆(与 Claude 版同因)**:指令文件要小、按需加载、按角色/层级拆分是业界共识(AGENTS.md 开放标准、Cursor Agent Rules、Claude skills 注入同精神);本项目沉淀证明:数据产物层 + 协作规范的时效性是活文档配套机制,不是一次性静态文件。详见 `docs/role-based-context-design.md`。

## 怎么装到新项目(四件套,缺一不可)

> ⚠️ **只拷根 AGENTS.md = 无角色执行层**。角色规范在 `.codex/skills/role-*/`,执行层必须整体拷贝。

**① 共享核心** —— 根 `AGENTS.md` 拷到新项目根

```bash
cp collab-standard-codex/AGENTS.md <新项目根>/AGENTS.md
```

**② 角色执行层** —— 角色 skill 整体拷 + 配置文件

```bash
cp -r collab-standard-codex/.codex <新项目根>/.codex/
```

**③ 主控层 + 教训索引** —— 主会话按需读,角色执行时不读

```bash
cp collab-standard-codex/docs/main-governance.md <新项目根>/docs/
cp collab-standard-codex/docs/lessons-index.md <新项目根>/docs/
cp collab-standard-codex/docs/role-based-context-design.md <新项目根>/docs/
```

**④ 项目专项** —— 用模板填本项目特定值

```bash
cp collab-standard-codex/templates/PROJECT-SPECIFIC.template.md <新项目根>/docs/PROJECT-SPECIFIC.md
```

把占位符(`<主域名>` `<数据产物A>` `<定时任务时点>` `<模型提供方>` `<DB名>` `<部署脚本>` `<bump版本脚本>` 等)替换为该项目实际值;不适用的章节可删。根 `AGENTS.md` 的「开工先读」节指向该 `PROJECT-SPECIFIC.md`。

## 双 agent 对等(Claude 版)

本目录是 **Codex 版**(机制:根 `AGENTS.md` 嵌套就近生效 + `.codex/skills` 按需加载 + multi_agent / 并发 exec)。Claude 版在 `../collab-standard-claude/`,机制不同但**方法论内核完全一致**:

| 层 | Codex 版(本目录) | Claude 版(../collab-standard-claude) |
|---|---|---|
| 共享核心 | 根 `AGENTS.md` 嵌套就近生效,按需加载 | 根 `CLAUDE.md` 对子 agent 全量注入 |
| 角色定义 | 无 per-agent 文件,靠 `.codex/skills/role-*` + 主会话约定 | `.claude/agents/*.md`(frontmatter + skills 字段) |
| 角色 skill | `.codex/skills/role-*/SKILL.md`(Agent Skills 标准) | `.claude/skills/role-*/SKILL.md` |
| 多 agent | multi_agent feature / 并发 codex exec 会话 | 内置 subagent(Agent 工具) |

迁移到新项目时按需要取一套,或两套都装(Claude 管 Claude 侧、Codex 管 Codex 侧)。

## 包内文件清单

```
collab-standard-codex/
├── README.md                                   # 本说明
├── AGENTS.md                                   # 共享核心(Codex 版根标准)
├── .codex/
│   ├── config.toml                             # multi_agent 默认开启 + 注释说明
│   └── skills/
│       ├── role-implementer/SKILL.md           # B 角色层 4 个 skill(按需加载)
│       ├── role-researcher/SKILL.md
│       ├── role-reviewer/SKILL.md
│       └── role-tester/SKILL.md
├── docs/
│   ├── main-governance.md                      # C 主控层(按需 Read)
│   ├── role-based-context-design.md            # 双 agent 对等差异 + 为什么三分类
│   └── lessons-index.md                        # 防重犯索引(通用教训,同 Claude 版)
└── templates/
    └── PROJECT-SPECIFIC.template.md            # 项目专项占位符骨架(同 Claude 版)
```