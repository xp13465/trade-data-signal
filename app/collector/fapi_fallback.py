"""FAPI 涨停池/龙虎榜兜底抓取器(2026-09-02 实施,P1 兜底源)。

调研:docs/fapi/fapi-integration-plan-20260901.md §3(涨停池+龙虎榜备用源)。
定位:东财主源(stock_zt_pool_em 系 / stock_lhb_detail_em 系)失败或空时,
collect_snapshot 空值分支调用本模块做真异源兜底(同花顺官方 API),返回
**东财兼容 DataFrame**(列名对齐 _apply_transform 需要的 `连板数`/`涨跌幅` 等),
从而复用现有 transform 链(spike_guard/scale/入库),不新增判定分支。

安全:key 只从 .env 读(HITHINK_FINANCE_API_KEY,与 fapi_daily.py 同源);
失败一律返回 (None, msg) 不抛异常,主源失败时兜底失败=静默保留 empty(不阻断)。

端点(FAPI 契约 http://fuyao.aicubes.cn):
  limit-up-pool   ?date_ms=<ms>&page=1&size=200 -> data.pagination.total + data.item[]
  limit-down-pool 同结构
  limit-break-pool 同结构
  dragon-tiger-list ?board_type=all&date=YYYY-MM-DD -> data.count + data.stock_items[]
实测(20260901):涨停 80 vs 东财 83、跌停 0 vs 0、炸板 6 vs 6;龙虎榜 count=68 vs 东财 79。
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import requests

from .fapi_daily import BASE, load_key

# FAPI 端点 PATH -> 东财 func(用于空值分支精准匹配)
ZT_ENDPOINTS = {
    "stock_zt_pool_em": "limit-up-pool",
    "stock_zt_pool_dtgc_em": "limit-down-pool",
    "stock_zt_pool_zbgc_em": "limit-break-pool",
}
LHB_ENDPOINTS = {
    "stock_lhb_detail_em": "dragon-tiger-list",
    "stock_lhb_jgmmtj_em": "dragon-tiger-list",
}
TIMEOUT = 20.0  # 兜底请求超时(与东财 _em 20s 同档,防拖慢主链)


def _date_ms(yyyymmdd: str) -> int:
    d = dt.datetime.strptime(yyyymmdd, "%Y%m%d").replace(
        tzinfo=dt.timezone(dt.timedelta(hours=8)))
    return int(d.timestamp() * 1000)


def _api(path: str, params: dict):
    """GET FAPI 端点,返回 data dict;失败/异常返回 None。"""
    try:
        r = requests.get(f"{BASE}{path}", headers={"X-api-key": load_key()},
                         params=params, timeout=TIMEOUT)
        r.raise_for_status()
        j = r.json()
        if j.get("code") != 0:
            return None
        return j.get("data") or {}
    except Exception:  # noqa: BLE001 兜底失败不阻断主链路
        return None


def _zt_df(pool_items: list, lianban_col: str = "连板数") -> pd.DataFrame:
    """涨停池 item -> 东财兼容 df。count_rows 用行数;max 取 lianban_col。
    FAPI continue_day_cnt(整型连板数) -> 东财「连板数」列语义对齐。"""
    rows = []
    for it in pool_items:
        row = {
            "代码": it.get("ticker", ""),
            "名称": it.get("name", ""),
            "最新价": it.get("last_price"),
            "涨跌幅": it.get("price_change_ratio_pct"),
            lianban_col: it.get("continue_day_cnt"),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def _lhb_df(stock_items: list, with_inst: bool) -> pd.DataFrame | None:
    """龙虎榜 stock_items -> 东财兼容 df。
    count_rows:每天 stock_count 去重股数(东财 lhb_count 按记录数,口径差已实测)
    sum(机构买入净额):用 org_net_value。无机构字段且 with_inst -> None(不硬编)。"""
    if not stock_items:
        return None
    rows = []
    for it in stock_items:
        row = {"代码": it.get("ticker", "")}
        if with_inst:
            row["机构买入净额"] = it.get("org_net_value")
        rows.append(row)
    return pd.DataFrame(rows)


def fetch_zt_fallback(func_name: str, date: str) -> tuple[pd.DataFrame | None, str]:
    """东财涨停/跌停/炸板池空值时的 FAPI 兜底。返回 (df, msg);df None=兜底失败。"""
    r = ZT_ENDPOINTS.get(func_name)
    if not r:
        return None, f"no fapi endpoint for {func_name}"
    data = _api(f"/api/a-share/special-data/{r}",
                {"date_ms": _date_ms(date), "page": 1, "size": 200})
    if data is None:
        return None, f"fapi {r} unavailable"
    items = data.get("item") or data.get("items") or []
    if not items:
        # 池子真 0(如跌停 0):返回空 df(count_rows=0),与东财空=真0 语义一致
        return pd.DataFrame(), f"fapi {r} empty(真0) date={date}"
    df = _zt_df(items)
    return df, f"fapi {r} {len(items)} rows"


def fetch_lhb_fallback(func_name: str, date: str) -> tuple[pd.DataFrame | None, str]:
    """东财龙虎榜空值时的 FAPI 兜底。date 需转 YYYY-MM-DD 契约格式。"""
    if func_name not in LHB_ENDPOINTS:
        return None, f"no fapi endpoint for {func_name}"
    d = _date_ms(date)
    # dragon-tiger-list 契约用 date=YYYY-MM-DD
    day = dt.datetime.fromtimestamp(d / 1000, tz=dt.timezone(dt.timedelta(hours=8)))
    data = _api("/api/a-share/special-data/dragon-tiger-list",
                {"board_type": "all", "date": day.strftime("%Y-%m-%d")})
    if data is None:
        return None, "fapi dragon-tiger-list unavailable"
    stock_items = data.get("stock_items") or []
    if not stock_items:
        return pd.DataFrame(), f"fapi dragon-tiger-list empty date={date}"
    with_inst = func_name == "stock_lhb_jgmmtj_em"
    df = _lhb_df(stock_items, with_inst)
    if with_inst and df is not None and "机构买入净额" not in df.columns:
        return None, "fapi lhb missing org_net_value"
    return df, f"fapi dragon-tiger-list {len(stock_items)} items"


def try_fallback(func_name: str, date: str) -> tuple[pd.DataFrame | None, str]:
    """统一入口:collect_snapshot 空值分支调用。返回 (df, msg)。"""
    if func_name in ZT_ENDPOINTS:
        return fetch_zt_fallback(func_name, date)
    if func_name in LHB_ENDPOINTS:
        return fetch_lhb_fallback(func_name, date)
    return None, f"no fapi fallback for {func_name}"