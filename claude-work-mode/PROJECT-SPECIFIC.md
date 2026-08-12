# A股看板项目专项规范

> 本文件是 `trade` 项目（A股情绪看板）的业务/数据/部署/定时任务专项规范，配合通用 `CLAUDE.md` 使用。
>
> - **通用工作模式**见同目录 `CLAUDE.md`（可移植，占位符待替换）
> - **角色拆分（2026-08-12）后本文件定位**：根 `CLAUDE.md` 已瘦身为共享核心（所有角色通用），主控专属在 `docs/main-governance.md`，角色专属在 `.claude/agents/` + `.claude/skills/role-*/`，本文件只承载**项目业务/数据/部署/定时任务专项**知识。通用 + 专项 + 角色 skill = 完整工作模式拓扑（见同目录 README.md）
> - 技术栈/公网/关键文件路径详见 memory `trade-sentiment-dashboard` 及项目 `NOTES.md`。

## 0. 项目概览 + 角色拆分后工作模式拓扑

- A股情绪看板，已上线生产。公网域名见 §2（推送与验证）
- 前端源码统一在 `static-site/`；后端 `app/`；数据产物 `static-site/data/*.json`；DB `data/sentiment.db` + `data/etf_national_team.db`（untracked，不进 git）
- compact 恢复第一动作：读 `TASKS.md` 会话状态小节 + `NOTES.md` 近期章节

### 0.1 角色拆分后各文件定位（2026-08-12，详见 docs/role-based-context-research.md）

| 文件/目录 | 定位 |
|---|---|
| 根 `CLAUDE.md` | **共享核心**（所有角色启动自动注入）：§0 角色速览/§1 开工先读/§6 中文/§5 调研/§18 防重犯索引表[L01-L28]/§22 一致性/§8 推送摘要/§14 稳定性摘要/§21 公示指针/§23 三铁律/历史归档/验收铁律 |
| `.claude/agents/implementer.md` 等 4 个 | **角色 agent 定义**（name/description/tools/model/skills 字段），body=角色 system prompt |
| `.claude/skills/role-implementer/SKILL.md` 等 4 个 | **角色专属规范全文**（经 agent 定义 `skills` 字段**启动全文注入**，确定性不依赖主动读）：implementer=§9 前端铁律/§21 公示/§8§14 操作/修bug三铁律/举一反三；reviewer=§15 回归/改动分级/smoke/数据校验/公示查证；researcher=调研方法论/防误判/§5.1 穷举回测/数据挖掘；tester=smoke/数据校验/curl 三查/一致性 |
| `docs/main-governance.md` | **主控专属规范全文**（§2/§3/§4/§7/§11/§15/§16/§19 + COMPACT 恢复 5 步），主控开工第一件事 Read，子 agent 永不读 |
| `docs/archive/CLAUDE-errors-2026-08.md` | **§18 教训原文全量归档**（28 锚点 L01-L28 + 经验 E01-E22 + 每日归纳），根文件只留索引表，`grep 锚点id` 反向追 |
| `docs/role-based-context-research.md` | 角色分上下文调研报告（用户反思触发，2026-08-12 建） |
| `docs/smoke-checklist.md` | P0/P1 主功能点 smoke 清单，reviewer/tester agent 读取执行 |
| `claude-work-mode/` | **可移植备份包**（通用 CLAUDE.md + 项目专项 + README），用于跨项目复用 |
| `docs/agent-quickstart.md` | 按任务类型 A-F 的操作步骤速查（按需 Read 型，非注入） |

## 1. 项目文件结构与落档（§7 专项）

- `NOTES.md`/`TASKS.md` 已拆分历史章节（2026-07-21）：历史章节（§1-§47，2026-07-06~07-20）归档到 `docs/archive/NOTES-history.md`；已完成项归档到 `docs/archive/TASKS-done.md`。主文件只保留近期章节 + 活跃待办 + 工作约定 + R2/全站性能待办。查历史在此二档
- smoke 清单落 `docs/smoke-checklist.md` 进 git，reviewer agent 读取执行
- 长任务 progress ledger 落 `.superpowers/sdd/progress.md` 进 git，跨 compaction 可恢复

## 2. 改完推送专项（§8 专项：域名/data 路径/deploy.sh）

- commit + push feat + merge main + push main（不推=白干，别人无法验收）；commit message 末尾加 `Co-Authored-By: Claude <noreply@anthropic.com>`
- **不 add 根目录 `data/` 下任何文件**（`sentiment.db`/`etf_national_team.db`/`signal_stats.json` 保持本地 M/untracked 不推）
- **`static-site/data/` 是正常上线渠道，不是禁推对象**：前端读的线上数据产物，`scripts/deploy.sh` 设计就是 commit+push 它（git 历史有 `data update [all]` commit 为证）。后端新增 JSON 字段/新品种后**必须跑 `bash scripts/deploy.sh` 推数据上线**，否则前端读旧数据。deploy.sh 的 `git add` 只加 `static-site/data/` + min JS，不碰根 `data/`，安全
- **线上 curl 验证/测试优先用 `https://ss.fx8.store/`**（CF 主站，server: cloudflare，wrangler.jsonc Workers 绑定，push main 自动 deploy，支持 br 压缩 + `_headers`）；备站 `https://sss.sugas.site/`（GitHub Pages，trade-data-signal 仓库）；`https://s.sugas.site/`（MaoziYun 备站，**有 300MB 总大小限制，超了拒绝部署一直 404**，需瘦身到 300MB 以下才恢复）。**3 域名任一验证到新版即算上线 OK，不卡单域名 404**（2026-07-22 教训：曾整晚死磕 s.sugas.site 404 56 次忘 ss.fx8.store/sss.sugas.site 已上线）
- `ss.fx8.store`（CF Workers 主站）支持 `_headers`（CSP/HSTS preload/nosniff/X-Frame/Permissions-Policy）+ br 压缩，已上线；`s.sugas.site`/maozi.io（MaoziYun/3.17.0 非 Cloudflare）`_headers` 不生效，MaoziYun 自带 HSTS + meta referrer 兜底
- ⚠️ **force-with-lease / force push 是最后手段，不是首选**（2026-07-20 gz 方案B agent 违规致 intraday 回退事故）：non-fast-forward 时优先 `git fetch + git rebase origin/main + 重试 push`（deploy.sh L141-160 内置此机制），rebase 失败 abort 退出等人工处理。**agent 不得擅自 force-with-lease / force push，尤其推 main**；确需强推须主控确认
- ⚠️ **deploy.sh `git add static-site/data/` 通配会带入工作区残留旧文件**（2026-07-20 事故根因）：跑 deploy.sh 前确认工作区无旧版实时数据文件（尤其 `intraday_snapshot.json`，由 intraday-snapshot 定时任务独立 push，不被全量 deploy 带入）；export.py 不生成 intraday_snapshot.json，工作区里的旧版会被通配带入 commit 覆盖线上新版
- ⚠️ **盘中（09:30-15:30）不跑全量 export + deploy**：全量 export + deploy 限定 15:35 后（收盘后），盘中只跑 intraday-snapshot 定时任务推 intraday_snapshot.json。agent 接"跑全量 export"任务须先确认时点，盘中拒绝或等收盘（撞 intraday-snapshot 定时任务推 main = 互相覆盖事故）
- ⚠️ **agent 推理"X 文件在 Y commit 里"前先核对**（2026-07-20 事故误判）：用 `git show --stat <commit>` 或 `git log -- <file>` 确认文件实际是否在 commit 里、是哪个时点版本，不靠"Y commit 是 Z 时点跑的所以含 Z 时点数据"推理
- ⚠️ **验上线验功能生效层**（2026-08-05 教训）：代码在 main + 版本号上线 ≠ 功能生效。说"已上线"前 curl JSON 验数据层（字段有值/无旧字段残留）+ 让用户确认显示。教训：判断预估成交额已上线但 `amount_forecast={}` 空对象后端没写数值；信号过滤代码在 main 但 overview.json 旧版 `signals_today` 还有 `s.sentiment_cyb`
- ⚠️ **"功能 done"三查清单（唯一权威，2026-08-11 AI 预测前端漏上线教训补）**：验收"已上线/done"必须三查齐：①main 链含 commit（`git log origin/main` 含 hash）②数据层生效（curl 线上 JSON 字段有值/无旧字段残留）③**前端展示层上线（curl 线上 app.min.js/lab.js 含新功能 class/中文字符串）**。只验①②不验③=前端代码写了但从未 commit main+上线，用户看不到。reviewer 验本地 min ≠ 前端上线，reviewer PASS 后主控 §0 必须补验③

## 3. R2 存储架构准则（§8.1）

- **R2 是存储架构的结构决策，不按单文件大小临时判断**。新数据类别从第一天就走 R2 架构（upload_r2 清单 + 前端 dataUrl R2 fallback），不等变大才补
- **走 R2 的类别（满足任一）**：①全量品种多（100+ index/31 industry/100+ trade_sim/1000+ public_fund）②有大 range 历史序列（`-all/-5y/-3y` 单文件 >1MB）③类别整体大（index 48M/industry 54M/trade_sim 268M/lab 109M）
- **走 CF Workers Static Assets 的小文件**：单文件 <100KB 且类别总量 <5MB 的状态/监控小文件（alert.json/daily_metric.json/schedule_stats.json/alert_analyze_*.json 等），走 R2 反增延迟
- **upload_r2.py 5 个按前缀命令**（upload-lab/upload-index/upload-industry/upload-trade-sim[-json]/upload-public-fund）+ **1 个大小阈值兜底**（upload-data-large >=1MB，exclude industry-/public_fund）+ **upload-claude-backup**（signal-backup 私有桶 claude-backup/ 前缀，每日备份用）。大小阈值是兜底非主架构，**新数据类别优先按前缀建独立命令**，不依赖大小阈值
- **前端 dataUrl R2 fallback**：大 range 历史序列 `-(all|5y|3y).json$` 走 R2 `data/` 前缀；其他 R2 类别（industry/index/trade_sim/public_fund）用硬编码 `https://ssd.fx8.store/{prefix}/` URL
- **本地留引用**：upload_r2 上传后不删本地 `static-site/data/`，CF Workers 兜底+本地开发；大文件可 `.gitignore` 移出 git（本地仍留）
- **上线流程**：export.py 生成 JSON -> 末尾自动跑 R2 上传（`EXPORT_SKIP_R2=1` 跳过，deploy.sh 自己跑）-> git push 触发 CF deploy -> 前端 fetch（大 range 走 R2 直链，小文件走 CF）
- **新数据类别上线 checklist（2026-08-11 定，同 §22 三步同步）**：写 `static-site/data/` 的生成器必须同时接 ①R2 上传（upload_r2 清单或 export 自动）②staticdata 同步（**scripts/staticdata_sync.sh** 或跑 deploy.sh 覆盖）。尤其「只写 static-site/data + 调 upload_r2 不跑 deploy.sh」的独立生成器（如 gen_daily_brief.py），缺 staticdata 留旧版直到下次 deploy
- **判断 checklist（扫描 agent 用）**：①该类别是否有 upload-{prefix} 命令？②前端 fetch 是否用 R2 URL 或 dataUrl 走 R2？③upload-data-large exclude 是否含该前缀（防双副本）？三条齐全=架构合规
- **fetchJSON 全跳 gz**（2026-08-01）：app.js+lab.js `tryGz=false` 全跳 .gz，统一走 .json+CF br 压缩；根因 CF .gz edge cache max-age=14400 4h 滞后致 public_fund 暂无数据；本地/R2 保留 .gz 不删，前端只是不 fetch；.gz fallback 保留防御性但不触发

## 4. 单版前端铁律（§9）

- 前端源码统一在 `static-site/`（web/ 已删，不再双写）；`app/main.py` 挂载 static-site/ 到根 /，`/api/*` 读 DB 不变
- 改 CSS/JS 后跑 `scripts/build_min.py`（terser minify，仅 static-site/app.js+lab.js 2 对）+ `scripts/bump_asset_version.py`（md5 前 8 位破缓存）
- 本地开发：`cd /Users/linhuichen/code/trade-data && /Users/linhuichen/code/trade/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000`（看页面+调 API）或 `python -m http.server -d static-site`
- ⚠️ **uvicorn cwd 必须是 trade-data/**（2026-07-20 方案B，根治线上读滞后镜像）：让 app/db.py 的 `.absolute()` 读最新主库 `trade-data/data/sentiment.db`，非 `trade/` 滞后镜像（仅 deploy.sh rsync 时同步）。launchd 写 trade-data/data/，uvicorn 从 trade/ 跑会读滞后镜像致 export 漏数据（resolve 修复 commit f0f6df78 需 cwd 切 trade-data 才生效）。trade-data/app 是 symlink 指向 trade/app，代码不变。调试加 `--reload`
- ⚠️ **改 app.js/lab.js 必 bump sw.js CACHE_VERSION**（2026-08-07 补）：否则旧 Service Worker CacheFirst 缓存旧 app.min.js 致用户拿不到新代码（硬刷后退回旧数据）。build_min + bump_asset_version + **bump sw.js CACHE_VERSION** 三步缺一不可
- ⚠️ **min 版 JS 验证用字符串非变量名**（2026-08-07 补）：terser mangle 重命名 let 局部变量（`_compBarsHtml` 等），grep 验 min 版上线用 class 名/中文字符串（`kst-comp-fill`/分项构成/优秀）非变量名
- ⚠️ **export 输出路径同步**（2026-08-07 补，§9 cwd trade-data 衍生陷阱）：export.py cwd trade-data 写 JSON 落 `trade-data/static-site/data/`，但 deploy.sh 从 `trade/static-site/data/` 推 git，两路径不同步推旧版。export 后必须 cp 或确认 rsync 同步

## 5. 切分支保护 DB（§10，2026-07-14 已根治，作历史教训留存）

- 历史隐患：`data/sentiment.db`（80MB）+ `data/etf_national_team.db` 曾进 git 跟踪，切分支时 git 用旧版覆盖污染 DB，致 2026-07-14 事故（收盘快照丢失）
- **2026-07-14 已根治（commit 8e3f5fa）**：两 DB 移出 git（git rm --cached + .gitignore），现 untracked。线上全是 `static-site/data/*.json` 静态产物，不依赖 DB
- 切分支现在不会再碰 DB（untracked 文件 git 不跟踪）
- **教训（派 agent 同步分支时注意）**：DB 仍 tracked 时，checkout 切到另一分支会触发 git 用该分支版本覆盖本地 DB。正确同步 main 的方式 = 避免本地 checkout，用 `git fetch origin && git push origin feat/xxx:main` 或 reset，而非 `git checkout main && merge --ff-only`（中间态 checkout 仍 track DB 的分支会复现事故）
- 绝不能 `git restore data/sentiment.db` / `git checkout -- data/sentiment.db`（若不慎重新 add）

## 6. 生产稳定性 P0（§14 专项：launchd 定时任务时点全清单）

- **核心一句话：生产稳定性是 P0 第一要素**。项目已上线生产（ss.fx8.store/sss.sugas.site/s.sugas.site + ssd.fx8.store R2），定时任务撞车会导致线上数据覆盖事故/DB 锁/用户看到错误数据，是不可逆生产故障
- **任务冲突检查不应由用户提醒才做**。每次派任务/设 cron/推 main 前**必须主动查 launchd 定时任务清单**（`launchctl list | grep trade` + 查 plist `StartCalendarInterval`），列当日盘后任务时点，确认新任务不撞，并**主动给用户时点建议**（不等用户问"会不会冲突"）
- **核心冲突类型**：① 推 main（intraday-snapshot 15:35/20:35 + update-all 17:50 + deploy）vs 另一推 main = 互相覆盖事故（§2 已有 2026-07-20 gz 方案B事故）② 写 DB（评分/采集）vs 同 DB 任务 = DB 锁/progress 撞 ③ 采集脚本并发 = 限流空转
- **盘后定时任务时点（15:35/16:00/16:30/17:50/20:35/22:00 等）不推 main 不写 public_fund.db**；**盘中（09:30-15:30）不跑全量 export+deploy**（§2 已有）
- **安全窗口：23:00 后**无推 main/评分/采集任务（3:17 pf-score-weekly / 5:00 us-stock-morning 不写 public_fund.db），大型实施任务放此窗口
- **agent 自己 push feat:main 也要避开**盘后定时任务时点，不只 cron 任务。agent prompt 须写明"避开 15:35/16:00/16:30/17:50/20:35/22:00 push main，撞 intraday-snapshot/update-all 推 main = 互相覆盖事故"
- **盘中 push 前端代码 main 也避开 intraday-snapshot 每10分钟时点**（09:25-11:32 + 13:01-15:02 共 27 次推 intraday_snapshot.json 到 main）。agent 改 app.js/style.css 后 push feat:main 虽改不同文件 rebase 能合并，但 git push 竞争 non-ff 重试有风险，尽量错开。**盘中 push main 选 :00/:10/:20/:30/:40/:50 之外的安全分钟，或等盘后 23:00+ 窗口**（2026-08-10 R2 迁移后：盘中 intraday 走 R2 不推 main，盘中 push 代码 main 不避 intraday；仍避盘后 17:50 update_all 推 main non-ff 竞争）

### 6.1 launchd 定时任务时点表（2026-08-12 实测 `launchctl list | grep trade`）

| 任务 | 时点 |
|---|---|
| intraday-snapshot | 盘中 09:25/09:35/.../11:32 + 13:01/13:05/.../15:02（每 10min 共 27 次）+ 15:35 + 20:35 |
| update-all | 17:50 |
| pf-score-daily | 16:00 |
| public-fund-daily | 16:30 / 17:00 |
| backfill-evening | 16:35 / 21:00 / 02:00 |
| lhb-backfill | 18:30 / 19:30 |
| lab-auto | 19:00 |
| futures-backfill | 20:05 / 21:00 |
| etf-national-team | 20:07 / 21:30 |
| daily-summary-supplement | 20:30 |
| **daily-brief**（AI 速递，gen_daily_brief.py） | 20:40 |
| public-fund-full | 22:00 |
| public-fund-estimation | 10:00 / 11:00 / 13:30 / 14:30 |
| rzhb-backfill | 08:00 / 19:15 |
| public-fund-quarterly | 03:00 / 04:00 / 07:00 |
| pf-score-weekly | 03:17 |
| us-stock-morning | 05:00 |
| pf-stage0-nav / overview / risk / manager | 01:43 / 02:17 / 02:33 / 02:47 |
| gold-night | 02:40 |
| schedule-monitor | 每 15min（:00/:15/:30/:45） |
| monitor-72h | 每 30min（:10/:40） |
| self-heal | 每 15min 偏移（:07/:22/:37/:52） |
| etf-track-index / feishu-listener | 事件/常驻（非定时） |
| claude-self-backup（com.claude.self-backup） | 每日 03:17（backup_claude_self.sh） |

> 核心冲突时点记忆：**15:35/16:00/17:50/20:35/22:00**（旧文档/§14 摘要常用，等同上表 5 个）。

## 7. 主功能回归复查（§15 专项：数据产物）

- **数据产物完整性校验**：被多模块读的关键 JSON：`board_etf_map.json`（空 key 占比 <30%）/ `overview.json`（a_amount 非空）/ `intraday_snapshot.json`（collected_at 今日）等。生成脚本跑完自动校验，超标 fail 不让 deploy（`check_data_integrity.py` deploy.sh 前置，已接入）。扩展 `collect_health` 到数据产物
- **task-reviewer 子 agent**：每次代码改动 push 前派独立 reviewer agent，不看新功能，专看"改动可能影响哪些老功能"（grep 改动文件被谁引用 + 跑关键老功能点），不占主控上下文
- **关键功能 smoke 清单**：维护 P0/P1 主功能点清单（首页 KPI 角标/指数表现 ETF/分时图 hover/情绪分/信号/策略实验室入口等），每次上线前 reviewer agent 跑一遍 curl 数据层 + 关键交互文字描述验证，失败项立即修
- **2026-08-06 教训**：`board_etf_map.json` 因 `etf_index_map.json` 缺失常 27/72 空数组，致指数表现模块 ETF 展示全失效（"全部无ETF"），用户发现时已上线。根因是某改动让数据产物损坏但无校验拦截。此 bug 触发本规范建立。教训对应 C 级（数据产物损坏），非显示改
- **smoke 清单落档**：主功能清单+数据校验规则放 `docs/smoke-checklist.md` 进 git（非 memory），reviewer agent 读取执行
- 模型只文本不能看 UI，回归验证用 curl JSON 数据层 + 关键交互文字描述 + 让用户确认显示三层

## 8. §22 数据一致性铁律项目专项（用户视角多展示位必须一致）

- **核心一句话：用户在N个展示位看到的数据必须统一**。不管内部层级（overview.json / board_etf_map.json / concepts.json），用户看到N处必须一致。只有一致才是最好的解释，文件不一致或缓存不一致都会产生误解
- **用户原则（2026-08-09 用户原话）**："不管层级 我的理解是。作为用户 3个展示位看到的数据一定要统一。比如不能存在文件不一致or 缓存不一致。都会产生误解。只有一致才是最好的解释。你的所有策略都只决定更新频率or排序。但是一旦更新肯定是3处一起同步"
- **本项目展示位映射**：量子科技类 top1/stable_top1 等关键字段在 overview.json（首页）+ board_etf_map.json（指数表现 ETF）+ concepts.json（概念）三处展示；R2/CF 缓存两套
- **所有策略只决定何时更新or如何排序**：stable_top1滞回/排序/更新频率等策略只决定更新时机或排序，**一旦更新必须N文件+N缓存（R2/CF）同步**。不能文件不一致（一个新版一个旧版）or 缓存不一致（R2新CF旧）
- **机制（权威）**：export/deploy 时校验N文件版本一致（关键字段如量子top1/stable_top1），不一致阻断或告警。**算法改动重跑数据产物时，列所有依赖该数据产物清单逐个确认"重跑+同步static-site+R2"三步完整**
- **事故例（2026-08-09 量子科技3展示位不一致）**：§18 索引记录；教训=算法改动重跑数据产物必须三步同步，一条不落
- **与 §15/§18 互参**：§15 防改坏、§22 防不一致、§18 记教训

## 9. §23 三条铁律项目验收口径

### 9.1 README 维护（23.1 项目现状）

- README 现状：功能亮点（信号灯+降亏toggle/AI速递/自动交易等）+参考与致敬（数据挖掘方法论/多 Agent 协作 traderagent/AI 预测 DeepSeek/自动交易 easytrader→thsautoorder/公开数据源致谢 a-stock-data 等）各段已建，后续新功能按段归属补
- 本项目引用外部资产清单（触发 23.1）：a-stock-data/easytrader/thsautoorder/tradingagents/DeepSeek/pysubgroup/mootdx/baostock/akshare/R2/CF Workers 等
- **验收口径**：实施 agent 自验含「grep README 确认本功能描述+致敬已补」，reviewer 查 README 同步，漏=验收不过

### 9.2 修 bug 三铁律项目例（23.2，2026-08-11 备站多模块异常触发）

- 触发场景：备站（sss.sugas.site）多个功能模块同时异常（公募基金 tab 暂无数据/指数表现加载失败刷新无用/凯利回测 signal_kelly_backtest.json Failed to fetch/信号实验配对排行加载失败等），若逐个打地鼠只修用户报的那几个=违反本规范
- ①**修完整**：修 bug 前先 grep 前端全量数据依赖 + curl 多处状态码列全同类异常（尤其备站 sss.sugas.site 走 R2 兜底链路）
- ②**自测完成**：修复后自测用户报的模块 + 同根因其他模块 + 跨展示位 §22 一致性，自验列测试清单
- ③**排查同类**：同文件类型/同 fallback 链路/同上传通道的其他文件（如本次 signal_kelly 未传 R2，要查所有新数据类别是否都传 R2——对照 §3 checklist）
- **验收口径**：修 bug agent 自验须含「同类错误面清单+逐项自测结果」，reviewer 查同类覆盖，漏=验收不过

### 9.3 举一反三项目例（23.3，2026-08-11 走势图切换触发）

- 触发场景：用户问"走势图轻量/完整切换为什么首页没效果"，现状=切换只接了 ETF 评分弹窗 1 个消费者，首页 sparkline/KPI sparkline/分时图都没接入
- 本模式/数据源/组件还被谁用：全站所有走势图渲染点（ETF 评分弹窗/首页 sparkline/KPI sparkline/分时图）+ 所有数据一致性展示位（§22 三展示位）
- **验收口径**：实施方案 agent 自验须含「同模式/同数据源/同组件还被谁用+相关展示位清单+逐项覆盖结果」，不只做用户点名处；reviewer 查举一反三覆盖，漏=验收不过

## 10. 数据产物/采集脚本/定时任务速查

- **数据产物**（static-site/data/*.json）：overview.json（首页核心）/ board_etf_map.json（指数表现 ETF 评分）/ concepts.json（概念）/ intraday_snapshot.json（分时快照）/ index-*.json（指数全量+历史 range）/ industry-*.json（31 行业）/ trade_sim-*.json（策略实验室回测）/ public_fund-*.json（公募基金）/ signal_kelly_*.json（凯利回测）/ daily_brief.json（AI 速递，gen_daily_brief.py 生成）/ alert.json/daily_metric.json/schedule_stats.json（监控小文件）等
- **采集脚本**：collector 系列（mootdx/baostock/腾讯多源）、index_backfill.py（指数补采）、futures/rzhb/lhb 回填、pf-stage0 系列（公募基金分阶段）、gen_daily_brief.py（AI 速递，deepseek，schedule 默认关）
- **定时任务**：见 §6.1 launchd 表
- **R2 上传链路**：export.py 自动跑 / upload_r2.py 按前缀命令 / staticdata_sync.sh（staticdata 同步）——见 §3

## 11. 子 agent 教训（§11 专项：具体 agent id，精简留存）

- **2026-07-15 教训 a194f/afe9**：a194f 曾只写"开始"641 秒不回写进度致盲区；429 后误判原会话终止重派 afe9 从头跑，浪费 a194f 已查的上下文。实际 task-notification note 明说"can resume"，429 和卡死都优先 resume——配额恢复后第一动作是 SendMessage resume 原会话，不是重派
- **2026-07-15 a5c6**：改名反复 came to rest，SendMessage 推进 3 次才完成；阈值可降到 240 秒
- **2026-08-07 ETF盈亏4轮振荡**：中途改口径停旧派新，SendMessage 让旧 agent 继续致误操作反向（a11439db9 拒绝大重构 -> 改派 a00f4f2c8b 成功）
- 最新教训索引：L01-L28 全文在 docs/archive/CLAUDE-errors-2026-08.md（根 CLAUDE.md §18 索引表可反向追）

## 12. 其他项目专项 memory 速查（开工现读）

以下为高频引用的项目专项 memory（非全部），开工现读 `~/.claude/projects/-Users-linhuichen-code-trade/memory/MEMORY.md` 索引：

- `trade-sentiment-dashboard` - 项目入口指针：技术栈+公网+关键文件路径，开工先读 3 文件
- `export-syspath-rootcause` - export.py sys.path 根因；DB UPDATE 须同时写主库+镜像
- `export-output-path-sync` - export 输出路径同步（§4）
- `cf-workers-large-json-404-r2-fallback` - ss.fx8.store 对 5MB+ 大 JSON 返回 404，前端走 R2 直链 ssd.fx8.store
- `deploy-verify-3-sites` - 3 域名任一验证到新版即算上线
- `asset-version-cache-busting` / `bump-sw-version-with-appjs` - 改 CSS/JS 后破缓存 + bump sw 版本
- `production-stability-p0` - 生产稳定性 P0 第一要素
- `intraday-snapshot-schedule` - intraday 时点设计（上午 11:32/下午 15:02 收尾，每 10min 共 27 次）
- `verify-feature-live-not-code-in-main` - 验上线验到功能生效层
- `verify-minjs-use-string-not-varname` - min 版 JS 验证用字符串非变量名
- `r2-arch-by-category-not-size` / `r2-optimize-after-generate` / `r2-upload-from-trade` - R2 架构按类别非按大小 + 生成后即走 + 从 trade 跑
- `compact-recovery-checklist` - compact 后第一动作 5 步
- `daily-brief-deepseek` - AI 速递已切 deepseek（非 glm），key 在 trade-data/.env 非 git；2026-08-10 第一阶段后端已上线，前端首盘小结展示待续
- `main-governance`（memory 索引） - 主控开工第一件事 Read docs/main-governance.md
