#!/usr/bin/env python3
"""「竞价仓/挂昨收仓」混合比例全表复现(2026-09-22 双口径需求配套, 报告 nextday-buy-mix-table-20260922.md)

口径 = 与 nextday_buy_split_backtest.py 同构(切片复用, 只改输出段):
  - 宇宙 = S06 动态 + K=1 + A 模式(同一 build_kept 逻辑, 546 笔 -> ops 可测 545 笔)
  - 实操口径(exec=real_buy_date, PC=信号日收盘, 无前视)
  - 每笔资金 INV=1万: b 比例走「竞价仓」(9:15-9:25 挂高价限价单吃开盘价, 效果=开盘直买, 545 笔全成交)
    其余 1-b 走「挂昨收+尾盘兜底」(现状默认档, 343 open + 129 limit + 73 tail)
  - profit_mix = profit0 - (1-b) × INV × r, r = 挂昨收相对开盘价的成本(open=0, limit=P/O-1, tail=C×(1+SLIP)/O-1)
    r 与 b 无关 -> 混合收益对 b 完全线性(端点 S0=+156,794 / 全挂昨收=+154,540, 斜率 +22.54 元/1%)

同构对账(§5.4⑦): b=1.0 与 b=0 端点必须逐位等于 nextday_buy_split.json 的 156,793.7054 / 154,540, 漂移即 FAIL。
输入: static-site/data/signal_kelly_trades.json / signal_kelly_backtest.json / kelly_mode_s06_state.json /
       kelly_loss_features.json + data/etf_national_team.db(etf_daily)
输出: stdout + nextday_buy_mix.json(混合比例逐 10% 全表 + 逐类分解)
复现: python3 docs/auto-trade/scripts/nextday_buy_mix_table.py
"""
import os, json, sqlite3, sys
sys.path.insert(0, "/Users/linhuichen/code/trade/scripts")
import kelly_posrating as kp

DATA = "/Users/linhuichen/code/trade/static-site/data"
DB = "/Users/linhuichen/code/trade/data/etf_national_team.db"
SLIP = 0.001
INV = 10000.0
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nextday_buy_mix.json")

# ---- 以下三段与 nextday_buy_split_backtest.py 逐字同构(build_kept/build_plans/fill_tier) ----
def build_kept(trades_doc, backtest_doc, s06_doc, feat_doc):
    fields = trades_doc["fields"]; fIdx = {f: i for i, f in enumerate(fields)}
    quads = trades_doc["quadrants"]; sell_modes = backtest_doc["config"]["sell_modes"]
    pos_raw = []
    for rk in ("rating_high", "rating_mid", "rating_low"):
        pos_raw += (quads.get(rk) or {}).get("A") or []
    trade_dims = kp._trade_dims(quads, fIdx)
    spec_map = {}
    for r in (feat_doc.get("meta") or {}).get("rules") or []:
        if isinstance(r, dict) and r.get("key"): spec_map[r["key"]] = r
    feats = feat_doc.get("features") or {}
    def feat_at(name, date):
        s = feats.get(name); return s.get(str(date)) if s else None
    s06 = kp.S06Resolver(s06_doc)
    pf = kp.make_passes_fade(fIdx, trade_dims, spec_map, feat_at, s06)
    bp = kp._collect_base_pool(quads, sell_modes, fIdx, pf)
    kept = kp._position_cap_kept_keys(bp, fIdx, 1)
    return [tb for tb in pos_raw if pf(tb) and kept.get(kp._base_key(tb, fIdx))], fIdx

def load_daily():
    con = sqlite3.connect(DB); cur = con.cursor()
    m = {}; cal = set()
    for ec, dt, op, hi, lo, cl in cur.execute("SELECT etf_code,date,open,high,low,close FROM etf_daily ORDER BY etf_code,date"):
        m.setdefault(ec, []).append((dt, op, hi, lo, cl)); cal.add(dt)
    con.close(); return m, sorted(cal)

def build_plans(kept, fIdx, daily, caliber):
    plans = []
    for tb in kept:
        ec = str(tb[fIdx["etf_code"]] or "")
        if caliber == "ops":
            ed = str(tb[fIdx["real_buy_date"]] or "")
        else:
            ed = str(tb[fIdx["buy_date"]] or "")
        rows = daily.get(ec) or []
        ri = next((i for i, r in enumerate(rows) if r[0] == ed), None)
        if ri is None or ri == 0: continue
        O, L, C = rows[ri][1], rows[ri][3], rows[ri][4]
        PC = rows[ri - 1][4]
        if not (O and L and C and PC): continue
        plans.append({"ec": ec, "bd": ed, "sdate": str(tb[fIdx["sell_date"]] or ""),
                      "profit0": tb[fIdx["profit"]] or 0, "O": O, "L": L, "C": C, "PC": PC})
    return plans

def fill_tier(p, d, mode):
    """返回 (r, st): r=相对开盘价成本(正=贵), st=成交类别"""
    P = p["PC"] * (1 - d)
    if p["O"] <= P: return 0.0, "open"
    if p["L"] <= P: return P / p["O"] - 1.0, "limit"
    if mode == "tail": return p["C"] * (1 + SLIP) / p["O"] - 1.0, "tail"
    return None, "skip"
# ---- 同构段结束 ----

def main():
    trades_doc = json.load(open(os.path.join(DATA, "signal_kelly_trades.json")))
    backtest_doc = json.load(open(os.path.join(DATA, "signal_kelly_backtest.json")))
    s06_doc = json.load(open(os.path.join(DATA, "kelly_mode_s06_state.json")))
    feat_doc = json.load(open(os.path.join(DATA, "kelly_loss_features.json")))
    daily, calendar = load_daily()
    kept, fIdx = build_kept(trades_doc, backtest_doc, s06_doc, feat_doc)
    plans = build_plans(kept, fIdx, daily, "ops")
    print(f"kept 宇宙: {len(kept)} 笔 | ops 可测: {len(plans)} 笔")

    # 逐类分解(全挂昨收, b=0): 每笔 diff = -INV×r
    cls = {"open": 0.0, "limit": 0.0, "tail": 0.0}
    cls_n = {"open": 0, "limit": 0, "tail": 0}
    for p in plans:
        r, st = fill_tier(p, 0.0, "tail")
        cls[st] += -INV * r if r is not None else 0.0
        cls_n[st] += 1
    print("\n逐类分解(挂昨收相对开盘直买差):")
    for st in ("open", "limit", "tail"):
        print(f"  {st:<6} n={cls_n[st]:>3}  合计 {cls[st]:>+10,.0f} 元")

    tot_s0 = sum(p["profit0"] for p in plans)
    tot_lim = tot_s0 + sum(cls.values())
    assert abs(tot_s0 - 156793.7054) < 0.1, f"S0 端点对账 FAIL: {tot_s0}"
    assert abs(tot_lim - 154540.0) < 1.0, f"挂昨收端点对账 FAIL: {tot_lim}"
    print(f"同构对账: S0 端点(b=100%) {tot_s0:>+10,.0f} = nextday_buy_split.json 156,794 ✓ | 挂昨收端点(b=0%) {tot_lim:>+10,.0f} = 154,540 ✓")

    # 混合比例全表(竞价仓 0%→100% 逐 10%)
    print("\n混合比例全表(竞价仓 b% / 挂昨收仓 (1-b)%):")
    rows = []
    peak_cash = 90000.0  # 两端点产物 peak_cash 均为 9.0 万(9 笔峰值), 混合内每笔仍 1 万同一标的, 峰值不变
    for b in [x / 10.0 for x in range(0, 11)]:
        tot = tot_s0 * b + tot_lim * (1 - b)
        ret = tot / peak_cash * 100.0
        rows.append({"b_quoted": round(b, 1), "b_plan": round(1 - b, 1),
                     "tot_profit": round(tot, 2), "ret_max_hold_pct": round(ret, 4)})
        print(f"  竞价 {b*100:>3.0f}% / 挂昨收 {(1-b)*100:>3.0f}% | 总净盈亏 {tot:>+10,.0f} | 峰值资金收益率 {ret:>+8.2f}%")

    slope = tot_s0 - tot_lim
    print(f"\n线性结论: 竞价仓每多 1% ≈ {slope/100:+.2f} 元/十年(斜率恒定, 因 r 与 b 无关)")

    json.dump({"n_ops": len(plans), "decomp": {st: {"n": cls_n[st], "sum_yuan": round(cls[st], 2)} for st in cls},
               "slope_per_1pct": round(slope / 100, 4), "mix_table": rows,
               "note": "b_quoted=竞价仓(挂高价限价单吃开盘价)比例, b_plan=挂昨收+尾盘兜底比例; 口径=S06+K=1+A ops(exec=real_buy_date)"},
              open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"\n已输出 {OUT}")

main()
