# Git 分支大扫除报告（2026-10-05）

> 任务：本地 **162** 支 / 远端 **125** 支 → 清理（用户 2026-10-05 原话「branch 好像100多个了 这个需要整理和清理了」）。
> 全程留在 `main`，未 `checkout` / `switch` / `reset` / `stash`；未 force push；未 push/改 main；未碰在册 4 个 worktree 及其占用分支。
> 本报告为**未提交**产物（任务要求「不 commit、不 push main，报告落档后交主控处理」）。

## 0. 一句话结论

| 项 | 清理前 | 清理后 | 删除数 |
|---|---|---|---|
| 本地分支 | 162 | **7** | **155** |
| 远端分支 | 125 | **7** | **120** |
| 本地 remote-tracking ref | 125 | 7（已 prune 掉 118 条已删分支的 tracking ref） | — |

- **共删 275 支**（本地 155 / 远端 120），**零失败、零 SKIP**。
- 删除前做了 **bundle 备份 → 上传 R2 长期留存 → 还原实测 25/25 通过**（§1）；删的每一支都先证明「内容已在 main」或被 bundle 覆盖。
- 远端 7 支里有 1 支（`feat/160-consistency-gate-20261005`）是**删除窗口内另一个在跑 agent 新推的**，不在本次评估范围 → 保留（§4）。
- **⚠️ 一条观察项**：禁区保护分支 `worktree-agent-ac4a41514dd158ebe` 在 14:33~14:39 之间消失，**经证据确认不是本任务所为**（未进删除清单/逐支日志，本地删除 14:24 已收工），系其所在 worktree 侧动作；内容无损失。详见 §4.2。

## 1. 备份（可逆性证明，§25 顺序：先备后删）

**① 本地 bundle**

```
git bundle create /tmp/branches-not-in-main-20261005.bundle --branches --remotes --not main
```

- 文件：`/tmp/branches-not-in-main-20261005.bundle`，**42,827 字节**，**md5 `e629c34f848abfe627c5e76c1820d07a`**
- 内容：25 个**不在 main 可达范围**的 ref（14 个 `refs/heads/*` + 11 个 `refs/remotes/origin/*`）= 真正有风险的提交集合
- `git bundle verify` → **`is okay`**；它要求的 12 条 prerequisite 已逐条 `git merge-base --is-ancestor <c> main` 实测定为 **main 祖先** ⇒ 任何含 main 的克隆都能消费该 bundle（不依赖本机临时对象）
- 注意：这是 **thin bundle**（不含 main 已有历史，所以只有 42KB 而不是 1.6GB）——前提是「main 历史仍在」，恢复时见 §5

**② 上传 R2 长期留存前缀（无 lifecycle 删除规则）**

- 桶：`signal-backup2`（#178 迁好的**新账号独立桶**；未用老桶 `signal-backup`）
- key：`git-branch-bundles/20261005/branches-not-in-main-20261005.bundle`
- 回验（HEAD，走 `scripts/upload_r2.py` 的跨账号路由通路）：`status=200`、`Content-Length=42827`、`ETag="e629c34f848abfe627c5e76c1820d07a"`
  ⇒ **远端字节数 + ETag 与本地 md5 逐位一致**
- **前缀安全性**：该桶已配的 5 条 lifecycle 规则是 `pre-upload/` `weekly/` `monthly/` `claude-backup/` `backup/`（**字面前缀**），`git-branch-bundles/` 不在其中 ⇒ **不会被自动删除**（这是选这个前缀的原因）

**③ 还原实测（不是「应该有备份」，是「实测可恢复」）**

```
git clone --bare --local /Users/linhuichen/code/trade /tmp/bc-restore-test.git   # 硬链，1s
git -C /tmp/bc-restore-test.git reflog expire --expire=now --all
git -C /tmp/bc-restore-test.git fetch <bundle> '+refs/heads/*:refs/restored/heads/*' '+refs/remotes/*:refs/restored/remotes/*'
```

结果：**25/25 ref 全部取回，且 hash 与 bundle `list-heads` 逐位一致**（`diff` 归零）。

## 2. 判定口径（不信 `--merged`、不信三点 diff）

删一支的**唯一前提 = 能证明「它的内容已经在 main」**。三条硬证据，满足其一：

| 证据 | 命令 | 含义 |
|---|---|---|
| ancestor-of-main | `git rev-list --count main..<br>` == 0 | tip 可达自 main ⇒ 提交本身就在 main 历史里，删分支纯丢标签 |
| cherry patch-id | `git cherry -v main <br>` 全部 `-` | 补丁等价已在 main（压扁/重放导致 hash 不同，`--merged` 会漏判的正是这类） |
| blob 逐位 | `git diff --name-status main...<br>` 列出的每个文件，`git rev-parse <br>:<p>` == `git rev-parse main:<p>`；或 `git diff main..<br>` 为**纯删除 0 新增**（main 是严格超集） | 内容逐字节已在 main |

- **`git branch --merged` 全程未使用**（memory `git-batch-delete-branches`：内容等价但 hash 不同会误判）。
- **三点 diff 只用来列「分支侧改了哪些文件」**，结论一律回到 **blob hash 比对**（memory `git-three-dot-diff-false-novelty`）。
- **远端逐支三查**（不盲删）：① `git ls-remote --heads origin` 取**远端真实 hash**（不信本地过期 tracking）②与本地 tracking 比对，**不一致即 SKIP**（本次 0 例）③满足上表证据才 `git push origin --delete <br>`，**一次一支、逐支留日志**。
- 拿不准的**一律不删**（宁留勿删）；有独有内容的进 §4。

## 3. 删除清单（本地 155 / 远端 120）

- 本地 155 = **144 ancestor-of-main** + **11 content-verified**（非祖先但内容已证在 main）
- 远端 120 = **113 ancestor-of-main** + **7 content-verified**
- 逐支日志（名字 / tip 短 hash / 依据 / rc）见 **附录 A（本地）**、**附录 B（远端）**。
- **bundle 覆盖核对**：11 支本地 content-verified + 7 支远端 content-verified 的 tip，**全部落在 bundle 的 25 个 ref 内**（逐支比对）；ancestor 类的无需 bundle（其 commit 就在 main 历史里，见 §5）。

### 3.1 本地 content-verified 11 支（非祖先、逐条给了证据）

| 分支 | 判定依据 |
|---|---|
| `feat/149a-deploy-lock-split-review-20261002` | cherry 全 `-`；报告文件 blob 与 main 同路径逐位相同 |
| `feat/cf-egress-probe-20261002` | main 版报告是**严格超集**（`git diff main..br` = 54 删除 / 0 新增，10-04 二轮复测节在 main） |
| `feat/harden-alerts-review-20261002` | cherry 全 `-`；报告 blob 逐位相同 |
| `feat/icepoint-consensus-review-20261002` | cherry 全 `-`（3 提交全等价）；`icepoint.py` blob 逐位相同，`queries.py` 为 main 更新版 |
| `feat/icepoint-consensus-front-review-20261002` | cherry 全 `-`（6 提交全等价）；7 文件中 4 个 blob 逐位相同，另 3 个 main 版行数更多（超集） |
| `feat/icepoint-source-groups-20261002` | cherry 全 `-`；两个新增文件 blob 均逐位相同 |
| `feat/r2-billing-4usd50-20261002` | cherry 全 `-`；报告 blob 逐位相同 |
| `feat/r2-billing-research-20261002` | cherry 全 `-`；报告 blob 逐位相同 |
| `feat/r2-bucket-capacity-20261002` | cherry 全 `-`；脚本 blob 逐位相同，报告 main 版含新增 §⑩（超集） |
| `review-report-alertchain-hardening` | cherry 全 `-`；5 文件中 4 个 blob 逐位相同，`brief_push_wrapper.sh` 为 main 更新版注释 |
| `worktree-agent-a814025345990cccf` | cherry 全 `-`；**18 个文件 blob 全部与 main 同路径逐位相同** |

### 3.2 远端 content-verified 7 支

`feat/149a-deploy-lock-split-review-20261002`、`feat/alertchain-hardening-20261003`（= 本地 `review-report-alertchain-hardening` 同 commit）、`feat/cf-egress-probe-20261002`、`feat/harden-alerts-review-20261002`、`feat/icepoint-source-groups-20261002`、`feat/r2-billing-4usd50-20261002`、`feat/r2-bucket-capacity-20261002` —— 依据同 §3.1，且 7 支 tip **全部在 bundle 覆盖范围内**。

### 3.3 ancestor-of-main：本地 144 + 远端 113 = 257 支

即 `git rev-list --count main..<br>` == 0：提交本身就是 main 历史的一部分，删掉的只是标签。全量名字见附录。

## 4. 保留清单（完整 + 原因）

### 4.1 桶②「有独有内容」——**按纪律不删**（等主控/用户决策）

| 分支 | 层 | 独有内容证据 |
|---|---|---|
| `zcode/standin-charter` | 本地+远端 | `.agents/zcode-standin/SKILL.md` 含 main **没有**的「⚠️ ZCode 专属分支纪律」段（`grep -c` main=0 / 分支=1）；同时该文件另有几处是分支侧的旧文案（main 已更新） ⇒ 分叉，需人工判定保留哪侧 |
| `feat/r2-slim-20261003` | 本地+远端 | 报告 `docs/ops/r2-slim-compression-measure-20261004.md` 与 main 非字节子集（main 是「定稿」版，分支是草稿版：`git diff main..br` 90 插入/137 删除，主要是标点/小节号差异 + main 多一行达标数字）⇒ **宁留勿删** |
| `feat/ledger-20261001b` | 远端 | 台账分支，改的是活文档 `docs/pending-features-index.md`（与 main 已大幅分叉；main 含「假成功占窗」等后续条目，但分支独有的「复审2 FAIL」字面不在 main）⇒ 信息可能已被后续条目覆盖，但**无法逐字证明** ⇒ 保留 |

### 4.2 在册 worktree 占用（任务指定禁删）

| 分支 | worktree | 说明 |
|---|---|---|
| `feat/178-r2-backup2-route-20261005` | `.claude/worktrees/agent-a047ac0eeaba6fc7e` | 已完成待 merge，**必须保留** |
| `feat/164-162-monitor-20261005` | `.claude/worktrees/agent-a6af8aa6633fbd8ab` | 在跑 |
| `worktree-agent-a2255194167eef851` | `.claude/worktrees/agent-a2255194167eef851` | 在跑（locked） |
| `worktree-agent-ac4a41514dd158ebe` | `.claude/worktrees/agent-ac4a41514dd158ebe` | 在跑（locked）。**⚠️ 观察项**：该 worktree 于 14:35 切到新分支 `feat/160-consistency-gate-20261005`，**其同名旧分支在 14:33~14:39 之间消失**（`git branch` 14:33 快照还在、14:39 已无）。**不是本任务删的**：该名字从未进入我的删除清单与逐支日志（`grep` 三处均为 0 命中，本地删除已于 14:24 结束），`.git/logs/refs/heads/` mtime=14:34 属该 worktree 侧动作。**内容无损失**（旧 tip `772a71788` 是 main 历史内 commit，`merge-base --is-ancestor` 实测 True）⇒ 仅作观察如实记录，是否需追查由主控定 |

### 4.3 其它保留

| 分支 | 层 | 原因 |
|---|---|---|
| `main` | 本地+远端 | 主干 |
| `feat/160-consistency-gate-20261005` | 本地+远端 | **本次删除窗口内（14:25 之后）由在跑 agent 新建**（先出现在远端，随后该 worktree 也切到它），不在评估快照内 ⇒ 未评估、不动 |

## 5. 恢复路径（怎么把删掉的分支弄回来）

**A. 从 R2 取回 bundle（异机/本机丢了 /tmp 时）**

```bash
# 走 scripts/upload_r2.py 的跨账号路由(新桶 signal-backup2 自动用 R2_BACKUP2_* 凭据)
python3 - <<'PY'
import sys; sys.path.insert(0, "/Users/linhuichen/code/trade/scripts")
import upload_r2 as u
KEY = "git-branch-bundles/20261005/branches-not-in-main-20261005.bundle"
st, data = u.s3_request("GET", KEY, bucket=u.BACKUP2_BUCKET)
print("status", st, "bytes", len(data))
open("/tmp/restored-bundle.bundle", "wb").write(data)
PY
# 校验:md5 必须 == e629c34f848abfe627c5e76c1820d07a
md5 /tmp/restored-bundle.bundle
git bundle verify /tmp/restored-bundle.bundle     # 必须 PASS(is okay)
```

**B. 从 bundle 恢复某一支（例：`feat/r2-slim-20261003`）**

```bash
# 在任意含 main 历史的克隆里执行(prerequisite 是 main 祖先,已在 main 历史中)
git fetch /tmp/branches-not-in-main-20261005.bundle   'refs/heads/feat/r2-slim-20261003:refs/heads/restored-r2-slim-20261003'
git rev-parse restored-r2-slim-20261003      # 应 == ac2d7d21a9c32152fda55702097d07eb69e6627e
# 远端同名分支:恢复后 push 回去即可(git push origin restored-r2-slim-20261003:feat/r2-slim-20261003)
git switch --create feat/r2-slim-20261003 restored-r2-slim-20261003   # 若要用原名
```

**C. ancestor 类分支（本地 144 + 远端 113）根本不用 bundle**：commit 仍在 main 历史里，附录日志有每支 tip 的短 hash，直接

```bash
git branch <原分支名> <tip>        # 例:git branch docs/audit-179-numbers-20261005 2481de53a
```

**D. 远端分支的"取消删除"**：远端删掉的 ref 就是 GitHub 上 ref 没了；按 B 取回后 `git push origin <ref>` 重推即可（时间窗口内 GitHub 也仍能通过事件 API 找回旧 SHA，但不要依赖）。

## 6. 未做 / 待主控处理

1. **本报告未 commit、未 push**（任务要求）；`git status` 当前干净与否请看主控侧。
2. `origin/HEAD` 是**坏 ref**（既非 symbolic，也解析不出对象；`git branch -r` 已不列它）。建议主控跑一次 `git remote set-head origin -a` 修好（我没动，避免越界）。
3. `/private/tmp/hc-review-feat` 是 **detached worktree**（HEAD = `cf68c7270`，即本次已删的 `review-report-alertchain-hardening` 的父提交）。它的 HEAD 仍引用着该 commit，**不影响本次删除**；若该 review worktree 已不再用，主控可 `git worktree remove /private/tmp/hc-review-feat`。
4. 本地残留 worktree 分支 `worktree-agent-a2255194167eef851` 按禁区要求保留（对应 worktree 仍在册 locked）。`worktree-agent-ac4a41514dd158ebe` 在窗口内由其 worktree 侧消失（**非本任务所为**，证据见 §4.2），主控若需追查可查该 agent 的会话记录。若主控确认这些 worktree 可清，对应分支可在 `git worktree remove <path>` 后再 `git branch -D`。
5. **PR 风险如实标注**：本机没有 `gh`，未能查「这些远端分支上有没有开着的 PR」（删 head 分支会关闭 PR）。本项目流程不走 PR（`main-merge.sh` 本地合 + 直推 main），风险低，但**没验证过**，如实记。**✅ 主控 2026-10-05 事后补验（不用 `gh`,走 GitHub REST API)**:`GET /repos/xp13465/trade-data-signal/pulls?state=open` → **open PRs = 0** ⇒ 本次删远端 head **未关闭任何 PR**,风险已排除。
6. 远端新推的 `feat/160-consistency-gate-20261005` 未评估（见 4.3）。

---

## 附录 A：本地 155 支逐支日志

| 分支 | tip | 依据 | rc |
|---|---|---|---|
| `docs/audit-179-numbers-20261005` | `2481de53a` | ancestor-of-main | 0 |
| `docs/audit-179-reverify-20261005` | `4847fb232` | ancestor-of-main | 0 |
| `docs/handoff-bkt-audit-done-20261005` | `b007f484b` | ancestor-of-main | 0 |
| `docs/handoff-worktree-trap-20261005` | `d8ae54856` | ancestor-of-main | 0 |
| `docs/index-sync-20261004` | `7795ab205` | ancestor-of-main | 0 |
| `docs/lifecycle-179-20261005` | `63c77800b` | ancestor-of-main | 0 |
| `docs/r2fix-merge-handoff-20261005` | `f8ec0519c` | ancestor-of-main | 0 |
| `feat/149a-deploy-git-lock-20261002` | `98e5ee4c7` | ancestor-of-main | 0 |
| `feat/149d-timer-offset-20261003` | `737f1659d` | ancestor-of-main | 0 |
| `feat/180-r2-large-put-progress-20261005` | `046558666` | ancestor-of-main | 0 |
| `feat/accnav-backfill-exec-20261003` | `973a57bda` | ancestor-of-main | 0 |
| `feat/accnav-backfill-research-20261003` | `0b900c4af` | ancestor-of-main | 0 |
| `feat/accnav-prerequisites-20261003` | `fcb56504b` | ancestor-of-main | 0 |
| `feat/accnav-review-20261003` | `42fdbfc2c` | ancestor-of-main | 0 |
| `feat/alert-harden-review-20261003` | `c76ae7274` | ancestor-of-main | 0 |
| `feat/alertchain-hardening-20261003` | `def95ef43` | ancestor-of-main | 0 |
| `feat/alerts-sweep-20261003` | `11841e01b` | ancestor-of-main | 0 |
| `feat/branch-inventory-20261003` | `26e57bc0d` | ancestor-of-main | 0 |
| `feat/cf-preview-off-20261003` | `d2f83bef9` | ancestor-of-main | 0 |
| `feat/cf-version-provenance-20261003` | `5cf256fd0` | ancestor-of-main | 0 |
| `feat/ci-pytest-fix-20261003` | `24b6a9d86` | ancestor-of-main | 0 |
| `feat/ci-pytest-review-20261003` | `004771b2f` | ancestor-of-main | 0 |
| `feat/emintraday-denoise-20261002` | `ec202edaa` | ancestor-of-main | 0 |
| `feat/export-guard-20261003` | `a1b5f13c3` | ancestor-of-main | 0 |
| `feat/frontleft-147-152-20261003` | `3bda4aa72` | ancestor-of-main | 0 |
| `feat/frontleft-review-20261003` | `f02692986` | ancestor-of-main | 0 |
| `feat/futures-pos-replace-20261003` | `43e0bc329` | ancestor-of-main | 0 |
| `feat/gtick-em-cooldown-20261004` | `df2112e72` | ancestor-of-main | 0 |
| `feat/harden-alerts-20261002` | `93f257bb7` | ancestor-of-main | 0 |
| `feat/hc-docs-registry-20261003` | `5f3e0bd48` | ancestor-of-main | 0 |
| `feat/hc-secret-research-20261003` | `0cdda656c` | ancestor-of-main | 0 |
| `feat/healthcheck-20261003` | `47c64aa1b` | ancestor-of-main | 0 |
| `feat/help-dblclick-20261003` | `69d61156f` | ancestor-of-main | 0 |
| `feat/holiday-wrapup-docs-20261003` | `11073b291` | ancestor-of-main | 0 |
| `feat/icepoint-consensus-20261002` | `78888b0e3` | ancestor-of-main | 0 |
| `feat/icepoint-legend-text-20261002` | `54f2bf615` | ancestor-of-main | 0 |
| `feat/index-152-live-20261002` | `8723a64a2` | ancestor-of-main | 0 |
| `feat/index-sync-20261003` | `451fed078` | ancestor-of-main | 0 |
| `feat/index-writeoff-20261003` | `fc951666a` | ancestor-of-main | 0 |
| `feat/mem-hygiene-20261004` | `cf5f6be93` | ancestor-of-main | 0 |
| `feat/open-banner-20261004` | `a6787c6ee` | ancestor-of-main | 0 |
| `feat/pf-nav-clobber-fix-20261002` | `9f536169a` | ancestor-of-main | 0 |
| `feat/purge-secret-rotate-20261003` | `8a1f82fbb` | ancestor-of-main | 0 |
| `feat/queries-except-logging-20261002` | `cf4919070` | ancestor-of-main | 0 |
| `feat/r2-archive-closeout-20261004` | `f415ea5c9` | ancestor-of-main | 0 |
| `feat/r2-archive-upload-20261004` | `21474d9e0` | ancestor-of-main | 0 |
| `feat/r2-mac-backups-restore-20261002` | `a38aedc61` | ancestor-of-main | 0 |
| `feat/r2-retention-14d-20261003` | `4193f3d18` | ancestor-of-main | 0 |
| `feat/r2-slim-report-20261004` | `2ce49542a` | ancestor-of-main | 0 |
| `feat/retention-align-20261004` | `c7d840891` | ancestor-of-main | 0 |
| `feat/retention-revert-20261004` | `d35857f03` | ancestor-of-main | 0 |
| `feat/updateall-perf-20261004` | `69803a006` | ancestor-of-main | 0 |
| `feat/worktree-cleanup-20261003` | `8ac1c19a1` | ancestor-of-main | 0 |
| `review-hc-timer-mount` | `517db4e9f` | ancestor-of-main | 0 |
| `worktree-agent-a00621e944b2fdb73 basis=ancestor-of-main rc=0 :: (deleted in smoke test earlier)` | `?` | ancestor-of-main | 0 |
| `worktree-agent-a01716f9c4489a301` | `8723a64a2` | ancestor-of-main | 0 |
| `worktree-agent-a047ac0eeaba6fc7e` | `197b0edc0` | ancestor-of-main | 0 |
| `worktree-agent-a06f409e7e6962cf4` | `47c64aa1b` | ancestor-of-main | 0 |
| `worktree-agent-a09d991351b5b1300` | `27813df68` | ancestor-of-main | 0 |
| `worktree-agent-a0b7e692af78b2ef3` | `11073b291` | ancestor-of-main | 0 |
| `worktree-agent-a0c6da07deae45237` | `8d8cc2d1d` | ancestor-of-main | 0 |
| `worktree-agent-a0ef0a0b2e02c6903` | `791a80a42` | ancestor-of-main | 0 |
| `worktree-agent-a1129d3a97dfbb24c` | `7d42f1eb5` | ancestor-of-main | 0 |
| `worktree-agent-a11cb4fb71521c66c` | `11073b291` | ancestor-of-main | 0 |
| `worktree-agent-a129175bba57fc061` | `47c64aa1b` | ancestor-of-main | 0 |
| `worktree-agent-a14fa4bbea4592389` | `c7d840891` | ancestor-of-main | 0 |
| `worktree-agent-a1710f327eda38131` | `8723a64a2` | ancestor-of-main | 0 |
| `worktree-agent-a1e0dea517a904218` | `7fd2dbbb0` | ancestor-of-main | 0 |
| `worktree-agent-a21a8da12bd0abd20` | `c7d840891` | ancestor-of-main | 0 |
| `worktree-agent-a23d9492760cfd76d` | `27813df68` | ancestor-of-main | 0 |
| `worktree-agent-a32eca2ef3e40884f` | `9faf92d8e` | ancestor-of-main | 0 |
| `worktree-agent-a388e66389260da74` | `887664cdd` | ancestor-of-main | 0 |
| `worktree-agent-a38f5bb77b40c1e6e` | `21474d9e0` | ancestor-of-main | 0 |
| `worktree-agent-a3fa5c52151661c4e` | `8a1f82fbb` | ancestor-of-main | 0 |
| `worktree-agent-a400cec918eaf5198` | `c8cd4992f` | ancestor-of-main | 0 |
| `worktree-agent-a45e08728ec92e53f` | `98e2998de` | ancestor-of-main | 0 |
| `worktree-agent-a46b828785bdb9354` | `fc951666a` | ancestor-of-main | 0 |
| `worktree-agent-a4769bc9343c0828a` | `11073b291` | ancestor-of-main | 0 |
| `worktree-agent-a4d09b139bcfc8043` | `7fd2dbbb0` | ancestor-of-main | 0 |
| `worktree-agent-a4db96bd1ddf07130` | `101073af8` | ancestor-of-main | 0 |
| `worktree-agent-a54d78abfef6c90f5` | `11073b291` | ancestor-of-main | 0 |
| `worktree-agent-a5622e1883dac9dd4` | `c8cd4992f` | ancestor-of-main | 0 |
| `worktree-agent-a578df4331fee2c08` | `c8cd4992f` | ancestor-of-main | 0 |
| `worktree-agent-a57e7deff684d67c8` | `0cdda656c` | ancestor-of-main | 0 |
| `worktree-agent-a5e822e993ce91d0f` | `2ce49542a` | ancestor-of-main | 0 |
| `worktree-agent-a5e9d82d968afd895` | `2a67bba25` | ancestor-of-main | 0 |
| `worktree-agent-a6af8aa6633fbd8ab` | `772a71788` | ancestor-of-main | 0 |
| `worktree-agent-a6b711a421079a130` | `11073b291` | ancestor-of-main | 0 |
| `worktree-agent-a6e41f0e4fff47165` | `2997460f4` | ancestor-of-main | 0 |
| `worktree-agent-a7031376632bb45be` | `7d42f1eb5` | ancestor-of-main | 0 |
| `worktree-agent-a705582e7ba802b26` | `8723a64a2` | ancestor-of-main | 0 |
| `worktree-agent-a7329add85c12b336` | `635bdc218` | ancestor-of-main | 0 |
| `worktree-agent-a7356b9257dc9cfd1` | `245155f0d` | ancestor-of-main | 0 |
| `worktree-agent-a75faa9059906d184` | `046558666` | ancestor-of-main | 0 |
| `worktree-agent-a7713290a8375412b` | `d35857f03` | ancestor-of-main | 0 |
| `worktree-agent-a772ff1bcc9af4d94` | `27813df68` | ancestor-of-main | 0 |
| `worktree-agent-a7809227903882f4b` | `11073b291` | ancestor-of-main | 0 |
| `worktree-agent-a782b4423d5522338` | `11073b291` | ancestor-of-main | 0 |
| `worktree-agent-a7f6f2c90f1b79893` | `27813df68` | ancestor-of-main | 0 |
| `worktree-agent-a802c8529ab2f3fc7` | `1501d6aa0` | ancestor-of-main | 0 |
| `worktree-agent-a82d3e09efe0d0523` | `fc951666a` | ancestor-of-main | 0 |
| `worktree-agent-a8403e0209f37cbb5` | `7fd2dbbb0` | ancestor-of-main | 0 |
| `worktree-agent-a8612545027927936` | `9224c459c` | ancestor-of-main | 0 |
| `worktree-agent-a875c7b8a407fdbd7` | `8e8dd199e` | ancestor-of-main | 0 |
| `worktree-agent-a96add3c0e2c6179c` | `978eac162` | ancestor-of-main | 0 |
| `worktree-agent-a9e2db23c2af94c4a` | `7fd2dbbb0` | ancestor-of-main | 0 |
| `worktree-agent-a9fb84f069bbe30ae` | `743c0043c` | ancestor-of-main | 0 |
| `worktree-agent-aa83f3a3efeff690e` | `e95ce72e4` | ancestor-of-main | 0 |
| `worktree-agent-aabf841affedc4872` | `f415ea5c9` | ancestor-of-main | 0 |
| `worktree-agent-aac34f6825996b5c4` | `f64782c89` | ancestor-of-main | 0 |
| `worktree-agent-aae9b9fe562f51c7c` | `7fd2dbbb0` | ancestor-of-main | 0 |
| `worktree-agent-aaec35b8e37b4e868` | `27813df68` | ancestor-of-main | 0 |
| `worktree-agent-ab2dc5afc4c52e86b` | `fc951666a` | ancestor-of-main | 0 |
| `worktree-agent-ab46344df19b9c206` | `11073b291` | ancestor-of-main | 0 |
| `worktree-agent-ab4d1f950792b6b36` | `e94dcee65` | ancestor-of-main | 0 |
| `worktree-agent-ab9324aa48fd6f066` | `7fd2dbbb0` | ancestor-of-main | 0 |
| `worktree-agent-ab98f5d739f81c907` | `887664cdd` | ancestor-of-main | 0 |
| `worktree-agent-abce6816d6d5ee83f` | `887664cdd` | ancestor-of-main | 0 |
| `worktree-agent-abe52ea876cf28b9d` | `7fd2dbbb0` | ancestor-of-main | 0 |
| `worktree-agent-ac2f40c2ba03f0130` | `887664cdd` | ancestor-of-main | 0 |
| `worktree-agent-ac562449df83a621b` | `27813df68` | ancestor-of-main | 0 |
| `worktree-agent-ac619cc02bcf989ae` | `11073b291` | ancestor-of-main | 0 |
| `worktree-agent-ac735ad5463e2ade2` | `27813df68` | ancestor-of-main | 0 |
| `worktree-agent-acb76651085a17f36` | `0cdda656c` | ancestor-of-main | 0 |
| `worktree-agent-ace11781a6d0397b3` | `27813df68` | ancestor-of-main | 0 |
| `worktree-agent-ad05c4234385726dd` | `1501d6aa0` | ancestor-of-main | 0 |
| `worktree-agent-ad63f53ee6aabbec2` | `7ee2c33ee` | ancestor-of-main | 0 |
| `worktree-agent-ad766797159ec2036` | `245155f0d` | ancestor-of-main | 0 |
| `worktree-agent-ad8cfa7e6d1d82182` | `5f3e0bd48` | ancestor-of-main | 0 |
| `worktree-agent-adc0fbf873353a6d5` | `887664cdd` | ancestor-of-main | 0 |
| `worktree-agent-ae2f7cfb35006f345` | `98e2998de` | ancestor-of-main | 0 |
| `worktree-agent-ae5c00ada12d81b7c` | `47c64aa1b` | ancestor-of-main | 0 |
| `worktree-agent-ae6f4508f230db573` | `6d497803e` | ancestor-of-main | 0 |
| `worktree-agent-ae8445feaaa1615ec` | `6d497803e` | ancestor-of-main | 0 |
| `worktree-agent-ae93b4063088ad451` | `43e0bc329` | ancestor-of-main | 0 |
| `worktree-agent-aebcf2a7ab7ccbe5b` | `e95ce72e4` | ancestor-of-main | 0 |
| `worktree-agent-aeca98ac082f0165d` | `5f3e0bd48` | ancestor-of-main | 0 |
| `worktree-agent-aedc10fc38294209e` | `11ee34fb8` | ancestor-of-main | 0 |
| `worktree-agent-aede926299d5fac77` | `7fd2dbbb0` | ancestor-of-main | 0 |
| `worktree-agent-af1f3aa9ed4677be5` | `ec0bcb4a0` | ancestor-of-main | 0 |
| `worktree-agent-afa1a567f5432b930` | `1501d6aa0` | ancestor-of-main | 0 |
| `worktree-agent-afcb2fa189b969a04` | `5e2cc6a8f` | ancestor-of-main | 0 |
| `worktree-agent-affb89c6a0be7a17f` | `7ee2c33ee` | ancestor-of-main | 0 |
| `worktree-agent-affe223e6aae180f9` | `9224c459c` | ancestor-of-main | 0 |
| `feat/149a-deploy-lock-split-review-20261002` | `acc06b58a` | content-verified-in-main(cherry-patch-id|blob-same|strict-subset) | 0 |
| `feat/cf-egress-probe-20261002` | `86d593e1e` | content-verified-in-main(cherry-patch-id|blob-same|strict-subset) | 0 |
| `feat/harden-alerts-review-20261002` | `55a6c7602` | content-verified-in-main(cherry-patch-id|blob-same|strict-subset) | 0 |
| `feat/icepoint-consensus-front-review-20261002` | `256ec7bdc` | content-verified-in-main(cherry-patch-id|blob-same|strict-subset) | 0 |
| `feat/icepoint-consensus-review-20261002` | `2ec653d21` | content-verified-in-main(cherry-patch-id|blob-same|strict-subset) | 0 |
| `feat/icepoint-source-groups-20261002` | `bbe2ef46a` | content-verified-in-main(cherry-patch-id|blob-same|strict-subset) | 0 |
| `feat/r2-billing-4usd50-20261002` | `773911e61` | content-verified-in-main(cherry-patch-id|blob-same|strict-subset) | 0 |
| `feat/r2-billing-research-20261002` | `628989754` | content-verified-in-main(cherry-patch-id|blob-same|strict-subset) | 0 |
| `feat/r2-bucket-capacity-20261002` | `833264726` | content-verified-in-main(cherry-patch-id|blob-same|strict-subset) | 0 |
| `review-report-alertchain-hardening` | `62a69f1d6` | content-verified-in-main(cherry-patch-id|blob-same|strict-subset) | 0 |
| `worktree-agent-a814025345990cccf` | `da1b19ae1` | content-verified-in-main(cherry-patch-id|blob-same|strict-subset) | 0 |

## 附录 B：远端 120 支逐支日志

| 分支 | tip | 依据 | rc |
|---|---|---|---|
| `codex/console-csp-noise-v1` | `8a814d655` | ancestor-of-main | 0 |
| `docs/126-revision-20260930` | `74a0e557d` | ancestor-of-main | 0 |
| `docs/149-report-sec9-landing` | `937c5ef34` | ancestor-of-main | 0 |
| `docs/audit-179-numbers-20261005` | `2481de53a` | ancestor-of-main | 0 |
| `docs/audit-179-reverify-20261005` | `4847fb232` | ancestor-of-main | 0 |
| `docs/fapi140-report-landing` | `65401a5f7` | ancestor-of-main | 0 |
| `docs/handoff-bkt-audit-done-20261005` | `b007f484b` | ancestor-of-main | 0 |
| `docs/handoff-worktree-trap-20261005` | `d8ae54856` | ancestor-of-main | 0 |
| `docs/index-sync-20261004` | `7795ab205` | ancestor-of-main | 0 |
| `docs/ledger-134-p2-20261002` | `eefe18c1f` | ancestor-of-main | 0 |
| `docs/lifecycle-179-20261005` | `63c77800b` | ancestor-of-main | 0 |
| `docs/pending-index-130-rework-133-20260930` | `333c7fef8` | ancestor-of-main | 0 |
| `docs/pending-index-131-done-20260930` | `f5b191d01` | ancestor-of-main | 0 |
| `docs/r2fix-merge-handoff-20261005` | `f8ec0519c` | ancestor-of-main | 0 |
| `docs/research-icepoint-luopan-20260930` | `238c2ad8c` | ancestor-of-main | 0 |
| `feat/123-fix-review-20261001` | `a50d92f0f` | ancestor-of-main | 0 |
| `feat/123-r4-review-20261001` | `038963319` | ancestor-of-main | 0 |
| `feat/132-monitor-fixups-20261001` | `8c7601885` | ancestor-of-main | 0 |
| `feat/132-review-20261001` | `f6a277612` | ancestor-of-main | 0 |
| `feat/132-review2-20261001` | `1af4e75d5` | ancestor-of-main | 0 |
| `feat/132-review3-20261001` | `ef13914ee` | ancestor-of-main | 0 |
| `feat/136-150-gitignore-block-20261001` | `ed82101fd` | ancestor-of-main | 0 |
| `feat/136-review-20261001` | `b1790246d` | ancestor-of-main | 0 |
| `feat/149-lock-split-20261001` | `d8d9ac255` | ancestor-of-main | 0 |
| `feat/149-review-landing` | `005812a75` | ancestor-of-main | 0 |
| `feat/149a-deploy-git-lock-20261002` | `98e5ee4c7` | ancestor-of-main | 0 |
| `feat/149d-timer-offset-20261003` | `737f1659d` | ancestor-of-main | 0 |
| `feat/149e-large-json-incremental-20261001` | `7079148af` | ancestor-of-main | 0 |
| `feat/149e-review-20261001` | `d4cf5aed1` | ancestor-of-main | 0 |
| `feat/149e-review3-20261001` | `e5ad18a19` | ancestor-of-main | 0 |
| `feat/149e-review4-20261001` | `2dcfd1ec5` | ancestor-of-main | 0 |
| `feat/180-r2-large-put-progress-20261005` | `046558666` | ancestor-of-main | 0 |
| `feat/accnav-backfill-exec-20261003` | `973a57bda` | ancestor-of-main | 0 |
| `feat/accnav-backfill-research-20261003` | `0b900c4af` | ancestor-of-main | 0 |
| `feat/accnav-prerequisites-20261003` | `fcb56504b` | ancestor-of-main | 0 |
| `feat/accnav-review-20261003` | `42fdbfc2c` | ancestor-of-main | 0 |
| `feat/alert-harden-review-20261003` | `c76ae7274` | ancestor-of-main | 0 |
| `feat/alerts-sweep-20261003` | `11841e01b` | ancestor-of-main | 0 |
| `feat/branch-inventory-20261003` | `26e57bc0d` | ancestor-of-main | 0 |
| `feat/cf-preview-off-20261003` | `d2f83bef9` | ancestor-of-main | 0 |
| `feat/cf-version-provenance-20261003` | `5cf256fd0` | ancestor-of-main | 0 |
| `feat/ci-pytest-fix-20261003` | `24b6a9d86` | ancestor-of-main | 0 |
| `feat/ci-pytest-review-20261003` | `004771b2f` | ancestor-of-main | 0 |
| `feat/emintraday-denoise-20261002` | `ec202edaa` | ancestor-of-main | 0 |
| `feat/export-guard-20261003` | `a1b5f13c3` | ancestor-of-main | 0 |
| `feat/frontleft-147-152-20261003` | `3bda4aa72` | ancestor-of-main | 0 |
| `feat/frontleft-review-20261003` | `f02692986` | ancestor-of-main | 0 |
| `feat/futures-pos-replace-20261003` | `43e0bc329` | ancestor-of-main | 0 |
| `feat/gtick-em-cooldown-20261004` | `df2112e72` | ancestor-of-main | 0 |
| `feat/harden-alerts-20261002` | `93f257bb7` | ancestor-of-main | 0 |
| `feat/hc-docs-registry-20261003` | `5f3e0bd48` | ancestor-of-main | 0 |
| `feat/hc-secret-research-20261003` | `0cdda656c` | ancestor-of-main | 0 |
| `feat/healthcheck-20261003` | `47c64aa1b` | ancestor-of-main | 0 |
| `feat/help-dblclick-20261003` | `69d61156f` | ancestor-of-main | 0 |
| `feat/holiday-housekeeping-20261001` | `a2dc69b4a` | ancestor-of-main | 0 |
| `feat/holiday-wrapup-docs-20261003` | `11073b291` | ancestor-of-main | 0 |
| `feat/housekeeping-review-20261001` | `d58a53861` | ancestor-of-main | 0 |
| `feat/icepoint-consensus-20261002` | `78888b0e3` | ancestor-of-main | 0 |
| `feat/icepoint-legend-text-20261002` | `54f2bf615` | ancestor-of-main | 0 |
| `feat/index-152-live-20261002` | `8723a64a2` | ancestor-of-main | 0 |
| `feat/index-sync-20261003` | `451fed078` | ancestor-of-main | 0 |
| `feat/index-writeoff-20261003` | `fc951666a` | ancestor-of-main | 0 |
| `feat/ledger-123-149-20261001` | `c792cbf70` | ancestor-of-main | 0 |
| `feat/ledger-124-20261001` | `a777300c4` | ancestor-of-main | 0 |
| `feat/ledger-136-150-20261001` | `4284cdeff` | ancestor-of-main | 0 |
| `feat/lianban-p2fix-20261002` | `7da2e6e76` | ancestor-of-main | 0 |
| `feat/lianban-p2fix-review-20261002` | `92e600a0b` | ancestor-of-main | 0 |
| `feat/lianban-review-20261002` | `b0a4b78db` | ancestor-of-main | 0 |
| `feat/mem-hygiene-20261004` | `cf5f6be93` | ancestor-of-main | 0 |
| `feat/open-banner-20261004` | `a6787c6ee` | ancestor-of-main | 0 |
| `feat/pf-nav-clobber-fix-20261002` | `9f536169a` | ancestor-of-main | 0 |
| `feat/purge-secret-rotate-20261003` | `8a1f82fbb` | ancestor-of-main | 0 |
| `feat/queries-except-logging-20261002` | `cf4919070` | ancestor-of-main | 0 |
| `feat/r2-archive-closeout-20261004` | `f415ea5c9` | ancestor-of-main | 0 |
| `feat/r2-archive-upload-20261004` | `21474d9e0` | ancestor-of-main | 0 |
| `feat/r2-mac-backups-restore-20261002` | `a38aedc61` | ancestor-of-main | 0 |
| `feat/r2-retention-14d-20261003` | `4193f3d18` | ancestor-of-main | 0 |
| `feat/r2-slim-report-20261004` | `2ce49542a` | ancestor-of-main | 0 |
| `feat/retention-align-20261004` | `c7d840891` | ancestor-of-main | 0 |
| `feat/retention-revert-20261004` | `d35857f03` | ancestor-of-main | 0 |
| `feat/updateall-perf-20261004` | `69803a006` | ancestor-of-main | 0 |
| `feat/worktree-cleanup-20261003` | `8ac1c19a1` | ancestor-of-main | 0 |
| `fix/console-csp-whitelist-20260930` | `51b15d7cf` | ancestor-of-main | 0 |
| `fix/doc-staleness-exempt-autoblock-20260930` | `d169fa415` | ancestor-of-main | 0 |
| `fix/hook-drop-unverifiable-20260929` | `5488b35bc` | ancestor-of-main | 0 |
| `fix/hook-isolation-check-20260929` | `2339ae090` | ancestor-of-main | 0 |
| `fix/r2-large-json-fuse-20260929` | `c0cd3d356` | ancestor-of-main | 0 |
| `review-hc-timer-mount` | `517db4e9f` | ancestor-of-main | 0 |
| `worktree-agent-a0566720878fdc0bf` | `839fb5036` | ancestor-of-main | 0 |
| `worktree-agent-a1152d9f73daf2481` | `fcd0c14c5` | ancestor-of-main | 0 |
| `worktree-agent-a1593f5b599a18d5a` | `4c796b176` | ancestor-of-main | 0 |
| `worktree-agent-a1caa746da5af5593` | `a8ec330e0` | ancestor-of-main | 0 |
| `worktree-agent-a25e29c4db5dba109` | `b258a881d` | ancestor-of-main | 0 |
| `worktree-agent-a2819ea6710ba9071` | `5151451ef` | ancestor-of-main | 0 |
| `worktree-agent-a29c186450baef9b2` | `0d402cccd` | ancestor-of-main | 0 |
| `worktree-agent-a32eca2ef3e40884f` | `9faf92d8e` | ancestor-of-main | 0 |
| `worktree-agent-a4073313ae3757f08` | `394201e3c` | ancestor-of-main | 0 |
| `worktree-agent-a48220c2c1f4f8dfa` | `e7afc040e` | ancestor-of-main | 0 |
| `worktree-agent-a514b07298e881741` | `bb13d1c25` | ancestor-of-main | 0 |
| `worktree-agent-a5e2d7cd43bcf8f87` | `d03cbecc5` | ancestor-of-main | 0 |
| `worktree-agent-a5e9d82d968afd895` | `2a67bba25` | ancestor-of-main | 0 |
| `worktree-agent-a69e2ed45b4902c59` | `67479e219` | ancestor-of-main | 0 |
| `worktree-agent-a7329add85c12b336` | `635bdc218` | ancestor-of-main | 0 |
| `worktree-agent-a7c88b498af1f88ee` | `b09a2f62f` | ancestor-of-main | 0 |
| `worktree-agent-a7cbb8af4e8d8d9f0` | `0c1c50e3d` | ancestor-of-main | 0 |
| `worktree-agent-a98a8632d62d582f9` | `7694ed04e` | ancestor-of-main | 0 |
| `worktree-agent-ab036b9fd6158245e` | `e24a6069e` | ancestor-of-main | 0 |
| `worktree-agent-ab4d1f950792b6b36` | `e94dcee65` | ancestor-of-main | 0 |
| `worktree-agent-ac60cb83bbdea434e` | `c4756a8ee` | ancestor-of-main | 0 |
| `worktree-agent-ac97136ca84199760` | `c120aed8a` | ancestor-of-main | 0 |
| `worktree-agent-ad43625fcfa9ae61b` | `32e7e94f5` | ancestor-of-main | 0 |
| `worktree-agent-af1e103df45f2939c` | `5a6439c2d` | ancestor-of-main | 0 |
| `worktree-agent-afe4479c6c8b9f732` | `32087adb0` | ancestor-of-main | 0 |
| `feat/149a-deploy-lock-split-review-20261002` | `acc06b58a` | content-verified-in-main(cherry-patch-id|blob-same|strict-subset) | 0 |
| `feat/alertchain-hardening-20261003` | `62a69f1d6` | content-verified-in-main(cherry-patch-id|blob-same|strict-subset) | 0 |
| `feat/cf-egress-probe-20261002` | `86d593e1e` | content-verified-in-main(cherry-patch-id|blob-same|strict-subset) | 0 |
| `feat/harden-alerts-review-20261002` | `55a6c7602` | content-verified-in-main(cherry-patch-id|blob-same|strict-subset) | 0 |
| `feat/icepoint-source-groups-20261002` | `bbe2ef46a` | content-verified-in-main(cherry-patch-id|blob-same|strict-subset) | 0 |
| `feat/r2-billing-4usd50-20261002` | `773911e61` | content-verified-in-main(cherry-patch-id|blob-same|strict-subset) | 0 |
| `feat/r2-bucket-capacity-20261002` | `833264726` | content-verified-in-main(cherry-patch-id|blob-same|strict-subset) | 0 |

## 附录 C：复现命令清单（本次实际跑过的关键命令）

```bash
# 1) 备份
git bundle create /tmp/branches-not-in-main-20261005.bundle --branches --remotes --not main
git bundle verify /tmp/branches-not-in-main-20261005.bundle
md5 /tmp/branches-not-in-main-20261005.bundle     # e629c34f848abfe627c5e76c1820d07a

# 2) 判定(按支)
git rev-list --count main..<br>
git cherry -v main <br>
git diff --name-status main...<br>
git rev-parse <br>:<path>; git rev-parse main:<path>

# 3) 本地删除(删前再验一次 ancestor)
git merge-base --is-ancestor $(git rev-parse <br>) main && git branch -D <br>

# 4) 远端删除(删前先取远端真实 hash 比对)
git ls-remote --heads origin
git push origin --delete <name>

# 5) 收尾
git remote prune origin
```

> 生成器脚本(临时,故意不落库): `/tmp/bc_report.py`；逐支日志源文件:`/tmp/bc-delete-log.txt`、`/tmp/bc-remote-delete-log.txt`。
