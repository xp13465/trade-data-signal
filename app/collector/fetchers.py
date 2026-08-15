"""按 indicators.yaml 调用 akshare 采集。分序列型/快照型/直爬/指数/板块。

异源自动切换兜底(2026-08-15):主源(akshare 各接口)失败时自动切真异源备用源(不同 host/
供应商),source 标记透传到 daily_metric.source 便于溯源。fallback 抓取器实现在
multisource.py(美财政部/HKEX官方/东财 push2delay/futsseapi/上交所IV自算QVIX)。
"""
from pathlib import Path

import akshare as ak
import pandas as pd
import yaml

from .base import safe_call
from ..calendar import last_trading_day, is_trading_day
from ..db import get_conn

# 异源兜底抓取器(见 multisource.py,集中管理所有 fallback)
from . import multisource

CONFIG_PATH = Path(__file__).absolute().parent.parent.parent / "config" / "indicators.yaml"

# 异源兜底 source 标记(入库 daily_metric.source / collect_log 溯源)
# 真异源=与主源不同 host/供应商,非同一源换接口(伪多源禁止)。
SOURCE_TREASURY = "treasury"  # us10y: 美国财政部官方 CSV
SOURCE_HKEX = "hkex"          # hk_south: HKEX 官方 JS 反算南向净买额
SOURCE_EM = "em"              # cn10y/a_turnover_rate/gold/美股全球指数: 东财
SOURCE_SSE = "sse"            # qvix: 上交所官方 IV 方差互换自算(真异源,权威)
SOURCE_RV_LOCAL = "rv_local"  # qvix 网底: 本地已实现波动率(口径差异,已公示)


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


# ================ 突跳检测（spike_guard） ================
# 防源端数值层面放大（如 2026-08-04 两融余额源端放大 1000 倍，scale 挡不住）。
# 在 indicators.yaml 给指标配 spike_guard: <倍数阈值>（如 5.0），不配则不检测
# （避免误伤合理跳变如新股上市）。检测在入库前：序列型逐日比对前一日值，
# 快照型查 DB 前一交易日值。触发则拒绝入库 + runner 写 collect_log 告警。


def _spike_guard_filter_series(metric, rows):
    """序列型突跳检测：对 rows=[(date,value),...] 逐日比对前一日值。
    配 metric['spike_guard']（倍数阈值，如 5.0）；prev!=0 且 abs(v/prev)>阈值 时剔除该行。
    返回 (filtered_rows, rejected)，rejected=[(date,v,prev,ratio),...]。
    被剔除行不更新 prev（避免被放大的值连锁误剔后续正常行）。
    """
    threshold = metric.get("spike_guard")
    if not threshold:
        return rows, []
    filtered = []
    rejected = []
    prev = None
    for d, v in rows:
        if prev is not None and prev != 0 and v != 0:
            ratio = abs(v / prev)
            if ratio > threshold:
                rejected.append((d, v, prev, ratio))
                continue  # 跳过此行，不更新 prev
        filtered.append((d, v))
        prev = v
    return filtered, rejected


def _spike_guard_check_snapshot(metric, date, value):
    """快照型突跳检测：查 DB 取 date 前一交易日值比对。
    返回 (blocked, prev_value, ratio, prev_date)。
    未配 spike_guard / value 为 0 或 None / DB 无 prev 时 blocked=False。
    """
    threshold = metric.get("spike_guard")
    if not threshold or value is None or value == 0:
        return False, None, None, None
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT date, value FROM daily_metric WHERE metric_id=? "
            "AND date < ? AND value IS NOT NULL AND value != 0 "
            "ORDER BY date DESC LIMIT 1",
            (metric["id"], date),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return False, None, None, None
    prev = float(row["value"])
    if prev == 0:
        return False, prev, None, row["date"]
    ratio = abs(value / prev)
    if ratio > threshold:
        return True, prev, ratio, row["date"]
    return False, prev, ratio, row["date"]


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


# QVIX daily k.csv T+1+ 才出 T 日（滞后 2 天）。optbbs(1.optbbs.com) 主源曾宕机，
# 同源分钟 csv(vix300.csv/vix50.csv) 在同一台服务器=伪多源，一起挂(2026-08-14)。
# 真异源兜底链(优先级从高到低,均与 optbbs 不同 host):
#   档1  上交所官方 IV 方差互换自算 QVIX(option_risk_indicator_sse,T+1 权威,历史全可回填)
#        -> multisource.sse_qvix_series, source="sse"
#   档2  本地 20 日滚动年化已实现波动率 RV(_qvix_rv_series, source="rv_local",口径差异已公示)
#   (档3 新浪实时 IV 自算为下一步,已在此留钩子)
RV_ETFS = {
    "index_option_300etf_qvix": "510300",
    "index_option_50etf_qvix": "510050",  # a_qvix_1000 实际在用的 50ETF 期权口径
}


def _qvix_rv_series(func_name, window=20):
    """用对应跟踪 ETF 日线 close 算 20 日滚动年化已实现波动率(RV)，返回 [(date, rv)]。

    daily_metric 只存 value 单列，故返回 close 语义的单值(annualized 波动率%)。
    RV = 最近 window 个交易日对数收益率 std × sqrt(252) × 100。
    数据源复用 fetch_etf_ohlc(sina 主源 + mootdx fallback，本身真异源)。
    返回全序列供回填；末尾即最新交易日。
    """
    from .etf_national_team import fetch_etf_ohlc  # 延迟导入避免循环依赖
    etf_code = RV_ETFS.get(func_name)
    if not etf_code:
        return None
    recs = fetch_etf_ohlc(etf_code)
    if not recs:
        return None
    recs = sorted(recs, key=lambda x: x["date"])
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
        seg = [x for x in rets[i - window:i] if x is not None]
        if len(seg) < 5:  # 窗口内有效收益不足 5 个，极端稀疏窗口不输出
            continue
        m = sum(seg) / len(seg)
        var = sum((x - m) ** 2 for x in seg) / len(seg)
        out.append((dates[i], round(math.sqrt(var) * math.sqrt(252) * 100, 3)))
    return out or None


def _qvix_latest_trading_date():
    """判断当前应补采的 QVIX 交易日:盘后(>=15:00)且今日交易日=今日,否则前一交易日。"""
    import datetime as _dt
    try:
        now = _dt.datetime.now()
        today = now.date()
        if now.hour >= 15 and is_trading_day(today):
            return today.strftime("%Y%m%d")
        return last_trading_day(today - _dt.timedelta(days=1))
    except Exception:  # noqa: BLE001
        return None


# ================ 单值指标 ================

def collect_series(metric, _source="akshare"):
    """采集单值序列指标。返回 (rows, msg, src)。

    src=本次采集的数据来源:
      "akshare"   默认主源(auth 各 akshare 接口)
      SOURCE_TREASURY/SOURCE_HKEX/SOURCE_EM/SOURCE_SSE/SOURCE_RV_LOCAL
               主源失败时自动切真异源兜底,透传 daily_metric.source 溯源 + collect_log 记降级。
    """
    # ── 异源兜底(主源函数全缺失/空/错误时切,pre函数形态) ──
    if metric["func"] == "bond_zh_us_rate":  # us10y<->东财 bond_zh_us_rate 缺失
        # us10y:主源东财 bond_zh_us_rate(akshare)+us10y param start_date。宕机/缺失时切美财政部官方
        if metric["id"] == "us10y":
            _rows = _fallback_then_main_series(metric, ["treasury"])
            return _rows
    if metric["func"] == "stock_hsgt_hist_em":  # hk_south
        if metric["id"] == "hk_south":
            _rows = _fallback_then_main_series(metric, ["hkex"])
            return _rows
    if metric["func"] == "bond_china_yield" and metric["id"] == "cn10y":
        _rows = _fallback_then_main_series(metric, ["cn10y_em"])
        return _rows
    if metric["func"] == "futures_main_sina" and metric["params"].get("symbol") == "AU0":
        _rows = _fallback_then_main_series(metric, ["gold_em"])
        return _rows
    fn = getattr(ak, metric["func"], None)
    if fn is None:
        return [], f"no attr {metric['func']}", _source
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
            return [], f"{metric['func']} empty", _source
    else:
        df = safe_call(fn, **params)
        if isinstance(df, Exception) or df is None or len(df) == 0:
            # QVIX daily k.csv 主源(optbbs)空/错误:真异源链 sse -> RV(网底)
            if metric["func"] in RV_ETFS:
                _src, _rows, _msg = _qvix_fallback(metric)
                if _rows:
                    return _rows, _msg, _src
            if isinstance(df, Exception):
                return [], f"{metric['func']} error: {df}", _source
            return [], f"{metric['func']} empty", _source
    # 行过滤（如 bond_china_yield 需筛「中债国债收益率曲线」）
    flt = metric.get("filter")
    if flt:
        for k, v in flt.items():
            if k in df.columns:
                df = df[df[k] == v]
        if len(df) == 0:
            return [], f"{metric['func']} empty after filter", _source
    dc = _date_col(df)
    col = metric.get("column")
    if not dc or not col or col not in df.columns:
        return [], f"{metric['func']} missing col (dc={dc}, col={col})", _source
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
    # QVIX 当日补采:主源 daily k.csv(T+1+ 滞后)缺当日时,真异源链 sse -> RV(网底)补一行
    if metric["func"] in RV_ETFS:
        target = _qvix_latest_trading_date()
        if target and not any(d == target for d, _ in rows):
            _src, _rows, _msg = _qvix_fallback(metric, just_date=target)
            if _rows:
                rows = rows + _rows
                return rows, _msg, _src
    # 突跳检测:配 spike_guard 的指标(如 a_fund_margin)，值跳变超阈值(倍)则剔除该行
    # (防源端数值层面放大，如 2026-08-04 两融余额源端放大 1000 倍，scale 挡不住)
    rows, spike_rejected = _spike_guard_filter_series(metric, rows)
    if spike_rejected:
        rej_str = "; ".join(
            f"{d}:{v:.4g}(prev={p:.4g},{r:.1f}x)" for d, v, p, r in spike_rejected
        )
        return rows, f"ok (spike_guard rejected {len(spike_rejected)}): {rej_str}", _source
    return rows, "ok", _source


def _qvix_fallback(metric, just_date=None):
    """QVIX 真异源兜底链:返回 (src, rows, msg)。优先级 sse官方IV自算 > RV(网底)。

    - 主源(optbbs)整体空/错误:取一档可用源全序列回填。
    - 主源只在当日缺:just_date=当日,优先 sse 算当日;sse 失败用 RV 当日。
    """
    func = metric["func"]
    und = RV_ETFS.get(func)
    sc = metric.get("scale", 1.0)
    # 档1: 上交所官方 IV 方差互换自算 QVIX(真异源,T+1权威)
    # 仅在补当日时调用(sse IV 为 T+1 发布,取最近交易日链);全序列回填开销大,网底 RV 更轻。
    if just_date:
        try:
            res, msg = multisource.sse_qvix_series(just_date, und)
            if res:
                return SOURCE_SSE, [(res[0][0], res[0][1] * sc)], (
                    f"{func} 主源缺{just_date}, sse官方IV自算QVIX: {res[0][1]:.2f} (sse)")
        except Exception:  # noqa: BLE001
            pass
    # 网底: 本地 20 日滚动年化已实现波动率(口径差异,已公示)
    rv = _qvix_rv_series(func)
    if rv:
        if just_date:
            rv_rows = [(d, v * sc) for d, v in rv if d == just_date]
            if rv_rows:
                return SOURCE_RV_LOCAL, rv_rows, (
                    f"{func} 主源缺{just_date}, RV网底: {rv_rows[0][1]:.2f} ({SOURCE_RV_LOCAL},口径差异)")
        return SOURCE_RV_LOCAL, [(d, v * sc) for d, v in rv], (
            f"{func} 主源宕机/空, 真异源全链都空, 切本地RV({SOURCE_RV_LOCAL},口径已公示)")
    return "akshare", [], f"{func} 异源全链(sse/RV)皆败"


def _fallback_then_main_series(metric, fallback_keys):
    """主源 akshare 缺失时先试异源兜底(record),若兜底有数据则用之并标 source,否则走主源。

    fallback_keys: 见下各函数,决定调哪个 multisource 抓取器 + source 标记。
    返回 (rows, msg, src) 直接给 runner。
    """
    # 先试主源,主源正常返回 akshare 全序列
    fn = getattr(ak, metric["func"], None)
    rows_main, src_main = _series_from_main(metric, fn)
    if rows_main:
        return rows_main, "ok", src_main
    # 主源空/错误 -> 异源兜底
    for key in fallback_keys:
        _res = _run_multisource(metric, key)
        if _res is None or not _res[0]:
            continue
        rows, msg, src = _res
        return rows, msg, src
    return [], f"{metric['func']} 主源+异源兜底皆败", "akshare"


def _series_from_main(metric, fn):
    """走 akshare 主源拉序列(与 collect_series 主体同逻辑,供兜底先试主源)。"""
    if fn is None:
        return [], "akshare"
    params = dict(metric.get("params") or {})
    try:
        import datetime as _dt
        if metric["func"] in NEEDS_DATE_RANGE:
            today = _dt.date.today()
            lookback = NEEDS_DATE_RANGE[metric["func"]]
            params.setdefault("start_date", (today - _dt.timedelta(days=lookback)).strftime("%Y%m%d"))
            params.setdefault("end_date", today.strftime("%Y%m%d"))
        if metric["func"] == "bond_china_yield":
            df = _fetch_bond_china_yield(fn, int(metric.get("lookback_days", 3650)))
        else:
            df = safe_call(fn, **params)
        if isinstance(df, Exception) or df is None or len(df) == 0:
            return [], "akshare"
        flt = metric.get("filter")
        if flt:
            for k, v in flt.items():
                if k in df.columns:
                    df = df[df[k] == v]
        dc = _date_col(df)
        col = metric.get("column")
        if not dc or not col or col not in df.columns:
            return [], "akshare"
        sc = metric.get("scale", 1.0)
        drop_zero = bool(metric.get("drop_zero"))
        rows = []
        for _, r in df.iterrows():
            try:
                v = float(r[col]) * sc
            except (TypeError, ValueError):
                continue
            if v != v:
                continue
            if drop_zero and v == 0:
                continue
            rows.append((_norm_date(r[dc]), v))
        if rows:
            return rows, "akshare"
    except Exception:  # noqa: BLE001
        pass
    return [], "akshare"


def _run_multisource(metric, key):
    """调到对应异源抓取器,返回 (rows, msg, src)。key: treasury/hkex/cn10y_em/gold_em。
    us10y: 美财政部 CSV(source=treasury)
    hk_south: HKEX 官方南向净买额(source=hkex)
    cn10y: 东财 datacenter 中国10Y(source=em)
    gold: 东财 futsseapi 沪金主连(source=em)
    """
    if key == "treasury":
        rows = multisource.fetch_treasury_us10y()
        if rows:
            return rows, "us10y 主源东财宕机, 切美财政部官方CSV(treasury)", SOURCE_TREASURY
    if key == "hkex":
        rows = multisource.fetch_hkex_south_net()
        if rows:
            return rows, "hk_south 主源东财宕机, 切HKEX官方JS反算南向净买额(hkex)", SOURCE_HKEX
    if key == "cn10y_em":
        rows = multisource.fetch_em_cn10y()
        if rows:
            return rows, "cn10y 主源中债宕机, 切东财datacenter(em)", SOURCE_EM
    if key == "gold_em":
        rows = multisource.fetch_em_gold_aum()
        if rows:
            return rows, "gold 主源新浪宕机, 切东财futsseapi沪金主连(em)", SOURCE_EM
    return None
    """zt_pool 系列空时交叉验证(2026-07-31 跌停池空修复,2026-07-20 提取公共函数)。

    场景:大盘反弹日跌停池(stock_zt_pool_dtgc_em)空=真0跌停,但涨停池
    (stock_zt_pool_em)有99只 -> 源正常,本池空=真0;涨停池也空 -> 源失败保留 empty。
    供 collect_snapshot 与 intraday_snapshot._collect_intraday_width_metrics 复用。

    返回 (count, message):
      - cross_df 有数据: (0, "ok (cross-check {cross_fn.__name__} has N rows, {func_name} 空=真0)")
      - cross_df 空/失败: (None, "{func_name} empty (cross-check {cross_fn.__name__} also empty)")
    """
    cross_fn = (ak.stock_zt_pool_em
                if func_name != "stock_zt_pool_em"
                else ak.stock_zt_pool_dtgc_em)
    cross_df = safe_call(cross_fn, date=date)
    if (not isinstance(cross_df, Exception)
            and cross_df is not None
            and len(cross_df) > 0):
        return 0, (f"ok (cross-check {cross_fn.__name__} has "
                   f"{len(cross_df)} rows, {func_name} 空=真0)")
    return None, f"{func_name} empty (cross-check {cross_fn.__name__} also empty)"


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
            # zt_pool 系列空时交叉验证(2026-07-31 7/31 跌停池空修复):
            # 场景:大盘反弹日跌停池(stock_zt_pool_dtgc_em)空=真0跌停,但涨停池
            # (stock_zt_pool_em)有99只 -> 源正常,本池空=真0;涨停池也空 -> 源失败保留 empty。
            # 仅对 count_rows transform(zt_count/dt_count)写0;其他 transform(max/mean/ratio)
            # 空=无数据保留 empty(连板高度/炸板率/打板溢价空时不好判0)。
            # 2026-07-20 提取 cross_check_zt_pool 公共函数,供 intraday_snapshot 复用。
            if (func_name in DATE_PARAM_FUNCS
                    and func_name.startswith("stock_zt_pool_")
                    and metric.get("transform") == "count_rows"):
                return cross_check_zt_pool(func_name, date)
            return None, f"{func_name} empty"
    val = _apply_transform(df, metric, date)
    if val is None:
        return None, f"{func_name} transform None (cols={list(df.columns)[:8]})"
    scaled = _scale(metric, val)
    # 突跳检测:配 spike_guard 的指标(如 a_amount)，与前一交易日值比对，跳变超阈值拒绝入库
    blocked, prev, ratio, prev_date = _spike_guard_check_snapshot(metric, date, scaled)
    if blocked:
        return None, (f"spike_guard blocked: {scaled:.4g} vs prev {prev:.4g} "
                      f"({prev_date}), ratio={ratio:.1f}x > {metric['spike_guard']}")
    return scaled, "ok"


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
    """腾讯行情函数(func 形如 tencent:index_turnover)。返回 (value, msg, src)。

    a_turnover_rate 主源腾讯指数换手率(value)宕机/空时,切东财 push2delay f168(eastmoney 异源)。
    """
    from . import tencent
    name = metric["func"][len("tencent:"):]
    params = dict(metric.get("params") or {})
    fn = getattr(tencent, f"fetch_{name}", None)
    if fn is not None:
        res = safe_call(fn, **params)
        if not isinstance(res, Exception) and res is not None:
            return _scale(metric, float(res)), "ok", "akshare"
        main_err = f"tencent:{name} error: {res}" if isinstance(res, Exception) else f"tencent:{name} empty"
    else:
        main_err = f"no tencent.fetch_{name}"
    # 主源失败 -> 东财 push2delay 异源兜底(仅 a_turnover_rate,上证指数换手率)
    if metric.get("id") == "a_turnover_rate":
        try:
            em_rows = multisource.fetch_em_index_turnover(secid=metric.get("params", {}).get("secid", "1.000001"))
            if em_rows:
                val = float(em_rows[0][1])
                return _scale(metric, val), (
                    f"a_turnover_rate 主源腾讯宕机, 切东财push2delay(em): {main_err}"), SOURCE_EM
        except Exception:  # noqa: BLE001
            pass
    return None, main_err, "akshare"


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
    # 申万一级行业指数：2026-07-10 起申万官方 swsresearch.com SSL 故障曾换同花顺聚合
    # （industry_extras._fetch_sw_ohlc_ths）。2026-08-14 实测申万源已恢复，SW_OHLC_SOURCE
    # 已回切 "sw"，走下方通用 ak.index_hist_sw 全量真实历史。回切原因 + 切换常量见
    # industry_extras.SW_OHLC_SOURCE 注释。
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
    if isinstance(df, Exception) or (df is not None and len(df) == 0) or df is None:
        main_err = (f"{idx['func']} error: {df}" if isinstance(df, Exception)
                    else f"{idx['func']} empty")
        # 美股/全球指数 主源(新浪)失败 -> 东财 push2delay 异源兜底(当日快照,真异源)
        if idx["id"] in multisource.EM_INDEX_MAP:
            secid, scale = multisource.EM_INDEX_MAP[idx["id"]]
            snap = multisource.fetch_em_index_snapshot(secid, scale, date_str=end_date)
            if snap:
                d, close = snap[0]
                return [(d, idx["id"], close, close, close, close, None, None)], (
                    f"{idx['func']} 主源新浪宕机, 切东财push2delay(em)当日快照: ({main_err})")
        if isinstance(df, Exception):
            return [], main_err
        return [], main_err
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
        close = g(r, "收盘", "收盘价", "close")  # +收盘价(国债期货 futures_main_sina 返中文带"价"后缀)
        pct = g(r, "涨跌幅", "pct_change")
        if pct is None and prev and close:
            pct = (close / prev - 1) * 100
        rows.append((
            _norm_date(r[dc]), idx["id"],
            g(r, "开盘", "开盘价", "open"),
            g(r, "最高", "最高价", "high"),
            g(r, "最低", "最低价", "low"),
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
