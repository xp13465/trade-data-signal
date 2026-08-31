# ZCode 临时代班秘书 · 记忆文件(索引 + 当前交接快照)

> 本文件是临时工秘书角色的 MEMORY 索引(仿 Claude Code memory 格式:一行一条,触发词前缀)。
> 每轮收尾同步写回 Claude Code 的 memory(`zcode-standin-handoff.md` + 索引行,见 SKILL.md §2 协议)。

## 当前交接快照(2026-08-31,每轮收尾更新)

- **角色状态 v2.1(2026-08-31 Claude Code 审核有条件通过,4 缺口已全部补进 SKILL.md)**:①§4.1 在跑 agent 接管协议(Claude 离线+有在跑 agent→按进度文件+工作区 diff 接管验收不等通知;429 死上报不硬重试)②§3 CronDelete 边界(绝不删 Claude 既有 job)③§2 写回第 3 条收紧(既有条目只做状态性追加,拿不准只写 handoff)④§2 第 4 条 handoff 必带验收入口(commit hash/进度文件/线上验证命令)。Claude Code 实测确认:memory 写回 138 行=137 条没动+1 追加,零问询恢复已验证可行。
- **sim implementer 确认在跑**(Claude Code 亲证 13:5x 派的 sim implementer 就是我在 jsonl 观察到的活动)——我继续不动 sim 相关任何文件,等其闭环或 Claude 交接清单
- **待用户拍板**:
  - [ ] 交接时序二选一(Claude Code 给的拍板项):①等 sim 闭环后干净交接 ②Claude 现在落在跑 agent 接管清单进 TASKS+handoff 再休息
  - [ ] 角色文件 commit 方案:Claude 建议定稿后单独 commit 不混 sim 分支 → 我的建议=git worktree 从 main 建独立分支(如 feat/zcode-standin-charter)commit+push,不碰当前 sim 工作区;等用户点头执行
- **开工必读完成度**:根 CLAUDE.md ✅ / main-governance.md ✅ / MEMORY.md 索引(137条)✅ / TASKS.md ✅ / codex 两份 ✅ / claude-work-mode README ✅;role skill 四份未读(按设计派单时子 agent 自读)
- **⚠️ 上轮 Claude Code 会话疑似仍在运行**:主会话 jsonl `1ddfbd20`(1ddfbd20-5b96-425c-85f8-07b8d8625b0f.jsonl)13:55:15 仍有写入,其子 agent a5cd04dc 13:56:46 仍在动——**代班开工前必须确认其收工,在跑=不动任何东西(SKILL.md §4)**
- **项目实况(13:36 TASKS 终态核实)**:
  - audit2 保守版瘦身**已全链闭环上线**:feat/claude-md-audit2-slim→main 92e364b0f 已 push,reviewer 六项 PASS,完成登记 done-list;我此前读到的 12:2x 交接快照已过时
  - 巡检 cron 已全停(891b3592/39510b35/16d344a4/e256016e/a256ebf0/2e751841)
  - thinking-proxy 已停用(用户拍板)
  - sim-etf-pin-align **暂停待用户指示**:半成品在 app.js/style.css 工作区 M 未 commit 未丢(当前分支 feat/sim-etf-pin-align),差 STEP 3 字段核对+1:1 对齐+108/110 统一;额度已恢复,用户发话即重派 fresh implementer
- **codex 外审通道现状(我第一轮核实的,待用户指令)**:
  - 11 个 ref status=pending 但实际全部已完成(报告在 /tmp/codex-reports/,codex-inbox 全 .done);verdict:8 PASS / rev-20260827-002 FAIL / rev-20260830-001 BLOCKED(后经修复 2ed475703 内审补位,v1.1.11 已发) / rev-20260830-002 FAIL
  - claude-inbox 回传信号全 .failed:watcher「stale report mtime<job_started」机检误拦真实报告,3 次重试 gave up——**回传闭环断点未修**
- **我的待办**:
  - [ ] 验证飞书 hook 在 ZCode 会话是否触发(收工后问用户有无收到通知)
  - [ ] `.agents/zcode-standin/` 两份文件未 commit(在 sim 半成品分支工作区;等用户确认角色+派活时随首单工作处理,避免在 sim 分支混 commit)
  - [ ] codex 回传闭环修复、11 ref 收尾清理——待用户指令排期
- **用户确认状态**:**等待用户确认角色总结后派活;确认前不执行任何项目改动**

## 记忆条目(一行一条,格式:标题 - 触发词;要点)

(暂无,从首轮实际工作开始追加)
