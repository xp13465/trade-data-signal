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
from .compute import signal_stats as sigstats
from .compute.position import compute_position, _label_from_percentile, _level_from_percentile
from .compute.market_summary import generate_summary
from .compute.rotation import compute_rotation
from .compute.signals import strategy_desc
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


# 买卖点回测 stats（读 data/signal_stats.json，由 app.compute.signal_stats 定期重算）。
# 返回 {index_id: {buy/buy_aux/sell: {5d/10d/20d: {win_rate,pl,mean,n}}}}；文件缺失返 {}。
def _stats_all() -> dict:
    return sigstats.load()


def _stats_for(index_id: str) -> dict:
    """单品种 stats：{buy:{...}, buy_aux:{...}, sell:{...}}；无则空 dict。"""
    return _stats_all().get(index_id, {})  # force-reload trigger


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
    "a_volume_ratio",       # 量比（放量/缩量）
    "a_fund_north",         # 北向资金（停更，最新非空 20240816）
    "a_fund_margin",        # 两融余额
]
# sparkline 网格所需指数（按展示顺序）
SPARKLINE_INDEX_IDS = ["sh", "sz", "hs300", "sz50", "cyb", "kc50", "csi500", "csi1000", "hsi", "hstech"]


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
    # 量比指标不在 indicators.yaml 中，手动补充
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
            # 量比额外附上信号文本
            if mid == "a_volume_ratio":
                sig_row = conn.execute(
                    "SELECT value FROM daily_metric WHERE metric_id='a_volume_signal' AND date=?",
                    (r["date"],),
                ).fetchone()
                signal_labels = {0: "正常", 1: "放量上涨", 2: "放量下跌", 3: "缩量上涨", 4: "缩量下跌"}
                entry["signal"] = signal_labels.get(int(sig_row["value"]) if sig_row and sig_row["value"] is not None else 0, "正常")
                entry["amount"] = conn.execute(
                    "SELECT value FROM daily_metric WHERE metric_id='a_amount' AND date=?",
                    (r["date"],),
                ).fetchone()
                entry["amount"] = entry["amount"]["value"] if entry["amount"] else None
            today_metrics.append(entry)

    # 近期买卖点（近15交易日，含今日）+ 近期冰点日（近30交易日）
    # 用日历日范围覆盖足够交易日：15交易日≈25天，30交易日≈45天
    # 前端按日分组（一天一行），故取"最近9个日期"的全部记录而非LIMIT 9条记录
    sig_start = (datetime.strptime(score_date, "%Y%m%d") - timedelta(days=25)).strftime("%Y%m%d")
    sig_dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM signal_daily WHERE date >= ? ORDER BY date DESC LIMIT 9",
        (sig_start,)
    ).fetchall()]
    sigs = []
    if sig_dates:
        sigs = [dict(r) for r in conn.execute(
            "SELECT date, index_id, signal, reason FROM signal_daily "
            "WHERE date IN (%s) ORDER BY date DESC, index_id" % ",".join("?" * len(sig_dates)),
            sig_dates
        ).fetchall()]
    freeze_start = (datetime.strptime(score_date, "%Y%m%d") - timedelta(days=120)).strftime("%Y%m%d")
    freeze_dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM score_daily WHERE is_freeze=1 AND date >= ? ORDER BY date DESC LIMIT 9",
        (freeze_start,)
    ).fetchall()]
    freeze_days = []
    if freeze_dates:
        freeze_days = [dict(r) for r in conn.execute(
            "SELECT date, score_id, value FROM score_daily WHERE is_freeze=1 "
            "AND date IN (%s) ORDER BY date DESC" % ",".join("?" * len(freeze_dates)),
            freeze_dates
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
    fg_6m = [{"date": r["date"], "value": r["value"], "is_freeze": r["is_freeze"], "is_overheat": r["is_overheat"]}
             for r in conn.execute(
                 "SELECT date, value, is_freeze, is_overheat FROM score_daily "
                 "WHERE score_id='fear_greed' AND date>=? ORDER BY date",
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
        "fear_greed_6m": fg_6m,
        # F1：申万行业涨跌幅热力图（接 G1 概览第 7 区块）
        "industry_heatmap": _industry_heatmap(),
    }


@app.get("/api/a-stock")
def a_stock(range: str = Depends(range_dep)):
    start, end = _range(range)
    cfg = load_config()
    groups = ("a_width", "a_fund", "a_sentiment", "lhb", "unlock", "ipo", "cov")
    metrics = {}
    for m in _metrics_for_groups(*groups):
        metrics[m["id"]] = {"name": m["name"], "unit": m.get("unit"), "data": _metric_series(m["id"], start, end)}
    indices = {i["id"]: {"name": i["name"], "data": _index_series(i["id"], start, end),
                         "strategy": strategy_desc(i["id"], cfg)} for i in _indices_for_market("a")}
    return {"metrics": metrics, "indices": indices}


@app.get("/api/hk")
def hk(range: str = Depends(range_dep)):
    start, end = _range(range)
    cfg = load_config()
    indices = {i["id"]: {"name": i["name"], "data": _index_series(i["id"], start, end),
                         "strategy": strategy_desc(i["id"], cfg)} for i in _indices_for_market("hk")}
    south = _metric_series("hk_south", start, end)
    return {"indices": indices, "hk_south": south}


@app.get("/api/global")
def global_(range: str = Depends(range_dep)):
    start, end = _range(range)
    cfg = load_config()
    indices = {i["id"]: {"name": i["name"], "data": _index_series(i["id"], start, end),
                         "strategy": strategy_desc(i["id"], cfg)} for i in _indices_for_market("global")}
    extras = {}
    extras_signals = {}
    extras_stats = {}
    extras_strategy = {}
    for mid in ("gold", "oil", "wti_oil", "comex_silver", "usdcnh", "a_qvix_300", "a_qvix_1000", "cn10y", "us10y", "cn_us_spread"):
        extras[mid] = _metric_series(mid, start, end)
        extras_signals[mid] = _signals(f"g.{mid}", start, end)
        extras_stats[mid] = _stats_for(f"g.{mid}")
        extras_strategy[mid] = strategy_desc(f"g.{mid}", cfg)
    return {"indices": indices, "extras": extras, "extras_signals": extras_signals,
            "extras_stats": extras_stats, "extras_strategy": extras_strategy}


@app.get("/api/sentiment")
def sentiment(range: str = Depends(range_dep)):
    start, end = _range(range)
    cfg = load_config()
    return {
        "a_sentiment": _score_series("a_sentiment", start, end),
        "cross_market": _score_series("cross_market", start, end),
        "sentiment_sz50": _score_series("sentiment_sz50", start, end),
        "sentiment_hs300": _score_series("sentiment_hs300", start, end),
        "sentiment_csi500": _score_series("sentiment_csi500", start, end),
        "sentiment_csi1000": _score_series("sentiment_csi1000", start, end),
        "sentiment_cyb": _score_series("sentiment_cyb", start, end),
        "sentiment_kc50": _score_series("sentiment_kc50", start, end),
        "fear_greed": _score_series("fear_greed", start, end),
        "signals": {
            "a_sentiment": _signals("s.a_sentiment", start, end),
            "cross_market": _signals("s.cross_market", start, end),
            "sentiment_sz50": _signals("s.sentiment_sz50", start, end),
            "sentiment_hs300": _signals("s.sentiment_hs300", start, end),
            "sentiment_csi500": _signals("s.sentiment_csi500", start, end),
            "sentiment_csi1000": _signals("s.sentiment_csi1000", start, end),
            "sentiment_cyb": _signals("s.sentiment_cyb", start, end),
            "sentiment_kc50": _signals("s.sentiment_kc50", start, end),
        },
        "stats": {
            "a_sentiment": _stats_for("s.a_sentiment"),
            "cross_market": _stats_for("s.cross_market"),
            "sentiment_sz50": _stats_for("s.sentiment_sz50"),
            "sentiment_hs300": _stats_for("s.sentiment_hs300"),
            "sentiment_csi500": _stats_for("s.sentiment_csi500"),
            "sentiment_csi1000": _stats_for("s.sentiment_csi1000"),
            "sentiment_cyb": _stats_for("s.sentiment_cyb"),
            "sentiment_kc50": _stats_for("s.sentiment_kc50"),
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
        "futures": _futures_data(),
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


# 品种名映射（代码 → 中文）
_VARIETY_NAMES = {
    "IF": "沪深300期货", "IC": "中证500期货",
    "IH": "上证50期货", "IM": "中证1000期货",
    "综合": "综合",
}
# 角色名映射（DB key → 对外展示）
_ROLE_DISPLAY = {
    "top20": "机构(前20)",
    "中信期货": "中信期货",
    "国泰君安": "国泰君安",
}
_ROLES_ORDER = ["top20", "中信期货", "国泰君安"]


def _futures_data():
    """期货持仓数据：近 1 年日度净持仓（按角色分组）+ 最新准确率（按角色分组）。"""
    conn = get_conn()

    ltd = last_trading_day()
    # 近 1 年日度净持仓（net_position 手数 + net_ratio 比例），按角色分组
    one_year_ago = (datetime.strptime(ltd, "%Y%m%d") - timedelta(days=365)).strftime("%Y%m%d")
    pos_rows = conn.execute(
        "SELECT date, variety, role, net_position, net_ratio FROM futures_position "
        "WHERE date>=? AND (net_position IS NOT NULL OR net_ratio IS NOT NULL) ORDER BY date, variety, role",
        (one_year_ago,),
    ).fetchall()

    # 按日期 → 角色 → 品种 pivot（手数 + 比例各一份）
    positions_by_date: dict[str, dict] = {}
    ratio_by_date: dict[str, dict] = {}
    for r in pos_rows:
        d = r["date"]
        role_display = _ROLE_DISPLAY.get(r["role"], r["role"])
        if d not in positions_by_date:
            positions_by_date[d] = {}
            ratio_by_date[d] = {}
        if role_display not in positions_by_date[d]:
            positions_by_date[d][role_display] = {}
            ratio_by_date[d][role_display] = {}
        positions_by_date[d][role_display][_VARIETY_NAMES.get(r["variety"], r["variety"])] = r["net_position"]
        ratio_by_date[d][role_display][_VARIETY_NAMES.get(r["variety"], r["variety"])] = r["net_ratio"]
    positions = [{"date": d, **v} for d, v in sorted(positions_by_date.items())]
    positions_ratio = [{"date": d, **v} for d, v in sorted(ratio_by_date.items())]

    # 最新 summary：取最新日期，按角色列出各品种 net_position（手数，非 ratio）
    summary_date = positions[-1]["date"] if positions else ltd
    summary_roles = {}
    # 查 net_position（手数）用于 summary
    summary_rows = conn.execute(
        "SELECT variety, role, net_position FROM futures_position "
        "WHERE date=? AND net_position IS NOT NULL",
        (summary_date,),
    ).fetchall()
    for r in summary_rows:
        role_display = _ROLE_DISPLAY.get(r["role"], r["role"])
        vname = _VARIETY_NAMES.get(r["variety"], r["variety"])
        if role_display not in summary_roles:
            summary_roles[role_display] = {}
        summary_roles[role_display][vname] = round(r["net_position"], 0)

    summary = {
        "date": summary_date,
        "品种": ["沪深300期货", "中证500期货", "上证50期货", "中证1000期货"],
        "roles": summary_roles,
    }

    # 最新准确率数据（仅综合品种，按角色+窗口，每个角色取最新 date 的 30/60/120 日窗口）
    accuracy_rows = conn.execute(
        "SELECT a.date, a.role, a.window, a.follow_accuracy, a.contrarian_accuracy, "
        "a.follow_n, a.contrarian_n "
        "FROM futures_accuracy a "
        "INNER JOIN (SELECT role, window, MAX(date) AS max_date "
        "            FROM futures_accuracy WHERE variety='综合' GROUP BY role, window) b "
        "ON a.role=b.role AND a.window=b.window AND a.date=b.max_date "
        "WHERE a.variety='综合' "
        "ORDER BY a.role, a.window"
    ).fetchall()

    accuracy: dict[str, dict] = {}
    for r in accuracy_rows:
        role_display = _ROLE_DISPLAY.get(r["role"], r["role"])
        if role_display not in accuracy:
            accuracy[role_display] = {}
        w = f"{r['window']}d"
        accuracy[role_display][w] = {
            "follow": r["follow_accuracy"],
            "contrarian": r["contrarian_accuracy"],
            "follow_n": r["follow_n"],
            "contrarian_n": r["contrarian_n"],
        }

    # 历史准确率序列（按日期 pivot，供前端折线图 tooltip 使用）
    acc_history_rows = conn.execute(
        "SELECT date, role, window, follow_accuracy, contrarian_accuracy "
        "FROM futures_accuracy WHERE variety='综合' "
        "ORDER BY date, role, window"
    ).fetchall()
    acc_history: list[dict] = []
    _acc_by_date: dict[str, dict] = {}
    for r in acc_history_rows:
        d = r["date"]
        role_display = _ROLE_DISPLAY.get(r["role"], r["role"])
        if d not in _acc_by_date:
            _acc_by_date[d] = {}
        if role_display not in _acc_by_date[d]:
            _acc_by_date[d][role_display] = {}
        w = f"{r['window']}d"
        _acc_by_date[d][role_display][w] = {
            "follow": r["follow_accuracy"],
            "contrarian": r["contrarian_accuracy"],
        }
    for d in sorted(_acc_by_date.keys()):
        acc_history.append({"date": d, **_acc_by_date[d]})

    conn.close()
    return {"summary": summary, "positions": positions, "positions_ratio": positions_ratio, "accuracy": accuracy, "accuracy_history": acc_history}


@app.get("/api/futures")
def futures_data():
    """期货机构净多空持仓：日度净持仓序列 + 最新准确率。"""
    return _futures_data()


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
    cfg = load_config()
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
            "stats": _stats_for(iid),
            "strategy": strategy_desc(iid, cfg),
            # F2：行业资金流 + 换手率（daily_metric）；成交额已在 data[].amount（F1 index_daily）
            "fund_flow": _metric_series(f"ind_flow_{iid}", start, end),
            "turnover": _metric_series(f"ind_turn_{iid}", start, end),
            # F3：行业内宽度（涨跌家数/涨停/跌停/炸板/封板率/成交额）
            "width": _industry_width(ind_code, start, end),
        }

    # Also include concept boards
    concepts_cfg = _indices_for_market("concept")
    concepts = {}
    for i in concepts_cfg:
        iid = i["id"]
        concepts[iid] = {
            "name": i["name"],
            "data": _index_series(iid, start, end),
            "signals": _signals(iid, start, end),
            "stats": _stats_for(iid),
            "strategy": strategy_desc(iid, cfg),
        }

    return {"indices": indices, "heatmap": _industry_heatmap(),
            "concepts": concepts}


@app.get("/api/ad_line")
def ad_line():
    """AD Line（腾落线）+ 涨跌家数比，最近 250 个交易日。"""
    conn = get_conn()
    # 分别查四个指标序列
    metrics = ["a_width_up_count", "a_width_down_count", "a_up_down_ratio",
               "a_ad_line", "a_ad_line_ma5", "a_ad_line_ma20"]
    series: dict[str, dict[str, float]] = {}
    for mid in metrics:
        rows = conn.execute(
            "SELECT date, value FROM daily_metric WHERE metric_id=? ORDER BY date",
            (mid,),
        ).fetchall()
        series[mid] = {r["date"]: r["value"] for r in rows}

    # 收集所有日期
    all_dates = sorted(set().union(*[s.keys() for s in series.values()]))
    # 取最近 250 个交易日
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
    conn.close()
    return {"data": data}


@app.get("/api/volume_ratio")
def volume_ratio():
    """成交量对比（放量/缩量标注），最近 250 个交易日。"""
    conn = get_conn()
    # 查成交额
    amount_rows = conn.execute(
        "SELECT date, value FROM daily_metric WHERE metric_id='a_amount' ORDER BY date"
    ).fetchall()
    amount_map = {r["date"]: r["value"] for r in amount_rows}

    # 查量比指标
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

    # 查上证涨跌幅
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
    conn.close()
    return {"data": data}


@app.get("/api/new_high_low")
def new_high_low():
    """新高新低家数：8 个主要指数的 52周/20日 NH-NL 统计。"""
    from .compute.new_high_low import INDEX_NAMES, INDICES, WINDOW_52W, WINDOW_20D
    conn = get_conn()

    # 从 daily_metric 读取历史数据
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

    # 实时计算最新日期的 details（指数级别的新高新低）
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

    conn.close()
    return {"data": data}


@app.get("/api/ma_alignment")
def ma_alignment():
    """均线排列状态：8 个主要指数的 MA5/MA10/MA20/MA60 多头/空头/震荡统计。"""
    from .compute.ma_alignment import INDICES, INDEX_NAMES, MA_PERIODS
    conn = get_conn()

    # 从 daily_metric 读取历史数据
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

    # 实时计算最新日期的 details（各指数均线状态）
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

    conn.close()
    return {"data": data}


@app.get("/api/position")
def position():
    """大盘位置感：8 个 A 股指数的 1年/3年/5年分位 + 标签。"""
    return {"positions": compute_position()}


@app.get("/api/summary")
def summary(date: str | None = None):
    """一句话市场总结：情绪+涨跌+家数+量能+热点板块。"""
    return generate_summary(date)


@app.get("/api/signal_freq")
def signal_freq():
    """全局信号频率统计：汇总所有品种 buy/buy_aux/sell 的今年次数/总计/月均。"""
    from datetime import datetime
    all_stats = sigstats.load()
    freq = {"buy": {"year": 0, "total": 0}, "buy_aux": {"year": 0, "total": 0}, "sell": {"year": 0, "total": 0}}
    cur_month = datetime.now().month  # 用于计算月均
    for iid, sigs in all_stats.items():
        if iid.startswith("_"):
            continue
        for sig in ("buy", "buy_aux", "sell"):
            s = sigs.get(sig, {})
            f = s.get("frequency")
            if f:
                freq[sig]["year"] += f.get("year_count", 0)
                freq[sig]["total"] += f.get("total_count", 0)
    for sig in freq:
        y = freq[sig]["year"]
        freq[sig]["monthly_avg"] = round(y / max(cur_month, 1), 2)
    return freq


@app.get("/api/rotation")
def rotation():
    """板块轮动速度：SW 行业 + 同花顺概念板块领涨变化频率，最近 250 日。"""
    conn = get_conn()
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
    conn.close()

    # 最新值摘要
    latest = compute_rotation()
    return {
        "data": data,
        "latest": {
            "date": latest["date"],
            "sw": {
                "speed_5d": latest.get("sw_rotation_5d"),
                "speed_10d": latest.get("sw_rotation_10d"),
                "speed_20d": latest.get("sw_rotation_20d"),
                "leader": latest.get("sw_leader"),
                "top3": latest.get("sw_top3"),
            },
            "concept": {
                "speed_5d": latest.get("concept_rotation_5d"),
                "speed_10d": latest.get("concept_rotation_10d"),
                "speed_20d": latest.get("concept_rotation_20d"),
                "leader": latest.get("concept_leader"),
                "top3": latest.get("concept_top3"),
            },
        },
    }


@app.get("/api/index/{index_id}")
def index_detail(index_id: str, range: str = Depends(range_dep)):
    if index_id not in _valid_index_ids():
        raise HTTPException(status_code=404, detail=f"未知的指数代码: {index_id}")
    start, end = _range(range)
    cfg = load_config()
    return {
        "ohlc": _index_series(index_id, start, end),
        "signals": _signals(index_id, start, end),
        "stats": _stats_for(index_id),
        "strategy": strategy_desc(index_id, cfg),
    }


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


@app.get("/trade_sim.html")
def trade_sim():
    return FileResponse(WEB_DIR / "trade_sim.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
