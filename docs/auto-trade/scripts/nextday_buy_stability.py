#!/usr/bin/env python3
"""次日买入执行策略 · 稳定性分解(按年/分半/一致性) —— 补 §5.1 全维度"""
import os, json, sqlite3, sys
sys.path.insert(0, "/Users/linhuichen/code/trade/scripts")
import kelly_posrating as kp
DATA = "/Users/linhuichen/code/trade/static-site/data"
SLIP = 0.001

def build_kept(trades_doc, backtest_doc, s06_doc, feat_doc):
    fields = trades_doc["fields"]; fIdx = {f: i for i, f in enumerate(fields)}
    quads = trades_doc["quadrants"]; sell_modes = backtest_doc["config"]["sell_modes"]
    pos_raw = []
    for rk in ("rating_high", "rating_mid", "rating_low"):
        pos_raw += (quads.get(rk) or {}).get("A") or []
    trade_dims = kp._trade_dims(quads, fIdx)
    spec_map, feats = {}, {}
    for r in (feat_doc.get("meta") or {}).get("rules") or []:
        if isinstance(r, dict) and r.get("key"): spec_map[r["key"]] = r
    feats = feat_doc.get("features") or {}
    def feat_at(name, date):
        s = feats.get(name)
        return s.get(str(date)) if s else None
    s06 = kp.S06Resolver(s06_doc)
    passes_fade = kp.make_passes_fade(fIdx, trade_dims, spec_map, feat_at, s06)
    base_pool = kp._collect_base_pool(quads, sell_modes, fIdx, passes_fade)
    kept = kp._position_cap_kept_keys(base_pool, fIdx, 1)
    out = []
    for tb in pos_raw:
        if passes_fade(tb) and kept.get(kp._base_key(tb, fIdx)):
            out.append(tb)
    return out, fIdx

def main():
    trades_doc = json.load(open(DATA + "/signal_kelly_trades.json"))
    backtest_doc = json.load(open(DATA + "/signal_kelly_backtest.json"))
    s06_doc = json.load(open(DATA + "/kelly_mode_s06_state.json"))
    feat_doc = json.load(open(DATA + "/kelly_loss_features.json"))
    kept, fIdx = build_kept(trades_doc, backtest_doc, s06_doc, feat_doc)
    con = sqlite3.connect("/Users/linhuichen/code/trade/data/etf_national_team.db")
    m = {}
    for ec, dt, op, hi, lo, cl in con.execute("SELECT etf_code,date,open,high,low,close FROM etf_daily ORDER BY etf_code,date"):
        m.setdefault(ec, []).append((dt, op, hi, lo, cl))
    plans = []
    for tb in kept:
        ec, bd = str(tb[fIdx["etf_code"]] or ""), str(tb[fIdx["buy_date"]] or "")
        rows = m.get(ec) or []
        idx = next((i for i, r in enumerate(rows) if r[0] == bd), None)
        if idx is None or idx == 0: continue
        bd_row, pc_row = rows[idx], rows[idx - 1]
        O, L, C = bd_row[1], bd_row[3], bd_row[4]
        PC = pc_row[4]
        if not (O and L and C and PC): continue
        plans.append({"bd": bd, "O": O, "L": L, "C": C, "PC": PC, "profit0": tb[fIdx["profit"]] or 0, "sr": str(tb[fIdx["sell_reason"]] or "")})
    n = len(plans)
    print(f"n={n}")

    # 按年: skip -0.5% vs skip -1.0% vs S0, 总收益率 + 成交率
    print(f"\n{'年份':>6} | {'笔数':>5} | {'S0收益率':>9} | {'-0.5%率/收益率':>16} | {'-1.0%率/收益率':>16}")
    yrs = {}
    for p in plans: yrs.setdefault(p["bd"][:4], []).append(p)
    rows_out = []
    for y in sorted(yrs):
        ps = yrs[y]
        s0 = sum(p["profit0"] for p in ps) / (len(ps) * 10000) * 100
        seg = f"{y}"
        line = [y, len(ps), f"{s0:+.2f}%"]
        for d in (0.005, 0.010):
            tp = ti = f_cnt = 0
            for p in ps:
                P = p["PC"] * (1 - d)
                if p["O"] <= P: eff = 0.0; f_cnt += 1
                elif p["L"] <= P: eff = P / p["O"] - 1; f_cnt += 1
                else: continue
                tp += p["profit0"] - 10000 * eff
                ti += 10000
            r = tp / ti * 100 if ti else 0
            line.append(f"{f_cnt/len(ps)*100:.0f}%/{r:+.2f}%")
        print(" | ".join(str(x) for x in line))
        rows_out.append(line)

    # 分半: 前半 vs 后半
    half = n // 2
    print("\n== 分半稳定性(全部有效笔) ==")
    sets = {"前半(近一半)": plans[len(ps) * 0: half] if False else plans[:half], "后半": plans[half:]}
    for name, ps in sets.items():
        seg = f"{name}: n={len(ps)}"
        for d in (0.0, 0.005, 0.010):
            tp = ti = f_cnt = 0
            for p in ps:
                P = p["PC"] * (1 - d)
                if p["O"] <= P: eff = 0.0; f_cnt += 1
                elif p["L"] <= P: eff = P / p["O"] - 1; f_cnt += 1
                else: continue
                tp += p["profit0"] - 10000 * eff
                ti += 10000
            r = tp / ti * 100 if ti else 0
            seg += f"  {('S0' if d==0 else f'-{d*100:.1f}%')}: 成交{f_cnt/len(ps)*100:.0f}% 收益{r:+.2f}%"
        print(seg)

    # 方向一致性: 逐笔 S0 收益为正时, 挂 -0.5% 是否也正(样本内)
    pos0 = sum(1 for p in plans if p["profit0"] > 0)
    print(f"\nS0 正收益笔: {pos0}/{n} = {pos0/n*100:.1f}%")

    # 逐笔 E 差异分布: -0.5% skip vs S0 的 profit 差
    diffs = []
    for p in plans:
        P = p["PC"] * 0.995
        if p["O"] <= P: eff = 0.0
        elif p["L"] <= P: eff = P / p["O"] - 1
        else:
            diffs.append(None); continue
        diffs.append(-10000 * eff)
    gain = [d for d in diffs if d is not None]
    print(f"-0.5% 成交笔 328: 其中省>0: {sum(1 for d in gain if d>0)} 省0(低开): {sum(1 for d in gain if d==0)} 亏(无): 0 平均省 {sum(gain)/len(gain):.1f} 元/笔")

main()
