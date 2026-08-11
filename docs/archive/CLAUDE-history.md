# CLAUDE.md 历史章节归档(§17/§10,2026-08-12)

> 本节收纳 CLAUDE.md 中已作废/已根治的历史章节原文,由 CLAUDE.md 整理提炼(去重12+提炼8+归档3大件)归档,防重犯条款精华保留在 CLAUDE.md 正文。
> 归档日期:2026-08-12

## §17 火山方舟高峰时段省token(已作废,原文 L198-203)

> 2026-08-09 用户定:18点高峰期限制已取消,派agent不再避14-18随时可派,以下条文作废留存备查。CLAUDE.md 正文现留 1 行索引。

---

## 17. 火山方舟高峰时段省token(2026-08-06 计入) ⚠️[2026-08-09 用户定]18点高峰期限制已取消,派agent不再避14-18随时可派,以下条文作废留存备查
- **火山方舟(模型提供方)14:00-18:00 高峰期高倍率结算**,开发派 agent(token 消耗大)尽量避开此时段,放 18:00 后或上午
- **简单对话/验收/轻量操作(消耗小)无所谓**,只针对派实施/调研 agent(消耗大)规避
- **14-18 必须干活时**:优先轻量验收/对话,重实施 agent 推迟到 18:00 后;用户主动派活除外(响应优先)
- 和 §14 并列:§14 避开定时任务时点(生产安全 P0),§17 避开高峰倍率(省 token);两者时点重叠时(如 15:35 既撞定时又高峰)双重规避
- **派 agent 前看时间**:14-18 期间如非紧急,向用户说明"高峰倍率,建议 18 后跑"等用户定;用户确认立即跑不卡


## §10 切分支保护 DB(已根治,原文 L90-95)

> 2026-07-14 已根治,作历史教训留存。CLAUDE.md 正文现保留防重犯精华 2 行。

---

## 10. 切分支保护 DB(2026-07-14 已根治,作历史教训留存)
- 历史隐患:data/sentiment.db(80MB)+ etf_national_team.db 曾进 git 跟踪,切分支时 git 用旧版覆盖污染 DB,致 2026-07-14 事故(收盘快照丢失)
- **2026-07-14 已根治(commit 8e3f5fa)**:两 DB 移出 git(git rm --cached + .gitignore),现 untracked。线上全是 static-site/data/*.json 静态产物,不依赖 DB
- 切分支现在不会再碰 DB(untracked 文件 git 不跟踪)
- **教训(派 agent 同步分支时注意)**:DB 仍 tracked 时,checkout 切到另一分支会触发 git 用该分支版本覆盖本地 DB。正确同步 main 的方式 = 避免本地 checkout,用 `git fetch origin && git push origin feat/xxx:main` 或 reset,而非 `git checkout main && merge --ff-only`(中间态 checkout 仍 track DB 的分支会复现事故)
- 绝不能 `git restore data/sentiment.db` / `git checkout -- data/sentiment.db`(若不慎重新 add)
