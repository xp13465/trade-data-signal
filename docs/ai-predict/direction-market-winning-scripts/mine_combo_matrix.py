#!/usr/bin/env python3
"""组合矩阵: 转向信号 + 过滤器 / 多信号同向
验证: 单信号转向已 57-66%, 叠加第二个条件能否再提升?
组合类型:
  C1: 转向信号 + 均线多头/空头状态
  C2: 转向信号 + 量能分位(放量/缩量)
  C3: 转向信号 + 涨跌比/宽度过滤
  C4: 双转向信号同日共振
"""
import json, sqlite3, os, bisect

DB='file:/Users/linhuichen/code/trade-data/data/sentiment.db?mode=ro'
OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),'out')
os.makedirs(OUT, exist_ok=True)
c=sqlite3.connect(DB,uri=True)
sh=c.execute("SELECT date,pct_change FROM index_daily WHERE index_id='sh' AND pct_change IS NOT NULL ORDER BY date").fetchall()
sh_idx={r[0]:i for i,r in enumerate(sh)}; sh_pct={r[0]:r[1] for r in sh}; sh_dates=[r[0] for r in sh]
def next_ret(date):
    if date not in sh_idx: return None
    i=sh_idx[date]
    if i+1>=len(sh_dates): return None
    return sh_pct[sh_dates[i+1]]

def load_futures():
    rows=c.execute("SELECT date,variety,role,long_chg,short_chg FROM futures_position ORDER BY date").fetchall()
    d={}
    for date,var,role,lc,sc in rows:
        if lc is None or sc is None: continue
        d.setdefault(role,{}).setdefault(var,[]).append((date,lc-sc))
    return d
fut=load_futures()

def metric_map(metric_id):
    rows=c.execute("SELECT date,value FROM daily_metric WHERE metric_id=? AND value IS NOT NULL ORDER BY date",(metric_id,)).fetchall()
    return {str(d):v for d,v in rows}
ma_bull=metric_map('a_ma_bullish')
ma_bear=metric_map('a_ma_bearish')
amount=metric_map('a_amount')
udr=metric_map('a_up_down_ratio')
zt=metric_map('a_width_zt_count')

def get_turn_days(role,var,direction):
    """direction='to_long'|'to_short': 返回 [(date,next_ret)] 连续>=2日同向后反转日"""
    series=fut[role][var]
    out=[]; prev_sig=None; run=0
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

def wr(items, key=None):
    if key: items=[x for x in items if key(x)]
    ups=sum(1 for _,nr in items if nr is not None and nr>0)
    downs=sum(1 for _,nr in items if nr is not None and nr<0)
    return len(items), ups, downs, (ups/len(items) if items else None)

# ---------- 各转向信号的次日涨率基线 ----------
print('=== 转向信号基线(次日涨率) ===')
base_signals={}
for role,var,direction,name in [
    ('中信期货','IM','to_long','中信IM转多'),
    ('top20','IM','to_long','top20IM转多'),
    ('国泰君安','IH','to_long','国君IH转多'),
    ('中信期货','综合','to_long','中信综合转多'),
    ('top20','IC','to_short','top20IC转空'),
    ('top20','IM','to_short','top20IM转空'),
    ('国泰君安','综合','to_short','国君综合转空'),
]:
    days=get_turn_days(role,var,direction)
    n,up,down,rate=wr(days)
    base_signals[name]=days
    print(f'  {name}: n={n} 次日涨率={rate*100:.1f}% (涨{up}/跌{down})')

# ---------- C1: 转向 + 均线状态过滤 ----------
print()
print('=== C1: 转向日 + 当日均线状态 ===')
for name, days in base_signals.items():
    for mstate, mmap, cond_name in [
        ('多头', ma_bull, lambda v: v>0),
        ('空头', ma_bear, lambda v: v>0),
    ]:
        sub=[(d,nr) for d,nr in days if mmap.get(d) is not None and (v:=mmap[d])>0]
        if len(sub)>=10:
            n,up,down,rate=wr(sub)
            print(f'  {name} + 均线{cond_name}: n={n} 涨率={rate*100:.1f}%')

# ---------- C2: 转向 + 量能 ----------
print()
print('=== C2: 转向日 + 量能(成交额 vs 前20日均值) ===')
amount_dates=sorted(amount.keys())
for name, days in base_signals.items():
    sub_hi, sub_lo=[],[]
    for d,nr in days:
        idx=bisect.bisect_left(amount_dates,d)
        if idx<20: continue
        hist=[amount[amount_dates[j]] for j in range(idx-20,idx) if amount_dates[j] in amount]
        if len(hist)<10: continue
        ma20=sum(hist)/len(hist)
        if d in amount:
            if amount[d]>1.2*ma20: sub_hi.append((d,nr))
            elif amount[d]<0.8*ma20: sub_lo.append((d,nr))
    for tag,sub in [('放量>1.2ma',sub_hi),('缩量<0.8ma',sub_lo)]:
        if len(sub)>=10:
            n,up,down,rate=wr(sub)
            print(f'  {name} + {tag}: n={n} 涨率={rate*100:.1f}%')

# ---------- C4: 双转向共振 ----------
print()
print('=== C4: 双信号同日共振(同日两品种都转向) ===')
pairs=[
    ('中信IM转多 + top20IM转多', base_signals['中信IM转多'], base_signals['top20IM转多'], 'up'),
    ('中信综合转多 + top20IM转多', base_signals['中信综合转多'], base_signals['top20IM转多'], 'up'),
    ('top20IC转空 + 中信综合转多', base_signals['top20IC转空'], base_signals['中信综合转多'], 'up'),
    ('top20IC转空 + top20IM转空', base_signals['top20IC转空'], base_signals['top20IM转空'], 'up'),
]
for pname, s1, s2, mode in pairs:
    d1={d for d,_ in s1}; d2={d for d,_ in s2}
    common=[(d,nr) for d,nr in s1 if d in d2]
    # 对照组: 只有单信号的日子
    only1=[(d,nr) for d,nr in s1 if d not in d2]
    only2=[(d,nr) for d,nr in s2 if d not in d1]
    n,up,down,rate=wr(common)
    n1,u1,d1r,r1=wr(only1); n2,u2,d2r,r2=wr(only2)
    r1s=f'{r1*100:.1f}%' if r1 else '-'; r2s=f'{r2*100:.1f}%' if r2 else '-'
    print(f'  {pname}: 共振n={n} 涨率={rate*100:.1f}% | 仅A n={n1} 涨率={r1s} | 仅B n={n2} 涨率={r2s}')
