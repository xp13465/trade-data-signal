# -*- coding: utf-8 -*-
"""#309 测试共用: 从 schedule_monitor.sh 的 python heredoc **ast 提取**结论判定函数。

为什么提取而不是复制: 结论行/告警判定是生产逻辑, 测试里再写一份必然静默漂移
(memory repro-script-second-implementation-drift)。提取后 E3(结论真假)、E4(重放)、
E6(误报抽样) 共用同一份生产实现。

只提取纯函数与常量, 不执行 heredoc 的其它语句, 因此不会跑任何业务脚本 / notify。
依赖注入: `datetime` 用标准库类(生产里 `from datetime import datetime`)、`ut` 用
`unit_truth` 模块(timer_health 是纯函数, 不启 systemctl)。
"""
from __future__ import annotations

import ast
import datetime
import functools
import hashlib
import re
import sys
from pathlib import Path

import unit_truth as ut
from notify_sent import notify_sent

ROOT = Path(__file__).absolute().parent.parent.parent
MONITOR = ROOT / "scripts" / "schedule_monitor.sh"

WANT_ASSIGN = {"COVERAGE_BUSINESS_TOTAL", "COVERAGE_SELF_MONITOR", "LOG_CALIBER_COVERAGE",
               "STATS_FRESH_WINDOW", "RECOVERY_COOLDOWN",
               "CONCLUSION_STATUS_KEY_PREFIX", "CONCLUSION_STATUS_SUBJECT_PREFIX"}
WANT_FUNC = {
    "_unit_short_name", "_fmt_time_part", "_fmt_span", "_stat_exit_code", "_unit_channel_owns_row",
    "_migrate_unit_owned_keys",
    "_truth_source", "_row_failure_ts", "_stats_failure_fresh", "_stats_failure_alertable",
    "_unit_channel_will_register", "_stats_failure_covered",
    "_failed_stats", "_failure_name", "_failure_detail", "_coverage_text",
    "_cfu_failed_units", "_build_conclusion", "_unit_alert_events",
    "_conclusion_is_ok", "_conclusion_digest", "_conclusion_recurrence_ok",
    "_conclusion_status_decision", "_conclusion_status_mark_recovered",
    "_conclusion_status_email_body", "_maybe_send_conclusion_status_email",
}


def heredoc_source() -> str:
    lines = MONITOR.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next(i for i, l in enumerate(lines) if "<<'PYEOF'" in l)
    end = next(i for i, l in enumerate(lines) if i > start and l.strip() == "PYEOF")
    return "".join(lines[start + 1:end])


@functools.lru_cache(maxsize=1)
def namespace() -> dict:
    src = heredoc_source()
    tree = ast.parse(src)
    picked, found = [], set()
    for node in tree.body:
        name = None
        if isinstance(node, ast.FunctionDef) and node.name in WANT_FUNC:
            name = node.name
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id in WANT_ASSIGN:
                    name = tgt.id
        if name:
            picked.append(ast.get_source_segment(src, node) + "\n")
            found.add(name)
    missing = (WANT_ASSIGN | WANT_FUNC) - found
    assert not missing, (
        f"schedule_monitor.sh 里未找到 {sorted(missing)}: 被重命名/删除了? 本测试锚点需同步"
    )
    ns = {"datetime": datetime.datetime, "timedelta": datetime.timedelta, "ut": ut, "re": re,
          "hashlib": hashlib, "sys": sys, "notify_sent": notify_sent,
          "REPO": ROOT, "MONITOR_LOG": Path("/tmp/schedule_monitor_launchd.log")}
    exec(compile("\n".join(picked), "<monitor-conclusion>", "exec"), ns)  # noqa: S102
    return ns


def conclusion():
    return namespace()["_build_conclusion"]


def unit_alert_events():
    return namespace()["_unit_alert_events"]


def maybe_send_conclusion_status_email():
    return namespace()["_maybe_send_conclusion_status_email"]