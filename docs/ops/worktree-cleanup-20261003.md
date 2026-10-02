# Worktree 清理报告(2026-10-03)

> 任务:清理本仓残留 agent worktree + 已合并分支,用户 2026-10-03 授权清收尾。全部删除动作严格走 §25 铁律(先备份到可独立恢复副本 → 验过 → 删)。

## 0. 执行目标与结果一句话

- **删除了 13 个已合并分支的残留 worktree**(每个约 126M,释放约 **1.7G**),外加把 `zcode/standin-charter` 分支独有段归档到 docs/。
- **保留了**全部 locked worktree(锁进程 pid 38456 = `claude --resume` **仍存活**,属「当前可能在使用」,且其中 `a780922` 含**未提交的 P0 export-guard 代码**)、全部 NOT-MERGED 分支的 worktree。
- 未删任何分支引用、未 merge、未 push main;全程未静默吞事件。

## 一.1 磁盘占用对比

| 指标 | 清理前 | 清理后 |
|---|---|---|
| worktree 数量(含主工作区) | 31 | 18 |
| `.claude/worktrees/` 磁盘占用 | 约 3.8G(约30个) | 2.1G(17个) |
| 释放 | — | 约 1.7G |

> 预清理占用未在删除前 du 记录(任务口径「约3.2G」为先前盘点),本报告以删除后 2.1G + 删除 13 个×~126M 推算。

## 2. 盘点全表(每个 worktree / 分支 → 判定 → 动作 → 证据)

判定方法:每 worktree 用 `git status --porcelain` 判 dirty;本地分支用 `git merge-base --is-ancestor <分支> origin/main`(==MERGED)判是否已合入;NOT-MERGED 分支查 `origin/main..分支` 未合入 commit;内容对比用 blob hash(`git rev-parse 分支:路径` vs `origin/main:路径`,非三点 diff)。

| # | worktree | 分支 | locked | dirty | 合并判定 | 动作 | 证据 |
|---|---|---|---|---|---|---|---|
| 1 | /trade (主) | main | — | 0 | — | **不碰** | 主工作区 |
| 2 | agent-a01716f9c4489a301 | worktree-agent-a01716... | LOCKED | 0 | MERGED | **保留(locked)** | pid38456 存活 |
| 3 | agent-a09d991351b5b1300 | feat/cf-egress-probe | — | 0 | NOT-MERGED | **保留** | ahead=1 |
| 4 | agent-a0b7e692af78b2ef3 | worktree-agent(本任务) | LOCKED | 0 | migrated | **保留(本任务自身)** | 任务自身 worktree |
| 5 | agent-a0c6da07deae45237 | feat/icepoint-source-groups | — | 0 | NOT-MERGED | **保留** | ahead=1 |
| 6 | agent-a0ef0a0b2e02c6903 | feat/r2-billing-4usd50 | — | 0 | NOT-MERGED | **保留** | ahead=1 |
| 7 | agent-a11cb4fb71521c66c | worktree-agent(并行切 to feat/futures-pos...) | LOCKED | 0 | migrated | **保留(locked)** | 锁进程并行在用 |
| 8 | agent-a23d9492760cfd76d | (detached HEAD b0836524e) | — | 1 | 孤儿commit | ✅**删** | 孤儿 commit,main 更完整;patch 已备份;含 untracked review 文档已备份 |
| 9 | agent-a388e66389260da74 | feat/r2-billing-research | — | 0 | NOT-MERGED | **保留** | ahead=1 |
| 10 | agent-a45e08728ec92e53f | worktree-agent-a45e | — | 1 | migrated | ✅**删** | UNTRACKED review2 文档已备份 |
| 11 | agent-a5622e1883dac9dd4 | feat/icepoint-consensus-review | — | 0 | NOT-MERGED | **保留(⛔禁merge)** | 含旧版生产代码,独有3 commit |
| 12 | agent-a578df4331fee2c08 | feat/r2-mac-backups-restore | — | 0 | migrated | ✅**删** | 已合入 |
| 13 | agent-a6b711a421079a130 | feat/help-dblclick | LOCKED | 0 | migrated | **保留(locked)** | pid38456 存活 |
| 14 | agent-a705582e7ba802b26 | feat/queries-except-logging | — | 0 | migrated | ✅**删** | 已合入 |
| 15 | agent-a7329add85c12b336 | worktree-agent-a7329 | — | 0 | migrated | ✅**删** | 已合入 |
| 16 | agent-a7809227903882f4b | worktree-agent-a78092... | LOCKED | 2(!!) | migrated | **保留(locked+未提交P0代码)** | `M scripts/upload_r2.py` + `M static-site/export.py` = 未提交的 export-guard P0 防误传代码,**已备份但绝不可删** |
| 17 | agent-a782b4423d5522338 | worktree-agent-a782b | LOCKED | 0 | migrated | **保留(locked)** | pid38456 存活 |
| 18 | agent-a7f6f2c90f1b79893 | feat/icepoint-legend-text | — | 0 | migrated | ✅**删** | 已合入 |
| 19 | agent-a814025345990cccf | worktree-agent-a8140 | — | 0 | NOT-MERGED | **保留** | ahead=1 |
| 20 | agent-aa83f3a3efeff690e | feat/icepoint-consensus-front-review | — | 0 | NOT-MERGED | **保留(⛔禁)** | 含旧版生产代码,独有7 commit |
| 21 | agent-aac34f6825996b5c4 | feat/holiday-wrapup-docs | — | 0 | migrated | ✅**删** | 已合入 |
| 22 | agent-aaec35b8e37b4e868 | feat/pf-nav-clobber-fix | — | 0 | migrated | ✅**删** | 已合入 |
| 23 | agent-ab98f5d739f81c907 | feat/149a-deploy-lock-split-review | — | 0 | NOT-MERGED | **保留** | review 分支 ahead=1 |
| 24 | agent-ac2f40c2ba03f0130 | feat/149a-deploy-git-lock | — | 0 | migrated | ✅**删** | 已合入 |
| 25 | agent-ac562449df83a621b | worktree-agent-ac562 | LOCKED | 0 | migrated | **保留(locked)** | pid38456 存活 |
| 26 | agent-ac735ad5463e2ade2 | worktree-agent-ac735 | — | 1 | migrated | ✅**删** | UNTRACKED emintraday review 文档已备份 |
| 27 | agent-adc0fbf873353a6d5 | feat/harden-alerts | — | 0 | migrated | ✅**删** | 已合入 |
| 28 | agent-ae2f7cfb35006f345 | feat/emintraday-denoise | — | 1 | migrated | ✅**删** | UNTRACKED `_dbg_f2_probe.mjs` 调试探针,已备份 |
| 29 | agent-ae8445feaaa1615ec | feat/r2-bucket-capacity | — | 0 | NOT-MERGED | **保留** | ahead=1 |
| 30 | agent-afcb2fa189b969a04 | worktree-agent-afcb2 | — | 1 | migrated | ✅**删** | UNTRACKED navclobber-review 文档已备份 |
| 31 | rev-harden-2 | feat/harden-alerts-review | — | 0 | NOT-MERGED | **保留** | ahead=1 |

## 3. 删了什么、各附「怎么恢复」

全部删除对象在删除前已备份到 `/tmp/worktree-cleanup-backup-20261003/`。删除对象信息:

| worktree | 删除的独有文件 | 备份位置 | 怎么恢复 |
|---|---|---|---|
| agent-a23d9492760cfd76d | `docs/ops/icepoint-legend-tip-review-20261002.md` + 孤儿 detached commit b0836524e(app.js 补丁) | `a23d949-*.md` + `orphan-b0836524e.patch` | 从 `/tmp/worktree-cleanup-backup-20261003/` 拷回;孤儿 commit 用 `git apply orphan-b0836524e.patch` |
| agent-a45e08728ec92e53f | `docs/ops/icepoint-legend-tip-review2-20261002.md` | `a45e087-*.md` | 拷贝回 docs/ops/ |
| agent-a578df4331fee2c08 | —(已合入,无独有) | — | 内容已在 origin/main |
| agent-a705582e7ba802b26 | —(已合入) | — | 已在 main |
| agent-a7329add85c12b336 | —(已合入) | — | 已在 main |
| agent-a7f6f2c90f1b79893 | —(已合入) | — | 已在 main |
| agent-aac34f6825996b5c4 | —(已合入) | — | 已在 main |
| agent-aaec35b8e37b4e868 | —(已合入) | — | 已在 main |
| agent-ac2f40c2ba03f0130 | —(已合入) | — | 已在 main |
| agent-ac735ad5463e2ade2 | `docs/ops/emintraday-denoise-review-20261002.md` | `ac735ad-*.md` | 拷贝回 docs/ops/ |
| agent-adc0fbf873353a6d5 | —(已合入) | — | 已在 main |
| agent-ae2f7cfb35006f345 | `scripts/playwright-accept/_dbg_f2_probe.mjs` | `ae2f7cf/_dbg_f2_probe.mjs` | 拷贝回 `scripts/playwright-accept/` 原路径 |
| agent-afcb2fa189b969a04 | `docs/ops/navclobber-review-20261003.md` | `afcb2fa-navclobber-review-20261003.md` | 拷贝回 docs/ops/ |

**备份完整性验证**:`/tmp/worktree-cleanup-backup-20261003/` 备份内容清单如下(删除的每一份独有未提交文件均能对应):
- `a23d949-icepoint-legend-tip-review-20261002.md`
- `a45e087-icepoint-legend-tip-review2-20261002.md`
- `ac735ad-emintraday-denoise-review-20261002.md`
- `afcb2fa-navclobber-review-20261003.md`
- `ae2f7cf/_dbg_f2_probe.mjs`(子目录)
- `a780922/`(子目录:upload_r2.py + export.py + export-guard.diff,此为保留未删,P0 代码备份)
- `orphan-b0836524e.patch`(孤儿 detached commit b0836524e 的 app.js 补丁)

## 4. 没删什么、为什么

1. **7 个 locked worktree**(a01716/a0b7e692/本任务/a11cb4/a6b711/a780922/a782b/ac562):所有 locked 锁文件内容均指向 **pid 38456 (claude --resume,start 2026-09-17)**,该进程**仍存活**,属「当前可能正在使用」→ 按任务 §四4「当前在用→不碰」**全部保留**。已逐个 cat locked 文件核实。
2. **agent-a7809227903882f4b**:locked 且工作区有 **2 个未提交的代码改动**(`scripts/upload_r2.py` +39 行、`static-site/export.py` +53 行),内容为「2026-10-03 export-guard L0/L2 根治本机误传 R2 事故」的 P0 安全防护,**未提交到任何分支、HEAD 就是 main** → 该 worktree 若删即永久丢失。**绝不可删**,已完整备份到 `/tmp/worktree-cleanup-backup-20261003/a780922/`(upload_r2.py + export.py + export-guard.diff),**并强烈建议主控把它提交入库**(这批 P0 防误传代码当前只存在于该 worktree 工作区)。
3. **NOT-MERGED 分支的 worktree**(15 个):未合入 main 有独有 commit,按任务「有未合并 commit→不删,列报告」保留。含⛔禁止 merge 的两个 `feat/icepoint-consensus-*`(旧版生产代码,合入会倒退)。
4. **分支引用本身全部未删**(包括已合并分支也未删分支 ref,只删了 worktree)→ 符合「不删分支引用」「不 merge」。

## 5. locked 的处置

- locked 文件位于 `.git/worktrees/<name>/locked`,内容全部为同一格式:
  `claude agent agent-<hash> (pid 38456 start Thu Sep 17 14:26:21 2026)`
- 进程 `ps -p 38456` → `ALIVE: claude --resume`(主会话,仍开着)→ 判定「当前在用」,locked worktree 全部**不触碰、不删除**。未解锁任何 locked。

## 6. 最终 git worktree list

```
/Users/linhuichen/code/trade                                            11073b291 [main]
/trade/.claude/worktrees/agent-a01716f9c4489a301  8723a64a2 [worktree-agent-a01716...] locked
... 见上表保留的 17 个 ...
```
(最终保留的 17 个 worktree 见第 2 表「保留」各行。)

## 7. 遗留建议给主控 / 用户

1. **agent-a780922 的 P0 export-guard 代码**落在未提交工作区,强烈建议尽快让它单独落一个 feat 分支 commit + merge main,别长期躺 worktree 未提交。
2. locked 的 7 个 worktree 因锁进程(主会话)存活保留;若确定主会话不再需要,可先 `git worktree lock --force --reason` 或由用户确认后 unlock+清,释放剩余 ~0.9G。
3. NOT-MERGED 分支(尤其两个 consensus review)如需长期保留作为对照,建议归档分支内容到 docs 后按需清理,避免继续占磁盘。

## 怎么本报告

- 本报告本身在 `docs/ops/worktree-cleanup-20261003.md`,随本 commit 推 feat 分支。
- 删除对象恢复路径见第 3 节各「怎么恢复」。