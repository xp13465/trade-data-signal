> 归档自 /tmp/repo-b1-fix-report-20261127.md,2026-11-27;原始路径为临时文件,本副本为持久归档

# #384 批1 审查后小修 实施报告(2026-11-27)

> 分支:`feat/repo-unify-b1-20261127`(延续,未新开);base `7c8a3d52c`。只改 F1/F2/F6/F7,F3/F4/F5 未动。

## 1. 逐条修前/修后

| # | 文件 | 修前 | 修后 |
|---|---|---|---|
| F2 | `scripts/tests/test_384_data_root_contract.py:29-40` | `_mk_dual_tree` 数据根目录名 `trade-data` ⇒ 候选 A(symlink 派生)与候选 B(兄弟 `trade-data`)同解,关 A 变异不红(判别力缺口) | 数据根改名 `deploy-data-tree`(非 `trade-data`),候选 B 不再命中同路径;docstring 写明判别力原因 |
| F6 | `scripts/tests/test_383_sentiment_single_root.py:7,11` | 模块 docstring 仍写 `(repo or pick_repo())` /「跟随 `pick_repo()` 的部署数据树」 | 订正为 `(repo or data_root())` /「跟随 `data_root()` 的数据根」,标注 #384 批1 起默认根变更 |
| F7 | `docs/pending-features-index.md:557`(#384 行) | 状态列「待办(2026-11-26 登记,远期;待用户拍板)」 | 「实施中(2026-11-27):批 1 已实施、独立审查 PASS,待合并(分支+commit);批 2-5 排期中(归一化/MAIN_REPO 读者/写侧字面量清理/收尾)」;只改状态列 |
| F1 | `/tmp/repo-b1-impl-report-20261127.md` §2 表 B 行 + §4 第 3 条 | 「mac 上取值完全相同 / mac 上取值不变」,掩盖 worktree 形态行为差异 | 改为「标准 mac 检出取值不变(D),但 worktree 形态下 MAIN_REPO 派生落工作树根(worktree 的 code.parent 无兄弟 trade-data → 回退代码根,设计 §4.1-2 已知限制,仅开发侧,生产显式 REPO 不受影响)」 |

## 2. F2 变异验证(判别力关,必证)

- 隔离副本 `/tmp/mut_a`(copy `scripts/pick_repo.py` + 用例,未碰 repo/生产):
  - 变异 `if (invoked / "scripts").is_symlink() and ...:` → `if False:`(关候选 A)。
  - 结果:**`1 failed, 9 passed`**,失败用例 = `test_derive_candidate_a_symlink`
    (`.../code/trade-data-signal != .../code/deploy-data-tree`,B 分支无法兜住)。
  - 同一用例未变异版本(worktree 内):**14 passed**。
- 结论:改坏候选 A 必红,判别力缺口已闭合。副本已删。

## 3. 自测结果

- 定向:`pytest -q scripts/tests/test_384_data_root_contract.py scripts/tests/test_383_sentiment_single_root.py` → `14 passed in 4.82s`。
- 机检:`check_task_state.py --deploy-mode --skip-zombie-crons` → `2 ok / 0 warn / 0 fail`(F7 状态列通过)。
- 语法:`py_compile` 三个 py 文件 → `COMPILE_OK`。
- 全量(`pytest -q scripts/tests/`,末行原样):
  **5601 passed, 6 skipped, 1 warning, 176 subtests passed in 757.60s (0:12:37)**
- L48:本批不新增触达外发路径的用例;两个测试文件内既有守卫用例保持 monkeypatch 打桩,跑测全程零外发。

## 4. 同类错误面 / 举一反三(§23.2/§23.3)

- 陈旧契约措辞:`grep 'repo or pick_repo()'` / `grep '跟随 pick_repo()'` 全仓 → 0 残留。
- 同模式测试面:`grep -l '_derive_data_root|data_root()' scripts/tests/` → 仅 test_383/test_384 两文件,均已覆盖。
- F2 同类判别力:候选 A/B 同解只存在于 `_mk_dual_tree` 布局;命名已改,其余用例不依赖 D 名为 `trade-data`(定向 14 用例全绿佐证)。

## 5. 边界维度清单(tester §5.3.1 七轴,供 reviewer §10.8 对账)

| 轴 | 维度 | 测/不测 | 理由/来源 |
|---|---|---|---|
| 输入域 | 数据根目录名 = / ≠ `trade-data` | 测 | F2 本体;≠ 名走候选 A,= 名走候选 B 各有独立用例 |
| 状态组合 | 双树 + symlink(候选A) / 双树无 symlink(候选B) / 单仓回退 | 测 | 14 用例全跑绿(派生三形态 + #208 祖先 symlink 回归) |
| 时序 | 无(纯文件系统布局,无时间逻辑) | 不测 | 改动不引入日期/时钟逻辑 |
| 上下游依赖 | `sentiment_db()` 默认根、`MAIN_REPO` 默认值 | 测 | 既有用例 `test_sentiment_db_follows_data_root` / `test_main_repo_default_not_mac_literal` 全绿 |
| 极端值 | 路径含空格/同名根 | 不测 | 本批仅改测试目录名与文档,不新增路径解析;继承批1 边界声明 |
| 回退路径 | 无 A 无 B → 代码根 | 测(变异负控) | 关 A 变异后确证回退到代码根(变异输出证明) |
| 并发与重入 | 多读者并发调用 | 不测 | 本批零生产代码改动(仅测试/文档),无并发面变化 |
| 守卫负向 | 守卫告警路径 | 测(打桩) | 既有 3 用例保持 `_stub_alert`,零外发 |

## 6. 交付与 git

- 提交文件:`docs/pending-features-index.md`、`scripts/tests/test_384_data_root_contract.py`、`scripts/tests/test_383_sentiment_single_root.py`;F1 只改 /tmp 报告(非仓库文件,不入 commit)。
- 仅 push feat 分支,未 push main;未 add 根 `data/`;全程无冲突/覆盖/倒退事件(§23.11)。

- commit:`2ab2e880b`(已 push 原 feat 分支)。
