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
import shutil
import sys
import tempfile
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


def _isolate_repo_env():
    """#247-R2 / #245 卫生(2026-10-11): 把 REPO/GIT_REPO 定向到临时树, 供 legacy 套件 REPO 隔离。

    病灶: notify-family 原脚本直接调 `notify.send(...)` / `flush_warning_batch(dry_run=False)`
    (三渠道用 mock 打桩、零真实外发), 但 `notify._record_ledger` 会落 `data/alerts/alert_ledger.jsonl`
    —— 其路径 `_ledger_path()` 在**调用时**读 `os.environ["REPO"]`(非 import 期绑定) ⇒ 主仓跑
    pytest 会把合成台账写进主仓 data/alerts(既存卫生项, #245/#247 留档)。把 env REPO 指向临时树,
    调用时解析即落临时树; 退出时临时树整体 rmtree。
    返回临时目录 Path(调用方负责 finally 清理); env 由既有 `_restore_env` 快照还原, 此处不动。
    ⚠️ env 只覆盖**调用时**解析的路径; **import 期绑定量**(ALERTS_FILE/ALERTS_DIR/... 由 REPO 派生)
    在同会话更早用例已导入 notify 时不随 env 变, 由 `_redirect_repo_paths` 在 import 后显式重绑
    (实测: 6 文件家族批里 test_notify_dedup 的 `_mirror_severe` 会经 import 期绑定的 ALERTS_FILE
    把 latest.md 写进主仓 data/alerts —— 仅 env 级修不掉, 须重绑, 2026-10-11)。
    """
    d = Path(tempfile.mkdtemp(prefix="legacy-repo-isolate-"))
    os.environ["REPO"] = str(d)
    os.environ["GIT_REPO"] = str(d)
    return d


# 各「模块 under test」的**落盘路径常量**(import 期由 REPO 派生)。env REPO 只覆盖**调用时**
# 解析的路径(如 notify `_ledger_path()`);这些 import 期绑定量在同会话更早用例已导入该模块时
# 不随 env 变, 须在 import 后显式重绑(否则主仓跑 pytest 会把合成告警/去重文件写进主仓 data/)。
# 只列**写盘类且落在 data/ 下**的常量: 不含 *_CONFIG 等**读盘类**(CI/临时树无该文件, 重定向会致
# 用例失败), 也不含 TASKS_PATH(各用例已自行 patch 到 tempdir)。
_REPO_PATH_ATTRS = {
    "notify": (
        "ALERTS_DIR", "ALERTS_FILE", "WARNING_BUFFER_FILE", "INFO_LOG_FILE",
        "WARNING_FLUSH_LOCK_FILE", "ALERT_DIGEST_FILE", "ALERT_DIGEST_LOCK_FILE",
        "ALERT_DIGEST_STATE_FILE", "WARNING_DEDUP_STATE_FILE", "WARNING_DEDUP_LOCK_FILE",
        "DEDUP_FILE",
    ),
    # feishu_ws_listener.StabilityFixTests 调 process_event(...) 时不传 dedup_path ⇒ 落到模块级
    # FORWARD_DEDUP_PATH(合成 3 行写进主仓 data/feishu_requests/, 2026-10-11 实测)。
    # LOG_PATH(#247-R2/#245 卫生补, 2026-10-11 B2 审查 O-2): 原为硬编码绝对路径
    # `/Users/linhuichen/code/trade-data/data/logs/feishu_listener.log`(镜像树), log() 复跑实测有新行;
    # 登记后随机制重定向到临时树(不再写 trade-data 镜像树), 有 try/except 兜底 CI 恒安全。
    "feishu_ws_listener": ("FORWARD_DEDUP_PATH", "AUTODONE_DEDUP_PATH", "LOG_PATH"),
    # agent_inbox_watcher(#247-R2/#245 卫生补, 2026-10-11 B2 审查 O-1): REPO 硬编码主仓(:23),
    # LOG_DIR/LOG_FILE 在 import 期由 REPO 派生绑定(:29-30); 原测试只 patch w.REPO(:110/:274)
    # 不更新已绑定的 LOG_DIR/LOG_FILE ⇒ 跑 pytest 时 log() 把合成行 append 进主仓
    # data/logs/agent_inbox_watcher.log(实测 rev-test-003/t-verdict-003, 2026-10-11 10:25:40)。
    # 与 feishu_ws_listener 逐字同型(import 期绑定量 + legacy 套件), 补登记后重定向到临时树。
    "agent_inbox_watcher": ("LOG_DIR", "LOG_FILE"),
}


def _redirect_repo_paths(iso_dir):
    """把**已在 sys.modules** 的受管模块的落盘路径常量重定向到临时树(与 env REPO 同树)。

    仅处理 `_REPO_PATH_ATTRS` 登记且在册的模块(notify 由各 notify-家族套件 import; feishu_ws_listener
    由 test_feishu_ws_listener 顶层 `import ... as fwl` 带入; agent_inbox_watcher 由 test_agent_inbox_watcher
    `import agent_inbox_watcher as w` 带入);收尾 `_restore_modules` 整体还原
    (快照两层: 对象身份 + 命名空间属性, 二者都须在 `_WATCH_MODULES` 内)。
    """
    for mname, attrs in _REPO_PATH_ATTRS.items():
        mod = sys.modules.get(mname)
        if mod is None:
            continue
        for name in attrs:
            orig = getattr(mod, name, None)
            if not isinstance(orig, Path):
                continue
            setattr(mod, name, iso_dir / "data" / Path(orig).name)


# 被包装脚本会往 sys.modules 里塞假模块 / pop 后重导入的「热点模块」; 包装收尾必须还原,
# 否则假 notify 会毒化**同 pytest 会话后续全部用例**(实测: test_204 的假 notify 缺
# `_get_tenant_access_token` → 之后 test_feishu_post 的 setUp patch 直接 AttributeError)。
# feishu_ws_listener 亦纳入: 其 import 期路径常量会被 `_redirect_repo_paths` 重绑,
# 必须随包装收尾还原(否则残留指向已删临时树)。
# agent_inbox_watcher 同理纳入(2026-10-11 O-1): LOG_DIR/LOG_FILE 被重绑, 收尾须还原。
_WATCH_MODULES = ("notify", "upload_r2", "check_data_integrity", "feishu_ws_listener",
                  "agent_inbox_watcher")


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


def run_unittest_module(module_name, min_tests, *, pre_import=None, isolate_repo=False):
    """import `module_name` 的全部 TestCase 并跑; 断用例数下限 + 全绿 + 零外发。返回 testsRun。

    isolate_repo=True 时, 运行期把 REPO/GIT_REPO 指向临时树(见 `_isolate_repo_env`), 防调用时
    解析的路径(如 notify 台账)污染主仓 data/; 退出清理临时树(#247-R2/#245 卫生)。
    """
    env_snapshot = dict(os.environ)
    mod_snapshot = _snapshot_modules()
    iso_dir = _isolate_repo_env() if isolate_repo else None
    _prepare(pre_import)
    try:
        with ZeroOutboundTrap() as trap:
            mod = importlib.import_module(module_name)
            if iso_dir is not None:
                _redirect_repo_paths(iso_dir)
            suite = unittest.defaultTestLoader.loadTestsFromModule(mod)
            buf = io.StringIO()
            res = unittest.TextTestRunner(verbosity=2, stream=buf).run(suite)
        out = buf.getvalue()
    finally:
        _restore_modules(mod_snapshot)
        _restore_env(env_snapshot)
        if iso_dir is not None:
            shutil.rmtree(iso_dir, ignore_errors=True)
    assert res.wasSuccessful(), (
        f"{module_name}: 有失败/异常用例(failures={len(res.failures)} errors={len(res.errors)})\n{out}")
    assert res.testsRun >= min_tests, (
        f"{module_name}: 仅跑到 {res.testsRun} 个用例(下限 {min_tests}), 疑似收集/执行异常(§18 L49)")
    assert trap.hits == [], f"{module_name}: 零外发被破坏(§18 L48) hits={trap.hits}"
    return res.testsRun


def run_script_main(module_name, *, pre_import=None, capture=True, isolate_repo=False):
    """import `module_name` 并调其 `main()`(进程式), 接住 SystemExit。

    capture=True 时把 stdout/stderr 收进命名空间(脚本大量 print, 避免污染 pytest 输出),
    原样返回供调用方按各自计数断言。返回 SimpleNamespace(rc, out, err, mod, trap_hits)。
    ⚠️ `err`(2026-10-25 审查补): 生产脚本的**强信号**常写 stderr(upload_r2 verify-r2 的
    「大量不一致」阈值告警即 stderr, upload_r2.py:4122-4123); 只收 stdout 会让对 stderr 的断言
    变成**永远通过的空断言**。`out` 语义不变(仍只含 stdout), 既有调用方零影响。
    isolate_repo=True 同 `run_unittest_module`(REPO/GIT_REPO→临时树)。
    """
    env_snapshot = dict(os.environ)
    mod_snapshot = _snapshot_modules()
    iso_dir = _isolate_repo_env() if isolate_repo else None
    _prepare(pre_import)
    rc = None
    out = ""
    err = ""
    try:
        with ZeroOutboundTrap() as trap:
            mod = importlib.import_module(module_name)
            if iso_dir is not None:
                _redirect_repo_paths(iso_dir)
            if capture:
                buf = _CapStdout()
                err_buf = _CapStdout()
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err_buf):
                    try:
                        mod.main()
                    except SystemExit as e:      # 原脚本以 sys.exit(0/1) 收尾
                        rc = e.code
                out = buf.getvalue()
                err = err_buf.getvalue()
            else:
                try:
                    mod.main()
                except SystemExit as e:
                    rc = e.code
    finally:
        _restore_modules(mod_snapshot)
        _restore_env(env_snapshot)
        if iso_dir is not None:
            shutil.rmtree(iso_dir, ignore_errors=True)
    return types.SimpleNamespace(rc=rc, out=out, err=err, mod=mod, trap_hits=trap.hits)