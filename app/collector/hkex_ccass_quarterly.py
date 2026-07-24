"""CCASS 季度反算北向净买额（C2 指标）。

背景：2024-08 港交所新规后，北向持股明细改季度披露，CCASS mutualmarket.aspx
只返回"上季度末"快照。无法日频反算，但可拿连续两个季度末快照反算季度净买额。

反算公式：季度净买额 = sum( (Q_curr持股 - Q_prev持股) × Q_curr收盘价 )
- 持股差 = Q_curr - Q_prev（股数，正=净买入）
- 收盘价用 Q_curr（最近季度末）A 股收盘价
- 单位：股数 × 元 = 元，/1e8 = 亿元

数据源：
- CCASS 持股：www3.hkexnews.hk/sdw/search/mutualmarket.aspx?t=sh|sz
  ASP.NET WebForm POST，返回上季度末数据（查 q+20 天确保已发布）
- 收盘价：baostock query_history_k_data_plus（逐只拿，季度任务可接受 ~7 分钟）

合理性校验：北向单季净买入历史范围约 -2000~+3000 亿（极端行情可超），异常值报错。
"""
import datetime as _dt
import json
import re as _re
import time as _time

import requests

from .base import UA


# HKEX CCASS 北向持股查询页（ASP.NET WebForm）
CCASS_URL_SH = "https://www3.hkexnews.hk/sdw/search/mutualmarket.aspx?t=sh"
CCASS_URL_SZ = "https://www3.hkexnews.hk/sdw/search/mutualmarket.aspx?t=sz"

# 季度末日期（月末日）
_QUARTER_END_MONTHS = [(3, 31), (6, 30), (9, 30), (12, 31)]

# 数据行解析正则（预编译提速）
_CCASS_ROW_RE = _re.compile(
    r'<td class="col-stock-code">\s*<div class="mobile-list-heading">Stock Code:</div>\s*'
    r'<div class="mobile-list-body">([^<]*)</div>\s*</td>\s*'
    r'<td class="col-stock-name">\s*<div class="mobile-list-heading">Name:</div>\s*'
    r'<div class="mobile-list-body">([^<]*)</div>\s*</td>\s*'
    r'<td class="col-shareholding">\s*<div class="mobile-list-heading">Shareholding in CCASS:</div>\s*'
    r'<div class="mobile-list-body">([^<]*)</div>'
)
_A_CODE_RE = _re.compile(r'A #(\d+)')


def _quarter_end_dates(n=4):
    """返回最近 n 个已发布的季度末日期（降序，最新在前）。

    发布规则：季度末后约 15 天 CCASS 才发布数据（实测 6/30 数据 7/15 发布）。
    所以"已发布"= 季度末 + 20 天 < 今天。
    """
    today = _dt.date.today()
    dates = []
    y, m = today.year, today.month
    # 从当前季度往前找
    for _ in range(n * 2 + 2):  # 多找几个确保够 n 个已发布
        # 当前季度的季度末
        if m <= 3:
            qe = _dt.date(y - 1, 12, 31)
        elif m <= 6:
            qe = _dt.date(y, 3, 31)
        elif m <= 9:
            qe = _dt.date(y, 6, 30)
        else:
            qe = _dt.date(y, 9, 30)
        # 已发布：季度末 + 20 天 < 今天
        if qe + _dt.timedelta(days=20) <= today:
            dates.append(qe)
        # 退到上一季度
        if m <= 3:
            y, m = y - 1, 12
        elif m <= 6:
            y, m = y, 3
        elif m <= 9:
            y, m = y, 6
        else:
            y, m = y, 9
        if len(dates) >= n:
            break
    return dates[:n]


def _fetch_ccass_holdings(session, url, query_date_str):
    """爬 CCASS 单市场（sh 或 sz）指定查询日期的北向持股。

    返回 {a_code: shareholding}（a_code 从 name 的 "A #XXXXXX" 提取）。
    服务器返回的是"早于查询日期的最近已发布季度末"数据。
    """
    # 1. GET 拿 fresh viewstate
    r = session.get(url, headers={"User-Agent": UA}, timeout=30)
    html = r.text
    m_vs = _re.search(r'__VIEWSTATE" id="__VIEWSTATE" value="([^"]*)"', html)
    m_vsg = _re.search(r'__VIEWSTATEGENERATOR" id="__VIEWSTATEGENERATOR" value="([^"]*)"', html)
    m_today = _re.search(r'today" id="today" value="([^"]*)"', html)
    if not (m_vs and m_vsg and m_today):
        return {}
    vs, vsg, today = m_vs.group(1), m_vsg.group(1), m_today.group(1)

    # 2. POST 查询
    data = {
        "__EVENTTARGET": "btnSearch",
        "__EVENTARGUMENT": "",
        "__VIEWSTATE": vs,
        "__VIEWSTATEGENERATOR": vsg,
        "today": today,
        "sortBy": "stockcode",
        "sortDirection": "asc",
        "originalShareholdingDate": query_date_str,
        "alertMsg": "",
        "txtShareholdingDate": query_date_str,
    }
    r = session.post(
        url,
        data=data,
        headers={
            "User-Agent": UA,
            "Referer": url,
            "Origin": "https://www3.hkexnews.hk",
        },
        timeout=30,
    )
    h = r.text

    # 3. 解析行
    holdings = {}
    for m in _CCASS_ROW_RE.finditer(h):
        name = m.group(2).strip()
        share_str = m.group(3).strip().replace(",", "")
        m_a = _A_CODE_RE.search(name)
        if not m_a:
            continue  # 无 A 股代码（如纯港股），跳过
        a_code = m_a.group(1)
        # 过滤 ETF/基金：A 股代码 159xxx（深 ETF）、51xxxx/52xxxx/56xxxx/58xxxx（沪 ETF）
        # 只保留正股：沪 60xxxx/68xxxx/90xxxx，深 00xxxx/30xxxx
        if a_code.startswith(("15", "51", "52", "56", "58")):
            continue
        try:
            shareholding = int(share_str)
            holdings[a_code] = shareholding
        except ValueError:
            continue
    return holdings


def _fetch_close_prices_baostock(a_codes, date_str):
    """从 baostock 逐只拿指定日期的 A 股收盘价。

    a_codes: set/list of 6 位 A 股代码（如 '688001'）
    date_str: 'YYYYMMDD' 或 'YYYY-MM-DD'
    返回 {a_code: close_price}。

    季度任务，~4000 只 * 0.1s ≈ 7 分钟可接受。失败股票跳过。
    """
    import baostock as bs

    # 登录
    try:
        lg = bs.login()
        if lg.error_code != "0":
            return {}
    except Exception:
        return {}

    # 日期格式转换
    d_iso = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}" if len(date_str) == 8 else date_str

    prices = {}
    for code in a_codes:
        # A 股代码转 baostock 代码（sh.6XXXXX / sz.0XXXXX / sz.3XXXXX）
        if code.startswith(("6", "9")):
            bs_code = f"sh.{code}"
        else:
            bs_code = f"sz.{code}"
        try:
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,close",
                start_date=d_iso,
                end_date=d_iso,
                frequency="d",
            )
            if rs.error_code == "0":
                while rs.next():
                    row = rs.get_row_data()
                    if row and len(row) >= 2 and row[1]:
                        try:
                            prices[code] = float(row[1])
                            break
                        except ValueError:
                            continue
        except Exception:
            continue  # 单只失败跳过
    try:
        bs.logout()
    except Exception:
        pass
    return prices


def _fetch_close_prices_db(a_codes, date_str):
    """先从 stock_daily.db 拿收盘价（快），缺失的再用 baostock 补。

    mootdx_daily_raw / baostock_daily_raw 表，code 是 6 位 A 股代码。
    """
    import sqlite3
    prices = {}
    missing = set(a_codes)
    db_path = "/Users/linhuichen/code/trade-data/data/stock_daily.db"
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        # mootdx_daily_raw 优先（数据更新）
        placeholders = ",".join("?" for _ in missing)
        cur.execute(
            f"SELECT code, close FROM mootdx_daily_raw WHERE date=? AND code IN ({placeholders})",
            [date_str] + list(missing),
        )
        for code, close in cur.fetchall():
            if close:
                prices[code] = float(close)
                missing.discard(code)
        # baostock_daily_raw 补缺失
        if missing:
            placeholders = ",".join("?" for _ in missing)
            cur.execute(
                f"SELECT code, close FROM baostock_daily_raw WHERE date=? AND code IN ({placeholders})",
                [date_str] + list(missing),
            )
            for code, close in cur.fetchall():
                if close:
                    prices[code] = float(close)
                    missing.discard(code)
        conn.close()
    except Exception:
        pass
    return prices, missing


def fetch_north_fund_ccass_quarterly(n_quarters=2):
    """CCASS 季度反算北向净买额，返回 [(quarter_end_YYYYMMDD, value_亿元), ...]。

    流程：
    1. 取最近 n_quarters 个已发布的季度末
    2. 每个季度末爬 CCASS 沪+深持股（查 q+20 天确保已发布）
    3. 连续两个季度算持股差 × Q_curr 收盘价 = 净买额
    4. 收盘价先从 stock_daily.db 拿，缺失用 baostock 补

    返回 [(quarter_end, net_buy_亿元), ...]，最新在前。

    默认 n_quarters=2（只算最新季度 Q2 vs Q1），baostock 拿价 ~4000 只 * 0.1s ≈ 7 分钟。
    若需更多历史对比，调大 n_quarters（每增 1 个对比 +7 分钟）。
    """
    quarters = _quarter_end_dates(n=n_quarters)
    if len(quarters) < 2:
        return []  # 不足两个季度无法算差

    # 1. 爬每个季度末的 CCASS 持股
    holdings = {}  # {quarter_date: {a_code: shareholding}}
    for q in quarters:
        # 查 q + 20 天（确保数据已发布）
        query_date = q + _dt.timedelta(days=20)
        query_str = query_date.strftime("%Y/%m/%d")
        s = requests.Session()
        # 沪股通
        sh = _fetch_ccass_holdings(s, CCASS_URL_SH, query_str)
        _time.sleep(0.5)  # 礼貌限速
        # 深股通
        sz = _fetch_ccass_holdings(s, CCASS_URL_SZ, query_str)
        # 合并（A 股代码不重叠：沪 6/68/9 开头，深 0/30 开头）
        merged = {**sh, **sz}
        holdings[q.strftime("%Y%m%d")] = merged

    # 2. 算连续两个季度的净买额
    rows = []
    q_keys = list(holdings.keys())  # 降序（最新在前）
    for i in range(1, len(q_keys)):
        q_curr = q_keys[i - 1]  # 最新季度（如 20260630）
        q_prev = q_keys[i]      # 上一季度（如 20260331）
        h_curr = holdings[q_curr]
        h_prev = holdings[q_prev]
        # 对齐 a_code（两期都有的股票）
        codes = set(h_curr) & set(h_prev)
        if not codes:
            continue
        # 拿 q_curr 收盘价（先 DB 后 baostock）
        prices_db, missing = _fetch_close_prices_db(codes, q_curr)
        prices = dict(prices_db)
        if missing:
            prices_bs = _fetch_close_prices_baostock(missing, q_curr)
            prices.update(prices_bs)
        # 算净买额 = sum((h_curr - h_prev) * price)
        net_buy = 0.0
        matched = 0
        for code in codes:
            diff = h_curr[code] - h_prev[code]
            if diff == 0:
                continue
            price = prices.get(code)
            if price is None:
                continue
            net_buy += diff * price
            matched += 1
        # 元 -> 亿元
        net_buy_yi = net_buy / 1e8
        # 合理性校验：北向单季净买入历史范围 -2000~+3000 亿（极端可放宽）
        # matched 覆盖率检查（< 50% 说明数据缺失严重，结果不可信）
        coverage = matched / len(codes) if codes else 0
        if coverage < 0.5:
            # 覆盖率太低，跳过（不报错，记日志）
            continue
        # 异常值检查（万亿级 = 数据错误）
        if abs(net_buy_yi) > 10000:
            continue  # 异常，跳过
        rows.append((q_curr, net_buy_yi))
    return rows
