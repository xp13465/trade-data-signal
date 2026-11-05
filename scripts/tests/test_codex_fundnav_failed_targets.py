"""首轮失败对象与摘要生命周期回归；业务壳只运行 tmp_path 副本，出口先正控。"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import smtplib
import socket
import sqlite3
import subprocess
import sys
from urllib.parse import unquote

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]


@pytest.fixture
def case(tmp_path, monkeypatch):
    popen, connect = subprocess.Popen, sqlite3.connect

    def deny(*args, **kwargs):
        raise AssertionError("业务出口已拦截")

    def local_db(path, *args, **kwargs):
        value = unquote(str(path).removeprefix("file:").split("?", 1)[0])
        if not Path(value).resolve().is_relative_to(tmp_path):
            return deny()
        return connect(path, *args, **kwargs)

    monkeypatch.setattr(socket, "socket", deny)
    monkeypatch.setattr(smtplib, "SMTP", deny)
    monkeypatch.setattr(subprocess, "Popen", deny)
    monkeypatch.setattr(os, "system", deny)
    monkeypatch.setattr(sqlite3, "connect", local_db)
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    for attempt in (socket.socket, smtplib.SMTP, lambda: subprocess.run(["forbidden"]),
                    lambda: os.system("forbidden"), lambda: sqlite3.connect(tmp_path.parent / "forbidden.db")):
        with pytest.raises(AssertionError, match="业务出口"):
            attempt()

    spec = importlib.util.spec_from_file_location("fundnav_targets_under_test", SCRIPTS / "check_data_integrity.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    data = tmp_path / "static-site/data"
    nav = data / "nav_bucket"
    nav.mkdir(parents=True)
    db = tmp_path / "data/public_fund.db"
    db.parent.mkdir()
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE fund_daily_nav(fund_code TEXT, date TEXT, unit_nav REAL, acc_nav REAL)")
        for i in range(31):
            code = f"{i:06d}"
            date = "20261103" if i == 0 else "20261104"
            payload = dict(code=code, name="测试基金", source="test", count=1, date=date,
                           nav=[[date, 1.0, 1.0]])
            (nav / f"{i:02x}.json").write_text(json.dumps({code: payload}), encoding="utf-8")
            con.execute("INSERT INTO fund_daily_nav VALUES (?, '20261104', 1, 1)", (code,))
    monkeypatch.setenv("REPO", str(tmp_path))
    monkeypatch.setenv("GIT_REPO", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(m, "_db_candidates", lambda name: [db])
    monkeypatch.setattr(m, "run_all_checks", lambda d, r: [m.check_fund_nav(d)])
    import random
    monkeypatch.setattr(random, "sample", lambda population, n: list(population)[:n])
    monkeypatch.setattr(random, "choice", lambda population: population[0])

    def cli(*args, directory=data):
        with monkeypatch.context() as patch:
            patch.setattr(sys, "argv", ["check_data_integrity.py", "--data-dir", str(directory), *map(str, args)])
            return m.main()

    def run(script, env, bash=None):
        assert Path(script).resolve().is_relative_to(tmp_path)
        bash = bash or shutil.which("bash")
        assert bash, "回归需要 bash"
        with monkeypatch.context() as patch:
            patch.setattr(subprocess, "Popen", popen)
            return subprocess.run([bash, str(script)], env=env, capture_output=True, text=True, timeout=20)

    return dict(m=m, root=tmp_path, data=data, db=db, cli=cli, run=run, monkeypatch=monkeypatch)


def first(case):
    path = case["root"] / "first.json"
    assert case["cli"]("--deploy-mode", "--summary-file", path) == 1
    return path


def miss(case):
    import random
    case["monkeypatch"].setattr(random, "sample", lambda population, n: list(population)[-n:] if n else [])


def change(case, date="20261104", value=1.0):
    path = case["data"] / "nav_bucket/00.json"
    d = json.loads(path.read_text())
    d["000000"].update(date=date, nav=[[date, value, 1.0]])
    path.write_text(json.dumps(d))


def test_known_failure_survives_new_random_draw_and_final_check(case):
    path = first(case)
    summary = json.loads(path.read_text())
    assert summary["fundnav_failed_items"] == [dict(bucket="00.json", code="000000", direction="db_ahead")]
    miss(case)
    assert case["cli"]("--fundnav-stale-probe") == 0  # 旧漏样路径
    assert case["cli"]("--fundnav-stale-probe", "--fundnav-failed-summary", path) == 3
    assert case["cli"]("--deploy-mode") == 0
    assert case["cli"]("--deploy-mode", "--fundnav-failed-summary", path) == 1
    change(case)
    assert case["cli"]("--deploy-mode", "--fundnav-failed-summary", path) == 0


@pytest.mark.parametrize("date,value,direction", [("20261105", 1, "db_behind"), ("20261104", 2, "unknown")])
def test_reverse_and_unknown_never_authorize_rebuild(case, date, value, direction):
    change(case, date, value)
    path = first(case)
    assert json.loads(path.read_text())["fundnav_failed_items"][0]["direction"] == direction
    assert case["cli"]("--fundnav-stale-probe", "--fundnav-failed-summary", path) == 0


@pytest.mark.parametrize("kind", ["directory", "db", "missing_context", "bad_json"])
def test_bound_summary_rejects_wrong_context(case, kind, capsys):
    path = first(case)
    change(case)
    data = case["data"]
    if kind == "directory":
        data = case["root"] / "other-data"
        shutil.copytree(case["data"], data)
    elif kind == "db":
        other = case["root"] / "other.db"
        shutil.copyfile(case["db"], other)
        case["monkeypatch"].setattr(case["m"], "_find_public_fund_db", lambda: other)
    elif kind == "missing_context":
        d = json.loads(path.read_text()); d.pop("fundnav_context"); path.write_text(json.dumps(d))
    else:
        path.write_text("{")
    assert case["cli"]("--fundnav-verify-failed", "--fundnav-failed-summary", path, directory=data) == 1
    assert "首轮 summary 不可用" in capsys.readouterr().err


@pytest.mark.parametrize("args", [["--fundnav-verify-failed"], ["--fundnav-verify-failed", "--fundnav-failed-summary", "unused"]])
def test_missing_parameters_are_readable(case, args, capsys):
    case["monkeypatch"].setattr(sys, "argv", ["check_data_integrity.py", *args])
    with pytest.raises(SystemExit) as error:
        case["m"].main()
    assert error.value.code == 2
    err = capsys.readouterr().err
    assert "--data-dir" in err and "Traceback" not in err


def shell_tools(case):
    """有限/tmp命令桩；没有系统PATH兜底，也不调用真实锁/重出/通知。"""
    root = case["root"]
    bindir = root / "bin"
    bindir.mkdir()
    body = f"#!{sys.executable} -I\n" + '''import os, sys, pathlib, tempfile, time
root=pathlib.Path(os.environ['REPO']).resolve()
def local(value):
 p=pathlib.Path(value).resolve(); assert p.is_relative_to(root); return p
name=pathlib.Path(sys.argv[0]).name; a=sys.argv[1:]
if name=='dirname': print(str(pathlib.Path(a[-1]).parent))
elif name=='date': print('1200')
elif name=='sleep': time.sleep(.01)
elif name=='mktemp':
 fd,p=tempfile.mkstemp(dir=root);os.close(fd);print(p)
elif name=='tail': print(local(a[-1]).read_text(),end='')
elif name=='rm':
 for f in a:
  if not f.startswith('-'): local(f).unlink(missing_ok=True)
else: print('EGRESS_BLOCKED',file=sys.stderr);sys.exit(97)
'''
    for name in ("dirname", "date", "sleep", "mktemp", "tail", "rm", "curl", "sendmail", "ssh"):
        p = bindir / name; p.write_text(body); p.chmod(0o700)
    env = dict(PATH=str(bindir), REPO=str(root), GIT_REPO=str(root))
    # 正控必须先于业务壳：三个外发桩均实际拒绝。
    control = root / "egress-controls.sh"
    control.write_text("\n".join(str(bindir / name) for name in ("curl", "sendmail", "ssh")) + "\n")
    r = case["run"](control, env)
    assert r.returncode == 97 and r.stderr.count("EGRESS_BLOCKED") == 3
    return env


@pytest.mark.parametrize("mode,expected", [("good", 0), ("noop", 12), ("fail", 12), ("behind", 10), ("unknown", 10),
                                          ("legacy-good", 0), ("legacy-fresh", 10), ("legacy-dry", 13), ("legacy-fail", 12)])
def test_copied_selfheal_revalidates_original_object(case, mode, expected):
    if mode == "behind": change(case, "20261105")
    if mode == "unknown": change(case, "20261104", 2)
    path = first(case)
    spaced_path = path.with_name("first summary with spaces.json")
    path.rename(spaced_path)
    path = spaced_path
    legacy = mode.startswith("legacy-")
    if mode == "legacy-fresh": change(case)
    env = shell_tools(case)
    root = case["root"]
    scripts = root / "scripts"
    (scripts / "lib").mkdir(parents=True)
    for name in ("fund_nav_selfheal.sh", "check_data_integrity.py"):
        shutil.copyfile(SCRIPTS / name, scripts / name)
    (scripts / "lib/repo_paths.sh").write_text('resolve_repo() { [ "$REPO" = "$GIT_REPO" ] || exit 96; }\n')
    py = root / ".venv/bin/python"; py.parent.mkdir(parents=True)
    py.write_text(f"#!{sys.executable} -I\n" + '''import sys,os,pathlib,json,sqlite3,random,importlib.util,socket,smtplib,subprocess
def deny(*a,**k): raise AssertionError('EGRESS_BLOCKED')
socket.socket=smtplib.SMTP=subprocess.Popen=deny
for f in (socket.socket,smtplib.SMTP,lambda:subprocess.run(['forbidden'])):
 try:f()
 except AssertionError:pass
 else:raise AssertionError('trap failed')
root=pathlib.Path(os.environ['REPO']).resolve();p=pathlib.Path(sys.argv[1]).resolve();assert p.is_relative_to(root)
if p.name=='with_lock.py':
 (root/'repair.marker').write_text('once')
 if os.environ['REPAIR_MODE']=='fail':sys.exit(9)
 if os.environ['REPAIR_MODE']=='good':
  f=root/'static-site/data/nav_bucket/00.json';d=json.loads(f.read_text());d['000000'].update(date='20261104',nav=[['20261104',1.,1.]]);f.write_text(json.dumps(d))
 sys.exit(0)
assert p.name=='check_data_integrity.py'
random.sample=lambda a,n:(list(a)[:n] if os.environ.get('LEGACY_DRAW')=='1' else list(a)[-n:]) if n else []
random.choice=lambda a:a[0]
spec=importlib.util.spec_from_file_location('copied_check',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m._db_candidates=lambda name:[root/'data/public_fund.db']
sys.argv=sys.argv[1:];sys.exit(m.main())
''')
    py.chmod(0o700)
    env.update(FUNDNAV_SELFHEAL_SUMMARY=str(path), FUNDNAV_SELFHEAL_NOW="1200",
               FUNDNAV_SELFHEAL_ASYNC_UPLOAD="0", FUNDNAV_SELFHEAL_TIMEOUT="30",
               FUNDNAV_SELFHEAL_LOCK_WAIT="0", FUNDNAV_SELFHEAL_LOCK=str(root / "lock"), REPAIR_MODE=mode)
    if legacy:
        if not Path("/bin/bash").exists(): pytest.skip("本机没有 /bin/bash")
        env.pop("FUNDNAV_SELFHEAL_SUMMARY")
        env.update(LEGACY_DRAW="1", REPAIR_MODE="fail" if mode == "legacy-fail" else "good")
        if mode == "legacy-dry": env["FUNDNAV_SELFHEAL_DRY_RUN"] = "1"
    if mode == "noop": env["LC_ALL"] = "en_US.UTF-8"
    r = case["run"](scripts / "fund_nav_selfheal.sh", env, bash="/bin/bash" if legacy else None)
    assert r.returncode == expected, (r.stdout, r.stderr)
    if mode == "legacy-good": assert "探针已转 0" in r.stdout
    if mode == "noop": assert "首轮失败对象复验仍失败 rc=1，不触发同步/上传" in r.stdout
    assert (root / "repair.marker").exists() == (mode in {"good", "noop", "fail", "legacy-good", "legacy-fail"})


@pytest.mark.parametrize("rc,record_off,early,archive_failure,explicit", [
    (0, 0, False, False, False), (7, 0, False, False, False),
    (9, 1, False, False, False), (5, 1, True, False, False),
    (6, 1, False, True, False), (0, 1, False, False, True),
    (11, 0, False, False, "exec"), (127, 1, False, False, "failed_exec")])
def test_summary_archive_cleanup_preserves_exit_code(case, rc, record_off, early, archive_failure, explicit):
    root = case["root"]
    env = shell_tools(case)
    scripts = root / "scripts"; scripts.mkdir()
    (scripts / "deploy_fail_tracker.py").write_text("# tmp-only tracker stub\n")
    first_path, final_path = root / "summary", root / "summary.final"
    foreign = root / "other-invocation.json"; foreign.write_text("{}")
    for p, phase in ((first_path, "first"), (final_path, "final")):
        p.write_text(json.dumps(dict(phase=phase, fundnav_failed_items=["original-object"])))
        p.with_name(p.name + ".tmp").write_text("temporary")
    source = (SCRIPTS / "deploy.sh").read_text()
    start = source.index("_deploy_integrity_summary_cleanup() {")
    end = source.index("trap _deploy_record_result EXIT", start) + len("trap _deploy_record_result EXIT")
    log = root if archive_failure else root / "deploy.log"
    definitions = f'DEPLOY_RECORD_OFF={record_off}\n'
    if not early:
        definitions += f'PY={json.dumps(sys.executable)}\nLOG={json.dumps(str(log))}\n_INTEGRITY_FIRST_SUMMARY={json.dumps(str(first_path))}\n_INTEGRITY_SUMMARY={json.dumps(str(final_path))}\n'
    body = "_deploy_integrity_summary_cleanup\n_deploy_integrity_summary_cleanup\n" if explicit else ""
    if explicit == "exec":
        stub = scripts / "exec-stub.py"; stub.write_text(f"raise SystemExit({rc})\n")
        body += 'exec "$PY" "$REPO/scripts/exec-stub.py"\n'
    elif explicit == "failed_exec":
        body += 'exec "$REPO/missing-command"\n'
        # bash 对不可执行/不存在的绝对路径在平台间可能返回126或127，比较本机原始值。
        control = root / "exec-control.sh"
        control.write_text('exec "$REPO/missing-command"\n')
        rc = case["run"](control, env).returncode
        assert rc in (126, 127)
    script = root / "cleanup-test.sh"
    script.write_text("set -u\n" + definitions + source[start:end] + "\n" + body + f"exit {rc}\n")
    r = case["run"](script, env)
    assert r.returncode == rc, (r.stdout, r.stderr)
    assert foreign.exists()
    for p in (first_path, final_path):
        assert p.exists() == (early or archive_failure)
        assert p.with_name(p.name + ".tmp").exists() == (early or archive_failure)
    if not early and not archive_failure:
        records = [json.loads(l.split(" ", 1)[1]) for l in log.read_text().splitlines() if l.startswith("[integrity-summary]")]
        assert [v["phase"] for v in records] == ["first", "final"]
        assert all(v["summary"]["fundnav_failed_items"] == ["original-object"] for v in records)
    if archive_failure:
        assert "保留原文件" in r.stderr
