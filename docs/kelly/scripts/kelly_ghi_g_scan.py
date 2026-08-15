# -*- coding: utf-8 -*-
# 【G模式专项穷举】强平顺序全矩阵 + cap扫描 + 稳健性 + 利润结构 (2026-08-15)
# 目的: 为 SOP §六.9「次日分批 × P≤3d」提供 P≤3d(FIFO/手段A/P*) 与 稳健性(FIFO20万 95.66% 基准为锚)内核。
# 结论(供报告引用): P≤3d 是 G 最优手段(强平0-3天新仓、b0/b1区间极窄); 15起始点全部 > 对应FIFO20万; 随机30点 0/30 负净利。
# 输入: static-site/data/signal_kelly_trades.json(2026-08-15 02:38)。
# 依赖(同目录): dailypool_rerun_core(DEFAULT_NEW/daily_pool_items/compute_scaled/DAILY)。
# 输出: 见 stdout + docs/kelly/position/kelly_ghi_g_scan_out.txt(本脚本会重写该文件)。
# 复现: cd /Users/linhuichen/code/trade && python3 docs/kelly/scripts/kelly_ghi_g_scan.py
# 数据版本: 2026-08-15 02:38。
"""G 模式专项穷举 — 与 H/I 完全对齐
1) 强平顺序全矩阵 x 多cap(10/15/20万) x b0/b1
2) FIFO 连续 cap 扫描(5-20万每1万) + 手段A 连续 cap 扫描 + LIFO/P<=5d 参考
3) 候选稳健性: 多起始时点(2011-2025每年0101) + 随机30日期, 与 FIFO 20万 95.66% 各起点对比
4) G FIFO 利润结构(按持仓段/自然vs强平) vs H/I
"""
import sys, contextlib, io, os, random, math
from collections import defaultdict
from datetime import datetime, timedelta
os.chdir('/Users/linhuichen/code/trade')
sys.path.insert(0,'docs/kelly/scripts'); sys.path.insert(0,'/Users/linhuichen/code/trade')
with contextlib.redirect_stdout(io.StringIO()):
    from dailypool_rerun_core import daily_pool_items, compute_scaled, DEFAULT_NEW, DAILY

out=[]
def line(s=''): out.append(s)

def cal_span(bd, sd):
    if not bd or not sd or sd < bd: return 0
    try:
        d1=datetime.strptime(bd,"%Y%m%d"); d2=datetime.strptime(sd,"%Y%m%d")
        return max((d2-d1).days,0)
    except: return 0
def _advance(bd, cal_days):
    d1=datetime.strptime(bd,"%Y%m%d")
    return (d1+timedelta(days=int(round(cal_days)))).strftime("%Y%m%d")
CAL_RATIO=1.498
def realize(pr,rp,bd,sd,hd,amt,close_date,model):
    ns = cal_span(bd,sd) if sd else (hd*CAL_RATIO if hd else 0)
    cs = cal_span(bd,close_date) if close_date else ns
    if ns<=0 or cs>=ns: return pr,rp,hd
    f=cs/ns
    if model=='b0': return 0.0,0.0,int(round(hd*f))
    if model=='b1':
        fp=pr*f; return fp,(fp/amt*100 if amt else 0),int(round(hd*f))
    if model=='b2': return pr,rp,int(round(hd*f))
    raise ValueError(model)

def simulate_custom(items, cap, method, model='b1', P_N=0, start_date=None):
    trs=[]
    for (pr,rp,bd,sd,hd,amt) in items:
        if start_date and (not bd or bd<start_date): continue
        trs.append({'profit':pr,'rp':rp,'bd':bd,'sd':sd,'hd':hd,'amt':amt,'closed':None})
    buys=defaultdict(list)
    for tr in trs: buys[tr['bd']].append(tr)
    all_dates=sorted(set([t['bd'] for t in trs]+[t['sd'] for t in trs if t['sd']]))
    open_trs=[]; kept=[]; cur=0.0; peak=0.0
    skipped=0; forced=0; nat=0; traded=0; forced_stats=[]; day_curs=[]
    for dt in all_dates:
        new_open=[]
        for tr in open_trs:
            if tr['sd']==dt and tr['closed'] is None:
                tr['closed']='natural'; cur-=tr['amt']
                kept.append((tr['profit'],tr['rp'],tr['bd'],tr['sd'],tr['hd'],tr['amt'])); nat+=1
            else: new_open.append(tr)
        open_trs=new_open
        if dt in buys:
            day_total=sum(t['amt'] for t in buys[dt])
            if method=='none':
                for tr in buys[dt]: open_trs.append(tr); cur+=tr['amt']
                traded+=1
            else:
                needed=cur+day_total-cap
                if needed>1e-6:
                    if method=='A': skipped+=1
                    else:
                        while needed>1e-6 and open_trs:
                            if method=='B': idx=0
                            elif method=='F': idx=len(open_trs)-1
                            elif method=='G': idx=min(range(len(open_trs)),key=lambda i:(open_trs[i]['sd'] or '99999999',i))
                            elif method=='E': idx=min(range(len(open_trs)),key=lambda i:open_trs[i]['profit'])
                            elif method=='E2': idx=max(range(len(open_trs)),key=lambda i:open_trs[i]['profit'])
                            elif method=='W':
                                def _wf(tr):
                                    ns=cal_span(tr['bd'],tr['sd']) if tr['sd'] else tr['hd']*CAL_RATIO
                                    return cal_span(tr['bd'],dt)/max(ns,1)
                                idx=max(range(len(open_trs)),key=lambda i:_wf(open_trs[i]))
                            elif method=='P':
                                young=[i for i,t in enumerate(open_trs) if cal_span(t['bd'],dt)<=P_N]
                                idx=min(young) if young else 0
                            else: raise ValueError(method)
                            tr=open_trs.pop(idx)
                            fpr,frp,fhd=realize(tr['profit'],tr['rp'],tr['bd'],tr['sd'],tr['hd'],tr['amt'],dt,model)
                            forced_stats.append((cal_span(tr['bd'],dt),tr['profit'],tr['rp'],tr['bd'],tr['sd'] or ''))
                            kept.append((fpr,frp,tr['bd'],dt,fhd,tr['amt'])); cur-=tr['amt']; forced+=1
                            needed=cur+day_total-cap
                        if needed<=1e-6:
                            for tr in buys[dt]: open_trs.append(tr); cur+=tr['amt']
                            traded+=1
                        else: skipped+=1
                else:
                    for tr in buys[dt]: open_trs.append(tr); cur+=tr['amt']
                    traded+=1
        peak=max(peak,cur); day_curs.append(cur)
    for tr in open_trs:
        if tr['closed'] is None:
            kept.append((tr['profit'],tr['rp'],tr['bd'],tr['sd'] or '99999999',tr['hd'],tr['amt']))
    avg_cur=sum(day_curs)/len(day_curs) if day_curs else 0
    return kept, peak, skipped, forced, nat, traded, forced_stats, avg_cur

def net_of(kept): return sum(t[0] for t in kept)

# ============ 0. 对账 ============
items = daily_pool_items('G', DEFAULT_NEW, 1)
b = compute_scaled(items)
line('='*130)
line('0. 对账: G K1 基线(关cap): 净=%+.0f 收益=%.2f%% 峰值=%.0f x%.1f 笔数=%d' % (
    b['net'], b['ret'], b['peak_capital'], b['peak_capital']/DAILY, b['n']))
for mdl in ['b0','b1']:
    kept, peak, sk, fo, na, td, fs, ac = simulate_custom(items, 200000, 'B', mdl)
    net=net_of(kept)
    line('  FIFO 20万 %s: 净=%+9.0f 收益=%6.2f%% 强平=%d (报告 95.66/200.46)' % (mdl, net, net/peak*100, fo))

# ============ 1. 强平顺序全矩阵 x 多cap ============
line('')
line('='*130)
line('1. G 强平顺序全矩阵: K1 x cap{10,15,20万} x 方法{B,F,G,E,E2,W,P*,A} x b0/b1')
for capv in [100000,150000,200000]:
    line('')
    line('--- cap=%d万 ---' % (capv//10000))
    line('%-9s %-4s | %11s %9s %7s %6s %6s | %5s' % ('方法','模型','净利','收益%','回撤%','calmar','强平','砍天'))
    for meth in ['B','F','G','E','E2','W']:
        for mdl in ['b0','b1']:
            kept, peak, sk, fo, na, td, fs, ac = simulate_custom(items, capv, meth, mdl)
            s=compute_scaled(kept); net=net_of(kept); ret=net/peak*100 if peak else 0
            line('%-9s %-4s | %+10.0f %8.2f %7.2f %6.2f %6d |' % (meth, mdl, net, ret, s['dd_pct'], s['calmar'], fo))
    for PN in [5,10,20,30]:
        for mdl in ['b0','b1']:
            kept, peak, sk, fo, na, td, fs, ac = simulate_custom(items, capv, 'P', mdl, P_N=PN)
            s=compute_scaled(kept); net=net_of(kept); ret=net/peak*100 if peak else 0
            line('P(<=%2dd) %-4s | %+10.0f %8.2f %7.2f %6.2f %6d |' % (PN, mdl, net, ret, s['dd_pct'], s['calmar'], fo))
    for mdl in ['b0']:
        kept, peak, sk, fo, na, td, fs, ac = simulate_custom(items, capv, 'A', mdl)
        s=compute_scaled(kept); net=net_of(kept); ret=net/peak*100 if peak else 0
        line('A满仓不买  %-4s | %+10.0f %8.2f %7.2f %6.2f %6d | 砍%d天' % (mdl, net, ret, s['dd_pct'], s['calmar'], fo, sk))

# ============ 2. 连续 cap 扫描 5-20万 ============
line('')
line('='*130)
line('2. G 连续 cap 扫描 5-20万每1万: FIFO(b0/b1) + 手段A(b0=b1) + LIFO b0 + P<=5d b0')
line('%-4s | %9s %8s | %9s %8s | %9s %8s | %9s %8s | %9s %8s' % ('cap万','FIFOb0净','FIFOb0%','FIFOb1净','FIFOb1%','手段A净','手段A%','LIFOb0净','LIFOb0%','P5d净','P5d%'))
ref_ret = None
fifo_rows=[]
for capv in range(50000, 200001, 10000):
    r=[]
    for meth, mdl in [('B','b0'),('B','b1'),('A','b0'),('F','b0'),('P','b0')]:
        kept, peak, sk, fo, na, td, fs, ac = simulate_custom(items, capv, meth, mdl, P_N=5)
        net=net_of(kept); ret=net/peak*100 if peak else 0
        r.append((net,ret,sk,fo))
    if capv==200000: ref_ret = r[0][1]
    fifo_rows.append((capv, r[0][1]))
    line('%-4.0f | %+8.0f %7.2f | %+8.0f %7.2f | %+8.0f %7.2f | %+8.0f %7.2f | %+8.0f %7.2f' % (
        capv/10000, r[0][0], r[0][1], r[1][0], r[1][1], r[2][0], r[2][1], r[3][0], r[3][1], r[4][0], r[4][1]))

# ============ 3. 稳健性 ============
line('')
line('='*130)
line('3. 稳健性: FIFO 20万(95.66基准) vs 手段A各档 vs 候选, 多起始时点+随机抽查')

def stats_of(kept, peak):
    net=net_of(kept); ret=net/peak*100 if peak else 0
    wins=sum(1 for t in kept if t[0]>0)
    wr=wins/len(kept)*100 if kept else 0
    srt=sorted(kept, key=lambda x:x[3] or '99999999')
    cum=0; peakc=0; maxdd=0
    for t in srt:
        cum+=t[0]; peakc=max(peakc,cum); maxdd=max(maxdd,peakc-cum)
    return net, ret, wr, maxdd

def run_series(meth, capv, mdl, start_date):
    kept, peak, sk, fo, na, td, fs, ac = simulate_custom(items, capv, meth, mdl, start_date=start_date)
    return stats_of(kept, peak)

def run_random(meth, capv, mdl, n=30, seed=42, rng_min='20110221', rng_max='20241231'):
    random.seed(seed)
    d1=datetime.strptime(rng_min,'%Y%m%d'); d2=datetime.strptime(rng_max,'%Y%m%d')
    span=(d2-d1).days
    rows=[]
    for _ in range(n):
        start=(d1+timedelta(days=random.randint(0,span))).strftime('%Y%m%d')
        kept, peak, sk, fo, na, td, fs, ac = simulate_custom(items, capv, meth, mdl, start_date=start)
        net,ret,wr,dd = stats_of(kept, peak)
        rows.append((start,len(kept),net,ret,wr,dd,sk))
    return rows

CONFIGS = [
    ('FIFO b0 20万', 'B', 200000, 'b0'),
    ('FIFO b0 15万', 'B', 150000, 'b0'),
    ('手段A 15万', 'A', 150000, 'b0'),
    ('手段A 20万', 'A', 200000, 'b0'),
    ('手段A 13万', 'A', 130000, 'b0'),
    ('手段A 10万', 'A', 100000, 'b0'),
    ('LIFO b0 20万', 'F', 200000, 'b0'),
    ('P5d b0 20万', 'P', 200000, 'b0'),
]
for tag, meth, capv, mdl in CONFIGS:
    line('')
    line('-'*130)
    line('G %s: 多起始时点(2011-2025每年0101 -> 2026)' % tag)
    line('%-6s | %6s | %12s %9s | %12s %9s | %7s %9s %5s' % ('起始年','笔数','FIFO20净','FIFO20%','本档净','本档收益%','胜率%','回撤abs','砍天'))
    ser=[]
    for SY in range(2011,2026):
        start='%d0101'%SY
        k2,p2,sk2,fo2,na2,td2,fs2,ac2 = simulate_custom(items, 200000, 'B', 'b0', start_date=start)
        n2,r2 = net_of(k2), net_of(k2)/p2*100 if p2 else 0
        kept, peak, sk, fo, na, td, fs, ac = simulate_custom(items, capv, meth, mdl, start_date=start)
        net,ret,wr,dd = stats_of(kept, peak)
        ser.append((SY,len(kept),net,ret,wr,dd,sk,n2,r2))
        line('%-6d | %6d | %+11.0f %8.2f | %+11.0f %8.2f | %6.1f %9.0f %5d' % (SY, len(kept), n2, r2, net, ret, wr, dd, sk))
    rets=[r[3] for r in ser]; fifos=[r[8] for r in ser]
    line('  多起始统计: 本档收益 min=%+.1f 均值=%+.1f 中位=%+.1f max=%+.1f | FIFO20万基准 各起点均值=%+.1f' % (
        min(rets), sum(rets)/len(rets), sorted(rets)[len(rets)//2], max(rets), sum(fifos)/len(fifos)))
    ge_all = all(r[3]>r[8] for r in ser)
    line('  全部起点 > 对应FIFO20万: %s' % ('是' if ge_all else '否'))
    if not ge_all:
        diffs=[r[0] for r in ser if r[3]<=r[8]]
        line('    不敌起点: %s' % diffs)
    rnd=run_random(meth, capv, mdl)
    rr=[r[3] for r in rnd]; rn=[r[2] for r in rnd]; rw=[r[4] for r in rnd]
    line('  随机抽查30点: 收益 min=%+.1f 均值=%+.1f 中位=%+.1f max=%+.1f | 净利min=%+.0f 中位=%+.0f | 胜率min=%.1f 中位=%.1f' % (
        min(rr), sum(rr)/len(rr), sorted(rr)[len(rr)//2], max(rr), min(rn), sorted(rn)[len(rn)//2], min(rw), sorted(rw)[len(rw)//2]))
    neg=[r for r in rn if r<0]
    line('  随机抽查负净利样本: %d/30' % len(neg))

# ============ 4. G FIFO 利润结构 vs H/I ============
line('')
line('='*130)
line('4. G FIFO 20万 b0 利润结构(自然/强平 + 持仓段) vs H/I FIFO 20万 b0')
def profit_struct(mode):
    it=daily_pool_items(mode, DEFAULT_NEW, 1)
    kept, peak, sk, fo, na, td, fs, ac = simulate_custom(it, 200000, 'B', 'b0')
    # 自然 vs 强平
    nat_kept=[t for t in kept if t[3]!='99999999' and t[3]==t[3]]  # 强平 sd=dt
    # 分辨: 强平单 sd 被改成 dt(强制日), 自然单 sd 保持原卖出日. 用原items对比不可行, 改用 fs 信息
    # fs 是强平列表 (持天,原利,原rp,原bd,原sd). 统计强平自然利.
    fnat=sum(x[1] for x in fs); fcnt=len(fs)
    # 持仓段分桶(所有 kept 按 sd-bd 或 hd)
    buckets={'short(<=20d)':[0,0.0],'mid(21-100d)':[0,0.0],'long(>100d)':[0,0.0],'未平':[0,0.0]}
    for (pr,rp,bd,sd,hd,amt) in kept:
        if sd=='99999999': key='未平'
        else:
            span=cal_span(bd,sd)
            if span<=20: key='short(<=20d)'
            elif span<=100: key='mid(21-100d)'
            else: key='long(>100d)'
        buckets[key][0]+=1; buckets[key][1]+=pr
    return dict(kept=kept, net=net_of(kept), peak=peak, ret=net_of(kept)/peak*100,
                forced_cnt=fcnt, forced_nat_profit=fnat, buckets=buckets, n_nat=na, n_traded=td)
for m in ['G','H','I']:
    st=profit_struct(m)
    line('')
    line('--- %s FIFO 20万 b0: 净=%+.0f 收益=%.2f%% 峰值=%.0f x%.1f 总笔数=%d 自然卖出=%d 强平=%d 强平自然利=%+.0f' % (
        m, st['net'], st['ret'], st['peak'], st['peak']/DAILY, len(st['kept']), st['n_nat'], st['forced_cnt'], st['forced_nat_profit']))
    for k,(n,pr) in st['buckets'].items():
        if n:
            line('    %-14s n=%5d 净=%+10.0f 均=%+.0f' % (k, n, pr, pr/n))

with open('docs/kelly/position/kelly_ghi_g_scan_out.txt','w') as f: f.write('\n'.join(out))
print('\n'.join(out))
