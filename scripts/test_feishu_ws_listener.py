#!/usr/bin/env python3
"""feishu_ws_listener 单测：收到回执功能。

用例：
1. test_send_receipt_posts_message_on_code_zero —— send_receipt 在 token 可用、API 返回 code=0
   时 POST im/v1/messages?receive_id_type=chat_id，payload 字段正确，返回 True。
2. test_send_receipt_returns_false_when_token_fails —— token 获取失败时 send_receipt
   返回 False 且不抛异常（best-effort 不阻塞）。
3. test_process_event_writes_inbox_and_sends_receipt —— process_event 落盘成功后调用
   send_receipt 向来源 chat_id 回执，文案含需求原文前 40 字 + 主控处理提示。

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


def fake_event(chat_id="oc_whitelist",
               content_text="需求：测试收到回执功能，验证落盘后触发回执",
               create_time="1750000000000", message_id="om_test123"):
    """构造 im.message.receive_v1 事件（白名单群，免前缀接收）。"""
    return SimpleNamespace(
        event=SimpleNamespace(
            message=SimpleNamespace(
                chat_id=chat_id,
                message_type="text",
                content=json.dumps({"text": content_text}, ensure_ascii=False),
                create_time=create_time,
                message_id=message_id,
            ),
            sender=SimpleNamespace(sender_id=SimpleNamespace(open_id="ou_test")),
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

        def fake_send(chat_id, text):
            sent.append((chat_id, text))
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
            chat_id, text = sent[0]
            self.assertEqual(chat_id, "oc_whitelist")
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
