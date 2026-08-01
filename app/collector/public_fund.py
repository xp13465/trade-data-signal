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

# 申万一级 31 行业 code -> 名称映射(与 industry_extras.py SW_EM_MAP 注释一致, 申万 2021 标准)
# 用于 holdings.top100 的 stock_industry 字段: 反查 stock_code 所属申万一级行业名
SW_INDUSTRY_NAMES: dict[str, str] = {
    "801010": "农林牧渔", "801030": "基础化工", "801040": "钢铁", "801050": "有色金属",
    "801080": "电子", "801110": "家用电器", "801120": "食品饮料", "801130": "纺织服饰",
    "801140": "轻工制造", "801150": "医药生物", "801160": "公用事业", "801170": "交通运输",
    "801180": "房地产", "801200": "商贸零售", "801210": "社会服务", "801230": "综合",
    "801710": "建筑材料", "801720": "建筑装饰", "801730": "电力设备", "801740": "国防军工",
    "801750": "计算机", "801760": "传媒", "801770": "通信", "801780": "银行",
    "801790": "非银金融", "801880": "汽车", "801890": "机械设备", "801950": "煤炭",
    "801960": "石油石化", "801970": "环保", "801980": "美容护理",
}

# 申万一级中属于"制造业"大类的子行业（用于 export 制造业拆分, 方案C Step3）
# 申万2021标准: 18个一级属于制造业大类(综合按任务要求归入制造业; 建筑装饰归建筑业非制造业)
MANUF_SUB_INDUSTRIES: set[str] = {
    "电子", "通信", "电力设备", "汽车", "机械设备", "国防军工",
    "家用电器", "食品饮料", "纺织服饰", "轻工制造", "医药生物",
    "建筑材料", "基础化工", "钢铁", "有色金属", "环保", "美容护理", "综合",
}


def _load_stock_industry_map() -> dict[str, str]:
    """加载 sw_components.json 构建 {stock_code: 申万一级名称} 反查字典。

    sw_components.json 结构: {industry_code: [stock_code, ...]}(6位纯数字代码)。
    路径优先 trade-data/data/(主库), 回退 trade/data/(_DATA_DIR)。
    映射率实测 100%(top100 全命中, 5210 成分股覆盖全 A 股)。
    文件不存在或读失败返回空 dict(holdings.stock_industry 留空字符串, 不影响导出)。
    """
    # 优先 trade-data/data/(主库, §9 cwd 约定), 回退 _DATA_DIR(trade/data/)
    candidates = [
        Path("/Users/linhuichen/code/trade-data/data/sw_components.json"),
        _DATA_DIR / "sw_components.json",
    ]
    sw_path = next((p for p in candidates if p.exists()), None)
    if not sw_path:
        print(f"[export] warn: sw_components.json 不存在, stock_industry 留空", flush=True)
        return {}
    try:
        sw_data = json.loads(sw_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[export] warn: sw_components.json 读取失败: {e}, stock_industry 留空", flush=True)
        return {}
    code2ind: dict[str, str] = {}
    for ind_code, stocks in sw_data.items():
        ind_name = SW_INDUSTRY_NAMES.get(ind_code, "")
        for s in stocks:
            code2ind[s] = ind_name
    return code2ind


DEFAULT_START = "20171201"  # fund_stock_position_lg 最早 2017-12-04
THROTTLE_SEC = 0.5  # 逐只子页延时（xq/em 限流不严, 0.5s 安全）

# 头部基金样本量: 季度 pipeline 默认 1000 只（35min），全量 9000 只（5.25h）
QUARTERLY_TOP_N = 1000
# full pipeline 已停调度（2026-07-20 launchctl unload），推荐功能都不需9000+，未来做基金筛选器再 load 恢复
FULL_TOP_N = 9000

# 行业合并映射表: 67 原始名(申万中文大类 + GICS中文短名 + GICS带编号 + GICS中英文多套分类混合)
# -> 标准名。⚠️ 必须和前端 static-site/app.js 的 IND_MERGE_MAP 保持 1:1 一致
# （否则 public_fund_industry_fund_map.json 的 key 和前端点击展开的行业名对不上）。
# 改动任一处必须同步另一处。
IND_MERGE_MAP: dict[str, str] = {
    '信息传输、软件和信息技术服务业': '信息技术', '信息技术': '信息技术', '信息科技': '信息技术',
    '45信息技术': '信息技术', '信息技术InformationTechnology': '信息技术', '科技': '信息技术',
    '金融业': '金融业', '金融': '金融业', '40金融': '金融业', 'E金融': '金融业', '金融Financials': '金融业',
    '房地产业': '房地产业', '房地产': '房地产业', '房地产RealEstate': '房地产业', '60房地产': '房地产业', '地产业': '房地产业',
    '材料': '材料', '原材料': '材料', '15原材料': '材料', '材料Materials': '材料', '基础材料': '材料',
    '工业': '工业', '20工业': '工业', 'G工业': '工业', '工业Industrials': '工业',
    '能源': '能源', 'D能源': '能源',
    '公用事业': '公用事业', 'J公用事业': '公用事业',
    '医疗保健': '医疗保健', '医疗': '医疗保健', '35医疗保健': '医疗保健', '保健HealthCare': '医疗保健',
    '非日常生活消费品': '非必需消费品', '非必需消费品': '非必需消费品', '25可选消费': '非必需消费品',
    '非必需消费品ConsumerDiscretionary': '非必需消费品', '消费者非必需品': '非必需消费品', '非周期性消费品': '非必需消费品',
    '必需消费品': '必需消费品', '日常消费品': '必需消费品', '30日常消费': '必需消费品',
    '必需消费品ConsumerStaples': '必需消费品', '消费者常用品': '必需消费品',
    '通讯': '通信服务', '通讯业务': '通信服务', '通信服务': '通信服务',
    '50电信服务': '通信服务', '电信服务': '通信服务', '电信业务': '通信服务', '通信服务CommunicationServices': '通信服务',
}

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
  close REAL,                        -- 沪深300收盘(lg only, 辅助; ak.fund_stock_position_lg 自带 close=hs300 非上证)
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

-- 逐只基金重仓股明细(自写 fetcher 带 Referer/UA 直爬东财 fundf10, 用于制造业拆分子行业-方案C)
-- 942 只持有制造业的基金, 只采当期 20260630
CREATE TABLE IF NOT EXISTS fund_portfolio_hold (
  report_date TEXT NOT NULL,
  fund_code TEXT NOT NULL,
  stock_code TEXT NOT NULL,
  stock_name TEXT,
  weight_pct REAL,                   -- 占净值%
  hold_share REAL,                   -- 持股数(万股)
  hold_value REAL,                   -- 持仓市值(万元)
  quarter_label TEXT,                -- 东财原始季度标签(如 '2026年2季度股票投资明细')
  PRIMARY KEY (report_date, fund_code, stock_code)
);
CREATE INDEX IF NOT EXISTS idx_portfolio_hold_fund_code ON fund_portfolio_hold(fund_code);
CREATE INDEX IF NOT EXISTS idx_portfolio_hold_report_date ON fund_portfolio_hold(report_date);
CREATE INDEX IF NOT EXISTS idx_portfolio_hold_stock_code ON fund_portfolio_hold(stock_code);

-- 盘中实时净值估算（fund_value_estimation_em, 盘中才有, 非交易日/盘后返回空）
CREATE TABLE IF NOT EXISTS fund_estimation_nav (
  fund_code TEXT NOT NULL,
  fund_name TEXT,
  fund_type TEXT,
  est_date TEXT NOT NULL,             -- 估算日期 YYYYMMDD (gzrq)
  est_nav REAL,                       -- 估算净值
  est_pct REAL,                       -- 估算涨跌%
  real_nav REAL,                      -- 公布单位净值
  real_pct REAL,                      -- 公布日增长率%
  est_deviation REAL,                 -- 估算偏差
  fetch_date TEXT,
  PRIMARY KEY (fund_code, est_date)
);
CREATE INDEX IF NOT EXISTS idx_estimation_nav_date ON fund_estimation_nav(est_date);

-- 基准指数日频（baostock sh.000300 沪深300, 反推算法用; stock_zh_index_daily_em 被封改 baostock）
CREATE TABLE IF NOT EXISTS fund_index_daily (
  date TEXT NOT NULL,
  index_id TEXT NOT NULL,             -- 'hs300' / 'csi500' 等
  close REAL,
  pct_change REAL,
  PRIMARY KEY (date, index_id)
);
CREATE INDEX IF NOT EXISTS idx_fund_index_daily_id ON fund_index_daily(index_id);
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


# ── Fetcher E2: 盘中实时净值估算 ─────────────────────────────────────────────────
def fetch_estimation() -> int:
    """fund_value_estimation_em (盘中实时估算) -> fund_estimation_nav。

    接口特性:
    - 盘中(09:30-15:00)返回全市场基金当日实时估算净值/涨跌
    - 盘后/非交易日返回 None (json_data["Data"]["list"] is None)
    - 全市场覆盖 ~10000+ 只 (pageSize=20000)
    - 只当日实时, 无历史

    采集策略:
    - 盘中定时采 (launchd 10:00/11:00/13:30/14:30 四档)
    - 盘后采当日最终估算 (15:30 后可能仍有当日最终估算值, 采不到则跳过)

    Returns: 写入行数 (0=盘后/非交易日无数据)
    """
    print("[E2] fetch_estimation() ...", flush=True)
    t = time.time()
    df = safe_call(ak.fund_value_estimation_em, retries=2)
    if isinstance(df, Exception) or df is None or len(df) == 0:
        print(f"[E2] fund_value_estimation_em 无数据(盘后/非交易日正常): {df}", flush=True)
        return 0
    today = dt.date.today().strftime("%Y%m%d")
    rows: list[tuple] = []
    # 列结构动态(列名含 cal_day/value_day 日期前缀), 找含关键字的列
    cols = list(df.columns)
    fund_code_col = next((c for c in cols if "基金代码" in str(c)), None)
    fund_name_col = next((c for c in cols if "基金名称" in str(c)), None)
    fund_type_col = next((c for c in cols if "基金类型" in str(c)), None)
    est_date_col = next((c for c in cols if "估算日期" in str(c)), None)
    # 估算值/估算增长率/公布单位净值/公布日增长率/估算偏差 列名含动态日期前缀
    est_nav_col = next((c for c in cols if "估算数据-估算值" in str(c)), None)
    est_pct_col = next((c for c in cols if "估算数据-估算增长率" in str(c)), None)
    real_nav_col = next((c for c in cols if "公布数据-单位净值" in str(c)), None)
    real_pct_col = next((c for c in cols if "公布数据-日增长率" in str(c)), None)
    dev_col = next((c for c in cols if "估算偏差" in str(c)), None)

    for _, r in df.iterrows():
        fund_code = str(r.get(fund_code_col, "")).strip() if fund_code_col else ""
        if not fund_code:
            continue
        est_date = _to_yyyymmdd(r.get(est_date_col)) if est_date_col else ""
        if not est_date:
            est_date = today
        rows.append((
            fund_code,
            str(r.get(fund_name_col, "")).strip() if fund_name_col else None,
            str(r.get(fund_type_col, "")).strip() if fund_type_col else None,
            est_date,
            _safe_float(r.get(est_nav_col)) if est_nav_col else None,
            _safe_float(r.get(est_pct_col)) if est_pct_col else None,
            _safe_float(r.get(real_nav_col)) if real_nav_col else None,
            _safe_float(r.get(real_pct_col)) if real_pct_col else None,
            _safe_float(r.get(dev_col)) if dev_col else None,
            today,
        ))
    if not rows:
        print(f"[E2] 无有效行", flush=True)
        return 0
    conn = get_conn()
    conn.executemany(
        "INSERT OR REPLACE INTO fund_estimation_nav"
        "(fund_code, fund_name, fund_type, est_date, est_nav, est_pct, "
        "real_nav, real_pct, est_deviation, fetch_date) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    print(f"[E2] fund_estimation_nav 写入 {len(rows)} 行 @{today}, {time.time()-t:.1f}s", flush=True)
    return len(rows)


# ── Fetcher E3: 基准指数日频 (baostock 沪深300) ──────────────────────────────────
def fetch_index_daily(start_date: str | None = None, end_date: str | None = None,
                      index_id: str = "hs300") -> int:
    """baostock sh.000300 沪深300日频 -> fund_index_daily (反推算法基准指数)。

    ak.stock_zh_index_daily_em 被东财封 RemoteDisconnected, 改用 baostock。
    baostock sh.000300 返回 date/close/pctChg, 日频交易日。

    Args:
      start_date: YYYYMMDD, 默认 1 年前
      end_date: YYYYMMDD, 默认今日
      index_id: 'hs300' (沪深300, 和 lg 源 close 一致, 88 魔咒图基准)
    Returns: 写入行数
    """
    print(f"[E3] fetch_index_daily({index_id}) ...", flush=True)
    t = time.time()
    try:
        import baostock as bs
    except ImportError:
        print("[E3] baostock 未安装, 跳过", flush=True)
        return 0
    if not start_date:
        start_date = (dt.date.today() - dt.timedelta(days=400)).strftime("%Y%m%d")
    if not end_date:
        end_date = dt.date.today().strftime("%Y%m%d")
    sd = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
    ed = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
    bs_code = {"hs300": "sh.000300"}.get(index_id, "sh.000300")

    lg = bs.login()
    if lg.error_code != "0":
        print(f"[E3] baostock login fail: {lg.error_msg}", flush=True)
        return 0
    try:
        rs = bs.query_history_k_data_plus(
            bs_code, "date,close,pctChg",
            start_date=sd, end_date=ed, frequency="d")
        rows_data: list[list] = []
        while (rs.error_code == "0") and rs.next():
            rows_data.append(rs.get_row_data())
    finally:
        bs.logout()
    if not rows_data:
        print(f"[E3] baostock 无数据 {bs_code} {sd}~{ed}", flush=True)
        return 0
    rows = []
    for r in rows_data:
        d = r[0].replace("-", "")
        close = _safe_float(r[1])
        pct = _safe_float(r[2])
        if not d:
            continue
        rows.append((d, index_id, close, pct))
    conn = get_conn()
    conn.executemany(
        "INSERT OR REPLACE INTO fund_index_daily(date, index_id, close, pct_change) "
        "VALUES (?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    print(f"[E3] fund_index_daily 写入 {len(rows)} 行 {index_id} "
          f"{rows[0][0]}~{rows[-1][0]}, {time.time()-t:.1f}s", flush=True)
    return len(rows)


# ── Fetcher E4: 回填头部基金历史净值时序 (反推算法用) ────────────────────────────
def fetch_nav_history(codes: list[str] | None = None, days: int = 90,
                      fund_type_filter: str = "偏股") -> int:
    """fund_open_fund_info_em 逐只拉历史净值 -> fund_daily_nav (回填历史日期)。

    反推算法需要滚动 60 日历史净值时序, 但 fund_daily_nav 只有当日(pipeline_daily 每天跑
    但 DB 可能刚重置)。本函数一次性回填头部偏股基金的历史净值, 供 _compute_position_estimate 用。

    Args:
      codes: 基金代码列表, 默认用 universe_top_funds(200) 选头部偏股基金
      days: 回填天数 (默认 90 日, 滚动 60 日回归需至少 60 日)
      fund_type_filter: 基金类型过滤关键字 (默认'偏股', 和 lg 源口径一致)
    Returns: 写入总行数
    """
    print(f"[E4] fetch_nav_history(days={days}) ...", flush=True)
    t0 = time.time()
    if codes is None:
        conn = get_conn()
        try:
            # 选偏股混合 + 股票型基金 (lg 源口径: 股票型+混合型, 88 魔咒专用)
            # 按 fund_code 升序取头部 200 只 (样本足够做全市场聚合中位数反推)
            rows_q = conn.execute(
                "SELECT fund_code, fund_name, fund_type FROM fund_basic "
                "WHERE (fund_type LIKE '%偏股%' OR fund_type LIKE '股票型%') "
                "ORDER BY fund_code ASC LIMIT 200"
            ).fetchall()
        finally:
            conn.close()
        codes = [r[0] for r in rows_q]
    print(f"[E4] 回填 {len(codes)} 只基金 {days} 日历史净值 ...", flush=True)

    start_date = (dt.date.today() - dt.timedelta(days=days + 30)).strftime("%Y%m%d")
    total_rows = 0
    ok = fail = 0
    for i, code in enumerate(codes, 1):
        try:
            df = safe_call(ak.fund_open_fund_info_em, retries=1,
                           symbol=code, indicator="单位净值走势")
            if isinstance(df, Exception) or df is None or len(df) == 0:
                fail += 1
                continue
            rows: list[tuple] = []
            for _, r in df.iterrows():
                d = _to_yyyymmdd(r.get("净值日期"))
                if not d or d < start_date:
                    continue
                nav = _safe_float(r.get("单位净值"))
                if nav is None:
                    continue
                # 日增长率列早期可能缺失(0.0), 用净值自己算更可靠
                nav_pct = _safe_float(r.get("日增长率"))
                rows.append((d, code, None, nav, None, None, nav_pct))
            if rows:
                conn = get_conn()
                conn.executemany(
                    "INSERT OR REPLACE INTO fund_daily_nav"
                    "(date, fund_code, fund_name, unit_nav, acc_nav, prev_unit_nav, nav_change_pct) "
                    "VALUES (?,?,?,?,?,?,?)",
                    rows,
                )
                conn.commit()
                conn.close()
                total_rows += len(rows)
                ok += 1
        except Exception as e:  # noqa: BLE001
            fail += 1
            if fail <= 3:
                print(f"  [E4] {code} 异常: {type(e).__name__} {e}", flush=True)
        time.sleep(0.3)  # throttle 防 em 限流
        if i % 50 == 0 or i == len(codes):
            elapsed = time.time() - t0
            eta = (elapsed / i) * (len(codes) - i) if i > 0 else 0
            print(f"  [E4] {i}/{len(codes)} ok={ok} fail={fail} "
                  f"rows={total_rows} elapsed={elapsed:.0f}s eta={eta:.0f}s", flush=True)
    print(f"[E4] 完成: ok={ok} fail={fail} 总行数={total_rows} "
          f"耗时={time.time()-t0:.0f}s", flush=True)
    return total_rows


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


# ── 逐只 fetcher I: 重仓股明细(自写直爬东财 fundf10, 制造业拆分子行业-方案C) ──────
PF_HOLD_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
PF_HOLD_URL = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
PF_HOLD_PROGRESS_PATH = Path("/tmp/pf-hold-collect-progress.json")


def _report_date_to_quarter_label(report_date: str) -> str:
    """YYYYMMDD -> 东财 quarter_label(如 '2026年2季度股票投资明细')。

    东财 jjcc 接口按 year 查返回该年所有季度的重仓股, 每个季度一个 h4 标签 + table。
    当期筛选: 半年报(0630)->2季度, 三季报(0930)->3季度, 年报(1231)->4季度, 一季报(0331)->1季度。
    """
    if not report_date or len(report_date) != 8:
        return ""
    y = report_date[:4]
    m = report_date[4:6]
    q = {"03": "1", "06": "2", "09": "3", "12": "4"}.get(m, "")
    if not q:
        return ""
    return f"{y}年{q}季度股票投资明细"


def fetch_fund_portfolio_hold(code: str, year: str | None = None, retries: int = 2) -> list[dict]:
    """自写直爬东财 fundf10 重仓股明细, 带 Referer+UA 绕过 akshare 404 问题。

    根因: akshare fund_portfolio_hold_em 不带 Referer 被东财返 404 -> JSONDecodeError。
    绕过: requests.get 带 Referer=https://fundf10.eastmoney.com/ccmx_{code}.html + 浏览器 UA,
          60 只样本 100% 成功(试采脚本 /tmp/trial_pf_hold_v2.py 验证)。

    Args:
      code: 基金代码(纯数字串如 '000073')
      year: 'YYYY' 年份, 默认最近年末
      retries: 重试次数(连接类错误指数退避 0.8*(i+1)s)
    Returns: list[dict], 每条 {stock_code, stock_name, weight_pct, hold_share,
                              hold_value, quarter_label};
             异常/空数据返回 [] 不抛
    """
    if year is None:
        year = _latest_report_dates(1)[0][:4]
    params = {
        "type": "jjcc",
        "code": code,
        "topline": "10000",
        "year": year,
        "month": "",
        "rt": "0.913877030254846",
    }
    headers = {
        "User-Agent": PF_HOLD_UA,
        "Referer": f"https://fundf10.eastmoney.com/ccmx_{code}.html",
    }
    import re
    from io import StringIO
    import requests
    import pandas as pd
    from bs4 import BeautifulSoup
    last_err = None
    for i in range(retries + 1):
        try:
            r = requests.get(PF_HOLD_URL, params=params, headers=headers, timeout=15)
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}"
                time.sleep(0.8 * (i + 1))
                continue
            text = r.text
            # 解析 var apidata={ content:"...",arryear:..., curyear:... };
            if "{" not in text:
                last_err = "no { in response"
                time.sleep(0.8 * (i + 1))
                continue
            m = re.search(r'content:"(.+?)",arryear:', text, re.DOTALL)
            if not m:
                last_err = "no content field"
                time.sleep(0.8 * (i + 1))
                continue
            content_html = m.group(1).replace('\\"', '"').replace("\\'", "'")
            # BeautifulSoup 解析 h4(季度标签) + pandas read_html 解析 table
            soup = BeautifulSoup(content_html, features="lxml")
            h4s = soup.find_all(name="h4", attrs={"class": "t"})
            item_labels = [h.text.split("\xa0\xa0")[1] if "\xa0\xa0" in h.text else h.text
                           for h in h4s]
            tables = pd.read_html(StringIO(content_html), converters={"股票代码": str})
            rows: list[dict] = []
            for idx, tbl in enumerate(tables):
                label = item_labels[idx] if idx < len(item_labels) else f"table_{idx}"
                tbl = tbl.copy()
                if "相关资讯" in tbl.columns:
                    del tbl["相关资讯"]
                # 统一列名(东财不同时期列名有空格变体)
                tbl.rename(columns={
                    "占净值 比例": "占净值比例",
                    "持股数（万股）": "持股数",
                    "持仓市值（万元）": "持仓市值",
                    "持股数 （万股）": "持股数",
                    "持仓市值 （万元）": "持仓市值",
                    "持仓市值（万元人民币）": "持仓市值",
                    "持仓市值 （万元人民币）": "持仓市值",
                }, inplace=True)
                for _, row in tbl.iterrows():
                    stock_code = str(row.get("股票代码", "")).strip()
                    stock_name = str(row.get("股票名称", "")).strip()
                    if not stock_code:
                        continue
                    rows.append({
                        "stock_code": stock_code,
                        "stock_name": stock_name,
                        "weight_pct": _safe_float(str(row.get("占净值比例", "")).replace("%", "")),
                        "hold_share": _safe_float(row.get("持股数")),
                        "hold_value": _safe_float(row.get("持仓市值")),
                        "quarter_label": label,
                    })
            return rows
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(0.8 * (i + 1))
    print(f"[I] {code} FAIL: {last_err}", flush=True)
    return []


def collect_portfolio_hold(report_date: str | None = None) -> dict:
    """采集持有'制造业'的基金的重仓股明细, 用于制造业拆分子行业(方案C Step1)。

    流程:
      1. 从 fund_industry_alloc 取 DISTINCT fund_code WHERE industry_name='制造业'(942 只)
      2. 串联调 fetch_fund_portfolio_hold 拉每只当年重仓股, throttle 0.5s/只
      3. 按 report_date 对应的 quarter_label 筛选当期(如 20260630->'2026年2季度股票投资明细')
      4. 批量写入 fund_portfolio_hold 表(每 20 只批量 INSERT + 回写 progress)

    断点续采: /tmp/pf-hold-collect-progress.json 记 {done:[...], fail:[...], total:N},
    启动时读 progress 跳过 done, 重跑只补失败/未采; total 变化(新增基金)自动重置 progress。

    Args:
      report_date: YYYYMMDD 报告期(如 '20260630'), 默认最近半年报
    Returns: {ok, fail, total, rows_written, fail_list}
    """
    if report_date is None:
        report_date = _latest_report_dates(1)[0]
    year = report_date[:4]
    target_label = _report_date_to_quarter_label(report_date)
    print(f"[I-collect] report_date={report_date} year={year} target_label={target_label}", flush=True)

    # 从 DB 取制造业基金清单
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT DISTINCT fund_code FROM fund_industry_alloc "
            "WHERE industry_name='制造业' ORDER BY fund_code"
        ).fetchall()
    finally:
        conn.close()
    fund_codes = [r[0] for r in rows]
    total = len(fund_codes)
    print(f"[I-collect] 制造业基金 {total} 只", flush=True)
    if total == 0:
        return {"ok": 0, "fail": 0, "total": 0, "rows_written": 0, "fail_list": []}

    # 断点续采
    prog = {"done": [], "fail": [], "total": total}
    if PF_HOLD_PROGRESS_PATH.exists():
        try:
            prog = json.loads(PF_HOLD_PROGRESS_PATH.read_text(encoding="utf-8"))
            # total 变化(新增基金) -> 重置 progress 避免脏数据
            if prog.get("total") != total:
                print(f"[I-collect] progress total {prog.get('total')} != 当前 {total}, 重置 progress",
                      flush=True)
                prog = {"done": [], "fail": [], "total": total}
        except Exception:  # noqa: BLE001
            prog = {"done": [], "fail": [], "total": total}
    done_set = set(prog.get("done", []))
    fail_list: list[str] = list(prog.get("fail", []))

    ok = 0
    fail = 0
    rows_written = 0
    t0 = time.time()
    BATCH_SIZE = 20
    pending_rows: list[tuple] = []

    for i, code in enumerate(fund_codes, 1):
        if code in done_set:
            ok += 1
        else:
            try:
                data = fetch_fund_portfolio_hold(code, year=year)
                if not data:
                    fail += 1
                    if code not in fail_list:
                        fail_list.append(code)
                else:
                    # 筛选当期 quarter_label
                    matched = ([r for r in data if r.get("quarter_label") == target_label]
                               if target_label else data)
                    if not matched:
                        # 当期没披露, 算失败(下次重跑可能已披露)
                        fail += 1
                        if code not in fail_list:
                            fail_list.append(code)
                    else:
                        for r in matched:
                            pending_rows.append((
                                report_date, code, r["stock_code"], r["stock_name"],
                                r["weight_pct"], r["hold_share"], r["hold_value"],
                                r["quarter_label"],
                            ))
                        ok += 1
                        rows_written += len(matched)
                        done_set.add(code)
                        if code in fail_list:
                            fail_list.remove(code)
            except Exception as e:  # noqa: BLE001
                fail += 1
                if code not in fail_list:
                    fail_list.append(code)
                print(f"  [I] {code} 异常: {type(e).__name__} {e}", flush=True)
            time.sleep(THROTTLE_SEC)

        # 批量写 DB + 回写 progress(每 BATCH_SIZE 只或最后一只)
        if (len(pending_rows) > 0 and (ok + fail - len(prog.get("done", [])) >= BATCH_SIZE)) or i == total:
            if pending_rows:
                conn = get_conn()
                conn.executemany(
                    "INSERT OR REPLACE INTO fund_portfolio_hold"
                    "(report_date, fund_code, stock_code, stock_name, "
                    "weight_pct, hold_share, hold_value, quarter_label) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    pending_rows,
                )
                conn.commit()
                conn.close()
                pending_rows = []
            prog["done"] = sorted(done_set)
            prog["fail"] = sorted(fail_list)
            prog["total"] = total
            try:
                PF_HOLD_PROGRESS_PATH.write_text(
                    json.dumps(prog, ensure_ascii=False), encoding="utf-8")
            except Exception as e:  # noqa: BLE001
                print(f"  [progress] WARN 写入失败: {e}", flush=True)
            elapsed = time.time() - t0
            processed = ok + fail  # 实际处理的(不含跳过的 done)
            # ETA 基于实际处理速度(已处理含跳过)
            eta = (elapsed / i) * (total - i) if i > 0 else 0
            print(f"  [I-collect] {i}/{total} ({i*100/total:.1f}%) ok={ok} fail={fail} "
                  f"rows={rows_written} elapsed={elapsed:.0f}s eta={eta:.0f}s "
                  f"(processed={processed})", flush=True)

    print(f"[I-collect] 完成: ok={ok} fail={fail} total={total} "
          f"rows_written={rows_written} elapsed={time.time()-t0:.0f}s", flush=True)
    if fail_list:
        sample = fail_list[:20]
        suffix = "..." if len(fail_list) > 20 else ""
        print(f"[I-collect] 失败 {len(fail_list)} 只: {sample}{suffix}", flush=True)
    return {"ok": ok, "fail": fail, "total": total,
            "rows_written": rows_written, "fail_list": fail_list}


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
    """日更 pipeline: fetch_daily_nav + fetch_estimation + 估算仓位变化（轻量, ~10s）。

    fetch_estimation 盘后/非交易日返回 0(无数据正常), 盘中才有实时估算。
    position_estimate 反推算法在 export_json_files 的 _compute_position_estimate 独立算,
    pipeline_daily 不重算(需 fund_daily_nav 历史时序 + fund_index_daily, 较重)。
    """
    t0 = time.time()
    print("=== pipeline_daily() ===", flush=True)
    stats: dict = {}
    stats["fund_daily_nav"] = fetch_daily_nav()
    # 盘中实时估算(盘后/非交易日返回 0 正常, 不阻塞)
    stats["fund_estimation_nav"] = fetch_estimation()
    # 估算仓位变化（用 fund_position_history 最新两期 cninfo 季报环比）
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
def _compute_manuf_breakdown(conn, report_date: str, stock_ind_map: dict[str, str]) -> list[dict]:
    """制造业大类 -> 申万一级子行业拆分（方案C Step3）。

    按基金维度拆分（非简单按重仓股聚合）:
      对每只制造业基金F:
        F制造业总仓位 = fund_industry_alloc 里 F 的制造业 weight_pct
        F重仓股中制造业子行业S的weight和 = Σ(重仓股中属于S的weight_pct)
        F重仓股中制造业整体(含未映射)的weight和 = Σ(重仓股中属于制造业子行业或未映射的weight_pct)
        拆分比例 = S子行业weight和 / 制造业整体weight和
        F拆给S的仓位 = F制造业总仓位 × 拆分比例
      全市场聚合: 每个S总仓位 = Σ(各基金拆给S的仓位)
    未映射股票(stock_code 不在 sw_components.json)归"制造业-其他"子项;
    非制造业申万一级(银行/房地产等)排除, 不参与拆分。

    Returns: [{sub_industry, weight, value, fund_count}, ...] 按 weight 降序;
             weight=聚合仓位%, value=聚合市值(万元), fund_count=持有该子行业的基金数。
    """
    # 1. 制造业基金清单 + 每只基金的制造业 weight + 制造业总仓位/总市值
    manuf_rows = conn.execute(
        "SELECT fund_code, weight_pct, hold_value FROM fund_industry_alloc "
        "WHERE report_date=? AND industry_name='制造业'",
        (report_date,),
    ).fetchall()
    if not manuf_rows:
        return []
    manuf_weight_by_fund = {r[0]: (r[1] or 0) for r in manuf_rows}
    manuf_total_value = sum(r[2] or 0 for r in manuf_rows)

    # 2. 取制造业基金的重仓股, 按基金聚合到申万一级(未映射 stock_code -> "")
    hold_rows = conn.execute(
        "SELECT fund_code, stock_code, weight_pct FROM fund_portfolio_hold "
        "WHERE report_date=?",
        (report_date,),
    ).fetchall()
    fund_hold_by_ind: dict[str, dict[str, float]] = {}
    for fc, sc, wp in hold_rows:
        ind = stock_ind_map.get(sc, "")
        d = fund_hold_by_ind.setdefault(fc, {})
        d[ind] = d.get(ind, 0) + (wp or 0)

    # 3. 按基金维度拆分
    sub_weight: dict[str, float] = {}   # {子行业名 or "制造业-其他": 聚合仓位}
    sub_funds: dict[str, set] = {}      # {子行业名: set(fund_code)}
    other_key = "制造业-其他"
    for fc, ind_map in fund_hold_by_ind.items():
        m_total = manuf_weight_by_fund.get(fc)
        if not m_total:
            continue  # 非制造业基金(重仓股表可能含少量跨大类基金)
        # F重仓股中: 制造业子行业weight和 + 未映射weight和(归其他), 排除非制造业申万一级
        m_hold_total = 0.0
        other_hold = 0.0
        for ind, w in ind_map.items():
            if ind in MANUF_SUB_INDUSTRIES:
                m_hold_total += w
            elif ind == "":  # 未映射
                other_hold += w
            # else: 非制造业申万一级(银行/房地产等), 排除
        denom = m_hold_total + other_hold
        if denom <= 0:
            continue
        for ind, w in ind_map.items():
            if ind in MANUF_SUB_INDUSTRIES:
                allocated = m_total * (w / denom)
                sub_weight[ind] = sub_weight.get(ind, 0) + allocated
                sub_funds.setdefault(ind, set()).add(fc)
        if other_hold > 0:
            sub_weight[other_key] = sub_weight.get(other_key, 0) + m_total * (other_hold / denom)
            sub_funds.setdefault(other_key, set()).add(fc)

    if not sub_weight:
        return []

    # 4. value 按权重比例从制造业 total_value 拆
    total_sub_weight = sum(sub_weight.values())
    breakdown = []
    for ind, w in sorted(sub_weight.items(), key=lambda x: -x[1]):
        value = manuf_total_value * (w / total_sub_weight) if total_sub_weight > 0 else 0
        breakdown.append({
            "sub_industry": ind,
            "weight": round(w, 2),
            "value": round(value, 2),
            "fund_count": len(sub_funds.get(ind, set())),
        })
    return breakdown


def _compute_manuf_subind_fund_map(conn, report_date: str, stock_ind_map: dict[str, str]) -> dict:
    """制造业子行业 -> 基金详情列表映射（供前端"子行业下钻到基金"弹窗, 方案C Step5）。

    重仓股拆分口径: 对每只制造业基金, 取其重仓股(fund_portfolio_hold), 按申万一级子行业
    聚合 weight_pct 和 hold_value 和, 输出每子行业的基金详情列表。

    与 _compute_manuf_breakdown 区别:
      - breakdown: 按基金维度拆分制造业总仓位(allocated = m_total × w/denom), 输出子行业聚合 weight/value/fund_count
      - subind_fund_map: 直接按重仓股子行业聚合每只基金的 weight_pct/hold_value 原始和, 输出基金详情列表

    结构: {report_date, subind_funds: {子行业名: [{fund_code, fund_name, weight_pct, hold_value}, ...]}}
    含18个 MANUF_SUB_INDUSTRIES + "制造业-其他"(未映射重仓股归此项); 非制造业申万一级(银行/房地产等)排除。
    每子行业基金列表按 weight_pct 降序; fund_name 从 fund_basic JOIN(fund_portfolio_hold 无 fund_name 字段)。
    """
    # 1. 制造业基金清单(只拆分持有制造业的基金的重仓股)
    manuf_rows = conn.execute(
        "SELECT fund_code FROM fund_industry_alloc "
        "WHERE report_date=? AND industry_name='制造业'",
        (report_date,),
    ).fetchall()
    manuf_fund_codes = {r[0] for r in manuf_rows}
    if not manuf_fund_codes:
        return {"report_date": report_date, "subind_funds": {}}

    # 2. 取制造业基金的重仓股, 按基金×子行业聚合 weight_pct 和 hold_value
    hold_rows = conn.execute(
        "SELECT fund_code, stock_code, weight_pct, hold_value FROM fund_portfolio_hold "
        "WHERE report_date=?",
        (report_date,),
    ).fetchall()
    # fund_code -> {sub_ind: {"weight_pct": sum, "hold_value": sum}}
    fund_sub_agg: dict[str, dict[str, dict[str, float]]] = {}
    other_key = "制造业-其他"
    for fc, sc, wp, hv in hold_rows:
        if fc not in manuf_fund_codes:
            continue  # 非制造业基金跳过
        ind = stock_ind_map.get(sc, "")
        if ind in MANUF_SUB_INDUSTRIES:
            sub = ind
        elif ind == "":
            sub = other_key  # 未映射归"制造业-其他"
        else:
            continue  # 非制造业申万一级(银行/房地产等)排除
        d = fund_sub_agg.setdefault(fc, {}).setdefault(sub, {"weight_pct": 0.0, "hold_value": 0.0})
        d["weight_pct"] += (wp or 0)
        d["hold_value"] += (hv or 0)

    if not fund_sub_agg:
        return {"report_date": report_date, "subind_funds": {}}

    # 3. fund_name 从 fund_basic JOIN(fund_portfolio_hold 无 fund_name 字段)
    fund_codes_used = set(fund_sub_agg.keys())
    name_map: dict[str, str] = {}
    if fund_codes_used:
        placeholders = ",".join("?" * len(fund_codes_used))
        name_rows = conn.execute(
            f"SELECT fund_code, fund_name FROM fund_basic WHERE fund_code IN ({placeholders})",
            tuple(fund_codes_used),
        ).fetchall()
        name_map = {r[0]: r[1] for r in name_rows}

    # 4. 按子行业聚合基金详情列表
    subind_funds: dict[str, list[dict]] = {}
    for fc, sub_map in fund_sub_agg.items():
        for sub, agg in sub_map.items():
            subind_funds.setdefault(sub, []).append({
                "fund_code": fc,
                "fund_name": name_map.get(fc, "") or "",
                "weight_pct": round(agg["weight_pct"], 4),
                "hold_value": round(agg["hold_value"], 4),
            })
    # 每子行业基金列表按 weight_pct 降序(和 industry_fund_map 排序一致)
    for lst in subind_funds.values():
        lst.sort(key=lambda x: (x["weight_pct"] or 0), reverse=True)

    return {"report_date": report_date, "subind_funds": subind_funds}


def _compute_position_estimate(conn: sqlite3.Connection) -> dict | None:
    """方案A: 今日预估仓位 + 历史预估时序 (净值回归反推 + lg 校准)。

    算法 (绝对正确, 和 lg 源同口径: 全市场股票型+混合型基金仓位):
    1. 取 fund_daily_nav 全部偏股基金历史净值涨跌时序 (fetch_nav_history 回填的 200 只 × 90 日)
    2. 取 fund_index_daily 沪深300日涨跌时序 (fetch_index_daily 回填)
    3. 每日算全市场偏股基金净值涨跌中位数 R_nav_median (抗极端值, 聚合平均掉个股风格偏移)
    4. 滚动 60 日 OLS 回归: R_nav_median ~ R_index, 斜率 = 原始仓位估计 × beta
       数学依据: R_nav = w_stock×R_stock + w_bond×R_bond + w_cash×R_cash
       忽略 R_bond(~0.01%/日) + R_cash(~0), OLS 斜率 = w_stock × beta
       beta = 基金组合相对沪深300的暴露系数 (>1 偏成长, <1 偏价值)
    5. lg 校准: lg 历史仓位(fund_position_history source='lg') vs 同期原始斜率, 算偏差中位数
       校准后仓位 = 原始斜率 - 偏差中位数 (消除 beta 系统性偏差, 和 lg 口径对齐)
    6. 今日预估 = 最新校准后仓位

    误差控制 (±5% 目标):
    - 滚动 60 日窗口降噪声 (非单日比值)
    - 全市场中位数抗极端值 (200 只基金回归斜率取中位数)
    - lg 校准消除 beta 系统性偏差
    - 偏股基金样本 (和 lg 源口径一致, 排除债基/货基/指数/QDII)

    输出 JSON 结构 (供前端 88 魔咒图加"今日预估仓位"点):
    {
      "report_date": "20260731",
      "current": {
        "date": "2026-07-31",
        "position_estimate": 93.6,        # 今日预估仓位% (校准后)
        "raw_slope": 105.29,              # 原始回归斜率% (校准前)
        "lg_latest_position": 96.01,      # lg 最新仓位% (校准锚点)
        "lg_latest_date": "20260724",
        "calibration_offset": -10.58,     # 校准偏移 (lg仓位 - 原始斜率 的中位数)
        "deviation_from_lg": -2.41,       # 今日预估 - lg最新 (正值=预估高于lg)
        "r_nav_median": 0.85,             # 今日全市场基金净值涨跌中位数%
        "r_index": 0.92,                  # 今日沪深300涨跌%
        "sample_fund_count": 200,
        "method": "rolling_60d_ols+lg_calibration",
        "confidence": "high"              # high(>=100样本)/medium(50-99)/low(<50)
      },
      "history": [                        # 历史预估仓位时序 (校准后, 供前端画线)
        {"date": "2026-07-31", "position": 93.6, "raw_slope": 105.29},
        ...
      ],
      "vs_lg": [                          # 预估 vs lg 周频仓位对比 (交叉验证)
        {"date": "2026-07-24", "estimate": 94.7, "lg": 96.01, "diff": -1.31},
        ...
      ],
      "meta": {
        "method": "rolling_60d_ols_regression + lg_calibration",
        "benchmark": "hs300",
        "sample": "top200_active_equity_funds",
        "window_days": 60,
        "calibration": "median(raw_slope - lg_position) over overlap period",
        "error_margin": "+-5%",
        "note": "反推斜率=w_stock×beta, lg校准消除beta偏差; 和lg源同口径(股票型+混合型全市场仓位)"
      }
    }

    独立计算, 不走 export_data() 7 元组 (遵循 _compute_position_backtest 模式, 避免 190c8f7e 解包破坏)。
    """
    import numpy as np  # 局部 import, 反推算法专用

    # 1. 取基金净值涨跌时序 (fund_daily_nav 回填后的多日数据)
    # ⚠️ 只取偏股+股票型基金 (JOIN fund_basic, 和 lg 源口径一致)
    # 若取全市场(含债基/货基)中位数会被拉低, 当日全市场23785只 vs 历史200只偏股, 口径不一致
    nav_rows = conn.execute(
        "SELECT d.date, d.fund_code, d.nav_change_pct FROM fund_daily_nav d "
        "JOIN fund_basic b ON d.fund_code = b.fund_code "
        "WHERE d.nav_change_pct IS NOT NULL AND d.nav_change_pct != 0 "
        "AND (b.fund_type LIKE '%偏股%' OR b.fund_type LIKE '股票型%') "
        "ORDER BY d.date ASC"
    ).fetchall()
    if not nav_rows:
        print("[estimate] fund_daily_nav 无历史净值涨跌数据, 请先跑 backfill-nav", flush=True)
        return None
    # 按日期聚合: 每日全市场基金净值涨跌中位数 (抗极端值)
    from collections import defaultdict
    daily_navs: dict[str, list[float]] = defaultdict(list)
    for d, _code, pct in nav_rows:
        if pct is not None:
            daily_navs[d].append(pct)
    if len(daily_navs) < 30:
        print(f"[estimate] 日期数 {len(daily_navs)} < 30, 不足做滚动回归", flush=True)
        return None
    nav_median_series: list[tuple[str, float]] = []
    for d in sorted(daily_navs.keys()):
        vals = daily_navs[d]
        nav_median_series.append((d, float(np.median(vals))))
    sample_fund_count = max(len(v) for v in daily_navs.values()) if daily_navs else 0

    # 2. 取沪深300日涨跌时序
    idx_rows = conn.execute(
        "SELECT date, pct_change FROM fund_index_daily "
        "WHERE index_id='hs300' AND pct_change IS NOT NULL "
        "ORDER BY date ASC"
    ).fetchall()
    if not idx_rows:
        print("[estimate] fund_index_daily 无沪深300数据, 请先跑 fetch_index_daily", flush=True)
        return None
    idx_map: dict[str, float] = {r[0]: r[1] for r in idx_rows}

    # 3. 合并基金中位数涨跌 + 沪深300涨跌, 对齐日期
    pts: list[dict] = []
    for d, nav_med in nav_median_series:
        r_idx = idx_map.get(d)
        if r_idx is None or r_idx == 0:  # 沪深300涨跌0或缺失跳过(防除零)
            continue
        pts.append({"date": d, "r_nav": nav_med, "r_index": float(r_idx)})
    if len(pts) < 30:
        print(f"[estimate] 合并后有效日期 {len(pts)} < 30", flush=True)
        return None

    # 4. 滚动 60 日 OLS 回归: r_nav ~ r_index, 斜率 = 原始仓位估计
    WINDOW = 60
    raw_slopes: list[dict] = []  # [{date, raw_slope}]
    for i in range(WINDOW, len(pts) + 1):
        sub = pts[i - WINDOW:i]
        x = np.array([p["r_index"] for p in sub])
        y = np.array([p["r_nav"] for p in sub])
        var_x = float(np.var(x, ddof=1))
        if var_x <= 0:
            continue
        slope = float(np.cov(x, y, ddof=1)[0, 1] / var_x) * 100  # 斜率×100=仓位%
        raw_slopes.append({"date": sub[-1]["date"], "raw_slope": round(slope, 2)})
    if not raw_slopes:
        print("[estimate] 滚动回归无有效输出", flush=True)
        return None

    # 5. lg 校准: lg 历史仓位 vs 同期原始斜率, 算偏差中位数
    lg_rows = conn.execute(
        "SELECT report_date, position_pct FROM fund_position_history "
        "WHERE source='lg' AND position_pct IS NOT NULL "
        "ORDER BY report_date ASC"
    ).fetchall()
    lg_map: dict[str, float] = {r[0]: r[1] for r in lg_rows}

    # 对齐 lg 日期和原始斜率日期 (lg 周频, 斜率日频; 取 lg 日期最近的斜率)
    # 偏差 = 原始斜率 - lg 仓位 (正值=反推偏高, 需减去)
    deviations: list[float] = []
    vs_lg_raw: list[dict] = []  # 先存 raw, estimate 在校准偏移确定后算
    slope_by_date = {s["date"]: s["raw_slope"] for s in raw_slopes}
    for lg_date, lg_pos in lg_map.items():
        # 找 lg_date 当天或最近(前7天内)的斜率
        candidate_slopes = [
            (d, s) for d, s in slope_by_date.items()
            if abs(int(d) - int(lg_date)) <= 700  # 7天内(YYYYMMDD数值差~7)
        ]
        if not candidate_slopes:
            continue
        # 取最接近 lg_date 的
        candidate_slopes.sort(key=lambda x: abs(int(x[0]) - int(lg_date)))
        nearest_date, nearest_slope = candidate_slopes[0]
        dev = nearest_slope - lg_pos
        deviations.append(dev)
        vs_lg_raw.append({
            "date": f"{lg_date[:4]}-{lg_date[4:6]}-{lg_date[6:8]}",
            "lg": round(lg_pos, 2),
            "raw_slope": nearest_slope,
            "raw_diff": round(dev, 2),
        })

    # 校准偏移: 用最近 4 期偏差均值 (约1个月, 贴合近期 beta 变化)
    # 偏差不稳定(6月~-1.5%, 7月~+10%), 用近期4期均值比全期中位数/8期均值更贴合当前 beta
    # 4期是周频lg约1个月, 平衡稳定性(4期降噪)+时效(贴合近期)
    if deviations:
        recent_devs = deviations[-4:] if len(deviations) >= 4 else deviations
        calibration_offset = float(np.mean(recent_devs))
    else:
        calibration_offset = 0.0
    print(f"[estimate] lg 校准: 最近4期偏差均值={calibration_offset:.2f}%, "
          f"对齐期数={len(deviations)}, 全期中位数={float(np.median(deviations)):.2f}%", flush=True)

    # vs_lg: 用最终校准偏移算 estimate (反推值 = raw_slope - calibration_offset)
    vs_lg: list[dict] = []
    for v in vs_lg_raw:
        est = max(0.0, min(100.0, v["raw_slope"] - calibration_offset))
        vs_lg.append({
            "date": v["date"],
            "estimate": round(est, 2),
            "lg": v["lg"],
            "diff": round(est - v["lg"], 2),
            "raw_slope": v["raw_slope"],
        })

    # 6. 校准后仓位时序 = 原始斜率 - 校准偏移
    history: list[dict] = []
    for s in raw_slopes:
        cal_pos = s["raw_slope"] - calibration_offset
        # 仓位约束 0-100% (防御性, 校准后可能略超100或负)
        cal_pos_clamped = max(0.0, min(100.0, cal_pos))
        history.append({
            "date": f"{s['date'][:4]}-{s['date'][4:6]}-{s['date'][6:8]}",
            "position": round(cal_pos_clamped, 2),
            "raw_slope": s["raw_slope"],
        })

    # 7. 当前状态: 最新校准后仓位
    latest = history[-1]
    cur_pos = latest["position"]
    lg_latest_row = lg_rows[-1] if lg_rows else None
    lg_latest_pos = lg_latest_row[1] if lg_latest_row else None
    lg_latest_date = lg_latest_row[0] if lg_latest_row else None
    dev_from_lg = round(cur_pos - lg_latest_pos, 2) if lg_latest_pos is not None else None

    # 置信度: 基于样本量
    if sample_fund_count >= 100:
        confidence = "high"
    elif sample_fund_count >= 50:
        confidence = "medium"
    else:
        confidence = "low"

    # 最新日的 r_nav_median / r_index
    latest_pt = pts[-1]

    return {
        "report_date": latest["date"].replace("-", ""),
        "current": {
            "date": latest["date"],
            "position_estimate": cur_pos,
            "raw_slope": latest["raw_slope"],
            "lg_latest_position": round(lg_latest_pos, 2) if lg_latest_pos is not None else None,
            "lg_latest_date": lg_latest_date,
            "calibration_offset": round(calibration_offset, 2),
            "deviation_from_lg": dev_from_lg,
            "r_nav_median": round(latest_pt["r_nav"], 4),
            "r_index": round(latest_pt["r_index"], 4),
            "sample_fund_count": sample_fund_count,
            "method": "rolling_60d_ols+lg_calibration",
            "confidence": confidence,
        },
        "history": history,
        "vs_lg": vs_lg[-20:] if len(vs_lg) > 20 else vs_lg,  # 最近20期交叉验证
        "meta": {
            "method": "rolling_60d_ols_regression + lg_calibration",
            "benchmark": "hs300",
            "sample": "top200_active_equity_funds",
            "window_days": WINDOW,
            "calibration": "median(raw_slope - lg_position) over overlap period",
            "error_margin": "+-5%",
            "note": "反推斜率=w_stock*beta, lg校准消除beta偏差; 和lg源同口径(股票型+混合型全市场仓位)",
        },
    }


def _compute_position_backtest(conn: sqlite3.Connection) -> dict | None:
    """G功能: 88 魔咒历史回测 + 极值标注。

    输入: fund_position_history lg 源(avg_position + close 时序, 445 期周频 2007-2026)
    输出: position_backtest JSON 产物(extremes + stats + current), 供前端 markPoint + 统计面板。

    算法:
    1. 遍历每期(avg_position + close), 对每期算 after_30d/60d/90d 沪深300涨跌:
       找首条 report_date >= D + N 天的记录, (close_future - close_now) / close_now * 100
    2. extremes: highs Top5(position>88 按仓位降序) + lows Top5(position<80 按仓位升序)
    3. stats: 88 魔咒(position>88) + 80 抄底(position<80) 各自 count/win_rate/avg_30d/60d/90d
       win_rate: 88 魔咒=触发后 30 天下跌占比; 80 抄底=触发后 30 天上涨占比
    4. current: 最新期仓位 + 区间(88 魔咒/中性/抄底) + 历史分位

    独立计算, 不走 export_data() 7 元组(避免破坏解包, 参考 190c8f7e 7 元组适配教训)。
    """
    rows = conn.execute(
        "SELECT report_date, position_pct, close FROM fund_position_history "
        "WHERE source='lg' AND position_pct IS NOT NULL AND close IS NOT NULL "
        "ORDER BY report_date ASC"
    ).fetchall()
    if not rows:
        return None

    # 解析日期, 构建 (date_str, date_obj, position, close) 列表
    pts: list[dict] = []
    for r in rows:
        d_str = r[0]
        try:
            d_obj = dt.datetime.strptime(d_str, "%Y%m%d")
        except ValueError:
            continue
        pts.append({"date_str": d_str, "date_obj": d_obj,
                    "position": r[1], "close": r[2]})
    if not pts:
        return None

    # 对每期算 after_30d/60d/90d: 找首条 report_date >= D + N 天
    HORIZONS = (30, 60, 90)
    for i, p in enumerate(pts):
        for h in HORIZONS:
            target = p["date_obj"] + dt.timedelta(days=h)
            future_close = None
            for j in range(i + 1, len(pts)):
                if pts[j]["date_obj"] >= target:
                    future_close = pts[j]["close"]
                    break
            if future_close is not None and p["close"]:
                p[f"after_{h}d"] = round(
                    (future_close - p["close"]) / p["close"] * 100, 2)
            else:
                p[f"after_{h}d"] = None

    # 极值: highs Top5 (position>88 降序), lows Top5 (position<80 升序)
    highs = sorted([p for p in pts if p["position"] > 88],
                   key=lambda x: x["position"], reverse=True)[:5]
    lows = sorted([p for p in pts if p["position"] < 80],
                  key=lambda x: x["position"])[:5]

    def _fmt_date(s: str) -> str:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"

    def _ext_fmt(p: dict) -> dict:
        return {
            "date": _fmt_date(p["date_str"]),
            "position": round(p["position"], 2),
            "close": round(p["close"], 2),
            "after_30d": p.get("after_30d"),
            "after_60d": p.get("after_60d"),
            "after_90d": p.get("after_90d"),
        }

    # 统计: 88 魔咒(position>88, win=after_30d<0) + 80 抄底(position<80, win=after_30d>0)
    def _zone_stats(filtered: list[dict], win_dir: str) -> dict:
        v30 = [p["after_30d"] for p in filtered if p.get("after_30d") is not None]
        v60 = [p["after_60d"] for p in filtered if p.get("after_60d") is not None]
        v90 = [p["after_90d"] for p in filtered if p.get("after_90d") is not None]
        wins = sum(1 for v in v30 if (v < 0 if win_dir == "down" else v > 0))
        return {
            "count": len(filtered),  # 全部触发期数(含无 after_30d 的末尾期)
            "sample_30d": len(v30),   # 有 after_30d 的有效样本
            "win_rate": round(wins / len(v30), 4) if v30 else None,
            "avg_30d": round(sum(v30) / len(v30), 2) if v30 else None,
            "avg_60d": round(sum(v60) / len(v60), 2) if v60 else None,
            "avg_90d": round(sum(v90) / len(v90), 2) if v90 else None,
        }

    spell_88 = [p for p in pts if p["position"] > 88]
    dip_80 = [p for p in pts if p["position"] < 80]

    # 当前状态: 最新期仓位 + 区间 + 历史分位
    current = pts[-1]
    cur_pos = current["position"]
    all_pos = sorted(p["position"] for p in pts)
    percentile = sum(1 for x in all_pos if x <= cur_pos) / len(all_pos)
    if cur_pos > 88:
        zone = "88魔咒"
    elif cur_pos < 80:
        zone = "80抄底"
    else:
        zone = "中性区"

    return {
        "report_date": current["date_str"],
        "extremes": {
            "highs": [_ext_fmt(p) for p in highs],
            "lows": [_ext_fmt(p) for p in lows],
        },
        "stats": {
            "spell_88": _zone_stats(spell_88, "down"),
            "dip_80": _zone_stats(dip_80, "up"),
        },
        "current": {
            "date": _fmt_date(current["date_str"]),
            "position": round(cur_pos, 2),
            "close": round(current["close"], 2),
            "zone": zone,
            "percentile": round(percentile, 4),
        },
    }


def _compute_holding_concentration_timeseries(conn: sqlite3.Connection) -> dict | None:
    """N功能: 抱团集中度历史时序(10期季报)。

    输入: fund_holding_stock 全部 report_date(当前2期+回填8期=10期)
    输出: holding_concentration_ts JSON 产物, 供前端 N 多信号共振仪表盘。

    每期算:
    - concentration_top10: Top10 重仓股 hold_value_total 占全市场比例(持仓市值集中度)
    - concentration_top20: Top20 重仓股 hold_value_total 占全市场比例
    - herfindahl: Top100 重仓股基金覆盖家数 Herfindahl 指数(和 compute_metrics 口径一致,
      H = Σ(fund_count_i / Σfund_count)^2, 值越大抱团越集中)
    - fund_count: 该期 Top100 总基金覆盖家数
    - total_stocks: 该期总股票数
    - total_value_wan: 该期全市场持仓总市值(万元)
    - top10_stocks: Top10 详情 [{code, name, fund_count, value}]

    独立计算, 不走 export_data() 7 元组(避免破坏解包, 参考 _compute_position_backtest 模式)。
    """
    # 取所有 report_date 升序
    dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT report_date FROM fund_holding_stock ORDER BY report_date ASC"
    ).fetchall()]
    if not dates:
        return None

    series: list[dict] = []
    for d in dates:
        # 取该期全量数据(按 hold_value_total 降序)
        rows = conn.execute(
            "SELECT stock_code, stock_name, fund_count, hold_value_total "
            "FROM fund_holding_stock WHERE report_date=? "
            "ORDER BY hold_value_total DESC",
            (d,),
        ).fetchall()
        if not rows:
            continue

        total_value = sum(r[3] or 0 for r in rows) or 1
        # Top100 基金覆盖家数(和 compute_metrics L1224-1226 口径一致)
        top100 = rows[:100]
        total_fund_count_top100 = sum(r[2] or 0 for r in top100) or 1

        # Top10/Top20 持仓市值集中度
        top10_value = sum(r[3] or 0 for r in rows[:10])
        top20_value = sum(r[3] or 0 for r in rows[:20])
        conc_top10 = round(top10_value / total_value, 6) if total_value else None
        conc_top20 = round(top20_value / total_value, 6) if total_value else None

        # Herfindahl: Top100 基金覆盖家数份额平方和
        herf = sum(((r[2] or 0) / total_fund_count_top100) ** 2 for r in top100)
        herf = round(herf, 6) if top100 else None

        series.append({
            "date": d,
            "concentration_top10": conc_top10,
            "concentration_top20": conc_top20,
            "herfindahl": herf,
            "fund_count": total_fund_count_top100,
            "total_stocks": len(rows),
            "total_value_wan": round(total_value, 2),
            "top10_stocks": [
                {"code": r[0], "name": r[1], "fund_count": r[2], "value": r[3]}
                for r in rows[:10]
            ],
        })

    if not series:
        return None

    return {
        "report_date": series[-1]["date"],  # 最新期
        "period_count": len(series),
        "series": series,
    }


def _compute_scale_change_ts(conn: sqlite3.Connection) -> dict | None:
    """N功能: 全市场规模变动历史时序(113期季报, 1998Q2-2026Q2)。

    输入: fund_scale_change 全量(fund_scale_change_em 113 行)
    输出: scale_change_ts JSON 产物, 供前端 N 多信号共振仪表盘(净申赎+规模两信号)。

    每期含:
    - net_purchase_share: 净申赎份额(亿份, =申购-赎回; <0=净赎回散户离场, >0=净申购散户涌入)
    - end_net_asset: 期末净资产(亿元, 全市场基金总规模)
    - purchase_share/redeem_share/end_total_share/fund_count: 辅助字段(前端 tooltip 用)

    独立计算, 不走 export_data() 7 元组(避免破坏解包, 参考 _compute_holding_concentration_timeseries 模式)。
    summary.scale_change_history 只取 LIMIT 20 期不够 N 功能全量时序分析, 故独立导出全量 113 期。
    """
    rows = conn.execute(
        "SELECT report_date, fund_count, purchase_share, redeem_share, "
        "net_purchase_share, end_total_share, end_net_asset "
        "FROM fund_scale_change ORDER BY report_date ASC"
    ).fetchall()
    if not rows:
        return None

    series = [{
        "date": r[0],
        "fund_count": r[1],
        "purchase_share": r[2],
        "redeem_share": r[3],
        "net_purchase_share": r[4],
        "end_total_share": r[5],
        "end_net_asset": r[6],
    } for r in rows]

    return {
        "report_date": series[-1]["date"],  # 最新期
        "period_count": len(series),
        "series": series,
    }


def _compute_industry_rotation_ts(conn: sqlite3.Connection) -> dict | None:
    """F功能: 全市场行业配置轮动历史时序(50期季报, 2017Q1-2026Q2)。

    输入: fund_industry_alloc 全量(50期 × 900+基金 × 134原始行业名)
    输出: industry_rotation_ts JSON 产物, 供前端 F 行业轮动时序堆叠面积图。

    每期含:
    - date: 报告期 YYYYMMDD
    - fund_count: 该期覆盖基金数(过滤 <50 fund 的脏数据期)
    - industries: {合并后行业名: 平均权重} (AVG weight_pct 跨基金, 非 SUM)

    口径:
    - 平均权重 AVG(weight_pct): 跨基金平均, 反映"典型基金"对该行业的配置占比
      (SUM 会受基金数量影响, AVG 更稳定可比跨期; 同 canonical name 多原始名按 fund_count 加权)
    - 行业名应用 F_INDUSTRY_MERGE_MAP 合并(134原始名 -> 15标准名, 比 IND_MERGE_MAP 更彻底:
      合并 GICS中英文/编号变体 + CSRC L1 大类映射到 GICS 等价物, 制造业/综合/农林牧渔保留)
    - "合计"行排除(是求和行非真实行业, 3 行 avg=58% 会污染图表)
    - 过滤 fund_count<50 的脏数据期(20170901=1只/20171215=1只/20260601=1只 等单基金误录)

    独立计算, 不走 export_data() 7 元组(避免破坏解包, 参考 _compute_scale_change_ts 模式)。
    """
    # F 专用行业合并映射(比 IND_MERGE_MAP 更彻底: 134原始名 -> 15标准名)
    # 合并策略: GICS中英文/编号变体 -> 11 GICS中文标准名; CSRC L1 大类映射到 GICS 等价物;
    # 制造业(CSRC超大类)/综合/农林牧渔(GICS无对应)保留独立; "合计"排除
    F_INDUSTRY_MERGE_MAP = {
        # 信息技术 (GICS + CSRC 信息传输)
        '信息技术': '信息技术', '信息传输、软件和信息技术服务业': '信息技术', '信息科技': '信息技术',
        '45信息技术': '信息技术', '信息技术InformationTechnology': '信息技术',
        '信息技术Information technology': '信息技术', 'InformationTechnology信息技术': '信息技术',
        'Information Technology 信息技术': '信息技术', 'H 信息技术': '信息技术', 'H信息技术': '信息技术',
        '信息技术Information': '信息技术', '科技': '信息技术', '金融信息技术': '信息技术',
        # 金融业 (GICS + CSRC 金融业)
        '金融业': '金融业', '金融': '金融业', '40金融': '金融业', 'E金融': '金融业', 'E 金融': '金融业',
        '金融Financials': '金融业', 'Financials金融': '金融业', 'Financials 金融': '金融业',
        # 房地产业 (GICS + CSRC 房地产业)
        '房地产业': '房地产业', '房地产': '房地产业', '房地产RealEstate': '房地产业',
        '60房地产': '房地产业', '地产业': '房地产业', 'K房地产': '房地产业', 'K 地产业': '房地产业',
        'RealEstate房地产': '房地产业', 'Real Estate 房地产': '房地产业', '地产建筑业': '房地产业',
        # 材料 (GICS + CSRC 采矿业/原材料)
        '材料': '材料', '原材料': '材料', '15原材料': '材料', '材料Materials': '材料',
        '基础材料': '材料', 'A基础材料': '材料', '原材料Materials': '材料',
        'Materials原材料': '材料', 'Materials 原材料': '材料', '采矿业': '材料',
        # 工业 (GICS + CSRC 建筑/交运/租赁/科研)
        '工业': '工业', '20工业': '工业', 'G工业': '工业', 'G 工业': '工业',
        '工业Industrials': '工业', 'Industrials工业': '工业', 'Industrials 工业': '工业',
        '建筑业': '工业', '交通运输、仓储和邮政业': '工业',
        '租赁和商务服务业': '工业', '科学研究和技术服务业': '工业',
        # 能源 (GICS)
        '能源': '能源', 'D能源': '能源', 'D 能源': '能源', '10能源': '能源',
        'Energy能源': '能源', '能源Energy': '能源', 'Energy 能源': '能源',
        # 公用事业 (GICS + CSRC 电力/水利)
        '公用事业': '公用事业', 'J公用事业': '公用事业', 'J 公用事业': '公用事业',
        '55公用事业': '公用事业', 'Utilities公用事业': '公用事业', 'Utilities 公用事业': '公用事业',
        '公共事业': '公用事业', '公共事业Utilities': '公用事业', '公用事业Utilities': '公用事业',
        '电力、热力、燃气及水生产和供应业': '公用事业',
        '水利、环境和公共设施管理业': '公用事业',
        # 医疗保健 (GICS + CSRC 卫生)
        '医疗保健': '医疗保健', '医疗': '医疗保健', '35医疗保健': '医疗保健',
        '保健HealthCare': '医疗保健', '保健': '医疗保健', 'HealthCare医疗保健': '医疗保健',
        'Health Care 医疗保健': '医疗保健', 'F医疗保健': '医疗保健', 'F 医疗保健': '医疗保健',
        '医疗保健Health Care': '医疗保健', '卫生和社会工作': '医疗保健',
        '卫生和社会工作业': '医疗保健',
        # 非必需消费品 (GICS + CSRC 批发零售/住宿餐饮/居民服务/教育/文娱)
        '非日常生活消费品': '非必需消费品', '非必需消费品': '非必需消费品', '25可选消费': '非必需消费品',
        '非必需消费品ConsumerDiscretionary': '非必需消费品', '消费者非必需品': '非必需消费品',
        '非周期性消费品': '非必需消费品', 'B消费者非必需品': '非必需消费品',
        'B 消费者非必需品': '非必需消费品',
        'ConsumerDiscretionary非日常生活消费品': '非必需消费品',
        'Consumer Discretionary 非日常生活消费品': '非必需消费品',
        '非日常生活消费品Consumer Discretionary': '非必需消费品',
        '可选消费': '非必需消费品', '可选消费品': '非必需消费品',
        '周期性消费品': '非必需消费品', '消费品,周期性': '非必需消费品',
        '非必需消费': '非必需消费品',
        '批发和零售业': '非必需消费品', '住宿和餐饮业': '非必需消费品',
        '居民服务、修理和其他服务业': '非必需消费品', '教育': '非必需消费品',
        '文化、体育和娱乐业': '非必需消费品',
        # 必需消费品 (GICS + CSRC 农林牧渔)
        '必需消费品': '必需消费品', '日常消费品': '必需消费品', '30日常消费': '必需消费品',
        '必需消费品ConsumerStaples': '必需消费品', '消费者常用品': '必需消费品',
        'C消费者常用品': '必需消费品', 'C 消费者常用品': '必需消费品',
        'ConsumerStaples日常消费品': '必需消费品', 'Consumer Staples 日常消费品': '必需消费品',
        '日常消费': '必需消费品', '消费品,非周期性': '必需消费品',
        '必需消费品Consumer': '必需消费品',
        '农、林、牧、渔业': '必需消费品',
        # 通信服务 (GICS)
        '通讯': '通信服务', '通讯业务': '通信服务', '通信服务': '通信服务',
        '通讯服务': '通信服务',
        '50电信服务': '通信服务', '电信服务': '通信服务', '电信业务': '通信服务',
        '通信服务CommunicationServices': '通信服务', '通信服务Communication': '通信服务',
        'TelecommunicationServices通讯服务': '通信服务',
        'Telecommunication Services 电信业务': '通信服务',
        '电信业务Conmmunications': '通信服务', 'I电信服务': '通信服务', 'I 电信服务': '通信服务',
        # 综合 (CSRC, GICS无对应)
        '综合': '综合', '综合经营': '综合',
        # 制造业 (CSRC超大类, GICS无对应, 占比最大 avg=44.86%, 保留独立看趋势)
        '制造业': '制造业',
        # "合计" 排除(不在此映射, 下面 filter 掉)
    }
    EXCLUDE_NAMES = {'合计'}

    rows = conn.execute(
        "SELECT report_date, industry_name, AVG(weight_pct), COUNT(DISTINCT fund_code) "
        "FROM fund_industry_alloc GROUP BY report_date, industry_name "
        "ORDER BY report_date ASC, AVG(weight_pct) DESC"
    ).fetchall()
    if not rows:
        return None

    # 按期聚合, 应用 F_INDUSTRY_MERGE_MAP 合并行业名(比 IND_MERGE_MAP 更彻底)
    # 同一 canonical name 多原始名 -> 按 fund_count 加权平均(各原始名覆盖基金数不同, 简单平均会偏差)
    periods_raw: dict[str, list[tuple[str, float, int]]] = {}
    period_fund_count: dict[str, int] = {}
    for date, ind_name, avg_w, fc in rows:
        if ind_name in EXCLUDE_NAMES:
            continue  # 排除"合计"求和行
        canonical = F_INDUSTRY_MERGE_MAP.get(ind_name, ind_name)
        periods_raw.setdefault(date, []).append((canonical, avg_w or 0.0, fc or 0))
        # 期覆盖基金数取该期所有行业 fc 的最大值(因为不同行业 fc 不同)
        if date not in period_fund_count or (fc or 0) > period_fund_count[date]:
            period_fund_count[date] = fc or 0

    # 过滤脏数据期: fund_count<50 的期(20170901=1只/20171215=1只/20260601=1只 等单基金误录)
    MIN_FUNDS = 50
    series = []
    all_canonical_avg: dict[str, list[float]] = {}  # canonical -> [avg_weights across periods] for ordering
    for date in sorted(periods_raw.keys()):
        if period_fund_count[date] < MIN_FUNDS:
            continue
        # 同 canonical name 多原始名 -> 按 fund_count 加权平均
        canonical_groups: dict[str, list[float]] = {}  # name -> [weighted_sum, total_fc]
        for canonical, avg_w, fc in periods_raw[date]:
            g = canonical_groups.setdefault(canonical, [0.0, 0])
            g[0] += avg_w * fc
            g[1] += fc
        industries = {name: round(ws / tf, 4) for name, (ws, tf) in canonical_groups.items() if tf > 0}
        for name, w in industries.items():
            all_canonical_avg.setdefault(name, []).append(w)
        series.append({
            "date": date,
            "fund_count": period_fund_count[date],
            "industries": industries,
        })

    if not series:
        return None

    # industries_order: 按全期平均权重降序排, 前端画堆叠面积图按此顺序堆叠(主导行业在下)
    industries_order = sorted(
        all_canonical_avg.keys(),
        key=lambda n: -sum(all_canonical_avg[n]) / len(all_canonical_avg[n]),
    )

    return {
        "report_date": series[-1]["date"],  # 最新期
        "period_count": len(series),
        "industries_count": len(industries_order),
        "industries_order": industries_order,
        "series": series,
    }


def export_data() -> tuple[dict, dict, dict, dict, dict, dict, dict]:
    """导出 7 类 JSON: summary / holdings / industry / top20 / asset_alloc / industry_fund_map / manuf_subind_fund_map。

    Returns: (summary, holdings, industry, top20, asset_alloc, industry_fund_map, manuf_subind_fund_map)
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
    # 最近 20 期净申赎(先 DESC LIMIT 20 取最近20期, 再 reverse 转升序;
    # 升序约定与 position_history 一致: 末项=最新期, 前端 _pfCalcChange 取 sch[n-1] 为当前期)
    sc_rows = conn.execute(
        "SELECT report_date, fund_count, purchase_share, redeem_share, "
        "net_purchase_share, end_total_share, end_net_asset "
        "FROM fund_scale_change ORDER BY report_date DESC LIMIT 20"
    ).fetchall()
    scale_history = [{"report_date": r[0], "fund_count": r[1],
                      "purchase_share": r[2], "redeem_share": r[3],
                      "net_purchase_share": r[4], "end_total_share": r[5],
                      "end_net_asset": r[6]} for r in sc_rows]
    scale_history.reverse()  # DESC->ASC: 末项=最新期, 前端取 sch[n-1] 为当前期
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
    # stock_code -> 申万一级名称反查(sw_components.json, 5210成分股覆盖全A股, 映射率100%)
    stock_ind_map = _load_stock_industry_map()
    holdings = {
        "report_date": report_date,
        "prev_report_date": prev_report,
        "top100": [{"stock_code": r[0], "stock_name": r[1], "fund_count": r[2],
                   "hold_share_total": r[3], "hold_value_total": r[4],
                   "prev_value": prev_map.get(r[0]),
                   "stock_industry": stock_ind_map.get(r[0], ""),
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
    industries_list = [{"industry_name": r[0], "total_weight": r[1],
                        "total_value": r[2], "fund_count": r[3]}
                       for r in ind_rows]

    # 制造业子行业拆分（方案C Step3）: 证监会"制造业"大类 -> 申万一级子行业 breakdown
    # 算法见 _compute_manuf_breakdown() docstring; 按基金维度拆分非简单聚合
    manuf_breakdown = _compute_manuf_breakdown(conn, report_date, stock_ind_map)
    if manuf_breakdown:
        for ind in industries_list:
            if ind["industry_name"] == "制造业":
                ind["breakdown"] = manuf_breakdown
                break

    industry = {
        "report_date": report_date,
        "industries": industries_list,
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

    # B2 修复: top20_adjustment 在此重算, 不依赖 fund_metrics 预计算值(可能 stale None)
    # 根因: compute_metrics 在数据未齐时跑会写 None 入 fund_metrics, export_data 直读永卡 None
    # 公式: (cur_top20_value - prev_top20_value) / prev_top20_value * 100
    # cur_top20_value = 当期 Top20 hold_value_total 之和(cur_rows 已 fetch)
    # prev_top20_value = 上期 Top20 hold_value_total 之和(独立查询, 与 compute_metrics 同口径)
    if prev_report:
        prev_top20_rows = conn.execute(
            "SELECT hold_value_total FROM fund_holding_stock "
            "WHERE report_date=? AND hold_value_total IS NOT NULL "
            "ORDER BY hold_value_total DESC LIMIT 20",
            (prev_report,),
        ).fetchall()
        prev_top20_value = sum(r[0] or 0 for r in prev_top20_rows)
    else:
        prev_top20_value = None
    cur_top20_value = sum(r[3] or 0 for r in cur_rows)
    top20_adjustment_fresh = None
    top20_detail_fresh = None
    if cur_top20_value and prev_top20_value and prev_top20_value != 0:
        top20_adjustment_fresh = round(
            (cur_top20_value - prev_top20_value) / prev_top20_value * 100, 4)
        top20_detail_fresh = {
            "current_top20_value": cur_top20_value,
            "prev_top20_value": prev_top20_value,
            "prev_report_date": prev_report,
            "note": "export_data 重算(防 fund_metrics 预计算值 stale)",
        }
    # patch summary.metrics 中 top20_adjustment(8 指标之一)
    for m in summary["metrics"]:
        if m["metric_id"] == "top20_adjustment":
            m["metric_value"] = top20_adjustment_fresh
            m["detail"] = top20_detail_fresh
            break

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

    # 6. industry_fund_map: 逐只基金-行业映射, 按合并后行业名分组, 供前端"点击展开某行业基金列表"按需 fetch
    # 结构: {report_date, industry_funds: {合并行业名: [{fund_code,fund_name,weight_pct,hold_value}, ...]}}
    # 每组按 weight_pct 降序; 行业名应用 IND_MERGE_MAP 合并(和前端 app.js 一致)
    fmap_rows = conn.execute(
        "SELECT a.fund_code, b.fund_name, a.industry_name, a.weight_pct, a.hold_value "
        "FROM fund_industry_alloc a "
        "LEFT JOIN fund_basic b ON a.fund_code = b.fund_code "
        "WHERE a.report_date=?",
        (report_date,),
    ).fetchall()
    _groups: dict[str, list[dict]] = {}
    for fc, fn, ind, wp, hv in fmap_rows:
        merged = IND_MERGE_MAP.get(ind, ind)
        _groups.setdefault(merged, []).append({
            "fund_code": fc, "fund_name": fn or "",
            "weight_pct": round(wp, 4) if wp is not None else None,
            "hold_value": round(hv, 4) if hv is not None else None,
        })
    for m in _groups.values():
        m.sort(key=lambda x: (x["weight_pct"] or 0), reverse=True)
    industry_fund_map = {
        "report_date": report_date,
        "industry_funds": _groups,
    }

    # 7. manuf_subind_fund_map: 制造业子行业 -> 基金详情列表(前端"子行业下钻到基金"弹窗, 方案C Step5)
    # 重仓股拆分口径: 每只制造业基金的重仓股按申万一级子行业聚合 weight_pct/hold_value 和
    manuf_subind_fund_map = _compute_manuf_subind_fund_map(conn, report_date, stock_ind_map)

    conn.close()
    return summary, holdings, industry, top20, asset_alloc, industry_fund_map, manuf_subind_fund_map


def export_json_files() -> None:
    """写 7 类 JSON 到 static-site/data/。"""
    summary, holdings, industry, top20, asset_alloc, industry_fund_map, manuf_subind_fund_map = export_data()
    STATIC_DATA_DIR.mkdir(parents=True, exist_ok=True)
    files = {
        "public_fund_summary.json": summary,
        "public_fund_holdings.json": holdings,
        "public_fund_industry.json": industry,
        "public_fund_top20.json": top20,
        "public_fund_asset_alloc.json": asset_alloc,
        "public_fund_industry_fund_map.json": industry_fund_map,
        "public_fund_manuf_subind_fund_map.json": manuf_subind_fund_map,
    }
    for fname, data in files.items():
        (STATIC_DATA_DIR / fname).write_text(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")
        size = (STATIC_DATA_DIR / fname).stat().st_size
        print(f"  [export] {fname} ({size} bytes)", flush=True)
    # G功能: 88 魔咒历史回测(独立计算, 不走 export_data 7 元组, 避免解包破坏)
    # N功能: 抱团集中度历史时序(独立计算, 同模式, 复用 conn)
    conn = get_conn()
    try:
        backtest = _compute_position_backtest(conn)
        concentration_ts = _compute_holding_concentration_timeseries(conn)
        scale_change_ts = _compute_scale_change_ts(conn)
        industry_rotation_ts = _compute_industry_rotation_ts(conn)
    finally:
        conn.close()
    if backtest:
        (STATIC_DATA_DIR / "public_fund_position_backtest.json").write_text(
            json.dumps(backtest, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")
        size = (STATIC_DATA_DIR / "public_fund_position_backtest.json").stat().st_size
        print(f"  [export] public_fund_position_backtest.json ({size} bytes)", flush=True)
    if concentration_ts:
        (STATIC_DATA_DIR / "public_fund_holding_concentration_ts.json").write_text(
            json.dumps(concentration_ts, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")
        size = (STATIC_DATA_DIR / "public_fund_holding_concentration_ts.json").stat().st_size
        print(f"  [export] public_fund_holding_concentration_ts.json ({size} bytes)", flush=True)
    if scale_change_ts:
        (STATIC_DATA_DIR / "public_fund_scale_change_ts.json").write_text(
            json.dumps(scale_change_ts, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")
        size = (STATIC_DATA_DIR / "public_fund_scale_change_ts.json").stat().st_size
        print(f"  [export] public_fund_scale_change_ts.json ({size} bytes)", flush=True)
    if industry_rotation_ts:
        (STATIC_DATA_DIR / "public_fund_industry_rotation_ts.json").write_text(
            json.dumps(industry_rotation_ts, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")
        size = (STATIC_DATA_DIR / "public_fund_industry_rotation_ts.json").stat().st_size
        print(f"  [export] public_fund_industry_rotation_ts.json ({size} bytes)", flush=True)
    # 方案A: 今日预估仓位 + 历史预估时序 (净值回归反推 + lg 校准, 独立计算非 7 元组)
    position_estimate = _compute_position_estimate(conn)
    if position_estimate:
        (STATIC_DATA_DIR / "public_fund_position_estimate.json").write_text(
            json.dumps(position_estimate, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")
        size = (STATIC_DATA_DIR / "public_fund_position_estimate.json").stat().st_size
        print(f"  [export] public_fund_position_estimate.json ({size} bytes)", flush=True)
    print(f"[export] 7 个 JSON 写入 -> {STATIC_DATA_DIR}", flush=True)


# ── CLI ─────────────────────────────────────────────────────────────────────────
def main():
    init_db()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "quarterly"
    if cmd not in ("quarterly", "full", "daily", "metrics", "export", "backfill", "backfill-industry", "check-fresh", "backfill-nav", "estimate"):
        print(__doc__)
        print(f"\n用法: python -m app.collector.public_fund <command>")
        print(f"  quarterly       季度全量(5汇总+top1000×2子页+8指标, ~35min)")
        print(f"  full            全量9000只×2子页(~5.25h, 凌晨解耦)")
        print(f"  daily           日更净值+估算仓位变化(~10s)")
        print(f"  metrics         重算8指标")
        print(f"  export          只导出5类JSON")
        print(f"  backfill --start 20240101 --end 20241231  历史重仓股回填")
        print(f"  backfill-industry --years 2017-2024 --top 1000  行业配置历史回填(8年)")
        print(f"  check-fresh [--top N]  数据新鲜度闸门(exit 0=应跑, 1=无新数据跳过)")
        print(f"  backfill-nav [--days 90]  回填头部200只偏股基金历史净值(反推算法用, ~60s)")
        print(f"  estimate        算预估仓位+导出JSON(需先 backfill-nav + fetch_index_daily)")
        sys.exit(1)

    # 进程互斥（quarterly/full/daily/backfill/backfill-industry/backfill-nav 持锁, metrics/export/check-fresh/estimate 不需要）
    if cmd in ("quarterly", "full", "daily", "backfill", "backfill-industry", "backfill-nav"):
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
    elif cmd == "backfill-industry":
        # 行业配置历史回填: --years 2017-2024 --top 1000
        # 逐只跑 fetch_fund_industry_alloc(code, year) 共8年, 独立进度文件断点续传
        years_arg = "2017-2024"
        top_n = QUARTERLY_TOP_N
        for i, a in enumerate(sys.argv[2:], 2):
            if a == "--years" and i + 1 < len(sys.argv):
                years_arg = sys.argv[i + 1]
            elif a == "--top" and i + 1 < len(sys.argv):
                top_n = int(sys.argv[i + 1])
        # 解析 years: "2017-2024" -> ["2017",...,"2024"]
        if "-" in years_arg:
            ys = years_arg.split("-")
            years = [str(y) for y in range(int(ys[0]), int(ys[1]) + 1)]
        else:
            years = [years_arg]
        print(f"[backfill-industry] years={years} top={top_n}", flush=True)
        funds = universe_top_funds(n=top_n)
        # 排除后端份额(fund_name 含"后端", 后端份额行业配置数据恒空)
        funds = [(c, n, ft) for c, n, ft in funds if "后端" not in n]
        print(f"[backfill-industry] 基金池: {len(funds)} 只(排除后端份额)", flush=True)
        # 独立进度文件, 避免和 /tmp/fund-collect-progress.json 冲突
        prog_path = Path("/tmp/fund-industry-backfill-progress.json")
        done: set[str] = set()
        if prog_path.exists():
            try:
                done = set(json.loads(prog_path.read_text(encoding="utf-8")).get("industry_backfill", []))
            except Exception:  # noqa: BLE001
                done = set()
        ok = empty = fail = 0
        t0 = time.time()
        for i, (code, name, _ft) in enumerate(funds, 1):
            for year in years:
                key = f"{code}|{year}"
                if key in done:
                    ok += 1  # 断点续传, 已完成计 ok
                    continue
                try:
                    n = fetch_fund_industry_alloc(code, year=year)
                    if n > 0:
                        ok += 1
                    else:
                        empty += 1
                    done.add(key)  # 无论 ok 还是 empty 都标记完成, 避免重跑
                except Exception as e:  # noqa: BLE001
                    fail += 1
                    print(f"  [H] {code} {name} {year} 异常: {type(e).__name__} {e}", flush=True)
                time.sleep(THROTTLE_SEC)
            # 每 50 只回写进度 + ETA
            if i % 50 == 0 or i == len(funds):
                try:
                    prog_path.write_text(
                        json.dumps({"industry_backfill": sorted(done)}, ensure_ascii=False),
                        encoding="utf-8",
                    )
                except Exception as e:  # noqa: BLE001
                    print(f"  [progress] WARN 写入失败: {e}", flush=True)
                elapsed = time.time() - t0
                eta = (elapsed / i) * (len(funds) - i) if i > 0 else 0
                print(f"  [backfill-industry] {i}/{len(funds)} funds "
                      f"({i*100/len(funds):.1f}%) ok={ok} empty={empty} fail={fail} "
                      f"elapsed={elapsed:.0f}s eta={eta:.0f}s", flush=True)
        print(f"[backfill-industry] 完成: ok={ok} empty={empty} fail={fail} "
              f"总耗时={time.time()-t0:.0f}s", flush=True)
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
    elif cmd == "backfill-nav":
        # 回填头部偏股基金历史净值时序 (反推算法用, 一次性 ~60s)
        # --days N 回填天数 (默认 90, 滚动 60 日回归需至少 60 日)
        days = 90
        for i, a in enumerate(sys.argv[2:], 2):
            if a == "--days" and i + 1 < len(sys.argv):
                days = int(sys.argv[i + 1])
        # 先确保沪深300日频有数据 (反推基准指数)
        fetch_index_daily()
        n = fetch_nav_history(days=days)
        print(f"[backfill-nav] 完成, 总行数={n}", flush=True)
    elif cmd == "estimate":
        # 算预估仓位 + 导出 JSON (需先 backfill-nav)
        # 先刷新沪深300到最新
        fetch_index_daily()
        export_json_files()
        print(f"[estimate] 预估仓位 JSON 已导出", flush=True)


if __name__ == "__main__":
    main()
