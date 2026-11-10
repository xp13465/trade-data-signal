#!/usr/bin/env python3
"""固定41c源码的三个缺陷反例；仅抽取允许函数，所有写入都在/tmp。"""
from __future__ import annotations

import ast
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from zoneinfo import ZoneInfo

BASE = "41c567e6aabbfec13af0d310bcc08df59194fdbf"


def source(repo, path):
    return subprocess.check_output(["git", "-C", str(repo), "show", f"{BASE}:{path}"],
                                   timeout=10).decode("utf-8")


def functions(text, names, constants=()):
    nodes = []
    for node in ast.parse(text).body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in constants for t in node.targets):
            nodes.append(node)
    assert {n.name for n in nodes if isinstance(n, ast.FunctionDef)} == set(names)
    return compile(ast.Module(body=nodes, type_ignores=[]), "<fixed-41c-allowed-functions>", "exec")


def main():
    repo = Path(__file__).absolute().parents[3]
    pre = source(repo, "scripts/check_preupload_backup.py")
    notify = source(repo, "scripts/notify.py")
    fixture = source(repo, "scripts/tests/test_f03r1_digest_atomic_write.py")
    assert hashlib.sha256(notify.encode()).hexdigest() == "c356ee9fb3f21ce053b895717797c9083b46e98264a1f2f0c73334d50037acf5"
    assert hashlib.sha256(fixture.encode()).hexdigest() == "2bd0e7b9e9b191457a4de53193614692a356e186970ad89a693106c825f53aca"
    sandbox = next(n for n in ast.parse(fixture).body
                   if isinstance(n, ast.FunctionDef) and n.name == "sandbox")
    patches = {n.args[1].value for n in ast.walk(sandbox) if isinstance(n, ast.Call)
               and isinstance(n.func, ast.Attribute) and n.func.attr == "setattr"
               and len(n.args) > 1 and isinstance(n.args[1], ast.Constant)}
    assert "ALERTS_DIR" in patches and "ALERTS_FILE" not in patches
    # 源函数用本地时区判断mtime，显式固定北京时区，使跨机器复现同一日界限。
    os.environ["TZ"] = "Asia/Shanghai"
    import time
    if hasattr(time, "tzset"):
        time.tzset()
    ns = {"Path": Path, "datetime": datetime, "re": re}
    exec(functions(pre, {"scan_today_logs", "parse_log_lines", "judge"},
                   {"_TAIL_BYTES", "_RE_DONE", "_RE_PROG"}), ns)
    with tempfile.TemporaryDirectory(prefix="alert-takeover-repro-", dir="/tmp") as tmp:
        root = Path(tmp)
        logs = root / "logs"
        logs.mkdir()
        log = logs / "upload.log"
        log.write_text("=== u 开始 2026-11-01 20:00:00 ===\n"
                       "备份完成 copied=0 skipped=0 failed=1\n"
                       "=== u 开始 2026-11-09 20:00:00 ===\n"
                       "备份完成 copied=12 skipped=0 failed=0\n")
        stamp = datetime.datetime(2026, 11, 9, 20, 1, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
        os.utime(log, (stamp, stamp))
        stat1 = ns["parse_log_lines"](ns["scan_today_logs"](logs, "20261109"))
        actual1 = ns["judge"](12, stat1)[1]
        assert (stat1["runs"], stat1["copied"], stat1["failed"], actual1) == (2, 12, 1, "FAIL")
        stat2 = ns["parse_log_lines"](["备份完成 copied=318 skipped=0 failed=1",
                                       "备份完成 copied=0 skipped=0 failed=-1"])
        actual2 = ns["judge"](318, stat2)[1]
        assert (stat2["runs"], stat2["failed"], actual2) == (2, 0, "OK")
        simulated = root / "simulated-live"
        simulated.mkdir()
        target = simulated / "latest.md"
        target.write_text("original-synthetic-content")
        isolated = root / "sandbox"
        isolated.mkdir()
        mirror_ns = {"os": os, "ALERTS_DIR": isolated, "ALERTS_FILE": target}
        exec(functions(notify, {"_replace_latest", "_chmod_like_target"}), mirror_ns)
        mirror_ns["_replace_latest"]("synthetic-test-entry")
        assert target.read_text() == "synthetic-test-entry"
        assert not (isolated / "latest.md").exists()
        result = {
            "source_head": BASE,
            "PREUPLOAD-DATE-01": {"observed": stat1, "judge": actual1,
                                  "expected_after_fix": "Nov9新失败0；Nov1旧失败单独保留"},
            "PREUPLOAD-SENTINEL-02": {"observed": stat2, "judge": actual2,
                                      "expected_after_fix": "FAIL/unknown，不能抵消为OK"},
            "TEST-MIRROR-03": {"fixture_missing": "ALERTS_FILE",
                               "simulated_live_replaced": True, "sandbox_latest_exists": False,
                               "expected_after_fix": "沙箱外目标不变，所有派生路径留沙箱"},
            "safety": "未导入业务模块/运行fixture或套件/访问网络/数据库/通知器；全部写入/tmp",
            "meaning": "退出0=三个固定旧源码缺陷均复现，不代表修复验收通过",
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
