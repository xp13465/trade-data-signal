# ============================================================
# 用途: 3pp 组合分类分析(对照 classify_kelly_3pp.js)
# 日期/来源: 2026-08-13 / tmp
# 结论: 3pp 组合分类结果, 与 JS 版互为验证
# 依赖: 无
# 输入/输出: 读 /tmp/kelly_trades_dc59898.json(基笔), 输出 3pp 分类
# 复现: python3 analyze_kelly_3pp.py
# 注意: 原文件硬编码读 /tmp/kelly_trades_dc59898.json, 如需重跑需准备该文件
# ============================================================
import json, sys

FIELDS = ['signal_date','index_id','signal','buy_date','sell_date','etf_code','etf_name','track_tier','track_score','match_method','track_low_confidence','buy_price','sell_price','shares','profit','return_pct','hold_days','sell_reason','current_price','market_state','rating']

def load(path):
    with open(path) as f:
        d = json.load(f)
    q = d['quadrants']
    # sell mode 'A' across rating_high/mid/low
    trades = []
    for rk in ['rating_high','rating_mid','rating_low']:
        for t in q[rk].get('A', []):
            if len(t) < len(FIELDS):
                continue
            rec = {FIELDS[i]: t[i] for i in range(len(FIELDS))}
            trades.append(rec)
    return d, trades

d_old, t_old = load('/tmp/kelly_trades_dc59898.json')
d_new, t_new = load('static-site/data/signal_kelly_trades.json')
print(f"OLD: A-mode raw trades (pre-hit-filter) = {len(t_old)}")
print(f"NEW: A-mode raw trades (pre-hit-filter) = {len(t_new)}")
print(f"OLD generated_at={d_old['generated_at']}  NEW generated_at={d_new['generated_at']}")

# sanity: unique keys
def bkey(t): return f"{t['signal_date']}|{t['index_id']}|{t['signal']}|{t['buy_date']}|{t['etf_code']}"
s_old={bkey(t) for t in t_old}
s_new={bkey(t) for t in t_new}
print(f"OLD unique bkeys={len(s_old)}  NEW unique bkeys={len(s_new)}")
print(f"交集 bkeys={len(s_old & s_new)}  仅旧={len(s_old-s_new)}  仅新={len(s_new-s_old)}")

# Dump sample to verify structure
print("\n--- OLD sample trade ---")
print(json.dumps(t_old[0], ensure_ascii=False))
