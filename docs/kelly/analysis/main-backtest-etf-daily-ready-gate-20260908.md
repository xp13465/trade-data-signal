# 主档回测 etf_daily 就绪判定闸门(2026-09-08)

> 实施方:implementer。背景:内审 FAIL 项(生产时序衔接缺陷),用户已拍板处置方向②改时序。
> 测试基准:current baseline(v1.1.7,memory `test-baseline-v112-anchor`)。本改动只加"数据就绪判定"前置闸门,不改回测口径/算法/键集,基线数字改动前后应一致(除 9/7 信号补入造成的预期推进)。
> 状态:**已实施**。改动文件:`scripts/signal_kelly_backtest.py`(唯一),commit 见报告末尾。

## 0 事故背景

9/7 买入的 5 笔(buy_aux×3 + buy_special×2,涉 516660/516390/159062/562510/512430)在主交易记录表/回测统计/首页模拟弹窗缺失,要等 9/9 主档才补入。

## 1 根因链(全部代码+数据证据)

### R1:主档回测生成时点(19:22)早于 etf_daily 9/8 真实 close 落库(20:40)

- 调用链:`update_all.sh`(launchd `com.trade.update-all` 17:50)四个 pipeline 完成后,O1 统一 deploy → `deploy.sh all` → `static-site/export.py` 7.9.2 步 subprocess 调 `signal_kelly_backtest.py` → 生成 `signal_kelly_trades.json`(export.py L1208-1212)。
- 实况(update_all_20260908_1750.log):pipeline 完成 19:20:52,O1 deploy 开始 19:22:04,signal_kelly_trades.json 生成 19:31(72,405,008 bytes)。**此时 etf_daily 9/8 仍是盘中占位态**。

### R2:9/8 etf_daily 盘中占位行(收盘前常态)

DB 实况(date | 总行 | accum_nav=1.5 占位 | close IS NULL):

```
20260902 | 1487 | 0 | 0
20260903 | 1488 | 0 | 0
20260904 | 1490 | 0 | 0
20260907 | 1491 | 0 | 0
20260908 | 1552 | 1540 | 1540   ← 当日尚未被真实收盘价覆盖
```

- 占位行特征:`accum_nav=1.5 / open=1.49 / close=NULL / etf_name=etf_code`(全同值)。
- 写入来源:盘中全市场 OHLC 采集经 `_upsert_daily`(app/collector/etf_national_team.py L949-969,全仓唯一 UPSERT 入口)+ 数据源返回哨兵价 + `universe_etf_codes` 名称取不到时 etf_name 回落 code。盘中常态(9/3 有 2 行、9/4 有 1 行、9/7 有 1 行),收盘后(17:50 pipeline_daily / 20:07 backfill)被真实数据覆盖。
- **额外实测**:9/8 当天 15:35 intraday-close 采的 12 行"真实 close"全部=9/7 close(昨收复制,非真实收盘价,10 只 open/accum_nav 仍 NULL),不可信。

### R3:signal_kelly_backtest 吃到占位行 → 伪跳空剔除

- `_batch_load_etf_prices`(L482-490)SQL:`SELECT etf_code, date, accum_nav, open, close FROM etf_daily WHERE etf_code IN (...) AND accum_nav IS NOT NULL`。**占位行 accum_nav=1.5 非 NULL,被读入**。
- 定价(KELLY_BUY_NEXTDAY=1,v1.1.4 起默认,L597-605):`gap = 次日open/信号日close - 1`;`|gap| > PSEUDO_GAP_EXCLUDE(0.20)` → return None 伪跳空剔除。
- 9/7 信号(如 516660,9/7 close=0.9432)次日 9/8 open_map=1.49(占位)→ `gap = 1.49/0.9432-1 ≈ 58% > 20%` → 整笔剔除 → 5 笔交易缺失。

### R4:真实 close 落库时点(数据源延迟)——比设计更晚

- 设计假设:20:07 etf backfill 主槽写当日真实 close。
- **实测**:9/8 当天 20:35 新浪源 fund_etf_hist_sina 仍返回最新日=9/7;20:40 出 9/8(510050 close=3.017)。mootdx 源 20:36 返回空。即 20:07 主槽采集拿到的是 9/7 数据(白采),"真实 close 落库"实际要靠 **21:30 兜底槽**(launchd `com.trade.etf-national-team.plist` 20:07 + 21:30)。
- 21:30 兜底 backfill 的 deploy→export→signal_kelly_backtest 链会自动重跑主档回测(export.py 每次 deploy 都跑 7.9.2 步),具备补正主档的能力。

## 2 方案:主档回测前置 etf_daily 就绪判定闸门

**核心一句话:主档回测必须消费真实 etf_daily 收盘价后才生成;未就绪时跳过本次生成(保留现有产物),靠 21:30 etf backfill 兜底 deploy 自然重跑补正。就绪判定是硬条件,不靠时点巧合。**

### 2.1 就绪判定(新增 `_etf_daily_today_ready()`)

对 `etf_daily` 全局最新数据日 `MAX(date)`:
- 总行数 = 该日全部行;
- 真实 close 行 = `close IS NOT NULL AND etf_name <> etf_code`(etf_name=etf_code 为占位哨兵行,与 `check_data_gap_alerts.NAV_REAL_WHERE` 同标准);
- 覆盖率 = 真实 close 行 / 总行数;**≥ 95% 判定就绪,< 95% 未就绪**。
- 未就绪 → 跳过本次主档生成(不覆盖 signal_kelly_backtest.json / signal_kelly_trades.json / sdc 档 / 分片 / lab 切片 / .gz),打印"跳过原因+覆盖率+建议",退出码 0。

### 2.2 读取排除占位行(第二层防御,新增 WHERE 条件)

`_batch_load_etf_prices` SQL 加 `AND etf_name <> etf_code`:
- 就绪判定通过但残留少量占位行(如个别 ETF 源延迟)时,占位 open=1.49 不进 open_map,防"残留占位→伪跳空误剔部分信号";
- 与 check_data_gap_alerts.NAV_REAL_WHERE 同标准,盘中档 compute_intraday 截断到<=T 已排除 T+1 占位,历史日无占位(实况 9/2-9/7 占位=0),无副作用。

### 2.3 时序效果

| 时点 | 环节 | etf_daily 9/8 | 就绪判定 | 主档结果 |
|---|---|---|---|---|
| 17:50→19:31 | update_all O1 export | 占位(覆盖率<1%) | 未就绪→跳过 | 保留旧主档,不发假数据 |
| 21:30 | etf backfill 兜底 deploy→export | 真实 close 就绪(≈100%) | 就绪→正常生成 | 9/7 信号正确入主档,push 上线 |
| 次日 17:50 | update_all O1 export | 9/8 已是历史真实价 | 就绪→正常生成 | 基线一致 |

- **不新增 launchd**:21:30 兜底槽已具备完整 deploy→export→signal_kelly_backtest 链,复用零新增。
- **不破坏盘中 9:40 链路**:`--intraday-rerun` 走 compute_intraday 单独分支,不经过新判定;读取 WHERE 对盘中档无副作用。
- **兜底失败时**:主档停在旧版,`check_data_gap_alerts` checker 6/7(22:35)会告警"断档 SEVERE/定价窗内 WARN",人工核查;最坏次日 17:50 主档补入(9/8 已是历史真实价)。

## 3 改动

唯一文件 `scripts/signal_kelly_backtest.py`:
1. 新增 `_etf_daily_today_ready(min_coverage=0.95)` 函数。
2. `_batch_load_etf_prices` SQL 加 `AND etf_name <> etf_code`。
3. `main()` 主档分支(非 intraday/lab-slices-only)在 `compute()` 前调就绪判定,未就绪则跳过生成返回 0。

## 4 自测结果(实测 2026-09-08 21:0x-21:20)

- 语法检查:`python3 -m py_compile scripts/signal_kelly_backtest.py` PASS(pre-commit lint_scripts 全过)。
- 就绪判定单元实测(改动前 DB,9/8 占位):`max_date=20260908, 覆盖率=0.0077(1540/1552 占位)→ ready=False`。
- 跳过路径实测:未就绪时主档直接跳过,stderr 打印原因+覆盖率+预案,产物不生成,退出码 0(不阻塞 deploy)。验证:输出到 /tmp 路径未生成文件 + RC=0。
- 9/8 真实 close 落库实测:21:07 etf 补采(指标 21:00 backfill 链)写入 9/8 真实 OHLC(ohlc=8932 vs 20:07 白采 7440),覆盖率达 1492/1552=96.1% → 就绪判定 ready=True。
- 重跑主档(9/8 就绪后,临时输出路径,不与 deploy 双写冲突):304120 笔,最新信号日推进到 **20260907**;9/7 全部 5 笔目标(buy_aux×3: 516660/516390/159062 + buy_special×2: 512430/562510)全部入主档(各象限 A-J 各档位齐全),9/7 当日共 200 笔入档。
- 基线核对(strongest):新旧 trades **非 9/7 历史已完成交易 295272 条逐条一致(零漂移)**;未平仓浮动交易各 8648 条数量一致(浮动盈亏数字随 9/8 真实价重估,属合理);各象限统计数字差异全部源自 9/7 信号补入(如 etf_has_track/all/A n 1943→1945)+ 未平仓重估,符合验收口径「除 9/7 补入导致的预期推进外基线一致」。

## 5 复现

- 脚本:改动在 `scripts/signal_kelly_backtest.py`(追踪于 trade git 仓库,不用新脚本即可复现)。
- 输入依赖:`trade-data/data/etf_national_team.db` etf_daily 表 + `trade-data/data/sentiment.db` signal_daily + static-site/data/ 下 signal_stats.json / board_etf_map.json / signal_kelly_etf_freeze.json。
- 重跑命令(就绪后手动补跑主档,等价 17:50/21:30 export 链的单步):
  ```bash
  cd /Users/linhuichen/code/trade && REPO=/Users/linhuichen/code/trade-data \
    /Users/linhuichen/code/trade/.venv/bin/python scripts/signal_kelly_backtest.py \
    --output static-site/data/signal_kelly_backtest.json
  ```
- 数据截止:2026-09-08(事故判定当日 etf_daily 占位态)。
- 关键口径一句话:主档回测生成前检查 etf_daily MAX(date) 真实 close 覆盖率(close IS NOT NULL 且 etf_name<>etf_code)/总行数 ≥95%,未就绪跳过本次生成。