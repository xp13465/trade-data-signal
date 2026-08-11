#!/usr/bin/env python3
"""feishu_ws_listener 单测：收到回执功能。

用例：
1. test_send_receipt_posts_message_on_code_zero —— send_receipt 在 token 可用、API 返回 code=0
   时 POST im/v1/messages?receive_id_type=chat_id，payload 字段正确，返回 True。
2. test_send_receipt_posts_reply_to_message_id —— 传 message_id 时 body 含
   reply_to_message_id=该消息 id（飞书引用回复）。
3. test_send_receipt_returns_false_when_token_fails —— token 获取失败时 send_receipt
   返回 False 且不抛异常（best-effort 不阻塞）。
4. test_process_event_writes_inbox_and_sends_receipt —— process_event 落盘成功后调用
   send_receipt 向来源 chat_id 引用回复（传 msg.message_id），文案含需求原文前 40 字 +
   主控处理提示。

运行：python3 scripts/test_feishu_ws_listener.py（标准库 unittest，无外部依赖）
"""
import json
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


class ProcessEventReceiptTests(unittest.TestCase):
    def test_process_event_writes_inbox_and_sends_receipt(self):
        content = "需求：测试收到回执功能，验证落盘后触发回执"
        sent = []

        def fake_send(chat_id, text, message_id=None):
            sent.append((chat_id, text, message_id))
            return True

        with tempfile.TemporaryDirectory() as td:
            inbox = Path(td)
            with patch.object(fwl, "send_receipt", side_effect=fake_send) as send_mock:
                fn = fwl.process_event(fake_event(chat_id="oc_whitelist", content_text=content),
                                       whitelist=WHITELIST, prefixes=["需求:"], inbox_dir=inbox)
            self.assertIsNotNone(fn)
            files = list(inbox.glob("*.json"))
            self.assertEqual(len(files), 1)
            rec = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertEqual(rec["content"], content)
            self.assertEqual(rec["ts"], 1750000000)
            self.assertEqual(rec["ts_iso"],
                             datetime.fromtimestamp(1750000000).strftime("%Y-%m-%d %H:%M:%S"))
            send_mock.assert_called_once()
            self.assertEqual(len(sent), 1)
            chat_id, text, message_id = sent[0]
            self.assertEqual(chat_id, "oc_whitelist")
            self.assertEqual(message_id, "om_test123")  # 引用回复用户那条消息
            self.assertIn("已收到需求", text)
            self.assertIn(content[:40], text)  # 文案含需求原文前 40 字
            self.assertIn("主控 1 分钟内开始处理", text)

    def test_process_event_skips_non_request_message(self):
        """非白名单群且无需求前缀：不落盘、不触发回执。"""
        with tempfile.TemporaryDirectory() as td:
            inbox = Path(td)
            with patch.object(fwl, "send_receipt") as send_mock:
                fn = fwl.process_event(
                    fake_event(chat_id="oc_other", content_text="闲聊消息"),
                    whitelist=WHITELIST, prefixes=["需求:"], inbox_dir=inbox)
            self.assertIsNone(fn)
            self.assertEqual(list(inbox.glob("*.json")), [])
            send_mock.assert_not_called()


class CrossGroupForwardTests(unittest.TestCase):
    """跨群转发用例：告警群/报告群用户消息抄送开发群 + 防循环 + 去重。"""

    def _run(self, event, chat_map=CHAT_MAP, forwarded_ids=None,
             prefixes=("需求:",)):
        with tempfile.TemporaryDirectory() as td:
            inbox = Path(td)
            with patch.object(fwl, "send_receipt") as send_mock:
                if forwarded_ids is None:
                    forwarded_ids = set()
                fn = fwl.process_event(
                    event, whitelist=WHITELIST, prefixes=list(prefixes),
                    inbox_dir=inbox, chat_map=chat_map,
                    forwarded_ids=forwarded_ids,
                    dedup_path=Path(td) / "dedup.jsonl")
            return fn, send_mock

    def test_alert_user_message_forwarded_to_dev_group(self):
        """① 告警群用户消息→转发到开发群且带 [转自告警群]。无前缀用户问询也转发。"""
        content = "这个告警怎么回事？"
        fn, send_mock = self._run(
            fake_event(chat_id=ALERT_CHAT, content_text=content, sender_type="user",
                       message_id="om_alert1"))
        send_mock.assert_called_once()
        chat_id, text = send_mock.call_args[0]
        self.assertEqual(chat_id, DEV_CHAT)
        self.assertEqual(text, f"[转自告警群] {content}")
        # 无需求前缀且非白名单：不落盘（只转发）
        self.assertIsNone(fn)

    def test_report_user_message_forwarded_to_dev_group(self):
        """② 报告群用户消息→转发到开发群且带 [转自报告群]。"""
        content = "今天的报告结论是什么？"
        fn, send_mock = self._run(
            fake_event(chat_id=REPORT_CHAT, content_text=content, sender_type="user",
                       message_id="om_report1"))
        send_mock.assert_called_once()
        chat_id, text = send_mock.call_args[0]
        self.assertEqual(chat_id, DEV_CHAT)
        self.assertEqual(text, f"[转自报告群] {content}")
        self.assertIsNone(fn)

    def test_bot_own_message_not_forwarded(self):
        """③ bot 自己发的消息（sender_type=app）→不转发（防循环）。"""
        # bot 在告警群发告警/回执也会触发 receive_v1 事件，sender_type=app，绝不能转发成循环
        fn, send_mock = self._run(
            fake_event(chat_id=ALERT_CHAT, content_text="SEVERE 告警：xx 异常",
                       sender_type="app", message_id="om_bot1"))
        send_mock.assert_not_called()
        self.assertIsNone(fn)  # 无前缀 + 非白名单：也不落盘

    def test_sender_type_missing_not_forwarded(self):
        """sender_type 取不到（None）→宁可不转发（防循环优先）。"""
        fn, send_mock = self._run(
            fake_event(chat_id=REPORT_CHAT, content_text="无法判定发送者类型",
                       sender_type=None, message_id="om_nost"))
        send_mock.assert_not_called()

    def test_dev_group_message_not_forwarded(self):
        """④ 开发群消息→不转发（已在群里）。"""
        content = "需求：开发群里的新需求"
        fn, send_mock = self._run(
            fake_event(chat_id=DEV_CHAT, content_text=content, sender_type="user",
                       message_id="om_dev1"))
        send_mock.assert_called_once()
        chat_id, text = send_mock.call_args[0]
        self.assertEqual(chat_id, DEV_CHAT)  # 只回执，不转发
        self.assertNotIn("[转自", text)
        self.assertIn("已收到需求", text)

    def test_dedup_same_message_id_only_forward_once(self):
        """⑤ 去重：同一 message_id 二次事件→只转发一次。"""
        content = "重复推送也要只转发一次"
        dedup = set()
        fn1, send_mock1 = self._run(
            fake_event(chat_id=ALERT_CHAT, content_text=content, sender_type="user",
                       message_id="om_dup1"),
            forwarded_ids=dedup)
        # 第二次事件（SDK at-least-once 重推）：同一 message_id
        fn2, send_mock2 = self._run(
            fake_event(chat_id=ALERT_CHAT, content_text=content, sender_type="user",
                       message_id="om_dup1"),
            forwarded_ids=dedup)
        # 第一次转发 1 次；第二次去重跳过不转发
        send_mock1.assert_called_once()
        send_mock2.assert_not_called()
        self.assertEqual(len(dedup), 1)
        self.assertIn("om_dup1", dedup)


if __name__ == "__main__":
    unittest.main(verbosity=2)
