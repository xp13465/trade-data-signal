#!/usr/bin/env python3
"""R4 块 update_dedup 修复自测(2026-10-01) — 生产隔离: 全部落 /tmp, 不真发信。

验证点:
  1. 正例 all_ok  : 发送成功 -> dedup 更新(去重语义保留)
  2. 正例续跑     : 6h 窗口内同 key suppress(不引入告警轰炸)
  3. 反例 all_fail: 发送全失败 -> dedup 不更新(不静默吞真故障)
  4. 反例续跑     : 失败后下次调用不被 suppress, 必重试
  5. info 级      : 只记 dashboard 不推送 -> 不占窗(也不占 severe 窗)
  6. tg_only      : telegram 任一渠道成功 -> 照常占窗
"""
import json
import sys
from pathlib import Path

WT = Path("/Users/linhuichen/code/trade/.claude/worktrees/agent-a45df7aac3ee7ea07")
sys.path.insert(0, str(WT / "scripts"))

import notify  # noqa: E402

TMP = Path("/tmp/agent123fix2")
TMP.mkdir(exist_ok=True)
notify.DEDUP_FILE = TMP / "notify_dedup.json"  # 生产隔离: dedup 落 /tmp

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


notify.send_tiered = fake_send_tiered
notify.adr.r4_staticdata_grade = lambda hb, st, now: (OUTCOME["tier"], "test-reason")


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


results = []
# 1. 正例 all_ok: 发送成功 -> dedup 更新
clear_dedup()
n1 = run_once("all_ok")
st = dedup_state()
results.append(("1.正例 all_ok -> dedup 更新", n1 == 1 and "staticdata_backup_fail" in st,
                f"send={n1} key={'staticdata_backup_fail' in st}"))

# 2. 正例续跑: 窗口内同 key suppress(不轰炸)
n2 = run_once("all_ok")
results.append(("2.正例续跑 -> 窗口内 suppress", n2 == 0,
                f"send={n2}(期望0=suppress)"))

# 3. 反例 all_fail: 发送全失败 -> dedup 不更新
clear_dedup()
n3 = run_once("all_fail")
st = dedup_state()
results.append(("3.反例 all_fail -> dedup 不更新", n3 == 1 and "staticdata_backup_fail" not in st,
                f"send={n3} key={'staticdata_backup_fail' in st}(期望无key)"))

# 4. 反例续跑: 失败后下次调用不被 suppress, 必重试
n4 = run_once("all_ok")
st = dedup_state()
results.append(("4.反例续跑 -> 失败后下次调用重试", n4 == 1 and "staticdata_backup_fail" in st,
                f"send={n4}(期望1=重试非suppress) key={'staticdata_backup_fail' in st}"))

# 5. info 级: 只记 dashboard 不推送 -> 不占窗
clear_dedup()
n5 = run_once("all_ok", tier="info")
st = dedup_state()
results.append(("5.info 级 -> 不占窗", n5 == 1 and "staticdata_backup_fail" not in st,
                f"send={n5}(info记dashboard) key={'staticdata_backup_fail' in st}(期望无key)"))

# 6. tg_only: telegram 任一渠道成功 -> 照常占窗
clear_dedup()
n6 = run_once("tg_only")
st = dedup_state()
results.append(("6.tg_only -> 任一渠道成功占窗", n6 == 1 and "staticdata_backup_fail" in st,
                f"send={n6} key={'staticdata_backup_fail' in st}"))

print("\n========== R4 dedup 修复自测结果 ==========")
all_pass = True
for name, ok, detail in results:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  |  {detail}")
    all_pass = all_pass and ok
print("===========================================")
print("总判定:", "ALL PASS" if all_pass else "HAS FAIL")
sys.exit(0 if all_pass else 1)
