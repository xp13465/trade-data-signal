#!/usr/bin/env python3
"""信号凯利回测 - 6 象限 × 4 卖出模式 × 3 周期。

对每条买信号(buy/buy_aux/buy_special/buy_backup),买入该信号对应指数的 track_score
第一名 ETF(1000 元,含费率),按 4 种卖出模式(固定 10 天 / 3% / 5% / 7% 止盈或满 10 天)
各自卖出,统计胜率/盈亏比/凯利 f*。

6 并列象限(非交叉,同一信号可同时归两组):
  - 评级 3 象限: rating_high/mid/low (按 signal_stats 10d score ≥0.75/≥0.55/<0.55)
  - ETF 归类 3 象限: etf_strong/related/approx (按第一名 ETF track_tier)
  - track_tier=none/no_score 的信号不纳入 ETF 归类,但纳入评级(若有 score)

3 周期: y1(近 1 年) / y3(近 3 年) / all(全部)

用法:
  python3 scripts/signal_kelly_backtest.py                     # 默认输出 static-site/data/
  python3 scripts/signal_kelly_backtest.py --output PATH.json  # 指定输出路径
"""
import argparse
import bisect
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# ── 路径 ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))  # trade/scripts/
ROOT = os.path.dirname(SCRIPT_DIR)                        # trade/

# 复用 simulate_trade 的费率函数 + ETF 价格加载
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, ROOT)
from simulate_trade import (  # noqa: E402
    _buy_with_fees, _sell_with_fees, _is_sh_etf,
    COMMISSION_RATE, SLIPPAGE, MIN_COMMISSION, TRANSFER_FEE_RATE_SH,
)
from app.db import get_conn  # noqa: E402

# ── 常量 ──────────────────────────────────────────────────────────────────────
BUY_AMOUNT = 1000          # 每笔买入金额(元)
HOLD_DAYS = 10             # 最大持有交易日
BUY_SIGNALS = ("buy", "buy_aux", "buy_special", "buy_backup")

SELL_MODES = {
    "A": {"label": "固定10天", "stop_profit": None},
    "B": {"label": "3%止盈", "stop_profit": 0.03},
    "C": {"label": "5%止盈", "stop_profit": 0.05},
    "D": {"label": "7%止盈", "stop_profit": 0.07},
}

PERIODS = {
    "y1":  {"label": "近1年", "cutoff": None},  # 运行时动态算
    "y3":  {"label": "近3年", "cutoff": None},
    "all": {"label": "全部", "cutoff": "0"},
}

RATING_HIGH = 0.75
RATING_MID = 0.55

QUADRANT_META = {
    "rating_high":  {"label": "高评级信号", "desc": "技术参考点综合把握度 score≥0.75"},
    "rating_mid":   {"label": "中评级信号", "desc": "0.55≤score<0.75"},
    "rating_low":   {"label": "低评级信号", "desc": "score<0.55"},
    "etf_strong":   {"label": "强关联ETF", "desc": "track_tier=strong (track_score≥80)"},
    "etf_related":  {"label": "相关ETF",   "desc": "track_tier=related (70-79)"},
    "etf_approx":   {"label": "近似ETF",   "desc": "track_tier=approx (50-69)"},
}


# ── 数据加载 ──────────────────────────────────────────────────────────────────

def _load_signal_stats():
    """读 signal_stats.json: 优先 static-site/data/(export 最新版), 回退 data/(根目录)。"""
    for p in [
        os.path.join(ROOT, "static-site", "data", "signal_stats.json"),
        os.path.join(ROOT, "data", "signal_stats.json"),
    ]:
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError("signal_stats.json 未找到 (static-site/data/ 和 data/ 都没有)")


def _load_board_etf_map():
    """读 board_etf_map.json (data/ 根目录)。"""
    p = os.path.join(ROOT, "data", "board_etf_map.json")
    if not os.path.exists(p):
        raise FileNotFoundError(f"board_etf_map.json 未找到: {p}")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _build_best_etf(etf_map):
    """每指数取 track_score 最高的 ETF 作为该信号匹配 ETF。

    返回 {index_id: {"code": etf_code, "track_tier": tier}}。
    无 track_score 的指数不纳入(调用方跳过)。
    """
    best = {}
    for iid, cands in etf_map.items():
        if iid == "_meta" or not isinstance(cands, list):
            continue
        scored = [c for c in cands if c.get("track_score") is not None]
        if not scored:
            continue
        top = max(scored, key=lambda c: c["track_score"])
        best[iid] = {"code": top["code"], "track_tier": top.get("track_tier", "none")}
    return best


def _get_etf_db_path():
    """ETF DB 路径: 优先 trade-data/data/etf_national_team.db(主库), 回退 trade/data/。"""
    main = os.path.join(os.path.dirname(ROOT), "trade-data", "data", "etf_national_team.db")
    if os.path.exists(main):
        return main
    return os.path.join(ROOT, "data", "etf_national_team.db")


def _batch_load_etf_prices(etf_codes):
    """批量加载 ETF 价格(accum_nav), 返回 {etf_code: {date: accum_nav}} + {etf_code: [sorted_dates]}。

    单次 SQL 查询所有需要的 ETF, 比 per-ETF 查询快 ~100x。
    """
    if not etf_codes:
        return {}, {}
    db_path = _get_etf_db_path()
    if not os.path.exists(db_path):
        print(f"  ⚠ ETF DB 不存在: {db_path}", file=sys.stderr)
        return {}, {}

    price_map = {c: {} for c in etf_codes}
    sorted_dates = {c: [] for c in etf_codes}
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        # 分批查(SQLite IN 占位符上限 999)
        codes = list(etf_codes)
        batch_size = 500
        for i in range(0, len(codes), batch_size):
            batch = codes[i:i + batch_size]
            placeholders = ",".join("?" * len(batch))
            rows = conn.execute(
                f"SELECT etf_code, date, accum_nav FROM etf_daily "
                f"WHERE etf_code IN ({placeholders}) AND accum_nav IS NOT NULL "
                f"ORDER BY etf_code, date",
                batch,
            ).fetchall()
            for code, date, nav in rows:
                price_map[code][date] = nav
    finally:
        conn.close()

    # 预排序日期列表(供 bisect 查找)
    for code in etf_codes:
        sorted_dates[code] = sorted(price_map[code].keys())

    return price_map, sorted_dates


# ── 回测 ──────────────────────────────────────────────────────────────────────

def _backtest_one(signal_date, prices, sorted_dates_list, etf_code, stop_profit):
    """单笔信号回测: 信号日买入 1000 元, 持有期内止盈或满 HOLD_DAYS 卖出。

    prices: 该 ETF 的 {date: accum_nav} 字典(已由调用方从 price_map 取出)。
    返回 dict {buy_date, sell_date, buy_price, sell_price, shares, profit, return_pct, hold_days}
    或 None(数据不足跳过)。
    """
    if not prices:
        return None

    buy_nav = prices.get(signal_date)
    if buy_nav is None or buy_nav <= 0:
        return None  # 信号日无 ETF 价格

    # 买入(含费率)
    buy_price, shares, _comm, _tf = _buy_with_fees(BUY_AMOUNT, buy_nav, etf_code)
    if shares <= 0:
        return None

    # 用 bisect 找未来 HOLD_DAYS 个交易日
    dates = sorted_dates_list
    idx = bisect.bisect_right(dates, signal_date)
    future_dates = dates[idx:idx + HOLD_DAYS]
    if len(future_dates) < HOLD_DAYS:
        return None  # 未来不足 HOLD_DAYS 天, 交易未完成

    # 模式 A: 最后一天卖出; 模式 B/C/D: 逐日检查止盈
    sell_date = future_dates[-1]  # 默认最后一天(D+10)
    if stop_profit is not None:
        for d in future_dates:
            nav = prices[d]
            unrealized = nav / buy_price - 1  # 未实现收益率(小数)
            if unrealized >= stop_profit:
                sell_date = d
                break

    sell_nav = prices[sell_date]
    sell_price, _sell_amount, _comm2, _tf2, net = _sell_with_fees(shares, sell_nav, etf_code)

    profit = net - BUY_AMOUNT
    return_pct = profit / BUY_AMOUNT * 100
    hold = future_dates.index(sell_date) + 1  # D+1=1, ..., D+10=10

    return {
        "buy_date": signal_date,
        "sell_date": sell_date,
        "buy_price": round(buy_price, 6),
        "sell_price": round(sell_price, 6),
        "shares": round(shares, 6),
        "profit": round(profit, 4),
        "return_pct": round(return_pct, 4),
        "hold_days": hold,
    }


def _compute_kelly(win_rate, pl_ratio):
    """凯利公式 f* = p - q/b, half_kelly = f*/2 * 100, tier 保守/均衡/激进。

    复用 public_fund.py 同口径: clamp f* [0,1], half_kelly [0,90]。
    """
    p = win_rate
    q = 1 - p
    b = pl_ratio if pl_ratio and pl_ratio > 0 else 0

    if b > 0:
        f_star = p - q / b
    else:
        f_star = 0.0
    f_star = max(0.0, min(1.0, f_star))

    half_kelly = f_star / 2 * 100
    half_kelly = max(0.0, min(90.0, half_kelly))

    if half_kelly < 30:
        tier = "保守"
    elif half_kelly < 60:
        tier = "均衡"
    else:
        tier = "激进"

    return round(f_star, 4), round(half_kelly, 2), tier


def _compute_stats(trades):
    """聚合统计: 胜率/盈亏比/mean_return/凯利/连胜连败等。"""
    n = len(trades)
    if n == 0:
        return {
            "n": 0, "win_count": 0, "lose_count": 0,
            "win_rate": 0, "pl_ratio": None, "mean_return": 0,
            "total_return": 0, "avg_hold_days": 0,
            "kelly_f": 0, "half_kelly": 0, "kelly_tier": "保守",
            "max_single_win": 0, "max_single_loss": 0,
            "win_streak_max": 0, "lose_streak_max": 0,
        }

    wins = [t for t in trades if t["profit"] > 0]
    losses = [t for t in trades if t["profit"] <= 0]
    win_count = len(wins)
    lose_count = len(losses)
    win_rate = win_count / n

    avg_win = sum(t["return_pct"] for t in wins) / win_count if win_count else 0.0
    avg_loss_abs = abs(sum(t["return_pct"] for t in losses) / lose_count) if lose_count else 0.0

    # 盈亏比(同 public_fund.py 边界处理)
    if lose_count > 0 and avg_loss_abs > 0:
        pl_ratio = avg_win / avg_loss_abs
    elif win_count > 0 and lose_count == 0:
        pl_ratio = 999.0  # 全胜无亏损
    else:
        pl_ratio = None  # 无胜或全零

    mean_return = sum(t["return_pct"] for t in trades) / n
    total_return = sum(t["profit"] for t in trades) / BUY_AMOUNT * 100
    avg_hold = sum(t["hold_days"] for t in trades) / n

    kelly_f, half_kelly, kelly_tier = _compute_kelly(win_rate, pl_ratio)

    # 最大单笔盈亏
    max_win = max((t["return_pct"] for t in trades), default=0)
    max_loss = min((t["return_pct"] for t in trades), default=0)

    # 连胜连败(按买入日排序)
    sorted_trades = sorted(trades, key=lambda t: t["buy_date"])
    win_streak = lose_streak = 0
    max_win_streak = max_lose_streak = 0
    for t in sorted_trades:
        if t["profit"] > 0:
            win_streak += 1
            lose_streak = 0
            max_win_streak = max(max_win_streak, win_streak)
        else:
            lose_streak += 1
            win_streak = 0
            max_lose_streak = max(max_lose_streak, lose_streak)

    return {
        "n": n,
        "win_count": win_count,
        "lose_count": lose_count,
        "win_rate": round(win_rate, 4),
        "pl_ratio": round(pl_ratio, 2) if pl_ratio is not None else None,
        "mean_return": round(mean_return, 4),
        "total_return": round(total_return, 4),
        "avg_hold_days": round(avg_hold, 2),
        "kelly_f": kelly_f,
        "half_kelly": half_kelly,
        "kelly_tier": kelly_tier,
        "max_single_win": round(max_win, 4),
        "max_single_loss": round(max_loss, 4),
        "win_streak_max": max_win_streak,
        "lose_streak_max": max_lose_streak,
    }


# ── 主流程 ────────────────────────────────────────────────────────────────────

def compute():
    """执行完整回测, 返回结果 dict。"""
    from datetime import timedelta
    today = datetime.now()
    PERIODS["y1"]["cutoff"] = (today - timedelta(days=365)).strftime("%Y%m%d")
    PERIODS["y3"]["cutoff"] = (today - timedelta(days=365 * 3)).strftime("%Y%m%d")

    # 1. 加载数据
    print("-> 加载 signal_stats.json ...", flush=True)
    signal_stats = _load_signal_stats()
    print(f"   {len(signal_stats)} 个 index_id (含 _updated_at)")

    print("-> 加载 board_etf_map.json ...", flush=True)
    etf_map = _load_board_etf_map()
    best_etf = _build_best_etf(etf_map)
    print(f"   {len(best_etf)} 个指数有 track_score 第一名 ETF")

    # 2. 读买信号
    print("-> 读 signal_daily 买信号 ...", flush=True)
    conn = get_conn()
    buy_rows = conn.execute(
        f"SELECT date, index_id, signal FROM signal_daily "
        f"WHERE signal IN ({','.join('?' * len(BUY_SIGNALS))}) ORDER BY date",
        BUY_SIGNALS,
    ).fetchall()
    conn.close()
    print(f"   {len(buy_rows)} 条买信号")

    # 3. 确定需要的 ETF 代码集合, 批量加载价格
    needed_etfs = set()
    for _date, iid, _sig in buy_rows:
        be = best_etf.get(iid)
        if be:
            needed_etfs.add(be["code"])
    print(f"-> 批量加载 {len(needed_etfs)} 只 ETF 的 accum_nav ...", flush=True)
    price_map, sorted_dates_map = _batch_load_etf_prices(needed_etfs)
    total_price_rows = sum(len(v) for v in price_map.values())
    print(f"   {total_price_rows} 行价格数据")

    # 4. 逐信号分类 + 4 模式回测
    # quadrants[quad_key][mode_key] = [trade, ...]
    quadrants = {qk: {mk: [] for mk in SELL_MODES} for qk in QUADRANT_META}
    skipped_no_etf = skipped_no_score = skipped_no_price = 0
    classified = 0

    for date, iid, sig in buy_rows:
        be = best_etf.get(iid)
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
            continue  # 无评级, 跳过(不纳入任何象限)

        if score_10d >= RATING_HIGH:
            rating = "high"
        elif score_10d >= RATING_MID:
            rating = "mid"
        else:
            rating = "low"

        # ETF 归类(只 strong/related/approx)
        etf_quad = tier if tier in ("strong", "related", "approx") else None

        # 4 模式回测
        prices = price_map.get(etf_code, {})
        sdates = sorted_dates_map.get(etf_code, [])
        any_valid = False
        for mode_key, mode_def in SELL_MODES.items():
            result = _backtest_one(date, prices, sdates, etf_code, mode_def["stop_profit"])
            if result is None:
                continue  # 数据不足(信号日无价格/未来不足10天)
            any_valid = True
            # 归入评级象限
            quadrants[f"rating_{rating}"][mode_key].append(result)
            # 归入 ETF 归类象限(如有)
            if etf_quad:
                quadrants[f"etf_{etf_quad}"][mode_key].append(result)

        if any_valid:
            classified += 1
        else:
            skipped_no_price += 1

    print(f"   分类完成: {classified} 信号有有效回测")
    print(f"   跳过: 无ETF映射={skipped_no_etf}, 无评级score={skipped_no_score}, 无ETF价格/未来不足={skipped_no_price}")

    # 5. 按周期聚合统计
    output = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "config": {
            "buy_amount": BUY_AMOUNT,
            "hold_days": HOLD_DAYS,
            "sell_modes": SELL_MODES,
            "periods": {k: v["label"] for k, v in PERIODS.items()},
            "rating_thresholds": {"high": RATING_HIGH, "mid": RATING_MID},
            "etf_tiers": ["strong", "related", "approx"],
            "commission_rate": COMMISSION_RATE,
            "slippage": SLIPPAGE,
            "min_commission": MIN_COMMISSION,
            "transfer_fee_rate_sh": TRANSFER_FEE_RATE_SH,
            "buy_signals": list(BUY_SIGNALS),
        },
        "quadrants": {},
    }

    for quad_key, quad_meta in QUADRANT_META.items():
        quad_data = {"label": quad_meta["label"], "desc": quad_meta["desc"], "periods": {}}
        for period_key, period_def in PERIODS.items():
            cutoff = period_def["cutoff"]
            period_data = {}
            for mode_key in SELL_MODES:
                all_trades = quadrants[quad_key][mode_key]
                # 按周期过滤(信号买入日期 >= cutoff)
                if cutoff and cutoff != "0":
                    period_trades = [t for t in all_trades if t["buy_date"] >= cutoff]
                else:
                    period_trades = list(all_trades)
                period_data[mode_key] = _compute_stats(period_trades)
            quad_data["periods"][period_key] = period_data
        output["quadrants"][quad_key] = quad_data

    # 6. 汇总打印
    print("\n=== 回测结果汇总 ===")
    for quad_key in QUADRANT_META:
        for period_key in PERIODS:
            n_a = output["quadrants"][quad_key]["periods"][period_key]["A"]["n"]
            n_b = output["quadrants"][quad_key]["periods"][period_key]["B"]["n"]
            if n_a > 0:
                hk = output["quadrants"][quad_key]["periods"][period_key]["A"]["half_kelly"]
                wr = output["quadrants"][quad_key]["periods"][period_key]["A"]["win_rate"]
                print(f"  {quad_key:14s} {period_key:3s}  A: n={n_a:5d} win_rate={wr:.3f} half_kelly={hk:.1f}%  B: n={n_b:5d}")

    return output


def main():
    parser = argparse.ArgumentParser(description="信号凯利回测")
    parser.add_argument("--output", default=None, help="输出 JSON 路径(默认 static-site/data/signal_kelly_backtest.json)")
    args = parser.parse_args()

    output_path = args.output or os.path.join(ROOT, "static-site", "data", "signal_kelly_backtest.json")

    print("=" * 60)
    print("信号凯利回测: 6象限 × 4模式 × 3周期")
    print(f"ROOT = {ROOT}")
    print(f"输出 = {output_path}")
    print("=" * 60)

    data = compute()

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    size = os.path.getsize(output_path)
    print(f"\n✓ 输出: {output_path} ({size} bytes = {size / 1024:.1f} KB)")

    # 生成 .gz
    import gzip
    gz_path = output_path + ".gz"
    with open(output_path, "rb") as src, gzip.open(gz_path, "wb") as dst:
        dst.write(src.read())
    print(f"✓ gzip: {gz_path} ({os.path.getsize(gz_path)} bytes)")


if __name__ == "__main__":
    main()
