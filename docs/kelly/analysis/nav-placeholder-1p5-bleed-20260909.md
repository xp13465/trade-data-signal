# 信号凯利回测 current_price=1.5 污染止血(2026-09-09, P0)

## 现象

用户报线上 bug:信号凯利回测 80%+ 收益率、持仓 current_price 全变 1.5 元、卖出价异常。

## 根因(主控已定位,2026-09-08 盘后 backfill 时序)

- `etf_daily` 表 `20260908` 有 1540 行 `accum_nav=1.5` 占位污染,split:
  - **1480 行混合行**:真实名 + 真实 close + 残留 `accum_nav=1.5`(盘后 backfill 覆盖了 OHLC/name 但不覆盖 accum_nav,COALESCE 不覆盖已有值)。
  - **60 行纯占位行**:`etf_name=etf_code`,close NULL,盘后仍无真实价。
- accum-nav pipeline 只补 `accum_nav IS NULL` 的行 → 1.5 非 NULL 永不修复。
- 回测 current_price 取 `max(date)=20260908` 的 `accum_nav=1.5` → 全持仓 current_price=1.5,收益率虚高 80%+。
- 线上 `signal_kelly_trades.json` 与 `signal_kelly_trades_sdc.json`(05:10 生成)均已污染。

## 修复链路(执行 2026-09-09 09:47-10:10)

1. **置 NULL**:`scripts/fix_etf_daily_nav_placeholder.py` 只处理混合行
   (`date='20260908' AND accum_nav=1.5 AND etf_name<>etf_code`,1480 行)置 NULL;
   60 行纯占位行保护不动。实改前自动备份 DB → `data/etf_national_team.db.bak-p0-20260909`。
2. **补齐**:`.venv/bin/python -m app.collector.etf_national_team accum-nav --lookback 30`
   (cwd=trade-data),缺失 1493 行 / 1492 只,补 1442 行 ok=1442 skip=0 失败 0(985s)。
   未补 38 行均为 QDII 跨境 ETF(纳指/标普/德国/法国/沙特等,东财源无累计净值;
   9/7 有 37/38 覆盖,回测 current_price 兜底取 9/7 nav,非污染)。
3. **DB 验证**:20260908 混合 accum_nav=1.5 残留 0;纯占位 etf_name=etf_code 60 行保持;
   `588930` 残留 1 行是**真实值**(akshare fund_open_fund_info_em 实测 9/8 累计净值=1.5000),
   已加入脚本 `REAL_NAV_ONE_FIVE` 豁免集。
   抽样对账:158000=1.047 / 562810=1.1806 / 159919=2.2227 与 akshare 实测逐位一致。
4. **重生成双档产物**(trade-data cwd):
   ```bash
   .venv/bin/python scripts/signal_kelly_backtest.py \
     --output static-site/data/signal_kelly_backtest.json \
     --trades-output static-site/data/signal_kelly_trades.json          # NDO 主档(默认)
   KELLY_BUY_NEXTDAY=0 .venv/bin/python scripts/signal_kelly_backtest.py \
     --output static-site/data/signal_kelly_backtest_sdc.json \
     --trades-output static-site/data/signal_kelly_trades_sdc.json      # SDC 对比档(#91)
   ```
   (⚠ 第 1 次跑 sdc 时漏传 `--trades-output`,把主档 signal_kelly_trades.json 覆盖为 sdc 档;
   已重新正确生成两档,10:09/10:10,`--trades-output` 必传。)
5. **产物验证**:
   - NDO: generated_at=10:09,304120 行,current_price==1.5 计数 0,sell_price==1.5 计数 0。
   - SDC: generated_at=10:10,304440 行,同 0。
   - 分片 trade_data/signal_kelly_trades_parts/(NDO)与 signal_kelly_trades_sdc_parts/(SDC)已重新生成
     并精确验证 t2026 分片 57000 行 current_price==1.5=0。
   - 抽样持仓 current_price 与 DB 9/8 accum_nav 逐位一致(562810=1.1806 / 516390=0.8221)。

## 上线状态(2026-09-09 10:1x)

- 本地 trade-data + trade 侧 `static-site/data/` 已同步新产物(文件级,static-site/data 已 gitignored)。
- **deploy.sh 被 §14 盘中闸门拒跑**(IS_TRADING=1, 10:1x 在 09:30-15:30 窗口内),未 force。
  → R2/线上数据仍是 05:10 污染版,待主控/用户拍板:
  - 方案 A:等盘后 15:30 后跑 `bash scripts/deploy.sh`(标准渠道,走 export + R2 + 闸门)。
  - 方案 B:盘中精确更新 kelly 相关 R2 key:
    `REPO=/Users/linhuichen/code/trade-data python scripts/upload_r2.py upload <local> data/signal_kelly_trades.json`
    等 + upload-kelly-parts + upload-kelly-parts-sdc(纯上传不碰 intraday,20KB intraday <1MB 不受
    upload-data-large 影响;但 upload-data-large 本身会连带 sentiment/index 大文件,不建议盘中跑)。

## 同类错误面清单(§23.2 三铁律)

| 项 | 检查结果 |
|---|---|
| signal_kelly_trades.json(NDO 主档) | ✅ 已重生成无 1.5 |
| signal_kelly_trades_sdc.json(#91 对比档) | ✅ 已重生成无 1.5 |
| signal_kelly_backtest.json / _sdc.json(统计档) | ✅ 连带重生成 |
| signal_kelly_trades_parts/ 分片(16 年片) | ✅ 已重生成,抽样精确验证 |
| signal_kelly_trades_sdc_parts/ 分片 | ✅ 已重生成 |
| signal_kelly_trades_intraday.json(盘中档) | 9/9 10:15 由其他链路生成,不属于本污染(盘中档用真实开盘价) |
| signal_kelly_snapshots/(每日快照) | 同 05:10 快照期,已停更告警会覆盖;非 1.5 污染源(快照是历史固化) |
| 其他 date 的 accum_nav=1.5 混合行 | 历史各日各有 1-2 行(如 2009-2026 各孤立日),疑似真实值或历史占位;
  对回测 current_price 无影响(max(date) 只取最新日),记录观察项不处理 |

## 复盘

- **教训**:盘后 backfill 写了真实 OHLC/name 但遗留 1.5 accum_nav,COALESCE 不覆盖已有值;
  accum-nav pipeline"只补 NULL"设计对"占位非 NULL 坏值"免疫。
  **需求**:占位写入与 backfill 应同判据(同写/同清);累积净值补齐应防"1.5 哨兵"。
  代码防御(accum_nav=1.5 判据 + pipeline 清扫占位)归于代码防御 agent,本次仅数据止血。

## 复现

- 修复脚本:`scripts/fix_etf_daily_nav_placeholder.py`(trade git,本 feat 分支;tracked)。
- 输入依赖:`trade-data/data/etf_national_team.db` etf_daily 表(主库,cwd=trade-data)。
- 重跑命令:
  ```bash
  cd /Users/linhuichen/code/trade-data
  # 1 预览(不改库)
  /Users/linhuichen/code/trade/.venv/bin/python scripts/fix_etf_daily_nav_placeholder.py --dry-run
  # 2 实改(自动备份 data/etf_national_team.db.bak-p0-20260909 + 置 NULL 1480 行)
  /Users/linhuichen/code/trade/.venv/bin/python scripts/fix_etf_daily_nav_placeholder.py
  # 3 补齐真实累计净值
  .venv/bin/python -m app.collector.etf_national_team accum-nav --lookback 30
  # 4 验证无残留 + 纯占位 60 行保护 + 588930 真实值豁免
  /Users/linhuichen/code/trade/.venv/bin/python scripts/fix_etf_daily_nav_placeholder.py --verify
  # 5 重生成回测双档(见上文"修复链路 4")
  ```
- 数据截止:2026-09-09,DB max(date)=20260909;污染判定日 20260908。
- 关键口径一句话:混合行 = date='20260908' AND accum_nav=1.5 AND etf_name<>etf_code(1480),置 NULL 后由
  accum-nav pipeline 从 akshare fund_open_fund_info_em 补真实累计净值;60 行纯占位 etf_name=etf_code 不动。