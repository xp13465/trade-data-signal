#!/usr/bin/env python3
"""转折点深度分析 + 组合矩阵
聚焦: 期货 net_chg(中信/国泰君安/top20 综合+IM+IH)的"转向日"次日胜率 vs 非转向日
转向定义:
  T1: 当日符号 != 前日符号
  T2: 连续>=2日同向后的首次反号
  T3: 反向且|net_chg| >= 前5日均值的1.5倍(强转向)
组合: 两个信号的预测方向做 AND/OR 交叉
"""
import json, sqlite3, os
from collections import OrderedDict

DB='file:/Users/linhuichen/code/trade-data/data/sentiment.db?mode=ro'
OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),'out')
os.makedirs(OUT, exist_ok=True)
c=sqlite3.connect(DB,uri=True)

# sh 次日基准
sh=c.execute("SELECT date,pct_change FROM index_daily WHERE index_id='sh' AND pct_change IS NOT NULL ORDER BY date").fetchall()
sh_idx={r[0]:i for i,r in enumerate(sh)}
sh_pct={r[0]:r[1] for r in sh}
sh_dates=[r[0] for r in sh]

def next_dir(date):
    if date not in sh_idx: return None
    i=sh_idx[date]
    if i+1>=len(sh_dates): return None
    nr=sh_pct[sh_dates[i+1]]
    return 1 if nr>0 else -1

def load_futures():
    rows=c.execute("SELECT date,variety,role,long_chg,short_chg FROM futures_position ORDER BY date").fetchall()
    d={}
    for date,var,role,lc,sc in rows:
        if lc is None or sc is None: continue
        d.setdefault(role,{}).setdefault(var,[]).append((date,lc-sc))
    return d

fut=load_futures()

def turn_analysis(role, var, contrarian=False, min_run=1, strong=False):
    """对 net_chg 序列做转向分析. contrarian=逆向信号口径"""
    series=fut[role][var]
    preds_all, trues_all=[], []
    turn_preds, turn_trues=[], []
    non_preds, non_trues=[], []
    prev_sig=0; run=0; 
    for i,(date,net) in enumerate(series):
        nd=next_dir(date)
        if nd is None: continue
        if net==0: continue
        sig=1 if net>0 else -1
        # 转向判定
        is_turn=False
        if i>=1:
            prev_net=series[i-1][1]
            if prev_net!=0:
                prev_sig=1 if prev_net>0 else -1
                if sig!=prev_sig:
                    if min_run==1: is_turn=True
                    elif run>=min_run: is_turn=True
        # 强转向
        if strong and is_turn:
            win=[abs(series[j][1]) for j in range(max(0,i-5),i) if series[j][1]!=0]
            if win and abs(net) < 1.5*sum(win)/len(win): is_turn=False
        run = run+1 if (i>=1 and sig==prev_sig) else 1
        # 信号预测: 正向/逆向
        pred = -sig if contrarian else sig
        preds_all.append(pred); trues_all.append(nd)
        if is_turn: turn_preds.append(pred); turn_trues.append(nd)
        else: non_preds.append(pred); non_trues.append(nd)
    def wr(p,t):
        if not p: return (0,0,None)
        h=sum(1 for a,b in zip(p,t) if a==b)
        return (len(p),h,h/len(p))
    base=wr(preds_all,trues_all); turn=wr(turn_preds,turn_trues); non=wr(non_preds,non_trues)
    return base,turn,non

print('=== 转向分析: 期货 net_chg 信号 ===')
print(f"{'信号':<42} {'n':>4} {'率':>6} | {'转向n':>5} {'转向率':>7} | {'非转n':>5} {'非转率':>7} {'转向-非转':>8}")
rows_out=[]
for role in ['中信期货','国泰君安','top20']:
    for var in ['综合','IM','IH','IF','IC']:
        if var not in fut.get(role,{}): continue
        for contrarian in [False, True]:
            tag = '逆向' if contrarian else '正向'
            base,turn,non = turn_analysis(role,var,contrarian,min_run=2)
            if base[0]<100: continue
            delta = (turn[2]-non[2]) if (turn[2] is not None and non[2] is not None) else None
            name=f'{role} {var} {tag}'
            dstr=f"{delta*100:+.1f}pp" if delta is not None else '-'
            print(f"{name:<42} {base[0]:>4} {base[2]*100:>5.1f}% | {turn[0]:>5} {turn[2]*100:>6.1f}% | {non[0]:>5} {non[2]*100:>6.1f}% {dstr:>8}")
            rows_out.append({'signal':name,'n':base[0],'wr':base[2],'turn_n':turn[0],'turn_wr':turn[2],'non_n':non[0],'non_wr':non[2],'delta':delta})

json.dump(rows_out, open(os.path.join(OUT,'turnpoint_analysis.json'),'w'), ensure_ascii=False, indent=1)
print('saved turnpoint_analysis.json')
