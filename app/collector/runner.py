"""每日采集编排：读 config → 采指标/指数/板块 → 落库 → 日志。"""
import sys
import datetime as dt

from ..db import get_conn
from ..calendar import last_trading_day
from . import fetchers
from .base import log_collect


def _now():
    return dt.datetime.now().isoformat()


def upsert_metric(date, metric_id, value, source="akshare"):
    conn = get_conn()
    conn.execute(
        "INSERT INTO daily_metric (date, metric_id, value, source, updated_at) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT(date, metric_id) DO UPDATE SET "
        "value=excluded.value, source=excluded.source, updated_at=excluded.updated_at "
        "WHERE daily_metric.source != 'manual'",
        (date, metric_id, value, source, _now()),
    )
    conn.commit()
    conn.close()


def upsert_metrics_many(metric_id, rows):
    """rows: [(date, value), ...]"""
    conn = get_conn()
    conn.executemany(
        "INSERT INTO daily_metric (date, metric_id, value, source, updated_at) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT(date, metric_id) DO UPDATE SET "
        "value=excluded.value, source=excluded.source, updated_at=excluded.updated_at "
        "WHERE daily_metric.source != 'manual'",
        [(d, metric_id, v, "akshare", _now()) for d, v in rows],
    )
    conn.commit()
    conn.close()


def upsert_index_rows(rows):
    conn = get_conn()
    conn.executemany(
        "INSERT INTO index_daily (date, index_id, open, high, low, close, pct_change, amount) "
        "VALUES (?,?,?,?,?,?,?,?) "
        "ON CONFLICT(date, index_id) DO UPDATE SET "
        "open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close, "
        "pct_change=excluded.pct_change, amount=excluded.amount",
        rows,
    )
    conn.commit()
    conn.close()


def upsert_board_rows(rows):
    conn = get_conn()
    conn.executemany(
        "INSERT INTO board_daily (date, board_type, board_name, pct_change, net_inflow) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT(date, board_type, board_name) DO UPDATE SET "
        "pct_change=excluded.pct_change, net_inflow=excluded.net_inflow",
        rows,
    )
    conn.commit()
    conn.close()


def run(date=None, verbose=True):
    if date is None:
        date = last_trading_day()
    cfg = fetchers.load_config()
    ok = fail = 0
    details = []

    # 1) 单值指标
    for m in cfg.get("metrics", []):
        if not m.get("enabled"):
            continue
        if m.get("type") == "derived":
            continue  # 综合分/衍生指标由 compute 模块产出
        mid = m["id"]
        func = m.get("func", "")
        try:
            if func.startswith("direct:"):
                rows, msg = fetchers.collect_direct(m)
                if rows:
                    upsert_metrics_many(mid, rows)
                    ok += 1
                    details.append((mid, "ok", f"{len(rows)} rows"))
                    log_collect(date, mid, "ok", f"{len(rows)} rows")
                else:
                    fail += 1
                    details.append((mid, "fail", msg))
                    log_collect(date, mid, "error", msg)
            elif func.startswith("tencent:"):
                val, msg = fetchers.collect_tencent(m, date)
                if val is not None:
                    upsert_metric(date, mid, val)
                    ok += 1
                    details.append((mid, "ok", f"{val:.4g}"))
                    log_collect(date, mid, "ok", str(val))
                else:
                    fail += 1
                    details.append((mid, "fail", msg))
                    log_collect(date, mid, "error", msg)
            elif func in fetchers.SERIES_FUNCS:
                rows, msg = fetchers.collect_series(m)
                if rows:
                    upsert_metrics_many(mid, rows)
                    ok += 1
                    details.append((mid, "ok", f"{len(rows)} rows"))
                    log_collect(date, mid, "ok", f"{len(rows)} rows")
                else:
                    fail += 1
                    details.append((mid, "fail", msg))
                    log_collect(date, mid, "error", msg)
            else:
                val, msg = fetchers.collect_snapshot(m, date)
                if val is not None:
                    upsert_metric(date, mid, val)
                    ok += 1
                    details.append((mid, "ok", f"{val:.4g}"))
                    log_collect(date, mid, "ok", str(val))
                else:
                    fail += 1
                    details.append((mid, "fail", msg))
                    log_collect(date, mid, "error", msg)
        except Exception as e:  # noqa: BLE001
            fail += 1
            details.append((mid, "fail", str(e)))
            log_collect(date, mid, "error", str(e))

    # 2) 指数（拉近 400 天，等于自动回填）
    start = (dt.datetime.strptime(date, "%Y%m%d") - dt.timedelta(days=400)).strftime("%Y%m%d")
    for idx in cfg.get("indices", []):
        if not idx.get("enabled", True):
            continue
        try:
            rows, msg = fetchers.collect_index(idx, start, date)
            if rows:
                upsert_index_rows(rows)
                ok += 1
                details.append((idx["id"], "ok", f"{len(rows)} rows"))
            else:
                fail += 1
                details.append((idx["id"], "fail", msg))
        except Exception as e:  # noqa: BLE001
            fail += 1
            details.append((idx["id"], "fail", str(e)))

    # 3) 板块
    for b in cfg.get("boards", []):
        if not b.get("enabled", True):
            continue
        try:
            rows, msg = fetchers.collect_board(b, date)
            if rows:
                upsert_board_rows(rows)
                ok += 1
                details.append((b["type"], "ok", f"{len(rows)} rows"))
            else:
                fail += 1
                details.append((b["type"], "fail", msg))
        except Exception as e:  # noqa: BLE001
            fail += 1
            details.append((b["type"], "fail", str(e)))

    # 4) 行业资金流 + 换手率（F2，东财 fflow/kline 端点，非 clist 不被封）
    try:
        from . import industry_extras
        res = industry_extras.collect_industry_extras(verbose=verbose)
        ok += res["ok"]
        fail += res["fail"]
        details.extend(res["details"])
    except Exception as e:  # noqa: BLE001
        fail += 1
        details.append(("industry_extras", "fail", str(e)))

    # 5) 全 A 股日线增量更新（D1，东财 push2his，封 IP 时跳过不阻塞其它采集）
    # 仅对已有 progress 的 code 增量（已 backfill 过的）；未 backfill 的由
    # `python -m app.collector.stock_daily full` 手动跑（避免 scheduler 触发 5500 只全量回填）。
    try:
        from . import stock_daily
        prog = stock_daily.load_progress()
        todo = [c for c in prog.keys()]  # 已 backfill 的 code 子集
        if todo:
            res = stock_daily.run_batch(todo, incremental=True, verbose=verbose)
            ok += res["ok"]
            fail += res["fail"]
            details.append(("stock_daily", "ok" if res["fail"] == 0 else "fail",
                            f"+{res['total_rows']} rows, {res['ok']} ok/{res['fail']} fail "
                            f"({len(todo)} codes)"))
        else:
            details.append(("stock_daily", "ok", "skip (no progress yet, run `stock_daily full` manually)"))
    except stock_daily.CooldownError as e:
        # 封 IP：不阻塞主采集，记 fail 等下次 scheduler 重试
        fail += 1
        details.append(("stock_daily", "fail", f"cooldown (剩余 {len(e.remaining_codes)})"))
    except Exception as e:  # noqa: BLE001
        fail += 1
        details.append(("stock_daily", "fail", str(e)[:150]))

    # 6) BaoStock 日线增量更新（D3，BaoStock 走自己服务，不受东财封锁影响）
    # 仅对已有 progress 的 code 增量（已 backfill 过的）；未 backfill 的由
    # `python -m app.collector.baostock_daily recent` 手动跑（避免 scheduler 触发全量回填）。
    try:
        from . import baostock_daily
        prog = baostock_daily.load_progress()
        todo = [c for c, v in prog.items() if v.get("r")]  # 已 backfill recent 段的 code
        if todo:
            res = baostock_daily.run_update(todo, verbose=verbose)
            ok += res["ok"]
            fail += res["fail"]
            details.append(("baostock_daily", "ok" if res["fail"] == 0 else "fail",
                            f"+{res['total_rows']} rows, {res['ok']} ok/{res['fail']} fail "
                            f"({len(todo)} codes)"))
        else:
            details.append(("baostock_daily", "ok",
                            "skip (no progress yet, run `baostock_daily recent` manually)"))
    except Exception as e:  # noqa: BLE001
        fail += 1
        details.append(("baostock_daily", "fail", str(e)[:150]))

    # 7) mootdx 日线增量更新（D1 主力，TCP 7709 不封 IP，akshare 东财封锁后改用）
    # 仅对已有 progress 的 code 增量（已 backfill 过的）；未 backfill 的由
    # `python -m app.collector.mootdx_daily full` 手动跑（避免 scheduler 触发全量回填）。
    try:
        from . import mootdx_daily
        prog = mootdx_daily.load_progress()
        todo = list(prog.keys())  # 已 backfill 的 code 子集
        if todo:
            res = mootdx_daily.run_batch(todo, incremental=True, verbose=verbose)
            ok += res["ok"]
            fail += res["fail"]
            details.append(("mootdx_daily", "ok" if res["fail"] == 0 else "fail",
                            f"+{res['total_rows']} rows, {res['ok']} ok/{res['fail']} fail "
                            f"({len(todo)} codes)"))
        else:
            details.append(("mootdx_daily", "ok",
                            "skip (no progress yet, run `mootdx_daily full` manually)"))
    except Exception as e:  # noqa: BLE001
        fail += 1
        details.append(("mootdx_daily", "fail", str(e)[:150]))

    # 8) 行业内宽度增量更新（F3，mootdx 增量后算近 15 天行业内涨跌/涨停/炸板）
    try:
        from . import industry_width
        res = industry_width.run_recent(days=15)
        if "error" in res:
            details.append(("industry_width", "ok", f"skip ({res['error']})"))
        else:
            details.append(("industry_width", "ok",
                            f"+{res.get('computed_rows',0)} rows recent"))
    except Exception as e:  # noqa: BLE001
        fail += 1
        details.append(("industry_width", "fail", str(e)[:150]))

    if verbose:
        print(f"=== 采集 {date} 完成: ok={ok} fail={fail} ===")
        for mid, st, msg in details:
            print(f"  [{st:>4}] {mid:<26} {msg}")
    return {"ok": ok, "fail": fail, "details": details}


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else None
    run(d)
