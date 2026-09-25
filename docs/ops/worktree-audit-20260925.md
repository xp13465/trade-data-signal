# worktree 审计清单(2026-09-25 只读分析)

## 复现段
- 判定方法:`git cherry main <branch>`(patch-equivalent;main-merge.sh 合入无 merge 祖先,不能用 `--merged`)
  - 空输出 = 无未合入 commit;`git merge-base --is-ancestor <branch> main`=0 复核(18 个空输出分支全=0)
  - `+ <sha>` = patch 不等价,需逐 commit 查内容是否已在 main
- 细查工具:`git log main..<branch> --oneline`、`git show --stat <commit>`、`git rev-parse <commit>:<path>` vs `git rev-parse main:<path>` blob 对比、`git grep -c <串> main -- <file>`、`git log main --oneline -S"<串>"`
- 本次只读,未删任何 worktree/分支/文件。删除需用户拍板后另行派单。

## 一、清单 A — 可安全删除(20 个)
判定口径:分支是 main 祖先(18 个)或独有 commit 的文件 blob 与 main 逐字节一致(3 个,内容已等价合入)。

| worktree 路径 | 分支 | HEAD | 判定 |
|---|---|---|---|
| /private/tmp/wt-caliber-fix | feat/backtest-caliber-report-20260923 | 1f6cda2c3 | main 祖先 |
| /private/tmp/wt-signal-freeze | feat/signal-historical-freeze | 991c27dfb | main 祖先 |
| /private/tmp/wt-snapshot-p2 | feat/signalfreeze-p2-check | d18712780 | main 祖先 |
| .claude/worktrees/agent-a0871d3eef48492a7 | worktree-agent-a0871d3eef48492a7 | e667de370 | main 祖先 |
| .claude/worktrees/agent-a254918c7ae5f2985 | worktree-agent-a254918c7ae5f2985 | 2ceb126d4 | main 祖先(主控线索吻合) |
| .claude/worktrees/agent-a2f56d09bf34000ff | worktree-agent-a2f56d09bf34000ff | 64d15f4fb | main 祖先 |
| .claude/worktrees/agent-a4474317daa5a4a07 | worktree-agent-a4474317daa5a4a07 | 2912c0b03 | main 祖先(主控线索吻合) |
| .claude/worktrees/agent-a6c5d46b28ba49275 | worktree-agent-a6c5d46b28ba49275 | cc377bcca | main 祖先(主控线索吻合) |
| .claude/worktrees/agent-a7a512194ebe31e43 | worktree-agent-a7a512194ebe31e43 | df52bf8e9 | main 祖先 |
| .claude/worktrees/agent-a85ae8e9941f8de93 | worktree-agent-aaaa97454818dc615 | 6103bfb7e | main 祖先;目录名≠分支名(异常1) |
| .claude/worktrees/agent-a90417b764ef6370a | worktree-agent-a90417b764ef6370a | 944c1a2c9 | main 祖先 |
| .claude/worktrees/agent-abd28234902d47e47 | worktree-agent-abd28234902d47e47 | b51f74b3f | main 祖先 |
| .claude/worktrees/agent-ac8bf1e12974d4cc5 | worktree-agent-ac8bf1e12974d4cc5 | c6ee9df96 | main 祖先(主控线索吻合) |
| .claude/worktrees/agent-ada4e557517366569 | feat/tasks-anomaly-selfheal | a993e5b83 | main 祖先;目录名≠分支名(异常2) |
| .claude/worktrees/agent-ae2c9fa42fc7a6a21 | worktree-agent-ae2c9fa42fc7a6a21 | 25828eb65 | main 祖先(主控线索吻合) |
| .claude/worktrees/agent-aec4d27d16e687b98 | worktree-agent-aec4d27d16e687b98 | b891a29c5 | main 祖先 |
| .claude/worktrees/agent-af47e386c7e9e020d | worktree-agent-af47e386c7e9e020d | 76e3214bd | main 祖先 |
| .claude/worktrees/agent-a13e6a52752824cbe | worktree-agent-a13e6a52752824cbe | b545b037a | 独有1 commit(告警噪音取证报告),blob==main(alert-noise-evidence-20260924.md f64d11e05) |
| .claude/worktrees/agent-a4d6d2f9ab211ddf4 | worktree-agent-a4d6d2f9ab211ddf4 | c82d0b644 | 独有1 commit(nextday 空计划根因),blob==main(nextday-plan-empty-rootcause-20260924.md 7bbf6477d) |
| .claude/worktrees/agent-aec22047efaf26f81 | worktree-agent-aec22047efaf26f81 | fc672fccf | 独有1 commit(proxy retry review),blob==main(proxy-transport-retry-review-20260924.md 902f8449e) |

## 二、清单 B — 需人工定(4 个)
| worktree 路径 | 分支 | HEAD | 独有 commit | 涉及文件 | 这活是什么 | 建议 |
|---|---|---|---|---|---|---|
| .claude/worktrees/agent-a550f7036cd5b2469 | worktree-agent-a550f7036cd5b2469 | c5ea51a2a | 7fef306bd + c5ea51a2a | beijiao_width.py 等 8 文件 + docs/analysis/beijiao-width-implement-20260902.md + README | 北交所宽度 C 方案实施 | 功能已改名 bj_width.py 合入 main(app/queries.py 8 处 bj_width、app.js 29 处、runner.py 6 处、pipeline.sh 1 处),README 已含「北交所」2 处。残留:实施文档 + launchd plist(launchd 已废弃)。建议=该废弃;文档若要留可 cherry-pick |
| .claude/worktrees/agent-ae30594839233ea8c | worktree-agent-ae30594839233ea8c | e73fcb646 | e73fcb646 | docs/ops/cgb10y-self-etf-feasibility-20260924.md | cgb_10y_etf self-ETF 可行性调研(结论不配+落地清单) | 文档未进 main。建议=该废弃或主控拍板(cherry-pick 留档) |
| .claude/worktrees/agent-ae5e8d204adef9e71 | worktree-agent-ae5e8d204adef9e71 | be8c710f7 | be8c710f7 | docs/review/proxy-env-hardening-delta-review-20260924.md | proxy env 数值解析加固 delta 复审(PASS-with-conditions) | 复审提到的「PEAK_HOURS 同类漏网必须修」已在 main 修掉(8fbd8f1d4 TTP_PEAK_HOURS 加守卫)。文档未进 main。建议=该废弃(核心待办已修) |
| .claude/worktrees/codex-reviewer | codex/mobile-ux-a11y-overreach-v4 | 14fbfbd0f | (无独有) | - | codex 评审通道固定 worktree | 分支已合入 main(main 祖先);按 memory codex-worktree-isolation 此目录是 codex 评审标准工作区,是否保留由主控/用户定 |

## 三、异常项
1. **目录名≠分支名(2 个)**:agent-a85ae8e9941f8de93 → 分支 worktree-agent-aaaa97454818dc615;agent-ada4e557517366569 → 分支 feat/tasks-anomaly-selfheal。疑似派单时目录/分支命名错位,不影响删除判定(分支均 main 祖先)。
2. **locked**:仅 agent-a7856132ec7f3894c(本次审计 agent 自己,pid 38456),非异常。
3. **HEAD 悬空**:无 detached worktree。
4. **幽灵 worktree**:本次 `git worktree list` 26 个全部目录存在、注册有效;09-23 文档列出的 10 个幽灵已不在本列表。

## 四、验证方法清单
- `git cherry main <branch>` 全 24 分支 + `git merge-base --is-ancestor <branch> main`(18 个空输出分支全=0)
- blob 对比:`git rev-parse <commit>:<path>` == `git rev-parse main:<path>`(a13/a4d6/aec22 三文档逐字节一致)
- 功能等价:`git grep -i beijiao main` → app/collector/bj_width.py;`git grep -c bj_width main -- app/queries.py static-site/app.js`(8/29 处)
- 待办落地:`git log main --oneline -S"PEAK_HOURS" -- scripts/` → 8fbd8f1d4
