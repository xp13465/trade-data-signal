"""公募基金后端采集（独立库 data/public_fund.db, 仿 etf_national_team.db 隔离）。

口径声明：本指标追踪全市场公募基金的仓位/重仓股/行业配置/规模变动/持有人结构，
用于推断"88 魔咒"（公募仓位≥88%见顶信号）、抱团度、净申赎率等市场情绪代理指标。

9 张表：
  1. fund_basic             基金清单（fund_name_em ~27409 行）
  2. fund_position_history  全市场仓位历史（fund_stock_position_lg 445 + fund_report_asset_allocation_cninfo 76）
  3. fund_holding_stock     重仓股聚合（fund_report_stock_cninfo ~5285 行/季, 巨潮）
  4. fund_industry_alloc    逐只行业配置（fund_portfolio_industry_allocation_em, 头部 1000 只逐只）
  5. fund_asset_alloc       逐只资产配置（fund_individual_detail_hold_xq 雪球, 股票/债券/现金仓位）
  6. fund_scale_change      全市场规模变动（fund_scale_change_em 113 行）
  7. fund_hold_structure    持有人结构（fund_hold_structure_em 45 行）
  8. fund_daily_nav         基金日净值（fund_open_fund_daily_em ~23738 行）
  9. fund_metrics           8 指标（5 核心 + 3 衍生）

8 个 fetcher：
  A. fetch_fund_name()                -> fund_basic
  B. fetch_position_lg()              -> fund_position_history (stock_position_lg + asset_allocation_cninfo 合并)
  C. fetch_holding_cninfo(date)       -> fund_holding_stock
  D. fetch_hold_structure()           -> fund_hold_structure
  E. fetch_daily_nav()                -> fund_daily_nav
  F. fetch_scale_change()             -> fund_scale_change
  G. fetch_fund_asset_alloc(code)     -> fund_asset_alloc (xq 雪球, 逐只)
  H. fetch_fund_industry_alloc(code)  -> fund_industry_alloc (em, 逐只)

8 指标 (compute_metrics)：
  核心 5:
    1. avg_position            平均股票仓位% (fund_position_history 最新值)
    2. concentration_herfindahl 抱团度: 重仓股基金覆盖家数 Herfindahl 指数 (fund_holding_stock)
    3. overlap_ratio           重叠度: Top30 重仓股平均基金覆盖家数 (fund_holding_stock)
    4. industry_concentration  行业集中度: 全市场行业配置 Herfindahl (fund_industry_alloc 聚合)
    5. net_redeem_ratio        净申赎率%: (申购-赎回)/期初份额 (fund_scale_change 最新期)
  衍生 3:
    6. position_change_ratio   加仓减仓比: 当期vs上期仓位变化>0家数/<0家数 (fund_position_history)
    7. top20_adjustment        头部 Top20 调仓: Top20 重仓股持股总市值环比变化 (fund_holding_stock)
    8. top30_concentration     Top30 集中度: Top30 重仓股占全市场重仓市值比例 (fund_holding_stock)

反爬策略:
  - 延时 0.5s (throttle 全局, 复用 base.throttle)
  - retry 3 次 (safe_call, 遇 514 等连接错误指数退避 2-5s)
  - 断点续采 /tmp/fund-collect-progress.json (逐只子页 fetcher 失败记录, 重跑跳过已采)

CLI 子命令:
  python -m app.collector.public_fund quarterly       季度全量(5汇总+top1000×2子页+8指标, ~35min)
  python -m app.collector.public_fund full             全量9000只×2子页(~5.25h, 凌晨解耦)
  python -m app.collector.public_fund daily            日更净值+估算仓位变化(8s)
  python -m app.collector.public_fund metrics          重算8指标
  python -m app.collector.public_fund export           导出JSON产物
  python -m app.collector.public_fund backfill --start 20240101 --end 20241231  历史回填
  python -m app.collector.public_fund check-fresh [--top N]  数据新鲜度闸门(exit 0=应跑, 1=跳过)
"""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

# 必须先 import base，应用 trust_env=False 全局补丁（绕 Clash 代理直连东财/雪球）
from . import base  # noqa: F401
import akshare as ak

from .base import safe_call, throttle

# ── 路径与常量 ──────────────────────────────────────────────────────────────────
_DATA_DIR = Path(__file__).absolute().parent.parent.parent / "data"
DB_PATH = _DATA_DIR / "public_fund.db"
LOCK_PATH = _DATA_DIR / "public_fund.lock"
STATIC_DATA_DIR = Path(__file__).absolute().parent.parent.parent / "static-site" / "data"
PROGRESS_PATH = Path("/tmp/fund-collect-progress.json")

DEFAULT_START = "20171201"  # fund_stock_position_lg 最早 2017-12-04
THROTTLE_SEC = 0.5  # 逐只子页延时（xq/em 限流不严, 0.5s 安全）

# 头部基金样本量: 季度 pipeline 默认 1000 只（35min），全量 9000 只（5.25h）
QUARTERLY_TOP_N = 1000
FULL_TOP_N = 9000

# 最新报告期（YYYYMMDD）：默认用最近年末/半年末
def _latest_report_dates(n: int = 4) -> list[str]:
    """最近 n 个报告期: 季末日期 YYYYMMDD（半年报 0630 / 年报 1231）。"""
    today = dt.date.today()
    dates: list[str] = []
    y, m = today.year, today.month
    # 半年报/年报规则: 4-9月用去年年报+前年半年报, 10-3月用今年半年报+去年年报
    for _ in range(n * 2):
        if m >= 7:
            dates.append(f"{y}0630")
            y, m = y - 1, 12
        else:
            dates.append(f"{y - 1}1231")
            y, m = y - 1, 6
        if len(dates) >= n:
            break
    return dates[:n]


# ── DB schema ───────────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS fund_basic (
  fund_code TEXT PRIMARY KEY,
  fund_name TEXT,
  fund_type TEXT,
  pinyin_abbr TEXT,
  pinyin_full TEXT,
  update_date TEXT
);
CREATE INDEX IF NOT EXISTS idx_fund_basic_type ON fund_basic(fund_type);

-- 全市场仓位历史（合并 stock_position_lg 445 + asset_allocation_cninfo 76）
CREATE TABLE IF NOT EXISTS fund_position_history (
  report_date TEXT NOT NULL,
  source TEXT NOT NULL,              -- 'lg'(股票仓位) / 'cninfo'(资产配置)
  position_pct REAL,                 -- 股票仓位% (lg: position; cninfo: 股票权益类)
  bond_pct REAL,                     -- 债券仓位% (cninfo only)
  cash_pct REAL,                     -- 现金仓位% (cninfo only)
  other_pct REAL,                    -- 其他% (cninfo only)
  fund_count INTEGER,                -- 基金覆盖家数
  total_net_asset REAL,              -- 基金市场净资产规模(亿)
  close REAL,                        -- 上证综指收盘(lg only, 辅助)
  fetch_date TEXT,
  PRIMARY KEY (report_date, source)
);
CREATE INDEX IF NOT EXISTS idx_position_history_date ON fund_position_history(report_date);

-- 重仓股聚合（fund_report_stock_cninfo ~5285 行/季）
CREATE TABLE IF NOT EXISTS fund_holding_stock (
  report_date TEXT NOT NULL,
  stock_code TEXT NOT NULL,
  stock_name TEXT,
  fund_count INTEGER,                -- 基金覆盖家数
  hold_share_total REAL,             -- 持股总数(股)
  hold_value_total REAL,             -- 持仓总市值(万元)
  PRIMARY KEY (report_date, stock_code)
);
CREATE INDEX IF NOT EXISTS idx_holding_stock_date ON fund_holding_stock(report_date);
CREATE INDEX IF NOT EXISTS idx_holding_stock_value ON fund_holding_stock(report_date, hold_value_total DESC);

-- 逐只行业配置（fund_portfolio_industry_allocation_em, 头部 1000 只）
CREATE TABLE IF NOT EXISTS fund_industry_alloc (
  report_date TEXT NOT NULL,
  fund_code TEXT NOT NULL,
  industry_name TEXT NOT NULL,
  weight_pct REAL,                   -- 占净值比%
  hold_value REAL,                   -- 市值(万元)
  PRIMARY KEY (report_date, fund_code, industry_name)
);
CREATE INDEX IF NOT EXISTS idx_industry_alloc_code ON fund_industry_alloc(fund_code);
CREATE INDEX IF NOT EXISTS idx_industry_alloc_date ON fund_industry_alloc(report_date);

-- 逐只资产配置（fund_individual_detail_hold_xq 雪球, 股票/债券/现金仓位占比）
CREATE TABLE IF NOT EXISTS fund_asset_alloc (
  report_date TEXT NOT NULL,
  fund_code TEXT NOT NULL,
  stock_pct REAL,                    -- 股票占比%
  bond_pct REAL,                     -- 债券占比%
  cash_pct REAL,                     -- 现金占比%
  other_pct REAL,                    -- 其他占比%
  PRIMARY KEY (report_date, fund_code)
);
CREATE INDEX IF NOT EXISTS idx_asset_alloc_code ON fund_asset_alloc(fund_code);

-- 全市场规模变动（fund_scale_change_em 113 行, 季度时序）
CREATE TABLE IF NOT EXISTS fund_scale_change (
  report_date TEXT NOT NULL,
  fund_count INTEGER,                -- 基金家数
  purchase_share REAL,               -- 期间申购(亿份)
  redeem_share REAL,                 -- 期间赎回(亿份)
  net_purchase_share REAL,           -- 净申赎份额(亿份, =申购-赎回)
  end_total_share REAL,              -- 期末总份额(亿份)
  end_net_asset REAL,                -- 期末净资产(亿元)
  PRIMARY KEY (report_date)
);

-- 持有人结构（fund_hold_structure_em 45 行, 半年报+年报）
CREATE TABLE IF NOT EXISTS fund_hold_structure (
  report_date TEXT NOT NULL,
  fund_count INTEGER,                -- 基金家数
  inst_hold_pct REAL,                -- 机构持有比例%
  retail_hold_pct REAL,              -- 个人持有比例%
  internal_hold_pct REAL,            -- 内部持有比例%
  total_share REAL,                  -- 总份额(亿份)
  PRIMARY KEY (report_date)
);

-- 基金日净值（fund_open_fund_daily_em ~23738 行, 日更）
CREATE TABLE IF NOT EXISTS fund_daily_nav (
  date TEXT NOT NULL,
  fund_code TEXT NOT NULL,
  fund_name TEXT,
  unit_nav REAL,                     -- 单位净值
  acc_nav REAL,                      -- 累计净值
  prev_unit_nav REAL,                -- 前日单位净值
  nav_change_pct REAL,               -- 日增长率%
  PRIMARY KEY (date, fund_code)
);
CREATE INDEX IF NOT EXISTS idx_daily_nav_code ON fund_daily_nav(fund_code);

-- 8 指标
CREATE TABLE IF NOT EXISTS fund_metrics (
  report_date TEXT NOT NULL,
  metric_id TEXT NOT NULL,
  metric_name TEXT,
  metric_value REAL,
  detail TEXT,                       -- JSON 字符串(明细, 如 Top30 重仓股清单)
  fetch_date TEXT,
  PRIMARY KEY (report_date, metric_id)
);
CREATE INDEX IF NOT EXISTS idx_metrics_id ON fund_metrics(metric_id);
"""

_LOCK_FILE: list = [None]


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
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()


def _acquire_lock(nonblock: bool = True) -> bool:
    """fcntl.flock 进程互斥（macOS 用 fcntl 非 flock 命令）。"""
    f = open(LOCK_PATH, "w")
    flags = fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblock else 0)
    try:
        fcntl.flock(f, flags)
    except BlockingIOError:
        return False
    _LOCK_FILE[0] = f
    return True


# ── 通用工具 ────────────────────────────────────────────────────────────────────
def _to_yyyymmdd(d) -> str:
    """日期转 YYYYMMDD 字符串（兼容 datetime.date / datetime / 字符串）。"""
    if d is None:
        return ""
    if isinstance(d, str):
        s = d.replace("-", "").replace("/", "")
        return s
    if isinstance(d, (dt.date, dt.datetime)):
        return d.strftime("%Y%m%d")
    return str(d)


def _safe_float(v, default=None) -> float | None:
    """安全转 float（None/NaN/'-'/'--' 返回 default）。"""
    if v is None:
        return default
    try:
        if isinstance(v, str):
            v = v.strip().replace("%", "").replace(",", "")
            if v in ("", "--", "-", "nan", "NaN"):
                return default
        f = float(v)
        if f != f:  # NaN
            return default
        return f
    except (ValueError, TypeError):
        return default


# ── Fetcher A: 基金清单 ─────────────────────────────────────────────────────────
def fetch_fund_name() -> int:
    """fund_name_em 全量基金清单 -> fund_basic（27409 行）。"""
    print("[A] fetch_fund_name() ...", flush=True)
    t = time.time()
    df = safe_call(ak.fund_name_em, retries=2)
    if isinstance(df, Exception) or df is None or len(df) == 0:
        print(f"[A] FAIL: {df}", flush=True)
        return 0
    today = dt.date.today().strftime("%Y%m%d")
    rows = []
    for _, r in df.iterrows():
        rows.append((
            str(r.get("基金代码", "")).strip(),
            str(r.get("基金简称", "")).strip(),
            str(r.get("基金类型", "")).strip(),
            str(r.get("拼音缩写", "")).strip(),
            str(r.get("拼音全称", "")).strip(),
            today,
        ))
    conn = get_conn()
    conn.executemany(
        "INSERT OR REPLACE INTO fund_basic"
        "(fund_code, fund_name, fund_type, pinyin_abbr, pinyin_full, update_date) "
        "VALUES (?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    print(f"[A] fund_basic 写入 {len(rows)} 行, {time.time()-t:.1f}s", flush=True)
    return len(rows)


# ── Fetcher B: 全市场仓位历史（stock_position_lg + asset_allocation_cninfo 合并）──
def fetch_position_lg() -> int:
    """fund_stock_position_lg (445) + fund_report_asset_allocation_cninfo (76) -> fund_position_history。"""
    print("[B] fetch_position_lg() ...", flush=True)
    t = time.time()
    today = dt.date.today().strftime("%Y%m%d")
    rows: list[tuple] = []

    # B1: stock_position_lg (445行, cols: date/close/position)
    df1 = safe_call(ak.fund_stock_position_lg, retries=2)
    if isinstance(df1, Exception) or df1 is None or len(df1) == 0:
        print(f"[B1] stock_position_lg FAIL: {df1}", flush=True)
    else:
        for _, r in df1.iterrows():
            report_date = _to_yyyymmdd(r.get("date"))
            position = _safe_float(r.get("position"))
            close = _safe_float(r.get("close"))
            if not report_date or position is None:
                continue
            rows.append((report_date, "lg", position, None, None, None, None, None, close, today))
        print(f"[B1] stock_position_lg +{len(df1)} 行", flush=True)

    # B2: fund_report_asset_allocation_cninfo (76行, cninfo 全市场资产配置)
    df2 = safe_call(ak.fund_report_asset_allocation_cninfo, retries=2)
    if isinstance(df2, Exception) or df2 is None or len(df2) == 0:
        print(f"[B2] asset_allocation_cninfo FAIL: {df2}", flush=True)
    else:
        for _, r in df2.iterrows():
            report_date = _to_yyyymmdd(r.get("报告期"))
            stock_pct = _safe_float(r.get("股票权益类占净资产比例"))
            bond_pct = _safe_float(r.get("债券固定收益类占净资产比例"))
            cash_pct = _safe_float(r.get("现金货币类占净资产比例"))
            fund_count = _safe_float(r.get("基金覆盖家数"))
            total_na = _safe_float(r.get("基金市场净资产规模"))
            if not report_date:
                continue
            # other = 100 - stock - bond - cash
            other_pct = None
            if stock_pct is not None and bond_pct is not None and cash_pct is not None:
                other_pct = max(0.0, 100.0 - stock_pct - bond_pct - cash_pct)
            rows.append((report_date, "cninfo", stock_pct, bond_pct, cash_pct, other_pct,
                         int(fund_count) if fund_count else None, total_na, None, today))
        print(f"[B2] asset_allocation_cninfo +{len(df2)} 行", flush=True)

    if not rows:
        return 0
    conn = get_conn()
    conn.executemany(
        "INSERT OR REPLACE INTO fund_position_history"
        "(report_date, source, position_pct, bond_pct, cash_pct, other_pct,"
        " fund_count, total_net_asset, close, fetch_date) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    print(f"[B] fund_position_history 写入 {len(rows)} 行, {time.time()-t:.1f}s", flush=True)
    return len(rows)


# ── Fetcher C: 重仓股聚合 ───────────────────────────────────────────────────────
def fetch_holding_cninfo(report_date: str | None = None) -> int:
    """fund_report_stock_cninfo(date) -> fund_holding_stock（~5285 行/季, 巨潮）。

    Args:
      report_date: YYYYMMDD 报告期（如 '20251231'），默认取 _latest_report_dates()[0]
    """
    if report_date is None:
        report_date = _latest_report_dates(1)[0]
    print(f"[C] fetch_holding_cninfo({report_date}) ...", flush=True)
    t = time.time()
    # akshare 接受 '20251231' / '20251231' 两种格式
    df = safe_call(ak.fund_report_stock_cninfo, retries=2, date=report_date)
    if isinstance(df, Exception) or df is None or len(df) == 0:
        print(f"[C] FAIL: {df}", flush=True)
        return 0
    rows = []
    for _, r in df.iterrows():
        stock_code = str(r.get("股票代码", "")).strip()
        stock_name = str(r.get("股票简称", "")).strip()
        fund_count = _safe_float(r.get("基金覆盖家数"))
        hold_share = _safe_float(r.get("持股总数"))
        hold_value = _safe_float(r.get("持股总市值"))
        if not stock_code:
            continue
        rows.append((
            report_date, stock_code, stock_name,
            int(fund_count) if fund_count else None,
            hold_share,
            hold_value,
        ))
    conn = get_conn()
    conn.executemany(
        "INSERT OR REPLACE INTO fund_holding_stock"
        "(report_date, stock_code, stock_name, fund_count, hold_share_total, hold_value_total) "
        "VALUES (?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    print(f"[C] fund_holding_stock 写入 {len(rows)} 行 @ {report_date}, {time.time()-t:.1f}s", flush=True)
    return len(rows)


# ── 数据新鲜度闸门 ──────────────────────────────────────────────────────────────
def _fetch_source_latest_report_date() -> str | None:
    """查询源(ak.fund_report_asset_allocation_cninfo)最新季报 report_date。

    只读检查, 不写 DB。调 cninfo 全市场资产配置汇总接口(B2, ~76 行季度数据),
    取最大报告期作为"源最新季报 report_date"。用于 has_new_data() 判断源是否有新季报。

    Returns: YYYYMMDD 字符串, 或 None(查询失败)
    """
    try:
        df = safe_call(ak.fund_report_asset_allocation_cninfo, retries=2)
        if isinstance(df, Exception) or df is None or len(df) == 0:
            print(f"[fresh] 源查询失败: {df}", flush=True)
            return None
        dates: list[str] = []
        for _, r in df.iterrows():
            d = _to_yyyymmdd(r.get("报告期"))
            if d:
                dates.append(d)
        return max(dates) if dates else None
    except Exception as e:  # noqa: BLE001
        print(f"[fresh] 源查询异常: {type(e).__name__} {e}", flush=True)
        return None


def has_new_data(top_n: int = QUARTERLY_TOP_N) -> tuple[bool, str]:
    """数据新鲜度闸门: 跑前检查源是否有新季报数据可采, 无新数据则跳过避免重复跑。

    核心逻辑(非季报日历闸门, 是数据新鲜度判断):
      - 源最新 report_date > DB 已采 report_date -> 跑(新季报披露了)
      - 源 == DB 但覆盖率不足(有失败) -> 补采(兜底重试)
      - 源 == DB 且采全 -> 跳过(无新数据, 重复跑没意义)

    实现:
      1. 源最新季报 report_date: 调 cninfo B2 接口(全市场资产配置汇总, 季度频, ~76 行)
         注意: fund_position_history 的 lg 源是周频不能用, cninfo 源才是季报
      2. DB 最新季报 report_date: fund_holding_stock MAX(report_date)(重仓股表, 季报频)
         fallback: fund_asset_alloc MAX(report_date); 再 fallback: None(首次跑必采)
      3. 覆盖率判断(源==DB 时):
         - fund_holding_stock @ db_latest 行数 < 4500(历史采全约 5285 行, 85% 阈值)
         - fund_asset_alloc @ db_latest DISTINCT fund_code < top_n * 0.95
         任一不足 -> 补采

    Args:
      top_n: 期望采全的基金数(quarterly=1000, full=9000), 用于 asset_alloc 覆盖率阈值
    Returns:
      (should_run, reason): should_run=True 应跑/补采, False 跳过
    """
    src_latest = _fetch_source_latest_report_date()
    if src_latest is None:
        return (True, "源查询失败, 默认跑(安全侧不跳过)")

    conn = get_conn()
    try:
        row = conn.execute("SELECT MAX(report_date) FROM fund_holding_stock").fetchone()
        db_latest = row[0] if row else None
        if db_latest is None:
            row = conn.execute("SELECT MAX(report_date) FROM fund_asset_alloc").fetchone()
            db_latest = row[0] if row else None
    finally:
        conn.close()

    if db_latest is None:
        return (True, f"DB 无数据(首次跑), 源最新={src_latest}, 应跑")

    if src_latest > db_latest:
        return (True, f"有新季报数据 src={src_latest} db={db_latest}, 应跑")
    if src_latest < db_latest:
        return (False, f"DB 比源新 db={db_latest} src={src_latest}, 跳过(防御性)")

    # src == db: 检查覆盖率(判断是否有失败基金需补采)
    holding_threshold = 4500  # 历史采全约 5285 行/季, 85% 阈值
    asset_threshold = int(top_n * 0.95)
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM fund_holding_stock WHERE report_date=?", (db_latest,)
        ).fetchone()
        holding_cnt = row[0] if row else 0
        row = conn.execute(
            "SELECT COUNT(DISTINCT fund_code) FROM fund_asset_alloc WHERE report_date=?",
            (db_latest,),
        ).fetchone()
        asset_cnt = row[0] if row else 0
    finally:
        conn.close()

    if holding_cnt < holding_threshold or asset_cnt < asset_threshold:
        return (True, f"补采失败基金 report_date={db_latest} "
                      f"holding={holding_cnt}/{holding_threshold} "
                      f"asset_alloc={asset_cnt}/{top_n}, 应跑")
    return (False, f"无新数据 report_date={db_latest} 已采全 "
                   f"holding={holding_cnt} asset_alloc={asset_cnt}/{top_n}, 跳过")


# ── Fetcher D: 持有人结构 ───────────────────────────────────────────────────────
def fetch_hold_structure() -> int:
    """fund_hold_structure_em (45) -> fund_hold_structure。"""
    print("[D] fetch_hold_structure() ...", flush=True)
    t = time.time()
    df = safe_call(ak.fund_hold_structure_em, retries=2)
    if isinstance(df, Exception) or df is None or len(df) == 0:
        print(f"[D] FAIL: {df}", flush=True)
        return 0
    rows = []
    for _, r in df.iterrows():
        report_date = _to_yyyymmdd(r.get("截止日期"))
        if not report_date:
            continue
        fund_count = _safe_float(r.get("基金家数"))
        inst = _safe_float(r.get("机构持有比列"))  # akshare 拼写'比列'(源站错字)
        retail = _safe_float(r.get("个人持有比列"))
        internal = _safe_float(r.get("内部持有比列"))
        total_share = _safe_float(r.get("总份额"))
        rows.append((
            report_date,
            int(fund_count) if fund_count else None,
            inst, retail, internal, total_share,
        ))
    conn = get_conn()
    conn.executemany(
        "INSERT OR REPLACE INTO fund_hold_structure"
        "(report_date, fund_count, inst_hold_pct, retail_hold_pct, internal_hold_pct, total_share) "
        "VALUES (?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    print(f"[D] fund_hold_structure 写入 {len(rows)} 行, {time.time()-t:.1f}s", flush=True)
    return len(rows)


# ── Fetcher E: 基金日净值 ───────────────────────────────────────────────────────
def fetch_daily_nav() -> int:
    """fund_open_fund_daily_em (~23738) -> fund_daily_nav（日更）。"""
    print("[E] fetch_daily_nav() ...", flush=True)
    t = time.time()
    df = safe_call(ak.fund_open_fund_daily_em, retries=2)
    if isinstance(df, Exception) or df is None or len(df) == 0:
        print(f"[E] FAIL: {df}", flush=True)
        return 0
    # 列结构: '基金代码','基金简称','<date>-单位净值','<date>-累计净值','<prev_date>-单位净值','<prev_date>-累计净值','日增长值','日增长率'
    cols = list(df.columns)
    # 找到日期列名（"YYYY-MM-DD-单位净值"）
    today_col_unit = next((c for c in cols if "-单位净值" in c and "2026" in c), None)
    today_col_acc = next((c for c in cols if "-累计净值" in c and "2026" in c), None)
    prev_col_unit = None
    # 第二个 'YYYY-MM-DD-单位净值' 是前日
    unit_cols = [c for c in cols if "-单位净值" in c]
    if len(unit_cols) >= 2:
        prev_col_unit = unit_cols[1]
    if not today_col_unit:
        print(f"[E] WARN 找不到今日单位净值列, cols[:10]={cols[:10]}", flush=True)
        return 0
    # 今日日期 YYYYMMDD（列名格式 'YYYY-MM-DD-单位净值', 取前 3 段拼成 YYYYMMDD）
    # split('-') -> ['YYYY','MM','DD','单位净值']，取前3段
    parts = today_col_unit.split("-")
    if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit():
        today_str = f"{parts[0]}{parts[1]}{parts[2]}"
    else:
        today_str = dt.date.today().strftime("%Y%m%d")
    rows = []
    for _, r in df.iterrows():
        fund_code = str(r.get("基金代码", "")).strip()
        if not fund_code:
            continue
        fund_name = str(r.get("基金简称", "")).strip()
        unit_nav = _safe_float(r.get(today_col_unit))
        acc_nav = _safe_float(r.get(today_col_acc)) if today_col_acc else None
        prev_unit = _safe_float(r.get(prev_col_unit)) if prev_col_unit else None
        nav_pct = _safe_float(r.get("日增长率"))
        rows.append((today_str, fund_code, fund_name, unit_nav, acc_nav, prev_unit, nav_pct))
    conn = get_conn()
    conn.executemany(
        "INSERT OR REPLACE INTO fund_daily_nav"
        "(date, fund_code, fund_name, unit_nav, acc_nav, prev_unit_nav, nav_change_pct) "
        "VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    print(f"[E] fund_daily_nav 写入 {len(rows)} 行 @{today_str}, {time.time()-t:.1f}s", flush=True)
    return len(rows)


# ── Fetcher F: 全市场规模变动 ───────────────────────────────────────────────────
def fetch_scale_change() -> int:
    """fund_scale_change_em (113) -> fund_scale_change（全市场净申赎时序）。"""
    print("[F] fetch_scale_change() ...", flush=True)
    t = time.time()
    df = safe_call(ak.fund_scale_change_em, retries=2)
    if isinstance(df, Exception) or df is None or len(df) == 0:
        print(f"[F] FAIL: {df}", flush=True)
        return 0
    rows = []
    for _, r in df.iterrows():
        report_date = _to_yyyymmdd(r.get("截止日期"))
        if not report_date:
            continue
        fund_count = _safe_float(r.get("基金家数"))
        purchase = _safe_float(r.get("期间申购"))
        redeem = _safe_float(r.get("期间赎回"))
        end_share = _safe_float(r.get("期末总份额"))
        end_na = _safe_float(r.get("期末净资产"))
        net_purchase = None
        if purchase is not None and redeem is not None:
            net_purchase = purchase - redeem
        rows.append((
            report_date,
            int(fund_count) if fund_count else None,
            purchase, redeem, net_purchase, end_share, end_na,
        ))
    conn = get_conn()
    conn.executemany(
        "INSERT OR REPLACE INTO fund_scale_change"
        "(report_date, fund_count, purchase_share, redeem_share, net_purchase_share,"
        " end_total_share, end_net_asset) "
        "VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    print(f"[F] fund_scale_change 写入 {len(rows)} 行, {time.time()-t:.1f}s", flush=True)
    return len(rows)


# ── 逐只 fetcher G: 资产配置（雪球 xq）────────────────────────────────────────
def fetch_fund_asset_alloc(code: str, report_date: str | None = None) -> int:
    """fund_individual_detail_hold_xq(symbol, date) -> fund_asset_alloc。

    雪球返回 4 行: 股票/债券/现金/其他 占比%。
    Args:
      code: 基金代码
      report_date: YYYYMMDD 报告期, 默认最近年末
    """
    if report_date is None:
        report_date = _latest_report_dates(1)[0]
    # xq 接口接受 'YYYY-MM-DD'
    xq_date = f"{report_date[:4]}-{report_date[4:6]}-{report_date[6:8]}"
    try:
        df = safe_call(ak.fund_individual_detail_hold_xq, retries=2,
                       symbol=code, date=xq_date)
        if isinstance(df, Exception) or df is None or len(df) == 0:
            return 0
    except Exception as e:  # noqa: BLE001
        print(f"[G] {code} xq FAIL: {type(e).__name__} {e}", flush=True)
        return 0
    stock_pct = bond_pct = cash_pct = other_pct = None
    for _, r in df.iterrows():
        atype = str(r.get("资产类型", "")).strip()
        pct = _safe_float(r.get("仓位占比"))
        if "股票" in atype:
            stock_pct = pct
        elif "债券" in atype:
            bond_pct = pct
        elif "现金" in atype:
            cash_pct = pct
        elif "其他" in atype or "其他" in atype:
            other_pct = pct
    if all(v is None for v in (stock_pct, bond_pct, cash_pct, other_pct)):
        return 0
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO fund_asset_alloc"
        "(report_date, fund_code, stock_pct, bond_pct, cash_pct, other_pct) "
        "VALUES (?,?,?,?,?,?)",
        (report_date, code, stock_pct, bond_pct, cash_pct, other_pct),
    )
    conn.commit()
    conn.close()
    return 1


# ── 逐只 fetcher H: 行业配置 ───────────────────────────────────────────────────
def fetch_fund_industry_alloc(code: str, year: str | None = None) -> int:
    """fund_portfolio_industry_allocation_em(symbol, date) -> fund_industry_alloc。

    Args:
      code: 基金代码
      year: 'YYYY' 年份, 默认最近年末
    """
    if year is None:
        year = _latest_report_dates(1)[0][:4]
    try:
        df = safe_call(ak.fund_portfolio_industry_allocation_em, retries=2,
                       symbol=code, date=year)
        if isinstance(df, Exception) or df is None or len(df) == 0:
            return 0
    except Exception as e:  # noqa: BLE001
        print(f"[H] {code} industry FAIL: {type(e).__name__} {e}", flush=True)
        return 0
    rows = []
    for _, r in df.iterrows():
        industry = str(r.get("行业类别", "")).strip()
        weight = _safe_float(r.get("占净值比例"))
        value = _safe_float(r.get("市值"))
        report_date_raw = str(r.get("截止时间", "")).strip()
        report_date = _to_yyyymmdd(report_date_raw)
        if not industry or not report_date:
            continue
        rows.append((report_date, code, industry, weight, value))
    if not rows:
        return 0
    conn = get_conn()
    conn.executemany(
        "INSERT OR REPLACE INTO fund_industry_alloc"
        "(report_date, fund_code, industry_name, weight_pct, hold_value) "
        "VALUES (?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    return len(rows)


# ── universe 选择 ───────────────────────────────────────────────────────────────
def universe_top_funds(n: int = QUARTERLY_TOP_N, conn=None) -> list[tuple[str, str, str]]:
    """头部基金清单: 优先按 fund_basic 选, 当前实现按 fund_code 升序前 n 只（排除指数股票型）。

    Returns: [(fund_code, fund_name, fund_type), ...]
    """
    own_conn = conn is None
    if own_conn:
        conn = get_conn()
    try:
        # 排除纯指数型/ETF联接/QDII（主动管理型对 88 魔咒/抱团度更有意义）
        rows = conn.execute(
            "SELECT fund_code, fund_name, fund_type FROM fund_basic "
            "WHERE fund_type NOT LIKE '%指数%' "
            "  AND fund_type NOT LIKE '%ETF联接%' "
            "  AND fund_type NOT LIKE '%QDII%' "
            "  AND fund_type NOT LIKE '%债%' "
            "  AND fund_type NOT LIKE '%货币%' "
            "ORDER BY fund_code ASC LIMIT ?",
            (n,),
        ).fetchall()
        result = [(r[0], r[1], r[2]) for r in rows]
    finally:
        if own_conn:
            conn.close()
    return result


# ── 断点续采 ────────────────────────────────────────────────────────────────────
def _load_progress() -> dict:
    if not PROGRESS_PATH.exists():
        return {"asset_alloc": [], "industry_alloc": []}
    try:
        return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"asset_alloc": [], "industry_alloc": []}


def _save_progress(prog: dict) -> None:
    try:
        PROGRESS_PATH.write_text(json.dumps(prog, ensure_ascii=False), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"  [progress] WARN 写入失败: {e}", flush=True)


def _fetch_per_fund_batch(funds: list[tuple[str, str, str]], label: str = "quarterly") -> dict:
    """逐只跑 fetch_fund_asset_alloc + fetch_fund_industry_alloc。

    反爬: 延时 0.5s + retry3(已含 safe_call) + 断点续采 /tmp/fund-collect-progress.json
    Returns: {"asset_alloc_ok": n, "asset_alloc_fail": n, "industry_ok": n, "industry_fail": n}
    """
    prog = _load_progress()
    asset_done = set(prog.get("asset_alloc", []))
    industry_done = set(prog.get("industry_alloc", []))
    asset_ok = asset_fail = industry_ok = industry_fail = 0
    total = len(funds)
    t0 = time.time()
    for i, (code, name, _ftype) in enumerate(funds, 1):
        # 资产配置 (G)
        if code not in asset_done:
            try:
                n = fetch_fund_asset_alloc(code)
                if n > 0:
                    asset_ok += 1
                    asset_done.add(code)
                else:
                    asset_fail += 1
            except Exception as e:  # noqa: BLE001
                asset_fail += 1
                print(f"  [G] {code} {name} 异常: {type(e).__name__} {e}", flush=True)
            time.sleep(THROTTLE_SEC)
        # 行业配置 (H)
        if code not in industry_done:
            try:
                n = fetch_fund_industry_alloc(code)
                if n > 0:
                    industry_ok += 1
                    industry_done.add(code)
                else:
                    industry_fail += 1
            except Exception as e:  # noqa: BLE001
                industry_fail += 1
                print(f"  [H] {code} {name} 异常: {type(e).__name__} {e}", flush=True)
            time.sleep(THROTTLE_SEC)
        # 每 50 只回写进度
        if i % 50 == 0 or i == total:
            prog["asset_alloc"] = sorted(asset_done)
            prog["industry_alloc"] = sorted(industry_done)
            _save_progress(prog)
            elapsed = time.time() - t0
            eta = (elapsed / i) * (total - i) if i > 0 else 0
            print(f"  [{label}] {i}/{total} ({i*100/total:.1f}%) "
                  f"asset_ok={asset_ok} industry_ok={industry_ok} "
                  f"elapsed={elapsed:.0f}s eta={eta:.0f}s", flush=True)
    return {
        "asset_alloc_ok": asset_ok, "asset_alloc_fail": asset_fail,
        "industry_ok": industry_ok, "industry_fail": industry_fail,
    }


# ── 8 指标计算 ──────────────────────────────────────────────────────────────────
def compute_metrics(report_date: str | None = None) -> dict:
    """计算 8 指标写入 fund_metrics（5 核心 + 3 衍生）。

    Args:
      report_date: YYYYMMDD 报告期, 默认取 _latest_report_dates(1)[0]
    Returns: {metric_id: value, ...}
    """
    if report_date is None:
        report_date = _latest_report_dates(1)[0]
    today = dt.date.today().strftime("%Y%m%d")
    print(f"[metrics] compute @ {report_date} ...", flush=True)
    conn = get_conn()
    results: dict[str, float | None] = {}
    detail: dict[str, any] = {}

    # 1. avg_position 平均股票仓位% (lg源优先: 股票型+混合型基金仓位, 88魔咒专用)
    # lg 源 ~80-92% 反映主动权益基金仓位（88魔咒≥88%见顶）
    # cninfo 源 ~20-25% 反映全市场基金资产配置（含债基/货基, 偏低）
    row_lg = conn.execute(
        "SELECT position_pct, report_date FROM fund_position_history "
        "WHERE source='lg' AND position_pct IS NOT NULL "
        "ORDER BY report_date DESC LIMIT 1"
    ).fetchone()
    row_cn = conn.execute(
        "SELECT position_pct, report_date FROM fund_position_history "
        "WHERE source='cninfo' AND position_pct IS NOT NULL "
        "ORDER BY report_date DESC LIMIT 1"
    ).fetchone()
    avg_position = row_lg[0] if row_lg else (row_cn[0] if row_cn else None)
    results["avg_position"] = avg_position
    detail["avg_position"] = {
        "lg_position": row_lg[0] if row_lg else None,
        "lg_date": row_lg[1] if row_lg else None,
        "cninfo_position": row_cn[0] if row_cn else None,
        "cninfo_date": row_cn[1] if row_cn else None,
        "note": "lg=股票型+混合型仓位(88魔咒专用); cninfo=全市场资产配置(含债基/货基)",
    }

    # 2. concentration_herfindahl 抱团度: 重仓股基金覆盖家数 Herfindahl
    # H = Σ(market_share_i^2), market_share_i = fund_count_i / Σ(fund_count_i)
    # 值越大表示抱团越集中 (1=完全一只股, 0=完全分散)
    rows = conn.execute(
        "SELECT stock_code, stock_name, fund_count, hold_value_total "
        "FROM fund_holding_stock WHERE report_date=? ORDER BY hold_value_total DESC LIMIT 100",
        (report_date,),
    ).fetchall()
    total_fund_count = sum(r[2] or 0 for r in rows) or 1
    herf = sum(((r[2] or 0) / total_fund_count) ** 2 for r in rows)
    results["concentration_herfindahl"] = round(herf, 6) if rows else None
    detail["concentration_herfindahl"] = {
        "top10_stocks": [{"code": r[0], "name": r[1], "fund_count": r[2], "value": r[3]}
                          for r in rows[:10]],
        "total_fund_count": total_fund_count,
    }

    # 3. overlap_ratio 重叠度: Top30 重仓股平均基金覆盖家数
    top30 = rows[:30] if len(rows) >= 30 else rows
    if top30:
        overlap = sum(r[2] or 0 for r in top30) / len(top30)
    else:
        overlap = None
    results["overlap_ratio"] = round(overlap, 2) if overlap is not None else None
    detail["overlap_ratio"] = {
        "top30_avg_fund_count": overlap,
        "top30_stocks": [{"code": r[0], "name": r[1], "fund_count": r[2]}
                          for r in top30[:10]],
    }

    # 4. industry_concentration 行业集中度: 全市场行业配置 Herfindahl
    # 聚合所有 fund_industry_alloc 按 industry_name 汇总 weight_pct
    ind_rows = conn.execute(
        "SELECT industry_name, SUM(weight_pct) as total_weight "
        "FROM fund_industry_alloc WHERE report_date=? "
        "GROUP BY industry_name ORDER BY total_weight DESC",
        (report_date,),
    ).fetchall()
    if ind_rows:
        total_w = sum(r[1] or 0 for r in ind_rows) or 1
        ind_herf = sum(((r[1] or 0) / total_w) ** 2 for r in ind_rows)
        results["industry_concentration"] = round(ind_herf, 6)
        detail["industry_concentration"] = {
            "top10_industries": [{"name": r[0], "weight": r[1]} for r in ind_rows[:10]],
            "total_industries": len(ind_rows),
        }
    else:
        results["industry_concentration"] = None
        detail["industry_concentration"] = {"note": "无行业配置数据"}

    # 5. net_redeem_ratio 净申赎率%: 净申赎/期末总份额 × 100
    sc_row = conn.execute(
        "SELECT net_purchase_share, end_total_share, purchase_share, redeem_share "
        "FROM fund_scale_change ORDER BY report_date DESC LIMIT 1"
    ).fetchone()
    if sc_row and sc_row[1] and sc_row[1] != 0:
        net_ratio = (sc_row[0] or 0) / sc_row[1] * 100
        results["net_redeem_ratio"] = round(net_ratio, 4)
        detail["net_redeem_ratio"] = {
            "net_purchase_share": sc_row[0],
            "end_total_share": sc_row[1],
            "purchase_share": sc_row[2],
            "redeem_share": sc_row[3],
        }
    else:
        results["net_redeem_ratio"] = None

    # 6. position_change_ratio 加仓减仓比: 当期vs上期仓位变化（cninfo 源最近两期）
    pos_rows = conn.execute(
        "SELECT report_date, position_pct FROM fund_position_history "
        "WHERE source='cninfo' AND position_pct IS NOT NULL "
        "ORDER BY report_date DESC LIMIT 2"
    ).fetchall()
    if len(pos_rows) >= 2:
        cur_pos = pos_rows[0][1] or 0
        prev_pos = pos_rows[1][1] or 0
        position_change = cur_pos - prev_pos
        results["position_change_ratio"] = round(position_change, 4)
        detail["position_change_ratio"] = {
            "current_date": pos_rows[0][0], "current_position": cur_pos,
            "prev_date": pos_rows[1][0], "prev_position": prev_pos,
            "change_pct": position_change,
        }
    else:
        results["position_change_ratio"] = None

    # 7. top20_adjustment 头部 Top20 调仓: Top20 重仓股环比持股总市值变化%
    cur_top20_value = sum(r[3] or 0 for r in rows[:20]) if len(rows) >= 20 else sum(r[3] or 0 for r in rows)
    # 上一期
    prev_report_row = conn.execute(
        "SELECT MAX(report_date) FROM fund_holding_stock WHERE report_date < ?",
        (report_date,),
    ).fetchone()
    prev_top20_value = None
    if prev_report_row and prev_report_row[0]:
        prev_rows = conn.execute(
            "SELECT hold_value_total FROM fund_holding_stock "
            "WHERE report_date=? ORDER BY hold_value_total DESC LIMIT 20",
            (prev_report_row[0],),
        ).fetchall()
        prev_top20_value = sum(r[0] or 0 for r in prev_rows)
    if cur_top20_value and prev_top20_value and prev_top20_value != 0:
        top20_change = (cur_top20_value - prev_top20_value) / prev_top20_value * 100
        results["top20_adjustment"] = round(top20_change, 4)
        detail["top20_adjustment"] = {
            "current_top20_value": cur_top20_value,
            "prev_top20_value": prev_top20_value,
            "prev_report_date": prev_report_row[0] if prev_report_row else None,
        }
    else:
        results["top20_adjustment"] = None

    # 8. top30_concentration Top30 集中度: Top30 重仓股占全市场重仓市值比例%
    total_value = conn.execute(
        "SELECT SUM(hold_value_total) FROM fund_holding_stock WHERE report_date=?",
        (report_date,),
    ).fetchone()[0]
    top30_value = sum(r[3] or 0 for r in rows[:30]) if len(rows) >= 30 else sum(r[3] or 0 for r in rows)
    if total_value and total_value != 0:
        top30_pct = top30_value / total_value * 100
        results["top30_concentration"] = round(top30_pct, 4)
        detail["top30_concentration"] = {
            "top30_value": top30_value, "total_value": total_value, "pct": top30_pct,
        }
    else:
        results["top30_concentration"] = None

    # 写入 DB
    metric_names = {
        "avg_position": "平均股票仓位%",
        "concentration_herfindahl": "抱团度Herfindahl",
        "overlap_ratio": "重叠度(Top30平均基金覆盖家数)",
        "industry_concentration": "行业集中度Herfindahl",
        "net_redeem_ratio": "净申赎率%",
        "position_change_ratio": "仓位变化(当期-上期,百分点)",
        "top20_adjustment": "Top20调仓环比%",
        "top30_concentration": "Top30集中度%",
    }
    metric_rows = []
    for mid, val in results.items():
        metric_rows.append((
            report_date, mid, metric_names.get(mid, mid),
            val, json.dumps(detail.get(mid), ensure_ascii=False) if detail.get(mid) else None,
            today,
        ))
    conn.executemany(
        "INSERT OR REPLACE INTO fund_metrics"
        "(report_date, metric_id, metric_name, metric_value, detail, fetch_date) "
        "VALUES (?,?,?,?,?,?)",
        metric_rows,
    )
    conn.commit()
    conn.close()
    print(f"[metrics] 8 指标写入: {results}", flush=True)
    return results


# ── 3 pipelines ─────────────────────────────────────────────────────────────────
def pipeline_quarterly(top_n: int = QUARTERLY_TOP_N) -> dict:
    """季度全量 pipeline: 5 汇总 + 头部 top_n 只×2 子页 + 8 指标。

    Args:
      top_n: 头部基金数, 默认 1000（~35min）
    Returns: stats dict
    """
    t0 = time.time()
    print(f"=== pipeline_quarterly(top_n={top_n}) ===", flush=True)
    stats: dict = {"top_n": top_n}

    # 5 汇总
    stats["fund_basic"] = fetch_fund_name()
    stats["fund_position_history"] = fetch_position_lg()
    report_date = _latest_report_dates(1)[0]
    stats["fund_holding_stock"] = fetch_holding_cninfo(report_date)
    stats["fund_hold_structure"] = fetch_hold_structure()
    stats["fund_scale_change"] = fetch_scale_change()

    # 头部 top_n 只 × 2 子页（asset_alloc + industry_alloc）
    funds = universe_top_funds(n=top_n)
    print(f"[quarterly] 头部 {len(funds)} 只逐只跑 G+H 子页 ...", flush=True)
    per_fund_stats = _fetch_per_fund_batch(funds, label="quarterly")
    stats.update(per_fund_stats)

    # 8 指标
    stats["metrics"] = compute_metrics(report_date)

    stats["elapsed_sec"] = round(time.time() - t0, 1)
    print(f"=== pipeline_quarterly 完成: {stats} ===", flush=True)
    return stats


def pipeline_full(top_n: int = FULL_TOP_N) -> dict:
    """全量 pipeline: 9000 只 × 2 子页（凌晨解耦, ~5.25h）。"""
    t0 = time.time()
    print(f"=== pipeline_full(top_n={top_n}) ===", flush=True)
    stats: dict = {"top_n": top_n}
    # 确保有 fund_basic
    conn = get_conn()
    cnt = conn.execute("SELECT COUNT(*) FROM fund_basic").fetchone()[0]
    conn.close()
    if cnt == 0:
        stats["fund_basic"] = fetch_fund_name()
    funds = universe_top_funds(n=top_n)
    print(f"[full] 全量 {len(funds)} 只逐只跑 G+H 子页 ...", flush=True)
    per_fund_stats = _fetch_per_fund_batch(funds, label="full")
    stats.update(per_fund_stats)
    stats["metrics"] = compute_metrics(_latest_report_dates(1)[0])
    stats["elapsed_sec"] = round(time.time() - t0, 1)
    print(f"=== pipeline_full 完成: {stats} ===", flush=True)
    return stats


def pipeline_daily() -> dict:
    """日更 pipeline: fetch_daily_nav + 估算仓位变化（轻量, ~10s）。"""
    t0 = time.time()
    print("=== pipeline_daily() ===", flush=True)
    stats: dict = {}
    stats["fund_daily_nav"] = fetch_daily_nav()
    # 估算仓位变化（用 fund_position_history 最新两期）
    conn = get_conn()
    rows = conn.execute(
        "SELECT report_date, position_pct FROM fund_position_history "
        "WHERE source='cninfo' AND position_pct IS NOT NULL "
        "ORDER BY report_date DESC LIMIT 2"
    ).fetchall()
    if len(rows) >= 2:
        change = (rows[0][1] or 0) - (rows[1][1] or 0)
        stats["position_change_estimate"] = round(change, 4)
    conn.close()
    stats["elapsed_sec"] = round(time.time() - t0, 1)
    print(f"=== pipeline_daily 完成: {stats} ===", flush=True)
    return stats


# ── export ──────────────────────────────────────────────────────────────────────
def export_data() -> tuple[dict, dict, dict, dict, dict]:
    """导出 5 类 JSON: summary / holdings / industry / top20 / asset_alloc。

    Returns: (summary, holdings, industry, top20, asset_alloc)
    """
    conn = get_conn()
    report_date = _latest_report_dates(1)[0]

    # 1. summary: 8 指标 + 元信息
    metric_rows = conn.execute(
        "SELECT metric_id, metric_name, metric_value, detail FROM fund_metrics "
        "WHERE report_date=? ORDER BY metric_id",
        (report_date,),
    ).fetchall()
    metrics_list = [{"metric_id": r[0], "metric_name": r[1],
                     "metric_value": r[2],
                     "detail": json.loads(r[3]) if r[3] else None}
                    for r in metric_rows]
    # 全量仓位轨迹(lg 周频 + cninfo 季报, 含同日双源; 2026-07-20 去 LIMIT 40 截断,
    # 让 range 切换"全部"档能看到完整 2007-2026 共19年数据)
    pos_rows = conn.execute(
        "SELECT report_date, source, position_pct, bond_pct, cash_pct, other_pct, "
        "fund_count, total_net_asset FROM fund_position_history "
        "ORDER BY report_date ASC"
    ).fetchall()
    position_history = [{"report_date": r[0], "source": r[1], "position_pct": r[2],
                         "bond_pct": r[3], "cash_pct": r[4], "other_pct": r[5],
                         "fund_count": r[6], "total_net_asset": r[7]}
                        for r in pos_rows]
    # 最近 4 期净申赎
    sc_rows = conn.execute(
        "SELECT report_date, fund_count, purchase_share, redeem_share, "
        "net_purchase_share, end_total_share, end_net_asset "
        "FROM fund_scale_change ORDER BY report_date DESC LIMIT 20"
    ).fetchall()
    scale_history = [{"report_date": r[0], "fund_count": r[1],
                      "purchase_share": r[2], "redeem_share": r[3],
                      "net_purchase_share": r[4], "end_total_share": r[5],
                      "end_net_asset": r[6]} for r in sc_rows]
    summary = {
        "report_date": report_date,
        "metrics": metrics_list,
        "position_history": position_history,
        "scale_change_history": scale_history,
        "fund_basic_count": conn.execute("SELECT COUNT(*) FROM fund_basic").fetchone()[0],
        "fund_holding_count": conn.execute(
            "SELECT COUNT(*) FROM fund_holding_stock WHERE report_date=?", (report_date,)).fetchone()[0],
        "fund_industry_count": conn.execute(
            "SELECT COUNT(*) FROM fund_industry_alloc WHERE report_date=?", (report_date,)).fetchone()[0],
        "fund_asset_count": conn.execute(
            "SELECT COUNT(DISTINCT fund_code) FROM fund_asset_alloc WHERE report_date=?", (report_date,)).fetchone()[0],
    }

    # prev_report / prev_map: holdings(top100) 与 top20 调仓对比共用, 只查一次
    prev_report = conn.execute(
        "SELECT MAX(report_date) FROM fund_holding_stock WHERE report_date < ?",
        (report_date,),
    ).fetchone()[0]
    prev_map: dict[str, float] = {}
    if prev_report:
        prev_rows = conn.execute(
            "SELECT stock_code, hold_value_total FROM fund_holding_stock WHERE report_date=?",
            (prev_report,),
        ).fetchall()
        prev_map = {r[0]: r[1] for r in prev_rows}

    # 2. holdings: Top100 重仓股(含调仓: 当期 hold_value_total vs 上期 prev_value; Q3: 扩到100)
    holding_rows = conn.execute(
        "SELECT stock_code, stock_name, fund_count, hold_share_total, hold_value_total "
        "FROM fund_holding_stock WHERE report_date=? "
        "ORDER BY hold_value_total DESC LIMIT 100",
        (report_date,),
    ).fetchall()
    holdings = {
        "report_date": report_date,
        "prev_report_date": prev_report,
        "top100": [{"stock_code": r[0], "stock_name": r[1], "fund_count": r[2],
                   "hold_share_total": r[3], "hold_value_total": r[4],
                   "prev_value": prev_map.get(r[0]),
                   "change_pct": round((r[4] - prev_map.get(r[0], 0)) / prev_map.get(r[0], 1) * 100, 2)
                                 if prev_map.get(r[0]) else None}
                  for r in holding_rows],
    }

    # 3. industry: 行业聚合（全市场汇总）
    ind_rows = conn.execute(
        "SELECT industry_name, SUM(weight_pct) as total_weight, SUM(hold_value) as total_value, "
        "COUNT(DISTINCT fund_code) as fund_count "
        "FROM fund_industry_alloc WHERE report_date=? "
        "GROUP BY industry_name ORDER BY total_weight DESC",
        (report_date,),
    ).fetchall()
    industry = {
        "report_date": report_date,
        "industries": [{"industry_name": r[0], "total_weight": r[1],
                        "total_value": r[2], "fund_count": r[3]}
                       for r in ind_rows],
    }

    # 4. top20: Top20 重仓股调仓对比(复用 prev_map; 指标口径保持 LIMIT 20 不变, Q3 要求)
    cur_rows = conn.execute(
        "SELECT stock_code, stock_name, fund_count, hold_value_total "
        "FROM fund_holding_stock WHERE report_date=? "
        "ORDER BY hold_value_total DESC LIMIT 20",
        (report_date,),
    ).fetchall()
    top20 = {
        "report_date": report_date,
        "prev_report_date": prev_report,
        "top20": [{"stock_code": r[0], "stock_name": r[1], "fund_count": r[2],
                   "current_value": r[3],
                   "prev_value": prev_map.get(r[0]),
                   "change_pct": round((r[3] - prev_map.get(r[0], 0)) / prev_map.get(r[0], 1) * 100, 2)
                                 if prev_map.get(r[0]) else None}
                  for r in cur_rows],
    }

    # 5. asset_alloc: 头部基金资产配置分布（聚合统计）
    aa_rows = conn.execute(
        "SELECT AVG(stock_pct) as avg_stock, AVG(bond_pct) as avg_bond, "
        "AVG(cash_pct) as avg_cash, COUNT(*) as fund_count "
        "FROM fund_asset_alloc WHERE report_date=?",
        (report_date,),
    ).fetchone()
    asset_alloc = {
        "report_date": report_date,
        "avg_stock_pct": aa_rows[0], "avg_bond_pct": aa_rows[1],
        "avg_cash_pct": aa_rows[2], "fund_count": aa_rows[3],
    }

    conn.close()
    return summary, holdings, industry, top20, asset_alloc


def export_json_files() -> None:
    """写 5 类 JSON 到 static-site/data/。"""
    summary, holdings, industry, top20, asset_alloc = export_data()
    STATIC_DATA_DIR.mkdir(parents=True, exist_ok=True)
    files = {
        "public_fund_summary.json": summary,
        "public_fund_holdings.json": holdings,
        "public_fund_industry.json": industry,
        "public_fund_top20.json": top20,
        "public_fund_asset_alloc.json": asset_alloc,
    }
    for fname, data in files.items():
        (STATIC_DATA_DIR / fname).write_text(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")
        size = (STATIC_DATA_DIR / fname).stat().st_size
        print(f"  [export] {fname} ({size} bytes)", flush=True)
    print(f"[export] 5 个 JSON 写入 -> {STATIC_DATA_DIR}", flush=True)


# ── CLI ─────────────────────────────────────────────────────────────────────────
def main():
    init_db()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "quarterly"
    if cmd not in ("quarterly", "full", "daily", "metrics", "export", "backfill", "check-fresh"):
        print(__doc__)
        print(f"\n用法: python -m app.collector.public_fund <command>")
        print(f"  quarterly       季度全量(5汇总+top1000×2子页+8指标, ~35min)")
        print(f"  full            全量9000只×2子页(~5.25h, 凌晨解耦)")
        print(f"  daily           日更净值+估算仓位变化(~10s)")
        print(f"  metrics         重算8指标")
        print(f"  export          只导出5类JSON")
        print(f"  backfill --start 20240101 --end 20241231  历史重仓股回填")
        print(f"  check-fresh [--top N]  数据新鲜度闸门(exit 0=应跑, 1=无新数据跳过)")
        sys.exit(1)

    # 进程互斥（quarterly/full/daily/backfill 持锁, metrics/export/check-fresh 不需要）
    if cmd in ("quarterly", "full", "daily", "backfill"):
        if not _acquire_lock(nonblock=True):
            print(f"[public_fund] 已有进程在跑（{LOCK_PATH}），跳过", file=sys.stderr)
            return

    if cmd == "quarterly":
        # 支持 --top N 覆盖默认 1000（小样本验证用）
        top_n = QUARTERLY_TOP_N
        for i, a in enumerate(sys.argv[2:], 2):
            if a == "--top" and i + 1 < len(sys.argv):
                top_n = int(sys.argv[i + 1])
        stats = pipeline_quarterly(top_n=top_n)
        export_json_files()
        print(f"[quarterly] stats: {stats}", flush=True)
    elif cmd == "full":
        top_n = FULL_TOP_N
        for i, a in enumerate(sys.argv[2:], 2):
            if a == "--top" and i + 1 < len(sys.argv):
                top_n = int(sys.argv[i + 1])
        stats = pipeline_full(top_n=top_n)
        export_json_files()
        print(f"[full] stats: {stats}", flush=True)
    elif cmd == "daily":
        stats = pipeline_daily()
        print(f"[daily] stats: {stats}", flush=True)
    elif cmd == "metrics":
        # 支持自定义 report_date
        report_date = None
        for i, a in enumerate(sys.argv[2:], 2):
            if a == "--date" and i + 1 < len(sys.argv):
                report_date = sys.argv[i + 1].replace("-", "")
        results = compute_metrics(report_date)
        print(f"[metrics] results: {results}", flush=True)
    elif cmd == "export":
        export_json_files()
    elif cmd == "backfill":
        # 历史重仓股回填: --start --end 指定报告期范围
        start = end = None
        for i, a in enumerate(sys.argv[2:], 2):
            if a == "--start" and i + 1 < len(sys.argv):
                start = sys.argv[i + 1].replace("-", "")
            elif a == "--end" and i + 1 < len(sys.argv):
                end = sys.argv[i + 1].replace("-", "")
        # 生成半年报/年报报告期列表
        if not start:
            start = "20200101"
        if not end:
            end = _latest_report_dates(1)[0]
        sy, sm = int(start[:4]), int(start[4:6])
        ey, em = int(end[:4]), int(end[4:6])
        dates: list[str] = []
        y, m = sy, sm
        while (y, m) <= (ey, em):
            if m <= 6:
                dates.append(f"{y-1 if m<=6 and m>=1 else y}1231" if m < 7 else f"{y}0630")
            if m >= 7:
                dates.append(f"{y}0630")
            # 推进到下一年
            y += 1
            m = 1
            if (y, m) > (ey, em):
                break
        # 简化: 直接生成年末+半年末
        dates = []
        for y in range(int(start[:4]), int(end[:4]) + 1):
            dates.append(f"{y}0630")
            dates.append(f"{y}1231")
        dates = [d for d in dates if start <= d <= end]
        print(f"[backfill] 报告期: {dates}", flush=True)
        total = 0
        for d in dates:
            total += fetch_holding_cninfo(d)
        print(f"[backfill] 完成, 共 {total} 行", flush=True)
    elif cmd == "check-fresh":
        # 数据新鲜度闸门(只读检查, 不持锁): exit 0=有新数据应跑, 1=无新数据跳过
        # --top N 覆盖率阈值(默认 1000 quarterly, full 用 9000)
        top_n = QUARTERLY_TOP_N
        for i, a in enumerate(sys.argv[2:], 2):
            if a == "--top" and i + 1 < len(sys.argv):
                top_n = int(sys.argv[i + 1])
        should_run, reason = has_new_data(top_n=top_n)
        print(f"[fresh] should_run={should_run} {reason}", flush=True)
        sys.exit(0 if should_run else 1)


if __name__ == "__main__":
    main()
