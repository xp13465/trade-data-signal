#!/usr/bin/env python3
"""最终组合验证:
1. 波浪动量(60日位置高分位) 叠加 期货转向 -> 胜率
2. top20IC转空+均线多头 逐年稳定性
3. 最强信号合成器的累积验证(多条件 AND)
"""
import json, sqlite3, os

DB='file:/Users/linhuichen/code/trade-data/data/sentiment.db?mode=ro'
OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),'out')
c=sqlite3.connect(DB,uri=True)
sh=c.execute("SELECT date,pct_change,close FROM index_daily WHERE index_id='sh' AND pct_change IS NOT NULL ORDER BY date").fetchall()
sh_dates=[r[0] for r in sh]; sh_pct={r[0]:r[1] for r in sh}; sh_close={r[0]:r[2] for r in sh}
sh_idx={d:i for i,d in enumerate(sh_dates)}
def next_ret(date):
    if date not in sh_idx: return None
    i=sh_idx[date]
    if i+1>=len(sh_dates): return None
    return sh_pct[sh_dates[i+1]]
def next_dir(date):
    r=next_ret(date)
    return None if r is None else (1 if r>0 else -1)

def load_futures():
    rows=c.execute("SELECT date,variety,role,long_chg,short_chg FROM futures_position ORDER BY date").fetchall()
    d={}
    for date,var,role,lc,sc in rows:
        if lc is None or sc is None: continue
        d.setdefault(role,{}).setdefault(var,[]).append((date,lc-sc))
    return d
fut=load_futures()

def metric_map(mid):
    rows=c.execute("SELECT date,value FROM daily_metric WHERE metric_id=? AND value IS NOT NULL ORDER BY date",(mid,)).fetchall()
    return {str(d):v for d,v in rows}
ma_bull=metric_map('a_ma_bullish')

# 波浪位置 pos60 高分位日集合
pos60={}
cl=[sh_close[d] for d in sh_dates]
for i,d in enumerate(sh_dates):
    if i<60: continue
    c=cl[i]; win=cl[i-59:i+1]
    pos60[d]=(c-min(win))/(max(win)-min(win)) if max(win)>min(win) else 0.5

def get_turn_days(role,var,direction):
    series=fut[role][var]; out=[]; prev_sig=None; run=0
    for i,(date,net) in enumerate(series):
        if net==0: continue
        sig=1 if net>0 else -1
        nr=next_ret(date)
        if i>=1 and prev_sig is not None and sig!=prev_sig and run>=2:
            if direction=='to_long' and sig==1: out.append((date,nr))
            elif direction=='to_short' and sig==-1: out.append((date,nr))
        run = run+1 if (i>=1 and sig==prev_sig) else 1
        prev_sig=sig
    return out

def stat(days):
    if not days: return (0,None)
    ups=sum(1 for _,nr in days if nr is not None and nr>0)
    return len(days), ups/len(days)

def year_stat(days):
    by={}
    for d,nr in days:
        y=d[:4]
        s=by.setdefault(y,[0,0])
        s[0]+=1
        if nr>0: s[1]+=1
    return {y:(s[0],s[1]/s[0]) for y,s in by.items() if s[0]>=5}

# 各转向信号
signals={}
for role,var,direction,name in [
    ('中信期货','IM','to_long','中信IM转多'),
    ('top20','IM','to_long','top20IM转多'),
    ('国泰君安','IH','to_long','国君IH转多'),
    ('top20','IC','to_short','top20IC转空'),
    ('top20','IM','to_short','top20IM转空'),
]:
    signals[name]=get_turn_days(role,var,direction)

print('=== 转向信号 + 波浪动量(60日位置高分位 pos60>=0.6) 交叉 ===')
for name, days in signals.items():
    sub=[(d,nr) for d,nr in days if pos60.get(d,0.5)>=0.6]
    base_n, base_r = stat(days)
    sub_n, sub_r = stat(sub)
    print(f'  {name}: 基线 n={base_n} 涨率={base_r*100:.1f}% | +动量高位 n={sub_n} 涨率={sub_r*100:.1f}%')

print()
print('=== 转向信号逐年稳定性 ===')
for name, days in signals.items():
    by=year_stat(days)
    s=f'  {name}: '
    for y in sorted(by):
        n,r=by[y]; s+=f'{y} {n}条{r*100:.0f}% | '
    print(s)

print()
print('=== top20IC转空 + 均线多头 逐年 ===')
days=get_turn_days('top20','IC','to_short')
sub=[(d,nr) for d,nr in days if ma_bull.get(d,0)>0]
by=year_stat(sub)
for y in sorted(by):
    n,r=by[y]; print(f'  {y}: n={n} 涨率={r*100:.1f}%')

print()
print('=== 合成器: 任意强信号触发(OR) 次日涨率 ===')
# 把5个强转向信号并集
all_days={}
for name, days in signals.items():
    for d,nr in days:
        all_days.setdefault(d,[]).append(nr)
or_days=[(d,max(nrs)) for d,nrs in all_days.items()]
# OR: 任一转向信号触发
or_dates=[d for d,_ in or_days]
n_any=len(or_days); up_any=sum(1 for d,_ in or_days if next_dir(d)>0)
print(f'  任一强转向触发(5信号OR): n={n_any} 次日涨率={up_any/n_any*100:.1f}%')
# AND: 波浪动量高位 且 任一强转向
and_days=[(d,nr) for d,nr in or_days if pos60.get(d,0.5)>=0.6]
n_a=len(and_days); up_a=sum(1 for d,_ in and_days if next_dir(d)>0)
print(f'  波浪动量高位 + 任一强转向(AND): n={n_a} 次日涨率={up_a/n_a*100:.1f}%')
# 强转向 + 均线多头
and2=[(d,nr) for d,nr in or_days if ma_bull.get(d,0)>0]
n_b=len(and2); up_b=sum(1 for d,_ in and2 if next_dir(d)>0)
print(f'  均线多头 + 任一强转向(AND): n={n_b} 次日涨率={up_b/n_b*100:.1f}%')
# 强转向 + 动量高位 + 均线多头(三重)
and3=[(d,nr) for d,nr in or_days if pos60.get(d,0.5)>=0.6 and ma_bull.get(d,0)>0]
n_c=len(and3); up_c=sum(1 for d,_ in and3 if next_dir(d)>0)
print(f'  动量高位+均线多头+强转向(三重AND): n={n_c} 次日涨率={up_c/n_c*100:.1f}%')

json.dump({'or_days':len(or_days),'or_up':up_any/n_any,'and_momentum':len(and_days),'and_momentum_up':up_a/n_a,
    'and_ma':len(and2),'and_ma_up':up_b/n_b,'triple':len(and3),'triple_up':up_c/n_c}, open(os.path.join(OUT,'final_combo.json'),'w'), ensure_ascii=False, indent=1)
