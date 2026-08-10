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
import os
import re as _re
import time as _time

import requests

from .base import UA


# HKEX CCASS 北向持股查询页（ASP.NET WebForm）
CCASS_URL_SH = "https://www3.hkexnews.hk/sdw/search/mutualmarket.aspx?t=sh"
CCASS_URL_SZ = "https://www3.hkexnews.hk/sdw/search/mutualmarket.aspx?t=sz"

# 季度末日期（月末日）
_QUARTER_END_MONTHS = [(3, 31), (6, 30), (9, 30), (12, 31)]

# 收盘价缓存库：mootdx_daily_raw / baostock_daily_raw（本模块只读 + 写 baostock_daily_raw 写穿缓存）
_STOCK_DB_PATH = "/Users/linhuichen/code/trade-data/data/stock_daily.db"

# 写穿缓存分批大小：每取到 N 只批量 ON CONFLICT 写一次 baostock_daily_raw。
# 硬时限(alarm)中途被杀也缓存了已取部分，下槽续用（自我修复），
# 避免"全量 ~4000 只循环结束后才写 1 次、被杀 = 0 只缓存"的指标停更回归。
_WRITE_BACK_BATCH = 200

# 硬时限(重算路径 SIGALRM)时长，按槽位区分：
# - 02:00 槽：3600s（1h）。该槽强制重算，慢网络 ~35-58min 能跑完（兑现"兜底补跑"语义）
# - 16:35/21:00 槽 + update_all(17:50) 等：600s（10min）。季度闸门命中即跳过，防慢/挂卡死
_ALARM_RECOMPUTE = 3600
_ALARM_GATE = 600

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


def _write_back_baostock_prices(prices, date_ymd):
    """写穿缓存：把 baostock 取到的历史收盘价写回 stock_daily.db 的 baostock_daily_raw。

    prices: {code: close}；date_ymd: 'YYYYMMDD'（baostock_daily_raw.date 列格式）。
    只写 code/date/close 三列（open/high/low 等留 NULL，TASK-D3 全量采数会补全）。
    INSERT ... ON CONFLICT DO UPDATE 幂等：重复写同 code+date 只更新 close，
    不会重复插入也不覆盖其他已有字段。
    写失败不影响主流程（prices 已在内存，CCASS 反算继续用）。

    调用方（_fetch_close_prices_baostock）每 _WRITE_BACK_BATCH 只调一次（分批写回）：
    alarm 中途被杀也缓存了已取部分，下槽续用。
    """
    if not prices:
        return
    import sqlite3
    try:
        conn = sqlite3.connect(_STOCK_DB_PATH, timeout=10.0)
        conn.execute("PRAGMA busy_timeout=10000;")  # 与采集并发写同库自动重试
        rows = [(code, date_ymd, close)
                for code, close in prices.items() if close is not None]
        conn.executemany(
            "INSERT INTO baostock_daily_raw (code, date, close) VALUES (?,?,?) "
            "ON CONFLICT(code, date) DO UPDATE SET close=excluded.close",
            rows,
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # 写缓存失败不阻断主流程（已取到 prices）


def _fetch_close_prices_baostock(a_codes, date_str):
    """从 baostock 逐只拿指定日期的 A 股收盘价。

    a_codes: set/list of 6 位 A 股代码（如 '688001'）
    date_str: 'YYYYMMDD' 或 'YYYY-MM-DD'
    返回 {a_code: close_price}。

    季度任务，~4000 只 * 0.1s ≈ 7 分钟可接受。失败股票跳过。

    防挂保底（方案②）：baostock 走裸 socket 无超时控制，不可达时单次请求可能无限挂
    （晚间延迟放大 0.5-0.9s/只 × 4000 只 ≈ 35-58min 已接近 launchd ExitTimeOut 7200s，
    baostock 全挂时 75s+ × 4000 更会超时被 SIGTERM 丢数据）。函数开头设全局 socket
    默认超时 15s（覆盖 login + 每只 query），finally 恢复原值不影响其他模块。
    写穿缓存（方案①）：取到的历史收盘价分批写回 stock_daily.db 的 baostock_daily_raw
    对应行（date=该季末日），首轮慢、次轮 _fetch_close_prices_db 本地命中变秒级。
    分批（每 _WRITE_BACK_BATCH 只）写：硬时限被杀也缓存已取部分，下槽续用（自我修复）。
    """
    import socket
    import baostock as bs

    _prev_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(15)  # 保底：单次 socket 请求最多挂 15s
    try:
        # 登录
        try:
            lg = bs.login()
            if lg.error_code != "0":
                return {}
        except Exception:
            return {}

        # 日期格式转换
        d_iso = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}" if len(date_str) == 8 else date_str
        _db_date = d_iso.replace("-", "")

        prices = {}
        pending = {}  # 本批待写穿缓存 {code: close}
        for i, code in enumerate(a_codes, start=1):
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
                                close = float(row[1])
                                prices[code] = close
                                pending[code] = close
                                break
                            except ValueError:
                                continue
            except Exception:
                continue  # 单只失败跳过
            # 写穿缓存分批写回：每 _WRITE_BACK_BATCH 只写一次，alarm 中途被杀也缓存已取部分
            # （下槽续用，自我修复），避免"全量循环结束后才写 1 次、被杀=0 只缓存"的停更回归
            if pending and i % _WRITE_BACK_BATCH == 0:
                _write_back_baostock_prices(pending, _db_date)
                pending = {}

        # 尾部不足一批的写回
        if pending:
            _write_back_baostock_prices(pending, _db_date)

        return prices
    finally:
        try:
            bs.logout()
        except Exception:
            pass
        socket.setdefaulttimeout(_prev_timeout)  # 恢复原 socket 超时，不影响其他模块


def _fetch_close_prices_db(a_codes, date_str):
    """先从 stock_daily.db 拿收盘价（快），缺失的再用 baostock 补。

    mootdx_daily_raw / baostock_daily_raw 表，code 是 6 位 A 股代码。
    """
    import sqlite3
    prices = {}
    missing = set(a_codes)
    db_path = _STOCK_DB_PATH
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


def _hard_timeout_handler(signum, frame):  # noqa: ARG001
    """SIGALRM 硬时限处理器：超时抛 TimeoutError，调用方捕获后跳过本槽。"""
    raise TimeoutError("a_fund_north_quarterly 硬时限超时，跳过本槽")


def _current_slot():
    """返回当前槽位标识，用于区分 02:00 强制重算槽与 16:35/21:00 闸门槽。

    优先读 backfill_metrics.sh 注入的 BACKFILL_SLOT（按 launchd 当前时刻写入，精确）；
    无注入时（update_all 17:50 / 手动跑）按当前小时推断。
    返回 '0200' / '1635' / '2100' / 'other'。
    """
    slot = os.environ.get("BACKFILL_SLOT", "").strip()
    if slot:
        # 归一：02:xx 小时段（如 launchd 延迟补跑注入 0205）统一算 02:00 强制重算槽，
        # 防 mac 睡眠唤醒后延迟执行丢失 02:00 槽的每日自纠正
        if slot.startswith("02"):
            return "0200"
        return slot
    h = _dt.datetime.now().hour
    if h == 2:
        return "0200"
    if h == 16:
        return "1635"
    if h == 21:
        return "2100"
    return "other"


def _latest_quarter_value(q_curr):
    """季度闸门：查主库 daily_metric 是否已有 a_fund_north_quarterly 的最新季度行。

    有 → 返回 value（命中则跳过重算，值每季只变一次）；无/异常 → None。
    用 runner 同款 get_conn() 读主库，保证与写入端（upsert_metrics_many）同库一致。
    """
    try:
        from ..db import get_conn
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT value FROM daily_metric "
                "WHERE metric_id='a_fund_north_quarterly' AND date=?",
                [q_curr],
            ).fetchone()
        finally:
            conn.close()
        return row[0] if (row and row[0] is not None) else None
    except Exception:
        return None  # 读库失败不阻断，走正常重算


def fetch_north_fund_ccass_quarterly(n_quarters=2):
    """CCASS 季度反算北向净买额，返回 [(quarter_end_YYYYMMDD, value_亿元), ...]。

    流程：
    1. 取最近 n_quarters 个已发布的季度末
    2. 每个季度末爬 CCASS 沪+深持股（查 q+20 天确保已发布）
    3. 连续两个季度算持股差 × Q_curr 收盘价 = 净买额
    4. 收盘价先从 stock_daily.db 拿，缺失用 baostock 补（写穿缓存，首轮慢次轮秒级）

    返回 [(quarter_end, net_buy_亿元), ...]，最新在前。

    默认 n_quarters=2（只算最新季度 Q2 vs Q1），baostock 拿价 ~4000 只 * 0.1s ≈ 7 分钟。
    若需更多历史对比，调大 n_quarters（每增 1 个对比 +7 分钟）。

    季度闸门 + 按槽位硬时限（主修，2026-08-10，reviewer FAIL 整改）：
    - 16:35/21:00 槽（+ update_all 17:50）：季度闸门生效——a_fund_north_quarterly 只在
      "季度末+20 天新季度发布"时才变，DB 已有最新季度行 → 直接返回，跳过重爬 CCASS +
      baostock 逐只取价，省掉 7-35min 尾部（update_all 8/10 同指标 33min 超 1800s 告警根因）。
      重算路径硬时限 600s（10min），防 baostock 慢/挂卡死
    - 02:00 槽：强制重算（不闸门）——每日自纠正（P2：首算瞬态坏值不冻结到下季度）+ 兑现
      "兜底补跑"语义（16:35/21:00 被杀的慢网络场景在此补算）。硬时限 3600s（1h），
      慢网络 ~35-58min 能跑完；就算仍超时被杀，写穿缓存已分批（每 _WRITE_BACK_BATCH 只）
      写回部分进度，次日 02:00 续用缓存，不会指标停更
    """
    quarters = _quarter_end_dates(n=n_quarters)
    if len(quarters) < 2:
        return []  # 不足两个季度无法算差

    # 槽位判定：02:00 强制重算；其他槽（16:35/21:00/update_all 17:50）季度闸门
    slot = _current_slot()
    force_recompute = (slot == "0200")
    alarm_seconds = _ALARM_RECOMPUTE if force_recompute else _ALARM_GATE

    # 季度闸门：仅非 02:00 槽生效（默认 n_quarters=2 只产 1 行 (quarters[0], value)，
    # DB 已有则直接返回；02:00 强制重算走每日自纠正，坏值不被冻结）
    if n_quarters <= 2 and not force_recompute:
        q_gate = quarters[0].strftime("%Y%m%d")
        v_existing = _latest_quarter_value(q_gate)
        if v_existing is not None:
            return [(q_gate, v_existing)]

    # 硬时限保险：重算路径（CCASS 爬取 + baostock 逐只取价）上限
    # 02:00 强制重算槽 3600s(1h)；其他槽 600s(闸门命中即跳过，防卡死)
    import signal as _signal
    _prev_alrm = None
    _alarm_armed = False
    try:
        _prev_alrm = _signal.signal(_signal.SIGALRM, _hard_timeout_handler)
        _signal.alarm(alarm_seconds)
        _alarm_armed = True
    except Exception:
        pass  # 非主线程/信号不可用：跳过硬时限（socket 15s 超时逐只兜底）

    try:
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
    except TimeoutError:
        # 硬时限超时：跳过本槽（返回已算结果，通常为空）。
        # 16:35/21:00 槽被杀 -> 当晚 02:00 强制重算 + 3600s alarm 兜底补跑；
        # 02:00 槽被杀 -> 写穿缓存已分批（每 _WRITE_BACK_BATCH 只）写回部分进度，次日同槽续用
        print(f"[a_fund_north_quarterly] 硬时限 {alarm_seconds}s 超时，跳过本槽 "
              f"(slot={slot})，02:00 槽兜底补跑", flush=True)
        return []
    finally:
        if _alarm_armed:
            try:
                _signal.alarm(0)
                _signal.signal(_signal.SIGALRM, _prev_alrm)
            except Exception:
                pass


# ── 一次性回填 CLI（历史季度末收盘价写穿缓存，手动跑，不自动触发）──────────────
def _count_db_rows(date_ymd):
    """baostock_daily_raw 指定 date 的行数（回填进度报告用）。"""
    import sqlite3
    try:
        conn = sqlite3.connect(_STOCK_DB_PATH)
        n = conn.execute(
            "SELECT COUNT(*) FROM baostock_daily_raw WHERE date=?", [date_ymd]
        ).fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0


def backfill_quarterly_close_prices(dates):
    """一次性回填历史季度末 A 股收盘价到 stock_daily.db（baostock_daily_raw）。

    dates: ['YYYYMMDD', ...] 季度末日期（如 20260630 / 20260331 / 20251231）。

    对每个季度末：爬 CCASS 沪+深持股拿 a_code 全集 -> baostock 逐只取该日收盘价
    （复用 _fetch_close_prices_baostock，内置 socket 15s 超时保底 + 写穿缓存自动写回）。
    写回后次轮 fetch_north_fund_ccass_quarterly 的 _fetch_close_prices_db
    本地命中变秒级，晚间 a_fund_north_quarterly 从 35-58min 降到秒级。

    一次性任务（不自动触发），执行放周末安全时点（8/15 后周六周日均可）：
    当前晚间 baostock 慢正是问题场景，回填放安全时点避免晚间慢 + 撞盘中采集
    限流/盘后定时（见 CLAUDE.md §14/§18）。
    """
    results = []
    for d in dates:
        q = _dt.date(int(d[:4]), int(d[4:6]), int(d[6:8]))
        query_date = q + _dt.timedelta(days=20)
        query_str = query_date.strftime("%Y/%m/%d")
        s = requests.Session()
        sh = _fetch_ccass_holdings(s, CCASS_URL_SH, query_str)
        _time.sleep(0.5)
        sz = _fetch_ccass_holdings(s, CCASS_URL_SZ, query_str)
        codes = set(sh) | set(sz)
        n_before = _count_db_rows(d)
        prices = _fetch_close_prices_baostock(codes, d)  # 内部已写穿缓存
        n_after = _count_db_rows(d)
        results.append({
            "date": d, "codes": len(codes), "fetched": len(prices),
            "db_rows_before": n_before, "db_rows_after": n_after,
        })
        print(f"[backfill] {d}: codes={len(codes)} fetched={len(prices)} "
              f"db_rows {n_before}->{n_after}", flush=True)
    return results


if __name__ == "__main__":
    import sys
    _args = sys.argv[1:]
    if _args and _args[0] == "backfill":
        _dates = _args[1:] or [d.strftime("%Y%m%d") for d in _quarter_end_dates(n=4)]
        backfill_quarterly_close_prices(_dates)
    else:
        print(__doc__)
        print("\n用法:")
        print("  python -m app.collector.hkex_ccass_quarterly backfill [YYYYMMDD ...]")
        print("    回填历史季度末 A 股收盘价到 stock_daily.db（baostock_daily_raw），")
        print("    不传日期默认回填最近 4 个已发布季度末。手动跑，放周末安全时点。")
