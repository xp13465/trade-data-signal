# -*- coding: utf-8 -*-
"""reviewer 独立复现 #202 P3-a: ast 抽取真 _ESCALATE_CHANNELS 字面量 + 真 adr, 30 组同输入对比。"""
import ast, json, sys, tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, "/Users/linhuichen/code/trade/scripts")
import alert_denoise_rules as adr

AFTER = "/tmp/rev-silence/after/scripts/notify.py"
BEFORE = "/tmp/rev-silence/before/scripts/notify.py"

def extract_chan(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if getattr(t, "id", None) == "_ESCALATE_CHANNELS":
                    return eval(compile(ast.Expression(node.value), "<lit>", "eval"), {"adr": adr})
    raise SystemExit("_ESCALATE_CHANNELS not found in " + path)

chan_before = extract_chan(BEFORE)
chan_after = extract_chan(AFTER)

print("== 1) 结构 ==")
print("before 元组长度:", {k: len(v) for k, v in chan_before.items()})
print("after  元组长度:", {k: len(v) for k, v in chan_after.items()})
assert set(chan_before) == set(chan_after) == {adr.PATROL_DRIFT_DEDUP_KEY, adr.FAILED_UNITS_DEDUP_KEY}

print("== 2) after 各通道天数常量接线 ==")
p = chan_after[adr.PATROL_DRIFT_DEDUP_KEY]
f = chan_after[adr.FAILED_UNITS_DEDUP_KEY]
print("patrol[3] =", p[3], "is PATROL_DRIFT_ESCALATE_DAYS:", p[3] is adr.PATROL_DRIFT_ESCALATE_DAYS)
print("failed[3] =", f[3], "is FAILED_UNITS_ESCALATE_DAYS:", f[3] is adr.FAILED_UNITS_ESCALATE_DAYS)
assert p[3] is adr.PATROL_DRIFT_ESCALATE_DAYS
assert f[3] is adr.FAILED_UNITS_ESCALATE_DAYS
print("两常量现值: PATROL =", adr.PATROL_DRIFT_ESCALATE_DAYS, " FAILED =", adr.FAILED_UNITS_ESCALATE_DAYS)
assert adr.PATROL_DRIFT_ESCALATE_DAYS == 3 and adr.FAILED_UNITS_ESCALATE_DAYS == 3

print("== 3) 调用点证据(改动前/后) ==")
import subprocess
for tag, path in (("before", BEFORE), ("after", AFTER)):
    out = subprocess.run(["grep", "-n", "-A2", "consecutive_days_escalate(", path], capture_output=True, text=True).stdout
    print(f"[{tag}]"); print(out.strip())

print("== 4) 30 组同输入对比(before 语义=两通道都传 FAILED 常量; after 语义=各传各的) ==")
mismatch = 0; total = 0; details = []
now = datetime(2026, 10, 6, 8, 30, 0)
for key, atup in chan_after.items():
    for seed_days in (1, 2, 3, 4, 5):
        for gapmode in ("consecutive", "same_day", "broken"):
            total += 1
            with tempfile.TemporaryDirectory() as td:
                sp_b = Path(td) / "sb.json"; sp_a = Path(td) / "sa.json"
                if gapmode == "consecutive":
                    seed = {"last_fail_date": (now - timedelta(days=1)).strftime("%Y-%m-%d"),
                            "consecutive_days": seed_days,
                            "first_fail_date": (now - timedelta(days=seed_days)).strftime("%Y-%m-%d"),
                            "last_grade_time": ""}
                elif gapmode == "same_day":
                    seed = {"last_fail_date": now.strftime("%Y-%m-%d"), "consecutive_days": seed_days,
                            "first_fail_date": "", "last_grade_time": ""}
                else:
                    seed = {"last_fail_date": (now - timedelta(days=3)).strftime("%Y-%m-%d"),
                            "consecutive_days": seed_days, "first_fail_date": "", "last_grade_time": ""}
                sp_b.write_text(json.dumps(seed), encoding="utf-8")
                sp_a.write_text(json.dumps(seed), encoding="utf-8")
                r_b = adr.consecutive_days_escalate(sp_b, now, adr.FAILED_UNITS_ESCALATE_DAYS)
                r_a = adr.consecutive_days_escalate(sp_a, now, atup[3])
                if r_b != r_a:
                    mismatch += 1
                    details.append((key, seed_days, gapmode, r_b, r_a))
            assert not sp_b.exists() or True  # 临时目录自动清理
print(f"total={total} mismatch={mismatch}")
for d in details:
    print("MISMATCH:", d)
assert mismatch == 0
print("PASS: 30 组逐位一致")
