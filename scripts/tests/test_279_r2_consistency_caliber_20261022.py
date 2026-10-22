#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#279 R2 一致性巡检口径修复（方案 A）真代码断言 —— pytest 版（2026-10-22）

用户拍板口径（docs/pending-features-index.md #279 + docs/ops/failed-units-rca-20261022.md）:
  判定层 = 三站（R2 直链 / CF r2-proxy / 主站同源）两两互比，任一不一致或某站不可读 ⇒ FAIL；
  提示层 = local 源树 vs 三站差异 ⇒ 只打 [INFO]，不计入 rc、不发告警（旧口径当第 4 源直接比
  ⇒ 部署闸门跳过 rsync 时误报 severe 连续 2 天）。

被验对象（真实生产函数/脚本，不做逻辑模拟）:
  - scripts/check_r2_consistency.py: check_file / main（网络层 _fetch_json 打桩）
  - scripts/check_r2_consistency.sh: 退出码语义 + notify 通道（PY 桩，零外发）

跑法: python3 -m pytest -q scripts/tests/test_279_r2_consistency_caliber_20261022.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import check_r2_consistency as crc  # conftest 已注入 scripts/

REPO_ROOT = Path(__file__).absolute().parent.parent.parent
WRAPPER = REPO_ROOT / "scripts" / "check_r2_consistency.sh"

OVERVIEW_REMOTES = [
    ("R2", "https://ssd.fx8.store/data/overview.json"),
    ("CF", "https://ss.fx8.store/r2/data/overview.json"),
    ("MAIN", "https://ss.fx8.store/data/overview.json"),
]


def _overview(date, score):
    """最小 overview 指纹载体（date + 首条信号 etf/track_score）。"""
    return {"date": date, "signals_today": [{"etfs": [{"code": "159739", "track_score": score}]}]}


def _concepts(score):
    return {"concepts": {"300816": {"etfs": [{"code": "159258", "track_score": score}]}}}


def _patch_fetch(monkeypatch, mapping):
    """按 URL 返回 (data, err)；mapping 缺省命中第一个值。"""
    def _fake(url):
        for key, val in mapping.items():
            if key in url:
                return val
        return next(iter(mapping.values()))
    monkeypatch.setattr(crc, "_fetch_json", _fake)


def _patch_local(monkeypatch, tmp_path, payload):
    p = tmp_path / "local.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(crc, "_local_candidates", lambda kind, rel: [p])
    return p


def _run_main(monkeypatch, capsys, files=None):
    if files is not None:
        monkeypatch.setattr(crc, "FILES", files)
    monkeypatch.setattr(sys, "argv", ["check_r2_consistency.py", "--quiet"])
    rc = crc.main()
    return rc, capsys.readouterr().out


# ============================================================
# 证据用例 1: 三站一致 + local 差异 ⇒ PASS(exit 0), INFO 且不含 FAIL/✗
# ============================================================
def test_case1_local_only_diff_is_pass_with_info(monkeypatch, tmp_path, capsys):
    _patch_fetch(monkeypatch, {"ssd.fx8.store": (_overview("20261021", 87.4), None),
                               "ss.fx8.store": (_overview("20261021", 87.4), None)})
    _patch_local(monkeypatch, tmp_path, _overview("20261019", 87.0))
    rc, out = _run_main(monkeypatch, capsys, files=[("overview", "overview.json", OVERVIEW_REMOTES)])
    assert rc == 0, f"local-only 差异必须 PASS,实际 rc={rc}\n{out}"
    assert "[INFO] [overview] local 落后于三站" in out, out
    assert "local方向=落后" in out, out
    assert "三站不一致" not in out and "✗" not in out, out
    assert "[SUMMARY]" in out and "结果=PASS" in out, out


# ============================================================
# 证据用例 2: 三站任两站不一致 ⇒ FAIL(非零),消息点明站名+文件+期望/实际
# ============================================================
def test_case2_station_mismatch_fails_with_station_names(monkeypatch, tmp_path, capsys):
    def _fake(url):
        if "ss.fx8.store/r2/" in url:          # CF 站旧版
            return _overview("20261020", 87.0), None
        return _overview("20261021", 87.4), None
    monkeypatch.setattr(crc, "_fetch_json", _fake)
    _patch_local(monkeypatch, tmp_path, _overview("20261021", 87.4))
    rc, out = _run_main(monkeypatch, capsys, files=[("overview", "overview.json", OVERVIEW_REMOTES)])
    assert rc == 1, out
    assert "[overview] 三站不一致 R2≠CF" in out, out
    assert "20261021" in out and "20261020" in out, out
    assert "结果=FAIL" in out, out


def test_case2b_main_station_mismatch_also_fails(monkeypatch, tmp_path, capsys):
    """R2 vs MAIN 也必须判（不只 R2 vs CF）。"""
    def _fake(url):
        if url.endswith("ss.fx8.store/data/overview.json") and "r2/" not in url:
            return _overview("20261019", 80.0), None
        return _overview("20261021", 87.4), None
    monkeypatch.setattr(crc, "_fetch_json", _fake)
    _patch_local(monkeypatch, tmp_path, _overview("20261021", 87.4))
    rc, out = _run_main(monkeypatch, capsys, files=[("overview", "overview.json", OVERVIEW_REMOTES)])
    assert rc == 1, out
    assert "三站不一致 R2≠MAIN" in out, out


def test_case2c_station_key_presence_asymmetry_fails(monkeypatch, tmp_path, capsys):
    """红线强化: 某站多/少一个指纹键(键集不对称=版本错位)也算三站不一致, 不得放过。"""
    r2_data = _overview("20261021", 87.4)
    r2_data["signals_today"].append({"etfs": [{"code": "512480", "track_score": 30.3}]})
    def _fake(url):
        return (r2_data if "ssd.fx8.store" in url else _overview("20261021", 87.4)), None
    monkeypatch.setattr(crc, "_fetch_json", _fake)
    _patch_local(monkeypatch, tmp_path, _overview("20261021", 87.4))
    rc, out = _run_main(monkeypatch, capsys, files=[("overview", "overview.json", OVERVIEW_REMOTES)])
    assert rc == 1, out
    assert "三站不一致 R2≠CF" in out and "sig_512480" in out, out


# ============================================================
# 证据用例 3: 三站一致但某站 404/读取失败 ⇒ FAIL（区分「不一致」与「不可读」）
# ============================================================
def test_case3_station_fetch_error_fails(monkeypatch, tmp_path, capsys):
    def _fake(url):
        if url.endswith("ss.fx8.store/data/overview.json") and "r2/" not in url:
            return None, "HTTPError: HTTP Error 404: Not Found"
        return _overview("20261021", 87.4), None
    monkeypatch.setattr(crc, "_fetch_json", _fake)
    _patch_local(monkeypatch, tmp_path, _overview("20261021", 87.4))
    rc, out = _run_main(monkeypatch, capsys, files=[("overview", "overview.json", OVERVIEW_REMOTES)])
    assert rc == 1, out
    assert "[overview] MAIN 拉取失败" in out, out
    assert "404" in out, out


def test_case3b_station_null_payload_fails(monkeypatch, tmp_path, capsys):
    """某站返回合法 JSON 但内容为 null（空文件）⇒ 不可读 ⇒ FAIL,不当「一致」放过。"""
    def _fake(url):
        if "ssd.fx8.store" in url:
            return None, None
        return _overview("20261021", 87.4), None
    monkeypatch.setattr(crc, "_fetch_json", _fake)
    _patch_local(monkeypatch, tmp_path, _overview("20261021", 87.4))
    rc, out = _run_main(monkeypatch, capsys, files=[("overview", "overview.json", OVERVIEW_REMOTES)])
    assert rc == 1, out
    assert "R2 读取失败: 内容为空" in out, out


# ============================================================
# 证据用例 4: 回放 10-21 23:20 真实差异 ⇒ 新逻辑判「local-only, INFO」, 不 FAIL
#            （数据取自 docs/ops/failed-units-rca-20261022.md 第 5 节原文）
# ============================================================
def test_case4_replay_1021_2320_diffs_are_info_only(monkeypatch, tmp_path, capsys):
    # overview: 三站 date=20261021 / sig_159739=87.4, local=20261019 / 87.0
    _patch_fetch(monkeypatch, {"ssd.fx8.store": (_overview("20261021", 87.4), None),
                               "ss.fx8.store": (_overview("20261021", 87.4), None)})
    _patch_local(monkeypatch, tmp_path, _overview("20261019", 87.0))
    probs, warns, infos, state = crc.check_file("overview", "overview.json", OVERVIEW_REMOTES, quiet=True)
    out = capsys.readouterr().out
    assert probs == [], probs
    assert warns == [], warns
    assert len(infos) == 1 and "local 落后于三站" in infos[0], infos
    assert "date" in out and "20261019" in out and "87.0" in out, out

    # concepts: 三站 thsc_300816_159258=36.6, local=35.7
    def _fake(url):
        if "ssd.fx8.store" in url or "/r2/" in url:
            return _concepts(36.6), None
        return _concepts(36.6), None
    monkeypatch.setattr(crc, "_fetch_json", _fake)
    _patch_local(monkeypatch, tmp_path, _concepts(35.7))
    probs, warns, infos, state = crc.check_file(
        "concepts", "industry-all-concepts.json",
        [("R2", "https://ssd.fx8.store/industry/industry-all-concepts.json"),
         ("CF", "https://ss.fx8.store/r2/industry/industry-all-concepts.json")], quiet=True)
    out = capsys.readouterr().out
    assert probs == [], probs
    assert any("local 与三站不一致" in i and "方向不明" in i and "300816_159258" in i
               for i in infos), infos


# ============================================================
# 证据用例 5: 零外发（通知调用打桩, 先证沙箱生效）
# ============================================================
def test_case5_info_path_never_calls_notify(tmp_path):
    """真实包装器 + 桩 PY: check 返回 0(local-only PASS) ⇒ 绝不调用 notify.py。
    「先证沙箱生效」= 桩 PY 记录每次被调用, 断言 check 调用确实走了桩。"""
    calls = tmp_path / "calls.log"
    stub = tmp_path / "stub_py.sh"
    stub.write_text(
        "#!/bin/sh\n"
        'echo "$*" >> "$CALLS"\n'
        'printf "[INFO] [overview] local 落后于三站(部署可能未完成/被跳过): date 三站=20261021 vs local=20261019\\n"\n'
        'printf "[SUMMARY] 文件=9 三站一致=9/9 local差异=1 local方向=落后 结果=PASS\\n"\n'
        "exit 0\n",
        encoding="utf-8")
    stub.chmod(0o755)
    env = dict(os.environ)
    env["REPO"] = str(tmp_path)
    env["PY"] = str(stub)
    env["CALLS"] = str(calls)
    env["R2_CONSISTENCY_PREFLIGHT_STUB"] = "inactive"
    p = subprocess.run(["bash", str(WRAPPER)], env=env, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr
    logged = calls.read_text(encoding="utf-8")
    assert "check_r2_consistency.py" in logged, f"桩 PY 未被调用(沙箱未生效): {logged!r}"
    assert "notify.py" not in logged, f"INFO 路径出现 notify 调用(零外发被破坏): {logged!r}"
    log = (tmp_path / "data" / "logs" / "r2_consistency_launchd.log").read_text(encoding="utf-8")
    assert "[INFO]" in log and "[SUMMARY]" in log
    assert "退出码=0" in log


def test_case5b_checker_source_has_no_notify_channel():
    """check_r2_consistency.py 自身不 import/调用 notify（告警只在包装器 rc!=0 时走）。"""
    src = Path(crc.__file__).read_text(encoding="utf-8")
    assert "notify" not in src, "审计器源码出现 notify 引用: 零外发前提被破坏"


def test_case5c_fail_path_still_alerts_once(tmp_path):
    """正控: 真 FAIL(桩 rc=1) ⇒ 包装器仍走原 severe 通道 1 次（降噪不吞真故障）。"""
    calls = tmp_path / "calls.log"
    stub = tmp_path / "fail_py.sh"
    stub.write_text(
        "#!/bin/sh\n"
        'echo "$*" >> "$CALLS"\n'
        'case "$1" in scripts/notify.py) exit 0 ;; esac\n'
        'printf "=== 1 项问题 ===\\n  ✗ [overview] 三站不一致 R2≠CF\\n"\n'
        "exit 1\n",
        encoding="utf-8")
    stub.chmod(0o755)
    env = dict(os.environ)
    env["REPO"] = str(tmp_path)
    env["PY"] = str(stub)
    env["CALLS"] = str(calls)
    env["R2_CONSISTENCY_PREFLIGHT_STUB"] = "inactive"
    p = subprocess.run(["bash", str(WRAPPER)], env=env, capture_output=True, text=True, timeout=120)
    assert p.returncode == 1, p.stderr
    logged = calls.read_text(encoding="utf-8")
    assert logged.count("notify.py") == 1, f"真 FAIL 应恰好 1 次告警: {logged!r}"
    assert "--severe" in logged and "r2_consistency_fail" in logged
    assert "[告警] §22 三站一致性校验失败" in logged
    log = (tmp_path / "data" / "logs" / "r2_consistency_launchd.log").read_text(encoding="utf-8")
    assert "退出码=1" in log


def test_case4b_local_structure_anomaly_is_info(tmp_path, monkeypatch, capsys):
    """边界: local 可读但指纹为空(空壳 {}) ⇒ 不能静默当「local 同步」, 打 INFO 不 FAIL。"""
    _patch_fetch(monkeypatch, {"ssd.fx8.store": (_overview("20261021", 87.4), None),
                               "ss.fx8.store": (_overview("20261021", 87.4), None)})
    _patch_local(monkeypatch, tmp_path, {})
    probs, warns, infos, state = crc.check_file("overview", "overview.json", OVERVIEW_REMOTES, quiet=True)
    assert probs == [], probs
    assert any("local 结构异常" in i for i in infos), infos


def test_case4c_local_unreadable_is_info(monkeypatch, tmp_path, capsys):
    """边界: local 文件缺失(部署未 rsync) ⇒ 只提示, 不 FAIL(三站本身一致)。"""
    _patch_fetch(monkeypatch, {"ssd.fx8.store": (_overview("20261021", 87.4), None),
                               "ss.fx8.store": (_overview("20261021", 87.4), None)})
    monkeypatch.setattr(crc, "_local_candidates", lambda kind, rel: [tmp_path / "nope.json"])
    probs, warns, infos, state = crc.check_file("overview", "overview.json", OVERVIEW_REMOTES, quiet=True)
    assert probs == [], probs
    assert any("local 读取失败" in i for i in infos), infos


def test_case4d_overfit_primary_lag_warns_not_fails(monkeypatch, tmp_path, capsys):
    """回归: overfit 双树 primary 滞后、次候选与三站一致 ⇒ WARN(不阻断)且不误报 INFO。"""
    good_data = {"generated_at": "2026-10-21T21:40:00",
                 "overfit": {"current": {"date": "20261021", "risk_score": 1.0}}}
    lag_data = {"generated_at": "2026-10-20T21:40:00",
                "overfit": {"current": {"date": "20261020", "risk_score": 1.0}}}
    lag = tmp_path / "primary.json"
    lag.write_text(json.dumps(lag_data), encoding="utf-8")
    good = tmp_path / "secondary.json"
    good.write_text(json.dumps(good_data), encoding="utf-8")
    monkeypatch.setattr(crc, "_fetch_json", lambda url: (good_data, None))
    monkeypatch.setattr(crc, "_local_candidates", lambda kind, rel: [lag, good])
    probs, warns, infos, state = crc.check_file(
        "overfit_monitor", "overfit_monitor.json", OVERVIEW_REMOTES, quiet=True)
    assert probs == [], probs
    assert warns and "primary" in warns[0], warns
    assert infos == [], infos


# ============================================================
# 证据用例 7: 调用方/定时器语义 —— 退出码只在真三站故障时非零
# ============================================================
def test_case7_exit_code_contract_and_summary_always_printed(monkeypatch, tmp_path, capsys):
    """local-only ⇒ rc=0;真站不一致 ⇒ rc=1。--quiet 下摘要仍输出（日志可追溯）。"""
    _patch_fetch(monkeypatch, {"ssd.fx8.store": (_overview("20261021", 87.4), None),
                               "ss.fx8.store": (_overview("20261021", 87.4), None)})
    _patch_local(monkeypatch, tmp_path, _overview("20261019", 87.0))
    rc, out = _run_main(monkeypatch, capsys, files=[("overview", "overview.json", OVERVIEW_REMOTES)])
    assert rc == 0
    assert out.count("[SUMMARY]") == 1, out
    assert "三站一致=1/1" in out and "local差异=1" in out, out
    assert "local方向=落后" in out, out# ============================================================
# 证据用例 8（#279 nits 改 1）: local 方向区分 —— 领先 = WARN、落后 = INFO、两者 rc 均 0
# ============================================================
def _board(score):
    """board_etf_map 最小指纹载体（只有 code→track_score，无时点字段 ⇒ 方向不可判定）。"""
    return {"sh": [{"code": "510300", "track_score": score}]}


def test_case8_local_lead_warns_not_fail(monkeypatch, tmp_path, capsys):
    """local 领先三站（上传漏传/传旧）⇒ [WARN] 明确提示, 但 rc=0 不告警。"""
    _patch_fetch(monkeypatch, {"ssd.fx8.store": (_overview("20261021", 87.4), None),
                               "ss.fx8.store": (_overview("20261021", 87.4), None)})
    _patch_local(monkeypatch, tmp_path, _overview("20261022", 88.0))
    probs, warns, infos, state = crc.check_file(
        "overview", "overview.json", OVERVIEW_REMOTES, quiet=True)
    out = capsys.readouterr().out
    assert probs == [], probs
    assert len(warns) == 1 and warns[0].startswith("[WARN] [overview] local 领先三站"), warns
    assert "疑似上传漏传/滞后" in warns[0], warns
    assert infos == [], infos
    assert state == "领先", state

    rc, out = _run_main(monkeypatch, capsys, files=[("overview", "overview.json", OVERVIEW_REMOTES)])
    assert rc == 0, f"local 领先不得计入 rc, 实际 rc={rc}\n{out}"
    assert "[WARN] [overview] local 领先三站(疑似上传漏传/滞后)" in out, out
    assert "local 落后于三站" not in out, out
    assert "local方向=领先" in out and "结果=PASS" in out, out
    assert "✗" not in out, out


def test_case8b_local_lag_info_only_no_warn(monkeypatch, tmp_path, capsys):
    """local 落后三站（部署未完成/被跳过）⇒ 只有 [INFO], 不得出现 WARN, rc=0。"""
    _patch_fetch(monkeypatch, {"ssd.fx8.store": (_overview("20261021", 87.4), None),
                               "ss.fx8.store": (_overview("20261021", 87.4), None)})
    _patch_local(monkeypatch, tmp_path, _overview("20261019", 87.0))
    probs, warns, infos, state = crc.check_file(
        "overview", "overview.json", OVERVIEW_REMOTES, quiet=True)
    assert probs == [] and warns == [], (probs, warns)
    assert len(infos) == 1 and "local 落后于三站" in infos[0], infos
    assert state == "落后", state

    rc, out = _run_main(monkeypatch, capsys, files=[("overview", "overview.json", OVERVIEW_REMOTES)])
    assert rc == 0, out
    assert "[INFO] [overview] local 落后于三站(部署可能未完成/被跳过)" in out, out
    assert "[WARN]" not in out, out
    assert "local方向=落后" in out, out


def test_case8c_direction_unknown_reported_honestly(monkeypatch, tmp_path, capsys):
    """无可比时点字段(board_etf_map)⇒ 报「方向不明」, 不硬扣「落后」帽子, rc=0。"""
    _patch_fetch(monkeypatch, {"ssd.fx8.store": (_board(36.6), None),
                               "ss.fx8.store": (_board(36.6), None)})
    _patch_local(monkeypatch, tmp_path, _board(30.0))
    probs, warns, infos, state = crc.check_file(
        "board_etf_map", "board_etf_map.json", OVERVIEW_REMOTES, quiet=True)
    assert probs == [] and warns == [], (probs, warns)
    assert any("方向不明" in i for i in infos), infos
    assert not any("落后于三站" in i for i in infos), infos
    assert state == "不明", state

    rc, out = _run_main(monkeypatch, capsys, files=[
        ("board_etf_map", "board_etf_map.json", OVERVIEW_REMOTES)])
    assert rc == 0, out
    assert "local 与三站不一致(方向不明" in out, out
    assert "local方向=不明" in out, out


def test_case8d_local_in_sync_reports_consistent(monkeypatch, tmp_path, capsys):
    """正控: local 与三站一致 ⇒ SUMMARY local方向=一致。"""
    _patch_fetch(monkeypatch, {"ssd.fx8.store": (_overview("20261021", 87.4), None),
                               "ss.fx8.store": (_overview("20261021", 87.4), None)})
    _patch_local(monkeypatch, tmp_path, _overview("20261021", 87.4))
    rc, out = _run_main(monkeypatch, capsys, files=[("overview", "overview.json", OVERVIEW_REMOTES)])
    assert rc == 0, out
    assert "local方向=一致" in out and "local差异=0" in out, out