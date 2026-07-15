# 工作模式规范

本文件为 Claude(主控)与用户协作的硬规范,每次开工前必读。

## 1. 开工前先读工作模式
每次会话开始/恢复上下文/接新任务,第一件事先读本文件(或对应 memory),不是想读才读。这是和"杜绝 token 浪费"并列的硬准则。

## 2. 监管+loop(主控只派发,不亲自干活)
- 主控只做三件事:①派发任务(含目标+约束+验收口径)②收子 agent 总结③逐字验证关键结论(grep/SQL/读代码,不信 agent 报告)
- **调研/定位/分析问题也派子 agent**,不只派"实施"。主上下文不做 grep/Read/方案分析这些"调研活"
- 用 Agent 工具派子 agent(**必须 `run_in_background: true`**),收完成通知(通知会丢,查 jsonl mtime 兜底)
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
- 技术细节(库表设计/接口选/参数定/定时器选)自己调研给默认方案,不抛回用户
- 只在真正方向性分叉(用现成指数 vs 自算综合分,语义不同)才给选项
- 指标清单等,直接 propose 一套默认集让用户 veto/增删

## 6. 始终用中文回复

## 7. memory 只是暂存
- 重要结论/决策/方案必须写项目文件(NOTES.md/TASKS.md/CLAUDE.md)commit 进 git
- memory 会丢,只作临时暂存指针
- 不要把规范/决策只放 memory

## 8. 改完必须推送
- 每次改完 commit + push feat + merge main + push main(不推=白干,别人无法验收)
- 不 add data/ 下任何文件(sentiment.db/etf_national_team.db/signal_stats.json/JSON 采集产物保持本地 M)
- commit message 末尾加 `Co-Authored-By: Claude <noreply@anthropic.com>`

## 9. 双版同步铁律
- web/app.js(动态版 /api/) 和 static-site/app.js(静态版 ./data/) 必须逐字相同(除数据源 URL)
- 改 CSS/JS 后跑 `scripts/build_min.py`(terser minify)+ `scripts/bump_asset_version.py`(md5 前 8 位破缓存)
- 双版改完 diff 验证 IDENTICAL

## 10. 切分支保护 DB(2026-07-14 已根治,作历史教训留存)
- 历史隐患:data/sentiment.db(80MB)+ etf_national_team.db 曾进 git 跟踪,切分支时 git 用旧版覆盖污染 DB,致 2026-07-14 事故(收盘快照丢失)
- **2026-07-14 已根治(commit 8e3f5fa)**:两 DB 移出 git(git rm --cached + .gitignore),现 untracked。线上全是 static-site/data/*.json 静态产物,不依赖 DB
- 切分支现在不会再碰 DB(untracked 文件 git 不跟踪)
- **教训(派 agent 同步分支时注意)**:DB 仍 tracked 时,checkout 切到另一分支会触发 git 用该分支版本覆盖本地 DB。正确同步 main 的方式 = 避免本地 checkout,用 `git fetch origin && git push origin feat/xxx:main` 或 reset,而非 `git checkout main && merge --ff-only`(中间态 checkout 仍 track DB 的分支会复现事故)
- 绝不能 `git restore data/sentiment.db` / `git checkout -- data/sentiment.db`(若不慎重新 add)

## 11. 子agent卡死/429处理(主动轮询+唤醒+重派读遗留)
- 主动轮询:派agent后用CronCreate设recurring每3分钟查jsonl mtime,不干等通知(通知会丢;agent卡死时通知永远不来,因agent没正常退出)
- 派agent的prompt要求写进度文件:**每完成一步立即echo**(每个grep/Edit都回写,不是每大步骤;2026-07-15 a194f曾只写"开始"641秒不回写致盲区),echo到 `/tmp/agent-progress-<名>.md`,主控Bash查(轻量不overflow),不依赖jsonl(大)/通知(会丢)/返回(可能429空)任一渠道
- **卡死**(jsonl mtime>480秒没动):先SendMessage试唤醒原会话(成本低,agent可能卡在长工具如grep/curl没退出,SendMessage排队等它下轮处理),下次轮询(3分钟)仍卡死=进程已死,重派新会话
- **429配额失败**:agent came to rest(退出运行)但task-id保留,配额恢复后**优先SendMessage resume原会话**(保留上下文比重派从头高效);resume不响应/状态乱才重派新会话。**2026-07-15教训(底线:不重复犯错)**:曾误判"429原会话已终止无法resume只能重派"(a194f 429后重派afe9从头跑,浪费a194f已查的32 tool_use上下文),实际task-notification note明说"can resume",429和卡死都优先resume--**配额恢复后第一动作是SendMessage resume原会话,不是重派**
- **came to rest**(agent完成一阶段停了等指令,非卡死非429):可随时SendMessage推进,不严格等480秒(2026-07-15 a5c6改名反复came to rest,SendMessage推进3次才完成;阈值可降到240秒)
- 重派新会话:让新agent读原agent遗留接着做(`/tmp/agent-progress-*.md`进度文件 + 工作区半成品,如数据时效a2ce接a06704b半成品),避免从头返工

## 12. superpowers 融合规则(2026-07-15 装 v6.1.1)
- superpowers 是纯 skill 库(14个,无 slash command),SessionStart hook 每次开会话强制注入 using-superpowers 全文(~800 token),且默认"1% 可能相关就主动调 skill"
- **优先级**:本项目 CLAUDE.md 硬规范 > superpowers skill。using-superpowers 声明"只有用户明示跳过才不走 skill",故下条明示跳过
- **运维/采集/上线/数据任务明示跳过** superpowers 的:①brainstorming 的 HARD-GATE(写码前必经设计门)②executing-plans/subagent-driven-development 的 continuous-execution(连轴转不停问用户)。这类任务**保留现有监工 loop**(§2§11:派 background 子agent→立即返回待命→CronCreate 轮询 jsonl mtime→卡死/429 优先 SendMessage resume→不问 yes/no 用户随时插话)
- **background 异步 + 卡死/429 轮询恢复机制保留不替换**:superpowers 假设子agent同步返回、无恢复机制,比现有弱
- **大型功能开发(策略实验室级)可按需用全套**:brainstorming→writing-plans(拆2-5分钟bite-sized task)→subagent-driven-development(implementer+reviewer+fixer循环)→TDD→finishing-a-development-branch
- **可借鉴技艺补强监工 loop**:①独立 task-reviewer 子agent 两阶段验收(spec合规+代码质量),作"逐字验证"之外第二双眼 ②大 diff 走文件交接(`.superpowers/sdd/review-*.diff`)不进主控上下文 ③progress ledger 落 `.superpowers/sdd/progress.md` 进 git 跨 compaction 可恢复,比 `/tmp/agent-progress-*` 耐久(长任务用)④using-git-worktrees 隔离并行改同区域

## 验收铁律
逐字验证关键结论(grep/SQL/读代码),不信 agent 报告。报"完成"不等于真完成。
