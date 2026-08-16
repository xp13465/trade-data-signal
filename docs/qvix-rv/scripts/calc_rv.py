"""计算 510050/510300 的 20 日滚动年化已实现波动率(RV)，作为 QVIX 近似兜底的数据验证。

目的：验证 optbbs 主源宕机时，用跟踪 ETF 日收益算的 RV 是否能近似 QVIX（兜底口径）。
方法口径：RV = 最近 20 个交易日对数收益率 r_t=ln(close_t/close_{t-1}) 的样本标准差 × √252 × 100（年化%）。
输入依赖：510050/510300 日线 close，来源 akshare fund_etf_hist_sina(sina 主源) + mootdx fallback，
          经 app/collector/etf_national_team.py::fetch_etf_ohlc 拉取（返全历史本地过滤）。
输出：stdout 打印最近 3 个交易日 RV；默认同时写 docs/qvix-rv/data/rv_{etf}.json 沉淀数据。
复现命令：
    cd /Users/linhuichen/code/qvix-rv-backfill
    /Users/linhuichen/code/trade/.venv/bin/python docs/qvix-rv/scripts/calc_rv.py
关键参数：窗口 window=20（交易日）；窗口内有效收益 <5 不输出；年化因子 252。
数据截止：拉取时点最近收盘日（本报告 2026-08-14）；510050 至 close=3.021，510300 至 close=4.726。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).absolute().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from app.collector.etf_national_team import fetch_etf_ohlc  # noqa: E402

# func_name: (etf_code, label, DB metric_id)
TARGETS = [
    ("index_option_300etf_qvix", "510300", "300ETF", "a_qvix_300"),
    ("index_option_50etf_qvix", "510050", "50ETF", "a_qvix_1000"),
    # 注意：真正生效的映射在 fetchers.py::RV_ETFS；此处为独立复现数据验证。
]


def calc_rv(rows, window=20):
    """rows: [{date, close}] → [(date, rv_annualized_pct)]，RV 为 20 日滚动年化对数波动率。"""
    recs = sorted(rows, key=lambda r: r["date"])
    closes = [r["close"] for r in recs]
    dates = [r["date"] for r in recs]
    import math

    rets = []
    for i in range(1, len(closes)):
        c0, c1 = closes[i - 1], closes[i]
        if c0 and c1 and c0 > 0 and c1 > 0:
            rets.append(math.log(c1 / c0))
        else:
            rets.append(None)
    out = []
    for i in range(len(closes)):
        if i < window:
            continue
        seg = [r for r in rets[i - window:i] if r is not None]
        if len(seg) < 5:
            continue
        m = sum(seg) / len(seg)
        var = sum((x - m) ** 2 for x in seg) / len(seg)
        sd = math.sqrt(var)
        out.append((dates[i], round(sd * math.sqrt(252) * 100, 3)))
    return out


def main():
    for func, code, label, _mid in TARGETS:
        rows = fetch_etf_ohlc(code)
        rv = calc_rv(rows)
        print(f"=== {label}({code}) 共{len(rows)}行, RV 序列 {len(rv)} 行 ===")
        for d, v in rv[-3:]:
            print(f"  RV {d}: {v:.3f} (annualized %)")
        # 沉淀数据
        data_out = Path(__file__).absolute().parent.parent / "data" / f"rv_{code}.json"
        import json
        data_out.write_text(
            json.dumps({"etf": code, "label": label, "func": func, "n": len(rv),
                        "series": [{"date": d, "rv": v} for d, v in rv]},
                       ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"  → 已写 {data_out}")


if __name__ == "__main__":
    main()
