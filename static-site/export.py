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
from app.compute.position import compute_position  # noqa: E402
from app.compute.market_summary import generate_summary  # noqa: E402
from app.compute.signals import strategy_desc  # noqa: E402
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
    "a_volume_ratio",
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
    metric_cfg["a_volume_ratio"] = {"id": "a_volume_ratio", "name": "量比", "unit": ""}
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
            entry = {
                "id": mid,
                "name": m["name"],
                "unit": m.get("unit"),
                "value": r["value"],
                "date": r["date"],
                "source": r["source"],
            }
            if mid == "a_volume_ratio":
                sig_row = conn.execute(
                    "SELECT value FROM daily_metric WHERE metric_id='a_volume_signal' AND date=?",
                    (r["date"],),
                ).fetchone()
                signal_labels = {0: "正常", 1: "放量上涨", 2: "放量下跌", 3: "缩量上涨", 4: "缩量下跌"}
                entry["signal"] = signal_labels.get(int(sig_row["value"]) if sig_row and sig_row["value"] is not None else 0, "正常")
                amt_row = conn.execute(
                    "SELECT value FROM daily_metric WHERE metric_id='a_amount' AND date=?",
                    (r["date"],),
                ).fetchone()
                entry["amount"] = amt_row["value"] if amt_row else None
            today_metrics.append(entry)

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
    indices = {i["id"]: {"name": i["name"], "data": _index_series(conn, i["id"], start, end),
                         "strategy": strategy_desc(i["id"], cfg)}
               for i in _indices_for_market(cfg, "a")}
    return {"metrics": metrics, "indices": indices}


def export_hk(conn, cfg, rng):
    """复刻 /api/hk。"""
    start, end = _range(rng)
    indices = {i["id"]: {"name": i["name"], "data": _index_series(conn, i["id"], start, end),
                         "strategy": strategy_desc(i["id"], cfg)}
               for i in _indices_for_market(cfg, "hk")}
    south = _metric_series(conn, "hk_south", start, end)
    return {"indices": indices, "hk_south": south}


def export_global(conn, cfg, rng):
    """复刻 /api/global。"""
    start, end = _range(rng)
    stats_all = _stats_all()
    indices = {i["id"]: {"name": i["name"], "data": _index_series(conn, i["id"], start, end),
                         "strategy": strategy_desc(i["id"], cfg)}
               for i in _indices_for_market(cfg, "global")}
    extras = {}
    extras_signals = {}
    extras_stats = {}
    extras_strategy = {}
    for mid in ("gold", "oil", "wti_oil", "comex_silver", "usdcnh", "a_qvix_300", "a_qvix_1000", "cn10y", "us10y", "cn_us_spread"):
        extras[mid] = _metric_series(conn, mid, start, end)
        extras_signals[mid] = _signals(conn, f"g.{mid}", start, end)
        extras_stats[mid] = _stats_for(stats_all, f"g.{mid}")
        extras_strategy[mid] = strategy_desc(f"g.{mid}", cfg)
    return {"indices": indices, "extras": extras, "extras_signals": extras_signals,
            "extras_stats": extras_stats, "extras_strategy": extras_strategy}


def export_sentiment(conn, cfg, rng):
    """复刻 /api/sentiment。"""
    start, end = _range(rng)
    stats_all = _stats_all()
    return {
        "a_sentiment": _score_series(conn, "a_sentiment", start, end),
        "cross_market": _score_series(conn, "cross_market", start, end),
        "sentiment_sz50": _score_series(conn, "sentiment_sz50", start, end),
        "sentiment_hs300": _score_series(conn, "sentiment_hs300", start, end),
        "sentiment_csi500": _score_series(conn, "sentiment_csi500", start, end),
        "sentiment_csi1000": _score_series(conn, "sentiment_csi1000", start, end),
        "sentiment_cyb": _score_series(conn, "sentiment_cyb", start, end),
        "sentiment_kc50": _score_series(conn, "sentiment_kc50", start, end),
        "signals": {
            "a_sentiment": _signals(conn, "s.a_sentiment", start, end),
            "cross_market": _signals(conn, "s.cross_market", start, end),
            "sentiment_sz50": _signals(conn, "s.sentiment_sz50", start, end),
            "sentiment_hs300": _signals(conn, "s.sentiment_hs300", start, end),
            "sentiment_csi500": _signals(conn, "s.sentiment_csi500", start, end),
            "sentiment_csi1000": _signals(conn, "s.sentiment_csi1000", start, end),
            "sentiment_cyb": _signals(conn, "s.sentiment_cyb", start, end),
            "sentiment_kc50": _signals(conn, "s.sentiment_kc50", start, end),
        },
        "stats": {
            "a_sentiment": _stats_for(stats_all, "s.a_sentiment"),
            "cross_market": _stats_for(stats_all, "s.cross_market"),
            "sentiment_sz50": _stats_for(stats_all, "s.sentiment_sz50"),
            "sentiment_hs300": _stats_for(stats_all, "s.sentiment_hs300"),
            "sentiment_csi500": _stats_for(stats_all, "s.sentiment_csi500"),
            "sentiment_csi1000": _stats_for(stats_all, "s.sentiment_csi1000"),
            "sentiment_cyb": _stats_for(stats_all, "s.sentiment_cyb"),
            "sentiment_kc50": _stats_for(stats_all, "s.sentiment_kc50"),
        },
        "strategy": {
            "a_sentiment": strategy_desc("s.a_sentiment", cfg),
            "cross_market": strategy_desc("s.cross_market", cfg),
            "sentiment_sz50": strategy_desc("s.sentiment_sz50", cfg),
            "sentiment_hs300": strategy_desc("s.sentiment_hs300", cfg),
            "sentiment_csi500": strategy_desc("s.sentiment_csi500", cfg),
            "sentiment_csi1000": strategy_desc("s.sentiment_csi1000", cfg),
            "sentiment_cyb": strategy_desc("s.sentiment_cyb", cfg),
            "sentiment_kc50": strategy_desc("s.sentiment_kc50", cfg),
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
            "strategy": strategy_desc(iid, cfg),
            "fund_flow": _metric_series(conn, f"ind_flow_{iid}", start, end),
            "turnover": _metric_series(conn, f"ind_turn_{iid}", start, end),
            "width": _industry_width(conn, ind_code, start, end),
        }

    # Also include concept boards
    concepts_cfg = _indices_for_market(cfg, "concept")
    concepts = {}
    for i in concepts_cfg:
        iid = i["id"]
        concepts[iid] = {
            "name": i["name"],
            "data": _index_series(conn, iid, start, end),
            "signals": _signals(conn, iid, start, end),
            "stats": _stats_for(stats_all, iid),
            "strategy": strategy_desc(iid, cfg),
        }

    return {"indices": indices, "heatmap": _industry_heatmap(conn, cfg),
            "concepts": concepts}


def export_index_detail(conn, cfg, index_id):
    """复刻 /api/index/{index_id}?range=all。全历史 ohlc + signals + stats + strategy。"""
    start, end = _range("all")
    stats_all = _stats_all()
    return {
        "ohlc": _index_series(conn, index_id, start, end),
        "signals": _signals(conn, index_id, start, end),
        "stats": _stats_for(stats_all, index_id),
        "strategy": strategy_desc(index_id, cfg),
    }


def export_metrics(cfg):
    """复刻 /api/metrics。"""
    return [{"id": m["id"], "name": m["name"], "unit": m.get("unit")}
            for m in cfg.get("metrics", []) if m.get("enabled")]


def export_position():
    """复刻 /api/position。"""
    return {"positions": compute_position()}


def export_summary():
    """复刻 /api/summary。"""
    return generate_summary()


def export_rotation(conn):
    """复刻 /api/rotation。"""
    metric_ids = [
        "a_rotation_5d", "a_rotation_10d", "a_rotation_20d",
        "a_rotation_concept_5d", "a_rotation_concept_10d", "a_rotation_concept_20d",
    ]
    series: dict[str, dict[str, float]] = {}
    for mid in metric_ids:
        rows = conn.execute(
            "SELECT date, value FROM daily_metric WHERE metric_id=? ORDER BY date",
            (mid,),
        ).fetchall()
        series[mid] = {r["date"]: r["value"] for r in rows}

    all_dates = sorted(set().union(*[s.keys() for s in series.values()]))
    all_dates = all_dates[-250:]

    data = []
    for d in all_dates:
        data.append({
            "date": d,
            "speed_5d": series.get("a_rotation_5d", {}).get(d),
            "speed_10d": series.get("a_rotation_10d", {}).get(d),
            "speed_20d": series.get("a_rotation_20d", {}).get(d),
            "speed_concept_5d": series.get("a_rotation_concept_5d", {}).get(d),
            "speed_concept_10d": series.get("a_rotation_concept_10d", {}).get(d),
            "speed_concept_20d": series.get("a_rotation_concept_20d", {}).get(d),
        })

    # 最新值摘要：从 index_daily 直接取当日领涨板块
    last_date = all_dates[-1] if all_dates else ""
    sw_top3 = []
    concept_top3 = []
    sw_leader = None
    concept_leader = None
    if last_date:
        sw_rows = conn.execute(
            "SELECT index_id, pct_change FROM index_daily "
            "WHERE index_id LIKE 'sw_%' AND date=? AND pct_change IS NOT NULL "
            "ORDER BY pct_change DESC LIMIT 3",
            (last_date,),
        ).fetchall()
        sw_top3 = [{"index_id": r["index_id"], "pct_change": r["pct_change"]} for r in sw_rows]
        sw_leader = sw_top3[0]["index_id"] if sw_top3 else None

        thsc_rows = conn.execute(
            "SELECT index_id, pct_change FROM index_daily "
            "WHERE index_id LIKE 'thsc_%' AND date=? AND pct_change IS NOT NULL "
            "ORDER BY pct_change DESC LIMIT 3",
            (last_date,),
        ).fetchall()
        concept_top3 = [{"index_id": r["index_id"], "pct_change": r["pct_change"]} for r in thsc_rows]
        concept_leader = concept_top3[0]["index_id"] if concept_top3 else None

    latest_sw = {
        "speed_5d": data[-1]["speed_5d"] if data else None,
        "speed_10d": data[-1]["speed_10d"] if data else None,
        "speed_20d": data[-1]["speed_20d"] if data else None,
        "leader": sw_leader,
        "top3": sw_top3,
    }
    latest_concept = {
        "speed_5d": data[-1]["speed_concept_5d"] if data else None,
        "speed_10d": data[-1]["speed_concept_10d"] if data else None,
        "speed_20d": data[-1]["speed_concept_20d"] if data else None,
        "leader": concept_leader,
        "top3": concept_top3,
    }

    return {
        "data": data,
        "latest": {
            "date": last_date,
            "sw": latest_sw,
            "concept": latest_concept,
        },
    }


def export_futures(conn):
    """复刻 /api/futures。"""
    end = last_trading_day()
    one_year_ago = (datetime.strptime(end, "%Y%m%d") - timedelta(days=365)).strftime("%Y%m%d")

    # 近 1 年日度净持仓
    pos_rows = conn.execute(
        "SELECT date, variety, net_ratio FROM futures_position "
        "WHERE date>=? AND net_ratio IS NOT NULL ORDER BY date, variety",
        (one_year_ago,),
    ).fetchall()

    positions_by_date = {}
    for r in pos_rows:
        d = r["date"]
        if d not in positions_by_date:
            positions_by_date[d] = {}
        positions_by_date[d][r["variety"]] = r["net_ratio"]
    positions = [{"date": d, **v} for d, v in sorted(positions_by_date.items())]

    # 最新准确率
    accuracy_rows = conn.execute(
        "SELECT a.date, a.variety, a.window, a.follow_accuracy, a.contrarian_accuracy "
        "FROM futures_accuracy a "
        "INNER JOIN (SELECT variety, window, MAX(date) AS max_date FROM futures_accuracy GROUP BY variety, window) b "
        "ON a.variety=b.variety AND a.window=b.window AND a.date=b.max_date "
        "ORDER BY a.variety, a.window"
    ).fetchall()

    accuracy = {}
    for r in accuracy_rows:
        v = r["variety"]
        if v not in accuracy:
            accuracy[v] = {}
        w = f"{r['window']}d"
        accuracy[v][f"follow_{w}"] = r["follow_accuracy"]
        accuracy[v][f"contrarian_{w}"] = r["contrarian_accuracy"]

    return {"positions": positions, "accuracy": accuracy}


def export_ad_line(conn):
    """复刻 /api/ad_line。"""
    metrics = ["a_width_up_count", "a_width_down_count", "a_up_down_ratio",
               "a_ad_line", "a_ad_line_ma5", "a_ad_line_ma20"]
    series: dict[str, dict[str, float]] = {}
    for mid in metrics:
        rows = conn.execute(
            "SELECT date, value FROM daily_metric WHERE metric_id=? ORDER BY date",
            (mid,),
        ).fetchall()
        series[mid] = {r["date"]: r["value"] for r in rows}

    all_dates = sorted(set().union(*[s.keys() for s in series.values()]))
    all_dates = all_dates[-250:]

    data = []
    for d in all_dates:
        up = series.get("a_width_up_count", {}).get(d)
        down = series.get("a_width_down_count", {}).get(d)
        data.append({
            "date": d,
            "up_count": up,
            "down_count": down,
            "ratio": series.get("a_up_down_ratio", {}).get(d),
            "ad_line": series.get("a_ad_line", {}).get(d),
            "ad_line_ma5": series.get("a_ad_line_ma5", {}).get(d),
            "ad_line_ma20": series.get("a_ad_line_ma20", {}).get(d),
        })
    return {"data": data}


def export_volume_ratio(conn):
    """复刻 /api/volume_ratio。"""
    amount_rows = conn.execute(
        "SELECT date, value FROM daily_metric WHERE metric_id='a_amount' ORDER BY date"
    ).fetchall()
    amount_map = {r["date"]: r["value"] for r in amount_rows}

    ratio_rows = conn.execute(
        "SELECT date, value FROM daily_metric WHERE metric_id='a_volume_ratio' ORDER BY date"
    ).fetchall()
    ratio_map = {r["date"]: r["value"] for r in ratio_rows}

    ma5_rows = conn.execute(
        "SELECT date, value FROM daily_metric WHERE metric_id='a_amount_ma5' ORDER BY date"
    ).fetchall()
    ma5_map = {r["date"]: r["value"] for r in ma5_rows}

    ma20_rows = conn.execute(
        "SELECT date, value FROM daily_metric WHERE metric_id='a_amount_ma20' ORDER BY date"
    ).fetchall()
    ma20_map = {r["date"]: r["value"] for r in ma20_rows}

    signal_rows = conn.execute(
        "SELECT date, value FROM daily_metric WHERE metric_id='a_volume_signal' ORDER BY date"
    ).fetchall()
    signal_map = {r["date"]: int(r["value"]) for r in signal_rows if r["value"] is not None}

    pct_rows = conn.execute(
        "SELECT date, pct_change FROM index_daily WHERE index_id='sh' ORDER BY date"
    ).fetchall()
    pct_map = {r["date"]: r["pct_change"] for r in pct_rows}

    all_dates = sorted(set(amount_map.keys()) & set(ratio_map.keys()))
    all_dates = all_dates[-250:]

    signal_labels = {0: "正常", 1: "放量上涨", 2: "放量下跌", 3: "缩量上涨", 4: "缩量下跌"}

    data = []
    for d in all_dates:
        data.append({
            "date": d,
            "amount": amount_map.get(d),
            "ma5": ma5_map.get(d),
            "ma20": ma20_map.get(d),
            "ratio": ratio_map.get(d),
            "signal": signal_labels.get(signal_map.get(d), "正常"),
            "signal_code": signal_map.get(d, 0),
            "pct_change": pct_map.get(d),
        })
    return {"data": data}


def export_new_high_low(conn):
    """复刻 /api/new_high_low。"""
    from app.compute.new_high_low import INDICES, INDEX_NAMES, WINDOW_52W, WINDOW_20D

    metric_ids = ["a_nh_52w", "a_nl_52w", "a_nhnl_52w", "a_nh_20d", "a_nl_20d"]
    series = {}
    for mid in metric_ids:
        rows = conn.execute(
            "SELECT date, value FROM daily_metric WHERE metric_id=? ORDER BY date",
            (mid,),
        ).fetchall()
        series[mid] = {r["date"]: r["value"] for r in rows}

    all_dates = sorted(set().union(*[s.keys() for s in series.values()]))
    all_dates = all_dates[-250:]

    latest_date = all_dates[-1] if all_dates else None
    latest_details = []
    if latest_date:
        import pandas as pd
        placeholders = ",".join(["?"] * len(INDICES))
        idx_rows = conn.execute(
            f"SELECT date, index_id, close FROM index_daily "
            f"WHERE index_id IN ({placeholders}) AND close IS NOT NULL ORDER BY date",
            INDICES,
        ).fetchall()

        if idx_rows:
            df = pd.DataFrame(idx_rows, columns=["date", "index_id", "close"])
            pivoted = df.pivot(index="date", columns="index_id", values="close")

            for iid in INDICES:
                if iid not in pivoted.columns:
                    continue
                series_i = pivoted[iid].dropna()
                if latest_date not in series_i.index:
                    continue

                close_val = float(series_i.loc[latest_date])
                idx_loc = series_i.index.get_loc(latest_date)

                nh_52w = False
                nl_52w = False
                if idx_loc >= WINDOW_52W:
                    lookback_52w = series_i.iloc[idx_loc - WINDOW_52W:idx_loc]
                    if len(lookback_52w) > 0:
                        prev_high = float(lookback_52w.max())
                        prev_low = float(lookback_52w.min())
                        if close_val > prev_high:
                            nh_52w = True
                        if close_val < prev_low:
                            nl_52w = True

                nh_20d = False
                nl_20d = False
                if idx_loc >= WINDOW_20D:
                    lookback_20d = series_i.iloc[idx_loc - WINDOW_20D:idx_loc]
                    if len(lookback_20d) > 0:
                        prev_high = float(lookback_20d.max())
                        prev_low = float(lookback_20d.min())
                        if close_val > prev_high:
                            nh_20d = True
                        if close_val < prev_low:
                            nl_20d = True

                latest_details.append({
                    "index_id": iid,
                    "name": INDEX_NAMES.get(iid, iid),
                    "close": round(close_val, 2),
                    "nh_52w": nh_52w,
                    "nl_52w": nl_52w,
                    "nh_20d": nh_20d,
                    "nl_20d": nl_20d,
                })

    data = []
    for d in all_dates:
        entry = {
            "date": d,
            "nh_52w": series.get("a_nh_52w", {}).get(d),
            "nl_52w": series.get("a_nl_52w", {}).get(d),
            "nhnl_52w": series.get("a_nhnl_52w", {}).get(d),
            "nh_20d": series.get("a_nh_20d", {}).get(d),
            "nl_20d": series.get("a_nl_20d", {}).get(d),
            "details": latest_details if d == latest_date else [],
        }
        data.append(entry)

    return {"data": data}


def export_ma_alignment(conn):
    """复刻 /api/ma_alignment。"""
    from app.compute.ma_alignment import INDICES, INDEX_NAMES, MA_PERIODS

    metric_ids = ["a_ma_bullish", "a_ma_bearish", "a_ma_cross"]
    series = {}
    for mid in metric_ids:
        rows = conn.execute(
            "SELECT date, value FROM daily_metric WHERE metric_id=? ORDER BY date",
            (mid,),
        ).fetchall()
        series[mid] = {r["date"]: r["value"] for r in rows}

    all_dates = sorted(set().union(*[s.keys() for s in series.values()]))
    all_dates = all_dates[-250:]

    latest_date = all_dates[-1] if all_dates else None
    latest_details = []
    if latest_date:
        import pandas as pd
        placeholders = ",".join(["?"] * len(INDICES))
        idx_rows = conn.execute(
            f"SELECT date, index_id, close FROM index_daily "
            f"WHERE index_id IN ({placeholders}) AND close IS NOT NULL ORDER BY date",
            INDICES,
        ).fetchall()

        if idx_rows:
            df = pd.DataFrame(idx_rows, columns=["date", "index_id", "close"])
            pivoted = df.pivot(index="date", columns="index_id", values="close")

            for iid in INDICES:
                if iid not in pivoted.columns:
                    continue
                series_i = pivoted[iid].dropna()
                if len(series_i) < max(MA_PERIODS) or latest_date not in series_i.index:
                    continue

                vals = {}
                for p in MA_PERIODS:
                    ma_vals = series_i.rolling(p, min_periods=p).mean()
                    v = ma_vals.get(latest_date)
                    vals[f"ma{p}"] = round(float(v), 2) if v is not None and not pd.isna(v) else None

                if any(v is None for v in vals.values()):
                    continue

                if vals["ma5"] > vals["ma10"] > vals["ma20"] > vals["ma60"]:
                    alignment = "bullish"
                elif vals["ma5"] < vals["ma10"] < vals["ma20"] < vals["ma60"]:
                    alignment = "bearish"
                else:
                    alignment = "cross"

                latest_details.append({
                    "index_id": iid,
                    "name": INDEX_NAMES.get(iid, iid),
                    "alignment": alignment,
                    "ma5": vals["ma5"],
                    "ma10": vals["ma10"],
                    "ma20": vals["ma20"],
                    "ma60": vals["ma60"],
                })

    data = []
    for d in all_dates:
        entry = {
            "date": d,
            "bullish": series.get("a_ma_bullish", {}).get(d),
            "bearish": series.get("a_ma_bearish", {}).get(d),
            "cross": series.get("a_ma_cross", {}).get(d),
            "details": latest_details if d == latest_date else [],
        }
        data.append(entry)

    return {"data": data}


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

    # 7.5. futures
    counts["futures.json"] = write_json(DATA_DIR / "futures.json", export_futures(conn))
    print(f"  futures.json ({counts['futures.json']} bytes)")

    # 7.6. ad_line
    counts["ad_line.json"] = write_json(DATA_DIR / "ad_line.json", export_ad_line(conn))
    print(f"  ad_line.json ({counts['ad_line.json']} bytes)")

    # 7.7. volume_ratio
    counts["volume_ratio.json"] = write_json(DATA_DIR / "volume_ratio.json", export_volume_ratio(conn))
    print(f"  volume_ratio.json ({counts['volume_ratio.json']} bytes)")

    # 7.8. position
    counts["position.json"] = write_json(DATA_DIR / "position.json", export_position())
    print(f"  position.json ({counts['position.json']} bytes)")

    # 7.9. summary
    counts["summary.json"] = write_json(DATA_DIR / "summary.json", export_summary())
    print(f"  summary.json ({counts['summary.json']} bytes)")

    # 7.10. rotation
    counts["rotation.json"] = write_json(DATA_DIR / "rotation.json", export_rotation(conn))
    print(f"  rotation.json ({counts['rotation.json']} bytes)")

    # 7.11. new_high_low
    counts["new_high_low.json"] = write_json(DATA_DIR / "new_high_low.json", export_new_high_low(conn))
    print(f"  new_high_low.json ({counts['new_high_low.json']} bytes)")

    # 7.12. ma_alignment
    counts["ma_alignment.json"] = write_json(DATA_DIR / "ma_alignment.json", export_ma_alignment(conn))
    print(f"  ma_alignment.json ({counts['ma_alignment.json']} bytes)")

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
