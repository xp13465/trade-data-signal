# -*- coding: utf-8 -*-
"""#213 批1 薄包装: scripts/test_notify_dedup.py → CI 闸门 ⑧(单一实现, 原文件零改动)。

原脚本形态 = unittest TestCase 集合(class DedupTests, U1~U15 = 15 个用例)。
打桩: send_telegram / send_feishu / _send_email 三渠道;U11 会 spawn 16 个子进程做
「跨进程去重」验证 —— 子进程是全新解释器, 不继承本包装的零外发陷阱;那些子进程在
worker 内自行 mock 渠道(既有设计), 故其零外发由「子进程自打桩」保证(见 _zero_outbound.py
文档「范围/局限」)。本包装的陷阱只覆盖**当前进程**内任何 mock 漏网的 urllib/smtplib 触达。
"""
from _wrap_util import run_unittest_module

_MIN_TESTS = 15         # 原文件 def test_ 实测 15(U1~U15)


def test_notify_dedup_wrapped():
    n = run_unittest_module("test_notify_dedup", _MIN_TESTS)
    print(f"test_notify_dedup: {n} 用例全绿, 当前进程零真实外发")