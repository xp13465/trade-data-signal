#!/usr/bin/env python3
"""全球行业联动胜率(用户点醒修正: 行业对行业, 非整体对整体)
海外/商品 X 行业 前日涨跌 -> A股对应行业 次日方向
映射(有把握):
  1. 商品: gold -> 有色金属 sw_801050; wti_oil/brent -> 石油石化 sw_801960 + 煤炭 sw_801950; comex_silver -> 有色
  2. 恒生科技 hstech -> 电子 sw_801080 / 计算机 sw_801130 / 通信 sw_801160
  3. 纳指/道指分化(海外科技vs价值代理) -> 电子/计算机(科技) vs 银行/非银(价值)
时间对齐: 海外/商品 D-1(北京D日开盘前已知) -> A股行业 D 日(隔夜) + D+1(延续)
诚实标注: 美股行业ETF(XBI医药/XLK科技)未采集, 最直接对应行业缺失; 本报告用商品+港股科技+纳指道指分化近似
"""
import json, sqlite3, os
DB='file:/Users/linhuichen/code/trade-data/data/sentiment.db?mode=ro'
OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),'out')
c=sqlite3.connect(DB,uri=True)
sh=c.execute("SELECT date FROM index_daily WHERE index_id='sh' ORDER BY date").fetchall()
sh_dates=[r[0] for r in sh]; sh_idx={d:i for i,d in enumerate(sh_dates)}

def load_idx(idx):
    rows=c.execute("SELECT date,pct_change FROM index_daily WHERE index_id=? AND pct_change IS NOT NULL ORDER BY date",(idx,)).fetchall()
    return {str(d):v for d,v in rows}
def load_metric(mid):
    rows=c.execute("SELECT date,value FROM daily_metric WHERE metric_id=? AND value IS NOT NULL ORDER BY date",(mid,)).fetchall()
    return {str(d):v for d,v in rows}
def prev_td(date):
    i=sh_idx.get(date,-1)
    return sh_dates[i-1] if i>=1 else None

def next_td_ret(idx_map, date):
    """A股行业指数 idx_map 在 date 的下一交易日 pct_change"""
    if date not in sh_idx: return None
    i=sh_idx[date]
    if i+1>=len(sh_dates): return None
    nd=sh_dates[i+1]
    return idx_map.get(nd)

def sector_stat(name, foreign_map, a_share_map, offset=1, filter_fn=None):
    """foreign_map: {date: pct}; a_share_map: {date: pct}; offset: 1=海外D-1->A股D(隔夜), 2=D-1->D+1
    计算: 海外前日涨跌符号 -> A股对应行业(offset)方向符号"""
    hits=0; tot=0; ups=downs=0
    details=[]
    for d in a_share_map:
        if d not in sh_idx: continue
        i=sh_idx[d]
        # 海外 D-1
        if i-1<0: continue
        fd=sh_dates[i-1]
        fv=foreign_map.get(fd)
        if fv is None or fv==0: continue
        # A股行业 offset
        target_idx=i-1+offset
        if target_idx<0 or target_idx>=len(sh_dates): continue
        tdate=sh_dates[target_idx]
        tv=a_share_map.get(tdate)
        if tv is None or tv==0: continue
        if filter_fn and not filter_fn(fv): continue
        fdir=1 if fv>0 else -1
        tdir=1 if tv>0 else -1
        tot+=1
        if tdir>0: ups+=1
        else: downs+=1
        if fdir==tdir: hits+=1
    rate=hits/tot if tot else None
    return {'n':tot,'hit':hits,'winrate':rate,'same_rate':ups/tot if tot else None,'up':ups,'down':downs}

def report(name, result, base_rate=None):
    if result['n']==0:
        print(f"  {name:<46} 无数据")
        return result
    wr=f"{result['winrate']*100:.1f}%" if result['winrate'] is not None else '-'
    sr=f"同日涨率{result['same_rate']*100:.1f}%" if result['same_rate'] is not None else '-'
    print(f"  {name:<46} n={result['n']:>4} 同向胜率={wr:>6} ({result['hit']}中) {sr} | 涨{result['up']}/跌{result['down']}")
    return result

print('=== A股行业自身次日涨率基准(同向基准=50%) ===')
ind_names={'sw_801050':'有色','sw_801950':'煤炭','sw_801960':'石油石化','sw_801080':'电子','sw_801130':'计算机','sw_801160':'通信','sw_801780':'银行','sw_801790':'非银金融'}
baselines={}
for code in ind_names:
    m=load_idx(code)
    ups=sum(1 for d in m if d in sh_idx and sh_idx[d]+1<len(sh_dates) and m.get(sh_dates[sh_idx[d]+1],0)>0)
    tot=sum(1 for d in m if d in sh_idx and sh_idx[d]+1<len(sh_dates) and sh_dates[sh_idx[d]+1] in m)
    r=ups/tot if tot else None
    baselines[code]=r
    print(f"  {ind_names[code]:<6} n={tot:>4} 次日涨率={r*100:.1f}%")

print()
print('=== 1. 商品 -> A股对应行业(隔夜D-1->D / 延续D-1->D+1) ===')
# gold -> 有色
gold=load_metric('gold'); color_metal=load_idx('sw_801050')
# oil -> 石油石化(短) / 煤炭(2014起)
wti=load_metric('wti_oil'); brent=load_metric('brent')
petro=load_idx('sw_801960'); coal=load_idx('sw_801950')
# silver -> 有色
silver=load_metric('comex_silver')

pairs=[('黄金→有色金属', gold, color_metal),('WTI原油→石油石化', wti, petro),('布伦特→石油石化', brent, petro),('WTI原油→煤炭', wti, coal),('白银→有色金属', silver, color_metal)]
sector_results=[]
for name, fm, am, *rest in pairs:
    for offset, tag in [(1,'隔夜'),(2,'延续')]:
        r=sector_stat(name, fm, am, offset=offset)
        report(f'{name} {tag}', r)
        sector_results.append({**r,'name':f'{name} {tag}'})

print()
print('=== 2. 恒生科技 -> A股科技(电子/计算机/通信) ===')
hstech=load_idx('hstech')
for code in ['sw_801080','sw_801130','sw_801160']:
    am=load_idx(code)
    for offset, tag in [(1,'隔夜'),(2,'延续')]:
        r=sector_stat(f'恒生科技→{ind_names[code]}', hstech, am, offset=offset)
        report(f'恒生科技→{ind_names[code]} {tag}', r)
        sector_results.append({**r,'name':f'恒生科技→{ind_names[code]} {tag}'})

print()
print('=== 3. 纳指/道指分化 -> A股科技/价值(海外板块代理) ===')
us_ndx=load_idx('us_ndx'); us_dji=load_idx('us_dji')
# 纳指涨跌 -> 电子/计算机
for code in ['sw_801080','sw_801130']:
    am=load_idx(code)
    for offset, tag in [(1,'隔夜'),(2,'延续')]:
        r=sector_stat(f'纳指→{ind_names[code]}', us_ndx, am, offset=offset)
        report(f'纳指→{ind_names[code]} {tag}', r)
        sector_results.append({**r,'name':f'纳指→{ind_names[code]} {tag}'})
# 道指 -> 银行/非银
for code in ['sw_801780','sw_801790']:
    am=load_idx(code)
    for offset, tag in [(1,'隔夜'),(2,'延续')]:
        r=sector_stat(f'道指→{ind_names[code]}', us_dji, am, offset=offset)
        report(f'道指→{ind_names[code]} {tag}', r)
        sector_results.append({**r,'name':f'道指→{ind_names[code]} {tag}'})

# 分化: 纳指-道指 相对强弱 -> 电子(科技强映射)
print()
print('=== 4. 纳指-道指分化(相对强弱) -> A股科技 ===')
rel=[]
for d in us_ndx:
    if d in us_dji and us_ndx[d] is not None and us_dji[d] is not None:
        rel.append((d, us_ndx[d]-us_dji[d]))
rel_map=dict(rel)
for code in ['sw_801080','sw_801130']:
    am=load_idx(code)
    for offset, tag in [(1,'隔夜'),(2,'延续')]:
        r=sector_stat(f'纳指-道指分化→{ind_names[code]}', rel_map, am, offset=offset)
        report(f'纳指-道指分化→{ind_names[code]} {tag}', r)
        sector_results.append({**r,'name':f'纳指-道指分化→{ind_names[code]} {tag}'})

json.dump(sector_results, open(os.path.join(OUT,'sector_linkage.json'),'w'), ensure_ascii=False, indent=1)
print('\nSaved sector_linkage.json')
