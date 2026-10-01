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

写库保护(只补缺口,2026-09-30 用户拍板)
========================================
默认 --fill-gaps-only(只补缺口):目标库该日已有非空 a_width_max_lianban 值
→ 跳过不写(不管该行 source 是什么),一根汗毛不动;只补缺值日期。
--overwrite 可覆盖已有非 manual 值(不推荐,需另行拍板)。两模式下
source='manual' 均受保护(ON CONFLICT ... WHERE source != 'manual',与
app/collector/width_history.py upsert_width 同款),手动补录永不被覆盖。
日志分列打印:计划写入 / 因已有值跳过 / 因 manual 跳过 / gap,不许静默跳过。

CLI
====
python -m app.backfill_lianban --dry-run --start 20210901 --end 20260611   # 只补缺口 dry-run
python -m app.backfill_lianban --dry-run --start 20210901 --db /tmp/x.db --out /tmp/x.json
# 真写生产主库(需用户单独授权 + P2-7 二次确认;dry-run 正常路径 rc=0,
# 有 gap/失败时 rc=1 供自动化感知):
python -m app.backfill_lianban --start 20210901 --write --confirm-prod
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
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

# 云上生产主库路径(与 docs/ops/lianban-prod-write-checklist.md 钉死的执行目标一致)。
# 云上 app.db.DB_PATH 经 symlink 链可能解析到旧镜像目录(trade-data-signal/data),
# 与真实主库(trade-data/data)realpath 不等;为避免 P2-7 护栏漏拦,显式登记常量。
_CLOUD_PROD_DB = "/home/ubuntu/code/trade-data/data/sentiment.db"

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


def _fetch_zt_all_pages(date: str) -> tuple[object, str]:
    """取某日 FAPI 涨停池**全量**。

    ⚠️ 直接复用 fapi_fallback.fetch_zt_fallback(#140 已加固翻页,2026-09-30
    合 main):四重停止条件(按 pagination.pages 翻页 / 末页兜底 len(batch)<200
    防 pages 缺失 / MAX_PAGES=10 安全上限 / len(df) vs total 对账 TRUNCATED
    告警)——本脚本不再持有第二份翻页实现(§5.4⑦ 同构对账:复刻=第二份
    实现,静默漂移是必然)。ST 排除仍在下方 max_lianban_ex_st 做(东财可比
    口径,排除后才是 max)。

    返回 (df or None, msg)。df 含全量行;None=失败。

    空 df 语义(2026-10-02 订正,回退 d1b3e9382 的 P2-3):fetch_zt_fallback 返回
    空 df 有 3 条可达路径,且 API 层**无法区分**「该日真0 / 服务端无该日数据 /
    契约异常」:
      A. 真0:          pagination.total=0                  -> msg `empty(真0)`
      B. 契约异常:      total=700 但 item 字段缺失/改名      -> msg `TRUNCATED total=700 got=0`
      C. 契约异常:      data 有 item 但缺 pagination,total 误取 0 -> msg 误报 `empty(真0)`
    A 股交易日全市场涨停池为空现实中不存在(2015 股灾日也有涨停),FAPI 报
    total=0 更可能是服务端无该日数据。故主循环 `len(df)==0` 一律按**异常**记
    gap、不写值(保守、可重试、诚实,§5.1④;禁止猜测性写 0,详见主循环注释)。
    """
    return fetch_zt_fallback("stock_zt_pool_em", date)


def _fetch_zt_with_retry(date: str) -> tuple[object, str]:
    """取全量涨停池,失败按 fapi_daily 策略重试 RETRY 次。
    成功也要随机节流(FAPI 是外部服务,别打太猛)。
    返回 (df or None, msg)。df 为 None = 重试后仍失败。"""
    last = None
    for i in range(RETRY):
        df, msg = _fetch_zt_all_pages(date)
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


def _fmt(v) -> str:
    """宽容数值格式化:数值用 :g,非数值/空串原样字符串(防旧库脏值崩溃, P2-1)。

    真实库 daily_metric.value 是 REAL 列,但边界/脏数据可能为空串或非数值,
    `{v:g}` 会抛 ValueError 导致回补崩溃。改为可转则 :g,不可转原样 str。
    """
    if isinstance(v, bool):
        return str(v)
    try:
        return f"{v:g}"
    except (ValueError, TypeError):
        return str(v)


def _to_float(v):
    """宽容转 float;不可转(空串/非数值)返回 None(供对账比较用, P2-1)。"""
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _existing_map(conn: sqlite3.Connection, start: str, end: str) -> dict[str, tuple[float, str]]:
    """现有 a_width_max_lianban 在 [start,end] 内的 (date -> (value, source))。

    只取 value IS NOT NULL 的行(空值视为缺口,可补)。
    """
    rows = conn.execute(
        "SELECT date, value, source FROM daily_metric WHERE metric_id=? "
        "AND date BETWEEN ? AND ? ORDER BY date",
        (METRIC_ID, start, end),
    ).fetchall()
    return {r["date"]: (r["value"], r["source"]) for r in rows if r["value"] is not None}


def _source_map(conn: sqlite3.Connection, start: str, end: str) -> dict[str, str]:
    """现有 a_width_max_lianban 在 [start,end] 内的 (date -> source),**含 NULL 值行**。

    manual 保护需要覆盖 manual+NULL 缺口行(它也在库里有行、source=manual,不该被
    计划写入)——只靠 _existing_map(滤 NULL)会漏掉它,把「manual+NULL 行」误计进
    planned_write(实际被 _upsert SQL `WHERE source != 'manual'` 拦下不写,账实不符,
    P2-2)。此处独立查一次 date->source,循环内 manual 判定改按本表。
    """
    rows = conn.execute(
        "SELECT date, source FROM daily_metric WHERE metric_id=? "
        "AND date BETWEEN ? AND ? ORDER BY date",
        (METRIC_ID, start, end),
    ).fetchall()
    return {r["date"]: r["source"] for r in rows}


def backfill_lianban(start: str, end: str, *, db: str | None = None,
                     dry_run: bool = True, with_st: bool = False,
                     fill_gaps_only: bool = True, verbose: bool = True) -> dict:
    """逐交易日回补最高连板。dry_run=True 只输出对账,一行都不写库。

    fill_gaps_only=True(默认,只补缺口):目标库该日已有非空 a_width_max_lianban
    值 → 跳过不写(不管 source 是什么);只写缺值日期。=False(覆盖模式):已有
    非 manual 值会被覆盖。两模式下 source='manual' 均不覆盖(_upsert SQL 二次
    兜底)。

    返回 dict:dates(总交易日)/planned_write/gap/skipped_existing/
    skipped_manual/overlap 对账/new 增量 摘要。
    """
    from .calendar import trading_days_between

    conn = _connect(db)
    try:
        dates = trading_days_between(start, end)
        existing = _existing_map(conn, start, end)
        src_map = _source_map(conn, start, end)
        n_overlap = len(set(dates) & set(existing))
        if verbose:
            print(f"回补连板 {start}~{end}:交易日 {len(dates)},现有非空值 {len(existing)} 天"
                  f"(重叠 {n_overlap} 天),模式={'只补缺口' if fill_gaps_only else '覆盖非manual'}"
                  f",含ST={'是' if with_st else '否'}", flush=True)

        rows: list[dict] = []   # 计划写入的行(缺口 + overwrite 下的已有非manual)
        computed_all: list[dict] = []  # 所有成功计算的行(date/value/池信息),供 a_sentiment 注入
        gaps: list[dict] = []   # gap 清单
        planned_write = 0      # 计划写入天数
        skipped_existing = 0   # 因已有值跳过(非manual,fill_gaps_only 下)
        skipped_manual = 0     # 因 manual 保护跳过(任何模式)
        for d in dates:
            df, msg = _fetch_zt_with_retry(d)
            if df is None:
                gaps.append({"date": d, "reason": msg})
                continue
            if len(df) == 0:
                # 空 df 处理(2026-10-02 回退 d1b3e9382 的 P2-3 语义改动):记 gap、
                # 不写值(禁止猜测性写 0)。依据:空 df 在 fetch_zt_fallback 层有
                # 3 条可达路径,API 层无法区分「该日真0 / 服务端无该日数据 / 契约异常」:
                #   A. 真0:      pagination.total=0 -> msg empty(真0)
                #   B. 契约异常: total=700 但 item 字段缺失/改名
                #                -> msg TRUNCATED total=700 got=0(写 0 静默丢 700 行)
                #   C. 契约异常: data 有 item 但缺 pagination,total 误取 0
                #                -> msg 误报 empty(真0)(写 0 静默丢全部)
                # A 股交易日全市场涨停池为空现实中不存在(2015 股灾日也有涨停),
                # FAPI 报 total=0 更可能是服务端无该日数据。写 0 是猜、记 gap 是
                # 诚实:gap 可重试、可人工核、不污染下游;且填 0 后 fill-gaps-only
                # 永久跳过不再重试,下游 a_sentiment 永远缺/错 lianban 分项。
                # gap 的 reason 已带 msg 原文,人工可分辨 empty(真0) vs TRUNCATED。
                gaps.append({"date": d, "reason": f"FAPI 涨停池空(真0/无数据/契约异常无法区分,3条路径见backfill_lianban主循环注释): {msg}"})
                continue
            value, st_cnt, total = max_lianban_ex_st(df, with_st=with_st)
            if value is None:
                gaps.append({"date": d,
                             "reason": f"全部被排除ST(排除{st_cnt}/{total}行,含ST时无连板可取值)"})
                continue
            computed_all.append({"date": d, "value": value})

            # ── 写/跳过判定 ──
            # manual 判定按 _source_map(含 NULL 值行):manual+NULL 缺口行也是 manual
            # 行,不该计划写入(P2-2)——否则计进 planned_write 却被 _upsert SQL 拦下,
            # 账实不符。只在「非 manual」时才看已有值。
            if src_map.get(d) == 'manual':
                # manual 保护:任何模式都不覆写(不调 _upsert)
                skipped_manual += 1
                if verbose:
                    old = existing.get(d)   # 可能 None(manual+NULL 缺口行)
                    old_s = f"现库={_fmt(old[0])}(source=manual,不覆盖)" if old is not None else "现库=NULL(manual,不覆盖)"
                    print(f"  manual跳过 {d}: {old_s} 新值={_fmt(value)}", flush=True)
                continue
            old = existing.get(d)          # None=缺口;否则 (value, source)
            if old is not None and fill_gaps_only:
                # 只补缺口:已有非空值(非manual)→ 跳过
                skipped_existing += 1
                if verbose:
                    print(f"  已有值跳过 {d}: 现库={_fmt(old[0])}(source={old[1]}) 新值={_fmt(value)}",
                          flush=True)
                continue
            # 缺口 / 覆盖模式下的已有非manual → 计划写入
            rows.append({"date": d, "value": value, "source": SOURCE,
                         "st_excluded": st_cnt, "pool_rows": total})
            planned_write += 1
            tag = ("覆盖-写" if old is not None else "增量-计划写入")
            if verbose:
                print(f"  {tag} {d}: value={_fmt(value)} 池={total} 排除ST={st_cnt}"
                      + (f" 现库={_fmt(old[0])}(source={old[1]})→覆盖" if old is not None else ""),
                      flush=True)
            if not dry_run:
                _upsert(conn, d, value, only_if_null=fill_gaps_only)

        if not dry_run:
            conn.commit()

        # ── 对账(仅对「计划写入」的重叠日判定;被跳过的重叠日不列入 mismatch) ──
        overlap_dates = sorted(set(dates) & set(existing))
        written_overlap = [d for d in overlap_dates if any(r["date"] == d for r in rows)]
        skipped_overlap = sorted(set(overlap_dates) - set(written_overlap))
        mismatch = []
        same = 0
        for d in written_overlap:
            new_v = next(r["value"] for r in rows if r["date"] == d)
            o = existing[d]
            # 宽容比较:任一侧非数值(空串/脏值)视为不等而非崩溃(P2-1)
            a, b = _to_float(new_v), _to_float(o[0])
            if a is not None and b is not None and abs(a - b) < 1e-9:
                same += 1
            else:
                mismatch.append({"date": d, "existing": o[0], "fapi": new_v})
        overlap_rate = same / len(written_overlap) if written_overlap else None

        new_dates = sorted(r["date"] for r in rows if r["date"] not in existing)
        return {
            "start": start, "end": end, "with_st": with_st,
            "fill_gaps_only": fill_gaps_only,
            "total_trading_days": len(dates),
            "planned_write": planned_write,
            "skipped_existing": skipped_existing,
            "skipped_manual": skipped_manual,
            "success_days": len(rows), "gap_days": len(gaps),
            "overlap_total": len(overlap_dates),
            "overlap_written": len(written_overlap),
            "overlap_skipped": skipped_overlap,
            "overlap_same": same,
            "overlap_rate": overlap_rate, "mismatch_days": mismatch,
            "increment_dates": new_dates,
            "gaps": gaps,
            "_all_dates": dates, "_rows": rows, "_computed": computed_all,
        }
    finally:
        conn.close()


def _upsert(conn: sqlite3.Connection, date: str, value: float,
            only_if_null: bool = False) -> None:
    """写库 ON CONFLICT ... WHERE source != 'manual'(防覆盖手动补录,width_history 同款)。

    only_if_null=True 时冲突更新额外要求现库 value IS NULL ——「只补缺口」竞态
    加固:防「读快照后、首个 INSERT 前」给缺口日写入的值被本行覆盖(生产
    23:00+ 无写入者,风险低,但用户要一根汗毛不动,加固一行更稳)。
    """
    when = "WHERE daily_metric.source != 'manual'"
    if only_if_null:
        when += " AND daily_metric.value IS NULL"
    conn.execute(
        "INSERT INTO daily_metric (date, metric_id, value, source, updated_at) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT(date, metric_id) DO UPDATE SET "
        "value=excluded.value, source=excluded.source, updated_at=excluded.updated_at "
        + when,
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
    ap.add_argument("--fill-gaps-only", action="store_true", default=False,
                    help="只补缺口:已有非空值跳过(默认行为;与 --overwrite 互斥)")
    ap.add_argument("--overwrite", action="store_true", default=False,
                    help="覆盖已有非 manual 值(需另拍板;manual 值仍受保护)")
    ap.add_argument("--with-st", action="store_true",
                    help="含 ST 全量 max(仅作对账对照,验证排除开关)")
    ap.add_argument("--out", default=None, help="对账结果写 JSON 到该路径")
    ap.add_argument("--confirm-prod", action="store_true",
                    help="二次确认写生产主库(--db 指向生产路径或未指定 --db 时,与 --write 连用必需)")
    args = ap.parse_args(argv)

    if not args.start.isdigit() or len(args.start) != 8:
        print("--start 需为 YYYYMMDD", file=sys.stderr)
        return 2
    dry_run = not args.write
    if args.dry_run and args.write:
        print("--dry-run 与 --write 互斥(默认 dry-run,--write 为真写库)", file=sys.stderr)
        return 2

    fill_gaps_only = not args.overwrite
    if args.fill_gaps_only and args.overwrite:
        print("--fill-gaps-only 与 --overwrite 互斥(默认只补缺口,--overwrite 为覆盖已有非manual值)",
              file=sys.stderr)
        return 2

    # P2-7 生产护栏:--write 且目标解析为生产主库(未指定 --db=默认生产库 / 显式指向
    # app.db.DB_PATH)→ 必须显式二次确认(--confirm-prod 或环境变量 LIANBAN_CONFIRM_PROD=1)。
    # 防留档复用者凭文档纪律误写生产;dry-run 不拦。
    if args.write and _target_is_prod(args.db):
        if not (args.confirm_prod or os.environ.get("LIANBAN_CONFIRM_PROD") == "1"):
            print("--write 目标为生产主库路径(未指定 --db 即默认 app.db 生产库)。"
                  "真写需显式二次确认:加 --confirm-prod 或环境变量 LIANBAN_CONFIRM_PROD=1。"
                  "建议先 dry-run 对账 + 按 docs/ops/lianban-prod-write-checklist.md 备份。",
                  file=sys.stderr)
            return 3

    start = args.start
    end = _last_trading_day_before(args.end)
    if args.end is not None:
        if not args.end.isdigit() or len(args.end) != 8:
            print("--end 需为 YYYYMMDD", file=sys.stderr)
            return 2
        end = args.end

    result = backfill_lianban(start, end, db=args.db, dry_run=dry_run,
                              with_st=args.with_st, fill_gaps_only=fill_gaps_only,
                              verbose=True)

    # ── 汇总打印 ──
    print(f"\n===== 回补汇总 [{start}~{end}] {'dry-run' if dry_run else '写库'} "
          f"{'含ST对照' if args.with_st else '排除ST'} "
          f"{'只补缺口' if fill_gaps_only else '覆盖非manual'} =====")
    print(f"交易日 {result['total_trading_days']} | gap {result['gap_days']}")
    print(f"计划写入 {result['planned_write']} 天 | 因已有值跳过 {result['skipped_existing']} 天 | "
          f"因 manual 跳过 {result['skipped_manual']} 天")
    if result["overlap_total"]:
        if result["overlap_written"]:
            print(f"重叠段对账:重叠 {result['overlap_total']} 天,计划写入 {result['overlap_written']} 天,"
                  f"一致 {result['overlap_same']} 天,一致率 {result['overlap_rate']:.2%}")
        else:
            print(f"重叠段:共 {result['overlap_total']} 天,全部跳过未写(只补缺口/manual保护),不产生覆盖")
        if result["overlap_skipped"]:
            print(f"跳过未写重叠日 {len(result['overlap_skipped'])} 天: "
                  + ", ".join(result["overlap_skipped"]))
        if result["mismatch_days"]:
            print("计划写入重叠日中 ALL 不等日(FAPI vs 现库):")
            for mm in result["mismatch_days"]:
                ex = _fmt(mm["existing"])
                fa = _fmt(mm["fapi"])
                print(f"  {mm['date']}: 现库={ex} vs FAPI={fa}")
    else:
        print("重叠段:无(区间内现库无 a_width_max_lianban 值)")
    print(f"增量段(缺口): {len(result['increment_dates'])} 天")
    if result["gaps"]:
        print(f"gap 清单({len(result['gaps'])} 天):")
        for g in result["gaps"]:
            print(f"  {g['date']}: {g['reason']}")
    if dry_run:
        print(f"\n[dry-run] 未写任何行到库{' (--db ' + str(args.db) + ')' if args.db else ''}")

    if args.out:
        payload = dict(result)
        payload["monthly"] = _fmt_month_summary(result)
        # 内部字段不落盘;computed=全量计算出的 (date,value)(含重叠段,供 a_sentiment 注入)
        payload["computed"] = [{"date": r["date"], "value": r["value"]} for r in result["_computed"]]
        payload.pop("_all_dates", None)
        payload.pop("_rows", None)
        payload.pop("_computed", None)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        print(f"对账明细已写 {args.out}")

    # P2-4 静默退出:有 gap/失败时非零退出,供自动化挂链感知(#132 同族弱形态)。
    # dry-run 正常路径(gap=0)仍 rc=0,不破坏现有手动用法;有 gap 即 rc=1。
    if result["gap_days"]:
        print(f"\n⚠️ 存在 {result['gap_days']} 天 gap/失败(详见上方 gap 清单),exit=1",
              file=sys.stderr)
        return 1
    return 0


def _target_is_prod(db: str | None) -> bool:
    """目标库是否生产主库路径。

    生产主库 = app.db.DB_PATH(未指定 --db 时 _connect 默认连它)。判定:
    - db 为 None → 默认走 app.db 生产主库 → True
    - db 显式 → resolve 后与 app.db.DB_PATH resolve 相等 → True(本机/开发库)
    - db 显式 → resolve 后与云上生产主库常量相等 → True(云上执行 checklist 显式
      --db 主库路径;app.db.DB_PATH 在云上经 symlink 可能解析到旧镜像目录,故
      realpath 与主库不等,须显式登记云上主库路径)
    其余(沙箱/副本/临时库)→ False。
    """
    if db is None:
        return True
    try:
        from .db import DB_PATH
        import os
        rp = os.path.realpath(db)
        return (rp == os.path.realpath(str(DB_PATH))
                or rp == os.path.realpath(_CLOUD_PROD_DB))
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(main())
