#!/usr/bin/env python3
"""专业投顾三维度挖掘: 交割日效应 / 波浪位置代理 / 国家队托底
1. 交割日: 每月第三个周五(IF/IH交割日), 节假日顺延近似标注
2. 波浪位置: 距20/60日高低百分位 + N日累计涨跌 + 波动率位置, 分位分层
3. 国家队托底: 核心宽基ETF(510300/510050/510500/510310/159919/159915)份额净流入
"""
import json, sqlite3, os, datetime, calendar
from collections import defaultdict

DB='file:/Users/linhuichen/code/trade-data/data/sentiment.db?mode=ro'
ETF_DB='file:/Users/linhuichen/code/trade/data/etf_national_team.db?mode=ro'
OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),'out')
os.makedirs(OUT, exist_ok=True)
c=sqlite3.connect(DB,uri=True)
ce=sqlite3.connect(ETF_DB,uri=True)

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
def is_trading_day(date_str):
    return date_str in sh_idx

# ========== 1. 交割日效应 ==========
# 每月第三个周五(IF/IH 交割日), 2015-2026
def third_friday(y, m):
    cal=calendar.monthcalendar(y, m)
    fridays=[w[4] for w in cal if w[4]!=0]
    return f'{y}{m:02d}{fridays[2]:02d}' if len(fridays)>=3 else None

delivery_days=set()
for y in range(2015, 2027):
    for m in range(1,13):
        d=third_friday(y,m)
        if d: delivery_days.add(d)

# 映射到最近交易日(节假日顺延: 交割日若休市, 顺延到下一交易日)
def nearest_trading_day(d):
    if d in sh_idx: return d
    # 向后找最多5天
    dt=datetime.datetime.strptime(str(d),'%Y%m%d')
    for i in range(1,6):
        nd=(dt+datetime.timedelta(days=i)).strftime('%Y%m%d')
        if nd in sh_idx: return nd
    return None

delivery_map={}
for d in delivery_days:
    nd=nearest_trading_day(d)
    if nd: delivery_map[nd]=d

def eval_delivery(label, dates):
    """dates: 信号日期集合, 计算次日方向"""
    ups=downs=0
    for d in dates:
        nd=next_dir(d)
        if nd is None: continue
        if nd>0: ups+=1
        else: downs+=1
    n=ups+downs
    return n, ups, (ups/n if n else None)

# 非交割日基准(全部交易日)
all_n=len([d for d in sh_dates if next_dir(d) is not None])
all_up=sum(1 for d in sh_dates if next_dir(d) is not None and next_dir(d)>0)
print('=== 1. 交割日效应(每月第三个周五) ===')
print(f'  基准(全交易日): n={all_n} 次日涨率={all_up/all_n*100:.1f}%')

# 交割日当日
deliv_trad=[d for d in delivery_map if is_trading_day(d)]
n,up,rate=eval_delivery('交割日', deliv_trad)
print(f'  交割日当日: n={n} 次日涨率={rate*100:.1f}%')

# 交割日前1日
prev_days=[]
for d in deliv_trad:
    i=sh_idx[d]
    if i-1>=0: prev_days.append(sh_dates[i-1])
n,up,rate=eval_delivery('交割日前1日', prev_days)
print(f'  交割日前1日: n={n} 次日涨率={rate*100:.1f}%')

# 交割日后1日
post_days=[]
for d in deliv_trad:
    i=sh_idx[d]
    if i+1<len(sh_dates): post_days.append(sh_dates[i+1])
n,up,rate=eval_delivery('交割日后1日', post_days)
print(f'  交割日后1日: n={n} 次日涨率={rate*100:.1f}%')

# 交割日所在周(周一到周五都在交割日前后)
print('  --- 按年 ---')
for y in range(2020,2027):
    ds=[d for d in deliv_trad if d[:4]==str(y)]
    n,up,rate=eval_delivery(y, ds)
    if n>=5: print(f'    {y}: n={n} 次日涨率={rate*100:.1f}%')

delivery_result={'benchmark_up_rate': all_up/all_n, 'delivery': eval_delivery('交割日',deliv_trad),
    'prev': eval_delivery('前1日',prev_days), 'post': eval_delivery('后1日',post_days)}

# ========== 2. 波浪位置代理 ==========
print()
print('=== 2. 波浪位置代理(分位分层) ===')
# 用 close 构建: 距20日高回撤 / 60日位置百分位 / 5日累计涨跌
close_list=[sh_close[d] for d in sh_dates]
n_all=len(close_list)
wave=[]
for i,d in enumerate(sh_dates):
    nr=next_dir(d)
    if nr is None: continue
    if i<60: continue
    c=close_list[i]
    win20=close_list[i-19:i+1]; win60=close_list[i-59:i+1]
    drawdown_20=(c-max(win20))/max(win20)           # 距20日高回撤,负=回撤
    pos60=(c-min(win60))/(max(win60)-min(win60)) if max(win60)>min(win60) else 0.5  # 60日位置 0~1
    ret5=(c-close_list[i-5])/close_list[i-5]        # 5日累计涨跌
    wave.append({'date':d,'dd20':drawdown_20,'pos60':pos60,'ret5':ret5,'dir':nr})

def quartile_report(name, key, ascending=True, thresh=(0.2,0.8)):
    vals=sorted([w[key] for w in wave])
    lo=vals[int(len(vals)*thresh[0])]
    hi=vals[int(len(vals)*thresh[1])]
    lo_grp=[w for w in wave if w[key]<=lo]
    hi_grp=[w for w in wave if w[key]>=hi]
    def rate(grp):
        ups=sum(1 for w in grp if w['dir']>0)
        return len(grp), ups, ups/len(grp)
    ln,lu,lr=rate(lo_grp); hn,hu,hr=rate(hi_grp)
    print(f'  {name}: 低分位 n={ln} 次日涨率={lr*100:.1f}% | 高分位 n={hn} 次日涨率={hr*100:.1f}%')
    return {'name':name,'lo_n':ln,'lo_up':lr,'hi_n':hn,'hi_up':hr}

wave_results=[]
# 回撤: 回撤深(低分位, dd最负)-> 次日涨? 反弹预期
wave_results.append(quartile_report('距20日高回撤 dd20', 'dd20', ascending=False))
# 60日位置: 位置低(接近60日低)-> 次日涨; 位置高(接近60日高)-> 次日跌(均值回归)
wave_results.append(quartile_report('60日位置百分位 pos60', 'pos60'))
# 5日涨跌: 超跌(5日跌幅大)-> 次日反弹; 超涨-> 次日回落
wave_results.append(quartile_report('5日累计涨跌 ret5', 'ret5'))
json.dump(wave_results, open(os.path.join(OUT,'wave_position.json'),'w'), ensure_ascii=False, indent=1)

# ========== 3. 国家队托底 ==========
print()
print('=== 3. 国家队托底(核心宽基ETF份额净流入) ===')
core_etfs=['510300','510050','510500','510310','159919','159915','510330','512100']
# etf_daily 的 fund_share 变化 = 资金流入
# 直接用 etf_signal 的 share_surge/share_outflow 日 或 etf_daily share_change
etf_share={}
for code in core_etfs:
    rows=ce.execute("SELECT date,etf_code,share_change FROM etf_daily WHERE etf_code=? AND share_change IS NOT NULL ORDER BY date",(code,)).fetchall()
    for date,ec,sc in rows:
        etf_share.setdefault(date,{})[ec]=sc
print('  核心ETF覆盖天数:', len(etf_share))
# 每日核心ETF份额变化之和
daily_sum=defaultdict(float); daily_cnt=defaultdict(int)
for date, d in etf_share.items():
    for ec,sc in d.items():
        daily_sum[date]+=sc; daily_cnt[date]+=1
# 净流入日: sum>0
inflow_days=[d for d in daily_sum if daily_sum[d]>0 and next_dir(d) is not None]
outflow_days=[d for d in daily_sum if daily_sum[d]<0 and next_dir(d) is not None]
def rate_of(dates):
    ups=sum(1 for d in dates if next_dir(d)>0)
    return len(dates), ups, ups/len(dates)
n,u,r=rate_of(inflow_days); n2,u2,r2=rate_of(outflow_days)
print(f'  核心ETF净流入日: n={n} 次日涨率={r*100:.1f}%')
print(f'  核心ETF净流出日: n={n2} 次日涨率={r2*100:.1f}%')
# 强流入(前20%分位)
vals=sorted([daily_sum[d] for d in daily_sum if next_dir(d) is not None])
if vals:
    hi=vals[int(len(vals)*0.8)]
    strong=[d for d in daily_sum if daily_sum[d]>=hi and next_dir(d) is not None]
    n,u,r=rate_of(strong)
    print(f'  强流入(前20%): n={n} 次日涨率={r*100:.1f}%')
# 按年
print('  --- 净流入日按年 ---')
for y in ['2020','2021','2022','2023','2024','2025','2026']:
    ds=[d for d in inflow_days if d[:4]==y]
    n,u,r=rate_of(ds)
    if n>=10: print(f'    {y}: n={n} 次日涨率={r*100:.1f}%')
json.dump({'inflow_days':len(inflow_days),'inflow_up':r,'outflow_days':len(outflow_days),'outflow_up':r2},
    open(os.path.join(OUT,'national_team.json'),'w'), ensure_ascii=False, indent=1)
print('\ndone')
