"""按 indicators.yaml 调用 akshare 采集。分序列型/快照型/直爬/指数/板块。"""
from pathlib import Path

import akshare as ak
import pandas as pd
import yaml

from .base import safe_call
from ..calendar import last_trading_day

CONFIG_PATH = Path(__file__).absolute().parent.parent.parent / "config" / "indicators.yaml"


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


# 返回历史序列的函数（一次拉全部，逐日入库 —— 等于自动回填）
SERIES_FUNCS = {
    "stock_hsgt_hist_em",
    "index_option_300etf_qvix", "index_option_1000index_qvix", "index_option_50etf_qvix",
    "futures_main_sina", "futures_foreign_hist", "currency_boc_sina",
    "stock_margin_sse", "stock_margin_szse",
    "bond_china_yield", "bond_zh_us_rate",
    "stock_a_gxl_lg",
}
DATE_PARAM_FUNCS = {  # 传 date=
    "stock_zt_pool_em", "stock_zt_pool_dtgc_em", "stock_zt_pool_zbgc_em",
    "stock_zt_pool_previous_em",
}
DATE_RANGE_FUNCS = {  # 传 start_date= end_date=
    "stock_lhb_detail_em", "stock_lhb_jgmmtj_em",
}
# 序列函数中需要显式传 start_date/end_date 才能拿到近期数据的（值=回溯天数）
NEEDS_DATE_RANGE = {
    "currency_boc_sina": 730,
    "stock_margin_sse": 2000,
    "stock_margin_szse": 2000,
}

# 昂贵的快照函数，缓存结果供多指标复用（如 stock_zh_a_spot 要 30s）
_spot_cache = [None]


def _get_spot_df():
    if _spot_cache[0] is None:
        df = safe_call(ak.stock_zh_a_spot)
        if not isinstance(df, Exception) and df is not None:
            _spot_cache[0] = df
    return _spot_cache[0]


def _norm_date(s) -> str:
    # pandas Timestamp / datetime / date 都有 strftime，统一走它（避免 Timestamp
    # 走 str() 得到 '1996-07-08 00:00:00' 后只 replace 不去时间，污染 date 列）。
    if hasattr(s, "strftime"):
        try:
            return s.strftime("%Y%m%d")
        except (ValueError, AttributeError):
            pass
    return str(s).replace("-", "").replace("/", "")


def _date_col(df):
    for c in ("日期", "date", "trade_date", "时间", "信用交易日期", "上榜日期"):
        if c in df.columns:
            return c
    return None


def _scale(metric, v):
    if v is None:
        return None
    return v * metric.get("scale", 1.0)


def _fetch_bond_china_yield(fn, lookback_days=3650):
    """bond_china_yield 限制 start_date/end_date 间隔 < 1 年，按 350 天窗口分块拉取后拼接。"""
    import datetime as _dt
    import pandas as pd
    end = _dt.date.today()
    start = end - _dt.timedelta(days=lookback_days)
    frames = []
    cur = start
    while cur < end:
        nxt = min(cur + _dt.timedelta(days=350), end)
        df = safe_call(fn, start_date=cur.strftime("%Y%m%d"), end_date=nxt.strftime("%Y%m%d"))
        if not isinstance(df, Exception) and df is not None and len(df):
            frames.append(df)
        cur = nxt + _dt.timedelta(days=1)
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


# ================ 单值指标 ================

def collect_series(metric):
    fn = getattr(ak, metric["func"], None)
    if fn is None:
        return [], f"no attr {metric['func']}"
    params = dict(metric.get("params") or {})
    if metric["func"] in NEEDS_DATE_RANGE:
        import datetime as _dt
        today = _dt.date.today()
        lookback = NEEDS_DATE_RANGE[metric["func"]]
        params.setdefault("start_date", (today - _dt.timedelta(days=lookback)).strftime("%Y%m%d"))
        params.setdefault("end_date", today.strftime("%Y%m%d"))
    # bond_china_yield 限制 start/end 间隔 < 1 年，按 350 天窗口分块拉取后拼接
    if metric["func"] == "bond_china_yield":
        df = _fetch_bond_china_yield(fn, int(metric.get("lookback_days", 3650)))
        if df is None or len(df) == 0:
            return [], f"{metric['func']} empty"
    else:
        df = safe_call(fn, **params)
        if isinstance(df, Exception):
            return [], f"{metric['func']} error: {df}"
        if df is None or len(df) == 0:
            return [], f"{metric['func']} empty"
    # 行过滤（如 bond_china_yield 需筛「中债国债收益率曲线」）
    flt = metric.get("filter")
    if flt:
        for k, v in flt.items():
            if k in df.columns:
                df = df[df[k] == v]
        if len(df) == 0:
            return [], f"{metric['func']} empty after filter"
    dc = _date_col(df)
    col = metric.get("column")
    if not dc or not col or col not in df.columns:
        return [], f"{metric['func']} missing col (dc={dc}, col={col})"
    sc = metric.get("scale", 1.0)
    drop_zero = bool(metric.get("drop_zero"))
    rows = []
    for _, r in df.iterrows():
        try:
            v = float(r[col]) * sc
        except (TypeError, ValueError):
            continue
        if v != v:  # NaN（东财北向 2024-08 后、QVIX 早期均返回 NaN，不入库）
            continue
        if drop_zero and v == 0:  # 源占位/解析缺失返回 0.0（如 QVIX 1000 源），当缺失跳过
            continue
        rows.append((_norm_date(r[dc]), v))
    return rows, "ok"


def collect_snapshot(metric, date):
    func_name = metric.get("func")
    if not func_name or func_name == "TODO":
        return None, "disabled"
    if func_name.startswith("direct:"):
        return None, "use-collect-direct"
    # 纯当日快照（无 date 参数，如 stock_zh_a_spot）只反映「最近交易日」的数据，
    # 无法回填历史日期。若调用方传入非最近交易日的 date，源仍返回今天的数据却会被
    # 盖章成历史日期 → 用今天的盘中值覆盖正确的历史值（20260703 回归的根因）。
    # 带日期参数的快照（zt_pool 等近 2 周可回填）不在此限。
    if func_name not in DATE_PARAM_FUNCS and func_name not in DATE_RANGE_FUNCS:
        ltd = last_trading_day()
        if date != ltd:
            return None, (
                f"skip backfill: {func_name} is a today-only snapshot, "
                f"date {date} != last_trading_day {ltd}"
            )
    # 昂贵快照：走缓存
    if func_name == "stock_zh_a_spot":
        df = _get_spot_df()
        if isinstance(df, Exception) or df is None:
            return None, "stock_zh_a_spot unavailable"
    else:
        fn = getattr(ak, func_name, None)
        if fn is None:
            return None, f"no attr {func_name}"
        params = dict(metric.get("params") or {})
        if func_name in DATE_PARAM_FUNCS:
            params["date"] = date
        if func_name in DATE_RANGE_FUNCS:
            params.update(start_date=date, end_date=date)
        df = safe_call(fn, **params)
        if isinstance(df, Exception):
            return None, f"{func_name} error: {df}"
        if df is None or len(df) == 0:
            return None, f"{func_name} empty"
    val = _apply_transform(df, metric, date)
    if val is None:
        return None, f"{func_name} transform None (cols={list(df.columns)[:8]})"
    return _scale(metric, val), "ok"


def collect_direct(metric):
    """直爬函数（func 形如 direct:market_fund_flow）。返回 [(date, value), ...]。"""
    from . import direct
    name = metric["func"][len("direct:"):]
    fn = getattr(direct, f"fetch_{name}", None)
    if fn is None:
        return [], f"no direct.fetch_{name}"
    res = safe_call(fn)
    if isinstance(res, Exception):
        return [], f"direct:{name} error: {res}"
    if not res:  # 空列表/None = 两源皆败无数据
        return [], f"direct:{name} 两源皆败无数据"
    sc = metric.get("scale", 1.0)
    return [(d, v * sc) for d, v in res], "ok"


def collect_tencent(metric, date):
    """腾讯行情函数（func 形如 tencent:index_turnover）。返回 (value, msg)。"""
    from . import tencent
    name = metric["func"][len("tencent:"):]
    params = dict(metric.get("params") or {})
    fn = getattr(tencent, f"fetch_{name}", None)
    if fn is None:
        return None, f"no tencent.fetch_{name}"
    res = safe_call(fn, **params)
    if isinstance(res, Exception):
        return None, f"tencent:{name} error: {res}"
    if res is None:
        return None, f"tencent:{name} empty"
    return _scale(metric, float(res)), "ok"


def _apply_transform(df, metric, date):
    t = metric.get("transform")
    col = metric.get("column")
    try:
        if t == "count_rows":
            return float(len(df))
        if t == "count_up":
            return float((df["涨跌幅"] > 0).sum())
        if t == "count_down":
            return float((df["涨跌幅"] < 0).sum())
        if t == "extract_item":
            item = metric.get("extract")
            row = df[df["item"] == item]
            return float(row["value"].iloc[0]) if len(row) else None
        if t == "ratio_count":
            zhaban = float(len(df))
            zt = 0.0
            f2 = metric.get("func2")
            if f2:
                df2 = safe_call(getattr(ak, f2), date=date)
                if not isinstance(df2, Exception) and df2 is not None:
                    zt = float(len(df2))
            denom = zt + zhaban
            return zhaban / denom if denom > 0 else None
        if col and col in df.columns:
            s = df[col]
            if t == "sum":
                return float(s.sum())
            if t == "mean":
                return float(s.mean())
            if t == "max":
                return float(s.max())
            if t == "median":
                return float(s.median())
            return float(s.iloc[-1])
        return None
    except Exception:
        return None


# ================ 指数 ================

def _collect_ths_concept(idx, start_date, end_date):
    """Collect THS concept board index data."""
    df = safe_call(ak.stock_board_concept_index_ths, symbol=idx["symbol"], start_date=start_date, end_date=end_date)
    if isinstance(df, Exception):
        return [], f"ths_concept error: {df}"
    if df is None or len(df) == 0:
        return [], "ths_concept empty"

    rows = []
    prev = None
    for _, r in df.iterrows():
        date_str = str(r['日期'])[:10].replace('-', '')  # 2020-01-02 → 20200102
        close = float(r['收盘价']) if pd.notna(r['收盘价']) else None
        pct = None
        if prev and close:
            pct = (close / prev - 1) * 100
        rows.append((
            date_str, idx["id"],
            float(r['开盘价']) if pd.notna(r['开盘价']) else None,
            float(r['最高价']) if pd.notna(r['最高价']) else None,
            float(r['最低价']) if pd.notna(r['最低价']) else None,
            close,
            pct,
            float(r['成交额']) if pd.notna(r['成交额']) else None,
        ))
        if close:
            prev = close
    return rows, "ok"


def collect_index(idx, start_date, end_date):
    if idx["func"] == "index_hist_ths_concept":
        return _collect_ths_concept(idx, start_date, end_date)
    # 申万一级行业指数：申万官方 swsresearch.com 自 2026-07-10 起 SSL 故障，
    # 主源换同花顺聚合（industry_extras._fetch_sw_ohlc_ths，90 子行业聚合 31 一级
    # + 锚定申万末日避免绝对值跳变）。申万恢复后把 SW_OHLC_SOURCE 改回 "sw" 即回切
    # 到下方通用 ak.index_hist_sw 逻辑。
    if idx["func"] == "index_hist_sw":
        from .industry_extras import SW_OHLC_SOURCE, _fetch_sw_ohlc_ths
        if SW_OHLC_SOURCE == "ths":
            return _fetch_sw_ohlc_ths(idx["id"], start_date, end_date)
        # SW_OHLC_SOURCE == "sw": 走申万官方 ak.index_hist_sw（下方通用逻辑）
    fn = getattr(ak, idx["func"], None)
    if fn is None:
        return [], f"no attr {idx['func']}"
    params = {"symbol": idx["symbol"]}
    if idx["func"] == "index_zh_a_hist":
        params.update(period="daily", start_date=start_date, end_date=end_date)
    if idx["func"] == "stock_zh_index_hist_csindex":
        # 中证指数公司源：start_date/end_date 是服务端过滤参数（sina 不带日期返全量）。
        # 始终从 20100101 拉全量，保证首次回填与「all」范围都有历史（与 sina 返全量行为一致）。
        params.update(start_date="20100101", end_date=end_date)
    if idx["func"] == "index_hist_sw":
        # 申万一级指数源（swsresearch.com，base.py 已 patch DNS）。
        # 无 start/end 参数，返全量历史（1999 起 ~6000 行）。period=day 日频。
        params.update(period="day")
    df = safe_call(fn, **params)
    if isinstance(df, Exception):
        return [], f"{idx['func']} error: {df}"
    if df is None or len(df) == 0:
        return [], f"{idx['func']} empty"
    dc = _date_col(df)
    if dc is None:
        return [], f"{idx['func']} no date col (cols={list(df.columns)[:6]})"

    def g(r, *ns):
        for n in ns:
            if n in df.columns:
                try:
                    return float(r[n])
                except (TypeError, ValueError):
                    return None
        return None

    rows = []
    prev = None
    for _, r in df.iterrows():
        close = g(r, "收盘", "close")
        pct = g(r, "涨跌幅", "pct_change")
        if pct is None and prev and close:
            pct = (close / prev - 1) * 100
        rows.append((
            _norm_date(r[dc]), idx["id"],
            g(r, "开盘", "open"),
            g(r, "最高", "high"),
            g(r, "最低", "low"),
            close, pct,
            g(r, "成交额", "成交金额", "amount"),
        ))
        if close:
            prev = close
    return rows, "ok"


# ================ 板块 ================

def collect_board(board, date):
    fn = getattr(ak, board["func"], None)
    if fn is None:
        return [], f"no attr {board['func']}"
    df = safe_call(fn)
    if isinstance(df, Exception) or df is None or len(df) == 0:
        return [], f"{board['func']} empty/err"
    name_col = "板块名称" if "板块名称" in df.columns else df.columns[1]
    pct_col = "涨跌幅" if "涨跌幅" in df.columns else None
    flow_col = "主力净流入金额" if "主力净流入金额" in df.columns else ("净额" if "净额" in df.columns else None)
    top = board.get("top", 5)
    if pct_col:
        df = df.sort_values(pct_col, ascending=False).head(top)
    else:
        df = df.head(top)
    rows = []
    for _, r in df.iterrows():
        try:
            pct = float(r[pct_col]) if pct_col else None
        except (TypeError, ValueError):
            pct = None
        try:
            flow = float(r[flow_col]) if flow_col else None
        except (TypeError, ValueError):
            flow = None
        rows.append((date, board["type"], str(r[name_col]), pct, flow))
    return rows, "ok"


# ================ 期货持仓排名 ================

def fetch_futures_position(date: str) -> dict:
    """采集 CFFEX 期货持仓排名数据，返回三个角色各自按品种汇总的数据。

    入参 date: YYYYMMDD 格式
    返回:
        {
            'top20': {variety: {total_long, total_short, long_chg, short_chg, contract_count}},
            '中信期货': {variety: {...}},
            '国泰君安': {variety: {...}},
        }

    调用 akshare.get_cffex_rank_table(date=date, vars_list=['IF', 'IC', 'IH', 'IM'])
    返回 dict[str, DataFrame]，每个合约 21 行（前20+1行汇总rank=999）。

    - top20: 取 rank=999 的汇总行，按品种累加各合约数据
    - 中信期货: 遍历每个合约前20行，在 long_party_name 中找含"中信期货"的行
      累加 long_open_interest，在 short_party_name 中找含"中信期货"的行累加
      short_open_interest（分别判断，不同 rank 都要累加），按品种汇总
    - 国泰君安: 同理，匹配"国泰君安"
    """
    result = safe_call(ak.get_cffex_rank_table, date=date, vars_list=['IF', 'IC', 'IH', 'IM'])
    if isinstance(result, Exception):
        return {}
    if not isinstance(result, dict) or len(result) == 0:
        return {}

    # 三个角色的品种累加器: role -> variety -> {total_long, total_short, ...}
    roles_agg = {
        'top20': {},
        '中信期货': {},
        '国泰君安': {},
    }

    # 检查 party_name 列名（不同 akshare 版本可能不同）
    # 常见列名：long_party_name / short_party_name 或 long_party / short_party
    for contract, df in result.items():
        if df is None or len(df) == 0:
            continue

        # 确定列名
        long_party_col = None
        short_party_col = None
        for col in df.columns:
            if 'long_party' in col.lower() and 'name' in col.lower():
                long_party_col = col
            if 'short_party' in col.lower() and 'name' in col.lower():
                short_party_col = col
        if long_party_col is None or short_party_col is None:
            continue

        # --- top20: rank=999 汇总行 ---
        summary = df[df['rank'] == 999]
        for _, r in summary.iterrows():
            try:
                v = str(r['variety'])
                agg = roles_agg['top20']
                if v not in agg:
                    agg[v] = {'total_long': 0, 'total_short': 0, 'long_chg': 0, 'short_chg': 0, 'contract_count': 0}
                agg[v]['total_long'] += float(r['long_open_interest'])
                agg[v]['total_short'] += float(r['short_open_interest'])
                agg[v]['long_chg'] += float(r['long_open_interest_chg'])
                agg[v]['short_chg'] += float(r['short_open_interest_chg'])
                agg[v]['contract_count'] += 1
            except (TypeError, ValueError, KeyError):
                continue

        # --- 中信期货 & 国泰君安: 遍历前20行 ---
        detail = df[df['rank'] != 999]
        for _, r in detail.iterrows():
            try:
                long_name = str(r[long_party_col])
                short_name = str(r[short_party_col])
                long_oi = float(r['long_open_interest'])
                short_oi = float(r['short_open_interest'])
                long_chg = float(r['long_open_interest_chg'])
                short_chg = float(r['short_open_interest_chg'])
                variety = str(r['variety'])
            except (TypeError, ValueError, KeyError):
                continue

            # 中信期货：匹配"中信期货"但不匹配"中信建投"
            if '中信期货' in long_name and '中信建投' not in long_name:
                agg = roles_agg['中信期货']
                if variety not in agg:
                    agg[variety] = {'total_long': 0, 'total_short': 0, 'long_chg': 0, 'short_chg': 0, 'contract_count': 0}
                agg[variety]['total_long'] += long_oi
                agg[variety]['long_chg'] += long_chg
                agg[variety]['contract_count'] = max(agg[variety]['contract_count'], 1)
            if '中信期货' in short_name and '中信建投' not in short_name:
                agg = roles_agg['中信期货']
                if variety not in agg:
                    agg[variety] = {'total_long': 0, 'total_short': 0, 'long_chg': 0, 'short_chg': 0, 'contract_count': 0}
                agg[variety]['total_short'] += short_oi
                agg[variety]['short_chg'] += short_chg
                agg[variety]['contract_count'] = max(agg[variety]['contract_count'], 1)

            # 国泰君安：匹配"国泰君安"
            if '国泰君安' in long_name:
                agg = roles_agg['国泰君安']
                if variety not in agg:
                    agg[variety] = {'total_long': 0, 'total_short': 0, 'long_chg': 0, 'short_chg': 0, 'contract_count': 0}
                agg[variety]['total_long'] += long_oi
                agg[variety]['long_chg'] += long_chg
                agg[variety]['contract_count'] = max(agg[variety]['contract_count'], 1)
            if '国泰君安' in short_name:
                agg = roles_agg['国泰君安']
                if variety not in agg:
                    agg[variety] = {'total_long': 0, 'total_short': 0, 'long_chg': 0, 'short_chg': 0, 'contract_count': 0}
                agg[variety]['total_short'] += short_oi
                agg[variety]['short_chg'] += short_chg
                agg[variety]['contract_count'] = max(agg[variety]['contract_count'], 1)

    # 移除空角色
    return {role: data for role, data in roles_agg.items() if data}
