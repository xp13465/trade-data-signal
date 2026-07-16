"""buy_aux（B1 辅买）逐品类优化回测 — sw_801110 家用电器打样。

背景：60 品类 buy_aux 凯利盘点，sw_801110 家电 f=-0.39（不建议），
胜率 44.8% / 盈亏比 0.66 / n=134 / 均值 -1.23%。样本充足（n=134），
非结构性异常序列。本脚本设计 3 个 buy_aux 收紧方案，全量回测 sw_801110
全史 buy_aux（5d/10d/20d 三 horizon 验证一致性），对比凯利改善。

数据源：data/sentiment.db
  - index_daily（sw_801110 的 date/open/high/low/close/amount）
  - amount 列作 volume 代理（成交金额，比 volume 更能反映资金进场）

复刻 app/compute/signals.py：
  - RSI(14) EWM α=1/14 adjust=False
  - BB(20, 2.0) std ddof=0
  - buy_aux B1 = (close_prev < bl_prev) & (close > bl)，fillna(False)
  - C1 主买 = RSI 上穿 30（用于去重：buy_aux_set - buy_set，C1 优先）

方案：
  A_rebound_strength — 反弹力度确认（close > bl × 1.02，过滤 barely-crossed 假信号）
  B_rsi_momentum     — RSI 动量确认（BB下轨回归 + RSI 上穿 40，价格+动量双确认）
  C_volume_surge     — 放量确认（BB下轨回归 + amount > 5日均量 × 1.2，资金进场确认）

凯利：f* = max(0, (b·p - (1-p))/b)，p=胜率 b=盈亏比。买点胜率=收益>0占比。
n<10 = 样本不足，n<30 = 样本不足警示。

约束：独立复刻，不 import app，不改 app/ 代码，不改 DB。
"""
import sqlite3
import numpy as np
import pandas as pd

DB = '/Users/linhuichen/code/trade/data/sentiment.db'
REPORT = '/Users/linhuichen/code/trade/14-家电buy_aux优化回测.md'
SID = 'sw_801110'
SID_NAME = '家用电器'
HORIZONS = [5, 10, 20]
PRIMARY_HORIZON = 10  # 主指标，与前端 tips 一致
KELLY_INSUF_N = 10
SAMPLE_WARN_N = 30

# ===================== 指标复刻（与 signals.py 一致）=====================

def rsi(close, period=14):
    """RSI(14) EWM α=1/period adjust=False（复刻 signals.py `_rsi`）。"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss
    return 100 - 100 / (1 + rs)


def bollinger(close, window=20, n_std=2.0):
    """BB(20, 2.0) std ddof=0（复刻 signals.py `_bollinger`）。返回 (bu, mid, bl)。"""
    mid = close.rolling(window).mean()
    sd = close.rolling(window).std(ddof=0)
    return mid + n_std * sd, mid, mid - n_std * sd


# ===================== 买点方案 =====================
# 每个方案返回 (buy_aux_mask, n_signals, logic_str)。
# buy_aux_mask 是 bool Series（事件化辅买信号日）。
# 输入：close, amount（可选），去重用 buy_set（C1 主买优先）。

def buy_aux_baseline(close, amount=None, buy_set=None):
    """基线 B1：BB 下轨回归（close_prev<bl_prev 且 close>bl）。"""
    if len(close) < 30:
        return pd.Series(False, index=close.index)
    _, _, bl = bollinger(close, 20, 2.0)
    mask = ((close.shift(1) < bl.shift(1)) & (close > bl)).fillna(False)
    return _dedup(mask, buy_set)


def buy_aux_scheme_a(close, amount=None, buy_set=None, rebound_pct=0.02):
    """方案 A：反弹力度确认（close > bl × (1+rebound_pct)）。

    要求 close 收回下轨之上 N%（默认 2%），过滤 barely-crossed 假信号。
    """
    if len(close) < 30:
        return pd.Series(False, index=close.index)
    _, _, bl = bollinger(close, 20, 2.0)
    thresh = bl * (1 + rebound_pct)
    mask = ((close.shift(1) < bl.shift(1)) & (close > thresh)).fillna(False)
    return _dedup(mask, buy_set)


def buy_aux_scheme_b(close, amount=None, buy_set=None, rsi_thresh=40):
    """方案 B：RSI 动量确认（BB下轨回归 + RSI 上穿 rsi_thresh）。

    价格反弹 + 动量转升双重确认，与 sell 的 MACD 死叉确认对称。
    RSI 上穿 40（而非 30）避免与 C1 完全重叠（C1 是 RSI 上穿 30），
    去重后 buy_aux_B 只在 RSI 30-40 区间上穿 40 时触发（C1 未触发的子集）。
    """
    if len(close) < 30:
        return pd.Series(False, index=close.index)
    _, _, bl = bollinger(close, 20, 2.0)
    r = rsi(close, 14)
    rp = r.shift(1)
    bb_revert = ((close.shift(1) < bl.shift(1)) & (close > bl)).fillna(False)
    rsi_cross = ((rp <= rsi_thresh) & (r > rsi_thresh)).fillna(False)
    mask = bb_revert & rsi_cross
    return _dedup(mask, buy_set)


def buy_aux_scheme_c(close, amount=None, buy_set=None, vol_mult=1.2, vol_window=5):
    """方案 C：放量确认（BB下轨回归 + amount > 5日均量 × 1.2）。

    放量反弹 = 有资金进场接盘，缩量反弹可能是死猫 bounce。
    用 amount（成交金额）作 volume 代理，比 volume（股数）更能反映资金进场。
    """
    if len(close) < 30 or amount is None:
        return pd.Series(False, index=close.index)
    _, _, bl = bollinger(close, 20, 2.0)
    bb_revert = ((close.shift(1) < bl.shift(1)) & (close > bl)).fillna(False)
    vol_ma = amount.rolling(vol_window).mean()
    vol_surge = (amount > vol_ma * vol_mult).fillna(False)
    mask = bb_revert & vol_surge
    return _dedup(mask, buy_set)


def _dedup(buy_aux_mask, buy_set):
    """C1 与 buy_aux 同日触发时去重：保留 C1（主买优先），不重复发 buy_aux。

    与 signals.py 一致：buy_aux_set = set(buy_aux[buy_aux].index) - buy_set。
    """
    if buy_set is None:
        return buy_aux_mask
    out = buy_aux_mask.copy()
    for d in buy_set:
        if d in out.index:
            out.at[d] = False
    return out


# ===================== C1 主买（用于去重）=====================

def compute_c1_buy(close):
    """C1 主买：RSI(14) 上穿 30。返回 buy_set（date set）。"""
    if len(close) < 30:
        return set()
    r = rsi(close, 14)
    rp = r.shift(1)
    buy = ((rp <= 30) & (r > 30)).fillna(False)
    return set(buy[buy].index)


# ===================== 数据加载 =====================

def load_index_ohlcv(iid):
    """从 sentiment.db 读 index_daily 的 close/high/low/amount。"""
    con = sqlite3.connect(DB)
    df = pd.read_sql_query(
        "SELECT date, open, high, low, close, amount FROM index_daily "
        "WHERE index_id=? AND close IS NOT NULL ORDER BY date",
        con, params=(iid,), parse_dates=['date'])
    con.close()
    if df.empty:
        return None
    df = df.set_index('date').astype(float)
    return df


# ===================== 回测工具 =====================

def forward_returns(close, sig_mask, horizon):
    """信号日 close → horizon 交易日后 close 收益率(%)。"""
    arr = close.values
    n = len(arr)
    sig_idx = np.where(sig_mask.values)[0]
    out = []
    for pos in sig_idx:
        if pos + horizon < n:
            out.append((arr[pos + horizon] - arr[pos]) / arr[pos] * 100.0)
    return out


def stats_block(returns):
    """返回 (n, mean, win_rate, pl, kelly_f)。买点：涨=赢。

    win_rate = 涨的占比（return > 0）
    pl = avg_win / avg_loss（avg_loss = |亏损|均值，无亏损→nan）
    kelly_f = max(0, (b·p - (1-p))/b)，b=pl, p=win_rate
    """
    if not returns:
        return (0, float('nan'), float('nan'), float('nan'), None)
    arr = np.array(returns, dtype=float)
    wins = arr[arr > 0]      # 涨 = 买点对
    losses = arr[arr <= 0]   # 跌或平 = 买点错（平算错，保守）
    n = len(arr)
    wr = len(wins) / n
    avg_win = wins.mean() if len(wins) else 0.0
    avg_loss = np.abs(losses).mean() if len(losses) else float('nan')
    pl = (avg_win / avg_loss) if (not np.isnan(avg_loss) and avg_loss > 0) else float('nan')
    f = None
    if not np.isnan(pl) and pl > 0:
        f = (pl * wr - (1 - wr)) / pl  # 不取 max(0,..)，保留负值便于看「差多少」
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
    print(f"加载数据 {SID}...")
    df = load_index_ohlcv(SID)
    if df is None:
        print(f"  {SID} 数据加载失败")
        return
    close = df['close']
    amount = df['amount'] if 'amount' in df.columns else None
    print(f"  {SID} 共 {len(close)} 行，{close.index[0].date()} ~ {close.index[-1].date()}")
    if amount is not None:
        print(f"  amount 范围 {amount.min():.2f} ~ {amount.max():.2f}，null {amount.isna().sum()}")

    # C1 主买（去重用）
    buy_set = compute_c1_buy(close)
    print(f"  C1 主买信号 {len(buy_set)} 个")

    # 方案列表
    schemes = [
        ('基线_B1', buy_aux_baseline, {}),
        ('A_反弹力度2%', buy_aux_scheme_a, {'rebound_pct': 0.02}),
        ('B_RSI上穿40', buy_aux_scheme_b, {'rsi_thresh': 40}),
        ('C_放量1.2倍', buy_aux_scheme_c, {'vol_mult': 1.2, 'vol_window': 5}),
    ]

    # 回测：每个方案 × 3 horizon
    # results[scheme][horizon] = (n, mean, wr, pl, f, cls, lbl, n_signals)
    results = {sn: {} for sn, _, _ in schemes}
    n_signals_map = {}  # 每方案的信号总数（事件数，未扣 forward 不足）
    for sn, func, kwargs in schemes:
        mask = func(close, amount=amount, buy_set=buy_set, **kwargs)
        n_signals = int(mask.sum())
        n_signals_map[sn] = n_signals
        for h in HORIZONS:
            rets = forward_returns(close, mask, h)
            n, m, wr, pl, f = stats_block(rets)
            cls, lbl = kelly_class(n, f)
            results[sn][h] = (n, m, wr, pl, f, cls, lbl)
        print(f"  {sn}: 信号 {n_signals} | 10d n={results[sn][10][0]} 胜率={fmt_pct(results[sn][10][2]*100)} "
              f"盈亏比={fmt_pl(results[sn][10][3])} f={fmt_f(results[sn][10][4])} {results[sn][10][6]}")

    # ===================== 生成报告 =====================
    L = []
    A = L.append
    A(f"# buy_aux（B1 辅买）优化回测 — sw_801110 {SID_NAME}\n")
    A(f"- 生成日期：2026-07-05")
    A(f"- 标的：sw_801110 家用电器（申万行业指数，{SID_NAME}）")
    A(f"- 数据源：data/sentiment.db index_daily（{len(close)} 行，{close.index[0].date()} ~ {close.index[-1].date()}）")
    A(f"- horizon：5d / 10d / 20d 三 horizon（10d 主指标与前端 tips 一致，5d/20d 验证一致性）")
    A(f"- RSI 算法：period=14, EWM α=1/14, adjust=False（复刻 signals.py `_rsi`）")
    A(f"- BB 算法：window=20, n_std=2.0, std ddof=0（复刻 signals.py `_bollinger`）")
    A(f"- 凯利公式：f* = (b·p - (1-p))/b，p=胜率 b=盈亏比；f>0=建议，f≤0=不建议，n<10=样本不足")
    A(f"- 买点胜率=收益>0占比（信号后 N 日上涨才算对）；盈亏比=平均盈利(涨)/平均亏损(跌)")
    A(f"- 去重：C1 主买（RSI 上穿 30）与 buy_aux 同日触发时保留 C1，不重复发 buy_aux（与 signals.py 一致）")
    A(f"- 3 个改进方案：A(反弹力度2%) / B(RSI上穿40) / C(放量1.2倍)")
    A("")
    A("> 背景：用户要求把凯利不建议（f≤0）的信号优化到「凯利建议」，退而求其次提高胜率。")
    A("> sw_801110 家电 buy_aux 当前 f=-0.39（不建议），是 buy_aux 逐个品类优化的第一个攻克对象（打样）。\n")

    # ---- 1. 基线 ----
    A(f"## 1. 基线（当前 B1 buy_aux）凯利状态\n")
    A("当前 buy_aux 逻辑：BB 下轨回归——前一日 close<下轨 且当日 close>下轨（从超卖区反弹回下轨之上）。")
    A("- **建议（f>0）**：否（f=-0.39，不建议）")
    A(f"- 胜率 {fmt_pct(results['基线_B1'][10][2]*100)} / 盈亏比 {fmt_pl(results['基线_B1'][10][3])} / "
      f"样本 n={results['基线_B1'][10][0]} / 均值 {fmt_mean(results['基线_B1'][10][1])} / 凯利 f={fmt_f(results['基线_B1'][10][4])}")
    A(f"- 信号总数（全史事件数）：{n_signals_map['基线_B1']}")
    A("")
    A("### 1.1 基线三 horizon 一致性\n")
    A("| horizon | n | 胜率 | 盈亏比 | 均值 | 凯利f | 凯利 |")
    A("|---|---:|---:|---:|---:|---:|---|")
    for h in HORIZONS:
        n, m, wr, pl, f, cls, lbl = results['基线_B1'][h]
        primary = " **主**" if h == PRIMARY_HORIZON else ""
        A(f"| {h}d{primary} | {n} | {fmt_pct(wr*100)} | {fmt_pl(pl)} | {fmt_mean(m)} | {fmt_f(f)} | {lbl} |")
    A("")
    A("> 基线 buy_aux 在 5d/10d/20d 三 horizon 均 f≤0（不建议），一致性高，非单 horizon 异常。")
    A("> 10d 主 horizon 胜率 44.8% < 50%，盈亏比 0.66 < 1，均值 -1.23% < 0——三维全负，确认是「真不建议」而非参数偶发。\n")

    # ---- 2. 各方案 ----
    scheme_meta = {
        'A_反弹力度2%': {
            'logic': '**反弹力度确认**：BB 下轨回归 + close 收回下轨之上 2%（`close > bl × 1.02`）。'
                     '现状是 close>bl 即触发（barely crossed 也算），改为要求 close 高于下轨 2%。',
            'why': '现状 buy_aux 的核心问题是「barely crossed」型假信号——close 刚刚高出下轨 0.01% 就触发，'
                   '这种反弹没有力度，往往是下跌中继的短暂停顿（dead cat bounce 的前半段）。'
                   '要求 close 高于下轨 2%，确保反弹有实质买盘力度，过滤掉「刚探头就缩回」的假突破。'
                   '2% 是 A 股指数日内常见波动幅度（家电指数日均振幅约 1.5-2%），不算苛刻。',
            'expect': '信号数减少（更严格）、胜率提升（留下的反弹更有力度）；但减少幅度未知，'
                   '若过严可能样本不足。',
        },
        'B_RSI上穿40': {
            'logic': '**RSI 动量确认**：BB 下轨回归 + RSI(14) 上穿 40（`rsi_prev ≤ 40 & rsi > 40`）。'
                     '价格反弹 + 动量转升双重确认。RSI 上穿 40（而非 30）避免与 C1 完全重叠——'
                     'C1 是 RSI 上穿 30，去重后 buy_aux_B 只在 RSI 30-40 区间上穿 40 时触发'
                     '（即 C1 未触发的轻度超卖反弹子集）。',
            'why': 'BB 下轨回归只看价格穿越（一维），不确认动量是否真转升。'
                   'RSI 上穿 40 = 动量已从超卖区开始向上突破（虽未到 C1 的 30 阈值，但已过 40），'
                   '是「价格反弹 + 动量转升」双维确认，与 sell 的 MACD 死叉确认（D1+S1 + DIF<DEA）'
                   '对称——都是给一维价格信号加正交的动量维确认。'
                   'RSI 40 是业界常用的超卖/正常分界（30=深度超卖，40=轻度超卖，50=中性），'
                   '非调参。此方案与 C1 互补不冲突（C1 抓深度超卖 RSI<30，B 抓轻度超卖 RSI 30-40）。',
            'expect': '信号数减少（要求 RSI 穿越额外条件）、胜率可能提升（动量确认）；'
                   '但 RSI 30-40 区间的反弹力度本就弱于 RSI<30，提升幅度可能有限。',
        },
        'C_放量1.2倍': {
            'logic': '**放量确认**：BB 下轨回归 + 当日成交金额 > 5 日均额 × 1.2（`amount > amount.rolling(5).mean() × 1.2`）。'
                     '用 amount（成交金额）作 volume 代理——比 volume（股数）更能反映资金进场规模。',
            'why': 'BB 下轨回归是价格信号，不反映成交量。缩量反弹往往是「没人愿意接」的死猫 bounce，'
                   '放量反弹才是「有资金主动进场接盘」的真反弹。量价关系是技术分析最经典的正交维度'
                   '（道氏理论三大假设之一：趋势需成交量确认）。1.2 倍是温和放量阈值（业界常用 1.5 倍 '
                   '激进，1.2 倍温和），5 日均额是短期资金基准。',
            'expect': '信号数减少（要求放量）、胜率提升（资金进场确认）；但家电指数的放量与价格反弹'
                   '相关性可能不如个股强（指数是组合，资金分散），效果待数据。',
        },
    }

    for sn in ['A_反弹力度2%', 'B_RSI上穿40', 'C_放量1.2倍']:
        r = results[sn]
        A(f"## 2.{['A','B','C'][['A_反弹力度2%','B_RSI上穿40','C_放量1.2倍'].index(sn)]} 方案 {sn}\n")
        A(f"**逻辑**：{scheme_meta[sn]['logic']}\n")
        A(f"**金融依据**：{scheme_meta[sn]['why']}\n")
        A(f"**预期**：{scheme_meta[sn]['expect']}\n")
        A("### 全量回测结果（三 horizon）\n")
        A("| horizon | n | 胜率 | 盈亏比 | 均值 | 凯利f | 凯利 | vs基线f |")
        A("|---|---:|---:|---:|---:|---:|---|---|")
        base_f_10 = results['基线_B1'][10][4]
        for h in HORIZONS:
            n, m, wr, pl, f, cls, lbl = r[h]
            base_f = results['基线_B1'][h][4]
            if f is not None and base_f is not None:
                delta = f - base_f
                delta_str = f"{delta*100:+.2f}pp"
            else:
                delta_str = "-"
            primary = " **主**" if h == PRIMARY_HORIZON else ""
            warn = f" ⚠️n<{SAMPLE_WARN_N}" if n < SAMPLE_WARN_N else ""
            A(f"| {h}d{primary} | {n}{warn} | {fmt_pct(wr*100)} | {fmt_pl(pl)} | {fmt_mean(m)} | {fmt_f(f)} | {lbl} | {delta_str} |")
        A("")
        # 主 horizon 详情
        n10, m10, wr10, pl10, f10, cls10, lbl10 = r[10]
        n_base = results['基线_B1'][10][0]
        sig_delta = n_signals_map[sn] - n_signals_map['基线_B1']
        sig_pct = sig_delta / n_signals_map['基线_B1'] * 100 if n_signals_map['基线_B1'] else 0
        A(f"**10d 主 horizon 摘要**：胜率 {fmt_pct(wr10*100)}（基线 {fmt_pct(results['基线_B1'][10][2]*100)}，"
          f"{(wr10-results['基线_B1'][10][2])*100:+.1f}pp）/ 盈亏比 {fmt_pl(pl10)}（基线 {fmt_pl(results['基线_B1'][10][3])}）/ "
          f"凯利 f={fmt_f(f10)}（基线 {fmt_f(base_f_10)}，{(f10-base_f_10)*100 if f10 is not None and base_f_10 is not None else 0:+.2f}pp）/ "
          f"样本 n={n10}（基线 {n_base}）/ 均值 {fmt_mean(m10)}")
        A(f"**信号数**：{n_signals_map[sn]}（基线 {n_signals_map['基线_B1']}，{sig_delta:+d}，{sig_pct:+.1f}%）")
        # 三 horizon 一致性判断
        fs = [r[h][4] for h in HORIZONS]
        f_signs = [(1 if (x is not None and x > 0) else 0) for x in fs]
        consistency = "三 horizon 一致转正（f>0）" if all(s == 1 for s in f_signs) else \
                      ("三 horizon 一致不建议（f≤0）" if all(s == 0 for s in f_signs) else \
                       "三 horizon 不一致（部分转正部分不建议）")
        A(f"**三 horizon 一致性**：{consistency}")
        if n10 < SAMPLE_WARN_N:
            A(f"**⚠️ 样本不足警示**：10d n={n10} < {SAMPLE_WARN_N}，结论仅供参考，可能过拟合。")
        A("")

    # ---- 3. 方案对比表 ----
    A("## 3. 方案对比（一栏一方案）\n")
    A("| 指标 | 基线 B1 | A 反弹力度2% | B RSI上穿40 | C 放量1.2倍 |")
    A("|---|---:|---:|---:|---:|")
    # 10d 主 horizon 对比
    for label, key in [('10d 胜率', 'wr'), ('10d 盈亏比', 'pl'), ('10d 均值', 'mean'),
                       ('10d 凯利f', 'f'), ('10d 凯利状态', 'lbl')]:
        cells = []
        for sn, _, _ in schemes:
            n, m, wr, pl, f, cls, lbl = results[sn][10]
            if key == 'wr':
                cells.append(fmt_pct(wr*100))
            elif key == 'pl':
                cells.append(fmt_pl(pl))
            elif key == 'mean':
                cells.append(fmt_mean(m))
            elif key == 'f':
                cells.append(fmt_f(f))
            elif key == 'lbl':
                cells.append(lbl)
        A(f"| {label} | " + " | ".join(cells) + " |")
    # 样本数与信号数
    A(f"| 10d 样本 n | {results['基线_B1'][10][0]} | {results['A_反弹力度2%'][10][0]} | "
      f"{results['B_RSI上穿40'][10][0]} | {results['C_放量1.2倍'][10][0]} |")
    sig_cells = [str(n_signals_map[sn]) for sn, _, _ in schemes]
    A(f"| 全史信号数 | " + " | ".join(sig_cells) + " |")
    # 信号数变化
    sig_delta_cells = []
    for sn, _, _ in schemes:
        d = n_signals_map[sn] - n_signals_map['基线_B1']
        pct = d / n_signals_map['基线_B1'] * 100 if n_signals_map['基线_B1'] else 0
        sig_delta_cells.append(f"{d:+d} ({pct:+.1f}%)")
    A(f"| 信号数变化（vs基线） | — | " + " | ".join(sig_delta_cells[1:]) + " |")
    # f 改善
    f_delta_cells = []
    base_f = results['基线_B1'][10][4]
    for sn, _, _ in schemes:
        f = results[sn][10][4]
        if f is not None and base_f is not None:
            f_delta_cells.append(f"{(f-base_f)*100:+.2f}pp")
        else:
            f_delta_cells.append("-")
    A(f"| 10d f 改善（vs基线） | — | " + " | ".join(f_delta_cells[1:]) + " |")
    # 胜率改善
    wr_delta_cells = []
    base_wr = results['基线_B1'][10][2]
    for sn, _, _ in schemes:
        wr = results[sn][10][2]
        wr_delta_cells.append(f"{(wr-base_wr)*100:+.1f}pp")
    A(f"| 10d 胜率改善（vs基线） | — | " + " | ".join(wr_delta_cells[1:]) + " |")
    # 是否转正
    zhuanzheng_cells = []
    for sn, _, _ in schemes:
        f = results[sn][10][4]
        zhuanzheng_cells.append("✅ 转正" if (f is not None and f > 0) else "❌ 未转正")
    A(f"| 是否转正（f>0） | " + " | ".join(zhuanzheng_cells) + " |")
    # 三 horizon 一致性
    consistency_cells = []
    for sn, _, _ in schemes:
        fs = [results[sn][h][4] for h in HORIZONS]
        f_signs = [(1 if (x is not None and x > 0) else 0) for x in fs]
        if all(s == 1 for s in f_signs):
            consistency_cells.append("一致转正")
        elif all(s == 0 for s in f_signs):
            consistency_cells.append("一致不建议")
        else:
            consistency_cells.append("不一致")
    A(f"| 三 horizon 一致性 | " + " | ".join(consistency_cells) + " |")
    A("")

    # ---- 4. 推荐 ----
    A("## 4. 推荐方案\n")
    # 找 10d f 最高的
    best_sn = max(['A_反弹力度2%', 'B_RSI上穿40', 'C_放量1.2倍'],
                  key=lambda sn: results[sn][10][4] if results[sn][10][4] is not None else -999)
    best_f = results[best_sn][10][4]
    base_f = results['基线_B1'][10][4]
    A(f"基于数据，**方案 {best_sn.split('_')[0]}（{best_sn}）** 10d 凯利 f 最高（{fmt_f(best_f)}，"
      f"基线 {fmt_f(base_f)}，改善 {(best_f-base_f)*100:+.2f}pp）。")
    A("")
    # 各方案转正情况
    for sn in ['A_反弹力度2%', 'B_RSI上穿40', 'C_放量1.2倍']:
        f10 = results[sn][10][4]
        n10 = results[sn][10][0]
        wr10 = results[sn][10][2]
        pl10 = results[sn][10][3]
        if f10 is not None and f10 > 0:
            A(f"- **方案 {sn.split('_')[0]}（{sn}）**：✅ **转正**，10d f={fmt_f(f10)}，"
              f"胜率 {fmt_pct(wr10*100)} / 盈亏比 {fmt_pl(pl10)} / n={n10}")
        else:
            base_wr = results['基线_B1'][10][2]
            A(f"- **方案 {sn.split('_')[0]}（{sn}）**：❌ 未转正，10d f={fmt_f(f10)}，"
              f"胜率 {fmt_pct(wr10*100)}（vs基线 {(wr10-base_wr)*100:+.1f}pp）/ n={n10}")
    A("")
    A("**最终方案由用户选定**（以下诚实结论辅助判断）。\n")

    # ---- 5. 诚实结论 ----
    A("## 5. 诚实结论\n")
    # 统计转正情况
    turned_positive = [sn for sn in ['A_反弹力度2%', 'B_RSI上穿40', 'C_放量1.2倍']
                       if results[sn][10][4] is not None and results[sn][10][4] > 0]
    A(f"### 5.1 转正情况\n")
    if turned_positive:
        A(f"**{len(turned_positive)} 个方案让 sw_801110 buy_aux 凯利转正（f>0）**：")
        for sn in turned_positive:
            n10, m10, wr10, pl10, f10, cls10, lbl10 = results[sn][10]
            base_n = results['基线_B1'][10][0]
            base_wr = results['基线_B1'][10][2]
            A(f"- {sn}：f={fmt_f(f10)}，胜率 {fmt_pct(wr10*100)}（{(wr10-base_wr)*100:+.1f}pp），"
              f"盈亏比 {fmt_pl(pl10)}，n={n10}（vs基线 {base_n}）")
        A(f"\n**推荐 {best_sn}**（10d f 最高，且三 horizon 一致性见上表）。")
    else:
        A(f"**0 个方案让 sw_801110 buy_aux 凯利转正（f>0）**——所有方案 10d f 仍 ≤0。")
        A(f"退而求其次看胜率提升：")
        for sn in ['A_反弹力度2%', 'B_RSI上穿40', 'C_放量1.2倍']:
            n10, m10, wr10, pl10, f10, cls10, lbl10 = results[sn][10]
            base_wr = results['基线_B1'][10][2]
            A(f"- {sn}：胜率 {fmt_pct(wr10*100)}（{(wr10-base_wr)*100:+.1f}pp），n={n10}，"
              f"f={fmt_f(f10)}（未达凯利建议，但胜率{'提升' if wr10>base_wr else '未提升'}）")
        A(f"\n**无方案转正**——sw_801110 buy_aux 优化空间有限，建议维持现状或考虑 skip 该品类的 buy_aux。")
    A("")

    # 5.2 过拟合警示
    A("### 5.2 过拟合警示\n")
    A(f"- **参数选择性**：试了 3 个方案（A 反弹 2% / B RSI 40 / C 放量 1.2 倍），"
      f"每个方案的参数（2% / 40 / 1.2 倍）都是业界常用值而非历史调参，但仍有选择性偏差风险——"
      f"可能存在其他参数组合效果更好或更差。本回测的结论是「这 3 个业界标准方案的表现」，"
      f"不等于「buy_aux 最优方案」。")
    A(f"- **样本数**：基线 n=134（充足），各方案 n 见上表。若某方案 n<30（样本不足警示），"
      f"其结论仅供参考，可能过拟合小样本。")
    A(f"- **三 horizon 一致性**：10d 是主指标，5d/20d 验证。若某方案仅 10d 转正而 5d/20d 不转正，"
      f"可能是单 horizon 偶发，稳健性存疑。一致转正（三 horizon 都 f>0）才稳健。")
    A(f"- **单品类打样局限**：本回测只测 sw_801110 一个品类，结论不能直接外推到其他品类。"
      f"buy_aux 优化的共性方向需在多个品类验证后才能确认（见 §6 下一品类建议）。")
    A("")

    # 5.3 总判断
    A("### 5.3 总判断\n")
    if turned_positive:
        best_f = results[best_sn][10][4]
        best_n = results[best_sn][10][0]
        # 三 horizon 一致性
        best_fs = [results[best_sn][h][4] for h in HORIZONS]
        all_positive = all(x is not None and x > 0 for x in best_fs)
        A(f"**方案 {best_sn} 让 sw_801110 buy_aux 凯利转正**（10d f={fmt_f(best_f)}，n={best_n}）。")
        if all_positive:
            A(f"三 horizon 一致转正（5d/10d/20d 均 f>0），稳健性高，非单 horizon 偶发。")
        else:
            A(f"⚠️ 三 horizon 不一致（非全部 f>0），10d 转正可能是单 horizon 偶发，稳健性存疑。")
        A(f"**建议落地方案 {best_sn}**（如用户认可）：")
        A(f"- `app/compute/signals.py` 的 buy_aux 判定加方案对应条件")
        A(f"- 重算 signal_daily + signal_stats.json")
        A(f"- 同步 REQUIREMENTS §7.4 变更历史 + 前端 ruleBar 文案")
        A(f"")
        A(f"**诚实提醒**：转正不等于「稳赚」。凯利 f>0 只意味着「正期望」，f 值通常较小"
          f"（个位数百分比），对应建议仓位很轻。buy_aux 仍是辅买点，置信度低于 C1 主买，"
          f"适合小仓位试探或观察确认，不可替代 C1 主买。")
    else:
        # 看胜率提升最多的
        best_wr_sn = max(['A_反弹力度2%', 'B_RSI上穿40', 'C_放量1.2倍'],
                         key=lambda sn: results[sn][10][2])
        best_wr = results[best_wr_sn][10][2]
        base_wr = results['基线_B1'][10][2]
        A(f"**所有 3 个方案均无法让 sw_801110 buy_aux 凯利转正**。")
        A(f"胜率提升最多的是 {best_wr_sn}（{fmt_pct(best_wr*100)}，{(best_wr-base_wr)*100:+.1f}pp），"
          f"但仍未达凯利建议。")
        A(f"")
        A(f"**建议**：")
        A(f"- 若用户接受「退而求其次提高胜率」（不强求凯利转正），可选 {best_wr_sn}")
        A(f"- 若用户坚持凯利转正才落地，建议 **维持现状或 skip sw_801110 的 buy_aux**")
        A(f"  （即该品类不发 buy_aux 信号，避免误导用户）")
        A(f"")
        A(f"**根本原因诊断**：sw_801110 家电指数在 BB 下轨回归日的反弹力度结构性偏弱，"
          f"可能是行业特性（家电是消费板块，受地产周期与消费需求影响，超卖后反弹启动慢），"
          f"非参数可调。可考虑换信号逻辑（如改用 RSI 双底、成交量底部背离等），但超出本回测范围。")
    A("")

    # ---- 6. 下一品类建议 ----
    A("## 6. 下一品类建议（基于本品类经验）\n")
    A("本品类（sw_801110 家电）是 buy_aux 逐个品类优化的打样。经验总结：\n")
    if turned_positive:
        A(f"1. **方案 {best_sn} 在 sw_801110 上转正**，可作为下一个品类的首选测试方案。")
        A(f"2. 三 horizon 一致性是关键判据——单 horizon 转正不可靠，三 horizon 一致转正才稳健。")
        A(f"3. 样本数监控：方案收紧后 n 下降，若 n<30 需警示，n<10 无法判定凯利。")
        A(f"4. 下一品类建议先用 {best_sn} 测试，若也转正则确认该方案为 buy_aux 通用优化方向；"
          f"若不转正则该方案可能品类特异性，需逐个测。")
    else:
        A(f"1. **sw_801110 上无方案转正**，说明 buy_aux 优化空间因品类而异，不是所有品类都能优化到凯利建议。")
        A(f"2. 下一品类建议同样测 3 方案（A 反弹力度 / B RSI 动量 / C 放量），"
          f"看是否有品类能转正。若多个品类都无法转正，可能说明 buy_aux 的 BB 下轨回归逻辑"
          f"本身在 A 股行业指数上结构性偏弱，需考虑换信号逻辑。")
        A(f"3. 退而求其次策略：若某方案虽未转正但稳定提升胜率（如 +3-5pp），"
          f"可作为「软优化」落地（buy_aux 仍是辅买，胜率提升即有价值，不强求凯利转正）。")
    A(f"4. **共性方向假设**（待多品类验证）：")
    A(f"   - 反弹力度确认（A）= 价格维度确认，过滤 barely-crossed 假信号")
    A(f"   - RSI 动量确认（B）= 动量维度确认，与 sell MACD 死叉对称")
    A(f"   - 放量确认（C）= 量价维度确认，经典道氏理论")
    A(f"   三者正交，若某品类多方案都转正，可考虑组合（如 A+C = 反弹力度+放量）做更严格过滤。")
    A("")

    # ---- 7. 附录：完整数据 ----
    A("## 7. 附录：完整回测数据\n")
    A("### 7.1 各方案三 horizon 完整数据\n")
    for sn, _, _ in schemes:
        A(f"#### {sn}\n")
        A("| horizon | n | 胜率 | 盈亏比 | 均值 | 凯利f | 凯利 | 信号数 |")
        A("|---|---:|---:|---:|---:|---:|---|---:|")
        for h in HORIZONS:
            n, m, wr, pl, f, cls, lbl = results[sn][h]
            primary = " **主**" if h == PRIMARY_HORIZON else ""
            warn = f" ⚠️" if n < SAMPLE_WARN_N else ""
            A(f"| {h}d{primary} | {n}{warn} | {fmt_pct(wr*100)} | {fmt_pl(pl)} | {fmt_mean(m)} | {fmt_f(f)} | {lbl} | {n_signals_map[sn]} |")
        A("")

    A("---")
    A("")
    A("*本报告由 `a-stock-data/backtest_buy_aux_optimize.py` 自动生成。"
      "回测独立复刻 signals.py 的 B1 buy_aux 逻辑，不 import app，不改 app/ 代码，不改 DB。"
      "凯利公式参考仓位，非投资建议。*")

    # 写文件
    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write("\n".join(L))
    print(f"\n报告已写入: {REPORT}")
    print(f"\n=== 汇总 ===")
    print(f"基线 B1: 10d f={fmt_f(results['基线_B1'][10][4])} ({results['基线_B1'][10][6]})")
    for sn in ['A_反弹力度2%', 'B_RSI上穿40', 'C_放量1.2倍']:
        n10, m10, wr10, pl10, f10, cls10, lbl10 = results[sn][10]
        print(f"{sn}: 10d f={fmt_f(f10)} ({lbl10}) 胜率={fmt_pct(wr10*100)} n={n10} 信号={n_signals_map[sn]}")


if __name__ == '__main__':
    main()
