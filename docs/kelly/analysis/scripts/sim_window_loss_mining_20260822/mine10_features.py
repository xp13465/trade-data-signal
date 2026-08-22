# -*- coding: utf-8 -*-
"""二轮挖掘 特征表构建(2026-08-22)。
输入:sentiment.db(daily_metric/score_daily/index_daily)+ static-site/data/index/hs300-all.json
输出:data/mine10_features.json  {feat_name: {YYYYMMDD: value}}
口径:全部按交易日对齐;价格衍生用 close 序列滚动自算(无前视:当日值用截至当日收盘数据)。
复现:python3 mine10_features.py (依赖见头部 import)
"""
import sqlite3, json, os, math

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(BASE, '../../../../..'))
OUT = os.path.join(BASE, 'data', 'mine10_features.json')

def main():
    con = sqlite3.connect(os.path.join(ROOT, 'data/sentiment.db'))
    cur = con.cursor()
    feats = {}

    def add_metric(name, metric_id):
        cur.execute("SELECT date, value FROM daily_metric WHERE metric_id=? AND value IS NOT NULL ORDER BY date", (metric_id,))
        feats[name] = {d: v for d, v in cur.fetchall()}

    # 全史族
    add_metric('ma_bull', 'a_ma_bullish')
    add_metric('nhnl52', 'a_nhnl_52w')
    add_metric('qvix100', 'a_qvix_1000')
    add_metric('rot10', 'a_rotation_10d')
    add_metric('div_yield', 'a_div_yield')
    # 近段族
    add_metric('vol_ratio_all', 'a_volume_ratio')
    add_metric('zt_count', 'a_width_zt_count')
    add_metric('dt_count', 'a_width_dt_count')
    add_metric('up_down_ratio', 'a_up_down_ratio')
    add_metric('ad_line', 'a_ad_line')
    add_metric('ad_line_ma20', 'a_ad_line_ma20')
    add_metric('turn_mean', 'a_turnover_mean')
    add_metric('fund_north_cum', 'a_fund_north')
    add_metric('margin_lvl', 'a_fund_margin')
    # score_daily 族
    for sid, nm in [('fear_greed', 'feargreed'), ('sentiment_hs300', 'sent_hs300'), ('a_sentiment', 'sent_a')]:
        cur.execute("SELECT date, value FROM score_daily WHERE score_id=? AND value IS NOT NULL ORDER BY date", (sid,))
        feats[nm] = {d: v for d, v in cur.fetchall()}

    # ---- 衍生特征 ----
    # AD 线距其 MA20(标准化差): adline_gap = (ad_line - ad_line_ma20)/|ad_line_ma20|
    if 'ad_line' in feats and 'ad_line_ma20' in feats:
        g = {}
        for d, v in feats['ad_line'].items():
            m = feats['ad_line_ma20'].get(d)
            if m not in (None, 0):
                g[d] = (v - m) / abs(m)
        feats['adline_gap'] = g
        del feats['ad_line']; del feats['ad_line_ma20']
    # up_down_ratio 5日均值
    if 'up_down_ratio' in feats:
        ds = sorted(feats['up_down_ratio'])
        roll = []
        g = {}
        for d in ds:
            roll.append(feats['up_down_ratio'][d])
            if len(roll) > 5: roll.pop(0)
            g[d] = sum(roll) / len(roll)
        feats['updown5'] = g
        del feats['up_down_ratio']
    # 北向:年内累计 -> 20日差(近20日净流入,亿)
    if 'fund_north_cum' in feats:
        ds = sorted(feats['fund_north_cum'])
        g = {}
        for i, d in enumerate(ds):
            if i >= 20:
                g[d] = feats['fund_north_cum'][d] - feats['fund_north_cum'][ds[i - 20]]
        feats['north_d20'] = g
        del feats['fund_north_cum']
    # 两融 20日变化率%
    if 'margin_lvl' in feats:
        ds = sorted(feats['margin_lvl'])
        g = {}
        for i, d in enumerate(ds):
            if i >= 20 and feats['margin_lvl'][ds[i - 20]]:
                g[d] = (feats['margin_lvl'][d] / feats['margin_lvl'][ds[i - 20]] - 1) * 100
        feats['margin_chg20'] = g
        del feats['margin_lvl']
    # 滚动3年分位(对 div_yield / turn_mean / qvix100):当前值在过去~756交易日的分位0-100
    def rolling_pctile(name, win=756):
        src = feats[name]
        ds = sorted(src)
        vals = []
        g = {}
        import bisect
        window_vals = []
        for d in ds:
            window_vals.append(src[d])
            if len(window_vals) > win: window_vals.pop(0)
            s = sorted(window_vals)
            rank = bisect.bisect_left(s, src[d])
            g[d] = rank / max(len(s) - 1, 1) * 100
        return g
    feats['div_pct'] = rolling_pctile('div_yield')
    feats['turn_pct'] = rolling_pctile('turn_mean')
    feats['qvix_pct'] = rolling_pctile('qvix100')

    # ---- hs300 价格衍生 ----
    with open(os.path.join(ROOT, 'static-site/data/index/hs300-all.json')) as f:
        ohlc = json.load(f)['ohlc']
    dates = [o['date'] for o in ohlc]
    closes = [o['close'] for o in ohlc]
    n = len(closes)
    f_dd, f_vol20, f_volchg, f_ret20, f_slope20, f_abv60 = {}, {}, {}, {}, {}, {}
    for i in range(n):
        c = closes[i]
        # dd252
        if i >= 20:
            hi = max(closes[max(0, i - 251):i + 1])
            if hi > 0: f_dd[dates[i]] = (c / hi - 1) * 100
            # vol20 年化
            rets = [(closes[j] / closes[j - 1] - 1) for j in range(i - 19, i + 1)]
            mu = sum(rets) / len(rets)
            var = sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)
            f_vol20[dates[i]] = math.sqrt(var) * math.sqrt(252) * 100
        if i >= 24:
            def _std(a, b):
                rets = [(closes[j] / closes[j - 1] - 1) for j in range(a, b + 1)]
                mu = sum(rets) / len(rets)
                return math.sqrt(sum((r - mu) ** 2 for r in rets) / max(len(rets) - 1, 1))
            s5, s20 = _std(i - 4, i), _std(i - 19, i)
            if s20 > 1e-12:
                f_volchg[dates[i]] = (s5 / s20 - 1) * 100  # >0 升波 <0 降波
        if i >= 20:
            f_ret20[dates[i]] = (c / closes[i - 20] - 1) * 100
        if i >= 30:
            ma_now = sum(closes[i - 19:i + 1]) / 20
            ma_prev = sum(closes[i - 25:i - 5]) / 20
            if ma_prev: f_slope20[dates[i]] = (ma_now / ma_prev - 1) * 100
        if i >= 59:
            ma60 = sum(closes[i - 59:i + 1]) / 60
            f_abv60[dates[i]] = 1.0 if c > ma60 else 0.0
    feats['h_dd252'] = {k: v for k, v in f_dd.items() if v is not None}
    feats['h_vol20'] = f_vol20
    feats['h_volchg'] = {k: v for k, v in f_volchg.items() if v is not None}
    feats['h_ret20'] = f_ret20
    feats['h_slope20'] = f_slope20
    feats['h_abv60'] = f_abv60

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        json.dump(feats, f, ensure_ascii=False)
    # 覆盖报告
    print(f"{'feat':16s} {'days':>6s} {'first':>9s} {'last':>9s}")
    for k in sorted(feats):
        v = feats[k]
        ks = sorted(v)
        print(f"{k:16s} {len(ks):6d} {ks[0]:>9s} {ks[-1]:>9s}")

if __name__ == '__main__':
    main()
