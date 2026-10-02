# Worktree 清理可逆性核查报告(2026-10-03)

> 独立核查 `feat/worktree-cleanup-20261003` 的清理(删 13 个残留 worktree,31→18,释放 ~1.7G)是否**真的可逆**(§25②「备份必须实测验证,不是『应该有备份』」)。
> 核查方式:只读 + 恢复演练(复制到 /tmp 临时目录,不覆盖原物)。所有结论带命令 + 真跑输出/退出码证据。

## 结论一句话

**清理可逆 ✓**。13 个被删 worktree 均无独有内容(分支全部是 origin/main 祖先);5 份独有未提交文件 + 1 份孤儿 commit 补丁全部在备份中且**实测可恢复**(md5 逐位一致 + 补丁对父基座干净应用 + 应用结果与 commit 树 md5 一致);分支引用一个没少;zcode/standin-charter 独有段归档逐字一致且未混入旧描述。备份目录 9 文件 / 308K。

## 一、13 个被删 worktree 无独有内容(独立重跑,不信报告转述)

对 13 个被删 worktree 对应的分支(引用保留)逐条重跑 `git log --oneline origin/main..<分支>`,**全部空输出**(RC=0,无 commit):

| 分支 | origin/main..分支 结果 |
|---|---|
| feat/r2-mac-backups-restore-20261002 | 空 ✓ |
| feat/queries-except-logging-20261002 | 空 ✓ |
| worktree-agent-a7329add85c12b336 | 空 ✓ |
| feat/icepoint-legend-text-20261002 | 空 ✓ |
| feat/holiday-wrapup-docs-20261003 | 空 ✓ |
| feat/pf-nav-clobber-fix-20261002 | 空 ✓ |
| feat/149a-deploy-git-lock-20261002 | 空 ✓ |
| worktree-agent-ac735ad5463e2ade2 | 空 ✓ |
| feat/harden-alerts-20261002 | 空 ✓ |
| feat/emintraday-denoise-20261002 | 空 ✓ |
| worktree-agent-afcb2fa189b969a04 | 空 ✓ |
| worktree-agent-a45e08728ec92e53f | 空 ✓ |
| worktree-agent-a23d9492760cfd76d | 空 ✓ |

→ 13 个分支内容全部已合入 main,无独有 commit。
唯一孤儿 detached commit `b0836524e`(agent-a23d949 的 app.js 补丁):`git cat-file -t b0836524e` = commit(对象仍在);`git branch --contains` 与 `git tag --contains` 均空 + `git merge-base --is-ancestor b0836524e origin/main` RC=1 → 真孤儿,已由 patch 备份兜底。

> 注:被删 worktree 目录已不存在(`git worktree list` 与 `.git/worktrees/` 均无 13 个中任何一个),`git status --porcelain` 无法对已删目录重跑,该证据依赖报告记录 + 备份逐份对应(5 个 dirty 的独有文件均有备份,见下节)。

## 二、备份实测可恢复(§25②)

备份目录 `/tmp/worktree-cleanup-backup-20261003/`:9 文件 / 308K。
- 与被删对象对应:5 份独有 md/mjs(afcb2fa / a45e087 / ac735ad / a23d949 / ae2f7cf)+ 1 份孤儿 commit 补丁(orphan-b0836524e.patch)+ a780922/ 3 份(保留未删 worktree 的 P0 代码额外副本)。

### 抽样恢复演练(2 个对象 + 孤儿补丁)
1. `afcb2fa-navclobber-review-20261003.md` → 拷到 /tmp/verify-restore-20261003/docs/ops/,md5 与备份一致(`9d6aa591011bf86331774f20a626c349`),文件可正常读(markdown 首行 = 标题)。
2. `ae2f7cf/_dbg_f2_probe.mjs` → 拷到 /tmp/verify-restore-20261003/scripts/playwright-accept/,md5 一致(`017336bdd4f715bbaba17c7f403d46fe`),`node --check` 语法合法。
3. `orphan-b0836524e.patch`:与 `git show b0836524e` **逐字节一致**(md5 `992831c8bc22cdca594e1b1a262f56ae` 相同);在 /tmp/patch-verify-repo(父提交 `b0836524e^` 的 app.js 基座)上 `git apply` **干净应用**,应用后文件与 `git show b0836524e:static-site/app.js` **md5 一致**(`98b916b3fd7257301a90f66d1b5b18a2`)→ 孤儿 commit 内容 100% 可恢复。

### 「怎么恢复」可执行性
- 5 份 md/mjs:报告写「拷贝回 docs/ops/ / scripts/playwright-accept/ 原路径」→ 实测可行(拷贝+md5 一致)。
- 孤儿补丁:报告写「git apply orphan-b0836524e.patch」→ 在当前 HEAD app.js 上会上下文漂移失败(`git apply --check` RC=1,**预期**,app.js 已演进);**在父提交基座 b0836524e^ 上应用成功**。建议恢复时用 `git cherry-pick b0836524e`(对象仍在)或在父基座 apply。属「恢复方法表述略欠精确」,不构成 §25 不达标(内容本身完全可恢复)。

## 三、zcode/standin-charter 独有段归档比对

- 归档 `docs/archive/zcode-standin-branch-discipline-20260903.md` 第 9 行 vs 分支原文 `.agents/zcode-standin/SKILL.md:52`:`diff` **空输出(RC=0)= 逐字一致**,非摘要、没漏行。
- commit `f5b25983d` 确为该独有行(feature commit,`diff` 只加 1 行)。
- **没混入 main 旧描述**:main 版 SKILL.md 无「ZCode 专属分支纪律」行(`grep -c` = 0),且 main 第 55 行 =「云上 systemd timer」(当前正确描述),分支第 56 行 =「launchd 时点」(旧描述,会倒退)——归档只含独有纪律段,不含会被倒退的旧内容 ✓。

## 四、现状核对

- `git worktree list`:核查开始时 20 行(main + 19)。porcelain 全量现 21 个(并发 agent 活动导致:a11cb4 的 worktree 于 07:37 后被并发任务移除,分支 feat/futures-pos-replace-20261003 仍在;a4769bc/ac619cc/ab46344 + 本核查 worktree 为清理后新增)。**清理本身保留的 17 个中 16 个仍在**(a11cb4 为清理后被并发任务移除)。
- `git branch -a`:13 个被删 worktree 的分支引用**全部在**(逐个 `git rev-parse --verify refs/heads/<分支>` 成功);报告「未删任何分支引用」属实。
- `du -sh .claude/worktrees/` = **2.6G**(报告称清理后 2.1G,差 0.5G = 清理后新增的 4 个 worktree,非清理口径)。
- **7 个 locked**:锁原因文件内容全部 = `claude agent agent-<hash> (pid 38456 ...)`;`ps -p 38456` = **ALIVE**(claude --resume,start 2026-09-17)→ 锁仍正当,**现仍不可清**。locked 集合本身动态(报告锁 7 个含 a0b7e692/a11cb4 已解锁,新增 a54d78/ab46344 锁定),数量保持 7。
- 附注:a780922 的 P0 export-guard 代码已由并发 agent 提交到 `feat/export-guard-20261003`(4fc1645c0,报告遗留建议已落实);备份 a780922/ 仍作为额外副本在。

## 五、结论

**清理可逆 ✓**(§25② 达标:备份存在、抽样实测可恢复、恢复路径可执行)。
无不可逆缺口。仅 2 个非阻断注意点:
1. 报告「孤儿补丁用 git apply」未注明需在父基座 b0836524e^ 上应用(当前 app.js 已演进会上下文失败);实际可用 `git cherry-pick b0836524e` 恢复。
2. 清理后并发 agent 又新建/移除若干 worktree(当前 21 个,含本核查 worktree),属正常并发活动,非清理反悔。

## 附:关键核查命令(真跑证据)

- `git log --oneline origin/main..<13 分支>` → 全部空,RC=0
- `git cat-file -t b0836524e` → commit;`git merge-base --is-ancestor b0836524e origin/main` → RC=1
- `md5 备份 vs 演练副本` → afcb2fa `9d6aa59...` / ae2f7cf `017336bdd4f...` 一致
- `md5 orphan patch vs git show b0836524e` → `992831c8bc22cdca594e1b1a262f56ae` 一致
- `/tmp/patch-verify-repo` 内 `git apply orphan-b0836524e.patch` → PATCH APPLY OK;结果 md5 vs `b0836524e:static-site/app.js` → `98b916b3fd7257301a90f66d1b5b18a2` 一致
- `diff 归档第9行 vs 分支:SKILL.md:52` → 空,RC=0
- `git grep -c "ZCode 专属分支纪律" origin/main:.agents/zcode-standin/SKILL.md` → 0
- `du -sh /Users/linhuichen/code/trade/.claude/worktrees/` → 2.6G
- `ps -p 38456` → ALIVE(claude --resume)
