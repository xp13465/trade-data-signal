# -*- coding: utf-8 -*-
"""二轮挖掘 补测①(2026-08-22 用户质疑补跑):五候选全窗口明细+四大熊市专项(vs9键)。
窗口: 近1/2/3/5年(以数据末 signal_date 为锚)+ 全史;
熊市: 2015股灾(20150615-20160131)/2018全年/2022全年/2024Q1。
口径: 补位口径不变;基线=9键(8键+候选1「牛主升×辅备买」),mode A K1 etf_def。
输出: data/mine18_windows.json
复现: python3 mine18_detail.py(依赖 mine10_features.json + static-site/data/signal_kelly_trades.json)
"""
import os, sys, json, datetime
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import r2_common as R

FEATS_PATH = os.path.join(BASE, 'data', 'mine10_features.json')
OUT_PATH = os.path.join(BASE, 'data', 'mine18_windows.json')

def build_cands(feats):
    """与 mine16_candidates.py main() 内逐字同构的阈值+规则构造(保证数字对齐)。"""
    def qth(fname, p):
        vals = sorted(v for v in feats[fname].values() if v is not None)
        return vals[min(int(p*(len(vals)-1)), len(vals)-1)]
    def make_rule(fname=None, direction=None, th=None, sig=None, tier=None, mkt=None):
        series = feats[fname] if fname else None
        def fn(t, fIdx):
            if fname is not None:
                v = series.get(str(t[3]))
                if v is None: return False
                b = v < th if direction == 'low' else v > th
                if not b: return False
            if sig is not None and t[2] != sig: return False
            if tier is not None and (t[fIdx['market_tier']] or '') != tier: return False
            if mkt is not None and (t[len(fIdx)] or '') != mkt: return False
            return True
        return fn
    return [
        ('N1 北向20日净流入<q30(-58亿)全停', make_rule('north_d20','low',qth('north_d20',0.30))),
        ('T1 低换手分位(<q30)×追买全停',     make_rule('turn_pct','low',qth('turn_pct',0.30),sig='buy_special')),
        ('D1 股息率<q50(2.59)全停',         make_rule('div_yield','low',qth('div_yield',0.50))),
        ('Q1 QVIX历史分位<q10 全停',         make_rule('qvix_pct','low',qth('qvix_pct',0.10))),
        ('N2 北向<q30×concept 全停',         make_rule('north_d20','low',qth('north_d20',0.30),mkt='concept')),
    ]

BEARS = [
    ('2015股灾~熔断',      '20150615', '20160131'),
    ('2018贸易战熊市',      '20180101', '20181231'),
    ('2022单边熊',         '20220101', '20221231'),
    ('2024Q1小微盘流动性危机', '20240101', '20240331'),
]

def win_detail(base9, new_sel, a, b=None):
    bw = R.window(base9, a, b); nw = R.window(new_sel, a, b)
    det = R.diff_detail(bw, nw)
    st = R.stats_of(nw)
    return dict(base_total=R.stats_of(bw)['total'], new_total=st['total'],
                net=round(st['total'] - R.stats_of(bw)['total'], 2),
                new_n=st['n'], sample_ok=st['n'] >= 10, **det)

def main():
    feats = json.load(open(FEATS_PATH))
    cands = build_cands(feats)
    rows, fIdx = R.prepare_rows(); R.init(rows, fIdx)
    dates = sorted(str(t[0]) for t in rows)
    dmin, dmax = dates[0], dates[-1]
    print(f"数据范围 signal_date: {dmin} ~ {dmax}  rows={len(rows)}")
    dd = datetime.date(int(dmax[:4]), int(dmax[4:6]), int(dmax[6:]))
    windows = [('全史', '00010101', None)]
    for yr, lab in ((365,'近1年'), (730,'近2年'), (1095,'近3年'), (1825,'近5年')):
        windows.append((lab, (dd - datetime.timedelta(days=yr)).strftime('%Y%m%d'), None))
    c1 = lambda t: (t[2] in ('buy_aux','buy_backup')) and ((t[fIdx['market_tier']] or '') == '牛市·主升')
    base9 = R.eval_rule_fill(rows, c1, 1)
    out = dict(data_range=[dmin, dmax], baseline9_full=R.stats_of(base9)['total'], candidates={})
    for name, rule in cands:
        both = lambda t, _r=rule: _r(t, fIdx) or c1(t)
        new_sel = R.eval_rule_fill(rows, both, 1)
        wres = {}
        for lab, a, b in windows:
            wres[lab] = win_detail(base9, new_sel, a, b)
        for lab, a, b in BEARS:
            wres['熊市·'+lab] = win_detail(base9, new_sel, a, b)
        out['candidates'][name] = wres
        line = ' '.join(f"{lab}={wres[lab]['net']:+,.0f}" for lab, _, _ in windows)
        bline = ' '.join(f"{lab.replace('熊市·','')}={wres['熊市·'+lab]['net']:+,.0f}(拦{wres['熊市·'+lab]['blocked_n']}笔)" for lab, _, _ in BEARS)
        print(f"== {name}\n   {line}\n   {bline}")
    with open(OUT_PATH, 'w') as f:
        json.dump(out, f, ensure_ascii=False, default=str)
    print('saved ->', OUT_PATH)

if __name__ == '__main__':
    main()
