#!/usr/bin/env python3
"""全球/跨市场联动信号挖掘
时间口径说明:
  - A股交易日 D。预测 D+1 方向(次日框架)。
  - 美股 D-1 收盘(北京 D 日5:00,A股D日开盘前已知) -> 测对 D 日(隔夜直接) 和 D+1(延续)
  - 亚太(日韩) D 日盘中先于 A股收盘 -> 测对 D+1; D-1 -> D(前日参考)
  - 港股 hsi D 日与 A股同时段 -> 测对 D+1; D-1 -> D
  - 行业 D 日涨幅榜 -> A股 D+1(轮动延续)
  - 公募基金: 查结构判断有无方向维度
"""
import json, sqlite3, os
DB='file:/Users/linhuichen/code/trade-data/data/sentiment.db?mode=ro'
OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),'out')
c=sqlite3.connect(DB,uri=True)
sh=c.execute("SELECT date,pct_change FROM index_daily WHERE index_id='sh' AND pct_change IS NOT NULL ORDER BY date").fetchall()
sh_dates=[r[0] for r in sh]; sh_pct={r[0]:r[1] for r in sh}; sh_idx={d:i for i,d in enumerate(sh_dates)}
def next_ret(date):
    if date not in sh_idx: return None
    i=sh_idx[date]
    if i+1>=len(sh_dates): return None
    return sh_pct[sh_dates[i+1]]
def next_dir(date):
    r=next_ret(date)
    return None if r is None else (1 if r>0 else -1)
def same_ret(date):
    return sh_pct.get(date)

def load_idx(idx):
    rows=c.execute("SELECT date,pct_change FROM index_daily WHERE index_id=? AND pct_change IS NOT NULL ORDER BY date",(idx,)).fetchall()
    return {str(d):v for d,v in rows}

def prev_trading_day(date):
    i=sh_idx[date]
    if i<=0: return None
    return sh_dates[i-1]

def stat(days):
    if not days: return (0,None)
    ups=sum(1 for _,nr in days if nr is not None and nr>0)
    downs=sum(1 for _,nr in days if nr is not None and nr<0)
    return (len(days), ups/len(days), ups, downs)

def yearly(days):
    by={}
    for d,nr in days:
        if nr is None: continue
        y=d[:4]; s=by.setdefault(y,[0,0,0]); s[0]+=1
        if nr>0: s[1]+=1
        elif nr<0: s[2]+=1
    return {y:(s[0],s[1],s[1]/s[0]) for y,s in by.items() if s[0]>=8}

def report(name, days):
    n,r,up,down=stat(days)
    days=[x for x in days if x[1] is not None]
    by=yearly(days)
    bys=' | '.join(f"{y}:{s[0]}条{s[2]*100:.0f}%" for y,s in sorted(by.items()))
    print(f"  {name:<52} n={n:>4} 次日涨率={r*100 if r else 0:>5.1f}% (涨{up}/跌{down})  {bys}")
    return {'name':name,'n':n,'up_rate':r,'by_year':by}

results=[]
# ========== 1. 美股隔夜/延续 ==========
print('=== 1. 美股(标普/道指/纳指) ===')
for code,name in [('us_spx','标普500'),('us_dji','道指'),('us_ixic','纳指综合')]:
    m=load_idx(code)
    # D-1 -> D 当日(隔夜直接效应)
    direct=[]; extend=[]
    for d in sh_dates:
        if d not in m: continue
        pd=prev_trading_day(d)
        if pd is None or pd not in m: continue
        us_prev=m[pd]
        if us_prev is None: continue
        # 直接: 美股D-1 -> A股D 当日
        direct.append((d, same_ret(d)))
        # 延续: 美股D-1 -> A股D+1
        extend.append((d, next_ret(d)))
    print(f'  [{name}] 隔夜直接(D-1美股->D当日):')
    r=report(f'{name} 隔夜 D-1->D', direct)
    print(f'  [{name}] 延续(D-1美股->D+1):')
    r=report(f'{name} 延续 D-1->D+1', extend)
    results.append(r)

# ========== 2. 亚太 ==========
print()
print('=== 2. 亚太联动(日韩/港股) ===')
for code,name in [('kospi','韩国KOSPI'),('nikkei225','日经225'),('hsi','恒生指数'),('hscei','国企指数H')]:
    m=load_idx(code)
    # D-1 -> D(前日参考)
    prev_ref=[]; ext=[]
    for d in sh_dates:
        if d not in m: continue
        pd=prev_trading_day(d)
        if pd is None or pd not in m: continue
        ap_prev=m[pd]
        if ap_prev is None: continue
        prev_ref.append((d, same_ret(d)))
        ext.append((d, next_ret(d)))
    r=report(f'{name} 前日 D-1->D', prev_ref)
    r2=report(f'{name} 次日 D-1->D+1', ext)
    results.append(r); results.append(r2)
    # D 当日 -> D+1
    syn=[]
    for d in sh_dates:
        if d in m and m[d] is not None:
            syn.append((d,next_ret(d)))
    r3=report(f'{name} 当日->次日 D->D+1', syn)
    results.append(r3)

# ========== 3. 行业风向 ==========
print()
print('=== 3. 行业风向(申万行业领涨/领跌 -> A股次日) ===')
ind_codes=['sw_801010','sw_801030','sw_801040','sw_801050','sw_801080','sw_801110','sw_801120','sw_801130','sw_801140','sw_801150','sw_801160','sw_801170','sw_801180','sw_801200','sw_801210','sw_801230','sw_801710','sw_801720','sw_801730','sw_801740','sw_801750','sw_801760','sw_801770','sw_801780','sw_801790','sw_801880','sw_801890','sw_801950']
ind_maps={code:load_idx(code) for code in ind_codes}
# 每日: 领涨行业数(>0) vs 领跌行业数(<0), 宽度
lead_ratio=[]  # (date, 领涨行业占比, 次日)
for d in sh_dates:
    ups=0; total=0
    for code,mm in ind_maps.items():
        if d in mm and mm[d] is not None:
            total+=1
            if mm[d]>0: ups+=1
    if total>=20:
        lead_ratio.append((d, ups/total, next_ret(d)))
# 领涨占比高分位 -> 次日
vals=sorted(x[1] for x in lead_ratio)
hi=vals[int(len(vals)*0.8)]; lo=vals[int(len(vals)*0.2)]
hi_grp=[(d,nr) for d,r,nr in lead_ratio if r>=hi and nr is not None]
lo_grp=[(d,nr) for d,r,nr in lead_ratio if r<=lo and nr is not None]
r=report('行业领涨占比>=80分位(普涨)->次日', hi_grp)
r2=report('行业领涨占比<=20分位(普跌)->次日', lo_grp)
results.append(r); results.append(r2)

# 领涨行业数极值(全涨/全跌)
all_up=[(d,nr) for d,r,nr in lead_ratio if r>=0.9 and nr is not None]
all_dn=[(d,nr) for d,r,nr in lead_ratio if r<=0.1 and nr is not None]
r=report('行业全涨(占比>=90%)->次日', all_up)
r2=report('行业全跌(占比<=10%)->次日', all_dn)
results.append(r); results.append(r2)

# ========== 4. 公募基金 ==========
print()
print('=== 4. 公募基金(查方向维度) ===')
import glob
pf_files=glob.glob('/Users/linhuichen/code/trade/static-site/data/public_fund_*.json')
for fp in pf_files:
    print('  ', os.path.basename(fp))
# 看 summary 是否有申赎/仓位
try:
    sj=json.load(open('/Users/linhuichen/code/trade/static-site/data/public_fund_summary.json'))
    print('  public_fund_summary keys:', list(sj.keys())[:15] if isinstance(sj,dict) else type(sj))
except Exception as e: print('  summary err', e)

json.dump(results, open(os.path.join(OUT,'global_linkage.json'),'w'), ensure_ascii=False, indent=1)
print('\ndone')
