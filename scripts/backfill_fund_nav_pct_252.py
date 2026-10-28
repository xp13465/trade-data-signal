#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#252 回填 `fund_daily_nav` 的 `nav_change_pct` / `prev_unit_nav`（2026-10-28）。

背景（根因报告 `/tmp/navnull-rootcause-report.md`）
  · 采集器「当日未发布 → 回退写前一交易日」路径按设计不写 prev/pct，源端当日没给
    「日增长率」时也直接落 NULL，且**没有**「用库内更早一条 unit_nav 派生 pct」的兜底
    ⇒ 2026-10 攒下 `nav_change_pct IS NULL` 49,295 行（10-16 单日 24,103 行，prev 整日全空）。
  · 代码侧根治已落 `app/collector/fund_pct.py`（单一实现）+ 采集器接入；本脚本只补历史数据，
    **计算一律调用同一实现**（`calc_pct` / `prev_nav_from_db`），脚本内不复制第二份公式。

范围判据（写死，见 `iter_plan()`）
  · 候选：`nav_change_pct IS NULL AND unit_nav IS NOT NULL`，且同 `fund_code` 存在**更早的
    非空 `unit_nav`**（= 能派生）；派生基准 `prev` 优先取本行 `prev_unit_nav`（同源更可信），
    本行为空才取库内更早的最近一条；
  · 补 `prev_unit_nav`：**仅当该行 pct 也在本次一起补时**才补（本脚本候选集天然满足：所有候选
    都是「pct 要补」的行），避免只补一半造成 pct/prev 口径不一致；
  · **不碰**：`unit_nav IS NULL`（1,942 只 QDII/FOF/定开当月不发布，不可派生）、
    真首条（库里无更早非空 unit，30 行）、`nav_change_pct` 已非空的行（绝不覆盖）。

安全（§25 删除/覆盖前必备份）
  · **默认 dry-run**：只统计 + 抽样打印，连接以 `mode=ro` + `PRAGMA query_only=1` 打开，
    物理上写不了库；`--report PATH` 落全量计划明细(jsonl)。
  · `--apply` 必须显式传。**执行前置**：①先备份整库（`bash scripts/backup_db.sh` 或
    `cp public_fund.db /path/backup_$(date +%Y%m%d_%H%M%S).db` 并校验可打开）；
    ②`UPDATE ... WHERE nav_change_pct IS NULL` 双保险 + 写后按 rowcount 逐批核对；
    ③分批提交（每批 ≤5,000 行），可中断可续跑（只补 NULL ⇒ 天然幂等）。
  · apply 时逐行把 `(date, fund_code, old_pct, old_prev, new_pct, new_prev)` 写
    `/tmp/backfill_fund_nav_pct_<ts>.jsonl`（边写边 flush）；回滚用
    `--rollback <jsonl>`：**只还原当前值仍等于我们写入值的行**，被别人改过的跳过并报告。

口径提示（诚实标注）：派生 pct 是**原始比值口径**（单位净值 ÷ 前一日单位净值，再减一，按百分数存）；
源端「日增长率」在分红日是调整口径（分红额并入涨幅），故分红日可能与源值有微差 ——
与 #251 脚本同一既有结论。

用法
    python3 scripts/backfill_fund_nav_pct_252.py                       # dry-run 全历史
    python3 scripts/backfill_fund_nav_pct_252.py --from 20261001 --to 20261031 --report /tmp/plan.jsonl
    python3 scripts/backfill_fund_nav_pct_252.py --apply               # 真正写库（先备份！）
    python3 scripts/backfill_fund_nav_pct_252.py --rollback /tmp/backfill_fund_nav_pct_<ts>.jsonl
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

try:  # 仓库内正常路径
    from app.collector.fund_pct import calc_pct, prev_nav_from_db  # noqa: E402
except ImportError:  # 云上 dry-run 的临时目录（同一文件复制，内容一致，非第二份实现）
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from fund_pct import calc_pct, prev_nav_from_db  # noqa: E402

_DEFAULT_DB = Path(os.environ.get("REPO", str(_ROOT))) / "data" / "public_fund.db"
_MAX_BATCH = 5000
_SAMPLE_N = 20


# ── 连接 ────────────────────────────────────────────────────────────────────────

def _open_ro(db: Path) -> sqlite3.Connection:
    """只读连接：URI mode=ro + query_only，dry-run 物理上无法写库。"""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=1")
    return conn


def _open_rw(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn


# ── 计划（dry-run 与 apply 共用同一份判据，禁止两套逻辑）────────────────────────

def iter_plan(conn, date_from: str, date_to: str):
    """逐行产出计划项 + 计数（生成器：apply 据此分批，内存不涨）。

    yield ("row", {...}) / 末尾 yield ("stats", {...})
    """
    stats = {"pct_null": 0, "unit_null": 0, "unit_ok": 0,
             "underivable": 0, "plan": 0, "fill_prev": 0, "prev_present": 0,
             "base_zero": 0}
    stats["pct_null"] = conn.execute(
        "SELECT COUNT(*) FROM fund_daily_nav "
        "WHERE date>=? AND date<=? AND nav_change_pct IS NULL", (date_from, date_to)
    ).fetchone()[0]
    stats["unit_null"] = conn.execute(
        "SELECT COUNT(*) FROM fund_daily_nav "
        "WHERE date>=? AND date<=? AND nav_change_pct IS NULL AND unit_nav IS NULL",
        (date_from, date_to)).fetchone()[0]
    cur = conn.execute(
        "SELECT date, fund_code, unit_nav, prev_unit_nav FROM fund_daily_nav "
        "WHERE date>=? AND date<=? AND nav_change_pct IS NULL AND unit_nav IS NOT NULL "
        "ORDER BY fund_code, date", (date_from, date_to))
    for r in cur:
        stats["unit_ok"] += 1
        base_db = prev_nav_from_db(conn, r["fund_code"], r["date"])  # 同时充当「可派生」判据
        if base_db is None:  # 真首条 / 无更早非空 unit ⇒ 不可派生，跳过（不编数）
            stats["underivable"] += 1
            continue
        old_prev = r["prev_unit_nav"]
        base = old_prev if old_prev is not None else base_db
        if float(base) == 0:  # prev=0 不可算（源侧坏值），不派生也不改
            stats["base_zero"] += 1
            continue
        new_pct = calc_pct(r["unit_nav"], base)
        if new_pct is None:  # 理论上 base 非 None/0 时不会发生，防御
            stats["underivable"] += 1
            continue
        fill_prev = old_prev is None
        stats["plan"] += 1
        if fill_prev:
            stats["fill_prev"] += 1
        else:
            stats["prev_present"] += 1
        yield ("row", {
            "date": r["date"], "fund_code": r["fund_code"],
            "unit_nav": r["unit_nav"], "old_prev": old_prev,
            "new_prev": base, "new_pct": new_pct, "fill_prev": fill_prev,
        })
    yield ("stats", stats)


def _fmt(v, nd=6):
    return "NULL" if v is None else f"{v:.{nd}f}"


# ── 写库 ────────────────────────────────────────────────────────────────────────

def _apply_batch(conn, batch, log_fh):
    """一个事务写一批；逐行断言 rowcount==1（写后核对），失败整批回滚。"""
    applied = 0
    conn.execute("BEGIN")
    try:
        for it in batch:
            if it["fill_prev"]:
                cur = conn.execute(
                    "UPDATE fund_daily_nav SET nav_change_pct=?, prev_unit_nav=? "
                    "WHERE date=? AND fund_code=? AND nav_change_pct IS NULL",
                    (it["new_pct"], it["new_prev"], it["date"], it["fund_code"]))
            else:  # prev 原本就有，只补 pct（绝不改 prev）
                cur = conn.execute(
                    "UPDATE fund_daily_nav SET nav_change_pct=? "
                    "WHERE date=? AND fund_code=? AND nav_change_pct IS NULL",
                    (it["new_pct"], it["date"], it["fund_code"]))
            if cur.rowcount != 1:
                raise RuntimeError(
                    f"更新行数={cur.rowcount}(期望 1): {it['fund_code']} {it['date']}"
                    "（可能已被别的路径改掉，本批回滚）")
            applied += 1
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    for it in batch:  # 回滚清单：先落盘再算数，任何时刻中断都留得下可还原记录
        log_fh.write(json.dumps({
            "date": it["date"], "fund_code": it["fund_code"],
            "old_pct": None, "old_prev": it["old_prev"],
            "new_pct": it["new_pct"], "new_prev": it["new_prev"],
        }, ensure_ascii=False) + "\n")
    log_fh.flush()
    return applied


def do_apply(db: Path, date_from: str, date_to: str, batch_size: int,
             log_path: Path | None = None) -> int:
    if log_path is None:
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = Path(f"/tmp/backfill_fund_nav_pct_{stamp}.jsonl")
    conn = _open_rw(db)
    total = 0
    try:
        with log_path.open("w", encoding="utf-8") as log_fh:
            batch: list[dict] = []
            stats = {}
            for kind, payload in iter_plan(conn, date_from, date_to):
                if kind == "stats":
                    stats = payload
                    break
                batch.append(payload)
                if len(batch) >= batch_size:
                    total += _apply_batch(conn, batch, log_fh)
                    print(f"[apply] 已写 {total} 行 ...", flush=True)
                    batch = []
            if batch:
                total += _apply_batch(conn, batch, log_fh)
        print(f"[apply] 完成：写入 {total} 行（计划 {stats.get('plan')}）")
        print(f"[回滚] 清单 -> {log_path}"
              f"（回滚命令：python3 {__file__} --rollback {log_path}）")
        # 写后自检：同一判据重跑，计划项应为 0（幂等 + 无漏写）
        conn2 = _open_ro(db)
        try:
            left = {"plan": None}
            for kind, payload in iter_plan(conn2, date_from, date_to):
                if kind == "stats":
                    left = payload
                    break
            ok = (left["plan"] == 0 and total == stats.get("plan"))
            print(f"[自检] 重跑候选可补 {left['plan']} 行（期望 0）、本轮写入 {total}"
                  f" / 计划 {stats.get('plan')} -> {'PASS' if ok else 'FAIL'}")
            return 0 if ok else 3
        finally:
            conn2.close()
    finally:
        conn.close()


def do_rollback(db: Path, log_path: Path, batch_size: int) -> int:
    conn = _open_rw(db)
    restored = skipped = 0
    try:
        pending: list[dict] = []
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            pending.append(json.loads(line))
            if len(pending) >= batch_size:
                r, s = _rollback_batch(conn, pending, log_path)
                restored += r
                skipped += s
                pending = []
        if pending:
            r, s = _rollback_batch(conn, pending, log_path)
            restored += r
            skipped += s
        print(f"[rollback] 还原 {restored} 行；跳过 {skipped} 行（当前值已被别人改过/行缺失，未触碰）")
        return 0 if skipped == 0 else 4
    finally:
        conn.close()


def _rollback_batch(conn, batch, log_path):
    restored = skipped = 0
    conn.execute("BEGIN")
    try:
        for it in batch:
            cur = conn.execute(
                "UPDATE fund_daily_nav SET nav_change_pct=?, prev_unit_nav=? "
                "WHERE date=? AND fund_code=? AND nav_change_pct IS ? AND prev_unit_nav IS ?",
                (it["old_pct"], it["old_prev"], it["date"], it["fund_code"],
                 it["new_pct"], it["new_prev"]))
            if cur.rowcount == 1:
                restored += 1
            else:
                skipped += 1
                print(f"[rollback][skip] {it['fund_code']} {it['date']}: "
                      f"当前值 != 我们写入的 (pct={it['new_pct']}, prev={it['new_prev']})",
                      flush=True)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return restored, skipped


# ── main ───────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="回填 fund_daily_nav 的 nav_change_pct/prev_unit_nav（默认 dry-run；--apply 才写库）",
        epilog="执行 --apply 前必须先备份整库，见文件头部「安全」段。")
    ap.add_argument("--db", default=str(_DEFAULT_DB), help=f"库路径（默认 {_DEFAULT_DB}）")
    ap.add_argument("--from", dest="date_from", default="00000000", help="起始日期 YYYYMMDD（含）")
    ap.add_argument("--to", dest="date_to", default="99999999", help="结束日期 YYYYMMDD（含）")
    ap.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run，零写入）")
    ap.add_argument("--rollback", default=None, metavar="JSONL", help="按回滚清单精确还原")
    ap.add_argument("--report", default=None, metavar="PATH", help="把全量计划明细写 jsonl（dry-run 用）")
    ap.add_argument("--batch-size", type=int, default=_MAX_BATCH, help=f"每批提交行数（≤{_MAX_BATCH}）")
    args = ap.parse_args(argv)

    db = Path(args.db)
    if not db.exists():
        print(f"[FAIL] 库不存在: {db}")
        return 2
    batch_size = max(1, min(args.batch_size, _MAX_BATCH))

    if args.rollback:
        return do_rollback(db, Path(args.rollback), batch_size)

    if args.apply:
        return do_apply(db, args.date_from, args.date_to, batch_size)

    # ── dry-run：只读连接，物理零写入 ──
    conn = _open_ro(db)
    try:
        plan_fh = open(args.report, "w", encoding="utf-8") if args.report else None
        stats, sample = {}, []
        t0 = dt.datetime.now()
        try:
            for kind, payload in iter_plan(conn, args.date_from, args.date_to):
                if kind == "stats":
                    stats = payload
                    break
                if plan_fh:
                    plan_fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
                if len(sample) < _SAMPLE_N:
                    sample.append(payload)
        finally:
            if plan_fh:
                plan_fh.close()
        elapsed = (dt.datetime.now() - t0).total_seconds()
        print(f"[范围] {args.date_from}..{args.date_to}  库={db}")
        print(f"[当月空值] nav_change_pct IS NULL: {stats['pct_null']} 行")
        print(f"  ├ unit_nav 也空（不可派生，跳过）: {stats['unit_null']} 行")
        print(f"  ├ unit 有值但库内无更早非空 unit（真首条，跳过）: {stats['underivable']} 行")
        print(f"  ├ prev=0 不可算（跳过）: {stats['base_zero']} 行")
        print(f"  └ 本次将补 pct: {stats['plan']} 行"
              f"（其中一并补 prev: {stats['fill_prev']} 行 / 原本已有 prev 只补 pct: {stats['prev_present']} 行）")
        print(f"[预期] 回填后该范围 nav_change_pct IS NULL ≈ "
              f"{stats['pct_null'] - stats['plan']} 行")
        print(f"[抽样] {len(sample)} 行（date / fund_code / unit / 原 prev / 派生 prev / 派生 pct）:")
        for it in sample:
            print(f"  · {it['date']} {it['fund_code']} unit={_fmt(it['unit_nav'])} "
                  f"prev={_fmt(it['old_prev'])} -> {_fmt(it['new_prev'])} "
                  f"pct={_fmt(it['new_pct'], 4)}")
        print(f"[耗时] {elapsed:.1f}s")
        if args.report:
            print(f"[明细] 全量计划已写 {args.report}")
        print("[dry-run] 未写库（connection=mode=ro + query_only）。确认无误并先备份后，加 --apply 执行。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())