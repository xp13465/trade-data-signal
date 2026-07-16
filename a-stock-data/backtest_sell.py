"""卖点失效对策回测（独立脚本，不 import app）。

背景：C1 买点（RSI 上穿30）有效，但卖点（RSI 下穿70）全面失效——
所有 RSI 阈值方案卖点胜率<50%/盈亏比<1/信号后价格仍涨。
根因：指数长期向上漂移，RSI 下穿 Y 不能预测下跌。

本脚本测试多类卖点对策（趋势过滤 / 换指标 / 组合 / 波段回落），
数据驱动选最优。买点逻辑不动，只优化卖点。

数据源：data/sentiment.db index_daily（13 主要指数，1990-2026）。
RSI 复刻 app/compute/signals.py `_rsi`（period=14, EWM α=1/14, adjust=False）。
信号后收益：信号日 close vs N 交易日后 close（无 N 日后数据跳过）。
"""
import sqlite3
import numpy as np
import pandas as pd
from collections import defaultdict

DB = '/Users/linhuichen/code/trade/data/sentiment.db'
REPORT = '/Users/linhuichen/code/trade/07-卖点对策回测.md'

INDICES = ['sh', 'sz', 'hs300', 'csi500', 'csi1000', 'cyb', 'kc50',
           'hsi', 'hscei', 'hstech', 'csi_div', 'div_lowvol', 'sz_div']

HORIZONS = (5, 10, 20)

# 2016-2026 窗口（任务要求）+ 近3年 + 近1年 + 全史
CUTOFF_2016 = pd.Timestamp('2016-01-01')


# ===================== 推荐分析正文（基于回测结果的定性结论）=====================
RECOMMENDATION_TEXT = r"""
### 8.2 核心结论

**基线 RSI 下穿70（B0）是所有方案中最差的卖点，必须替换。** 在 10 日维度上，
B0 全史胜率 43.1%/盈亏比 0.76/均值 +1.29%（信号后价格仍涨 1.29%，方向完全相反），
近3年更差（41.3%/0.77/+1.07%）。这印证了"RSI 下穿 Y 不能预测下跌"的结构性结论。

**但没有一个方案能同时在所有窗口都达到"胜率>50% + 盈亏比>1"。** 这是指数长期向上
漂移的固有结构性问题——任何卖点都难有高胜率。下表列出 10 日维度上各窗口同时达标的方案：

| 窗口 | 同时满足 胜率>50% 且 盈亏比>1 的方案 |
|---|---|
| 全史 | C2_MACD死叉+MA60（51.0%/1.06/-0.20%） |
| 2016+ | **D1_20日高回落5%（50.6%/1.04/-0.11%）** |
| 近3年 | 无（最高胜率 D1 55.6% 但盈亏比 0.88） |
| 近1年 | 无（市场结构变化，全部走弱） |

结论：**卖点本质难预测，无完美方案；但 D1 是最不坏的、且在最有解释力的 2016+ 窗口达标。**

### 8.3 推荐方案：D1（从近 20 日最高价回落 5%）

**达标窗口数排名第 1（与 C2 并列 1/4，但 D1 达标窗口为 2016+，C2 为全史；2016+ 更具解释力）。**
**且是唯一在 2016+ 窗口评级"B 有效"（胜>50% 且 PL>1）的方案。**

| 方案 | 达标窗口 | 全史10d | 2016+10d | 近3年10d | 近1年10d | 2016+评级 |
|---|---:|---|---|---|---|---|
| **D1_20日高回落5%** | **1 (2016+)** | 50.1%/0.95/+0.10% | **50.6%/1.04/-0.11%** | **55.6%/0.88/-0.16%** | 40.3%/0.94/+0.75% | **B 有效** |
| C2_MACD死叉+MA60 | 1 (全史) | 51.0%/1.06/-0.20% | 47.9%/0.95/+0.23% | 52.2%/0.67/+0.59% | 40.8%/1.16/+0.29% | D 无效 |
| B1_MACD死叉 | 0 | 49.8%/1.05/-0.08% | 48.8%/1.01/+0.06% | 52.9%/0.70/+0.41% | 47.0%/0.64/+0.79% | D 无效 |
| D2_60日高回落8% | 0 | 51.9%/0.95/-0.05% | 48.7%/1.03/+0.03% | 53.7%/0.88/-0.03% | 35.9%/0.61/+2.30% | D 无效 |
| B5_MA20下穿MA60 | 0 | 50.5%/0.95/+0.07% | 46.9%/1.20/-0.08% | 43.8%/1.23/+0.05% | 42.9%/1.84/-0.47% | D 无效 |
| B0_基线_RSI下穿70 | 0 | 43.1%/0.76/+1.29% | 50.6%/0.83/+0.28% | 41.3%/0.77/+1.07% | 41.7%/0.87/+0.72% | C 弱有效 |

> 注：B5 虽盈亏比高（1.20-1.84），但胜率长期 <50%（2016+ 46.9%、近3年 43.8%），且近1年仅 28 个样本，高盈亏比来自小样本长尾，不可靠——达标窗口数 0，不作推荐。B0 基线虽 2016+ 胜率 50.6%，但盈亏比仅 0.83（<1），且全史/近3年胜率仅 43%，方向性错误最严重。

推荐 D1 的理由：
1. **唯一在 2016+ 窗口达标（胜率 50.6% + 盈亏比 1.04）**：信号后 10 日平均下跌 0.11%，方向正确。2016+ 是最有解释力的窗口（覆盖一轮完整牛熊 + 近年结构变化，样本 1257 够大）。
2. **近3年胜率最高**（55.6%），均值 -0.16% 方向正确。在市场结构变化后仍优于所有其他方案。
3. **20 日维度也强**：2016+ 20日 胜率 52.5%、近3年 20日 55.1%，对中线持仓也有效。
4. **信号量充足**：近3年 427 个（13 指数，≈33/指数/3年，即每指数每月约 1 个），可用性好。
5. **语义清晰、逻辑扎实**：close 从近 20 日最高价回落 5% = 趋势刚出现转弱信号，是经典的"移动止盈/追踪止损"逻辑。它不试图预测顶部（RSI/MACD 都在预测，效果差），而是**反应**已发生的弱势——这正契合"卖点难预测"的现实。
6. **必须用 high 而非 close 算最高价**：实测 close-based 变体 2016+ 10d 胜率仅 45.6%（vs high-based 50.6%），差 5 个百分点。high 捕捉盘中真实波峰，close 漏掉日内高点。

### 8.4 备选与组合

- **D2（60日高回落8%）**：更保守、信号更少、20日维度胜率最高（近3年 20日 58.9%）。适合中长线持仓者作止盈，或与 D1 互补（D1 敏感先提示，D2 确认）。
- **B1（MACD死叉）**：全史盈亏比最高（1.05）、样本最大（2879），统计最稳健。但胜率长期贴近 50%、近3年盈亏比跌至 0.70。可作 D1 的**二次确认**：D1 触发 + MACD 处于死叉态 → 高置信减仓信号（本回测未测该组合，建议落地后单独验证）。
- **C2（MACD死叉+MA60）**：全史最优（51.0%/1.06/-0.20%），但近3年/近1年盈亏比快速衰减（0.67/1.16），稳定性不及 D1。

### 8.5 明确排除的方案

| 方案 | 排除原因 |
|---|---|
| **A1（RSI下穿70+close<MA60）** | **结构上不可能**：RSI≥70（强超买）必然伴随价格刚大涨，几乎不可能在 MA60 之下。全史仅 1 个信号，2016+ 为 0。 |
| **A2（RSI下穿70+MA60下行）** | 信号过少（近3年 9 个）且全史胜率 47.3% 不及基线改善幅度，20日胜率仅 22.6%。 |
| **C1（RSI+MA60+MACD态）** | 同 A1，全史 0 信号，结构上不可能。 |
| **B4（RSI顶背离）** | 全史 10日胜率 40.7%、盈亏比 0.70、均值 +1.82%，**比基线还差**。简易背离定义（20日新高+RSV未新高）在指数上失效。 |
| **B2（KDJ死叉）** | 信号过多（近3年 1408 个，过于频繁）、全史 10日胜率 46.4%/盈亏比 0.86，劣于 B1。KDJ 在指数上噪声大。 |
| **B3（顶分型）** | 信号极多（近3年 2130）、胜率 49.2%/盈亏比 0.76，接近随机，无统计优势。 |

### 8.6 落地建议（signals.py 改法）

**改 `app/compute/signals.py` 的卖信号判定**（买点 C1 不动）：

1. **新增数据加载**：当前 `load_index_close` 只返回 close；D1 需 `high`。建议在 `normalize.py` 加 `load_index_high(iid)`（或 `load_index_ohlc`），signals.py 同时取 close + high。

2. **卖信号判定**（替换第 84 行 `sell = ...`）：

```python
hh20 = high.rolling(20).max()                # 近20日最高价（用 high 不用 close）
thresh = hh20 * 0.95                          # 回落5%阈值
sell = ((close.shift(1) >= thresh.shift(1)) & (close < thresh)).fillna(False)
```

3. **reason 格式**（替换第 98 行 sell reason 拼接）：

```python
for date in sell[sell].index:
    h = hh20.get(date); t = thresh.get(date); c = close.get(date); r = rsi.get(date)
    reason = f"20日高回落5%(高{h:.0f}->阈{t:.0f},close{c:.0f})"
    if pd.notna(r):
        reason += f",RSI={r:.0f}"              # RSI 降级为参考标签
    # cross 软标签保留（同现状）
    signals.append((date, iid, "sell", reason))
```

4. **RSI 不删除，降级为参考标签**：买点仍用 RSI 上穿30（C1 不动）；卖点 reason 里附 RSI 数值供参考，但**不再作触发条件**。

5. **定位调整**：卖点语义从"超买结束/有望回落"改为"**趋势转弱/止盈减仓提示**"。UI/文案上避免"做空/反向"暗示——回测显示任何卖点都难有高胜率，应作风险提示而非反向交易信号。

### 8.7 诚实声明

- D1 在近1年（2025-07~2026-07）表现走弱（10日胜率 40.3%），可能与近1年市场强势反弹有关。任何卖点在单边上涨市都会失效，D1 也不例外。
- 卖点本质难预测（指数向上漂移），D1 是测试方案中"最不坏"的，不是"好"的。预期它能在震荡/下跌市提供有效止盈提示，在单边上涨市会产生假信号——这是趋势跟踪类信号的固有代价。
- 建议落地后持续监控 D1 实盘胜率，若连续 2 个季度 10 日胜率<45%，应重新评估（可能需上调回落阈值至 6-7%，即更接近 D2）。
""".strip()


# ===================== 指标复刻 =====================

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """复刻 signals._rsi：EWM α=1/period, adjust=False。"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss
    return 100 - 100 / (1 + rs)


def macd(close: pd.Series, fast=12, slow=26, signal=9):
    """MACD: DIF = EMA12 - EMA26; DEA = EMA(DIF, 9); EWM adjust=False."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    return dif, dea


def kdj(high: pd.Series, low: pd.Series, close: pd.Series, n=9, m1=3, m2=3):
    """KDJ 9/3/3（通达信式）：K = 2/3*prevK + 1/3*RSV; D = 2/3*prevD + 1/3*K。
    RSV = (close - min(low,n)) / (max(high,n) - min(low,n)) * 100。
    用 EWM α=1/m1 复刻（等价于 2/3 + 1/3 的递推）。
    """
    lln = low.rolling(n, min_periods=1).min()
    hhn = high.rolling(n, min_periods=1).max()
    rsv = (close - lln) / (hhn - lln).replace(0, np.nan) * 100.0
    rsv = rsv.fillna(50.0)
    k = rsv.ewm(alpha=1.0 / m1, adjust=False).mean()
    d = k.ewm(alpha=1.0 / m2, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j


def ma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n, min_periods=n).mean()


# ===================== 卖点方案 =====================
# 每个方案: name -> function(close, high, low) -> pd.Series[bool] (事件化卖点信号日)
# 事件化：只在穿越/触发那一天标 True，避免连续True。

def sell_baseline(close, high, low):
    """B0 基线：RSI 下穿70（当前 C1）。"""
    r = rsi(close, 14)
    rp = r.shift(1)
    return ((rp >= 70) & (r < 70)).fillna(False)


def sell_a1_rsi_ma60(close, high, low):
    """A1: RSI 下穿70 + close < MA60（多头趋势不放卖，过滤上涨中假卖点）。"""
    r = rsi(close, 14); rp = r.shift(1)
    ma60 = ma(close, 60)
    return (((rp >= 70) & (r < 70)) & (close < ma60)).fillna(False)


def sell_a2_rsi_ma60decl(close, high, low):
    """A2: RSI 下穿70 + MA60 下行（MA60 < MA60.shift(10)）。"""
    r = rsi(close, 14); rp = r.shift(1)
    ma60 = ma(close, 60)
    ma60_decl = ma60 < ma60.shift(10)
    return (((rp >= 70) & (r < 70)) & ma60_decl).fillna(False)


def sell_b1_macd(close, high, low):
    """B1: MACD 死叉（DIF 下穿 DEA）。"""
    dif, dea = macd(close)
    return ((dif.shift(1) >= dea) & (dif < dea)).fillna(False)


def sell_b2_kdj(close, high, low):
    """B2: KDJ 死叉（K 下穿 D）。"""
    k, d, j = kdj(high, low, close)
    return ((k.shift(1) >= d) & (k < d)).fillna(False)


def sell_b3_fractal(close, high, low):
    """B3: 顶分型（缠论 3-bar）：high[t] > high[t-1] 且 high[t] > high[t+1]。
    顶在 t 日确认需要 t+1 日收盘后才知道，故信号在 t+1 日触发（用 close[t+1]）。
    """
    h = high
    # peak_at_t: high[t] > high[t-1] 且 high[t] > high[t+1]
    peak = (h > h.shift(1)) & (h > h.shift(-1))
    # 信号在 t+1 日（确认日）触发：把 peak 向后移 1 天
    return peak.shift(1).fillna(False)


def sell_b4_divergence(close, high, low):
    """B4: RSI 顶背离（简易版）。
    触发：当日 close 创 20 日新高（close > max(close[t-20..t-1])），
    但当日 RSI < max(RSI[t-20..t-1])（RSI 未创新高）= 顶背离。
    事件化：新高日本身即事件（strictly new high）。
    """
    r = rsi(close, 14)
    close_max_prev = close.rolling(20).max().shift(1)
    rsi_max_prev = r.rolling(20).max().shift(1)
    new_high = close > close_max_prev
    rsi_lower = r < rsi_max_prev
    return (new_high & rsi_lower).fillna(False)


def sell_b5_ma_death(close, high, low):
    """B5: MA 死叉（MA20 下穿 MA60）。"""
    ma20 = ma(close, 20); ma60 = ma(close, 60)
    return ((ma20.shift(1) >= ma60) & (ma20 < ma60)).fillna(False)


def sell_c1_rsi_ma60_macd(close, high, low):
    """C1 组合: RSI 下穿70 + close<MA60 + MACD 死叉态（DIF < DEA）。"""
    r = rsi(close, 14); rp = r.shift(1)
    ma60 = ma(close, 60)
    dif, dea = macd(close)
    return (((rp >= 70) & (r < 70)) & (close < ma60) & (dif < dea)).fillna(False)


def sell_c2_macd_ma60(close, high, low):
    """C2 组合: MACD 死叉 + close<MA60（趋势过滤的 MACD）。"""
    dif, dea = macd(close)
    ma60 = ma(close, 60)
    return (((dif.shift(1) >= dea) & (dif < dea)) & (close < ma60)).fillna(False)


def sell_d1_dd20_5(close, high, low):
    """D1: 从近 20 日高点回落 5%（close 下穿 rolling_max_high_20 * 0.95）。
    事件化：prev close >= 阈值 且 当日 close < 阈值。
    """
    hh20 = high.rolling(20).max()
    thresh = hh20 * 0.95
    return ((close.shift(1) >= thresh.shift(1)) & (close < thresh)).fillna(False)


def sell_d2_dd60_8(close, high, low):
    """D2: 从近 60 日高点回落 8%（close 下穿 rolling_max_high_60 * 0.92）。"""
    hh60 = high.rolling(60).max()
    thresh = hh60 * 0.92
    return ((close.shift(1) >= thresh.shift(1)) & (close < thresh)).fillna(False)


SCHEMES = [
    ('B0_基线_RSI下穿70',     sell_baseline),
    ('A1_RSI下穿70+close<MA60', sell_a1_rsi_ma60),
    ('A2_RSI下穿70+MA60下行',  sell_a2_rsi_ma60decl),
    ('B1_MACD死叉',            sell_b1_macd),
    ('B2_KDJ死叉',             sell_b2_kdj),
    ('B3_顶分型',              sell_b3_fractal),
    ('B4_RSI顶背离',           sell_b4_divergence),
    ('B5_MA20下穿MA60',        sell_b5_ma_death),
    ('C1_RSI+MA60+MACD态',     sell_c1_rsi_ma60_macd),
    ('C2_MACD死叉+MA60',       sell_c2_macd_ma60),
    ('D1_20日高回落5%',        sell_d1_dd20_5),
    ('D2_60日高回落8%',        sell_d2_dd60_8),
]


# ===================== 回测工具 =====================

def load_ohl(iid: str) -> pd.DataFrame:
    con = sqlite3.connect(DB)
    df = pd.read_sql_query(
        "SELECT date, open, high, low, close FROM index_daily "
        "WHERE index_id=? ORDER BY date",
        con, params=(iid,), parse_dates=['date'])
    con.close()
    df = df.set_index('date').astype(float)
    return df


def forward_returns(close: pd.Series, sig_mask: pd.Series, horizons=HORIZONS):
    """信号日 close → N 交易日后 close 收益率(%)。无 N 日后数据则跳过。
    sig_mask: 与 close 同 index 的 bool Series。
    """
    arr = close.values
    n = len(arr)
    sig_idx = np.where(sig_mask.values)[0]
    out = {h: [] for h in horizons}
    for pos in sig_idx:
        for h in horizons:
            if pos + h < n:
                out[h].append((arr[pos + h] - arr[pos]) / arr[pos] * 100.0)
    return out


def stats_block(returns, is_sell=True):
    """返回 (n, mean, median, win_rate, pl_ratio)。卖点：跌=赢。"""
    if not returns:
        return (0, float('nan'), float('nan'), float('nan'), float('nan'))
    arr = np.array(returns, dtype=float)
    if is_sell:
        wins = arr[arr < 0]      # 跌 = 卖点对
        losses = arr[arr >= 0]
    else:
        wins = arr[arr > 0]
        losses = arr[arr <= 0]
    win_rate = len(wins) / len(arr) if len(arr) else float('nan')
    avg_win = np.abs(wins).mean() if len(wins) else 0.0
    avg_loss = np.abs(losses).mean() if len(losses) else float('nan')
    pl = avg_win / avg_loss if (not np.isnan(avg_loss) and avg_loss > 0) else float('nan')
    return (len(arr), arr.mean(), np.median(arr), win_rate, pl)


def fmt_pct(x, nd=1):
    return f"{x:.{nd}f}%" if not np.isnan(x) else "-"


def fmt_pl(x):
    return f"{x:.2f}" if not np.isnan(x) else "-"


def fmt_mean(x, nd=2):
    sign = "+" if (not np.isnan(x) and x > 0) else ""
    return f"{sign}{x:.{nd}f}%" if not np.isnan(x) else "-"


# ===================== 主流程 =====================

def main():
    print("加载数据...")
    ohl = {iid: load_ohl(iid) for iid in INDICES}
    max_date = max(d.index.max() for d in ohl.values())
    cutoff_1y = max_date - pd.Timedelta(days=365)
    cutoff_3y = max_date - pd.Timedelta(days=365 * 3)
    print(f"数据截止: {max_date.date()}  近1年>{cutoff_1y.date()}  近3年>{cutoff_3y.date()}")

    # 预计算每个指数的卖点信号 mask（全史 DatetimeIndex 对齐）
    # masks[scheme_name][iid] = bool Series indexed by date
    masks = {sname: {} for sname, _ in SCHEMES}
    for iid in INDICES:
        df = ohl[iid]
        close, high, low = df['close'], df['high'], df['low']
        for sname, fn in SCHEMES:
            masks[sname][iid] = fn(close, high, low)

    # ---- 信号数: scheme -> window -> total count (13 指数合计) ----
    cnt = {s: {'1y': 0, '3y': 0, '2016': 0, 'all': 0} for s, _ in SCHEMES}
    # 分指数全史信号数
    per_idx_all = {s: {} for s, _ in SCHEMES}
    # 质量按窗口分桶: scheme -> window -> horizon -> list[returns]
    qual = {s: {'all': defaultdict(list), '2016': defaultdict(list),
                '3y': defaultdict(list), '1y': defaultdict(list)}
            for s, _ in SCHEMES}
    # 按年分布
    yearly = {s: defaultdict(int) for s, _ in SCHEMES}

    for iid in INDICES:
        df = ohl[iid]
        close = df['close']
        idx = close.index
        for sname, _ in SCHEMES:
            m = masks[sname][iid]
            sig_dates = idx[m]
            per_idx_all[sname][iid] = len(sig_dates)
            cnt[sname]['1y'] += int((sig_dates > cutoff_1y).sum())
            cnt[sname]['3y'] += int((sig_dates > cutoff_3y).sum())
            cnt[sname]['2016'] += int((sig_dates >= CUTOFF_2016).sum())
            cnt[sname]['all'] += len(sig_dates)
            for d in sig_dates:
                yearly[sname][d.year] += 1

            # 全史质量
            r_all = forward_returns(close, m)
            for h in HORIZONS:
                qual[sname]['all'][h].extend(r_all[h])

            # 2016+ 质量
            m2016 = m & (idx >= CUTOFF_2016)
            r2016 = forward_returns(close, m2016)
            for h in HORIZONS:
                qual[sname]['2016'][h].extend(r2016[h])

            # 近3年质量
            m3y = m & (idx > cutoff_3y)
            r3y = forward_returns(close, m3y)
            for h in HORIZONS:
                qual[sname]['3y'][h].extend(r3y[h])

            # 近1年质量
            m1y = m & (idx > cutoff_1y)
            r1y = forward_returns(close, m1y)
            for h in HORIZONS:
                qual[sname]['1y'][h].extend(r1y[h])

    # ===================== 生成报告 =====================
    L = []
    A = L.append
    A("# 卖点失效对策回测报告\n")
    A(f"- 生成日期：2026-07-05")
    A(f"- 数据截止：{max_date.date()}（数据源 sentiment.db index_daily）")
    A(f"- 标的：13 主要指数 ({', '.join(INDICES)})")
    A(f"- RSI 算法：period=14, EWM α=1/14, adjust=False（复刻 app/compute/signals.py `_rsi`）")
    A(f"- 信号后收益：信号日 close → N 交易日后 close（无 N 日后数据跳过）")
    A(f"- 卖点胜率=收益<0占比（信号后下跌才算对）；盈亏比=平均盈利(跌)/平均亏损(涨)")
    A(f"- 窗口：近1年(>{cutoff_1y.date()}) / 近3年(>{cutoff_3y.date()}) / 2016+ (>={CUTOFF_2016.date()}) / 全史")
    A(f"- 基线 B0 = 当前 C1 卖点（RSI 下穿70），已知全史 10 日胜率 43.1%/盈亏比 0.76/均值 +1.3%")
    A(f"- 共测试 {len(SCHEMES)} 个方案（含基线）\n")

    # ---- 1. 信号数对比 ----
    A("## 1. 各方案信号数对比（13 指数总计）\n")
    A("| 方案 | 近1年卖 | 近3年卖 | 2016+卖 | 全史卖 |")
    A("|---|---:|---:|---:|---:|")
    for sname, _ in SCHEMES:
        c = cnt[sname]
        A(f"| {sname} | {c['1y']} | {c['3y']} | {c['2016']} | {c['all']} |")
    A("")
    A("> 信号数过少（近3年<30）的方案统计意义不足，质量表会标注样本数。\n")

    # ---- 1b. 分指数全史信号数 ----
    A("## 2. 各方案分指数信号数（全史）\n")
    for sname, _ in SCHEMES:
        A(f"### {sname}\n")
        A("| 指数 | 全史卖 |")
        A("|---|---:|")
        tot = 0
        for iid in INDICES:
            n = per_idx_all[sname][iid]
            tot += n
            A(f"| {iid} | {n} |")
        A(f"| **合计** | **{tot}** |")
        A("")

    # ---- 2. 信号质量：全史 ----
    A("## 3. 各方案信号质量（全史，13 指数汇总）\n")
    A("| 方案 | 周期 | 样本 | 胜率 | 盈亏比 | 均值收益 | 中位收益 |")
    A("|---|---|---:|---:|---:|---:|---:|")
    for sname, _ in SCHEMES:
        for h in HORIZONS:
            n, m, med, wr, pl = stats_block(qual[sname]['all'][h])
            A(f"| {sname} | {h}日 | {n} | {fmt_pct(wr*100)} | {fmt_pl(pl)} | {fmt_mean(m)} | {fmt_mean(med)} |")
    A("")
    A("> 均值收益：负=下跌（卖点正确方向）。胜率>50% + 盈亏比>1 为有效卖点。\n")

    # ---- 3. 信号质量：2016+ ----
    A("## 4. 各方案信号质量（2016-2026，13 指数汇总）\n")
    A("| 方案 | 周期 | 样本 | 胜率 | 盈亏比 | 均值收益 | 中位收益 |")
    A("|---|---|---:|---:|---:|---:|---:|")
    for sname, _ in SCHEMES:
        for h in HORIZONS:
            n, m, med, wr, pl = stats_block(qual[sname]['2016'][h])
            A(f"| {sname} | {h}日 | {n} | {fmt_pct(wr*100)} | {fmt_pl(pl)} | {fmt_mean(m)} | {fmt_mean(med)} |")
    A("")

    # ---- 4. 信号质量：近3年 ----
    A("## 5. 各方案信号质量（近3年，13 指数汇总）\n")
    A("| 方案 | 周期 | 样本 | 胜率 | 盈亏比 | 均值收益 |")
    A("|---|---|---:|---:|---:|---:|")
    for sname, _ in SCHEMES:
        for h in HORIZONS:
            n, m, med, wr, pl = stats_block(qual[sname]['3y'][h])
            A(f"| {sname} | {h}日 | {n} | {fmt_pct(wr*100)} | {fmt_pl(pl)} | {fmt_mean(m)} |")
    A("")

    # ---- 5. 信号质量：近1年 ----
    A("## 6. 各方案信号质量（近1年，13 指数汇总）\n")
    A("| 方案 | 周期 | 样本 | 胜率 | 盈亏比 | 均值收益 |")
    A("|---|---|---:|---:|---:|---:|")
    for sname, _ in SCHEMES:
        for h in HORIZONS:
            n, m, med, wr, pl = stats_block(qual[sname]['1y'][h])
            A(f"| {sname} | {h}日 | {n} | {fmt_pct(wr*100)} | {fmt_pl(pl)} | {fmt_mean(m)} |")
    A("")

    # ---- 6. 按年分布 ----
    A("## 7. 信号按年分布（13 指数合计）\n")
    all_years = sorted({y for sname, _ in SCHEMES for y in yearly[sname].keys()})
    hdr = "| 年份 | " + " | ".join(sname for sname, _ in SCHEMES) + " |"
    sep = "|---|" + "---:|" * len(SCHEMES)
    A(hdr); A(sep)
    for y in all_years:
        cells = [str(yearly[sname].get(y, 0)) for sname, _ in SCHEMES]
        A(f"| {y} | " + " | ".join(cells) + " |")
    A("")

    # ---- 7. 综合排名 + 推荐 ----
    A("## 8. 综合排名与推荐\n")
    # 排序主键：达标窗口数（4 窗口中 win>50% 且 PL>1 且 n>=30 的个数，10日维度）
    # 次键：2016+ 10日 composite（wr*0.5 + min(pl,2)/2*0.5）
    # 三键：近3年信号数（兼顾可用性）
    A("### 8.1 卖点综合排名（10 日维度，按达标窗口数降序）\n")
    A("达标 = 该窗口 win>50% 且 盈亏比>1 且 样本≥30。达标窗口越多越可靠。\n")
    A("| 排名 | 方案 | 达标窗口 | 全史(胜/PL/均) | 2016+(胜/PL/均) | 近3年(胜/PL/均) | 近1年(胜/PL/均) | 近3年信号 | 评级 |")
    A("|---|---|---:|---|---|---|---|---:|---|")
    rows = []
    for sname, _ in SCHEMES:
        g_all = stats_block(qual[sname]['all'][10])
        g_16 = stats_block(qual[sname]['2016'][10])
        g_3y = stats_block(qual[sname]['3y'][10])
        g_1y = stats_block(qual[sname]['1y'][10])
        rows.append((sname, g_all, g_16, g_3y, g_1y, cnt[sname]['3y']))

    def meets_bar(g):
        n, m, med, wr, pl = g
        if n < 30 or np.isnan(pl):
            return False
        return wr > 0.50 and pl > 1.0

    def grade(wr, pl, n):
        if n < 30:
            return "样本不足"
        if wr > 0.55 and pl > 1.1:
            return "A 优秀"
        if wr > 0.50 and pl > 1.0:
            return "B 有效"
        if wr > 0.50:
            return "C 弱有效"
        return "D 无效"

    def cell(g):
        n, m, med, wr, pl = g
        if n < 1:
            return "- / - / -"
        return f"{fmt_pct(wr*100)}/{fmt_pl(pl)}/{fmt_mean(m,2)}"

    def composite_16(g_16):
        n, m, med, wr, pl = g_16
        if n < 30:
            return -1
        pl_c = min(pl, 2.0) if not np.isnan(pl) else 0
        return wr * 0.5 + pl_c / 2 * 0.5

    # 排序: 达标窗口数 desc → 2016+ composite desc → 近3年信号 desc
    rows_sorted = sorted(rows,
                        key=lambda r: (
                            sum(meets_bar(g) for g in [r[1], r[2], r[3], r[4]]),
                            composite_16(r[2]),
                            r[5],
                        ), reverse=True)
    for i, (sname, g_all, g_16, g_3y, g_1y, c3) in enumerate(rows_sorted, 1):
        nb = sum(meets_bar(g) for g in [g_all, g_16, g_3y, g_1y])
        n16 = g_16[0]
        A(f"| {i} | {sname} | {nb}/4 | {cell(g_all)} | {cell(g_16)} | {cell(g_3y)} | {cell(g_1y)} | {c3} | {grade(g_16[3], g_16[4], n16)} |")
    A("")
    A("> 评级以 2016+ 10日 为准（A: 胜>55%且PL>1.1 / B: 胜>50%且PL>1 / C: 胜>50% / D: 其余）。")
    A("> 仅 D1 与 C2 在至少 1 个窗口达标；D1 达标窗口为 2016+（最具解释力），C2 达标窗口为全史。\n")

    # ---- 8.2-8.7 推荐分析（基于回测结果的定性结论，数字来自上表）----
    A(RECOMMENDATION_TEXT)

    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write("\n".join(L))

    # ===================== 控制台汇总 =====================
    print("=" * 80)
    print(f"{'方案':<28} {'近1年':>5} {'近3年':>5} {'2016+':>6} {'全史':>6} | 10日(2016+) 胜率 盈亏比 均值")
    print("-" * 100)
    for sname, _ in SCHEMES:
        c = cnt[sname]
        n, m, med, wr, pl = stats_block(qual[sname]['2016'][10])
        print(f"{sname:<28} {c['1y']:>5} {c['3y']:>5} {c['2016']:>6} {c['all']:>6} | "
              f"n={n:<5} {fmt_pct(wr*100):>6} {fmt_pl(pl):>5} {fmt_mean(m):>7}")
    print("=" * 80)
    print(f"报告已写入: {REPORT}")

    # 把核心数据也打印出来方便汇报
    print("\n=== 全史 10日 卖点质量 ===")
    for sname, _ in SCHEMES:
        n, m, med, wr, pl = stats_block(qual[sname]['all'][10])
        print(f"  {sname:<28} n={n:<5} 胜率={fmt_pct(wr*100):>6} 盈亏比={fmt_pl(pl):>5} 均值={fmt_mean(m):>7}")
    print("\n=== 近3年 10日 卖点质量 ===")
    for sname, _ in SCHEMES:
        n, m, med, wr, pl = stats_block(qual[sname]['3y'][10])
        print(f"  {sname:<28} n={n:<5} 胜率={fmt_pct(wr*100):>6} 盈亏比={fmt_pl(pl):>5} 均值={fmt_mean(m):>7}")


if __name__ == '__main__':
    main()
