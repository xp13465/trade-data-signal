# -*- coding: utf-8 -*-
"""#213 批1 薄包装: scripts/test_feishu_ws_listener.py → CI 闸门 ⑧(单一实现, 原文件零改动)。

原脚本形态 = unittest TestCase 集合(5 个类: SendReceiptTests / AutoTodoReceiptTests /
ProcessEventAutoTodoTests / CrossGroupForwardTests / StabilityFixTests, 合计 33 个用例)。
打桩:fwl._get_tenant_access_token / fwl._feishu_http_post_json(FakeNotify 承接)。

⚠️ 原文件 `fwl`(feishu_ws_listener)是长驻 websocket 监听器模块; 本包装只 import 它 +
跑其 TestCase(不 start 监听循环), 网络出口由 ZeroOutboundTrap 兜底(§18 L48)。

#247-R2/#245 卫生(2026-10-11): isolate_repo=True —— StabilityFixTests 调 process_event 不传
dedup_path ⇒ 落模块级 FORWARD_DEDUP_PATH(合成 3 行曾写进主仓 data/feishu_requests/)。
env REPO→临时树 + `_redirect_repo_paths` 重绑 import 期常量, 双向隔离(见 _wrap_util 注释)。
"""
from _wrap_util import run_unittest_module

_MIN_TESTS = 33         # 原文件 def test_ 实测 33


def test_feishu_ws_listener_wrapped():
    n = run_unittest_module("test_feishu_ws_listener", _MIN_TESTS, isolate_repo=True)
    print(f"test_feishu_ws_listener: {n} 用例全绿, 零真实外发")