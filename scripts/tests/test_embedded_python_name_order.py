# -*- coding: utf-8 -*-
"""顺序守卫 scripts/check_embedded_py_name_order.py 的自测(2026-10-26, P1 事故复发防线)。

事故背景: schedule_monitor.sh 内嵌 Python 里 MISSED_CONTINUOUS_THRESHOLD 定义在模块尾部,
模块级 `for t in TASKS:` 漏跑检查却先使用它 ⇒ 首次真漏跑必 NameError, 整轮监控静默中止
26 天(脚本末尾 exit 0, systemd 恒 success)。旧测试全是「抽片段 exec + 手工注入常量」,
把缺失的常量喂了进去, 所以永远发现不了。

本文件守住三件事:
① 判别力: 坏样本(先使用后定义)必须 FAIL, 好样本必须 PASS —— 样本构造不能让守卫
   「看起来绿」;
② 不许静默放过: 非 Python heredoc / `from x import *` / exec 动态执行 必须走显式
   允许名单(带原因), 否则报错;
③ 真源码零命中: 全仓扫一遍必须 0 处; 并把真实事故版(常量搬回尾部)本体复现出来,
   验证守卫确实会在原事故形态上变红。

不依赖时间/网络/环境变量, 无副作用(只在 tmp_path 里造文件)。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_embedded_py_name_order as chk  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SCHEDULE_MONITOR = REPO / "scripts" / "schedule_monitor.sh"
_REAL_NON_PY = dict(chk.NON_PYTHON_ALLOWLIST)
_REAL_UNVER = dict(chk.UNVERIFIABLE_PY_ALLOWLIST)


@pytest.fixture(autouse=True)
def _empty_allowlists(monkeypatch):
    """tmp_path 里造的样本不涉及仓库现有 heredoc ⇒ 清空允许名单, 避免「过期条目」噪声。"""
    monkeypatch.setattr(chk, "NON_PYTHON_ALLOWLIST", {})
    monkeypatch.setattr(chk, "UNVERIFIABLE_PY_ALLOWLIST", {})


def _write(tmp_path: Path, body: str, name: str = "case.sh") -> Path:
    p = tmp_path / "scripts" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def _scan(tmp_path: Path):
    rc, problems, _seen = chk.check_root(tmp_path)
    return rc, "\n".join(problems)


def _py_heredoc(py_src: str, tag: str = "PYEOF") -> str:
    return f"#!/usr/bin/env bash\npython3 - <<'{tag}'\n{py_src}\n{tag}\n"


# ── ① 判别力: 坏样本必须红、好样本必须绿 ────────────────────────────────────
def test_bad_sample_used_before_defined_fails(tmp_path):
    """任务书点名的坏样本: `x = y` 在前、`y = 1` 在后 ⇒ 必须 FAIL。"""
    _write(tmp_path, _py_heredoc("x = y\ny = 1\n"))
    rc, out = _scan(tmp_path)
    assert rc == 1, out
    assert "先使用后定义" in out
    assert "`y`" in out


def test_good_sample_passes(tmp_path):
    """顺序正确(先定义后使用) ⇒ 必须 PASS。"""
    _write(tmp_path, _py_heredoc("y = 1\nx = y\nprint(x)\n"))
    rc, out = _scan(tmp_path)
    assert rc == 0, out
    assert out == ""


def test_undefined_name_is_not_our_business(tmp_path):
    """全模块都没有的定义(外部注入/内置)不归本守卫管 —— 只抓「后面才定义」这一种。"""
    _write(tmp_path, _py_heredoc("x = undefined_forever\n"))
    rc, out = _scan(tmp_path)
    assert rc == 0, out


def test_module_level_loop_reference_flagged(tmp_path):
    """事故同形: 模块级 for 循环体里先用到、常量定义在循环之后 ⇒ 必须 FAIL。"""
    src = "TH = None\n" "for _t in range(1):\n" "    v = THRESHOLD\n" "THRESHOLD = 2\n"
    _write(tmp_path, _py_heredoc(src))
    rc, out = _scan(tmp_path)
    assert rc == 1, out
    assert "THRESHOLD" in out


def test_function_body_reference_is_deferred(tmp_path):
    """函数体里引用后面才定义的模块常量 = 合法(定义时函数体不执行)。"""
    src = "def f():\n    return LATER\nLATER = 1\nprint(f())\n"
    _write(tmp_path, _py_heredoc(src))
    rc, out = _scan(tmp_path)
    assert rc == 0, out


def test_default_arg_reference_is_immediate(tmp_path):
    """默认参数在定义时求值 ⇒ 引用后面才定义的常量是真错误, 必须 FAIL。"""
    src = "def f(v=LATER):\n    return v\nLATER = 1\n"
    _write(tmp_path, _py_heredoc(src))
    rc, out = _scan(tmp_path)
    assert rc == 1, out
    assert "LATER" in out


def test_comprehension_target_not_flagged_as_use(tmp_path):
    """推导式里的循环变量是局部绑定, 不能当「先使用」。"""
    src = "rows = [(a, b) for a, b in [(1, 2)]]\n"
    _write(tmp_path, _py_heredoc(src))
    rc, out = _scan(tmp_path)
    assert rc == 0, out


# ── ② 不许静默放过: 三种无法静态判定的情形必须显式登记 ─────────────────────
def test_non_python_heredoc_must_be_allowlisted(tmp_path, monkeypatch):
    _write(tmp_path, "#!/usr/bin/env bash\ncat > note.txt <<'EOF'\nhello\nEOF\n")
    rc, out = _scan(tmp_path)
    assert rc == 1, out
    assert "未登记的非 Python heredoc" in out

    monkeypatch.setattr(
        chk, "NON_PYTHON_ALLOWLIST", {("scripts/case.sh", "EOF", 1): "测试用纯文本"}
    )
    rc, out = _scan(tmp_path)
    assert rc == 0, out


def test_star_import_must_be_allowlisted(tmp_path, monkeypatch):
    _write(tmp_path, _py_heredoc("from os import *\nprint(getcwd())\n"))
    rc, out = _scan(tmp_path)
    assert rc == 1, out
    assert "from-import *" in out

    monkeypatch.setattr(
        chk, "UNVERIFIABLE_PY_ALLOWLIST",
        {("scripts/case.sh", "PYEOF", 1): "测试用星号导入"},
    )
    rc, out = _scan(tmp_path)
    assert rc == 0, out


def test_exec_must_be_allowlisted(tmp_path, monkeypatch):
    _write(tmp_path, _py_heredoc("code = 'x = 1'\nexec(code)\n"))
    rc, out = _scan(tmp_path)
    assert rc == 1, out
    assert "exec/eval/compile" in out

    monkeypatch.setattr(
        chk, "UNVERIFIABLE_PY_ALLOWLIST",
        {("scripts/case.sh", "PYEOF", 1): "测试用动态执行"},
    )
    rc, out = _scan(tmp_path)
    assert rc == 0, out


def test_stale_allowlist_entry_is_reported(tmp_path, monkeypatch):
    """登记了却扫不到 = 死条目, 同样要报(防允许名单烂成黑洞)。"""
    monkeypatch.setattr(
        chk, "NON_PYTHON_ALLOWLIST", {("scripts/gone.sh", "EOF", 1): "已删除的旧 heredoc"}
    )
    _write(tmp_path, _py_heredoc("x = 1\n"))
    rc, out = _scan(tmp_path)
    assert rc == 1, out
    assert "允许名单过期" in out


def test_unclosed_heredoc_is_reported(tmp_path):
    _write(tmp_path, "#!/usr/bin/env bash\ncat > a.txt <<'EOF'\nhello\n")
    rc, out = _scan(tmp_path)
    assert rc == 1, out
    assert "未登记的非 Python heredoc" in out or "无法 ast 解析" in out


def test_heredoc_in_comment_line_is_ignored(tmp_path):
    """注释行里的 `<<HEREDOC` 不是真 heredoc(ci_selfcheck.sh 有这种行)。"""
    _write(tmp_path, "#!/usr/bin/env bash\n# 用法示例: cat <<HEREDOC 这种写在注释里\necho ok\n")
    rc, out = _scan(tmp_path)
    assert rc == 0, out


# ── ③ 真源码: 全仓零命中 + 原事故形态必须变红 ───────────────────────────────
def test_real_repo_has_zero_hits(monkeypatch):
    """真仓库当前必须 0 处(允许名单用真表, 顺带验证没有过期条目/新漏登记 heredoc)。"""
    monkeypatch.setattr(chk, "NON_PYTHON_ALLOWLIST", _REAL_NON_PY)
    monkeypatch.setattr(chk, "UNVERIFIABLE_PY_ALLOWLIST", _REAL_UNVER)
    rc, problems, seen = chk.check_root(REPO)
    assert rc == 0, "\n".join(problems)
    assert seen, "应当扫到 heredoc, 扫不到说明检测器坏了"


def test_real_incident_shape_is_detected(monkeypatch, tmp_path):
    """把真实事故版复现出来: 常量搬回模块尾部 ⇒ 守卫必须红。

    这是 2026-10-26 P1 事故的原形(NameError 静默 26 天)。守卫若在这份真源码上抓不到,
    就等于没有判别力, 本用例即失效。
    """
    monkeypatch.setattr(chk, "NON_PYTHON_ALLOWLIST", _REAL_NON_PY)
    monkeypatch.setattr(chk, "UNVERIFIABLE_PY_ALLOWLIST", _REAL_UNVER)
    text = SCHEDULE_MONITOR.read_text(encoding="utf-8")
    lines = text.splitlines()
    const = "MISSED_CONTINUOUS_THRESHOLD = 2"
    hits = [i for i, ln in enumerate(lines) if ln.strip() == const]
    assert len(hits) == 1, f"预期模块级定义恰好 1 处, 实得 {hits}"
    moved = lines.pop(hits[0])
    end = max(i for i, ln in enumerate(lines) if ln.strip() == "PYEOF")
    lines.insert(end, moved)

    bad = tmp_path / "scripts" / "schedule_monitor.sh"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("\n".join(lines) + "\n", encoding="utf-8")

    rc, problems, _ = chk.check_root(tmp_path)
    joined = "\n".join(problems)
    assert rc == 1, "事故版必须被判红"
    assert "先使用后定义" in joined
    assert "MISSED_CONTINUOUS_THRESHOLD" in joined