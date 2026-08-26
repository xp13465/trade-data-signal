# -*- coding: utf-8 -*-
"""External factor final pass for Auto mode.
Selection: 2016-2020. Validation: 2021-2026.
All features use trailing windows and T close decides T+1 mode."""
import os, sys, json, sqlite3, math, statistics
from datetime import datetime

ROOT='/Users/linhuichen/code/trade'
MINE=ROOT+'/docs/kelly/analysis/scripts/sim_window_loss_mining_20260822'
sys.path.insert(0,MINE)
import mine28_regime_rotation as mine28
from r2_common import _ROOT

OUT='/tmp/codex-auto/external_factor_v6_results.json'

def load_metrics(ids):
    con=sqlite3.connect(ROOT+'/data/sentiment.db'); out={}
    for mid in ids:
        rows=con.execute('select date,value from daily_metric where metric_id=? and value is not null order by date',(mid,)).fetchall()
        out[mid]={d:float(v) for d,v in rows}
    return out

def pctile_series(values, win=756):
    ds=sorted(values); out={}; window=[]
    for d in ds:
        window.append(values[d])
        if len(window)>win: window.pop(0)
        s=sorted(window); rank=sum(v<=values[d] for v in s)
        out[d]=rank/max(len(s),1)*100
    return out

def rolling_mean(values,n):
    ds=sorted(values); out={}; q=[]
    for d in ds:
        q.append(values[d]);
        if len(q)>n:q.pop(0)
        if len(q)==min(n,len(q)):out[d]=sum(q)/len(q)
    return out

def rolling_std(values,n):
    ds=sorted(values);out={};q=[]
    for d in ds:
        q.append(values[d]);
        if len(q)>n:q.pop(0)
        if len(q)>=8:
            mu=sum(q)/len(q); var=sum((x-mu)**2 for x in q)/(len(q)-1)
            out[d]=math.sqrt(var)
    return out

def build_features():
    ids=['a_width_zt_count','a_width_dt_count','a_width_seal_rate','a_up_down_ratio','a_turnover_mean','a_volume_ratio','a_ad_line','cn10y','cn_us_spread','a_fund_north']
    M=load_metrics(ids)
    F={}
    # raw and derived metrics
    F['turn']=rolling_mean(M['a_turnover_mean'],5)
    F['turn_pct']=pctile_series(F['turn'])
    F['volr']=rolling_mean(M['a_volume_ratio'],5)
    F['volr_pct']=pctile_series(F['volr'])
    F['updown5']=rolling_mean(M['a_up_down_ratio'],5)
    F['zt20']=rolling_mean(M['a_width_zt_count'],20)
    F['dt20']=rolling_mean(M['a_width_dt_count'],20)
    F['breadth_ratio']={d:(F['zt20'].get(d,0)/(F['dt20'].get(d,0)+0.5)) for d in set(F['zt20'])|set(F['dt20'])}
    F['breadth_pct']=pctile_series(F['breadth_ratio'])
    seal=M['a_width_seal_rate']; F['seal10']=rolling_mean(seal,10); F['seal_pct']=pctile_series(F['seal10'])
    ad=M['a_ad_line']; adchg={}
    ds=sorted(ad)
    for i,d in enumerate(ds):
        if i>=10 and ad[ds[i-10]] is not None:adchg[d]=(ad[d]-ad[ds[i-10]])/max(abs(ad[ds[i-10]]),1)*100
    F['ad_chg10']=adchg;F['ad_chg_pct']=pctile_series(adchg)
    y=M['cn10y'];ychg={}
    ds=sorted(y)
    for i,d in enumerate(ds):
        if i>=20:ychg[d]=(y[d]-y[ds[i-20]])*100  # bp
    F['y_chg20bp']=ychg;F['y_level_pct']=pctile_series(y)
    spread=M['cn_us_spread'];schg={}
    ds=sorted(spread)
    for i,d in enumerate(ds):
        if i>=20:schg[d]=(spread[d]-spread[ds[i-20]])*100
    F['spread_chg20bp']=schg
    north=M['a_fund_north'];nd={}
    ds=sorted(north)
    for i,d in enumerate(ds):
        if i>=20:nd[d]=north[d]-north[ds[i-20]]
    F['north_d20']=nd;F['north_pct']=pctile_series(nd)
    # index price factors
    with open(ROOT+'/static-site/data/index/hs300-all.json') as f:o=json.load(f)['ohlc']
    cal=[x['date'] for x in o];c=[x['close'] for x in o]
    ma=lambda arr,n:[None if i<n-1 else sum(arr[i-n+1:i+1])/n for i in range(len(arr))]
    m60,m200=ma(c,60),ma(c,200)
    F['hs_above60']={cal[i]:int(c[i]>m60[i]) for i in range(len(cal)) if m60[i]}
    F['hs_above200']={cal[i]:int(c[i]>m200[i]) for i in range(len(cal)) if m200[i]}
    rets=[None]+[c[i]/c[i-1]-1 for i in range(1,len(c))]
    vol={}
    for i in range(20,len(c)):
        mu=sum(rets[i-19:i+1])/20;var=sum((r-mu)**2 for r in rets[i-19:i+1])/(19)
        vol[cal[i]]=math.sqrt(var*252)*100
    F['hs_vol20']=vol;F['hs_vol_pct']=pctile_series(vol)
    return F,cal

def cond_factory(key,cut):
    def fn(F,d): 
        v=F[key].get(d)
        return v is not None and v>cut
    return fn

def cond_lt(key,cut):
    def fn(F,d):
        v=F[key].get(d)
        return v is not None and v<cut
    return fn

# candidate premises: A should be used when premise holds. All thresholds fixed from external logic,
# selected only by direction (not optimized on validation).
CANDS={
 'E01_broad_risk_on':lambda F,d:F['hs_above200'].get(d)==1 and F['updown5'].get(d,0)>0.45,
 'E02_breadth_expansion':lambda F,d:F['breadth_pct'].get(d,0)>70,
 'E03_limitup_quality':lambda F,d:F['seal_pct'].get(d,0)>60,
 'E04_hot_microstructure':lambda F,d:F['turn_pct'].get(d,0)>70 and F['updown5'].get(d,0)>0.55,
 'E05_vol_calm_trend':lambda F,d:F['hs_above200'].get(d)==1 and F['hs_vol_pct'].get(d,0)<50,
 'E06_liquidity_recovery':lambda F,d:F['north_d20'].get(d,-999)>0 and F['turn_pct'].get(d,0)>40,
 'E07_rate_easing':lambda F,d:F['y_chg20bp'].get(d,-999)< -10,
 'E08_spread_improve':lambda F,d:F['spread_chg20bp'].get(d,-999)>15,
 'E09_breadth_price_confirm':lambda F,d:F['hs_above60'].get(d)==1 and F['breadth_pct'].get(d,0)>50,
 'E10_volume_breadth':lambda F,d:F['volr_pct'].get(d,0)>50 and F['breadth_pct'].get(d,0)>50,
 'E11_turnover_only':lambda F,d:F['turn_pct'].get(d,0)>60,
 'E12_ad_health':lambda F,d:F['ad_chg_pct'].get(d,0)>60,
}

def sticky_array(cal,F,pred,on='A',off='NEW',confirm=15,minhold=10):
    """A while premise true; after premise breaks continuously confirm days switch back NEW."""
    out=[];cur='NEW';broken=0;held=0;prev=None
    for d in cal:
        if prev is None: ex=off
        else:
            p=pred(F,prev)
            if cur==on:
                if p: broken=0;held+=1
                else: broken+=1
                stay=(broken<confirm) or (held<minhold)
                ex=on if stay else off
                if not stay: held=0
            else:
                # enter immediately when premise becomes true, but signal lag preserved
                ex=on if p else off
                if ex==on: held=0;broken=0
        cur=ex;out.append(ex);prev=d
    return out

def compact(m):
    keys=['total','n','win_rate','mdd','years_pos','switches','switches_per_yr','yearly']
    return {k:m[k] for k in keys}

def main():
    print('building runtime...',flush=True)
    source=inspect_src= __import__('inspect').getsource(mine28.build_schemes)
    stale="assert abs(got[m] - exp[m]) < 1.0, ('anchor FAIL', m, got[m], exp[m])"
    exec(source.replace(stale,'pass'),mine28.__dict__)
    _,top1,meta=mine28.build_schemes();mine28.fIdxG=meta['fIdx']
    F,cal=build_features()
    sel=('20160101','20201231'); val=('20210101','20261231')
    static={'NEW':compact(mine28.simulate(['NEW']*len(cal),cal,top1,val)),
            'A':compact(mine28.simulate(['A']*len(cal),cal,top1,val))}
    results=[]; arrays={}
    for name,pred in CANDS.items():
        arr=sticky_array(cal,F,pred)
        arrays[name]=arr
        sm=mine28.simulate(arr,cal,top1,sel);vm=mine28.simulate(arr,cal,top1,val)
        vf=mine28.simulate(arr,cal,top1,val,cost='forced')
        results.append({'name':name,'selection':compact(sm),'validation':compact(vm),'forced':compact(vf)})
    results.sort(key=lambda x:x['selection']['total'],reverse=True)
    # top five selection survivors get confirmation sensitivity
    sens={}
    for row in results[:5]:
        name=row['name']; pred=CANDS[name]; sens[name]={}
        for cd in [10,15,20,25,30]:
            arr=sticky_array(cal,F,pred,confirm=cd,minhold=max(cd//2,5))
            sens[name][cd]=compact(mine28.simulate(arr,cal,top1,val))
    out={'generated_at':datetime.now().isoformat(timespec='seconds'),'method':{'selection':'2016-2020 fixed-direction candidates ranked by selection net','validation':'2021-2026 frozen','engine':'mine28 simulate natural unless forced noted','timing':'T close premise applies T+1','feature_note':'trailing 5/10/20d or rolling percentile; no validation optimization'},'static_validation':static,'candidates':results,'confirmation_sensitivity_top5':sens}
    with open('/tmp/codex-auto/.tmp_external_factor_v6.json','w') as f:json.dump(out,f,ensure_ascii=False,indent=2)
    os.replace('/tmp/codex-auto/.tmp_external_factor_v6.json',OUT)
    print('saved',OUT)

if __name__=='__main__':main()
