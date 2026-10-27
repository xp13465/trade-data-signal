#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性修复 `index_daily.pct_change` 被抹成 NULL 的历史行(2026-10-29)。

背景(根因报告 /tmp/pctchange-rootcause-report.md)
  采集器自算 pct 时,df 首行没有「上一行 close」⇒ pct=None;upsert 全字段覆盖 ⇒ 把库里
  正确的好值抹成 NULL。两个源的窗口首行每天前移 ⇒ 每天抹掉一个新日期(实测量级 271 行
  「值→缺失」+ 12 行抖动回填)。**已污染的行走不了外部源**(那些日期早已跌出抓取窗口),
  但用库内自己的 close 序列回算可**逐位复现**被抹掉的原值(报告 §4.2 5/5 抽样一致)。

修法
  · 候选 = 审计表 `history_overwrite_audit` 里 index_daily 的「pct 有值→缺失」记录
    (只认这个白名单,防误伤),再核对当前库确实 `pct_change IS NULL AND close IS NOT NULL`;
  · 逐行用「同 index_id、date 更早、close 非空的最近一条 close」回算 pct;
  · 只 UPDATE pct_change 一列,**不碰 OHLC/amount**;更新带 `pct_change IS NULL` 守卫;
  · 与审计里记录的被抹前旧值交叉验证,超出容差的行**单独列出并跳过**(交人工确认)。

安全
  · 默认 dry-run(只打印将改行数与样例 10 行);`--apply` 才写库;
  · 写库前把将改行导出到 /tmp 备份文件(§25 删除/覆盖前必备份),回滚方式=按备份把
    pct_change 置回 NULL;
  · 幂等可重跑:修过的行 pct 不再为 NULL,重跑候选自然归零。

用法
    python scripts/repair_index_pct_null.py                 # dry-run(默认)
    python scripts/repair_index_pct_null.py --apply         # 执行
    python scripts/repair_index_pct_null.py --db /path/x.db # 指定库(本机镜像/测试库)
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).absolute().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.collector.index_pct import prev_close_from_db  # noqa: E402

# 审计表 before_val/after_val 的格式: app/history_audit._fmt_vals → "open|high|low|close|pct|amount"
_PCT_IDX = 4
_TOL_REL = 1e-5
_TOL_ABS = 1e-6
_SAMPLE_N = 10


def _parse_pct(s):
    """审计格式的 pct 字段 → float;'-'(缺失)或非法值 → None。"""
    if not s:
        return None
    parts = s.split("|")
    if len(parts) <= _PCT_IDX:
        return None
    raw = parts[_PCT_IDX]
    if raw == "-":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _open_db(db_path: str | None):
    if db_path:
        conn = sqlite3.connect(db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn
    from app.db import get_conn
    return get_conn()


def find_candidates(conn):
    """审计表定位「pct 有值→缺失」候选(降序取该行最后一次审计记录)。"""
    rows = conn.execute(
        "SELECT a.date, a.index_id, a.before_val, a.after_val "
        "FROM history_overwrite_audit a "
        "JOIN (SELECT date, index_id, MAX(id) AS mid FROM history_overwrite_audit "
        "      WHERE src_table='index_daily' AND kind='changed' "
        "      GROUP BY date, index_id) m "
        "  ON a.id = m.mid "
        "JOIN index_daily i ON i.date = a.date AND i.index_id = a.index_id "
        "WHERE a.src_table='index_daily' AND a.kind='changed' "
        "  AND i.pct_change IS NULL AND i.close IS NOT NULL "
        "ORDER BY a.index_id, a.date"
    ).fetchall()
    out = []
    for r in rows:
        before_pct = _parse_pct(r["before_val"])
        after_pct = _parse_pct(r["after_val"])
        if before_pct is None or after_pct is not None:
            continue  # 只修「值→缺失」;缺失→有值/值→值 不是本次目标
        out.append({
            "date": r["date"],
            "index_id": r["index_id"],
            "audit_before_pct": before_pct,
            "audit_before_val": r["before_val"],
        })
    return out


def plan(conn, candidates):
    """逐行算新值 + 与审计旧值交叉验证。返回 (repairable, skipped)。"""
    repairable, skipped = [], []
    for c in candidates:
        row = conn.execute(
            "SELECT close FROM index_daily WHERE date=? AND index_id=? AND pct_change IS NULL",
            (c["date"], c["index_id"]),
        ).fetchone()
        if row is None or row[0] is None:
            skipped.append((c, "已非 NULL 或 close 空(可能已被别的路径修掉)"))
            continue
        close = float(row[0])
        prev_close = prev_close_from_db(conn, c["index_id"], c["date"])
        if prev_close is None or float(prev_close) == 0:
            skipped.append((c, "无更早的前收,无法回算"))
            continue
        new_pct = (close / float(prev_close) - 1.0) * 100.0
        before = c["audit_before_pct"]
        if abs(new_pct - before) > max(_TOL_ABS, abs(before) * _TOL_REL):
            skipped.append((c, f"回算 {new_pct:.6f} 与审计旧值 {before:.6f} 不一致"))
            continue
        repairable.append({**c, "close": close, "prev_close": float(prev_close),
                           "new_pct": new_pct})
    return repairable, skipped


def _write_backup(items, stamp):
    """写库前导出将改行(§25:先备份,验可恢复,再改)。返回 (路径, 行数)。"""
    path = Path(f"/tmp/repair_index_pct_null_backup_{stamp}.tsv")
    lines = ["index_id\tdate\told_pct\tnew_pct\tprev_close\taudit_before_pct"]
    for it in items:
        lines.append("\t".join([
            it["index_id"], it["date"], "NULL", f"{it['new_pct']:.10f}",
            f"{it['prev_close']:.10f}", f"{it['audit_before_pct']:.10f}",
        ]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path, len(items)


def main(argv=None):
    ap = argparse.ArgumentParser(description="一次性修复 index_daily.pct_change 被抹成 NULL 的行")
    ap.add_argument("--apply", action="store_true", help="真正写库(默认 dry-run 只打印)")
    ap.add_argument("--db", default=None, help="库文件路径(缺省=app.db 生产库路径)")
    args = ap.parse_args(argv)

    conn = _open_db(args.db)
    try:
        candidates = find_candidates(conn)
        repairable, skipped = plan(conn, candidates)
        print(f"[候选] 审计定位「pct 值→缺失」且当前仍为 NULL: {len(candidates)} 行")
        print(f"[将改] 可回算且与审计旧值一致: {len(repairable)} 行")
        print(f"[跳过] {len(skipped)} 行")
        for c, why in skipped[:_SAMPLE_N]:
            print(f"    - skip {c['index_id']} {c['date']}: {why}")
        if len(skipped) > _SAMPLE_N:
            print(f"    ... 其余 {len(skipped) - _SAMPLE_N} 行同理")
        for it in repairable[:_SAMPLE_N]:
            print(f"    · {it['index_id']} {it['date']}: NULL -> {it['new_pct']:.6f} "
                  f"(close={it['close']} prev={it['prev_close']})")
        if len(repairable) > _SAMPLE_N:
            print(f"    ... 其余 {len(repairable) - _SAMPLE_N} 行同式")

        if not args.apply:
            print("[dry-run] 未写库。确认无误后加 --apply 执行。")
            return 0
        if not repairable:
            print("[apply] 无待改行(已修过或无可回算行),未写库。")
            return 0

        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path, n = _write_backup(repairable, stamp)
        back = [ln.split("\t") for ln in backup_path.read_text(encoding="utf-8").splitlines()[1:]]
        if len(back) != n or n != len(repairable):
            print(f"[FAIL] 备份校验不过: 期望 {len(repairable)} 行, 实际 {len(back)} 行 -> 不写库")
            return 2
        print(f"[备份] {n} 行 -> {backup_path} (校验通过;回滚=按备份把 pct_change 置回 NULL)")

        updated = 0
        conn.execute("BEGIN")
        try:
            for it in repairable:
                cur = conn.execute(
                    "UPDATE index_daily SET pct_change=? "
                    "WHERE date=? AND index_id=? AND pct_change IS NULL",
                    (it["new_pct"], it["date"], it["index_id"]),
                )
                if cur.rowcount != 1:
                    raise RuntimeError(
                        f"更新行数={cur.rowcount}(期望 1): {it['index_id']} {it['date']}")
                updated += 1
            conn.commit()
        except Exception:
            conn.rollback()
            print("[FAIL] 写入异常,已回滚;备份文件保留可查。")
            raise
        print(f"[apply] 已修复 {updated} 行(pct_change 单列;OHLC/amount 未动)。")
        # 幂等自检:已修行不应再「可修」;剩下只有本次跳过的(修不了的)行
        left = find_candidates(conn)
        left_repairable, _ = plan(conn, left)
        print(f"[自检] 重跑候选 {len(left)} 行,其中仍可修 {len(left_repairable)} 行(期望 0)"
              f" -> {'PASS' if not left_repairable else 'FAIL'}")
        return 0 if not left_repairable else 3
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())