"""Portable stdlib CLI checks. Run directly to avoid repository conftest side effects.

Every CLI child loads a temporary audit guard, positively tested before any view
execution. Inputs, HOME, REPO and all writable locations are temporary; no notify,
collector, upload or backtest module is imported. No production evidence implied.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).absolute().parents[1] / "alert_noise_count.py"
DAY = "2026-11-06"
GUARD = '''import os, sys
def guard(event, args):
    denied = (event.startswith("socket.") or event in {
        "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn",
        "urllib.Request", "http.client.connect", "smtplib.connect"})
    if event == "open" and isinstance(args[0], (str, bytes)):
        path = os.path.abspath(os.fsdecode(args[0]))
        mode, flags = args[1], args[2]
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT))
        denied = denied or os.path.basename(path) == ".env" or (
            writing and os.path.commonpath([path, os.environ["TEST_SANDBOX"]]) != os.environ["TEST_SANDBOX"])
    if denied:
        print("EGRESS_TRAP:" + event, file=sys.stderr)
        raise SystemExit(97)
sys.addaudithook(guard)
'''


def row(group="alert", subject="[告警] unit 异常", tier="warning", **extra):
    value = {"ts": DAY + " 10:00:00", "tree": "/fixture/run", "group": group,
             "tier": tier, "subject": subject, "key": "same-key",
             "source": "notify.py", "channels": {"email": True, "feishu": True}}
    value.update(extra)
    return value


class AllGroupsCLI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="codex-allgroups-")
        cls.root = Path(cls.temp.name).resolve()
        (cls.root / "sitecustomize.py").write_text(GUARD, encoding="utf-8")
        cls.env = {"PATH": os.environ.get("PATH", ""), "HOME": str(cls.root),
                   "TMPDIR": str(cls.root), "REPO": str(cls.root / "repo"),
                   "PYTHONPATH": str(cls.root), "PYTHONDONTWRITEBYTECODE": "1",
                   "TEST_SANDBOX": str(cls.root), "LC_ALL": "C", "TZ": "UTC"}
        # Must precede the first real CLI run. The trap prevents these operations
        # before any DNS/socket/process/shell/env-file access occurs.
        for code, event in [
            ("import socket; socket.socket()", "socket.__new__"),
            ("import socket; socket.getaddrinfo('invalid.example',443)", "socket.getaddrinfo"),
            ("import subprocess; subprocess.run(['forbidden-positive-control'])", "subprocess.Popen"),
            ("import os; os.system('forbidden-positive-control')", "os.system"),
            ("open('/forbidden/.env')", "open"),
            ("open('/forbidden/output', 'w')", "open"),
        ]:
            result = cls.child(["-c", code])
            if result.returncode != 97 or "EGRESS_TRAP:" + event not in result.stderr:
                raise AssertionError(f"guard positive control failed: {event}: {result}")
        print("EGRESS_POSITIVE_CONTROL: 6/6 blocked before CLI", flush=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def child(cls, args):
        return subprocess.run([sys.executable, "-B", *args], cwd=cls.root,
                              env=cls.env, capture_output=True, text=True, timeout=10)

    def ledger(self, rows, name="ledger.jsonl", tail=""):
        path = self.root / name
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows) + tail,
                        encoding="utf-8")
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def cli(self, path, *args, all_groups=True, as_json=True):
        result = self.child([str(SCRIPT), "--date", DAY, "--ledger", str(path),
                             *(["--all-groups"] if all_groups else []),
                             *(["--json"] if as_json else []), *args])
        self.assertNotIn("EGRESS_TRAP:", result.stderr)
        self.assertIn(result.returncode, (0, 1, 2), result.stderr)
        return result, json.loads(result.stdout) if as_json else result.stdout

    def test_legacy_default_schema_and_three_exit_codes(self):
        keys = {"date", "date_range", "ledger", "ledger_exists", "no_data", "noise_max",
                "days", "totals", "repeat_caveat", "warn_untagged", "skipped_bad_lines",
                "skipped_undated_alert_rows", "records_scanned", "diverted", "rc"}
        for count, expected in ((1, 0), (4, 1), (0, 2)):
            path = self.ledger([row(subject="[告警·摘要] 例", tier="digest") for _ in range(count)])
            result, payload = self.cli(path, all_groups=False)
            self.assertEqual(result.returncode, expected)
            self.assertEqual(set(payload), keys)
            self.assertEqual(payload["noise_max"], 3)
            self.assertEqual(payload["totals"]["noise"], count)
            self.assertEqual(payload["totals"]["pass"], None if not count else count <= 3)
            result, text = self.cli(path, all_groups=False, as_json=False)
            self.assertEqual(result.returncode, expected)
            self.assertIn("pass=null" if not count else "PASS" if expected == 0 else "FAIL", text)

    def test_operations_and_business_across_all_four_groups(self):
        rows = []
        for group in ("alert", "report", "follow", "agent_done"):
            rows.extend([
                row(group),
                row(group, "[72h恢复] unit 恢复", "notice"),
                row(group, "[告警·摘要] 并入 9 条", "digest", merged_count=9),
                row(group, "[告警·聚合] 2 条", "notice", noise_class="warning_batch", merged_count=2),
                row(group, "[告警] 【持续故障升级】unit", "critical"),
                row(group, "[买卖点信号] 市场风险恢复", "notice"),
                row(group, "[完成] review [告警] 分类", "agent_done"),
            ])
        result, p = self.cli(self.ledger(rows))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(p["data_status"], "observed")
        self.assertIsNone(p["current_unresolved_incidents"])
        self.assertNotIn("pass", p)
        for g in ("alert", "report", "follow", "agent_done"):
            b = p["groups"][g]
            self.assertEqual((b["ledger_rows"], b["business_rows"], b["unknown_rows"]), (7, 2, 0))
            self.assertEqual(b["operations"]["feishu_sent"], 5)
            self.assertEqual(b["operations"]["declared_merged_slots"], 11)
            for kind in ("recovery", "digest", "warning_batch", "escalation"):
                self.assertEqual(b["by_kind"][kind]["rows"], 1)
        self.assertTrue(p["groups"]["unknown"]["no_data"])

    def test_delivery_false_missing_and_merged_not_incidents(self):
        rows = [row("report", "[告警·摘要] 历史合并", "digest", merged_count=7,
                    channels={"email": True, "feishu": False}),
                row("report", "[恢复] 历史恢复", "notice", channels={}),
                row("report", merged_count=-1), row("report", merged_count="3"),
                row("report", merged_count=True), row("report", channels={"feishu": "false"}),
                row("report", channels=None), row("report", merged_count=0)]
        result, p = self.cli(self.ledger(rows))
        self.assertEqual(result.returncode, 2)
        b = p["groups"]["report"]["operations"]
        self.assertEqual((b["rows"], b["feishu_sent"], b["feishu_not_successful"], b["feishu_unknown"]), (8, 4, 1, 3))
        self.assertEqual(b["declared_merged_slots"], 7)
        self.assertEqual(b["merged_count_invalid_rows"], 3)
        self.assertEqual(b["merged_count_missing_rows"], 3)
        self.assertIsNone(p["current_unresolved_incidents"])

    def test_cross_day_unknown_bad_and_undated_are_visible(self):
        rows = [row(ts="2026-11-05 23:59:59"), row(ts=DAY + " 00:00:00"),
                row(ts="2026-11-04 10:00:00"), row(ts="bad timestamp"),
                row("follow", "new topic", "notice"), row(noise_class="future_label"),
                row(group=None), row("report", subject=""), row("alert", subject=None),
                row("agent_done", tier="future_tier")]
        result, p = self.cli(self.ledger(rows, tail='not-json\n[]\n'), "--days", "2")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(p["date_range"], ["2026-11-05", DAY])
        self.assertEqual(p["coverage"]["skipped_bad_lines"], 2)
        self.assertEqual(p["coverage"]["undated_rows"], 1)
        self.assertEqual(p["coverage"]["outside_window_rows"], 1)
        self.assertEqual(p["days"][0]["groups"]["alert"]["ledger_rows"], 1)
        self.assertEqual(p["groups"]["unknown"]["operations"]["rows"], 1)
        self.assertEqual(p["groups"]["alert"]["unknown_rows"], 2)
        reasons = {r for item in p["uncertainties"] for r in item["reasons"]}
        self.assertTrue({"unknown_noise_class", "missing_or_invalid_subject",
                         "unknown_or_missing_group", "unknown_or_missing_tier"} <= reasons)
        self.assertTrue(all(item["line"] >= 1 for item in p["uncertainties"]))

    def test_missing_empty_outside_and_partial_ledger_coverage(self):
        missing = self.root / "not-there.jsonl"
        for path in (missing, self.ledger([], "empty.jsonl"),
                     self.ledger([row(ts="2026-01-01")], "outside.jsonl")):
            result, p = self.cli(path)
            self.assertEqual(result.returncode, 2)
            self.assertTrue(p["no_data"])
            self.assertEqual(p["data_status"], "no_data")
        result, p = self.cli(self.ledger([row()]), "--extra-ledger", str(missing))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(p["data_status"], "partial")
        self.assertFalse(p["coverage"]["all_trees_verified"])
        self.assertEqual([i["status"] for i in p["coverage"]["ledgers"]], ["read", "missing"])

    def test_missing_timestamp_and_channels_preserve_unknown(self):
        no_ts = row()
        del no_ts["ts"]
        no_channels = row("follow")
        del no_channels["channels"]
        result, p = self.cli(self.ledger([no_ts, no_channels]))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(p["coverage"]["undated_rows"], 1)
        self.assertEqual(p["groups"]["alert"]["ledger_rows"], 0)
        self.assertTrue(p["groups"]["alert"]["no_data"])
        self.assertEqual(p["groups"]["follow"]["operations"]["feishu_unknown"], 1)
        self.assertEqual(p["data_status"], "partial")

    def test_malformed_field_types_do_not_crash_or_become_healthy(self):
        path = self.ledger([row(tier=["warning"], channels=[]),
                            row(tier={"new": "tier"}, group=["report"]),
                            row(subject=42, noise_class={"new": "tag"})])
        result, p = self.cli(path)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(p["data_status"], "partial")
        self.assertEqual(len(p["uncertainties"]), 3)

    def test_unreadable_ledger_is_partial_without_discarding_other_file(self):
        result, p = self.cli(self.ledger([row()]), "--extra-ledger", str(self.root))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(p["data_status"], "partial")
        self.assertEqual(p["coverage"]["ledgers"][1]["status"], "unreadable")
        self.assertEqual(p["groups"]["alert"]["operations"]["rows"], 1)

    def test_physical_file_dedup_not_cross_tree_message_dedup(self):
        first = self.ledger([row()], "tree-a.jsonl")
        second = self.ledger([row()], "tree-b.jsonl")
        symlink = self.root / "symlink.jsonl"
        hardlink = self.root / "hardlink.jsonl"
        symlink.symlink_to(first)
        os.link(first, hardlink)
        self.addCleanup(symlink.unlink)
        self.addCleanup(hardlink.unlink)
        result, p = self.cli(first, "--extra-ledger", str(symlink), "--extra-ledger", str(hardlink),
                             "--extra-ledger", str(first), "--extra-ledger", str(second))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(p["coverage"]["records_scanned"], 2)
        self.assertEqual(p["groups"]["alert"]["operations"]["rows"], 2)
        self.assertEqual(sum(i["status"] == "duplicate_physical_file" for i in p["coverage"]["ledgers"]), 3)

    def test_sources_and_development_forward_are_not_faults(self):
        path = self.ledger([
            row("report", "巡检结果", "notice", source="/fixture/check_failed_units.py"),
            row("report", "[状态说明] 监控结论异常", "notice"),
            row("agent_done", "[codex] turn 完成 [告警] 修复", "notice", source="codex_notify_bridge.py"),
            row("follow", "行情报告", "subscribe"),
            row("report", "市场情绪", "notice", source="daily_summary_email.py"),
            row("agent_done", "[完成] review", "critical"),
        ])
        result, p = self.cli(path)
        self.assertEqual(result.returncode, 2)  # conflicting metadata remains unknown
        self.assertEqual(p["groups"]["report"]["operations"]["rows"], 2)
        self.assertEqual(p["groups"]["agent_done"]["business_rows"], 1)
        self.assertEqual(p["groups"]["agent_done"]["unknown_rows"], 1)
        self.assertEqual(p["groups"]["report"]["business_rows"], 1)

    def test_text_view_lists_zero_categories_and_uncertainties(self):
        path = self.ledger([row("follow"), row("report", "unknown", "notice")])
        result, text = self.cli(path, as_json=False)
        self.assertEqual(result.returncode, 2)
        for label in ("recovery", "digest", "warning_batch", "escalation", "声明 merged 槽位",
                      "unknown", "不推断当前未恢复故障", str(path)):
            self.assertIn(label, text)
        self.assertIn("无台账数据", text)

    def test_default_repo_path_and_extra_requires_flag(self):
        path = self.root / "repo" / "data" / "alerts" / "alert_ledger.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row()) + "\n", encoding="utf-8")
        self.addCleanup(path.unlink)
        result = self.child([str(SCRIPT), "--date", DAY, "--all-groups", "--json"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["coverage"]["ledgers"][0]["path"], str(path))
        result = self.child([str(SCRIPT), "--date", DAY, "--extra-ledger", str(path)])
        self.assertEqual(result.returncode, 2)
        self.assertIn("--extra-ledger", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
