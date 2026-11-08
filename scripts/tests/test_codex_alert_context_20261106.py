"""只执行备份校验载荷/正文片段和 R2 通知块，不运行下载、PUT 或通知主体。"""
import ast
import contextlib
import html
import io
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import types

import pytest

from test_codex_r2_alert_delivery import sandbox  # 复用已验证的八类陷阱正控/恢复

ROOT = Path(__file__).resolve().parents[2]
_REAL_POPEN = subprocess.Popen
TABLES = {
    "sentiment": ["score_daily", "daily_metric", "signal_daily", "index_daily",
                  "industry_width_daily", "futures_position", "futures_accuracy", "collect_log"],
    "etf_national_team": ["etf_daily", "etf_signal", "etf_holder_quarterly", "national_team_holders"],
    "stock_daily": ["baostock_daily_raw", "fapi_daily_raw", "mootdx_daily_raw"],
    "public_fund": ["fund_daily_nav", "fund_purchase_status", "fund_performance", "fund_rating", "fund_basic"],
}


def backup_fixture(sb):
    live, backup = sb.tmp / "live", sb.tmp / "backup"
    live.mkdir()
    backup.mkdir()
    paths = {}
    for name, tables in TABLES.items():
        paths[name] = backup / f"{name}_20240104.db"
        for path in (paths[name], live / f"{name}.db"):
            with sqlite3.connect(path) as conn:
                for table in tables:
                    conn.execute(f'CREATE TABLE "{table}" (x INTEGER)')
                    conn.execute(f'INSERT INTO "{table}" VALUES (1)')
    return live, paths


def sql(path, statement):
    with sqlite3.connect(path) as conn:
        conn.execute(statement)


def validate(sb, live, paths, notes):
    src = (ROOT / "scripts/verify_backup.sh").read_text()
    start = src.index("import datetime\n", src.index("VERIFY_REPORT=$("))
    payload = src[start:src.index("\nPYEOF", start)]
    args = [str(paths.get(n) or "") for n in TABLES]
    sb.mp.setattr(sys, "argv", ["isolated-validator", *args, str(live), notes])
    sb.mp.setenv("VERIFY_TODAY", "20240104")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(compile(payload, "verify-backup-validator", "exec"), {})
    return out.getvalue()


def render_actual_body(sb, report, pf_rc=0):
    """仅当前源码的解析/赋值片段；截断在任何通知/清理命令之前。"""
    src = (ROOT / "scripts/verify_backup.sh").read_text()
    parse = src[src.index("# 解析结果\n"):src.index("# public_fund 演练产物")]
    start = src.index('if [ "$VERIFY_OK" != "1" ]')
    block = src[start:src.index('  echo "-> 发送演练失败告警邮件', start)]
    assert "notify.py" not in parse + block and "rm -" not in parse + block
    script = 'set -eu\nRC=0\n' + parse + block + '\n printf "%s" "$BODY"\nfi\nexit "$RC"\n'
    env = {**os.environ, "VERIFY_REPORT": report, "PF_RC": str(pf_rc),
           "LOG": str(sb.tmp / "verify.log"), "TMPDIR": str(sb.tmp), "VERIFY_NOTIFY_DRY_RUN": "1"}
    # 允许的唯一子进程是上述有限的 Bash 变量/正文片段；不 source/exec 业务脚本。
    with sb.mp.context() as mp:
        mp.setattr(subprocess, "Popen", _REAL_POPEN)
        result = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True,
                                cwd=sb.tmp, env=env, timeout=5)
    assert result.returncode in (0, 1), result.stderr
    return result.returncode, html.unescape(result.stdout)


@pytest.mark.parametrize("case", ["count", "empty", "missing_backup_table", "missing_live_table",
                                   "integrity", "connect", "freshness", "undated", "ratio", "note_fail"])
def test_every_actual_fail_reaches_backup_body(sandbox, case):
    live, paths = backup_fixture(sandbox)
    notes = "public_fund=SKIP(周频未到:非周日)"
    if case == "count":
        sql(paths["sentiment"], "INSERT INTO signal_daily VALUES (2)")
        expected = ("sentiment", "signal_daily", "备份=2", "本地=1")
    elif case == "empty":
        sql(paths["sentiment"], "DELETE FROM signal_daily")
        expected = ("signal_daily", "备份空")
    elif case == "missing_backup_table":
        sql(paths["sentiment"], "DROP TABLE signal_daily")
        expected = ("signal_daily", "备份表缺失")
    elif case == "missing_live_table":
        sql(live / "sentiment.db", "DROP TABLE signal_daily")
        expected = ("signal_daily", "本地表缺失")
    elif case == "integrity":
        # PRAGMA 可返回非 ok，同时其它查询仍可执行；只注入其诊断返回值。
        connect = sqlite3.connect

        def integrity_fault(path, *args, **kwargs):
            conn = connect(path, *args, **kwargs)
            if str(paths["sentiment"]) not in str(path):
                return conn

            class Connection:
                def execute(self, statement):
                    if statement == "PRAGMA integrity_check":
                        return types.SimpleNamespace(fetchone=lambda: ("fixture integrity failure",))
                    return conn.execute(statement)

                def close(self):
                    conn.close()

            return Connection()

        sandbox.mp.setattr(sqlite3, "connect", integrity_fault)
        expected = ("sentiment", "fixture integrity failure")
    elif case == "connect":
        (live / "sentiment.db").unlink()
        expected = ("sentiment", "连接失败")
    elif case == "freshness":
        old = paths["stock_daily"].with_name("stock_daily_20231230.db")
        paths["stock_daily"].rename(old)
        paths["stock_daily"] = old
        expected = ("stock_daily", "备份过旧")
    elif case == "undated":
        p = paths["stock_daily"].with_name("undated.db")
        paths["stock_daily"].rename(p)
        paths["stock_daily"] = p
        expected = ("stock_daily", "无法判定日期")
    elif case == "ratio":
        sql(live / "public_fund.db", "INSERT INTO fund_basic VALUES (2)")
        expected = ("public_fund", "fund_basic", "备份过旧/被截断")
    else:
        notes += ';stock_daily=FAIL(LIST <bad & "x">)'
        expected = ('stock_daily=FAIL(LIST <bad & "x">)',)
    report = validate(sandbox, live, paths, notes)
    assert report.startswith("VERIFY_OK=0\n")
    rc, body = render_actual_body(sandbox, report)
    assert rc == 1 and "失败明细：" in body
    assert all(item in body for item in expected), body
    assert "public_fund=SKIP" in body
    # 逐条验证原结果中的实际失败，不只核一个固定样例。
    for line in report.splitlines():
        if line.lstrip().startswith("===") or line.startswith("VERIFY_"):
            continue
        if "✗" in line or "=FAIL" in line:
            assert line.strip() in body


def test_skip_with_unbound_source_remains_unknown(sandbox):
    live, paths = backup_fixture(sandbox)
    paths.pop("public_fund")
    report = validate(sandbox, live, paths, "public_fund=SKIP(周频未到:非周日)")
    assert report.startswith("VERIFY_OK=0\n")
    rc, body = render_actual_body(sandbox, report)
    assert rc == 1 and "unknown/not_verified" in body


def test_multiple_failure_reasons_visible_together(sandbox):
    live, paths = backup_fixture(sandbox)
    sql(paths["sentiment"], "INSERT INTO signal_daily VALUES (2)")
    sql(paths["etf_national_team"], "DROP TABLE etf_daily")
    report = validate(sandbox, live, paths, "public_fund=SKIP(周频未到:非周日)")
    rc, body = render_actual_body(sandbox, report)
    assert rc == 1
    assert all(x in body for x in ("sentiment", "signal_daily", "etf_national_team", "etf_daily", "备份表缺失"))


def track_sqlite_connections(sb):
    """真实 SQLite 执行，仅记录连接关闭；不替换 PRAGMA 或查询结果。"""
    opened = []
    connect = sqlite3.connect

    class Connection(sqlite3.Connection):
        was_closed = False

        def close(self):
            super().close()
            self.was_closed = True

    def tracked_connect(*args, **kwargs):
        conn = connect(*args, **kwargs, factory=Connection)
        opened.append(conn)
        return conn

    sb.mp.setattr(sqlite3, "connect", tracked_connect)
    return opened


@pytest.mark.parametrize("corrupt_side", ["backup", "local", "both"])
def test_real_corrupt_file_keeps_diagnostics_and_checks_other_databases(sandbox, corrupt_side):
    live, paths = backup_fixture(sandbox)
    if corrupt_side in ("backup", "both"):
        paths["sentiment"].write_bytes(b"This is a real non-SQLite file.\n" * 64)
    if corrupt_side in ("local", "both"):
        (live / "sentiment.db").write_bytes(b"This is a real non-SQLite file.\n" * 64)
    # 后面的有效库也有真实行数差；坏库不能阻止它及其后的健康库被校验。
    sql(paths["etf_national_team"], "INSERT INTO etf_daily VALUES (2)")
    opened = track_sqlite_connections(sandbox)
    report = validate(sandbox, live, paths, "")
    assert report.startswith("VERIFY_OK=0\n")
    assert len(opened) == 12 and all(c.was_closed for c in opened)
    rc, body = render_actual_body(sandbox, report)
    assert rc == 1 and "失败明细：" in body
    assert "DatabaseError: file is not a database" in body
    details = html.unescape(next(line.split("=", 1)[1] for line in report.splitlines()
                                if line.startswith("VERIFY_FAILURE_DETAILS_HTML=")))
    for table in TABLES["sentiment"]:
        diagnostic = next(line for line in report.splitlines()
                          if not line.startswith("VERIFY_") and table in line and "SQLite" in line)
        assert all(x in diagnostic for x in ("备份=", "本地=", "✗FAIL", str(paths["sentiment"]),
                                             str(live / "sentiment.db"), "DatabaseError: file is not a database"))
        assert ("备份=ERROR(" if corrupt_side in ("backup", "both") else "备份=1 ") in diagnostic
        assert ("本地=ERROR(" if corrupt_side in ("local", "both") else "本地=1 ") in diagnostic
        assert f"sentiment: {diagnostic.strip()}" in details
        assert diagnostic.strip() in body
    assert "etf_national_team: etf_daily" in body and "备份=2  本地=1" in body
    assert "跨时点行数减少，待审计核对" in body
    for table in TABLES["stock_daily"] + TABLES["public_fund"]:
        assert any(table in line and "[OK]" in line for line in report.splitlines())


def test_partial_sqlite_connection_failure_closes_open_backup(sandbox):
    live, paths = backup_fixture(sandbox)
    (live / "sentiment.db").unlink()
    opened = track_sqlite_connections(sandbox)
    report = validate(sandbox, live, paths, "")
    assert report.startswith("VERIFY_OK=0\n")
    assert len(opened) == 11 and all(c.was_closed for c in opened)
    rc, body = render_actual_body(sandbox, report)
    assert rc == 1 and "sentiment: ✗ 连接失败" in body
    assert any("fund_basic" in line and "[OK]" in line for line in report.splitlines())


def load_functions(path, names, ns):
    tree = ast.parse(path.read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in nodes} == set(names)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec", flags=16777216), ns)
    return tree


@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("count", [50, 51, 131, 203])
def test_r2_body_only_current_facts_and_same_routing(sandbox, full, count):
    calls, marks, windows = [], [], []
    fake = types.ModuleType("notify")
    fake.check_dedup = lambda key, win: windows.append((key, win)) or False
    fake.send = lambda *a, **kw: calls.append((a, kw)) or {"email": True, "telegram": False, "feishu": False}
    fake.update_dedup = marks.append
    sandbox.mp.setitem(sys.modules, "notify", fake)
    ns = {"sys": types.SimpleNamespace(path=[], stderr=io.StringIO()), "ROOT": sandbox.tmp,
          "full": full, "total_mismatch_found": count, "repaired_total": count - 1}
    path = ROOT / "scripts/upload_r2.py"
    tree = load_functions(path, {"_verify_r2_notification_handled"}, ns)
    verify = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "cmd_verify_r2")
    block = next(n for n in ast.walk(verify) if isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
                 and isinstance(n.test.left, ast.Name) and n.test.left.id == "total_mismatch_found")
    exec(compile(ast.Module(body=[block], type_ignores=[]), str(path), "exec"), ns)
    if count == 50:
        assert calls == [] and marks == [] and windows == []
        return
    assert len(calls) == 1
    (subject, body), kwargs = calls[0]
    assert f"本轮待核查 {count} 个 key" in body and f"成功 {count - 1} 个" in body
    assert ("周日全量对账" if full else "平日增量/抽样对账") in body
    assert "114" not in body and "10-04" not in body and "不可逐字考" not in body
    assert "未按原因拆分" in body and "不能把总数当作已确认缺失数" in body
    assert "覆盖来源待验" in body and "尚不能确认异源覆盖" in body
    assert kwargs == {"from_prefix": "[告警]", "ledger_key": "verify_r2_mass_mismatch"}
    assert windows == [("verify_r2_mass_mismatch", 86400)] and marks == ["verify_r2_mass_mismatch"]
    rules = {}
    load_functions(ROOT / "scripts/alert_denoise_rules.py", {"category_of", "domain_of"}, rules)
    assert rules["category_of"](kwargs["ledger_key"], subject) == "r2"
    assert rules["domain_of"](kwargs["ledger_key"], subject) == "r2_deploy"


@pytest.mark.parametrize("descs", [["verify-r2"], ["unknown-command"]])
def test_unchecked_channel_is_pending_not_confirmed(sandbox, descs):
    out = io.StringIO()
    ns = {"sys": types.SimpleNamespace(exit=sys.exit, stderr=out),
          "os": types.SimpleNamespace(environ={}), "_R2_CHANNELS": []}
    load_functions(ROOT / "scripts/upload_r2.py", {"cmd_verify_channels"}, ns)
    with contextlib.redirect_stdout(out), pytest.raises(SystemExit) as exc:
        ns["cmd_verify_channels"](descs)
    assert exc.value.code == 1
    assert "待验" in out.getvalue() and "未确认缺口" in out.getvalue()


def test_stale_body_uses_actual_objects_and_rounds(sandbox):
    calls = []
    fake = types.ModuleType("notify")
    fake.check_dedup = lambda *a: False
    fake.send = lambda *a, **kw: calls.append((a, kw)) or {"email": True, "telegram": False, "feishu": False}
    fake.update_dedup = lambda *a: None
    sandbox.mp.setitem(sys.modules, "notify", fake)
    objects = ["data/boot.json", "data/hk-1y.json", "data/hk-3m.json", "data/hk-6m.json"]
    ns = {"sys": types.SimpleNamespace(path=[], stderr=io.StringIO()), "ROOT": sandbox.tmp,
          "datetime": __import__("datetime"), "stale_standalone_names": objects,
          "stale_standalone_bytes": 300, "repaired_total": 4,
          "_STALE_ALERT_COUNT_THRESHOLD": 3, "_STALE_ALERT_BYTES_THRESHOLD": 1024 * 1024,
          "_STALE_ALERT_CONSECUTIVE_THRESHOLD": 3,
          "_compute_stale_consecutive_rounds": lambda *a: 16,
          "_fmt_name_list": lambda xs: ", ".join(xs)}
    path = ROOT / "scripts/upload_r2.py"
    tree = load_functions(path, {"_verify_r2_notification_handled"}, ns)
    verify = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "cmd_verify_r2")
    block = next(n for n in ast.walk(verify) if isinstance(n, ast.If) and isinstance(n.test, ast.Name)
                 and n.test.id == "stale_standalone_names")
    exec(compile(ast.Module(body=[block], type_ignores=[]), str(path), "exec"), ns)
    assert len(calls) == 1
    (_, body), kwargs = calls[0]
    assert all(x in body for x in objects) and "连续第 16 轮" in body
    assert "台账实有池" not in body and "a-stock-" not in body and "news_digest 家族" not in body
    assert "原因待核" in body and "不能证明属于设计内无需处置" in body
    assert "连续 16 轮仍需排查" in body and "补传不替代源头修复" in body
    assert kwargs["ledger_key"] == "verify_r2_standalone_stale" and kwargs["from_prefix"] == "[告警]"
