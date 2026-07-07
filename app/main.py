"""FastAPI 后端：提供看板数据 + 手动补录 + 静态前端。"""
import re
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .calendar import last_trading_day
from .collector.fetchers import load_config
from .db import get_conn

app = FastAPI(title="情绪数据复盘看板")
WEB_DIR = Path(__file__).resolve().parent.parent / "web"

RANGES = {"1m": 30, "3m": 90, "6m": 180, "1y": 365}
VALID_RANGES = set(RANGES) | {"all"}
_DATE_RE = re.compile(r"^\d{8}$")


def range_dep(range: str = "1y"):
    """range 参数校验：非法值返回 400 而非静默回退。"""
    if range not in VALID_RANGES:
        raise HTTPException(
            status_code=400,
            detail=f"无效的 range 参数: {range}，可选 {', '.join(sorted(VALID_RANGES))}",
        )
    return range


def _valid_index_ids() -> set[str]:
    cfg = load_config()
    return {i["id"] for i in cfg.get("indices", []) if i.get("enabled", True)}


def _valid_metric_ids() -> set[str]:
    cfg = load_config()
    return {m["id"] for m in cfg.get("metrics", []) if m.get("enabled")}


def _range(rng: str):
    end = last_trading_day()
    if rng == "all":
        return "20100101", end
    days = RANGES.get(rng, 365)
    start = (datetime.strptime(end, "%Y%m%d") - timedelta(days=days)).strftime("%Y%m%d")
    return start, end


def _metric_series(metric_id, start, end):
    conn = get_conn()
    rows = conn.execute(
        "SELECT date, value FROM daily_metric WHERE metric_id=? AND date BETWEEN ? AND ? ORDER BY date",
        (metric_id, start, end),
    ).fetchall()
    conn.close()
    return [{"date": r["date"], "value": r["value"]} for r in rows]


def _index_series(index_id, start, end):
    conn = get_conn()
    rows = conn.execute(
        "SELECT date, open, high, low, close, pct_change, amount FROM index_daily "
        "WHERE index_id=? AND date BETWEEN ? AND ? ORDER BY date",
        (index_id, start, end),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _score_series(score_id, start, end):
    conn = get_conn()
    rows = conn.execute(
        "SELECT date, value, is_freeze, is_overheat, components FROM score_daily "
        "WHERE score_id=? AND date BETWEEN ? AND ? ORDER BY date",
        (score_id, start, end),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _signals(index_id=None, start=None, end=None):
    conn = get_conn()
    q = "SELECT date, index_id, signal, reason FROM signal_daily WHERE date BETWEEN ? AND ?"
    params = [start, end]
    if index_id:
        q += " AND index_id=?"
        params.append(index_id)
    rows = conn.execute(q + " ORDER BY date", params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _metrics_for_groups(*groups):
    cfg = load_config()
    return [m for m in cfg.get("metrics", []) if m.get("group") in groups and m.get("enabled")]


def _indices_for_market(market):
    cfg = load_config()
    return [i for i in cfg.get("indices", []) if i.get("market") == market and i.get("enabled", True)]


# ============ API ============

# 概览 KPI 卡片所需指标（来自 daily_metric，按展示顺序）
KPI_METRIC_IDS = [
    "a_width_zt_count",     # 涨停数
    "a_width_dt_count",     # 跌停数
    "a_width_zhaban_rate",  # 炸板率
    "a_amount",             # 成交额
    "a_fund_north",         # 北向资金（停更，最新非空 20240816）
    "a_fund_margin",        # 两融余额
]
# sparkline 网格所需指数（按展示顺序）
SPARKLINE_INDEX_IDS = ["sh", "sz", "hs300", "cyb", "kc50", "hsi", "hstech"]


@app.get("/api/overview")
def overview():
    conn = get_conn()
    # 最新分数日期（作为「今日」基准；指数/部分指标可能滞后于该日）
    row = conn.execute("SELECT max(date) FROM score_daily").fetchone()
    score_date = row[0] if row and row[0] else last_trading_day()
    scores = {r["score_id"]: dict(r) for r in conn.execute(
        "SELECT score_id, value, is_freeze, is_overheat FROM score_daily WHERE date=?", (score_date,)
    ).fetchall()}

    # KPI 指标今日快照：每个指标取最新非空值（北向停更后仍能取到 20240816）
    cfg = load_config()
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

    # 今日买卖点 + 近期冰点/过热日（保留原逻辑）
    sigs = [dict(r) for r in conn.execute(
        "SELECT date, index_id, signal, reason FROM signal_daily WHERE date=?", (score_date,)
    ).fetchall()]
    freeze_days = [dict(r) for r in conn.execute(
        "SELECT date, score_id, value FROM score_daily WHERE is_freeze=1 ORDER BY date DESC LIMIT 5"
    ).fetchall()]

    # 指数 sparkline：近 30 个交易日收盘 + 当日涨跌幅
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

    # 市场宽度近 1 月（上涨/下跌家数，用于堆叠面积）
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

    # 近 6 月分数序列（跨市场分 + A 股情绪分）
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

    conn.close()
    return {
        "date": score_date,
        # 兼容字段（保留）
        "scores": scores,
        "signals_today": sigs,
        "recent_freeze": freeze_days,
        # 新增：今日快照
        "today": {
            "scores": {k: {**v, "date": score_date} for k, v in scores.items()},
            "metrics": today_metrics,
        },
        "indices_sparkline": indices_sparkline,
        "width_1m": width_1m,
        "cross_market_6m": cross_6m,
        "a_sentiment_6m": asent_6m,
        # F1：申万行业涨跌幅热力图（接 G1 概览第 7 区块）
        "industry_heatmap": _industry_heatmap(),
    }


@app.get("/api/a-stock")
def a_stock(range: str = Depends(range_dep)):
    start, end = _range(range)
    groups = ("a_width", "a_fund", "a_sentiment", "lhb", "unlock", "ipo", "cov")
    metrics = {}
    for m in _metrics_for_groups(*groups):
        metrics[m["id"]] = {"name": m["name"], "unit": m.get("unit"), "data": _metric_series(m["id"], start, end)}
    indices = {i["id"]: {"name": i["name"], "data": _index_series(i["id"], start, end)} for i in _indices_for_market("a")}
    return {"metrics": metrics, "indices": indices}


@app.get("/api/hk")
def hk(range: str = Depends(range_dep)):
    start, end = _range(range)
    indices = {i["id"]: {"name": i["name"], "data": _index_series(i["id"], start, end)} for i in _indices_for_market("hk")}
    south = _metric_series("hk_south", start, end)
    return {"indices": indices, "hk_south": south}


@app.get("/api/global")
def global_(range: str = Depends(range_dep)):
    start, end = _range(range)
    indices = {i["id"]: {"name": i["name"], "data": _index_series(i["id"], start, end)} for i in _indices_for_market("global")}
    extras = {}
    for mid in ("gold", "oil", "wti_oil", "comex_silver", "usdcnh", "a_qvix_300", "a_qvix_1000", "cn10y", "us10y", "cn_us_spread"):
        extras[mid] = _metric_series(mid, start, end)
    return {"indices": indices, "extras": extras}


@app.get("/api/sentiment")
def sentiment(range: str = Depends(range_dep)):
    start, end = _range(range)
    return {
        "a_sentiment": _score_series("a_sentiment", start, end),
        "cross_market": _score_series("cross_market", start, end),
    }


def _industry_heatmap():
    """申万一级行业近 1 日 / 近 5 日涨跌幅（用于热力图）。不受 range 影响，固定取最新。"""
    cfg = load_config()
    indices = [i for i in cfg.get("indices", []) if i.get("market") == "industry" and i.get("enabled", True)]
    conn = get_conn()
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
        # 近 5 日累计：用 close 算 (latest / close_5d_ago - 1) * 100
        pct_5d = None
        if len(rows) >= 6 and rows[5]["close"]:
            pct_5d = (latest["close"] / rows[5]["close"] - 1) * 100
        elif len(rows) >= 2 and rows[-1]["close"]:
            # 不足 6 个交易日，用最早可用的算（标注实际天数）
            pct_5d = (latest["close"] / rows[-1]["close"] - 1) * 100
        out.append({
            "id": iid,
            "name": idx["name"],
            "pct_1d": pct_1d,
            "pct_5d": pct_5d,
            "last_date": latest["date"],
        })
    conn.close()
    return out


def _industry_width(industry_code: str, start: str, end: str):
    """行业内宽度序列（F3，从 industry_width_daily 查）。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT date, up_count, down_count, zt_count, dt_count, zb_count, seal_rate, amount "
        "FROM industry_width_daily WHERE industry_code=? AND date BETWEEN ? AND ? ORDER BY date",
        (industry_code, start, end),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/industry")
def industry(range: str = Depends(range_dep)):
    start, end = _range(range)
    indices_cfg = _indices_for_market("industry")
    indices = {}
    for i in indices_cfg:
        iid = i["id"]
        # 行业指数代码（sw_801010 → 801010）
        ind_code = iid[3:] if iid.startswith("sw_") else iid
        indices[iid] = {
            "name": i["name"],
            "data": _index_series(iid, start, end),
            "signals": _signals(iid, start, end),
            # F2：行业资金流 + 换手率（daily_metric）；成交额已在 data[].amount（F1 index_daily）
            "fund_flow": _metric_series(f"ind_flow_{iid}", start, end),
            "turnover": _metric_series(f"ind_turn_{iid}", start, end),
            # F3：行业内宽度（涨跌家数/涨停/跌停/炸板/封板率/成交额）
            "width": _industry_width(ind_code, start, end),
        }
    return {"indices": indices, "heatmap": _industry_heatmap()}


@app.get("/api/index/{index_id}")
def index_detail(index_id: str, range: str = Depends(range_dep)):
    if index_id not in _valid_index_ids():
        raise HTTPException(status_code=404, detail=f"未知的指数代码: {index_id}")
    start, end = _range(range)
    return {"ohlc": _index_series(index_id, start, end), "signals": _signals(index_id, start, end)}


@app.get("/api/metrics")
def metrics_list():
    """供手动补录表单用的指标列表。"""
    cfg = load_config()
    return [{"id": m["id"], "name": m["name"], "unit": m.get("unit")} for m in cfg.get("metrics", []) if m.get("enabled")]


class ManualEntry(BaseModel):
    date: str
    metric_id: str
    value: float
    note: str = ""


def _validate_date(date: str) -> None:
    if not _DATE_RE.match(date):
        raise HTTPException(status_code=400, detail="日期格式错误，要求 yyyyMMdd（如 20260703）")
    try:
        datetime.strptime(date, "%Y%m%d")
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效的日期: {date}")


@app.get("/api/manual/check")
def manual_check(date: str, metric_id: str):
    """查某日期+指标是否已有数据，供前端覆盖确认。"""
    conn = get_conn()
    row = conn.execute(
        "SELECT value, source FROM daily_metric WHERE date=? AND metric_id=?",
        (date, metric_id),
    ).fetchone()
    conn.close()
    if row:
        return {"exists": True, "value": row["value"], "source": row["source"]}
    return {"exists": False}


@app.post("/api/manual")
def manual(entry: ManualEntry):
    _validate_date(entry.date)
    if entry.metric_id not in _valid_metric_ids():
        raise HTTPException(status_code=400, detail=f"未知的指标 ID: {entry.metric_id}")
    now = datetime.now().isoformat()
    conn = get_conn()
    conn.execute(
        "INSERT INTO manual_entry (date, metric_id, value, note, created_at) VALUES (?,?,?,?,?)",
        (entry.date, entry.metric_id, entry.value, entry.note, now),
    )
    conn.execute(
        "INSERT INTO daily_metric (date, metric_id, value, source, updated_at) VALUES (?,?,?,?,?) "
        "ON CONFLICT(date, metric_id) DO UPDATE SET value=excluded.value, source='manual', updated_at=excluded.updated_at",
        (entry.date, entry.metric_id, entry.value, "manual", now),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


# ============ 前端静态文件 ============
@app.get("/")
def root():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
