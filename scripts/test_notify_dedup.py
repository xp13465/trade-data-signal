#!/usr/bin/env python3
"""test_notify_dedup.py - warning 同源指纹降噪回归测试（B1/B2/B3，2026-08-26）。

背景：docs/feishu-aggregate-spam-rootcause-20260826.md §5——聚合链路"防丢不防噪"，
同源告警反复入队每 30min 一封轰炸。改造后：
B1 defer_warning 同源指纹 4h 固定窗抑制（只累计 repeat_count）；
B2 flush 发送时同源合并显示「[第N次]」/「[本批N条合并]」+ 发送后 notified_repeat 快照；
B3 send() 入口识别 [恢复] 前缀清除对应指纹状态（恢复即静默清零）。
穿透硬门槛：①翻倍穿透（新增量 ≥ max(2, 2×已通知量)）②critical 升级直发天然绕过。

用例：
U1 同指纹窗口内不入队 + repeat_count 累计（B1 主场景）
U2 固定窗过期后重新入队，从第 1 次重新计（GC）
U3 critical 升级穿透：send_tiered(tier=critical) 直发，不经 buffer/指纹状态
U4 翻倍穿透：已通知 1 次后再积累 2 次 → 第 3 次照常入队
U5 恢复即静默清零：[恢复] 到达清指纹状态，复发从第 1 次重新计（B3）
U6 状态文件损坏容错：坏 JSON 当空重建，defer 正常工作且状态文件恢复合法 JSON
U7 向后兼容：旧格式 buffer 条目（无 fp 字段）flush 正常分组发送
U8 B2 显示与 dry_run 安全：[第N次] 标签出现；dry_run 不清 buffer 不写状态
U9 flush 成功后 notified_repeat 快照对齐 repeat_count

codex007 补丁用例（2026-08-26，P1×3 + P2×3 各至少一测）：
U10  P1① buffer 追加失败 → 绝不登记指纹状态（无幽灵静默窗）
U11  P1② 多进程并发 defer 同指纹 → repeat_count 精确不丢（dedup 短锁）
U12  P1③ 快照保存失败 → due 条目保留 buffer 重发（宁重发不吞）
U13  P2④ dry_run 恢复消息全路径只读，不触碰 state
U14  P2⑤ 收严匹配：共享长前缀不误清 + 聚合恢复 body 明细行逐源清零
U15  P2⑥ 身份标识 token（sh510300/sz159915）异源不互吞；计量数字差仍同源

跑法：python3 scripts/test_notify_dedup.py   （可重复跑；全部 tmp 目录隔离）
"""
import json
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).absolute().parent
sys.path.insert(0, str(ROOT))

import notify  # noqa: E402


def _old_ts(hours=1.0):
    """30min 聚合窗口之前的 ts（必到期）。"""
    return (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


class DedupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="notify_dedup_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.buf = Path(self.tmp) / "warning_buffer.jsonl"
        self.state = Path(self.tmp) / "warning_dedup_state.json"
        self.lock = Path(self.tmp) / "warning_buffer.flushlock"
        self.dedup_lock = Path(self.tmp) / "warning_dedup.lock"
        # 关键：读写目标全部指到临时目录，绝不碰生产 data/alerts/
        for attr, val in (("WARNING_BUFFER_FILE", self.buf),
                          ("WARNING_FLUSH_LOCK_FILE", self.lock),
                          ("WARNING_DEDUP_STATE_FILE", self.state),
                          ("WARNING_DEDUP_LOCK_FILE", self.dedup_lock)):
            setattr(self, f"_orig_{attr}", getattr(notify, attr))
            setattr(notify, attr, val)
            self.addCleanup(lambda a=attr, o=getattr(self, f"_orig_{attr}"):
                            setattr(notify, a, o))
        # 三渠道全 mock 成功（绝不真发）；仅邮件侧记录调用参数供断言（每条消息恰记 1 次）
        self.sent = []

        def fake_channel(subject, body, **k):
            return True

        def fake_email(subject, body, **k):
            self.sent.append({"subject": subject, "body": str(body)})
            return True

        for name in ("send_telegram", "send_feishu"):
            p = unittest.mock.patch.object(notify, name, side_effect=fake_channel)
            p.start()
            self.addCleanup(p.stop)
        p = unittest.mock.patch.object(notify, "_send_email", side_effect=fake_email)
        p.start()
        self.addCleanup(p.stop)

    # ── 工具 ──────────────────────────────────────────────────────
    def _read_buf(self):
        if not self.buf.exists():
            return []
        out = []
        for ln in self.buf.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                out.append(json.loads(ln))
        return out

    def _read_state(self):
        if not self.state.exists():
            return {}
        return json.loads(self.state.read_text(encoding="utf-8"))

    def _write_buf(self, entries):
        with open(self.buf, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

    # ── U1 同指纹窗口内不入队 + repeat 计数（B1 主场景）─────────────
    def test_u1_same_fingerprint_suppressed_with_repeat_count(self):
        r1 = notify.defer_warning("baostock 封禁熔断(10001011)", "覆盖率持续不足")
        r2 = notify.defer_warning("baostock 封禁熔断(10001012)", "覆盖率持续不足")
        r3 = notify.defer_warning("baostock 封禁熔断(10001099)", "覆盖率仍不足")
        self.assertTrue(r1 and r2 and r3)  # 返回值语义=True=已处理（入队或合并计数）
        entries = self._read_buf()
        self.assertEqual(len(entries), 1,
                         f"同指纹 4h 窗口内应只入队 1 条，实际 {len(entries)} 条")
        self.assertEqual(entries[0]["subject"], "baostock 封禁熔断(10001011)")
        st = self._read_state()
        self.assertEqual(len(st), 1)
        rec = next(iter(st.values()))
        self.assertEqual(rec["repeat_count"], 3, "被抑制的 2 次应累计进 repeat_count")
        self.assertEqual(rec["notified_repeat"], 0, "尚未随聚合发出过")
        self.assertIn("window_start", rec)
        self.assertIn("last_seen", rec)
        # 不同源（归一化后仍不同）不受影响，正常入队
        notify.defer_warning("deploy R2 上传失败", "upload-index err")
        entries = self._read_buf()
        self.assertEqual(len(entries), 2)
        subjects = {e["subject"] for e in entries}
        self.assertIn("deploy R2 上传失败", subjects)

    # ── U2 固定窗过期后重新入队 ────────────────────────────────────
    def test_u2_window_expiry_requeues_from_first(self):
        notify.defer_warning("feishu ws 心跳陈旧", "持续超时")
        st = self._read_state()
        fp = next(iter(st))
        # 把窗口起点拨回 5 小时前（超过 4h 窗）
        old = (datetime.now() - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")
        st[fp]["window_start"] = old
        st[fp]["first_seen"] = old
        st[fp]["repeat_count"] = 42
        self.state.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        n_before = len(self._read_buf())
        notify.defer_warning("feishu ws 心跳陈旧", "持续超时")
        entries = self._read_buf()
        self.assertEqual(len(entries), n_before + 1, "窗口过期后同源应重新入队")
        st2 = self._read_state()
        self.assertEqual(st2[fp]["repeat_count"], 1, "过期重建后应从第 1 次重新计")
        self.assertEqual(st2[fp]["notified_repeat"], 0)

    # ── U3 critical 穿透：升级直发不经 buffer/state ────────────────
    def test_u3_critical_bypasses_dedup_entirely(self):
        notify.defer_warning("update_all 卡死", "117min 未完成")
        n_buf = len(self._read_buf())
        res = notify.send_tiered("update_all 卡死(恶化)", "进程僵死需人工",
                                 tier=notify.TIER_CRITICAL)
        self.assertTrue(res["email"] and res["feishu"], "critical 必须立即直发")
        self.assertEqual(len(self._read_buf()), n_buf, "critical 不得进 warning buffer")
        # critical 直发不影响既有指纹的窗口计数（两套机制互不干扰）
        st = self._read_state()
        recs = list(st.values())
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["repeat_count"], 1)

    # ── U4 翻倍穿透 ────────────────────────────────────────────────
    def test_u4_double_burst_breakthrough(self):
        s = "intraday R2 上传失败"
        notify.defer_warning(s, "err")          # 第 1 次：入队
        # 模拟该批已被聚合发出（快照 notified_repeat=1）
        st = self._read_state()
        fp = next(iter(st))
        st[fp]["notified_repeat"] = 1
        self.state.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        notify.defer_warning(s, "err")          # 第 2 次：burst=1 < max(2,2)=2 → 抑制
        self.assertEqual(len(self._read_buf()), 1)
        notify.defer_warning(s, "err")          # 第 3 次：burst=2 ≥ 2 → 穿透入队
        entries = self._read_buf()
        self.assertEqual(len(entries), 2, "翻倍穿透后应照常入队（共首条+穿透条 2 条）")
        st2 = self._read_state()
        self.assertEqual(st2[fp]["repeat_count"], 3)

    # ── U5 恢复即静默清零（B3）────────────────────────────────────
    def test_u5_recovery_clears_fingerprint_state(self):
        s = "baostock 封禁熔断(10001011)"
        notify.defer_warning(s, "覆盖率不足")
        notify.defer_warning(s, "覆盖率不足")    # 抑制，rc=2
        st = self._read_state()
        self.assertEqual(next(iter(st.values()))["repeat_count"], 2)
        # [恢复] 消息到达（走 send() 主路径，CLI/分级入口同款）
        notify.send(f"[恢复] {s} 08-26 15:00", "<br>异常已自动恢复</br>")
        self.assertEqual(self._read_state(), {}, "恢复后对应指纹状态应清零")
        # 复发：从第 1 次重新计入队
        n_before = len(self._read_buf())
        notify.defer_warning(s, "再次触发")
        entries = self._read_buf()
        self.assertEqual(len(entries), n_before + 1, "恢复后复发应立即重新入队")
        st2 = self._read_state()
        self.assertEqual(next(iter(st2.values()))["repeat_count"], 1)
        # monitor_72h 链路的恢复前缀是 [72h恢复] 而非 [恢复]——同样必须清零（举一反三）
        notify.defer_warning("feishu ws 心跳陈旧", "持续超时")   # 新源登记 rc=1
        self.assertEqual(len(self._read_state()), 2,
                         "baostock(复发 rc=1) + feishu ws 应各有一条指纹状态")
        notify.send("[72h恢复] feishu ws 心跳陈旧 08-26 16:00", "已恢复")
        st3 = self._read_state()
        self.assertEqual(len(st3), 1, "[72h恢复] 只清对应指纹，不动其他源")
        self.assertNotIn(notify.warning_fingerprint("feishu ws 心跳陈旧"), st3)
        # 非恢复前缀的消息不得误清
        notify.send("[告警] baostock 封禁熔断(10001011) 恶化", "x")
        self.assertEqual(len(self._read_state()), 1, "[告警] 等非恢复前缀不得触发清零")

    # ── U6 状态文件损坏容错 ────────────────────────────────────────
    def test_u6_corrupt_state_file_rebuilt(self):
        self.state.parent.mkdir(parents=True, exist_ok=True)
        self.state.write_text('{"broken-json": [', encoding="utf-8")  # 半截非法 JSON
        notify.defer_warning("监控交接缺失", "上轮未落盘")
        entries = self._read_buf()
        self.assertEqual(len(entries), 1, "坏状态当空重建，告警必须照常入队")
        # save 后状态文件恢复为合法 JSON 且计数从 1 开始
        st = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(next(iter(st.values()))["repeat_count"], 1)
        # 结构非法（顶层非 dict）同样容错
        self.state.write_text('"just-a-string"', encoding="utf-8")
        notify.defer_warning("另一个独立告警源", "x")
        self.assertEqual(len(self._read_buf()), 2)

    # ── U7 向后兼容：旧格式 buffer 条目（无 fp 字段）────────────────
    def test_u7_legacy_entries_without_fp_flush_normally(self):
        old = _old_ts()
        self._write_buf([
            {"ts": old, "subject": "legacy-alpha", "body": "旧条目无fp字段",
             "from_prefix": "[告警·聚合]", "rid": "r-l1"},
            {"ts": old, "subject": "legacy-beta 完全不同的告警", "body": "另一类",
             "from_prefix": "[告警·聚合]", "rid": "r-l2"},
        ])
        r = notify.flush_warning_batch()
        self.assertTrue(r["sent_batch"])
        self.assertEqual(r["n_due"], 2)
        self.assertEqual(self._read_buf(), [], "发送成功后应清掉")
        self.assertEqual(len(self.sent), 1)
        # 两个不同源条目各自成行展示（<hr> 分隔），内容一条不少
        body = self.sent[0]["body"]
        self.assertIn("legacy-alpha", body)
        self.assertIn("legacy-beta", body)
        self.assertIn("<hr>", body)

    # ── U8 B2 显示 + dry_run 安全 ─────────────────────────────────
    def test_u8_repeat_label_and_dry_run_safety(self):
        s = "磁盘水位告警"
        fp = notify.warning_fingerprint(s, "用量超阈值")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.state.write_text(json.dumps({
            fp: {"norm_subject": notify._norm_fp_text(s), "first_seen": now_str,
                 "window_start": now_str, "last_seen": now_str,
                 "repeat_count": 5, "notified_repeat": 1, "last_subject": s},
        }, ensure_ascii=False), encoding="utf-8")
        self._write_buf([{"ts": _old_ts(), "subject": s, "body": "用量超阈值",
                          "from_prefix": "[告警·聚合]", "rid": "r-u8", "fp": fp}])
        before_state = self.state.read_text(encoding="utf-8")
        before_buf = self.buf.read_bytes()
        r = notify.flush_warning_batch(dry_run=True)
        self.assertTrue(r["sent_batch"])
        self.assertEqual(len(self.sent), 1)
        self.assertIn("[第5次]", self.sent[0]["body"],
                      "repeat_count>1 应显示 [第N次] 标签")
        self.assertIn(s, self.sent[0]["body"])
        self.assertEqual(self.buf.read_bytes(), before_buf, "dry_run 不得清 buffer")
        self.assertEqual(self.state.read_text(encoding="utf-8"), before_state,
                         "dry_run 不得写状态文件（自验可重复跑）")
        # 同指纹多条同时到期 → 合并为一行 + [本批N条合并]
        self._write_buf([
            {"ts": _old_ts(), "subject": f"{s} #{i}", "body": "用量超阈值",
             "from_prefix": "[告警·聚合]", "rid": f"r-m{i}", "fp": fp}
            for i in range(3)
        ])
        self.sent.clear()
        notify.flush_warning_batch()
        self.assertEqual(len(self.sent), 1)
        b = self.sent[0]["body"]
        self.assertIn("[本批3条合并]", b)
        self.assertEqual(b.count("<hr>"), 0, "同指纹 3 条应合并为一行（无组间分隔也应有且仅一组）")

    # ── U9 flush 成功后 notified_repeat 快照 ───────────────────────
    def test_u9_snapshot_notified_after_send(self):
        s = "覆盖率不足 85%"
        fp = notify.warning_fingerprint(s, "低于阈值")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.state.write_text(json.dumps({
            fp: {"norm_subject": notify._norm_fp_text(s), "first_seen": now_str,
                 "window_start": now_str, "last_seen": now_str,
                 "repeat_count": 7, "notified_repeat": 1, "last_subject": s},
        }, ensure_ascii=False), encoding="utf-8")
        self._write_buf([{"ts": _old_ts(), "subject": s, "body": "低于阈值",
                          "from_prefix": "[告警·聚合]", "rid": "r-u9", "fp": fp}])
        r = notify.flush_warning_batch()
        self.assertTrue(r["sent_batch"])
        st = self._read_state()
        self.assertEqual(st[fp]["notified_repeat"], 7,
                         "发送成功后已通知基准应快照对齐 repeat_count")
        # 后续抑制判定以新基准起算：再来 1 次不穿透（burst=1 < max(2,14)）
        notify.defer_warning(s, "低于阈值")
        self.assertEqual(len(self._read_buf()), 0, "新基准下单次重复应被抑制")


    # ── U10 P1① buffer 追加失败 → 绝不登记指纹状态 ─────────────────
    def test_u10_buffer_append_failure_leaves_state_untouched(self):
        s = "baostock 限流封禁"
        orig_append = notify._append_jsonl
        with unittest.mock.patch.object(notify, "_append_jsonl", return_value=False):
            r = notify.defer_warning(s, "err")
        self.assertTrue(r, "返回值语义=True=已处理（本次尝试失败但已如实上报日志）")
        self.assertEqual(self._read_buf(), [], "追加失败时 buffer 必须无条目")
        self.assertEqual(self._read_state(), {},
                         "P1①：buffer 失败绝不能登记指纹状态（否则同源被压到窗过期）")
        # 恢复后同源告警正常入队并登记（无「幽灵静默窗」残留）
        notify._append_jsonl = orig_append
        notify.defer_warning(s, "err")
        self.assertEqual(len(self._read_buf()), 1)
        rec = next(iter(self._read_state().values()))
        self.assertEqual(rec["repeat_count"], 1)

    # ── U11 P1② 多进程并发 defer 同指纹 → 计数精确不丢 ─────────────
    def test_u11_concurrent_defer_no_lost_repeat_count(self):
        import multiprocessing as mp
        n_proc, subject = 16, "并发计数探针告警源"
        buf_p, lock_p = str(self.buf), str(self.lock)
        state_p, dlock_p = str(self.state), str(self.dedup_lock)
        ctx = mp.get_context("spawn")
        procs = [ctx.Process(target=_dedup_worker_proc,
                             args=(buf_p, lock_p, state_p, dlock_p, subject))
                 for _ in range(n_proc)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=30)
            self.assertEqual(p.exitcode, 0, f"子进程异常退出 exitcode={p.exitcode}")
        entries = self._read_buf()
        self.assertEqual(len(entries), 1, "同指纹并发只应首条入队")
        st = self._read_state()
        self.assertEqual(len(st), 1)
        rc = next(iter(st.values()))["repeat_count"]
        self.assertEqual(rc, n_proc,
                         f"P1②：{n_proc} 次并发 defer 计数必须精确（锁内增量推进），实际 {rc}")

    # ── U12 P1③ 快照保存失败 → due 条目保留重发（宁重发不吞）────────
    def test_u12_snapshot_save_failure_keeps_due_entries(self):
        s = "快照失败保留验证源"
        fp = notify.warning_fingerprint(s)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.state.write_text(json.dumps({
            fp: {"norm_subject": notify._norm_fp_text(s), "first_seen": now_str,
                 "window_start": now_str, "last_seen": now_str,
                 "repeat_count": 3, "notified_repeat": 1, "last_subject": s},
        }, ensure_ascii=False), encoding="utf-8")
        self._write_buf([{"ts": _old_ts(), "subject": s, "body": "x",
                          "from_prefix": "[告警·聚合]", "rid": "r-u12", "fp": fp}])
        with unittest.mock.patch.object(notify, "_save_warning_dedup_state",
                                        return_value=False):
            r = notify.flush_warning_batch()
        self.assertTrue(r["sent_batch"], "发送本身仍成功（渠道 mock 成功）")
        kept = self._read_buf()
        self.assertEqual([e["rid"] for e in kept], ["r-u12"],
                         "P1③：快照未落盘必须跳过清理，due 行留在 buffer 下轮重发")
        st = self._read_state()
        self.assertEqual(st[fp]["notified_repeat"], 1, "快照失败不得推进已通知基准")

    # ── U13 P2④ dry_run 恢复消息不触碰真实 state ───────────────────
    def test_u13_dry_run_recovery_never_touches_state(self):
        s = "dryrun 保护验证源"
        notify.defer_warning(s, "x")
        notify.defer_warning(s, "x")
        before = self.state.read_text(encoding="utf-8")
        before_buf = self.buf.read_bytes() if self.buf.exists() else b""
        notify.send(f"[恢复] {s} 08-26 15:00", "已恢复", dry_run=True)
        self.assertEqual(self.state.read_text(encoding="utf-8"), before,
                         "P2④：dry_run 全路径只读，恢复清零不得删状态")
        self.assertEqual(self.buf.read_bytes(), before_buf)

    # ── U14 P2⑤ 收严匹配：共享长前缀不误清 + 聚合 body 明细逐源清 ───
    def test_u14_strict_matching_and_body_detail_clearing(self):
        # 场景A：共享长前缀的两个不同源，恢复只清对应那一个
        a, b = "alpha-service 数据库连接失败", "alpha-service 数据库连接池耗尽"
        notify.defer_warning(a, "x")
        notify.defer_warning(b, "x")
        fpa, fpb = notify.warning_fingerprint(a), notify.warning_fingerprint(b)
        self.assertNotEqual(fpa, fpb, "身份标识/尾段不同的两源必须异指纹")
        notify.send("[恢复] alpha-service 数据库连接失败 08-26 15:00", "")
        st = self._read_state()
        self.assertNotIn(fpa, st, "恢复核心词应精确清掉同源指纹")
        self.assertIn(fpb, st, "仅共享长前缀的另一源不得被误清（收严为全串包含关系）")
        # 场景B：聚合恢复（真实模板 monitor_72h.sh L857/L859）subject=[72h恢复] N项异常恢复
        # MM-DD HH:MM（核心词 "#项异常恢复" 匹配不到任何单源）→ 靠 body 明细行逐源清零。
        c, d = "beta 任务超时监控", "gamma 磁盘水位"
        notify.defer_warning(c, "x")
        notify.defer_warning(d, "x")
        fpc, fpd = notify.warning_fingerprint(c), notify.warning_fingerprint(d)
        body = ("[恢复] beta 任务超时监控 异常关键词&lt;超时&gt; 已消失 "
                "(首次发现: 2026-08-26 10:00:00, 恢复时间: 2026-08-26 15:00:00)<br>"
                "[恢复] gamma 磁盘水位 异常关键词&lt;水位&gt; 已消失 "
                "(首次发现: 2026-08-26 11:00:00, 恢复时间: 2026-08-26 15:00:00)")
        notify.send("[72h恢复] 3项异常恢复 08-26 15:00", body)
        st2 = self._read_state()
        self.assertNotIn(fpc, st2, "body 明细行第 1 条应被枚举清零")
        self.assertNotIn(fpd, st2, "body 明细行第 2 条应被枚举清零")

    # ── U15 P2⑥ 身份标识 token 异源不互吞 + 计量数字差仍同源 ────────
    def test_u15_identity_tokens_are_distinct_sources(self):
        x, y = "ETF 净值偏离 sh510300", "ETF 净值偏离 sz159915"
        notify.defer_warning(x, "偏离 0.51%")
        notify.defer_warning(y, "偏离 0.88%")
        entries = self._read_buf()
        subjects = {e["subject"] for e in entries}
        self.assertEqual(len(entries), 2, "不同标的（sh510300 vs sz159915）异源各自入队")
        self.assertEqual(subjects, {x, y})
        self.assertEqual(len(self._read_state()), 2, "两源各持独立指纹窗口")
        # 对照平衡面：同标的仅计量数字差 → 仍判同源抑制（F6 取舍的双向验证）
        z = "ETF 净值偏离 sh510300"
        notify.defer_warning(z, "偏离 0.99%")
        self.assertEqual(len(self._read_buf()), 2, "同标的数字差应抑制不入队")
        st = self._read_state()
        self.assertEqual(st[notify.warning_fingerprint(x)]["repeat_count"], 2)


# ── 并发 worker（U11 用；模块顶层定义，spawn 子进程可 pickle）────────
def _dedup_worker_proc(buf_path, lock_path, state_path, dedup_lock_path, subject):
    """spawn 不继承主进程的模块 patch 与 mock：子进程内重新指路径 + mock 渠道，
    然后对同一 subject 各 defer 一次。"""
    sys.path.insert(0, str(Path(__file__).absolute().parent))
    import notify
    notify.WARNING_BUFFER_FILE = Path(buf_path)
    notify.WARNING_FLUSH_LOCK_FILE = Path(lock_path)
    notify.WARNING_DEDUP_STATE_FILE = Path(state_path)
    notify.WARNING_DEDUP_LOCK_FILE = Path(dedup_lock_path)
    try:
        notify.send_telegram = lambda *a, **k: True
        notify.send_feishu = lambda *a, **k: True
        notify._send_email = lambda *a, **k: True
        notify.defer_warning(subject, "并发计数")
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
