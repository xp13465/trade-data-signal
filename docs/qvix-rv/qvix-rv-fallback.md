# QVIX 真异源兜底(RV 近似)设计报告

> 日期：2026-08-15 ｜ 分支：feat/qvix-rv-backfill ｜ 状态：C 兜底 + 结构升级已实施（本次不做 B）

## 1. 背景与问题

QVIX（中国波指，期权隐含波动率 A 股恐慌指数）主源为 `1.optbbs.com`（阿里云，期权论坛）。
2026-08-14（周五）凌晨 02:00 起宕机至今未恢复（DNS 正常、TCP connect=0、HTTP 000）。

- **主源 daily csv** 和 **fallback 分钟 csv**（vix300.csv/vix50.csv）位于**同一台服务器=伪多源**，
  整机宕机时一起挂，旧 fallback 形同虚设。
- 8/13（周四）21:00 最后一次正常：`a_qvix_300=18.75`、`a_qvix_1000=16.72`，DB 停在 8/13。
- 8/14 盘中 qvix 全程缺，影响：情绪分 qvix 分项（sentiment.py L104-109）、
  波指飙升告警 L7 权重 0.07（alert_score.py L302-304）、signals.py 买卖点信号（L772-774）、
  首页 KPI sparkline（queries.py L45/L1091/L1431）。

**历史遗留**：`a_qvix_1000` 的 func 是 `index_option_50etf_qvix`（50ETF期权），id 却叫 qvix_1000
（7-20 换源遗留，原名中证1000股指期权源停更，人工换到50ETF期权）。名字标注「中国波指(50ETF期权)」。
本任务**冻结契约不动 id/采集语义**，RV 兜底只对齐它现有口径（用 510050）。

## 2. 方案（用户已拍板：C 兜底 + B 中期升级，本次只做 C + 结构升级）

| 方案 | 内容 | 本次 |
|---|---|---|
| C 兜底 | 用 50ETF/300ETF 日收益算 20 日滚动年化已实现波动率（RV）作近似兜底 | ✅ 本次实施 |
| B 中期 | 自算真 QVIX 口径一致（期权定价） | ❌ 单独立项，本次不做 |
| 结构升级 | 把「单源 + 同服务器伪 fallback」升级为「optbbs 主源 + 本地自算 RV」真异源互备 | ✅ 本次实施 |

## 3. RV 计算口径

- **公式**：RV = 最近 20 个交易日**对数收益率**的样本标准差 × √252 × 100（年化，单位 %）
  - `r_t = ln(close_t / close_{t-1})`
  - `RV = std(r_{t-19..t}) × √252 × 100`
- **窗口**：20 个交易日（与 QVIX 波指的时间尺度一致；窗口内有效收益 ≥5 个才输出，极端稀疏不输出）
- **数据来源**：510050/510300 日线 close，复用 `fetch_etf_ohlc`
  （akshare `fund_etf_hist_sina` 主源 + mootdx fallback，**本身即真异源**，任一源挂不影响另一源）
- **映射**：
  - `a_qvix_300` → 510300（300ETF，对齐 300ETF 期权口径）
  - `a_qvix_1000` → 510050（50ETF，对齐其实际在用的 50ETF 期权口径——冻结契约不趁机改名）
- **输出**：`[(date, rv)]` 全序列（历史回填 + 当日），与 qvix 的 close 单值语义一致，
  消费方 `load_metric_series`/`load_metric_value` 零改动即可跟随。

**口径差异警示**：RV 是已实现波动率（已发生的价格波动），QVIX 是隐含波动率（市场对未来波动率的预期），
二者理论关系为 IV ≈ RV + 风险溢价。A 股期权市场价差不大（见 §6 验证），约 19-24 vs QVIX 17-19 同量级，
作为**兜底近似**可接受，精确口径待 B 方案。此差异已前端公示。

## 4. fallback 链路图

```
采集 collect_series(a_qvix_300 / a_qvix_1000)
   │
   ├─ 主源 optbbs daily csv (index_option_300etf_qvix / index_option_50etf_qvix)
   │    ├─ 成功 + 有当日  → 用主源 QVIX 值, source=akshare（优先）
   │    ├─ 主源异常/空    → ↓ 切 RV（source=rv_local）
   │    └─ 成功但缺当日   → ↓ 只补 RV 最新交易日一行（source=rv_local, 历史段仍主源口径）
   │
   ▼
本地 RV 自算 (fetch_etf_ohlc: sina fund_etf_hist_sina 主源 + mootdx fallback)
   ├─ 510300 . 510050 日线 close → 20 日滚动年化对数波动率
   └─ 返回全序列/补当日 → collect_log 记录「RV 兜底 rv_local」→ DB source=rv_local
```

- **触发条件（两种都切 RV）**：① 主源 `safe_call` 返回 Exception/空 ② 主源成功但缺当日行
- **source 标记**：RV 兜底入库 `source='rv_local'`，主源 `source='akshare'`，可 DB 溯源
- **恢复回主源**：optbbs 恢复后，主源 daily csv 优先（collect_series 只在主源空/缺当日时切 RV）

## 5. 代码改动

| 文件 | 改动 |
|---|---|
| `app/collector/fetchers.py` | 移除伪多源 QVIX_MIN_FUNCS/分钟 csv fallback；新增 `RV_ETFS` 映射 + `_qvix_rv_series()` RV 计算 + `RV_SOURCE` 标记；collect_series 两处 fallback 改调 RV，返回三元组 `(rows, msg, src)` |
| `app/collector/runner.py` | `upsert_metrics_many` 加 `source` 参数；collect_series 接三元组入库 source；**补回 `_now()` 定义**（be3da2c94 误删，回归 bug 致 upsert 全 NameError，本次修复） |
| `app/collector/index_backfill.py` | 两处 collect_series 接三元组 + 传 source |
| `scripts/us_stock_morning.py` | collect_series 接三元组 |
| `scripts/rzhb_backfill.sh` | collect_series 接三元组 |
| `static-site/app.js` | qvix 公示 4 处补 RV 兜底口径说明（§21） |
| `README.md` | 功能亮点补真异源兜底说明 |

## 6. RV 数值验证（2017 真实数据，venv 实跑）

| 指标 | 8/13 RV | 8/14 RV | 主源最后值(8/13) |
|---|---|---|---|
| 300ETF(510300) → a_qvix_300 | 23.39 | **19.66** | 18.75 |
| 50ETF(510050) → a_qvix_1000 | 18.80 | **16.61** | 16.72 |

RV 与主源 QVIX 最后值同量级、方向一致（8/14 波动回落），作为兜底近似合理。
510050 拉取 5221 行（2005 上市）、510300 拉取 3456 行，20 日窗口 + 历史分位基准充足（≥250 交易日远超阈值）。

## 7. 消费方零改动确认

QVVIX 消费方全走 `load_metric_series`/`load_metric_value`（读 daily_metric.value），
不读 source，故 RV 值入库后自动跟随，消费方代码零改动：
- `app/compute/sentiment.py` L104-109（hs300/csi1000 情绪分 qvix 分项）
- `app/alert_score.py` L302-304（L7 波指飙升告警）
- `app/compute/signals.py` L772-774（买卖点信号）
- `app/queries.py` L45/L1091/L1431（首页 KPI sparkline / 指标序列）

## 8. 降级透明化

- collect_log 在 RV 生效时记录「RV 兜底 rv_local（主源宕机/缺当日）」非静默 ok
- DB daily_metric.source='rv_local' 可溯源
- 前端 qvix 4 处公示文案标注意义差异：主源宕机时 RV 近似、源恢复后回 QVIX

## 复现

- **RV 计算脚本（活脚本生产引用）**：RV 逻辑在 `app/collector/fetchers.py::_qvix_rv_series`，
  生产采集链路直接调用，无独立副本（防双份维护分叉）。
- **复现命令**（在项目根目录，venv）：
  ```
  cd /Users/linhuichen/code/qvix-rv-backfill
  /Users/linhuichen/code/trade/.venv/bin/python -c "
  from app.collector import fetchers
  for f in ('index_option_300etf_qvix','index_option_50etf_qvix'):
      rv = fetchers._qvix_rv_series(f)
      print(f, rv[-1])
  "
  ```
- **输入依赖**：510050/510300 日线 close，来源 akshare `fund_etf_hist_sina`（sina 主源，mootdx fallback），
  经 `fetch_etf_ohlc` 拉取（etf_national_team.py，无起止参数返全历史本地过滤）。
- **数据截止/版本**：2026-08-14 收盘（510050 至 20260814 close=3.021，510300 至 20260814 close=4.726）。
- **关键口径一句话**：RV = 20 日滚动对数收益率样本标准差 × √252 × 100；窗口内有效收益 ≥5 才输出。
