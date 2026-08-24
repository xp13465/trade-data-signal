#!/usr/bin/env python3
"""信号凯利回测 - 16 象限 × 9 卖出模式 × 5 周期。

对每条买信号(buy/buy_aux/buy_special/buy_backup),买入该信号对应指数的 track_score
第一名 ETF(10000 元,含费率),按 9 种卖出模式(A=固定10天 / B=3% / C=5% / D=7% 止盈或满期;
E=持有5天 / F=持有15天 不止盈 / G=卖出信号 / H=卖出+追止损 / I=追关注加追止损)各自卖出,
统计胜率/盈亏比/凯利 f*。

G/H/I 为信号驱动卖出(移植 simulate_trade.py sell_types 机制到每笔交易独立):
  G: 对应指数后续第一个 sell 信号日卖出, 无 sell 信号则持有至回测结束
  H: sell OR sell_stop_loss 任一信号(取最早日)触发卖出
  I: G 的基础上, buy_special(追关注)交易额外受 sell_stop_loss 约束(即追关注用 H 逻辑)

16 并列象限(非交叉,同一信号可同时归多组):
  - 评级 3 象限: rating_high/mid/low (按 signal_stats 10d score ≥0.75/≥0.55/<0.55)
  - ETF 归类 4 象限: etf_strong/related/approx/has_track (按第一名 ETF track_tier;
    has_track=none/null 两档: none 即 track_score 30-49 弱跟踪、null 即 track_score<30 或
    数据不足(N<30 无分), 与首页筛选档4口径「track_tier=none/null(跟踪分<50或数据不足)」统一,
    2026-08-24 用户拍板修复——初版实现只装 none 漏装 null 属实现 bug, 见
    docs/kelly/analysis/has-track-caliber-fix-plan-20260824.md)
  - 信号类型 4 象限: sig_main/buy, sig_aux/buy_aux, sig_special/buy_special, sig_backup/buy_backup
  - 指数大类 5 象限: mkt_a(A股宽基) / mkt_hk(港股) / mkt_global(全球) / mkt_industry(申万行业) / mkt_concept(概念)

5 周期: y1(近 1 年) / y3(近 3 年) / y5(近 5 年) / y10(近 10 年) / all(全部)

用法:
  python3 scripts/signal_kelly_backtest.py                     # 默认输出 static-site/data/
  python3 scripts/signal_kelly_backtest.py --output PATH.json  # 指定输出路径
"""
import argparse
import bisect
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import yaml

# ── 路径 ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))  # trade/scripts/
ROOT = os.path.dirname(SCRIPT_DIR)                        # trade/

# 复用 simulate_trade 的费率函数 + ETF 价格加载
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, ROOT)
from simulate_trade import (  # noqa: E402
    _buy_with_fees, _sell_with_fees, _is_sh_etf,
    COMMISSION_RATE, SLIPPAGE, MIN_COMMISSION, TRANSFER_FEE_RATE_SH,
)
from app.db import get_conn  # noqa: E402

# 凯利回测默认费率(保持该回测的既定口径, 不受 simulate_trade 重构影响)
# simulate_trade._sell_with_fees 重构后默认新增印花税万5 + 过户费沪深统一;
# 凯利回测按原口径走: 佣金万3 min5 + 滑点千1 + 沪市过户费万0.1(仅沪市 ETF) + 印花税恒0
# (与 purpose-notes lab.sigkelly "费率口径/ETF档印花税恒0" 公示一致, 避免重构侧漏到凯利)
_KELLY_FEE_CONFIG = {
    'buy_commission': COMMISSION_RATE,
    'sell_commission': COMMISSION_RATE,
    'stamp_tax': 0.0,
    'transfer_fee': TRANSFER_FEE_RATE_SH,
    'transfer_fee_mode': 'sh',
    'slippage': SLIPPAGE,
    'slippage_mode': 'fixed',
    'slippage_sigma': 0.0,
    'min_commission': MIN_COMMISSION,
}

# ── 常量 ──────────────────────────────────────────────────────────────────────
BUY_AMOUNT = 10000         # 每笔买入金额(元) -- 1000->10000 降低最低佣金占比(往返费率~1%->~0.3%)
HOLD_DAYS = 10             # 默认最大持有交易日(ABCD 模式用; E=5/F=15 per-mode 覆盖)
# 买入价口径: 1=次日开盘(真实跟单口径, v1.1.4 起默认, 见 kelly-nextday-open-backtest.md)
#            0=信号日收盘等价 accum_nav(旧基线, 用于回退验证)
KELLY_BUY_NEXTDAY = int(os.environ.get("KELLY_BUY_NEXTDAY", "1"))
# 份额折算伪跳空阈值(|次日open/信号日close - 1| > 该值即剔除该笔, 见报告 §1.4)
PSEUDO_GAP_EXCLUDE = 0.20
# 数据截止日(仅用于自验复现报告 §2.1 数字, 默认不设=全量; 不进线上默认路径)
KELLY_ASOF = os.environ.get("KELLY_ASOF", "")
# 入样信号白名单(§23.6 单一事实源 = config/universe_rules.yaml buy_whitelist, 此处为对齐副本)。
# 改动必须与 yaml 同步, 并跑 scripts/check_universe_alignment.py 对称校验(断言3 会拦截白名单漂移)。
BUY_SIGNALS = ("buy", "buy_aux", "buy_special", "buy_backup")

SELL_MODES = {
    "A": {"label": "固定10天", "hold_days": 10, "stop_profit": None},
    "B": {"label": "3%止盈",   "hold_days": 10, "stop_profit": 0.03},
    "C": {"label": "5%止盈",   "hold_days": 10, "stop_profit": 0.05},
    "D": {"label": "7%止盈",   "hold_days": 10, "stop_profit": 0.07},
    "E": {"label": "持有5天",  "hold_days": 5,  "stop_profit": None},
    "F": {"label": "持有15天", "hold_days": 15, "stop_profit": None},
    # G/H/I: 信号驱动卖出(每笔交易查对应指数后续 sell/sell_stop_loss 信号, 无则持有至回测结束)
    # desc=短说明(前端 modeDesc 用); guidance_desc=完整跟单文案(_guidance 用, 与 desc 同源一处维护)
    "G": {"label": "卖出信号",   "hold_days": None, "stop_profit": None, "signal": True,
          "sell_types": ("sell",), "desc": "指数卖出信号触发",
          "guidance_desc": "对应指数卖出信号(sell)触发卖出，无信号则持有至回测结束"},
    "H": {"label": "卖出+追止损", "hold_days": None, "stop_profit": None, "signal": True,
          "sell_types": ("sell", "sell_stop_loss"), "desc": "卖出或追止损信号触发",
          "guidance_desc": "对应指数卖出信号(sell)或追止损信号(sell_stop_loss)任一触发卖出"},
    "I": {"label": "追关注加追止损", "hold_days": None, "stop_profit": None, "signal": True,
          "sell_types": ("sell",), "special_sell_types": ("sell", "sell_stop_loss"),
          "desc": "追关注额外受追止损约束",
          "guidance_desc": "对应指数卖出信号(sell)触发卖出；追关注(buy_special)交易额外受追止损信号(sell_stop_loss)约束"},
}

PERIODS = {
    "y1":  {"label": "近1年", "cutoff": None},  # 运行时动态算
    "y3":  {"label": "近3年", "cutoff": None},
    "y5":  {"label": "近5年", "cutoff": None},
    "y10": {"label": "近10年", "cutoff": None},
    "all": {"label": "全部", "cutoff": "0"},
}

RATING_HIGH = 0.75
RATING_MID = 0.55

# 大盘择时(MA60)过滤 - 降亏toggle后端注入
MARKET_FILTER_MA_WINDOW = 60
A_STOCK_MARKETS = {"a", "concept", "industry"}  # 仅A股类按大盘择时, hk/global标true不过滤

QUADRANT_META = {
    # 评级 3 象限(互斥,覆盖全体有 score 的信号)
    "rating_high":   {"label": "高评级信号", "desc": "技术参考点综合把握度 score≥0.75"},
    "rating_mid":    {"label": "中评级信号", "desc": "0.55≤score<0.75"},
    "rating_low":    {"label": "低评级信号", "desc": "score<0.55"},
    # ETF 归类 4 象限(评级的子集; 2026-08-24 起 none+null 同归 has_track, 与首页筛选档4口径统一)
    "etf_strong":    {"label": "强关联ETF",  "desc": "track_tier=strong (track_score≥75)"},
    "etf_related":   {"label": "相关ETF",    "desc": "track_tier=related (60-74)"},
    "etf_approx":    {"label": "近似ETF",    "desc": "track_tier=approx (50-59)"},
    "etf_has_track": {"label": "有跟踪ETF",  "desc": "track_tier=none/null (track_score<50 或数据不足: none=30-49弱跟踪, null=<30极弱或N<30无分)"},
    # 信号类型 4 象限(按 signal 字段, 互斥覆盖全体买信号)
    "sig_main":      {"label": "主关注",     "desc": "buy 主关注核心买入信号"},
    "sig_aux":       {"label": "辅关注",     "desc": "buy_aux 辅助买入信号"},
    "sig_special":   {"label": "追关注",     "desc": "buy_special 追涨信号"},
    "sig_backup":    {"label": "备关注",     "desc": "buy_backup 备选信号"},
    # 指数大类 5 象限(按 indicators.yaml market 字段, 互斥覆盖全体有 ETF 映射的信号)
    "mkt_a":         {"label": "A股宽基/红利", "desc": "market=a (上证/深证/沪深300/中证500/创业板/科创/北证/红利等)"},
    "mkt_hk":        {"label": "港股",       "desc": "market in (hk,hk_industry) (恒生/恒生科技/恒生国企/港股板块)"},
    "mkt_global":    {"label": "全球/欧美/国债", "desc": "market=global (道琼斯/纳指/标普/国债等)"},
    "mkt_industry":  {"label": "申万行业",   "desc": "market=industry (31个申万一级行业)"},
    "mkt_concept":   {"label": "概念/主题",   "desc": "market=concept (同花顺/中证概念主题)"},
}

# signal 字段 -> 信号类型象限 key
SIG_QUAD_MAP = {
    "buy": "sig_main",
    "buy_aux": "sig_aux",
    "buy_special": "sig_special",
    "buy_backup": "sig_backup",
}

# indicators.yaml market 字段 -> 指数大类象限 key
MARKET_QUAD_MAP = {
    "a": "mkt_a",
    "hk": "mkt_hk",
    "hk_industry": "mkt_hk",  # 港股板块归入港股大类
    "global": "mkt_global",
    "industry": "mkt_industry",
    "concept": "mkt_concept",
}


# ── 数据加载 ──────────────────────────────────────────────────────────────────

def _load_signal_stats():
    """读 signal_stats.json: 优先 static-site/data/(export 最新版), 回退 data/(根目录)。"""
    for p in [
        os.path.join(ROOT, "static-site", "data", "signal_stats.json"),
        os.path.join(ROOT, "data", "signal_stats.json"),
    ]:
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError("signal_stats.json 未找到 (static-site/data/ 和 data/ 都没有)")


def _load_board_etf_map():
    """读 board_etf_map.json (data/ 根目录)。"""
    p = os.path.join(ROOT, "data", "board_etf_map.json")
    if not os.path.exists(p):
        raise FileNotFoundError(f"board_etf_map.json 未找到: {p}")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# ── 换标漂移修复: 每信号事件 ETF 选择冻结落盘(#58) ────────────────────────────
# 背景: 原 _build_best_etf 每次回测都读当前 board_etf_map.json 取每指数当前 track_score 最高 ETF,
# 并把该 ETF 指派给该指数所有历史信号日。一旦某 index 的 best ETF 被另一只反超, 该 index 全部历史成交
# 整批从旧代码切到新代码(旧记录删除、新代码独立行情重算收益)——换标漂移。
# 修复: 历史成交应按"信号日当时的 index→ETF 映射"固化; 因无历史映射快照(见 Q1), 采用冻结落盘方案:
# 对每个已出现的信号事件 (date|index_id|signal), 首次回测时固化其 ETF 选择到持久化查找表
# data/signal_kelly_etf_freeze.json; 之后 board_etf_map 的 best ETF 变更只影响「新出现的信号事件」,
# 不改写已固化的历史成交。换标只影响未来新信号。

# freeze 文件路径默认为 data/ 根目录(非 git 提交的运行时持久化数据)
ETF_FREEZE_PATH_ENV = "SIGNAL_KELLY_ETF_FREEZE_PATH"


def _etf_freeze_path():
    p = os.environ.get(ETF_FREEZE_PATH_ENV)
    if p:
        return p
    return os.path.join(ROOT, "data", "signal_kelly_etf_freeze.json")


def _signal_key(date, iid, sig):
    """信号事件的唯一键: date|index_id|signal。"""
    return f"{date}|{iid}|{sig}"


def _load_etf_freeze():
    """读冻结查找表 {signal_key: {code, name, track_tier, ..., frozen_at}}。文件不存在返回 {}。"""
    p = _etf_freeze_path()
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _save_etf_freeze(freeze):
    """写冻结查找表(原子写: 先写临时文件再 rename)。"""
    p = _etf_freeze_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(freeze, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, p)


# ── 宇宙感知剪枝(v1.1.7 实施批, 2026-08-24 用户拍板) ─────────────────────────
# 背景: 冻结固化机制(#58)对已固化信号事件直接返回冻结 ETF, 绕过当前宇宙判定——
# board_etf_map 已把 bj50(北证50) 等改为空数组(显式不收录, build_board_etf_map.py 不留兜底),
# 但 20260813 中间版 map 时代固化的 72 个 bj50 键仍从冻结路径穿透入样, trades 残留
# 41 笔底层交易 / 1476 展示行(has_track 卡每卡 41 笔)。
# 修复: 解析前先查 config/universe_rules.yaml excluded_categories 排除声明(§23.6 单一事实源,
# 禁止硬编码任何指数 id 字面量), 命中即视为无效不入样, 返回 (None, False) 与
# "map 无此 key" 路径同语义; 新信号与已冻结信号一视同仁(冻结值不得穿透排除类别)。
# 铁律: freeze 文件本体不动(只读旁路, 不删不改键), 剪枝发生在读取侧。
# 影响面佐证: docs/kelly/analysis/bj50-residue-pruning-impact-20260824.md
# (NEW14 默认组合 +0.26% 且堵「过滤真空日垫底替补」洞; 2011-2024 十四年零变化)。

_PRUNED_UNIVERSE_N = 0     # 剪枝计数(调用级: needed_etfs 与分类循环各扫一遍, 全量跑下≈事件数×2)
_EXCLUDED_MATCHERS_CACHE = None


def _excluded_matchers():
    """读 config/universe_rules.yaml excluded_categories, 返回 ((name, mode, patterns), ...) 缓存版。"""
    global _EXCLUDED_MATCHERS_CACHE
    if _EXCLUDED_MATCHERS_CACHE is None:
        cfg_path = os.path.join(ROOT, "config", "universe_rules.yaml")
        matchers = []
        if os.path.exists(cfg_path):
            with open(cfg_path, encoding="utf-8") as f:
                rules = yaml.safe_load(f) or {}
            for cat in rules.get("excluded_categories") or []:
                m = cat.get("match")
                pats = (m,) if isinstance(m, str) else tuple(m or ())
                matchers.append((cat.get("name", "?"), cat.get("mode", "?"), pats))
        else:
            print(f"  ⚠ universe_rules.yaml 未找到({cfg_path}), 宇宙感知剪枝不生效", file=sys.stderr)
        _EXCLUDED_MATCHERS_CACHE = tuple(matchers)
    return _EXCLUDED_MATCHERS_CACHE


def _iid_in_excluded_category(iid):
    """index_id 是否命中排除类别(匹配口径与 check_universe_alignment._match_any 一致: 前缀或全等)。"""
    for _name, _mode, pats in _excluded_matchers():
        if any(iid.startswith(p) or iid == p for p in pats):
            return True
    return False


def _resolve_etf(date, iid, sig, best_etf, freeze):
    """解析某信号事件 (date,index_id,signal) 匹配的 ETF。

    - 宇宙感知剪枝(v1.1.7): 该指数命中 config/universe_rules.yaml 排除类别(债/情绪/
      全球商品利率/港股行业/空数组)→视为无效不入样, 返回 (None, False)(与 "map 无此 key"
      同语义); 冻结值也不得穿透排除类别(freeze 文件本体不动, 读取侧剪枝)。
    - 若该信号事件已在冻结查找表: 返回冻结的 ETF 值(历史成交固化, 不再随当前 best 变更)。
    - 若未冻结(新信号): 用当前 best ETF, 并就地写入 freeze(便于 compute() 结束时持久化)。
    返回 (etf_dict, is_frozen)。best_etf 无此指数时返回 (None, False)。
    """
    global _PRUNED_UNIVERSE_N
    if _iid_in_excluded_category(iid):
        _PRUNED_UNIVERSE_N += 1
        return None, False
    key = _signal_key(date, iid, sig)
    frozen = freeze.get(key)
    if frozen is not None:
        return frozen, True
    be = best_etf.get(iid)
    if not be:
        return None, False
    # 冻结当前 best(补充 frozen_at 时间戳便于审计)
    entry = dict(be)
    from datetime import datetime as _dt
    entry["frozen_at"] = _dt.now().strftime("%Y-%m-%d %H:%M")
    freeze[key] = entry
    return entry, False


def _load_market_map():
    """读 config/indicators.yaml -> {index_id: market}。

    用于按指数大类(mkt_a/hk/global/industry/concept)重新分桶。
    """
    cfg_path = os.path.join(ROOT, "config", "indicators.yaml")
    if not os.path.exists(cfg_path):
        raise FileNotFoundError(f"indicators.yaml 未找到: {cfg_path}")
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    market_map = {}
    for item in (cfg or {}).get("indices", []):
        iid = item.get("id")
        market = item.get("market")
        if iid and market:
            market_map[iid] = market
    return market_map


def _load_market_state(conn):
    """加载沪深300日频, 计算 MA60, 返回 (state, dates)。

    state: {date: True(多头 close>MA60)/False(空头)}; dates: 排序日期列表(供 bisect)。
    无 hs300 数据时返回 ({}, []), _is_market_bull 保守返回 True(不过滤)。
    """
    rows = conn.execute(
        "SELECT date, close FROM index_daily WHERE index_id='hs300' "
        "AND close IS NOT NULL ORDER BY date"
    ).fetchall()
    if not rows:
        print("  ⚠ hs300 数据为空, 大盘择时过滤不生效", file=sys.stderr)
        return {}, []
    dates = [r[0] for r in rows]
    closes = [r[1] for r in rows]
    ma_window = MARKET_FILTER_MA_WINDOW
    state = {}
    for i in range(ma_window - 1, len(dates)):
        ma = sum(closes[i - ma_window + 1 : i + 1]) / ma_window
        state[dates[i]] = closes[i] > ma
    return state, dates


def _load_market_tiers(conn, index_id='hs300'):
    """指定指数(index_id, 默认 hs300)四档大盘状态(与 app/queries.py 同口径算法)。
    返回 {date: tier_str} (tier_str ∈ {"牛市·主升","上升期","下降期","熊市·主跌"})；
    无数据返回 {}。仅注入 trade 供前端判定用, 不参与回测过滤本身
    (过滤由前端 lab.js _kellyPassesFadeFilters 对 trade 数据重算)。
    """
    rows = conn.execute(
        "SELECT date, close FROM index_daily WHERE index_id=? "
        "AND close IS NOT NULL ORDER BY date", (index_id,)
    ).fetchall()
    if not rows:
        return {}
    dates = [r[0] for r in rows]
    closes = [r[1] for r in rows]
    n = len(dates)

    def _ma(w, i):
        if i < w - 1:
            return None
        return sum(closes[i - w + 1: i + 1]) / w

    tiers = {}
    for i in range(200 - 1, n):
        c = closes[i]
        m20, m60, m120, m200 = _ma(20, i), _ma(60, i), _ma(120, i), _ma(200, i)
        if None in (m20, m60, m120, m200):
            continue
        bull = m20 > m60 > m120
        bear = m20 < m60 < m120
        if c > m200 and bull:
            tier = "牛市·主升"
        elif c > m200:
            tier = "上升期"
        elif c < m200 and bear:
            tier = "熊市·主跌"
        elif c < m200:
            tier = "下降期"
        else:
            tier = "上升期"
        tiers[dates[i]] = tier
    return tiers


def _market_tier_at(signal_date, market_tiers, market_dates):
    """<= 信号日最近的四档 tier_str；无状态返回 ""(前端视为不过滤)。"""
    if not market_tiers:
        return ""
    idx = bisect.bisect_right(market_dates, signal_date) - 1
    while idx >= 0:
        d = market_dates[idx]
        if d in market_tiers:
            return market_tiers[d]
        idx -= 1
    return ""


def _is_market_bull(signal_date, market_state, market_dates):
    """判断信号日的大盘状态。查找 <= signal_date 的最近有 MA60 状态的交易日。

    无数据时返回 True(保守不过滤)。
    """
    if not market_state:
        return True
    idx = bisect.bisect_right(market_dates, signal_date) - 1
    while idx >= 0:
        d = market_dates[idx]
        if d in market_state:
            return market_state[d]
        idx -= 1
    return True


def _build_best_etf(etf_map):
    """每指数取 track_score 最高的 ETF 作为该信号匹配 ETF。

    返回 {index_id: {"code": etf_code, "track_tier": tier}}。
    无 track_score 的指数不纳入(调用方跳过)。
    """
    best = {}
    for iid, cands in etf_map.items():
        if iid == "_meta" or not isinstance(cands, list):
            continue
        scored = [c for c in cands if c.get("track_score") is not None]
        if not scored:
            continue
        top = max(scored, key=lambda c: c["track_score"])
        best[iid] = {"code": top["code"], "track_tier": top.get("track_tier", "none"),
                     "name": top.get("name", ""),
                     "track_score": top.get("track_score"),
                     "match_method": top.get("match_method"),
                     "track_low_confidence": top.get("track_low_confidence")}
    return best


def _get_etf_db_path():
    """ETF DB 路径: 优先 trade-data/data/etf_national_team.db(主库), 回退 trade/data/。"""
    main = os.path.join(os.path.dirname(ROOT), "trade-data", "data", "etf_national_team.db")
    if os.path.exists(main):
        return main
    return os.path.join(ROOT, "data", "etf_national_team.db")


def _batch_load_etf_prices(etf_codes):
    """批量加载 ETF 价格(accum_nav + 原始 open/close), 供次日开盘买入口径(gap 换算)使用。

    单次 SQL 查询所有需要的 ETF, 比 per-ETF 查询快 ~100x。
    """
    if not etf_codes:
        return {}, {}, {}, {}

    db_path = _get_etf_db_path()
    if not os.path.exists(db_path):
        print(f"  ⚠ ETF DB 不存在: {db_path}", file=sys.stderr)
        return {}, {}, {}, {}

    nav_map = {c: {} for c in etf_codes}
    open_map = {c: {} for c in etf_codes}
    close_map = {c: {} for c in etf_codes}
    sorted_dates = {c: [] for c in etf_codes}
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        # 分批查(SQLite IN 占位符上限 999)
        codes = list(etf_codes)
        batch_size = 500
        for i in range(0, len(codes), batch_size):
            batch = codes[i:i + batch_size]
            placeholders = ",".join("?" * len(batch))
            rows = conn.execute(
                f"SELECT etf_code, date, accum_nav, open, close FROM etf_daily "
                f"WHERE etf_code IN ({placeholders}) AND accum_nav IS NOT NULL "
                f"ORDER BY etf_code, date",
                batch,
            ).fetchall()
            for code, date, nav, op, cl in rows:
                nav_map[code][date] = nav
                if op is not None:
                    open_map[code][date] = op
                if cl is not None:
                    close_map[code][date] = cl
    finally:
        conn.close()

    # 预排序日期列表(供 bisect 查找, 基于有 accum_nav 的交易日)
    for code in etf_codes:
        sorted_dates[code] = sorted(nav_map[code].keys())

    return nav_map, open_map, close_map, sorted_dates


# ── 回测 ──────────────────────────────────────────────────────────────────────

def _next_trading_day(signal_date, sorted_dates_list):
    """返回 signal_date 之后第一个交易日(次日开盘定价用)。无则返回 None。"""
    idx = bisect.bisect_right(sorted_dates_list, signal_date)
    if idx < len(sorted_dates_list):
        return sorted_dates_list[idx]
    return None


def _calendar_days(d1, d2):
    """两个 YYYYMMDD 日期字符串间的自然日天数(max 0)。"""
    try:
        dd1 = datetime.strptime(d1, "%Y%m%d")
        dd2 = datetime.strptime(d2, "%Y%m%d")
        return max((dd2 - dd1).days, 0)
    except (ValueError, TypeError):
        return 0


def _backtest_one(signal_date, prices, sorted_dates_list, etf_code, etf_name, stop_profit,
                  index_id=None, signal=None, track_tier=None, track_score=None,
                  match_method=None, track_low_confidence=None, today=None, hold_days=HOLD_DAYS,
                  market_state=None, rating=None, sell_mode=None, sell_signals=None, market_tier=None, market_tier_all=None, market_tier_cyb=None,
                  open_map=None, close_map=None):
    """单笔信号回测: 信号日买入 1000 元, 持有期内止盈或满 hold_days 卖出。

    prices: 该 ETF 的 {date: accum_nav} 字典(已由调用方从 price_map 取出)。
    today: 全局最新数据日(YYYYMMDD), 用于持仓中trade预估; None 时回退本ETF最后日期。
    hold_days: 最大持有交易日(per-mode, A/B/C/D=10, E=5, F=15; G/H/I=None 信号驱动不用)。
    market_state: 大盘择时状态(True=多头进场允许/False=空头跳过过滤; 非A股类标True)。
    sell_mode: 卖出模式 key(A-I), G/H/I 走信号驱动卖出分支。
    sell_signals: 该指数 [(date, signal)] 按日期排序的卖出信号时间线(G/H/I 用, 可能为 [])。
    返回 dict {signal_date, index_id, signal, buy_date, sell_date, etf_code, etf_name,
              track_tier, track_score, match_method, track_low_confidence,
              buy_price, sell_price, shares, profit, return_pct, hold_days, sell_reason,
              current_price, market_state, rating}
    或 None(信号日无价格/买入失败/持仓中无当前价)。

    持仓中trade: 信号日后不足 hold_days 个交易日时, 不丢弃, 按当前价预估盈亏
    (sell_date="", sell_price=0, current_price=当前价, sell_reason="持有中"),
    预估 profit 正常计入统计(不隔离), 详见 _compute_stats 的 holding_count。
    """
    if not prices:
        return None

    buy_nav = prices.get(signal_date)
    if buy_nav is None or buy_nav <= 0:
        return None  # 信号日无 ETF 价格

    # 买入价口径:
    #  - KELLY_BUY_NEXTDAY=1(v1.1.4 起默认, 真实跟单): 信号日收盘后固化, 实际次日开盘才能成交。
    #    买入价 = 信号日 accum_nav × (次日原始 open / 信号日原始 close), 即把次日开盘价
    #    换算成 accum_nav 等价值(scale-free, 正确处理分红/份额折算, 见 kelly-nextday-open-backtest.md §1.1)。
    #  - KELLY_BUY_NEXTDAY=0(旧基线): 直接取信号日 accum_nav(当日收盘等价)。
    # 伪跳空剔除(报告 §1.4): 若 |次日open/信号日close - 1| > 20%(份额折算等, 非真实可交易跳空),
    # 次日开盘价不可用, 整笔剔除(基线与次日同口径剔除, 保证可比)。
    if KELLY_BUY_NEXTDAY:
        sig_close = close_map.get(etf_code, {}).get(signal_date) if close_map else None
        nxt_open = open_map.get(etf_code, {}).get(_next_trading_day(signal_date, sorted_dates_list)) if open_map else None
        if sig_close is None or sig_close <= 0 or nxt_open is None or nxt_open <= 0:
            return None  # 缺原始价, 无法按次日开盘重定价
        gap = nxt_open / sig_close - 1.0
        if abs(gap) > PSEUDO_GAP_EXCLUDE:
            return None  # 伪跳空(份额折算), 剔除该笔
        buy_nav = buy_nav * (1.0 + gap)

    # 买入(含费率)
    buy_price, shares, _comm, _tf = _buy_with_fees(BUY_AMOUNT, buy_nav, etf_code, _KELLY_FEE_CONFIG)
    if shares <= 0:
        return None

    # 用 bisect 找未来 hold_days 个交易日
    dates = sorted_dates_list
    idx = bisect.bisect_right(dates, signal_date)

    # 模式 G/H/I: 信号驱动卖出(每笔交易查对应指数后续 sell/sell_stop_loss 信号, 无则持有至回测结束)。
    # 置于 future_dates 之前: G/H/I 的 hold_days=None, 不参与固定持有日切片。
    if sell_mode in ("G", "H", "I"):
        return _backtest_signal_sell(
            signal_date, prices, dates, etf_code, sell_mode, signal, sell_signals, today,
            index_id, etf_name, track_tier, track_score, match_method, track_low_confidence,
            market_state, rating, buy_price, shares, market_tier, market_tier_all,
            market_tier_cyb,
        )

    future_dates = dates[idx:idx + hold_days]

    # 持仓中: 未来不足 hold_days 个交易日, 按当前价预估盈亏(不丢弃, 含未实现综合表现)
    if len(future_dates) < hold_days:
        ref_today = today if today else (dates[-1] if dates else None)
        current_nav = prices.get(ref_today) if ref_today else None
        price_date = ref_today  # current_nav 实际取值日期(回退时下方更新为 dates[-1])
        if current_nav is None and dates:
            current_nav = prices.get(dates[-1])  # 回退到本ETF最后日期
            price_date = dates[-1]
        if current_nav is None or current_nav <= 0:
            return None  # 无当前价, 无法预估
        _sp, _sell_amount, _comm2, _tf2, net, _st = _sell_with_fees(shares, current_nav, etf_code, _KELLY_FEE_CONFIG)
        profit = net - BUY_AMOUNT
        return_pct = profit / BUY_AMOUNT * 100
        # hold_days 用交易日口径(与已卖出 L264 一致): price_date 在 future_dates 的序号+1.
        # 修复: 原用 _calendar_days(signal_date, ref_today) 按全局 today 算自然日, 但
        # current_price 可能回退到本 ETF 滞后日期(如 7/28), 两者不匹配致 hold_days 虚高
        # (如显示 18 天, 实际仅 6 个交易日). 改跟踪 price_date + 交易日口径, 不超 hold_days.
        try:
            hold = future_dates.index(price_date) + 1
        except ValueError:
            hold = 0  # price_date == signal_date(当天买入, 无后续交易日)
        return {
            "signal_date": signal_date,
            "index_id": index_id,
            "signal": signal,
            "buy_date": signal_date,
            "sell_date": "",
            "etf_code": etf_code,
            "etf_name": etf_name,
            "track_tier": track_tier,
            "track_score": track_score,
            "match_method": match_method,
            "track_low_confidence": track_low_confidence,
            "buy_price": round(buy_price, 6),
            "sell_price": 0,
            "shares": round(shares, 6),
            "profit": round(profit, 4),
            "return_pct": round(return_pct, 4),
            "hold_days": hold,
            "sell_reason": "持有中",
            "current_price": round(current_nav, 6),
            "market_state": market_state,
            "market_tier": market_tier,
            "market_tier_all": market_tier_all,
            "market_tier_cyb": market_tier_cyb,
            "rating": rating,
        }

    # 模式 A/E/F: 最后一天卖出(不止盈); 模式 B/C/D: 逐日检查止盈
    sell_date = future_dates[-1]  # 默认最后一天(D+hold_days)
    sell_reason = "到期"
    if stop_profit is not None:
        for d in future_dates:
            nav = prices[d]
            unrealized = nav / buy_price - 1  # 未实现收益率(小数)
            if unrealized >= stop_profit:
                sell_date = d
                sell_reason = "止盈"
                break

    sell_nav = prices[sell_date]
    sell_price, _sell_amount, _comm2, _tf2, net, _st = _sell_with_fees(shares, sell_nav, etf_code, _KELLY_FEE_CONFIG)

    profit = net - BUY_AMOUNT
    return_pct = profit / BUY_AMOUNT * 100
    hold = future_dates.index(sell_date) + 1  # D+1=1, ..., D+10=10

    return {
        "signal_date": signal_date,
        "index_id": index_id,
        "signal": signal,
        "buy_date": signal_date,
        "sell_date": sell_date,
        "etf_code": etf_code,
        "etf_name": etf_name,
        "track_tier": track_tier,
        "track_score": track_score,
        "match_method": match_method,
        "track_low_confidence": track_low_confidence,
        "buy_price": round(buy_price, 6),
        "sell_price": round(sell_price, 6),
        "shares": round(shares, 6),
        "profit": round(profit, 4),
        "return_pct": round(return_pct, 4),
        "hold_days": hold,
        "sell_reason": sell_reason,
        "current_price": 0,
        "market_state": market_state,
        "market_tier": market_tier,
        "market_tier_all": market_tier_all,
        "market_tier_cyb": market_tier_cyb,
        "rating": rating,
    }


def _backtest_signal_sell(signal_date, prices, dates, etf_code, sell_mode, signal, sell_signals,
                          today, index_id, etf_name, track_tier, track_score, match_method,
                          track_low_confidence, market_state, rating, buy_price, shares, market_tier=None, market_tier_all=None, market_tier_cyb=None):
    """模式 G/H/I 信号驱动卖出(每笔交易独立, 混合指数回测)。

    G: 对应指数后续第一个 sell 信号日卖出, 无 sell 信号则持有至回测结束。
    H: sell OR sell_stop_loss 任一信号(取最早日)触发卖出。
    I: buy_special(追关注)交易用 H 逻辑, 其他交易用 G 逻辑。
    卖出价 = 信号日当日 ETF 收盘价(accum_nav)。sell_signals 为该指数 [(date, signal)] 按日期排序。
    返回与 _backtest_one 同结构 dict, 或 None(无当前价无法预估)。
    """
    # 决定该笔交易的卖出信号类型集合: 读 SELL_MODES 配置(G=sell / H=sell+sell_stop_loss /
    # I=buy_special 追关注用 special_sell_types, 其他用 sell_types), 不硬编码模式逻辑
    mode_def = SELL_MODES[sell_mode]
    special_types = mode_def.get("special_sell_types")
    if signal == "buy_special" and special_types:
        sell_types = special_types
    else:
        sell_types = mode_def.get("sell_types") or ("sell",)

    # 找买入日之后第一个匹配卖出信号日(要求该 ETF 当日有价格可卖出)
    sell_date = None
    sell_reason = None
    for d, sig in (sell_signals or []):
        if d <= signal_date or sig not in sell_types:
            continue
        if prices.get(d):
            sell_date = d
            sell_reason = "追止损卖出" if sig == "sell_stop_loss" else "卖出信号"
            break

    if sell_date is None:
        # 无匹配卖出信号: 持有至回测结束, 按当前价预估盈亏(复用持仓中口径)
        ref_today = today if today else (dates[-1] if dates else None)
        current_nav = prices.get(ref_today) if ref_today else None
        price_date = ref_today
        if current_nav is None and dates:
            current_nav = prices.get(dates[-1])
            price_date = dates[-1]
        if current_nav is None or current_nav <= 0:
            return None
        _sp, _sell_amount, _comm2, _tf2, net, _st = _sell_with_fees(shares, current_nav, etf_code, _KELLY_FEE_CONFIG)
        profit = net - BUY_AMOUNT
        return_pct = profit / BUY_AMOUNT * 100
        try:
            hold = dates.index(price_date) - dates.index(signal_date)
        except ValueError:
            hold = 0  # price_date == signal_date(无后续交易日)
        return {
            "signal_date": signal_date,
            "index_id": index_id,
            "signal": signal,
            "buy_date": signal_date,
            "sell_date": "",
            "etf_code": etf_code,
            "etf_name": etf_name,
            "track_tier": track_tier,
            "track_score": track_score,
            "match_method": match_method,
            "track_low_confidence": track_low_confidence,
            "buy_price": round(buy_price, 6),
            "sell_price": 0,
            "shares": round(shares, 6),
            "profit": round(profit, 4),
            "return_pct": round(return_pct, 4),
            "hold_days": hold,
            "sell_reason": "持有中",
            "current_price": round(current_nav, 6),
            "market_state": market_state,
            "market_tier": market_tier,
            "market_tier_all": market_tier_all,
            "market_tier_cyb": market_tier_cyb,
            "rating": rating,
        }

    # 有匹配卖出信号日: 当日收盘卖出
    sell_nav = prices[sell_date]
    sell_price, _sell_amount, _comm2, _tf2, net, _st = _sell_with_fees(shares, sell_nav, etf_code, _KELLY_FEE_CONFIG)
    profit = net - BUY_AMOUNT
    return_pct = profit / BUY_AMOUNT * 100
    try:
        hold = dates.index(sell_date) - dates.index(signal_date)
    except ValueError:
        hold = 1
    return {
        "signal_date": signal_date,
        "index_id": index_id,
        "signal": signal,
        "buy_date": signal_date,
        "sell_date": sell_date,
        "etf_code": etf_code,
        "etf_name": etf_name,
        "track_tier": track_tier,
        "track_score": track_score,
        "match_method": match_method,
        "track_low_confidence": track_low_confidence,
        "buy_price": round(buy_price, 6),
        "sell_price": round(sell_price, 6),
        "shares": round(shares, 6),
        "profit": round(profit, 4),
        "return_pct": round(return_pct, 4),
        "hold_days": hold,
        "sell_reason": sell_reason,
        "current_price": 0,
        "market_state": market_state,
        "market_tier": market_tier,
        "market_tier_all": market_tier_all,
        "market_tier_cyb": market_tier_cyb,
        "rating": rating,
    }


def _compute_kelly(win_rate, pl_ratio):
    """凯利公式 f* = p - q/b, half_kelly = f*/2 * 100, tier 保守/均衡/激进。

    复用 public_fund.py 同口径: clamp f* [0,1], half_kelly [0,90]。
    """
    p = win_rate
    q = 1 - p
    b = pl_ratio if pl_ratio and pl_ratio > 0 else 0

    if b > 0:
        f_star = p - q / b
    else:
        f_star = 0.0
    f_star = max(0.0, min(1.0, f_star))

    half_kelly = f_star / 2 * 100
    half_kelly = max(0.0, min(90.0, half_kelly))

    if half_kelly < 30:
        tier = "保守"
    elif half_kelly < 60:
        tier = "均衡"
    else:
        tier = "激进"

    return round(f_star, 4), round(half_kelly, 2), tier


def _max_concurrent(trades):
    """最大同时持仓笔数: 按 buy_date/sell_date 区间重叠算(扫描线, 同日先买后卖=保守)。

    持仓中trade(sell_date 空)视为至今仍持有, 用远期哨兵日期 "99999999"。
    """
    if not trades:
        return 0
    _SENTINEL = "99999999"
    events = []
    for t in trades:
        events.append((t["buy_date"], 0))   # 0=buy, 先处理(保守, 同日买入算占用)
        events.append((t.get("sell_date") or _SENTINEL, 1))  # 1=sell, 后处理; 持仓中->远期
    events.sort()
    cur = max_conc = 0
    for _date, etype in events:
        if etype == 0:
            cur += 1
            if cur > max_conc:
                max_conc = cur
        else:
            cur -= 1
    return max_conc


def _years_from_trades(trades):
    """从交易 buy_date 跨度算年数(用于 all 周期年化)。"""
    if not trades:
        return 1.0
    dates = [t["buy_date"] for t in trades]
    d_min = datetime.strptime(min(dates), "%Y%m%d")
    d_max = datetime.strptime(max(dates), "%Y%m%d")
    days = (d_max - d_min).days
    return max(days / 365.25, 1.0 / 365.25)  # 至少1天


def _max_drawdown(trades):
    """最大累计收益回撤(按 sell_date 时序): 返回 (abs元, pct%)。

    pct = 回撤绝对值 / 总投入 × 100。
    """
    if not trades:
        return 0.0, 0.0
    # 持仓中trade(sell_date 空)排到时序末尾(预估盈亏在"现在"实现)
    sorted_t = sorted(trades, key=lambda t: t.get("sell_date") or "99999999")
    cumulative = 0.0
    peak = 0.0
    max_dd_abs = 0.0
    for t in sorted_t:
        cumulative += t["profit"]
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd_abs:
            max_dd_abs = dd
    total_invest = len(trades) * BUY_AMOUNT
    pct = (max_dd_abs / total_invest * 100) if total_invest > 0 else 0.0
    return round(max_dd_abs, 4), round(pct, 4)


def _annualized_return(return_pct_max_holding, period_key, trades):
    """年化收益率(%)。基于峰值资金收益率开方(D修正)。

    return_pct_max_holding = total_profit/峰值占用资金*100 (峰值资金收益率, 非平均化)。
    y1=return_pct_max_holding; y3=(1+r)^(1/3)-1; y5=(1+r)^(1/5)-1;
    y10=(1+r)^(1/10)-1; all=(1+r)^(1/years)-1。
    r=return_pct_max_holding/100。负收益 r<=-1 时返回0(无法开方)。
    """
    r = return_pct_max_holding / 100.0
    if r <= -1:
        return 0.0
    if period_key == "y1":
        return round(return_pct_max_holding, 4)
    elif period_key == "y3":
        return round(((1 + r) ** (1.0 / 3) - 1) * 100, 4)
    elif period_key == "y5":
        return round(((1 + r) ** (1.0 / 5) - 1) * 100, 4)
    elif period_key == "y10":
        return round(((1 + r) ** (1.0 / 10) - 1) * 100, 4)
    else:  # all
        years = _years_from_trades(trades)
        if years <= 0:
            return round(return_pct_max_holding, 4)
        return round(((1 + r) ** (1.0 / years) - 1) * 100, 4)


def _guidance(quad_key, mode_key):
    """跟单操作指引: 看到X信号 -> 信号日收盘买10000元Y类型ETF -> 按模式卖出。"""
    quad_label = QUADRANT_META[quad_key]["label"]
    mode_def = SELL_MODES[mode_key]
    if mode_def.get("signal"):
        # G/H/I: 信号驱动卖出, 完整文案从 SELL_MODES guidance_desc 读(与 desc 同源一处维护, 新加模式不漏)
        sell_str = mode_def.get("guidance_desc") or mode_def.get("desc") or "信号触发卖出"
        return f"看到{quad_label} → 信号日收盘买{BUY_AMOUNT}元匹配ETF → {sell_str}"
    hd = mode_def["hold_days"]
    if mode_def["stop_profit"] is None:
        sell_str = f"持有{hd}天到期卖出"
    else:
        pct = int(mode_def["stop_profit"] * 100)
        sell_str = f"持有至{pct}%止盈或{hd}天到期卖出"
    return f"看到{quad_label} → 信号日收盘买{BUY_AMOUNT}元匹配ETF → {sell_str}"


def _compute_stats(trades, period_key="all"):
    """聚合统计: 胜率/盈亏比/mean_return/凯利/连胜连败等。"""
    n = len(trades)
    if n == 0:
        return {
            "n": 0, "win_count": 0, "lose_count": 0,
            "win_rate": 0, "pl_ratio": None, "mean_return": 0,
            "total_return": 0, "avg_hold_days": 0,
            "kelly_f": 0, "half_kelly": 0, "kelly_tier": "保守",
            "max_single_win": 0, "max_single_loss": 0,
            "win_streak_max": 0, "lose_streak_max": 0,
            "total_invest": 0, "total_profit": 0, "total_return_pct": 0,
            "max_concurrent": 0, "max_concurrent_capital": 0,
            "return_pct_max_holding": 0,
            "annualized_return": 0, "sharpe": 0,
            "max_drawdown": 0, "max_drawdown_pct": 0, "calmar": 0,
            "holding_count": 0, "holding_capital": 0,
        }

    wins = [t for t in trades if t["profit"] > 0]
    losses = [t for t in trades if t["profit"] <= 0]
    win_count = len(wins)
    lose_count = len(losses)
    win_rate = win_count / n

    avg_win = sum(t["return_pct"] for t in wins) / win_count if win_count else 0.0
    avg_loss_abs = abs(sum(t["return_pct"] for t in losses) / lose_count) if lose_count else 0.0

    # 盈亏比(同 public_fund.py 边界处理)
    if lose_count > 0 and avg_loss_abs > 0:
        pl_ratio = avg_win / avg_loss_abs
    elif win_count > 0 and lose_count == 0:
        pl_ratio = 999.0  # 全胜无亏损
    else:
        pl_ratio = None  # 无胜或全零

    mean_return = sum(t["return_pct"] for t in trades) / n
    total_return = sum(t["profit"] for t in trades) / BUY_AMOUNT * 100
    avg_hold = sum(t["hold_days"] for t in trades) / n

    kelly_f, half_kelly, kelly_tier = _compute_kelly(win_rate, pl_ratio)

    # 最大单笔盈亏
    max_win = max((t["return_pct"] for t in trades), default=0)
    max_loss = min((t["return_pct"] for t in trades), default=0)

    # 连胜连败(按买入日排序)
    sorted_trades = sorted(trades, key=lambda t: t["buy_date"])
    win_streak = lose_streak = 0
    max_win_streak = max_lose_streak = 0
    for t in sorted_trades:
        if t["profit"] > 0:
            win_streak += 1
            lose_streak = 0
            max_win_streak = max(max_win_streak, win_streak)
        else:
            lose_streak += 1
            win_streak = 0
            max_lose_streak = max(max_lose_streak, lose_streak)

    # 金额 + 总收益(口径修正)
    total_invest = n * BUY_AMOUNT
    total_profit = round(sum(t["profit"] for t in trades), 4)
    total_return_pct = round(total_profit / total_invest * 100, 4) if total_invest > 0 else 0
    # 最大同时持仓资金占用
    max_conc = _max_concurrent(trades)
    max_concurrent_capital = max_conc * BUY_AMOUNT
    # 最大持仓收益率 = 最终盈亏 / 峰值占用资金
    return_pct_max_holding = round(total_profit / max_concurrent_capital * 100, 4) if max_concurrent_capital > 0 else 0
    # 年化收益(D修正: 基于峰值资金收益率 return_pct_max_holding 开方, 非平均化 total_return_pct)
    annualized = _annualized_return(return_pct_max_holding, period_key, trades)
    # 夏普比率(无风险利率0, per-trade)
    returns = [t["return_pct"] for t in trades]
    if n > 1:
        _mean = sum(returns) / n
        _var = sum((x - _mean) ** 2 for x in returns) / (n - 1)
        _std = _var ** 0.5
        sharpe = round(_mean / _std, 4) if _std > 0 else 0
    else:
        sharpe = 0
    # 最大回撤
    max_dd_abs, max_dd_pct = _max_drawdown(trades)
    # 卡尔玛比率
    calmar = round(annualized / max_dd_pct, 4) if max_dd_pct > 0 else 0
    # 持仓中trade计数(预估盈亏已计入上面 total_profit/胜率/凯利等, 不隔离; 此处仅计数+标注)
    holding_count = sum(1 for t in trades if not t.get("sell_date"))
    holding_capital = holding_count * BUY_AMOUNT

    return {
        "n": n,
        "win_count": win_count,
        "lose_count": lose_count,
        "win_rate": round(win_rate, 4),
        "pl_ratio": round(pl_ratio, 2) if pl_ratio is not None else None,
        "mean_return": round(mean_return, 4),
        "total_return": round(total_return, 4),
        "avg_hold_days": round(avg_hold, 2),
        "kelly_f": kelly_f,
        "half_kelly": half_kelly,
        "kelly_tier": kelly_tier,
        "max_single_win": round(max_win, 4),
        "max_single_loss": round(max_loss, 4),
        "win_streak_max": max_win_streak,
        "lose_streak_max": max_lose_streak,
        "total_invest": total_invest,
        "total_profit": total_profit,
        "total_return_pct": total_return_pct,
        "max_concurrent": max_conc,
        "max_concurrent_capital": max_concurrent_capital,
        "return_pct_max_holding": return_pct_max_holding,
        "annualized_return": annualized,
        "sharpe": sharpe,
        "max_drawdown": max_dd_abs,
        "max_drawdown_pct": max_dd_pct,
        "calmar": calmar,
        "holding_count": holding_count,
        "holding_capital": holding_capital,
    }


# ── 主流程 ────────────────────────────────────────────────────────────────────

def compute():
    """执行完整回测, 返回结果 dict。"""
    from datetime import timedelta
    today = datetime.now()
    PERIODS["y1"]["cutoff"] = (today - timedelta(days=365)).strftime("%Y%m%d")
    PERIODS["y3"]["cutoff"] = (today - timedelta(days=365 * 3)).strftime("%Y%m%d")
    PERIODS["y5"]["cutoff"] = (today - timedelta(days=365 * 5)).strftime("%Y%m%d")
    PERIODS["y10"]["cutoff"] = (today - timedelta(days=365 * 10)).strftime("%Y%m%d")

    # 1. 加载数据
    print("-> 加载 signal_stats.json ...", flush=True)
    signal_stats = _load_signal_stats()
    print(f"   {len(signal_stats)} 个 index_id (含 _updated_at)")

    print("-> 加载 board_etf_map.json ...", flush=True)
    etf_map = _load_board_etf_map()
    best_etf = _build_best_etf(etf_map)
    print(f"   {len(best_etf)} 个指数有 track_score 第一名 ETF")

    # 换标漂移修复: 加载已固化的每信号事件 ETF 选择。board_etf_map 的 best 变更只影响新信号事件,
    # 已固化历史成交保持不变。
    print("-> 加载已固化 ETF 选择 (signal_kelly_etf_freeze.json) ...", flush=True)
    etf_freeze = _load_etf_freeze()
    frozen_prev_count = len(etf_freeze)
    print(f"   {frozen_prev_count} 个信号事件已固化 ETF")

    print("-> 加载 indicators.yaml 市场分类 ...", flush=True)
    market_map = _load_market_map()
    print(f"   {len(market_map)} 个指数有 market 分类")

    # 2. 读买信号
    print("-> 读 signal_daily 买信号 ...", flush=True)
    conn = get_conn()
    buy_rows = conn.execute(
        f"SELECT date, index_id, signal FROM signal_daily "
        f"WHERE signal IN ({','.join('?' * len(BUY_SIGNALS))}) ORDER BY date",
        BUY_SIGNALS,
    ).fetchall()
    # 读卖出信号(sell/sell_stop_loss)时间线, 供 G/H/I 信号驱动卖出模式按指数查后续信号
    sell_rows = conn.execute(
        "SELECT date, index_id, signal FROM signal_daily "
        "WHERE signal IN ('sell','sell_stop_loss') ORDER BY index_id, date"
    ).fetchall()
    sell_timeline = {}
    for _d, _iid, _sig in sell_rows:
        sell_timeline.setdefault(_iid, []).append((_d, _sig))
    # 加载沪深300 MA60 大盘择时状态(降亏toggle后端注入)
    print("-> 加载 hs300 MA60 大盘择时状态 ...", flush=True)
    market_state, market_dates = _load_market_state(conn)
    print(f"   {len(market_state)} 个交易日有 MA60 状态")
    # 加载沪深300 四档大盘状态(v1.1.2 三键, 注入 market_tier 供前端判定)
    print("-> 加载 hs300 四档大盘状态(v1.1.2)...", flush=True)
    market_tiers = _load_market_tiers(conn)
    print(f"   {len(market_tiers)} 个交易日有四档状态")
    # 加载创业板指(cyb)四档大盘状态(#69 新键 excludeSpecialBearCyb, 注入 market_tier_cyb 供前端判定)
    print("-> 加载 cyb 四档大盘状态(#69)...", flush=True)
    cyb_tiers = _load_market_tiers(conn, index_id='cyb')
    print(f"   {len(cyb_tiers)} 个交易日有 cyb 四档状态")
    conn.close()
    print(f"   {len(buy_rows)} 条买信号")

    # 3. 确定需要的 ETF 代码集合, 批量加载价格。注意: 用 _resolve_etf 而非直接 best_etf.get,
    #    这样已固化的历史信号事件用冻结 ETF, 新信号事件就地冻结当前 best。
    needed_etfs = set()
    for _date, iid, _sig in buy_rows:
        be, _frozen = _resolve_etf(_date, iid, _sig, best_etf, etf_freeze)
        if be:
            needed_etfs.add(be["code"])
    print(f"-> 批量加载 {len(needed_etfs)} 只 ETF 的 accum_nav/open/close ...", flush=True)
    price_map, open_map, close_map, sorted_dates_map = _batch_load_etf_prices(needed_etfs)
    total_price_rows = sum(len(v) for v in price_map.values())
    print(f"   {total_price_rows} 行价格数据")

    # 全局最新数据日(所有ETF最后日期的最大值), 用于持仓中trade预估当前价
    today_str = max((ds[-1] for ds in sorted_dates_map.values() if ds), default=None)
    if today_str:
        print(f"   全局最新数据日 today={today_str}")

    # 4. 逐信号分类 + 6 模式回测
    # quadrants[quad_key][mode_key] = [trade, ...]
    quadrants = {qk: {mk: [] for mk in SELL_MODES} for qk in QUADRANT_META}
    skipped_no_etf = skipped_no_score = skipped_no_price = 0
    classified = 0
    frozen_used = 0  # 使用已固化 ETF 的信号事件数(历史成交固化, 不随当前 best 变更)

    # ETF track_tier -> 象限后缀映射(none+null -> has_track, 2026-08-24 与首页筛选档4口径统一;
    # tier 仅五态(strong/related/approx/none/None)无脏值, None 键=track_score<30 或 N<30 无分)
    etf_quad_map = {"strong": "strong", "related": "related", "approx": "approx", "none": "has_track",
                    None: "has_track"}

    for date, iid, sig in buy_rows:
        if KELLY_ASOF and date > KELLY_ASOF:
            continue  # 仅验证用: 数据截止复现报告数字
        be, be_frozen = _resolve_etf(date, iid, sig, best_etf, etf_freeze)
        if not be:
            skipped_no_etf += 1
            continue
        if be_frozen:
            frozen_used += 1

        etf_code = be["code"]
        tier = be["track_tier"]

        # 信号评级(按 signal_stats 10d score)
        stats_entry = signal_stats.get(iid, {}).get(sig, {})
        score_10d = stats_entry.get("10d", {}).get("score") if isinstance(stats_entry, dict) else None
        if score_10d is None:
            skipped_no_score += 1
            continue  # 无评级, 跳过(不纳入任何象限)

        if score_10d >= RATING_HIGH:
            rating = "high"
        elif score_10d >= RATING_MID:
            rating = "mid"
        else:
            rating = "low"

        # ETF 归类(strong/related/approx/has_track; none+null 同归 has_track, 2026-08-24 口径统一)
        etf_quad = etf_quad_map.get(tier)

        # 大盘择时 market_state: A股类(a/concept/industry)按hs300 MA60实际状态, 非A股类标True不过滤
        market = market_map.get(iid)
        if market in A_STOCK_MARKETS:
            ms = _is_market_bull(date, market_state, market_dates)
        else:
            ms = True
        # 四档 market_tier(v1.1.2 三键): hs300 四档判定。
        #   market_tier = A股类(a/concept/industry)四档, 非A股类为 ""(主键 excludeSpecialBear 仅A股类, 与 market_state 同守卫);
        #   market_tier_all = 全市场四档(备选键 declinePhaseSpecial 下降期×buy_special 全市场用)。
        #   market_tier_cyb(#69): A股类信号注入 cyb(创业板指)四档, 非A股类为 ""(新键 excludeSpecialBearCyb 用, 与 market_tier 同构守卫)。
        mt_all = _market_tier_at(date, market_tiers, market_dates)
        mt = mt_all if market in A_STOCK_MARKETS else ""
        mt_cyb = _market_tier_at(date, cyb_tiers, market_dates)
        mt_cyb = mt_cyb if market in A_STOCK_MARKETS else ""

        # 9 模式回测(A-F 固定规则 + G/H/I 信号驱动)
        prices = price_map.get(etf_code, {})
        sdates = sorted_dates_map.get(etf_code, [])
        sell_signals = sell_timeline.get(iid, [])  # 该指数卖出信号时间线(G/H/I 用)
        any_valid = False
        for mode_key, mode_def in SELL_MODES.items():
            result = _backtest_one(date, prices, sdates, etf_code, be["name"], mode_def["stop_profit"],
                                   iid, sig, be.get("track_tier"), be.get("track_score"),
                                   be.get("match_method"), be.get("track_low_confidence"),
                                   today=today_str, hold_days=mode_def["hold_days"], market_state=ms, rating=rating,
                                   sell_mode=mode_key, sell_signals=sell_signals, market_tier=mt, market_tier_all=mt_all,
                                   market_tier_cyb=mt_cyb, open_map=open_map, close_map=close_map)
            if result is None:
                continue  # 数据不足(信号日无价格/未来不足 hold_days 天)
            any_valid = True
            # 归入评级象限
            quadrants[f"rating_{rating}"][mode_key].append(result)
            # 归入 ETF 归类象限(如有)
            if etf_quad:
                quadrants[f"etf_{etf_quad}"][mode_key].append(result)
            # 归入信号类型象限(按 signal 字段, 互斥覆盖全体)
            sig_quad = SIG_QUAD_MAP.get(sig)
            if sig_quad:
                quadrants[sig_quad][mode_key].append(result)
            # 归入指数大类象限(按 indicators.yaml market 字段, market 已在循环外算)
            mkt_quad = MARKET_QUAD_MAP.get(market)
            if mkt_quad:
                quadrants[mkt_quad][mode_key].append(result)

        if any_valid:
            classified += 1
        else:
            skipped_no_price += 1

    print(f"   分类完成: {classified} 信号有有效回测")
    print(f"   跳过: 无ETF映射={skipped_no_etf}, 无评级score={skipped_no_score}, 无ETF价格/未来不足={skipped_no_price}")
    print(f"   换标漂移修复: 使用已固化ETF的信号事件={frozen_used}, 本次新固化={len(etf_freeze) - frozen_prev_count}")
    print(f"   宇宙感知剪枝(v1.1.7): 排除类别信号事件跳过(调用级)={_PRUNED_UNIVERSE_N} "
          f"(冻结穿透路径一并剪除, freeze 文件本体不动)")

    # 换标漂移修复: 持久化冻结查找表(含本轮新固化), 供下次回测保持历史成交固化。
    try:
        _save_etf_freeze(etf_freeze)
        print(f"   ✓ 已固化 {len(etf_freeze)} 个信号事件 -> {_etf_freeze_path()}")
    except OSError as e:
        print(f"   ⚠ 冻结表写盘失败(不影响本次回测结果): {e}", file=sys.stderr)

    # 5. 按周期聚合统计
    output = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "config": {
            "buy_amount": BUY_AMOUNT,
            "hold_days": HOLD_DAYS,
            "sell_modes": SELL_MODES,
            "periods": {k: v["label"] for k, v in PERIODS.items()},
            "period_cutoffs": {k: v["cutoff"] for k, v in PERIODS.items()},
            "rating_thresholds": {"high": RATING_HIGH, "mid": RATING_MID},
            "etf_tiers": ["strong", "related", "approx", "none"],
            "commission_rate": COMMISSION_RATE,
            "slippage": SLIPPAGE,
            "min_commission": MIN_COMMISSION,
            "transfer_fee_rate_sh": TRANSFER_FEE_RATE_SH,
            "buy_signals": list(BUY_SIGNALS),
            "signal_type_quads": SIG_QUAD_MAP,
            "market_quads": MARKET_QUAD_MAP,
            "buy_price_basis": "next_day_open" if KELLY_BUY_NEXTDAY else "signal_day_close",
        },
        "quadrants": {},
    }

    # trades 列文件(列式存储, 每 quadrant x mode 存 all 周期全量, 前端按 cutoff 过滤 y1/y3)
    TRADE_FIELDS = ["signal_date", "index_id", "signal", "buy_date", "sell_date", "etf_code", "etf_name",
                    "track_tier", "track_score", "match_method", "track_low_confidence",
                    "buy_price", "sell_price", "shares", "profit", "return_pct",
                    "hold_days", "sell_reason", "current_price", "market_state", "market_tier", "market_tier_all", "market_tier_cyb", "rating"]
    trades_output = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "buy_amount": BUY_AMOUNT,
        "period_cutoffs": {k: v["cutoff"] for k, v in PERIODS.items()},
        "fields": TRADE_FIELDS,
        "quadrants": {},
    }

    for quad_key, quad_meta in QUADRANT_META.items():
        quad_data = {"label": quad_meta["label"], "desc": quad_meta["desc"], "periods": {}, "guidance": {}}
        for mode_key in SELL_MODES:
            quad_data["guidance"][mode_key] = _guidance(quad_key, mode_key)
        for period_key, period_def in PERIODS.items():
            cutoff = period_def["cutoff"]
            period_data = {}
            for mode_key in SELL_MODES:
                all_trades = quadrants[quad_key][mode_key]
                # 按周期过滤(信号买入日期 >= cutoff)
                if cutoff and cutoff != "0":
                    period_trades = [t for t in all_trades if t["buy_date"] >= cutoff]
                else:
                    period_trades = list(all_trades)
                period_data[mode_key] = _compute_stats(period_trades, period_key)
            quad_data["periods"][period_key] = period_data
        output["quadrants"][quad_key] = quad_data
        # trades 文件: 每 quadrant x mode 存 all 周期全量(列式)
        trades_output["quadrants"][quad_key] = {}
        for mode_key in SELL_MODES:
            trades_output["quadrants"][quad_key][mode_key] = [
                [t.get(f, "") for f in TRADE_FIELDS]
                for t in quadrants[quad_key][mode_key]
            ]

    # 6. 汇总打印
    print("\n=== 回测结果汇总 ===")
    for quad_key in QUADRANT_META:
        for period_key in PERIODS:
            n_a = output["quadrants"][quad_key]["periods"][period_key]["A"]["n"]
            n_b = output["quadrants"][quad_key]["periods"][period_key]["B"]["n"]
            if n_a > 0:
                hk = output["quadrants"][quad_key]["periods"][period_key]["A"]["half_kelly"]
                wr = output["quadrants"][quad_key]["periods"][period_key]["A"]["win_rate"]
                print(f"  {quad_key:14s} {period_key:3s}  A: n={n_a:5d} win_rate={wr:.3f} half_kelly={hk:.1f}%  B: n={n_b:5d}")

    return output, trades_output


def _export_trades_parts(trades_data, trades_path):
    """追加分片导出(2026-08-22 首页模拟回测弹窗提速): 同目录 signal_kelly_trades_parts/ 下
    - recent.json: signal_date 最近 N 天热区片(N 自适应从 [120,90,60] 选第一个序列化 <=3MB 的窗口;
      首页弹窗打开只拉这一片秒开)
    - t{YYYY}.json: 按 signal_date 年份切片(空年份不出文件; 弹窗超出热区时按年并行拉)

    每片结构与全量完全一致 {generated_at,buy_amount,period_cutoffs,fields,quadrants},
    quadrants[qk][mk] 只含属于该片/该窗口的行(空 qk 整键省略)。前端两策略互斥取用
    (热区内只用 recent / 超出只用年片), 拼接不会重复计数。
    全量 signal_kelly_trades.json 本体不动(lab.js 凯利区依赖 + §23.7 冻结契约),
    本函数只在 main() 末尾追加调用。分片不生成 .gz(前端 fetchJSON 全走 .json, CF 自动 br)。
    """
    from datetime import datetime as _dt, timedelta as _td

    parts_dir = os.path.join(os.path.dirname(trades_path), "signal_kelly_trades_parts")
    fields = trades_data["fields"]
    sig_i = fields.index("signal_date")

    def _dump(name, rows_by_qm):
        shard = {
            "generated_at": trades_data["generated_at"],
            "buy_amount": trades_data["buy_amount"],
            "period_cutoffs": trades_data["period_cutoffs"],
            "fields": fields,
            "quadrants": {},
        }
        n = 0
        for qk, mk_map in rows_by_qm.items():
            if not mk_map:
                continue
            shard["quadrants"][qk] = {}
            for mk, rows in mk_map.items():
                if rows:
                    shard["quadrants"][qk][mk] = rows
                    n += len(rows)
        payload = json.dumps(shard, ensure_ascii=False, separators=(",", ":"))
        with open(os.path.join(parts_dir, name), "w", encoding="utf-8") as f:
            f.write(payload)
        return len(payload), n

    # 全量行按 (qk, mk) 分组引用(不拷贝行内容, 切片只筛引用)
    grouped = {}
    all_rows = []
    for qk, mk_map in trades_data.get("quadrants", {}).items():
        for mk, arr in mk_map.items():
            grouped[(qk, mk)] = arr
            all_rows.extend(arr)
    if not all_rows:
        print("⚠ 分片导出跳过: 无交易记录")
        return

    max_date = max(r[sig_i] for r in all_rows)
    max_d = _dt.strptime(max_date, "%Y%m%d")

    os.makedirs(parts_dir, exist_ok=True)

    def _rows_in_window(cut):
        rows_by_qm = {}
        cnt = 0
        for (qk, mk), arr in grouped.items():
            sel = [r for r in arr if r[sig_i] >= cut]
            if sel:
                rows_by_qm.setdefault(qk, {})[mk] = sel
                cnt += len(sel)
        return rows_by_qm, cnt

    # recent 热区片: 窗口自适应(目标<=2MB, 硬上限3MB; 2026-08-21 实测 120天≈4.6MB/90天≈3.4MB,
    # 故从大到小选第一个 <=3MB 的窗口, 保证弹窗首开秒开)
    recent_done = False
    for win in (120, 90, 60):
        cut = (max_d - _td(days=win)).strftime("%Y%m%d")
        rows_by_qm, cnt = _rows_in_window(cut)
        size, _n = _dump("_probe.json", rows_by_qm)
        probe = os.path.join(parts_dir, "_probe.json")
        if size <= 3 * 1024 * 1024:
            os.replace(probe, os.path.join(parts_dir, "recent.json"))
            print(f"✓ 分片 recent.json ({win}天窗口, {cnt} 行, {size / 1024:.1f} KB)")
            recent_done = True
            break
        os.remove(probe)
    if not recent_done:
        # 兜底: 全超限也落 60 天最小片(前端另有全量兜底链路)
        cut = (max_d - _td(days=60)).strftime("%Y%m%d")
        rows_by_qm, cnt = _rows_in_window(cut)
        size, _n = _dump("recent.json", rows_by_qm)
        print(f"✓ 分片 recent.json (60天兜底, {cnt} 行, {size / 1024:.1f} KB)")

    # 年份切片(空年份不出文件; 用 id(row) 集合按年筛引用)
    by_year = {}
    for r in all_rows:
        by_year.setdefault(r[sig_i][:4], set()).add(id(r))
    total_size = 0
    for y in sorted(by_year):
        ids = by_year[y]
        rows_by_qm = {}
        cnt = 0
        for (qk, mk), arr in grouped.items():
            sel = [r for r in arr if id(r) in ids]
            if sel:
                rows_by_qm.setdefault(qk, {})[mk] = sel
                cnt += len(sel)
        size, _n = _dump(f"t{y}.json", rows_by_qm)
        total_size += size
        print(f"✓ 分片 t{y}.json ({cnt} 行, {size / 1024:.1f} KB)")
    print(f"✓ 分片导出完成: {parts_dir} ({len(by_year)} 个年片 + recent)")


def main():
    parser = argparse.ArgumentParser(description="信号凯利回测")
    parser.add_argument("--output", default=None, help="输出 JSON 路径(默认 static-site/data/signal_kelly_backtest.json)")
    parser.add_argument("--trades-output", default=None, help="交易记录 JSON 路径(默认 static-site/data/signal_kelly_trades.json)")
    parser.add_argument("--skip-parts", action="store_true", help="跳过分片导出(signal_kelly_trades_parts/, 默认生成)")
    args = parser.parse_args()

    output_path = args.output or os.path.join(ROOT, "static-site", "data", "signal_kelly_backtest.json")
    trades_path = args.trades_output or os.path.join(os.path.dirname(output_path), "signal_kelly_trades.json")

    print("=" * 60)
    print("信号凯利回测: 16象限 × 9模式 × 5周期")
    print(f"ROOT = {ROOT}")
    print(f"输出 = {output_path}")
    print(f"交易记录 = {trades_path}")
    print("=" * 60)

    data, trades_data = compute()

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    size = os.path.getsize(output_path)
    print(f"\n✓ 输出: {output_path} ({size} bytes = {size / 1024:.1f} KB)")

    # 交易记录文件(列式存储, all 周期全量)
    with open(trades_path, "w", encoding="utf-8") as f:
        json.dump(trades_data, f, ensure_ascii=False, separators=(",", ":"))
    t_size = os.path.getsize(trades_path)
    total_trades = sum(len(v) for q in trades_data.get("quadrants", {}).values() for v in q.values())
    print(f"✓ 交易记录: {trades_path} ({t_size} bytes = {t_size / 1024:.1f} KB, {total_trades} 笔)")

    # 分片导出(首页模拟回测弹窗提速, 2026-08-22 追加; --skip-parts 可跳过; 失败不影响全量文件)
    if not args.skip_parts:
        try:
            _export_trades_parts(trades_data, trades_path)
        except Exception as e:  # noqa: BLE001
            print(f"⚠ 分片导出失败(不影响全量文件): {type(e).__name__}: {e}", file=sys.stderr)

    # 生成 .gz
    import gzip
    for p in [output_path, trades_path]:
        gz_path = p + ".gz"
        with open(p, "rb") as src, gzip.open(gz_path, "wb") as dst:
            dst.write(src.read())
        print(f"✓ gzip: {gz_path} ({os.path.getsize(gz_path)} bytes)")


if __name__ == "__main__":
    main()
