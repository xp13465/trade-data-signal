"""每品种买卖点回测 stats：基于历史 signal_daily 信号算 forward 收益统计。

为每个 index_id（指数/指标 g.*/分数 s.*）的 buy/buy_aux/sell 信号算
forward 收益（信号日 close/value → N 交易日后 close/value，N=5/10/20），
输出胜率/盈亏比/均值收益/样本数，供前端折线图 tips 显示。

逻辑（参考 a-stock-data/backtest_strategies.py 的 forward 收益算法）：
- 信号日 close/value → N 交易日后的 close/value，收益 % = (fwd/cur - 1) * 100。
- 当天信号无 forward（未来未到，shift(-N) 自然 NaN）→ 跳过。
- 样本数 = N 日后有数据的信号数（NaN 不计入）。
- 胜率：买=收益>0 占比；卖=收益<0 占比（信号后下跌才算对）。
- 盈亏比 = 平均盈利绝对值 / 平均亏损绝对值（无亏损 → NaN）。
- 均值收益 = 收益 % 算术平均。

存储：data/signal_stats.json
  {
    "_updated_at": "20260706",
    "sh": {
      "buy":     {"5d": {"win_rate": 0.523, "pl": 1.26, "mean": 0.75, "n": 156}, "10d": {...}, "20d": {...}},
      "buy_aux": {...},
      "sell":    {...}
    },
    ...
  }

独立跑：python -m app.compute.signal_stats
集成 runner.py（step 10）定期重算。
"""
import json
from pathlib import Path

import pandas as pd

from ..db import get_conn
from .normalize import load_index_close, load_metric_value, load_score_value

HORIZONS = (5, 10, 20)
MIN_SAMPLE = 10  # 样本数 < 10 前端标"样本不足"

STATS_PATH = Path(__file__).absolute().parent.parent.parent / "data" / "signal_stats.json"


def _load_signal_dates() -> dict[str, dict[str, list[str]]]:
    """读 signal_daily，返回 {index_id: {signal: [date, ...]}}（date 升序）。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT date, index_id, signal FROM signal_daily ORDER BY index_id, signal, date"
    ).fetchall()
    conn.close()
    out: dict[str, dict[str, list[str]]] = {}
    for r in rows:
        iid = r["index_id"]
        sig = r["signal"]
        out.setdefault(iid, {}).setdefault(sig, []).append(r["date"])
    return out


def _load_series_for(index_id: str) -> pd.Series:
    """按 index_id 前缀加载对应 close/value 序列（按 date 升序，过滤 NULL）。

    - g.<metric_id> → daily_metric value
    - s.<score_id>  → score_daily value
    - 其他（指数）  → index_daily close
    """
    if index_id.startswith("g."):
        return load_metric_value(index_id[2:])
    if index_id.startswith("s."):
        return load_score_value(index_id[2:])
    return load_index_close(index_id)


def _stats_for_returns(returns: list[float], is_sell: bool) -> dict:
    """算一组 forward 收益的胜率/盈亏比/均值/样本数。

    - 买/辅买：wins = r>0，losses = r<=0
    - 卖：wins = r<0，losses = r>=0（信号后下跌才算对）
    - 盈亏比 = mean(|wins|) / mean(|losses|)；无亏损 → None
    """
    arr = [r for r in returns if r is not None and not pd.isna(r)]
    n = len(arr)
    if n == 0:
        return {"win_rate": None, "pl": None, "mean": None, "n": 0}
    if is_sell:
        wins = [r for r in arr if r < 0]
        losses = [r for r in arr if r >= 0]
    else:
        wins = [r for r in arr if r > 0]
        losses = [r for r in arr if r <= 0]
    win_rate = len(wins) / n
    mean_win = sum(abs(r) for r in wins) / len(wins) if wins else 0.0
    mean_loss = sum(abs(r) for r in losses) / len(losses) if losses else None
    pl = (mean_win / mean_loss) if (mean_loss is not None and mean_loss > 0) else None
    mean_ret = sum(arr) / n
    return {
        "win_rate": round(win_rate, 4),
        "pl": round(pl, 4) if pl is not None else None,
        "mean": round(mean_ret, 4),
        "n": n,
    }


def _compute_frequency(sig_map: dict) -> dict:
    """计算每个品种×信号类型的频率统计。

    返回 {index_id: {signal: {year_count, monthly_avg, months: {YYYY-MM: count}}}}
    """
    from datetime import datetime
    freq: dict = {}
    for iid, sigs in sig_map.items():
        iid_freq: dict = {}
        for sig, dates in sigs.items():
            if not dates:
                continue
            # 今年累计
            year_start = str(datetime.now().year) + "0101"
            year_dates = [d for d in dates if d >= year_start]
            year_count = len(year_dates)
            # 按月统计
            month_counts: dict = {}
            for d in dates:
                m = d[:6]  # YYYYMM (YYYYMMDD → YYYYMM)
                month_counts[m] = month_counts.get(m, 0) + 1
            # 最近12个月各月次数
            months_sorted = sorted(month_counts.items())[-12:]
            months_dict = {m: c for m, c in months_sorted}
            # 月均（全历史有信号的月份数）
            active_months = len(month_counts)
            monthly_avg = round(len(dates) / max(active_months, 1), 2) if active_months > 0 else 0
            iid_freq[sig] = {
                "year_count": year_count,
                "monthly_avg": monthly_avg,
                "total_count": len(dates),
                "months": months_dict,
            }
        if iid_freq:
            freq[iid] = iid_freq
    return freq


def compute() -> dict:
    """遍历每品种 × 每信号 × 每 horizon，算 stats，返回完整 dict。"""
    sig_map = _load_signal_dates()
    freq_map = _compute_frequency(sig_map)
    out: dict = {}
    for iid, sigs in sig_map.items():
        series = _load_series_for(iid)
        has_series = not series.empty
        if has_series:
            fwd = {h: (series.shift(-h) / series - 1.0) * 100.0 for h in HORIZONS}
        iid_stats: dict = {}
        for sig, dates in sigs.items():
            is_sell = sig == "sell"
            sig_stats: dict = {}
            if has_series:
                for h in HORIZONS:
                    fwd_h = fwd[h]
                    returns = [float(fwd_h.get(d)) for d in dates if d in fwd_h.index]
                    sig_stats[f"{h}d"] = _stats_for_returns(returns, is_sell)
            # 频率统计
            freq = freq_map.get(iid, {}).get(sig)
            if freq:
                sig_stats["frequency"] = freq
            if sig_stats:
                iid_stats[sig] = sig_stats
        if iid_stats:
            out[iid] = iid_stats
    return out


def store(stats: dict) -> int:
    """写 data/signal_stats.json（覆盖，原子写）。返回字节数。

    原子写（写 .tmp 再 replace）：core/width 多 pipeline 并发跑 compute 时，
    避免两进程同时 write_text 导致文件撕裂/读到半截 JSON。
    """
    from app.calendar import last_trading_day
    stats_with_meta = {"_updated_at": last_trading_day(), **stats}
    STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(stats_with_meta, ensure_ascii=False, separators=(",", ":"))
    tmp = STATS_PATH.parent / (STATS_PATH.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(STATS_PATH)  # 原子替换（POSIX rename）
    return len(text)


def compute_global_freq() -> dict:
    """全局信号频率统计：聚合所有品种 buy/buy_aux/sell 的今年次数/总计/月均。

    月均算法（S2 修复）：用今年实际有信号的有效月份数做分母，而不是当前月份。
    原 `year / cur_month` 在 1 月查看时会把全年次数当月均，数值虚高。
    每品种 frequency 已带 `months` dict（最近 12 个月 YYYYMM->count），
    取其中今年的月份求并集，即"今年有信号的月份数"。

    返回：
      {sig: {monthly_avg, year_count, total_count, active_months}}
    """
    from datetime import datetime
    all_stats = load()
    this_year = str(datetime.now().year)
    cur_month = datetime.now().month
    freq: dict = {
        sig: {"year_count": 0, "total_count": 0, "year_months": set()}
        for sig in ("buy", "buy_aux", "sell")
    }
    for iid, sigs in all_stats.items():
        if iid.startswith("_"):
            continue
        for sig in ("buy", "buy_aux", "sell"):
            f = sigs.get(sig, {}).get("frequency")
            if not f:
                continue
            freq[sig]["year_count"] += f.get("year_count", 0)
            freq[sig]["total_count"] += f.get("total_count", 0)
            # 收集今年实际有信号的月份（YYYYMM 前缀匹配当前年）
            for ym in f.get("months", {}):
                if isinstance(ym, str) and ym.startswith(this_year):
                    freq[sig]["year_months"].add(ym)
    out: dict = {}
    for sig, d in freq.items():
        y = d["year_count"]
        active = len(d["year_months"])
        # 有效月数 > 0 用之；否则退回 cur_month（旧数据 months 缺失的兜底，避免 0 除）
        divisor = active if active > 0 else max(cur_month, 1)
        monthly_avg = round(y / divisor, 2) if y > 0 else 0
        out[sig] = {
            "monthly_avg": monthly_avg,
            "year_count": y,
            "total_count": d["total_count"],
            "active_months": active,
        }
    return out


def load() -> dict:
    """读 data/signal_stats.json（API/export 用，文件不存在返空 dict）。"""
    if not STATS_PATH.exists():
        return {}
    try:
        return json.loads(STATS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def main():
    stats = compute()
    n_bytes = store(stats)
    n_iid = len([k for k in stats if not k.startswith("_")])
    print(f"=== signal_stats 完成: {n_iid} 个品种 × 3 信号 × 3 horizon ===")
    print(f"写入 {STATS_PATH} ({n_bytes} bytes)")
    # 抽样打印 sh
    if "sh" in stats:
        print("\n抽样 sh:")
        for sig in ("buy", "buy_aux", "sell"):
            if sig in stats["sh"]:
                s = stats["sh"][sig]["10d"]
                print(f"  {sig:8s} 10d: 胜率={s['win_rate']}, 盈亏比={s['pl']}, 均值={s['mean']}%, n={s['n']}")


if __name__ == "__main__":
    main()
