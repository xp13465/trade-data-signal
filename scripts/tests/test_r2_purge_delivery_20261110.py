"""真实函数/收尾 shell 的隔离回归；不加载 uploader 顶层或真实凭证。"""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import types

import pytest
from test_codex_r2_alert_delivery import sandbox  # 复用已有零外发/越界写正控

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/upload_r2.py"


def functions(*names):
    tree = ast.parse(SOURCE.read_text())
    return compile(ast.Module(body=[n for n in tree.body
                                   if isinstance(n, ast.FunctionDef) and n.name in names],
                              type_ignores=[]), str(SOURCE), "exec")


def namespace(sb, responses=(), secret="fixture"):
    calls = []
    replies = iter(responses)

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, method, path, body, **kwargs):
            assert (method, path) == ("POST", "/api/purge-cache")
            self.keys = json.loads(body)["keys"]
            calls.append(self.keys)

        def getresponse(self):
            status, payload = next(replies, (200, {"purged": len(self.keys), "total": len(self.keys)}))
            body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            return types.SimpleNamespace(status=status, read=lambda: body)

        def close(self):
            pass

    notify = types.ModuleType("notify")
    notify.send = lambda *a, **k: None
    notify.check_dedup = lambda *a, **k: True
    notify.update_dedup = lambda *a, **k: None
    sb.mp.setitem(sys.modules, "notify", notify)
    sb.mp.setenv("PURGE_SECRET", secret)
    ns = dict(os=os, json=json, hashlib=hashlib,
              sys=types.SimpleNamespace(path=[], exit=sys.exit), ROOT=sb.tmp,
              STATIC_DIR=sb.tmp / "static-site", time=types.SimpleNamespace(sleep=lambda n: None),
              http=types.SimpleNamespace(client=types.SimpleNamespace(HTTPSConnection=Connection)),
              R2_UPLOAD_HTTP_TIMEOUT=30, _CTX=None)
    exec(functions("purge_cache", "cmd_purge_low_freq", "_data_cache_ttl"), ns)
    return ns, calls


@pytest.mark.parametrize("secret,keys,expected", [("", [], True), ("", ["data/low.json"], False),
                                                 ("fixture", [], True), ("fixture", ["data/low.json"], True)])
def test_empty_missing_secret_and_success(sandbox, secret, keys, expected):
    ns, calls = namespace(sandbox, secret=secret)
    failed = []
    assert ns["purge_cache"](keys, failed_keys=failed) is expected
    assert failed == ([] if expected else ["/data/low.json"])
    assert len(calls) == (1 if secret and keys else 0)


@pytest.mark.parametrize("reply", [(503, b"unavailable"), (200, b"not-json"),
                                   (200, {"purged": 0, "total": 1}),
                                   (200, {"purged": 1}), (200, {"purged": True, "total": 1})])
def test_failed_or_incomplete_response_is_not_success(sandbox, reply):
    ns, calls = namespace(sandbox, [reply] * 3)
    failed = []
    assert ns["purge_cache"](["data/low.json"], failed_keys=failed) is False
    assert failed == ["/data/low.json"]
    assert calls == [["/data/low.json"]] * 3


def test_partial_batches_preserve_exact_failure_keys(sandbox):
    ns, calls = namespace(sandbox, [(200, {"purged": 30, "total": 30})] + [(503, b"fixture")] * 3)
    failed = []
    keys = [f"data/k{i}.json" for i in range(31)]
    assert ns["purge_cache"](keys, failed_keys=failed) is False
    assert failed == ["/data/k30.json"]
    assert calls[0] == ["/" + k for k in keys[:30]]
    assert calls[1:] == [["/data/k30.json"]] * 3


@pytest.mark.parametrize("success", [False, True])
def test_cli_receipt_has_fixed_request_identity_and_real_result(sandbox, success, capsys):
    ns, _ = namespace(sandbox, secret="fixture" if success else "")
    data = ns["STATIC_DIR"] / "data"
    data.mkdir(parents=True)
    (data / "low.json").write_text("{}")
    (data / "boot.json").write_text("{}")
    receipt = sandbox.tmp / "receipt.json"
    sandbox.mp.setenv("R2_PURGE_RESULT_PATH", str(receipt))
    sandbox.mp.setenv("R2_PURGE_RUN_ID", "fixture-round")
    assert ns["cmd_purge_low_freq"]() is success
    result = json.loads(receipt.read_text())
    assert result["run_id"] == "fixture-round"
    assert result["requested_keys"] == ["/data/low.json"]
    assert result["request_sha256"] == hashlib.sha256(b'["/data/low.json"]').hexdigest()
    assert result["failed_keys"] == ([] if success else ["/data/low.json"])
    assert result["status"] == ("complete" if success else "failed")
    assert "PURGE_REQUEST:" in capsys.readouterr().out


def test_interrupted_command_keeps_pending_exact_request(sandbox):
    ns, _ = namespace(sandbox)
    data = ns["STATIC_DIR"] / "data"
    data.mkdir(parents=True)
    (data / "low.json").write_text("{}")
    receipt = sandbox.tmp / "interrupted.json"
    sandbox.mp.setenv("R2_PURGE_RESULT_PATH", str(receipt))

    def interrupt(*a, **kw):
        raise KeyboardInterrupt

    ns["purge_cache"] = interrupt
    with pytest.raises(KeyboardInterrupt):
        ns["cmd_purge_low_freq"]()
    result = json.loads(receipt.read_text())
    assert result["status"] == "pending"
    assert result["requested_keys"] == result["failed_keys"] == ["/data/low.json"]


@pytest.mark.parametrize("success,code", [(True, 0), (False, 1)])
def test_actual_cli_dispatch_uses_purge_result(success, code):
    dispatch = [n for n in ast.walk(ast.parse(SOURCE.read_text()))
                if isinstance(n, ast.If) and ast.unparse(n.test) == "cmd == 'purge-low-freq'"][-1]
    with pytest.raises(SystemExit) as exc:
        exec(compile(ast.Module(body=dispatch.body, type_ignores=[]), "actual CLI dispatch", "exec"),
             {"sys": sys, "cmd_purge_low_freq": lambda: success})
    assert exc.value.code == code


def test_independent_cache_lock_has_invalidate_before_publish_counterexample(sandbox):
    """反证实际data-large只清/r2/，不能据零PUT就拆末尾purge锁。"""
    ns, _ = namespace(sandbox)
    key = "data/kelly_loss_features.json"
    remote = {key: "old"}
    cache = {}
    calls = []

    def invalidate(keys, cache_prefix="/"):
        calls.append(cache_prefix)
        for k in keys:
            cache.pop(cache_prefix + k, None)

    def upload(*a, **kw):
        remote[key] = "new"
        return 1, 1, [], [key]

    ns.update(_incremental_upload=upload, _channel_on_fail=lambda *a: None,
              purge_cache=invalidate)
    exec(functions("cmd_upload_data_large"), ns)
    assert ns["_data_cache_ttl"]("/" + key) == 3600
    invalidate([key])                 # 独立cache锁允许早清
    cache["/" + key] = remote[key]    # 并发读者在PUT前缓存旧版
    ns["cmd_upload_data_large"]()    # 真实上传后清缓存逻辑
    assert calls == ["/", "/r2/"]
    assert remote[key] == "new" and cache["/" + key] == "old"


@pytest.mark.parametrize("purge_rc", [0, 1, 124])
def test_async_purge_failure_keeps_bounded_catchup_and_returns_nonzero(tmp_path, purge_rc):
    shell = (ROOT / "scripts/r2_upload_async.sh").read_text()
    # 执行真实末尾编排；通道及通知是临时桩，绝不执行生产shell前缀。
    tail = shell[shell.index("# 初次: 数据通道"):]
    fake = tmp_path / "python-stub"
    fake.write_text('#!/bin/sh\nexit 0\n')
    fake.chmod(0o700)
    marker = tmp_path / "pending"
    marker.touch()
    log = tmp_path / "run.log"
    calls = tmp_path / "calls"
    prelude = '''set -u
R2_FAIL=""; R2_DELIVERY_FAIL=0; R2_PURGE_FAIL=0
R2_LOCK_WAIT_N=0; R2_LOCK_WAIT_MAX=0
upload_data_channels() { echo data >> "$CALLS"; }
run_r2_upload() { echo "$1" >> "$CALLS"; if [ "$1" = purge-low-freq ]; then return "$PURGE_RC"; fi; }
finalize_verify() { echo finalize >> "$CALLS"; }
'''
    env = {**os.environ, "LOG": str(log), "CALLS": str(calls), "PY": str(fake),
           "REPO": str(tmp_path), "PENDING_FILE": str(marker), "PURGE_RC": str(purge_rc)}
    r = subprocess.run(["bash"], input=prelude + tail, env=env, text=True,
                       capture_output=True, timeout=8)
    assert r.returncode == (1 if purge_rc else 0), r.stdout + r.stderr
    assert calls.read_text().splitlines() == ["data", "verify-r2", "purge-low-freq", "finalize", "data", "finalize"]
    assert f"退出码={1 if purge_rc else 0}" in log.read_text()


def test_async_retains_lock_event_snapshots_without_duplicates(tmp_path):
    source = (ROOT / "scripts/r2_upload_async.sh").read_text()
    helper = source[source.index("_mirror_r2_lock_events() {"):source.index("_run_r2_upload_impl() {")]
    events = tmp_path / "events.log"
    log = tmp_path / "main.log"
    events.write_text('business\nR2_LOCK: {"event":"wait"}\n')
    script = helper + '''
_R2_LOCK_EVENTS_SEEN=0
_mirror_r2_lock_events "$EVENTS"
_mirror_r2_lock_events "$EVENTS"
printf '%s\n' 'R2_LOCK: {"event":"released"}' >> "$EVENTS"
_mirror_r2_lock_events "$EVENTS"
'''
    r = subprocess.run(["bash"], input=script, env={**os.environ, "EVENTS": str(events), "LOG": str(log)},
                       text=True, capture_output=True, timeout=5)
    assert r.returncode == 0, r.stderr
    assert log.read_text().splitlines() == ['R2_LOCK: {"event":"wait"}', 'R2_LOCK: {"event":"released"}']


@pytest.mark.parametrize("periodic_first", [False, True])
@pytest.mark.parametrize("buried", [False, True])
def test_kill_tail_and_mirror_have_one_structured_exit(tmp_path, periodic_first, buried):
    source = (ROOT / "scripts/r2_upload_async.sh").read_text()
    helpers = []
    for name in ("_dump_kill_tail", "_mirror_r2_lock_events"):
        start = source.index(name + "() {")
        end = source.index("\n}\n", start) + 3
        helpers.append(source[start:end])
    event = 'R2_LOCK: {"event":"wait","stage":"global"}'
    events, log = tmp_path / "events", tmp_path / "persistent"
    # 两条文本完全相同但来源行不同的真实事件，不能按文本去重。
    events.write_text(event + "\n" + event + "\n" + ("business\n" * (80 if buried else 1)))
    script = "\n".join(helpers) + '''
_R2_LOCK_EVENTS_SEEN=0
R2_KILL_CTX=''
if [ "$PERIODIC_FIRST" = 1 ]; then _mirror_r2_lock_events "$EVENTS"; fi
_dump_kill_tail "$EVENTS" fixture
_mirror_r2_lock_events "$EVENTS"
_mirror_r2_lock_events "$EVENTS"
'''
    env = {**os.environ, "EVENTS": str(events), "LOG": str(log), "PERIODIC_FIRST": str(int(periodic_first))}
    r = subprocess.run(["bash"], input=script, env=env, text=True, capture_output=True, timeout=5)
    assert r.returncode == 0, r.stderr
    assert [s for s in log.read_text().splitlines() if s.startswith("R2_LOCK: ")] == [event, event]
    assert "business" in log.read_text()
    # 再追加一条相同文本的新事件；游标按来源行前进，后一次kill/mirror也只能增加这一条。
    events.write_text(events.read_text() + event + "\n")
    script = "\n".join(helpers) + '''
_R2_LOCK_EVENTS_SEEN=2
R2_KILL_CTX=''
_dump_kill_tail "$EVENTS" fixture
_mirror_r2_lock_events "$EVENTS"
_mirror_r2_lock_events "$EVENTS"
'''
    r = subprocess.run(["bash"], input=script, env=env, text=True, capture_output=True, timeout=5)
    assert r.returncode == 0, r.stderr
    assert [s for s in log.read_text().splitlines() if s.startswith("R2_LOCK: ")] == [event] * 3


LOCK_CHILD = r'''
import ast,atexit,datetime,fcntl,json,os,re,sys,time
from pathlib import Path
root=Path(sys.argv[1]); source=Path(sys.argv[2]); role=sys.argv[3]
def guard(event,args):
 if event in ('socket.connect','socket.getaddrinfo','subprocess.Popen','os.system'):raise RuntimeError(event)
sys.addaudithook(guard)
sys.path.insert(0,str(source.parent));import r2_lock_paths as _rlp
os.environ['R2_UPLOAD_LOCK']=str(root/'upload.lock');os.environ['R2_UPLOAD_LOCK_TIMEOUT']='8'
os.environ.pop('R2_UPLOAD_LOCK_DOMAIN',None)
if role in ('writer','exception-waiter','domain-probe'):os.environ['R2_UPLOAD_LOCK_DOMAIN']='data'
_LOCK_DOMAIN_ENV=_rlp.DOMAIN_ENV;_LOCK_DOMAIN_RE=re.compile(r'^[a-z0-9][a-z0-9_-]{0,31}$');_BARRIER_FDS={};_R2_LOCK_OBSERVATIONS={};_R2_LOCK_HEARTBEAT_SECS=30
probe_lock_holder=lambda p:'pid=424242 python --token ARGV_MUST_NOT_APPEAR'
names={'_lock_domain','_domain_upload_lock_path','_global_upload_lock_path','_release_r2_upload_lock','_acquire_r2_upload_lock','_acquire_lock_for_command','_r2_lock_event','_r2_lock_close','_r2_lock_release_at_exit'}
exec(compile(ast.Module(body=[n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'actual lock functions','exec'))
atexit.register(_r2_lock_release_at_exit)
sys.argv=['upload_r2.py','upload-data-large' if role=='writer' else 'purge-low-freq','ARGV_MUST_NOT_APPEAR']
os.environ['PURGE_SECRET']='ENV_MUST_NOT_APPEAR'
original_event=_r2_lock_event
def _r2_lock_event(fd,event,reason=''):
 original_event(fd,event,reason)
 state=_R2_LOCK_OBSERVATIONS.get(fd,{})
 if role=='exception-waiter' and state.get('stage')=='domain' and event=='acquired':(root/'domain-held').touch()
 if role=='exception-waiter' and state.get('stage')=='global' and event=='wait':(root/'waiting-global').touch()
def wait(name):
 deadline=time.monotonic()+10
 while not (root/name).exists():
  assert time.monotonic()<deadline,name;time.sleep(.01)
if role=='writer':
 fd=_acquire_r2_upload_lock();(root/'writer-ready').touch();wait('release-writer');(root/'remote').write_text('new');_release_r2_upload_lock(fd)
elif role=='global-holder':
 fd=_acquire_r2_upload_lock();(root/'global-held').touch();wait('release-global');_release_r2_upload_lock(fd)
elif role=='exception-waiter':
 fd=_acquire_r2_upload_lock();raise RuntimeError('isolated work exception')
elif role=='domain-probe':
 _acquire_r2_upload_lock(timeout=0)
elif role=='purger':
 (root/'purger-started').touch();fd=_acquire_lock_for_command('purge-low-freq',[]);(root/'cache').unlink(missing_ok=True);(root/'purged').touch();_release_r2_upload_lock(fd)
else:
 (root/'cache').write_text((root/'remote').read_text());(root/'reader-done').touch()
'''


def test_three_processes_preserve_publish_then_invalidate(tmp_path):
    (tmp_path / "remote").write_text("old")
    procs = []

    def start(role):
        p = subprocess.Popen([sys.executable, "-c", LOCK_CHILD, str(tmp_path), str(SOURCE), role],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        procs.append(p)
        return p

    def wait(name):
        deadline = time.monotonic() + 6
        while not (tmp_path / name).exists():
            assert time.monotonic() < deadline, name
            time.sleep(.01)

    try:
        start("writer"); wait("writer-ready")
        start("purger"); wait("purger-started")
        start("reader"); wait("reader-done")
        assert not (tmp_path / "purged").exists()
        assert (tmp_path / "cache").read_text() == "old"
        (tmp_path / "release-writer").touch()
        for p in procs:
            out, err = p.communicate(timeout=12)
            assert p.returncode == 0, out + err
            assert 'ARGV_MUST_NOT_APPEAR' not in err and 'ENV_MUST_NOT_APPEAR' not in err
        assert (tmp_path / "remote").read_text() == "new"
        assert (tmp_path / "purged").exists() and not (tmp_path / "cache").exists()
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
            p.communicate(timeout=3)


def test_three_processes_domain_held_while_global_waits_and_exception_releases(tmp_path):
    procs = []
    logs = {}

    def start(role):
        p = subprocess.Popen([sys.executable, "-c", LOCK_CHILD, str(tmp_path), str(SOURCE), role],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        procs.append(p)
        return p

    def wait(name):
        deadline = time.monotonic() + 6
        while not (tmp_path / name).exists():
            assert time.monotonic() < deadline, name
            time.sleep(.01)

    try:
        holder = start("global-holder"); wait("global-held")
        waiter = start("exception-waiter"); wait("domain-held"); wait("waiting-global")
        observer = start("domain-probe")
        _, logs["observer"] = observer.communicate(timeout=6)
        assert observer.returncode == 1
        (tmp_path / "release-global").touch()
        for name, p in [("holder", holder), ("waiter", waiter)]:
            _, logs[name] = p.communicate(timeout=8)
        assert holder.returncode == 0 and waiter.returncode == 1
        events = {k: [json.loads(line.removeprefix("R2_LOCK: ")) for line in text.splitlines()
                      if line.startswith("R2_LOCK: ")] for k, text in logs.items()}
        assert any(x["event"] == "wait" and x["stage"] == "domain" for x in events["observer"])
        assert not any(x["event"] == "acquired" for x in events["observer"])
        assert "pid=424242" in logs["observer"] and "ARGV_MUST_NOT_APPEAR" not in logs["observer"]
        rows = events["waiter"]
        assert [(x["stage"], x["event"]) for x in rows[:4]] == [
            ("domain", "wait"), ("domain", "acquired"), ("global", "wait"), ("global", "acquired")]
        assert rows[3]["wait_seconds"] > 0
        assert all(x["work_seconds"] == 0 for x in rows[:4])
        released = [x for x in rows if x["event"] == "released"]
        assert {x["stage"] for x in released} == {"domain", "global"}
        assert all(x["reason"] == "process_exit" for x in released)
        domain = next(x for x in released if x["stage"] == "domain")
        assert domain["held_seconds"] >= domain["work_seconds"] >= 0
        assert all(x["utc"].endswith("+00:00") and x["pid"] == waiter.pid for x in rows)
        assert all(x["command"] == "purge-low-freq" for x in rows)
        assert "ARGV_MUST_NOT_APPEAR" not in logs["waiter"] and "ENV_MUST_NOT_APPEAR" not in logs["waiter"]
        # 异常进程真实释放之后，另一个进程可再次取得相同域/全局屏障。
        p = start("writer"); wait("writer-ready"); (tmp_path / "release-writer").touch()
        _, err = p.communicate(timeout=6)
        assert p.returncode == 0, err
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
            p.communicate(timeout=3)
