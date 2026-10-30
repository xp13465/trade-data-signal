# -*- coding: utf-8 -*-
"""#364 自测: R2 内层工作预算(R2_UPLOAD_WORK_TIMEOUT)真实生效(2026-10-30)。

被测面 = `scripts/upload_r2.py` 的 #364 工作预算机制:
  - `_work_budget_begin/_remaining_work/_effective_request_timeout/_work_budget_check/_work_sleep`
  - 三个拦截点: a) 单请求 socket 超时 = min(配置, 剩余); b) 重试门(attempt 前 + 退避前);
    c) 文件间门(主上传 `_upload_glob._upload_one` / 备份 `_backup_one`)
  - 备份阶段单 PUT 的 progress_label(`[备份 xxx] ↑ 上传中 ...`)
  - 备份阶段 GET 下载进度 `_read_with_progress`(`[备份 xxx] ↓ 下载中 x/y MiB`, ≥8MiB 才打点;
    S3 二版补, T8)
  - 真 8 线程池(`_upload_glob`)里 worker 到期 ⇒ 主线程 fut.result() 收 SystemExit 124、日志只一行
    (S7 二版补, T7)

对照病灶(10-29 实测): 单文件最坏 5 次重试 × 600s + 15s 退避 = 3015s > 外层 run_to 2760s,
外层先杀、python 来不及打失败日志 ⇒ 43 分钟黑屏。

零网络/零 R2 写: `_upload_glob` / `_backup_overwritten_keys` / `s3_request` / `s3_head` /
`http.client.HTTPSConnection` 全部 monkeypatch 成内存假实现; STATIC_DIR 指 tmp_path。
另有 http.client.connect 阻断兜底(§18 L48「自测零外发」)。

§18 L51(时敏): 跑时刻由 env `R2_NOW_OVERRIDE` 冻结(默认周四 21:10), 不依赖真实日期;
可用 `R2_TEST_NOW=2026-11-04T21:10:00` 平移一天复跑(验收 V10)。

跑法: .venv/bin/python -m pytest -q scripts/tests/test_364_work_budget_20261030.py
"""
import gzip
import hashlib
import http.client
import json
import os
import random
import re
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import upload_r2 as ur  # noqa: E402  (conftest 已注入 scripts/ 与仓库根路径)

REPO = Path(__file__).resolve().parents[2]
TB_SH = REPO / "scripts" / "turnover_backfill.sh"

STATE_NAME = ".r2_test_364_state.json"        # 测试私有名(不碰生产 .r2_*_state.json)
FROZEN_NOW = os.environ.get("R2_TEST_NOW", "2026-10-29T21:10:00")   # 周四(非周日)


def _paths(tmp_path):
    sd = tmp_path / "data"          # STATIC_DIR.parent / "data" = 状态/marker/进度落点
    stem = STATE_NAME.replace("_state.json", "")
    return {
        "state": sd / STATE_NAME,
        "marker": sd / f"{stem}_uploading.marker",
        "ckpt": sd / f"{stem}_ckpt.json",
    }


def _mk_tree(tmp_path, monkeypatch, *, n=3, marker=None, ckpt=None):
    """铺 n 个文件 + 状态(指纹全部不符 ⇒ 全部待传); STATIC_DIR 指向 tmp 树。"""
    static = tmp_path / "static-site"
    local = static / "data"
    local.mkdir(parents=True)
    files = {}
    for i in range(n):
        p = local / f"f_{i:02d}.json"
        p.write_text(json.dumps({"i": i}), encoding="utf-8")
        files[p.name] = {"size": p.stat().st_size, "md5": "0" * 32}
    monkeypatch.setattr(ur, "STATIC_DIR", static)
    ps = _paths(tmp_path)
    ps["state"].parent.mkdir(parents=True, exist_ok=True)
    ps["state"].write_text(json.dumps({"version": 1, "updated_at": "x", "mode": "增量",
                                       "count": n, "files": files, "changed": []}),
                           encoding="utf-8")
    if marker is not None:
        ps["marker"].write_text(marker, encoding="utf-8")
    if isinstance(ckpt, int):
        ps["ckpt"].write_text(json.dumps({"version": 1, "count": 0, "files": {}}),
                              encoding="utf-8")
    return local, ps


def _fake_backup(monkeypatch):
    """备份段假实现(不发网络, 返回 0/0/0/[]), 让用例只关心工作预算。"""
    def _fake(keys, _label, md5_map=None):
        return 0, 0, 0, []
    monkeypatch.setattr(ur, "_backup_overwritten_keys", _fake)


def _fake_upload(monkeypatch, *, sleep_per_file=0.0, gate=True):
    """主上传段假实现: 每个文件开始前调用**真实** `_work_budget_check`(与生产同位置的门)。"""
    sent = []

    def _fake(local_dir, _patterns, prefix, only_files=None, on_success=None,
              verify_etag=False):
        local_dir = Path(local_dir)
        files = sorted(Path(f) for f in (only_files or []))
        for f in files:
            if gate:
                ur._work_budget_check("upload-file")
            if sleep_per_file:
                time.sleep(sleep_per_file)
            rel = str(f.relative_to(local_dir))
            sent.append(rel)
            if on_success is not None:
                on_success(f, rel)
        return len(files), len(files), [], [f"{prefix}/{r}" for r in sent]

    monkeypatch.setattr(ur, "_upload_glob", _fake)
    return sent


def _run(local, *, checkpoint_every=0):
    return ur._incremental_upload(local, ["*.json"], "data", STATE_NAME,
                                  label="data-large", checkpoint_every=checkpoint_every)


@pytest.fixture(autouse=True)
def _frozen_now(monkeypatch):
    """冻结跑时刻(周四 21:10), 不受真实星期影响(§18 L51)。"""
    monkeypatch.setenv("R2_NOW_OVERRIDE", FROZEN_NOW)


@pytest.fixture(autouse=True)
def _budget_reset(monkeypatch):
    """每个用例前后清零工作预算全局态 + 删 env(防用例间串味)。"""
    monkeypatch.delenv("R2_UPLOAD_WORK_TIMEOUT", raising=False)
    ur._WORK_DEADLINE = None
    ur._WORK_BUDGET_S = 0
    ur._WORK_LABEL = ""
    ur._WORK_EXPIRED = False
    try:
        ur._KA_TLS.conns = {}
    except Exception:  # noqa: BLE001 - threading.local 属性缺失时无所谓
        pass
    yield
    ur._WORK_DEADLINE = None
    ur._WORK_BUDGET_S = 0
    ur._WORK_LABEL = ""
    ur._WORK_EXPIRED = False


_LOCAL_HTTP_OK = False      # 由 local_http_ok fixture 打开(F1 真传输用例专用)
_ORIG_CONNECT: dict = {}    # 类名 → 原始 connect(loopback 放行时调用)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """自测零外发机检: 真实 HTTP(S) 连接一律直接报错。

    唯一放行孔 = 测试显式 `local_http_ok` **且** 目标 host 是 loopback(F1 起本地 http.server
    验真传输)。非 loopback 依然报错 ⇒「零外发」在结构上仍然成立, 不是「整体关掉守卫」。
    """
    def _guard(cls):
        orig = cls.connect
        _ORIG_CONNECT[cls.__name__] = orig

        def _connect(self, *a, **k):
            if _LOCAL_HTTP_OK and getattr(self, "host", "") in ("127.0.0.1", "localhost"):
                return orig(self, *a, **k)
            raise AssertionError("自测期禁止真实网络连接(零外发铁律)")

        return _connect

    for cls in (http.client.HTTPConnection, http.client.HTTPSConnection):
        monkeypatch.setattr(cls, "connect", _guard(cls), raising=False)


@pytest.fixture
def local_http_ok():
    """F1 专用: 只放行本机 loopback(F1 之外没有任何用例使用)。"""
    global _LOCAL_HTTP_OK
    assert _ORIG_CONNECT, "网络守卫未安装(测试基础设施坏了)"
    _LOCAL_HTTP_OK = True
    try:
        yield
    finally:
        _LOCAL_HTTP_OK = False


# ---------------- T1: 未设 / 空 / 0 / 非数字 ⇒ 完全禁用, 行为不变 ----------------
def test_t1_unset_means_disabled_byte_identical(tmp_path, monkeypatch, capsys):
    """未设预算 ⇒ 不设截止时刻、不打预算日志、不改有效超时、门是空操作。"""
    for raw in (None, "", "  ", "0", "abc", "-3"):
        if raw is None:
            monkeypatch.delenv("R2_UPLOAD_WORK_TIMEOUT", raising=False)
        else:
            monkeypatch.setenv("R2_UPLOAD_WORK_TIMEOUT", raw)
        ur._work_budget_begin("data-large")
        assert ur._WORK_DEADLINE is None, f"R2_UPLOAD_WORK_TIMEOUT={raw!r} 应禁用"
        assert ur._work_budget_check("x") is None   # 不抛
        assert ur._effective_request_timeout() == ur.R2_UPLOAD_HTTP_TIMEOUT
        out = capsys.readouterr().out
        assert "工作预算" not in out and "R2 工作预算" not in out, f"{raw!r} 不应打预算日志"
    monkeypatch.delenv("R2_UPLOAD_WORK_TIMEOUT", raising=False)

    # 端到端: 无预算时正常跑完, 输出里没有任何预算字样(行为逐字不变方向)
    local, ps = _mk_tree(tmp_path, monkeypatch)
    _fake_backup(monkeypatch)
    sent = _fake_upload(monkeypatch)
    ok, total, failed, _keys = _run(local)
    out = capsys.readouterr().out
    assert (ok, total, failed, len(sent)) == (3, 3, [], 3)
    assert "工作预算" not in out
    assert ps["state"].exists() and not ps["marker"].exists()


# ---------------- T2: 预算 5s + 每文件 6s ⇒ exit 124, 中途保 marker/进度/不写 state ----------------
def test_t2_budget_expiry_exit_124_keeps_marker_and_ckpt(tmp_path, monkeypatch, capsys):
    """到期 ⇒ 一行可 grep 日志 + exit 124; marker 与断点进度保留; _state.json 逐字节不变。"""
    local, ps = _mk_tree(tmp_path, monkeypatch)
    _fake_backup(monkeypatch)
    _fake_upload(monkeypatch, sleep_per_file=6.0)
    state_before = ps["state"].read_bytes()
    monkeypatch.setenv("R2_UPLOAD_WORK_TIMEOUT", "5")
    ur._work_budget_begin("data-large")
    t0 = time.monotonic()
    with pytest.raises(SystemExit) as ei:
        _run(local, checkpoint_every=1)
    elapsed = time.monotonic() - t0
    out = capsys.readouterr().out
    assert ei.value.code == 124, f"工作预算到期必须 exit 124, 实得 {ei.value.code}"
    assert f"[data-large] R2 工作预算: 5s(内层,等锁后开始计时)" in out
    assert "⚠ 工作预算 5s 到期(内层,非外层 timeout)" in out
    assert out.count("工作预算 5s 到期") == 1, "到期日志只许一行(多线程去重)"
    assert "marker/断点续传进度保留" in out
    assert 5.0 <= elapsed < 12.0, f"到期应≈第一个文件耗时(6s), 实得 {elapsed:.1f}s"
    assert ps["marker"].exists(), "到期中止必须保留 marker(下轮据此续传)"
    snap = json.loads(ps["ckpt"].read_text(encoding="utf-8"))
    assert snap["count"] == 1, f"已完成的首个文件应落进进度, 实得 {snap}"
    assert ps["state"].read_bytes() == state_before, "到期中止不许写 _state.json"


def test_t2b_backup_phase_expiry_not_swallowed(tmp_path, monkeypatch, capsys):
    """备份阶段到期同样中止(不被「备份异常(不阻断)」的 except Exception 吞掉)。"""
    local, ps = _mk_tree(tmp_path, monkeypatch)
    state_before = ps["state"].read_bytes()

    def _budgeted_backup(keys, _label, md5_map=None):
        ur._work_budget_check("backup-file")   # 与生产 `_backup_one` 同位置的门
        raise AssertionError("预算已耗尽, 不应继续做备份请求")

    monkeypatch.setattr(ur, "_backup_overwritten_keys", _budgeted_backup)
    _fake_upload(monkeypatch)
    monkeypatch.setenv("R2_UPLOAD_WORK_TIMEOUT", "5")
    ur._work_budget_begin("data-large")
    ur._WORK_DEADLINE = time.monotonic() - 1
    with pytest.raises(SystemExit) as ei:
        _run(local)
    out = capsys.readouterr().out
    assert ei.value.code == 124
    assert "工作预算 5s 到期(内层,非外层 timeout)" in out
    assert "覆盖前备份异常(不阻断)" not in out, "到期是中止信号, 不许被备份段的 except Exception 降级成普通失败"
    assert ps["marker"].exists() and ps["state"].read_bytes() == state_before


# ---------------- T3: 拦截点 a —— 单请求超时 = min(配置, 剩余), 下限 1s ----------------
def test_t3_request_timeout_clamped_to_remaining(tmp_path, monkeypatch, capsys):
    """剩余 3s ⇒ 生效超时 3s(而非配置 30s); 下限 1s; 禁用 ⇒ 配置值。"""
    monkeypatch.setenv("R2_UPLOAD_WORK_TIMEOUT", "5")
    ur._work_budget_begin("data-large")
    assert ur._WORK_BUDGET_S == 5
    # +3.9s ⇒ int(剩余)=3(实现取 floor, 保证不越过预算; 见 _effective_request_timeout)
    ur._WORK_DEADLINE = time.monotonic() + 3.9
    assert ur._effective_request_timeout() == 3
    ur._WORK_DEADLINE = time.monotonic() + 0.2
    assert ur._effective_request_timeout() == 1, "下限 1s(不能给 0/负数)"
    ur._WORK_DEADLINE = None
    assert ur._effective_request_timeout() == ur.R2_UPLOAD_HTTP_TIMEOUT

    # 复用连接: socket 超时也要刷成剩余(否则等锁/等恢复的老连接仍按 600s 停滞)
    class _Sock:
        def __init__(self):
            self.timeouts = []
        def settimeout(self, v):
            self.timeouts.append(v)

    class _Conn:
        def __init__(self):
            self.sock = _Sock()

    c = _Conn()
    ur._set_conn_timeout(c)          # 禁用 ⇒ 不碰
    assert c.sock.timeouts == []
    ur._WORK_DEADLINE = time.monotonic() + 3.9
    ur._set_conn_timeout(c)
    assert c.sock.timeouts == [3]

    # 新建连接: 真实 HTTPSConnection 构造参数 timeout = 剩余
    seen = {}

    class _FakeHTTP:
        def __init__(self, host, timeout=None, context=None):
            seen["host"], seen["timeout"] = host, timeout
        def close(self):
            pass

    monkeypatch.setattr(ur.http.client, "HTTPSConnection", _FakeHTTP)
    ur._KA_TLS.conns = {}
    ur._WORK_DEADLINE = time.monotonic() + 3.9
    ur._get_keepalive_conn("example.invalid")
    assert seen["timeout"] == 3


def test_t3b_stuck_request_cut_at_remaining_not_config(monkeypatch, capsys):
    """真走 s3_request: 剩 3s 时连接超时=3, 请求被 socket 超时打断 ⇒ 3s 收口(不是 30s)。"""
    monkeypatch.setenv("R2_UPLOAD_WORK_TIMEOUT", "5")
    ur._work_budget_begin("data-large")
    deadline = time.monotonic() + 3.9      # int(剩余)=3(floor 语义)
    ur._WORK_DEADLINE = deadline
    seen = {"timeout": None, "n": 0}

    class _FakeHTTP:
        def __init__(self, host, timeout=None, context=None):
            seen["timeout"] = timeout
        def request(self, *_a, **_k):
            seen["n"] += 1
        def getresponse(self):
            time.sleep(seen["timeout"])          # 模拟请求真的卡满「生效超时」
            raise socket.timeout("simulated stall")
        def close(self):
            pass

    monkeypatch.setattr(ur.http.client, "HTTPSConnection", _FakeHTTP)
    t0 = time.monotonic()
    with pytest.raises(SystemExit) as ei:
        ur.s3_request("PUT", "data/x.json", b"payload")
    elapsed = time.monotonic() - t0
    out = capsys.readouterr().out
    assert seen["timeout"] == 3, f"连接超时应=剩余 3s(配置 30s), 实得 {seen['timeout']}"
    assert seen["n"] == 1, "被 socket 超时打断后应进重试门, 剩余已耗尽 ⇒ 不再发第 2 次"
    assert ei.value.code == 124
    assert "工作预算 5s 到期(内层,非外层 timeout)" in out
    assert 3.0 <= elapsed < 5.0, f"应在剩余预算附近收口, 实得 {elapsed:.1f}s"


# ---------------- T4: 预算充裕 ⇒ 正常跑完, 无到期日志, state 正常写 ----------------
def test_t4_within_budget_completes_normally(tmp_path, monkeypatch, capsys):
    local, ps = _mk_tree(tmp_path, monkeypatch)
    _fake_backup(monkeypatch)
    _fake_upload(monkeypatch, sleep_per_file=0.1)
    monkeypatch.setenv("R2_UPLOAD_WORK_TIMEOUT", "60")
    ur._work_budget_begin("data-large")
    ok, total, failed, _keys = _run(local)
    out = capsys.readouterr().out
    assert (ok, total, failed) == (3, 3, [])
    assert "[data-large] R2 工作预算: 60s(内层,等锁后开始计时)" in out
    assert "工作预算 60s 到期" not in out
    st = json.loads(ps["state"].read_text(encoding="utf-8"))
    assert st["mode"] == "增量" and st["changed"] == ["f_00.json", "f_01.json", "f_02.json"]
    assert not ps["marker"].exists()


# ---------------- T5: 备份阶段单 PUT 带 progress_label「备份 <key>」 ----------------
def test_t5_backup_put_has_backup_progress_label(monkeypatch):
    """备份桶 PUT 必须带非空 progress_label 且形如「备份 <key>」; 阈值沿用 8MiB 常量。"""
    body = b"x" * 1024
    key = "data/data_large_00.json"
    md5 = __import__("hashlib").md5(body).hexdigest()
    puts = []

    def _fake_head(k, bucket=None, keep_alive=False, with_len=False):
        if k == key:
            return (200, md5, len(body))
        # 备份桶: PUT 之前不存在(404) → 不触发减量跳过; PUT 之后回读 200(证落地)
        if puts:
            return (200, md5, len(body)) if with_len else (200, md5)
        return (404, None) if not with_len else (404, None, None)

    def _fake_req(method, k, payload=b"", **kw):
        if method == "GET":
            return 200, body
        if method == "PUT":
            puts.append({"key": k, **kw})
            return 200, b""
        raise AssertionError(f"意外请求 {method} {k}")

    monkeypatch.setattr(ur, "s3_head", _fake_head)
    monkeypatch.setattr(ur, "s3_request", _fake_req)
    monkeypatch.setattr(ur, "_prune_pre_upload", lambda *_a, **_k: None)
    copied, skipped, failed, _samples = ur._backup_overwritten_keys({key: "0" * 32}, "data-large")
    assert (copied, skipped, failed) == (1, 0, 0)
    assert len(puts) == 1
    label = puts[0].get("progress_label")
    assert label and label.startswith("备份 ") and key in label, f"备份 PUT 进度标签不对: {label!r}"
    assert ur._PROGRESS_PUT_MIN == 8 * 1024 * 1024, "大文件进度阈值应沿用既有 8MiB 常量"
    # 源码形状守卫: 备份 PUT 的 progress_label 确实由 f-string 拼出「备份 <key>」
    src = Path(ur.__file__).read_text(encoding="utf-8")
    assert 'progress_label=f"备份 {key}"' in src


# ---------------- T6: 拦截点 b —— 重试门(attempt 前 + 退避前), 不许越过预算 ----------------
def test_t6a_expired_before_attempt_sends_nothing(monkeypatch, capsys):
    monkeypatch.setenv("R2_UPLOAD_WORK_TIMEOUT", "5")
    ur._work_budget_begin("data-large")
    ur._WORK_DEADLINE = time.monotonic() - 1
    calls = {"n": 0}

    class _FakeHTTP:
        def __init__(self, *a, **k):
            calls["n"] += 1
        def close(self):
            pass

    monkeypatch.setattr(ur.http.client, "HTTPSConnection", _FakeHTTP)
    with pytest.raises(SystemExit) as ei:
        ur.s3_request("PUT", "data/x.json", b"y")
    out = capsys.readouterr().out
    assert ei.value.code == 124 and calls["n"] == 0, "预算已耗尽 ⇒ 一次请求都不许发"
    assert out.count("工作预算 5s 到期") == 1


def test_t6b_after_first_failure_no_backoff_no_second_attempt(monkeypatch, capsys):
    """第 1 次失败后剩余耗尽 ⇒ 退避门前中止: 不 sleep、不发第 2 次、日志无 attempt 2。"""
    monkeypatch.setenv("R2_UPLOAD_WORK_TIMEOUT", "60")
    ur._work_budget_begin("data-large")
    ur._WORK_DEADLINE = time.monotonic() + 30.0   # attempt 1 放行
    calls = {"n": 0}
    slept = []

    class _FakeHTTP:
        def __init__(self, *a, **k):
            pass
        def request(self, *_a, **_k):
            calls["n"] += 1
            ur._WORK_DEADLINE = time.monotonic() - 1   # 模拟本次请求耗掉全部剩余
            raise OSError("simulated connection reset")
        def close(self):
            pass

    monkeypatch.setattr(ur.http.client, "HTTPSConnection", _FakeHTTP)
    monkeypatch.setattr(ur, "_work_sleep", lambda w: slept.append(w))
    with pytest.raises(SystemExit) as ei:
        ur.s3_request("PUT", "data/x.json", b"y")
    captured = capsys.readouterr()
    assert ei.value.code == 124
    assert calls["n"] == 1, "退避门前必须中止, 不许发第 2 次"
    assert slept == [], "剩余已耗尽 ⇒ 连退避 sleep 都不许做"
    assert "attempt 1 失败" in captured.err and "attempt 2" not in captured.err
    assert "工作预算 60s 到期" in captured.out


# ---------------- T7: 真 8 线程池的 SystemExit 传播(S7) ----------------
def test_t7_thread_pool_propagates_expiry_to_main_thread(tmp_path, monkeypatch, capsys):
    """真 `_upload_glob`(8 线程池)里 worker 到期 ⇒ 主线程 fut.result() 收到 SystemExit 124。

    构造: 16 个文件 / 预算 2s / 假 PUT 每次睡 2.5s ⇒ 第一批 8 个 worker 在 deadline 后才完成,
    第二批 8 个 worker 一启动就撞上文件间门(拦截点 c) ⇒ 到期发生在 worker 线程, 必须由主线程
    接住并 exit 124; 若有人把 `except Exception` 改成 `except BaseException`(或在线程池汇合处
    包一层吞掉), 本用例必红。
    """
    n = 16
    local, _ps = _mk_tree(tmp_path, monkeypatch, n=n)
    peak = {"now": 0, "max": 0}
    lock = __import__("threading").Lock()

    def _slow_put(method, key, payload=b"", **kw):
        with lock:
            peak["now"] += 1
            peak["max"] = max(peak["max"], peak["now"])
        try:
            time.sleep(3.0)          # 跨过 2s deadline(留 1s 余量防 CI 抖动)
            return 200, b""
        finally:
            with lock:
                peak["now"] -= 1

    monkeypatch.setattr(ur, "s3_request", _slow_put)
    monkeypatch.setenv("R2_UPLOAD_WORK_TIMEOUT", "2")
    ur._work_budget_begin("data-large")
    t0 = time.monotonic()
    with pytest.raises(SystemExit) as ei:
        ur._upload_glob(local, ["*.json"], "data")
    elapsed = time.monotonic() - t0
    out = capsys.readouterr().out
    assert ei.value.code == 124, f"线程池到期必须 exit 124, 实得 {ei.value.code}"
    assert out.count("工作预算 2s 到期") == 1, "并发到期日志只许一行"
    assert "✗" not in out, "SystemExit 不许被 worker 的 except Exception 降级成普通失败"
    assert peak["max"] >= 2, f"必须真并发(峰值 in-flight={peak['max']}), 否则本用例没测到线程池"
    assert elapsed < 10.0, f"应≈3s 收口(串行需 {n * 3:.0f}s), 实得 {elapsed:.1f}s"


# ---------------- T8: 备份 GET 下载进度(#364 S3) ----------------
class _FakeGetResp:
    """假 GET 响应: 支持 getheader('Content-Length') + read(n) 分块吐。"""

    def __init__(self, total, headers=None):
        self._left = total
        self._total = total
        self._headers = {"Content-Length": str(total)} if headers is None else headers

    def getheader(self, name):
        return self._headers.get(name)

    def read(self, n=-1):
        if self._left <= 0:
            return b""
        n = self._left if n is None or n < 0 else min(n, self._left)
        self._left -= n
        return b"x" * n


def test_t8a_get_small_file_no_progress_line(capsys):
    """< 8MiB 或没有 Content-Length ⇒ 零新增日志(小文件不刷屏), 内容仍逐字节完整。"""
    for total, headers in ((ur._PROGRESS_PUT_MIN - 1, None),
                           (0, {"Content-Length": "n/a"}),
                           (0, {})):
        resp = _FakeGetResp(total, headers)
        data = ur._read_with_progress(resp, "备份 data/x.json")
        assert len(data) == total
        assert capsys.readouterr().out == "", "小文件/长度未知不许打进度行"


def test_t8b_get_large_file_progress_lines(capsys):
    """≥ 8MiB ⇒ 按 4MiB 步长打「[label] ↓ 下载中 x/y MiB (NB)」, 内容逐字节完整。"""
    total = 8 * 1024 * 1024
    resp = _FakeGetResp(total)
    data = ur._read_with_progress(resp, "备份 data/big.bin")
    out = capsys.readouterr().out
    assert len(data) == total and data == b"x" * total
    lines = [ln for ln in out.splitlines() if "↓ 下载中" in ln]
    assert len(lines) >= 2, f"8MiB 文件应至少 2 行进度, 实得 {lines!r}"
    assert lines[0].startswith("[备份 data/big.bin] ↓ 下载中 4.0/8.0 MiB ("), lines[0]
    assert lines[-1].endswith("/8.0 MiB (4194304B)"), lines[-1]
    # 源码形状守卫: s3_request 的 GET 分支确实走分块读(不是又退回一次性 read)
    src = Path(ur.__file__).read_text(encoding="utf-8")
    assert 'if method == "GET" and progress_label is not None:' in src
    assert "data = _read_with_progress(resp, progress_label)" in src


# ---------------- 静态守卫: 三个拦截点在源码里确实存在(防回退) ----------------
def test_source_shape_three_interception_points_present():
    src = Path(ur.__file__).read_text(encoding="utf-8")
    for needle, why in [
        ('os.environ.get("R2_UPLOAD_WORK_TIMEOUT"', "未读取工作预算 env(倒挂未根治)"),
        ('_work_budget_check("s3_request-attempt")', "缺拦截点 b(attempt 前)"),
        ('_work_budget_check("s3_request-backoff")', "缺拦截点 b(退避前)"),
        ('_work_budget_check("s3_head-attempt")', "缺 HEAD 的 attempt 前门"),
        ('_work_budget_check("s3_head-backoff")', "缺 HEAD 的退避前门"),
        ('_work_budget_check("upload-file")', "缺拦截点 c(主上传文件间)"),
        ('_work_budget_check("backup-file")', "缺拦截点 c(备份文件间)"),
        ("timeout=_effective_request_timeout()", "缺拦截点 a(新连接超时未夹剩余)"),
        ("_set_conn_timeout(conn)", "缺拦截点 a(复用连接超时未刷)"),
        ("class WorkBudgetExceeded(SystemExit)", "到期必须抛 SystemExit(不许被 except Exception 吞)"),
    ]:
        assert needle in src, why
    # 到期语义: 退出码 124 + 不写 state(marker/进度保留)
    m = re.search(r"def _work_budget_check.*?WorkBudgetExceeded\(f", src, re.S)
    assert m, "工作预算门实现缺失/形状变了, 需同步本测试"
    assert "super().__init__(124)" in src


# =====================================================================================
# F1(三轮阻断项): 真 http.client 字节等价 —— 本地 http.server, 零外发
# -------------------------------------------------------------------------------------
# 病灶: T8a/T8b 用自造 `_FakeGetResp` 建模 read(), 只证明「拼接不丢不重」, 盖不到
#   chunked 解码 / gzip / Content-Length 非法 / 截断 这些**真实传输语义**。
# 做法(F1): 起本地 ThreadingHTTPServer + 真 http.client, 五形态各比一次
#   `_read_with_progress(...)` vs 原 `resp.read()`: **长度 + md5 逐位一致**。
# =====================================================================================
_F1_BIG = 8 * 1024 * 1024 + 12345                       # 8.4MiB(> 8MiB 打点阈值)
_F1_BODY = (bytes(range(256)) * (_F1_BIG // 256 + 1))[:_F1_BIG]   # 确定性非零内容(能识别错位)
_F1_SMALL = b"hello-small-" * 100
_F1_BOGUS = b"bogus-length-body"
_F1_GZ = gzip.compress(random.Random(42).randbytes(_F1_BIG), 1)   # 随机正文 ⇒ gzip 仍 >= 8MiB
_F1_CUT = 1000


class _FixedHandler(BaseHTTPRequestHandler):
    """五形态之①~⑤(除 chunked): HTTP/1.0; 无合法 CL 时靠关连接收尾。"""

    protocol_version = "HTTP/1.0"

    def log_message(self, *_a):     # 静默(否则 stderr 刷屏)
        pass

    def do_GET(self):
        p = self.path
        if p == "/big":
            self._fixed(_F1_BIG, _F1_BODY)
        elif p == "/small":
            self._fixed(len(_F1_SMALL), _F1_SMALL)
        elif p == "/bogus-cl":
            self.send_response(200)
            self.send_header("Content-Length", "n/a")      # 非法 CL ⇒ client 读不到长度
            self.end_headers()
            self.wfile.write(_F1_BOGUS)
            self.wfile.flush()
            self.close_connection = True
        elif p == "/gzip":
            self.send_response(200)
            self.send_header("Content-Length", str(len(_F1_GZ)))
            self.send_header("Content-Encoding", "gzip")
            self.end_headers()
            self.wfile.write(_F1_GZ)
            self.wfile.flush()
        elif p == "/trunc":
            self.send_response(200)
            self.send_header("Content-Length", str(_F1_BIG))   # 声明整包, 实际只发前 1000B
            self.end_headers()
            self.wfile.write(_F1_BODY[:_F1_CUT])
            self.wfile.flush()
            self.close_connection = True
        else:
            self.send_response(404)
            self.end_headers()

    def _fixed(self, n, body):
        self.send_response(200)
        self.send_header("Content-Length", str(n))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()


class _ChunkedHandler(BaseHTTPRequestHandler):
    """⑤ HTTP/1.1 chunked(自己按 chunk 帧写, client 侧 http.client 负责解码)。"""

    protocol_version = "HTTP/1.1"

    def log_message(self, *_a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        step = 700_000
        for i in range(0, _F1_BIG, step):
            part = _F1_BODY[i:i + step]
            self.wfile.write(b"%x\r\n" % len(part) + part + b"\r\n")
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()
        self.close_connection = True


@pytest.fixture(scope="module")
def http_forms():
    """起本地服务(127.0.0.1:随机端口), 跑完必关(不留残留端口/线程)。"""
    servers = []

    def _start(handler):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        srv.daemon_threads = True
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        servers.append((srv, th))
        return srv.server_address[1]

    port = _start(_FixedHandler)
    cport = _start(_ChunkedHandler)
    forms = {name: (port, path) for name, path in (
        ("plain-big", "/big"), ("small", "/small"),
        ("bogus-cl", "/bogus-cl"), ("gzip", "/gzip"), ("trunc", "/trunc"))}
    forms["chunked"] = (cport, "/chunked")
    try:
        yield forms
    finally:
        for srv, th in servers:
            srv.shutdown()
            srv.server_close()
            th.join(timeout=5)


def _f1_fetch(port, path, *, progress, label="f1"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        if progress:
            return ur._read_with_progress(resp, label)
        return resp.read()
    finally:
        conn.close()


@pytest.mark.parametrize("form", ["plain-big", "small", "bogus-cl", "gzip", "chunked"])
def test_f1_real_http_transport_byte_identical(form, http_forms, local_http_ok, capsys):
    """五形态: 分块读 == 原 read(), 长度 + md5 逐位一致(真 socket, 禁 mock)。

    「走没走分块读路径」也钉住: ≥8MiB(plain-big/gzip) 必须真打进度行; 小文件/长度未知/chunked
    (client 侧 CL=None)必须零进度行 —— 否则「等价」可能只是两边都退化成一次 read()。
    """
    port, path = http_forms[form]
    capsys.readouterr()                       # 清掉基线输出
    base = _f1_fetch(port, path, progress=False)
    got = _f1_fetch(port, path, progress=True, label=f"f1 {form}")
    out = capsys.readouterr().out
    expect = {"plain-big": _F1_BODY, "small": _F1_SMALL, "bogus-cl": _F1_BOGUS,
              "gzip": _F1_GZ, "chunked": _F1_BODY}[form]
    print(f"[F1 {form:10s}] len={len(got):9d} md5={hashlib.md5(got).hexdigest()} "
          f"进度行={out.count('↓ 下载中')}")
    assert len(got) == len(expect), f"{form}: 长度 {len(got)} != 服务端原始 {len(expect)}"
    assert hashlib.md5(got).digest() == hashlib.md5(expect).digest(), f"{form}: 内容 md5 不一致"
    assert len(got) == len(base) and got == base, f"{form}: 与 resp.read() 不等价"
    if form in ("plain-big", "gzip"):
        assert out.count("↓ 下载中") >= 2, f"{form}: 应走分块读并打进度, 实际没打(可能退化成一次 read)"
    else:
        assert "↓ 下载中" not in out, f"{form}: <8MiB/长度未知不该打进度行"


def test_f1_truncated_body_short_read_not_silently_accepted(http_forms, local_http_ok, monkeypatch):
    """截断体: 分块读**返回短包**(不抛、也不假装读全) ⇒ 必须靠下游 size 校验兜住。

    真实语义差异(实测): `HTTPResponse.read(n)` 读到 EOF 只返回短包; `read()` 才抛
    IncompleteRead。故分块读路径本身「安静」, 安全性完全依赖下游 `len(body) != size` 判定 ——
    本用例把那条链路真跑一遍(HEAD 报整包大小, GET 返回短包 ⇒ 记 GET 短读失败)。
    """
    port, path = http_forms["trunc"]
    short = _f1_fetch(port, path, progress=True, label="f1 trunc")
    print(f"[F1 trunc     ] 分块读返回 {len(short)}B / 声明 {_F1_BIG}B(短包被识别为短包)")
    assert 0 < len(short) < _F1_BIG, f"截断体应返回短包, 实得 {len(short)}B"
    assert short == _F1_BODY[:_F1_CUT]
    with pytest.raises(http.client.IncompleteRead):
        _f1_fetch(port, path, progress=False)     # 对照: read-all 会抛

    # 下游判定链路(upload_r2.py 的 P3 源体长度校验): 源码形状守卫 + 给出行号
    src = Path(ur.__file__).read_text(encoding="utf-8")
    needle = "if size_s is not None and len(body) != int(size_s):"
    assert needle in src, "短读判定(P3 源体长度校验)被删/改形, 截断体会静默放行"
    line_no = src[:src.index(needle)].count("\n") + 1
    assert "短读 len=" in src
    print(f"[F1 trunc     ] 依赖 upload_r2.py:{line_no} 的 size 校验(_fail GET 短读)")

    # 真跑该链路: 短包 + HEAD 声明整包 ⇒ 必须 failed(不许当成功备份)
    key = "data/f1_trunc.json"
    monkeypatch.setattr(ur, "s3_head",
                        lambda k, **_kw: (200, "0" * 32, _F1_BIG) if k == key else (404, None))
    monkeypatch.setattr(ur, "s3_request", lambda method, k, **_kw: (200, short))
    copied, skipped, failed, samples = ur._backup_overwritten_keys({key: "0" * 32}, "data-large")
    assert (copied, skipped, failed) == (0, 0, 1), f"短读必须记失败, 实得 {(copied, skipped, failed)}"
    assert samples and samples[0]["stage"] == "GET" and "短读" in samples[0]["detail"], samples


# =====================================================================================
# S1 / S3: turnover_backfill.sh 自检段(抠段到临时副本; 绝不跑脚本主体)
# -------------------------------------------------------------------------------------
# 红线: turnover_backfill.sh 主体含 pipeline/export/upload, 一律不执行。这里只把
#   「run_to 包装 + 三个预算常量 + FATAL/区间/梯度自检函数 + 两行真实 run_to 调用文本」
#   抠进临时宿主; 调用行放在 `if false; then ... fi` 里 —— 文本在场(供自检 grep 读字面量),
#   但永不执行。告警目标打桩: PY 指向记录器脚本(真 notify.py 永不执行, §18 L48)。
# =====================================================================================
def _slice(src: str, start: str, end: str) -> str:
    i = src.index(start)
    j = src.index(end, i)
    return src[i:j]


def _build_selfcheck_harness(tmp_path, *, splice=()):
    """用真实脚本的原文抠出可跑宿主; splice=[(旧,新)] 做变异。返回 (harness.sh, 记录器, 日志)。"""
    src = TB_SH.read_text(encoding="utf-8")
    run_to_fn = _slice(src, "run_to() {", "\n}\n") + "\n}\n"
    budget = _slice(src, "R2_LOCK_WAIT_BUDGET=", "\n\n# 进程互斥")
    checks = _slice(src, '_self_src="${BASH_SOURCE[0]}"', "\n\n# 4) 上传 R2")
    calls = re.findall(r"^[ \t]*run_to [0-9]+ env [^\n]*\\\n[^\n]*$", src, re.M)
    assert len(calls) == 2, f"脚本里 R2 调用行应为 2 处(实得 {len(calls)}), 本测试锚点需同步"

    stub = tmp_path / "notify-stub.sh"
    rec = tmp_path / "notify-calls.txt"
    log = tmp_path / "run.log"
    stub.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "' + str(rec) + '"\nexit 0\n',
                    encoding="utf-8")
    stub.chmod(0o755)

    lines = [
        "set -uo pipefail",
        f'PY="{stub}"',
        f'LOG="{log}"',
        f'REPO="{tmp_path}"',
        run_to_fn,
        budget,
        checks,
        "# 真实调用行原样内联(永不被执行; 仅供自检 grep 读 run_to 字面量)",
        "if false; then",
        *calls,
        "fi",
        "_r2_check_ranges",
        '_r2_check_step "upload-intraday" "R2_WORK_BUDGET_INTRADAY" '
        '"$R2_WORK_BUDGET_INTRADAY" "$OUTER_INTRADAY"',
        '_r2_check_step "upload-data-large" "R2_WORK_BUDGET" '
        '"$R2_WORK_BUDGET" "$OUTER_LARGE"',
        'echo HARNESS-PASS >> "$LOG"',
        'exit 0',
        "",
    ]
    body = "\n".join(lines)
    for old, new in splice:
        assert old in body, f"变异锚点不在宿主里: {old!r}"
        body = body.replace(old, new, 1)
    harness = tmp_path / "harness.sh"
    harness.write_text(body, encoding="utf-8")
    return harness, stub, rec, log


def _run_harness(harness, log):
    proc = subprocess.run(["bash", str(harness)], capture_output=True, text=True,
                          errors="replace", timeout=60)
    return proc, (log.read_text(encoding="utf-8") if log.exists() else "")


def test_s1_s3_selfcheck_passes_on_real_values(tmp_path):
    """基线: 现行真实数值 ⇒ 自检全过、无告警调用(守卫不误杀)。"""
    harness, _stub, rec, log = _build_selfcheck_harness(tmp_path)
    proc, logtxt = _run_harness(harness, log)
    assert proc.returncode == 0, proc.stderr + logtxt
    assert "HARNESS-PASS" in logtxt
    assert not rec.exists(), "自检通过时不许发任何告警"


def test_s1_notify_sandbox_proven_before_fatal_run(tmp_path):
    """§18 L48「先证沙箱生效」: PY 已被替换成本地记录器, 真 notify.py / 真外发链路不可达。"""
    harness, stub, rec, _log = _build_selfcheck_harness(tmp_path)
    text = harness.read_text(encoding="utf-8")
    assert f'PY="{stub}"' in text, "宿主必须把 PY 指向记录器(打桩)"
    assert "notify.py" in text, "脚本侧调用点仍在(打桩=替换 PY, 不是删调用)"
    stub_src = stub.read_text(encoding="utf-8")
    assert "curl" not in stub_src and "sendmail" not in stub_src and "python" not in stub_src
    # 记录器自证: 任何 `"$PY" scripts/notify.py …` 只落到本地文件, 不可能外发
    subprocess.run(["bash", str(stub), "scripts/notify.py", "[告警]", "--severe"],
                   capture_output=True, timeout=30, check=True)
    assert rec.read_text(encoding="utf-8").count("\n") == 1
    rec.unlink()          # 清掉自证记录, 保证后续用例的「零外发」计数从 0 起


def test_s1_fatal_branch_alerts_and_writes_end_line(tmp_path):
    """V3: 真倒挂(run_to 2760→2000) ⇒ FATAL 行 + 告警调用(打桩) + 标准「结束」行, exit 2。"""
    harness, _stub, rec, log = _build_selfcheck_harness(
        tmp_path, splice=[("run_to 2760 env", "run_to 2000 env")])
    proc, logtxt = _run_harness(harness, log)
    assert proc.returncode == 2, f"FATAL 应 exit 2, 实得 {proc.returncode}: {proc.stderr}"
    assert "FATAL: upload-intraday 预算梯度倒挂" in proc.stderr
    assert "FATAL: upload-intraday 预算梯度倒挂" in logtxt, "FATAL 必须同时落日志"
    calls = rec.read_text(encoding="utf-8")
    assert calls.count("\n") == 1, f"应恰好一条告警调用, 实得 {calls!r}"
    for needle in ("[告警]", "turnover 预算自检 FATAL", "--severe",
                   "--dedup-key turnover_backfill_budget_fatal", "--dedup-window 3600"):
        assert needle in calls, f"告警参数缺 {needle!r}: {calls!r}"
    assert "=== turnover_backfill.sh 结束" in logtxt and "退出码=2" in logtxt, logtxt[-400:]


@pytest.mark.parametrize("work_var,old_lit,new_lit,new_outer", [
    ("R2_WORK_BUDGET", "R2_WORK_BUDGET=3120", "R2_WORK_BUDGET=1200", ("run_to 4980 env", "run_to 3060 env")),
    ("R2_WORK_BUDGET_INTRADAY", "R2_WORK_BUDGET_INTRADAY=900", "R2_WORK_BUDGET_INTRADAY=300",
     ("run_to 2760 env", "run_to 2160 env")),
])
def test_s3_absolute_shrink_fails_even_when_relation_holds(
        tmp_path, work_var, old_lit, new_lit, new_outer):
    """V5: 工作预算缩水且外层同步(关系式仍成立) ⇒ 绝对值区间断言必须 FATAL。"""
    harness, _stub, _rec, log = _build_selfcheck_harness(
        tmp_path, splice=[(old_lit, new_lit), new_outer])
    proc, logtxt = _run_harness(harness, log)
    assert proc.returncode == 2, f"{work_var} 缩水应 FATAL, 实得 rc={proc.returncode}"
    assert f"{work_var}=" in proc.stderr and "越出区间" in proc.stderr, proc.stderr
    assert "=== turnover_backfill.sh 结束" in logtxt
    assert "HARNESS-PASS" not in logtxt


# =====================================================================================
# S2: r2_lock_gradient_audit.py 必须**从脚本实读**预算字面量(表不手抄)
# =====================================================================================
def test_s2_audit_reads_turnover_literals_and_fails_on_drift(tmp_path, monkeypatch, capsys):
    """V4: 副本 `run_to 4980→3000` / 工作 3120→1200 制造漂移 ⇒ 审计 FAIL(不许照抄表就过)。"""
    import r2_lock_gradient_audit as aud

    errs = []
    aud._check_turnover_literals(errs)
    assert errs == [], f"现行脚本与本表应一致, 实得 {errs}"

    src = TB_SH.read_text(encoding="utf-8")
    for old, new, why in [
        ("run_to 4980 env", "run_to 3000 env", "外层 run_to 漂移"),
        ("R2_WORK_BUDGET=3120", "R2_WORK_BUDGET=1200", "工作预算常量漂移"),
    ]:
        mut = tmp_path / f"tb_{why}.sh"
        mut.write_text(src.replace(old, new, 1), encoding="utf-8")
        monkeypatch.setattr(aud, "TB_SH", mut)
        errs2 = []
        aud._check_turnover_literals(errs2)
        assert errs2, f"{why}: 审计必须 FAIL(实得无错)"
        assert any("不一致" in e or "梯度不成立" in e for e in errs2), errs2
        capsys.readouterr()                        # 清掉 aud.main 的表格输出
        assert aud.main([]) == 1, f"{why}: 完整审计应以 FAIL 退出"