# 残留 git 分支 + worktree 全量盘点报告(2026-10-03)
> 只读盘点,零破坏性 git 写操作。本文档仅出「处置建议清单」,删除/合并动作由主控/后续 agent 执行。
> 产出人:researcher agent(隔离 worktree agent-abe52ea876cf28b9d);落档 feat/branch-inventory-20261003。

## 一、盘点口径说明(命令/判据)

**基线**:origin/main = 7fd2dbbb0(2026-10-03 fetch origin --prune 后)。

**命令序列**:
1. git fetch origin --prune(只更新 remote-tracking ref,不改本地分支)
2. git for-each-ref refs/heads / git branch --merged/--no-merged main → 分支总表与合/未合分群
3. git rev-list --left-right --count origin/main...<branch> → 各未合分支相对 main 的 behind/ahead commit 数
4. git log origin/main..<branch> --oneline + git diff-tree -r --stat <独有commit> → 分支独有 commit 及其文件范围
5. git ls-tree -r origin/main --name-only -- docs/ → main 全库 docs 文件名清单(1094 个文件)
6. git rev-parse origin/main:<路径> <branch>:<路径> → blob hash 逐位对比(同=内容逐位一致)
7. git diff origin/main <branch> -- <代码文件> → 核对生产代码新旧
8. git worktree list --porcelain + du -sh → worktree 全量/lock/磁盘
9. git worktree prune --dry-run → 失效 worktree 记录

**判「分支独有内容」的判据(不用三点 diff)**:
- 本报告用 **blob hash 逐位比**(git rev-parse,hash 同=逐位一致)+ **跨路径文件名查全库**(git ls-tree -r origin/main 全量按文件名 grep),双判据。
- 不用 git diff main...branch(三点 diff):比的是 merge-base vs 分支,分支共同祖先落后 main 时会把 main 早已收录的文件**误报成「分支独有」**(memory git-three-dot-diff-false-novelty,已实测踩坑 2 份 main 已收录报告被误判)。

## 二、本地分支总览

| 项 | 数量 | 说明 |
|---|---|---|
| 本地分支总数 | 76 | refs/heads 全量 |
| --merged main | 65 | 含 main 自身;含 1 个 **--merged 误判**(feat/accnav-backfill-exec-20261003,tip==main HEAD) |
| --no-merged main | 11 | 逐个处置见 §三 |

## 三、未合入 main 的本地分支(11 个)逐个处置表

| # | 分支名 | behind/ahead | 独有内容(相对 origin/main) | 处置建议 | 证据 |
|---|---|---|---|---|---|
| 1 | feat/149a-deploy-lock-split-review-20261002 | 71/1 | acc06b58a:docs/ops/149a-deploy-lock-split-review-20261002.md | **可安全删**(内容已在 main) | main 有同名;blob 8e3db26e 双端逐位同 |
| 2 | feat/cf-egress-probe-20261002 | 33/1 | 86d593e1e:docs/ops/cf-edge-egress-probe-20261002.md | **可安全删**(内容已在 main) | main 有同名;blob 10de179b 双端逐位同 |
| 3 | feat/harden-alerts-review-20261002 | 72/1 | 55a6c7602:docs/ops/harden-alerts-review-20261002.md | **可安全删**(内容已在 main) | main 有同名;blob 04e47759 双端逐位同 |
| 4 | feat/icepoint-source-groups-20261002 | 62/1 | bbe2ef46a:docs/research/icepoint-source-groups-returns-20261002.md + docs/scripts/icepoint_bt/bt_source_groups_ret.py | **可安全删**(内容已在 main) | main 有同名 2 文件;blob d8abeaf/978a766a 逐位同 |
| 5 | feat/r2-billing-4usd50-20261002 | 58/1 | 773911e61:docs/ops/r2-billing-4usd50-followup-20261002.md | **可安全删**(内容已在 main) | main 有同名;blob 500c3340 双端逐位同 |
| 6 | feat/r2-billing-research-20261002 | 72/1 | 628989754:docs/ops/r2-billing-usage-attribution-20261002.md | **可安全删**(内容已在 main;无远端) | main 有同名;blob 7652ae25 双端逐位同 |
| 7 | feat/r2-bucket-capacity-20261002 | 60/1 | 833264726:docs/ops/r2-backup-bucket-capacity-20261002.md + docs/scripts/r2_bucket_stats.py | **可安全删**(内容已在 main) | main 有同名 2 文件;blob 36667003/7111e129 逐位同 |
| 8 | worktree-agent-a814025345990cccf | 72/1 | da1b19ae1:18 文件(docs/research/icepoint-incremental-backtest-20261002.md + 17 个 docs/scripts/icepoint_bt/bt_*.py) | **可安全删**(内容已在 main;无远端) | 报告 blob 13d463ee 逐位同;git diff origin/main a814... -- docs/scripts/icepoint_bt/ 只显示 main 独有 bt_source_groups_ret.py,其余 17 文件零差异 |
| 9 | feat/icepoint-consensus-review-20261002 | 58/3 | 37d37de8c(app/compute/icepoint.py +116)、e62d698c7(app/queries.py +25)、2ec653d21(app/queries.py +16-2) | **⛔禁止合,建议删** | 见 §三-1 专项 |
| 10 | feat/icepoint-consensus-front-review-20261002 | 56/7 | 073ff952f(app.js +74/style.css +13)、b300a4087(purpose-notes.js +4)、03a45981f(docs+scripts)、256ec7bdc(合并 main)+ 同 #9 的 3 commit | **⛔禁止合,建议删** | 见 §三-2 专项 |
| 11 | zcode/standin-charter | 1012/1 | f5b25983d:.agents/zcode-standin/SKILL.md +1 行(ZCode 专属分支纪律) | **需人工定夺(保留)** | 见 §三-3 专项 |

### 三-1 专项:feat/icepoint-consensus-review-20261002(⛔禁止合)

**独有 3 commit 内容全部已在 main,分支无独有增量**:app/compute/icepoint.py main blob e1f6c1fd == 分支 blob e1f6c1fd(逐位同);app/queries.py main 的 098f755cc blob d8cbea1d7 == 分支 2ec653d21 blob d8cbea1d7,main 的 2f79c5579 blob cdb62111 == 分支 e62d698c7 blob cdb62111 → 分支的 queries 改动已通过 icepoint-consensus-20261002 合入 main,逐位一致。

**但分支 tip 的 queries.py 是旧版**:git diff origin/main 分支 -- app/queries.py 显示分支缺 main 已上线的:
- ae126cd72 的 **4 处 logger.exception**(走势卡 ETF 盈亏/信号卡 ETF 盈亏/时效横幅/汪汪队卡片,静默吞 DB 故障→留痕)
- 9e7ec2893 的 **icepoint 四因子失败 logger.exception 留痕**
- 分支甚至缺 import logging/logger 定义

**合入后果**:把 main 的 queries.py 倒退成缺异常留痕的旧版 → 熔断/降级故障恢复排查能力丢失。**结论:禁止合,建议删(无远端,纯本地残留)**。

### 三-2 专项:feat/icepoint-consensus-front-review-20261002(⛔禁止合)

**独有 7 commit 的前端/docs 内容全部已在 main**(与 main 的 commit 逐字相同):
- 分支 073ff952f == main cffe2b7a9(app.js +74/style.css +13,message/stat/diff 全同)
- 分支 b300a4087 == main ba65f8cf4(purpose-notes.js +4,全同)
- 分支 03a45981f == main bb57b7eb6(docs+scripts 报告,全同)
- queries/icepoint 3 commit 同 §三-1(main 已采纳)

**但分支 tip 的 app.js(e6542996)缺 main 已上线的生产修复**(git diff origin/main 分支 -- static-site/app.js):
- **A1.1 全局熔断**(a62563f5a):分支是旧版 _EM_TRIP_THRESHOLD=3 无跨 code 全局熔断冷却;main 是 =2 + _emGlobalDetFails/_emGlobalTripUntil/冷却短路
- **A1.2 休市感知停轮询**(a62563f5a):分支缺 _isMarketClosedToday(snap) + MARKET_OPEN_CHECK_HOLIDAY_MS + _holiday 判定
- **A1.2 Finding1-3 港股错位日修正**(a62563f5a):分支缺 _isMarketClosedTodayForCode(港股恒放行实时)/state.intradaySnapshot 最新 snap/港股交易时段判定
- **冰点二义修复**:分支缺 sh_hits.total<4「数据不足不可判定 vs 评估过未命中」的双义判据(tooltip + 下钻弹窗两处)
- **❓tooltip 显示 <b> 标签修复**(18d69cdbb):分支保留初版 termTip(_icePublic) 直塞 HTML 进 data-tip → 字面显示 <b> 标签的 bug 版
- **全站帮助图标移动端双弹修复**(2026-10-03):分支缺 _modalHelpSel 排除集合([data-ice-note] 等)

**合入后果**:把 static-site/app.js 倒退到 2026-10-02 前旧版,丢失上述全部线上修复 → 盘中东财失败噪音/休市轮询轰炸/港股错位/❓显示 bug 复发。**结论:禁止合,建议删(无远端,纯本地残留)**。

### 三-3 专项:zcode/standin-charter(需人工定夺)

- 独有 commit f5b25983d 给 .agents/zcode-standin/SKILL.md +1 行「⚠️ ZCode 专属分支纪律(2026-09-03 用户定):ZCode 所有产出走 zcode/* 分支,禁止直接 commit/push main」
- 分支 SKILL.md blob 55d593ae ≠ main f7d79738:**双向分叉**:分支有 main **没有**的新内容(ZCode 专属分支纪律段);分支保留 main **已改掉**的旧表述(§14 生产稳定推 main 前查 launchd 时点 — main 已改「云上 systemd timer」,memory local-dev-cloud-prod-split;hooks 机械提醒描述也旧)
- 有远端 origin/zcode/standin-charter,是 ZCode 代班秘书章程活分支(memory zcode-standin-handoff)
- **建议:保留,需人工定夺**(把 main 的 systemd timer 新口径合回分支;分支的分支纪律段决定是否合回 main 或留作 ZCode 工作分支)

## 四、已合入 main 的本地分支(65 个含 main)清理建议

**可批量清理约 59 个**:git branch --merged main 列出的 feat/* 与 worktree-agent-* 分支(内容已在 main,--merged 判据成立)。

**不应删的例外**:
| 分支 | 原因 | 证据 |
|---|---|---|
| main | 工作分支 | — |
| feat/accnav-backfill-exec-20261003 | **⛔ 在用(--merged 误判典型)**:acc_nav 补数任务有 background agent 在跑,worktree agent-a9e2db23c2af94c4a locked(pid 38456) | 分支 tip 7fd2dbbb0==main HEAD → --merged 判真但实际是刚分出未提交的在用分支;**任何情况下不得删/checkout/改动** |
| worktree-agent-abe52ea876cf28b9d | 当前盘点会话的 worktree 分支 | 本会话结束随 worktree 一起清 |
| worktree-agent-a01716f9c4489a301 / worktree-agent-ac562449df83a621b | locked worktree 占用(pid 38456),需等会话结束 | git worktree list --porcelain 的 locked 标记 |
| feat/export-guard-20261003 / feat/worktree-cleanup-20261003 | 已合但 worktree 仍 checkout 在分支(agent-ae93b4063088ad451 / agent-a0b7e692af78b2ef3),需先 git worktree remove 再删分支 | worktree list 对应关系 |
| worktree-agent-a4769bc9343c0828a / worktree-agent-a54d78abfef6c90f5 / worktree-agent-ab46344df19b9c206 | worktree 占用(agent-* 同前缀目录),先清 worktree 再删分支 | worktree list |

> 处置顺序建议:先 git worktree remove 清占用 worktree(§25 备份后),再 git branch -d 删分支;远端对应分支由主控另行 git push origin --delete。

## 五、worktree 盘点(21 登记 + 3 孤儿目录)

### 5.1 全量表

| worktree 路径(相对 .claude/worktrees/) | checkout 分支 | HEAD | locked | 类别 | 磁盘 |
|---|---|---|---|---|---|
| agent-a09d991351b5b1300 | feat/cf-egress-probe-20261002 | 86d593e1e | 否 | **可立即清理**(分支内容已在 main) | 127M |
| agent-a0b7e692af78b2ef3 | feat/worktree-cleanup-20261003 | 8ac1c19a1 | 否 | **可立即清理**(merged) | 127M |
| agent-a0c6da07deae45237 | feat/icepoint-source-groups-20261002 | bbe2ef46a | 否 | **可立即清理**(分支内容已在 main) | 130M |
| agent-a0ef0a0b2e02c6903 | feat/r2-billing-4usd50-20261002 | 773911e61 | 否 | **可立即清理**(分支内容已在 main) | 127M |
| agent-a388e66389260da74 | feat/r2-billing-research-20261002 | 628989754 | 否 | **可立即清理**(分支内容已在 main) | 126M |
| agent-a4769bc9343c0828a | worktree-agent-a4769bc9343c0828a | 11073b291 | 否 | **可立即清理**(merged) | 127M |
| agent-a54d78abfef6c90f5 | worktree-agent-a54d78abfef6c90f5 | 11073b291 | 否 | **可立即清理**(merged) | 127M |
| agent-a814025345990cccf | worktree-agent-a814025345990cccf | da1b19ae1 | 否 | **可立即清理**(18 文件全在 main) | 130M |
| agent-ab46344df19b9c206 | worktree-agent-ab46344df19b9c206 | 11073b291 | 否 | **可立即清理**(merged) | 127M |
| agent-ab98f5d739f81c907 | feat/149a-deploy-lock-split-review-20261002 | acc06b58a | 否 | **可立即清理**(分支内容已在 main) | 126M |
| agent-ae8445feaaa1615ec | feat/r2-bucket-capacity-20261002 | 833264726 | 否 | **可立即清理**(分支内容已在 main) | 130M |
| agent-ae93b4063088ad451 | feat/export-guard-20261003 | a1b5f13c3 | 否 | **可立即清理**(merged) | 127M |
| rev-harden-2 | feat/harden-alerts-review-20261002 | 55a6c7602 | 否 | **可立即清理**(分支内容已在 main) | 126M |
| agent-ad766797159ec2036 | detached(69d61156f=main 已有 commit) | 69d61156f | 否 | **可立即清理**(detached,内容已在 main) | 127M |
| agent-a01716f9c4489a301 | worktree-agent-a01716f9c4489a301 | 8723a64a2 | **是(pid 38456)** | locked 需等会话结束 | 127M |
| agent-ac562449df83a621b | worktree-agent-ac562449df83a621b | 27813df68 | **是(pid 38456)** | locked 需等会话结束 | 127M |
| agent-abe52ea876cf28b9d | worktree-agent-abe52ea876cf28b9d | 7fd2dbbb0 | **是(pid 38456)** | 本盘点会话 worktree,会话结束才清 | 127M |
| agent-a9e2db23c2af94c4a | feat/accnav-backfill-exec-20261003 | 7fd2dbbb0 | **是(pid 38456)** | **⛔不应清理**(在用 acc_nav 补数任务) | 127M |
| agent-a5622e1883dac9dd4 | feat/icepoint-consensus-review-20261002 | 2ec653d21 | 否 | **待分支处置**(⛔禁止合分支) | 127M |
| agent-aa83f3a3efeff690e | feat/icepoint-consensus-front-review-20261002 | 256ec7bdc | 否 | **待分支处置**(⛔禁止合分支) | 127M |
| /Users/linhuichen/code/trade | main(主 checkout) | 7fd2dbbb0 | 否 | **不清理** | — |

### 5.2 孤儿目录(文件系统存在、git worktree list 无登记,git worktree prune --dry-run 无输出,需人工 rm)

| 目录 | 磁盘 |
|---|---|
| .claude/worktrees/agent-a4d09b139bcfc8043 | 127M |
| .claude/worktrees/agent-a5e9d82d968afd895 | 127M |
| .claude/worktrees/agent-a618e4617ed5354e3 | 127M |

### 5.3 磁盘统计

| 类别 | 个数 | 磁盘 |
|---|---|---|
| 可立即清理(worktree) | 14 | ~1784M(≈1.74GB) |
| 可立即清理(孤儿目录) | 3 | 381M |
| **可立即释放合计** | **17** | **≈2.11GB** |
| locked 需等会话结束(不含 accnav 与本会话) | 2 | ~254M |
| 本会话 worktree(会话结束清) | 1 | 127M |
| ⛔ 在用不应清理(accnav) | 1 | 127M |
| ⛔ 禁止合分支 worktree(待处置) | 2 | ~254M |
| 主 checkout | 1 | — |

## 六、结论摘要

**现在可以安全删的**(内容已全部在 main,blob 逐位一致):
- 未合分支 8 个:149a-deploy-lock-split-review / cf-egress-probe / harden-alerts-review / icepoint-source-groups / r2-billing-4usd50 / r2-billing-research / r2-bucket-capacity / worktree-agent-a814025345990cccf
- 已合分支约 59 个(git branch --merged main 其余)
- worktree 17 个(14 登记 + 3 孤儿)≈ 2.11GB

**需要抽出来合的**:**无** —— 全部未合分支的独有内容(报告/docs/scripts)blob 逐位已在 main,无抽内容合的对象;唯一有代码独有内容的两个分支(icepoint 两 review)其代码也已在 main 且 tip 是旧版,结论是禁止合而非抽内容合。

**需人工定夺**:zcode/standin-charter(双向分叉章程,保留)。

**禁止碰的**:
- feat/accnav-backfill-exec-20261003 及其 worktree(在用,--merged 误判典型,红线)
- feat/icepoint-consensus-review-20261002、feat/icepoint-consensus-front-review-20261002(⛔禁止合,建议删,理由见 §三-1/三-2)

## 七、诚实标注(与任务预估的偏差)

- **worktree 数**:任务预估「残留 worktree 约 20 个」;实测登记 21 个(20 个 agent-* + rev-harden-2)+ 3 个孤儿目录(无登记)= **24 个残留目录**。
- **locked 数**:任务预估「约 7 个 locked(pid 38456)」;实测 git worktree list --porcelain 带 locked 的 **4 个**,全部 pid=38456(start Thu Sep 17 14:26:21 2026,同一 claude --resume 主进程),无其它 lock 标记。任务预估值与实测的差异按实测为准。
- 分支数:任务预估「已合约 63、未合约 11」;实测 --merged 65(含 main 自身)、--no-merged 11。差异来自 accnav-backfill-exec 被 --merged 误判计入。

## 复现(## 复现)

以下命令序列可重跑出同一张表(在任意 worktree 或主 checkout 执行,git 仓库共享):

```bash
# 1. 刷新远端
git fetch origin --prune

# 2. 分支总表
git branch --merged main | wc -l        # 65(含 main)
git branch --no-merged main             # 11 个
git for-each-ref refs/heads --format=%(refname:short)|%(objectname:short)|%(upstream:short) | sort
# 3. 未合分支 behind/ahead 与独有 commit
git rev-list --left-right --count origin/main...<branch>
git log origin/main..<branch> --oneline
git diff-tree -r --stat <独有commit>

# 4. 判内容是否已在 main(blob hash 逐位比)
git ls-tree -r origin/main --name-only -- docs/ > /tmp/main-docs.txt
grep -F <文件名> /tmp/main-docs.txt
git rev-parse origin/main:<路径> <branch>:<路径>   # hash 同=逐位一致

# 5. 判生产代码新旧
git diff origin/main <branch> -- app/queries.py
git diff origin/main <branch> -- static-site/app.js

# 6. worktree 与磁盘
git worktree list --porcelain
git worktree prune --dry-run
du -sh /Users/linhuichen/code/trade/.claude/worktrees/agent-* /Users/linhuichen/code/trade/.claude/worktrees/rev-harden-2
```

## 九、报告闭环

- 本文档 = 报告本体;生成依据 = 上述 git 只读命令(无独立生成脚本,复现段可重跑)。
- 后续处置(删分支/删 worktree/删远端/合 zcode)由主控按 §25(备份后删)/§8(机制 D)执行,本报告只出建议。
