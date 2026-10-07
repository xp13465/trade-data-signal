# -*- coding: utf-8 -*-
"""#213 批1 薄包装: scripts/test_notify_feishu_retry.py → CI 闸门 ⑧(单一实现, 原文件零改动)。

原脚本形态 = unittest TestCase 集合(SendFeishuRetryTests 5 + DedupOnlyOnSuccessTests 3 = 8)。
本包装 = importlib 导入原模块 + 收全部用例跑, 断 用例数下限 + 全绿 + 零真实外发。
"""
from _wrap_util import run_unittest_module

_MIN_TESTS = 8          # 原文件 def test_ 实测 8(5+3)


def test_notify_feishu_retry_wrapped():
    n = run_unittest_module("test_notify_feishu_retry", _MIN_TESTS)
    print(f"test_notify_feishu_retry: {n} 用例全绿, 零真实外发")