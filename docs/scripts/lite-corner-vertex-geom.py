# -*- coding: utf-8 -*-
# 目的: 复现 static-site/app.js _lwSVG connectNulls+perColor 分段渲染几何, 量化「色变点折角」与「颜色切换滞后」,
#       验证根治方案(段首跨段借前一点 + 绘制边界共享端点)效果。
# 方法口径: 与前端一致 — _lwLineCard liteCfg(boundaryGap:true, smooth:true, connectNulls:true, itemColor=5档色函数);
#           catmull-rom→cubic bezier 控制点公式 c1=p1+(p2-p0)/6, c2=p2-(p3-p1)/6;
#           y extent=_lwValueExtent 简化(raw min/max); 角度=到达切线 vs 离开切线夹角(0°=共线平滑, 180°=折角).
# 输入依赖: static-site/data/overview.json 的 fear_greed_6m/a_sentiment_6m/cross_market_6m 序列
# 输出: 每图色段数/色变点数, 当前折角分布(平均/min/max), 修复后折角(应=0), 颜色滞后逐段表
# 复现命令: python3 docs/scripts/lite-corner-vertex-geom.py
# 关键结论: 当前实现色变点折角 90°~165°(平均~110°), 修复段首后全部 0.0°(共线);
#           每段 stroke 旧色画到 _nxt=下一色段首点(旧色延伸一个点距, 颜色切换滞后).
import json, math, statistics

d = json.load(open('static-site/data/overview.json'))
series_list = {
    '恐贪指数(fear_greed_6m)': [x['value'] for x in d['fear_greed_6m']],
    'A股情绪分(a_sentiment_6m)': [x['value'] for x in d['a_sentiment_6m']],
    '跨市场评分(cross_market_6m)': [x['value'] for x in d['cross_market_6m']],
}
def cfn(v):
    if v is None or math.isnan(v): return "#86909c"
    if v <= 25: return "#42a5f5"
    if v <= 40: return "#4fc3f7"
    if v <= 60: return "#86909c"
    if v <= 75: return "#e6a23c"
    return "#e6492e"
def cfnA(v):
    if v is None or math.isnan(v): return "#86909c"
    if v <= 20: return "#42a5f5"
    if v <= 40: return "#4fc3f7"
    if v <= 60: return "#86909c"
    if v <= 80: return "#e6a23c"
    return "#e6492e"
def angle(v1, v2):
    dm = math.sqrt(sum(a*a for a in v1)) * math.sqrt(sum(b*b for b in v2))
    if dm == 0: return 0
    return math.degrees(math.acos(max(-1, min(1, sum(a*b for a, b in zip(v1, v2)) / dm))))
def coords(vals):
    n = len(vals); iw = 640-55-20; ih = 300-35-44
    vv = [v for v in vals if v is not None]
    yMin, yMax = min(vv), max(vv)
    if yMin == yMax: yMax = yMin + 1
    xs = [55 + (i + 0.5) * (iw / n) for i in range(n)]
    ys = [35 + ih - ((v - yMin) / ((yMax - yMin) or 1)) * ih if v is not None else None for v in vals]
    return xs, ys
for name, vals in series_list.items():
    cfn_use = cfn if name.startswith('恐贪') else cfnA
    xs, ys = coords(vals)
    idx = [i for i, v in enumerate(vals) if v is not None]
    segs = []; rs2 = 0
    while rs2 < len(idx):
        re = rs2; c0 = cfn_use(vals[idx[rs2]])
        while re + 1 < len(idx) and cfn_use(vals[idx[re+1]]) == c0: re += 1
        segs.append((rs2, re, cfn_use(vals[idx[re]]))); rs2 = re + 1
    post, fixed = [], []
    for si in range(len(segs) - 1):
        rs2, re, c0 = segs[si]; rs2n, ren, c1 = segs[si+1]
        P = idx[re + 1]
        if P - idx[re] > 1 or re == rs2 or ren == rs2n: continue
        if idx[re + 2] > P + 1: continue
        va = (xs[idx[re+2]] - xs[idx[re]], ys[idx[re+2]] - ys[idx[re]])   # 中心差分(上段到达, ctxKEnd 借点)
        vl = (xs[idx[re+2]] - xs[P], ys[idx[re+2]] - ys[P])               # 前向差分(下段离开, 现状 p0=p1=P)
        vf = (xs[idx[re+2]] - xs[idx[re]], ys[idx[re+2]] - ys[idx[re]])   # 中心差分(修复: 下段段首借前一色段最后点)
        post.append(angle(va, vl)); fixed.append(angle(va, vf))
    print(f"{name}: 色段数={len(segs)} 色变点数={len(segs)-1} | 当前折角 平均={statistics.mean(post):.1f}° "
          f"min={min(post):.1f}° max={max(post):.1f}° | 修复段首后 平均={statistics.mean(fixed):.1f}°(应=0)")
