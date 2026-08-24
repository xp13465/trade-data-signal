# Claude 工作模式规范包

这是从实际项目（A股情绪看板 `trade`）磨合中提取的 **Claude Code 协作规范**，已同步到 **2026-08-16（角色拆分后全量同步版：含 08-12 之后新增 §0.1/§5.2-§5.5/§8.1/§23.4-§23.7/§24 等规范 + 命中率走势月度追加）**。完整工作模式拓扑见下：

```
┌────────────────────────────────────────────────────────────┐
│  完整工作模式拓扑（2026-08-12 角色分上下文拆分后）            │
├────────────────────────────────────────────────────────────┤
│  根 CLAUDE.md          = 共享核心（所有角色启动自动注入）       │
│                         §0 角色速览/§1 开工先读/§6 中文/§5 调研 │
│                         §18 索引表[L01-L39]/§22 一致性/§8 §14 摘要│
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

- `CLAUDE.md` - **通用工作模式规范**（可移植，无项目业务知识；项目专项配置用 `<占位符>` 标注，移植时替换为实际值）。= 根 `CLAUDE.md` 共享核心的**通用部分** + 被瘦身移出但通用可移植的章节（§0.1/§5.1-§5.5/§8.1/§9 隔离/§10 破缓存/§11 子agent生命周期/§12 API错误不卡死/§13 模型约束/§15 回归分级/§16 角色画像/§17 superpowers/§23.4-§23.7/§24 前端防撕裂 等）
- `PROJECT-SPECIFIC.md` - **A股看板项目专项规范**（域名/DB/数据产物/采集脚本/launchd 定时任务时点/R2 架构/上传链路/§4.1 前端防撕裂·§4.2 测试基准定义/§22 一致性项目化/§23 项目验收口径 9.1-9.6/角色拆分后各文件定位）
- `.claude/agents/ + .claude/skills/role-*/` - **角色 agent 定义 + 角色规范全文**（执行层，8 文件：`agents/{implementer,researcher,reviewer,tester}.md` 4 个 + `skills/role-{implementer,researcher,reviewer,tester}/SKILL.md` 4 个；镜像项目结构，移植时整体回拷）。agent `model:` 为项目私有配置（代理白名单），移植到其他环境按需替换
- `README.md` - 本说明文件（含 📈 命中率走势结果报告 —— claude-work-mode/ 内嵌的每日追加工作表）

## 怎么用

### 给 `trade` 项目（本仓库）

根 `CLAUDE.md` 是实际加载的共享核心（角色拆分后已瘦身），`.claude/agents/` + `.claude/skills/role-*/` + `docs/main-governance.md` 是实际加载的角色/主控规范。本目录是**可移植备份包**，便于：

- 复用通用部分到其他项目时只取 `CLAUDE.md`
- 工作模式演进后，定期同步拆分到此两文件，保持备份完整

### 给自己新项目用（全局，所有项目自动加载，通用部分）

角色化拆分后，全局部署不再只是单拷根文件——子 agent 靠 `.claude/agents/` + `.claude/skills/role-*/` 注入角色规范，只拷根文件 = 子 agent 无角色执行层。完整三步：

**① 全局共享核心**

```bash
cp CLAUDE.md ~/.claude/CLAUDE.md
```

Claude Code 启动时自动加载 `~/.claude/CLAUDE.md`，对所有项目生效，只承载"所有角色都该无条件知道"的共享核心。

**② 项目角色执行层**

```bash
cp -r .claude/agents .claude/skills <新项目根>/.claude/
```

拷贝 `.claude/agents/ + .claude/skills/role-*/` 到新项目根（角色 agent 定义 + 角色规范全文，子 agent 启动经 agent 定义 `skills` 字段全文注入；缺 = 子 agent 无角色规范）。角色层放**项目 `.claude/`** 而非全局，因为 agent 定义是项目级（`model:` 为项目私有配置），全局全拷会污染所有项目的子 agent。

**③ 项目专项**

新建 `PROJECT-SPECIFIC.md` 填项目专项（域名/DB/数据产物/定时任务时点），并在全局 `~/.claude/CLAUDE.md` 里引用它（开工先读）。

移植时把 `<占位符>`（如 `<docs/main-governance.md>`/`<deploy脚本>`/`<主域名>`/`<模型名>`/`<定时任务时点>`/`<数据校验脚本>`/`<docs/smoke-checklist.md>`/`<skill库名及版本>`/`<高峰时段>`/`<任务调度器>`/`<数据产物A>`）替换为该项目的实际值，或删去不适用的章节。

### 给单个项目用（仅该项目生效，通用+该项目专项）

1. 把通用 `CLAUDE.md` 复制到项目根（或 `~/.claude/CLAUDE.md` 全局）
2. 新建项目自己的 `PROJECT-SPECIFIC.md`（参考本包 `PROJECT-SPECIFIC.md` 的结构，填该项目的域名/DB/数据产物/定时任务等）
3. 在通用 `CLAUDE.md` 里引用 `PROJECT-SPECIFIC.md`（开工先读）
4. 建 `.claude/agents/<role>.md` + `.claude/skills/<role>/SKILL.md` 按角色注入专属规范 **（执行层必需**，不是可选——子 agent 启动经 agent 定义 `skills` 字段注入角色规范全文，缺 = 子 agent 无角色规范），可参考本包 `.claude/` 的 4 角色模板（implementer/researcher/reviewer/tester）。见 §0 设计原则

### 给其他人用

让对方一并拷贝「`CLAUDE.md`（放 `~/.claude/` 全局或项目根）」+「`.claude/agents/ + .claude/skills/role-*/`（放项目内，角色执行层）」+「新建 `PROJECT-SPECIFIC.md` 填项目专项」，再按上面「给单个项目用」整体走一遍。只贴 `CLAUDE.md` 漏掉角色执行层，子 agent 无角色规范。

## 拆分原则（2026-08-12 更新）

- **通用部分**（可移植，无业务）：工作模式/协作机制/方法论。项目特定配置用 `<占位符>`（域名/模型名/定时任务时点/数据产物/文件名等），移植时替换。
- **项目专项**（A股看板业务）：具体域名/DB/数据产物/采集脚本/launchd 定时任务时点/技能库版本/模型提供方。
- **角色拆分核心原则**：根 CLAUDE.md 删不掉、躲不开子 agent（启动全量注入），所以根文件只留"所有角色都该无条件知道"的共享核心；角色专属规范进 `.claude/skills/<role>/SKILL.md` 经 agent 定义 `skills` 字段**启动全文注入**（确定性）；主控专属进 `docs/main-governance.md`（主控按需 Read，子 agent 永不读）。业界共识：指令文件要小、按需加载、按角色/目录拆分。

边界章节（如 §7 落档、§8 推送、§11 子 agent、§13 模型、§15 回归、§17 高峰）按「通用模式 + 专项配置」拆：通用机制放 `CLAUDE.md`，具体值/事故 id/项目文件名放 `PROJECT-SPECIFIC.md`。

> **部署落点**：`~/.claude/CLAUDE.md`（全局）只承载共享核心；角色规范放**项目 `.claude/`**（`.claude/agents/` + `.claude/skills/role-*/`），因为 agent 定义是项目级（如 `model:` 代理白名单为项目私有），全局全拷会污染所有项目的子 agent。

## 通用规范清单（CLAUDE.md）

每条一句话：

0. **角色分上下文速览** - 5 角色上下文来源（主控=共享核心+governance / 实施·reviewer·调研·测试=共享核心+角色 skill 启动注入）
0.1 **主控角色红线** - 主控只调度不实施，紧急 A 级小改除外；B 级+永不碰
1. **开工先读** - 主控先 Read main-governance，子 agent 已注入角色 skill，再读共享核心
5. **调研后给方案** - 技术细节自定默认方案；方案选择终极完整不妥协；参数测试驱动；候选不硬选
  5.1 **穷举回测** - 数据回测穷举最大化铁律（用户愿意等，不留尾巴）
  5.2 **模型参数层优先** - 慢/贵先查 thinking 开关等模型参数层，再上社区查经验
  5.3 **优化核心保障** - 精简只动冗余不动核心 + 可逆 + 复查兜底
  5.4 **测试基准锚点** - 一切回测/测试以已定稿推荐最优组合为前提，偏离=违规
  5.5 **token 优化 6 条** - 输出简洁/命令静默/派单只回结论/@文件直引/小任务不spawn/失败方向rewind
6. **始终用中文回复**（附口语化）
8. **改完必须推送** - commit+push+merge main；验上线验功能生效层非代码在 main；三查清单；非-ff rebase 不强推
  8.1 **派单定位锚点** - 派单 prompt 必带 @文件:行号/符号锚点，省重读重扫 token
9. **新功能先隔离** - tab/独立表/物理隔离，验证后再融合
10. **改静态资源必须破缓存** - 版本号+SW CACHE_VERSION+min 版用字符串验证
11. **子 agent 生命周期与通知兜底** - SendMessage 主动通知 + 进度文件 + cron 轮询 + 卡死/429/came-to-rest 处理 + 中途改口径停旧派新
12. **遇 API 错误不卡死** - 换方案或暂存，能力与模式匹配
13. **模型能力约束** - 开工先确认模型能力，文本 only 禁图片
14. **生产稳定性 P0** - 主动查定时任务冲突，给时点建议
15. **主功能回归复查 + 改动分级 + reviewer** - A/B/C 级分级，reviewer agent + 数据校验 + smoke 清单
16. **agent 角色画像与 prompt 写作** - 主控 PM 定位 + 角色定义落 .claude/agents + prompt 必含项
17. **superpowers / skill 库融合** - 若装 skill 库，运维任务明示跳过 HARD-GATE，大型开发可按需用全套
18. **防重犯索引表** - L01-L39 摘要表（原文全量在 archive，grep 锚点 id 反向追）
19. **高峰时段省 token** - 若模型提供方有高峰倍率，派 agent 避开高峰
21. **算法改动同步公示** - 改算法逻辑必须同步改前端公示文案（用户铁律，已复发 2 次）
22. **数据一致性铁律** - 用户在 N 个展示位看到的数据必须统一，更新必 N 文件+N 缓存同步
23. **用户新增铁律** - 23.1 README 维护 / 23.2 修 bug 三铁律 / 23.3 举一反三 / 23.4 团队协作查已落档 / 23.5 新产物当场落档 / 23.6 入样宇宙规则 / 23.7 版本冻结契约
24. **前端部署/SW 防撕裂** - 版本串强制刷新 + SW 壳芯配套失败回退 + 部署后验哈希==引用
- **验收铁律** - 逐字验证关键结论，不信 agent 报告

> 注：编号继承根/旧版（§0/§1/§5/§6/§8/§9-§19/§21/§22/§23），§20（快速上手引导维护）为主控专属，在 `docs/main-governance.md`。

## 项目专项清单（PROJECT-SPECIFIC.md，trade 仓库）

0. 项目概览 + 角色拆分后工作模式拓扑（各文件定位表）
1. 项目文件结构与落档（NOTES/TASKS 历史拆分、docs/archive、docs/smoke-checklist.md）
2. 改完推送专项（3 域名 ss.fx8.store/sss.sugas.site/s.sugas.site + R2 ssd.fx8.store + deploy.sh + force push 事故 + intraday 时点 + 三查清单项目化）
3. R2 存储架构（index/industry/trade_sim/public_fund 类别 + upload_r2 命令 + 新类别上线 checklist + fetchJSON 跳 gz）
4. 单版前端铁律（static-site + trade-data cwd + build_min + bump sw + min 验证 + export 路径同步）
  4.1 前端部署/SW 防撕裂专项（bump_asset_version 改发布序号 + sw.js 壳芯配套 + 部署后哈希==index 校验）
  4.2 测试基准锚点专项（v1.1.1 当前基准 / v1.1.0「基础5」推荐最优组合定义 / 版本升级原则）
5. 切分支保护 DB（sentiment.db/etf_national_team.db + commit 8e3f5fa）
6. 生产稳定性 P0（launchd 定时任务时点全表：intraday 27 次 + 15:35/16:00/16:30/17:50/20:35/22:00 + daily-brief 20:40 + 23:00 安全窗口）
7. 主功能回归复查（board_etf_map.json/overview.json/intraday_snapshot.json + check_data_integrity.py + 08-06 教训）
8. §22 一致性项目专项（overview/board_etf_map/concepts 三展示位 + R2/CF 缓存）
9. §23 项目验收口径（9.1 README 现状 / 9.2 备站多模块例 / 9.3 走势图切换例 / 9.4 团队协作 / 9.5 入样宇宙规则 / 9.6 版本冻结契约）
10. 数据产物/采集脚本/定时任务速查
11. 子 agent 教训（具体 agent id：a194f/afe9/a5c6/a11439db9/a00f4f2c8b 精简留存）
12. 其他项目专项 memory 速查（含 daily-brief-deepseek 模型切换）

## 章节映射（根 CLAUDE.md → 拆分 + 角色 skill）

| 根 CLAUDE.md | 通用 CLAUDE.md | 项目专项 PROJECT-SPECIFIC.md | 角色 skill |
|---|---|---|---|
| §0 角色分上下文速览 | §0（通用化 5 角色） | §0.1（各文件定位表） | - |
| §0.1 主控角色红线 | §0.1 | -（治理文档） | - |
| §1 开工先读 | §1 | - | - |
| §5 调研后方案 | §5（含 5.1-5.5） | §4.2（测试基准定义） | researcher skill §3 |
| §6 中文（附口语化） | §6 | - | - |
| §8 改完推送 | §8（通用+三查） | §2（域名/deploy.sh/data 路径/项目例） | implementer §3 |
| §8.1 派单定位锚点 | §8.1 | - | - |
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
| §18 防重犯索引 | §18（L01-L39 摘要表） | §11（agent id 教训引用）+§9.5 | 各 role skill 教训蒸馏 |
| §21 算法公示 | §21（指针+强化款） | - | implementer §2 |
| §22 数据一致性 | §22（通用化） | §8（三展示位项目化） | tester/reviewer 校验 |
| §23 三铁律（已延至 23.7） | §23（通用化 23.1-23.7） | §9（项目验收口径 9.1-9.6） | implementer §5/§6 |
| §24 前端部署/SW 防撕裂 | §24 | §4.1（bump_asset_version/sw.js/部署校验） | implementer §1/§24 |
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

---

## 📈 命中率走势（工作模式结果报告）

> **统计口径**：命中率 = `cache_read / (cache_read + input)`（cache_read 为缓存命中读、input 为冷启动重读），按天求和聚合。**数据源** = `~/.claude/projects/-Users-linhuichen-code-trade/*.jsonl`（Claude Code 会话 JSONL，只读不改业务文件）。**纯本地统计，跑脚本不消耗任何 LLM token**。每日 23:30 由 launchd 任务 `com.trade.token-cache-stats` 自动追加当天数据（当天会话截至 23:30）。**健康标准：命中率 > 0.7**。
> **版本/改动列**：claude 版本 = 当天实际运行 `claude --version`；当日改动 = 当天 trade 仓库 `claude-work-mode/CLAUDE.md` 或根 `CLAUDE.md` 的 git commit（hash 前 8 位 + 主题），详细版本变更见下方「版本/改动日志」。
> **复现/手动追加**：`python3 scripts/token_cache_stats.py --append-daily`（追加今天）；`python3 scripts/token_cache_stats.py --append-daily <YYYY-MM-DD>`（追加指定日期）；统计报告模式（默认窗口）见 `scripts/token_cache_stats.py` 脚本 docstring。

<!-- token-cache-trend-begin -->
| 日期 | 命中率 | 冷读input | claude版本 | 当日改动 |
|---|---|---|---|---|
| 2026-08-10 | 0.9134 | 24,569,429 | — | — |
| 2026-08-11 | 0.8262 | 63,618,029 | — | — |
| 2026-08-12 | 0.8229 | 51,612,948 | — | — |
| 2026-08-13 | 0.9592 | 11,384,021 | — | — |
| 2026-08-14 | 0.9583 | 11,058,773 | — | — |
| 2026-08-15 | 0.9776 | 9,242,627 | — | — |
| 2026-08-16 | 0.9746 | 5,912,792 | 2.1.224 | e32017f69 docs(CLAUDE.md): 新增 §23.8 skill 维护同步铁律 — skill 是活资产与项目一致迭代,过时比没有更危险; f34211e79 chore(反思落档): §18 过错索引加 L41(同步任务验收口径做窄——同步 claude-work-mode 只同步根 CLAUDE.md,漏 agents/skills 执行层+README 部署指引过时,用户点破才发现)——归档锚点+主控专属表+计数40→41; a0986a60a docs(claude-work-mode): 使用指引升级为「全局共享核心+项目角色执行层+项目专项」完整部署; 8818f53c7 feat(claude-work-mode全量同步): 补全执行层 .claude/agents/ + .claude/skills/role-*/ 8 文件 (此前只同步根 CLAUDE.md, 漏了角色执行层, 拓扑图与实物脱节); 9e1243fee chore(反思落档): §18 过错索引加 L40(打tag只做点名处没举一反三,版本链v1.1.0漏打没暴露)——归档锚点+主控专属表+计数39→40; e4861253f chore(规范): 新增 §5.6 DeepSeek 官方 API 峰谷定价铁律(2026-08-17 生效)+同步 claude-work-mode; deef6c5bf chore(命中率走势): 08-16 当天数据实时刷新(0.9830)——幂等更新同一行不重复追加; 76613a2d0 chore(命中率走势): 08-16 当天数据刷新至最新(0.9828/2,937,926)+当日改动列并入新commit; 9a31f21df chore(README走势段): 补复现/手动追加命令一句(§23.5复现段); e8bbd4c1d feat(claude-work-mode全量同步+命中率走势): 08-12后新增规范同步进备份包 + token缓存命中率每日追加走势; 2bb4f1e08 chore(收尾): 标记 v1.1.1 + 补 about/privacy 版本串 a279 + TASKS 登记今日4项; b46660a1c docs(§19每日总结): 8/15当天归纳落档 — 新过错L34-L39+经验E27-E30 |
| 2026-08-18 | 0.9741 | 5,705,391 | ? | e24d42a54 docs(compact): AUTO_COMPACT_WINDOW 数字校正 600000→1048576 对齐 settings.json 实况; 222db1844 fix(构建): build_min 从 git HEAD 读源+§24⑤内容校验+deploy push 限 main 根治 min 被脏工作区覆盖; 1eec05cdd feat(kelly): v1.1.2 凯利三键改造 — excludeSpecialBear 升四档判定 + 2备选键 + 历史四档轨迹图后端 |
| 2026-08-19 | 0.9747 | 3,989,072 | ? | ce5ca8dce docs(规范+待办): 全局核心问题报告维度全铁律(§5.1⑤+researcher skill§3⑤) + 落档#69 CYB降亏新标志方向 + 新增#73 多指数四档展示; b74368b5a feat(防再犯CD): push main 统一入口 main-merge.sh + 同文件并发串行 check_file_owners(用户拍板 B 降级安全并行) |
| 2026-08-20 | 0.9869 | 746,855 | ? | cd8ea5d8e docs(CLAUDE.md): 存量修正3处(用户已拍板全修) 版本基准引用过时+§18过错索引计数; 3d9d9cdab docs(CLAUDE.md): 瘦身方案#94 A1+§5.4状态独立 删§18元信息+基准定义挪memory权威; 8cb60a5a7 docs(CLAUDE.md): §23.12 TASKS任务治理4态流转规范落档(用户2026-08-20定,task活跃/todolist远期/完成文件/归档7天) |
| 2026-08-21 | 0.1473 | 47,686,787 | ? | 无 |
| 2026-08-22 | 0.8589 | 12,999,772 | ? | 无 |
| 2026-08-23 | 0.8412 | 14,254,981 | ? | 无 |
| 2026-08-24 | 0.8757 | 16,791,771 | ? | 17e1aa2ea docs(governance): 主控过错七条缺口根治——L30/L31/L32/L33/L35/L36六条全文回填18.1+L29留指针(已全文化至根CLAUDE.md §0.1防双份分叉)+头部计数20→27(过错16+经验11自洽)+CLAUDE.md §18主控节索引行补L29例外括注; 7f05426da docs(skill+archive+governance): has_track口径P0教训全链路落档——L44入档(archive全文+锚点行+CLAUDE.md表)+四role skill各加教训条(reviewer第三方锚点/implementer开工三源对照/researcher核查分析对象/tester独立锚点机检)+零丢失等式修复(补录L43锚点行,42断链→44==44)+governance回填E25/E26/E27/E29/E30五条经验(15→20条)+reviewer双##7编号顺延修复; 278ba6c42 docs(skill): has_track口径P0教训同步执行层——reviewer新增档位语义强制第三方锚点检查+implementer新增开工三源逐字对照+CLAUDE.md §23.13反向标注(§23.8双向咬合); 677c51b89 docs(规范): §23.13 口径三源核对+不统一必上报拍板(has_track口径事故P0反思,2026-08-24用户定); f4b123a7d docs(规范): §5.4⑥发版联动清单补'全部键集登记点+机检PASS'+§22补'代码内常量登记点也是一致性对象'(v1.1.5漏邮件白名单根因堵口,2026-08-24用户定性=错误非保守); e1fa7f28f docs(落档): 本会话研究四件+全站排查两件+防前视铁律四处+README宗旨段+#94登记 |
<!-- token-cache-trend-end -->

**ASCII 迷你柱状图**（每格 = 0.01 命中率，刻度 0.70~1.00，一眼看升降；由脚本 `--append-daily` 随走势表同步更新，保证与实际命中率一致）：

<!-- token-cache-ascii-begin -->
```
命中率刻度 0.70 ───────────────────────────── 1.00 (每格 0.01)
08-10  █████████████████████(21)  24,569,429    0.9134
08-11  █████████████(13)  63,618,029    0.8262
08-12  ████████████(12)  51,612,948    0.8229
08-13  ██████████████████████████(26)  11,384,021    0.9592
08-14  ██████████████████████████(26)  11,058,773    0.9583
08-15  ████████████████████████████(28)  9,242,627     0.9776
08-16  ███████████████████████████(27)  5,912,792     0.9746
08-18  ███████████████████████████(27)  5,705,391     0.9741
08-19  ███████████████████████████(27)  3,989,072     0.9747
08-20  █████████████████████████████(29)  746,855       0.9869
08-21  (0)  47,686,787    0.1473
08-22  ████████████████(16)  12,999,772    0.8589
08-23  ██████████████(14)  14,254,981    0.8412
08-24  ██████████████████(18)  16,791,771    0.8757
```
<!-- token-cache-ascii-end -->

> 说明：括号内数字 = 柱格数（可视刻度即为命中率距 0.70 的格数）。08-10~08-15 的 claude 版本与当日改动为历史回溯未逐一追溯，标 "—"；08-16 起每日 23:30 自动填写实际版本 + 当日 commit。

### 版本/改动日志（可追溯可回滚）

> 每次 claude 版本变化 + 每次 claude-work-mode/根 CLAUDE.md/skill/agent 规范 commit 都记录在此，命中率跳变时可对照"当时发生了什么改动"判断因果。**回滚**：规范/配置 commit 可 `git revert <hash>`；claude 版本可 upgrade/downgrade。由每日 23:30 追加时同步更新（同一行幂等去重）。

<!-- token-cache-changelog-begin -->
| 日期 | 版本 | 改动 |
|---|---|---|
| 2026-08-16 | 2.1.224 | e32017f69 docs(CLAUDE.md): 新增 §23.8 skill 维护同步铁律 — skill 是活资产与项目一致迭代,过时比没有更危险; f34211e79 chore(反思落档): §18 过错索引加 L41(同步任务验收口径做窄——同步 claude-work-mode 只同步根 CLAUDE.md,漏 agents/skills 执行层+README 部署指引过时,用户点破才发现)——归档锚点+主控专属表+计数40→41; a0986a60a docs(claude-work-mode): 使用指引升级为「全局共享核心+项目角色执行层+项目专项」完整部署; 8818f53c7 feat(claude-work-mode全量同步): 补全执行层 .claude/agents/ + .claude/skills/role-*/ 8 文件 (此前只同步根 CLAUDE.md, 漏了角色执行层, 拓扑图与实物脱节); 9e1243fee chore(反思落档): §18 过错索引加 L40(打tag只做点名处没举一反三,版本链v1.1.0漏打没暴露)——归档锚点+主控专属表+计数39→40; e4861253f chore(规范): 新增 §5.6 DeepSeek 官方 API 峰谷定价铁律(2026-08-17 生效)+同步 claude-work-mode; deef6c5bf chore(命中率走势): 08-16 当天数据实时刷新(0.9830)——幂等更新同一行不重复追加; 76613a2d0 chore(命中率走势): 08-16 当天数据刷新至最新(0.9828/2,937,926)+当日改动列并入新commit; 9a31f21df chore(README走势段): 补复现/手动追加命令一句(§23.5复现段); e8bbd4c1d feat(claude-work-mode全量同步+命中率走势): 08-12后新增规范同步进备份包 + token缓存命中率每日追加走势; 2bb4f1e08 chore(收尾): 标记 v1.1.1 + 补 about/privacy 版本串 a279 + TASKS 登记今日4项; b46660a1c docs(§19每日总结): 8/15当天归纳落档 — 新过错L34-L39+经验E27-E30 |
| 2026-08-18 | ? | e24d42a54 docs(compact): AUTO_COMPACT_WINDOW 数字校正 600000→1048576 对齐 settings.json 实况; 222db1844 fix(构建): build_min 从 git HEAD 读源+§24⑤内容校验+deploy push 限 main 根治 min 被脏工作区覆盖; 1eec05cdd feat(kelly): v1.1.2 凯利三键改造 — excludeSpecialBear 升四档判定 + 2备选键 + 历史四档轨迹图后端 |
| 2026-08-19 | ? | ce5ca8dce docs(规范+待办): 全局核心问题报告维度全铁律(§5.1⑤+researcher skill§3⑤) + 落档#69 CYB降亏新标志方向 + 新增#73 多指数四档展示; b74368b5a feat(防再犯CD): push main 统一入口 main-merge.sh + 同文件并发串行 check_file_owners(用户拍板 B 降级安全并行) |
| 2026-08-20 | ? | cd8ea5d8e docs(CLAUDE.md): 存量修正3处(用户已拍板全修) 版本基准引用过时+§18过错索引计数; 3d9d9cdab docs(CLAUDE.md): 瘦身方案#94 A1+§5.4状态独立 删§18元信息+基准定义挪memory权威; 8cb60a5a7 docs(CLAUDE.md): §23.12 TASKS任务治理4态流转规范落档(用户2026-08-20定,task活跃/todolist远期/完成文件/归档7天) |
| 2026-08-21 | ? | — |
| 2026-08-22 | ? | — |
| 2026-08-23 | ? | — |
| 2026-08-24 | ? | 17e1aa2ea docs(governance): 主控过错七条缺口根治——L30/L31/L32/L33/L35/L36六条全文回填18.1+L29留指针(已全文化至根CLAUDE.md §0.1防双份分叉)+头部计数20→27(过错16+经验11自洽)+CLAUDE.md §18主控节索引行补L29例外括注; 7f05426da docs(skill+archive+governance): has_track口径P0教训全链路落档——L44入档(archive全文+锚点行+CLAUDE.md表)+四role skill各加教训条(reviewer第三方锚点/implementer开工三源对照/researcher核查分析对象/tester独立锚点机检)+零丢失等式修复(补录L43锚点行,42断链→44==44)+governance回填E25/E26/E27/E29/E30五条经验(15→20条)+reviewer双##7编号顺延修复; 278ba6c42 docs(skill): has_track口径P0教训同步执行层——reviewer新增档位语义强制第三方锚点检查+implementer新增开工三源逐字对照+CLAUDE.md §23.13反向标注(§23.8双向咬合); 677c51b89 docs(规范): §23.13 口径三源核对+不统一必上报拍板(has_track口径事故P0反思,2026-08-24用户定); f4b123a7d docs(规范): §5.4⑥发版联动清单补'全部键集登记点+机检PASS'+§22补'代码内常量登记点也是一致性对象'(v1.1.5漏邮件白名单根因堵口,2026-08-24用户定性=错误非保守); e1fa7f28f docs(落档): 本会话研究四件+全站排查两件+防前视铁律四处+README宗旨段+#94登记 |
<!-- token-cache-changelog-end -->
