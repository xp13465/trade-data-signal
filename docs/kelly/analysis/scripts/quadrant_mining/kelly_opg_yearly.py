# -*- coding: utf-8 -*-
"""K2C5/K3/C1+C2+C5 剔除对可操作 G 的按年边际分解(v1.0.0 口径补测)
目的: 验证候选键在可操作 G(13万 P≤3d)下的边际是否稳定多年还是单年主导
口径: 可操作 G = 全信号 G 模式 过 AI宏4+3+1 + positionCap K1 每日池 + 13万 P3d b0 仿真;
      按年净利 = 仿真后 kept 交易按 buy_date 年聚合; 剔除边际 = 剔除后该年净利 - 基线该年净利
输入: static-site/data/signal_kelly_trades.json (2026-08-15 02:38 批)
依赖: kelly_opg_engine.py(OpgEngine/p3d_cap)
输出: 每年基线G净利 + 各候选剔除Δ
复现: python3 kelly_opg_yearly.py
"""
import sys, os
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kelly_opg_engine import OpgEngine, MODES, load_trades, AI_MACRO, p3d_cap

td = load_trades()
oeng = OpgEngine(td)
eng = oeng.eng


def g_yearly_profit(exclude_keys=None):
    rec = oeng._mode_recomputed('G', AI_MACRO, exclude_keys)
    kt, _ = p3d_cap(rec, 130000, 'b0')
    ymap = defaultdict(float)
    for k in kt:
        ymap[k['buy_date'][0:4]] += k['profit']
    return ymap


def excl_keys(pred):
    cache = {}
    ks = set()
    for mk in MODES:
        for t in eng._all_by_mode[mk]:
            if pred(oeng.attr_of(t, cache)): ks.add(eng.base_key(t))
    return ks


if __name__ == '__main__':
    base_y = g_yearly_profit()
    cands = [
        ('K2C5 港股追涨', excl_keys(lambda a: a['sig'] in ('buy_special', 'buy_backup') and a['mkt'] == 'hk')),
        ('K3 主关注×概念', excl_keys(lambda a: a['sig'] == 'buy' and a['mkt'] == 'concept')),
        ('C1+C2+C5', excl_keys(lambda a: (a['sig'] == 'buy' and a['mkt'] == 'concept') or (a['sig'] == 'buy_special' and a['mkt'] == 'hk') or (a['sig'] == 'buy_backup' and a['mkt'] == 'hk'))),
    ]
    print("=== 可操作 G 按年净利: 基线 vs 剔除后 Δ(v1.0.0, 13万 P3d b0) ===")
    years = sorted(base_y.keys())
    print(f"{'年':<5} {'基线G':>10} " + " ".join(f"{name.split()[0]:>10}" for name, _ in cands))
    for y in years:
        row = [f"{y:<5} {base_y[y]:>+10,.0f}"]
        for name, ks in cands:
            ymap = g_yearly_profit(ks)
            d = ymap.get(y, 0) - base_y.get(y, 0)
            row.append(f"{d:>+10,.0f}")
        print(" ".join(row))
    print(f"{'合计':<5} {sum(base_y.values()):>+10,.0f} " + " ".join(
        f"{sum(g_yearly_profit(ks).values()) - sum(base_y.values()):>+10,.0f}" for _, ks in cands))
