#!/usr/bin/env python3
"""nextday_plan_generator.py - 次日买入计划生成器(PRD 阶段一 §3/§6, 干跑模式 AUTO_EXEC_ON=false)

目的:
    每天盘后(launchd com.trade.nextday-plan)生成次日(T+1)买入计划:
      ①复用首页 AI建议同一条选取链(K=1 每日 top1)选出当日信号, 输出 data/nextday_plan.json
      ②把计划写进 static-site/data/auto_trade_steps.json(行为级状态机, seq1 挂单行为 pending,
        §6.2 全字段)
      ③同步两树 static-site/data/ + R2(upload_r2 upload-data-files, §22 三步同步)
      ④通知(邮件+飞书, 复用 notify.send 链路)
    干跑模式: 本阶段只生成计划+通知书, 不连 easytrader 不真实下单(AUTO_EXEC_ON=false, PRD §8/§9)。

方法口径(2026-09-10 方案A根治, 设计缺口: 原实现从 signal_kelly_trades.json 选 signal_date==T,
但主回测 KELLY_BUY_NEXTDAY=1 口径下买价=次日开盘价, 今日信号永远不在 trades 里 → 定时跑必出
空计划误导。方案A(用户拍板): 生成器改走首页同一条路 = signal_daily 当日信号 + 冻结表 top1 ETF):
    - 信号源 = sentiment.db signal_daily 当日(T)全部信号, 排除 s.* 情绪分(与首页查询
      app/queries.py L1123-1128 一致), 再只取买信号 BUY_SIGNALS={buy,buy_aux,buy_special,
      buy_backup}(buy_special_filtered 归一为 buy_special, 与 queries._AI_MACRO_BUY_SIGNALS 一致)
    - top1 判定 = 冻结表 data/signal_kelly_etf_freeze.json(key=date|index_id|signal)命中
      → 冻结 code 为权威 top1(_bk_top); 未命中 → 前端 _topEtfByScore 同构(纯 max(track_score),
      平手回退 similarity)。track_score 取 board_etf_map 注入值(与首页 overview 逐位一致)。
    - 降亏过滤 = 首页同款(queries._ai_macro_hit_filters, ctx 与 overview 完全同构) ∩ S06
      基座成员集(s06.filters_for_date(T) True 键; 快照缺行 fail-open 放行)。a9 基座补
      bullAuxBackupStop 前端分支(buy_aux/buy_backup × hs300 四档=牛市·主升)。
    - K=1 保留 = kelly 排序准则(track_score DESC → rating high>mid>low → signal
      buy_backup>buy>buy_aux>buy_special → buy_date ASC), 与首页 AI建议 top1 一致。
    - buy_date = T 的下一个交易日(权威交易日历 data/trade_dates.txt, §11.4 长假处理)
    - prev_close = 该 etf T 日收盘(etf_daily, 即挂单价上限; 与首页 etf_close 同源同口径)
    - amount = 每日资金池 1 万等分(K=1 即 1 万)
    - 双校验: ① prev_close>0 非停牌(该 etf 前一日有成交) ② prev_close vs 信号日收盘 ±20% 内
      (伪跳空剔除同款, 防除权/份额折算错位; 信号日收盘 = etf_daily 该 etf T 日 close)

输入依赖:
    - <REPO>/data/sentiment.db signal_daily  (当日信号, 首页同源)
    - <REPO>/data/signal_kelly_etf_freeze.json(冻结表, key=date|index_id|signal → top1 ETF)
    - <REPO>/data/signal_stats.json           (评级 10d score, 首页同源)
    - <REPO>/config/indicators.yaml          (指数 market 归类, 首页同源)
    - <REPO>/static-site/data/kelly_mode_s06_state.json(S06 动态基座快照, 20:35 每日重生)
    - <REPO>/static-site/data/kelly_loss_features.json(降亏特征, ai_macro 内部读取)
    - <REPO>/data/board_etf_map.json         (每信号 ETF 候选映射, 首页同源)
    - <REPO>/data/etf_national_team.db etf_daily(取标的 T 日收盘 -> 挂单价上限 + 交易日集合)
    - <REPO>/data/trade_dates.txt            (权威交易日历, buy_date 下一交易日)
输出:
    - data/nextday_plan.json(本地权威: {date, plan:[{etf_code,etf_name,prev_close,amount,signal,track_score,signal_date,buy_date}]}; 空计划 {date, empty:true})
    - static-site/data/nextday_plan.json(用户页面可见, 同内容)
    - static-site/data/auto_trade_steps.json({schema_version:"v1", steps:[...]}, 追加模式幂等: 同 date 已存在则跳过)
关键参数(常量, 与 kelly_posrating/前端逐位对齐, 改参数必须同步 §22):
    - K=1, BUY_AMOUNT=10000, PSEUDO_GAP=0.20(伪跳空剔除阈值同 signal_kelly_backtest.PSEUDO_GAP_EXCLUDE)
复现命令:
    REPO=/Users/linhuichen/code/trade-data GIT_REPO=/Users/linhuichen/code/trade python3 scripts/nextday_plan_generator.py --date 20260910 --dry-run
    # --dry-run 只计算打印不落盘不发通知(自测); 无 --date 取今天; 无 --dry-run 会落盘两树+R2+通知
    REPO=/Users/linhuichen/code/trade-data GIT_REPO=/Users/linhuichen/code/trade python3 scripts/nextday_plan_generator.py   # launchd 同款(真跑)
    # 数据未就绪退出非 0(退出码 2), 可 NEXTDAY_PLAN_FORCE=1 强制跳过(不推荐, 防误导空计划)
"""
import argparse
import json
import os
import subprocess
import sys
import sqlite3
from datetime import datetime, date
from pathlib import Path

# 运行根: 显式 REPO 优先(trade-data 运行副本), 缺省回退脚本所在仓
ROOT = Path(__file__).resolve().parent.parent
REPO = Path(os.environ.get("REPO", str(ROOT)))
GIT_REPO = Path(os.environ.get("GIT_REPO", str(ROOT)))
PY = os.environ.get("PY", str(REPO / ".venv" / "bin" / "python"))
SCRIPT_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(REPO))  # 优先 REPO(实时数据侧; app 经 symlink 读 trade, __file__ 不 resolve → data 路径落 REPO)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

import kelly_posrating as kp  # noqa: E402  (复用 S06Resolver + _tds_fade_spec_hit(bullAuxBackupStop))
from app import queries as appq  # noqa: E402  (首页 AI建议同款: etf_for/_etf_freeze/_align_home_top1_to_backtest/_ai_macro_*)
from app.collector.fetchers import load_config  # noqa: E402  (indicators.yaml indicator.market 归类)

K = 1                       # K 档(每日 top1, 与首页 AI仓位建议默认 K=1 一致)
BUY_AMOUNT = 10000          # 每日资金池 1 万等分
PSEUDO_GAP = 0.20           # 伪跳空剔除阈值(与 signal_kelly_backtest.PSEUDO_GAP_EXCLUDE 同款)
LOG_TAG = "[nextday_plan]"
BUY_SIGNALS = {"buy", "buy_aux", "buy_special", "buy_backup"}  # 与 queries._AI_MACRO_BUY_SIGNALS 同源
_RATING_RANK = {"high": 0, "mid": 1, "low": 2, "": 3}
_SIG_RANK = {"buy_backup": 0, "buy": 1, "buy_aux": 2, "buy_special": 3, "": 9}


def log(msg):
    print(f"{LOG_TAG} {msg}", flush=True)


def _load_json(name: str, base: Path):
    p = base / name
    if not p.exists():
        raise FileNotFoundError(f"输入产物缺失: {p}")
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def _etf_daily_dates(db_path: Path) -> list[str]:
    """etf_daily 全部交易日(升序)。etf_daily 只含历史有行情日期(不含未来)。"""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        cur.execute("SELECT DISTINCT date FROM etf_daily ORDER BY date")
        return [r[0] for r in cur.fetchall()]
    finally:
        con.close()


def _trade_calendar_dates(db_path: Path) -> list[str]:
    """权威交易日历(含未来, up to 当年): data/trade_dates.txt(akshare tool_trade_date_hist_sina 缓存)。

    用于确定 buy_date 下一交易日: T 是今天时 etf_daily 里没有 > T 的日期(今天之后的数据还没产生),
    必须用交易日历推算下一交易日(§11.4 长假/调休: 交易日历已含, 取 > T 的最小工作日即可)。
    """
    cands = []
    for base in (db_path.parent, ROOT / "data", REPO / "data"):
        p = base / "trade_dates.txt"
        if p.exists():
            try:
                cands = sorted({line.strip() for line in p.read_text().splitlines() if line.strip()})
                if cands:
                    return cands
            except Exception:
                continue
    return cands


def _prev_close(db_path: Path, etf_code: str, on_or_before: str):
    """etf_daily 该 etf <= on_or_before 最近一天 close(T 日收盘=挂单价上限)。"""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT date, close FROM etf_daily WHERE etf_code=? AND date<=? ORDER BY date DESC LIMIT 1",
            (etf_code, on_or_before),
        )
        row = cur.fetchone()
        if row is None:
            return None, None
        return row[0], (float(row[1]) if row[1] is not None else None)
    finally:
        con.close()


def _next_trading_day(dates: list[str], t: str) -> str:
    """取 > t 的最小日期(下一交易日)。t 在集合内则取下一个; t 为最后一天则返回 None。"""
    for d in dates:
        if d > t:
            return d
    return None


def _today():
    return date.today().strftime("%Y%m%d")


def _shares_planned(amount: float, price: float) -> int:
    """100 份整数倍向下取整(§6.6: 10000÷昨收 向下取整到 100 份整数倍)。"""
    if price <= 0:
        return 0
    return int(amount / price / 100) * 100


def _norm_signal(sig: str) -> str:
    """买信号归一: buy_special_filtered(邮件链路变体名) -> buy_special(与 queries/前端同口径)。"""
    return "buy_special" if str(sig or "") == "buy_special_filtered" else str(sig or "")


def _top_etf_by_score(etfs):
    """首页 AI建议 top1 判定(static-site/app.js _topEtfByScore 同构):
    _bk_top(冻结表权威)优先; 未命中 → 纯 max(track_score), 平手回退 similarity(与回测 _build_best_etf 同准则)。"""
    if not etfs:
        return None
    for _e in etfs:
        if isinstance(_e, dict) and _e.get("_bk_top") is True:
            return _e
    best = None
    for _e in etfs:
        if not isinstance(_e, dict):
            continue
        ts = _e.get("track_score")
        if ts is None:
            continue
        if best is None or ts > best.get("track_score", -1):
            best = _e
        elif ts == best.get("track_score"):
            if (_e.get("similarity") or -1) > (best.get("similarity") or -1):
                best = _e
    return best


def _signal_candidates(conn, cfg, T, freeze, sig_stats):
    """首页 overview 同款构建当日信号候选(signal_daily 注入 etfs + 冻结 _bk_top + ai_macro)。

    返回 sigs, 每条含: date/index_id/signal/reason/etfs/_bt_in_universe/ai_macro/_top1/_rating。
    """
    rows = conn.execute(
        "SELECT date, index_id, signal, reason FROM signal_daily "
        "WHERE date=? AND index_id NOT LIKE 's.%%' ORDER BY index_id",
        (T,),
    ).fetchall()
    sigs = [dict(r) for r in rows]
    if not sigs:
        return sigs
    _mkt_map = appq._ai_macro_build_market_map(cfg)
    _tier_state, _tier_dates, _ma60_bull_state = appq._ai_macro_build_market_state(conn)
    _cyb_state, _cyb_dates = appq._ai_macro_build_cyb_tier(conn)
    _ctx = {
        "rating_of": lambda _s: appq._ai_macro_rating_of(_s, sig_stats),
        "market_of": lambda _iid: _mkt_map.get(_iid or "", ""),
        "track_score_of": appq._ai_macro_track_score_of,
        "tier_of": lambda _d: appq._ai_macro_tier_at(_d, _tier_state, _tier_dates),
        "ma60_bull_of": lambda _d: appq._ai_macro_ma60_bull_at(_d, _ma60_bull_state, _tier_dates),
        "cyb_tier_of": lambda _d: appq._ai_macro_tier_at(_d, _cyb_state, _cyb_dates),
    }
    for _s in sigs:
        # ETF 候选注入(board_etf_map 或 self ETF), 与 overview L1186-1193 同款
        _self = appq._self_etf_for(_s["index_id"], cfg, conn)
        if _self:
            _s["etfs"] = _self["etfs"]
        else:
            _s["etfs"] = [dict(_e) for _e in (appq.etf_for(_s["index_id"]).get("etfs") or [])]
        # 冻结表命中 → 该信号 top1 = 回测标的(标 _bk_top 权威); 空数组指数不从冻结 prepend(同首页)
        appq._align_home_top1_to_backtest(_s, freeze)
        _s["_bt_in_universe"] = any(_e.get("track_score") is not None for _e in (_s.get("etfs") or []))
        # AI宏降亏命中标注(与 overview L1444-1452 同款)
        _f = appq._ai_macro_hit_filters(_s, _ctx)
        _s["ai_macro"] = {"hit": bool(_f), "filters": _f}
        _s["_top1"] = _top_etf_by_score(_s.get("etfs"))
        _s["_rating"] = appq._ai_macro_rating_of(_s, sig_stats)
        # hs300 四档(T 日大盘状态, bullAuxBackupStop a9 分支判定用)
        _s["_tier_at"] = appq._ai_macro_tier_at(T, _tier_state, _tier_dates)
    return sigs


def _ai_fade_hit(sig: dict, members) -> bool:
    """首页 _isAiFadeHit 同款降亏判定: ai_macro.filters ∩ S06 基座成员集; a9 基座补 bullAuxBackupStop。

    members: s06.filters_for_date(T) 的 True 键集合; None = S06 快照缺行 fail-open(放行)。
    """
    if members is None:
        return False
    if sig.get("ai_macro", {}).get("hit"):
        fs = sig.get("ai_macro", {}).get("filters") or []
        if any(_fk in members for _fk in fs):
            return True
    if "bullAuxBackupStop" in members:
        # 前端 _isBullStopHit(app.js L2904)同构: sig∈{buy_aux,buy_backup} × tier=牛市·主升
        # 用 kp._tds_fade_spec_hit(LEGACY_SPECS 同源)判定, 避免内联复制分叉
        if kp._tds_fade_spec_hit("bullAuxBackupStop",
                                 {"sig": str(sig.get("signal") or ""), "tier": str(sig.get("_tier_at") or "")}):
            return True
    return False


def _kelly_sort_key(cand: dict):
    """K=1 排序准则(kelly _position_cap_kept_keys / 首页 _posCapSortedFn 同款):
    track_score DESC → rating(high>mid>low) → signal(buy_backup>buy>buy_aux>buy_special) → buy_date ASC。"""
    ts = cand["track_score"] if cand["track_score"] is not None else -1.0
    return (-float(ts), _RATING_RANK.get(str(cand.get("_rating") or ""), 3),
            _SIG_RANK.get(str(cand.get("signal") or ""), 9), str(cand.get("buy_date") or ""))


def main():
    ap = argparse.ArgumentParser(description="次日买入计划生成器(PRD 阶段一 §3/§6, 干跑)")
    ap.add_argument("--date", default=None, help="信号日 T(YYYYMMDD, 缺省=今天)")
    ap.add_argument("--dry-run", action="store_true", help="只计算打印, 不落盘两树/不 R2/不通知")
    ap.add_argument("--no-r2", action="store_true", help="落盘但不传 R2(自测用)")
    ap.add_argument("--no-notify", action="store_true", help="落盘但不通知(自测用)")
    args = ap.parse_args()

    T = args.date or _today()
    data_dir = REPO / "static-site" / "data"
    db_path = REPO / "data" / "etf_national_team.db"
    if not db_path.exists():
        db_path = ROOT / "data" / "etf_national_team.db"
    sent_db = REPO / "data" / "sentiment.db"
    if not sent_db.exists():
        sent_db = ROOT / "data" / "sentiment.db"
    log(f"REPO={REPO} T={T} dry_run={args.dry_run}")

    # 输入产物
    s06_doc = _load_json("kelly_mode_s06_state.json", data_dir)
    freeze = appq._etf_freeze()

    # ---- 数据就绪 gate(§23.15 不上残缺版): etf_daily 需已更新到 T 日(backfill-evening 补完后),
    #      否则 prev_close 非 T 日收盘 → 计划挂单价失真, 明确告警退出, 不产出误导性受限计划。
    #      NEXTDAY_PLAN_FORCE=1 可跳过(不推荐, 仅人工核查用)。
    etf_dates = _etf_daily_dates(db_path)
    if etf_dates and etf_dates[-1] < T:
        if os.environ.get("NEXTDAY_PLAN_FORCE") == "1":
            log(f"⚠ FORCE: etf_daily 最新日 {etf_dates[-1]} < T {T}, 强制继续(prev_close 可能非 T 日收盘)")
        else:
            log(f"✗ 数据未就绪: etf_daily 最新日 {etf_dates[-1]} < T {T}(backfill-evening 未完成), "
                f"不产出误导性计划。可 NEXTDAY_PLAN_FORCE=1 强制跳过(不推荐)")
            return 2
    elif not etf_dates:
        log("✗ etf_daily 为空, 无法确定 prev_close 与交易日")
        return 2
    # s06 基座成员集(S06Resolver fail-open: 快照缺行 → None → 降亏放行, 同前端降级契约)
    s06 = kp.S06Resolver(s06_doc)
    _f6 = s06.filters_for_date(T)
    members = {k for k, v in (_f6 or {}).items() if v} if _f6 else None
    if members is None:
        log("⚠ s06 快照缺行(T 无基座), 降亏过滤 fail-open 放行(与前端降级契约一致)")

    # ---- 信号候选(首页同款构建) ----
    conn = sqlite3.connect(f"file:{sent_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cfg = load_config()
        sig_stats = appq.sigstats.load()
    except Exception as e:
        conn.close()
        log(f"✗ 信号统计/配置加载失败: {e}")
        return 2
    sigs = _signal_candidates(conn, cfg, T, freeze, sig_stats)
    conn.close()
    log(f"T={T} signal_daily 信号(排除 s.*)={len(sigs)}")

    # 买信号 + 入样宇宙 + 降亏过滤(首页 kept 同款): 先滤降亏再选 top-K
    kept_signals = []
    fade_cut = []
    for _s in sigs:
        _sig = _norm_signal(_s["signal"])
        if _sig not in BUY_SIGNALS:
            continue
        if not _s.get("_bt_in_universe"):
            keep_cut_note = f"{_s['index_id']} {_sig} 未入样宇宙(无跟踪 ETF track_score)"
            log(f"  - {keep_cut_note}")
            continue
        top1 = _s.get("_top1")
        if not top1 or top1.get("track_score") is None:
            continue
        if _ai_fade_hit(_s, members):
            fade_cut.append(f"{_s['index_id']} {_s['signal']} ai_filters={_s['ai_macro']['filters']}")
            continue
        kept_signals.append({
            "signal_date": T,
            "index_id": _s["index_id"],
            "signal": _sig,
            "etf_code": str(top1.get("code") or ""),
            "etf_name": str(top1.get("name") or "") or str(top1.get("code") or ""),
            "track_score": top1.get("track_score"),
            "track_tier": top1.get("track_tier"),
            "_rating": _s.get("_rating"),
        })
    for _c in fade_cut:
        log(f"  ✗ 降亏过滤剔除: {_c}")
    log(f"当日买入信号通过降亏候选={len(kept_signals)}")

    # ---- K=1 保留(首页 AI建议 top1 同款排序) ----
    etf_dates = _etf_daily_dates(db_path)
    cal_dates = _trade_calendar_dates(db_path)
    trade_dates = cal_dates or etf_dates
    if not trade_dates:
        log("✗ 交易日历与 etf_daily 均为空, 无法确定下一交易日")
        return 2

    buy_date = _next_trading_day(trade_dates, T)
    if buy_date is None:
        log(f"⚠ 交易日历无 > {T} 的下一交易日(可能 T 已是日历最后一天), 走空计划")
        kept_signals = []
    for _c in kept_signals:
        _c["buy_date"] = buy_date
    kept_signals.sort(key=_kelly_sort_key)
    kept_signals = kept_signals[:K]
    _kept_desc = [f"{c['index_id']}|{c['signal']}|{c['etf_code']} ts={c['track_score']}" for c in kept_signals]
    log(f"K={K} 保留信号={_kept_desc}")

    # ---- prev_close + 双校验(原逻辑保留) ----
    plan = []
    for t in kept_signals:
        etf_code = t["etf_code"]
        etf_name = t["etf_name"]
        track_score = t["track_score"]
        # 信号日收盘 = etf_daily 该 etf T 日 close(伪跳空校验参考点)
        last_date, sig_close = _prev_close(db_path, etf_code, T)
        # 双校验 ①: prev_close>0 非停牌(该 etf 前一日有成交)
        _, prev_close = _prev_close(db_path, etf_code, T)
        if prev_close is None or prev_close <= 0:
            log(f"  ✗ {etf_code} {etf_name} prev_close={prev_close}(非停牌校验失败, 前一日无成交)")
            continue
        # 双校验 ②: prev_close vs 信号日收盘 ±20%(伪跳空剔除同款)
        if sig_close is not None and sig_close > 0:
            gap = prev_close / sig_close - 1.0
            if abs(gap) > PSEUDO_GAP:
                log(f"  ✗ {etf_code} {etf_name} 伪跳空剔除 prev_close={prev_close} sig_close={sig_close} gap={gap:.2%}")
                continue
        plan.append({
            "etf_code": etf_code,
            "etf_name": etf_name,
            "prev_close": round(prev_close, 4),
            "amount": BUY_AMOUNT,
            "signal": t["signal"],
            "track_score": track_score,
            "signal_date": T,
            "buy_date": buy_date,
        })

    plan_doc = {"date": T, "plan": plan} if plan else {"date": T, "empty": True}
    log(f"计划条目={len(plan)} buy_date={buy_date}")
    for p in plan:
        log(f"  {p['etf_code']} {p['etf_name']} prev_close={p['prev_close']} amount={p['amount']} "
            f"signal={p['signal']} track_score={p['track_score']} buy_date={p['buy_date']}")

    if args.dry_run:
        log("DRY-RUN: 不落盘不 R2 不通知")
        print(json.dumps(plan_doc, ensure_ascii=False, indent=2))
        return 0

    # ---- 落盘: 本地 data/nextday_plan.json + 两树 static-site/data/ ----
    write_targets = [ROOT / "data", data_dir, GIT_REPO / "static-site" / "data"]
    written = []
    for d in write_targets:
        d.mkdir(parents=True, exist_ok=True)
        with (d / "nextday_plan.json").open("w", encoding="utf-8") as f:
            json.dump(plan_doc, f, ensure_ascii=False, indent=1)
        written.append(str(d / "nextday_plan.json"))

    # ---- auto_trade_steps.json 追加(幂等: 同 date 已存在则跳过) ----
    steps_doc = {"schema_version": "v1", "steps": []}
    steps_paths = [data_dir / "auto_trade_steps.json", GIT_REPO / "static-site" / "data" / "auto_trade_steps.json"]
    for sp in steps_paths:
        if sp.exists():
            try:
                with sp.open("r", encoding="utf-8") as f:
                    existing = json.load(f)
                if isinstance(existing, dict) and isinstance(existing.get("steps"), list):
                    steps_doc["steps"] = existing["steps"]
                    break
            except Exception:
                pass
    # 幂等: steps 的 date = 执行日(buy_date, §6.2 交易日), 已存在该执行日的 seq1 挂单行则跳过
    if plan and any(str(s.get("date")) == buy_date and str(s.get("seq")) == "1"
                    for s in steps_doc["steps"]):
        log(f"auto_trade_steps 已含执行日 date={buy_date}, 幂等跳过追加")
    elif plan:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for p in plan:
            shares = _shares_planned(p["amount"], p["prev_close"])
            step = {
                "date": p["buy_date"],
                "seq": 1,
                "time_slot": "09:15",
                "action": "buy",
                "etf_code": p["etf_code"],
                "etf_name": p["etf_name"],
                "order_price": p["prev_close"],
                "expected_range": f"低开按开盘价成交; 高开等回落至 {p['prev_close']} 或尾盘兜底",
                "decision": f"9:25 集合竞价: O ≤ {p['prev_close']}? 是→按O成交; 否→高开等回落触及 {p['prev_close']}; 14:55 仍未触及→撤单市价兜底",
                "amount": p["amount"],
                "shares_planned": shares,
                "status": "pending",
                "status_text": "待执行",
                "signal": p["signal"],
                "track_score": p["track_score"],
                "trigger_note": f"按昨收价 {p['prev_close']} 挂限价买单, 9:25 集合竞价撮合(干跑阶段只生成计划, 不真实下单)",
                "updated_at": now,
            }
            steps_doc["steps"].append(step)
            log(f"auto_trade_steps 追加 seq1 {step['etf_code']} {step['etf_name']} buy_date={step['date']} shares={shares}")

        for sp in steps_paths:
            with sp.open("w", encoding="utf-8") as f:
                json.dump(steps_doc, f, ensure_ascii=False, indent=1)
            written.append(str(sp))

    # ---- R2 上传(§22 三步同步; 盘后产物走 upload-data-files 段) ----
    if not args.no_r2 and not args.dry_run:
        r2_files = ["nextday_plan.json"]
        if plan:
            r2_files.append("auto_trade_steps.json")
        cmd = [PY, str(SCRIPT_DIR / "upload_r2.py"), "upload-data-files"] + r2_files
        log("R2: " + " ".join(cmd))
        try:
            env = dict(os.environ)
            env.setdefault("REPO", str(REPO))
            r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
            log(f"R2 退出码={r.returncode}\n{r.stdout}")
            if r.returncode != 0:
                log(f"⚠ R2 上传失败(告警): {r.stderr[-2000:]}")
        except Exception as e:
            log(f"⚠ R2 上传异常: {e}")

    # ---- 通知(邮件+飞书, 复用 notify.send 链路; 干跑阶段通知内容是「明日计划」) ----
    if not args.no_notify and not args.dry_run:
        if plan:
            lines = []
            for p in plan:
                lines.append(
                    f"明日计划: {p['etf_code']} {p['etf_name']} | 昨收 {p['prev_close']} | "
                    f"买入 {p['amount']//10000} 万元 | 信号: {p['signal']} | 跟踪分 {p['track_score']}"
                )
            subject = f"明日买入计划 {T}"
            body = "<br>".join(lines)
        else:
            subject = f"明日买入计划 {T}(空)"
            body = "明日无买入计划(无信号或 T 日非交易日)。"
        cmd = [PY, str(SCRIPT_DIR / "notify.py"), subject, body,
               "--dedup-key", f"nextday_plan_{T}", "--dedup-window", "86400"]
        log("notify: " + subject)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            log(f"notify 退出码={r.returncode}")
        except Exception as e:
            log(f"⚠ notify 异常: {e}")

    log("落盘完成: " + ", ".join(written))
    return 0


if __name__ == "__main__":
    sys.exit(main())