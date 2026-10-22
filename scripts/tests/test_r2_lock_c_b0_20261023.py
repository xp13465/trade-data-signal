# -*- coding: utf-8 -*-
"""R2 锁治理第一阶段:C(等锁诊断)+ B-0(data-large 分段计时)自测 —— 2026-10-23。

方案: docs/ops/r2-lock-plan-20261023.md §3.2(B-0)/§4(C);根因: docs/ops/r2-lock-contention-20261023.md。

**零上传 / 零外发**:全程打桩(`_backup_overwritten_keys` / `_upload_glob` 替身 + 本地临时文件),
不碰 R2、不跑备份、不调用 notify/邮件/飞书(§18 L48 先打桩;本文件连 nextday 模块都不 import,
因为它在 import 期会拉起 app/queries 与通知链路)。

覆盖:
  ① B-0 `[timing]` 格式可 grep + 只对 data-large 输出;
  ② 走一次 data-large 增量路径的**替身**流程, 断言 fingerprint/backup/upload/total 四行顺序齐;
  ③ C 超时诊断: 子进程 stderr 尾段 + 持锁进程字段进日志, 告警文案是说人话版;
  ④ 无心跳时回落「等了约 N 秒」, 探测不到时不谎称持锁者;
  ⑤ `_acquire_r2_upload_lock` fail-closed 分支打印持锁进程候选(原消息与退出码不变)。
"""
import fcntl
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(REPO))   # conftest §④ 已铺 .env 垫片, upload_r2 顶层 load_env() 可过

import r2_lock_probe as probe  # noqa: E402
import upload_r2 as ur  # noqa: E402


# ══════════════════════ ① B-0 格式 + 通道闸门 ══════════════════════
def test_phase_timing_format_and_scope(capsys):
    ur._phase_timing("data-large", "fingerprint", time.time() - 12.34, "files=23 pending=21")
    out = capsys.readouterr().out
    assert re.search(
        r"^\[timing\] phase=fingerprint elapsed=1[23]\.\d+s channel=data-large files=23 pending=21$",
        out, re.M), f"timing 行格式不符: {out!r}"

    ur._phase_timing("etf-hist", "upload", time.time())
    assert "[timing]" not in capsys.readouterr().out, "非 data-large 通道不应新增 timing 行(不打扰其余 11 通道日志)"


# ══════════════════════ ② data-large 全程四段(替身, 零上传) ══════════════════════
def test_incremental_upload_emits_four_phases(tmp_path, monkeypatch, capsys):
    static = tmp_path / "static-site"
    data_dir = static / "data"
    data_dir.mkdir(parents=True)
    target = data_dir / "a-stock-all.json"      # 命中 _LARGE_RANGE_RE, 不需真造 1MB
    target.write_text('{"k": 1}', encoding="utf-8")

    # 状态文件放在 STATIC_DIR.parent/data/(引擎口径), 旧 md5 制造「增量待传」
    state_dir = tmp_path / "data"
    state_dir.mkdir()
    (state_dir / ".r2_data_large_state.json").write_text(
        '{"version": 1, "files": {"a-stock-all.json": {"size": 1, "md5": "old"}}}',
        encoding="utf-8")

    monkeypatch.setattr(ur, "STATIC_DIR", static)
    monkeypatch.setattr(ur, "_now", lambda: datetime(2026, 10, 22, 22, 30, 0))  # 周四, 冻结运行日
    monkeypatch.setattr(ur, "_backup_overwritten_keys",
                        lambda r2_keys, label, md5_map=None: (1, 0, 0, []))
    monkeypatch.setattr(ur, "_upload_glob",
                        lambda *a, **k: (1, 1, [], ["data/a-stock-all.json"]))

    ok, total, failed, uploaded = ur._incremental_upload(
        data_dir, ["*.json"], "data", ".r2_data_large_state.json",
        exclude_fn=lambda f: not ur._is_data_large_file(f), label="data-large")
    assert (ok, total, failed) == (1, 1, [])
    assert uploaded == ["data/a-stock-all.json"], "上传替身应被调用(证明打桩生效、无真上传)"

    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("[timing]")]
    phases = [re.match(r"\[timing\] phase=(\w+)", ln).group(1) for ln in lines]
    assert phases == ["fingerprint", "preupload_backup", "upload", "total"], f"四段顺序不符: {phases}"
    assert "copied=1 skipped=0 failed=0" in lines[1]
    assert "ok=1 total=1" in lines[2]
    assert all("channel=data-large" in ln for ln in lines)


# ══════════════════════ ③ C 诊断文案(纯函数, 零外发) ══════════════════════
def _timeout_exc(stderr_text, timeout=480):
    exc = subprocess.TimeoutExpired(cmd=["python3", "upload_r2.py"], timeout=timeout)
    exc.stderr = stderr_text.encode("utf-8")
    exc.stdout = b""
    return exc


def test_lock_timeout_diag_human_readable():
    tail = (
        "⏳ 等待 R2 上传锁 30s(上限 7300s, 持锁进程可用 lsof /tmp/trade_r2_upload.lock 排查)\n"
        "⏳ 等待 R2 上传锁 420s(上限 7300s, 持锁进程可用 lsof /tmp/trade_r2_upload.lock 排查)\n"
    )
    log_text, subject, body = probe.build_lock_timeout_diag(
        _timeout_exc(tail),
        lock_path="/tmp/trade_r2_upload.lock",
        log_path="/repo/data/logs/nextday_plan_launchd.log",
        date_tag="20261022",
        subject_prefix="[告警] 次日买入计划 R2",
        source="nextday_plan_generator.py",
        file_names=["nextday_plan.json", "auto_trade_steps.json", "signal_kelly_day_snapshot.json"],
        probe=lambda _p: "pid=41022(已运行 24:13) python3 upload_r2.py upload-data-large",
    )
    # 子进程 stderr 尾段(等锁心跳)→ 日志
    assert "等待 R2 上传锁 420s" in log_text
    # 持锁进程字段 → 日志
    assert "pid=41022" in log_text and "upload-data-large" in log_text
    # 说人话的告警: 「上传前排队等锁超时(等了 N 秒, 被 <持锁任务> 占着)」
    assert "上传前排队等锁超时(等了 420 秒, 被 pid=41022" in body
    assert "本次要传的是 3 个小文件" in body
    assert subject == "[告警] 次日买入计划 R2 上传前排队等锁超时 20261022"
    assert "R2 上传超时" not in subject, "旧黑话「R2 上传超时」不应再出现在标题"
    # 等锁秒数取心跳最大值(30/420 → 420)
    assert probe.parse_lock_wait_secs(tail) == 420


def test_lock_timeout_diag_no_heartbeat_falls_back():
    log_text, _subject, body = probe.build_lock_timeout_diag(
        _timeout_exc(""),
        lock_path="/tmp/trade_r2_upload.lock",
        log_path="/repo/x.log",
        date_tag="20261022",
        probe=lambda _p: "",
    )
    assert "等了约 480 秒" in body, "无心跳时应保守说「约 480 秒」, 不谎称精确值"
    assert "未知(只读探测不到持锁进程" in log_text
    assert "子进程输出尾段(等锁心跳):\n(空)" in log_text


# ══════════════════════ ④ probe_lock_holder 只读、失败不抛 ══════════════════════
def test_probe_lock_holder_missing_file_returns_empty():
    assert probe.probe_lock_holder("/tmp/__no_such_r2_lock_probe__.lock") == ""


@pytest.mark.skipif(shutil.which("lsof") is None, reason="本机无 lsof(精简镜像)⇒ 探测按设计返回空串")
def test_probe_lock_holder_sees_open_fd(tmp_path):
    lock = tmp_path / "probe.lock"
    fh = open(lock, "w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        desc = probe.probe_lock_holder(lock)
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()
    assert f"pid={os.getpid()}" in desc, f"lsof 应能看到持有该 fd 的本进程: {desc!r}"


# ══════════════════════ ⑤ upload_r2 fail-closed 分支打印持锁候选 ══════════════════════
def test_fail_closed_prints_lock_holder(tmp_path, monkeypatch, capsys):
    lock = tmp_path / "held.lock"
    holder = open(lock, "w")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
    try:
        monkeypatch.setenv("R2_UPLOAD_LOCK", str(lock))
        monkeypatch.setenv("R2_UPLOAD_LOCK_TIMEOUT", "1")
        monkeypatch.setattr(ur, "_R2_LOCK_HEARTBEAT_SECS", 3600)   # 不制造心跳噪音
        monkeypatch.setattr(ur, "probe_lock_holder",
                            lambda _p, _m=3: "pid=41022(已运行 24:13) python3 upload_r2.py upload-data-large")
        with pytest.raises(SystemExit) as ei:
            ur._acquire_r2_upload_lock()
        assert ei.value.code == 1, "fail-closed 退出码必须仍是 1(控制流未变)"
        err = capsys.readouterr().err
        assert "排队等待超" in err, "原 fail-closed 文案必须保留(其余测试与运维口径依赖)"
        assert "占锁进程候选(lsof 只读): pid=41022" in err
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()