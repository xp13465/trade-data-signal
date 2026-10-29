"""导入路径 P0（2026-10-29）：以 REPO 根为 cwd 用 importlib 加载 upload_r2.py 必须成功。

背景（实测）：`python -` 的 sys.path[0] 是 **cwd**，而 `scripts/upload_r2.py` 模块级
`import r2_lock_paths`（同目录）依赖 sys.path[0] = 脚本所在目录。生产演练
`verify_backup.sh` 以单元文件 WorkingDirectory=<REPO> 根起内嵌 python，于是 10-28 上线的
stock_daily 存在性预判恒 `ERR`（每个库都误报 "R2 LIST 失败"），整段 integrity/行数校验跑不到。

为什么另起一套「真执行」用例：`test_255_backup_drill_20261028.py` 用替身 python 把
`$PY - .../upload_r2.py` 整段拦截，import 这一层从来没被执行过；而 pytest 进程内又由
conftest 把 `scripts/` 塞进 sys.path，等于替生产环境兜了底。所以这里的用例一律
**起子进程 + cwd=REPO 根 + 去掉 PYTHONPATH**，不借 conftest 的 sys.path 便利。

判别力：改前必红（ModuleNotFoundError），改后必绿；配套源码形状守卫防"顺手简化"回去。
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# 只去掉 PYTHONPATH（那是唯一能"偷偷"把 scripts/ 补回 sys.path 的变量）；
# 其余环境沿用：CI 无 .env 时靠 conftest 铺的 GIT_REPO 垫片，本地用真 .env。
_STRIP = {"PYTHONPATH"}


def _env():
    return {k: v for k, v in os.environ.items() if k not in _STRIP}


def _run(argv):
    return subprocess.run(
        argv,
        cwd=str(REPO),
        env=_env(),
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
    )


def test_T_REAL_1_import_upload_r2_from_repo_root():
    """生产等价 cwd（REPO 根）下真加载 upload_r2.py：改前 ModuleNotFoundError，改后退出码 0。"""
    code = (
        "import importlib.util;"
        "s=importlib.util.spec_from_file_location('u','scripts/upload_r2.py');"
        "m=importlib.util.module_from_spec(s);"
        "s.loader.exec_module(m);"
        "print('IMPORT_OK')"
    )
    r = _run([sys.executable, "-c", code])
    assert r.returncode == 0, (
        "REPO 根 cwd 下加载 scripts/upload_r2.py 失败（生产演练就是这条路径）：\n"
        f"{r.stderr}"
    )
    assert "IMPORT_OK" in r.stdout


def test_T_REAL_2_restore_script_help_from_repo_root():
    """docs/scripts/restore_r2_db_backup.py 在 REPO 根下 --help 必须正常退出（它模块级加载 upload_r2）。"""
    r = _run([sys.executable, "docs/scripts/restore_r2_db_backup.py", "--help"])
    assert r.returncode == 0, (
        "restore_r2_db_backup.py --help 在 REPO 根下失败：\n"
        f"{r.stderr}"
    )
    assert "usage" in (r.stdout + r.stderr).lower()


def test_T_REAL_4_mutation_dropping_guard_turns_t1_red(tmp_path):
    """变异：把兜底删回裸 `import r2_lock_paths` ⇒ 同样的加载方式必红（证明 T-REAL-1 有判别力）。"""
    src = (REPO / "scripts" / "upload_r2.py").read_text(encoding="utf-8")
    start = src.index("try:\n    import r2_lock_paths as _rlp")
    tail_marker = "    import r2_lock_paths as _rlp  # noqa: E402\n"
    end = src.index(tail_marker, start) + len(tail_marker)
    mutated = src[:start] + "import r2_lock_paths as _rlp  # noqa: E402\n" + src[end:]

    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "upload_r2.py").write_text(mutated, encoding="utf-8")
    (repo / "scripts" / "r2_lock_paths.py").write_bytes(
        (REPO / "scripts" / "r2_lock_paths.py").read_bytes())

    code = (
        "import importlib.util;"
        "s=importlib.util.spec_from_file_location('u','scripts/upload_r2.py');"
        "m=importlib.util.module_from_spec(s);"
        "s.loader.exec_module(m)"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=str(repo), env=_env(),
                       capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    assert r.returncode != 0, "删掉兜底后仍能加载 ⇒ T-REAL-1 没有判别力"
    assert "ModuleNotFoundError" in r.stderr


def test_T_REAL_3_upload_r2_guards_lock_paths_import():
    """源码形状守卫：`import r2_lock_paths` 必须带 ModuleNotFoundError 兜底（防被"简化"回去）。"""
    src = (REPO / "scripts" / "upload_r2.py").read_text(encoding="utf-8")
    idx = src.index("import r2_lock_paths as _rlp")
    window = src[max(0, idx - 700): idx + 300]
    assert "except ModuleNotFoundError" in window, "缺 ModuleNotFoundError 兜底"
    assert "sys.path.insert" in window, "兜底分支里必须补 sys.path（否则 import 仍失败）"
    # 兜底必须是"先试后补"，不是无条件 insert 到搜索路径最前面（以后者会打歪全仓 import）
    assert window.index("try:") < window.index("sys.path.insert")