# -*- coding: utf-8 -*-
"""#213 批1 薄包装: scripts/test_132_notify_tier_dedup.py → CI 闸门 ⑧(单一实现, 原文件零改动)。

原脚本形态 = unittest TestCase 集合(class TierDedupTests, 13 个用例)。
本包装 = importlib 导入原模块 + 收全部用例跑, 断 用例数下限 + 全绿 + 零真实外发。
"""
from _wrap_util import run_unittest_module

_MIN_TESTS = 13         # 原文件 def test_ 实测 13


def test_132_notify_tier_dedup_wrapped():
    n = run_unittest_module("test_132_notify_tier_dedup", _MIN_TESTS)
    print(f"test_132_notify_tier_dedup: {n} 用例全绿, 零真实外发")