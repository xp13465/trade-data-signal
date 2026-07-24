"""每日采集编排：读 config -> 采指标/指数/板块 -> 落库 -> 日志。

支持子集采集（pipeline 并行模式）：run(date, steps=[...]) 只跑指定 step，
不传 steps 则全跑（向后兼容）。step 名：
  metrics / indices / boards / industry_extras / stock_daily / baostock /
  mootdx / industry_width / width_history / futures / ad_line / turnover
依赖由调用方保证（如 width pipeline 传 ["mootdx","industry_width","width_history"]）。
"""
import signal
import sys
import datetime as dt

from ..db import get_conn
from ..calendar import last_trading_day
from . import fetchers
from .base import log_collect


def _now():
    return dt.datetime.now().isoformat()


def _want(steps, name):
    """steps=None 跑全部；否则只跑 steps 中列出的 step。"""
    return steps is None or name in steps


def _mootdx_timeout_handler(signum, frame):  # noqa: ARG001
    """SIGALRM 处理器：mootdx step 超 30min 抛 TimeoutError 跳过，防阻塞 update_all。"""
    raise TimeoutError("mootdx step timeout 30min")


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


def run(date=None, verbose=True, steps=None):
    if date is None:
        date = last_trading_day()
    cfg = fetchers.load_config()
    ok = fail = 0
    details = []

    # 1) 单值指标
    if _want(steps, "metrics"):
        for m in cfg.get("metrics", []):
            if not m.get("enabled"):
                continue
            if m.get("type") == "derived":
                continue  # 综合分/衍生指标由 compute 模块产出
            mid = m["id"]
            func = m.get("func", "")
            if not func or func == "TODO":
                continue  # 派生/专属采集器指标(width_history/cleanup_d3d2 产出),主 pipeline 不采不记
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
    if _want(steps, "indices"):
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

        # step2 采后校验 + 多源补采（主源新浪当日延迟 -> baostock/腾讯兜底，
        # 避免首页涨幅 0% / 恐贪卡片缺失；详见 index_backfill.py）
        try:
            from .index_backfill import verify_and_backfill_indices
            bk_ok, bk_fail, bk_details = verify_and_backfill_indices(date, verbose=verbose)
            ok += bk_ok
            fail += bk_fail
            details.extend(bk_details)
        except Exception as e:  # noqa: BLE001
            if verbose:
                print(f"  [校验] 补采异常: {e}")

    # 3) 板块
    if _want(steps, "boards"):
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
    if _want(steps, "industry_extras"):
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
    if _want(steps, "stock_daily"):
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

    # 6) BaoStock 日线增量更新 -- 默认跳过：baostock_daily_raw 仅手动 cleanup_d3d2 读，
    # 日常看板/导出不依赖（全 A 股日线主力是 mootdx_daily）。5072 codes 串行 + 45% 失败
    # 重试耗时 ~1h，故日常不跑；需补数据时手动 `python -m app.collector.baostock_daily recent`，
    # 或设环境变量 RUN_BAOSTOCK=1 临时启用本步。
    if _want(steps, "baostock"):
        import os
        if os.environ.get("RUN_BAOSTOCK"):
            try:
                from . import baostock_daily, baostock_parallel
                prog = baostock_daily.load_progress()
                # 2026-07-23 修复：progress 可能只有部分 code（历史全量 backfill 未跑完），
                # 跑前先 reconcile 从 DB 重建（与 turnover step 同口径），否则 todo 只含
                # progress 已有的少数 code，致 run_update 只采少数 code
                if len(prog) < 4000:
                    print(f"[baostock] progress 只有 {len(prog)} codes < 4000，先 reconcile 从 DB 重建", flush=True)
                    baostock_daily.reconcile()
                    prog = baostock_daily.load_progress()
                todo = [c for c, v in prog.items() if v.get("r")]  # 已 backfill recent 段的 code
                if todo:
                    res = baostock_parallel.run_update_parallel(todo, n_workers=4, verbose=verbose)
                    ok += res["ok"]
                    fail += res["fail"]
                    details.append(("baostock_daily", "ok" if res["fail"] == 0 else "fail",
                                    f"+{res['total_rows']} rows, {res['ok']} ok/{res['fail']} fail "
                                    f"({len(todo)} codes, parallel)"))
                else:
                    details.append(("baostock_daily", "ok", "skip (no progress)"))
            except Exception as e:  # noqa: BLE001
                fail += 1
                details.append(("baostock_daily", "fail", str(e)[:150]))
        else:
            details.append(("baostock_daily", "ok",
                            "skip (日常不跑; 需时 RUN_BAOSTOCK=1 或手动 `baostock_daily recent`)"))

    # 7) mootdx 日线增量更新（D1 主力，TCP 7709 不封 IP，akshare 东财封锁后改用）
    # progress 非空：仅对已 backfill 的 code 增量（避免 scheduler 触发 mootdx 全量
    #   回填——mootdx TCP 串行 5527 只~7h 会阻塞 update_all）。
    # progress 为空（mootdx 从未跑过）：不再静默 skip，直接调 baostock fallback
    #   采 all_codes（HTTP 源，不阻塞 scheduler；2016-至今近 10 年段，1990-2015 老段
    #   由 `baostock_daily old` 单独补）。fallback 写 mootdx_progress.json，mootdx
    #   恢复后自动回归主力。**不走 run_batch 全量**（mootdx 7h）以遵守"防 scheduler
    #   全量回填"设计约束——换 baostock fallback 实现路径而非 mootdx 全量。
    if _want(steps, "mootdx"):
        # 30min 超时保护（P0-b，2026-07-22）：mootdx 7/17 起 bestip 全空 + baostock
        # fallback 串行 5527 只~7h，7-21 18:03 阻塞 width pipeline 被 SIGTERM 杀（只采
        # 85 只）。signal.alarm 主线程同步调用最简（pipeline.sh 各 step 独立子进程，
        # run() 在主线程）；SIGALRM 中断 socket syscall 抛 TimeoutError，跳过 mootdx
        # step 继续跑 industry_width/width_history（用已有数据算），防复发。
        _prev_sigalrm = signal.signal(signal.SIGALRM, _mootdx_timeout_handler)
        signal.alarm(1800)  # 30min
        try:
            try:
                from . import mootdx_daily
                prog = mootdx_daily.load_progress()
                if prog:
                    todo = list(prog.keys())  # 已 backfill 的 code 子集
                    # update_all 自动路径用更激进的熔断阈值(15 < 默认 50)：部分故障
                    # (批量全 empty)15 只×5s≈75s 即切 baostock fallback，比默认 250s
                    # 快 3 倍；整体故障(client init 失败)已在 run_batch 秒级切 fallback。
                    # 正常偶发 empty 不会连续 15 只，误触发风险低。CLI full/update 手动
                    # 跑仍用默认 50(容错优先，避免误切)。
                    res = mootdx_daily.run_batch(todo, incremental=True, verbose=verbose,
                                                 consecutive_fail_limit=15)
                    ok += res["ok"]
                    fail += res["fail"]
                    details.append(("mootdx_daily", "ok" if res["fail"] == 0 else "fail",
                                    f"+{res['total_rows']} rows, {res['ok']} ok/{res['fail']} fail "
                                    f"({len(todo)} codes)"))
                else:
                    # progress 空：mootdx 从未跑过，直接 baostock fallback 采 all_codes
                    # （跳过 mootdx 尝试；不走 run_batch 全量避免 7h 阻塞 scheduler）。
                    all_codes = mootdx_daily.load_codes()
                    today = dt.date.today().strftime("%Y%m%d")
                    fb_rows, fb_ok, fb_skip = mootdx_daily._run_baostock_fallback(
                        all_codes, progress=prog, incremental=True,
                        today=today, verbose=verbose)
                    mootdx_daily.save_progress(prog)  # fallback 内部每 5 只存盘，补末尾
                    ok += fb_ok
                    fail += len(all_codes) - fb_ok - fb_skip
                    details.append(("mootdx_daily", "ok" if fb_ok else "fail",
                                    f"fallback(baostock): +{fb_rows} rows, {fb_ok} ok/"
                                    f"{len(all_codes) - fb_ok - fb_skip} fail/{fb_skip} skip_bj "
                                    f"({len(all_codes)} codes, progress was empty)"))
            except TimeoutError:
                fail += 1
                details.append(("mootdx_daily", "fail",
                                "timeout 30min, skip (后续 industry_width/width_history 用已有数据算)"))
            except Exception as e:  # noqa: BLE001
                fail += 1
                details.append(("mootdx_daily", "fail", str(e)[:150]))
        finally:
            signal.alarm(0)  # 取消未触发的 alarm
            signal.signal(signal.SIGALRM, _prev_sigalrm)  # 恢复原 handler

    # 8) 行业内宽度增量更新（F3，mootdx 增量后算近 15 天行业内涨跌/涨停/炸板）
    if _want(steps, "industry_width"):
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

    # 9) 全市场宽度近期重算（D2，mootdx 增量后算近 30 天宽度，覆盖漏跑工作日）
    #    run_recent 从 mootdx_daily_raw 算 zt/dt/zb/seal_rate/up/down/amount，不依赖
    #    collect_snapshot 当日快照。漏跑工作日（如周一忘周二跑）下次执行时重算近 30 天
    #    自动补全。A1 近端值保护：up/down/amount 跳过已有 akshare 值的日期；zt/dt/zb
    #    全段覆盖（收盘封板口径替代 zt_pool 触板口径）。upsert WHERE source != 'manual'。
    if _want(steps, "width_history"):
        try:
            from . import width_history
            res = width_history.run_recent(days=30)
            if "error" in res:
                details.append(("width_history", "ok", f"skip ({res['error']})"))
            else:
                details.append(("width_history", "ok",
                                f"+{res.get('computed_days',0)} days recent"))
        except Exception as e:  # noqa: BLE001
            fail += 1
            details.append(("width_history", "fail", str(e)[:150]))

    # 10) 期货机构净多空持仓采集 + 准确率计算
    if _want(steps, "futures"):
        try:
            from . import futures_position as fp_collector
            fp_collector.collect_daily(date)
            details.append(("futures_position", "ok", f"collected {date}"))
            ok += 1
        except Exception as e:  # noqa: BLE001
            fail += 1
            details.append(("futures_position", "fail", str(e)[:150]))

        try:
            from ..compute.futures_position import compute_accuracy
            n_acc = compute_accuracy(date=date)
            details.append(("futures_accuracy", "ok", f"{n_acc} rows"))
            ok += 1
        except Exception as e:  # noqa: BLE001
            fail += 1
            details.append(("futures_accuracy", "fail", str(e)[:150]))

    # 11) AD Line（腾落线）+ 涨跌家数比
    # 注：compute/runner.run() 也会算 ad_line，此处保留供全跑模式向后兼容；
    # pipeline 模式下由对应 pipeline 跑 compute_runner 覆盖，本步可被 steps 排除。
    if _want(steps, "ad_line"):
        try:
            from ..compute.ad_line import compute_ad_line, store_ad_line
            out = compute_ad_line()
            n = store_ad_line(out)
            details.append(("ad_line", "ok", f"{n} rows derived"))
            ok += 1
        except Exception as e:  # noqa: BLE001
            fail += 1
            details.append(("ad_line", "fail", str(e)[:150]))

    # 12) 换手率分布（BaoStock 增量 -> cleanup_d3d2 算 a_turnover_* 入 daily_metric）
    # a_turnover_mean/median/p90/p10/gt5_pct 是大盘信号 A股「换手率分布分位数」「换手率>5%
    # 家数占比」图表数据源。baostock_daily_raw 增量慢（5527 codes 串行 ~10-30min），
    # 仅 RUN_BAOSTOCK=1 时跑（turnover pipeline 设此 env）；cleanup_d3d2 增量快（只算新
    # 交易日），总是跑。历史根因：本步曾不自动跑 -> a_turnover 停滞 9 天（2026-07-15 修复）。
    if _want(steps, "turnover"):
        import os
        if os.environ.get("RUN_BAOSTOCK"):
            try:
                from . import baostock_daily, baostock_parallel
                prog = baostock_daily.load_progress()
                # 2026-07-23 修复：progress 可能只有部分 code（历史全量 backfill 未跑完），
                # 跑前先 reconcile 从 DB 重建，否则 todo 只含 progress 已有的少数 code，
                # 致 run_update 只采少数 code -> a_turnover_* 5项 缺 T 日数据角标滞后
                if len(prog) < 4000:
                    print(f"[turnover] progress 只有 {len(prog)} codes < 4000，先 reconcile 从 DB 重建", flush=True)
                    baostock_daily.reconcile()
                    prog = baostock_daily.load_progress()
                todo = [c for c, v in prog.items() if v.get("r")]
                if todo:
                    res = baostock_parallel.run_update_parallel(todo, n_workers=4, verbose=verbose)
                    ok += res["ok"]
                    fail += res["fail"]
                    details.append(("baostock_turnover", "ok" if res["fail"] == 0 else "fail",
                                    f"+{res['total_rows']} rows, {res['ok']} ok/{res['fail']} fail "
                                    f"({len(todo)} codes, parallel)"))
                else:
                    details.append(("baostock_turnover", "ok", "skip (no progress)"))
            except Exception as e:  # noqa: BLE001
                fail += 1
                details.append(("baostock_turnover", "fail", str(e)[:150]))
        else:
            details.append(("baostock_turnover", "ok",
                            "skip (需 RUN_BAOSTOCK=1; turnover pipeline 已设)"))
        # 算换手率分布（增量，快；部分采集日自动跳过待补全）
        try:
            from . import cleanup_d3d2
            tres = cleanup_d3d2.run_turnover()
            if "error" in tres:
                details.append(("turnover_dist", "ok", f"skip ({tres['error']})"))
            else:
                details.append(("turnover_dist", "ok",
                                f"+{tres.get('days', 0)} days, {tres.get('written', 0)} rows, "
                                f"skipped_partial={tres.get('skipped_partial', 0)}"))
                ok += 1
        except Exception as e:  # noqa: BLE001
            fail += 1
            details.append(("turnover_dist", "fail", str(e)[:150]))

    if verbose:
        print(f"=== 采集 {date} 完成 (steps={steps or 'all'}): ok={ok} fail={fail} ===")
        for mid, st, msg in details:
            print(f"  [{st:>4}] {mid:<26} {msg}")
    return {"ok": ok, "fail": fail, "details": details}


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else None
    run(d)
