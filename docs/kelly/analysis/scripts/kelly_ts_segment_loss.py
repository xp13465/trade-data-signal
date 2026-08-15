# -*- coding: utf-8 -*-
"""
# track_score 跟踪分分段亏损概率回测 (2026-08-15)
目的: 验证假设「track_score 是否存在特定分段的交易亏损概率特别大; 剔除该段能否提高收益率/降低最大回撤」
方法口径: v1.0.0 基准 = AI宏7键(默认推荐) + 每日资金池等分 + topK K=1;
         G 模式用 13万 P≤3d「先卖年轻仓」可操作口径(b0 保守下界); A/F 模式每日池直接算(无 cap)。
         分段: 等宽(5/10段) + 分位数(基于候选池 P20/40/60/80 与 P10..P90) 两套口径。
         信号层(候选池)静态分段 + 组合层(topK选出)静态分段 + 剔除验证(每日池选择前剔除该段→重算topK→组合指标)。
         交叉维度: market_state(regime依赖, 借鉴社区MRP/regime-split方法) / rating / signal / track_tier。
输入: static-site/data/signal_kelly_trades.json (generated_at 2026-08-15 19:08)
依赖: docs/kelly/scripts/dailypool_rerun_core.py + /tmp/kelly_combo_advice_analysis.py + /tmp/kelly_posfilter_backtest.py
输出: stdout + docs/kelly/analysis/data/kelly_ts_segment_loss.json
复现: python3 docs/kelly/analysis/scripts/kelly_ts_segment_loss.py
"""
import sys, os, contextlib, io, json, math
from collections import defaultdict
os.chdir('/Users/linhuichen/code/trade')
sys.path.insert(0,'docs/kelly/scripts'); sys.path.insert(0,'/tmp'); sys.path.insert(0,'/Users/linhuichen/code/trade')
with contextlib.redirect_stdout(io.StringIO()):
    from dailypool_rerun_core import DEFAULT_NEW, DAILY, full_sort_key, compute_scaled
from kelly_posfilter_backtest import base_signals, get_by_date, base_key
from kelly_combo_advice_analysis import passes_fade, fIdx
from datetime import datetime, timedelta
import numpy as np

OUT = {}

def cal_span(bd, sd):
    if not bd or not sd or sd < bd: return 0
    try:
        d1=datetime.strptime(bd,"%Y%m%d"); d2=datetime.strptime(sd,"%Y%m%d")
        return max((d2-d1).days,0)
    except: return 0
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

def daily_pool_kept(mode, F, K, ts_excl_fn=None):
    bd = get_by_date(mode)
    kept_keys = set()
    for sd, rows in bd.items():
        fr = [t for t in rows if passes_fade(t, F)]
        if ts_excl_fn is not None:
            fr = [t for t in fr if not ts_excl_fn(t)]
        if not fr: continue
        srt = sorted(fr, key=full_sort_key)[:K]
        for t in srt: kept_keys.add(base_key(t))
    return [t for t in base_signals(mode) if base_key(t) in kept_keys]

def items_from_kept(mode, kept_trades, F, K, ts_excl_fn=None):
    bd = get_by_date(mode)
    kept_keys = set(base_key(t) for t in kept_trades)
    day_counts = defaultdict(int)
    for sd, rows in bd.items():
        fr = [t for t in rows if passes_fade(t, F)]
        if ts_excl_fn is not None:
            fr = [t for t in fr if not ts_excl_fn(t)]
        if not fr: continue
        srt = sorted(fr, key=full_sort_key)[:K]
        day_counts[sd] = len(srt)
    items = []
    for sd, rows in bd.items():
        n = day_counts.get(sd, 0)
        if n == 0: continue
        amt = DAILY / n
        for t in rows:
            if base_key(t) not in kept_keys: continue
            bp = t[fIdx['profit']] or 0; rp = t[fIdx['return_pct']] or 0
            items.append((bp*(amt/DAILY), rp, str(t[fIdx['buy_date']] or ''), str(t[fIdx['sell_date']] or ''), t[fIdx['hold_days']] or 0, amt))
    return items

def seg_stats(trades, label):
    if not trades: return None
    profits = [t[fIdx['profit']] or 0 for t in trades]
    rps = [t[fIdx['return_pct']] or 0 for t in trades]
    n = len(profits)
    wins = [p for p in profits if p > 0]; losses = [p for p in profits if p < 0]
    flat = sum(1 for p in profits if p == 0)
    win_rate = len(wins)/n*100
    loss_prob = len(losses)/n*100
    net = sum(profits)
    avg_rp = sum(rps)/n
    loss_amt = sum(losses)
    avg_win = sum(wins)/len(wins) if wins else 0
    avg_loss = abs(sum(losses)/len(losses)) if losses else 0
    plr = avg_win/avg_loss if (len(wins)>0 and len(losses)>0) else None
    return {'label':label,'n':n,'win_rate':round(win_rate,1),'loss_prob':round(loss_prob,1),
            'net':round(net),'avg_rp':round(avg_rp,2),'loss_amt':round(loss_amt),
            'plr':round(plr,2) if plr else None,'flat':flat}

def chi2_seg(trades, bins, overall_loss_prob):
    """卡方检验: 各段亏损比例 vs 整体是否显著差异"""
    import math as m
    table = []
    for label, fn in bins:
        seg = [t for t in trades if fn(t)]
        n = len(seg)
        if n == 0: continue
        loss = sum(1 for t in seg if (t[fIdx['profit']] or 0) < 0)
        table.append((label, n, loss))
    N = sum(r[1] for r in table)
    if N == 0: return None
    total_loss = sum(r[2] for r in table)
    total_win = N - total_loss
    chi2 = 0.0
    for label, n, loss in table:
        win = n - loss
        exp_loss = n * total_loss / N
        exp_win = n * total_win / N
        if exp_loss > 0: chi2 += (loss - exp_loss)**2 / exp_loss
        if exp_win > 0: chi2 += (win - exp_win)**2 / exp_win
    return {'chi2': round(chi2,2), 'k': len(table), 'N': N}

def equal_bins(edges):
    def fn(lo,hi):
        def f(t):
            ts = t[fIdx['track_score']]
            return ts is not None and lo <= ts < hi
        return f
    return [(f'{lo}-{hi}', fn(lo,hi)) for lo,hi in zip(edges[:-1], edges[1:])]

# ============ 主分析 ============
res_all = {}
for mode in ['G','A','F']:
    base = base_signals(mode)
    filtered = [t for t in base if passes_fade(t, DEFAULT_NEW)]
    kept0 = daily_pool_kept(mode, DEFAULT_NEW, 1)
    OUT.setdefault(mode, {})
    OUT[mode]['candidate_n'] = len(filtered)
    OUT[mode]['topk_n'] = len(kept0)
    ts_arr = np.array([t[fIdx['track_score']] for t in filtered])
    qs5 = (np.percentile(ts_arr,q) for q in [20,40,60,80])
    bins_eq5 = equal_bins([0,20,40,60,80,100])
    bins_q5 = equal_bins([0]+[np.percentile(ts_arr,q) for q in [20,40,60,80]]+[100])
    bins_eq10 = equal_bins(list(range(0,101,10)))
    bins_q10 = equal_bins([0]+[np.percentile(ts_arr,q) for q in range(10,100,10)]+[100])
    bins_all = {'等宽5段':bins_eq5, '分位数5段':bins_q5, '等宽10段':bins_eq10, '分位数10段':bins_q10}

    # 基线(组合层)
    items0 = items_from_kept(mode, kept0, DEFAULT_NEW, 1)
    if mode == 'G':
        k_b0, pk_b0, sk, fo, nat, td, fs, ac = simulate_custom(items0, 130000, 'P', 'b0', P_N=3)
        s_base = compute_scaled(k_b0)
        base_desc = 'G 13万 P≤3d b0'
    else:
        k_b0 = items0; s_base = compute_scaled(items0)
        base_desc = f'{mode} 每日池K1'
    OUT[mode]['baseline'] = {'desc':base_desc,'net':s_base['net'],'ret':s_base['ret'],'dd_pct':s_base['dd_pct'],'n':s_base['n']}

    # 信号层静态
    sig_static = {}
    all_s = seg_stats(filtered, '整体')
    for bname, bins in bins_all.items():
        rows = [seg_stats([t for t in filtered if fn(t)], label) for label, fn in bins]
        sig_static[bname] = {'rows':rows, 'overall':all_s, 'chi2':chi2_seg(filtered, bins, all_s['loss_prob'])}
    OUT[mode]['signal_static'] = sig_static

    # 组合层静态
    top_static = {}
    all_t = seg_stats(kept0, '整体')
    for bname, bins in bins_all.items():
        rows = [seg_stats([t for t in kept0 if fn(t)], label) for label, fn in bins]
        top_static[bname] = {'rows':rows, 'overall':all_t}
    OUT[mode]['topk_static'] = top_static

    # 剔除验证(单段)
    excl = {}
    for bname, bins in [('等宽5段',bins_eq5), ('分位数5段',bins_q5)]:
        rows = []
        for label, fn in bins:
            kept_ex = daily_pool_kept(mode, DEFAULT_NEW, 1, ts_excl_fn=fn)
            items_ex = items_from_kept(mode, kept_ex, DEFAULT_NEW, 1, ts_excl_fn=fn)
            if mode == 'G':
                k_ex, pk_ex, *_ = simulate_custom(items_ex, 130000, 'P', 'b0', P_N=3)
                s_ex = compute_scaled(k_ex)
            else:
                s_ex = compute_scaled(items_ex)
            rows.append({'segment':label, 'deleted':len(kept0)-len(kept_ex), 'net':s_ex['net'],
                         'dnet':s_ex['net']-s_base['net'], 'ret':s_ex['ret'], 'dret':s_ex['ret']-s_base['ret'],
                         'dd_pct':s_ex['dd_pct']})
        excl[bname] = rows
    OUT[mode]['excl_single'] = excl

    # 剔除验证(多段联合: 信号层亏概率最高的2-3段)
    q5_rows = sig_static['分位数5段']['rows']
    ranked = sorted([r for r in q5_rows if r], key=lambda r:-r['loss_prob'])
    combos = {'最差2段': ranked[:2], '最差3段': ranked[:3]}
    excl_multi = {}
    for cname, rws in combos.items():
        labels = [r['label'] for r in rws]
        def fn_multi(t, labels=labels):
            ts = t[fIdx['track_score']]
            if ts is None: return False
            for lo,hi in [tuple(l.split('-')) for l in labels]:
                if float(lo) <= ts < float(hi): return True
            return False
        kept_ex = daily_pool_kept(mode, DEFAULT_NEW, 1, ts_excl_fn=fn_multi)
        items_ex = items_from_kept(mode, kept_ex, DEFAULT_NEW, 1, ts_excl_fn=fn_multi)
        if mode == 'G':
            k_ex, pk_ex, *_ = simulate_custom(items_ex, 130000, 'P', 'b0', P_N=3)
            s_ex = compute_scaled(k_ex)
        else:
            s_ex = compute_scaled(items_ex)
        excl_multi[cname] = {'segments':labels, 'deleted':len(kept0)-len(kept_ex), 'net':s_ex['net'],
                             'dnet':s_ex['net']-s_base['net'], 'ret':s_ex['ret'], 'dret':s_ex['ret']-s_base['ret'],
                             'dd_pct':s_ex['dd_pct']}
    OUT[mode]['excl_multi'] = excl_multi

# ============ 交叉维度 (信号层, G模式) ============
mode = 'G'
base = base_signals(mode)
filtered = [t for t in base if passes_fade(t, DEFAULT_NEW)]
bins_q5 = equal_bins([0]+[np.percentile(np.array([t[fIdx['track_score']] for t in filtered]),q) for q in [20,40,60,80]]+[100])
cross = {}
for dim_name, getter in [
    ('market_state', lambda t: 'True(多头)' if t[fIdx['market_state']] is True else ('False(空头)' if t[fIdx['market_state']] is False else 'None')),
    ('rating', lambda t: str(t[fIdx['rating']] or 'None')),
    ('signal', lambda t: str(t[fIdx['signal']] or 'None')),
    ('track_tier', lambda t: str(t[fIdx['track_tier']] or 'None')),
]:
    dim_vals = sorted(set(getter(t) for t in filtered))
    rows_out = []
    for label, fn in bins_q5:
        for dv in dim_vals:
            seg = [t for t in filtered if fn(t) and getter(t)==dv]
            s = seg_stats(seg, f'{label}x{dv}')
            if s and s['n'] >= 10:
                rows_out.append(s)
    cross[dim_name] = rows_out
OUT['G']['cross_dim'] = cross

# 保存
json.dump(OUT, open('/Users/linhuichen/code/trade/docs/kelly/analysis/data/kelly_ts_segment_loss.json','w'), ensure_ascii=False, indent=1)

# ============ 打印 ============
for mode in ['G','A','F']:
    o = OUT[mode]
    b = o['baseline']
    print('='*110)
    print('[%s] 基线: %s | 候选池 n=%d, topK n=%d' % (mode, b['desc'], o['candidate_n'], o['topk_n']))
    print('  净=%+.0f 收益率=%.2f%% 回撤=%.2f%% 交易n=%d' % (b['net'], b['ret'], b['dd_pct'], b['n']))
    print('\n-- 信号层静态(候选池) --')
    for bname, blk in o['signal_static'].items():
        print(f'  [{bname}] 整体: n={blk["overall"]["n"]} 亏概率={blk["overall"]["loss_prob"]}% 净={blk["overall"]["net"]} | chi2={blk["chi2"]}')
        for r in blk['rows']:
            if r is None: continue
            print('    %-12s n=%4d 胜率=%5.1f 亏概=%5.1f 净=%+9.0f 均收=%5.2f 盈亏比=%s' % (r['label'],r['n'],r['win_rate'],r['loss_prob'],r['net'],r['avg_rp'],r['plr']))
    print('\n-- 组合层静态(topK选出) --')
    for bname, blk in o['topk_static'].items():
        print(f'  [{bname}] 整体: n={blk["overall"]["n"]} 亏概率={blk["overall"]["loss_prob"]}% 净={blk["overall"]["net"]}')
        for r in blk['rows']:
            if r is None: continue
            print('    %-12s n=%4d 胜率=%5.1f 亏概=%5.1f 净=%+9.0f 均收=%5.2f 盈亏比=%s' % (r['label'],r['n'],r['win_rate'],r['loss_prob'],r['net'],r['avg_rp'],r['plr']))
    print('\n-- 剔除验证(单段, 每日池选择前剔除) --')
    print('  基线: 净=%+.0f 收益=%.2f%% 回撤=%.2f%%' % (b['net'], b['ret'], b['dd_pct']))
    for bname, rows in o['excl_single'].items():
        print(f'  [{bname}]')
        for r in rows:
            print('    %-12s 删%4d 净=%+9.0f(Δ%+8.0f) 收益=%7.2f(Δ%+6.2f) 回撤=%5.2f' % (r['segment'],r['deleted'],r['net'],r['dnet'],r['ret'],r['dret'],r['dd_pct']))
    print('\n-- 剔除验证(多段联合) --')
    for cname, r in o['excl_multi'].items():
        print('    %-8s %s 删%4d 净=%+9.0f(Δ%+8.0f) 收益=%7.2f(Δ%+6.2f) 回撤=%5.2f' % (cname, r['segments'], r['deleted'], r['net'], r['dnet'], r['ret'], r['dret'], r['dd_pct']))

print('\n' + '='*110)
print('[G 交叉维度](信号层 分位数5段, n>=10)')
for dim_name, rows in OUT['G']['cross_dim'].items():
    print(f'\n-- {dim_name} --')
    for r in rows:
        print('    %-16s n=%4d 胜率=%5.1f 亏概=%5.1f 净=%+9.0f 均收=%5.2f' % (r['label'],r['n'],r['win_rate'],r['loss_prob'],r['net'],r['avg_rp']))
print('\n数据已存: docs/kelly/analysis/data/kelly_ts_segment_loss.json')
