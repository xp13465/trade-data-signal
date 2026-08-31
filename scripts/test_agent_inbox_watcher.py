#!/usr/bin/env python3
"""agent_inbox_watcher 单元测试(2026-08-31 重写对齐当前实现)。

历史注记: 本文件 8-28 归档版(5b68ad1a7)测的是当时磁盘上未提交演进版 watcher
的接口(REPORTS_DIR/CLAUDE_ACTIONS_DIR/codex_report_is_valid/claude_receipt_is_valid/
claude 通道命令=claude-inbox-consumer.sh), 这些接口在 git 任何版本均不存在,
旧测试在当前实现上 setUp 即 AttributeError。现对齐当前实现重写:
build_command 形状断言 + report_is_fresh 报告有效性机检逐分支
(2026-08-31 codex ref 断点修复, 详见 agent_inbox_watcher.py 模块 docstring)。

运行: cd <repo> && python3 -m unittest scripts.test_agent_inbox_watcher -v
(或 python3 scripts/test_agent_inbox_watcher.py, 需 scripts/ 在 sys.path)
"""

import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent_inbox_watcher as watcher


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone().isoformat()


class AgentInboxWatcherTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.signals = self.root / "signals"
        self.signals.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def write_report(self, request_id: str, mtime: float | None = None) -> Path:
        report = self.root / f"{request_id}.json"
        report.write_text(json.dumps({
            "request_id": request_id,
            "verdict": "PASS",
            "summary": "ok",
            "issues": [],
            "impact_surface": [],
            "smoke_results": {},
            "recommendation": "none",
        }), encoding="utf-8")
        if mtime is not None:
            os.utime(report, (mtime, mtime))
        return report

    def write_signal(self, request_id: str, payload: dict,
                     mtime: float | None = None) -> Path:
        signal = self.signals / f"{request_id}.ready"
        signal.write_text(json.dumps(payload), encoding="utf-8")
        if mtime is not None:
            os.utime(signal, (mtime, mtime))
        return signal

    # ---- build_command 形状(消费链现状) ----

    def test_codex_dispatch_uses_codex_exec(self):
        command = watcher.build_command("codex", "test-001")
        self.assertIn("exec", command)
        self.assertTrue(command[0].endswith("codex"))

    def test_claude_dispatch_uses_report_validator(self):
        command = watcher.build_command("claude", "test-001")
        self.assertEqual(
            command[:3],
            ["bash", str(watcher.REPO / "scripts" / "codex-review-report.sh"),
             "test-001"],
        )

    # ---- report_is_fresh 报告有效性机检(逐分支) ----

    def test_fresh_report_after_signaled_at_passes(self):
        # 报告晚于信号创建(complete.py 写信号后 touch 的正常回传)→ 放行
        now = time.time()
        report = self.write_report("t-001", mtime=now + 5)
        payload = {"request_id": "t-001", "report_path": str(report),
                   "signaled_at": iso(now)}
        signal = self.write_signal("t-001", payload)
        valid, error = watcher.report_is_fresh(payload, signal)
        self.assertTrue(valid, error)

    def test_stale_report_earlier_than_signal_rejected(self):
        # 报告明显早于信号创建(旧残留: 信号重发但报告未重写)→ 拦, 文案含 stale report
        now = time.time()
        report = self.write_report("t-002", mtime=now - 3600)
        payload = {"request_id": "t-002", "report_path": str(report),
                   "signaled_at": iso(now)}
        signal = self.write_signal("t-002", payload)
        valid, error = watcher.report_is_fresh(payload, signal)
        self.assertFalse(valid)
        self.assertIn("stale report", error)

    def test_missing_signaled_at_falls_back_to_signal_mtime(self):
        # 无 signaled_at 字段 → 回退信号文件自身 mtime 作基准(两种方向)
        now = time.time()
        stale = self.write_report("t-003", mtime=now - 3600)
        signal = self.write_signal(
            "t-003", {"request_id": "t-003", "report_path": str(stale)}, mtime=now)
        valid, error = watcher.report_is_fresh(
            {"request_id": "t-003", "report_path": str(stale)}, signal)
        self.assertFalse(valid)
        self.assertIn("stale report", error)

        fresh = self.write_report("t-004", mtime=now + 10)
        signal2 = self.write_signal(
            "t-004", {"request_id": "t-004", "report_path": str(fresh)}, mtime=now)
        valid, error = watcher.report_is_fresh(
            {"request_id": "t-004", "report_path": str(fresh)}, signal2)
        self.assertTrue(valid, error)

    def test_unparseable_signaled_at_falls_back_to_signal_mtime(self):
        # signaled_at 非法串 → 回退信号文件 mtime, 不抛异常
        now = time.time()
        report = self.write_report("t-005", mtime=now + 10)
        payload = {"request_id": "t-005", "report_path": str(report),
                   "signaled_at": "not-a-time"}
        signal = self.write_signal("t-005", payload, mtime=now)
        valid, error = watcher.report_is_fresh(payload, signal)
        self.assertTrue(valid, error)

    def test_tolerance_allows_millisecond_race(self):
        # 报告略早于 signaled_at 但在容差(60s)内 → 放行(mtime 粒度/竞态防误拦)
        now = time.time()
        report = self.write_report("t-006", mtime=now - 30)
        payload = {"request_id": "t-006", "report_path": str(report),
                   "signaled_at": iso(now)}
        signal = self.write_signal("t-006", payload)
        valid, error = watcher.report_is_fresh(payload, signal)
        self.assertTrue(valid, error)

    def test_signal_without_report_path_passes(self):
        # codex 通道信号(无 report_path, 报告由作业期间自写)→ 不适用, 放行
        payload = {"request_id": "t-007"}
        signal = self.write_signal("t-007", payload)
        valid, error = watcher.report_is_fresh(payload, signal)
        self.assertTrue(valid, error)

    def test_missing_report_rejected(self):
        # 报告文件缺失 → 拦, 文案含 report missing
        now = time.time()
        payload = {"request_id": "t-008",
                   "report_path": str(self.root / "ghost.json"),
                   "signaled_at": iso(now)}
        signal = self.write_signal("t-008", payload)
        valid, error = watcher.report_is_fresh(payload, signal)
        self.assertFalse(valid)
        self.assertIn("report missing", error)


if __name__ == "__main__":
    unittest.main()
