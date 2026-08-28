#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
入样宇宙「兜底匹配」价值审计(#deploy拦截调研,2026-08-25)
=========================================================
背景:
  deploy 被 §23.6 对称校验(check_universe_alignment.py assertion1)拦截: board_etf_map 有 34 个
  空数组指数(无正式收录跟踪 ETF), 但线上 overview 里 bj50 的 buy 信号经 queries.py L1115
  _align_home_top1_to_backtest 冻结表 prepend(data/signal_kelly_etf_freeze.json, match_method=
  holdings_overlap, track_score=3.9, 标的 159543 国证2000ETF工银)后 etfs 非空 → L1119
  _bt_in_universe 判 True; 而校验按 map 重算(bj50=[])判 False → 两边打架。
  三候选方案: A 尊重显式收录(关兜底入样) / B 兜底转正(校验补兜底逻辑) / C 给空数组配专属 ETF。
  本脚本用真实数据回答: 兜底到底有没有好处? 纠正后有什么缺点?

任务与口径:
  T1 规模画像: 34 空数组指数全史(signal_daily 19910205~20260821)buy 类信号数/占比 + 近30交易日活跃。
  T2A trades 实证: signal_kelly_trades.json 全史中 bj50 的 738 笔 vs 同期(>=20231121)宇宙内其余交易,
      对比胜率/平均单笔收益率(return_pct)/总盈亏(profit 元)。
  T2B 10日窗到期冻结对错(warn_signal_window_caliber_20260825 同款 Na 口径):
      F组=34空数组指数 buy 类信号; U组=board_etf_map 非空数组 key(正式收录宇宙)的 buy 类信号;
      信号日在该指数 index_daily 序列位置 i, i+10 存在才结算 ret=(c[i+10]-c[i])/c[i]*100;
      买类 ret>0=对。输出总体+按指数+按年分解。
  T2C track_score 分布: F 组唯一有实际兜底分的是 bj50(冻结表), 检验 <30 极弱档占比。
  T3 AI建议视角: trade-data 镜像 overview(515条 signals_today)复刻前端 kept 排序
      (app.js L4487 _posCapSortedFn: top1 track_score DESC→评级→信号类型), 看 bj50 在各信号日的位次。
  T4/T5(跟踪度抽查+方案C清单)在报告中以 WebSearch+配置证据补充, 不在本脚本。

输入依赖:
  - /Users/linhuichen/code/trade/data/sentiment.db (signal_daily / index_daily)
  - /Users/linhuichen/code/trade/data/board_etf_map.json (34空数组判定)
  - /Users/linhuichen/code/trade/data/signal_kelly_trades.json (回测全史交易)
  - /Users/linhuichen/code/trade-data/static-site/data/overview.json (线上镜像快照, deploy拦截现场同源)

输出:
  - ../data/universe-fallback-audit-20260825.json (机器可读全表)
  - stdout markdown 表格

复现命令:
  python3 docs/kelly/analysis/scripts/universe_fallback_value_audit.py

数据截止: sentiment.db signal_daily/index_daily 至 20260821; trades generated_at 见 JSON;
镜像 overview date=20260824。测试基准=v1.1.5(NEW14 默认); 本审计为统计口径评估非择时回测,
防前视不适用, 但全部窗收益只用信号日及之后数据(c[i]→c[i+10]), 无未来信息泄漏。
关键口径一句话: F组兜底入样=map空数组指数的买类信号; 对错=10交易日窗到期冻结(ret>0=对);
U组对照=map 正式收录(非空数组)指数的买类信号。
"""
import json
import sqlite3
import sys
from bisect import bisect_left
from collections import defaultdict, Counter

ROOT = "/Users/linhuichen/code/trade"
DB = f"{ROOT}/data/sentiment.db"
MAP_PATH = f"{ROOT}/data/board_etf_map.json"
TRADES_PATH = f"{ROOT}/data/signal_kelly_trades.json"
LIVE_OV = "/Users/linhuichen/code/trade-data/static-site/data/overview.json"
OUT = f"{ROOT}/docs/kelly/analysis/data/universe-fallback-audit-20260825.json"

BUY_KEYS = {"buy", "buy_aux", "buy_special", "buy_backup"}
WINDOW = 10


def load_prices(conn):
    px = {}
    for iid, in conn.execute("SELECT DISTINCT index_id FROM index_daily").fetchall():
        rows = conn.execute(
            "SELECT date, close FROM index_daily WHERE index_id=? AND close IS NOT NULL ORDER BY date",
            (iid,)).fetchall()
        if rows:
            px[iid] = ([r[0] for r in rows], [r[1] for r in rows])
    return px


def window_ret(dates, closes, sig_date):
    """Na 严格10日窗: 位置 i+N 存在才结算; 返回 ret 或 None(未结算)."""
    i = bisect_left(dates, sig_date)
    if i >= len(dates) or dates[i] != sig_date:
        # 信号日无收盘价(停发/缺采): 找信号日之后第一个有价的日期为基准? warn脚本口径=无则不算.
        return None
    j = i + WINDOW
    if j >= len(dates):
        return None
    return (closes[j] - closes[i]) / closes[i] * 100


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    m = json.load(open(MAP_PATH))
    empty = sorted(k for k, v in m.items() if not v)
    universe = sorted(k for k, v in m.items() if v)
    out = {"generated_by": __file__, "window": WINDOW}

    # ---------- T1 规模画像 ----------
    rows = conn.execute("SELECT date,index_id,signal FROM signal_daily").fetchall()
    f_sigs, u_cnt = [], 0
    for r in rows:
        if r["signal"] not in BUY_KEYS:
            continue
        if r["index_id"] in set(empty):
            f_sigs.append((r["date"], r["index_id"], r["signal"]))
        elif r["index_id"] in set(universe):
            u_cnt += 1
    per_idx = Counter(x[1] for x in f_sigs)
    recent_dates = sorted(set(r["date"] for r in conn.execute(
        "SELECT DISTINCT date FROM signal_daily ORDER BY date DESC LIMIT 30")))
    rec = Counter(x[1] for x in f_sigs if x[0] >= recent_dates[0])
    out["t1"] = {
        "empty_indices": len(empty), "hit_indices": len(per_idx),
        "f_total_buy": len(f_sigs), "u_total_buy": u_cnt,
        "f_share_pct": round(len(f_sigs) / (len(f_sigs) + u_cnt) * 100, 2),
        "per_index": dict(per_idx.most_common()),
        "recent30_range": [recent_dates[0], recent_dates[-1]],
        "recent30_total": sum(rec.values()), "recent30_per_index": dict(rec.most_common()),
    }

    # ---------- T2B 10日窗到期冻结 ----------
    px = load_prices(conn)
    f_stats = defaultdict(lambda: [0, 0, 0.0])  # n, wins, sum_ret
    u_stats = [0, 0, 0.0]
    f_year = defaultdict(lambda: [0, 0])
    miss_price = Counter()
    for d, iid, sig in f_sigs:
        p = px.get(iid)
        if p is None:
            miss_price[iid] += 1
            continue
        ret = window_ret(p[0], p[1], d)
        if ret is None:
            continue
        st = f_stats[iid]
        st[0] += 1; st[1] += ret > 0; st[2] += ret
        y = f_year[d[:4]]
        y[0] += 1; y[1] += ret > 0
        u_stats_placeholder = None
    # U 组抽样算窗(全量 35k 条也可承受, 直接全量)
    for r in rows:
        if r["signal"] not in BUY_KEYS or r["index_id"] not in set(universe):
            continue
        p = px.get(r["index_id"])
        if p is None:
            continue
        ret = window_ret(p[0], p[1], r["date"])
        if ret is None:
            continue
        u_stats[0] += 1; u_stats[1] += ret > 0; u_stats[2] += ret
    tot_f = [sum(v[0] for v in f_stats.values()), sum(v[1] for v in f_stats.values()),
             sum(v[2] for v in f_stats.values())]
    out["t2b"] = {
        "f_settled": tot_f[0], "f_winrate_pct": round(tot_f[1] / tot_f[0] * 100, 2),
        "f_avg_ret": round(tot_f[2] / tot_f[0], 3),
        "u_settled": u_stats[0], "u_winrate_pct": round(u_stats[1] / u_stats[0] * 100, 2),
        "u_avg_ret": round(u_stats[2] / u_stats[0], 3),
        "per_index": {k: {"n": v[0], "winrate_pct": round(v[1] / v[0] * 100, 2),
                          "avg_ret": round(v[2] / v[0], 3)}
                      for k, v in sorted(f_stats.items(), key=lambda kv: -kv[1][0])},
        "per_year": {y: {"n": v[0], "winrate_pct": round(v[1] / v[0] * 100, 2)}
                     for y, v in sorted(f_year.items())},
        "no_price_skipped": dict(miss_price),
    }

    # ---------- T2A trades 实证 ----------
    t = json.load(open(TRADES_PATH))
    q = t["quadrants"]
    bj, other = [], []
    cut = "20231121"
    for qk, qv in q.items():
        for pk, pv in qv.items():
            for tr in pv:
                if tr[1] == "bj50":
                    bj.append(tr)
                elif tr[0] >= cut:
                    other.append(tr)
    def agg(trs):
        n = len(trs)
        if not n:
            return None
        win = sum(1 for x in trs if x[15] > 0)
        return {"n": n, "winrate_pct": round(win / n * 100, 2),
                "avg_ret_pct": round(sum(x[15] for x in trs) / n, 3),
                "total_profit_yuan": round(sum(x[14] for x in trs), 0)}
    out["t2a"] = {"bj50_all": agg(bj), "universe_same_period": agg(other),
                  "trades_generated_at": t.get("generated_at")}

    # ---------- T2C track_score ----------
    fz = json.load(open(f"{ROOT}/data/signal_kelly_etf_freeze.json"))
    bj_ts = [v.get("track_score") for k, v in fz.items() if "|bj50|" in k]
    weak = sum(1 for s in bj_ts if s is not None and s < 30)
    out["t2c"] = {"bj50_freeze_keys": len(bj_ts), "score_lt30": weak,
                  "score_values_sample": sorted(set(s for s in bj_ts if s is not None))}

    # ---------- T3 kept 位次(镜像 overview) ----------
    ov = json.load(open(LIVE_OV))
    st = ov["signals_today"]
    byd = defaultdict(list)
    for s in st:
        byd[s["date"]].append(s)
    pos = []
    for d, g in sorted(byd.items()):
        grp = [s for s in g if s["signal"] in BUY_KEYS and s.get("_bt_in_universe") is not False]
        def ts(s):
            sc = [e.get("track_score") for e in (s.get("etfs") or []) if e.get("track_score") is not None]
            return max(sc) if sc else -1
        grp.sort(key=lambda s: -ts(s))
        for i, s in enumerate(grp):
            if s["index_id"] in set(empty):
                pos.append({"date": d, "index_id": s["index_id"],
                            "rank": i + 1, "n_cand": len(grp)})
    out["t3"] = {"overview_signals_today": len(st), "fallback_rank_in_day": pos,
                 "ever_topK4": sum(1 for p in pos if p["rank"] <= 4)}

    json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1, default=str)

    # ---------- stdout markdown ----------
    print("## T1 规模画像")
    print(f"- 34空数组指数中产生过buy类信号的: {out['t1']['hit_indices']}/34, 合计 {len(f_sigs)} 条 "
          f"(占全史buy类 {out['t1']['f_share_pct']}%)")
    print(f"- 近30交易日({out['t1']['recent30_range'][0]}~{out['t1']['recent30_range'][1]}): {out['t1']['recent30_total']} 条")
    print("\n## T2A trades 实证(bj50 738笔 vs 宇宙同期)")
    print(f"- bj50 全史: {out['t2a']['bj50_all']}")
    print(f"- 宇宙同期: {out['t2a']['universe_same_period']}")
    print("\n## T2B 10日窗到期冻结")
    print(f"- F组(兜底): n={out['t2b']['f_settled']} 胜率={out['t2b']['f_winrate_pct']}% 均收益={out['t2b']['f_avg_ret']}%")
    print(f"- U组(正式收录): n={out['t2b']['u_settled']} 胜率={out['t2b']['u_winrate_pct']}% 均收益={out['t2b']['u_avg_ret']}%")
    print("- F组按年:", json.dumps(out["t2b"]["per_year"], ensure_ascii=False))
    print("\n## T2C track_score")
    print(f"- bj50 冻结键 {out['t2c']['bj50_freeze_keys']} 个, score<30 极弱档 {out['t2c']['score_lt30']} 个 "
          f"({round(out['t2c']['score_lt30']/max(out['t2c']['bj50_freeze_keys'],1)*100)}%), 取值={out['t2c']['score_values_sample']}")
    print("\n## T3 AI建议kept位次(近30信号日)")
    for p in out["t3"]["fallback_rank_in_day"]:
        print(f"- {p['date']} {p['index_id']}: 第{p['rank']}/{p['n_cand']}位")
    print(f"\n输出已写 {OUT}")


if __name__ == "__main__":
    main()
