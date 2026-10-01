#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#132 残留① 凌晨槽时点漂移判定反例实测(2026-10-01)。

打真实判定代码: 直接 import backfill_direct_metrics._is_morning_slot(唯一判定实现,
无第二份逻辑副本), 通过显式 `now` 参数注入时点做确定性断言(函数支持 now 参数正是
为此; 生产调用不传 now 走真实当前时间)。

覆盖: 唤醒漂移(BACKFILL_SLOT=0200/0300/0459 实际 03:00/03:30/04:59 → 仍凌晨槽),
窗口边界(05:00 → 非凌晨), 非凌晨兜底槽(1750/2100), 空 env(手动/update_all 保守
非凌晨), 以及「BACKFILL_SLOT 有值但实际时点已过窗口」场景。

跑法(worktree 内, 用 trade-data venv):
  /Users/linhuichen/code/trade-data/.venv/bin/python scripts/tests/test_132_morning_slot.py
"""
import datetime as dt
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import backfill_direct_metrics as bdm  # noqa: E402

FAIL = []


def check(name, cond, detail):
    tag = "PASS" if cond else "FAIL"
    if not cond:
        FAIL.append(name)
    print(f"[{tag}] {name} — {detail}")


# 表驱动: (BACKFILL_SLOT env 值, 实际判定时点, 期望, 说明)
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

for slot, now, expected, desc in CASES:
    os.environ["BACKFILL_SLOT"] = slot
    got = bdm._is_morning_slot(now)
    check(f"morning_slot({slot or '空'}, {now:%H:%M})", got == expected,
          f"期望={expected} 实际={got} — {desc}")

if FAIL:
    print(f"\nFAIL {len(FAIL)} 项: {FAIL}")
    sys.exit(1)
print(f"\n全部 PASS({len(CASES)} 项)")
