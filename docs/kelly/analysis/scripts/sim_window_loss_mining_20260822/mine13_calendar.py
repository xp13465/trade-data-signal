# -*- coding: utf-8 -*-
"""二轮挖掘 日历/月相/星期 维度(2026-08-22)。
方法来源:method-survey C4/D1/D2(春节效应/二月效应/月末旬/星期几/月相/中秋节)。
规则一律时段级(buy_date 判定),补位口径主判据 + 删笔对照副列,三道门同 mine11。
春节/中秋日期表硬编码 2011-2026;月相=朔望周期天文近似(锚点 2000-01-06 新月,synodic 29.530588853d,精度<1天)。
输出:data/mine13_calendar.json
复现:python3 mine13_calendar.py
"""
import os, sys, json, math, datetime
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import r2_common as R

OUT_PATH = os.path.join(BASE, 'data', 'mine13_calendar.json')

CNY = {2011:'20110203',2012:'20120123',2013:'201310' if False else '20130210',2014:'20140131',2015:'20150219',
       2016:'20160208',2017:'20170128',2018:'20180216',2019:'20190205',2020:'20200125',2021:'20210212',
       2022:'20220201',2023:'20230122',2024:'20240210',2025:'20250129',2026:'20260217'}
MIDAUTUMN = {2011:'20110912',2012:'20120930',2013:'20130919',2014:'20140908',2015:'20150927',2016:'20160915',
             2017:'20171004',2018:'20180924',2019:'20190913',2020:'20201001',2021:'20210921',2022:'20220910',
             2023:'20230929',2024:'20240917',2025:'20251006',2026:'20260925'}

def d(s):
    return datetime.date(int(s[:4]), int(s[4:6]), int(s[6:]))

def moon_phase_dates(kind='new', year_from=2010, year_to=2027):
    """近似新月/满月公历日期列表(YYYYMMDD)。"""
    synodic = 29.530588853
    anchor = datetime.date(2000, 1, 6)  # 已知新月
    out = []
    t = anchor
    # 从 2000 推到 year_from
    while t.year < year_from:
        t += datetime.timedelta(days=synodic)
    while t.year <= year_to:
        if kind == 'full':
            half = datetime.timedelta(days=synodic / 2)
            out.append(t + half)
        else:
            out.append(t)
        t += datetime.timedelta(days=synodic)
    return [x.strftime('%Y%m%d') for x in out]

def in_window(ds, table, pre, post):
    dd = d(ds)
    for y, hol in table.items():
        h = d(hol)
        if h - datetime.timedelta(days=pre) <= dd <= h + datetime.timedelta(days=post):
            return True
    return False

def main():
    rows, fIdx = R.prepare_rows()
    R.init(rows, fIdx)
    base = R.eval_baseline(rows, 1)
    new_moons = set(moon_phase_dates('new'))
    full_moons = set(moon_phase_dates('full'))

    def near_moon(ds, moonset, gap=2):
        dd = d(ds)
        for i in range(-gap, gap + 1):
            if (dd + datetime.timedelta(days=i)).strftime('%Y%m%d') in moonset:
                return True
        return False

    rules = {}
    for n in (3, 5, 10):
        rules[f'cny_pre{n}'] = lambda t, _n=n: in_window(str(t[3]), CNY, _n, 0)
        rules[f'cny_post{n}'] = lambda t, _n=n: in_window(str(t[3]), CNY, 0, _n)
    rules['midautumn_pm5'] = lambda t: in_window(str(t[3]), MIDAUTUMN, 5, 5)
    rules['moon_new_pm2'] = lambda t: near_moon(str(t[3]), new_moons, 2)
    rules['moon_full_pm2'] = lambda t: near_moon(str(t[3]), full_moons, 2)
    rules['xun_early'] = lambda t: 1 <= int(str(t[3])[6:]) <= 10
    rules['xun_mid'] = lambda t: 11 <= int(str(t[3])[6:]) <= 20
    rules['xun_late'] = lambda t: int(str(t[3])[6:]) >= 21
    for w in range(5):
        rules[f'weekday{w}'] = lambda t, _w=w: R_sim_weekday(str(t[3])) == _w

    def R_sim_weekday(s):
        return datetime.date(int(s[:4]), int(s[4:6]), int(s[6:])).weekday()

    results = []
    for name, fn in rules.items():
        new_sel = R.eval_rule_fill(rows, fn, 1)
        det = R.diff_detail(base, new_sel)
        gates = R.three_gates(base, new_sel, det)
        st_new = R.stats_of(new_sel)
        del_sel = R.eval_rule_del(rows, fn, 1)
        det_del = R.diff_detail(base, del_sel)
        results.append(dict(rule=name, fill=dict(det, new_total=st_new['total']), gates=gates,
                            yearly_blocked={},
                            delmode=dict(blocked_n=det_del['blocked_n'], net_improve_delmode=det_del['net_improve'])))
        g = gates
        print(f"{name:16s} net={det['net_improve']:+8.0f} blk({det['blocked_n']:>3d},{det['blocked_pnl']:+7.0f}) "
              f"| aprH={g['apr_hurt']:+7.0f} maA={g['mayaug_improve']:+7.0f} fwd={g['forward']['net_improve']:+8.0f} "
              f"nr={g['blocked_neg_ratio']:.0%} | G{'1' if g['g1'] else '-'}{'2' if g['g2'] else '-'}{'3' if g['g3'] else '-'}")
    with open(OUT_PATH, 'w') as f:
        json.dump(dict(baseline=R.stats_of(base), rules=results), f, ensure_ascii=False)

if __name__ == '__main__':
    main()
