# -*- coding: utf-8 -*-
"""CI 门禁 ⑧ 「缺省第三方库」导入级 stub 的**单一事实源**(2026-10-09, CI run #727 红修复)。

背景(为什么需要):
  CI Quality Gate ⑧ 只装 pytest + pyyaml + numpy/pandas/pyarrow
  (`.github/workflows/ci.yml` 的 `pip install` 行),而 `app.collector` 生产链顶层
  `import requests / akshare`。凡在**裸子进程**里 import 该链的代码,都会因缺 requests
  而 `ModuleNotFoundError`。两份调用点:
    ① pytest **进程内**:`conftest.py` 装上 stub ⇒ 进程内 import 正常(历史行为)。
    ② **子进程**:`gen_fapi_golden_238.py` 的 `python -c` oracle 子进程、
       `fapi_oom_mem_probe.py` —— 不加载 conftest,须各自**先调用本函数**再 import 目标模块。
  这正是 CI #727(合并 #238)变红的根因:新测试 `test_golden_fixture_reproducible_from_legacy_oracle`
  起的子进程没有 conftest 的 stub ⇒ 在 CI(缺 requests)上 import 旧版 fapi_daily 失败
  ⇒ 生成器 exit 1 ⇒ 断言 `out.returncode == 0` FAIL;而本机装上 requests 故假绿(§18 L49 反面)。

判据(与 conftest 原逻辑逐字一致,搬移不改语义):
  仅当模块**未安装**(`find_spec` 为 None,含 `sys.modules[name] is None` 的情形)且
  **未加载**(不在 `sys.modules`)时,注入空 `ModuleType`。本地 venv 装了真库 ⇒ 不 stub,
  保持与生产同构。stub 只保证**import 语句可解析**;任何**运行时**调用(如 `requests.get`)
  不在 stub 内 ⇒ `AttributeError` **响亮失败**,绝不假绿(§18 L49)。
"""
from __future__ import annotations

import importlib.util
import sys
import types

# (模块名, 是否需要「带 Session」的桩, 需一并注册的子模块)
_SPECS: tuple[tuple[str, bool, tuple[str, ...]], ...] = (
    ("requests", True, ()),
    ("pandas", False, ()),
    ("akshare", False, ()),
    ("pyarrow", False, ("parquet",)),
)


def _session_stub():
    """requests 桩:仅满足 import 期模块级用法(`base.py EM_SESSION = requests.Session()`
    后紧跟 `EM_SESSION.headers.update(...)`),headers 必须是可 update 的 dict;
    `mount()` 在 base.py try/except 内(requests.adapters 导入失败即整体跳过),补上防 try
    块意外成功。运行时方法(em_get 里的 `.get`)不在桩内 ⇒ AttributeError 响亮失败。
    """

    class _Session:
        def __init__(self, *a, **k):
            self.headers = {}

        def mount(self, *a, **k):  # noqa: B027
            return None

    return _Session


def install_missing_third_party_stubs() -> list[str]:
    """对 CI 缺省的第三方库注入导入级 stub;返回**本次实际 stub** 的模块名列表(便于自证)。"""
    stubbed: list[str] = []
    for name, need_session, submods in _SPECS:
        if name in sys.modules or importlib.util.find_spec(name) is not None:
            continue  # 本地 venv 已装 / 已加载: 不 stub, 保持同构
        mod = types.ModuleType(name)
        if need_session:
            mod.Session = _session_stub()
        sys.modules[name] = mod
        if submods:
            mod.__path__ = []  # 允许子模块注册
            for sub in submods:
                sys.modules[f"{name}.{sub}"] = types.ModuleType(f"{name}.{sub}")
        stubbed.append(name)
    return stubbed