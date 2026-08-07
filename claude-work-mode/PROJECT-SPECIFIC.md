# A股看板项目专项规范

> 本文件是 `trade` 项目（A股情绪看板）的业务/数据/部署/定时任务专项规范，配合通用 `CLAUDE.md` 使用。
>
> - **通用工作模式**见同目录 `CLAUDE.md`（可移植，占位符待替换）
> - **本文件**是从根 `CLAUDE.md` 提取的项目专项部分（域名/DB/数据产物/采集脚本/定时任务时点/skill 库/模型提供方）
> - **通用 + 本文件 = 根 `CLAUDE.md` 完整备份**。根 `CLAUDE.md` 是实际加载的规范，更新后定期同步到此
>
> 技术栈/公网/关键文件路径详见 memory `trade-sentiment-dashboard` 及项目 `NOTES.md`。

## 0. 项目概览

- A股情绪看板，已上线生产。公网域名见 §2（推送与验证）
- 前端源码统一在 `static-site/`；后端 `app/`；数据产物 `static-site/data/*.json`；DB `data/sentiment.db` + `data/etf_national_team.db`（untracked，不进 git）
- compact 恢复第一动作：读 `TASKS.md` 会话状态小节 + `NOTES.md` §48 近期章节

## 1. 项目文件结构与落档（§7 专项）

- `NOTES.md`/`TASKS.md` 已拆分历史章节（2026-07-21）：历史章节（§1-§47，2026-07-06~07-20）归档到 `docs/archive/NOTES-history.md`；已完成项（22 任务全 done + 晚续 3 及更早交接状态 + 综合 AI 风险预警 P1/P2/P4 全闭环）归档到 `docs/archive/TASKS-done.md`。主文件只保留 §48 近期章节 + 晚续 4 活跃待办 + 工作约定 + R2/全站性能待办。查历史在此二档
- smoke 清单落 `docs/smoke-checklist.md` 进 git，reviewer agent 读取执行
- 长任务 progress ledger 落 `.superpowers/sdd/progress.md` 进 git，跨 compaction 可恢复

## 2. 改完推送专项（§8 专项：域名/data 路径/deploy.sh）

- commit + push feat + merge main + push main（不推=白干，别人无法验收）
- **不 add 根目录 `data/` 下任何文件**（`sentiment.db`/`etf_national_team.db`/`signal_stats.json` 保持本地 M/untracked 不推）
- **`static-site/data/` 是正常上线渠道，不是禁推对象**：前端读的线上数据产物，`scripts/deploy.sh` 设计就是 commit+push 它（git 历史有 `data update [all]` commit 为证）。后端新增 JSON 字段/新品种后**必须跑 `bash scripts/deploy.sh` 推数据上线**，否则前端读旧数据（memory `data-schema-change-needs-deploy`）。deploy.sh 的 `git add` 只加 `static-site/data/` + min JS，不碰根 `data/`，安全
- **线上 curl 验证/测试优先用 `https://ss.fx8.store/`**（CF 主站，server: cloudflare，wrangler.jsonc Workers 绑定，push main 自动 deploy，支持 br 压缩）；备站 `https://sss.sugas.site/`（GitHub Pages，xp13465/trade-data-signal 仓库）；`https://s.sugas.site/`（MaoziYun 备站，**有 300MB 总大小限制，超了拒绝部署一直 404**，2026-07-22 实测 531MB 超 300MB 自 21:35 后停止拉取，需瘦身到 300MB 以下才恢复）；旧 maozi.io 最后兜底（s.aisusu.cn 已撤 DNS 不可达）。**3 域名任一验证到新版即算上线 OK，不卡单域名 404**（2026-07-22 教训：曾整晚死磕 s.sugas.site 404 56 次忘 ss.fx8.store/sss.sugas.site 已上线，违反 memory `deploy-verify-3-sites`）
- `ss.fx8.store`（CF Workers 主站）支持 `_headers`（CSP/HSTS preload/nosniff/X-Frame/Permissions-Policy）+ br 压缩，已上线；`s.sugas.site`/maozi.io（MaoziYun/3.17.0 非 Cloudflare）`_headers` 不生效，MaoziYun 自带 HSTS + meta referrer 兜底。`_headers` 配置在 CF 主站已生效（wrangler.jsonc Workers 已绑定 ss.fx8.store 主站）
- ⚠️ **force-with-lease / force push 是最后手段，不是首选**（2026-07-20 gz 方案B agent 违规致 intraday 回退事故，见 NOTES §48 小节S 事故记录）：non-fast-forward 时优先 `git fetch + git rebase origin/main + 重试 push`（deploy.sh L141-160 内置此机制），rebase 失败 abort 退出等人工处理。**agent 不得擅自 force-with-lease / force push，尤其推 main**；确需强推须主控确认
- ⚠️ **deploy.sh `git add static-site/data/` 通配会带入工作区残留旧文件**（2026-07-20 事故根因）：跑 deploy.sh 前确认工作区无旧版实时数据文件（尤其 `intraday_snapshot.json`，由 intraday-snapshot 定时任务独立 push，不被全量 deploy 带入）；export.py 不生成 intraday_snapshot.json，工作区里的旧版会被通配带入 commit 覆盖线上新版
- ⚠️ **盘中（09:30-15:30）不跑全量 export + deploy**：全量 export + deploy 限定 15:35 后（收盘后），盘中只跑 intraday-snapshot 定时任务推 intraday_snapshot.json。agent 接"跑全量 export"任务须先确认时点，盘中拒绝或等收盘（撞 intraday-snapshot 定时任务推 main = 互相覆盖事故）
- ⚠️ **agent 推理"X 文件在 Y commit 里"前先核对**（2026-07-20 事故误判）：用 `git show --stat <commit>` 或 `git log -- <file>` 确认文件实际是否在 commit 里、是哪个时点版本，不靠"Y commit 是 Z 时点跑的所以含 Z 时点数据"推理
- ⚠️ **验上线验功能生效层**（2026-08-05 教训）：代码在 main + 版本号上线 ≠ 功能生效。说"已上线"前 curl JSON 验数据层（字段有值/无旧字段残留）+ 让用户确认显示。教训：判断预估成交额已上线但 `amount_forecast={}` 空对象后端没写数值；信号过滤代码在 main 但 overview.json 旧版 `signals_today` 还有 `s.sentiment_cyb`

## 3. R2 存储架构准则（§8.1）

- **R2 是存储架构的结构决策，不按单文件大小临时判断**。新数据类别从第一天就走 R2 架构（upload_r2 清单 + 前端 dataUrl R2 fallback），不等变大才补
- **走 R2 的类别（满足任一）**：①全量品种多（100+ index/31 industry/100+ trade_sim/1000+ public_fund）②有大 range 历史序列（`-all/-5y/-3y` 单文件 >1MB）③类别整体大（index 48M/industry 54M/trade_sim 268M/lab 109M）
- **走 CF Workers Static Assets 的小文件**：单文件 <100KB 且类别总量 <5MB 的状态/监控小文件（alert.json/daily_metric.json/schedule_stats.json/alert_analyze_*.json 等），走 R2 反增延迟（.gz 优先对小文件收益小）
- **upload_r2.py 5 个按前缀命令**（upload-lab/upload-index/upload-industry/upload-trade-sim[-json]/upload-public-fund）+ **1 个大小阈值兜底**（upload-data-large >=1MB，exclude industry-/public_fund）。大小阈值是兜底非主架构，**新数据类别优先按前缀建独立命令**，不依赖大小阈值
- **前端 dataUrl R2 fallback**：大 range 历史序列 `-(all|5y|3y).json$` 走 R2 `data/` 前缀；其他 R2 类别（industry/index/trade_sim/public_fund）用硬编码 `https://ssd.fx8.store/{prefix}/` URL（和 dataUrl 同模式，不扩展 `_R2_LARGE_RANGE_RE` 避免语义混淆）
- **本地留引用**：upload_r2 上传后不删本地 `static-site/data/`，CF Workers 兜底+本地开发；大文件可 `.gitignore` 移出 git（本地仍留），和 a-stock-all.json 等同策略
- **上线流程**：export.py 生成 JSON -> 末尾自动跑 R2 上传（`EXPORT_SKIP_R2=1` 跳过，deploy.sh 自己跑）-> git push 触发 CF deploy -> 前端 fetch（大 range 走 R2 直链，小文件走 CF）
- **判断 checklist（扫描 agent 用）**：①该类别是否有 upload-{prefix} 命令？②前端 fetch 是否用 R2 URL 或 dataUrl 走 R2？③upload-data-large exclude 是否含该前缀（防双副本）？三条齐全=架构合规
- **fetchJSON 全跳 gz**（2026-08-01）：app.js+lab.js `tryGz=false` 全跳 .gz，统一走 .json+CF br 压缩；根因 CF .gz edge cache max-age=14400 4h 滞后致 public_fund 暂无数据；本地/R2 保留 .gz 不删，前端只是不 fetch；.gz fallback 保留防御性但不触发

## 4. 单版前端铁律（§9）

- 前端源码统一在 `static-site/`（web/ 已删，不再双写）；`app/main.py` 挂载 static-site/ 到根 /，`/api/*` 读 DB 不变
- 改 CSS/JS 后跑 `scripts/build_min.py`（terser minify，仅 static-site/app.js+lab.js 2 对）+ `scripts/bump_asset_version.py`（md5 前 8 位破缓存）
- 本地开发：`cd /Users/linhuichen/code/trade-data && /Users/linhuichen/code/trade/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000`（看页面+调 API）或 `python -m http.server -d static-site`
- ⚠️ **uvicorn cwd 必须是 trade-data/**（2026-07-20 方案B，根治线上读滞后镜像）：让 app/db.py 的 `.absolute()` 读最新主库 `trade-data/data/sentiment.db`（inode 237343239），非 `trade/` 滞后镜像（inode 238648312，仅 deploy.sh rsync 时同步）。launchd 写 trade-data/data/，uvicorn 从 trade/ 跑会读滞后镜像致 export 漏数据（resolve 修复 commit f0f6df78 需 cwd 切 trade-data 才生效）。trade-data/app 是 symlink 指向 trade/app，代码不变。调试加 `--reload`
- ⚠️ **改 app.js/lab.js 必 bump sw.js CACHE_VERSION**（2026-08-07 补）：否则旧 Service Worker CacheFirst 缓存旧 app.min.js 致用户拿不到新代码（硬刷后退回旧数据）。build_min + bump_asset_version + **bump sw.js CACHE_VERSION** 三步缺一不可
- ⚠️ **min 版 JS 验证用字符串非变量名**（2026-08-07 补）：terser mangle 重命名 let 局部变量（`_compBarsHtml` 等），grep 验 min 版上线用 class 名/中文字符串（`kst-comp-fill`/分项构成/优秀）非变量名
- ⚠️ **export 输出路径同步**（2026-08-07 补，§9 cwd trade-data 衍生陷阱）：export.py cwd trade-data 写 JSON 落 `trade-data/static-site/data/`，但 deploy.sh 从 `trade/static-site/data/` 推 git，两路径不同步推旧版。export 后必须 cp 或确认 rsync 同步

## 5. 切分支保护 DB（§10，2026-07-14 已根治，作历史教训留存）

- 历史隐患：`data/sentiment.db`（80MB）+ `data/etf_national_team.db` 曾进 git 跟踪，切分支时 git 用旧版覆盖污染 DB，致 2026-07-14 事故（收盘快照丢失）
- **2026-07-14 已根治（commit 8e3f5fa）**：两 DB 移出 git（git rm --cached + .gitignore），现 untracked。线上全是 `static-site/data/*.json` 静态产物，不依赖 DB
- 切分支现在不会再碰 DB（untracked 文件 git 不跟踪）
- **教训（派 agent 同步分支时注意）**：DB 仍 tracked 时，checkout 切到另一分支会触发 git 用该分支版本覆盖本地 DB。正确同步 main 的方式 = 避免本地 checkout，用 `git fetch origin && git push origin feat/xxx:main` 或 reset，而非 `git checkout main && merge --ff-only`（中间态 checkout 仍 track DB 的分支会复现事故）
- 绝不能 `git restore data/sentiment.db` / `git checkout -- data/sentiment.db`（若不慎重新 add）

## 6. 子 agent 教训（§11 专项：具体 agent id）

- **2026-07-15 教训 a194f/afe9**：a194f 曾只写"开始"641 秒不回写进度致盲区；429 后误判原会话终止重派 afe9 从头跑，浪费 a194f 已查的 32 tool_use 上下文。实际 task-notification note 明说"can resume"，429 和卡死都优先 resume--配额恢复后第一动作是 SendMessage resume 原会话，不是重派
- **2026-07-15 a5c6**：改名反复 came to rest，SendMessage 推进 3 次才完成；阈值可降到 240 秒
- **数据时效 a2ce 接 a06704b 半成品**：重派新会话读原 agent 遗留接着做，避免从头返工
- **2026-08-07 ETF盈亏4轮振荡**：中途改口径停旧派新，SendMessage 让旧 agent 继续致误操作反向（a11439db9 拒绝大重构 -> 改派 a00f4f2c8b 成功）

## 7. superpowers 融合（§12，2026-07-15 装 v6.1.1）

- superpowers 是纯 skill 库（14 个，无 slash command），SessionStart hook 每次开会话强制注入 using-superpowers 全文（~800 token），且默认"1% 可能相关就主动调 skill"
- **优先级**：本项目 CLAUDE.md 硬规范 > superpowers skill。using-superpowers 声明"只有用户明示跳过才不走 skill"，故下条明示跳过
- **运维/采集/上线/数据任务明示跳过** superpowers 的：①brainstorming 的 HARD-GATE（写码前必经设计门）②executing-plans/subagent-driven-development 的 continuous-execution（连轴转不停问用户）。这类任务**保留现有监工 loop**（§2/§11：派 background 子 agent->立即返回待命->CronCreate 轮询 jsonl mtime->卡死/429 优先 SendMessage resume->不问 yes/no 用户随时插话）
- **background 异步 + 卡死/429 轮询恢复机制保留不替换**：superpowers 假设子 agent 同步返回、无恢复机制，比现有弱
- **大型功能开发（策略实验室级）可按需用全套**：brainstorming->writing-plans（拆 2-5 分钟 bite-sized task）->subagent-driven-development（implementer+reviewer+fixer 循环）->TDD->finishing-a-development-branch
- **可借鉴技艺补强监工 loop**：①独立 task-reviewer 子 agent 两阶段验收（spec 合规+代码质量）②大 diff 走文件交接（`.superpowers/sdd/review-*.diff`）不进主控上下文 ③progress ledger 落 `.superpowers/sdd/progress.md` 进 git 跨 compaction 可恢复 ④using-git-worktrees 隔离并行改同区域

## 8. 模型能力约束（§13 专项：glm-5.2）

- 当前模型 **glm-5.2**（火山方舟提供）**只支持文本输入，不支持图片**。Read 图片/截图/视觉对比会触发 API Error 400 "Model only support text input"，终止 agent
- 派子 agent 时**禁止图片操作**（截图对比/UI 视觉看图/Read 图片验证效果）。需视觉验证的用文字描述+ASCII 示意图，或让用户自己看
- 子 agent 撞 400 "Model only support text input" = 尝试了图片输入。若其调研已基本完成，读进度文件 + 主控补完剩余即可，无需重派从头
- **2026-07-16 教训**：P2-4 og.png 压缩 agent 在"开始写报告"时疑似 Read og.png 验证压缩效果，撞 400 终止。但 P0-1 压缩调研已完成（坐实不可行），og.png 主控手动 magick 256 色压缩补完（67KB->36KB），无损失
- **magick 无 alpha PNG 白边**（memory）：PNG 无 alpha（color-type 2）转 ico 白边是自带白底，`-background none`/`-trim` 无效，用 `-fuzz 5% -transparent white` 把白底变透明；ico 字节可能巧合相同用 md5 验证

## 9. 生产稳定性 P0（§14 专项：launchd 定时任务时点）

- **核心一句话：生产稳定性是 P0 第一要素**。项目已上线生产（ss.fx8.store/sss.sugas.site/s.sugas.site + ssd.fx8.store R2），定时任务撞车会导致线上数据覆盖事故/DB 锁/用户看到错误数据，是不可逆生产故障
- **任务冲突检查不应由用户提醒才做**。每次派任务/设 cron/推 main 前**必须主动查 launchd 定时任务清单**（`launchctl list | grep trade` + 查 plist `StartCalendarInterval`），列当日盘后任务时点，确认新任务不撞，并**主动给用户时点建议**（不等用户问"会不会冲突"）
- **核心冲突类型**：① 推 main（intraday-snapshot 15:35/20:35 + update-all 17:50 + deploy）vs 另一推 main = 互相覆盖事故（§2 已有 2026-07-20 gz 方案B事故）② 写 DB（评分/采集）vs 同 DB 任务 = DB 锁/progress 撞 ③ 采集脚本并发 = 限流空转
- **盘后定时任务时点（15:35/16:00/17:50/20:35/22:00）不推 main 不写 public_fund.db**；**盘中（09:30-15:30）不跑全量 export+deploy**（§2 已有）
- **安全窗口：23:00 后**无推 main/评分/采集任务（3:17 weekly 周日才跑，5:00 us-stock-morning 不写 public_fund.db），大型实施任务放此窗口
- **agent 自己 push feat:main 也要避开**盘后定时任务时点，不只 cron 任务。agent prompt 须写明"避开 15:35/16:00/17:50/20:35 push main，撞 intraday-snapshot/update-all 推 main = 互相覆盖事故"
- **盘中 push 前端代码 main 也避开 intraday-snapshot 每10分钟时点**（:25/:35/:45/:55/:05/:15，09:25-15:02 共 27 次推 intraday_snapshot.json 到 main）。agent 改 app.js/style.css 后 push feat:main 虽改不同文件 rebase 能合并，但 git push 竞争 non-ff 重试有风险，尽量错开。**盘中 push main 选 :00/:10/:20/:30/:40/:50 之外的安全分钟，或等盘后 23:00+ 窗口**
- 2026-08-04 教训：方案C盘后实施 cron 我直接定 15:35 没查 launchd，用户主动提醒才查，发现撞 5 个定时任务。改 23:03 启动避开。详见 memory `production-stability-p0`

## 10. 主功能回归复查（§15 专项：数据产物）

- **数据产物完整性校验**：被多模块读的关键 JSON：`board_etf_map.json`（空 key 占比 <30%）/ `overview.json`（a_amount 非空）/ `intraday_snapshot.json`（collected_at 今日）等。生成脚本跑完自动校验，超标 fail 不让 deploy（`check_data_integrity.py` deploy.sh 前置，已接入）。扩展 `collect_health` 到数据产物
- **task-reviewer 子 agent**：每次代码改动 push 前派独立 reviewer agent，不看新功能，专看"改动可能影响哪些老功能"（grep 改动文件被谁引用 + 跑关键老功能点），不占主控上下文（§7 superpowers 借鉴）
- **关键功能 smoke 清单**：维护 P0/P1 主功能点清单（首页 KPI 角标/指数表现 ETF/分时图 hover/情绪分/信号/策略实验室入口等），每次上线前 reviewer agent 跑一遍 curl 数据层 + 关键交互文字描述验证，失败项立即修
- **2026-08-06 教训**：`board_etf_map.json` 因 `etf_index_map.json` 缺失常 27/72 空数组，致指数表现模块 ETF 展示全失效（"全部无ETF"），用户发现时已上线。根因是某改动让数据产物损坏但无校验拦截。此 bug 触发本规范建立。教训对应 C 级（数据产物损坏），非显示改
- **smoke 清单落档**：主功能清单+数据校验规则放 `docs/smoke-checklist.md` 进 git（非 memory），reviewer agent 读取执行
- 模型只文本不能看 UI，回归验证用 curl JSON 数据层 + 关键交互文字描述 + 让用户确认显示三层

## 11. 火山方舟高峰省 token（§17 专项）

- **火山方舟（模型提供方）14:00-18:00 高峰期高倍率结算**，开发派 agent（token 消耗大）尽量避开此时段，放 18:00 后或上午
- 简单对话/验收/轻量操作（消耗小）无所谓，只针对派实施/调研 agent（消耗大）规避
- **14-18 必须干活时**：优先轻量验收/对话，重实施 agent 推迟到 18:00 后；用户主动派活除外（响应优先）
- 和 §9（本文件）并列：§9 避开定时任务时点（生产安全 P0），本条避开高峰倍率（省 token）；两者时点重叠时（如 15:35 既撞定时又高峰）双重规避
- **派 agent 前看时间**：14-18 期间如非紧急，向用户说明"高峰倍率，建议 18 后跑"等用户定；用户确认立即跑不卡

## 12. 其他项目专项 memory 速查（开工现读）

以下为高频引用的项目专项 memory（非全部），开工现读 `~/.claude/projects/-Users-linhuichen-code-trade/memory/MEMORY.md` 索引：

- `trade-sentiment-dashboard` - 项目入口指针：技术栈+公网+关键文件路径，开工先读 3 文件
- `export-syspath-rootcause` - export.py sys.path 根因（§9 衍生陷阱真正根因）；DB UPDATE 须同时写主库+镜像，跳过 rsync 避免旧版覆盖新版
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
