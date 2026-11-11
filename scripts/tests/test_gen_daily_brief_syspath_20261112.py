"""gen_daily_brief 脚本模式 sys.path 回归（2026-11-12）：仓库根必须被补进 sys.path。

背景（云上 20:40 daily_brief rc=1 实证）：`scripts/run_daily_brief.sh` 以「直接执行脚本」
方式调用 gen_daily_brief.py ⇒ sys.path[0]=scripts/ 而 cwd≠仓库根；7289085f5 在
load_data()（scripts/gen_daily_brief.py）引入 `from app.fx_contract import ...`，模块级
sys.path 初始化只 insert 了 ROOT/scripts 没 insert 仓库根 ⇒ 云上 import 必炸
ModuleNotFoundError: No module named 'app'。本机 CI 因 cwd=仓库根而假绿。

判别力：改前必红（仓库根不在 sys.path / app 不可导入），改后必绿。
与 test_importpath_p0_20261029.py 同款纪律：起子进程 + cwd=空临时目录 + 去掉 PYTHONPATH，
不借 conftest 把 scripts/ 塞进 sys.path 的便利，真实复现脚本模式。
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"

# 只去掉 PYTHONPATH（那是唯一能"偷偷"把仓库根补进子进程 sys.path 的变量）。
_STRIP = {"PYTHONPATH"}


def _env():
    return {k: v for k, v in os.environ.items() if k not in _STRIP}


def test_script_mode_repo_root_on_syspath(tmp_path):
    """脚本模式（sys.path[0]=scripts/、cwd=空目录）加载 gen_daily_brief 后仓库根必须在 sys.path。"""
    code = (
        "import sys; sys.path.insert(0, {scripts!r}); "
        "import gen_daily_brief; "
        "print('ROOT_OK' if any(p == {root!r} for p in sys.path) else 'ROOT_MISSING'); "
        "import importlib.util; "
        "print('APP_OK' if importlib.util.find_spec('app') is not None else 'APP_MISSING')"
    ).format(scripts=str(SCRIPTS), root=str(REPO))
    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(tmp_path),
        env=_env(),
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
    )
    assert r.returncode == 0, f"脚本模式加载 gen_daily_brief 失败：\n{r.stderr}"
    assert "ROOT_OK" in r.stdout, (
        f"仓库根未进 sys.path（云上 20:40 rc=1 同根因）：\n{r.stdout}\n{r.stderr}"
    )
    assert "APP_OK" in r.stdout, (
        f"app 包不可导入（load_data 的 from app.fx_contract import 必炸）：\n{r.stdout}\n{r.stderr}"
    )
