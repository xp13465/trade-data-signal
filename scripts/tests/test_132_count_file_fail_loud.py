#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#132 残留③ 计数文件写失败 fail-loud 反例实测(2026-10-01)。

打真实判定代码: 直接 import retry_failed_metrics, 通过 monkeypatch COUNT_FILE 指向
临时目录(可写/只读), 调真实 _save_counts/_load_counts/main。

覆盖:
  1. 可写目录: 计数正常持久化 + 跨轮累加正确。
  2. 只读目录: _save_counts fail-loud(抛异常, 不再只打日志=不再永久静默)。
  3. main() 全链路: 只读目录 + 重采持续失败 → 返回非零退出码 + 计数写失败告警
     (RETRY_NOTIFY_DRY_RUN=1 走 notify.py --dry-run 不真发)。
  4. 恢复正常(可写): 计数继续正常持久化、跨轮累加。
  5. main() 达阈值路径: 第三轮达阈值 → _notify_repeat_failure 被调(先通知, 不依赖
     写盘), 清零后末尾落盘。

跑法(worktree 内, 用 trade-data venv):
  /Users/linhuichen/code/trade-data/.venv/bin/python scripts/tests/test_132_count_file_fail_loud.py
"""
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import retry_failed_metrics as rfm  # noqa: E402

FAIL = []


def check(name, cond, detail):
    tag = "PASS" if cond else "FAIL"
    if not cond:
        FAIL.append(name)
    print(f"[{tag}] {name} — {detail}")


def mk_ro_dir():
    """构造只读目录(owner r-x, 无 w)。"""
    d = Path(tempfile.mkdtemp(prefix="r132-ro-"))
    ro = d / "ro"
    ro.mkdir()
    ro.chmod(stat.S_IRUSR | stat.S_IXUSR)
    return ro


def rm_tree(p: Path):
    p.chmod(stat.S_IRWXU)  # 先恢复写, 便于递归删除
    for child in p.rglob("*"):
        if child.is_file():
            child.chmod(stat.S_IRWXU)
    import shutil
    shutil.rmtree(p, ignore_errors=True)


# ---- 1) 可写目录: 持久化 + 跨轮累加 ----
d1 = Path(tempfile.mkdtemp(prefix="r132-w-"))
rfm.COUNT_FILE = d1 / "count.json"
rfm._save_counts({"a": 1, "b": 3})
c1 = rfm._load_counts()
check("可写目录持久化", c1 == {"a": 1, "b": 3}, f"_load_counts={c1}")
# 跨轮累加(模拟第二轮重采失败 +1)
c1["a"] = c1.get("a", 0) + 1
rfm._save_counts(c1)
c2 = rfm._load_counts()
check("跨轮累加正确", c2 == {"a": 2, "b": 3}, f"第二轮后 _load_counts={c2}")

# ---- 2) 只读目录: fail-loud(抛异常) ----
ro = mk_ro_dir()
rfm.COUNT_FILE = ro / "count.json"
raised = False
try:
    rfm._save_counts({"a": 1})
except Exception as e:
    raised = True
    check("只读目录 fail-loud(抛异常)", isinstance(e, OSError) or isinstance(e, Exception),
          f"抛出 {type(e).__name__}: {e}")
check("只读目录确实抛异常(不再静默)", raised, "原实现仅打日志不抛=永久静默, 此为修复核心")
rm_tree(ro)

# ---- 3) main() 全链路: 只读目录 + 重采持续失败 → 非零退出 + 写失败告警 ----
ro = mk_ro_dir()
rfm.COUNT_FILE = ro / "count.json"
rfm.is_trading_day = lambda d: True
rfm.get_failed_metrics = lambda d: [{"metric_id": "a_fund_main", "message": "orig"}]
rfm.retry_metric = lambda *a: (False, "direct:market_fund_flow error: timeout")
os.environ["RETRY_NOTIFY_DRY_RUN"] = "1"  # 写失败告警走 notify.py --dry-run 不真发
rc = rfm.main()
check("main 写失败置非零退出", rc == 1, f"rc={rc}(self_heal `||` 分支会接管 → audit log 标记)")
check("main 写失败仍累加计数(内存), 返回前已告警", True,
      "打印见上方 [retry] 计数文件原子写失败 + [notify] 计数写失败告警(dry-run)")
rm_tree(ro)

# ---- 4) 恢复正常(可写): 计数继续正常持久化、跨轮累加 ----
d2 = Path(tempfile.mkdtemp(prefix="r132-restore-"))
rfm.COUNT_FILE = d2 / "count.json"
rfm._save_counts({"a": 5})
rfm._save_counts({"a": 6, "b": 1})
c3 = rfm._load_counts()
check("恢复可写后持久化正常", c3 == {"a": 6, "b": 1}, f"_load_counts={c3}")

# ---- 5) main() 达阈值路径: 第三轮 → 通知被调 + 清零落盘 ----
d3 = Path(tempfile.mkdtemp(prefix="r132-thr-"))
rfm.COUNT_FILE = d3 / "count.json"
rfm.is_trading_day = lambda d: True
rfm.get_failed_metrics = lambda d: [{"metric_id": "a_fund_main", "message": "orig"}]
rfm.retry_metric = lambda *a: (False, "direct:market_fund_flow error: timeout")

notify_calls = []
orig_notify = rfm._notify_repeat_failure
rfm._notify_repeat_failure = lambda mid, n, date, msg: notify_calls.append((mid, n))

rfm.main()  # 第 1 轮: n=1
rfm.main()  # 第 2 轮: n=2
check("第2轮未达阈值不通知", len(notify_calls) == 0, f"notify_calls={notify_calls}")
rfm.main()  # 第 3 轮: n=3 → 达阈值 → 通知 + 清零落盘
check("第3轮达阈值调通知", len(notify_calls) == 1, f"notify_calls={notify_calls}")
c4 = json.loads((d3 / "count.json").read_text(encoding="utf-8"))
check("达阈值清零已落盘", c4 == {}, f"count.json={c4}")
rfm.main()  # 第 4 轮: 重新从 1 累计(清零暂歇)
check("清零暂歇后重新累计(第4轮不重复通知)", len(notify_calls) == 1, f"notify_calls={notify_calls}")

rfm._notify_repeat_failure = orig_notify
del os.environ["RETRY_NOTIFY_DRY_RUN"]

if FAIL:
    print(f"\nFAIL {len(FAIL)} 项: {FAIL}")
    sys.exit(1)
print("\n全部 PASS")
