#!/usr/bin/env python3
"""check_sim_trade_append_only.py - 模拟交易账本 append-only 闸门(静态扫描 + 临时库实测)。

三层检查:
  ① 静态: sim_trade_*.py 源码里禁出现对 sim_trade_* 表的 UPDATE / DELETE /
     INSERT OR REPLACE / REPLACE INTO(唯一例外: 触发器 DDL 自身的 RAISE 文案)。
  ② 结构: 临时库 --init 后 4 表 / 3 视图 / 8 触发器 / integrity_check=ok。
  ③ 实测: 向 4 张表各插 1 行, 逐表尝试 UPDATE 与 DELETE, 必须全部 IntegrityError(ABORT);
     再试 INSERT OR REPLACE 命中主键冲突, 必须同样 ABORT(REPLACE 先 DELETE 被拦)。

退出码: 0=全 PASS, 1=任一层 FAIL(打印失败项)。
用法: python3 scripts/check_sim_trade_append_only.py [--scripts-dir scripts]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sim_trade_db as db  # noqa: E402

FORBIDDEN = [
    (re.compile(r"\bUPDATE\s+sim_trade_\w+", re.I), "UPDATE sim_trade_*"),
    (re.compile(r"\bDELETE\s+FROM\s+sim_trade_\w+", re.I), "DELETE FROM sim_trade_*"),
    (re.compile(r"INSERT\s+OR\s+REPLACE", re.I), "INSERT OR REPLACE"),
    (re.compile(r"\bREPLACE\s+INTO\b", re.I), "REPLACE INTO"),
]

# 触发器 DDL 里必然出现 "BEFORE UPDATE ON sim_trade_x" / "BEFORE DELETE ON sim_trade_x",
# 这是允许的(它是拦截器本身), 静态扫描需剔除以 BEFORE 开头的 DDL 行。
TRIGGER_DDL_PAT = re.compile(r"BEFORE\s+(UPDATE|DELETE)\s+ON\s+sim_trade_", re.I)


def _sql_like_strings(path: Path):
    """提取源码里的非 docstring 字符串常量(注释天然忽略; docstring 是说明文字不算 SQL)。"""
    import ast
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docs.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            yield node.lineno, node.value


def static_scan(scripts_dir: Path) -> list[str]:
    bad = []
    for p in sorted(scripts_dir.glob("sim_trade_*.py")):
        for lineno, text in _sql_like_strings(p):
            if TRIGGER_DDL_PAT.search(text) or "RAISE(ABORT" in text:
                continue  # 触发器拦截器 DDL 本身允许出现 BEFORE UPDATE/DELETE
            for pat, name in FORBIDDEN:
                if pat.search(text):
                    bad.append(f"{p.name}:{lineno}: {name} -> {text.strip()[:120]}")
    return bad


def _seed_rows(con: sqlite3.Connection) -> dict:
    """每表插一行最小合法数据, 返回 {table: primary_key_column}。"""
    now = db.now_iso()
    con.execute(
        "INSERT INTO sim_trade_signal (signal_id, signal_date, exec_date, sell_due_date, index_id,"
        " etf_code, source, frozen_at, trigger_source, created_at)"
        " VALUES ('sig_test','20260101','20260102','20260115','IDX','510300','log',?, 'test', ?)",
        (now, now))
    con.execute(
        "INSERT INTO sim_trade_order (order_id, signal_id, side, action, etf_code, intended_at,"
        " triggered_at, trigger_source, created_at)"
        " VALUES ('ord_test','sig_test','buy','open','510300','09:30',?,'test',?)", (now, now))
    con.execute(
        "INSERT INTO sim_trade_fill (fill_id, order_id, side, fill_date, price_kind, price_raw,"
        " source, created_at) VALUES ('fill_test','ord_test','buy','20260102','open',4.0,'test',?)",
        (now,))
    con.execute(
        "INSERT INTO sim_trade_event (event_id, order_id, signal_id, event_type, event_at, created_at)"
        " VALUES ('evt_test','ord_test','sig_test','trigger_run',?,?)", (now, now))
    con.commit()
    return {
        "sim_trade_signal": ("signal_id", "sig_test"),
        "sim_trade_order": ("order_id", "ord_test"),
        "sim_trade_fill": ("fill_id", "fill_test"),
        "sim_trade_event": ("event_id", "evt_test"),
    }


def _must_abort(con, sql: str, params=()) -> str | None:
    try:
        con.execute(sql, params)
        con.rollback()
        return "NOT_ABORTED"
    except sqlite3.IntegrityError as exc:
        con.rollback()
        msg = str(exc)
        return None if "append-only" in msg else f"WRONG_ERROR: {msg}"
    except sqlite3.DatabaseError as exc:
        con.rollback()
        return f"WRONG_ERROR: {exc}"


def dynamic_check() -> dict:
    tmp = tempfile.mkdtemp(prefix="sim_trade_gate_")
    path = Path(tmp) / "gate.db"
    con = db.init_db(path)
    fails = []
    try:
        structure = db.check_db(con)
        if not structure["ok"]:
            fails.append(f"structure: {structure}")
        seeds = _seed_rows(con)
        aborts = {}
        for table, (pk, val) in seeds.items():
            for sql in (f"UPDATE {table} SET {pk}={pk} WHERE {pk}=?",
                        f"DELETE FROM {table} WHERE {pk}=?"):
                err = _must_abort(con, sql, (val,))
                aborts[f"{table}:{sql.split()[0]}"] = "ABORT" if err is None else err
                if err:
                    fails.append(f"{table}:{sql.split()[0]}: {err}")
        # INSERT OR REPLACE 命中主键 → 内部先 DELETE → 必须 ABORT
        err = _must_abort(con, "INSERT OR REPLACE INTO sim_trade_signal (signal_id, signal_date,"
                               " exec_date, sell_due_date, index_id, etf_code, source, frozen_at,"
                               " trigger_source, created_at) VALUES"
                               " ('sig_test','20260101','20260102','20260115','IDX','510300','log',"
                               "'x','test','x')")
        aborts["sim_trade_signal:INSERT OR REPLACE"] = "ABORT" if err is None else err
        if err:
            fails.append(f"INSERT OR REPLACE: {err}")
        counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in seeds}
    finally:
        con.close()
        for f in path.parent.glob("*"):
            f.unlink(missing_ok=True)
        path.parent.rmdir()
    return {"structure": structure, "aborts": aborts, "counts_after_attempts": counts, "fails": fails}


def run(scripts_dir: Path) -> dict:
    static = static_scan(scripts_dir)
    dyn = dynamic_check()
    return {
        "static_forbidden_hits": static,
        "structure_ok": dyn["structure"]["ok"],
        "trigger_count": dyn["structure"]["trigger_count"],
        "aborts": dyn["aborts"],
        "counts_after_attempts": dyn["counts_after_attempts"],
        "pass": not static and not dyn["fails"],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="模拟交易账本 append-only 闸门")
    ap.add_argument("--scripts-dir", default=str(SCRIPT_DIR))
    args = ap.parse_args(argv)
    out = run(Path(args.scripts_dir))
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
