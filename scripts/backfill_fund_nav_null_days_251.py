#!/usr/bin/env python3
"""#251 一次性回填：fund_daily_nav「unit_nav 全 NULL 天」修复工具。

背景（真实事故）：东财在新交易日「先把 showday 滚到当日、稍后才发布当日净值」。采集器
16:30/17:00 撞上这个滚动窗口时，会写出一整批 unit_nav/acc_nav/nav_change_pct 全 NULL 的
「当日」行，而当天真实可用的前一日净值只被塞进次日的 prev_unit_nav 列里、回不到它自己
那一天。已知受影响日：09-28/29/30、10-08/10-09/10-12。代码侧根治见
app/collector/public_fund.py:fetch_daily_nav（列名日期解析 + 未发布回退 + COALESCE UPSERT）。

本工具只做**数据修复**，两条回填路径，均取真实值、不造数：
  A) `--live-refresh`：实时拉 fund_open_fund_daily_em，取「已发布的最新日期列」的单位净值/
     累计净值/前日单价/日增长率，写回该日期行（COALESCE 只补空、不覆盖）。
  B) 链式回填：对每个 `--dates` 传入的日期 D，unit_nav(D) = 次一交易日行(D') 的
     prev_unit_nav（= D 的真实单位净值）；再派生 nav_change_pct(D) =
     (unit_nav(D)/prev_unit_nav(D)-1)*100（D 行现存 prev_unit_nav 即有）。
     acc_nav 在 B 路无来源 → **保持 NULL 并计数上报**，绝不推算（累计净值含分红，无法由单位
     净值反推）。

幂等：仅更新 unit_nav IS NULL 的行；重复跑不改已填行。`--dry-run` 只打印计划。

用法：
  python3 scripts/backfill_fund_nav_null_days_251.py --dates 20261008,20261009 --live-refresh --dry-run
  python3 scripts/backfill_fund_nav_null_days_251.py --dates 20261008,20261009 --live-refresh
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _ROOT / "data" / "public_fund.db"


def _safe_float(v, default=None):
    if v is None:
        return default
    try:
        if isinstance(v, str):
            v = v.strip().replace("%", "").replace(",", "")
            if v in ("", "--", "-", "nan", "NaN"):
                return default
        f = float(v)
        return default if f != f else f
    except (TypeError, ValueError):
        return default


def _conn(db: Path) -> sqlite3.Connection:
    c = sqlite3.connect(db, timeout=30.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000;")
    return c


def stats(c: sqlite3.Connection, dates: list[str]) -> dict:
    out = {}
    for d in dates:
        r = c.execute(
            "SELECT COUNT(*) n, SUM(unit_nav IS NOT NULL) u, SUM(acc_nav IS NOT NULL) a, "
            "SUM(prev_unit_nav IS NOT NULL) p, SUM(nav_change_pct IS NOT NULL) pc "
            "FROM fund_daily_nav WHERE date=?", (d,)).fetchone()
        out[d] = dict(n=r["n"], unit_nn=r["u"] or 0, acc_nn=r["a"] or 0,
                      prev_nn=r["p"] or 0, pct_nn=r["pc"] or 0)
    return out


def live_refresh(c: sqlite3.Connection, dry: bool) -> str | None:
    """A 路：实时响应里「已发布的最新日期列」整行写回。返回写入日期（YYYYMMDD）或 None。"""
    import akshare as ak
    df = ak.fund_open_fund_daily_em()
    if df is None or len(df) == 0:
        print("[A] FAIL: 实时响应为空")
        return None
    unit_by_date, acc_by_date = {}, {}
    for col in df.columns:
        s = str(col)
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})-单位净值$", s)
        if m:
            unit_by_date["".join(m.groups())] = s
            continue
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})-累计净值$", s)
        if m:
            acc_by_date["".join(m.groups())] = s
    dates_desc = sorted(unit_by_date, reverse=True)
    if not dates_desc:
        print(f"[A] WARN 找不到日期列, cols={list(df.columns)[:6]}")
        return None
    # 目标 = 最新一个「整列已发布」的日期（当日未发布则回退次新，与 collector #251 同规则）
    target = next((d for d in dates_desc
                   if any(_safe_float(v) is not None for v in df[unit_by_date[d]])), None)
    if target is None:
        print("[A] WARN 所有日期列均未发布")
        return None
    idx = dates_desc.index(target)
    prev_col = unit_by_date[dates_desc[idx + 1]] if idx + 1 < len(dates_desc) else None
    use_pct = target == dates_desc[0]
    cu, ca = unit_by_date[target], acc_by_date.get(target)
    rows = []
    for _, r in df.iterrows():
        code = str(r.get("基金代码", "")).strip()
        if not code:
            continue
        rows.append((code, str(r.get("基金简称", "")).strip(),
                     _safe_float(r.get(cu)), _safe_float(r.get(ca)) if ca else None,
                     _safe_float(r.get(prev_col)) if prev_col else None,
                     _safe_float(r.get("日增长率")) if use_pct else None))
    print(f"[A] live 最新已发布日={target}（列序 {dates_desc}）准备写 {len(rows)} 行"
          + ("  [dry-run]" if dry else ""))
    if dry:
        return target
    c.executemany(
        "INSERT INTO fund_daily_nav(date,fund_code,fund_name,unit_nav,acc_nav,"
        "prev_unit_nav,nav_change_pct) VALUES(?,?,?,?,?,?,?) "
        "ON CONFLICT(date,fund_code) DO UPDATE SET "
        "fund_name=COALESCE(excluded.fund_name,fund_daily_nav.fund_name),"
        "unit_nav=COALESCE(excluded.unit_nav,fund_daily_nav.unit_nav),"
        "acc_nav=COALESCE(excluded.acc_nav,fund_daily_nav.acc_nav),"
        "prev_unit_nav=COALESCE(excluded.prev_unit_nav,fund_daily_nav.prev_unit_nav),"
        "nav_change_pct=COALESCE(excluded.nav_change_pct,fund_daily_nav.nav_change_pct)",
        [(target, *r) for r in rows])
    c.commit()
    print(f"[A] 已写 {target}")
    # A2：实时响应的「次新日期列」同样带该日的 单位净值/累计净值 —— 顺手补回该日（只补空，
    # COALESCE；不给 prev/pct，避免误改）。这是 10-09 累计净值的唯一真实来源（历史表不存在）。
    if idx + 1 < len(dates_desc):
        older = dates_desc[idx + 1]
        cu2, ca2 = unit_by_date[older], acc_by_date.get(older)
        rows2 = []
        for _, r in df.iterrows():
            code = str(r.get("基金代码", "")).strip()
            if code:
                rows2.append((older, code, str(r.get("基金简称", "")).strip(),
                              _safe_float(r.get(cu2)), _safe_float(r.get(ca2)) if ca2 else None))
        print(f"[A2] 用次新列补 {older} 的 unit/acc（只补空），{len(rows2)} 行"
              + ("  [dry-run]" if dry else ""))
        if not dry:
            c.executemany(
                "INSERT INTO fund_daily_nav(date,fund_code,fund_name,unit_nav,acc_nav) "
                "VALUES(?,?,?,?,?) ON CONFLICT(date,fund_code) DO UPDATE SET "
                "fund_name=COALESCE(excluded.fund_name,fund_daily_nav.fund_name),"
                "unit_nav=COALESCE(fund_daily_nav.unit_nav,excluded.unit_nav),"
                "acc_nav=COALESCE(fund_daily_nav.acc_nav,excluded.acc_nav)", rows2)
            c.commit()
            print(f"[A2] 已补 {older}")
    return target


def chain_fill(c: sqlite3.Connection, date: str, dry: bool) -> dict:
    """B 路：unit_nav(D) = 次一交易日行的 prev_unit_nav；再派生 nav_change_pct。"""
    nxt = c.execute("SELECT MIN(date) d FROM fund_daily_nav WHERE date>?", (date,)).fetchone()["d"]
    if not nxt:
        print(f"[B] {date} 无次一交易日行 → 跳过")
        return {}
    before = c.execute("SELECT SUM(unit_nav IS NOT NULL) u FROM fund_daily_nav WHERE date=?",
                       (date,)).fetchone()["u"] or 0
    n_fill = c.execute(
        "SELECT COUNT(*) n FROM fund_daily_nav t WHERE t.date=? AND t.unit_nav IS NULL "
        "AND (SELECT p.prev_unit_nav FROM fund_daily_nav p WHERE p.date=? "
        "     AND p.fund_code=t.fund_code AND p.prev_unit_nav IS NOT NULL) IS NOT NULL",
        (date, nxt)).fetchone()["n"]
    print(f"[B] {date}: 可由 {nxt} 的 prev_unit_nav 回填 unit_nav 的行数={n_fill} "
          f"(该日现有非空 unit_nav={before})" + ("  [dry-run]" if dry else ""))
    if dry:
        return dict(filled=n_fill)
    c.execute(
        "UPDATE fund_daily_nav AS t SET unit_nav=(SELECT p.prev_unit_nav FROM fund_daily_nav p "
        "WHERE p.date=? AND p.fund_code=t.fund_code AND p.prev_unit_nav IS NOT NULL) "
        "WHERE t.date=? AND t.unit_nav IS NULL", (nxt, date))
    # 派生涨跌幅（用该行现存 prev_unit_nav，口径与采集器一致：单位净值相对前一日 %）
    c.execute(
        "UPDATE fund_daily_nav SET nav_change_pct=ROUND((unit_nav/prev_unit_nav-1)*100,2) "
        "WHERE date=? AND unit_nav IS NOT NULL AND prev_unit_nav IS NOT NULL "
        "AND prev_unit_nav>0 AND nav_change_pct IS NULL", (date,))
    c.commit()
    print(f"[B] 已回填 {date}（unit_nav + 派生 nav_change_pct）")
    return dict(filled=n_fill)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(_DEFAULT_DB))
    ap.add_argument("--dates", required=True,
                    help="逗号分隔 YYYYMMDD，需链式回填 unit_nav 的日期（不含 live 刷新日）")
    ap.add_argument("--live-refresh", action="store_true",
                    help="A 路：实时拉东财、写回最新已发布日")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    dates = [d.strip() for d in a.dates.split(",") if d.strip()]
    db = Path(a.db)
    if not db.exists():
        print(f"DB 不存在: {db}")
        return 2
    c = _conn(db)
    print("BEFORE:", stats(c, dates + ["20260930"]))
    if a.live_refresh:
        live_refresh(c, a.dry_run)
    for d in dates:
        chain_fill(c, d, a.dry_run)
    print("AFTER :", stats(c, dates + ["20260930"]))
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())