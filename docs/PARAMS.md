# PARAMS 参数细则文档 · A股情绪看板（tdsignal）

> 文档基于代码现状（2026-07-11），所有参数均读代码确认，不编造。
> 代码仓库：/Users/linhuichen/code/trade

---

## 1 策略参数（买卖点信号）

> 源文件：`app/compute/signals.py` + `a-stock-data/backtest_strategies.py` + `config/indicators.yaml`

### 1.1 指标计算参数

| 指标 | 参数 | 默认值 | 计算方式 | 源文件 |
|------|------|--------|----------|--------|
| RSI | period | 14 | EWM α=1/period, adjust=False；gain=max(delta,0), loss=max(-delta,0), RSI=100-100/(1+avgGain/avgLoss) | signals.py `_rsi()` / backtest_strategies.py `rsi()` |
| 布林带 | window, n_std | 20, 2.0 | mid=rolling(20).mean(), sd=rolling(20).std(ddof=0), bu=mid+2σ, bl=mid-2σ | signals.py `_bollinger()` / lab.js `computeBBLab()` |
| MACD | fast, slow, signal | 12, 26, 9 | DIF=EMA(12)-EMA(26), DEA=EMA(DIF,9)；EMA=ewm(span=N, adjust=False) | signals.py `_macd()` / lab.js `computeMACDLab()`（alpha=2/(N+1)） |
| ATR | period | 14（backtest_strategies）/ 10（Supertrend） | TR=max(H-L, |H-前收|, |L-前收|)；ATR=EWM(TR, α=1/14) 或 Wilder RMA | backtest_strategies.py `atr()` / lab.js `computeATRTrailLab()` |
| Supertrend | period, mult | 10, 3.0 | ATR(10) Wilder平滑 × 3；basicBand=hl2±mult×ATR；finalBand 带冗余收缩；dir 翻转逻辑 | lab.js `computeSupertrendLab()` |
| MA | periods | [5, 10, 20, 60] | SMA(close, n)，min_periods=n | ma_alignment.py |
| KDJ | n | 9 | RSV=(close-low_n)/(high_n-low_n)*100, K=EMA(RSV,1/3), D=EMA(K,1/3) | lab.js `computeKDJLab()` |
| Donchian | n | 10, 20, 55 | upper=high.rolling(n).max().shift(1), lower=low.rolling(n).min().shift(1)（不含当日） | lab.js `computeDonchianLab()` |

### 1.2 买点信号触发条件

| 信号 key | 中文名 | 触发条件（精确） | 状态 | 源文件 |
|-----------|--------|------------------|------|--------|
| C1_RSI30 | RSI上穿30买 | RSI(14) 前日≤30 且 当日>30（超卖结束） | **live 生产** | signals.py / backtest_strategies.py |
| BB_lower_revert | 布林下轨回归买 | 前日 close<bl[前日] 且 当日 close>bl[当日]（跌破下轨后收回） | 实验中 | lab.js `computeBBLowerRevertLab()` |
| Supertrend_buy | Supertrend翻多买 | dir 前日=-1 且 当日=+1（趋势线翻多） | 实验中 | lab.js `computeSupertrendLab()` |
| Donchian20_up | 唐奇安20日突破买 | close 当日>upper[20] 且 前日≤upper[20]（突破近20日最高） | 实验中 | lab.js |
| Donchian55_up | 海龟55日突破买 | close 当日>upper[55] 且 前日≤upper[55] | 实验中 | lab.js |
| MA_golden_5_20 | MA5/MA20金叉买 | MA5 前日≤MA20 且 当日>MA20 | 实验中 | lab.js |
| MA_golden_10_60 | MA10/MA60金叉买 | MA10 前日≤MA60 且 当日>MA60 | 实验中 | lab.js |
| MACD_golden | MACD金叉买 | DIF 前日≤DEA 且 当日>DEA | 实验中 | lab.js |
| BB_upper_break | 突破布林上轨买 | close 前日≤bu 且 当日>bu | **已排除** | lab.js |
| KDJ_golden_oversold | KDJ超卖金叉买 | K 前日≤D 且 当日>D 且 K<35 | **已排除** | lab.js |
| Vol_breakout | 放量突破买 | volume>2×MA(20,vol) 且 pct_change>2% | **已排除**（指数无 volume，不出图） | backtest_strategies.py |

### 1.3 卖点信号触发条件

| 信号 key | 中文名 | 触发条件（精确） | 状态 | 源文件 |
|-----------|--------|------------------|------|--------|
| D1_high20_drop5 | 20日高回落5%卖 | th=hh20×0.95；close 前日≥th 且 当日<th，**且** close>MA60（多头过滤），**且** DIF<DEA（MACD死叉确认） | **live 生产** | signals.py / lab.js `computeD1Lab()` |
| B0_RSI70 | RSI下穿70卖 | RSI(14) 前日≥70 且 当日<70 | **已排除**（旧基线，已被 D1 替代） | lab.js |
| BB_upper_revert | 布林上轨回落卖 | close 前日>bu[前日] 且 当日<bu[当日]（突破上轨后回落） | 实验中（**不融生产**，回测劣于 D1，见 NOTES §15） | lab.js `computeBBLab()` |
| MA_death_5_20 | MA5/MA20死叉卖 | MA5 前日≥MA20 且 当日<MA20 | 实验中 | lab.js `computeMADeathCrossLab()` |
| BB_middle_break | 跌破布林中轨卖 | close 前日≥mid 且 当日<mid（mid=MA20） | 实验中 | lab.js |
| Donchian10_down | 跌破10日最低卖 | close 当日<lower[10] 且 前日≥lower[10] | 实验中 | lab.js |
| Donchian20_down | 跌破20日最低卖 | close 当日<lower[20] 且 前日≥lower[20] | 实验中 | lab.js |
| MACD_death | MACD死叉卖 | DIF 前日≥DEA 且 当日<DEA | 实验中 | lab.js |
| ATR_trail_stop | ATR追踪止损卖 | trail=hc20-3×ATR(14)；close 当日<trail 且 前日≥trail（hc20=近20日最高收盘价） | 实验中 | lab.js `computeATRTrailLab()` |
| KDJ_death_overbought | KDJ超买死叉卖 | K 前日≥D 且 当日<D 且 K>70 | **已排除** | lab.js |
| Supertrend_sell | Supertrend翻空卖 | dir 前日=+1 且 当日=-1 | **已排除** | lab.js |

### 1.4 Per-index 参数调优

> 源文件：`config/indicators.yaml` 的 `buy_filter` / `buy_aux_filter` 字段

**buy_filter（收紧买点阈值，从 RSI 30 改为 RSI 25）**：

| 指数/行业 | buy_filter | 说明 |
|-----------|------------|------|
| kc50（科创50） | rsi_cross_25 | 科创50波动大，收紧阈值减少假信号 |
| sw_801730（电力设备） | rsi_cross_25 | |
| sw_801760（传媒） | rsi_cross_25 | |

**buy_aux_filter（辅买信号过滤条件）**：

| 过滤类型 | 触发条件 | 适用指数（18个） |
|---------|----------|------------------|
| rsi_cross_40 | RSI 从 ≤40 升回 >40（比 C1 的 30 宽松） | sh/sz/hs300/sz50/csi500/csi1000/cyb/bj50/恒生科技/恒生指数/恒生国企 等 11 个 |
| close_above_bl_2pct | 当日收盘价 > 布林下轨 + 2%（确认收回力度） | sw_801080(电子)/sw_801170(通信)/sw_801750(计算机)/sw_801880(机械)/sw_801960(食品饮料)/sw_801120(食品) 等 7 个 |

### 1.5 信号 reason 字符串格式

> 源文件：`app/compute/signals.py` `compute()` 函数

信号生成时附带 reason 字符串，格式示例：
- buy: `"RSI(14)从29.3升至31.2，上穿30阈值"`
- buy_aux: `"收盘价3285.1收回布林下轨3282.4之上(+0.08%)"`
- sell: `"收盘价3285.1从20日最高3456.0回落5.0%至阈值3283.2，且>MA60(3250.3)且MACD死叉"`

### 1.6 卖点盈亏标注

> 源文件：`app/compute/signals.py`

卖点信号生成时查找最近的前买点，标注持有期盈亏：
- 前买点为 buy：标注"盈亏 +X.X%"（正=赚 红/负=亏 灰）
- 前买点为 buy_aux：标注"辅买盈亏"
- 无前买点：标注"无前买点"（橙色 #ff9800）
- 买点失败（后无卖点）：标注灰色 #9e9e9e

---

## 2 回测参数

> 源文件：`scripts/lab/lab_simulate.py`（523 行）+ `a-stock-data/backtest_strategies.py`（781 行）

### 2.1 回测框架参数

| 参数 | 值 | 说明 |
|------|-----|------|
| SAMPLE_STOCKS | 200 | 回测采样股票数（从全 A 股随机抽取） |
| SEED | 20260705 | 随机种子（保证可复现） |
| HORIZONS | (5, 10, 20, 60) | forward 收益计算窗口（交易日） |
| 统计窗口 | 全史 / 近10年 / 近5年 / 近3年 / 近1年 | 5 个时间窗口 |

### 2.2 模拟回测参数（lab_simulate.py）

| 参数 | 值 | 说明 |
|------|-----|------|
| INITIAL_CAPITAL | 100,000 元 | 初始本金 |
| POSITION_SIZE | 10,000 元 | 定额模式每次买入金额 |
| MAX_POSITIONS | 10 | 最大同时持仓数 |
| MAX_CURVE_POINTS | 100 | 净值曲线最大点数（降采样） |
| MAX_CURVE_POINTS_WIN | 100 | 每窗口净值曲线最大点数 |
| 交易模式 | full_in / fixed_10k | 全仓进出 / 1万定额分批 |
| 配对组合 | 8 买 × 8 卖 = 64 | 去重后按 "buyKey|sellKey" 存一份 |
| 总组数 | 64 × 2 模式 = 128 | 每指数 128 组回测 |

**模拟指数列表（9 个 A 股宽基）**：

| id | 名称 | 说明 |
|----|------|------|
| sh | 上证指数 | 大盘 |
| sz | 深证成指 | |
| cyb | 创业板指 | 成长 |
| kc50 | 科创50 | 科技 |
| bj50 | 北证50 | 2022 起，历史较短 |
| sz50 | 上证50 | 价值 |
| hs300 | 沪深300 | |
| csi500 | 中证500 | 中小盘 |
| csi1000 | 中证1000 | 小盘 |

**BUY_KEYS（8个）**：BB_lower_revert, Supertrend_buy, Donchian20_up, Donchian55_up, MA_golden_5_20, MA_golden_10_60, MACD_golden, C1_RSI30

**SELL_KEYS（8个）**：BB_upper_revert, MA_death_5_20, BB_middle_break, Donchian10_down, Donchian20_down, MACD_death, ATR_trail_stop, D1_high20_drop5

**窗口定义**：

| key | 中文名 | 年数 |
|-----|--------|------|
| all | 全历史 | None |
| y10 | 近10年 | 10 |
| y5 | 近5年 | 5 |
| y3 | 近3年 | 3 |
| y1 | 近1年 | 1 |

### 2.3 回测统计指标

`_build_stats()` 计算以下指标：

| 指标 | 计算方式 |
|------|----------|
| total_ret | 总收益率（期末/期初-1）×100 |
| annual_ret | 年化收益率 |
| max_drawdown | 最大回撤（峰值到谷值） |
| win_rate | 胜率（盈利交易/总交易）×100 |
| n_trades | 交易笔数 |
| final_total | 期末总资金 |
| years | 回测年数 |

### 2.4 推荐榜评分公式

> 源文件：`a-stock-data/backtest_strategies.py` 中的 score 计算

```
score = 0.4 × norm(total_ret) + 0.3 × norm(win_rate) + 0.2 × norm(−max_dd) + 0.1 × norm(n_trades)
```

- `norm(x)`：将指标在所有配对中归一化到 0-1（min-max normalization）
- `-max_dd`：负回撤（回撤越小分越高）
- 权重：总收益 40% + 胜率 30% + 回撤控制 20% + 样本量 10%

### 2.5 Kelly 公式（凯利仓位）

> 源文件：`web/app.js` `statsHint()` 函数

```
f* = max(0, (b·p − (1−p)) / b)
```

- `p` = 胜率
- `b` = 盈亏比（平均盈利/平均亏损）
- `f*` = 凯利建议仓位比例
- f*=0 时标注"不建议"（红色警示）

### 2.6 信号频率统计

> 源文件：`app/compute/signal_stats.py`

| 参数 | 值 | 说明 |
|------|-----|------|
| HORIZONS | (5, 10, 20) | forward 收益窗口（交易日） |
| MIN_SAMPLE | 10 | 样本数 < 10 标"样本不足" |
| 统计指标 | win_rate / pl / mean / n | 胜率/盈亏比/均值收益/样本数 |
| 存储路径 | data/signal_stats.json | 独立 JSON + 集成 runner.py step10 |

---

## 3 情绪评分参数

> 源文件：`app/compute/sentiment.py` + `app/compute/cross.py` + `app/compute/fear_greed.py` + `app/compute/normalize.py`

### 3.1 A 股综合情绪分（a_sentiment）

> 6 分量加权，源文件：`app/compute/sentiment.py`

| 分量 | metric_id | 权重 | 说明 |
|------|-----------|------|------|
| 涨跌比 | a_width_ratio | 0.25 | 上涨家数/(上涨+下跌) |
| 涨停 | a_width_zt_count | 0.20 | 涨停家数 |
| 炸板 | a_width_zb_count | 0.15 | 炸板家数（涨停后打开） |
| 连板 | a_width_lianban | 0.15 | 连板家数 |
| 成交额 | a_amount | 0.10 | 成交额 |
| 北向 | a_north | 0.15 | 北向资金净流入 |

**计算流程**：
1. 每个分量经 `normalized()` 做 rolling_percentile（120 日窗口，min_periods=10）
2. direction 调整：负向指标（如炸板）取 100-p
3. 6 分量加权求和（avail_count≥3 才输出，否则 None）
4. 输出 score_daily 表，score_id='a_sentiment'

### 3.2 Per-index 情绪分

> 源文件：`app/compute/sentiment.py` `compute_index_sentiment()`

每个指数独立计算情绪分（6 个指数：sz50/hs300/csi500/csi1000/cyb/kc50）：

| 分量 | 计算 | 权重 |
|------|------|------|
| RSI | rolling(period).mean() **注意：与 signals.py 的 EWM 版本不同**，这里用 SMA | 等权 |
| 量能偏离 | volume / rolling(20).mean() | 等权 |
| 涨跌幅 | pct_change | 等权 |
| QVIX | 仅 hs300/csi1000 有（INDEX_QVIX_MAP） | 等权（如有） |

- 每个分量经 `rolling_percentile()` 归一化到 0-100
- 等权平均（avail_count≥2 才输出）
- 输出 score_daily 表，score_id='sentiment_sz50' 等

### 3.3 跨市场综合评分（cross_market）

> 源文件：`app/compute/cross.py`

- 输入：所有 type=simple 且 enabled=True 的指标
- 归一化：每个指标经 `normalized()` 做 rolling_percentile + direction 调整
- 聚合：trim_mean（去掉最高 1 个 + 最低 1 个，取剩余均值）
- 最低数量：≥3 个指标才输出

### 3.4 恐贪指数（fear_greed）

> 源文件：`app/compute/fear_greed.py`

**输入 8 个分数（等权平均）**：

| score_id | 说明 |
|----------|------|
| a_sentiment | A 股综合情绪分 |
| cross_market | 跨市场综合评分 |
| sentiment_sz50 | 上证50 情绪分 |
| sentiment_hs300 | 沪深300 情绪分 |
| sentiment_csi500 | 中证500 情绪分 |
| sentiment_csi1000 | 中证1000 情绪分 |
| sentiment_cyb | 创业板情绪分 |
| sentiment_kc50 | 科创50 情绪分 |

- 最低数量：≥4 个分数才输出
- 输出 score_id='fear_greed'

**恐贪标签（5 档）**：

| 区间 | 标签 | 颜色 |
|------|------|------|
| ≤25 | 极度恐惧 | #c62828（深红） |
| 26-40 | 恐惧 | #e6a23c（橙） |
| 41-60 | 中性 | #86909c（灰） |
| 61-75 | 贪婪 | #67c23a（浅绿） |
| >75 | 极度贪婪 | #2e8b57（深绿） |

### 3.5 归一化参数

> 源文件：`app/compute/normalize.py`

| 参数 | 值 | 说明 |
|------|-----|------|
| _WINDOW | 120 | rolling 窗口（交易日） |
| _MIN_PERIODS | 10 | 最小数据量 |
| rolling_percentile | rolling(120).rank(pct=True) × 100 | 百分位归一化 |
| direction | negative -> 100-p | 负向指标反转 |

### 3.6 情绪标签映射

**综合情绪分标签（7 档）**，源文件：`app/compute/market_summary.py` `_sentiment_desc()`：

| 区间 | 标签 |
|------|------|
| ≤20 | 极度悲观 |
| 21-35 | 低迷 |
| 36-45 | 偏谨慎 |
| 46-55 | 平稳 |
| 56-70 | 回暖 |
| 71-85 | 乐观积极 |
| >85 | 亢奋 |

**per-index 情绪分标签（5 档）**，源文件：`app/compute/signals.py` `_cross_tag()`：

| 区间 | 标签 |
|------|------|
| ≤20 | 冰点 |
| 21-50 | 偏冷 |
| 51-70 | 中性 |
| 71-80 | 偏热 |
| >80 | 狂热 |

**冰点/过热判定**：
- 冰点：情绪分 ≤20（红色 #e6492e）
- 过热：情绪分 >80（绿色 #2e8b57）
- 中性：20-80（蓝色 #5b8ff9）

### 3.7 市场位置感

> 源文件：`app/compute/position.py`

| 参数 | 值 |
|------|-----|
| POSITION_INDICES | 8 个 A 股指数（sh/sz/hs300/sz50/csi500/csi1000/cyb/kc50） |
| WINDOW_DAYS | {"1y": 250, "3y": 750, "5y": 1250} |

**位置标签（5 档）**：

| 区间 | 标签 |
|------|------|
| ≤20% | 低位 |
| 21-40% | 偏低 |
| 41-60% | 合理 |
| 61-80% | 偏高 |
| >80% | 高位 |

### 3.8 成交量比信号

> 源文件：`app/compute/volume_ratio.py`

| 参数 | 值 |
|------|-----|
| RATIO_HIGH | 1.2（显著放量阈值） |
| RATIO_LOW | 0.8（显著缩量阈值） |
| 温和放量 | ≥1.1 |
| 温和缩量 | ≤0.9 |

**信号分类**：

| 信号 | 条件 |
|------|------|
| 放量上涨(1) | ratio≥RATIO_HIGH 且 close>前收 |
| 放量下跌(2) | ratio≥RATIO_HIGH 且 close<前收 |
| 缩量上涨(3) | ratio≤RATIO_LOW 且 close>前收 |
| 缩量下跌(4) | ratio≤RATIO_LOW 且 close<前收 |
| 正常(0) | 其他 |

### 3.9 均线排列

> 源文件：`app/compute/ma_alignment.py`

| 参数 | 值 |
|------|-----|
| MA_PERIODS | [5, 10, 20, 60] |
| 多头排列 | MA5>MA10>MA20>MA60 |
| 空头排列 | MA5<MA10<MA20<MA60 |
| 交叉 | 其他 |

### 3.10 新高新低

> 源文件：`app/compute/new_high_low.py`

| 参数 | 值 |
|------|-----|
| INDICES | 8 个 A 股宽基指数 |
| WINDOW_52W | 250 交易日（年度新高/新低） |
| WINDOW_20D | 20 交易日（月度新高/新低） |
| NH-NL | 新高数量 - 新低数量（IBD 经典指标） |

### 3.11 AD Line（腾落线）

> 源文件：`app/compute/ad_line.py`

- AD Line = cumsum(上涨家数 - 下跌家数)
- 涨跌比 = 上涨家数 / (上涨 + 下跌)
- MA5 / MA20

### 3.12 板块轮动速度

> 源文件：`app/compute/rotation.py`

| 参数 | 值 |
|------|-----|
| WINDOWS | [5, 10, 20] |
| 计算对象 | SW 行业（sw_%）+ 同花顺概念（thsc_%） |
| 轮动速度 | 领涨板块变化次数 / (N-1) × 100，0-100% |
| 前缀 | sw_ / thsc_ |

**速度标签**：

| 区间 | 标签 | 颜色 |
|------|------|------|
| ≥60 | 快速轮动 | #e67e22（橙） |
| 30-59 | 中等轮动 | #f9a825（黄） |
| <30 | 轮动缓慢 | #2e7d32（绿） |

---

## 4 采集参数

> 源文件：`app/collector/runner.py` + `app/collector/index_backfill.py` + `scripts/update_all.sh`

### 4.1 采集步骤（runner.py，11 步）

| Step | 名称 | 内容 | 数据源 |
|------|------|------|--------|
| 1 | metrics | 单值指标（利率/汇率/油价/金价/QVIX 等） | akshare（新浪/腾讯/东财） |
| 2 | indices | 指数日线（拉近 400 天）+ 多源补采校验 | 新浪主源 + baostock/腾讯补采 + 申万 trend |
| 3 | boards | 板块涨跌/资金流 | akshare（东财） |
| 4 | industry_extras | 行业资金流 + 换手率 | 东财 fflow/kline 端点（非 clist，不封） |
| 5 | stock_daily | 全 A 股日线增量更新 | 东财 push2his（封 IP 时跳过） |
| 6 | baostock | BaoStock 日线增量（默认跳过） | baostock（需 RUN_BAOSTOCK=1） |
| 7 | mootdx | mootdx 日线增量（D1 主力） | mootdx TCP 7709（不封 IP） |
| 8 | industry_width | 行业内宽度（近 15 天） | mootdx 增量后算 |
| 9 | width_history | 全市场宽度（近 30 天重算） | mootdx 增量后算 |
| 10 | futures | 期货机构持仓 + 准确率 | 中金所前 20 会员 |
| 11 | ad_line | AD Line（腾落线） | compute/ad_line.py |

### 4.2 多源补采参数

> 源文件：`app/collector/index_backfill.py`

**核心 A 股指数（9 个）**：

| index_id | baostock 代码 | 腾讯代码 | 说明 |
|----------|---------------|----------|------|
| sh | sh.000001 | sh000001 | 上证指数 |
| sz | sz.399001 | sz399001 | 深证成指 |
| hs300 | sh.000300 | sh000300 | 沪深300 |
| sz50 | sh.000016 | sh000016 | 上证50 |
| csi500 | sh.000905 | sh000905 | 中证500 |
| csi1000 | sh.000852 | sh000852 | 中证1000 |
| cyb | sz.399006 | sz399006 | 创业板指 |
| kc50 | sh.000688 | sh000688 | 科创50（baostock 无，腾讯补） |
| bj50 | None | bj899050 | 北证50（baostock 无，腾讯补） |

**申万行业指数（31 个 sw_801xxx）**：申万官方 trend API（swsresearch.com），T+1 发布延迟。

**补采优先级**：新浪主源 -> baostock（7/8）-> 腾讯兜底（全覆盖，~12s/只）

### 4.3 数据源特性

| 数据源 | 延迟 | 限流 | 特点 |
|--------|------|------|------|
| baostock | T+1 | 无 | 7/8 核心指数（缺科创50/北证50），串行 |
| mootdx | T+0 | TCP 7709 不封 IP | D1 主力源，5072 只全 A 股 |
| 新浪（akshare） | T+0 | 无 | 主源，快，全覆盖 |
| 腾讯（akshare） | T+0 | 无 | 全覆盖但慢（~12s/只全量拉取），兜底 |
| 东财（akshare） | T+0 | **IP 封禁**（clist 端点） | fflow/kline 端点可用 |
| 申万官方 | **T+1** | 无 | 唯一支持 sw_* 代码，周五数据可能周一才出 |

### 4.4 进程互斥

> 源文件：`scripts/update_all.sh` + `scripts/with_lock.py`

- 锁文件：`/tmp/trade_update_all.lock`
- 锁类型：`fcntl.flock --nb`（非阻塞独占锁）
- 持不到锁=已有在跑=自动跳过
- 采集脚本不并发（撞 progress 原子写 + 限流空转）

### 4.5 并行流水线

> 源文件：`scripts/update_all.sh` + `scripts/pipeline.sh`

| Pipeline | steps | 阻塞性 |
|----------|-------|--------|
| core | metrics/indices/boards + compute_runner(情绪分/信号/衍生) | 分钟级先上线 |
| width | mootdx/industry_width/width_history + compute_runner | 慢（5072 只） |
| futures | futures + compute_accuracy | 独立 |
| stock_daily | stock_daily + baostock | 后台不等，不 export 不 push |

各 pipeline 的 commit+push 经 `flock /tmp/trade_deploy.lock` 串行，避免 git index.lock 冲突。

---

## 5 定时任务

> 源文件：`scripts/plists/com.trade.update-all.plist` + `scripts/plists/com.trade.backfill-evening.plist`

| 任务 | 时间 | 内容 | plist |
|------|------|------|-------|
| 全量采集 | 15:33 | update_all.sh（4 pipeline 并发） | com.trade.update-all.plist |
| 补采兜底 | 20:00 | backfill_indices.sh（校验+补采+重算+推送） | com.trade.backfill-evening.plist |

- 非交易日跳过采集，仅 deploy + check_signals
- `force` 参数可绕过交易日闸门（周末补数据/校准）
- 严重告警（耗时>1h 或 core 退出码非 0）发邮件 + 写 alert_log

---

## 6 数据库参数

> 源文件：`app/db.py`

| 参数 | 值 |
|------|-----|
| DB_PATH | data/sentiment.db |
| 模式 | WAL（Write-Ahead Logging） |
| busy_timeout | 30000 ms |
| timeout | 30.0 s |
| 表数量 | 11 |

**表结构**：

```sql
daily_metric (date, metric_id, value, source, updated_at)  -- PK(date, metric_id)
index_daily (date, index_id, open, high, low, close, pct_change, amount)  -- PK(date, index_id)
board_daily (date, board_type, board_name, pct_change, net_inflow)  -- PK(date, board_type, board_name)
score_daily (date, score_id, value)  -- PK(date, score_id)
signal_daily (date, index_id, signal, reason)  -- PK(date, index_id, signal)
manual_entry (date, metric_id, value, note)
collect_log (date, metric_id, status, message, logged_at)
alert_log (id, date, severity, issue, log_path, created_at)
industry_width_daily (date, industry_id, up_count, down_count, zt_count, dt_count, zb_count, seal_rate, amount)
futures_position (date, role, product, net_position)
futures_accuracy (date, role, window, follow, contrarian)
```

- `daily_metric.source='manual'` 的记录不被自动采集覆盖（WHERE source != 'manual'）

---

## 7 UI/配色参数

> 源文件：`web/style.css` + `web/lab.css` + `web/app.js`

### 7.1 中文配色惯例（A 股红涨绿跌）

| 语义 | 颜色 | 色值 | 用途 |
|------|------|------|------|
| 红涨 | 红 | #e6492e | 涨幅/上涨/买点 |
| 绿跌 | 绿 | #2e8b57 | 跌幅/下跌/卖点止盈 |
| 蓝 | 蓝 | #165dff / #2563eb | 主色调/链接/最新数据高亮 |
| 紫 | 紫 | #9c27b0 / #d63384 | 实验策略/辅买信号 |

### 7.2 信号颜色

| 信号 | 颜色 | 色值 | CSS class |
|------|------|------|-----------|
| buy（买点） | 红 | #e6492e | `.buy` |
| buy_aux（辅买） | 粉紫 | #d63384 | `.buy_aux` / `.buy-aux` |
| sell（卖点） | 绿 | #2e8b57 | `.sell` |
| freeze（冰点） | 蓝 | #2563eb / #c62828 | `.freeze` |
| 买点失败 | 灰 | #9e9e9e | `.rule-dot-loss` |
| 无前买点 | 橙 | #ff9800 | `.rule-dot-noref` |

### 7.3 胜率配色梯度（6 档，色盲友好）

> 源文件：`web/style.css` `.chart-hint .wr`

| 区间 | class | 颜色 | 字重 |
|------|-------|------|------|
| ≥80 | wr-excellent | #15803d 深绿 | 700 |
| 70-79 | wr-good | #16a34a 中绿 | 700 |
| 60-69 | wr-fair | #65a30d 浅绿 | 600 |
| 50-59 | wr-neutral | #4e5969 中性灰 | 400 |
| 40-49 | wr-weak | #d97706 浅橙 | 400 |
| 30-39 | wr-poor | #ea580c 橙 | 600 |
| <30 | wr-bad | #dc2626 红 | 700 |

### 7.4 最大回撤三色分级（国人风格：红=好/绿=差）

> 源文件：`web/lab.js` `_labDdColor()` + `web/lab.css`

| 回撤区间 | 级别 | 颜色 | 色值 | CSS class |
|----------|------|------|------|-----------|
| <20% | good（回撤小=好） | 红 | #c92a2a | `.lab-matrix-good` |
| 20-40% | warn（一般） | 黄 | #ad6800 | `.lab-matrix-warn` |
| >40% | bad（回撤大=差） | 绿 | #2e7d32 | `.lab-matrix-bad` |

### 7.5 矩阵三色分级

> 源文件：`web/lab.css`

| 级别 | 背景色 | 文字色 | 语义 |
|------|--------|--------|------|
| good | #fff1f0（浅红底） | #c92a2a（红字） | 收益>5% / 胜率>55% |
| warn | #fffbe6（浅黄底） | #ad6800（黄字） | 中间 |
| bad | #f0f9eb（浅绿底） | #2e7d32（绿字） | 收益<-5% / 胜率<45% |

### 7.6 情绪标签颜色

> 源文件：`web/style.css`

| 标签 | 背景色 | 文字色 |
|------|--------|--------|
| 冰点(freeze) | #ffebee | #c62828 |
| 偏冷(cool) | #fff3e0 | #e65100 |
| 中性(neutral) | #f5f5f5 | #616161 |
| 偏热(warm) | #e8f5e9 | #2e7d32 |
| 过热(hot) | #c8e6c9 | #1b5e20 |

### 7.7 H5 移动端断点

| 断点 | 说明 |
|------|------|
| max-width: 768px | H5 模式开启（底部导航 + 顶部精简条 + 1/2 列网格） |
| max-width: 640px | chart-hint 字号缩小 |
| max-width: 720px | ov-2col 单列 |
| max-width: 600px | lab 策略列表单列 + sim stats 2 列 |

### 7.8 版本缓存破缓存

> 源文件：`scripts/bump_asset_version.py`

- CSS/JS 引用带 `?v=N` 参数
- 改样式后跑 `python scripts/bump_asset_version.py` 自增版本号
- 影响文件：web/index.html + static-site/index.html 中的 app.js / style.css / lab.js / lab.css / qr.js 引用

---

## 8 计算流水线（compute/runner.py）

> 源文件：`app/compute/runner.py`，15 步计算

| Step | 模块 | 输出 |
|------|------|------|
| 1 | sentiment | 6 个 per-index 情绪分（sz50/hs300/csi500/csi1000/cyb/kc50） |
| 2 | cross | 跨市场综合评分（cross_market） |
| 3 | signals | 买卖点信号（buy/buy_aux/sell + reason） |
| 4 | derived | 衍生指标（MA 排列/位置感等） |
| 5 | ad_line | AD Line（腾落线） |
| 6 | volume_ratio | 成交量比信号 |
| 7 | position | 市场位置感（1y/3y/5y 分位） |
| 8 | fear_greed | 恐贪指数（8 分量等权） |
| 9 | signal_stats | 信号频率统计（forward 收益） |
| 10 | new_high_low | 新高新低（NH-NL） |
| 11 | ma_alignment | 均线排列（多头/空头/交叉） |
| 12 | rotation | 板块轮动速度（5d/10d/20d） |
| 13-15 | （预留扩展） | |

---

## 9 前端状态参数

> 源文件：`web/app.js` `state` 对象

| 状态 | 默认值 | 说明 |
|------|--------|------|
| tab | overview | 当前主 Tab |
| range | 5y | 折线图数据范围（全/10y/5y/3y/1y） |
| subtab | a-stock | 大盘 Tab 二级页（a-stock/hk/global） |
| heatmapRange | all | 行业热力图模式（1d/5d/all） |
| labZone | buy | 策略实验室分区（buy/sell/excluded/prod） |
| labSimIdx | sh | 模拟回测指数 |
| labSimWindow | y1 | 模拟回测时间窗口（默认近1年） |
| labSimPairFi | D1_high20_drop5 | 全仓模式当前配对（买策略默认配 D1 卖） |
| labSimPairFk | D1_high20_drop5 | 定额模式当前配对 |
| labSimFiOpen | false | 全仓交易记录折叠 |
| labSimFkOpen | false | 定额交易记录折叠 |

### 9.1 周期选择器选项

| 值 | 显示 | 说明 |
|----|------|------|
| all | 全 | 全历史 |
| 10y | 10年 | 近10年 |
| 5y | 5年 | 近5年（默认） |
| 3y | 3年 | 近3年 |
| 1y | 1年 | 近1年 |

### 9.2 模拟回测交易记录分页

| 参数 | 值 |
|------|-----|
| perPage | 20 条/页 |
| 净值曲线 | SVG 降采样（MAX_CURVE_POINTS=100） |

---

## 10 配置文件参数

> 源文件：`config/indicators.yaml`（202 行）

### 10.1 指标配置字段

| 字段 | 说明 | 示例 |
|------|------|------|
| id | 指标唯一标识 | a_qvix_300 |
| name | 中文名 | A股300波动率 |
| group | 分组 | cn / hk / global / macro |
| type | 类型 | simple / derived |
| func | 采集函数 | direct: / tencent: / series: / snapshot |
| transform | 数据变换 | none / log / pct |
| scale | 缩放 | 1 / 100 |
| direction | 方向 | positive / negative |
| enabled | 是否启用 | true / false |
| drop_zero | 零值丢弃 | true（a_qvix_300 / a_qvix_1000） |

### 10.2 指标规模

| 类别 | 数量 | 说明 |
|------|------|------|
| 全局指标（metrics） | 35+ | 含利率/汇率/商品/波动率等 |
| A 股指数（indices） | 13 | sh/sz/hs300/sz50/csi500/csi1000/cyb/kc50/bj50 + 4 港股 |
| 港股指数 | 3 | 恒生指数/恒生科技/恒生国企 |
| 美股指数 | 4 | 标普500/纳指/道指/费城半导体 |
| 申万行业指数 | 31 | sw_801010 - sw_801980 |
| 概念板块 | 27 | 同花顺概念 |

### 10.3 全局指标列表（GLOBAL_METRIC_IDS）

> 源文件：`app/compute/signals.py`

```python
GLOBAL_METRIC_IDS = (
    "cn10y", "us10y", "wti_oil", "comex_silver",
    "gold", "oil", "usdcnh",
    "a_qvix_300", "a_qvix_1000", "cn_us_spread",
)
```

- `SKIP_IDS = {oil, usdcnh, cn_us_spread}`：结构异常，跳过信号计算
- `_STD_SELL_IDS = {usdcnh, cn_us_spread}`：用标准卖点逻辑

### 10.4 评分列表（SCORE_IDS）

> 源文件：`app/compute/signals.py`

```python
SCORE_IDS = (
    "cross_market", "a_sentiment",
    "sentiment_sz50", "sentiment_hs300",
    "sentiment_csi500", "sentiment_csi1000",
    "sentiment_cyb", "sentiment_kc50",
)
```

---

## 11 期货机构持仓参数

> 源文件：`app/collector/futures_position.py` + `app/compute/futures_position.py` + `web/app.js` `renderFuturesSection()`

### 11.1 采集参数

| 参数 | 值 |
|------|-----|
| 数据来源 | 中金所前 20 会员持仓 |
| 角色 | 机构(前20) / 中信期货 / 国泰君安 |
| 品种 | 沪深300期货(IF) / 中证500期货(IC) / 上证50期货(IH) / 中证1000期货(IM) / 综合 |
| 采集频率 | 每日（step 10 futures） |

### 11.2 准确率计算

> 源文件：`app/compute/futures_position.py` `compute_accuracy()`

| 参数 | 值 |
|------|-----|
| 滚动窗口 | 30d / 60d / 120d |
| 同向(follow) | 跟随机构方向做多/空，次日涨跌方向一致的比率 |
| 逆向(contrarian) | 反向操作，次日涨跌方向一致的比率 |
| 准确率阈值 | >55% 高亮（同向绿色 acc-good / 逆向橙色 acc-warn） |

### 11.3 前端展示

- 净多空概览表：正数=净多（绿色 #16a34a）/ 负数=净空（红色 #e6492e）
- 折线图：Y 轴万手，0 轴虚线，hover 显示当日准确率
- 准确率表：同向 >55% 绿色加粗 / 逆向 >55% 橙色加粗

---

## 12 策略实验室分区定义

> 源文件：`web/lab.js`

### 12.1 4 分区

| 分区 | label | 数量 | 说明 |
|------|-------|------|------|
| buy | 🧪 候选买点 | 7 | 候选买点策略（含 BB 下轨/Supertrend 实验中） |
| sell | 🧪 候选卖点 | 7 | 候选卖点策略（含 BB 上轨/MA 死叉实验中） |
| excluded | 📋 已排除 | 6 | 反面教材（回测不达标已弃用） |
| prod | ✅ 生产参考 | 2 | 已上线生产策略（C1/D1） |

### 12.2 状态标签

| 状态 | 标签 | CSS class | 背景色 | 文字色 |
|------|------|-----------|--------|--------|
| live | 已上线生产 | lab-tag-live | #e8f5e9 | #2e7d32 |
| experimental | 实验中 | lab-tag-exp | #f3e5f5 | #9c27b0 |
| dev | 开发中 | lab-tag-dev | #f5f5f5 | #757575 |
| excluded | 已排除 | lab-tag-excluded | #fbe9e7 | #bf360c |

### 12.3 回测矩阵

| 维度 | 值 |
|------|-----|
| 窗口（行） | 全史 / 近10年 / 近5年 / 近3年 / 近1年 |
| Horizon（列） | 5d / 10d / 20d / 60d |
| 统计指标 | 胜率 / 盈亏比 / 均值收益 / 样本数 |
| 达标线 | 胜率≥50%（border 红色 #c92a2a 高亮） |
| 三色分级 | good(红底) / warn(黄底) / bad(绿底) |

### 12.4 回测数据来源

- 矩阵数据：`lab_backtest.json`（全市场聚合）+ `lab_backtest_{index}.json`（per-index）
- 模拟回测：`lab_sim_{index}_stats.json`（小文件，stats+配对卡片）+ `lab_sim_{index}_full.json`（大文件，trades+equity_curve）
- 数据路径：web 版 `/static/data/lab/`，静态版 `./data/lab/`
- 大文件按需加载（fetchJSONProgress 带 HTTP 进度条）

---

## 13 监控与告警

> 源文件：`scripts/update_all.sh` + `scripts/notify.py`

| 触发条件 | 动作 |
|----------|------|
| 耗时 > 1 小时 | SEVERE=1，发严重告警邮件 + 写 alert_log |
| core 退出码非 0 | SEVERE=1，发严重告警邮件 + 写 alert_log |
| 正常完成 | 发完成通知邮件（含耗时/退出码/日志路径） |
| 指数补采三源均缺 | collect_log 写 warn 告警 |
| check_signals 失败 | 邮件失败不阻塞，不影响公网部署 |

---

## 附：关键文件索引

| 文件 | 用途 |
|------|------|
| app/db.py | SQLite 数据库定义（11 表 + WAL + busy_timeout） |
| app/compute/runner.py | 计算流水线编排（15 步） |
| app/compute/signals.py | 买卖点信号生成（RSI/BB/MACD/MA + per-index 过滤） |
| app/compute/sentiment.py | A 股综合情绪分 + per-index 情绪分 |
| app/compute/cross.py | 跨市场综合评分（trim_mean） |
| app/compute/fear_greed.py | 恐贪指数（8 分量等权） |
| app/compute/normalize.py | 归一化（rolling_percentile 120 日窗口） |
| app/compute/position.py | 市场位置感（1y/3y/5y 分位） |
| app/compute/ma_alignment.py | 均线排列（MA5/10/20/60） |
| app/compute/market_summary.py | 一句话总结 + 情绪标签（7 档） |
| app/compute/ad_line.py | AD Line（腾落线） |
| app/compute/volume_ratio.py | 成交量比信号（4 档） |
| app/compute/rotation.py | 板块轮动速度（5d/10d/20d） |
| app/compute/new_high_low.py | 新高新低（NH-NL） |
| app/compute/signal_stats.py | 信号 forward 收益统计 |
| app/compute/futures_position.py | 期货准确率计算 |
| app/collector/runner.py | 采集编排（11 步） |
| app/collector/index_backfill.py | 多源补采（9 核心 + 31 申万） |
| config/indicators.yaml | 指标配置（35+ 指标 + per-index 过滤） |
| a-stock-data/backtest_strategies.py | 22 策略定义 + 回测引擎 |
| scripts/lab/lab_simulate.py | 模拟配对回测（9 指数 × 64 配对 × 2 模式） |
| scripts/update_all.sh | 并行流水线编排（4 pipeline） |
| scripts/bump_asset_version.py | CSS/JS 版本号破缓存 |
| scripts/plists/*.plist | launchd 定时任务（15:33 + 20:00） |
| web/app.js | 前端主逻辑（2690 行） |
| web/lab.js | 策略实验室前端（2261 行） |
| web/style.css | 主样式（1465 行） |
| web/lab.css | 实验室样式（630 行） |
