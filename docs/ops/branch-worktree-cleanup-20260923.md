# 分支/worktree 清理清单(2026-09-23 只读分析)

## 复现段
- 仓库: /Users/linhuichen/code/trade | main: `fb3a75a67` | origin/main 与本地 main 一致
- 判定方法: `git cherry main <branch>`(非 `--merged`,因 main-merge.sh 合入无 merge 祖先,`--merged` 会误判)
  - 输出 `- <sha>` / 空 = 等价 patch 已在 main = 已合入;输出 `+ <sha>` = 未合入
- 临时脚本: /tmp/classify_local2.sh、/tmp/classify_remote2.sh(放 /tmp,未入仓库);原始分类数据: /tmp/branch-local-classify2.txt、/tmp/branch-remote-classify2.txt、/tmp/worktree-dirs.txt
- 本次只读分析,未删任何分支/worktree/文件

## 一、分类统计
- 本地分支 225 = A(已合入可删) 214 + B(未合入需人工) 10(main 1 个排除)
  - A 类未被 worktree 占用(可直接删): **127**
  - A 类被 worktree 占用(先清 worktree 再删): **87**
- 远端分支 180 = A(已合入可删) 169 + B(未合入需人工) 11(main 排除)
- C 类(未合入+最后活动>30 天+被后续分支取代): **0 个** — 全部 B 类最后 commit 都在 30 天内(2~21 天)
- worktree 登记 97 个(含主 worktree),其中幽灵/可 prune: **10 个**(6 个目录不存在 + 4 个目录存在但无 .git 文件只剩残留数据)
- 备注: git cherry 的 `-` 判定为「等价 patch 已在 main」(main-merge 无祖先也可判定),与 `--merged` 不同,可信

## 二、A 类完整清单
### 2.1 本地未被 worktree 占用 127 个(可直接 `git branch -D` 删除)
```
codex/fix-watcher-notify-race
codex/review-skill-cx006-008
codex/reviewer
codex/site-review-sigkelly-20260917
codex/site-review-sigkelly-mobile-ux-v2
codex/site-review-sigkelly-mobile-ux-v3
codex/watcher-model-v41
docs/kelly-stall-report
feat/11day-mode
feat/a1-immutable-cache
feat/a11y-cleanup-v5
feat/accum-nav-check-since-return-fix
feat/alert-noise-rootfix
feat/at-steps-hl-done-focus
feat/at-steps-sell-rows
feat/atomic-write-sweep
feat/atomic-write-trades-fix
feat/baostock-10001001-reconnect
feat/claude-md-refactor
feat/cloud-arch-separation
feat/cloud-finalize-fix
feat/cloud-path-hardcode-fix
feat/cloud-sync-after-merge
feat/decommission-r2-20260903
feat/deploy-git-fetch-timeout-20260915
feat/deploy-nonblock-boardmap
feat/deploy-push-timeout
feat/eastmoney-turnover-baostock
feat/evo-fix
feat/evo-hover-fix
feat/feishu-follow-group
feat/fix-159880-nextday-gate
feat/fix-ci-download-skip
feat/fix-cloud-single-repo-path
feat/fix-gih-nav-ready-gate
feat/fix-kelly-stagnation-weekend
feat/fix-monitor-overview-lag
feat/fix-overfit-monitor-real-buy-date
feat/fix-ovf-parity-c-window
feat/fix-r2-upload-timeout-systemic
feat/fix-timeout-fetch-news-ab-anchor
feat/frontend-steps-slot-render-order
feat/gap-check
feat/gapcheck-date-freshness
feat/gapcheck-fail-r2
feat/homepage-signal-trend-fix
feat/homepage-trend-backfill-badge
feat/intraday-realprice-trade90
feat/kelly-freeze-timespot-rootfix-20260918
feat/kelly-intraday-rerun
feat/kelly-netasset-vol-curve
feat/kelly-rootfix-345
feat/kelly-unique-export
feat/kelly-unique-frontend-parity
feat/kelly-unique-parts
feat/krating-data-driven
feat/local-audit-clean
feat/lof-field-filter-nav-backfill
feat/lof-path-absolute-align
feat/main-backtest-etf-daily-ready-gate
feat/mainmerge-indexhtml-detection
feat/mobile-a11y-font-touch
feat/mobile-a11y-font-touch-2
feat/mobile-ux-a11y-revert-v4
feat/netasset-daily-change-fix
feat/netasset-modal-ui
feat/netasset-peak-capital
feat/nextday-plan-idempotent-self-heal
feat/nextday-plan-signal-daily
feat/nextday-prev-close-stale-fix
feat/nextday-steps-enhance
feat/nextday-steps-enhance-design
feat/nextday-table-fix
feat/notify-cloud-fix
feat/ops-alert-denoise-lab-wait
feat/pending-drift-sweep
feat/prd-plan-fix98
feat/proxy-7key-p0
feat/remove-lab-slices
feat/schedule-monitor-launchctl-wording
feat/sdc-real-buy-fallback
feat/selfheal-limit-notify
feat/sigkelly-batch2
feat/sigkelly-diagnosis-intraday-view
feat/sigkelly-nav-async
feat/sigkelly-snapshot-fix
feat/sigkelly-y1-render
feat/stat-cross-platform-fix
feat/steps-reminder-view
feat/steps-reminder-view-i2
feat/systemd-logperm-rootfix
feat/systemd-purge-secret-envfile
feat/systemd-unit-generator
feat/systemd-units-20260912
feat/task-state-rootfix
feat/task-state-wiring
feat/turnover-watchdog-900
feat/upload-timeout-host-tag
feat/us-stock-morning-timeout-fix
worktree-agent-a0f60ab2e5c3165d0
worktree-agent-a2debb73039a12d75
worktree-agent-a2df69522522f8a8a
worktree-agent-a356651522eb38484
worktree-agent-a368c4cbab37900d1
worktree-agent-a4798fd2a7959ae10
worktree-agent-a4c65d2337668bbb9
worktree-agent-a50b676e72cde63c6
worktree-agent-a54e4faa567d1e381
worktree-agent-a65540680bd015fb5
worktree-agent-a6dbf2a91b3b66b3a
worktree-agent-a71cab2d1e3c67c91
worktree-agent-a848ddfbf28de8790
worktree-agent-a87b228ddc79c9e00
worktree-agent-a8eb698afafc24ff6
worktree-agent-a92c87e4ed8b8905f
worktree-agent-a9e873da14d776abe
worktree-agent-ac4feddbbb5b68da3
worktree-agent-ace3bb2e274bdbd7d
worktree-agent-acfb02eede3f5fd28
worktree-agent-ad0973943bca32662
worktree-agent-ad1430feccc125e0d
worktree-agent-ad5aef2cf169f840c
worktree-agent-adc4c89f5a1a36b8f
worktree-agent-ae0fdfea3fbe7ad3e
worktree-agent-ae7c9fef1b85a7869
worktree-agent-af7988e0c49e359f3
worktree-agent-af8b5d0aca7793aa2
```
### 2.2 本地被 worktree 占用 87 个(先 `git worktree remove` / prune 对应 worktree,再删分支)
```
codex/mobile-ux-a11y-overreach-v4
f4-bj-export
feat/aicutoff-g1xa
feat/alert-denoise-r2-timeout-recover
feat/alert-fix-ops-918
feat/at-step-modal-datetime-hover
feat/at-steps-hl-fix
feat/bandfix-a5x9
feat/batch-fix-109
feat/c8-fix-p1
feat/changelog-bump-sync-noise-fix
feat/codex-findings-fix3
feat/deploy-kelly-snapshots-upload
feat/fix-intraday-refresh
feat/fix555-changelog-y1progress
feat/gapcheck-multisource
feat/impl-lab-rcts-fix
feat/index-misfix
feat/intraday-tbl-i18n
feat/kelly-intraday-linked-filter
feat/kelly-netasset-natday
feat/kelly-nextday-toggle-91
feat/main-merge-weekend-safe-window
feat/migration-macos-linux-compat
feat/mobile-ux-fix-share-auth
feat/mobile-ux-revert-44px
feat/mobile-ux-sigkelly-6
feat/monitor-schedule-semantic-fix
feat/nav-lazy-loading
feat/nextday-bid-tip-optional
feat/nextday-gap-check-gen-side
feat/nextday-steps-backfill
feat/opt-baostock
feat/p0-1-pytest
feat/p0-nav-placeholder-defense
feat/perf-turnover-detach
feat/prd-plan-backend
feat/prd-plan-frontend
feat/proxy-followup
feat/proxy-rework
feat/quad-fix
feat/r2-upload-rootcause-fix
feat/reviewer-pack8-cleanup
feat/s06-log-notify-decouple
feat/sigkelly-progressive-y1
feat/sim-price-col
feat/sim-price-toggle
feat/third-fund-source
feat/toast-changelog-099
feat/two-gates-intraday
feat/ui-trade90-modal
fix-watcher-sync-git-refs
fix/cache-config-snapshot-git-add
worktree-agent-a219d9103d4b1627c
worktree-agent-a2487b9584b8938e8
worktree-agent-a25288cbf2680af4d
worktree-agent-a26a74266d9f40735
worktree-agent-a30946ddd9476ccb5
worktree-agent-a3896057723715f5e
worktree-agent-a3aee8750afcfabb3
worktree-agent-a412a26cc922e7b82
worktree-agent-a44b2b6f002cd5e4b
worktree-agent-a48e5380104bae591
worktree-agent-a591d683f9a0a6218
worktree-agent-a63e8bf066aa33621
worktree-agent-a6a748c22936c92de
worktree-agent-a6e9d436f500176e6
worktree-agent-a73ba501f326eb4c4
worktree-agent-a7cc32b5dc869a3fb
worktree-agent-a8d7a35c6e7acef8d
worktree-agent-a9254945d54db2998
worktree-agent-a954d7b52176cc106
worktree-agent-aa243d3b7da9c779d
worktree-agent-aa3e203556ebde98b
worktree-agent-aba28048fc7ee5a16
worktree-agent-abcce7e0afd16a504
worktree-agent-ac266f4b4ccaf7ff0
worktree-agent-acbff7a4a6d3f128b
worktree-agent-ad98823bc4c646fc9
worktree-agent-adb53c6e1774171c9
worktree-agent-ade982ae58a7a279c
worktree-agent-ae1d2d2748fce9934
worktree-agent-ae8f5e133a1e1566f
worktree-agent-inbox-rev-20260916-001
worktree-agent-inbox-rev-cachetest-20260915-001
worktree-agent-inbox-rev-test-20260915-001
worktree-agent-inbox-test-001
```
### 2.3 远端已合入 169 个(`git push origin --delete` 删除,风险高,需二次确认后再执行)
```
codex/fix-watcher-notify-race
codex/mobile-ux-a11y-overreach-v4
codex/review-skill-cx006-008
codex/reviewer
codex/site-review-sigkelly-20260917
codex/site-review-sigkelly-mobile-ux-v2
codex/site-review-sigkelly-mobile-ux-v3
codex/watcher-model-v41
docs/kelly-stall-report
feat/a11y-cleanup-v5
feat/accum-nav-check-since-return-fix
feat/aicutoff-g1xa
feat/alert-denoise-r2-timeout-recover
feat/alert-fix-ops-918
feat/alert-noise-rootfix
feat/at-step-modal-datetime-hover
feat/at-steps-hl-done-focus
feat/at-steps-hl-fix
feat/at-steps-sell-rows
feat/atomic-write-sweep
feat/atomic-write-trades-fix
feat/bandfix-a5x9
feat/baostock-10001001-reconnect
feat/batch-fix-109
feat/c8-fix-p1
feat/changelog-bump-sync-noise-fix
feat/claude-md-refactor
feat/cloud-arch-separation
feat/cloud-finalize-fix
feat/cloud-path-hardcode-fix
feat/cloud-sync-after-merge
feat/codex-findings-fix3
feat/collab-standard
feat/decommission-r2-20260903
feat/deploy-git-fetch-timeout-20260915
feat/deploy-kelly-snapshots-upload
feat/deploy-nonblock-boardmap
feat/deploy-push-timeout
feat/eastmoney-turnover-baostock
feat/evo-fix
feat/evo-hover-fix
feat/feishu-follow-group
feat/fix-159880-nextday-gate
feat/fix-ci-download-skip
feat/fix-cloud-single-repo-path
feat/fix-intraday-refresh
feat/fix-kelly-stagnation-weekend
feat/fix-monitor-overview-lag
feat/fix-overfit-monitor-real-buy-date
feat/fix-ovf-parity-c-window
feat/fix-r2-upload-timeout-systemic
feat/fix-timeout-fetch-news-ab-anchor
feat/fix555-changelog-y1progress
feat/frontend-steps-slot-render-order
feat/gap-check
feat/gapcheck-date-freshness
feat/gapcheck-fail-r2
feat/gapcheck-multisource
feat/homepage-signal-trend-fix
feat/homepage-trend-backfill-badge
feat/impl-lab-rcts-fix
feat/index-misfix
feat/intraday-realprice-trade90
feat/intraday-tbl-i18n
feat/kelly-freeze-timespot-rootfix-20260918
feat/kelly-intraday-linked-filter
feat/kelly-intraday-rerun
feat/kelly-netasset-natday
feat/kelly-netasset-vol-curve
feat/kelly-rootfix-345
feat/kelly-unique-export
feat/kelly-unique-parts
feat/krating-data-driven
feat/local-audit-clean
feat/lof-field-filter-nav-backfill
feat/lof-path-absolute-align
feat/main-backtest-etf-daily-ready-gate
feat/main-merge-weekend-safe-window
feat/mainmerge-indexhtml-detection
feat/mobile-a11y-font-touch
feat/mobile-a11y-font-touch-2
feat/mobile-ux-a11y-revert-v4
feat/mobile-ux-revert-44px
feat/mobile-ux-sigkelly-6
feat/monitor-schedule-semantic-fix
feat/nav-lazy-loading
feat/netasset-daily-change-fix
feat/netasset-modal-ui
feat/netasset-peak-capital
feat/nextday-bid-tip-optional
feat/nextday-gap-check-gen-side
feat/nextday-plan-idempotent-self-heal
feat/nextday-plan-signal-daily
feat/nextday-prev-close-stale-fix
feat/nextday-steps-backfill
feat/nextday-steps-enhance
feat/nextday-steps-enhance-design
feat/nextday-table-fix
feat/notify-cloud-fix
feat/ops-alert-denoise-lab-wait
feat/opt-baostock
feat/p0-1-pytest
feat/p0-nav-placeholder-defense
feat/perf-turnover-detach
feat/prd-plan-backend
feat/prd-plan-fix98
feat/prd-plan-frontend
feat/proxy-7key-p0
feat/proxy-followup
feat/proxy-rework
feat/quad-fix
feat/r2-upload-rootcause-fix
feat/remove-lab-slices
feat/reviewer-pack8-cleanup
feat/s06-log-notify-decouple
feat/schedule-monitor-launchctl-wording
feat/sdc-real-buy-fallback
feat/selfheal-limit-notify
feat/sigkelly-batch2
feat/sigkelly-diagnosis-intraday-view
feat/sigkelly-nav-async
feat/sigkelly-progressive-y1
feat/sigkelly-silent-fill
feat/sigkelly-snapshot-fix
feat/sigkelly-y1-render
feat/sim-price-col
feat/sim-price-toggle
feat/stat-cross-platform-fix
feat/steps-reminder-view
feat/systemd-logperm-rootfix
feat/systemd-purge-secret-envfile
feat/systemd-unit-generator
feat/systemd-units-20260912
feat/task-state-rootfix
feat/task-state-wiring
feat/third-fund-source
feat/toast-changelog-099
feat/turnover-watchdog-900
feat/two-gates-intraday
feat/ui-trade90-modal
feat/upload-timeout-host-tag
feat/us-stock-morning-timeout-fix
worktree-agent-a219d9103d4b1627c
worktree-agent-a2487b9584b8938e8
worktree-agent-a25288cbf2680af4d
worktree-agent-a26a74266d9f40735
worktree-agent-a2df69522522f8a8a
worktree-agent-a30946ddd9476ccb5
worktree-agent-a3896057723715f5e
worktree-agent-a3aee8750afcfabb3
worktree-agent-a412a26cc922e7b82
worktree-agent-a44b2b6f002cd5e4b
worktree-agent-a48e5380104bae591
worktree-agent-a591d683f9a0a6218
worktree-agent-a63e8bf066aa33621
worktree-agent-a6e9d436f500176e6
worktree-agent-a73ba501f326eb4c4
worktree-agent-a7cc32b5dc869a3fb
worktree-agent-a8d7a35c6e7acef8d
worktree-agent-a954d7b52176cc106
worktree-agent-aa243d3b7da9c779d
worktree-agent-abcce7e0afd16a504
worktree-agent-ac266f4b4ccaf7ff0
worktree-agent-acbff7a4a6d3f128b
worktree-agent-ad98823bc4c646fc9
worktree-agent-adb53c6e1774171c9
worktree-agent-ade982ae58a7a279c
worktree-agent-ae1d2d2748fce9934
worktree-agent-ae8f5e133a1e1566f
```

## 三、B 类清单(有未合入 commit,需人工判断保留/合入后删)
| 分支 | 未合入数 | 最后commit | 主题 |
|---|---|---|---|
| codex/fix-watcher-sync-git-refs | 1 | 2026-09-07 | fix(codex-watcher): .failed retry no longer blocked by sync_git_refs skip |
| feat/kelly-unique-appjs | 6 | 2026-09-21 | docs(kelly-unique Phase D): 落档 §9 消费方脚本改读记录(10 脚本各 1 行改法 + 自测结果) |
| feat/launchd-cloud-cutover-fallback | 1 | 2026-09-13 | ops(launchd): 阶段4c 停本机35业务任务兜底脚本(restore+manual) |
| feat/nextday-plan-fix | 2 | 2026-09-10 | fix(nextday_plan): 空数组展开改 ${GEN_ARGS[@]+"${GEN_ARGS[@]}"} 兼容 set -u + bash 3.2 |
| feat/p0-nav-placeholder-fix | 1 | 2026-09-09 | fix(p0-nav): 清除 etf_daily 20260908 accum_nav=1.5 占位污染+复盘落档 |
| research/fapi-h-k1 | 7 | 2026-09-02 | feat(fapi): P2 盘中延迟实测完成(238轮, 秒级实时档可兜底) |
| worktree-agent-a550f7036cd5b2469 | 2 | 2026-09-04 | docs(beijiao-width): 实施说明落档(§23.5 四件套)+README 功能亮点补北交所宽度卡 |
| worktree-agent-a7ea16ffefe0db35c | 1 | 2026-09-12 | fix(scripts): 迁移 feat review 4 项修复(F1回退备份治理/F2 unit命名/F3 activating映射/F4 systemctl真值源) |
| zcode/standin-charter | 1 | 2026-09-03 | docs(zcode-standin): 章程新增ZCode专属分支纪律——所有产出走zcode/*分支,禁止直接commit/push main |
| zcode/test-report-20260903 | 1 | 2026-09-03 | test(回归): 首份全量回归报告(PASS12/FAIL3/SKIP14)——watcher测试未跟重构/S1键谓词2行差异/export_manifest环境FAIL/含S06防前视抽验PASS |

### 远端独有 B 类(本地没有对应分支)
| 分支 | 未合入数 | 最后commit | 主题 |
|---|---|---|---|
| feat/cloud-systemd-path-fix | 1 | 2026-09-13 | fix(systemd): 单仓路径 /opt/trade → /home/ubuntu/code/trade-data-signal + 全量注入 MAIN_REPO(阶段4b) |

## 四、C 类(疑似废弃)
0 个。注: worktree-agent-a7ea16ffefe0db35c 与远端 feat/migration-macos-linux-compat **指向同一 commit**(0f74629c99),是同一份「迁移 review 4 项修复」的两个分支载体,属疑似重复,归入 B 类待人工确认。

## 五、worktree 映射表(97 个含主)
| 路径 | 分支 | 目录存在 | 标记 | 判定 |
|---|---|---|---|---|
| /Users/linhuichen/code/trade | main | YES | - | 主 worktree(保留) |
| /private/tmp/wt-backfill-impl | feat/nextday-steps-backfill | YES | prunable | 半幽灵(目录在但无.git,残留可清) |
| /private/tmp/wt-evo-fix | feat/evo-fix | NO | prunable | 幽灵(目录不存在) |
| /private/tmp/wt-gap-fix | feat/gap-check | NO | prunable | 幽灵(目录不存在) |
| /private/tmp/wt-increment | feat/kelly-intraday-linked-filter | YES | prunable | 半幽灵(目录在但无.git,残留可清) |
| /private/tmp/wt-lab-rcts-fix | feat/impl-lab-rcts-fix | YES | prunable | 半幽灵(目录在但无.git,残留可清) |
| /private/tmp/wt-monitor-semantic-fix | feat/monitor-schedule-semantic-fix | YES | - | 正常(分支分类见二/三) |
| /private/tmp/wt-nextday-table-fix | feat/nextday-table-fix | NO | prunable | 幽灵(目录不存在) |
| /private/tmp/wt-prd-plan-fix98 | feat/prd-plan-fix98 | NO | prunable | 幽灵(目录不存在) |
| /private/tmp/wt-quad-fix | feat/quad-fix | YES | prunable | 半幽灵(目录在但无.git,残留可清) |
| /private/tmp/wt-safe-window | feat/main-merge-weekend-safe-window | YES | - | 正常(分支分类见二/三) |
| /private/tmp/wt-step-enhance | feat/nextday-steps-enhance | NO | prunable | 幽灵(目录不存在) |
| /private/tmp/wt-trend-fix | feat/homepage-signal-trend-fix | NO | prunable | 幽灵(目录不存在) |
| /private/tmp/wt-two-gates | feat/two-gates-intraday | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a1461d99c44405772 | feat/nextday-bid-tip-optional | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a219d9103d4b1627c | worktree-agent-a219d9103d4b1627c | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a2487b9584b8938e8 | worktree-agent-a2487b9584b8938e8 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a25288cbf2680af4d | worktree-agent-a25288cbf2680af4d | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a26a74266d9f40735 | worktree-agent-a26a74266d9f40735 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a2debb73039a12d75 | feat/gapcheck-multisource | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a30946ddd9476ccb5 | worktree-agent-a30946ddd9476ccb5 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a368c4cbab37900d1 | f4-bj-export | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a3896057723715f5e | worktree-agent-a3896057723715f5e | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a3aee8750afcfabb3 | worktree-agent-a3aee8750afcfabb3 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a412a26cc922e7b82 | worktree-agent-a412a26cc922e7b82 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a4317659dca9e2d02 | feat/nextday-gap-check-gen-side | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a44b2b6f002cd5e4b | worktree-agent-a44b2b6f002cd5e4b | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a4798fd2a7959ae10 | fix/cache-config-snapshot-git-add | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a48e5380104bae591 | worktree-agent-a48e5380104bae591 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a50b676e72cde63c6 | feat/alert-denoise-r2-timeout-recover | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a54e4faa567d1e381 | feat/s06-log-notify-decouple | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a550f7036cd5b2469 | worktree-agent-a550f7036cd5b2469 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a591d683f9a0a6218 | worktree-agent-a591d683f9a0a6218 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a63e8bf066aa33621 | worktree-agent-a63e8bf066aa33621 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a65540680bd015fb5 | feat/mobile-ux-revert-44px | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a6a748c22936c92de | worktree-agent-a6a748c22936c92de | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a6e9d436f500176e6 | worktree-agent-a6e9d436f500176e6 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a73ba501f326eb4c4 | worktree-agent-a73ba501f326eb4c4 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a7cc32b5dc869a3fb | worktree-agent-a7cc32b5dc869a3fb | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a7ea16ffefe0db35c | worktree-agent-a7ea16ffefe0db35c | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a87b228ddc79c9e00 | feat/r2-upload-rootcause-fix | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a8d7a35c6e7acef8d | worktree-agent-a8d7a35c6e7acef8d | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a8dbc67ee14a51e0e | feat/migration-macos-linux-compat | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a9254945d54db2998 | worktree-agent-a9254945d54db2998 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a92c87e4ed8b8905f | feat/alert-fix-ops-918 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-a954d7b52176cc106 | worktree-agent-a954d7b52176cc106 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-aa243d3b7da9c779d | worktree-agent-aa243d3b7da9c779d | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-aa3e203556ebde98b | worktree-agent-aa3e203556ebde98b | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-aba28048fc7ee5a16 | worktree-agent-aba28048fc7ee5a16 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-abcce7e0afd16a504 | worktree-agent-abcce7e0afd16a504 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-ac266f4b4ccaf7ff0 | worktree-agent-ac266f4b4ccaf7ff0 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-ac4feddbbb5b68da3 | feat/mobile-ux-sigkelly-6 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-acbff7a4a6d3f128b | worktree-agent-acbff7a4a6d3f128b | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-ace3bb2e274bdbd7d | feat/nav-lazy-loading | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-acfb02eede3f5fd28 | feat/reviewer-pack8-cleanup | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-ad0973943bca32662 | feat/at-steps-hl-fix | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-ad1430feccc125e0d | feat/at-step-modal-datetime-hover | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-ad5aef2cf169f840c | fix-watcher-sync-git-refs | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-ad98823bc4c646fc9 | worktree-agent-ad98823bc4c646fc9 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-adb53c6e1774171c9 | worktree-agent-adb53c6e1774171c9 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-adc4c89f5a1a36b8f | feat/intraday-tbl-i18n | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-ade982ae58a7a279c | worktree-agent-ade982ae58a7a279c | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-ae0fdfea3fbe7ad3e | feat/third-fund-source | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-ae1d2d2748fce9934 | worktree-agent-ae1d2d2748fce9934 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-ae7c9fef1b85a7869 | feat/deploy-kelly-snapshots-upload | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-ae8f5e133a1e1566f | worktree-agent-ae8f5e133a1e1566f | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-af7988e0c49e359f3 | feat/codex-findings-fix3 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-af8b5d0aca7793aa2 | feat/mobile-ux-fix-share-auth | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-baostock-speed | feat/opt-baostock | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-impl-52c | feat/kelly-netasset-natday | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-inbox-rev-20260916-001 | worktree-agent-inbox-rev-20260916-001 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-inbox-rev-cachetest-20260915-001 | worktree-agent-inbox-rev-cachetest-20260915-001 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-inbox-rev-test-20260915-001 | worktree-agent-inbox-rev-test-20260915-001 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-inbox-test-001 | worktree-agent-inbox-test-001 | YES | locked | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/agent-toast-changelog-099 | feat/toast-changelog-099 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/aicutoff-g1xa | feat/aicutoff-g1xa | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/bandfix2 | feat/bandfix-a5x9 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/batch-fix-109 | feat/batch-fix-109 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/c8-fix-p1 | feat/c8-fix-p1 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/codex-reviewer | codex/mobile-ux-a11y-overreach-v4 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/fix-f21 | (detached) | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/fix-intraday-refresh | feat/fix-intraday-refresh | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/fix555-changelog-progress | feat/fix555-changelog-y1progress | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/impl-47 | feat/p0-1-pytest | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/impl-91 | feat/kelly-nextday-toggle-91 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/impl-c8-noise | feat/changelog-bump-sync-noise-fix | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/index-misfix | feat/index-misfix | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/p0-nav-defense | feat/p0-nav-placeholder-defense | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/prd-plan-backend | feat/prd-plan-backend | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/prd-plan-frontend | feat/prd-plan-frontend | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/proxy-followup | feat/proxy-followup | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/proxy-rework | feat/proxy-rework | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/sigkelly-prog | feat/sigkelly-progressive-y1 | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/sim-price-col | feat/sim-price-col | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/sim-price-toggle | feat/sim-price-toggle | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/turnover-detach | feat/perf-turnover-detach | YES | - | 正常(分支分类见二/三) |
| /Users/linhuichen/code/trade/.claude/worktrees/ui-trade90 | feat/ui-trade90-modal | YES | - | 正常(分支分类见二/三) |

## 六、幽灵 worktree 清单(10 个, `git worktree prune` 即可清理注册)
| 路径 | 分支 | 状态 |
|---|---|---|
| /private/tmp/wt-backfill-impl | feat/nextday-steps-backfill | 目录存在但无.git(仅残留 data/) |
| /private/tmp/wt-evo-fix | feat/evo-fix | 目录不存在 |
| /private/tmp/wt-gap-fix | feat/gap-check | 目录不存在 |
| /private/tmp/wt-increment | feat/kelly-intraday-linked-filter | 目录存在但无.git(仅残留 static-site/) |
| /private/tmp/wt-lab-rcts-fix | feat/impl-lab-rcts-fix | 目录存在但无.git(残留 .agents/.claude/a-stock-data 等) |
| /private/tmp/wt-nextday-table-fix | feat/nextday-table-fix | 目录不存在 |
| /private/tmp/wt-prd-plan-fix98 | feat/prd-plan-fix98 | 目录不存在 |
| /private/tmp/wt-quad-fix | feat/quad-fix | 目录存在但无.git(仅残留 scripts/) |
| /private/tmp/wt-step-enhance | feat/nextday-steps-enhance | 目录不存在 |
| /private/tmp/wt-trend-fix | feat/homepage-signal-trend-fix | 目录不存在 |

## 七、最需人工判断的条目
1. **B 类 10 个本地分支**(见三):kelly-unique-appjs(6 commit,2 天前仍活跃,疑似未完成)、research/fapi-h-k1(7 commit,调研专用)、zcode/* 2 个(秘书角色章程+回归报告,章程分支纪律要求 zcode 产出走 zcode 分支)是否保留
2. **worktree-agent-a7ea16ffefe0db35c** = 远端 feat/migration-macos-linux-compat 同一 commit 的另一分支载体,确认后二者删一留一
3. **远端删除风险高**:169 个远端已合入分支删除前建议抽查 2-3 个远端有本地无的(A 类 feat/collab-standard、feat/sigkelly-silent-fill)确认合入状态
4. **codex/* 分支共 11 个**:8 个是 A 类,但属外审通道产物,2019 外审改点名制后是否保留由用户定
5. **agent-inbox-test-001** 带 `locked` 标记,删除前检查是手动 lock 还是残留

## 附录: 方法与校验证据
- git cherry 空输出 = 无未合入(抽查 feat/two-gates-intraday、feat/alert-noise-rootfix、feat/turnover-watchdog-900 均为空输出,符合已合入预期)
- main-merge.sh 用 merge 或 cherry-pick 合入(见 scripts/main-merge.sh 头部注释),无固定 merge 祖先,故不能用 --merged
- 幽灵 worktree 注册目录(.git/worktrees/wt-*)仍存在且 HEAD 指向分支,grow git 仍视分支被占用;先 prune 再删分支
- 本文件为只读分析产物,执行删除需用户确认后另行派单

