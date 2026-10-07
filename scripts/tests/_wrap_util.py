# -*- coding: utf-8 -*-
"""#213 共享工具: 薄包装历史自测脚本入 CI 闸门 ⑧ 的通用跑法(单一实现, 防 11 份重复样板)。

两种包装形态(对应两类原脚本, 见 docs/ops/213-scripts-root-tests-ci-verdict-20261007.md §1):
  ① `run_unittest_module`: 原脚本是「unittest TestCase 集合」形态(notify 家族 / feishu_ws_listener /
     agent_inbox_watcher)→ import 模块 + `defaultTestLoader.loadTestsFromModule` 收全部用例 + 跑 +
     断 `testsRun >= min_tests`(防 0 用例假绿, §18 L49)+ `wasSuccessful()`。
  ② `run_script_main`: 原脚本是「进程式 main() + PASS/FAIL 计数 + sys.exit」形态(test_204 /
     test_ai_macro_hit_filters / test_188)→ import 模块 + 调 `main()` + 接住 SystemExit + 断 rc==0,
     再按各脚本自己的计数断言(由调用方做, 防把不同脚本的计数语义写死在此)。

共性(两者都做):
  · 把 `scripts/` 塞进 sys.path(原脚本靠同目录 import, 包装后需显式补);
  · 用 `ZeroOutboundTrap` 包裹执行(§18 L48 零外发自证);
  · 收尾**整体还原 os.environ**(原脚本有的在 import 期/执行期改 REPO/MATCH/OR_API_KEY 等, 进程式
    设计不还原; pytest 长驻会话里必须还原, 否则毒化同会话其余用例)。
"""
from __future__ import annotations

import contextlib
import importlib
import io
import os
import sys
import types
import unittest
from pathlib import Path

_HERE = Path(__file__).absolute().parent          # scripts/tests
SCRIPTS = _HERE.parent                            # scripts
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from _zero_outbound import ZeroOutboundTrap  # noqa: E402


def _prepare(pre_import):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    if pre_import is not None:
        pre_import()


def _restore_env(snapshot):
    os.environ.clear()
    os.environ.update(snapshot)


# 被包装脚本会往 sys.modules 里塞假模块 / pop 后重导入的「热点模块」; 包装收尾必须还原,
# 否则假 notify 会毒化**同 pytest 会话后续全部用例**(实测: test_204 的假 notify 缺
# `_get_tenant_access_token` → 之后 test_feishu_post 的 setUp patch 直接 AttributeError)。
_WATCH_MODULES = ("notify", "upload_r2", "check_data_integrity")


def _snapshot_modules():
    """快照热点模块的「模块对象 + 其命名空间」两层状态。

    两层缺一不可: ①脚本常 `sys.modules["notify"] = Fake`(换对象) ⇒ 还原对象身份;
    ②脚本也常直接改**真模块**的属性(实测 test_204 把真 notify.send 换成抛错陷阱且不还原)
    ⇒ 还必须还原被改动的属性, 否则后续用例调用真 notify.send 就撞上陷阱。
    """
    snap = {}
    for m in _WATCH_MODULES:
        existed = m in sys.modules
        obj = sys.modules.get(m)
        snap[m] = (existed, obj, dict(vars(obj)) if obj is not None else None)
    return snap


def _restore_modules(snap):
    for m, (existed, obj, saved_vars) in snap.items():
        if not existed:
            sys.modules.pop(m, None)
            continue
        sys.modules[m] = obj
        if saved_vars is None:
            continue
        cur = vars(obj)
        for k in [k for k in cur if k not in saved_vars]:
            del cur[k]                      # 运行期新增的属性: 删除
        for k, v in saved_vars.items():
            if k not in cur or cur[k] is not v:
                cur[k] = v                  # 被替换的属性: 还原原引用


class _CapStdout(io.StringIO):
    """捕获用 stdout: 兼容生产模块 import 期的 `sys.stdout.reconfigure(line_buffering=True)`。

    upload_r2.py:44 在**模块级**调 `sys.stdout.reconfigure(...)`; 若 redirect 目标是原生
    StringIO 会在 import 期 AttributeError(本包装实测踩到)。补 no-op reconfigure, 语义无影响。
    """

    def reconfigure(self, *a, **k):      # 仅吞掉生产模块的行缓冲设置(捕获场景本就无 fd 语义)
        return None


def run_unittest_module(module_name, min_tests, *, pre_import=None):
    """import `module_name` 的全部 TestCase 并跑; 断用例数下限 + 全绿 + 零外发。返回 testsRun。"""
    env_snapshot = dict(os.environ)
    mod_snapshot = _snapshot_modules()
    _prepare(pre_import)
    try:
        with ZeroOutboundTrap() as trap:
            mod = importlib.import_module(module_name)
            suite = unittest.defaultTestLoader.loadTestsFromModule(mod)
            buf = io.StringIO()
            res = unittest.TextTestRunner(verbosity=2, stream=buf).run(suite)
        out = buf.getvalue()
    finally:
        _restore_modules(mod_snapshot)
        _restore_env(env_snapshot)
    assert res.wasSuccessful(), (
        f"{module_name}: 有失败/异常用例(failures={len(res.failures)} errors={len(res.errors)})\n{out}")
    assert res.testsRun >= min_tests, (
        f"{module_name}: 仅跑到 {res.testsRun} 个用例(下限 {min_tests}), 疑似收集/执行异常(§18 L49)")
    assert trap.hits == [], f"{module_name}: 零外发被破坏(§18 L48) hits={trap.hits}"
    return res.testsRun


def run_script_main(module_name, *, pre_import=None, capture=True):
    """import `module_name` 并调其 `main()`(进程式), 接住 SystemExit。

    capture=True 时把 stdout/stderr 收进命名空间(脚本大量 print, 避免污染 pytest 输出),
    原样返回供调用方按各自计数断言。返回 SimpleNamespace(rc, out, mod, trap_hits)。
    """
    env_snapshot = dict(os.environ)
    mod_snapshot = _snapshot_modules()
    _prepare(pre_import)
    rc = None
    out = ""
    try:
        with ZeroOutboundTrap() as trap:
            mod = importlib.import_module(module_name)
            if capture:
                buf = _CapStdout()
                with contextlib.redirect_stdout(buf):
                    try:
                        mod.main()
                    except SystemExit as e:      # 原脚本以 sys.exit(0/1) 收尾
                        rc = e.code
                out = buf.getvalue()
            else:
                try:
                    mod.main()
                except SystemExit as e:
                    rc = e.code
    finally:
        _restore_modules(mod_snapshot)
        _restore_env(env_snapshot)
    return types.SimpleNamespace(rc=rc, out=out, mod=mod, trap_hits=trap.hits)