"""retry_failed_metrics.py - 单项指标失败自动重采(自动修复机制 2026-07-31)。

读 collect_log 当日最新 status=error 的 metric_id,对每个 error 指标调对应
重采函数(collect_snapshot/collect_direct)。成功则 upsert daily_metric + 写
collect_log ok(覆盖 error,让 collect_health 变 ok);失败则保留 error(等下次
self_heal 重试或明日 update_all 兜底)。

触发:self_heal.sh 每15分钟调用(在任务级 force-heal 之前,轻量重采优先)。
非交易日跳过。返回重采结果摘要。

设计要点:
- 复用 fetchers.collect_snapshot/collect_direct(含 2026-07-31 zt_pool 交叉验证修复:
  跌停池空+涨停池有数据=真0跌停,写0+ok,不再误报 error)
- 只重采当日 error 项(不重采历史),避免长跑
- 不受 self_heal 每日3次上限限制(单项重采轻量,不像 force 重跑整个 update_all)
- 重采成功写 collect_log ok + 清旧非 ok 记录,queries.collect_health 取最新一条变 ok
- 重采仍失败保留 error,下次 self_heal(15分钟后)再试,直到成功或当日结束

场景(2026-07-31 7/31 跌停池空事故):
- 17:50 update_all 采 stock_zt_pool_dtgc_em 空,collect_log error
- collect_health level=error,线上小红点
- 18:07 self_heal 调本脚本 -> retry a_width_dt_count -> collect_snapshot 交叉验证
  涨停池99只 -> 跌停池空=真0,写0+ok -> collect_health 变 ok,红点消失
"""
import datetime as dt
import sys
from pathlib import Path

# 定位 REPO(脚本所在目录的父目录)。用 .absolute() 不用 .resolve():
# trade-data/scripts 是 symlink -> trade/scripts,.resolve() 会解析到 trade 致 sys.path 加 trade,
# app.db 加载自 trade/app/db.py 读 trade/data/sentiment.db(滞后镜像,§9 事故根因)。
# .absolute() 不解析 symlink,从 trade-data 跑时 __file__=trade-data/scripts/retry_...,
# parent.parent=trade-data,sys.path 加 trade-data,app.db 读 trade-data/data/sentiment.db(主库)。
_ROOT = Path(__file__).absolute().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.calendar import is_trading_day
from app.collector.base import log_collect
from app.collector.fetchers import load_config, collect_snapshot, collect_direct
from app.collector.runner import upsert_metric, upsert_metrics_many
from app.db import get_conn


def get_failed_metrics(date: str) -> list[dict]:
    """读 collect_log 当日最新 status=error 的 metric_id 列表(去重,取最新一条)。

    与 queries.collect_health 同逻辑:ORDER BY run_at DESC,_seen 去重保留最新。
    只返回最新状态非 ok 的指标。
    """
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT metric_id, status, message FROM collect_log "
            "WHERE run_date=? ORDER BY run_at DESC",
            (date,),
        ).fetchall()
    finally:
        conn.close()
    seen: set[str] = set()
    failed: list[dict] = []
    for r in rows:
        mid = r["metric_id"]
        if mid in seen:
            continue
        seen.add(mid)
        if r["status"] != "ok":
            failed.append({"metric_id": mid, "message": r["message"] or ""})
    return failed


def _clear_old_errors(date: str, mid: str) -> None:
    """清同 run_date 同 metric_id 旧非 ok 记录(让 collect_health 干净,同 backfill_metrics.sh 逻辑)。"""
    conn = get_conn()
    try:
        conn.execute(
            "DELETE FROM collect_log WHERE run_date=? AND metric_id=? AND status<>?",
            (date, mid, "ok"),
        )
        conn.commit()
    finally:
        conn.close()


def retry_metric(mid: str, date: str, cfg: dict) -> tuple[bool, str]:
    """重采单个指标。返回 (success, msg)。

    复用 collect_snapshot/collect_direct(含 zt_pool 交叉验证修复)。
    成功:upsert daily_metric + 清旧 error + 写 collect_log ok。
    失败:保留原 error(不写新记录,避免 collect_log 膨胀)。
    """
    m = next((x for x in cfg.get("metrics", []) if x.get("id") == mid), None)
    if not m:
        return False, f"no config for {mid}"
    if not m.get("enabled", True):
        return False, f"disabled {mid}"
    func = m.get("func", "")
    if not func or func == "TODO":
        return False, f"no func/TODO {mid}"
    try:
        if func.startswith("direct:"):
            rows, msg = collect_direct(m)
            if rows:
                upsert_metrics_many(mid, rows)
                _clear_old_errors(date, mid)
                log_collect(date, mid, "ok", f"{len(rows)} rows (retry)")
                return True, f"{len(rows)} rows"
            return False, msg or "direct empty"
        # 快照型(含 zt_pool 系列,collect_snapshot 内置交叉验证)
        val, msg = collect_snapshot(m, date)
        if val is not None:
            upsert_metric(date, mid, val)  # source 默认 akshare
            _clear_old_errors(date, mid)
            log_collect(date, mid, "ok", f"{val} (retry: {msg})")
            return True, f"{val} ({msg})"
        return False, msg or "snapshot None"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    today = dt.date.today().strftime("%Y%m%d")
    if not is_trading_day(today):
        print(f"[retry] 非交易日({today}),跳过", flush=True)
        return 0
    cfg = load_config()
    failed = get_failed_metrics(today)
    if not failed:
        print(f"[retry] {today} 无 error 指标,无需重采", flush=True)
        return 0
    failed_ids = [f["metric_id"] for f in failed]
    print(f"[retry] {today} 发现 {len(failed)} 个 error 指标: {failed_ids}", flush=True)
    ok = fail = 0
    for f in failed:
        mid = f["metric_id"]
        success, msg = retry_metric(mid, today, cfg)
        if success:
            ok += 1
            print(f"  [ok] {mid}: {msg}", flush=True)
        else:
            fail += 1
            print(f"  [fail] {mid}: {msg} (原 error: {f['message']})", flush=True)
    print(f"=== retry 完成 ok={ok} fail={fail} ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
