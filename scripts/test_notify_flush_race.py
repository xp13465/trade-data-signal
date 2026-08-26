#!/usr/bin/env python3
"""test_notify_flush_race.py - flush_warning_batch 并发竞态回归测试（B1，2026-08-26）。

背景：codex 外审 P1——旧实现 pre_offset 字节快照+事后切尾，两个 flusher 并发时
重复推送 + 后完成者把对方写入内容截成非法 JSON 致条目永久丢失。修复后：
flush 全生命周期持 WARNING_FLUSH_LOCK_FILE 专用锁 + 按稳定 ID 精确移除。

用例：
T1 双进程并发 flush + 持续 append：零丢失、零重复、文件始终合法 JSONL。
T2 单进程正常流：满窗条目发出并清掉，未满窗口保留。
T3 空 buffer / 不存在文件：安全返回不抛。
T4 存量无 rid 旧条目（ts+subject 兜底稳定 ID）：能正常发出且被清理。
T5 损坏行容错：坏行跳过且打印明确告警（带片段），合法条目不受影响；清理时坏行原样回写。
T6 发送前二次确认：条目已被他方清走 → 放弃本批防重复。

跑法：python3 scripts/test_notify_flush_race.py   （可重复跑）
"""
import json
import multiprocessing
import os
import shutil
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


def _writer_proc(buf_path, lock_path, n_due, barrier_path, state_path=None,
                 dlock_path=None):
    """子进程 A：预写满窗条目（带显式 rid）→ 等栅栏 → 调真实 flush_warning_batch。"""
    notify.WARNING_BUFFER_FILE = Path(buf_path)
    notify.WARNING_FLUSH_LOCK_FILE = Path(lock_path)
    if state_path:
        notify.WARNING_DEDUP_STATE_FILE = Path(state_path)
    if dlock_path:  # codex009 P2：dedup 锁同样隔离到 tmp（codex007 F2 起 flush 收尾会取它）
        notify.WARNING_DEDUP_LOCK_FILE = Path(dlock_path)
    _patch_channels(barrier_path)  # spawn 不继承主进程 mock，子进程内重新 mock 防真发
    with open(buf_path, "a", encoding="utf-8") as f:
        for i in range(n_due):
            # subject/body 用字母后缀（B2 指纹分组会把仅差数字的条目合并为一行，
            # 本测试断言「每个条目逐条推送零重复」，须构造互不同源的条目绕开合并）
            ch = chr(ord('a') + i)
            f.write(json.dumps({
                "ts": _make_old_ts(),
                "rid": f"rid-A-{i}",  # 显式 rid：父进程可断言「每个条目至多被推送一次」
                "subject": f"A-due-{ch}",
                "body": f"body-A-{ch}",
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


def _appender_proc(buf_path, lock_path, n_append, barrier_path, state_path=None,
                   dlock_path=None):
    """子进程 B：等同一栅栏后持续追加未满窗口新条目（与 A 的 flush 并发交错）。"""
    notify.WARNING_BUFFER_FILE = Path(buf_path)
    notify.WARNING_FLUSH_LOCK_FILE = Path(lock_path)
    if dlock_path:
        notify.WARNING_DEDUP_LOCK_FILE = Path(dlock_path)
    if state_path:
        # 关键隔离：B1 起 defer_warning 读写指纹状态文件，不指到 tmp 会污染/读到
        # 生产 data/alerts/warning_dedup_state.json（跨轮同指纹被 4h 窗误抑制）
        notify.WARNING_DEDUP_STATE_FILE = Path(state_path)
    _patch_channels(barrier_path)  # defer_warning 本身不发送，保险起见统一 mock
    deadline = time.time() + 10
    while not (Path(barrier_path).exists() and Path(str(barrier_path) + ".go").exists()):
        if time.time() > deadline:
            sys.exit(3)
        time.sleep(0.01)
    # 注意：subject 用字母后缀（B-new-a/b/...）而非数字——B1 同源指纹降噪上线后，
    # defer_warning 会把仅差数字的条目归一化为同指纹抑制入队（只留第 1 条），
    # 本进程测的是「并发 append 不丢」语义，须构造互不同源的告警绕开去重。
    for i in range(n_append):
        notify.defer_warning(f"B-new-{chr(ord('a') + i)}",
                             f"body-B-new-{chr(ord('a') + i)}")
    Path(str(barrier_path) + f".doneB-{os.getpid()}").write_text("ok", encoding="utf-8")
    sys.exit(0)


def _flusher2_proc(buf_path, lock_path, barrier_path, state_path=None,
                   dlock_path=None):
    """子进程 C：第二个并发 flusher（模拟 schedule_monitor 与 monitor_72h 撞车）。"""
    notify.WARNING_BUFFER_FILE = Path(buf_path)
    notify.WARNING_FLUSH_LOCK_FILE = Path(lock_path)
    if state_path:
        notify.WARNING_DEDUP_STATE_FILE = Path(state_path)
    if dlock_path:
        notify.WARNING_DEDUP_LOCK_FILE = Path(dlock_path)
    _patch_channels(barrier_path)  # spawn 不继承 mock，防真发
    deadline = time.time() + 10
    while not (Path(barrier_path).exists() and Path(str(barrier_path) + ".go").exists()):
        if time.time() > deadline:
            sys.exit(3)
        time.sleep(0.01)
    r = notify.flush_warning_batch(dry_run=False)
    Path(str(barrier_path) + f".doneC-{os.getpid()}").write_text(json.dumps(r), encoding="utf-8")
    sys.exit(0)


def _record_send(sent_log_path, subject, body):
    """把「实际成功发送」的聚合消息(subject+body)以 JSON 行追加进共享记录(flock 防交错)。
    codex006 P2：三进程各自 mock 无共享记录时，「都发送但只一个清理成功」会假绿；
    记录真实发送流水（含 body，单条目 subject 在 body 内），父进程才能断言零重复推送。"""
    import fcntl
    with open(sent_log_path, "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps({"subject": subject, "body": body}, ensure_ascii=False) + "\n")
        fcntl.flock(f, fcntl.LOCK_UN)


def _patch_channels(tag=""):
    """mock 掉三个发送渠道：全部返回成功（确定性 sent_batch=True），并把每次成功发送的
    聚合消息(subject+body)落入 <tmp>/sent-rN.log 共享记录（主进程与 spawn 子进程各自调用）。
    tag 仅用于日志定位，不影响行为。"""
    sent_log = os.environ.get("NOTIFY_TEST_SENT_LOG", "")

    def fake_email(subject, body, **k):
        if sent_log:
            _record_send(sent_log, subject, str(body))
        return True

    def fake_tg(subject, body, **k):
        return True

    def fake_fs(subject, body, **k):
        return True

    unittest.mock.patch.object(notify, "_send_email", side_effect=fake_email).start()
    unittest.mock.patch.object(notify, "send_telegram", side_effect=fake_tg).start()
    unittest.mock.patch.object(notify, "send_feishu", side_effect=fake_fs).start()


class FlushRaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="notify_flush_race_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.buf = str(Path(self.tmp) / "warning_buffer.jsonl")
        self.lock = str(Path(self.tmp) / "warning_buffer.flushlock")
        # 关键：flush 读写目标指到临时目录，绝不碰生产 data/alerts/warning_buffer.jsonl
        # （B1 后含指纹状态文件 warning_dedup_state.json 与去重锁 warning_dedup.lock，
        # 同样必须隔离——codex009 P2：测试持生产锁文件可能与真实监控互相等待）
        self.dlock = str(Path(self.tmp) / "warning_dedup.lock")
        self._orig_buf = notify.WARNING_BUFFER_FILE
        self._orig_lock = notify.WARNING_FLUSH_LOCK_FILE
        self._orig_state = notify.WARNING_DEDUP_STATE_FILE
        self._orig_dlock = getattr(notify, "WARNING_DEDUP_LOCK_FILE", None)
        notify.WARNING_BUFFER_FILE = Path(self.buf)
        notify.WARNING_FLUSH_LOCK_FILE = Path(self.lock)
        notify.WARNING_DEDUP_STATE_FILE = Path(self.tmp) / "warning_dedup_state.json"
        notify.WARNING_DEDUP_LOCK_FILE = Path(self.dlock)
        self.addCleanup(self._restore_paths)
        _patch_channels()

    def _restore_paths(self):
        notify.WARNING_BUFFER_FILE = self._orig_buf
        notify.WARNING_FLUSH_LOCK_FILE = self._orig_lock
        notify.WARNING_DEDUP_STATE_FILE = self._orig_state
        if self._orig_dlock is not None:
            notify.WARNING_DEDUP_LOCK_FILE = self._orig_dlock

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
        """T4 存量无 rid 旧条目：ts+subject 兜底稳定 ID，正常发出+清理，零丢失。"""
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
        sent_log = str(Path(tmp) / f"sent-r{round_no}.log")
        # 每轮独立指纹状态文件（B1 隔离：跨轮共享会因 4h 窗把同字母 subject 误抑制）
        statep = str(Path(tmp) / f"dedup-state-r{round_no}.json")
        # 每轮独立去重锁（codex009 P2：不与生产 data/alerts/warning_dedup.lock 共享）
        dlockp = str(Path(tmp) / f"dedup-lock-r{round_no}.lock")
        # 共享发送记录路径经环境变量传给 spawn 子进程（P2：真实发送流水共享）
        os.environ["NOTIFY_TEST_SENT_LOG"] = sent_log
        self.addCleanup(os.environ.pop, "NOTIFY_TEST_SENT_LOG", None)
        ctx = multiprocessing.get_context("spawn")
        procs = [
            ctx.Process(target=_writer_proc,
                        args=(buf, lockp, N_DUE, barrier, statep, dlockp)),
            ctx.Process(target=_flusher2_proc,
                        args=(buf, lockp, barrier, statep, dlockp)),
            ctx.Process(target=_appender_proc,
                        args=(buf, lockp, N_APPEND, barrier, statep, dlockp)),
        ]
        for p in procs:
            p.start()
        time.sleep(0.3)  # 让子进程先落好各自预写内容
        Path(barrier + ".go").touch()  # 放行三进程同时开跑
        for p in procs:
            p.join(timeout=60)
            self.assertEqual(p.exitcode, 0, f"子进程异常退出 exit={p.exitcode}")
        entries = self._read_entries(buf)  # 解析失败会直接抛 → 文件始终合法 JSONL 断言
        due_entries = [e for e in entries if e["subject"].startswith("A-due-")]
        due_subjects = [e["subject"] for e in due_entries]
        new_subjects = [e["subject"] for e in entries if e["subject"].startswith("B-new-")]
        # 零重复（文件层）：due 条目每个只出现一次（两 flusher 只有一方能发走并清掉；
        # 另一方二次确认查不到即放弃；即使都尝试也绝不在文件里留两份）
        for s in set(due_subjects):
            self.assertEqual(due_subjects.count(s), 1, f"due 条目重复：{s}")
        # 零丢失：append 的每条新条目必须都在（flush 清理不许误删新增）
        self.assertEqual(len(new_subjects), N_APPEND, f"append 新条目有丢失：{new_subjects}")
        for i in range(N_APPEND):
            self.assertIn(f"B-new-{chr(ord('a') + i)}", new_subjects)
        # 至多 N_DUE 条 due 残留（0 或 N：若两 flusher 都因竞态放弃则整批留下轮，
        # 但绝不超 N 且无重复；正常恰有一方发走 → 残留 0）
        self.assertLessEqual(len(due_subjects), N_DUE)
        # flush 锁文件存在（机制在位证据）
        self.assertTrue(Path(lockp).exists())
        # ── P2 加固：真实发送流水断言 ──────────────────────────────
        # 合并三进程写入的共享 sent.log（JSONL：{subject, body}）：每个显式 rid 条目的
        # subject 至多出现在一次推送的 body 中。旧断言只数最终文件，若两 flusher 都发送
        # 但只有一个清理成功 → 文件无重复但用户收两封 → 假绿；这里直接验「推送次数」本身。
        if Path(sent_log).exists():
            sent_msgs = []
            for ln in Path(sent_log).read_text(encoding="utf-8").splitlines():
                if ln.strip():
                    sent_msgs.append(json.loads(ln))  # 非法行=记录写坏，直接失败暴露
            for i in range(N_DUE):
                subj = f"A-due-{chr(ord('a') + i)}"
                # 单条条目在推送正文中的出现次数 = 该条目被推送给用户的次数
                n_sent = sum(1 for m in sent_msgs if subj in m["body"])
                if subj not in due_subjects:  # 已被发走并清掉的那批必须恰好推 1 次
                    self.assertEqual(n_sent, 1, f"{subj} 推送 {n_sent} 次(应=1)")
                else:
                    # 留在文件的批次：至多被推 1 次（且留下轮），绝不重复推送
                    self.assertLessEqual(n_sent, 1, f"{subj} 推送 {n_sent} 次(>1=重复推送)")
            # 聚合邮件格式校验：每条推送 subject 必含「N条 warning 汇总」
            for m in sent_msgs:
                self.assertIn("条 warning 汇总", m["subject"],
                              f"聚合邮件 subject 格式异常：{m['subject']}")
        else:
            # 整轮无人成功发送（两 flusher 都因竞态放弃）也合法，但此时文件里必有全部 due
            self.assertEqual(len(due_subjects), N_DUE, "无发送记录时 due 应整批留在文件")

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
