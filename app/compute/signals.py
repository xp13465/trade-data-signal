"""§7 买点/卖点：买=RSI 事件化（C1）+ BB下轨回归辅买点（B1），卖=20日高回落5%（D1）
叠加 MA60 多头过滤（S1）+ MACD 死叉确认（DIF<DEA，方案 B 2026-07-05）。

买点（C1 主买 + B1 辅买，2026-07-05 B1+S1 优化）：
- C1 主买点 signal='buy' 不变：RSI(14) 上穿 30（前一日≤30 且当日>30，超卖结束、有望反弹）。
- B1 辅买点 signal='buy_aux'：BB 下轨回归（前一日 close<下轨 且当日 close>下轨，从超卖
  区反弹回下轨之上）。语义与 C1 同为「超卖反弹」，强势市更敏感，互补 C1 盲区。
  - BB：mid=close.rolling(20).mean(), sd=close.rolling(20).std(ddof=0), bu=mid+2σ, bl=mid-2σ。
  - C1 与 BB 同日触发时去重：保留 C1（主买优先），不重复发 buy_aux。
  - buy_aux 也算买点：更新 last_buy_close 游标 + 参与 vs前买 标注。

卖点（D1 + S1 MA60 多头过滤 + MACD 死叉确认，2026-07-05 方案 B）：
- D1 触发逻辑保留：close 从近 20 日最高价（high-based）回落 5%。
- S1 过滤：仅当 close > MA60（60 日均线，多头趋势）才放卖——砍下跌趋势中的假卖点
  （熊市噪声）。回测降噪率 39%（全史卖点 59830→36289）。
- MACD 死叉确认（方案 B，2026-07-05）：D1+S1 基础上加 DIF<DEA（动量转弱确认），
  过滤「强趋势中回调假摔」型假信号。回测 sell 凯利建议率 18.3%→43.3%（11→26 个建议）。
  **s.* 情绪分序列豁免**（a_sentiment 加 MACD 后 n=106→7 样本不足），保留原 D1+S1。
- MA60：close.rolling(60, min_periods=60).mean()。MA60 为 NaN（前 60 日）时 close>MA60
  为 False，自动不放卖（与 min_periods=60 一致）。
- MACD(12,26,9)：DIF=EMA(close,12)-EMA(close,26)，DEA=EMA(DIF,9)，EMA 用 ewm(span=N, adjust=False)。
- reason 末尾附 MA60 标签 + MACD[死叉确认] 标签：`MA60={m:.0f}[趋势过滤] MACD=DIF{d}/DEA{e}[死叉确认]`。

事件化：只在「穿越」那一天标，一次连续超卖/超买期只产 1 个点
（RSI 反复进出超卖/超买区则每次退出各 1 个点，算独立事件）。

cross 不再作硬门槛过滤，而是分级标签附在 reason 末尾供参考：
<30 冰点 / 30-50 偏冷 / 50-70 中性 / 70-80 偏热 / >=80 狂热。

阈值定义（语义）：
- 买触发 rsi_prev<=30 且 rsi>30（基线）：前一日在超卖区（含边界）、当日升回 30 之上 = 超卖结束
  per-index buy_filter=rsi_cross_25 时改为 rsi_prev<=25 且 rsi>25（更宽松、更早捕捉超卖反弹）
- 辅买触发 close_prev<bl_prev 且 close>bl：前一日跌破下轨、当日收回下轨之上 = 超卖反弹
- 卖触发 close_prev>=thresh 且 close<thresh：前一日还在阈之上、当日跌破阈 = 趋势转弱
  且 close>MA60：多头趋势中（过滤熊市假卖点）

C1 变更（2026-07-06）：原 E1 逻辑要求买 cross<30、卖 cross>70 作共振硬门槛，
近年市场宽度结构变化致 cross 多在 30-70 中性区，近端买点长期 0、卖点也偏少。
改为 RSI 事件为主、cross 软分级标签化，恢复信号可用性。

D1 变更（2026-07-06）：C1 卖点用 RSI 下穿70，回测显示全史 10日胜率仅 43.1%/盈亏比
0.76/均值 +1.29%（信号后价格仍涨，方向相反），是最差的卖点。改 D1=20日高回落5%
（high-based），2016+ 10日胜率 50.6%/盈亏比 1.04，是回测 12 方案中唯一在 2016+
窗口达标的卖点。RSI 在卖点降级为参考标签附在 reason（不作触发）；买点 RSI 不动。

方案 B 标注（2026-07-06）：卖点 reason 附 `vs前买{±X.XX%}[分类]` 标签，标注相对
最近一次前置买点 close 的盈亏，便于用户判断卖点质量与操作建议。**只加标注，不改
触发条件**。B1+S1 后 buy_aux 也更新 last_buy_close 游标（buy_aux 也是买点）。
- 维护 `last_buy_close` 游标（每个 index_id 独立，按 date 升序遍历）：遇到 buy 或
  buy_aux 信号时更新 last_buy_close=该买点 close。
- 卖点触发时：close > 前买点 close → `vs前买+X.XX%[止盈]`（前端绿）；close < 前买点
  close → `vs前买-X.XX%[买点失败]`（前端灰，操作建议止损观望）；窗口内无前置买点
  → `无前买点[趋势中]`（前端橙）。
- 例：`20日高回落5%(高8864->阈8421,close8300), RSI=33, cross=55[中性], MA60=8200[趋势过滤], vs前买-2.32%[买点失败]`

B1+S1 变更（2026-07-05）：买点加 BB 下轨回归辅买点（buy_aux，与 C1 互补，回测买点
15007→38547 翻 2.57×）；卖点叠加 MA60 多头过滤（砍下跌趋势假卖点，回测卖点
59830→36289 砍 39%）。组合卖/买比 3.99→0.94（买卖平衡）。详见 `11-买卖点优化方案回测.md`。

Per-index buy_aux 增强（2026-07-05，配置化）：`config/indicators.yaml` 给单个指数加
`buy_aux_filter` 字段即可叠加增强过滤（未配置的走基线 B1）。当前 sw_801110 家用电器配置
`buy_aux_filter: rsi_cross_40` = BB下轨回归 ∧ RSI(14) 上穿40（rp≤40 & r>40，与 C1 上穿30
对称，价格反弹+动量转升双维确认）。回测 sw_801110 buy_aux 10d 凯利 f -38.5%→+16.2% 转正，
胜率 44.8%→54.5%，盈亏比 0.66→1.19，n 134→33，三 horizon（5d/10d/20d）一致转正
（+19.1%/+16.2%/+17.1%），稳健非偶发。详见 `14-家电buy_aux优化回测.md`。其他 59 品类
buy_aux 不动（基线 B1），后续逐品类验证后各自加方案。reason 加 `RSI[上穿40]` 段。

Per-index buy 主买点 RSI 阈值收紧（2026-07-08，配置化）：`config/indicators.yaml` 给单个
指数加 `buy_filter` 字段即可收紧 C1 主买 RSI 阈值（未配置走基线 RSI 上穿 30）。
当前 kc50 科创50、sw_801730 电力设备、sw_801760 传媒 配置 `buy_filter: rsi_cross_25`
= RSI(14) 上穿 25（rp≤25 & r>25，比基线 30 更宽松、更早捕捉超卖反弹）。回测三品类
10d 凯利 f 显著改善：kc50 15.92%→57.56%、sw_801730 0%→29.55%、sw_801760 0%→41.74%。
详见 `22-buy收紧RSI回测-21个不建议.md`。其他 57 品类 buy 不动（基线 RSI 上穿 30），
后续逐品类验证后各自加方案。reason 格式改为 `RSI上穿25(...)`（标注实际阈值）。
"""
import pandas as pd

from .normalize import load_index_amount, load_index_close, load_index_high, load_metric_value, load_score_value
from ..collector.fetchers import load_config
from ..db import get_conn


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss
    return 100 - 100 / (1 + rs)


def _bollinger(close: pd.Series, window: int = 20, n_std: float = 2.0):
    """布林带：mid=MA(window), sd=std(ddof=0), bu=mid+n_std*sd, bl=mid-n_std*sd。

    与 11-买卖点优化方案回测.md 一致（std ddof=0）。返回 (bu, mid, bl)。
    """
    mid = close.rolling(window).mean()
    sd = close.rolling(window).std(ddof=0)
    bu = mid + n_std * sd
    bl = mid - n_std * sd
    return bu, mid, bl


# === 国债三品种波段仓位管理策略（2026-07-24 上线）===
# 回测依据: /tmp/backtest_cgb_band.py + /tmp/cgb_band_results.json best_params.{品种}.all.params
# 回测验证: cgb_idx 降风险(年化3.57%->3.23% 微降,回撤-10.4%->-4.8% 大降,夏普2.80->3.58);
#           cgb_10y_etf 放宽双赢(年化3.50%->3.24% 微降,回撤-4.62%->-3.62% 降,夏普1.31->1.52);
#           cgb_10y_future 双赢(年化1.30%->1.63% 升,回撤-6.80%->-2.37% 大降,夏普0.42->1.58)。
# 替代原 D1 卖点(20日高回落5%)对国债完全失效(sell=0 无理由)的问题:国债波动小,D1 从未触发。
# 波段策略用 RSI+乖离+布林三指标,减仓/接回/止损三动作,实盘化每日独立判断。
CGB_BAND_PARAMS = {
    "cgb_idx": {
        "bias_th": 0.003, "rsi_high": 65, "rsi_low": 35,
        "ratio1": 0.2, "ratio2": 0.5, "ratio3": 0.3,
    },
    "cgb_10y_etf": {
        "bias_th": 0.003, "rsi_high": 70, "rsi_low": 35,
        "ratio1": 0.3, "ratio2": 0.5, "ratio3": 0.3,
    },
    "cgb_10y_future": {
        "bias_th": 0.003, "rsi_high": 65, "rsi_low": 25,
        "ratio1": 0.5, "ratio2": 0.2, "ratio3": 0.3,
    },
}


def compute_band_signal(index_id: str, params: dict) -> list[dict]:
    """国债波段仓位管理信号（实盘化，全历史每天1条，每日独立判断，返回信号 list[dict]）。

    读 index_daily 全量历史 cgb 品种收盘价（前60天 MA60 暖机，其后每天算信号），算指标，
    遍历 MA60 暖机后每天算信号。指标与回测 /tmp/backtest_cgb_band.py 一致:
    - MA20/MA60 乖离: bias20=close/MA20-1, bias60=close/MA60-1
    - RSI14: EWM α=1/14 adjust=False（复刻 _rsi）
    - 布林(20,2σ): rolling(20).std(ddof=1, 与回测一致; signals._bollinger 用 ddof=0 是另一套口径)

    动作条件(回测 L103-105, 实盘化去掉 last_action 防连续, 每天独立判断给方向+比例):
    - 减仓: (bias20>bias_th AND rsi>rsi_high) OR close>=bb_up -> 减 ratio1
    - 接回: (rsi<rsi_low AND |bias60|<0.02) OR close<=bb_low -> 接 ratio2
    - 止损: close<MA60*0.98 -> 减 ratio3
    - 持有: 无以上

    实盘化「不看历史仓位」= 不依赖回测的 pos/cash/last_action 状态，每天独立给当前状态。
    （实盘只需当前状态提示，历史回溯用回测结果 /tmp/cgb_band_results.json）

    返回 list[dict]（全历史每天1条，升序；数据不足返回 []）。每条 dict:
      {date, signal, reason, ratio, rsi, bias20, bias60, bb_pos}
      signal: "减仓"/"接回"/"止损"/"持有"
      date: 交易日(YYYYMMDD 字符串, 与 signal_daily 主键一致)

    2026-07-24 修复: 原只返回最新1天 dict|None, store() DELETE 重算致历史波段信号每天被
    覆盖(sell减仓次日消失)。改为返回全历史 list,与其他信号(buy/sell等算全历史)一致,
    signal_daily 保留历史波段信号,前端走势图可回放历史减仓/接回时点。
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT date, close FROM index_daily WHERE index_id=? AND close IS NOT NULL "
        "ORDER BY date DESC",
        (index_id,),
    ).fetchall()
    conn.close()
    if len(rows) < 60:
        return []
    # 按日期升序（DB 取出是 DESC，反转）
    rows = list(reversed(rows))
    dates = [r[0] for r in rows]
    closes = [float(r[1]) for r in rows]
    close = pd.Series(closes, index=dates)

    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60, min_periods=60).mean()
    bias20 = (close - ma20) / ma20
    bias60 = (close - ma60) / ma60
    rsi = _rsi(close, 14)
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()  # ddof=1 与回测一致（backtest_cgb_band.py L51 默认）
    bb_up = bb_mid + 2.0 * bb_std
    bb_low = bb_mid - 2.0 * bb_std
    bb_pos = (close - bb_low) / (bb_up - bb_low)

    bias_th = params["bias_th"]
    rsi_high = params["rsi_high"]
    rsi_low = params["rsi_low"]
    ratio1 = params["ratio1"]
    ratio2 = params["ratio2"]
    ratio3 = params["ratio3"]

    out: list[dict] = []
    # 从 index 60 开始（前60天 MA60 暖机），算最后60天每天信号（与回测 dropna(ma60) 后等价）
    #
    # 性能优化（2026-07-25）：原逐日 close.iloc[i]/rsi.iloc[i]/... 读 7 个 pandas Series，
    # 3 CGB 指数 × ~4000 天 × 7 .iloc[] = ~84k 次 pandas indexing 开销（cProfile 实测 0.7s）。
    # 改为 numpy 数组下标读取（arr[i] O(1) 无包装），算法/输出完全一致。
    import numpy as np
    c_arr = close.to_numpy(dtype=float)
    r_arr = rsi.to_numpy(dtype=float)
    b20_arr = bias20.to_numpy(dtype=float)
    b60_arr = bias60.to_numpy(dtype=float)
    m60_arr = ma60.to_numpy(dtype=float)
    bu_arr = bb_up.to_numpy(dtype=float)
    bl_arr = bb_low.to_numpy(dtype=float)
    bp_arr = bb_pos.to_numpy(dtype=float)
    for i in range(60, len(rows)):
        c = c_arr[i]
        r = r_arr[i]
        b20 = b20_arr[i]
        b60 = b60_arr[i]
        m60 = m60_arr[i]
        bu = bu_arr[i]
        bl = bl_arr[i]
        bp = bp_arr[i]
        d = dates[i]
        if np.isnan(c) or np.isnan(r) or np.isnan(b20) or np.isnan(b60) or np.isnan(m60) or np.isnan(bu) or np.isnan(bl):
            continue

        reduce_sig = (b20 > bias_th and r > rsi_high) or (c >= bu)
        rebuy_sig = (r < rsi_low and abs(b60) < 0.02) or (c <= bl)
        stop_sig = c < m60 * 0.98

        if stop_sig:
            signal = "止损"
            ratio = ratio3
            drop_pct = (c - m60) / m60 * 100
            reason = (f"波段止损{int(ratio * 100)}%: 跌破MA60支撑"
                      f"(MA60={m60:.2f},close={c:.2f},跌幅{drop_pct:.2f}%)")
        elif reduce_sig:
            signal = "减仓"
            ratio = ratio1
            triggers = []
            if b20 > bias_th and r > rsi_high:
                triggers.append(f"RSI{r:.0f}超买+bias20 {b20 * 100:.2f}%")
            if c >= bu:
                triggers.append("触布林上轨")
            reason = f"波段减仓{int(ratio * 100)}%: " + "+".join(triggers)
        elif rebuy_sig:
            signal = "接回"
            ratio = ratio2
            triggers = []
            if r < rsi_low and abs(b60) < 0.02:
                triggers.append(f"RSI{r:.0f}超卖+乖离回归")
            if c <= bl:
                triggers.append("触布林下轨")
            reason = f"波段接回{int(ratio * 100)}%: " + "+".join(triggers)
        else:
            signal = "持有"
            ratio = 0.0
            bp_str = f"{bp * 100:.0f}%" if not np.isnan(bp) else "NA"
            reason = (f"波段持有: 无超买超卖信号"
                      f"(RSI{r:.0f},bias20 {b20 * 100:.2f}%,BB位{bp_str})")

        out.append({
            "date": d,
            "signal": signal,
            "reason": reason,
            "ratio": float(ratio),
            "rsi": float(r),
            "bias20": float(b20),
            "bias60": float(b60),
            "bb_pos": float(bp) if not np.isnan(bp) else None,
        })
    return out


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD(12,26,9)：DIF = EMA(close,12) - EMA(close,26)，DEA = EMA(DIF,9)。

    EMA 用 ewm(span=N, adjust=False).mean()（α=2/(N+1)，业界标准）。
    与 `a-stock-data/backtest_sell_optimize.py::macd()` 一致（worker 已复刻验证）。
    返回 (dif, dea)。MACD 柱 = (dif-dea)*2 不算（关键 DIF/DEA）。
    """
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    dif = ema_f - ema_s
    dea = dif.ewm(span=signal, adjust=False).mean()
    return dif, dea


def _load_index_low(index_id: str) -> pd.Series:
    """近 N 日最低价序列（Supertrend 备买用 ATR 需要 high/low/close 三序列）。

    直接查 index_daily（与 normalize.load_index_high 对称），不污染 normalize.py
    （本次任务约束仅改 signals.py + signal_stats.py + check_signals.py）。
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT date, low FROM index_daily WHERE index_id=? AND low IS NOT NULL ORDER BY date",
        (index_id,),
    ).fetchall()
    conn.close()
    if not rows:
        return pd.Series(dtype=float)
    return pd.Series({r["date"]: r["low"] for r in rows}).sort_index().astype(float)


def _load_index_ohlc_amount(index_id: str) -> tuple:
    """一次查询加载 close/high/low/amount 四序列（性能优化 2026-07-25）。

    原计算流程对每个指数调 4 次 normalize.load_index_*/_load_index_low，各开 1 个
    sqlite 连接 + 1 次 execute + 1 次 fetchall + 1 次 close（93 指数 × 4 = 372 次
    连接开关 + PRAGMA journal_mode 开销，cProfile 实测 DB 部分约 1.3s）。合并为
    1 次查询 `SELECT date, close, high, low, amount WHERE index_id=? ORDER BY date`，
    按列拆 Series 并各自 dropna（等价于原 `WHERE col IS NOT NULL` 过滤）。

    返回 (close, high, low, amount) 四个 pd.Series，与分别调用
    load_index_close / load_index_high / _load_index_low / load_index_amount 完全等价
    （同 index、同 dtype=float、各列过滤 null、按 date 升序）。调用方仍需 high/low/
    amount.reindex(close.index) 对齐到 close（与原逻辑一致）。
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT date, close, high, low, amount FROM index_daily "
        "WHERE index_id=? ORDER BY date",
        (index_id,),
    ).fetchall()
    conn.close()
    if not rows:
        empty = pd.Series(dtype=float)
        return empty, empty, empty, empty
    # 按列拆分：每列只保留非 null 值（等价于原各 loader 的 WHERE col IS NOT NULL）
    close_data = {r["date"]: r["close"] for r in rows if r["close"] is not None}
    high_data = {r["date"]: r["high"] for r in rows if r["high"] is not None}
    low_data = {r["date"]: r["low"] for r in rows if r["low"] is not None}
    amount_data = {r["date"]: r["amount"] for r in rows if r["amount"] is not None}
    close = pd.Series(close_data).sort_index().astype(float) if close_data else pd.Series(dtype=float)
    high = pd.Series(high_data).sort_index().astype(float) if high_data else pd.Series(dtype=float)
    low = pd.Series(low_data).sort_index().astype(float) if low_data else pd.Series(dtype=float)
    amount = pd.Series(amount_data).sort_index().astype(float) if amount_data else pd.Series(dtype=float)
    return close, high, low, amount


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 10) -> pd.Series:
    """ATR(period) Wilder smoothing（ewm alpha=1/period, adjust=False）。

    TR = max(high-low, abs(high-prev_close), abs(low-prev_close))；
    ATR = TR.ewm(alpha=1/period, adjust=False).mean()（Wilder 平滑，业界标准）。
    与 talib.ATR / TradingView Supertrend 口径一致。
    """
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def _supertrend(
    high: pd.Series, low: pd.Series, close: pd.Series,
    period: int = 10, multiplier: float = 3.0,
):
    """Supertrend 指标（ATR×multiplier），返回 (supertrend_line, direction)。

    direction = 1 多头 / -1 空头。翻多 = direction 从 -1 转 1（备买 Supertrend_buy 触发）。

    标准算法（TradingView/MetaTrader 口径）：
    - hl2 = (high+low)/2，atr = ATR(period, Wilder smoothing)
    - upper_basic = hl2 + multiplier*atr，lower_basic = hl2 - multiplier*atr
    - final_upper: 若 upper_basic < prev_final_upper 或 prev_close > prev_final_upper -> 用 upper_basic，
      否则继承 prev_final_upper（多头时上轨只下移不上移，直到被突破换边）
    - final_lower: 若 lower_basic > prev_final_lower 或 prev_close < prev_final_lower -> 用 lower_basic，
      否则继承 prev_final_lower（空头时下轨只上移不下移，直到被突破换边）
    - direction: close > prev_final_upper -> 1（多头）；close < prev_final_lower -> -1（空头）；
      否则继承 prev_direction
    - supertrend line: 多头=final_lower（支撑线），空头=final_upper（压力线）

    数据不足（前 period 日 ATR 为 NaN）安全跳过，direction 默认 1（多头），后续迭代会被覆盖。

    性能优化（2026-07-25）：原用 pandas Series.iloc[i] 读写逐日递推，每赋值触发 pandas 内部
    validate/cast/setitem/apply 全链路开销（93 指数 × ~10000 天 × 多次 .iloc[]= ≈ 1.17M 次
    setitem，占 signals.compute 93% 耗时，cProfile 实测 69s/74s）。改为 numpy 数组下标读写
    （arr[i]=val 是 O(1) 原生赋值无 pandas 包装），算法/递推关系/输出完全一致，实测降至 ~1.5s
    （省 97%+）。算法本身有递归依赖（每日依赖前日 final_upper/final_lower/direction），循环无法
    消除，但 numpy 标量读写消除 pandas .iloc 开销即够。
    """
    import numpy as np

    hl2 = (high + low) / 2.0
    atr = _atr(high, low, close, period)
    upper_basic = hl2 + multiplier * atr
    lower_basic = hl2 - multiplier * atr

    n = len(close)
    # 全部转 numpy 数组做循环（避免 pandas .iloc[]=/iloc[] 的链路开销）
    ub_arr = upper_basic.to_numpy(dtype=float)
    lb_arr = lower_basic.to_numpy(dtype=float)
    close_arr = close.to_numpy(dtype=float)
    fu_arr = ub_arr.copy()  # final_upper
    fl_arr = lb_arr.copy()  # final_lower
    dir_arr = np.ones(n, dtype=np.int8)  # 默认多头=1

    for i in range(1, n):
        # ATR/upper_basic 为 NaN（前 period 日）跳过，保持默认值
        ub_i = ub_arr[i]
        prev_close = close_arr[i - 1]
        if np.isnan(ub_i) or np.isnan(prev_close):
            continue
        # final_upper 更新（多头时上轨只下移不上移）
        prev_fu = fu_arr[i - 1]
        if not np.isnan(prev_fu):
            if ub_i < prev_fu or prev_close > prev_fu:
                fu_arr[i] = ub_i
            else:
                fu_arr[i] = prev_fu
        # final_lower 更新（空头时下轨只上移不下移）
        prev_fl = fl_arr[i - 1]
        if not np.isnan(prev_fl):
            lb_i = lb_arr[i]
            if lb_i > prev_fl or prev_close < prev_fl:
                fl_arr[i] = lb_i
            else:
                fl_arr[i] = prev_fl
        # direction 更新：close 突破 prev_final_upper -> 多头；跌破 prev_final_lower -> 空头；否则继承
        prev_fu2 = fu_arr[i - 1]
        prev_fl2 = fl_arr[i - 1]
        cur_close = close_arr[i]
        if not np.isnan(prev_fu2) and cur_close > prev_fu2:
            dir_arr[i] = 1
        elif not np.isnan(prev_fl2) and cur_close < prev_fl2:
            dir_arr[i] = -1
        else:
            dir_arr[i] = dir_arr[i - 1]  # i >= 1 here, 继承前日

    # supertrend line: 多头=final_lower（支撑），空头=final_upper（压力）
    # vectorized np.where 替代原逐日 .iloc[] 赋值循环
    supertrend_arr = np.where(dir_arr == 1, fl_arr, fu_arr)
    supertrend = pd.Series(supertrend_arr, index=close.index, dtype=float)
    direction = pd.Series(dir_arr, index=close.index, dtype=int)

    return supertrend, direction


def _cross_tag(cross_val) -> str:
    """cross 分级标签：<30 冰点 / 30-50 偏冷 / 50-70 中性 / 70-80 偏热 / >=80 狂热。

    NaN 返回空串（调用方 reason 拼接时省略 cross 段）。
    """
    if pd.isna(cross_val):
        return ""
    v = float(cross_val)
    if v < 30:
        return "冰点"
    if v < 50:
        return "偏冷"
    if v < 70:
        return "中性"
    if v < 80:
        return "偏热"
    return "狂热"


def _buy_type_cn(buy_type) -> str:
    """买点类型 key 转中文（sell reason 的 vs前买[类型] 标注用，2026-07-22）。

    buy_special_filtered 是 buy_special 被 h5 标灰的预览，类型算"追买"。
    None/未知 -> 空串（调用方应保证 last_buy_type 非 None 才调用）。
    """
    return {
        "buy": "主买",
        "buy_aux": "辅买",
        "buy_special": "追买",
        "buy_backup": "备买",
        "buy_special_filtered": "追买",
    }.get(buy_type, "买")


def _load_cross_score() -> pd.Series:
    conn = get_conn()
    rows = conn.execute(
        "SELECT date, value FROM score_daily WHERE score_id='cross_market' ORDER BY date"
    ).fetchall()
    conn.close()
    if not rows:
        return pd.Series(dtype=float)
    return pd.Series({r["date"]: r["value"] for r in rows}).sort_index().astype(float)


def _load_buy_aux_filters(cfg) -> dict:
    """从 indicators.yaml 读 per-index buy_aux 增强配置（支持后续逐品类扩展）。

    返回 {signal_daily_index_id: filter_name}。仅配置了 `buy_aux_filter` 字段的品类
    出现，其他走基线 B1（无增强）。
    - indices: key = idx['id']（如 'sw_801110'）
    - metrics: key = 'g.' + mid（如 'g.cn10y'）—— 暂无品类配置，预留扩展
    - scores: 情绪分 s.* 暂不支持 per-index 增强（结构不同，需要时再扩展）

    当前取值：
    - 'rsi_cross_40' = RSI(14) 上穿40 确认（rp≤40 & r>40），与 C1 上穿30 对称。
      sw_801110 家电打样：f -38%→+16% 转正（14-家电buy_aux优化回测.md）。
      sw_801140 轻工：f -25%→-14% 未转正但胜率 45%→50% 退而求其次（16-行业批量回测）。
    - 'close_above_bl_2pct' = 反弹力度确认（close > bl × 1.02），过滤 barely-crossed
      假信号（dead cat bounce 前半段）。sw_801030 基础化工：f -21%→+20% 转正，
      三 horizon 一致（5d/10d/20d 全 f>0），n=19<30 样本警示但最稳健（16-行业批量回测）。
    """
    out = {}
    for idx in cfg.get("indices", []):
        if not idx.get("enabled", True):
            continue
        f = idx.get("buy_aux_filter")
        if f:
            out[idx["id"]] = f
    for m in cfg.get("metrics", []):
        if not m.get("enabled", True):
            continue
        f = m.get("buy_aux_filter")
        if f:
            out[f"g.{m['id']}"] = f
    return out


def _load_buy_filters(cfg) -> dict:
    """从 indicators.yaml 读 per-index buy 主买点 RSI 阈值配置（C1 收紧）。

    返回 {signal_daily_index_id: filter_name}。仅配置了 `buy_filter` 字段的品类
    出现，其他走基线 C1（RSI 上穿 30）。
    - indices: key = idx['id']（如 'kc50'）
    - metrics: key = 'g.' + mid（预留扩展）
    - scores: 情绪分 s.* 暂不支持 per-index 增强（结构不同，需要时再扩展）

    当前取值：
    - 'rsi_cross_25' = RSI(14) 上穿 25（rp≤25 & r>25），比基线 30 更宽松、
      更早捕捉超卖反弹。回测显示 kc50 科创50（f 15.92%→57.56%）、
      sw_801730 电力设备（f 0%→29.55%）、sw_801760 传媒（f 0%→41.74%）
      三品类用 25 替代 30 后凯利 f 显著改善（详见 22-buy收紧RSI回测-21个不建议.md）。
    """
    out = {}
    for idx in cfg.get("indices", []):
        if not idx.get("enabled", True):
            continue
        f = idx.get("buy_filter")
        if f:
            out[idx["id"]] = f
    # metrics/scores 预留扩展，当前无配置
    return out


def _load_sell_no_trend_filters(cfg) -> dict:
    """从 indicators.yaml 读 per-index 卖点去趋势过滤配置。

    返回 {signal_daily_index_id: True}。仅配置了 ``sell_no_trend_filter: true`` 的品类
    出现，其他走基线（S1 MA60 多头 + MACD 死叉双重过滤）。

    当前取值：
    - usdcnh（离岸人民币）：干预市单边上行，MA60 多头过滤把卖点砍到 n=7（几乎全程在上方）。
      去过滤后卖点数量恢复，kelly=0.34-0.47 胜率 60-66% 优秀（回测验证）。
    """
    out = {}
    for m in cfg.get("metrics", []):
        if not m.get("enabled", True):
            continue
        f = m.get("sell_no_trend_filter")
        if f:
            out[f"g.{m['id']}"] = True
    return out


def strategy_desc(index_id: str, cfg: dict) -> dict:
    """返回策略描述，供前端 hint-strategy 蓝色标注行 + 标题❓弹窗（顶层 buy/buy_aux/sell 字符串向后兼容 + _detail 6字段完整描述）。

    纯描述函数，不改买卖点计算逻辑。读 indicators.yaml 的 buy_filter / buy_aux_filter + 本模块的
    _SKIP_BUY_IDS / _SKIP_SELL_IDS / s.* 前缀规则，与 _compute_value_signals / compute 的实际触发逻辑一致：
    - buy: "RSI(14)上穿30"（C1 主买，基线）；per-index buy_filter=rsi_cross_25 → "RSI(14)上穿25"
      _SKIP_BUY_IDS / s.a_sentiment → "skip"
    - buy_aux:
        基线（无 buy_aux_filter）"BB下轨回归"
        rsi_cross_40 → "BB下轨回归+RSI上穿40"
        close_above_bl_2pct → "BB下轨回归+反弹2%"
        _SKIP_BUY_IDS / s.a_sentiment → "skip"
    - sell:
        基线（g.* 指标 + 指数）"20日高回落5%+MA60多头+MACD死叉"
        s.* 情绪分 → "20日高回落5%+MA60多头（豁免MACD）"（a_sentiment 加 MACD 后 n=106→7 故豁免）
        _SKIP_SELL_IDS → "skip"

    index_id: signal_daily 的 index_id（指数裸 id 如 'sh'/'sw_801110'，或 'g.cn10y'/'s.a_sentiment'）
    cfg: indicators.yaml 解析后的 dict（load_config() 返回）
    """
    raw = index_id.split(".", 1)[1] if "." in index_id else index_id
    is_score = index_id.startswith("s.")
    is_skip_buy = raw in _SKIP_BUY_IDS  # usdcnh 干预市买点失效
    is_skip_sell = raw in _SKIP_SELL_IDS  # cn_us_spread 卖点完全反向
    is_a_sentiment = index_id == "s.a_sentiment"  # RSI 结构性≥40 → skip_buy（买/辅买都 skip）

    if is_skip_buy or is_a_sentiment:
        buy = "skip"
        buy_aux = "skip"
    else:
        buy_filt = _load_buy_filters(cfg).get(index_id)
        if buy_filt == "rsi_cross_25":
            buy = "RSI(14)上穿25"
        else:
            buy = "RSI(14)上穿30"
        filt = _load_buy_aux_filters(cfg).get(index_id)
        if filt == "rsi_cross_40":
            buy_aux = "BB下轨回归+RSI上穿40"
        elif filt == "close_above_bl_2pct":
            buy_aux = "BB下轨回归+反弹2%"
        else:
            buy_aux = "BB下轨回归"

    sell_no_trend = _load_sell_no_trend_filters(cfg).get(index_id, False)
    if is_skip_sell:
        sell = "skip"
    elif sell_no_trend:
        sell = "20日高回落2σ（去趋势过滤）"
    elif is_score:
        sell = "20日高回落5%+MA60多头（豁免MACD）"
    else:
        sell = "20日高回落5%+MA60多头+MACD死叉"

    # === _detail 6 字段完整描述（供前端标题❓ click 弹 modal 展开该指数策略组合）===
    # 顶层 buy/buy_aux/sell 字符串保持不变（向后兼容），_detail 为新增子对象。
    if is_skip_buy or is_a_sentiment:
        buy_detail = {
            "desc": "skip（买点失效）",
            "params": "-",
            "filter": "skip：" + (
                "s.a_sentiment RSI 结构性≥40（0 信号，仅算卖）" if is_a_sentiment
                else f"_SKIP_BUY_IDS 干预市买点失效（{raw} RSI 超卖后继续跌，回测验证）"
            ),
            "enabled": False,
        }
        buy_aux_detail = {
            "desc": "skip（辅买同步失效）",
            "params": "-",
            "filter": "skip：与 buy 同步（_SKIP_BUY_IDS / s.a_sentiment）",
            "enabled": False,
        }
    else:
        if buy == "RSI(14)上穿25":
            buy_detail = {
                "desc": "RSI(14) 上穿 25（C1 主买，超卖拐点，per-index 收紧）",
                "params": "RSI 周期=14，上穿阈值=25（rp≤25 & r>25）",
                "filter": f"per-index buy_filter=rsi_cross_25（{raw}：回测凯利 f 15.92%->57.56%，比基线 30 更早捕捉超卖反弹）",
                "enabled": True,
            }
        else:
            buy_detail = {
                "desc": "RSI(14) 上穿 30（C1 主买，超卖拐点，均值回归思路）",
                "params": "RSI 周期=14，上穿阈值=30（rp≤30 & r>30）",
                "filter": "基线（无 per-index buy_filter 配置）",
                "enabled": True,
            }
        if buy_aux == "BB下轨回归+RSI上穿40":
            buy_aux_detail = {
                "desc": "BB 下轨回归 + RSI(14) 上穿 40（B1 辅买，左侧布局 + 动量转升双维确认）",
                "params": "BB 周期=20，σ=2.0；RSI 上穿阈值=40（rp≤40 & r>40，与 C1 上穿30 对称）",
                "filter": f"per-index buy_aux_filter=rsi_cross_40（{raw}：价格反弹+动量转升双维确认）",
                "enabled": True,
            }
        elif buy_aux == "BB下轨回归+反弹2%":
            buy_aux_detail = {
                "desc": "BB 下轨回归 + 反弹 2%（B1 辅买，左侧布局 + 反弹力度确认）",
                "params": "BB 周期=20，σ=2.0；反弹阈值=close > BB下轨 × 1.02（方案A，蕴含 B1 的 close>bl）",
                "filter": f"per-index buy_aux_filter=close_above_bl_2pct（{raw}：2% 反弹过滤盘整下轨假回归）",
                "enabled": True,
            }
        else:
            buy_aux_detail = {
                "desc": "BB 下轨回归（B1 辅买，左侧布局，价格跌穿 BB 下轨后回归）",
                "params": "BB 周期=20，σ=2.0（close.shift(1)<bl.shift(1) & close>bl）",
                "filter": "基线（无 per-index buy_aux_filter 配置）",
                "enabled": True,
            }

    # 降回撤方案B 第三层叠加 per-index（小节AV C1，sh 用 C1|D1a 叠加替代原豁免，非 sh 保持方案 B）
    if raw == "sh":
        # sh 专属 C1|D1a 公式来自 L940-953，实测数据来自 L945-947 注释
        buy_special_filter_text = (
            "sh 专属 C1|D1a 叠加（替代原 sh 豁免）："
            "C1 高波动/距高点远(atr_pct>=2.5% OR dist_from_high>=15%) + D1a 中档共振补刀(atr_pct∈[1.8%,2.5%) AND dist_from_low60>15% AND dev_ma60>1.05)；"
            "sh 实测(vs 单 C1)：612->503 保留82.2%，peak(<-10%) 7.35%->5.58%(-1.78pp)，mdd -3.72%->-2.65%(改善1.07pp)，"
            "ret20 +6.29%->+4.31%(损1.96pp可接受)，keep 67.7%，Jaccard 重叠率30.8%(C1 与 D1a 互补性强)"
        )
    else:
        # 非 sh 方案B 公式来自 L939（其他 9 指数继续方案 B 不变，均有改善或微损可接受）
        buy_special_filter_text = (
            f"非 sh 方案B 第三层叠加（{raw}）：atr_pct>=2.5% OR dist_from_low60>30%（高波动/涨多顶部过滤，命中日不发也不更新游标）"
        )
    buy_special_detail = {
        "desc": "唐奇安 20 日上轨突破 + B4 5日站稳确认（2%容差）+ h5/R2 真过滤（C+C12+E2+量价背离收紧）",
        "params": (
            "Donchian 周期=20（don_upper=high.rolling(20).max().shift(1)，不含当日）；"
            "站稳窗口=5日（close.rolling(5).min() >= close.shift(5)*0.98，允许 2% 噪音）；"
            "h5 R2 = C(dev_ma60>1.20 & ATR>3%) | C12(dev_ma60∈(1.0,1.1] & drawdown_hh20<-2%) | "
            "E2(close>BB上轨 & ATR>3%) | 量价背离收紧(price_vol_div==1 & ATR>2.5%)"
        ),
        "filter": (
            "全局统一（所有指数均启用）；h5 R2 真过滤上线（尖尖逃顶方案A，命中日直接 drop 不 append）；"
            + buy_special_filter_text
        ),
        "enabled": True,
    }
    buy_backup_detail = {
        "desc": "Supertrend ATR(10)×3 翻多 + 3 日二次确认（close.rolling(3).min() > close.shift(3)）",
        "params": (
            "ATR 周期=10，multiplier=3.0（_supertrend high/low/close）；"
            "确认窗口=3日（min_close_3d > close_shift3，翻多后 3 日收盘未跌破翻多日收盘=有效翻多非诱多）"
        ),
        "filter": "全局统一；3日二次确认过滤诱多（回测：诱多 22.3%->6.0%，胜率 57%->79%，t+20 收益 +2.22%->+7.73%）",
        "enabled": True,
    }
    if is_skip_sell:
        sell_detail = {
            "desc": "skip（卖点失效）",
            "params": "-",
            "filter": f"skip：_SKIP_SELL_IDS（{raw} 卖点完全反向，卖后涨 15-25%，回测验证）",
            "enabled": False,
        }
    elif sell_no_trend:
        sell_detail = {
            "desc": "20日高回落 2σ（去趋势过滤，干预市单边上行适用）",
            "params": "hh20=high.rolling(20).max()；std20=close.rolling(20).std()；阈值=hh20-2.0*std20（2σ 去趋势）",
            "filter": f"per-index sell_no_trend_filter=true（{raw}：单边上行 MA60 把卖点砍到 n=7，去过滤后 kelly=0.34-0.47 胜率 60-66%）",
            "enabled": True,
        }
    elif is_score:
        sell_detail = {
            "desc": "20日高回落 5% + MA60 多头（豁免 MACD 死叉，s.* 情绪分序列适用）",
            "params": "hh20=high.rolling(20).max()；阈值=hh20*0.95（5% 回落）；MA60 多头过滤（value>ma60）",
            "filter": "s.* 情绪分序列豁免 MACD（a_sentiment 加 MACD 后 n=106->7 样本不足，cross_market 同理），保留 D1+S1",
            "enabled": True,
        }
    else:
        sell_detail = {
            "desc": "20日高回落 5% + MA60 多头 + MACD 死叉（D1+S1+B 方案，止盈减仓提示）",
            "params": "hh20=high.rolling(20).max()；阈值=hh20*0.95（5% 回落）；MA60 多头过滤（close>ma60）；MACD 死叉（DIF<DEA）",
            "filter": "基线（指数 + g.* 指标均应用 MACD 过滤，回测建议率 18.3%->43.3%）",
            "enabled": True,
        }
    _STOP_LOSS_ATR_MULT_DESC = {"csi_div": 4.5}  # 与 L682 compute 中 _STOP_LOSS_ATR_MULT 保持一致
    atr_mult = _STOP_LOSS_ATR_MULT_DESC.get(raw, 3.5)
    sell_stop_loss_detail = {
        "desc": f"ATR×{atr_mult} Chandelier Exit（近20日最高-{atr_mult}×ATR(14)，移动止损线跟随高点更新）",
        "params": (
            f"ATR 周期=14（Wilder）；倍数={atr_mult}"
            + (f"（{raw} per-index 覆盖为 4.5，更宽止损线降 24% 信号数，套牢率 48.3%->46.1%）" if atr_mult != 3.5 else "（默认 3.5）")
            + "；hh20=high.rolling(20).max().shift(1)（不含当日）"
        ),
        "filter": (
            "全局统一；首次跌破触发（today below AND prev NOT below，astype(bool) 强制布尔取反，避免连续标）；与 buy 独立无配对 entry；"
            "第一个止损卖过滤(小节AE):每个 buy 后窗口内只保留第一个止损卖(all_buy_dates 排序,window_end=下一buy,stops_in_window[0]),"
            "降幅 83-88%,盈亏比 5/5 全升(hs300 0.961->1.098,sh 0.919->1.038 突破1.0)；"
            "同日叠加过滤:buy 日不触发止损(sell_stop_set 排除 buy_dates_set),避免买点同时止损矛盾"
        ),
        "enabled": True,
    }

    return {
        "buy": buy,
        "buy_aux": buy_aux,
        "sell": sell,
        "_detail": {
            "buy": buy_detail,
            "buy_aux": buy_aux_detail,
            "buy_special": buy_special_detail,
            "buy_backup": buy_backup_detail,
            "sell": sell_detail,
            "sell_stop_loss": sell_stop_loss_detail,
        },
    }


# ============ B 扩展：全球指标 + 情绪分数买卖点（2026-07-07）============
# value 当 close 算 RSI 买 + 20日高回落卖，规则按 09-指标买卖点回测.md 推荐：
#   买 = RSI(14) 上穿 30（与指数 C1 一致）+ BB 下轨回归辅买点（B1，2026-07-05 加）
#   卖分支：恒正序列（min>0）用 %回落5%（thresh=hh20*0.95）；
#           含负数/窄幅序列用 std 2σ（thresh=hh20-2.0*std20）。
#   卖叠加 MA60 多头过滤（S1，2026-07-05 加）+ MACD 死叉确认（方案 B，2026-07-05 加）。
#   **s.* 情绪分序列豁免 MACD 过滤**（a_sentiment 加 MACD 后 n=106→7 样本不足），保留 D1+S1。
# a_sentiment 买规则失效（RSI 结构性≥40，0 信号）→ skip_buy，仅算卖（buy_aux 也跳过）。
# signal_daily index_id 前缀：g.<metric_id> / s.<score_id>（区分指数/指标/分数）。
# 卖点 reason 附 vs前买 标注，分母用 |last_buy_value| 兼容负数序列（如 cn_us_spread）。
GLOBAL_METRIC_IDS = (
    "cn10y", "us10y", "wti_oil", "brent", "comex_silver", "gold", "oil",
    "usdcnh", "a_qvix_300", "a_qvix_1000", "cn_us_spread",
)
SCORE_IDS = ("cross_market", "a_sentiment", "sentiment_sz50", "sentiment_hs300", "sentiment_csi500", "sentiment_csi1000", "sentiment_cyb", "sentiment_kc50", "fear_greed")
# 窄幅序列（虽恒正但 %回落 0 信号，回测验证）+ 含负数序列 → 强制走 std 卖规则
_STD_SELL_IDS = {"usdcnh", "cn_us_spread"}
# #5 结构性异常品类（汇率干预市/均值回归 sell 反向/地缘驱动）——调参救不了，skip 买卖点
# 拆分自原 SKIP_IDS（oil/usdcnh/cn_us_spread），按回测结论分别处理：
# - _SKIP_BUY_IDS: 买点失效（干预市 RSI 超卖后继续跌），保持 skip_buy
# - _SKIP_SELL_IDS: 卖点完全反向（卖后涨 15-25%），保持 skip_sell
# oil 买点（kelly=0.18 胜率 59.3%, ≥wti_oil）+卖点（20d 勉强建议）都开，不在任何 skip 集。
_SKIP_BUY_IDS = {"usdcnh"}
_SKIP_SELL_IDS = {"cn_us_spread"}


def _compute_value_signals(value: pd.Series, sid: str, skip_buy: bool = False, kind: str = "指标",
                           buy_aux_filter: str = None, skip_sell: bool = False,
                           sell_no_trend_filter: bool = False):
    """value 序列 → 买卖点 signals（sid 已含 g./s. 前缀）。

    B1+S1（2026-07-05）：买加 BB 下轨回归辅买点（buy_aux），卖叠加 MA60 多头过滤。
    Per-index buy_aux 增强（2026-07-05）：buy_aux_filter='rsi_cross_40' 叠加 RSI 上穿40
    确认（配置化，支持后续逐品类扩展，当前仅 sw_801110 用，g.*/s.* 预留扩展位）。

    value: pd.Series（按 date 升序，float），当 close 用
    sid: signal_daily index_id（如 'g.cn10y' / 's.cross_market'）
    skip_buy: True 时跳过买信号（buy + buy_aux，a_sentiment 用，RSI 失效）
    kind: reason 标签（"指标"/"情绪分"），区分指数 signals
    buy_aux_filter: per-index 增强过滤名（None=基线 B1；'rsi_cross_40'=RSI 上穿40 确认）
    sell_no_trend_filter: True 时跳过卖点 MA60 多头过滤 + MACD 死叉确认（usdcnh 干预市用，
        单边上行 MA60 把卖点砍到 n=7；去过滤后 kelly=0.34-0.47 胜率 60-66%）
    """
    if len(value) < 60:  # MA60 需要 60 日，不足则卖点过滤全砍，无意义
        return []
    rsi = _rsi(value, 14)
    rsi_prev = rsi.shift(1)

    # 买点（C1 主买）：RSI 上穿 30；skip_buy 时全 False
    if skip_buy:
        buy = pd.Series(False, index=value.index)
    else:
        buy = ((rsi_prev <= 30) & (rsi > 30)).fillna(False)

    # B1 辅买点：BB 下轨回归（value 从下轨下回到上方）；skip_buy 时也跳过
    if skip_buy:
        buy_aux = pd.Series(False, index=value.index)
    else:
        _, _, bl_ = _bollinger(value, 20, 2.0)
        buy_aux = ((value.shift(1) < bl_.shift(1)) & (value > bl_)).fillna(False)
        # Per-index buy_aux 增强（配置化）：'rsi_cross_40' 叠加 RSI 上穿40 确认
        # （rp≤40 & r>40，与 C1 上穿30 对称，价格反弹+动量转升双维确认）
        if buy_aux_filter == "rsi_cross_40":
            rsi_cross_40 = ((rsi_prev <= 40) & (rsi > 40)).fillna(False)
            buy_aux = buy_aux & rsi_cross_40
        elif buy_aux_filter == "close_above_bl_2pct":
            # 方案A 反弹力度2%：close > bl × 1.02（蕴含 B1 的 close>bl）
            close_above_bl_2pct = (value > bl_ * 1.02).fillna(False)
            buy_aux = buy_aux & close_above_bl_2pct

    # 卖点分支：恒正（min>0）且非窄幅 → %回落5%；否则（含负数/窄幅）→ std 2σ
    raw = sid.split(".", 1)[1] if "." in sid else sid
    use_std = (raw in _STD_SELL_IDS) or not (value.min() > 0)
    hh20 = value.rolling(20).max()
    if use_std:
        std20 = value.rolling(20).std()
        thresh = hh20 - 2.0 * std20
        sell_label = "20日高回落2σ"
    else:
        thresh = hh20 * 0.95
        sell_label = "20日高回落5%"
    sell = ((value.shift(1) >= thresh.shift(1)) & (value < thresh)).fillna(False)

    # S1 卖点降噪：仅当 value > MA60（多头趋势）才放卖——砍下跌趋势假卖点
    # sell_no_trend_filter=True 时跳过（usdcnh 干预市单边上行 MA60 把卖点砍光）
    ma60 = value.rolling(60, min_periods=60).mean()
    if not sell_no_trend_filter:
        sell = sell & (value > ma60).fillna(False)

    # 方案 B（MACD 死叉确认，2026-07-05）：D1+S1 基础上加 DIF<DEA（动量转弱确认）。
    # s.* 情绪分序列豁免（a_sentiment 加 MACD 后 n=106→7 样本不足，cross_market 同理），
    # 保留原 D1+S1 逻辑。g.* 指标与非前缀指数一样应用 MACD 过滤。
    use_macd = not sid.startswith("s.") and not sell_no_trend_filter
    if use_macd:
        dif, dea = _macd(value)
        sell = sell & (dif < dea).fillna(False)
    else:
        dif = dea = None

    # skip_sell override（cn_us_spread 卖点完全反向）
    if skip_sell:
        sell = pd.Series(False, index=value.index)

    # B 标注（vs前买）：分母用 |last_buy_value| 兼容负数序列
    # buy_aux 与 C1 同日时去重（保留 C1 主买）；buy_aux 也算买点，更新 last_buy_value
    buy_set = set(buy[buy].index)
    buy_aux_set = set(buy_aux[buy_aux].index) - buy_set  # 去重：C1 主买优先
    sell_set = set(sell[sell].index)
    out = []
    last_buy_value = None
    last_buy_type = None  # 跟随 last_buy_value 同步更新（sell reason 标 [类型] 用）
    for date in sorted(buy_set | buy_aux_set | sell_set):
        v = value.get(date)
        if date in buy_set:
            last_buy_value = float(v) if pd.notna(v) else last_buy_value
            last_buy_type = "buy"
            r = rsi.get(date)
            rp = rsi_prev.get(date)
            reason = f"RSI上穿30({rp:.0f}->{r:.0f})" if pd.notna(r) and pd.notna(rp) else "RSI=NA"
            reason += f",[{kind}]"
            out.append((date, sid, "buy", reason))
        if date in buy_aux_set:
            # buy_aux 也算买点 → 更新 last_buy_value 游标
            last_buy_value = float(v) if pd.notna(v) else last_buy_value
            last_buy_type = "buy_aux"
            r = rsi.get(date)
            parts = []
            if pd.notna(v):
                parts.append(f"布林下轨回归(下轨{bl_.get(date):.4g},value{v:.4g})")
            else:
                parts.append("布林下轨回归")
            if pd.notna(r):
                parts.append(f"RSI={r:.0f}")
            if buy_aux_filter == "rsi_cross_40":
                parts.append("RSI[上穿40]")
            if buy_aux_filter == "close_above_bl_2pct":
                parts.append("反弹[2%]")
            parts.append(f"[{kind}]")
            out.append((date, sid, "buy_aux", ", ".join(parts)))
        if date in sell_set:
            h = hh20.get(date)
            t = thresh.get(date)
            m = ma60.get(date)
            parts = []
            if pd.notna(h) and pd.notna(t) and pd.notna(v):
                parts.append(f"{sell_label}(高{h:.4g}->阈{t:.4g},value{v:.4g})")
            else:
                parts.append(sell_label)
            rv = rsi.get(date)
            if pd.notna(rv):
                parts.append(f"RSI={rv:.0f}")
            # S1 趋势过滤标签
            if pd.notna(m):
                tag = "去趋势过滤" if sell_no_trend_filter else "趋势过滤"
                parts.append(f"MA60={m:.4g}[{tag}]")
            # MACD 死叉确认标签（方案 B，2026-07-05）：s.* 豁免不加
            if use_macd and dif is not None:
                dv = dif.get(date)
                ev = dea.get(date)
                if pd.notna(dv) and pd.notna(ev):
                    parts.append(f"MACD=DIF{dv:.4g}/DEA{ev:.4g}[死叉确认]")
            # vs前买 标注：分母 |last_buy_value| 兼容负数（cn_us_spread 可 -3~2），标 [买点类型] 前缀
            # （2026-07-22 加 last_buy_type 游标，类型来自前买点：buy->主买/buy_aux->辅买）
            if last_buy_value is not None and pd.notna(v):
                denom = abs(last_buy_value)
                if denom > 0:
                    pct = (float(v) - last_buy_value) / denom * 100
                    sign = "+" if pct >= 0 else ""
                    tag = "止盈" if pct > 0 else "买点失败"
                    type_cn = _buy_type_cn(last_buy_type)
                    parts.append(f"vs前买[{type_cn}]{sign}{pct:.2f}%[{tag}]")
                else:
                    parts.append("无前买点[趋势中]")
            else:
                parts.append("无前买点[趋势中]")
            parts.append(f"[{kind}]")
            out.append((date, sid, "sell", ", ".join(parts)))
    return out


def compute():
    cfg = load_config()
    cross = _load_cross_score()
    buy_aux_filters = _load_buy_aux_filters(cfg)  # per-index buy_aux 增强（如 sw_801110 RSI上穿40）
    buy_filters = _load_buy_filters(cfg)  # per-index buy 主买点 RSI 阈值收紧（如 kc50 RSI上穿25）
    sell_no_trend_filters = _load_sell_no_trend_filters(cfg)  # per-index 卖点去趋势过滤（如 usdcnh 干预市）
    signals = []
    for idx in cfg.get("indices", []):
        if not idx.get("enabled", True):
            continue
        iid = idx["id"]
        # 性能优化（2026-07-25）：4 次 DB 查询合并为 1 次（_load_index_ohlc_amount），
        # 省 93×3=279 次 sqlite 连接开关 + execute + fetchall 开销（~0.7s）。
        # 原: close=load_index_close(iid); high=load_index_high(iid).reindex(close.index);
        #     low=_load_index_low(iid).reindex(close.index); amount=load_index_amount(iid).reindex(close.index)
        close, high_raw, low_raw, amount_raw = _load_index_ohlc_amount(iid)
        if len(close) < 60:  # MA60 需要 60 日，不足则卖点过滤全砍，无意义
            continue
        high = high_raw.reindex(close.index)  # high 对齐 close，缺失前向无填充
        rsi = _rsi(close, 14)
        cross_aligned = cross.reindex(close.index)
        rsi_prev = rsi.shift(1)

        # 买点（C1 主买）：RSI 上穿阈值事件化；首日 shift 出 NaN，fillna(False) 跳过。
        # 基线 RSI 上穿 30；per-index buy_filter 可收紧阈值（如 rsi_cross_25 = 上穿 25）。
        # cross 不再作硬门槛，仅作分级标签写进 reason。
        buy_filter = buy_filters.get(iid)
        if buy_filter == "rsi_cross_25":
            buy = ((rsi_prev <= 25) & (rsi > 25)).fillna(False)
        else:
            buy = ((rsi_prev <= 30) & (rsi > 30)).fillna(False)

        # B1 辅买点：BB 下轨回归（close 从下轨下回到上方）——强势市更敏感，互补 C1 盲区。
        # mid=MA20, sd=std(ddof=0), bu=mid+2σ, bl=mid-2σ（与 11 回测报告一致）。
        _, _, bl_ = _bollinger(close, 20, 2.0)
        buy_aux = ((close.shift(1) < bl_.shift(1)) & (close > bl_)).fillna(False)

        # Per-index buy_aux 增强（配置化，支持后续逐品类扩展）：
        # sw_801110 方案B = RSI 上穿40 确认（rp≤40 & r>40，与 C1 上穿30 对称），
        # 价格反弹 + 动量转升双维确认，f -38%→+16% 转正（14-家电buy_aux优化回测.md）。
        # sw_801140 方案B = 同 sw_801110，f -25%→-14% 未转正但胜率 45%→50% 退而求其次
        # （16-行业buy_aux批量回测）。
        # sw_801030 方案A = 反弹力度确认（close > bl × 1.02），过滤 barely-crossed 假信号，
        # f -21%→+20% 转正，三 horizon 一致，n=19<30 样本警示（16-行业buy_aux批量回测）。
        buy_aux_filter = buy_aux_filters.get(iid)
        if buy_aux_filter == "rsi_cross_40":
            rsi_cross_40 = ((rsi_prev <= 40) & (rsi > 40)).fillna(False)
            buy_aux = buy_aux & rsi_cross_40
        elif buy_aux_filter == "close_above_bl_2pct":
            # 方案A 反弹力度2%：B1 基线已含 close>bl，叠加 close > bl × 1.02（蕴含 close>bl）
            close_above_bl_2pct = (close > bl_ * 1.02).fillna(False)
            buy_aux = buy_aux & close_above_bl_2pct

        # 卖点（D1，high-based 20 日回落 5%）：close 从近 20 日最高价（用 high 不用 close）
        # 回落 5% = 趋势转弱/止盈减仓提示。事件化：前一日还在阈之上、当日跌破阈才标。
        hh20 = high.rolling(20).max()
        thresh = hh20 * 0.95
        sell = ((close.shift(1) >= thresh.shift(1)) & (close < thresh)).fillna(False)

        # S1 卖点降噪：仅当 close > MA60（多头趋势）才放卖——砍下跌趋势假卖点（回测砍 39%）。
        # MA60 前 60 日为 NaN，close>NaN 为 False，自动不放卖（与 min_periods=60 一致）。
        ma60 = close.rolling(60, min_periods=60).mean()
        sell = sell & (close > ma60).fillna(False)

        # 方案 B（MACD 死叉确认，2026-07-05）：D1+S1 基础上加 DIF<DEA（动量转弱确认），
        # 过滤「强趋势中回调假摔」型假信号。回测建议率 18.3%→43.3%（11→26 个建议）。
        # 指数（无前缀）一律应用 MACD 过滤；s.* 情绪分序列在 _compute_value_signals 豁免。
        dif, dea = _macd(close)
        sell = sell & (dif < dea).fillna(False)

        # 特买 Donchian20_up（2026-07-21）：close 突破前20日最高价（不含当日）= 唐奇安20日上轨突破。
        # 激进战法高回撤高收益，趋势跟踪类（与 C1/B1 均值回归类互补）。独立计算不影响 buy/buy_aux/sell。
        # don_upper = 前20日（不含当日）最高价 = high.rolling(20).max().shift(1)（含当日 20 日 max 再 shift）。
        don_upper = high.rolling(20).max().shift(1)
        donchian20_up = (close > don_upper).fillna(False)

        # 备买 Supertrend_buy（2026-07-21）：ATR(10)×3 Supertrend 从翻空转翻多 = 趋势转向。
        # 趋势跟踪类（与 C1/B1 均值回归类互补）。独立计算不影响 buy/buy_aux/sell。
        # low 对齐 close（缺失前向无填充），low 全空则跳过 Supertrend（如部分指数无 low 数据）。
        # 性能优化（2026-07-25）：low/amount 复用 _load_index_ohlc_amount 已查的 low_raw/amount_raw
        low = low_raw.reindex(close.index)
        if low.dropna().empty:
            # 无 low 数据（极少见）-> 不发备买/止损信号，st_line 全 NaN（reason 兜底省略 ST 值）
            st_line = close.astype(float) * float("nan")
            supertrend_buy = pd.Series(False, index=close.index)
            sell_stop_loss = pd.Series(False, index=close.index)
            buy_special_filt = pd.Series(False, index=close.index)
            buy_backup_filt = pd.Series(False, index=close.index)
            h5_filter_mask = pd.Series(False, index=close.index)  # 无 low -> 无 ATR -> 不过滤
            peak_dd_filter_mask = pd.Series(False, index=close.index)  # 无 low -> 无 ATR/low_60 -> 不过滤
        else:
            st_line, st_dir = _supertrend(high, low, close, period=10, multiplier=3.0)
            supertrend_buy = ((st_dir.shift(1) == -1) & (st_dir == 1)).fillna(False)

            # sell_stop_loss（A1, 2026-07-21 初版 Don20；2026-07-21 改 ATR×3 Chandelier Exit；2026-07-21 改 ATR×3.5 降频）：
            # atr3_line = 近20日（不含当日）最高价 - 3.5*ATR(14) = high.rolling(20).max().shift(1) - 3.5*atr14。
            # 从高点回撤 3.5*ATR 触发止损（移动止损线，跟随高点更新），即 Chandelier Exit。
            # 独立事件化（无配对 entry，区别于回测 /tmp/backtest_stoploss_compare.py atr_3 的
            # entry_close - 3*ATR(entry_idx) 入场价固定线口径——本信号无 entry 概念，用高点移动线适配）。
            # 事件化（前一日未跌破、当日跌破才标，避免连续标），当天跌破当天发。
            # 方案A定倍（2026-07-22）：红利三指数 per-index ATR 倍数。csi_div 4.5（更宽止损线，降24%信号数，
            # 套牢率 48.3%->46.1% 改善）；div_lowvol/sz_div 保持默认 3.5。回测依据 /tmp/backtest_stoploss_dedup.py。
            # 首次跌破 dtype 修复（2026-07-22）：sell_stop_cond.shift(1).fillna(False) 返回 object dtype，
            # ~object 做位运算（~True=-2, ~False=-1）非布尔取反，致 first_break==below 完全不去重（6-7x 误增）。
            # 修复：.astype(bool) 强制布尔，~bool 才是布尔取反。修复后 csi_div 1029->151 信号（6.9x 去重）。
            _STOP_LOSS_ATR_MULT = {"csi_div": 4.5}  # per-index ATR 倍数覆盖；缺省走 3.5
            atr_mult = _STOP_LOSS_ATR_MULT.get(iid, 3.5)
            atr14 = _atr(high, low, close, 14)
            atr3_line = high.rolling(20).max().shift(1) - atr_mult * atr14
            sell_stop_cond = (close < atr3_line).fillna(False)
            # 首次跌破触发：today below AND prev NOT below（持续下方不出，回到上方再跌破才再出）。
            # astype(bool) 必须：shift+fillna 返回 object dtype，~object 是位运算非布尔取反（2026-07-22 修复）。
            sell_stop_prev = sell_stop_cond.shift(1).fillna(False).astype(bool)
            sell_stop_loss = sell_stop_cond & (~sell_stop_prev)

            # buy_special 加 B4_hold5d 过滤（2026-07-21，stateless 延后触发）：
            # 当天 t 回看 t-5 是否 Donchian 上轨突破日（原 donchian20_up 触发条件），
            # 若是检查 t-4..t 的 min(low) >= low[t-5]（突破后5日内最低价未跌破突破日最低价
            # = 有效突破站稳）。确认则当天 t 发 buy_special 信号（信号日=t+5 即当天 t），
            # reason 追加 "+5日站稳确认"；未确认则不发。
            # 回测：胜率 43.4%->56.8%，盈亏比 5.42->7.89，均收 11.59%->19.14%，9组合无退化。
            # 参考 /tmp/backtest_filter_b_v2.py::filter_B4_continuous_confirm(L73-94，用 low 作支撑)。
            # stateless 实现：donchian20_up.shift(5) & (low.rolling(5).min() >= low.shift(5))
            #   - low.rolling(5).min() at t = min(low[t-4..t])（5个值，不含 t-5，与 filter_B4
            #     切片 [bd+1:bd+6] 即 [t-4..t] 一致）
            #   - low.shift(5) at t = low[t-5]（突破日 low）
            donchian20_up_shift5 = donchian20_up.shift(5)
            # 2026-07-22 升级（尖尖逃顶方案A）：low 瞬时插针假站稳 -> close 收盘有效站稳（容差2%）。
            # 原 low.rolling(5).min() >= low.shift(5) 易被盘中插针 low 触发假确认；
            # 改 close.rolling(5).min() >= close.shift(5)*0.98（允许2%噪音，close 站稳才算有效突破）。
            # 调研依据 /tmp/peak_filter_backtest.py：close+2%容差 OR R2 真过滤组合滤率10.66%、
            # trap-1.43pp(12.83%->11.40%)、win+0.6pp、pf+0.04、误杀55.82%最低、mean持平。
            min_close_5d = close.rolling(5).min()  # at t: min(close[t-4..t])
            close_shift5 = close.shift(5)  # at t: close[t-5]（突破日 close）
            b4_hold5d_confirm = (min_close_5d >= close_shift5 * 0.98).fillna(False)
            buy_special_filt = donchian20_up_shift5 & b4_hold5d_confirm

            # buy_backup 加二次确认过滤（2026-07-21，stateless 延后触发）：
            # 当天 t 回看 t-3 是否 Supertrend 翻多日（原 supertrend_buy 触发条件），
            # 若是检查 t-2..t 的 min(close) > close[t-3]（翻多后3日内收盘价未跌破翻多日
            # 收盘 = 有效翻多非诱多）。确认则当天 t 发 buy_backup 信号（信号日=t+3 即当天 t），
            # reason 追加 "+3日二次确认"；未确认则不发。
            # 回测：诱多 22.3%->6.0%，胜率 57%->79%，t+20 收益 +2.22%->+7.73%，样本 358->117。
            # 参考 /tmp/backtest_buy_backup_filter.py::still_above(L146-163，seg=pos+1..pos+1+days
            # 即 [t-2..t]，min > close[t-3])。
            # stateless 实现：supertrend_buy.shift(3) & (close.rolling(3).min() > close.shift(3))
            supertrend_buy_shift3 = supertrend_buy.shift(3)
            min_close_3d = close.rolling(3).min()  # at t: min(close[t-2..t])
            close_shift3 = close.shift(3)  # at t: close[t-3]（翻多日 close）
            confirm_above = (min_close_3d > close_shift3).fillna(False)
            buy_backup_filt = supertrend_buy_shift3 & confirm_above

            # h5 平衡档过滤（2026-07-22 预览->真过滤上线，尖尖逃顶方案A）：被过滤的 buy_special 直接 drop 不 append。
            # 方案 R2 = C + C12 + E2 + 量价背离收紧（2026-07-22 强化）：
            #   C  = 偏离 ma60>20% AND ATR>3%（方案 C，原 h5 主体）
            #   C12 = 均线附近假突破(dev_ma60∈(1.0,1.1] AND drawdown_hh20<-0.02)
            #   E2 = 布林上轨外 AND ATR>3%（新增）：close>BB_upper=close.rolling(20).mean()+2σ
            #   量价背离收紧 = price_vol_div==1 AND ATR>2.5%（新增，ATR 从 0.03 收紧到 0.025）
            # h5 条件 = 偏离 ma60>20% AND ATR(14)/close>3% 双条件精准过滤（方案 C，2026-07-22 修正标注：原 88bd0eb3 commit message 误用 A 模板，实际代码即方案 C，与 L715 方案 C 一致）。
            # 调研依据 /tmp/peak_filter_combos.py::h5 拆分：
            #   - ATR>0.03 真过滤：滤中套牢率 20.05% >> 保留套牢率 9.45%，确实把高波动假突破标灰
            #   - 量价背离误杀元凶：滤中套牢率 8.96% < 保留 9.45%（把好信号误标灰），故去掉
            # 改前 (atr_pct>0.03)|(price_vol_div==1) 滤率 29.4% -> 改后 (atr_pct>0.03) 滤率 10.05%
            # 预期：总收益 167.3 -> 190.9 (+23.6)，滤中套牢 23.84%（ATR 单独贡献）
            # 2026-07-22 真过滤上线：原预览模式（标灰展示不删除）改为真 drop，buy_special_filtered 类型废弃。
            # 调研依据 /tmp/peak_filter_backtest.py：close+2%容差(方案A升级) OR R2 真过滤 组合滤率10.66%、
            #   trap-1.43pp(12.83%->11.40%)、win+0.6pp、pf+0.04、误杀55.82%最低、mean持平。
            # R2 强化（2026-07-22）：/tmp/r2_c12_verify.py 实测 R2(C|E2|PV 不含C12) 滤率 7.87%/滤中套牢 26.50%/滤后10d+1.638%；
            #   R2+C12 滤率 14.24%/滤中套牢 23.31%/滤后套牢 11.09%(基线 12.83%)/滤后 10d+1.731%(基线 +1.656%)。
            #   E2 命中 188(独占42), PV 命中 428(独占297), C12 命中 846(独占821 最大)；三项叠加基本不误杀好信号。
            # atr14 已在 L655 算过（Wilder 14 周期，同 peak_filter_backtest.py L36-42 口径）；amount 用 load_index_amount。
            # 性能优化（2026-07-25）：amount 复用 _load_index_ohlc_amount 已查的 amount_raw
            amount = amount_raw.reindex(close.index)
            atr_pct = atr14 / close
            # price_vol_div 计算保留（h5 不再用，未来可能复用于其他过滤档）：
            #   5 日价涨（close/close.shift(5)-1 > 0）且 近 5 日至少 3 日 amount < MA5(amount)。
            if amount.dropna().empty:
                price_vol_div = pd.Series(0, index=close.index, dtype=int)
            else:
                amt_ma5 = amount.rolling(5).mean()
                price_5d_chg = close / close.shift(5) - 1
                amt_below_ma5 = (amount < amt_ma5).astype(int)
                amt_below_5d = amt_below_ma5.rolling(5).sum()
                price_vol_div = ((price_5d_chg > 0) & (amt_below_5d >= 3)).astype(int)
            # 方案 C (2026-07-22): 偏离 ma60>20% AND ATR>3% 双条件精准过滤
            # 滤率 5.02%, 滤中套牢 30.60%(最高=过滤掉的最差,精准度最高), 总收益 200.2(+32.9 vs h5)
            # 依据 /tmp/peak_filter_combos.py h7 行 + h5 优化方案文档
            # price_vol_div 计算保留(h5 不再用, 未来可能复用)
            dev_ma60 = close / ma60
            # C12 叠加（2026-07-22）：均线附近假突破 = dev_ma60∈(1.0,1.1] AND drawdown_hh20<-0.02
            #   语义：均线附近刚启动（dev≤1.1）且从近20日高点回撤超2% = 趋势未确立就回撤的假突破
            #   效果：新增标灰8%(107个),总标灰率3.5%->11.2%,滤中套牢率fwd_5=45.79%(+10.2pp)/fwd_10=48.60%(+13.8pp),3/5指数有效,不误杀好信号
            #   口径与 /tmp/h5_optimize2.py L79-80 一致：drawdown_hh20 = close/hh20-1.0
            #   (hh20=high.rolling(20).max() 不带shift, L613 已算可复用; atr3_line L657 用的带shift版本口径不同)
            drawdown_hh20 = close / hh20 - 1.0
            # E2 新增（2026-07-22 R2 强化）：布林上轨外 + 高波动
            #   bb_upper = close.rolling(20).mean() + 2 * close.rolling(20).std()
            #   above_bb_upper = (close > bb_upper).astype(int)
            #   命中 188 个，独占 42 个；命中 10d 均 -1.058% 几乎不误杀好信号
            bb_upper = close.rolling(20).mean() + 2 * close.rolling(20).std()
            above_bb_upper = (close > bb_upper).astype(int)
            # h5_filter_mask = R2 = C | C12 | E2 | 量价背离收紧
            h5_filter_mask = (
                ((dev_ma60 > 1.20) & (atr_pct > 0.03))                              # C 现状
                | ((dev_ma60 > 1.0) & (dev_ma60 <= 1.1) & (drawdown_hh20 < -0.02))  # C12 现状
                | ((above_bb_upper == 1) & (atr_pct > 0.03))                        # E2 新增
                | ((price_vol_div == 1) & (atr_pct > 0.025))                        # 量价背离收紧新增
            )
            h5_filter_mask = h5_filter_mask.fillna(False)

            # 降回撤过滤方案B（2026-07-22 第三层叠加，不替换 B4 close 站稳 + h5 R2 真过滤）：
            # 非 sh 分支: peak_dd_filter_mask = (atr_pct >= 0.025) OR (dist_from_low60 > 0.30)
            #   - atr_pct = ATR(14)/close（高波动=假突破/顶部震荡风险）
            #   - dist_from_low60 = (close - low_60) / low_60（涨多顶部=回撤空间大）
            # 调研依据 /tmp/agent-progress-drawdown-filter.md 阶段4 方案B（C7）:
            #   全集保留 12085/15809(76.5%), mdd -4.52%->-4.01%(-0.51pp), peak(<-10%) 11.34%->8.50%(-2.84pp,尖尖过滤率25%),
            #   ret20 +2.47%->+1.62%(-0.85pp 可接受); 滤除组 mdd -6.20%/peak 20.55%(精准度高)。
            # 触发分解: atr_pct>=2.5%: 1581(10.0%), dist_from_low60>30%: 3256(20.6%), 两者同时 1115, 总滤除 3722(23.5%)。
            # sh 分支（2026-07-22 小节AV C1，替代原 sh 豁免）：用 dist_from_high>=15% 替代方案 B 的 dist_from_low60>30%（后者对 sh 误滤）。
            #   核心洞察：sh 大盘趋势性强，涨多顶部(dist_from_low60>30%)常是趋势中继而非尖顶，方案 B 对 sh 误滤致
            #   mdd -3.72%->-3.91%(退化 0.19pp) + ret20 +5.27%->+1.90%(损大 3.37pp)。dist_from_high>=15% 精准滤低位假突破：
            #   dist_from_high 尖尖组 11.13% vs 非尖尖 5.59%(ratio 1.99)，>=15% 档尖尖率 23.91%(baseline 2.3 倍)、
            #   ret20 -0.43%(亏损)、bot_acc 45.65% = 典型低位假突破。
            #   C1 sh 实测(vs sh 豁免基线)：742->612(保留 82.5%)，mdd -3.72%->-3.01%(降 0.71pp)，
            #   尖尖率(<-10%) 10.38%->7.35%(降 3.02pp/29%)，bot_acc 66.04%->69.12%(升 3.08pp)，
            #   ret20 +5.27%->+6.29%(升 1.02pp，不损反升)。
            #   其他 9 指数继续方案 B 不变（均有改善或微损可接受）。
            low_60 = low.rolling(60).min()
            dist_from_low60 = (close - low_60) / low_60
            # C1 sh 专属：dist_from_high = (high_250 - close) / high_250（距 250 日高点的跌幅，>=15% = 低位假突破）
            high_250 = high.rolling(250, min_periods=1).max()
            dist_from_high = (high_250 - close) / high_250
            peak_dd_filter_mask = ((atr_pct >= 0.025) | (dist_from_low60 > 0.30)).fillna(False)
            if iid == "sh":
                # sh 用 C1|D1a 叠加（2026-07-22 小节AV 升级，原单 C1 → 叠加）：
                #   C1 高波动/距高点远（atr_pct>=2.5% OR dist_from_high>=15%）
                #     + D1a 中档共振补刀（atr_pct∈[1.8%,2.5%) AND dist_from_low60>15% AND dev_ma60>1.05）
                #   D1a 补 C1 未覆盖的"中波动+涨多+均线之上"共振区，进一步降尖尖。
                #   叠加实测（vs 单 C1）：612->503(保留 82.2%)，peak(<-10%) 7.35%->5.58%(-1.78pp)，
                #     mdd -3.72%->-2.65%(改善 1.07pp)，ret20 +6.29%->+4.31%(损 1.96pp 可接受)，
                #     bot_acc 69.12%->68.33%(-0.79pp)，keep 67.7%，Jaccard 重叠率 30.8%(C1 与 D1a 互补性强)。
                peak_dd_filter_mask = (
                    (atr_pct >= 0.025) |                        # C1 高波动
                    (dist_from_high >= 0.15) |                  # C1 距高点远
                    ((atr_pct >= 0.018) & (atr_pct < 0.025) &   # D1a 中档共振补刀
                     (dist_from_low60 > 0.15) & (dev_ma60 > 1.05))
                ).fillna(False)

        # 方案 B 标注（2026-07-06）：卖点 reason 附 vs前买 标签 + 分类（止盈/买点失败/无前买点）。
        # B1+S1（2026-07-05）：buy_aux 也算买点，更新 last_buy_close 游标。
        #   - 遇到 buy 信号：更新 last_buy_close = 该买点 close
        #   - 遇到 buy_aux 信号：也更新 last_buy_close（buy_aux 是辅买点）
        #   - 遇到 sell 信号：若 last_buy_close 存在，算 pct=(close-last_buy_close)/last_buy_close*100，
        #     pct>0 → 止盈；pct<=0 → 买点失败；若 last_buy_close 不存在 → 无前买点(趋势中)。
        # C1 与 BB 同日触发时去重：保留 C1 主买（signal='buy'），不重复发 buy_aux。
        buy_set = set(buy[buy].index)
        buy_aux_set = set(buy_aux[buy_aux].index) - buy_set  # 去重：C1 主买优先
        sell_set = set(sell[sell].index)
        # 游标扩展（2026-07-22 方案B）：buy_special/buy_backup 也算前买点，纳入主循环游标更新，
        # 使 sell reason 能标注全 4 种买点类型 [主买/辅买/追买/备买]。
        # 2026-07-22 h5 真过滤上线（尖尖逃顶方案A）：buy_special_set 排除 h5_filter_mask 命中日，
        # 被过滤信号不发也不更新游标，原 buy_special_filtered 类型废弃（前端灰 pin 渲染保留无数据不影响）。
        # 2026-07-22 降回撤过滤方案B（第三层叠加）：buy_special_set 再排除 peak_dd_filter_mask 命中日，
        # 非 sh 指数：高波动(atr_pct>=2.5%) 或 涨多顶部(dist_from_low60>30%) 不发也不更新游标。
        # sh 指数（2026-07-22 小节AV C1，替代原豁免）：高波动(atr_pct>=2.5%) 或 低位假突破(dist_from_high>=15%) 不发也不更新游标。
        #   sh peak_dd_filter_mask 已在 L810 改 C1 公式（非全 False），此处正常排除命中日（sh buy_special 742->612 保留 82.5%）。
        # 这些信号的 reason 标注仍走独立 append 循环（L872-918），主循环只更新游标。
        buy_special_set_all = set(buy_special_filt[buy_special_filt].index)
        buy_special_set = {d for d in buy_special_set_all
                           if not bool(h5_filter_mask.get(d, False))           # h5 真过滤：排除命中日
                           and not bool(peak_dd_filter_mask.get(d, False))}    # 降回撤方案B：排除高波动/涨多顶部日
        buy_backup_set = set(buy_backup_filt[buy_backup_filt].index)
        # 方案A 同日叠加过滤(2026-07-22):raw_sell_stop_set 在过滤前保存原始 stop 集合,
        # 供 buy reason 标注判断(若买点日 d 在 raw_sell_stop_set 则追加 "[同日触发ATR止损·弱势反弹]")。
        # 必须在所有 buy append (L783 buy / L805 buy_aux / L909 buy_special / L928 buy_backup) 之前定义。
        raw_sell_stop_set = set(sell_stop_loss[sell_stop_loss].index)
        last_buy_close = None  # 游标：最近一次买点 close（buy/buy_aux/buy_special/buy_backup，None=窗口内无前置买点）
        last_buy_type = None   # 游标：最近一次买点类型 key（跟随 last_buy_close 同步更新，sell reason 标 [类型] 用）
        # 同日多种买点触发时按代码顺序后更新覆盖：buy -> buy_aux -> buy_special -> buy_backup
        for date in sorted(buy_set | buy_aux_set | sell_set | buy_special_set | buy_backup_set):
            if date in buy_set:
                # 买点（C1 主买）：RSI 上穿阈值事件化；reason 标注实际阈值。
                last_buy_close = float(close.get(date)) if pd.notna(close.get(date)) else last_buy_close
                last_buy_type = "buy"
                r = rsi.get(date)
                rp = rsi_prev.get(date)
                if buy_filter == "rsi_cross_25":
                    reason = f"RSI上穿25({rp:.0f}->{r:.0f})" if pd.notna(r) and pd.notna(rp) else "RSI=NA"
                else:
                    reason = f"RSI上穿30({rp:.0f}->{r:.0f})" if pd.notna(r) and pd.notna(rp) else "RSI=NA"
                cv = cross_aligned.get(date)
                if pd.notna(cv):
                    reason += f",cross={cv:.0f}[{_cross_tag(cv)}]"
                signals.append((date, iid, "buy", reason + (" [同日触发ATR止损·弱势反弹]" if date in raw_sell_stop_set else "")))
            if date in buy_aux_set:
                # B1 辅买点：BB 下轨回归。也算买点 → 更新 last_buy_close 游标。
                last_buy_close = float(close.get(date)) if pd.notna(close.get(date)) else last_buy_close
                last_buy_type = "buy_aux"
                c = close.get(date)
                bl_v = bl_.get(date)
                r = rsi.get(date)
                parts = []
                if pd.notna(bl_v) and pd.notna(c):
                    parts.append(f"布林下轨回归(下轨{bl_v:.0f},close{c:.0f})")
                else:
                    parts.append("布林下轨回归")
                if pd.notna(r):
                    parts.append(f"RSI={r:.0f}")
                if buy_aux_filter == "rsi_cross_40":
                    parts.append("RSI[上穿40]")
                if buy_aux_filter == "close_above_bl_2pct":
                    parts.append("反弹[2%]")
                cv = cross_aligned.get(date)
                if pd.notna(cv):
                    parts.append(f"cross={cv:.0f}[{_cross_tag(cv)}]")
                signals.append((date, iid, "buy_aux", ", ".join(parts) + (" [同日触发ATR止损·弱势反弹]" if date in raw_sell_stop_set else "")))
            if date in buy_special_set:
                # 特买/追买也算前买点 -> 更新游标（reason 标注走独立 append 循环 L872-899）。
                # 2026-07-22 h5 真过滤上线：buy_special_set 已排除 h5_filter_mask 命中日，
                # 此处进来的都是真发信号的 buy_special，last_buy_type 固定 "buy_special"。
                c = close.get(date)
                if pd.notna(c):
                    last_buy_close = float(c)
                last_buy_type = "buy_special"
            if date in buy_backup_set:
                # 备买也算前买点 -> 更新游标（reason 标注走独立 append 循环 L900-918）。
                c = close.get(date)
                if pd.notna(c):
                    last_buy_close = float(c)
                last_buy_type = "buy_backup"
            if date in sell_set:
                # 卖点（D1+S1）：close 从近 20 日 high 之 max 回落 5%，且 close>MA60（多头才放卖）。
                h = hh20.get(date)
                t = thresh.get(date)
                c = close.get(date)
                m = ma60.get(date)
                r = rsi.get(date)
                parts = []
                if pd.notna(h) and pd.notna(t) and pd.notna(c):
                    parts.append(f"20日高回落5%(高{h:.0f}->阈{t:.0f},close{c:.0f})")
                else:
                    parts.append("20日高回落5%")
                if pd.notna(r):
                    parts.append(f"RSI={r:.0f}")  # RSI 降级为参考标签，不作触发
                cv = cross_aligned.get(date)
                if pd.notna(cv):
                    parts.append(f"cross={cv:.0f}[{_cross_tag(cv)}]")  # cross 软分级参考
                # S1 趋势过滤标签
                if pd.notna(m):
                    parts.append(f"MA60={m:.0f}[趋势过滤]")
                # MACD 死叉确认标签（方案 B，2026-07-05）：DIF<DEA 动量转弱确认
                dv = dif.get(date)
                ev = dea.get(date)
                if pd.notna(dv) and pd.notna(ev):
                    parts.append(f"MACD=DIF{dv:.0f}/DEA{ev:.0f}[死叉确认]")
                # vs前买 标注（方案 B）：按 close vs last_buy_close 分类，标 [买点类型] 前缀
                # （2026-07-22 加 last_buy_type 游标，类型来自前买点：buy->主买/buy_aux->辅买）
                if last_buy_close is not None and pd.notna(c):
                    pct = (float(c) - last_buy_close) / last_buy_close * 100
                    sign = "+" if pct >= 0 else ""
                    tag = "止盈" if pct > 0 else "买点失败"
                    type_cn = _buy_type_cn(last_buy_type)
                    parts.append(f"vs前买[{type_cn}]{sign}{pct:.2f}%[{tag}]")
                else:
                    parts.append("无前买点[趋势中]")
                signals.append((date, iid, "sell", ", ".join(parts)))

        # 特买 buy_special Donchian20_up + B4_hold5d 过滤 + 备买 buy_backup Supertrend_buy +
        # 二次确认过滤 + sell_stop_loss ATR×{atr_mult} Chandelier Exit 止损 独立 append（不去重，叠加多色 pin，
        # 独立计算不影响 buy/buy_aux/sell）。趋势跟踪类，与 C1/B1 均值回归类互补。
        # 注：buy_special_set/buy_backup_set 已在主循环前 L764-765 定义（游标扩展共用）。
        sell_stop_set = set(raw_sell_stop_set)  # 复用 L769 raw_sell_stop_set(方案A),后续 L880 同日叠加过滤
        # === 第一个止损卖过滤(2026-07-20 追买保护)===
        # 每个买入信号开持仓窗口 [信号日, 下一个买入日前),窗口内只保留第一个 sell_stop_loss,
        # 无前置买入的止损全过滤。sell_stop_loss 与 buy 独立(L794-799),不破坏买卖配对。
        # D3 注:2026-07-22 h5 真过滤上线后 buy_special_set 已排除 h5_filter_mask 命中日,
        # 被过滤信号不算窗口起点,严格 D3 自动满足（原预览模式注释作废）。
        all_buy_dates = sorted(buy_set | buy_aux_set | buy_backup_set | buy_special_set)
        filtered_stop_set = set()
        for i, bd in enumerate(all_buy_dates):
            # 日期为 YYYYMMDD 字符串(来自 index_daily),用字符串哨兵替代 pd.Timestamp.max
            window_end = all_buy_dates[i+1] if i+1 < len(all_buy_dates) else "99991231"
            stops_in_window = sorted(d for d in sell_stop_set if bd <= d < window_end)
            if stops_in_window:
                filtered_stop_set.add(stops_in_window[0])
        # === 同日叠加过滤(方案A 2026-07-22)===
        # 60-68% sell_stop_loss 与 buy 同日触发(深熊反弹初期 RSI上穿30 + close<atr3_line 矛盾信号),
        # 买入日不该止损,过滤掉与 buy 同日的 stop(raw sell_stop_set 保留在 L769 供 buy reason 标注判断)
        # 2026-07-22 首次跌破修复后:buy 同日 first-break = price 当日首次跌破 Chandelier 线(RSI 说超卖反弹
        # 但价格刚破支撑 = 矛盾确认),过滤逻辑仍成立。修复前 BUG(below==first_break)过度过滤(买日常 below),
        # 修复后同日 first-break 更少 -> 过滤更少 -> 最终窗口化信号数略升(csi_div 64->86)但每个都是真首次跌破。
        buy_dates_set = set(all_buy_dates)
        sell_stop_set = {d for d in filtered_stop_set if d not in buy_dates_set}
        # 突破日/翻多日数据 vectorized 取（shift 后在信号日读取，对应 bd=t-5 / bd=t-3）
        don_upper_shift5 = don_upper.shift(5)  # 突破日的前高
        close_shift5 = close.shift(5)  # 突破日 close
        st_line_shift3 = st_line.shift(3)  # 翻多日 ST 支撑线
        close_shift3 = close.shift(3)  # 翻多日 close
        for date in sorted(buy_special_set):
            # 特买：唐奇安20日上轨突破 + B4_hold5d 过滤（延后5日触发）。reason 标注突破日前高 +
            # 突破日 close + 信号日 close + cross 软分级参考。
            # 2026-07-22 h5 真过滤上线（尖尖逃顶方案A）：buy_special_set 已在 L794 排除 h5_filter_mask
            # 命中日，此处进来的都是真发信号的 buy_special。原 buy_special_filtered 预览标灰改为真 drop，
            # 命中 h5 的信号不发也不 append（降套牢优先，符合"尖尖逃顶"诉求）。
            c_now = close.get(date)  # 信号日（=突破日+5）close
            du = don_upper_shift5.get(date)  # 突破日的前高
            c_break = close_shift5.get(date)  # 突破日 close
            parts = []
            if pd.notna(du) and pd.notna(c_break):
                parts.append(f"唐奇安20日上轨突破(前高{du:.0f},close{c_break:.0f})")
            else:
                parts.append("唐奇安20日上轨突破")
            parts.append("+5日站稳确认")  # B4_hold5d 过滤（close+2%容差）
            if pd.notna(c_now):
                parts.append(f"确认日close{c_now:.0f}")
            cv = cross_aligned.get(date)
            if pd.notna(cv):
                parts.append(f"cross={cv:.0f}[{_cross_tag(cv)}]")
            parts.append("[指数]")
            reason = ", ".join(parts)
            # 方案A(2026-07-22):同日触发 ATR 止损 -> 追加弱势反弹预警
            if date in raw_sell_stop_set:
                reason += " [同日触发ATR止损·弱势反弹]"
            signals.append((date, iid, "buy_special", reason))
        for date in sorted(buy_backup_set):
            # 备买：Supertrend ATR(10)×3 翻多 + 二次确认过滤（延后3日触发）。reason 标注翻多日
            # ST 支撑 + 翻多日 close + 信号日 close + cross 软分级参考。
            c_now = close.get(date)  # 信号日（=翻多日+3）close
            sv = st_line_shift3.get(date)  # 翻多日 ST 支撑线
            c_flip = close_shift3.get(date)  # 翻多日 close
            parts = []
            if pd.notna(sv) and pd.notna(c_flip):
                parts.append(f"Supertrend ATR(10)×3 翻多(ST支撑{sv:.0f},close{c_flip:.0f})")
            else:
                parts.append("Supertrend ATR(10)×3 翻多")
            parts.append("+3日二次确认")  # 二次确认过滤
            if pd.notna(c_now):
                parts.append(f"确认日close{c_now:.0f}")
            cv = cross_aligned.get(date)
            if pd.notna(cv):
                parts.append(f"cross={cv:.0f}[{_cross_tag(cv)}]")
            parts.append("[指数]")
            signals.append((date, iid, "buy_backup", ", ".join(parts) + (" [同日触发ATR止损·弱势反弹]" if date in raw_sell_stop_set else "")))
        for date in sorted(sell_stop_set):
            # 止损卖：ATR×{atr_mult} Chandelier Exit 首次跌破（从近20日最高价回撤 atr_mult*ATR）。
            # reason 标注 ATR 倍数 + 线 + close + cross（2026-07-22: 倍数动态显示，csi_div=4.5 其他=3.5）。
            c = close.get(date)
            al = atr3_line.get(date)
            av = atr14.get(date)
            parts = []
            if pd.notna(al) and pd.notna(c) and pd.notna(av):
                parts.append(f"ATR×{atr_mult:g}止损(ATR={av:.2f}, 线={al:.0f}, close={c:.0f})")
            else:
                parts.append(f"ATR×{atr_mult:g}止损")
            cv = cross_aligned.get(date)
            if pd.notna(cv):
                parts.append(f"cross={cv:.0f}[{_cross_tag(cv)}]")
            parts.append("[指数]")
            signals.append((date, iid, "sell_stop_loss", ", ".join(parts)))

        # 国债三品种波段仓位管理信号(2026-07-24): 替代 D1 sell=0 无理由(国债波动小 D1 从不触发)。
        # 与标准 buy/buy_aux/sell/buy_special/buy_backup/sell_stop_loss 并存
        # (signal_daily 主键 date+index_id+signal,减仓/止损 if/elif 互斥,同天同品种最多1条 sell 不冲突)。
        # 减仓/止损 -> "sell"(alert_score sell_cnt 按日 COUNT 计入); 接回 -> "buy_aux"(买点提示);
        # 持有 -> "band_hold"(新类型,alert_score 不影响)。
        # 实盘化: 近60天每天1条信号(与其他信号算全历史一致),前端走势图可回放历史减仓/接回时点。
        # 2026-07-24 修复: 原只算最新1天,store() DELETE 重算致历史波段信号每天被覆盖。
        if iid in CGB_BAND_PARAMS:
            band_list = compute_band_signal(iid, CGB_BAND_PARAMS[iid])
            if band_list:
                sig_map = {"减仓": "sell", "止损": "sell", "接回": "buy_aux", "持有": "band_hold"}
                for band in band_list:
                    sig_type = sig_map[band["signal"]]
                    signals.append((band["date"], iid, sig_type, band["reason"]))

    # B 扩展：全球指标 + 情绪分数 signals（value 当 close，按 09 回测推荐规则 + B1+S1）
    for mid in GLOBAL_METRIC_IDS:
        value = load_metric_value(mid)
        if value.empty:
            continue
        skip_buy = mid in _SKIP_BUY_IDS  # usdcnh 买点失效（干预市）
        skip_sell = mid in _SKIP_SELL_IDS  # cn_us_spread 卖点反向
        sell_ntf = sell_no_trend_filters.get(f"g.{mid}", False)  # usdcnh 去趋势过滤
        signals.extend(_compute_value_signals(value, f"g.{mid}", skip_buy=skip_buy, skip_sell=skip_sell, kind="指标",
                                              buy_aux_filter=buy_aux_filters.get(f"g.{mid}"),
                                              sell_no_trend_filter=sell_ntf))
    for scid in SCORE_IDS:
        value = load_score_value(scid)
        if value.empty:
            continue
        signals.extend(_compute_value_signals(value, f"s.{scid}", skip_buy=(scid == "a_sentiment"),
                                              kind="情绪分", buy_aux_filter=buy_aux_filters.get(f"s.{scid}")))

    return signals


def store(signals) -> int:
    conn = get_conn()
    conn.execute("DELETE FROM signal_daily")  # 信号逻辑变更，清空重算
    # INSERT OR REPLACE: 全历史 band 信号(接回->buy_aux)可能与标准 buy_aux(布林下轨回归)
    # 同天同品种冲突(30个, cgb_idx 历史)。band 信号后 append, 覆盖标准 buy_aux
    # (cgb 波段仓管是国债主要信号, 有 ratio 仓位比例)。其他品种无 band 无影响。
    conn.executemany(
        "INSERT OR REPLACE INTO signal_daily (date, index_id, signal, reason) VALUES (?,?,?,?)",
        signals,
    )
    conn.commit()
    conn.close()
    return len(signals)
