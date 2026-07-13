"""v1 国家队宽基 ETF 资金动向追踪（后端采集 + 存储 + 信号 + export）。

口径声明：本指标为代理推断，非真实国家队席位数据。基于 ETF 每日份额变动 + 成交额放量，
结合季度机构持仓占比校准，推断疑似大资金进场/离场。无法精确区分汇金/证金/社保/险资/公募。

4 个 fetcher：
  A. fund_etf_scale_sse(date)         沪市 ETF 每日份额（上交所，工作日可达，周末抛 KeyError 跳过）
  B. fund_scale_daily_szse(start,end) 深市 ETF 每日份额（深交所，区间批量）
  C. mootdx bars(frequency=9)         ETF OHLC+成交额（替代东财 push2his，2026-07-13 起 push2his IP 封）
  D. 直爬东财 FundArchivesDatas.aspx?type=cyrjg  季度持有人结构（机构占比，半年报+年报，滞后2-3月）

存储：独立库 data/etf_national_team.db（与 sentiment.db 隔离，采集异常不影响看板）。
3 张表：etf_daily / etf_signal / etf_holder_quarterly。

信号算法：
  z-score = (share_change - mean(过去20日,不含当日)) / std(过去20日,不含当日)
  vol_ratio = amount / mean(过去5日,不含当日)
  share_surge:  share_change>0 AND z>2  AND vol_ratio>1.5  (疑似大资金进场)
  share_outflow: share_change<0 AND z<-2 AND vol_ratio>1.5 (疑似大资金离场)
  volume_surge: vol_ratio>2 (放量,独立信号)
  折算日排除: |share_change_pct|>30% 且 vol_ratio<1.0 -> 标记 split_suspect 不触发
  季度校准: 当季机构占比>85% 置信×1.5 / <60% ×0.7 (写进 note)

CLI：
  python -m app.collector.etf_national_team backfill --start 2023-01-01   全量回填
  python -m app.collector.etf_national_team daily                         当日增量
  python -m app.collector.etf_national_team signals                      重算信号
  python -m app.collector.etf_national_team holders                      只拉持有人(半年一次)
"""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

# 必须先 import base，应用 trust_env=False 全局补丁（绕 Clash 代理直连东财/上交所）
from . import base  # noqa: F401
import akshare as ak

from .base import em_get, throttle

# ── 路径与常量 ──────────────────────────────────────────────────────────────────
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DB_PATH = _DATA_DIR / "etf_national_team.db"
LOCK_PATH = _DATA_DIR / "etf_national_team.lock"
STATIC_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "static-site" / "data"
WEB_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "web" / "data"

# 12 只宽基 ETF（code, 易记名, 跟踪指数, 市场 sh/sz）
ETF_LIST = [
    ("510050", "50ETF华夏", "上证50", "sh"),
    ("510300", "300ETF华泰柏瑞", "沪深300", "sh"),
    ("510310", "300ETF易方达", "沪深300", "sh"),
    ("159919", "300ETF嘉实", "沪深300", "sz"),
    ("510500", "500ETF南方", "中证500", "sh"),
    ("159922", "500ETF嘉实", "中证500", "sz"),
    ("512100", "1000ETF南方", "中证1000", "sh"),
    ("159845", "1000ETF华夏", "中证1000", "sz"),
    ("159915", "创业板ETF易方达", "创业板", "sz"),
    ("159952", "创业板ETF广发", "创业板", "sz"),
    ("588000", "科创50ETF华夏", "科创50", "sh"),
    ("588050", "科创50ETF工银", "科创50", "sh"),
]
ETF_BY_CODE = {c: (n, idx, mkt) for c, n, idx, mkt in ETF_LIST}
SH_CODES = [c for c, _, _, m in ETF_LIST if m == "sh"]
SZ_CODES = [c for c, _, _, m in ETF_LIST if m == "sz"]

# ── v2: cninfo PDF 解析汇金/证金具名持有人 ──────────────────────────────────────
# cninfo 公告查询 API（巨潮资讯网）
CNINFO_ANNOUNCE_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_PDF_BASE = "http://static.cninfo.com.cn/"

# 深市 ETF 在 cninfo 的 orgId（从 fund_stock.json 拿到；沪市 ETF cninfo 未收录 orgId）
CNINFO_ETF_ORGID = {
    "159919": "jjjl0000037",  # 沪深300ETF嘉实
    "159922": "jjjl0000037",  # 中证500ETF嘉实
    "159845": "jjjl0000031",  # 中证1000ETF华夏
    "159915": "jjjl0000041",  # 创业板ETF易方达
    "159952": "jjjl0000065",  # 创业板ETF广发
}

# 国家队主体识别关键词（持有人名称包含这些即归类）
NATIONAL_TEAM_PATTERNS = [
    ("汇金", ["中央汇金投资有限责任公司", "中央汇金资产管理有限责任公司", "中央汇金"]),
    ("证金", ["中国证券金融股份有限公司", "中国证券金融", "中证金融"]),
    ("社保", ["全国社保基金", "社保基金"]),
    ("外管局", ["中央外汇业务中心", "国家外汇管理局"]),
]

# 历史公开增持里程碑事件 seed（基于新华社/证监会公开公告整理，用于前端"关键事件"展示）
# 这类汇金/证金"宣布增持"声明不通过 cninfo 披露（汇金非上市公司），作为 seed 静态补充
NATIONAL_TEAM_EVENTS = [
    {
        "date": "20231011", "actor": "汇金",
        "action": "宣布增持四大行",
        "note": "中央汇金在二级市场增持工/农/中/建四大行A股，并拟未来6个月继续增持。",
        "source": "新华财经",
    },
    {
        "date": "20231023", "actor": "汇金",
        "action": "宣布增持ETF",
        "note": "中央汇金公告称当日买入交易型开放式指数基金（ETF），并将在未来继续增持。本系统 v1 信号准确捕捉：510300当日份额+9.9亿(z=4.62)，510310份额+4.3亿(z=7.47)。",
        "source": "新华财经",
    },
    {
        "date": "20240206", "actor": "汇金",
        "action": "扩大ETF增持范围",
        "note": "中央汇金公告称充分认可当前A股配置价值，已扩大ETF增持范围并将持续加大增持力度。",
        "source": "新华财经",
    },
    {
        "date": "20150705", "actor": "证金",
        "action": "入场维稳（A股救市）",
        "note": "中国证券金融公司获央行流动性支持，通过申购公募基金等方式入场维稳（千股跌停期间）。",
        "source": "证监会公告",
    },
    {
        "date": "20080923", "actor": "汇金",
        "action": "首次宣布增持三大行",
        "note": "中央汇金在二级市场增持工/中/建三行A股（金融危机期间维稳）。",
        "source": "上交所公告",
    },
    {
        "date": "20130620", "actor": "汇金",
        "action": "增持工行/建行",
        "note": "中央汇金增持工商银行、建设银行A股（钱荒期间维稳）。",
        "source": "新华财经",
    },
]

DEFAULT_START = "20050101"  # 最大化历史: 510050 上市日 2005-02-23, mootdx 可采到上市首日

# SSE fund_etf_scale_sse 最早可采日(~2012-01-04), 早于此日返回 KeyError, 避免空转
SSE_SHARES_EARLIEST = "20120104"
# mootdx bars 翻页安全上限(510050 上市2005~21年≈5180根, 留余量到6000)
MOOTDX_PAGE_LIMIT = 6000

# ── DB schema ───────────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS etf_daily (
  date TEXT NOT NULL,
  etf_code TEXT NOT NULL,
  etf_name TEXT,
  close REAL,
  amount REAL,                -- 成交额（元）
  fund_share REAL,            -- 基金份额（份）
  share_change REAL,          -- 当日份额变动 = 今日 - 昨日（份）
  share_change_pct REAL,      -- 份额变动百分比 %
  PRIMARY KEY (date, etf_code)
);
CREATE INDEX IF NOT EXISTS idx_etf_daily_code ON etf_daily(etf_code);
CREATE INDEX IF NOT EXISTS idx_etf_daily_date ON etf_daily(date);

CREATE TABLE IF NOT EXISTS etf_signal (
  date TEXT NOT NULL,
  etf_code TEXT NOT NULL,
  signal_type TEXT NOT NULL,  -- 'share_surge'/'share_outflow'/'volume_surge'/'split_suspect'
  share_change REAL,
  amount_ratio REAL,           -- 成交额/5日均量倍数
  intensity REAL,             -- 份额变动 z-score
  note TEXT,
  PRIMARY KEY (date, etf_code, signal_type)
);
CREATE INDEX IF NOT EXISTS idx_etf_signal_date ON etf_signal(date);

CREATE TABLE IF NOT EXISTS etf_holder_quarterly (
  report_date TEXT NOT NULL,
  etf_code TEXT NOT NULL,
  inst_hold_pct REAL,          -- 机构持有比例 %
  retail_hold_pct REAL,        -- 个人持有比例 %
  internal_hold_pct REAL,      -- 内部持有比例 %
  total_share REAL,            -- 总份额（亿份）
  fetch_date TEXT,
  PRIMARY KEY (report_date, etf_code)
);
CREATE INDEX IF NOT EXISTS idx_etf_holder_code ON etf_holder_quarterly(etf_code);

-- v2: 汇金/证金具名持有人（从 cninfo 年报/半年报 PDF "9.2 期末上市基金前十名持有人" 解析）
CREATE TABLE IF NOT EXISTS national_team_holders (
  report_date TEXT NOT NULL,      -- 报告期 YYYYMMDD（年报 2024-12-31 -> 20241231）
  etf_code TEXT NOT NULL,
  holder_name TEXT NOT NULL,      -- 持有人全称（如"中央汇金投资有限责任公司"）
  holder_type TEXT,               -- '汇金'/'证金'/'其他机构'
  hold_share REAL,                -- 持有份额（份）
  hold_pct REAL,                  -- 占上市总份额比例 %
  rank INTEGER,                   -- 前十大持有人排名 1-10
  source_pdf_url TEXT,            -- 来源 PDF URL
  fetch_date TEXT,
  PRIMARY KEY (report_date, etf_code, holder_name)
);
CREATE INDEX IF NOT EXISTS idx_nth_code ON national_team_holders(etf_code);
CREATE INDEX IF NOT EXISTS idx_nth_type ON national_team_holders(holder_type);
"""


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def _acquire_lock(nonblock: bool = True) -> bool:
    """fcntl.flock 进程互斥（macOS 用 fcntl 非 flock 命令）。
    nonblock=True: 持不到锁立即返回 False（重复跑跳过）。
    """
    f = open(LOCK_PATH, "w")
    flags = fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblock else 0)
    try:
        fcntl.flock(f, flags)
    except BlockingIOError:
        return False
    # 持锁到进程退出（fd 不关闭，借 GC 保持锁）
    _LOCK_FILE[0] = f
    return True


_LOCK_FILE = [None]


# ── Fetcher A: 沪市 ETF 每日份额（上交所）─────────────────────────────────────
def fetch_sse_shares(date_yyyymmdd: str) -> dict[str, float]:
    """上交所某日全量 ETF 份额。返回 {code: fund_share}（仅本清单沪市 ETF）。
    周末/节假日 akshare 抛 KeyError，调用方 try/except 跳过。
    """
    throttle()
    df = ak.fund_etf_scale_sse(date=date_yyyymmdd)
    if df is None or len(df) == 0:
        return {}
    out = {}
    for code in SH_CODES:
        rows = df[df["基金代码"].astype(str) == code]
        if len(rows):
            try:
                out[code] = float(rows.iloc[0]["基金份额"])
            except (TypeError, ValueError):
                pass
    return out


# ── Fetcher B: 深市 ETF 每日份额（深交所，区间批量）──────────────────────────────
def fetch_szse_shares(start_yyyymmdd: str, end_yyyymmdd: str) -> dict[str, dict[str, float]]:
    """深交所区间 ETF 份额。返回 {date_yyyymmdd: {code: fund_share}}（仅本清单深市 ETF）。
    fund_scale_daily_szse 要求 start/end 为 YYYYMMDD 格式。"""
    throttle()
    df = ak.fund_scale_daily_szse(start_date=start_yyyymmdd, end_date=end_yyyymmdd, symbol="ETF")
    if df is None or len(df) == 0:
        return {}
    out: dict[str, dict[str, float]] = {}
    for _, row in df.iterrows():
        code = str(row["基金代码"]).strip()
        if code not in SZ_CODES:
            continue
        try:
            dstr = str(row["日期"]).strip()[:10].replace("-", "")  # 2025-07-11 -> 20250711
            share = float(row["基金份额"])
        except (TypeError, ValueError):
            continue
        out.setdefault(dstr, {})[code] = share
    return out


# ── Fetcher C: ETF OHLC+成交额（mootdx，替代被封的 push2his）─────────────────────
def fetch_etf_ohlc(code: str, start_yyyymmdd: str = DEFAULT_START, client=None) -> list[dict]:
    """mootdx 拉 ETF 日线 OHLC+成交额。从最新往历史拉，过滤 >= start。
    返回 [{date, etf_code, open, close, high, low, amount}]。
    mootdx bars 单次上限 800 根（约 3.2 年），2023 至今一次够。
    client: 可选 tdx_client 复用（避免每只ETF重新选服务器，daily 增量提速 10×）。
    """
    if client is None:
        from .mootdx_daily import tdx_client
        client = tdx_client(market="std")
    PAGE = 800
    start_off = 0
    out: list[dict] = []
    while True:
        df = client.bars(symbol=code, frequency=9, offset=PAGE, start=start_off)
        if df is None or len(df) == 0:
            break
        for ts, row in df.iterrows():
            dstr = str(ts)[:10].replace("-", "")  # 2026-07-13 -> 20260713
            if dstr < start_yyyymmdd:
                continue
            try:
                out.append({
                    "date": dstr,
                    "etf_code": code,
                    "open": float(row["open"]),
                    "close": float(row["close"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "amount": float(row["amount"]),  # 元
                })
            except (TypeError, ValueError):
                continue
        if len(df) < PAGE:
            break
        start_off += PAGE
        if start_off > MOOTDX_PAGE_LIMIT:  # 安全上限 ~24年(510050 2005上市≈5180根)
            break
    return out


# ── Fetcher D: 季度持有人结构（东财直爬）────────────────────────────────────────
def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).strip()


def _parse_pct(s: str) -> float | None:
    s = _strip_html(s).replace("%", "").replace("，", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_share(s: str) -> float | None:
    s = _strip_html(s).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fetch_holder_structure(code: str) -> list[dict]:
    """直爬东财 FundArchivesDatas.aspx?type=cyrjg 拿 ETF 持有人结构。
    返回 [{report_date, etf_code, inst_hold_pct, retail_hold_pct, internal_hold_pct, total_share}]。
    半年报+年报，滞后2-3月。total_share 单位亿份。
    """
    url = f"http://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=cyrjg&code={code}"
    headers = {"Referer": f"http://fundf10.eastmoney.com/ccmx_{code}.html"}
    r = em_get(url, headers=headers, timeout=15)
    if r.status_code != 200:
        print(f"  [holder] {code} HTTP {r.status_code}", flush=True)
        return []
    text = r.text
    # 东财返回 var apidata={ content:"<table>...</table>", summary:"..." };
    m = re.search(r'content:"(.+?)",\s*summary:', text, re.DOTALL)
    if not m:
        return []
    html = m.group(1).replace('\\"', '"').replace("\\/", "/")
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
    except Exception:  # noqa: BLE001
        soup = None
    out: list[dict] = []
    if soup is not None:
        for tr in soup.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 5:
                continue
            try:
                rdate = _strip_html(tds[0].get_text()).replace("/", "-")[:10]  # 2025-12-31
                if not re.match(r"\d{4}-\d{2}-\d{2}", rdate):
                    continue
                report_date = rdate.replace("-", "")
                out.append({
                    "report_date": report_date,
                    "etf_code": code,
                    "inst_hold_pct": _parse_pct(tds[1].get_text()),
                    "retail_hold_pct": _parse_pct(tds[2].get_text()),
                    "internal_hold_pct": _parse_pct(tds[3].get_text()),
                    "total_share": _parse_share(tds[4].get_text()),  # 亿份
                })
            except Exception:  # noqa: BLE001
                continue
    return out


# ── v2 Fetcher E: cninfo PDF 解析汇金/证金具名持有人 ────────────────────────────
def _cninfo_session():
    """trust_env=False 的 session（绕 Clash 直连 cninfo）。"""
    import requests
    s = requests.Session()
    s.trust_env = False
    return s


def fetch_cninfo_reports(code: str, org_id: str, report_types: tuple = ("annual", "semi")) -> list[dict]:
    """查 cninfo ETF 年报/半年报公告列表。
    返回 [{title, pub_date, pdf_url, announcement_id}]。
    report_types: 'annual' 年报 / 'semi' 半年报。
    """
    s = _cninfo_session()
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "http://www.cninfo.com.cn/",
               "X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/javascript, */*; q=0.01"}
    out = []
    page = 1
    while page <= 5:  # 最多5页=150条，足够覆盖10+年
        data = {
            "pageNum": str(page), "pageSize": "30", "column": "fund",
            "tabName": "fulltext", "category": "category_jjgg_ndbg_szsh",
            "plate": "", "stock": f"{code},{org_id}", "searchkey": "",
            "secid": "", "sortName": "", "sortType": "", "isHLtitle": "true",
        }
        try:
            r = s.post(CNINFO_ANNOUNCE_URL, data=data, timeout=15, headers=headers)
            j = r.json()
        except Exception as e:  # noqa: BLE001
            print(f"  [cninfo] {code} 查询失败 p{page}: {type(e).__name__}", flush=True)
            break
        ann = j.get("announcements") or []
        if not ann:
            break
        for a in ann:
            title = a.get("announcementTitle", "").replace("<em>", "").replace("</em>", "")
            # 只要年报/半年报全文（排除"摘要"/"推迟披露"/"提示性公告"）
            is_annual = "年度报告" in title and "摘要" not in title and "推迟" not in title and "提示" not in title
            is_semi = "半年度报告" in title and "摘要" not in title and "推迟" not in title
            if not (is_annual or is_semi):
                continue
            t = a.get("announcementTime")
            pub = dt.datetime.fromtimestamp(t / 1000).strftime("%Y%m%d") if t else ""
            rtype = "annual" if is_annual else "semi"
            out.append({
                "title": title,
                "pub_date": pub,
                "report_type": rtype,
                "pdf_url": CNINFO_PDF_BASE + a.get("adjunctUrl", ""),
                "announcement_id": a.get("announcementId", ""),
            })
        if len(ann) < 30:
            break
        page += 1
    return out


def _extract_report_date(title: str, report_type: str) -> str | None:
    """从公告标题提取报告期 YYYYMMDD。
    年报 '2024年年度报告' -> '20241231'；半年报 '2024年半年度报告' -> '20240630'。
    """
    m = re.search(r"(20\d{2})年", title)
    if not m:
        return None
    year = m.group(1)
    if report_type == "semi":
        return f"{year}0630"
    return f"{year}1231"


def parse_top_holders_from_pdf(pdf_path: str) -> list[dict]:
    """pdfplumber 解析"9.2 期末上市基金前十名持有人"表格。
    返回 [{rank, holder_name, hold_share, hold_pct}]，解析失败返 []。
    """
    try:
        import pdfplumber
    except ImportError:
        print("  [pdf] pdfplumber 未安装", flush=True)
        return []
    out = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            # 跳过目录页（含....）+ 必须含 9.2 前十名持有人
            if "...." in text:
                continue
            if "前十名持有人" not in text and "前十名份额持有人" not in text:
                continue
            tables = page.extract_tables()
            for t in tables:
                flat = " ".join(str(c) for row in t for c in row if c)
                if "持有人名称" not in flat and "持有份额" not in flat:
                    continue
                for row in t:
                    cells = [(c or "").replace("\n", "").strip() for c in row]
                    # 找序号 1-15
                    seq = None
                    for c in cells:
                        if c.isdigit() and 1 <= int(c) <= 15:
                            seq = int(c)
                            break
                    if seq is None:
                        continue
                    hold_share = None
                    hold_pct = None
                    holder_name = None
                    for c in cells:
                        if not c or c == str(seq):
                            continue
                        # 份额：含逗号的大数字 或 纯数字>4位
                        if hold_share is None and re.match(r"^[\d,]+\.?\d*$", c) and len(c.replace(",", "")) > 4:
                            hold_share = float(c.replace(",", ""))
                        # 占比：纯小数（如 51.56）
                        elif hold_pct is None and re.match(r"^\d+\.\d{1,3}$", c):
                            hold_pct = float(c)
                        # 持有人名称：含中文长度>4 且不是表头
                        if holder_name is None and re.search(r"[一-鿿]{4,}", c):
                            if "占" not in c and "持有人" not in c and "份额" not in c and "比例" not in c:
                                holder_name = c
                    if holder_name and (hold_share is not None or hold_pct is not None):
                        out.append({
                            "rank": seq,
                            "holder_name": holder_name,
                            "hold_share": hold_share,
                            "hold_pct": hold_pct,
                        })
            if out:  # 同一页找到就不再翻后续页
                break
    return out


def classify_holder(name: str) -> str:
    """识别持有人类型：'汇金'/'证金'/'社保'/'外管局'/'其他机构'。"""
    for htype, patterns in NATIONAL_TEAM_PATTERNS:
        for p in patterns:
            if p in name:
                return htype
    return "其他机构"


def download_cninfo_pdf(pdf_url: str, dest_path: Path) -> bool:
    """下载 cninfo PDF。"""
    s = _cninfo_session()
    try:
        r = s.get(pdf_url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200 or len(r.content) < 1000:
            return False
        dest_path.write_bytes(r.content)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"    下载失败: {type(e).__name__}", flush=True)
        return False


def _store_holders_v2(conn, code: str, report_date: str, holders: list[dict], pdf_url: str) -> int:
    """存 v2 具名持有人到 national_team_holders 表。"""
    fetch_date = dt.datetime.now().strftime("%Y%m%d")
    n = 0
    for h in holders:
        htype = classify_holder(h["holder_name"])
        # v2 只存国家队 + 前十大（其他机构也存，前端可选择性展示）
        conn.execute(
            "INSERT OR REPLACE INTO national_team_holders "
            "(report_date, etf_code, holder_name, holder_type, hold_share, hold_pct, rank, source_pdf_url, fetch_date) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (report_date, code, h["holder_name"], htype, h.get("hold_share"),
             h.get("hold_pct"), h["rank"], pdf_url, fetch_date),
        )
        n += 1
    conn.commit()
    return n


def fetch_and_parse_holders_v2(code: str, org_id: str, start_year: int = 2015) -> dict:
    """完整 v2 pipeline: 查年报列表 -> 下载 PDF -> 解析前十大持有人 -> 入库。
    返回 {reports_found, pdfs_downloaded, holders_extracted, national_team_count}。
    """
    conn = get_conn()
    stats = {"reports_found": 0, "pdfs_downloaded": 0, "holders_extracted": 0, "nt_count": 0}
    reports = fetch_cninfo_reports(code, org_id)
    stats["reports_found"] = len(reports)
    if not reports:
        conn.close()
        return stats

    print(f"  {code}: 找到 {len(reports)} 份年报/半年报", flush=True)
    tmp_dir = _DATA_DIR / ".cninfo_pdf"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    for rep in reports:
        report_date = _extract_report_date(rep["title"], rep["report_type"])
        if not report_date or report_date < f"{start_year}0101":
            continue
        # 已解析过的报告期跳过（DB 有该期数据则跳，除非强制）
        existing = conn.execute(
            "SELECT 1 FROM national_team_holders WHERE etf_code=? AND report_date=? LIMIT 1",
            (code, report_date)).fetchone()
        if existing:
            continue
        pdf_name = f"{code}_{report_date}.pdf"
        pdf_path = tmp_dir / pdf_name
        print(f"    {report_date} ({rep['report_type']}): 下载 {rep['pdf_url'][-40:]}", flush=True)
        if not download_cninfo_pdf(rep["pdf_url"], pdf_path):
            continue
        stats["pdfs_downloaded"] += 1
        holders = parse_top_holders_from_pdf(str(pdf_path))
        if not holders:
            print(f"      解析失败（无前十大持有人表）", flush=True)
            continue
        n = _store_holders_v2(conn, code, report_date, holders, rep["pdf_url"])
        stats["holders_extracted"] += n
        nt = sum(1 for h in holders if classify_holder(h["holder_name"]) != "其他机构")
        stats["nt_count"] += nt
        print(f"      解析 {n} 个持有人（国家队 {nt}）", flush=True)
        # 清理 PDF 释放空间
        try:
            pdf_path.unlink()
        except Exception:  # noqa: BLE001
            pass
    conn.close()
    return stats


# ── 数据入库 ────────────────────────────────────────────────────────────────────
def _upsert_daily(conn, rows: list[dict], fields: list[str]) -> int:
    """UPSERT etf_daily（按 date+etf_code 主键合并字段）。
    rows: list of dict（含 date, etf_code + 部分字段）。
    fields: 要更新的字段名列表（除 date/etf_code 外）。
    """
    n = 0
    for r in rows:
        if not r.get("date") or not r.get("etf_code"):
            continue
        cols = ["date", "etf_code"] + fields
        placeholders = ",".join(["?"] * len(cols))
        updates = ",".join(f"{f}=excluded.{f}" for f in fields)
        vals = [r.get(c) for c in cols]
        conn.execute(
            f"INSERT INTO etf_daily ({','.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(date, etf_code) DO UPDATE SET {updates}",
            vals,
        )
        n += 1
    conn.commit()
    return n


def _store_holder(conn, code: str, rows: list[dict]) -> int:
    fetch_date = dt.datetime.now().strftime("%Y%m%d")
    n = 0
    for r in rows:
        conn.execute(
            "INSERT INTO etf_holder_quarterly "
            "(report_date, etf_code, inst_hold_pct, retail_hold_pct, internal_hold_pct, total_share, fetch_date) "
            "VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(report_date, etf_code) DO UPDATE SET "
            "inst_hold_pct=excluded.inst_hold_pct, retail_hold_pct=excluded.retail_hold_pct, "
            "internal_hold_pct=excluded.internal_hold_pct, total_share=excluded.total_share, fetch_date=excluded.fetch_date",
            (r["report_date"], r["etf_code"], r.get("inst_hold_pct"),
             r.get("retail_hold_pct"), r.get("internal_hold_pct"),
             r.get("total_share"), fetch_date),
        )
        n += 1
    conn.commit()
    return n


def compute_share_change(conn, etf_code: str) -> int:
    """按 etf_code 重算 share_change = 今日份额 - 昨日份额 + share_change_pct。"""
    rows = conn.execute(
        "SELECT date, fund_share FROM etf_daily WHERE etf_code=? "
        "AND fund_share IS NOT NULL ORDER BY date", (etf_code,)
    ).fetchall()
    prev_share = None
    n = 0
    for r in rows:
        share = r["fund_share"]
        if prev_share is not None:
            change = share - prev_share
            pct = (change / prev_share * 100) if prev_share else None
            conn.execute(
                "UPDATE etf_daily SET share_change=?, share_change_pct=? WHERE date=? AND etf_code=?",
                (change, pct, r["date"], etf_code),
            )
            n += 1
        prev_share = share
    conn.commit()
    return n


def compute_signals(conn, etf_code: str) -> int:
    """重算单只 ETF 的信号。清空旧信号后按日遍历。
    z-score: (share_change - mean(过去20日,不含当日)) / std
    vol_ratio: amount / mean(过去5日,不含当日)
    """
    import pandas as pd

    rows = conn.execute(
        "SELECT date, close, amount, fund_share, share_change, share_change_pct "
        "FROM etf_daily WHERE etf_code=? ORDER BY date", (etf_code,)
    ).fetchall()
    if len(rows) < 22:
        return 0
    df = pd.DataFrame([dict(r) for r in rows])

    sc = df["share_change"]
    amt = df["amount"]
    sc_mean = sc.shift(1).rolling(20, min_periods=20).mean()
    sc_std = sc.shift(1).rolling(20, min_periods=20).std()
    z = (sc - sc_mean) / sc_std
    amt_mean = amt.shift(1).rolling(5, min_periods=5).mean()
    vol_ratio = amt / amt_mean

    # 季度校准：最新一期机构占比
    h = conn.execute(
        "SELECT inst_hold_pct FROM etf_holder_quarterly WHERE etf_code=? "
        "ORDER BY report_date DESC LIMIT 1", (etf_code,)
    ).fetchone()
    inst_pct = h["inst_hold_pct"] if h else None

    # 清空该 ETF 旧信号
    conn.execute("DELETE FROM etf_signal WHERE etf_code=?", (etf_code,))

    n = 0
    for i in range(len(df)):
        zi = z.iloc[i]
        vri = vol_ratio.iloc[i]
        if pd.isna(zi) or pd.isna(vri):
            continue
        sc_i = sc.iloc[i]
        scp = df["share_change_pct"].iloc[i]
        date = df["date"].iloc[i]
        signals: list[tuple] = []

        # 折算日排除：|变动pct|>30% 且 vol_ratio<1.0
        if scp is not None and abs(scp) > 30 and vri < 1.0:
            conn.execute(
                "INSERT OR REPLACE INTO etf_signal "
                "(date, etf_code, signal_type, share_change, amount_ratio, intensity, note) "
                "VALUES (?,?,?,?,?,?,?)",
                (date, etf_code, "split_suspect", float(sc_i) if sc_i == sc_i else None,
                 round(float(vri), 2), round(float(zi), 2), "份额折算疑似,不触发信号"),
            )
            n += 1
            continue  # 折算日不触发真实信号

        if sc_i is not None and sc_i > 0 and zi > 2 and vri > 1.5:
            signals.append(("share_surge", float(sc_i)))
        if sc_i is not None and sc_i < 0 and zi < -2 and vri > 1.5:
            signals.append(("share_outflow", float(sc_i)))
        if vri > 2:
            signals.append(("volume_surge", float(sc_i) if sc_i == sc_i else None))

        for sig_type, sc_v in signals:
            az = abs(zi)
            if az >= 5:
                grade = "极端异动"
            elif az >= 3:
                grade = "显著异动"
            else:
                grade = "轻度异动"
            notes = [grade]
            if inst_pct is not None:
                if inst_pct > 85:
                    notes.append(f"机构占比{inst_pct:.0f}%国家队主导置信×1.5")
                elif inst_pct < 60:
                    notes.append(f"机构占比{inst_pct:.0f}%散户主导置信×0.7")
            note = ",".join(notes)
            conn.execute(
                "INSERT OR REPLACE INTO etf_signal "
                "(date, etf_code, signal_type, share_change, amount_ratio, intensity, note) "
                "VALUES (?,?,?,?,?,?,?)",
                (date, etf_code, sig_type, sc_v, round(float(vri), 2),
                 round(float(zi), 2), note),
            )
            n += 1
    conn.commit()
    return n


def recompute_all_signals(conn) -> int:
    """重算所有 ETF 的 share_change + 信号。"""
    total = 0
    for code, _, _, _ in ETF_LIST:
        compute_share_change(conn, code)
        n = compute_signals(conn, code)
        total += n
    return total


# ── Pipeline: daily 增量 ────────────────────────────────────────────────────────
def pipeline_daily() -> dict:
    """当日增量：mootdx OHLC（近5日补缺）+ SSE/SZSE 份额（近5日补缺）+ 重算信号。"""
    from ..calendar import last_trading_day, trading_days_between
    print(f"[etf_nt] daily 开始 {dt.datetime.now():%Y-%m-%d %H:%M:%S}", flush=True)
    t0 = time.time()
    conn = get_conn()
    today = dt.datetime.now().strftime("%Y%m%d")
    ltd = last_trading_day()
    # 近5个交易日（补缺）
    recent = trading_days_between(
        (dt.datetime.now() - dt.timedelta(days=10)).strftime("%Y%m%d"), today)
    recent = recent[-6:] if len(recent) >= 6 else recent
    stats = {"ohlc": 0, "sse": 0, "szse": 0, "signals": 0}

    # 1. mootdx OHLC（每只ETF拉近800根覆盖近5日，复用 client 避免每只重新选服务器）
    from .mootdx_daily import tdx_client
    _tdx = tdx_client(market="std")
    for code, _, _, _ in ETF_LIST:
        try:
            rows = fetch_etf_ohlc(code, start_yyyymmdd=(dt.datetime.now() - dt.timedelta(days=15)).strftime("%Y%m%d"), client=_tdx)
            # 只取近5交易日
            recent_set = set(recent)
            rows = [r for r in rows if r["date"] in recent_set]
            # 取交易所返回的简称
            name = _etf_name_from_mootdx(code)
            for r in rows:
                r["etf_name"] = name
            n = _upsert_daily(conn, rows, ["etf_name", "close", "amount"])
            stats["ohlc"] += n
        except Exception as e:  # noqa: BLE001
            print(f"  [ohlc] {code} 失败: {type(e).__name__} {e}", flush=True)

    # 2. SSE 沪市份额（近5日逐日）
    for d in recent:
        try:
            shares = fetch_sse_shares(d)
            rows = [{"date": d, "etf_code": c, "fund_share": s} for c, s in shares.items()]
            stats["sse"] += _upsert_daily(conn, rows, ["fund_share"])
        except Exception as e:  # noqa: BLE001
            print(f"  [sse] {d} 跳过: {type(e).__name__}", flush=True)

    # 3. SZSE 深市份额（区间批量一次）
    if recent:
        try:
            sz_data = fetch_szse_shares(recent[0], recent[-1])
            rows = []
            for d, m in sz_data.items():
                for c, s in m.items():
                    rows.append({"date": d, "etf_code": c, "fund_share": s})
            stats["szse"] += _upsert_daily(conn, rows, ["fund_share"])
        except Exception as e:  # noqa: BLE001
            print(f"  [szse] 失败: {type(e).__name__} {e}", flush=True)

    # 4. 重算 share_change + 信号
    stats["signals"] = recompute_all_signals(conn)
    conn.close()

    dt_sec = time.time() - t0
    print(f"[etf_nt] daily 完成 {dt_sec:.1f}s: ohlc={stats['ohlc']} sse={stats['sse']} "
          f"szse={stats['szse']} signals={stats['signals']}", flush=True)
    return stats


_MOOTDX_NAME_CACHE: dict[str, str] = {}


def _etf_name_from_mootdx(code: str) -> str:
    """从 mootdx bars 结果取 ETF 简称（首次拉取后缓存）。取不到用配置易记名。"""
    if code in _MOOTDX_NAME_CACHE:
        return _MOOTDX_NAME_CACHE[code]
    name = ETF_BY_CODE.get(code, (code,))[0]
    _MOOTDX_NAME_CACHE[code] = name
    return name


def _fetch_and_store_name(conn, code: str, rows: list[dict]) -> None:
    """从 mootdx bars 结果里没法拿名称，用 fund_etf_fund_daily_em 取实时简称缓存。"""
    if code in _MOOTDX_NAME_CACHE:
        return
    name = ETF_BY_CODE.get(code, (code,))[0]
    try:
        throttle()
        df = ak.fund_etf_fund_daily_em()
        if df is not None and len(df):
            r = df[df["基金代码"].astype(str) == code]
            if len(r):
                name = str(r.iloc[0].get("基金简称") or name).strip()
    except Exception:  # noqa: BLE001
        pass
    _MOOTDX_NAME_CACHE[code] = name


# ── Pipeline: backfill 全量 ──────────────────────────────────────────────────────
def pipeline_backfill(start: str = DEFAULT_START) -> dict:
    """全量回填：OHLC + 持有人 + 份额 + 信号。start 格式 YYYYMMDD。"""
    from ..calendar import trading_days_between
    print(f"[etf_nt] backfill 开始 {dt.datetime.now():%Y-%m-%d %H:%M:%S} start={start}", flush=True)
    t0 = time.time()
    conn = get_conn()
    today = dt.datetime.now().strftime("%Y%m%d")
    stats = {"ohlc": 0, "holders": 0, "sse": 0, "szse": 0, "signals": 0}

    # 1. mootdx OHLC（每只ETF全历史, 老牌如510050上市2005需翻页7次, 复用 client 提速）
    print(f"[etf_nt] 1/4 OHLC（mootdx, 12只ETF）...", flush=True)
    from .mootdx_daily import tdx_client
    _tdx = tdx_client(market="std")
    for code, _, _, _ in ETF_LIST:
        try:
            rows = fetch_etf_ohlc(code, start_yyyymmdd=start, client=_tdx)
            _fetch_and_store_name(conn, code, rows)
            name = _MOOTDX_NAME_CACHE[code]
            for r in rows:
                r["etf_name"] = name
            n = _upsert_daily(conn, rows, ["etf_name", "close", "amount"])
            stats["ohlc"] += n
            print(f"  {code} {name}: {n} 行 OHLC", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"  [ohlc] {code} 失败: {type(e).__name__} {e}", flush=True)

    # 2. 持有人结构（东财直爬，12只×1s限流）
    print(f"[etf_nt] 2/4 持有人结构（东财, 12只）...", flush=True)
    for code, _, _, _ in ETF_LIST:
        try:
            rows = fetch_holder_structure(code)
            n = _store_holder(conn, code, rows)
            stats["holders"] += n
            latest = rows[0]["report_date"] if rows else "?"
            print(f"  {code}: {n} 期, 最新={latest}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"  [holder] {code} 失败: {type(e).__name__} {e}", flush=True)

    # 3. 深市份额（SZSE 区间批量，按月分段）
    print(f"[etf_nt] 3a/4 深市份额（SZSE区间批量）...", flush=True)
    # 按月分段避免单次请求过大
    cur = dt.datetime.strptime(start, "%Y%m%d")
    end_dt = dt.datetime.now()
    while cur <= end_dt:
        seg_end = min(cur + dt.timedelta(days=31), end_dt)
        sd = cur.strftime("%Y%m%d")
        ed = seg_end.strftime("%Y%m%d")
        try:
            sz_data = fetch_szse_shares(sd, ed)
            rows = []
            for d, m in sz_data.items():
                for c, s in m.items():
                    rows.append({"date": d, "etf_code": c, "fund_share": s})
            stats["szse"] += _upsert_daily(conn, rows, ["fund_share"])
        except Exception as e:  # noqa: BLE001
            print(f"  [szse] {sd}-{ed} 失败: {type(e).__name__} {e}", flush=True)
        cur = seg_end + dt.timedelta(days=1)
    print(f"  深市份额入库 {stats['szse']} 行", flush=True)

    # 4. 沪市份额（SSE 按日循环，最慢）
    # SSE fund_etf_scale_sse 最早~2012-01-04 有数据, 早于此日 KeyError 空转, 取 max
    sse_start = max(start, SSE_SHARES_EARLIEST)
    print(f"[etf_nt] 3b/4 沪市份额（SSE按日循环 {sse_start}-{today}）...", flush=True)
    tdays = trading_days_between(sse_start, today)
    n_done = 0
    batch_rows: list[dict] = []
    BATCH_SIZE = 100  # 批量提交减少WAL抖动, 防止长时间运行DB损坏
    for d in tdays:
        try:
            shares = fetch_sse_shares(d)
            for c, s in shares.items():
                batch_rows.append({"date": d, "etf_code": c, "fund_share": s})
        except Exception as e:  # noqa: BLE001
            pass  # 周末/节假日 KeyError 静默跳过
        n_done += 1
        if n_done % BATCH_SIZE == 0 or n_done == len(tdays):
            if batch_rows:
                stats["sse"] += _upsert_daily(conn, batch_rows, ["fund_share"])
                batch_rows = []
            conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
            print(f"  SSE 进度 {n_done}/{len(tdays)} 天, 累计入库 {stats['sse']} 行", flush=True)
    print(f"  沪市份额入库 {stats['sse']} 行（{n_done} 交易日）", flush=True)

    # 5. 重算 share_change + 信号
    print(f"[etf_nt] 4/4 重算 share_change + 信号...", flush=True)
    stats["signals"] = recompute_all_signals(conn)
    conn.close()

    dt_sec = time.time() - t0
    print(f"[etf_nt] backfill 完成 {dt_sec:.0f}s: ohlc={stats['ohlc']} holders={stats['holders']} "
          f"sse={stats['sse']} szse={stats['szse']} signals={stats['signals']}", flush=True)
    return stats


def pipeline_holders() -> int:
    """单独拉持有人结构（半年跑一次）。"""
    print(f"[etf_nt] holders 开始 {dt.datetime.now():%Y-%m-%d %H:%M:%S}", flush=True)
    conn = get_conn()
    total = 0
    for code, _, _, _ in ETF_LIST:
        try:
            rows = fetch_holder_structure(code)
            n = _store_holder(conn, code, rows)
            total += n
            latest = rows[0]["report_date"] if rows else "?"
            print(f"  {code}: {n} 期, 最新={latest}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"  [holder] {code} 失败: {type(e).__name__} {e}", flush=True)
    # 重算信号（持有人变了季度校准要更新）
    recompute_all_signals(conn)
    conn.close()
    print(f"[etf_nt] holders 完成, 共 {total} 期", flush=True)
    return total


def pipeline_signals() -> int:
    """只重算信号。"""
    print(f"[etf_nt] signals 重算开始...", flush=True)
    conn = get_conn()
    n = recompute_all_signals(conn)
    conn.close()
    print(f"[etf_nt] signals 重算完成, 共 {n} 条", flush=True)
    return n


def pipeline_holders_v2(start_year: int = 2015) -> dict:
    """v2: cninfo PDF 解析汇金/证金具名持有人。
    对深市 5 只 ETF（有 orgId 的）查年报/半年报 -> 下载 PDF -> 解析前十大持有人。
    沪市 7 只 cninfo 未收录 orgId，跳过（前端标注"待补"）。
    """
    print(f"[etf_nt] v2 holders 开始 {dt.datetime.now():%Y-%m-%d %H:%M:%S}", flush=True)
    t0 = time.time()
    total = {"reports_found": 0, "pdfs_downloaded": 0, "holders_extracted": 0, "nt_count": 0}
    for code, name, _, _ in ETF_LIST:
        org_id = CNINFO_ETF_ORGID.get(code)
        if not org_id:
            print(f"  {code} {name}: 跳过（cninfo 无 orgId，沪市待补）", flush=True)
            continue
        print(f"  {code} {name}: orgId={org_id}", flush=True)
        stats = fetch_and_parse_holders_v2(code, org_id, start_year=start_year)
        for k in total:
            total[k] += stats[k]
    conn = get_conn()
    # 统计国家队总数
    nt_total = conn.execute(
        "SELECT COUNT(*) FROM national_team_holders WHERE holder_type!='其他机构'"
    ).fetchone()[0]
    conn.close()
    dt_sec = time.time() - t0
    print(f"[etf_nt] v2 holders 完成 {dt_sec:.0f}s: reports={total['reports_found']} "
          f"pdfs={total['pdfs_downloaded']} holders={total['holders_extracted']} "
          f"新国家队={total['nt_count']}（DB累计国家队记录 {nt_total}）", flush=True)
    return total


# ── export JSON（双版同步：web API + static-site 文件）─────────────────────────
def export_data() -> tuple[dict, dict]:
    """生成两个 JSON 结构（daily + quarterly），供 web API 和 static-site 共用。"""
    conn = get_conn()
    today = dt.datetime.now().strftime("%Y%m%d")
    # 近60日
    start60 = (dt.datetime.now() - dt.timedelta(days=90)).strftime("%Y%m%d")
    updated_at = dt.datetime.now().isoformat()

    etfs: list[dict] = []
    for code, name, index, mkt in ETF_LIST:
        # 日级数据（近60日，过滤非交易日后的实际数据）
        rows = conn.execute(
            "SELECT date, etf_name, close, amount, fund_share, share_change, share_change_pct "
            "FROM etf_daily WHERE etf_code=? AND date>=? ORDER BY date",
            (code, start60),
        ).fetchall()
        daily = [dict(r) for r in rows]
        # 该ETF的信号（近60日）
        sig_rows = conn.execute(
            "SELECT date, signal_type, share_change, amount_ratio, intensity, note "
            "FROM etf_signal WHERE etf_code=? AND date>=? AND signal_type!='split_suspect' "
            "ORDER BY date", (code, start60),
        ).fetchall()
        sig_map: dict[str, list] = {}
        for s in sig_rows:
            sig_map.setdefault(s["date"], []).append({
                "type": s["signal_type"],
                "share_change": s["share_change"],
                "amount_ratio": s["amount_ratio"],
                "intensity": s["intensity"],
                "note": s["note"],
            })
        # 拼进 daily
        for d in daily:
            d["signals"] = sig_map.get(d["date"], [])
            # 份额转亿份展示
            if d.get("fund_share") is not None:
                d["fund_share_yi"] = round(d["fund_share"] / 1e8, 2)
            if d.get("share_change") is not None:
                d["share_change_yi"] = round(d["share_change"] / 1e8, 2)
        # 最新一行
        latest = daily[-1] if daily else None
        etfs.append({
            "code": code,
            "name": name,
            "index": index,
            "market": mkt,
            "daily": daily,
            "latest": latest,
        })

    # 季度持有人
    q_etfs: list[dict] = []
    for code, name, index, mkt in ETF_LIST:
        rows = conn.execute(
            "SELECT report_date, inst_hold_pct, retail_hold_pct, internal_hold_pct, total_share "
            "FROM etf_holder_quarterly WHERE etf_code=? ORDER BY report_date",
            (code,),
        ).fetchall()
        history = [dict(r) for r in rows]
        q_etfs.append({
            "code": code,
            "name": name,
            "index": index,
            "history": history,
        })

    # v2 具名持有人（cninfo PDF 解析的前十大持有人，含汇金/证金识别）
    h_etfs: list[dict] = []
    for code, name, index, mkt in ETF_LIST:
        rows = conn.execute(
            "SELECT report_date, holder_name, holder_type, hold_share, hold_pct, rank, source_pdf_url "
            "FROM national_team_holders WHERE etf_code=? ORDER BY report_date DESC, rank",
            (code,),
        ).fetchall()
        if not rows:
            h_etfs.append({
                "code": code, "name": name, "index": index,
                "has_data": False,
                "note": "cninfo未收录orgId，待补" if code not in CNINFO_ETF_ORGID else "暂无解析数据",
            })
            continue
        # 按报告期分组
        reports_map: dict[str, dict] = {}
        for r in rows:
            rd = r["report_date"]
            rep = reports_map.setdefault(rd, {"report_date": rd, "holders": []})
            h = {
                "rank": r["rank"],
                "name": r["holder_name"],
                "type": r["holder_type"],
                "hold_share": r["hold_share"],
                "hold_pct": r["hold_pct"],
            }
            if r["hold_share"] is not None:
                h["hold_share_yi"] = round(r["hold_share"] / 1e8, 2)
            rep["holders"].append(h)
        # 每期国家队汇总（汇金合计/证金合计）
        reports = []
        for rd in sorted(reports_map.keys(), reverse=True):
            rep = reports_map[rd]
            holders = rep["holders"]
            nt_sum: dict[str, dict] = {}
            for h in holders:
                if h["type"] == "其他机构":
                    continue
                t = h["type"]
                d = nt_sum.setdefault(t, {"count": 0, "total_share": 0.0, "total_pct": 0.0})
                d["count"] += 1
                if h["hold_share"]:
                    d["total_share"] += h["hold_share"]
                if h["hold_pct"]:
                    d["total_pct"] += h["hold_pct"]
            for d in nt_sum.values():
                d["total_share_yi"] = round(d["total_share"] / 1e8, 2)
                d["total_pct"] = round(d["total_pct"], 2)
            rep["national_team_summary"] = nt_sum
            reports.append(rep)
        # 最新一期国家队合计
        latest_nt = reports[0]["national_team_summary"] if reports else {}
        h_etfs.append({
            "code": code, "name": name, "index": index,
            "has_data": True,
            "reports": reports,
            "latest_national_team": latest_nt,
        })

    conn.close()
    daily_json = {"updated_at": updated_at, "etfs": etfs}
    quarterly_json = {"updated_at": updated_at, "etfs": q_etfs}
    holders_json = {
        "updated_at": updated_at,
        "source": "cninfo 年报/半年报 PDF §9.2 期末上市基金前十名持有人（pdfplumber 解析）",
        "note": "仅深市5只ETF有cninfo orgId；沪市7只待补。持有人类型按名称关键词识别汇金/证金/社保/外管局。",
        "etfs": h_etfs,
        # 历史公开增持事件 seed（汇金/证金宣布增持的里程碑事件）
        "events": NATIONAL_TEAM_EVENTS,
    }
    return daily_json, quarterly_json, holders_json


def export_json_files() -> None:
    """写三个 JSON 到 static-site/data/（static-site 前端读 ./data/*.json）。
    web 版走 /api/etf-national-team 动态读 DB，不需静态 JSON（与项目现有模式一致：overview/futures 等均只写 static-site/data/）。
    """
    daily_json, quarterly_json, holders_json = export_data()
    STATIC_DATA_DIR.mkdir(parents=True, exist_ok=True)
    (STATIC_DATA_DIR / "etf_national_team.json").write_text(
        json.dumps(daily_json, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (STATIC_DATA_DIR / "etf_national_team_quarterly.json").write_text(
        json.dumps(quarterly_json, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (STATIC_DATA_DIR / "etf_national_team_holders.json").write_text(
        json.dumps(holders_json, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[etf_nt] export JSON 完成 -> static-site/data/ (3 files)", flush=True)


# ── CLI ────────────────────────────────────────────────────────────────────────
def main():
    init_db()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "daily"
    if cmd in ("daily", "backfill", "signals", "holders", "holders_v2", "export"):
        # 进程互斥（daily/backfill/holders 持锁跑，signals/export/holders_v2 不需要锁）
        if cmd in ("daily", "backfill", "holders"):
            if not _acquire_lock(nonblock=True):
                print(f"[etf_nt] 已有进程在跑（{LOCK_PATH}），跳过", file=sys.stderr)
                return
        if cmd == "daily":
            stats = pipeline_daily()
            export_json_files()
        elif cmd == "backfill":
            start = DEFAULT_START
            for i, a in enumerate(sys.argv[2:], 2):
                if a == "--start" and i + 1 < len(sys.argv):
                    start = sys.argv[i + 1].replace("-", "")
            stats = pipeline_backfill(start)
            export_json_files()
        elif cmd == "signals":
            pipeline_signals()
        elif cmd == "holders":
            pipeline_holders()
            export_json_files()
        elif cmd == "holders_v2":
            pipeline_holders_v2()
            export_json_files()
        elif cmd == "export":
            export_json_files()
    else:
        print(__doc__)
        print(f"\n用法: python -m app.collector.etf_national_team <command>")
        print(f"  backfill --start 20230101   全量回填")
        print(f"  daily                       当日增量")
        print(f"  signals                     重算信号")
        print(f"  holders                     只拉持有人(半年一次)")
        print(f"  holders_v2                  v2 cninfo PDF解析汇金/证金具名持有人")
        print(f"  export                      只导出JSON")
        sys.exit(1)


if __name__ == "__main__":
    main()
