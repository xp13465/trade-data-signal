# -*- coding: utf-8 -*-
"""#364 自测: R2 内层工作预算(R2_UPLOAD_WORK_TIMEOUT)真实生效(2026-10-30)。

被测面 = `scripts/upload_r2.py` 的 #364 工作预算机制:
  - `_work_budget_begin/_remaining_work/_effective_request_timeout/_work_budget_check/_work_sleep`
  - 三个拦截点: a) 单请求 socket 超时 = min(配置, 剩余); b) 重试门(attempt 前 + 退避前);
    c) 文件间门(主上传 `_upload_glob._upload_one` / 备份 `_backup_one`)
  - 备份阶段单 PUT 的 progress_label(`[备份 xxx] ↑ 上传中 ...`)

对照病灶(10-29 实测): 单文件最坏 5 次重试 × 600s + 15s 退避 = 3015s > 外层 run_to 2760s,
外层先杀、python 来不及打失败日志 ⇒ 43 分钟黑屏。

零网络/零 R2 写: `_upload_glob` / `_backup_overwritten_keys` / `s3_request` / `s3_head` /
`http.client.HTTPSConnection` 全部 monkeypatch 成内存假实现; STATIC_DIR 指 tmp_path。
另有 http.client.connect 阻断兜底(§18 L48「自测零外发」)。

§18 L51(时敏): 跑时刻由 env `R2_NOW_OVERRIDE` 冻结(默认周四 21:10), 不依赖真实日期;
可用 `R2_TEST_NOW=2026-11-04T21:10:00` 平移一天复跑(验收 V10)。

跑法: .venv/bin/python -m pytest -q scripts/tests/test_364_work_budget_20261030.py
"""
import json
import os
import re
import socket
import time
from pathlib import Path

import pytest

import upload_r2 as ur  # noqa: E402  (conftest 已注入 scripts/ 与仓库根路径)

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


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """自测零外发机检: 任何真实 HTTP(S) 连接尝试直接报错。"""
    import http.client

    def _boom(*_a, **_k):
        raise AssertionError("自测期禁止真实网络连接(零外发铁律)")

    for cls in (http.client.HTTPConnection, http.client.HTTPSConnection):
        monkeypatch.setattr(cls, "connect", _boom, raising=False)


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