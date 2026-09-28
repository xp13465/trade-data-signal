# CLAUDE.md 历史章节归档(§17/§10/§12/§13,2026-08-12;§12/§13 于 2026-09-28 从框架仓 claude-work-mode 还原补充)

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


## §13 模型能力约束(2026-09-28 从框架仓 claude-work-mode 还原,非本仓下沉前原文逐字留存)

> 本节为 2026-09-28 从框架仓 claude-work-mode/CLAUDE.md §13 还原,**非本仓下沉前原文逐字留存**;核心约束一致,细节可能与原版有出入。CLAUDE.md 正文现留 1 行摘要(仅文本不支持图片/禁止图片操作/撞 400/视觉验证用文字+ASCII 示意图)。

---

## 13. 模型能力约束(开工先确认当前模型能力)

- 开工前确认当前模型(deepseek-v4-pro / flash,文本 only)的能力边界:当前模型**只支持文本输入,不支持图片**,Read 图片/截图/视觉对比会触发 API Error 400 终止 agent
- 派子 agent 时**禁止图片操作**(截图对比/UI 视觉看图/Read 图片验证效果)。需视觉验证的用文字描述+ASCII 示意图,或让用户自己看
- 子 agent 撞 400 "Model only support text input" = 尝试了图片输入。若其调研已基本完成,读进度文件 + 主控补完剩余即可,无需重派从头
- 任何能力受限都同理:撞能力边界别硬试,换文字/数据层验证


## §12 superpowers 融合规则(2026-09-28 从框架仓 claude-work-mode 还原,非本仓下沉前原文逐字留存)

> 本节为 2026-09-28 从框架仓 claude-work-mode/CLAUDE.md 对应节(其编号 §17,内容即本仓 §12)还原,**非本仓下沉前原文逐字留存**;核心约束一致,细节可能与原版有出入。CLAUDE.md 正文现留 1 行摘要(运维/采集/上线/数据任务跳过 brainstorming HARD-GATE + continuous-execution;大型功能可按需用全套)。

---

## 12. superpowers 融合规则(装于 2026-07-15,superpowers v6.1.1,14 个 skill + 子 skill 共 63 个 SKILL.md)

本仓环境已装 superpowers 等 skill 库(纯 skill 集,无 slash command,SessionStart hook 每次开会话强制注入全文,默认"1% 可能相关就主动调 skill"):

- **优先级**:项目 CLAUDE.md 硬规范 > skill 库。skill 库默认"只有用户明示跳过才不走",故运维/采集/上线/数据任务明示跳过其 ①brainstorming 的 HARD-GATE(写码前必经设计门)②executing-plans/subagent-driven-development 的 continuous-execution(连轴转不停问用户)
- **运维/采集/上线/数据任务保留现有监工 loop**(§2/§11:派 background 子 agent->立即返回待命->轮询恢复->不问 yes/no 用户随时插话)。skill 库假设子 agent 同步返回、无恢复机制,比现有弱
- **大型功能开发可按需用全套**:brainstorming->writing-plans(拆 2-5 分钟 bite-sized task)->subagent-driven-development(implementer+reviewer+fixer 循环)->TDD->finishing-a-development-branch
- **可借鉴技艺补强监工 loop**:①独立 task-reviewer 子 agent 两阶段验收(spec 合规+代码质量)②大 diff 走文件交接不进主控上下文 ③progress ledger 落 git 跨 compaction 可恢复,比 `/tmp/agent-progress-*` 耐久(长任务用)④using-git-worktrees 隔离并行改同区域
