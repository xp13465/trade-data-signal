"""共享查询层：main.py 路由与 static-site/export.py 共用的 DB 查询逻辑。

设计原则：
- 函数无状态：接受 conn/cfg 参数，不自建连接、不持有模块级缓存。
- 缓存可选：building block 函数接受 cache=None；非空时读缓存（全量+字符串切片），
  为空时直接带 BETWEEN 查询。cache 由调用方（export.py）创建管理。
- stats_all_dict 可选：composite 函数接受预计算 stats dict；None 时内部调 stats_all()
  现算。export.py 传进程级缓存，main.py 传 None。
- 2 bug 修复（2026-07-25）：
  1. stats_all() 统一用 sigstats.compute() 现算（非 load 读 JSON，修 main 缺品种 bug）
  2. rotation() 统一用 compute_rotation() 含门控（非 export 直接 SQL，修无门控不一致）
"""
import json
import re
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from .calendar import last_trading_day
from .collector.fetchers import load_config
from .compute import signal_stats as sigstats
from .compute.market_summary import generate_summary, summary_brief
from .compute.rotation import compute_rotation
from .compute.signals import strategy_desc

# ============ 常量 ============

RANGES = {"1m": 30, "3m": 90, "6m": 180, "1y": 365, "3y": 1095, "5y": 1825}
VALID_RANGES = set(RANGES) | {"all"}

# 概览 KPI 卡片所需指标（来自 daily_metric，按展示顺序）
KPI_METRIC_IDS = [
    "a_width_zt_count",     # 涨停数
    "a_width_dt_count",     # 跌停数
    "a_width_up_count",     # 上涨家数
    "a_width_down_count",   # 下跌家数
    "a_amount",             # 成交额
    "a_volume_ratio",       # 量比（放量/缩量）
    "a_fund_north",         # 北向资金（停更，最新非空 20240816）
    "a_fund_margin",        # 两融余额
    "gold",                 # 商品(沪金) - 供数据时效横幅EXTRA取日期
    "cn10y",                # 10年国债收益率
    "a_qvix_300",           # QVIX波动率
    "lhb_count",            # 龙虎榜数量
    "a_width_zhaban_rate",   # 炸板率（新源 mootdx derived，7-20有数据；旧 a_width_zb_count 数/旧源东财 stock_zt_pool_em 停7-16 已弃）
    "a_width_fengban_rate", # 封板率（新源 derived=1-炸板率，旧 a_width_seal_rate func=TODO 停7-16）
    "a_fund_main",          # 主力净流入
    "a_turnover_mean",      # 换手率均值
    "a_turnover_median",    # 换手率中位数
    "a_turnover_p90",       # 换手率90分位
    "a_turnover_p10",       # 换手率10分位
    "a_turnover_gt5_pct",   # 换手率>5%占比
]
# sparkline 网格所需指数（按展示顺序）
SPARKLINE_INDEX_IDS = ["sh", "sz", "hs300", "sz50", "cyb", "kc50", "bj50", "csi500", "csi1000", "hsi", "hstech"]

_DATE_RE = re.compile(r"^\d{8}$")

# static-site/data 目录（overview 读静态 JSON 取补充源日期）
_STATIC_DATA_DIR = Path(__file__).absolute().parent.parent / "static-site" / "data"

# 行业/概念 -> 相关 ETF 候选列表映射（读 data/board_etf_map.json）
_ETF_MAP_PATH = Path(__file__).absolute().parent.parent / "data" / "board_etf_map.json"


# ============ 参数校验辅助 ============

def valid_index_ids(cfg) -> set[str]:
    return {i["id"] for i in cfg.get("indices", []) if i.get("enabled", True)}


def valid_metric_ids(cfg) -> set[str]:
    return {m["id"] for m in cfg.get("metrics", []) if m.get("enabled")}


def validate_date(date: str) -> None:
    if not _DATE_RE.match(date):
        raise ValueError(f"日期格式错误，要求 yyyyMMdd（如 20260703）, got: {date}")
    try:
        datetime.strptime(date, "%Y%m%d")
    except ValueError:
        raise ValueError(f"无效的日期: {date}")


# ============ Building blocks（接受 conn, cache=None）============

def range_for(rng: str):
    """range 参数 -> (start, end) 日期字符串。"""
    end = last_trading_day()
    if rng == "all":
        return "20100101", end
    days = RANGES.get(rng, 365)
    start = (datetime.strptime(end, "%Y%m%d") - timedelta(days=days)).strftime("%Y%m%d")
    return start, end


def metric_series(conn, metric_id, start, end, *, cache=None):
    """daily_metric 序列。cache 非空时优先读缓存（全量），按 start/end 字符串切片。"""
    if cache is not None:
        key = ("metric", metric_id)
        cached = cache.get(key)
        if cached is None:
            rows = conn.execute(
                "SELECT date, value FROM daily_metric WHERE metric_id=? ORDER BY date",
                (metric_id,),
            ).fetchall()
            cached = [{"date": r["date"], "value": r["value"]} for r in rows]
            cache[key] = cached
        return [r for r in cached if start <= r["date"] <= end]
    rows = conn.execute(
        "SELECT date, value FROM daily_metric WHERE metric_id=? AND date BETWEEN ? AND ? ORDER BY date",
        (metric_id, start, end),
    ).fetchall()
    return [{"date": r["date"], "value": r["value"]} for r in rows]


def index_series(conn, index_id, start, end, *, cache=None):
    """index_daily OHLC 序列。"""
    if cache is not None:
        key = ("index", index_id)
        cached = cache.get(key)
        if cached is None:
            rows = conn.execute(
                "SELECT date, open, high, low, close, pct_change, amount FROM index_daily "
                "WHERE index_id=? ORDER BY date",
                (index_id,),
            ).fetchall()
            cached = [dict(r) for r in rows]
            cache[key] = cached
        return [r for r in cached if start <= r["date"] <= end]
    rows = conn.execute(
        "SELECT date, open, high, low, close, pct_change, amount FROM index_daily "
        "WHERE index_id=? AND date BETWEEN ? AND ? ORDER BY date",
        (index_id, start, end),
    ).fetchall()
    return [dict(r) for r in rows]


def score_series(conn, score_id, start, end, *, cache=None):
    """score_daily 序列。"""
    if cache is not None:
        key = ("score", score_id)
        cached = cache.get(key)
        if cached is None:
            rows = conn.execute(
                "SELECT date, value, is_freeze, is_overheat, components FROM score_daily "
                "WHERE score_id=? ORDER BY date",
                (score_id,),
            ).fetchall()
            cached = [dict(r) for r in rows]
            cache[key] = cached
        return [r for r in cached if start <= r["date"] <= end]
    rows = conn.execute(
        "SELECT date, value, is_freeze, is_overheat, components FROM score_daily "
        "WHERE score_id=? AND date BETWEEN ? AND ? ORDER BY date",
        (score_id, start, end),
    ).fetchall()
    return [dict(r) for r in rows]


def signals(conn, index_id=None, start=None, end=None, *, cache=None):
    """signal_daily 序列。index_id=None 取全局。"""
    if cache is not None:
        key = ("signals", index_id)
        cached = cache.get(key)
        if cached is None:
            q = "SELECT date, index_id, signal, reason FROM signal_daily"
            params = []
            if index_id:
                q += " WHERE index_id=?"
                params.append(index_id)
            q += " ORDER BY date"
            rows = conn.execute(q, params).fetchall()
            cached = [dict(r) for r in rows]
            cache[key] = cached
        return [r for r in cached if start <= r["date"] <= end]
    q = "SELECT date, index_id, signal, reason FROM signal_daily WHERE date BETWEEN ? AND ?"
    params = [start, end]
    if index_id:
        q += " AND index_id=?"
        params.append(index_id)
    rows = conn.execute(q + " ORDER BY date", params).fetchall()
    return [dict(r) for r in rows]


def industry_width(conn, industry_code, start, end, *, cache=None):
    """行业内宽度序列（从 industry_width_daily 查）。"""
    if cache is not None:
        key = ("industry_width", industry_code)
        cached = cache.get(key)
        if cached is None:
            rows = conn.execute(
                "SELECT date, up_count, down_count, zt_count, dt_count, zb_count, seal_rate, amount "
                "FROM industry_width_daily WHERE industry_code=? ORDER BY date",
                (industry_code,),
            ).fetchall()
            cached = [dict(r) for r in rows]
            cache[key] = cached
        return [r for r in cached if start <= r["date"] <= end]
    rows = conn.execute(
        "SELECT date, up_count, down_count, zt_count, dt_count, zb_count, seal_rate, amount "
        "FROM industry_width_daily WHERE industry_code=? AND date BETWEEN ? AND ? ORDER BY date",
        (industry_code, start, end),
    ).fetchall()
    return [dict(r) for r in rows]


def metrics_for_groups(cfg, *groups):
    return [m for m in cfg.get("metrics", []) if m.get("group") in groups and m.get("enabled")]


def indices_for_market(cfg, market):
    return [i for i in cfg.get("indices", []) if i.get("market") == market and i.get("enabled", True)]


@lru_cache(maxsize=1)
def _etf_map() -> dict:
    if not _ETF_MAP_PATH.exists():
        return {}
    return json.loads(_ETF_MAP_PATH.read_text(encoding="utf-8"))


def etf_for(index_id: str) -> dict:
    """返回 {etfs: [{code, name, amount}, ...]}，按成交额降序；无匹配返空列表。

    匹配到多个时全部返回，前端按体量排序展示、用户自选；匹配不到为空数组
    （不再硬塞"代理"ETF，避免名称对不上误导用户）。
    """
    return {"etfs": _etf_map().get(index_id) or []}


def industry_heatmap(conn, cfg):
    """申万一级行业近 1 日 / 近 5 日涨跌幅（用于热力图）。不受 range 影响，固定取最新。"""
    indices = indices_for_market(cfg, "industry")
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
        # 近 5 日累计：优先用 close 算 (latest / close_5d_ago - 1) * 100；
        # 盘中反哺行 close=NULL 时改用近 5 日 pct_change 累乘（实时累计收益）。
        pct_5d = None
        if latest["close"]:
            if len(rows) >= 6 and rows[5]["close"]:
                pct_5d = (latest["close"] / rows[5]["close"] - 1) * 100
            elif len(rows) >= 2 and rows[-1]["close"]:
                # 不足 6 个交易日，用最早可用的算（标注实际天数）
                pct_5d = (latest["close"] / rows[-1]["close"] - 1) * 100
        elif len(rows) >= 5:
            # 盘中 close=NULL：用近 5 日 pct_change 累乘算累计收益
            # rows[0..4] = 今日(盘中) + 前4日，累乘 = 5日累计涨跌幅
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


# ============ stats（买卖点回测统计）============

# 买卖点回测 stats（现算 signal_stats，读 DB）。
# 返回 {index_id: {buy/buy_aux/sell: {5d/10d/20d: {win_rate,pl,mean,n}}}}；无数据返 {}。
# 2026-07-25 修复：原 main.py 读 data/signal_stats.json（load），pipeline 并行跑时
# store 互相覆盖偶发缺品种；统一用 sigstats.compute() 现算，SQLite WAL 事务隔离
# 保证读到完整版本，不受并发 store 覆盖文件影响。
def stats_all() -> dict:
    return sigstats.compute()


def stats_for(stats_all_dict: dict, index_id: str) -> dict:
    """单品种 stats：{buy:{...}, buy_aux:{...}, sell:{...}}；无则空 dict。"""
    return stats_all_dict.get(index_id, {})


# ============ Composite 端点 ============

# 品种名映射（代码 -> 中文）
_VARIETY_NAMES = {
    "IF": "沪深300期货", "IC": "中证500期货",
    "IH": "上证50期货", "IM": "中证1000期货",
    "综合": "综合",
}
# 角色名映射（DB key -> 对外展示）
_ROLE_DISPLAY = {
    "top20": "机构(前20)",
    "中信期货": "中信期货",
    "国泰君安": "国泰君安",
}
_ROLES_ORDER = ["top20", "中信期货", "国泰君安"]


def overview(conn, cfg):
    """复刻 /api/overview。"""
    # 最新分数日期（作为「今日」基准；指数/部分指标可能滞后于该日）
    row = conn.execute("SELECT max(date) FROM score_daily").fetchone()
    score_date = row[0] if row and row[0] else last_trading_day()
    scores = {r["score_id"]: dict(r) for r in conn.execute(
        "SELECT score_id, value, is_freeze, is_overheat FROM score_daily WHERE date=?", (score_date,)
    ).fetchall()}

    # KPI 指标今日快照：每个指标取最新非空值（北向停更后仍能取到 20240816）
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
                amt_row = conn.execute(
                    "SELECT value FROM daily_metric WHERE metric_id='a_amount' AND date=?",
                    (r["date"],),
                ).fetchone()
                entry["amount"] = amt_row["value"] if amt_row else None
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
        from .collector.intraday_snapshot import load_latest_snapshot
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
    heatmap = industry_heatmap(conn, cfg)
    try:
        from .collector.intraday_snapshot import maybe_override_heatmap
        heatmap = maybe_override_heatmap(heatmap)
    except Exception:  # noqa: BLE001
        pass

    # 数据时效横幅补充源日期：期货/ETF国家队/美股从静态导出 JSON 取末日期
    extra_dates = {}
    try:
        def _jload(name):
            p = _STATIC_DATA_DIR / name
            return json.load(open(p, encoding="utf-8")) if p.exists() else None
        _fut = _jload("futures.json")
        if _fut and _fut.get("summary", {}).get("date"):
            extra_dates["futures_date"] = _fut["summary"]["date"]
        _etf = _jload("etf_national_team-all.json")
        # etf_date 优先取 etf_daily 表 MAX(date)（真实数据日期，如 20260717），
        # JSON updated_at 是重建时间戳（如 20260720）会误导角标假绿。etf_daily 在
        # 独立库 etf_national_team.db（与 sentiment.db 隔离），单独连接查询。
        _etf_d = ""
        try:
            from .collector.etf_national_team import get_conn as _etf_get_conn
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
        from .collector.etf_national_team import latest_signals_overview, recent_signals_overview
        nt_signals_today = latest_signals_overview()
        if nt_signals_today:
            nt_signals_today["recent"] = recent_signals_overview()
    except Exception:  # noqa: BLE001
        pass

    return {
        "date": score_date,
        "collected_at": collected_at,
        "collect_health": collect_health,
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
        "industry_heatmap": heatmap,
        "futures_date": extra_dates.get("futures_date", ""),
        "etf_date": extra_dates.get("etf_date", ""),
        "us_dji_date": extra_dates.get("us_dji_date", ""),
        "csi_div_date": extra_dates.get("csi_div_date", ""),
        "nt_signals_today": nt_signals_today,
    }


def a_stock(conn, cfg, start, end, *, cache=None, include_etf=False):
    """复刻 /api/a-stock。include_etf=True 时注入 ETF 候选列表（export 用）。"""
    groups = ("a_width", "a_fund", "a_sentiment", "lhb", "unlock", "ipo", "cov")
    metrics = {}
    for m in metrics_for_groups(cfg, *groups):
        metrics[m["id"]] = {"name": m["name"], "unit": m.get("unit"), "data": metric_series(conn, m["id"], start, end, cache=cache)}
    indices = {}
    for i in indices_for_market(cfg, "a"):
        entry = {
            "name": i["name"],
            "data": index_series(conn, i["id"], start, end, cache=cache),
            "strategy": strategy_desc(i["id"], cfg),
        }
        if include_etf:
            entry.update(etf_for(i["id"]))
        indices[i["id"]] = entry
    return {"metrics": metrics, "indices": indices}


def hk(conn, cfg, start, end, *, cache=None, stats_all_dict=None):
    """复刻 /api/hk。"""
    indices = {i["id"]: {"name": i["name"], "data": index_series(conn, i["id"], start, end, cache=cache),
                         "strategy": strategy_desc(i["id"], cfg)} for i in indices_for_market(cfg, "hk")}
    south = metric_series(conn, "hk_south", start, end, cache=cache)
    sa = stats_all_dict if stats_all_dict is not None else stats_all()
    hk_industries = {i["id"]: {"name": i["name"], "data": index_series(conn, i["id"], start, end, cache=cache),
                               "signals": signals(conn, i["id"], start, end, cache=cache),
                               "stats": stats_for(sa, i["id"]),
                               "strategy": strategy_desc(i["id"], cfg)}
                     for i in indices_for_market(cfg, "hk_industry")}
    return {"indices": indices, "hk_south": south, "hk_industries": hk_industries}


def global_market(conn, cfg, start, end, *, cache=None, stats_all_dict=None):
    """复刻 /api/global。"""
    indices = {i["id"]: {"name": i["name"], "data": index_series(conn, i["id"], start, end, cache=cache),
                         "strategy": strategy_desc(i["id"], cfg)} for i in indices_for_market(cfg, "global")}
    sa = stats_all_dict if stats_all_dict is not None else stats_all()
    extras = {}
    extras_signals = {}
    extras_stats = {}
    extras_strategy = {}
    for mid in ("gold", "oil", "wti_oil", "comex_silver", "usdcnh", "a_qvix_300", "a_qvix_1000", "cn10y", "us10y", "cn_us_spread", "brent"):
        extras[mid] = metric_series(conn, mid, start, end, cache=cache)
        extras_signals[mid] = signals(conn, f"g.{mid}", start, end, cache=cache)
        extras_stats[mid] = stats_for(sa, f"g.{mid}")
        extras_strategy[mid] = strategy_desc(f"g.{mid}", cfg)
    return {"indices": indices, "extras": extras, "extras_signals": extras_signals,
            "extras_stats": extras_stats, "extras_strategy": extras_strategy}


def sentiment(conn, cfg, start, end, *, cache=None, stats_all_dict=None):
    """复刻 /api/sentiment。"""
    sa = stats_all_dict if stats_all_dict is not None else stats_all()
    return {
        "a_sentiment": score_series(conn, "a_sentiment", start, end, cache=cache),
        "cross_market": score_series(conn, "cross_market", start, end, cache=cache),
        "sentiment_sz50": score_series(conn, "sentiment_sz50", start, end, cache=cache),
        "sentiment_hs300": score_series(conn, "sentiment_hs300", start, end, cache=cache),
        "sentiment_csi500": score_series(conn, "sentiment_csi500", start, end, cache=cache),
        "sentiment_csi1000": score_series(conn, "sentiment_csi1000", start, end, cache=cache),
        "sentiment_cyb": score_series(conn, "sentiment_cyb", start, end, cache=cache),
        "sentiment_kc50": score_series(conn, "sentiment_kc50", start, end, cache=cache),
        "fear_greed": score_series(conn, "fear_greed", start, end, cache=cache),
        "signals": {
            "a_sentiment": signals(conn, "s.a_sentiment", start, end, cache=cache),
            "cross_market": signals(conn, "s.cross_market", start, end, cache=cache),
            "sentiment_sz50": signals(conn, "s.sentiment_sz50", start, end, cache=cache),
            "sentiment_hs300": signals(conn, "s.sentiment_hs300", start, end, cache=cache),
            "sentiment_csi500": signals(conn, "s.sentiment_csi500", start, end, cache=cache),
            "sentiment_csi1000": signals(conn, "s.sentiment_csi1000", start, end, cache=cache),
            "sentiment_cyb": signals(conn, "s.sentiment_cyb", start, end, cache=cache),
            "sentiment_kc50": signals(conn, "s.sentiment_kc50", start, end, cache=cache),
            "fear_greed": signals(conn, "s.fear_greed", start, end, cache=cache),
        },
        "stats": {
            "a_sentiment": stats_for(sa, "s.a_sentiment"),
            "cross_market": stats_for(sa, "s.cross_market"),
            "sentiment_sz50": stats_for(sa, "s.sentiment_sz50"),
            "sentiment_hs300": stats_for(sa, "s.sentiment_hs300"),
            "sentiment_csi500": stats_for(sa, "s.sentiment_csi500"),
            "sentiment_csi1000": stats_for(sa, "s.sentiment_csi1000"),
            "sentiment_cyb": stats_for(sa, "s.sentiment_cyb"),
            "sentiment_kc50": stats_for(sa, "s.sentiment_kc50"),
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


def industry(conn, cfg, start, end, *, cache=None, stats_all_dict=None):
    """复刻 /api/industry。"""
    sa = stats_all_dict if stats_all_dict is not None else stats_all()
    indices_cfg = indices_for_market(cfg, "industry")
    indices = {}
    for i in indices_cfg:
        iid = i["id"]
        # 行业指数代码（sw_801010 -> 801010）
        ind_code = iid[3:] if iid.startswith("sw_") else iid
        indices[iid] = {
            "name": i["name"],
            "data": index_series(conn, iid, start, end, cache=cache),
            "signals": signals(conn, iid, start, end, cache=cache),
            "stats": stats_for(sa, iid),
            "strategy": strategy_desc(iid, cfg),
            # F2：行业资金流 + 换手率（daily_metric）；成交额已在 data[].amount（F1 index_daily）
            "fund_flow": metric_series(conn, f"ind_flow_{iid}", start, end, cache=cache),
            "turnover": metric_series(conn, f"ind_turn_{iid}", start, end, cache=cache),
            # F3：行业内宽度（涨跌家数/涨停/跌停/炸板/封板率/成交额）
            "width": industry_width(conn, ind_code, start, end, cache=cache),
            # 相关 ETF 候选列表（按成交额降序，前端悬浮展示供用户自选）
            **etf_for(iid),
        }

    # Also include concept boards
    concepts_cfg = indices_for_market(cfg, "concept")
    concepts = {}
    for i in concepts_cfg:
        iid = i["id"]
        concepts[iid] = {
            "name": i["name"],
            "data": index_series(conn, iid, start, end, cache=cache),
            "signals": signals(conn, iid, start, end, cache=cache),
            "stats": stats_for(sa, iid),
            "strategy": strategy_desc(iid, cfg),
            **etf_for(iid),
        }

    return {"indices": indices, "heatmap": industry_heatmap(conn, cfg),
            "concepts": concepts}


def index_detail(conn, cfg, index_id, start, end, *, cache=None, stats_all_dict=None, include_etf=False):
    """复刻 /api/index/{index_id}。include_etf=True 时注入 ETF 候选列表（export 用）。"""
    sa = stats_all_dict if stats_all_dict is not None else stats_all()
    result = {
        "ohlc": index_series(conn, index_id, start, end, cache=cache),
        "signals": signals(conn, index_id, start, end, cache=cache),
        "stats": stats_for(sa, index_id),
        "strategy": strategy_desc(index_id, cfg),
    }
    if include_etf:
        result.update(etf_for(index_id))
    return result


def futures_data(conn):
    """期货持仓数据：近 1 年日度净持仓（按角色分组）+ 最新准确率（按角色分组）。"""
    ltd = last_trading_day()
    # 近 1 年日度净持仓（net_position 手数 + net_ratio 比例），按角色分组
    one_year_ago = (datetime.strptime(ltd, "%Y%m%d") - timedelta(days=365)).strftime("%Y%m%d")
    pos_rows = conn.execute(
        "SELECT date, variety, role, net_position, net_ratio FROM futures_position "
        "WHERE date>=? AND (net_position IS NOT NULL OR net_ratio IS NOT NULL) ORDER BY date, variety, role",
        (one_year_ago,),
    ).fetchall()

    # 按日期 -> 角色 -> 品种 pivot（手数 + 比例各一份）
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
        "a.follow_n, a.contrarian_n, a.net_direction, a.actual_return "
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
    latest_bet: dict[str, dict] = {}
    for r in latest_bet_rows:
        role_display = _ROLE_DISPLAY.get(r["role"], r["role"])
        latest_bet[role_display] = {
            "net_direction": r["net_direction"],
            "actual_return": r["actual_return"],
            "date": r["date"],
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

    return {"summary": summary, "positions": positions, "positions_ratio": positions_ratio,
            "accuracy": accuracy, "accuracy_history": acc_history, "latest_bet": latest_bet}


def ad_line(conn):
    """AD Line（腾落线）+ 涨跌家数比，最近 250 个交易日。"""
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
    return {"data": data}


def volume_ratio(conn):
    """成交量对比（放量/缩量标注），最近 250 个交易日。"""
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
    return {"data": data}


def new_high_low(conn):
    """新高新低家数：8 个主要指数的 52周/20日 NH-NL 统计。"""
    from .compute.new_high_low import INDEX_NAMES, INDICES, WINDOW_52W, WINDOW_20D

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

    return {"data": data}


def ma_alignment(conn):
    """均线排列状态：8 个主要指数的 MA5/MA10/MA20/MA60 多头/空头/震荡统计。"""
    from .compute.ma_alignment import INDICES, INDEX_NAMES, MA_PERIODS

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

    return {"data": data}


def rotation(conn):
    """板块轮动速度：SW 行业 + 同花顺概念板块领涨变化频率，最近 250 日。

    2026-07-25 修复：latest 统一用 compute_rotation()（含门控/回退），
    非 export 原直接 SQL 查当日 top3（无门控，盘前/周末幽灵数据不一致）。
    """
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

    # 最新值摘要：统一用 compute_rotation()（含门控/回退，与 API 一致）
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


def summary_history(conn, offset: int = 0, limit: int = 15):
    """历史一句话总结（时间倒序，实时回算当页）。

    取有 a_sentiment 数据的交易日倒序，skip offset 取 limit 个，每个调
    generate_summary(date) 回算。用于首页"更多"弹窗分页。无缓存表，靠各原料
    表的全历史实时回算（单页 15 天 ~12 SQL/天 <1s）。
    """
    dates = [r["date"] for r in conn.execute(
        "SELECT DISTINCT date FROM score_daily WHERE score_id='a_sentiment' "
        "ORDER BY date DESC"
    ).fetchall()]
    total = len(dates)
    items = [summary_brief(generate_summary(d))
             for d in dates[offset:offset + limit]]
    return {"items": items, "total": total, "offset": offset, "limit": len(items)}


def intraday_snapshot():
    """盘中实时快照：9 指数实时行情 + 31 行业实时涨跌幅。

    数据源：腾讯实时（指数）+ 同花顺行业 summary（聚合申万一级）。
    盘中采集更新最新一行；无数据时返回空结构。
    """
    from .collector.intraday_snapshot import load_latest_snapshot
    snap = load_latest_snapshot()
    if snap is None:
        return {"collected_at": None, "is_closed": True, "label": "暂无快照",
                "prev_trading_day": "", "indices": [], "industries": [], "concepts": []}
    return snap


def etf_national_team(rng="all"):
    """国家队宽基 ETF 资金动向：12 只宽基 ETF 近份额+成交额+信号。"""
    from .collector.etf_national_team import export_data, _nt_slice_by_range
    daily, _q, _h = export_data()
    return _nt_slice_by_range(daily, rng)


def etf_national_team_quarterly():
    """季度持有人结构（机构占比历史轨迹，半年报+年报）。"""
    from .collector.etf_national_team import export_data
    _d, quarterly, _h = export_data()
    return quarterly


def etf_national_team_holders():
    """v2 具名持有人：cninfo 年报/半年报 PDF 解析的前十大持有人（含汇金/证金识别）。"""
    from .collector.etf_national_team import export_data
    _d, _q, holders = export_data()
    return holders


def position():
    """大盘位置感：8 个 A 股指数的 1年/3年/5年分位 + 标签。"""
    from .compute.position import compute_position
    return {"positions": compute_position()}


def summary(date: str | None = None):
    """一句话市场总结：情绪+涨跌+家数+量能+热点板块。"""
    return generate_summary(date)


def signal_freq(stats_all_dict=None):
    """全局信号频率统计：汇总所有品种 buy/buy_aux/sell 的今年次数/总计/月均。

    2026-07-25 修复：统一用 stats_all() 现算（sigstats.compute()），非 load 读 JSON。
    传 stats_all_dict（进程内 cache）避免重复算，与 export 其他 export_* 保持一致。
    """
    if stats_all_dict is None:
        stats_all_dict = stats_all()
    return sigstats.compute_global_freq(stats_all_dict)


def metrics_list(cfg):
    """供手动补录表单用的指标列表。"""
    return [{"id": m["id"], "name": m["name"], "unit": m.get("unit")} for m in cfg.get("metrics", []) if m.get("enabled")]
