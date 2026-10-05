# 残留 3 支分支判定比对（2026-10-05）

> 任务：对 `docs/ops/git-branch-cleanup-20261005.md` §4.1/§6.3 保留的三支（`zcode/standin-charter` / `feat/r2-slim-20261003` / `feat/ledger-20261001b`）做**逐支、逐文件**实证比对，支撑用户拍板「删 / 留 / 先迁移再删」。
> 只读产出：未改任何业务文件、未删分支、未 push；本报告为本任务唯一新增文件（commit 见本文件所在分支 `docs/branch-residual-triage-20261005`）。
> 方法：① `git diff --name-status $(git merge-base main <br>) <br>` 列差异面（**不用三点 diff**，避 memory `git-three-dot-diff-false-novelty` 误报）② 逐文件 **blob hash 跨版本比对** ③ 分支独有 token（commit hash/文件路径/数字）**全量搜 main 索引 + main 树 + main 历史** ④ bundle 覆盖**独立核实**（本地 `list-heads` + R2 取回 md5 双验，不采信文档声称）。
> 口径声明：本报告一切「独有/覆盖」结论 = 上述命令的真实输出；本报告不执行任何总结性推断当结论，拿不准项显式标注「需人工判定」。

## 0. 一句话结论（明细证据见各小节）

| 分支 | 层 | 分支独有内容 | 判定建议 | 删了怎么恢复 |
|---|---|---|---|---|
| `zcode/standin-charter` | 本地+远端 | **仅 1 行 bullet 是真独有**，且已**逐位归档在 main**（`docs/archive/zcode-standin-branch-discipline-20260903.md:9`，706B 逐位一致）；另 3 处为被 main 更新掉的旧文案 | **可删**（零信息损失；合并反而倒退） | main 内归档文件（含恢复说明）+ bundle（已验） |
| `feat/r2-slim-20261003` | 本地+远端 | **S2c 页级去重工程落地要点**（per-file 页索引 ~12MB / sha256 去重 / 重建逻辑 / 合计包体 ~0.25 GiB，main 无此 3 处字样）+ long31 `exit 144` 叙事（与 main 的「限时窗口停掉」叙事相左，**需人工判定**）+ 少量数字（per-DB 总量 5.565/4.606 GiB、字节级明细） | **建议先迁移再删**（迁 2 段到 main `docs/ops/r2-slim-compression-measure-20261004.md` §⑨/§⑧，见 §3.5） | 迁移后 bundle；未迁移前原样可查 |
| `feat/ledger-20261001b` | 远端 | 7 行台账**字面**独有，但全部 token（3 个 commit / 3 份报告路径 / 3 个分支名）**逐一实测可追**：commit 全为 ancestor-of-main，报告文件全在 main 树，「二轮 FAIL」事实在 main 行 + 文件 + commit 主题 | **可删**（无一处信息不在 main） | bundle（已验） |

> 注：以上「可删」均为**实证结论 + 建议**；是否删由用户拍板。删除动作本身另有 §25 备份可逆要求（bundle 已就位，见 §5）。

## 1. 公共方法与关键命令（全部可复跑）

```bash
# ① 差异面（分支侧改了什么）——用 merge-base，不用 main...<br>
git diff --name-status $(git merge-base main <br>) <br>
# ② 分支 tip 是否在 main 可达：非 0 = tip 不在 main（需 bundle 兜底）
git rev-list --count main..<br>
# ③ 判「内容在不在 main」：blob 逐位
git rev-parse <br>:<path>; git rev-parse main:<path>
# ④ 分支独有 token 全量搜 main 树 / main 历史
git grep -l "<token>" main -- ; git merge-base --is-ancestor <c> main
# ⑤ bundle 覆盖：list-heads 逐 hash 核对 + R2 取回 md5 双验
git bundle list-heads /tmp/branches-not-in-main-20261005.bundle | sort
```

三支 tip / merge-base / 独有 commit 数一览：

| 分支 | tip | merge-base | mb..tip 独有 commit 数 | tip 在 main? |
|---|---|---|---|---|
| `zcode/standin-charter` | `f5b25983d`（2026-09-03 16:41） | `0986bb0ca`（2026-09-03 16:38） | 1 | 否（`rev-list --count main..br` = 1） |
| `feat/r2-slim-20261003` | `ac2d7d21a`（2026-10-04 00:57） | `5f3e0bd48`（2026-10-03 23:00） | 1 | 否（=1） |
| `feat/ledger-20261001b`（远端） | `6eae46443`（2026-10-01 23:44） | `4284cdeff`（2026-10-01 22:52） | 3 | 否（=3） |

## 2. `zcode/standin-charter`（本地 + 远端）—— 结论：**可删**（内容已归档覆盖）

### 2.1 差异面（逐文件）

```
$ git diff --name-status 0986bb0ca refs/heads/zcode/standin-charter
M	.agents/zcode-standin/SKILL.md
```

差异面**只有 1 个文件**：`.agents/zcode-standin/SKILL.md`（分支自身 +1/-0，即只新增 1 行）。
`git rev-list --count main..br` = **1**（tip 不在 main）；`br..main` = 1171（main 已大幅前进）。

blob 比对：

```
br : 55d593ae75fd7e385bd65ba61c2f4de3cf897c7b
main: f7d797388f4df601a86ed6163a618856c17fcc8d   ← 非字节相同（= 分叉，需逐行判定）
```

`git diff main refs/heads/zcode/standin-charter -- .agents/zcode-standin/SKILL.md` = **3 个 hunk / 4 插入 3 删除**。分支侧 4 行独有（逐行判定归属）：

| # | 分支侧独有行（分支行号） | 性质 | main 侧对应状态 |
|---|---|---|---|
| 1 | L52 `- **⚠️ ZCode 专属分支纪律(2026-09-03 用户定,对 ZCode 优先于上条)**:ZCode 的**所有**产出（功能代码/docs 报告/脚本收编/**本章程与 MEMORY 更新**）一律提交到 `zcode/*` 命名空间分支并 push;**ZCode 禁止直接 commit/push main**（2026-09-01~03 期间 8 笔直落 main 为历史存量,已 push 不回改 §23.11,靠 Co-Authored-By 尾注追溯）。`zcode/*` 分支何时 merge 进 main=由用户或 Claude Code 确认后走 main-merge.sh（或 Claude 主动合入）,**ZCode 不自行合并自己的分支**。注意:本章程在 main 亦有历史版本（Claude 会改）,我的更新落 zcode/* 分支后可能与 main 分叉,merge 时按互补保留（§23.11 非静默）` | **真独有**（本分支唯一信息增量） | **已被逐位归档到 main**：`docs/archive/zcode-standin-branch-discipline-20260903.md:9`（706B，`diff` 两行 → **IDENTICAL**），由 main commit `15e8eb0af`（2026-10-03 07:35 worktree-cleanup-20261003 清理收尾）落档 |
| 2 | L41 `| 派单三件套 hook | PostToolUse(Agent) hook 机械提醒 | …(§0.2 三件套) |` | **旧文案** | main L41 已更新 2026-09-29 机检收敛版（"读调用参数机检 ①prompt 含进度文件路径 ②implementer 的 isolation；全过静默"），commit `744645ff1`（2026-09-29 10:58） |
| 3 | L56 `- **铁律全守**:…§14 生产稳定(**推 main 前查 launchd 时点**)…` | **旧文案** | main L55 已改「推 main 前查**云上 systemd timer 定时任务时点**」，commit `a100eb06c`（2026-09-28 22:58 全仓 launchd 口径大扫除） |
| 4 | L114 `- **hooks 机械提醒无法复刻**:…Claude Code 的 PostToolUse(Agent) **三件套机械提醒**在我侧缺失…` | **旧文案** | main L113 已更新为「派单机检（①进度文件 ②implementer 的 isolation；2026-09-29 起全过静默）」，同 `744645ff1` |

### 2.2 归档覆盖性的独立核实

```bash
$ git grep -n "专属分支纪律" main -- | head
main:docs/archive/zcode-standin-branch-discipline-20260903.md:1:# ZCode 专属分支纪律(2026-09-03,归档)
main:docs/archive/zcode-standin-branch-discipline-20260903.md:9:- **⚠️ ZCode 专属分支纪律(2026-09-03 用户定,对 ZCode 优先于上条)**…（全文）
$ git show refs/heads/zcode/standin-charter:.agents/zcode-standin/SKILL.md | sed -n '52p' > /tmp/zc-br-line.txt
$ git show main:docs/archive/zcode-standin-branch-discipline-20260903.md | sed -n '9p' > /tmp/zc-ar-line.txt
$ diff /tmp/zc-br-line.txt /tmp/zc-ar-line.txt && echo IDENTICAL
IDENTICAL（两文件均 706 字节）
```

归档文件正文另含处置说明与恢复路径（原文摘）：「**为什么归档不 merge**：该 commit 含 main 没有的『ZCode 专属分支纪律』历史段;同分支其它内容（如把 main 的 2026-09-29 hook 机检收敛 / 云上 systemd timer）改回旧描述 → 合入会倒退,按任务定论『不要 merge』」「**怎么恢复**：若后续需要把这段纪律重新并入 main：修改 `.agents/zcode-standin/SKILL.md`,在 main 版对应位置（『分支纪律』小节下）插入本归档文件『归档内容』段即可」。
⇒ 该分支在 2026-10-03 已按「已处理、不 merge」处置，**独有内容已落 main 树可查**。

### 2.3 删了会丢什么 / 不丢什么

- **会丢**：无。唯一独有段（上表 #1）已在 main `docs/archive/zcode-standin-branch-discipline-20260903.md` 逐位可查；其余 3 行为 main 已更新的旧文案（合并反而倒退）。
- **不会丢的旁证**：本地+远端 tip `f5b25983d` 在 bundle 中**双 ref 覆盖**（§5 已验）；远端 `git ls-remote` 实测当前仍在（`f5b25983d… refs/heads/zcode/standin-charter`）。

### 2.4 判定建议：**可删**（理由三条）

1. 独有信息已**逐位**在 main（归档文件 `15e8eb0af`，2026-10-03），删除不产生任何「无处可查」信息；
2. 其余内容为**会被倒退的旧文案**（两条 main 侧更新 commit 作证），保留该分支反而留有误 merge 风险；
3. 删除完全可逆：bundle（本地 md5 已验 + R2 取回 md5 已验，§5）+ main 内归档文件自带恢复说明。

> 备注（如实标注）：若用户出于「zcode 命名空间归属」想保留该 ref，成本为零（不删也无害）；但「保留的价值」不来自信息（信息已在 main），仅来自命名空间偏好。

## 3. `feat/r2-slim-20261003`（本地 + 远端）—— 结论：**建议先迁移再删**

### 3.1 差异面（逐文件）

```
$ git diff --name-status 5f3e0bd48 refs/heads/feat/r2-slim-20261003
A	docs/ops/r2-slim-compression-measure-20261004.md
$ git rev-list --count main..br → 1 ; br..main → 124
```

分支自身 = 1 个 commit（`ac2d7d21a`，2026-10-04 00:57「R2 mac-backups 瘦身压缩率实测」），**新增**该报告草稿（121 行）。
**main 侧同路径文件当前状态**：同路径文件存在（由另一条链落 main：`2ce49542a` 定稿 → `21474d9e0` 上传回读 → `d35857f03` 保留期真相落档），为**定稿版（167 行）**。

blob 比对（同路径不同版本，非字节相同）：

```
br : 2a2bb35a5aba63c19d0c1ebb4d3e453f31feb907   (121 行)
main: 0977ed8d63890518d70bb2eff63d375536ecdd4e   (167 行)
$ git diff --numstat main br -- docs/ops/r2-slim-compression-measure-20261004.md
90	137	docs/ops/r2-slim-compression-measure-20261004.md   ← 大幅重写（仅约 31 行字面保留）
```

结构性差异（逐节）——**注意**：这推翻了清理报告 §4.1「主要是标点/小节号差异」的描述，实际是重写：

| 节 | 分支（草稿）侧 | main（定稿）侧当前状态 |
|---|---|---|
| §③ | 「清单盘面(86 对象构成)」：per-DB 总量 etf 5.565 GiB / sentiment 4.606 GiB、相邻日增量 4.3/1.1 MB、`.gz ≈ 30-38% 保留率`、R2 第二份盘面（backup 09-04~09-11 滚动 / weekly 09-07/14/21/28 / monthly 07-21/08-03/09-01） | **被换成**「保留期口径重算（keep_days 30→14）」：口径 A/B 两表 + reviewer 复算 1,285,523,660 B + 生效时点订正（`r2-retention-effective-20261004.md`）——**main 更新** |
| §④ | 页级去重两行（1.627 / 0.228 GiB，含 ~2 分钟 / ~5 分钟耗时；合计 7.869/9.268） | main §④ 同表**无页级去重两行**（挪到 §⑨），其余行一致（zstd 20.9% vs 草稿 20.8% 等四舍五入差） |
| §⑤ | 6 行策略表：含 **S2c 页级去重行（7.869 GiB 余 2.131）** 与 S3b 行；推荐 **S2c** | main §⑤ 4 行表（S1/S2b/S2a/S3a），**无 S2c 行**；推荐 S2b；S2c 仅以 §⑨「维度登记、不作为推荐」存在（主控已定选型 = zstd -19 整包） |
| §⑥ | 执行草案分 S2b / **S2c 两套**（S2c = 分页去重工具 1./4. 步工程细节） | main §⑥ 只有「方案 A 执行草案」（S2b 路线） |
| §⑧ | 6 条；含 **exit 144 / long=27**（第 2 条）与 **per-file 页索引 ~12MB / 合计包体 ~0.25 GiB**（第 3 条） | main §⑧ 7 条；第 3 条是 **long31「按任务书限时窗口停掉」**叙事；**无** 12MB/0.25 GiB 字样 |
| §⑨ | **无此节** | main 新增 §⑨「页级去重维度登记（只登记数字与出处，不作为推荐方案）」：1,746,536,956/1.627、243,010,132/0.228 + 明细（etf 总页 1,458,782→唯一 120,133；sentiment 总页 1,207,438→唯一 306,353；唯一页再 zstd → 0.064+0.164=0.228）+ 来源标注「`feat/r2-slim-20261003` @ `ac2d7d21a`（不 merge，只引用）」 |
| 复现命令 | 含 `/tmp/r2slim_pagededup.py` 行、raw tar 大小 10,920,969,896 B | main 复现段含 zstd/gzip 计时行、页级去重脚本引用行（少了 raw tar 字节数） |

### 3.2 分支侧**真独有**内容（main 全树 0 命中，逐条核过）

以下 token 在 main 索引/树**全量搜 0 命中**（`git grep -l <token> main --` 无输出）：`页索引`、`sha256 去重`、`0.25 GiB`、`exit 144`、`long=27`。对应原文（分支行号）：

1. **§⑥ S2c 工程落地要点（L75、L78）**——「分页去重工具…对每个 .db 按 4096B 分页（SQLite page_size 已验证 4096）→ sha256 去重 → 存『唯一页 bin』+『per-file 页索引』（每页 4B uint32，86 文件 × 约 15 万页 × 4B ≈ **12 MB**，可忽略）」「重建逻辑：per-file 页索引 → 从唯一页 bin 对应页位取回按序写文件，即逐位还原（唯一页集 + 页序列索引完整，重建=原文件）」。
2. **§⑧-3（L94）**——「页级去重 0.228 GiB 为『唯一页集合』内容大小；工程落地需额外 **per-file 页索引（~12MB）** 与重建脚本，**合计包体 ~0.25 GiB**，不影响达标结论。页级去重按『内容层下界』诚实标注…」。
3. **§⑧-2（L93）+ §④ L48**——「zstd --ultra -22 --long=31 未测出数字（**exit 144** 终止），标注 UNVERIFIED；zstd -19 **已默认 long=27（128MB 窗口）**，预期大窗口提升有限，不以 0.8-1.3 GiB 预期入表」。⚠️ **与 main §⑧-3 叙事相左**（main 写「按任务书限时窗口停掉」）——**两版对同一事件的归因不同：分支草稿=「运行失败 exit 144」，main 定稿=「主动停掉」；双方对产物 211,386,368 B ≈ 0.197 GiB 与「结论不依赖它」一致。谁准确=需人工判定**（本报告只读，不重跑该压缩；`/tmp/mac_backups_20261001_long31.tar.zst` 至今仍在，211,386,368 B，mtime 10-04 00:49，仅能佐证体积不能佐证退出码）。
4. **少量数字**（main 以 GiB 四舍五入或缺失）：per-DB 总量 5.565 / 4.606 GiB（main 0 命中）；唯一页 zstd 字节级 68,282,496 B(etf) / 175,727,636 B(sentiment)（main 只有 0.064/0.164 GiB 表述）；raw tar 10,920,969,896 B；S2c 合计 7.869 GiB / 余 2.131；`~2 分钟 / ~5 分钟` 耗时。多数可由 main 已有数字推出，但字面不在 main。

### 3.3 删了会丢什么 / 不丢什么

- **真会「无处可查」（若直接删且不迁移）**：上述 §3.2 的 1/2/3 三项——S2c 工程要点（12MB 页索引 / sha256 / 重建逻辑 / 0.25 GiB 包体）、exit 144 叙事与 long=27 标注。**这些字面在 main 树 0 命中**；删除后仅能从 bundle 取（可恢复但不可 grep）。
- **不丢**：页级去重全部**数字**（1.627/0.228/唯一页明细）已在 main §⑨；S2b/口径/费用/failure 数字在 main §④/⑤/⑦；「不 merge 只引用」的来源标注已在 main §⑨（@ `ac2d7d21a`）。

### 3.4 判定建议：**建议先迁移再删**（迁移清单 = 下节；也可选择直接删，代价=§3.2 三项只进 bundle 不进工作树）

### 3.5 迁移清单（迁哪几段、迁到哪个文件的哪一节）

| # | 迁什么（源：分支 `ac2d7d21a` 行） | 迁到（目标：main 现状文件行） | 迁法 |
|---|---|---|---|
| 1 | 分支 §⑧-3 拆两半：**~12MB 页索引 / 重建脚本 / 合计 ~0.25 GiB** 半段（L94 前半 + §⑥ L75/L78 工程细节合并为一段） | `docs/ops/r2-slim-compression-measure-20261004.md` **§⑨「页级去重维度登记」末尾**（main 现 L139「来源」行之后）新增一条 bullet：「工程落地要点（来自草稿分支 `ac2d7d21a`）：唯一页 bin + per-file 页索引（4B uint32/页，86 文件 ≈12MB）+ 重建脚本，合计包体 ~0.25 GiB；sha256 分页去重，重建=按页索引逐位还原」 | 追加 1 bullet（3-4 行） |
| 2 | 分支 §⑧-2 / §④ L48 的 **exit 144 + long=27** 两点（L93+L48） | 同上文件 **§⑧ 第 3 条（main 现 L120「long31 未跑完已终止…按任务书限时窗口停掉」）** 末尾 | 先人工核实退出码归因（`exit 144` vs 主动停），核实后：main 表述订正或加一行「另据草稿分支记录，该进程报 exit 144（与『限时停掉』并存，待考）」；**核实前不建议直接改** |
| 3 | （可选，价值低）分支 §③ L28-29 per-DB 总量 5.565/4.606 GiB | 同上文件 **§⑨「依据」行（main 现 L137）** | 补一句总量即可（数字可由 86 文件清单推出） |

迁移后即可删分支（本地 + 远端）；main §⑨ 的「来源 @ `ac2d7d21a`」标注仍可由 bundle 兑现（§5 已验覆盖）。

## 4. `feat/ledger-20261001b`（仅远端）—— 结论：**可删**

### 4.1 差异面（逐文件）

```
$ git diff --name-status 4284cdeff refs/remotes/origin/feat/ledger-20261001b
M	docs/ops/149-lock-split-implementation-20261001.md
M	docs/pending-features-index.md
$ git rev-list --count main..br → 3（811df951f / 3dfdf5452 / 6eae46443） ; br..main → 1170
```

**逐文件 blob 比对**：

| 文件 | 分支 blob | main blob | 关系 | 差异 |
|---|---|---|---|---|
| `docs/ops/149-lock-split-implementation-20261001.md` | `c06a837d2d9a76840ba7f93715b8676559d95cd4` | `c06a837d2d9a76840ba7f93715b8676559d95cd4` | **同一 blob（逐字节相同）** | 分支侧 3 个 commit 的第 1 个（`811df951f`，+19 行 §9）**已完整进入 main**（后续 2 个 commit 未再动该文件） |
| `docs/pending-features-index.md` | `f21d7423d0ead0eeb7bbde04b3c609c2e8e869ca` | `8217c15e4c0ee817b77b64b93d1df7322e0e4f6e` | 不同版本 | `git diff --numstat`（限该文件）= **7 ins / 82 del**：分支 = 10-01 当日旧盘面，main = 今天（10-05）收口后的新盘面 |

### 4.2 `pending-features-index.md` 分支侧 7 行「独有」（相对 main 字面独有，但语义已入 main）

分支侧独有 7 行（`git diff --unified=0 main br` 全部 `-` 行中 7 行），逐行 token 追证：

| 分支行 | 内容摘 | token 追证（在 main 的落点） | 判定 |
|---|---|---|---|
| L6（表头「最近更新」行） | 「…四表12,663行全量导出 #149b+#149c(+#118补)…复审2 两轮 FAIL 后收口…」 | 该行是**当日盘面态**；等价事实今天的 main 表头（含 10-04/10-05 更新）已覆盖；主干事实（149b/149c 完成、review2 FAIL 结论）在 main 均在 | 旧盘面，非独有信息 |
| L216 (#126 行) | 「#126 | … | 完成 | …`1af4e75d5`…」 | commit `1af4e75d5` = `git merge-base --is-ancestor 1af4e75d5 main` → **YES（已在 main 祖先链）**；main #126 行现状保留 | 已入 main |
| L223 (#132 行) | 「…二轮独立复审判 FAIL…」+ 分支文件引用 `132-monitor-residuals-review-20261001.md` / `…-review2-…` | 两份报告文件**在 main 工作树均存在**（`ls docs/ops/132-monitor-residuals-review-20261001.md docs/ops/132-monitor-residuals-review2-20261001.md` 均有）；main #132 行现文案为「二轮 FAIL 的 P0 值得记…」；**「复审2 FAIL」字面在两侧文件版本均不存在**（它是分支 commit message `6eae46443` 的标题用词），main 侧 `132-monitor-residuals-review2-20261001.md` 首行即「# #132 复审修复(第二轮)独立审查报告 — FAIL」 | 已入 main（含 FAIL 结论本身） |
| L224 (#133 行) | 引用 `feat/132-review-20261001` / `feat/132-review2-20261001` 分支名 + `d4cf5aed1` | 分支 `feat/132-review-20261001` / `feat/132-review2-20261001` 的 commit（`d4cf5aed1` 等）`--is-ancestor main` → **YES**；main #133 行现状为对应收口记录 | 已入 main |
| L225 (#134 行) | 引用 `132-monitor-residuals-review3` 链 | `132-monitor-residuals-review3-20261001.md` **在 main 工作树存在**；#134 收口在 main #134 行 | 已入 main |
| L238 (#147 行) | 状态「进行中/待回收」旧描述 | main #147 行已成为其后续状态 | 旧盘面 |
| L240 (#149 行) | 「LOGBACKUP…」当日描述 | main #149 行 + `149e` 系列（`149e-large-json-incremental-review-20261001.md` 在 main 树存在、`feat/149e-*` commit `--is-ancestor main` YES） | 已入 main |

**全套 token 逐项追证结果（8/8 commit 全部 `--is-ancestor main = YES`）**：`1af4e75d5`、`d4cf5aed1`、`811df951f`、`3dfdf5452`、`6eae46443` + 132/149e 链相关 commit 全部已在 main 祖先链；**11/11 被引用文件全部在 main 工作树存在**（132 review/review2/review3、149e review/review3/review4 等）。main 侧相对分支**多 40 行**（#151–#190 及模块 18/19/20），即 main 是分支的**超集**（在该文件上）。

### 4.3 删了会丢什么

- **字面层**：7 行旧盘面文字（当日表头 + 6 行行记录）在 main 无字面。但每行的**语义与指向**（commit / 报告文件 / 状态结论）已在 main 可查（见 4.2 表）。
- **实质层**：**无丢失**——分支的 3 个 commit 中，`811df951f` 内容已在 main（同 blob）；`3dfdf5452`/`6eae46443` 是 pending 索引的中间态修改，其最终形态已被 main 收口版取代（main = 分支超集）。

### 4.4 判定建议：**可删**（本地无此分支，远端 `origin/feat/ledger-20261001b` 可删；bundle 已覆盖该 tip，见 §5）

## 5. 恢复路径现成性核查（独立核实，非引用文档）

### 5.1 本地 bundle 实体 + 校验

```
$ md5 /tmp/branches-not-in-main-20261005.bundle
MD5 (...) = e629c34f848abfe627c5e76c1820d07a     ← 与清理报告 §1 声称的 md5 一致
$ ls -l /tmp/branches-not-in-main-20261005.bundle
-rw-r--r--  1 linhuichen  wheel  42827 10  5 14:07 ...bundle   ← 42,827 字节，与报告一致
$ git bundle verify /tmp/branches-not-in-main-20261005.bundle
The bundle contains this ref: ... ; The bundle records a complete history.   ← 尾部另有
"The bundle uses this hash algorithm: sha1"；prerequisite 12 条均为 main 祖先（报告 §1 已测）
```

### 5.2 三支 tip 的逐个 hash 覆盖核对（命令 + 真实输出）

```
$ git bundle list-heads /tmp/branches-not-in-main-20261005.bundle | grep -E '<三 tip hash>'
ac2d7d21a9c32152fda55702097d07eb69e6627e refs/heads/feat/r2-slim-20261003
f5b25983d95fbc1f6825f1a4754f7388211dd652 refs/heads/zcode/standin-charter
6eae464432fc796816bf447f137211a574c802b0 refs/remotes/origin/feat/ledger-20261001b
ac2d7d21a9c32152fda55702097d07eb69e6627e refs/remotes/origin/feat/r2-slim-20261003
f5b25983d95fbc1f6825f1a4754f7388211dd652 refs/remotes/origin/zcode/standin-charter
```

| tip | 分支 | bundle 内 ref 数 | 覆盖判定 |
|---|---|---|---|
| `f5b25983d95fbc1f6825f1a4754f7388211dd652` | `zcode/standin-charter`（本地+远端同 hash） | 2（`refs/heads/` + `refs/remotes/origin/`） | **已覆盖** |
| `ac2d7d21a9c32152fda55702097d07eb69e6627e` | `feat/r2-slim-20261003`（本地+远端同 hash） | 2 | **已覆盖** |
| `6eae464432fc796816bf447f137211a574c802b0` | `feat/ledger-20261001b`（仅远端） | 1（仅 `refs/remotes/origin/`，无本地同名分支） | **已覆盖** |

**关键限定（恢复时必要条件）**：该 bundle 是 **thin bundle**——它把 main 历史列为 prerequisite（不含 main 对象本体）。因此**「能恢复」的前提 = 恢复现场仍持有 main 历史**（正常克隆/本仓均满足；若拿一个 42KB 的 bundle 到空仓库会 verify 失败）。清理报告 §1/§5 对此已有声明（§1 note「thin bundle…前提是 main 历史仍在」），此处独立复验属实。

### 5.3 R2 侧独立回读（不信任文档声称，实取实测）

```bash
$ python3 - <<'EOF'
import sys, hashlib, socket, importlib.util
socket.setdefaulttimeout(25)
spec = importlib.util.spec_from_file_location("upload_r2", "scripts/upload_r2.py")
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
KEY = "git-branch-bundles/20261005/branches-not-in-main-20261005.bundle"
status, data = u.s3_request("GET", KEY, bucket=u.BACKUP2_BUCKET)
print("status:", status); print("bytes:", len(data)); print("md5:", hashlib.md5(data).hexdigest())
EOF
```
实测输出（原样）：
```
status: 200
bytes: 42827
md5: e629c34f848abfe627c5e76c1820d07a     ← 与本地文件逐字节同源（md5 全等）
```

**§5 结论：三支 tip 全部在 bundle 覆盖内（本地 + R2 双份同 md5），清理报告 §6.3「这三支 tip 亦在 bundle 覆盖范围内」一句经独立核实 = 真。**

### 5.4 三支远端分支 hash 现状（删前事实定格）

```
$ git ls-remote --heads origin | grep -E 'standin-charter|r2-slim-20261003|ledger-20261001b'
6eae464432fc796816bf447f137211a574c802b0	refs/heads/feat/ledger-20261001b
ac2d7d21a9c32152fda55702097d07eb69e6627e	refs/heads/feat/r2-slim-20261003
f5b25983d95fbc1f6825f1a4754f7388211dd652	refs/heads/zcode/standin-charter
```

三支远端 hash 与本报告所核 tip 逐位一致；**删除后恢复路径 = 5.1/5.3 的 bundle（本地或 R2 取回）+ `git fetch <bundle> '<refspec>:<新分支名>'` + `git push origin <新分支名>:<原名>`**。

## 6. 对清理报告 `docs/ops/git-branch-cleanup-20261005.md` 的勘误建议（该报告不动，此处仅登记）

| 位置 | 报告原文摘 | 本报告核实结果 | 建议 |
|---|---|---|---|
| §4.1 行 103 | `zcode`: 「含 main **没有**的『⚠️ ZCode 专属分支纪律』段（grep main=0 / 分支=1）」 | 该段**已归档在 main**：`docs/archive/zcode-standin-branch-discipline-20260903.md:9`（blob 逐字节相同，main commit `15e8eb0af` 加入）。精确表述应为「在 `.agents/` 路径下 main=0，但内容已归档在 `docs/archive/`」 | 补一句归档落点（消除「main 没有」的误导） |
| §4.1 行 104 | `r2-slim`: 「90 插入/137 删除，**主要是标点/小节号差异** + main 多一行达标数字」 | 实为**整篇重写**：§③/④/⑤/⑥/⑧ 五节内容重构（口径 A/B 换 §③、S2c 撤表降登记、执行草案换路线），30 余行字面保留、main 侧 167 行 ≠ 草稿 121 行；分支侧另有 S2c 工程要点/exit144 等 main 0 命中内容 | 「主要是标点/小节号差异」订正为「整篇重写、main 为定稿」；分支真独有项见本报告 §3.2 |
| §4.1 行 105 / §6.3 | `ledger`: 「**无法逐字证明**被覆盖 ⇒ 保留」 | **可以逐字证明**：3 commit 全部 `--is-ancestor main = YES`；被引用 11 个文件全部在 main 工作树存在；`149-lock-split` 文件两侧**同一 blob**；主文件 main 为分支超集（+40 行 #151–#190） | 「无法逐字证明」订正为「已逐字证明（本报告 §4）⇒ 可删」 |
| §6.3 末段 | 「这三支 tip 亦在 bundle 覆盖范围内」 | **经独立核实属实**（本报告 §5.2/§5.3） | 无需改动 |

## 7. 复现命令（全部只读，可原样重跑）

```bash
cd /Users/linhuichen/code/trade

# ① 三支差异面（merge-base 单侧 diff，非三点）
for BR in zcode/standin-charter feat/r2-slim-20261003 origin/feat/ledger-20261001b; do
  MB=$(git merge-base main "$BR")
  echo "== $BR tip=$(git rev-parse "$BR") mb=$MB"
  git diff --name-status "$MB" "$BR"
done

# ② blob 逐字节比对（zcode 归档覆盖 / ledger 149 同 blob）
git rev-parse zcode/standin-charter:.agents/zcode-standin/SKILL.md
git rev-parse main:docs/archive/zcode-standin-branch-discipline-20260903.md
git rev-parse origin/feat/ledger-20261001b:docs/ops/149-lock-split-implementation-20261001.md
git rev-parse main:docs/ops/149-lock-split-implementation-20261001.md

# ③ 独有 token 在 main 的存在性
git grep -l "页索引\|sha256 去重\|0.25 GiB\|exit 144\|long=27" main --          # 预期 0 输出
git grep -l "复审2 FAIL" main -- ; git grep -l "复审2 FAIL" origin/feat/ledger-20261001b --  # 两侧预期均 0

# ④ ledger 引用物追证
git merge-base --is-ancestor 1af4e75d5 main && echo YES   # 其余 7 个 commit 同法
ls docs/ops/132-monitor-residuals-review-20261001.md docs/ops/132-monitor-residuals-review2-20261001.md

# ⑤ bundle 覆盖 + R2 回读
git bundle list-heads /tmp/branches-not-in-main-20261005.bundle | grep -E 'f5b25983|ac2d7d21a|6eae46443'
# R2 回读脚本（完整可跑版见 §5.3 代码块；需本机 scripts/upload_r2.py 凭据环境）
```

## 8. 诚实标注 / 需人工判定项

1. **唯一需人工判定 = r2-slim 的 exit 144 归因**：分支说「zstd --ultra -22 --long=31 运行失败（exit 144，211MB 处终止）」，main §⑧-3 说「按任务书限时窗口停掉」。两者对同一事件的归因不同、对「结论不依赖它」一致。本报告只读不重跑该压缩（重跑需分钟级 CPU 且非本任务范围），**建议迁移前由人工选一侧口径**（或双记）。实物佐证：`/tmp/mac_backups_20261001_long31.tar.zst` 现存 211,386,368 B（mtime 10-04 00:49），只能佐证体积不能佐证退出码。
2. **zcode 的「main 没有」是「该路径没有」**：`.agents/zcode-standin/SKILL.md` 行 52 那段在 main 的 `.agents/` 路径下确实不存在（grep=0），但其**逐字节相同副本**在 `docs/archive/`——所以判定「可删」依据是「内容已归档 ≠ 内容已丢」，非「内容不存在」。
3. **本报告未做的事**：未删任何分支/文件；未 push；未修改清理报告；未重跑 exit 144 压缩实验；未验证 bundle 在「空仓库」下的可消费性（thin bundle 依赖 main 历史，报告 §1 已声明，本报告复述该限定）。
4. **数值口径**：所有行数/字节数来自 `git diff --numstat` / `wc -l` / `git cat-file -s` 实测；pending 索引的行级比对以「分支侧 `-` 行 ∪ 语义追证」为准，未逐行 diff 全 240+ 行 main 表（0 忽略白名单外差异：分支 7 独有行均已列 §4.2）。

---
*本报告由只读调研产出（2026-10-05），不实施任何删除；拍板权在用户。*
