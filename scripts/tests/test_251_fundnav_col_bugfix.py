#!/usr/bin/env python3
"""#251 回归测试：fund_daily_nav 采集「列选择 + 当日未发布回退」根治。

真实事故（10-08/10-09/10-12 unit_nav 全 NULL）：
  东财在新交易日「先把 showday 滚到当日、稍后才发布当日净值」。16:30/17:00 采集撞上这个
  「滚动未发布」窗口时，旧逻辑照写一整批 unit_nav/acc_nav 全 NULL 的「当日」行进
  fund_daily_nav，而当天真实可用的前一日净值只被塞进次日的 prev_unit_nav 错列里、永远
  回不到它自己那一天。云上日志为证：20261008_1630 写 @20260930(24218 行)、
  20261008_1700 写 @20261008(24218 行) 且当日列全空。

本测试：
  · 断言输入取自 2026-10-12 真实响应（列名 + 真实行值，见 REAL_* 常量）；
  · 「未发布当日列」用真实空单元格形态（空字符串 ""，非 NaN）构造——这是东财实际返回的
    形态，也是旧代码 notna()/按列序取用的失守点；
  · 在旧代码上 FAIL、在新代码上 PASS（旧逻辑在 run_01 由 `_legacy_fetch_daily_nav` 复刻
    并逐位验证「确实写出全 NULL 当日行」，证明 fixture 能触发该 bug）。

CI 防护（must-fix-1，2026-10-12 独立审查）：
  原版 `_check` 只记录不 assert，且用例名 `test_*` 被 pytest 当空壳收集 ⇒ CI 闸门
  （.github/workflows/ci.yml:123 `python3 -m pytest -q scripts/tests/`）里 6 passed 却零防护
  （§18 L49 空转养绿）。现改为：①用例改名 `run_*`（进程式，不被 pytest 空壳收集）
  ②新增 `test_251_fundnav_col_bugfix_ci_gate`（pytest 唯一入口）经 house 桥接
  `scripts/tests/_wrap_util.py::run_script_main` 跑完整 main()，断「无 FAIL 检查 + 检查数下限
  + 零真实外发」。期望值改错 ⇒ 该 gate FAIL（非 0）。

用法：python3 scripts/tests/test_251_fundnav_col_bugfix.py
退出码 0=全过；1=有 FAIL。
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from app.collector import public_fund as pf  # noqa: E402

# ── 真实样本锚点：2026-10-12 实际响应（akshare 1.18.64 / fund_open_fund_daily_em）──────
REAL_COLS = [
    "基金代码", "基金简称",
    "2026-10-12-单位净值", "2026-10-12-累计净值",
    "2026-10-09-单位净值", "2026-10-09-累计净值",
    "日增长值", "日增长率", "申购状态", "赎回状态", "手续费",
]
REAL_ROWS = [
    {"基金代码": "026990", "基金简称": "国泰产业智选混合发起A",
     "2026-10-12-单位净值": "0.8051", "2026-10-12-累计净值": "0.8051",
     "2026-10-09-单位净值": "0.7832", "2026-10-09-累计净值": "0.7832",
     "日增长值": "0.0219", "日增长率": "2.80", "申购状态": "开放申购",
     "赎回状态": "开放赎回", "手续费": "0.05%"},
    {"基金代码": "026991", "基金简称": "国泰产业智选混合发起C",
     "2026-10-12-单位净值": "0.8043", "2026-10-12-累计净值": "0.8043",
     "2026-10-09-单位净值": "0.7824", "2026-10-09-累计净值": "0.7824",
     "日增长值": "0.0219", "日增长率": "2.80", "申购状态": "开放申购",
     "赎回状态": "开放赎回", "手续费": "0.00%"},
    {"基金代码": "161226", "基金简称": "国投瑞银白银期货(LOF)A",
     "2026-10-12-单位净值": "1.6758", "2026-10-12-累计净值": "1.6758",
     "2026-10-09-单位净值": "1.6372", "2026-10-09-累计净值": "1.6372",
     "日增长值": "0.0386", "日增长率": "2.36", "申购状态": "暂停申购",
     "赎回状态": "开放赎回", "手续费": "0.10%"},
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS fund_daily_nav (
    date TEXT NOT NULL, fund_code TEXT NOT NULL,
    fund_name TEXT, unit_nav REAL, acc_nav REAL,
    prev_unit_nav REAL, nav_change_pct REAL,
    PRIMARY KEY (date, fund_code)
);
"""

_RESULTS: list[tuple[bool, str]] = []
_MIN_CHECKS = 24          # 全用例 `_check` 条数（run_01..run_06 实测 24）；CI gate 的防删下限（§18 L49）


def _check(cond: bool, label: str) -> None:
    _RESULTS.append((bool(cond), label))
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}", flush=True)


def _mk_df(cols: list[str], rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=cols)


def _race_df() -> pd.DataFrame:
    """10-13 16:30 撞上「滚动未发布」窗口的真实形态：
    当日(10-13)两列全空字符串 + 日增长率给 '0.00'，前一日(10-12)列是 2026-10-12 真实净值。

    注(nit-1 订正, 2026-10-12 独立审查): 此处「未发布日 日增长率 = 0.00」是**比真实更严格**的
    构造 —— 事故备份实测 10-08/09/12 的 DB nav_change_pct 是**全 NULL**(非 0.0), 即东财未发布
    日的日增长率实为缺失而非 0。构造成 '0.00' 可额外验证「新逻辑不得把未发布日的涨跌串记到
    回退日头上」(run_02 末条断言), 本身有效, 故不改数据, 只订正注释措辞。"""
    cols = [
        "基金代码", "基金简称",
        "2026-10-13-单位净值", "2026-10-13-累计净值",
        "2026-10-12-单位净值", "2026-10-12-累计净值",
        "日增长值", "日增长率", "申购状态", "赎回状态", "手续费",
    ]
    rows = []
    for r in REAL_ROWS:  # 真实 10-12 值挂在「前一日」列上，与事故当天的响应同形
        rows.append({
            "基金代码": r["基金代码"], "基金简称": r["基金简称"],
            "2026-10-13-单位净值": "", "2026-10-13-累计净值": "",
            "2026-10-12-单位净值": r["2026-10-12-单位净值"],
            "2026-10-12-累计净值": r["2026-10-12-累计净值"],
            # 未发布日构造「日增长率 = 0.00」（比真实更严格, 见本函数 docstring nit-1 订正注释）
            "日增长值": "0.00", "日增长率": "0.00",
            "申购状态": "开放申购", "赎回状态": "开放赎回", "手续费": "0.05%",
        })
    return _mk_df(cols, rows)


def _legacy_fetch_daily_nav(df: pd.DataFrame, db_path: Path) -> str:
    """旧实现逐行复刻（#251 修复前 app/collector/public_fund.py:878-919）。

    保留旧逻辑的失守点：按 `"-单位净值" in c and "2026" in c` 取第一个日期列当「今日」、
    按 unit_cols[1] 取「前日」、INSERT OR REPLACE、用列序而非列名里的日期。返回写入的日期。"""
    cols = list(df.columns)
    today_col_unit = next((c for c in cols if "-单位净值" in c and "2026" in c), None)
    today_col_acc = next((c for c in cols if "-累计净值" in c and "2026" in c), None)
    prev_col_unit = None
    unit_cols = [c for c in cols if "-单位净值" in c]
    if len(unit_cols) >= 2:
        prev_col_unit = unit_cols[1]
    parts = today_col_unit.split("-")
    today_str = f"{parts[0]}{parts[1]}{parts[2]}"
    rows = []
    for _, r in df.iterrows():
        rows.append((
            today_str, str(r.get("基金代码", "")).strip(), str(r.get("基金简称", "")).strip(),
            pf._safe_float(r.get(today_col_unit)),
            pf._safe_float(r.get(today_col_acc)) if today_col_acc else None,
            pf._safe_float(r.get(prev_col_unit)) if prev_col_unit else None,
            pf._safe_float(r.get("日增长率")),
        ))
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    conn.executemany(
        "INSERT OR REPLACE INTO fund_daily_nav"
        "(date,fund_code,fund_name,unit_nav,acc_nav,prev_unit_nav,nav_change_pct) VALUES (?,?,?,?,?,?,?)",
        rows)
    conn.commit()
    conn.close()
    return today_str


def _fresh_db() -> Path:
    d = Path(tempfile.mkdtemp(prefix="t251_"))
    p = d / "public_fund.db"
    conn = sqlite3.connect(p)
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()
    return p


def _run_fixed(df: pd.DataFrame, db_path: Path) -> int:
    """把模块的 DB_PATH/ak 换成测试替身，调用真实 fetch_daily_nav。"""
    orig_db, orig_ak = pf.DB_PATH, pf.ak.fund_open_fund_daily_em
    pf.DB_PATH = db_path
    pf.ak.fund_open_fund_daily_em = lambda *a, **k: df
    try:
        return pf.fetch_daily_nav()
    finally:
        pf.DB_PATH = orig_db
        pf.ak.fund_open_fund_daily_em = orig_ak


def _q(db_path: Path, sql: str, args=()):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


# ── 用例 ────────────────────────────────────────────────────────────────────────
def run_01_fixture_triggers_bug_on_legacy() -> None:
    """L49 前置：先证明 race fixture 在旧逻辑下确实产出全 NULL 当日行（否则 fixture 无效）。"""
    print("test_01 旧逻辑在 race fixture 上复现 bug（fixture 有效性）")
    db = _fresh_db()
    written = _legacy_fetch_daily_nav(_race_df(), db)
    _check(written == "20261013", f"旧逻辑把日期写成未发布当日 20261013（实际 {written}）")
    rows = _q(db, "SELECT unit_nav, acc_nav FROM fund_daily_nav WHERE date='20261013'")
    _check(len(rows) == 3, f"旧逻辑为未发布当日写出 3 行（实际 {len(rows)}）")
    _check(all(r["unit_nav"] is None and r["acc_nav"] is None for r in rows),
           "旧逻辑写出的当日行 unit_nav/acc_nav 全 NULL（=事故形态）")


def run_02_new_code_falls_back_to_published_prev_day() -> None:
    """新逻辑：当日未发布 → 回退到次新已发布日，不写全 NULL 当日行。"""
    print("test_02 新逻辑：未发布当日回退（10-08/09/12 根因场景）")
    db = _fresh_db()
    n = _run_fixed(_race_df(), db)
    _check(n == 3, f"仍写 3 行（实际 {n}）")
    _check(len(_q(db, "SELECT 1 FROM fund_daily_nav WHERE date='20261013'")) == 0,
           "未为「未发布当日 20261013」写任何行")
    r = _q(db, "SELECT unit_nav, acc_nav, nav_change_pct FROM fund_daily_nav "
               "WHERE date='20261012' AND fund_code='026990'")
    _check(len(r) == 1, "已发布日前一日 20261012 落行")
    _check(r and r[0]["unit_nav"] == 0.8051, f"026990 20261012 unit_nav=0.8051（实际 {r and r[0]['unit_nav']}）")
    _check(r and r[0]["acc_nav"] == 0.8051, f"026990 20261012 acc_nav=0.8051（实际 {r and r[0]['acc_nav']}）")
    # 回退日不得继承「未发布当日」的 日增长率（0.00），否则等于把当日涨跌记到前一日头上
    _check(r and r[0]["nav_change_pct"] is None,
           f"回退日 nav_change_pct 置空、不串用未发布日的 0.00（实际 {r and r[0]['nav_change_pct']}）")
    r2 = _q(db, "SELECT unit_nav FROM fund_daily_nav WHERE date='20261012' AND fund_code='161226'")
    _check(r2 and r2[0]["unit_nav"] == 1.6758, f"161226 20261012 unit_nav=1.6758（实际 {r2 and r2[0]['unit_nav']}）")


def run_03_normal_response_writes_newest_full_row() -> None:
    """正常（当日已发布）：写最新日，unit/acc/prev/pct 齐。"""
    print("test_03 新逻辑：正常响应写最新已发布日全字段")
    db = _fresh_db()
    n = _run_fixed(_mk_df(REAL_COLS, REAL_ROWS), db)
    _check(n == 3, f"写 3 行（实际 {n}）")
    r = _q(db, "SELECT unit_nav, acc_nav, prev_unit_nav, nav_change_pct FROM fund_daily_nav "
               "WHERE date='20261012' AND fund_code='026990'")
    _check(r and r[0]["unit_nav"] == 0.8051, f"unit_nav=0.8051（实际 {r and r[0]['unit_nav']}）")
    _check(r and r[0]["acc_nav"] == 0.8051, f"acc_nav=0.8051（实际 {r and r[0]['acc_nav']}）")
    _check(r and r[0]["prev_unit_nav"] == 0.7832, f"prev_unit_nav=0.7832（实际 {r and r[0]['prev_unit_nav']}）")
    _check(r and r[0]["nav_change_pct"] == 2.80, f"nav_change_pct=2.80（实际 {r and r[0]['nav_change_pct']}）")
    _check(len(_q(db, "SELECT 1 FROM fund_daily_nav WHERE date='20261009'")) == 0,
           "不把 prev 列另写一行（prev 仅作列值）")


def run_04_column_order_independent() -> None:
    """抵抗上游列序微调：把两个日期列整体倒序，仍须认最新日。"""
    print("test_04 新逻辑：列序倒置仍认最新日（抗上游微调）")
    db = _fresh_db()
    rev = REAL_COLS[:2] + REAL_COLS[4:6] + REAL_COLS[2:4] + REAL_COLS[6:]
    _check(rev[2].startswith("2026-10-09"), "fixture 列序确已倒置（09 在前）")
    _run_fixed(_mk_df(rev, REAL_ROWS), db)
    _check(len(_q(db, "SELECT 1 FROM fund_daily_nav WHERE date='20261012'")) == 3,
           "倒序下仍写最新日 20261012 三行")
    _check(len(_q(db, "SELECT 1 FROM fund_daily_nav WHERE date='20261009'")) == 0,
           "倒序下未误写 20261009")


def run_05_fallback_does_not_clobber_existing_values() -> None:
    """回退重写「前一日」行时，不得抹掉该行已有的 prev_unit_nav/nav_change_pct（COALESCE 保留）。"""
    print("test_05 新逻辑：回退写不踩踏已有值（COALESCE）")
    db = _fresh_db()
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO fund_daily_nav(date,fund_code,fund_name,unit_nav,acc_nav,"
                 "prev_unit_nav,nav_change_pct) VALUES('20261012','026990','x',NULL,NULL,1.111,-9.99)")
    conn.commit()
    conn.close()
    _run_fixed(_race_df(), db)
    r = _q(db, "SELECT unit_nav, prev_unit_nav, nav_change_pct FROM fund_daily_nav "
               "WHERE date='20261012' AND fund_code='026990'")[0]
    _check(r["unit_nav"] == 0.8051, f"空 unit_nav 被补上 0.8051（实际 {r['unit_nav']}）")
    _check(r["prev_unit_nav"] == 1.111, f"已有 prev_unit_nav=1.111 未被抹（实际 {r['prev_unit_nav']}）")
    _check(r["nav_change_pct"] == -9.99, f"已有 nav_change_pct=-9.99 未被抹（实际 {r['nav_change_pct']}）")


def run_06_all_columns_blank_returns_zero() -> None:
    """所有日期列都未发布：不写行、返回 0（不制造全 NULL 批）。"""
    print("test_06 新逻辑：全列未发布 → 不写")
    db = _fresh_db()
    cols = ["基金代码", "基金简称", "2026-10-13-单位净值", "2026-10-13-累计净值",
            "2026-10-12-单位净值", "2026-10-12-累计净值", "日增长值", "日增长率"]
    rows = [{"基金代码": "026990", "基金简称": "A",
             "2026-10-13-单位净值": "", "2026-10-13-累计净值": "",
             "2026-10-12-单位净值": "", "2026-10-12-累计净值": "",
             "日增长值": "0.00", "日增长率": "0.00"}]
    n = _run_fixed(_mk_df(cols, rows), db)
    _check(n == 0, f"返回 0（实际 {n}）")
    _check(len(_q(db, "SELECT 1 FROM fund_daily_nav")) == 0, "DB 无新增行")


def main() -> int:
    for fn in (run_01_fixture_triggers_bug_on_legacy,
               run_02_new_code_falls_back_to_published_prev_day,
               run_03_normal_response_writes_newest_full_row,
               run_04_column_order_independent,
               run_05_fallback_does_not_clobber_existing_values,
               run_06_all_columns_blank_returns_zero):
        fn()
    bad = [lbl for ok, lbl in _RESULTS if not ok]
    print(f"\n{'=' * 60}\n#251 回归：{len(_RESULTS) - len(bad)}/{len(_RESULTS)} 通过", flush=True)
    if bad:
        for b in bad:
            print(f"  FAIL: {b}", flush=True)
        return 1
    print("ALL PASS", flush=True)
    return 0


# ── CI 闸门 ⑧ 入口（must-fix-1）─────────────────────────────────────────────────
def test_251_fundnav_col_bugfix_ci_gate() -> None:
    """pytest 唯一入口（.github/workflows/ci.yml job ⑧ `pytest -q scripts/tests/`）。

    本文件是「进程式 main() + PASS/FAIL 计数」形态，house 机制 = `_wrap_util.run_script_main`
    桥接（与 test_188/test_204/test_ai_macro_hit_filters 同款）：import 本模块 → 调 main() →
    零外发陷阱包裹 → 按本脚本自己的计数断言。传 `__name__` 而非硬编码模块名，使本文件被复制
    成任意副本（如变异验证副本）时仍桥接**副本自身**，变异即被捕获。
    """
    from _wrap_util import run_script_main  # scripts/tests/ 同目录(house 薄包装工具)

    r = run_script_main(__name__)
    bad = [lbl for ok, lbl in r.mod._RESULTS if not ok]
    assert not bad, f"#251 回归有 FAIL 检查: {bad}\n{r.out[-3000:]}"
    assert len(r.mod._RESULTS) >= _MIN_CHECKS, (
        f"#251 仅记录 {len(r.mod._RESULTS)} 条检查（下限 {_MIN_CHECKS}），"
        f"疑似断言被删/未执行（§18 L49 假绿）\n{r.out[-3000:]}")
    assert r.trap_hits == [], f"零真实外发被破坏（§18 L48）hits={r.trap_hits}"
    print(f"#251 fundnav 回归（CI 闸门）: {len(r.mod._RESULTS)} 条检查全过，零真实外发")


if __name__ == "__main__":
    sys.exit(main())