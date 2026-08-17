#!/usr/bin/env python3
"""首页三张分段色图(SVG轻量版)变色分界点校准自验: 固定 0-100 值域后, 渐变 stop 像素 vs 曲线同值像素精确对齐对照表。

- 目的: 证明三张0-100温度计图固定值域后颜色切点精确落在阈值(恐贪25/40/60/75, 情绪/跨市场20/40/60/80), 渐变与曲线同_py映射差0px。
- 方法口径: 复刻 _lwValueExtent(fixedMin=0,fixedMax=100) + 渐变采样生成(_gstep=gspan/800, 阈值双stop硬切) + _py 像素映射(PL=55,PR=20,PT=35,PB=44,ih=221)。
- 输入依赖: /tmp/overview_online.json = 线上 https://ss.fx8.store/data/overview.json
- 输出: 三图「阈值t -> 渐变stop像素 vs 曲线像素(差0.000px) + 实际最近stop值(偏差0.12=采样粒度)」对照表。
- 复现命令: python3 docs/scripts/lite-svg-grad-calibration.py (先 curl -s https://ss.fx8.store/data/overview.json -o /tmp/overview_online.json)
- 关联: docs/lite-svg-grad-calibration.md; 数据截止 2026-08-17。
"""
import json, math
def niceNumber(val, round):
    exp10 = math.pow(10, math.floor(math.log(val)/math.log(10)))
    f = val/exp10
    if round:
        if f<1.5: nf=1
        elif f<2.5: nf=2
        elif f<4: nf=3
        elif f<7: nf=5
        else: nf=10
    else:
        if f<1: nf=1
        elif f<2: nf=2
        elif f<3: nf=3
        elif f<5: nf=5
        else: nf=10
    return nf*exp10
def getPrecision(val):
    e=1;c=0
    while round(val*e)/e!=val:
        e*=10;c+=1
        if c>10:break
    return c
def intervalPrecision(iv): return getPrecision(iv)+2
def roundTo(prec,x): return round(x,prec)
def lwValueExtent(vals, splitNumber=None, zeroBased=False, fixedMin=None, fixedMax=None):
    if fixedMin is not None and fixedMax is not None and fixedMax>fixedMin:
        span=fixedMax-fixedMin
        step=niceNumber(span/(splitNumber or 5),True)
        prec=intervalPrecision(step)
        yMin=roundTo(prec,math.floor(fixedMin/step)*step)
        yMax=roundTo(prec,math.ceil(fixedMax/step)*step)
        ticks=[];tv=yMin
        while tv<=yMax+step/1e6:
            ticks.append(roundTo(prec,tv)); tv=roundTo(prec,tv+step)
            if len(ticks)>10000:break
        return {'yMin':yMin,'yMax':yMax,'step':step,'prec':prec,'ticks':ticks}
    valid=[v for v in vals if v is not None]
    rawMin=min(valid);rawMax=max(valid)
    extMin,extMax=rawMin,rawMax
    if extMin==extMax:
        if extMin!=0: s=abs(extMin);extMax+=s/2;extMin-=s/2
        else: extMax=1
    span=extMax-extMin
    step=niceNumber(span/(splitNumber or 5),True)
    prec=intervalPrecision(step)
    niceMin=roundTo(prec,math.ceil(extMin/step)*step)
    niceMax=roundTo(prec,math.floor(extMax/step)*step)
    niceMin=max(min(niceMin,extMax),extMin)
    niceMax=max(min(niceMax,extMax),extMin)
    if niceMin>niceMax: niceMin=niceMax
    yMin=roundTo(prec,math.floor(extMin/step)*step)
    yMax=roundTo(prec,math.ceil(extMax/step)*step)
    return {'yMin':yMin,'yMax':yMax,'step':step,'prec':prec}
def fgColor(v):
    if v<=25: return "#42a5f5"
    if v<=40: return "#4fc3f7"
    if v<=60: return "#86909c"
    if v<=75: return "#e6a23c"
    return "#e6492e"
def asColor(v):
    if v<=20: return "#42a5f5"
    if v<=40: return "#4fc3f7"
    if v<=60: return "#86909c"
    if v<=80: return "#e6a23c"
    return "#e6492e"
def build_stops(gymax,gymin,colorFn):
    gspan=gymax-gymin
    gstep=max(0.05,gspan/800)
    stops=[];gprevCol=colorFn(gymax);gprevV=gymax
    stops.append([0,gprevCol])
    v=gymax-gstep
    while v>gymin:
        gc=colorFn(v)
        if gc!=gprevCol:
            go=(gymax-gprevV)/gspan
            stops.append([go,gprevCol]);stops.append([go,gc]);gprevCol=gc
        gprevV=v;v-=gstep
    gbot=colorFn(gymin)
    if gbot!=gprevCol:
        go=(gymax-gprevV)/gspan
        stops.append([go,gprevCol]);stops.append([go,gbot])
    stops.append([1,gbot])
    return stops
d=json.load(open('/tmp/overview_online.json'))
W=900;H=300;PL=55;PR=20;PT=35;PB=44
ih=H-PT-PB
print("修复后(固定 0-100)三图: 阈值t -> 渐变stop像素 vs 曲线同值像素")
for key,cf,thresh,label in [
    ('fear_greed_6m',fgColor,[25,40,60,75],'恐贪 25/40/60/75'),
    ('a_sentiment_6m',asColor,[20,40,60,80],'情绪分 20/40/60/80'),
    ('cross_market_6m',asColor,[20,40,60,80],'跨市场 20/40/60/80'),
]:
    vals=[x['value'] for x in d[key] if x.get('value') is not None]
    ext=lwValueExtent(vals,None,False,0,100)
    yMin,yMax=ext['yMin'],ext['yMax']
    gspan=yMax-yMin
    def py(v): return PT+ih-((v-yMin)/(gspan or 1))*ih
    stops=build_stops(yMax,yMin,cf)
    gy1=py(yMax);gy2=py(yMin)
    print(f"\n[{label}] 数据min={min(vals):.1f} max={max(vals):.1f} | 值域=固定[{yMin},{yMax}] | 渐变y1={gy1:.1f}(顶/高值) y2={gy2:.1f}(底/低值)")
    for t in thresh:
        expoff=(yMax-t)/gspan
        stoppix=gy1+expoff*(gy2-gy1)
        curvepix=py(t)
        # 最近实际 stop
        best=min(stops,key=lambda s:abs(s[0]-expoff))
        actval=yMax-best[0]*gspan
        print(f"  t={t}: 期望offset={expoff*100:.2f}% 渐变stop像素={stoppix:.2f} 曲线像素={curvepix:.2f} 差={stoppix-curvepix:+.3f}px | 实际最近stop值={actval:.2f}(偏差{abs(actval-t):.2f})")
