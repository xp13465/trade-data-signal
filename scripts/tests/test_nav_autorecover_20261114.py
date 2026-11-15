"""NAV 发布自动恢复接线(B 批 2026-11-14)证据用例。

任务书证据用例 1-6 对应:
  1 unknown 存在 → 恰调用一次 recover-protected(幂等), 退出 0;
  2 CAS 412(旧代次)→ 判拒绝不覆盖, 恢复计数不虚增;
  3 无 unknown → 零调用(门控);
  4 积压超期 → 恰一条事件, 重复跑同 dedup 不再首报; 恢复后只发一次恢复通知;
  5 recover 失败 → 主链仍按原 rc 退出, 不被吞成成功;
  6 全量 pytest 由 CI/开发侧跑(本文件本身不跑全量)。

纪律: 全部 stub/dry-run, 禁真实上传(Transport fake + 伪造 journal)、禁真发通知
(monkeypatch send_*);冻结时钟 NAV_SELFHEAL_NOW / R2_RECOVER_NOW(L51);env 一律
monkeypatch 自动还原(L56);不裸写 os.environ。
"""
import datetime
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
SELFHEAL_SRC = SCRIPTS / "nav_journal_selfheal.py"
SHELL_SRC = SCRIPTS / "fund_nav_upload_async.sh"
CAS_SIBLING = Path(__file__).resolve().parent / "test_r2_protected_writes_20261111.py"

NOW = "2026-11-13T10:00:00Z"          # 周五(业务日)
NOW_YESTERDAY_BD = "2026-11-12"       # 周四


def load_selfheal():
    spec = importlib.util.spec_from_file_location("nav_journal_selfheal_under_test", SELFHEAL_SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_row(repo, key, **over):
    """按 SafeWriter 主 journal 落点写一行;sha256 路径与 r2_safe_write.SafeWriter.path 同源。"""
    root = repo / "data" / ".r2-protected"
    root.mkdir(parents=True, exist_ok=True)
    row = {"version": 1, "bucket": "public", "key": key,
           "sha256": "a" * 64, "size": 3, "write_id": "w" * 32, "state": "unknown",
           "confirmed": False, "pending_purge": True, "run_id": "r" * 32,
           "old_sha256": None, "backup_key": None,
           "business_date": NOW[:10], "source_channel": "fund_nav_upload_async",
           "generation": "r" * 32 + "@" + NOW[:10],
           "first_unresolved_at": NOW, "retry_count": 0}
    row.update(over)
    jname = hashlib.sha256(("public/" + key).encode()).hexdigest() + ".json"
    (root / jname).write_text(json.dumps(row, sort_keys=True))
    return row


def row_path(repo, key):
    return repo / "data" / ".r2-protected" / (hashlib.sha256(("public/" + key).encode()).hexdigest() + ".json")


def read_row(repo, key):
    return json.loads(row_path(repo, key).read_text())


def state_path(repo):
    return repo / "data/.nav_autorecover_state.json"


def write_state(repo, notified_at=NOW, keys=None):
    state_path(repo).parent.mkdir(parents=True, exist_ok=True)
    state_path(repo).write_text(json.dumps({"event": "nav_pending_overdue",
                                            "notified_at": notified_at,
                                            "overdue_keys": keys or ["nav_bucket/2e.json"]}))


# ── 证据用例 1 / 3 / 5: 自愈步脚本层(stub recover + stub notify) ──────────────


class Rec:
    def __init__(self):
        self.recover_calls = []
        self.events = []
        self.recoveries = []

    def fake_recover(self, repo):
        self.recover_calls.append(str(repo))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")


@pytest.fixture
def selfheal(tmp_path, monkeypatch):
    mod = load_selfheal()
    rec = Rec()
    monkeypatch.setattr(mod, "invoke_recover", rec.fake_recover)
    monkeypatch.setattr(mod, "send_event",
                        lambda repo, subject, body: rec.events.append((subject, body)) or
                        types.SimpleNamespace(returncode=0))
    monkeypatch.setattr(mod, "send_recovery",
                        lambda repo, subject, body: rec.recoveries.append((subject, body)) or
                        types.SimpleNamespace(returncode=0))
    monkeypatch.setenv("NAV_SELFHEAL_NOW", NOW)
    return mod, rec, tmp_path


def test_case1_unknown_triggers_single_recover_and_exit_zero(selfheal):
    """用例1: unknown 存在 → 恰调用一次 recover-protected; 恢复后再跑零调用(幂等, 不重复写)。"""
    mod, rec, repo = selfheal
    write_row(repo, "nav_bucket/2e.json", state="unknown")
    write_row(repo, "nav_bucket/3f.json", state="confirmed", confirmed=True, pending_purge=False)
    rc = mod.main(["--root", str(repo)])
    assert rc == 0
    assert len(rec.recover_calls) == 1
    assert not rec.events  # 业务日期=今天, 未超期, 零事件
    # 幂等: 恢复成功(stub 把 unknown 置 confirmed)后再跑 → 门控零调用, 零事件
    row = read_row(repo, "nav_bucket/2e.json")
    row.update(state="confirmed", confirmed=True, pending_purge=False,
               first_unresolved_at=None)
    (repo / "data" / ".r2-protected" / (hashlib.sha256(b"public/nav_bucket/2e.json").hexdigest() + ".json")).write_text(json.dumps(row, sort_keys=True))
    rc2 = mod.main(["--root", str(repo)])
    assert rc2 == 0
    assert len(rec.recover_calls) == 1  # 第二轮零调用(重复跑不重复写)


def test_case3_no_unknown_zero_calls(selfheal):
    """用例3: 无 unknown(仅 confirmed/preparing) → 零调用(门控生效), 退出 0。"""
    mod, rec, repo = selfheal
    write_row(repo, "nav_bucket/2e.json", state="confirmed", confirmed=True, pending_purge=False)
    write_row(repo, "data/nextday_plan.json", state="preparing")
    rc = mod.main(["--root", str(repo)])
    assert rc == 0
    assert rec.recover_calls == []          # preparing 不触发 recover-protected(下轮正常上传自愈)
    assert not rec.events                    # preparing 业务日期=今天, 不超期


def test_case5_recover_failure_does_not_block_main(selfheal):
    """用例5: recover-protected 失败(rc=1) → 自愈步退出仍 0, 不吞主链 rc(主链 rc 由调用方保留)。"""
    mod, rec, repo = selfheal
    write_row(repo, "nav_bucket/2e.json", state="unknown")
    def failing_recover(r):
        rec.recover_calls.append(str(r))
        return types.SimpleNamespace(returncode=1, stdout="", stderr="boom")
    mod.invoke_recover = failing_recover  # fixture 已捕获 monkeypatch 对象, 此处直接换桩
    rc = mod.main(["--root", str(repo)])
    assert rc == 0                          # 自愈步永不改主链 rc
    assert len(rec.recover_calls) == 1
    assert not rec.events                   # 未到超期, 失败不刷事件(不按尝试次数刷屏)


def test_case5_shell_rc_preserved():
    """用例5(shell 层): 自愈步在 rc 判定之后、exit 之前; || 兜底不阻断; exit "$rc" 保留原值。"""
    text = SHELL_SRC.read_text()
    subprocess.run(["bash", "-n", str(SHELL_SRC)], check=True)
    assert "nav_journal_selfheal.py" in text
    assert "不阻断主链, 不改主链 rc" in text
    selfheal_at = text.index("nav_journal_selfheal.py")
    assert text.index('exit "$rc"') > selfheal_at            # 自愈步之后仍按原 rc 退出
    assert 'R2_BUSINESS_DATE="$BIZ_DATE"' in text           # journal 可见性字段注入
    assert "R2_SOURCE_CHANNEL=fund_nav_upload_async" in text


# ── 证据用例 4: 积压超期恰一条事件 + 恢复只发一次 ──────────────────────────────


def test_case4_overdue_single_event_and_recovery(selfheal):
    """用例4: 超期 → 恰一条事件(对象范围/保留版本/数据年龄/需人工动作), 6h 窗内重复跑不首报;
    journal 全部 confirmed 后只发一次恢复通知; unknown 未清不得发恢复。"""
    mod, rec, repo = selfheal
    key = "nav_bucket/2e.json"
    write_row(repo, key, state="unknown", business_date=NOW_YESTERDAY_BD)
    rc = mod.main(["--root", str(repo)])
    assert rc == 0
    assert len(rec.events) == 1
    subject, body = rec.events[0]
    assert subject == "[告警] NAV 发布未决积压超期"
    for needle in ("对象范围", "保留版本", "数据年龄", "需人工动作", "recover-protected"):
        assert needle in body, needle
    # 状态文件在位(已通知事件登记)
    assert json.loads((repo / "data/.nav_autorecover_state.json").read_text())["event"] == "nav_pending_overdue"
    # 重复跑(同一冻结时钟, 6h 窗内) → 不再首报、不再新事件
    rc = mod.main(["--root", str(repo)])
    assert rc == 0
    assert len(rec.events) == 1
    assert rec.recoveries == []
    # unknown 仍在(未清绿) → 不发恢复通知
    rc = mod.main(["--root", str(repo)])
    assert rec.recoveries == []
    # journal 全部 confirmed → 恰一次恢复通知, 状态清
    row = read_row(repo, key)
    row.update(state="confirmed", confirmed=True, pending_purge=False, first_unresolved_at=None)
    (repo / "data/.r2-protected" / (hashlib.sha256(("public/" + key).encode()).hexdigest() + ".json")).write_text(json.dumps(row, sort_keys=True))
    rc = mod.main(["--root", str(repo)])
    assert rc == 0
    assert len(rec.recoveries) == 1
    assert not (repo / "data/.nav_autorecover_state.json").exists()
    # 再跑 → 不重复发恢复
    rc = mod.main(["--root", str(repo)])
    assert len(rec.recoveries) == 1


# ── P0-1 恢复判据判别用例(审查 §5/§9: 原 case4 第 173 次运行仍在 overdue 分支, 断言空转) ──


def test_case4b_unresolved_not_overdue_withholds_recovery(selfheal, capsys):
    """P0-1 判别: 已通知超期事件 + journal 仍 unknown/preparing + **本次未超期** →
    ①不发恢复通知 ②状态不被清除 ③再次运行仍 withheld。

    场景刻意不进 overdue 分支(business_date=今天、first_unresolved_at=NOW 即 0h),
    确保真正走到 `elif state:` 的恢复判据; 变异「本次无 unknown 就算恢复」必须在此红。
    """
    mod, rec, repo = selfheal
    write_row(repo, "nav_bucket/2e.json", state="unknown")            # 未清: unknown 仍在
    write_row(repo, "data/nextday_plan.json", state="preparing")      # 另一类未决
    write_state(repo)                                                 # 已通知过的超期事件
    rc = mod.main(["--root", str(repo)])
    out1 = capsys.readouterr().out
    assert rc == 0
    assert rec.recoveries == []                                       # ① 不发恢复
    assert state_path(repo).exists()                                  # ② 状态保留
    assert "恢复通知 withheld" in out1
    assert "恢复通知已发" not in out1
    rc = mod.main(["--root", str(repo)])                              # ③ 再次运行仍 withheld
    out2 = capsys.readouterr().out
    assert rc == 0
    assert rec.recoveries == []
    assert state_path(repo).exists()
    assert "恢复通知 withheld" in out2


# ── P1-1 空 journal 不得假恢复 ────────────────────────────────────────────────


def test_p1_1_empty_journal_withholds_and_keeps_state(selfheal, capsys):
    """P1-1: journal 为空(0/0) + 已有事件状态 → withheld、状态保留、措辞不声称「全部 confirmed」。"""
    mod, rec, repo = selfheal
    (repo / "data" / ".r2-protected").mkdir(parents=True, exist_ok=True)
    write_state(repo)
    rc = mod.main(["--root", str(repo)])
    out = capsys.readouterr().out
    assert rc == 0
    assert rec.recoveries == []
    assert state_path(repo).exists()
    assert "journal 为空" in out
    assert "全部 confirmed" not in out          # 0/0 不是「全部 confirmed」的事实


# ── F5 恢复通知发送失败不清状态 ──────────────────────────────────────────────


def test_f5_recovery_send_failure_keeps_state_then_success_clears(selfheal, capsys):
    """F5: send_recovery 失败(rc!=0) → 状态保留、下次重试; 成功后同一状态才被清。"""
    mod, rec, repo = selfheal
    write_row(repo, "nav_bucket/2e.json", state="confirmed", confirmed=True, pending_purge=False)
    write_state(repo)
    calls = []

    def failing(repo_, subject, body):
        calls.append(subject)
        return types.SimpleNamespace(returncode=1)

    mod.send_recovery = failing
    rc = mod.main(["--root", str(repo)])
    assert rc == 0
    assert len(calls) == 1
    assert state_path(repo).exists()             # 发送失败 → 不清状态
    assert "状态保留" in capsys.readouterr().out
    # 下一次成功 → 清状态, 不重复发
    mod.send_recovery = lambda repo_, subject, body: (
        calls.append(subject), types.SimpleNamespace(returncode=0))[1]
    rc = mod.main(["--root", str(repo)])
    assert rc == 0
    assert len(calls) == 2
    assert not state_path(repo).exists()


# ── F8 老 row 缺时间字段 / 坏 journal: mtime 兜底进超期事件 ──────────────────


def test_f8_legacy_row_and_unreadable_journal_use_mtime_fallback(selfheal):
    """F8/F2: 缺 business_date+first_unresolved_at 的老 row 与半写 journal, mtime>24h →
    同一超期事件可见(原因 journal_mtime_over_24h), 不静默失告警。"""
    mod, rec, repo = selfheal
    write_row(repo, "nav_bucket/2e.json", state="unknown",
              business_date=None, first_unresolved_at=None)
    bad = repo / "data" / ".r2-protected" / "bad-halfwritten.json"
    bad.write_text('{"version": 1, "key": ')     # 半写文件
    old = datetime.datetime.strptime(NOW, "%Y-%m-%dT%H:%M:%SZ") - datetime.timedelta(hours=25)
    ts = (old - datetime.datetime(1970, 1, 1)).total_seconds()
    os.utime(row_path(repo, "nav_bucket/2e.json"), (ts, ts))
    os.utime(bad, (ts, ts))
    rc = mod.main(["--root", str(repo)])
    assert rc == 0
    assert len(rec.events) == 1                  # 恰一条事件(两类未决合并为一条)
    subject, body = rec.events[0]
    assert "journal_mtime_over_24h" in body
    assert "<unreadable:bad-halfwritten.json>" in body
    assert state_path(repo).exists()


# ── F16 preparing 跨日常驻: withheld + 人工处置提示 ─────────────────────────


def test_f16_preparing_only_withheld_prints_manual_hint(selfheal, capsys):
    """F16: 只剩 preparing(自动永不重试) → withheld 且给出人工处置路径(可 grep 提示)。"""
    mod, rec, repo = selfheal
    write_row(repo, "data/nextday_plan.json", state="preparing")
    write_state(repo)
    rc = mod.main(["--root", str(repo)])
    out = capsys.readouterr().out
    assert rc == 0
    assert rec.recoveries == []
    assert state_path(repo).exists()
    assert "恢复通知 withheld" in out
    assert "preparing" in out and "recover-protected 人工模式" in out


# ── P1-3 自愈步工作预算接线 + 不阻断主链 ─────────────────────────────────────


def test_p1_3_recover_work_budget_wired_and_non_blocking(selfheal, monkeypatch):
    """P1-3: invoke_recover 注入 R2_UPLOAD_WORK_TIMEOUT(默认 600; 已设则沿用),
    预算到期(rc=124)时自愈步仍退 0、不刷事件、不改主链 rc。"""
    mod, rec, repo = selfheal
    write_row(repo, "nav_bucket/2e.json", state="unknown")
    captured = {}

    def fake_run(cmd, env=None, capture_output=True, text=True):
        captured.update(env or {})
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    real = load_selfheal()                       # fixture 已把 mod.invoke_recover 换成桩
    monkeypatch.setattr(real.subprocess, "run", fake_run)
    real.invoke_recover(repo)
    assert captured["R2_UPLOAD_WORK_TIMEOUT"] == "600"
    assert captured["R2_RECOVER_AUTO"] == "1"
    captured.clear()
    monkeypatch.setenv("R2_UPLOAD_WORK_TIMEOUT", "900")   # 显式设值不覆盖(setdefault)
    real.invoke_recover(repo)
    assert captured["R2_UPLOAD_WORK_TIMEOUT"] == "900"
    # 预算到期: 子进程 rc=124 → 自愈步照旧退 0, 不发事件/恢复
    mod.invoke_recover = lambda r: types.SimpleNamespace(returncode=124, stdout="预算到期", stderr="")
    rc = mod.main(["--root", str(repo)])
    assert rc == 0
    assert rec.events == [] and rec.recoveries == []


# ── P1-4 业务日口径(交易日历)+ 24h 年龄门控边界 ────────────────────────────


def test_overdue_24h_boundary(selfheal):
    """P1-4 边界: 刚过 24h 进超期; 未到 24h(差 60s)不进。"""
    mod, rec, repo = selfheal
    now = datetime.datetime.strptime(NOW, "%Y-%m-%dT%H:%M:%SZ")
    just_over = (now - datetime.timedelta(hours=24, seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    not_yet = (now - datetime.timedelta(hours=24) + datetime.timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    base = {"state": "unknown", "business_date": NOW[:10]}   # 业务日期=今天, 不触发条件①
    rows = [dict(base, key="a", first_unresolved_at=just_over),
            dict(base, key="b", first_unresolved_at=not_yet)]
    got = mod.overdue_rows(rows, now)
    assert [r["key"] for r, _ in got] == ["a"]
    assert got[0][1] == "unresolved_over_24h"


# ── 证据用例 2: CAS 412 拒绝旧代次(真实 uploader + Transport fake) ────────────
# 桩复制自 test_r2_protected_writes_20261111.py(pytest 禁止跨文件直调 fixture; 桩不执行
# 任何网络/凭据/通知, 只消除模块初始化读真实 .env)。

R2_SOURCE = SCRIPTS / "upload_r2.py"


class Transport:
    def __init__(self):
        self.objects = {}
        self.calls = []

    def put(self, bucket, key, body, headers=None):
        self.objects[bucket, key] = (body, {'ETag': '"' + hashlib.md5(body).hexdigest() + '"',
            'Content-Length': str(len(body)), **{k: v for k, v in (headers or {}).items() if k.startswith('x-amz-meta-')}})

    def request(self, method, uri, body, headers):
        from urllib.parse import urlsplit, parse_qs, unquote
        parsed = urlsplit(uri)
        bucket, _, key = unquote(parsed.path).lstrip('/').partition('/')
        headers = {k.lower(): v for k, v in headers.items()}
        self.calls.append((method, bucket, key))
        old = self.objects.get((bucket, key))
        if method in ('GET', 'HEAD'):
            if old:
                return 200, old[0] if method == 'GET' else b'', old[1]
            return 404, b'<Error><Code>NoSuchKey</Code></Error>', {}
        if ('if-none-match' in headers and old) or \
                ('if-match' in headers and (not old or old[1]['ETag'] != headers['if-match'])):
            return 412, b'precondition', {}
        self.put(bucket, key, body, headers)
        return 200, b'', {}


@pytest.fixture
def cas_client(tmp_path, monkeypatch):
    import ast
    import io
    for name in ('R2_BUCKET', 'R2_S3_ENDPOINT', 'R2_S3_ACCESS_KEY_ID', 'R2_S3_SECRET_ACCESS_KEY'):
        monkeypatch.setenv(name, 'https://fake.invalid' if name.endswith('ENDPOINT') else 'fake')
    monkeypatch.setenv('REPO', str(tmp_path))
    monkeypatch.setenv('GIT_REPO', str(tmp_path))
    monkeypatch.setenv('ALLOW_FULL_UPLOAD', '1')
    monkeypatch.setenv('R2_UPLOAD_LOCK', str(tmp_path / 'upload.lock'))
    monkeypatch.syspath_prepend(str(R2_SOURCE.parent))
    monkeypatch.setitem(sys.modules, 'notify', types.SimpleNamespace(
        send=lambda *a, **k: None, check_dedup=lambda *a: True, update_dedup=lambda *a: None))
    # 只消除模块初始化读真实 .env/stdout reconfigure; 生产函数原样执行。
    tree = ast.parse(R2_SOURCE.read_text())
    tree.body = [n for n in tree.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
        and (getattr(n.value.func, 'id', '') == 'load_env' or getattr(n.value.func, 'attr', '') == 'reconfigure'))]
    m = types.ModuleType('isolated_r2_nav_autorecover'); m.__file__ = str(R2_SOURCE)
    exec(compile(tree, str(R2_SOURCE), 'exec'), m.__dict__)
    fake = Transport()
    class Connection:
        sock = None
        def __init__(self, *a, **k): pass
        def request(self, method, uri, body=None, headers=None):
            self.result = fake.request(method, uri, body, headers or {})
        def getresponse(self):
            st, body, headers = self.result
            return types.SimpleNamespace(status=st, read=io.BytesIO(body).read,
                                         getheaders=lambda: list(headers.items()),
                                         getheader=lambda k, default=None: headers.get(k, default))
        def close(self): pass
    monkeypatch.setattr(m.http.client, 'HTTPSConnection', Connection)
    monkeypatch.setattr(m, '_route_bucket', lambda b: ('fake.invalid', 'fake', 'fake'))
    monkeypatch.setattr(m, 'BUCKET', 'public'); monkeypatch.setattr(m, 'BACKUP_BUCKET', 'backup')
    monkeypatch.setattr(m, '_work_sleep', lambda *a: None)
    monkeypatch.setattr(m, 'purge_cache', lambda *a, **k: True)
    monkeypatch.setattr(m, '_prune_pre_upload', lambda *a: None)
    monkeypatch.setattr(m, '_notify_channel_upload_fail', lambda *a, **k: None)
    m.STATIC_DIR.mkdir(parents=True)
    yield m, fake


def test_case2_cas_412_rejects_old_generation(cas_client, monkeypatch):
    """用例2: 旧代次 unknown 的 retry_put 重放被 R2 412 拒绝 → 不覆盖新输出;
    恢复计数恰 +1/轮(不虚增); 退出非零(如实未决)。"""
    m, fake = cas_client
    key = "nav_bucket/2e.json"
    old_bytes, new_bytes = b"old-gen", b"new-gen-B"
    # 写者 B 已提交新代次(新 ETag + 新 write-id)
    fake.put("public", key, new_bytes, {"x-amz-meta-write-id": "b" * 32})
    # 写者 A 的 journal: unknown, if-match 挂旧 ETag(旧代次)
    safe = m.SafeWriter(m.__dict__)
    row = {"version": 1, "bucket": "public", "key": key,
           "sha256": hashlib.sha256(old_bytes).hexdigest(), "size": len(old_bytes),
           "write_id": "a" * 32, "state": "unknown", "confirmed": False,
           "pending_purge": True, "run_id": "r" * 32,
           "old_sha256": None, "backup_key": None,
           "business_date": NOW[:10], "source_channel": "fund_nav_upload_async",
           "generation": "r" * 32 + "@" + NOW[:10],
           "first_unresolved_at": NOW, "retry_count": 0,
           "headers": {"if-match": '"stale-old-etag"', "x-amz-meta-write-id": "a" * 32}}
    safe.save(row)
    safe.store(safe.root / "payloads" / row["sha256"], old_bytes)
    monkeypatch.setenv("R2_RECOVER_AUTO", "1")
    monkeypatch.setenv("R2_RECOVER_NOW", NOW)
    with pytest.raises(SystemExit) as ei:
        m.cmd_recover_protected()
    assert ei.value.code == 1
    # 拒绝旧输出覆盖新输出: 远端仍是 B 的字节
    assert fake.objects["public", key][0] == new_bytes
    after = safe.load(key)
    assert after["state"] == "unknown"          # 未被强签 confirmed
    assert after["retry_count"] == 1           # 恰 +1, 不虚增
    # 再跑一轮: 仍 412 拒绝, 计数再 +1(每轮至多 +1)
    with pytest.raises(SystemExit) as ei2:
        m.cmd_recover_protected()
    assert ei2.value.code == 1
    assert fake.objects["public", key][0] == new_bytes
    assert safe.load(key)["retry_count"] == 2


def test_auto_mode_retry_cap_and_preparing_skip(cas_client, monkeypatch):
    """自动模式门控: retry_count>=3 只报不试(计数不动、零网络调用); preparing 跳过不计 failure;
    人工模式(不设 env)行为不变(preparing 仍计 failure, unknown 仍尝试)。"""
    m, fake = cas_client
    key = "nav_bucket/4e.json"
    safe = m.SafeWriter(m.__dict__)
    capped = {"version": 1, "bucket": "public", "key": key,
             "sha256": "c" * 64, "size": 1, "write_id": "e" * 32, "state": "unknown",
             "confirmed": False, "pending_purge": True, "run_id": "r" * 32,
             "old_sha256": None, "backup_key": None,
             "business_date": NOW[:10], "first_unresolved_at": NOW,
             "retry_count": 3, "headers": {}}
    safe.save(capped)
    prepping = dict(capped, key="nav_bucket/5e.json", write_id="d" * 32,
                    state="preparing", retry_count=0)
    safe.save(prepping)
    monkeypatch.setenv("R2_RECOVER_AUTO", "1")
    monkeypatch.setenv("R2_RECOVER_NOW", NOW)
    with pytest.raises(SystemExit) as ei:      # capped unknown 如实非零
        m.cmd_recover_protected()
    assert ei.value.code == 1
    assert fake.calls == []                     # 零网络尝试(preparing 跳过 + capped 只报不试)
    assert safe.load(key)["retry_count"] == 3   # 计数不动
    # 人工模式: 行为不变(preparing 无 recover 动作但计 failure → 非零)
    monkeypatch.delenv("R2_RECOVER_AUTO")
    with pytest.raises(SystemExit) as ei2:
        m.cmd_recover_protected()
    assert ei2.value.code == 1


def test_business_days_between(cas_client):
    """业务日计数: 周五→周一=1, 周四→周五=1, 同日=0(超龄判定基础)。"""
    m, _ = cas_client
    d = datetime.date
    assert m._business_days_between(d(2026, 11, 13), d(2026, 11, 16)) == 1  # 五→一
    assert m._business_days_between(d(2026, 11, 12), d(2026, 11, 13)) == 1
    assert m._business_days_between(d(2026, 11, 13), d(2026, 11, 13)) == 0
    assert m._business_days_between(d(2026, 11, 13), d(2026, 11, 18)) == 3   # 超龄线


def test_business_days_uses_trading_calendar_and_declared_fallback(cas_client, monkeypatch):
    """P1-4: 龄计数走交易日历(排节假日); 缺历时回退只排周末(声明的已知偏差)。"""
    m, _ = cas_client
    d = datetime.date
    # 2026 国庆 10-01..10-07 休市: 9-30→10-9 只有 10-8/10-9 两个交易日; 只排周末会算 7
    assert m._business_days_between(d(2026, 9, 30), d(2026, 10, 9)) == 2
    monkeypatch.setattr(m, "_trade_day_window", lambda: None)   # 模拟缺历
    assert m._business_days_between(d(2026, 9, 30), d(2026, 10, 9)) == 7


def test_business_days_beyond_calendar_coverage_falls_back(cas_client):
    """P1-4: 日期区间超出日历覆盖(2030 年) → 回退只排周末, 不用日历空集把龄算成 0。"""
    m, _ = cas_client
    d = datetime.date
    assert m._business_days_between(d(2030, 1, 7), d(2030, 1, 11)) == 4   # 一→五(回退)


def test_p1_2_bad_journal_does_not_abort_other_keys(cas_client, monkeypatch):
    """P1-2: 半写/损坏 journal 只跳过本文件并如实非零, 其余 unknown 键照常恢复(不再整轮中止)。

    同时断言容错轮 GC 零删除(坏文件保留 / 无引用文件不被删 / 旧清单不覆写)。
    """
    m, fake = cas_client
    safe = m.SafeWriter(m.__dict__)
    key = "nav_bucket/6e.json"
    payload = b"ok"
    row = {"version": 1, "bucket": "public", "key": key,
           "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload),
           "write_id": "f" * 32, "state": "unknown", "confirmed": False,
           "pending_purge": True, "run_id": "r" * 32, "old_sha256": None, "backup_key": None,
           "business_date": NOW[:10], "first_unresolved_at": NOW, "retry_count": 0,
           "headers": {"x-amz-meta-write-id": "f" * 32}}
    safe.save(row)
    safe.store(safe.root / "payloads" / row["sha256"], payload)
    # 坏 journal 文件名排序在前 ⇒ 若仍整轮中止, 后面的合法键永远处理不到
    (safe.root / "000-bad-journal.json").write_text('{"version": 1, "key": ')
    manifest_before = (safe.root / "gc-manifest.json").read_bytes()
    orphan = safe.root / "payloads" / ("0" * 64)
    orphan.write_bytes(b"orphan")                # 默认 gc 会删; 容错轮必须零删除
    monkeypatch.setenv("R2_RECOVER_AUTO", "1")
    monkeypatch.setenv("R2_RECOVER_NOW", NOW)
    with pytest.raises(SystemExit) as ei:
        m.cmd_recover_protected()
    assert ei.value.code == 1                    # 坏文件如实非零(该键仍未恢复)
    assert fake.calls                             # 合法键照常尝试
    assert safe.load(key)["state"] == "confirmed"  # 合法键恢复成功(未被坏文件阻断)
    # 容错轮零删除: 坏文件原地保留(供人工核验) + 无引用文件不被删 + 旧 gc 清单不覆写
    assert (safe.root / "000-bad-journal.json").exists()
    assert orphan.exists()
    assert (safe.root / "gc-manifest.json").read_bytes() == manifest_before


def test_p1_2_default_mode_still_strict_on_corrupt_journal(cas_client):
    """P1-2 对照: 容错仅在自动自愈轮开; 默认(人工/其它调用方)仍严格失败不删任何东西。"""
    m, _ = cas_client
    safe = m.SafeWriter(m.__dict__)
    safe.root.mkdir(parents=True, exist_ok=True)
    (safe.root / "corrupt.json").write_text('{bad json')
    with pytest.raises(ValueError):
        with safe.storage_lock():
            safe.gc()
    assert (safe.root / "corrupt.json").exists()
