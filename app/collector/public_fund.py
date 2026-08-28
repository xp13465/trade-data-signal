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

-- ── 筛选器阶段0: 6 张新表（2026-08-02 新增, 为评分引擎提供数据地基）──────────────
-- fund_basic 扩 15 列由 _migrate_fund_basic() 用 ALTER TABLE ADD COLUMN 处理
-- (CREATE TABLE IF NOT EXISTS 不会改已有表结构, 故用迁移函数动态加列)

-- 表10: fund_manager 基金经理（PK=fund_code+manager_name）
-- fund_manager_em 拿关系+经理档案(8列), 自爬fundf10补 appoint_date + managed_history
-- 经理级别属性(managed_count/managed_scale/best_return)在每条关系记录冗余, 采集时全量刷新
CREATE TABLE IF NOT EXISTS fund_manager (
  fund_code TEXT NOT NULL,
  manager_name TEXT NOT NULL,
  appoint_date TEXT,              -- 任职起始日 YYYYMMDD(自爬fundf10 manager页)
  managed_count INTEGER,          -- 在管基金数
  managed_scale REAL,             -- 在管规模(亿元)
  best_return REAL,               -- 历史最佳回报%
  managed_history TEXT,           -- 任职历史 JSON(管过哪些基金 [{code,name,start,end}])
  tenure_days INTEGER,            -- 任职天数(从 appoint_date 算到今天)
  work_days INTEGER,              -- 累计从业天数(fund_manager_em "累计从业时间")
  update_date TEXT,
  PRIMARY KEY (fund_code, manager_name)
);
CREATE INDEX IF NOT EXISTS idx_fund_manager_name ON fund_manager(manager_name);
CREATE INDEX IF NOT EXISTS idx_fund_manager_company ON fund_manager(fund_code);

-- 表11: fund_performance 9区间收益率+快照（PK=fund_code+update_date）
-- fund_open_fund_rank_em("全部") 一次拿全市场20070只 9区间收益率(金矿, 2.5s)
CREATE TABLE IF NOT EXISTS fund_performance (
  fund_code TEXT NOT NULL,
  update_date TEXT NOT NULL,      -- 日期 YYYYMMDD
  unit_nav REAL,                  -- 单位净值快照
  acc_nav REAL,                   -- 累计净值快照
  day_growth REAL,                -- 日增长率%
  return_1w REAL,                 -- 近1周%
  return_1m REAL,                 -- 近1月%
  return_3m REAL,                 -- 近3月%
  return_6m REAL,                 -- 近6月%
  return_1y REAL,                 -- 近1年%
  return_2y REAL,                 -- 近2年%
  return_3y REAL,                 -- 近3年%
  return_ytd REAL,                -- 今年来%
  return_since_inception REAL,    -- 成立来%
  fee_rate REAL,                  -- 手续费%(rank_em 自带)
  PRIMARY KEY (fund_code, update_date)
);
CREATE INDEX IF NOT EXISTS idx_fund_performance_date ON fund_performance(update_date);

-- 表12: fund_risk_indicator 风险指标（PK=fund_code+period）
-- fund_individual_analysis_xq 拿5指标(3周期:1y/3y/5y), 失败降级用 fetch_nav_history 净值自算
-- xq 提供: annual_volatility/sharpe/max_drawdown/risk_return_rank/anti_risk_rank
-- 自算补: sortino/calmar/downside_risk/information_ratio/alpha(需5年净值, 回撤依赖 fund_daily_nav)
CREATE TABLE IF NOT EXISTS fund_risk_indicator (
  fund_code TEXT NOT NULL,
  period TEXT NOT NULL,           -- '1y'/'3y'/'5y'
  sharpe REAL,                    -- 年化夏普比率
  sortino REAL,                   -- 索提诺比率(自算)
  calmar REAL,                    -- 卡玛比率(自算)
  max_drawdown REAL,              -- 最大回撤%
  annual_volatility REAL,         -- 年化波动率%
  downside_risk REAL,             -- 下行风险%(自算)
  information_ratio REAL,         -- 信息比率(自算, 需基准)
  alpha REAL,                     -- alpha(自算, 需基准回归)
  risk_return_rank INTEGER,       -- 较同类风险收益比%(xq, 0-100)
  anti_risk_rank INTEGER,         -- 较同类抗风险波动%(xq, 0-100)
  data_source TEXT,               -- 'xq'/'self_calc'/'mixed'
  update_date TEXT,
  PRIMARY KEY (fund_code, period)
);
CREATE INDEX IF NOT EXISTS idx_fund_risk_indicator_period ON fund_risk_indicator(period);

-- 表13: fund_rating 4家评级（PK=fund_code+rating_date）
-- fund_rating_all 一次拿全市场18096只
-- 4家: 上海证券/招商证券/济安金信/晨星(任务描述"银河"实测是"上海证券")
CREATE TABLE IF NOT EXISTS fund_rating (
  fund_code TEXT NOT NULL,
  rating_date TEXT NOT NULL,      -- 评级日期 YYYYMMDD
  shanghai_securities REAL,       -- 上海证券评级(1-5)
  cms REAL,                       -- 招商证券评级(1-5)
  jajx REAL,                      -- 济安金信评级(1-5)
  morningstar REAL,               -- 晨星评级(1-5)
  five_star_count INTEGER,        -- 5星评级家数
  update_date TEXT,
  PRIMARY KEY (fund_code, rating_date)
);
CREATE INDEX IF NOT EXISTS idx_fund_rating_date ON fund_rating(rating_date);

-- 表14: fund_purchase_status 申赎状态（PK=fund_code+update_date）
-- fund_purchase_em 一次拿全市场27115只
CREATE TABLE IF NOT EXISTS fund_purchase_status (
  fund_code TEXT NOT NULL,
  update_date TEXT NOT NULL,      -- 采集日期 YYYYMMDD
  purchase_status TEXT,           -- 申购状态(开放申购/暂停申购/限制大额)
  redeem_status TEXT,             -- 赎回状态(开放赎回/暂停赎回)
  next_open_date TEXT,            -- 下一开放日 YYYYMMDD
  purchase_min REAL,              -- 购买起点(元)
  daily_limit REAL,               -- 日累计限定金额(元)
  PRIMARY KEY (fund_code, update_date)
);
CREATE INDEX IF NOT EXISTS idx_fund_purchase_status_date ON fund_purchase_status(update_date);

-- 表15: fund_fee_detail 费率分档（PK=fund_code+fee_type+tier_index）
-- fund_individual_detail_info_xq 逐只拿买入/卖出/其他费用分档(9行/只)
CREATE TABLE IF NOT EXISTS fund_fee_detail (
  fund_code TEXT NOT NULL,
  fee_type TEXT NOT NULL,         -- 'purchase'(买入)/'redeem'(卖出)/'other'(其他)
  tier_index INTEGER NOT NULL,    -- 档位序号(0,1,2...)
  condition_desc TEXT,            -- 条件描述(如"0.0万<买入金额<50.0万")
  fee_rate REAL,                  -- 费率(%或元, 买入100万+可能是固定元)
  update_date TEXT,
  PRIMARY KEY (fund_code, fee_type, tier_index)
);
CREATE INDEX IF NOT EXISTS idx_fund_fee_detail_code ON fund_fee_detail(fund_code);

-- ── 阶段1 评分引擎: fund_score 综合评分表（2026-07-20 新增）──────────────────────
-- PK=fund_code+score_date, 每日重算头部2000 + 周日全量27409只
-- 6维度子分 + 5风险指标 + 经理6维 + 半凯利仓位 + 市场乘数 + 数据完整度
-- 独立计算模式不走 export_data() 7元组（遵循 commit 190c8f7e 教训, 仿 _compute_position_estimate）
CREATE TABLE IF NOT EXISTS fund_score (
  fund_code TEXT NOT NULL,
  score_date TEXT NOT NULL,            -- 评分日期 YYYYMMDD
  composite_score REAL,                -- 综合分 0-100
  star_rating INTEGER,                 -- 星级 1-5
  -- 6 维度子分 (0-100)
  score_return REAL,                   -- D1 历史业绩
  score_risk_adjusted REAL,            -- D2 风险调整后收益
  score_drawdown REAL,                 -- D3 回撤控制
  score_stability REAL,                -- D4 业绩稳定性
  score_scale REAL,                    -- D5 规模与流动性
  score_fee REAL,                      -- D6 费率
  -- 5 风险指标 (3y 周期原始值)
  sharpe REAL, sortino REAL, calmar REAL,
  information_ratio REAL, alpha REAL,
  -- 经理稳健度 6 维 (0-100) + 综合分
  manager_score REAL,
  m1_tenure REAL, m2_scale REAL, m3_perf_stability REAL,
  m4_drawdown REAL, m5_coherence REAL, m6_focus REAL,
  -- 半凯利仓位
  kelly_fraction REAL,                 -- 凯利比例 f* (0-1)
  half_kelly_position REAL,            -- 半凯利建议仓位% (0-90)
  kelly_win_rate REAL,                 -- 胜率 p
  kelly_win_loss_ratio REAL,           -- 赔率 b
  kelly_tier TEXT,                     -- 保守/均衡/激进
  market_adjustment REAL,              -- 市场乘数 (基于预估仓位)
  final_suggestion REAL,               -- 最终建议仓位% = half_kelly × market_adjustment
  -- 元数据
  benchmark TEXT,                      -- 基准指数 (hs300/csi500/gem)
  score_method TEXT,                   -- 评分方法版本 (如 'v1.0_20260720')
  data_completeness REAL,              -- 数据完整度% (缺数据降权)
  update_date TEXT,
  PRIMARY KEY (fund_code, score_date)
);
CREATE INDEX IF NOT EXISTS idx_fund_score_date ON fund_score(score_date);
CREATE INDEX IF NOT EXISTS idx_fund_score_composite ON fund_score(composite_score DESC);
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
    _migrate_fund_basic(conn)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()


# fund_basic 扩 15 列（11 任务要求 + 4 金矿补充, 覆盖 fund_overview_em 18 字段金矿）
# CREATE TABLE IF NOT EXISTS 不改已有表结构, 用 ALTER TABLE ADD COLUMN 动态加列
# SQLite ADD COLUMN 无 IF NOT EXISTS, 用 PRAGMA table_info 检查避免重复添加
FUND_BASIC_NEW_COLUMNS: list[tuple[str, str]] = [
    # (列名, 列定义) —— 11 任务要求
    ("fund_company", "TEXT"),        # 基金管理人
    ("fund_manager", "TEXT"),        # 基金经理人
    ("setup_date", "TEXT"),          # 成立日期 YYYYMMDD(从"成立日期/规模"解析)
    ("scale", "REAL"),               # 净资产规模(亿元, 解析数字)
    ("management_fee", "REAL"),      # 管理费率%
    ("custody_fee", "REAL"),         # 托管费率%
    ("purchase_fee", "REAL"),        # 最高认购费率%
    ("custodian", "TEXT"),           # 基金托管人
    ("strategy", "TEXT"),            # 基金全称(含策略描述, fund_overview_em 无独立"投资策略"字段)
    ("benchmark", "TEXT"),           # 业绩比较基准
    ("tracking_target", "TEXT"),     # 跟踪标的
    # 4 金矿补充(完整覆盖18字段, 不丢信息)
    ("issue_date", "TEXT"),          # 发行日期 YYYYMMDD
    ("share_scale", "REAL"),         # 份额规模(亿份)
    ("service_fee", "REAL"),         # 销售服务费率%(C类份额关键指标)
    ("dividend_total", "TEXT"),      # 成立来分红(原文)
]


def _migrate_fund_basic(conn: sqlite3.Connection) -> None:
    """fund_basic ALTER TABLE ADD COLUMN 迁移: 幂等加 15 列(已存在跳过)。"""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(fund_basic)")}
    for col, col_def in FUND_BASIC_NEW_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE fund_basic ADD COLUMN {col} {col_def}")
    conn.commit()


def _acquire_lock(nonblock: bool = True, lock_name: str = "public_fund") -> bool:
    """fcntl.flock 进程互斥（macOS 用 fcntl 非 flock 命令）。

    lock_name: 锁名(对应 data/<lock_name>.lock), 默认 public_fund.lock。
    stage0-* 用 public_fund_stage0.lock 独立锁, 不阻塞 daily/quarterly/full
    (stage0 写 risk_indicator/fee_detail/manager/overview/nav_history,
     daily 写 daily_nav/index_daily/estimation_nav, 不同表无 DB 写冲突)。
    """
    lock_path = _DATA_DIR / f"{lock_name}.lock"
    f = open(lock_path, "w")
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
    # UPSERT 而非 INSERT OR REPLACE: REPLACE=删整行重插, 会把 fetch_fund_overview
    # 补的 15 扩展列(fund_company/fund_manager 等)清成 NULL(2026-08-25 bug 修复,
    # 实测 27624 行中扩展列非空仅 18)。这里只更新基础 6 列, 扩展列保留由 Fetcher N 维护。
    conn.executemany(
        "INSERT INTO fund_basic"
        "(fund_code, fund_name, fund_type, pinyin_abbr, pinyin_full, update_date) "
        "VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(fund_code) DO UPDATE SET "
        "fund_name=excluded.fund_name, fund_type=excluded.fund_type, "
        "pinyin_abbr=excluded.pinyin_abbr, pinyin_full=excluded.pinyin_full, "
        "update_date=excluded.update_date",
        rows,
    )
    conn.commit()
    conn.close()
    print(f"[A] fund_basic 写入 {len(rows)} 行(UPSERT保扩展列), {time.time()-t:.1f}s", flush=True)
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
    try:
        df = safe_call(ak.fund_value_estimation_em, retries=2)
        if isinstance(df, Exception):
            # 修复c(2026-08-03): akshare API 故障(如 NoneType subscriptable)优雅降级返回0, 不抛异常
            print(f"[E2] fund_value_estimation_em API 故障(优雅降级返回0): {type(df).__name__}: {df}", flush=True)
            return 0
        if df is None or len(df) == 0:
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
    except Exception as e:
        # 修复c(2026-08-03): 防御性兜底, 任何意外异常(列名解析/iterrows/写DB)都不抛出, 优雅返回0
        print(f"[E2] fetch_estimation 意外异常(优雅降级返回0): {type(e).__name__}: {e}", flush=True)
        return 0


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
    # 多因子基准: hs300(大盘价值) + csi500(中盘) + gem(创业板成长), 控风格偏移
    bs_code = {"hs300": "sh.000300", "csi500": "sh.000905", "gem": "sz.399006"}.get(
        index_id, "sh.000300")

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
def fetch_nav_history(codes: list[str] | None = None, days: int = 400,
                      fund_type_filter: str = "偏股") -> int:
    """fund_open_fund_info_em 逐只拉历史净值 -> fund_daily_nav (回填历史日期)。

    反推算法需要滚动 120 日历史净值时序, 但 fund_daily_nav 只有当日(pipeline_daily 每天跑
    但 DB 可能刚重置)。本函数一次性回填头部偏股基金的历史净值, 供 _compute_position_estimate 用。
    默认 400 日 (~13个月): 120日滚动窗起始后剩 ~7个月 slopes, 与 lg 周频 overlap ~31期,
    校准稳健 + vs_lg 无重复 (2026-08-02 从 90->400 根治 vs_lg 重复+校准不稳)。

    Args:
      codes: 基金代码列表, 默认用 universe_top_funds(200) 选头部偏股基金
      days: 回填天数 (默认 400 日, 滚动 120 日回归需至少 120 日)
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
    """采集头部主动权益基金的重仓股明细, 用于申万一级口径行业配置 + 制造业拆分子行业(方案C Step1)。

    流程:
      1. 从 fund_industry_alloc 取 DISTINCT fund_code(头部主动权益基金 ~973 只, 原 L1220
         硬编码 WHERE industry_name='制造业' 已于 2026-08-02 去除: 语义误导且无实际过滤效果,
         因头部基金几乎全部配置制造业, WHERE 等同全表; 去除后语义清晰, 采全市场头部基金重仓股)
      2. 串联调 fetch_fund_portfolio_hold 拉每只当年重仓股, throttle 0.5s/只
      3. 按 report_date 对应的 quarter_label 筛选当期(如 20260630->'2026年2季度股票投资明细')
      4. 批量写入 fund_portfolio_hold 表(每 20 只批量 INSERT + 回写 progress)

    断点续采: /tmp/pf-hold-collect-progress.json 记 {done:[...], fail:[...], total:N},
    启动时读 progress 跳过 done, 重跑只补失败/未采; total 变化(新增基金)保留仍在新清单的 done,
    只补采新增基金(不重置丢已有进度)。

    Args:
      report_date: YYYYMMDD 报告期(如 '20260630'), 默认最近半年报
    Returns: {ok, fail, total, rows_written, fail_list}
    """
    if report_date is None:
        report_date = _latest_report_dates(1)[0]
    year = report_date[:4]
    target_label = _report_date_to_quarter_label(report_date)
    print(f"[I-collect] report_date={report_date} year={year} target_label={target_label}", flush=True)

    # 从 DB 取头部基金清单(去制造业硬编码, 采全市场头部主动权益基金)
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT DISTINCT fund_code FROM fund_industry_alloc "
            "ORDER BY fund_code"
        ).fetchall()
    finally:
        conn.close()
    fund_codes = [r[0] for r in rows]
    total = len(fund_codes)
    print(f"[I-collect] 头部基金 {total} 只", flush=True)
    if total == 0:
        return {"ok": 0, "fail": 0, "total": 0, "rows_written": 0, "fail_list": []}

    # 断点续采
    prog = {"done": [], "fail": [], "total": total}
    if PF_HOLD_PROGRESS_PATH.exists():
        try:
            prog = json.loads(PF_HOLD_PROGRESS_PATH.read_text(encoding="utf-8"))
            # total 变化(新增基金) -> 保留仍在新清单的 done, 只补采新增(不重置丢已有进度)
            if prog.get("total") != total:
                old_done = set(prog.get("done", []))
                retained = old_done & set(fund_codes)
                new_count = total - len(retained)
                print(f"[I-collect] progress total {prog.get('total')} != 当前 {total}, "
                      f"保留已采 {len(retained)} 只, 补采新增 {new_count} 只",
                      flush=True)
                prog = {"done": sorted(retained), "fail": [], "total": total}
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


# ── 筛选器阶段0: 7 个 fetcher (2026-08-02 新增, 为评分引擎提供数据地基) ────────
PF_STAGE0_PROGRESS_PATH = Path("/tmp/pf-stage0-collect-progress.json")
PF_STAGE0_THROTTLE = 0.4  # 逐只接口延时(秒), 反爬低加保险


def _load_stage0_progress(fetcher_name: str) -> dict:
    """读断点续采进度: {fetcher_name: {done:[], fail:[], total:N}}(经 DB 一致性闸门裁剪)。"""
    if not PF_STAGE0_PROGRESS_PATH.exists():
        return {"done": [], "fail": [], "total": 0}
    try:
        data = json.loads(PF_STAGE0_PROGRESS_PATH.read_text(encoding="utf-8"))
        prog = data.get(fetcher_name, {"done": [], "fail": [], "total": 0})
    except Exception:  # noqa: BLE001
        return {"done": [], "fail": [], "total": 0}
    return _prune_stage0_done_vs_db(fetcher_name, prog)


# 防复发闸门(2026-08-25 bug②): 断点 done 必须与 DB 实际有值状态一致。
# 病灶实证: fund_overview 断点 done=27600 全命中跳过(周日 57s"跑完"27600 只),
# 但 fund_basic 扩展列非空仅 18 行——done 只记"曾尝试成功", 感知不到"数据后来
# 被清"(bug① UPSERT 前身 REPLACE 清列), 假断点导致永不补列。
# 各 fetcher 的 DB 有效判据 = 一条返回"实际有数据 code 集"的 SQL, 加载时 done∩有效集。
_STAGE0_DB_VALIDITY: dict[str, str] = {
    "fund_overview":
        "SELECT fund_code FROM fund_basic WHERE COALESCE(fund_company,'')!=''",
    "fund_fee_detail": "SELECT DISTINCT fund_code FROM fund_fee_detail",
    # #98/#99 配套收紧(2026-08-27): fund_manager 表里 M1 base 行几乎恒存在,
    # 旧判据"表里有行"恒真 = 自爬列被清也视为有效(done=27116 而 history 非空仅 9 实证)。
    # 改为自爬产物列非空才算有效; 页面合法空的 code 由 attempt 强摘要(empty0)豁免。
    "fund_manager":
        "SELECT DISTINCT fund_code FROM fund_manager "
        "WHERE COALESCE(managed_history,'')!='' OR COALESCE(appoint_date,'')!=''",
    "fund_risk_indicator": "SELECT DISTINCT fund_code FROM fund_risk_indicator",
    # stage0-nav 同纳入闸门(#5 举一反三, 2026-08-27): 补过历史净值的 code 才算 done
    "nav": "SELECT DISTINCT fund_code FROM fund_daily_nav",
}

# codex-001 medium 修复(2026-08-26): 「合法空结果反复重采」根治——attempt 成功标记。
# 病灶: 上面业务列判据把「上游确实返回空字段/空关系」当无效(fund_company 非空是唯一判据),
# 这类 code 永远进不了 valid 集 → 断点 done 被闸门裁剪 → 反复重采浪费窗口(fund_manager
# scrape=False 路径每次还重建 base 行放大成本)。
# 修法: attempt 成功(fetch 成功且解析成功)时把 {code: 摘要} 存入 progress["attempt"],
# 闸门优先认 attempt 摘要(成功过=有效, 不再以业务列非空判定), 业务列 SQL 仅作无摘要时
# 的回退判据(兼容历史断点/数据被清场景仍能自动重采)。
_STAGE0_ATTEMPT_KEYS = {"fund_overview", "fund_fee_detail", "fund_manager",
                        "fund_risk_indicator"}


def _stage0_attempt_strong(s) -> bool:
    """attempt 摘要分级(#99, 2026-08-27): 仅「强证据」摘要豁免业务列校验。

    强证据=该 code 已确认拿全数据或确认合法空:
      - "ok{n}"           fee/manager 有实写内容 / overview 采样字段全齐
      - "empty0"          页面级确认空(manager LEGAL_EMPTY 哨兵 / fee 空行集)
      - "empty{m}/{m}"    overview n==m 全字段空 = 确认空(源侧无此基金数据)
      - "xq"/"self_calc"/"xq_mixed"   risk_indicator 数据源分支(codex004 P3,
        自算降级也算确认拿到数据, 与 P3「自算降级也算成功不反复重采」原意对齐)
    弱证据(不豁免, 回退业务列 SQL 自动校验):
      - "" / None         无摘要历史断点
      - "empty"(网络失败标记)
      - "empty{n}/{m}" 且 0<n<m —— 部分字段未齐(partial): 上游后续补字段后
        业务列判据失效 → 自动重采, 不再永久免采。
    """
    if not s:
        return False
    s = str(s)
    if s.startswith("ok"):
        return True
    if s == "empty0":
        return True
    if s in ("xq", "self_calc", "xq_mixed"):
        return True
    import re
    m = re.fullmatch(r"empty(\d+)/(\d+)", s)
    if m:
        n, total = m.group(1), m.group(2)
        return n == "0" or n == total
    return False


def _prune_stage0_done_vs_db(fetcher_name: str, prog: dict) -> dict:
    """闸门: 断点 done 与 DB 实际有值 code 集取交集, 失效部分自动重采不报完成。

    codex-001 medium 后语义: progress["attempt"] 里记了成功摘要的 code 视为永久有效
    (fetch 成功≠业务列非空, 合法空结果不再反复重采); 无摘要的历史断点回退业务列 SQL 判定。
    #99 分级修正(2026-08-27): 只有强证据摘要(ok/确认空)直接放行; partial 摘要
    (部分字段未齐)与无摘要同等对待, 回退业务列 SQL——防"上游后来补了字段但断点
    已标完成永不补采"。兼容历史格式("empty"/无斜杠弱标记一律走 SQL)。

    F-02 修复(2026-08-28): manager/nav 的历史 done 大量无 attempt 摘要,
    闸门裁剪后 nav 26121/27579、manager 仅 9/27116 → 重采成本从分钟级回跳小时级。
    修法: 无摘要 done 统一补 empty0 占位(F-02 核心修复, 防小时级重采),
    同时记入 pending 复盘集合, 下次专用任务重新扫描时不永久免采。
    占位摘要语义=「该 code 曾有页面响应, 但数据未落库/已被清」, 不是「确认无数据」。
    """
    sql = _STAGE0_DB_VALIDITY.get(fetcher_name)
    done = prog.get("done") or []
    if not sql or not done:
        return prog
    attempts = prog.get("attempt") or {}
    # 无强证据摘要的 done → 补 empty0 占位(F-02 核心修复, 防小时级重采)
    no_att = [c for c in done if not _stage0_attempt_strong(attempts.get(c))]
    if no_att:
        for c in no_att:
            if not attempts.get(c):
                attempts[c] = "empty0"
        prog["attempt"] = attempts
        prog.setdefault("pending_review", []).extend(
            [c for c in no_att if c not in prog.get("pending_review", [])])
    # 仅强证据摘要放行(#99); partial/无摘要回退业务列判据
    attempted = [c for c in done if _stage0_attempt_strong(attempts.get(c))]
    rest = [c for c in done if not _stage0_attempt_strong(attempts.get(c))]
    if not rest:
        prog["done"] = done
        return prog
    try:
        conn = get_conn()
        try:
            valid = {r[0] for r in conn.execute(sql).fetchall()}
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        print(f"  [progress] WARN 闸门查询失败(本次跳过校验): {e}", flush=True)
        return prog
    retained_rest = [c for c in rest if c in valid]
    if len(retained_rest) < len(rest):
        print(f"  [progress] 闸门: {fetcher_name} 无摘要done={len(rest)} "
              f"vs DB实际有值={len(valid)}, 裁剪至 {len(retained_rest)}(失效部分将重采)",
              flush=True)
    prog["done"] = attempted + retained_rest
    return prog


def _save_stage0_progress(fetcher_name: str, prog: dict) -> None:
    """写断点续采进度(按 fetcher_name 分区, 互不干扰)。"""
    try:
        data = {}
        if PF_STAGE0_PROGRESS_PATH.exists():
            data = json.loads(PF_STAGE0_PROGRESS_PATH.read_text(encoding="utf-8"))
        data[fetcher_name] = prog
        PF_STAGE0_PROGRESS_PATH.write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"  [progress] WARN 写入失败: {e}", flush=True)


def _stage0_reset_prog(old_prog: dict, codes: list[str], total: int) -> dict:
    """重建 progress 结构(宇宙变化时): done/attempt 都按新宇宙裁剪保留(codex-001 medium)。

    attempt 摘要随 done 同口径裁剪——code 还在宇宙里且成功过就保留, 不因 total 变化丢摘要。
    """
    old_done = set(old_prog.get("done", []))
    old_att = old_prog.get("attempt") or {}
    retained = old_done & set(codes)
    return {
        "done": sorted(retained),
        "fail": [],
        "total": total,
        "attempt": {c: s for c, s in old_att.items() if c in set(codes)},
    }


def _parse_overview_date(s: str) -> str:
    """解析 fund_overview_em 日期字段 'YYYY年MM月DD日' -> 'YYYYMMDD'。"""
    if not s:
        return ""
    import re
    m = re.search(r'(\d{4})年(\d{2})月(\d{2})日', str(s))
    return f"{m.group(1)}{m.group(2)}{m.group(3)}" if m else ""


def _parse_overview_scale(s: str) -> float | None:
    """解析 fund_overview_em 规模字段 '197.40亿元（截止至：2026年06月30日）' -> 197.40。"""
    if not s:
        return None
    import re
    m = re.search(r'([\d.]+)\s*亿', str(s))
    return _safe_float(m.group(1)) if m else None


def _parse_overview_fee(s: str) -> float | None:
    """解析 fund_overview_em 费率字段 '1.00%（每年）' / '0.80%（前端）' -> 1.00。"""
    if not s:
        return None
    import re
    m = re.search(r'([\d.]+)\s*%', str(s))
    return _safe_float(m.group(1)) if m else None


def _parse_setup_date_scale(s: str) -> tuple[str, float | None]:
    """解析 fund_overview_em '成立日期/规模' 合并字段。
    '2015年05月27日 / 3.965亿份' -> ('20150527', 3.965)
    """
    if not s:
        return "", None
    import re
    setup = ""
    m = re.search(r'(\d{4})年(\d{2})月(\d{2})日', str(s))
    if m:
        setup = f"{m.group(1)}{m.group(2)}{m.group(3)}"
    m2 = re.search(r'([\d.]+)\s*亿份', str(s))
    share = _safe_float(m2.group(1)) if m2 else None
    return setup, share


# ── Fetcher J: 9区间收益率(金矿, 一次拿全市场) ─────────────────────────────────
def fetch_fund_performance() -> int:
    """fund_open_fund_rank_em('全部') 一次拿全市场20070只9区间收益率 -> fund_performance。

    金矿接口: 2.5s 拿全市场, 9区间收益率(近1周/1月/3月/6月/1年/2年/3年/今年/成立来)。
    """
    print("[J] fetch_fund_performance() ...", flush=True)
    t = time.time()
    df = safe_call(ak.fund_open_fund_rank_em, retries=2, symbol="全部")
    if isinstance(df, Exception) or df is None or len(df) == 0:
        print(f"[J] FAIL: {df}", flush=True)
        return 0
    today = dt.date.today().strftime("%Y%m%d")
    rows = []
    for _, r in df.iterrows():
        code = str(r.get("基金代码", "")).strip()
        if not code:
            continue
        rows.append((
            code, today,
            _safe_float(r.get("单位净值")),
            _safe_float(r.get("累计净值")),
            _safe_float(r.get("日增长率")),
            _safe_float(r.get("近1周")),
            _safe_float(r.get("近1月")),
            _safe_float(r.get("近3月")),
            _safe_float(r.get("近6月")),
            _safe_float(r.get("近1年")),
            _safe_float(r.get("近2年")),
            _safe_float(r.get("近3年")),
            _safe_float(r.get("今年来")),
            _safe_float(r.get("成立来")),
            _safe_float(str(r.get("手续费", "")).replace("%", "")),
        ))
    conn = get_conn()
    conn.executemany(
        "INSERT OR REPLACE INTO fund_performance"
        "(fund_code, update_date, unit_nav, acc_nav, day_growth, "
        "return_1w, return_1m, return_3m, return_6m, return_1y, return_2y, "
        "return_3y, return_ytd, return_since_inception, fee_rate) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    print(f"[J] fund_performance 写入 {len(rows)} 行, {time.time()-t:.1f}s", flush=True)
    return len(rows)


# ── Fetcher K: 4家评级(汇总, 一次拿全市场) ─────────────────────────────────────
def fetch_fund_rating() -> int:
    """fund_rating_all 一次拿全市场18096只4家评级 -> fund_rating。

    4家: 上海证券/招商证券/济安金信/晨星(任务描述'银河'实测是'上海证券')。
    """
    print("[K] fetch_fund_rating() ...", flush=True)
    t = time.time()
    df = safe_call(ak.fund_rating_all, retries=2)
    if isinstance(df, Exception) or df is None or len(df) == 0:
        print(f"[K] FAIL: {df}", flush=True)
        return 0
    today = dt.date.today().strftime("%Y%m%d")
    rows = []
    for _, r in df.iterrows():
        code = str(r.get("代码", "")).strip()
        if not code:
            continue
        rows.append((
            code, today,
            _safe_float(r.get("上海证券")),
            _safe_float(r.get("招商证券")),
            _safe_float(r.get("济安金信")),
            _safe_float(r.get("晨星评级")),
            _safe_float(r.get("5星评级家数")),
            today,
        ))
    conn = get_conn()
    conn.executemany(
        "INSERT OR REPLACE INTO fund_rating"
        "(fund_code, rating_date, shanghai_securities, cms, jajx, "
        "morningstar, five_star_count, update_date) "
        "VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    print(f"[K] fund_rating 写入 {len(rows)} 行, {time.time()-t:.1f}s", flush=True)
    return len(rows)


# ── Fetcher L: 申赎状态(汇总, 一次拿全市场) ─────────────────────────────────────
def fetch_fund_purchase_status() -> int:
    """fund_purchase_em 一次拿全市场27115只申赎状态 -> fund_purchase_status。"""
    print("[L] fetch_fund_purchase_status() ...", flush=True)
    t = time.time()
    df = safe_call(ak.fund_purchase_em, retries=2)
    if isinstance(df, Exception) or df is None or len(df) == 0:
        print(f"[L] FAIL: {df}", flush=True)
        return 0
    today = dt.date.today().strftime("%Y%m%d")
    rows = []
    for _, r in df.iterrows():
        code = str(r.get("基金代码", "")).strip()
        if not code:
            continue
        next_open = r.get("下一开放日")
        next_open_str = ""
        if next_open is not None:
            try:
                next_open_str = _to_yyyymmdd(next_open)
            except (ValueError, TypeError):
                next_open_str = ""  # NaT 等异常值留空
        rows.append((
            code, today,
            str(r.get("申购状态", "")).strip(),
            str(r.get("赎回状态", "")).strip(),
            next_open_str,
            _safe_float(r.get("购买起点")),
            _safe_float(r.get("日累计限定金额")),
        ))
    conn = get_conn()
    conn.executemany(
        "INSERT OR REPLACE INTO fund_purchase_status"
        "(fund_code, update_date, purchase_status, redeem_status, "
        "next_open_date, purchase_min, daily_limit) "
        "VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    print(f"[L] fund_purchase_status 写入 {len(rows)} 行, {time.time()-t:.1f}s", flush=True)
    return len(rows)


# ── Fetcher M: 基金经理(汇总 + 自爬fundf10补任职历史) ──────────────────────────
PF_MANAGER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
PF_MANAGER_URL_TMPL = "https://fundf10.eastmoney.com/jjjl_{code}.html"


# codex004 P2: 合法空结果哨兵——页面 200 且解析成功但「无任职历史+无管过基金」。
# 与 None(网络/HTTP 失败, 应重试)显式区分, 主循环据此把合法空 code 加入 done_set 不再重采。
_PF_MGR_LEGAL_EMPTY = "LEGAL_EMPTY"


def _scrape_fundf10_manager(code: str, retries: int = 2) -> dict | str | None:
    """自爬 fundf10 manager 页, 返回经理归属信息(#98, 2026-08-27)。

    解析:
      任职变动表(表头含 起始期/截止期/基金经理): 每行=一段任期组合,
        经理列是空格分隔的姓名列表——
        - appoint_map: 每位经理首次出现行的起始期 = 其对本基金的任命日
        - current_managers: 截止期=="至今" 行的经理名单(在任组合)
        - appoint_date: 兼容保留 = 至今行的起始期(原口径)
      管过基金表(表头含 基金代码+任职天数): 首张表构建 managed_history JSON
        [{code,name,type,start,end,return}] —— 注意页面无法确证该表归属哪位
        经理, 写库时只落到首位在任者行, 不再刷全部经理行(#98 根治)。
    Returns: {appoint_date, managed_history(JSON str), current_managers,
              appoint_map}; _PF_MGR_LEGAL_EMPTY(解析成功的合法空); None(网络失败)
    """
    import re
    from io import StringIO
    import pandas as pd
    from bs4 import BeautifulSoup
    import requests

    url = PF_MANAGER_URL_TMPL.format(code=code)
    headers = {"User-Agent": PF_MANAGER_UA, "Referer": "https://fundf10.eastmoney.com/"}
    last_err = None
    for i in range(retries + 1):
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}"
                time.sleep(0.8 * (i + 1))
                continue
            soup = BeautifulSoup(r.text, features="lxml")
            tables = soup.find_all("table")
            appoint_date = ""
            current_managers: list[str] = []
            appoint_map: dict[str, str] = {}
            # 任职变动表: 扫全行, per-经理任命日 + 在任名单(#98 经理归属依据)
            for tbl in tables:
                rows_html = tbl.find_all("tr")
                if not rows_html:
                    continue
                header = [td.get_text(strip=True) for td in rows_html[0].find_all(["th", "td"])]
                if "起始期" in header and "截止期" in header:
                    for tr in rows_html[1:]:
                        cells = [td.get_text(strip=True) for td in tr.find_all(["th", "td"])]
                        start = _to_yyyymmdd(cells[0]) if cells else ""
                        if len(cells) >= 4 and start:
                            # F-01 fix(2026-08-28): 从 <a> 标签提取经理列表,
                            # 而非 .split() 空格切分(两经理名紧邻会粘连成一个假经理)。
                            # 对老页面(无链接单元格)保留文本 split 作为 fallback,
                            # 仍需处理两字姓名/复合姓的误切。
                            nm_cells = tr.find_all(["th", "td"])[2] if len(tr.find_all(["th", "td"])) >= 3 else None
                            if nm_cells:
                                links = nm_cells.find_all("a")
                                if links:
                                    # 优先取 <a> 文本列表(东方财富现行页格式)
                                    names = [a.get_text(strip=True) for a in links if a.get_text(strip=True)]
                                else:
                                    # 老页面无链接: 用空格 split(仍存在两字名误切风险, 需人工补充)
                                    names = [nm for nm in (nm_cells.get_text(strip=True) or "").split() if nm]
                            else:
                                names = [nm for nm in (cells[2] or "").split() if nm]
                            # 每位经理首次出现的任期起始 = 任命日(按行序首个命中)
                            for nm in names:
                                if nm not in appoint_map:
                                    appoint_map[nm] = start
                            if cells[1] == "至今":
                                if not appoint_date:
                                    appoint_date = start
                                for nm in names:
                                    if nm not in current_managers:
                                        current_managers.append(nm)
                    if appoint_date or appoint_map or current_managers:
                        break
            # table[2]: 经理管过的基金 -> managed_history JSON
            managed_history: list[dict] = []
            for tbl in tables:
                rows_html = tbl.find_all("tr")
                if not rows_html:
                    continue
                header = [td.get_text(strip=True) for td in rows_html[0].find_all(["th", "td"])]
                if "基金代码" in header and "任职天数" in header:
                    for tr in rows_html[1:]:
                        cells = [td.get_text(strip=True) for td in tr.find_all(["th", "td"])]
                        if len(cells) >= 7:
                            managed_history.append({
                                "code": cells[0],
                                "name": cells[1],
                                "type": cells[2],
                                "start": _to_yyyymmdd(cells[3]),
                                "end": cells[4] if cells[4] != "至今" else "",
                                "tenure_days": cells[5],
                                "return": _safe_float(cells[6].replace("%", "")),
                            })
                    break
            if not appoint_date and not appoint_map and not managed_history:
                # codex004 P2: 页面成功解析的合法空(该基金确无任职历史/管过基金),
                # 用哨兵与网络失败的 None 区分
                return _PF_MGR_LEGAL_EMPTY
            # F-04(2026-08-28): 返回原始 managed_history 列表而非 JSON 串,
            # 便于调用方按经理名拆分 per-manager 史, 不再整段只落首位在任者。
            return {
                "appoint_date": appoint_date,
                "managed_history_list": managed_history,
                "current_managers": current_managers,
                "appoint_map": appoint_map,
            }
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(0.8 * (i + 1))
    return None


def fetch_fund_manager(scrape: bool = True, codes: list[str] | None = None) -> int:
    """fund_manager_em 全市场 + 自爬fundf10补任职历史 -> fund_manager。

    流程:
      1. fund_manager_em 拿全市场35436行经理-基金关系(姓名/公司/基金代码/累计从业时间/资产规模/最佳回报)
      2. 批量写入 fund_manager 表基础信息(managed_count/managed_scale/best_return/work_days)
      3. (可选) 逐只自爬 fundf10 manager 页补 appoint_date + managed_history + tenure_days
      4. 断点续采: 自爬部分用 PF_STAGE0_PROGRESS_PATH["fund_manager"]

    Args:
      scrape: 是否自爬fundf10补任职历史(全量27409只~3h, 小样本验证可限codes)
      codes: 限制自爬的基金代码列表(小样本验证用), None=全市场
    Returns: 写入行数
    """
    print("[M] fetch_fund_manager() ...", flush=True)
    t0 = time.time()
    # M1: fund_manager_em 拿全市场经理-基金关系
    df = safe_call(ak.fund_manager_em, retries=2)
    if isinstance(df, Exception) or df is None or len(df) == 0:
        print(f"[M] fund_manager_em FAIL: {df}", flush=True)
        return 0
    today = dt.date.today().strftime("%Y%m%d")
    base_rows: list[tuple] = []
    for _, r in df.iterrows():
        code = str(r.get("现任基金代码", "")).strip()
        name = str(r.get("姓名", "")).strip()
        if not code or not name:
            continue
        work_days = _safe_float(r.get("累计从业时间"))
        managed_scale = _safe_float(r.get("现任基金资产总规模"))
        best_return = _safe_float(r.get("现任基金最佳回报"))
        # 9列: fund_code, manager_name, managed_count(待反算), managed_scale,
        #      best_return, managed_history(None,自爬补), tenure_days(None,自爬补),
        #      work_days, update_date
        base_rows.append((code, name, None, managed_scale, best_return,
                          None, None, int(work_days) if work_days else None, today))
    # 反算 managed_count: 每个经理出现的基金数
    from collections import Counter
    mgr_count = Counter(r[1] for r in base_rows)
    base_rows = [(r[0], r[1], mgr_count[r[1]], r[3], r[4], r[5], r[6], r[7], r[8])
                 for r in base_rows]
    conn = get_conn()
    # UPSERT 而非 INSERT OR REPLACE(codex-001 medium 同根根治, 2026-08-26): REPLACE=
    # 删整行重插, 会把 M2 自爬补的 appoint_date/managed_history/tenure_days 清成 NULL
    # (与 fund_basic bug① REPLACE 清扩展列同病)——M1 重跑(如 scrape=False 路径/重试)
    # 即毁掉已爬历史, 且 attempt 断点认为 done 不会补爬 = 数据永久丢失面。只更新 M1
    # 拥有的 5 列, 自爬列保留由 M2 维护。
    conn.executemany(
        "INSERT INTO fund_manager"
        "(fund_code, manager_name, managed_count, managed_scale, best_return, "
        "managed_history, tenure_days, work_days, update_date) "
        "VALUES (?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(fund_code, manager_name) DO UPDATE SET "
        "managed_count=excluded.managed_count, managed_scale=excluded.managed_scale, "
        "best_return=excluded.best_return, work_days=excluded.work_days, "
        "update_date=excluded.update_date",
        base_rows,
    )
    conn.commit()
    conn.close()
    print(f"[M1] fund_manager_em 写入 {len(base_rows)} 行(UPSERT保自爬列), "
          f"{time.time()-t0:.1f}s", flush=True)

    if not scrape:
        return len(base_rows)

    # M2: 逐只自爬 fundf10 补 appoint_date + managed_history + tenure_days
    if codes is None:
        codes = sorted(set(r[0] for r in base_rows))
    total = len(codes)
    print(f"[M2] 自爬 fundf10 {total} 只补任职历史 ...", flush=True)
    prog = _load_stage0_progress("fund_manager")
    if prog.get("total") != total:
        prog = _stage0_reset_prog(prog, codes, total)
    done_set = set(prog.get("done", []))
    attempts = prog.setdefault("attempt", {})
    ok = fail = nomatch = 0
    BATCH = 20
    pending: list[tuple] = []
    for i, code in enumerate(codes, 1):
        if code in done_set:
            ok += 1
        else:
            try:
                result = _scrape_fundf10_manager(code)
                # codex004 P2 三态 + #98 经理归属(2026-08-27):
                #   dict=有数据 / _PF_MGR_LEGAL_EMPTY=页面解析成功的合法空(empty0 确认空,
                #   跨轮不重采) / None=网络或 HTTP 失败(标 empty 留重试面)
                if result == _PF_MGR_LEGAL_EMPTY:
                    attempts[code] = "empty0"
                    done_set.add(code)
                    ok += 1
                elif result:
                    cur = result.get("current_managers") or []
                    amap = result.get("appoint_map") or {}
                    # F-04(2026-08-28): managed_history_list 返回原始列表,
                    # 按经理名拆分 -> 每位经理写入自己的历史, 不再只落首位在任者。
                    mgr_history_list = result.get("managed_history_list") or []
                    history_names = {h.get("name") for h in mgr_history_list}
                    _mc = get_conn()
                    try:
                        db_mgrs = {r[0] for r in _mc.execute(
                            "SELECT manager_name FROM fund_manager WHERE fund_code=?",
                            (code,)).fetchall()}
                    finally:
                        _mc.close()
                    targets = [nm for nm in cur if nm in db_mgrs]
                    if targets:
                        for nm in targets:
                            appoint = amap.get(nm, "")
                            # 按经理名筛出该经理的管过基金史(JSON per-manager 结构)
                            mgr_hist = [h for h in mgr_history_list if h.get("name") == nm]
                            hist_one = json.dumps(mgr_hist, ensure_ascii=False) if mgr_hist else None
                            tenure = None
                            if appoint:
                                ad = dt.datetime.strptime(appoint, "%Y%m%d").date()
                                tenure = (dt.date.today() - ad).days
                            pending.append((appoint, appoint, hist_one, tenure, code, nm))
                        attempts[code] = f"ok{len(mgr_history_list)}"
                        done_set.add(code)
                        ok += 1
                    else:
                        # F-03(2026-08-28): 页面与库现任名单脱节时不标完成,
                        # 记录待复盘集合; pending 前缀=弱证据, 回退业务列 SQL 校验,
                        # 防成为多数基金持久免采路径(当前扩展数据尚未回填)。
                        attempts[code] = f"pending{len(mgr_history_list)}nm"
                        nomatch += 1
                else:
                    attempts[code] = "empty"
                    fail += 1
            except Exception as e:  # noqa: BLE001
                fail += 1
                if fail <= 3:
                    print(f"  [M2] {code} 异常: {type(e).__name__} {e}", flush=True)
            time.sleep(PF_STAGE0_THROTTLE)
        if (len(pending) >= BATCH) or i == total:
            if pending:
                conn = get_conn()
                # #98(2026-08-27): WHERE 带 manager_name 键 + COALESCE/CASE 保旧——
                # 文本空串与 None 都不覆写已有值, 多经理行互不清除
                conn.executemany(
                    "UPDATE fund_manager SET "
                    "appoint_date=CASE WHEN ?!='' THEN ? ELSE appoint_date END, "
                    "managed_history=COALESCE(?, managed_history), "
                    "tenure_days=COALESCE(?, tenure_days) "
                    "WHERE fund_code=? AND manager_name=?",
                    pending,
                )
                conn.commit()
                conn.close()
                pending = []
            prog["done"] = sorted(done_set)
            prog["fail"] = []
            prog["total"] = total
            _save_stage0_progress("fund_manager", prog)
            elapsed = time.time() - t0
            eta = (elapsed / i) * (total - i) if i > 0 else 0
            print(f"  [M2] {i}/{total} ({i*100/total:.1f}%) ok={ok} fail={fail} "
                  f"nomatch={nomatch} elapsed={elapsed:.0f}s eta={eta:.0f}s", flush=True)
    print(f"[M2] 自爬完成: ok={ok} fail={fail} nomatch={nomatch} total={total} "
          f"耗时={time.time()-t0:.0f}s", flush=True)
    return len(base_rows)


# ── Fetcher N: fund_basic 补全(逐只 fund_overview_em) ─────────────────────────
def fetch_fund_overview(codes: list[str] | None = None) -> int:
    """fund_overview_em 逐只补 fund_basic 15新列(18字段金矿)。

    解析 fund_overview_em 18字段, UPDATE fund_basic 的 15 新列:
      fund_company/fund_manager/setup_date/scale/management_fee/custody_fee/
      purchase_fee/custodian/strategy/benchmark/tracking_target/
      issue_date/share_scale/service_fee/dividend_total

    Args:
      codes: 基金代码列表, None=全市场(fund_basic 全量27409只, ~6.2h挂凌晨)
    Returns: 成功更新行数
    """
    print("[N] fetch_fund_overview() ...", flush=True)
    t0 = time.time()
    if codes is None:
        conn = get_conn()
        try:
            rows_q = conn.execute("SELECT fund_code FROM fund_basic ORDER BY fund_code").fetchall()
        finally:
            conn.close()
        codes = [r[0] for r in rows_q]
    total = len(codes)
    print(f"[N] 逐只 fund_overview_em {total} 只 ...", flush=True)

    prog = _load_stage0_progress("fund_overview")
    if prog.get("total") != total:
        prog = _stage0_reset_prog(prog, codes, total)
    done_set = set(prog.get("done", []))
    attempts = prog.setdefault("attempt", {})
    ok = fail = 0
    BATCH = 20
    pending: list[tuple] = []
    today = dt.date.today().strftime("%Y%m%d")

    for i, code in enumerate(codes, 1):
        if code in done_set:
            ok += 1
        else:
            try:
                df = safe_call(ak.fund_overview_em, retries=1, symbol=code)
                if isinstance(df, Exception) or df is None or len(df) == 0:
                    fail += 1
                else:
                    r = df.iloc[0]
                    setup, share = _parse_setup_date_scale(r.get("成立日期/规模", ""))
                    # codex-001 medium: attempt 成功摘要(空值字段计数)——fetch 成功即记,
                    # 合法空结果(全字段空)不再被业务列判据反复重采
                    _vals = [
                        str(r.get("基金管理人", "")).strip(),
                        str(r.get("基金经理人", "")).strip(),
                        setup, share,
                        str(r.get("业绩比较基准", "")).strip(),
                    ]
                    attempts[code] = f"empty{sum(1 for v in _vals if not v)}/{len(_vals)}"
                    pending.append((
                        str(r.get("基金管理人", "")).strip(),     # fund_company
                        str(r.get("基金经理人", "")).strip(),      # fund_manager
                        setup,                                     # setup_date
                        _parse_overview_scale(r.get("净资产规模", "")),  # scale
                        _parse_overview_fee(r.get("管理费率", "")),      # management_fee
                        _parse_overview_fee(r.get("托管费率", "")),      # custody_fee
                        _parse_overview_fee(r.get("最高认购费率", "")),   # purchase_fee
                        str(r.get("基金托管人", "")).strip(),      # custodian
                        str(r.get("基金全称", "")).strip(),        # strategy
                        str(r.get("业绩比较基准", "")).strip(),    # benchmark
                        str(r.get("跟踪标的", "")).strip(),        # tracking_target
                        _parse_overview_date(r.get("发行日期", "")),  # issue_date
                        share,                                     # share_scale
                        _parse_overview_fee(r.get("销售服务费率", "")),  # service_fee
                        str(r.get("成立来分红", "")).strip(),      # dividend_total
                        today,                                     # update_date
                        code,                                      # WHERE fund_code
                    ))
                    ok += 1
                    done_set.add(code)
            except Exception as e:  # noqa: BLE001
                fail += 1
                if fail <= 3:
                    print(f"  [N] {code} 异常: {type(e).__name__} {e}", flush=True)
            time.sleep(PF_STAGE0_THROTTLE)

        if (len(pending) >= BATCH) or i == total:
            if pending:
                conn = get_conn()
                # #100 UPSERT 保护语义(2026-08-27): 文本列 COALESCE(NULLIF(新,''),旧)、
                # 数值列 COALESCE(新,旧)——本轮接口返回空字段时保留 DB 已有值, 只有
                # 非空新值才覆写; 防"二次补跑返回部分空"静默清掉先前采集成果。
                conn.executemany(
                    "UPDATE fund_basic SET "
                    "fund_company=COALESCE(NULLIF(?,''),fund_company), "
                    "fund_manager=COALESCE(NULLIF(?,''),fund_manager), "
                    "setup_date=COALESCE(NULLIF(?,''),setup_date), "
                    "scale=COALESCE(?,scale), "
                    "management_fee=COALESCE(?,management_fee), "
                    "custody_fee=COALESCE(?,custody_fee), "
                    "purchase_fee=COALESCE(?,purchase_fee), "
                    "custodian=COALESCE(NULLIF(?,''),custodian), "
                    "strategy=COALESCE(NULLIF(?,''),strategy), "
                    "benchmark=COALESCE(NULLIF(?,''),benchmark), "
                    "tracking_target=COALESCE(NULLIF(?,''),tracking_target), "
                    "issue_date=COALESCE(NULLIF(?,''),issue_date), "
                    "share_scale=COALESCE(?,share_scale), "
                    "service_fee=COALESCE(?,service_fee), "
                    "dividend_total=COALESCE(NULLIF(?,''),dividend_total), "
                    "update_date=? WHERE fund_code=?",
                    pending,
                )
                conn.commit()
                conn.close()
                pending = []
            prog["done"] = sorted(done_set)
            prog["fail"] = []
            prog["total"] = total
            _save_stage0_progress("fund_overview", prog)
            elapsed = time.time() - t0
            eta = (elapsed / i) * (total - i) if i > 0 else 0
            print(f"  [N] {i}/{total} ({i*100/total:.1f}%) ok={ok} fail={fail} "
                  f"elapsed={elapsed:.0f}s eta={eta:.0f}s", flush=True)
    print(f"[N] 完成: ok={ok} fail={fail} total={total} "
          f"耗时={time.time()-t0:.0f}s", flush=True)
    # 防复发自检(bug② 闸门配套): 收尾核对「断点 done 数 vs DB 扩展列实际有值数」,
    # 不一致打 WARN——防"假完成标记"再次静默产生, 下次加载侧闸门会自动裁剪重采。
    # codex-001 medium 后口径: done 含「确认空结果」(attempt 强摘要 empty0 / 全字段空),
    # 比对基准改为 DB有值数 + 确认空数, 纯业务列比对会对合法空结果误报 WARN。
    # #99 分级后(2026-08-27)partial(部分字段未齐)不计入空确认——它本就该被闸门
    # 回退业务列校验、在关键字段补齐前保持可重采。
    try:
        conn = get_conn()
        try:
            db_valid = conn.execute(
                "SELECT COUNT(*) FROM fund_basic WHERE COALESCE(fund_company,'')!=''"
            ).fetchone()[0]
        finally:
            conn.close()
        attempts = prog.get("attempt") or {}
        empty_n = sum(1 for c in prog.get("done", [])
                      if _stage0_attempt_strong(attempts.get(c))
                      and str(attempts.get(c)).startswith("empty"))
        done_n = len(prog.get("done", []))
        if abs(done_n - db_valid - empty_n) > max(50, int(total * 0.01)):
            print(f"  [N] WARN 一致性: 断点done={done_n}(含合法空{empty_n}) vs "
                  f"DB扩展列有值={db_valid}, 疑似数据被清/断点失真(下次运行闸门自动重采)",
                  flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  [N] WARN 一致性自检失败: {e}", flush=True)
    return ok


# ── Fetcher P: 费率分档(逐只 fund_individual_detail_info_xq) ───────────────────
def fetch_fund_fee_detail(codes: list[str] | None = None) -> int:
    """fund_individual_detail_info_xq 逐只拿费率分档 -> fund_fee_detail。

    每只9行: 买入规则3档/卖出规则4档/其他费用2档。
    fee_type映射: 买入规则->purchase, 卖出规则->redeem, 其他费用->other。

    Args:
      codes: 基金代码列表, None=全市场(27409只~4.5h挂凌晨)
    Returns: 写入行数
    """
    print("[P] fetch_fund_fee_detail() ...", flush=True)
    t0 = time.time()
    if codes is None:
        conn = get_conn()
        try:
            rows_q = conn.execute("SELECT fund_code FROM fund_basic ORDER BY fund_code").fetchall()
        finally:
            conn.close()
        codes = [r[0] for r in rows_q]
    total = len(codes)
    print(f"[P] 逐只 fund_individual_detail_info_xq {total} 只 ...", flush=True)

    prog = _load_stage0_progress("fund_fee_detail")
    if prog.get("total") != total:
        prog = _stage0_reset_prog(prog, codes, total)
    done_set = set(prog.get("done", []))
    attempts = prog.setdefault("attempt", {})
    ok = fail = 0
    total_rows = 0
    BATCH = 50
    pending: list[tuple] = []
    today = dt.date.today().strftime("%Y%m%d")
    FEE_TYPE_MAP = {"买入规则": "purchase", "卖出规则": "redeem", "其他费用": "other"}

    for i, code in enumerate(codes, 1):
        if code in done_set:
            ok += 1
        else:
            try:
                df = safe_call(ak.fund_individual_detail_info_xq, retries=1, symbol=code)
                if isinstance(df, Exception) or df is None or len(df) == 0:
                    fail += 1
                else:
                    rows_written = 0
                    for idx, (_, r) in enumerate(df.iterrows()):
                        fee_type_cn = str(r.get("费用类型", "")).strip()
                        fee_type = FEE_TYPE_MAP.get(fee_type_cn, "other")
                        condition = str(r.get("条件或名称", "")).strip()
                        fee = _safe_float(r.get("费用"))
                        pending.append((code, fee_type, idx, condition, fee, today))
                        rows_written += 1
                    if rows_written:
                        ok += 1
                        total_rows += rows_written
                        attempts[code] = f"ok{rows_written}"
                        done_set.add(code)
                    else:
                        # codex-001 medium: 上游返回空行集=合法空结果, 记摘要不重采
                        attempts[code] = "empty0"
                        ok += 1
                        done_set.add(code)
            except Exception as e:  # noqa: BLE001
                fail += 1
                if fail <= 3:
                    print(f"  [P] {code} 异常: {type(e).__name__} {e}", flush=True)
            time.sleep(PF_STAGE0_THROTTLE)

        if (len(pending) >= BATCH) or i == total:
            if pending:
                conn = get_conn()
                conn.executemany(
                    "INSERT OR REPLACE INTO fund_fee_detail"
                    "(fund_code, fee_type, tier_index, condition_desc, fee_rate, update_date) "
                    "VALUES (?,?,?,?,?,?)",
                    pending,
                )
                conn.commit()
                conn.close()
                pending = []
            prog["done"] = sorted(done_set)
            prog["fail"] = []
            prog["total"] = total
            _save_stage0_progress("fund_fee_detail", prog)
            elapsed = time.time() - t0
            eta = (elapsed / i) * (total - i) if i > 0 else 0
            print(f"  [P] {i}/{total} ({i*100/total:.1f}%) ok={ok} fail={fail} "
                  f"rows={total_rows} elapsed={elapsed:.0f}s eta={eta:.0f}s", flush=True)
    print(f"[P] 完成: ok={ok} fail={fail} total={total} rows={total_rows} "
          f"耗时={time.time()-t0:.0f}s", flush=True)
    return total_rows


# ── Fetcher O: 风险指标(逐只 xq + 失败降级净值自算) ────────────────────────────
XQ_PERIOD_MAP = {"近1年": "1y", "近3年": "3y", "近5年": "5y"}
PERIOD_DAYS = {"1y": 365, "3y": 1095, "5y": 1825}
RF_ANNUAL = 2.0  # 无风险利率年化%(简化, 用2%)


def _compute_risk_from_nav(fund_code: str, period: str, benchmark: str = "hs300") -> dict | None:
    """从 fund_daily_nav 净值时序自算风险指标(降级用)。

    算: sharpe/sortino/calmar/max_drawdown/annual_volatility/downside_risk/information_ratio/alpha
    阶段1 Step2(2026-07-20): 补 IR + Alpha (需 fund_index_daily 基准回归)

    Args:
      fund_code: 基金代码
      period: '1y'/'3y'/'5y'
      benchmark: 'hs300'/'csi500'/'gem'
    Returns: dict 或 None(数据不足)
    """
    import math
    from statistics import stdev, mean

    days = PERIOD_DAYS.get(period, 365)
    start_date = (dt.date.today() - dt.timedelta(days=days + 30)).strftime("%Y%m%d")
    conn = get_conn()
    try:
        nav_rows = conn.execute(
            "SELECT date, unit_nav FROM fund_daily_nav "
            "WHERE fund_code=? AND date>=? AND unit_nav IS NOT NULL "
            "ORDER BY date", (fund_code, start_date)
        ).fetchall()
        # 同时取基准指数日涨跌（IR + Alpha 回归用）
        bench_rows = conn.execute(
            "SELECT date, pct_change FROM fund_index_daily "
            "WHERE index_id=? AND date>=? AND pct_change IS NOT NULL "
            "ORDER BY date", (benchmark, start_date)
        ).fetchall() if benchmark else []
    finally:
        conn.close()
    if len(nav_rows) < 30:
        return None

    navs = [r[1] for r in nav_rows]
    nav_dates = [r[0] for r in nav_rows]
    returns = [(navs[i] - navs[i - 1]) / navs[i - 1]
               for i in range(1, len(navs)) if navs[i - 1] > 0]
    ret_dates = nav_dates[1:len(returns) + 1]  # 对齐收益日期 (收益是 i vs i-1, 用 i 的日期)
    if len(returns) < 20:
        return None

    avg_ret = mean(returns)
    vol_daily = stdev(returns) if len(returns) > 1 else 0.0
    annual_vol = vol_daily * math.sqrt(252) * 100  # 转%

    # 年化收益率(几何)
    total_ret = (navs[-1] / navs[0] - 1) if navs[0] > 0 else 0.0
    years = len(returns) / 252.0
    annual_ret = ((1 + total_ret) ** (1 / years) - 1) * 100 if years > 0 else 0.0

    sharpe = (annual_ret - RF_ANNUAL) / annual_vol if annual_vol > 0 else 0.0

    neg_returns = [r for r in returns if r < 0]
    downside_daily = stdev(neg_returns) if len(neg_returns) > 1 else 0.0
    downside_risk = downside_daily * math.sqrt(252) * 100
    sortino = (annual_ret - RF_ANNUAL) / downside_risk if downside_risk > 0 else 0.0

    # 最大回撤
    peak = navs[0]
    max_dd = 0.0
    for nav in navs:
        if nav > peak:
            peak = nav
        dd = (peak - nav) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    max_drawdown = max_dd * 100
    calmar = annual_ret / max_drawdown if max_drawdown > 0 else 0.0

    # ── IR + Alpha (Step2 新增, 需基准回归) ─────────────────────────────────────
    # IR = (R_p - R_b) / TE, TE = stdev(R_fund_daily - R_bench_daily) × √252 × 100
    # Alpha: CAPM 回归 R_fund - R_f = α + β × (R_bench - R_f) + ε, α 年化 = α_daily × 252
    information_ratio = None
    alpha = None
    if bench_rows and len(bench_rows) >= 20:
        bench_map = {d: float(p) for d, p in bench_rows}
        # 对齐基金日收益 + 基准日涨跌 (基准 pct_change 是 %, 转小数)
        aligned = [(rd, fr, bench_map[rd] / 100.0)
                   for rd, fr in zip(ret_dates, returns) if rd in bench_map]
        if len(aligned) >= 20:
            fund_rets = [a[1] for a in aligned]
            bench_rets = [a[2] for a in aligned]
            excess_daily = [f - b for f, b in zip(fund_rets, bench_rets)]
            if len(excess_daily) > 1:
                te_daily = stdev(excess_daily)
                te_annual = te_daily * math.sqrt(252) * 100  # 跟踪误差年化%
                # 年化超额收益 = (mean(fund_daily) - mean(bench_daily)) × 252 × 100 (转%)
                excess_annual = (mean(fund_rets) - mean(bench_rets)) * 252 * 100
                if te_annual > 0:
                    information_ratio = excess_annual / te_annual
                # CAPM 回归: R_fund - R_f = α + β × (R_bench - R_f) + ε
                rf_daily = RF_ANNUAL / 100.0 / 252.0  # 日频无风险（小数）
                fund_excess = [f - rf_daily for f in fund_rets]
                bench_excess = [b - rf_daily for b in bench_rets]
                var_b = sum((b - mean(bench_excess)) ** 2 for b in bench_excess) / (len(bench_excess) - 1)
                if var_b > 0:
                    cov_fb = sum((f - mean(fund_excess)) * (b - mean(bench_excess))
                                 for f, b in zip(fund_excess, bench_excess)) / (len(bench_excess) - 1)
                    beta = cov_fb / var_b
                    alpha_daily = mean(fund_excess) - beta * mean(bench_excess)
                    alpha = alpha_daily * 252 * 100  # 年化转%

    return {
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "max_drawdown": max_drawdown,
        "annual_volatility": annual_vol,
        "downside_risk": downside_risk,
        "information_ratio": information_ratio,
        "alpha": alpha,
        "risk_return_rank": None,
        "anti_risk_rank": None,
        "data_source": "self_calc",
    }


def fetch_fund_risk_indicator(codes: list[str] | None = None) -> int:
    """fund_individual_analysis_xq 逐只, 失败降级净值自算 -> fund_risk_indicator。

    xq 返回 3 周期(近1年/3年/5年) x 5 指标(夏普/波动率/最大回撤/风险收益比/抗风险波动)。
    xq 失败(LOF/ETF 等)降级用 _compute_risk_from_nav 从 fund_daily_nav 自算。
    自算补: 索提诺/卡玛/下行风险(xq 不提供)。
    不算: 信息比率/alpha(需基准回归, 第一版留 None)。

    Args:
      codes: 基金代码列表, None=全市场(27409只~4.5h挂凌晨)
    Returns: 写入行数
    """
    print("[O] fetch_fund_risk_indicator() ...", flush=True)
    t0 = time.time()
    if codes is None:
        conn = get_conn()
        try:
            rows_q = conn.execute("SELECT fund_code FROM fund_basic ORDER BY fund_code").fetchall()
        finally:
            conn.close()
        codes = [r[0] for r in rows_q]
    total = len(codes)
    print(f"[O] 逐只 fund_individual_analysis_xq {total} 只 ...", flush=True)

    prog = _load_stage0_progress("fund_risk_indicator")
    if prog.get("total") != total:
        prog = _stage0_reset_prog(prog, codes, total)
    done_set = set(prog.get("done", []))
    attempts = prog.setdefault("attempt", {})
    ok = fail = xq_ok = self_calc_ok = 0
    total_rows = 0
    BATCH = 20
    pending: list[tuple] = []
    today = dt.date.today().strftime("%Y%m%d")

    for i, code in enumerate(codes, 1):
        if code in done_set:
            ok += 1
        else:
            rows_this = 0
            # codex004 P3: 本轮实际数据源分支(xq_ok 是跨 code 累计值, 不能用来判定
            # 当前 code 走的哪条路径)——self_calc=净值自算降级 / xq=纯雪球 /
            # xq_mixed=雪球+自算补指标混合
            branch = "self_calc"
            try:
                df = safe_call(ak.fund_individual_analysis_xq, retries=1, symbol=code)
                if isinstance(df, Exception) or df is None or len(df) == 0:
                    # 降级: 净值自算
                    for period in ("1y", "3y", "5y"):
                        result = _compute_risk_from_nav(code, period)
                        if result:
                            pending.append((
                                code, period, result["sharpe"], result["sortino"],
                                result["calmar"], result["max_drawdown"],
                                result["annual_volatility"], result["downside_risk"],
                                result["information_ratio"], result["alpha"],
                                result["risk_return_rank"], result["anti_risk_rank"],
                                result["data_source"], today,
                            ))
                            rows_this += 1
                    if rows_this:
                        self_calc_ok += 1
                else:
                    srcs: set[str] = set()
                    for _, r in df.iterrows():
                        period_cn = str(r.get("周期", "")).strip()
                        period = XQ_PERIOD_MAP.get(period_cn, "")
                        if not period:
                            continue
                        # xq 提供 5 指标, 补自算 sortino/calmar/downside_risk/IR/alpha(xq不提供)
                        # 有 fund_daily_nav 净值时补全, 无则留 None
                        calc = _compute_risk_from_nav(code, period)
                        sortino_v = calc["sortino"] if calc else None
                        calmar_v = calc["calmar"] if calc else None
                        downside_v = calc["downside_risk"] if calc else None
                        ir_v = calc["information_ratio"] if calc else None
                        alpha_v = calc["alpha"] if calc else None
                        src = "mixed" if calc else "xq"
                        srcs.add(src)
                        pending.append((
                            code, period,
                            _safe_float(r.get("年化夏普比率")),
                            sortino_v,   # sortino 自算补(xq不提供)
                            calmar_v,    # calmar 自算补
                            _safe_float(r.get("最大回撤")),
                            _safe_float(r.get("年化波动率")),
                            downside_v,  # downside_risk 自算补
                            ir_v,        # information_ratio 自算补(Step2 升级, 需基准回归)
                            alpha_v,     # alpha 自算补(Step2 升级, CAPM 回归)
                            _safe_float(r.get("较同类风险收益比")),
                            _safe_float(r.get("较同类抗风险波动")),
                            src, today,
                        ))
                        rows_this += 1
                    if rows_this:
                        xq_ok += 1
                        # codex004 P3: 按本 code 实际数据源标记(含自算补指标=xq_mixed)
                        branch = "xq_mixed" if "mixed" in srcs else "xq"
                if rows_this:
                    ok += 1
                    total_rows += rows_this
                    # codex-001 medium: attempt 成功摘要(自算降级也算成功——数据源
                    # 确实无该基金风险数据时, 自算路径已尽力, 不再反复重采)。
                    # codex004 P3: 摘要按本轮实际数据源分支(self_calc/xq/xq_mixed),
                    # 不再用跨 code 累计的 xq_ok 判定(首个 xq 成功后纯自算 code 被
                    # 误标 ok 的摘要失真已根除); 闸门只认 attempt key 存在性不受影响
                    attempts[code] = {"self_calc": "self_calc", "xq": "ok",
                                      "xq_mixed": "xq_mixed"}[branch]
                    done_set.add(code)
                else:
                    fail += 1
            except Exception as e:  # noqa: BLE001
                fail += 1
                if fail <= 3:
                    print(f"  [O] {code} 异常: {type(e).__name__} {e}", flush=True)
            time.sleep(PF_STAGE0_THROTTLE)

        if (len(pending) >= BATCH) or i == total:
            if pending:
                conn = get_conn()
                conn.executemany(
                    "INSERT OR REPLACE INTO fund_risk_indicator"
                    "(fund_code, period, sharpe, sortino, calmar, max_drawdown, "
                    "annual_volatility, downside_risk, information_ratio, alpha, "
                    "risk_return_rank, anti_risk_rank, data_source, update_date) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    pending,
                )
                conn.commit()
                conn.close()
                pending = []
            prog["done"] = sorted(done_set)
            prog["fail"] = []
            prog["total"] = total
            _save_stage0_progress("fund_risk_indicator", prog)
            elapsed = time.time() - t0
            eta = (elapsed / i) * (total - i) if i > 0 else 0
            print(f"  [O] {i}/{total} ({i*100/total:.1f}%) ok={ok} fail={fail} "
                  f"xq={xq_ok} self_calc={self_calc_ok} "
                  f"elapsed={elapsed:.0f}s eta={eta:.0f}s", flush=True)
    print(f"[O] 完成: ok={ok} fail={fail} total={total} xq={xq_ok} "
          f"self_calc={self_calc_ok} 耗时={time.time()-t0:.0f}s", flush=True)
    return total_rows


# ── 阶段1 评分引擎: 半凯利仓位 + 6维度 + 经理 + 综合分 ───────────────────────────
# 独立计算模式不走 export_data() 7元组 (遵循 commit 190c8f7e 教训, 仿 _compute_position_estimate)
# Step3-7 完整实现: _compute_kelly_inputs/_compute_dimension_scores/_compute_manager_score/
# _compute_composite_score/_compute_fund_score; Step8 批量 compute_all_scores

# 评分方法版本号 (用于 fund_score.score_method 字段, 升级公式时 bump)
SCORE_METHOD_VERSION = "v1.0_20260720"

# 6维度主观赋权 (方案 §2.3 推荐基线, 业绩+风险共50%, 回撤+稳定性30%, 规模+费率20%)
SCORE_WEIGHTS: dict[str, float] = {
    "score_return": 0.25,         # D1 历史业绩
    "score_risk_adjusted": 0.25,  # D2 风险调整后收益
    "score_drawdown": 0.15,       # D3 回撤控制
    "score_stability": 0.15,      # D4 业绩稳定性
    "score_scale": 0.10,          # D5 规模与流动性
    "score_fee": 0.10,            # D6 费率
}

# 基准映射: 解析 fund_basic.benchmark/tracking_target 字段选对应指数
# fund_index_daily 仅含 hs300/csi500/gem 3指数, 其他类型兜底 hs300
BENCHMARK_KEYWORD_MAP: list[tuple[str, str]] = [
    # (关键字, 指数id) — 按 fund_basic.benchmark 或 tracking_target 文本匹配
    ("沪深300", "hs300"), ("沪深 300", "hs300"), ("hs300", "hs300"), ("000300", "hs300"),
    ("中证500", "csi500"), ("中证 500", "csi500"), ("csi500", "csi500"), ("000905", "csi500"),
    ("创业板", "gem"), ("科创50", "gem"), ("科创 50", "gem"),
]


def _pick_benchmark(benchmark_text: str | None, tracking_target: str | None = None) -> str:
    """从 fund_basic.benchmark 或 tracking_target 文本识别对应指数 id。
    匹配不到返回 'hs300' (默认基准, 全市场统一兜底)。
    """
    for text in (benchmark_text or "", tracking_target or ""):
        for kw, idx_id in BENCHMARK_KEYWORD_MAP:
            if kw in text:
                return idx_id
    return "hs300"


def _compute_kelly_inputs(fund_code: str, period_months: int = 36) -> dict | None:
    """从 fund_daily_nav 月频算凯利胜率赔率 (方案 §5.2 推荐方案B 月频3年)。

    算法:
      1. fund_daily_nav 按月聚合(每月最后交易日 unit_nav), 算月收益率
      2. 取近 period_months 个月收益
      3. p = 胜率 = len(wins)/len(samples)
      4. b = 赔率 = mean(wins)/abs(mean(losses)) (无亏损=999)
      5. f* = (p*b - q)/b = p - q/b (q=1-p)
      6. half_kelly = f*/2 * 100 (转%), clamp 0-90% (绝不 All in)
      7. 分档: <30 保守, 30-60 均衡, >=60 激进

    Args:
      fund_code: 基金代码
      period_months: 月数(默认36=3年)
    Returns: dict {win_rate, win_loss_ratio, kelly_fraction, half_kelly_position, tier, sample_count}
             或 None(数据不足)
    """
    from statistics import mean
    # 取近 period_months+1 月末日净值(多1个用于算首个月收益)
    # 估算起始日期: period_months 月 ≈ period_months*30.5 天, 加 buffer 60 天
    start_date = (dt.date.today() - dt.timedelta(days=period_months * 31 + 60)).strftime("%Y%m%d")
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT date, unit_nav FROM fund_daily_nav "
            "WHERE fund_code=? AND date>=? AND unit_nav IS NOT NULL AND unit_nav > 0 "
            "ORDER BY date", (fund_code, start_date)
        ).fetchall()
    finally:
        conn.close()
    if len(rows) < 20:
        return None

    # 月频聚合: 按 YYYYMM 分组, 每月取最后交易日的 unit_nav
    monthly: dict[str, float] = {}  # YYYYMM -> 月末净值
    for d, nav in rows:
        ym = d[:6]  # YYYYMM
        monthly[ym] = float(nav)  # 后写覆盖 = 月末最后一天
    month_keys = sorted(monthly.keys())
    if len(month_keys) < 4:  # 至少4个月才能算3个月收益
        return None

    # 算月收益率
    monthly_returns = []
    for i in range(1, len(month_keys)):
        prev_nav = monthly[month_keys[i - 1]]
        curr_nav = monthly[month_keys[i]]
        if prev_nav > 0:
            monthly_returns.append((curr_nav - prev_nav) / prev_nav)

    # 取近 period_months 个月
    samples = monthly_returns[-period_months:] if len(monthly_returns) >= period_months else monthly_returns
    if len(samples) < 6:  # 至少6个月样本
        return None

    wins = [r for r in samples if r > 0]
    losses = [r for r in samples if r < 0]
    n = len(samples)
    p = len(wins) / n  # 胜率
    if losses:
        avg_win = mean(wins) if wins else 0.0
        avg_loss_abs = abs(mean(losses))
        b = avg_win / avg_loss_abs if avg_loss_abs > 0 else 999.0
    elif wins:
        # 全胜无亏损: 赔率设999 (凯利公式退化, f* 接近1)
        b = 999.0
    else:
        # 全部为0收益(货币基金可能): 胜率0.5, 赔率1
        p = 0.5
        b = 1.0
    q = 1 - p
    # 凯利比例 f* = p - q/b
    f_star = p - q / b if b > 0 else 0.0
    f_star = max(0.0, min(1.0, f_star))  # clamp 0-1 (负凯利=不参与, 超1=理论全仓)
    half_kelly = f_star / 2 * 100  # 半凯利转%
    half_kelly = max(0.0, min(90.0, half_kelly))  # 0-90% clamp, 绝不 All in

    # 分档
    if half_kelly < 30:
        tier = "保守"
    elif half_kelly < 60:
        tier = "均衡"
    else:
        tier = "激进"

    return {
        "win_rate": round(p, 4),
        "win_loss_ratio": round(b, 4),
        "kelly_fraction": round(f_star, 4),
        "half_kelly_position": round(half_kelly, 2),
        "tier": tier,
        "sample_count": n,
    }


# ── 百分位工具 (横截面归一化, 抗极端值, 无正态假设) ─────────────────────────────
def _percentile(value: float, all_values: list[float], reverse: bool = False) -> float:
    """算 value 在 all_values 中的百分位 (0-100)。
    reverse=False 越大越好(收益/夏普/胜率), reverse=True 越小越好(回撤/std/费率)。
    缺失数据返回 50 (中性分, 不偏不倚)。
    """
    if value is None or not all_values:
        return 50.0
    valid = [v for v in all_values if v is not None]
    if not valid:
        return 50.0
    n = len(valid)
    # 排序后找 value 的位置
    sorted_v = sorted(valid)
    # 二分查找位置
    import bisect
    pos = bisect.bisect_left(sorted_v, value)
    pct = pos / n * 100 if n > 0 else 50.0
    if reverse:
        pct = 100 - pct
    return round(pct, 2)


def _compute_dimension_scores(conn: sqlite3.Connection, fund_code: str,
                              benchmark: str = "hs300",
                              bench_returns_3y: float | None = None) -> tuple[dict, float]:
    """算 6 维度子分 (0-100) + data_completeness (方案 §2)。

    D1 历史业绩(0.25): fund_performance return_3y/ytd/since_inception + hs300 超额
    D2 风险调整(0.25): fund_risk_indicator 3y sharpe/sortino/calmar (缺用 _compute_risk_from_nav 现算)
    D3 回撤控制(0.15): max_drawdown(3y) 反向 + 修复时长(fund_daily_nav 现算)
    D4 业绩稳定性(0.15): 月胜率 + 跑赢基准月率 + 月收益std
    D5 规模流动性(0.10): scale 钟形 + purchase_status
    D6 费率(0.10): management+custody+service+purchase 总持有成本反向

    Args:
      conn: DB 连接
      fund_code: 基金代码
      benchmark: 基准指数 id
      bench_returns_3y: 基准3年累计收益率% (外部预算好避免重复查)
    Returns: (dimension_scores dict, data_completeness 0-1)
    """
    import math
    from statistics import mean, stdev
    today = dt.date.today().strftime("%Y%m%d")
    dims = {
        "score_return": None, "score_risk_adjusted": None,
        "score_drawdown": None, "score_stability": None,
        "score_scale": None, "score_fee": None,
    }
    ready_count = 0

    # ── D1 历史业绩 ──────────────────────────────────────────────────────────
    perf = conn.execute(
        "SELECT return_3y, return_ytd, return_since_inception, return_1y, return_2y "
        "FROM fund_performance WHERE fund_code=? ORDER BY update_date DESC LIMIT 1",
        (fund_code,)
    ).fetchone()
    if perf:
        r3y = _safe_float(perf["return_3y"])
        rytd = _safe_float(perf["return_ytd"])
        rsince = _safe_float(perf["return_since_inception"])
        r1y = _safe_float(perf["return_1y"])
        # 缺3年用1年×1.5替代(降权通过 data_completeness)
        r3y_eff = r3y if r3y is not None else (r1y * 1.5 if r1y is not None else None)
        # 子分: 绝对收益(0.4*3y + 0.2*ytd + 0.4*since) 简化用绝对值映射 (收益好分数高)
        # 横截面百分位需全市场样本, 第一版用绝对阈值映射 (避免每只都查全市场)
        def _ret_to_score(r):
            if r is None:
                return None
            # 收益率->分数映射: 50%收益=100分, 0%=50分, -30%=0分 (线性插值)
            if r >= 50:
                return 100.0
            if r >= 0:
                return 50.0 + r  # 0->50, 50->100
            if r >= -50:
                return 50.0 + r  # -50->0
            return 0.0
        abs_score = None
        if r3y_eff is not None or rytd is not None or rsince is not None:
            parts = []
            if r3y_eff is not None:
                parts.append((_ret_to_score(r3y_eff), 0.4))
            if rytd is not None:
                parts.append((_ret_to_score(rytd), 0.2))
            if rsince is not None:
                parts.append((_ret_to_score(rsince), 0.4))
            total_w = sum(w for _, w in parts)
            if total_w > 0:
                abs_score = sum(s * w for s, w in parts) / total_w
        # 超额收益子分 (vs hs300 3年累计)
        excess_score = None
        if r3y_eff is not None and bench_returns_3y is not None:
            excess = r3y_eff - bench_returns_3y
            excess_score = _ret_to_score(excess)
        if abs_score is not None and excess_score is not None:
            dims["score_return"] = round(abs_score * 0.5 + excess_score * 0.5, 2)
        elif abs_score is not None:
            dims["score_return"] = round(abs_score, 2)
        if dims["score_return"] is not None:
            ready_count += 1

    # ── D2 风险调整 ──────────────────────────────────────────────────────────
    risk = conn.execute(
        "SELECT sharpe, sortino, calmar, information_ratio, alpha, max_drawdown "
        "FROM fund_risk_indicator WHERE fund_code=? AND period='3y' LIMIT 1",
        (fund_code,)
    ).fetchone()
    risk_data = dict(risk) if risk else {}
    # 缺3y风险用 _compute_risk_from_nav 现算 (stage0 未就绪过渡)
    if not risk or risk_data.get("sharpe") is None:
        calc = _compute_risk_from_nav(fund_code, "3y", benchmark=benchmark)
        if calc:
            for k in ("sharpe", "sortino", "calmar", "information_ratio", "alpha", "max_drawdown"):
                if risk_data.get(k) is None:
                    risk_data[k] = calc[k]
    sharpe = _safe_float(risk_data.get("sharpe"))
    sortino = _safe_float(risk_data.get("sortino"))
    calmar = _safe_float(risk_data.get("calmar"))
    if sharpe is not None or sortino is not None or calmar is not None:
        # 夏普->分数映射: 2.0=100分, 0=50分, -1=0分 (夏普负=不及格)
        def _sharpe_to_score(s):
            if s is None:
                return None
            if s >= 2.0:
                return 100.0
            if s >= 0:
                return 50.0 + s * 25  # 0->50, 2->100
            if s >= -2.0:
                return 50.0 + s * 25  # -2->0
            return 0.0
        parts = []
        if sharpe is not None:
            parts.append((_sharpe_to_score(sharpe), 0.4))
        if sortino is not None:
            parts.append((_sharpe_to_score(sortino), 0.3))
        if calmar is not None:
            parts.append((_sharpe_to_score(calmar), 0.3))
        total_w = sum(w for _, w in parts)
        if total_w > 0:
            dims["score_risk_adjusted"] = round(sum(s * w for s, w in parts) / total_w, 2)
            ready_count += 1

    # ── D3 回撤控制 ──────────────────────────────────────────────────────────
    max_dd = _safe_float(risk_data.get("max_drawdown"))
    if max_dd is None:
        # 再试1y
        risk1y = conn.execute(
            "SELECT max_drawdown FROM fund_risk_indicator WHERE fund_code=? AND period='1y' LIMIT 1",
            (fund_code,)
        ).fetchone()
        max_dd = _safe_float(risk1y["max_drawdown"]) if risk1y else None
    if max_dd is not None:
        # max_dd 反向: 0%=100分, 30%=50分, 60%=0分
        def _dd_to_score(dd):
            if dd is None:
                return None
            if dd <= 0:
                return 100.0
            if dd >= 60:
                return 0.0
            return 100.0 - dd * (100.0 / 60.0)
        max_dd_score = _dd_to_score(max_dd)
        # 修复时长子分 (fund_daily_nav 自算)
        recovery_score = None
        try:
            nav_rows = conn.execute(
                "SELECT date, unit_nav FROM fund_daily_nav "
                "WHERE fund_code=? AND unit_nav IS NOT NULL AND unit_nav > 0 "
                "ORDER BY date DESC LIMIT 800",
                (fund_code,)
            ).fetchall()
            if len(nav_rows) >= 60:
                # 倒序变正序
                navs = [r[1] for r in reversed(nav_rows)]
                # 找最大回撤区间 + 修复时长
                peak = navs[0]
                max_dd_idx = 0
                cur_dd = 0.0
                cur_max_dd = 0.0
                cur_peak = navs[0]
                for i, nav in enumerate(navs):
                    if nav > cur_peak:
                        cur_peak = nav
                    dd = (cur_peak - nav) / cur_peak if cur_peak > 0 else 0
                    if dd > cur_max_dd:
                        cur_max_dd = dd
                        max_dd_idx = i
                # 从 max_dd_idx 往后找首次 >= cur_peak(回撤前高)
                trough_nav = navs[max_dd_idx]
                pre_peak = max(navs[:max_dd_idx + 1]) if max_dd_idx > 0 else navs[0]
                recovery_days = None
                for j in range(max_dd_idx + 1, len(navs)):
                    if navs[j] >= pre_peak:
                        recovery_days = j - max_dd_idx
                        break
                if recovery_days is not None:
                    # 修复时长->分数: 0天=100, 250天(1年)=50, 500天=0
                    if recovery_days >= 500:
                        recovery_score = 0.0
                    else:
                        recovery_score = 100.0 - recovery_days * (100.0 / 500.0)
                else:
                    # 未修复 = 0分
                    recovery_score = 0.0
        except Exception:  # noqa: BLE001
            pass
        if max_dd_score is not None and recovery_score is not None:
            dims["score_drawdown"] = round(max_dd_score * 0.7 + recovery_score * 0.3, 2)
        elif max_dd_score is not None:
            dims["score_drawdown"] = round(max_dd_score, 2)
        if dims["score_drawdown"] is not None:
            ready_count += 1

    # ── D4 业绩稳定性 ────────────────────────────────────────────────────────
    try:
        # fund_daily_nav 月频 + 基准月频
        start_d = (dt.date.today() - dt.timedelta(days=36 * 31 + 60)).strftime("%Y%m%d")
        nav_rows = conn.execute(
            "SELECT date, unit_nav FROM fund_daily_nav "
            "WHERE fund_code=? AND date>=? AND unit_nav IS NOT NULL AND unit_nav > 0 "
            "ORDER BY date", (fund_code, start_d)
        ).fetchall()
        bench_rows = conn.execute(
            "SELECT date, pct_change FROM fund_index_daily "
            "WHERE index_id=? AND date>=? AND pct_change IS NOT NULL "
            "ORDER BY date", (benchmark, start_d)
        ).fetchall() if benchmark else []
        if len(nav_rows) >= 60:
            # 月频聚合
            monthly_nav: dict[str, float] = {}
            for d, nav in nav_rows:
                monthly_nav[d[:6]] = float(nav)
            m_keys = sorted(monthly_nav.keys())
            m_returns = []
            for i in range(1, len(m_keys)):
                prev = monthly_nav[m_keys[i - 1]]
                curr = monthly_nav[m_keys[i]]
                if prev > 0:
                    m_returns.append((m_keys[i], (curr - prev) / prev))
            # 基准月频
            bench_monthly: dict[str, float] = {}
            for d, pct in bench_rows:
                ym = d[:6]
                bench_monthly.setdefault(ym, 0.0)
                # 月收益 = 累乘 (1+r1)(1+r2)...(1+rn)-1, 简化为日涨跌累加(误差小)
                bench_monthly[ym] = (1 + bench_monthly[ym] / 100) * (1 + float(pct) / 100) - 1
            # 月胜率
            wins = sum(1 for _, r in m_returns if r > 0)
            win_rate = wins / len(m_returns) if m_returns else 0.5
            # 跑赢基准月率
            beat_count = 0
            beat_total = 0
            for ym, r in m_returns:
                if ym in bench_monthly:
                    beat_total += 1
                    if r > bench_monthly[ym]:
                        beat_count += 1
            beat_rate = beat_count / beat_total if beat_total > 0 else 0.5
            # 月收益 std
            rets = [r for _, r in m_returns]
            std_monthly = stdev(rets) if len(rets) > 1 else 0.0
            # 子分: 胜率*0.4 + 跑赢率*0.4 + (100-std百分位)*0.2
            # std 映射: 0%=100分, 10%=50分, 20%=0分
            std_score = 100.0 - min(std_monthly * 1000, 100.0) if std_monthly else 50.0
            dims["score_stability"] = round(
                win_rate * 100 * 0.4 + beat_rate * 100 * 0.4 + std_score * 0.2, 2)
            ready_count += 1
    except Exception:  # noqa: BLE001
        pass

    # ── D5 规模与流动性 ─────────────────────────────────────────────────────
    basic = conn.execute(
        "SELECT scale FROM fund_basic WHERE fund_code=?", (fund_code,)
    ).fetchone()
    scale = _safe_float(basic["scale"]) if basic else None
    # 规模钟形: <2亿=0, 2-10亿=50, 10-100亿=100, 100-500亿=70, >500亿=40
    if scale is not None:
        if scale < 2:
            scale_score = 0.0
        elif scale < 10:
            scale_score = 50.0
        elif scale < 100:
            scale_score = 100.0
        elif scale < 500:
            scale_score = 70.0
        else:
            scale_score = 40.0
    else:
        scale_score = 50.0
    # 流动性: 申购状态
    ps = conn.execute(
        "SELECT purchase_status FROM fund_purchase_status WHERE fund_code=? "
        "ORDER BY update_date DESC LIMIT 1", (fund_code,)
    ).fetchone()
    ps_str = ps["purchase_status"] if ps else ""
    if "开放申购" in (ps_str or ""):
        liquid_score = 100.0
    elif "限制大额" in (ps_str or "") or "限大额" in (ps_str or ""):
        liquid_score = 50.0
    elif "暂停" in (ps_str or ""):
        liquid_score = 0.0
    else:
        liquid_score = 50.0  # 未知
    dims["score_scale"] = round(scale_score * 0.6 + liquid_score * 0.4, 2)
    ready_count += 1

    # ── D6 费率 ─────────────────────────────────────────────────────────────
    basic_full = conn.execute(
        "SELECT management_fee, custody_fee, service_fee, purchase_fee "
        "FROM fund_basic WHERE fund_code=?", (fund_code,)
    ).fetchone()
    if basic_full:
        mgmt = _safe_float(basic_full["management_fee"]) or 0.0
        cust = _safe_float(basic_full["custody_fee"]) or 0.0
        svc = _safe_float(basic_full["service_fee"]) or 0.0
        purch = _safe_float(basic_full["purchase_fee"]) or 0.0
        # 总成本 = (年费率*3) + 申购费*0.5 (3年摊薄)
        total_cost = (mgmt + cust + svc) * 3 + purch * 0.5
        # 反向映射: 0%=100分, 5%=50分, 10%=0分
        if total_cost >= 10:
            dims["score_fee"] = 0.0
        else:
            dims["score_fee"] = round(100.0 - total_cost * 10, 2)
        ready_count += 1

    data_completeness = ready_count / 6.0
    return dims, data_completeness


def _compute_manager_score(conn: sqlite3.Connection, fund_code: str) -> dict:
    """算经理稳健度 6 维 (0-100) + 综合分 (方案 §4)。

    M1 任职年限: fund_manager.tenure_days (缺用 work_days proxy)
    M2 管理规模: managed_scale 钟形分箱
    M3 历史业绩稳定性: best_return (缺 managed_history std 时单维)
    M4 回撤控制: managed_history 缺时用 best_return 反向 proxy
    M5 任职连贯性: managed_history 缺时跳过, 重分配权重
    M6 精力分散: managed_count 反向

    Returns: {manager_score, m1_tenure, m2_scale, m3_perf_stability, m4_drawdown,
              m5_coherence, m6_focus, data_completeness}
    """
    # 取该基金所有经理 (多经理取均值或最资深)
    mgr_rows = conn.execute(
        "SELECT manager_name, appoint_date, managed_count, managed_scale, "
        "best_return, managed_history, tenure_days, work_days "
        "FROM fund_manager WHERE fund_code=?",
        (fund_code,)
    ).fetchall()
    if not mgr_rows:
        return {
            "manager_score": None, "m1_tenure": None, "m2_scale": None,
            "m3_perf_stability": None, "m4_drawdown": None,
            "m5_coherence": None, "m6_focus": None,
            "data_completeness": 0.0,
        }

    # 多经理取均值(各维分别取均值)
    import json as _json
    from statistics import mean as _mean, stdev as _stdev

    # M1 任职年限 (tenure_days 缺用 work_days/365 proxy)
    m1_vals = []
    has_real_tenure = False
    for r in mgr_rows:
        td = r["tenure_days"]
        if td is not None and td > 0:
            m1_vals.append(float(td) / 365.0)  # 年
            has_real_tenure = True
        elif r["work_days"]:
            m1_vals.append(float(r["work_days"]) / 365.0)  # 从业年限 proxy
    m1 = None
    if m1_vals:
        m1_years = _mean(m1_vals)
        # 阈值: >5年=90+, 3-5年=70-90, 1-3年=50-70, <1年=<50
        if m1_years >= 5:
            m1 = 90.0 + min(10, (m1_years - 5) * 2)
        elif m1_years >= 3:
            m1 = 70.0 + (m1_years - 3) * 10
        elif m1_years >= 1:
            m1 = 50.0 + (m1_years - 1) * 10
        else:
            m1 = max(0, 50.0 - (1 - m1_years) * 50)

    # M2 管理规模 (钟形: <10亿=40, 10-50=70, 50-300=100, 300-800=80, >800=60)
    m2_vals = [_safe_float(r["managed_scale"]) for r in mgr_rows if r["managed_scale"]]
    m2 = None
    if m2_vals:
        avg_scale = _mean(m2_vals)
        if avg_scale < 10:
            m2 = 40.0
        elif avg_scale < 50:
            m2 = 70.0
        elif avg_scale < 300:
            m2 = 100.0
        elif avg_scale < 800:
            m2 = 80.0
        else:
            m2 = 60.0

    # M3 历史业绩稳定性 (best_return + managed_history std)
    m3_vals = []
    has_history = False
    for r in mgr_rows:
        br = _safe_float(r["best_return"])
        mh_str = r["managed_history"]
        history_returns = []
        if mh_str:
            try:
                mh = _json.loads(mh_str)
                if isinstance(mh, list):
                    for h in mh:
                        ret = h.get("return") if isinstance(h, dict) else None
                        if ret is not None:
                            history_returns.append(float(ret))
                    if history_returns:
                        has_history = True
            except (ValueError, TypeError):
                pass
        if br is not None:
            # best_return -> 分数: >100%=100, 50%=80, 0%=50, -30%=0
            if br >= 100:
                br_score = 100.0
            elif br >= 0:
                br_score = 50.0 + br * 0.5
            else:
                br_score = max(0, 50.0 + br)
            if history_returns:
                # 稳定性 = 100 - std百分位 (std大扣分)
                std_h = _stdev(history_returns) if len(history_returns) > 1 else 0.0
                # std映射: 0=100, 50=50, 100=0
                std_score = max(0, 100.0 - std_h)
                m3_vals.append(br_score * 0.5 + std_score * 0.5)
            else:
                m3_vals.append(br_score)  # 单维 proxy
    m3 = _mean(m3_vals) if m3_vals else None

    # M4 回撤控制 (managed_history 各基金回撤均值缺, 用 best_return 反向 proxy)
    # best_return 高者通常回撤控制好 (过渡方案, 方案 §4.4)
    m4_vals = []
    for r in mgr_rows:
        br = _safe_float(r["best_return"])
        if br is not None:
            # best_return 高->回撤控制好 (proxy): >100=100, 50=80, 0=50, -30=0
            if br >= 100:
                m4_vals.append(100.0)
            elif br >= 0:
                m4_vals.append(50.0 + br * 0.5)
            else:
                m4_vals.append(max(0, 50.0 + br))
    m4 = _mean(m4_vals) if m4_vals else None

    # M5 任职连贯性 (managed_history 缺跳过)
    m5_vals = []
    for r in mgr_rows:
        mh_str = r["managed_history"]
        if not mh_str:
            continue
        try:
            mh = _json.loads(mh_str)
            if isinstance(mh, list) and len(mh) > 0:
                # 平均任职天数 + 换基频率
                tenures = []
                for h in mh:
                    td = h.get("tenure_days") if isinstance(h, dict) else None
                    if td:
                        tenures.append(float(td))
                if tenures:
                    avg_tenure_years = _mean(tenures) / 365.0
                    work_years = (r["work_days"] or 0) / 365.0
                    switch_freq = len(mh) / work_years if work_years > 0 else 0
                    # 子分: 平均任职长*0.6 + (100-换基频率百分位)*0.4
                    tenure_score = min(100, avg_tenure_years * 20)  # 5年=100
                    # 换基频率: 0次/年=100, 2次/年=50, 4次/年=0
                    freq_score = max(0, 100.0 - switch_freq * 25)
                    m5_vals.append(tenure_score * 0.6 + freq_score * 0.4)
        except (ValueError, TypeError):
            pass
    m5 = _mean(m5_vals) if m5_vals else None

    # M6 精力分散 (managed_count 反向)
    m6_vals = []
    for r in mgr_rows:
        mc = r["managed_count"]
        if mc is not None:
            mc = int(mc)
            # 1-3只=90+, 4-6只=70-90, 7-10只=50-70, >10只=<50
            if mc <= 3:
                m6_vals.append(90.0 + (3 - mc) * 3.33)
            elif mc <= 6:
                m6_vals.append(70.0 + (6 - mc) * 6.67)
            elif mc <= 10:
                m6_vals.append(50.0 + (10 - mc) * 5)
            else:
                m6_vals.append(max(0, 50.0 - (mc - 10) * 5))
    m6 = _mean(m6_vals) if m6_vals else None

    # 加权汇总 (方案 §4.3): M1*0.2 + M2*0.15 + M3*0.2 + M4*0.2 + M5*0.15 + M6*0.1
    # 缺数据时: 重分配权重到就绪维度 (M5 普遍缺, 重分配到 M1/M2/M6)
    weights = {"m1": 0.2, "m2": 0.15, "m3": 0.2, "m4": 0.2, "m5": 0.15, "m6": 0.1}
    values = {"m1": m1, "m2": m2, "m3": m3, "m4": m4, "m5": m5, "m6": m6}
    ready = {k: v for k, v in values.items() if v is not None}
    if not ready:
        manager_score = None
        completeness = 0.0
    else:
        total_w = sum(weights[k] for k in ready)
        manager_score = round(sum(ready[k] * weights[k] for k in ready) / total_w, 2)
        completeness = len(ready) / 6.0
    return {
        "manager_score": manager_score,
        "m1_tenure": round(m1, 2) if m1 is not None else None,
        "m2_scale": round(m2, 2) if m2 is not None else None,
        "m3_perf_stability": round(m3, 2) if m3 is not None else None,
        "m4_drawdown": round(m4, 2) if m4 is not None else None,
        "m5_coherence": round(m5, 2) if m5 is not None else None,
        "m6_focus": round(m6, 2) if m6 is not None else None,
        "data_completeness": round(completeness, 4),
    }


def _compute_composite_score(dims: dict, data_completeness: float,
                              weights: dict | None = None) -> tuple[float | None, int | None]:
    """6 维度加权汇总 + data_completeness 降权 + 星级映射 (方案 §2.5)。

    composite_score = Σ(D_i × w_i) × data_completeness
    星级: >=85五星 / 70-85四星 / 50-70三星 / 30-50二星 / <30一星
    """
    w = weights or SCORE_WEIGHTS
    ready = {k: v for k, v in dims.items() if v is not None and k in w}
    if not ready:
        return None, None
    total_w = sum(w[k] for k in ready)
    raw = sum(ready[k] * w[k] for k in ready) / total_w if total_w > 0 else 0
    composite = raw * data_completeness
    composite = round(composite, 2)
    # 星级映射
    if composite >= 85:
        star = 5
    elif composite >= 70:
        star = 4
    elif composite >= 50:
        star = 3
    elif composite >= 30:
        star = 2
    else:
        star = 1
    return composite, star


def _get_market_adjustment() -> float:
    """从 public_fund_position_estimate.json 读预估仓位, 算市场乘数 (方案 §5.4)。
    预估仓位 >88% 高位减仓 ×0.7, 80-88% 中性 ×1.0, <80% 低位加仓 ×1.2。
    JSON 不存在或读取失败默认 1.0 (中性)。
    """
    try:
        p = STATIC_DATA_DIR / "public_fund_position_estimate.json"
        if not p.exists():
            return 1.0
        data = json.loads(p.read_text(encoding="utf-8"))
        pos = data.get("current", {}).get("position_estimate")
        if pos is None:
            return 1.0
        if pos > 88:
            return 0.7
        if pos >= 80:
            return 1.0
        return 1.2
    except Exception:  # noqa: BLE001
        return 1.0


def _compute_fund_score(conn: sqlite3.Connection, fund_code: str,
                        benchmark: str | None = None) -> dict | None:
    """单只基金完整评分 (Step7, 方案 §7.3)。
    整合 dims + mgr + kelly + market_adjustment + final_suggestion。

    Args:
      conn: DB 连接
      fund_code: 基金代码
      benchmark: 基准指数 id (None 自动从 fund_basic.benchmark/tracking_target 解析)
    Returns: dict 对应 fund_score 表一行字段, 或 None(数据严重不足无法评)
    """
    # 取 fund_basic
    basic = conn.execute(
        "SELECT fund_name, fund_type, benchmark as bench_text, tracking_target, scale "
        "FROM fund_basic WHERE fund_code=?", (fund_code,)
    ).fetchone()
    if not basic:
        return None
    # 基准解析
    if benchmark is None:
        benchmark = _pick_benchmark(basic["bench_text"], basic["tracking_target"])

    # 算基准3年累计收益率 (D1 超额用)
    bench_returns_3y = None
    try:
        start_d = (dt.date.today() - dt.timedelta(days=365 * 3 + 30)).strftime("%Y%m%d")
        bench_rows = conn.execute(
            "SELECT date, close, pct_change FROM fund_index_daily "
            "WHERE index_id=? AND date>=? AND close IS NOT NULL ORDER BY date",
            (benchmark, start_d)
        ).fetchall()
        if len(bench_rows) >= 100:
            first_close = float(bench_rows[0]["close"])
            last_close = float(bench_rows[-1]["close"])
            if first_close > 0:
                bench_returns_3y = (last_close / first_close - 1) * 100
    except Exception:  # noqa: BLE001
        pass

    # 6维度 + data_completeness
    dims, completeness = _compute_dimension_scores(
        conn, fund_code, benchmark=benchmark, bench_returns_3y=bench_returns_3y)
    # 经理6维
    mgr = _compute_manager_score(conn, fund_code)
    # 半凯利
    kelly = _compute_kelly_inputs(fund_code)
    # 综合分 + 星级
    composite, star = _compute_composite_score(dims, completeness)
    if composite is None:
        return None  # 6维全缺无法评分

    # 市场乘数 + 最终建议
    market_adj = _get_market_adjustment()
    half_kelly = kelly["half_kelly_position"] if kelly else 0.0
    final_suggestion = round(half_kelly * market_adj, 2)
    final_suggestion = max(0.0, min(90.0, final_suggestion))

    # 风险指标原始值 (3y)
    risk_row = conn.execute(
        "SELECT sharpe, sortino, calmar, information_ratio, alpha "
        "FROM fund_risk_indicator WHERE fund_code=? AND period='3y' LIMIT 1",
        (fund_code,)
    ).fetchone()
    if risk_row is None or risk_row["sharpe"] is None:
        # 用 _compute_risk_from_nav 现算补
        calc = _compute_risk_from_nav(fund_code, "3y", benchmark=benchmark)
        if calc:
            sharpe_v = calc["sharpe"]
            sortino_v = calc["sortino"]
            calmar_v = calc["calmar"]
            ir_v = calc["information_ratio"]
            alpha_v = calc["alpha"]
        else:
            sharpe_v = sortino_v = calmar_v = ir_v = alpha_v = None
    else:
        sharpe_v = _safe_float(risk_row["sharpe"])
        sortino_v = _safe_float(risk_row["sortino"])
        calmar_v = _safe_float(risk_row["calmar"])
        ir_v = _safe_float(risk_row["information_ratio"])
        alpha_v = _safe_float(risk_row["alpha"])
        # 表里缺 IR/alpha 时也用现算补
        if ir_v is None or alpha_v is None:
            calc = _compute_risk_from_nav(fund_code, "3y", benchmark=benchmark)
            if calc:
                ir_v = ir_v if ir_v is not None else calc["information_ratio"]
                alpha_v = alpha_v if alpha_v is not None else calc["alpha"]

    today = dt.date.today().strftime("%Y%m%d")
    return {
        "fund_code": fund_code,
        "score_date": today,
        "composite_score": composite,
        "star_rating": star,
        "score_return": dims["score_return"],
        "score_risk_adjusted": dims["score_risk_adjusted"],
        "score_drawdown": dims["score_drawdown"],
        "score_stability": dims["score_stability"],
        "score_scale": dims["score_scale"],
        "score_fee": dims["score_fee"],
        "sharpe": sharpe_v, "sortino": sortino_v, "calmar": calmar_v,
        "information_ratio": ir_v, "alpha": alpha_v,
        "manager_score": mgr["manager_score"],
        "m1_tenure": mgr["m1_tenure"], "m2_scale": mgr["m2_scale"],
        "m3_perf_stability": mgr["m3_perf_stability"], "m4_drawdown": mgr["m4_drawdown"],
        "m5_coherence": mgr["m5_coherence"], "m6_focus": mgr["m6_focus"],
        "kelly_fraction": kelly["kelly_fraction"] if kelly else None,
        "half_kelly_position": half_kelly,
        "kelly_win_rate": kelly["win_rate"] if kelly else None,
        "kelly_win_loss_ratio": kelly["win_loss_ratio"] if kelly else None,
        "kelly_tier": kelly["tier"] if kelly else None,
        "market_adjustment": market_adj,
        "final_suggestion": final_suggestion,
        "benchmark": benchmark,
        "score_method": SCORE_METHOD_VERSION,
        "data_completeness": round(completeness, 4),
        "update_date": today,
    }


# ── Step8: 批量评分 + 断点续采 ────────────────────────────────────────────────
SCORE_PROGRESS_PATH = Path("/tmp/pf-score-progress.json")


def _load_score_progress() -> dict:
    if not SCORE_PROGRESS_PATH.exists():
        return {"done": [], "fail": [], "total": 0, "score_date": ""}
    try:
        return json.loads(SCORE_PROGRESS_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"done": [], "fail": [], "total": 0, "score_date": ""}


def _save_score_progress(prog: dict) -> None:
    try:
        SCORE_PROGRESS_PATH.write_text(
            json.dumps(prog, ensure_ascii=False), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"  [score-progress] WARN 写入失败: {e}", flush=True)


def compute_all_scores(top_n: int | None = 2000, benchmark: str | None = None,
                       resume: bool = True) -> int:
    """全市场批量评分写入 fund_score 表 (Step8, 方案 §7.3)。

    评分宇宙: 全市场所有基金 (用户决策1, 不排除债基/货基/QDII/指数, 按基金类型分基准)
    benchmark=None 时逐只从 fund_basic.benchmark/tracking_target 解析

    Args:
      top_n: 头部N只(按 scale 降序), None=全量27409只
      benchmark: 统一基准(默认None逐只解析)
      resume: True 断点续采(从 /tmp/pf-score-progress.json 接着跑)
    Returns: 写入行数
    """
    print(f"[score] compute_all_scores(top_n={top_n}, benchmark={benchmark}, resume={resume})", flush=True)
    t0 = time.time()
    conn = get_conn()
    try:
        # 选评分宇宙: 全市场所有基金, 按 scale 降序取头部N只 (规模大优先, 用户决策全市场)
        if top_n:
            rows = conn.execute(
                "SELECT fund_code FROM fund_basic "
                "WHERE fund_code IS NOT NULL "
                "ORDER BY COALESCE(scale, 0) DESC, fund_code ASC LIMIT ?",
                (top_n,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT fund_code FROM fund_basic ORDER BY fund_code").fetchall()
        all_codes = [r[0] for r in rows]
    finally:
        conn.close()
    total = len(all_codes)
    today = dt.date.today().strftime("%Y%m%d")
    print(f"[score] 评分宇宙: {total} 只 (top_n={top_n})", flush=True)

    # 断点续采: 同一 score_date 且 resume=True 时跳过已完成的
    prog = _load_score_progress() if resume else {"done": [], "fail": [], "total": 0, "score_date": ""}
    if resume and prog.get("score_date") == today and prog.get("total") == total:
        done_set = set(prog.get("done", []))
        pending = [c for c in all_codes if c not in done_set]
        print(f"[score] 断点续采: 已完成 {len(done_set)}/{total}, 待评 {len(pending)}", flush=True)
    else:
        done_set = set()
        pending = list(all_codes)
        prog = {"done": [], "fail": [], "total": total, "score_date": today}

    BATCH = 50  # 每50只批量 INSERT + 回写进度
    pending_rows: list[tuple] = []
    ok = fail = 0
    conn = get_conn()
    try:
        for i, code in enumerate(pending, 1):
            try:
                score = _compute_fund_score(conn, code, benchmark=benchmark)
                if score is None:
                    fail += 1
                else:
                    # 转 INSERT tuple (字段顺序对应 fund_score 表)
                    pending_rows.append((
                        score["fund_code"], score["score_date"],
                        score["composite_score"], score["star_rating"],
                        score["score_return"], score["score_risk_adjusted"],
                        score["score_drawdown"], score["score_stability"],
                        score["score_scale"], score["score_fee"],
                        score["sharpe"], score["sortino"], score["calmar"],
                        score["information_ratio"], score["alpha"],
                        score["manager_score"],
                        score["m1_tenure"], score["m2_scale"], score["m3_perf_stability"],
                        score["m4_drawdown"], score["m5_coherence"], score["m6_focus"],
                        score["kelly_fraction"], score["half_kelly_position"],
                        score["kelly_win_rate"], score["kelly_win_loss_ratio"],
                        score["kelly_tier"], score["market_adjustment"],
                        score["final_suggestion"], score["benchmark"],
                        score["score_method"], score["data_completeness"],
                        score["update_date"],
                    ))
                    ok += 1
                    done_set.add(code)
            except Exception as e:  # noqa: BLE001
                fail += 1
                if fail <= 5:
                    print(f"  [score] {code} 异常: {type(e).__name__} {e}", flush=True)

            # 批量 INSERT + 回写进度
            if len(pending_rows) >= BATCH or i == len(pending):
                if pending_rows:
                    conn.executemany(
                        "INSERT OR REPLACE INTO fund_score"
                        "(fund_code, score_date, composite_score, star_rating, "
                        "score_return, score_risk_adjusted, score_drawdown, score_stability, "
                        "score_scale, score_fee, sharpe, sortino, calmar, "
                        "information_ratio, alpha, manager_score, "
                        "m1_tenure, m2_scale, m3_perf_stability, m4_drawdown, "
                        "m5_coherence, m6_focus, kelly_fraction, half_kelly_position, "
                        "kelly_win_rate, kelly_win_loss_ratio, kelly_tier, "
                        "market_adjustment, final_suggestion, benchmark, "
                        "score_method, data_completeness, update_date) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        pending_rows,
                    )
                    conn.commit()
                    pending_rows = []
                prog["done"] = sorted(done_set)
                prog["fail"] = []
                prog["total"] = total
                prog["score_date"] = today
                _save_score_progress(prog)
                elapsed = time.time() - t0
                done_count = len(done_set)
                eta = (elapsed / max(done_count, 1)) * (total - done_count) if done_count > 0 else 0
                print(f"  [score] {i}/{len(pending)} ({done_count*100/total:.1f}%) "
                      f"ok={ok} fail={fail} elapsed={elapsed:.0f}s eta={eta:.0f}s", flush=True)
    finally:
        conn.close()
    print(f"[score] 完成: ok={ok} fail={fail} total={total} 耗时={time.time()-t0:.0f}s", flush=True)
    return ok


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
        "note": "乐咕乐股=股票型+混合型仓位(88魔咒专用); 巨潮资讯=全市场资产配置(含债基/货基)",
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
    # 上期 Top100(算抱团度/重叠度 delta_vs_last, 复用给 top20_adjustment prev 查询, 避免重复查询)
    # 方案A: 采集完成度闸门 -- 当期 stocks 数 < 历年同期阈值 -> 采集未完成, delta=null
    # 方案B: 同披露类型对比 -- prev_report 加披露类型过滤(全披露06/12 vs 前十大03/09), 跨类型 delta=null
    cur_stocks_count = conn.execute(
        "SELECT COUNT(*) FROM fund_holding_stock WHERE report_date=?",
        (report_date,),
    ).fetchone()[0]
    _report_month = report_date[4:6]
    is_full_disclosure = _report_month in ("06", "12")  # 0630中报/1231年报=全披露; 0331/0930=前十大
    # 历年同期 stocks 阈值(SQL证据: 0331≈2800/0630≈5000+/0930≈2600/1231≈5100, 取 min*0.8 留余量)
    _INCOMPLETE_THRESHOLDS = {"03": 2200, "06": 4000, "09": 2100, "12": 4100}
    _incomplete_threshold = _INCOMPLETE_THRESHOLDS.get(_report_month, 0)
    is_incomplete = bool(_incomplete_threshold and cur_stocks_count < _incomplete_threshold)
    # prev_report 加披露类型过滤(方案B): 全披露(06/12)只和全披露比, 前十大(03/09)只和前十大比
    _prev_type_months = ("06", "12") if is_full_disclosure else ("03", "09")
    prev_report_row = conn.execute(
        "SELECT MAX(report_date) FROM fund_holding_stock "
        "WHERE report_date < ? AND substr(report_date,5,2) IN (?,?)",
        (report_date, _prev_type_months[0], _prev_type_months[1]),
    ).fetchone()
    # 未过滤类型的上一期(用来判断跨期不可比: 同类型prev为空但未过滤prev存在 -> 跨类型被排除)
    prev_report_unfiltered = conn.execute(
        "SELECT MAX(report_date) FROM fund_holding_stock WHERE report_date < ?",
        (report_date,),
    ).fetchone()
    is_cross_type = (
        not (prev_report_row and prev_report_row[0])
        and bool(prev_report_unfiltered and prev_report_unfiltered[0])
    )
    prev_rows = []
    if prev_report_row and prev_report_row[0]:
        prev_rows = conn.execute(
            "SELECT stock_code, stock_name, fund_count, hold_value_total "
            "FROM fund_holding_stock WHERE report_date=? ORDER BY hold_value_total DESC LIMIT 100",
            (prev_report_row[0],),
        ).fetchall()
    # delta_vs_last: 抱团度 Herfindahl 环比(当期 - 上期)
    # 采集未完成(方案A)或跨披露类型(方案B)时不计算 delta
    prev_total_fund_count = sum(r[2] or 0 for r in prev_rows) or 1
    prev_herf = sum(((r[2] or 0) / prev_total_fund_count) ** 2 for r in prev_rows) if prev_rows else None
    if is_incomplete or is_cross_type or not (rows and prev_rows and prev_herf is not None):
        delta_herf = None
    else:
        delta_herf = round(herf - prev_herf, 6)
    detail["concentration_herfindahl"] = {
        "top10_stocks": [{"code": r[0], "name": r[1], "fund_count": r[2], "value": r[3]}
                          for r in rows[:10]],
        "total_fund_count": total_fund_count,
        "delta_vs_last": delta_herf,
        "prev_report_date": prev_report_row[0] if (prev_report_row and prev_report_row[0]) else None,
        "incomplete": is_incomplete or None,
        "cross_type": is_cross_type or None,
        "current_stocks": cur_stocks_count,
    }

    # 3. overlap_ratio 重叠度: Top30 重仓股平均基金覆盖家数
    top30 = rows[:30] if len(rows) >= 30 else rows
    if top30:
        overlap = sum(r[2] or 0 for r in top30) / len(top30)
    else:
        overlap = None
    results["overlap_ratio"] = round(overlap, 2) if overlap is not None else None
    # delta_vs_last: 重叠度环比(当期 - 上期), 采集未完成或跨披露类型时不计算
    prev_top30 = prev_rows[:30] if len(prev_rows) >= 30 else prev_rows
    prev_overlap = (sum(r[2] or 0 for r in prev_top30) / len(prev_top30)) if prev_top30 else None
    if is_incomplete or is_cross_type or not (overlap is not None and prev_overlap is not None):
        delta_overlap = None
    else:
        delta_overlap = round(overlap - prev_overlap, 2)
    detail["overlap_ratio"] = {
        "top30_avg_fund_count": overlap,
        "top30_stocks": [{"code": r[0], "name": r[1], "fund_count": r[2], "value": r[3]}
                          for r in top30],
        "delta_vs_last": delta_overlap,
        "prev_report_date": prev_report_row[0] if (prev_report_row and prev_report_row[0]) else None,
        "incomplete": is_incomplete or None,
        "cross_type": is_cross_type or None,
        "current_stocks": cur_stocks_count,
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
    # 上一期(复用上方 concentration_herfindahl 块已查的 prev_report_row + prev_rows Top100)
    prev_top20_value = sum(r[3] or 0 for r in prev_rows[:20]) if prev_rows else None
    if cur_top20_value and prev_top20_value and prev_top20_value != 0:
        top20_change = (cur_top20_value - prev_top20_value) / prev_top20_value * 100
        results["top20_adjustment"] = round(top20_change, 4)
        detail["top20_adjustment"] = {
            "current_top20_value": cur_top20_value,
            "prev_top20_value": prev_top20_value,
            "prev_report_date": prev_report_row[0] if (prev_report_row and prev_report_row[0]) else None,
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
    """日更 pipeline: fetch_daily_nav + fetch_estimation + fetch_index_daily + 估算仓位变化（~15s）。

    fetch_estimation 盘后/非交易日返回 0(无数据正常), 盘中才有实时估算。
    fetch_index_daily 刷新 hs300/csi500/gem 三指数日频(baostock ~5s), 供
    _compute_position_estimate 反推算法用——每日必采, 否则 fund_index_daily 滞后
    致 position_estimate.json 算不出最新交易日仓位(2026-08-02 根治: 原 pipeline_daily
    不调 fetch_index_daily, 靠 backfill-nav/estimate 命令一次性刷新, 交易日收盘后
    fund_index_daily 停在旧日期, _compute_position_estimate 缺当日 r_hs300 跳过)。
    position_estimate 反推算法在 export_json_files 的 _compute_position_estimate 独立算,
    pipeline_daily 只保证输入数据(fund_daily_nav + fund_index_daily)每日更新。
    """
    t0 = time.time()
    print("=== pipeline_daily() ===", flush=True)
    stats: dict = {}
    stats["fund_daily_nav"] = fetch_daily_nav()
    # 盘中实时估算(盘后/非交易日返回 0 正常, 不阻塞)
    stats["fund_estimation_nav"] = fetch_estimation()
    # 三指数日频刷新(反推算法基准, baostock ~5s, 每日必采避免 fund_index_daily 滞后)
    for _idx in ("hs300", "csi500", "gem"):
        stats[f"index_{_idx}"] = fetch_index_daily(index_id=_idx)
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


def _compute_sw_industry_alloc(conn, report_date: str, stock_ind_map: dict[str, str]) -> dict:
    """申万一级行业配置(反查口径): 基金 top10 重仓股按申万一级聚合, 揭示真实风格暴露。

    与证监会口径 industry(19 大类, 基金直接披露) 区别:
      - 申万一级: 31 个细分行业, 基于重仓股反查 sw_components.json(非基金直接披露)
      - 证监会口径: 19 个粗门类, 基金直接披露全仓位行业配置(含非重仓股)

    3 个硬限制(前端诚实标注):
      1. 时序不可用: fund_portfolio_hold 仅 1 期(最新季报 20260630), 无历史对比
      2. 覆盖率 ~42%: top10 重仓股平均占净值 42.39%, 仅反映重仓股部分行业暴露, 非完整行业配置
      3. 反查口径: 基于重仓股反查申万一级(非基金直接披露), 有信息差价值但非官方披露

    聚合口径(和证监会 industry JSON 字段对齐便于前端复用):
      - total_weight: SUM(weight_pct) 所有基金重仓股在该行业的占净值比例之和
      - total_value: SUM(hold_value) 实际持仓市值(更准确反映资金暴露)
      - fund_count: COUNT(DISTINCT fund_code) 有多少基金的重仓股落入该行业
      - avg_weight: total_weight / fund_count 基金平均配置该行业的比例

    未映射股票(港股代码等不在 sw_components.json)归 "未分类" 项。
    排序按 total_weight DESC(和证监会口径 industry 一致)。
    """
    hold_rows = conn.execute(
        "SELECT fund_code, stock_code, weight_pct, hold_value FROM fund_portfolio_hold "
        "WHERE report_date=?",
        (report_date,),
    ).fetchall()
    if not hold_rows:
        return {
            "report_date": report_date, "coverage_pct": None,
            "coverage_note": "无重仓股数据", "period_count": 0,
            "industries": [],
        }

    # 按申万一级聚合(未映射归"未分类")
    agg: dict[str, dict] = {}
    unmapped_key = "未分类"
    fund_total_weight: dict[str, float] = {}  # 每基金 top10 weight_pct 之和(算 coverage_pct)
    for fc, sc, wp, hv in hold_rows:
        ind = stock_ind_map.get(sc, "")
        key = ind if ind else unmapped_key
        d = agg.setdefault(key, {"total_weight": 0.0, "total_value": 0.0, "funds": set()})
        d["total_weight"] += (wp or 0)
        d["total_value"] += (hv or 0)
        d["funds"].add(fc)
        fund_total_weight[fc] = fund_total_weight.get(fc, 0) + (wp or 0)

    # coverage_pct: 平均重仓集中度(top10 占净值比例的基金平均值)
    coverage_pct = (round(sum(fund_total_weight.values()) / len(fund_total_weight), 2)
                    if fund_total_weight else None)

    industries_list = []
    for name, d in agg.items():
        fc_count = len(d["funds"])
        total_weight = round(d["total_weight"], 4)
        avg_weight = round(total_weight / fc_count, 4) if fc_count else 0
        industries_list.append({
            "industry_name": name,
            "total_weight": total_weight,
            "total_value": round(d["total_value"], 4),
            "fund_count": fc_count,
            "avg_weight": avg_weight,
        })
    industries_list.sort(key=lambda x: x["total_weight"], reverse=True)

    return {
        "report_date": report_date,
        "coverage_pct": coverage_pct,
        "coverage_note": (f"基于top10重仓股反查申万一级, 覆盖约{coverage_pct}%仓位, "
                          f"仅最新一期无历史时序, 反查口径非基金直接披露"),
        "period_count": 1,
        "fund_count": len(fund_total_weight),
        "industries": industries_list,
    }


def _compute_position_estimate(conn: sqlite3.Connection) -> dict | None:
    """方案A: 今日预估仓位 + 历史预估时序 (hs300 净值回归反推 + lg 全overlap中位数校准)。

    算法 (绝对正确, 和 lg 源同口径: 全市场股票型+混合型基金仓位):
    1. 取 fund_daily_nav 固定 200 只头部偏股基金历史净值涨跌时序 (fetch_nav_history 回填 400 日)
       ⚠️ 固定 200 只面板 (非全市场23786只): 保证跨日中位数口径一致, 不随日频pipeline样本变化漂移
    2. 取 fund_index_daily 三指数日涨跌时序: hs300(大盘价值)+csi500(中盘)+gem(创业板成长)
       csi500/gem 由 backfill-nav 采集入库, 供未来风格分析; 当前回归只用 hs300 (最稳)
    3. 每日算 200 只基金净值涨跌中位数 R_nav_median (抗极端值, 聚合平均掉个股风格偏移)
    4. 滚动 120 日单因子 OLS 回归: R_nav ~ R_hs300, 斜率 = w_stock × β_hs300
       数学依据: R_nav = w_stock×R_stock + w_bond×R_bond + w_cash×R_cash
       忽略 R_bond(~0.01%/日) + R_cash(~0), OLS 斜率 ×100 = w_stock×β_hs300×100
       β_hs300 ≈ 1.06-1.13 (偏股基金略偏成长, β>1), lg 校准吸收 β 偏差
       ⚠️ 选 hs300 而非多因子/综合基准:
          - 多因子 sum(slopes): 三指数高度相关(多重共线性), Σβ 无约束随窗口波动 (82-100 跳变)
          - 综合基准 (hs300+csi500+gem)/3: csi500/gem 波动大, β_composite 不稳 (78-92 跳变, 14%波幅)
          - hs300 单因子: β_hs300 最稳 (101-108, 7%波幅), lg 校准效果最好
    5. lg 校准: lg 历史仓位(fund_position_history source='lg') vs 同期 raw_slope, 算偏差中位数
       校准后仓位 = raw_slope - 偏差中位数 (消除 β_hs300 偏差, 和 lg 口径对齐)
       ⚠️ 用全 overlap 期中位数 (非最近4期均值): overlap ~45期时中位数稳健, 不受尾部噪声干扰
    6. 今日预估 = 最新校准后仓位

    误差控制 (±5% 目标):
    - 滚动 120 日窗口降噪声 (非单日比值)
    - 固定 200 只面板中位数抗极端值 (口径跨日一致)
    - hs300 单因子 β 最稳 (7%波幅, 优于综合基准 14%/多因子 sum 不稳)
    - lg 全 overlap 期中位数校准 (45 期稳健, 非最近 4 期均值)
    - 偏股基金样本 (和 lg 源口径一致, 排除债基/货基/指数/QDII)

    输出 JSON 结构 (供前端 88 魔咒图加"今日预估仓位"点):
    {
      "report_date": "20260731",
      "current": {
        "date": "2026-07-31",
        "position_estimate": 96.5,         # 今日预估仓位% (校准后)
        "raw_slope": 103.2,                # 原始 hs300 斜率% (校准前)
        "lg_latest_position": 96.01,       # lg 最新仓位% (校准锚点)
        "lg_latest_date": "20260724",
        "calibration_offset": 6.7,         # 校准偏移 (raw_slope - lg 全overlap中位数)
        "deviation_from_lg": 0.49,         # 今日预估 - lg最新 (正值=预估高于lg)
        "r_nav_median": 0.85,              # 今日200只基金净值涨跌中位数%
        "r_index": 0.92,                   # 今日沪深300涨跌% (向后兼容别名=r_hs300)
        "r_hs300": 0.92, "r_csi500": 0.5, "r_gem": 0.3,  # 今日三指数涨跌%
        "sample_fund_count": 200,
        "method": "rolling_120d_ols_hs300+lg_calibration",
        "confidence": "high"               # high(>=100样本)/medium(50-99)/low(<50)
      },
      "history": [                         # 历史预估仓位时序 (校准后, 供前端画线)
        {"date": "2026-07-31", "position": 96.5, "raw_slope": 103.2},
        ...
      ],
      "vs_lg": [                           # 预估 vs lg 周频仓位对比 (交叉验证)
        {"date": "2026-07-24", "estimate": 96.5, "lg": 96.01, "diff": 0.49, "raw_slope": 103.2},
        ...
      ],
      "meta": {
        "method": "rolling_120d_ols_regression(hs300) + lg_calibration",
        "benchmark": "hs300 (csi500/gem collected for future style analysis)",
        "sample": "top200_active_equity_funds_fixed_panel",
        "window_days": 120,
        "calibration": "median(raw_slope - lg_position) over all overlap periods",
        "error_margin": "+-5%",
        "note": "hs300单因子OLS最稳, lg全overlap中位数校准吸收β偏差; 固定200只面板口径一致"
      }
    }

    独立计算, 不走 export_data() 7 元组 (遵循 _compute_position_backtest 模式, 避免 190c8f7e 解包破坏)。
    """
    import numpy as np  # 局部 import, 反推算法专用
    from collections import defaultdict
    from datetime import datetime as _dt

    # 1. 取固定 200 只头部偏股基金净值涨跌时序 (口径跨日一致, 不随日频pipeline样本漂移)
    # ⚠️ 固定面板: 用 fund_basic 当前偏股+股票型 ORDER BY fund_code LIMIT 200 选出,
    #    所有日期只取这 200 只 (subquery), 避免 7月23786只 vs 4-6月189只口径不一致
    #    和 fetch_nav_history 回填的同一批基金, 保证面板连续
    nav_rows = conn.execute(
        "SELECT d.date, d.fund_code, d.nav_change_pct FROM fund_daily_nav d "
        "WHERE d.nav_change_pct IS NOT NULL AND d.nav_change_pct != 0 "
        "AND d.fund_code IN ("
        "  SELECT fund_code FROM fund_basic "
        "  WHERE (fund_type LIKE '%偏股%' OR fund_type LIKE '股票型%') "
        "  ORDER BY fund_code ASC LIMIT 200"
        ") ORDER BY d.date ASC"
    ).fetchall()
    if not nav_rows:
        print("[estimate] fund_daily_nav 无历史净值涨跌数据, 请先跑 backfill-nav", flush=True)
        return None
    # 按日期聚合: 每日 200 只基金净值涨跌中位数 (抗极端值, 固定面板口径一致)
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

    # 2. 取三指数日涨跌时序 (多因子: hs300大盘 + csi500中盘 + gem创业板成长)
    idx_rows = conn.execute(
        "SELECT date, index_id, pct_change FROM fund_index_daily "
        "WHERE pct_change IS NOT NULL AND pct_change != 0 "
        "AND index_id IN ('hs300','csi500','gem') ORDER BY date ASC"
    ).fetchall()
    idx_maps: dict[str, dict[str, float]] = {"hs300": {}, "csi500": {}, "gem": {}}
    for d, idx_id, pct in idx_rows:
        if idx_id in idx_maps:
            idx_maps[idx_id][d] = float(pct)
    if not idx_maps["hs300"]:
        print("[estimate] fund_index_daily 无 hs300 数据, 请先跑 fetch_index_daily", flush=True)
        return None
    if not idx_maps.get("csi500") or not idx_maps.get("gem"):
        print("[estimate] fund_index_daily 缺 csi500/gem 数据, 请先跑 backfill-nav (多因子)",
              flush=True)
        return None

    # 3. 合并基金中位数 + hs300(必需) + csi500/gem(可选, 供透明展示), 对齐日期
    #    回归只用 hs300 (最稳), csi500/gem 仅在 current 输出当日涨跌供参考
    pts: list[dict] = []
    for d, nav_med in nav_median_series:
        r_h = idx_maps["hs300"].get(d)
        if r_h is None or r_h == 0:  # hs300 必需 (防除零)
            continue
        r_c = idx_maps["csi500"].get(d)
        r_g = idx_maps["gem"].get(d)
        pts.append({"date": d, "r_nav": nav_med,
                    "r_hs300": float(r_h),
                    "r_csi500": float(r_c) if r_c is not None else None,
                    "r_gem": float(r_g) if r_g is not None else None})
    if len(pts) < 30:
        print(f"[estimate] 合并后有效日期 {len(pts)} < 30", flush=True)
        return None

    # 4. 滚动 120 日单因子 OLS 回归: R_nav ~ R_hs300 (最稳基准)
    #    综合基准 R_composite = (R_hs300 + R_csi500 + R_gem) / 3: 等权合成大盘+中盘+成长
    #    ⚠️ 三指数等权综合后波动率高于单 hs300 (csi500/gem 波动大), β_composite 不稳;
    #       实测 composite raw_slope 范围 78-92 (14%波幅), 比 hs300 单因子 101-108 (7%波幅) 更差
    #    故最终选用 hs300 单因子 (β_hs300 最稳 ~1.06-1.13), csi500/gem 仅采集备用 (未来风格分解)
    #    slope = w_stock × β_hs300, lg 校准吸收 β_hs300 偏差 (45 期中位数, 稳健)
    #    (csi500/gem 仍由 backfill-nav 采集入库, 供未来多因子/风格分析, 当前回归只用 hs300)
    WINDOW = 120  # 60日β波动大(7月raw_slope 101-119跳变), 120日窗平滑β时变, 平衡稳定性+overlap
    raw_slopes: list[dict] = []  # [{date, raw_slope}]
    for i in range(WINDOW, len(pts) + 1):
        sub = pts[i - WINDOW:i]
        x = np.array([p["r_hs300"] for p in sub])
        y = np.array([p["r_nav"] for p in sub])
        var_x = float(np.var(x, ddof=1))
        if var_x <= 0:
            continue
        slope = float(np.cov(x, y, ddof=1)[0, 1] / var_x) * 100  # slope×100=仓位%
        raw_slopes.append({"date": sub[-1]["date"], "raw_slope": round(slope, 2)})
    if not raw_slopes:
        print("[estimate] 滚动回归无有效输出", flush=True)
        return None

    # 5. lg 校准: lg 历史仓位 vs 同期原始斜率, 算偏差中位数 (全 overlap 期)
    lg_rows = conn.execute(
        "SELECT report_date, position_pct FROM fund_position_history "
        "WHERE source='lg' AND position_pct IS NOT NULL "
        "ORDER BY report_date ASC"
    ).fetchall()
    lg_map: dict[str, float] = {r[0]: r[1] for r in lg_rows}

    # 对齐 lg 日期和原始斜率日期 (lg 周频, 斜率日频; 取 lg 日期最近 7 天内的斜率)
    # ⚠️ 修 bug: 旧码 abs(int(d)-int(lg_date))<=700 用 YYYYMMDD 整数差, 跨月可达3个月
    #    (20260703-20260313=390<=700), 致早期 lg 全匹配到首个斜率 -> vs_lg 17期重复 93.29
    #    正确做法: datetime 算真实天数差 <=7 天
    deviations: list[float] = []
    vs_lg_raw: list[dict] = []
    slope_by_date = {s["date"]: s["raw_slope"] for s in raw_slopes}
    slope_dt: dict[str, _dt] = {d: _dt.strptime(d, "%Y%m%d") for d in slope_by_date}
    for lg_date, lg_pos in lg_map.items():
        lg_d = _dt.strptime(lg_date, "%Y%m%d")
        # 找 lg_date 7 天内最近的斜率 (真实日历日差, 非YYYYMMDD整数差)
        best_d, best_s, best_diff = None, None, 999
        for d, s in slope_by_date.items():
            diff = abs((slope_dt[d] - lg_d).days)
            if diff <= 7 and diff < best_diff:
                best_d, best_s, best_diff = d, s, diff
        if best_s is None:
            continue  # 无 7 天内斜率, 跳过 (不硬凑, 避免 vs_lg 重复)
        dev = best_s - lg_pos
        deviations.append(dev)
        vs_lg_raw.append({
            "date": f"{lg_date[:4]}-{lg_date[4:6]}-{lg_date[6:8]}",
            "lg": round(lg_pos, 2),
            "raw_slope": best_s,
            "raw_diff": round(dev, 2),
        })

    # 校准偏移: 全 overlap 期中位数 (稳健, 不受尾部噪声干扰)
    # overlap ~36期时中位数远比 4期均值稳定; 中位数抗异常期(如风格突变期)
    if deviations:
        calibration_offset = float(np.median(deviations))
    else:
        calibration_offset = 0.0
    print(f"[estimate] lg 校准: 全overlap中位数={calibration_offset:.2f}%, "
          f"对齐期数={len(deviations)}, 均值={float(np.mean(deviations)):.2f}%", flush=True)

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

    # 最新日的 r_nav_median / 三指数涨跌
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
            "r_index": round(latest_pt["r_hs300"], 4),  # 向后兼容别名
            "r_hs300": round(latest_pt["r_hs300"], 4),
            "r_csi500": round(latest_pt["r_csi500"], 4) if latest_pt["r_csi500"] is not None else None,
            "r_gem": round(latest_pt["r_gem"], 4) if latest_pt["r_gem"] is not None else None,
            "sample_fund_count": sample_fund_count,
            "method": f"rolling_{WINDOW}d_ols_hs300+lg_calibration",
            "confidence": confidence,
        },
        "history": history,
        "vs_lg": vs_lg[-20:] if len(vs_lg) > 20 else vs_lg,  # 最近20期交叉验证
        "meta": {
            "method": f"rolling_{WINDOW}d_ols_regression(hs300) + lg_calibration",
            "benchmark": "hs300 (csi500/gem collected for future style analysis)",
            "sample": "top200_active_equity_funds_fixed_panel",
            "window_days": WINDOW,
            "calibration": "median(raw_slope - lg_position) over all overlap periods",
            "error_margin": "+-5%",
            "note": "hs300单因子OLS最稳(β_hs300~1.06-1.13, 波幅7%), lg全overlap中位数校准吸收β偏差; 固定200只面板口径一致; csi500/gem已采集备用",
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
        # 方案A: 今日预估仓位 (复用 conn, 必须在 close 前算, 2026-08-02 修 latent bug)
        position_estimate = _compute_position_estimate(conn)
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
    # position_estimate 已在 try 块内算好 (复用 conn)
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
    if cmd not in ("quarterly", "full", "daily", "metrics", "export", "backfill", "backfill-industry", "check-fresh", "backfill-nav", "estimate", "fetch-estimation",
                   "stage0-daily", "stage0-overview", "stage0-risk", "stage0-manager", "stage0-nav", "stage0-sample"):
        print(__doc__)
        print(f"\n用法: python -m app.collector.public_fund <command>")
        print(f"  quarterly       季度全量(5汇总+top1000×2子页+8指标, ~35min)")
        print(f"  full            全量9000只×2子页(~5.25h, 凌晨解耦)")
        print(f"  daily           日更净值+估算仓位变化+三指数刷新(~15s)")
        print(f"  metrics         重算8指标")
        print(f"  export          只导出5类JSON")
        print(f"  backfill --start 20240101 --end 20241231  历史重仓股回填")
        print(f"  backfill-industry --years 2017-2024 --top 1000  行业配置历史回填(8年)")
        print(f"  check-fresh [--top N]  数据新鲜度闸门(exit 0=应跑, 1=无新数据跳过)")
        print(f"  backfill-nav [--days 400]  回填头部200只偏股基金历史净值(反推算法用, ~90s)")
        print(f"  estimate        算预估仓位+导出JSON(需先 backfill-nav + fetch_index_daily)")
        print(f"  fetch-estimation  盘中实时估算(fund_value_estimation_em, 盘后/非交易日返回0)")
        print(f"  ── 筛选器阶段0 (2026-08-02 新增, 挂凌晨不阻塞核心) ──")
        print(f"  stage0-daily    日更4汇总接口~22s(performance/rating/purchase/manager_em)")
        print(f"  stage0-overview 周月更fund_overview_em全量~6.2h(补fund_basic 15新列)")
        print(f"  stage0-risk     季报后risk_indicator+fee_detail~4.5h(逐只xq+费率)")
        print(f"  stage0-manager  自爬fundf10补任职历史~3h(appoint_date+managed_history)")
        print(f"  stage0-nav [--days 1825]  补5年净值历史(27409只, 分批断点续采)")
        print(f"  stage0-sample   小样本验证3只(161725/000001/110011全流程)")
        sys.exit(1)

    # 进程互斥:
    #   - quarterly/full/daily/backfill/backfill-industry/backfill-nav 持 public_fund.lock(默认)
    #   - stage0-* 持 public_fund_stage0.lock 独立锁, 不阻塞 daily/quarterly/full
    #     修复b(2026-08-03): 原 stage0 持公共锁 15h+ 阻塞 daily, daily 撞锁 exit0 当成功
    #     继续 export+deploy 旧数据上线; stage0 写 risk_indicator/fee_detail/manager/overview,
    #     daily 写 daily_nav/index_daily/estimation_nav, 不同表无 DB 写冲突, 可独立锁
    #   - metrics/export/check-fresh/estimate/fetch-estimation 不需要锁
    # 修复a(2026-08-03): 撞锁 sys.exit(2) 而非 return, 让 daily.sh 检测 RC!=0 跳过 export+deploy
    STAGE0_CMDS = ("stage0-daily", "stage0-overview", "stage0-risk", "stage0-manager", "stage0-nav")
    if cmd in ("quarterly", "full", "daily", "backfill", "backfill-industry", "backfill-nav"):
        if not _acquire_lock(nonblock=True):
            print(f"[public_fund] 已有进程在跑（{_DATA_DIR}/public_fund.lock），跳过", file=sys.stderr)
            sys.exit(2)
    elif cmd in STAGE0_CMDS:
        if not _acquire_lock(nonblock=True, lock_name="public_fund_stage0"):
            print(f"[public_fund] stage0 已有进程在跑（{_DATA_DIR}/public_fund_stage0.lock），跳过", file=sys.stderr)
            sys.exit(2)

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
        # 回填头部偏股基金历史净值时序 (反推算法用, 一次性 ~90s)
        # --days N 回填天数 (默认 400, 120日滚动窗后剩~7月 slopes 供 lg 校准)
        days = 400
        for i, a in enumerate(sys.argv[2:], 2):
            if a == "--days" and i + 1 < len(sys.argv):
                days = int(sys.argv[i + 1])
        # 先确保三指数日频有数据 (多因子回归基准: hs300+csi500+gem)
        for _idx in ("hs300", "csi500", "gem"):
            fetch_index_daily(index_id=_idx)
        n = fetch_nav_history(days=days)
        print(f"[backfill-nav] 完成, 总行数={n}", flush=True)
    elif cmd == "estimate":
        # 算预估仓位 + 导出 JSON (需先 backfill-nav)
        # 先刷新三指数到最新 (多因子: hs300+csi500+gem)
        for _idx in ("hs300", "csi500", "gem"):
            fetch_index_daily(index_id=_idx)
        export_json_files()
        print(f"[estimate] 预估仓位 JSON 已导出", flush=True)
    elif cmd == "fetch-estimation":
        # 盘中实时估算 (fund_value_estimation_em, 盘后/非交易日返回0)
        # 供盘中 launchd 定时采调用, 不持锁(轻量~5s, 不和 daily/quarterly/full 撞)
        n = fetch_estimation()
        print(f"[fetch-estimation] 写入 {n} 行", flush=True)
    elif cmd == "stage0-daily":
        # 日更4汇总接口 ~22s (金矿+全市场汇总, 不逐只)
        nj = fetch_fund_performance()  # J 金矿 2.5s
        nk = fetch_fund_rating()  # K 1.8s
        nl = fetch_fund_purchase_status()  # L 6.7s
        nm = fetch_fund_manager(scrape=False)  # M em部分(不自爬) 10s
        print(f"[stage0-daily] J={nj} K={nk} L={nl} M={nm}", flush=True)
    elif cmd == "stage0-overview":
        # 周月更 fund_overview_em 全量补 fund_basic 15新列 ~6.2h (27409只×0.4s)
        n = fetch_fund_overview()
        print(f"[stage0-overview] ok={n}", flush=True)
    elif cmd == "stage0-risk":
        # 季报后 risk_indicator + fee_detail ~4.5h (逐只xq+费率, 含降级自算)
        no = fetch_fund_risk_indicator()
        np_ = fetch_fund_fee_detail()
        print(f"[stage0-risk] O={no} P={np_}", flush=True)
    elif cmd == "stage0-manager":
        # 自爬 fundf10 补任职历史 ~3h (27409只×0.4s, appoint_date+managed_history)
        # 先确保 fund_manager_em 基础数据在(全市场35436行), 再逐只自爬
        n = fetch_fund_manager(scrape=True)
        print(f"[stage0-manager] base={n}", flush=True)
    elif cmd == "stage0-nav":
        # 补5年净值历史(分批, 断点续采) -- 27409只×1825天, 大工程挂凌晨
        days = 1825
        for i, a in enumerate(sys.argv[2:], 2):
            if a == "--days" and i + 1 < len(sys.argv):
                days = int(sys.argv[i + 1])
        conn = get_conn()
        try:
            rows_q = conn.execute("SELECT fund_code FROM fund_basic ORDER BY fund_code").fetchall()
        finally:
            conn.close()
        all_codes = [r[0] for r in rows_q]
        prog = _load_stage0_progress("nav")
        done_set = set(prog.get("done", []))
        pending = [c for c in all_codes if c not in done_set]
        total = len(all_codes)
        print(f"[stage0-nav] 全市场{total}只 days={days}, 已完成{len(done_set)}, "
              f"待采{len(pending)}", flush=True)
        BATCH = 500
        t0 = time.time()
        for bi, i in enumerate(range(0, len(pending), BATCH)):
            batch = pending[i:i + BATCH]
            n = fetch_nav_history(codes=batch, days=days, fund_type_filter="")
            done_set.update(batch)
            prog["done"] = sorted(done_set)
            prog["total"] = total
            _save_stage0_progress("nav", prog)
            elapsed = time.time() - t0
            done_count = len(done_set)
            eta = (elapsed / done_count) * (total - done_count) if done_count > 0 else 0
            print(f"[stage0-nav] batch {bi+1}/{(len(pending)-1)//BATCH+1} "
                  f"done={done_count}/{total} ({done_count*100/total:.1f}%) "
                  f"elapsed={elapsed:.0f}s eta={eta:.0f}s", flush=True)
        print(f"[stage0-nav] 完成, 已采{len(done_set)}/{total}", flush=True)
    elif cmd == "stage0-sample":
        # 小样本验证3只(161725/000001/110011全流程)
        codes = ["161725", "000001", "110011"]
        print("[stage0-sample] 3只基金全流程验证 ...", flush=True)
        fetch_fund_performance()  # J 全市场(含3只)
        fetch_fund_rating()  # K 全市场(含3只)
        fetch_fund_purchase_status()  # L 全市场(含3只)
        fetch_fund_manager(scrape=True, codes=codes)  # M em全量+自爬3只
        fetch_fund_overview(codes=codes)  # N 补3只fund_basic
        fetch_fund_risk_indicator(codes=codes)  # O 3只xq+降级自算
        fetch_fund_fee_detail(codes=codes)  # P 3只费率分档
        print("[stage0-sample] 完成, 查DB验证7表数据", flush=True)


if __name__ == "__main__":
    main()
