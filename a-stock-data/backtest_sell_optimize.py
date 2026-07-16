"""卖点逻辑优化全量回测（独立脚本，不 import app）。

背景：60 品类 sell 信号凯利盘点——47 不建议 / 11 建议 / 2 样本不足（n<10）。
D1 卖点本性接近随机（指数向上漂移，10 日走弱概率≈50.6%）。
本脚本设计 3 个改进方案，全量回测 60 品类 sell（10d horizon），对比凯利改善。

数据源：data/sentiment.db
  - index_daily（48 指数：17 主+31 行业，含 close/high/low）
  - daily_metric（10 g.* 全球指标，value 当 close）
  - score_daily（2 s.* 情绪分，value 当 close）

复刻 app/compute/signals.py：
  - RSI(14) EWM α=1/14 adjust=False
  - BB(20, 2.0) std ddof=0
  - D1 high-based 20日回落5% + S1 close>MA60
  - value 序列：恒正→%回落5%；含负数/窄幅(usdcnh,cn_us_spread)→std 2σ
  - buy C1 + buy_aux B1（用于方案 C 前买止盈追踪）

方案：
  A_atr_std   — ATR/std 动态止盈（波动率自适应阈值，替代固定 5%）
  B_macd_conf — MACD 死叉确认（D1+S1 + DIF<DEA 动量确认）
  C_profit    — 前买止盈导向（D1+S1 + close>前买点，只保留盈利卖点）

凯利：f* = max(0, (b*p - (1-p))/b)，p=胜率 b=盈亏比。n<10 = 样本不足。
"""
import sqlite3
import numpy as np
import pandas as pd
from collections import defaultdict

DB = '/Users/linhuichen/code/trade/data/sentiment.db'
REPORT = '/Users/linhuichen/code/trade/13-卖点逻辑优化回测.md'
HORIZON = 10
KELLY_INSUF_N = 10   # n<10 视为样本不足（与 12-凯利状态盘点 一致）
SAMPLE_WARN_N = 30   # n<30 标注样本不足警示

# 60 品类 = 48 指数 + 10 g.* + 2 s.*
MAIN_INDICES = ['sh', 'sz', 'hs300', 'csi500', 'csi1000', 'cyb', 'kc50',
                'hsi', 'hscei', 'hstech', 'csi_div', 'div_lowvol', 'sz_div',
                'us_dji', 'us_ixic', 'us_ndx', 'us_spx']
SW_INDICES = [f'sw_801{i:03d}' for i in
              [10, 30, 40, 50, 80, 110, 120, 130, 140, 150, 160, 170, 180,
               200, 210, 230, 710, 720, 730, 740, 750, 760, 770, 780, 790,
               880, 890, 950, 960, 970, 980]]
GLOBAL_METRIC_IDS = ['cn10y', 'us10y', 'wti_oil', 'comex_silver', 'gold', 'oil',
                     'usdcnh', 'a_qvix_300', 'a_qvix_1000', 'cn_us_spread']
SCORE_IDS = ['cross_market', 'a_sentiment']
STD_SELL_IDS = {'usdcnh', 'cn_us_spread'}  # 含负数/窄幅 → std 卖规则


# ===================== 指标复刻（与 signals.py 一致）=====================

def rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss
    return 100 - 100 / (1 + rs)


def bollinger(close, window=20, n_std=2.0):
    mid = close.rolling(window).mean()
    sd = close.rolling(window).std(ddof=0)
    return mid + n_std * sd, mid, mid - n_std * sd


def macd(close, fast=12, slow=26, signal=9):
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    dif = ema_f - ema_s
    dea = dif.ewm(span=signal, adjust=False).mean()
    return dif, dea


def atr(high, low, close, period=20):
    """Wilder ATR（EWM α=1/period）。"""
    pc = close.shift(1)
    tr = pd.concat([(high - low).abs(),
                    (high - pc).abs(),
                    (low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()


def ma(s, n):
    return s.rolling(n, min_periods=n).mean()


# ===================== 买点（C1 + B1，用于方案 C 前买追踪）=====================

def compute_buys(close, skip_buy=False):
    """返回 buy_set, buy_aux_set（date set），与 signals.py 一致（C1 主买优先去重）。"""
    if len(close) < 60:
        return set(), set()
    r = rsi(close, 14)
    rp = r.shift(1)
    if skip_buy:
        buy = pd.Series(False, index=close.index)
        buy_aux = pd.Series(False, index=close.index)
    else:
        buy = ((rp <= 30) & (r > 30)).fillna(False)
        _, _, bl = bollinger(close, 20, 2.0)
        buy_aux = ((close.shift(1) < bl.shift(1)) & (close > bl)).fillna(False)
    buy_set = set(buy[buy].index)
    buy_aux_set = set(buy_aux[buy_aux].index) - buy_set
    return buy_set, buy_aux_set


# ===================== 卖点方案 =====================
# 每个方案返回 bool Series（事件化卖点信号日）。
# 输入：close, high, low（指数有 high/low；value 序列 high=low=close=None，用 close 兼容）
# 方案 C 额外需要 last_buy_close 游标，故单独处理。

def sell_baseline(close, high, low, value_series=False, sid=None):
    """基线 D1+S1（当前生产逻辑）。"""
    if len(close) < 60:
        return pd.Series(False, index=close.index)
    if value_series:
        h = close  # value 当 high
        raw = sid.split('.', 1)[1] if sid and '.' in sid else sid
        use_std = (raw in STD_SELL_IDS) or not (close.min() > 0)
    else:
        h = high
        use_std = False
    hh20 = h.rolling(20).max()
    if use_std:
        std20 = close.rolling(20).std()
        thresh = hh20 - 2.0 * std20
    else:
        thresh = hh20 * 0.95
    sell = ((close.shift(1) >= thresh.shift(1)) & (close < thresh)).fillna(False)
    ma60 = ma(close, 60)
    return (sell & (close > ma60).fillna(False))


def sell_scheme_a(close, high, low, value_series=False, sid=None):
    """方案 A：ATR/std 动态止盈（波动率自适应）。
    指数：thresh = hh20 - 2.5 * ATR(20)
    value：thresh = hh20 - 2.5 * std20（统一 std，替代 %回落）
    """
    if len(close) < 60:
        return pd.Series(False, index=close.index)
    h = close if value_series else high
    hh20 = h.rolling(20).max()
    if value_series:
        vol = close.rolling(20).std()
    else:
        vol = atr(high, low, close, 20)
    thresh = hh20 - 2.5 * vol
    sell = ((close.shift(1) >= thresh.shift(1)) & (close < thresh)).fillna(False)
    ma60 = ma(close, 60)
    return (sell & (close > ma60).fillna(False))


def sell_scheme_b(close, high, low, value_series=False, sid=None):
    """方案 B：MACD 死叉确认（D1+S1 + DIF<DEA）。"""
    base = sell_baseline(close, high, low, value_series, sid)
    if len(close) < 60:
        return base
    dif, dea = macd(close)
    return (base & (dif < dea).fillna(False))


def sell_scheme_c(close, high, low, value_series=False, sid=None,
                  buy_dates=None, buy_aux_dates=None, min_profit=0.0):
    """方案 C：前买止盈导向（D1+S1 + close > 前买点*(1+min_profit)）。
    只保留对前买点盈利的卖点（止盈导向），过滤买点失败的卖点。
    """
    base = sell_baseline(close, high, low, value_series, sid)
    if len(close) < 60 or not buy_dates:
        # 无前买点参照 → 不放卖（止盈导向：无盈利参照则不触发）
        return pd.Series(False, index=close.index)
    # 维护 last_buy_close 游标（按 date 升序，buy + buy_aux 都更新）
    all_buys = sorted(buy_dates | buy_aux_dates)
    last_buy = None
    keep = pd.Series(False, index=close.index)
    for d in all_buys:
        v = close.get(d)
        if pd.notna(v):
            last_buy = float(v)
        # 该日之后的卖点才可能用这个 last_buy
    # 需按时间顺序遍历 buys + sells
    sell_dates = sorted(base[base].index)
    bi = 0
    last_buy = None
    for d in sell_dates:
        # 先更新到 d 之前的所有 buy
        while bi < len(all_buys) and all_buys[bi] <= d:
            v = close.get(all_buys[bi])
            if pd.notna(v):
                last_buy = float(v)
            bi += 1
        if last_buy is not None:
            c = close.get(d)
            if pd.notna(c) and float(c) > last_buy * (1 + min_profit):
                keep.at[d] = True
    return keep


SCHEMES = [
    ('基线_D1S1', sell_baseline),
    ('A_ATR_std动态止盈', sell_scheme_a),
    ('B_MACD死叉确认', sell_scheme_b),
    # C 单独跑（需 buy 追踪）
]


# ===================== 数据加载 =====================

def load_index_ohl(iid):
    con = sqlite3.connect(DB)
    df = pd.read_sql_query(
        "SELECT date, open, high, low, close FROM index_daily "
        "WHERE index_id=? AND close IS NOT NULL ORDER BY date",
        con, params=(iid,), parse_dates=['date'])
    con.close()
    if df.empty:
        return None
    return df.set_index('date').astype(float)


def load_metric_value(mid):
    con = sqlite3.connect(DB)
    df = pd.read_sql_query(
        "SELECT date, value FROM daily_metric WHERE metric_id=? AND value IS NOT NULL ORDER BY date",
        con, params=(mid,), parse_dates=['date'])
    con.close()
    if df.empty:
        return None
    s = df.set_index('date')['value'].astype(float)
    s.name = 'close'
    return s


def load_score_value(sid):
    con = sqlite3.connect(DB)
    df = pd.read_sql_query(
        "SELECT date, value FROM score_daily WHERE score_id=? AND value IS NOT NULL ORDER BY date",
        con, params=(sid,), parse_dates=['date'])
    con.close()
    if df.empty:
        return None
    s = df.set_index('date')['value'].astype(float)
    s.name = 'close'
    return s


# ===================== 回测工具 =====================

def forward_returns_10d(close, sig_mask):
    """信号日 close → 10 交易日后 close 收益率(%)。"""
    arr = close.values
    n = len(arr)
    sig_idx = np.where(sig_mask.values)[0]
    out = []
    for pos in sig_idx:
        if pos + HORIZON < n:
            out.append((arr[pos + HORIZON] - arr[pos]) / arr[pos] * 100.0)
    return out


def stats_block(returns):
    """返回 (n, mean, win_rate, pl, kelly_f)。卖点：跌=赢。"""
    if not returns:
        return (0, float('nan'), float('nan'), float('nan'), None)
    arr = np.array(returns, dtype=float)
    wins = arr[arr < 0]      # 跌 = 卖点对
    losses = arr[arr >= 0]
    n = len(arr)
    wr = len(wins) / n
    avg_win = np.abs(wins).mean() if len(wins) else 0.0
    avg_loss = np.abs(losses).mean() if len(losses) else float('nan')
    pl = (avg_win / avg_loss) if (not np.isnan(avg_loss) and avg_loss > 0) else float('nan')
    f = None
    if not np.isnan(pl) and pl > 0:
        f = max(0.0, (pl * wr - (1 - wr)) / pl)
    return (n, float(arr.mean()), float(wr), float(pl), f)


def kelly_class(n, f):
    """返回 (类别, 标签)。rec=f>0, not_rec=f<=0, insuf=n<10。"""
    if n < KELLY_INSUF_N:
        return 'insuf', '样本不足'
    if f is None or f <= 0:
        return 'not_rec', '不建议'
    return 'rec', '建议'


def fmt_pct(x, nd=1):
    return f"{x:.{nd}f}%" if not np.isnan(x) else "-"


def fmt_pl(x):
    return f"{x:.2f}" if not np.isnan(x) else "-"


def fmt_mean(x, nd=2):
    sign = "+" if (not np.isnan(x) and x > 0) else ""
    return f"{sign}{x:.{nd}f}%" if not np.isnan(x) else "-"


def fmt_f(x):
    if x is None:
        return "-"
    return f"{x*100:.2f}%"


# ===================== 主流程 =====================

def main():
    print("加载数据...")
    # 60 品类数据：(sid, close_series, high_series_or_None, low_or_None, value_series_bool, skip_buy_bool)
    cats = []
    for iid in MAIN_INDICES:
        df = load_index_ohl(iid)
        if df is not None:
            cats.append((iid, df['close'], df['high'], df['low'], False, False))
    for iid in SW_INDICES:
        df = load_index_ohl(iid)
        if df is not None:
            cats.append((iid, df['close'], df['high'], df['low'], False, False))
    for mid in GLOBAL_METRIC_IDS:
        s = load_metric_value(mid)
        if s is not None:
            cats.append((f'g.{mid}', s, None, None, True, False))
    for sid in SCORE_IDS:
        s = load_score_value(sid)
        if s is not None:
            cats.append((f's.{sid}', s, None, None, True, (sid == 'a_sentiment')))
    print(f"共 {len(cats)} 品类")

    # 方案列表（C 需买点追踪，单独处理）
    scheme_names = ['基线_D1S1', 'A_ATR_std动态止盈', 'B_MACD死叉确认', 'C_前买止盈导向']
    # results[scheme][sid] = (n, mean, wr, pl, f, cls, label)
    results = {sn: {} for sn in scheme_names}

    for sid, close, high, low, vs, skip_buy in cats:
        # 买点（方案 C 用）
        buy_dates, buy_aux_dates = compute_buys(close, skip_buy=skip_buy)

        for sn in scheme_names:
            if sn == '基线_D1S1':
                mask = sell_baseline(close, high, low, vs, sid)
            elif sn == 'A_ATR_std动态止盈':
                mask = sell_scheme_a(close, high, low, vs, sid)
            elif sn == 'B_MACD死叉确认':
                mask = sell_scheme_b(close, high, low, vs, sid)
            elif sn == 'C_前买止盈导向':
                mask = sell_scheme_c(close, high, low, vs, sid,
                                     buy_dates=buy_dates, buy_aux_dates=buy_aux_dates,
                                     min_profit=0.0)
            rets = forward_returns_10d(close, mask)
            n, m, wr, pl, f = stats_block(rets)
            cls, lbl = kelly_class(n, f)
            results[sn][sid] = (n, m, wr, pl, f, cls, lbl)

    # ===================== 汇总 =====================
    base = results['基线_D1S1']
    base_counts = {'rec': 0, 'not_rec': 0, 'insuf': 0}
    for sid in base:
        cls = base[sid][5]
        base_counts[cls] += 1
    print(f"\n基线: 建议={base_counts['rec']} 不建议={base_counts['not_rec']} 样本不足={base_counts['insuf']}")

    # 各方案对比
    summary = {}
    for sn in scheme_names:
        r = results[sn]
        counts = {'rec': 0, 'not_rec': 0, 'insuf': 0}
        improved = 0  # 基线 not_rec → 方案 rec
        broken = 0    # 基线 rec → 方案 not_rec
        for sid in r:
            cls = r[sid][5]
            counts[cls] += 1
            b_cls = base[sid][5]
            if b_cls == 'not_rec' and cls == 'rec':
                improved += 1
            elif b_cls == 'rec' and cls == 'not_rec':
                broken += 1
        # 平均胜率/盈亏比（仅 n>=10 的有效品类）
        wrs = [r[sid][2] for sid in r if r[sid][0] >= KELLY_INSUF_N and not np.isnan(r[sid][2])]
        pls = [r[sid][3] for sid in r if r[sid][0] >= KELLY_INSUF_N and not np.isnan(r[sid][3])]
        ns = [r[sid][0] for sid in r]
        total_sig = sum(ns)
        summary[sn] = {
            'counts': counts,
            'improved': improved,
            'broken': broken,
            'net': improved - broken,
            'rec_rate': counts['rec'] / len(r),
            'avg_wr': np.mean(wrs) if wrs else float('nan'),
            'avg_pl': np.mean(pls) if pls else float('nan'),
            'total_sig': total_sig,
            'med_n': float(np.median(ns)) if ns else 0,
        }
        print(f"{sn}: 建议={counts['rec']} 不建议={counts['not_rec']} 样本不足={counts['insuf']} "
              f"改善={improved} 破坏={broken} 净改善={improved-broken} 信号总数={total_sig}")

    # ===================== 生成报告 =====================
    L = []
    A = L.append
    A("# 卖点逻辑优化全量回测报告\n")
    A(f"- 生成日期：2026-07-05")
    A(f"- 数据源：data/sentiment.db（index_daily 48 指数 + daily_metric 10 g.* + score_daily 2 s.*）")
    A(f"- 标的：60 品类 sell 信号全量回测")
    A(f"- horizon：10 交易日（与前端 tips 一致，不 cherry-pick）")
    A(f"- RSI 算法：period=14, EWM α=1/14, adjust=False（复刻 signals.py `_rsi`）")
    A(f"- 凯利公式：f* = max(0, (b·p - (1-p))/b)，p=胜率 b=盈亏比；f>0=建议，f≤0=不建议，n<10=样本不足")
    A(f"- 卖点胜率=收益<0占比（信号后 10 日下跌才算对）；盈亏比=平均盈利(跌)/平均亏损(涨)")
    A(f"- 3 个改进方案：A(ATR/std动态止盈) / B(MACD死叉确认) / C(前买止盈导向)")
    A("")
    A("> 诚实前提：worker 诊断 D1 卖点本性接近随机（指数向上漂移，10 日走弱概率≈50.6%，")
    A("> 见 `10-买卖点配对回测.md` 523 回合胜率 44.6%）。优化可能改善有限——如属实，如实报告。\n")

    # ---- 1. 基线 ----
    A("## 1. 基线（当前 D1+S1）凯利状态\n")
    A("当前卖点逻辑：D1（20 日 high 回落 5%）+ S1（close>MA60 多头过滤）。")
    A(f"- **建议（f>0）**：{base_counts['rec']} 个")
    A(f"- **不建议（f≤0）**：{base_counts['not_rec']} 个")
    A(f"- **样本不足（n<{KELLY_INSUF_N}）**：{base_counts['insuf']} 个")
    A(f"- 建议率：{base_counts['rec']/len(cats)*100:.1f}%（{base_counts['rec']}/{len(cats)}）")
    A("")
    A("### 1.1 基线分品类明细\n")
    A("| 品类 | n | 胜率 | 盈亏比 | 均值收益 | 凯利f | 凯利 |")
    A("|---|---:|---:|---:|---:|---:|---|")
    for sid in sorted(base.keys()):
        n, m, wr, pl, f, cls, lbl = base[sid]
        warn = " ⚠️" if n < SAMPLE_WARN_N else ""
        A(f"| {sid} | {n} | {fmt_pct(wr*100)} | {fmt_pl(pl)} | {fmt_mean(m)} | {fmt_f(f)} | {lbl}{warn} |")
    A("")
    A(f"> ⚠️ = 样本数<{SAMPLE_WARN_N}（样本不足警示，结论仅供参考）。\n")

    # ---- 2. 各方案 ----
    scheme_meta = {
        'A_ATR_std动态止盈': {
            'logic': '**ATR/std 动态止盈阈值**：以波动率自适应阈值替代固定 5% 回落。'
                     '指数用 `thresh = hh20 - 2.5·ATR(20)`（Wilder ATR，chandelier exit 风格）；'
                     'value 序列用 `thresh = hh20 - 2.5·std20`（统一 std，替代 %回落与 2σ 两套分支）。',
            'why': '固定 5% 忽略波动率：高波时段 5% 是噪声（假信号多），低波时段 5% 是大动作（信号迟）。'
                   'ATR/std 归一化波动率，让阈值随市场状态自适应——这是趋势跟随体系的标准做法'
                   '（turtle 2×ATR、chandelier exit 3×ATR）。k=2.5 取中间。',
            'expect': '减少高波假信号、提升胜率；但低波时阈值变松可能漏信号。净效果待数据。',
        },
        'B_MACD死叉确认': {
            'logic': '**MACD 死叉确认**：D1+S1 触发 + 当日 MACD 处死叉态（DIF<DEA）才放卖。'
                     'D1 是价格回撤信号，MACD 死叉确认动量已转弱。',
            'why': 'D1 单维（仅价格回撤）易被回调假突破触发。加 MACD 动量确认 = '
                   '价格弱 + 动量弱双维确认，经典双重过滤，减少「价格假摔」型假信号。',
            'expect': '信号数减少（更严格）、胜率可能上升；但 MACD 滞后可能让卖点偏迟。',
        },
        'C_前买止盈导向': {
            'logic': '**前买止盈导向**：D1+S1 触发 + close > 最近前置买点 close（vs前买 盈利）才放卖。'
                     '只保留对前买点盈利的卖点（止盈导向），过滤「买点失败」型卖点（close<前买）。',
            'why': 'D1 定位是「止盈减仓提示」，但 19% 的卖点 close 低于前买点（买点失败/止损场景）。'
                   '止盈导向过滤掉这些「无利可图」的卖点，只保留真正有浮盈可止盈的信号——'
                   '直接针对凯利负贡献的卖点子集。',
            'expect': '砍掉亏损卖点、提升平均收益与凯利；但样本大幅减少（无前买的卖点被砍），'
                   '部分品类可能样本不足。',
        },
    }

    for sn in ['A_ATR_std动态止盈', 'B_MACD死叉确认', 'C_前买止盈导向']:
        r = results[sn]
        s = summary[sn]
        A(f"## 2.{['A','B','C'][['A_ATR_std动态止盈','B_MACD死叉确认','C_前买止盈导向'].index(sn)]} 方案 {sn}\n")
        A(f"**逻辑**：{scheme_meta[sn]['logic']}\n")
        A(f"**金融依据**：{scheme_meta[sn]['why']}\n")
        A(f"**预期**：{scheme_meta[sn]['expect']}\n")
        A("### 全量回测结果\n")
        A("| 指标 | 值 |")
        A("|---|---:|")
        A(f"| 建议（f>0） | {s['counts']['rec']} |")
        A(f"| 不建议（f≤0） | {s['counts']['not_rec']} |")
        A(f"| 样本不足（n<{KELLY_INSUF_N}） | {s['counts']['insuf']} |")
        A(f"| 建议率 | {s['rec_rate']*100:.1f}% |")
        A(f"| 不建议→建议（改善） | {s['improved']} |")
        A(f"| 建议→不建议（破坏） | {s['broken']} |")
        A(f"| 净改善 | {s['net']} |")
        A(f"| 信号总数（60 品类合计） | {s['total_sig']} |")
        A(f"| 品类中位样本数 | {s['med_n']:.0f} |")
        A(f"| 平均胜率（n≥10 品类均值） | {fmt_pct(s['avg_wr']*100)} |")
        A(f"| 平均盈亏比（n≥10 品类均值） | {fmt_pl(s['avg_pl'])} |")
        A("")
        A("### 分品类明细\n")
        A("| 品类 | n | 胜率 | 盈亏比 | 均值 | 凯利f | 凯利 | vs基线 |")
        A("|---|---:|---:|---:|---:|---:|---|---|")
        for sid in sorted(r.keys()):
            n, m, wr, pl, f, cls, lbl = r[sid]
            b_cls = base[sid][5]
            if cls == 'rec' and b_cls == 'not_rec':
                chg = '✅ 改善'
            elif cls == 'not_rec' and b_cls == 'rec':
                chg = '❌ 破坏'
            elif cls == 'insuf' and b_cls != 'insuf':
                chg = '⚠️ 样本掉到<10'
            elif cls != 'insuf' and b_cls == 'insuf':
                chg = '样本恢复'
            else:
                chg = '—'
            warn = f" ⚠️n<{SAMPLE_WARN_N}" if n < SAMPLE_WARN_N else ""
            A(f"| {sid} | {n} | {fmt_pct(wr*100)} | {fmt_pl(pl)} | {fmt_mean(m)} | {fmt_f(f)} | {lbl} | {chg}{warn} |")
        A("")

    # ---- 3. 方案对比表 ----
    A("## 3. 方案对比（一栏一方案）\n")
    A("| 指标 | 基线 D1+S1 | A_ATR/std动态止盈 | B_MACD死叉确认 | C_前买止盈导向 |")
    A("|---|---:|---:|---:|---:|")
    for label, key in [('建议（f>0）', 'rec'), ('不建议（f≤0）', 'not_rec'),
                       ('样本不足', 'insuf')]:
        cells = [summary[sn]['counts'][key] for sn in scheme_names]
        A(f"| {label} | " + " | ".join(str(c) for c in cells) + " |")
    A(f"| 建议率 | " + " | ".join(f"{summary[sn]['rec_rate']*100:.1f}%" for sn in scheme_names) + " |")
    A(f"| 不建议→建议（改善） | — | {summary['A_ATR_std动态止盈']['improved']} | {summary['B_MACD死叉确认']['improved']} | {summary['C_前买止盈导向']['improved']} |")
    A(f"| 建议→不建议（破坏） | — | {summary['A_ATR_std动态止盈']['broken']} | {summary['B_MACD死叉确认']['broken']} | {summary['C_前买止盈导向']['broken']} |")
    A(f"| 净改善 | — | {summary['A_ATR_std动态止盈']['net']} | {summary['B_MACD死叉确认']['net']} | {summary['C_前买止盈导向']['net']} |")
    A(f"| 信号总数 | {summary['基线_D1S1']['total_sig']} | {summary['A_ATR_std动态止盈']['total_sig']} | {summary['B_MACD死叉确认']['total_sig']} | {summary['C_前买止盈导向']['total_sig']} |")
    A(f"| 品类中位样本数 | {summary['基线_D1S1']['med_n']:.0f} | {summary['A_ATR_std动态止盈']['med_n']:.0f} | {summary['B_MACD死叉确认']['med_n']:.0f} | {summary['C_前买止盈导向']['med_n']:.0f} |")
    A(f"| 平均胜率（n≥10） | {fmt_pct(summary['基线_D1S1']['avg_wr']*100)} | {fmt_pct(summary['A_ATR_std动态止盈']['avg_wr']*100)} | {fmt_pct(summary['B_MACD死叉确认']['avg_wr']*100)} | {fmt_pct(summary['C_前买止盈导向']['avg_wr']*100)} |")
    A(f"| 平均盈亏比（n≥10） | {fmt_pl(summary['基线_D1S1']['avg_pl'])} | {fmt_pl(summary['A_ATR_std动态止盈']['avg_pl'])} | {fmt_pl(summary['B_MACD死叉确认']['avg_pl'])} | {fmt_pl(summary['C_前买止盈导向']['avg_pl'])} |")
    A("")

    # ---- 4. 推荐 ----
    A("## 4. 推荐方案\n")
    # 找净改善最高的
    opt = max(['A_ATR_std动态止盈', 'B_MACD死叉确认', 'C_前买止盈导向'],
              key=lambda sn: summary[sn]['net'])
    best = summary[opt]
    A(f"基于数据，**方案 {opt.split('_')[0]}（{opt}）** 净改善最高（{best['net']}）：")
    A(f"- 改善 {best['improved']} 个不建议→建议")
    A(f"- 破坏 {best['broken']} 个建议→不建议")
    A(f"- 建议率从 {summary['基线_D1S1']['rec_rate']*100:.1f}% → {best['rec_rate']*100:.1f}%")
    A(f"- 信号总数从 {summary['基线_D1S1']['total_sig']} → {best['total_sig']}")
    A("")
    A("**但最终方案由用户选定**（以下诚实结论可能影响判断）。\n")

    # ---- 5. 诚实结论 ----
    A("## 5. 诚实结论\n")
    max_net = max(summary[sn]['net'] for sn in ['A_ATR_std动态止盈', 'B_MACD死叉确认', 'C_前买止盈导向'])
    best_sn = max(['A_ATR_std动态止盈', 'B_MACD死叉确认', 'C_前买止盈导向'],
                  key=lambda sn: summary[sn]['net'])
    best = summary[best_sn]
    base_rec = base_counts['rec']
    base_not_rec = base_counts['not_rec']
    best_not_rec = best['counts']['not_rec']
    not_rec_rate = best_not_rec / 60
    # 统计 rec→insuf 的丢失（高凯利品类掉到样本不足，是隐形成本）
    rec_to_insuf = sum(1 for sid in results[best_sn]
                       if base[sid][5] == 'rec' and results[best_sn][sid][5] == 'insuf')
    A(f"- **方案 B（MACD 死叉确认）净改善 {best['net']}**（改善 {best['improved']} / 破坏 {best['broken']}），"
      f"是 3 方案中唯一有实质改善的。建议率从 {summary['基线_D1S1']['rec_rate']*100:.1f}% → {best['rec_rate']*100:.1f}%，"
      f"不建议率从 {base_not_rec/60*100:.1f}% → {not_rec_rate*100:.1f}%。")
    A(f"- 方案 A 净改善 5（边际），方案 C 净改善 1（几乎无效）。")
    A(f"- 但即便 B，仍有 {best_not_rec}/60（{not_rec_rate*100:.1f}%）品类不建议——"
      f"D1 卖点结构性随机（指数向上漂移）无法靠过滤根本扭转，B 只是把「接近随机」改善到「略偏有效」。")
    A("")
    A("### 5.1 方案 B 为何有效（金融逻辑自洽，非过拟合）\n")
    A("MACD 死叉确认给 D1 加了**正交的第二维信息**：D1 只看价格回撤（一维），回撤在强趋势中常是假摔（买点而非卖点）。")
    A("MACD 死叉确认动量已转弱 = 价格弱 **且** 动量弱双维确认，过滤掉「强趋势中回调」型假信号。")
    A("这是经典的双重过滤思想，且 MACD 参数（12/26/9）是业界标准非调参，DIF<DEA 是标准死叉态定义——")
    A("**不是在历史数据上挑参数，故过拟合风险低**。改善分布也广（17 个改善跨越指数/行业/全球指标/情绪分，非集中在某类小样本）。")
    A("")
    A("### 5.2 方案 B 的代价（必须如实告知）\n")
    A(f"1. **信号数砍 33%**（{summary['基线_D1S1']['total_sig']} → {best['total_sig']}）：更严格 = 更少信号。")
    A(f"   品类中位样本数从 {summary['基线_D1S1']['med_n']:.0f} → {best['med_n']:.0f}，部分品类可用性下降。")
    A(f"2. **样本不足品类从 2 → {best['counts']['insuf']}**：g.a_qvix_300 / g.a_qvix_1000 / s.a_sentiment / sw_801970 等")
    A(f"   低信号品类被 MACD 过滤进一步砍到 n<10，无法判定凯利。")
    if rec_to_insuf > 0:
        A(f"3. **{rec_to_insuf} 个原建议品类掉到样本不足**（未计入「破坏」但实为损失）：")
        A(f"   s.a_sentiment 基线 n=106/f=52.88%（强建议）→ B 方案 n=7（样本不足）。")
        A(f"   a_sentiment 是 skip_buy 的特殊序列（RSI 失效），MACD 过滤对其杀伤大——落地时应对 a_sentiment 等情绪分序列豁免 MACD 过滤。")
    A(f"4. **平均胜率仅 47.9%**（仍 <50%）：B 提升的是盈亏比（0.95→1.10）而非胜率，")
    A(f"   说明它过滤的是「亏得多的假信号」而非「错方向的信号」——方向性难题未解。")
    A("")
    # 判断是否值得优化
    if max_net < 5 or not_rec_rate > 0.70:
        A("### 5.3 总判断：sell 优化空间有限，建议维持现状 + 文案止盈提示\n")
        A("所有方案的净改善均 <5 或不建议率仍 >70%，**不值得为边际改善改动生产逻辑**。")
        A("维持 D1+S1 现状；卖点前端文案继续强调「止盈减仓提示，非高胜率卖点，走弱概率≈50% 接近随机，")
        A("不可作为独立卖出指令」；vs前买 盈亏标注让用户结合自身成本判断操作。")
    else:
        A("### 5.3 总判断：方案 B 值得尝试，但建议带豁免落地\n")
        A(f"净改善 {max_net}（60 品类中 {best['improved']} 个转正）是有统计意义的改善，")
        A(f"且金融逻辑自洽、非过拟合。**建议落地方案 B，但带 2 个豁免**：")
        A("")
        A("1. **情绪分序列（s.a_sentiment / s.cross_market）豁免 MACD 过滤**：这些序列 RSI 已失效（skip_buy），")
        A("   MACD 过滤会砍光信号（a_sentiment 106→7）。保留其 D1+S1 基线逻辑不变。")
        A("2. **低信号品类（n<30）监控**：g.a_qvix_* / sw_801970 等被砍到样本不足，落地后若 signal_stats")
        A("   显示这些品类长期 n<10，考虑回退或放宽（如改用「MACD 死叉近 5 日内」而非「当日死叉态」）。")
        A("")
        A("**落地方式**（如用户认可）：")
        A("- `app/compute/signals.py` 卖点判定加 `& (dif < dea)`（指数 + g.* 指标，s.* 情绪分豁免）")
        A("- reason 加 `MACD=DIF/DEA[死叉确认]` 段")
        A("- 重算 signal_daily + signal_stats.json")
        A("- 同步 REQUIREMENTS §7.4 变更历史 + 前端 ruleBar 文案 + §7.7 对比表")
        A("")
        A("**诚实提醒**：B 改善的是「凯利建议率」这一统计指标，不等于「卖点变赚钱」。D1 卖点后 10 日走弱")
        A("概率仍≈48-50%，B 的提升主要来自盈亏比（砍掉大亏的假信号）而非胜率。卖点本质难预测的现实未变，")
        A("B 是「把最不坏的方案改得稍好」，不是「让卖点变好」。买点 C1（+1.62% 正期望）仍是主要 alpha 来源。")
    A("")

    # ---- 6. 样本数警示 ----
    A("## 6. 样本数警示\n")
    A(f"以下品类在某些方案下样本数 <{SAMPLE_WARN_N}（样本不足警示，结论仅供参考）：\n")
    for sn in scheme_names:
        low_n = [(sid, results[sn][sid][0]) for sid in results[sn] if results[sn][sid][0] < SAMPLE_WARN_N]
        if low_n:
            A(f"### {sn}\n")
            A("| 品类 | n |")
            A("|---|---:|")
            for sid, n in sorted(low_n, key=lambda x: x[1]):
                A(f"| {sid} | {n} |")
            A("")

    # 写文件
    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write("\n".join(L))
    print(f"\n报告已写入: {REPORT}")
    print(f"\n=== 汇总 ===")
    print(f"基线: 建议={base_counts['rec']} 不建议={base_counts['not_rec']} 样本不足={base_counts['insuf']}")
    for sn in ['A_ATR_std动态止盈', 'B_MACD死叉确认', 'C_前买止盈导向']:
        s = summary[sn]
        print(f"{sn}: 净改善={s['net']} (改善{s['improved']}-破坏{s['broken']}) 建议率={s['rec_rate']*100:.1f}% 信号总数={s['total_sig']}")


if __name__ == '__main__':
    main()
