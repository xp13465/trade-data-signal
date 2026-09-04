#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""净资产走势图调研·验证脚本(2026-09-01, researcher 只读落档)

目的:
  1) 验证「逐日净资产」算法能从 signal_kelly_trades.json + accum_nav_map.json 推导
  2) 精确复刻前端 sim 弹窗完整管线(K选样→GHI管位→日期切片→峰值扫描), 与页面同构(§3.2 对账铁律)
  3) 期末对账锚点: 净资产_末 == 初始资金 + cumYuan(前端口径 Σ费后盈亏含持仓中浮盈) + (期末市值 - 按current_price市值)
  4) 输出逐日曲线样例(供实施后与页面渲染逐位对账)

口径(与前端 _simRenderOnce/_simRenderTable 对齐):
  - 模式池: _simBuildModePool (quadrants[qk][mode] 按 mode 现筛 + basekey 去重)
  - K选样: 每 signal_date 按 (track_score DESC→rating→signal→buy_date ASC) 取前 K
  - GHI管位: _simGhiHoldCap (G/I=P≤3d先卖年轻仓腾位改写卖出日/强平; H=满仓不买超容日丢弃)
  - 日期切片: 按 signal_date 字符串比较, 空=不筛 (管位后执行, 与前端 L4223-4231 同序)
  - 峰值扫描: asc 正序 signal_date, openMap 快照最大值 (前端 L4874-4901); peakDisp=max(peak,1)
  - 初始资金 = 峰值同时持仓笔数 × ¥10000 (H 档管位开=5笔=5万, 与用户"如 H 方法 5W 起步"一致; 同 L4931 cumPct 分母)
  - 每笔本金 PRIN=10000; 费率 etf_def (万3/最低5/滑点千1/过户万0.1/印花万5卖, _SIM_FEE_PRESETS 同值)
  - 买入执行价=记录 buy_price ÷(1+0.001)还原真实净值再×(1+用户滑点); 卖出同 (L5176-5188 双滑点修复)
  - 逐日净资产 = 现金 + 持仓市值; 现金 = 初始 - Σ开仓日扣本金 + Σ卖出日回笼净额(PRIN+费后盈亏)
    市值 = Σ未平仓份额×当日真实净值(accum_nav, 缺日向前取)
  - 交易日历 = 窗口内持仓 ETF 的 accum_nav 日期并集 ∩ [startD,endD] (真实交易日序列, 每交易日打点)

数据版本: signal_kelly_trades.json generated_at=2026-09-03 21:44; accum_nav_map.json 2026-08-30(末日期 20260828)。
复现命令: cd docs/kelly/analysis/sim-netasset-equity-chart-20260901 && python3 scripts/netasset_daily_repro.py
"""
import json, os, sys
from datetime import date

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))
TRADES = os.path.join(ROOT, "static-site", "data", "signal_kelly_trades.json")
NAV = os.path.join(ROOT, "static-site", "data", "accum_nav_map.json")
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "netasset_daily_sample.json")

PRIN = 10000.0
SLIP_MAIN = 0.001
FP = {"commission_rate": 0.0003, "min_commission": 5.0, "slippage": 0.001,
      "transfer_fee_rate_sh": 0.00001, "stamp_duty_rate": 0.0005}
GHI_TIERS = {"G": {"play": "满仓不卖·P≤3d", "tier": "10万", "cap": 100000},
             "H": {"play": "满仓不买", "tier": "5万", "cap": 50000},
             "I": {"play": "P≤3d", "tier": "9万", "cap": 90000}}
_META_TIER = {"sell": None, "sell_stop_loss": None, "band_hold": None, "band_sell": None,
              "buy": "H", "buy_aux": "I", "buy_special": "G", "buy_backup": None}

def load():
    tr = json.load(open(TRADES)); nav = json.load(open(NAV))
    fI = {f: i for i, f in enumerate(tr["fields"])}
    return tr, nav, fI

def base_key(r, fI):
    return "|".join(str(r[fI[k]]) for k in ["signal_date", "index_id", "signal", "buy_date", "etf_code"])

def build_pool(tr, fI, mode):
    seen, recs = {}, []
    for qk, dims in tr["quadrants"].items():
        for orig in (dims.get(mode) or []):
            bk = base_key(orig, fI)
            if bk not in seen:
                seen[bk] = orig; recs.append(orig)
    return recs

def rk(r): return {"high": 0, "mid": 1, "low": 2}.get(r, 3)
def sk(s): return {"buy_backup": 0, "buy": 1, "buy_aux": 2, "buy_special": 3}.get(s, 9)

def top_k(rows, fI, K):
    by = {}
    for t in rows: by.setdefault(str(t[fI["signal_date"]] or ""), []).append(t)
    out = []
    for sd in sorted(by):
        r = sorted(by[sd], key=lambda a: (
            -(float(a[fI["track_score"]]) if a[fI["track_score"]] not in (None, "") else 0),
            rk(str(a[fI["rating"]] or "")), sk(str(a[fI["signal"]] or "")), str(a[fI["buy_date"]] or "")))
        out.extend(r[:K])
    return out

def ghi_hold_cap(rows, fI, mode):
    """精确复刻 app.js _simGhiHoldCap L3664-3753"""
    t = GHI_TIERS.get(mode)
    if not t: return rows, None
    capN = round(t["cap"] / 10000)
    isP = mode in ("G", "I")
    def day_span(bd, sd):
        if not bd or sd < bd: return 0
        d1 = date(int(bd[:4]), int(bd[4:6]), int(bd[6:8]))
        d2 = date(int(sd[:4]), int(sd[4:6]), int(sd[6:8]))
        return max(round((d2 - d1).days), 0)
    trs = [{"row": r, "buy_date": str(r[fI["buy_date"]] or ""), "sell_date": str(r[fI["sell_date"]] or "") or None,
            "signal_date": str(r[fI["signal_date"]] or ""), "closed": None} for r in rows]
    buysByDate, datesSet, allDates = {}, set(), []
    for tr in trs:
        bd = tr["buy_date"]
        buysByDate.setdefault(bd, []).append(tr)
        if bd not in datesSet: datesSet.add(bd); allDates.append(bd)
        sd2 = tr["sell_date"]
        if sd2 and sd2 not in datesSet: datesSet.add(sd2); allDates.append(sd2)
    allDates.sort()
    openTrs, kept, cur, peak = [], [], 0, 0
    for dt in allDates:
        newOpen = []
        for x in openTrs:
            if x["sell_date"] == dt and x["closed"] is None:
                x["closed"] = "natural"; cur -= 1; kept.append(x["row"])
            else: newOpen.append(x)
        openTrs = newOpen
        dayTrs = buysByDate.get(dt)
        if dayTrs:
            dayTotal = len(dayTrs); needed = cur + dayTotal - capN
            if needed > 0:
                if isP:
                    while needed > 0 and openTrs:
                        sel = None; selBuy = None
                        for ot in openTrs:
                            if ot["closed"] is not None: continue
                            if day_span(ot["buy_date"], dt) <= 3:
                                if sel is None or ot["buy_date"] < selBuy: sel = ot; selBuy = ot["buy_date"]
                        if sel is None:
                            for ot2 in openTrs:
                                if ot2["closed"] is not None: continue
                                if sel is None or ot2["buy_date"] < sel["buy_date"]: sel = ot2
                        sel["closed"] = "p3d"
                        selRow = sel["row"][:]
                        selRow[fI["sell_date"]] = dt
                        selRow[fI["sell_reason"]] = "管位腾位卖出"
                        kept.append(selRow); cur -= 1
                        openTrs = [o for o in openTrs if o is not sel]
                        needed = cur + dayTotal - capN
                    if needed <= 0:
                        for q in dayTrs: openTrs.append(q); cur += 1
                # H=满仓不买: 超容日不买(丢弃), 不进 kept
            else:
                for q2 in dayTrs: openTrs.append(q2); cur += 1
        if cur > peak: peak = cur
    for z in openTrs:
        if z["closed"] is None: kept.append(z["row"])
    return kept, peak

def peak_positions(rows, fI):
    """精确复刻 L4874-4901 openMap 快照扫描"""
    asc = sorted(rows, key=lambda a: str(a[fI["signal_date"]] or ""))
    openMap = {}; peak = 0; gi = 0; n = len(asc)
    while gi < n:
        sd = str(asc[gi][fI["signal_date"]] or ""); gj = gi
        while gj < n and str(asc[gj][fI["signal_date"]] or "") == sd: gj += 1
        for ok in list(openMap):
            if openMap[ok] and openMap[ok] <= sd: del openMap[ok]
        for i in range(gi, gj):
            bd = str(asc[i][fI["buy_date"]] or ""); sld = str(asc[i][fI["sell_date"]] or "")
            if bd and bd <= sd and (sld == "" or sld > sd):
                bk = base_key(asc[i], fI)
                if bk not in openMap: openMap[bk] = sld
        if len(openMap) > peak: peak = len(openMap)
        gi = gj
    return peak

def buy_with_fees(budget, close, etf_code, fp):
    buy_price = close * (1 + fp["slippage"])
    if buy_price <= 0: return 0.0, 0.0
    sh = fp["transfer_fee_rate_sh"] if etf_code else 0.0
    shares = budget / (buy_price * (1 + fp["commission_rate"] + sh))
    gross = shares * buy_price
    comm = gross * fp["commission_rate"]
    if comm < fp["min_commission"]:
        shares = (budget - fp["min_commission"]) / (buy_price * (1 + sh))
        gross = shares * buy_price
        comm = fp["min_commission"]
    return shares, comm + gross * sh

def sell_net(shares, close, etf_code, fp):
    sell_price = close * (1 - fp["slippage"])
    gross = shares * sell_price
    comm = max(gross * fp["commission_rate"], fp["min_commission"])
    sh = fp["transfer_fee_rate_sh"] if etf_code else 0.0
    net = gross - comm - gross * sh - gross * fp["stamp_duty_rate"]
    return net

def calc_row(t, fI, fp):
    """复刻 _simBtCalcRow L5176-5202: pnlYuan/费后盈亏; 持仓中按 current_price"""
    bp_raw = float(t[fI["buy_price"]] or 0)
    bp = bp_raw / (1 + SLIP_MAIN) if bp_raw > 0 else 0.0
    is_holding = not str(t[fI["sell_date"]] or "")
    if is_holding:
        cp = float(t[fI["current_price"]] or 0)
        eff_sp = cp if cp > 0 else 0.0
    else:
        sp = float(t[fI["sell_price"]] or 0)
        eff_sp = sp / (1 - SLIP_MAIN) if sp > 0 else 0.0
    code = str(t[fI["etf_code"]] or "")
    br = buy_with_fees(PRIN, bp, code, fp)
    if is_holding and not (eff_sp > 0):
        pnl_yuan = 0.0
    else:
        net = sell_net(br[0], eff_sp, code, fp)
        pnl_yuan = net - PRIN
    return pnl_yuan, is_holding, br[0]

def daily_netasset(rows, nav, fI, fp, init_capital):
    prep = []
    for r in rows:
        code = str(r[fI["etf_code"]] or "")
        bp_raw = float(r[fI["buy_price"]] or 0)
        bp = bp_raw / (1 + SLIP_MAIN) if bp_raw > 0 else 0.0
        shares, _ = buy_with_fees(PRIN, bp, code, fp)
        sell_d = str(r[fI["sell_date"]] or "")
        realized = 0.0
        if sell_d:
            sp = float(r[fI["sell_price"]] or 0)
            px = sp / (1 - SLIP_MAIN) if sp > 0 else 0.0
            if px > 0: realized = sell_net(shares, px, code, fp) - PRIN
        prep.append({"code": code, "buy": str(r[fI["buy_date"]] or ""), "sell": sell_d,
                     "shares": shares, "realized": realized, "bp_real": bp})
    cal = set()
    for p in prep:
        nd = nav.get(p["code"])
        if nd: cal.update(nd.keys())
    cal = sorted(cal)
    proceeds_by_day = {}
    for p in prep:
        if p["sell"]:
            proceeds_by_day.setdefault(p["sell"], 0.0)
            proceeds_by_day[p["sell"]] += PRIN + p["realized"]
    open_by_idx = {}; cash = init_capital; curve = []
    nav_ff = 0
    for d in cal:
        if d in proceeds_by_day: cash += proceeds_by_day[d]
        for i in list(open_by_idx):
            if open_by_idx[i]["sell"] == d: del open_by_idx[i]
        for i, p in enumerate(prep):
            if p["buy"] == d and i not in open_by_idx:
                open_by_idx[i] = p; cash -= PRIN
        mv, hold_n = 0.0, 0
        for i, p in open_by_idx.items():
            nd = nav.get(p["code"]); px = None
            if nd:
                cands = [k for k in nd if k <= d]
                px = nd[cands[-1]] if cands else None
            if px is None or px <= 0:
                px = p["bp_real"]; nav_ff += 1
            mv += p["shares"] * px; hold_n += 1
        curve.append({"date": d, "value": round(cash + mv, 2), "holdings": hold_n,
                      "cash": round(cash, 2), "mv": round(mv, 2)})
    realized_acc = sum(p["realized"] for p in prep)
    return curve, realized_acc, nav_ff

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "H"
    K = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    W0 = sys.argv[3] if len(sys.argv) > 3 else "20250901"
    W1 = sys.argv[4] if len(sys.argv) > 4 else "20260831"
    tr, nav, fI = load()
    pool = [t for t in build_pool(tr, fI, mode)
            if (not W0 or str(t[fI["signal_date"]] or "") >= W0) and (not W1 or str(t[fI["signal_date"]] or "") <= W1)]
    kept = top_k(pool, fI, K)
    kept, ghi_peak = ghi_hold_cap(kept, fI, mode)
    peak = peak_positions(kept, fI)
    if ghi_peak is not None and ghi_peak != peak:
        print(f"!! 管位内部peak={ghi_peak} 扫描peak={peak} 不一致(以渲染扫描为准)")
    peakDisp = max(peak, 1)
    init_capital = peakDisp * PRIN
    # 前端口径 cumYuan(含持仓中浮盈, 复刻 _simBtCalcRow)
    cum_yuan = sum(calc_row(t, fI, FP)[0] for t in kept)
    curve, realized_acc, nav_ff = daily_netasset(kept, nav, fI, FP, init_capital)
    curve = [c for c in curve if (not W0 or c["date"] >= W0) and (not W1 or c["date"] <= W1)]
    if not curve:
        print("空窗口"); return
    final = curve[-1]
    # 对账: 净资产末 = 初始 + cumYuan + (期末市值 - 按current_price市值)
    curp_mv = 0.0
    for t in kept:
        if not str(t[fI["sell_date"]] or "") and (float(t[fI["current_price"]] or 0) > 0):
            code = str(t[fI["etf_code"]] or "")
            bp_raw = float(t[fI["buy_price"]] or 0); bp = bp_raw / (1 + SLIP_MAIN) if bp_raw > 0 else 0.0
            sh, _ = buy_with_fees(PRIN, bp, code, FP)
            curp_mv += sh * float(t[fI["current_price"]])
    diff = final["value"] - (init_capital + cum_yuan + (final["mv"] - curp_mv))
    print(f"模式={mode} K={K} 窗口={W0}~{W1} 费率=etf_def")
    print(f"信号{len(pool)}→K1={len(top_k(pool,fI,K))}→管位后{len(kept)} | 峰值同时持仓={peak}笔 → 初始资金={init_capital:.0f}元")
    print(f"  (G/H/I 管位开; {mode}档 cap={GHI_TIERS.get(mode,{}).get('tier','无管位')})")
    print(f"曲线点数={len(curve)} 区间={curve[0]['date']}~{curve[-1]['date']} | nav forward-fill 笔次={nav_ff}")
    print(f"期末净资产={final['value']:.2f} = 现金{final['cash']:.2f} + 市值{final['mv']:.2f}(持仓{final['holdings']}笔)")
    print(f"前端口径 cumYuan={cum_yuan:.2f} (Σ费后盈亏含持仓中浮盈)")
    print(f"对账: 初始{init_capital:.0f}+cumYuan{cum_yuan:.2f}+(期末市值{final['mv']:.2f}-按current_price市值{curp_mv:.2f}) = {init_capital+cum_yuan+final['mv']-curp_mv:.2f}")
    print(f"  vs 期末净资产 {final['value']:.2f} → 差 {diff:.4f} {'✓ 一致' if abs(diff)<0.05 else '✗ 不一致'}")
    n = len(curve)
    print("曲线抽样:")
    for i in [0, n//4, n//2, 3*n//4, n-1]:
        c = curve[i]
        print(f"  {c['date']} 净资产={c['value']:.2f} 持仓={c['holdings']}笔 现金={c['cash']:.2f} 市值={c['mv']:.2f}")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({"meta": {"mode": mode, "K": K, "window": [W0, W1], "fee": "etf_def",
                        "trades_generated_at": tr.get("generated_at"),
                        "init_capital": init_capital, "peak_positions": peak,
                        "ghi_tier": GHI_TIERS.get(mode, {}).get("tier", None),
                        "formula": "净资产(日)=现金+持仓市值; 现金=初始-Σ开仓本金+Σ卖出净额(PRIN+费后盈亏); 市值=Σ未平仓份额×当日accum_nav(缺日向前取); 初始=峰值同时持仓笔数×10000"},
               "curve": curve}, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"样例输出: {OUT}")

if __name__ == "__main__":
    main()
