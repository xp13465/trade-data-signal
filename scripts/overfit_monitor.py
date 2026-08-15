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
  信号日收盘->最新收盘上涨 = 对; 看空(sell/sell_stop_loss)下跌 = 对; band_hold 中性不计。与首页 _calcSignalAccuracy 同口径。
- 4 维过拟合风险分(0-100): risk_score = 0.40*D1(回测-实盘偏离) + 0.25*D2(滚动样本外衰减) + 0.20*D3(参数稳定) + 0.15*D4(象限退化)。
  等级: 绿 <30(正常) / 黄 30-60(关注) / 红 >60(高风险)。
- 各维度按滚动窗口 w30/w60/w90 加权偏重最新(30 灵敏 / 90 稳健)。

输入依赖
--------
- DB: ${REPO}/data/sentiment.db(signal_daily 信号权威历史 / index_daily 指数收盘价)
- JSON: static-site/data/signal_kelly_trades.json(回测成交明细, 2011-2026, 16 象限 x 9 模式)
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
import json
import os
import sqlite3
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, date as date_cls

import yaml

# ── 路径 ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))   # trade-data/scripts/
REPO = os.path.dirname(SCRIPT_DIR)                        # trade-data/
sys.path.insert(0, SCRIPT_DIR)

# ── 常量 ──────────────────────────────────────────────────────────────────────
BUY_SIGNALS = ("buy", "buy_aux", "buy_special", "buy_backup")
SELL_SIGNALS = ("sell", "sell_stop_loss")
AFG_MODES = ["A", "F", "G"]
WINDOWS = [30, 60, 90]
DEFAULT_K = 1
OVERFIT_MODE = "G"        # 主展示/预警口径的卖出模式(用户主推 G = 信号驱动卖出)
SURFACE_DAYS = 365        # 维度滚动曲线体积裁剪窗口(现 365 天, 足够画长曲线; total 仍 730)
# 4 维权重
W_D1, W_D2, W_D3, W_D4 = 0.40, 0.25, 0.20, 0.15

OUT_JSON = os.path.join(REPO, "static-site", "data", "overfit_monitor.json")

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


def load_signal_daily(conn):
    """读 signal_daily 全表 -> [{'date','index_id','signal'}], 按日聚合。"""
    rows = conn.execute(
        "SELECT date, index_id, signal FROM signal_daily ORDER BY date"
    ).fetchall()
    by_date = defaultdict(list)
    for r in rows:
        by_date[r[0]].append({"index_id": r[1], "signal": r[2]})
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

    # trade_tier/字段: ['signal_date','index_id','signal','buy_date','sell_date','etf_code',
    #   'etf_name','track_tier','track_score','match_method','track_low_confidence',
    #   'buy_price','sell_price','shares','profit','return_pct','hold_days',
    #   'sell_reason','current_price','market_state','rating']
    FIELD = ["signal_date", "index_id", "signal", "buy_date", "sell_date", "etf_code",
             "etf_name", "track_tier", "track_score", "match_method", "track_low_confidence",
             "buy_price", "sell_price", "shares", "profit", "return_pct", "hold_days",
             "sell_reason", "current_price", "market_state", "rating"]
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
                    "quad": qname,
                })
    return by_date, data.get("generated_at", "")


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


def bucket_actual(by_date, close_map, latest_date, grade_map=None):
    """实盘口径按日打点: 信号日收盘 -> 最新收盘方向。与首页 since_correct 同口径。
    returns {date: {total, by_mode(占位), by_signal, by_grade}}
    """
    out = []
    all_dates = sorted(by_date.keys())
    # 最新可用收盘日(末日兜底)
    latest_close = {}
    for iid, m in close_map.items():
        if m:
            latest_close[iid] = m[max(m.keys())]
    grade_map = grade_map or {}
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
                continue  # 今日信号无"至今"语义(与 queries.py L914-916 一致)
            since_ret = (today_close - sig_close) / sig_close
            is_win = (since_ret < 0) if (sig in SELL_SIGNALS) else (since_ret > 0)
            n += 1
            if is_win:
                win += 1
            _bucket_add(by_signal[sig], is_win)
            g = grade_map.get((iid, sig))
            if g in ("high", "mid", "low"):
                _bucket_add(by_grade[g], is_win)
        if n > 0:
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
            # 跳过样本不足(早期窗口不满 / 该维度样本稀疏) -> win_rate=None
            if n < min_n:
                seq.append({"date": p["date"], "n": n, "win_rate": None})
                continue
            seq.append({"date": p["date"], "n": n, "win_rate": (win / n * 100) if n else None})
        out[w] = seq
    return out


def rolling_win_rates_by_dim(bt_buckets, act_buckets, bt_keys, act_keys, windows=WINDOWS, min_n=20):
    """多个维度的滚动聚合: {key: {bt: {w:[..]}, act: {w:[..]}}}。
    bt_buckets: {date: bt_daily[d]}   act_buckets: [ {date,total,by_signal,by_grade} ]
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
    """对单维度 bt/act 滚动序列, 派生 30/60/90 三套 daily(支持风险分窗口切换)。"""
    return {
        str(w): _derive_daily_series(bt_roll, act_roll, None, latest_date, win=w, min_n=min_n)
        for w in WINDOWS
    }


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
        by_date = load_signal_daily(conn)
        close_map = load_index_close(conn)
    else:
        by_date, close_map = {}, {}
    trades_by_date, trades_generated = load_trades()
    market_map = load_market_map()

    latest_signal = max(by_date.keys()) if by_date else "0"

    # 回测口径每日打点(按 signal_date)
    bt_daily = bucket_backtest_trades(trades_by_date, None)
    bt_dates = sorted(bt_daily.keys())
    # 实盘口径每日打点(grade_map = signal_stats 当前10d.score分档, 见 load_signal_grade_map)
    grade_map = load_signal_grade_map()
    actual_daily = bucket_actual(by_date, close_map, latest_signal, grade_map) if conn_ok else []

    # 滚动窗口(回测口径, 主展示 = 实盘 vs 回测) —— total 维度, 保留现状结构
    # 注意: points 需携带完整桶(total/by_signal/by_grade), rolling_win_rates 用 key_path 取子维度。
    bt_points = [{"date": d, **bt_daily[d]} for d in bt_dates]
    actual_dates = [p["date"] for p in actual_daily]
    act_points = [{"date": p["date"], **{k: v for k, v in p.items() if k in ("total", "by_signal", "by_grade")}} for p in actual_daily]
    bt_roll = rolling_win_rates(bt_points, bt_dates, WINDOWS)
    act_roll = rolling_win_rates(act_points, actual_dates, WINDOWS)

    # 维度滚动(需求1: 信号评级 + 信号类型): 裁剪到最近 SURFACE_DAYS(体积控制)
    def _trim_roll(roll):
        return {str(w): seq[-SURFACE_DAYS:] for w, seq in roll.items()}

    # 评级: high/mid/low(回测含, 实盘含)
    grade_keys = [["by_grade", "high"], ["by_grade", "mid"], ["by_grade", "low"]]
    grade_sig_keys_map = {
        "high": ["by_grade", "high"], "mid": ["by_grade", "mid"], "low": ["by_grade", "low"],
    }
    by_grade_out = {}
    for g in ("high", "mid", "low"):
        kp = grade_sig_keys_map[g]
        bt_r = rolling_win_rates(bt_points, bt_dates, WINDOWS, key_path=kp)
        act_r = rolling_win_rates(act_points, [p["date"] for p in actual_daily], WINDOWS, key_path=kp)
        by_grade_out[g] = {
            "backtest": _trim_roll(bt_r),
            "actual": _trim_roll(act_r),
        }
    # 信号: 回测 4 种 buy 类; 实盘 6 种(含 sell)
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
            bt_r = rolling_win_rates(bt_points, bt_dates, WINDOWS, key_path=sig_map_bt[sig])
            entry["backtest"] = _trim_roll(bt_r)
        else:
            entry["backtest"] = {}
        if sig in sig_map_act:
            act_r = rolling_win_rates(act_points, [p["date"] for p in actual_daily], WINDOWS, key_path=sig_map_act[sig])
            entry["actual"] = _trim_roll(act_r)
        else:
            entry["actual"] = {}
        by_signal_out[sig] = entry

    # 4 维过拟合
    d1 = calc_d1_deviation(act_roll.get(60, []), bt_roll.get(60, []), 60)
    d2 = calc_d2_oos(trades_by_date)
    d3 = calc_d3_param(trades_by_date)
    quadrant_health = calc_quadrant_health(trades_by_date, 60)
    d4 = calc_d4_quadrant(trades_by_date, 60)
    risk, risk_detail = compute_risk(d1, d2, d3, d4)

    # 预警: 读上次风险分数列
    prev = load_prev_state()
    prev_scores = [s.get("risk_score") for s in prev.get("overfit", {}).get("daily", [])
                   if s.get("risk_score") is not None]
    today = date_cls.today().strftime("%Y%m%d")
    alerts = evaluate_alerts(risk, prev_scores, d1, d2, d3, d4, latest_signal)

    # 构造输出
    out = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "version": "v1",
        "config": {
            "default_k": DEFAULT_K, "modes": AFG_MODES, "overfit_mode": OVERFIT_MODE,
            "windows": WINDOWS, "weights": {"d1": W_D1, "d2": W_D2, "d3": W_D3, "d4": W_D4},
            "data_sources": {
                "backtest": "signal_kelly_trades.json", "actual": "signal_daily+index_daily",
                "trades_generated_at": trades_generated,
                "signal_daily_max_date": latest_signal,
            },
        },
        "accuracy": {
            # 体积优化(2026-08-15): backtest_daily/actual_daily 前端只用 rolling 曲线,
            # 明细多维(by_mode/by_signal)仅用于离线 D 维度计算, 不留前端产物体。保留 total 供回溯。
            "backtest_daily": {d: {"n": bt_daily[d]["total"]["n"], "win": bt_daily[d]["total"]["win"],
                                   "win_rate": bt_daily[d]["total"]["win_rate"]} for d in bt_dates[-730:]},
            "actual_daily": [{"date": p["date"], "n": p["total"]["n"], "win": p["total"]["win"],
                              "win_rate": p["total"]["win_rate"]}
                             for p in actual_daily if p.get("date") <= latest_signal][-730:],
            "rolling": {
                # 前端只用滚动曲线, 全史点(backtest 1560/actual 6484)体积大。裁剪到最近 730 交易日
                # (与 daily 一致, 足够画长曲线)。D 维度用裁剪前完整 rolling 已算, 不受影响。
                "backtest": {str(w): roll[-730:] for w, roll in bt_roll.items()},
                "actual": {str(w): roll[-730:] for w, roll in act_roll.items()},
            },
        },
        "overfit": {
            "current": {
                "date": latest_signal,
                "d1": d1, "d2": d2, "d3": d3, "d4": d4,
                "risk_score": risk, "level": risk_level(risk),
                "weighted": risk_detail["weighted"],
            },
            "daily": _derive_daily_series(bt_roll, act_roll, risk, latest_signal, win=60)[-730:],
            # 风险分窗口切换(需求3): total 派生 30/60/90 三套 daily
            "daily_by_win": {
                str(w): _derive_daily_series(bt_roll, act_roll, risk, latest_signal, win=w)[-SURFACE_DAYS:]
                for w in WINDOWS
            },
            # 风险分维度切换(需求1): 各评级/信号维度 60 窗口派生(复用 _derive_daily_series)
            "daily_by_dim": {
                "grade": {
                    g: _derive_daily_series(
                        by_grade_out[g]["backtest"], by_grade_out[g]["actual"],
                        risk, latest_signal, win=60)[-SURFACE_DAYS:]
                    for g in ("high", "mid", "low")
                },
                "sig_type": {
                    sig: _derive_daily_series(
                        by_signal_out[sig]["backtest"], by_signal_out[sig]["actual"],
                        risk, latest_signal, win=60)[-SURFACE_DAYS:]
                    for sig in ("buy", "buy_aux", "buy_special", "buy_backup", "sell", "sell_stop_loss")
                },
            },
            "quadrant_health": quadrant_health,
        },
    }
    # 维度滚动写进 accuracy(需求1): by_signal / by_grade
    out["accuracy"]["rolling"]["by_signal"] = {
        sig: {"backtest": by_signal_out[sig]["backtest"], "actual": by_signal_out[sig]["actual"]}
        for sig in ("buy", "buy_aux", "buy_special", "buy_backup", "sell", "sell_stop_loss")
    }
    out["accuracy"]["rolling"]["by_grade"] = {
        g: {"backtest": by_grade_out[g]["backtest"], "actual": by_grade_out[g]["actual"]}
        for g in ("high", "mid", "low")
    }
    # 体积控制日志(维度 rolling 裁剪到 SURFACE_DAYS)
    print(f"   accuracy.rolling.by_signal {[s for s in by_signal_out]}")
    print(f"   accuracy.rolling.by_grade {[g for g in by_grade_out]} (维度裁剪 {SURFACE_DAYS} 天)")

    # 写文件
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    tmp = OUT_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OUT_JSON)
    print(f"✅ overfit_monitor.json 已写: {OUT_JSON}")

    # 视图摘要
    print(f"   回测口径近60滚动胜率(末点): {bt_roll.get(60, [])[-1] if bt_roll.get(60) else 'N/A'}")
    print(f"   实盘口径近60滚动胜率(末点): {act_roll.get(60, [])[-1] if act_roll.get(60) else 'N/A'}")
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

    # 回写包含 sent 状态
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OUT_JSON)
    if alerts:
        print(f"   (预警记录已回写 {len(alerts)} 条)")

    # R2 上传(§22 三步同步: overfit_monitor 走 R2 data/ 前缀, static-site/data 已 gitignore)
    # deploy 链 upload-data-large 含 overfit_monitor 强制例外; 独立打点时也自传, 保证线上立即可见。
    # deploy.sh 已 RUN_R2 时经 ENV OVERFIT_SKIP_R2=1 跳过, 防重复(repo=deploy 语义同 EXPORT_SKIP_R2)。
    if not dry_run and os.environ.get("OVERFIT_SKIP_R2") != "1":
        try:
            import subprocess as _sp
            # ⚠ 必须传 REPO=trade-data: upload_r2 的 ROOT 经 .resolve() 解析到 trade/(trade-data/scripts
            # 是 trade/scripts symlink), 不传则读 trade/static-site/data(旧版), 与本脚本写盘
            # trade-data/static-site/data(新版) 不一致(§22 三步同步, L33 STATIC_DIR=REPO/static-site)。
            _env = dict(os.environ)
            _env["REPO"] = REPO
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
