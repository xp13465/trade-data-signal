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

跑法：python3 scripts/test_notify_dedup.py   （可重复跑；全部 tmp 目录隔离）
"""
import json
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
        self.buf = Path(self.tmp) / "warning_buffer.jsonl"
        self.state = Path(self.tmp) / "warning_dedup_state.json"
        self.lock = Path(self.tmp) / "warning_buffer.flushlock"
        # 关键：读写目标全部指到临时目录，绝不碰生产 data/alerts/
        for attr, val in (("WARNING_BUFFER_FILE", self.buf),
                          ("WARNING_FLUSH_LOCK_FILE", self.lock),
                          ("WARNING_DEDUP_STATE_FILE", self.state)):
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
