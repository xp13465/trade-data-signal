#!/usr/bin/env python3
"""feishu_ws_listener 单测：收到回执 + 需求自动进待办（主控零轮询）。

用例：
SendReceiptTests —— send_receipt 原始发飞书 API（token/引用回复/failure best-effort）。
AutoTodoReceiptTests —— 需求自动进待办 + 即时回执：
  - summarize：压平换行/截断
  - append_todo_to_tasks：在 TASKS.md `#### 待办` 锚点后插入 `- [ ] (飞书 ...) <摘要>`
    （插在待办锚点后，非文件末尾乱插）；锚点缺失返回 False；写入失败不抛异常返回 False
  - send_requirement_receipt：notify.py 发开发群 agent_done（引用回复）+ 失败退化 send_receipt
  - _load_autodone_ids：载入 autodone jsonl + 历史 *.processed.json（旧 cron 已处理防重复）
ProcessEventAutoTodoTests —— process_event 全路径模拟：
  落盘 + TASKS 进待办 + 回执；异常路径（TASKS 写入失败）不中断监听；同 message_id 去重只处理一次
CrossGroupForwardTests —— 跨群转发：报告群用户消息→开发群；告警群用户消息**仅带需求前缀**
  才转发（无前缀计划任务执行告警/恢复类问询不抄送）；bot 自己（app）/sender_type 缺失不转
  发（防循环）；同 message_id 去重只转发一次。

运行：python3 scripts/test_feishu_ws_listener.py（标准库 unittest，无外部依赖）
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).absolute().parent
sys.path.insert(0, str(ROOT))

import feishu_ws_listener as fwl  # noqa: E402

WHITELIST = {"oc_98a49be023582358fa6cec24749907b5"}
ALERT_CHAT = "oc_7d8d3eb6b322ddeb6b8e3c53519fae7e"
REPORT_CHAT = "oc_edd9ac6dbe07303bed6f30d44b19604c"
DEV_CHAT = "oc_98a49be023582358fa6cec24749907b5"
CHAT_MAP = {"alert": ALERT_CHAT, "report": REPORT_CHAT, "agent_done": DEV_CHAT}


def fake_event(chat_id="oc_whitelist",
               content_text="需求：测试收到回执功能，验证落盘后触发回执",
               create_time="1750000000000", message_id="om_test123",
               sender_type=None):
    """构造 im.message.receive_v1 事件（白名单群，免前缀接收）。

    sender_type: user=人类用户 / app=应用(bot 自己)；None=事件里无 sender_type 字段。"""
    sender = SimpleNamespace(sender_id=SimpleNamespace(open_id="ou_test"))
    if sender_type is not None:
        sender.sender_type = sender_type
    return SimpleNamespace(
        event=SimpleNamespace(
            message=SimpleNamespace(
                chat_id=chat_id,
                message_type="text",
                content=json.dumps({"text": content_text}, ensure_ascii=False),
                create_time=create_time,
                message_id=message_id,
            ),
            sender=sender,
        )
    )


class FakeNotify:
    """notify.py 替身：记录 send_feishu 调用，按 result 返回成功/失败。"""

    def __init__(self, result=True):
        self.result = result
        self.calls = []

    def send_feishu(self, subject, body, chat_key=None,
                    reply_to_message_id=None, **kwargs):
        self.calls.append((subject, body, chat_key, reply_to_message_id))
        return self.result


class SendReceiptTests(unittest.TestCase):
    def test_send_receipt_posts_message_on_code_zero(self):
        calls = []

        def fake_post(url, payload, headers, timeout=5):
            calls.append((url, json.loads(payload), headers))
            return {"code": 0, "msg": "success"}

        text = "✅ 已收到需求「测试」，主控 1 分钟内开始处理"
        with patch.object(fwl, "_get_tenant_access_token", return_value="tok_test"), \
             patch.object(fwl, "_feishu_http_post_json", side_effect=fake_post) as post:
            ok = fwl.send_receipt("oc_123", text)
        self.assertTrue(ok)
        post.assert_called_once()
        self.assertEqual(len(calls), 1)
        url, body, headers = calls[0]
        self.assertIn("/open-apis/im/v1/messages", url)
        self.assertIn("receive_id_type=chat_id", url)
        self.assertEqual(body["receive_id"], "oc_123")
        self.assertEqual(body["msg_type"], "text")
        self.assertEqual(json.loads(body["content"])["text"], text)
        self.assertEqual(headers["Authorization"], "Bearer tok_test")

    def test_send_receipt_posts_reply_to_message_id(self):
        calls = []

        def fake_post(url, payload, headers, timeout=5):
            calls.append(json.loads(payload))
            return {"code": 0, "msg": "success"}

        with patch.object(fwl, "_get_tenant_access_token", return_value="tok_test"), \
             patch.object(fwl, "_feishu_http_post_json", side_effect=fake_post):
            ok = fwl.send_receipt("oc_123", "text", message_id="om_test123")
        self.assertTrue(ok)
        self.assertEqual(len(calls), 1)
        body = calls[0]
        self.assertEqual(body["receive_id"], "oc_123")
        self.assertEqual(body["reply_to_message_id"], "om_test123")  # 飞书引用回复

    def test_send_receipt_returns_false_when_token_fails(self):
        with patch.object(fwl, "_get_tenant_access_token", return_value=None):
            ok = fwl.send_receipt("oc_123", "text")
        self.assertFalse(ok)

    def test_send_receipt_returns_false_when_api_fails(self):
        def fake_post(url, payload, headers, timeout=5):
            return {"code": 99999, "msg": "mock error"}

        with patch.object(fwl, "_get_tenant_access_token", return_value="tok_test"), \
             patch.object(fwl, "_feishu_http_post_json", side_effect=fake_post):
            ok = fwl.send_receipt("oc_123", "text")
        self.assertFalse(ok)


class AutoTodoReceiptTests(unittest.TestCase):
    """需求自动进待办 + 即时回执（主控零轮询）。"""

    def test_summarize_collapses_whitespace_and_truncates(self):
        self.assertEqual(fwl.summarize("  需求：\n做  X功能  "), "需求： 做 X功能")
        long = "字" * 200
        s = fwl.summarize(long, limit=80)
        self.assertEqual(len(s), 80)
        self.assertTrue(s.endswith("…"))

    def test_append_todo_inserts_after_anchor(self):
        """在 `#### 待办` 锚点后插入 `- [ ] (飞书 ...) <摘要>`（非文件末尾乱插），
        其余行（含超长行）原样保留。"""
        with tempfile.TemporaryDirectory() as td:
            tasks = Path(td) / "TASKS.md"
            huge = "X" * 5000  # 模拟超长行
            tasks.write_text(
                "## 会话状态\n\n#### 待办\n- 阶段1: 已有\n- 阶段2: 已有\n\n## 其他\n"
                f"{huge}\n",
                encoding="utf-8")
            with patch.object(fwl, "TASKS_PATH", tasks):
                ok = fwl.append_todo_to_tasks("需求：做X功能", 1750000000)
            self.assertTrue(ok)
            lines = tasks.read_text(encoding="utf-8").splitlines()
        ts_iso = datetime.fromtimestamp(1750000000).strftime("%Y-%m-%d %H:%M")
        self.assertEqual(lines[3], f"- [ ] (飞书 {ts_iso}) 需求：做X功能")  # 锚点(第2行)后第一项
        self.assertEqual(lines[2], "#### 待办")
        self.assertIn(huge, lines)  # 超长行原样保留
        self.assertEqual(lines[-1], huge)  # 文件末尾仍是超长行，未乱插

    def test_append_todo_returns_false_without_anchor(self):
        """找不到 `#### 待办` 锚点：返回 False，文件不变（不往末尾乱插）。"""
        with tempfile.TemporaryDirectory() as td:
            tasks = Path(td) / "TASKS.md"
            tasks.write_text("## 无待办锚点\n随便写写\n", encoding="utf-8")
            with patch.object(fwl, "TASKS_PATH", tasks):
                ok = fwl.append_todo_to_tasks("需求：X", 1750000000)
            self.assertFalse(ok)
            self.assertNotIn("(飞书 ", tasks.read_text(encoding="utf-8"))

    def test_append_todo_returns_false_when_missing_file(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(fwl, "TASKS_PATH", Path(td) / "missing" / "TASKS.md"):
                ok = fwl.append_todo_to_tasks("需求：X", 1750000000)
        self.assertFalse(ok)

    def test_append_todo_never_raises_on_write_failure(self):
        """写入失败（只读目录）→ 返回 False 不抛异常（异常保护，不中断监听）。"""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            tasks = d / "TASKS.md"
            tasks.write_text("#### 待办\n- 已有\n", encoding="utf-8")
            os.chmod(d, 0o555)
            try:
                with patch.object(fwl, "TASKS_PATH", tasks):
                    ok = fwl.append_todo_to_tasks("需求：X", 1750000000)
            finally:
                os.chmod(d, 0o755)
        self.assertFalse(ok)

    def test_send_requirement_receipt_uses_notify(self):
        """回执走 notify.py 发开发群 agent_done + 引用回复用户消息；不回退 send_receipt。"""
        fake = FakeNotify(result=True)
        with patch.object(fwl, "_get_notify", return_value=fake), \
             patch.object(fwl, "send_receipt") as fallback:
            ok = fwl.send_requirement_receipt("oc_dev", "摘要ABC", "om_x")
        self.assertTrue(ok)
        self.assertEqual(len(fake.calls), 1)
        subject, body, chat_key, rmid = fake.calls[0]
        self.assertEqual(chat_key, "agent_done")
        self.assertEqual(rmid, "om_x")  # 引用回复用户那条消息
        self.assertIn("✅ 已收到你的需求：摘要ABC", body)
        self.assertIn("已纳入待办，主控将跟进处理", body)
        fallback.assert_not_called()

    def test_send_requirement_receipt_falls_back_when_notify_fails(self):
        """notify 发送失败 → 退化 send_receipt 直接回用户所在群（双保险）。"""
        fake = FakeNotify(result=False)
        sent = []

        def fs(chat_id, text, message_id=None):
            sent.append((chat_id, text, message_id))
            return True

        with patch.object(fwl, "_get_notify", return_value=fake), \
             patch.object(fwl, "send_receipt", side_effect=fs):
            ok = fwl.send_requirement_receipt("oc_dev", "摘要", "om_x")
        self.assertTrue(ok)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], "oc_dev")
        self.assertEqual(sent[0][2], "om_x")
        self.assertIn("已收到你的需求：摘要", sent[0][1])

    def test_send_requirement_receipt_falls_back_when_notify_import_fails(self):
        """notify import 失败（_get_notify 返回 None）→ 退化 send_receipt，不中断。"""
        sent = []

        def fs(chat_id, text, message_id=None):
            sent.append((chat_id, text, message_id))
            return True

        with patch.object(fwl, "_get_notify", return_value=None), \
             patch.object(fwl, "send_receipt", side_effect=fs):
            ok = fwl.send_requirement_receipt("oc_dev", "摘要", "om_x")
        self.assertTrue(ok)
        self.assertEqual(len(sent), 1)

    def test_load_autodone_ids_reads_processed_json(self):
        """启动载入历史 *.processed.json（旧 cron 已整理过的消息防重复处理）。"""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "111-om_old1.processed.json").write_text(
                json.dumps({"message_id": "om_old1"}), encoding="utf-8")
            (d / "222-om_old2.processed.json").write_text("not json",
                                                          encoding="utf-8")  # 文件名兜底取 mid
            with patch.object(fwl, "AUTODONE_DEDUP_PATH", d / "none.jsonl"):
                ids = fwl._load_autodone_ids(d)
        self.assertIn("om_old1", ids)
        self.assertIn("om_old2", ids)
        self.assertNotIn("111", ids)


class ProcessEventAutoTodoTests(unittest.TestCase):
    """process_event 全路径模拟：落盘 + 进 TASKS + 回执（不真发飞书/不真改真 TASKS.md）。"""

    def test_process_event_writes_inbox_and_autodone(self):
        content = "需求：测试收到回执功能，验证落盘后触发回执"
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            inbox = d / "inbox"
            tasks = d / "TASKS.md"
            tasks.write_text("#### 待办\n- 阶段1: 已有\n\n## 其他\n", encoding="utf-8")
            autodone_path = d / "autodone.jsonl"
            with patch.object(fwl, "TASKS_PATH", tasks), \
                 patch.object(fwl, "AUTODONE_DEDUP_PATH", autodone_path), \
                 patch.object(fwl, "send_requirement_receipt") as receipt_mock:
                fn = fwl.process_event(
                    fake_event(chat_id="oc_whitelist", content_text=content),
                    whitelist=WHITELIST, prefixes=["需求:"], inbox_dir=inbox)
            self.assertIsNotNone(fn)
            # ① 落盘格式不变（<ts>-<mid>.json）
            files = list(inbox.glob("*.json"))
            self.assertEqual(len(files), 1)
            rec = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertEqual(rec["content"], content)
            self.assertEqual(rec["ts"], 1750000000)
            self.assertEqual(rec["ts_iso"],
                             datetime.fromtimestamp(1750000000).strftime("%Y-%m-%d %H:%M:%S"))
            # ② 进 TASKS：插在 `#### 待办` 锚点后，非文件末尾乱插
            tasks_text = tasks.read_text(encoding="utf-8")
            ts_iso = datetime.fromtimestamp(1750000000).strftime("%Y-%m-%d %H:%M")
            self.assertIn(f"#### 待办\n- [ ] (飞书 {ts_iso}) 需求：测试收到回执功能，验证落盘后触发回执\n",
                          tasks_text)
            self.assertLess(tasks_text.index("(飞书 "), tasks_text.index("## 其他"))
            # ③ 回执：调 send_requirement_receipt（chat_id + 摘要 + 引用回复 message_id）
            receipt_mock.assert_called_once()
            args, kwargs = receipt_mock.call_args
            chat_id, excerpt = args
            self.assertEqual(chat_id, "oc_whitelist")
            self.assertEqual(kwargs["message_id"], "om_test123")
            self.assertIn("需求：测试收到回执功能", excerpt)
            # ④ 去重 jsonl 已标记
            self.assertTrue(autodone_path.exists())
            self.assertIn("om_test123",
                          json.loads(autodone_path.read_text(encoding="utf-8"))["message_id"])

    def test_process_event_continues_when_todo_append_fails(self):
        """异常保护：TASKS.md 追加失败（append 返回 False）不中断监听，落盘+回执照常。"""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            inbox = d / "inbox"
            with patch.object(fwl, "append_todo_to_tasks", return_value=False), \
                 patch.object(fwl, "send_requirement_receipt") as receipt_mock, \
                 patch.object(fwl, "AUTODONE_DEDUP_PATH", d / "autodone.jsonl"):
                fn = fwl.process_event(fake_event(chat_id="oc_whitelist",
                                                  content_text="需求：X",
                                                  message_id="om_err1"),
                                       whitelist=WHITELIST, prefixes=["需求:"], inbox_dir=inbox)
            self.assertIsNotNone(fn)
            self.assertEqual(len(list(inbox.glob("*.json"))), 1)
            receipt_mock.assert_called_once()

    def test_process_event_continues_when_todo_file_unwritable(self):
        """异常保护：TASKS.md 只读（真实写入失败）→ append 返回 False，监听继续（仍落盘+回执）。"""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            ro_dir = d / "ro"
            ro_dir.mkdir()
            tasks = ro_dir / "TASKS.md"
            tasks.write_text("#### 待办\n- 已有\n", encoding="utf-8")
            inbox = d / "inbox"  # 可写
            os.chmod(ro_dir, 0o555)
            try:
                with patch.object(fwl, "TASKS_PATH", tasks), \
                     patch.object(fwl, "AUTODONE_DEDUP_PATH", d / "autodone.jsonl"), \
                     patch.object(fwl, "send_requirement_receipt") as receipt_mock:
                    fn = fwl.process_event(fake_event(chat_id="oc_whitelist",
                                                      content_text="需求：X",
                                                      message_id="om_err2"),
                                           whitelist=WHITELIST, prefixes=["需求:"], inbox_dir=inbox)
            finally:
                os.chmod(ro_dir, 0o755)
            self.assertIsNotNone(fn)  # 不中断监听
            self.assertEqual(len(list(inbox.glob("*.json"))), 1)
            receipt_mock.assert_called_once()

    def test_process_event_dedup_same_message_id(self):
        """防重复：同一 message_id 二次事件 → 只进一次 TASKS、只回执一次（仍落盘幂等覆盖）。"""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            tasks = d / "TASKS.md"
            tasks.write_text("#### 待办\n- 已有\n", encoding="utf-8")
            autodone_path = d / "autodone.jsonl"
            dedup = set()
            with patch.object(fwl, "TASKS_PATH", tasks), \
                 patch.object(fwl, "AUTODONE_DEDUP_PATH", autodone_path), \
                 patch.object(fwl, "send_requirement_receipt") as receipt_mock:
                fn1 = fwl.process_event(fake_event(chat_id="oc_whitelist",
                                                   content_text="需求：A",
                                                   message_id="om_dupA"),
                                        whitelist=WHITELIST, prefixes=["需求:"],
                                        inbox_dir=d / "i1", autodone_ids=dedup)
                fn2 = fwl.process_event(fake_event(chat_id="oc_whitelist",
                                                   content_text="需求：A",
                                                   message_id="om_dupA"),
                                        whitelist=WHITELIST, prefixes=["需求:"],
                                        inbox_dir=d / "i2", autodone_ids=dedup)
            self.assertIsNotNone(fn1)
            self.assertIsNotNone(fn2)  # 仍落盘
            receipt_mock.assert_called_once()  # 只回执一次
            tasks_text = tasks.read_text(encoding="utf-8")
            self.assertEqual(tasks_text.count("- [ ] (飞书 "), 1)  # 只进一次待办

    def test_process_event_skips_non_request_message(self):
        """非白名单群且无需求前缀：不落盘、不触发自动处理。"""
        with tempfile.TemporaryDirectory() as td:
            inbox = Path(td) / "inbox"
            with patch.object(fwl, "append_todo_to_tasks") as todo_mock, \
                 patch.object(fwl, "send_requirement_receipt") as receipt_mock:
                fn = fwl.process_event(
                    fake_event(chat_id="oc_other", content_text="闲聊消息"),
                    whitelist=WHITELIST, prefixes=["需求:"], inbox_dir=inbox)
            self.assertIsNone(fn)
            self.assertEqual(list(inbox.glob("*.json")), [])
            todo_mock.assert_not_called()
            receipt_mock.assert_not_called()


class CrossGroupForwardTests(unittest.TestCase):
    """跨群转发用例：告警群/报告群用户消息抄送开发群 + 防循环 + 去重。

    转发走 fwl.send_receipt；需求自动进待办/回执走 fwl.append_todo_to_tasks /
    fwl.send_requirement_receipt（已打桩，不真改 TASKS/不真发飞书）。"""

    def _run(self, event, chat_map=CHAT_MAP, forwarded_ids=None,
             prefixes=("需求:",)):
        with tempfile.TemporaryDirectory() as td:
            inbox = Path(td)
            with patch.object(fwl, "send_receipt") as send_mock, \
                 patch.object(fwl, "append_todo_to_tasks") as todo_mock, \
                 patch.object(fwl, "send_requirement_receipt") as receipt_mock, \
                 patch.object(fwl, "AUTODONE_DEDUP_PATH", Path(td) / "autodone.jsonl"):
                if forwarded_ids is None:
                    forwarded_ids = set()
                fn = fwl.process_event(
                    event, whitelist=WHITELIST, prefixes=list(prefixes),
                    inbox_dir=inbox, chat_map=chat_map,
                    forwarded_ids=forwarded_ids,
                    dedup_path=Path(td) / "dedup.jsonl")
            return fn, send_mock, todo_mock, receipt_mock

    def test_alert_user_message_without_prefix_not_forwarded(self):
        """① 告警群用户消息无需求前缀→不转发开发群（计划任务执行告警/恢复类问询留运维群）。"""
        content = "这个告警怎么回事？"
        fn, send_mock, todo_mock, receipt_mock = self._run(
            fake_event(chat_id=ALERT_CHAT, content_text=content, sender_type="user",
                       message_id="om_alert1"))
        send_mock.assert_not_called()  # 不转发开发群
        todo_mock.assert_not_called()  # 非合法需求不进待办
        receipt_mock.assert_not_called()
        self.assertIsNone(fn)

    def test_alert_user_message_with_demand_prefix_forwarded(self):
        """② 告警群用户消息带"需求:"前缀→转发到开发群且带 [转自告警群]，同时进待办+回执。"""
        content = "需求：告警群里提的新开发需求"
        fn, send_mock, todo_mock, receipt_mock = self._run(
            fake_event(chat_id=ALERT_CHAT, content_text=content, sender_type="user",
                       message_id="om_alert2"))
        # 转发 1 次到开发群（send_receipt）
        send_mock.assert_called_once()
        forward_calls = [c for c in send_mock.call_args_list
                         if c.args[0] == DEV_CHAT and c.args[1].startswith("[转自告警群]")]
        self.assertEqual(len(forward_calls), 1)
        self.assertEqual(forward_calls[0].args[1], f"[转自告警群] {content}")
        # 带需求前缀：落盘为合法需求（非 None）+ 自动进待办 + 即时回执
        self.assertIsNotNone(fn)
        todo_mock.assert_called_once()
        receipt_mock.assert_called_once()

    def test_report_user_message_forwarded_to_dev_group(self):
        """③ 报告群用户消息→转发到开发群且带 [转自报告群]。"""
        content = "今天的报告结论是什么？"
        fn, send_mock, todo_mock, receipt_mock = self._run(
            fake_event(chat_id=REPORT_CHAT, content_text=content, sender_type="user",
                       message_id="om_report1"))
        send_mock.assert_called_once()
        chat_id, text = send_mock.call_args[0]
        self.assertEqual(chat_id, DEV_CHAT)
        self.assertEqual(text, f"[转自报告群] {content}")
        self.assertIsNone(fn)  # 无需求前缀且非白名单：不进待办不回执

    def test_bot_own_message_not_forwarded(self):
        """④ bot 自己发的消息（sender_type=app）→不转发（防循环）。"""
        # bot 在告警群发告警/回执也会触发 receive_v1 事件，sender_type=app，绝不能转发成循环
        fn, send_mock, todo_mock, receipt_mock = self._run(
            fake_event(chat_id=ALERT_CHAT, content_text="SEVERE 告警：xx 异常",
                       sender_type="app", message_id="om_bot1"))
        send_mock.assert_not_called()
        todo_mock.assert_not_called()
        receipt_mock.assert_not_called()
        self.assertIsNone(fn)  # 无前缀 + 非白名单：也不落盘

    def test_sender_type_missing_not_forwarded(self):
        """sender_type 取不到（None）→宁可不转发（防循环优先）。"""
        fn, send_mock, todo_mock, receipt_mock = self._run(
            fake_event(chat_id=REPORT_CHAT, content_text="无法判定发送者类型",
                       sender_type=None, message_id="om_nost"))
        send_mock.assert_not_called()
        todo_mock.assert_not_called()
        receipt_mock.assert_not_called()

    def test_dev_group_message_not_forwarded(self):
        """⑤ 开发群消息→不转发（已在群里），但自动进待办 + 即时回执。"""
        content = "需求：开发群里的新需求"
        fn, send_mock, todo_mock, receipt_mock = self._run(
            fake_event(chat_id=DEV_CHAT, content_text=content, sender_type="user",
                       message_id="om_dev1"))
        send_mock.assert_not_called()  # 开发群自身不转发
        receipt_mock.assert_called_once()  # 只回执
        args, kwargs = receipt_mock.call_args
        chat_id, excerpt = args
        self.assertEqual(chat_id, DEV_CHAT)
        self.assertEqual(kwargs["message_id"], "om_dev1")
        self.assertIn("开发群里的新需求", excerpt)
        todo_mock.assert_called_once()
        self.assertIsNotNone(fn)

    def test_dedup_same_message_id_only_forward_once(self):
        """⑥ 去重：同一 message_id 二次事件→只转发一次。（用报告群：无条件转发，测去重语义）"""
        content = "重复推送也要只转发一次"
        dedup = set()
        fn1, send_mock1, _, _ = self._run(
            fake_event(chat_id=REPORT_CHAT, content_text=content, sender_type="user",
                       message_id="om_dup1"),
            forwarded_ids=dedup)
        # 第二次事件（SDK at-least-once 重推）：同一 message_id
        fn2, send_mock2, _, _ = self._run(
            fake_event(chat_id=REPORT_CHAT, content_text=content, sender_type="user",
                       message_id="om_dup1"),
            forwarded_ids=dedup)
        # 第一次转发 1 次；第二次去重跳过不转发
        send_mock1.assert_called_once()
        send_mock2.assert_not_called()
        self.assertEqual(len(dedup), 1)
        self.assertIn("om_dup1", dedup)


if __name__ == "__main__":
    unittest.main(verbosity=2)
