# 「工作模式规范 + 多 agent 协作规范」蒸馏调研报告

> 任务:盘点现有资产全貌,为「蒸馏成一个通用版(去项目化)新目录,供其他项目参考」提供事实依据 + 结构方案。
> 角色:researcher(只读)。日期:2026-10-14。证据口径:全部结论带 `文件:行号` 或命令输出。
> 只读声明:本次仅新增本报告文件(外加任务要求的进度文件 /tmp/agent-progress-workmode-recon.md);未改任何既有文件、未 commit、未 push、未跑任何业务脚本。

---

## 0. 结论摘要(TL;DR)

1. **规范正文(=蒸馏源头)共 15 个文件(10 个主资产 + 4 个 agent 定义 + 1 个 codex skill)、2232 行**:根 `CLAUDE.md` 283 + `docs/main-governance.md` 239 + 4 个 role skill 641 + 4 个 agent 定义 111 + `docs/pre-release-quality-flow.md` 88 + `docs/role-based-context-research.md` 207 + `docs/thinking-off-optimization.md` 324 + `.agents/codex-reviewer/SKILL.md` 237 + `docs/active-rules-archive.md` 102。逐节性质标注见 §1:纯通用约 55%、混合(通用骨架嵌项目例)约 40%、纯项目特定约 5%(业务专用节如 §5.6 峰谷定价、§23.6 入样宇宙)。
2. **三个旧镜像目录的本质是三种模式,不是三份同源副本**:`claude-work-mode/` = 本仓规范的"镜像备份包"(项目内容混排,去化程度低,最后规范同步 2026-09-28);`collab-standard-claude/` + `collab-standard-codex/` = "去业务化通用标准包"一对(残留仅 2 处 git 链接,最后更新 2026-09-28 / 09-21)。中国结论:**新蒸馏应吸取 collab-standard-claude 已验证的"去业务化 + 占位符化 + 通用锚点(G-M/G-I/G-R/G-T)"手法为底**;claude-work-mode 的价值在"完整执行层镜像 + 章节映射表 + 同步约定"三点可吸收。
3. **三个包共同的缺口(相对当前 10-14 规范)= 10 月全部增量**:根 §5.7(方案=可证伪承诺)、§5.8(6 关流程)、§25(删除前必备份)、§24 的 CI 自查(10-07)、reviewer skill §10.7/§10.8(10-14)、tester skill §5.3.1(10-14)、implementer 续跑分支条(09-23)等;另外 collab 两包还缺 §5.4⑥⑦ 之后的联动、§23.11/23.13/23.14/23.15 部分条目、§24 全文版。详见 §2.5 差距清单。
4. **分离判据可执行化**:一句话 = 「保留可复用的**判据/流程/红线**,剔除可替换的**事实/实体/编号**;混合节 = 留铁律句、抽走项目例」。9 类实体逐类处置规则见 §3。
5. **推荐结构 = 新建单一目录 `work-mode-standard/`(三分类 ABC 为骨架)**,文件树 + 逐文件来源映射 + 预估行数(~1400-1600 行)见 §4.1;备选二方案见 §4.2(双 agent 对等包 / 原地更新)。
6. **残留扫描基线(实施后机检用)**:对 15 个源文件实测 8 类项目依赖共约 **390 处**(域名 16 / scripts 路径 27 / 任务编号 11 / memory 名 18 / docs 引用 ~70 / 数据产物名 ~45 / 业务词 ~170 / 时点数字 33;另机器绝对路径为建议扫描项,本次未单独计数)。扫描命令集与"0 残留"判据见 §5。

---

## 1. 规范正文资产清单(行数 + 章节骨架 + 性质标注)

性质图例:**[通]** = 通用(任何项目成立)| **[混]** = 混合(通用骨架里嵌项目例子/项目锚点)| **[项]** = 项目特定(绑本仓业务/数据/域名/时点,通用版应剔除或抽象)。行号 = `grep -n '^#'` 实测。

### 1.1 根 CLAUDE.md(283 行)= C 共享核心(所有角色启动自动注入)

| 节 | 行号 | 性质 | 备注(项目依赖点) |
|---|---|---|---|
| 标题+导语 | 1-7 | [混] | "角色子 agent"机制=Claude Code 通用;指向 `.claude/agents` 路径=可移植 |
| §0 角色分上下文速览 | 8-17 | [混] | 表格角色定义通用;"§9 前端/§24"节号引用=项目节号 |
| §0.1 主控红线:只调度不实施 | 18-23 | [混] | 红线通用;"L29 教训"锚点=项目;紧急 A 级例外=通用 |
| §0.2 派 background agent 三件套 | 24-30 | [混] | 三件套通用;`agent_dispatch_cron_reminder.py` hook/settings.json=Claude Code 机制(可移植);L01 锚点=项目 |
| §1 开工先读 | 31-33 | [通] | — |
| §6 中文+口语化 | 34-43 | [混] | 规范通用;"smoke→冒烟测试"存量替换记录+`docs/smoke-checklist.md` 标识符=项目 |
| §5 调研后给方案 | 44-49 | [通] | — |
| §5.1 穷举最大化(含⑥防前视) | 50-63 | [通] | 方法论全通用;"K 值敏感性"为项目式举例(轻) |
| §5.2 性能/成本:先查模型参数层 | 64-69 | [通] | 方法论通用 |
| §5.3 精简核心保障 | 70-77 | [混] | 铁律通用;"20.6KB→9.6KB/91 链接"=项目数据 |
| §5.4 测试基准锚点 | 78-87 | [混] | 铁律通用;权威=memory `test-baseline-v112-anchor`=项目→应抽象为"项目专项定义" |
| §5.5 token 6 条 | 88-96 | [通] | — |
| §5.7 方案=可证伪承诺 | 97-110 | [通] | 2026-10-14 新;三旧包全缺 |
| §5.8 上线前 6 关 | 111-118 | [混] | 流程通用;引用 docs/pre-release-quality-flow.md + scripts=项目 |
| §5.6 DeepSeek 峰谷定价 | 119-126 | [项] | 绑具体服务商;通用版可剔除或抽象为"外部 API 计费时段规避"原则 |
| §18 防重犯索引表 | 127-165 | [混] | 机制(锚点+grep 反追+滚动窗口)=通用;L36-L50/E21-E30 表内容=大量项目实体 |
| §22 数据一致性 | 166-173 | [混] | 铁律通用;board_etf_map/concepts/overview+18 处登记点=项目 |
| §8 改完必须推送 | 174-181 | [混] | 流程框架通用;域名/机制 D main-merge.sh/deploy.sh=项目 |
| §8.1 派单锚点 | 182-184 | [通] | — |
| §14 生产稳定 P0 | 185-191 | [混] | "查定时任务再动手"通用;时点数字/任务名=项目 |
| §21 算法公示 | 192-194 | [混] | "改算法必同步公示"通用;具体公示文件=项目 |
| §23 用户新增铁律 23.1-23.15 | 195-245 | 混合为主 | 逐条见下 |
| 23.1 README 维护 | 198-200 | [通] | — |
| 23.2 修 bug 三铁律 | 201-203 | [通] | — |
| 23.3 举一反三 | 204-206 | [通] | — |
| 23.4 团队协作:已落档未开发+冲突预防 | 207-209 | [通] | — |
| 23.5 新产物当场落档 | 210-212 | [通] | — |
| 23.6 入样宇宙规则治理 | 213-215 | [项] | 绑"信号凯利回测"业务 |
| 23.7 版本功能冻结契约 | 216-218 | [通] | — |
| 23.8 skill 维护同步 | 219-221 | [通] | — |
| 23.9 三档互证教学法 | 222-224 | [通] | — |
| 23.10 飞书抄送与邮件一致 | 225-227 | [混] | "多渠道内容一致"通用;"飞书/邮件/notify.py"=项目 |
| 23.11 git 绝不静默 | 228-230 | [通] | — |
| 23.12 TASKS 4 态流转 | 231-233 | [混] | 模式通用;"TASKS.md"文件名=项目 |
| 23.12-1 状态单一事实源 | 234-236 | [混] | 同上 |
| 23.14 外审点名制 | 237-239 | [混] | "外审需用户点名"通用;codex-reviewer skill 引用=项目 |
| 23.15 上线必须完整版 | 240-242 | [通] | — |
| 23.13 口径三源核对 | 243-245 | [通] | — |
| §24 前端部署防撕裂 | 246-251 | [混] | "版本串+SW+数据同步闭环"通用;CI 自查(10-07)/具体脚本=项目 |
| 历史/约束归档引用 | 252-258 | [混] | 节号对照表=项目专属(通用版需重写为"新目录的节号对照");§10/§12/§13 条款=通用 |
| §25 删除前必备份 | 259-269 | [混] | 铁律通用;staticdata-old-mirror 例=项目 |
| 验收铁律 | 270-272 | [通] | — |
| Compact Instructions | 273-283 | [混] | Compact 机制=Claude Code 通用;9 条内容嵌项目状态(应用"骨架保留、状态抽走"处理) |

### 1.2 docs/main-governance.md(239 行)= A 主控专属(子 agent 永不读)

| 节 | 行号 | 性质 | 备注 |
|---|---|---|---|
| 头部导语 | 1-5 | [通] | "子 agent 永不读"设计=通用 |
| COMPACT 恢复第一动作 | 9-17 | [混] | 5 步机制通用;TASKS/NOTES/jsonl 路径=Claude Code 机制(可移植);L28 教训=项目 |
| §1 开工先读(主控版) | 19-21 | [通] | — |
| §2 监管+loop | 22-31 | [通] | — |
| §3 不冲突就并行派 | 32-37 | [通] | — |
| §4 杜绝 token 浪费 | 38-43 | [通] | — |
| §7 memory 读+落档写 | 44-53 | [混] | 两条规则通用;NOTES/TASKS/scripts/tasks_archive.py/cron id=项目 |
| §11 子 agent 卡死/429 | 54-71 | [混] | 机制主体通用(轮询/唤醒/resume 口径);cron 参数/harness 细节可移植;项目教训日期=项目 |
| §15 回归复查+改动分级 | 72-91 | [混] | A/B/C 分级+回归三层=通用;board_etf_map/main-merge.sh/smoke-checklist=项目 |
| §16 角色画像与协作 | 92-137 | [混] | 角色分工+prompt 写作=通用;thinking 配置/notify.py/app.js 1.3MB=项目 |
| §19 自我成长机制 | 138-163 | [混] | 每日/每周 review 机制通用;cron id/memory 工具=项目 |
| §20 快速上手引导机制 | 164-181 | [混] | "绕弯路→写速查"通用;agent-quickstart.md 文件名=项目 |
| §18.1 主控专属教训 28 条 | 184-218 | [混] | 结构与 G-M 通用化范式一致;条目内容需去业务化(v1.1.0/L35 Explore=项目) |
| §18.2 主控调度视角:团队协作 | 222-231 | [混] | 机制通用;pending-features-index.md 文件名=项目 |
| 验收铁律 | 234-235 | [通] | — |
| 与角色 skill 边界 | 237-239 | [通] | — |

### 1.3 四个 role skill(共 641 行)

| 文件 | 行数 | 性质分布 | 关键项目依赖节 |
|---|---|---|---|
| role-implementer/SKILL.md | 193 | 混合为主(~50% 混/40% 通/10% 项) | §1 单版前端(static-site/trade-data cwd)、§1.1 防撕裂(§24 全文版)、§3 上线操作(main-merge.sh/域名)、§3.1 R2 架构(全项目)、§7 教训 21 条 |
| role-reviewer/SKILL.md | 213 | 通用为底(~60% 通) | §2 分级/§3 回归三层(board_etf_map)、§5.2 前端四查、§7 教训、§10.x 方法论(10.1-10.6 通用度高) |
| role-researcher/SKILL.md | 100 | 通用为主(~70% 通) | §5 教训 8 条(去业务化即可);§1-§4 方法论全通用 |
| role-tester/SKILL.md | 135 | 混合(~50% 通) | §1 smoke 清单、§2 check_data_integrity、§2.1 Playwright 脚本路径、§3 三查(域名)、§5.x 方法论通用 |

> 共同结构:frontmatter(name/description)+「关联规范源」段(§23.8 机制,通用)+ 正文节 + 「相关文件指针」段(项目文档名)。

### 1.4 四个 agent 定义(共 111 行,26-30 行/个)

| 文件 | 行数 | 性质 | 备注 |
|---|---|---|---|
| implementer.md / reviewer.md / researcher.md / tester.md | 30/28/26/27 | [混] | 角色职责描述=通用;frontmatter(tools/skills/effort)机制=Claude Code 通用;**描述里引用的节号(§9/§21/§8§14)=项目节号,通用版需改为新节号或描述性文字**;正文"适用根 CLAUDE.md 共享核心"段=通用 |

### 1.5 配套文档(共 958 行,按需查档,非每会话注入)

| 文件 | 行数 | 性质 | 建议去向 |
|---|---|---|---|
| docs/pre-release-quality-flow.md | 88 | [通] 为主 | 6 关流程=极强通用骨架;进新目录 docs/quality-flow.md(去化节号/时点/CI 细节) |
| docs/role-based-context-research.md | 207 | [混] | ②③ 章节(Claude Code 机制实证+业界 AGENTS.md/Cursor 对比)=通用;④ 本项目方案=项目;提为 design 文档 |
| docs/thinking-off-optimization.md | 324 | [项] 为主 | 结论表(§四"哪些值得关")可抽出为通用小节;其余为 glm-5.2/方舟/deepseek 实测记录,不进通用版(属项目环境经验) |
| .agents/codex-reviewer/SKILL.md | 237 | [混] | worktree 绝对路径/项目教训编号=项目;审查方法论(CX-001~008、反幻觉证据规则、入口三问)=通用;建议作为"可选加装件"单列 |
| docs/active-rules-archive.md | 102 | [混] | §23.1-23.12-1 全文下沉;通用版把"铁律正文"并入对应文件,"项目验收口径 9.1-9.6"归 PROJECT-SPECIFIC |

---

## 2. 三个旧镜像目录盘点

### 2.1 总览

| 目录 | 文件数 | 总行数(正文) | 定位 | 最后 commit | 去项目化程度 |
|---|---|---|---|---|---|
| `claude-work-mode/` | 28(含 18 个 config-snapshots JSON) | ~1671 行(正文) | 本仓规范的**镜像备份包**(通用+项目专项双文件分离) | 7f2014f62 2026-10-05(但那是快照自动追加;规范内容最后同步 2026-09-28) | **低**(照抄+分文件,残留大量项目实体) |
| `collab-standard-claude/` | 14 | ~1457 行 | **纯通用去业务化标准包**(Claude 版) | 2a305e91e 2026-09-28(创建于 09-21) | **高**(项目词残留仅 2 处=README git 链接) |
| `collab-standard-codex/` | 11 | ~1358 行 | 同上(Codex 版,与 claude 版对等) | a763a9110 2026-09-21 | **高**(同 claude 版) |

证据:`find <目录> -type f | wc -l`、`wc -l` 逐文件、`git log -1 --format='%h %ad %s' -- <目录>/`。

### 2.2 claude-work-mode/(镜像备份模式)

文件树:
```
claude-work-mode/
├── CLAUDE.md              274 行  # "通用"CLAUDE.md(实为摘要级通用化,教训表全带项目实体)
├── PROJECT-SPECIFIC.md    238 行  # trade 项目专项(域名/DB/数据产物/采集脚本/定时任务/R2/基准定义)
├── README.md              435 行  # 使用说明+移植三步+章节映射表+同步约定+命中率走势(项目工作表)
├── config-snapshots/*.json ×17    # 每日"模型/端点"去敏快照(自动追加,非规范正文)
└── .claude/
    ├── agents/{implementer,reviewer,researcher,tester}.md ×4
    └── skills/role-{implementer,reviewer,researcher,tester}/SKILL.md ×4
```
特点(证据:`head -60 claude-work-mode/README.md` L33-39;`claude-work-mode/CLAUDE.md` 行内抽样):
- 设计意图=「通用部分进 CLAUDE.md、项目部分进 PROJECT-SPECIFIC.md」双文件;根文件使用了 `<占位符>`(如 `<docs/main-governance.md>`),但**教训/铁律正文里的项目实体大量保留**(如 L47 表:baostock 封禁/daily-brief/v1.1.0;§23.6 入样宇宙全文;grep 实测:ss.fx8.store 9 处/kelly 20 处/ETF 23 处/overview.json 11 处/board_etf_map 18 处,涉及 4-6 个文件)。
- 独有价值三点:①完整执行层镜像(agents+skills 全文件,移植即整体回拷);②README 的「章节映射表」(根 CLAUDE.md→通用/专项/skill 的逐节对照,149-177 行);③「同步约定」(178-184 行)+「重要说明」(185-194 行)的维护纪律。
- 缺点:名实不符("通用 CLAUDE.md"里夹杂项目教训);与 collab 两包职责重叠;README 内嵌"命中率走势"项目工作表(194 行起,与包用途无关)。

### 2.3 collab-standard-claude/(通用标准模式,Claude 版)

文件树:
```
collab-standard-claude/
├── README.md                     131 行  # 拓扑+快速启动话术+三分类方法论+安装四件套+双 agent 对等表
├── CLAUDE.md                     189 行  # C 共享核心(去业务化)
├── docs/
│   ├── main-governance.md        196 行  # A 主控层
│   ├── lessons-index.md          131 行  # 防重犯索引(重编为 G-M/G-I/G-R/G-T 通用锚点)
│   └── role-based-context-design.md 112 行 # 为什么三分类+机制实证
├── templates/PROJECT-SPECIFIC.template.md 107 行 # 占位符骨架(含"状态型内容维护纪律")
├── .claude/agents/{...}.md ×4
└── .claude/skills/role-{...}/SKILL.md ×4
```
去化手法(证据:全文阅读 `collab-standard-claude/CLAUDE.md`):
- 项目实体→`<占位符>`:如 `<部署脚本>`/`<前端公示JS文件>`/`<主域名> 优先/<备站1>/<备站2>`(L105-106)、`<PROJECT-SPECIFIC.md 测试基准爆发>`(L79,注意此处有笔误"爆发"疑为"节")。
- 教训表→重编通用锚点:`lessons-index.md` 用 G-M01~G-M16(主控)/G-I01~G-I18(实施)/G-R01~G-R10(调研)…逐条剥离业务实体(如"信号凯利回测"→"回测/测试")。
- 节号重排:把根 §18 索引表替换为 §26 防重犯机制概要;把 implementer skill §6.5 提升为共享核心 §9(七级阶梯)/§10(破缓存)——⚠️ 这一提升是**设计选择**(理由:执行类高频约定),实施新蒸馏时需复核是否维持(见 §4.3)。
- 实测残留:全包 grep 项目词仅 `trade-data-signal` 2 处(README 的 git 链接,属必要引用)。

### 2.4 collab-standard-codex/(通用标准模式,Codex 版)

文件树:`README.md` 124 + `AGENTS.md` 189(≈claude 版 CLAUDE.md)+ `docs/{lessons-index 131,role-based-context-design 36,main-governance 224}` + `.codex/config.toml`(~40)+ `.codex/skills/role-*` ×4 + `templates/PROJECT-SPECIFIC.template.md` 107。
与 claude 版的关系(证据:md5 + diff):
- **完全相同**:`docs/lessons-index.md`、`templates/PROJECT-SPECIFIC.template.md`(md5 一致)。
- **工具适配改写**:AGENTS.md/CLAUDE.md、main-governance、role-based-context-design(36 行精简版)、skills ×4(如 implementer skill 顶上改为"快速勾选"清单式,角色改称"并发执行会话",机制表述替换 subagent→multi_agent/codex exec)。
- 停点 2026-09-21,连 09-28 的悬空引用修复也没有跟随。

### 2.5 差距清单(三个包 vs 当前 10-14 规范;只列"缺什么",不列完全无关项)

**公共缺口(三个包全缺,均为 10 月增量)**:
- 根 §5.7(方案=可证伪承诺,2026-10-14)、§5.8(上线前 6 关,2026-10-14)、§25(删除前必备份,2026-10-01)
- `docs/pre-release-quality-flow.md`(2026-10-14 定稿)全文件
- reviewer skill §10.7(方案可证伪性审查)、§10.8(边界完整性独立复核)(2026-10-14)
- tester skill §5.3.1(边界维度清单穷举)(2026-10-14)
- implementer/CLAUDE 的 10-07 更新:push main 后 CI 自查(ci_selfcheck.sh)
- implementer §3 续跑同任务延续原 feat 分支(2026-09-23)

**claude-work-mode 单独缺口(相对当前)**:
- 根文件:§25、§5.7、§5.8、Compact Instructions 节(实测 `comm` 对比:root 有而 cwm 缺 = `25./5.7/5.8`)
- skills:implementer 缺 10 月更新(101 行 diff);reviewer 缺 §10.7/§10.8(137 行 diff);tester 缺 §5.3.1(41 行 diff);researcher 33 行 diff(多为小改)
- 亮点:它的 skills 是"照抄项目版"故与当前差异最小(结构全同,只欠 10 月增量)

**collab-standard-claude 单独缺口**:
- 根 CLAUDE.md:`comm` 对比根实测缺 `14./18./23.6/23.11/23.12-1/23.13/23.14/23.15/24./5.6/5.7/5.8`;其中 §5.6/23.6 属"有意剔除"(项目特定),§5.7/5.8/24 属"未及同步",§23.11(部分吸收进 §8 bullet)/§23.13/23.15(散见)/§18(改成 §26)属"重构吸收"
- skills:reviewer 缺 §5.2(前端四查)/§10.7/§10.8;tester 缺 §5.3.1;implementer 缺 §1.1 前端防撕裂全文(被简化吸收为 §1+§3.1)、缺 09-23/10-07 更新
- lessons-index:缺 2026-09-21 之后新增的教训条目(L48 通知脚本自测打桩/L49 假样本养绿/L50 探针不执行生产脚本/10 月各项)

**collab-standard-codex 单独缺口**:同 claude 版,另缺 09-28 的悬空引用修复;停点最早(09-21)。

### 2.6 彼此重复内容盘点(三边对照)

| 重复块 | 三边都有? | 说明 |
|---|---|---|
| 共享核心正文(CLAUDE.md/AGENTS.md) | 是(3 版) | claude-work-mode 版(274 行,项目实体多)/collab-claude 版(189)/collab-codex 版(189,≈同 collab-claude) |
| 4 个 agent 定义 | 是(3 版) | 内容近同源;claude-work-mode 版 tool 列表同、描述内节号略旧;collab 版已去化 |
| 4 个 role skill | 是(4 版:当前+3 包) | 同源不同刻度:当前=项目版最新;cwm=项目版 09-28 快照;collab 两版=去化重写(09-21 基底) |
| 主控 governance | cwm 包不含独立 governance(它的主控规范靠根仓库本身);collab 两包各 1 版(196/224 行) | collab 两版内容内核一致 |
| lessons-index / PROJECT-SPECIFIC 模板 | collab 两包一致(md5 相同) | 见 §2.4 |
| README | 3 版各自独立 | cwm 版最全(含映射表+同步约定);collab 版含安装四件套+启动话术 |

结论:三包重复率高(执行层 8 文件×3 版 + 共享核心×3 版),**维护成本 = 3 倍同步工时**,这正是"新蒸馏一版取代旧三者重叠职责"的事实依据。

---

## 3. 分离判据(可执行规则,直接交实施方照做)

### 3.1 一句话判据

**「保留可复用的判据/流程/红线;剔除可替换的事实/实体/编号;混合节 = 留铁律句 + 抽走项目例 + 用 `<占位符>` 接上。」**

判定单句口诀(实施时逐句念):**这句话换一个项目还能不能原样成立?** 能 → 保留;要改几个词才能成立 → 改占位符;**整句都是这个项目的事 → 剔除**(内容移入模板示例或直接删)。

### 3.2 实体处置规则表(9 类,逐类给处理方式 + 正反例)

| # | 实体类型 | 处理方式 | 例(原→改) | 实测规模(§5.2) |
|---|---|---|---|---|
| 1 | 域名/URL(ss.fx8.store 等) | 全部→占位符 | `ss.fx8.store CF 主站优先 / sss.sugas.site / s.sugas.site` → `<主域名> 优先 / <备站1> / <备站2>` | 16 处 |
| 2 | 脚本/路径(scripts/xx.py、/Users/…) | 抽象为角色化占位符或去掉具体名 | `scripts/main-merge.sh` → `<主分支合并统一脚本>`;`/Users/linhuichen/...` → 删 | 27 处 |
| 3 | 数据产物/表/字段(board_etf_map.json、sentiment.db) | 抽象为类别词或占位符 | `board_etf_map.json 空key占比<30%` → `<关键数据产物> 空 key 占比 <阈值>`(阈值示例可留,标注"示例") | ~45 处 |
| 4 | 业务算法/信号名(kelly/凯利/track_score/入样宇宙) | 抽象为功能类目 | `动「AI 推荐/降亏过滤」核心功能` → `动「核心推荐/过滤」类核心功能`(collab 已示范);`信号凯利回测「入样宇宙规则」`整节 → 抽象为「回测样本宇宙规则治理」或剔除 | ~36 处 |
| 5 | 具体时点数字(15:35/17:50/23:00) | 抽象为原则+占位符 | `盘后时点(15:35/16:00/17:50/20:35/22:00)不推 main` → `<盘后任务时点列表> 不推 main;安全窗口 <安全起始时点> 后` | 33 处 |
| 6 | 任务/事故编号(#252、L48、CX-001) | L/CX 锚点保留(带"该项目的教训索引"说明),任务编号 #NNN 删 | `#196 新增 check_failed_units.py` → 去编号留方法论 | 11(+L 锚点数十处) |
| 7 | memory 名(`test-baseline-v112-anchor` 等) | →`<项目专项文档>` 占位符;或删"memory"机制改用"项目活文档" | `权威见 memory test-baseline-v112-anchor` → `权威见项目专项的基准定义(<PROJECT-SPECIFIC.md 对应节>)` | 18 处(9 个名) |
| 8 | 项目文档名(docs/smoke-checklist.md、agent-quickstart.md 等) | →占位符或通用名 | `docs/smoke-checklist.md` → `<项目冒烟测试清单>` | ~70 处 |
| 9 | 业务词(ETF/情绪/采集/盘中/交易日/飞书) | 语境判断:方法论证言里可保留(如"盘中 vs 盘后/非交易日"=通用测试维度);业务实体处→抽象 | `分时图hover/情绪分/信号` → `<关键功能点举例>` | ~170 处 |

### 3.3 保留清单(必须原样保留原文/仅改节号)

- 全部"红线/铁律"的方法论内核:主控只调度不实施、派单三件套(机制)、修 bug 三铁律、举一反三、冻结契约、git 绝不静默、删除前必备份、验收铁律、口径三源核对、上线完整版、防前视三机检、方案三件(§5.7)、6 关流程。
- 全部"角色方法论":researcher §1-§4/§3.1/§3.2/§3.2b、reviewer §10.1-§10.8、tester §5.1-§5.4/§5.3.1、implementer §5/§6/§6.5。
- 全部"机制说明":Claude Code 角色注入机制(agents+skills 字段)、token 优化 6 条、防重犯索引机制(锚点+反追+复发强化)、memory 读优化+落档写保障(两规则本身)。
- 全部"验收口径"句(「自验须含…」「缺=验收不过」)=通用模式,保留。

### 3.4 混合节改写四手法(实施时按序选)

1. **铁律句原样 + 项目例改"示例(某项目)"或抽走为模板条目**(占比最高;如 §22/§24/§25)。
2. **机制叙述保留 + 具体配置值摘走**(如 §0.2 保留"进度文件+cron 兜底"机制,摘走 hook 脚本名/分钟档 → 或保留为"示例参数")。
3. **教训表整表重编通用锚点**(照 collab lessons-index 的 G-M/G-I/G-R/G-T 范式,已在 2.3 验证)。
4. **整节属项目业务 → 剔除;内容若仍想给读者看 → 移入 PROJECT-SPECIFIC.template 的示例注释**。

### 3.5 边界约定(易踩的四个坑)

1. **日期戳处理**:保留日期(它是规范演进史,不碍移植)但把"用户"泛化?→ **建议保留原文**("2026-08-12 用户定"直接留),理由:旧包先例 collab 版即保留日期;改日期反而丢失可追溯性。只需保证日期后的**内容**已去化。
2. **Claude Code 专属机制不算"项目特定"**:agent 定义/hook/skills 字段/subagent 通知机制属于"同平台通用"(目标读者=Claude Code 用户),保留;被抽象的是"配置值/具体脚本名"。
3. **教训锚点 id(L48 等)保留**:它是"索引→原文"机制的齿轮,但需在索引文件头声明「锚点原文在被蒸馏项目的归档,新项目从零积累自己的锚点」——collab lessons-index 已示范此声明写法。
4. **"示例"必须显式标注**:凡保留的项目式举例(如阈值数字),加"(示例,按项目替换)"标记,否则机检会误判为残留、读者会误当规范。

---

## 4. 建议的新目录结构

### 4.1 推荐方案 A:新建单一目录 `work-mode-standard/`(三分类 ABC 骨架)

**为什么推荐这个**:collab-standard-claude 的骨架已被验证"可移植+可安装"(README 四件套+模板+去化实测仅 2 处残留),缺的只是 ①10 月增量同步 ②吸收 cwm 的完整执行层镜像与映射表;claude-work-mode 的"镜像"思路不能直接当通用版(项目实体混排),但它的"整体回拷+章节映射+同步约定"正是通用版该有的可用性。

建议目录名:`work-mode-standard/`(备选名 `agent-collab-standard/`;命名规则=一眼可知"工作模式标准",避免旧名 collab-standard-* 的"双包对等"历史包袱)。

```
work-mode-standard/
├── README.md                              ~200 行  # 入口:定位/拓扑/三分类方法论/安装四件套(cp 命令)/给新项目 Claude 的启动话术/维护约定/章节映射表(吸收 cwm 149-177 行体例)
├── CLAUDE.md                              ~200 行  # C 共享核心(以 collab-claude 版 189 行为底 + 补 §5.7/§5.8/§25 + 复核 §9/§10 提级)
├── docs/
│   ├── main-governance.md                 ~200 行  # A 主控层(collab 版 196 行 + 补 10 月更新:§11/§16 的时间约束条)
│   ├── quality-flow.md                    ~90 行   # 上线前 6 关流程(来源:docs/pre-release-quality-flow.md 去化版,节号改指新目录各节)
│   ├── lessons-index.md                   ~170 行  # 防重犯索引(collab 版 131 行 + 追加 09-21→10-14 教训的 G 锚点重编)
│   └── role-based-context-design.md       ~100 行  # 设计依据(来源:docs/role-based-context-research.md ②③④的机制实证部分)
├── .claude/
│   ├── agents/{implementer,reviewer,researcher,tester}.md   ×4 (~30 行/个,近当前版原文,去节号改指新目录)
│   └── skills/
│       ├── role-implementer/SKILL.md      ~170 行  # collab 版 140 为底 + 补 §1.1 防撕裂(+根§24 机制①~⑤)、§3 的 CI 自查/续跑分支条、§3.2 联动
│       ├── role-reviewer/SKILL.md         ~200 行  # collab 版 161 为底 + 补 §5.2 四查、§10.7、§10.8
│       ├── role-researcher/SKILL.md       ~95 行   # collab 版 87 为底(近全通用,小补即可)
│       └── role-tester/SKILL.md           ~130 行  # collab 版 96 为底 + 补 §5.3.1、CI 可跑约束
└── templates/
    ├── PROJECT-SPECIFIC.template.md       ~110 行  # collab 模板(含"状态型内容维护纪律",已较完善)
    └── (可选)quality-flow 项目化注记      # 在模板内增一节"质量流程项目化"(时点/CI/域名填法)
```

**逐文件来源映射**(节级):

| 新文件 | 主要来源 | 需补/需改 |
|---|---|---|
| CLAUDE.md | `collab-standard-claude/CLAUDE.md`(189 行,底) | 补:§5.7/§5.8/§25 全文(从根 CLAUDE.md 97-110/111-118/259-269 去化);复核 §9(七级阶梯)/§10(破缓存)是否保留提级;§26 补 10 月教训机制更新(L48-L50 的"条款→机制"表述,如"被违反≥2次=条款无效必须重写"已有) |
| docs/main-governance.md | `collab-standard-claude/docs/main-governance.md`(196 行,底) | 补:§11 通知兜底机制的 10-07 子 agent 收工纪律(timeout 约束/残留后台声明);§16 派单 timeout 约束;§15 的"CI 必须真绿" |
| docs/quality-flow.md | `docs/pre-release-quality-flow.md`(88 行) | 去化:§号引用改指新目录节;时点数字占位;"CI 环境差异(CI 只装 pytest…)"改为通用表述 |
| docs/lessons-index.md | `collab-standard-claude/docs/lessons-index.md`(131 行,底) | 追加:09-21 后教训(通知脚本自测打桩/假样本养绿/探针不执行生产脚本/10-14 双条)编成新 G 锚点;更新"缺 09-21 后条目" |
| skills ×4 | collab 版为底 + 当前版做增量来源 | 见上表各行 |
| agents ×4 | 当前 `.claude/agents/*.md`(近通用) | 描述里节号(§9/§21/§8§14)改指新目录节 |
| templates | `collab-standard-claude/templates/PROJECT-SPECIFIC.template.md`(107 行) | 微调:补质量流程项目化节 |

**预估总行数**:~1400-1600 行(≈当前项目版 2232 行的 70%)。

**其他项目拿走后怎么用(上手指引组织)**:
1. README 第 1 屏放「给新项目的一段话」(直接复制粘贴给新项目 Claude 会话——复用 collab 版话术体例,README.md 60-70 行,更新指向本目录);
2. 安装四件套(cp 命令:①CLAUDE.md ②.claude/agents+skills ③docs 三件 ④模板填 PROJECT-SPECIFIC);
3. 项目专项填写指引(模板内逐节 `<占位符>` 说明 + "不适用的章节可删");
4. 维护约定(吸收 cwm 体例:本项目改动后定期同步;或"改动即同步";加"通用版不写死状态型内容"纪律)。

### 4.2 备选方案 B(二选一)

**B1:双 agent 对等包(沿用现有 collab-standard-{claude,codex} 双目录形态,只做"新版更新")**
- 形态:更新两个旧目录(而不是新建),claude 包吸收 §4.1 全部更新;codex 包同步镜像(md5 一致的共享文件 + 工具适配层)。
- 适合:确实有"用 Codex 当主会话跑同套规范"的需求(现状代码库已有 .agents/codex-reviewer,说明有 Codex 外审场景)。
- 代价:维护成本 ×2(每次更新要出两份);本次蒸馏工作量 ≈ 推荐方案的 1.7 倍。

**B2:原地增强,不新建目录(直接更新 collab-standard-claude 并改名/重写 README)**
- 形态:Treat 现有目录为草稿,直接改造。
- 优点:省一次目录搬迁。
- 缺点:①目录名与历史包袱(collab-standard-* 已带"对等双包"语义)②用户明确要求"新蒸馏一版"③旧目录同时保留会造成"三个分发副本"变"四个"。→ 不推荐。

### 4.3 取舍说明(为什么这么分,不这么分的代价)

| 决策点 | 选择 | 理由 | 不这么做的代价 |
|---|---|---|---|
| 以 collab 版为底 vs 以 cwm 版为底 | collab 版 | 去化实测仅 2 处残留;cwm 版是镜像包,去化需重做且教训表全带项目实体 | 用 cwm 为底 = 先花大量工时去化,再发现结构不如 collab 清晰 |
| 单包 vs 双包(claude+codex) | 单包为主,B1 作备选 | 用户要求"一个通用版";Codex 适配的增量=AGENTS.md 改名+skill 措辞,可在 README 附"Codex 适配指引"覆盖 | 双包 = 每次更新双份维护;且 Codex 侧现状(09-21 停点)已说明其维护投入不足 |
| 保留完整执行层(agents+skills 实体文件)vs 只给"参考文本" | 保留完整文件 | ①skills 字段启动注入需要真实文件才能生效(拿走即用)②两种用法兼容(直接装/仅参考) | 只给文本 = 每个新项目自己重排文件结构,易漏 skills 字段接线(cwm README 明确"只拷根文件=子 agent 无角色执行层") |
| 教训表放 CLAUDE.md vs 独立 lessons-index | 独立文件 | 根文件必须小(对子 agent 无条件全量注入);索引+反追机制不变 | 放根文件 = 每会话白付 token(与 §5.5 精神冲突) |
| §9/§10(七级阶梯/破缓存)是否维持"提升进共享核心" | 复核后定(建议维持) | collab 版的设计判断:执行类高频约定放共享核心→所有角色可见;但这是 project 侧决策,通用版应保留(它们本身通用) | 维持不改动的风险低;若移回 skill 需同步改多处引用(代价>收益) |
| 待旧三包处置 | 建议:cwm 保留为"本仓镜像备份"(继续每日快照用途);collab 两包**归档或冻结**(标注"已被 work-mode-standard 取代") | 避免四份副本并存;cwm 的快照机制与本仓运维绑定,不动 | 四份并存 = 下次同步又漏一处(正是 L41 教训"同步验收做窄"的复发场景) |

---

## 5. 项目编号/路径依赖扫描(方法 + 预估残留量)

### 5.1 扫描命令集(可复制,供实施后机检逐条跑)

```bash
# 设 NEW=新目录路径(如 work-mode-standard)
# ① 域名/URL 残留(应=0,除非显式"示例")
grep -rnoE '(https?://[^ )>`"]+|[a-z0-9-]+\.(store|site|com|cn|net|io|dev)\b)' "$NEW" | grep -v '示例'
# ② 脚本/项目路径
grep -rnoE '(\.claude|scripts|static-site|trade-data)/[A-Za-z0-9_./-]+' "$NEW"
# ③ 任务/事故编号
grep -rnoE '#[0-9]{1,4}\b' "$NEW"
# ④ memory 名 / memory 引用
grep -rnoE '(memory `[a-z0-9-]+`|\[\[[a-z0-9-]+\]\])' "$NEW"
# ⑤ 业务词黑名单(按项调;命中处人工判是"通用示例"还是"残留")
grep -rniE 'kelly|凯利|baostock|deepseek|feishu|飞书|board_etf_map|sentiment\.db|overview\.json|nav_bucket|signal_kelly|intraday|ss\.fx8|sugas' "$NEW"
# ⑥ 时点数字(HH:MM)
grep -rnoE '\b([01][0-9]|2[0-3]):[0-5][0-9]\b' "$NEW"
# ⑦ 机器绝对路径
grep -rnoE '/Users/[A-Za-z0-9._-]+/' "$NEW"
# ⑧ 数据产物/表名(样本)
grep -rniE '\.json|\.db|\.parquet' "$NEW" | grep -v '示例'
# ⑨ 复查占位符合规(正向:应当都被 <...> 形式包裹)
grep -roE '<[^>]{2,30}>' "$NEW" | sort | uniq -c | sort -rn
```

判据:**①③④⑦ 必须 0 残留;②⑤⑥⑧ 允许"带「示例」标注"的少量存在;⑨ 白名单核对(占位符命名统一)。**
建议(后续可做,不在本次范围):仿 `scripts/check_doc_staleness.py` 的范式(过时口径做 merge 硬闸门,docstring 见 scripts/check_doc_staleness.py 1-40 行)写一个 `check_distill_residue.py` 挂 merge 链,把黑名单硬编码进脚本,防日后回填。

### 5.2 现状基线(对 10 个源文件 + 4 个 agent 定义实测;实施后目标=归零/占位化)

| 类别 | 实测处数 | 备注 |
|---|---|---|
| 域名式串 | 16 | ss.fx8.store 5 / sss.sugas.site 4 / s.sugas.site 4 / ssd.fx8.store 3 |
| scripts/ 路径 | 27 | 去重 15 个:main-merge.sh 7 / playwright-accept 3+ / upload_r2.py 2 / deploy.sh 2 / ci_selfcheck.sh 2 / agent_dispatch_cron_reminder.py 2 / … |
| #NNN 编号 | 11 | #90×3 / #223/#203/#196/#195/#194/#12/#11/#10 各 1 |
| memory 名 | 18 | 9 个名:test-baseline-v112-anchor×4 / local-dev-cloud-prod-split×3 / deploy-cdn-stale-snapshot-blue-screen×3 / repro-script-second-implementation-drift×2 / emergency-heal-respect-schedule-window×2 / … |
| docs/ 引用 | ~70 | agent-quickstart 13 / smoke-checklist 9 / main-governance 9 / archive/CLAUDE-errors 9 / active-rules-archive 9 / pending-features-index 5 / … |
| 数据产物/表名 | ~45 | board_etf_map 9+3 / sentiment.db 6 / overview.json 6 / intraday_snapshot 5+2 / signal_stats 3+ / etf_index_map 3 / public_fund 2+2 / a-stock-3m 2 / nav_bucket 1 / mine10_features 1 |
| 业务词 | ~170 | 回测 57 / 信号 28 / etf 24+ETF 20 / 盘中 19 / 交易日 15 / kelly 14 / 采集 8 / 情绪 3 / 凯利 2 |
| 时点数字 | 33 | 17:50×9 / 15:35×6 / 20:35×5 / 23:00×5 / 16:00×4 / 22:00×4 |
| **合计** | **约 390 处** | 去重后不同实体约 100 个 |
> 注:上表是"现状基线"(说明蒸馏的加工面);新目录不要求把这些复制一遍再改——**以 collab 版(残留≈0)为底 + 增量补充**可将加工面压到不足 100 处(主要是 10 月新增条款的项目依赖)。若以 cwm 版为底则需加工全量 390 处。

### 5.3 实施后机检设计(PASS 判据)

1. 跑 §5.1 ①③④⑦ 四组命令,输出为空=硬残留 PASS;
2. ②⑤⑥⑧ 的每条命中必须落在"显式标注示例"或"通用语境"(如"盘中/盘后/非交易日"作为测试维度轴)= PASS,否则 FAIL;
3. 占位符命名集合人工过一遍(统一 `<主域名>/<部署脚本>/<数据产物目录>` 风格);
4. 增量来源核验:新目录的每处 10 月新增内容,对照 §2.5 公共缺口清单逐条打勾(缺项=验收不过)。

---

## 6. 证据附录(关键命令与原始输出摘要)

- 行数:`wc -l` 对 10 源文件(见 §1 各表),总计 2232 行;三包行数见 §2.1。
- 骨架:`grep -n -E '^#{1,4} '` 对各文件(报告 §1/§2 的行号即此输出)。
- 差距:`comm -23 <(sort 根节号) <(sort 包节号)` 得到"根有包缺"清单(root vs cwm = `25./5.7/5.8`;root vs collab-claude = `14./18./23.6/23.11/23.12-1/23.13/23.14/23.15/24./5.6/5.7/5.8`)。
- 重复:`md5 -q` + `diff | grep -c '^[<>]'`:collab 两包的 lessons-index/PROJECT-SPECIFIC.template md5 相同;skills diff = implementer 254 行 / reviewer 100 / researcher 41 / tester 42(collab-claude vs codex)。
- 残留:§5.2 各计数命令(`grep -hoE` 单文件循环 + 去重 `sort | uniq -c`)。
- 包历史:`git log -1 --format='%h %ad %s' --date=short -- <目录>/` 三包实测:cwm=7f2014f62(10-05,快照自动追加);规范内容最后同步 = 09-28 三轮修复(9a229de43/8b2ecda22/df643e112);collab-claude=2a305e91e(09-28);collab-codex=a763a9110(09-21)。
- 相关机检范式参照:`scripts/check_doc_staleness.py`(过时口径 merge 硬闸门,行级豁免 vs 词级豁免的权衡记录在脚本 docstring 28-40 行)。

---

## 附:本报告未做/待主控决断项(诚实标注)

1. **§9/§10 提级保留与否**(七级阶梯/破缓存放共享核心):collab 版的设计选择,建议维持,但属可辩论项(§4.3)。
2. **Codex 侧要不要同步出新版**:本报告推荐单包+适配指引;若用户要"双 agent 对等",走 §4.2 B1。
3. **旧三包处置**(cwm 保留/collab 两包冻结归档):建议本身需用户确认(涉及"删/留"决策,按 §25 精神,冻结不删即可逆)。
4. **通用版是否随本仓继续演进**(维护约定二选一:定期同步 vs 改动即同步):建议"改动即同步"避免惰性漂移,代价是每次改规范多一步;最终由用户拍板。
