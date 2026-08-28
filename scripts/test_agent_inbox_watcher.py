#!/usr/bin/env python3

import json
import tempfile
import time
import unittest
from pathlib import Path

import agent_inbox_watcher as watcher


class AgentInboxWatcherTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        watcher.REPORTS_DIR = self.root / "reports"
        watcher.CLAUDE_ACTIONS_DIR = self.root / "reports" / "claude-actions"
        watcher.REPORTS_DIR.mkdir()
        watcher.CLAUDE_ACTIONS_DIR.mkdir(parents=True)
        self.started = time.time()
        self.report = {
            "request_id": "test-001",
            "verdict": "FAIL",
            "summary": "two actionable findings",
            "issues": [
                {"severity": "high", "file": "app.js"},
                {"severity": "medium", "file": "lab.js"},
            ],
            "impact_surface": [],
            "smoke_results": {},
            "recommendation": "fix before merge",
        }
        self.write_json(watcher.REPORTS_DIR / "test-001.json", self.report)

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def write_json(path: Path, payload: dict):
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(path)

    def receipt(self, **overrides):
        payload = {
            "request_id": "test-001",
            "status": "completed",
            "summary": "verified and fixed",
            "report_verdict": "FAIL",
            "actions": [
                {"decision": "fixed", "detail": "high issue fixed"},
                {"decision": "scheduled", "detail": "medium issue scheduled"},
            ],
            "changed_files": ["app.js"],
            "verification": {"commands": ["node --check app.js"], "results": "PASS"},
            "worktree_path": "/tmp/worktrees/agent-inbox-test-001",
        }
        payload.update(overrides)
        return payload

    def test_codex_dispatch_is_pinned_to_one_request(self):
        command = watcher.build_command("codex", "test-001")
        joined = " ".join(command)
        self.assertIn("request_id=test-001", joined)
        self.assertIn("refs/codex/req/test-001", joined)
        self.assertNotIn("所有 pending", joined)

    def test_claude_dispatch_uses_fixed_consumer(self):
        command = watcher.build_command("claude", "test-001")
        self.assertEqual(command[:3], ["bash", str(watcher.REPO / "scripts" / "claude-inbox-consumer.sh"), "test-001"])

    def test_codex_report_validation_accepts_fresh_schema(self):
        valid, error = watcher.codex_report_is_valid("test-001", self.started - 1)
        self.assertTrue(valid, error)

    def test_codex_report_validation_rejects_stale_report(self):
        valid, error = watcher.codex_report_is_valid("test-001", self.started + 1)
        self.assertFalse(valid)
        self.assertIn("stale report", error)

    def test_claude_receipt_validation_accepts_complete_receipt(self):
        self.write_json(watcher.CLAUDE_ACTIONS_DIR / "test-001.json", self.receipt())
        valid, error = watcher.claude_receipt_is_valid("test-001", self.started - 1)
        self.assertTrue(valid, error)

    def test_claude_receipt_requires_action_coverage(self):
        payload = self.receipt(actions=[{"decision": "fixed", "detail": "only one"}])
        self.write_json(watcher.CLAUDE_ACTIONS_DIR / "test-001.json", payload)
        valid, error = watcher.claude_receipt_is_valid("test-001", self.started - 1)
        self.assertFalse(valid)
        self.assertIn("actions do not cover", error)

    def test_claude_receipt_rejects_foreign_worktree(self):
        payload = self.receipt(worktree_path="/tmp/not-isolated")
        self.write_json(watcher.CLAUDE_ACTIONS_DIR / "test-001.json", payload)
        valid, error = watcher.claude_receipt_is_valid("test-001", self.started - 1)
        self.assertFalse(valid)
        self.assertIn("worktree_path", error)


if __name__ == "__main__":
    unittest.main()
