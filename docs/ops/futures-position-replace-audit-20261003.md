# futures_position 综合品种 REPLACE 整行覆盖隐患 修复 + 全库同类点审计(2026-10-03)

## 结论摘要
- **点名处(app/compute/futures_position.py:505)确认同类根因**：`compute_net_position` 防御性重算综合品种时，
  用 `INSERT OR REPLACE INTO futures_position (date, variety, role, net_ratio, source)` **只写 2 个业务列**，
  REPLACE=删整行重插 → 采集器(`app/collector/futures_position.py` `_upsert`)写入的
  `total_long/total_short/net_position/long_chg/short_chg/contract_count` 被清成 NULL。
  已改 `ON CONFLICT(date, variety, role) DO UPDATE SET net_ratio=excluded.net_ratio, source=excluded.source`，
  只更新本次真正取到的列，其余列保留旧值（与先例 `9f536169a` 修法同型）。
- **全库 44 处 INSERT OR REPLACE（含注释）逐点三分类**：同类需修 1 处（即点名处，已修）；
  确认安全 31 处（写全列或唯一权威写入者或自测临时库）；纯注释/已转 UPSERT 说明 12 处（无代码）。
- **自测 8 项 PASS**：Part A 复现旧 REPLACE 把 6 列清成 NULL；Part B 用修复后真实
  `compute_net_position()` 跑，6 列逐列保留、net_ratio/source 正常更新。`__file__` 断言模块落本 worktree 内。
- **云上只读确认**：云上 sqlite 3.37.2（>=3.24 支持 ON CONFLICT）；未写云上任何数据。

## 一、点名处根因（附行号+代码）

文件 `app/compute/futures_position.py`，函数 `compute_net_position()`，原 L505：

```python
# 原(REPLACE 部分列 → 整行覆盖)
conn.execute(
    "INSERT OR REPLACE INTO futures_position (date, variety, role, net_ratio, source) "
    "VALUES (?,?,?,?,?)",
    (date_val, "综合", role, float(net_ratio), "computed"),
)
```

`futures_position` 表 schema（app/db.py L96-110，PK=`(date, variety, role)`）共 12 列：
`date, variety, role, total_long, total_short, net_position, net_ratio,
 long_chg, short_chg, contract_count, source, created_at`。

**两个写入者写同一张表**：
1. `app/collector/futures_position.py:29` `_upsert` —— 每日采集，写全 12 列（UPSERT ON CONFLICT）。
2. `app/compute/futures_position.py:505` `compute_net_position` —— CLI 防御性重算综合品种
   （`python -m app.compute.futures_position net`），只写 `net_ratio+source` 两列。

REPLACE 语义=先 DELETE 后 INSERT，未指定的 10 列落 NULL。故只要在采集后手动跑过 `net`，
综合品种行的 `total_long/total_short/net_position/long_chg/short_chg/contract_count` 即被清零，
`acc_nav`-型踩踏（public_fund 9f536169a 事故）的同根因。

修复后 L503-510：

```python
# UPSERT 而非 INSERT OR REPLACE(2026-10-03 同类根治, 同 public_fund L1131 先例)
conn.execute(
    "INSERT INTO futures_position (date, variety, role, net_ratio, source) "
    "VALUES (?,?,?,?,?) "
    "ON CONFLICT(date, variety, role) DO UPDATE SET "
    "net_ratio=excluded.net_ratio, source=excluded.source",
    (date_val, "综合", role, float(net_ratio), "computed"),
)
```

> 观察项（不改，冻结契约 §23.7）：`compute_net_position` 用「4 品种 net_ratio 平均」作综合值，
> 采集器用「(总多-总空)/(总多+总空)」作综合 net_ratio，两者公式不同。修复只消除 NULL 踩踏，
> 不改变既有口径差异（防御性重算覆盖 net_ratio 语义保持原样），如需统一口径另行拍板。

## 二、全库同类点三分类清单（§23.2 举一反三）

grep `INSERT OR REPLACE`（`app/` `scripts/` 全域，--include=*.py，44 处含注释）。

### A. 同类需修（1 处，本次已修）
| 位置 | 表 | 判定 |
|---|---|---|
| `app/compute/futures_position.py:505` | `futures_position` | 部分列(net_ratio,source)+REPLACE，另一写入者写全列 → 会踩空其余列。**已改 UPSERT** |

### B. 确认安全（31 处：写全列 / 唯一权威写入者 / 自测临时库）
判定口径：INSERT 列出列数 = schema 全列数，且（该表唯一写入者 或 所有写入者均写全列），
REPLACE 退化为「整行权威全量覆盖」，合理保留。

| 位置 | 表 | 列覆盖 | 理由 |
|---|---|---|---|
| `app/compute/futures_position.py:232` | `futures_accuracy` | 11/11 | 唯一写入者 compute_accuracy，写全列 |
| `app/compute/futures_position.py:466` | `futures_ih_detail_acc` | 12/12 | 唯一写入者 record_ih_detail_acc，写全列 |
| `app/compute/signals.py:1449` | `signal_daily` | 4/4 | 唯一写入者，写全列 |
| `app/collector/etf_national_team.py:929` | `national_team_holders` | 9/9 | 唯一写入者，写全列 |
| `app/collector/etf_national_team.py:1104/1136` | `etf_signal` | 7/7 | 唯一写入者，写全列 |
| `app/collector/intraday_snapshot.py:1701` | `intraday_amount_history` | 5/5 | 唯一写入者，写全列 |
| `app/collector/intraday_snapshot.py:2005/2011` | `score_daily` | 7/7 | 全项目 5 个写入者(cross/fear_greed/sentiment/export_alert/intraday)均写全列 |
| `scripts/export_alert.py:147` | `score_daily` | 7/7 | 同上 |
| `scripts/lhb_history_backfill.py:58/81` | `daily_metric` | 5/5 | 全项目 30+ 写入者均写全列(date,metric_id,value,source,updated_at) |
| `scripts/check_ds_resilience.py:191` | `mootdx_daily_raw` | 10/10 | 自测临时库；生产侧 mootdx_daily.py:422 也写全列 |
| `scripts/check_data_gap_alerts.py:2142` | `fund_daily_nav` | 7/7 | `_mk_fundnav` 自测临时库(非生产) |
| `app/collector/public_fund.py:681` | `fund_position_history` | 10/10 | 唯一写入者，写全列 |
| `app/collector/public_fund.py:726` | `fund_holding_stock` | 6/6 | 唯一写入者，写全列 |
| `app/collector/public_fund.py:858` | `fund_hold_structure` | 6/6 | 唯一写入者，写全列 |
| `app/collector/public_fund.py:911` | `fund_daily_nav` | 7/7 | fetch_daily_nav 每日权威全量覆盖（任务指定已知安全，勿改） |
| `app/collector/public_fund.py:991` | `fund_estimation_nav` | 10/10 | 唯一写入者，写全列 |
| `app/collector/public_fund.py:1064` | `fund_index_daily` | 4/4 | 唯一写入者，写全列 |
| `app/collector/public_fund.py:1193` | `fund_scale_change` | 7/7 | 唯一写入者，写全列 |
| `app/collector/public_fund.py:1242` | `fund_asset_alloc` | 6/6 | 唯一写入者，写全列 |
| `app/collector/public_fund.py:1284` | `fund_industry_alloc` | 5/5 | 唯一写入者，写全列 |
| `app/collector/public_fund.py:1525` | `fund_portfolio_hold` | 8/8 | 唯一写入者，写全列 |
| `app/collector/public_fund.py:1798` | `fund_performance` | 15/15 | 唯一写入者，写全列 |
| `app/collector/public_fund.py:1840` | `fund_rating` | 8/8 | 唯一写入者，写全列 |
| `app/collector/public_fund.py:1884` | `fund_purchase_status` | 7/7 | 唯一写入者，写全列 |
| `app/collector/public_fund.py:2406` | `fund_fee_detail` | 6/6 | 唯一写入者，写全列 |
| `app/collector/public_fund.py:2673` | `fund_risk_indicator` | 14/14 | 唯一写入者，写全列 |
| `app/collector/public_fund.py:3632` | `fund_score` | 33/33 | 唯一写入者，写全列 |
| `app/collector/public_fund.py:3997` | `fund_metrics` | 6/6 | 唯一写入者，写全列 |

### C. 纯注释 / 已转 UPSERT 说明（12 处，无代码，不涉及）
`app/db.py:130`（注释）、`app/collector/public_fund.py:614/1131/2064`（UPSERT 已转说明）、
`app/compute/futures_position.py:449`（注释）、`app/compute/signals.py:1445`（注释）、
`scripts/check_data_gap_alerts.py:696/757/782`（事故背景注释）、`scripts/lhb_history_backfill.py:14`（注释）、
`scripts/backfill_futures_acc.py:5`、`scripts/backfill_futures_acc_7_15.py:4`（注释）。

### 疑似待判
**无**。逐点核对后无「疑似需判」项——所有 REPLACE 要么写全列，要么唯一写入者，要么是自测临时库/注释。

## 三、修的点逐个「修前/修后 + 自测输出」

唯一修正点 `app/compute/futures_position.py` `compute_net_position`（见 §一 代码）。

自测脚本：`docs/ops/test_futures_position_replace_selfcheck.py`（随本报告一并 commit），
本机 sqlite **3.38.4** 实测输出：

```
PASS[1] fp.__file__=.../app/compute/futures_position.py 落在 worktree .../agent-a11cb4fb71521c66c 内
PASS[2] db.__file__=.../app/db.py 落在 worktree 内
=== Part A: 旧 INSERT OR REPLACE 行为(病灶复现) ===
PASS[3] 前置: 全列写入后 total_long=100.0
  REPLACE 后 total_long=None total_short=None net_position=None long_chg=None short_chg=None contract_count=None
PASS[4] 病灶复现: REPLACE 部分列后 六列全部被清成 NULL(保留=0)
=== Part B: 修复后 compute_net_position(UPSERT) 其他列保留 ===
PASS[5] compute_net_position 写回 1 行
PASS[6] net_ratio 被更新为综合值 0.055(mean=0.055)
  UPSERT 后 total_long=100.0 total_short=90.0 net_position=10.0 long_chg=5.0 short_chg=-3.0 contract_count=200
PASS[7] 其他列(采集器写入)在 UPSERT 后逐列保留(六列全=写入值)
PASS[8] source 被更新为 'computed'(本次真正取到的列正常更新)
ALL 8 PASS (sqlite 3.38.4)
```

## 四、云上只读验证说明
- 云上 sqlite **3.37.2**（ssh 只读 `import sqlite3; print(sqlite3.sqlite_version)` 确认）。
- `ON CONFLICT DO UPDATE` 语法要求 sqlite >= 3.24.0（2018 年），云上 3.37.2 满足；且
  采集器 `app/collector/futures_position.py` 已在生产跑同一 UPSERT 语法，兼容性由线上既有用法背书。
- 云上未做任何写操作。云上该文件所在仓库路径未在 /home 下定位到（find 未命中），
  未能对云上文件内容做逐字节 grep，如实标注；云上代码经 git 拉取随下次部署更新。
- 本次改动为纯 SQL 语义（REPLACE→UPSERT），不涉及数据产物/前端/算法公示，无需 R2/static-site 同步。

## 复现段
`WT_PATH=/Users/linhuichen/code/trade/.claude/worktrees/agent-a11cb4fb71521c66c \
/Users/linhuichen/code/trade/.venv/bin/python3 \
docs/ops/test_futures_position_replace_selfcheck.py`

（脚本自建临时 sqlite 库，不碰生产 sentiment.db；Part A 复现病灶、Part B 验修复后真实函数行为。）
