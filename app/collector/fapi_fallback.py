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
MAX_PAGES = 10  # #140 安全上限(页):最多 10 页=2000 条,防服务端异常翻页死循环(触顶靠对账 TRUNCATED 告警)


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
    """东财涨停/跌停/炸板池空值时的 FAPI 兜底。返回 (df, msg);df None=兜底失败。

    #140 修复(2026-09-30):原实现固定 page=1&size=200 单页,服务端 size 上限 200
    (code=1003 拒大 size),但响应带 pagination.pages 支持翻页 —— 普涨日(涨停池
    >200 行)静默截断,20241008 只取 200/711(丢 71.9%),max_lianban 6 vs 真值 13
    连板高度直接判错。现改为:①按 pagination.pages 循环翻页取满;②末页兜底判据
    len(batch)<200(防 pages 字段缺失/不准);③安全上限 MAX_PAGES(触顶告警不
    静默截断);④返回前对账机检 len(df) vs pagination.total 不等走 msg 链路带
    TRUNCATED 字样的告警(兜底极少触发,不会刷屏)。
    """
    r = ZT_ENDPOINTS.get(func_name)
    if not r:
        return None, f"no fapi endpoint for {func_name}"
    params = {"date_ms": _date_ms(date), "page": 1, "size": 200}
    data = _api(f"/api/a-share/special-data/{r}", params)
    if data is None:
        return None, f"fapi {r} unavailable"
    items = list(data.get("item") or data.get("items") or [])
    pag = data.get("pagination") or {}
    total = int(pag.get("total") or 0)
    # total=0(如休市日/真 0 池):优雅返回空,不翻页不报错
    if total == 0:
        return pd.DataFrame(), f"fapi {r} empty(真0) date={date}"
    # 循环翻页取满:先取当前页,取完再判「是否还有下一页」。
    # 停止条件(任一满足):①服务端声明的 pages 已翻完(page>=pages)
    # ②total 已取满 ③末页兜底:batch<200(防 pages 缺失/虚高/不收敛)
    # ④安全上限 MAX_PAGES 触顶(触顶后对账 TRUNCATED 告警)。
    pages = int(pag.get("pages") or 0)  # pages 缺失=0:交给 batch<200 末页兜底
    page = 1
    while True:
        if page > 1:
            data = _api(f"/api/a-share/special-data/{r}", {**params, "page": page})
            if data is None:
                return None, f"fapi {r} page{page}/{pages} unavailable date={date}"
            batch = list(data.get("item") or data.get("items") or [])
            if not batch:
                break  # 服务端已无更多数据(early exit)
            items += batch
            if len(batch) < 200:
                break  # 末页兜底:不满 200 = 已是最后一页(防 pages 缺失/虚高/不收敛)
        if pages and page >= pages:
            break  # 服务端声明的页数已翻完(当前页正是最后一页,已取)
        if len(items) >= total:
            break  # total 已取满
        if page >= MAX_PAGES:
            break  # 安全上限触顶(对账会 TRUNCATED)
        page += 1
    df = _zt_df(items)
    msg = f"fapi {r} {len(df)} rows"
    if len(df) != total:
        # 对账机检:翻页后仍不等于 pagination.total(服务端异常/早期 break),
        # 告警而不是静默截断(走 msg 链路 -> collect_log 可查可告警)
        msg += f"; TRUNCATED total={total} got={len(df)}"
    return df, msg


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