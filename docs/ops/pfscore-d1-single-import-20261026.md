# pf-score D1 同步改「一表一文件 · 一次导入」+ 单语句字节封顶（2026-10-26）

> 范围：**只做本地改造与本地验证**。本文第 8 节是「今晚 23:00 后单独派单」的生产实测清单，本次**未执行**，
> 全程未对远程 D1 做任何写操作（无 execute / import / 建表 / 删表，未跑 `pf_score_daily.sh`）。

涉及文件：
- `scripts/sync_fund_screener_to_d1.sh`（`fund_screener` 表）
- `scripts/sync_fund_score_to_d1.sh`（`fund_score` 表）
- `scripts/lib/d1_sql_bundle.py`（新：字节封顶打包器，纯计算，不连 D1）
- `scripts/lib/d1_execute.sh`（新：单文件导入 + 网络类失败重试，两个脚本共用一份，防第二份实现漂移）
- `scripts/tests/test_pfscore_d1_single_import_20261026.py`（新：首批 14 个 + 审查收尾批 7 个 = **21 个机检用例**）

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
3. **硬断言**：生成完 `max_stmt_bytes < 90,000`，否则**生成阶段直接失败**——python 内部 `sys.exit(3)`，
   但 shell 调用方经 `_fail()` 对外退出码是 **1**（不是 3；巡检只看 0/非 0）。生成目录里**一个文件都不留**
   （`.sql` 与 `meta.json` 都不写：`meta.json` 本批已从「断言之前写」挪到「全部生成动作之后写」，
   旧版会在超限时残留约 1.8KB 的 `meta.json`）。**不上传**。
4. **重试**：网络类失败（fetch failed / 连接断 / 超时 / 5xx）最多重试 2 次，退避 30s、90s；
   **SQL 类错误不重试**（`SQLITE_TOOBIG` / syntax error / no such table|column / constraint failed）。
   - 单次 `wrangler d1 execute` 上限 **300s**（`D1_EXEC_TIMEOUT_SEC`，25MB 导入生产预期 45~55s 的约 5 倍余量）；
     超时（rc=124）按**网络类失败**处理。云上用 coreutils `timeout`；本机 mac 没有该命令时退化为
     bash 轮询实现（`kill -0` + `sleep 1` + `kill -TERM`，同样返回 124），保证测试不靠「本机恰好有 timeout」假绿。
   - 重试总预算默认 **360s**（`D1_RETRY_BUDGET`，旧名 `D1_SYNC_BUDGET_SEC` 仍兼容），**远小于** daily 任务的
     10 分钟墙（`TimeoutStartUSec`，实测 10-23/10-25 都在 16:10 被杀）——旧默认 1800s 永远用不到，只会让
     进程白挂到 systemd 杀。每次尝试前先查预算（不是只在退避前），单次上限还会被剩余预算压小；
     预算耗尽打印「已用 Xs / 预算 Ys, 放弃重试」。
   - 重试用尽或预算用尽 ⇒ 照常非 0 退出（不吞），由既有 `_fail()` 写失败状态供巡检告警。
5. **score 脚本补 `DRY_RUN=1`**（此前只有 screener 有）：只生成不推 D1，不预检凭据、不写失败状态。
6. 校验段（D1 `COUNT(*)` 与本地比对）**比对逻辑未改**，只给这条查询包了 60s 超时（`D1_VERIFY_TIMEOUT_SEC`，
   防止小查询也无限挂；它仍**不在重试内**，见 §9）。两表仍由 `pf_score_daily.sh` **串行**调用（未改）。

日志新增（两个脚本都打印）：文件路径、总字节、语句条数、**最大单条字节**、软/硬上限、超长单行语句数、模式。

## 3. 实现预期 vs 实测（X→Y）

> **口径声明（2026-10-26 审查 M4）**：本文所有「实测」数字来自**本机镜像**
> `trade-data/data/public_fund.db`（`fund_basic` 27,758 行、`MAX(score_date)=20260913`，已陈旧），
> **不是生产库**。生产权威库实测为 **28,302 行、`MAX(score_date)=20261025`**，按体积推算生产包体
> 比本机产物大约 **+2%**（screener ≈25.0MB、score ≈16.0MB）。真实耗时与体积以第 8 节生产实测为准。

| 指标 | 改前 | 预期 | 实测（本机镜像 dry-run 全量） |
|---|---|---|---|
| 单表 wrangler 调用次数 | 347~354 次 | **1 次** | 生成产物 **1 个文件** ⇒ 执行段 1 次（dry-run 不触网，调用次数由 `files=1` 结构保证 + 单测断言 `["full_import.sql"]`） |
| dry-run 生成的文件数 | 347（数据）+2 | **1** | screener **1**、score **1** |
| 单表预期耗时 | 18~22 分钟 | 45~55 秒 | 本地无法测服务端导入耗时 ⇒ 见第 8 节生产实测第 2 项 |
| 中途失败后线上状态 | 半成品（2000/3520 行） | 旧全量（待实测确认） | 本机不可测 ⇒ 见第 8 节第 1 项（临时表 `_atomic_test`） |
| 单语句最大字节 | 78,105（无守卫） | ≤60,000 且有断言 | screener **59,999**、score **60,000** |

## 4. 证据用例（实测输出）

### 4.1 screener dry-run（本机镜像 `trade-data/data/public_fund.db`，27,758 行，**非生产库**）

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

### 4.2 score dry-run（同一本机镜像；`score_date=20260913` 是镜像值，生产会是 20261025）

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
- 脚本退出码 **= 1**（python 内部 3 经 `_fail()` 归一；旧文档写 rc=3 不准确，本批已改），
  输出含 `硬上限` + `SQLITE_TOOBIG` + 实际字节数；
- 生成目录里 **文件数 = 0**（`.sql` 与 `meta.json` 都没有；旧版 meta.json 在断言前写、会残留 1,779B，
  本批已挪到全部生成动作之后）⇒ 绝不上传半个包。
- score 表同样有 `test_score_over_hard_cap_fails_before_writing_package` 锁这两个断言。

### 4.5 判别力（用例 5，变异实测后还原）

| 变异 | 结果 | 结论 |
|---|---|---|
| 把「按字节封顶」改回「只按 80 行切批」（`d1_sql_bundle.add_inserts`） | 3 条红：`test_packer_respects_byte_soft_cap_and_keeps_all_rows`、`test_packer_isolates_oversize_single_row`、`test_screener_dry_run_long_row_isolated_and_passes` | 用例 3 必红 ✓ |
| 去掉 `bundle.assert_limits()` 调用 | 1 条红：`test_screener_over_hard_cap_fails_before_writing_package`（rc 变 0） | 用例 4 必红 ✓ |
| 还原上述两处 | 本文件 + `test_266` 全绿（首批当时 18 passed；加收尾批后本文件 21 passed） | 绿 ✓ |

### 4.6 回退开关实测

`D1_SPLIT_MODE=legacy DRY_RUN=1` 跑本机镜像：生成 `000_schema.sql` + `001_data.sql` … `347_data.sql` + `999_meta.sql`
（数据文件数 **347**，与改前一致），文件内容结构同旧版（首个数据文件以 `DELETE FROM fund_screener;` 开头）。
score 脚本同法可切回。

**与改动前产物逐字节对比（证明回退是真回退，不是"看起来像"）**

做法：`git show HEAD:scripts/sync_fund_screener_to_d1.sh` 抽出旧版 `<<'PYEOF'` 生成段（同法抽 score），
喂同一个本机镜像各跑一遍，产物与改造后的 legacy 产物 `diff -rq` 比对：

| 表 | 差异项 | 归一化后结论 |
|---|---|---|
| `fund_screener` | 仅 `999_meta.sql` / `meta.json`（内含 `built_at` 时间戳） | 时间戳归一化后**零差异**；`000_schema.sql` + 347 个数据文件逐字节一致 |
| `fund_score` | 仅 `999_meta.sql`（内含 `synced_at`） | 时间戳归一化后**零差异**；`000_schema.sql` + 347 个数据文件逐字节一致 |

即：回退模式下生成的 SQL 与改动前完全等价（只有本来每次都会变的时间戳字段不同）。
旧版在本机镜像上实测同时复现了原风险值：`files=347 max_stmt_bytes=78107`（无字节守卫）。

### 4.7 全量 pytest

首批（单文件导入本体）：
```
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/
1585 passed, 2 skipped in 387.70s (0:06:27)
```

审查收尾批（M1/M2/M3/L2，+7 个用例）：
```
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/
1592 passed, 2 skipped in 337.15s (0:05:37)
```

删掉那个不可达的 score 守卫（见 §4.8.3）后又跑了一遍全量：
`1592 passed, 2 skipped in 335.20s (0:05:35)` —— 数字一致，零倒退。

- 首批基线 `1571 passed, 2 skipped` + 14 个新用例 = **1585**；收尾批基线 1585 + 7 个新用例 = **1592**，
  两批都**零倒退**。
- 相关回归单跑（`test_275_d1_sync_visibility_20261022` + `test_266_fund_screener_contract` + 本批新用例）
  提前跑过一遍：`37 passed in 15.48s`（`test_275` 端到端走真脚本 + 假 npx，改后仍绿）。
- 改的是 `scripts/` 源码，按 L52 要求跑的是**全量**（`tests/` 里有源码形状守卫），不是只跑相关用例。
- 首次全量跑时发现新用例里的假 `npx` 会按参数位置 `echo ok > "$3"` 往仓库根写一个叫 `execute`
  的垃圾文件（`$3` 恰好是子命令名）；已改成只打 stdout（由 lib 重定向到指定输出文件）。
  修复后复跑全量：`1585 passed, 2 skipped in 432.22s`，仓库根无残留文件。

### 4.8 审查收尾批（M1/M2/M3/L2）证据与判别力

#### 4.8.1 M1 命令行 argv 断言

假 `npx` 现在记录**完整 argv**（每行一根、以 ASCII `0x1F` 分隔；bash 3.2 用八进制 `\037`），
`test_execute_argv_shape_and_file_flag_with_spaces` 断言：

- 参数个数与顺序 = `["wrangler", "d1", "execute", "testdb", "--remote", "-y", "--file=<路径>"]`（**7 个**）；
- 路径含空格时仍是**单个参数**（不是被拆成两个）；
- `--file=` 的值等于生成目录里那个文件。

判别力实测：生产拼命令改成 `--file $file`（少引号）⇒ 该用例红（argv 多出 5 项，路径被空格拆开）；
参数顺序打乱成 `execute --remote -y <db>` ⇒ 红（index 3 `--remote` != `testdb`）。

#### 4.8.2 M2 单次超时与重试预算

- `test_single_call_timeout_is_enforced`：假 npx 睡 5s + 单次上限 1s ⇒ 3 次尝试、rc≠0、stderr 含「超时」、
  总耗时 <10s。**本机 mac 没有 coreutils `timeout`**，该用例真实走的是 bash 轮询回退分支（不是假绿）。
- `test_retry_budget_exhausted_before_first_attempt`：deadline 已过 + `D1_BUDGET_START=now-100` +
  `D1_BUDGET_TOTAL_SEC=360` ⇒ **一次调用都没发起**（`attempts.txt` 不存在 / 0 行），
  stderr 匹配「已用 10[01]s / 预算 360s」。
- 其余重试语义用例（网络失败第 3 次成功 / SQL 错不重试 / 重试用尽非 0）保持绿。

判别力实测：去掉 `_d1_run_with_timeout` 包装 ⇒ 超时用例红（rc 变 0，5s 后才返回）；
去掉预算耗尽检查 ⇒ 预算用例红（实际发起了 1 次调用）。

#### 4.8.3 L2 空输入：会不会清空线上表？

**实测结论：两模式都不会。** 都不产出「可导入的 DELETE-only 包」：

- **single**：生成段上游守卫先退出（screener：`fund_basic 无数据`；score：`无有效评分`），根本到不了打包；
  打包器再兜一层结构防线——`add_inserts` 收到空行集**先抛错、且不把 `DELETE` 入队**
  （`scripts/lib/d1_sql_bundle.py:76-79`），即使上游守卫将来被删，也产不出 DELETE-only 包。
- **legacy**：空输入只写 `000_schema.sql`，不生成 `001_data.sql` ⇒ 落盘文件里没有 `DELETE`（旧版行为，安全）。

三条用例（都含「目录内任何文件不得出现 `DELETE FROM`」断言）：

| 用例 | 断言 | 结果 |
|---|---|---|
| `test_screener_empty_input_single_fails_without_package` | rc≠0、含 `fund_basic 无数据`、无 .sql、无 `DELETE FROM` | 绿 |
| `test_screener_empty_input_legacy_fails_without_delete` | rc≠0、无 `001_data.sql`、无 `DELETE FROM` | 绿 |
| `test_score_empty_input_single_fails_without_package` | rc≠0、含 `无有效评分`、无 .sql、无 `DELETE FROM` | 绿 |

**行为差异与结论（诚实标注）**：single 是**主动失败**（更响），legacy 是「只写 schema 后失败」；
两者对线上数据的效果相同 = **保留旧全量**。所以**不统一行为也可以**，本批只做「结构加固 + 用例锁行为」，
不改任何一方的产物格式。

**一个中间过程要如实记下**：本批起初在 score 脚本加过一个 `if not rows: exit(1)` 守卫，变异测试证明它
**不可达**（`MAX(score_date)` 与取数查询用同一个 `composite_score IS NOT NULL` 谓词 ⇒ latest 有值时 rows 必非空），
已删除该分支，改成注释写清三层防线（不可达分支测不到、只会掩盖真实防线）。

判别力实测：打包器去掉空行集守卫 ⇒ 打包器用例红（`DID NOT RAISE ValueError`）；
删掉 screener 上游空数据守卫 ⇒ 端到端用例红（缺少 `fund_basic 无数据` 输出 / 走崩溃路径）。

#### 4.8.4 本批变异矩阵（改坏 → 必红 → 还原 → 绿）

| # | 改坏什么 | 期望变红的用例 | 实测 |
|---|---|---|---|
| 1 | 拼命令少引号：`--file="$file"` → `--file $file` | `test_execute_argv_shape_and_file_flag_with_spaces` | rc=1，argv 断言失败 ✓ |
| 2 | 参数顺序打乱：`execute "$db" --remote -y` → `execute --remote -y "$db"` | 同上 | rc=1，index 3 不符 ✓ |
| 3 | 去掉 `_d1_run_with_timeout` 包装 | `test_single_call_timeout_is_enforced` | rc=1，返回码变 0 ✓ |
| 4 | 去掉预算耗尽检查（第一处） | `test_retry_budget_exhausted_before_first_attempt` | rc=1，真发起了调用 ✓ |
| 5 | `meta.json` 写盘挪回硬断言之前（screener + score） | 两个 `*_over_hard_cap_fails_before_writing_package` | rc=1，2 failed（目录非空）✓ |
| 6 | 打包器放行空行集（去掉 `if not rows: raise`） | `test_packer_empty_rows_raises_without_queueing_delete` | rc=1，DID NOT RAISE ✓ |
| 7 | 删掉 screener 上游空数据守卫 | `test_screener_empty_input_single_fails_without_package` | rc=1，缺 `fund_basic 无数据` ✓ |

全部还原后复跑：**21 passed**。四份源码的 md5 与变异前逐位一致（变异脚本里强制断言）。

> 诚实记录：第一轮变异脚本把用例名单独传给 pytest（没带 `文件::`），pytest 返回 **rc=4「找不到用例」**，
> 脚本一度把它当成「变红」——这是**假红**。已改成 `<文件>::<用例>` 选择器，并显式区分
> `rc==1`（真失败=有效判别力）/ `rc==4`（用法错=无效），重跑后 7/7 都是真红。

#### 4.8.5 文档本批改了哪些处（M3 + M4 + 差集）

- M3：§2 第 3 条（调用方退出码 **1**、生成目录零残留）、§2 第 4 条（单次超时 + 预算口径）、§4.4（rc=1、文件数 0）。
- M4：§3 新增口径声明（本机镜像 27,758 行 / 20260913 vs 生产 28,302 行 / 20261025 / 包体 +2%）、
  §4.1 / §4.2 / §4.6 / §6 里把本机镜像称作「真实库」的表述全部改为「本机镜像」；
  现在正文只有两处出现这三个字，且都是「审查原话引用」（§4.8.5 本行与 §6.1 第 5 行），不是事实陈述。
- §5：可调参数换成 `D1_EXEC_TIMEOUT_SEC=300` / `D1_VERIFY_TIMEOUT_SEC=60` / `D1_RETRY_BUDGET=360`（含理由），
  并补「legacy 在 daily 600s 墙下跑不完」的硬限制。
- §6：边界清单新增第 8/9/10 行（空输入、外层墙与单次超时、生成目录残留），并新增 §6.1「审查差集 10 条逐条处置」。
- §8：生产实测第 1 项加查 meta 表；新增第 4 项「import 期间并发读 GET 观察」。
- §9：新增已知残留清单（L1/L3/计数校验不在重试内/H1 回退限制/H2 时点）。

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
- 其它可调参数（一般不用动）：
  - `D1_MAX_STMT_BYTES=60000`（单条语句软上限）、`D1_MAX_STMT_BYTES_ASSERT=90000`（硬断言）
  - `D1_RETRY_DELAYS="30 90"`（两项 = 最多重试 2 次）
  - `D1_EXEC_TIMEOUT_SEC=300`（单次 `wrangler d1 execute` 上限；超时=网络类失败，可重试）
  - `D1_VERIFY_TIMEOUT_SEC=60`（结尾 D1 计数查询上限；小查询不需要 300s）
  - `D1_RETRY_BUDGET=360`（重试总预算，**必须远小于调用方的墙**；旧名 `D1_SYNC_BUDGET_SEC` 仍兼容）
    - 360s 的理由：daily 任务的有效墙是 10 分钟（`TimeoutStartUSec=10min`），还要给生成（本机镜像实测
      生成 screener 24MB 约十几秒）与校验留余量；旧默认 1800s 在 10 分钟墙下永远用不到，只会白等到被 kill。
    - 预算内单次上限会被剩余预算压小（剩余 20s 不会再发 300s 的调用）；耗尽打印「已用 Xs / 预算 Ys」。
- **⚠️ 回退 legacy 的硬限制（诚实标注，上线决策待主控/用户拍板）**：legacy 模式单表 37~44 分钟，
  在 daily 任务的 10 分钟墙里**根本跑不完**（连第一张表都跑不完）。所以「出问题就回退 legacy」不能单独执行：
  要么同时把 daily 的 `TimeoutStartUSec` 提到 ≥90 分钟（或把 sync 挪到大墙窗口），
  要么接受回退期间两表停更（前端会降级到 Top100，不白屏）。本次**未改云上 unit**（超出范围）。
- 回退后行为 = 改动前逐字节一致的产物（多文件、80 行/批、无字节守卫），**速度回到 37~44 分钟**。

## 6. 边界维度清单（七轴；供 reviewer §10.8 独立复核对账）

| # | 维度 | 来源（需求点 / 改动点） | 测 / 不测 | 理由与结果 |
|---|---|---|---|---|
| 1 | **输入域**：行数规模、字段空值、中文、单引号、超长文本 | 生成段（行值构造、字节切批） | **测** | 本机镜像全量 27,758 行 dry-run（含中文/引号转义/NULL）+ sqlite 载入逐行校验；单测覆盖 UTF-8 字节计数（30000 汉字=90000 字节必须触发硬上限）。**不测**：生产库 28,302 行的真实体积（预计 +2%，由第 8 节实测确认） |
| 2 | **状态组合**：首跑 / 重跑幂等 / 表已存在 / D1 存量行 | `CREATE TABLE IF NOT EXISTS` + `DELETE` 全量替换 | **部分测** | 测：sqlite 两次载入内容 hash 不变（沿用 `test_266` 幂等断言）、`DELETE` 仍是第一条数据语句；**不测**：生产 D1 上「中途失败后旧全量是否保留」= 服务端事务语义，本机无法验证 ⇒ 第 8 节第 1 项 |
| 3 | **时序**：生成→执行顺序、重试退避、时间预算 | 执行段重试逻辑 | **测** | 假 npx 打桩三条：网络失败第 3 次成功=rc0、SQL 类错误只尝试 1 次、用尽=非 0；预算耗尽=立刻非 0。真实网络抖动时序 **不测** ⇒ 第 8 节第 2 项 |
| 4 | **上下游依赖**：`pf_score_daily.sh` / `pf_score_weekly.sh` 调用方、`worker/fund_{score,screener}.js` 读表、`check_failed_units.py` 巡检 | 调用契约 / 表结构 / 失败状态 | **测** | 退出码语义不变（0 / 非 0）；DRY_RUN 不写失败状态（不污染巡检）；表结构语句逐字未变（仅拆成语句列表）；`test_275` 回归通过 |
| 5 | **极端值**：65KB 单行、95KB 单行、边界 60,000/90,000 | 字节封顶 + 硬断言 | **测** | 4.3 / 4.4 用例 + 单测（打包器层 3 条）；判别力已验（4.5） |
| 6 | **回退路径**：`D1_SPLIT_MODE=legacy` | 任务书硬要求 6 | **测** | 本机镜像 legacy dry-run：349 个 .sql、347 个数据文件（与改前一致）；非法值 rc=2；长期回退改法见第 5 节。**不测**：legacy 在 daily 600s 墙下能否跑完 —— 已知跑不完（37~44 分钟），见 §5 末条 |
| 7 | **并发与重入**：两表并行、同脚本重入、D1 import 期间整库不可服务 | `pf_score_daily.sh` 串行调用 | **部分测** | 测：两表仍由调用方串行（本次未引入并行）；脚本无内部并行；同日重入 = DELETE+INSERT 幂等。**不测**：import 期间 D1 对外不可服务的并发影响 —— 由「保持串行 + 单文件更快」规避，生产实测期间不并发（第 8 节） |
| 8 | **空输入**：上游当天 rows=0 | 生成段 / `d1_sql_bundle.add_inserts` / legacy 分支 | **测** | 三层防护 + 3 条用例实测（§4.8.3）：single 与 legacy **都不会产出带 `DELETE` 的空包** ⇒ 不会清空线上表；single 主动失败（不覆盖旧数据），legacy 只写 schema（也保留旧数据） |
| 9 | **外层墙与单次超时**：daily 600s 墙、单次调用卡死 | 审查 M2 | **测** | 单次 300s 上限 + 预算 360s + 每次尝试前查预算 + 预算耗尽日志；判别力已验（§4.8.2）。**不测**：真实 systemd kill 路径（云上只读、本次不动 unit） |
| 10 | **生成目录残留**：meta.json 与硬断言的先后 | 审查 M3 | **测** | `meta.json` 挪到全部生成动作之后；超限时生成目录文件数 = 0（screener + score 两表用例都锁） |

### 6.1 审查差集 10 条逐条处置（2026-10-26 收尾批）

独立审查（`/tmp/agent-report-pfscore-review.md` §9.2）在我方清单之外另推 10 条，逐条处置如下：

| # | 审查差集项 | 处置 | 落点 / 证据 |
|---|---|---|---|
| 1 | daily **600s 墙**与 `BUDGET=1800` 冲突、`npx` 无单调用超时 | **本批修（M2）**：单次 300s + 预算 360s + 每次尝试前查 + 计数查询也包超时 | `scripts/lib/d1_execute.sh:42-66,79-103`；`sync_fund_screener_to_d1.sh:88-90,561-565,577`；`sync_fund_score_to_d1.sh:60-62,329-333,345`；用例 §4.8.2 |
| 2 | 调度时点前提错误（每天 16:00，不是周日 03:17）+ 生产实测无并发读探针 | **归主控/用户（H2）**，本批不改代码；第 8 节生产实测补一条「import 期间并发 GET」观察 | 第 8 节第 4 项 |
| 3 | 打桩只有次数、无 **argv 断言** | **本批修（M1）**：假 npx 记录完整 argv（`0x1F` 分隔），断言 7 个参数与顺序、含空格路径仍是单参数、`--file=` 值等于生成目录文件 | `scripts/tests/test_pfscore_d1_single_import_20261026.py`：`_fake_npx` / `_argv_calls` / `test_execute_argv_shape_and_file_flag_with_spaces`；判别力 §4.8.1 |
| 4 | 「一个字节都不写盘」与 **rc=3** 表述不实 | **本批修（M3）**：文档改正；并把 `meta.json` 挪到全部生成动作之后 ⇒ 现在真的零残留 | 本文 §2 第 3 条、§4.4；`screener:523-527`、`score:291-295` |
| 5 | 文档「真实库」= **本机陈旧镜像** | **本批修（M4）**：全部改「本机镜像 27,758 行 / 20260913」，并标明生产权威库 28,302 行 / 20261025 / 包体 +2% | 本文 §3 口径声明、§4.1/§4.2、§6 第 1/6 行 |
| 6 | **meta 表最后导入**（非原子失败时 meta/数据错位） | **归主控（L1）**：依赖服务端原子性结论，今晚生产实测完再定；本批不动导入顺序 | 第 8 节第 1 项（建议加查 `screener_meta`/`sync_meta`） |
| 7 | **空输入** single 抛错 vs legacy 保留旧数据 | **本批加固（L2）**：包层空行集先报错且 `DELETE` 不入队；score 脚本补 `rows=0` 守卫；实测两模式都不产出 DELETE-only 包 | §4.8.3；`d1_sql_bundle.py:76-79`、`score:180-185`（注释写清三层防线） |
| 8 | kill 残留 ~25MB 临时目录（云上已有 2 个） | **归主控（L3）**：另派清理，本批不动 EXIT trap | 本文 §9 |
| 9 | 计数校验走直接 `npx`，**不在重试内**（旧版已有，非本次引入） | **如实保留 + 本批只加超时**：`D1_VERIFY_TIMEOUT_SEC=60`；**未**纳入重试（避免扩大改动面），误判风险仍在 | 本文 §9 |
| 10 | 默认 `single` 的上线顺序风险 | **归主控/用户（H1）**：代码默认值未改；文档 §5 补了「legacy 在 600s 墙下跑不完」的硬限制 | 本文 §5 |

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
   - 同时查 `screener_meta` / `sync_meta`（meta 表是**最后**导入的，非原子失败时可能「旧 meta + 新/部分数据」，L1）。
2. **真实单文件耗时与上传速率**：导一次 24~25MB 的 `full_import.sql`，记录总耗时、wrangler 输出里的上传/ingest 分段时间。
   预期 45~55 秒，悲观 ≤2 分钟；若 >5 分钟则复核方案（可能需要拆分或换直连 API）。
3. **清理与回归**：删除测试表，并确认 `fund_screener` / `fund_score` 两表行数**未被触碰**（跑前跑后各记一次 `COUNT(*)`）。
   实测全程避开盘中与盘后任务时点（§14），23:00 后窗口执行。
4. **并发读观察（审查 H2 补）**：import 期间并发 `GET /api/fund_screener`、`/api/fund_score` 各记几次响应
   （状态码 + 耗时 + 是否降级到 Top100），作为「16:00 活跃时段单文件导入是否可接受」的依据；
   单表 >2 分钟则不能按「可接受」签。

## 9. 已知风险 / 待确认

- **单文件 25MB 走 `--file` 的实际上限与耗时**由生产实测第 2 项确认（本机只能确认文件生成与本地载入正确）。
- **服务端事务是否真回滚**由第 1 项确认；如果 D1 import 不是全事务，本改造的「失败后旧全量保留」预期不成立，需改影子表（已在第 1 项写明降级路径）。
- `full_import.sql` 生成在临时目录（`TMPDIR`/`/tmp`），25MB 级；生产磁盘余量需正常（与此前 347 个文件总量相同量级）。
- 若 `max_stmt_bytes` 逼近 90,000 硬上限（本机镜像当前 59,999/60,000；生产 +2% 体积后仍在软上限内，硬上限余量充足），
  说明某只基金长文本在变长 —— 日志会打印该值，便于提前发现。

**已知残留（本次明确不改，归主控排期）**

- **L1 meta 表最后导入**：`screener_meta` / `sync_meta` 在数据语句之后，非原子失败时可能「旧 meta + 新/部分数据」。
  依赖第 8 节第 1 项原子性结论再定（改导入顺序或影子表）。
- **L3 kill 残留**：`trap 'rm -rf "$GEN_DIR"' EXIT` 在 systemd SIGKILL 路径跑不到，云上已有 2 个 ~25MB 临时目录
  （10-22、10-23 各一个）；磁盘剩 14G，不紧急。本次不动 trap。
- **计数校验不在重试内**（旧版已有，非本次引入）：`screener:577` / `score:344` 的 `COUNT(*)` 是独立 `npx`，
  网络抖动会把「数据已导成功」误判为失败。本批只给它加了 60s 超时，**未**纳入重试。
- **H1 默认 single = merge 即切生产 / legacy 回退受 600s 墙限制**：代码默认值未改（上线决策归主控/用户），
  回退限制见 §5 末条。
- **H2 真实同步时点是每天 16:00**（`pf_score_daily.sh`），不是周日 03:17；生产实测在 23:00 空载，
  不覆盖 16:00 活跃时段 —— 第 8 节第 4 项补并发读观察。