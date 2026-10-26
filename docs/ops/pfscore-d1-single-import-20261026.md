# pf-score D1 同步改「一表一文件 · 一次导入」+ 单语句字节封顶（2026-10-26）

> 范围：**只做本地改造与本地验证**。本文第 8 节是「今晚 23:00 后单独派单」的生产实测清单，本次**未执行**，
> 全程未对远程 D1 做任何写操作（无 execute / import / 建表 / 删表，未跑 `pf_score_daily.sh`）。

涉及文件：
- `scripts/sync_fund_screener_to_d1.sh`（`fund_screener` 表）
- `scripts/sync_fund_score_to_d1.sh`（`fund_score` 表）
- `scripts/lib/d1_sql_bundle.py`（新：字节封顶打包器，纯计算，不连 D1）
- `scripts/lib/d1_execute.sh`（新：单文件导入 + 网络类失败重试，两个脚本共用一份，防第二份实现漂移）
- `scripts/tests/test_pfscore_d1_single_import_20261026.py`（新：14 个机检用例）

---

## 1. 依据（可修正的事实，均为已发生的实测）

| # | 依据 | 数值 / 位置 |
|---|---|---|
| 1 | 旧做法每 80 行一个 SQL 文件、逐文件 `wrangler d1 execute --file` | 单表 **347~354 次**调用 |
| 2 | 单次 wrangler 调用耗时（进程冷启动 + import 握手） | **6.35 秒/次**（`~/.config/.wrangler/logs/wrangler-2026-10-25_08-0[1-6]*.log` 的 `durationMs` 与文件名时间戳差） |
| 3 | 单表总耗时 | **37~44 分钟**（`docs/ops/pf-screener-cloud-steps-20261022.md`：00:58:57→01:36:19 = 37m22s，354 数据文件） |
| 4 | 其中 D1 侧真正执行的时间 | 11~13 毫秒/批（80 行）⇒ 占 **0.19%**；99.8% 是进程冷启动 + import 握手 |
| 5 | 官方上限 | `--file` 单文件 **5 GiB**（文件先 PUT 到 R2 再 ingest）；**单条语句 100,000 字节**，超了报 `statement too long: SQLITE_TOOBIG` |
| 6 | `--file` 本身就是 import 管线 | cli.js `executeRemotely` → `import init` → PUT → `ingest` → `poll`；wrangler 4.152 **没有** `d1 import` 子命令 |
| 7 | import 文件不能写 `BEGIN/COMMIT` | 导入作业本身就是一个事务（三重证据） |
| 8 | 旧口径的余量风险 | 347 文件合并后 361 条语句，**最大单条 78,105 字节**，离 100,000 只剩 22% |

依据若被推翻（例如生产实测单文件导入耗时远超预期、或服务端不回滚），按第 9 节回退，方案即判失败并重新定位。

## 2. 改动内容

1. **一表一文件、一次导入**：`000_schema` + 全部数据 + `999_meta` 按原顺序写进**同一个文件**
   `full_import.sql`；`DELETE FROM ...` 仍是**第一条数据语句**（紧跟 schema，位置未挪）。
   执行段对每个表**只调用一次** `npx wrangler d1 execute "$D1_DB" --remote -y --file=<单文件>`。
2. **按字节切批**（不再只按 80 行）：单条语句软上限 60,000 字节（UTF-8 实际字节，中文按 3 字节算），
   贪心装箱；单行本身就超软上限时**该行独立成句**（不与其他行混批）。
3. **硬断言**：生成完 `max_stmt_bytes < 90,000`，否则**生成阶段直接退出（rc=3）**，一个字节都不写盘/不上传。
4. **重试**：网络类失败（fetch failed / 连接断 / 超时 / 5xx）最多重试 2 次，退避 30s、90s，重试前打印剩余预算；
   **SQL 类错误不重试**（`SQLITE_TOOBIG` / syntax error / no such table|column / constraint failed）；
   重试用尽或预算用尽 ⇒ 照常非 0 退出（不吞），由既有 `_fail()` 写失败状态供巡检告警。
5. **score 脚本补 `DRY_RUN=1`**（此前只有 screener 有）：只生成不推 D1，不预检凭据、不写失败状态。
6. 校验段（D1 `COUNT(*)` 与本地比对）**未改动**。两表仍由 `pf_score_daily.sh` **串行**调用（未改）。

日志新增（两个脚本都打印）：文件路径、总字节、语句条数、**最大单条字节**、软/硬上限、超长单行语句数、模式。

## 3. 实现预期 vs 实测（X→Y）

| 指标 | 改前 | 预期 | 实测（本机 dry-run，真实库全量） |
|---|---|---|---|
| 单表 wrangler 调用次数 | 347~354 次 | **1 次** | 生成产物 **1 个文件** ⇒ 执行段 1 次（dry-run 不触网，调用次数由 `files=1` 结构保证 + 单测断言 `["full_import.sql"]`） |
| dry-run 生成的文件数 | 347（数据）+2 | **1** | screener **1**、score **1** |
| 单表预期耗时 | 18~22 分钟 | 45~55 秒 | 本地无法测服务端导入耗时 ⇒ 见第 8 节生产实测第 2 项 |
| 中途失败后线上状态 | 半成品（2000/3520 行） | 旧全量（待实测确认） | 本机不可测 ⇒ 见第 8 节第 1 项（临时表 `_atomic_test`） |
| 单语句最大字节 | 78,105（无守卫） | ≤60,000 且有断言 | screener **59,999**、score **60,000** |

## 4. 证据用例（实测输出）

### 4.1 screener dry-run（真实 `trade-data/data/public_fund.db`，27758 行）

```
[sync-screener-python] mode=single rows=27758 cols=80 files=1 path=/var/folders/.../fund-screener-d1.72993/full_import.sql
  total_bytes=24476215 statements=425 max_stmt_bytes=59999 soft_cap=60000 hard_cap=90000
  oversize_single_row_stmts=0 coverage_cols=79
[sync-screener] DRY_RUN 完成: mode=single 生成目录 .../fund-screener-d1.72993 待执行文件数=1(未推 D1)
```

sqlite3 载入合并文件（`sqlite3 /tmp/fscr_bundle_test.db < full_import.sql`，耗时 2.57s）：

```
27758                        # fund_screener 行数
3                            # idx_fscr_composite / idx_fscr_type / idx_fscr_scale
fund_total | 27758           # screener_meta 与实表一致
```

### 4.2 score dry-run（同一真实库）

```
[sync-d1-python] mode=single score_date=20260913 rows=27758 files=1 path=.../fund-score-d1.73071/full_import.sql
  total_bytes=15703143 statements=271 max_stmt_bytes=60000 soft_cap=60000 hard_cap=90000 oversize_single_row_stmts=0
[sync-d1] DRY_RUN 完成: mode=single 生成目录 .../fund-score-d1.73071 待执行文件数=1(未推 D1)
```

sqlite3 载入：`27758` 行、`2` 个索引（`idx_fs_composite` / `idx_fs_type`）、`sync_meta` = `score_date=20260913 / rows=27758`。

### 4.3 字节封顶与孤立超长行（用例 3）

`test_screener_dry_run_long_row_isolated_and_passes`：fixture 里塞一只 strategy = 21,660 个汉字（=64,980 字节）：
- 生成成功、`oversize_single_row_stmts=1`；
- 含长文本的那条语句**只有一行**（断言语句内无 `),(` 分隔符）⇒ 不会把 65KB 拖进大批；
- 其余语句均 ≤60,000 字节，最大 <90,000。

### 4.4 超限守卫（用例 4）

`test_screener_over_hard_cap_fails_before_writing_package`：strategy = 31,670 个汉字（=95,010 字节）：
- 脚本 rc≠0，输出含 `硬上限` + `SQLITE_TOOBIG` + 实际字节数；
- 生成目录里 **`.sql` 文件数 = 0** ⇒ 绝不上传半个包。

### 4.5 判别力（用例 5，变异实测后还原）

| 变异 | 结果 | 结论 |
|---|---|---|
| 把「按字节封顶」改回「只按 80 行切批」（`d1_sql_bundle.add_inserts`） | 3 条红：`test_packer_respects_byte_soft_cap_and_keeps_all_rows`、`test_packer_isolates_oversize_single_row`、`test_screener_dry_run_long_row_isolated_and_passes` | 用例 3 必红 ✓ |
| 去掉 `bundle.assert_limits()` 调用 | 1 条红：`test_screener_over_hard_cap_fails_before_writing_package`（rc 变 0） | 用例 4 必红 ✓ |
| 还原上述两处 | `18 passed`（本文件 14 + `test_266` 4） | 绿 ✓ |

### 4.6 回退开关实测

`D1_SPLIT_MODE=legacy DRY_RUN=1` 跑真实库：生成 `000_schema.sql` + `001_data.sql` … `347_data.sql` + `999_meta.sql`
（数据文件数 **347**，与改前一致），文件内容结构同旧版（首个数据文件以 `DELETE FROM fund_screener;` 开头）。
score 脚本同法可切回。

**与改动前产物逐字节对比（证明回退是真回退，不是"看起来像"）**

做法：`git show HEAD:scripts/sync_fund_screener_to_d1.sh` 抽出旧版 `<<'PYEOF'` 生成段（同法抽 score），
喂同一个真实库各跑一遍，产物与改造后的 legacy 产物 `diff -rq` 比对：

| 表 | 差异项 | 归一化后结论 |
|---|---|---|
| `fund_screener` | 仅 `999_meta.sql` / `meta.json`（内含 `built_at` 时间戳） | 时间戳归一化后**零差异**；`000_schema.sql` + 347 个数据文件逐字节一致 |
| `fund_score` | 仅 `999_meta.sql`（内含 `synced_at`） | 时间戳归一化后**零差异**；`000_schema.sql` + 347 个数据文件逐字节一致 |

即：回退模式下生成的 SQL 与改动前完全等价（只有本来每次都会变的时间戳字段不同）。
旧版真实库实测同时复现了原风险值：`files=347 max_stmt_bytes=78107`（无字节守卫）。

### 4.7 全量 pytest

```
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/
1585 passed, 2 skipped in 387.70s (0:06:27)
```

- 基线 `1571 passed, 2 skipped` + 本批新增 14 个用例 = **1585 passed, 2 skipped，零倒退**。
- 相关回归单跑（`test_275_d1_sync_visibility_20261022` + `test_266_fund_screener_contract` + 本批新用例）
  提前跑过一遍：`30 passed in 6.45s`（`test_275` 端到端走真脚本 + 假 npx，改后仍绿）。
- 改的是 `scripts/` 源码，按 L52 要求跑的是**全量**（`tests/` 里有源码形状守卫），不是只跑相关用例。
- 首次全量跑时发现新用例里的假 `npx` 会按参数位置 `echo ok > "$3"` 往仓库根写一个叫 `execute`
  的垃圾文件（`$3` 恰好是子命令名）；已改成只打 stdout（由 lib 重定向到指定输出文件）。
  修复后复跑全量：`1585 passed, 2 skipped in 432.22s`，仓库根无残留文件。

## 5. 回退路径（出问题怎么退回旧的多文件模式）

```bash
# 只回退一个表（以 screener 为例）：加一个环境变量即可，代码不用改
D1_SPLIT_MODE=legacy bash scripts/sync_fund_screener_to_d1.sh
D1_SPLIT_MODE=legacy bash scripts/sync_fund_score_to_d1.sh
```

- 生产承载点是 `scripts/pf_score_daily.sh` 末尾的两行 `bash "$GIT_REPO/scripts/sync_..."`；
  要长期回退，在该脚本调用前 `export D1_SPLIT_MODE=legacy`（或在云上 systemd unit 加 `Environment=`），
  撤掉/删掉即恢复默认单文件模式。
- 验证回退生效：日志里 `mode=legacy`、`待执行文件数=349`（screener）/ 348（score）；
  默认模式为 `mode=single`、`待执行文件数=1`。
- 非法值（如 `D1_SPLIT_MODE=bogus`）**启动即失败 rc=2**，不会静默退回任何一种模式。
- 其它可调参数（一般不用动）：`D1_MAX_STMT_BYTES=60000`、`D1_MAX_STMT_BYTES_ASSERT=90000`、
  `D1_RETRY_DELAYS="30 90"`、`D1_SYNC_BUDGET_SEC=1800`。
- 回退后行为 = 改动前逐字节一致的产物（多文件、80 行/批、无字节守卫），**速度回到 37~44 分钟**。

## 6. 边界维度清单（七轴；供 reviewer §10.8 独立复核对账）

| # | 维度 | 来源（需求点 / 改动点） | 测 / 不测 | 理由与结果 |
|---|---|---|---|---|
| 1 | **输入域**：行数规模、字段空值、中文、单引号、超长文本 | 生成段（行值构造、字节切批） | **测** | 真实库全量 27758 行 dry-run（含中文/引号转义/NULL）+ sqlite 载入逐行校验；单测覆盖 UTF-8 字节计数（30000 汉字=90000 字节必须触发硬上限） |
| 2 | **状态组合**：首跑 / 重跑幂等 / 表已存在 / D1 存量行 | `CREATE TABLE IF NOT EXISTS` + `DELETE` 全量替换 | **部分测** | 测：sqlite 两次载入内容 hash 不变（沿用 `test_266` 幂等断言）、`DELETE` 仍是第一条数据语句；**不测**：生产 D1 上「中途失败后旧全量是否保留」= 服务端事务语义，本机无法验证 ⇒ 第 8 节第 1 项 |
| 3 | **时序**：生成→执行顺序、重试退避、时间预算 | 执行段重试逻辑 | **测** | 假 npx 打桩三条：网络失败第 3 次成功=rc0、SQL 类错误只尝试 1 次、用尽=非 0；预算耗尽=立刻非 0。真实网络抖动时序 **不测** ⇒ 第 8 节第 2 项 |
| 4 | **上下游依赖**：`pf_score_daily.sh` / `pf_score_weekly.sh` 调用方、`worker/fund_{score,screener}.js` 读表、`check_failed_units.py` 巡检 | 调用契约 / 表结构 / 失败状态 | **测** | 退出码语义不变（0 / 非 0）；DRY_RUN 不写失败状态（不污染巡检）；表结构语句逐字未变（仅拆成语句列表）；`test_275` 回归通过 |
| 5 | **极端值**：65KB 单行、95KB 单行、边界 60,000/90,000 | 字节封顶 + 硬断言 | **测** | 4.3 / 4.4 用例 + 单测（打包器层 3 条）；判别力已验（4.5） |
| 6 | **回退路径**：`D1_SPLIT_MODE=legacy` | 任务书硬要求 6 | **测** | 真实库 legacy dry-run：349 个 .sql、347 个数据文件（与改前一致）；非法值 rc=2；长期回退改法见第 5 节 |
| 7 | **并发与重入**：两表并行、同脚本重入、D1 import 期间整库不可服务 | `pf_score_daily.sh` 串行调用 | **部分测** | 测：两表仍由调用方串行（本次未引入并行）；脚本无内部并行；同日重入 = DELETE+INSERT 幂等。**不测**：import 期间 D1 对外不可服务的并发影响 —— 由「保持串行 + 单文件更快」规避，生产实测期间不并发（第 8 节） |

## 7. 同模式 / 同数据源消费点清单（§23.3 举一反三）

- 全仓用 `wrangler d1 execute --file` 逐文件导入的脚本**只有这两个**（`grep -rn "d1 execute"` 结果：其余全是文档）。
  ⇒ 两个都改了，无第三处漏改。
- 共享逻辑抽到 `lib/d1_sql_bundle.py` + `lib/d1_execute.sh`，避免两脚本各写一份（第二份实现静默漂移，§5.4⑦ 同精神）。
- 读这两张表的消费点（`worker/fund_score.js`、`worker/fund_screener.js`、前端 offshore tab）**零改动**：
  表名/列名/索引名逐字未变，只是打包与传输方式变化。
- 巡检消费点（`check_failed_units.py` 读 `<REPO>/data/d1_sync_state/*.json`）零改动：失败仍走 `_fail()`。

## 8. 今晚 23:00 后生产实测清单（本次**不执行**，交主控单独派单）

1. **原子性**：建临时表 `fund_screener_atomic_test`（名字必须带 `_atomic_test`），导一个「前面正常 + 末尾故意 UNIQUE 冲突」
   的小文件，查 `COUNT(*)`：
   - `0` ⇒ 服务端真原子（失败整包回滚，线上保住旧全量）；
   - `非 0` ⇒ 服务端不回滚 ⇒ **方案降级**：改走影子表（新表导入完成后再 `DROP`/`RENAME` 切换）。
2. **真实单文件耗时与上传速率**：导一次 24~25MB 的 `full_import.sql`，记录总耗时、wrangler 输出里的上传/ingest 分段时间。
   预期 45~55 秒，悲观 ≤2 分钟；若 >5 分钟则复核方案（可能需要拆分或换直连 API）。
3. **清理与回归**：删除测试表，并确认 `fund_screener` / `fund_score` 两表行数**未被触碰**（跑前跑后各记一次 `COUNT(*)`）。
   实测全程避开盘中与盘后任务时点（§14），23:00 后窗口执行。

## 9. 已知风险 / 待确认

- **单文件 25MB 走 `--file` 的实际上限与耗时**由生产实测第 2 项确认（本机只能确认文件生成与本地载入正确）。
- **服务端事务是否真回滚**由第 1 项确认；如果 D1 import 不是全事务，本改造的「失败后旧全量保留」预期不成立，需改影子表（已在第 1 项写明降级路径）。
- `full_import.sql` 生成在临时目录（`TMPDIR`/`/tmp`），25MB 级；生产磁盘余量需正常（与此前 347 个文件总量相同量级）。
- 若 `max_stmt_bytes` 逼近 90,000 硬上限（当前 59,999/60,000），说明某只基金长文本在变长 —— 日志会打印该值，便于提前发现。