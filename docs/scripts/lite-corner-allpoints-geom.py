# -*- coding: utf-8 -*-
"""
调研脚本:首页三张分段色图(恐贪/情绪分/跨市场)整线每点折角分布 + 分段色实际渲染序列
输入依赖: /tmp/overview_online.json (线上 https://ss.fx8.store/data/overview.json)
重跑命令: python3 docs/scripts/lite-corner-allpoints-geom.py
关键口径: 与 static-site/app.js 一致 —
  _lwLineCard liteCfg: boundaryGap:true, smooth:true, connectNulls:true, itemColor=5档色函数
  catmull-rom→cubic 控制点: c1=p1+(p2-p0)/6, c2=p2-(p3-p1)/6 (_lwLineDIdxCtx L12378)
  当前(2026-08-17 a319)修复: 段首跨段借前一色段末点(中心差分) + kEnd=re(去向色) + 共享端点
  折角=该数据点「到达切线 vs 离开切线」夹角(0°=共线平滑, 非0°=可见折角)
"""
import json, math, sys

def load_data(path='/tmp/overview_online.json'):
    with open(path) as f:
        return json.load(f)

# ---- 与前端一致的 5 档色函数 ----
def fg_color(v):
    if v is None or (isinstance(v,float) and math.isnan(v)): return "#86909c"
    if v <= 25: return "#42a5f5"
    if v <= 40: return "#4fc3f7"
    if v <= 60: return "#86909c"
    if v <= 75: return "#e6a23c"
    return "#e6492e"

def as_color(v):
    if v is None or (isinstance(v,float) and math.isnan(v)): return "#86909c"
    if v <= 20: return "#42a5f5"
    if v <= 40: return "#4fc3f7"
    if v <= 60: return "#86909c"
    if v <= 80: return "#e6a23c"
    return "#e6492e"

cm_color = as_color  # 跨市场与情绪分同档

# ---- _lwValueExtent 复刻 (splitNumber=5, zeroBased=false, 无 fixed) ----
def nice_number(span, rounded=False):
    if span <= 0: return 1
    import math as m
    exponent = m.floor(m.log10(span))
    fraction = span / (10 ** exponent)
    if rounded:
        if fraction < 1.5: nice = 1
        elif fraction < 3: nice = 2
        elif fraction < 7: nice = 5
        else: nice = 10
    else:
        if fraction <= 1: nice = 1
        elif fraction <= 2: nice = 2
        elif fraction <= 5: nice = 5
        else: nice = 10
    return nice * (10 ** exponent)

def interval_prec(step):
    import math as m
    if step <= 0: return 0
    # 前端 _intervalPrecision: 基于 step 小数位
    s = repr(step)
    if '.' in s:
        return len(s.split('.')[1])
    return 0

def round_to(prec, v):
    return round(v, prec)

def lw_value_extent(vals, split_number=None, zero_based=None, fixed_min=None, fixed_max=None):
    valid = [v for v in vals if v is not None and not (isinstance(v,float) and math.isnan(v))]
    if valid:
        _m = min(valid); _M = max(valid)
        if zero_based:
            raw_min = min(0, _m); raw_max = max(0, _M)
        else:
            raw_min = _m; raw_max = _M
    else:
        raw_min = 0; raw_max = 1
    ext_min, ext_max = raw_min, raw_max
    if ext_min == ext_max:
        if ext_min != 0:
            _s = abs(ext_min); ext_max += _s/2; ext_min -= _s/2
        else:
            ext_max = 1
    span = ext_max - ext_min
    step = nice_number(span / (split_number or 5), True)
    prec = interval_prec(step)
    yMin = round_to(prec, math.floor(ext_min/step)*step)
    yMax = round_to(prec, math.ceil(ext_max/step)*step)
    if yMin == yMax:
        yMax = yMin + step
    return yMin, yMax

def build_geometry(vals, W, H, PL=55, PR=20, PT=35, PB=44, boundary_gap=True):
    """复刻 _lwSVG 几何: xs(px坐标) + ys(py坐标)"""
    n = len(vals)
    iw = W - PL - PR; ih = H - PT - PB
    # 无 dataZoom: _i0=0, _i1=n-1, _nView=n
    unitW = iw / n if boundary_gap else iw / max(1, n-1)
    px = [PL + (i + 0.5)*unitW if boundary_gap else PL + i*unitW for i in range(n)]
    yMin, yMax = lw_value_extent(vals)
    ys = [PT + ih - ((v - yMin) / ((yMax - yMin) or 1)) * ih for v in vals]
    return px, ys, (yMin, yMax)

def lw_line_d_idx_ctx(xs, ys, idx, kStart, kEnd, ctxKEnd):
    """复刻 _lwLineDIdxCtx (L12378, 2026-08-17 当前版本)"""
    beziers = []  # (k, p0, p1, p2, p3, c1, c2)
    segK = kStart
    for k in range(kStart, kEnd):
        if idx[k+1] > idx[k] + 1:  # 跨 null → 直线
            segK = k + 1
            continue
        if k > segK:
            pk = k - 1
        elif k == kStart and kStart > 0 and idx[kStart] - idx[kStart-1] == 1:
            pk = kStart - 1
        else:
            pk = k
        p0 = (xs[idx[pk]], ys[idx[pk]])
        p1 = (xs[idx[k]], ys[idx[k]])
        p2 = (xs[idx[k+1]], ys[idx[k+1]])
        p3i = min(ctxKEnd, k+2)
        if p3i > k+1 and idx[p3i] > idx[k+1] + 1:
            p3c = k+1
        else:
            p3c = p3i
        p3 = (xs[idx[p3c]], ys[idx[p3c]])
        c1 = (p1[0] + (p2[0]-p0[0])/6, p1[1] + (p2[1]-p0[1])/6)
        c2 = (p2[0] - (p3[0]-p1[0])/6, p2[1] - (p3[1]-p1[1])/6)
        beziers.append((k, p0, p1, p2, p3, c1, c2))
    return beziers

def seg_color_runs(vals, color_fn):
    """按颜色分连续段 (与 connectNulls+perColor 分支同): 返回 [(start,end,color)] 全 idx"""
    runs = []
    i = 0
    n = len(vals)
    while i < n:
        c0 = color_fn(vals[i])
        j = i
        while j + 1 < n and color_fn(vals[j+1]) == c0:
            j += 1
        runs.append((i, j, c0))
        i = j + 1
    return runs

def compute_all_angles(vals, color_fn, W, H, PL=55, PR=20, PT=35, PB=44):
    """复刻整个 connectNulls+perColor 分支, 返回每个数据点的到达/离开切线角"""
    px, py, extent = build_geometry(vals, W, H, PL, PR, PT, PB)
    n = len(vals)
    idx = list(range(n))  # 无 null
    runs = seg_color_runs(vals, color_fn)
    # 复刻 while 循环: 得到每个点被哪条 path 覆盖 + 该点折角
    # 记录每条 path 的 bezier 列表: (drawStart, re, color, beziers)
    paths = []
    rs2 = 0
    prevRe = -1
    while rs2 < len(idx):
        re = rs2
        c0 = color_fn(vals[idx[rs2]])
        while re + 1 < len(idx) and color_fn(vals[idx[re+1]]) == c0:
            re += 1
        drawStart = prevRe if prevRe >= 0 else rs2
        if drawStart == re:
            # 单点段(仅首段单点)
            pass
        else:
            beziers = lw_line_d_idx_ctx(px, py, idx, drawStart, re, min(len(idx)-1, re+2))
            paths.append((drawStart, re, c0, beziers))
        prevRe = re
        rs2 = re + 1
    # 计算每点折角: 到达切线(该点所在前一 bezier 的 c2→p2) vs 离开切线(下一 bezier 的 p1→c1)
    # 建立 bezier 覆盖表: 每个 bezier 从 data-index p1 到 p2 (相邻 idx)
    # bezier k 覆盖线段 idx[k] → idx[k+1]
    angles = {}   # point_idx -> angle (到达vs离开)
    # 收集每个数据点 p 的: 到达 tangent (从 p-1 bezier) 与 离开 tangent (p bezier)
    in_tangent = {}
    out_tangent = {}
    for (ds, re, color, beziers) in paths:
        for (k, p0, p1, p2, p3, c1, c2) in beziers:
            a = idx[k]; b = idx[k+1]
            if b == a + 1:  # 相邻
                # 到达 tangent at b = b - c2
                t_in = (p2[0]-c2[0], p2[1]-c2[1])
                # 离开 tangent at a = c1 - a
                t_out = (c1[0]-p1[0], c1[1]-p1[1])
                if b in in_tangent: in_tangent[b] = None  # 冲突标记(不该发生)
                in_tangent[b] = t_in
                if a in out_tangent: out_tangent[a] = None
                out_tangent[a] = t_out
    def ang_between(u, v):
        nu = math.hypot(u[0], u[1]); nv = math.hypot(v[0], v[1])
        if nu == 0 or nv == 0: return None
        c = (u[0]*v[0] + u[1]*v[1]) / (nu*nv)
        c = max(-1, min(1, c))
        return math.degrees(math.acos(c))
    for p in range(1, n-1):
        ti = in_tangent.get(p); to = out_tangent.get(p)
        if ti is None or to is None:
            continue
        angles[p] = ang_between(ti, to)
    return angles, paths, px, py, extent

def color_of_segment(i, vals, color_fn):
    """线段 i→i+1 的渲染色 = 覆盖该线段的 path 的 stroke 色"""
    return color_fn(vals[i+1])  # 去向色(echarts 口径)

def main():
    d = load_data()
    charts = [
        ("恐贪指数", "fear_greed_6m", fg_color, 300),
        ("A股综合情绪分", "a_sentiment_6m", as_color, 250),
        ("跨市场综合评分", "cross_market_6m", cm_color, 210),
    ]
    for name, key, color_fn, H in charts:
        series = d[key]
        vals = [x['value'] for x in series]
        dates = [x['date'] for x in series]
        n = len(vals)
        angles, paths, px, py, extent = compute_all_angles(vals, color_fn, 640, H)
        # 折角分布
        av = sorted([a for a in angles.values() if a is not None])
        non_smooth = [(i, angles[i], dates[i], vals[i], color_fn(vals[i]))
                      for i in sorted(angles) if angles[i] is not None and angles[i] > 5.0]
        smooth_pts = sum(1 for a in angles.values() if a is not None and a <= 5.0)
        total_pts = len(angles)
        # 色变点 vs 普通点
        color_change_pts = set()
        for (s, e, c) in seg_color_runs(vals, color_fn):
            if e + 1 < n:
                color_change_pts.add(e)  # e 是色变点(旧色段末)
        cc_angles = {i: angles[i] for i in color_change_pts if i in angles and angles[i] is not None}
        ord_angles = {i: angles[i] for i in angles if i not in color_change_pts and angles[i] is not None}
        print(f"=== {name} (n={n}, H={H}, yExtent={extent}) ===")
        print(f"  折角分布: 全部 {total_pts} 点, 平滑(≤5°) {smooth_pts}, 非平滑(>5°) {total_pts-smooth_pts}")
        if av:
            print(f"  avg={sum(av)/len(av):.2f}° min={min(av):.2f}° max={max(av):.2f}°")
        print(f"  色变点折角: n={len(cc_angles)} avg={sum(cc_angles.values())/len(cc_angles) if cc_angles else 0:.2f}° max={max(cc_angles.values()) if cc_angles else 0:.2f}°")
        print(f"  普通点折角: n={len(ord_angles)} avg={sum(ord_angles.values())/len(ord_angles) if ord_angles else 0:.2f}° max={max(ord_angles.values()) if ord_angles else 0:.2f}°")
        if non_smooth:
            print(f"  非平滑点清单(idx/date/val/angle/color):")
            for i, a, dt, v, c in non_smooth[:40]:
                mark = " [色变点]" if i in color_change_pts else ""
                print(f"    idx {i} {dt} val={v} angle={a:.1f}° {c}{mark}")
        else:
            print("  所有点折角 ≤5° → 整线平滑")
        # 分段色渲染序列: 线段 i→i+1 的颜色
        print(f"  色段 runs: {len(seg_color_runs(vals, color_fn))}")
        print()

if __name__ == '__main__':
    main()
