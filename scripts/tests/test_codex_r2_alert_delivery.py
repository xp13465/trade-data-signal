"""R2 写门禁/占窗和自动摘要回退的可移植隔离回归。

只编译下面列出的完整生产函数，不导入模块顶层（upload_r2 会 load_env）。
S3/渠道/规则台账在边界替换；完整 verify/send/原子摘要文件路径真实执行。
不检测实际 cron 挂载，不把 buffer 接受当成最终送达。无研究目录/旧 SHA 依赖。
"""
import argparse
import ast
import builtins
import datetime as dt
import hashlib
import html
import io
import itertools
import json
import os
from pathlib import Path
import re
import smtplib
import socket
import subprocess
import sys
import time
import types
from concurrent.futures import ThreadPoolExecutor, as_completed  # 先载入标准库

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHANNELS = ("email", "telegram", "feishu")
FALSE = dict.fromkeys(CHANNELS, False)
ROUTES = ("digest_only", "recovery", "budget", "domain", "notice_recent",
          "notice_daily", "notice_rollover", "trace", "budget_domain")
STATES = ("healthy", "digest_disabled", "budget_disabled", "unmounted")


class ForbiddenAction(BaseException):
    """不被生产函数的 except Exception 吞掉。"""


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """所有生产 AST 执行前正控；局部补丁、env、sys.path 均在 fixture 结束恢复。"""
    before_env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
    before_path = sys.path[:]
    hits = []

    def deny(*args, **kwargs):
        hits.append("external")
        raise ForbiddenAction("禁止真实网络/SMTP/业务子进程")

    def check(path, writing=False):
        if isinstance(path, (str, bytes, os.PathLike)):
            p = Path(os.fsdecode(path))
            if p.name == ".env" or p.name.startswith(".env."):
                hits.append("credentials")
                raise ForbiddenAction("禁止凭据读取")
            if writing and not p.resolve().is_relative_to(tmp_path.resolve()):
                hits.append("write")
                raise ForbiddenAction("禁止 fixture 以外写入")

    def wrap_open(original):
        def guarded(file, mode="r", *args, **kwargs):
            check(file, any(c in mode for c in "wax+"))
            return original(file, mode, *args, **kwargs)
        return guarded

    with monkeypatch.context() as mp:
        mp.setattr(builtins, "open", wrap_open(builtins.open))
        mp.setattr(io, "open", wrap_open(io.open))
        real_os_open = os.open

        def os_open(path, flags, *args, **kwargs):
            check(path, bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
            return real_os_open(path, flags, *args, **kwargs)

        mp.setattr(os, "open", os_open)
        for name in ("mkdir", "unlink", "remove", "rmdir", "chmod", "truncate"):
            original = getattr(os, name)

            def mutate(path, *args, _fn=original, **kwargs):
                check(path, True)
                return _fn(path, *args, **kwargs)

            mp.setattr(os, name, mutate)
        for name in ("rename", "replace"):
            original = getattr(os, name)

            def move(src, dst, *args, _fn=original, **kwargs):
                check(src, True)
                check(dst, True)
                return _fn(src, dst, *args, **kwargs)

            mp.setattr(os, name, move)
        for obj, name in ((socket, "socket"), (socket, "getaddrinfo"),
                          (socket, "create_connection"), (smtplib, "SMTP"),
                          (smtplib, "SMTP_SSL"), (subprocess, "Popen"), (os, "system")):
            mp.setattr(obj, name, deny)
        controls = (lambda: socket.socket(), lambda: smtplib.SMTP("invalid.example"),
                    lambda: subprocess.run([sys.executable, "-c", "pass"], timeout=1),
                    lambda: os.system("true"), lambda: (ROOT / "forbidden-probe").write_text("x"),
                    lambda: os.replace(tmp_path / "absent", ROOT / "forbidden-probe"),
                    lambda: (ROOT / ".env").read_bytes(),
                    lambda: (ROOT / ".env.production").read_bytes())
        for control in controls:
            with pytest.raises(ForbiddenAction):
                control()
        hits.clear()
        yield types.SimpleNamespace(tmp=tmp_path, mp=mp, deny=deny)
        assert hits == [], "正控之后触达了未获准副作用"
    after_env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
    unchanged = after_env == before_env
    assert unchanged, "fixture 环境未恢复（不回显环境值）"
    assert sys.path == before_path


def source(name):
    path = ROOT / "scripts" / name
    return ast.parse(path.read_text(encoding="utf-8")), str(path)


def load(tree, path, names, namespace):
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in nodes} == set(names)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, "exec", flags=16777216), namespace)


def constants(tree, names, namespace):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in names:
                    namespace[target.id] = ast.literal_eval(node.value)
    assert set(names) <= namespace.keys()


class Clock(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2024, 1, 4, 23, 35, tzinfo=tz)


class Upload:
    """真实 guard/verify/glob；S3 对象只存在内存中。"""
    def __init__(self, sb, kind="clean", sunday=False):
        self.sb, self.kind = sb, kind
        self.local = sb.tmp / "static-site" / "data"
        self.local.mkdir(parents=True, exist_ok=True)
        self.remote, self.puts, self.heads, self.marks, self.sends = {}, [], [], [], []
        self.fail_put = False
        for i in range(51 if kind == "mass" else 0 if kind == "ledger" else 1):
            p = self.local / f"{i:02}.json"
            p.write_bytes(b'{"authoritative":"fixture"}')
            self.remote["fixture/" + p.name] = p.read_bytes() if kind == "clean" else b"older"
        self.response = FALSE.copy()
        self.notify = types.ModuleType("notify")

        def send(*args, **kwargs):
            self.sends.append(kwargs["ledger_key"])
            if isinstance(self.response, Exception):
                raise self.response
            return self.response

        self.notify.send = send
        self.notify.check_dedup = lambda key, window: key in self.marks
        self.notify.update_dedup = self.marks.append
        fake_sys = types.SimpleNamespace(platform="linux", stderr=sys.stderr, path=[], exit=sys.exit)
        day = dt.date(2024, 1, 7 if sunday else 4)
        ns = self.ns = {
            "sys": fake_sys, "Path": Path, "ROOT": Path("/home/fixture/trade"),
            "REPO_EXPLICIT": True, "BUCKET": "invalid-fixture", "PUBLIC": "https://invalid.example",
            "STATIC_DIR": self.local.parent, "hashlib": hashlib, "json": json,
            "datetime": types.SimpleNamespace(date=types.SimpleNamespace(today=lambda: day), datetime=Clock),
            "_MULTIPART_THRESHOLD": 100 * 1024 * 1024,
            "_R2_CHANNELS": [{"label": "fixture", "local_dir": lambda: self.local,
                              "patterns": ["*.json"], "r2_prefix": "fixture", "state_name": None}],
            "_LEDGER_MISSING": "missing", "_LEDGER_CORRUPT": "corrupt",
            "_STALE_ALERT_COUNT_THRESHOLD": 1, "_STALE_ALERT_BYTES_THRESHOLD": 999999,
            "_STALE_ALERT_CONSECUTIVE_THRESHOLD": 2, "_assert_no_double_upload": lambda p: True,
            "_load_standalone_keys": lambda **kw: (set(self.remote) if kind == "stale" else set(),
                                                   "missing" if kind == "ledger" else "ok"),
            "_compute_stale_consecutive_rounds": lambda *a: 1,
            "_reset_stale_state_if_clean": lambda: None,
            "_standalone_keys_path": lambda: sb.tmp / "ledger.json",
            "_work_budget_check": lambda *a: None, "_upload_multipart": sb.deny,
            "s3_head": self.head, "s3_request": self.put,
        }
        tree, path = source("upload_r2.py")
        constants(tree, {"_A_CLASS", "_TRADE_FALLBACK_OK", "_PRIVATE_ONLY_CMDS", "_READ_ONLY_CMDS"}, ns)
        load(tree, path, {"_is_production_writer", "_is_public_bucket_write", "guard_repo_default",
                          "_verify_r2_notification_handled", "cmd_verify_r2", "_upload_glob",
                          "_file_md5", "_channel_files", "_uniform_sample", "_fmt_name_list"}, ns)
        sb.mp.setitem(sys.modules, "notify", self.notify)

    def head(self, key, **kwargs):
        self.heads.append(key)
        data = self.remote.get(key)
        pair = (200, hashlib.md5(data).hexdigest()) if data is not None else (404, None)
        return (*pair, len(data) if data is not None else None) if kwargs.get("with_len") else pair

    def put(self, method, key, payload, **kwargs):
        assert method == "PUT" and key.startswith("fixture/")
        self.puts.append(key)
        if self.fail_put:
            return 503, b"injected failure"
        self.remote[key] = payload
        return 200, b""

    def verify(self):
        self.ns["guard_repo_default"]("verify-r2")
        self.ns["cmd_verify_r2"]()


def notification(sb, route="domain", state="healthy", delivered=False, writefail=False):
    """完整 send/摘要存储/flush；规则台账和渠道在依赖边界替换。"""
    home = sb.tmp / "notice"
    home.mkdir(exist_ok=True)
    tree, path = source("notify.py")
    os_proxy = types.SimpleNamespace(**{k: getattr(os, k) for k in dir(os) if not k.startswith("__")})
    os_proxy.environ = ({"ALERT_DIGEST_DISABLE": "1"} if state == "digest_disabled" else
                        {"ALERT_BUDGET_DISABLE": "1"} if state == "budget_disabled" else {})
    calls, events = [], []
    adr = types.SimpleNamespace(
        DOMAIN_AGGREGATE_EXEMPT_KEYS=set(), DOMAIN_AGGREGATE_EXEMPT_PREFIXES=("active_escalate|",),
        DOMAIN_ABSORB_REASON="domain_inhibited", ALERT_DOMAIN_GROUP_INTERVAL=7200,
        category_of=lambda *a: "r2" if route in {"budget", "budget_domain", "notice_recent", "notice_daily", "notice_rollover"} else None,
        domain_of=lambda *a: "r2_deploy" if route in {"domain", "budget_domain"} else None,
        domain_inhibit_judge=lambda *a: ("absorb", {"n_absorbed_today": 1, "n_absorbed": 1}),
        record_suppression=lambda **kw: None, stall_canonical_key=lambda *a: None,
        ALERT_BUDGET={"r2": 1}, ALERT_NOTICE_BUDGET={"r2": 1}, repeat_absorb_days=lambda: 7,
        repeat_recent_absorb_judge=lambda *a: route == "notice_recent",
        rollover_absorb_judge=lambda *a: (route == "notice_rollover", "fixture"),
        ROLLOVER_ABSORB_REASON="rollover_digested", NOTICE_OVER_BUDGET_REASON="notice_over_budget",
        REPEAT_RECENT_ABSORB_REASON="repeat_recent_direct", domain_aggregate_summary=lambda entries: {},
    )
    ns = {"os": os_proxy, "time": time, "json": json, "re": re, "html": html,
          "hashlib": hashlib, "datetime": Clock, "sys": sys, "Path": Path, "adr": adr,
          "REPO": home, "argparse": argparse, "SEVERE_PREFIX": "",
          "ALERT_DIGEST_FILE": home / "digest.jsonl", "ALERT_DIGEST_LOCK_FILE": home / "digest.lock",
          "ALERT_DIGEST_STATE_FILE": home / "digest_state.json", "ALERT_DIGEST_HM": "23:25",
          "DIGEST_ENTRY_BODY_LIMIT": 3000, "DIGEST_REASON_LABELS": {}, "_DIGEST_DETAIL_REASONS": set(),
          "_RECOVERY_PREFIX_RE": re.compile(r"^\[恢复\]"),
          "ALERT_AGGREGATE_SUBJECT_RE": re.compile(r"^\[告警·摘要\]"),
          "_HTML_LAYOUT_TAG_RE": re.compile(r"<[^>]+>"), "_ESCALATION_SUBJECT_MARKERS": (),
          "_LATEST_ENTRY_LEVELS": ("notice", "warning", "severe"),
          "_LEDGER_LOCAL": types.SimpleNamespace(depth=0), "TIER_CRITICAL": "critical",
          "TIER_WARNING": "warning", "TIER_INFO": "info",
          "_finish": lambda rc, status, detail, **kw: (rc, status),
          "_resolve_feishu_chat_key": lambda *a: "alert", "_domain_state": lambda: {},
          "_commit_domain_state": lambda *a: events.append("domain"),
          "_email_group_gate_disabled": lambda: False, "_mirror_latest_entry": lambda *a, **kw: None,
          "_record_ledger": lambda *a, **kw: None, "_noise_class_of": lambda *a: None,
          "clear_warning_dedup_for_recovery": lambda *a: None,
          "_budget_today_count": lambda *a: 1, "_budget_today_keys": lambda *a: {"case"},
          "_budget_today_notice_keys": lambda *a: {"case"} if route == "notice_daily" else set(),
          "_rollover_seen": lambda: {}, "_budget_recent_direct_keys": lambda *a: {"case"},
          "_budget_today_notice_count": lambda *a: 1, "_commit_rollover_seen": lambda *a: None}
    ns["_ledger_depth"] = lambda: ns["_LEDGER_LOCAL"].depth
    for channel, name in zip(CHANNELS, ("_send_email", "send_telegram", "send_feishu")):
        def transport(*a, _channel=channel, **kwargs):
            calls.append(_channel)
            return delivered if _channel == "feishu" else False
        ns[name] = transport
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.startswith("DIGEST_"):
                    try:
                        ns[target.id] = ast.literal_eval(node.value)
                    except (TypeError, ValueError):
                        pass
    load(tree, path, {"send", "_ledger_key_of", "_digest_chain_available", "_absorb_to_digest",
                      "_atomic_write_digest", "_parse_buffer_lines", "_flock_ex_wait",
                      "_split_body_lines", "_absorb_split_to_digest", "flush_digest",
                      "_flush_digest_locked", "_stable_rid", "_chmod_like_target", "_main_impl"}, ns)
    if state == "unmounted":
        # 仅验证 provider 返回不可用后的路由，不假装现有 helper 会检测实际挂载。
        ns["_digest_chain_available"] = lambda: (False, "fixture: consumer unmounted")
    if writefail:
        def fail(*args):
            raise OSError("injected atomic write failure")
        ns["_atomic_write_digest"] = fail
    return ns, ns["ALERT_DIGEST_FILE"], calls


@pytest.mark.parametrize("platform,root", [("darwin", "/home/fixture"), ("darwin", "/Users/dev"), ("linux", "/devtree")])
@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("command", ["verify-r2", "upload", "upload-all-data", "upload-lab"])
def test_nonproduction_public_write(sandbox, platform, root, explicit, command):
    f = Upload(sandbox)
    f.ns.update(ROOT=Path(root), REPO_EXPLICIT=explicit)
    f.ns["sys"].platform = platform
    with pytest.raises(SystemExit) as err:
        f.ns["guard_repo_default"](command)
    assert err.value.code == (2 if explicit or command in {"upload", "upload-lab"} else 3)
    assert not f.heads and not f.puts


@pytest.mark.parametrize("command,explicit,code", [("list", False, None), ("download-db", False, None),
                                                  ("verify-channels", True, None), ("verify-channels", False, 3)])
def test_read_only_guard_contract(sandbox, command, explicit, code):
    f = Upload(sandbox)
    f.ns.update(ROOT=Path("/devtree"), REPO_EXPLICIT=explicit)
    assert not f.ns["_is_public_bucket_write"](command)
    if code:
        with pytest.raises(SystemExit) as err:
            f.ns["guard_repo_default"](command)
        assert err.value.code == code
    else:
        f.ns["guard_repo_default"](command)


@pytest.mark.parametrize("sunday", [False, True])
@pytest.mark.parametrize("kind,count", [("mass", 51), ("stale", 1), ("clean", 0)])
def test_cloud_automatic_repair(sandbox, sunday, kind, count):
    f = Upload(sandbox, kind, sunday)
    f.verify()
    assert len(f.puts) == count
    assert all(f.remote["fixture/" + p.name] == p.read_bytes() for p in f.local.glob("*.json"))


def test_cloud_upload_failure_is_not_success(sandbox):
    f = Upload(sandbox, "stale")
    f.fail_put = True
    with pytest.raises(SystemExit) as err:
        f.verify()
    assert err.value.code == 1
    assert not f.sends


@pytest.mark.parametrize("kind", ["mass", "stale", "ledger"])
@pytest.mark.parametrize("flags", list(itertools.product((False, True), repeat=4)))
def test_dedup_all_boolean_results(sandbox, kind, flags):
    f = Upload(sandbox, kind)
    f.response = dict(zip((*CHANNELS, "digested"), flags))
    f.verify()
    assert len(f.sends) == 1
    assert len(f.marks) == int(any(flags))


@pytest.mark.parametrize("kind", ["mass", "stale", "ledger"])
@pytest.mark.parametrize("result", [None, {}, [], "sent", {"email": True}, {"digested": True},
                                    {**FALSE, "email": 1}, {**FALSE, "digested": "true"},
                                    {**FALSE, "status": "sent"}, RuntimeError("transport failed")])
def test_bad_or_failed_result_does_not_occupy(sandbox, kind, result):
    f = Upload(sandbox, kind)
    f.response = result
    f.verify()
    assert not f.marks


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("delivered", [False, True])
def test_complete_send_automatic_routes(sandbox, route, state, delivered):
    ns, buffer, calls = notification(sandbox, route, state, delivered)
    result = ns["send"]("[恢复] fixture" if route in {"recovery", "trace"} else "[告警] fixture",
                        "body<br>detail", ledger_key="case", digest_only=route == "digest_only",
                        severe=route in {"budget", "budget_domain", "trace"}, budget_exempt=route == "trace")
    if state == "healthy" and route != "trace":
        assert result == {**FALSE, "digested": True}
        assert not calls and buffer.exists()
    else:
        assert calls == list(CHANNELS)
        assert not result.get("digested")
        assert buffer.exists() == (state == "healthy" and route == "trace" and delivered)


@pytest.mark.parametrize("kind", ["mass", "stale", "ledger"])
@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("delivered", [False, True])
def test_real_send_result_controls_r2_window(sandbox, kind, state, delivered):
    f = Upload(sandbox, kind)
    ns, buffer, calls = notification(sandbox, state=state, delivered=delivered)
    f.notify.send = ns["send"]
    f.verify()
    assert len(f.marks) == int(state == "healthy" or delivered)
    assert buffer.exists() == (state == "healthy")
    assert len(calls) == (0 if state == "healthy" else 3)


@pytest.mark.parametrize("delivered", [False, True])
def test_digest_write_failure_falls_back_without_false_window(sandbox, delivered):
    f = Upload(sandbox, "ledger")
    ns, buffer, calls = notification(sandbox, delivered=delivered, writefail=True)
    f.notify.send = ns["send"]
    f.verify()
    assert calls == list(CHANNELS) and not buffer.exists()
    assert bool(f.marks) == delivered


@pytest.mark.parametrize("state", STATES)
def test_explicit_writer_cli_and_manual_flush_contract(sandbox, state):
    ns, buffer, calls = notification(sandbox, state=state)
    assert ns["_absorb_to_digest"]("manual", "body", key="explicit", category="manual")
    assert buffer.exists()  # 存储函数没有被机械禁用。
    buffer.unlink()
    result = ns["_main_impl"](["manual", "body", "--defer-digest"])
    assert result == (0, "noop" if state == "budget_disabled" else "digested")
    assert buffer.exists() == (state != "budget_disabled")
    inner = []
    ns["_flush_digest_locked"] = lambda **kw: inner.append(kw) or {"sent": False, "n": 0, "n_remaining": 0}
    ns["flush_digest"]()
    assert len(inner) == int(state != "digest_disabled")
    assert not calls


def test_caller_disable_does_not_prove_consumer_disabled(sandbox):
    ns, buffer, calls = notification(sandbox, state="digest_disabled", delivered=True)
    assert ns["_absorb_to_digest"]("manual", "body", key="cross-env", category="manual")
    assert not ns["_digest_chain_available"]()[0]
    # 独立consumer环境模型；未读取真实cron/systemd，不声称实际曾漏信。
    ns["os"].environ = {}
    assert ns["_digest_chain_available"]()[0]
    result = ns["flush_digest"]()  # 真实持锁主体、真实临时文件、替身渠道。
    assert result["sent"] and calls == list(CHANNELS)
    assert buffer.read_bytes() == b""


@pytest.mark.parametrize("kind", ["mass", "stale", "ledger"])
def test_failed_delivery_retries_then_success_suppresses(sandbox, kind):
    f = Upload(sandbox, kind)
    f.verify()
    assert not f.marks and len(f.sends) == 1
    for key in f.remote:
        f.remote[key] = b"drift-again"
    f.response = {**FALSE, "feishu": True}
    f.verify()
    assert len(f.sends) == 2 and len(f.marks) == 1
    for key in f.remote:
        f.remote[key] = b"drift-after-delivery"
    f.verify()
    assert len(f.sends) == 2  # 已接受通知才允许窗内抑制。
