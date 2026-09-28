# CLAUDE.md 历史章节归档(§17/§10/§12/§13,2026-08-12;§12/§13 于 2026-09-28 以 git 历史 commit d2fb77c0e 逐字原文补档)

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


## §13 模型能力约束(逐字原文,源 commit `d2fb77c0e`(2026-07-16 §13 计入时的版本))

> 本节为 2026-09-28 从本仓 git 历史 commit `d2fb77c0e` 的 CLAUDE.md 逐字还原,非框架仓还原版;正文与当时版本逐字一致,仅节末补一行现况注。CLAUDE.md 正文现留 1 行摘要(仅文本不支持图片/禁止图片操作/撞 400/视觉验证用文字+ASCII 示意图)。

---

## 13. 模型能力约束(2026-07-16 计入)
- 当前模型(glm-5.2)**只支持文本输入,不支持图片**。Read 图片/截图/视觉对比会触发 API Error 400 "Model only support text input",终止 agent
- 派子 agent 时**禁止图片操作**(截图对比/UI 视觉看图/Read 图片验证效果)。需视觉验证的用文字描述+ASCII 示意图,或让用户自己看
- 子 agent 撞 400 "Model only support text input" = 尝试了图片输入。若其调研已基本完成,读进度文件 + 主控补完剩余即可,无需重派从头
- **2026-07-16 教训**:P2-4 og.png 压缩 agent 在"开始写报告"时疑似 Read og.png 验证压缩效果,撞 400 终止。但 P0-1 压缩调研已完成(坐实不可行),og.png 主控手动 magick 256色压缩补完(67KB->36KB),无损失

> (注:`glm-5.2` 为 2026-07-16 时值;当前模型 deepseek-v4-pro / flash,约束不变)


## §12 superpowers 融合规则(逐字原文,源 commit `d2fb77c0e`(2026-07-15 装 v6.1.1))

> 本节为 2026-09-28 从本仓 git 历史 commit `d2fb77c0e` 的 CLAUDE.md 逐字还原(§12),非框架仓还原版;正文与当时版本逐字一致。CLAUDE.md 正文现留 1 行摘要(运维/采集/上线/数据任务跳过 brainstorming HARD-GATE + continuous-execution;大型功能可按需用全套)。

---

## 12. superpowers 融合规则(2026-07-15 装 v6.1.1)
- superpowers 是纯 skill 库(14个,无 slash command),SessionStart hook 每次开会话强制注入 using-superpowers 全文(~800 token),且默认"1% 可能相关就主动调 skill"
- **优先级**:本项目 CLAUDE.md 硬规范 > superpowers skill。using-superpowers 声明"只有用户明示跳过才不走 skill",故下条明示跳过
- **运维/采集/上线/数据任务明示跳过** superpowers 的:①brainstorming 的 HARD-GATE(写码前必经设计门)②executing-plans/subagent-driven-development 的 continuous-execution(连轴转不停问用户)。这类任务**保留现有监工 loop**(§2§11:派 background 子agent→立即返回待命→CronCreate 轮询 jsonl mtime→卡死/429 优先 SendMessage resume→不问 yes/no 用户随时插话)
- **background 异步 + 卡死/429 轮询恢复机制保留不替换**:superpowers 假设子agent同步返回、无恢复机制,比现有弱
- **大型功能开发(策略实验室级)可按需用全套**:brainstorming→writing-plans(拆2-5分钟bite-sized task)→subagent-driven-development(implementer+reviewer+fixer循环)→TDD→finishing-a-development-branch
- **可借鉴技艺补强监工 loop**:①独立 task-reviewer 子agent 两阶段验收(spec合规+代码质量),作"逐字验证"之外第二双眼 ②大 diff 走文件交接(`.superpowers/sdd/review-*.diff`)不进主控上下文 ③progress ledger 落 `.superpowers/sdd/progress.md` 进 git 跨 compaction 可恢复,比 `/tmp/agent-progress-*` 耐久(长任务用)④using-git-worktrees 隔离并行改同区域

