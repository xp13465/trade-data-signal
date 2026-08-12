# Claude 工作模式规范包

这是从实际项目（A股情绪看板 `trade`）磨合中提取的 **Claude Code 协作规范**，已同步到 **2026-08-12 角色分上下文拆分后的新版结构**。拆分后完整工作模式拓扑见下：

```
┌────────────────────────────────────────────────────────────┐
│  完整工作模式拓扑（2026-08-12 角色分上下文拆分后）            │
├────────────────────────────────────────────────────────────┤
│  根 CLAUDE.md          = 共享核心（所有角色启动自动注入）       │
│                         §0 角色速览/§1 开工先读/§6 中文/§5 调研 │
│                         §18 索引表[L01-L28]/§22 一致性/§8 §14 摘要│
│                         §21 公示指针/§23 三铁律/验收铁律        │
├────────────────────────────────────────────────────────────┤
│  .claude/agents/*.md   = 角色 agent 定义（implementer/reviewer/ │
│                          researcher/tester，skills 字段挂接）  │
│  .claude/skills/role-*/= 角色专属规范全文（经 skills 字段启动     │
│  SKILL.md                全文注入，确定性不依赖主动读）         │
├────────────────────────────────────────────────────────────┤
│  docs/main-governance.md = 主控专属规范（§2/3/4/7/11/15/16/19  │
│                          + COMPACT 恢复 5 步），主控按需 Read， │
│                          子 agent 永不读                      │
├────────────────────────────────────────────────────────────┤
│  docs/archive/CLAUDE-errors-2026-08.md = §18 教训原文全量归档   │
│  docs/smoke-checklist.md = P0/P1 主功能 smoke 清单             │
│  docs/role-based-context-research.md = 角色拆分调研报告        │
├────────────────────────────────────────────────────────────┤
│  ★ claude-work-mode/   = 本可移植备份包（本次同步主体）         │
│     CLAUDE.md（通用） + PROJECT-SPECIFIC.md（项目专项）         │
│     + README.md，跨项目复用用，非实际加载                       │
└────────────────────────────────────────────────────────────┘
```

## 包内文件

- `CLAUDE.md` - **通用工作模式规范**（可移植，无项目业务知识；项目专项配置用 `<占位符>` 标注，移植时替换为实际值）。= 根 `CLAUDE.md` 共享核心的**通用部分** + 被瘦身移出但通用可移植的章节（§9 新功能隔离/§10 破缓存/§11 子agent生命周期/§12 API错误不卡死/§13 模型约束/§15 回归分级/§16 角色画像/§17 superpowers/§19 高峰省token）
- `PROJECT-SPECIFIC.md` - **A股看板项目专项规范**（域名/DB/数据产物/采集脚本/launchd 定时任务时点/R2 架构/上传链路/§22 一致性项目化/§23 三铁律项目验收口径/角色拆分后各文件定位）
- `README.md` - 本说明文件

## 怎么用

### 给 `trade` 项目（本仓库）

根 `CLAUDE.md` 是实际加载的共享核心（角色拆分后已瘦身），`.claude/agents/` + `.claude/skills/role-*/` + `docs/main-governance.md` 是实际加载的角色/主控规范。本目录是**可移植备份包**，便于：

- 复用通用部分到其他项目时只取 `CLAUDE.md`
- 工作模式演进后，定期同步拆分到此两文件，保持备份完整

### 给自己新项目用（全局，所有项目自动加载，通用部分）

```bash
cp CLAUDE.md ~/.claude/CLAUDE.md
```

Claude Code 启动时自动加载 `~/.claude/CLAUDE.md`，对所有项目生效。移植时把 `<占位符>`（如 `<docs/main-governance.md>`/`<deploy脚本>`/`<主域名>`/`<模型名>`/`<定时任务时点>`/`<数据校验脚本>`/`<docs/smoke-checklist.md>`/`<skill库名及版本>`/`<高峰时段>`/`<任务调度器>`/`<数据产物A>`）替换为该项目的实际值，或删去不适用的章节。

### 给单个项目用（仅该项目生效，通用+该项目专项）

1. 把通用 `CLAUDE.md` 复制到项目根（或 `~/.claude/CLAUDE.md` 全局）
2. 新建项目自己的 `PROJECT-SPECIFIC.md`（参考本包 `PROJECT-SPECIFIC.md` 的结构，填该项目的域名/DB/数据产物/定时任务等）
3. 在通用 `CLAUDE.md` 里引用 `PROJECT-SPECIFIC.md`（开工先读）
4. （可选，角色化进阶）建 `.claude/agents/<role>.md` + `.claude/skills/<role>/SKILL.md` 按角色注入专属规范，见 §0 设计原则

### 给其他人用

让对方把通用 `CLAUDE.md` 内容贴到他自己的 `~/.claude/CLAUDE.md`（全局）或项目根 `CLAUDE.md`（单项目），并按上面「给单个项目用」补项目专项。

## 拆分原则（2026-08-12 更新）

- **通用部分**（可移植，无业务）：工作模式/协作机制/方法论。项目特定配置用 `<占位符>`（域名/模型名/定时任务时点/数据产物/文件名等），移植时替换。
- **项目专项**（A股看板业务）：具体域名/DB/数据产物/采集脚本/launchd 定时任务时点/技能库版本/模型提供方。
- **角色拆分核心原则**：根 CLAUDE.md 删不掉、躲不开子 agent（启动全量注入），所以根文件只留"所有角色都该无条件知道"的共享核心；角色专属规范进 `.claude/skills/<role>/SKILL.md` 经 agent 定义 `skills` 字段**启动全文注入**（确定性）；主控专属进 `docs/main-governance.md`（主控按需 Read，子 agent 永不读）。业界共识：指令文件要小、按需加载、按角色/目录拆分。

边界章节（如 §7 落档、§8 推送、§11 子 agent、§13 模型、§15 回归、§17 高峰）按「通用模式 + 专项配置」拆：通用机制放 `CLAUDE.md`，具体值/事故 id/项目文件名放 `PROJECT-SPECIFIC.md`。

## 通用规范清单（CLAUDE.md）

每条一句话：

0. **角色分上下文速览** - 5 角色上下文来源（主控=共享核心+governance / 实施·reviewer·调研·测试=共享核心+角色 skill 启动注入）
1. **开工先读** - 主控先 Read main-governance，子 agent 已注入角色 skill，再读共享核心
5. **调研后给方案** - 技术细节自定默认方案；方案选择终极完整不妥协；参数测试驱动；候选不硬选
6. **始终用中文回复**
8. **改完必须推送** - commit+push+merge main；验上线验功能生效层非代码在 main；三查清单；非-ff rebase 不强推
9. **新功能先隔离** - tab/独立表/物理隔离，验证后再融合
10. **改静态资源必须破缓存** - 版本号+SW CACHE_VERSION+min 版用字符串验证
11. **子 agent 生命周期与通知兜底** - SendMessage 主动通知 + 进度文件 + cron 轮询 + 卡死/429/came-to-rest 处理 + 中途改口径停旧派新
12. **遇 API 错误不卡死** - 换方案或暂存，能力与模式匹配
13. **模型能力约束** - 开工先确认模型能力，文本 only 禁图片
14. **生产稳定性 P0** - 主动查定时任务冲突，给时点建议
15. **主功能回归复查 + 改动分级 + reviewer** - A/B/C 级分级，reviewer agent + 数据校验 + smoke 清单
16. **agent 角色画像与 prompt 写作** - 主控 PM 定位 + 角色定义落 .claude/agents + prompt 必含项
17. **superpowers / skill 库融合** - 若装 skill 库，运维任务明示跳过 HARD-GATE，大型开发可按需用全套
18. **防重犯索引表** - L01-L28 摘要表（原文全量在 archive，grep 锚点 id 反向追）
19. **高峰时段省 token** - 若模型提供方有高峰倍率，派 agent 避开高峰
21. **算法改动同步公示** - 改算法逻辑必须同步改前端公示文案（用户铁律，已复发 2 次）
22. **数据一致性铁律** - 用户在 N 个展示位看到的数据必须统一，更新必 N 文件+N 缓存同步
23. **用户新增铁律** - 23.1 README 维护 / 23.2 修 bug 三铁律 / 23.3 举一反三
- **验收铁律** - 逐字验证关键结论，不信 agent 报告

> 注：编号继承根/旧版（§0/§1/§5/§6/§8/§9-§19/§21/§22/§23），§20（快速上手引导维护）为主控专属，在 `docs/main-governance.md`。

## 项目专项清单（PROJECT-SPECIFIC.md，trade 仓库）

0. 项目概览 + 角色拆分后工作模式拓扑（各文件定位表）
1. 项目文件结构与落档（NOTES/TASKS 历史拆分、docs/archive、docs/smoke-checklist.md）
2. 改完推送专项（3 域名 ss.fx8.store/sss.sugas.site/s.sugas.site + R2 ssd.fx8.store + deploy.sh + force push 事故 + intraday 时点 + 三查清单项目化）
3. R2 存储架构（index/industry/trade_sim/public_fund 类别 + upload_r2 命令 + 新类别上线 checklist + fetchJSON 跳 gz）
4. 单版前端铁律（static-site + trade-data cwd + build_min + bump sw + min 验证 + export 路径同步）
5. 切分支保护 DB（sentiment.db/etf_national_team.db + commit 8e3f5fa）
6. 生产稳定性 P0（launchd 定时任务时点全表：intraday 27 次 + 15:35/16:00/16:30/17:50/20:35/22:00 + daily-brief 20:40 + 23:00 安全窗口）
7. 主功能回归复查（board_etf_map.json/overview.json/intraday_snapshot.json + check_data_integrity.py + 08-06 教训）
8. §22 一致性项目专项（overview/board_etf_map/concepts 三展示位 + R2/CF 缓存）
9. §23 三铁律项目验收口径（23.1 README 现状 / 23.2 备站多模块例 / 23.3 走势图切换例）
10. 数据产物/采集脚本/定时任务速查
11. 子 agent 教训（具体 agent id：a194f/afe9/a5c6/a11439db9/a00f4f2c8b 精简留存）
12. 其他项目专项 memory 速查（含 daily-brief-deepseek 模型切换）

## 章节映射（根 CLAUDE.md → 拆分 + 角色 skill）

| 根 CLAUDE.md | 通用 CLAUDE.md | 项目专项 PROJECT-SPECIFIC.md | 角色 skill |
|---|---|---|---|
| §0 角色分上下文速览 | §0（通用化 5 角色） | §0.1（各文件定位表） | - |
| §1 开工先读 | §1 | - | - |
| §5 调研后方案（含 5.1 穷举回测） | §5（含 5.1） | - | researcher skill §3 |
| §6 中文 | §6 | - | - |
| §8 改完推送 | §8（通用+三查） | §2（域名/deploy.sh/data 路径/项目例） | implementer §3 |
| §8.1 R2 | - | §3（全 R2 内容） | implementer §3.1 |
| §9 单版前端 | §10（破缓存通用） | §4（static-site/trade-data cwd/build_min/bump sw） | implementer §1 |
| §10 切分支 DB | 历史归档引用 | §5（sentiment.db/etf_national_team.db/8e3f5fa） | - |
| §11 子 agent 卡死/429 | §11（机制） | §11（具体 agent id 教训） | 主控治理文档 |
| §12 superpowers | §17（融合规则通用） | - | - |
| §13 模型能力 | §13（通用约束） | §12（daily-brief-deepseek） | - |
| §14 生产 P0 | §14（主动查冲突通用） | §6（launchd 时点全表/23:00 窗口） | implementer §4 |
| §15 回归复查 | §15（分级/reviewer/smoke 通用） | §7（数据产物/校验脚本/08-06 教训） | reviewer skill |
| §16 agent 角色画像 | §16 | §0.1（角色定义定位） | agents/*.md 定义 |
| §17 火山方舟高峰 | §19（高峰避让通用） | §12（模型切换后注） | - |
| §18 防重犯索引 | §18（L01-L28 摘要表） | §11（agent id 教训引用） | 各 role skill 教训蒸馏 |
| §21 算法公示 | §21（指针+强化款） | - | implementer §2 |
| §22 数据一致性 | §22（通用化） | §8（三展示位项目化） | tester/reviewer 校验 |
| §23 三铁律 | §23（通用化） | §9（项目验收口径） | implementer §5/§6 |
| 验收铁律 | 验收铁律 | - | - |

## 同步约定

- **根 `CLAUDE.md`（共享核心）是 source of truth**，实际加载；`.claude/agents/` + `.claude/skills/role-*/` + `docs/main-governance.md` 承载角色/主控规范；本目录是拆分备份。
- 根 `CLAUDE.md` 或角色 skill 更新后（新增章节/教训），**定期同步**到此两文件：通用部分进 `CLAUDE.md`，项目专项进 `PROJECT-SPECIFIC.md`，并更新本 README 的清单与映射表。
- 通用 `CLAUDE.md` 的 `<占位符>` 在移植到新项目时替换；本项目专项值在 `PROJECT-SPECIFIC.md` 里是实际值。
- 角色 skill 与 quickstart 分工：quickstart=操作步骤（怎么上线/怎么验），role skill=角色职责+专属规范+专属教训；改动任一 grep 另一处同步。

## 重要说明

- 通用 `CLAUDE.md` 不含任何项目特定知识（业务逻辑、数据口径、采集脚本、策略细节等），可安全移植。
- 项目专项靠各项目自己的 `PROJECT-SPECIFIC.md` + `NOTES.md` + `TASKS.md` 沉淀，开工先读这三份。
- 本规范是「磨合出来的协作约定」，不是 Claude Code 的官方配置；可根据团队实际增删调整。
- 复制到全局 `~/.claude/CLAUDE.md` 后，若个别项目有特殊要求，可在项目根 `CLAUDE.md` 里追加覆盖。
