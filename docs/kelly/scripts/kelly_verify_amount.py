# ============================================================
# 用途: 金额口径另一验证(对照 amount_verify.js): 按前端 lab.js 逻辑复算每日池等分金额, 验证「当日信号数<K」时分配
# 日期/来源: 2026-08-14 / tmp
# 结论: 与 amount_verify.js 结论一致: 当日保留数不足 K 时每笔金额放大(=buyAmount/当日保留数)
# 依赖: 无(纯读 JSON 复算)
# 输入/输出: 读 static-site/data/signal_kelly_trades.json, 输出分仓金额分布
# 复现: python3 kelly_verify_amount.py
# 注意: 原文件用相对路径读 static-site/data, 需在仓库根运行
# ============================================================
# -*- coding: utf-8 -*-
"""按前端 lab.js 逻辑复算每日池等分金额, 验证「当日信号数<K」时的分配"""
import json, collections

td = json.load(open('static-site/data/signal_kelly_trades.json'))
q = td['quadrants']
F = td['fields']
def idx(f): return F.index(f)
I = {f: idx(f) for f in F}
BUY = td.get('buy_amount') or 10000

RATING_RANK = {'high':0,'mid':1,'low':2,'':3}
SIG_RANK = {'buy_backup':0,'buy':1,'buy_aux':2,'buy_special':3,'':9}

def base_key(t):
    return '|'.join([str(t[I['signal_date']]), str(t[I['index_id']]), str(t[I['signal']]),
                     str(t[I['buy_date']]), str(t[I['etf_code']])])

# 基笔池: 跨 rating 三分区 × 全卖出模式, baseKey 去重 (无 toggle 过滤版)
pool, seen = [], set()
for rk in ['rating_high','rating_mid','rating_low']:
    for mk, arr in q.get(rk, {}).items():
        for t in arr:
            bk = base_key(t)
            if bk not in seen:
                seen.add(bk); pool.append(t)

by_date = collections.defaultdict(list)
for t in pool:
    by_date[str(t[I['signal_date']])].append(t)

def sort_key(t):
    ts = t[I['track_score']] if I['track_score'] is not None else -1
    ts = float(ts) if ts not in (None,'') else -1
    ra = RATING_RANK.get(str(t[I['rating']] or ''), 3)
    sg = SIG_RANK.get(str(t[I['signal']] or ''), 9)
    bd = str(t[I['buy_date']] or '')
    return (-ts, ra, sg, bd)

K = 3
kept_by_day = {}
for sd, rows in by_date.items():
    rows_sorted = sorted(rows, key=sort_key)
    n = min(K, len(rows_sorted))
    kept_by_day[sd] = len(rows_sorted[:n])

# 每笔金额
def per_amount(sd):
    n = kept_by_day.get(sd, 0)
    return BUY/n if n>0 else BUY

# 统计「当日保留数」分布
dist = collections.Counter(kept_by_day.values())
print('== 当日保留基笔数分布(全历史, K=3, 无过滤) ==')
for c in sorted(dist): print(f'  当日保留 {c} 个: {dist[c]} 天')

# 持仓中(未卖出)的 trades 金额验证
holding = []
for sd, rows in by_date.items():
    kept = sorted(rows, key=sort_key)[:min(K, len(rows))]
    amt = per_amount(sd)
    for t in kept:
        if not str(t[I['sell_date']] or ''):
            holding.append((sd, amt, base_key(t)))

print()
print('== 持仓中 trades(未卖出) 笔数与金额(前10) ==')
for sd, amt, bk in holding[:10]:
    print(f'   {sd} 保留{kept_by_day[sd]}个 每笔={amt:.4f}')
print(f'   持仓中总笔数: {len(holding)}')
print(f'   持仓中金额分布: {collections.Counter(round(a,2) for _,a,_ in holding)}')

# 用户报的场景: 1笔/3333.3333, 2笔/6666.6666 —— 即持仓中1笔3333.3333 或 2笔各3333.3333
print()
print('== 直接验证用户看到的数值 ==')
cnt_3333 = sum(1 for _,a,_ in holding if abs(a-3333.3333)<0.01)
cnt_10000 = sum(1 for _,a,_ in holding if abs(a-10000)<0.01)
cnt_5000 = sum(1 for _,a,_ in holding if abs(a-5000)<0.01)
print(f'   持仓中 每笔=3333.3333(当日3信号): {cnt_3333} 笔')
print(f'   持仓中 每笔=10000(当日1信号凑满): {cnt_10000} 笔')
print(f'   持仓中 每笔=5000(当日2信号): {cnt_5000} 笔')

# 举一个「当日只1个信号」的具体例子
one_signal_days = [sd for sd,n in kept_by_day.items() if n==1]
print()
print(f'== 当日只保留1个信号的日期示例: {one_signal_days[:5]} ==')
for sd in one_signal_days[:3]:
    rows = by_date[sd]
    print(f'   {sd}: 原始信号数={len(rows)}, 保留1个, 每笔={per_amount(sd):.2f} (凑满1W)')
