# Claude 工作模式规范包

这是从实际项目（A股情绪看板 `trade`）磨合中提取的 **Claude Code 协作规范**，拆成「通用工作模式」+「项目专项」两部分，合计 = 根 `CLAUDE.md` 完整备份。通用部分可移植到任何项目，项目专项是 `trade` 业务/数据/部署/定时任务特定知识。

## 包内文件

- `CLAUDE.md` - **通用工作模式规范**（可移植，无项目业务知识；项目专项配置用 `<占位符>` 标注，移植时替换为实际值）
- `PROJECT-SPECIFIC.md` - **A股看板项目专项规范**（域名/DB/数据产物/采集脚本/定时任务时点/skill 库/模型提供方，从根 `CLAUDE.md` 提取）
- `README.md` - 本说明文件

> 通用 `CLAUDE.md` + 项目专项 `PROJECT-SPECIFIC.md` = 根 `CLAUDE.md`（约 194 行，§0-§17 + 验收铁律）的完整备份。

## 怎么用

### 给 `trade` 项目（本仓库）

根 `CLAUDE.md` 已是实际加载的完整规范（通用+专项合并），无需另配。本目录是它的拆分备份，便于：

- 复用通用部分到其他项目时只取 `CLAUDE.md`
- 根 `CLAUDE.md` 更新后，定期同步拆分到此两文件，保持备份完整

### 给自己新项目用（全局，所有项目自动加载，通用部分）

```bash
cp CLAUDE.md ~/.claude/CLAUDE.md
```

Claude Code 启动时自动加载 `~/.claude/CLAUDE.md`，对所有项目生效。移植时把 `<占位符>`（如 `<任务看板>`/`<部署域名>`/`<模型名>`/`<定时任务时点>`/`<数据校验脚本>`/`<docs/smoke-checklist.md>`/`<skill库名及版本>`/`<高峰时段>`/`<progress ledger>`/`<任务调度器>`/`<deploy脚本>`）替换为该项目的实际值，或删去不适用的章节。

### 给单个项目用（仅该项目生效，通用+该项目专项）

1. 把通用 `CLAUDE.md` 复制到项目根（或 `~/.claude/CLAUDE.md` 全局）
2. 新建项目自己的 `PROJECT-SPECIFIC.md`（参考本包 `PROJECT-SPECIFIC.md` 的结构，填该项目的域名/DB/数据产物/定时任务等）
3. 在通用 `CLAUDE.md` 里引用 `PROJECT-SPECIFIC.md`（开工先读）

### 给其他人用

让对方把通用 `CLAUDE.md` 内容贴到他自己的 `~/.claude/CLAUDE.md`（全局）或项目根 `CLAUDE.md`（单项目），并按上面「给单个项目用」补项目专项。

## 拆分原则

- **通用部分**（可移植，无业务）：工作模式/协作机制/方法论。项目特定配置用 `<占位符>`（域名/模型名/定时任务时点/数据产物/文件名等），移植时替换。
- **项目专项**（A股看板业务）：具体域名/DB/数据产物/采集脚本/定时任务时点/skill 库版本/模型提供方。

边界章节（如 §7 落档、§8 推送、§11 子 agent、§13 模型、§15 回归、§17 高峰）按「通用模式 + 专项配置」拆：通用机制放 `CLAUDE.md`，具体值/事故 id/项目文件名放 `PROJECT-SPECIFIC.md`。

## 通用规范清单（CLAUDE.md）

每条一句话：

0. **COMPACT 恢复后第一动作** - compact 后 5 步恢复 transient 状态（读看板/笔记/cron/jsonl mtime/git log）
1. **开工前先读工作模式** - 每次会话第一件事读规范，与"杜绝 token 浪费"并列
2. **监管 + loop** - 主控只派发不亲干，子 agent fresh context 不复用，验收验 1-2 点
3. **不冲突就并行派** - 同文件同区域冲突串行，其余并行
4. **杜绝 token 浪费** - 直接给判断动作，不自问自答
5. **调研后给方案** - 技术细节自定默认方案；方案选择终极完整不妥协；参数测试驱动；候选不硬选
6. **始终用中文回复**
7. **memory 读优化 + 落档写保障** - memory 现读现用，重要结论落档 git；任务/cron 默认持久化
8. **改完必须 git push** - commit+push+merge main；验上线验功能生效层非代码在 main；非-ff rebase 不强推
9. **新功能先隔离** - tab/独立表/物理隔离，验证后再融合
10. **改静态资源必须破缓存** - 版本号+SW CACHE_VERSION+min 版用字符串验证
11. **子 agent 生命周期与通知兜底** - SendMessage 主动通知 + 进度文件 + cron 轮询 + 卡死/429/came-to-rest 处理 + 中途改口径停旧派新
12. **遇 API 错误不卡死** - 换方案或暂存，能力与模式匹配
13. **模型能力约束** - 开工先确认模型能力，文本 only 禁图片
14. **生产稳定性 P0** - 主动查定时任务冲突，给时点建议
15. **主功能回归复查 + 改动分级 + reviewer** - A/B/C 级分级，reviewer agent + 数据校验 + smoke 清单
16. **agent 角色画像与 prompt 写作** - 主控 PM 定位 + 6 类子 agent 角色 + prompt 必含项
17. **superpowers / skill 库融合** - 若装 skill 库，运维任务明示跳过 HARD-GATE，大型开发可按需用全套
18. **高峰时段省 token** - 若模型提供方有高峰倍率，派 agent 避开高峰
- **验收铁律** - 逐字验证关键结论，不信 agent 报告

## 项目专项清单（PROJECT-SPECIFIC.md，trade 仓库）

0. 项目概览（static-site/app/data 路径）
1. 项目文件结构与落档（NOTES/TASKS 历史拆分、docs/archive、docs/smoke-checklist.md）
2. 改完推送专项（3 域名 ss.fx8.store/sss.sugas.site/s.sugas.site + R2 ssd.fx8.store + deploy.sh + force push 事故 + intraday 时点 + 验功能生效层项目例）
3. R2 存储架构（index/industry/trade_sim/public_fund 类别 + upload_r2 命令 + fetchJSON 跳 gz）
4. 单版前端铁律（static-site + trade-data cwd + build_min + bump sw + min 验证 + export 路径同步）
5. 切分支保护 DB（sentiment.db/etf_national_team.db + commit 8e3f5fa）
6. 子 agent 教训（具体 agent id：a194f/afe9/a5c6/a2ce/a11439db9/a00f4f2c8b）
7. superpowers 融合（v6.1.1，14 个 skill）
8. 模型能力约束（glm-5.2 + og.png 教训 + magick PNG 白边）
9. 生产稳定性 P0（launchd 定时 15:35/16:00/17:50/20:35/22:00 + intraday 每 10 分钟 + 23:00 安全窗口）
10. 主功能回归复查（board_etf_map.json/overview.json/intraday_snapshot.json + check_data_integrity.py + 08-06 教训）
11. 火山方舟高峰省 token（14:00-18:00 + glm-5.2）
12. 其他项目专项 memory 速查（开工现读 MEMORY.md 索引）

## 章节映射（根 CLAUDE.md → 拆分）

| 根 CLAUDE.md | 通用 CLAUDE.md | 项目专项 PROJECT-SPECIFIC.md |
|---|---|---|
| §0 compact 恢复 | §0（5 步用占位） | §0 概览 + §1（TASKS/NOTES 文件名） |
| §1 开工先读 | §1 | - |
| §2 监管 loop | §2 | - |
| §3 并行 | §3 | - |
| §4 token | §4 | - |
| §5 调研后方案 | §5（含参数测试/候选不硬选） | - |
| §6 中文 | §6 | - |
| §7 memory+落档 | §7（机制+持久化） | §1（项目文件名/拆分） |
| §8 改完推送 | §8（通用 shell+验生效层+不强推） | §2（域名/deploy.sh/data 路径/事故/intraday 时点/项目例） |
| §8.1 R2 | - | §3（全 R2 内容） |
| §9 单版前端 | §10（破缓存通用） | §4（static-site/trade-data cwd/build_min/bump sw/export 同步） |
| §10 切分支 DB | §8（通用教训：DB 移出 git） | §5（sentiment.db/etf_national_team.db/8e3f5fa） |
| §11 子 agent 卡死/429 | §11（机制） | §6（具体 agent id 教训） |
| §12 superpowers | §17（融合规则通用） | §7（v6.1.1/14 skill） |
| §13 模型能力 | §13（通用约束） | §8（glm-5.2/og.png/magick） |
| §14 生产 P0 | §14（主动查冲突通用） | §9（launchd 时点/域名/23:00 窗口） |
| §15 回归复查 | §15（分级/reviewer/smoke 通用） | §10（board_etf_map 等数据产物/校验脚本） |
| §16 agent 角色画像 | §16 | - |
| §17 火山方舟 | §18（高峰避让通用） | §11（14-18/glm-5.2） |
| 验收铁律 | 验收铁律 | - |

## 同步约定

- 根 `CLAUDE.md` 是实际加载的项目规范，是 source of truth。本目录是它的拆分备份。
- 根 `CLAUDE.md` 更新后（新增章节/教训），**定期同步**到此两文件：通用部分进 `CLAUDE.md`，项目专项进 `PROJECT-SPECIFIC.md`，并更新本 README 的清单与映射表。
- 通用 `CLAUDE.md` 的 `<占位符>` 在移植到新项目时替换；本项目专项值在 `PROJECT-SPECIFIC.md` 里是实际值。

## 重要说明

- 通用 `CLAUDE.md` 不含任何项目特定知识（业务逻辑、数据口径、采集脚本、策略细节等），可安全移植。
- 项目专项靠各项目自己的 `PROJECT-SPECIFIC.md` + `NOTES.md` + `TASKS.md` 沉淀，开工先读这三份。
- 本规范是「磨合出来的协作约定」，不是 Claude Code 的官方配置；可根据团队实际增删调整。
- 复制到全局 `~/.claude/CLAUDE.md` 后，若个别项目有特殊要求，可在项目根 `CLAUDE.md` 里追加覆盖。
