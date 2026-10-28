#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#252 回填 `fund_daily_nav` 的 `nav_change_pct` / `prev_unit_nav`（2026-10-28）。

背景（根因报告 `docs/ops/fund-nav-pct-rootfix-20261028.md`）
  · 采集器「当日未发布 → 回退写前一交易日」路径按设计不写 prev/pct，源端当日没给
    「日增长率」时也直接落 NULL，且**没有**「用库内前一交易日那条 unit_nav 派生 pct」的兜底
    ⇒ 2026-10 攒下 `nav_change_pct IS NULL` 49,295 行（10-16 单日 24,103 行，prev 整日全空）。
  · 代码侧根治已落 `app/collector/fund_pct.py`（单一实现）+ 采集器接入；本脚本只补历史数据，
    **计算一律调用同一实现**（`PrevNavCache` / `calc_pct`），脚本内不复制第二份公式。

范围判据（写死，见 `iter_plan()`）
  · 候选：`nav_change_pct IS NULL AND unit_nav IS NOT NULL`；
  · **基准 = 目标日的前一交易日那一行**（交易日历 `app/calendar.py` 判，禁用自然日差 1）：
    该基金在基准日没有行 / `unit_nav` 为空 ⇒ **不可派生，保持 NULL**（含跨多日 gap≥2、
    周更基金、真首条 —— 这是**正确行为**，不是漏补）；
  · 本行已有 `prev_unit_nav` 且与基准日净值**不一致** ⇒ 该 prev 不是前一交易日的值
    （历史 gap≥2 列值 / 源端事后修正）⇒ 不派生、不改 prev，计入 `prev_mismatch`；
  · `prev_unit_nav` 为空 ⇒ 一并补成基准日净值（只有 pct 一起补的行才补 prev，避免半补）；
  · **不碰**：`unit_nav IS NULL`（1,942 只 QDII/FOF/定开当月不发布，不可派生）、
    `nav_change_pct` 已非空的行（绝不覆盖）。

安全（§25 删除/覆盖前必备份）
  · **默认 dry-run**：只统计 + 抽样打印，连接以 `mode=ro` + `PRAGMA query_only=1` 打开，
    物理上写不了库；`--report PATH` 落全量计划明细(jsonl)。
  · `--apply` 必须显式传 **且必须带 `--backup-confirm <备份文件>`**（硬门，代码强制）：
    不提供 / 路径不存在 / 就是当前库本身 / 不是 SQLite 库 / `fund_daily_nav` 行数与当前库
    不等 ⇒ **拒绝执行并说明**。备份命令（别用 `cp`，WAL 模式下 `cp` 可能丢最新提交）：
        sqlite3 data/public_fund.db ".backup /path/public_fund_backup_$(date +%Y%m%d_%H%M%S).db"
  · 写库：`UPDATE ... WHERE nav_change_pct IS NULL` 双保险 + 写后按 rowcount 逐批核对；
    分批提交（每批 ≤5,000 行），可中断可续跑（只补 NULL ⇒ 天然幂等）。
  · apply 时逐行把 `(date, fund_code, old_pct, old_prev, new_pct, new_prev)` 写
    `/tmp/backfill_fund_nav_pct_<ts>.jsonl`：**先写盘 + flush + fsync 成功后才 commit**；
    commit 失败则 rollback 并把该批日志回退到本批起点（该批标记未生效）。
    回滚用 `--rollback <jsonl>`：**只还原当前值仍等于我们写入值的行**，被别人改过的跳过并报告。
  · 回填窗口：16:20 公募日更槽（`trade-public-fund-daily.timer`）跑完并确认无并发写库任务后再跑；
    `--apply` 会先回显实际范围与预计行数，便于当班核对。

口径提示（诚实标注）：派生 pct 是**原始比值口径**（单位净值 ÷ 前一交易日单位净值，再减一，按百分数存）；
源端「日增长率」在分红日是调整口径（分红额并入涨幅），故分红日可能与源值有微差 ——
与 #251 脚本同一既有结论。

用法
    python3 scripts/backfill_fund_nav_pct_252.py                       # dry-run 全历史
    python3 scripts/backfill_fund_nav_pct_252.py --from 20261001 --to 20261031 --report /tmp/plan.jsonl
    python3 scripts/backfill_fund_nav_pct_252.py --apply --backup-confirm /path/backup.db
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
    from app.collector.fund_pct import PrevNavCache, calc_pct  # noqa: E402
except ImportError:  # 云上 dry-run 的临时目录（同一文件复制，内容一致，非第二份实现）
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from fund_pct import PrevNavCache, calc_pct  # noqa: E402

_DEFAULT_DB = Path(os.environ.get("REPO", str(_ROOT))) / "data" / "public_fund.db"
_MAX_BATCH = 5000
_SAMPLE_N = 20
_SENTINEL = ("00000000", "99999999")


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

def _same_nav(a, b) -> bool:
    """两处净值是否同一值（库内 4 位小数，允许浮点噪声）。"""
    return abs(float(a) - float(b)) <= 1e-9


def iter_plan(conn, date_from: str, date_to: str, cache: PrevNavCache | None = None):
    """逐行产出计划项 + 计数（生成器：apply 据此分批，内存不涨）。

    yield ("row", {...}) / 末尾 yield ("stats", {...})
    """
    stats = {"pct_null": 0, "unit_null": 0, "unit_ok": 0,
             "underivable": 0, "prev_mismatch": 0, "base_zero": 0,
             "plan": 0, "fill_prev": 0, "prev_present": 0}
    stats["pct_null"] = conn.execute(
        "SELECT COUNT(*) FROM fund_daily_nav "
        "WHERE date>=? AND date<=? AND nav_change_pct IS NULL", (date_from, date_to)
    ).fetchone()[0]
    stats["unit_null"] = conn.execute(
        "SELECT COUNT(*) FROM fund_daily_nav "
        "WHERE date>=? AND date<=? AND nav_change_pct IS NULL AND unit_nav IS NULL",
        (date_from, date_to)).fetchone()[0]
    if cache is None:
        cache = PrevNavCache(conn)
    cur = conn.execute(
        "SELECT date, fund_code, unit_nav, prev_unit_nav FROM fund_daily_nav "
        "WHERE date>=? AND date<=? AND nav_change_pct IS NULL AND unit_nav IS NOT NULL "
        "ORDER BY fund_code, date", (date_from, date_to))
    for r in cur:
        stats["unit_ok"] += 1
        old_prev = r["prev_unit_nav"]
        # 基准 = 前一交易日那一行（交易日历口径）；缺失 ⇒ 不派生（跨多日/真首条，正确留 NULL）
        base = cache.prev_nav(r["fund_code"], r["date"])
        if base is None:
            stats["underivable"] += 1
            continue
        if old_prev is not None and not _same_nav(old_prev, base):
            # 行里 prev 不是前一交易日的值（历史 gap≥2 列值等）⇒ 不派生、不改 prev
            stats["prev_mismatch"] += 1
            continue
        if float(base) == 0:  # 基准为 0 不可算（源侧坏值），不派生也不改
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


def _plan_stats(conn, date_from: str, date_to: str) -> dict:
    """只取统计（不落明细），供 `--apply` 前回显「预计行数」。"""
    for kind, payload in iter_plan(conn, date_from, date_to):
        if kind == "stats":
            return payload
    return {}


def _fmt(v, nd=6):
    return "NULL" if v is None else f"{v:.{nd}f}"


# ── 写库 ────────────────────────────────────────────────────────────────────────

def _rewind_log(log_fh, pos: int):
    """把回滚清单回退到本批起点（该批未生效 ⇒ 不留「以为写了」的记录）。"""
    log_fh.seek(pos)
    log_fh.truncate()
    log_fh.flush()
    os.fsync(log_fh.fileno())


def _apply_batch(conn, batch, log_fh):
    """一个事务写一批；逐行断言 rowcount==1（写后核对），失败整批回滚。

    顺序 = **回滚清单先落盘（write + flush + fsync）再 commit**：进程在两者之间崩，
    库里没有这批改动、日志里多出的行回滚时会被「当前值 != 写入值」跳过，仍然安全；
    反过来（先 commit 再写日志）会出现「已写库但回滚记录丢失」——不可接受。
    commit 失败 ⇒ rollback + 该批日志回退到起点（标记未生效）。
    """
    applied = 0
    log_pos = log_fh.tell()
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
        for it in batch:  # 回滚清单：先落盘再 commit
            log_fh.write((json.dumps({
                "date": it["date"], "fund_code": it["fund_code"],
                "old_pct": None, "old_prev": it["old_prev"],
                "new_pct": it["new_pct"], "new_prev": it["new_prev"],
            }, ensure_ascii=False) + "\n").encode("utf-8"))
        log_fh.flush()
        os.fsync(log_fh.fileno())
    except Exception:
        conn.rollback()
        _rewind_log(log_fh, log_pos)
        raise
    try:
        conn.commit()
    except Exception:
        conn.rollback()
        _rewind_log(log_fh, log_pos)
        raise
    return applied


def _verify_backup(db: Path, backup_path: Path | None) -> tuple[bool, str]:
    """`--apply` 备份硬门：备份必须是**当前库的一致副本**，否则拒绝执行并说明。

    判据（比「文件大小」硬）：①提供了路径 ②存在且是普通文件 ③不是当前库本身
    ④SQLite 文件头正确 ⑤`fund_daily_nav` 行数与当前库逐位相等（WAL 模式下用 `cp`
    拷出来的库可能缺最新提交 ⇒ 行数不等 ⇒ 拒绝，提示改用 `sqlite3 .backup`）。
    """
    if backup_path is None:
        return False, ("未提供 --backup-confirm；--apply 前必须先备份整库：\n"
                       f"  sqlite3 {db} \".backup /path/public_fund_backup_$(date +%Y%m%d_%H%M%S).db\"")
    if not backup_path.exists():
        return False, f"--backup-confirm 路径不存在: {backup_path}"
    if not backup_path.is_file():
        return False, f"--backup-confirm 不是普通文件: {backup_path}"
    if backup_path.resolve() == db.resolve():
        return False, f"--backup-confirm 指向当前库本身({db})，不是备份"
    with backup_path.open("rb") as fh:
        if fh.read(16) != b"SQLite format 3\x00":
            return False, f"--backup-confirm 不是 SQLite 库文件: {backup_path}"
    try:
        bconn = _open_ro(backup_path)
        try:
            n_backup = bconn.execute("SELECT COUNT(*) FROM fund_daily_nav").fetchone()[0]
        finally:
            bconn.close()
        conn = _open_ro(db)
        try:
            n_db = conn.execute("SELECT COUNT(*) FROM fund_daily_nav").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as e:
        return False, f"--backup-confirm 打不开/不是本库结构: {backup_path}（{e}）"
    if n_backup != n_db:
        return False, (f"备份与当前库不是一致副本：备份 fund_daily_nav={n_backup} 行，"
                       f"当前库={n_db} 行。WAL 模式下 `cp` 可能丢最新提交，请用\n"
                       f"  sqlite3 {db} \".backup /path/public_fund_backup.db\"\n重新备份后再 --apply")
    size_mb = backup_path.stat().st_size / 1024 / 1024
    return True, f"备份校验 PASS: {backup_path}（{size_mb:.1f}MB，{n_backup} 行，与当前库一致）"


def do_apply(db: Path, date_from: str, date_to: str, batch_size: int,
             log_path: Path | None = None, backup_path: Path | None = None) -> int:
    ok, msg = _verify_backup(db, backup_path)
    print(f"[备份] {msg}", flush=True)
    if not ok:
        return 2
    if log_path is None:
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = Path(f"/tmp/backfill_fund_nav_pct_{stamp}.jsonl")
    # 建议 7：apply 前回显实际范围与预计行数（只读预览一遍，不写库）
    conn_ro = _open_ro(db)
    try:
        preview = _plan_stats(conn_ro, date_from, date_to)
    finally:
        conn_ro.close()
    print(f"[apply] 范围 {date_from}..{date_to}  库={db}")
    print(f"[apply] 预计写入 {preview.get('plan', 0)} 行"
          f"（其中一并补 prev {preview.get('fill_prev', 0)} 行 / 原本有 prev 只补 pct "
          f"{preview.get('prev_present', 0)} 行）；跳过：基准日缺失 "
          f"{preview.get('underivable', 0)} 行、prev 与基准日不一致 "
          f"{preview.get('prev_mismatch', 0)} 行、基准 0 {preview.get('base_zero', 0)} 行",
          flush=True)
    conn = _open_rw(db)
    total = 0
    try:
        with log_path.open("wb") as log_fh:
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

def _norm_date(value: str, name: str) -> str:
    """日期参数必须是 8 位 `YYYYMMDD`（传 `2026-10-01` 以前会静默 0 行）。"""
    s = str(value or "").strip()
    if s in _SENTINEL:
        return s
    if len(s) != 8 or not s.isdigit():
        raise ValueError(f"{name} 必须是 8 位日期 YYYYMMDD（收到 {value!r}），例：--from 20261001")
    dt.datetime.strptime(s, "%Y%m%d")  # 真实日期校验（20260231 直接报错）
    return s


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="回填 fund_daily_nav 的 nav_change_pct/prev_unit_nav（默认 dry-run；--apply 才写库）",
        epilog="执行 --apply 前必须先备份整库：sqlite3 <db> \".backup <备份路径>\"，"
               "再用 --backup-confirm <备份路径> 声明。")
    ap.add_argument("--db", default=str(_DEFAULT_DB), help=f"库路径（默认 {_DEFAULT_DB}）")
    ap.add_argument("--from", dest="date_from", default="00000000", help="起始日期 YYYYMMDD（含）")
    ap.add_argument("--to", dest="date_to", default="99999999", help="结束日期 YYYYMMDD（含）")
    ap.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run，零写入）")
    ap.add_argument("--backup-confirm", default=None, metavar="PATH",
                    help="--apply 的硬门：整库备份文件路径（必须是当前库的一致副本）")
    ap.add_argument("--rollback", default=None, metavar="JSONL", help="按回滚清单精确还原")
    ap.add_argument("--report", default=None, metavar="PATH", help="把全量计划明细写 jsonl（dry-run 用）")
    ap.add_argument("--batch-size", type=int, default=_MAX_BATCH, help=f"每批提交行数（≤{_MAX_BATCH}）")
    args = ap.parse_args(argv)

    try:
        date_from = _norm_date(args.date_from, "--from")
        date_to = _norm_date(args.date_to, "--to")
    except ValueError as e:
        print(f"[FAIL] {e}")
        return 2
    if date_from > date_to:
        print(f"[FAIL] --from({date_from}) 晚于 --to({date_to})")
        return 2

    db = Path(args.db)
    if not db.exists():
        print(f"[FAIL] 库不存在: {db}")
        return 2
    batch_size = max(1, min(args.batch_size, _MAX_BATCH))

    if args.rollback:
        return do_rollback(db, Path(args.rollback), batch_size)

    if args.apply:
        return do_apply(db, date_from, date_to, batch_size,
                        backup_path=Path(args.backup_confirm) if args.backup_confirm else None)

    # ── dry-run：只读连接，物理零写入 ──
    conn = _open_ro(db)
    try:
        plan_fh = open(args.report, "w", encoding="utf-8") if args.report else None
        stats, sample = {}, []
        t0 = dt.datetime.now()
        try:
            for kind, payload in iter_plan(conn, date_from, date_to):
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
        print(f"[范围] {date_from}..{date_to}  库={db}")
        print(f"[当月空值] nav_change_pct IS NULL: {stats['pct_null']} 行")
        print(f"  ├ unit_nav 也空（不可派生，跳过）: {stats['unit_null']} 行")
        print(f"  ├ 基准日（前一交易日）无该基金行/为空 ⇒ 正确留 NULL: {stats['underivable']} 行")
        print(f"  ├ 行内 prev 与基准日净值不一致（跨多日列值等，不派生）: {stats['prev_mismatch']} 行")
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
        print("[dry-run] 未写库（connection=mode=ro + query_only）。确认无误并先备份后，"
              "加 --apply --backup-confirm <备份文件> 执行。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())