> 落档:2026-10-22(原样归档)
> 关联:`docs/ops/batch-fix-20261022.md`、`docs/ops/version-consistency-rca-20261022.md`

# §24⑤ 版本一致性校验 TOCTOU 加固 · 独立审查报告

- 审查对象: feat/fix-version-check-toctou-20261022, head 8113a7226(修复 70939bf98 + 测试 8113a7226)
- 基线: origin/main 54a4fcf30(base 是祖先, 仅 3 文件改动: check_version_consistency.py / build_min.py / 新增 test_277)
- 审查环境: macOS, venv Python 3.11.0 + pytest 9.1.1, worktree 隔离, 只读, 零外发, 未执行任何生产脚本
- 结论: **PASS(无阻断项)**; 非阻断差集 4 项见 §4

## 1. B1 五条逐条核(代码锚点 + 真跑)

| # | 要求 | 结论 | 证据 |
|---|---|---|---|
| 1 | 整个窗口只固定一次 HEAD 读源 | PASS | check_version_consistency.py:281 取 head0; :282 单次比对; build_min.py `_read_source` 用 `git show {head}:{path}`(ref=head or "HEAD")。真跑警告文案实际出现「不在 git abae4cb38318」, 证明读的是固定 sha 而非 HEAD |
| 2 | 重建前快照 8 min, 重建后比快照 | PASS | :244 `_snapshot_min_md5` 在 :245 `_rebuild_from_head` 之前执行(逐行确认顺序) |
| 3 | HEAD 变只重试 1 次, 且新 sha+新快照+重建 | PASS | :286-290 条件重试一次; `head=head1`; `_check3_once` 内部重新快照+重建; 无循环 |
| 4 | 仍变 ⇒ FAIL 且消息含「校验期间 HEAD 变化」不含误导原因 | PASS | :292-296 返回 False + 专用文案; 文案不含「min 过期」「工作区源脏」(测试 case3 断言) |
| 5 | 干净工作区 + min 正确 ⇒ PASS, 旧行为不回归 | PASS | 真跑临时 git 仓库 rc=0, `head=abae4cb38318 min_snapshot=[...]`; 正常 FAIL 文案仍是「工作区源脏或 min 过期」 |

## 2. 语义/边界风险核查(必审点 ②)

- **脏工作区 × 并发 pull 能否误 PASS**: 不能。重建固定用 sha 读 git 源, 工作区脏内容不参与; 若 min 由脏源生成 ⇒ 与 HEAD 重建不一致 ⇒ FAIL; 若 HEAD 移动后新 HEAD 内容恰好等于脏源与 min ⇒ PASS 且内容真实一致, 属正确裁决。实测: 仅脏源 PASS; 脏源+脏 min FAIL(工作区源脏)。
- **head=None 分支**: 非 git / 非仓库目录 → `_git_head_sha` 返回 None, 不崩, 输出 `head=n/a`, 与旧版行为一致(实测 rc=0)。
- **worktree `.git` 文件形态**: `_git_repo_of` 返回 None(既有局限), 表现为 0 对跳过 PASS; 用旧版(base 文件)同输入实测同样 0 对 PASS ⇒ 本次未放大。
- **退出码/组合/跳过路径**: `--checks 1,2` rc=0; `--checks 9` rc=1; 缺 min rc=1; 旧 min rc=1; 源缺失仍按旧语义 skip 不 FAIL。deploy.sh:532 经 `${PIPESTATUS[0]}` 取 rc, CI ci.yml:118/131 取 rc, 均未被新输出影响。
- **build_min 默认行为逐字不变**: 只有 build_min.main() 无参调用走写入路径; 默认 `head=None` ⇒ `git show HEAD:` 与旧警告文案逐字一致(L114/L159/L166 的 npx 调用点未动)。
- **新输出行是否被解析器误读**: 全仓 grep 只有 deploy.sh 用退出码、CI 用退出码; 无脚本解析 `head=`/`min_snapshot=`/新消息文本 ⇒ 无误读面。
- **新增测试时敏性**: test_277 无日期字面量、无 today()/now(), 每个用例自建临时仓库, 不会随 main 前进失效; 未加入 time-shift allowlist(本来就不需要)。

## 3. 自跑全量 pytest + 变异

- 全量: `nohup .venv/bin/python -m pytest -q scripts/tests/` → **1172 passed, 2 skipped, 145.09s, RC=0**(/tmp/review-toctou-pytest.log + .rc); 新用例 7/7 全过。
- 变异(均先备份原文件, 跑完还原; 还原后 md5 678be8ab1c1cbca7836897f0c460bf57 == HEAD blob, `git status --porcelain` 空):
  - M1 重试仍用旧 sha (`head = head0`) → 2 failed / 5 passed(红, 护栏有效)
  - M2 快照挪到重建之后 → **7 passed(绿, 缺口: B1 第 2 条无测试钉住)**
  - M3 删除 head2 复验 → 1 failed / 6 passed(红, 护栏有效)
  - M4 `_rebuild_from_head` 忽略固定 sha (head=None) → **7 passed(绿, 缺口: B1 第 1 条机制无测试钉住)**

## 4. §10.8 边界独立复核(差集, 我方多出项)

实施方清单已覆盖: 正常 PASS/单次竞态/持续竞态/脏工作区/旧 min/缺 min/空站/非 git/权限。**我方独立推演后多出的项**:

1. **head1/head2 取不到(None)分支**: 条件 `head0 and head1 and ...` 下 rev-parse 瞬时失败会被当成"窗口稳定"直接采信。概率极低、方向是极小概率误导性裁决; 建议后续加显式告警(非阻断)。
2. **unborn HEAD / 非仓库目录**: 实测不崩、n/a PASS, 与旧版逐位一致; 但 non-git 时 build_min fallback 路径 `site_dir/static-site/...` 与真实源路径错位 ⇒ 检查空转(0 对)是**既有行为**, 非本次引入。建议另立单登记。
3. **快照顺序/固定 sha 无测试护栏**: 即 M2/M4 两条变异全绿。生产逻辑已由真跑+代码锚点独立核实, 不阻断; 建议补 2 条最小单测。
4. **残余微窗口**: 重试成功后到输出 PASS 之间若再发生 pull, 理论仍可能误判; 本次已消除 RCA 主窗口, 彻底根治需 RCA 的 B2。属残余风险声明, 非阻断。

另核: faketime +45d CI 步(新测试无时敏面, 本地 mac 无法跑 faketime, 该步 CI 仍 continue-on-error); GIT_REPO 指向另一仓库/符号链接(解析逻辑未改, 与旧版同, 不测+理由)。

## 5. check_version_progress.py:341-343 同族评估

- 现状: `head`/`parent` 在 main() 开头一次读取, 之后 check_a/check_b 全程用 parent 的 `git show`, 版本串/worktree 内容在窗口内被并发 pull 改写 ⇒ 同族 TOCTOU 理论存在。
- 实测窗口: **2.42s**(~320 次 git show), 不是实施报告说的"毫秒级"; 误判方向是 stale PASS(可能漏报倒退), 不是误阻断。
- 处置: 不在本分支修(超范围, 改动面大且语义不同); 建议另立任务, 可缓存 version_key、或同样固定 sha + 复验。不影响本次 PASS。

## 6. 冻结契约 / 防白屏强度

- §24⑤ 校验强度未降: 正常路径逐字不变; 重试窗口内内容必须与**同一新 HEAD** 重建一致才 PASS(比旧版更严格: 旧版窗口错位必 FAIL); 持续抖动明确 FAIL 且不误伤。
- 无前端/数据/算法改动, 不触 §21/§22/§24④; 无删除、无外发、无生产写入。
- B3(钉 terser 版本)按实施方报告未做: 认可(约 4 行, 但会新增 npx 缓存键/网络失败面, 且失败会走 skip 削弱校验; 属 RCA 后续项)。

## 7. 非阻断建议(交主控决定是否 merge 后补)

1. 补 2 条单测钉住「快照在重建前」「重建用固定 sha」(对应 M2/M4)。
2. head1/head2=None 时输出一条显式告警(不可信窗口)。
3. check_version_progress 同族另立任务。
4. B3 terser 钉版本继续挂在 RCA 待办。

## 8. 证据与探针自证(§10.0)

- 探针 = 新增 7 用例(经 M1/M3 变异证明有判别力) + 临时真实 git 仓库真跑(独立于实施方环境) + 旧版(base 文件)同输入对照(证明 worktree/非 git 行为未变化)。
- 未执行生产脚本、未 curl 线上、未发通知; 全程 worktree 内只读, 变异仅改 worktree 临时副本且已还原。
- 真跑分支: clean PASS(rc=0 head=sha) / 脏源 PASS / 脏源+脏 min FAIL / 旧 min FAIL / 缺 min FAIL / 非 git PASS head=n/a / `--checks 1,2` PASS / `--checks 9` rc=1。
