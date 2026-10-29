#!/usr/bin/env python3
"""#342/#343/#345 备份演练跟进项 — verify_backup.sh 行为测试（2026-10-29）。

被测 = scripts/verify_backup.sh。本用例**零网络/零真下载/零真外发**：
  - bash 侧行为沿用 `test_255_backup_drill_20261028.Drill`（假 REPO + 替身 python +
    假 date/sleep/df；notify 替身只写参数到临时日志，另加 `VERIFY_NOTIFY_DRY_RUN=1` 双保险）。
  - #345 的「分页完整性判据」在脚本内嵌 python 块里，替身 python 会把它整块拦掉 ⇒
    该块用**从脚本正文抽出来的原文**单独跑（不复制逻辑），加载的 upload_r2.py 是替身：
    把真实 upload_r2.py 整体 exec 进替身模块命名空间（保留真实 `_list_keys` 分页循环），
    只把网络层 `s3_request` 换成按 fixture 返回假响应。
  - 子进程 cwd = 假 REPO 根（复刻生产 unit `WorkingDirectory=<REPO>`）、**故意不设
    PYTHONPATH**：若脚本没有把 upload_r2.py 同目录加进 sys.path，import 会
    ModuleNotFoundError ⇒ 全部用例退化成 ERR（这正是本次修掉的前置缺陷，见 A1）。

覆盖的判定点：
  A. #345 内嵌块：正常单页/多页/零对象仍给正确日期（逐位一致）；首页非 200 ⇒ ERR；
     后续页非 200 或「截断却没有续页 token」⇒ LIST_FAIL(分页未取全)，不回落成旧日期。
  B. #342 告警正文：「失败/跳过项：」内容 == 结论行「跳过: …」同一串；无跳过项⇒不出现该行。
  C. #343 门限：0 / 负数 / 非数字 / 小数 / 带符号 / 空串 ⇒ 回落 4718592（空间门仍生效）；
     纯数字（含前导 0）⇒ 原样采用。
  D. 源码形状守卫 + 变异（≥2）：改坏生产逻辑必须变红（判别力关）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "verify_backup.sh"
REAL_UPLOAD_R2 = REPO_ROOT / "scripts" / "upload_r2.py"
REAL_LOCK_PATHS = REPO_ROOT / "scripts" / "r2_lock_paths.py"
REPO_PATHS_LIB = REPO_ROOT / "scripts" / "lib" / "repo_paths.sh"

from test_255_backup_drill_20261028 import (  # noqa: E402  (同目录, conftest 已加 path)
    Drill,
    STUB_PY,
    _write_exec,
)

# 告警正文里点名真因的那一行前缀（#342）
NOTES_PREFIX = "失败/跳过项："
LIST_FAIL_TOKEN = "LIST_FAIL(分页未取全)"


# ============================================================ A. #345 内嵌块（真跑）
# 替身 upload_r2.py：把真实 upload_r2.py 整体 exec 进本模块，再换掉网络层 s3_request。
# 这样 `_list_keys` 的分页循环是**生产同一份实现**（不复制逻辑 ⇒ 不漂移）。
FAKE_UPLOAD_R2 = '''
import json
import os

_src = os.environ["STUB_REAL_UPLOAD_R2"]
exec(compile(open(_src, encoding="utf-8").read(), _src, "exec"))

_pages = json.load(open(os.environ["STUB_PAGES"], encoding="utf-8"))
_n = {"i": 0}


def s3_request(method, key, payload=None, bucket=None, **kw):
    i = _n["i"]
    _n["i"] += 1
    assert i < len(_pages), "列表页取超了: fixture 只有 %d 页" % len(_pages)
    page = _pages[i]
    return (page.get("status", 200), page["body"].encode("utf-8"))
'''

# 生产环境同款 .env 垫片（upload_r2.py 模块级 load_env() 缺 .env 会 sys.exit）
ENV_SHIM = (
    "R2_BUCKET=ci-shim-test\n"
    "R2_S3_ENDPOINT=https://invalid.example\n"
    "R2_S3_ACCESS_KEY_ID=ci-shim\n"
    "R2_S3_SECRET_ACCESS_KEY=ci-shim\n"
)


def _page(keys=(), *, truncated=False, token=None, status=200, body=None):
    if body is not None:
        return {"status": status, "body": body}
    ks = "".join(f"<Key>{k}</Key>" for k in keys)
    if truncated:
        tail = "<IsTruncated>true</IsTruncated>"
        if token:
            tail += f"<NextContinuationToken>{token}</NextContinuationToken>"
    else:
        tail = "<IsTruncated>false</IsTruncated>"
    return {"status": status, "body": f"<ListBucketResult>{ks}{tail}</ListBucketResult>"}


def _embedded_list_block(src_path: Path | None = None) -> str:
    """从脚本正文抽出 r2_latest_backup_date 内嵌的 python 块（原文，不复制改写）。"""
    src = (src_path or SCRIPT).read_text(encoding="utf-8")
    start = src.index("r2_latest_backup_date() {")
    m = re.search(r"<<'PYEOF'\n(.*?)\nPYEOF", src[start:], re.S)
    assert m, "r2_latest_backup_date 内嵌 python 块结构变了，用例需同步"
    return m.group(1)


def _run_list_block(tmp_path: Path, pages, *, name: str = "stock_daily",
                    block_src: str | None = None):
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    shutil.copy(REAL_LOCK_PATHS, scripts / "r2_lock_paths.py")
    (scripts / "upload_r2.py").write_text(FAKE_UPLOAD_R2, encoding="utf-8")
    pages_file = tmp_path / "pages.json"
    pages_file.write_text(json.dumps(pages), encoding="utf-8")
    shim = tmp_path / "envshim"
    shim.mkdir()
    (shim / ".env").write_text(ENV_SHIM, encoding="utf-8")
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "GIT_REPO": str(shim),
        "REPO": str(repo),
        "STUB_REAL_UPLOAD_R2": str(REAL_UPLOAD_R2),
        "STUB_PAGES": str(pages_file),
        # 故意不设 PYTHONPATH；cwd 复刻生产 WorkingDirectory=<REPO>
    }
    return subprocess.run(
        [sys.executable, "-", str(scripts / "upload_r2.py"), name],
        input=block_src if block_src is not None else _embedded_list_block(),
        env=env, cwd=str(repo), capture_output=True, text=True, timeout=60,
    )


def _last_line(r) -> str:
    lines = [ln for ln in r.stdout.strip().splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def test_A1_block_imports_upload_r2_with_cwd_at_repo_root(tmp_path):
    """A1（前置缺陷守卫）：cwd=REPO 根且无 PYTHONPATH 时，块必须仍能 import upload_r2。

    upload_r2.py 模块级 `import r2_lock_paths`（同目录）依赖 sys.path[0]=脚本目录；
    `python -` 的 sys.path[0] 是 cwd（生产 unit WorkingDirectory=<REPO> 根）⇒ 不显式补
    `sys.path` 就 ModuleNotFoundError，整个存在性预判恒 ERR（每个库都误报 LIST 失败）。
    """
    r = _run_list_block(tmp_path, [_page(["backup/stock_daily_20261028.db.gz"])])
    assert r.returncode == 0, f"{r.stderr}\n{r.stdout}"
    assert "ModuleNotFoundError" not in r.stderr, f"import 失败: {r.stderr}"
    assert _last_line(r) == "20261028", f"{r.stdout}\n{r.stderr}"


def test_A2_single_page_returns_latest_date(tmp_path):
    """A2：正常路径逐位一致（多 key 取最大日期）。"""
    r = _run_list_block(tmp_path, [_page([
        "backup/stock_daily_20261026.db.gz",
        "backup/stock_daily_20261028.db.gz",
        "backup/stock_daily_20261027.db.gz",
    ])])
    assert _last_line(r) == "20261028", f"{r.stdout}\n{r.stderr}"


def test_A3_two_pages_returns_latest_date_from_last_page(tmp_path):
    """A3：多页取全（第 2 页有更新日期）⇒ 取到最新，不受分页顺序影响。"""
    r = _run_list_block(tmp_path, [
        _page(["backup/stock_daily_20261026.db.gz"], truncated=True, token="T1"),
        _page(["backup/stock_daily_20261028.db.gz"]),
    ])
    assert _last_line(r) == "20261028", f"{r.stdout}\n{r.stderr}"


def test_A4_zero_objects_returns_none(tmp_path):
    """A4：0 对象 ⇒ NONE（不是 ERR、更不是旧日期）。"""
    r = _run_list_block(tmp_path, [_page([])])
    assert _last_line(r) == "NONE", f"{r.stdout}\n{r.stderr}"


def test_A5_first_page_failure_returns_err(tmp_path):
    """A5：首页就非 200 ⇒ 完全看不见 ⇒ ERR（既有语义，不许变成 NONE）。"""
    r = _run_list_block(tmp_path, [_page(status=500, body="<Error/>")])
    assert _last_line(r) == "ERR", f"{r.stdout}\n{r.stderr}"


def test_A6_later_page_failure_reports_list_fail(tmp_path):
    """A6（#345 主场景）：第 1 页成功、第 2 页 500 ⇒ LIST_FAIL，不许拿第 1 页旧日期顶替。

    旧实现的病灶：`_list_keys` 只打一行警告就 return 部分 key ⇒ 最新 key 取成旧日期
    ⇒ 演练侧误报「备份过旧」，把真因（LIST 部分失败）盖掉。
    """
    r = _run_list_block(tmp_path, [
        _page(["backup/stock_daily_20261020.db.gz"], truncated=True, token="T1"),
        _page(status=500, body="<Error/>"),
    ])
    assert _last_line(r) == LIST_FAIL_TOKEN, f"{r.stdout}\n{r.stderr}"
    assert "备份过旧" not in r.stdout
    # 原始失败打印要留进 stderr(落 $LOG)，供人排查是哪一页挂了
    assert "status=500" in r.stderr


def test_A7_truncation_without_token_reports_list_fail(tmp_path):
    """A7：IsTruncated=true 却没有续页 token（语义不闭合）⇒ 同样判分页未取全。"""
    r = _run_list_block(tmp_path, [
        _page(["backup/stock_daily_20261020.db.gz"], truncated=True, token=None),
    ])
    assert _last_line(r) == LIST_FAIL_TOKEN, f"{r.stdout}\n{r.stderr}"


# ============================================================ B/C. bash 侧（Drill 沙箱）
class DrillListPartial(Drill):
    """Drill + 一个「分页部分失败」旋钮（替身 python 输出 LIST_FAIL token）。

    STUB_PY 是 test_255 的单一事实源：这里**替换并断言替换成功**，漂移时响亮失败，
    不会静默退化成"没这条用例"。
    """

    def __init__(self, tmp_path: Path):
        super().__init__(tmp_path)
        anchor = '      if [ "${STUB_LIST_FAIL:-0}" = "1" ]; then echo "ERR"; exit 0; fi'
        assert anchor in STUB_PY, "test_255 的替身结构变了，本用例需同步"
        patched = STUB_PY.replace(
            anchor,
            anchor + '\n      if [ "${STUB_LIST_PARTIAL:-0}" = "1" ]; then '
                     f'echo "{LIST_FAIL_TOKEN}"; exit 0; fi',
            1,
        )
        _write_exec(self.repo / ".venv" / "bin" / "python", patched)


def _conclusion_notes(stdout: str) -> str:
    """结论行里「跳过: …」那一段（= 告警正文该复用的同一串）。"""
    lines = [ln for ln in stdout.splitlines() if "=== 结论" in ln]
    assert len(lines) == 1, f"结论行应恰好 1 条: {lines}\n{stdout}"
    m = re.search(r"跳过: (.*?)）===", lines[0])
    return m.group(1) if m else ""


def test_B1_notify_body_names_skip_items_same_string(tmp_path):
    """B1（#342）：真失败 + 有跳过项 ⇒ 正文带「失败/跳过项：」，且与结论行同一串。"""
    drill = Drill(tmp_path)
    drill.set_rows("stock_daily", backup=0)      # 真失败：备份空
    r = drill.run(dow=3)                          # 非周日 ⇒ public_fund SKIP（有跳过项）
    assert r.returncode == 1, f"{r.stdout}\n{r.stderr}"
    notes = _conclusion_notes(r.stdout)
    assert notes, f"前提不成立：本用例需要跳过项\n{r.stdout}"
    assert f"{NOTES_PREFIX}{notes}" in drill.notified, (
        f"告警正文没点名真因/与结论行不一致:\nnotes={notes!r}\nnotify={drill.notified}")
    assert "--severe" in drill.notified


def test_B2_notify_body_has_no_empty_notes_tail(tmp_path):
    """B2（#342 反向）：无跳过/失败项 ⇒ 正文不许留「失败/跳过项：」空尾巴。"""
    drill = Drill(tmp_path)
    drill.set_rows("stock_daily", backup=0)       # 真失败
    # public_fund 走通 + 台账 OK ⇒ 跳过项为空
    drill.set_ledger(date=drill.today, gz_size=123456)
    r = drill.run(dow=7, mode="1", extra_env={"STUB_HEAD_LEN": "123456"})
    assert r.returncode == 1, f"{r.stdout}\n{r.stderr}"
    assert _conclusion_notes(r.stdout) == "", f"前提不成立：仍有跳过项\n{r.stdout}"
    assert "--severe" in drill.notified
    assert NOTES_PREFIX not in drill.notified, f"出现了空尾巴:\n{drill.notified}"


def test_B3_list_partial_failure_is_named_and_not_stale(tmp_path):
    """B3（#345 消费侧）：LIST 分页未取全 ⇒ 点名 LIST_FAIL，不许回落成「备份过旧」。"""
    drill = DrillListPartial(tmp_path)
    r = drill.run(dow=3, extra_env={"STUB_LIST_PARTIAL": "1"})
    assert r.returncode == 1, f"分页未取全必须 FAIL: rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert LIST_FAIL_TOKEN in r.stdout
    assert f"stock_daily=FAIL({LIST_FAIL_TOKEN}" in r.stdout
    # 真·误报文案是新鲜度检查的「✗FAIL 备份过旧」（verify_backup.sh:483）；
    # 注意不能用裸"备份过旧"——本修复的提示语里也会写到这个词。
    assert "FAIL 备份过旧" not in r.stdout, "真因被「备份过旧」盖掉了"
    assert "--severe" in drill.notified


@pytest.mark.parametrize("value", ["0", "-5", "abc", "5.0", "+5"])
def test_C1_non_positive_or_invalid_min_kb_falls_back(tmp_path, value):
    """C1（#343）：0/负数/非数字/小数/带符号 ⇒ 回落 4718592（空间门仍生效）。

    判别力：可用空间 10KiB。回落 4718592 ⇒ 判空间不足 SKIP（不启动大库还原）；
    若原样采用非法值（如 0）⇒ 10 < 0 为假 ⇒ 会直接跑还原 ⇒ 本断言必红。
    """
    drill = Drill(tmp_path)
    r = drill.run(dow=7, mode="1", min_kb=value, extra_env={"STUB_AVAIL_KB": "10"})
    assert "回落默认 4718592" in r.stderr, f"{value!r} 未回落: {r.stderr}"
    assert "SKIP(空间不足" in r.stdout, f"{value!r} 空间门没生效:\n{r.stdout}"
    assert not drill.restore_called, "门限非法却仍启动了大库还原 = 安全网关掉"
    assert r.returncode == 0                     # 空间不足是 SKIP（已 severe 告警）


def test_C2_leading_zero_digit_value_is_accepted_as_is(tmp_path):
    """C2（#343 反向）：纯数字（前导 0）不回落 —— 05 按 5KiB 用。"""
    drill = Drill(tmp_path)
    r = drill.run(dow=7, mode="1", min_kb="05", extra_env={"STUB_AVAIL_KB": "10"})
    assert "回落默认" not in r.stderr, f"05 是合法正整数，不该回落: {r.stderr}"
    assert "SKIP(空间不足" not in r.stdout, f"10KiB >= 5KiB 应放行:\n{r.stdout}"
    assert drill.restore_called


def test_C3_empty_min_kb_uses_default_silently(tmp_path):
    """C3（#343 边界）：空串 ⇒ 用默认值，不算非法（不刷警告）。"""
    drill = Drill(tmp_path)
    r = drill.run(dow=7, mode="1", min_kb="", extra_env={"STUB_AVAIL_KB": "10"})
    assert "回落默认" not in r.stderr, f"空串走 ${VAR:-默认}，不该报非法: {r.stderr}"
    assert "SKIP(空间不足" in r.stdout
    assert not drill.restore_called


# ============================================================ D. 源码形状 + 变异
def test_D1_source_shape_guard_followups():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "-le 0" in src and "回落默认 4718592" in src          # #343
    assert NOTES_PREFIX in src                                  # #342
    assert "VERIFY_SKIP_NOTES=" in src                          # #342 机器行/解析
    assert LIST_FAIL_TOKEN in src                               # #345
    # 导入可达性不再由本脚本兜（主控 2026-10-29 拍板：一处根治在 upload_r2.py 载荷侧），
    # 这里只守住"不要在本脚本里塞无条件 sys.path.insert"这条边界。
    assert "sys.path.insert(" not in src


def _mutated_script(tmp_path: Path) -> Path:
    dst = tmp_path / "mut" / "scripts"
    (dst / "lib").mkdir(parents=True, exist_ok=True)
    (dst / "verify_backup.sh").write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    (dst / "lib" / "repo_paths.sh").write_text(REPO_PATHS_LIB.read_text(encoding="utf-8"),
                                               encoding="utf-8")
    return dst / "verify_backup.sh"


def test_D2_mutation_without_zero_check_turns_C1_red(tmp_path):
    """变异①：删掉「0/负数回落」分支 ⇒ C1(min_kb=0) 必红。"""
    mut = _mutated_script(tmp_path)
    src = mut.read_text(encoding="utf-8")
    old = '  *)\n    if [ "$PF_MIN_KB" -le 0 ]; then'
    assert old in src
    mut.write_text(src.replace(old, "  *)\n    if false; then", 1), encoding="utf-8")

    drill = Drill(tmp_path / "run")
    r = drill.run(dow=7, mode="1", min_kb="0", extra_env={"STUB_AVAIL_KB": "10"}, script=mut)
    assert not ("回落默认 4718592" in r.stderr and "SKIP(空间不足" in r.stdout
                and not drill.restore_called), (
        "变异后 0 仍然回落并拦住空间门 ⇒ C1 没有判别力")


def test_D3_mutation_without_notes_line_turns_B1_red(tmp_path):
    """变异②：删掉告警正文「失败/跳过项：」那一行 ⇒ B1 必红。"""
    mut = _mutated_script(tmp_path)
    src = mut.read_text(encoding="utf-8")
    old = '  [ -n "${VERIFY_SKIP_NOTES:-}" ] && BODY="$BODY<br>失败/跳过项：$VERIFY_SKIP_NOTES"\n'
    assert old in src
    mut.write_text(src.replace(old, "", 1), encoding="utf-8")

    drill = Drill(tmp_path / "run")
    drill.set_rows("stock_daily", backup=0)
    r = drill.run(dow=3, script=mut)
    assert NOTES_PREFIX not in drill.notified, "变异后仍点名真因 ⇒ B1 没有判别力"


def test_D4_mutation_without_list_fail_branch_turns_B3_red(tmp_path):
    """变异③：删掉 LIST_FAIL 分支 ⇒ 分页部分失败会被当成正常下载 ⇒ B3 必红。"""
    mut = _mutated_script(tmp_path)
    src = mut.read_text(encoding="utf-8")
    start = src.index("    LIST_FAIL*)")
    end = src.index("    NONE)", start)
    mut.write_text(src[:start] + src[end:], encoding="utf-8")

    drill = DrillListPartial(tmp_path / "run")
    r = drill.run(dow=3, extra_env={"STUB_LIST_PARTIAL": "1"}, script=mut)
    assert not (r.returncode == 1 and LIST_FAIL_TOKEN in r.stdout), (
        f"变异后仍判 LIST_FAIL ⇒ B3 没有判别力\n{r.stdout}")


def test_D5_mutation_without_truncation_closed_check_turns_A7_red(tmp_path):
    """变异④：去掉「截断未闭合」判据 ⇒ A7 会退回旧日期 ⇒ 必红。"""
    mut = _mutated_script(tmp_path)
    src = mut.read_text(encoding="utf-8")
    old = 'truncation_open = bool(_calls) and "<IsTruncated>true</IsTruncated>" in _calls[-1][1]'
    assert old in src
    mut.write_text(src.replace(old, "truncation_open = False", 1), encoding="utf-8")

    r = _run_list_block(tmp_path / "run", [
        _page(["backup/stock_daily_20261020.db.gz"], truncated=True, token=None),
    ], block_src=_embedded_list_block(mut))
    assert _last_line(r) != LIST_FAIL_TOKEN, (
        "变异后仍判分页未取全 ⇒ A7 没有判别力")