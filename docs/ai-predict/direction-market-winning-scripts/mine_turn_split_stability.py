#!/usr/bin/env python3
"""转向日方向拆分(转多 vs 转空) + 按年稳定性
核心问题: 机构资金"转向日"次日方向到底跟哪边?
  转多日(前net<0,当日net>0): 次日涨率?  (机构转加多, 看涨)
  转空日(前net>0,当日net<0): 次日跌率?  (机构转加空, 看跌)
按年稳定性: 最优信号逐年命中率
"""
import json, sqlite3, os

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

def split_turn(role, var):
    """拆分转向日: 转多日次日涨率 vs 转空日次日跌率"""
    series=fut[role][var]
    to_long_up, to_long_n=[], 0      # 转多日: 次日涨?
    to_short_down, to_short_n=[], 0  # 转空日: 次日跌?
    prev_sig=None; run=0
    for i,(date,net) in enumerate(series):
        if net==0: continue
        sig=1 if net>0 else -1
        nr=next_ret(date)
        if i==0 or prev_sig is None or sig==prev_sig:
            prev_sig=sig; run+=1; continue
        # 转向日
        if run>=2:  # 连续>=2日同向后反转
            if sig==1 and prev_sig==-1:   # 转多
                to_long_n+=1; to_long_up.append(1 if nr is not None and nr>0 else 0)
            elif sig==-1 and prev_sig==1:  # 转空
                to_short_n+=1; to_short_down.append(1 if nr is not None and nr<0 else 0)
        prev_sig=sig; run=1
    def rate(arr):
        if not arr: return None
        return sum(arr)/len(arr)
    return (to_long_n, rate(to_long_up)), (to_short_n, rate(to_short_down))

print('=== 转向日方向拆分(连续>=2日同向后反转) ===')
print(f"{'信号':<34} {'转多n':>5} {'转多→次日涨率':>12} | {'转空n':>5} {'转空→次日跌率':>12}")
split_rows=[]
for role in ['中信期货','国泰君安','top20']:
    for var in ['综合','IM','IH','IF','IC']:
        if var not in fut.get(role,{}): continue
        (ln,lu),(sn,sd)=split_turn(role,var)
        name=f'{role} {var}'
        lu_s=f"{lu*100:.1f}%" if lu is not None else '-'
        sd_s=f"{sd*100:.1f}%" if sd is not None else '-'
        print(f"{name:<34} {ln:>5} {lu_s:>12} | {sn:>5} {sd_s:>12}")
        split_rows.append({'signal':name,'to_long_n':ln,'to_long_up_rate':lu,'to_short_n':sn,'to_short_down_rate':sd})
json.dump(split_rows, open(os.path.join(OUT,'turn_split.json'),'w'), ensure_ascii=False, indent=1)

# 按年稳定性: top20 IC 逆向(转向最强) + 中信 IM 正向 + top20 IM 正向
print()
print('=== 按年稳定性(次年命中率) ===')
def yearly_stab(role, var, contrarian=False, min_run=2):
    series=fut[role][var]
    by_year={}
    prev_sig=None; run=0
    for i,(date,net) in enumerate(series):
        if net==0: continue
        sig=1 if net>0 else -1
        nr=next_ret(date)
        if nr is None: continue
        year=date[:4]
        d=by_year.setdefault(year,{'n':0,'hit':0})
        is_turn=False
        if i>=1 and prev_sig is not None and sig!=prev_sig and run>=min_run: is_turn=True
        pred = -sig if contrarian else sig
        if is_turn:
            d['n']+=1
            if (pred==1 and nr>0) or (pred==-1 and nr<0): d['hit']+=1
        run = run+1 if (i>=1 and sig==prev_sig) else 1
        prev_sig=sig
    return by_year

for name, role, var, contra in [
    ('top20 IC 逆向 转向日','top20','IC',True),
    ('中信 IM 正向 转向日','中信期货','IM',False),
    ('top20 IM 正向 转向日','top20','IM',False),
]:
    by=yearly_stab(role,var,contra)
    print(f'{name}:')
    for y in sorted(by):
        d=by[y]
        if d['n']>=10:
            print(f'  {y}: n={d["n"]} 命中={d["hit"]} 率={d["hit"]/d["n"]*100:.1f}%')
