#!/usr/bin/env python3
"""test_132_notify_tier_dedup.py - #132 审 C-1/C-2 + 复审2 P0/P1 回归测试（2026-10-01）。

第一轮背景：docs/ops/132-monitor-residuals-review-20261001.md 三个 caveat：
C-1  notify.py main() 的 --tier 分支在通用 check_dedup(L2140) 之前 return 0，
      --dedup-key/--dedup-window 被静默丢弃（假降噪）。既有调用方
      with_lock.py L114 / staticdata_sync.sh L248 / staticdata_backup_async.sh L394
      均显式传 --tier+--dedup-key 组合且语义=期望去重生效，无调用方依赖「--tier 不去重」。
      修复=tier 分支内补通用 dedup 语义（发送前 check_dedup suppress + 发送成功后
      update_dedup 占窗）。不动通用路径 L2185-2205 的 and ok 契约。
C-2  defer_warning 无 dry_run 参数，RETRY_NOTIFY_DRY_RUN=1 时自测会污染真 buffer。
      修复=defer_warning 加 dry_run 最前短路：不写 buffer、不落 dedup 状态、不外发。

第二轮背景：docs/ops/132-monitor-residuals-review2-20261001.md（独立复审 FAIL 修复）：
P0   send_tiered warning 分支无条件 deferred=True → buffer 追加失败也走 update_dedup
      占窗 → 后续同 key 调用被 check_dedup 吞（与 #123 R4 同款）。修复=defer_warning
      返回三态（enqueued/suppressed/append_failed），只有真入队/真抑制才占窗。
P1   修完 P0 后同 key「失败→恢复→窗口内再失败」的剩余抑制须全部落在设计语义内。
P3   retry_failed_metrics.py 计数写失败告警文案区分「真入队」与「被 dedup 抑制」。

验收判据（主控复审指令）：
  ① 同一 dedup key 连续调两次，第二次不入队（buffer 行数前后对比）
  ② 不同 key 仍能各自入队
  ③ dry_run 时不写 buffer、不落 dedup 状态、不外发
  ④ (P0) buffer 写失败 → 不占窗：第二次同 key 仍能重试、不 suppress
  ⑤ (P0) 真入队 → 正常占窗（不回归）
  ⑥ (P0) 真抑制 → 占窗语义正确
  ⑦ (P1) 同 key「失败→恢复→再失败」时序三段实测观测值

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

    def _read_state(self):
        if not self.state.exists():
            return {}
        try:
            return json.loads(self.state.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

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
        """send_tiered 透传 dry_run 给 defer_warning：dry-run 不写 buffer。
        复审2 P0 订正：dry_run 返回 defer_status="dry_run" → deferred=False（未真入队
        不占窗，与 main() 层 `not args.dry_run` guard 双重不占窗一致）。"""
        n0 = len(self._read_buf())
        res = notify.send_tiered("132 源", "payload", tier=notify.TIER_WARNING,
                                 dry_run=True)
        self.assertEqual(res.get("defer_status"), "dry_run")
        self.assertEqual(res.get("deferred"), False,
                         "dry_run 未真入队，不得视为占窗语义的 deferred")
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

    # ═══ 第二轮复审 P0/P1（docs/ops/132-monitor-residuals-review2-20261001.md）═══
    # P0: send_tiered warning 分支无条件 deferred=True → buffer 追加失败也走 update_dedup
    #     占窗，真告警被静默吞。修法=defer_warning 三态返回，只有 enqueued/suppressed 占窗。
    # 判据: ① buffer 写失败→不占窗(第二次同 key 仍能重试不 suppress)
    #        ② 真入队→正常占窗(不回归)  ③ 真抑制→占窗语义正确
    #        ④ 同 key「失败→恢复→再失败」时序(即 P1 用例)  ⑤ 回归

    def test_p0_buf_append_fail_no_dedup_second_call_retries(self):
        """P0-① buffer 写失败→不占窗：第一次 append 失败不得 update_dedup；第二次同
        dedup-key 仍能重试（不被 check_dedup 拦在 send_tiered 之前）。"""
        calls = []

        def fake_append(path, rec):
            calls.append(1)
            return False

        with unittest.mock.patch.object(notify, "_append_jsonl", fake_append):
            rc1 = self._cli("P0 append fail 源", "第一次")
            self.assertEqual(rc1, 0)
            rc2 = self._cli("P0 append fail 源", "第二次")
            self.assertEqual(rc2, 0)
        self.assertEqual(len(self._read_buf()), 0, "append 失败 buffer 必须为空")
        self.assertEqual(self._read_dedup(), {},
                         "P0-① 修复核心：append 失败绝不 update_dedup 占窗")
        self.assertEqual(calls, [1, 1],
                         "第二次同 key 必须仍进入 defer_warning 重试（未被 dedup 拦截）")
        st = self._read_state()
        self.assertEqual(st, {}, "内存指纹状态也不得被 append 失败污染")

    def test_p0_tier_send_ok_append_failed_false(self):
        """P0-① 判定直接：_tier_send_ok 对 append_failed 必须 False（不占窗）。"""
        self.assertFalse(notify._tier_send_ok(
            {"defer_status": "append_failed", "deferred": False}, notify.TIER_WARNING))
        self.assertTrue(notify._tier_send_ok(
            {"defer_status": "enqueued", "deferred": True}, notify.TIER_WARNING))
        self.assertTrue(notify._tier_send_ok(
            {"defer_status": "suppressed", "deferred": True}, notify.TIER_WARNING))

    def test_p0_enqueue_still_occupies_window(self):
        """P0-② 真入队仍正常占窗（不回归 read dedup 语义）。"""
        rc1 = self._cli("P0 enqueue 源", "第一次")
        self.assertEqual(rc1, 0)
        self.assertEqual(len(self._read_buf()), 1, "真入队应写入 buffer")
        self.assertIn("test_132_key", self._read_dedup(), "真入队应 update_dedup 占窗")
        # 窗口内同 key 第二次被 check_dedup 抑制（不重复入队）
        rc2 = self._cli("P0 enqueue 源", "第二次")
        self.assertEqual(rc2, 0)
        self.assertEqual(len(self._read_buf()), 1, "窗口内第二次不该再入队")

    def test_p0_internal_suppressed_still_occupies_window(self):
        """P0-③ 真抑制（内部 4h 指纹窗命中）→ defer_warning 返回 suppressed → 仍占
        main 层窗口（设计语义：已处理过=占窗，抑制的是重试轰炸不吞首次送达）。"""
        # 预埋活动指纹窗 → defer 走 suppressed 分支
        now = notify.datetime.now()
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        subject = "P0 suppressed 源"
        fp = notify.warning_fingerprint(subject, "payload")
        self.state.write_text(json.dumps({
            fp: {
                "norm_subject": subject[:200], "first_seen": now_str,
                "window_start": now_str, "last_seen": now_str,
                "repeat_count": 1, "notified_repeat": 0, "last_subject": subject[:200],
            }
        }), encoding="utf-8")
        status = notify.defer_warning(subject, "payload")
        self.assertEqual(status, "suppressed", "预埋指纹窗应命中抑制")
        self.assertEqual(len(self._read_buf()), 0, "抑制不得写 buffer")
        # 经 send_tiered + main 层 → deferred=True（suppressed 允许占窗）→ update_dedup
        res = notify.send_tiered(subject, "payload", tier=notify.TIER_WARNING)
        self.assertEqual(res.get("defer_status"), "suppressed")
        self.assertEqual(res.get("deferred"), True)
        self.assertTrue(notify._tier_send_ok(res, notify.TIER_WARNING))
        notify.main([subject, "payload", "--tier", notify.TIER_WARNING, "--from-prefix", "[告警]",
                     "--dedup-key", "test_132_p0_supp", "--dedup-window", "21600"])
        self.assertIn("test_132_p0_supp", self._read_dedup(),
                      "真抑制=已处理过，应占 main 层 dedup 窗")

    def test_p1_fail_then_recover_then_fail_timing(self):
        """P1 时序：同 key「先失败 → 恢复 → 窗口内再失败」。
        结论（P0 修复后）：占窗只发生在真入队时；窗口内第二次抑制=调用方自己要的 dedup
        语义（消息在恢复期已真入队送达），不算吞告警。三段实测观测值如下。"""
        subject = "P1 时序源"
        # 第 1 段: append 失败 → 不占窗
        with unittest.mock.patch.object(notify, "_append_jsonl", return_value=False):
            notify.main([subject, "失败1", "--tier", notify.TIER_WARNING,
                         "--from-prefix", "[告警]",
                         "--dedup-key", "test_132_p1", "--dedup-window", "21600"])
        self.assertEqual(self._read_dedup().get("test_132_p1"), None,
                         "段1 失败不得占窗")
        self.assertEqual(len(self._read_buf()), 0)
        # 第 2 段: 恢复 → 真入队 → 占窗
        notify.main([subject, "恢复后", "--tier", notify.TIER_WARNING,
                     "--from-prefix", "[告警]",
                     "--dedup-key", "test_132_p1", "--dedup-window", "21600"])
        self.assertIn("test_132_p1", self._read_dedup(), "段2 真入队应占窗")
        self.assertEqual(len(self._read_buf()), 1)
        # 第 3 段: 窗口内再失败 → 被 check_dedup 在设计语义内抑制（消息段2已真送达）
        with unittest.mock.patch.object(notify, "_append_jsonl", return_value=False):
            notify.main([subject, "再失败", "--tier", notify.TIER_WARNING,
                         "--from-prefix", "[告警]",
                         "--dedup-key", "test_132_p1", "--dedup-window", "21600"])
        self.assertEqual(len(self._read_buf()), 1,
                         "段3 窗口内被抑制=设计语义（段2已入队送达），不新增 buffer 条目")
        self.assertEqual(len(self._read_dedup()), 1, "抑制不改变窗状态")


if __name__ == "__main__":
    unittest.main(verbosity=2)
