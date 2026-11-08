"""turnover 命令发现回归：复用现有审计，不执行上传、锁、通知或生产请求。"""
from pathlib import Path
import socket

import pytest
import r2_lock_gradient_audit as audit

ROOT = Path(__file__).resolve().parents[2]
TURNOVER = ROOT / "scripts/turnover_backfill.sh"
OWNER = "scripts/turnover_backfill.sh"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("静态审计测试禁止网络连接")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


@pytest.mark.parametrize("scope", ["small", "large"])
def test_real_turnover_command_line_matches(scope):
    # 取真实调用行，不能用手写样例替代当前脚本接线。
    lines = [line for line in TURNOVER.read_text().splitlines()
             if not line.lstrip().startswith("#")
             and f"scripts/upload_r2.py upload-turnover {scope} " in line]
    assert len(lines) == 1, lines
    match = audit._WRITE_INVOKE.search(lines[0])
    assert match is not None, lines[0]
    assert match.group(1) == "upload-turnover"


def test_actual_callers_include_turnover():
    assert OWNER in audit._upload_callers()


@pytest.fixture
def isolated_repo(tmp_path, monkeypatch):
    # 只在临时树增加写者。原文件全是只读符号链接，不修改、执行链接目标。
    root = tmp_path / "repo"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    for source in (ROOT / "scripts").iterdir():
        (scripts / source.name).symlink_to(source, target_is_directory=source.is_dir())
    monkeypatch.setattr(audit, "REPO", root)
    rows, errors = audit.audit()
    assert errors == [], errors
    assert not any(row["status"] == "FAIL" for row in rows)
    return root


@pytest.mark.parametrize("scope", ["small", "large"])
def test_unregistered_turnover_writer_fails_audit(isolated_repo, capsys, scope):
    unknown = isolated_repo / "scripts/unregistered_turnover_writer.sh"
    unknown.write_text(f'"$PY" scripts/upload_r2.py upload-turnover {scope}\n')
    owner = f"scripts/{unknown.name}"
    # 不注入域字面量：必须由真实命令发现层报错，不能靠别的域检查碰巧拦住。
    assert owner in audit._upload_callers()
    rows, errors = audit.audit()
    matching = [row for row in rows if row["owner"] == owner]
    assert len(matching) == 1
    assert matching[0]["status"] == "FAIL"
    assert "上传调用方未登记域/锁等待" in matching[0]["note"]
    assert len(errors) == 1 and owner in errors[0]
    assert "未登记" in errors[0]
    # 真正的审计入口必须返回非零，不能只在内部列表加一条但 CLI 仍绿。
    assert audit.main(["--check-doc", "--quiet"]) == 1
    output = capsys.readouterr().out
    assert "FAIL=1" in output and owner in output and "未登记" in output


@pytest.mark.parametrize("old,new", [
    ("R2_LOCK_WAIT_BUDGET=1800", "R2_LOCK_WAIT_BUDGET=1799"),
    ("R2_WORK_BUDGET_INTRADAY=900", "R2_WORK_BUDGET_INTRADAY=899"),
    ("R2_WORK_BUDGET=3120", "R2_WORK_BUDGET=3119"),
    ("run_to 2760 env", "run_to 2759 env"),
    ("run_to 4980 env", "run_to 4979 env"),
])
def test_each_existing_budget_mutation_still_fails(tmp_path, monkeypatch, capsys, old, new):
    # 保留原来的五个独立变异；不缩短、不扩张真实预算，不运行 shell 主体。
    _rows, errors = audit.audit()
    assert errors == [], errors
    source = TURNOVER.read_text()
    assert source.count(old) == 1
    mutant = tmp_path / "turnover-mutant.sh"
    mutant.write_text(source.replace(old, new, 1))
    monkeypatch.setattr(audit, "TB_SH", mutant)
    errors = []
    audit._check_turnover_literals(errors)
    assert any("改任一边漏另一边" in error for error in errors), errors
    assert audit.main(["--check-doc", "--quiet"]) == 1
    output = capsys.readouterr().out
    assert "FAIL 明细" in output and "turnover" in output and "改任一边漏另一边" in output


def test_existing_turnover_budget_rows_unchanged():
    rows = [row for row in audit.SITES if row[0] == OWNER]
    assert len(rows) == 2
    assert [(row[2], row[3], row[4], row[5]) for row in rows] == [
        ("data", 1800, 2760, "trade-turnover-backfill.service"),
        ("data", 1800, 4980, "trade-turnover-backfill.service"),
    ]
    errors = []
    audit._check_turnover_literals(errors)
    assert errors == [], errors
