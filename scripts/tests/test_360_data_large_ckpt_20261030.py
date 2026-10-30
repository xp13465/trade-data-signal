# -*- coding: utf-8 -*-
"""#360 自测: data-large 启用分片续传, marker 残留不再跨调用方继承全量(2026-10-30)。

被测面 = `scripts/upload_r2.py::_incremental_upload` 的「marker_stale 判定 + checkpoint 续传」+
`cmd_upload_data_large` 的 `checkpoint_every=5` 调用点 + 新增 `_read_checkpoint`。

依据(任务书 + 实测):
  - data-large 常态 24 个文件(全量 ~270MB), 同 channel 有两个调用方
    (turnover_backfill 21:10 / r2_upload_async 21:31+), 共享同一个
    `.r2_data_large_uploading.marker` 与 `.r2_data_large_state.json`;
    一方失败留下的 marker 让另一方下一轮无条件全量(10-27~10-29 连续三天)。
  - 改法: marker 残留时「有可用进度就续传, 无进度 / 进度损坏才全量」。

零网络/零 R2 写: `_upload_glob` + `_backup_overwritten_keys` 全部 monkeypatch 成内存假传输,
STATIC_DIR 指到 tmp_path(状态/标记/进度文件全落 tmp), 另有 http.client.connect 阻断兜底
(§18 L48「自测零外发」同精神)。

§18 L51(时敏): 跑时刻由 env `R2_NOW_OVERRIDE` 冻结(周四), 不依赖真实星期, 隔天/跨周跑结论不变。

跑法: .venv/bin/python -m pytest -q scripts/tests/test_360_data_large_ckpt_20261030.py
"""
import hashlib
import json
import re
from pathlib import Path

import pytest

import upload_r2 as ur  # noqa: E402  (conftest 已注入 scripts/ 与仓库根路径)

N_FILES = 24                     # data-large 常态文件数(实测 24/24)
CKPT_EVERY = 5                   # 每 5 个落一次进度
STATE_NAME = ".r2_test_360_state.json"          # 测试私有名(不碰生产 .r2_*_state.json)
FROZEN_NOW = "2026-10-29T21:10:00"               # 周四(避开周日强制全量, 结论与真实日期无关)


def _paths(tmp_path):
    sd = tmp_path / "data"
    stem = STATE_NAME.replace("_state.json", "")
    return {
        "state": sd / STATE_NAME,
        "marker": sd / f"{stem}_uploading.marker",
        "ckpt": sd / f"{stem}_ckpt.json",
    }


def _mk_tree(tmp_path, monkeypatch, *, state="match", marker=None, ckpt=None):
    """铺 24 个文件 + 状态 + (可选)残留 marker / 进度文件; STATIC_DIR 指向 tmp 树。

    state="match" ⇒ 状态里 md5 与当前一致(平日增量集=0); "stale" ⇒ 全部指纹不符(增量集=24);
    "partial" ⇒ 后 4 个不符(增量集=4, 还原 10-27~10-29 的真实形态: 只有少数文件变过)。
    ckpt: None=不写; int N=前 N 个文件记为已完成(指纹取**真实** md5); str=原样写入(损坏样本)。
    """
    static = tmp_path / "static-site"
    local = static / "data"
    local.mkdir(parents=True)
    real = {}
    for i in range(N_FILES):
        p = local / f"data_large_{i:02d}.json"
        p.write_text(json.dumps({"i": i, "pad": "x" * 200}), encoding="utf-8")
        real[p.name] = hashlib.md5(p.read_bytes()).hexdigest()
    if state == "match":
        files = real
    elif state == "partial":
        files = {k: (v if i < N_FILES - 4 else "0" * 32) for i, (k, v) in enumerate(real.items())}
    else:  # stale
        files = {k: "0" * 32 for k in real}
    files = {k: {"size": (local / k).stat().st_size, "md5": v} for k, v in files.items()}
    monkeypatch.setattr(ur, "STATIC_DIR", static)
    ps = _paths(tmp_path)
    ps["state"].parent.mkdir(parents=True, exist_ok=True)
    ps["state"].write_text(json.dumps({"version": 1, "updated_at": "x", "mode": "增量",
                                       "count": len(files), "files": files, "changed": []}),
                           encoding="utf-8")
    if marker is not None:
        ps["marker"].write_text(marker, encoding="utf-8")
    if isinstance(ckpt, int):
        done = {f"data_large_{i:02d}.json": real[f"data_large_{i:02d}.json"]
                for i in range(ckpt)}
        ps["ckpt"].write_text(json.dumps({"version": 1, "updated_at": "x",
                                          "count": len(done), "files": done},
                                         ensure_ascii=False, sort_keys=True), encoding="utf-8")
    elif isinstance(ckpt, str):
        ps["ckpt"].write_text(ckpt, encoding="utf-8")
    return local, ps


def _fake_bits(monkeypatch, *, fail=(), on_each=None, backup_out=None):
    """内存假传输: 返回发出去的文件 rel 清单(升序); fail 里的 rel 记失败不回调 on_success。

    backup_out(list) 非 None 时, 收集「覆盖前备份」阶段被要求备份的 R2 key(证明全量口径)。
    """
    sent = []

    def _fake_backup(keys, _label):
        if backup_out is not None:
            backup_out.extend(sorted(keys))
        return 0, 0, 0, []

    def _fake_upload(local_dir, _patterns, prefix, only_files=None, on_success=None,
                     verify_etag=False):
        local_dir = Path(local_dir)
        files = sorted(Path(f) for f in (only_files or []))
        ok, failed, keys = 0, [], []
        for f in files:
            rel = str(f.relative_to(local_dir))
            if rel in fail:
                failed.append(rel)
                continue
            ok += 1
            keys.append(f"{prefix}/{rel}")
            sent.append(rel)
            if on_success is not None:
                on_success(f, rel)
            if on_each is not None:
                on_each(rel)
        return ok, len(files), failed, keys

    monkeypatch.setattr(ur, "_upload_glob", _fake_upload)
    monkeypatch.setattr(ur, "_backup_overwritten_keys", _fake_backup)
    return sent


@pytest.fixture(autouse=True)
def _frozen_now(monkeypatch):
    """冻结跑时刻(周四 21:10 = turnover 真实时点), 不受真实星期影响(§18 L51)。"""
    monkeypatch.setenv("R2_NOW_OVERRIDE", FROZEN_NOW)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """自测零外发机检: 任何 HTTP(S) 连接尝试直接报错。"""
    import http.client

    def _boom(*_a, **_k):
        raise AssertionError("自测期禁止真实网络连接(零外发铁律)")

    for cls in (http.client.HTTPConnection, http.client.HTTPSConnection):
        monkeypatch.setattr(cls, "connect", _boom, raising=False)


def _run(local, *, checkpoint_every=CKPT_EVERY, resume_on_stale_marker=True):
    """按 data-large 的调用口径跑引擎(两个开关都开)。"""
    return ur._incremental_upload(local, ["*.json"], "data", STATE_NAME,
                                  label="data-large", checkpoint_every=checkpoint_every,
                                  resume_on_stale_marker=resume_on_stale_marker)


def _ckpt_snapshot(ps):
    if not ps["ckpt"].exists():
        return None
    return json.loads(ps["ckpt"].read_text(encoding="utf-8"))


# ---------------- T1: 中途确实落盘(24 文件 / 每 5 个) ----------------
def test_t1_ckpt_written_midrun(tmp_path, monkeypatch, capsys):
    """24 文件全量跑一次, 进度必须在**中途**落盘(不只结束时), 成功收尾后清理。"""
    local, ps = _mk_tree(tmp_path, monkeypatch, state="match",
                         marker="2026-10-29T21:10:00 pid=999999", ckpt=None)
    seen = []

    def _spy(_rel):
        snap = _ckpt_snapshot(ps)
        if snap is not None:
            seen.append((snap["count"], sorted(snap["files"])[:3]))

    sent = _fake_bits(monkeypatch, on_each=_spy)
    ok, total, failed, _keys = _run(local)
    out = capsys.readouterr().out

    assert (ok, total, failed) == (N_FILES, N_FILES, [])
    assert "强制全量重传(fail-closed)" in out and "无进度文件" in out
    # 中途落盘时点 = 每 5 个一次(5/10/15/20); 24 不整除 ⇒ 最后一次落盘在 20, 期间可被 kill 恢复
    counts = [c for c, _ in seen]
    distinct = [c for i, c in enumerate(counts) if i == 0 or c != counts[i - 1]]
    assert distinct == [5, 10, 15, 20], f"进度落盘时点不对, 实得 {counts}"
    counts = distinct
    assert counts[-1] < N_FILES, "进度只在结束处才写 = 等于没启用(任务书点名的最容易做错的点)"
    # 贴一条真实进度内容(前几行)作证据
    first = _ckpt_snapshot(ps)
    assert first is None, "全成功收尾后进度文件应被清理"
    print("T1 首条进度样本(5 个完成时):", seen[0])
    print(f"T1 落盘次数={len(seen)} 落盘时点={counts}")


# ---------------- T2: 第二次带进度 ⇒ 只补剩余 ----------------
def test_t2_second_run_resumes_only_rest(tmp_path, monkeypatch, capsys):
    """进度已有 20/24 + 状态全是旧指纹 ⇒ 只补 4 个(待传数明显小于首次的 24)。"""
    local, ps = _mk_tree(tmp_path, monkeypatch, state="stale", marker=None, ckpt=20)
    sent = _fake_bits(monkeypatch)
    ok, total, failed, _keys = _run(local)
    out = capsys.readouterr().out

    assert (ok, total, failed) == (4, 4, [])
    assert len(sent) == 4 and not set(sent) & {f"data_large_{i:02d}.json" for i in range(20)}
    assert "↩ 断点续传: checkpoint 命中 20 个已上传(跳过), 本次实传 4 个" in out
    assert "模式=增量 本次待传 24/24" in out, "过滤前口径应为扫描出的待传 24(进度剔除发生在引擎内)"
    assert ps["ckpt"].exists() is False, "全成功收尾后进度文件应清理"


# ---------------- T3: marker 残留 + 完好进度 ⇒ 续传(不是全量) ----------------
def test_t3_stale_marker_with_good_ckpt_resumes(tmp_path, monkeypatch, capsys):
    """最锐利用例: 状态只有 4 个指纹不符(真实形态)+ marker 残留(pid 已死)+ 进度 20/24。

    改前: marker 一律罚全量 ⇒ 24 个重传; 改后: 有可用进度 ⇒ 只补那 4 个。
    """
    local, ps = _mk_tree(tmp_path, monkeypatch, state="partial",
                         marker="2026-10-28T21:31:24 pid=999999", ckpt=20)
    sent = _fake_bits(monkeypatch)
    ok, total, failed, _keys = _run(local)
    out = capsys.readouterr().out

    assert (ok, total, failed) == (4, 4, []), "marker 残留但有可用进度 ⇒ 应按进度续传 4 个"
    assert "有可用进度 20 个 → 按进度续传(只补未完成)" in out
    assert "模式=上次中断按进度续传" in out
    assert "强制全量重传" not in out
    assert len(sent) == 4
    assert ps["marker"].exists() is False, "本轮收尾成功应清掉残留 marker"


def test_t3b_stale_marker_state_all_match_uploads_nothing(tmp_path, monkeypatch, capsys):
    """边界: 状态全部命中(平日增量=0)+ marker 残留 + 可用进度 ⇒ 无需重传, 直接收口。

    诚实标注: 这里从「改前 24 个全量重传」变成「0 个」。安全性依据 = 状态清单只在
    PUT 成功 + ETag 对账后才写, md5 命中 ⇒ R2 对象内容一致, 重传对正确性零增量。
    """
    local, ps = _mk_tree(tmp_path, monkeypatch, state="match",
                         marker="2026-10-28T21:31:24 pid=999999", ckpt=20)
    sent = _fake_bits(monkeypatch)
    ok, total, failed, _keys = _run(local)
    out = capsys.readouterr().out
    assert (ok, total, failed, len(sent)) == (0, 0, [], 0)
    assert "有可用进度 20 个 → 按进度续传(只补未完成)" in out
    assert ps["marker"].exists() is False and ps["ckpt"].exists() is False


def test_t3_discriminating_power_no_checkpoint(tmp_path, monkeypatch, capsys):
    """判别力关: 同一场景关掉 checkpoint_every(0) ⇒ 必须回到全量 24, 断言真咬住新代码。"""
    local, _ps = _mk_tree(tmp_path, monkeypatch, state="match",
                          marker="2026-10-28T21:31:24 pid=999999", ckpt=20)
    sent = _fake_bits(monkeypatch)
    ok, total, _failed, _keys = _run(local, checkpoint_every=0)
    out = capsys.readouterr().out
    assert (ok, total) == (N_FILES, N_FILES), "未启用进度时 marker 残留仍应全量(fail-closed)"
    assert "强制全量重传(fail-closed)" in out and "模式=上次上传中断强制全量" in out
    assert len(sent) == N_FILES


def test_other_channel_default_keeps_full_on_stale_marker(tmp_path, monkeypatch, capsys):
    """其它通道(未开 resume_on_stale_marker)行为逐字不变: marker 残留 ⇒ 仍走全量口径。

    fund-nav 是唯一另一个启用 checkpoint 的通道(500), 它的 marker 语义必须保持原样:
    force_full 照旧成立(待传集合=全部 24, 覆盖前备份也按 24 个做), 只是既有进度过滤仍会
    剔掉已完成的 20 个 —— 这条「全量再扣进度」的老路径不动, 变的只有日志文案是否点名续传。
    """
    local, _ps = _mk_tree(tmp_path, monkeypatch, state="partial",
                          marker="2026-10-28T21:31:24 pid=999999", ckpt=20)
    backup_keys = []
    sent = _fake_bits(monkeypatch, backup_out=backup_keys)
    ok, total, _failed, _keys = _run(local, checkpoint_every=500,
                                     resume_on_stale_marker=False)
    out = capsys.readouterr().out
    assert (ok, total) == (4, 4), "实传数=全量 24 扣掉进度里已完成的 20(老路径)"
    assert len(backup_keys) == 4 and len(sent) == 4, "过滤后动作集与改前一致"
    assert ("⚠ 检测到上次上传未正常结束(.r2_test_360_uploading.marker), 强制全量重传(fail-closed)") in out
    assert "模式=上次上传中断强制全量" in out
    assert "按进度续传" not in out
    # force_full 口径的可观测残留: 状态里 changed 记的是「全量 24」而不是增量 4(改前即如此)
    st = json.loads(_ps["state"].read_text(encoding="utf-8"))
    assert st["mode"] == "上次上传中断强制全量" and len(st["changed"]) == N_FILES


# ---------------- T4: marker 残留但无进度 / 进度损坏 ⇒ 必须全量 ----------------
def test_t4a_stale_marker_without_ckpt_forces_full(tmp_path, monkeypatch, capsys):
    local, _ps = _mk_tree(tmp_path, monkeypatch, state="match",
                          marker="2026-10-29T21:10:00 pid=999999", ckpt=None)
    _fake_bits(monkeypatch)
    ok, total, _failed, _keys = _run(local)
    out = capsys.readouterr().out
    assert (ok, total) == (N_FILES, N_FILES)
    assert ("⚠ 检测到上次上传未正常结束(.r2_test_360_uploading.marker), 无可用进度"
            "(无进度文件), 强制全量重传(fail-closed)") in out
    assert "模式=上次上传中断强制全量" in out


def test_t4b_stale_marker_with_corrupt_ckpt_forces_full(tmp_path, monkeypatch, capsys):
    """进度文件写坏(半截 JSON)⇒ 不许当空集续传, 必须全量。"""
    local, _ps = _mk_tree(tmp_path, monkeypatch, state="match",
                          marker="2026-10-29T21:10:00 pid=999999", ckpt='{"version": 1, "files": {"a')
    _fake_bits(monkeypatch)
    ok, total, _failed, _keys = _run(local)
    out = capsys.readouterr().out
    assert (ok, total) == (N_FILES, N_FILES), "进度损坏必须退全量(fail-closed 不削弱)"
    assert "无可用进度(进度文件损坏/不可读), 强制全量重传(fail-closed)" in out
    assert "模式=上次上传中断强制全量" in out


def test_t4c_stale_marker_with_wrong_shape_ckpt_forces_full(tmp_path, monkeypatch, capsys):
    """进度文件结构不符(files 不是 dict)同样按损坏处理 ⇒ 全量。"""
    local, _ps = _mk_tree(tmp_path, monkeypatch, state="match",
                          marker="2026-10-29T21:10:00 pid=999999",
                          ckpt='{"version": 1, "files": []}')
    _fake_bits(monkeypatch)
    ok, total, _failed, _keys = _run(local)
    out = capsys.readouterr().out
    assert (ok, total) == (N_FILES, N_FILES)
    assert "进度文件损坏/不可读" in out


# ---------------- T5: 中途失败 ⇒ marker 保留 / state 不写 / 进度保留 ----------------
def test_t5_partial_failure_keeps_marker_state_ckpt(tmp_path, monkeypatch, capsys):
    local, ps = _mk_tree(tmp_path, monkeypatch, state="match",
                         marker="2026-10-29T21:10:00 pid=999999", ckpt=None)
    state_before = ps["state"].read_bytes()
    fail = {"data_large_21.json", "data_large_22.json", "data_large_23.json",
            "data_large_20.json"}
    _fake_bits(monkeypatch, fail=fail)
    with pytest.raises(SystemExit) as ei:
        _run(local)
    out = capsys.readouterr().out
    assert ei.value.code == 1
    assert "FAILED_FILES:" in out
    assert ps["marker"].exists(), "失败必须保留 marker(下轮据此判定)"
    assert ps["state"].read_bytes() == state_before, "失败不许写状态(宁多传不漏传)"
    snap = _ckpt_snapshot(ps)
    assert snap is not None and snap["count"] == 20, "进度必须保留已完成的 20 个"
    assert not set(snap["files"]) & fail


# ---------------- 调用点静态守卫: 启用且 N 必须是「会中途落盘」的量级 ----------------
def test_call_site_enabled_with_sane_n():
    src = Path(ur.__file__).read_text(encoding="utf-8")
    body = src.split("def cmd_upload_data_large(", 1)[1].split("\ndef ", 1)[0]
    m = re.search(r"checkpoint_every=(\d+)", body)
    assert m, "data-large 调用点未启用 checkpoint_every"
    n = int(m.group(1))
    assert 0 < n < N_FILES, (f"checkpoint_every={n} 不小于本通道文件数 {N_FILES} ⇒ "
                             f"永远不会中途落盘(照抄 fund-nav 的 200 就是这个坑)")
    assert n <= 5, f"checkpoint_every={n} 偏大: data-large 只有 ~24 个大文件, 断点粒度应在 5 以内"
    assert "resume_on_stale_marker=True" in body, "data-large 未开「有进度就续传」开关"
    # 除 data-large 外, 生产代码里不许出现第 3 个开此开关的通道(禁改其它 channel 行为)
    assert src.count("resume_on_stale_marker=True,") == 1