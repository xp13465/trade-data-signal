# B2 补笔增量复审（O-1/O-2 同类面补齐）— 独立复审报告

- 复审对象：`feat/next-steps-b2-lowrisk` 增量 `7785ce00f..208ecfe78`（tip = `208ecfe78`，3 文件）
- 复审方式：本机 worktree 隔离（fresh context，独立复现，不采信报告）；解释器 = `.venv` python3.11 + pytest 9.1.1
- **总判定：PASS**（1 条 must-fix = 报告「对拍行」md5 自相矛盾，纯文书订正、不阻断 merge；建议随本批订正后合并）

## 0. 锚点核对（diff 逐行核）

- 分支 = `feat/next-steps-b2-lowrisk`，tip = `208ecfe78`「fix(B2-补笔): 隔离同类面补齐 O-1/O-2 + 报告勘误」✓
- `git diff 7785ce00f..208ecfe78` = 3 文件，与派单/报告描述一致：
  - `scripts/tests/_wrap_util.py`（+18/−4：登记 2 条 + `_WATCH_MODULES` + 注释）
  - `scripts/tests/test_agent_inbox_watcher_pytest.py`（+7/−1：`isolate_repo=True` + 注释）
  - `docs/ops/next-steps-b2-report-20261011.md`（+38：勘误 + 补笔段）
- 除本报告外，工作区无其他未提交改动（`git status --porcelain` 空）

## 1. 登记正确性（核心，逐项独立取证）

### 1.1 「常量在目标模块 import 期派生」事实核（读源头，非报告）

- `scripts/agent_inbox_watcher.py:23 REPO = Path("/Users/linhuichen/code/trade")`（硬编码主仓）；
  `:29 LOG_DIR = REPO / "data" / "logs"`；`:30 LOG_FILE = LOG_DIR / "agent_inbox_watcher.log"` → **import 期派生属实**。
  写盘点还有 `:424 log_path = LOG_DIR / f"inbox-{kind}-{request_id}.log"`（同被重绑覆盖）。
  `log()`（:47-56）= `LOG_DIR.mkdir(parents=True, exist_ok=True)` → `open(LOG_FILE,"a")`，**try/except 兜底**（CI 不炸，但会静默不写）。
- `scripts/feishu_ws_listener.py:63 LOG_PATH = Path("/Users/linhuichen/code/trade-data/data/logs") / "feishu_listener.log"`
  → 硬编码 **trade-data 镜像树**属实；`log()`（:81-91）= `LOG_PATH.parent.mkdir` → `open(...,"a")`，try/except。
- **重绑时序能否覆盖**：`_wrap_util.run_unittest_module` 流程 = `_snapshot_modules()`（L175）→ `_isolate_repo_env()`（L176）→
  `importlib.import_module`（L180）→ `_redirect_repo_paths(iso_dir)`（L182，**import 之后**）→ 跑 suite → finally `_restore_modules`。
  legacy 套件在**模块级** `import agent_inbox_watcher as w`（`scripts/test_agent_inbox_watcher.py:24`）⇒ import 完成时模块已在 `sys.modules`，
  重绑必然命中（非静默跳过）——由 §3 探针实测坐实（spy 在真跑流程内打印重绑后常量）。

### 1.2 `_WATCH_MODULES` 加 `agent_inbox_watcher` 的必要性（负控证明，非推理）

- **负控**：运行期把 `agent_inbox_watcher` 从 `_WATCH_MODULES` 摘掉后跑包装：15 用例仍全绿，但收尾
  `w.LOG_DIR/LOG_FILE` **残留指向已删临时树**（`[N4-NOWATCH-POST-CONSTS] .../legacy-repo-isolate-unmh9x8b/data/logs`，且 `[N4-ISO-DIR-EXISTS] False`）
  ⇒ 该登记**必要**（与 feishu_ws_listener 先例同律：「重绑过的模块必须随包装收尾还原」）。
- **正控**（补笔后真跑）：收尾 `w.LOG_DIR/LOG_FILE` 逐个还原主仓路径、`w.log.__name__ == 'log'`（原函数引用还原）✓。
- 不变量机检：`set(_REPO_PATH_ATTRS) ⊆ set(_WATCH_MODULES)` = **True**（重绑名单 ⊆ 还原名单，新增登记未破坏不变量）。

### 1.3 第三处同类面穷举（11 个 module 包装 vs 应登记项）

11 个包装逐一定位「被测模块」与写盘容器：

| # | 包装 | 被测模块 | 隔离 | 同名型面? |
|---|---|---|---|---|
| 1 | test_132_notify_tier_dedup | notify | 否 | 否（登记已在；全用例 dry_run/tempdir+patch）|
| 2 | test_188_s06_sync_blindspot | upload_r2 | 否 | 否（`REPO=td` 置于 `import upload_r2` 前 :99→:108，STATIC_DIR 绑临时树）|
| 3 | test_204_etfscore_loud | upload_r2 | 否 | 否（自 patch `ur.STATIC_DIR/ROOT`→临时树 + `_upload_glob`/`_backup_overwritten_keys`/`purge_cache` 打桩）|
| 4 | test_agent_inbox_watcher | agent_inbox_watcher | **是（本补笔）** | 已补 ✓ |
| 5 | test_ai_macro_hit_filters | app.queries | 否 | 否（纯只读：grep 无 `write_text`/`open(w|a)`/`to_sql`/`commit`）|
| 6 | test_feishu_post | notify + check_signals | 是 | 否（check_signals 写盘点不被触达：只调 `build_feishu_post/build_email` 纯构建器）|
| 7 | test_feishu_ws_listener | feishu_ws_listener | 是 | 已补 LOG_PATH ✓ |
| 8/9/10/11 | notify_flush_race / notify_feishu_retry / notify_dedup / notify_reply | notify | 3 是 1 否 | 否（未隔离的 retry 全用例 tempfile + patch `DEDUP_FILE`/`_append_jsonl`/`send`）|

- **附机检**：16 个登记属性逐一核「存在且为 Path」→ `[ATTR-BAD] []`（无「登记了但 `getattr` 拿不到 ⇒ 静默 no-op」项）。
- **附全仓跑后扫描**（主仓排除 .git/.venv/worktrees，`find -newer marker`）：仅 `TASKS.md`（11:00:07 = 主控记账写入，含本审在跑状态，非测试行）
  与 `.claude/scheduled_tasks.json`（harness cron 状态文件）——均非测试产物；主仓 `TASKS.md` 内「飞书 20xx」测试注入行计数 = **0**（feishu 套件全部自 patch `TASKS_PATH` 到 tempdir）。
- 结论：**无第三处遗漏**（穷举 11 包装 + 2 未隔离被测模块静态核 + 全仓跑后扫描三重口径一致）。

## 2. 双树零污染独立对拍（跑前跑后，含全量）

基线（10:51 打 marker）：主仓 `data/logs/agent_inbox_watcher.log` = **85464 行 / md5 `076bd4e1a4d56f0c22980721f6f3ea5e`**；
trade-data `data/logs/feishu_listener.log` = **md5 `8e1177df211f71c9fe2469b7b10f045c`**；`refs/codex/*` = 3 条。

| 跑法 | 结果 | 主仓 log | feishu 镜像 | find -newer | refs |
|---|---|---|---|---|---|
| 定向 2 包装（agent_inbox_watcher + feishu_ws_listener） | **2 passed in 4.13s**（报告 4.14s）| md5 零变化 | md5 零变化 | 双树空 | 3→3 |
| **全量** `pytest -q scripts/tests/` | **746 passed / 2 skipped / 3 failed in 81.82s**（报告 746/2/3、82.07s 逐字命中）| md5 零变化 | md5 零变化 | 主仓 data 全量 + trade-data/data 全量 + 主仓全仓（排除项外）**空** | 3→3 |
| 9 包装回归（2 目标 + notify 家族 6 + test_229_230） | **22 passed in 6.43s**（报告 22）| — | — | — | — |
| 正向探针 + 负控 | 见 §3（跑后主仓双 log md5 亦零变化）| md5 零变化 | md5 零变化 | 空 | — |

- 零外发：每个包装内建 `assert trap.hits == []`（`ZeroOutboundTrap`，网/邮件三出口）——上述各跑全绿 ⇒ **hits=[] 机检成立**，无真实发通知/飞书。

## 3. 正向证明（排除「log 从未被调用」假绿，§18 L49 同精神）

探针（static-only：只经 `_wrap_util` 官方包装路径跑 legacy 单测，不直接 exec 业务脚本）在**真跑流程内** spy `_redirect_repo_paths`：

- **重绑瞬间**（spy 在真流程 import 之后、suite 之前执行）：
  `w.LOG_DIR → <iso>/data/logs`、`w.LOG_FILE → <iso>/data/agent_inbox_watcher.log`、`fwl.LOG_PATH → <iso>/data/feishu_listener.log`（主仓/trade-data 路径 → 临时树）✓
- **物理落点**：探针行落临时树（`[SPY-ISO-PROBE-CONTENT]` = `2026-10-11T10:57:18 REVIEW-PROBE-agent_inbox_watcher`）✓
- **log() 真被调用且真重定向**（逐调用核落点）：agent_inbox_watcher 套件 **15 次 log 调用，15/15 落临时树**；
  feishu 套件 **54 次，54/54 落临时树**（含 `cleanup_ref removed git ref refs/codex/req/...`、`recovered malformed lock`、`sync_git_refs created ...` 等合成行，与主仓 log 10:25:40 段旧病灶行逐字同类）
- **收尾还原**：跑后常量回主仓路径、log 引用回原函数、临时树已 `rmtree` ✓；负控见 §1.2

## 4. 报告勘误段与实物一致性 + 清理可逆性（§25）

- **清理正确性（比「抽查」更强：逐位前缀等价）**：`head -85464 /tmp/b2fix-backup-*.log | md5` = `076bd4e1a4d56f0c22980721f6f3ea5e` = 现文件 md5
  ⇒ 现文件 = 备份前 85464 行的**逐字节等价**，删除动作 = 纯尾截断 14 行；**10:25:40 之前既有行（含 10:16:11 段）零改动**成立。
- **尾 14 行内容核**：含 `rev-test-003`×2（`skip` + `cleanup_ref`）、`t-verdict-003`×1、临时路径 `tmpc86xal8k`、`t-clean-001` 等 ✓ 与报告描述一致。
- **备份核**：`/tmp/b2fix-backup-agent_inbox_watcher.log` = **85478 行 / md5 `653eb82b3bd76dc9687081adee38f51d`** ✓ 存在、与报告「删前原态」相符（可逆性成立，恢复路径 = 从该备份整文件取回）。
- **must-fix（文书，1 条）**：报告补笔段「双树零污染对拍」行写作「主仓 log **85464 行 / md5 `653eb82b…` 零变化**」——**自相矛盾**
  （`653eb82b…` 按同报告「数据清理」段 = **删前 85478 行**原态的 md5；85464 行文件的实测 md5 = `076bd4e1a4d56f0c22980721f6f3ea5e`）。
  订正建议：该行改为「主仓 log **85464 行 / md5 `076bd4e1…`** 零变化（注：`653eb82b…` 为删前 85478 行原态，见「数据清理」段）」。
  影响面：仅证据表文字，零功能影响、不阻断 merge；但该行正是「零污染」的核心举证，值自相矛盾会被后续反查者判为假证据，**建议合并前订正**。

## 5. 3 failed 归属（非本改动引入，勿动勿修）

- `test_188_s06_sync_blindspot`×1：`scripts/upload_r2.py:3730 UnboundLocalError('standalone_files')`（台账缺失/损坏⇒退回旧行为分支未赋值）。
  diff 未触 `upload_r2.py`；且 B6 修复 commit `6b1335e3b` **非**本分支祖先（`git merge-base --is-ancestor` = 否，实测）⇒ pre-existing。
- `test_245`×2：时钟敏感（23:25 前 no-op / 隔日 stale 必发）；B7 `4243b9196` 同样非本分支祖先 ⇒ pre-existing。与 diff 全无关（双方均未被 diff 文件导入）。

## 6. 假绿猎捕结论（本次复审核心价值项）

1. **重绑后是否还原**：是（正控 §1.2；负控证明不登记就残留）——`_WATCH_MODULES` 语义用对。
2. **登记是否「看起来对但不生效」**：否——16 属性全存在且为 Path（§1.3 机检）；重绑在真流程内被 spy 实证命中（§3）。
3. **「log 从未被调用」假绿**：已排除（15/15、54/54 逐调用落点核）。
4. **静默失败面**：`log()` 的 try/except 会把「路径不可写」吞掉（仅 stderr 打印），若未来隔离机制再退化，主仓污染是「静默写成功」而非报错——
   本补笔已封住已知两个入口；建议后续任何新增 legacy 包装套件，按本批模式先问「被测模块有无 import 期派生写盘常量」。

## 三、判定

- **PASS**：登记正确性（源头事实 + 时序覆盖 + 收尾还原 + 负控必要性 + 11 包装穷举无第三处遗漏）、双树零污染（定向 + 全量 + 全仓范围）、正向证明、清理可逆性 **全部独立复现成立**。
- **must-fix：1 条（文书级）** —— §4 对拍行 md5 自相矛盾订正；不阻断 merge（代码零缺陷）。
- merge 资格：本增量 PASS（内审）；B2 本体另见 `docs/ops/next-steps-b2-review-20261011.md`。

### 已滤低分项（<80，仅记录）
- `_redirect_repo_paths` 对「登记了但不在 `sys.modules`」的模块**静默跳过**（无告警）：若未来某 legacy 套件改成函数内延迟 import 被测模块，隔离会静默失效（本批 agent_inbox_watcher 为模块级 import，实证命中，不受影响）。机制加固建议留档（如加一条「登记模块未在册」stderr 提示）。
