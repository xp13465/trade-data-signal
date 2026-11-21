#!/usr/bin/env python3
"""export_sim_trade.py - 把模拟交易账本导出成 admin 工作台可展示的 JSON。

数据链路: data/sim_trade.db(append-only 账本)
        -> scripts/export_sim_trade.py(本脚本, 原子写)
        -> static-site/data/simtrade.json(公开静态产物)
        -> admin/ops.html「模拟交易」tab 渲染。

输出区块:
  1. positions  当前持仓(有有效买入、未平仓): 标的/买入日/成本价/份额/最新价/浮动盈亏
  2. trades     成交流水(近 N 条, 买/卖/价格/份额/费用/滑点估算)
  3. summary    累计指标, calc(回测等价)与 real(真实可执行)双口径分开,
                算法直接复用 sim_trade_review.review(不重写指标实现)
  4. backfill   可选「回填全史对照」(--backfill-db 指定, 未配置则 available=false)
  5. runs       最近 3 个业务日四阶段运行状态(账本事件 + 每日 JSONL 日志)

空库/账本尚未建立也必须产出合法 JSON(空数组 + 状态说明), 前端不白屏。
所有账本读取走 sim_trade_db.connect(), 不裸连(保证 recursive_triggers=ON 的同一路径)。

用法:
  python3 scripts/export_sim_trade.py --db data/sim_trade.db \
      --out static-site/data/simtrade.json \
      --etf-db data/etf_national_team.db   # 不传则不取价: 未平仓最新价为空(不做隐式路径回退)
  python3 scripts/export_sim_trade.py --backfill-db /tmp/sim_trade_backfill.db
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
for p in (str(SCRIPT_DIR), str(ROOT / "static-site")):
    if p not in sys.path:
        sys.path.insert(0, p)

import sim_trade_db as db  # noqa: E402
import sim_trade_review as review_mod  # noqa: E402

SCHEMA_VERSION = 1
STAGES = ("signal", "buy_fill", "sell_order", "settle")
MAX_RUN_DAYS = 3


def _json_loads(raw):
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _fee_of(row):
    """从 fee_config 的 real 段取费用/滑点(真实口径); 缺失返回 None。"""
    cfg = _json_loads(row["fee_config"])
    real = cfg.get("real") if isinstance(cfg.get("real"), dict) else {}
    gross = real.get("gross")
    net = real.get("net")
    fee = round(float(gross) - float(net), 4) if gross is not None and net is not None else None
    slip_rate = (real.get("quote") or {}).get("slippage") if isinstance(real.get("quote"), dict) else None
    slip = round(float(gross) * float(slip_rate), 4) if gross is not None and slip_rate is not None else None
    return fee, slip, slip_rate


def _etf_latest(etf_con, code: str) -> dict | None:
    if etf_con is None or not code:
        return None
    try:
        row = etf_con.execute(
            "SELECT date, close FROM etf_daily WHERE etf_code=? AND close IS NOT NULL "
            "ORDER BY date DESC LIMIT 1", (code,)).fetchone()
    except sqlite3.Error:
        return None
    return {"date": row[0], "close": float(row[1])} if row else None


def export_positions(con, etf_con=None) -> list[dict]:
    rows = con.execute(
        "SELECT * FROM v_sim_trade_position ORDER BY signal_date DESC, etf_code").fetchall()
    out = []
    for r in rows:
        if not r["buy_fill_id"] or r["closed"]:
            continue
        latest = _etf_latest(etf_con, r["etf_code"])
        shares = float(r["buy_shares_real"] or 0)
        # 视图不带 fee_config, 按 buy_fill_id 回查买入成交的真实费率净额
        buy_fee_row = con.execute(
            "SELECT fee_config FROM sim_trade_fill WHERE fill_id=?", (r["buy_fill_id"],)).fetchone()
        cfg = _json_loads(buy_fee_row[0] if buy_fee_row else None)
        price = latest["close"] if latest else None
        market_value = round(price * shares, 2) if price is not None and shares else None
        profit = None
        profit_pct = None
        if r["sell_fill_kind"] == "mark" and r["profit_mark"] is not None:
            profit = round(float(r["profit_mark"]), 2)
        elif market_value is not None:
            real_net = ((cfg.get("real") or {}).get("net")) if isinstance(cfg.get("real"), dict) else None
            if real_net is not None:
                profit = round(market_value - float(real_net), 2)
        amount = float(r["amount"] or 10000)
        if profit is not None and amount:
            profit_pct = round(profit / amount * 100, 2)
        out.append({
            "etf_code": r["etf_code"], "etf_name": r["etf_name"],
            "signal_date": r["signal_date"], "exec_date": r["exec_date"],
            "sell_due_date": r["sell_due_date"], "amount": amount,
            "buy_date": r["buy_fill_date"], "buy_price": r["buy_price_raw"],
            "shares": shares or None, "buy_cost": r["buy_cost"],
            "latest_price": price, "latest_date": latest["date"] if latest else None,
            "market_value": market_value, "profit": profit, "profit_pct": profit_pct,
            "price_source": "etf_daily" if latest else ("mark" if r["sell_fill_kind"] == "mark" else "unavailable"),
            "mark_profit": r["profit_mark"],
        })
    return out


def export_trades(con, recent: int = 200) -> tuple[list[dict], dict]:
    rows = con.execute(
        """
        SELECT f.fill_id, f.side, f.fill_date, f.price_kind, f.price_raw,
               f.shares_real, f.status, f.fee_config, f.source, f.created_at,
               o.signal_id, s.etf_code, s.etf_name, s.signal_date, s.sell_due_date
        FROM v_sim_fill_effective f
        JOIN sim_trade_order o ON o.order_id = f.order_id
        JOIN v_sim_signal_effective s ON s.signal_id = o.signal_id
        WHERE f.price_kind <> 'mark'
        ORDER BY f.fill_date DESC, f.created_at DESC
        LIMIT ?
        """, (recent,)).fetchall()
    out = []
    for r in rows:
        fee, slip, slip_rate = _fee_of(r)
        out.append({
            "fill_id": r["fill_id"], "side": r["side"], "fill_date": r["fill_date"],
            "price_kind": r["price_kind"], "price": r["price_raw"],
            "shares": r["shares_real"], "status": r["status"], "source": r["source"],
            "fee": fee, "slippage_est": slip, "slippage_rate": slip_rate,
            "etf_code": r["etf_code"], "etf_name": r["etf_name"],
            "signal_date": r["signal_date"], "sell_due_date": r["sell_due_date"],
            "created_at": r["created_at"],
        })
    total = con.execute(
        "SELECT COUNT(*) FROM v_sim_fill_effective WHERE price_kind <> 'mark'").fetchone()[0]
    return out, {"shown": len(out), "total": total, "limit": recent}


def export_summary(con, etf_con=None) -> dict:
    out = {}
    for caliber in ("calc", "real"):
        out[caliber] = review_mod.review(con, caliber, "signal", False)
    rows = con.execute("SELECT * FROM v_sim_trade_position").fetchall()
    out["counts"] = {
        "signals": len(rows),
        "closed": sum(1 for r in rows if r["closed"]),
        "open": sum(1 for r in rows if r["buy_fill_id"] and not r["closed"]),
        "no_fill": sum(1 for r in rows if not r["buy_fill_id"]),
    }
    return out


def export_backfill(path: str | Path | None) -> dict:
    if not path:
        return {"available": False, "reason": "未配置回填对照库(--backfill-db)"}
    p = Path(path)
    if not p.exists():
        return {"available": False, "reason": "回填对照库不存在: " + p.name}
    con = db.connect(p)
    try:
        return {
            "available": True, "db": p.name,
            "note": "K=1 页面卡口径(含未平仓估值标记), 与 live 账本分开计算",
            "calc": review_mod.review(con, "calc", "signal", True),
            "real": review_mod.review(con, "real", "signal", True),
        }
    finally:
        con.close()


def export_runs(con, log_dir: str | Path | None) -> list[dict]:
    """最近 3 个业务日的四阶段运行状态: 账本 trigger_run 事件 + 每日 JSONL 日志。"""
    by_date: dict[str, dict] = {}

    def slot(date: str, stage: str) -> dict:
        return by_date.setdefault(date, {}).setdefault(stage, {
            "stage": stage, "ran": False, "inserted": None, "ignored": None,
            "stats": None, "source": None, "at": None})

    rows = con.execute(
        "SELECT event_at, payload FROM sim_trade_event WHERE event_type='trigger_run' "
        "ORDER BY event_at DESC LIMIT 40").fetchall()
    for r in rows:
        payload = _json_loads(r["payload"])
        stage = payload.get("stage")
        if stage not in STAGES:
            continue
        date = payload.get("signal_date") or payload.get("date") or str(r["event_at"])[:10].replace("-", "")
        date = str(date)
        if len(date) != 8 or not date.isdigit():
            continue
        s = slot(date, stage)
        if s["ran"]:
            continue
        s.update({
            "ran": True, "at": r["event_at"], "source": "event", "stats": payload,
            "inserted": payload.get("inserted", payload.get("signals")),
            "ignored": payload.get("ignored"),
        })

    if log_dir and Path(log_dir).is_dir():
        files = sorted(Path(log_dir).glob("sim_trade_run_*.jsonl"), reverse=True)[:MAX_RUN_DAYS]
        for fp in files:
            date = fp.stem.replace("sim_trade_run_", "")
            if len(date) != 8 or not date.isdigit():
                continue
            try:
                lines = fp.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    payload = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(payload, dict):
                    continue
                stage = payload.get("stage")
                if stage not in STAGES:
                    continue
                s = slot(date, stage)
                if s["ran"] and s["source"] == "event":
                    continue
                s.update({
                    "ran": True, "at": payload.get("at") or payload.get("frozen_at") or s["at"],
                    "source": "log", "stats": payload,
                    "inserted": payload.get("inserted", payload.get("signals")),
                    "ignored": payload.get("ignored"),
                })

    # 只保留最近 3 个有记录的业务日(按日期倒序), 缺阶段补 ran=false 占位
    dates = sorted(by_date.keys(), reverse=True)[:MAX_RUN_DAYS]
    out = []
    for date in dates:
        stages = [by_date[date].get(st, {"stage": st, "ran": False, "inserted": None,
                                         "ignored": None, "stats": None, "source": None, "at": None})
                  for st in STAGES]
        out.append({"date": date, "stages": stages})
    return out


def build_payload(db_path: str, out_path: str, backfill_db=None,
                  log_dir=None, etf_db=None, recent: int = 200) -> dict:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        # 公开 /data/ 链路: 只写库文件名, 不泄服务器绝对路径(审查缺陷 D6)
        "source": {"db": Path(db_path).name, "db_exists": Path(db_path).exists(),
                   "status": "ok", "note": None},
        "positions": [], "trades": [], "trade_meta": {"shown": 0, "total": 0, "limit": recent},
        "summary": None, "backfill": {"available": False, "reason": "未配置"},
        "runs": [],
    }
    if not Path(db_path).exists():
        payload["source"].update({"status": "missing", "note": "账本尚未建立, 等待首个触发器运行"})
        payload["backfill"] = export_backfill(backfill_db)
        return payload
    try:
        con = db.connect(db_path)
    except sqlite3.Error as exc:
        payload["source"].update({"status": "error", "note": "账本无法打开: " + str(exc)})
        payload["backfill"] = export_backfill(backfill_db)
        return payload
    etf_con = None
    if etf_db and Path(etf_db).exists():
        try:
            etf_con = sqlite3.connect("file:" + str(etf_db) + "?mode=ro", uri=True)
        except sqlite3.Error:
            etf_con = None
    try:
        try:
            payload["positions"] = export_positions(con, etf_con)
            payload["trades"], payload["trade_meta"] = export_trades(con, recent)
            payload["summary"] = export_summary(con, etf_con)
            payload["runs"] = export_runs(con, log_dir)
        except sqlite3.Error as exc:
            msg = str(exc)
            # 空库/未初始化库 -> empty(等待首个触发器); 损坏/无法读取 -> error(不能伪装成「等数据」)。
            if "no such table" in msg or "no such view" in msg:
                payload["source"].update({"status": "empty", "note": "账本尚未初始化: " + msg})
            else:
                payload["source"].update({"status": "error", "note": "账本无法读取: " + msg})
    finally:
        con.close()
        if etf_con is not None:
            etf_con.close()
    payload["backfill"] = export_backfill(backfill_db)
    return payload


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="导出模拟交易账本 -> static-site/data/simtrade.json")
    ap.add_argument("--db", default=str(ROOT / "data" / "sim_trade.db"))
    ap.add_argument("--out", default=str(ROOT / "static-site" / "data" / "simtrade.json"))
    ap.add_argument("--backfill-db", default=None)
    ap.add_argument("--etf-db", default=None,
                    help="etf_daily 库(取未平仓最新价); 不传则不取价(最新价为空), 不做隐式路径回退")
    ap.add_argument("--log-dir", default=str(ROOT / "data" / "logs"))
    ap.add_argument("--recent", type=int, default=200)
    args = ap.parse_args(argv)

    payload = build_payload(args.db, args.out, args.backfill_db,
                            args.log_dir, args.etf_db, args.recent)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    from util_atomic import atomic_write_json  # 与 export.py 同一原子写实现(同目录 fsync+replace)
    atomic_write_json(out_path, payload, indent=1)
    print(json.dumps({
        "out": str(out_path), "status": payload["source"]["status"],
        "positions": len(payload["positions"]), "trades": payload["trade_meta"]["shown"],
        "runs": len(payload["runs"]),
    }, ensure_ascii=False))
    # 退出码语义(审查缺陷 D5): 只有 error(账本损坏/读取失败)非零, 让发布脚本/systemd
    # 记 failed 并触发告警; missing(库还没建, 首跑前正常)与 empty(库已建未初始化)
    # 仍是正常空态 → 0, 否则首跑前每天报假失败。
    return 2 if payload["source"]["status"] == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
