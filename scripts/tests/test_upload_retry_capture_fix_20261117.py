"""2026-11-17 修两处已确认根因失败: 上传有界重试 + 成套捕获诊断/间隔/瞬态排除。

依据 /tmp/rca-backup-nav-20261116.md(实测):
- 上传: 条件 PUT 设计上只发一次(upload_r2.py:787-792), 跨境链拥塞时一次 TLS 断连/响应丢失
  即判死 ⇒ `write unconfirmed HTTP 0`(主对象) + `backup readback SHA256 mismatch`
  (备份键内容寻址, 真实语义 = 读回 404 空)。
- 捕获: 判据「窗口内零变更」+ 重试间隔 0s + 展开不过滤写入中间件 ⇒ 21:00 两轮都判死,
  且只打状态不打文件名。

本文件逐条锁定实现边界(真跑, 判别力见提交说明):
上传: ①第 1 次连接断、第 2 次成功 ②持续断开 ⇒ 恰好 3 次尝试后失败 ③412 ⇒ 只 1 次、不覆盖
      ④备份读回 404 两次后成功 ⑤自己写入已落地 + 首轮确认失败 ⇒ 重试遇 412 只认自己的字节
      ⑥永久 403 不重试 ⑦备份读回内容确不相同不重试
捕获: ①稳定目录成功 ②窗口内持续改真实状态文件 ⇒ 失败且报出该文件名 ③只有 .receipt-*/ *.tmp*
      变化 ⇒ 成功且不因中间件判死 ④重试间隔为正且被使用 ⑤总窗口上限生效(不无限等待)
      ⑥失败 stdout 行带 offender(主入口)
全部临时目录, 不碰生产数据、不发通知、不涉网络(HTTPS 连接被 fake 接管)。
运行日无关(无 date.today() 断言, 样例 mtime 固定历史时点, L51)。
"""
import ast
import hashlib
import io
import json
import os
import sys
import types
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, unquote

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import backup_state_capture as bsc  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_backup_state_capture as caps_repo  # noqa: E402  复用同款完整仓样例(不复制清单)

SOURCE = SCRIPTS / "upload_r2.py"
KEY = "data/nextday_plan.json"


# ---------------------------------------------------------------------------
# 上传侧: 真实 upload_r2 + HTTPS transport fake(与 test_r2_protected_writes 同款)
# ---------------------------------------------------------------------------
class Transport:
    """可编程假 transport: 按调用序号注入连接断/HTTP 状态/备份读回 404/确认期缺 write-id。"""

    def __init__(self):
        self.objects = {}
        self.calls = []
        self.public_put_actions = []   # 依次消费: 'ok' / 'raise' / 'status:<code>'
        self.public_put_always_raise = False
        self.public_puts = 0
        self.strip_write_id_gets = 0  # 落地后前 N 次 public GET 去掉 write-id(模拟首轮确认读不到)
        self.backup_hide_gets = 0     # 前 N 次备份 GET 返回 404(备份 PUT 未落地)
        self.corrupt_backup = False

    def put(self, bucket, key, body, headers=None):
        self.objects[bucket, key] = (body, {
            'ETag': '"' + hashlib.md5(body).hexdigest() + '"',
            'Content-Length': str(len(body)),
            **{k: v for k, v in (headers or {}).items() if k.startswith('x-amz-meta-')}})

    def request(self, method, uri, body, headers):
        parsed = urlsplit(uri)
        bucket, _, key = unquote(parsed.path).lstrip('/').partition('/')
        q = parse_qs(parsed.query, keep_blank_values=True)
        headers = {k.lower(): v for k, v in headers.items()}
        if hasattr(body, 'read'):
            body = body.read()
        self.calls.append((method, bucket, key, dict(q), dict(headers)))
        old = self.objects.get((bucket, key))
        if method in ('GET', 'HEAD'):
            if bucket == 'backup' and self.backup_hide_gets > 0:
                self.backup_hide_gets -= 1
                return 404, b'<Error><Code>NoSuchKey</Code></Error>', {}
            if not old:
                return 404, b'<Error><Code>NoSuchKey</Code></Error>', {}
            hdrs = dict(old[1])
            if bucket == 'public' and self.public_puts > 0 and self.strip_write_id_gets > 0:
                self.strip_write_id_gets -= 1
                hdrs = {k: v for k, v in hdrs.items() if k != 'x-amz-meta-write-id'}
            return 200, old[0] if method == 'GET' else b'', hdrs
        if bucket == 'public':
            self.public_puts += 1
            action = 'ok'
            if self.public_put_always_raise:
                action = 'raise'
            elif self.public_put_actions:
                action = self.public_put_actions.pop(0)
            if action == 'raise':
                raise OSError('connection reset before known commit')
            if action.startswith('status:'):
                return int(action.split(':', 1)[1]), b'', {}
        if ('if-none-match' in headers and old) or (
                'if-match' in headers and (not old or old[1]['ETag'] != headers['if-match'])):
            return 412, b'precondition', {}
        if self.corrupt_backup and bucket == 'backup':
            body = b'x' * len(body)
        self.put(bucket, key, body, headers)
        return 200, b'<CompleteMultipartUploadResult/>', {}


@pytest.fixture
def client(tmp_path, monkeypatch):
    for name in ('R2_BUCKET', 'R2_S3_ENDPOINT', 'R2_S3_ACCESS_KEY_ID', 'R2_S3_SECRET_ACCESS_KEY'):
        monkeypatch.setenv(name, 'https://fake.invalid' if name.endswith('ENDPOINT') else 'fake')
    monkeypatch.setenv('REPO', str(tmp_path))
    monkeypatch.setenv('GIT_REPO', str(tmp_path))
    monkeypatch.setenv('ALLOW_FULL_UPLOAD', '1')
    monkeypatch.setenv('R2_UPLOAD_LOCK', str(tmp_path / 'upload.lock'))
    monkeypatch.syspath_prepend(str(SCRIPTS))
    monkeypatch.setitem(sys.modules, 'notify', types.SimpleNamespace(
        send=lambda *a, **k: None, check_dedup=lambda *a: True, update_dedup=lambda *a: None))
    # 只剥离模块初始化读真实 .env/stdout reconfigure; 生产函数原样执行。
    tree = ast.parse(SOURCE.read_text())
    tree.body = [n for n in tree.body if not (
        isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
        and (getattr(n.value.func, 'id', '') == 'load_env'
             or getattr(n.value.func, 'attr', '') == 'reconfigure'))]
    m = types.ModuleType('isolated_r2_retry'); m.__file__ = str(SOURCE)
    exec(compile(tree, str(SOURCE), 'exec'), m.__dict__)
    fake = Transport()

    class Connection:
        sock = None

        def __init__(self, *a, **k):
            pass

        def request(self, method, uri, body=None, headers=None):
            self.result = fake.request(method, uri, body, headers or {})

        def getresponse(self):
            st, body, headers = self.result
            return types.SimpleNamespace(status=st, read=io.BytesIO(body).read,
                                         getheaders=lambda: list(headers.items()),
                                         getheader=lambda k, default=None: headers.get(k, default))

        def close(self):
            pass

    monkeypatch.setattr(m.http.client, 'HTTPSConnection', Connection)
    monkeypatch.setattr(m, '_route_bucket', lambda b: ('fake.invalid', 'fake', 'fake'))
    monkeypatch.setattr(m, 'BUCKET', 'public')
    monkeypatch.setattr(m, 'BACKUP_BUCKET', 'backup')
    sleeps = []
    monkeypatch.setattr(m, '_work_sleep', lambda wait: sleeps.append(wait))
    monkeypatch.setattr(m, 'purge_cache', lambda *a, **k: True)
    monkeypatch.setattr(m, '_prune_pre_upload', lambda *a: None)
    monkeypatch.setattr(m, '_notify_channel_upload_fail', lambda *a, **k: None)
    m.STATIC_DIR.mkdir(parents=True)
    m.sleeps = sleeps
    yield m, fake


def safe_writer(m):
    return m.SafeWriter(m.__dict__)


def seed_old(fake, key=KEY, body=b'old'):
    fake.put('public', key, body)


def retry_logs(capsys):
    return [json.loads(line.split('R2_WRITE_RETRY: ', 1)[1])
            for line in capsys.readouterr().err.splitlines() if 'R2_WRITE_RETRY: ' in line]


def public_put_calls(fake):
    return [c for c in fake.calls if c[0] == 'PUT' and c[1] == 'public']


def test_first_put_connection_loss_then_success(client, capsys):
    """①第 1 次连接断(HTTP 0)、第 2 次成功 ⇒ 成功, 恰好 2 次 PUT, 日志 attempt=1/error_kind=connection。"""
    m, f = client
    seed_old(f)
    safe = safe_writer(m)
    row = safe.prepare(KEY, b'new')
    f.public_put_actions = ['raise', 'ok']
    safe.commit(row, b'new')
    assert len(public_put_calls(f)) == 2
    logs = retry_logs(capsys)
    assert [x['attempt'] for x in logs] == [1]
    assert logs[0]['error_kind'] == 'connection' and logs[0]['exhausted'] is False
    assert logs[0]['key'] == KEY and isinstance(logs[0]['elapsed_ms'], int)
    assert safe.load(KEY)['confirmed'] is True


def test_persistent_connection_loss_three_attempts_then_fail(client, capsys):
    """②持续连接断 ⇒ 恰好 3 次尝试(1+2 重试)后如实失败, 不吞错。"""
    m, f = client
    seed_old(f)
    safe = safe_writer(m)
    row = safe.prepare(KEY, b'new')
    f.public_put_always_raise = True
    with pytest.raises(Exception) as exc:
        safe.commit(row, b'new')
    assert 'write unconfirmed HTTP 0; no fallback' in str(exc.value)
    assert len(public_put_calls(f)) == 3
    logs = retry_logs(capsys)
    assert [x['attempt'] for x in logs] == [1, 2, 3]
    assert logs[-1]['exhausted'] is True
    assert safe.load(KEY)['state'] == 'unknown'   # 未确认即保持 unknown(可恢复), 不冒充 confirmed


def test_412_not_retried_and_never_overwrites(client):
    """③412(条件不成立) ⇒ 只 1 次尝试、绝不覆盖他人写入。"""
    m, f = client
    seed_old(f)
    safe = safe_writer(m)
    row = safe.prepare(KEY, b'new')
    f.put('public', KEY, b'concurrent')   # 竞争写入抢先落地 ⇒ if-match 必 412
    with pytest.raises(Exception) as exc:
        safe.commit(row, b'new')
    assert 'conditional write rejected HTTP 412' in str(exc.value)
    assert len(public_put_calls(f)) == 1
    assert f.objects['public', KEY][0] == b'concurrent'
    assert safe.load(KEY)['status'] == 412


def test_backup_readback_empty_twice_then_success(client, capsys):
    """④备份读回 404 两次后成功 ⇒ 成功(备份侧同样有界重试)。"""
    m, f = client
    seed_old(f, body=b'old')
    safe = safe_writer(m)
    row = safe.prepare(KEY, b'new')   # prepare 内先备份旧版
    f.backup_hide_gets = 2            # 前两次读回 404 ⇒ 触发 2 次重试, 第 3 次读到
    safe.immutable(row['backup_key'], b'old')
    logs = retry_logs(capsys)
    assert [x['attempt'] for x in logs] == [1, 2]
    assert [x['error_kind'] for x in logs] == ['readback_empty', 'readback_empty']
    assert f.objects['backup', row['backup_key']][0] == b'old'


def test_own_write_landed_then_412_confirms_own_bytes(client, capsys):
    """⑤首轮 PUT 已落地但响应丢失 + 确认期读不到 write-id ⇒ 重试遇 412 只认自己的字节算成功。"""
    m, f = client
    seed_old(f)
    safe = safe_writer(m)
    row = safe.prepare(KEY, b'new')
    f.public_put_actions = ['raise']         # 先把字节写进假对象, 再抛连接断
    f.strip_write_id_gets = 2                # 首轮 confirm 的 2 次 GET 都读不到 write-id ⇒ 不认
    safe.commit(row, b'new')
    assert safe.load(KEY)['confirmed'] is True
    logs = retry_logs(capsys)
    assert logs and logs[0]['error_kind'] == 'connection'
    # 第 2 次 PUT 因 if-match 仍指旧 ETag 而 412, 但字节是自己的 ⇒ 不算覆盖、不算失败
    assert len(public_put_calls(f)) == 2
    assert f.objects['public', KEY][0] == b'new'


def test_permanent_403_not_retried(client):
    """⑥永久性 4xx(403) ⇒ 不重试, 只 1 次尝试。"""
    m, f = client
    seed_old(f)
    safe = safe_writer(m)
    row = safe.prepare(KEY, b'new')
    f.public_put_actions = ['status:403']
    with pytest.raises(Exception) as exc:
        safe.commit(row, b'new')
    assert 'conditional write rejected HTTP 403' in str(exc.value)
    assert len(public_put_calls(f)) == 1
    assert f.objects['public', KEY][0] == b'old'


def test_backup_corrupt_readback_not_retried(client, capsys):
    """⑦备份读回内容确不相同(内容寻址路径出现别的字节) ⇒ 不重试(真异常, 不是传输抖动)。"""
    m, f = client
    seed_old(f)
    safe = safe_writer(m)
    row = safe.prepare(KEY, b'new')
    del f.objects['backup', row['backup_key']]   # 键不在位 ⇒ 走到真写入与读回比对
    f.corrupt_backup = True
    before = len([c for c in f.calls if c[0] == 'PUT' and c[1] == 'backup'])
    with pytest.raises(Exception) as exc:
        safe.immutable(row['backup_key'], b'old')
    assert 'backup readback SHA256 mismatch' in str(exc.value)
    after = len([c for c in f.calls if c[0] == 'PUT' and c[1] == 'backup'])
    assert after - before == 1                   # 只发一次, 不重放
    assert retry_logs(capsys) == []              # 一个字节不差才叫真异常, 不打重试日志


def test_upload_path_end_to_end_still_succeeds(client):
    """端到端回归: 正常链路(含旧版备份)在重试改造后仍 rc=1、对象与备份都在位。"""
    m, f = client
    seed_old(f)
    p = m.STATIC_DIR / KEY
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b'new')
    assert m._upload_glob(p.parent, [p.name], 'data')[0] == 1
    row = safe_writer(m).load(KEY)
    assert row['confirmed'] and not row['pending_purge']
    assert f.objects['public', KEY][0] == b'new'
    assert f.objects['backup', row['backup_key']][0] == b'old'


# ---------------------------------------------------------------------------
# 捕获侧: 最小临时仓(固定 mtime, 与运行日无关)
# ---------------------------------------------------------------------------
def make_repo(tmp_path, *, extra=None):
    """完整声明仓(复用既有用例同款样例)+ 本次额外投放的中间件;mtime 固定历史时点。"""
    repo = caps_repo.make_repo(tmp_path)
    for rel, body in (extra or {}).items():
        p = repo / "data" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
        os.utime(p, (caps_repo.FIXTURE_MTIME, caps_repo.FIXTURE_MTIME))
    return repo


def run_capture(repo, out_root, **kw):
    return bsc.capture(repo, out_root, repo.parent / "backups", "20261113_2100",
                       SCRIPTS, with_db_leg=False, **kw)


def test_capture_stable_dir_consistent(tmp_path, monkeypatch):
    """捕获①: 稳定目录 ⇒ 成功、零重试、瞬态中间件不进集合。"""
    monkeypatch.setattr(bsc, "RETRY_INTERVAL_SECONDS", 0.01)
    repo = make_repo(tmp_path)
    result = run_capture(repo, tmp_path / "sets")
    m = result["manifest"]
    assert m["status"] == "captured" and m["complete"] is True
    assert m["sidecar_consistency"]["retries"] == 0
    assert result["uploadable"] is True


def test_capture_names_the_file_that_keeps_changing(tmp_path, monkeypatch, capsys):
    """捕获②: 窗口内持续改一个真实状态文件 ⇒ 失败且**报出该文件名**(旧实现只打状态)。"""
    monkeypatch.setattr(bsc, "RETRY_INTERVAL_SECONDS", 0.01)
    repo = make_repo(tmp_path)
    orig = bsc.read_stable
    calls = {"n": 0}

    def always(path, max_bytes=None):
        payload, before = orig(path, max_bytes)
        if path.name == "alert_state.json":
            calls["n"] += 1
            path.write_text('{"changed":%d}' % calls["n"])
        return payload, before

    monkeypatch.setattr(bsc, "read_stable", always)
    result = run_capture(repo, tmp_path / "sets")
    m = result["manifest"]
    assert m["status"] == "inconsistent" and result["uploadable"] is False
    assert calls["n"] == 2                     # 只重试一次(有界)
    assert m["changed_files"] == ["alert_state.json"]
    assert m["changed_total"] == 1
    assert m["retry_window_exhausted"] is False
    err = capsys.readouterr().err
    assert "STATE_CAPTURE_INCONSISTENT" in err and "alert_state.json" in err
    assert "STATE_CAPTURE_RETRY" in err        # 重试前也点名 offender


def test_capture_ignores_receipt_and_tmp_intermediates(tmp_path, monkeypatch):
    """捕获③: 只有 .receipt-*/ *.tmp* 中间件在动 ⇒ 成功, 且中间件不进集合(按设计排除记账)。"""
    monkeypatch.setattr(bsc, "RETRY_INTERVAL_SECONDS", 0.01)
    repo = make_repo(tmp_path, extra={
        "ops_delivery/pub/.receipt-abc123": "partial",
        "ops_delivery/pub/r.json.tmp.deadbeef": "partial",
    })
    orig = bsc.read_stable
    gone = {"n": 0}

    def vanishes(path, max_bytes=None):
        payload, before = orig(path, max_bytes)
        # 模拟写入中间件的真实生命周期: 展开时存在, 读完后立即被 unlink(最终产物另行发布)。
        if path.name.startswith(".receipt-") or ".tmp." in path.name:
            gone["n"] += 1
            path.unlink()
        return payload, before

    monkeypatch.setattr(bsc, "read_stable", vanishes)
    result = run_capture(repo, tmp_path / "sets")
    m = result["manifest"]
    assert gone["n"] == 0                      # 中间件在读之前就被排除 ⇒ 压根没进入读取
    assert m["status"] == "captured" and m["complete"] is True
    skips = {s["rel"]: s["reason"] for s in m["skipped"]}
    assert skips["ops_delivery/pub/.receipt-abc123"] == "transient_intermediate_by_design"
    assert skips["ops_delivery/pub/r.json.tmp.deadbeef"] == "transient_intermediate_by_design"
    captured = {r["rel"] for r in m["files"]}
    assert not any("receipt-" in rel for rel in captured)
    assert not any(".tmp." in rel for rel in captured)


def test_capture_retry_interval_is_positive_and_used(tmp_path, monkeypatch):
    """捕获④: 重试间隔为正(不是 0s)且真被使用; 生产常量本身 > 0。"""
    assert bsc.RETRY_INTERVAL_SECONDS > 0
    sleeps = []
    monkeypatch.setattr(bsc.time, "sleep", lambda s: sleeps.append(s))
    repo = make_repo(tmp_path)
    orig = bsc.read_stable
    calls = {"n": 0}

    def once(path, max_bytes=None):
        payload, before = orig(path, max_bytes)
        if path.name == "alert_state.json" and calls["n"] == 0:
            calls["n"] += 1
            path.write_text('{"changed":1}')
        return payload, before

    monkeypatch.setattr(bsc, "read_stable", once)
    result = run_capture(repo, tmp_path / "sets")
    assert sleeps == [bsc.RETRY_INTERVAL_SECONDS]
    assert result["manifest"]["status"] == "captured"
    assert result["manifest"]["sidecar_consistency"]["retries"] == 1


def test_capture_retry_total_window_bound(tmp_path, monkeypatch):
    """捕获⑤: 总窗口上限生效 —— 窗口不够就**不等待不重试**, 绝不无限等(有界)。"""
    monkeypatch.setattr(bsc, "RETRY_INTERVAL_SECONDS", 5.0)
    monkeypatch.setattr(bsc, "RETRY_TOTAL_WINDOW_SECONDS", 0.0)
    sleeps = []
    monkeypatch.setattr(bsc.time, "sleep", lambda s: sleeps.append(s))
    repo = make_repo(tmp_path)
    orig = bsc.read_stable
    calls = {"n": 0}

    def always(path, max_bytes=None):
        payload, before = orig(path, max_bytes)
        if path.name == "alert_state.json":
            calls["n"] += 1
            path.write_text('{"changed":%d}' % calls["n"])
        return payload, before

    monkeypatch.setattr(bsc, "read_stable", always)
    result = run_capture(repo, tmp_path / "sets")
    m = result["manifest"]
    assert sleeps == []                        # 窗口已到 ⇒ 不睡
    assert calls["n"] == 1                     # 也没跑第二轮
    assert m["status"] == "inconsistent" and m["retry_window_exhausted"] is True
    assert m["changed_files"] == ["alert_state.json"]


def test_capture_main_stdout_names_offenders(tmp_path, monkeypatch, capsys):
    """捕获⑥: 主入口失败行必须带文件名(旧实现只有 status/set_dir/duration)。"""
    monkeypatch.setattr(bsc, "RETRY_INTERVAL_SECONDS", 0.01)
    repo = make_repo(tmp_path)
    orig = bsc.read_stable
    calls = {"n": 0}

    def always(path, max_bytes=None):
        payload, before = orig(path, max_bytes)
        if path.name == "alert_state.json":
            calls["n"] += 1
            path.write_text('{"changed":%d}' % calls["n"])
        return payload, before

    monkeypatch.setattr(bsc, "read_stable", always)
    rc = bsc.main(["--repo", str(repo), "--backup-dir", str(tmp_path / "backups"),
                   "--stamp", "20261113_2100", "--out-root", str(tmp_path / "sets"),
                   "--scripts-dir", str(SCRIPTS), "--no-db-leg"])
    out = capsys.readouterr().out.strip().splitlines()
    assert rc == 1 and len(out) == 1           # 仍是唯一 stdout 行
    payload = json.loads(out[0])
    assert payload["status"] == "inconsistent"
    assert payload["changed_files"] == ["alert_state.json"]
    assert payload["changed_total"] == 1


@pytest.mark.parametrize("name,expected", [
    (".receipt-abc123", True),
    ("r.json.tmp.deadbeef", True),
    ("x.tmp", True),
    ("x.tmp-1", True),
    ("alert_state.json", False),
    (".r2_index_state.json", False),
    ("gc-manifest.json", False),
    ("x.tmpl.json", False),     # .tmp 必须是独立名字段, 宁窄勿宽
])
def test_is_transient_intermediate_unit(name, expected):
    assert bsc.is_transient_intermediate(name) is expected
