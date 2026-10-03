#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R4 块 update_dedup 修复 pytest 版(2026-10-01 修复, 2026-10-03 由脚本式自测改造) — 生产隔离: 全部落临时目录, 不真发信。

原脚本式自测把 6 条验证点写在顶层直接执行 + 末行 sys.exit(), pytest 收集时顶层执行
import notify 崩溃(硬编码他人 worktree 绝对路径) → CI 门禁 ⑧ 全红。本文件改为真 pytest:
  1. 仓库根由 conftest 提供(SCRIPTS 已入 sys.path), 消除硬编码绝对路径;
  2. 6 条验证点逐条落成 test 函数(断言强度与原脚本逐条对等, 无删减无放宽);
  3. notify.send_tiered / notify.adr.r4_staticdata_grade 为模块级打桩, 用 autouse fixture
     前后 patch + restore, 防污染 test_alert_denoise_20261001.py 的同名真实函数测试。

验证点(与 docstring 顶部对应):
  1. 正例 all_ok  : 发送成功 -> dedup 更新(去重语义保留)
  2. 正例续跑     : 6h 窗口内同 key suppress(不引入告警轰炸)
  3. 反例 all_fail: 发送全失败 -> dedup 不更新(不静默吞真故障)
  4. 反例续跑     : 失败后下次调用不被 suppress, 必重试
  5. info 级      : 只记 dashboard 不推送 -> 不占窗(也不占 severe 窗)
  6. tg_only      : telegram 任一渠道成功 -> 照常占窗

跑法(pytest, CI ⑧同):
  python3 -m pytest -q scripts/tests/test_notify_r4_dedup_20261001.py
"""
import json
import tempfile
from pathlib import Path

import pytest

import notify

TMP = Path(tempfile.mkdtemp(prefix="r4-dedup-"))
notify.DEDUP_FILE = TMP / "notify_dedup.json"  # 生产隔离: dedup 落临时目录, 不碰生产 data/notify_dedup.json

OUTCOME = {"v": "all_ok", "tier": "severe"}  # 桩开关
CALLED = {"n": 0}
_calls = []  # 记录每次 send_tiered 的 tier/outcome, 便于断言


def fake_send_tiered(subject, body, tier=notify.TIER_CRITICAL, **kw):
    CALLED["n"] += 1
    _calls.append({"tier": tier, "outcome": OUTCOME["v"]})
    o = OUTCOME["v"]
    if tier == notify.TIER_INFO:
        return {"tier": "info", "email": False, "telegram": False,
                "feishu": False, "info_logged": True}
    if o == "all_ok":
        return {"tier": tier, "email": True, "telegram": False, "feishu": False}
    if o == "all_fail":
        return {"tier": tier, "email": False, "telegram": False, "feishu": False}
    if o == "tg_only":
        return {"tier": tier, "email": False, "telegram": True, "feishu": False}
    raise AssertionError(f"未知 OUTCOME={o}")


def dedup_state():
    if not notify.DEDUP_FILE.exists():
        return {}
    return json.loads(notify.DEDUP_FILE.read_text())


def clear_dedup():
    if notify.DEDUP_FILE.exists():
        notify.DEDUP_FILE.unlink()


def run_once(outcome, tier="severe"):
    """跑一次 notify main(R4 块路径, dedup-key=staticdata_backup_fail)。返回 send 调用次数。"""
    OUTCOME["v"] = outcome
    OUTCOME["tier"] = tier
    CALLED["n"] = 0
    _calls.clear()
    rc = notify.main(["[告警] staticdata备份失败", "body", "--severe",
                      "--dedup-key", "staticdata_backup_fail",
                      "--dedup-window", "3600"])
    assert rc == 0, f"main 返回 {rc}"
    return CALLED["n"]


@pytest.fixture(autouse=True)
def _isolate():
    """每个测试前后: 打桩 send_tiered / r4_staticdata_grade, 测完恢复(防跨文件污染)。"""
    _orig_send = notify.send_tiered
    _orig_grade = notify.adr.r4_staticdata_grade
    notify.send_tiered = fake_send_tiered
    notify.adr.r4_staticdata_grade = lambda hb, st, now: (OUTCOME["tier"], "test-reason")
    clear_dedup()
    yield
    notify.send_tiered = _orig_send
    notify.adr.r4_staticdata_grade = _orig_grade
    clear_dedup()


# ───────────────── 验证点逐条: 与原脚本 1..6 一一对应 ─────────────────
def test_1_all_ok_updates_dedup():
    """正例 all_ok: 发送成功 -> dedup 更新(去重语义保留)。"""
    clear_dedup()
    n1 = run_once("all_ok")
    st = dedup_state()
    assert n1 == 1, f"send={n1}(期望1)"
    assert "staticdata_backup_fail" in st, \
        f"dedup 应更新 key, 实得 st={st}"


def test_2_all_ok_rerun_suppressed():
    """正例续跑: 6h 窗口内同 key suppress(不引入告警轰炸)。"""
    clear_dedup()
    run_once("all_ok")          # 第1轮: 发送成功 -> dedup 更新占窗
    n2 = run_once("all_ok")     # 第2轮: 窗口内同 key -> suppress
    assert n2 == 0, f"send={n2}(期望0=suppress)"


def test_3_all_fail_no_dedup():
    """反例 all_fail: 发送全失败 -> dedup 不更新(不静默吞真故障)。"""
    clear_dedup()
    n3 = run_once("all_fail")
    st = dedup_state()
    assert n3 == 1, f"send={n3}(期望1=仍尝试发送)"
    assert "staticdata_backup_fail" not in st, \
        f"全渠道失败不得写 dedup, 实得 st={st}(防发送故障时被静默 suppress)"


def test_4_all_fail_rerun_retry():
    """反例续跑: 失败后下次调用不被 suppress, 必重试。"""
    clear_dedup()
    run_once("all_fail")        # 失败轮: dedup 未写
    n4 = run_once("all_ok")     # 下次调用必须重试(不被上次失败 suppress)
    st = dedup_state()
    assert n4 == 1, f"send={n4}(期望1=重试非suppress)"
    assert "staticdata_backup_fail" in st


def test_5_info_only_dashboard_no_window():
    """info 级: 只记 dashboard 不推送 -> 不占窗(也不占 severe 窗)。"""
    clear_dedup()
    n5 = run_once("all_ok", tier="info")
    st = dedup_state()
    assert n5 == 1, f"send={n5}(info记dashboard, 渠道全False)"
    assert "staticdata_backup_fail" not in st, \
        f"info 级不得占窗, 实得 st={st}"


def test_6_tg_only_occupies_window():
    """tg_only: telegram 任一渠道成功 -> 照常占窗。"""
    clear_dedup()
    n6 = run_once("tg_only")
    st = dedup_state()
    assert n6 == 1, f"send={n6}(telegram渠道成功)"
    assert "staticdata_backup_fail" in st, \
        f"任一渠道成功应占窗, 实得 st={st}"