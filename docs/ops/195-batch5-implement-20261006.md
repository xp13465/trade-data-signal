# #195 批5 实施报告 —— 链内被调 / 变体 / 孤儿 16 个脚本 `resolve_repo` 迁移(收尾批)

> 日期 2026-10-06(implementer,worktree 隔离)
> 分支 `feat/195-resolve-repo-batch5-20261006`,base = main `232444342`
> 方案:`docs/ops/195-resolve-repo-plan-20261006.md` §4.5 / §3.5 / §3.6 / §4.6;批4 样本 `git diff 8a3f6b62e c7fe32b30`
> **自测全程 static-only:未执行任何仓内业务脚本**(§18 L50 硬约束,详见 §5「零外发证据」)

## 0. 结论速览

- **16/16 文件迁移完成**,diff 仅动 header(`REPO`/`GIT_REPO` 默认值行 → `source lib` + `resolve_repo`),无夹带逻辑/格式改动。
- **静态断言 16/16 PASS**(每文件恰 1 行 source + 恰 1 行 resolve_repo + 代码行零 `:-?/Users/linhuichen`);**`bash -n` 17/17 PASS**(16 脚本 + lib)。
- **ratchet PASS**:`pattern 命中 0 / 白名单外 0 / MIGRATED 58 / PASS 58 / R3 残留 0`;`--selftest` PASS(负对照 PASS + 变异 FAIL)。
- **export 集合 16/16 逐行不变**(实测批5 仅 1 个 export 脚本)。
- **STATICDATA_REPO 两机逐字节 MATCH**(mac / 云上 env 空态新值 == 旧默认/旧兜底结果)。
- **T1-T7 = 11/11 PASS**;**pytest 全量 234 passed / 1 skipped**;**本机真实布局 probe 16/16**(含「harness 抓漂移」自证)。
- **零真实外发 / 零生产写入**(证据见 §5)。
- 上报 8 项(§6),给 §0 待验 5 项(§7)。**无阻塞项**。

---

## 1. 逐文件 diff 摘要(16 个)

统一改法(§3.5 模板,批1 定稿的带兜底版):

```
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/repo_paths.sh" || { echo "FATAL: repo_paths.sh missing" >&2; exit 2; }
resolve_repo "${BASH_SOURCE[0]}"
```

| # | 文件 | 原 header 行 | 迁移后 | 备注 |
|---|---|---|---|---|
| 1 | `backfill_indices.sh` | `REPO="${REPO:-…trade-data}"` (L12) | source+resolve | 链内被调(backfill_metrics) |
| 2 | `build_echarts.sh` | 同上 (L17) | source+resolve | 孤儿/手动 |
| 3 | `check_signals.sh` | 同上 (L16) | source+resolve | **邮件链**,仅动此行,逻辑/键集零改 |
| 4 | `collect.sh` | 同上 (L17) | source+resolve | 链内被调(update_all_serial) |
| 5 | `fix_turnover_partial_20260814.sh` | 同上 (L25) | source+resolve | 一次性/手动 |
| 6 | `fund_nav_upload_async.sh` | `REPO`+`GIT_REPO` (L22-23) | source+resolve | 链内被调(r2_upload_async/update_all) |
| 7 | `migrate_large_json_out_of_git.sh` | `REPO`+`GIT_REPO`+`STATICDATA_REPO` (L17-19) | source+resolve + **STATICDATA 去字面量** | 见 §3 |
| 8 | `pipeline.sh` | `REPO` (L20) | source+resolve | 链内被调(update_all) |
| 9 | `push_schedule_stats.sh` | `REPO`+`GIT_REPO`+`export` (L31-33) | source+resolve + **保留原 export 行** | 唯一 export 脚本 |
| 10 | `r2_upload_async.sh` | `REPO`+`GIT_REPO` (L29-30) | source+resolve | 链内被调(deploy) |
| 11 | `stage0_full_manual.sh` | `REPO` (L25,带尾注释) | source+resolve(尾注释随行删) | 手动 |
| 12 | `staticdata_backup_async.sh` | `REPO`+`GIT_REPO`+`STATICDATA_REPO` (L46-48) | source+resolve + **STATICDATA 去字面量** | 见 §3 |
| 13 | `staticdata_sync.sh` | `REPO`+`GIT_REPO`+`STATICDATA_REPO` (L30-32) | source+resolve + **STATICDATA 去字面量** | 见 §3 |
| 14 | `sync_fund_score_to_d1.sh` | `REPO` (L19) | source+resolve | 链内被调(pf_score_daily/weekly) |
| 15 | `update_all_serial.sh` | `REPO` (L16) | source+resolve | 手动串行链 |
| 16 | `verify_backup.sh` | `REPO` (L26) | source+resolve | 手动/备份演练 |

**diff 面机检**:`git diff -- scripts/*.sh` 的全部 `+/-` 行仅三类 —— ①`source … lib/repo_paths.sh` 行 ②`resolve_repo` 行 ③`STATICDATA_REPO` 去字面量行(**`export REPO GIT_REPO` 行在 `push_schedule_stats.sh` 中作为上下文未变**)。无任何越界改动。
`git diff --stat`:17 files changed, **42 insertions(+), 31 deletions(-)**(含 ratchet 白名单搬运)。

---

## 2. export 对照表(以代码现状为准,**不抄方案 §2.2**)

机检法:对每文件比对 base(`git show 232444342:`)与工作区的 `^\s*export (REPO|GIT_REPO|TRADE_DIR|STATICDATA_REPO)\b` 代码行(排除注释)。

| 文件 | 原 export | 迁移后 export | 判定 |
|---|---|---|---|
| `push_schedule_stats.sh` | `export REPO GIT_REPO   # #75 …` (L33) | `export REPO GIT_REPO   # #75 …` (L34) | **不变**(保留原 export 语义,置于 resolve 之后) |
| 其余 15 个 | 无 | 无 | 不变 |

**`EXPORT-SET UNCHANGED = 16/16`。**

> ⚠️ 方案 §3.6 列出的「6 个原 export 脚本(check_data_gap_alerts / check_r2_consistency / nextday_gap_check / nextday_plan / s06_snapshot / turnover_backfill)」中**不含 `push_schedule_stats.sh`**;**批5 实测 export 脚本恰 1 个且就是它** ⇒ 该清单同样失准(与批4 审查「方案 export 列对不上」同病)。本批以**代码现状**为准。

---

## 3. STATICDATA_REPO 两机逐字节对照 + 取舍理由(本批唯一设计取舍)

### 3.1 现状与改法

3 个文件均有(改前):

```bash
STATICDATA_REPO="${STATICDATA_REPO:-/Users/linhuichen/code/trade-data-signal-staticdata}"
…
if [ ! -d "$STATICDATA_REPO/.git" ] && [ -n "${GIT_REPO:-}" ] && [ -d "${GIT_REPO}-staticdata/.git" ]; then
  STATICDATA_REPO="${GIT_REPO}-staticdata"     # 云上单仓兜底分支(未改动,仍在位)
fi
```

改后(去 mac 字面量,置于 `resolve_repo` 之后、`$GIT_REPO` 已就位处):

```bash
STATICDATA_REPO="${STATICDATA_REPO:-$(dirname "$GIT_REPO")/trade-data-signal-staticdata}"
```

### 3.2 两机逐字节对照(env 空态)

| 机器 | `GIT_REPO` | 改后新默认值 | 改前取值(env 空) | 判定 |
|---|---|---|---|---|
| mac | `/Users/linhuichen/code/trade` | `/Users/linhuichen/code/trade-data-signal-staticdata` | 旧默认 = 同串(命中即用) | **MATCH** |
| 云上 | `/home/ubuntu/code/trade-data-signal` | `/home/ubuntu/code/trade-data-signal-staticdata` | 旧默认(mac 串)不存在 → **旧兜底** `${GIT_REPO}-staticdata` = 同串 | **MATCH** |

- mac 实测:`ls -d /Users/linhuichen/code/trade-data-signal-staticdata/.git` 存在 ⇒ 新默认直接命中真目录。
- 云上实测(只读 ssh):`/home/ubuntu/code/trade-data-signal-staticdata/.git` 存在 ⇒ 新默认直接命中。
- 表达式 eval 机检(只 eval 表达式,不 source 脚本):两机均 `MATCH`。
- **注意 mac 上 `GIT_REPO` 尾名是 `trade` 而非 `trade-data-signal`** ⇒ 写成 `${GIT_REPO}-staticdata` 在 mac 会得到不存在的 `/Users/linhuichen/code/trade-staticdata`(主控已排除的错解;本批未采用)。故只能用 `dirname`。

### 3.3 兜底分支语义是否被破坏

- 兜底行 `STATICDATA_REPO="${GIT_REPO}-staticdata"`(staticdata_sync.sh L37 / staticdata_backup_async.sh L58 / migrate_large_json_out_of_git.sh L25)**一字未改,仍在位**(机检 3/3)。
- **可达性说明**:新默认值在两机标准布局下**已直接指向真目录**(含 `.git`),故兜底分支在标准布局下**不再被触发**(退化为冗余安全网);仅在「非标准 GIT_REPO(既非 mac 也非云上标准布局)且 `${GIT_REPO}-staticdata` 恰存在」这种非常规形态下仍可兜住。
- mac 边界诚实标注:若 mac 的默认目录**没有** `.git`,旧逻辑兜底会得到 `/Users/linhuichen/code/trade-staticdata`(**与默认不同名**);新逻辑同样会走到同一兜底 => 行为一致。**语义未破坏。**
- 三文件内 `$STATICDATA_REPO` 的后续用法(rsync / git ls-files / `.git` 探测)**未受影响**(仅 header 默认值行变化,变量名与用处不变)。

### 3.4 取舍理由

- 目标:去掉 mac 字面量(R3 要求 MIGRATED 文件代码行零 `:-?/Users/linhuichen`),同时**两机取值逐字节不变**、**不动 lib**(`resolve_staticdata_repo` 在 lib 中**不存在**,见 §6 上报①)。
- `$(dirname "$GIT_REPO")/trade-data-signal-staticdata` 是唯一同时满足「两机一致 + 不依赖 mac 路径 + 无需 lib 新增符号」的形式。

---

## 4. ratchet 白名单搬运 + 防空转

- 16 个从 `PENDING_BASELINE` **全部移出**(该集合现为**空集**),移入 `MIGRATED` 并加 `# 批5(链内被调 / 变体 / 孤儿 16 个, 收尾批)` 分组;**搬运恰 16 个**。
- `PENDING_BASELINE = set()`;注释同步更新为「批2 删 10,批3 删 9,批4 删 21,批5 删 16 ⇒ 余 0,全仓 57 个 mac 字面量脚本已全部迁移」。

**ratchet 实跑输出**:

```
[ratchet] 扫描 scripts/**/*.sh:pattern 命中 0 个(白名单外 0)
[ratchet] MIGRATED 58 个,PASS 58;R3 残留命中=0
[ratchet] R3 正则健康自检: ':-?/Users/linhuichen' 命中标准样本 OK
[ratchet] RESULT=PASS
```

**`--selftest`**:`PASS 负对照(未变异→RESULT=PASS)` + `PASS 变异样本(第 57 行代码→RESULT=FAIL,R3 残留命中=1)`;`[ratchet-selftest] PASS`。

### 4.1 「pattern 命中 = 0」后 R1/R2/R3 的非空转证据

| 规则 | 全迁完状态下的判别力 | 证据 |
|---|---|---|
| R1(回潮) | **仍非空转**:pattern 命中 0 只是「无现存病灶」;若**新脚本**重写 mac 默认值 → `pattern_files - known` 非空 → FAIL | **实测**:在快照树放 `scripts/zz_newscript_backslider.sh`(`REPO="${REPO:-/Users/linhuichen/…}"`)→ ratchet `pattern 命中 1 个(白名单外 1)` + `FAIL R1 回潮` + `RESULT=FAIL(1)`(已复原) |
| R2(迁移面) | **恒定非空转**:每次运行对 58 个 MIGRATED 文件逐一断言「存在 + source 恰 1 + resolve 恰 1」 | 输出 `MIGRATED 58 个,PASS 58` |
| R3(残留面) | 有**恒在自检**(`_VACUITY_PROBE` 每次运行先反查标准病灶样本)+ `--selftest` 变异 | 输出「R3 正则健康自检 … OK」;selftest 变异 FAIL 已见效 |

**设计边界(如实上报)**:`PENDING_BASELINE` 变空后,R2 的 `tightened` 提示项(「基线内已不再命中」)恒为空 —— 这是**收尾批的自然终态**,不是失控,已按派单要求**未自改判据**。

---

## 5. 自测结果 + 零外发证据

### 5.1 静态自测(static-only,全部合法手段)

| 项 | 结果 |
|---|---|
| 静态断言(1 source / 1 resolve / 0 mac 残留) | **16/16 PASS** |
| `bash -n`(16 脚本 + `lib/repo_paths.sh`) | **17/17 PASS** |
| `bash scripts/tests/test_resolve_repo.sh`(快照树) | **T1-T7 汇总 PASS=11 FAIL=0** |
| `pytest scripts/tests`(快照树 `/tmp/impl195b5-snap`,先证桩生效) | **234 passed, 1 skipped**(RC=0) |
| 本机真实布局 probe(只 source lib) | [1] env 空推导==旧 mac 默认 **PASS**;[2] harness 抓漂移自证 **PASS**;[3] 16 文件真实 caller 路径 **16/16 PASS** |
| export 集合 before/after | **16/16 SAME** |
| STATICDATA_REPO 表达式两机 eval | **mac MATCH / 云上 MATCH** |
| 兜底分支仍在位 | **3/3** |
| ratchet 主检 + `--selftest` | **PASS / PASS** |

**快照树「先证桩生效」**:测试在 `/tmp/impl195b5-snap`(仓库快照,排除 `.git/docs/static-site/.claude`;后补 `docs/deploy` 供 `test_196` 读云上快照)运行,**不作用于 worktree**;首跑出 4 个 FAIL 全因快照缺 `docs/deploy/systemd-units-cloud-snapshot.txt`(环境缺件,非代码问题),补齐后 234 passed / 1 skipped。

### 5.2 零外发 / 零生产写入证据

1. **全程未执行任何仓内业务脚本**:所用命令仅 `grep/ls/stat/rsync/git diff|status|show/python3(自写独立脚本)/bash -n/ratchet/pytest(快照树)`;resolve 探针**只 source `lib/repo_paths.sh`**(经 python 子进程传 caller 路径),**未 source/exec 任何业务脚本主体**。
2. **worktree `data/` 无会话期写入**:`find data -mmin -40 -type f` 命中文件的 mtime 全为 `2026-10-06 03:30:01`(= worktree 创建时刻,与 `lib/repo_paths.sh` 同刻),当前时刻 03:34:47 ⇒ **会话期内零写入**。
3. **生产 staticdata 仓库无写入**:`find /Users/linhuichen/code/trade-data-signal-staticdata -mmin -40 -type f`(排 `.git/`)**空**。
4. **未启停任何 unit**;云上**只读** ssh(`ls`/`grep`/`git rev-parse`,无写)。
5. **无邮件/飞书/告警/R2 动作**:本批未跑 `check_signals.sh` 等任何发送链脚本;测试套件内建零网络(conftest 桩 + tmpdir)。

### 5.3 云上只读抽样(3+ unit)

| unit | `ExecStart` | `Environment` | 定时 | 判定 |
|---|---|---|---|---|
| `trade-update-all.service` | `update_all.sh`(→ 调 `collect.sh` / `check_signals.sh`) | `REPO=/home/ubuntu/code/trade-data` / `GIT_REPO=/home/ubuntu/code/trade-data-signal` | `Mon..Sat 17:50` / `Sun 22:30` | env 齐全 ⇒ 迁移后 `source=env` 零改写 |
| `trade-intraday-snapshot.service` | `intraday_snapshot.sh`(→ 调 `staticdata_sync.sh` 等) | 同上 | `09:25…14:35` 多档 | 同上 |
| `trade-r2-consistency.service` | `check_r2_consistency.sh` | 同上 | `23:20` | 同上 |

- 云上**仍是 base 旧版代码**(未 pull),抽样**只核 unit 环境/触发面**,不把「云上仍旧代码」判 FAIL。
- 3 个 unit 均**未设** `STATICDATA_REPO` env ⇒ 走推导/默认路径;迁移后推导值 == 旧兜底值(§3.2)。

---

## 6. 上报项(不阻塞,交主控/拍板)

1. **方案文档 §3.6/§4.5 说 lib 定义 `resolve_staticdata_repo`,但 lib 实际只有 `resolve_repo` + `_resolve_repo_fatal`**(与派单一致)。本批**未调用不存在的函数**,改用 `dirname "$GIT_REPO"` 形式。建议订正方案 §3.6/§4.5。
2. **方案 §2.2 主表 export 列对批5 失准**(与批4 审查同病,累计第 4 次):实测批5 仅 `push_schedule_stats.sh` 一个 export 脚本;方案 §3.6 的「6 个 export 脚本」清单也不含它 ⇒ 该清单同样失准。建议以代码现状重扫后订正 §2.2/§3.6。
3. **派单期望「MIGRATED 57」,实测 58**:批1 的 `cloud_unit_patrol.sh` 不在「57 病灶」内(#194 已修、非 mac 字面量脚本),但它计入 MIGRATED ⇒ 42+16=58。**数字差异非缺陷**,已在报告标注。
4. **ratchet 全迁完设计边界**:见 §4.1 —— R1 仍非空转(实测可抓新脚本回潮)、R2 恒跑 58、R3 靠恒在自检 + selftest;`tightened` 提示恒空属自然终态。**未自改判据。**
5. **ratchet 仍未挂链**(方案 §7.2 待拍板#2):批5 后 57 个已全迁完,**建议尽快拍板挂 deploy/CI 链**,否则「回潮」只靠人跑。
6. **STATICDATA_REPO 兜底分支在全迁完布局下不再被触发**(退化为冗余安全网),语义未破坏;mac 上旧兜底值 `/Users/linhuichen/code/trade-staticdata` 与默认目录不同名,新逻辑行为一致。已在 §3.3 诚实标注。
7. **`check_signals.sh` 仅动 header 一行**,邮件链键集/逻辑零改动(§22/§23.10 不受影响);本批未执行它。
8. **§23.4 团队协作扫描**:`docs/pending-features-index.md` 中 #195 批5 = 收尾批(本批);未发现同模块在建任务冲突;ratchet 挂链决策(#201)仍在待拍板,本批**未擅自挂链**。

### 6.1 举一反三 / 同类错误面清单(§23.2 / §23.3)

- **同类错误面(同根因)**:全仓 `(REPO|GIT_REPO|TRADE_DIR|STATICDATA_REPO):-/Users/linhuichen` 脚本 —— 批1-5 累计 **57 个全迁完**,本批收尾后 `pattern 命中 = 0`(ratchet 实测)。
- **同数据源/同组件还被谁用(链内被调面)**:`update_all.sh → collect.sh / check_signals.sh / update_all_serial.sh`;`deploy.sh → r2_upload_async.sh / staticdata_sync.sh / staticdata_backup_async.sh`;`backup_db.sh → verify_backup.sh`;`pf_score_daily/weekly.sh → sync_fund_score_to_d1.sh`;`fund_nav_upload_async.sh ← update_all/r2_upload_async`。上述父脚本(批2-4 已迁)**export 语义未变**,子脚本迁移后 `source=env` 优先 ⇒ 链内传递值一致。
- **相关展示位**:本批均为 `.sh` header,**无前端/数据产物/公示文案变化**(§21/§22 N/A,无版本串/前端改动)。

---

## 7. 给 §0 的待验清单

1. **main 链**:merge 后 `git log origin/main` 含本 feat commit hash(本批无前端/数据层 ⇒ §8 三查为 ①有 ②N/A ③N/A)。
2. **云上 pull 同步后静态核**:16 文件各 `grep -c '^resolve_repo '` = 1;`grep -rn ':-?/Users/linhuichen' scripts/*.sh`(代码行)= **0**;3 个 STATICDATA 行取值为 `$(dirname "$GIT_REPO")/…`。
3. **云上自然实跑观察**:下一窗口 `trade-update-all`(17:50)`.err` 出现 `resolve_repo: REPO=/home/ubuntu/code/trade-data (source=env)`;`check_signals` 链无异常。
4. **48h 无新增 failed unit**(`systemctl --failed` 空)。
5. **ratchet 挂链拍板**(§6 上报⑤)。

---

## 8. 主控收紧项声明(§4.5 两条验收点被收紧,本批未做)

方案 §4.5 原文两条验收点**已由主控显式收紧**,本批**一律不做**:

1. 原文「本机干跑 `verify_backup`(设 REPO 不存在→rc=2 无外发)」⇒ **不做**(会执行 `verify_backup.sh` 主体)。改用 **静态 diff + 只 source lib 的探针**覆盖同一断言(「REPO 不存在 → fail-loud rc=2」已由 `test_resolve_repo.sh` T4 在 lib 层验证:T4 断言 `exit=2` + 固定日志已写)。
2. 原文「孤儿脚本本机 dry-source 一次(仅 source+打印 REPO)」⇒ **不做**(dry-source 会执行脚本主体逻辑)。改用**静态 diff + lib 探针**(§5.1 本机 probe [3]:16 文件真实 caller 路径 env 空推导 == 旧 mac 默认 16/16)。

> 依据:§18 L50(审查/测试探针一律 static-only,绝不 source/exec 业务脚本主体);harness 门控禁用「环境变量是否齐」这类可被真实形态绕过的条件。

---

## 9. 复现段(本报告每个数字的复跑命令)

```bash
# 静态断言 + bash -n(python3 /tmp/impl195b5_assert.py)
# 本机真实布局 probe(python3 /tmp/impl195b5_probe.py)
# STATICDATA 表达式两机 eval(python3 /tmp/impl195b5_staticdata.py)
# export before/after(python3 /tmp/impl195b5_export.py)
python3 scripts/check_repo_paths_ratchet.py            # → RESULT=PASS(pattern 0 / MIGRATED 58 / R3 0)
python3 scripts/check_repo_paths_ratchet.py --selftest # → [ratchet-selftest] PASS
bash scripts/tests/test_resolve_repo.sh                # → 汇总 PASS=11 FAIL=0
# 快照树(先证桩生效):rsync 仓库 → /tmp/impl195b5-snap(补 docs/deploy) → pytest
#   /Users/linhuichen/code/trade/.venv/bin/python -m pytest scripts/tests -q
#   → 234 passed, 1 skipped
# ratchet R1 非空转实证:快照树放含 mac 字面量的新脚本 → RATCHET_ROOT=/tmp/impl195b5-snap python3 …/check_repo_paths_ratchet.py → FAIL R1
```

配套脚本(python 独立脚本,不 source 任何业务脚本):`/tmp/impl195b5_assert.py`、`/tmp/impl195b5_probe.py`、`/tmp/impl195b5_staticdata.py`、`/tmp/impl195b5_export.py`(均为一次性机检器;/tmp 属临时,复现段已给等价命令)。