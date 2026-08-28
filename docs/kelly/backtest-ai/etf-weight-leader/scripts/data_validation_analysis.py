#!/usr/bin/env python3
"""ETF→权重龙头个股 #95 数据验证一次性分析脚本(只读, 2026-08-21)。

目的: 基于 Step1 result + Step2 stock_top_weights.db + sentiment.db 信号,
     产出 #95 数据验证报告所需的全部数字(龙头效应强弱 / 数据可用性 / 映射链覆盖)。

依赖(输入):
  - docs/kelly/backtest-ai/etf-weight-leader/data/etf_hold_verify_result.json
  - data/stock_top_weights.db(stock_top_daily 表)
  - data/sentiment.db(signal_daily 表, 再生案可重跑空跑此节)

输出: 控制台打印各维度统计摘要(报告引用)。

复现命令:
  .venv/bin/python docs/kelly/backtest-ai/etf-weight-leader/scripts/data_validation_analysis.py

数据截止: ETF 持仓 2026Q2 / 个股日线 2026-08-20 / 信号至 2026 当前。
"""
import json, sqlite3, statistics
from collections import defaultdict, Counter

PROJ = "/Users/linhuichen/code/trade"
RESULT = f"{PROJ}/docs/kelly/backtest-ai/etf-weight-leader/data/etf_hold_verify_result.json"
DB = f"{PROJ}/data/stock_top_weights.db"
SENT = f"{PROJ}/data/sentiment.db"
FOREIGN = {"hsi","hstech","hscei","us_dji","us_spx","us_ndx","us_ixic","nikkei225","dax","cac40"}
BUY = ("buy","buy_aux","buy_special","buy_backup")
WINDOW_START = "20190601"   # 个股法回测起点(见方案文档 §六)

d = json.load(open(RESULT))
etfs = d['etfs']

print("\n########## A. Step1 覆盖与去重集合 ##########")
print("coverage:", d['coverage'])
print("universe: A股=%d 境外=%d"%(d['top_stock_universe']['a_stock_count'],
                                  d['top_stock_universe']['foreign_count']))
print("overall dist:", d['top1_weight_dist']['overall'])

cross = defaultdict(list)
for e in etfs:
    if e['top1_median_weight'] is None: continue
    cross[(e['track_tier'] or 'none', e['index_class'] or '其他')].append(e['top1_median_weight'])
print("\n-- tier x class top1 中位 --")
for (t,c),v in sorted(cross.items()):
    v=sorted(v); strong=sum(1 for x in v if x>5); weak=sum(1 for x in v if x<1)
    print("  %-8s x %-4s: n=%d median=%.2f >5=%d <1=%d"%(t,c,len(v),v[len(v)//2],strong,weak))

qc=[e['quarter_count'] for e in etfs]
buckets=Counter('<4' if q<4 else '4-7' if q<8 else '8-15' if q<16 else '16-23' if q<24 else '>=24' for q in qc)
print("\n-- ETF 季度数分布(新成立判断) --", dict(sorted(buckets.items())))

print("\n########## B. 龙头效应强弱 ##########")
weak=[]; mid=[]
for e in etfs:
    if e['top1_median_weight'] is None: continue
    w=e['top1_median_weight']
    if w<1: weak.append((e['index_key'],e['etf_name'],w,e['index_class']))
    elif w<5: mid.append((e['index_key'],e['etf_name'],w,e['index_class']))
print("TOP1<1%% 弱(数=%d):"%len(weak))
for x in sorted(weak,key=lambda z:z[2]): print("   ",x)
print("1-5%% 中(数=%d):"%len(mid))
for x in sorted(mid,key=lambda z:z[2]): print("   ",x)

classstats=defaultdict(list)
for e in etfs:
    wts=[t['weight'] for t in e['top1_weight_series'] if t.get('weight') is not None]
    if not wts: continue
    ratio=sum(1 for w in wts if w>5)/len(wts)
    classstats[e['index_class'] or '其他'].append(ratio)
print("\n-- 每类中位 TOP1>5%% 季度占比 --")
for c in sorted(classstats):
    v=sorted(classstats[c])
    print("  %s: n=%d 中位=%.0f%% 区间[%.0f%%,%.0f%%]"%(c,len(v),v[len(v)//2]*100,min(v)*100,max(v)*100))

print("\n########## C. stock_top_weights.db 数据可用性 ##########")
con=sqlite3.connect(DB); cur=con.cursor()
rows=cur.execute("SELECT code,MIN(date),MAX(date),COUNT(*),"
  "SUM(CASE WHEN date<'20200701' THEN 1 ELSE 0 END)"
  " FROM stock_top_daily GROUP BY code").fetchall()
y0c=Counter(r[1][:4] for r in rows)
nfull=sum(1 for r in rows if r[1][:4]<='2019' and r[3]>=1500)
nlate=sum(1 for r in rows if r[1][:4]>='2022')
print("起始年份:", dict(sorted(y0c.items())))
print("2019起全历史(起始2019且>=1500行): %d 只"%(nfull,))
print("2022后上市: %d 只"%(nlate,))
ns=sorted(r[3] for r in rows)
print("行数 p5/p50/p95: %.0f / %.0f / %.0f"%(ns[int(.05*len(ns))],ns[len(ns)//2],ns[int(.95*len(ns))]))
# 中间断档(有2019前段数据但中间整年缺)
gap=0; gap_rows=[]
for code,min_d,max_d,n,pre in rows:
    if not pre: continue
    yrs=set(r[0] for r in cur.execute("SELECT DISTINCT substr(date,1,4) FROM stock_top_daily WHERE code=?",(code,)))
    missing=[str(y) for y in range(2020,int(max_d[:4])+1) if str(y) not in yrs]
    if missing: gap+=1; gap_rows.append((code,min_d,max_d,missing))
print("中间年份整年断档股票数:", gap, gap_rows[:10])
# 未拉到最新(退市/合并)
stale=cur.execute("SELECT code,MAX(date) FROM stock_top_daily GROUP BY code HAVING MAX(date)<'20260801'").fetchall()
print("未更新到2026-08(真实退市/合并所致)股票:", stale)
ok192=sum(1 for c,m,d_,n_,p_ in rows if m<WINDOW_START)
print("2019-%s 起点已有数据: %d / %d = %.1f%%"%(WINDOW_START,ok192,len(rows),ok192/len(rows)*100))
con.close()

print("\n########## D. 映射链覆盖(sentiment.db 信号) ##########")
etf_by_idx={e['index_key']: e for e in etfs if e['index_key']}
con=sqlite3.connect(SENT); cur=con.cursor()
rows=cur.execute("SELECT date,index_id,signal FROM signal_daily "
                 "WHERE signal IN ('buy','buy_aux','buy_special','buy_backup') "
                 "AND date>=?",(WINDOW_START,)).fetchall()
covered=defaultdict(int); uncovered=defaultdict(int); covered_idx=set()
for dt,ix,sg in rows:
    if ix in etf_by_idx and etf_by_idx[ix]['quarter_count']>0:
        covered[ix]+=1; covered_idx.add(ix)
    else: uncovered[ix]+=1
print("2019Q2+ buy信号总数:", len(rows))
print("可映射个股(ETF有持仓)指数数=%d 信号数=%d"%(len(covered_idx),sum(covered.values())))
print("无个股映射指数数=%d 信号数=%d"%(len(uncovered),sum(uncovered.values())))
cbg=sum(v for k,v in uncovered.items() if k.startswith('cgb'))
foreign=sum(v for k,v in covered.items() if k in FOREIGN)
print("其中: 债类cgb信号=%d; 境外指数(需fallback)信号=%d"%(cbg,foreign))
byy=Counter(dt[:4] for dt,ix,sg in rows if ix in etf_by_idx and etf_by_idx[ix]['quarter_count']>0)
print("可映射信号按年:", dict(sorted(byy.items())))
con.close()
print("\n[DONE]")
