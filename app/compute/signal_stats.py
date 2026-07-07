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

STATS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "signal_stats.json"


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


def compute() -> dict:
    """遍历每品种 × 每信号 × 每 horizon，算 stats，返回完整 dict。"""
    sig_map = _load_signal_dates()
    out: dict = {}
    for iid, sigs in sig_map.items():
        series = _load_series_for(iid)
        if series.empty:
            continue
        # 预计算 forward 收益（horizon → Series 对齐 series.index）
        fwd = {h: (series.shift(-h) / series - 1.0) * 100.0 for h in HORIZONS}
        iid_stats: dict = {}
        for sig, dates in sigs.items():
            is_sell = sig == "sell"
            sig_stats: dict = {}
            for h in HORIZONS:
                # 只取信号日有 forward 数据的（dropna）
                fwd_h = fwd[h]
                returns = [float(fwd_h.get(d)) for d in dates if d in fwd_h.index]
                sig_stats[f"{h}d"] = _stats_for_returns(returns, is_sell)
            iid_stats[sig] = sig_stats
        out[iid] = iid_stats
    return out


def store(stats: dict) -> int:
    """写 data/signal_stats.json（覆盖）。返回字节数。"""
    from app.calendar import last_trading_day
    stats_with_meta = {"_updated_at": last_trading_day(), **stats}
    STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(stats_with_meta, ensure_ascii=False, separators=(",", ":"))
    STATS_PATH.write_text(text, encoding="utf-8")
    return len(text)


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
