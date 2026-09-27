# 分支清理(2026-09-27):本地 87→4 / 远端 54→4

> 触发:用户发现「远端只有 15 个分支,本地怎么有 85 个之多」→ 核实为 GitHub 页面未刷新(刷新后远端确为 54),但**本地/远端确实长期积压**,遂做全量清理。
>
> §23.5 四件套:本报告(本体)+ 删除前备份清单 `docs/ops/branch-cleanup-backup-20260927.txt` + 复现段(见文末)+ 配套 commit。

## 1. 积压根因

**每次 `isolation: worktree` 派 agent 会自动建一个 `worktree-agent-<hash>` 分支**;活干完 merge 进 main、worktree 目录清理掉了,但**分支留在本地没人推没人删**。本次 87 个本地分支里有 **50 个**是这类一次性壳。

## 2. 判定口径(🔴 这里最容易错)

**禁用裸 `git branch --merged main` 当结论**——squash merge 后 commit hash 变了、也不再是 main 的祖先,`--merged` 会把「内容早已进 main」的分支误判成「未合并」。(此前踩过,见 memory `git-batch-delete-branches`。)

实际判据:

| 步骤 | 判据 | 结论 |
|---|---|---|
| 先跑 `git worktree list` | 被 worktree 占用的分支 | **绝对不能删**(本次 `codex/mobile-ux-a11y-overreach-v4` 被 `.claude/worktrees/codex-reviewer` 占着) |
| `git rev-list --count main..<br>` | = 0 | tip 已是 main 祖先,纯壳,内容 100% 在 main → 可删 |
| 非 0 | 逐分支抽「可 grep 标识符」(文件名/函数名/中文串)去 main 上核 | 全命中 = squash 已入 main → 可删;**有未命中 = 有 main 里没有的东西 → 归「需人工」** |
| blob 逐字节 | `git rev-parse <br>:<p>` == `git rev-parse main:<p>` | 独有 commit 只改了与 main 逐字节一致的文档 → 可删 |

**保守原则:拿不准一律归「需人工」,不替用户拍板。**

## 3. 总账

| | 本地 87 | 远端 54 |
|---|---|---|
| ①可安全删 | 76 | 41 |
| ②需人工 | 9 | 11(9 同名 + 2 远端独有) |
| ③不可删 | 2 | 2 |
| **清理后** | **4** | **4** |

保留的 4 条:`main`、`codex/mobile-ux-a11y-overreach-v4`(worktree 占用)、`codex/reviewer`、`zcode/standin-charter`(后两条是 codex / ZCode 协作命名约定,后续会复用)。

## 4. ①类为什么可安全删(76 个的三块证据)

- **A. unique=0 纯壳 69 个**:`main..<br>` 计数 = 0,tip 已是 main 祖先 → commit 本身就在 main 历史里,永久保留。
- **B. unique=1 但独有文档与 main 逐字节一致 6 个**:如 `worktree-agent-a13e6a52752824cbe` 独有的 `docs/ops/alert-noise-evidence-20260924.md`,其 blob ID 与 main 上的同名文件**完全相同**(`git rev-parse` 对比 IDENTICAL)。
- **C. `feat/nextday-plan-fix` 1 个**:修 `${GEN_ARGS[@]:-}` 空数组展开 bug,main 上 `0e4a5f2b9`(2026-09-10)已用 `if [ "${#GEN_ARGS[@]}" -gt 0 ]` 修得**更彻底**,修复目标 100% 在 main。

## 5. ②类的存档机制:用 git 标签,不用「拷文件进 main」

**决定:`git tag archive/20260927/<原分支名> <tip>`(轻量标签),9 条。**

为什么不用「把独有文件 `git show` 出来拷进 main」:

1. **有覆盖风险**:`codex/fix-watcher-sync-git-refs` 的独有改动是 `scripts/agent_inbox_watcher.py`,而 **main 上该文件有更新版**(4 状态机 + 保留 REVIEWER_MODEL/failed_at 退避,分支的 2 状态方案未被采纳)——拷进去会**覆盖 main 的现行实现**。
2. **保真度更高**:标签保留**整条分支历史**,而不是我只挑出来的那几个「NO-MAIN 文件」。
3. **可原样复活**:`git checkout -b <原分支名> archive/20260927/<原分支名>`。
4. **零运行风险**:全仓 `grep -rn "git tag" scripts/ app/` = **空**,没有任何脚本消费 tag,不干扰版本号机制。

相对的代价只是仓库多 9 个 `archive/` 命名空间的 ref(与 `v1.1.x` 版本标签不同前缀,不冲突)。

9 条标签(每条对应分支 tip):

| tag | sha | 原分支的独有内容 |
|---|---|---|
| `archive/20260927/research/fapi-h-k1` | `bd94b227f` | 12 独有 commit;k1 名次偏移回测脚本(681 行)+ csi1000 可行性报告+脚本 + 夜盘汇总等 5 文件未入 main |
| `archive/20260927/feat/kelly-unique-appjs` | `26eadc993` | 6 独有 commit;`check_kelly_unique_lab_parity.mjs` 对账脚本 + 3 个 playwright 快照脚本 + json + r2 上传失败调研报告未入 main |
| `archive/20260927/zcode/test-report-20260903` | `04593ef22` | zcode 阶段回归报告(PASS12/FAIL3/SKIP14)未入 main |
| `archive/20260927/feat/branch-cleanup-20260923` | `797359685` | 383 条分支/worktree 删除前备份清单未入 main |
| `archive/20260927/feat/launchd-cloud-cutover-fallback` | `63cc62d1b` | `restore-launchd.sh` / `run-task-manually.sh` 兜底脚本未入 main(launchd 已废弃) |
| `archive/20260927/feat/p0-nav-placeholder-fix` | `7de5e5764` | nav 占位污染清理报告 + `fix_etf_daily_nav_placeholder.py` 未入 main |
| `archive/20260927/codex/fix-watcher-sync-git-refs` | `618e9d660` | watcher 的独立修复形态(main 用不同方案达成同目标,**故未拷文件,只留标签**) |
| `archive/20260927/feat/cloud-systemd-path-fix` | `820feacec` | 单仓路径方案,main 已演进为分离架构版(方案被反转+迭代) |
| `archive/20260927/worktree-agent-a550f7036cd5b2469` | `c5ea51a2a` | 北交所宽度旧名实现 `beijiao_width.py` + 实施文档 + launchd plist(功能已改名 `bj_width.py` 合入 main) |

## 6. 执行步骤(顺序不能换)

1. **先打标签**(本地 7 条 + 远端独有 2 条 `git fetch origin refs/heads/X:refs/tags/archive/...`)——**必须在删分支之前**,否则对象失去引用
2. 生成删除前全量备份清单(name|sha|独有 commit 数,本地 87 + 远端 54 + 标签 9)→ commit 进 main
3. **推标签到远端**(先于删远端分支——`cloud-systemd-path-fix` / `a550f7036cd5b2469` 两条远端独有分支的内容只在远端,不推标签就删=真丢)
4. 删本地 83 条(`git branch -D`)
5. 删远端 50 条(`git push origin --delete`)
6. 终态核对:本地 4 / 远端 4 / 标签 9 / 备份清单在库

## 7. 复现段

**重新判定(只读)**:

```bash
git worktree list                                   # 先排除占用分支
git for-each-ref --format='%(refname:short)|%(objectname)' refs/heads/   # 本地全量
git ls-remote --heads origin                        # 远端全量
git rev-list --count main..<br>                     # 独有 commit 数;=0 即纯壳
git rev-parse <br>:<path>; git rev-parse main:<path> # blob 逐字节比对
git cat-file -e main:<path>                         # 该路径是否在 main 树里
```

**恢复任意已删分支**:

```bash
# ②类(有标签):按原分支名原样复活
git checkout -b <原分支名> archive/20260927/<原分支名>
# ①类 / 未打标签的:用备份清单里的 sha(对象在 reflog / gc 前可捞)
grep '<分支名>' docs/ops/branch-cleanup-backup-20260927.txt
git branch <分支名> <sha>
```

**撤销标签**(若将来认为不需要):

```bash
git tag -d archive/20260927/<原分支名> && git push origin :refs/tags/archive/20260927/<原分支名>
```

## 8. 关联

- 审计依据:全量只读审计报告(本地 87 + 远端 54 逐条判定,含 blob 比对与改名替代扫描);交叉佐证 `docs/ops/worktree-audit-20260925.md`
- 同类先例:`docs/ops/branch-delete-backup-20260923.txt`(383 条)、memory `git-batch-delete-branches`(`--merged` 误判教训)
- memory:`concurrent-implementers-worktree-isolation`(worktree 隔离)、`resume-same-task-reuse-branch`(分支身份漂移)
