"""ETF 持仓数据验证脚本(Step1, 一次性, 只读不写生产)。

目的: 验证 112 只 track_score 第一 ETF 的东财 fundf10 持仓数据落地覆盖率,
     产出 TOP1-3 个股去重集合(供 Step2 补采日线), 按 tier/指数大类分组的
     TOP1 权重分布, 验证"龙头效应强弱"分档(>5%强 / 1-5%中 / <1%弱)。

依赖:
  - static-site/data/board_etf_map.json(读 track_score 第一 ETF 清单)
  - app/collector/public_fund.py fetch_fund_portfolio_hold(东财 fundf10 拉持仓, 只读网络)
  - data/ 下无任何写库操作(纯只读验证)

输出:
  - docs/kelly/backtest-ai/etf-weight-leader/data/etf_hold_verify_result.json(全量结果)
  - docs/kelly/backtest-ai/etf-weight-leader/data/etf_hold_collect_progress.json(断点续采进度)
  - 控制台打印统计摘要

复现命令:
  .venv/bin/python docs/kelly/backtest-ai/etf-weight-leader/scripts/etf_hold_verify.py
  (112 ETF x 2019-2026 每 year 一次请求, throttle 0.5s, 约 15-25 分钟)
"""
import os
os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")
import sys
import json
import time
from pathlib import Path
from collections import Counter

PROJ_ROOT = Path(__file__).absolute().parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(PROJ_ROOT))

from app.collector.public_fund import fetch_fund_portfolio_hold

BOARD_MAP = PROJ_ROOT / "static-site/data/board_etf_map.json"
OUT_DIR = Path(__file__).absolute().parent.parent / "data"
RESULT_PATH = OUT_DIR / "etf_hold_verify_result.json"
PROGRESS_PATH = OUT_DIR / "etf_hold_collect_progress.json"

YEARS = [str(y) for y in range(2019, 2027)]
THROTTLE = 0.5

# 指数大类分类 --------------------------------------------------------------
FOREIGN_KEYS = {"hsi","hstech","hscei","us_dji","us_spx","us_ndx","us_ixic",
                "nikkei225","dax","cac40"}
BROAD_KEYS = {"sh","sz","hs300","sz50","csi500","csi1000","cyb","kc50",
              "csi_div","div_lowvol","sz_div",
              "csi_000010","csi_000330","csi_000903","csi_000510","csi_930050",
              "csi_932000","csi_000102","csi_000673","csi_931643","csi_932315"}

def classify_index(key: str) -> str:
    if key in FOREIGN_KEYS:
        return "境外"
    if key in BROAD_KEYS:
        return "宽基"
    if key.startswith("sw_") or key.startswith("gz_") or key.startswith("csi_399"):
        return "行业"
    if key.startswith("thsc_") or key.startswith("sse_"):
        return "主题"
    if key.startswith("csi_"):
        return "主题"
    return "其他"


def load_top_etfs():
    d = json.loads(BOARD_MAP.read_text(encoding="utf-8"))
    items = []
    for k, v in d.items():
        if not isinstance(v, list):
            continue
        scored = [e for e in v if e.get("track_score") is not None]
        if not scored:
            continue
        best = max(scored, key=lambda e: e["track_score"])
        items.append({
            "index_key": k,
            "etf_code": best["code"],
            "etf_name": best["name"],
            "track_tier": best.get("track_tier"),
            "track_score": best.get("track_score"),
            "stable_top1": best.get("stable_top1"),
            "index_class": classify_index(k),
        })
    return items


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    etfs = load_top_etfs()
    print(f"[I] track_score 第一 ETF 共 {len(etfs)} 只", flush=True)

    # 断点续采
    done = {}
    if PROGRESS_PATH.exists():
        done = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))

    for i, e in enumerate(etfs):
        code = e["etf_code"]
        if code in done:
            continue
        yearly = {}
        for year in YEARS:
            rows = fetch_fund_portfolio_hold(code, year)
            # 按季度分组, 每季度条数
            by_q = {}
            for r in rows:
                by_q.setdefault(r["quarter_label"], []).append(r)
            yearly[year] = {q: [{"stock_code": x["stock_code"],
                                 "stock_name": x["stock_name"],
                                 "weight_pct": x["weight_pct"]}
                                for x in rs] for q, rs in by_q.items()}
            time.sleep(THROTTLE)
        done[code] = yearly
        PROGRESS_PATH.write_text(json.dumps(done, ensure_ascii=False))
        n_q = sum(len(v) for v in yearly.values())
        print(f"[I] {i+1}/{len(etfs)} {code} {e['etf_name']}: 年数={len([1 for y in yearly if yearly[y]])} "
              f"季度总数={n_q}", flush=True)

    # ---- 汇总统计 ----
    result = {"meta": {"note": "112只track_score第一ETF东财fundf10持仓验证(2019-2026全季度)",
                       "source": "fundf10.eastmoney.com jjcc",
                       "etf_count": len(etfs), "years": YEARS,
                       "classify_rule": "FOREIGN/BROAD_LIST硬编码 + 前缀规则, 见脚本头"},
              "etfs": [], "coverage": {}, "top1_weight_dist": {},
              "top_stock_universe": []}

    etf_meta = {e["etf_code"]: e for e in etfs}
    for code, yearly in done.items():
        meta = etf_meta.get(code, {})
        quarters = []
        top1_list = []
        top3_codes = set()
        for year, qs in yearly.items():
            for q_label, rows in qs.items():
                rows_sorted = sorted(rows, key=lambda x: x["weight_pct"] or 0, reverse=True)
                qinfo = {"quarter": q_label, "top": rows_sorted[:10]}
                quarters.append(qinfo)
                if rows_sorted:
                    top1_list.append({"quarter": q_label,
                                      "code": rows_sorted[0]["stock_code"],
                                      "name": rows_sorted[0]["stock_name"],
                                      "weight": rows_sorted[0]["weight_pct"]})
                    for r in rows_sorted[:3]:
                        if r["stock_code"]:
                            top3_codes.add(r["stock_code"])
        n_quarters = len(quarters)
        result["etfs"].append({
            "etf_code": code, "etf_name": meta.get("etf_name"),
            "index_key": meta.get("index_key"), "index_class": meta.get("index_class"),
            "track_tier": meta.get("track_tier"), "quarter_count": n_quarters,
            "top1_median_weight": _median([t["weight"] for t in top1_list if t.get("weight")]),
            "top1_weight_series": top1_list,
            "top3_stock_codes": sorted(top3_codes),
        })

    # 覆盖率
    total = len(etfs)
    with_data = sum(1 for e in result["etfs"] if e["quarter_count"] > 0)
    result["coverage"] = {
        "etf_total": total,
        "etf_with_holdings": with_data,
        "coverage_rate": round(with_data / total, 4),
        "quarter_total": sum(e["quarter_count"] for e in result["etfs"]),
    }

    # TOP1 权重分布(分档 + 按 tier + 按指数大类)
    tier_dist = {}
    class_dist = {}
    for e in result["etfs"]:
        w = e["top1_median_weight"]
        if w is None:
            continue
        tier = e["track_tier"] or "none"
        cls = e["index_class"] or "其他"
        tier_dist.setdefault(tier, []).append(w)
        class_dist.setdefault(cls, []).append(w)
    result["top1_weight_dist"]["overall"] = _dist_buckets(
        [x for e in result["etfs"] if e["top1_median_weight"] is not None for x in [e["top1_median_weight"]]])
    result["top1_weight_dist"]["by_tier"] = {k: _dist_buckets(v) for k, v in sorted(tier_dist.items())}
    result["top1_weight_dist"]["by_index_class"] = {k: _dist_buckets(v) for k, v in sorted(class_dist.items())}

    # TOP1-3 个股去重集合(仅 A 股 6 位数字代码)
    top_stocks = set()
    foreign_stocks = set()
    for e in result["etfs"]:
        for c in e["top3_stock_codes"]:
            if c.isdigit() and len(c) == 6:
                top_stocks.add(c)
            else:
                foreign_stocks.add(c)
    result["top_stock_universe"] = {
        "a_stock_codes": sorted(top_stocks),
        "a_stock_count": len(top_stocks),
        "foreign_codes": sorted(foreign_stocks),
        "foreign_count": len(foreign_stocks),
    }

    RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    _print_summary(result)


def _median(vals):
    vals = sorted(vals)
    if not vals:
        return None
    n = len(vals)
    return round(vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2, 2)


def _dist_buckets(vals):
    strong = sum(1 for v in vals if v > 5)
    mid = sum(1 for v in vals if 1 <= v <= 5)
    weak = sum(1 for v in vals if v < 1)
    return {"n": len(vals),
            ">5%_强": strong, "1-5%_中": mid, "<1%_弱": weak,
            "median_pct": round(sorted(vals)[len(vals)//2], 2) if vals else None}


def _print_summary(result):
    c = result["coverage"]
    print("\n===== 汇总 =====")
    print(f"覆盖率: {c['etf_with_holdings']}/{c['etf_total']} = {c['coverage_rate']:.1%}")
    print(f"季度总数: {c['quarter_total']}")
    print("\nTOP1 权重分档(按 ETF 中位 TOP1 权重):")
    for k, v in result["top1_weight_dist"]["overall"].items():
        print(f"  {k}: {v}")
    print("\n按 tier:")
    for tier, v in result["top1_weight_dist"]["by_tier"].items():
        print(f"  {tier}: {v}")
    print("\n按指数大类:")
    for cls, v in result["top1_weight_dist"]["by_index_class"].items():
        print(f"  {cls}: {v}")
    u = result["top_stock_universe"]
    print(f"\nTOP1-3 个股去重: A股 {u['a_stock_count']} 只, 境外 {u['foreign_count']} 只")
    print(f"结果已写: {RESULT_PATH}")


if __name__ == "__main__":
    main()
