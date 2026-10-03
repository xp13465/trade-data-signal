# -*- coding: utf-8 -*-
"""scripts/tests 共享 pytest 环境(2026-10-03 新增, CI 门禁 ⑧ pytest 加固)。

背景: scripts/tests 由「脚本式自测」改造为真 pytest(CI Quality Gate ⑧ 收集崩溃修复),
本 conftest 统一解决三个环境问题, 所有 test_*.py 共享(不用每个文件重复 sys.path 样板)。

① sys.path: 仓库根 + scripts/ 入 path。test 文件 import notify / alert_denoise_rules /
   retry_failed_metrics / backfill_direct_metrics 等 scripts/ 目录模块需要。
   pytest 默认只把 test 文件所在目录(scripts/tests)加入 sys.path(import-mode=prepend),
   不包含 scripts/, 故必须显式注入(与既有三个正常测试 test_kelly_stats 等做法一致)。

② REPO env: backfill_direct_metrics.py 顶层 `os.environ.get("REPO", 开发者主仓绝对路径缺省)`
   的缺省值是开发者主仓绝对路径, CI(ubuntu runner)上不存在 → 显式 setdefault 为仓库根,
   消除主仓绝对路径依赖(且测试文件不再硬编码任何绝对路径)。

③ 第三方库 stub(CI 依赖最小化): CI ⑧ 只 `pip install pytest pyyaml`, 而
   retry_failed_metrics / backfill_direct_metrics 会 import app.collector 生产链
   (fetchers → multisource/fapi_fallback/fapi_daily, base), 其顶层 `import requests /
   pandas / akshare / pyarrow`(本地 dev venv 有; CI 没有, 装齐这些重型库会拖慢门禁且
   含网络/DNS 依赖, 不适合 CI 常驻)。因测试只「import 模块 + 调纯函数/方向patch」、
   从不调用第三方库方法, 只需保证这些 import 语句能解析 → 对「未安装」的库注入空
   ModuleType stub。本地 venv 已装有真实库时 find_spec 命中 → 不 stub, 保持与生产
   同构(原脚本式自测的行为不变)。
   - requests: app/collector/base.py 顶层 `EM_SESSION = requests.Session()` 后紧跟
     `EM_SESSION.headers.update(...)`, stub 的 Session 需带可 update 的 headers dict +
     mount() 空实现(运行时 .get 等不在 stub → AttributeError 响亮失败, 不假绿)。
   - pandas / akshare: 仅顶层 import, 无子模块访问。
   - pyarrow: fapi_daily.py 顶层 `import pyarrow.parquet as pq`, 需连子模块一起 stub
     (空模块无 __path__, 单独 stub 父包会导致 `import pyarrow.parquet` 从磁盘找不
     到子模块而 ImportError)。

注: base.py 顶层 `_SWS_IP = _resolve_sws_ip()` 会做一次真实 DNS 解析, 内层 try/except
兜底(fallback 固定 IP), CI/本地均不抛; baostock_socket_timeout 的 apply_socket_timeout()
内置 try import baostock, CI 无 baostock 时静默跳过。均已实测。切勿为省事删除 stub, 否则
rfm/bdm 两个测试在 CI 上会退回 ImportError。
"""
import importlib.util
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).absolute().parent.parent.parent  # scripts/tests -> 仓库根
SCRIPTS = ROOT / "scripts"

for _p in (str(SCRIPTS), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("REPO", str(ROOT))

# ③ 未安装的第三方库注入 stub(本地已装则保持真库)
for _name, _need_session, _submods in (
    ("requests", True, ()),
    ("pandas", False, ()),
    ("akshare", False, ()),
    ("pyarrow", False, ("parquet",)),
):
    if _name in sys.modules or importlib.util.find_spec(_name) is not None:
        continue  # 本地 venv 已装: 不 stub, 保持同构
    _m = types.ModuleType(_name)
    if _need_session:
        # requests: 仅满足 import 期模块级用法(base.py `EM_SESSION = requests.Session()`
        # 后紧跟 `EM_SESSION.headers.update(...)`), headers 必须是可 update 的 dict;
        # mount() 在 base.py try/except 内(requests.adapters 导入失败即整体跳过), 补上
        # 防 try 块意外成功。任何**运行时**方法调用(如 em_get 里的 .get)不在 stub 内 →
        # AttributeError 响亮失败, 不假绿(测试只调纯判定函数, 不触运行时第三方调用)。
        class _Session:
            def __init__(self, *a, **k):
                self.headers = {}

            def mount(self, *a, **k):  # noqa: B027
                return None
        _m.Session = _Session
    sys.modules[_name] = _m
    if _submods:
        _m.__path__ = []  # 允许子模块注册
        for _sub in _submods:
            sys.modules[f"{_name}.{_sub}"] = types.ModuleType(f"{_name}.{_sub}")