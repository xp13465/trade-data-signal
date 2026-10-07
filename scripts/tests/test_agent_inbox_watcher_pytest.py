# -*- coding: utf-8 -*-
"""#213 批1 薄包装: scripts/test_agent_inbox_watcher.py → CI 闸门 ⑧(单一实现, 原文件零改动)。

原脚本形态 = unittest TestCase 集合(LockTest 3 / SyncRefsTest 4 / VerdictReadTest 5 /
RetryCountTest 2 / CleanupRefTest 1 = 15 个用例)。

⚠️ 硬前置: 原脚本在**模块级** `os.environ["OR_API_KEY"]="test-key-0000"`(L21)后
才 `import agent_inbox_watcher`(L24) —— 被 import 的模块缺 OR_API_KEY 会
`SystemExit("OR_API_KEY required")`(agent_inbox_watcher.py:37-38)。
本包装用 setdefault 再兜一层(即使原文件的设置被后移也不炸), 且 `_wrap_util` 收尾
**整体还原 os.environ**, 防该 key 泄漏毒化同会话其余用例。
"""
import os

from _wrap_util import run_unittest_module

_MIN_TESTS = 15         # 原文件 def test_ 实测 15(3+4+5+2+1)


def test_agent_inbox_watcher_wrapped():
    n = run_unittest_module(
        "test_agent_inbox_watcher", _MIN_TESTS,
        pre_import=lambda: os.environ.setdefault("OR_API_KEY", "test-key-0000"),
    )
    print(f"test_agent_inbox_watcher: {n} 用例全绿, 零真实外发")