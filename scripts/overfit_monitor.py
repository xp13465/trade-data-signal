#!/usr/bin/env python3
"""过拟合监控系统 - 每日多维打点 + 4 维过拟合指标 + 综合风险分 + 预警通知。

目的
----
用户按 AFG 交易模式实操, 实操数据是硬检验。本脚本每日打点「准确率(回测口径 + 实盘口径)」历史序列,
自研 4 维度过拟合指标(回测-实盘偏离 / 滚动样本外 / 参数稳定 / 象限退化), 合成 0-100 综合风险分,
命中预警规则时通过 notify.py 发邮件 + Telegram + 飞书。

方法口径(与现有 v1.0.0 展示口径对齐)
------------------------------------
- 回测口径准确率: signal_kelly_trades.json 每笔交易按 signal_date 分组, return_pct>0 = 对(按模式卖出到期收益方向)。
- 实盘口径准确率: signal_daily 每信号日 -> signal_daily 日收盘对应的 index_daily 收盘, 看多(buy/buy_aux/buy_special/buy_backup)
  信号日收盘->最新收盘上涨 = 对; band_hold 中性不计。
  2026-08-17 用户拍板方案A「实盘限定回测宇宙」: 实盘线只统计回测宇宙内信号(信号类型 ∈ 买入白名单
  buy/buy_aux/buy_special/buy_backup + board_etf_map 有非空 track_score 即 _bt_in_universe=True, 与 §23.6
  universe_rules.yaml 单一事实源对齐), 卖/止损卖/情绪类/全球商品利率/港股行业/未入样 buy 类等回测不测的信号
  全部剔除, 使实盘线与回测线比同一批买入信号(此前把卖类/情绪类 ~22% 命中率信号混入实盘总样本, 造成口径错位)。
- 4 维过拟合风险分(0-100): risk_score = 0.40*D1(回测-实盘偏离) + 0.25*D2(滚动样本外衰减) + 0.20*D3(参数稳定) + 0.15*D4(象限退化)。
  等级: 绿 <30(正常) / 黄 30-60(关注) / 红 >60(高风险)。
- 各维度按滚动窗口 w30/w60/w90 加权偏重最新(30 灵敏 / 90 稳健)。
- 样本数下限(2026-08-17 用户拍板「样本数不要做限制」): 完全去掉样本充足阈值判定, 各统计口径(10/15/30/60/100)
  有多少样本画多少, 早期窗口不满 / 稀疏维度的档位照常算 win_rate(n 值照常输出, 前端看 n 判断可信度)。
  落地于 rolling_win_rates, 前端 _overfitSampleInsufficient 同步删除。

输入依赖
--------
- DB: ${REPO}/data/sentiment.db(signal_daily 信号权威历史 / index_daily 指数收盘价)
- JSON: static-site/data/signal_kelly_trades.json(回测成交明细, 2011-2026, 16 象限 x 10 模式)
- YAML: config/indicators.yaml(index_id -> market 大类映射, 与 signal_kelly_backtest.py 同源)
- 运行时必须在 trade-data/ 下跑(REPO=trade-data 主库, cwd 语义同 signal_kelly_backtest.py)

输出
----
${REPO}/static-site/data/overfit_monitor.json(随 export/deploy 三步同步 R2 + 备站, 见 doc §4.1)

关键参数种子
-----------
DEFAULT_K=1 / AFG_MODES=["A","F","G"] / OVERFIT_MODE="G"(默认预警/主展示口径)
WINDOWS=[30,60,90] / D1 权重=0.40 / D2=0.25 / D3=0.20 / D4=0.15
偏离阈值: >+10% 低 / 0~10% 正常 / -10%~0 关注 / <-10% 高风险
OOS 阈值: 衰减 >20% 高 / 10-20% 关注 / <10% 正常
参数敏感: 微扰收益变化 >30% 或符号翻转 -> 尖峰; 10-30% 关注; <10% 稳定
象限退化: 连续 N 日实盘胜率 < 回测预期-10pp 或跌破 50%

复现命令
--------
cd /Users/linhuichen/code/trade-data
.venv/bin/python scripts/overfit_monitor.py            # 每日增量打点(21:40 launchd)
.venv/bin/python scripts/overfit_monitor.py --rebuild  # 全量历史回算(一次性, 建曲线)
.venv/bin/python scripts/overfit_monitor.py --dry-run  # 不打点只评估预警 + 试发(测试)

数据截止: signal_daily MAX(date)=20260814; trades 2011-01-19 -> 2026-08-13
"""
import argparse
import bisect
import json
import math
import os
import sqlite3
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, date as date_cls, timedelta

import yaml

# ── 路径 ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))   # trade-data/scripts/
sys.path.insert(0, SCRIPT_DIR)
# 统一部署源树/上传 helper(防再犯机制 E, 2026-08-18): REPO = 部署源树(trade-data),
# guard_deploy_source_tree 防误写 git 仓(trade); R2 上传 env 用 force_env 强制覆盖。
from pick_repo import pick_repo, pick_git_repo, force_env, guard_deploy_source_tree  # noqa: E402
REPO = str(guard_deploy_source_tree(pick_repo()))         # trade-data/(部署源树)

# ── 常量 ──────────────────────────────────────────────────────────────────────
BUY_SIGNALS = ("buy", "buy_aux", "buy_special", "buy_backup")
SELL_SIGNALS = ("sell", "sell_stop_loss")
_BUY_SIG_SET = set(BUY_SIGNALS)
# top-K 排序常量(与首页 _posCapSortedFn / lab 同源, §23.6): rating 高>中>低>空; signal 备买>主买>辅买>追买
_TOPK_RC = {"high": 0, "mid": 1, "low": 2, "": 3}
_TOPK_SC = {"buy_backup": 0, "buy": 1, "buy_aux": 2, "buy_special": 3}
AFG_MODES = ["A", "F", "G"]
# 统计口径可选项(交易日): 10/15/30/60/100, 默认 60(2026-08-16 用户定: 显示可选口径, 两图随口径重算)
WINDOWS = [10, 15, 30, 60, 100]
DEFAULT_K = 1
OVERFIT_MODE = "G"        # 主展示/预警口径的卖出模式(用户主推 G = 信号驱动卖出)
SURFACE_DAYS = 200        # 曲线序列裁剪窗口(2026-08-16: 前端显示范围上限 180, 序列只需 ~200 天即够画; 体积控制)
# 4 维权重
W_D1, W_D2, W_D3, W_D4 = 0.40, 0.25, 0.20, 0.15

OUT_JSON = os.path.join(REPO, "static-site", "data", "overfit_monitor.json")
# B拆分(2026-08-24 提速组合A+B+C+D): K档扩展 bank(by_k/filtered_by_k)单独落 ext 文件。
# 主文件只留默认首屏渲染所需(accuracy/overfit 核心曲线 + filtered 默认bank + recent 组集明细),
# by_k/filtered_by_k 占原文件 77% 体积(compact 口径 2.5MB/9.7MB)且仅「K档×{p8对照/组集失败/降亏关}」
# 组合消费(app.js _ovBank), 前端按需拉取(_fetchOverfitExt 单例 promise)。拆分前后数值逐位一致由
# scripts/check_overfit_split_parity.py 断言(§23.5 报告可复现)。
OUT_EXT_JSON = os.path.join(REPO, "static-site", "data", "overfit_monitor_ext.json")

# market -> 大类象限(与 signal_kelly_backtest.py 同源)
MARKET_QUAD_MAP = {
    "a": "mkt_a", "hk": "mkt_hk", "hk_industry": "mkt_hk",
    "global": "mkt_global", "industry": "mkt_industry", "concept": "mkt_concept",
}


# ── DB 连接 ──────────────────────────────────────────────────────────────────
def find_db():
    """sentiment.db 权威主库。cwd 必须在 trade-data/ 才读最新(trade/ 读滞后镜像)。"""
    candidates = [
        os.path.join(REPO, "data", "sentiment.db"),
        os.path.join(REPO, "data", "signal.db"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    raise FileNotFoundError("sentiment.db 未找到 (trade-data/data/)")


# ── 数据加载 ──────────────────────────────────────────────────────────────────
def load_market_map():
    """config/indicators.yaml -> {index_id: market}。"""
    p = os.path.join(REPO, "config", "indicators.yaml")
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return {
        it.get("id"): it.get("market")
        for it in (cfg or {}).get("indices", []) if it.get("id") and it.get("market")
    }


# ── AI 宏降亏删线层判定(v1.1.0, 监控卡自动联动) ─────────────────────────────────
# 与 app/queries.py _ai_macro_hit_filters(L606-678, 8 键成员级) + _bt_in_universe(§23.6)
# 同源(v1.1.0 基准)。监控卡「AI降亏过滤」开关开启时，打点侧过滤掉被删线命中的信号，
# 让监控数据同步反映过滤后的实际(§23.3/§22 举一反三: 首页/凯利区已各自实现了该过滤层)。
# 判定为纯函数(无 DB 依赖, 便于单测)。返回 True = 该信号**被过滤**(命中 8 键 或 未入样本)。

def _ai_weekday(date_str):
    """信号日星期 0=Mon..6=Sun(与 queries._ai_macro_weekday 同款)；失败返 -1。"""
    if not date_str or len(date_str) < 8:
        return -1
    try:
        return datetime(int(date_str[0:4]), int(date_str[4:6]), int(date_str[6:8])).weekday()
    except ValueError:
        return -1


def _ai_quarter(mm):
    """信号月 -> 季度(ceil(mm/3))。"""
    if not mm or not mm.isdigit():
        return 0
    return (int(mm) + 2) // 3


# AI 宏 8 键成员(与 queries._AI_MACRO_BUY_SIGNALS 同源; 非买不判降亏, §23.6 MED3)
_AI_MACRO_BUY_SIGNALS = ("buy", "buy_aux", "buy_special", "buy_special_filtered", "buy_backup")
# 仅 A 股类(大盘择时只对 A 股类, 与 queries._AI_MACRO_A_STOCK_MARKETS 同源)
_AI_MACRO_A_STOCK_MARKETS = {"mkt_a", "mkt_concept", "mkt_industry"}


def ai_macro_hit_keys(date_str, signal, mkt, rating, ts):
    """返回命中 AI 宏 8 键中的 7 键(降亏条件名列表, 不含 excludeSpecialBear, 由 signal_ai_filtered 补)。
    入参: mkt=mkt_a/mkt_hk/..., rating=high/mid/low/''，ts=track_score|None。
    与 queries._ai_macro_hit_filters 同源(v1.1.0)。
    """
    _f = []
    _mm = date_str[4:6] if len(date_str) >= 8 else ""
    try:
        _dd = int(date_str[6:8])
    except (ValueError, IndexError):
        _dd = 0
    _wd = _ai_weekday(date_str) if date_str else -1
    _q = _ai_quarter(_mm)
    _sig = signal or ""
    if _sig not in _AI_MACRO_BUY_SIGNALS:
        return _f
    # 1 n2
    if _sig == "buy_special" and _mm == "11" and mkt == "mkt_industry":
        _f.append("n2NovSpecialIndustry")
    # 2 excludeSpecialBear (is_bull 在调用处算好, 传入 ts... 需再传 bull)
    # 2b k2c5HkChase
    if _sig in ("buy_special", "buy_backup") and mkt == "mkt_hk":
        _f.append("k2c5HkChase")
    # 3 janMidRating
    if _mm == "01" and 11 <= _dd <= 20 and rating == "mid":
        _f.append("janMidRating")
    # 4 janMidSpecial
    if _sig == "buy_special" and _mm == "01" and 11 <= _dd <= 20:
        _f.append("janMidSpecial")
    # 5 r7MayReinforced
    if ((mkt == "mkt_a" and _mm == "05") or (rating == "mid" and _mm == "05")
            or (_sig == "buy_special" and _mm == "11" and mkt == "mkt_industry")
            or (_sig == "buy_special" and _mm == "11" and _wd == 0)):
        _f.append("r7MayReinforced")
    # 6 excludeAuxCross
    if _sig == "buy_aux" and (_mm == "03" or _mm == "05"):
        _f.append("excludeAuxCross")
    # 7 greedy15(信号级可判定子集)
    if ((_sig == "buy_special" and _mm == "05")
            or (_sig == "buy_special" and _mm == "11" and mkt == "mkt_concept")
            or (_sig == "buy_special" and _mm == "03")
            or (_sig == "buy_aux" and _mm == "01")
            or (_sig == "buy" and _mm == "01")
            or (_mm == "03" and _wd == 2 and mkt == "mkt_concept" and rating == "low")
            or (_sig == "buy_aux" and _mm == "12" and ts is not None and ts < 50)
            or (_sig == "buy_aux" and _mm == "05")
            or (_sig == "buy_special" and _mm == "11" and mkt == "mkt_industry")
            or (_mm == "04" and _wd == 1 and mkt == "mkt_concept" and ts is not None and ts < 50)
            or (mkt == "mkt_global" and _q == 1 and _sig == "buy_aux" and rating == "low")
            or (_sig == "buy_special" and _mm == "09" and _wd == 2)):
        _f.append("greedy15")
    return _f


def signal_ai_filtered(date_str, signal, mkt, rating, ts, bull):
    """AI 宏 9 规则删线层判定: 返回 True = 该信号被过滤(命中 8 键 或 _bt_in_universe===false 未入样本)。
    与 queries._ai_macro_hit_filters + _bt_in_universe 同源(v1.1.0):
      - 8 键成员级 = ai_macro_hit_keys 非空(命中即删线+建议回避)
      - +1 类回测剔除 = 未入样本(债类 cgb_*/情绪 s.*/全球商品利率 g.*/港股行业 hk_*/空数组;
        board_etf_map 无 key 或该 index 无任何 ETF 有非空 track_score => _bt_in_universe=false)。
    仅买信号守卫(§23.6 MED3): 非买(sell/sell_stop_loss/band_*)不判降亏。
    is_bull 为布尔(调用处由 hs300 MA60 算好); 无状态(ts/bull None)时:
      - ts None 且属于排除类别 => 未入样本被过滤; ts None 无排除类别 => 保守保留(不过滤, 与 §23.6 空数组例外一致)。
    """
    _sig = signal or ""
    # 非买信号(卖/持有中性)不判降亏(与凯利区"只对买交易过滤"同源)
    if _sig not in _AI_MACRO_BUY_SIGNALS:
        return False
    # buy_special_filtered 归 buy_special
    _sig = "buy_special" if _sig == "buy_special_filtered" else _sig
    # +1 类未入样本: 无 track_score(排除类别, 除自我ETF例外 cgb_10y_etf)
    if ts is None:
        # cgb_10y_etf 是自我ETF唯一例外(§23.6), board_etf_map 有 key 且有 ETF 时 ts 非 None
        return True
    # 8 键命中(含 excludeSpecialBear 需 bull, 见下)
    keys = ai_macro_hit_keys(date_str, _sig, mkt, rating, ts)
    _mm = date_str[4:6] if len(date_str) >= 8 else ""
    if _sig == "buy_special" and mkt in _AI_MACRO_A_STOCK_MARKETS and not bull:
        if "excludeSpecialBear" not in keys:
            keys.append("excludeSpecialBear")
    return bool(keys)


def load_board_etf_track_score():
    """board_etf_map.json -> {index_id: top1 track_score|None}。
    _bt_in_universe = 该 index 存在任一 ETF 有非空 track_score(与 queries L861 同源)。"""
    for p in (os.path.join(REPO, "static-site", "data", "board_etf_map.json"),
              os.path.join(REPO, "data", "board_etf_map.json")):
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    m = json.load(f)
                out = {}
                for iid, arr in m.items():
                    if iid in ("_meta", "_hysteresis") or not isinstance(arr, list):
                        continue
                    best = None
                    for it in arr:
                        ts = it.get("track_score") if isinstance(it, dict) else None
                        if ts is not None and (best is None or ts > best):
                            best = ts
                    out[iid] = best
                return out
            except (json.JSONDecodeError, OSError):
                return {}
    return {}


def load_board_etf_track_tier():
    """board_etf_map.json -> {index_id: top1 track_tier}(X1 键 recent 打标用, 2026-08-24)。

    与 load_board_etf_track_score 同款遍历(同一 max-ts 条目), 读其 track_tier 属性——
    保证 ts 与 tier 同源同条目(与 queries._ai_macro_track_tier_of / 回测 _build_best_etf 同口径)。
    三态归一(2026-08-24 has-track 口径统一): top1 tier=None(score<30 或 N<30 无分) → "null"
    (与回测 trades 列/首页筛选档4 一致, X1 spec 含 "null" 命中); 无带 track_score 条目 → ""
    (诚实降级不命中, 且与「概念无ETF」同串——X1 spec 只含 none/null 不含 "", 概念无ETF不被误伤)。"""
    for p in (os.path.join(REPO, "static-site", "data", "board_etf_map.json"),
              os.path.join(REPO, "data", "board_etf_map.json")):
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    m = json.load(f)
                out = {}
                for iid, arr in m.items():
                    if iid in ("_meta", "_hysteresis") or not isinstance(arr, list):
                        continue
                    best = None      # (ts, tier)
                    for it in arr:
                        if not isinstance(it, dict):
                            continue
                        ts = it.get("track_score")
                        if ts is not None and (best is None or ts > best[0]):
                            best = (ts, it.get("track_tier"))
                    if best is None:
                        out[iid] = ""
                    else:
                        out[iid] = "null" if best[1] is None else str(best[1])
                return out
            except (json.JSONDecodeError, OSError):
                return {}
    return {}


def build_market_state_hs300(close_map):
    """沪深300 close 相对 MA60 状态 -> {date: bool}。无数据返 {} (保守不过滤)。"""
    hs = close_map.get("hs300")
    if not hs or len(sorted(hs)) < 60:
        return {}
    dates = sorted(hs)
    closes = [hs[d] for d in dates]
    state = {}
    for i in range(59, len(dates)):
        ma = sum(closes[i - 59: i + 1]) / 60
        state[dates[i]] = closes[i] > ma
    return state


def load_signal_daily(conn):
    """读 signal_daily 全表 -> [{'date','index_id','signal','reason'}], 按日聚合。
    2026-08-24 对错判定改「N交易日到期冻结窗」后 reason 必带: 波段减仓(sell+reason 含「波段减仓」)
    用固定 5 日窗, 其余买/卖类用默认 10 日窗(与 app/queries.py _WIN_* 参数表同语义, §22 防分叉)。"""
    rows = conn.execute(
        "SELECT date, index_id, signal, reason FROM signal_daily ORDER BY date"
    ).fetchall()
    by_date = defaultdict(list)
    for r in rows:
        by_date[r[0]].append({"index_id": r[1], "signal": r[2], "reason": r[3]})
    return by_date


def load_index_close(conn):
    """index_daily -> {index_id: {date: close}}(含 g./s. 前缀走 daily_metric/score_daily)。"""
    close_map = {}
    rows = conn.execute(
        "SELECT index_id, date, close FROM index_daily WHERE close IS NOT NULL ORDER BY date"
    ).fetchall()
    for r in rows:
        close_map.setdefault(r[0], {})[r[1]] = r[2]

    # 情绪/动态指标(g./s. 前缀)走 daily_metric/score_daily 值(与 queries.py L870-883 同源)
    for prefix, table, idcol in (("g.", "daily_metric", "metric_id"), ("s.", "score_daily", "score_id")):
        try:
            rows = conn.execute(
                f"SELECT {idcol}, date, value FROM {table} WHERE value IS NOT NULL ORDER BY date"
            ).fetchall()
        except sqlite3.OperationalError:
            continue
        for r in rows:
            close_map.setdefault(prefix + r[0], {})[r[1]] = r[2]
    return close_map


def load_trades():
    """返回 (trades_by_date, mode_label)。
    trades_by_date: {signal_date: [ {signal, index_id, return_pct, mode, market_state, rating} ]}
    读 static-site/data/signal_kelly_trades.json(export 最新版), 回退 data/(根目录)。
    """
    p = os.path.join(REPO, "static-site", "data", "signal_kelly_trades.json")
    if not os.path.exists(p):
        p2 = os.path.join(REPO, "data", "signal_kelly_trades.json")
        if os.path.exists(p2):
            p = p2
        else:
            raise FileNotFoundError("signal_kelly_trades.json 未找到 (static-site/data/ 和 data/ 都没有)")

    # trade 行字段(2026-08-23 收尾修复): schema 实际 24 列, index20-22 为 market_tier 三兄弟
    # (signal_kelly_backtest.py L469/L576-577: market_tier/market_tier_all/market_tier_cyb),
    # rating 在 index 23。原硬编码 21 项缺这 3 列 → t["rating"] 读到 market_tier 字符串,
    # by_grade 回测桶/评级类过滤键(janMidRating 等)全部静默失效(§23.7⑤ 上报后用户确认修)。
    FIELD = ["signal_date", "index_id", "signal", "buy_date", "sell_date", "etf_code",
             "etf_name", "track_tier", "track_score", "match_method", "track_low_confidence",
             "buy_price", "sell_price", "shares", "profit", "return_pct", "hold_days",
             "sell_reason", "current_price", "market_state",
             "market_tier", "market_tier_all", "market_tier_cyb", "rating"]
    IDX = {f: i for i, f in enumerate(FIELD)}

    with open(p, encoding="utf-8") as f:
        data = json.load(f)

    by_date = defaultdict(list)  # date -> [trades]
    quad = data.get("quadrants", {})
    for qname, qdata in quad.items():
        if not isinstance(qdata, dict):
            continue
        for mode, arr in qdata.items():
            if not isinstance(arr, list):
                continue
            for tr in arr:
                if not isinstance(tr, list) or len(tr) < len(FIELD):
                    continue
                d = tr[IDX["signal_date"]]
                by_date[d].append({
                    "signal": tr[IDX["signal"]],
                    "index_id": tr[IDX["index_id"]],
                    "return_pct": tr[IDX["return_pct"]],
                    "mode": mode,
                    "market_state": tr[IDX["market_state"]],
                    "rating": tr[IDX["rating"]],
                    "track_score": tr[IDX["track_score"]],  # 2026-08-15 AI宏过滤需用
                    "quad": qname,
                })
    return by_date, data.get("generated_at", "")


# ── AI 宏过滤层(监控卡开关联动) ─────────────────────────────────────────────────
# 「AI降亏过滤」开关开启时, 打点侧只统计**未命中删线**的信号(命中 8 键或未入样本的被过滤),
# 让监控数据同步反映过滤后的实际(§23.3 举一反三: 首页/凯利区已各自实现同一删线层)。
# 回测侧/实盘侧共用同一判词 signal_ai_filtered, 仅评级/ts/bull 来源不同(诚实标注双源差异)。

class FilterCtx(object):
    """过滤判定依赖的上下文(Single source):
      - market_map: {index_id: raw_market} (来自 config/indicators.yaml, 含 "a"/"hk"/"concept"...)
      - ts_map: {index_id: top1 track_score|None} (来自 board_etf_map)
      - tier_map: {index_id: top1 track_tier|None} (来自 board_etf_map; X1 键 recent 打标用, 2026-08-24)
      - bull_state: {date: bool} (hs300 MA60 多头态; 缺省空=保守不过滤)
      - mkt_of(iid) / bull_of(date) / ts_of(iid) / tt_of(iid) 提供索引级映射。
    """

    def __init__(self, market_map, ts_map=None, bull_state=None, tier_map=None):
        self.market_map = market_map or {}
        self.ts_map = ts_map or {}
        self.tier_map = tier_map or {}
        self.bull_state = bull_state or {}

    def mkt_of(self, iid):
        raw = self.market_map.get(iid)
        if not raw:
            # g./s. 前缀(情绪/全球指标)与 hk_* 等无 indicators 项时按前缀推断
            if iid and iid.startswith(("hsi", "hscei", "hstech")):
                return "mkt_hk"
            if iid and (iid.startswith("hk_") or iid.startswith("cgb_") or iid.startswith("s.")):
                return "mkt_hk"  # 排除类别, 未入样本先拦
            return ""
        # indicators.yaml 的 market 是原始值(非 mkt_ 前缀), 映射为大类象限
        m = MARKET_QUAD_MAP.get(raw, "")
        return ("mkt_" + raw) if not m else m

    def ts_of(self, iid):
        return self.ts_map.get(iid)

    def tt_of(self, iid):
        """top1 ETF 跟踪档位(strong/related/approx/none/null, loader 已三态归一);
        无映射/"" → "" 不命中(X1 判定用; "null"=极弱/无分档, 2026-08-24 起命中 X1 与回测同口径)。"""
        return self.tier_map.get(iid) or ""

    def bull_of(self, date_str):
        # 取 <= 信号日最近的 MA60 状态; 无给定日则向前找
        if not self.bull_state:
            return True
        d = date_str
        guard = 0
        while d and d not in self.bull_state and guard < 30:
            guard += 1
            try:
                dt = datetime(int(d[0:4]), int(d[4:6]), int(d[6:8]))
                d = (dt - timedelta(days=1)).strftime("%Y%m%d")
            except Exception:
                d = None
                break
        return self.bull_state.get(d, True) if d else True

    def is_filtered(self, date_str, signal, iid, rating=None):
        """该信号是否被 AI 宏删线过滤(True=过滤)。rating 可自外部注入(回测取 frozen, 实盘取 grade_map)。"""
        mkt = self.mkt_of(iid)
        ts = self.ts_of(iid)
        bull = self.bull_of(date_str)
        return signal_ai_filtered(date_str, signal, mkt, rating, ts, bull)


# ── T3-2(2026-08-23) AI降亏 7 模式·recent 明细块(前端组集数据层) ─────────────────
# 【目的】监控卡接入 7 模式下拉(T3-1 lab/弹窗同款交互): 后端不为 7 模式各预切一份 bank
#   (26.5MB×7 体积灾难), 改为打点「近 N 日逐信号明细」(每键命中标注+回测/实盘胜负), 前端按
#   所选模式组集后复刻聚合链(bucket 去重→rolling_win_rates→_derive_daily_series)。
#   可行性已验证: 前端两图只消费 accuracy.rolling + overfit.daily_by_win/daily_by_dim;
#   daily 曲线=_derive_daily_series 纯滚动胜率偏差派生(current_risk 参数未被引用),
#   d2(OOS)/d3(参数扰动)/d4(象限退化)是回测级重算但不进前端渲染链路(仅预警主口径)。
# 【口径】明细命中键 = v1.1.2 四档口径(与 queries._ai_macro_hit_filters 同源), 与老 filtered bank
#   的 MA60 口径(历史遗留, §23.7⑤ 已上报)存在 excludeSpecialBear 微差 —— v1.1.5 起默认 new14 走
#   组集(recent 明细逐信号打标→前端组集), 仅 p8 对照档走 filtered bank 现有数字不变
#   (新交互无现网行为可对齐), tooltip 诚实标注。
# 【信号级子集】老键中依赖 price_bin(bpb)/ETF相关性(etf) 的组件信号级不可判, 降级跳过
#   (与 queries greedy15/r7 同原则, 首页 ai_macro.filters 同为信号级子集口径, 公示已声明)。
# 【打标键集合】= common.js _KELLY_FADE_MODE_PRESETS 7 模式 keys 并集 + bullAuxBackupStop(独立开关)。
#   ⚠同步纪律: common.js 预设增改模式时本集合必须同步(§23.8 关联更新), 否则新模式组集缺键。
RECENT_KEYS = [
    # p8 ∪ p9 基座(8键 + 候选1)
    "excludeSpecialBear", "n2NovSpecialIndustry", "janMidRating", "janMidSpecial",
    "k2c5HkChase", "r7MayReinforced", "excludeAuxCross", "greedy15", "bullAuxBackupStop",
    # a9/b9/c9 增量(T1 新键 + k3)
    "t1LowTurnSpecial", "q1QvixLowPct", "m1MarginDownBull", "v1HighVol20", "r1VolRatioLow",
    "k3ConceptBuy", "r2bSpecialGlobal", "r2gLowRatingQ3", "n1NorthOutflow", "d1LowDivYield",
    "h1VolChgHighA", "p1LowDivBackup",
    # new14/new18 增量(老键: 5月族/下降期备选/greedy7/v4f + NEW18 北向流出×概念类)
    #   n2NorthOutConcept 2026-08-23 收尾补列(reviewer 终审 FAIL 单点): 原 25 键漏列 →
    #   recent_hit_keys 双重门控(_pk in RECENT_KEYS)致 NEW18 组集该键恒 false, 人口偏松。
    #   补列后走 lr.rule_hit T1 分支自动判定(特征=north_d20, loss_rules.py N2 规格单源)。
    "r10May6NonMay", "declinePhaseSpecial", "greedy7", "v4f", "n2NorthOutConcept",
    # new15 增量(mine29c 2026-08-24 用户拍板): X1 整剔 track_tier=none/null 象限(loss_rules.py 规格单源,
    #   tier_map=board_etf_map top1 跟踪档位, 2026-08-24 起三态归一含 "null"), 供监控卡 new15 模式组集;
    #   不加则组集缺键人口偏松(同 n2 教训)。
    "excludeTierNone",
]
# 明细覆盖交易日数(≥ SURFACE_DAYS=200 + 最大统计窗口 100 + 余量; 前端滚动窗口最长 100 日)
RECENT_DAYS = 340
# hs300 四档短码(明细行 tier 字段, 省体积: 中文档名 10B+ → 1 字符)
_TIER_CODES = {"牛市·主升": 1, "上升期": 2, "下降期": 3, "熊市·主跌": 4}


def load_market_tier_map():
    """market_tier_history.json(export 链 queries.market_tier_history 同源产物) ->
    (tier_map, ma60_map): {date: tier_str} / {date: bool}。文件缺失/损坏返回 ({}, {})。
    供 recent 明细的 v1.1.2 四档判定(与 queries tier_of/ma60_bull_of 同源, §22)。"""
    for p in (os.path.join(REPO, "static-site", "data", "market_tier_history.json"),
              os.path.join(REPO, "data", "market_tier_history.json")):
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    arr = json.load(f)
                tier_map, ma60_map = {}, {}
                for r in arr if isinstance(arr, list) else []:
                    if r and r.get("date"):
                        tier_map[str(r["date"])] = r.get("tier") or ""
                        ma60_map[str(r["date"])] = bool(r.get("ma60_bull"))
                return tier_map, ma60_map
            except (json.JSONDecodeError, OSError):
                return {}, {}
    return {}, {}


def _recent_map_lookup(m, date_str, default):
    """<= date_str 最近日查找(对齐 queries._ai_macro_tier_at 的 bisect_right 语义)。"""
    if not m:
        return default
    d = date_str
    guard = 0
    while d and guard < 40:
        if d in m:
            return m[d]
        guard += 1
        try:
            dt = datetime(int(d[0:4]), int(d[4:6]), int(d[6:8]))
            d = (dt - timedelta(days=1)).strftime("%Y%m%d")
        except Exception:
            return default
    return default


def load_loss_rules_recent():
    """loss_rules.py 单源 + 特征序列(T1 20新键判定用; 与 queries._ai_macro_loss_rules 同源加载)。
    返回 (module|None, feat_at)；module 缺失/特征缺失均降级(新键不打标, 不阻断主链路)。
    ⚠特征文件显式走 REPO 双路回退(2026-08-23 收尾修复): loss_rules.load_features 默认按自身位置
    ../static-site/data 找, worktree/异 cwd 跑会静默落空 → T1 特征类新键全部不打标(组集人口偏松,
    无报错难察觉)。与 load_market_tier_map/load_trades 同款 REPO 回退风格根治。"""
    try:
        import importlib.util
        mod_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "loss_rules.py")
        spec = importlib.util.spec_from_file_location("loss_rules", mod_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["loss_rules"] = mod
        spec.loader.exec_module(mod)
        feats = None
        for fp in (os.path.join(REPO, "static-site", "data", "kelly_loss_features.json"),
                   os.path.join(REPO, "data", "kelly_loss_features.json")):
            if os.path.exists(fp):
                feats = mod.load_features(fp)
                break
        return mod, mod.make_feat_at(feats)
    except Exception:
        return None, (lambda name, date: None)


def recent_hit_keys(date_str, signal, mkt, rating, ts, tier, ma60_bull, lr, feat_at, track_tier=""):
    """recent 明细行命中键判定(v1.1.2 四档口径, 逐字对齐 queries._ai_macro_hit_filters 信号级子集):
    8键(excludeSpecialBear=四档) + bullAuxBackupStop + 备选键(legacyMa60/declinePhase;
    excludeSpecialBearCyb 无 cyb tier 数据源不打标, 诚实降级) + T1 新键(loss_rules.rule_hit 单源,
    track_tier=X1 键 recent 打标用, 2026-08-24)。
    仅买信号守卫(MED3); tier 仅 A股类注入(对齐 queries L812); bpb/etf 组件降级跳过。返回键名列表。"""
    _sig = signal or ""
    if _sig not in _AI_MACRO_BUY_SIGNALS:
        return []
    _sig_n = "buy_special" if _sig == "buy_special_filtered" else _sig
    _mm = date_str[4:6] if len(date_str) >= 8 else ""
    try:
        _dd = int(date_str[6:8])
    except (ValueError, IndexError):
        _dd = 0
    _wd = _ai_weekday(date_str) if date_str else -1
    _q = _ai_quarter(_mm)
    _is_a = mkt in _AI_MACRO_A_STOCK_MARKETS
    _tier = (tier or "") if _is_a else ""
    _f = []
    # 1 n2
    if _sig_n == "buy_special" and _mm == "11" and mkt == "mkt_industry":
        _f.append("n2NovSpecialIndustry")
    # 2 excludeSpecialBear(v1.1.2 主键, 四档)
    if _sig_n == "buy_special" and _is_a and _tier in ("熊市·主跌", "下降期"):
        _f.append("excludeSpecialBear")
    # 2b legacyMa60Special(备选, 老 MA60 语义)
    if _sig_n == "buy_special" and _is_a and not ma60_bull:
        _f.append("legacyMa60Special")
    # 2c declinePhaseSpecial(备选, 下降期×buy_special×全市场)
    if _sig_n == "buy_special" and _tier == "下降期":
        _f.append("declinePhaseSpecial")
    # 2d excludeSpecialBearCyb: 无 cyb tier 数据源, 明细不打标(诚实降级)
    # 2e bullAuxBackupStop(+1 候选1: 牛市·主升×辅买/备买, 四档)
    if _sig in ("buy_aux", "buy_backup") and _tier == "牛市·主升":
        _f.append("bullAuxBackupStop")
    # 2f k2c5HkChase
    if _sig_n in ("buy_special", "buy_backup") and mkt == "mkt_hk":
        _f.append("k2c5HkChase")
    # 3 janMidRating / 4 janMidSpecial
    if _mm == "01" and 11 <= _dd <= 20 and rating == "mid":
        _f.append("janMidRating")
    if _sig_n == "buy_special" and _mm == "01" and 11 <= _dd <= 20:
        _f.append("janMidSpecial")
    # 5 r7MayReinforced(bpb vlow 组件降级跳过)
    if ((mkt == "mkt_a" and _mm == "05") or (rating == "mid" and _mm == "05")
            or (_sig_n == "buy_special" and _mm == "11" and mkt == "mkt_industry")
            or (_sig_n == "buy_special" and _mm == "11" and _wd == 0)):
        _f.append("r7MayReinforced")
    # 6 excludeAuxCross
    if _sig_n == "buy_aux" and (_mm == "03" or _mm == "05"):
        _f.append("excludeAuxCross")
    # 7 greedy15(bpb/q 组件降级跳过, 与 queries L896-907 逐字同)
    if ((_sig_n == "buy_special" and _mm == "05")
            or (_sig_n == "buy_special" and _mm == "11" and mkt == "mkt_concept")
            or (_sig_n == "buy_special" and _mm == "03")
            or (_sig_n == "buy_aux" and _mm == "01")
            or (_sig_n == "buy" and _mm == "01")
            or (_mm == "03" and _wd == 2 and mkt == "mkt_concept" and rating == "low")
            or (_sig_n == "buy_aux" and _mm == "12" and ts is not None and ts < 50)
            or (_sig_n == "buy_aux" and _mm == "05")
            or (_sig_n == "buy_special" and _mm == "11" and mkt == "mkt_industry")
            or (_mm == "04" and _wd == 1 and mkt == "mkt_concept" and ts is not None and ts < 50)
            or (mkt == "mkt_global" and _q == 1 and _sig_n == "buy_aux" and rating == "low")
            or (_sig_n == "buy_special" and _mm == "09" and _wd == 2)):
        _f.append("greedy15")
    # new14/new18 增量老键(信号级可判组件; bpb/etf 组件降级跳过, 对齐 queries 降级原则)
    if _mm == "05":
        _f.append("r10May6NonMay")   # r10 组件1 {mm:"05"}
    if _sig_n == "buy_special" and _mm == "11" and mkt == "mkt_industry":
        _f.append("r10May6NonMay")   # r10 组件3
    if _sig_n == "buy_special" and _mm == "11" and _wd == 0:
        _f.append("r10May6NonMay")   # r10 组件4
    if _sig_n == "buy_special" and _mm == "03" and mkt == "mkt_industry":
        _f.append("r10May6NonMay")   # r10 组件6
    if _mm == "03" and _wd == 2 and _sig_n == "buy_aux":
        _f.append("r10May6NonMay")   # r10 组件7
    # k3ConceptBuy(NEW14 成员; RECENT_KEYS 已登记但此前漏判定谓词=恒 false, 2026-08-26 补:
    # 与 queries._ai_macro_hit_filters 同病灶第三处登记点闭环 §23.2③, 口径逐字同款 buy×mkt_concept)
    if _sig_n == "buy" and mkt == "mkt_concept":
        _f.append("k3ConceptBuy")
    if _sig_n == "buy_special" and _mm == "05":
        _f.append("greedy7")   # greedy7 组件1
    if _sig_n == "buy_special" and _mm == "11" and mkt == "mkt_concept":
        _f.append("greedy7")   # 组件2
    if _sig_n == "buy_special" and _mm == "03":
        _f.append("greedy7")   # 组件3
    if _sig_n == "buy_aux" and _mm == "01":
        _f.append("greedy7")   # 组件4
    if _sig_n == "buy" and _mm == "01":
        _f.append("greedy7")   # 组件6
    if _mm == "03" and _wd == 2 and mkt == "mkt_concept" and rating == "low":
        _f.append("greedy7")   # 组件7
    # v4f 组件 {buy,06,wd2,etf:related}: etf 相关性信号级不可判 → 整键降级不打标(new18 组集该键恒 false)
    # T1 20 新键(loss_rules 单源; rating/ts 语义对齐 queries._ai_macro_hit_new_keys)
    if lr is not None:
        _c = {"sig": _sig, "mkt": lr.MKT_LONG2SHORT.get(mkt, ""), "tier": _tier,
              "track_tier": track_tier or "",
              "date": date_str, "smonth": _mm, "rating": rating or "", "ts": ts, "feat_at": feat_at}
        _have = set(_f)
        for _pk in lr.NEW_KEYS_PROD:
            if _pk in _have:
                continue
            try:
                if _pk in RECENT_KEYS and lr.rule_hit(_pk, _c):
                    _f.append(_pk)
            except Exception:
                continue
    # 只保留 RECENT_KEYS 集合内的键(老键判定产生的键若不在集合=组集用不到, 丢弃省体积)
    return [k for k in _f if k in _RECENT_KEY_SET]


_RECENT_KEY_SET = set(RECENT_KEYS)


def build_recent_block(by_date_raw, close_map, trades_by_date_raw, grade_map, latest_signal, ctx,
                       tier_map, ma60_map, lr, feat_at):
    """近 RECENT_DAYS 日逐信号明细(前端 7 模式组集数据层)。

    行结构(字段名压缩省体积):
      d=signal_date  i=index_id  s=signal(买5类+卖2类; band_hold/情绪类对曲线无贡献不打)
      g=实盘评级(grade_map high/mid/low|null, 实盘桶 by_grade 用)
      t=track_score(ctx.ts_of(index 级 board_etf_map top1); null=未入样, 过滤判定+top-K 用)
      tier=hs300四档短码(0=非A股类/无数据 1=牛市·主升 2=上升期 3=下降期 4=熊市·主跌)
      k=命中键"|"-join(空串=无; v1.1.2 四档口径, 见 recent_hit_keys)
      w=[A,F,G] 回测胜负 1/0(null=该 mode 无基笔; bucket_backtest_trades 同款 (mode,d,i,s) 去重)
      gr=回测交易冻结 rating(high/mid/low|null, 回测桶 by_grade 用)
      v=实盘胜负 1/0(null=不计入; bucket_actual 同款条件链: band_hold/非买非卖/未入样/无收盘/当日)
    返回 {"days": RECENT_DAYS, "latest": latest_signal, "keys": RECENT_KEYS, "rows": [...]}。
    """
    all_dates = sorted(by_date_raw.keys())
    recent_dates = set(all_dates[-RECENT_DAYS:]) if all_dates else set()
    # 回测侧 w/gr: per (d, i, s) first-wins per mode(bucket_backtest_trades seen 去重同款)
    bt_map = {}
    for d in sorted(trades_by_date_raw.keys()):
        if d not in recent_dates:
            continue
        seen = set()
        for t in trades_by_date_raw.get(d, []):
            mode = t.get("mode")
            if mode not in AFG_MODES:
                continue
            key = (d, t.get("index_id"), t.get("signal"))
            dk = (mode,) + key
            if dk in seen:
                continue
            seen.add(dk)
            ent = bt_map.setdefault(key, {"w": {}, "gr": None})
            if mode not in ent["w"]:
                ent["w"][mode] = 1 if (t.get("return_pct") or 0) > 0 else 0
                # gr 守卫(与 bucket_backtest_trades by_grade 同款 in 校验): 2026-08-23 收尾修复——
                # 原历史遗留=load_trades FIELD 21 项 vs trades schema 24 项(rating 实在 index 23),
                # t["rating"] 读到 market_tier 字符串 → 校验恒 None(by_grade 回测桶空+评级类过滤键失效)。
                # FIELD 已补齐 market_tier 三兄弟(§23.7⑤ 上报后用户确认修), gr 正常取冻结评级。
                if ent["gr"] is None and t.get("rating") in ("high", "mid", "low"):
                    ent["gr"] = t.get("rating")
    # 实盘侧 v: bucket_actual 单信号判定(条件链逐字对齐 L649-684)
    latest_close = {}
    for iid, m in close_map.items():
        if m:
            latest_close[iid] = m[max(m.keys())]
    rows = []
    for d in all_dates[-RECENT_DAYS:]:
        for s in by_date_raw.get(d, []):
            sig = s.get("signal")
            iid = s.get("index_id")
            is_sell = sig in SELL_SIGNALS
            if not is_sell and sig not in _BUY_SIG_SET and sig != "buy_special_filtered":
                continue  # band_hold/情绪类等: bucket_actual/过滤链均不计, 不打
            # 实盘胜负(bucket_actual 条件链)
            v = None
            if sig == "band_hold":
                v = None
            else:
                sig_n = "buy_special" if sig == "buy_special_filtered" else sig
                is_sell_n = sig_n in SELL_SIGNALS
                ok = True
                if not is_sell_n:
                    if sig_n not in BUY_SIGNALS or ctx.ts_of(iid) is None:
                        ok = False
                if ok:
                    cm = close_map.get(iid)
                    sig_close = cm.get(d) if cm else None
                    today_close = latest_close.get(iid)
                    if sig_close is None or today_close is None or d >= latest_signal:
                        ok = False
                    else:
                        since_ret = (today_close - sig_close) / sig_close
                        v = 1 if ((since_ret < 0) if is_sell_n else (since_ret > 0)) else 0
            # 命中键(v1.1.2 四档)
            mkt = ctx.mkt_of(iid)
            rating = grade_map.get((iid, sig),
                                   grade_map.get((iid, "buy_special" if sig == "buy_special_filtered" else sig), ""))
            tier = _recent_map_lookup(tier_map, d, "")
            ma60 = _recent_map_lookup(ma60_map, d, True)
            keys = recent_hit_keys(d, sig, mkt, rating, ctx.ts_of(iid), tier, ma60, lr, feat_at,
                                   track_tier=ctx.tt_of(iid))
            bt = bt_map.get((d, iid, sig))
            rows.append({
                "d": d, "i": iid, "s": sig,
                "g": rating if rating in ("high", "mid", "low") else None,
                "t": ctx.ts_of(iid),
                "tier": _TIER_CODES.get(tier, 0),
                "k": "|".join(keys),
                "w": [(bt or {}).get("w", {}).get(m) for m in AFG_MODES],
                "gr": (bt or {}).get("gr"),
                "v": v,
            })
    return {"days": RECENT_DAYS, "latest": latest_signal, "keys": RECENT_KEYS, "rows": rows}


def filter_trades_by_date(trades_by_date, ctx, mode_filt=None):
    """过滤回测交易: 只保留 not signal_ai_filtered 的交易(仍按 mode 区分, 不破坏 A/F/G 差异)。
    回测 rating 用交易冻结值; track_score 用交易冻结值(优先)否则 ctx.ts_map。
    返回新的 trades_by_date(未改原 dict)。"""
    out = {}
    for d, lst in trades_by_date.items():
        kept = []
        for t in lst:
            if mode_filt is not None and t["mode"] not in mode_filt:
                continue
            ts = t.get("track_score")
            if ts is None:
                ts = ctx.ts_of(t.get("index_id"))
            rating = t.get("rating")
            if ctx.is_filtered(str(d), t.get("signal"), t.get("index_id"), rating):
                continue
            kept.append(t)
        if kept:
            out[d] = kept
    return out


def filter_actual_by_date(by_date, ctx, grade_map):
    """过滤实盘信号: 只保留 not signal_ai_filtered 的信号。
    实盘评级 = grade_map[(iid, sig)](signal_stats 当前 10d score 分档, 与 _ai_macro_rating_of 同源诚实标注)。
    返回新的 by_date(未改原 dict)。"""
    out = {}
    for d, lst in by_date.items():
        kept = []
        for s in lst:
            sig = s.get("signal")
            iid = s.get("index_id")
            rating = grade_map.get((iid, sig), grade_map.get((iid, "buy_special" if sig == "buy_special_filtered" else sig), ""))
            if ctx.is_filtered(str(d), sig, iid, rating):
                continue
            kept.append(s)
        if kept:
            out[d] = kept
    return out


# ── top-K 保留集(监控卡 K 档, 与首页/凯利 top-K 同口径 §23.6) ───────────────
# K档 × 降亏开关两开关独立(2026-08-16 用户拍板修改原方案): K 档基于「人口」信号集做 top-K,
#   人口由调用方决定 —— 全信号(by_date_raw) 或 降亏过滤后(by_date_filt)。降亏开=前端读 filtered_by_k
#   (过滤人口 top-K), 降亏关=前端读 by_k(全信号人口 top-K)。K 独立可用, 不依赖降亏开关。
def build_topk_kept_map(by_date, ctx, grade_map, k):
    """在给定人口信号集上按 signal_date 分组 quality 序取前 k(top-K 保留集)。
    人口由调用方决定 = 全信号 by_date_raw(by_k 档) 或 降亏过滤后 by_date_filt(filtered_by_k 档)。
    排序口径(与首页 _posCapSortedFn / lab top-K 同源, §23.6): track_score DESC → rating(高>中>低>空)
    → signal(备买>主买>辅买>追买); 仅 buy 类信号(buy/buy_aux/buy_special/buy_backup, 卖/波段不入位)。
    返 {(signal_date_str, index_id, signal)} 保留集(实盘侧 top-K 与回测侧同批基笔, 1:1 对齐首页语义)。"""
    by_signal_date = defaultdict(list)
    for d, lst in by_date.items():
        for s in lst:
            sig = s.get("signal")
            if sig not in _BUY_SIG_SET:
                continue
            iid = s.get("index_id")
            # track_score: 信号冻结值优先, 否则 ctx.ts_map(board_etf_map)
            ts = s.get("track_score")
            if ts is None:
                ts = ctx.ts_of(iid)
            # P2 修法①: 排除未入样信号(ts=None, 债类/情绪/全球商品利率/港股行业/空数组等无 track_score,
            #   board_etf_map 无 key 或该 index 无任何 ETF 有非空 track_score => _bt_in_universe=false)。
            # 与首页 _posCapSortedFn 人口(_bt_in_universe !== false)同人口(§23.6),
            # 真正做到 top-K 与首页 AI仓位建议同口径(by_k/filtered_by_k 均只从已入样信号选)。
            if ts is None:
                continue
            rating = s.get("rating") or grade_map.get(
                (iid, sig), grade_map.get((iid, "buy_special" if sig == "buy_special_filtered" else sig), ""))
            by_signal_date[d].append({"iid": iid, "sig": sig, "ts": ts, "rating": rating})
    kept = set()
    for d, items in by_signal_date.items():
        items.sort(key=lambda t: (-(t["ts"] if t["ts"] is not None else -1),
                                   _TOPK_RC.get(t["rating"], 3),
                                   _TOPK_SC.get(t["sig"], 9)))
        for it in items[:k]:
            _sig = "buy_special" if it["sig"] == "buy_special_filtered" else it["sig"]
            kept.add((str(d), it["iid"], _sig))
    return kept


def filter_trades_by_kept(trades_by_date, kept):
    """回测交易按保留集过滤: 只留 (signal_date, index_id, signal) 在 kept 内的交易。"""
    out = {}
    for d, lst in trades_by_date.items():
        new = [t for t in lst if (str(d), t.get("index_id"), t.get("signal")) in kept]
        if new:
            out[d] = new
    return out


def filter_by_date_by_kept(by_date, kept):
    """实盘信号按保留集过滤: 只留 (signal_date, index_id, signal) 在 kept 内的信号。"""
    out = {}
    for d, lst in by_date.items():
        new = [s for s in lst if (str(d), s.get("index_id"), s.get("signal")) in kept]
        if new:
            out[d] = new
    return out


# ── 口径打点 ──────────────────────────────────────────────────────────────────
def _win(sig):
    """单笔是否命中方向。回测口径: return_pct>0 = 对。"""
    return (sig.get("return_pct") or 0) > 0


def bucket_backtest_trades(trades_by_date, dates):
    """按 signal_date 桶回测口径: 每日 {'total':{n,win,win_rate}, by_mode:{A:{..},F:..,G:..},
    by_signal:{..}, by_grade:{high/mid/low}}。
    只统计记入总体的模式(A/F/G)。其余模式按 AFG_MODES 过滤。

    去重(2026-08-15, 需求4): 同一笔交易(signal_date+index_id+signal)会按 16 象限 × mode 重复出现在
    trades_by_date 多个位置, 累计 ~11.85 倍虚高。此处按 (mode, signal_date, index_id, signal) 去重,
    每笔交易在**同一种卖出模式内只计一次**(去掉跨象限重复), 但保留 A/F/G 卖出模式差异(三者 return_pct
    不同、语义为三种独立卖出策略, 不可合并)。
    效果验证: 去重后 win_rate=55.71% 与现状 55.70% 一致(等权平均同比例缩), n 90048→22794(去掉 ~4x 跨象限重复)。
    注意: 本函数仅用于**滚动准确率曲线**, 不影响 4 维风险分(D2/D4 用原始 trades_by_date 全象限聚合)。
    """
    out = {}
    all_dates = sorted(trades_by_date.keys())
    for d in all_dates:
        trades = trades_by_date[d]
        n = win = 0
        by_mode = defaultdict(_bucket_new)
        by_signal = defaultdict(_bucket_new)
        by_grade = defaultdict(_bucket_new)
        seen = set()  # (mode, date, index_id, signal) 去重
        for t in trades:
            mode = t["mode"]
            sig = t["signal"]
            if mode not in AFG_MODES:
                continue
            dk = (mode, d, t["index_id"], sig)
            if dk in seen:
                continue
            seen.add(dk)
            hit = _win(t)
            n += 1
            if hit:
                win += 1
            _bucket_add(by_mode[mode], hit)
            if sig in ("buy", "buy_aux", "buy_special", "buy_backup"):
                _bucket_add(by_signal[sig], hit)
            elif sig in SELL_SIGNALS:
                _bucket_add(by_signal[sig], hit)
            g = t.get("rating")
            if g in ("high", "mid", "low"):
                _bucket_add(by_grade[g], hit)
        out[d] = {
            "total": _bucket_final(n, win),
            "by_mode": {m: by_mode[m] for m in AFG_MODES if by_mode[m]["n"]},
            "by_signal": {k: v for k, v in by_signal.items() if v["n"]},
            "by_grade": {k: v for k, v in by_grade.items() if v["n"]},
        }
    return out


def load_signal_grade_map():
    """实盘评级映射: {(index_id, signal): high|mid|low}。

    基于 static-site/data/signal_stats.json 的 [index_id][signal]['10d']['score'](最近10日滚动 score 0-1),
    按与回测同源阈值(0.75/0.55, 见 signal_kelly_backtest.py RATING_HIGH/RATING_MID)分档。
    ⚠ 诚实标注(§5.1): 实盘评级是「当前 score 快照」分档(signal_stats 只存最近10日 score, 无历史逐日 score),
    回测评级是「生成时 score」固化 — 两者时间轴不完全一致(实盘按当前分档统一套用全部历史信号)。
    """
    p = os.path.join(REPO, "static-site", "data", "signal_stats.json")
    if not os.path.exists(p):
        p2 = os.path.join(REPO, "data", "signal_stats.json")
        if os.path.exists(p2):
            p = p2
        else:
            return {}
    try:
        with open(p, encoding="utf-8") as f:
            stats = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    RATING_HIGH, RATING_MID = 0.75, 0.55
    grade_map = {}
    for iid, sigs in (stats or {}).items():
        if not isinstance(sigs, dict):
            continue
        for sig, periods in sigs.items():
            if not isinstance(periods, dict):
                continue
            d10 = periods.get("10d")
            if not isinstance(d10, dict):
                continue
            score = d10.get("score")
            if not isinstance(score, (int, float)):
                continue
            if score >= RATING_HIGH:
                g = "high"
            elif score >= RATING_MID:
                g = "mid"
            else:
                g = "low"
            grade_map[(iid, sig)] = g
    return grade_map


# 对错判定「N交易日到期冻结窗」窗长表(2026-08-24 用户拍板, 与 app/queries.py _WIN_* 同语义单点对齐,
# §22 防分叉; 监控卡固定跟默认档 10 日不做切换, 前端首页才有 10/15 对照切换):
_WIN_DEFAULT_N = 10   # 买入四类+sell/sell_stop_loss 默认档(A 方法 10 日固定卖出周期)
_WIN_BAND_SELL_N = 5  # 波段减仓(sell + reason 含「波段减仓」)固定档


def bucket_actual(by_date, close_map, latest_date, grade_map=None, universe=None):
    """实盘口径按日打点: N 交易日到期冻结窗方向(2026-08-24 起, 替代原"至今"口径)。与首页 since_correct 同语义。
    到期冻结机制: 满窗(N 个后继交易日存在)=第 N 日收盘 vs 信号日收盘 定案; 未满窗=最新收盘暂计至今;
    今日信号(d>=latest_date)仍不计。波段减仓(reason 含「波段减仓」)固定 5 日窗, 其余计分信号默认 10 日窗。
    2026-08-17 方案A「实盘限定回测宇宙」: 买类只统计回测宇宙内信号, 使实盘线与回测线比同一批买入信号。
    universe = {index_id: track_score|None}(来自 board_etf_map, 同 §23.6 _bt_in_universe 判定):
      - 买信号类型必须 ∈ BUY_SIGNALS(buy/buy_aux/buy_special/buy_backup) —— 回测只测买入白名单信号(§23.6 buy_whitelist);
        卖(sell/sell_stop_loss)/情绪类/全球商品利率/港股行业等回测不测的信号剔除。
      - index 必须 _bt_in_universe=True(universe[iid] is not None, 即 board_etf_map 有 key 且有非空 track_score)。
      - band_hold 中性不计(原逻辑)。
    2026-08-17 方案B(卖类): sell/sell_stop_loss **不过滤宇宙**, 统计全部卖信号实盘实际命中率(卖后跌=对),
      无回测对照(回测交易本体全为买信号, 卖信号不独立成回测交易)。
    returns {date: {total, by_mode(占位), by_signal, by_grade}}
    """
    out = []
    all_dates = sorted(by_date.keys())
    # 最新可用收盘(未满窗暂计端兜底) + 每标的排序日期序列缓存(bisect 定位第 N 后继交易日, O(logK)/条)
    latest_close = {}
    seq_cache = {}
    for iid, m in close_map.items():
        if m:
            latest_close[iid] = m[max(m.keys())]
            seq_cache[iid] = sorted(m.keys())
    grade_map = grade_map or {}
    universe = universe or {}
    for d in all_dates:
        sigs = by_date[d]
        n = win = 0
        by_signal = defaultdict(_bucket_new)
        by_grade = defaultdict(_bucket_new)
        for s in sigs:
            sig = s["signal"]
            iid = s["index_id"]
            if sig == "band_hold":
                continue  # 中性不计
            # 2026-08-17 方案B: 卖类(sell/sell_stop_loss)不过滤宇宙, 统计全部卖信号实盘实际命中率(无回测对照);
            # 买类仍限定回测宇宙(方案A): 只统计回测会测的买入白名单信号 + 已入样(_bt_in_universe)。
            is_band_sell = (sig == "sell") and ("波段减仓" in (s.get("reason") or ""))
            n_win = _WIN_BAND_SELL_N if is_band_sell else _WIN_DEFAULT_N
            is_sell = sig in SELL_SIGNALS
            if not is_sell:
                if sig not in BUY_SIGNALS:
                    continue  # 情绪类/全球商品利率/港股行业等回测不测、非卖类, 剔除(避免 22% 命中率混入实盘总样本拉低)
                if universe.get(iid) is None:
                    continue  # 不在回测宇宙(board_etf_map 无 key 或无非空 track_score = _bt_in_universe False)
            cm = close_map.get(iid)
            if not cm:
                continue
            sig_close = cm.get(d)
            if sig_close is None:
                continue
            today_close = latest_close.get(iid)
            if today_close is None:
                continue
            if d >= latest_date:
                continue  # 今日信号无"至今"语义(与 queries.py 今日信号短路一致)
            # N 交易日到期冻结窗: 满窗=第 N 后继交易日收盘定案; 未满窗=最新收盘暂计至今
            ds = seq_cache.get(iid) or []
            i0 = bisect.bisect_right(ds, d)
            if i0 + n_win <= len(ds):
                ref_close = cm[ds[i0 + n_win - 1]]
            else:
                ref_close = today_close
            since_ret = (ref_close - sig_close) / sig_close
            # 方向判定: 买类恒看多(涨=对); 卖类(sell/sell_stop_loss 含波段减仓变体)看空(卖后跌=对, 2026-08-17 方案B)
            is_win = (since_ret < 0) if is_sell else (since_ret > 0)
            if not is_sell:
                # total 只含买类(方案A 实盘总样本=回测宇宙内买入信号); 卖类仅入 by_signal, 不混入总样本
                n += 1
                if is_win:
                    win += 1
            _bucket_add(by_signal[sig], is_win)
            g = grade_map.get((iid, sig))
            if g in ("high", "mid", "low"):
                _bucket_add(by_grade[g], is_win)
        # 2026-08-17 方案B: 日期可能只有卖类信号(total=0 但 by_signal 有值), 仍须入点以保 sell 维度曲线
        if n > 0 or by_signal:
            out.append({"date": d, "total": _bucket_final(n, win),
                        "by_signal": {k: v for k, v in by_signal.items() if v["n"]},
                        "by_grade": {k: v for k, v in by_grade.items() if v["n"]}})
    return out


def _bucket_new():
    return {"n": 0, "win": 0, "win_rate": None}


def _bucket_add(b, hit):
    b["n"] += 1
    if hit:
        b["win"] += 1


def _bucket_final(n, win):
    return {"n": n, "win": win, "win_rate": (win / n * 100) if n else None}


# ── 滚动窗口聚合 ───────────────────────────────────────────────────────────
def _bucket_at(point, key_path):
    """从每日点取某维度桶 {n,win}(key_path 如 ['total'] 或 ['by_grade','high'])。"""
    cur = point
    for k in key_path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    if not isinstance(cur, dict):
        return None
    return cur


def rolling_win_rates(daily_points, dates, windows=WINDOWS, key_path=None, min_n=20):
    """把每日 {date,total:{win_rate}} 聚合成滚动窗口序列(key_path 默认 total; 可传 ['by_grade','high'] 等)。
    返回 {w: [{date, win_rate, n}]}(仅在窗口内有 signal 的日期出现)。
    2026-08-17 用户拍板「样本数不做限制」: 完全去掉样本数下限判定, 有多少画多少;
    早期窗口不满 / 维度样本稀疏的档位照常算 win_rate(n 值照常输出, 前端看 n 判断可信度)。
    min_n 参数仅为兼容透传占位, 不再参与判定(调用方 rolling_win_rates_by_dim/_derive_daily_series 仅透传)。
    """
    points = sorted(daily_points, key=lambda x: x["date"])
    key_path = key_path or ["total"]
    out = {}
    for w in windows:
        seq = []
        for i, p in enumerate(points):
            b = _bucket_at(p, key_path)
            if not b or b.get("n", 0) == 0:
                continue
            start = max(0, i - w + 1)
            window = points[start:i + 1]
            n = sum((_bucket_at(x, key_path) or {}).get("n", 0) for x in window)
            win = sum((_bucket_at(x, key_path) or {}).get("win", 0) for x in window)
            # 不设样本数下限: 有多少画多少(2026-08-17 用户拍板)
            seq.append({"date": p["date"], "n": n, "win_rate": (win / n * 100) if n else None})
        out[w] = seq
    return out


def rolling_win_rates_by_dim(bt_buckets, act_buckets, bt_keys, act_keys, windows=WINDOWS, min_n=20):
    """多个维度的滚动聚合: {key: {bt: {w:[..]}, act: {w:[..]}}}。
    bt_buckets: {date: bt_daily[d]}   act_buckets: [ {date,total,by_signal,by_grade} ]
    样本数下限判定见 rolling_win_rates(2026-08-17 已完全去掉), 本函数仅透传 min_n 占位。
    """
    out = {}
    bt_points_list = [{"date": d, **bt_buckets[d]} for d in sorted(bt_buckets.keys())]
    act_points_list = list(act_buckets)
    for key in bt_keys:
        bt_roll = rolling_win_rates(bt_points_list, [], windows, key_path=key, min_n=min_n)
        act_roll = rolling_win_rates(act_points_list, [], windows, key_path=key, min_n=min_n) \
            if key in act_keys else {}
        out[key] = {"bt": bt_roll, "act": act_roll}
    # 仅实盘存在的维度(如 sell/sell_stop_loss 回测无)
    for key in act_keys:
        if key in out:
            continue
        if key in ("sell", "sell_stop_loss"):
            continue  # 回测侧无 sell 类, 单独处理(scroll skip)
        act_roll = rolling_win_rates(act_points_list, [], windows, key_path=key, min_n=min_n)
        out[key] = {"bt": {}, "act": act_roll}
    return out


def add_win_rate_from_daily(daily, date, wins, total):
    """工具:给某日 rolling 点注入字段。"""
    return


# ── 4 维过拟合指标 ───────────────────────────────────────────────────────────
def calc_d1_deviation(actual_series, backtest_series, window=60):
    """维度1: 回测-实盘偏离度。用最近 window 窗口内实盘胜率 vs 回测胜率。
    实盘(actual)缺样本时返回 None(数据不足)。
    """
    if not actual_series or not backtest_series:
        return None
    # 取最近有数据的实盘点
    def _last_win_rate(series):
        for p in reversed(series):
            wr = p.get("win_rate")
            if wr is not None:
                return wr
        return None
    a_wr = _last_win_rate(actual_series)
    b_wr = _last_win_rate(backtest_series)
    if a_wr is None or b_wr is None or b_wr == 0:
        return None
    dev = (a_wr - b_wr) / b_wr  # 相对偏离
    # 偏离风险分: >+10% -> 10(超预期, 低); 0~10% -> 30; -10%~0 -> 60; <-10% -> 90
    if dev > 0.10:
        return 10
    if dev > 0:
        return 30
    if dev > -0.10:
        return 60
    return 90


def calc_d2_oos(trades_by_date):
    """维度2: 滚动样本外检验。按年切分, 用前 5 年选最优组合, 检验下一年。
    返回最近一次 OOS 风险分(样本不足或不适用时 None)。
    """
    # 回测口径各年 AFG 总体胜率
    year_win = defaultdict(lambda: {"n": 0, "win": 0})
    for d, trades in trades_by_date.items():
        y = d[:4]
        for t in trades:
            if t["mode"] not in AFG_MODES:
                continue
            year_win[y]["n"] += 1
            if _win(t):
                year_win[y]["win"] += 1
    years = sorted(year_win.keys())
    if len(years) < 5:
        return None
    # 用最后一年作为检验窗口, 前5年为调参窗口(近似方案 §3 维度2: 5 年调参 -> 下一年检验)
    # 递归回看每连续 6 年: [y-5..y-1] 调参, y 检验
    def _try_eval(y_train_start, y_test):
        tr, te = year_win.get(y_train_start), year_win.get(y_test)
        # 调参窗口取该年及之后4年聚合? 简化: 用检验年前 5 个含数据的年份聚合
        avail = [yy for yy in years if yy < y_test]
        if len(avail) < 5:
            return None
        train_years = avail[-5:]
        tn = tw = 0
        for yy in train_years:
            tn += year_win[yy]["n"]
            tw += year_win[yy]["win"]
        if tn == 0:
            return None
        tr_wr = tw / tn
        te_wr = te["win"] / te["n"] if te["n"] else None
        if te_wr is None or tr_wr == 0:
            return None
        decay = (te_wr - tr_wr) / tr_wr
        # 衰减率 >20% 高 / 10-20% 关注 / <10% 正常(负值=检验窗口更好=好)
        if decay > 0.20:
            return 90
        if decay > 0.10:
            return 60
        return 20
    # 取最近一个可评估的检验年
    for y_test in reversed(years):
        if y_test < years[-1]:
            continue
        res = _try_eval(None, y_test)
        if res is not None:
            return res
    return None


def calc_d3_param(trades_by_date):
    """维度3: 参数稳定性。对默认组合做卖出模式微扰(A<->F<->G),
    滚动 60 日收益率相对默认 G 的敏感度。
    某模式收益变化 >30% 或符号翻转 -> 微扰风险。返回 0-100(角度分)。
    """
    # 近 60 日 (60 个有交易的日期)
    all_dates = sorted(trades_by_date.keys())
    recent = all_dates[-60:]
    mode_rets = defaultdict(list)  # mode -> [return_pct]  近60日
    for d in recent:
        for t in trades_by_date[d]:
            if t["mode"] in AFG_MODES:
                mode_rets[t["mode"]].append(t["return_pct"] or 0)
    if OVERFIT_MODE not in mode_rets or len(mode_rets[OVERFIT_MODE]) < 10:
        return None
    def _avg(arr):
        return sum(arr) / len(arr) if arr else 0.0
    base = _avg(mode_rets[OVERFIT_MODE])
    if base == 0:
        return None
    max_sens = 0.0
    for m in AFG_MODES:
        if m == OVERFIT_MODE or not mode_rets.get(m):
            continue
        v = _avg(mode_rets[m])
        sens = abs(v - base) / abs(base)
        # 符号翻转惩罚
        if v * base < 0:
            sens = max(sens, 0.35)
        max_sens = max(max_sens, sens)
    if max_sens > 0.30:
        return 90
    if max_sens > 0.10:
        return 50
    return 20


def calc_quadrant_health(trades_by_date, window=60):
    """维度4: 象限退化检测(回测口径, 数据充足)。

    对每个象限, 算近 window 个有交易日的胜率 vs 全史胜率(回测预期)。
    近窗口 < 全史-10pp(百分点) -> 该象限退化(degraded=True)。
    退化比例 = 退化的象限数 / 重点象限总数(低样本跳过)。
    同时返回每象限 {last_n_win_rate, backtest_exp(n & 全史胜率), degraded, last_n} 供前端 quadrant_health。
    数据不足(重点象限近窗样本<20)返 None。
    """
    QUADS = ["sig_main", "sig_aux", "sig_special", "sig_backup",
             "mkt_a", "mkt_hk", "mkt_global", "mkt_industry", "mkt_concept",
             "rating_high", "rating_mid", "rating_low",
             "etf_strong", "etf_related", "etf_approx", "etf_has_track"]
    # 各象限: 全史 n/win + 近窗 n/win
    all_dates = sorted(trades_by_date.keys())
    recent_set = set(all_dates[-window:])
    health = {}
    for q in QUADS:
        total_n = total_win = 0
        rec_n = rec_win = 0
        for d, trades in trades_by_date.items():
            in_rec = d in recent_set
            for t in trades:
                if t["quad"] != q or t["mode"] not in AFG_MODES:
                    continue
                hit = _win(t)
                total_n += 1
                total_win += int(hit)
                if in_rec:
                    rec_n += 1
                    rec_win += int(hit)
        if total_n == 0:
            health[q] = {"n": 0, "win_rate": None, "last_n": 0, "last_win_rate": None,
                         "backtest_exp": None, "degraded": None}
            continue
        exp = total_win / total_n * 100
        health[q] = {
            "n": total_n, "win_rate": total_win / total_n * 100,
            "last_n": rec_n, "last_win_rate": (rec_win / rec_n * 100) if rec_n else None,
            "backtest_exp": exp, "degraded": None,
        }
        if rec_n >= 20 and health[q]["last_win_rate"] is not None:
            health[q]["degraded"] = health[q]["last_win_rate"] < exp - 10
    return health


def calc_d4_quadrant(trades_by_date, window=60):
    """维度4得分: 退化比例×100。重点象限这里=所有有数据象限中 degraded 的比例。
    无退化信号返低分; 数据不足返 None。"""
    health = calc_quadrant_health(trades_by_date, window)
    if not health:
        return None
    scored = [h for h in health.values() if h.get("degraded") is not None and h["n"] >= 20]
    if not scored:
        return None
    degrade_count = sum(1 for h in scored if h["degraded"])
    return round(degrade_count / len(scored) * 100)


# ── 综合风险分 + 等级 ───────────────────────────────────────────────────────
def risk_level(score):
    if score is None:
        return "gray"
    if score < 30:
        return "green"
    if score <= 60:
        return "yellow"
    return "red"


def compute_risk(d1, d2, d3, d4):
    """综合 0-100 分数。维度为 None(数据不足)按 0 处理但记录权重缺失。"""
    parts = [W_D1 * (d1 if d1 is not None else 0),
             W_D2 * (d2 if d2 is not None else 0),
             W_D3 * (d3 if d3 is not None else 0),
             W_D4 * (d4 if d4 is not None else 0)]
    total_w = 0.0
    dims = []
    for v, w in zip(parts, (W_D1, W_D2, W_D3, W_D4)):
        total_w += w
        dims.append(round(w * (v / w if v else 0)))
    score = round(sum(parts))
    return score, {
        "d1": d1, "d2": d2, "d3": d3, "d4": d4,
        "weighted": {k: round(parts[i], 1) for i, k in enumerate(["d1", "d2", "d3", "d4"])},
    }


# ── 预警 ─────────────────────────────────────────────────────────────────────
ALERT_RULES = {
    "overfit_high": {"level": "SEVERE", "desc": "综合过拟合风险分 >=60(红区)"},
    "risk_climbing": {"level": "WARN", "desc": "风险分连续 5 日攀升"},
    "quadrant_degrade": {"level": "WARN", "desc": "重点象限连续 10 日实盘胜率 < 回测预期-15pp"},
    "oos_fail": {"level": "WARN", "desc": "样本外衰减率 >20%"},
    "param_spike": {"level": "WARN", "desc": "卖出模式微扰收益翻转符号或变化>30%"},
}


def evaluate_alerts(risk_score, prev_scores, d1, d2, d3, d4, date):
    """返回 [ {type, level, subject, body} ] 触发的预警。"""
    alerts = []
    if risk_score is not None and risk_score >= 60:
        alerts.append(_mk_alert("overfit_high", risk_score, date, d1=d1, d2=d2, d3=d3, d4=d4))

    # 连续 5 日攀升: 取最近 6 个有分日期, 看近 5 次是否严格递增
    if len(prev_scores) >= 5:
        recent = prev_scores[-5:]
        if all(recent[i] < recent[i + 1] for i in range(len(recent) - 1)):
            alerts.append(_mk_alert("risk_climbing", risk_score, date, prev=recent))

    if d2 is not None and d2 >= 60:
        alerts.append(_mk_alert("oos_fail", risk_score, date, d2=d2))
    if d3 is not None and d3 >= 90:
        alerts.append(_mk_alert("param_spike", risk_score, date, d3=d3))

    # 象限退化第一版: 数据不充分(实盘象限细分未建), 暂不触发, 预留
    return alerts


def _mk_alert(typ, risk_score, date, **kw):
    rule = ALERT_RULES[typ]
    subject = f"[过拟合监控] {risk_score if risk_score is not None else ''}分 · {rule['desc']}"
    body = (
        f"<b>过拟合监控预警</b> · 数据日期 {date}<br>"
        f"触发规则: <b>{rule['desc']}</b>(级别 {rule['level']})<br>"
        f"当前综合风险分: <b>{risk_score}</b> / 100<br>"
        f"建议: 关注回测参数是否处于历史拟合的尖峰区, 实盘与回测预期若有明显背离, 降低参数依赖/降仓观察。<br>"
    )
    if kw.get("d1") is not None:
        body += f"D1 回测-实盘偏离: {kw['d1']}<br>"
    if kw.get("d2") is not None:
        body += f"D2 样本外衰减: {kw['d2']}<br>"
    if kw.get("d3") is not None:
        body += f"D3 参数稳定: {kw['d3']}<br>"
    return {"type": typ, "level": rule["level"], "subject": subject, "body": body,
            "date": date, "risk_score": risk_score}


# ── 邮件发送 ─────────────────────────────────────────────────────────────────
def send_notify(subject, body, level="WARN", dry_run=False, dedup_key=None):
    """调 notify.py 发邮件+Telegram+飞书。dry_run 试发。"""
    notify = os.path.join(SCRIPT_DIR, "notify.py")
    cmd = [sys.executable, notify, subject, body]
    if level == "SEVERE":
        cmd.append("--severe")
    if dedup_key:
        cmd += ["--dedup-key", dedup_key, "--dedup-window", "86400"]  # 同 key 24h 不重发
    if dry_run:
        cmd.append("--dry-run")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return r.returncode == 0, r.stderr
    except Exception as e:  # noqa: BLE001
        return False, str(e)


# ── 主流程 ───────────────────────────────────────────────────────────────────
def load_prev_state():
    if os.path.exists(OUT_JSON):
        try:
            with open(OUT_JSON, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _derive_daily_series(bt_roll, act_roll, current_risk, latest_date, win=60, min_n=20):
    """从「实盘 vs 回测 W 日滚动胜率偏离」派生历史每日过拟合风险分序列(无前视)。
    注意: 本函数消费 rolling_win_rates 已算好的序列, 内部无 flat n<min_n 判断(样本数下限已去掉,
    min_n 参数仅为透传占位)。

    设计(公示): 过拟合监控核心 = 「回测预期好但实盘表现差」的偏离信号。
    对每个历史日 T, 用截至 T 的实盘 __win__ 日滚动胜率 vs 回测 __win__ 日滚动胜率偏离(pp) 映射风险分:
      dev = 实盘胜率 - 回测胜率(百分点)
      dev > +10pp  -> 低风险(实盘超预期, 10-25)
      0 ~ +10pp    -> 正常(25-45)
      -10pp ~ 0    -> 关注(50-65)
      dev < -10pp  -> 高风险(实盘显著低于回测预期, 70-95)
    返回 [{date, risk_score, level, win_rate(回测%)}], 供前端 daily 曲线。"""
    seq = []
    btw = bt_roll.get(win, []) or bt_roll.get(str(win), [])
    actw = {}
    for p in (act_roll.get(win, []) or act_roll.get(str(win), [])):
        actw[p["date"]] = p.get("win_rate")
    for p in btw:
        wr_pct = p.get("win_rate")   # 回测百分比(42.92)
        if wr_pct is None:
            continue
        b_wr = wr_pct
        a_wr = actw.get(p["date"])
        if a_wr is None:
            # 实盘缺失(该日无 index 收盘等) -> 中性 40
            sc = 40.0
        else:
            dev = a_wr - b_wr  # 百分点
            if dev > 10:
                sc = max(10, 25 - (dev - 10) * 0.5)   # 实盘超预期越多风险越低
            elif dev > 0:
                sc = 35 - dev * 1.0                    # 0~10pp -> 25-35
            elif dev > -10:
                sc = 55 - dev * 1.0                    # 0~-10pp -> 55-65
            else:
                sc = min(95, 70 - (dev + 10) * 1.5)   # <-10pp -> 70-95 高风险
        sc = max(0, min(100, sc))
        seq.append({"date": p["date"], "risk_score": round(sc),
                    "level": risk_level(sc),
                    "win_rate": round(wr_pct, 1)})
    return seq


def derive_daily_for_rolls(bt_roll, act_roll, latest_date, min_n=20):
    """对单维度 bt/act 滚动序列, 派生 WINDOWS(10/15/30/60/100)多套 daily(统计口径可切)。
    样本数下限判定随 rolling_win_rates(2026-08-17 已完全去掉), 本函数仅透传 min_n 占位。"""
    return {
        str(w): _derive_daily_series(bt_roll, act_roll, None, latest_date, win=w, min_n=min_n)
        for w in WINDOWS
    }


def _compute_bank(by_date, close_map, trades_by_date, grade_map, latest_signal, ts_map=None):
    """由（已可选过滤的）原始样本计算 accuracy + overfit 两棵子树。
    被 build_output 调用多次：未过滤(raw) + 过滤(filtered, AI宏删线层) + by_k(全信号top-K 4套) + filtered_by_k(降亏过滤后top-K 4套)。
    D2/D3/D4/象限用过滤后的 trades_by_date(保持一致, 见 §5.1/§5.4)。
    2026-08-16 窗口语义改造v2: 统计口径可切 10/15/30/60/100(默认60), 输出多套滚动序列;
    前端「显示范围」只截取最近 N 日展示(30/60/90/180), 不改变统计窗口。
    2026-08-17 方案A: ts_map={index_id: track_score|None}(board_etf_map) 传入 bucket_actual, 实盘线限定回测宇宙。"""
    # 滚动按全部候选口径各算一套(10/15/30/60/100); accuracy.rolling/daily_by_win/daily_by_dim 均多套
    _ROLL_WIN = WINDOWS
    bt_daily = bucket_backtest_trades(trades_by_date, None)
    bt_dates = sorted(bt_daily.keys())
    actual_daily = bucket_actual(by_date, close_map, latest_signal, grade_map, universe=ts_map) if by_date else []

    # 滚动窗口(total 维度)
    bt_points = [{"date": d, **bt_daily[d]} for d in bt_dates]
    actual_dates = [p["date"] for p in actual_daily]
    act_points = [{"date": p["date"], **{k: v for k, v in p.items() if k in ("total", "by_signal", "by_grade")}} for p in actual_daily]
    bt_roll = rolling_win_rates(bt_points, bt_dates, _ROLL_WIN)
    act_roll = rolling_win_rates(act_points, actual_dates, _ROLL_WIN)

    def _trim_roll(roll):
        return {str(w): seq[-SURFACE_DAYS:] for w, seq in roll.items()}

    grade_sig_keys_map = {
        "high": ["by_grade", "high"], "mid": ["by_grade", "mid"], "low": ["by_grade", "low"],
    }
    by_grade_out = {}
    for g in ("high", "mid", "low"):
        kp = grade_sig_keys_map[g]
        bt_r = rolling_win_rates(bt_points, bt_dates, _ROLL_WIN, key_path=kp)
        act_r = rolling_win_rates(act_points, [p["date"] for p in actual_daily], _ROLL_WIN, key_path=kp)
        by_grade_out[g] = {"backtest": _trim_roll(bt_r), "actual": _trim_roll(act_r)}

    sig_map_bt = {
        "buy": ["by_signal", "buy"], "buy_aux": ["by_signal", "buy_aux"],
        "buy_special": ["by_signal", "buy_special"], "buy_backup": ["by_signal", "buy_backup"],
    }
    sig_map_act = dict(sig_map_bt)
    sig_map_act.update({
        "sell": ["by_signal", "sell"], "sell_stop_loss": ["by_signal", "sell_stop_loss"],
    })
    by_signal_out = {}
    for sig in ("buy", "buy_aux", "buy_special", "buy_backup", "sell", "sell_stop_loss"):
        entry = {}
        if sig in sig_map_bt:
            bt_r = rolling_win_rates(bt_points, bt_dates, _ROLL_WIN, key_path=sig_map_bt[sig])
            entry["backtest"] = _trim_roll(bt_r)
        else:
            entry["backtest"] = {}
        if sig in sig_map_act:
            act_r = rolling_win_rates(act_points, [p["date"] for p in actual_daily], _ROLL_WIN, key_path=sig_map_act[sig])
            entry["actual"] = _trim_roll(act_r)
        else:
            entry["actual"] = {}
        by_signal_out[sig] = entry

    # 4 维过拟合。顶部综合分(current)固定 60 窗口口径=单一权威稳定值(前端只读不自算 §23.6,
    # D2/D3/D4 不随窗口, 仅 D1 窗口相关; 前端切换统计口径时仅曲线(daily_by_win/daily_by_dim)随口径重算,
    # 顶部综合分保持 60。公示见 purpose-notes/前端 tip)
    d1 = calc_d1_deviation(act_roll.get(60, []), bt_roll.get(60, []), 60)
    d2 = calc_d2_oos(trades_by_date)
    d3 = calc_d3_param(trades_by_date)
    quadrant_health = calc_quadrant_health(trades_by_date, 60)
    d4 = calc_d4_quadrant(trades_by_date, 60)
    risk, risk_detail = compute_risk(d1, d2, d3, d4)

    out = {
        "accuracy": {
            "backtest_daily": {d: {"n": bt_daily[d]["total"]["n"], "win": bt_daily[d]["total"]["win"],
                                   "win_rate": bt_daily[d]["total"]["win_rate"]} for d in bt_dates[-SURFACE_DAYS:]},
            "actual_daily": [{"date": p["date"], "n": p["total"]["n"], "win": p["total"]["win"],
                              "win_rate": p["total"]["win_rate"]}
                             for p in actual_daily if p.get("date") <= latest_signal][-SURFACE_DAYS:],
            "rolling": {
                "backtest": {str(w): roll[-SURFACE_DAYS:] for w, roll in bt_roll.items()},
                "actual": {str(w): roll[-SURFACE_DAYS:] for w, roll in act_roll.items()},
                "by_signal": {
                    sig: {"backtest": by_signal_out[sig]["backtest"], "actual": by_signal_out[sig]["actual"]}
                    for sig in ("buy", "buy_aux", "buy_special", "buy_backup", "sell", "sell_stop_loss")
                },
                "by_grade": {
                    g: {"backtest": by_grade_out[g]["backtest"], "actual": by_grade_out[g]["actual"]}
                    for g in ("high", "mid", "low")
                },
            },
        },
        "overfit": {
            "current": {
                "date": latest_signal,
                "d1": d1, "d2": d2, "d3": d3, "d4": d4,
                "risk_score": risk, "level": risk_level(risk),
                "weighted": risk_detail["weighted"],
            },
            "daily": _derive_daily_series(bt_roll, act_roll, risk, latest_signal, win=60)[-SURFACE_DAYS:],
            "daily_by_win": {
                # 统计口径多套(10/15/30/60/100), 前端按选中口径换 key 读取 → 两图随口径重算
                str(w): _derive_daily_series(bt_roll, act_roll, risk, latest_signal, win=w)[-SURFACE_DAYS:]
                for w in WINDOWS
            },
            "daily_by_dim": {
                "grade": {
                    g: {
                        str(w): _derive_daily_series(
                            by_grade_out[g]["backtest"], by_grade_out[g]["actual"],
                            risk, latest_signal, win=w)[-SURFACE_DAYS:]
                        for w in WINDOWS
                    }
                    for g in ("high", "mid", "low")
                },
                "sig_type": {
                    sig: {
                        str(w): _derive_daily_series(
                            by_signal_out[sig]["backtest"], by_signal_out[sig]["actual"],
                            risk, latest_signal, win=w)[-SURFACE_DAYS:]
                        for w in WINDOWS
                    }
                    for sig in ("buy", "buy_aux", "buy_special", "buy_backup", "sell", "sell_stop_loss")
                },
            },
            "quadrant_health": quadrant_health,
        },
    }
    return out


def build_output(rebuild=False, dry_run=False):
    conn_ok = True
    try:
        conn = sqlite3.connect(find_db())
        conn.row_factory = sqlite3.Row
    except Exception as e:  # noqa: BLE001
        print(f"⚠ DB 连接失败: {e}", file=sys.stderr)
        conn_ok = False
        conn = None

    if conn_ok:
        by_date_raw = load_signal_daily(conn)
        close_map = load_index_close(conn)
    else:
        by_date_raw, close_map = {}, {}
    trades_by_date_raw, trades_generated = load_trades()
    market_map = load_market_map()

    latest_signal = max(by_date_raw.keys()) if by_date_raw else "0"

    # 实盘评级(与回测同源阈值 0.75/0.55, 当前10d.score 分档)
    grade_map = load_signal_grade_map()

    # AI 宏过滤上下文(board_etf_map track_score + hs300 MA60 bull + market_map)
    ctx = FilterCtx(market_map,
                    ts_map=load_board_etf_track_score(),
                    bull_state=build_market_state_hs300(close_map),
                    tier_map=load_board_etf_track_tier())

    # 两棵 bank: 未过滤(现状) + 过滤(AI宏删线层) —— 前端「AI降亏过滤」开关切换读取
    bank_raw = _compute_bank(by_date_raw, close_map, trades_by_date_raw, grade_map, latest_signal,
                             ts_map=ctx.ts_map)
    if conn_ok:
        by_date_filt = filter_actual_by_date(by_date_raw, ctx, grade_map)
    else:
        by_date_filt = {}
    trades_by_date_filt = filter_trades_by_date(trades_by_date_raw, ctx, mode_filt=AFG_MODES)
    bank_filt = _compute_bank(by_date_filt, close_map, trades_by_date_filt, grade_map, latest_signal,
                              ts_map=ctx.ts_map)

    # K 档(2026-08-16): K 档 × 降亏开关两开关独立(用户拍板修正) —— 前端:
    #   降亏开 + K 档 = filtered_by_k[k](降亏过滤人口 top-K); 降亏关 + K 档 = by_k[k](全信号人口 top-K)。
    #   by_k 与 filtered_by_k 各有 K=1..4 一套, 共 8 套; K 独立可用不依赖降亏开关(与首页/Lab 语义对齐 §23.6)。
    K_ALLOWED = [1, 2, 3, 4]
    by_k = {}
    filtered_by_k = {}
    for k in K_ALLOWED:
        # 全信号人口 top-K(降亏关): 由原始 by_date_raw 选 top-K
        kept_raw = build_topk_kept_map(by_date_raw, ctx, grade_map, k)
        by_date_raw_k = filter_by_date_by_kept(by_date_raw, kept_raw) if conn_ok else {}
        trades_raw_k = filter_trades_by_kept(trades_by_date_raw, kept_raw)
        by_k[str(k)] = _compute_bank(by_date_raw_k, close_map, trades_raw_k, grade_map, latest_signal,
                                     ts_map=ctx.ts_map)
        # 降亏过滤人口 top-K(降亏开): 由过滤后 by_date_filt 选 top-K
        kept_filt = build_topk_kept_map(by_date_filt, ctx, grade_map, k)
        by_date_filt_k = filter_by_date_by_kept(by_date_filt, kept_filt)
        trades_filt_k = filter_trades_by_kept(trades_by_date_filt, kept_filt)
        filtered_by_k[str(k)] = _compute_bank(by_date_filt_k, close_map, trades_filt_k, grade_map, latest_signal,
                                              ts_map=ctx.ts_map)

    # 预警主口径 = 未过滤的风险分(现状行为不变); filtered 仅作前端对比数据
    d1 = bank_raw["overfit"]["current"]["d1"]
    d2 = bank_raw["overfit"]["current"]["d2"]
    d3 = bank_raw["overfit"]["current"]["d3"]
    d4 = bank_raw["overfit"]["current"]["d4"]
    risk = bank_raw["overfit"]["current"]["risk_score"]

    prev = load_prev_state()
    prev_scores = [s.get("risk_score") for s in prev.get("overfit", {}).get("daily", [])
                   if s.get("risk_score") is not None]
    today = date_cls.today().strftime("%Y%m%d")
    alerts = evaluate_alerts(risk, prev_scores, d1, d2, d3, d4, latest_signal)

    # 构造输出
    out = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "version": "v2",
        "config": {
            "default_k": DEFAULT_K, "modes": AFG_MODES, "overfit_mode": OVERFIT_MODE,
            "windows": WINDOWS, "weights": {"d1": W_D1, "d2": W_D2, "d3": W_D3, "d4": W_D4},
            "data_sources": {
                "backtest": "signal_kelly_trades.json", "actual": "signal_daily+index_daily",
                "trades_generated_at": trades_generated,
                "signal_daily_max_date": latest_signal,
            },
            "ai_filter": {
                "version": "v1.1.0",
                "rule_count": 9,
                "desc": "AI宏删线层: 8键(基础5+核心3)+1类(未入样本 _bt_in_universe)。开关开启时监控只统计未命中删线的信号。",
            },
            "topk": {
                "desc": "K档 × 降亏开关两开关独立(2026-08-16): by_k=全信号人口top-K, filtered_by_k=降亏过滤人口top-K(降亏开用)。排序口径=track_score DESC→评级→信号类型, 与首页AI建议top-K同源(§23.6)。K独立可用不依赖降亏开关。",
                "k_allowed": [1, 2, 3, 4],
            },
            "recent": {
                "desc": "T3-2(2026-08-23) 近N日逐信号明细(每键命中标注+回测A/F/G胜负+实盘胜负), 供监控卡7模式下拉前端组集。键命中=v1.1.2四档口径(与首页/凯利同源); 老filtered bank仍为MA60口径(历史遗留待用户拍板)。信号级子集: price_bin/ETF相关性组件不可判降级跳过。",
                "days": RECENT_DAYS,
                "tier_codes": {"0": "非A股类/无数据", "1": "牛市·主升", "2": "上升期", "3": "下降期", "4": "熊市·主跌"},
            },
        },
    }
    out["accuracy"] = bank_raw["accuracy"]
    out["overfit"] = bank_raw["overfit"]
    # 修复(2026-08-24, 用户拍板): B拆分 commit 70163b663 误删主文件 filtered 挂载——拆分前
    # L1643 本为 out["filtered"] = bank_filt, 注释声明「filtered 留主文件」却无赋值, 致
    # 「降亏开+无K档」默认路径(app.js _ovFade)读到全信号人口而非过滤人口(check_overfit_split_parity
    # L101 断言 main 含 filtered 当时未挂自动链故未拦)。现恢复同构挂载(bank_filt 整体, 与拆分前一致),
    # parity 校验同批挂 deploy.sh 1.2.2 + overfit_monitor.sh 打点链防再犯。
    out["filtered"] = bank_filt
    # B拆分(2026-08-24): by_k/filtered_by_k 不再挂主文件, 单独落 OUT_EXT_JSON(K档交互专用,
    # 默认首屏零消费); filtered 留主文件——它是「降亏开+无K档」默认路径 bank(app.js _ovBank
    # L2204, 调研报告 §2.4 实测), 拆走会致老数据过渡期/组集回退场景首屏多一次拉取。
    ext_out = {
        "generated_at": out["generated_at"],
        "version": out["version"],
        "desc": "K档扩展bank(by_k=全信号人口top-K / filtered_by_k=降亏过滤人口top-K), 与主文件 "
                "overfit_monitor.json 同一次打点产出(generated_at 对齐); 仅前端 K档×{p8对照/组集失败/降亏关} "
                "组合按需拉取。拆分前数值逐位一致校验: scripts/check_overfit_split_parity.py",
        "by_k": by_k,
        "filtered_by_k": filtered_by_k,
    }

    # T3-2(2026-08-23) recent 明细块: 近 RECENT_DAYS 日逐信号打点(每键命中+回测/实盘胜负),
    # 供前端监控卡 7 模式下拉组集(键命中是后端打的标记; 前端只组集所选模式的键集合,
    # 聚合链一致性由 scripts/check_overfit_recent_parity.mjs 断言与 bank raw 口径逐位对照)。
    try:
        tier_map, ma60_map = load_market_tier_map()
        lr_mod, lr_feat = load_loss_rules_recent()
        out["recent"] = build_recent_block(by_date_raw, close_map, trades_by_date_raw, grade_map,
                                           latest_signal, ctx, tier_map, ma60_map, lr_mod, lr_feat)
        print(f"   recent 明细块: {len(out['recent']['rows'])} 行(近 {RECENT_DAYS} 日, "
              f"{sum(1 for r in out['recent']['rows'] if r['k'])} 行带键)")
    except Exception as e:  # noqa: BLE001
        out["recent"] = None   # 明细失败不阻断主产物(前端回退现有 bank)
        print(f"⚠ recent 明细块生成失败(前端回退现有 bank): {e}", file=sys.stderr)

    # 体积控制日志
    print(f"   accuracy.rolling.by_signal {[s for s in out['accuracy']['rolling']['by_signal']]}")
    print(f"   accuracy.rolling.by_grade {[g for g in out['accuracy']['rolling']['by_grade']]} (维度裁剪 {SURFACE_DAYS} 天)")

    # 写文件(A瘦身 2026-08-24): indent=2 → compact separators。indent 纯缩进空格占 64% 体积
    # (线上实测 26.6MB→9.7MB compact), br 压缩后传输同步下降; 字段/数值零变化(json.load 无感)。
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    tmp = OUT_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, OUT_JSON)
    # B拆分(2026-08-24): ext 文件同 compact 口径落盘(by_k/filtered_by_k), 与主文件同一次打点。
    tmp2 = OUT_EXT_JSON + ".tmp"
    with open(tmp2, "w", encoding="utf-8") as f:
        json.dump(ext_out, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp2, OUT_EXT_JSON)
    print(f"✅ overfit_monitor.json 已写: {OUT_JSON} (compact)")
    print(f"✅ overfit_monitor_ext.json 已写: {OUT_EXT_JSON} (by_k/filtered_by_k 拆分)")

    # 视图摘要
    bt60 = out["accuracy"]["rolling"]["backtest"].get("60", [])
    act60 = out["accuracy"]["rolling"]["actual"].get("60", [])
    print(f"   回测口径近60滚动胜率(末点): {bt60[-1] if bt60 else 'N/A'}")
    print(f"   实盘口径近60滚动胜率(末点): {act60[-1] if act60 else 'N/A'}")
    print(f"   D1={d1} D2={d2} D3={d3} D4={d4} 综合={risk} 等级={risk_level(risk)}")

    # 预警通知
    if alerts:
        for a in alerts:
            print(f"   ⚠ 触发预警: {a['type']} ({a['level']})")
        if not dry_run:
            # SEVERE 优先发; warn 也发(不轰炸: 同类型 24h dedup)
            for a in alerts:
                dedup = "overfit_" + a["type"]
                ok, err = send_notify(a["subject"], a["body"], a["level"],
                                      dry_run=dry_run, dedup_key=dedup)
                a["sent"] = ok
                a["notify_error"] = err if not ok else None
                print(f"   {a['type']}: 发送{'成功' if ok else '失败'} {('dry-run' if dry_run else '')}")
        else:
            for a in alerts:
                a["sent"] = False
                a["notify_error"] = "dry_run"
        out["alerts"] = alerts
    else:
        print("   无触发预警")

    # 回写包含 sent 状态(A瘦身: 同 compact 口径; ext 文件不含 alerts 无需回写)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, OUT_JSON)
    if alerts:
        print(f"   (预警记录已回写 {len(alerts)} 条)")

    # R2 上传(§22 三步同步: overfit_monitor 主+ext 两文件走 R2 data/ 前缀, static-site/data 已 gitignore)
    # deploy 链 upload-data-large 含 overfit_monitor* 强制例外(startswith 前缀, B拆分后含 _ext);
    # 独立打点时也自传, 保证线上立即可见。upload-data-large 上传后对 overfit_monitor*.json 以
    # cache_prefix="/" purge /data/ rewrite 路由 edge 缓存(C 件套补偿: 该两文件已挪 MED 600s,
    # 「重跑立即看」靠 purge 保证, 见 headers.js dataCacheTtl 沿革注释)。
    # deploy.sh 已 RUN_R2 时经 ENV OVERFIT_SKIP_R2=1 跳过, 防重复(repo=deploy 语义同 EXPORT_SKIP_R2)。
    if not dry_run and os.environ.get("OVERFIT_SKIP_R2") != "1":
        try:
            import subprocess as _sp
            # ⚠ 必须传 REPO=trade-data: upload_r2 的 ROOT 经 .resolve() 解析到 trade/(trade-data/scripts
            # 是 trade/scripts symlink), 不传则读 trade/static-site/data(旧版), 与本脚本写盘
            # trade-data/static-site/data(新版) 不一致(§22 三步同步, L33 STATIC_DIR=REPO/static-site)。
            # 统一 helper force_env(防再犯机制 E): 强制覆盖 REPO/GIT_REPO, 不用 setdefault。
            _env = force_env(dict(os.environ), REPO)
            r = _sp.run(
                [sys.executable, os.path.join(SCRIPT_DIR, "upload_r2.py"), "upload-data-large"],
                capture_output=True, text=True, timeout=120, env=_env)
            if r.returncode == 0:
                print("   overfit_monitor.json → R2 上传完成")
            else:
                print(f"   ⚠ R2 上传失败(rc={r.returncode}): {r.stderr[-300:]}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"   ⚠ R2 上传异常: {e}", file=sys.stderr)
    return out


def main():
    parser = argparse.ArgumentParser(description="过拟合监控每日打点 + 系維指标")
    parser.add_argument("--rebuild", action="store_true", help="全量历史回算(一次性, 建曲线)")
    parser.add_argument("--dry-run", action="store_true", help="不打点, 试评估+试发预警")
    args = parser.parse_args()
    build_output(rebuild=args.rebuild, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
