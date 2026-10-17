# -*- coding: utf-8 -*-
"""#253-c1 自测: 周日白天(<23:00)大批量 full 延后夜间(2026-10-17)。

被测面 = `scripts/upload_r2.py::_incremental_upload` 的延后分支(+ 新增的 `_now()` 注入点)。
权威规格 = docs/ops/watchdog-tradesim-slowkill-20261011.md §5-c1 + 派单任务书 B 段;
实施报告 = /tmp/upload-j1c1-report.md。

零网络/零 R2 写: 全程 `dry_run=True`(引擎在 PUT 前 return) + STATIC_DIR 指到 tmp 树,
状态文件/落盘标记全在 tmp_path 下, 不触任何真实产物(§18 L48「自测零外发」同精神)。

§18 L51(时敏铁律)落地:
  - **跑时刻由 env R2_NOW_OVERRIDE 注入冻结**(不写死日期字面量进生产代码, 不替换标准库类);
  - 覆盖「隔天仍绿」⇔ 平移一天(周日→周一/周日 23:00→周日 14:00)重跑, 结论必须跟着变;
  - 判别力关: 关掉开关(通道集置空 / 阈值置 0)后断言必须翻转 ⇒ 证明断言真咬住新代码。

跑法: python3 -m pytest -q scripts/tests/test_253_c1_night_full_defer_20261017.py
"""
import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import upload_r2 as ur  # noqa: E402  (顶层 load_env 由 conftest §④ 垫片兜住)

# 冻结时刻(周日 = 2026-10-18; 周一 = 2026-10-19; 均为注入值, 非生产代码里的字面量)
SUN_DAYTIME = "2026-10-18T14:00:00"     # 周日白天
SUN_2359 = "2026-10-18T23:59:00"        # 周日 23:00 后
SUN_2300 = "2026-10-18T23:00:00"        # 边界: 恰好 23:00(不算白天)
SUN_2259 = "2026-10-18T22:59:00"        # 边界: 差 1 分钟
MON_DAYTIME = "2026-10-19T14:00:00"     # 平日(周一)

N_FILES = 10          # 本地文件数
N_UNCHANGED = 5       # 状态文件里指纹一致(未变)的文件数 ⇒ 增量集=5, full=10
STATE_NAME = ".r2_test_253c1_state.json"      # 测试私有名(不碰生产 .r2_*_state.json)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """自测零外发机检: 任何 HTTP(S) 连接尝试直接报错 ⇒ 证明本轮不触真实 R2(§18 L48 同精神)。"""
    import http.client

    def _boom(*_a, **_k):
        raise AssertionError("自测期禁止真实网络连接(零外发铁律): 有 PUT 尝试即测试失败")

    for cls in (http.client.HTTPConnection, http.client.HTTPSConnection):
        monkeypatch.setattr(cls, "connect", _boom, raising=False)


def _mk_tree(tmp_path, monkeypatch):
    """铺 tmp 本地树 + 状态文件, 把 STATIC_DIR 指过去(状态/标记路径随之落 tmp)。"""
    static = tmp_path / "static-site"
    local = static / "data" / "trade_sim"
    local.mkdir(parents=True)
    files = {}
    for i in range(N_FILES):
        p = local / f"trade_sim_{i}.json"
        p.write_text(json.dumps({"i": i}, ensure_ascii=False), encoding="utf-8")
        md5 = hashlib.md5(p.read_bytes()).hexdigest()
        # 前 N_UNCHANGED 个指纹与状态一致(未变); 其余写入错指纹 ⇒ 待传
        files[p.name] = {"size": p.stat().st_size,
                         "md5": md5 if i < N_UNCHANGED else "0" * 32}
    monkeypatch.setattr(ur, "STATIC_DIR", static)
    state_dir = tmp_path / "data"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / STATE_NAME).write_text(
        json.dumps({"version": 1, "updated_at": "x", "mode": "增量",
                    "count": len(files), "files": files, "changed": []}),
        encoding="utf-8")
    return local


def _run(local, *, label="trade-sim"):
    """dry_run=True 跑一次增量引擎, 返回 (返回三元组, stdout 全文)。"""
    ok, total, failed, keys = ur._incremental_upload(
        local, ["*.json"], "trade_sim_data", STATE_NAME, label=label, dry_run=True)
    return (ok, total), failed


def _out(capsys):
    return capsys.readouterr().out


def test_defer_log_landing_contract():
    """落地契约(静态): 延后分支/常量/注入点/依赖注释都在位, 且同函数不再直取 date.today()。"""
    src = ur.__file__ and Path(ur.__file__).read_text(encoding="utf-8")
    body = src.split("def _incremental_upload(", 1)[1].split("\ndef ", 1)[0]
    assert "_NIGHT_FULL_DEFER_HOUR" in body, "延后阈值未在引擎内使用"
    assert "延迟到 {_NIGHT_FULL_DEFER_HOUR}:00 后" in body, "延后日志缺「延迟到 23:00 后」要素"
    assert "now:%Y-%m-%d %H:%M" in body, "延后日志缺「时间」要素"
    assert "_now()" in body and "datetime.date.today().weekday()" not in body, \
        "引擎内仍直取系统日期 ⇒ 时敏用例无法注入冻结(§18 L51)"
    region = body.split("# #253-c1:", 1)[1].split('print(f"[{label}] 模式=', 1)[0]
    assert not re.search(r"\d{4}-\d{2}-\d{2}", region), \
        "延后判定区出现写死的日期字面量(§18 L51 禁止; 时刻必须来自 _now() 注入点)"
    # §22 登记点一致性: 延后通道集的每个 label 必须真存在于 upload_r2.py 的 label="..." 调用点上
    # (防拼写漂移 ⇒ 开关静默失效: 集合里写错一个名字, 该通道永远不会被延后且无任何报错)
    declared = set(re.findall(r'label="([^"]+)"', src))
    assert ur._NIGHT_FULL_DEFER_CHANNELS <= declared, \
        f"延后通道集含未登记的 label: {sorted(ur._NIGHT_FULL_DEFER_CHANNELS - declared)}"
    assert "verify-r2" in src.split("_NIGHT_FULL_DEFER_CHANNELS", 1)[0][-800:], \
        "延后开关旁必须写明「verify-r2 周日全量对账独立 ⇒ 漂移防护不丢」的依赖结论"


def test_sunday_daytime_defers_to_night(tmp_path, monkeypatch, capsys):
    """① 周日白天 + trade-sim + 有状态 ⇒ 跳过 full, 走平日增量 + 落延后日志。"""
    local = _mk_tree(tmp_path, monkeypatch)
    monkeypatch.setenv("R2_NOW_OVERRIDE", SUN_DAYTIME)
    (ok, total), _ = _run(local)
    out = _out(capsys)
    assert (ok, total) == (N_UNCHANGED, N_UNCHANGED), f"应只传增量集 {N_UNCHANGED}, 实得 {(ok, total)}"
    assert "⏸ 周日白天(<23:00)大批量 full 延后夜间" in out
    assert "2026-10-18 14:00" in out and "trade-sim" in out and "延迟到 23:00 后" in out
    assert "模式=增量(周日 full 延后到 23:00 后)" in out
    assert "周日强制全量" not in out.split("模式=")[-1], "延后轮不应以「周日强制全量」模式收尾"


def test_sunday_after_23h_keeps_full(tmp_path, monkeypatch, capsys):
    """② 周日 23:00 后 ⇒ 不跳过, 仍全量。"""
    local = _mk_tree(tmp_path, monkeypatch)
    monkeypatch.setenv("R2_NOW_OVERRIDE", SUN_2359)
    (ok, total), _ = _run(local)
    out = _out(capsys)
    assert (ok, total) == (N_FILES, N_FILES), "23:00 后应恢复全量"
    assert "模式=周日强制全量" in out
    assert "延后夜间" not in out


def test_sunday_boundary_2300_and_2259(tmp_path, monkeypatch, capsys):
    """边界: 22:59 延后 / 23:00 不延后(口径 = 当前时刻 < 23:00)。"""
    local = _mk_tree(tmp_path, monkeypatch)
    monkeypatch.setenv("R2_NOW_OVERRIDE", SUN_2259)
    (ok_a, _), _ = _run(local)
    out_a = _out(capsys)
    monkeypatch.setenv("R2_NOW_OVERRIDE", SUN_2300)
    (ok_b, _), _ = _run(local)
    out_b = _out(capsys)
    assert (ok_a, ok_b) == (N_UNCHANGED, N_FILES), f"22:59 应延后/23:00 应全量, 实得 {ok_a}/{ok_b}"
    assert "延后夜间" in out_a and "延后夜间" not in out_b


def test_weekday_behavior_unchanged(tmp_path, monkeypatch, capsys):
    """③ 平日(周一) ⇒ 完全不变: 走增量, 无延后日志(隔天平移验证)。"""
    local = _mk_tree(tmp_path, monkeypatch)
    monkeypatch.setenv("R2_NOW_OVERRIDE", MON_DAYTIME)
    (ok, total), _ = _run(local)
    out = _out(capsys)
    assert (ok, total) == (N_UNCHANGED, N_UNCHANGED)
    assert "模式=增量 本次待传" in out, "平日应保持「模式=增量」原样"
    assert "延后夜间" not in out


def test_other_channels_unchanged_on_sunday(tmp_path, monkeypatch, capsys):
    """④ 非这三通道(如 lab) 周日白天 ⇒ 不延后, 仍全量。"""
    local = _mk_tree(tmp_path, monkeypatch)
    monkeypatch.setenv("R2_NOW_OVERRIDE", SUN_DAYTIME)
    for label in ("lab", "etf-hist", "industry", "trade-sim-json-x"):
        (ok, total), _ = _run(local, label=label)
        out = _out(capsys)
        assert (ok, total) == (N_FILES, N_FILES), f"{label} 不该被延后(实得 {ok}/{total})"
        assert "延后夜间" not in out


def test_each_deferred_channel_declared(tmp_path, monkeypatch, capsys):
    """三个点名通道(trade-sim / trade-sim-json / index) 周日白天都延后。"""
    local = _mk_tree(tmp_path, monkeypatch)
    monkeypatch.setenv("R2_NOW_OVERRIDE", SUN_DAYTIME)
    assert ur._NIGHT_FULL_DEFER_CHANNELS == {"trade-sim", "trade-sim-json", "index"}
    for label in sorted(ur._NIGHT_FULL_DEFER_CHANNELS):
        (ok, _), _ = _run(local, label=label)
        out = _out(capsys)
        assert ok == N_UNCHANGED and "延后夜间" in out, f"{label} 未延后"


def test_marker_stale_also_deferred(tmp_path, monkeypatch, capsys):
    """「marker 残留强制全量」这一 full 来源同样延后(任务书口径: 无论周日强制还是 marker 残留)。"""
    local = _mk_tree(tmp_path, monkeypatch)
    (tmp_path / "data" / STATE_NAME.replace("_state.json", "_uploading.marker")).write_text(
        "residual", encoding="utf-8")
    monkeypatch.setenv("R2_NOW_OVERRIDE", SUN_DAYTIME)
    (ok, _), _ = _run(local)
    out = _out(capsys)
    assert ok == N_UNCHANGED, "marker 残留的 full 也应在周日白天被延后"
    assert "检测到上次上传未正常结束" in out and "延后夜间" in out
    assert "full 原因为「上次上传中断强制全量」" in out


def test_first_run_full_not_deferred(tmp_path, monkeypatch, capsys):
    """诚实边界: 首次/无状态全量(old_files 空)**不**延后 —— 保持 export-guard L3 原路。"""
    local = _mk_tree(tmp_path, monkeypatch)
    (tmp_path / "data" / STATE_NAME).unlink()          # 无状态 ⇒ 首次全量
    monkeypatch.setenv("R2_NOW_OVERRIDE", SUN_DAYTIME)
    (ok, _), _ = _run(local)
    out = _out(capsys)
    assert ok == N_FILES, "首次/无状态全量不延后(仍全量, 由 export-guard L3 拦截)"
    assert "模式=首次/无状态全量" in out
    assert "延后夜间" not in out


def test_discriminating_power(tmp_path, monkeypatch, capsys):
    """判别力关: 关掉开关(通道集置空 / 阈值置 0)后, 原断言必须翻转 ⇒ 断言真咬住新代码。"""
    local = _mk_tree(tmp_path, monkeypatch)
    monkeypatch.setenv("R2_NOW_OVERRIDE", SUN_DAYTIME)
    monkeypatch.setattr(ur, "_NIGHT_FULL_DEFER_CHANNELS", frozenset())
    (ok_a, _), _ = _run(local)
    out_a = _out(capsys)
    monkeypatch.setattr(ur, "_NIGHT_FULL_DEFER_CHANNELS", frozenset({"trade-sim"}))
    monkeypatch.setattr(ur, "_NIGHT_FULL_DEFER_HOUR", 0)
    (ok_b, _), _ = _run(local)
    out_b = _out(capsys)
    assert (ok_a, ok_b) == (N_FILES, N_FILES), "开关关掉后必须回到 full"
    assert "延后夜间" not in out_a and "延后夜间" not in out_b


def test_now_injection_and_default(tmp_path, monkeypatch):
    """注入点自身: env 冻结值被解析; 未设 env 时回退真实时间(带时区, 不崩)。"""
    monkeypatch.setenv("R2_NOW_OVERRIDE", "2026-10-18T14:00:00")
    assert ur._now().weekday() == 6 and ur._now().hour == 14
    monkeypatch.setenv("R2_NOW_OVERRIDE", "不是时间")     # 非法值 ⇒ 回退系统时间, 不抛
    assert ur._now().year >= 2026
    monkeypatch.delenv("R2_NOW_OVERRIDE", raising=False)
    now = ur._now()
    assert now.year >= 2026 and 0 <= now.hour <= 23


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))