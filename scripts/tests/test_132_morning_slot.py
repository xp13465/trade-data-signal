#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#132 残留① 凌晨槽时点漂移判定反例 pytest 版(2026-10-01 修复, 2026-10-03 改造)。

原脚本式自测顶层 for 循环 9 条 check + sys.exit。改为真 pytest: 9 条表驱动 CASE 用
@parametrize 逐条落成 test 用例(断言强度与原脚本逐条对等), 用例间用 monkeypatch 隔离 env。

打真实判定代码: import backfill_direct_metrics 的 _is_morning_slot(唯一判定实现, 无第二份
逻辑副本), 通过显式 `now` 参数注入时点做确定性断言(函数支持 now 参数正是为此; 生产调用
不传 now 走真实当前时间)。

覆盖(与原 docstring 对应): 唤醒漂移(BACKFILL_SLOT=0200/0300/0459 实际 03:00/03:30/04:59 →
仍凌晨槽), 窗口边界(05:00 → 非凌晨), 非凌晨兜底槽(1750/2100), 空 env(手动/update_all 保守
非凌晨), 以及「BACKFILL_SLOT 有值但实际时点已过窗口」场景。

跑法(pytest, CI ⑧同):
  python3 -m pytest -q scripts/tests/test_132_morning_slot.py
"""
import datetime as dt

import pytest

import backfill_direct_metrics as bdm  # noqa: E402  (conftest 已注入 scripts/ + REPO env + CI 第三方库 stub)

# 表驱动: (BACKFILL_SLOT env 值, 实际判定时点, 期望, 说明) —— 与原脚本 CASES 逐条一致
CASES = [
    ("0200", dt.datetime(2026, 10, 1, 2, 0), True, "02:00 整点正常启动=凌晨槽(基准语义)"),
    ("0200", dt.datetime(2026, 10, 1, 3, 30), True, "02:00 槽唤醒漂移到 03:30=仍凌晨槽(#132 核心修复)"),
    ("0300", dt.datetime(2026, 10, 1, 3, 0), True, "BACKFILL_SLOT=0300(唤醒漂移)实际 03:00=仍凌晨槽"),
    ("0459", dt.datetime(2026, 10, 1, 4, 59), True, "宽限窗口内 04:59=仍凌晨槽"),
    ("0500", dt.datetime(2026, 10, 1, 5, 0), False, "窗口边界 05:00=不再凌晨槽(该有数据而没有=真故障须报)"),
    ("1750", dt.datetime(2026, 10, 1, 17, 50), False, "16:35 兜底槽漂移到 17:50=非凌晨槽(六源全败=真故障)"),
    ("2100", dt.datetime(2026, 10, 1, 21, 0), False, "21:00 兜底槽=非凌晨槽"),
    ("0200", dt.datetime(2026, 10, 1, 17, 50), False, "env 残留 0200 但实际时点 17:50=非凌晨槽(按实际时点判)"),
    ("", dt.datetime(2026, 10, 1, 3, 0), False, "无 env(手动/update_all)=保守非凌晨槽(不放过)"),
]

case_ids = [f"slot{slot or 'empty'}@{now:%H%M}" for slot, now, _, _ in CASES]


@pytest.mark.parametrize("slot,now,expected,desc", CASES, ids=case_ids)
def test_morning_slot(monkeypatch, slot, now, expected, desc):
    """9 条表驱动用例: BACKFILL_SLOT + 注入时点 → _is_morning_slot 判定 == 期望。"""
    monkeypatch.setenv("BACKFILL_SLOT", slot)
    got = bdm._is_morning_slot(now)
    assert got == expected, f"morning_slot({slot or '空'}, {now:%H:%M}) 期望={expected} 实际={got} — {desc}"