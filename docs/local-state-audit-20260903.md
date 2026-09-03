# 本地状态审计(2026-09-03)

> 只读审计报告,未改动任何文件。审计对象:主仓库 /Users/linhuichen/code/trade(main, HEAD=13ce38eb9=origin/main)。
> 审计范围:工作区改动文件 / worktree / 未跟踪文件 / 未上线 commit / stash / /tmp 残留 / 报告落档。

## 0. 结论速览(五类)

| 分类 | 数量 | 明细 |
|---|---|---|
| ✅ 正常待 commit | 1 | TASKS.md(FAPI 观察期交接段,会话中改动,4+/1-,合理) |
| ✅ 正常状态 | 3 | 两个 locked worktree(在跑 agent 隔离区)+ 32 项 data/ 根数据产物(§8 本就不进 git) |
| ⚠️ 该 gitignore | 1 | .codegraph/(工具本地缓存,54MB db,内部自带 .gitignore 已兜底,建议根 .gitignore 补 .codegraph/) |
| ⚠️ 该清理(已结束任务的残留) | 4 类 | docs/_test(0 字节空文件)、scripts/agent_inbox_watcher.py.bak(被原文件取代)、stash 16 条历史残留、/tmp/agent-progress-*.md 139 个 |
| 🔴 做了没上线(待主控决策) | 1 分支 | research/fapi-h-k1 分支 12 个 commit 未合入 main(含 feat(fapi) 生产改动,需核对是否该 merge/归档) |

## 1. TASKS.md 的 M(4+/1-,仅「最后更新」交接段一处)

- **证据**:`git diff --stat TASKS.md` = `1 file changed, 4 insertions(+), 1 deletion(-)`;diff 内容仅「最后更新」交接段(2026-09-01→09-03,新增外审 v1.1.14 收尾批闭环 + FAPI 观察期评估登记,并把旧交接折叠为「历史交接(≥2 轮前)」)
- **结论**:是主控会话中登记的 FAPI 观察期交接段改动,**只此一处、合理待 commit**,无异常夹带。

## 2. 未跟踪文件逐个定性(非 data 5 项 + data 抽查)

### 2.1 `.codegraph/` — 工具本地缓存,该 gitignore(非该进 git)
- **证据**:内含 `codegraph.db`(54,042,624 字节,54MB,9-3 09:32) + 自带 `.gitignore`(`*` + `!.gitignore`);根 `.gitignore` 无 `.codegraph/` 条目;`git check-ignore .codegraph` = NOT-IGNORED;`.codegraph/.gitignore` 未被 tracked(`git ls-files .codegraph/` 空)
- **定性**:codegraph 工具(codex 评估落档 docs/codex-reviews/codegraph-eval-20260901.md)本地索引缓存,**54MB 大文件不能进 git**;内部 `.gitignore` 已兜底(db 不会被打包),但 git status 仍显示 `?? .codegraph/` 目录
- **建议**:根 `.gitignore` 加一行 `.codegraph/`(目录整体忽略,更干净);工具本身结论「值得装但只定位不当影响面」已在 eval 落档

### 2.2 `docs/_test` — 测试残留,可删
- **证据**:0 字节空文件,`file` = `empty`,mtime 9-2 10:44(09-02 会话期)
- **定性**:测试产生的空占位残留,非正式文档
- **建议**:删除

### 2.3 `scripts/agent_inbox_watcher.py.bak` — 备份被原文件取代,可删
- **证据**:原文件 `scripts/agent_inbox_watcher.py` 在(7,748B,9-3 00:14);.bak 7,753B(9-2 10:32);launchd `com.trade.agent-inbox-watcher.plist` ProgramArguments 指向原文件 `scripts/agent_inbox_watcher.py`;diff 仅 1 行:LOCK_PATH 从 `/tmp/agent_inbox.lock` 改为 `.git/agent_inbox.lock`
- **定性**:一次小改动的旧备份,已被原文件取代且无任何引用
- **建议**:删除(差异仅 lock 路径,如需保留历史可查 git)

### 2.4 `scripts/codex-watcher.sh` — 孤儿脚本确认,与 7d-function-audit 结论一致
- **证据**:内容 300B 只是 `exec python3 scripts/agent_inbox_watcher.py` 的 zsh 包装;launchd 目录无 codex-watcher plist(35 个 com.trade.* plist 中仅 `com.trade.agent-inbox-watcher.plist` 引用 agent_inbox_watcher.py);grep scripts/CLAUDE.md 无其他引用,仅 docs/7d-function-audit-20260902.md:91-93 点名「孤儿脚本 codex-watcher.sh 无任何 launchd/脚本引用」
- **定性**:7d-function-audit 已确认的孤儿脚本,本轮复查仍无引用(仅自身注释 + 手动启动便捷入口),功能本体 agent_inbox_watcher.py 已被 launchd 挂载
- **建议**:保留作手动启动入口可,或删除(功能不依赖它);低风险

### 2.5 data/ 32 项 — §8 规范根 data/ 不进 git,均正常,但注意两类
- **证据**:32 项全为 `?? data/`;`.gitignore` 已覆盖部分(etf_national_team.db/public_fund.db/sentiment.db 等 L37/L42/L12),但**大量状态 json/db 未在 .gitignore 中**(如 signal.db、fund.db、board_concept.db、ab_direction_anchor.json、etf_index_map.json 等,`git check-ignore data/signal.db`=NOT-IGNORED)
- **定性**:按 CLAUDE.md §8「不 add 根目录 data/ 下任何文件」,这些本来就**不进 git**,未跟踪属正常;但 .gitignore 覆盖不全导致 git status 长期 32 项噪音
- **两类值得注意**:
  - **0 字节空库**:`data/board_concept.db`(0B)、`data/fund.db`(0B)、`data/.tickertmp/`(2 个 0B 头文件 bn_headers.txt/cc_headers.txt)——疑似初始化残留,可清
  - **.bak 旧备份 5 个**:alert_state.json.bak-x2(8-4/8-14)、daily_brief.json.bak-20260814-legacy、etf_national_team.db.bak-backfill-20260728(38MB!)、news_digest.json.bak-rewash-html-20260816——均为 7-8 月旧备份,无引用,可清(38MB db bak 是大头)
- **建议**:①根 .gitignore 补一组 data 忽略规则(或建 data/.gitignore 忽略全部)消除 32 项噪音;②清 0 字节空库 + 5 个 .bak(尤其 38MB db bak)

## 3. 做了没上线(重点扫描)

### 3.1 main 无未推 commit
- **证据**:`git rev-parse origin/main` == `git rev-parse HEAD` == 13ce38eb9;`git log origin/main...HEAD` 空
- **结论**:主仓库 main 工作区与远端完全同步,无「本地 commit 未 push」

### 3.2 🔴 research/fapi-h-k1 分支 12 个 commit 未合入 main(待主控决策)
- **证据**:`git branch -a` 有 `research/fapi-h-k1`(bd94b227f,origin/research/fapi-h-k1 同 hash 已推);`git log research/fapi-h-k1 --not origin/main` = 12 个 commit;merge-base=851f41b2;该分支领先 main 45/落后 12(`git rev-list --left-right --count`=45 12)
- **12 个 commit 内容**(从新到旧):
  - bd94b227f feat(fapi): P2 盘中延迟实测完成(238轮,秒级实时档可兜底)
  - b4b7286cc fix(kelly): repro s06NoBull 返回对象 bug 修正+全 s06 数字重跑落档
  - d68c8b58e docs(tasks): 夜间轮FAPI四条线状态同步
  - c80fd38c4 feat(fapi): THS概念换官方并行对照脚本+基线报告
  - d82b28cca feat(fapi): P1 涨停池+龙虎榜兜底源落地(东财空值时FAPI异源)
  - 9adc2a81a docs(summary): 夜间连轴转总结落档
  - f46681f70 fix(fapi): P0 生产落点修正+采集自动清理
  - 62bdb47bc docs(analysis): TASKS#20 交易方法最终推荐方法论
  - 2becc27ea docs(kelly): k1 名次偏移回测结论
  - f581770cb docs(fapi): P0 日线 T+0 采集落地
  - 46836bbbd docs(fapi): 同花顺FAPI接入方案+试点验证
  - 9a14cc65b chore(命中率走势): 2026-09-01 自动追加
- **定性**:分支名带 research 前缀,多数为 docs/方案落档,但**含多个 feat(fapi)/fix(fapi) 生产改动**(P0/P1/P2、涨停池兜底、THS 对照脚本、采集自动清理)。TASKS.md 交接段未提及此分支;外审 v1.1.14 收尾批只删了 3 个分支(feat/etf-weight-leader-b123-backtest、codex/ghi-sim-modal-handoff、fix/platform-healthcheck-mjs),未处理 research/fapi-h-k1
- **⚠️ 建议主控核对**:FAPI 四条线观察期(com.trade.fapi-daily 已挂载)是「只增不改」试点,这些 feat/fix 是否已通过其他路径上线、或是否需要在观察期结束前合 main——**不该静默搁置**(§23.11 不静默);若为纯研究存档可归档分支

### 3.3 git stash 16 条残留,基本全是历史,可清
- **证据**:`git stash list` = 16 条,stash@{0}(zcode-standin memory M + sensenova detect-log temp)最新,@{1}(TASKS状态更新暂存),@{2}(main-merge conflict 20260829),@{3}(crash-recovery-backup-20260812),@{4}-@{15} 全为 07-30~08-29 的 feat/iframe-theme-follow、feat/b4-* 等已结束分支的 rebase/temp 暂存
- **定性**:stash@{0} 内容已确认是 zcode-standin 代班收尾的 memory 快照(该单已闭环上线 67481e89b,stash 内「首单全链闭环上线」已发生);其余全部为已结束任务的历史暂存,无恢复价值
- **建议**:`git stash drop` 全部 16 条(或至少 @{0}@{1}@{2} 之外 13 条老批次);仅 @{2} main-merge conflict 或需人工确认后 drop

### 3.4 .claude/worktrees/ 历史残留:已清干净
- **证据**:`.claude/worktrees/` 目录内仅 2 个子目录(agent-a30946ddd9476ccb5、agent-a71bdf0bce9ac1ea9),均为 9-3 16:07 更新、locked;`git worktree list` = main + 这 2 个,共 3 条
- **结论**:除两个在跑 agent 的隔离区外无历史 worktree 残留,与任务描述一致

### 3.5 data/alerts/latest.md 近 1-2 天:无「已完成未上线」隐患,只有例行监控告警
- **证据**:latest.md(23KB,9-2 20:30)tail 记录 09-01~09-02 的 severe 告警:update_all 耗时超 1h(123min/154min)、etf_national_team 退出失败、飞书 hook 心跳陈旧——均为**生产监控例行告警**,非「代码做了没上线」
- **结论**:无「已完成未上线」信号;告警本身(update_all 持续超时、心跳陈旧)是运维隐患,不属本次审计范围但可顺带提示主控

## 4. 废弃残留清单

### 4.1 /tmp/agent-progress-*.md — 139 个,基本全可清
- **证据**:`ls /tmp/agent-progress-*.md | wc -l` = **139**(比任务描述「十几个」多很多);mtime 跨度 08-29 20:21 ~ 09-03 16:15;最老 agent-progress-ghi-modal.md(08-29)、agent-progress-implementer-gih-fix.md(08-29)、agent-progress-s06-k1-v2.md(08-29)
- **注意**:其中 `agent-progress-opt-baostock.md`(9-3 16:12)和 `agent-progress-opt-sensenova.md`(9-3 16:08)是**当前在跑 2 个 implementer agent 的进度文件,不能清**;`agent-progress-local-audit.md`(本审计)结束后也可清
- **建议**:保留 opt-baostock/opt-sensenova/local-audit 3 个,其余 136 个可通删除(已结束 agent 的临时进度文件,落档价值已过期)

### 4.2 data/ 目录 .bak/空库清单
- **证据**:见 §2.5
- **建议**:删 5 个 .bak(含 38MB etf_national_team.db.bak-backfill)+ 3 个 0 字节空库(board_concept.db/fund.db/.tickertmp/)

## 5. 处理建议汇总

| 动作 | 目标 | 优先级 |
|---|---|---|
| commit TASKS.md | FAPI 观察期交接段 | 常规 |
| 根 .gitignore 补 `.codegraph/` | 消除 `?? .codegraph/` 噪音 | 低 |
| 根 .gitignore 补 data 条目或建 data/.gitignore | 消除 32 项 data 噪音 | 中 |
| 删 docs/_test | 0 字节测试残留 | 低 |
| 删 scripts/agent_inbox_watcher.py.bak | 旧备份被取代 | 低 |
| 处理 scripts/codex-watcher.sh | 孤儿脚本,删或留手动入口(二选一,低风险) | 低 |
| 删 data/*.bak 5 个 + 0 字节空库 3 个 | 释放 38MB+ | 中 |
| git stash drop 16 条 | 历史暂存全清 | 低 |
| rm /tmp/agent-progress-*.md 136 个(留 opt 两个 + local-audit) | 临时进度残留 | 低 |
| **主控核对 research/fapi-h-k1 分支 12 commit 去留** | 未合 main 的 feat/fix 生产改动,不静默搁置 | **高** |

## 复现

- **审计命令**(全部只读):
  - `git status --porcelain`(37 项:1 M + 36 ??)
  - `git diff --stat TASKS.md`(4+/1-,仅「最后更新」段)
  - `git worktree list`(main + 2 locked agent worktree)
  - `git stash list`(16 条)
  - `git log research/fapi-h-k1 --not origin/main`(12 个未合 commit)
  - `git rev-parse origin/main` == `HEAD` == 13ce38eb9(main 无未推 commit)
  - `ls /tmp/agent-progress-*.md | wc -l`(139,留 3 个在跑)
  - `git check-ignore .codegraph data/signal.db`(均 NOT-IGNORED)
- **数据截止**:2026-09-03 16:2x(本地快照)
- **关键口径**:「正常待 commit」= 会话中交接段改动;「做了没上线」= research/fapi-h-k1 未合 main 分支;「该 gitignore」= .codegraph 与 data 噪音;「残留」= 已结束任务临时产物/备份
