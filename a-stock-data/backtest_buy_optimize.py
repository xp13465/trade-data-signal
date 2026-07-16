"""C1 主买（RSI 上穿 30）收紧 RSI 方向回测 — 21 个凯利不建议品类。

测试不同 RSI 阈值 + cross 冰点共振，看能否提胜率/转正凯利。

数据源：data/sentiment.db
  - index_daily（指数 close）
  - daily_metric（g.* 全球指标 value）
  - score_daily（cross_market 跨市场评分）

复刻 app/compute/signals.py：
  - RSI(14) EWM α=1/14 adjust=False
  - buy = RSI 上穿 threshold（rsi_prev <= threshold & rsi > threshold），fillna(False)

方案（对每个品类）：
  基线 — RSI 上穿 30（当前 C1）
  A — RSI 上穿 28
  B — RSI 上穿 25
  C — RSI 上穿 30 + cross < 30（冰点共振）
  D — RSI 上穿 28 + cross < 30
  E — RSI 上穿 25 + cross < 30

每个方案算 5d/10d/20d forward return，输出胜率、盈亏比、凯利 f、样本数 n。

凯利：f* = max(0, (b·p - (1-p))/b)，p=胜率 b=盈亏比。买点胜率=收益>0占比。
n<10 = 样本不足，n<30 = 样本不足警示。

约束：独立复刻，不 import app，不改 app/ 代码，不改 DB。
"""
import sqlite3
import numpy as np
import pandas as pd
import os

DB = '/Users/linhuichen/code/trade/data/sentiment.db'
REPORT_DIR = '/Users/linhuichen/code/trade/a-stock-data'
HORIZONS = [5, 10, 20]
KELLY_INSUF_N = 10
SAMPLE_WARN_N = 30

# 21 个凯利不建议品类（buy 任一 horizon f<=0 && n>=10）
CATEGORIES = [
    # 指数类（close 来自 index_daily）
    ('kc50', '科创50', 'index'),
    ('sw_801080', '电子', 'index'),
    ('sw_801110', '家用电器', 'index'),
    ('sw_801120', '食品饮料', 'index'),
    ('sw_801130', '纺织服饰', 'index'),
    ('sw_801140', '轻工制造', 'index'),
    ('sw_801150', '医药生物', 'index'),
    ('sw_801170', '交通运输', 'index'),
    ('sw_801200', '商贸零售', 'index'),
    ('sw_801730', '电力设备', 'index'),
    ('sw_801750', '计算机', 'index'),
    ('sw_801760', '传媒', 'index'),
    ('sw_801890', '机械设备', 'index'),
    ('sz_div', '深证红利', 'index'),
    # 美股指数（close 来自 index_daily）
    ('us_dji', '道琼斯', 'index'),
    ('us_ixic', '纳斯达克', 'index'),
    ('us_ndx', '纳斯达克100', 'index'),
    ('us_spx', '标普500', 'index'),
    # 全球指标（value 来自 daily_metric）
    ('g.cn10y', '中国10年国债', 'metric'),
    ('g.us10y', '美国10年国债', 'metric'),
    ('g.wti_oil', 'WTI原油', 'metric'),
]


def rsi(close, period=14):
    """与 signals.py _rsi() 一致：EWM α=1/period, adjust=False"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss
    return 100 - 100 / (1 + rs)


def load_index_close(iid):
    """从 index_daily 加载 close 序列"""
    con = sqlite3.connect(DB)
    df = pd.read_sql_query(
        "SELECT date, close FROM index_daily WHERE index_id=? AND close IS NOT NULL ORDER BY date",
        con, params=(iid,), parse_dates=['date'])
    con.close()
    if df.empty:
        return None
    return df.set_index('date')['close'].astype(float)


def load_metric_value(mid):
    """从 daily_metric 加载 value 序列"""
    con = sqlite3.connect(DB)
    df = pd.read_sql_query(
        "SELECT date, value FROM daily_metric WHERE metric_id=? AND value IS NOT NULL ORDER BY date",
        con, params=(mid,), parse_dates=['date'])
    con.close()
    if df.empty:
        return None
    return df.set_index('date')['value'].astype(float)


def load_cross_market():
    """从 score_daily 加载 cross_market 评分"""
    con = sqlite3.connect(DB)
    df = pd.read_sql_query(
        "SELECT date, value FROM score_daily WHERE score_id='cross_market' AND value IS NOT NULL ORDER BY date",
        con, parse_dates=['date'])
    con.close()
    if df.empty:
        return None
    return df.set_index('date')['value'].astype(float)


def get_buy_signals(close, rsi_threshold, cross=None, cross_threshold=None):
    """生成 RSI 上穿阈值买点信号。

    close: pd.Series
    rsi_threshold: RSI 上穿阈值（如 30/28/25）
    cross: pd.Series 或 None（跨市场评分）
    cross_threshold: 如果 cross 不为 None，要求 cross < cross_threshold

    返回 bool Series，事件化（shift 穿越检测）。
    """
    r = rsi(close, 14)
    rp = r.shift(1)
    buy = ((rp <= rsi_threshold) & (r > rsi_threshold)).fillna(False)

    if cross is not None and cross_threshold is not None:
        cross_aligned = cross.reindex(close.index)
        buy = buy & (cross_aligned < cross_threshold).fillna(False)

    return buy


def forward_returns(close, sig_mask, horizon):
    """信号日 close → horizon 交易日后 close 收益率(%)"""
    arr = close.values
    n = len(arr)
    sig_idx = np.where(sig_mask.values)[0]
    out = []
    for pos in sig_idx:
        if pos + horizon < n:
            out.append((arr[pos + horizon] - arr[pos]) / arr[pos] * 100.0)
    return out


def stats_block(returns):
    """返回 (n, mean_pct, win_rate, pl, kelly_f, kelly_label)

    买点：涨=赢（收益>0）
    """
    if not returns:
        return (0, float('nan'), float('nan'), float('nan'), None, '样本不足')
    arr = np.array(returns, dtype=float)
    wins = arr[arr > 0]       # 涨 = 买点对
    losses = arr[arr <= 0]
    n = len(arr)
    wr = len(wins) / n
    avg_win = wins.mean() if len(wins) else 0.0
    avg_loss = np.abs(losses).mean() if len(losses) else float('nan')
    pl = (avg_win / avg_loss) if (not np.isnan(avg_loss) and avg_loss > 0) else float('nan')
    f = None
    if not np.isnan(pl) and pl > 0:
        raw_f = (pl * wr - (1 - wr)) / pl
        f = max(0.0, raw_f)
    label = '建议' if (f is not None and f > 0) else '不建议'
    if n < KELLY_INSUF_N:
        label = '样本不足'
    return (n, float(arr.mean()), float(wr), float(pl), f, label)


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


def fmt_kelly_raw(x):
    """返回未 clamp 的原始凯利（用于判断改善方向）"""
    if x is None or np.isnan(x):
        return float('-inf')
    return x


def main():
    cross = load_cross_market()
    print(f"cross_market loaded: {len(cross) if cross is not None else 0} rows")

    # 方案定义: (名称, rsi_threshold, cross_threshold或None)
    schemes = [
        ('基线_RSI上穿30', 30, None),
        ('A_RSI上穿28', 28, None),
        ('B_RSI上穿25', 25, None),
        ('C_RSI上穿30+cross冰点', 30, 30),
        ('D_RSI上穿28+cross冰点', 28, 30),
        ('E_RSI上穿25+cross冰点', 25, 30),
    ]

    all_results = {}  # {sid: {scheme_name: {horizon: stats}}}
    all_signals = {}  # {sid: {scheme_name: total_signals}}

    for sid, name, cat_type in CATEGORIES:
        print(f"\n处理: {sid} ({name}) [{cat_type}]")

        # 加载数据
        if cat_type == 'index':
            clean_sid = sid  # 直接用 sid 查 index_daily
            close = load_index_close(clean_sid)
        else:
            # g.* 从 daily_metric
            clean_sid = sid.split('.', 1)[1] if '.' in sid else sid
            close = load_metric_value(clean_sid)

        if close is None or len(close) < 60:
            print(f"  SKIP: 数据不足 (len={len(close) if close is not None else 0})")
            continue

        print(f"  close: {len(close)} rows, {close.index[0].date()} ~ {close.index[-1].date()}")

        cat_results = {}
        cat_sigs = {}

        for sname, rsi_th, cross_th in schemes:
            has_cross = cross_th is not None and cross is not None
            buy_mask = get_buy_signals(close, rsi_th, cross if has_cross else None, cross_th)

            horizon_results = {}
            total_sig = 0
            for h in HORIZONS:
                rets = forward_returns(close, buy_mask, h)
                n, m, wr, pl, f, label = stats_block(rets)
                horizon_results[h] = (n, m, wr, pl, f, label)
                total_sig = n

            cat_results[sname] = horizon_results
            cat_sigs[sname] = int(buy_mask.sum())
            print(f"    {sname}: signals={cat_sigs[sname]}, 10d n={horizon_results[10][0]}, "
                  f"wr={horizon_results[10][2]:.3f}, pl={horizon_results[10][3]:.3f}, "
                  f"f={fmt_f(horizon_results[10][4])}, {horizon_results[10][5]}")

        all_results[sid] = cat_results
        all_signals[sid] = cat_sigs

    # ===================== 生成报告 =====================
    L = []
    A = L.append

    A("# C1 主买（RSI 上穿 30）收紧 RSI 方向回测报告\n")
    A(f"- 生成日期：2026-07-08")
    A(f"- 数据源：data/sentiment.db（index_daily + daily_metric + score_daily）")
    A(f"- 品类：21 个凯利不建议品类（buy f<=0 && n>=10）")
    A(f"- RSI 算法：period=14, EWM α=1/14, adjust=False（复刻 signals.py `_rsi`）")
    A(f"- 凯利公式：f* = max(0, (b·p - (1-p))/b)，p=胜率 b=盈亏比；f>0=建议，f<=0=不建议，n<10=样本不足")
    A(f"- 买点胜率=收益>0占比（信号后 horizon 日上涨才算对）；盈亏比=平均盈利(涨)/平均亏损(跌)")
    A(f"- 6 方案：基线(RSI上穿30) / A(RSI上穿28) / B(RSI上穿25) / C(RSI上穿30+cross<30) / D(RSI上穿28+cross<30) / E(RSI上穿25+cross<30)")
    A("")
    A("> 诚实前提：C1 主买整体健康（41/60 建议），这 21 个品类是凯利不建议的少数。")
    A("> 收紧 RSI 阈值（30→28→25）或加 cross 冰点共振（<30），看能否提胜率转正凯利。")
    A("")

    # ---- 1. 21 品类清单 ----
    A("## 1. 21 个不建议品类清单（当前基线状态）\n")
    A("| 品类 | ID | 类型 | 10d n | 10d 胜率 | 10d 盈亏比 | 10d 凯利f | 10d 均值 | 5d f | 20d f |")
    A("|---|---:|---:|---:|---:|---:|---:|---:|---:|")

    for sid, name, cat_type in CATEGORIES:
        if sid not in all_results:
            continue
        base = all_results[sid]['基线_RSI上穿30']
        d10 = base[10]
        d5 = base[5]
        d20 = base[20]
        A(f"| {name} | {sid} | {cat_type} | {d10[0]} | {fmt_pct(d10[2]*100)} | {fmt_pl(d10[3])} | {fmt_f(d10[4])} | {fmt_mean(d10[1])} | {fmt_f(d5[4])} | {fmt_f(d20[4])} |")
    A("")

    # ---- 2. 逐品类方案对比 ----
    A("## 2. 逐品类方案对比\n")

    scheme_names = [s[0] for s in schemes]
    horizon_labels = {5: '5d', 10: '10d', 20: '20d'}

    for sid, name, cat_type in CATEGORIES:
        if sid not in all_results:
            continue
        r = all_results[sid]
        A(f"### {name}（{sid}）\n")

        base_n10 = r['基线_RSI上穿30'][10][0]
        base_f10 = r['基线_RSI上穿30'][10][4] if r['基线_RSI上穿30'][10][4] is not None else 0
        A(f"当前基线：10d n={base_n10}, f={fmt_f(base_f10)}")
        A("")

        # 方案对比表（10d 主 horizon）
        A("| 方案 | 10d n | 10d 胜率 | 10d 盈亏比 | 10d 均值 | 10d 凯利f | 10d 判定 | 5d f | 20d f | 信号数 | vs基线 |")
        A("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")

        for sn in scheme_names:
            d10 = r[sn][10]
            d5 = r[sn][5]
            d20 = r[sn][20]
            sigs = all_signals[sid].get(sn, 0)

            # vs基线比较
            f10_val = d10[4] if d10[4] is not None else 0
            if sn == '基线_RSI上穿30':
                chg = '—'
            elif d10[0] < KELLY_INSUF_N:
                chg = '样本不足'
            elif f10_val > 0 and base_f10 <= 0:
                chg = '✅ 转正'
            elif f10_val > base_f10 and f10_val > 0:
                chg = '改善'
            elif f10_val > base_f10:
                chg = '边际改善'
            elif f10_val <= base_f10:
                chg = '无改善'
            else:
                chg = '—'

            warn = f" ⚠️n<{SAMPLE_WARN_N}" if d10[0] < SAMPLE_WARN_N else ""
            A(f"| {sn} | {d10[0]} | {fmt_pct(d10[2]*100)} | {fmt_pl(d10[3])} | {fmt_mean(d10[1])} | {fmt_f(d10[4])} | {d10[5]}{warn} | {fmt_f(d5[4])} | {fmt_f(d20[4])} | {sigs} | {chg} |")
        A("")

        # 5d 详细
        A("**5d horizon 明细**\n")
        A("| 方案 | n | 胜率 | 盈亏比 | 均值 | 凯利f | 判定 |")
        A("|---|---:|---:|---:|---:|---:|")
        for sn in scheme_names:
            d = r[sn][5]
            warn = f" ⚠️n<{SAMPLE_WARN_N}" if d[0] < SAMPLE_WARN_N else ""
            A(f"| {sn} | {d[0]} | {fmt_pct(d[2]*100)} | {fmt_pl(d[3])} | {fmt_mean(d[1])} | {fmt_f(d[4])} | {d[5]}{warn} |")
        A("")

        # 20d 详细
        A("**20d horizon 明细**\n")
        A("| 方案 | n | 胜率 | 盈亏比 | 均值 | 凯利f | 判定 |")
        A("|---|---:|---:|---:|---:|---:|")
        for sn in scheme_names:
            d = r[sn][20]
            warn = f" ⚠️n<{SAMPLE_WARN_N}" if d[0] < SAMPLE_WARN_N else ""
            A(f"| {sn} | {d[0]} | {fmt_pct(d[2]*100)} | {fmt_pl(d[3])} | {fmt_mean(d[1])} | {fmt_f(d[4])} | {d[5]}{warn} |")
        A("")

    # ---- 3. 汇总 ----
    A("## 3. 汇总分析\n")

    # 统计各方案改善情况
    A("### 3.1 方案改善统计（10d 主 horizon）\n")
    A("| 方案 | 转正 | 改善 | 边际改善 | 无改善 | 样本不足 | 总有效 |")
    A("|---|---:|---:|---:|---:|---:|---:|")

    for sn in scheme_names:
        if sn == '基线_RSI上穿30':
            continue
        positive = 0   # 转正（f 从 <=0 变 >0）
        improved = 0   # 改善（f 提高但未转正）
        marginal = 0   # 边际改善（f 提高但仍 <=0）
        no_improve = 0  # 无改善
        insufficient = 0  # 样本不足
        total = 0

        for sid, name, cat_type in CATEGORIES:
            if sid not in all_results:
                continue
            total += 1
            base = all_results[sid]['基线_RSI上穿30']
            cur = all_results[sid][sn]
            base_f = base[10][4] if base[10][4] is not None else 0
            cur_f = cur[10][4] if cur[10][4] is not None else 0

            if cur[10][0] < KELLY_INSUF_N:
                insufficient += 1
            elif cur_f > 0 and base_f <= 0:
                positive += 1
            elif cur_f > base_f:
                if cur_f > 0:
                    improved += 1
                else:
                    marginal += 1
            else:
                no_improve += 1

        A(f"| {sn} | {positive} | {improved} | {marginal} | {no_improve} | {insufficient} | {total} |")
    A("")

    # ---- 4. 推荐 ----
    A("## 4. 推荐方案（逐品类）\n")
    A("对每个品类，找最优方案（10d f 最高且 >= 基线，n >= 10）。\n")
    A("| 品类 | ID | 基线10d f | 推荐方案 | 推荐10d f | 推荐10d n | 推荐10d 胜率 | 推荐10d 盈亏比 | 建议 |")
    A("|---|---:|---:|---:|---:|---:|---:|---|")

    recommend_tighten = []
    recommend_keep = []
    recommend_insuf = []

    for sid, name, cat_type in CATEGORIES:
        if sid not in all_results:
            continue
        base = all_results[sid]['基线_RSI上穿30']
        base_f = base[10][4] if base[10][4] is not None else 0

        best_scheme = '基线_RSI上穿30'
        best_f = base_f
        best_n = base[10][0]
        best_wr = base[10][2]
        best_pl = base[10][3]

        for sn in scheme_names:
            if sn == '基线_RSI上穿30':
                continue
            cur = all_results[sid][sn]
            cur_f = cur[10][4] if cur[10][4] is not None else 0
            cur_n = cur[10][0]

            if cur_n < KELLY_INSUF_N:
                continue  # 样本不足不推荐

            if cur_f > best_f:
                best_f = cur_f
                best_scheme = sn
                best_n = cur_n
                best_wr = cur[10][2]
                best_pl = cur[10][3]

        if best_scheme != '基线_RSI上穿30' and best_f > 0:
            recommend_tighten.append((sid, name, best_scheme, best_f, best_n))
            advice = '✅ 建议收紧'
        elif best_scheme != '基线_RSI上穿30' and best_f > base_f:
            recommend_tighten.append((sid, name, best_scheme, best_f, best_n))
            advice = '边际改善'
        elif best_n < KELLY_INSUF_N:
            recommend_insuf.append((sid, name))
            advice = '样本不足'
        else:
            recommend_keep.append((sid, name, base_f))
            advice = '维持现状'

        A(f"| {name} | {sid} | {fmt_f(base_f)} | {best_scheme} | {fmt_f(best_f)} | {best_n} | {fmt_pct(best_wr*100)} | {fmt_pl(best_pl)} | {advice} |")
    A("")

    # ---- 5. 总结 ----
    A("## 5. 总结\n")
    A(f"- **建议收紧**：{len(recommend_tighten)} 个品类")
    for sid, name, sc, f, n in recommend_tighten:
        A(f"  - {name}（{sid}）：{sc}，f={fmt_f(f)}，n={n}")
    A(f"- **维持现状**：{len(recommend_keep)} 个品类")
    for sid, name, f in recommend_keep:
        A(f"  - {name}（{sid}）：基线 f={fmt_f(f)}")
    A(f"- **样本不足**：{len(recommend_insuf)} 个品类")
    for sid, name in recommend_insuf:
        A(f"  - {name}（{sid}）")
    A("")

    if recommend_tighten:
        A("### 5.1 收紧建议\n")
        A("以下品类通过收紧 RSI 阈值或加 cross 冰点共振，凯利 f 转正或改善：\n")
        for sid, name, sc, f, n in recommend_tighten:
            A(f"- **{name}（{sid}）**：{sc}，10d f={fmt_f(f)}，n={n}")
        A("")
        A("**落地方式**（如用户认可）：")
        A("- 逐品类在 `config/indicators.yaml` 加 `buy_aux_filter` 或引入新的 `buy_filter` 字段")
        A("- 或统一收紧全品类 RSI 阈值（需评估对已建议品类的影响）")
        A("- 建议先落地改善最显著的品类，观察一段后再扩展")
        A("")

    if recommend_keep:
        A("### 5.2 维持现状\n")
        A(f"{len(recommend_keep)} 个品类收紧后无改善或样本不足，建议维持 C1 基线（RSI 上穿 30）。")
        A("这些品类买点凯利为负可能是结构性原因（行业特性、数据噪声），收紧 RSI 阈值或加 cross 冰点共振无法扭转。")
        A("")

    A("### 5.3 诚实提醒\n")
    A("- 买点本质是「超卖反弹」，RSI 上穿 30 已是经典超卖阈值，进一步收紧（28/25）会减少信号、增加等待时间")
    A("- cross 冰点共振（<30）在近年市场宽度结构变化下，cross 多在 30-70 中性区，可能大幅砍信号")
    A("- 收紧后 n 普遍下降，样本不足的结论不可靠")
    A("- 建议以 10d 为主 horizon 判断（与前端 tips 一致），5d/20d 作交叉验证")
    A("")

    # 写文件
    report_path = os.path.join(REPORT_DIR, '22-buy收紧RSI回测-21个不建议.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(L))
    print(f"\n报告已写入: {report_path}")

    # 打印摘要
    print(f"\n=== 摘要 ===")
    print(f"建议收紧: {len(recommend_tighten)}")
    for sid, name, sc, f, n in recommend_tighten:
        print(f"  {name} ({sid}): {sc}, f={f*100:.2f}%, n={n}")
    print(f"维持现状: {len(recommend_keep)}")
    print(f"样本不足: {len(recommend_insuf)}")


if __name__ == '__main__':
    main()