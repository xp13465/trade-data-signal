# 工作模式标准(通用版)

> 一套**与具体项目业务无关**的「AI 多角色协作工作模式」标准,从一个长期实战项目里长期磨合提炼。已**去业务化 + 占位符化**:不含任何项目特定实体(域名 / 数据产物 / 定时任务 / 模型提供方 / 算法名),项目特定值全部用 `<占位符>` 标注,移植到新项目时替换即可。
>
> 核心保留的是三样:**工作模式**(主控只调度不实施、上线前六道关)+ **多 agent 流转**(角色分层 + 派单 + 审查/测试并行)+ **踩过的坑与经验**(一条不丢地留档)。

## 1. 这包是什么(三层结构)

同一套规范按「谁需要知道」拆三层:根文件对所有角色无条件全量注入,所以只放共享核心;角色干活要用的操作细节进角色 skill(启动时全文注入对应角色);主控专属的调度策略单独放一份,子 agent 永不读、不为这些文字买单。

| 层 | 落在哪 | 放什么 | 谁读 |
|---|---|---|---|
| **共享核心** | `CLAUDE.md` | 所有角色都该无条件知道:数据一致性、算法公示同步、git 绝不静默、删除前必备份、验收铁律、防重犯索引、token 行为层、说人话 | 主控 + 全部子 agent,每会话自动注入 |
| **主控层** | `docs/main-governance.md` | 只调度不实施、派单规范、任务治理、压缩恢复、自我成长机制 | 主控按需读,子 agent 永不读 |
| **角色层** | `skills/role-*/SKILL.md` + `agents/*.md` | 实施 / 审查 / 调研 / 测试 / 机械型 五个角色的操作规范与专属教训 | 对应角色子 agent,启动全文注入 |

```
work-mode-standard/
├── README.md                            # 本说明(入口)
├── CLAUDE.md                            # 共享核心(C 层,自动全量注入)
├── docs/
│   ├── main-governance.md               # 主控层(A 层,按需读)
│   ├── quality-flow.md                  # 上线前六道关 + 一个观察锚点(路线图)
│   ├── role-based-context-design.md     # 为什么要分三层 + 机制实证
│   ├── lessons-index.md                 # 避坑索引(一行一条)
│   └── pitfalls/<域>.md                 # 避坑正文(15 个域)
├── agents/{implementer,reviewer,researcher,tester,mech-runner}.md   # 5 角色定义
├── skills/role-{implementer,reviewer,researcher,tester}/SKILL.md # 4 个 role skill 操作规范
└── templates/PROJECT-SPECIFIC.template.md                        # 项目专项填空模板
```

> **本包内不放 `.claude/`:这是刻意的普通目录约定**。Claude Code 只认项目里的 `.claude/agents/` 与 `.claude/skills/`,所以本包用普通目录 `agents/` + `skills/` 存文件,**安装时才拷进新项目的 `.claude/` 下**(见下一节)。这样做的好处是本包自身不带隐藏目录,拷贝/打包/进 git 都不会被工具误当配置。

## 2. 安装五件套(缺一不可)

> ⚠️ **只拷根文件 = 子 agent 没有角色执行层**。子 agent 靠 `.claude/agents/` + `.claude/skills/role-*/` 注入角色规范,**角色层必须整体拷贝**。把 `<项目>` 换成新项目根目录。

```bash
# 以下命令在「存放本包的上一级目录」执行 —— 即当前目录下能看到 work-mode-standard/ 这个文件夹。
# 若你人已经在 work-mode-standard/ 里面,先 cd .. 退到上一级;否则下面每条命令都会报找不到 work-mode-standard/。

# ① 共享核心 —— 根 CLAUDE.md 拷到项目根
cp work-mode-standard/CLAUDE.md <项目>/CLAUDE.md

# ② 主控层与配套文档 —— 先把项目 docs/ 建出来(②和⑤都往它里面拷),再拷 docs 文件
mkdir -p <项目>/docs
cp -r work-mode-standard/docs/* <项目>/docs/

# ③ 角色定义 —— 先在项目里建出 .claude/ 目录,再拷 5 个 agent 定义
mkdir -p <项目>/.claude/agents <项目>/.claude/skills
cp -r work-mode-standard/agents/* <项目>/.claude/agents/

# ④ 角色操作规范 —— 4 个 role skill 拷进项目 .claude/skills/
cp -r work-mode-standard/skills/* <项目>/.claude/skills/

# ⑤ 项目专项 —— 拷模板到项目,再自己把占位符填成实际值
cp work-mode-standard/templates/PROJECT-SPECIFIC.template.md <项目>/docs/
# 然后把 <项目>/docs/PROJECT-SPECIFIC.template.md 改名/填成 PROJECT-SPECIFIC.md
```

装完检查一句:新项目 `.claude/agents/` 有 5 个文件、`.claude/skills/` 有 4 个目录,且每个 agent 定义里的 `skills:` 字段指向的 skill 目录**存在**(接线断了,角色规范就注入不进去)。

## 3. 给新项目的启动话术(可直接整段粘给新项目的 Claude 主会话)

---

你是一套「AI 多角色协作工作模式」的入口。新项目刚装上这套标准,开工第一步先读根 `CLAUDE.md`(共享核心:所有角色都得无条件守——数据一致性 / 算法公示同步 / git 绝不静默 / 删除前必备份 / 验收铁律),再读 `docs/main-governance.md`(主控专属:只调度不实施 / 派单规范 / 改动分级),然后读 `docs/PROJECT-SPECIFIC.md`(项目特定值:项目名 / 域名与部署命令 / 定时任务时点 / 权威数据源 / 公示位)。

角色子 agent 不用手动注入——`.claude/agents/*.md` 已通过 `skills` 字段把对应角色规范(`.claude/skills/role-*/SKILL.md`)启动全文注入。多 agent 协作时:每次派子 agent 必齐三件(后台跑 + 进度文件 `/tmp/agent-progress-<名>.md` 每步 echo + 巡检兜底定时任务),合并 / 推主分支走统一入口,子 agent 只推 feat 分支。上线前对照 `docs/quality-flow.md` 走六道关。遇到问题先查 `docs/lessons-index.md` 避坑索引。开始。

---

## 4. 维护约定(写死,防"镜像又没同步")

- **发版本时同步**:来源项目**每次发版本(打 tag / 发版)时**,把「同步通用包」当作发版清单里的一项执行——把 `work-mode-standard/` 对应文件同步到本次发版的最新状态。**为什么不写成"改一次同步一次"**:改动即同步靠日常自觉,没有明确触发点、全靠记性,结果就是无限往后拖;现实里出现过「多个镜像包全部过时、最终被废弃」的先例——不是"改错",是"忘了同步"。把同步挂到"发版本"这个必然会发生的时点上,有明确触发点、不靠记性,漏不了。
- **通用版不写死状态型内容**:版本号 / 时点 / 编号 / 现网端点 / 当前配置值这类**随时间会变**的东西,一律不写进本包,写进使用者自己的 `PROJECT-SPECIFIC.md`。本包里对应位置只留 `<占位符>`。**这条是上面"发版本时同步"能成立的前提**:通用包只装"会不会随时间变都不变"的方法论,才谈得上按发版节奏批量同步;一旦混进状态型内容,同步就从"对一次快照"变成"每次都要逐项改值",必然拖成同步不了。
- **验收口径**:改完规范自验须含「本包对应文件是否同步 + 是否又混进状态型内容」。
- **本条 2026-10-15 由使用者确认**:以上约定(尤其"发版本时同步"这个触发点)是经使用者拍板定下的,不是随手写的措辞。
- **最近同步:2026-10-15 → 2026-10-18**(源侧 97 个增量 commit,范围 `0af1e6586..57b65e24d`);再下次同步从此范围之后起算。

## 5. 章节映射表(旧 CLAUDE.md 节号 → 本包哪个文件)

带 `§` 的节号沿用被蒸馏项目的老编号,方便老成员对照;新项目直接按本包文件结构读即可。

| 老节号 | 主题 | 本包落点 |
|---|---|---|
| §0 / §0.1 / §0.2 | 角色分上下文 / 主控只调度 / 派单三件套 | `CLAUDE.md` §0 系列;派单细节见 `main-governance.md` §11 |
| §1 | 开工先读 | `CLAUDE.md` §1;主控版见 `main-governance.md` §1 |
| §5 / §5.1 | 调研后给方案 / 穷举回测+防前视 | `CLAUDE.md` §5、§5.1;防前视全文见 `skills/role-researcher` §3.1 |
| §5.2 / §5.3 | 性能成本先查参数层 / 精简核心保障 | `CLAUDE.md` §5.2、§5.3 |
| §5.3.1 | 条款生命周期(每条带三样 + 季度退役巡检) | `CLAUDE.md` §5.3.1 |
| §5.4 | 测试基准锚点(含同构对账) | `CLAUDE.md` §5.4;对账全文见 `skills/role-researcher` §3.2 |
| §5.5 | token 优化 6 条 | `CLAUDE.md` §5.5;各角色子集见对应 skill |
| §5.7 | 方案 = 可证伪的承诺 | `CLAUDE.md` §5.7;流程见 `docs/quality-flow.md` ②;审查见 `skills/role-reviewer` §10.7 |
| §5.8 | 上线前六道关 | `CLAUDE.md` §5.8;路线图全文见 `docs/quality-flow.md` |
| §5.9 | 实施前必须先验证(三验齐) | `CLAUDE.md` §5.9;调研侧见 `skills/role-researcher` §2;审查侧见 `skills/role-reviewer` §10.7 |
| §5.10 | 探索通道(隔离 + 时间盒 + 落地前补证) | `CLAUDE.md` §5.10 |
| §6 | 中文 + 说人话 | `CLAUDE.md` §6 |
| §8 / §8.1 | 改完必须推送 / 派单锚点 | `CLAUDE.md` §8、§8.1;操作细节见 `skills/role-implementer` §3 |
| §9 | 写码前 7 级阶梯 | `CLAUDE.md` §9;全文见 `skills/role-implementer` §6.5 |
| §10 | 改静态资源必须破缓存 | `CLAUDE.md` §10;全文见 `skills/role-implementer` §1.1 |
| §14 | 生产稳定性 P0(时点) | `CLAUDE.md` §14;细节见 `skills/role-implementer` §4 |
| §15 | 主功能回归 + 改动分级 A/B/C | `main-governance.md` §15;操作见 `skills/role-reviewer` §1-§3 |
| §16 | agent 角色画像与协作规范 | `main-governance.md` §16 |
| §18 | 防重犯机制(锚点索引) | `CLAUDE.md` §26;索引 `docs/lessons-index.md`;正文 `docs/pitfalls/` |
| §19 | 自我成长机制(总结 + review) | `main-governance.md` §19 |
| §21 | 算法改动同步公示 | `CLAUDE.md` §21;全文见 `skills/role-implementer` §2 |
| §22 | 数据一致性铁律 | `CLAUDE.md` §22 |
| §23.1-§23.16 | 用户新增铁律 | `CLAUDE.md` §23 各条 |
| §24 | 前端部署 / 缓存防撕裂 | `CLAUDE.md` §24;实施侧 `skills/role-implementer` §1.1;审查侧 `skills/role-reviewer` §5.2 |
| §25 | 删除前必备份·可逆安全 | `CLAUDE.md` §25 |
| Compact | 上下文压缩保留项 / 恢复清单 | `CLAUDE.md` §27;恢复清单见 `main-governance.md` 首屏 |

> 已剔除的项目特有节(如某服务商的峰谷计价、某业务专用规则):内容不属通用方法论,需要的话作为示例写进使用者自己的 `PROJECT-SPECIFIC.md`。

## 6. Codex 适配指引(不假设 Claude 专属能力)

本包用 Claude Code 的机制举例(根 `CLAUDE.md` 全量注入 / `.claude/agents` 角色定义 + `skills` 字段注入),但**方法论内核与具体工具无关**。移植给 Codex 或其它 agent 工具时,按目标工具的实际机制改「装载方式」即可,内容不动:

| 层 | Claude Code | 移植到 Codex(参考) |
|---|---|---|
| 共享核心 | 根 `CLAUDE.md` 对子 agent 全量注入 | 根 `AGENTS.md`(就近生效、按需加载;把共享核心全文放这) |
| 主控层 | `docs/main-governance.md`(按需 Read) | 同一份,主会话按需读 |
| 角色定义 | `.claude/agents/*.md`(frontmatter + `skills` 字段) | 无 per-agent 文件时,把角色规范放 `.codex/skills/role-*/`(Agent Skills 标准),或主会话约定"派活时先读对应角色 skill" |
| 角色 skill | `.claude/skills/role-*/SKILL.md` | 同一份内容,换目录 |
| 多 agent | 内置 subagent(Agent 工具) | 工具的多 agent 能力 / 并发会话 |

要点:①**内容不变,只换装载**——三层拆分、判据、红线、教训都通用;②**角色层别省**——只给共享核心、不给角色操作规范,角色子 agent 就没有执行层;③**不假设某工具专属能力**(如"后台跑""进度文件"这类具体做法按目标工具改写成等价机制,机制意图——"派发有兜底、进展可观测"——不能省)。

## 7. 避坑库指路

避坑与经验正文在 `docs/pitfalls/<域>.md`(15 个域:a 多 agent 协作 / b 通知告警 / c 测试自测验证 / d git 分支合并 / e 数据产物一致性 / f 成本 token / g 派单任务调度 / h 调研防误判 / i 前端部署缓存 / j 删除备份安全 / k 生产运维平台 / l 数据源外部依赖 / m 回测数据科学口径 / n LLM 平台工具链 / o 沟通文档治理);一行一条的索引在 `docs/lessons-index.md`(158 条)。

> 用法:**命中场景 → 读索引一行 → 打开对应域正文看「现象 / 根因 / 防再犯」**。索引里的锚点 id 指向被蒸馏项目的归档原文;新项目从零积累自己的锚点,机制(索引 + 反追 + 复发强化)照搬即可。

> **域短名 ↔ 索引全名对照**:上面括号里的短名是"指路用的简称",索引 `lessons-index.md` 与正文 `pitfalls/<域>.md` 里用的是域全名,同一个域两种叫法,如实对照如下 —— a 多 agent 协作 = A 多 agent 协作与角色纪律;b 通知告警 = B 通知与告警;c 测试自测验证 = C 测试 · 自测 · 验证;d git 分支合并 = D git · 分支 · 合并 · 发布;e 数据产物一致性 = E 数据产物与一致性;f 成本 token = F 成本与 token;g 派单任务调度 = G 派单 · 任务治理 · 调度时序;h 调研防误判 = H 调研 · 结论纪律 · 防误判;i 前端部署缓存 = I 前端 · 部署 · 缓存;j 删除备份安全 = J 删除与备份安全;k 生产运维平台 = K 生产运维 · 稳定性 · 平台环境;l 数据源外部依赖 = L 数据源与外部依赖;m 回测数据科学口径 = M 回测 · 口径 · 数据科学方法论;n LLM 平台工具链 = N LLM 平台与工具链操作;o 沟通文档治理 = O 沟通 · 工作方式 · 文档治理。查某域正文时,用域字母 a~o 或域全名去索引 / 正文都对得上。
