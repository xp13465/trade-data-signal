> 落档:2026-10-22(原样归档)
> 关联:`docs/ops/batch-fix-20261022.md`、`docs/ops/version-consistency-rca-20261022.md`

# §24⑤ 版本一致性校验 TOCTOU 加固 —— 实施报告(2026-10-22)

残留后台任务:无(全量 pytest 三轮均 nohup 跑完并回收,未留 `moved to the background`)。

## 0. 结论
- **B1 已实施并逐条验证通过**(校验窗口自洽:只取一次 HEAD / 重建前快照 min / 结束复验 HEAD / 变化只重试一次 / 仍变 FAIL 且消息写明「校验期间 HEAD 变化」;脏工作区检测与 PASS 语义不变)。
- **B3 未做**(理由见 §7:集中钉版本需 4 行 diff 超「≤3 行」门槛,且 `terser@5.51.2` 会改变 npx 缓存命中路径、引入一次联网解析,属新增失败面;建议与依赖锁一并做)。
- commits:`70939bf98`(fix)+ `8113a7226`(test 补「缺 min 版」分支);分支 `feat/fix-version-check-toctou-20261022`(base = origin/main `54a4fcf30`;**未 push main、未 force**)。

## 1. 改动文件:行
| 文件 | 位置 | 改动 |
|---|---|---|
| `scripts/build_min.py` | `:77` `_read_source(..., head=None)` | 新增可选 `head` 参数 |
| | `:91` `ref = head or "HEAD"` | 读源改用 `git show <ref>:<path>`,固定 sha 时中途 pull 不影响 |
| | `:100` 告警文案 | 「不在 git HEAD」→「不在 git {ref}」(固定 sha 时日志不再误导) |
| | `:184` / `:195` `build_pairs_in_memory(..., head=None)` | 新增可选 `head` 并透传;**默认 None ⇒ 写文件路径行为逐字不变** |
| `scripts/check_version_consistency.py` | `:20-30` 模块 docstring | 校验3 描述补 TOCTOU 加固口径 |
| | `:197` `_git_head_sha()` | 单次 `git rev-parse HEAD`(取不到返 None) |
| | `:218` `_snapshot_min_md5()` | 重建**前**快照 8 个 min 文件 md5 |
| | `:230` `_rebuild_from_head()` | 按固定 sha 调 build_min(单独成函数,便于单测注入) |
| | `:239` `_check3_once()` | 单次窗口:快照 → 按固定 sha 重建 → 比快照(缺 min 版分支改从快照读) |
| | `:273` `check3()` | 两段式:head0 → 比对 → head1;变化 ⇒ 重试一次(head1 固定、重新快照) → head2;仍变 ⇒ FAIL「校验期间 HEAD 变化(疑似并发 git pull),已重试 1 次仍不稳定: head a→b→c;本次比对结果不可信…」,不再输出 min 过期/工作区源脏 |
| | `:298` 追溯行 | 输出 `head=<sha12> min_snapshot=[dst=hash8 …]` |
| `scripts/tests/test_277_version_check_toctou_20261022.py` | 新增 177 行 / 7 用例 | 见 §2 |

## 2. 证据用例逐条结果(实现前写定,实现后逐条跑)
| # | 用例 | 结果 |
|---|---|---|
| 1 | 正常态:干净 HEAD 真跑 | **PASS**。克隆 HEAD `dc242231d` 后实跑 `--checks 3`:`build_min 映射 8 对 min 内容均 == git HEAD 源重建(0 对跳过)`;`head=dc242231dd60 min_snapshot=[common.min.js=075f1101 purpose-notes.min.js=22306377 kelly-review-notes.min.js=3ed58633 kelly-reports-content.min.js=bb7b705c app.min.js=87dbf668 lab.min.js=987eacfb style.min.css=711f7e30 lab.min.css=fd3f4258]`。其中 22306377/87dbf668 与 RCA 记录一致 |
| 2 | 竞态模拟(桩):HEAD A → 重建后 B → 重试 B 稳定 | **PASS**,断言 `_git_head_sha` 恰好调用 **3 次**(= 只重试 1 次)、输出含「已重新固定 sha 重试 1 次」、追溯行 head = B 前 12 位;A 的重建故意返回错误内容,证明采用的是重试结果而非「第一次碰巧 PASS」 |
| 3 | 持续变化:A→B→C | **FAIL**,消息含「校验期间 HEAD 变化(疑似并发 git pull), 已重试 1 次仍不稳定: head aaaaaaaaaaaa → bbbbbbbbbbbb → cccccccccccc」;**不含**「min 过期」也不含「工作区源脏」;python 调用次数 3 |
| 4 | 真脏工作区(源改 + min 由脏源生成) | **FAIL**,消息含「工作区源脏」 |
| 5 | min 真过期(干净源 + 旧 min) | **FAIL**,消息含「min 内容与 git HEAD 源重建不一致」 |
| 5b | 源在 / min 文件缺失(改动面 None 分支) | **FAIL**,消息含「缺 min 版」 |
| + | 真实并发 pull 复刻:重建过程中**真**提交新 HEAD 且源+min 同步换新(等价 main-merge 第 10 步 ssh 云上 pull) | **PASS** 且带「已重新固定 sha 重试 1 次」(不打桩 rev-parse/重建,只桩掉外部压缩器) |

## 3. 变异测试(≥2 个真红,还原绿)
- **变异 A「去掉 HEAD 变化检测」**(`if head0 and head1 and head0 != head1:` → `if False:`):用例 2 / 3 / 真实竞态 **3 红**,其余 4 绿。
- **变异 B「去掉重试」**(检测到变化直接 return FAIL,不重新比对):用例 2 / 3 / 真实竞态 **3 红**,其余 4 绿。
- 两次 `git checkout --` 还原后 7 用例全绿(1.06s)。

## 4. 全量 pytest(L52:改 `scripts/` 任何源码必跑全量)
- 终态(含 7 用例):**1172 passed, 2 skipped in 141.27s**
- 中间轮(含 6 用例):1171 passed, 2 skipped in 142.14s
- 无 FAILED;2 skip 与本次改动无关(既有条件跳过)。

## 5. 边界维度清单(§5.8③实施关出口,tester skill §5.3.1 七轴)
| 轴 | 边界 | 测/不测 | 结果或理由(来源) |
|---|---|---|---|
| 输入域 | 有 git 仓库 + 干净工作区 + min 正确 | 测 | 用例 1 实跑 PASS |
| 输入域 | 非 git 环境 / `GIT_REPO` 无效(→ repo=None) | 测(手工) | `/tmp/toctou-nogit` 实跑:`head=n/a`,`min_snapshot` 全 missing,全 skip ⇒ PASS,不崩、不重试(改动点:head 为 None 分支) |
| 输入域 | worktree 里 `.git` 是**文件** ⇒ `_git_repo_of` 返 None | 不测新增路径 | 既有行为(`docs/architecture-review-20260903.md:169` 已记载),本次未改该解析逻辑 |
| 输入域 | 8 对里部分源缺失 | 测 | 6 用例 fixture 只放 CSS 两对,其余走 skip 路径,输出「跳过(源不存在)」不 FAIL |
| 输入域 | 源在 / min 缺 | 测 | 用例 5b FAIL「缺 min 版」 |
| 状态组合 | 脏工作区 + HEAD 同时变化 | 不测 | 重试后按新 sha 判;组合语义 = 用例 2(重试)+ 用例 4(脏工作区)两分支叠加,无独立代码路径 |
| 时序 | HEAD 在第一次 rev-parse **之前**变化 | 不测 | 整个窗口都用新 sha,无错位(设计上不可观测);唯一的时间边界是首/末 rev-parse |
| 时序 | HEAD 在快照前 / 重建中 / 重建后变化 | 测 | 真实竞态用例在**重建中途**推进 HEAD;桩用例覆盖首末 rev-parse 不一致 |
| 时序 | HEAD 变走又变回同一 sha | 不测 | fast-forward pull 产生不了此形态;且同 sha ⇒ 内容同 ⇒ 比对照样成立 |
| 上下游依赖 | `deploy.sh:532`(默认全跑 1,2,3) | 测(手工) | 在克隆上实跑 `--checks 1,2` PASS(rc=0)+ `--checks 3` PASS;退出码语义 0/1 未变 |
| 上下游依赖 | `main-merge.sh:254` 调用点 | 核(grep) | 该处是 **build_min 写路径**(不传 head ⇒ 行为不变);main-merge **不直接**调用本脚本(grep 仅 deploy.sh / ci.yml 两处) |
| 上下游依赖 | CI `ci.yml:118`(1,2)/`:131`(3) | 核 | 1,2 不涉及改动;3 受益(`--checks 3` 同一函数) |
| 上下游依赖 | `build_pairs_in_memory` 其他调用方 | 核(grep) | 唯一调用方为 check_version_consistency(已改);`build_min.main()` 不传 head |
| 极端值 | 8 对全缺(空站) | 测(手工) | 同上 /tmp/toctou-nogit PASS |
| 极端值 | min 为 0 字节 | 不测 | 与「min 内容不一致」同一比较分支(用例 5 覆盖该分支形状) |
| 回退路径 | `git show` 失败(源不在该提交)→ 回退工作区 + 告警 | 不测 | 既有语义,本次仅把告警文案改成带 ref;行为未变 |
| 回退路径 | 重试后仍不稳定 → FAIL 且不误报 | 测 | 用例 3 |
| 并发与重入 | 并发 git pull 与校验窗口重叠 | 测 | 桩用例 2 + 真实 HEAD 中途前进用例 |
| 并发与重入 | 两个 checker 并行跑 | 不测 | 纯只读(快照读 min + `git show` + rev-parse),无共享状态/写盘 |
| 耗时 | 新增成本 | 测(实跑) | 每次 check3 增加 8 次文件读 + 1~2 次 rev-parse;克隆实跑整体仍在数十秒量级(与改前同阶),最坏重试翻倍一次 |

## 6. 同类错误面清单(§23.2)+ 举一反三(§23.3)
- **同型实现只有一处**:grep 全 `scripts/` 的 `git show HEAD` / `rev-parse HEAD`,仅 `build_min.py`(写路径,不做磁盘比对)与本脚本(唯一 check3)。无第二套实现需同步。
- **同族但窗口不同,本次不改(上报主控定夺)**:`scripts/check_version_progress.py:341-343` 也是「先读工作区 index.html、再读 HEAD/HEAD^」,理论上并发 pull 有极短错位窗口,但它无几十秒重建、窗口是毫秒级,且属另一脚本另一任务;本次不动,建议主控登记后续评估。
- **受益调用点 = 2 处**:`deploy.sh:532`(默认全跑,上线硬门禁)与 `ci.yml:131`(`--checks 3` 前瞻检查)。`main-merge.sh:254` 不受影响(写路径)。
- **不受影响面**:§21 算法公示(无算法/数值)、§22 数据一致性(无数据产物)、§24 前端版本串(未改前端源码、**未 bump**)。
- **已知限制(未改)**:worktree 中 `.git` 为文件 → `_git_repo_of` 返 None → 校验3 退化为读工作区源(既有行为,已在文档记载)。所以本报告的用例 1 是在 `/tmp` 的 HEAD 克隆(真 `.git` 目录)上跑的,与云上/CI 形态一致。

## 7. B3(npx terser 版本钉)决定:未做
1. 「一处集中钉」需新增 1 行常量 + 3 处引用 = **4 行 diff**,超出任务书「≤3 行才做」门槛 1 行;
2. `npx --yes terser@5.51.2` 与现 `npx --yes terser`(命中缓存 latest)在 npx 里是**不同缓存键**,云上首次部署会走一次联网解析/安装 —— 新增失败面;而 terser 失败在本链是「静默 skip 配对」(不 FAIL),等于弱化校验;
3. 建议与「build_min 依赖锁(package.json + package-lock / npm ci)」一并做,不在本次小修里夹带。

## 8. 纪律自证
- worktree 隔离;分支从 origin/main 新建,中途 origin/main 前进(`dc242231d` → `54a4fcf30`)已 **rebase 对齐**(`merge-base --is-ancestor` 返回 0),rebase 无冲突、无静默覆盖。
- 只 push feat(远端 `8113a7226`),main 仍 `54a4fcf30`;**未 force**。
- **零外发**:未跑 `deploy.sh`、未调用 `notify.py`、未触发通知;真机实跑只在 `/tmp/toctou-case1`(HEAD 克隆)与 `/tmp/toctou-nogit` 上做只读校验。
- 未碰云上/生产/systemd;未改前端源码 ⇒ 不 bump 版本串(机制 C 由主控 main-merge 统一处理)。
- 每条 Bash 显式 timeout;未出现 `moved to the background (ID:` 提示(全量 pytest 用 nohup + pid/日志轮询,已跑完回收)。
- pending 索引 `#277` 仍为「修复中(2026-10-22 派单)」,建议主控 merge 时改状态。
## 9. 审查差集补测(reviewer 指出的 2 条测试缺口,同分支续跑)
reviewer 变异证据:M2(把快照挪到重建之后)、M4(重建忽略固定 sha,`head=None`)两种改坏下原 7 个用例**全绿** ⇒ 两条核心机制当时没被钉住。已补 2 条桩级用例:
- `test_m2_snapshot_must_be_taken_before_rebuild`:重建窗口内把 min 换成新内容(HEAD 不动,隔离"快照时机"这一个变量);正确实现按**重建前**快照判定 ⇒ PASS,追溯行 `min_snapshot` 给旧 hash、不含新 hash。把 `_snapshot_min_md5` 挪到重建之后 ⇒ 本用例必红。
- `test_m4_rebuild_must_use_fixed_head_sha`:桩掉 `build_min._read_source` 记录收到的 head,断言**全程 == 首次 `git rev-parse HEAD`**,且追溯行含该 sha;重建传 `head=None` ⇒ 本用例必红。
- 实跑证据(worktree 内,逐个变异→还原):
  - 变异 M2(`# MUTATION-M2 快照挪到重建之后`)⇒ `1 failed, 8 passed`,只有 M2 用例红;
  - 变异 M4(`_rebuild_from_head` 内 `head=None` + `# MUTATION-M4 忽略固定 sha`)⇒ `1 failed, 8 passed`,只有 M4 用例红;
  - `git checkout -- scripts/check_version_consistency.py` 还原 ⇒ `9 passed in 1.33s`;
  - 还原后 `git status --porcelain` 仅剩测试文件的 `M`(无源码残留变异)。
- 补测后单文件:`9 passed in 1.33s`。

## 10. pending 索引更新(2026-10-22 第三批,只改指定行)
- `#266` 状态列改为「一期已上线(代码 main `2b2841454` / D1 行数 / worker 401 / **前端已上线**三站 app.min.js md5 `87dbf668`、UI 锚点 5/5、版本串 `20261022`/SW `v6-20261022-a649`、overview date=20261021;二期未动)」。
- `#277` 状态列改为「**已修复(审查 PASS,2026-10-22;待合并 main)**;B1 落地…;B3(npx terser 钉版本)未做(理由见实施报告)」。
- 表尾新增 4 行:#281 `check_version_progress.py:341-343` 同族竞态 / #282 rev-parse 瞬时失败被当「窗口稳定」/ #283 残余微窗口(main-merge 第 10 步 pull 与 deploy 串行)/ #284 非 git·unborn HEAD 校验空转(既有行为),均为「待议(2026-10-22 登记)」。
- 「最近更新」追加第三批一行(按 §6④ 前两批历史行原样保留;协调稿里的「已上线上线」重复字按语义修正为「已上线回核」)。
- 自验:`git diff -U0` 只含上述 4 类改动(266/277 两行 + 4 新增行 + 1 最近更新行),**#271/#273-#280 各行零改动**;新增行 `awk -F'|' NF=8` 四条全 PASS。

## 11. 全量回归(L52)
- `pytest -q scripts/tests/`(nohup 落 `/tmp/pytest-277-full2.log`)⇒ **1174 passed, 2 skipped in 142.56s (0:02:22)**,零失败零错误。
- §8 纪律自证末条订正:pending 索引 `#277` 已由本节同步为「已修复(待合并)」。
