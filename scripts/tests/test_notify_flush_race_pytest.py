# -*- coding: utf-8 -*-
"""#213 批1 薄包装: scripts/test_notify_flush_race.py → CI 闸门 ⑧(单一实现, 原文件零改动)。

原脚本形态 = unittest TestCase 集合(class FlushRaceTests, t1~t6 = 6 个用例)。
t1 并发去重压测会 spawn 3 个子进程(各跑一轮 flush), 子进程不继承本包装的零外发陷阱
(其零外发由子进程内 `_patch_channels` 自打桩保证, 见 _zero_outbound.py「范围/局限」)。
"""
from _wrap_util import run_unittest_module

_MIN_TESTS = 6          # 原文件 def test_ 实测 6(t1~t6)


def test_notify_flush_race_wrapped():
    n = run_unittest_module("test_notify_flush_race", _MIN_TESTS)
    print(f"test_notify_flush_race: {n} 用例全绿, 当前进程零真实外发")