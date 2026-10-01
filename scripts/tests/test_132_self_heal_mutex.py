#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#132 残留② self_heal 并发双通知修复反例实测(2026-10-01)。

self_heal.sh 调 retry_failed_metrics 已改经 with_lock.py --nb 进程互斥(#132)。
本测试用与生产完全相同的 with_lock.py(仓内既有唯一实现) + 同一锁语义模拟两个并发
self_heal 轮次, 证明: 并发时只有一个实例进入 retry(读计数+发通知), 另一个被 --nb
跳过 → 不可能出现"双双读到 n=2 双双跨阈值发两次通知"。

模拟的 retry 体=「写计数 + 发通知」两动作(即并发双通知的最小造影), 统计 runs/notifies。

跑法(worktree 内, 用 trade-data venv):
  /Users/linhuichen/code/trade-data/.venv/bin/python scripts/tests/test_132_self_heal_mutex.py
"""
import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

# 测试文件在 scripts/tests/ 下, 上溯三级到仓库根
REPO_ROOT = Path(__file__).absolute().parent.parent.parent
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
PY = str(Path(sys.executable))
VERSHO = "/Users/linhuichen/code/trade-data/.venv/bin/python"

FAIL = []


def check(name, cond, detail):
    tag = "PASS" if cond else "FAIL"
    if not cond:
        FAIL.append(name)
    print(f"[{tag}] {name} — {detail}")


LOCK = Path(tempfile.mkdtemp(prefix="r132-lk-")) / "retry.lock"  # 临时锁, 不碰生产 /tmp 锁
COUNTER = Path(tempfile.mkdtemp(prefix="r132-ct-")) / "sim.json"

# 模拟 retry 体(与 retry_failed_metrics 并发双通知同构: 计数++ + 通知++), 经 with_lock --nb 包裹
SIM_CODE = (
    "import json, time; from pathlib import Path;"
    f"p=Path({str(COUNTER)!r});"
    "time.sleep(1);"  # 模拟重采耗时, 放大重叠窗口
    "d=json.loads(p.read_text()) if p.exists() else {'runs':0,'notifies':0};"
    "d['runs']+=1;"
    "d['notifies']+=1;"
    "p.write_text(json.dumps(d));"
)


def run_one():
    return subprocess.run(
        [VERSHO, str(SCRIPTS / "with_lock.py"), "--nb", str(LOCK),
         sys.executable, "-c", SIM_CODE],
        capture_output=True, text=True,
    )


# 两个并发 self_heal 轮次(线程并发启动, 共用同一把锁)
rs = []
threads = [threading.Thread(target=lambda: rs.append(run_one())) for _ in range(2)]
for t in threads:
    t.start()
for t in threads:
    t.join()

final = json.loads(COUNTER.read_text(encoding="utf-8"))
print(f"模拟结果: {final}")

check("并发两实例只有一个进入 retry(runs=1)", final["runs"] == 1,
      f"runs={final['runs']}(期望 1; --nb 锁跳过第二实例)")
check("通知只发生一次(notifies=1)", final["notifies"] == 1,
      f"notifies={final['notifies']}(期望 1, 杜绝并发双通知)")

# 被跳过的一侧 stderr 应含 with_lock 跳过标记(进 audit 日志)
skipped = [r for r in rs if "[with_lock]" in r.stderr and "已被占用" in r.stderr]
check("被跳过实例留 audit 标记(stderr 含 with_lock 跳过)", len(skipped) == 1,
      f"stderr 跳过标记条数={len(skipped)}")

# 全部成功退出(跳过不是失败, exit 0)
check("两实例均 exit 0(跳过非失败)", all(r.returncode == 0 for r in rs),
      f"returncodes={[r.returncode for r in rs]}")

# 串行基线: 同一锁二次 依次跑(无并发) → 两次都进(锁已释放), 验证锁不残留
c_prev = final["runs"]
run_one()
run_one()
after = json.loads(COUNTER.read_text(encoding="utf-8"))
check("锁不残留(串行两轮都进, runs+2)", after["runs"] == c_prev + 2,
      f"runs {c_prev} → {after['runs']}")

if FAIL:
    print(f"\nFAIL {len(FAIL)} 项: {FAIL}")
    sys.exit(1)
print("\n全部 PASS")