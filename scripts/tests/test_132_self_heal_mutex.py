#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#132 残留② self_heal 并发双通知修复 pytest 版(2026-10-01 修复, 2026-10-03 改造)。

self_heal.sh 调 retry_failed_metrics 已改经 with_lock.py --nb 进程互斥(#132)。
本测试用与生产完全相同的 with_lock.py(仓内既有唯一实现) + 同一锁语义模拟两个并发
self_heal 轮次, 证明: 并发时只有一个实例进入 retry(读计数+发通知), 另一个被 --nb
跳过 → 不可能出现"双双读到 n=2 双双跨阈值发两次通知"。

模拟的 retry 体=「写计数 + 发通知」两动作(即并发双通知的最小造影), 统计 runs/notifies。

原脚本式自测: 顶层创建 LOCK/COUNTER + 直接跑并发实验 + sys.exit; 且 VERSHO 硬编码
开发者本机 venv 绝对路径(CI ubuntu 上不存在 → subprocess FileNotFoundError)。
改为真 pytest:
  - 实验放进 test 函数内执行(pytest 收集阶段零副作用), 并发实验 5 条验证点落在同一
    test(同一实验的 5 个角度, 拆开会重复跑 1s 并发实验且依赖跨 test 状态), 串行基线
    独立一个 test;
  - VERSHO 硬编码 → sys.executable(当前解释器, 本地/CI 通吃);
  - 临时锁/计数器目录用 pytest tmp_path fixture(并发/重跑安全)。

跑法(pytest, CI ⑧同):
  python3 -m pytest -q scripts/tests/test_132_self_heal_mutex.py
"""
import json
import subprocess
import sys
import threading
from pathlib import Path

# 测试文件在 scripts/tests/ 下, 上溯三级到仓库根(与既有正常 test 文件同范式)
REPO_ROOT = Path(__file__).absolute().parent.parent.parent
SCRIPTS = REPO_ROOT / "scripts"
PY = str(Path(sys.executable))


def run_one(lock, counter):
    """经 with_lock --nb 包裹一次模拟 retry 体; 返回 subprocess.CompletedProcess。"""
    sim_code = (
        "import json, time; from pathlib import Path;"
        f"p=Path({str(counter)!r});"
        "time.sleep(1);"  # 模拟重采耗时, 放大重叠窗口
        "d=json.loads(p.read_text()) if p.exists() else {'runs':0,'notifies':0};"
        "d['runs']+=1;"
        "d['notifies']+=1;"
        "p.write_text(json.dumps(d));"
    )
    return subprocess.run(
        [PY, str(SCRIPTS / "with_lock.py"), "--nb", str(lock),
         sys.executable, "-c", sim_code],
        capture_output=True, text=True,
    )


def test_concurrent_lock_exclusion(tmp_path):
    """两个并发 self_heal 轮次共用同一把锁: 只有一个进入 retry, 另一个 --nb 跳过。"""
    lock = tmp_path / "retry.lock"          # 临时锁, 不碰生产 /tmp 锁
    counter = tmp_path / "sim.json"

    rs = []
    threads = [threading.Thread(target=lambda: rs.append(run_one(lock, counter)))
               for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final = json.loads(counter.read_text(encoding="utf-8"))

    # 验证点1: 并发两实例只有一个进入 retry
    assert final["runs"] == 1, \
        f"runs={final['runs']}(期望 1; --nb 锁跳过第二实例)"
    # 验证点2: 通知只发生一次
    assert final["notifies"] == 1, \
        f"notifies={final['notifies']}(期望 1, 杜绝并发双通知)"
    # 验证点3: 被跳过的一侧 stderr 应含 with_lock 跳过标记(进 audit 日志)
    skipped = [r for r in rs if "[with_lock]" in r.stderr and "已被占用" in r.stderr]
    assert len(skipped) == 1, \
        f"stderr 跳过标记条数={len(skipped)}(期望恰 1 条)"
    # 验证点4: 全部成功退出(跳过不是失败, exit 0)
    assert all(r.returncode == 0 for r in rs), \
        f"returncodes={[r.returncode for r in rs]}(跳过非失败)"


def test_serial_release_no_residue(tmp_path):
    """串行基线: 同一锁两次依次跑(无并发) → 两次都进(锁已释放), 验证锁不残留。"""
    lock = tmp_path / "retry.lock"
    counter = tmp_path / "sim.json"

    run_one(lock, counter)
    run_one(lock, counter)
    after = json.loads(counter.read_text(encoding="utf-8"))
    assert after["runs"] == 2, \
        f"串行两轮 runs={after['runs']}(期望 2=锁不残留, 两次都进)"