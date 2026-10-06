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
import tempfile
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

# ④ upload_r2 顶层 load_env() 垫片(2026-10-06, CI 门禁 ⑧ 收集期崩溃根治, 原 #219 事故)
#   scripts/upload_r2.py 模块级 `load_env()`(:269) 若无 .env 会 `sys.exit`(:251), 其后
#   `os.environ["R2_BUCKET"]` 等再硬取(:270-275)。CI(ubuntu runner)无 .env(`.gitignore` 忽略)
#   ⇒ 任何测试文件顶层 `import upload_r2` 会在 **pytest 收集期**触发 SystemExit ⇒ INTERNALERROR
#   「no tests ran」(exit 3) ⇒ 整个 Job1 ⑧ 全军覆没(**不是**只挂一个文件; 收集期崩会让本目录
#   全部用例一条都不跑)。
#   本垫片在 conftest 加载期(早于 pytest 收集任何 test 模块)铺一个临时 .env:
#     ① `GIT_REPO` 指向 tempdir(命中 _find_env() 的 `$GIT_REPO/.env` 候选);
#     ② tempdir 内 `.env` 含 4 个键, 满足「文件存在 + 顶层 os.environ[...] 键齐」两道校验。
#   值全 dummy。垫片**只决定「模块能否 import」, 不产生任何真实触达**: 引用 upload_r2 的两个
#   测试(test_193 / test_219)对其调用全是纯函数 / 临时树输入; test_193 的自验脚本还对上传播径
#   与 notify 逐条打桩(见其 docstring「零外发自证」, 遵循 §18 L48)。setdefault 不覆盖已设值
#   (本机开发环境已 export GIT_REPO 时不改动), 只补 CI 的缺口。
#   注: 与 test_193 原先内联的同类垫片合并为本处单一事实源(§5.1 消除重复), 两文件共用。
_ENV_SHIM_DIR = Path(tempfile.mkdtemp(prefix="ci-env-shim-"))
(_ENV_SHIM_DIR / ".env").write_text(
    "R2_BUCKET=ci-shim-test\n"
    "R2_S3_ENDPOINT=https://invalid.example\n"
    "R2_S3_ACCESS_KEY_ID=ci-shim\n"
    "R2_S3_SECRET_ACCESS_KEY=ci-shim\n",
    encoding="utf-8",
)
os.environ.setdefault("GIT_REPO", str(_ENV_SHIM_DIR))