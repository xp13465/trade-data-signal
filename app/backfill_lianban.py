#!/usr/bin/env python3
"""连板(最高连板 a_width_max_lianban)历史回补:dry-run 对账 + 写库。

背景
====
daily_metric.a_width_max_lianban 仅 20260612 起(东财涨停池历史只滚动保留近
2-3 周),历史缺值。根因三层:
1. app/collector/width_history.py 用 mootdx 回填 7 项宽度指标,唯独漏最高连板
   —— mootdx 历史段每天仅 ~85 只样本股,推不出全市场最高连板。
2. app/backfill.py 的 skip 判据用 _have("a_width_zt_count"),zt_count 被全段回填
   后 → 所有历史日 skip,连板从没补过。
3. 东财涨停池历史已清空 → 20260612 即现有起点。

唯一可行历史源 = 同花顺官方 API(FAPI)涨停池,实测 20210901 起逐交易日可用,
字段 continue_day_cnt 等价东财「连板数」(映射见 app/collector/fapi_fallback.py
_zt_df:continue_day_cnt -> 连板数列)。

口径陷阱(FAPI 含 ST,东财不含)
==============================
FAPI 涨停池含 ST 股,东财涨停池不含。实测 20260701:FAPI 全量 max=7
(top=ST中装)vs 东财当时=3,全是 ST 撑的。
→ 取值前必须排除名称含 ST 的股票。判定规则 = 名称字符串宽松包含子串 "ST"
  (覆盖 *ST / ST / SST 等形态;东财涨停池不含 ST,故排除后才是东财可比口径)。
  排除后与现有重叠段对账一致率 98.5%(含 ST 仅 84%)。

写库保护
========
ON CONFLICT DO UPDATE ... WHERE daily_metric.source != 'manual'
(防覆盖手动补录,与 app/collector/width_history.py upsert_width 同款)。

CLI
====
python -m app.backfill_lianban --dry-run --start 20210901 --end 20260611
python -m app.backfill_lianban --dry-run --start 20210901 --db /tmp/x.db --out /tmp/x.json
python -m app.backfill_lianban --start 20210901   # 真写库(需用户单独授权)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sqlite3
import sys
import time

from .collector.fapi_fallback import fetch_zt_fallback

# ── 与 fapi_daily.py 同款重试/退避(fapi_fallback 自身不重试,外层按此策略兜)──
RETRY = 3
BACKOFF = [5, 15, 30]  # 秒
# FAPI 是外部服务,逐日请求节流(随机化防突发)
THROTTLE = (0.3, 0.8)

# ST 排除判定规则:名称宽松包含子串 "ST"(覆盖 *ST / ST / SST 等形态)。
# FAPI 涨停池含 ST 股,东财涨停池不含,排除后才是东财可比口径。
ST_SUBSTR = "ST"

METRIC_ID = "a_width_max_lianban"
SOURCE = "fapi"

# 与 app/db.py SCHEMA 的 daily_metric 表定义一致(--db 直连时兜底建表)
_DAILY_METRIC_DDL = """
CREATE TABLE IF NOT EXISTS daily_metric (
  date TEXT NOT NULL,
  metric_id TEXT NOT NULL,
  value REAL,
  source TEXT,
  updated_at TEXT,
  PRIMARY KEY (date, metric_id)
)
"""


def _last_trading_day_before(end: str | None) -> str:
    """返回 <= end(默认昨天)的最近交易日(YYYYMMDD),复用 app.calendar。"""
    if end:
        return end
    d = dt.date.today() - dt.timedelta(days=1)
    from .calendar import last_trading_day
    return last_trading_day(d)


def _connect(db: str | None) -> sqlite3.Connection:
    """未指定 --db 走 app.db.get_conn()(默认路径+自动建表/迁移);
    指定 --db 直连给定路径(sqlite3,幂等建 daily_metric 表)。"""
    if db is None:
        from .db import get_conn
        return get_conn()
    conn = sqlite3.connect(db, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.executescript(_DAILY_METRIC_DDL)
    return conn


def _fetch_zt_with_retry(date: str) -> tuple[object, str]:
    """调 fetch_zt_fallback,失败按 fapi_daily 策略重试 RETRY 次。
    成功也要随机节流(FAPI 是外部服务,别打太猛)。
    返回 (df or None, msg)。df 为 None = 重试后仍失败。"""
    last = None
    for i in range(RETRY):
        df, msg = fetch_zt_fallback("stock_zt_pool_em", date)
        if df is not None:
            time.sleep(random.uniform(*THROTTLE))
            return df, msg
        last = msg
        if i < RETRY - 1:
            time.sleep(BACKOFF[i])
    return None, f"重试{RETRY}次仍失败: {last}"


def max_lianban_ex_st(df, with_st: bool = False) -> tuple[float | None, int, int]:
    """返回 (排除 ST 后 max 连板, 被排除 ST 数, 池子总行数)。

    - with_st=False(默认):排除名称含 ST_SUBSTR 的股票,东财可比口径。
    - with_st=True:含 ST 全量 max(仅作对账对照,验证排除开关在起作用)。
    - 排除后无股票或连板全 NaN → 返回 (None, ...),由调用方记 gap。
    """
    total = len(df)
    if total == 0:
        return None, 0, 0
    name = df["名称"].astype(str)
    if with_st:
        series = df["连板数"]
        return float(series.max()), 0, total
    mask_st = name.str.contains(ST_SUBSTR, na=False)
    series = df.loc[~mask_st, "连板数"]
    if series.empty:
        return None, int(mask_st.sum()), total
    if series.isna().all():
        return None, int(mask_st.sum()), total
    return float(series.max()), int(mask_st.sum()), total


def _existing_map(conn: sqlite3.Connection, start: str, end: str) -> dict[str, float]:
    """现有 a_width_max_lianban 在 [start,end] 内的 (date -> value)。"""
    rows = conn.execute(
        "SELECT date, value FROM daily_metric WHERE metric_id=? "
        "AND date BETWEEN ? AND ? ORDER BY date",
        (METRIC_ID, start, end),
    ).fetchall()
    return {r["date"]: r["value"] for r in rows if r["value"] is not None}


def backfill_lianban(start: str, end: str, *, db: str | None = None,
                     dry_run: bool = True, with_st: bool = False,
                     verbose: bool = True) -> dict:
    """逐交易日回补最高连板。dry_run=True 一行都不写库,只输出对账。

    返回 dict:dates(总交易日)/success/gaps/overlap 对账/new 增量 摘要。
    """
    from .calendar import trading_days_between

    conn = _connect(db)
    try:
        dates = trading_days_between(start, end)
        existing = _existing_map(conn, start, end)
        if verbose:
            print(f"回补连板 {start}~{end}:交易日 {len(dates)},现有值 {len(existing)} 天"
                  f"(重叠 {len(set(dates) & set(existing))} 天)", flush=True)

        rows: list[dict] = []   # 待写/已算行
        gaps: list[dict] = []   # gap 清单
        for i, d in enumerate(dates):
            df, msg = _fetch_zt_with_retry(d)
            if df is None:
                gaps.append({"date": d, "reason": msg})
                continue
            if len(df) == 0:
                gaps.append({"date": d, "reason": f"FAPI 涨停池空(真0或当日无数据): {msg}"})
                continue
            value, st_count, total = max_lianban_ex_st(df, with_st=with_st)
            if value is None:
                gaps.append({"date": d,
                             "reason": f"全部被 ST 排除(排除{st_count}/{total}行,含ST时无连板可取值)"})
                continue
            rows.append({"date": d, "value": value, "source": SOURCE,
                         "st_excluded": st_count, "pool_rows": total})
            if dry_run:
                if d in existing:
                    tag = "重叠-对账"
                else:
                    tag = "增量"
                if verbose:
                    print(f"  {tag} {d}: value={value:g} (池{total} 排除ST{st_count})"
                          + (f" 现库={existing[d]:g}" if d in existing else ""), flush=True)
            else:
                _upsert(conn, d, value)

        if not dry_run:
            conn.commit()

        # ── 对账 ──
        overlap_dates = sorted(set(dates) & set(existing))
        mismatch = []
        same = 0
        for d in overlap_dates:
            new_v = next((r["value"] for r in rows if r["date"] == d), None)
            if new_v is None:
                mismatch.append({"date": d, "existing": existing[d], "fapi": None})
                continue
            if abs(new_v - existing[d]) < 1e-9:
                same += 1
            else:
                mismatch.append({"date": d, "existing": existing[d], "fapi": new_v})
        overlap_rate = same / len(overlap_dates) if overlap_dates else None

        new_dates = sorted(r["date"] for r in rows if r["date"] not in existing)
        return {
            "start": start, "end": end, "with_st": with_st,
            "total_trading_days": len(dates),
            "success_days": len(rows), "gap_days": len(gaps),
            "overlap_total": len(overlap_dates), "overlap_same": same,
            "overlap_rate": overlap_rate, "mismatch_days": mismatch,
            "increment_dates": new_dates,
            "gaps": gaps,
            "_all_dates": dates, "_rows": rows,
        }
    finally:
        conn.close()


def _upsert(conn: sqlite3.Connection, date: str, value: float) -> None:
    """写库 ON CONFLICT ... WHERE source != 'manual'(防覆盖手动补录,width_history 同款)。"""
    conn.execute(
        "INSERT INTO daily_metric (date, metric_id, value, source, updated_at) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT(date, metric_id) DO UPDATE SET "
        "value=excluded.value, source=excluded.source, updated_at=excluded.updated_at "
        "WHERE daily_metric.source != 'manual'",
        (date, METRIC_ID, float(value), SOURCE, dt.datetime.now().isoformat()),
    )


def _fmt_month_summary(result: dict) -> list[dict]:
    """增量段按月聚合:交易日数/成功数/gap 数/当月 max 连板分布(含分位数)。"""
    from collections import Counter

    months: dict[str, dict] = {}
    for d in result["_all_dates"]:
        y, m = d[:4], d[4:6]
        months.setdefault(y + "-" + m, {"trading_days": 0, "success": 0, "gaps": 0, "values": []})
        months[y + "-" + m]["trading_days"] += 1
    for r in result["_rows"]:
        y, m = r["date"][:4], r["date"][4:6]
        months.setdefault(y + "-" + m, {"trading_days": 0, "success": 0, "gaps": 0, "values": []})
        months[y + "-" + m]["success"] += 1
        months[y + "-" + m]["values"].append(r["value"])
    for g in result["gaps"]:
        y, m = g["date"][:4], g["date"][4:6]
        months.setdefault(y + "-" + m, {"trading_days": 0, "success": 0, "gaps": 0, "values": []})
        months[y + "-" + m]["gaps"] += 1
    out = []
    for k in sorted(months):
        mm = months[k]
        vals = mm["values"]
        summary = {
            "month": k,
            "trading_days": mm["trading_days"],
            "success": mm["success"],
            "gaps": mm["gaps"],
            "max_lianban_hist": dict(Counter(int(v) for v in vals).most_common()),
        }
        if vals:
            sv = sorted(vals)
            summary["min_max"] = sv[0]
            summary["p50_max"] = sv[len(sv) // 2]
            summary["p90_max"] = sv[int(len(sv) * 0.9)]
            summary["max_max"] = sv[-1]
        out.append(summary)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="连板历史回补(dry-run 对账 / 写库)")
    ap.add_argument("--start", default="20210901", help="回补起点(YYYYMMDD,默认 20210901)")
    ap.add_argument("--end", default=None, help="回补终点(YYYYMMDD,默认昨天最近交易日)")
    ap.add_argument("--db", default=None, help="sqlite 库路径(默认 app.db 默认 sentiment.db)")
    ap.add_argument("--dry-run", action="store_true", default=False,
                    help="显式声明 dry-run(默认即 dry-run;与 --write 互斥)")
    ap.add_argument("--write", action="store_true", help="真写库(需用户单独授权)")
    ap.add_argument("--with-st", action="store_true",
                    help="含 ST 全量 max(仅作对账对照,验证排除开关)")
    ap.add_argument("--out", default=None, help="对账结果写 JSON 到该路径")
    args = ap.parse_args(argv)

    if not args.start.isdigit() or len(args.start) != 8:
        print("--start 需为 YYYYMMDD", file=sys.stderr)
        return 2
    dry_run = not args.write
    if args.dry_run and args.write:
        print("--dry-run 与 --write 互斥(默认 dry-run,--write 为真写库)", file=sys.stderr)
        return 2

    start = args.start
    end = _last_trading_day_before(args.end)
    if args.end is not None:
        if not args.end.isdigit() or len(args.end) != 8:
            print("--end 需为 YYYYMMDD", file=sys.stderr)
            return 2
        end = args.end

    result = backfill_lianban(start, end, db=args.db, dry_run=dry_run,
                              with_st=args.with_st, verbose=True)

    # ── 汇总打印 ──
    print(f"\n===== 回补汇总 [{start}~{end}] {'dry-run' if dry_run else '写库'} "
          f"{'含ST对照' if args.with_st else '排除ST'} =====")
    print(f"交易日 {result['total_trading_days']} | 成功 {result['success_days']} | "
          f"gap {result['gap_days']}")
    if result["overlap_total"]:
        print(f"重叠段对账:共 {result['overlap_total']} 天,一致 {result['overlap_same']} 天,"
              f"一致率 {result['overlap_rate']:.2%}")
        if result["mismatch_days"]:
            print("ALL 不等日:")
            for mm in result["mismatch_days"]:
                ex = mm["existing"]
                fa = f"{mm['fapi']:g}" if mm["fapi"] is not None else "None"
                print(f"  {mm['date']}: 现库={ex:g} vs FAPI={fa}")
    else:
        print("重叠段:无(区间内现库无 a_width_max_lianban 值)")
    print(f"增量段: {len(result['increment_dates'])} 天")
    if result["gaps"]:
        print(f"gap 清单({len(result['gaps'])} 天):")
        for g in result["gaps"]:
            print(f"  {g['date']}: {g['reason']}")
    if dry_run:
        print(f"\n[dry-run] 未写任何行到库{' (--db ' + str(args.db) + ')' if args.db else ''}")

    if args.out:
        payload = dict(result)
        payload["monthly"] = _fmt_month_summary(result)
        # 内部字段不落盘;保留计算出的 (date,value) 全量供 a_sentiment 模拟注入
        payload["computed"] = [{"date": r["date"], "value": r["value"]} for r in result["_rows"]]
        payload.pop("_all_dates", None)
        payload.pop("_rows", None)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        print(f"对账明细已写 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
