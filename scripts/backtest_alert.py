"""综合 AI 风险预警回测框架。

验证 alert_score 的高低预警对上证指数未来 N 日涨跌的预测力:
  - 高位预警 (HIGH_ALERT > 阈值, 默认 80) 后 N 日下跌占比, 目标 > 55%
  - 低位预警 (LOW_ALERT > 阈值, 默认 80) 后 N 日上涨占比, 目标 > 60%
  - 盈亏比 = 平均命中幅度 / 平均未命中幅度, 目标 > 1.2
  - 防过拟合: 样本外验证(前 2/3 训练 / 后 1/3 验证) + 参数稳定性(阈值 ±5)

用法:
  .venv/bin/python scripts/backtest_alert.py --start 20240701
  .venv/bin/python scripts/backtest_alert.py --start 20160101 --end 20260720
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.alert_score import compute_alert_scores  # noqa: E402

_BENCHMARK = "sh"            # 收益基准: 上证指数
_HOLDINGS = (5, 10, 20)      # N 日持有期
_DEFAULT_HIGH = 72           # HIGH_ALERT 触发阈值(约96分位, 调参后最优: N10下跌占比56.4%)
_DEFAULT_LOW = 85            # LOW_ALERT 触发阈值(约95分位, 调参后最优: N10上涨占比65.7%)
_TARGET_HIGH_WIN = 0.55      # 高位预警下跌占比目标
_TARGET_LOW_WIN = 0.60       # 低位预警上涨占比目标
_TARGET_PL = 1.2             # 盈亏比目标


def _forward_returns(close: pd.Series, holdings: tuple[int, ...]) -> dict[int, pd.Series]:
    """各持有期 forward 收益: close[t+N]/close[t]-1, 对齐到 t 日。"""
    out = {}
    for n in holdings:
        out[n] = close.shift(-n) / close - 1
    return out


def _stats(returns: pd.Series, is_high: bool) -> dict:
    """统计一组触发样本的胜率/盈亏比。is_high=True 时命中=下跌; False 时命中=上涨。"""
    r = returns.dropna()
    n = len(r)
    if n == 0:
        return {"n": 0, "win_rate": None, "avg_ret": None, "pl_ratio": None}
    if is_high:
        hits = r[r < 0]            # 下跌=命中
        miss = r[r > 0]
        win_rate = len(hits) / n
        pl = (hits.abs().mean() / miss.mean()) if len(miss) and miss.mean() != 0 else None
    else:
        hits = r[r > 0]            # 上涨=命中
        miss = r[r < 0]
        win_rate = len(hits) / n
        pl = (hits.mean() / miss.abs().mean()) if len(miss) and miss.abs().mean() != 0 else None
    return {"n": n, "win_rate": win_rate, "avg_ret": r.mean(), "pl_ratio": pl}


def _fmt_block(title: str, alerts: pd.Series, fwd: dict[int, pd.Series], is_high: bool, target: float) -> str:
    lines = [title]
    for n in _HOLDINGS:
        idx = alerts[alerts].index.intersection(fwd[n].index)
        st = _stats(fwd[n].reindex(idx), is_high)
        wr = f"{st['win_rate']*100:.1f}%" if st['win_rate'] is not None else "N/A"
        pl = f"{st['pl_ratio']:.2f}" if st['pl_ratio'] is not None else "N/A"
        avg = f"{st['avg_ret']*100:+.2f}%" if st['avg_ret'] is not None else "N/A"
        ok = "OK" if (st['win_rate'] or 0) >= target else "x"
        plo = "OK" if (st['pl_ratio'] or 0) >= _TARGET_PL else "x"
        lines.append(f"  N={n:>2}: 样本={st['n']:>3} 胜率={wr:>6}({ok}) 盈亏比={pl:>5}({plo}) 平均收益={avg}")
    return "\n".join(lines)


def _freq_per_year(alerts: pd.Series) -> str:
    """按年统计触发次数。"""
    if alerts.sum() == 0:
        return "  (无触发)"
    s = alerts[alerts]
    years = pd.Series([d[:4] for d in s.index])
    return "  " + "  ".join(f"{y}:{c}次" for y, c in years.value_counts().sort_index().items())


def run(start: str, end: str | None, high_th: float, low_th: float) -> str:
    end = end or compute_alert_scores().index[-1]
    df = compute_alert_scores(start=start, end=end)

    import sqlite3
    with sqlite3.connect(ROOT / "data" / "sentiment.db") as c:
        close = pd.Series({r[0]: r[1] for r in c.execute(
            "SELECT date,close FROM index_daily WHERE index_id=? AND close IS NOT NULL ORDER BY date", (_BENCHMARK,)
        )}).astype(float)
    fwd = _forward_returns(close, _HOLDINGS)

    ha = (df["high_alert"] >= high_th).reindex(close.index, fill_value=False)
    la = (df["low_alert"] >= low_th).reindex(close.index, fill_value=False)
    n_h, n_l = int(ha.sum()), int(la.sum())

    out = []
    out.append(f"=== 综合风险预警回测  {start} ~ {end}  (基准: 上证) ===")
    out.append(f"区间交易日: {len(df)}  高位触发(>={high_th}): {n_h}  低位触发(>={low_th}): {n_l}\n")
    out.append(_fmt_block(f"【高位预警】HIGH_ALERT>={high_th} -> 后N日下跌占比(目标>{_TARGET_HIGH_WIN*100:.0f}%)",
                          ha, fwd, True, _TARGET_HIGH_WIN))
    out.append("\n  触发频率(按年):")
    out.append(_freq_per_year(ha))
    out.append("")
    out.append(_fmt_block(f"【低位预警】LOW_ALERT>={low_th} -> 后N日上涨占比(目标>{_TARGET_LOW_WIN*100:.0f}%)",
                          la, fwd, False, _TARGET_LOW_WIN))
    out.append("\n  触发频率(按年):")
    out.append(_freq_per_year(la))

    # ---- 防过拟合 1: 样本外验证(前 2/3 训练 / 后 1/3 验证) ----
    out.append("\n=== 防过拟合 1: 样本外验证 (前2/3 vs 后1/3) ===")
    dates = df.index.tolist()
    cut = dates[int(len(dates) * 2 / 3)]
    for tag, sl in [("前2/3(训练)", df[df.index <= cut]), ("后1/3(样本外)", df[df.index > cut])]:
        ha_s = (sl["high_alert"] >= high_th).reindex(close.index, fill_value=False)
        la_s = (sl["low_alert"] >= low_th).reindex(close.index, fill_value=False)
        sh = _stats(fwd[10].reindex(ha_s[ha_s].index), True)
        sl_ = _stats(fwd[10].reindex(la_s[la_s].index), False)
        hw = f"{sh['win_rate']*100:.1f}%" if sh['win_rate'] else "N/A"
        lw = f"{sl_['win_rate']*100:.1f}%" if sl_['win_rate'] else "N/A"
        out.append(f"  {tag} 高位N=10: 样本{sh['n']} 胜率{hw} | 低位N=10: 样本{sl_['n']} 胜率{lw}")

    # ---- 防过拟合 2: 参数稳定性(阈值 ±5) ----
    out.append("\n=== 防过拟合 2: 参数稳定性 (N=10, 阈值±5) ===")
    for th in [high_th - 5, high_th, high_th + 5]:
        ha_s = (df["high_alert"] >= th).reindex(close.index, fill_value=False)
        s = _stats(fwd[10].reindex(ha_s[ha_s].index), True)
        w = f"{s['win_rate']*100:.1f}%" if s['win_rate'] else "N/A"
        out.append(f"  高位阈值{th}: 样本{s['n']} 胜率{w}")
    for th in [low_th - 5, low_th, low_th + 5]:
        la_s = (df["low_alert"] >= th).reindex(close.index, fill_value=False)
        s = _stats(fwd[10].reindex(la_s[la_s].index), False)
        w = f"{s['win_rate']*100:.1f}%" if s['win_rate'] else "N/A"
        out.append(f"  低位阈值{th}: 样本{s['n']} 胜率{w}")

    out.append("\n=== 过拟合迹象判读 ===")
    out.append("  - 若样本外胜率较训练段骤降>10pct -> 过拟合风险")
    out.append("  - 若阈值±5样本数/胜率突变(样本翻倍或胜率翻转) -> 阈值敏感=过拟合")
    out.append("  - 触发频率: 高位目标3-8次/年, 低位2-5次/年; 过高=阈值松, 过低=阈值紧")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="综合风险预警回测")
    ap.add_argument("--start", default="20240701", help="起始日 YYYYMMDD (默认 20240701)")
    ap.add_argument("--end", default=None, help="结束日 YYYYMMDD (默认 DB 最新)")
    ap.add_argument("--high-threshold", type=float, default=_DEFAULT_HIGH, help=f"HIGH_ALERT 触发阈值 (默认{_DEFAULT_HIGH})")
    ap.add_argument("--low-threshold", type=float, default=_DEFAULT_LOW, help=f"LOW_ALERT 触发阈值 (默认{_DEFAULT_LOW})")
    args = ap.parse_args()
    report = run(args.start, args.end, args.high_threshold, args.low_threshold)
    print(report)
    with open("/tmp/agent-progress-alert-backtest.md", "a") as f:
        f.write(f"\n\n[回测报告 {args.start}~{args.end or 'latest'}]\n{report}\n")


if __name__ == "__main__":
    main()
