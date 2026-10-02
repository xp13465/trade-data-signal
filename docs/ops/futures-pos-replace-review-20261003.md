# futures_position REPLACE→UPSERT 修复 Review 报告(2026-10-03)

- reviewer: 独立复验,未参与实施;只读审查,未改任何业务代码
- 审查对象: 分支 `feat/futures-pos-replace-20261003` @ `90fc909df`(base `11073b291`,未合 main)
- 方法: 全 diff 核对 + 独立自测 14 项(import **feat worktree 内修复代码** + `__file__` 断言防主 checkout 老代码) + 全库 44 处 REPLACE 独立计数 + 6 处「安全」抽样复核 + compute_net_position 调用方全库 grep + 云上 sqlite 版本只读独立复核

## 总体结论: **PASS(可 merge)**

---

## ① 改动正确性逐项判定 — PASS(6 项全过)

| 判定项 | 结果 | 证据 |
|---|---|---|
| 冲突键 `(date,variety,role)` 是否真为唯一约束 | ✅ 是 | `app/db.py:96-110` `CREATE TABLE IF NOT EXISTS futures_position (... PRIMARY KEY (date, variety, role))`,与 ON CONFLICT 目标逐字一致 |
| SET 只更新 net_ratio+source,其余列保留旧值 | ✅ 是 | 独立自测 P2/M4:采集器写入的 total_long/total_short/net_position/long_chg/short_chg/contract_count 六列逐列保留,net_ratio/source 正常更新 |
| 反向风险:新行插入语义是否保留 | ✅ 在 | 独立自测 M1:无冲突的新 (date,variety,role) → 正常 INSERT(net_ratio+source 写入,其余列 NULL=新行预期) |
| 冲突键不同组合 | ✅ 正确 | 独立自测 M2:变 variety / 变 role → 插新行不冲突;三键全同 → 走 UPDATE;裸 INSERT 重复三键仍报 IntegrityError(PK 约束未破坏) |
| 连续两次调用(幂等) | ✅ 幂等 | 独立自测 P2 末段:二次调用 n=1,六列仍保留,net_ratio 不变 |
| SQL 语法可执行 | ✅ | 独立自测 P2 跑真实 `compute_net_position()` 成功写回;采集器 `app/collector/futures_position.py:24-40` `_upsert` 已在生产用**同一语法** `ON CONFLICT(date, variety, role) DO UPDATE SET` 每日跑 |

**病灶复现确认**:独立自测 P1 用旧 `INSERT OR REPLACE` 只写 net_ratio+source → 六列全部清成 NULL(实测 `(None,None,None,None,None,None)`),证明 implementer 对根因的描述属实,修复方向正确。

## ② §23.2 三分类清单抽样(6 处「安全」独立复核)— PASS

审计文档称 31 处安全。抽样复核 6 处(含任务点名要特别核的 public_fund.py:911 与 daily_metric),判定全部成立:

| 位置 | 表 | 列覆盖 | 独立复核结论 |
|---|---|---|---|
| `app/collector/public_fund.py:911` fetch_daily_nav | `fund_daily_nav` | 7/7 | schema 7 列(PK date,fund_code)全被写入 → REPLACE=整行权威覆盖,安全;**保留不动成立**。历史回填写入者(:1131)已先转 UPSERT(9f536169a 先例),不会与日更 REPLACE 冲突 |
| `scripts/lhb_history_backfill.py:58/81` | `daily_metric` | 5/5 | schema 5 列(date,metric_id,value,source,updated_at)全被写入;全项目 daily_metric 写入者(30+ 处)均同 5 列形状(独立 grep 佐证),无部分列写入 → 安全 |
| `app/compute/futures_position.py:232` | `futures_accuracy` | 11/11 | schema 11 列全写入 → 安全 |
| `app/compute/futures_position.py:466` | `futures_ih_detail_acc` | 12/12 | schema 12 列全写入 → 安全 |
| `app/compute/signals.py:1449` | `signal_daily` | 4/4 | schema 4 列全写入(先 DELETE 全表再 REPLACE 全量重算,唯一权威写入者)→ 安全 |
| `app/collector/etf_national_team.py:929` | `national_team_holders` | 9/9 | schema 9 列全写入 → 安全 |

**独立计数核对**:`grep -rn "INSERT OR REPLACE" --include=*.py app/ scripts/` = 44 处,与审计文档「44 处」一致。`同类需修 1 处(已修)`判定成立——点名处是唯一「部分列+REPLACE+另一写入者写全列」的真隐患,其余要么写全列、要么唯一权威写入者、要么自测临时库/注释。**无被误判为安全的项**。

## ③ 调用方影响面 — PASS(生产链路零影响)

`compute_net_position` 全库唯一调用方 = **CLI 子命令**(`app/compute/futures_position.py:544` `n = compute_net_position()`,`python -m app.compute.futures_position net`)。
- **不在** runner.py 每日流水线(该步只 collect_daily + compute_accuracy,已读 runner.py L556-571 确认);
- **不在** 云上 20:05 `futures_backfill.sh`(云上 systemctl 确认 `trade-futures-backfill.timer` 在位;脚本内只 collect_daily + compute_accuracy);
- **不在** 任何 scripts/*.py 或 *.sh。

故:该函数是**手动防御性工具**,本次改 UPSERT 只影响「人手动跑 net 时不再踩空列」,不会改变任何生产数据链路行为。调用方预期无破坏。

## ④ 云上版本独立复核 — PASS

云上只读 `ssh ubuntu@122.51.111.173 "python3 -c 'import sqlite3;print(sqlite3.sqlite_version)'"` 独立输出 **`3.37.2`**。
- ON CONFLICT UPSERT 需 sqlite ≥ **3.24.0**(2018-06 起),3.37.2 满足;
- 且采集器 `_upsert` 的同一 ON CONFLICT 语法已在生产每日跑,为云上兼容性提供运行时实证。
- 全程只读,未写云上任何数据。

## ⑤ 观察项(口径差异)核实 + 建议

**是真差异(两边代码核实)**:
- `compute_net_position`(`app/compute/futures_position.py:499-503`):综合值 = 四品种 net_ratio 的简单平均(`pos_df[available].mean(axis=1)`),等权;
- 采集器 `_upsert`(`app/collector/futures_position.py:81-84`):综合 net_ratio = `(Σ总多 − Σ总空)/(Σ总多 + Σ总空)`,按手数加权。
- 数学上两式仅在四品种分母相等或比率全相等时同值,一般不等。

**实际后果**:因本函数不在任何流水线,仅人手动跑 `net` 时,综合行 net_ratio 会被覆盖成「等权平均」,而 net_position(手数)仍是采集器加权口径 → 同一行两口径并存;但方向 sign(accuracy 只用符号)几乎不翻转,展示曲线值略有偏移。**不会再把列写歪**(本次修复已消除 NULL 踩踏,列本身保留)。

**建议:另开低优先任务,不阻塞本次 merge**。依据:①实现上采集器 collect_daily 已自算并写全综合行,`compute_net_position` 的「防御性重算」实质冗余;②口径差异为 pre-existing(本次 diff 未引入),§23.7 冻结契约要求不顺手改;③若后续保留该函数,应改为与采集器同口径或直接弃用,避免人手动跑后展示值漂移。

## ⑥ 自测实测输出(独立跑,非照抄)

- 本机 sqlite:**3.38.4**(`python3 -c 'import sqlite3;print(sqlite3.sqlite_version)'`)
- 独立脚本 14 项 **ALL PASS**(P0 `__file__` 断言 + P1 病灶复现 + P2 真实函数六列保留/幂等 + M1 新行插入 + M2 冲突键组合/PK 约束 + M4 混合场景),关键输出:
  - `fp.__file__=/Users/linhuichen/code/trade/.claude/worktrees/agent-a11cb4fb71521c66c/app/compute/futures_position.py` 落 feat worktree 内(非主 checkout 老代码)
  - P1:旧 REPLACE 后六列 = `(None,None,None,None,None,None)`(病灶复现)
  - P2:修复后六列 = `(100.0, 90.0, 10.0, 5.0, -3.0, 200)` 全保留,net_ratio=0.055(四品种均值),二次调用幂等
  - M1:新行 net_ratio=0.05/source=computed 正常插入
  - M2:变一列=新行(共 3 行),三键全同=更新,裸 INSERT 重复三键报 IntegrityError
  - M4:有采集行日期六列保留+net_ratio=0.065;无综合行日期新行插入正常(net_ratio=0.025)
- implementer 自测脚本(8 项)亦独立重跑通过,结果一致。

## ⑦ §21 公示判断 — PASS(不命中)

本次 diff 为纯 SQL 写入语义修复(REPLACE→UPSERT),**不改任何评分/权重/分段函数/匹配规则/算法口径**,未动 track_score/跟踪分/TE/R²/IR 等公示文案所指对象 → §21 触发词不命中,不需改 purpose-notes.js/app.js/lab.js。

## ⑧ 低分项(<80)已滤:3 项

1. `created_at` 在 UPSERT 后不刷新(保留采集器原值)——纯信息列语义,无消费方依赖,25 分。
2. `compute_net_position` 整体冗余(采集器已写综合)——设计层面讨论,已并入 ⑤ 建议,50 分。
3. `scripts/check_north_gap_backfill.py:377` 部分列 `INSERT INTO daily_metric VALUES (?,?,?)`——是普通 INSERT 非 REPLACE、pre-existing、不在 44 处清单,非本次改动引入,25 分。
