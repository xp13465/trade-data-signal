# 方案:工作模式 + 多 agent 协作规范蒸馏成通用版(#263,2026-10-14)

> 依据本文件 = 两份只读调研(`docs/ops/workmode-distill-recon-20261014.md` 规范资产 / `docs/ops/workmode-distill-experience-20261014.md` 经验与坑)+ 用户拍板。本文件是**方案关出口件**(CLAUDE.md §5.7 三件齐)。

## 0. 用户拍板与主控默认推进(2026-10-14)

- **用户原话**:「最新的工作规范和多agent写协作规范蒸馏到一个新目录。用于其他项目参考 蒸馏过程中和项目相关的不需要保留。核心保留的是工作模式和多agent流转 还是坑和一些经验总结」。
- **已拍板**:①新目录放 **trade 仓内** ②旧三个镜像目录 **标废弃留档、不删**。
- **主控按推荐直接推进(用户「听你的建议」)**:③**只出一包 + README 附「Codex 适配指引」**(不做双份对等包 —— 旧 `collab-standard-codex` 停在 09-21、比 Claude 版少一截,双份必然漂移已被自家验证)④**避坑 157 条全展开成正文**(不降级成速查卡)。

## 1. 可修正的依据(证据)

| # | 事实 | 证据 |
|---|---|---|
| 1 | 规范正文资产 = 15 文件 2232 行;纯通用 ≈55% / 混合 ≈40% / 纯项目 ≈5% | recon §1(逐节骨架 + 性质标注) |
| 2 | 三个旧包**全缺 10 月增量**:`collab-standard-*` 停 09-21/09-28、`claude-work-mode` 停 09-28;§5.7 / §5.8 / §25 / CI 自查 / reviewer §10.7§10.8 / tester §5.3.1 / 续跑分支条 一条都没有 | recon §2.5(差距清单) |
| 3 | `collab-standard-claude/` 去化已彻底(全包仅 2 处 git 链接残留),骨架(README 四件套 + 模板 + 角色实体文件)可作底子 | recon §2.3 |
| 4 | 经验资产:memory 246 份 / §18 表 L15+E10 / archive **实测 L50+E30=80** ⇒ 通用候选 **157 条(15 域)**、纯业务特定剔除 83 条 | experience §一、§四 |
| 5 | 项目依赖残留基线:**8 类约 390 处**(域名 16 / 脚本路径 27 / 任务编号 11 / memory 名 18 / docs 引用 ~70 / 产物名 ~45 / 业务词 ~170 / 时点数字 33) | recon §5.2 |

## 2. 结构(目标树)

```
work-mode-standard/
├── README.md                 入口(是什么/怎么装 4 条命令/给新项目的启动话术/维护约定/章节映射表/Codex 适配指引)
├── CLAUDE.md                 共享核心(所有角色无条件知道的那层)
├── docs/
│   ├── main-governance.md    主控层(只调度不实施/派单规范/任务治理/COMPACT 恢复)
│   ├── quality-flow.md       6 道关 + 观察锚点
│   ├── role-based-context-design.md   角色分层的设计依据
│   ├── lessons-index.md      避坑索引(一行一条 ×157)
│   └── pitfalls/<15 域>.md   避坑正文(现象→根因→防再犯→反例/代价→来源)
├── .claude/
│   ├── agents/{implementer,reviewer,researcher,tester}.md      ×4
│   └── skills/role-{implementer,reviewer,researcher,tester}/SKILL.md  ×4
└── templates/PROJECT-SPECIFIC.template.md
```

**15 个避坑域**(→ `docs/pitfalls/<slug>.md`):a 多 agent 协作 / b 通知告警 / c 测试自测验证 / d git 分支合并 / e 数据产物一致性 / f 成本 token / g 派单任务调度 / h 调研防误判 / i 前端部署缓存 / j 删除备份安全 / k 生产运维平台 / l 数据源外部依赖 / m 回测数据科学口径 / n LLM 平台工具链 / o 沟通文档治理。

## 3. 实现预期(可观测 X→Y)

1. 新目录 `work-mode-standard/` 出现,自带 README 上手指引 ⇒ **整体拷走即可用**(角色文件是实体文件,拿走即生效)。
2. 10 月增量(recon §2.5 清单)**逐条**在新目录里能找到落点(§5.7 方案可证伪 / §5.8 六关 / §25 删前必备份 / CI 真绿 / 边界独立复核 / 边界维度穷举 / 续跑延用原分支 / 应急不豁免时点)。
3. 8 类项目依赖 **390 处 → 0 或 `<占位符>`**(刻意保留的通用示例须显式标注)。
4. 避坑库:157 条(索引 + 正文)在位,每条带来源可溯源。

## 4. 证据用例(事先写定,实现后逐条跑)

1. **残留机检**:照 recon §5.1 扫描命令集逐条跑(域名/脚本路径/任务编号/memory 名/业务词/时点数字/机器绝对路径/产物名),结果必须 0 或显式标注;占位符化项须被 `<...>` 包裹。
2. **拿走能用实证**:把 `work-mode-standard/` 整包拷到 `/tmp/<临时目录>`,按 README 的 4 条安装命令装一遍,检查 `.claude/agents/` + `.claude/skills/` 接线完整、角色定义 `skills:` 字段指向存在。
3. **增量落点抽查**:从 recon §2.5 清单抽 5 条,逐条指出落在新目录哪个文件哪一节。
4. **核心不丢**:抽查 10 条避坑(每域至少 1 条),核"现象/根因/防再犯"三要素齐、且不依赖本项目语境即可读懂。
5. **旧包冻结留痕**:`claude-work-mode/` 原样未动;`collab-standard-{claude,codex}/` 各加一行"已被 work-mode-standard 取代"。

**验收 = 拿这 5 条对预期;对不上 ⇒ 判「方案失败」**(§5.7④),不许当"完成度打折"。

## 5. 分工(两路并行,文件边界不重叠)

| 路 | 分支 | 产出文件 | 依据 |
|---|---|---|---|
| 路1 规范正文包 | `feat/263-workmode-spec` | `README.md` / `CLAUDE.md` / `docs/{main-governance,quality-flow,role-based-context-design}.md` / `.claude/**` / `templates/**` | recon §3 判据 + §4.1 结构 + §2.5 差距清单 |
| 路2 避坑库 | `feat/263-workmode-pitfalls` | `docs/lessons-index.md` / `docs/pitfalls/<15 域>.md` | experience §二判据 + §三盘点 + §四终版清单 |

- 两路各自 worktree 隔离、各自 commit 到自己的 feat 分支、**禁 push main**;合并由主控走 `scripts/main-merge.sh`。
- README 里指向避坑库的两行由路1 按本方案 §2 的固定措辞写死(接口约定),路2 不碰 README。
- 旧包冻结留痕(`collab-standard-*` 加取代行)由路1 顺手做(1 行改动/包)。

## 6. 维护约定(防"镜像仓又没同步")

新目录 README 必须写一节「维护约定」:**本仓规范改动后,"改动即同步"到本目录**(不再靠记性),并说明"通用版不写死状态型内容(版本号/时点/编号)"—— 这是 L41「同步验收做窄」+ 本次三包全过时的双重复发场景,必须在产物里内建防线。

> 2026-10-15 用户拍板:**保留维护约定,同步触发点 = 发版本时**(替代上文"改动即同步"的写法——本项目每次发版本(打 tag / 发版)时,把「同步通用包」作为发版清单的一项执行);落地见 `work-mode-standard/README.md` §4「维护约定」。