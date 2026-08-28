# -*- coding: utf-8 -*-
# 关键验证: SVG 实际发出的坐标(每点 toFixed(1) 1位小数)上, 色段边界处到达/离开切线夹角是否仍≈0?
import json, math, importlib.util, sys
spec = importlib.util.spec_from_file_location("geom", "/Users/linhuichen/code/trade/docs/scripts/lite-corner-allpoints-geom.py")
geom = importlib.util.module_from_spec(spec); spec.loader.exec_module(geom)
load_data, fg_color, as_color, cm_color, build_geometry, seg_color_runs = geom.load_data, geom.fg_color, geom.as_color, geom.cm_color, geom.build_geometry, geom.seg_color_runs

def r1(x): return round(x, 1)
def angle(u, v):
    nu = math.hypot(*u); nv = math.hypot(*v)
    if nu==0 or nv==0: return None
    c = (u[0]*v[0]+u[1]*v[1])/(nu*nv); c = max(-1, min(1, c))
    return math.degrees(math.acos(c))

def angles_from_emitted(vals, color_fn, W, H, PL=55, PR=20, PT=35, PB=44):
    n = len(vals)
    px, py, ext = build_geometry(vals, W, H, PL, PR, PT, PB)
    P = [(r1(px[i]), r1(py[i])) for i in range(n)]
    seglist = []
    rs2 = 0; prevRe = -1
    while rs2 < n:
        re = rs2
        c0 = color_fn(vals[rs2])
        while re+1 < n and color_fn(vals[re+1]) == c0: re += 1
        ds = prevRe if prevRe >= 0 else rs2
        seglist.append((ds, re, c0))
        prevRe = re; rs2 = re+1
    seg_data = []
    for (ds, re, c0) in seglist:
        if ds == re: continue
        ctxKEnd = min(n-1, re+2)
        _segK = ds
        cs = []
        for k in range(ds, re):
            _pk = k-1 if k > _segK else (ds-1 if (k==ds and ds>0) else k)
            p0 = P[_pk]; p1 = P[k]; p2 = P[k+1]
            _p3i = min(ctxKEnd, k+2)
            p3 = P[_p3i]
            c1 = (r1(p1[0]+(p2[0]-p0[0])/6), r1(p1[1]+(p2[1]-p0[1])/6))
            c2 = (r1(p2[0]-(p3[0]-p1[0])/6), r1(p2[1]-(p3[1]-p1[1])/6))
            cs.append((k, c1, c2, P[k+1]))
        seg_data.append((ds, re, c0, cs))
    angles = {}
    # 关键: 共享端点 = 上一段末点 re == 本段起点 ds (drawStart=prevRe=上一段re)
    # 切勿用 prev.re == ds-1 匹配(会配错段, 产假角 78-169°, 见 L2026-08-17 修正)
    by_re = {x[1]: x for x in seg_data}
    for (ds, re, c0, cs) in seg_data:
        if ds <= 0 or not cs: continue
        prev = by_re.get(ds)
        if not prev or not prev[3]: continue
        last_c = prev[3][-1]
        t_in = (P[ds][0]-last_c[2][0], P[ds][1]-last_c[2][1])
        first_c = cs[0]
        t_out = (first_c[1][0]-P[ds][0], first_c[1][1]-P[ds][1])
        angles[ds] = angle(t_in, t_out)
    return angles

d = load_data()
charts = [("恐贪", "fear_greed_6m", fg_color, 300), ("情绪", "a_sentiment_6m", as_color, 250), ("跨市场", "cross_market_6m", cm_color, 210)]
for name, key, cf, H in charts:
    vals = [x['value'] for x in d[key]]
    ang = angles_from_emitted(vals, cf, 640, H)
    aa = [a for a in ang.values() if a is not None]
    if aa:
        print(f"{name}: 色变边界 {len(aa)} 个 avg={sum(aa)/len(aa):.3f}° max={max(aa):.3f}° >5°={sum(1 for a in aa if a>5)} >1°={sum(1 for a in aa if a>1)}")
        bad = sorted(((i,a) for i,a in ang.items() if a and a>1), key=lambda x:-x[1])[:10]
        for i,a in bad: print(f"   idx {i} {d[key][i]['date']} val={d[key][i]['value']} {cf(d[key][i]['value'])} angle={a:.2f}°")
