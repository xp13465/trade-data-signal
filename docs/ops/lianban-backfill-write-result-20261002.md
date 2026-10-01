# 连板(最高连板)历史回补 · 生产写库执行报告(2026-10-02)

## 0. 结论摘要

用户 2026-09-30 拍板「写」后,于 2026-10-02 凌晨安全窗口完成生产写库:

- **F4 逐行双向校验:ADDED=1154 / REMOVED=0 / CHANGED=0**(期望数字逐位命中)
- 下游 compute 全量重算完成,`score_daily.score_id='a_sentiment'` 在回补段有值
- 备份产物在位,回滚路径可执行(在线 backup API,无需重启服务)
- 无残留进程,DB integrity ok

## 1. 授权与范围

- 授权(用户 2026-09-30 拍板「写」):仅写云上 `/home/ubuntu/code/trade-data/data/sentiment.db` 及其配套备份文件;云上其余一切只读。
- 脚本:`app/backfill_lianban.py`(本分支最新,含 F1 翻页取满 + F7 `only_if_null` 竞态加固,commit `b83416e37`)
- 口径:只补缺口(`fill-gaps`),`ON CONFLICT ... WHERE source != 'manual'` 防覆盖手动补录;FAPI 涨停池排除 ST 后取 max(东财可比口径)
- 区间:`--start 20210901 --end 20260929`(近一个交易日),增量段 1154 个交易日

## 2. 执行步骤

### 2.1 F3 备份(SQLite 在线 backup API,WAL 安全)

```
备份产物:/home/ubuntu/code/trade-data/data/sentiment.db.bak-lianban-202610012304
```

- 用 SQLite 在线 backup API(`src.backup(dst)`),**未用裸 cp**(主库 WAL 模式,裸 cp 会拷到缺数据/撕裂)
- `PRAGMA integrity_check` = ok,src/dst rows 231097 一致
- 基线 md5 `c6e0c0a8032f4d00ccfed09de2134382` 备份前后未变

### 2.2 写库(只补缺口,单事务)

```
执行:PID 3329606,python -m app.backfill_lianban --write --start 20210901 --end 20260929 --db /home/ubuntu/code/trade-data/data/sentiment.db
```

- 单事务写入(F8):中途 Ctrl-C/SIGKILL = 0 行落库
- 汇总打印:计划写入 1154 天

### 2.3 F4 逐行双向校验

```
期望:added=1154 / removed=0 / changed=0
实测:lianban_days=1231,manual_rows=0
source 分布:akshare=25 / fapi=1154 / intraday=52
gap_null=0,gap_cov=1154,whole_null=0
```

- 双向 EXCEPT:`expected_inc=1154 / actual=1154 / missing=0 / extra=0`
- 备份 vs 当前逐行对比:**ADDED=1154 / REMOVED=0 / CHANGED=0**,重叠段 **77** 天 value diff=0
- 数字对不上会立即停下上报,本轮数字与期望逐位命中

> **数字订正(2026-10-02,独立核验 PASS 后)**:初稿「重叠 76 天」的 76 = 脚本 `_existing_map`(`app/backfill_lianban.py`)用 `BETWEEN start AND end` 在 `[20210901, 20260929]` 区间内数出的重叠数,**20260930 那天被 `--end 20260929` 挡在区间外** → 77−1=76。tester 独立核验以**整库行数**为准:备份库(回补前)`a_width_max_lianban` 实有 **77 行**(20260612~20260930,akshare 25 + intraday 52),且 1231 − 1154 = 77,两路自洽。**正确数 = 77**,旧数 76 保留于此可反查。教训:重叠/增量数字必须直接取自脚本输出或整库实测,不以区间截断口径代整库口径。

### 2.4 下游 compute 全量重算

- 先备份:`/home/ubuntu/code/trade-data/data/score_daily.bak-lianban-202610020002.db`(38554 行,integrity ok)
- 再全量 compute(入口 `app/compute/runner.py` run()):PID 3337402,全链路完成 —— 情绪分 2602 天 / 买卖点 71402 个 / 跨市场 / 派生公式 / AD Line / 量比 / 位置感 / 恐贪指数 / 买卖点 stats / 新高新低 / 均线排列 / 板块轮动
- 验证:`sentiment.py` 消费 `daily_metric.metric_id='a_width_max_lianban'`(权重 0.15),`score_daily.score_id='a_sentiment'` 在回补段(如 20210915)有值

## 3. 最终状态

| 项 | 值 |
|---|---|
| daily_metric 总行数 | 232251 |
| `daily_metric.metric_id='a_width_max_lianban'` 行数 | 1231(20210901~20260930) |
| fapi 写入行 | 1154 |
| integrity | ok |
| 残留进程 | 无 |

## 4. 回滚路径

恢复命令 = SQLite 在线 backup API(`src.backup(dst)`,与备份同款):

```python
import sqlite3
src = sqlite3.connect("<备份库路径>")   # 如 sentiment.db.bak-lianban-202610012304
dst = sqlite3.connect("<生产库路径>")   # /home/ubuntu/code/trade-data/data/sentiment.db
src.backup(dst)
dst.close(); src.close()
```

- **先清理当前库 `-wal`/`-shm` 文件**(确认无写入进程后再清;恢复前 `PRAGMA integrity_check` 验备份完好)
- 恢复 score_daily 同款(`score_daily.bak-lianban-202610020002.db`)
- **无需重启任何服务**(DB 层恢复,服务按需自动重读)

## 5. 复现段

- dry-run 对账(不写库):

```bash
python -m app.backfill_lianban --dry-run --start 20210901 --end 20260929 --db <db> --out <json>
```

- F4 双向 EXCEPT(校验 added/removed/changed):

```sql
-- 期望增量(备份缺失而当前有)
SELECT date FROM current_lianban EXCEPT SELECT date FROM backup_lianban;   -- 应 1154 行
-- 期望删除(备份有而当前无)
SELECT date FROM backup_lianban EXCEPT SELECT date FROM current_lianban;   -- 应 0 行
-- 变更(两边都有但 value 不等)
SELECT a.date FROM backup a JOIN current b USING(date) WHERE abs(a.value-b.value)>1e-9;  -- 应 0 行
```

## 6. 配套 commit

- 本报告:本分支 commit(见 git log,分支 `worktree-agent-a7c88b498af1f88ee`)
- 脚本本体:`app/backfill_lianban.py`(F1 翻页 + F7 竞态加固,`b83416e37`)
- 台账:#134 行已更新为「✅ 已写库 + 独立核验 PASS(含数字订正:重叠 77 天)」

## 7. 独立核验(2026-10-02 主控另派 tester,云上只读重算)

tester 独立复核(自建只读查询,未复用实施侧脚本),全部实测值 PASS:

| 核验项 | tester 实测 |
|---|---|
| `daily_metric.metric_id='a_width_max_lianban'` 写库后行数 | 1231(20210901~20260930) |
| source 分布 | akshare 25 / fapi 1154 / intraday 52,manual 0 |
| 重叠天数(备份库回补前整库) | **77 天**(20260612~20260930),逐行 value diff=0 |
| ADDED / REMOVED / CHANGED | 1154 / 0 / 0 |
| 备份库 integrity | ok |
| daily_metric 总行数 | 232251 |
| 残留进程 | 无 |

证据命令(mode=ro 只读查询):

```sql
-- 写库后 lianban 全量(1231 行)
SELECT date, value, source FROM daily_metric
WHERE metric_id='a_width_max_lianban' ORDER BY date;
-- 备份库回补前 lianban 全量(77 行,对 sentiment.db.bak-lianban-202610012304 跑)
SELECT date, value, source FROM daily_metric
WHERE metric_id='a_width_max_lianban' ORDER BY date;
-- 备份 vs 当前逐行 diff(0 行)
SELECT a.date FROM <备份> a JOIN <当前> b USING(date)
WHERE abs(a.value-b.value) > 1e-9;
```

**术语约定(后续报告必须遵守)**:云上 `sentiment.db` **没有独立 `lianban` 表**——连板数据落在 **`daily_metric.metric_id='a_width_max_lianban'`** 的行;`a_sentiment` 也不是表,是 **`score_daily.score_id`**。报告/台账一律用精确坐标,不写「lianban 表」「a_sentiment 表」类简写。
