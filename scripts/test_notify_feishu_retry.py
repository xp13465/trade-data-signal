#!/usr/bin/env python3
"""notify.py 飞书发送重试 + dedup 语义自测（P1-1，2026-08-11 稳定性修复）。

用例：
- _send_feishu_api：网络瞬时错误（URLError）→ 3 次重试后失败；HTTP 5xx → 重试；HTTP 4xx → 不重试；
  飞书瞬时错误码（99999）→ 重试；第二次成功 → 重试后成功；确定性错误（230001）→ 不重试。
- dedup 语义：发送成功才 update_dedup（notify_agent_done 全渠道失败不更新；成功才更新）。

运行：python3 scripts/test_notify_feishu_retry.py
"""
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).absolute().parent
sys.path.insert(0, str(ROOT))

import notify  # noqa: E402


class SendFeishuRetryTests(unittest.TestCase):
    """_send_feishu_api 有限重试（签名不变）。"""

    def _call(self, side_effect):
        mock_fn = unittest.mock.Mock(side_effect=side_effect)
        with patch.object(notify, "_get_tenant_access_token", return_value="tok"), \
             patch.object(notify, "_feishu_http_post_json", mock_fn), \
             patch.object(notify.time, "sleep") as sleep_mock:
            ok = notify._send_feishu_api("oc_x", "测试", "正文")
        return ok, mock_fn, sleep_mock

    def test_network_error_retries_then_fails(self):
        """网络瞬时错误（URLError）→ 3 次重试后失败（不静默当成功）。"""
        def boom(*a, **k):
            raise urllib.error.URLError("connection reset")
        ok, fn, sleep_mock = self._call(boom)
        self.assertFalse(ok)
        self.assertEqual(fn.call_count, 3)  # 重试 3 次
        self.assertEqual(sleep_mock.call_count, 2)  # 退避 2 次

    def test_http_5xx_retries_http_4xx_no_retry(self):
        """HTTP 5xx 重试；HTTP 4xx 不重试（确定性错误）。"""
        def fivexx(*a, **k):
            raise urllib.error.HTTPError("/x", 503, "busy", {}, None)
        ok, fn, _ = self._call(fivexx)
        self.assertFalse(ok)
        self.assertEqual(fn.call_count, 3)

        def fourxx(*a, **k):
            raise urllib.error.HTTPError("/x", 400, "bad", {}, None)
        ok, fn, sleep_mock = self._call(fourxx)
        self.assertFalse(ok)
        self.assertEqual(fn.call_count, 1)  # 不重试
        self.assertEqual(sleep_mock.call_count, 0)

    def test_transient_code_retries_then_succeeds(self):
        """飞书瞬时错误码 99999 → 重试；第二次成功 → True。"""
        calls = {"n": 0}

        def flaky(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"code": 99999, "msg": "server busy"}
            return {"code": 0, "msg": "success"}
        ok, fn, sleep_mock = self._call(flaky)
        self.assertTrue(ok)
        self.assertEqual(fn.call_count, 2)
        self.assertEqual(sleep_mock.call_count, 1)

    def test_deterministic_code_no_retry(self):
        """确定性错误（230001 内容非法）→ 不重试直接失败。"""
        def bad(*a, **k):
            return {"code": 230001, "msg": "invalid message content"}
        ok, fn, sleep_mock = self._call(bad)
        self.assertFalse(ok)
        self.assertEqual(fn.call_count, 1)
        self.assertEqual(sleep_mock.call_count, 0)

    def test_signature_unchanged(self):
        """对外签名不变（hooks 抄送 agent 可能复用）：仍接受旧参数。"""
        with patch.object(notify, "_get_tenant_access_token", return_value="tok"), \
             patch.object(notify, "_feishu_http_post_json",
                          return_value={"code": 0, "msg": "success"}), \
             patch.object(notify.time, "sleep"):
            ok = notify._send_feishu_api("oc_x", "s", "t")
            ok2 = notify._send_feishu_api("oc_x", "s", "t",
                                          reply_to_message_id="om_x", msg_type="post",
                                          content={"zh_cn": {"title": "a", "content": []}})
        self.assertTrue(ok)
        self.assertTrue(ok2)


class DedupOnlyOnSuccessTests(unittest.TestCase):
    """P1-1：发送成功才 update_dedup（失败不标记，下次可重发）。"""

    def _make_dedup(self):
        td = tempfile.TemporaryDirectory()
        return Path(td.name) / "notify_dedup.json", td

    def test_agent_done_all_fail_no_dedup_update(self):
        """notify_agent_done 全渠道失败 → 不 update_dedup（下次可重发）。"""
        dedup_file, td = self._make_dedup()
        with patch.object(notify, "DEDUP_FILE", dedup_file), \
             patch.object(notify, "send",
                          return_value={"email": False, "telegram": False, "feishu": False}), \
             patch.object(notify, "update_dedup") as upd_mock:
            notify.notify_agent_done("ag_x", "摘要", dry_run=False)
        upd_mock.assert_not_called()
        td.cleanup()

    def test_agent_done_success_updates_dedup(self):
        """notify_agent_done 至少一渠道成功 → update_dedup（防 5min 内轰炸）。"""
        dedup_file, td = self._make_dedup()
        with patch.object(notify, "DEDUP_FILE", dedup_file), \
             patch.object(notify, "send",
                          return_value={"email": True, "telegram": False, "feishu": True}), \
             patch.object(notify, "update_dedup") as upd_mock:
            notify.notify_agent_done("ag_x", "摘要", dry_run=False)
        upd_mock.assert_called_once()
        td.cleanup()

    def test_cli_dedup_fail_no_update(self):
        """main --dedup-key：全渠道失败 → 不 update_dedup（下次可重发）。"""
        dedup_file, td = self._make_dedup()
        with patch.object(notify, "DEDUP_FILE", dedup_file), \
             patch.object(notify, "send",
                          return_value={"email": False, "telegram": False, "feishu": False}), \
             patch.object(notify, "update_dedup") as upd_mock:
            rc = notify.main(["主题", "正文", "--dedup-key", "k1", "--dedup-window", "1800"])
        self.assertEqual(rc, 0)
        upd_mock.assert_not_called()
        td.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
