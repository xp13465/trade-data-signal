> 归档自 /tmp/repo-b1-impl-report-20261127.md,2026-11-27;原始路径为临时文件,本副本为持久归档

# #384 批1 实施报告(python 数据根单源 + #383 遗留两项,2026-11-27)

- 分支:`feat/repo-unify-b1-20261127`(base = `origin/main@192691ab3`)
- 设计权威:`/tmp/repo-unify-design-20261127.md` §1.3/§1.4/§2.1/§5;任务书:`/tmp/task-repo-unify-batch1-20261127.md`
- 性质:纯代码,无数据迁移、无状态写、无生产库写

## 1. 改动面(3 个文件)

| 文件 | 改动 |
|---|---|
| `scripts/pick_repo.py` | 新增 `CODE_ROOT`(:37)/`INVOKED_ROOT`(:38)/`_derive_data_root()`(:43,§1.3 算法,A 候选要求 `<invoked>/scripts` 是 symlink)/`code_root()`(:61,原 `pick_git_repo` body 抽名)/`data_root()`(:127,env REPO → `guard_deploy_source_tree` 读侧守卫 → 否则布局派生);`pick_git_repo()`(:95)改为委托 `code_root()`;`GIT_REPO_DEFAULT = CODE_ROOT`(旧名兼容,`candidate_repos` 不动);`MAIN_REPO`(:76)默认改「env 或布局派生数据根」;`sentiment_db()`(:147)默认根 `pick_repo()` → `data_root()`(显式 repo 兼容保留);模块 docstring 同步 |
| `scripts/tests/test_384_data_root_contract.py`(新建) | 10 个用例(下表),零网络全 tmp_path |
| `scripts/tests/test_383_sentiment_single_root.py` | 用例 2 契约同步:`sentiment_db()` 默认根已从 `pick_repo()` 变 `data_root()`,原用例打桩 `pick_repo.pick_repo` 失效 → 改打桩 `data_root`,断言不变;改名 `test_no_env_falls_back_to_data_root` |

**冻结面核对(设计 §3)**:`candidate_repos()` 列表构成/`pick_repo()` 选中算法/`guard_deploy_source_tree` 判据/`force_env`/`fetch_news` 写路径/deploy.sh 均**一字未动**(diff 里零行)。

**新建用例清单(10)**:`test_derive_candidate_a_symlink` / `test_derive_candidate_b_sibling` / `test_derive_single_repo` / `test_derive_symlinked_ancestor_not_candidate_a`(#208 回归) / `test_env_repo_data_tree_wins` / `test_env_repo_code_repo_two_tree_raises` / `test_single_repo_repo_equals_code_root_ok` / `test_code_root_prefers_env_git_repo` / `test_sentiment_db_follows_data_root` / `test_main_repo_default_not_mac_literal`。

**零外发(L48)**:3 个触发守卫的用例全部先 `_stub_alert()` 打桩 `_alert_guard_blocked`(记录器,只记录不发送);`test_env_repo_code_repo_two_tree_raises` 还断言 stub 被调用(证明走的是守卫告警路径,不是别的 SystemExit)。本次自测期间无任何真实外发。

## 2. 实现预期对表(设计 §2.1 表 5 场景)

| # | 场景 | 改前 | 改后实测 | 证据 |
|---|---|---|---|---|
| 1 | Linux 形态无 env(D/scripts→C/scripts symlink) | `pick_repo()=C`,`sentiment_db()=C/data`(陈旧) | 数据根派生 = D | smoke A:`/tmp/smoke384a/code/trade-data /tmp/smoke384a/code/trade-data/data/sentiment.db`;B 形态 smoke 同;用例 `test_derive_candidate_a_symlink`/`b_sibling` 绿 |
| 2 | env REPO=C + 独立 D | `sentiment_db()=trade/data/sentiment.db` 静默 | **SystemExit**,文案含「解析到 git 仓」「而非部署源树」 | 用例 `test_env_repo_code_repo_two_tree_raises`(打桩告警)绿;未在 CLI 跑该场景(避免真告警) |
| 3 | env REPO=D(现网) | D | **逐字不变** | `REPO=/Users/linhuichen/code/trade-data GIT_REPO=/Users/linhuichen/code/trade` → `data_root()=/Users/linhuichen/code/trade-data`,`sentiment_db()=/Users/linhuichen/code/trade-data/data/sentiment.db` |
| 4 | 单仓(无 D、无 env) | C | C 不变 | 本 worktree smoke:derived = worktree 根(无兄弟 trade-data → 单仓回退);用例 `test_derive_single_repo` 绿 |
| 5 | `sentiment_db()` 5 处生产读者 | 返回值 | 不变(均显式传 repo,或默认根同为 D) | `aggregate_shadow.py:162`/`ab_direction_anchor.py:263,295`/`replay_direction_anchor.py:91` 显式传 repo(拼该树,语义不变);`gen_daily_brief.pick_db(repo)` 显式传;`brief_ledger.py:111` 走默认根 `data_root()`(现网 env REPO=D → D) |

**#383 遗留两项修前/修后对照**

| 遗留 | 修前 | 修后 |
|---|---|---|
| A(env REPO 指向代码仓的伪单仓) | `sentiment_db()=trade/data/sentiment.db`(MAX 20261028 陈旧),无提示 | `data_root()` 调 `guard_deploy_source_tree` → SystemExit + 告警(stub 用例证明) |
| B(Linux 无 env 时 MAIN_REPO 默认落代码仓) | `MAIN_REPO = Path(env 或 "/Users/linhuichen/code/trade-data")`;Linux 上不存在 → `candidate_repos=[不存在,C]` → `pick_repo()=C` → 陈旧库 | `MAIN_REPO` 默认 = `_derive_data_root(CODE_ROOT, INVOKED_ROOT)`(D/单仓 C);标准 mac 检出取值不变(D),但 **worktree 形态下 MAIN_REPO 派生落工作树根**(worktree 的 code.parent 无兄弟 `trade-data` → 回退代码根,设计 §4.1-2 已知限制,非「完全相同」)|

## 3. 自测结果

**① 新用例 + #383 回归**
```
14 passed in 0.27s
```

**② 全量 `pytest -q scripts/tests/`(L52:改 scripts/ 源码必跑全量,后台化跑)末行原样**
```
5601 passed, 6 skipped, 1 warning, 176 subtests passed in 738.30s (0:12:18)
```
(无 failed;15:33 起跑,后台化+短轮询,非转后台残留)

**③ 本机 smoke(设计证据用例 2,逐字输出)**
```
--- smoke 3: 现网形态 REPO=D GIT_REPO=C ---
/Users/linhuichen/code/trade-data /Users/linhuichen/code/trade-data/data/sentiment.db
--- smoke W: 本 worktree 无 env(无兄弟 trade-data → 单仓回退代码根) ---
/Users/linhuichen/code/trade/.claude/worktrees/agent-aad34397131009dbe /Users/linhuichen/code/trade/.claude/worktrees/agent-aad34397131009dbe/data/sentiment.db
--- smoke A: D/scripts -> C/scripts symlink (云上形态) ---
/tmp/smoke384a/code/trade-data /tmp/smoke384a/code/trade-data/data/sentiment.db
--- smoke B: 兄弟 trade-data 存在 (mac 物理路径形态) ---
/private/tmp/smoke384b/code/trade-data /private/tmp/smoke384b/code/trade-data/data/sentiment.db
```

**④ 现网行为锚点(只读,设计证据用例 3)**
```
[brief_ledger] repo=/home/ubuntu/code/trade-data db=/home/ubuntu/code/trade-data/data/sentiment.db
```
db 仍为 D(=数据根),批 1 不改该链。

**⑤ 全仓 grep(任务书 3④)**:`os.environ.get("REPO", "/Users` 与 `MAIN_REPO, "/Users` 命中 6 个文件(`check_data_gap_alerts.py:137` / `upload_r2.py:193` / `backfill_direct_metrics.py:49` / `fetch_news.py:77` / `gen_daily_brief.py:62` / `fapi_bj_width_export.py:53`),全部属**批 4 范围**(设计 §2.4 明列 4 个 + MAIN_REPO 变体 2 个),批 1 不动;`pick_repo.py` 已从该命中集合移除。`GIT_REPO_DEFAULT` 消费方仅 `candidate_repos()`(本文件),无独立断言面;`ops/monitoring/tests` 无引用 `pick_repo.MAIN_REPO/data_root` 的硬编码断言。

## 4. 行为变化(如实标注)

1. **错配场景从「静默读陈旧库」→「响亮失败」(设计定性,非退化)**:env REPO 指向代码仓且独立部署树存在时,`data_root()` 抛 `SystemExit` 并走 `_alert_guard_blocked` 告警(生产上 unit 会进 failed,由 `check_failed_units.py` 15 分钟内告警)。风险缓解按设计 §4.1:现网已核实核心 unit(REPO=D)不触发;上线观察一个完整交易日(20:40 daily brief + 21:15 ab-anchor)。
2. **`sentiment_db()` 默认根 `pick_repo()` → `data_root()`**:现网两者同为 D(场景 3 实测);差异只在「无 env + 双树」时不再按 overview 日期猜树 —— 这正是 #384 要消除的误判面。
3. **`MAIN_REPO` 模块默认值**:标准 mac 检出取值不变(`/Users/linhuichen/code/trade-data`);**但 worktree 形态下取值变为工作树根**(实测 `env -u REPO -u GIT_REPO -u MAIN_REPO` 打印 `/Users/linhuichen/code/trade/.claude/worktrees/agent-...`:worktree 的 `code.parent` 无兄弟 `trade-data` → 派生回退代码根,设计 §4.1-2 已知限制,仅开发侧、生产 unit 显式 REPO 不受影响);Linux 上从「不存在路径」→ 派生数据根(mac 字面量 → 布局派生,设计 §3 允许的两处之一)。
4. **`GIT_REPO_DEFAULT`/`candidate_repos()`/`pick_repo()` 选中算法/守卫判据零变更**,写/上传链行为不变。

## 5. 边界维度清单(role-tester §5.3.1 七轴,交 reviewer §10.8 独立复核对账)

| 轴 | 维度 | 测/不测 | 依据与理由 |
|---|---|---|---|
| 输入域 | env REPO 取值:未设/空串/数据树/代码根/不存在目录 | 测 | 用例 `env_repo_data_tree_wins`(数据树)、`code_repo_two_tree_raises`(代码根)、空串落派生(`MAIN_REPO` 同款 `or` 处理);不存在目录 → `data_root()` 走派生(与 `pick_repo()` 同语义,已读代码确认) |
| 输入域 | env GIT_REPO 未设/设代码根/设不存在目录 | 部分测 | `code_root_prefers_env_git_repo` 测「设代码根」;未设→CODE_ROOT、不存在→CODE_ROOT 为 `pick_git_repo` 原有语义,代码路径直读确认(未单测) |
| 状态组合 | REPO==GIT_REPO 且 MAIN_REPO==git(真单仓) | 测 | `test_single_repo_repo_equals_code_root_ok` |
| 状态组合 | REPO==GIT_REPO 但 MAIN_REPO≠git 且存在(双树错配) | 测 | `test_env_repo_code_repo_two_tree_raises` |
| 时序 | 模块常量 `MAIN_REPO` import 时求值 vs 运行时改 env | 测 | `test_main_repo_default_not_mac_literal` 子进程纯净 env 复算;刻意说明模块常量不随 runtime env 变(与原设计一致) |
| 上下游依赖 | 5 处生产读者 + `gen_daily_brief.pick_db` 3 调用点 | 测(静态+用例) | 逐处 grep 显式传 repo;`test_sentiment_db_follows_data_root` 覆盖默认/显式两路 |
| 上下游依赖 | `app/db.py` 仍自解 `_HERE`(批 2 范围) | 不测 | 批 1 不改 `app/db.py`;设计 §2.2 单列批 2,跨实现一致性用例在批 2 |
| 极端值 | 祖先目录是 symlink、scripts 本身是实体目录 | 测 | `test_derive_symlinked_ancestor_not_candidate_a`(#208 回归) |
| 极端值 | 数据根/代码根同名/路径含空格 | 不测 | 算法纯 Path 拼接,无字符串解析;bash 侧同类已在 `repo_paths.sh` 单测覆盖,批 1 不引入新解析 |
| 回退路径 | 无 env、无 symlink、无兄弟 trade-data(单仓/CI) | 测 | `test_derive_single_repo` + worktree smoke;CI(无 trade-data)落 C 与改前一致 |
| 回退路径 | 自定义布局(部署树不叫 trade-data 且不走 symlink) → 退回代码根 | 不测 | 设计 §4.1-2 已知限制,env REPO 仍最高优先;批 3/5 检查器负责暴露,批 1 不扩算法 |
| 并发与重入 | `data_root()` 被多读者并发调用 | 不测(推理) | 纯函数 + 只读 env/文件系统判定,无状态、无写、无锁需求;`guard_deploy_source_tree` 只读 |
| 守卫负向 | 守卫告警路径 | 测(打桩) | L48:3 个相关用例全部 stub,断言 stub 被调用/不被调用,零真实外发 |

## 6. 写码前 7 级阶梯与复用(§6.5)

- 第 2 层(库里已有)成立:未新造解析算法 —— 派生算法直接照搬 `repo_paths.sh:43-76`(bash 权威);读侧守卫直接复用现成 `guard_deploy_source_tree`,未新增判据。
- 第 3/4 层:`pathlib` + `os.environ`,无新依赖。
- 无新增抽象层:只加 3 个公开函数(设计点名)+ 1 个私有纯函数,无配置项/无扩展位。

## 7. 交付物

- 代码:`scripts/pick_repo.py`、`scripts/tests/test_384_data_root_contract.py`(新)、`scripts/tests/test_383_sentiment_single_root.py`(契约同步)
- 仅推 feat 分支,**未 push main**;未 add 根 `data/` 下任何文件;无 git 冲突/覆盖/倒退事件(§23.11)
