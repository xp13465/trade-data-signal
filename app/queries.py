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
import bisect
import json
import re
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from .calendar import last_trading_day
from .collector.fetchers import load_config
from .compute import signal_stats as sigstats
from .compute.market_summary import generate_summary, summary_brief
from .compute.futures_position import compute_role_ih_detail
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
    "a_fund_north",         # 北向资金（成交总额,HKEX源,每日更新;原净买额2024-08停更）
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
SPARKLINE_INDEX_IDS = ["sh", "sz", "hs300", "sz50", "cyb", "kc50", "bj50", "csi500", "csi1000", "hsi", "hstech", "hscei"]

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

    track_* 字段裁剪：透传 track_score + track_tier + track_n + track_low_confidence + stable_top1；
    4项原始指标（track_avg_dev/te/ir/r2/roll_std）只存 board_etf_map.json 后端 debug 用。
    track_n 透传供前端延迟纳入排序（track_n<90 排后，只展示不排 top1）。
    """
    raw = _etf_map().get(index_id) or []
    _TRACK_STRIP = {"track_avg_dev", "track_te", "track_ir", "track_r2", "track_roll_std"}
    etfs = [{k: v for k, v in _e.items() if k not in _TRACK_STRIP} if isinstance(_e, dict) else _e
            for _e in raw]
    return {"etfs": etfs}


# ── 首页 1:1 对齐回测(#60 方案A): ETF 选择冻结表接入 ────────────────────────────
# 背景: 回测 scripts/signal_kelly_backtest.py 已用 #58 冻结表 data/signal_kelly_etf_freeze.json
# (键 = date|index_id|signal, 值为该信号事件的固化 ETF)根治换标漂移; 首页 overview signals_today 的
# etfs 由 etf_for() 读当前 board_etf_map.json 注入, 未冻结 → 历史信号日随当前映射漂(同类漂移未修)。
# 方案A(用户定): 首页实操验证退化为回测口径(回测是实证基准) = 纯 max(track_score), 并接入同表冻结,
# 使首页每信号 top1 = 回测每笔成交标的 1:1。
#
# 此处只**只读** freeze 表防御(冻结表属回测脚本所有, 首页不回写避免并发写冲突):
#   命中冻结 → 该信号 top1 为冻结 ETF(权威), 注入 `_bk_top:true` 供前端优先取;
#   未命中(新信号) → 前端纯 max(track_score) 自然 = 回测 would-be 冻结(不写回)。
# 键格式与 #58 `_signal_key` 完全一致: f"{date}|{index_id}|{signal}"。
_ETF_FREEZE_PATH = Path(__file__).absolute().parent.parent / "data" / "signal_kelly_etf_freeze.json"


def _etf_freeze() -> dict:
    """读 #58 冻结查找表 {signal_key: {code, name, track_tier, track_score, ...}}。文件不存在返回 {}。"""
    if not _ETF_FREEZE_PATH.exists():
        return {}
    try:
        data = json.loads(_ETF_FREEZE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _signal_key(date: str, index_id: str, signal: str) -> str:
    return f"{date}|{index_id}|{signal}"


def _align_home_top1_to_backtest(_s: dict, freeze: dict) -> None:
    """把一条 signals_today 信号与其回测标的 1:1 对齐: 命中 #58 冻结表则把冻结 ETF 标为权威 top1。

    - 命中冻结: 在信号 etfs 中给冻结 code 所在条目加 `_bk_top: True`(权威 top1, 前端 _topEtfByScore
      优先返回); 若冻结 code 不在当前 etfs(已被 board_etf_map 换代), 按冻结条目 prepend 到 etfs 首。
    - 未命中冻结: 不改动(前端纯 max(track_score) 自然对齐回测 would-be 冻结)。
    _s["etfs"] 为 list[dict]; 返回前原地改 _s["etfs"] 并置 _s["_bk_top"]。
    """
    key = _signal_key(_s.get("date", ""), _s.get("index_id", ""), _s.get("signal", ""))
    frozen = freeze.get(key)
    if not frozen or not isinstance(_s.get("etfs"), list):
        return
    etfs = _s["etfs"]
    code = frozen.get("code")
    idx = next((i for i, e in enumerate(etfs) if isinstance(e, dict) and e.get("code") == code), -1)
    if idx >= 0:
        etfs[idx] = dict(etfs[idx])
        etfs[idx]["_bk_top"] = True
    else:
        # 冻结 ETF 已被 board_etf_map 换代移除 → prepend 冻结条目, 保证首页仍显回测标的
        entry = {k: v for k, v in frozen.items() if k != "frozen_at"}
        entry["_bk_top"] = True
        etfs.insert(0, entry)
    _s["_bk_top"] = True


def _self_etf_for(iid, cfg, conn):
    """ETF本体注入：当 index 本身就是 ETF（indicators.yaml func=fund_etf_hist_sina，
    如 cgb_10y_etf symbol=sh511260），board_etf_map.json 无此 key（非板块/宽基映射）
    -> etf_for 返空 -> 走势卡/弹窗/信号列表"无相关ETF"。此处直接用 symbol 剥 sh/sz/bj
    前缀作 ETF 代码注入，match_method="self" 标识"index 即 ETF 自身"。
    自动覆盖未来同类 index，无需改 board_etf_map.py 或硬编码 index_id。
    返回 {"etfs":[{"code","name","match_method":"self","amount"?}]} 或 None。
    """
    for i in cfg.get("indices", []):
        if i.get("id") != iid or not i.get("enabled", True):
            continue
        if i.get("func") == "fund_etf_hist_sina" and i.get("symbol"):
            _sym = i["symbol"]
            _code = _sym[2:] if _sym[:2] in ("sh", "sz", "bj") else _sym
            _etf = {"code": _code, "name": i.get("name") or _code, "match_method": "self"}
            # index_daily.amount 单位=元（如 cgb_10y_etf 3976292387≈39.76亿）；
            # 无数据则不注入 amount（前端降级不显体量）
            _self_amt = conn.execute(
                "SELECT amount FROM index_daily WHERE index_id=? AND amount IS NOT NULL "
                "ORDER BY date DESC LIMIT 1",
                (iid,),
            ).fetchone()
            if _self_amt and _self_amt["amount"]:
                _etf["amount"] = round(_self_amt["amount"] / 1e8, 2)
            return {"etfs": [_etf]}
        break  # 找到 iid 但非 fund_etf_hist_sina -> 无 self ETF
    return None


def _enrich_etfs_since_return(conn, indices):
    """走势卡 ETF 至今盈亏:为 indices[iid].etfs 注入 etf_since_return + etf_price_diff。

    取每个指数最新信号日(无论多旧,不限 overview signals_today 15交易日窗口),算信号日
    ETF 累计净值(accum_nav) vs 最新累计净值的涨跌幅。所有指数(无论信号新旧)都有,
    根治走势卡(全球/港股/A股 tab)相关ETF至今盈亏缺失(Layer2+3)。
    复用 overview() L524-575 口径:self ETF(match_method=self)用 index_daily close,
    其余用 etf_national_team.db etf_daily.accum_nav(已复权除权日不跳变)。
    今日信号(最新信号日==last_trading_day)无"至今"语义=None,对齐 overview L554-555。
    accum_nav 缺失(QDII跨境ETF等)-> None,前端跳过不显。
    """
    # 收集所有 etf codes(批量查一次 accum_nav,避免 N+1)
    _etf_codes = set()
    for _entry in indices.values():
        for _e in (_entry.get("etfs") or []):
            if _e.get("code"):
                _etf_codes.add(_e["code"])
    _etf_close_cache: dict[str, dict[str, float]] = {}
    if _etf_codes:
        try:
            from .collector.etf_national_team import get_conn as _etf_get_conn
            _ec = _etf_get_conn()
            for _r in _ec.execute(
                "SELECT etf_code, date, accum_nav FROM etf_daily "
                "WHERE etf_code IN (%s) AND accum_nav IS NOT NULL" % ",".join("?" * len(_etf_codes)),
                tuple(_etf_codes),
            ).fetchall():
                _etf_close_cache.setdefault(_r["etf_code"], {})[_r["date"]] = _r["accum_nav"]
            _ec.close()
        except Exception:  # noqa: BLE001
            pass
    _today = last_trading_day()
    _close_map_cache: dict[str, dict[str, float]] = {}

    def _load_close_map(iid: str) -> dict[str, float]:
        if iid in _close_map_cache:
            return _close_map_cache[iid]
        m: dict[str, float] = {}
        # 三分支独立循环用各自正确列名，对齐 overview() _load_close_map(L561-587)。
        # 旧实现三分支共用单循环 m[r["date"]] = r["value"]，但 else(index_daily)
        # SQL 是 SELECT date, close，列名 close 不是 value，r["value"] 抛 IndexError。
        # 被 cgb_10y_etf(self ETF)信号日==today 跳过掩盖；信号日≠today 即崩 export(P0)。
        if iid.startswith("g."):
            rows = conn.execute(
                "SELECT date, value FROM daily_metric WHERE metric_id=? AND value IS NOT NULL",
                (iid[2:],),
            ).fetchall()
            for r in rows:
                m[r["date"]] = r["value"]
        elif iid.startswith("s."):
            rows = conn.execute(
                "SELECT date, value FROM score_daily WHERE score_id=? AND value IS NOT NULL",
                (iid[2:],),
            ).fetchall()
            for r in rows:
                m[r["date"]] = r["value"]
        else:
            rows = conn.execute(
                "SELECT date, close FROM index_daily WHERE index_id=? AND close IS NOT NULL",
                (iid,),
            ).fetchall()
            for r in rows:
                m[r["date"]] = r["close"]
        _close_map_cache[iid] = m
        return m

    for _iid, _entry in indices.items():
        _etfs = _entry.get("etfs") or []
        if not _etfs:
            continue
        # 最新信号日(无论多旧,不限于 signals_today 窗口)
        _sig_row = conn.execute(
            "SELECT date FROM signal_daily WHERE index_id=? ORDER BY date DESC LIMIT 1",
            (_iid,),
        ).fetchone()
        _sig_date = _sig_row["date"] if _sig_row else None
        for _e in _etfs:
            _e["etf_since_return"] = None
            _e["etf_price_diff"] = None
            _code = _e.get("code")
            # 今日信号(最新信号日==last_trading_day)无"至今"语义=None,对齐 overview L554-555
            if not _code or not _sig_date or _sig_date == _today:
                continue
            # self ETF(如 511260=cgb_10y_etf)数据在 index_daily 不在 etf_daily,
            # 用 _load_close_map(index_id) 取 close,self 的 etf_since_return=指数涨跌幅(本体即ETF)
            if _e.get("match_method") == "self":
                _cm = _load_close_map(_iid)
            else:
                _cm = _etf_close_cache.get(_code)
            if not _cm:
                continue
            _sig_close = _cm.get(_sig_date)
            if _sig_close is None:
                continue
            # 今日 = 最新 etf_daily.date(per-ETF 最大日期,不同 ETF 末日可能不同)
            _today_close = _cm.get(max(_cm.keys()))
            if _today_close is None:
                continue
            _e["etf_since_return"] = round((_today_close - _sig_close) / _sig_close * 100, 2)
            _e["etf_price_diff"] = round(_today_close - _sig_close, 3)


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


# ============ AI宏降亏命中标注(2026-08-13 首页 AI 开关) ============
# 提取凯利回测区 lab.js _kellyPassesFadeFilters 的「AI宏默认降亏」8 键谓词
# (基础 5 键 n2/excludeSpecialBear四档/janMidRating/janMidSpecial/k2c5HkChase 港股追涨剔除
#  + 3元核心 3 键 r7MayReinforced/excludeAuxCross/greedy15；K2C5 并基础5为第 8 键，
#  v1.1.0 用户拍板 定名「基础5」, 穷举验证 docs/kelly/analysis/kelly-k2c5-exhaust-interaction.md)
# v1.1.2(2026-08-17 用户拍板): excludeSpecialBear 语义从 MA60 熊 → 四档(熊市·主跌+下降期)，
#   默认开=新主键(见 §5.4⑥ 发版本); 另新增 2 个默认关备选键 legacyMa60Special(老MA60熊×追买)
#   与 declinePhaseSpecial(下降期×buy_special 全市场), 均带 NEW 标签。
# 为可复用的信号级谓词，给 overview.json 每条信号注入 ai_macro:{hit, filters}。
# 与凯利区降亏逻辑同源(§22)。
# ⚠ 粒度降级(诚实标注)：凯利区基于交易级字段(含 ETF 买入价 buy_price 的
# price_bin 五分位)，overview 信号级无价格字段 → price_bin 依赖子条件在信号级
# **不可判定、不参与命中**(漏标不误标，宁保守不误杀)。其余字段(信号日/信号类型/
# 指数大类 mkt_*/评级 high-mid-low/weekday/top1 track_score)均与凯利同源同口径。
# ⚠ +1类回测剔除(债类/波段不入宇宙)不在此 8 键内：由 overview 每条信号的
# _bt_in_universe 字段承载(L840 注入, 等价回测 _build_best_etf 入样判定, §23.6)。
# 前端首页删除线 = ①ai_macro.filters 命中 8 键之一(→「AI降亏」标注) +
# ②_bt_in_universe===false(→「未入样本」标注), 两者正交叠加 = 8键+1类 = 9 (v1.1.0)。
# 首页开关=AI宏总开关(tds_kelly_filters.aiMacro)：on → ai_macro.hit 信号灰显对照。
_AI_MACRO_TOGGLE_NAMES = {
    "n2NovSpecialIndustry": "11月+追关注+行业",
    "excludeSpecialBear": "追关注×熊市交叉",
    "legacyMa60Special": "老MA60熊×追买",
    "declinePhaseSpecial": "下降期×追关注",
    "janMidRating": "J1 1月中旬+mid评级",
    "janMidSpecial": "J2 1月中旬+追关注",
    "k2c5HkChase": "港股追涨剔除",
    "r7MayReinforced": "5月强化+3非五月R7",
    "excludeAuxCross": "辅关注×3/5月交叉",
    "greedy15": "Greedy-15组合",
}


def _ai_macro_weekday(date_str: str) -> int:
    """信号日星期，与 lab.js _kellyBuyWeekday 同款(0=Mon..6=Sun)；无法解析返回 -1。"""
    if not date_str or len(date_str) < 8:
        return -1
    try:
        return datetime(int(date_str[0:4]), int(date_str[4:6]), int(date_str[6:8])).weekday()
    except ValueError:
        return -1


def _ai_macro_quarter(mm: str) -> int:
    """信号月 → 季度(ceil(mm/3)，与凯利 _q3 同款)；空串返回 0。"""
    if not mm or not mm.isdigit():
        return 0
    return (int(mm) + 2) // 3


def _ai_macro_build_market_map(cfg) -> dict:
    """indicators.yaml → {index_id: mkt_a/mkt_hk/mkt_global/mkt_industry/mkt_concept}(与凯利脚本同源)。"""
    out = {}
    for i in cfg.get("indices", []):
        iid, mkt = i.get("id"), i.get("market")
        if iid and mkt:
            out[iid] = f"mkt_{mkt}"
    return out


def _ai_macro_build_market_state(conn):
    """沪深300 四档大盘状态 + MA60 择时(与凯利 kelly_4tier / market_summary._market_state_of 同口径)。
    返回 (tiers, dates, ma60_bull)；无数据返回 (None, None, None) 保守不过滤。
    tiers: {date: tier_str}, tier_str ∈ {"牛市·主升","上升期","下降期","熊市·主跌"}：
      牛市·主升=价>MA200 且 多头排列(MA20>MA60>MA120)
      上升期   =价>MA200 且 非多头
      下降期   =价<MA200 且 非空头
      熊市·主跌=价<MA200 且 空头排列(MA20<MA60<MA120)
    ma60_bull: {date: close>MA60} 老 MA60 备选键(legacyMa60Special)判定源。
    """
    rows = conn.execute(
        "SELECT date, close FROM index_daily WHERE index_id='hs300' "
        "AND close IS NOT NULL ORDER BY date"
    ).fetchall()
    if not rows:
        return None, None, None
    dates = [r["date"] for r in rows]
    closes = [r["close"] for r in rows]
    n = len(dates)

    def _ma(w: int, i: int):
        if i < w - 1:
            return None
        return sum(closes[i - w + 1: i + 1]) / w

    tiers = {}
    ma60_bull = {}
    for i in range(200 - 1, n):
        c = closes[i]
        m20 = _ma(20, i)
        m60 = _ma(60, i)
        m120 = _ma(120, i)
        m200 = _ma(200, i)
        ma60 = _ma(60, i)
        if None in (m20, m60, m120, m200):
            continue
        bull = m20 > m60 > m120
        bear = m20 < m60 < m120
        if c > m200 and bull:
            tier = "牛市·主升"
        elif c > m200:
            tier = "上升期"
        elif c < m200 and bear:
            tier = "熊市·主跌"
        elif c < m200:
            tier = "下降期"
        else:
            tier = "上升期"
        tiers[dates[i]] = tier
        if ma60 is not None:
            ma60_bull[dates[i]] = closes[i] > ma60
    return tiers, dates, ma60_bull


def _ai_macro_classify_tiers(dates, closes):
    """四档大盘状态分类(共享纯函数, 供 hs300/cyb 等任意指数复用, 避免复制分叉)。
    tiers: {date: tier_str}, tier_str ∈ {"牛市·主升","上升期","下降期","熊市·主跌"}：
      牛市·主升=价>MA200 且 多头排列(MA20>MA60>MA120)
      上升期   =价>MA200 且 非多头
      下降期   =价<MA200 且 非空头
      熊市·主跌=价<MA200 且 空头排列(MA20<MA60<MA120)
    """
    n = len(dates)

    def _ma(w: int, i: int):
        if i < w - 1:
            return None
        return sum(closes[i - w + 1: i + 1]) / w

    tiers = {}
    for i in range(200 - 1, n):
        c = closes[i]
        m20 = _ma(20, i)
        m60 = _ma(60, i)
        m120 = _ma(120, i)
        m200 = _ma(200, i)
        if None in (m20, m60, m120, m200):
            continue
        bull = m20 > m60 > m120
        bear = m20 < m60 < m120
        if c > m200 and bull:
            tier = "牛市·主升"
        elif c > m200:
            tier = "上升期"
        elif c < m200 and bear:
            tier = "熊市·主跌"
        elif c < m200:
            tier = "下降期"
        else:
            tier = "上升期"
        tiers[dates[i]] = tier
    return tiers


def _ai_macro_build_cyb_tier(conn):
    """创业板指(cyb)四档大盘状态(#69 新键 excludeSpecialBearCyb 判定源)。
    返回 (tiers, dates)；无数据返回 ({}, [])。与 hs300 _ai_macro_build_market_state 同口径算法
    (共享 _ai_macro_classify_tiers)。cyb=创业板指, 数据 2010+ 起, 足够长。
    """
    rows = conn.execute(
        "SELECT date, close FROM index_daily WHERE index_id='cyb' "
        "AND close IS NOT NULL ORDER BY date"
    ).fetchall()
    if not rows:
        return {}, []
    dates = [r["date"] for r in rows]
    closes = [r["close"] for r in rows]
    return _ai_macro_classify_tiers(dates, closes), dates


def _ai_macro_build_index_tiers(conn, index_id):
    """任意宽基指数四档大盘状态(纯展示, 供 index_detail 注入 tiers, #73 8 宽基四档色带)。
    返回 ({date: tier}, [dates])；无数据返回 ({}, [])。
    与 hs300(_ai_macro_build_market_state) / cyb(_ai_macro_build_cyb_tier) 同口径算法
    (共享 _ai_macro_classify_tiers): 读 index_daily 该指数全部 close →
    价 vs MA200 + MA20/60/120 排列四档。纯展示, 不影响过滤(§23.7 只增不改)。
    """
    rows = conn.execute(
        "SELECT date, close FROM index_daily WHERE index_id=? "
        "AND close IS NOT NULL ORDER BY date", (index_id,)
    ).fetchall()
    if not rows:
        return {}, []
    dates = [r["date"] for r in rows]
    closes = [r["close"] for r in rows]
    return _ai_macro_classify_tiers(dates, closes), dates


def _ai_macro_tier_at(date_str: str, tiers, dates):
    """<= 信号日最近的四档 tier_str；无状态返回 None(不过滤)。"""
    if not tiers:
        return None
    idx = bisect.bisect_right(dates, date_str) - 1
    while idx >= 0:
        d = dates[idx]
        if d in tiers:
            return tiers[d]
        idx -= 1
    return None


def _ai_macro_ma60_bull_at(date_str: str, ma60_bull, dates) -> bool:
    """老 MA60 备选键：<= 信号日最近交易日 close>MA60(多头 True, 熊 False)。
    与旧 excludeSpecialBear MA60 判定同口径；无状态保守 True(不过滤)。"""
    if not ma60_bull:
        return True
    idx = bisect.bisect_right(dates, date_str) - 1
    while idx >= 0:
        d = dates[idx]
        if d in ma60_bull:
            return ma60_bull[d]
        idx -= 1
    return True


def market_tier_history(conn):
    """沪深300 四档大盘状态全历史序列(2002 起, 供前端历史四档轨迹图/色带/时间线面板)。
    与 _ai_macro_build_market_state 同口径, 输出 [{date, tier, ma60_bull}] 按日期升序。
    tier ∈ {"牛市·主升","上升期","下降期","熊市·主跌"}, ma60_bull 为老 MA60 备选键判定。
    纯展示数据, 不影响过滤(§23.7 只增不改)。
    """
    tiers, dates, ma60_bull = _ai_macro_build_market_state(conn)
    if not tiers:
        return []
    out = []
    for d in dates:
        if d in tiers:
            out.append({"date": d, "tier": tiers[d], "ma60_bull": bool(ma60_bull.get(d, False))})
    return out


def _ai_macro_is_bull(date_str: str, state, dates) -> bool:
    """<= 信号日最近的 MA60 状态(多头 True)；无状态保守 True(不过滤)。
    (为兼容旧调用保留；主键已改为四档 tier 判定, 此函数不再被 _ai_macro_hit_filters 使用。)"""
    if not state:
        return True
    idx = bisect.bisect_right(dates, date_str) - 1
    while idx >= 0:
        d = dates[idx]
        if d in state:
            return state[d]
        idx -= 1
    return True


def _ai_macro_rating_of(sig: dict, sig_stats: dict) -> str:
    """信号评级 high/mid/low：signal_stats[index_id][signal].10d.score 分档
    (≥0.75 high / ≥0.55 mid / <0.55 low，与前端 _getSignalScore/凯利脚本同口径)。
    buy_special_filtered 归 buy_special(与凯利脚本同)。无 score 返回 ""。"""
    sig_key = "buy_special" if sig.get("signal") == "buy_special_filtered" else (sig.get("signal") or "")
    try:
        d = (sig_stats.get(sig.get("index_id") or "", {}) or {}).get(sig_key, {}).get("10d", {})
    except AttributeError:
        return ""
    s = d.get("score")
    if s is None:
        return ""
    return "high" if s >= 0.75 else ("mid" if s >= 0.55 else "low")


def _ai_macro_track_score_of(sig: dict):
    """top1 ETF track_score(与凯利脚本 _build_best_etf 同口径，取最高分)；无返 None。"""
    best = None
    for _e in (sig.get("etfs") or []):
        ts = _e.get("track_score")
        if ts is not None and (best is None or ts > best):
            best = ts
    return best


# 仅 A股类才按 hs300 MA60 大盘择时判断熊市(与凯利脚本 A_STOCK_MARKETS={"a","concept","industry"} 同源);
# 非 A 类(hk/global/hk_industry)凯利区 market_state 恒 True 不过滤, 此处须同守卫防误标(review FAIL1)。
_AI_MACRO_A_STOCK_MARKETS = {"mkt_a", "mkt_concept", "mkt_industry"}
# 凯利回测仅对买交易应用降亏过滤(与 signal_kelly_backtest.py BUY_SIGNALS=("buy","buy_aux","buy_special","buy_backup") 同源);
# overview 信号级另含 buy_special_filtered(追买h5过滤预览, 归 buy_special, 与 _ai_macro_rating_of 同口径)一并计入。
# 非买信号(band_hold/sell/sell_stop_loss)凯利区不存在(只采买信号), 一律不判降亏(review MED3)。
_AI_MACRO_BUY_SIGNALS = {"buy", "buy_aux", "buy_special", "buy_special_filtered", "buy_backup"}


def _ai_macro_hit_filters(sig: dict, ctx: dict) -> list:
    """信号级 AI宏(基础5+核心3 = 8 toggle, +1类剔除走 _bt_in_universe 字段)命中条件名列表
    (与凯利区 AI宏默认集同源, v1.1.0 基准, docs/kelly/analysis/kelly-k2c5-exhaust-interaction.md)。
    ctx 需含: rating_of(sig)->str / market_of(iid)->str / track_score_of(sig)->float|None /
    tier_of(date)->str|None(四档) / ma60_bull_of(date)->bool(老MA60备选)。price_bin 依赖子条件降级不参与命中(见模块级注释)。
    仅买信号守卫(MED3): 非买信号直接返空(与凯利区"只对买交易过滤"同源)。"""
    _f = []
    _d = str(sig.get("date") or "")
    _mm = _d[4:6] if len(_d) >= 8 else ""
    _dd = int(_d[6:8]) if len(_d) >= 8 else 0
    _sig = sig.get("signal") or ""
    _wd = _ai_macro_weekday(_d)
    _rating = ctx["rating_of"](sig)
    _mkt = ctx["market_of"](sig.get("index_id") or "")
    _ts = ctx["track_score_of"](sig)
    _tier = ctx["tier_of"](_d)
    _ma60_bull = ctx["ma60_bull_of"](_d)
    _cyb_tier = ctx["cyb_tier_of"](_d)
    _q = _ai_macro_quarter(_mm)

    # ⚠仅买信号守卫(与凯利区"只对买交易过滤"同源): 非买(band_hold/sell/sell_stop_loss)一律不判降亏
    if _sig not in _AI_MACRO_BUY_SIGNALS:
        return []

    # 1 n2: buy_special + 11月 + 行业指数
    if _sig == "buy_special" and _mm == "11" and _mkt == "mkt_industry":
        _f.append("n2NovSpecialIndustry")
    # 2 excludeSpecialBear(v1.1.2 主键, 四档升级): buy_special + A股类 + 四档∈{熊市·主跌,下降期}
    #   (大盘择时仅对A股类, 非A不过滤, 与凯利 kelly_4tier R1_all 判定同源; 老 MA60 语义降为备选键 legacyMa60Special)
    if _sig == "buy_special" and _mkt in _AI_MACRO_A_STOCK_MARKETS and _tier in ("熊市·主跌", "下降期"):
        _f.append("excludeSpecialBear")
    # 2b legacyMa60Special(默认关备选, v1.1.2): 老 excludeSpecialBear 的 MA60 熊×buy_special×A股类
    #   close<MA60(ma60_bull=False) 判熊, 与 v1.1.0 旧语义完全一致(仅 A股类, 非A不过滤)
    if _sig == "buy_special" and _mkt in _AI_MACRO_A_STOCK_MARKETS and not _ma60_bull:
        _f.append("legacyMa60Special")
    # 2c declinePhaseSpecial(默认关备选, v1.1.2): 下降期×buy_special×全市场(B 方案 V4d_all 增量, 不限于A股)
    if _sig == "buy_special" and _tier == "下降期":
        _f.append("declinePhaseSpecial")
    # 2d excludeSpecialBearCyb(#69 新键, 默认关非默认推荐): cyb(创业板指)四档版 excludeSpecialBear——
    #   与主键 excludeSpecialBear 判定语义完全一致, 仅判定源 hs300 四档 → cyb 四档:
    #   buy_special × A股类 × cyb 四档∈{熊市·主跌, 下降期}。默认不进首页/凯利默认组合, 凯利区独立开关供人工复测。
    if _sig == "buy_special" and _mkt in _AI_MACRO_A_STOCK_MARKETS and _cyb_tier in ("熊市·主跌", "下降期"):
        _f.append("excludeSpecialBearCyb")
    # 2b k2c5HkChase(K2C5, 并基础5 v1.1.0 第8键): signal∈{buy_special,buy_backup} × 港股
    #   与 lab.js _kellyPassesFadeFilters L7521 同谓词(_mktD3==="hk")。
    #   ⚠港股分类须对齐回测 MARKET_QUAD_MAP(scripts/signal_kelly_backtest.py L128-130):
    #   回测把 market in (hk,hk_industry) 都归入 mkt_hk 象限(港股板块归入港股大类), lab.js
    #   mktD 读该象限 → "hk"; 故后端 mkt 长形式只判单值 (mkt_hk,)。
    #   ❗为什么不能连 mkt_hk_industry 一起判(2026-08-15 P2-1 修正): hk_industry 信号(如 hk_hsmbi)
    #   在 §23.6 宇宙规则里属排除类别(港股行业 hk_*), 从未入样 → board_etf_map 无 key 无 track_score
    #   → 回测 _build_best_etf 从不收录其 trade, 故 signal_kelly_trades.json 的 mkt_hk 象限只有
    #   {hsi,hscei,hstech}(见 reviewer 审计复现), K2C5 在回测侧根本无从过滤 hk_industry 交易。
    #   后端若连 mkt_hk_industry 一起判 = over-flag(防漏标意图反致过度标注): 12 条未入样 hk_industry
    #   信号被标「AI降亏」而非「未入样本」, 与凯利区实际过滤范围不一致。故只判 mkt_hk。
    if _sig in ("buy_special", "buy_backup") and _mkt == "mkt_hk":
        _f.append("k2c5HkChase")
    # 3 janMidRating: 1月中旬(11-20日) + mid 评级
    if _mm == "01" and 11 <= _dd <= 20 and _rating == "mid":
        _f.append("janMidRating")
    # 4 janMidSpecial: buy_special + 1月中旬
    if _sig == "buy_special" and _mm == "01" and 11 <= _dd <= 20:
        _f.append("janMidSpecial")
    # 5 r7MayReinforced: 并集(5月A股 / 5月mid / 11月special+行业 / 11月special+周一)
    #   ⚠5月vlow、3月周二high 两项依赖 price_bin 信号级降级不参与
    if ((_mkt == "mkt_a" and _mm == "05") or (_rating == "mid" and _mm == "05")
            or (_sig == "buy_special" and _mm == "11" and _mkt == "mkt_industry")
            or (_sig == "buy_special" and _mm == "11" and _wd == 0)):
        _f.append("r7MayReinforced")
    # 6 excludeAuxCross: buy_aux + 3/5月
    if _sig == "buy_aux" and (_mm == "03" or _mm == "05"):
        _f.append("excludeAuxCross")
    # 7 greedy15: 15step 并集(信号级可判定子集)
    #   ⚠step5(q2+vlow+buy_aux+concept)/step9(06+vlow+low)/step14(01+low+buy_special+concept)
    #   依赖 price_bin 信号级降级不参与
    if ((_sig == "buy_special" and _mm == "05")
            or (_sig == "buy_special" and _mm == "11" and _mkt == "mkt_concept")
            or (_sig == "buy_special" and _mm == "03")
            or (_sig == "buy_aux" and _mm == "01")
            or (_sig == "buy" and _mm == "01")
            or (_mm == "03" and _wd == 2 and _mkt == "mkt_concept" and _rating == "low")
            or (_sig == "buy_aux" and _mm == "12" and _ts is not None and _ts < 50)
            or (_sig == "buy_aux" and _mm == "05")
            or (_sig == "buy_special" and _mm == "11" and _mkt == "mkt_industry")
            or (_mm == "04" and _wd == 1 and _mkt == "mkt_concept" and _ts is not None and _ts < 50)
            or (_mkt == "mkt_global" and _q == 1 and _sig == "buy_aux" and _rating == "low")
            or (_sig == "buy_special" and _mm == "09" and _wd == 2)):
        _f.append("greedy15")
    return _f


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
    # 治本: 用 last_trading_day() 锚定交易日，避免周末 cross_market 单条记录污染。
    # cross_market 含全球/夜盘指标(美指/黄金周六有数据)会在非交易日异常写入 score_daily，
    # 致 max(date) 取到周六 -> 其它依赖 A 股指标的 score(a_sentiment/fear_greed/per-index)被过滤掉。
    # 兜底: 若该交易日盘前尚未计算评分(last_trading_day 当天还没跑 update_all)，回退到
    # 最近一个有 a_sentiment 评分的日期(同 market_summary.py L95 口径，a_sentiment 仅交易日写入)，
    # 保证 today.scores 始终齐全而非空对象。
    score_date = last_trading_day()
    _row = conn.execute(
        "SELECT max(date) FROM score_daily WHERE score_id='a_sentiment' AND date <= ?",
        (score_date,)
    ).fetchone()
    if _row and _row[0]:
        score_date = _row[0]
    # P1 hover 分项构成：components 是 JSON string，parse 成 dict 供前端直接读。
    # a_sentiment 6维(ratio/zt/zhaban/lianban/amount/north)
    # cross_market 9维(a_width/a_fund/a_sentiment/hk/global/lhb/unlock/ipo/cov)
    # 6宽基: sz50/csi500/cyb/kc50 各2维(rsi/pct_change); hs300/csi1000 各3维(+qvix)
    # fear_greed: {label, available_scores}
    # high_alert/low_alert 8维(H1-H8/L1-L8)亦一并 parse，P2 方案J 前端渲染时直接可用
    #
    # 2026-08-18 根治「当前值停旧、文件已有最新」：每张卡独立取自身 score_id 的
    # max(date)<=最近交易日(anchor)，单指标缺失(如 a_sentiment 因 width 采集失败缺当日)
    # 不再拖垮其它 8 张卡(旧逻辑单一锚定 a_sentiment，见下方 score_date 兜底注释)。
    # 与 sentiment-1y/6m 序列(score_series 逐 score_id 取 max)口径一致(§22 一致性)。
    # 每行自带 date=该卡实际最新日期，L1456 today.scores 不再强制覆盖为 score_date。
    scores = {}
    for _r in conn.execute(
        "SELECT score_id, value, is_freeze, is_overheat, components, date FROM score_daily "
        "WHERE date=(SELECT max(date) FROM score_daily s2 "
        "            WHERE s2.score_id=score_daily.score_id AND s2.date<=?)",
        (last_trading_day(),)
    ).fetchall():
        _d = dict(_r)
        _comp_raw = _d.get("components")
        try:
            _d["components"] = json.loads(_comp_raw) if _comp_raw else None
        except (ValueError, TypeError):
            _d["components"] = None
        scores[_r["score_id"]] = _d

    # KPI 指标今日快照：每个指标取最新非空值
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
    # 用日历日范围覆盖足够交易日：15交易日≈35天（含周末+节假日冗余），30交易日≈45天
    # 前端按日分组（一天一行），故取"最近15个日期"的全部记录而非 LIMIT 15 条记录
    sig_start = (datetime.strptime(score_date, "%Y%m%d") - timedelta(days=35)).strftime("%Y%m%d")
    sig_dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM signal_daily WHERE date >= ? ORDER BY date DESC LIMIT 15",
        (sig_start,)
    ).fetchall()]
    sigs = []
    if sig_dates:
        # 过滤 s.* 情绪分信号（方案B 2026-07-20）：情绪分是 0-100 衍生指标非可交易标的，
        # 混入首页买卖点列表易误导且无 ETF 参考。只在 signals_today（首页信号列表）排除，
        # signal_daily 表保留 s.* 记录，KPI 卡片/弹窗仍经 signals() 函数按 index_id 查 s.*
        # 画走势+pin（见 L761-769）。
        sigs = [dict(r) for r in conn.execute(
            "SELECT date, index_id, signal, reason FROM signal_daily "
            "WHERE date IN (%s) AND index_id NOT LIKE 's.%%' "
            "ORDER BY date DESC, index_id" % ",".join("?" * len(sig_dates)),
            sig_dates
        ).fetchall()]
    # 2026-08-05 注入 ETF 候选到每条信号（前端信号 cell 展示 ETF tag + 真实ETF/概念标的筛选）。
    # etf_for 已 lru_cache 零开销；etfs=[] 表示概念标的（无跟踪ETF，前端显"无ETF"灰标）。
    # 深拷贝 etfs 列表：_etf_map() lru_cache 返回共享对象，不同信号日需独立 etf_since_return（L461+）。
    # 2026-08-07 注入指数中文名+代码（从 indicators.yaml 单一来源，遵守"一个指数一个名字"原则），
    # 前端 signals_today 展示"中文名（代码）"优先后端注入，_INDEX_NAME_MAP 仅作兜底。
    # _idx_meta 在循环外建一次（避免每条 signal 重建），循环内只查 map。
    # func 字段用于 fund_etf_hist_sina 分支（index 本身就是 ETF，如 cgb_10y_etf sh511260）。
    _idx_meta = {i["id"]: {"name": i.get("name"), "symbol": i.get("symbol"), "func": i.get("func")}
                 for i in cfg.get("indices", []) if i.get("enabled", True)}
    # 2026-08-13 #60 方案A 首页1:1对齐回测: 读 #58 冻结表一次, 每条信号命中冻结则标权威 top1。
    _home_freeze = _etf_freeze()
    # =========================================================
    # 2026-08-14 P0-2 盘后补齐角标后端注入: 判定某信号是否为"迟到信号"
    # (数据源晚到, 21:00 backfill-evening 指数补采重算后才进 signal_daily, 从未进任何
    # 盘中重算轮, 用户白天没看到、更没被告知)。可靠时间源 = signal_intraday_log 表
    # (盘中每轮 _recompute_signals 后 append 当日 (time,index_id,signal) 快照)——
    # 而非给 signal_daily 加 created_at 列: signal_daily 是 DELETE+INSERT 全量重建,
    # 每次重算会把全历史行都重新盖成"本次爬取时间", 加列无法区分迟到(见 memory
    # homepage-814-signal-annotation)。
    # 口径(对齐用户 2026-08-14:"17:50 固化后 / 21:00 指数补采才进=迟到"):
    #   日期 D 的信号 (index_id,signal) 判迟到 ⟺ 三者同时满足:
    #   ① 指数 market 非 全球/港股(global/hk/hk_industry)——这些本就隔夜/晚发属"正常"
    #      (欧股/美股/港股每天都不进 A 股盘中轮, 不排除会把它们每天误标成盘后补齐)
    #   ② (index_id,signal) 从未出现在 D 的任意盘中 intraday_log 轮(即补采后才进)
    #   ③ D 当天盘中轮覆盖完整(轮数 >=3 且 首轮 <= 17:00)——否则日志不全(如
    #      intraday_log 建表当天 08-10 只有 20:36 一轮)无法判定, 宁可不标不误标
    # 自查: 8/14 div_lowvol/gz_399431(true, A股晚发) / 8/14 csi_399986(false) /
    # 8/13 cac40(false, 欧股) 均验证通过。
    _late_excl_markets = {"global", "hk", "hk_industry"}
    _mkt_cfg = {i["id"]: i.get("market") for i in cfg.get("indices", [])}
    if sig_dates:
        _dph = ",".join("?" * len(sig_dates))
        # per-date 盘中轮覆盖(轮数 + 首轮时间) → 判定当天日志是否完整
        _il_cov = {}
        for row in conn.execute(
            "SELECT date, COUNT(*) AS n, MIN(time) AS m FROM signal_intraday_log "
            "WHERE date IN (%s) GROUP BY date" % _dph, sig_dates,
        ).fetchall():
            _il_cov[row["date"]] = (row["n"], row["m"])
        # 当天(与任何盘中轮同一行)的确切 first-seen 时间, -s:* 已排除不入; 建 (date,index_id,signal)→首见。
        # 2026-08-15 补: 只取白天盘中轮 time <= '17:00'(保留 15:35 盘中轮) —— 排除 18:43/20:35
        # 两个盘后 check_signals 补采轮, 否则"白天盘中零记录、仅盘后才首现"的信号(如 8/14 中证
        # 银行 csi_399986 sell)会被误当"盘中出现过"→ 不标迟到。用户口径: 17:50 后补采才进 = 迟到。
        _il_first = {}
        for row in conn.execute(
            "SELECT date, index_id, signal, MIN(time) AS m FROM signal_intraday_log "
            "WHERE date IN (%s) AND time <= '17:00' "
            "GROUP BY date, index_id, signal" % _dph, sig_dates,
        ).fetchall():
            _il_first[(row["date"], row["index_id"], row["signal"])] = row["m"]
    else:
        _il_cov, _il_first = {}, {}
    for _s in sigs:
        _meta = _idx_meta.get(_s["index_id"])
        if _meta:
            _s["name"] = _meta["name"]
            _s["symbol"] = _meta["symbol"]
        # ETF本体注入去重（2026-08-09）：改调 _self_etf_for helper，复用 global_market/index_detail
        # 同一逻辑。func=fund_etf_hist_sina 的 index（如 cgb_10y_etf）本身就是 ETF，
        # board_etf_map.json 无此 key -> etf_for 返空 -> helper 用 symbol 剥前缀注入 match_method="self"。
        _self = _self_etf_for(_s["index_id"], cfg, conn)
        if _self:
            _s["etfs"] = _self["etfs"]
        else:
            _s["etfs"] = [dict(_e) for _e in (etf_for(_s["index_id"]).get("etfs") or [])]
        # 首页1:1对齐回测(#60 方案A): 命中冻结表 → 该信号 top1 = 回测标的(标 _bk_top)。
        _align_home_top1_to_backtest(_s, _home_freeze)
        # AI建议入样宇宙1:1对齐回测(#25): 信号是否在凯利回测入样宇宙内
        # (有跟踪 ETF 且带 track_score)。放 freeze 对齐后,冻结条目(回测只在宇宙内冻结)
        # 也带 track_score,不会误判。前端 AI 建议只在此宇宙内选。
        _s["_bt_in_universe"] = any(_e.get("track_score") is not None for _e in (_s.get("etfs") or []))
        # 2026-08-14 P0-2 盘后补齐角标: 迟到信号=true(数据源晚到 21:00 补采才进)。
        # 判定见上方注释: 非全球/港股市场 && 当日无 intraday_log 记录 && 当日盘中轮覆盖完整。
        _iid = _s["index_id"]
        # 2026-08-15 A2补: g.*(全球商品/利率/汇率, 读 daily_metric)与 s.*(情绪综合分, 读 score_daily)
        # 这两种前缀指标本就不会进 A 股盘中 intraday_log 轮(signal_intraday_log 中它们记录=0),
        # 正常隔夜/T+1 晚发属既定规律, 一旦触发会因"盘中无记录"被误标盘后补齐 → 一律不标。
        # 与上方 L809 "-s:* 已排除不入"注释、以及 _load_close_map 的 g./s. 前缀数据源分派一致。
        if _iid.startswith(("g.", "s.")):
            _bt_late = False
        elif _mkt_cfg.get(_iid, None) in _late_excl_markets:
            _bt_late = False
        else:
            _cov = _il_cov.get(_s["date"])
            _cov_ok = bool(_cov) and _cov[0] >= 3 and (_cov[1] or "24:00") <= "17:00"
            _seen = (_s["date"], _iid, _s["signal"]) in _il_first
            _bt_late = _cov_ok and not _seen
        _s["_bt_late"] = _bt_late
    # 信号至今盈亏（方案B后端算）：为每条信号算 since_return（至今涨跌%）+ since_correct（对错）。
    # 缓存 {index_id: {date: close/value}} 避免 N+1（同 index_id 多信号只查一次）。
    # 用传入 conn 查（不调 normalize.load_* 避免新建连接，遵守模块无状态原则）。
    # 方向判定：看多(buy/buy_aux/buy_special/buy_special_filtered/buy_backup)至今涨=对；
    # 看空(sell/sell_stop_loss)至今跌=对；band_hold 中性 since_correct=None 但 since_return 照算。
    if sigs:
        _close_map_cache: dict[str, dict[str, float]] = {}

        def _load_close_map(iid: str) -> dict[str, float]:
            if iid in _close_map_cache:
                return _close_map_cache[iid]
            m: dict[str, float] = {}
            if iid.startswith("g."):
                rows = conn.execute(
                    "SELECT date, value FROM daily_metric WHERE metric_id=? AND value IS NOT NULL",
                    (iid[2:],),
                ).fetchall()
                for r in rows:
                    m[r["date"]] = r["value"]
            elif iid.startswith("s."):
                rows = conn.execute(
                    "SELECT date, value FROM score_daily WHERE score_id=? AND value IS NOT NULL",
                    (iid[2:],),
                ).fetchall()
                for r in rows:
                    m[r["date"]] = r["value"]
            else:
                rows = conn.execute(
                    "SELECT date, close FROM index_daily WHERE index_id=? AND close IS NOT NULL",
                    (iid,),
                ).fetchall()
                for r in rows:
                    m[r["date"]] = r["close"]
            _close_map_cache[iid] = m
            return m

        _SELL_SIGNALS = {"sell", "sell_stop_loss"}
        for _s in sigs:
            _sig_type = _s.get("signal")
            _iid = _s.get("index_id")
            _sig_date = _s.get("date")
            _s["since_return"] = None
            _s["since_correct"] = None
            _cm = _load_close_map(_iid)
            _sig_close = _cm.get(_sig_date)
            if _sig_close is None:
                continue
            # 两段式信号固化(2026-08-14): 每条信号补当日收盘价 close(该信号日指数收盘价),
            # 供前端"已固化·可操作"展示与盘后固定价格窗口参考。
            _s["close"] = _sig_close
            # "至今"端收盘 = 最新可用收盘（非 score_date：score_date 是盘后评分日，盘中滞后于最新信号日，
            # 用它做锚会让 8/14 信号拿 8/14 收盘当至今端算 0、8/17 信号拿 8/14 收盘反向判错）
            _today_close = _cm.get(max(_cm.keys()))
            if _today_close is None:
                continue
            # 今日信号(date==最新信号日)无"至今"语义：since_return/since_correct 均 None
            # （sig_dates DESC 降序第一个=最新信号日期，前端 _renderSignalGrid 以 items 最新日期为今日）
            if _sig_date == sig_dates[0]:
                continue
            # 边界：最新可用收盘未超过信号日（如该指数 817 无收盘）→ 尚无一天走势，视为未结算（不算 0 硬判）
            if max(_cm.keys()) <= _sig_date:
                continue
            _since_ret = round((_today_close - _sig_close) / _sig_close * 100, 2)
            _s["since_return"] = _since_ret
            # band_hold 中性 -> since_correct=None（since_return 照算）
            if _sig_type == "band_hold":
                _s["since_correct"] = None
            else:
                _is_sell = _sig_type in _SELL_SIGNALS
                _s["since_correct"] = (_since_ret < 0) if _is_sell else (_since_ret > 0)

        # ETF 至今盈亏（2026-08-05）：基于 ETF 累计净值(accum_nav)算信号日至今涨跌幅，注入 etfs[] 每个候选。
        # 和指数 since_return（L449）口径一致：信号日累计净值 vs 最新累计净值。今日信号无"至今"语义=None。
        # 跨库查 etf_national_team.db（etf_daily 表 accum_nav 列,已复权除权日不跳变）：
        # etf_since_return=涨跌幅%(2位小数)，etf_price_diff=今日accum_nav-信号日accum_nav(3位小数，元/份)。
        # accum_nav 缺失(QDII跨境ETF等) -> None，前端跳过不显。
        _etf_codes = set()
        for _s in sigs:
            for _e in (_s.get("etfs") or []):
                if _e.get("code"):
                    _etf_codes.add(_e["code"])
        _etf_close_cache: dict[str, dict[str, float]] = {}
        _etf_price_cache: dict[str, dict[str, float]] = {}  # etf_code->{date: close} 两段式信号固化
        if _etf_codes:
            try:
                from .collector.etf_national_team import get_conn as _etf_get_conn
                _ec = _etf_get_conn()
                # 2026-08-14 fix(F1回归): 拆两条独立查询, _etf_close_cache 恢复 accum_nav IS NOT NULL,
                # _etf_price_cache(etf_close) 单独查 close。共用一条查询+close IS NOT NULL 会让
                # 有 close 但 accum_nav 为 NULL 的行进 _etf_close_cache -> _today_close=None -> 整体 None。
                _etf_close_sql = (
                    "SELECT etf_code, date, accum_nav FROM etf_daily "
                    "WHERE etf_code IN (%s) AND accum_nav IS NOT NULL" % ",".join("?" * len(_etf_codes))
                )
                for _r in _ec.execute(_etf_close_sql, tuple(_etf_codes)).fetchall():
                    _etf_close_cache.setdefault(_r["etf_code"], {})[_r["date"]] = _r["accum_nav"]
                _etf_price_sql = (
                    "SELECT etf_code, date, close FROM etf_daily "
                    "WHERE etf_code IN (%s) AND close IS NOT NULL" % ",".join("?" * len(_etf_codes))
                )
                for _r in _ec.execute(_etf_price_sql, tuple(_etf_codes)).fetchall():
                    _etf_price_cache.setdefault(_r["etf_code"], {})[_r["date"]] = _r["close"]
                _ec.close()
            except Exception:  # noqa: BLE001
                pass
        for _s in sigs:
            _sig_date = _s.get("date")
            for _e in (_s.get("etfs") or []):
                _e["etf_since_return"] = None
                _e["etf_price_diff"] = None
                _code = _e.get("code")
                if not _code:
                    continue
                # 2026-08-08 fix: self ETF(如 511260=cgb_10y_etf)数据在 index_daily 不在 etf_daily,
                # _etf_close_cache 永远 None。self 时用 _load_close_map(index_id) 取 index_daily close,
                # self 的 etf_since_return=指数 since_return(本体即ETF,正确)
                if _e.get("match_method") == "self":
                    _cm = _load_close_map(_s["index_id"])
                    _price_cm = _cm
                else:
                    _cm = _etf_close_cache.get(_code)
                    _price_cm = _etf_price_cache.get(_code)
                # 两段式信号固化(2026-08-14): 每条 ETF 候选补当日收盘价 etf_close(该信号日),
                # 今日信号也有(收盘价版,供盘后固定价格窗口参考)。
                # 末日兜底: 该信号日 etf_daily 无 close(如银行ETF今日数据滞后)时取最新可用 close,
                # 对齐 etf_since_return 的 max(_cm.keys()) 兜底, 供盘后固定价格窗口可操作参考。
                if _price_cm:
                    _e["etf_close"] = _price_cm.get(_sig_date)
                    if _e["etf_close"] is None and _price_cm:
                        _e["etf_close"] = _price_cm.get(max(_price_cm.keys()))
                # 今日信号(date==最新信号日)无"至今"语义，对齐指数口径
                if _sig_date == sig_dates[0]:
                    continue
                if not _cm:
                    continue
                _sig_close = _cm.get(_sig_date)
                if _sig_close is None:
                    continue
                # 今日 = 最新 etf_daily.date（per-ETF 最大日期，不同 ETF 末日可能不同）
                _today_close = _cm.get(max(_cm.keys()))
                if _today_close is None:
                    continue
                _ret = round((_today_close - _sig_close) / _sig_close * 100, 2)
                _e["etf_since_return"] = _ret
                _e["etf_price_diff"] = round(_today_close - _sig_close, 3)

    # AI宏降亏命中标注(2026-08-13 首页 AI 开关): 每条信号注入 ai_macro:{hit, filters}
    # 8 键(toggle 基础5+核心3, v1.1.2 excludeSpecialBear 升四档)谓词与凯利区 AI宏默认降亏
    # (lab.js _kellyPassesFadeFilters + _kellyDefaultFilters)同源; +1类回测剔除由
    # 各信号 _bt_in_universe 字段承载(L840, 端到端三处一致, 见模块级注释)。
    # 默认组合只开主键 excludeSpecialBear(四档); 备选键 legacyMa60Special/declinePhaseSpecial
    # 默认关, 仅在用户于凯利区手动开启时参与命中(首页默认不标这两键)。
    # 信号级粒度降级: price_bin(ETF 买入价分位)依赖子条件在 overview 不可判定(无价格字段),
    # 不参与命中(漏标不误标, 诚实标注见 _ai_macro_hit_filters 模块级注释)。
    if sigs:
        _sig_stats = sigstats.load()  # 主库 data/signal_stats.json(与 overview 同源)
        _market_map = _ai_macro_build_market_map(cfg)
        _tier_state, _tier_dates, _ma60_bull_state = _ai_macro_build_market_state(conn)
        # #69: cyb(创业板指)四档状态, 供新键 excludeSpecialBearCyb 谓词 + 注入 overview 信号供未来前端用
        _cyb_state, _cyb_dates = _ai_macro_build_cyb_tier(conn)
        _ctx = {
            "rating_of": lambda _s: _ai_macro_rating_of(_s, _sig_stats),
            "market_of": lambda _iid: _market_map.get(_iid or "", ""),
            "track_score_of": _ai_macro_track_score_of,
            "tier_of": lambda _d: _ai_macro_tier_at(_d, _tier_state, _tier_dates),
            "ma60_bull_of": lambda _d: _ai_macro_ma60_bull_at(_d, _ma60_bull_state, _tier_dates),
            "cyb_tier_of": lambda _d: _ai_macro_tier_at(_d, _cyb_state, _cyb_dates),
        }
        for _s in sigs:
            _f = _ai_macro_hit_filters(_s, _ctx)
            _s["ai_macro"] = {
                "hit": bool(_f),
                "filters": _f,
                # #69: 注入 cyb 四档供未来前端用(新键 excludeSpecialBearCyb 展示可读, 不参与默认判定)
                "cyb_tier": _ai_macro_tier_at(str(_s.get("date") or ""), _cyb_state, _cyb_dates),
            }

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

    # 近90日「情绪日历」：#19 首页近期冰点与情绪分买卖点信号合并(只后端, 前端另派)。
    # 背景: 近期冰点卡现有9日(recent_freeze, 近120日 LIMIT 9)硬塞当日信号=9/9全空, 必须扩到近90日
    # 合并进"情绪日历"才有内容。数据源全现成, 无新算法, 纯按 date join:
    #   - freeze: score_daily WHERE is_freeze=1 (近90日), 过滤低质 low_alert(值75-77 是"低位机会>75"口径,
    #     非<20冰点混标, 合并数组里不作为冰点展示, 见 research 文档 §4「展示形态 schema 提案」)。
    #   - signals: signal_daily WHERE index_id LIKE 's.%' (情绪分买卖点信号, 同 sentiment-*.json r.signals 同源,
    #     信号算法 app/compute/signals.py)。
    #   - 按 date join, 同日 freeze+signals 都并进同一天; signals 组内 buy>buy_aux>sell 排序
    #     (对齐前端 renderSentimentSignalList 口径)。
    #   - 日期降序; 新增旁路字段, 不动既存 recent_freeze / signals_today 行为(§5.3 核心保障)。
    #   研究文档: docs/market-state/sentiment-signal-freeze-merge-research.md
    _cal_start = (datetime.strptime(score_date, "%Y%m%d") - timedelta(days=90)).strftime("%Y%m%d")
    _cal_freeze_rows = conn.execute(
        "SELECT date, score_id, value FROM score_daily "
        "WHERE is_freeze=1 AND score_id!='low_alert' AND date>=? ORDER BY date",
        (_cal_start,)
    ).fetchall()
    _cal_sig_rows = conn.execute(
        "SELECT date, index_id, signal, reason FROM signal_daily "
        "WHERE index_id LIKE 's.%' AND date>=? ORDER BY date",
        (_cal_start,)
    ).fetchall()
    _cal_by_date = {}
    for _r in _cal_freeze_rows:
        _d = _cal_by_date.setdefault(_r["date"], {"date": _r["date"], "freeze": [], "signals": []})
        _val = _r["value"]
        _d["freeze"].append({"score_id": _r["score_id"], "value": (round(_val, 2) if _val is not None else None)})
    _sig_ord = {"buy": 0, "buy_aux": 1, "sell": 2}
    for _r in _cal_sig_rows:
        _d = _cal_by_date.setdefault(_r["date"], {"date": _r["date"], "freeze": [], "signals": []})
        _d["signals"].append({
            "index_id": _r["index_id"],
            "signal": _r["signal"],
            "reason": _r["reason"],
        })
    for _d in _cal_by_date.values():
        _d["signals"].sort(key=lambda _s: _sig_ord.get(_s["signal"], 9))
    sentiment_calendar = [dict(_d) for _d in sorted(
        _cal_by_date.values(), key=lambda _d: _d["date"], reverse=True)]

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

    # P1-④+ KPI 小卡 sparkline 扩展：所有有数据的卡统一加 *_6m 字段（布局和谐，
    # flex-wrap 换行后每行统一高度，动态展示）。a_sentiment/cross_market/fear_greed
    # 已有独立字段（上面 asent_6m/cross_6m/fg_6m），此处补其余 18 metric + 6 score。
    # daily_metric 类（18 个）：成交额/量比/宽度计数/炸板封板率/金债/QVIX/融资融券/换手率5项
    # score_daily 类（6 个）：5 大宽基 + 创业板/科创50 情绪分（0-100，含 is_freeze/is_overheat 标记）
    KPI_SPARK_METRIC_IDS = (
        "a_amount", "a_volume_ratio",
        "a_width_zt_count", "a_width_dt_count", "a_width_up_count", "a_width_down_count",
        "a_width_zhaban_rate", "a_width_fengban_rate",
        "gold", "cn10y", "a_qvix_300",
        "a_fund_margin", "a_fund_main",
        "a_turnover_mean", "a_turnover_median", "a_turnover_p90", "a_turnover_p10", "a_turnover_gt5_pct",
        "lhb_count",  # 龙虎榜上榜家数（回填6m历史后，2026-08-05）
    )
    KPI_SPARK_SCORE_IDS = (
        "sentiment_sz50", "sentiment_hs300", "sentiment_csi500",
        "sentiment_csi1000", "sentiment_cyb", "sentiment_kc50",
        "high_alert", "low_alert",   # 新增: sparkline + 数据积累
    )
    kpi_spark_6m = {}
    for _mid in KPI_SPARK_METRIC_IDS:
        _rows = conn.execute(
            "SELECT date, value FROM daily_metric WHERE metric_id=? AND date>=? ORDER BY date",
            (_mid, six_m_start),
        ).fetchall()
        if len(_rows) >= 2:
            kpi_spark_6m[f"{_mid}_6m"] = [{"date": r["date"], "value": r["value"]} for r in _rows]
    for _sid in KPI_SPARK_SCORE_IDS:
        _rows = conn.execute(
            "SELECT date, value, is_freeze, is_overheat FROM score_daily "
            "WHERE score_id=? AND date>=? ORDER BY date",
            (_sid, six_m_start),
        ).fetchall()
        if len(_rows) >= 2:
            kpi_spark_6m[f"{_sid}_6m"] = [
                {"date": r["date"], "value": r["value"], "is_freeze": r["is_freeze"], "is_overheat": r["is_overheat"]}
                for r in _rows
            ]

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
            # 持续故障降级：同一 metric_id+message 在最近 N 个采集日都报 error，
            # 降级为 warn（黄点），message 加"[持续X天 已知故障]"前缀。
            # 避免红点常亮困扰用户，真新故障（<N天）仍红点报。
            _N_DEGRADE = 3
            _recent_dates = [r["run_date"] for r in conn.execute(
                "SELECT DISTINCT run_date FROM collect_log ORDER BY run_date DESC LIMIT ?",
                (_N_DEGRADE,)
            ).fetchall()]
            _degraded_items = []
            for r in _filtered:
                _msg = r["message"] or ""
                _cnt = 0
                if _recent_dates and r["metric_id"]:
                    _ph = ",".join("?" * len(_recent_dates))
                    _cnt = conn.execute(
                        f"SELECT COUNT(DISTINCT run_date) FROM collect_log "
                        f"WHERE metric_id=? AND message=? AND status!=? AND run_date IN ({_ph})",
                        (r["metric_id"], _msg, "ok", *_recent_dates)
                    ).fetchone()[0]
                if _cnt >= _N_DEGRADE and r["status"] == "error":
                    _degraded_items.append({
                        "metric_id": r["metric_id"],
                        "status": "warn",
                        "message": f"[持续{_cnt}天 已知故障] {_msg}",
                    })
                else:
                    _degraded_items.append({
                        "metric_id": r["metric_id"],
                        "status": r["status"],
                        "message": _msg,
                    })
            collect_health["level"] = "error" if any(it["status"] == "error" for it in _degraded_items) else "warn"
            collect_health["items"] = _degraded_items

    # 行业热力图：盘中时用快照行业覆盖（P2-B，含 net_inflow/lead_stock），收盘后用 DB（P0-A 已修 SQL）
    heatmap = industry_heatmap(conn, cfg)
    try:
        from .collector.intraday_snapshot import maybe_override_heatmap
        heatmap = maybe_override_heatmap(heatmap)
    except Exception:  # noqa: BLE001
        pass

    # 数据时效横幅补充源日期：期货/ETF汪汪队/美股从静态导出 JSON 取末日期
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
        # 美股: 从 DB 取最新日期（与 csi_div 同路径，不依赖 global-all.json 生成顺序）。
        # 原 _jload("global-all.json") 读静态 JSON，但 export.py 先生成 overview 再生成
        # global-all，致 overview 读到上一版 global-all 的旧末日期（us_dji_date 滞后 1 天）。
        _ud_db = conn.execute(
            "SELECT date FROM index_daily WHERE index_id='us_dji' ORDER BY date DESC LIMIT 1"
        ).fetchall()
        if _ud_db:
            extra_dates["us_dji_date"] = _ud_db[0]["date"]
        # 中证红利: 中证指数公司盘后次日发布，从 DB 取最新日期(不在 SPARKLINE_INDEX_IDS 中)
        _cd = conn.execute("SELECT date FROM index_daily WHERE index_id='csi_div' ORDER BY date DESC LIMIT 1").fetchall()
        if _cd:
            extra_dates["csi_div_date"] = _cd[0]["date"]
    except Exception:  # noqa: BLE001
        pass

    # 汪汪队(ETF汪汪队)最新信号 + 共振聚合：首页🐶卡片展示，点击跳专区
    nt_signals_today = None
    try:
        from .collector.etf_national_team import latest_signals_overview, recent_signals_overview
        nt_signals_today = latest_signals_overview()
        if nt_signals_today:
            nt_signals_today["recent"] = recent_signals_overview()
    except Exception:  # noqa: BLE001
        pass

    # 两段式信号固化 signals_meta(2026-08-14 实施, 方案见 docs/signal-finalize-time.md §5.3):
    # 基于服务端当前时点 + 当日是否有数据判定版本(不新增采集/不新增 launchd)。
    # 规则: A股 15:03 收盘价首轮定稿(15:03-15:36 不变, 不会再消失), 15:05-15:30 盘后
    # 固定价格窗口可按收盘价操作; 17:50 update_all 后含港股/欧股/国债=full;
    # 20:36 晚间快照后=evening 当天最终。非交易日/盘前(score_date!=今日)展示上日已定稿
    # 信号, 视为 full。前端由 signals_meta 驱动三态提示条, 禁止硬编码时间。
    _now = datetime.now()
    _today_str = _now.strftime("%Y%m%d")
    _hm = _now.hour * 100 + _now.minute
    _is_today = score_date == _today_str
    _has_signals = bool(sigs)
    if not _is_today:
        _meta_version, _meta_finalized, _meta_coverage = "full", True, "all"
    elif not _has_signals or _hm < 1503:
        _meta_version, _meta_finalized, _meta_coverage = "a-share-close", False, "a-share"
    elif _hm < 1750:
        _meta_version, _meta_finalized, _meta_coverage = "a-share-close", True, "a-share"
    elif _hm < 2036:
        _meta_version, _meta_finalized, _meta_coverage = "full", True, "all"
    else:
        _meta_version, _meta_finalized, _meta_coverage = "evening", True, "all"
    if not _meta_finalized:
        _finalized_note = "盘中预估,收盘后重算定版,信号可能消失"
    elif _meta_version == "a-share-close":
        _finalized_note = "当日A股信号已用收盘价定稿(15:03),不会再消失"
    elif _meta_version == "full":
        # W1(2026-08-14): 17:50 update_all 起跑到 ~18:42 才完成信号重算(欧股/国债数据晚间入库),
        # 期间数据仍是 A 股收盘价版。文案放宽为"陆续补齐", 与 docs/signal-finalize-time.md 对齐,
        # 不硬编码 18:45 阈值(20:36 同理, 数字阈值不灵活)。
        # W3(2026-08-16 用户定修法①): full 文案注明已定稿时点(A股15:03、港股/欧股/国债17:50起补齐),
        #   并说清 21:00 指数补采后最终定稿。与 evening 文案拆开(按版本走), 不再共用/合并 full/evening。
        _finalized_note = "当日完整版信号:A股15:03已定稿、港股/欧股/国债17:50起补齐,21:00指数补采后最终定稿"
    else:
        # evening(20:36+, 当天最终版, 文案跟版本走——不再沿用 full 的"进行式"说法)
        # W2(2026-08-14 首页8/14信号补): 21:00 backfill-evening 指数(如 div_lowvol/gz_399431 收盘价)
        # 数据源晚到才发布→补采重算 signal_daily, 可能在该时点后仍新增/变动信号, 故 20:36 并非真"最终"。
        # W3(2026-08-16 用户定修法①): evening 如实说"已定稿", 并注明晚发指数补采(21:00)可能再补。
        # 此文案为 signals_meta.finalized_note, 前端提示条由后端注入驱动, 禁止前端硬编码时间。
        _finalized_note = "当日信号已定稿:A股15:03、港股/欧股/国债17:50已补齐;晚发指数补采(21:00)可能再补"
    signals_meta = {
        "version": _meta_version,
        "generated_at": _now.strftime("%Y-%m-%d %H:%M"),
        "coverage": _meta_coverage,
        "finalized": _meta_finalized,
        "finalized_note": _finalized_note,
        "operable_window": "15:05-15:30 盘后固定价格交易窗口可按收盘价操作",
    }

    # 2026-08-18 后端根治「今日锚过时」(前端补丁 121e6fb63/b0c87c1831 同根因的源头修):
    # 盘中 signal_daily 每轮 _recompute_signals 已写入今日(如 20260818)信号, 但 score_daily
    # (a_sentiment 评分)可能尚未算到今日(score_date 停在 20260817/更早), 致 overview.date
    # 过时 → 前端所有以 overview.date 为"今日锚"的消费点(信号卡今日高亮/走势图 T 日提示等)
    # 误判"无今日信号/数据截止"。这里在源头让 overview.date = max(score_date, 最新信号日),
    # 只前进不后退, 根治而非各消费点逐个补丁。sig_dates 按 date DESC, 首元素即最新信号日。
    _overview_date = score_date
    if sig_dates and sig_dates[0] > _overview_date:
        _overview_date = sig_dates[0]

    return {
        "date": _overview_date,
        "collected_at": collected_at,
        "collect_health": collect_health,
        "signals_meta": signals_meta,
        # 兼容字段（保留）
        "scores": scores,
        "signals_today": sigs,
        "recent_freeze": freeze_days,
        # #19 近90日「情绪日历」：按 date 合并冰点+情绪分信号(date → {freeze, signals})。
        # 新增旁路字段, 与既存 recent_freeze/signals_today 兼容不冲突(§22/§5.3)。
        "sentiment_calendar": sentiment_calendar,
        # 今日快照：每张卡自带独立 date(自身 score_id 的 max(date))，
        # 单指标缺失不拖垮其它卡；无 date 的行(理论上不会发生)回退 score_date。
        "today": {
            "scores": {k: {**v, "date": v.get("date") or score_date} for k, v in scores.items()},
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
        # P1-④+ KPI 小卡 sparkline 扩展：20 个 *_6m 字段扁平化合并（a_amount_6m/sentiment_sz50_6m 等）
        **kpi_spark_6m,
    }


def a_stock(conn, cfg, start, end, *, cache=None, include_etf=False):
    """复刻 /api/a-stock。include_etf=True 时注入 ETF 候选列表（export 用）。"""
    groups = ("a_width", "a_fund", "a_sentiment", "lhb", "unlock", "ipo", "cov")
    metrics = {}
    for m in metrics_for_groups(cfg, *groups):
        metrics[m["id"]] = {"name": m["name"], "unit": m.get("unit"), "data": metric_series(conn, m["id"], start, end, cache=cache)}
    # a_amount 补 source 字段：盘中 intraday 半日值(source='intraday')需前端视觉区分，
    # 避免半日值混入日频序列尾部下掉(2026-08-04 事故)。绕过 cache 直接查带 source。
    if "a_amount" in metrics:
        amt_rows = conn.execute(
            "SELECT date, value, source FROM daily_metric WHERE metric_id='a_amount' "
            "AND date BETWEEN ? AND ? ORDER BY date",
            (start, end),
        ).fetchall()
        metrics["a_amount"]["data"] = [
            {"date": r["date"], "value": r["value"], "source": r["source"]} for r in amt_rows
        ]
    indices = {}
    for i in indices_for_market(cfg, "a"):
        entry = {
            "name": i["name"],
            "symbol": i.get("symbol"),  # 2026-08-06 走势图卡片标题加指数代码（indexIdToCode 剥前缀用）
            "data": index_series(conn, i["id"], start, end, cache=cache),
            "strategy": strategy_desc(i["id"], cfg),
        }
        if include_etf:
            entry.update(etf_for(i["id"]))
        indices[i["id"]] = entry
    if include_etf:
        _enrich_etfs_since_return(conn, indices)
    return {"metrics": metrics, "indices": indices}


def hk(conn, cfg, start, end, *, cache=None, stats_all_dict=None):
    """复刻 /api/hk。"""
    indices = {}
    for i in indices_for_market(cfg, "hk"):
        entry = {
            "name": i["name"],
            "symbol": i.get("symbol"),  # 2026-08-06 走势图卡片标题加指数代码
            "data": index_series(conn, i["id"], start, end, cache=cache),
            "strategy": strategy_desc(i["id"], cfg),
        }
        entry.update(etf_for(i["id"]))  # 2026-07-28 注入港股 ETF 候选（hsi/hstech/hscei，board_etf_map 单源）
        indices[i["id"]] = entry
    _enrich_etfs_since_return(conn, indices)
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
    # 2026-08-09 走势图问题2：注入 etf_for（跨境 ETF 候选，供全球指数走势卡相关ETF展示，
    # 对齐 industry/a_stock 的 **etf_for(iid) 结构）。board_etf_map.json 由 build_board_etf_map.py 生成。
    indices = {}
    for i in indices_for_market(cfg, "global"):
        iid = i["id"]
        indices[iid] = {
            "name": i["name"],
            "symbol": i.get("symbol"),  # 2026-08-06 走势图卡片标题加指数代码
            "data": index_series(conn, iid, start, end, cache=cache),
            "strategy": strategy_desc(iid, cfg),
            **etf_for(iid),
        }
        # ETF本体兜底（cgb_10y_etf 等 fund_etf_hist_sina 指数）：board_etf_map.json 无此 key
        # -> etf_for 返空 -> 走势卡"无ETF"。此处用 symbol 剥前缀注入 self ETF。
        if not indices[iid].get("etfs"):
            _self = _self_etf_for(iid, cfg, conn)
            if _self:
                indices[iid]["etfs"] = _self["etfs"]
    _enrich_etfs_since_return(conn, indices)
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
    """复刻 /api/index/{index_id}。include_etf=True 时注入 ETF 候选列表（export 用）。
    8 宽基(hs300/sh/sz/csi500/cyb/sz50/csi1000/kc50)注入 tiers(四档大盘状态, 对齐 ohlc 日期)
    供前端走势图四档色带(纯展示, #73)。"""
    sa = stats_all_dict if stats_all_dict is not None else stats_all()
    ohlc = index_series(conn, index_id, start, end, cache=cache)
    result = {
        "ohlc": ohlc,
        "signals": signals(conn, index_id, start, end, cache=cache),
        "stats": stats_for(sa, index_id),
        "strategy": strategy_desc(index_id, cfg),
    }
    # 8 宽基注入四档大盘状态(纯展示, 不影响过滤; 与回测/首页同口径 §22/§23.6, #73)。
    # tiers 数组与 ohlc 一一对应(每日期前向填充最近可用 tier, 无状态=None)。
    # hs300 保持原路径(含 ma60_bull, 逐位与现状一致); cyb 复用 _ai_macro_build_cyb_tier;
    # 其余 sh/sz/csi500/sz50/csi1000/kc50 用 _ai_macro_build_index_tiers(同口径算法)。
    _WIDE_BASE_TIER_IDS = {"hs300", "sh", "sz", "csi500", "cyb", "sz50", "csi1000", "kc50"}
    if index_id in _WIDE_BASE_TIER_IDS:
        if index_id == "hs300":
            _tiers, _tier_dates, _ma60 = _ai_macro_build_market_state(conn)
        elif index_id == "cyb":
            _tiers, _tier_dates = _ai_macro_build_cyb_tier(conn)
        else:
            _tiers, _tier_dates = _ai_macro_build_index_tiers(conn, index_id)
        if _tiers:
            _tier_list = []
            _last = None
            for _o in ohlc:
                _t = _ai_macro_tier_at(_o["date"], _tiers, _tier_dates)
                if index_id == "hs300":
                    _m = _ai_macro_ma60_bull_at(_o["date"], _ma60, _tier_dates)
                    _last = _t if _t is not None else _last
                    _tier_list.append({"date": _o["date"], "tier": _last,
                                       "ma60_bull": bool(_m)})
                else:
                    _last = _t if _t is not None else _last
                    _tier_list.append({"date": _o["date"], "tier": _last})
            result["tiers"] = _tier_list
    if include_etf:
        result.update(etf_for(index_id))
        # ETF本体兜底（cgb_10y_etf 等 fund_etf_hist_sina 指数）：board_etf_map.json 无此 key
        # -> etf_for 返空 -> 弹窗"无ETF"。此处用 symbol 剥前缀注入 self ETF。
        if not result.get("etfs"):
            _self = _self_etf_for(index_id, cfg, conn)
            if _self:
                result["etfs"] = _self["etfs"]
        # 注入 etf_since_return + etf_price_diff（对齐 overview/a_stock 口径，
        # 否则 index detail JSON 的 etfs 全 None，走势卡弹窗盈亏缺失）
        if result.get("etfs"):
            _enrich_etfs_since_return(conn, {index_id: result})
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

    # 中信/机构/国泰君安 4品种合计净加仓 15天明细：最近15个交易日合计净加仓方向 vs 上证50次日涨跌
    citic_ih_detail = compute_role_ih_detail(role="中信期货", n_days=15)
    inst_ih_detail = compute_role_ih_detail(role="top20", n_days=15)
    guotai_ih_detail = compute_role_ih_detail(role="国泰君安", n_days=15)

    return {"summary": summary, "positions": positions, "positions_ratio": positions_ratio,
            "accuracy": accuracy, "accuracy_history": acc_history, "latest_bet": latest_bet,
            "citic_ih_detail": citic_ih_detail, "inst_ih_detail": inst_ih_detail,
            "guotai_ih_detail": guotai_ih_detail}


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
    """汪汪队宽基 ETF 资金动向：12 只宽基 ETF 近份额+成交额+信号。"""
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


# ============ 公募基金 (public_fund) ============
# 7 个薄包装: 直接复用 collector.export_data() 返回的 7 类 JSON, 避免重复采集。
# main.py 路由（/api/public-fund-*）与 static-site/export.py 共用。
# export_data() 返回 (summary, holdings, industry, top20, asset_alloc,
# industry_fund_map, manuf_subind_fund_map) 共 7 值, 这里 7 个薄包装各取所需。
# 2026-07-20 补 industry_fund_map + manuf_subind_fund_map 薄包装 + export.py 写盘
# (原仅 5 个薄包装, export.py 也只写 5 JSON, 漏第 6/7 值致下次季报数据滞后)。

def public_fund_summary():
    """公募基金总览: 8 指标 + 仓位轨迹 + 净申赎时序 + 各表行数。"""
    from .collector.public_fund import export_data
    summary, _h, _i, _t, _a, _ifm, _msfm = export_data()
    return summary


def public_fund_holdings():
    """Top50 重仓股: 基金覆盖家数 + 持股总数 + 持仓总市值。"""
    from .collector.public_fund import export_data
    _s, holdings, _i, _t, _a, _ifm, _msfm = export_data()
    return holdings


def public_fund_industry():
    """行业聚合: 全市场行业配置汇总（按行业 SUM weight_pct 排序）。"""
    from .collector.public_fund import export_data
    _s, _h, industry, _t, _a, _ifm, _msfm = export_data()
    return industry


def public_fund_top20():
    """Top20 调仓: 当期 vs 上期持股总市值对比 + 环比变化%。"""
    from .collector.public_fund import export_data
    _s, _h, _i, top20, _a, _ifm, _msfm = export_data()
    return top20


def public_fund_asset_alloc():
    """头部基金资产配置分布: AVG 股票/债券/现金 占比 + 覆盖家数。"""
    from .collector.public_fund import export_data
    _s, _h, _i, _t, asset_alloc, _ifm, _msfm = export_data()
    return asset_alloc


def public_fund_industry_fund_map():
    """逐只基金-行业映射, 按合并后行业名分组(27行业+制造业935只)。
    供前端"点击展开某行业基金列表"按需 fetch。"""
    from .collector.public_fund import export_data
    _s, _h, _i, _t, _a, industry_fund_map, _msfm = export_data()
    return industry_fund_map


def public_fund_manuf_subind_fund_map():
    """制造业子行业 -> 基金详情列表(19子行业, 电子712/通信431)。
    前端"子行业下钻到基金"弹窗, 方案C Step5。"""
    from .collector.public_fund import export_data
    _s, _h, _i, _t, _a, _ifm, manuf_subind_fund_map = export_data()
    return manuf_subind_fund_map


def public_fund_position_backtest():
    """G功能: 88 魔咒历史回测 + 极值标注。
    独立计算(不走 export_data 7 元组), 复用 fund_position_history lg 源 avg_position+close 时序。
    返回 {report_date, extremes{highs,lows Top5}, stats{spell_88,dip_80}, current}。"""
    from .collector.public_fund import _compute_position_backtest, get_conn
    conn = get_conn()
    try:
        return _compute_position_backtest(conn)
    finally:
        conn.close()


def public_fund_holding_concentration_ts():
    """N功能: 抱团集中度历史时序(10期季报)。
    独立计算(不走 export_data 7 元组), 复用 fund_holding_stock 全量 report_date 时序。
    返回 {report_date, period_count, series:[{date, concentration_top10, concentration_top20,
    herfindahl, fund_count, total_stocks, total_value_wan, top10_stocks}]}。"""
    from .collector.public_fund import _compute_holding_concentration_timeseries, get_conn
    conn = get_conn()
    try:
        return _compute_holding_concentration_timeseries(conn)
    finally:
        conn.close()


def public_fund_position_estimate():
    """方案A: 今日预估仓位 + 历史预估时序 (净值回归反推 + lg 校准)。
    独立计算(不走 export_data 7 元组), 复用 fund_daily_nav 历史净值时序 + fund_index_daily 沪深300。
    返回 {report_date, current{position_estimate,raw_slope,lg_latest_position,...},
    history:[{date,position,raw_slope}], vs_lg:[{date,estimate,lg,diff}], meta}。
    需先跑 `python -m app.collector.public_fund backfill-nav` 回填历史净值 + fetch_index_daily 沪深300。"""
    from .collector.public_fund import _compute_position_estimate, get_conn
    conn = get_conn()
    try:
        return _compute_position_estimate(conn)
    finally:
        conn.close()


def public_fund_scale_change_ts():
    """N功能: 全市场规模变动历史时序(113期季报, 1998Q2-2026Q2)。
    独立计算(不走 export_data 7 元组), 复用 fund_scale_change 全量时序。
    summary.scale_change_history 只取 LIMIT 20 期不够 N 功能全量分析, 故独立导出全量 113 期。
    返回 {report_date, period_count, series:[{date, net_purchase_share, end_net_asset,
    purchase_share, redeem_share, end_total_share, fund_count}]}。"""
    from .collector.public_fund import _compute_scale_change_ts, get_conn
    conn = get_conn()
    try:
        return _compute_scale_change_ts(conn)
    finally:
        conn.close()


def public_fund_industry_rotation_ts():
    """F功能: 全市场行业配置轮动历史时序(50期季报, 2017Q1-2026Q2, 过滤<50 fund 脏数据期)。
    独立计算(不走 export_data 7 元组), 复用 fund_industry_alloc 全量时序。
    行业名应用 IND_MERGE_MAP 合并(67原始名->27标准名, 和 industry_fund_map 一致)。
    返回 {report_date, period_count, industries_order, series:[{date, fund_count,
    industries:{合并行业名:平均权重}}]}。"""
    from .collector.public_fund import _compute_industry_rotation_ts, get_conn
    conn = get_conn()
    try:
        return _compute_industry_rotation_ts(conn)
    finally:
        conn.close()


def public_fund_sw_industry_alloc():
    """申万一级行业配置(反查口径): 基金 top10 重仓股按申万一级聚合, 揭示真实风格暴露。

    独立计算(不走 export_data 7 元组, 遵循 commit 190c8f7e 教训), 复用 fund_portfolio_hold
    + sw_components.json 反查。返回 {report_date, coverage_pct, coverage_note, period_count,
    fund_count, industries:[{industry_name, total_weight, total_value, fund_count, avg_weight}]}。

    3 个硬限制(前端诚实标注):
      1. 时序不可用: fund_portfolio_hold 仅 1 期(最新季报), 无历史对比
      2. 覆盖率 ~42%: top10 重仓股平均占净值 42.39%, 仅反映重仓股部分行业暴露
      3. 反查口径: 基于重仓股反查申万一级(非基金直接披露), 有信息差价值但非官方披露

    供前端"行业配置"卡第四档 'sw' 切换( vs 证监会口径 industry 19 大类)。"""
    from .collector.public_fund import (
        _compute_sw_industry_alloc, _load_stock_industry_map, _latest_report_dates, get_conn)
    conn = get_conn()
    try:
        report_date = _latest_report_dates(1)[0]
        stock_ind_map = _load_stock_industry_map()
        return _compute_sw_industry_alloc(conn, report_date, stock_ind_map)
    finally:
        conn.close()


def public_fund_score(top_n: int = 100):
    """阶段1: 公募基金综合评分头部N只(按综合分降序)。
    独立计算(不走 export_data 7元组), 复用 fund_score 表(由 compute_all_scores 写入)。
    返回 {date, count, method, data:[{fund_code, fund_name, fund_type, composite_score,
    star_rating, score_return, ..., half_kelly_position, final_suggestion, ...}]}。
    """
    import sqlite3
    from .collector.public_fund import DB_PATH, SCORE_METHOD_VERSION
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT MAX(score_date) as latest FROM fund_score"
        ).fetchone()
        latest = row["latest"]
        if not latest:
            return {"date": None, "count": 0, "method": SCORE_METHOD_VERSION, "data": []}
        rows = conn.execute(
            "SELECT s.fund_code, b.fund_name, b.fund_type, "
            "s.composite_score, s.star_rating, "
            "s.score_return, s.score_risk_adjusted, s.score_drawdown, "
            "s.score_stability, s.score_scale, s.score_fee, "
            "s.sharpe, s.sortino, s.calmar, s.information_ratio, s.alpha, "
            "s.manager_score, s.m1_tenure, s.m2_scale, s.m3_perf_stability, "
            "s.m4_drawdown, s.m5_coherence, s.m6_focus, "
            "s.kelly_fraction, s.half_kelly_position, s.kelly_win_rate, "
            "s.kelly_win_loss_ratio, s.kelly_tier, s.market_adjustment, "
            "s.final_suggestion, s.benchmark, s.data_completeness, s.update_date "
            "FROM fund_score s LEFT JOIN fund_basic b ON s.fund_code=b.fund_code "
            "WHERE s.score_date=? AND s.composite_score IS NOT NULL "
            "ORDER BY s.composite_score DESC LIMIT ?",
            (latest, top_n)
        ).fetchall()
        data = []
        for r in rows:
            d = {}
            for k in r.keys():
                v = r[k]
                d[k] = v if v != "" else None
            data.append(d)
        return {"date": latest, "count": len(data), "method": SCORE_METHOD_VERSION, "data": data}
    finally:
        conn.close()


def public_fund_score_detail(fund_code: str):
    """阶段1: 单只基金评分详情(6维度+5指标+经理6维+凯利+市场乘数完整字段)。
    返回 {fund_code, fund_name, fund_type, composite_score, star_rating, ...} 或
    {error: 'fund_score 表无此基金评分'}。
    """
    import sqlite3
    from .collector.public_fund import DB_PATH, _compute_fund_score, get_conn
    # 优先读 fund_score 表(已评分), 没有则现算
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT s.*, b.fund_name, b.fund_type FROM fund_score s "
            "LEFT JOIN fund_basic b ON s.fund_code=b.fund_code "
            "WHERE s.fund_code=? ORDER BY s.score_date DESC LIMIT 1",
            (fund_code,)
        ).fetchone()
        if row:
            d = {}
            for k in row.keys():
                v = row[k]
                d[k] = v if v != "" else None
            return d
    finally:
        conn.close()
    # 表里无, 现算一次(单只~0.1s, 不写表)
    conn = get_conn()
    try:
        score = _compute_fund_score(conn, fund_code)
        if score is None:
            return {"error": f"基金 {fund_code} 无 fund_basic 记录或数据严重不足无法评分"}
        # 补 fund_name/fund_type
        from .collector.public_fund import _safe_float
        basic = conn.execute(
            "SELECT fund_name, fund_type FROM fund_basic WHERE fund_code=?",
            (fund_code,)
        ).fetchone()
        score["fund_name"] = basic["fund_name"] if basic else None
        score["fund_type"] = basic["fund_type"] if basic else None
        return score
    finally:
        conn.close()


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
