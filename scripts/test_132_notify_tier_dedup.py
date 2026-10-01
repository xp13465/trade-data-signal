#!/usr/bin/env python3
"""test_132_notify_tier_dedup.py - #132 审 C-1/C-2 回归测试（2026-10-01）。

背景：docs/ops/132-monitor-residuals-review-20261001.md 三个 caveat：
C-1  notify.py main() 的 --tier 分支在通用 check_dedup(L2140) 之前 return 0，
      --dedup-key/--dedup-window 被静默丢弃（假降噪）。既有调用方
      with_lock.py L114 / staticdata_sync.sh L248 / staticdata_backup_async.sh L394
      均显式传 --tier+--dedup-key 组合且语义=期望去重生效，无调用方依赖「--tier 不去重」。
      修复=tier 分支内补通用 dedup 语义（发送前 check_dedup suppress + 发送成功后
      update_dedup 占窗）。不动通用路径 L2157 的 and ok 契约。
C-2  defer_warning 无 dry_run 参数，RETRY_NOTIFY_DRY_RUN=1 时自测会污染真 buffer。
      修复=defer_warning 加 dry_run 最前短路：不写 buffer、不落 dedup 状态、不外发。

验收判据（主控复审指令）：
  ① 同一 dedup key 连续调两次，第二次不入队（buffer 行数前后对比）
  ② 不同 key 仍能各自入队
  ③ dry_run 时不写 buffer、不落 dedup 状态、不外发

跑法：python3 scripts/test_132_notify_tier_dedup.py   （全部 tmp 目录隔离，不碰生产文件）
"""
import json
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).absolute().parent
sys.path.insert(0, str(ROOT))

import notify  # noqa: E402


class TierDedupTests(unittest.TestCase):
    """C-1/C-2 修复回归。走 notify.main(argv) 真实 CLI 路径，文件目标全指临时目录。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="notify_132_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.buf = Path(self.tmp) / "warning_buffer.jsonl"
        self.state = Path(self.tmp) / "warning_dedup_state.json"
        self.lock = Path(self.tmp) / "warning_buffer.flushlock"
        self.dedup_lock = Path(self.tmp) / "warning_dedup.lock"
        self.dedup_file = Path(self.tmp) / "notify_dedup.json"
        self.info_log = Path(self.tmp) / "info_log.jsonl"
        # 读写目标全指临时目录，绝不碰生产 data/alerts/ data/notify_dedup.json
        for attr, val in (("WARNING_BUFFER_FILE", self.buf),
                          ("WARNING_FLUSH_LOCK_FILE", self.lock),
                          ("WARNING_DEDUP_STATE_FILE", self.state),
                          ("WARNING_DEDUP_LOCK_FILE", self.dedup_lock),
                          ("DEDUP_FILE", self.dedup_file),
                          ("INFO_LOG_FILE", self.info_log)):
            setattr(self, f"_orig_{attr}", getattr(notify, attr))
            setattr(notify, attr, val)
            self.addCleanup(lambda a=attr, o=getattr(self, f"_orig_{attr}"):
                            setattr(notify, a, o))

    # ── 工具 ──────────────────────────────────────────────────────
    def _read_buf(self):
        if not self.buf.exists():
            return []
        return [json.loads(ln) for ln in self.buf.read_text(encoding="utf-8").splitlines()
                if ln.strip()]

    def _read_dedup(self):
        if not self.dedup_file.exists():
            return {}
        return json.loads(self.dedup_file.read_text(encoding="utf-8"))

    def _cli(self, subject, body, *extra):
        """走 notify.main(argv) 真实 CLI 路径（tier warning + dedup-key 组合）。"""
        argv = [subject, body, "--tier", notify.TIER_WARNING, "--from-prefix", "[告警]",
                "--dedup-key", "test_132_key", "--dedup-window", "21600"] + list(extra)
        return notify.main(argv)

    # ── C-1：--tier + --dedup-key 组合去重真正生效 ─────────────────
    def test_c1_same_key_second_call_not_enqueued(self):
        """同一 dedup key 连续调两次：第二次不得再入 buffer（验收判据①）。"""
        rc1 = self._cli("132告警源A", "第一次")
        n1 = len(self._read_buf())
        self.assertEqual(rc1, 0)
        self.assertEqual(n1, 1, "第一次应入队 1 条")
        self.assertEqual(self._read_buf()[0]["subject"], "132告警源A")

        rc2 = self._cli("132告警源A", "第二次")  # 同 key（同 subject 同 body）
        n2 = len(self._read_buf())
        self.assertEqual(rc2, 0)
        self.assertEqual(n2, 1, "同 dedup-key 窗口内第二次不得再入队（buffer 行数前后对比）")
        # dedup 状态已写入（占窗）
        self.assertIn("test_132_key", self._read_dedup(), "发送成功应 update_dedup 占窗")

    def test_c1_different_keys_each_enqueue(self):
        """不同 dedup key 各自入队，互不压制（验收判据②）。"""
        self._cli("132告警源A", "bodyA")
        self.assertEqual(len(self._read_buf()), 1)
        argv = ["132告警源B", "bodyB", "--tier", notify.TIER_WARNING,
                "--from-prefix", "[告警]", "--dedup-key", "test_132_key_B",
                "--dedup-window", "21600"]
        notify.main(argv)
        entries = self._read_buf()
        self.assertEqual(len(entries), 2, "不同 key 应各自入队")
        self.assertEqual({e["subject"] for e in entries},
                         {"132告警源A", "132告警源B"})

    def test_c1_dry_run_no_dedup_check_no_state(self):
        """dry-run 不走去重（需看到发送日志）也不占窗：不写 dedup 状态。"""
        rc = self._cli("132告警源A", "第一次", "--dry-run")
        self.assertEqual(rc, 0)
        self.assertEqual(self._read_dedup(), {}, "dry-run 不得 update_dedup 占窗")
        # dry-run 走 defer_warning(dry_run=True) 短路 → 不写 buffer
        self.assertEqual(len(self._read_buf()), 0, "dry-run 不得写 buffer")

    # ── C-2：defer_warning dry_run 最前短路，不碰任何状态 ──────────
    def test_c2_dry_run_no_buffer_no_state(self):
        """dry-run：不写 buffer、不落 dedup 状态（验收判据③）。"""
        n0 = len(self._read_buf())
        rc = notify.defer_warning("132 dryrun 源", "payload", dry_run=True)
        self.assertTrue(rc, "dry-run 返回 True（保持恒 True 语义）")
        self.assertEqual(len(self._read_buf()), n0, "dry-run 不得写 buffer")
        self.assertFalse(self.state.exists(), "dry-run 不得落 dedup 状态文件")

    def test_c2_dry_run_via_cli_no_buffer(self):
        """CLI 层验证：--tier warning --dry-run 不写 buffer（原 bug 会污染真 buffer）。"""
        self._cli("132 dryrun cli 源", "payload", "--dry-run")
        self.assertEqual(len(self._read_buf()), 0,
                         "CLI dry-run 不得写 buffer（修复前 RETRY_NOTIFY_DRY_RUN 会污染）")
        self.assertFalse(self.state.exists(), "CLI dry-run 不得落 dedup 状态文件")

    def test_c2_send_tiered_passes_dry_run(self):
        """send_tiered 透传 dry_run 给 defer_warning：dry-run 不写 buffer。"""
        n0 = len(self._read_buf())
        res = notify.send_tiered("132 源", "payload", tier=notify.TIER_WARNING,
                                 dry_run=True)
        self.assertEqual(res.get("deferred"), True)
        self.assertEqual(len(self._read_buf()), n0, "send_tiered dry-run 不得写 buffer")
        self.assertFalse(self.state.exists())

    # ── 举一反三：复刻既有调用方参数组合（C-1 影响面）──────────────
    def test_repro_with_lock_params_dry_run_no_buffer(self):
        """with_lock.py L114 参数组合（--tier warning + dedup-key + WITH_LOCK_NOTIFY_DRY_RUN）：
        dry-run 不再写 buffer（修复前 RETRY_NOTIFY_DRY_RUN 同款污染问题会命中 with_lock）。"""
        argv = ["排队超时跳过 /tmp/trade_deploy.lock", "with_lock 排队等锁超时 body",
                "--tier", notify.TIER_WARNING, "--from-prefix", "[告警]",
                "--dedup-key", "with_lock_block_timeout:/tmp/trade_deploy.lock",
                "--dedup-window", "21600", "--dry-run"]
        rc = notify.main(argv)
        self.assertEqual(rc, 0)
        self.assertEqual(len(self._read_buf()), 0,
                         "with_lock 参数组合 dry-run 不得写 buffer（C-2 覆盖既有调用方）")
        self.assertFalse(self.state.exists())

    def test_repro_staticdata_info_params_dedup(self):
        """staticdata_sync.sh L248 参数组合（--tier info + dedup-key staticdata_sync_oversize_skip）：
        C-1 修复后 dedup 真正生效——第二次同 key 不重复记 info（修复前每次调用都记 dashboard）。"""
        argv = ["[告警] staticdata 同步变更量超阈值跳过 commit", "oversize body",
                "--tier", notify.TIER_INFO, "--from-prefix", "[告警]",
                "--dedup-key", "staticdata_sync_oversize_skip", "--dedup-window", "21600"]
        rc1 = notify.main(argv)
        self.assertEqual(rc1, 0)
        self.assertTrue(self.info_log.exists(), "第一次应记 info dashboard")
        rc2 = notify.main(argv)
        self.assertEqual(rc2, 0)
        n_lines = len(self.info_log.read_text(encoding="utf-8").splitlines())
        self.assertEqual(n_lines, 1, "同 dedup-key 第二次不得重复记 info（占窗生效）")
        self.assertIn("staticdata_sync_oversize_skip", self._read_dedup())


if __name__ == "__main__":
    unittest.main(verbosity=2)
