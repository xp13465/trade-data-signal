#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全信号「至今 vs N交易日窗」对错判定口径对比(#46 调研,2026-08-25)
=================================================================
目的:
  用户拍板=全站信号对错判定改「到期冻结 N=15 交易日窗」(不满15日用至今暂计,
  满15日用第15日收盘定案;band_hold 中性不计)。本脚本重算 至今/5/7/10/15 四种窗长
  下七类信号(buy/buy_aux/buy_special/buy_backup/sell/sell_stop_loss/band_sell)的对错,
  产出对比矩阵+翻转分析(卖侧V回来被冤枉比例)+买入虚高水分(30日窗口高估多少)+
  band_sell 按年分解+V型占比简评+数据缺口核查+ETF价对照,支撑窗长选型与影响面评估。

数据源(两切片不同源,均诚实标注):
  - 「近30交易日」切片 = 线上 overview.json signals_today items(用户实际看到的展示位,
    data/overview-live-20260824.json 快照,515条/30信号日/20260714~20260824)。
    ⚠️ 不用本地 sentiment.db 主库: 主库与线上镜像库不同步(memory export-syspath-rootcause,
    本次实测主库同窗口止损卖90条 vs 线上65条), 以展示位为准。
  - 「全史」切片       = 本地 sentiment.db signal_daily 全量(19910205~20260821, 60749条警示+买类)。
    历史段经 500/500 抽全量核验与线上固化 close 一致(仅8/24当日价两边都无或仅线上有)。
  - 价格序列           = sentiment.db index_daily.close(非 g. 标的, queries.py _load_close_map 同源);
    g.* -> daily_metric.value。历史段与线上 100% 一致(本脚本作者已验),"至今端"债类线上
    较本地新1个交易日(8/24), 对已到期定案样本零影响。

口径定义:
  - 分类 = reason 含「波段减仓」-> band_sell(app.js _calcSignalAccuracy 同款), 否则按 signal;
    band_hold 中性不计入(2026-08-24 用户定)。
  - 至今口径(现状): ret=(该标的序列最新收盘-信号日收盘)/信号日收盘*100; 今日新信号(date==最新
    信号日)或序列未超前信号日 -> 未结算(复刻 queries.py L1189-1198)。
  - Na「严格N日窗」(对照): 信号日在标的自身交易日序列位置 i, i+N 存在才结算:
    ret_N=(close[seq[i+N]]-close[T])/close[T]*100; 否则未结算不计。
  - Nb「实施N日窗」(用户拍板机制): 满 N 日 -> 第 N 日收盘定案(值同 Na);
    未满 N 日 -> 暂计至今值(今日新信号仍未结算)。
  - 对错: 看空三类 ret<0=对/>0=错/=0不计; 买四类反向(ret>0=对)。
  - 翻转分析(卖侧, 已定案子集): 至今判错(ret>=0) 但 N 日窗 ret<0 的比例 = V回来被冤枉比例。
  - 虚高水分(买侧, 已定案子集): 至今判对(ret>0) 但 N 日窗 ret<=0 的比例 = 窗口拉长的水分。
  - V 型简评(band_sell): 已满15日样本中, 信号后15交易日内最低价较信号价跌幅>=X% 且其后
    收盘收复至信号价的比例(X=2%/3% 两档)。

输入依赖:
  - /Users/linhuichen/code/trade/data/overview-live-20260824.json (线上快照, 由
    curl -A "Mozilla/5.0..." "https://ss.fx8.store/data/overview.json" 下载, 见报告复现段)
  - /Users/linhuichen/code/trade/data/sentiment.db (signal_daily/index_daily/daily_metric)
  - /Users/linhuichen/code/trade/data/etf_national_team.db (etf_daily.accum_nav, 仅T7)
  - /Users/linhuichen/code/trade/data/signal_kelly_etf_freeze.json (冻结top1, 仅T7)
输出:
  - ../data/warn-window-caliber-20260825.json (全部表格机器可读)
  - stdout markdown 表格

复现命令:
  python3 docs/kelly/analysis/scripts/warn_signal_window_caliber_20260825.py
数据截止: 价格/index_daily=20260821(本地); 线上快照基准日=20260824(含8/24盘中信号)
关键口径一句话: 到期冻结N日窗=信号日收盘vs第N交易日收盘(不满N日暂计至今), 看空跌=对, band_hold不计。
"""
import json
import sqlite3
import sys
from bisect import bisect_left
from collections import defaultdict

ROOT = "/Users/linhuichen/code/trade"
DB = f"{ROOT}/data/sentiment.db"
LIVE_OV = f"{ROOT}/docs/kelly/analysis/data/overview-live-20260824.json"
OUT = f"{ROOT}/docs/kelly/analysis/data/warn-window-caliber-20260825.json"

WINDOWS = [5, 7, 10, 15]
SELL_KEYS = {"sell", "sell_stop_loss", "band_sell"}
BUY_KEYS = {"buy", "buy_aux", "buy_special", "buy_backup"}
ALL_KEYS = SELL_KEYS | BUY_KEYS


def classify(signal, reason):
    if reason and "波段减仓" in reason:
        return "band_sell"
    return signal


class Px:
    """价格序列容器: dates/closes 升序; low 可选"""

    def __init__(self):
        self.d = defaultdict(list)   # iid -> dates list
        self.c = defaultdict(list)   # iid -> closes list
        self.low = defaultdict(list)

    def add_close(self, iid, d, v):
        self.d[iid].append(d)
        self.c[iid].append(v)

    def finalize(self):
        for iid in self.d:
            pairs = sorted(zip(self.d[iid], self.c[iid]))
            self.d[iid] = [x[0] for x in pairs]
            self.c[iid] = [x[1] for x in pairs]
        for iid in self.low:
            pairs = sorted(self.low[iid])
            self.low[iid] = ([x[0] for x in pairs], [x[1] for x in pairs])

    def get(self, iid):
        if iid not in self.d or not self.d[iid]:
            return None
        return self.d[iid], self.c[iid]


def load_px(conn):
    px = Px()
    for iid, d, c in conn.execute(
        "SELECT index_id, date, close FROM index_daily WHERE close IS NOT NULL"
    ):
        px.add_close(iid, d, c)
    for mid, d, v in conn.execute(
        "SELECT metric_id, date, value FROM daily_metric WHERE value IS NOT NULL"
    ):
        px.add_close("g." + mid, d, v)
    for iid, d, lo in conn.execute(
        "SELECT index_id, date, low FROM index_daily WHERE low IS NOT NULL"
    ):
        px.low[iid].append((d, lo))
    px.finalize()
    return px


def window_rets(px, iid, t):
    """-> (ret_today, settled_today, {N:(ret_strict,settled_strict)}); 信号日无价 -> (None,False,{})"""
    got = px.get(iid)
    if not got:
        return None, False, {n: (None, False) for n in WINDOWS}
    dates, closes = got
    i = bisect_left(dates, t)
    if i >= len(dates) or dates[i] != t:
        return None, False, {n: (None, False) for n in WINDOWS}
    sig_close = closes[i]
    last = len(dates) - 1
    ret_today, settled = None, False
    if last > i:
        ret_today = (closes[last] - sig_close) / sig_close * 100
        settled = True
    strict = {}
    for n in WINDOWS:
        j = i + n
        strict[n] = ((closes[j] - sig_close) / sig_close * 100, True) if j <= last else (None, False)
    return ret_today, settled, strict


def tally(sel, val_fn):
    b = {"n": 0, "t": 0, "f": 0}
    for rc in sel:
        v = val_fn(rc)
        is_buy = rc["k"] in BUY_KEYS
        if v is None:
            b["n"] += 1
        elif (v > 0) if is_buy else (v < 0):
            b["t"] += 1
        elif v != 0:
            b["f"] += 1
        else:
            b["n"] += 1
    b["settled"] = b["t"] + b["f"]
    b["pct"] = round(b["t"] / b["settled"] * 100, 1) if b["settled"] else None
    return b


def nb_val(rc, n):
    rs, ok = rc["strict"][n]
    if ok:
        return rs
    return rc["ret_today"] if rc["settled_today"] else None


def main():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    px = load_px(conn)

    # ── 人口1: 近30交易日 = 线上 overview 快照 items ──
    ov = json.load(open(LIVE_OV))
    live_items = ov.get("signals_today") or []
    latest_sig_date = max(it["date"] for it in live_items)
    recs30 = []
    for it in live_items:
        k = classify(it.get("signal"), it.get("reason"))
        if k not in ALL_KEYS:
            continue
        rt, st, strict = window_rets(px, it["index_id"], it["date"])
        recs30.append({
            "date": it["date"], "iid": it["index_id"], "k": k,
            "ret_today": rt if it["date"] != latest_sig_date else None,
            "settled_today": st and it["date"] != latest_sig_date,
            # 复刻现状 L1194: 今日信号无至今语义
            "strict": {n: ((v[0] if it["date"] != latest_sig_date else None), v[1] and it["date"] != latest_sig_date)
                       for n, v in strict.items()},
            "live_correct": it.get("since_correct"),
        })

    # ── 自检A: 近30日·至今口径必须精确复现线上快照(止损卖33/32, 纯卖8/6, 波段减仓1/18) ──
    chk = {}
    for k in ("sell", "sell_stop_loss", "band_sell"):
        sub = [r for r in recs30 if r["k"] == k]
        b = tally(sub, lambda r: r["ret_today"] if r["settled_today"] else None)
        live_t = sum(1 for r in sub if r["live_correct"] is True)
        live_f = sum(1 for r in sub if r["live_correct"] is False)
        chk[k] = {"recomputed": f"{b['t']}对/{b['f']}错/{b['n']}未结算",
                  "live": f"{live_t}对/{live_f}错",
                  "match": b["t"] == live_t and b["f"] == live_f}
    print("## 自检A: 近30交易日·至今口径 复现线上快照")
    for k, v in chk.items():
        print(f"- {k}: 重算={v['recomputed']} | 线上={v['live']} | {'PASS' if v['match'] else 'FAIL'}")

    # ── 自检B: 逐条至今方向与线上 since_correct 一致率(容忍至今端债类漂移1日) ──
    both = [r for r in recs30 if r["k"] in ALL_KEYS and r["live_correct"] is not None and r["settled_today"]]
    agree = sum(1 for r in both if r["live_correct"] == ((r["ret_today"] < 0) if r["k"] in SELL_KEYS else (r["ret_today"] > 0)))
    dis = [r for r in both if r["live_correct"] != ((r["ret_today"] < 0) if r["k"] in SELL_KEYS else (r["ret_today"] > 0))]
    print(f"- 自检B: 双方均已结算且可比 {len(both)} 条, 方向一致 {agree} ({round(agree/len(both)*100,1) if both else 0}%), "
          f"不一致 {len(dis)} 条(预期=至今端债类线上多1交易日的漂移)")

    # ── 人口2: 全史 = 本地 signal_daily ──
    rows = conn.execute(
        "SELECT date, index_id, signal, reason FROM signal_daily WHERE index_id NOT LIKE 's.%' ORDER BY date"
    ).fetchall()
    conn.close()
    recs_all = []
    for r in rows:
        k = classify(r["signal"], r["reason"])
        if k not in ALL_KEYS:
            continue
        rt, st, strict = window_rets(px, r["index_id"], r["date"])
        recs_all.append({"date": r["date"], "iid": r["index_id"], "k": k,
                         "ret_today": rt, "settled_today": st, "strict": strict})

    out = {"meta": {}, "selfcheck": {"A": chk, "B_disagree_n": len(dis),
                                     "B_disagree_detail": [{"k": r["k"], "iid": r["iid"], "date": r["date"]} for r in dis[:20]]},
           "matrix": {}, "flip": {}, "inflate": {}, "band_yearly": {}, "vshape": {}, "gap": [], "etf": {}}
    out["meta"] = {"live_snapshot_items": len(live_items), "latest_sig_date_live": latest_sig_date,
                   "n_pop30": len(recs30), "n_allhist": len(recs_all),
                   "px_last_date_index_daily_sh": (px.d.get("sh") or ["0"])[-1]}

    # ── T1 主矩阵: 七类 × 口径 × 两切片 ──
    for slice_name, sel in (("近30交易日", recs30), ("全史", recs_all)):
        for k in sorted(ALL_KEYS):
            sub = [r for r in sel if r["k"] == k]
            if not sub:
                continue
            row = {"至今": tally(sub, lambda r: r["ret_today"] if r["settled_today"] else None)}
            for n in WINDOWS:
                row[f"{n}日实施"] = tally(sub, lambda r, n=n: nb_val(r, n))
                row[f"{n}日严格"] = tally(sub, lambda r, n=n: r["strict"][n][0] if r["strict"][n][1] else None)
            out["matrix"][f"{slice_name}|{k}"] = row

    # ── T2 卖侧翻转分析(已定案 = 严格口径结算 且 至今已结算) ──
    for slice_name, sel in (("近30交易日", recs30), ("全史", recs_all)):
        for k in ("band_sell", "sell", "sell_stop_loss"):
            sub = [r for r in sel if r["k"] == k and r["settled_today"] and r["ret_today"] is not None]
            row = {}
            for n in WINDOWS:
                bothn = [r for r in sub if r["strict"][n][1]]
                wrong_today = [r for r in bothn if r["ret_today"] >= 0]
                flipped = [r for r in wrong_today if r["strict"][n][0] < 0]
                row[str(n)] = {"n_both": len(bothn), "wrong_today": len(wrong_today),
                               "flip_to_right": len(flipped),
                               "flip_pct": round(len(flipped) / len(wrong_today) * 100, 1) if wrong_today else None}
            out["flip"].setdefault(slice_name, {})[k] = row

    # ── T3 买侧虚高水分(已定案子集: 至今对 -> N日转错) ──
    for slice_name, sel in (("近30交易日", recs30), ("全史", recs_all)):
        for k in sorted(BUY_KEYS):
            sub = [r for r in sel if r["k"] == k and r["settled_today"] and r["ret_today"] is not None]
            row = {}
            for n in WINDOWS:
                bothn = [r for r in sub if r["strict"][n][1]]
                right_today = [r for r in bothn if r["ret_today"] > 0]
                turned = [r for r in right_today if r["strict"][n][0] <= 0]
                row[str(n)] = {"n_both": len(bothn), "right_today": len(right_today),
                               "turn_wrong": len(turned),
                               "inflate_pct": round(len(turned) / len(right_today) * 100, 1) if right_today else None}
            out["inflate"].setdefault(slice_name, {})[k] = row

    # ── T4 band_sell 窗长专项 + 按年分解(严格口径=已到期定案; 全史) ──
    yearly = defaultdict(lambda: defaultdict(lambda: {"n": 0, "t": 0, "f": 0}))
    for r in recs_all:
        if r["k"] != "band_sell":
            continue
        y = r["date"][:4]
        for n in WINDOWS:
            ret, ok = r["strict"][n]
            if not ok or ret == 0:
                continue
            cell = yearly[y][str(n)]
            cell["n"] += 1
            cell["t" if ret < 0 else "f"] += 1
    out["band_yearly"] = {y: {n: dict(v, pct=round(v["t"] / v["n"] * 100, 1) if v["n"] else None)
                              for n, v in vv.items()} for y, vv in sorted(yearly.items())}

    # ── T5 V 型简评(band_sell 已满15日样本) ──
    vstat = {}
    for X in (0.5, 1.0, 2.0, 3.0):
        tot = v_cnt = 0
        for r in recs_all:
            if r["k"] != "band_sell":
                continue
            got = px.get(r["iid"])
            lw = px.low.get(r["iid"])
            if not got or not lw:
                continue
            dates, closes = got
            i = bisect_left(dates, r["date"])
            if i >= len(dates) or dates[i] != r["date"] or i + 15 >= len(dates):
                continue
            sig_close = closes[i]
            ldates, llows = lw
            wdates = dates[i + 1:i + 16]
            li0 = bisect_left(ldates, wdates[0])
            seg_low = llows[li0:li0 + 15]
            drop = (sig_close - min(seg_low)) / sig_close * 100
            tot += 1
            if drop >= X:
                seg_close = closes[i + 1:i + 16]
                wl = seg_close.index(min(seg_close))
                if any(c >= sig_close for c in seg_close[wl:]):
                    v_cnt += 1
        vstat[f"X={X}%"] = {"n_full15": tot, "v_count": v_cnt,
                            "v_pct": round(v_cnt / tot * 100, 1) if tot else None}
    out["vshape"] = vstat

    # ── T6 数据缺口核查: pop30 各标的价格最新日期 vs 20260821(本地) ──
    gap_iids = sorted({r["iid"] for r in recs30})
    local_last = max((px.d.get(i) or ["0"])[-1] for i in gap_iids)
    for iid in gap_iids:
        ld = (px.d.get(iid) or ["缺失"])[-1]
        if ld != "20260821":
            out["gap"].append({"iid": iid, "local_last_price_date": ld})
    out["gap_total_iids"] = len(gap_iids)
    out["meta"]["px_last_date_local_max"] = local_last


    # ── T7 ETF 价对照(近30交易日警示类): 指数ret vs top1ETF accum_nav ret 方向一致率 ──
    # 目的=稳健性检验: 若判定基准从指数价换成 board_etf_map 映射 ETF 价, 结论方向会不会翻
    try:
        freeze = json.load(open(f"{ROOT}/data/signal_kelly_etf_freeze.json"))
        ec = sqlite3.connect(f"file:{ROOT}/data/etf_national_team.db?mode=ro", uri=True)
        es = {}
        for code, d, nav in ec.execute(
            "SELECT etf_code, date, accum_nav FROM etf_daily WHERE accum_nav IS NOT NULL ORDER BY etf_code, date"
        ):
            es.setdefault(code, []).append((d, nav))
        ec.close()
        agree = tot7 = 0
        dis_detail = []
        for it in live_items:
            k = classify(it.get("signal"), it.get("reason"))
            if k not in SELL_KEYS:
                continue
            key = f"{it['date']}|{it['index_id']}|{it['signal']}"
            etfs = it.get("etfs") or []
            code = freeze[key]["code"] if key in freeze else ((etfs or [{}])[0].get("code"))
            rt = it.get("since_return")
            if not code or code not in es or rt is None:
                continue
            edates = [x[0] for x in es[code]]
            i = bisect_left(edates, it["date"])
            j = len(edates) - 1
            if i >= len(edates) or edates[i] != it["date"] or j <= i:
                continue
            eret = (es[code][j][1] - es[code][i][1]) / es[code][i][1] * 100
            tot7 += 1
            same = (rt < 0) == (eret < 0)
            agree += same
            if not same:
                dis_detail.append({"key": key, "k": k, "idx_ret": round(rt, 2), "etf_ret": round(eret, 2)})
        out["etf"] = {"n": tot7, "agree": agree,
                      "agree_pct": round(agree / tot7 * 100, 1) if tot7 else None,
                      "disagree_n": len(dis_detail), "disagree_detail": dis_detail[:30]}
    except Exception as e:  # noqa
        out["etf"] = {"error": str(e)}

    with open(OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\nOK -> {OUT}")
    print(json.dumps(out["meta"], ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
