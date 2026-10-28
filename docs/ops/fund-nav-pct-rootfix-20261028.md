# 公募基金日净值 `nav_change_pct` / `prev_unit_nav` 空值根治（2026-10-28）

> 分支：`fix/fund-nav-pct-rootfix-20261028`（首版 `b11ad2e74`，本文件对应当日**审查返工**版）
> 代码：`app/collector/fund_pct.py`（单一实现）＋ `app/collector/public_fund.py`（采集端接入）
> 数据：`scripts/backfill_fund_nav_pct_252.py`（默认 dry-run，`--apply` 需备份硬门）
> 自测：`scripts/tests/test_252_fund_nav_pct_20261028.py`

## 一、依据（问题真实存在 + 根因已定位）

**现象**：`fund_daily_nav.nav_change_pct IS NULL` 在 2026-10 累积 **49,295 行**（云上权威库
`/home/ubuntu/code/trade-data/data/public_fund.db` 只读实测），其中 **10-16 单日 24,103 行**，
且该日 `prev_unit_nav` **整日全空**。

**根因（两条路径都没有兜底，代码实文）**：

1. `public_fund.fetch_daily_nav()` 的「当日尚未发布 → 回退写前一交易日」路径按设计不写
   prev / pct：次新列不存在 ⇒ `prev=None`、`use_pct=False` ⇒ `nav_change_pct=NULL`。
2. 源端当日没给「日增长率」时直接落 NULL，没有「用库内**前一交易日**那条 `unit_nav` 派生」的兜底。

**为什么必须限制为「前一交易日」（口径裁定，2026-10-28 审查）**：

- 字段语义：`nav_change_pct` 是**日**增长率，分母只能是前一交易日。
- **源端自己也拒绝跨多日算**：东财对周更基金（000053 / 009437 / 009467）周更日的 `JZZZL` 为空；
  006111 在 2026-10-15 无净值时，10-16 的 `JZZZL` 同样为空。
- 云上只读对账：对源端确实给了 pct 的跨日行，我们的多日比值与源值只对得上
  **10-24%**（gap2 20% / gap3 24% / gap4 10% / gap5 11%）；**gap=1 时 100%（2,485/2,486）**。
- 首版实现「用库里更早一条派生」会把 **2,837 行（11.1%，跨多日累计涨幅）** 写进「日增长率」字段。

**判据**：基准行 `date == last_trading_day(目标日 - 1)`，交易日历取 `app/calendar.py`
（`data/trade_dates.txt` 覆盖 1990-2026）。**禁用自然日差 1** —— 自然日口径会把
**726 行**「周末/节假日跨天但交易日相邻」的**正确日涨幅**误杀（如 10-16 周五 → 10-19 周一）。

## 二、实现预期（可观测 X → Y，已实测达成）

| 指标 | 改前（首版） | 改后（本版） | 说明 |
|---|---|---|---|
| 10 月可派生行 | 25,627 | **22,790** | 排除 2,837 行非前一交易日基准 |
| 回填后 10 月仍 NULL | 23,668 | **26,505** | 多留的 NULL 是「跨多日不补」的正确行为 |
| 10-16 保留派生行 | 24,103 | **22,047** | 该日可派生行的 97%，主战场不被推翻 |

云上只读 dry-run 实测（`python3 scripts/backfill_fund_nav_pct_252.py --db <云上库> --from 20261001 --to 20261031`）：

```
[当月空值] nav_change_pct IS NULL: 49295 行
  ├ unit_nav 也空（不可派生，跳过）: 23638 行
  ├ 基准日（前一交易日）无该基金行/为空 ⇒ 正确留 NULL: 2867 行
  ├ 行内 prev 与基准日净值不一致（跨多日列值等，不派生）: 0 行
  └ 本次将补 pct: 22790 行（其中一并补 prev: 22755 行 / 原本已有 prev 只补 pct: 35 行）
[预期] 回填后该范围 nav_change_pct IS NULL ≈ 26505 行
[耗时] 1.5s
```

## 三、性能（必修 2：按前一交易日一次性预取）

- 旧实现逐行 `SELECT unit_nav ... WHERE fund_code=? AND date<? ORDER BY date DESC LIMIT 1`，
  `EXPLAIN QUERY PLAN` = `SEARCH ... USING INDEX idx_daily_nav_code (fund_code=?)` +
  **`USE TEMP B-TREE FOR ORDER BY`**（无 `(fund_code,date)` 复合索引 ⇒ 每行一次全史排序）。
- 新实现 `PrevNavCache`：每个「基准日」一条 `WHERE date=?`（走主键 `(date, fund_code)`，
  `EXPLAIN` = `SEARCH ... USING INDEX sqlite_autoindex_fund_daily_nav_1 (date=?)`），派生只在内存查表。
- **云上只读实测（同库同口径）**：
  - 回填 dry-run（25,627 候选）：**22.15s → 1.52s**（省 20.6s）；
  - 采集端最坏路径（单日 22,893 只逐只取 prev）：**15.567s → 0.092s**（省 15.5s，
    满足「新增耗时 <1s」）。这正是 16:20 槽 `TimeoutStartUSec=900s`（实测 843-861s）里
    每次回退日多耗 11-25s 的来源，现在余量回到 ~40s 以上。
- **单一实现**：回填脚本只 `from app.collector.fund_pct import PrevNavCache, calc_pct`，
  不复制第二份公式（用例 C7 源码形状守卫）；采集端与回填共用同一口径与同一取数路径。

## 四、证据用例清单（`scripts/tests/test_252_fund_nav_pct_20261028.py`，32 例）

| 用例 | 守什么 |
|---|---|
| A1 / A10 | gap=1 派生成功；**跨周末但交易日相邻（10-16→10-19）仍派生** ⇒ 守「禁用自然日」 |
| A11 / A12 | gap=2（10-16→10-20）⇒ NULL；跨国庆长假（09-30→10-09）⇒ NULL |
| A2 / A13 | 源端 prev 列值仅在「列日期 == 前一交易日」时采信；gap2 列值改用基准行（prev 与 pct 同口径） |
| A3-A9 | prev=0 / 真首条 / pct 已有 / unit 空 / 基准行 unit 空 / calc 边界 / 包装函数 |
| A14 | 交易日历不可用 ⇒ 保守不派生（绝不退化成自然日口径） |
| A15 | 预取路径 vs 逐行点查**逐位一致**（15 组） |
| B1-B7 | 经**真实** `fetch_daily_nav`：正常路径缺 pct 派生 / 回退路径用基准行 / 列值优先 / 真首条 NULL / 已有值不被 COALESCE 抹 / **采集端列值 gap2 ⇒ 按限制处理** |
| C1-C6 | 回填范围判据（含 gap / prev 不一致桶）/ dry-run 零写入（md5 前后一致）/ 只补 NULL + 回滚清单 + 精确还原 / 幂等 / 跳过被别人改过的行 / 分批 |
| C7 | 源码形状守卫：回填脚本无第二份公式 |
| C8 | **`--apply` 备份硬门**：不给 / 不存在 / 指向库本身 / 非 SQLite / 行数不符 ⇒ 全部拒绝且零写入 |
| C9 | `--from/--to` 必须 8 位 `YYYYMMDD`（传 `2026-10-01` 现在报错，不再静默 0 行） |
| C10 | **回滚清单先落盘**：commit 失败 ⇒ 库不变 + 该批日志回退到起点（不留「以为写了」的记录） |

**变异验证（cp 备份 + 还原 + md5 一致）**：

- 变异①（`PrevNavCache.prev_nav` 退回「库里更早任意一条」= 去掉 gap 限制）⇒ **8 例红**
  （A11 / A13 / A15 / B6 / B7 / C1 / C2 / C3）。
- 变异②（`prev_trading_date` 换成自然日差 1）⇒ **A10 红**。
- 还原后 `md5 = 10aed1a40a11af966cad2d0d362b4002`（与变异前一致）。

## 五、安全（必修 3 / 必修 4）

- **默认 dry-run**：`mode=ro` + `PRAGMA query_only=1`，物理写不了库；本轮全部验证均为 dry-run。
- **`--apply` 备份硬门（必修 3）**：必须显式 `--backup-confirm <备份文件>`，判据 = 存在 +
  普通文件 + 不是当前库本身 + SQLite 文件头 + `fund_daily_nav` **行数与当前库逐位相等**；
  任何一条不满足 ⇒ 拒绝执行并给出正确备份命令（`sqlite3 <db> ".backup <路径>"`，
  **别用 `cp`** —— WAL 模式下 `cp` 可能丢最新提交）。
- **回滚清单先落盘（必修 4）**：`写盘 + flush + os.fsync` 成功后才 `commit`；
  commit 失败 ⇒ `rollback` + 该批日志回退到本批起点（标记未生效）。
- **建议 7（本单做）**：`--from/--to` 8 位日期格式校验（非法/不存在的日期直接报错退出 2）；
  `--apply` 前回显实际范围与预计行数（范围 / 计划行数 / 各类跳过数）。

## 六、回填操作前置（真正 `--apply` 时）

1. **窗口**：等 `trade-public-fund-daily`（16:20 槽）跑完、确认没有其它写 `public_fund.db` 的任务
   再动手（建议 17:00 后或 21:00 后非采集时点）。
2. **备份**：`sqlite3 /home/ubuntu/code/trade-data/data/public_fund.db ".backup /home/ubuntu/backups/public_fund_pre252_$(date +%Y%m%d_%H%M%S).db"`
   并用 `--backup-confirm` 传入（硬门会自己核对行数）。
3. **先 dry-run**：`--from 20261001 --to 20261031 --report /tmp/plan.jsonl`，核对计划行数。
4. **执行**：`--apply --backup-confirm <备份>`；完成后脚本自带写后自检（重跑候选应为 0 行）。
5. **回滚**：`--rollback /tmp/backfill_fund_nav_pct_<ts>.jsonl`（只还原「当前值仍等于我们写入值」的行，
   被别人改过的跳过并报告）。

## 七、诚实标注

- 派生 pct 是**原始比值**口径（单位净值 / 前一交易日单位净值 − 1）；源端「日增长率」在**分红日**
  是调整口径（分红额并入涨幅），**分红日两者会有微差** —— 与 #251 脚本同一既有结论。
- **跨多日不补导致的部分 NULL 属正确行为**，不是漏补（本版 10 月 2,867 行）：
  含真首条（库里无前一交易日行）与 gap≥2 / 周更基金。
- `unit_nav IS NULL` 的基金（QDII / FOF / 定开当月不发布，**1,942 只**）根本不可派生。
- 本单**不**做（记录为跟进项）：
  ① 「pct 有值但 prev 空」（10 月 495 行）可选补 prev；
  ② 派生值四舍五入对齐源端（派生值是原始比值，不对齐）；
  ③ `scripts/backfill_fund_nav_null_days_251.py:181` 的第二份公式收敛（既存，另立项）。

## 八、上线观察锚点（合并后次日）

1. **16:20 槽时长应仍 ≈860s（不恶化）**：`journalctl -u trade-public-fund-daily --since today`
   或 `systemctl show -p TimeoutStartUSec` 对照；若明显低于 900s 上限且日志出现 `[E] fund_daily_nav`
   用时接近 900 ⇒ 说明还有别处逐行查库，立即回查。
2. **当日空值增量应接近 0**：次日跑完查
   `SELECT COUNT(*) FROM fund_daily_nav WHERE date='<T日>' AND nav_change_pct IS NULL`，
   应只剩「unit 为空 / 基准日无行」两类（≈2,000 行量级），不再出现 24,000 行量级。
3. **prev 是否整日有值**：`SELECT COUNT(*) FROM fund_daily_nav WHERE date='<T日>' AND prev_unit_nav IS NULL`
   的增量应同样低；若整日全空 ⇒ 回退路径没走到 `PrevNavCache`，查 `prev_col_date` 是否被正确传入。
4. 回填执行后：`nav_change_pct IS NULL` 总量应从 78,455（10-28 云上实测）明显下降；
   10 月应从 49,295 降到 ≈26,505（按本版口径）。