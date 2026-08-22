#!/usr/bin/env python3
"""宏观驱动因子联动(共同因子框架) - 替换"表面传染"错误框架
用户原话: "美国加息黄金就跌... 全球基本也都跌。这叫联动。不是美股涨其他都涨"
核心: 共同宏观驱动力(利率/美元流动性/恐慌)同时驱动多资产同向
代理(可拿到):
  us10y 10年美债(2016起) = 利率水平/加息状态代理
  gold(2008起) = 避险+实际利率+通胀代理
  a_qvix_300/1000 = A股隐波(恐慌代理, 2012起)
  cn_us_spread = 中美利差(2016起)
  usdcnh = 美元强弱代理(2023起, 单位跳变谨慎)
缺失: 美元指数DXY/议息日历 -> 诚实标注待补
"""
import json, sqlite3, os, bisect
DB='file:/Users/linhuichen/code/trade-data/data/sentiment.db?mode=ro'
OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),'out')
c=sqlite3.connect(DB,uri=True)
sh=c.execute("SELECT date FROM index_daily WHERE index_id='sh' ORDER BY date").fetchall()
sh_dates=[r[0] for r in sh]; sh_idx={d:i for i,d in enumerate(sh_dates)}
def load_metric(mid):
    rows=c.execute("SELECT date,value FROM daily_metric WHERE metric_id=? AND value IS NOT NULL ORDER BY date",(mid,)).fetchall()
    return [(str(d),v) for d,v in rows]
def load_idx(idx):
    rows=c.execute("SELECT date,pct_change FROM index_daily WHERE index_id=? AND pct_change IS NOT NULL ORDER BY date",(idx,)).fetchall()
    return {str(d):v for d,v in rows}

def next_a_ret(idx_map, date):
    """idx_map(A股行业/指数) 在 date 之后下一个交易日的 pct_change"""
    if date not in sh_idx: return None
    i=sh_idx[date]
    if i+1>=len(sh_dates): return None
    return idx_map.get(sh_dates[i+1])

def series_next(dir_map, date):
    """海外/宏观代理在 date 的下一A股交易日(用该代理值)"""
    if date not in sh_idx: return None
    i=sh_idx[date]
    if i+1>=len(sh_dates): return None
    nd=sh_dates[i+1]
    return dir_map.get(nd)

def macro_stat(name, macro_series, target_map, use_next=False, filter_label=None, ascending=True, quantile=None):
    """macro_series: [(date, value)] 宏观代理. target_map: {date: pct} 目标资产.
    use_next=False: 信号日date -> A股下一交易日(次日预测, 常规)
    use_next=True: 用代理在A股下一交易日的位置(A股D, 信号=代理D)
    计算宏观代理变化方向 与 目标资产方向 的同向/异向"""
    # 构建代理日变化
    vals={d:v for d,v in macro_series}
    dates=sorted(vals.keys())
    hits=0; tot=0; up_t=down_t=0; up_m=0
    prev=None
    for d in dates:
        v=vals[d]
        if prev is not None and v!=prev and v!=0:
            mdir=1 if v>prev else -1
            if filter_label is not None:
                # 环境过滤: 例如 us10y 上行通道
                pass
            # 目标: A股下一交易日
            tdate = d
            if use_next:
                tdate = sh_dates[sh_idx[d]+1] if sh_idx[d]+1<len(sh_dates) else None
            tv = target_map.get(tdate) if tdate else None
            # 也测海外代理下一A股交易日处的目标? 保持简单: 目标=A股下一交易日方向
            nr = next_a_ret(target_map, d)
            if nr is None or nr==0: prev=v; continue
            tdir=1 if nr>0 else -1
            tot+=1
            if tdir>0: up_t+=1
            else: down_t+=1
            if mdir==tdir: hits+=1
        prev=v
    rate=hits/tot if tot else None
    return {'n':tot,'hit':hits,'same_rate':rate,'up_asset':up_t,'down_asset':down_t,'macro_up':up_m}

def report(name, r, base_note=''):
    if r['n']==0: print(f'  {name:<50} 无数据'); return r
    sr=f"{r['same_rate']*100:.1f}%" if r['same_rate'] is not None else '-'
    print(f"  {name:<50} n={r['n']:>4} 同向胜率={sr:>6} ({r['hit']}中) 资产涨{r['up_asset']}/跌{r['down_asset']} {base_note}")
    return r

print('=== 宏观驱动联动: 代理变化方向 -> 目标资产次日方向 ===')
print('(同向胜率>50% = 该宏观代理涨时目标也涨; <50% = 反向联动)')
results=[]

# ---- 1. us10y(利率) 变化方向 -> 黄金/A股/美股/港股 ----
us10y=load_metric('us10y'); gold_v=load_metric('gold')
sh_map=load_idx('sh'); usspx=load_idx('us_spx'); hsi=load_idx('hsi')
# 资产 map: {date: pct_change} 用指数日线
print()
print('--- 1. 美债10Y收益率日变化 -> 次日资产方向 ---')
# us10y -> 黄金: 用 daily_metric gold 构造 pct 变化
gold_pct={}
gdates=[d for d,_ in gold_v]
for i in range(1,len(gold_v)):
    d0,v0=gold_v[i-1]; d1,v1=gold_v[i]
    if v0 and v1: gold_pct[d1]=(v1-v0)/v0*100
# us10y 变化 -> 黄金
r=macro_stat('us10y升 -> 黄金次日', us10y, gold_pct); report('美债利率上行→黄金(应反向<50%)', r); results.append({**r,'name':'us10y→黄金'})
# us10y -> A股
r=macro_stat('us10y升 -> A股次日', us10y, sh_map); report('美债利率上行→A股(应反向<50%)', r); results.append({**r,'name':'us10y→A股'})
# us10y -> 美股
r=macro_stat('us10y升 -> 美股次日', us10y, usspx); report('美债利率上行→美股(应反向<50%)', r); results.append({**r,'name':'us10y→美股'})
# us10y -> 港股
r=macro_stat('us10y升 -> 港股次日', us10y, hsi); report('美债利率上行→港股(应反向<50%)', r); results.append({**r,'name':'us10y→港股'})

# ---- 2. 黄金 -> A股/美股(风险偏好联动) ----
print()
print('--- 2. 黄金涨跌 -> 次日资产方向(黄金=风险偏好+实际利率代理) ---')
r=macro_stat('黄金涨 -> A股次日', gold_v, sh_map); report('黄金涨→A股', r); results.append({**r,'name':'gold→A股'})
r=macro_stat('黄金涨 -> 美股次日', gold_v, usspx); report('黄金涨→美股', r); results.append({**r,'name':'gold→美股'})
r=macro_stat('黄金涨 -> 港股次日', gold_v, hsi); report('黄金涨→港股', r); results.append({**r,'name':'gold→港股'})

# ---- 3. 隐波 a_qvix_300(恐慌) -> A股 ----
print()
print('--- 3. A股隐波qvix变化 -> 次日(恐慌升=弱) ---')
qvix=load_metric('a_qvix_300')
r=macro_stat('隐波升 -> A股次日', qvix, sh_map); report('A股隐波上升→A股(应反向<50%)', r); results.append({**r,'name':'qvix→A股'})

# ---- 4. 中美利差 cn_us_spread -> A股 ----
print()
print('--- 4. 中美利差变化 -> A股次日 ---')
spread=load_metric('cn_us_spread')
r=macro_stat('中美利差走阔 -> A股次日', spread, sh_map); report('中美利差走阔→A股', r); results.append({**r,'name':'spread→A股'})

# ---- 5. 利率环境分档(us10y 20日均线上/下 = 加息通道/降息通道) ----
print()
print('--- 5. 利率环境分档(us10y 20日均线上方=加息通道) -> 资产表现 ---')
us10y_dates=[d for d,_ in us10y]; us10y_vals={d:v for d,v in us10y}
env_hi=[]; env_lo=[]; env_mid=[]
for i,d in enumerate(us10y_dates):
    if i<20: continue
    win=[us10y_vals[us10y_dates[j]] for j in range(i-20,i)]
    ma=sum(win)/len(win)
    v=us10y_vals[d]
    nr_sh=next_a_ret(sh_map,d); nr_gold=next_a_ret(gold_pct,d)
    if nr_sh is None: continue
    if v>ma*1.005: env_hi.append((d,nr_sh,nr_gold))
    elif v<ma*0.995: env_lo.append((d,nr_sh,nr_gold))
    else: env_mid.append((d,nr_sh,nr_gold))
for tag,grp in [('利率上行通道(20日线上方)',env_hi),('利率下行通道(20日线下方)',env_lo),('利率盘整',env_mid)]:
    if not grp: continue
    up_sh=sum(1 for _,ns,_ in grp if ns>0)
    gold_pos=sum(1 for _,ns,ng in grp if ng is not None and ng>0)
    gold_n=sum(1 for _,ns,ng in grp if ng is not None)
    print(f'  {tag:<30} n={len(grp):>4} A股次日涨率={up_sh/len(grp)*100:.1f}% 黄金次日涨率={gold_pos/gold_n*100:.1f}% (n_gold={gold_n})')

json.dump(results, open(os.path.join(OUT,'macro_drivers.json'),'w'), ensure_ascii=False, indent=1)
print('\nSaved macro_drivers.json')
