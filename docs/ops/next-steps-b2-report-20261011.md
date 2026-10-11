# B2 低危欠账清理批 — 实施报告（2026-10-11）

**分支**：`feat/next-steps-b2-lowrisk`（基线 `68245b767`，已 rebase 到 `origin/main`）
**依据**：`docs/ops/next-steps-plan-20261011.md` §1 B2（用户已拍板 D1 放行）
**纪律**：只 commit+push feat 分支（禁 push main）；**未自行 bump 任何版本串**（机制 C）；未 add 根目录 `data/`；本批未真跑任何生产 flush/notify 链。

---

## 0. 结论摘要

- 段 A 冻结面 3 项（#229 / #230 / #245⑩+#247-R1 文案）+ 段 B 5 项 + 子项 9 全部落地。
- **#230 举一反三**：发现并一并修掉**逐字同型**的 `flush_digest`（CLI `--flush-digest --dry-run` 同样留 0 字节 lock）—— 属 §23.3 主动扩面，已单独标注。
- `static-site/style.css` 为**纯注释**改动，min 产物**逐字节不变** ⇒ **无需 bump/deploy**（证据见 §4）。
- 全量 `pytest -q scripts/tests/`：**746 passed / 2 skipped / 3 failed**；3 条 failed 经**基线复现 + CI 交叉核对**判定为**既有（非本批引入）**，其中 2 条是**生产时点相关**的真问题，另 1 类已在别线修复中（见 §6）。
- 本批**全程无 git 冲突/覆盖/版本倒退事件**（§23.11）。

---

## 1. 逐子项结果

| # | 子项 | 结果 | 落点 |
|---|---|---|---|
| 1 | #229 `--tier info --dry-run` 仍写 `info_log.jsonl` | **done** | `notify.py` `log_info` 最前短路 + `send_tiered` info 分支透传 `dry_run` |
| 2 | #230 `--flush-warnings --dry-run` 建 0 字节 flushlock | **done** | `notify.py` `flush_warning_batch` 于 `mkdir/open` **之前**短路 |
| 2b | **（举一反三）**`--flush-digest --dry-run` 同型建 0 字节 digest lock | **done** | `notify.py` `flush_digest` 同法短路 |
| 3 | #245⑩ / #247-R1 sh 兜底句「未生成」文案失真 | **done** | `nextday_plan.sh` 告警 body 重写（两类原因 + 影响/注意同步） |
| 4 | #226 conftest tempdir 清理 | **done** | `scripts/tests/conftest.py` `atexit.register(shutil.rmtree, _ENV_SHIM_DIR, ignore_errors=True)` |
| 5 | #236 `update_all.sh` 注释旧数 `211s` | **done** | 3 处 → `222s`（权威值见 `docs/ops/236-f2-alert-upload-decouple-20261009.md` §「10-08 实测排队 222s」） |
| 6 | #240 残余文书（P-1/P-4/P-5） | **done** | `check_failed_units.py`（易漂行号→**文案锚** + 维护契约）；`docs/ops/alert-denoise-batch2-20261009.md`（同类面表 10→**16** + 行号→`--dedup-key` 锚）。P-2 为观察项、P-3=已闭环 #241（不属本批） |
| 7 | #245-卫生 / #247-R2 worktree 残留 + legacy 套件 REPO 隔离 | **done** | `scripts/tests/_wrap_util.py` 新增 `isolate_repo` + `_redirect_repo_paths`；5 个 legacy 包装启用（4 notify 家族 + feishu_ws_listener） |
| 8 | #115-遗留② `style.css` 注释订正（`#74` 为**错编号**） | **done** | 2 处注释去 `#74`；**min 不变**（§4） |
| 9 | 残留分支/worktree 清理（独立 commit） | **done** | §5 |

---

## 2. §23.2 同类错误面清单（先列清单，再逐项给结论）

### 2.1「`--dry-run` 仍落盘」同类面（#229 / #230 族）

穷举方式：`grep -nE "def [a-z_]+\(|\.mkdir\(|open\([^)]*[\"'](a|w|a\+)" scripts/notify.py` 取全部落盘点，逐个核对「dry_run 是否在**写入函数内**被守」。

| 落盘点 | 现状 | 结论 |
|---|---|---|
| `_record_ledger`（台账 jsonl） | `if dry_run or ALERT_LEDGER_DISABLE` 短路 | 已守（前批） |
| `write_alert`（latest.md） | `if dry_run: return` | 已守（#184） |
| `_mirror_severe`（latest.md 追加） | 调用侧 `if severe and not dry_run` | 已守 |
| `defer_warning`（warning buffer + dedup state） | `if dry_run: return "dry_run"` | 已守 |
| `_flush_warning_batch_locked` | `sent and not dry_run` 才清理 | 已守 |
| `_flush_digest_locked` | `if dry_run:` 提前 return（不清理/不写 state） | 已守 |
| **`log_info`（info_log.jsonl）** | 原**无**门控 | **本批修（#229）** |
| **`flush_warning_batch`（flushlock 建文件）** | 原**无条件** `mkdir+open` | **本批修（#230）** |
| **`flush_digest`（digest lock 建文件）** | 原**无条件** `mkdir+open`（与上行逐字同型） | **本批修（#230 举一反三）** |
| `update_dedup`（DEDUP_FILE） | 函数内无 dry_run 形参 | **不改**：`dry_run` 概念在本层不存在；**全部**调用点已守（`notify_agent_done` / CLI `--dedup-key` / `upload_r2.py` 非 dry-run 语境）；改动形参会波及 3 个外部调用方，收益为 0、风险非 0 |
| `_save_warning_dedup_state` | 调用侧（`defer_warning` / flush）已守 | 不改（同上理由） |

**结论**：同类面**已穷举**，2 处真缺口（本批修）+ 1 处同型缺口（本批举一反三修）+ 2 处「概念不适用但已核清」。

### 2.2「#240 残余同类面」复核（P-5 订正）

`grep -rl "21600" scripts/`（排除 `scripts/tests/` 与 `scripts/test_*`）**实测 16 个非测试文件**（本批独立复算：brief_push_wrapper / check_failed_units / check_preupload_backup / check_r2_consistency / cloud_unit_patrol / deploy / notify / notify_sent / r2_upload_async / r2_upload_skip_notify / retry_failed_metrics / schedule_monitor / staticdata_backup_async / staticdata_sync / upload_r2 / with_lock），与原报告首轮「10 个」不符 —— **已在文档内订正为 16 并说明订正**（P-5）。

---

## 3. §23.3 举一反三清单（不只做点名处）

| 维度 | 清单 | 逐项结果 |
|---|---|---|
| **同模式**（#230 病灶形态：flush 前无条件建锁） | `flush_warning_batch` / `flush_digest`（唯二「抢全生命周期锁」的 flush 函数） | 2/2 已覆盖（后 1 处为本批新增修复） |
| **同模式**（#229 病灶形态：绕过「唯一写入函数单点守卫」的写盘） | `log_info` / `write_alert` / `_record_ledger` / `defer_warning` / `update_dedup` / `_save_warning_dedup_state` | 6/6 已核（§2.1） |
| **同数据源**（会写主仓 `data/` 的 legacy 套件） | notify 家族 4 个包装 + `feishu_ws_listener` 包装（写 `data/feishu_requests/forwarded_message_ids.jsonl`） | 5/5 已隔离（本条为**实测发现**：单纯 env-REPO 隔离**挡不住** import 期绑定量，见 §3.1） |
| **同组件**（import 期由 REPO 派生的路径常量） | `notify` 11 个 + `feishu_ws_listener` 2 个（登记于 `_REPO_PATH_ATTRS`） | 13/13 已重绑；读盘类（`*_CONFIG`/`TASKS_PATH`）**刻意不重绑**（CI/临时树无该文件，重绑会致用例失败/语义漂移） |
| **相关展示位**（前端链） | `static-site/style.css` → `style.min.css` → SW/版本串 | 注释改动；min 逐字节不变 ⇒ **无需 bump/deploy**（§4） |
| **相关展示位**（用户可见文案） | `nextday_plan.sh` sh 兜底句 vs py 侧文案（#247 双 dedup key 语境） | 已核：py 先发/本条兜底语义未变，只订正「未生成」失真表述 |
| **同链**（`#240` 判据文案耦合） | `check_failed_units.py` `_notify_sent` ↔ `notify_sent.py` ↔ notify 汇总打印文案 | 已在 `_notify_sent` docstring 写入**维护契约**（改汇总文案必须同步标记集） |

### 3.1 关键实测发现（item 7 的隐藏缺口）

`isolate_repo` 仅把 `REPO/GIT_REPO` 指向临时树时，**只覆盖「调用时解析」的路径**（如 `_ledger_path()` 每次读 env）；而 `notify.ALERTS_FILE` / `ALERTS_DIR` / … 是 **import 期绑定**，在同会话更早用例已 import `notify` 后**不随 env 变**。实测：6 文件家族批里 `test_notify_dedup` 的 `_mirror_severe` 仍把 `data/alerts/latest.md` 写进主仓。故新增 `_redirect_repo_paths()` 在 import 后显式重绑（收尾由 `_restore_modules` 整体还原；`feishu_ws_listener` 一并纳入 `_WATCH_MODULES` 防残留）。

---

## 4. 前端产物核对（min 哈希 before/after）

`style.css` 改动为**纯注释**（rcssmin 去注释）。

| 项 | 值 |
|---|---|
| HEAD 版 `style.css` 经 `rcssmin.cssmin()`（与 `build_min.py:179` 同参） | `d1c8a3db868dc16c90b16bd4d3c719b6` / 253519 B |
| 工作区新版同法 | `d1c8a3db868dc16c90b16bd4d3c719b6` / 253519 B |
| 结果 | **IDENTICAL** |
| 与仓内 `static-site/style.min.css` 现状比对 | **一致**（同 md5） |

⇒ **min 哈希未变 ⇒ 无需 bump 版本串、无需 deploy**（`main-merge.sh` 亦会跳过 bootprint 无变化的 bump 路径）。

---

## 5. 子项 9（git 运维）明细 + §25 恢复路径

**做法**：动态枚举（`git worktree list` + `git branch` 全集）→ **只删**「`git rev-list --count main..<branch>` = 0」的分支 → **当日（10-11）有活动/今日新建的 worktree·分支一律列「待主控复核」不删**（用户点名约束）。

**结果**：
- 已删（`ahead=0`，内容全在 `origin/main` 可达链上）：本地 feature 分支与远端同名分支（远端现仅存 4 条：`main` / `feat/b3-fundnav-cleanup` / `fix/verify-r2-full-standalone` / `fix/tests-date-sensitive-20261011`）。
- `git worktree list` 无我造成的孤儿 worktree；`git worktree prune --dry-run` 空。

**待主控复核（当日活动，一律不删）** —— 以下为**本次报告时点的实测快照**：

| worktree / 分支 | 说明 |
|---|---|
| `feat/next-steps-b2-lowrisk`（本 agent） | 本批分支 |
| `fix/verify-r2-full-standalone` @ `a6154e2dd` | 别线在跑 |
| `fix/tests-date-sensitive-20261011` @ `b6e85b409` | 别线在跑 |
| `feat/b3-fundnav-cleanup` @ `a88094c97` | 别线在跑 |
| `worktree-agent-a59ca4479ded02837` @ `7ad8873b6` | agent 分支（当日活动） |
| `worktree-agent-aa097cfc2ea5f63b0` @ `6cb62b5b4` | agent 分支（当日活动） |
| `worktree-agent-ab4446b2d65f29b81` @ `11776c31b` | agent 分支（当日活动） |
| `worktree-agent-ab563a094a08827b0` @ `d48ca5202` | agent 分支 |
| `worktree-agent-aeabaaf5ce79fe344` @ `6cb62b5b4` | agent 分支（当日活动） |

**§25 恢复路径（逐条落字）**：被删分支的内容**全部可从 `origin/main` 取回**（删除前置条件即 `main..<branch>` 计数=0，无独有 commit）。恢复命令：
```bash
git fetch origin
git branch <name> origin/main            # 重建同名分支(指向 main 可达链上的对应 commit)
# 或按需精确定位: git log --oneline origin/main | grep <commit-subject>
```
未做任何 `rm -rf` / `git gc` / `git prune`（无不可逆动作）。

---

## 6. 独立发现（**不属本批改动**，仅上报）

### 6.1 main CI ⑧ 自 2026-10-11 起红（两类，均已确认根因）

`CI Quality Gate` 在 `7ad8873b6`（2026-10-11 01:52Z）由 success→failure，而 `68245b767`（10-10 23:23Z，**前一版**）为 success；两次之间**仅 docs 提交**（`14635a732` / `7ad8873b6`）⇒ 结构性原因必是**时点/星期相关**。独立复现 + 因果验证：

| 类别 | 失败用例 | 根因（独立确认） | 判别证据 |
|---|---|---|---|
| ① **真 bug（生产可达）** | `test_188_s06_sync_blindspot_pytest` | `scripts/upload_r2.py:3730` 引用 `standalone_files`，而该变量**仅在 `else`（平日）分支赋值**；`full = datetime.date.today().weekday() == 6`（周日全量）时未绑定 ⇒ 只要周日对账发现 mismatch 即 `UnboundLocalError` | 2026-10-11 = **周日**（weekday=6）；令 `datetime.date.today()` 固定为非周日（本地临时 sitecustomize，未改仓）后该用例 **1 passed** ⇒ 触发条件坐实为「周日全量分支」 |
| ② **测试时间炸弹（生产无影响）** | `test_245_l2_budget_digest_20261010::test_04` / `::test_04d` | 硬编码 `_patch_now(datetime(2026,10,10,12:00))`，而条目日取**真实** `_today()=datetime.now()`；10-10 当天两者一致，10-11 起**永久失配**（`test_04` 反转成 `{'sent': True}`、`test_04d` 反转成 `{'sent': False}`）⇒ 此类**不会自愈**，每天都在红 | 用例源码自证（`_today()`=真实 now vs 硬编码 10-10） |

**交叉核对**：`origin/main` 现 tip `5a8226b6a` 的 CI run 结论亦为 **failure**（2026-10-11 02:08Z）。
**处置**：本批**不修**（B 级生产代码/别家用例，超 B2 授权面）；报告时点已存在在跑修复分支 `fix/verify-r2-full-standalone` 与 `fix/tests-date-sensitive-20261011`（见 §5 待复核表）—— 本节为**独立确认其根因**，供主控比对。

### 6.2 复现命令（本机）

```bash
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/     # 746 passed/2 skipped/3 failed
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q \
  /Users/linhuichen/code/trade/scripts/tests/test_188_s06_sync_blindspot_pytest.py \
  /Users/linhuichen/code/trade/scripts/tests/test_245_l2_budget_digest_20261010.py   # 基线(未改码)复现同样 3 failed
```

---

## 7. 自验证据（逐条对验收口径）

| 验收点 | 证据 |
|---|---|
| #229/#230 **打桩自测**（§18 L48：先证打桩判定生效，零真实外发） | `scripts/tests/test_229_230_notify_dryrun_gates_20261011.py` **14 passed**；首个用例 `test_zero_outbound_sentinel_is_effective` 先证 `_boom` 哨兵确实抛错（否则其余「零外发」断言即假绿）；全部落盘面 monkeypatch 到 `tmp_path` |
| **红先验**（旧码必须红） | 用 HEAD 版 `notify.py` 跑同文件：**10 failed / 4 passed**；换回新版 **14 passed** |
| 非 dry-run 分支=**代码级对照**（禁真跑生产 flush 链） | diff 论证：`log_info` 仅在 `dry_run` 命中时短路；`send_tiered` info 分支 `dry_run=False`（缺省）时返回值与旧版**逐字段相同**；`flush_warning_batch`/`flush_digest` 的 dry_run 短路置于 `mkdir+open` **之前**，`dry_run=False` 走原路径**零变化**；两处均由静态机检用例钉住「短路位置」防复发 |
| item 7 零残留 | 家族批（11 文件）跑后仓内 `data/alerts`、`data/feishu_requests` **均不存在** |
| item 8 min 哈希 | §4（IDENTICAL，与仓内 `style.min.css` 一致） |
| 语法/编译 | `bash -n nextday_plan.sh update_all.sh` OK；`py_compile` notify.py/check_failed_units.py/_wrap_util.py/conftest.py/新测试 OK |
| 全量回归 | `pytest -q scripts/tests/` 746 passed / 2 skipped / 3 failed（3 条 §6 既有） |
| §23.11 无静默 | 本批全程无冲突/覆盖/版本倒退；分支删除前均先核 `ahead=0` |

---

## 8. 遗留 / 观察项

1. **#240 P-2（低·观察）**：F1 的「响亮打日志」在生产调用链可能被父进程吞 stderr —— 本批按原文**只报不改**，建议并入「告警链 sent 语义收口」小任务。
2. **`update_dedup`/`_save_warning_dedup_state`** 仍是「调用侧守 dry_run」而非「函数内单点守卫」：本批**刻意不改**（理由见 §2.1），留档供后续统一口径时参考。
3. **main CI 红**（§6）在修复分支合并前会持续；任何 feat 走 `main-merge.sh` 都会看到 ⑧ FAIL，属**既有基线**、非本批引入。