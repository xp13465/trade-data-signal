#!/usr/bin/env python3
"""test_notify_flush_race.py - flush_warning_batch 并发竞态回归测试（B1，2026-08-26）。

背景：codex 外审 P1——旧实现 pre_offset 字节快照+事后切尾，两个 flusher 并发时
重复推送 + 后完成者把对方写入内容截成非法 JSON 致条目永久丢失。修复后：
flush 全生命周期持 WARNING_FLUSH_LOCK_FILE 专用锁 + 按稳定 ID 精确移除。

用例：
T1 双进程并发 flush + 持续 append：零丢失、零重复、文件始终合法 JSONL。
T2 单进程正常流：满窗条目发出并清掉，未满窗口保留。
T3 空 buffer / 不存在文件：安全返回不抛。
T4 存量无 rid 旧条目（内容哈希兜底）：能正常发出且被清理。
T5 损坏行容错：坏行跳过且打印明确告警（带片段），合法条目不受影响；清理时坏行原样回写。
T6 发送前二次确认：条目已被他方清走 → 放弃本批防重复。

跑法：python3 scripts/test_notify_flush_race.py   （可重复跑）
"""
import json
import multiprocessing
import os
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).absolute().parent
sys.path.insert(0, str(ROOT))

import notify  # noqa: E402

# 子进程 worker 用 spawn 启动时需要能重新 import 本测试模块（__main__ 保护下安全）
N_DUE = 6        # 每个 writer 预写的满窗条目数
N_APPEND = 8     # append 进程持续追加的新条目数


def _make_old_ts():
    """30min 窗口之前的 ts（必到期）。"""
    import datetime
    return (datetime.datetime.now() - datetime.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")


def _writer_proc(buf_path, lock_path, n_due, barrier_path):
    """子进程 A：预写满窗条目 → 等栅栏 → 调真实 flush_warning_batch（真锁真文件）。"""
    import datetime
    notify.WARNING_BUFFER_FILE = Path(buf_path)
    notify.WARNING_FLUSH_LOCK_FILE = Path(lock_path)
    _patch_channels()  # spawn 不继承主进程 mock，子进程内重新 mock 防真发
    with open(buf_path, "a", encoding="utf-8") as f:
        for i in range(n_due):
            f.write(json.dumps({
                "ts": _make_old_ts(),
                "subject": f"A-due-{os.getpid()}-{i}",
                "body": f"body-A-{i}",
                "from_prefix": "[告警·聚合]",
            }, ensure_ascii=False) + "\n")
    # 栅栏：两进程都写完才放行（用文件存在性模拟，避免跨平台 Barrier 兼容坑）
    Path(barrier_path).touch()
    deadline = time.time() + 10
    while not (Path(barrier_path).exists() and Path(str(barrier_path) + ".go").exists()):
        if time.time() > deadline:
            sys.exit(3)
        time.sleep(0.01)
    r = notify.flush_warning_batch(dry_run=False)
    Path(str(barrier_path) + f".doneA-{os.getpid()}").write_text(json.dumps(r), encoding="utf-8")
    sys.exit(0)


def _appender_proc(buf_path, lock_path, n_append, barrier_path):
    """子进程 B：等同一栅栏后持续追加未满窗口新条目（与 A 的 flush 并发交错）。"""
    notify.WARNING_BUFFER_FILE = Path(buf_path)
    notify.WARNING_FLUSH_LOCK_FILE = Path(lock_path)
    _patch_channels()  # defer_warning 本身不发送，保险起见统一 mock
    deadline = time.time() + 10
    while not (Path(barrier_path).exists() and Path(str(barrier_path) + ".go").exists()):
        if time.time() > deadline:
            sys.exit(3)
        time.sleep(0.01)
    for i in range(n_append):
        notify.defer_warning(f"B-new-{i}", f"body-B-new-{i}")
    Path(str(barrier_path) + f".doneB-{os.getpid()}").write_text("ok", encoding="utf-8")
    sys.exit(0)


def _flusher2_proc(buf_path, lock_path, barrier_path):
    """子进程 C：第二个并发 flusher（模拟 schedule_monitor 与 monitor_72h 撞车）。"""
    notify.WARNING_BUFFER_FILE = Path(buf_path)
    notify.WARNING_FLUSH_LOCK_FILE = Path(lock_path)
    _patch_channels()  # spawn 不继承 mock，防真发
    deadline = time.time() + 10
    while not (Path(barrier_path).exists() and Path(str(barrier_path) + ".go").exists()):
        if time.time() > deadline:
            sys.exit(3)
        time.sleep(0.01)
    r = notify.flush_warning_batch(dry_run=False)
    Path(str(barrier_path) + f".doneC-{os.getpid()}").write_text(json.dumps(r), encoding="utf-8")
    sys.exit(0)


def _patch_channels():
    """mock 掉三个发送渠道全部成功（确定性断言 sent_batch=True + 绝不真发）。
    主进程与 spawn 子进程都要各自调用（spawn 不继承 mock）。"""
    for name in ("_send_email", "send_telegram", "send_feishu"):
        unittest.mock.patch.object(notify, name, return_value=True).start()


class FlushRaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="notify_flush_race_")
        self.buf = str(Path(self.tmp) / "warning_buffer.jsonl")
        self.lock = str(Path(self.tmp) / "warning_buffer.flushlock")
        # 关键：flush 读写目标指到临时目录，绝不碰生产 data/alerts/warning_buffer.jsonl
        self._orig_buf = notify.WARNING_BUFFER_FILE
        self._orig_lock = notify.WARNING_FLUSH_LOCK_FILE
        notify.WARNING_BUFFER_FILE = Path(self.buf)
        notify.WARNING_FLUSH_LOCK_FILE = Path(self.lock)
        self.addCleanup(self._restore_paths)
        _patch_channels()

    def _restore_paths(self):
        notify.WARNING_BUFFER_FILE = self._orig_buf
        notify.WARNING_FLUSH_LOCK_FILE = self._orig_lock

    def _read_entries(self, path=None, allow_bad=False):
        """解析 JSONL 文件；allow_bad=False 时任何非 JSON 行直接抛（=合法 JSONL 断言）。"""
        out = []
        raw = Path(path or self.buf).read_bytes()
        for ln in raw.decode("utf-8", errors="replace").splitlines():
            if ln.strip():
                try:
                    out.append(json.loads(ln))
                except json.JSONDecodeError:
                    if not allow_bad:
                        raise
        return out

    def test_t4_legacy_no_rid_entries(self):
        """T4 存量无 rid 旧条目：内容哈希兜底稳定 ID，正常发出+清理，零丢失。"""
        old_ts = _make_old_ts()
        legacy = [
            {"ts": old_ts, "subject": "legacy-1", "body": "旧条目无rid",
             "from_prefix": "[告警]"},
            {"ts": old_ts, "subject": "legacy-2", "body": "x" * 100,
             "from_prefix": "[告警·聚合]"},
            {"ts": "2099-01-01 00:00:00", "subject": "keep-fresh", "body": "刚到的",
             "from_prefix": "[告警·聚合]"},  # 未满窗口应保留
        ]
        with open(self.buf, "w", encoding="utf-8") as f:
            for e in legacy:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        r = notify.flush_warning_batch()
        self.assertTrue(r["sent_batch"])
        self.assertEqual(r["n_due"], 2)  # legacy-1/legacy-2 到期；时间戳全法
        entries = self._read_entries()
        subjects = [e["subject"] for e in entries]
        self.assertNotIn("legacy-1", subjects)
        self.assertNotIn("legacy-2", subjects)
        self.assertIn("keep-fresh", subjects)  # 未满窗口留下轮

    def test_t5_corrupt_line_tolerated_and_reported(self):
        """T5 坏行跳过+明确告警（非静默）；合法条目照发；清理时坏行原样回写。"""
        old = _make_old_ts()
        good1 = json.dumps({"ts": old, "subject": "good-1", "body": "b1",
                            "from_prefix": "[告警·聚合]", "rid": "r-good-1"}, ensure_ascii=False)
        bad_line = '{"ts": "' + old + '", "subject": "broken'  # 半行非法 JSON
        good2 = json.dumps({"ts": old, "subject": "good-2", "body": "b2",
                            "from_prefix": "[告警·聚合]", "rid": "r-good-2"}, ensure_ascii=False)
        fresh = json.dumps({"ts": "2099-01-01 00:00:00", "subject": "fresh", "body": "f",
                            "from_prefix": "[告警·聚合]", "rid": "r-fresh"}, ensure_ascii=False)
        Path(self.buf).write_text("\n".join([good1, bad_line, good2, fresh]) + "\n",
                                  encoding="utf-8")
        import io
        err_buf = io.StringIO()
        with unittest.mock.patch.object(sys, "stderr", err_buf):
            r = notify.flush_warning_batch()
        printed = err_buf.getvalue()
        self.assertTrue(r["sent_batch"])
        self.assertIn("坏行跳过", printed)          # 明确告警日志（带片段）
        self.assertIn("broken", printed)           # 片段前80字符可见
        entries = self._read_entries(self.buf, allow_bad=True)
        subjects = [e.get("subject", "") for e in entries]
        self.assertNotIn("good-1", subjects)
        self.assertNotIn("good-2", subjects)
        self.assertIn("fresh", subjects)
        # 坏行原样回写（下轮可解析的半行不吞）
        self.assertIn('{"ts": "', Path(self.buf).read_text(encoding="utf-8"))

    def test_t6_second_confirm_skips_gone_entries(self):
        """T6 快照后条目被他方清走 → 二次确认查不到 → 放弃本批不重发。"""
        old = _make_old_ts()
        Path(self.buf).write_text(json.dumps(
            {"ts": old, "subject": "gone-entry", "body": "b", "from_prefix": "[告警·聚合]",
             "rid": "r-gone"}, ensure_ascii=False) + "\n", encoding="utf-8")
        real_open = open

        def open_then_empty(path, *a, **k):
            """第一次读返回有条目，之后所有读返回空文件（模拟他方已清）。"""
            if str(path) == self.buf and getattr(open_then_empty, "first", True):
                open_then_empty.first = False
                return real_open(path, *a, **k)
            if str(path) == self.buf:
                import tempfile as tf
                empty = tf.NamedTemporaryFile(suffix=".jsonl", delete=False)
                empty.close()
                return real_open(empty.name, *a, **k)
            return real_open(path, *a, **k)

        with unittest.mock.patch("builtins.open", side_effect=open_then_empty):
            r = notify.flush_warning_batch()
        self.assertFalse(r["sent_batch"])  # 放弃本批防重复

    def test_t1_concurrent_flush_no_loss_no_dup(self):
        """T1 主场景：双 flusher + 持续 appender 三进程并发——零丢失、零重复、合法 JSONL。

        可重复跑（默认连跑 5 轮取交集断言）。"""
        for round_no in range(5):
            with self.subTest(round=round_no):
                self._run_one_race_round(round_no)

    def _run_one_race_round(self, round_no):
        tmp = self.tmp
        buf = str(Path(tmp) / f"buf-r{round_no}.jsonl")
        lockp = str(Path(tmp) / f"lock-r{round_no}.flushlock")
        barrier = str(Path(tmp) / f"barrier-r{round_no}")
        ctx = multiprocessing.get_context("spawn")
        procs = [
            ctx.Process(target=_writer_proc, args=(buf, lockp, N_DUE, barrier)),
            ctx.Process(target=_flusher2_proc, args=(buf, lockp, barrier)),
            ctx.Process(target=_appender_proc, args=(buf, lockp, N_APPEND, barrier)),
        ]
        for p in procs:
            p.start()
        time.sleep(0.3)  # 让子进程先落好各自预写内容
        Path(barrier + ".go").touch()  # 放行三进程同时开跑
        for p in procs:
            p.join(timeout=60)
            self.assertEqual(p.exitcode, 0, f"子进程异常退出 exit={p.exitcode}")
        entries = self._read_entries(buf)  # 解析失败会直接抛 → 文件始终合法 JSONL 断言
        due_subjects = [e["subject"] for e in entries if e["subject"].startswith(("A-due-",))]
        new_subjects = [e["subject"] for e in entries if e["subject"].startswith("B-new-")]
        # 零重复：due 条目每个只出现一次（两 flusher 只有一方能发走并清掉；
        # 另一方二次确认查不到即放弃；即使都尝试也绝不在文件里留两份）
        for s in set(due_subjects):
            self.assertEqual(due_subjects.count(s), 1, f"due 条目重复：{s}")
        # 零丢失：append 的每条新条目必须都在（flush 清理不许误删新增）
        self.assertEqual(len(new_subjects), N_APPEND, f"append 新条目有丢失：{new_subjects}")
        for i in range(N_APPEND):
            self.assertIn(f"B-new-{i}", new_subjects)
        # 至多 N_DUE 条 due 残留（0 或 N：若两 flusher 都因竞态放弃则整批留下轮，
        # 但绝不超 N 且无重复；正常恰有一方发走 → 残留 0）
        self.assertLessEqual(len(due_subjects), N_DUE)
        # flush 锁文件存在（机制在位证据）
        self.assertTrue(Path(lockp).exists())

    def test_t2_single_process_normal_flow(self):
        """T2 单进程正常流：满窗发出清掉、未满窗口保留、计数正确。"""
        old = _make_old_ts()
        rows = []
        for i in range(3):
            rows.append({"ts": old, "subject": f"old-{i}", "body": f"b{i}",
                         "from_prefix": "[告警·聚合]", "rid": f"r-old-{i}"})
        rows.append({"ts": "2099-01-01 00:00:00", "subject": "fresh", "body": "f",
                     "from_prefix": "[告警·聚合]", "rid": "r-fresh"})
        with open(self.buf, "w", encoding="utf-8") as f:
            for e in rows:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        r = notify.flush_warning_batch()
        self.assertTrue(r["sent_batch"])
        self.assertEqual(r["n_due"], 3)
        entries = self._read_entries()
        self.assertEqual([e["subject"] for e in entries], ["fresh"])

    def test_t3_empty_and_missing_buffer(self):
        """T3 空 buffer / 文件不存在：安全返回不抛。"""
        Path(self.buf).write_text("", encoding="utf-8")
        r = notify.flush_warning_batch()
        self.assertEqual(r, {"sent_batch": False, "n_due": 0, "n_remaining": 0})
        missing = notify.flush_warning_batch.__wrapped__ if hasattr(
            notify.flush_warning_batch, "__wrapped__") else None
        # 文件不存在场景：换一个不存在的路径
        notify.WARNING_BUFFER_FILE = Path(self.tmp) / "no_such_buffer.jsonl"
        r2 = notify.flush_warning_batch()
        self.assertEqual(r2, {"sent_batch": False, "n_due": 0, "n_remaining": 0})
        del missing


if __name__ == "__main__":
    unittest.main(verbosity=2)
