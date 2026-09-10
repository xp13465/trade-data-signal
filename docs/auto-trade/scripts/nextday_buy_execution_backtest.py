#!/usr/bin/env python3
"""
次日买入执行策略回测 v2 —— S06+K=1+A 模式交易重放, 模拟各挂单档位(基准=昨收), 求 E[综合买入价 vs 开盘价]
目的: 验证「次日挂昨收X%折扣限价」vs「开盘直接买」的期望收益, 选最优档位(§5.1 用户假设数据验证)
口径:
  - 回测宇宙 = signal_kelly_trades.json + kelly_posrating 同款过滤(S06 动态 + loss键 + A模式 + K=1 top1)
  - 每笔: signal_date 出信号, buy_date(=T+1) 执行; 昨收 = buy_date 前 1 交易日 close(etf_daily)
  - 挂单价 P = 昨收 * (1 - d); 成交判定与成交价:
      O <= P (低开/平开)  -> 集合竞价即成交, 成交价 = O (实际比挂单价更好)
      O >  P (高开) 且 L <= P -> 回落触及挂价, 成交价 = P
      O >  P 且 L >  P -> 未成交; miss_action: 尾盘兜底 C*(1+SLIP) 或 放弃(计 0 折价, 即不买)
  - 指标: 成交率(含低开自动成交) / 成交折价均值(vs O) / E[折价%] = 全笔(执行价/O - 1)均值
          E 越负越好(买得比开盘便宜); 相对 S0(0%) 差 * 每万 = 收益影响元
输出: stdout 表格 + nextday_buy_exec.json
复现: python3 docs/auto-trade/scripts/nextday_buy_execution_backtest.py
"""
import os, json, sqlite3
from datetime import datetime

DATA = "/Users/linhuichen/code/trade/static-site/data"
syspath = "/Users/linhuichen/code/trade/scripts"
import sys
sys.path.insert(0, syspath)
import kelly_posrating as kp

SLIP = 0.001

def load_trades():
    with open(os.path.join(DATA, "signal_kelly_trades.json")) as f:
        return json.load(f)

def build_kept_trades(trades_doc, backtest_doc, s06_doc, feat_doc):
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
    cur.execute("SELECT etf_code, date, open, high, low, close FROM etf_daily ORDER BY etf_code, date")
    m = {}
    for ec, dt, op, hi, lo, cl in cur.fetchall():
        m.setdefault(ec, []).append((dt, op, hi, lo, cl))
    con.close()
    return m

def main():
    print("== 加载回测宇宙(S06+K=1+A 模式) ==")
    trades_doc = load_trades()
    with open(os.path.join(DATA, "signal_kelly_backtest.json")) as f:
        backtest_doc = json.load(f)
    with open(os.path.join(DATA, "kelly_mode_s06_state.json")) as f:
        s06_doc = json.load(f)
    with open(os.path.join(DATA, "kelly_loss_features.json")) as f:
        feat_doc = json.load(f)
    kept, fIdx = build_kept_trades(trades_doc, backtest_doc, s06_doc, feat_doc)
    print(f"K=1 保留交易: {len(kept)} 笔")
    daily = load_daily()

    plans = []
    miss = 0
    for tb in kept:
        ec = str(tb[fIdx["etf_code"]] or "")
        bd = str(tb[fIdx["buy_date"]] or "")
        rows = daily.get(ec) or []
        idx = None
        for i, r in enumerate(rows):
            if r[0] == bd:
                idx = i
                break
        if idx is None or idx == 0:
            miss += 1
            continue
        bd_row = rows[idx]
        pc_row = rows[idx - 1]
        # 要求前一交易日是本笔 buy_date 前最后一日(近似昨收; 跨 gap 允许)
        O, H, L, C = bd_row[1], bd_row[2], bd_row[3], bd_row[4]
        PC = pc_row[4]
        if not (O and H and L and C and PC):
            miss += 1
            continue
        plans.append({"etf_code": ec, "etf_name": tb[fIdx["etf_name"]], "buy_date": bd,
                      "signal_date": tb[fIdx["signal_date"]], "O": O, "L": L, "C": C, "PC": PC})
    print(f"有 OHLC+昨收 的计划: {len(plans)} / {len(kept)} (缺 {miss})")

    DISCOUNTS = [0.0, 0.002, 0.003, 0.004, 0.005, 0.006, 0.008, 0.010, 0.012, 0.015]
    out = {}
    for miss_action in ("tail", "skip"):
        print()
        print(f"===== miss_action = {miss_action} ({'尾盘C兜底' if miss_action=='tail' else '放弃不买'}) =====")
        header = f"{'折扣/昨收':>9} | {'总成交率':>8} | {'低开即成交':>9} | {'回落触及':>8} | {'成交折价%':>9} | {'E[折价%]':>9} | {'每万收益差':>10}"
        print(header); print("-" * len(header))
        for d in DISCOUNTS:
            P_base = 1 - d
            n_low = n_fill = n_unfill = 0
            s_all = 0.0
            s_fill_disc = 0.0
            n_fill_for_disc = 0
            for p in plans:
                O, L, C, PC = p["O"], p["L"], p["C"], p["PC"]
                P = PC * P_base
                if O <= P:
                    # 低开/平开 <= 挂价: 开盘即成交在 O
                    eff = O
                    n_low += 1; n_fill += 1
                    s_fill_disc += (O / O - 1) * 100
                    n_fill_for_disc += 1
                elif L <= P:
                    # 高开但日内回落触及 P
                    eff = P
                    n_fill += 1
                    s_fill_disc += (P / O - 1) * 100
                    n_fill_for_disc += 1
                else:
                    # 未成交
                    n_unfill += 1
                    if miss_action == "tail":
                        eff = C * (1 + SLIP)
                    else:
                        eff = None  # 放弃, 该笔不入账(折价计 0)
                if eff is not None:
                    s_all += (eff / O - 1) * 100
            n = len(plans)
            e = s_all / n
            fill_rate = n_fill / n
            disc = s_fill_disc / n_fill_for_disc if n_fill_for_disc else 0
            win = e * 100  # 每万本金收益差(元): 1% 折价=100元/万
            print(f"{(1-d)*100:>7.1f}% | {fill_rate*100:>6.1f}% | {n_low/n*100:>7.1f}% | {n_fill-n_low:>6} | {disc:>+8.3f}% | {e:>+8.3f}% | {win:>+9.1f} 元")
            out.setdefault(miss_action, {})[d] = {"fill_rate": fill_rate, "E_disc": e, "win_per_10k": win}

    # 用户假设验证
    print()
    print("== 用户假设验证 ==")
    for d in (0.005, 0.010):
        for ma in ("tail", "skip"):
            r = out[ma][d]
            print(f"挂昨收-{d*100:.1f}% miss={ma}: 成交率 {r['fill_rate']*100:.1f}%  E[折价] {r['E_disc']:+.3f}%  每万 {r['win_per_10k']:+.1f} 元")

    # 按年分解: tail 口径最优档
    print()
    print("== 按年分解(尾盘兜底, 挂昨收-0.5% vs -1.0%) ==")
    yrs = {}
    for p in plans:
        yrs.setdefault(p["buy_date"][:4], []).append(p)
    for y in sorted(yrs):
        ps = yrs[y]
        line = f"{y}: n={len(ps):>4}"
        for d in (0.005, 0.010):
            n_fill = 0
            s_all = 0.0
            for p in ps:
                O, L, C, PC = p["O"], p["L"], p["C"], p["PC"]
                P = PC * (1 - d)
                if O <= P:
                    eff = O; n_fill += 1
                elif L <= P:
                    eff = P; n_fill += 1
                else:
                    eff = C * (1 + SLIP)
                s_all += (eff / O - 1) * 100
            line += f"  -{d*100:.1f}%: 成交率{n_fill/len(ps)*100:>5.1f}% E[{s_all/len(ps):+.3f}%]"
        print(line)

    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "nextday_buy_exec.json"), "w") as f:
        json.dump({"generated_at": datetime.now().isoformat(), "n_plans": len(plans), "out": out}, f, ensure_ascii=False, indent=1)
    print("\n已输出 nextday_buy_exec.json")

main()
