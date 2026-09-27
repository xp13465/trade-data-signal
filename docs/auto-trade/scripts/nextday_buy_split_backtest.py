#!/usr/bin/env python3
"""次日买入挂单策略穷举回测: 开盘直买 vs 昨收价挂单 vs 拆分挂单组合(用户 2026-09-22 需求)
口径(实操无前视, 与 nextday_plan 一致):
  - 宇宙 = S06 动态 + K=1 + A 模式(实操计划同款 build_kept, 与 nextday_gap_maxhold_backtest.py 同源)
  - 信号日 T 收盘后信号固化 -> 执行日 E = real_buy_date(T+1)
  - PC(昨收) = E 前一交易日收盘 = 信号日收盘(无前视)
  - 每笔金额 INV=1万, 策略 = [(w_i, d_i)], sum w=1, 挂单价 P_i = PC*(1-d_i)
  - 每档独立判定(标准集合竞价+盘中限价单规则):
      O <= P_i   -> 低开, 集合竞价按 O 成交(r=0, 与 S0 同)
      L <= P_i   -> 盘中触及, 按 P_i 成交(r = P_i/O - 1)
      否则        -> tail: 尾盘 C*(1+SLIP) 兜底(r = C*(1+SLIP)/O - 1) / skip: 该档放弃(不投不占资金)
  - profit = profit0 - INV * sum(w_i * r_i)(profit0 = 次日开盘买入复权收益, 与既有脚本同款修正)
  - 资金占用: 成交档 buy_date+金额, sell_date-金额(A 模式第10交易日, 持有中按数据末日回收)
对照口径(legacy, 20260910 报告同款): exec_date = 信号日当天, PC = 信号日前一交易日收盘(前视, 仅作历史对照)
输入: static-site/data/signal_kelly_trades.json / signal_kelly_backtest.json / kelly_mode_s06_state.json /
       kelly_loss_features.json + data/etf_national_team.db(etf_daily)
输出: stdout + nextday_buy_split.json; 报告 docs/auto-trade/nextday-buy-split-backtest-20260922.md
复现: python3 docs/auto-trade/scripts/nextday_buy_split_backtest.py
"""
import os, json, sqlite3, sys
sys.path.insert(0, "/Users/linhuichen/code/trade/scripts")
import kelly_posrating as kp

DATA = "/Users/linhuichen/code/trade/static-site/data"
DB = "/Users/linhuichen/code/trade/data/etf_national_team.db"
SLIP = 0.001
INV = 10000.0
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nextday_buy_split.json")

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
    """caliber='ops' 实操口径(exec=real_buy_date, PC=信号日收盘, 无前视)
       caliber='legacy' 旧基线口径(exec=信号日, PC=信号日前一交易日, 前视对照)"""
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
    P = p["PC"] * (1 - d)
    if p["O"] <= P: return 0.0, "open"
    if p["L"] <= P: return P / p["O"] - 1.0, "limit"
    if mode == "tail": return p["C"] * (1 + SLIP) / p["O"] - 1.0, "tail"
    return None, "skip"

def simulate(plans, tiers, mode):
    per_trade = []
    for p in plans:
        if mode == "all":
            per_trade.append({"profit": p["profit0"], "inv": INV, "bd": p["bd"], "sdate": p["sdate"],
                              "st": ["open"] * len(tiers)})
            continue
        profit = 0.0; inv_used = 0.0; st_by_tier = []
        for w, d in tiers:
            r, st = fill_tier(p, d, mode)
            st_by_tier.append(st)
            if st == "skip": continue
            profit += p["profit0"] * w - INV * w * r
            inv_used += INV * w
        per_trade.append({"profit": profit, "inv": inv_used, "bd": p["bd"], "sdate": p["sdate"], "st": st_by_tier})
    tot = {"tot_profit": sum(x["profit"] for x in per_trade),
           "tot_inv": sum(x["inv"] for x in per_trade), "n_trades": len(per_trade)}
    return per_trade, tot

def sdate_of(p, cutoff):
    return p["sdate"] or cutoff

def max_holding_stats(per_trade, cutoff, calendar):
    delta = {}; cnt = {}
    for x in per_trade:
        if x["inv"] == 0: continue
        sd = sdate_of(x, cutoff)
        delta[x["bd"]] = delta.get(x["bd"], 0.0) + x["inv"]
        cnt[x["bd"]] = cnt.get(x["bd"], 0) + 1
        if sd and sd > x["bd"]:
            delta[sd] = delta.get(sd, 0.0) - x["inv"]; cnt[sd] = cnt.get(sd, 0) - 1
    cal = [c for c in calendar if c >= min(delta.keys()) and c <= cutoff]
    cur = cur_n = 0.0; peak = peak_n = 0.0; cum = 0.0; n_days = 0
    for dt in cal:
        cur += delta.get(dt, 0.0); cur_n += cnt.get(dt, 0)
        if cur < 1e-9: cur = 0.0
        if cur_n < 0: cur_n = 0
        cum += cur; n_days += 1
        if cur > peak: peak = cur
        if cur_n > peak_n: peak_n = cur_n
    return {"peak_cash": peak, "peak_n": peak_n, "avg_pos": cum / n_days if n_days else 0.0, "days": n_days}

def max_drawdown(per_trade, cutoff, calendar):
    """已实现收益曲线最大回撤: 卖出日结算, 峰值→谷值"""
    delta = {}
    for x in per_trade:
        sd = sdate_of(x, cutoff)
        if sd <= x["bd"]: sd = cutoff
        delta[sd] = delta.get(sd, 0.0) + x["profit"]
    cur = peak = mdd = 0.0
    for d in calendar:
        if d not in delta: continue
        cur += delta[d]
        if cur > peak: peak = cur
        if peak - cur > mdd: mdd = peak - cur
    return mdd, peak

def yearly_stats(per_trade):
    ys = {}
    for x in per_trade:
        y = x["bd"][:4]
        ys.setdefault(y, {"n": 0, "profit": 0.0})
        ys[y]["n"] += 1; ys[y]["profit"] += x["profit"]
    return ys

def tier_tally(per_trade, ntiers):
    tally = [{} for _ in range(ntiers)]
    for x in per_trade:
        for i, st in enumerate(x["st"]):
            tally[i][st] = tally[i].get(st, 0) + 1
    return tally

def main():
    trades_doc = json.load(open(os.path.join(DATA, "signal_kelly_trades.json")))
    backtest_doc = json.load(open(os.path.join(DATA, "signal_kelly_backtest.json")))
    s06_doc = json.load(open(os.path.join(DATA, "kelly_mode_s06_state.json")))
    feat_doc = json.load(open(os.path.join(DATA, "kelly_loss_features.json")))
    daily, calendar = load_daily()
    kept, fIdx = build_kept(trades_doc, backtest_doc, s06_doc, feat_doc)

    print(f"kept 宇宙: {len(kept)} 笔 (S06+K=1+A)")
    plans_ops = build_plans(kept, fIdx, daily, "ops")
    plans_leg = build_plans(kept, fIdx, daily, "legacy")
    print(f"ops(实操, exec=real_buy_date) 可测: {len(plans_ops)} 笔 / legacy(旧, 信号日当天) 可测: {len(plans_leg)} 笔")
    cutoff_ops = max(p["bd"] for p in plans_ops)

    STRATS = [
        ("S0 开盘直买",            [(1.0, 0.0)], "all"),
        ("单档 昨收 100%",         [(1.0, 0.0)], "tail"),
        ("单档 昨收 100% skip",    [(1.0, 0.0)], "skip"),
        ("单档 -0.3% 100%",        [(1.0, 0.003)], "tail"),
        ("单档 -0.3% 100% skip",   [(1.0, 0.003)], "skip"),
        ("单档 -0.5% 100%",        [(1.0, 0.005)], "tail"),
        ("单档 -0.5% 100% skip",   [(1.0, 0.005)], "skip"),
        ("单档 -0.8% 100%",        [(1.0, 0.008)], "tail"),
        ("单档 -0.8% 100% skip",   [(1.0, 0.008)], "skip"),
        ("单档 -1.0% 100%",        [(1.0, 0.01)], "tail"),
        ("单档 -1.0% 100% skip",   [(1.0, 0.01)], "skip"),
        ("拆2 昨收1/2+-0.5%1/2",   [(0.5, 0.0), (0.5, 0.005)], "tail"),
        ("拆2 昨收1/2+-0.5%1/2sk", [(0.5, 0.0), (0.5, 0.005)], "skip"),
        ("拆2 昨收1/2+-1.0%1/2",   [(0.5, 0.0), (0.5, 0.01)], "tail"),
        ("拆2 昨收1/2+-1.0%1/2sk", [(0.5, 0.0), (0.5, 0.01)], "skip"),
        ("拆2 昨收0.6+-0.5%0.4",   [(0.6, 0.0), (0.4, 0.005)], "tail"),
        ("拆2 昨收0.4+-0.5%0.6",   [(0.4, 0.0), (0.6, 0.005)], "tail"),
        ("拆2 昨收0.5+-0.8%0.5",   [(0.5, 0.0), (0.5, 0.008)], "tail"),
        ("拆2 -0.5%1/2+-1.0%1/2",  [(0.5, 0.005), (0.5, 0.01)], "tail"),
        ("拆3 昨1/3+-0.5%1/3+-1%1/3", [(1/3, 0.0), (1/3, 0.005), (1/3, 0.01)], "tail"),
        ("拆3 昨1/3+-0.5%1/3+-1%1/3sk",[(1/3, 0.0), (1/3, 0.005), (1/3, 0.01)], "skip"),
        ("拆3 昨0.5+-0.5%0.3+-1%0.2", [(0.5, 0.0), (0.3, 0.005), (0.2, 0.01)], "tail"),
        ("拆3 昨0.2+-0.5%0.3+-1%0.5", [(0.2, 0.0), (0.3, 0.005), (0.5, 0.01)], "tail"),
        ("拆3 昨1/3+-0.3%1/3+-0.8%1/3", [(1/3, 0.0), (1/3, 0.003), (1/3, 0.008)], "tail"),
        ("拆3 -0.3%1/3+-0.5%1/3+-1%1/3", [(1/3, 0.003), (1/3, 0.005), (1/3, 0.01)], "tail"),
        ("拆4 昨1/4+-0.3%1/4+-0.5%1/4+-1%1/4", [(0.25,0.0),(0.25,0.003),(0.25,0.005),(0.25,0.01)], "tail"),
    ]

    print("\n================ 实操口径(exec=real_buy_date, 无前视) ================")
    print(f"{'策略':<30}{'总收益':>11}{'Σ投入':>10}{'峰值':>8}{'return_max':>10}{'闲置率':>8}{'最大回撤':>9}{'回撤/峰值':>9}  档位成交(O/L/T/S)")
    rows = []
    for name, tiers, mode in STRATS:
        per_trade, tot = simulate(plans_ops, tiers, mode)
        mh = max_holding_stats(per_trade, cutoff_ops, calendar)
        rat = tot["tot_profit"] / mh["peak_cash"] * 100 if mh["peak_cash"] else 0
        idle = 1 - tot["tot_inv"] / (tot["n_trades"] * INV)
        mdd, peak = max_drawdown(per_trade, cutoff_ops, calendar)
        tally = tier_tally(per_trade, len(tiers))
        rows.append({"name": name, "tiers": [list(x) for x in tiers], "mode": mode,
                     "tot_profit": tot["tot_profit"], "tot_inv": tot["tot_inv"],
                     "peak_cash": mh["peak_cash"], "peak_n": mh["peak_n"],
                     "avg_pos": mh["avg_pos"], "ret_max_hold": rat, "idle_rate": idle,
                     "mdd": mdd, "peak": peak, "tier_tally": tally})
        tstr = " | ".join(str(t) for t in tally)
        print(f"{name:<30}{tot['tot_profit']:>+11,.0f}{tot['tot_inv']/10000:>9,.1f}万{mh['peak_cash']/10000:>7,.1f}万{rat:>+9.2f}%{idle*100:>7.1f}%{mdd:>+9,.0f}{mdd/peak*100 if peak else 0:>8.1f}%  {tstr}")

    # 按年分解
    print("\n--- 按年分解(实操口径, S0 vs 主要策略) ---")
    anchor_names = ["S0 开盘直买", "单档 昨收 100%", "单档 -0.5% 100%", "拆2 昨收1/2+-0.5%1/2", "拆3 昨1/3+-0.5%1/3+-1%1/3"]
    anchor = {nm: None for nm in anchor_names}
    for nm in anchor:
        for r in rows:
            if r["name"] == nm:
                per_trade, _ = simulate(plans_ops, r["tiers"], r["mode"])
                anchor[nm] = yearly_stats(per_trade)
    years = sorted(set().union(*[set(v.keys()) for v in anchor.values() if v]))
    print(f"{'年':<6}" + "".join(f"{nm[:9]:>13}" for nm in anchor_names))
    for y in years:
        line = f"{y:<6}"
        for nm in anchor_names:
            ys = anchor[nm]
            line += f"{ys[y]['profit'] if y in ys else 0:>+11,.0f}" + f"/{ys[y]['n'] if y in ys else 0}" + " " * (2 if len(f"{ys[y]['profit'] if y in ys else 0:+.0f}")<10 else 0)
        print(line)

    # 极端窗口
    print("\n--- 极端窗口专项(S0 vs 拆3 昨1/3-0.5%-1%, 按 exec 日区间) ---")
    win_map = {"2015H2": ("20150701", "20151231"), "2018": ("20180101", "20181231"),
               "2022": ("20220101", "20221231"), "2024Q1": ("20240101", "20240331"),
               "2026近3月": ("20260601", "20261231")}
    for wname, (lo, hi) in win_map.items():
        s0 = s3 = 0.0; nw = 0
        for p in plans_ops:
            if not (lo <= p["bd"] <= hi): continue
            nw += 1; s0 += p["profit0"]
            pr, _ = simulate([p], [(1/3, 0.0), (1/3, 0.005), (1/3, 0.01)], "tail")
            s3 += pr[0]["profit"]
        print(f"{wname:<10} n={nw:<3} S0 {s0:>+9,.0f} | 拆3 {s3:>+9,.0f} | diff {s3 - s0:>+8,.0f}")

    # 分半稳定性
    print("\n--- 分半稳定性(按 exec 日时间中点切, S0 vs 拆3) ---")
    half = sorted(plans_ops, key=lambda p: p["bd"])
    mid = half[len(half) // 2]["bd"]
    h1 = [p for p in half if p["bd"] <= mid]; h2 = [p for p in half if p["bd"] > mid]
    for nm, tiers, mode in [("S0", [(1.0,0.0)], "all"), ("拆3", [(1/3,0.0),(1/3,0.005),(1/3,0.01)], "tail")]:
        _, t1 = simulate(h1, tiers, mode); _, t2 = simulate(h2, tiers, mode)
        print(f"{nm:<6} 前半({len(h1)}笔) {t1['tot_profit']:>+9,.0f} | 后半({len(h2)}笔) {t2['tot_profit']:>+9,.0f}")

    # 对照 legacy
    print("\n================ 对照口径(legacy 信号日当天, 20260910 报告同款, 前视) ================")
    for name, tiers, mode in [("S0 开盘直买", [(1.0, 0.0)], "all"),
                              ("单档 昨收 100%", [(1.0, 0.0)], "tail"),
                              ("单档 昨收 100% skip", [(1.0, 0.0)], "skip")]:
        per_trade, tot = simulate(plans_leg, tiers, mode)
        print(f"{name:<26} 总收益 {tot['tot_profit']:>+10,.0f} ({len(per_trade)}笔)")

    json.dump({"kept": len(kept), "n_ops": len(plans_ops), "n_leg": len(plans_leg),
               "scenarios_ops": rows}, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"\n已输出 {OUT}")

main()
