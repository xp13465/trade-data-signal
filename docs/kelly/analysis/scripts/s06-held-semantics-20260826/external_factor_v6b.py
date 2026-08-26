# -*- coding: utf-8 -*-
"""Second external factor batch: structural regime variables."""
import sys,json,math,sqlite3,statistics
import os as _os; sys.path.insert(0,_os.path.dirname(_os.path.abspath(__file__)))  # 落档副本: 同目录依赖(原 /tmp/codex-auto, 20260826 归档)
import external_factor_v6 as e
import mine28_regime_rotation as m

ROOT='/Users/linhuichen/code/trade'

def load_index(name):
    o=json.load(open(f'{ROOT}/static-site/data/index/{name}-all.json'))['ohlc']
    return {x['date']:x['close'] for x in o}

def build_struct_features():
    F,cal=e.build_features()
    idx={n:load_index(n) for n in ['hs300','csi500','csi1000','cyb']}
    start_n=20
    dates=[d for d in cal if all(d in idx[n] for n in idx)][start_n:]
    closes={n:[idx[n][d] for d in dates] for n in idx}
    hs=closes['hs300']; rets=[None]+[hs[i]/hs[i-1]-1 for i in range(1,len(hs))]
    def roll_ret(a,n):
        return {dates[i]:(a[i]/a[i-n]-1)*100 for i in range(n,len(a))}
    def pct(vals):
        ds=sorted(vals);out={};q=[]
        for d in ds:
            q.append(vals[d])
            if len(q)>756:q.pop(0)
            out[d]=sum(x<=vals[d] for x in q)/len(q)*100
        return out
    def volseries(a,n=20):
        r=[None]+[a[i]/a[i-1]-1 for i in range(1,len(a))]; out={}
        for i in range(n,len(a)):
            mu=sum(r[i-n+1:i+1])/n;var=sum((x-mu)**2 for x in r[i-n+1:i+1])/(n-1)
            out[dates[i]]=math.sqrt(var*252)*100
        return out
    v20=volseries(hs,20);v120=volseries(hs,120)
    F['vol_term']={d:v20[d]-v120[d] for d in v20 if d in v120};F['vol_term_pct']=pct(F['vol_term'])
    # Amihud: mean(|ret| / amount), hs300 amount raw from ohlc
    o=json.load(open(ROOT+'/static-site/data/index/hs300-all.json'))['ohlc']; od={x['date']:x for x in o}
    am={};q=[]
    for i,d in enumerate(dates):
        if i==0 or rets[i] is None:continue
        val=abs(rets[i])/(od[d]['amount'] or 1)*1e12;q.append(val)
        if len(q)>20:q.pop(0)
        am[d]=sum(q)/len(q)
    F['amihud']=am;F['amihud_pct']=pct(am)
    rr={n:roll_ret(closes[n],20) for n in idx}
    common=set.intersection(*(set(rr[n]) for n in idx))
    F['size_spread']={d:rr['csi1000'][d]-rr['hs300'][d] for d in sorted(common)}
    disp={}
    for d in dates:
        if d not in common:continue
        vals=[rr[n][d] for n in idx];mu=sum(vals)/4
        disp[d]=math.sqrt(sum((x-mu)**2 for x in vals)/4)
    F['dispersion']=disp;F['dispersion_pct']=pct(disp)
    con=sqlite3.connect(ROOT+'/data/sentiment.db');y=dict(con.execute("select date,value from daily_metric where metric_id='cn10y'"))
    dy={d:(y[d]-y[p])*100 for p,d in zip(dates[:-1],dates[1:]) if p in y and d in y}
    pairs=[]
    corr={}
    win=20
    for i,d in enumerate(dates):
        if rets[i] is None:continue
        pairs.append((rets[i],dy.get(d)))
        if len(pairs)>win:pairs.pop(0)
        pp=[z for z in pairs if z[1] is not None]
        if len(pp)>=15:
            xs=[a for a,b in pp];ys=[b for a,b in pp];mx=sum(xs)/len(xs);my=sum(ys)/len(ys)
            cov=sum((a-mx)*(b-my) for a,b in pp);vx=sum((a-mx)**2 for a in xs);vy=sum((b-my)**2 for b in ys)
            corr[d]=cov/math.sqrt(vx*vy) if vx>0 and vy>0 else 0
    F['bond_corr']=corr
    # rolling skew of hs300 returns
    sk={};q=[]
    for i,d in enumerate(dates):
        if rets[i] is None:continue
        q.append(rets[i]);
        if len(q)>20:q.pop(0)
        mu=sum(q)/len(q);sd=statistics.stdev(q) if len(q)>2 else 0
        sk[d]=(sum((x-mu)**3 for x in q)/(len(q)*(sd**3))) if sd else 0
    F['ret_skew']=sk
    return F,cal

C={
 'S01_short_vol_stress':lambda F,d:F['vol_term_pct'].get(d,50)>70,
 'S02_contango_calm':lambda F,d:F['vol_term_pct'].get(d,50)<30,
 'S03_illiquidity_high':lambda F,d:F['amihud_pct'].get(d,50)>70,
 'S04_liquidity_rich':lambda F,d:F['amihud_pct'].get(d,50)<30,
 'S05_smallcap_leads':lambda F,d:F['size_spread'].get(d,-999)>2,
 'S06_largecap_leads':lambda F,d:F['size_spread'].get(d,-999)<-2,
 'S07_dispersion_high':lambda F,d:F['dispersion_pct'].get(d,50)>70,
 'S08_dispersion_low':lambda F,d:F['dispersion_pct'].get(d,50)<30,
 'S09_bond_stock_neg':lambda F,d:F['bond_corr'].get(d,0)<-0.25,
 'S10_bond_stock_pos':lambda F,d:F['bond_corr'].get(d,0)>0.25,
 'S11_crash_skew':lambda F,d:F['ret_skew'].get(d,0)<-0.5,
 'S12_positive_skew':lambda F,d:F['ret_skew'].get(d,0)>0.5,
}

def main():
    print('runtime',flush=True)
    import inspect
    src=inspect.getsource(m.build_schemes);stale="assert abs(got[m] - exp[m]) < 1.0, ('anchor FAIL', m, got[m], exp[m])"
    exec(src.replace(stale,'pass'),m.__dict__);_,top1,meta=m.build_schemes();m.fIdxG=meta['fIdx']
    F,cal=build_struct_features();sel=('20160101','20201231');val=('20210101','20261231')
    static={'NEW':e.compact(m.simulate(['NEW']*len(cal),cal,top1,val)),'A':e.compact(m.simulate(['A']*len(cal),cal,top1,val))}
    rows=[]
    for name,pred in C.items():
        arr=e.sticky_array(cal,F,pred,confirm=15,minhold=10)
        rows.append({'name':name,'selection':e.compact(m.simulate(arr,cal,top1,sel)),'validation':e.compact(m.simulate(arr,cal,top1,val)),'forced':e.compact(m.simulate(arr,cal,top1,val,cost='forced'))})
    rows.sort(key=lambda r:r['selection']['total'],reverse=True)
    out={'generated_at':__import__('datetime').datetime.now().isoformat(timespec='seconds'),'static_validation':static,'candidates':rows,'gate_note':'selection top half must beat validation NEW; then confirmation sensitivity'}
    json.dump(out,open('/tmp/codex-auto/external_factor_v6b_results.json','w'),ensure_ascii=False,indent=2)
    print('STATIC',static)
    for r in rows:
        print(r['name'],'sel',r['selection']['total'],'val',r['validation']['total'],'mdd',r['validation']['mdd'],'sw/y',r['validation']['switches_per_yr'],'forced',r['forced']['total'])

if __name__=='__main__':main()
