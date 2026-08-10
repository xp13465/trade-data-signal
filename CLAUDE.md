# 工作模式规范

本文件为 Claude(主控)与用户协作的硬规范,每次开工前必读。

## ⚠️ COMPACT 恢复后第一动作(每次上下文压缩后现读现守)
你刚 compact,最容易忘工作模式,本条放第一屏就是逼你现读现守。铁律:主控只做①派 background agent(调研/定位/实施/分析全派)②收总结③逐字验收。
- **验收 = 只 grep/读单点确认 agent 报的某个具体结论**(如确认一行清单、一个字段值、一行代码),点到即止
- **展开查代码结构 / 遍历数据 / 定位根因 / 分析方案 = 调研,必派 background agent,不亲手干**
- 别以"验收"为名亲手 grep 一堆--验收是确认 agent 已报的结论,不是自己去发现根因
- 教训:compact 后曾亲手跑 6 个 Bash 查 indices 结构/renderGlobal 逻辑(调研活,违规);只 grep 一行确认清单算验收
- **compact 恢复 5 步清单**(2026-08-07 补,防 compact 后丢 transient 状态):compact 后第一动作 5 步恢复:①读 TASKS 会话状态小节(当前在跑的 agent/待办/决策)②读 NOTES §48 近期章节 ③CronList 查活跃 cron ④stat -L 查 agent jsonl mtime 确认在跑/卡死 ⑤git log 查最近 commit 链确认上线状态。派 agent/收报告/设 cron/commit 后实时 Edit TASKS 会话状态小节
- **reviewer PASS 后主控不 §0 复验代码 + 主控§0 与 agent 自验去重**(2026-08-07 用户定,省 token):①reviewer 是独立验收 agent(fresh context 批判性查),reviewer PASS 后主控信 reviewer,不 §0 重复 grep 代码点。主控 §0 只验上线点(push hash 在 main + curl 验功能生效层,reviewer 不验线上 deploy)+ 复验可疑 reviewer(FAIL/可疑时亲自确认再回滚/修)。即 §0 从"验代码"转为"验上线+复验可疑"②agent 自验 grep 代码点,主控 §0 不重复同点,只验 agent 自验没覆盖的。避免三层(agent 自验+主控§0+reviewer)重复 grep 代码点

## 1. 开工前先读工作模式
每次会话开始/恢复上下文/接新任务,第一件事先读本文件(或对应 memory),不是想读才读。这是和"杜绝 token 浪费"并列的硬准则。

## 2. 监管+loop(主控只派发,不亲自干活)
- 主控只做三件事:①派发任务(含目标+约束+验收口径)②收子 agent 总结③逐字验证关键结论(grep/SQL/读代码,不信 agent 报告)
- **调研/定位/分析问题也派子 agent**,不只派"实施"。主上下文不做 grep/Read/方案分析这些"调研活"
- 用 Agent 工具派子 agent(**必须 `run_in_background: true`** + **派完立即 CronCreate 兜底**,见 §11;SendMessage 通知会丢,cron 兜底查进度文件 DONE+jsonl mtime 防傻等。cron 兜底查进度文件 DONE+jsonl mtime 防傻等(架构限制下最优,见 §11))
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
- **⚠️ 落档是经验积累成长的重要准则(2026-08-08 用户三次强调)**：重要和有价值的东西都要落档文件,方便后续校对排查避免重复犯错。落档不只是防丢,是经验积累成长的基础--每次重要结论/决策/方案/检查报告落档,后续可校对排查,避免重复犯错(发现成本+返工成本高)。派 agent+收报告后立即落档 NOTES/TASKS,不只报口头;agent 完成即落档,不累积
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
- ⚠️ **交易日盘中(09:30-15:30)不跑全量 export + deploy**:全量 export + deploy 限定交易日 15:35 后(收盘后);**周末/节假日休市例外:intraday-snapshot 不推数据无撞车风险,可随时跑不等盘后**(2026-08-09 教训:曾误让用户等盘后,用户提醒周末不开盘)。盘中 intraday-snapshot 走 R2 上传不推 main(2026-08-10 R2迁移阶段3 commit 508eabb44)。agent 接"跑全量 export"任务须先确认**是否交易日**+时点,交易日盘中拒绝或等收盘(防全量 export 覆盖 R2 实时数据,非避 push main),休市直接跑
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
- **新数据类别上线 checklist(2026-08-11 定)**:写 `static-site/data/` 的生成器必须同时接 ①R2 上传(upload_r2 清单或 export 自动) ②staticdata 同步(**scripts/staticdata_sync.sh** 或跑 deploy.sh 覆盖)。尤其「只写 static-site/data + 调 upload_r2 但不跑 deploy.sh」的独立生成器(如 gen_daily_brief.py),缺 staticdata 会留旧版直到下次 deploy(同步时机缺口,机制见 docs/staticdata-daily-brief-sync.md)
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
- **通知机制四层:cron 兜底为主(架构限制下最优)+ SendMessage/task-notification 补充(有时送达更快但不可靠)+ 进度文件 DONE(证据)+ notify.py 邮件只重要节点**(2026-08-05 定,2026-08-09 调研穷尽修正,见下):harness 架构下无"子agent完成结论可靠送达主控 session"的完美主动通知方案(调研 ae65 穷尽)。①**cron 兜底为主**(派 agent 后立即设,不设=傻等):`durable:true`,每15分钟 `3,18,33,48`,prompt 查 `## DONE` + `stat -L` jsonl mtime(>900s 卡死)。DONE->落档 TASKS+推进;卡死->resume/重派;运行中->极简报。agent 处理完 CronDelete。2026-07-21 定10分钟(原3分钟太频繁),2026-08-08 用户改15分钟(省cron调用) ②SendMessage/task-notification 为补充(走同一队列,不可靠) ③进度文件写 `## DONE <结论>`(证据) ④notify.py 邮件只重要节点(上线完成/生产异常/需用户介入),非每 agent 完成
- ⚠️ **harness 架构硬限制(2026-08-09 调研 ae65 穷尽)**:harness 层无"子agent完成结论可靠送达主控 session"的完美主动通知方案。根因=消息队列"单消息注入清除其余"设计(注入一条会清空队列其余消息)+ task-notification 优先级 later + 多子agent同时完成互相竞争(96%丢)。具体:①SendMessage 送达率~1.9%、task-notification ~12%,都走同一队列不可靠 ②SubagentStop hook 的 additionalContext 注入子 agent 非主控 ③无 CLI 命令向运行中 session 注入消息
- ⚠️ **根本矛盾**:不阻塞(用户随时插话,§2)+ 主动可靠通知主控 = harness 架构下不可兼得。notify.py 通知用户转告=用户否定("靠我在通知你这个方案比兜底还糟",依赖用户比 cron 兜底还糟)
- ✅ **cron 兜底是架构限制下最优残余**(不阻塞前提下主控自主唯一可靠):15min 延迟 + token 成本是代价,但无完美主动通知方案时是唯一可靠路径。实际维持原样(派 agent 立即设 cron 兜底防傻等)。notify.py 邮件降级为只重要节点(上线完成/生产异常/需用户介入),非每 agent 完成。曾误判"notify.py 邮件主方案/L0 直达"为标准方案并实施,调研穷尽后推翻(2026-08-09 修正)
- ⚠️ **2026-08-08 教训(cron 不设致傻等+状态不一致)**:曾把 cron 当"极端丢时才用"兜底,致派 agent 后不设 cron(CronList 空)纯等 SendMessage->傻等+用户来问+状态不一致。修复:派 agent 同步设 cron 兜底(必设防傻等)。cron 是架构限制下最优残余,不是"治标待替代"
- 派agent的prompt要求写进度文件:**每完成一步立即echo**(每个grep/Edit都回写,不是每大步骤;2026-07-15 a194f曾只写"开始"641秒不回写致盲区),echo到 `/tmp/agent-progress-<名>.md`,主控Bash查(轻量不overflow),不依赖jsonl(大)/通知(会丢)/返回(可能429空)任一渠道
- **卡死**(jsonl mtime>900秒没动,15分钟轮询阈值):先SendMessage试唤醒原会话(成本低,agent可能卡在长工具如grep/curl没退出,SendMessage排队等它下轮处理),下次轮询(15分钟)仍卡死=进程已死,重派新会话
- **429配额失败**:agent came to rest(退出运行)但task-id保留,配额恢复后**优先SendMessage resume原会话**(保留上下文比重派从头高效);resume不响应/状态乱才重派新会话。**2026-07-15教训(底线:不重复犯错)**:曾误判"429原会话已终止无法resume只能重派"(a194f 429后重派afe9从头跑,浪费a194f已查的32 tool_use上下文),实际task-notification note明说"can resume",429和卡死都优先resume--**配额恢复后第一动作是SendMessage resume原会话,不是重派**
- **came to rest**(agent完成一阶段停了等指令,非卡死非429):可随时SendMessage推进,不严格等480秒(2026-07-15 a5c6改名反复came to rest,SendMessage推进3次才完成;阈值可降到240秒)
- 重派新会话:让新agent读原agent遗留接着做(`/tmp/agent-progress-*.md`进度文件 + 工作区半成品,如数据时效a2ce接a06704b半成品),避免从头返工
- ⚠️ **worktree isolation SendMessage 不送达 + sm_use=0 违规**(2026-08-07 教训):worktree sidechain agent SendMessage to 'main' 返回 queued success 但不送达主控 session(harness 限制);非 worktree agent 也可能 sm_use=0(根本没执行 SendMessage 违规)。**worktree agent 必配 cron 兜底**(查进度文件 mtime+DONE 标记);**通用保险=cron 查进度文件**(不只依赖 SendMessage)
- ⚠️ **中途改口径停旧派新**(2026-08-07 教训,ETF盈亏4轮振荡):中途改口径/方向必须停旧 agent 派新 agent 带全新规格,不能 SendMessage 让旧 agent 继续(旧规格上下文致误操作反向)。改口径=停旧派新,非 resume
- ⚠️ **停前确认规格对错,规格对优先 resume**(2026-08-08 教训):停 agent 前先对照用户最新需求确认 agent 规格对错。**规格对(已 commit 正确代码)优先 SendMessage resume 复用上下文**(省 token,TaskStop 后 task-id 保留 SendMessage 可 resume transcript 恢复,实测 af062cc257e3ce2e3 resume 成功"had no active task; resumed from transcript"),只有**真改口径**(用户明确改方向)才停旧派新。区分:真改口径=停旧派新;**误解口径**(主控理解错,agent 规格其实对)=resume 非停旧派新。教训:误解 self 去体量停了 af062cc257(其 fa6f88a2f self 补 amount 规格对),新开 ae7587bd7/ae91cb28ac fresh context 重新读代码费 token,应 resume af062cc257
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
- **盘后定时任务时点(15:35/16:00/17:50/20:35/22:00)不推 main 不写 public_fund.db**;**交易日盘中(09:30-15:30)不跑全量 export+deploy**(§8 已有,休市可随时跑)
- **安全窗口:23:00 后**无推 main/评分/采集任务(3:17 weekly 周日才跑,5:00 us-stock-morning 不写 public_fund.db),大型实施任务放此窗口
- **agent 自己 push feat:main 也要避开**盘后定时任务时点,不只 cron 任务。agent prompt 须写明"避开 15:35/16:00/17:50/20:35 push main,撞 intraday-snapshot/update-all 推 main = 互相覆盖事故"
- **⚠️[2026-08-10 R2迁移阶段3 更新]盘中 push 代码 main 不再避 intraday 时点**:intraday-snapshot 已改走 R2 上传不推 main(commit 508eabb44),static-site/data/ 移出 git(.gitignore L188 `static-site/data/*`),代码仓库不含数据 JSON。盘中 push 代码 main(app.js/style.css/min JS)不撞 intraday 数据(代码走 git push main,数据走 R2,不同渠道不竞争 non-ff)。**但盘后 17:50 update_all deploy.sh 推 main 仍需注意 non-ff 竞争**(deploy.sh 有 rebase 重试机制 L300-490,non-ff 自动 rebase)。盘中全量 export+deploy 仍禁(理由从"撞 intraday push main"变为"防 export 覆盖 R2 实时数据")
- 2026-08-04 教训:方案C盘后实施 cron 我直接定 15:35 没查 launchd,用户主动提醒才查,发现撞 5 个定时任务。改 23:03 启动避开。详见 memory `production-stability-p0`

## 15. 主功能回归复查(2026-08-06 计入,2026-08-06 强化)
- **核心一句话:新功能绝对不可以影响老功能**。站点功能日益庞大,改动影响面是网状的(一个数据文件被多模块读),单靠"改的人自己测 + 主控验关键点"覆盖不到跨模块回归
- **⚠️ 每次代码改动都要独立 review + 回归测试(2026-08-06 用户强化标准)**:不只大改动,**任何**改 app.js/lab.js/style.css/后端逻辑/数据产物脚本的改动,push 上线前必须:①派独立 task-reviewer 子 agent(grep 改动文件被谁引用+跑 P0 smoke)②reviewer 通过才 push main。流程:实施 agent 改完 -> reviewer agent review -> 通过 -> 主控 push main。"改的人自己测"不算 review,必须额外一双眼睛。今天(8/6)收盘hover/Task1/预估校准上线时没派 reviewer(执行不到位,已补派回归 review),此后严格执行
- **改动分级 + 小问题口子(2026-08-07 用户定,修订 L121 一刀切)**:review 本质是怕改坏逻辑,纯显示改无逻辑可坏,不需派 reviewer。按级别分级:
  - **A 级 小(纯显示)**:同时满足 5 条=①性质:纯显示/文案/CSS/常量配置(不动 if/for/事件绑定/数据结构/SQL/数据产物脚本) ②定位已知:改动点已知(用户指明或之前 agent 已定位行号),grep 即得,不需调研探索 ③量级:≤30 行纯改 ④验证:grep/读单点即确认正确(不需跑 smoke/多场景/curl 数据层) ⑤风险:前端代码可 git revert(不碰 DB/数据产物/后端/定时任务)。**主控直接改 + 主控 grep 自验 + 主控 push feat+main,不派实施 agent 不派 reviewer**。核心两条:纯显示不动逻辑 + 定位已知不需调研,任一不满足就升级派 agent
  - **B 级 大(逻辑)**:逻辑分支/if/for/事件绑定/数据结构/跨函数/跨模块。派 agent 实施 + 派 reviewer agent + reviewer 通过主控 push main。**reviewer 按影响面分级**(2026-08-07 补,省 token):①无隐藏影响面(单点逻辑,不被轮询/事件/跨函数引用):agent 自验+主控§0单点,不派 reviewer ②有隐藏影响面(轮询/事件/跨函数/数据被多模块读):派 reviewer 只查影响面+相关 smoke(不跑全 P0) ③广涉及面(跨模块/数据产物/定时任务/后端):完整 reviewer(全 P0 smoke+check_data_integrity)
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
- **cron 兜底为主(架构限制下最优,2026-08-09 调研穷尽)**:派 agent 后立即 CronCreate 兜底,这是不阻塞前提下主控自主唯一可靠路径(SendMessage~1.9%/task-notification~12% 送达率都走队列不可靠,无完美主动通知主控方案,见 §11)
- **SendMessage/task-notification(补充,有时送达更快但不可靠)**:agent 完成 `SendMessage to: 'main'`,走消息队列(单消息注入清除其余设计,~1.9% 送达率,不可单靠)+ 进度文件写 `## DONE <结论>`(证据)。prompt 末尾要求这两个动作
- **L2 进度文件**:agent 每步 echo 回写 `/tmp/agent-progress-<名>.md`(每个 grep/Edit 都回写,非每大步骤),完成写 `## DONE <结论>`,主控 Bash 查(轻量不 overflow)
- **cron 兜底(架构限制下最优,见 §11)**:派 agent 后立即 CronCreate(`durable:true`,每15分钟 `3,18,33,48` 避 :00/:30),prompt 查进度文件 `## DONE` + `stat -L` jsonl mtime(非 .output symlink,symlink mtime 不准会误判卡死)。DONE->落档 TASKS+推进;卡死->resume/重派;运行中->极简报。agent 处理完 CronDelete。**不设 cron 纯等 SendMessage=傻等**(8/8 教训)。notify.py 邮件只重要节点(上线完成/生产异常/需用户介入),非每 agent 完成
- **卡死**(jsonl mtime>900秒没动):先 SendMessage 唤醒原会话(成本低,可能卡在长工具没退出)-> 下次轮询仍卡死=进程已死,重派新会话读遗留(`/tmp/agent-progress-*` + 工作区半成品)接着做,避免从头返工
- **429 配额失败**:配额恢复后**优先 SendMessage resume 原会话**(保留上下文比重派高效);resume 不响应/状态乱才重派。底线:不重复犯错(曾误判 429 原会话终止重派从头,浪费已查上下文)
- **came to rest**(agent 完成一阶段停了等指令,非卡死非429):可随时 SendMessage 推进,不严格等480秒
- **默认持久化**(§7):CronCreate 默认 durable:true;长任务进度落 git(`.superpowers/sdd/progress.md` 或 NOTES/TASKS)非 /tmp(/tmp 重启丢)

### agent prompt 写作规范
- **必含**:目标 + 约束(引用 CLAUDE.md 章节不重复全文,§4 减 token)+ 验收口径 + 上线流程(如适用)+ 进度文件路径 + 完成时通知(见 §11,架构限制下 cron 兜底为主):①`SendMessage to: 'main', summary: '完成', message: '<结论摘要>'`(补充,不可靠)②end_turn 退出触发 task-notification 带 result(harness 自动,补充)③进度文件写 `## DONE <结论>`(证据)④重要节点(上线完成/生产异常/需用户介入)调 `python3 scripts/notify.py --agent-done <名> '<结论摘要>'` 发邮件(非每 agent 完成)
- **约束引用**:"见 §8/§14" 而非重述全文;只写本次任务特有约束
- **禁止图片操作**(§13):模型只文本,Read 图片触发 400 终止 agent;需视觉验证用文字+ASCII 示意图或让用户看
- commit message 末尾加 `Co-Authored-By: Claude <noreply@anthropic.com>`
- push feat **普通推送,不 force-with-lease**(§8);non-ff 优先 `git fetch + rebase origin/main + 重试`,rebase 失败 abort 等人工,agent 不强推
- 避开定时任务时点(§14):盘中 push 代码 main 无需避 intraday(2026-08-10 intraday 走 R2 不推 main,代码数据不同渠道),但避盘后 update_all 17:50 deploy.sh 推 main non-ff 竞争(有 rebase 重试);盘中全量 export+deploy 仍禁(防覆盖 R2 实时数据)

## 17. 火山方舟高峰时段省token(2026-08-06 计入) ⚠️[2026-08-09 用户定]18点高峰期限制已取消,派agent不再避14-18随时可派,以下条文作废留存备查
- **火山方舟(模型提供方)14:00-18:00 高峰期高倍率结算**,开发派 agent(token 消耗大)尽量避开此时段,放 18:00 后或上午
- **简单对话/验收/轻量操作(消耗小)无所谓**,只针对派实施/调研 agent(消耗大)规避
- **14-18 必须干活时**:优先轻量验收/对话,重实施 agent 推迟到 18:00 后;用户主动派活除外(响应优先)
- 和 §14 并列:§14 避开定时任务时点(生产安全 P0),§17 避开高峰倍率(省 token);两者时点重叠时(如 15:35 既撞定时又高峰)双重规避
- **派 agent 前看时间**:14-18 期间如非紧急,向用户说明"高峰倍率,建议 18 后跑"等用户定;用户确认立即跑不卡

## 18. 犯错积累与防重犯(2026-08-08 起,每次犯错追加)
用户定:慢慢积累经验迭代完美。每次犯错记录于此 + 防重犯条款,不重犯同类。
- **2026-08-08 犯错 7 条**:
  1. 通知丢失不设 cron 傻等(§11:cron 兜底必设防傻等;2026-08-09 调研穷尽无完美主动通知主控方案,cron 兜底是架构限制下最优残余)
  2. DB 方案理解反复 3 次纠正(防:关键决策前复述理解让用户确认,不臆断不反复)
  3. 架构偏差 exclude 偏离全量本意(防:用户说"全量/全部"不擅自 exclude/清理,先确认)
  4. .gz 断定不严谨凭 memory(防:断定前验证,memory 可能过时,不凭记忆断定)
  5. agent 误报 trade/trade-data 混淆未识破(防:agent 关键结论 §0 验,尤其路径/文件数类)
  6. cherry-pick 撞冲突 + 干扰后台 agent(防:切分支/checkout 前 CronList + 查后台 agent 是否改文件)
  7. hoverpop 方案试错(防:方案先调研充分再实施,不边试边改)
- **通知机制(2026-08-09 调研穷尽修正)**:见 §11。harness 架构硬限制无完美主动通知主控方案(SendMessage~1.9%/task-notification~12% 都走队列不可靠,队列"单消息注入清除其余"+多agent竞争96%丢;SubagentStop hook 注入子agent非主控;无CLI向运行中session注入),cron 兜底是架构限制下最优残余(不阻塞前提下主控自主唯一可靠),notify.py 邮件降级只重要节点。曾误判 notify.py 主方案并实施后推翻
- **2026-08-08 会话级总结追加(ETF信号灯+hoverpop+lowconf+拆档阶段,5条新过错)**:
  8. ETF拆档 null 归属理解错(根因:主控把 null/N<30 极弱归入"概念无ETF"档,但"概念无ETF"=真无任何ETF匹配,null/N<30=有ETF但数据不足算出极弱分,两者语义不同;用户纠正 null 有ETF算得出分应归"有跟踪ETF"档。防:归属/分类前复述口径让用户确认,不靠语义猜测"无数据=无ETF")
  9. hoverpop"无数据"调研误判(根因:调研agent说"signal-tier没铺到hoverpop用老逻辑",实际前端三处都已用_etfLightInfo接track_tier,真因是数据产物不一致(R2 index-all旧'none' vs overview新null)+前端文案L1553 null->"无数据"应"极弱"。防:调研下结论前深入到数据产物层验证(R2旧版vs新版字段值差异),不只看代码逻辑分支;调研结论"没铺到/老逻辑"类要 grep 验证再报)
  10. low_confidence灰蓝虚线过时规则未发现(根因:信号灯统一配色时,_etfLightInfo在track_tier判断之前拦截`if(track_low_confidence) return 灰蓝虚线`,直接覆盖档位灯。统一配色只改了主路径没遍历所有拦截分支。防:改动一个灯/样式体系时遍历所有 return/分支(不只主路径),grep 所有 `return {cls:` 确认无过时拦截)
  11. 需求2理解错加未要求改动(根因:用户需求只说"信号列表中间加信号灯",主控理解成"展示ETF名/代码替代指数名/代码"并实施。加了用户没要求的改动。防:理解需求时不擅自加未要求的改动(只做明确要求的),不确定时复述需求让用户确认"是否还要改X")
  12. 至今盈亏调研方向偏差(根因:用户说"走势卡相关etf后面至今盈亏不见了",调研去查生成逻辑queries.py etf_since_return而非显示层etf-tag-pnl渲染。没对准用户实际看到的问题位置。防:调研先对准用户描述的UI位置(grep 渲染层),确认显示层无问题再查生成层,不直接跳到生成层)
  13. 量子科技调研误判"0量子ETF/不可改善"(根因:调研agent只用了当前算法匹配范围——name+track_index搜"量子"无结果+overlap只看成分股直接重叠,断定"全市场0只量子ETF/不可改善"。但用户用同花顺(第三方平台)搜到多个相关ETF(大数据516000/云计算516510/央企科技562380/科创159335),真因是算法只看成分股直接重叠不看ETF持仓重叠。第二次调研才找到根因+方案(第4层ETF持仓重叠匹配)。防:调研"无/0/不可改善"类结论,不只验证当前算法覆盖范围,要换方法/换数据源(第三方平台如同花顺概念搜索)+考虑不同关联维度(持仓重叠 vs 成分重叠),不轻断"不可改善";调研结论里列"已验证哪些方法/数据源"便于主控判断充分性)
- **token浪费(本阶段)**:①hoverpop信号灯问题重复调研(第一次误判"没铺到老逻辑"第二次才找真因数据产物不一致,应一次调研到位:代码+数据产物同查)②移动端hoverpop修复试错返工(第一次white-space:normal+flex-wrap:wrap效果更差布局错乱,方案应先充分验证移动端窄屏实际效果再实施,不靠推理)③多次429配额耗尽(L6411信号灯分层/L6506 reviewer/L6507 push告警调研,月配额耗尽致全agent终止;§17高峰期多个agent并发消耗大,防:高峰期控制并发agent数,非紧急推迟到18后)④量子科技调研重复(第一次断"0/不可改善"过早,第二次才找到持仓重叠根因+方案,同①模式复发:调研"不可改善"结论过早致二次调研,应一次调研到位:换方法/换数据源+多关联维度同查)
- **每日归纳(2026-08-08 全天 13 条过错,按主题分组,不删减只归类)**:
  - 通知机制(1条):①不设cron傻等(§11:cron兜底必设;2026-08-09穷尽无完美主动通知主控方案,cron为架构限制下最优残余)
  - 理解/口径偏差(3条):②DB方案反复3次⑧ETF拆档null归属⑪需求2加未要求改动(共性:关键决策/归属/需求前复述确认,不臆断不扩展)
  - 调研不充分/误判(4条):④.gz凭memory断定⑨hoverpop调研误判⑫至今盈亏方向偏差⑬量子科技"0/不可改善"误判(共性:下结论前验证数据产物层/换方法换数据源/对准UI位置,不只看当前算法范围)
  - 架构/全量(1条):③exclude偏离全量(防:用户说全量不擅自exclude)
  - agent结论验收(1条):⑤trade/trade-data混淆(防:路径/文件数类§0验)
  - git操作(1条):⑥cherry-pick撞冲突(防:切分支前查后台agent)
  - 实施/试错(2条):⑦hoverpop方案试错⑩lowconf过时规则未发现(共性:方案先充分调研再实施;改体系遍历所有分支)
  - token浪费:重复调研(hoverpop+量子)②试错返工(移动端)③高峰并发429(共性:一次调研到位+先验证再实施+高峰控制并发)
  - 中心思想校准:13条过错核心="调研/理解/实施前充分验证,不臆断不轻断不试错",防重犯条款保持具体可执行
- **2026-08-08 追加过错(量子科技第4层需求丢失)**:
  - 过错:①第二次调研找到第4层ETF持仓重叠方案后没落档TASKS待办,只存memory教训,致需求丢失(§7:memory非持久化写保障,落档NOTES/TASKS才是写保障) ②批量归档28条标done时把e4007405d标done+虚构完成依据(TASKS-done L1448说"做了第4层+匹配516000等ETF"),但 `git show e4007405d` commit message自述"量子科技thsc_300830确认不可改善(0量子ETF)",直接矛盾,凭commit标题臆断未核对实际内容
  - 防重犯:①调研找到方案后必须立即落档TASKS待办(不只存memory,memory非持久化) ②归档done前必须 `git show <commit>` 核对commit message实际内容,不凭commit标题/摘要臆断完成内容(commit标题可能只说大方向,body才说具体做了什么/没做什么)
- **2026-08-08 追加(方案A board_etf_map数据产物遗漏+reviewer误报,印证回归检查不完整)**:
  - 过错:①方案A agent 改 build_board_etf_map.py 代码(TRACK_WEIGHTS_INDIRECT)也重跑了生成新 board_etf_map.json(源文件trade-data/data/已是159586),但**build_board_etf_map.py写ROOT/data/(用.absolute()非.resolve()),export.py不复制board_etf_map到static-site/data/,data/->static-site/data/复制步骤遗漏**,两处static-site旧版516630+R2旧版 ②reviewer验"local board_etf_map=159586"误报,实际local static-site=516630(reviewer没真读上线文件,信agent自验或验了源文件trade-data/data/而非static-site上线文件) ③主控§0 curl board_etf_map才发现(overview 159586但board_etf_map 516630不一致),非等用户发现
  - 防重犯:①算法改动重跑数据产物时,列所有依赖该算法的数据产物清单(board_etf_map/overview/index detail/trade_sim)逐个确认**重跑+同步到static-site/data/+上传R2**三步完整,不只重跑 ②build_board_etf_map.py写ROOT/data/需手动cp到static-site/data/(export.py不复制它,data/->static-site/data/是独立步骤,memory export-output-path-sync衍生陷阱) ③reviewer验数据产物必须真读上线文件(static-site/data/或R2/CF)非源文件或agent自验,reviewer prompt明确"curl local static-site+R2+CF三处验具体字段值" ④主控§0不只验主路径(overview),验所有相关数据产物三版本一致(overview vs board_etf_map vs index detail) ⑤agent自验+reviewer+主控§0三层都需真验文件内容,任一层信结论不验文件=漏洞
- **2026-08-09 追加(量子科技3展示位数据不一致)**:
  - 过错:层B concepts.json R2未更新(方案A重跑board_etf_map时 concepts 的 upload-industry 遗漏),本地新版(159586)没上传R2,线上R2旧版(516630);层A stable_top1滞回 count=2 未切换(设计行为明天自动),term-pop 优先滞回标记(516630)非分数第一(159586)。3展示位(概念列表top1/相关ETF hoverpop/首页信号hoverpop)看到不一致数据
  - 防重犯:①更新必N处同步(数据一致性铁律§22)②算法改动重跑时列所有依赖数据产物(含concepts.json)逐个确认重跑+同步static-site+R2三步(§18已有教训重申)③滞回切换时确认3展示位(overview stable_top1+board_etf_map hysteresis+concepts)同步切换
- **2026-08-09 追加(凯利回测系列4条过错+§0证伪查错文件)**:
  14. D修正 annualized 口径判断偏差(根因:主控 prompt 指定用 total_return 总盈亏/单笔本金 开方,y1=258.78% 年化 258% 明显不合理--固定金额非复利,总盈亏/单笔本金=平均×笔数非真实收益率。用户定改 return_pct_max_holding 峰值资金收益率开方 y1≈3.04% y10≈1.37% 合理。commits 2686adf80 错->4c6d50917 修。防:指定计算口径前先验算典型值合理性,年化>100% 或负值应警觉查口径定义,不直接实施不合理口径;同§18教训⑦模式"方案先充分调研再实施"的口径版--口径也要验算非只方案)
  15. 前端改 agent 漏做2个追加 A级小改(根因:SendMessage 追加费率格式+卡间水印布局2任务给运行中 agent,送达率低~1.9%(§11)agent commit 前没处理,需另开 commit b4ac948ab 补做。防:追加任务给运行中 agent 不只靠 SendMessage,主控在 agent commit 前主动确认追加任务是否处理;或追加任务等当前 commit 后派新 agent 不追加到运行中 agent;同§11 SendMessage 不可靠的延伸--追加任务=改规格,应走"停旧派新"或"commit后新派"非SendMessage)
  16. 数据没上线 R2(根因:backfill 0d6fe0edd 没 upload signal_kelly(backtest/trades.json),CF 404 用户访问看不到。backfill 不跑 signal_kelly_backtest.py(独立脚本无 launchd)+export.py upload_r2 没传 signal_kelly。防:新数据类别上线后确认上传链路完整三步:①export.py upload_r2 清单含该类别②launchd 定时覆盖或 deploy.sh 含③backfill 补跑上传;独立脚本(无 launchd)的 backfill 手动补跑上传 R2;同§18"算法改动重跑数据产物列清单逐个确认重跑+同步static-site+R2三步"的上线链路版)
  17. §0 证伪查错文件(根因:前次 agent 说"CF edge 缓存 industry-all-concepts.json",主控 §0 跟着查错文件,实际走势图读 thsc_300830-all.json。§0 验收信 agent 说的文件名没 grep 前端渲染逻辑确认实际读哪个。防:§0 证伪前先 grep 前端渲染逻辑(fetch/dataUrl/fetchJSON)确认实际读哪个文件,不跟 agent 说的文件名查;§0 验收文件类结论时独立确认文件路径非信 agent 报告;同§18教训⑤"agent关键结论§0验"的延伸--文件名/路径类结论也要独立验非信agent)
- **token浪费(8/9凯利阶段)**:①D修正返工(第一次 total_return 错->第二次 return_pct_max_holding 修,应指定口径前验算数值合理性一次到位,同§18教训⑦模式)②SendMessage 追加任务漏做致另开 commit 补做(应追加任务不靠 SendMessage 或 commit 前确认,同§11)③数据没上线 R2 致紧急派 agent 修(应上线链路确认完整,同§18"重跑数据产物列清单")④8/9 全天100+ subagent(虽多数 justified 并行不冲突,token 消耗大,非紧急可适当控制并发数)
- **经验(非过错,8/9凯利回测+R2阶段,记录防绕路)**:
  ① R2 purge_cache 分批避 CF Worker 超时 500(commit ea64df512):一次性发400+ keys 致 Worker CPU/wall time 超限->500,改分批每批30 keys(PURGE_BATCH_SIZE,20-50安全区间)+批间 sleep 0.5s 避 CF 限流,400+ keys->14批每批30 keys 远在 Worker 时限内。适用:所有 R2 purge cache 场景(数据更新后清 CF edge 缓存),不能一次性全量 purge
  ② 持仓 hold_days 改交易日口径修复虚高(commit 9cba7ca42):hold_days 用自然日含周末致虚高,改交易日口径+跟踪 price_date。适用:所有"持有天数"类计算(回测/统计),用交易日非自然日
  ③ check_data_integrity 加3校验 + 新建 check_r2_consistency.py(commit 1d5fe3ccc):数据完整性校验扩展(3新规则)+ R2 审计脚本(本地 vs R2 一致性)。适用:数据产物改动后跑 check_data_integrity(deploy 前置)+ 定期跑 check_r2_consistency 审计 R2
  ④ 凯利回测卡间比较水印设计(蓝★综合最佳+紫◆最稳定,全局16卡互比,commit ff56d9b71):跨卡片全局互比而非单卡内比较,用颜色+符号双标识。适用:UI 多卡比较场景,全局互比+双标识设计
- **2026-08-10 追加(降亏4toggle+模拟回测费率客调阶段,2条新过错+经验)**:
  18. §21算法公示gap复发(根因:模拟回测费率5参数实施agent 963ba3881 没更新 purpose-notes.js 的算法公示文案,reviewer FAIL catch(problem 4)。同会话降亏4toggle agent c818fddd3 正确更新了 purpose-notes.js(§21同步),但费率agent没--同会话两agent一做一不做,说明 fresh context agent 不主动读§21全文,主控 prompt 未对费率agent显式要求 grep 公示点。防重犯:算法/逻辑改动 agent prompt 必含显式动作"§21:grep purpose-notes.js + app.js/lab.js 所有算法说明文案,同步更新新规则,漏=验收不过";不只引用"见§21",要列出具体 grep 动作+文件名(purpose-notes.js);fresh context agent 不读 CLAUDE.md 全文,§21规范需在 prompt 转成具体可执行动作)
  19. 前端重算与后端算法对齐不完整(根因:费率5参数实施agent移植凯利费率模型框架到 trade_sim 前端 replay 重算,但3处没逐字段对齐后端算法:①open_positions.buy_close 存 br.buyPrice(含滑点买价)非原始close,后端 buy_price=close*(1+slippage) ②equity_curve 起点应用窗口起点(w_start)非 ledger[0].date,末点应加{date:signal_last_date,value:finalTotal} ③rounds.buy_close 应用 sold 的 buy_close 平均值非首个 sub_round 值。reviewer FAIL catch 3 bug,fix 0e024896f。防重犯:前端重算类实施(replay/recompute/前端复算后端逻辑),自验须逐字段对比后端 JSON 输出--取一个 signal 的 trade_sim/sigkelly JSON,前端 replay 后逐字段对比 open_positions/rounds/equity_curve/summary 各字段值,不只对比 summary 总计;prompt 要求"自验:取一个 signal JSON,前端 replay 后逐字段对比后端输出,列对比表,不一致项列差值")
  - 经验(非过错,记录防绕路):①GitHub Actions deploy 需约90s,curl 验上线 sleep 90 非15(首次 sleep 15 curl 到旧版 SW a91 非 a92)②Edit 工具匹配含 em dash(U+2014)或特殊字符的行会失败(3次匹配失败),改用 `sed -i '' 'Nc\替换内容'` 行号替换(memory appjs-em-dash-edit 已有 em dash 记录,补充 sed fallback)③reviewer FAIL 后§0验2点(positions.push+purpose-notes)合规(§0允许 FAIL 时亲自确认再回滚/修),非违规--主控本会话较守规:全程派 background agent + §0验1-2点 + cron 兜底,未亲干调研/实施 ④intraday 走 R2 不推 main 后,盘中 push 代码 main 不用避 intraday 时点(commit 4fb1a88e9,已落§14/§16):R2 迁移后 intraday_snapshot 走 R2 不推 main,盘中 push 代码 main 改不同文件 rebase 能合不撞车。适用:盘中需 push 前端代码 main 时避 update_all(17:50)即可,不用避 intraday 每10分钟时点 ⑤分时图 1min 轮询自愈机制(S1-S5+S9,commit d2a97108b):5阶段自愈--S1 fetch 加 AbortController 8s 超时防卡死 / S2 inflight 去重 Map+15s 兜底清理防毒化 / S3 6次失败不永久停改降频5min兜底重试(7x24自愈) / S4 overview 3min 轮询心跳唤起 intraday(定时器丢失/刷新超5min则重启) / S5 visibilitychange 切回前台清 in-flight。适用:所有定时轮询类前端机制,fetch 必加超时+inflight去重+失败降频不永久停+心跳唤起+切前台清inflight ⑥决策树/子群发现数据挖掘方法论(commit 7ada31c57):手写CART决策树+beam search子群+关联规则+多维交叉,超越人工2特征穷举(最高2.52)找到78个比值>3标志(单标志最高10.06,3月+周二+高价ETF 7/7年全亏)。适用:多特征组合优化场景(降亏标志/参数寻优),用决策树找高纯度叶节点=高比值标志,非人工穷举
  - token浪费:reviewer FAIL 5问题致 fix+复审 extra round。但这是 reviewer 系统设计正常工作(catch bugs before 上线,§15),非浪费。可优化:实施agent自验更充分(逐字段对比后端)可减少 reviewer catch 的问题数,但 reviewer 存在的意义就是 catch agent 自验漏的,不需追求 agent 自验100%
- **2026-08-10 追加(每日总结,backfill整改闭环+备用站404+开源化+KPI 阶段,4条新过错+经验)**:
  20. §0 验收 grep 字面量误判"整改未落地"(根因:backfill 整改 §0 第一轮 grep 字面量 "3600" 无结果→误判"整改点未落地"(3600 无/BACKFILL_SLOT 无/校验无),实际代码用常量 `_ALARM_RECOMPUTE=3600`(hkex_ccass_quarterly.py L47-48)+`_current_slot()` 读 env 槽通道,第二轮查常量名+赋值行才确认全落地,多耗一轮验证。防重犯:§0 验"值/配置/阈值"类结论时,grep 字面量无结果先怀疑"值被封装成常量/变量/配置/env",改 grep 常量名/变量名+查赋值行确认值,不直接下"未落地/未实现"结论;§0 是确认 agent 已报结论,第一轮无结果应换更精确 grep 方式而非否定)
  21. 备用站 reviewer 卡死 22min+无进度文件(根因:reviewer agent 没按 §16 prompt 要求每步 echo 进度文件,jsonl 停 23:33:48 22min 才被 cron 轮询发现;SendMessage 唤醒无效(33min)→判定死 TaskStop 重派,浪费 22-33min+重派 token。上次卡死根因=不写进度文件。防重犯:派任何 agent(尤其 reviewer)prompt 显式"每步 echo 进度文件,不写=无法监控按卡死重派";主控轮询 jsonl mtime+进度文件双重查,卡死先 SendMessage 唤醒(成本低),>1 轮仍无活动再判定死重派并强化进度文件要求)
  22. curl -sv 泄漏 GitHub token(根因:DB Release 上传 agent 诊断 POST /releases 404 时 curl -sv,把 Authorization header 的 token 值打印进 Bash 输出泄漏到会话,用户被迫撤销重发新 token。防重犯:curl 带认证头诊断禁止 -v/-i(会打印请求头);token 从 .env 读不硬编码不 echo;agent prompt 处理认证/密钥时显式"不 echo token、curl 不带 -v、token 从 .env 读";泄漏后立即建议用户 revoke)
  23. 主控 prompt 期望数值错误(根因:邮件任务 prompt 期望国君 15日同向=66.7,实际 accuracy 字段值 33.3(follow_ratio),代码读对字段输出 33.3 与页面一致,reviewer 判 §22 合规非代码 bug——主控 prompt 期望值写错。防重犯:任务 prompt 里的期望数值先核实来源(字段语义/页面实际),reviewer 按真实数据判合规不盲信任务描述期望值;reviewer 发现期望值与实际不符时先查任务描述是否笔误)
  - 经验(非过错,8/10 backfill整改+备用站404+开源化+邮件阶段,记录防绕路):
    ① 定时任务超时修复的"兜底槽按槽差异化"策略(backfill CCASS e2a41b058→reviewer FAIL P1/P2→整改 9be4e8f30→复验 PASS 全闭环):02:00 兜底槽强制重算+3600s 宽限(一石二鸟:解决 P1 慢网络停更回归+ P2 坏值冻结每日自纠正),16:35/21:00 常规槽闸门跳过+600s;槽通道=BACKFILL_SLOT env 注入(backfill_metrics.sh L23)+py `_current_slot()` 读 env 按槽差异化。适用:同一脚本多 launchd 槽位要差异化行为(兜底槽 vs 常规槽),用 env 通道注入槽标识,避免所有槽一刀切;reviewer FAIL→整改→复验 流程 catch 上线前回归(§15 正常)
    ② 数据挖掘盲区发现方法论(降亏第三轮):对比数据源全部字段 vs 历轮实际挖过的字段,v3/v4 跑 19 字段版无 market_state,部署版已有(N=66,591)从未挖过→market_state×全维度=盲区=优先挖掘目标。适用:任何多轮数据挖掘前先核对字段覆盖,未覆盖字段=最大机会(同 §18 教训 8/9/13 模式"验证数据产物层再下结论")
    ③ 新 toggle/标志评估用"叠加边际"非只 standalone 比值(降亏第三轮回测验证 docs/kelly-loss-round3-verify.md):A1/A2/A3 standalone 比值 4-10 但叠加现有 4 toggle 边际=0(被完全覆盖不推荐);A45 叠加边际 +107k 才推荐;现有 toggle 已砍 87.9% 亏损,新候选只在残余 12% 里再砍 ~1pp。适用:多 toggle/多标志叠加场景,新候选必须算叠加现有配置的边际贡献,不被 standalone 比值误导
    ④ 邮件期货风向字段语义修正(9ce765bef):accuracy.net_direction(静态净持仓方向)vs inst_ih_detail.details[-1](动态当日净加方向)两字段语义不同致"当日:空"矛盾,15日同向80%一致;改读动态字段+白话预警。适用:页面与邮件同数据源时先确认字段语义(静态 vs 动态/快照 vs 增量),矛盾先查字段选错非数据错
    ⑤ 开源化两仓库分工(用户纠偏定稿 0547f6733):数据开源主体(manifest+fetch_data+DB Release)放静态数据仓库 trade-data-signal-staticdata(CC BY 4.0),开发库 trade-data-signal 只代码 MIT+README「数据开源」章节引导,双向互链;DB 分发走 GitHub Release(GITHUB_TOKEN env 方案,release_db.sh 支持,gh CLI 未装改 token),manifest uploaded=true+URL 替换+下载 206 可达验证。适用:开源项目数据/代码分仓库,数据主体放数据仓库避免开发库肥大+双份
    ⑥ check_data_integrity 加"定时任务该有的数据在不在"类校验(backfill 季度闸门 check_a_fund_north_quarterly 最新季度行存在,缺失/滞后即 FAIL):C级数据任务防静默缺失。适用:任何数据产物改动新增对应完整性校验点防静默
  - token浪费(8/10):①§0 第一轮 grep 字面量误判→第二轮才确认(字面量 vs 常量,多一轮验证,同过错 20)②备用站 reviewer 卡死 22-33min+重派(不写进度文件致卡死难发现,同过错 21)③通知 reviewer API 失败重派(a959b2490de2cceb4 Prompt too long 全文读大文件终止,重派约束 git diff+定点 grep 不全文读大文件)。backfill FAIL→整改→复验 是 reviewer 系统正常 catch 非浪费(§15)
- **2026-08-11 用户新规范(README 维护:功能完成必补 README,两条)**:①做功能**若参考了文件或用了开源项目**,完成后必须在 README「🎓 参考与致敬」段扩充描述作用 + 附致敬(含跳转链接)。触发:任何实施任务(agent 或主控)引用了外部开源项目/库/文件/平台能力(如 a-stock-data/easytrader/thsautoorder/tradingagents/DeepSeek/pysubgroup/mootdx/baostock/akshare/R2/CF Workers 等)。②站点**有重大功能添加/发布/更新**,完成后必须在 README 主体段(功能亮点/系统架构/技术栈/在线体验)完善补充描述(不只参考段)。动作:功能完成后检查 README 对应段落,缺则补"该功能做了什么/用了什么/参考了什么→作用→来源链接",有则更新对齐实际用法。验收口径:实施 agent 自验含「grep README 确认本功能描述+致敬已补」,reviewer 查 README 同步,漏=验收不过(同 §21 算法公示同步模式)。README 现状:功能亮点(信号灯+降亏toggle/AI速递/自动交易等)+参考与致敬(数据挖掘方法论/多 Agent 协作 traderagent/AI 预测 DeepSeek/自动交易 easytrader→thsautoorder/公开数据源致谢 a-stock-data 等)各段已建,后续新功能按段归属补
- **2026-08-11 用户新规范(修 bug 三铁律:修完整+自测+排查同类,2026-08-11 备站多模块异常触发)**:用户原话"每一个修复bug的核心要修好修完整以及自测完成,不是只为图快和我说啥你修啥,不调研是否还有其他同类错误 。要落档规范不要再犯"。触发场景:备站(sss.sugas.site)多个功能模块同时异常(公募基金 tab 暂无数据/指数表现加载失败刷新无用/凯利回测 signal_kelly_backtest.json Failed to fetch/信号实验配对排行加载失败/诸如此类还有很多),若逐个打地鼠只修用户报的那几个=违反本规范。三铁律:①**修完整**:修一个 bug 前先全面调研同类错误面(用户报 1 个,先 grep 前端全量数据依赖+curl 多处状态码列全同类异常,不只听用户报的),根因修复不只表面症状 ②**自测完成**:修复后必须自己全面测试(用户报的模块+同根因其他模块+跨展示位 §22 一致性),自验列测试清单,不"草率说修好了" ③**排查同类**:修完自查"是否还有其他同类错误"(同文件类型/同 fallback 链路/同上传通道的其他文件,如本次 signal_kelly 未传 R2,要查所有新数据类别是否都传 R2)。验收口径:修 bug agent 自验须含「同类错误面清单(与用户报的同根因的所有模块)+逐项自测结果」,reviewer 查同类覆盖,漏=验收不过。防重犯:①修 bug 前必派调研/先列异常面清单,不直接上手修用户报的那几个 ②修复后自测清单要全覆盖(不只用户报的)③根因层面修(如备站数据通道/R2 上传链路/fallback 逻辑),不逐文件打补丁

## 19. 自我成长机制(2026-08-08 定,每天总结+定期review防重犯)
用户定:慢慢积累迭代完美,每天总结过错+token浪费+解决方案落档防重犯。memory文件持久但内容会过时需定期review。

### 机制(用户选:会话级+每日cron兜底+每周memory review)
1. **会话级总结**(主流程,会话结束前/大阶段/上线后必做):派 agent 总结本次①过错(违规§2亲干/§4自问自答/§11不设cron/§15不派reviewer/§14不查定时 + 误判 + 返工)②token浪费(亲干调研/重复grep/长盘算/无效agent/重复确认/§17高峰派agent)③解决方案(防重犯条款,具体可执行如"派agent后立即设cron")④经验类归纳(非过错的好经验/绕路经验/方法论/架构洞察,含场景+怎么用),转 §18 经验条目或 §20 docs/agent-quickstart.md 快速上手 step。落档 §18 追加 + memory 更新(feedback类 Why+How to apply)
2. **每日cron兜底**(durable,23:30 安全窗口):会话开时派agent归纳当天§18/memory+会话日志,更新§18防重犯条款+经验条目(不只归纳过错,也归纳非过错经验/方法论/架构洞察)。会话关不触发下次补。⚠️cron 7天过期需续设
3. **memory周review**(每周日23:00+):派agent review memory全部文件:删过时(文件/字段/规范变化,验证后删)+合并重复+更新MEMORY.md索引
4. **总结复核 agent**(独立 fresh context,总结完成后派,会话级/每日/每周总结都派,2026-08-08 用户定):git log 可查总结前后差异,复核 agent 读总结前原文(git show 旧版 CLAUDE.md §18 / memory 旧版)+ 总结后新版,逐条检查:①核心点保留(§18 核心条款/根因/场景未删,删过时事实不删教训;经验条目也保留非只过错)②中心思想未跑偏(§18="不重犯同类+经验积累成长",防重犯条款具体可执行非泛泛)③非为总结而总结(归纳非删减非凑数,有实质提炼非形式总结)④非为省token省token(不该删的不删,token 节省是归纳副产品非目标)⑤经验类已归纳(非过错的好经验/方法论/架构洞察有落档,不只归纳过错)。发现问题->回退(git revert)/修正重做。这是"总结核心点保留"原则的执行保障:光有原则不够,独立复核兜底。git log 让复核可验(对比总结前后差异)

### memory有效期
- 文件持久(磁盘不过期),内容会过时(项目变化后没更新)。加载:MEMORY.md索引每次会话全加载(一行一条),具体文件按recall相关性加载(非全量)。备份:每天3:17 claude-self-daily-backup(保留30天)。重要结论落NOTES/TASKS git(§7)不只memory

### 执行
- 会话级总结是主控职责,会话结束前必做,派agent不亲干
- 防重犯条款具体可执行(如"X场景做Y"),不泛泛
- §18即时记+§19归纳解决方案配合
- **总结核心点保留(防跑偏,2026-08-08 用户补)**:总结是归纳不是删减,多次总结后不能忘中心思想跑偏(类比 compact 总结后忘东西)。①防重犯条款保持具体可执行(如"派agent后立即设cron"),不简化成泛泛("注意设cron") ②过错记录含根因(为什么错),不只留"错了" ③memory review 删过时事实(文件/字段/规范变了),不删教训(教训永远有效) ④归纳只合并同类+提炼解决方案,不删原有核心条款/场景/根因 ⑤经验条目也保留(非过错的好经验/方法论/架构洞察,含场景+怎么用,不只记过错) ⑥定期校准:§18 中心思想="不重犯同类+经验积累成长",归纳不能变流水账丢目标。总结 agent prompt 须明确"保留原有核心点+经验条目,只归纳不删减"
- **总结自查 + 复核两层(2026-08-08 用户补)**:总结产出后必派独立复核 agent(fresh context)按机制第4条检查,复核 PASS 才算总结完成(会话级/每日/每周总结都派)。git log 查总结前后差异(总结前原文 git show 旧版取)。不为总结而总结,不为省token省token,中心思想不能偏,核心点不能丢。定期总结自查后还要有人复核--总结 agent 自己查(自查)+ 复核 agent 独立查(复核)两层兜底

## 20. 快速上手引导持续完善机制(2026-08-08 定,绕弯路后完善引导)
快速上手引导是**持续性工作**,非一次性落档。绕弯路解决问题后,完善 `docs/agent-quickstart.md`(主速查,另一 agent 持续建;数据上线类见 `docs/data-deploy-quickstart.md`)对应部分,避免下次子 agent fresh context 重复绕弯路(开发效率 + 查询 token 双损)。

- **核心一句话**:绕弯路解决的问题,下次子 agent 不应重复--把它写进 `docs/agent-quickstart.md` 对应任务类型的"这类任务怎么直接做对"step + 常见坑速查,子 agent 接任务读速查直接做对
- **触发条件(识别"这次绕弯路")**:
  ① 子 agent fresh context 反复调研同一已知架构/流程(R2 数据上线/CF Workers 路由/build_min+bump_asset_version+bump sw 三步/launchd 定时清单/export cwd trade-data 写 JSON 路径同步 等)
  ② 试错返工:方案未充分调研就实施致返工(§18 教训⑦ hoverpop/移动端)
  ③ 误解口径/方向偏差:调研下结论前未验证(§18 教训⑧⑨⑪⑫,如"无/0/不可改善"过早断定、调研跳到生成层不对准 UI 位置)
  ④ 子 agent 重新发现已知的坑:§18 已记录但 fresh context 不知道(子 agent 不读 §18 全文,速查文档是它真正会读的入口)
  ⑤ 经验类(非过错的好经验/方法论/架构洞察):§18 经验条目里的可操作经验(如 R2 purge 分批/自愈机制设计/决策树挖掘方法论),转成子 agent 可直接执行的 step
- **动作**:
  ① 识别:主控或子 agent 识别"这次绕弯路解决的问题,下次子 agent 不应重复"
  ② 完善 `docs/agent-quickstart.md` 对应任务类型部分:记录"这类任务怎么直接做对"的标准 step(含验收口径)+ 常见坑速查(链接 §18 对应教训条目,不重述根因)
  ③ commit 进 git(§7 落档写保障;只放 memory 不算数)
- **和 §18/§19 配合(三者互补,不重复)**:
  - **§18 记过错+经验**(反向防重犯+正向经验积累):每次犯错即时追加含根因+防重犯条款;非过错的好经验/方法论/架构洞察也记于此("经验(非过错)"条目,含场景+怎么用)。面向主控读
  - **§19 每天总结**(横向归纳):会话级/每日/每周归纳过错+token浪费+解决方案+经验类,提炼防重犯条款+经验条目,面向主控读
  - **§20 完善引导**(正向持续):把"怎么做对"沉淀进 `docs/agent-quickstart.md`,面向**子 agent fresh context 读**--§18/§19 主控读得到但子 agent fresh context 不读全文,§20 是子 agent 真正会读的速查入口。经验类(§18 经验条目)也转成 step
  - 一句话:**§18 防错+记经验 / §19 总结过错+经验 / §20 引导对**,§20 把 §18/§19 的教训+经验转成子 agent 可直接执行的 step
- **持续性**:每次绕弯路都完善,`docs/agent-quickstart.md` 越来越全,子 agent 直接用不绕弯路;§19 会话级总结时必查本次绕弯路,有则完善 `docs/agent-quickstart.md`(总结 agent 的产出之一)
- **派 agent 时引用**(§16 agent prompt 规范延伸):主控派子 agent prompt 引用“见 docs/agent-quickstart.md <对应任务类型>”,子 agent fresh context 读速查快速上手,不重复调研已知流程;若该任务类型速查尚未写,子 agent 完成后补写(把本次“怎么做对”沉淀,触发 §20 动作②)

## 21. 算法改动同步公示文案(2026-08-08 定,防算法公示与实施不同步)
- **核心一句话:改算法逻辑必须同步改前端算法公示文案**。算法公示(前端展示的算法说明/公式/规则解释)是用户理解算法的依据,算法改了公示不改=用户看老规则误导,且修复成本高(发现成本+返工)
- **触发**:任何改 track_score/评分/权重/分段函数/匹配规则等算法逻辑的改动(build_board_etf_map.py/queries.py/simulate_trade.py 等后端算法),必须 grep 前端算法公示文案同步更新
- **算法公示文案位置**:app.js/lab.js 中 track_score/跟踪分/算法/TE/R²/IR/权重/百分位/match_method 等相关说明文字(弹窗/tooltip/策略实验室公式展示)。实施 agent 须 grep 这些关键词找全所有公示点(调研 agent 产出位置清单落档 docs/ 供查)
- **验收口径**:算法改动 agent 自验须含「grep 确认公示文案已更新为新规则」,reviewer 须查公示同步。算法改了公示没改=验收不通过
- **历史教训**:之前出现过算法公示老版本和实施规则不同步(算法改了公示没改,用户看老规则),修复需重新定位所有公示点+更新+重新上线,发现成本+返工成本高。本规范防丢失忘记,下次算法改动必读

## 22. 数据一致性铁律(2026-08-09 定,用户视角多展示位必须一致)
- **核心一句话:用户在N个展示位看到的数据必须统一**。不管内部层级(overview.json/board_etf_map.json/concepts.json),用户看到N处必须一致。只有一致才是最好的解释,文件不一致或缓存不一致都会产生误解
- **用户原则(2026-08-09 用户原话)**:"不管层级 我的理解是。作为用户 3个展示位看到的数据一定要统一。比如不能存在文件不一致or 缓存不一致。都会产生误解。只有一致才是最好的解释。你的所有策略都只决定更新频率or排序。但是一旦更新肯定是3处一起同步"
- **所有策略只决定何时更新or如何排序**:stable_top1滞回/排序/更新频率等策略只决定更新时机或排序,**一旦更新必须N文件+N缓存(R2/CF)同步**。不能文件不一致(一个新版一个旧版)or 缓存不一致(R2新CF旧)
- **机制**:export/deploy 时校验N文件版本一致(关键字段如量子top1/stable_top1),不一致阻断或告警。算法改动重跑数据产物时,列所有依赖该数据产物清单逐个确认重跑+同步static-site+R2三步(§18 已有教训)
- **与 §15/§18 互参**:§15 是"改坏老功能"回归复查,本条是"用户视角多展示位一致性"铁律,§18 记具体犯错(2026-08-09 量子科技3展示位不一致)。三者互补:§15 防改坏、§22 防不一致、§18 记教训

## 验收铁律
逐字验证关键结论(grep/SQL/读代码),不信 agent 报告。报“完成”不等于真完成。
