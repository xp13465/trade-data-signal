#!/usr/bin/env python3
"""静态化导出脚本：从 SQLite (data/sentiment.db) 导出所有 API 端点数据为静态 JSON。

复刻 app/main.py 各端点的查询逻辑，保证 JSON 结构与 API 返回一致（前端改动最小）。
可重复跑（python static-site/export.py），覆盖 data/ 下 JSON。

导出端点：
  - data/overview.json                 （今日快照 + 指数 sparkline + 宽度 + 分数 + 行业热力图 + 买卖点 + 冰点日）
  - data/a-stock-{1m,3m,6m,1y,all}.json
  - data/hk-{1m,3m,6m,1y,all}.json
  - data/global-{1m,3m,6m,1y,all}.json
  - data/sentiment-{1m,3m,6m,1y,all}.json
  - data/industry-{1m,3m,6m,1y,all}.json
  - data/metrics.json                  （指标注册表）
  - data/index/{index_id}-all.json     （44 个指数 ohlc + signals 全历史）

range 处理方案（备注）：
  - tab 端点（a-stock/hk/global/sentiment/industry）预生成多 range JSON（各 5 个文件），
    前端按 state.range 直接读对应文件，逻辑最简（无需客户端切片）。
  - index 端点仅预生成 all 全历史（44 文件），前端读后用 ohlc 日期范围客户端过滤 signals
    （signals 数组小，过滤开销可忽略；避免 44×5=220 文件膨胀）。

数据源：仅读 data/sentiment.db（API 只用此库；stock_daily.db 仅供采集器用，API 不读）。
"""
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 复用 app 包代码（与 API 完全一致的查询逻辑）
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.calendar import last_trading_day  # noqa: E402
from app.collector.fetchers import load_config  # noqa: E402
from app.compute import signal_stats as sigstats  # noqa: E402
from app.db import get_conn  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent
DATA_DIR = STATIC_DIR / "data"
INDEX_DIR = DATA_DIR / "index"

RANGES = {"1m": 30, "3m": 90, "6m": 180, "1y": 365}
ALL_RANGES = list(RANGES.keys()) + ["all"]


def _stats_all() -> dict:
    """读 data/signal_stats.json（与 main.py _stats_all 一致）。"""
    return sigstats.load()


def _stats_for(stats_all: dict, index_id: str) -> dict:
    return stats_all.get(index_id, {})

# 概览 KPI 指标（与 main.py KPI_METRIC_IDS 一致）
KPI_METRIC_IDS = [
    "a_width_zt_count",
    "a_width_dt_count",
    "a_width_zhaban_rate",
    "a_amount",
    "a_fund_north",
    "a_fund_margin",
]
SPARKLINE_INDEX_IDS = ["sh", "sz", "hs300", "cyb", "kc50", "hsi", "hstech"]


# ============ 查询辅助（复刻 main.py 私有函数，保证结构一致）============

def _range(rng: str):
    end = last_trading_day()
    if rng == "all":
        return "20100101", end
    days = RANGES.get(rng, 365)
    start = (datetime.strptime(end, "%Y%m%d") - timedelta(days=days)).strftime("%Y%m%d")
    return start, end


def _metric_series(conn, metric_id, start, end):
    rows = conn.execute(
        "SELECT date, value FROM daily_metric WHERE metric_id=? AND date BETWEEN ? AND ? ORDER BY date",
        (metric_id, start, end),
    ).fetchall()
    return [{"date": r["date"], "value": r["value"]} for r in rows]


def _index_series(conn, index_id, start, end):
    rows = conn.execute(
        "SELECT date, open, high, low, close, pct_change, amount FROM index_daily "
        "WHERE index_id=? AND date BETWEEN ? AND ? ORDER BY date",
        (index_id, start, end),
    ).fetchall()
    return [dict(r) for r in rows]


def _score_series(conn, score_id, start, end):
    rows = conn.execute(
        "SELECT date, value, is_freeze, is_overheat, components FROM score_daily "
        "WHERE score_id=? AND date BETWEEN ? AND ? ORDER BY date",
        (score_id, start, end),
    ).fetchall()
    return [dict(r) for r in rows]


def _signals(conn, index_id=None, start=None, end=None):
    q = "SELECT date, index_id, signal, reason FROM signal_daily WHERE date BETWEEN ? AND ?"
    params = [start, end]
    if index_id:
        q += " AND index_id=?"
        params.append(index_id)
    rows = conn.execute(q + " ORDER BY date", params).fetchall()
    return [dict(r) for r in rows]


def _metrics_for_groups(cfg, *groups):
    return [m for m in cfg.get("metrics", []) if m.get("group") in groups and m.get("enabled")]


def _indices_for_market(cfg, market):
    return [i for i in cfg.get("indices", []) if i.get("market") == market and i.get("enabled", True)]


def _industry_heatmap(conn, cfg):
    """申万一级行业近 1 日 / 近 5 日涨跌幅（与 main.py _industry_heatmap 一致）。"""
    indices = _indices_for_market(cfg, "industry")
    out = []
    for idx in indices:
        iid = idx["id"]
        rows = conn.execute(
            "SELECT date, close, pct_change FROM index_daily "
            "WHERE index_id=? AND close IS NOT NULL ORDER BY date DESC LIMIT 6",
            (iid,),
        ).fetchall()
        if len(rows) < 2:
            continue
        latest = rows[0]
        pct_1d = latest["pct_change"]
        pct_5d = None
        if len(rows) >= 6 and rows[5]["close"]:
            pct_5d = (latest["close"] / rows[5]["close"] - 1) * 100
        elif len(rows) >= 2 and rows[-1]["close"]:
            pct_5d = (latest["close"] / rows[-1]["close"] - 1) * 100
        out.append({
            "id": iid,
            "name": idx["name"],
            "pct_1d": pct_1d,
            "pct_5d": pct_5d,
            "last_date": latest["date"],
        })
    return out


def _industry_width(conn, industry_code, start, end):
    rows = conn.execute(
        "SELECT date, up_count, down_count, zt_count, dt_count, zb_count, seal_rate, amount "
        "FROM industry_width_daily WHERE industry_code=? AND date BETWEEN ? AND ? ORDER BY date",
        (industry_code, start, end),
    ).fetchall()
    return [dict(r) for r in rows]


# ============ 端点导出函数 ============

def export_overview(conn, cfg):
    """复刻 /api/overview。"""
    row = conn.execute("SELECT max(date) FROM score_daily").fetchone()
    score_date = row[0] if row and row[0] else last_trading_day()
    scores = {r["score_id"]: dict(r) for r in conn.execute(
        "SELECT score_id, value, is_freeze, is_overheat FROM score_daily WHERE date=?",
        (score_date,),
    ).fetchall()}

    metric_cfg = {m["id"]: m for m in cfg.get("metrics", []) if m.get("enabled")}
    today_metrics = []
    for mid in KPI_METRIC_IDS:
        m = metric_cfg.get(mid)
        if not m:
            continue
        r = conn.execute(
            "SELECT date, value, source FROM daily_metric WHERE metric_id=? AND value IS NOT NULL "
            "ORDER BY date DESC LIMIT 1",
            (mid,),
        ).fetchone()
        if r:
            today_metrics.append({
                "id": mid,
                "name": m["name"],
                "unit": m.get("unit"),
                "value": r["value"],
                "date": r["date"],
                "source": r["source"],
            })

    sigs = [dict(r) for r in conn.execute(
        "SELECT date, index_id, signal, reason FROM signal_daily WHERE date=?",
        (score_date,),
    ).fetchall()]
    freeze_days = [dict(r) for r in conn.execute(
        "SELECT date, score_id, value FROM score_daily WHERE is_freeze=1 ORDER BY date DESC LIMIT 5"
    ).fetchall()]

    spark_start = (datetime.strptime(score_date, "%Y%m%d") - timedelta(days=60)).strftime("%Y%m%d")
    indices_cfg = {i["id"]: i for i in cfg.get("indices", []) if i.get("enabled", True)}
    indices_sparkline = {}
    for iid in SPARKLINE_INDEX_IDS:
        idx = indices_cfg.get(iid)
        if not idx:
            continue
        rows = conn.execute(
            "SELECT date, close, pct_change FROM index_daily WHERE index_id=? AND date>=? ORDER BY date",
            (iid, spark_start),
        ).fetchall()
        if not rows:
            continue
        recent = rows[-30:]
        indices_sparkline[iid] = {
            "name": idx["name"],
            "dates": [r["date"] for r in recent],
            "closes": [r["close"] for r in recent],
            "pct_change": recent[-1]["pct_change"],
            "last_date": recent[-1]["date"],
        }

    width_start = (datetime.strptime(score_date, "%Y%m%d") - timedelta(days=45)).strftime("%Y%m%d")
    width_1m = {
        "up": [{"date": r["date"], "value": r["value"]} for r in conn.execute(
            "SELECT date, value FROM daily_metric WHERE metric_id='a_width_up_count' AND date>=? ORDER BY date",
            (width_start,),
        )],
        "down": [{"date": r["date"], "value": r["value"]} for r in conn.execute(
            "SELECT date, value FROM daily_metric WHERE metric_id='a_width_down_count' AND date>=? ORDER BY date",
            (width_start,),
        )],
    }

    six_m_start = (datetime.strptime(score_date, "%Y%m%d") - timedelta(days=210)).strftime("%Y%m%d")
    cross_6m = [{"date": r["date"], "value": r["value"], "is_freeze": r["is_freeze"], "is_overheat": r["is_overheat"]}
                for r in conn.execute(
                    "SELECT date, value, is_freeze, is_overheat FROM score_daily "
                    "WHERE score_id='cross_market' AND date>=? ORDER BY date",
                    (six_m_start,))]
    asent_6m = [{"date": r["date"], "value": r["value"], "is_freeze": r["is_freeze"], "is_overheat": r["is_overheat"]}
                for r in conn.execute(
                    "SELECT date, value, is_freeze, is_overheat FROM score_daily "
                    "WHERE score_id='a_sentiment' AND date>=? ORDER BY date",
                    (six_m_start,))]

    return {
        "date": score_date,
        "scores": scores,
        "signals_today": sigs,
        "recent_freeze": freeze_days,
        "today": {
            "scores": {k: {**v, "date": score_date} for k, v in scores.items()},
            "metrics": today_metrics,
        },
        "indices_sparkline": indices_sparkline,
        "width_1m": width_1m,
        "cross_market_6m": cross_6m,
        "a_sentiment_6m": asent_6m,
        "industry_heatmap": _industry_heatmap(conn, cfg),
    }


def export_a_stock(conn, cfg, rng):
    """复刻 /api/a-stock。"""
    start, end = _range(rng)
    groups = ("a_width", "a_fund", "a_sentiment", "lhb", "unlock", "ipo", "cov")
    metrics = {}
    for m in _metrics_for_groups(cfg, *groups):
        metrics[m["id"]] = {"name": m["name"], "unit": m.get("unit"), "data": _metric_series(conn, m["id"], start, end)}
    indices = {i["id"]: {"name": i["name"], "data": _index_series(conn, i["id"], start, end)}
               for i in _indices_for_market(cfg, "a")}
    return {"metrics": metrics, "indices": indices}


def export_hk(conn, cfg, rng):
    """复刻 /api/hk。"""
    start, end = _range(rng)
    indices = {i["id"]: {"name": i["name"], "data": _index_series(conn, i["id"], start, end)}
               for i in _indices_for_market(cfg, "hk")}
    south = _metric_series(conn, "hk_south", start, end)
    return {"indices": indices, "hk_south": south}


def export_global(conn, cfg, rng):
    """复刻 /api/global。"""
    start, end = _range(rng)
    stats_all = _stats_all()
    indices = {i["id"]: {"name": i["name"], "data": _index_series(conn, i["id"], start, end)}
               for i in _indices_for_market(cfg, "global")}
    extras = {}
    extras_signals = {}
    extras_stats = {}
    for mid in ("gold", "oil", "wti_oil", "comex_silver", "usdcnh", "a_qvix_300", "a_qvix_1000", "cn10y", "us10y", "cn_us_spread"):
        extras[mid] = _metric_series(conn, mid, start, end)
        extras_signals[mid] = _signals(conn, f"g.{mid}", start, end)
        extras_stats[mid] = _stats_for(stats_all, f"g.{mid}")
    return {"indices": indices, "extras": extras, "extras_signals": extras_signals, "extras_stats": extras_stats}


def export_sentiment(conn, cfg, rng):
    """复刻 /api/sentiment。"""
    start, end = _range(rng)
    stats_all = _stats_all()
    return {
        "a_sentiment": _score_series(conn, "a_sentiment", start, end),
        "cross_market": _score_series(conn, "cross_market", start, end),
        "signals": {
            "a_sentiment": _signals(conn, "s.a_sentiment", start, end),
            "cross_market": _signals(conn, "s.cross_market", start, end),
        },
        "stats": {
            "a_sentiment": _stats_for(stats_all, "s.a_sentiment"),
            "cross_market": _stats_for(stats_all, "s.cross_market"),
        },
    }


def export_industry(conn, cfg, rng):
    """复刻 /api/industry。"""
    start, end = _range(rng)
    stats_all = _stats_all()
    indices_cfg = _indices_for_market(cfg, "industry")
    indices = {}
    for i in indices_cfg:
        iid = i["id"]
        ind_code = iid[3:] if iid.startswith("sw_") else iid
        indices[iid] = {
            "name": i["name"],
            "data": _index_series(conn, iid, start, end),
            "signals": _signals(conn, iid, start, end),
            "stats": _stats_for(stats_all, iid),
            "fund_flow": _metric_series(conn, f"ind_flow_{iid}", start, end),
            "turnover": _metric_series(conn, f"ind_turn_{iid}", start, end),
            "width": _industry_width(conn, ind_code, start, end),
        }
    return {"indices": indices, "heatmap": _industry_heatmap(conn, cfg)}


def export_index_detail(conn, cfg, index_id):
    """复刻 /api/index/{index_id}?range=all。全历史 ohlc + signals + stats。"""
    start, end = _range("all")
    stats_all = _stats_all()
    return {
        "ohlc": _index_series(conn, index_id, start, end),
        "signals": _signals(conn, index_id, start, end),
        "stats": _stats_for(stats_all, index_id),
    }


def export_metrics(cfg):
    """复刻 /api/metrics。"""
    return [{"id": m["id"], "name": m["name"], "unit": m.get("unit")}
            for m in cfg.get("metrics", []) if m.get("enabled")]


# ============ JSON 序列化 + 写盘 ============

def _json_default(o):
    """处理 sqlite3 可能返回的非标准 JSON 类型。"""
    if isinstance(o, (sqlite3.Row,)):
        return dict(o)
    raise TypeError(f"not serializable: {type(o)}")


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    # 紧凑输出（separators 无空白）——industry-all.json 全历史约 26MB，
    # 默认 ', '/': ' 分隔会让其超 Cloudflare Pages 25MB 单文件限制。
    text = json.dumps(data, ensure_ascii=False, default=_json_default,
                      separators=(",", ":"))
    path.write_text(text, encoding="utf-8")
    return len(text)


def main():
    cfg = load_config()
    conn = get_conn()
    counts = {}

    # 1. overview
    counts["overview.json"] = write_json(DATA_DIR / "overview.json", export_overview(conn, cfg))
    print(f"  overview.json ({counts['overview.json']} bytes)")

    # 2-6. tab 端点 × 5 ranges
    tab_exporters = {
        "a-stock": export_a_stock,
        "hk": export_hk,
        "global": export_global,
        "sentiment": export_sentiment,
        "industry": export_industry,
    }
    for name, fn in tab_exporters.items():
        for rng in ALL_RANGES:
            fname = f"{name}-{rng}.json"
            data = fn(conn, cfg, rng)
            counts[fname] = write_json(DATA_DIR / fname, data)
            print(f"  {fname} ({counts[fname]} bytes)")

    # 7. metrics
    counts["metrics.json"] = write_json(DATA_DIR / "metrics.json", export_metrics(cfg))
    print(f"  metrics.json ({counts['metrics.json']} bytes)")

    # 8. index/{id}-all.json（44 个指数）
    all_indices = [i["id"] for i in cfg.get("indices", []) if i.get("enabled", True)]
    for iid in all_indices:
        fname = f"{iid}-all.json"
        data = export_index_detail(conn, cfg, iid)
        counts[f"index/{fname}"] = write_json(INDEX_DIR / fname, data)
    print(f"  index/*.json ({len(all_indices)} files)")

    conn.close()

    total_files = len(counts) + len(all_indices)
    total_bytes = sum(counts.values())
    print(f"\n导出完成：{len(counts)} 个 JSON 文件，{total_bytes / 1024 / 1024:.1f} MB")
    print(f"  - overview: 1")
    print(f"  - tab ranges: 5 tabs × 5 ranges = 25")
    print(f"  - metrics: 1")
    print(f"  - index detail: {len(all_indices)} (all range, full history)")
    print(f"输出目录: {DATA_DIR}")


if __name__ == "__main__":
    main()
