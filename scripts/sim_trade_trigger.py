#!/usr/bin/env python3
"""sim_trade_trigger.py - A 模式信号触发模拟交易账本 · 四阶段触发器。

阶段(与 design doc §2 时间线一致):
  --stage signal      T 22:45   读 nextday_plan.json 定格 T+1 信号 → sim_trade_signal
  --stage buy_fill    T+1 09:50 拉实时开盘价(expect_date fail-closed) → 买入指令 + provisional fill
  --stage sell_order  D+10 14:55 到期持仓写卖出指令 + 可选 14:55 实时价 provisional fill
  --stage settle      D+10 22:45 etf_daily 补写 exec_date<=结算日 的漏跑买入 + 复核过期 provisional
                                (confirmed, supersedes provisional) + D+10 收盘价结算卖出

口径(2026-11-20 用户拍板):
  ① 买入 = 次日 09:30 市价单; 成交价用触发器实抓的当天真实开盘价(不用理论价), 滑点/费率如实记。
  ② 盈亏双记: 真实口径(100 份整手、真实价、实际费率 etf_main) + 回测等价口径(accum_nav 换算、
     回测费率 backtest=万3/最低5 + 滑点千1)。两套都写, 不混算:
       - 表内 net/gross/commission/transfer_fee/stamp_tax = **回测等价(calc)口径**(与页面锚点对账);
       - 真实口径明细放 fee_config JSON 的 real 段(真实价 + 100 份整手 + etf_main 费率)。
  ③ 卖出双记: 结算默认 D+10 收盘价(close); sell_order 阶段 14:55 实时价单列一记(intraday,
     provisional), 未来接交易软件成交时点。
  ④ append-only: 只 INSERT OR IGNORE; 复核/纠错 = 追加新行 + supersedes_*。
  ⑤ 防前视: signal 只用 T 日收盘及之前数据; exec_date > signal_date; sell_due_date 为
     signal_date 后第 10 个交易日; fill_date <= signal_date 的成交一律不允许(测试机检)。

实时开盘价复用 `scripts/signal_kelly_backtest.py:1234-1337` `_fetch_intraday_open_prices`
(懒 import, expect_date fail-closed; 取不到当日价写 fill_failed 事件, 绝不写假价)。

用法:
  python3 scripts/sim_trade_trigger.py --stage signal --date 20261119 --db data/sim_trade.db \\
      --data-dir static-site/data --etf-db data/etf_national_team.db --trade-dates data/trade_dates.txt
  ... --stage buy_fill --date 20261120 [--prices-json /tmp/prices.json]
  生产写库需 SIM_TRADE_ENABLED=1 或 --force(防误触发; timer 单元文件显式置 1)。
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sim_trade_db as db  # noqa: E402

# 费率档(与 kelly_posrating.FEE_ETF_MAIN / signal_kelly_backtest._KELLY_FEE_CONFIG 同款)
FEE_PRESETS = {
    # 页面 K=1 卡 / 真实可执行口径(万0.5 / 最低0.1元 / 滑点千1 / 沪市过户费万0.1 / 无印花税)
    "etf_main": {"commission_rate": 0.00005, "min_commission": 0.1, "slippage": 0.001,
                 "transfer_fee_rate_sh": 0.00001, "stamp_duty_rate": 0.0},
    # 回测锚点口径(万3 / 最低5元 / 滑点千1 / 沪市过户费万0.1 / 无印花税)
    "backtest": {"commission_rate": 0.0003, "min_commission": 5.0, "slippage": 0.001,
                 "transfer_fee_rate_sh": 0.00001, "stamp_duty_rate": 0.0},
}
CALC_FEE_PRESET = "backtest"   # 回测等价口径(锚点 158.40/146.43 同源)
REAL_FEE_PRESET = "etf_main"   # 真实可执行口径(页面 K=1 卡默认费率)


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def load_json(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_trade_dates(path: str | Path) -> list[str]:
    with open(path, "r", encoding="utf-8") as f:
        return sorted({ln.strip() for ln in f if ln.strip()})


def nth_trading_day_after(dates: list[str], t: str, n: int) -> str | None:
    """> t 的第 n 个交易日(与 nextday_plan_generator._nth_trading_day_after 同口径)。"""
    cnt = 0
    for d in dates:
        if d > t:
            cnt += 1
            if cnt >= n:
                return d
    return None


def next_trading_day(dates: list[str], t: str) -> str | None:
    return nth_trading_day_after(dates, t, 1)


def _is_sh_etf(code: str) -> bool:
    return str(code or "").startswith(("51", "58"))


def _tf_rate(code: str, cfg: dict) -> float:
    return cfg["transfer_fee_rate_sh"] if _is_sh_etf(code) else 0.0


def calc_buy(amount: float, close: float, code: str, cfg: dict) -> dict:
    """回测等价买入: close 为未含滑点的等价值; 返回成交价/分数份额/费用/净成本。"""
    buy_price = close * (1 + cfg["slippage"])
    c, min_c, tf_rate = cfg["commission_rate"], cfg["min_commission"], _tf_rate(code, cfg)
    shares = amount / (buy_price * (1 + c + tf_rate))
    gross = shares * buy_price
    comm = gross * c
    if comm < min_c:
        shares = (amount - min_c) / (buy_price * (1 + tf_rate))
        gross = shares * buy_price
        comm = min_c
    transfer = gross * tf_rate
    return {"price": round(buy_price, 9), "shares": shares, "gross": gross,
            "commission": comm, "transfer_fee": transfer, "stamp_tax": 0.0, "net": amount}


def calc_sell(shares: float, close: float, code: str, cfg: dict) -> dict:
    """回测等价卖出: close 为未含滑点的等价值; 返回成交价/费用/净回款。"""
    sell_price = close * (1 - cfg["slippage"])
    amount = shares * sell_price
    c, min_c, tf_rate = cfg["commission_rate"], cfg["min_commission"], _tf_rate(code, cfg)
    comm = max(amount * c, min_c)
    transfer = amount * tf_rate
    stamp = amount * cfg["stamp_duty_rate"]
    net = amount - comm - transfer - stamp
    return {"price": round(sell_price, 9), "gross": amount, "commission": comm,
            "transfer_fee": transfer, "stamp_tax": stamp, "net": net}


def real_buy(amount: float, price: float, code: str, cfg: dict) -> dict:
    """真实口径买入: 100 份整手, 真实成交价, 预算尽量花光。"""
    if price <= 0:
        return {"shares": 0.0, "gross": 0.0, "commission": 0.0, "transfer_fee": 0.0, "net": 0.0}
    c, min_c, tf_rate = cfg["commission_rate"], cfg["min_commission"], _tf_rate(code, cfg)
    qty = int(amount / price / 100) * 100
    while qty > 0:
        gross = qty * price
        comm = max(gross * c, min_c)
        transfer = gross * tf_rate
        if gross + comm + transfer <= amount + 1e-9:
            break
        qty -= 100
    if qty <= 0:
        return {"shares": 0.0, "gross": 0.0, "commission": 0.0, "transfer_fee": 0.0, "net": 0.0}
    gross = qty * price
    comm = max(gross * c, min_c)
    transfer = gross * tf_rate
    return {"shares": float(qty), "gross": gross, "commission": comm,
            "transfer_fee": transfer, "net": gross + comm + transfer}


def real_sell(shares: float, price: float, code: str, cfg: dict) -> dict:
    if price <= 0 or shares <= 0:
        return {"gross": 0.0, "commission": 0.0, "transfer_fee": 0.0, "stamp_tax": 0.0, "net": 0.0}
    qty = int(shares / 100) * 100 or shares
    gross = qty * price
    c, min_c, tf_rate = cfg["commission_rate"], cfg["min_commission"], _tf_rate(code, cfg)
    comm = max(gross * c, min_c)
    transfer = gross * tf_rate
    stamp = gross * cfg["stamp_duty_rate"]
    return {"gross": gross, "commission": comm, "transfer_fee": transfer,
            "stamp_tax": stamp, "net": gross - comm - transfer - stamp}


def fee_config_json(real: dict, calc: dict, real_preset: str, calc_preset: str) -> str:
    """真实/回测双口径完整费率与净额落 fee_config JSON(表内 net 列=calc 口径)。"""
    return json.dumps({
        "real": {"preset": real_preset, "quote": FEE_PRESETS[real_preset], **real},
        "calc": {"preset": calc_preset, "quote": FEE_PRESETS[calc_preset], **calc},
    }, ensure_ascii=False, sort_keys=True)


def open_etf_ro(path: str | Path) -> sqlite3.Connection | None:
    """只读打开 etf_daily 库; 必须设 row_factory(etf_bar 用 dict(row), 缺了会 ValueError)。"""
    if not Path(path).exists():
        return None
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def etf_bar(con: sqlite3.Connection, code: str, date: str) -> dict | None:
    row = con.execute(
        "SELECT date, open, close, accum_nav, etf_name FROM etf_daily WHERE etf_code=? AND date=?",
        (code, date),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def s06_mode_for(s06_doc: dict | None, signal_date: str) -> dict:
    """按 signal_date 取 S06 当日 effective_mode(只用 <= signal_date 的行, 防前视)。"""
    if not s06_doc:
        return {"mode": None, "decision_date": None, "generated_at": None, "note": "s06_missing"}
    rows = [r for r in (s06_doc.get("daily") or []) if str(r.get("date")) <= signal_date]
    coverage_end = str(s06_doc.get("coverage_end") or "")
    if rows and signal_date <= coverage_end:
        r = max(rows, key=lambda x: str(x.get("date")))
        return {"mode": r.get("effective_mode"), "decision_date": r.get("decision_date"),
                "generated_at": s06_doc.get("generated_at"), "note": None}
    # 覆盖期外/无行: 按快照 off_base 兜底过滤(kelly_posrating 同款降级契约), 如实记 note
    mode = s06_doc.get("off_base")
    return {"mode": mode, "decision_date": None, "generated_at": s06_doc.get("generated_at"),
            "note": "s06_beyond_coverage_off_base_fallback"}


def fade_keyset_hash(mode: str | None) -> str | None:
    try:
        import kelly_posrating as kp
        keys = kp.FADE_MODE_PRESETS.get(mode or "")
        if keys is None:
            return None
        return db.stable_id(*keys)
    except Exception:  # noqa: BLE001
        return None


def jsonl_log(log_dir: str | Path, date: str, payload: dict) -> None:
    d = Path(log_dir)
    d.mkdir(parents=True, exist_ok=True)
    with open(d / f"sim_trade_run_{date}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": db.now_iso(), **payload}, ensure_ascii=False) + "\n")


def _require_enabled(args) -> bool:
    if getattr(args, "force", False) or getattr(args, "dry_run", False):
        return True
    return os.environ.get("SIM_TRADE_ENABLED") == "1"


def _open_db(args) -> sqlite3.Connection:
    return db.init_db(args.db)


# ---------------------------------------------------------------------------
# 阶段 1: signal(T 22:45)
# ---------------------------------------------------------------------------
def run_signal(args) -> dict:
    plan_doc = load_json(args.plan_json)
    plan_date = str(plan_doc.get("date") or "")
    if args.date and plan_date and args.date != plan_date:
        raise SystemExit(f"plan.json date={plan_date} 与 --date={args.date} 不符, 拒绝定格(防误触发)")
    signal_date = args.date or plan_date
    dates = load_trade_dates(args.trade_dates)
    s06_doc = load_json(args.s06_json) if Path(args.s06_json).exists() else None
    s06_sha = db.file_sha256(args.s06_json)
    mode_info = s06_mode_for(s06_doc, signal_date)
    fade_hash = fade_keyset_hash(mode_info["mode"])
    plan_items = plan_doc.get("plan") or []
    plan_file_sha = db.file_sha256(args.plan_json)

    con = _open_db(args)
    stats = {"stage": "signal", "date": signal_date, "rows": len(plan_items),
             "inserted": 0, "ignored": 0, "skipped": 0, "superseded": 0}
    etf_db = open_etf_ro(args.etf_db)
    try:
        for item in plan_items:
            code = str(item.get("etf_code") or "")
            sig_date = str(item.get("signal_date") or signal_date)
            exec_date = str(item.get("buy_date") or "") or next_trading_day(dates, sig_date) or ""
            if not code or not exec_date:
                stats["skipped"] += 1
                continue
            if args.truncate_to and (sig_date > args.truncate_to or exec_date > args.truncate_to):
                stats["skipped"] += 1
                continue
            if exec_date <= sig_date:
                raise SystemExit(f"防前视: exec_date({exec_date}) 必须晚于 signal_date({sig_date})")
            sell_due = nth_trading_day_after(dates, sig_date, 10) or ""
            if not sell_due:
                raise SystemExit(f"交易日历不足: 无法计算 {sig_date} 的 D+10 卖出日")
            bar = etf_bar(etf_db, code, sig_date) if etf_db else None
            plan_hash = db.stable_id("plan", sig_date, exec_date, code,
                                     item.get("signal"), item.get("track_score"),
                                     item.get("prev_close"), item.get("amount"))
            signal_id = db.stable_id("A", sig_date, exec_date, code, plan_hash)
            # 计划变更: 同一 exec_date 已存在不同 signal 行 → 新行 supersedes 最新旧行(不 UPDATE)
            prev = con.execute(
                "SELECT signal_id FROM v_sim_signal_effective WHERE exec_date=? AND signal_id<>? "
                "ORDER BY created_at DESC LIMIT 1", (exec_date, signal_id)).fetchone()
            supersedes = prev[0] if prev else None
            row = {
                "signal_id": signal_id, "schema_version": db.SCHEMA_VERSION, "strategy": "A",
                "signal_date": sig_date, "exec_date": exec_date, "sell_due_date": sell_due,
                "index_id": str(item.get("index_id") or item.get("etf_code") or ""),
                "etf_code": code, "etf_name": item.get("etf_name"),
                "signal": item.get("signal"), "track_score": item.get("track_score"),
                "rating": item.get("rating"), "bk_ts": None, "track_tier": item.get("track_tier"),
                "late": int(item.get("late") or 0), "source": "log",
                "s06_effective_mode": mode_info["mode"],
                "s06_decision_date": mode_info["decision_date"],
                "s06_state_generated_at": mode_info["generated_at"],
                "s06_state_sha256": s06_sha,
                "fade_mode": "s06", "fade_keyset_hash": fade_hash,
                "universe_pass": 1, "fade_pass": 1, "k_cap": 1, "k_rank": 1,
                "amount": float(item.get("amount") or 10000),
                "plan_prev_close": item.get("prev_close"),
                "signal_accum_nav": (bar or {}).get("accum_nav"),
                "signal_close_raw": (bar or {}).get("close"),
                "plan_hash": plan_hash,
                "day_snapshot_hash": None,
                "frozen_at": db.now_iso(),
                "trigger_source": "nextday_plan.json",
                "supersedes_signal_id": supersedes,
                "revision": 1,
                "note": ";".join(x for x in [
                    mode_info["note"],
                    None if bar else "signal_bar_missing",
                ] if x) or None,
                "created_at": db.now_iso(),
            }
            if args.dry_run:
                stats["inserted"] += 1
                continue
            inserted = db.insert_or_ignore(con, "sim_trade_signal", row)
            if inserted:
                stats["inserted"] += 1
                stats["superseded"] += 1 if supersedes else 0
            else:
                stats["ignored"] += 1
        if not args.dry_run:
            db.record_event(con, "trigger_run", payload={"stage": "signal", **stats},
                            source="sim_trade_trigger")
            con.commit()
    finally:
        if etf_db:
            etf_db.close()
        con.close()
    jsonl_log(args.log_dir, signal_date, {"plan_file_sha256": plan_file_sha, **stats})
    return stats


# ---------------------------------------------------------------------------
# 价格源
# ---------------------------------------------------------------------------
def fetch_buy_open_prices(codes: list[str], expect_date: str) -> tuple[dict, list, dict]:
    """复用 signal_kelly_backtest._fetch_intraday_open_prices(懒 import, expect_date fail-closed)。"""
    from signal_kelly_backtest import _fetch_intraday_open_prices  # noqa: PLC0415
    return _fetch_intraday_open_prices(codes, expect_date=expect_date)


def _norm_quote_date(value) -> str | None:
    """东财「数据日期」归一为 YYYYMMDD; 无法解析返回 None(fail-closed)。"""
    s = str(value).strip()[:10].replace("-", "")
    return s if len(s) == 8 and s.isdigit() else None


def fetch_last_prices(codes: list[str], expect_date: str) -> dict:
    """14:55 实时最新价(东财 spot)。

    fail-closed(2026-11-21 F5): 必须能证明「这一行价格就是 expect_date 当天的」——
    缺「数据日期」列、日期解析失败、或日期 != expect_date 一律返回 {} 不写假价。
    """
    try:
        import warnings
        import akshare as ak
    except Exception:  # noqa: BLE001
        return {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            df = ak.fund_etf_spot_em()
        except Exception:  # noqa: BLE001
            return {}
    if df is None or getattr(df, "empty", True) or "代码" not in df.columns:
        return {}
    if "数据日期" not in df.columns:
        return {}  # 无日期列 ⇒ 无法证明是当日价 ⇒ fail-closed
    try:
        quote_dates = df["数据日期"].map(_norm_quote_date)
    except Exception:  # noqa: BLE001
        return {}
    df = df[quote_dates == expect_date]  # 逐行校验, 混日期源也不会串价
    if df is None or getattr(df, "empty", True):
        return {}
    out = {}
    for _, row in df[df["代码"].isin([str(c) for c in codes])].iterrows():
        try:
            px = float(row.get("最新价") or row.get("开盘价"))
        except (TypeError, ValueError):
            continue
        if px > 0:
            out[str(row["代码"])] = px
    return out


def _price_overrides(path: str | None) -> dict:
    if not path:
        return {}
    return {str(k): float(v) for k, v in load_json(path).items()}


# ---------------------------------------------------------------------------
# 阶段 2: buy_fill(T+1 09:50)
# ---------------------------------------------------------------------------
def run_buy_fill(args) -> dict:
    date = args.date
    con = _open_db(args)
    stats = {"stage": "buy_fill", "date": date, "signals": 0, "orders": 0,
             "fills": 0, "fill_failed": 0, "confirmed_existing": 0, "skipped": 0,
             "superseded": 0}
    signals = con.execute(
        "SELECT * FROM v_sim_signal_effective WHERE exec_date=? AND signal_date<?", (date, date)).fetchall()
    stats["signals"] = len(signals)
    prices = _price_overrides(args.prices_json)
    try:
        if signals and not prices:
            codes = sorted({s["etf_code"] for s in signals})
            try:
                out, _zv, _meta = fetch_buy_open_prices(codes, expect_date=date)
                prices.update(out or {})
            except Exception as e:  # noqa: BLE001
                db.record_event(con, "fill_failed", signal_id=None,
                                payload={"stage": "buy_fill", "date": date, "reason": "fetch_error",
                                         "error": f"{type(e).__name__}: {e}"},
                                source="sim_trade_trigger")
        for s in signals:
            code = s["etf_code"]
            order_id = db.stable_id(s["signal_id"], "buy", "0930", s["amount"],
                                    "market", s["plan_prev_close"])
            confirmed = con.execute(
                "SELECT 1 FROM sim_trade_order o JOIN sim_trade_fill f ON f.order_id=o.order_id "
                "WHERE o.signal_id=? AND o.side='buy' AND f.status='confirmed' LIMIT 1",
                (s["signal_id"],)).fetchone()
            if confirmed:
                stats["confirmed_existing"] += 1
                continue
            if args.dry_run:
                stats["orders"] += 1
                continue
            order = {
                "order_id": order_id, "signal_id": s["signal_id"], "strategy": "A",
                "side": "buy", "action": "open", "etf_code": code, "etf_name": s["etf_name"],
                "qty_plan": float(int((s["amount"] or 10000) / (s["plan_prev_close"] or 1) / 100) * 100),
                "qty_unit": "share", "amount": s["amount"], "price_type": "market",
                "limit_price": None, "intended_at": "09:30", "triggered_at": db.now_iso(),
                "trigger_source": "sim_trade_trigger.buy_fill", "broker_account": None,
                "broker_order_id": None, "request_payload": None, "response_payload": None,
                "initial_status": "submitted", "created_at": db.now_iso(),
            }
            if db.insert_or_ignore(con, "sim_trade_order", order):
                stats["orders"] += 1
            px = prices.get(code)
            if not px or px <= 0:
                db.record_event(con, "fill_failed", order_id=order_id, signal_id=s["signal_id"],
                                payload={"stage": "buy_fill", "date": date, "reason": "no_price",
                                         "expect_date": date, "etf_code": code},
                                source="sim_trade_trigger")
                stats["fill_failed"] += 1
                continue
            accum_ref, close_ref = s["signal_accum_nav"], s["signal_close_raw"]
            equiv = (accum_ref * px / close_ref) if (accum_ref and close_ref and close_ref > 0) else None
            calc = calc_buy(s["amount"] or 10000, equiv, code, FEE_PRESETS[CALC_FEE_PRESET]) if equiv else None
            real = real_buy(s["amount"] or 10000, px, code, FEE_PRESETS[REAL_FEE_PRESET])
            fee_json = fee_config_json(real, calc or {}, REAL_FEE_PRESET, CALC_FEE_PRESET)
            # 同日重跑(2026-11-21 F4): 已有有效 provisional 且新价不同 → 新行 supersede 旧行,
            # 保证一单任何时刻只有 1 条有效买入成交(append-only: 只追加纠错链, 不删不改)。
            prev = con.execute(
                "SELECT fill_id, price_raw FROM v_sim_fill_effective"
                " WHERE order_id=? AND side='buy'"
                " ORDER BY CASE status WHEN 'confirmed' THEN 0 ELSE 1 END, created_at DESC LIMIT 1",
                (order_id,)).fetchone()
            fill_id = db.stable_id(order_id, date, "realtime", round(px, 6), round(real["shares"], 6))
            supersedes = prev[0] if (prev and prev[0] != fill_id) else None
            fill = {
                "fill_id": fill_id, "order_id": order_id, "side": "buy", "fill_date": date,
                "fill_time": "09:30", "price_kind": "open", "price_raw": px,
                "price_equiv": equiv, "accum_nav_ref": accum_ref, "raw_close_ref": close_ref,
                "raw_ref_date": s["signal_date"],
                "shares_calc": (calc or {}).get("shares"), "shares_real": real["shares"],
                "gross": (calc or {}).get("gross"), "commission": (calc or {}).get("commission"),
                "transfer_fee": (calc or {}).get("transfer_fee"),
                "stamp_tax": (calc or {}).get("stamp_tax"), "net": (calc or {}).get("net"),
                "fee_preset": CALC_FEE_PRESET, "fee_config": fee_json,
                "source": "realtime", "source_ts": db.now_iso(), "quote_date": date,
                "status": "provisional", "supersedes_fill_id": supersedes,
                "correction_reason": "同日异价重跑: 新 provisional 取代旧 provisional" if supersedes else None,
                "created_at": db.now_iso(),
            }
            if db.insert_or_ignore(con, "sim_trade_fill", fill):
                stats["fills"] += 1
                if supersedes:
                    stats["superseded"] += 1
                    db.record_event(con, "correction", order_id=order_id, signal_id=s["signal_id"],
                                    payload={"stage": "buy_fill", "date": date,
                                             "reason": "rerun_price_differs",
                                             "prev_fill_id": supersedes,
                                             "prev_price_raw": prev["price_raw"],
                                             "new_fill_id": fill_id, "new_price_raw": px},
                                    source="sim_trade_trigger")
            else:
                stats["skipped"] += 1
        if not args.dry_run:
            db.record_event(con, "trigger_run", payload=stats, source="sim_trade_trigger")
            con.commit()
    finally:
        con.close()
    jsonl_log(args.log_dir, date, stats)
    return stats


# ---------------------------------------------------------------------------
# 阶段 3: sell_order(D+10 14:55)
# ---------------------------------------------------------------------------
def run_sell_order(args) -> dict:
    date = args.date
    con = _open_db(args)
    stats = {"stage": "sell_order", "date": date, "positions": 0, "orders": 0,
             "fills": 0, "no_price": 0, "skipped": 0}
    rows = con.execute(
        "SELECT * FROM v_sim_trade_position WHERE sell_due_date=? AND closed=0", (date,)).fetchall()
    stats["positions"] = len(rows)
    prices = _price_overrides(args.prices_json)
    etf = open_etf_ro(args.etf_db)
    try:
        if rows and not prices:
            codes = sorted({r["etf_code"] for r in rows})
            prices.update(fetch_last_prices(codes, expect_date=date))
        for p in rows:
            code = p["etf_code"]
            qty = p["buy_shares_real"] or 0
            # 2026-11-21 F2: 没有有效买入成交就没有可卖的东西。只记事件, 不写卖出指令/0 份额假成交。
            if p["buy_fill_id"] is None or qty <= 0:
                if not args.dry_run:
                    db.record_event(con, "sell_skipped_no_fill", signal_id=p["signal_id"],
                                    payload={"stage": "sell_order", "date": date,
                                             "reason": "no_valid_buy_fill",
                                             "buy_fill_id": p["buy_fill_id"],
                                             "buy_shares_real": p["buy_shares_real"]},
                                    source="sim_trade_trigger")
                stats["skipped"] += 1
                continue
            order_id = db.stable_id(p["signal_id"], "sell", "1455", qty, "market", None)
            if args.dry_run:
                stats["orders"] += 1
                continue
            order = {
                "order_id": order_id, "signal_id": p["signal_id"], "strategy": "A",
                "side": "sell", "action": "close", "etf_code": code, "etf_name": p["etf_name"],
                "qty_plan": qty, "qty_unit": "share", "amount": None, "price_type": "market",
                "limit_price": None, "intended_at": "14:55", "triggered_at": db.now_iso(),
                "trigger_source": "sim_trade_trigger.sell_order", "broker_account": None,
                "broker_order_id": None, "request_payload": None, "response_payload": None,
                "initial_status": "submitted", "created_at": db.now_iso(),
            }
            if db.insert_or_ignore(con, "sim_trade_order", order):
                stats["orders"] += 1
            px = prices.get(code)
            if not px or px <= 0:
                db.record_event(con, "price_unavailable", order_id=order_id, signal_id=p["signal_id"],
                                payload={"stage": "sell_order", "date": date, "reason": "no_1455_price",
                                         "expect_date": date}, source="sim_trade_trigger")
                stats["no_price"] += 1
                continue
            bar = etf_bar(etf, code, date) if etf else None
            equiv = None
            if bar and bar.get("accum_nav") and bar.get("close") and bar["close"] > 0:
                equiv = bar["accum_nav"] * px / bar["close"]
            calc = calc_sell(p["buy_shares_calc"] or qty, equiv, code, FEE_PRESETS[CALC_FEE_PRESET]) if equiv else None
            real = real_sell(qty, px, code, FEE_PRESETS[REAL_FEE_PRESET])
            fill_id = db.stable_id(order_id, date, "realtime", round(px, 6), round(qty, 6))
            # 同日重跑的 F4 同类面在卖出侧天然不成立: 第一笔 provisional 卖出就让
            # v_sim_trade_position.closed=1, 重跑扫不到该持仓(positions=0), 不会产生第二条有效卖出。
            # 结算复核用 prev_fill_id supersede 最新有效卖出(见 run_settle 阶段 2)。
            fill = {
                "fill_id": fill_id, "order_id": order_id, "side": "sell", "fill_date": date,
                "fill_time": "14:55", "price_kind": "intraday", "price_raw": px,
                "price_equiv": equiv, "accum_nav_ref": (bar or {}).get("accum_nav"),
                "raw_close_ref": (bar or {}).get("close"), "raw_ref_date": date,
                "shares_calc": (calc or {}).get("shares", p["buy_shares_calc"]),
                "shares_real": qty, "gross": (calc or {}).get("gross"),
                "commission": (calc or {}).get("commission"),
                "transfer_fee": (calc or {}).get("transfer_fee"),
                "stamp_tax": (calc or {}).get("stamp_tax"), "net": (calc or {}).get("net"),
                "fee_preset": CALC_FEE_PRESET,
                "fee_config": fee_config_json(real, calc or {}, REAL_FEE_PRESET, CALC_FEE_PRESET),
                "source": "realtime", "source_ts": db.now_iso(), "quote_date": date,
                "status": "provisional", "supersedes_fill_id": None,
                "correction_reason": None, "created_at": db.now_iso(),
            }
            if db.insert_or_ignore(con, "sim_trade_fill", fill):
                stats["fills"] += 1
            else:
                stats["skipped"] += 1
        if not args.dry_run:
            db.record_event(con, "trigger_run", payload=stats, source="sim_trade_trigger")
            con.commit()
    finally:
        if etf:
            etf.close()
        con.close()
    jsonl_log(args.log_dir, date, stats)
    return stats


# ---------------------------------------------------------------------------
# 阶段 4: settle(D+10 22:45) — 复核买入 + 结算卖出
# ---------------------------------------------------------------------------
def run_settle(args) -> dict:
    date = args.date
    con = _open_db(args)
    stats = {"stage": "settle", "date": date, "buy_confirmed": 0, "buy_backfilled": 0,
             "buy_backfill_failed": 0, "sell_settled": 0, "no_bar": 0, "skipped": 0}
    etf = open_etf_ro(args.etf_db)
    if etf is None:
        raise SystemExit(f"etf_daily DB 不存在: {args.etf_db}")
    try:
        # 1a) 漏跑补写(2026-11-21 F1): exec_date <= 结算日 且没有任何有效买入成交的信号,
        #     用 etf_daily 该执行日官方开盘价追加 confirmed 买入(缺 order 一并补建, FK 需要)。
        #     覆盖 09:50 取价失败 / timer 漏跑 / 机器不在线 / 隔日手动补, 交易不再永久丢失。
        missing = con.execute(
            "SELECT s.* FROM v_sim_signal_effective s "
            "WHERE s.exec_date<=? AND s.trigger_source<>'backfill' AND NOT EXISTS ("
            "  SELECT 1 FROM sim_trade_order o JOIN v_sim_fill_effective f"
            "  ON f.order_id=o.order_id AND f.side='buy'"
            "  WHERE o.signal_id=s.signal_id AND o.side='buy') "
            "ORDER BY s.exec_date, s.signal_id", (date,)).fetchall()
        for s in missing:
            exec_date = s["exec_date"]
            order_id = db.stable_id(s["signal_id"], "buy", "0930", s["amount"],
                                    "market", s["plan_prev_close"])
            bar = etf_bar(etf, s["etf_code"], exec_date)
            if not bar or not bar.get("open"):
                if not args.dry_run:
                    db.record_event(con, "fill_failed", order_id=order_id, signal_id=s["signal_id"],
                                    payload={"stage": "settle_backfill", "reason": "no_etf_daily_open",
                                             "date": exec_date, "etf_code": s["etf_code"]},
                                    source="sim_trade_trigger")
                stats["buy_backfill_failed"] += 1
                continue
            px = float(bar["open"])
            accum_ref, close_ref = s["signal_accum_nav"], s["signal_close_raw"]
            equiv = (accum_ref * px / close_ref) if (accum_ref and close_ref and close_ref > 0) else None
            calc = calc_buy(s["amount"] or 10000, equiv, s["etf_code"], FEE_PRESETS[CALC_FEE_PRESET]) if equiv else None
            real = real_buy(s["amount"] or 10000, px, s["etf_code"], FEE_PRESETS[REAL_FEE_PRESET])
            if args.dry_run:
                stats["buy_backfilled"] += 1
                continue
            db.insert_or_ignore(con, "sim_trade_order", {
                "order_id": order_id, "signal_id": s["signal_id"], "strategy": "A",
                "side": "buy", "action": "open", "etf_code": s["etf_code"], "etf_name": s["etf_name"],
                "qty_plan": float(int((s["amount"] or 10000) / (s["plan_prev_close"] or 1) / 100) * 100),
                "qty_unit": "share", "amount": s["amount"], "price_type": "market",
                "limit_price": None, "intended_at": "09:30", "triggered_at": db.now_iso(),
                "trigger_source": "sim_trade_trigger.settle_backfill", "broker_account": None,
                "broker_order_id": None, "request_payload": None, "response_payload": None,
                "initial_status": "submitted", "created_at": db.now_iso(),
            })
            fill_id = db.stable_id(order_id, exec_date, "etf_daily", round(px, 6), round(real["shares"], 6))
            fill = {
                "fill_id": fill_id, "order_id": order_id, "side": "buy", "fill_date": exec_date,
                "fill_time": "22:45", "price_kind": "open", "price_raw": px,
                "price_equiv": equiv, "accum_nav_ref": accum_ref, "raw_close_ref": close_ref,
                "raw_ref_date": s["signal_date"],
                "shares_calc": (calc or {}).get("shares"), "shares_real": real["shares"],
                "gross": (calc or {}).get("gross"), "commission": (calc or {}).get("commission"),
                "transfer_fee": (calc or {}).get("transfer_fee"),
                "stamp_tax": (calc or {}).get("stamp_tax"), "net": (calc or {}).get("net"),
                "fee_preset": CALC_FEE_PRESET,
                "fee_config": fee_config_json(real, calc or {}, REAL_FEE_PRESET, CALC_FEE_PRESET),
                "source": "etf_daily", "source_ts": db.now_iso(), "quote_date": exec_date,
                "status": "confirmed", "supersedes_fill_id": None,
                "correction_reason": "settle 漏跑补写: etf_daily 开盘价", "created_at": db.now_iso(),
            }
            if db.insert_or_ignore(con, "sim_trade_fill", fill):
                stats["buy_backfilled"] += 1
                db.record_event(con, "settle_backfill", order_id=order_id, signal_id=s["signal_id"],
                                payload={"stage": "settle_backfill", "date": exec_date,
                                         "price_raw": px, "price_equiv": equiv},
                                source="sim_trade_trigger")
            else:
                stats["skipped"] += 1
        # 1b) 买入复核: 每个买入 order 取最新一条「有效 provisional」, 用 etf_daily 该执行日开盘价
        #     追加 confirmed 并 supersede 它(过期未复核的也补)。用 v_sim_fill_effective 取,
        #     已被 supersede 的旧 provisional 不会重复复核(2026-11-21 F1/F7 联动)。
        rows = con.execute(
            "SELECT s.*, o.order_id, f.fill_id AS prev_fill_id "
            "FROM v_sim_signal_effective s "
            "JOIN sim_trade_order o ON o.signal_id=s.signal_id AND o.side='buy' "
            "JOIN v_sim_fill_effective f ON f.fill_id = ("
            "  SELECT f2.fill_id FROM v_sim_fill_effective f2"
            "  WHERE f2.order_id=o.order_id AND f2.side='buy' AND f2.status='provisional'"
            "  ORDER BY f2.created_at DESC, f2.fill_id LIMIT 1) "
            "WHERE s.exec_date<=? AND s.trigger_source<>'backfill' "
            "ORDER BY s.exec_date, s.signal_id", (date,)).fetchall()
        for s in rows:
            exec_date = s["exec_date"]
            bar = etf_bar(etf, s["etf_code"], exec_date)
            if not bar or not bar.get("open"):
                if not args.dry_run:
                    db.record_event(con, "fill_failed", order_id=s["order_id"], signal_id=s["signal_id"],
                                    payload={"stage": "settle", "reason": "no_etf_daily_open",
                                             "date": exec_date, "etf_code": s["etf_code"]},
                                    source="sim_trade_trigger")
                stats["no_bar"] += 1
                continue
            px = float(bar["open"])
            accum_ref, close_ref = s["signal_accum_nav"], s["signal_close_raw"]
            equiv = (accum_ref * px / close_ref) if (accum_ref and close_ref and close_ref > 0) else None
            calc = calc_buy(s["amount"] or 10000, equiv, s["etf_code"], FEE_PRESETS[CALC_FEE_PRESET]) if equiv else None
            real = real_buy(s["amount"] or 10000, px, s["etf_code"], FEE_PRESETS[REAL_FEE_PRESET])
            fill_id = db.stable_id(s["order_id"], exec_date, "etf_daily", round(px, 6), round(real["shares"], 6))
            if args.dry_run:
                stats["buy_confirmed"] += 1
                continue
            fill = {
                "fill_id": fill_id, "order_id": s["order_id"], "side": "buy", "fill_date": exec_date,
                "fill_time": "22:45", "price_kind": "open", "price_raw": px,
                "price_equiv": equiv, "accum_nav_ref": accum_ref, "raw_close_ref": close_ref,
                "raw_ref_date": s["signal_date"],
                "shares_calc": (calc or {}).get("shares"), "shares_real": real["shares"],
                "gross": (calc or {}).get("gross"), "commission": (calc or {}).get("commission"),
                "transfer_fee": (calc or {}).get("transfer_fee"),
                "stamp_tax": (calc or {}).get("stamp_tax"), "net": (calc or {}).get("net"),
                "fee_preset": CALC_FEE_PRESET,
                "fee_config": fee_config_json(real, calc or {}, REAL_FEE_PRESET, CALC_FEE_PRESET),
                "source": "etf_daily", "source_ts": db.now_iso(), "quote_date": exec_date,
                "status": "confirmed", "supersedes_fill_id": s["prev_fill_id"],
                "correction_reason": "etf_daily 开盘价复核", "created_at": db.now_iso(),
            }
            if db.insert_or_ignore(con, "sim_trade_fill", fill):
                stats["buy_confirmed"] += 1
            else:
                stats["skipped"] += 1
        # 2) 到期卖出结算: etf_daily close → confirmed(close 口径, 与 A 模式回测同源)
        # ⚠️ 不能用 p.closed=0 筛选: sell_order 阶段写过的 provisional 14:55 成交也会让 closed=1,
        # 用 closed=0 会永久跳过结算(provisional 永远升不了 confirmed)。正确判据 = 尚无 confirmed 卖出。
        sells = con.execute(
            "SELECT p.*, o.order_id, "
            "(SELECT f.fill_id FROM v_sim_fill_effective f WHERE f.order_id=o.order_id AND f.side='sell' "
            " ORDER BY CASE f.status WHEN 'confirmed' THEN 0 ELSE 1 END, f.created_at DESC LIMIT 1) AS prev_fill_id "
            "FROM v_sim_trade_position p JOIN sim_trade_order o ON o.signal_id=p.signal_id AND o.side='sell' "
            "WHERE p.sell_due_date=? AND NOT EXISTS ("
            "  SELECT 1 FROM sim_trade_fill f WHERE f.order_id=o.order_id AND f.side='sell'"
            "  AND f.status='confirmed')", (date,)).fetchall()
        for p in sells:
            # 2026-11-21 F2: 无有效买入成交(或 0 份额)时拒绝结算卖出, 只记事件。
            if p["buy_fill_id"] is None or not p["buy_shares_real"] or p["buy_shares_real"] <= 0:
                if not args.dry_run:
                    db.record_event(con, "sell_skipped_no_fill", order_id=p["order_id"],
                                    signal_id=p["signal_id"],
                                    payload={"stage": "settle", "date": date,
                                             "reason": "no_valid_buy_fill",
                                             "buy_fill_id": p["buy_fill_id"],
                                             "buy_shares_real": p["buy_shares_real"]},
                                    source="sim_trade_trigger")
                stats["skipped"] += 1
                continue
            bar = etf_bar(etf, p["etf_code"], date)
            if not bar or not bar.get("close"):
                if not args.dry_run:
                    db.record_event(con, "fill_failed", order_id=p["order_id"], signal_id=p["signal_id"],
                                    payload={"stage": "settle", "reason": "no_etf_daily_close",
                                             "date": date, "etf_code": p["etf_code"]},
                                    source="sim_trade_trigger")
                stats["no_bar"] += 1
                continue
            px = float(bar["close"])
            accum_ref = bar.get("accum_nav")
            shares_calc = p["buy_shares_calc"] or p["buy_shares_real"] or 0
            # D+10 收盘等价值 = 当日 accum_nav(与 A 模式回测卖出同源); 未含滑点
            equiv = accum_ref
            calc = calc_sell(shares_calc, equiv, p["etf_code"], FEE_PRESETS[CALC_FEE_PRESET]) if equiv else None
            real = real_sell(p["buy_shares_real"] or 0, px, p["etf_code"], FEE_PRESETS[REAL_FEE_PRESET])
            fill_id = db.stable_id(p["order_id"], date, "etf_daily", round(px, 6), round(p["buy_shares_real"] or 0, 6))
            if args.dry_run:
                stats["sell_settled"] += 1
                continue
            fill = {
                "fill_id": fill_id, "order_id": p["order_id"], "side": "sell", "fill_date": date,
                "fill_time": "22:45", "price_kind": "close", "price_raw": px,
                "price_equiv": equiv, "accum_nav_ref": accum_ref, "raw_close_ref": px,
                "raw_ref_date": date,
                "shares_calc": (calc or {}).get("shares", shares_calc),
                "shares_real": p["buy_shares_real"],
                "gross": (calc or {}).get("gross"), "commission": (calc or {}).get("commission"),
                "transfer_fee": (calc or {}).get("transfer_fee"),
                "stamp_tax": (calc or {}).get("stamp_tax"), "net": (calc or {}).get("net"),
                "fee_preset": CALC_FEE_PRESET,
                "fee_config": fee_config_json(real, calc or {}, REAL_FEE_PRESET, CALC_FEE_PRESET),
                "source": "etf_daily", "source_ts": db.now_iso(), "quote_date": date,
                "status": "confirmed", "supersedes_fill_id": p["prev_fill_id"],
                "correction_reason": "D+10 收盘价结算", "created_at": db.now_iso(),
            }
            if db.insert_or_ignore(con, "sim_trade_fill", fill):
                stats["sell_settled"] += 1
                db.record_event(con, "settle", order_id=p["order_id"], signal_id=p["signal_id"],
                                payload={"stage": "settle", "date": date, "price_raw": px,
                                         "price_equiv": equiv}, source="sim_trade_trigger")
            else:
                stats["skipped"] += 1
        if not args.dry_run:
            db.record_event(con, "trigger_run", payload=stats, source="sim_trade_trigger")
            con.commit()
    finally:
        etf.close()
        con.close()
    jsonl_log(args.log_dir, date, stats)
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="A 模式信号触发模拟交易账本触发器")
    ap.add_argument("--stage", required=True, choices=("signal", "buy_fill", "sell_order", "settle"))
    ap.add_argument("--date", help="业务日期 YYYYMMDD(必填; signal=信号日 T, 其余=执行日)")
    ap.add_argument("--db", default="data/sim_trade.db")
    ap.add_argument("--data-dir", default="static-site/data")
    ap.add_argument("--plan-json", default=None)
    ap.add_argument("--s06-json", default=None)
    ap.add_argument("--etf-db", default="data/etf_national_team.db")
    ap.add_argument("--trade-dates", default="data/trade_dates.txt")
    ap.add_argument("--log-dir", default="data/logs")
    ap.add_argument("--prices-json", default=None, help="测试/调试用价格覆盖 {etf_code: price}")
    ap.add_argument("--truncate-to", default=None, help="防前视截断: 忽略晚于该日的数据(测试用)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="跳过 SIM_TRADE_ENABLED=1 生产开关")
    return ap


def main(argv=None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if not args.date:
        ap.error("--date 必填")
    args.plan_json = args.plan_json or str(Path(args.data_dir) / "nextday_plan.json")
    args.s06_json = args.s06_json or str(Path(args.data_dir) / "kelly_mode_s06_state.json")
    if not _require_enabled(args):
        print("SIM_TRADE_ENABLED != 1: 生产写库关闭(手动执行请加 --force)", file=sys.stderr)
        return 0
    fn = {"signal": run_signal, "buy_fill": run_buy_fill,
          "sell_order": run_sell_order, "settle": run_settle}[args.stage]
    stats = fn(args)
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
