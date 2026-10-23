# -*- coding: utf-8 -*-
"""R2 锁治理 A 方案(小文件独立锁 + B0-1 同 key 收口)自测 —— 2026-10-23。

方案: docs/ops/r2-lock-plan-20261023.md §2.2(A1~A4)/§2.4(证据用例)/§2.6(d)(B0-1 台账收口);
根因: docs/ops/r2-lock-contention-20261023.md。

**零上传 / 零网络 / 零写 R2**:全程本地临时目录 + 打桩(`_incremental_upload` / `purge_cache`),
锁文件全部落在 pytest tmp_path(env R2_UPLOAD_LOCK / R2_UPLOAD_SMALL_LOCK 覆盖),不碰生产锁,
不 import/调用任何上传/备份/通知实现(§18 L48 先打桩)。

覆盖(对应任务书「证据用例」):
  ① 路由:非 upload-data-files 命令一律全局锁(原行为);
  ② 路由:小载荷 → 小锁;大 range 文件名 / ≥1MB / 总字节超阈值 / R2_SMALL_CHANNEL=0 → 回全局锁;
  ③ 取锁:小锁被占时全局锁仍可获取,反之亦然(两把锁互不阻塞);
  ④ 取锁:__main__ 单点(_acquire_lock_for_command)——data-files 小载荷不排全局队列,
     其余命令照旧在全局锁上排队(fail-closed exit 1 语义不变);
  ⑤ 默认参数路径:不传 lock_path_override = 沿用 env R2_UPLOAD_LOCK(现有调用方行为不变);
  ⑥ B0-1:all-data 跳过台账内有效 key;过期后重新纳入;env TTL 覆盖;
  ⑦ 台账格式:dict 带时间戳、旧 list 格式兼容并迁移、时间戳坏按过期、写侧清理过期条目;
  ⑧ verify-r2 侧 _load_standalone_keys 语义不变(不过滤过期, 覆盖面只增不减);
  ⑨ 审查建议 1: 旧 list 条目按台账 mtime 定基准(取不到 mtime ⇒ 立即过期, 不永真);
  ⑩ 审查建议 2: 超时诊断逐把探测全局锁 + 小锁(哪把被占能在文案里定位到);
  ⑪ 审查建议 2 防漂移: 4 处调用方统一走 probe_locks/lock_paths_from_env, 不复制路由判定。
"""
import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(REPO))   # conftest 已铺 .env 垫片, upload_r2 顶层 load_env() 可过

import r2_lock_probe as probe  # noqa: E402
import upload_r2 as ur  # noqa: E402

T0 = datetime(2026, 10, 22, 22, 30, 0)


# ══════════════════════ 公共夹具 ══════════════════════
@pytest.fixture
def lane(tmp_path, monkeypatch):
    """隔离环境: STATIC_DIR 指向临时树, 两把锁都指向 tmp 下的测试文件。

    返回 (static_dir, data_dir, global_lock, small_lock, clock)。
    clock["now"] 可改, 用于推进「台账条目年龄」而不 sleep。
    """
    static = tmp_path / "static-site"
    data_dir = static / "data"
    data_dir.mkdir(parents=True)
    global_lock = tmp_path / "test_global.lock"
    small_lock = tmp_path / "test_small.lock"
    monkeypatch.setattr(ur, "STATIC_DIR", static)
    monkeypatch.setenv("R2_UPLOAD_LOCK", str(global_lock))
    monkeypatch.setenv("R2_UPLOAD_SMALL_LOCK", str(small_lock))
    monkeypatch.delenv("R2_SMALL_CHANNEL", raising=False)
    monkeypatch.delenv("R2_SMALL_CHANNEL_MAX_BYTES", raising=False)
    monkeypatch.delenv("R2_STANDALONE_KEY_TTL_DAYS", raising=False)
    monkeypatch.setenv("R2_UPLOAD_LOCK_TIMEOUT", "1")
    monkeypatch.setattr(ur, "_R2_LOCK_HEARTBEAT_SECS", 3600)   # 不制造心跳噪音
    clock = {"now": T0}
    monkeypatch.setattr(ur, "_now", lambda: clock["now"])
    return static, data_dir, global_lock, small_lock, clock


def _mk(data_dir, name, size):
    p = data_dir / name
    p.write_bytes(b"x" * size)
    return p


def _set_mtime(path, when):
    """把文件 mtime 冻结成 when(按本地墙钟换算, 与 _legacy_ledger_ts 的 fromtimestamp 对称)。

    用例一律显式设置 mtime, 不依赖「测试运行时真实日期」(§18 L51: 禁写死/依赖运行日)。
    """
    ts = time.mktime(when.timetuple())
    os.utime(path, (ts, ts))


def _write_legacy_ledger(lane, keys, mtime):
    """造一份旧 list 格式台账, 并把 mtime 冻结成给定时刻。"""
    _static, _data_dir, _global_lock, _small_lock, _clock = lane
    ledger_path = ur._standalone_keys_path()
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(list(keys)), encoding="utf-8")
    if mtime is not None:
        _set_mtime(ledger_path, mtime)
    return ledger_path


# ══════════════════════ ① 路由: 非 data-files 命令 ══════════════════════
@pytest.mark.parametrize("cmd", [
    "upload-data-large", "upload-all-data", "upload-index", "verify-r2",
    "upload-kelly-parts", "purge-low-freq",
])
def test_route_non_data_files_commands_always_global(cmd, lane):
    _static, _data_dir, global_lock, small_lock, _clock = lane
    got = ur._route_upload_lock(cmd, ["nextday_plan.json"])
    assert got == global_lock, f"{cmd} 必须仍拿全局锁(方案 A 只动 data-files)"
    assert got != small_lock


# ══════════════════════ ② 路由: 小载荷 / 各类退回全局锁 ══════════════════════
def test_route_small_payload_uses_small_lock(lane):
    """nextday 实测三文件量级(246B/91,708B/29,916B)⇒ 小锁。"""
    _static, data_dir, _global_lock, small_lock, _clock = lane
    names = []
    for name, size in (("nextday_plan.json", 246), ("auto_trade_steps.json", 91708),
                       ("signal_kelly_day_snapshot.json", 29916)):
        _mk(data_dir, name, size)
        names.append(name)
    assert ur._route_upload_lock("upload-data-files", names) == small_lock


def test_route_large_range_name_falls_back_to_global(lane):
    """命中 _LARGE_RANGE_RE(-all/-5y/-3y)即使只有几字节也回全局锁(硬闸门, 防与 data-large 同 key)。"""
    _static, data_dir, global_lock, _small_lock, _clock = lane
    _mk(data_dir, "a-stock-all.json", 4)
    assert ur._route_upload_lock("upload-data-files", ["a-stock-all.json"]) == global_lock
    _mk(data_dir, "sentiment-3y.json", 4)
    assert ur._route_upload_lock("upload-data-files", ["sentiment-3y.json"]) == global_lock


def test_route_1mb_file_falls_back_to_global(lane):
    """≥1MB(upload-data-large 的取件判据)⇒ 全局锁。"""
    _static, data_dir, global_lock, _small_lock, _clock = lane
    _mk(data_dir, "big_plain.json", ur.LARGE_THRESHOLD)
    assert ur._route_upload_lock("upload-data-files", ["big_plain.json"]) == global_lock


def test_route_overfit_monitor_prefix_falls_back_to_global(lane):
    """overfit_monitor* 属 data-large 取件范围 ⇒ 全局锁(不受大小影响)。"""
    _static, data_dir, global_lock, _small_lock, _clock = lane
    _mk(data_dir, "overfit_monitor_x.json", 10)
    assert ur._route_upload_lock("upload-data-files", ["overfit_monitor_x.json"]) == global_lock


def test_route_total_bytes_threshold_default_and_env(lane, monkeypatch):
    """阈值 8MB 是方案 §2.2.1 定死的默认值; 超过 → 全局锁; env 可覆盖。"""
    _static, data_dir, global_lock, small_lock, clock = lane
    assert ur._SMALL_CHANNEL_MAX_BYTES_DEFAULT == 8 * 1024 * 1024
    assert ur._small_channel_max_bytes() == 8 * 1024 * 1024   # 无 env = 方案默认值
    _mk(data_dir, "a.json", 60)
    _mk(data_dir, "b.json", 60)
    # 默认 8MB 下 120B 远小于阈值 ⇒ 小锁
    assert ur._route_upload_lock("upload-data-files", ["a.json", "b.json"]) == small_lock
    # env 压到 100B ⇒ 120B 超阈值 ⇒ 全局锁(阈值只影响走哪把锁)
    monkeypatch.setenv("R2_SMALL_CHANNEL_MAX_BYTES", "100")
    assert ur._route_upload_lock("upload-data-files", ["a.json", "b.json"]) == global_lock
    # 恰好等于阈值不算超(> 才退回)
    monkeypatch.setenv("R2_SMALL_CHANNEL_MAX_BYTES", "120")
    assert ur._route_upload_lock("upload-data-files", ["a.json", "b.json"]) == small_lock
    # 非法值(非数字 / 负数)回默认 8MB —— 坏 env 不能把阈值误判成 0 导致小锁通道被悄悄关掉
    monkeypatch.setenv("R2_SMALL_CHANNEL_MAX_BYTES", "abc")
    assert ur._small_channel_max_bytes() == 8 * 1024 * 1024
    monkeypatch.setenv("R2_SMALL_CHANNEL_MAX_BYTES", "-5")
    assert ur._small_channel_max_bytes() == 8 * 1024 * 1024


def test_route_missing_file_still_small(lane):
    """不存在的文件(stat 失败)按 0 字节处理 ⇒ 小锁; cmd 侧照旧打印「⚠ 无文件」。

    这正是方案 §2.4 用例 2 的形状: 传一个不存在的文件名, 验证它不去排全局队列。
    """
    _static, _data_dir, _global_lock, small_lock, _clock = lane
    assert ur._route_upload_lock("upload-data-files", ["__no_such_file__.json"]) == small_lock


def test_route_env_switch_off_rolls_back_to_global(lane, monkeypatch):
    """回滚开关 R2_SMALL_CHANNEL=0 ⇒ 恒全局锁(一行 env 回现状, 不用回滚代码)。"""
    _static, data_dir, global_lock, _small_lock, _clock = lane
    _mk(data_dir, "nextday_plan.json", 246)
    monkeypatch.setenv("R2_SMALL_CHANNEL", "0")
    assert ur._route_upload_lock("upload-data-files", ["nextday_plan.json"]) == global_lock


# ══════════════════════ ③ 两把锁互不阻塞(真实 flock, 零网络) ══════════════════════
def test_two_locks_do_not_block_each_other(lane, capsys):
    _static, _data_dir, _global_lock, _small_lock, _clock = lane
    small_fd = ur._acquire_r2_upload_lock(lock_path_override=ur._small_upload_lock_path())
    assert isinstance(small_fd, int), "小锁应能立即拿到"
    try:
        # 小锁被占时, 全局锁仍可拿(证明两者是不同对象)
        global_fd = ur._acquire_r2_upload_lock()
        assert isinstance(global_fd, int), "小锁被占时全局锁必须仍可获取"
        try:
            # 反过来: 自己那一把再拿一次必然失败(fail-closed exit 1), 语义与原全局锁一致
            with pytest.raises(SystemExit) as ei:
                ur._acquire_r2_upload_lock(lock_path_override=ur._small_upload_lock_path())
            assert ei.value.code == 1
            with pytest.raises(SystemExit) as ei2:
                ur._acquire_r2_upload_lock()
            assert ei2.value.code == 1
        finally:
            os.close(global_fd)
    finally:
        os.close(small_fd)
    err = capsys.readouterr().err
    assert "排队等待超" in err


# ══════════════════════ ④ __main__ 取锁单点(零 R2 流量) ══════════════════════
def test_lock_for_command_small_lane_skips_global_queue(lane, capsys):
    """全局锁被占时, upload-data-files 小载荷**立刻**拿到小锁(不再排 1420–2575s 的队)。"""
    _static, data_dir, global_lock, _small_lock, _clock = lane
    _mk(data_dir, "nextday_plan.json", 246)
    holder = open(global_lock, "w")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
    try:
        t0 = time.time()
        fd = ur._acquire_lock_for_command(
            "upload-data-files", ["nextday_plan.json", "__no_such_file__.json"])
        elapsed = time.time() - t0
        assert isinstance(fd, int), "应拿到小锁, 而不是 sleep 到超时"
        os.close(fd)
        assert elapsed < 1.0, f"不得排全局队列(实测 {elapsed:.2f}s, timeout=1s)"
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()
    assert "排队等待超" not in capsys.readouterr().err


def test_lock_for_command_other_cmd_still_queues_on_global(lane, capsys):
    """对照组: 其余命令在全局锁被占时照旧 fail-closed(exit 1, 文案含全局锁路径)。"""
    _static, _data_dir, global_lock, _small_lock, _clock = lane
    holder = open(global_lock, "w")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
    try:
        with pytest.raises(SystemExit) as ei:
            ur._acquire_lock_for_command("upload-data-large", [])
        assert ei.value.code == 1, "不得改变既有 fail-closed 退出码"
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()
    err = capsys.readouterr().err
    assert f"R2 上传锁 {global_lock}" in err, "回归: 仍是全局锁原文案(带锁路径)"


def test_lock_for_command_large_payload_still_queues_on_global(lane, capsys):
    """data-files 但载荷命中大文件判据 ⇒ 照旧排全局锁(硬闸门在取锁单点生效)。"""
    _static, data_dir, global_lock, _small_lock, _clock = lane
    _mk(data_dir, "a-stock-all.json", 4)
    holder = open(global_lock, "w")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
    try:
        with pytest.raises(SystemExit) as ei:
            ur._acquire_lock_for_command("upload-data-files", ["a-stock-all.json"])
        assert ei.value.code == 1
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()
    assert f"R2 上传锁 {global_lock}" in capsys.readouterr().err


# ══════════════════════ ⑤ 默认参数路径 = 原全局锁(现有调用方不变) ══════════════════════
def test_default_lock_path_unchanged(lane, capsys, monkeypatch):
    """不传 lock_path_override ⇒ 读 env R2_UPLOAD_LOCK(生产即原路径), 不碰小锁。"""
    _static, _data_dir, global_lock, small_lock, _clock = lane
    holder = open(global_lock, "w")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
    try:
        with pytest.raises(SystemExit):
            ur._acquire_r2_upload_lock()
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()
    err = capsys.readouterr().err
    assert str(global_lock) in err
    assert str(small_lock) not in err
    # 无 env 时的生产默认值也钉死(防被顺手改掉)
    monkeypatch.delenv("R2_UPLOAD_LOCK", raising=False)
    assert ur._global_upload_lock_path() == Path("/tmp/trade_r2_upload.lock")
    monkeypatch.delenv("R2_UPLOAD_SMALL_LOCK", raising=False)
    assert ur._small_upload_lock_path() == Path("/tmp/trade_r2_upload_small.lock")


def test_cmd_upload_data_files_no_file_returns_without_lock_use(lane, capsys):
    """cmd 侧「无文件」快速返回(方案 §2.4 用例 2 的终点行为), 不触发任何上传。"""
    _static, _data_dir, _global_lock, _small_lock, _clock = lane
    ur.cmd_upload_data_files(["__no_such_file__.json"])
    assert "⚠ 无文件" in capsys.readouterr().out


# ══════════════════════ ⑥ B0-1: all-data 跳过台账 key + 过期失效 ══════════════════════
def _capture_all_data(monkeypatch):
    """跑 cmd_upload_all_data, 拦下它实际使用的 exclude_fn 与 purge 入参(零上传)。"""
    captured = {}
    purged = []

    def fake_engine(local_dir, patterns, prefix, state_name, **kw):
        captured["exclude_fn"] = kw["exclude_fn"]
        captured["label"] = kw.get("label")
        return 0, 0, [], []

    monkeypatch.setattr(ur, "_incremental_upload", fake_engine)
    monkeypatch.setattr(ur, "purge_cache", lambda keys: purged.append(list(keys)))
    ur.cmd_upload_all_data()
    return captured["exclude_fn"], purged


def test_all_data_skips_active_standalone_keys(lane, monkeypatch):
    """台账内有效 key ⇒ all-data 跳过(两个写入者结构性拆开, 方案 §2.6(d) B0-1)。"""
    _static, data_dir, _global_lock, _small_lock, _clock = lane
    _mk(data_dir, "nextday_plan.json", 246)
    _mk(data_dir, "schedule_stats.json", 500)
    _mk(data_dir, "overview.json", 800)
    ur._record_standalone_keys(["data/nextday_plan.json", "data/schedule_stats.json"])

    exclude_fn, _purged = _capture_all_data(monkeypatch)
    assert exclude_fn(data_dir / "nextday_plan.json") is True, "台账内 key 必须被 all-data 跳过"
    assert exclude_fn(data_dir / "schedule_stats.json") is True
    assert exclude_fn(data_dir / "overview.json") is False, "非台账 key 仍归 all-data"


def test_all_data_still_excludes_large_files(lane, monkeypatch):
    """回归: 原有排除口径(≥1MB 等)不受 B0-1 影响。"""
    _static, data_dir, _global_lock, _small_lock, _clock = lane
    _mk(data_dir, "big_plain.json", ur.LARGE_THRESHOLD)
    _mk(data_dir, "overfit_monitor_x.json", 10)
    exclude_fn, _purged = _capture_all_data(monkeypatch)
    assert exclude_fn(data_dir / "big_plain.json") is True
    assert exclude_fn(data_dir / "overfit_monitor_x.json") is True


def test_all_data_reincludes_expired_ledger_key(lane, monkeypatch):
    """过期规则: 台账条目超 TTL 未再被 data-files 登记 ⇒ 失效, all-data 重新接管(防新型漏传)。"""
    _static, data_dir, _global_lock, _small_lock, clock = lane
    _mk(data_dir, "nextday_plan.json", 246)
    _mk(data_dir, "schedule_stats.json", 500)
    ur._record_standalone_keys(["data/nextday_plan.json", "data/schedule_stats.json"])

    # 第 16 天: 只有 nextday 又被 data-files 上传过(schedule_stats 停更 16 天 > 14 天 TTL)
    clock["now"] = T0 + timedelta(days=16)
    ur._record_standalone_keys(["data/nextday_plan.json"])
    assert ur._active_standalone_keys() == {"data/nextday_plan.json"}

    # 第 21 天: nextday 5 天前刚更新过(仍有效); schedule_stats 已 21 天未更新 ⇒ 失效
    clock["now"] = T0 + timedelta(days=21)
    assert ur._active_standalone_keys() == {"data/nextday_plan.json"}
    exclude_fn, _purged = _capture_all_data(monkeypatch)
    assert exclude_fn(data_dir / "nextday_plan.json") is True
    assert exclude_fn(data_dir / "schedule_stats.json") is False, "过期条目必须交回 all-data"


def test_ledger_ttl_env_override(lane, monkeypatch):
    """TTL 可配置: R2_STANDALONE_KEY_TTL_DAYS=1 ⇒ 2 天未更新即失效。"""
    _static, data_dir, _global_lock, _small_lock, clock = lane
    _mk(data_dir, "nextday_plan.json", 246)
    ur._record_standalone_keys(["data/nextday_plan.json"])
    clock["now"] = T0 + timedelta(days=2)
    assert ur._active_standalone_keys() == {"data/nextday_plan.json"}, "默认 14 天内仍有效"
    monkeypatch.setenv("R2_STANDALONE_KEY_TTL_DAYS", "1")
    assert ur._active_standalone_keys() == set(), "TTL=1 天时 2 天前的条目应失效"
    monkeypatch.setenv("R2_STANDALONE_KEY_TTL_DAYS", "not-a-number")
    assert ur._standalone_key_ttl_days() == ur._STANDALONE_KEY_TTL_DAYS, "非法值回默认"


def test_all_data_behaves_as_before_when_ledger_missing(lane, monkeypatch):
    """台账缺失 ⇒ 不跳过任何文件(行为完全回到改动前, 不会因台账异常少传)。"""
    _static, data_dir, _global_lock, _small_lock, _clock = lane
    _mk(data_dir, "nextday_plan.json", 246)
    assert not ur._standalone_keys_path().exists()
    assert ur._active_standalone_keys() == set()
    exclude_fn, _purged = _capture_all_data(monkeypatch)
    assert exclude_fn(data_dir / "nextday_plan.json") is False


# ══════════════════════ ⑦ 台账格式: dict 时间戳 / 旧 list 兼容 / 坏时间戳 / 写侧清理 ══════════════════════
def test_ledger_written_as_dict_with_last_seen(lane):
    _static, data_dir, _global_lock, _small_lock, clock = lane
    _mk(data_dir, "nextday_plan.json", 246)
    ur._record_standalone_keys(["data/nextday_plan.json"])
    raw = json.loads(ur._standalone_keys_path().read_text(encoding="utf-8"))
    assert isinstance(raw, dict), "新格式必须是 dict(key -> 最后登记时刻)"
    assert raw == {"data/nextday_plan.json": "2026-10-22 22:30:00"}

    clock["now"] = T0 + timedelta(days=3)
    ur._record_standalone_keys(["data/nextday_plan.json"])
    raw = json.loads(ur._standalone_keys_path().read_text(encoding="utf-8"))
    assert raw == {"data/nextday_plan.json": "2026-10-25 22:30:00"}, "再次上传必须刷新时间戳"


def test_ledger_legacy_list_still_readable_and_migrated(lane):
    """旧格式(list, 生产现存格式)必须可读; 之后一次登记即落成 dict(平滑迁移)。"""
    _static, data_dir, _global_lock, _small_lock, _clock = lane
    _mk(data_dir, "nextday_plan.json", 246)
    ledger_path = ur._standalone_keys_path()
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(["data/nextday_plan.json"]), encoding="utf-8")
    _set_mtime(ledger_path, T0)   # 刚迁移: 台账 mtime = 今天(冻结, 不依赖运行日)

    keys, state = ur._load_standalone_keys(warn=False)
    assert state == ur._LEDGER_OK and keys == {"data/nextday_plan.json"}
    assert ur._active_standalone_keys() == {"data/nextday_plan.json"}, \
        "旧格式条目按台账 mtime 定基准; mtime=今天 ⇒ 仍有效(不一把全过期)"

    ur._record_standalone_keys(["data/nextday_plan.json"])
    assert isinstance(json.loads(ledger_path.read_text(encoding="utf-8")), dict)


def test_ledger_unparsable_timestamp_treated_expired(lane, capsys):
    _static, data_dir, _global_lock, _small_lock, _clock = lane
    _mk(data_dir, "nextday_plan.json", 246)
    ledger_path = ur._standalone_keys_path()
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps({"data/nextday_plan.json": "not-a-time"}), encoding="utf-8")
    assert ur._active_standalone_keys() == set(), "坏时间戳按过期处理(宁可多传不漏传)"
    assert "时间戳不可解析" in capsys.readouterr().err, "不得静默改变行为"


def test_record_prunes_expired_entries(lane):
    """写侧清理: 超 TTL 的旧条目在下次登记时移出台账(防只增不减)。"""
    _static, data_dir, _global_lock, _small_lock, clock = lane
    _mk(data_dir, "nextday_plan.json", 246)
    _mk(data_dir, "schedule_stats.json", 500)
    ur._record_standalone_keys(["data/nextday_plan.json", "data/schedule_stats.json"])
    clock["now"] = T0 + timedelta(days=20)
    ur._record_standalone_keys(["data/nextday_plan.json"])
    raw = json.loads(ur._standalone_keys_path().read_text(encoding="utf-8"))
    assert list(raw) == ["data/nextday_plan.json"], "过期条目应被清出台账(交回 all-data)"


# ══════════════════════ ⑧ verify-r2 侧语义不变(覆盖只增不减) ══════════════════════
def test_load_standalone_keys_ignores_expiry(lane):
    """_load_standalone_keys = 台账全部 key(不做过期过滤), verify-r2 对账覆盖面不缩水。"""
    _static, data_dir, _global_lock, _small_lock, clock = lane
    _mk(data_dir, "nextday_plan.json", 246)
    ur._record_standalone_keys(["data/nextday_plan.json"])
    clock["now"] = T0 + timedelta(days=30)
    keys, state = ur._load_standalone_keys(warn=False)
    assert state == ur._LEDGER_OK
    assert keys == {"data/nextday_plan.json"}, "过期键仍须被 verify-r2 覆盖(只能多查, 不能少查)"
    assert ur._active_standalone_keys() == set()


# ══════════════════════ ⑨ 审查建议 1: 旧 list 条目必须有时间基准, 不许永不过期 ══════════════════════
# 病因: 旧 list 迁移成 dict 时 ts=None, 而 _standalone_entry_active(None) 恒 True
#       ⇒ 旧条目(最可能陈旧的存量)永不过期, 与「过期防永久跳过」的意图相反。
# 修法: 迁移时用台账文件 mtime 作基准; 取不到 mtime ⇒ 立即过期(宁可多传一次)。
def test_legacy_list_entry_active_when_ledger_mtime_is_today(lane):
    """用例 A: 旧 list + 台账 mtime = 今天 + now = 今天 ⇒ 有效(不能一把全过期)。

    同时断言「时间基准真的落到了 mtime」——否则 ts=None(旧实现)也能让本条「有效」,
    用例就没有判别力(回滚修复时本条必须一起红)。
    """
    _static, _data_dir, _global_lock, _small_lock, _clock = lane
    _write_legacy_ledger(lane, ["data/nextday_plan.json"], mtime=T0)
    ledger, state, migrated = ur._load_standalone_ledger(warn=False)
    assert state == ur._LEDGER_OK and migrated is True
    assert ledger == {"data/nextday_plan.json": "2026-10-22 22:30:00"}, \
        "旧条目必须带 mtime 基准(不是 None)"
    assert ur._active_standalone_keys() == {"data/nextday_plan.json"}


def test_legacy_list_entry_expires_by_ledger_mtime(lane):
    """用例 B: 旧 list + 台账 mtime = 222 天前 ⇒ 过期(修前这里会误判有效)。"""
    _static, _data_dir, _global_lock, _small_lock, _clock = lane
    _write_legacy_ledger(lane, ["data/nextday_plan.json"], mtime=T0 - timedelta(days=222))
    assert ur._active_standalone_keys() == set(), "旧条目超 TTL 必须失效(交回 all-data)"


def test_legacy_list_entry_expired_when_mtime_unavailable(lane, monkeypatch, capsys):
    """用例 C: 旧 list + 台账 mtime 取不到 ⇒ 过期(不永真), 且显式打 stderr。"""
    _static, _data_dir, _global_lock, _small_lock, _clock = lane
    _write_legacy_ledger(lane, ["data/nextday_plan.json"], mtime=T0)
    monkeypatch.setattr(ur, "_ledger_file_mtime", lambda _p: None)
    assert ur._active_standalone_keys() == set(), "取不到时间基准 ⇒ 按过期处理, 不得永久有效"
    assert "无可用时间基准" in capsys.readouterr().err, "不得静默改变行为"


# ══════════════════════ ⑩ 审查建议 2: 超时诊断必须看两把锁(全局锁 + 小锁) ══════════════════════
def test_lock_paths_from_env_reads_both_envs(monkeypatch):
    """锁路径 env 与 upload_r2.py 同名同缺省(诊断不许另写一份路径默认值)。"""
    monkeypatch.setenv("R2_UPLOAD_LOCK", "/tmp/g.lock")
    monkeypatch.setenv("R2_UPLOAD_SMALL_LOCK", "/tmp/s.lock")
    assert probe.lock_paths_from_env() == [("全局锁", "/tmp/g.lock"), ("小锁", "/tmp/s.lock")]
    monkeypatch.delenv("R2_UPLOAD_LOCK")
    monkeypatch.delenv("R2_UPLOAD_SMALL_LOCK")
    assert probe.lock_paths_from_env() == [
        ("全局锁", "/tmp/trade_r2_upload.lock"), ("小锁", "/tmp/trade_r2_upload_small.lock")]


def test_probe_locks_locates_small_lock(monkeypatch):
    """小锁被占: 诊断必须点出小锁(修前只探全局锁 ⇒ 会报「全局锁无占用」指错方向)。"""
    monkeypatch.setenv("R2_UPLOAD_LOCK", "/tmp/g.lock")
    monkeypatch.setenv("R2_UPLOAD_SMALL_LOCK", "/tmp/s.lock")
    text = probe.probe_locks(probe.lock_paths_from_env(),
                             probe=lambda p: "pid=42(已运行 00:09) upload_r2.py" if p == "/tmp/s.lock" else "")
    assert "小锁(/tmp/s.lock)=pid=42" in text, text
    assert "全局锁(/tmp/g.lock)=无占用/探测不到" in text, text


def test_probe_locks_locates_global_lock(monkeypatch):
    """全局锁被占(大载荷/非 data-files 命令): 仍能定位到全局锁。"""
    monkeypatch.setenv("R2_UPLOAD_LOCK", "/tmp/g.lock")
    monkeypatch.setenv("R2_UPLOAD_SMALL_LOCK", "/tmp/s.lock")
    text = probe.probe_locks(probe.lock_paths_from_env(),
                             probe=lambda p: "pid=7(已运行 24:13) upload-data-large" if p == "/tmp/g.lock" else "")
    assert "全局锁(/tmp/g.lock)=pid=7" in text, text
    assert "小锁(/tmp/s.lock)=无占用/探测不到" in text, text


def test_probe_locks_never_raises(monkeypatch):
    """探测函数自身抛异常也不得把诊断链路弄挂(§ L50 同精神: 诊断只读且 fail-safe)。"""
    def _boom(_p):
        raise RuntimeError("lsof 炸了")

    text = probe.probe_locks([("全局锁", "/tmp/g.lock")], probe=_boom)
    assert text == "全局锁(/tmp/g.lock)=无占用/探测不到"


def test_lock_timeout_diag_with_two_locks_reports_small_lock(monkeypatch):
    """nextday 侧诊断文案: 构造「小通道等锁超时」, 文案必须出现小锁路径且标注其被占。"""
    monkeypatch.setenv("R2_UPLOAD_LOCK", "/tmp/g.lock")
    monkeypatch.setenv("R2_UPLOAD_SMALL_LOCK", "/tmp/s.lock")
    exc = subprocess.TimeoutExpired(cmd=["python3", "upload_r2.py"], timeout=480)
    exc.stderr = "⏳ 等待 R2 上传锁 120s(上限 7300s)\n".encode("utf-8")
    exc.stdout = b""
    log_text, _subject, body = probe.build_lock_timeout_diag(
        exc, lock_path="/tmp/g.lock", lock_paths=probe.lock_paths_from_env(),
        log_path="/tmp/x.log", date_tag="20261023",
        source="nextday_plan_generator.py", file_names=["nextday_plan.json"],
        probe=lambda p: "pid=42(已运行 00:09) upload_r2.py" if p == "/tmp/s.lock" else "")
    assert "/tmp/s.lock" in log_text and "小锁(/tmp/s.lock)=pid=42" in log_text, log_text
    assert "小锁(/tmp/s.lock)=pid=42" in body, body
    assert "上传前排队等锁超时(等了 120 秒" in body


# ══════════════════════ ⑪ 防漂移: 4 处调用方必须走统一探测(不许各写一份路由判定) ══════════════════════
_CALL_SITES = ["nextday_plan_generator.py", "fapi_bj_width_export.py",
               "gen_daily_brief.py", "nextday_gap_check.py"]


@pytest.mark.parametrize("name", _CALL_SITES)
def test_call_sites_probe_both_locks_not_single(name):
    """源码形状守卫: 4 处超时诊断必须用 probe_locks/lock_paths_from_env, 且不再只探全局锁。

    只探一把会在 A 方案后(小载荷走小锁)把超时指错方向; 统一入口 = 不会出现第二份路由判定。
    """
    src = (SCRIPTS / name).read_text(encoding="utf-8")
    assert "lock_paths_from_env" in src, f"{name} 未按统一入口取两把锁路径"
    assert ("probe_locks(" in src) or ("lock_paths=lock_paths_from_env()" in src), \
        f"{name} 未逐把探测(全局锁 + 小锁)"
    assert "_route_upload_lock" not in src, f"{name} 不得复制路由判定(第二实现必然漂移)"