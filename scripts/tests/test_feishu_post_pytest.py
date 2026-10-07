# -*- coding: utf-8 -*-
"""#213 批2 薄包装: scripts/test_feishu_post.py → CI 闸门 ⑧(单一实现)。

原脚本形态 = unittest TestCase 集合(4 类: PostBuilderTest 5 / SendFeishuPostTest 4 /
ResolveChatKeyTests 6 / CheckSignalsPostTest 5 = 20 个用例)。
本批仅改了原脚本 SendFeishuPostTest.setUp 一处(补钉 load_feishu_config, 见该文件内注释),
堵住「CI 无 config/email.json ⇒ send_feishu 静默返 False」这一入 CI 的先决项;其余零改动。
"""
from _wrap_util import run_unittest_module

_MIN_TESTS = 20         # 原文件 def test_ 实测 20(5+4+6+5)


def test_feishu_post_wrapped():
    n = run_unittest_module("test_feishu_post", _MIN_TESTS)
    print(f"test_feishu_post: {n} 用例全绿, 零真实外发")