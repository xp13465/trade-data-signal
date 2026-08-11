#!/usr/bin/env python3
"""test_notify_reply.py - notify.py 飞书引用回复(reply_to_message_id)透传单测。

用 unittest.mock 拦截 _feishu_http_post_json 捕获请求 payload，验证：
1) reply_to_message_id 非空时 body 含该字段（引用回复原消息）
2) reply_to_message_id 为空时 body 不含该字段（不影响现有普通发送）

跑法：cd scripts && python3 -m unittest test_notify_reply -v
"""
import json
import unittest
from unittest import mock

import notify  # scripts/ 下同目录直接 import


class NotifyReplyTest(unittest.TestCase):
    def setUp(self):
        # 假 token 绕过真实凭证/网络
        patcher = mock.patch("notify._get_tenant_access_token", return_value="fake-token")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _capture_body(self, reply_id):
        """调 _send_feishu_api，返回 (ok, 实际发给 _feishu_http_post_json 的 body dict)。"""
        captured = {}

        def fake_post(url, payload, headers, timeout=20):
            captured["body"] = json.loads(payload.decode("utf-8"))
            return {"code": 0}

        with mock.patch("notify._feishu_http_post_json", side_effect=fake_post):
            ok = notify._send_feishu_api("oc_test", "subject", "text",
                                         reply_to_message_id=reply_id)
        return ok, captured["body"]

    def test_reply_to_message_id_in_body(self):
        """reply_to_message_id 非空 -> body 含该字段，其余字段不受影响。"""
        ok, body = self._capture_body("om_abc123")
        self.assertTrue(ok)
        self.assertEqual(body["reply_to_message_id"], "om_abc123")
        self.assertEqual(body["receive_id"], "oc_test")
        self.assertEqual(body["msg_type"], "text")
        self.assertIn("text", json.loads(body["content"]))

    def test_no_reply_to_message_id(self):
        """reply_to_message_id 为空 -> body 不含该字段（现有普通发送不受影响）。"""
        ok, body = self._capture_body(None)
        self.assertTrue(ok)
        self.assertNotIn("reply_to_message_id", body)
        self.assertEqual(body["receive_id"], "oc_test")
        self.assertEqual(body["msg_type"], "text")

    def test_send_feishu_dry_run_reply(self):
        """send_feishu dry-run 应打印 reply_to_message_id（自验 body 透传链可用）。"""
        with mock.patch("notify.load_feishu_config",
                        return_value={"enabled": True, "mode": "app",
                                      "chat_ids": {"agent_done": "oc_test"}}), \
                mock.patch("sys.stderr") as stderr:
            ok = notify.send_feishu("subject", "body", chat_key="agent_done",
                                    dry_run=True, reply_to_message_id="om_abc123")
        self.assertTrue(ok)
        printed = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertIn("reply_to_message_id=om_abc123", printed)


if __name__ == "__main__":
    unittest.main()
