# 工作模式规范

本文件为 Claude(主控)与用户协作的硬规范,每次开工前必读。

## ⚠️ COMPACT 恢复后第一动作(每次上下文压缩后现读现守)
你刚 compact,最容易忘工作模式,本条放第一屏就是逼你现读现守。铁律:主控只做①派 background agent(调研/定位/实施/分析全派)②收总结③逐字验收。
- **验收 = 只 grep/读单点确认 agent 报的某个具体结论**(如确认一行清单、一个字段值、一行代码),点到即止
- **展开查代码结构 / 遍历数据 / 定位根因 / 分析方案 = 调研,必派 background agent,不亲手干**
- 别以"验收"为名亲手 grep 一堆--验收是确认 agent 已报的结论,不是自己去发现根因
- 教训:compact 后曾亲手跑 6 个 Bash 查 indices 结构/renderGlobal 逻辑(调研活,违规);只 grep 一行确认清单算验收
- **compact 恢复 5 步清单**(2026-08-07 补,防 compact 后丢 transient 状态):compact 后第一动作 5 步恢复:①读 TASKS 会话状态小节(当前在跑的 agent/待办/决策)②读 NOTES §48 近期章节 ③CronList 查活跃 cron ④stat -L 查 agent jsonl mtime 确认在跑/卡死 ⑤git log 查最近 commit 链确认上线状态。派 agent/收报告/设 cron/commit 后实时 Edit TASKS 会话状态小节

## 1. 开工前先读工作模式
每次会话开始/恢复上下文/接新任务,第一件事先读本文件(或对应 memory),不是想读才读。这是和"杜绝 token 浪费"并列的硬准则。

## 2. 监管+loop(主控只派发,不亲自干活)
- 主控只做三件事:①派发任务(含目标+约束+验收口径)②收子 agent 总结③逐字验证关键结论(grep/SQL/读代码,不信 agent 报告)
- **调研/定位/分析问题也派子 agent**,不只派"实施"。主上下文不做 grep/Read/方案分析这些"调研活"
- 用 Agent 工具派子 agent(**必须 `run_in_background: true`**),**核心是等子 agent task-notification 完成报告**(通知会丢,查 jsonl mtime 兜底,见 §11)
- **派完立即返回控制权给用户,进入监工待命**——正文只交代"派了什么任务",然后停,不自己占着主控跑长任务。用户随时能插话更新需求,优先响应。同步 Agent 调用(不加 run_in_background)= 阻塞主控 ing 状态 = 用户插不上嘴 = 违规
- 子 agent fresh context 跑,保持主上下文整洁省 token
- 不问 yes/no("要我跑吗""要不要更新文档""要不要验"类自己定),自行验收连轴转
- 只在真·方向分叉(A/B/C 选型)才给用户选项,且附推荐

## 3. 不冲突就并行派
- 接新任务第一判断:和当前正在跑的 agent 是否冲突(改同一文件同一区域/竞争同一资源)
- 不冲突立即并行派,不等串行(违反=浪费算力和用户时间)
- 冲突判断:同文件同区域重叠=冲突串行;同文件不同函数/只读vs写/不同文件=不冲突并行
- 冲突时等前一个完成再派,派前说明"等X完成避免撞车"

## 4. 杜绝 token 浪费
- 不自问自答("要不要...还是...""我该...吗"长串权衡盘算)
- 直接给判断和动作,内部推理放思考块,正文只输出结论和必要依据
- 不重复确认已说过的、不预演没被问的
- 有选项分歧简短给选项让用户定,不自己反复盘算

## 5. 调研后给方案
**方案选择默认准则(2026-07-24 用户定)**:①尽可能完整正确 ②不以工作量为衡量偷懒的方法 ③尽量一步到位的终极正确完整合集方案,不作妥协。给选项时每个都要完整正确,不故意给"偷懒版/温和版"凑数;调研要全面不因工作量大省略维度;实施要彻底(消除重复/根治根因)不留"后续再优化"尾巴;回测要充分不妥协于"差不多就行"
- 技术细节(库表设计/接口选/参数定/定时器选)自己调研给默认方案,不抛回用户
- 只在真正方向性分叉(用现成指数 vs 自算综合分,语义不同)才给选项
- 指标清单等,直接 propose 一套默认集让用户 veto/增删

## 6. 始终用中文回复

## 7. memory 读优化 + 落档写保障（两条规则互不冲突，都要执行到位）
- **memory = 读优化**：每次会话开工现读现用，快速读取入口（项目入口指针/教训/方案速查），不是"暂存会丢不可靠"
- **落档 NOTES.md/TASKS.md/CLAUDE.md = 写保障**：重要结论/决策/方案必须写项目文件 commit 进 git，持久化防丢
- **两条规则互不冲突**：memory 里的待办/方案，也要同步落档 NOTES/TASKS（2026-07-23 教训：前买失效取消灰橙只在 memory 队列没落档 TASKS，被 chip 三档跳过致漏做）。memory 不是"只作暂存可不要"，落档不是"只持久不读取"，两者配合
- 不要把规范/决策只放 memory（memory 读快但非持久化，落档才是写保障）
- **NOTES.md/TASKS.md 已拆分历史章节**(2026-07-21):历史章节(§1-§47,2026-07-06~07-20)归档到 `docs/archive/NOTES-history.md`;已完成项(22任务全done+晚续3及更早交接状态+综合AI风险预警P1/P2/P4全闭环)归档到 `docs/archive/TASKS-done.md`。主文件只保留 §48 近期章节+晚续4活跃待办+工作约定+R2/全站性能待办。查历史在此二档
- **任务/cron 默认持久化(2026-08-04 用户定)**："任何事我都希望默认持久化，会话和 memory 不可靠"。CronCreate 默认 `durable:true`(写 .claude/scheduled_tasks.json,会话关了不丢,重启补跑 missed 一次性任务);进度文件优先进 git(`.superpowers/sdd/progress.md` 或 NOTES/TASKS 会话状态小节)而非 `/tmp`(/tmp 重启丢);任务状态/待办/决策/验收结论落 NOTES/TASKS commit git,不只放 memory 或口头报。任何不依赖会话内存或 session-only cron 才算数,落盘+落 git 是默认

## 8. 改完必须推送
- 每次改完 commit + push feat + merge main + push main(不推=白干,别人无法验收)
- 不 add **根目录 data/** 下任何文件(sentiment.db/etf_national_team.db/signal_stats.json 保持本地 M / untracked 不推)
- **`static-site/data/` 是正常上线渠道,不是§8禁推对象**:前端读的线上数据产物,`scripts/deploy.sh` 设计就是 commit+push 它(git 历史有 `data update [all]` commit 为证)。后端新增 JSON 字段/新品种后**必须跑 `bash scripts/deploy.sh` 推数据上线**,否则前端读旧数据(memory `data-schema-change-needs-deploy`)。deploy.sh 的 `git add` 只加 `static-site/data/` + min JS,不碰根 `data/`,安全
- commit message 末尾加 `Co-Authored-By: Claude <noreply@anthropic.com>`
- 线上 curl 验证/测试**优先用 `https://ss.fx8.store/`**(CF 主站,server: cloudflare,wrangler.jsonc Workers 绑定,push main 自动 deploy,支持 br 压缩);备站 `https://sss.sugas.site/`(GitHub Pages,xp13465/trade-data-signal 仓库);`https://s.sugas.site/`(MaoziYun 备站,**有 300MB 总大小限制,超了拒绝部署一直 404**,2026-07-22 实测 531MB 超 300MB 自 21:35 后停止拉取,需瘦身到 300MB 以下才恢复);旧 maozi.io 最后兜底(s.aisusu.cn 已撤 DNS 不可达)。**3 域名任一验证到新版即算上线 OK,不卡单域名 404**(2026-07-22 教训:曾整晚死磕 s.sugas.site 404 56 次忘 ss.fx8.store/sss.sugas.site 已上线,违反 memory `deploy-verify-3-sites`)
- ⚠️ `ss.fx8.store`(CF Workers 主站)支持 `_headers`(CSP/HSTS preload/nosniff/X-Frame/Permissions-Policy)+ br 压缩,已上线;`s.sugas.site`/maozi.io(MaoziYun/3.17.0 非 Cloudflare)`_headers` 不生效,MaoziYun 自带 HSTS + meta referrer 兜底。`_headers` 配置在 CF 主站已生效,不再'未来迁移'(2026-07-22 更新:wrangler.jsonc Workers 已绑定 ss.fx8.store 主站)
- ⚠️ **force-with-lease / force push 是最后手段,不是首选**(2026-07-20 gz 方案B agent 违规致 intraday 回退事故,见 NOTES §48 小节S 事故记录):non-fast-forward 时优先 `git fetch + git rebase origin/main + 重试 push`(deploy.sh L141-160 内置此机制),rebase 失败 abort 退出等人工处理。**agent 不得擅自 force-with-lease / force push,尤其推 main**;确需强推须主控确认
- ⚠️ **deploy.sh `git add static-site/data/` 通配会带入工作区残留旧文件**(2026-07-20 事故根因):跑 deploy.sh 前确认工作区无旧版实时数据文件(尤其 `intraday_snapshot.json`,由 intraday-snapshot 定时任务独立 push,不被全量 deploy 带入);export.py 不生成 intraday_snapshot.json,工作区里的旧版会被通配带入 commit 覆盖线上新版
- ⚠️ **盘中(09:30-15:30)不跑全量 export + deploy**:全量 export + deploy 限定 15:35 后(收盘后),盘中只跑 intraday-snapshot 定时任务推 intraday_snapshot.json。agent 接"跑全量 export"任务须先确认时点,盘中拒绝或等收盘(撞 intraday-snapshot 定时任务推 main = 互相覆盖事故)
- ⚠️ **agent 推理“X 文件在 Y commit 里”前先核对**(2026-07-20 事故误判):用 `git show --stat <commit>` 或 `git log -- <file>` 确认文件实际是否在 commit 里、是哪个时点版本,不靠“Y commit 是 Z 时点跑的所以含 Z 时点数据”推理
- ⚠️ **验上线验功能生效层非代码在 main**(2026-08-05 教训):代码在 main + 版本号上线 ≠ 功能生效。说“已上线”前 curl JSON 验数据层(字段有值/无旧字段残留)+ 让用户确认显示。教训:判断预估成交额已上线但 amount_forecast={} 空对象后端没写数值;信号过滤代码在 main 但 overview.json 旧版 signals_today 还有 s.sentiment_cyb

### 8.1 R2 存储架构准则(2026-08-01 定,按数据类别不按大小)
- **R2 是存储架构的结构决策,不按单文件大小临时判断**。新数据类别从第一天就走 R2 架构(upload_r2 清单+前端 dataUrl R2 fallback),不等变大才补
- **走 R2 的类别(满足任一)**:①全量品种多(100+ index/31 industry/100+ trade_sim/1000+ public_fund) ②有大 range 历史序列(`-all/-5y/-3y` 单文件 >1MB) ③类别整体大(index 48M/industry 54M/trade_sim 268M/lab 109M)
- **走 CF Workers Static Assets 的小文件**:单文件 <100KB 且类别总量 <5MB 的状态/监控小文件(alert.json/daily_metric.json/schedule_stats.json/alert_analyze_*.json 等),走 R2 反增延迟(.gz 优先对小文件收益小)
- **upload_r2.py 5 个按前缀命令**(upload-lab/upload-index/upload-industry/upload-trade-sim[-json]/upload-public-fund)+ **1 个大小阈值兜底**(upload-data-large >=1MB,exclude industry-/public_fund)。大小阈值是兜底非主架构,**新数据类别优先按前缀建独立命令**,不依赖大小阈值
- **前端 dataUrl R2 fallback**:大 range 历史序列 `-(all|5y|3y).json$` 走 R2 `data/` 前缀;其他 R2 类别(industry/index/trade_sim/public_fund)用硬编码 `https://ssd.fx8.store/{prefix}/` URL(和 dataUrl 同模式,不扩展 `_R2_LARGE_RANGE_RE` 避免语义混淆)
- **本地留引用**:upload_r2 上传后不删本地 `static-site/data/`,CF Workers 兜底+本地开发;大文件可 `.gitignore` 移出 git(本地仍留),和 a-stock-all.json 等同策略
- **上线流程**:export.py 生成 JSON -> 末尾自动跑 R2 上传(EXPORT_SKIP_R2=1 跳过,deploy.sh 自己跑)-> git push 触发 CF deploy -> 前端 fetch(大 range 走 R2 直链,小文件走 CF)
- **判断 checklist(扫描 agent 用)**:①该类别是否有 upload-{prefix} 命令? ②前端 fetch 是否用 R2 URL 或 dataUrl 走 R2? ③upload-data-large exclude 是否含该前缀(防双副本)? 三条齐全=架构合规

## 9. 单版前端铁律(2026-07-15 web/ 弃用)
- 前端源码统一在 static-site/(web/ 已删,不再双写);app/main.py 挂载 static-site/ 到根 /,/api/* 读 DB 不变
- 改 CSS/JS 后跑 `scripts/build_min.py`(terser minify,仅 static-site/app.js+lab.js 2对)+ `scripts/bump_asset_version.py`(md5 前 8 位破缓存)
- 本地开发:`cd /Users/linhuichen/code/trade-data && /Users/linhuichen/code/trade/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000`(看页面+调API)或 `python -m http.server -d static-site`
- ⚠️ **uvicorn cwd 必须是 trade-data/**(2026-07-20 方案B,根治线上读滞后镜像):让 app/db.py 的 `.absolute()` 读最新主库 `trade-data/data/sentiment.db`(inode 237343239),非 `trade/` 滞后镜像(inode 238648312,仅 deploy.sh rsync 时同步)。launchd 写 trade-data/data/,uvicorn 从 trade/ 跑会读滞后镜像致 export 漏数据(resolve 修复 commit f0f6df78 需 cwd 切 trade-data 才生效)。trade-data/app 是 symlink 指向 trade/app,代码不变。调试加 `--reload`
- ⚠️ **改 app.js/lab.js 必 bump sw.js CACHE_VERSION**(2026-08-07 补):否则旧 Service Worker CacheFirst 缓存旧 app.min.js 致用户拿不到新代码(硬刷后退回旧数据)。build_min + bump_asset_version + **bump sw.js CACHE_VERSION** 三步缺一不可
- ⚠️ **min 版 JS 验证用字符串非变量名**(2026-08-07 补):terser mangle 重命名 let 局部变量(_compBarsHtml 等),grep 验 min 版上线用 class 名/中文字符串(kst-comp-fill/分项构成/优秀)非变量名
- ⚠️ **export 输出路径同步**(2026-08-07 补,§9 cwd trade-data 衍生陷阱):export.py cwd trade-data 写 JSON 落 trade-data/static-site/data/,但 deploy.sh 从 trade/static-site/data/ 推 git,两路径不同步推旧版。export 后必须 cp 或确认 rsync 同步

## 10. 切分支保护 DB(2026-07-14 已根治,作历史教训留存)
- 历史隐患:data/sentiment.db(80MB)+ etf_national_team.db 曾进 git 跟踪,切分支时 git 用旧版覆盖污染 DB,致 2026-07-14 事故(收盘快照丢失)
- **2026-07-14 已根治(commit 8e3f5fa)**:两 DB 移出 git(git rm --cached + .gitignore),现 untracked。线上全是 static-site/data/*.json 静态产物,不依赖 DB
- 切分支现在不会再碰 DB(untracked 文件 git 不跟踪)
- **教训(派 agent 同步分支时注意)**:DB 仍 tracked 时,checkout 切到另一分支会触发 git 用该分支版本覆盖本地 DB。正确同步 main 的方式 = 避免本地 checkout,用 `git fetch origin && git push origin feat/xxx:main` 或 reset,而非 `git checkout main && merge --ff-only`(中间态 checkout 仍 track DB 的分支会复现事故)
- 绝不能 `git restore data/sentiment.db` / `git checkout -- data/sentiment.db`(若不慎重新 add)

## 11. 子agent卡死/429处理(主动轮询+唤醒+重派读遗留)
- **标准流程:agent 完成 SendMessage to 'main' 主动通知**(2026-08-05 用户定,补 task-notification 会丢的短板):agent prompt 末尾要求完成时 `SendMessage to: 'main', summary: '完成', message: '<结论摘要+关键验收点>'`,harness "Messages from teammates are delivered automatically" 自动送达主控,不需轮询。比 task-notification(agent came to rest 时 harness 自动触发,被动,会丢)更可靠--agent 主动调用工具控制发送时机和内容。**轮询是兜底**(SendMessage 极端丢时 CronCreate 每10分钟 `grep DONE` 进度文件兜底,不干等)。2026-07-21 用户定10分钟(原3分钟太频繁打扰/费token),cron 用 `7,17,27,37,47,57` 避开 :00/:30
- 派agent的prompt要求写进度文件:**每完成一步立即echo**(每个grep/Edit都回写,不是每大步骤;2026-07-15 a194f曾只写"开始"641秒不回写致盲区),echo到 `/tmp/agent-progress-<名>.md`,主控Bash查(轻量不overflow),不依赖jsonl(大)/通知(会丢)/返回(可能429空)任一渠道
- **卡死**(jsonl mtime>600秒没动,10分钟轮询阈值放宽):先SendMessage试唤醒原会话(成本低,agent可能卡在长工具如grep/curl没退出,SendMessage排队等它下轮处理),下次轮询(10分钟)仍卡死=进程已死,重派新会话
- **429配额失败**:agent came to rest(退出运行)但task-id保留,配额恢复后**优先SendMessage resume原会话**(保留上下文比重派从头高效);resume不响应/状态乱才重派新会话。**2026-07-15教训(底线:不重复犯错)**:曾误判"429原会话已终止无法resume只能重派"(a194f 429后重派afe9从头跑,浪费a194f已查的32 tool_use上下文),实际task-notification note明说"can resume",429和卡死都优先resume--**配额恢复后第一动作是SendMessage resume原会话,不是重派**
- **came to rest**(agent完成一阶段停了等指令,非卡死非429):可随时SendMessage推进,不严格等480秒(2026-07-15 a5c6改名反复came to rest,SendMessage推进3次才完成;阈值可降到240秒)
- 重派新会话:让新agent读原agent遗留接着做(`/tmp/agent-progress-*.md`进度文件 + 工作区半成品,如数据时效a2ce接a06704b半成品),避免从头返工
- ⚠️ **worktree isolation SendMessage 不送达 + sm_use=0 违规**(2026-08-07 教训):worktree sidechain agent SendMessage to 'main' 返回 queued success 但不送达主控 session(harness 限制);非 worktree agent 也可能 sm_use=0(根本没执行 SendMessage 违规)。**worktree agent 必配 cron 兜底**(查进度文件 mtime+DONE 标记);**通用保险=cron 查进度文件**(不只依赖 SendMessage)
- ⚠️ **中途改口径停旧派新**(2026-08-07 教训,ETF盈亏4轮振荡):中途改口径/方向必须停旧 agent 派新 agent 带全新规格,不能 SendMessage 让旧 agent 继续(旧规格上下文致误操作反向)。改口径=停旧派新,非 resume
- ⚠️ **SendMessage resume 触发拒绝大重构**(2026-08-07 教训):SendMessage resume 触发“非用户确认”系统提示 agent 拒绝大重构(a11439db9 拒绝)。改派新 agent 初始 prompt 绕过(a00f4f2c8b 成功)
- ⚠️ **API 错误别卡死/重试同调用**(2026-08-07 补,§13 图片400外的通用):400/参数无效/不支持类报错别重试同调用(2天前连续3 agent a023 400/aabd/aff 卡死),换方案或暂存任务,别逼用户重启

## 12. superpowers 融合规则(2026-07-15 装 v6.1.1)
- superpowers 是纯 skill 库(14个,无 slash command),SessionStart hook 每次开会话强制注入 using-superpowers 全文(~800 token),且默认"1% 可能相关就主动调 skill"
- **优先级**:本项目 CLAUDE.md 硬规范 > superpowers skill。using-superpowers 声明"只有用户明示跳过才不走 skill",故下条明示跳过
- **运维/采集/上线/数据任务明示跳过** superpowers 的:①brainstorming 的 HARD-GATE(写码前必经设计门)②executing-plans/subagent-driven-development 的 continuous-execution(连轴转不停问用户)。这类任务**保留现有监工 loop**(§2§11:派 background 子agent→立即返回待命→CronCreate 轮询 jsonl mtime→卡死/429 优先 SendMessage resume→不问 yes/no 用户随时插话)
- **background 异步 + 卡死/429 轮询恢复机制保留不替换**:superpowers 假设子agent同步返回、无恢复机制,比现有弱
- **大型功能开发(策略实验室级)可按需用全套**:brainstorming→writing-plans(拆2-5分钟bite-sized task)→subagent-driven-development(implementer+reviewer+fixer循环)→TDD→finishing-a-development-branch
- **可借鉴技艺补强监工 loop**:①独立 task-reviewer 子agent 两阶段验收(spec合规+代码质量),作"逐字验证"之外第二双眼 ②大 diff 走文件交接(`.superpowers/sdd/review-*.diff`)不进主控上下文 ③progress ledger 落 `.superpowers/sdd/progress.md` 进 git 跨 compaction 可恢复,比 `/tmp/agent-progress-*` 耐久(长任务用)④using-git-worktrees 隔离并行改同区域

## 13. 模型能力约束(2026-07-16 计入)
- 当前模型(glm-5.2)**只支持文本输入,不支持图片**。Read 图片/截图/视觉对比会触发 API Error 400 "Model only support text input",终止 agent
- 派子 agent 时**禁止图片操作**(截图对比/UI 视觉看图/Read 图片验证效果)。需视觉验证的用文字描述+ASCII 示意图,或让用户自己看
- 子 agent 撞 400 "Model only support text input" = 尝试了图片输入。若其调研已基本完成,读进度文件 + 主控补完剩余即可,无需重派从头
- **2026-07-16 教训**:P2-4 og.png 压缩 agent 在“开始写报告”时疑似 Read og.png 验证压缩效果,撞 400 终止。但 P0-1 压缩调研已完成(坐实不可行),og.png 主控手动 magick 256色压缩补完(67KB->36KB),无损失
- **通用 API 错误别卡死/重试同调用**(2026-08-07 补):不只图片400,任何 400/参数无效/subagent_tokens=0/不支持类报错别重试同调用。换方案(重派新 agent 初始 prompt)或暂存任务,别逼用户重启。详见 §11

## 14. 生产稳定性 P0(2026-08-04 计入,最高优先级)
- **核心一句话:生产稳定性是 P0 第一要素**。项目已上线生产(ss.fx8.store/sss.sugas.site/s.sugas.site + ssd.fx8.store R2),定时任务撞车会导致线上数据覆盖事故/DB锁/用户看到错误数据,是不可逆生产故障
- **任务冲突检查不应由用户提醒才做**。每次派任务/设 cron/推 main 前**必须主动查 launchd 定时任务清单**(`launchctl list | grep trade` + 查 plist `StartCalendarInterval`),列当日盘后任务时点,确认新任务不撞,并**主动给用户时点建议**(不等用户问"会不会冲突")
- **核心冲突类型**:① 推 main(intraday-snapshot 15:35/20:35 + update-all 17:50 + deploy)vs 另一推 main = 互相覆盖事故(§8 已有 2026-07-20 gz方案B事故) ② 写 DB(评分/采集)vs 同 DB 任务 = DB锁/progress撞 ③ 采集脚本并发 = 限流空转
- **盘后定时任务时点(15:35/16:00/17:50/20:35/22:00)不推 main 不写 public_fund.db**;**盘中(09:30-15:30)不跑全量 export+deploy**(§8 已有)
- **安全窗口:23:00 后**无推 main/评分/采集任务(3:17 weekly 周日才跑,5:00 us-stock-morning 不写 public_fund.db),大型实施任务放此窗口
- **agent 自己 push feat:main 也要避开**盘后定时任务时点,不只 cron 任务。agent prompt 须写明"避开 15:35/16:00/17:50/20:35 push main,撞 intraday-snapshot/update-all 推 main = 互相覆盖事故"
- **盘中 push 前端代码 main 也避开 intraday-snapshot 每10分钟时点**(:25/:35/:45/:55/:05/:15,09:25-15:02 共27次推 intraday_snapshot.json 到 main)。agent 改 app.js/style.css 后 push feat:main 虽改不同文件 rebase 能合并,但 git push 竞争 non-ff 重试有风险,尽量错开。**盘中 push main 选 :00/:10/:20/:30/:40/:50 之外的安全分钟,或等盘后 23:00+ 窗口**
- 2026-08-04 教训:方案C盘后实施 cron 我直接定 15:35 没查 launchd,用户主动提醒才查,发现撞 5 个定时任务。改 23:03 启动避开。详见 memory `production-stability-p0`

## 15. 主功能回归复查(2026-08-06 计入,2026-08-06 强化)
- **核心一句话:新功能绝对不可以影响老功能**。站点功能日益庞大,改动影响面是网状的(一个数据文件被多模块读),单靠"改的人自己测 + 主控验关键点"覆盖不到跨模块回归
- **⚠️ 每次代码改动都要独立 review + 回归测试(2026-08-06 用户强化标准)**:不只大改动,**任何**改 app.js/lab.js/style.css/后端逻辑/数据产物脚本的改动,push 上线前必须:①派独立 task-reviewer 子 agent(grep 改动文件被谁引用+跑 P0 smoke)②reviewer 通过才 push main。流程:实施 agent 改完 -> reviewer agent review -> 通过 -> 主控 push main。"改的人自己测"不算 review,必须额外一双眼睛。今天(8/6)收盘hover/Task1/预估校准上线时没派 reviewer(执行不到位,已补派回归 review),此后严格执行
- **改动分级 + 小问题口子(2026-08-07 用户定,修订 L121 一刀切)**:review 本质是怕改坏逻辑,纯显示改无逻辑可坏,不需派 reviewer。按级别分级:
  - **A 级 小(纯显示)**:同时满足 5 条=①性质:纯显示/文案/CSS/常量配置(不动 if/for/事件绑定/数据结构/SQL/数据产物脚本) ②定位已知:改动点已知(用户指明或之前 agent 已定位行号),grep 即得,不需调研探索 ③量级:≤30 行纯改 ④验证:grep/读单点即确认正确(不需跑 smoke/多场景/curl 数据层) ⑤风险:前端代码可 git revert(不碰 DB/数据产物/后端/定时任务)。**主控直接改 + 主控 grep 自验 + 主控 push feat+main,不派实施 agent 不派 reviewer**。核心两条:纯显示不动逻辑 + 定位已知不需调研,任一不满足就升级派 agent
  - **B 级 大(逻辑)**:逻辑分支/if/for/事件绑定/数据结构/跨函数/跨模块。派 agent 实施 + 派 reviewer agent(批判性+P0 smoke) + reviewer 通过主控 push main
  - **C 级 数据/后端**:数据产物/SQL/后端/定时任务。派 agent 实施 + 派 reviewer + 数据完整性校验(check_data_integrity.py deploy 前置) + reviewer 通过主控 push main
  - **小口子打包原则**:多个 A 级小改动(≥3 个 或合计 >50 行)凑一起=派 agent 合适(打包一个 agent 一次实施省 cherry-pick,主控改多个分散点易漏)。单个 A 级主控改,多个打包派 agent。A 级是否"过多"看分散度+总行数,不绝对按个数
  - **08-06 教训对应 C 级**(board_etf_map.json 数据产物损坏),非显示改。教训针对数据/逻辑,纯显示改不威胁逻辑,A 级不派 reviewer 合理
- **大阶段回归必行**:当天开发功能多后/大阶段结束/上线前,必须做主功能快速全量回归,不等用户发现再修(那都晚了)
- **回归机制三层**:
  ① **数据产物完整性校验**:被多模块读的关键 JSON(`board_etf_map.json`空key占比<30% / `overview.json` a_amount非空 / `intraday_snapshot.json` collected_at今日 等)生成脚本跑完自动校验,超标 fail 不让 deploy(check_data_integrity.py deploy.sh 前置,已接入)。扩展 `collect_health` 到数据产物
  ② **task-reviewer 子 agent**:每次代码改动 push 前派独立 reviewer agent,不看新功能,专看"改动可能影响哪些老功能"(grep 改动文件被谁引用 + 跑关键老功能点),不占主控上下文(§12 superpowers 借鉴)
  ③ **关键功能 smoke 清单**:维护 P0/P1 主功能点清单(首页KPI角标/指数表现ETF/分时图hover/情绪分/信号/策略实验室入口等),每次上线前 reviewer agent 跑一遍 curl 数据层 + 关键交互文字描述验证,失败项立即修
- **2026-08-06 教训**:`board_etf_map.json` 因 `etf_index_map.json` 缺失常 27/72 空数组,致指数表现模块 ETF 展示全失效("全部无ETF"),用户发现时已上线。根因是某改动让数据产物损坏但无校验拦截。此 bug 触发本规范建立
- **smoke 清单落档**:主功能清单+数据校验规则放 `docs/smoke-checklist.md` 进 git(非 memory),reviewer agent 读取执行
- 模型只文本不能看 UI,回归验证用 curl JSON 数据层 + 关键交互文字描述 + 让用户确认显示三层

## 16. agent 角色画像与协作规范(2026-08-06 计入)
主控 + 子 agent 分工 + 通知兜底 + prompt 写作,集中规范(§2/§11/§15 细节互参,本节为总览)

### 主控(主 agent)= 项目管理(PM)定位
- **本质是项目管理,不是实施者**:拆任务、派活、收验收、控风险、排优先级、协调多 agent,不亲干实施。把代码库当项目,把子 agent 当团队成员,主控是 PM+技术总监
- 只做三件事:①派发任务(目标+约束+验收口径)②收子 agent 总结③逐字验证关键结论(§0 验收铁律,验1-2点点到即止)
- **不亲干调研/实施/分析活**(§2):grep 遍历/读代码结构/定位根因/方案分析全派子 agent;验收只确认 agent 已报的某个具体结论
- 监工 loop:派(run_in_background:true)->立即返回待命->收报告->验收->派下一个。用户随时插话,优先响应
- 不问 yes/no("要我跑吗/要不要验"自己定),只在真·方向分叉(A/B/C 选型)给选项附推荐(§4)
- **PM 职责延伸**:多 agent 并行冲突判断(§3)、生产稳定性风险把控(§14)、回归质量门禁(§15 reviewer)、任务优先级排序、跨任务依赖管理、进度落档(§7)

### 子 agent 角色(按职责分,fresh context 跑,不占主控上下文)
1. **调研 agent**:定位根因/查证/方案分析/盘点。**只读不改**。产出结论+证据(grep/SQL/读代码结果),主控验收。如 etf_index_map 丢失深挖、app.js 85模块盘点
2. **实施 agent**:写代码改文件。prompt 含目标+约束+验收口径+上线流程。如 Task1 宽基映射修复、收盘 hover 修复
3. **验收 agent**:主控轻量验收(grep/读单点验1-2点)够用时**不派**;需全面验证(多文件/多场景/跨模块)时派独立验收 agent
4. **reviewer agent**(§15 核心):独立看"改动影响哪些老功能",**批判性找问题,不改代码**。每次代码改动 push main 前必派,通过才上线。读 docs/smoke-checklist.md 跑 P0 smoke + grep 改动文件被谁引用
5. **测试 agent**:跑回归 smoke 清单/压测/边界测试。可由 reviewer 兼任或独立派(大改动时)
6. **综合 agent**:汇总多 sub-agent 结果产出文档。如 4 盘点 sub-agent -> 综合 agent 产出 docs/smoke-checklist.md
- **角色可兼任**:小任务一个 agent 调研+实施;大任务拆多角色(实施->reviewer->测试流水线)

### 通知与兜底机制(§11 细节,本节总览)
- **标准流程(主动通知)**:agent 完成 `SendMessage to: 'main'` 主动通知(harness 自动送达),比 task-notification(被动会丢)可靠。prompt 末尾要求此动作
- **进度文件**:agent 每步 echo 回写 `/tmp/agent-progress-<名>.md`(每个 grep/Edit 都回写,非每大步骤),主控 Bash 查(轻量不 overflow)
- **兜底轮询**:SendMessage 极端丢时,CronCreate 每10分钟(`7,17,27,37,47,57` 避 :00/:30)grep DONE 进度文件;`stat -L` 查 jsonl mtime(非 .output symlink,symlink mtime 不准会误判卡死)
- **卡死**(jsonl mtime>600秒没动):先 SendMessage 唤醒原会话(成本低,可能卡在长工具没退出)-> 下次轮询仍卡死=进程已死,重派新会话读遗留(`/tmp/agent-progress-*` + 工作区半成品)接着做,避免从头返工
- **429 配额失败**:配额恢复后**优先 SendMessage resume 原会话**(保留上下文比重派高效);resume 不响应/状态乱才重派。底线:不重复犯错(曾误判 429 原会话终止重派从头,浪费已查上下文)
- **came to rest**(agent 完成一阶段停了等指令,非卡死非429):可随时 SendMessage 推进,不严格等480秒
- **默认持久化**(§7):CronCreate 默认 durable:true;长任务进度落 git(`.superpowers/sdd/progress.md` 或 NOTES/TASKS)非 /tmp(/tmp 重启丢)

### agent prompt 写作规范
- **必含**:目标 + 约束(引用 CLAUDE.md 章节不重复全文,§4 减 token)+ 验收口径 + 上线流程(如适用)+ 进度文件路径 + 完成时 SendMessage to 'main'
- **约束引用**:"见 §8/§14" 而非重述全文;只写本次任务特有约束
- **禁止图片操作**(§13):模型只文本,Read 图片触发 400 终止 agent;需视觉验证用文字+ASCII 示意图或让用户看
- commit message 末尾加 `Co-Authored-By: Claude <noreply@anthropic.com>`
- push feat **普通推送,不 force-with-lease**(§8);non-ff 优先 `git fetch + rebase origin/main + 重试`,rebase 失败 abort 等人工,agent 不强推
- 避开定时任务时点(§14):盘中 push main 避开 intraday 每10分钟(:25/:35/:45/:55/:05/:15)+ 盘后(15:35/16:00/17:50/20:35/22:00),安全窗口 23:00+ 或午休 11:30-13:00

## 17. 火山方舟高峰时段省token(2026-08-06 计入)
- **火山方舟(模型提供方)14:00-18:00 高峰期高倍率结算**,开发派 agent(token 消耗大)尽量避开此时段,放 18:00 后或上午
- **简单对话/验收/轻量操作(消耗小)无所谓**,只针对派实施/调研 agent(消耗大)规避
- **14-18 必须干活时**:优先轻量验收/对话,重实施 agent 推迟到 18:00 后;用户主动派活除外(响应优先)
- 和 §14 并列:§14 避开定时任务时点(生产安全 P0),§17 避开高峰倍率(省 token);两者时点重叠时(如 15:35 既撞定时又高峰)双重规避
- **派 agent 前看时间**:14-18 期间如非紧急,向用户说明"高峰倍率,建议 18 后跑"等用户定;用户确认立即跑不卡

## 验收铁律
逐字验证关键结论(grep/SQL/读代码),不信 agent 报告。报"完成"不等于真完成。
