#!/usr/bin/env python3
"""
次日买入执行策略 · 拍板补测: 测试一(高开率/开盘买不到概率) + 测试二(return_pct_max_holding 口径)
目的: 为用户拍板「次日买入执行默认档」提供两组数据
  测试一: 545 笔完整环路计划中 高开率(O>PC) / 低开率(O<=PC); 高开笔中 回落触达昨收(L<=PC 挂昨收单成交)
          vs 全天未回落(L>PC 买不到); 关键 = 「高开且 L>PC」(集合竞价+盘中都买不到) 占全部笔比例
  测试二: return_pct_max_holding = 总净盈亏 / 峰值同时持仓资金
          放弃模式下未成交笔次日不占资金 -> 峰值持仓资金降低 -> 相对收益率可能反而更高
          对照档: S0 全投(545) / 挂昨收+尾盘兜底(545 全投) / 挂昨收+放弃(465) / -0.5% 放弃(328) / -1% 放弃(188)
口径(与 nextday_buy_full_loop_backtest.py 完全一致, 不发明新口径):
  - 宇宙 = S06+K=1+A 模式 545 笔 (build_kept: signal_kelly_trades.json + backtest.json + kelly_mode_s06_state.json + kelly_loss_features.json)
  - 每笔: buy_date 当日开盘 O / 日内最低 L / 收盘 C; PC = buy_date 前一日收盘 (=既有脚本"T日收盘昨收")
  - 挂单判定: P = PC*(1-d); O<=P 低开以 O 成交; L<=P 回落以 P 成交; 否则 skip(放弃 profit=0 不占资金) / tail(C*(1+SLIP) 兜底, SLIP=0.001)
  - profit 修正(复权): profit = profit0 - 1万*r, r = 成交价/O - 1 (既有脚本同款; S0 直接成交 r=0)
  - 卖出日: A 模式第 10 交易日 = signal_kelly_trades 真实 sell_date(若缺失=持有中, 记为分析截止日+1 回收即数据末日尾)
  - 在仓资金扫描: buy_date +1万, sell_date -1万 (卖出日收盘卖出回收, 当日不再占用——用户指定口径; 敏感性对照见报告)
输入依赖: static-site/data/signal_kelly_trades.json + signal_kelly_backtest.json + kelly_mode_s06_state.json + kelly_loss_features.json + data/etf_national_team.db(etf_daily)
输出: stdout + nextday_gap_maxhold.json; 报告 docs/auto-trade/next-day-buy-gap-and-max-holding-20260910.md
复现: python3 docs/auto-trade/scripts/nextday_gap_maxhold_backtest.py
"""
import os, json, sqlite3
import sys
sys.path.insert(0, "/Users/linhuichen/code/trade/scripts")
import kelly_posrating as kp

DATA = "/Users/linhuichen/code/trade/static-site/data"
DB = "/Users/linhuichen/code/trade/data/etf_national_team.db"
SLIP = 0.001
INV = 10000.0
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nextday_gap_maxhold.json")


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
    con = sqlite3.connect(DB)
    cur = con.cursor()
    m = {}
    cal = set()
    for ec, dt, op, hi, lo, cl in cur.execute("SELECT etf_code, date, open, high, low, close FROM etf_daily ORDER BY etf_code, date"):
        m.setdefault(ec, []).append((dt, op, hi, lo, cl))
        cal.add(dt)
    con.close()
    return m, sorted(cal)


def build_plans(trades_doc, backtest_doc, s06_doc, feat_doc, daily):
    """与 nextday_buy_full_loop_backtest.py 完全同款的 plans 构建(同一事实源)"""
    kept, fIdx = build_kept(trades_doc, backtest_doc, s06_doc, feat_doc)
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
        L = bd_row[3]
        C = bd_row[4]
        PC = pc_row[4]
        if not (O and L and C and PC):
            continue
        profit_baseline = tb[fIdx["profit"]] or 0
        sell_date = str(tb[fIdx["sell_date"]] or "")
        sell_reason = str(tb[fIdx["sell_reason"]] or "")
        plans.append({"ec": ec, "bd": bd, "sdate": sell_date, "O": O, "L": L, "C": C, "PC": PC,
                      "profit0": profit_baseline, "hold": tb[fIdx["hold_days"]], "sell_reason": sell_reason})
    return plans


def simulate(plans, d, mode):
    """返回 (每笔结果列表, 汇总)。每笔: filled(skip=0/tail=-1/正常1), profit, inv, invest_date, sell_date"""
    per_trade = []
    for p in plans:
        P = p["PC"] * (1 - d)
        if p["O"] <= P:
            r = 0.0
            st = 1
        elif p["L"] <= P:
            r = P / p["O"] - 1
            st = 1
        elif mode == "skip":
            per_trade.append({"profit": 0.0, "inv": 0.0, "st": 0,
                              "bd": p["bd"], "sdate": p["sdate"], "O": p["O"], "L": p["L"], "C": p["C"], "PC": p["PC"]})
            continue
        else:
            r = p["C"] * (1 + SLIP) / p["O"] - 1
            st = -1
        profit = p["profit0"] - INV * r
        per_trade.append({"profit": profit, "inv": INV, "st": st,
                          "bd": p["bd"], "sdate": p["sdate"], "O": p["O"], "L": p["L"], "C": p["C"], "PC": p["PC"]})
    tot_profit = sum(x["profit"] for x in per_trade)
    tot_inv = sum(x["inv"] for x in per_trade)
    return per_trade, {"tot_profit": tot_profit, "tot_inv": tot_inv,
                       "n_fill": sum(1 for x in per_trade if x["st"] == 1),
                       "n_skip": sum(1 for x in per_trade if x["st"] == 0),
                       "n_tail": sum(1 for x in per_trade if x["st"] == -1)}


def sdate_of(p, cutoff):
    return p["sdate"] or cutoff  # 持有中 => 分析截止日回收


def max_holding_stats(per_trade, cutoff, calendar):
    """按交易日历扫描在仓资金: buy_date +inv(占用起), sell_date -inv(卖出日收盘回收, 当日不再占用)。
    返回峰值资金/峰值笔数/平均在仓资金(全区间交易日均值)/总占用天数。"""
    delta = {}  # date -> 资金净变化
    cnt = {}    # date -> 笔数净变化
    for x in per_trade:
        if x["inv"] == 0:
            continue
        sd = sdate_of(x, cutoff)
        delta[x["bd"]] = delta.get(x["bd"], 0.0) + x["inv"]
        cnt[x["bd"]] = cnt.get(x["bd"], 0) + 1
        if sd and sd > x["bd"]:
            delta[sd] = delta.get(sd, 0.0) - x["inv"]
            cnt[sd] = cnt.get(sd, 0) - 1
        # sd == bd: 当日买当日卖(极端), 不占隔日资金
    cal = [c for c in calendar if c >= min(delta.keys()) and c <= cutoff]
    cur = 0.0
    cur_n = 0
    peak = 0.0
    peak_n = 0
    cum = 0.0
    n_days = 0
    for dt in cal:
        cur += delta.get(dt, 0.0)
        cur_n += cnt.get(dt, 0)
        if cur < 1e-9:
            cur = 0.0
        if cur_n < 0:
            cur_n = 0
        cum += cur
        n_days += 1
        if cur > peak:
            peak = cur
        if cur_n > peak_n:
            peak_n = cur_n
    avg_pos = cum / n_days if n_days else 0.0
    return {"peak_cash": peak, "peak_n": peak_n, "avg_pos": avg_pos, "days": n_days}


def main():
    trades_doc = json.load(open(os.path.join(DATA, "signal_kelly_trades.json")))
    backtest_doc = json.load(open(os.path.join(DATA, "signal_kelly_backtest.json")))
    s06_doc = json.load(open(os.path.join(DATA, "kelly_mode_s06_state.json")))
    feat_doc = json.load(open(os.path.join(DATA, "kelly_loss_features.json")))
    daily, calendar = load_daily()
    plans = build_plans(trades_doc, backtest_doc, s06_doc, feat_doc, daily)
    n = len(plans)
    cutoff = max(p["bd"] for p in plans)  # 分析截止 = 最后一笔买入日(20260908)
    print(f"完整环路计划: {n} 笔; 分析截止日(持有中回收) = {cutoff}")
    print()

    # ============ 测试一: 高开率 / 高开后开盘价买不到的概率 ============
    up = sum(1 for p in plans if p["O"] > p["PC"])
    flat_down = n - up
    up_reach = sum(1 for p in plans if p["O"] > p["PC"] and p["L"] <= p["PC"])
    up_no_reach = up - up_reach
    print("========== 测试一: 高开率 + 高开后开盘价买不到概率 ==========")
    print(f"总笔数              : {n}")
    print(f"高开 O>PC           : {up} 笔 = {up/n*100:.1f}%")
    print(f"低开(含平) O<=PC    : {flat_down} 笔 = {flat_down/n*100:.1f}%")
    print(f"  - 其中 O==PC      : {sum(1 for p in plans if p['O'] == p['PC'])} 笔")
    print(f"高开笔中 回落触达昨收(L<=PC): {up_reach} 笔 = {up_reach/up*100:.1f}% (挂昨收单按昨收成交)")
    print(f"高开笔中 全天未回落 (L>PC) : {up_no_reach} 笔 = {up_no_reach/up*100:.1f}% (挂昨收单买不到)")
    print(f"[关键] 高开且 L>PC 占全样本  : {up_no_reach/n*100:.1f}%  <- 裸开盘直买 vs 挂昨收 核心差异(集合竞价+盘中都买不到)")
    print(f"对照: 高开且 L>PC 的这些笔若开盘直买, 其 profit0 合计 = {sum(p['profit0'] for p in plans if p['O'] > p['PC'] and p['L'] > p['PC']):+,.0f} 元 ({up_no_reach} 笔, 占 S0 总收益 {sum(p['profit0'] for p in plans if p['O'] > p['PC'] and p['L'] > p['PC'])/sum(p['profit0'] for p in plans)*100:.1f}%)")
    print()

    # ============ 测试二: return_pct_max_holding 各档对比 ============
    print("========== 测试二: return_pct_max_holding = 总净盈亏 / 峰值同时持仓资金 ==========")
    scenarios = [
        ("S0 开盘直买全投(545)", 0.0, "all"),
        ("挂昨收+尾盘兜底(465+80)", 0.0, "tail"),
        ("挂昨收+放弃(465 投入)", 0.0, "skip"),
        ("-0.5% 放弃(328 投入)", 0.005, "skip"),
        ("-1% 放弃(188 投入)", 0.01, "skip"),
    ]
    rows = []
    for name, d, mode in scenarios:
        if mode == "all":
            per_trade = [{"profit": p["profit0"], "inv": INV, "st": 1,
                          "bd": p["bd"], "sdate": p["sdate"]} for p in plans]
            tot = {"tot_profit": sum(p["profit0"] for p in plans), "tot_inv": n * INV,
                   "n_fill": n, "n_skip": 0, "n_tail": 0}
        else:
            per_trade, tot = simulate(plans, d, mode)
        mh = max_holding_stats(per_trade, cutoff, calendar)
        rat = tot["tot_profit"] / mh["peak_cash"] * 100 if mh["peak_cash"] else 0
        idle = 1 - tot["tot_inv"] / (n * INV)
        rows.append((name, tot, mh, rat, idle))
        print(f"{name:<24} 总收益 {tot['tot_profit']:>+10,.0f} | 总投入 {tot['tot_inv']/10000:>7,.1f}万 | "
              f"峰值持仓资金 {mh['peak_cash']/10000:>8,.1f}万 | 峰值笔数 {mh['peak_n']:>3} | "
              f"平均在仓 {mh['avg_pos']/10000:>6,.1f}万 | 资金闲置率 {idle*100:>5.1f}% | return_pct_max_holding {rat:>+7.2f}%")
    # 总收益率对照(既有报告口径)
    print()
    print("对照(既有报告口径 总收益率=总收益/Σ投入):")
    for name, tot, mh, rat, idle in rows:
        print(f"  {name:<24} {tot['tot_profit']/(tot['tot_inv']/INV)/INV*100:+.2f}% (Σ投入 {tot['tot_inv']/10000:,.1f}万, 成交/放弃/兜底 {tot['n_fill']}/{tot['n_skip']}/{tot['n_tail']})")

    out = {"n": n, "cutoff": cutoff,
           "gap": {"up": up, "flat_down": flat_down, "up_reach": up_reach, "up_no_reach": up_no_reach,
                   "up_rate": up / n, "up_no_reach_rate": up_no_reach / n},
           "scenarios": [{"name": nm, "tot_profit": t["tot_profit"], "tot_inv": t["tot_inv"],
                          "n_fill": t["n_fill"], "n_skip": t["n_skip"], "n_tail": t["n_tail"],
                          "peak_cash": m["peak_cash"], "peak_n": m["peak_n"], "avg_pos": m["avg_pos"],
                          "idle_rate": 1 - t["tot_inv"] / (n * INV), "return_pct_max_holding": t["tot_profit"] / m["peak_cash"] * 100}
                         for nm, t, m, r, i in rows]}
    json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
    print()
    print(f"已输出 {OUT}")


main()
