#!/usr/bin/env python3
"""最终规则验证清单: 每个推荐喂预测的规则输出 n/涨率/跌率/按年
规则分两类:
  A. 看涨信号(信号触发 -> 预测次日涨)
  B. 看跌信号(信号触发 -> 预测次日跌)
C. 黑名单(实测无效/反指标的信号)
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
amount=metric_map('a_amount')
lhb_inst=metric_map('lhb_inst_net')
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
# pos60
pos60={}
cl=[sh_close[d] for d in sh_dates]
for i,d in enumerate(sh_dates):
    if i<60: continue
    cc=cl[i]; win=cl[i-59:i+1]
    pos60[d]=(cc-min(win))/(max(win)-min(win)) if max(win)>min(win) else 0.5

def full_stat(days):
    """days: [(date,next_ret)]. 返回含按年"""
    ups=sum(1 for _,nr in days if nr is not None and nr>0)
    downs=sum(1 for _,nr in days if nr is not None and nr<0)
    by={}
    for d,nr in days:
        y=d[:4]
        s=by.setdefault(y,[0,0,0]); s[0]+=1
        if nr>0: s[1]+=1
        elif nr<0: s[2]+=1
    by_sum={y:(s[0],s[1],s[2],s[1]/s[0]) for y,s in by.items() if s[0]>=8}
    return {'n':len(days),'up':ups,'down':downs,'up_rate':ups/len(days) if days else None,'by_year':by_sum}

# ---- A. 看涨信号 ----
print('=== A. 看涨信号(触发->预测次日涨) ===')
bull_rules=[]
# A1 top20IC转空
bull_rules.append(('top20IC转空(机构IC上转空=逆势看涨)', get_turn_days('top20','IC','to_short')))
# A2 top20IM转多
bull_rules.append(('top20IM转多(机构IM上转多加多=顺势看涨)', get_turn_days('top20','IM','to_long')))
# A3 国泰IH转多
bull_rules.append(('国泰君安IH转多', get_turn_days('国泰君安','IH','to_long')))
# A4 中信IM转多
bull_rules.append(('中信IM转多', get_turn_days('中信期货','IM','to_long')))
# A5 top20IC转空+均线多头
bull_rules.append(('top20IC转空+均线多头', [(d,nr) for d,nr in get_turn_days('top20','IC','to_short') if ma_bull.get(d,0)>0]))
# A6 top20IC转空+动量高位
bull_rules.append(('top20IC转空+动量高位pos60>=0.6', [(d,nr) for d,nr in get_turn_days('top20','IC','to_short') if pos60.get(d,0.5)>=0.6]))
# A7 top20IM转多+动量高位
bull_rules.append(('top20IM转多+动量高位', [(d,nr) for d,nr in get_turn_days('top20','IM','to_long') if pos60.get(d,0.5)>=0.6]))
# A8 交割日当日
import calendar, datetime
def third_friday(y,m):
    cal=calendar.monthcalendar(y,m); fs=[w[4] for w in cal if w[4]!=0]
    return f'{y}{m:02d}{fs[2]:02d}' if len(fs)>=3 else None
deliv=set()
for y in range(2015,2027):
    for m in range(1,13):
        d=third_friday(y,m)
        if d and d in sh_idx: deliv.add(d)
bull_rules.append(('交割日当日(每月第三个周五)', [(d,next_ret(d)) for d in sorted(deliv)]))
# A9 波浪动量高分位
pos_hi=[(d,next_ret(d)) for d in sh_dates if pos60.get(d,0.5)>=0.8 and next_ret(d) is not None]
bull_rules.append(('波浪动量高分位pos60>=0.8(强者恒强)', pos_hi))
# A10 国家队强流入(核心宽基ETF)
ce=sqlite3.connect('file:/Users/linhuichen/code/trade/data/etf_national_team.db?mode=ro',uri=True)
core=['510300','510050','510500','510310','159919','159915','510330','512100']
dsum={}
for code in core:
    for date,sc in ce.execute("SELECT date,share_change FROM etf_daily WHERE etf_code=? AND share_change IS NOT NULL",(code,)).fetchall():
        dsum[str(date)]=dsum.get(str(date),0)+(sc or 0)
vals=sorted(v for v in dsum.values())
hi=vals[int(len(vals)*0.8)]
strong=[(d,next_ret(d)) for d,v in dsum.items() if v>=hi and next_ret(d) is not None]
bull_rules.append(('国家队核心ETF强流入(前20%)', strong))
# A11 龙虎榜机构净买
lhb_buy=[(d,next_ret(d)) for d,v in lhb_inst.items() if v>0 and next_ret(d) is not None]
bull_rules.append(('龙虎榜机构净买>0', lhb_buy))
# A12 强转向OR合成器
all_days={}
for name,days in bull_rules[:4]:
    for d,nr in days: all_days.setdefault(d,[]).append(nr)
or_days=[(d,max(v)) for d,v in all_days.items()]
bull_rules.append(('任一强转向OR(4信号)', or_days))

for name,days in bull_rules:
    s=full_stat(days)
    by=' | '.join(f"{y}:{s['by_year'][y][1]}/{s['by_year'][y][0]}={s['by_year'][y][3]*100:.0f}%" for y in sorted(s['by_year']))
    print(f"  {name:<36} n={s['n']:>4} 涨率={s['up_rate']*100:>5.1f}% (涨{s['up']}/跌{s['down']})  {by}")

json.dump({n:full_stat(d) for n,d in bull_rules}, open(os.path.join(OUT,'final_rules_bull.json'),'w'), ensure_ascii=False, indent=1)

# ---- B. 看跌信号 ----
print()
print('=== B. 看跌信号(触发->预测次日跌) ===')
bear_rules=[]
# B1 波浪动量低分位(弱势延续)
pos_lo=[(d,next_ret(d)) for d in sh_dates if pos60.get(d,0.5)<=0.2 and next_ret(d) is not None]
bear_rules.append(('波浪动量低分位pos60<=0.2(弱势延续)', pos_lo))
# B2 量能高分位(放量滞涨)
amt_dates=sorted(amount.keys())
def amt_hi_series():
    out=[]
    for i,d in enumerate(amt_dates):
        if i<20: continue
        win=[amount[amt_dates[j]] for j in range(i-20,i)]
        ma=sum(win)/len(win)
        if amount[d]>1.3*ma:
            nr=next_ret(d)
            if nr is not None: out.append((d,nr))
    return out
bear_rules.append(('成交额放量>1.3倍20日均', amt_hi_series()))
# B3 情绪分高分位(过热回落)
import os as _os
sj=json.load(open('/Users/linhuichen/code/trade/static-site/data/sentiment-1y.json'))
a_sent=[(x['date'],x['value']) for x in sj['a_sentiment']]
sv=sorted(x[1] for x in a_sent)
hi=sorted(x[1] for x in a_sent)[int(len(a_sent)*0.8)]
sent_hi=[(d,next_ret(d)) for d,v in a_sent if v>=hi and next_ret(d) is not None]
bear_rules.append(('情绪分高分位(过热)', sent_hi))

for name,days in bear_rules:
    s=full_stat(days)
    by=' | '.join(f"{y}:{s['by_year'][y][2]}/{s['by_year'][y][0]}={s['by_year'][y][3]*100:.0f}%" for y in sorted(s['by_year']))
    print(f"  {name:<36} n={s['n']:>4} 次日涨率={s['up_rate']*100:>5.1f}% (跌{s['down']})  {by}")

json.dump({n:full_stat(d) for n,d in bear_rules}, open(os.path.join(OUT,'final_rules_bear.json'),'w'), ensure_ascii=False, indent=1)
print('\ndone')
