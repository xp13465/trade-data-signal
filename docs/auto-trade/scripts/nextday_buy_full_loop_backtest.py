#!/usr/bin/env python3
"""
次日买入执行策略 · 完整环路回测 —— 挂单策略 vs 开盘直接买, 用 A 模式第10交易日卖出价算总收益
口径:
  - 宇宙 = S06+K=1+A 模式 545 笔(signal_kelly_trades.json + kelly_posrating 同款过滤)
  - 每笔: signal_date 出信号 -> buy_date(T+1) 执行买入; 卖出 = A 模式(固定10交易日)卖出日 sell_date 收盘价
    (直接用回测产物 sell_price 复权价; 买入价在复权空间换算: 挂单价 = 昨收复权价*(1-d))
  - 买入复权换算: 回测 buy_price = accum_nav(信号日) * (次日open/信号日close)
    昨收复权价 = buy_price / gap_factor, 其中 gap_factor = 次日open原始价 / 信号日close复权价...
    简化近似: 真实买入折价比例直接应用到复权收益:
      S0 profit_baseline = profit(回测已算, 含费率)
      策略成交价相对 O 的折价率 r = (eff_px/O - 1); profit_strat = profit_baseline - 买入成本增加额
    买入成本增加 = buy_amount * r(折价率)  (1% 折价 ≈ 本金1%节省)
  - skip 口径: 未成交笔 profit=0(放弃); tail 口径: eff=C*(1+SLIP)
  - 对比指标: 总收益 / 投入总本金 / 每笔平均 / 总收益率 = 总收益/总投入; 相对 S0 增量
输出: stdout + json
复现: python3 docs/auto-trade/scripts/nextday_buy_full_loop_backtest.py
"""
import os, json, sqlite3
import sys
sys.path.insert(0, "/Users/linhuichen/code/trade/scripts")
import kelly_posrating as kp

DATA = "/Users/linhuichen/code/trade/static-site/data"
SLIP = 0.001

def build_kept(trades_doc, backtest_doc, s06_doc, feat_doc):
    fields = trades_doc["fields"]
    fIdx = {f: i for i, f in enumerate(fields)}
    quads = trades_doc["quadrants"]
    sell_modes = backtest_doc["config"]["sell_modes"]
    pos_raw = []
    for rk in ("rating_high", "rating_mid", "rating_low"):
        pos_raw += (quads.get(rk) or {}).get("A") or []
    trade_dims = kp._trade_dims(quads, fIdx)
    spec_map, feats = {}, {}
    for r in (feat_doc.get("meta") or {}).get("rules") or []:
        if isinstance(r, dict) and r.get("key"):
            spec_map[r["key"]] = r
    feats = feat_doc.get("features") or {}
    def feat_at(name, date):
        series = feats.get(name)
        if not series:
            return None
        return series.get(str(date))
    s06 = kp.S06Resolver(s06_doc)
    passes_fade = kp.make_passes_fade(fIdx, trade_dims, spec_map, feat_at, s06)
    base_pool = kp._collect_base_pool(quads, sell_modes, fIdx, passes_fade)
    kept = kp._position_cap_kept_keys(base_pool, fIdx, 1)
    out = []
    for tb in pos_raw:
        if not passes_fade(tb):
            continue
        if not kept.get(kp._base_key(tb, fIdx)):
            continue
        out.append(tb)
    return out, fIdx

def load_daily():
    con = sqlite3.connect("/Users/linhuichen/code/trade/data/etf_national_team.db")
    cur = con.cursor()
    m = {}
    for ec, dt, op, hi, lo, cl in cur.execute("SELECT etf_code, date, open, high, low, close FROM etf_daily ORDER BY etf_code, date"):
        m.setdefault(ec, []).append((dt, op, hi, lo, cl))
    con.close()
    return m

def main():
    trades_doc = json.load(open(os.path.join(DATA, "signal_kelly_trades.json")))
    backtest_doc = json.load(open(os.path.join(DATA, "signal_kelly_backtest.json")))
    s06_doc = json.load(open(os.path.join(DATA, "kelly_mode_s06_state.json")))
    feat_doc = json.load(open(os.path.join(DATA, "kelly_loss_features.json")))
    kept, fIdx = build_kept(trades_doc, backtest_doc, s06_doc, feat_doc)
    daily = load_daily()

    plans = []
    for tb in kept:
        ec = str(tb[fIdx["etf_code"]] or "")
        bd = str(tb[fIdx["buy_date"]] or "")
        rows = daily.get(ec) or []
        idx = next((i for i, r in enumerate(rows) if r[0] == bd), None)
        if idx is None or idx == 0:
            continue
        bd_row, pc_row = rows[idx], rows[idx - 1]
        O = bd_row[1]
        L = bd_row[3]  # low
        C = bd_row[4]
        PC = pc_row[4]
        if not (O and L and C and PC):
            continue
        profit_baseline = tb[fIdx["profit"]] or 0      # 回测 S0 profit(复权含费)
        sell_reason = str(tb[fIdx["sell_reason"]] or "")
        plans.append({"ec": ec, "bd": bd, "O": O, "L": L, "C": C, "PC": PC,
                      "profit0": profit_baseline, "hold": tb[fIdx["hold_days"]], "sell_reason": sell_reason})
    n = len(plans)
    print(f"完整环路计划: {n} 笔 (持有中笔数={sum(1 for p in plans if not p['sell_reason'] or p['sell_reason']=='持有中')})")

    # S0-baseline: 开盘价直接买, 545 笔全买
    s0_all = sum(p["profit0"] for p in plans)
    print(f"S0-baseline(开盘价直接买, 全买 {len(plans)} 笔) = {s0_all:+.0f} 元 (总投入 {len(plans)*10000:.0f} 元, 收益率 {s0_all/(len(plans)*10000)*100:+.2f}%)")
    print()
    DISCOUNTS = [0.0, 0.003, 0.005, 0.008, 0.010, 0.012, 0.015]
    print(f"{'折扣/昨收':>9} | {'口径':>6} | {'成/放弃/兜底':>14} | {'总收益':>12} | {'Σ投入':>10} | {'总收益率':>9} | {'每笔均值':>10}")
    print("-" * 95)
    res = {}
    for d in DISCOUNTS:
        for ma in ("skip", "tail"):
            tot_p = 0.0
            tot_inv = 0.0
            n_fill = n_skip = n_tail = 0
            for p in plans:
                P = p["PC"] * (1 - d)
                if p["O"] <= P:
                    r = 0.0            # 低开: 成交价=O, 与 S0 同
                    n_fill += 1
                elif p["L"] <= P:
                    r = P / p["O"] - 1  # 回落触及: 折价 P
                    n_fill += 1
                else:
                    if ma == "skip":
                        tot_inv += 0  # 不买, 投入 0, 收益 0
                        n_skip += 1
                        continue
                    else:
                        r = p["C"] * (1 + SLIP) / p["O"] - 1  # 尾盘兜底
                        n_tail += 1
                inv = 10000.0
                profit = p["profit0"] - inv * r   # S0 收益 - 买入价差(1万本金的折价/溢价值)
                tot_p += profit
                tot_inv += inv
            rate = tot_p / tot_inv * 100 if tot_inv else 0
            print(f"{(1-d)*100:>7.1f}% | {ma:>6} | {n_fill:>5}/{n_skip:>5}/{n_tail:>5} | {tot_p:>+11.0f} | {tot_inv:>9.0f} | {rate:>+8.2f}% | {tot_p/n:>+9.1f}")
            res.setdefault(d, {})[ma] = {"tot_profit": tot_p, "tot_inv": tot_inv, "rate": rate, "n_fill": n_fill, "n_skip": n_skip, "n_tail": n_tail}

    # S0 基准(挂昨收价限价) = d=0 档真值(⚠️ 2026-09-10 修复: 旧公式未成交仍计 profit0, 虚高; 现统一走循环口径)
    s0_skip, s0_tail = res.get(0.0, {}).get("skip", {}), res.get(0.0, {}).get("tail", {})
    print(f"S0-挂昨收价限价+skip(真放弃): {s0_skip.get('tot_profit', 0):+.0f} 元 (成交 {s0_skip.get('n_fill', 0)}/放弃 {s0_skip.get('n_skip', 0)})")
    print(f"S0-挂昨收价限价+tail(尾盘兜底): {s0_tail.get('tot_profit', 0):+.0f} 元 (成交 {s0_tail.get('n_fill', 0)}/兜底 {s0_tail.get('n_tail', 0)})")

    json.dump({"n": n, "res": res}, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "nextday_buy_full_loop.json"), "w"), ensure_ascii=False, indent=1)
    print("已输出 nextday_buy_full_loop.json")

main()
