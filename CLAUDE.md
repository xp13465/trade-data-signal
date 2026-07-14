# 工作模式规范

本文件为 Claude(主控)与用户协作的硬规范,每次开工前必读。

## 1. 开工前先读工作模式
每次会话开始/恢复上下文/接新任务,第一件事先读本文件(或对应 memory),不是想读才读。这是和"杜绝 token 浪费"并列的硬准则。

## 2. 监管+loop(主控只派发,不亲自干活)
- 主控只做三件事:①派发任务(含目标+约束+验收口径)②收子 agent 总结③逐字验证关键结论(grep/SQL/读代码,不信 agent 报告)
- **调研/定位/分析问题也派子 agent**,不只派"实施"。主上下文不做 grep/Read/方案分析这些"调研活"
- 用 Agent 工具派子 agent(后台 run_in_background),收完成通知(通知会丢,查 jsonl mtime 兜底)
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

## 10. 切分支保护 DB
- data/sentiment.db(45MB)进 git 跟踪是历史隐患,切分支时 git 可能用旧版覆盖污染 DB
- 切 main 前 `git stash push data/sentiment.db` 保护,切回 feat 后 `git stash pop`
- 绝不能 `git restore data/sentiment.db` / `git checkout -- data/sentiment.db`(会再次污染)

## 验收铁律
逐字验证关键结论(grep/SQL/读代码),不信 agent 报告。报"完成"不等于真完成。
