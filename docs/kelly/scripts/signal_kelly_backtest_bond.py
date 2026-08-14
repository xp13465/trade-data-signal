#!/usr/bin/env python3
"""债类指数纳入回测 probe(穷举对比变体,不覆盖/破坏现有主流程)。

背景(2026-08-14 任务): 现有回测 scripts/signal_kelly_backtest.py 的 ETF 宇宙来自
board_etf_map.json(_build_best_etf 只读该文件), 无债类指数映射(cgb_10y_etf 等不在)
-> 债类指数所有信号在生成阶段被 skipped_no_etf 跳过。但首页信号列表却能显示债类信号,
因为 app/queries.py `_self_etf_for` 有「ETF本体兜底」: 对 func=fund_etf_hist_sina 的指数
(cgb_10y_etf symbol=sh511260), 用该指数自身作 ETF 标的(match_method=self), 价格走 index_daily.close。

本脚本在现有回测基础上, 新增「self-ETF 兜底」穷举变体, 复用现有全部基础设施
(信号来源 SQL / 卖出模式内核 / 费率 / 每日池拆K口径), 只改「指数->ETF 标的」解析层,
跑出两份对比(不纳入债类 vs 纳入债类), 用数据回答「纳入债类后收益率是变好还是变差」。

产物(§23.5 落档,按 docs/kelly/README.md 规则:报告->analysis/ 脚本->scripts/ 数据->analysis/data/):
- 本脚本:      docs/kelly/scripts/signal_kelly_backtest_bond.py
- 对比报告:    docs/kelly/analysis/kelly-bond-inclusion-probe.md
- 数据输出:    docs/kelly/analysis/data/bond_probe_comparison.json

用法:
  python3 scripts/signal_kelly_backtest_bond.py --output docs/kelly/analysis/data/bond_probe_comparison.json

注意: 本脚本不写现网 signal_kelly_trades.json / signal_kelly_backtest.json(不覆盖线上产物),
只输出独立的 bond_probe_comparison.json; 不修改现有 signal_kelly_etf_freeze.json(用独立临时 freeze,
避免污染现网已固化成交)。
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))  # trade/scripts/
ROOT = os.path.dirname(SCRIPT_DIR)                        # trade/

sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, ROOT)

import signal_kelly_backtest as S  # noqa: E402  (复用现有全部基础设施)
from app.db import get_conn  # noqa: E402

SELF_ETF_FUNC = "fund_etf_hist_sina"  # indicators.yaml func, 首页 _self_etf_for 判定


# ── self-ETF 识别: 与 app/queries.py _self_etf_for 同源 ──────────────────────
def _load_self_etf_map():
    """读 config/indicators.yaml, 找出所有 func=fund_etf_hist_sina 的指数(首页 self-ETF 兜底同款)。

    返回 {index_id: {"code": etf_code, "name": name}}。symbol 形如 sh511260 -> code 511260。
    """
    import yaml
    cfg_path = os.path.join(ROOT, "config", "indicators.yaml")
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    self_map = {}
    for item in (cfg or {}).get("indices", []):
        if item.get("func") == SELF_ETF_FUNC and item.get("symbol"):
            sym = item["symbol"]
            code = sym[2:] if sym[:2] in ("sh", "sz", "bj") else sym
            self_map[item["id"]] = {"code": code, "name": item.get("name") or code}
    return self_map


def _load_index_close_price(index_ids):
    """批量加载 index_daily.close 价格(self-ETF 价格源, 与首页 _enrich_etfs_since_return 同源)。

    返回 {index_id: {date: close}} + {index_id: [sorted_dates]}。
    """
    result = {i: {} for i in index_ids}
    sdates = {i: [] for i in index_ids}
    if not index_ids:
        return result, sdates
    conn = get_conn()
    try:
        placeholders = ",".join("?" * len(index_ids))
        rows = conn.execute(
            f"SELECT index_id, date, close FROM index_daily "
            f"WHERE index_id IN ({placeholders}) AND close IS NOT NULL "
            f"ORDER BY index_id, date",
            list(index_ids),
        ).fetchall()
        for iid, date, close in rows:
            result[iid][date] = close
    finally:
        conn.close()
    for i in index_ids:
        sdates[i] = sorted(result[i].keys())
    return result, sdates


def _compute_per_universe(buy_rows, best_etf, self_map, signal_stats, market_map,
                          market_state, market_dates, sell_timeline, today_str,
                          etf_price_map, etf_sdates_map, self_price_map, self_sdates_map,
                          with_self_etf):
    """在指定宇宙(是否纳入 self-ETF)下跑完整信号分类 + 全模式回测。

    返回 (quadrants, skipped 明细)。
    quadrants[quad_key][mode_key] = [trade,...] (与现有 compute() 同构)。
    """
    quadrants = {qk: {mk: [] for mk in S.SELL_MODES} for qk in S.QUADRANT_META}
    skipped_no_etf = skipped_no_score = skipped_no_price = 0
    classified = 0
    bond_entered = 0      # 进入回测的 self-ETF(债类)信号数
    bond_no_price = 0     # self-ETF 信号但无价格
    bond_total = 0        # self-ETF 买信号总数

    etf_quad_map = {"strong": "strong", "related": "related", "approx": "approx", "none": "has_track"}

    for date, iid, sig in buy_rows:
        be = best_etf.get(iid)
        is_self = False
        if not be and with_self_etf and iid in self_map:
            # self-ETF 兜底(首页同款): 用该指数自身作 ETF 标的
            be = {"code": self_map[iid]["code"], "name": self_map[iid]["name"],
                  "track_tier": "none", "track_score": None, "match_method": "self",
                  "track_low_confidence": None}
            is_self = True
            bond_total += 1
        if not be:
            skipped_no_etf += 1
            continue

        etf_code = be["code"]
        tier = be["track_tier"]

        # 信号评级(按 signal_stats 10d score)
        stats_entry = signal_stats.get(iid, {}).get(sig, {})
        score_10d = stats_entry.get("10d", {}).get("score") if isinstance(stats_entry, dict) else None
        if score_10d is None:
            skipped_no_score += 1
            if is_self:
                bond_total -= 1  # 无评级, 不进入债券回测统计口径
            continue

        if score_10d >= S.RATING_HIGH:
            rating = "high"
        elif score_10d >= S.RATING_MID:
            rating = "mid"
        else:
            rating = "low"

        etf_quad = etf_quad_map.get(tier)

        market = market_map.get(iid)
        if market in S.A_STOCK_MARKETS:
            ms = S._is_market_bull(date, market_state, market_dates)
        else:
            ms = True

        # 价格源: self-ETF 用 index_daily.close, 其余用 etf_daily.accum_nav(一次性批量加载, 非逐笔查)
        if is_self:
            prices = self_price_map.get(iid, {})
            sdates = self_sdates_map.get(iid, [])
        else:
            prices = etf_price_map.get(etf_code, {})
            sdates = etf_sdates_map.get(etf_code, [])

        sell_signals = sell_timeline.get(iid, [])
        any_valid = False
        for mode_key, mode_def in S.SELL_MODES.items():
            result = S._backtest_one(
                date, prices, sdates, etf_code, be["name"], mode_def["stop_profit"],
                index_id=iid, signal=sig, track_tier=be.get("track_tier"),
                track_score=be.get("track_score"), match_method=be.get("match_method"),
                track_low_confidence=be.get("track_low_confidence"),
                today=today_str, hold_days=mode_def["hold_days"], market_state=ms, rating=rating,
                sell_mode=mode_key, sell_signals=sell_signals,
            )
            if result is None:
                continue
            any_valid = True
            quadrants[f"rating_{rating}"][mode_key].append(result)
            if etf_quad:
                quadrants[f"etf_{etf_quad}"][mode_key].append(result)
            sig_quad = S.SIG_QUAD_MAP.get(sig)
            if sig_quad:
                quadrants[sig_quad][mode_key].append(result)
            mkt_quad = S.MARKET_QUAD_MAP.get(market)
            if mkt_quad:
                quadrants[mkt_quad][mode_key].append(result)
            if is_self:
                bond_entered += 1

        if any_valid:
            classified += 1
        elif is_self:
            bond_no_price += 1

    return quadrants, {
        "skipped_no_etf": skipped_no_etf,
        "skipped_no_score": skipped_no_score,
        "skipped_no_price": skipped_no_price,
        "classified": classified,
        "self_etf_bond": {"total_signals": bond_total, "entered": bond_entered,
                          "no_price": bond_no_price},
    }


def main():
    parser = argparse.ArgumentParser(description="债类指数纳入回测 probe(穷举对比)")
    parser.add_argument("--output", default=os.path.join(ROOT, "docs", "kelly", "analysis", "data",
                                                         "bond_probe_comparison.json"))
    args = parser.parse_args()

    today = datetime.now()
    S.PERIODS["y1"]["cutoff"] = (today - timedelta(days=365)).strftime("%Y%m%d")
    S.PERIODS["y3"]["cutoff"] = (today - timedelta(days=365 * 3)).strftime("%Y%m%d")
    S.PERIODS["y5"]["cutoff"] = (today - timedelta(days=365 * 5)).strftime("%Y%m%d")
    S.PERIODS["y10"]["cutoff"] = (today - timedelta(days=365 * 10)).strftime("%Y%m%d")

    print("=" * 60)
    print("债类指数纳入回测 probe")
    print("=" * 60)

    # 加载数据(与现有 compute() 同源)
    signal_stats = S._load_signal_stats()
    etf_map = S._load_board_etf_map()
    best_etf = S._build_best_etf(etf_map)
    print(f"board_etf_map best 指数数: {len(best_etf)}")
    self_map = _load_self_etf_map()
    print(f"self-ETF 指数(self=index 即 ETF): {self_map}")
    market_map = S._load_market_map()

    conn = get_conn()
    buy_rows = conn.execute(
        f"SELECT date, index_id, signal FROM signal_daily "
        f"WHERE signal IN ({','.join('?' * len(S.BUY_SIGNALS))}) ORDER BY date",
        S.BUY_SIGNALS,
    ).fetchall()
    sell_rows = conn.execute(
        "SELECT date, index_id, signal FROM signal_daily "
        "WHERE signal IN ('sell','sell_stop_loss') ORDER BY index_id, date"
    ).fetchall()
    sell_timeline = {}
    for _d, _iid, _sig in sell_rows:
        sell_timeline.setdefault(_iid, []).append((_d, _sig))
    market_state, market_dates = S._load_market_state(conn)
    conn.close()
    print(f"买信号总数: {len(buy_rows)}")

    # 一次性批量加载所有所需价格(不逐笔查 DB)
    # ETF 价格: 全部 best ETF(两宇宙共用同一价格面,保证公平可比)
    all_etf_codes = {b["code"] for b in best_etf.values()}
    print(f"-> 批量加载 {len(all_etf_codes)} 只 best ETF 的 accum_nav ...", flush=True)
    etf_price_map, etf_sdates_map = S._batch_load_etf_prices(all_etf_codes)
    total_price_rows = sum(len(v) for v in etf_price_map.values())
    print(f"   {total_price_rows} 行 ETF 价格数据")

    # self-ETF 价格: index_daily.close
    self_indexes = list(self_map.keys())
    print(f"-> 批量加载 {len(self_indexes)} 个 self-ETF 指数的 index_daily.close ...", flush=True)
    self_price_map, self_sdates_map = _load_index_close_price(self_indexes)
    for iid in self_indexes:
        print(f"   self-ETF {iid}({self_map[iid]['code']}): {len(self_price_map[iid])} 行 close "
              f"({self_sdates_map[iid][0]}-{self_sdates_map[iid][-1] if self_sdates_map[iid] else '无'})")

    # 全局最新数据日: 用所有 best ETF 价格的最大日期(与现有脚本同源口径)
    today_str = max((ds[-1] for ds in etf_sdates_map.values() if ds), default=None)
    print(f"全局最新数据日 today={today_str}")

    # ── 宇宙1: 现状(不纳入 self-ETF 债类) ──
    print("\n--- 宇宙1: 现状(不纳入 self-ETF 债类) ---")
    quads_base, skip_base = _compute_per_universe(
        buy_rows, best_etf, self_map, signal_stats, market_map,
        market_state, market_dates, sell_timeline, today_str,
        etf_price_map, etf_sdates_map, self_price_map, self_sdates_map, with_self_etf=False)

    # ── 宇宙2: 纳入 self-ETF(债类) ──
    print("\n--- 宇宙2: 纳入 self-ETF(债类) ---")
    quads_bond, skip_bond = _compute_per_universe(
        buy_rows, best_etf, self_map, signal_stats, market_map,
        market_state, market_dates, sell_timeline, today_str,
        etf_price_map, etf_sdates_map, self_price_map, self_sdates_map, with_self_etf=True)

    print("\n跳过统计(现状 vs 纳入):")
    for k in ["skipped_no_etf", "skipped_no_score", "skipped_no_price", "classified"]:
        print(f"  {k}: {skip_base[k]} -> {skip_bond[k]}")
    print(f"  self-ETF 债类信号: {skip_bond['self_etf_bond']}")

    # ── 聚合统计对比(按卖出模式, all 周期) ──
    comparison = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "universe": {
            "baseline": "现状(不纳入 self-ETF 债类, ETF宇宙=board_etf_map)",
            "bond_probe": "纳入 self-ETF(首页同款兜底, cgb_10y_etf 等 func=fund_etf_hist_sina 指数用自身作ETF)",
        },
        "self_etf_map": self_map,
        "bond_detail": skip_bond["self_etf_bond"],
        "skipped": {"baseline": {k: v for k, v in skip_base.items() if k != "self_etf_bond"},
                    "bond_probe": {k: v for k, v in skip_bond.items() if k != "self_etf_bond"}},
        "by_mode": {},
        "by_signal": {},
        "bond_only": {},
        "period_cutoffs": {k: v["cutoff"] for k, v in S.PERIODS.items()},
    }

    # 逐卖出模式对比(全体有 score 信号: rating_high+mid+low 三象限合计, 与现有口径同)
    for mode_key in S.SELL_MODES:
        base_trades = (quads_base["rating_high"][mode_key]
                       + quads_base["rating_mid"][mode_key]
                       + quads_base["rating_low"][mode_key])
        bond_trades = (quads_bond["rating_high"][mode_key]
                       + quads_bond["rating_mid"][mode_key]
                       + quads_bond["rating_low"][mode_key])
        # 债类单独: 只有 bond_probe 宇宙才有 self-ETF 债类交易; 且只取 match_method=self
        bond_only_trades = [t for t in bond_trades if t.get("match_method") == "self"]
        comparison["by_mode"][mode_key] = {
            "label": S.SELL_MODES[mode_key]["label"],
            "baseline": S._compute_stats(base_trades, "all"),
            "bond_probe": S._compute_stats(bond_trades, "all"),
            "bond_only": S._compute_stats(bond_only_trades, "all"),
        }
        comparison["bond_only"][mode_key] = {
            "n": len(bond_only_trades),
            "total_profit": round(sum(t["profit"] for t in bond_only_trades), 4),
            "total_invest": len(bond_only_trades) * S.BUY_AMOUNT,
            "total_return_pct": round(sum(t["profit"] for t in bond_only_trades)
                                      / (len(bond_only_trades) * S.BUY_AMOUNT) * 100, 4)
                                if bond_only_trades else 0,
            "win_rate": round(sum(1 for t in bond_only_trades if t["profit"] > 0) / len(bond_only_trades), 4)
                        if bond_only_trades else 0,
            "mean_return": round(sum(t["return_pct"] for t in bond_only_trades) / len(bond_only_trades), 4)
                           if bond_only_trades else 0,
            "signal_count": len(set(t["signal_date"] for t in bond_only_trades)),
        }

    # 逐信号类型对比(all 周期, 覆盖短/中长模式)
    for sig in S.BUY_SIGNALS:
        quad_key = S.SIG_QUAD_MAP[sig]
        comparison["by_signal"][sig] = {}
        for mode_key in ["A", "F", "G", "H", "I"]:
            base_t = quads_base[quad_key][mode_key]
            bond_t = quads_bond[quad_key][mode_key]
            bond_only_t = [t for t in bond_t if t.get("match_method") == "self"]
            comparison["by_signal"][sig][mode_key] = {
                "baseline": S._compute_stats(base_t, "all"),
                "bond_probe": S._compute_stats(bond_t, "all"),
                "bond_only": S._compute_stats(bond_only_t, "all"),
            }

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(comparison, f, ensure_ascii=False, indent=2)
    print(f"\n✓ 对比输出: {args.output}")

    # 打印关键对比表(all 周期)
    print("\n=== 对比表(全体有score信号, all周期) ===")
    print(f"{'模式':<6} {'基线n':>7} {'纳入n':>7} {'债类n':>6} | {'基线净利':>9} {'纳入净利':>9} | {'基线胜率':>8} {'纳入胜率':>8} | {'债类胜率':>8}")
    for mode_key in S.SELL_MODES:
        row = comparison["by_mode"][mode_key]
        b, p, bo = row["baseline"], row["bond_probe"], row["bond_only"]
        print(f"{S.SELL_MODES[mode_key]['label']:<6} {b['n']:>7d} {p['n']:>7d} {bo['n']:>6d} | "
              f"{b['total_profit']:>9.0f} {p['total_profit']:>9.0f} | "
              f"{b['win_rate']*100:>7.1f}% {p['win_rate']*100:>7.1f}% | {bo['win_rate']*100:>7.1f}%")


if __name__ == "__main__":
    main()
