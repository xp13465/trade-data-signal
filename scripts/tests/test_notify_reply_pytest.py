# -*- coding: utf-8 -*-
"""#213 批1 薄包装: scripts/test_notify_reply.py → CI 闸门 ⑧(单一实现, 原文件零改动)。

原脚本形态 = unittest TestCase 集合(class NotifyReplyTest, 3 个用例, mock
`_get_tenant_access_token` / `_feishu_http_post_json` 两层)。
本包装 = importlib 导入原模块 + 收全部用例跑, 断 用例数下限 + 全绿 + 零真实外发。
"""
from _wrap_util import run_unittest_module

_MIN_TESTS = 3          # 原文件 def test_ 实测 3(grep -c 'def test_'), 下限取实测值防用例被删静默


def test_notify_reply_wrapped():
    n = run_unittest_module("test_notify_reply", _MIN_TESTS)
    print(f"test_notify_reply: {n} 用例全绿, 零真实外发")