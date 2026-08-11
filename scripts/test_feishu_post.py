#!/usr/bin/env python3
"""test_feishu_post.py - notify.py 飞书 post 富文本 + 报告群信号消息格式化单测。

覆盖（2026-08-11 飞书格式模板任务）：
1) post_text / build_feishu_post 构建器（彩色标题/表头/色名过滤/a 链接）
2) send_feishu(feishu_post=...) report 群 -> msg_type=post（捕获请求 body 验证 content 结构）
3) 3 群差异化：alert/agent_done 群忽略 feishu_post 保持 text（不破坏现有格式）
4) 无 feishu_post 时仍走 text（回归，现有 alert 消息不受影响）
5) check_signals.build_feishu_post 买卖分组（买绿/卖红/持有灰）+ 触发条件截断
6) check_signals.build_email 邮件 HTML 含 @media (max-width:600px) 移动端适配

跑法：cd scripts && python3 -m unittest test_feishu_post -v
"""
import json
import unittest
from unittest import mock

import notify
import check_signals  # noqa: F401  （含 build_feishu_post / build_email）

SAMPLE_SIGNALS = [
    {"index_id": "sh000300", "signal": "buy",
     "reason": "RSI 上穿 30（超卖反弹启动），这是一个特别长的触发条件说明用来验证截断行为是否正常"},
    {"index_id": "sh000905", "signal": "sell",
     "reason": "20 日高点回落 5% + MA60 多头过滤 + MACD 死叉确认，止盈减仓提示"},
    {"index_id": "sh000016", "signal": "band_hold", "reason": "当前处于波段持有状态"},
]
NAME_MAP = {"sh000300": "沪深300", "sh000905": "中证500", "sh000016": "上证50"}


class PostBuilderTest(unittest.TestCase):
    def test_post_text_no_style_color(self):
        """post text 标签不带 style.color（飞书 im/v1/messages 不支持，实测 230001）。"""
        tag = notify.post_text("买入")
        self.assertEqual(tag["tag"], "text")
        self.assertEqual(tag["text"], "买入")
        self.assertNotIn("style", tag)

    def test_post_md_bold_header(self):
        """md 标签：分组表头用 **加粗**（飞书支持 md 渲染）。"""
        tag = notify.post_md("🟢 **买入信号**（主买1 辅买1）")
        self.assertEqual(tag["tag"], "md")
        self.assertIn("**", tag["text"])

    def test_post_text_link(self):
        tag = notify.post_text("链接", href="https://ss.fx8.store")
        self.assertEqual(tag["tag"], "a")
        self.assertEqual(tag["href"], "https://ss.fx8.store")

    def test_post_text_un_escape(self):
        tag = notify.post_text("a\nb", un_escape=True)
        self.assertTrue(tag["un_escape"])

    def test_build_feishu_post_structure(self):
        post = notify.build_feishu_post("标题", [[notify.post_text("a")]])
        self.assertIn("zh_cn", post)
        self.assertEqual(post["zh_cn"]["title"], "标题")
        self.assertEqual(post["zh_cn"]["content"][0][0]["text"], "a")


class SendFeishuPostTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("notify._get_tenant_access_token", return_value="fake-token")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _send_with_post(self, chat_key):
        """调 send_feishu(feishu_post=...)，捕获实际发给 _feishu_http_post_json 的 body。"""
        captured = {}
        post = notify.build_feishu_post(
            "测试标题",
            [[notify.post_md("🟢 **买入信号**")],
             [notify.post_text("🟢 主买 沪深300 | RSI 上穿 30")]],
        )

        def fake_post(url, payload, headers, timeout=20):
            captured["body"] = json.loads(payload.decode("utf-8"))
            return {"code": 0}

        with mock.patch("notify._feishu_http_post_json", side_effect=fake_post):
            ok = notify.send_feishu("subject", "<html>body</html>",
                                    chat_key=chat_key, feishu_post=post)
        return ok, captured["body"]

    def test_report_group_uses_post(self):
        """report 群 + feishu_post -> msg_type=post，content 是 post 富文本 JSON 串。"""
        ok, body = self._send_with_post("report")
        self.assertTrue(ok)
        self.assertEqual(body["msg_type"], "post")
        content = json.loads(body["content"])
        # im/v1/messages app 模式：content 直接是 {"zh_cn": ...}（无 post 外层包，
        # 加 {"post": ...} 外层会报 230001 invalid message content，实测确定）
        self.assertNotIn("post", content)
        self.assertIn("zh_cn", content)
        self.assertEqual(content["zh_cn"]["title"], "测试标题")
        self.assertEqual(content["zh_cn"]["content"][0][0]["tag"], "md")  # 表头 md 加粗

    def test_alert_group_keeps_text(self):
        """alert 群忽略 feishu_post 保持 text（3 群差异化，不破坏告警群格式）。"""
        ok, body = self._send_with_post("alert")
        self.assertTrue(ok)
        self.assertEqual(body["msg_type"], "text")
        content = json.loads(body["content"])
        self.assertIn("text", content)  # 非 post

    def test_no_post_keeps_text(self):
        """无 feishu_post -> text（现有 alert/agent_done 普通发送回归）。"""
        captured = {}

        def fake_post(url, payload, headers, timeout=20):
            captured["body"] = json.loads(payload.decode("utf-8"))
            return {"code": 0}

        with mock.patch("notify._feishu_http_post_json", side_effect=fake_post):
            ok = notify.send_feishu("subject", "<table><tr><td>a</td><td>b</td></tr></table>",
                                    chat_key="agent_done")
        self.assertTrue(ok)
        self.assertEqual(captured["body"]["msg_type"], "text")
        content = json.loads(captured["body"]["content"])
        self.assertIn("text", content)
        # _html_to_text 拍平表格为纯文本（表变 | 分隔）
        self.assertIn("a", content["text"])
        self.assertIn("b", content["text"])

    def test_post_webhook_mode(self):
        """webhook 模式 post：content 是对象非 JSON 字符串 + post 外层包。"""
        post = notify.build_feishu_post("标题", [[notify.post_text("x")]])
        captured = {}

        def fake_post(url, payload, headers, timeout=20):
            captured["payload"] = json.loads(payload.decode("utf-8"))
            return {"code": 0}

        with mock.patch("notify.load_feishu_config",
                        return_value={"enabled": True, "mode": "webhook",
                                      "chat_ids": {"report": "oc_test"},
                                      "webhook_urls": {"report": "https://example.com/hook"}}), \
                mock.patch("notify._feishu_http_post_json", side_effect=fake_post):
            ok = notify.send_feishu("subject", "body", chat_key="report", feishu_post=post)
        self.assertTrue(ok)
        self.assertEqual(captured["payload"]["msg_type"], "post")
        self.assertIsInstance(captured["payload"]["content"], dict)  # webhook 是对象
        self.assertEqual(captured["payload"]["content"]["post"]["zh_cn"]["title"], "标题")


class CheckSignalsPostTest(unittest.TestCase):
    def test_build_feishu_post_groups_and_colors(self):
        """买卖分组（彩色 emoji 前缀 买绿/卖红/持有灰）+ 分组表头 md 加粗 + 触发条件截断。"""
        post = check_signals.build_feishu_post(
            "[买卖点信号] 20260811 主买×1 | 卖×1 | 持有×1", SAMPLE_SIGNALS, NAME_MAP)
        lines = post["zh_cn"]["content"]
        texts = [" | ".join(t.get("text", "") for t in line) for line in lines]
        joined = "\n".join(texts)
        self.assertIn("🟢 **买入信号**", joined)   # md 加粗分组表头 + 绿 emoji
        self.assertIn("🔴 **卖出信号**", joined)   # 卖红
        self.assertIn("⚪ **波段持有**", joined)   # 持有灰
        self.assertIn("🟢 主买 沪深300", joined)   # 买行绿 emoji 前缀
        self.assertIn("🔴 卖 中证500", joined)     # 卖行红 emoji 前缀
        # 触发条件截断（FEISHU_POST_REASON_MAX=32）：长 reason 以 … 结尾
        buy_row = [t["text"] for t in lines[1]]
        self.assertTrue(any(t.endswith("…") for t in buy_row))
        # post text 标签不携带 style（飞书不支持，实测 230001）
        for line in lines:
            for t in line:
                self.assertNotIn("style", t)

    def test_build_email_has_mobile_media_query(self):
        """邮件 HTML 含 @media (max-width:600px) 移动端适配（修手机预览错位）。"""
        _, body = check_signals.build_email("20260811", SAMPLE_SIGNALS, NAME_MAP)
        self.assertIn("@media (max-width:600px)", body)
        self.assertIn("td{display:block", body)


if __name__ == "__main__":
    unittest.main()
