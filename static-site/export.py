#!/usr/bin/env python3
"""静态化导出脚本：从 SQLite (data/sentiment.db) 导出所有 API 端点数据为静态 JSON。

复刻 app/main.py 各端点的查询逻辑，保证 JSON 结构与 API 返回一致（前端改动最小）。
可重复跑（python static-site/export.py），覆盖 data/ 下 JSON。

导出端点：
  - data/overview.json                 （今日快照 + 指数 sparkline + 宽度 + 分数 + 行业热力图 + 买卖点 + 冰点日）
  - data/a-stock-{3m,6m,1y,3y,5y,all}.json
  - data/hk-{3m,6m,1y,3y,5y,all}.json
  - data/global-{3m,6m,1y,3y,5y,all}.json
  - data/sentiment-{3m,6m,1y,3y,5y,all}.json
  - data/industry-{3m,6m,1y,3y,5y,all}.json
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
ROOT = Path(__file__).absolute().parent.parent
sys.path.insert(0, str(ROOT))
from app.calendar import last_trading_day  # noqa: E402
from app.collector.fetchers import load_config  # noqa: E402
from app.compute import signal_stats as sigstats  # noqa: E402
from app.compute.position import compute_position  # noqa: E402
from app.compute.market_summary import generate_summary, summary_brief  # noqa: E402
from app.compute.signals import strategy_desc  # noqa: E402
from app.db import get_conn  # noqa: E402

STATIC_DIR = Path(__file__).absolute().parent
DATA_DIR = STATIC_DIR / "data"
INDEX_DIR = DATA_DIR / "index"

# 1m 周期已废弃删除：前端 range 选项仅 3m/6m/1y/3y/5y/all（无 1m 按钮），1m JSON 无人 fetch（冗余）
RANGES = {"3m": 90, "6m": 180, "1y": 365, "3y": 1095, "5y": 1825}
ALL_RANGES = list(RANGES.keys()) + ["all"]


_stats_cache = None


def _stats_all() -> dict:
    """现算 signal_stats（读 DB），进程内缓存。

    根因（2026-07-16 修复）：原读 data/signal_stats.json 文件，但 pipeline core/width
    并行跑 compute_runner 时 signal_stats.store 互相覆盖，偶发写出缺部分品种（全球指数
    ftse100/dax/cac40 等 + 全球指标 oil/brent/usdcnh/cn_us_spread）的文件。export 读到
    缺品种文件 -> global-*.json / index/*.json 缺这些品种 stats -> 前端全球tab有买卖点pin
    但无回测口径/胜率/凯利/模拟回测（statsHint 收到空 stats 只显示策略文字）。

    改为现算 sigstats.compute()：直接读 signal_daily + index_daily/daily_metric/score_daily，
    SQLite WAL 事务隔离保证读到某个 commit 后的完整版本（不会读到 DELETE+INSERT 中间的
    空表），不受并发 store 覆盖文件影响。进程内缓存（export 多次调 _stats_all）避免重复算。
    """
    global _stats_cache
    if _stats_cache is None:
        _stats_cache = sigstats.compute()
    return _stats_cache


def _stats_for(stats_all: dict, index_id: str) -> dict:
    return stats_all.get(index_id, {})

# 概览 KPI 指标（与 main.py KPI_METRIC_IDS 一致）
KPI_METRIC_IDS = [
    "a_width_zt_count",
    "a_width_dt_count",
    "a_width_up_count",
    "a_width_down_count",
    "a_amount",
    "a_volume_ratio",
    "a_fund_north",
    "a_fund_margin",
    "gold",
    "cn10y",
    "a_qvix_300",
    "lhb_count",
    "a_width_zhaban_rate",     # 炸板率（新源 mootdx derived，7-20有数据；旧 a_width_zb_count 数/旧源东财 stock_zt_pool_em 停7-16 已弃）
    "a_width_fengban_rate",   # 封板率（新源 derived=1-炸板率，旧 a_width_seal_rate func=TODO 停7-16）
    "a_fund_main",
    "a_turnover_mean",
    "a_turnover_median",
    "a_turnover_p90",
    "a_turnover_p10",
    "a_turnover_gt5_pct",
]
SPARKLINE_INDEX_IDS = ["sh", "sz", "hs300", "sz50", "cyb", "kc50", "bj50", "csi500", "csi1000", "hsi", "hstech"]


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


# 行业/概念 -> 相关 ETF 候选列表映射（读 data/board_etf_map.json，由 scripts/build_board_etf_map.py 生成）。
ETF_MAP_PATH = ROOT / "data" / "board_etf_map.json"
_ETF_CACHE = None


def _etf_for(index_id):
    """返回 {etfs: [{code, name, amount}, ...]}，按成交额降序；无匹配返空列表。"""
    global _ETF_CACHE
    if _ETF_CACHE is None:
        _ETF_CACHE = json.loads(ETF_MAP_PATH.read_text(encoding="utf-8")) if ETF_MAP_PATH.exists() else {}
    return {"etfs": _ETF_CACHE.get(index_id) or []}


def _industry_heatmap(conn, cfg):
    """申万一级行业近 1 日 / 近 5 日涨跌幅（与 main.py _industry_heatmap 一致）。"""
    indices = _indices_for_market(cfg, "industry")
    out = []
    for idx in indices:
        iid = idx["id"]
        rows = conn.execute(
            "SELECT date, close, pct_change FROM index_daily "
            "WHERE index_id=? AND pct_change IS NOT NULL ORDER BY date DESC LIMIT 6",
            (iid,),
        ).fetchall()
        if len(rows) < 2:
            continue
        latest = rows[0]
        pct_1d = latest["pct_change"]
        pct_5d = None
        # 优先用 close 算；盘中反哺行 close=NULL 时改用近 5 日 pct_change 累乘
        if latest["close"]:
            if len(rows) >= 6 and rows[5]["close"]:
                pct_5d = (latest["close"] / rows[5]["close"] - 1) * 100
            elif len(rows) >= 2 and rows[-1]["close"]:
                pct_5d = (latest["close"] / rows[-1]["close"] - 1) * 100
        elif len(rows) >= 5:
            # 盘中 close=NULL：用近 5 日 pct_change 累乘算累计收益
            cum = 1.0
            for r in rows[:5]:
                cum *= (1 + (r["pct_change"] or 0) / 100)
            pct_5d = (cum - 1) * 100
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

    # 前端按日分组（一天一行），故取"最近9个日期"的全部记录而非LIMIT 9条记录
    sig_start = (datetime.strptime(score_date, "%Y%m%d") - timedelta(days=25)).strftime("%Y%m%d")
    sig_dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM signal_daily WHERE date >= ? ORDER BY date DESC LIMIT 9",
        (sig_start,),
    ).fetchall()]
    sigs = []
    if sig_dates:
        sigs = [dict(r) for r in conn.execute(
            "SELECT date, index_id, signal, reason FROM signal_daily "
            "WHERE date IN (%s) ORDER BY date DESC, index_id" % ",".join("?" * len(sig_dates)),
            sig_dates,
        ).fetchall()]
    freeze_start = (datetime.strptime(score_date, "%Y%m%d") - timedelta(days=120)).strftime("%Y%m%d")
    freeze_dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM score_daily WHERE is_freeze=1 AND date >= ? ORDER BY date DESC LIMIT 9",
        (freeze_start,),
    ).fetchall()]
    freeze_days = []
    if freeze_dates:
        freeze_days = [dict(r) for r in conn.execute(
            "SELECT date, score_id, value FROM score_daily WHERE is_freeze=1 "
            "AND date IN (%s) ORDER BY date DESC" % ",".join("?" * len(freeze_dates)),
            freeze_dates,
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
    fg_6m = [{"date": r["date"], "value": r["value"], "is_freeze": r["is_freeze"], "is_overheat": r["is_overheat"]}
             for r in conn.execute(
                 "SELECT date, value, is_freeze, is_overheat FROM score_daily "
                 "WHERE score_id='fear_greed' AND date>=? ORDER BY date",
                 (six_m_start,))]

    # 采集时间 + 数据健康度：collect_log 最新一次 run（run_date 取当天全部记录）
    _last = conn.execute(
        "SELECT run_date, run_at FROM collect_log ORDER BY run_at DESC LIMIT 1"
    ).fetchone()
    # collected_at：盘中 snap 每30分钟更新（11:30/13:05等），但凌晨 backfill 让
    # collect_log.run_at 停在 02:01；取 snap.collected_at 与 collect_log run_at 较新者显示。
    def _fmt_iso(iso: str) -> str:
        return iso[:10].replace("-", "") + " " + iso[11:19] if iso and len(iso) >= 19 else ""
    _cands: list[tuple[str, str]] = []  # (iso, formatted) 取较新者
    if _last and _last["run_at"] and len(_last["run_at"]) >= 19:
        _cands.append((_last["run_at"], _fmt_iso(_last["run_at"])))
    try:
        from app.collector.intraday_snapshot import load_latest_snapshot
        _snap = load_latest_snapshot()
        if _snap and _snap.get("collected_at") and len(_snap["collected_at"]) >= 19:
            _cands.append((_snap["collected_at"], _fmt_iso(_snap["collected_at"])))
    except Exception:  # noqa: BLE001
        pass
    collected_at = max(_cands, key=lambda x: x[0])[1] if _cands else ""
    # 数据健康度：最新一次 run 的 warn/error 记录（绿=全ok/黄=有warn/红=有error）
    # 采集时间旁圆点展示，hover pop 显示具体告警，管理用户预期（如某指数源未取到）
    collect_health = {"level": "ok", "items": []}
    if _last and _last["run_date"]:
        # 取每个 metric_id 当天最新一条状态（20:00 ok 覆盖 17:50 瞬时 error），
        # 避免后续成功采集被早先 error 永久误报（如 usdcnh 17:50 forex_hist_em 被封
        # error，20:00 currency_boc_sina ok，只看最新即 ok 不报）
        _all_rows = conn.execute(
            "SELECT metric_id, status, message FROM collect_log WHERE run_date=? ORDER BY run_at DESC",
            (_last["run_date"],)
        ).fetchall()
        _seen = set()
        _hrows = []
        for _r in _all_rows:
            if _r["metric_id"] in _seen:
                continue
            _seen.add(_r["metric_id"])
            if _r["status"] != "ok":
                _hrows.append(_r)
        # 复核"指数今日数据缺失"类告警：backfill 凌晨跑时新浪主源未取到当日指数，
        # 但盘中 intraday_snapshot 反哺后 index_daily 已有当日 close，旧告警成陈旧误报，
        # 前端小红点因此常亮误导用户。对核心 A 股指数（index_backfill.CORE_A_INDICES）
        # 的该类 item 复核 index_daily 是否已有当日 close，有则移除该 item。
        _CORE_A_IDX = {"sh", "sz", "hs300", "sz50", "csi500", "csi1000", "cyb", "kc50", "bj50"}
        _hrun_date = _last["run_date"]
        _filtered = []
        for _r in _hrows:
            _msg = _r["message"] or ""
            if _r["metric_id"] in _CORE_A_IDX and "指数今日数据缺失" in _msg:
                _chk = conn.execute(
                    "SELECT close FROM index_daily WHERE index_id=? AND date=?",
                    (_r["metric_id"], _hrun_date)
                ).fetchone()
                if _chk and _chk["close"] is not None:
                    continue  # 实际已有数据，跳过陈旧误报
            _filtered.append(_r)
        if _filtered:
            collect_health["level"] = "error" if any(r["status"] == "error" for r in _filtered) else "warn"
            collect_health["items"] = [
                {"metric_id": r["metric_id"], "status": r["status"], "message": r["message"]}
                for r in _filtered
            ]

    # 行业热力图：盘中时用快照行业覆盖（P2-B，含 net_inflow/lead_stock），收盘后用 DB（P0-A 已修 SQL）
    heatmap = _industry_heatmap(conn, cfg)
    try:
        from app.collector.intraday_snapshot import maybe_override_heatmap
        heatmap = maybe_override_heatmap(heatmap)
    except Exception:  # noqa: BLE001
        pass

    # 数据时效横幅补充源日期：期货/ETF国家队/美股从静态导出 JSON 取末日期
    extra_dates = {}
    try:
        def _jload(name):
            p = DATA_DIR / name
            return json.load(open(p, encoding="utf-8")) if p.exists() else None
        _fut = _jload("futures.json")
        if _fut and _fut.get("summary", {}).get("date"):
            extra_dates["futures_date"] = _fut["summary"]["date"]
        _etf = _jload("etf_national_team-all.json")
        # etf_date 优先取 etf_daily 表 MAX(date)（真实数据日期，如 20260717），
        # JSON updated_at 是重建时间戳会误导角标假绿。etf_daily 在独立库 etf_national_team.db。
        _etf_d = ""
        try:
            from app.collector.etf_national_team import get_conn as _etf_get_conn
            _ec = _etf_get_conn()
            _er = _ec.execute("SELECT MAX(date) FROM etf_daily").fetchone()
            _ec.close()
            if _er and _er[0]:
                _etf_d = _er[0]
        except Exception:  # noqa: BLE001
            pass
        if _etf_d:
            extra_dates["etf_date"] = _etf_d
        elif _etf and _etf.get("updated_at"):
            extra_dates["etf_date"] = _etf["updated_at"][:10].replace("-", "")
        _glob = _jload("global-all.json")
        if _glob:
            _ud = _glob.get("indices", {}).get("us_dji", {}).get("data", [])
            if _ud:
                extra_dates["us_dji_date"] = _ud[-1]["date"]
        # 中证红利: 中证指数公司盘后次日发布，从 DB 取最新日期(不在 SPARKLINE_INDEX_IDS 中)
        _cd = conn.execute("SELECT date FROM index_daily WHERE index_id='csi_div' ORDER BY date DESC LIMIT 1").fetchall()
        if _cd:
            extra_dates["csi_div_date"] = _cd[0]["date"]
    except Exception:  # noqa: BLE001
        pass

    # 汪汪队(ETF国家队)最新信号 + 共振聚合：首页🐶卡片展示，点击跳专区
    nt_signals_today = None
    try:
        from app.collector.etf_national_team import latest_signals_overview, recent_signals_overview
        nt_signals_today = latest_signals_overview()
        if nt_signals_today:
            nt_signals_today["recent"] = recent_signals_overview()
    except Exception:  # noqa: BLE001
        pass

    return {
        "date": score_date,
        "collected_at": collected_at,
        "collect_health": collect_health,
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
        "fear_greed_6m": fg_6m,
        "industry_heatmap": heatmap,
        "futures_date": extra_dates.get("futures_date", ""),
        "etf_date": extra_dates.get("etf_date", ""),
        "us_dji_date": extra_dates.get("us_dji_date", ""),
        "csi_div_date": extra_dates.get("csi_div_date", ""),
        "nt_signals_today": nt_signals_today,
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
    stats_all = _stats_all()
    hk_industries = {i["id"]: {"name": i["name"], "data": _index_series(conn, i["id"], start, end),
                               "signals": _signals(conn, i["id"], start, end),
                               "stats": _stats_for(stats_all, i["id"]),
                               "strategy": strategy_desc(i["id"], cfg)}
                     for i in _indices_for_market(cfg, "hk_industry")}
    return {"indices": indices, "hk_south": south, "hk_industries": hk_industries}


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
    for mid in ("gold", "oil", "wti_oil", "comex_silver", "usdcnh", "a_qvix_300", "a_qvix_1000", "cn10y", "us10y", "cn_us_spread", "brent"):
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
        "fear_greed": _score_series(conn, "fear_greed", start, end),
        "signals": {
            "a_sentiment": _signals(conn, "s.a_sentiment", start, end),
            "cross_market": _signals(conn, "s.cross_market", start, end),
            "sentiment_sz50": _signals(conn, "s.sentiment_sz50", start, end),
            "sentiment_hs300": _signals(conn, "s.sentiment_hs300", start, end),
            "sentiment_csi500": _signals(conn, "s.sentiment_csi500", start, end),
            "sentiment_csi1000": _signals(conn, "s.sentiment_csi1000", start, end),
            "sentiment_cyb": _signals(conn, "s.sentiment_cyb", start, end),
            "sentiment_kc50": _signals(conn, "s.sentiment_kc50", start, end),
            "fear_greed": _signals(conn, "s.fear_greed", start, end),
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
            **_etf_for(iid),
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
            **_etf_for(iid),
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


def export_signal_freq():
    """复刻 /api/signal_freq：全局信号频率统计。

    委托 signal_stats.compute_global_freq()，与动态版 /api/signal_freq 字段完全一致
    （含 year/year_count、total/total_count 两套字段，X6 兼容期；月均按今年实际有
    信号的有效月份数计算，S2 修复）。
    """
    return sigstats.compute_global_freq()


def export_summary():
    """复刻 /api/summary。"""
    return generate_summary()


def export_summary_history(days: int = 90):
    """复刻 /api/summary/history：最近 N 天一句话总结（时间倒序）。

    静态站无后端，预生成 summary_history.json 供前端"更多"弹窗本地分页。
    取有 a_sentiment 的日期倒序前 N 个，每个调 generate_summary(date) 回算。
    """
    conn = get_conn()
    dates = [r["date"] for r in conn.execute(
        "SELECT DISTINCT date FROM score_daily WHERE score_id='a_sentiment' "
        "ORDER BY date DESC LIMIT ?",
        (days,),
    ).fetchall()]
    conn.close()
    items = [summary_brief(generate_summary(d)) for d in dates]
    return {"items": items, "total": len(items)}


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
    _VARIETY_NAMES = {
        "IF": "沪深300期货", "IC": "中证500期货",
        "IH": "上证50期货", "IM": "中证1000期货",
        "综合": "综合",
    }
    _ROLE_DISPLAY = {
        "top20": "机构(前20)",
        "中信期货": "中信期货",
        "国泰君安": "国泰君安",
    }

    end = last_trading_day()
    one_year_ago = (datetime.strptime(end, "%Y%m%d") - timedelta(days=365)).strftime("%Y%m%d")

    # 近 1 年日度净持仓（按角色分组）
    pos_rows = conn.execute(
        "SELECT date, variety, role, net_position, net_ratio FROM futures_position "
        "WHERE date>=? AND (net_position IS NOT NULL OR net_ratio IS NOT NULL) ORDER BY date, variety, role",
        (one_year_ago,),
    ).fetchall()

    positions_by_date = {}
    ratio_by_date = {}
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

    # 最新 summary
    summary_date = positions[-1]["date"] if positions else end
    summary_roles = {}
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

    # 最新准确率（按角色+窗口，仅综合品种）
    accuracy_rows = conn.execute(
        "SELECT a.date, a.role, a.window, a.follow_accuracy, a.contrarian_accuracy, "
        "a.follow_n, a.contrarian_n, a.net_direction, a.actual_return "
        "FROM futures_accuracy a "
        "INNER JOIN (SELECT role, window, MAX(date) AS max_date "
        "            FROM futures_accuracy WHERE variety='综合' GROUP BY role, window) b "
        "ON a.role=b.role AND a.window=b.window AND a.date=b.max_date "
        "WHERE a.variety='综合' "
        "ORDER BY a.role, a.window"
    ).fetchall()

    accuracy = {}
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
        # net_direction/actual_return 同日同角色跨窗口一致，写入 role 级别
        accuracy[role_display]["net_direction"] = r["net_direction"]
        accuracy[role_display]["actual_return"] = r["actual_return"]

    # 最近已完成的方向+涨跌（actual_return 非null 的最新日期）
    latest_bet_rows = conn.execute(
        "SELECT role, net_direction, actual_return, date "
        "FROM futures_accuracy WHERE variety='综合' AND actual_return IS NOT NULL "
        "AND date=(SELECT MAX(date) FROM futures_accuracy WHERE variety='综合' AND actual_return IS NOT NULL) "
        "ORDER BY role"
    ).fetchall()
    latest_bet = {}
    for r in latest_bet_rows:
        role_display = _ROLE_DISPLAY.get(r["role"], r["role"])
        latest_bet[role_display] = {
            "net_direction": r["net_direction"],
            "actual_return": r["actual_return"],
            "date": r["date"],
        }

    # 历史准确率序列
    acc_history_rows = conn.execute(
        "SELECT date, role, window, follow_accuracy, contrarian_accuracy "
        "FROM futures_accuracy WHERE variety='综合' "
        "ORDER BY date, role, window"
    ).fetchall()
    acc_history = []
    _acc_by_date = {}
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

    return {"summary": summary, "positions": positions, "positions_ratio": positions_ratio,
            "accuracy": accuracy, "accuracy_history": acc_history, "latest_bet": latest_bet}


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


def export_intraday_snapshot():
    """复刻 /api/intraday_snapshot：从 DB 读最新盘中实时快照。

    与 API 返回结构一致：{collected_at, is_closed, label, indices, industries}。
    DB 无数据时返回空结构（label="暂无快照"），保证双版一致。
    """
    from app.collector.intraday_snapshot import load_latest_snapshot
    snap = load_latest_snapshot()
    if snap is None:
        return {"collected_at": None, "is_closed": True, "label": "暂无快照",
                "prev_trading_day": "", "indices": [], "industries": [], "concepts": []}
    return snap


def _nt_slice_by_range(daily_json, rng):
    """按 range 切片 daily（日历日），与前端 ntSliceDataByRange 一致。
    all/未知 -> 全量；1m/3m/6m/1y/3y/5y -> 按天数 cutoff 过滤 date。
    保留 latest（全历史最新行不随 range 切，与前端 ntSliceDataByRange 行为一致）。"""
    if rng == "all":
        return daily_json
    days = RANGES.get(rng, 365)
    end = last_trading_day()
    cutoff = (datetime.strptime(end, "%Y%m%d") - timedelta(days=days)).strftime("%Y%m%d")
    out_etfs = []
    for e in daily_json.get("etfs", []):
        out_etfs.append({
            "code": e["code"], "name": e["name"], "index": e["index"],
            "market": e.get("market"),
            "daily": [d for d in (e.get("daily") or []) if d.get("date", "") >= cutoff],
            "latest": e.get("latest"),
        })
    return {"updated_at": daily_json.get("updated_at"), "etfs": out_etfs}


def export_etf_national_team(rng="all"):
    """国家队宽基 ETF 资金动向（12 只宽基 ETF 份额+成交额+信号）。
    与 /api/etf-national-team?range=rng 返回结构一致。读 data/etf_national_team.db。
    rng 默认 all（全历史）；1y/3y/5y 等按日历日切片，大幅减小默认加载体积。"""
    from app.collector.etf_national_team import export_data
    daily, _q, _h = export_data()
    return _nt_slice_by_range(daily, rng)


def export_etf_national_team_quarterly():
    """季度持有人结构（机构占比历史轨迹）。与 /api/etf-national-team/quarterly 一致。"""
    from app.collector.etf_national_team import export_data
    _d, quarterly, _h = export_data()
    return quarterly


def export_etf_national_team_holders():
    """v2 具名持有人（cninfo PDF 解析的前十大持有人，含汇金/证金识别）。
    与 /api/etf-national-team/holders 一致。
    """
    from app.collector.etf_national_team import export_data
    _d, _q, holders = export_data()
    return holders


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


def write_industry_split(conn, cfg, rng="all") -> tuple[dict, int, int]:
    """导出 industry-{rng} 拆分文件并返回 (counts, n_indices, n_concepts)。

    生成（rng 替换下方 {rng}）：
    - industry-{rng}-indices/{iid}.json × 31 行业
    - industry-{rng}-concepts.json（概念 + 当日实时行）
    - industry-{rng}-meta.json（热力图 + index_ids + concept_ids）
    - 仅 all range 额外产 {iid}-detail.json × 31（tooltip 专属字段，按需加载）

    all range 主文件瘦身（全历史 29MB 超 Cloudflare Pages 25MB 限制，瘦身省 ~68%），
    tooltip 专属字段拆到 {iid}-detail.json 按需加载。非 all range（5y 等）主文件保留
    全字段：单文件 <25MB 无需瘦身，且前端 _preloadIndDetail 检测 width[0] 含 zt_count
    即走内存分支（app.js _indHasDetail），免 detail 二次请求，故不产 detail.json。

    供 main() 收盘全量导出 与 intraday_snapshot._export_affected_json 盘中导出共用。
    盘中调用时 index_daily 已含当日行业/概念实时行（_backfill_industry_daily /
    _backfill_concept_daily），故导出 JSON 含当日 -> 前端读 JSON 即可盘中可见当日。
    """
    ind_all = export_industry(conn, cfg, rng)
    ind_split_dir = DATA_DIR / f"industry-{rng}-indices"
    ind_split_dir.mkdir(parents=True, exist_ok=True)
    counts: dict = {}
    slim = rng == "all"  # 仅 all 瘦身（全历史 29MB 超 25MB 限制）
    if slim:
        # B2 折中瘦身：主文件只保留渲染必需字段，tooltip 专属字段拆到 {iid}-detail.json
        _KEEP_DATA = ("date", "close", "pct_change", "amount")
        _KEEP_WIDTH = ("date", "up_count", "down_count")
        _DET_OHLC = ("open", "high", "low")
        _DET_WIDTH = ("zt_count", "dt_count", "zb_count", "seal_rate", "amount")
    for iid, ind in ind_all["indices"].items():
        if slim:
            slim_obj = {k: v for k, v in ind.items() if k not in ("data", "width")}
            slim_obj["data"] = [{k: x.get(k) for k in _KEEP_DATA} for x in ind["data"]]
            slim_obj["width"] = [{k: x.get(k) for k in _KEEP_WIDTH} for x in ind["width"]]
            counts[f"industry-{rng}-indices/{iid}.json"] = write_json(
                ind_split_dir / f"{iid}.json", slim_obj)
            detail = {
                "ohlc": [{k: x.get(k) for k in _DET_OHLC} for x in ind["data"]],
                "width": [{k: x.get(k) for k in _DET_WIDTH} for x in ind["width"]],
            }
            counts[f"industry-{rng}-indices/{iid}-detail.json"] = write_json(
                ind_split_dir / f"{iid}-detail.json", detail)
        else:
            counts[f"industry-{rng}-indices/{iid}.json"] = write_json(
                ind_split_dir / f"{iid}.json", ind)
    counts[f"industry-{rng}-concepts.json"] = write_json(
        DATA_DIR / f"industry-{rng}-concepts.json", {"concepts": ind_all["concepts"]})
    counts[f"industry-{rng}-meta.json"] = write_json(
        DATA_DIR / f"industry-{rng}-meta.json",
        {"heatmap": ind_all["heatmap"], "index_ids": list(ind_all["indices"].keys()),
         "concept_ids": list(ind_all["concepts"].keys())})
    n_indices = len(ind_all["indices"])
    n_concepts = len(ind_all["concepts"])
    print(f"  industry-{rng} 拆分: {n_indices} 行业 + {n_concepts} 概念 + meta")
    return counts, n_indices, n_concepts


def write_industry_all_split(conn, cfg) -> tuple[dict, int, int]:
    """兼容别名 -> write_industry_split(conn, cfg, "all")。"""
    return write_industry_split(conn, cfg, "all")


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
            if name == "industry" and rng in ("all", "5y", "3y"):
                continue  # industry-all/5y/3y 拆分为多文件（见下方），避免大单文件拖慢首屏
            fname = f"{name}-{rng}.json"
            data = fn(conn, cfg, rng)
            counts[fname] = write_json(DATA_DIR / fname, data)
            print(f"  {fname} ({counts[fname]} bytes)")
            # 信号弹窗只需 extras 四件套（不含 indices），单独导出轻量版省 ~68% 体积
            if name == "global" and rng == "all":
                counts["global-extras-all.json"] = write_json(
                    DATA_DIR / "global-extras-all.json",
                    {k: data[k] for k in ("extras", "extras_signals", "extras_stats", "extras_strategy")})
                print(f"  global-extras-all.json ({counts['global-extras-all.json']} bytes)")

    # industry-all/5y/3y 拆分：31 行业各一个文件 + concepts + meta。
    # all 全历史 29MB 超 Cloudflare Pages 25MB 单文件限制须拆；5y 14MB / 3y 9.2MB 虽未超限，
    # 但拆成 31 个小文件按需 fetch 提速首屏（前端 all/5y/3y 并发组装，见 app.js _loadIndustryData）。
    for rng in ("all", "5y", "3y"):
        ind_counts, _n_ind, _n_concept = write_industry_split(conn, cfg, rng)
        counts.update(ind_counts)

    # 7. metrics（已废弃：前端无 fetch 引用，2026-07-15 删除上线产物，不再生成）
    # counts["metrics.json"] = write_json(DATA_DIR / "metrics.json", export_metrics(cfg))
    # print(f"  metrics.json ({counts['metrics.json']} bytes)")

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
    counts["summary_history.json"] = write_json(
        DATA_DIR / "summary_history.json", export_summary_history())
    print(f"  summary_history.json ({counts['summary_history.json']} bytes)")
    counts["signal_freq.json"] = write_json(DATA_DIR / "signal_freq.json", export_signal_freq())
    print(f"  signal_freq.json ({counts['signal_freq.json']} bytes)")

    # 7.10. rotation
    counts["rotation.json"] = write_json(DATA_DIR / "rotation.json", export_rotation(conn))
    print(f"  rotation.json ({counts['rotation.json']} bytes)")

    # 7.11. new_high_low
    counts["new_high_low.json"] = write_json(DATA_DIR / "new_high_low.json", export_new_high_low(conn))
    print(f"  new_high_low.json ({counts['new_high_low.json']} bytes)")

    # 7.12. ma_alignment
    counts["ma_alignment.json"] = write_json(DATA_DIR / "ma_alignment.json", export_ma_alignment(conn))
    print(f"  ma_alignment.json ({counts['ma_alignment.json']} bytes)")

    # 7.13. intraday_snapshot（盘中实时快照，从 DB 读最新行）
    counts["intraday_snapshot.json"] = write_json(
        DATA_DIR / "intraday_snapshot.json", export_intraday_snapshot())
    print(f"  intraday_snapshot.json ({counts['intraday_snapshot.json']} bytes)")

    # 7.14. etf_national_team × range（默认1y≈0.67MB，all≈7.6MB；手机默认只下1y，避免7.6MB裸传卡顿）
    # 仿 sentiment 拆分：预生成 1m/3m/6m/1y/3y/5y/all 七个文件，前端按 state.range 按需 fetch。
    from app.collector.etf_national_team import export_data as _nt_export_data
    _nt_daily, _nt_quarterly, _nt_holders = _nt_export_data()
    for rng in ALL_RANGES:
        fname = f"etf_national_team-{rng}.json"
        counts[fname] = write_json(DATA_DIR / fname, _nt_slice_by_range(_nt_daily, rng))
        print(f"  {fname} ({counts[fname]} bytes)")
    counts["etf_national_team_quarterly.json"] = write_json(
        DATA_DIR / "etf_national_team_quarterly.json", _nt_quarterly)
    print(f"  etf_national_team_quarterly.json ({counts['etf_national_team_quarterly.json']} bytes)")
    counts["etf_national_team_holders.json"] = write_json(
        DATA_DIR / "etf_national_team_holders.json", _nt_holders)
    print(f"  etf_national_team_holders.json ({counts['etf_national_team_holders.json']} bytes)")

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
    print(f"  - tab ranges: 5 tabs × {len(ALL_RANGES)} ranges")
    print(f"  - metrics: 1")
    print(f"  - index detail: {len(all_indices)} (all range, full history)")
    print(f"输出目录: {DATA_DIR}")


if __name__ == "__main__":
    main()
