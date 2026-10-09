#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#132 残留③ 计数文件写失败 fail-loud 反例 pytest 版(2026-10-01 修复, 2026-10-03 改造)。

原脚本式自测顶层直接执行 5 条 check + sys.exit(pytest 收集时 no tests collected)。
本文件改为真 pytest: 5 条验证点逐条落成 test 函数, 断言与原脚本逐条对等。

打真实判定代码: import retry_failed_metrics, 通过 monkeypatch COUNT_FILE 指向临时目录
(可写/只读), 调真实 _save_counts/_load_counts/main。测试各条自身隔离: 临时目录用 pytest
tmp_path 原生 fixture(并发/重跑安全), main() 链路经 monkeypatch env(不真发信)。

覆盖(与原 docstring 对应):
  1. 可写目录: 计数正常持久化 + 跨轮累加正确。
  2. 只读目录: _save_counts fail-loud(抛异常, 不再只打日志=不再永久静默)。
  3. main() 全链路: 只读目录 + 重采持续失败 → 返回非零退出码 + 计数写失败告警
     (RETRY_NOTIFY_DRY_RUN=1 走 notify.py --dry-run 不真发)。
  4. 恢复正常(可写): 计数继续正常持久化、跨轮累加。
  5. main() 达阈值路径: 第三轮达阈值 → _notify_repeat_failure 被调(先通知, 不依赖
     写盘), **送达后**清零末尾落盘。(2026-10-09 #241 同族B波: _notify_repeat_failure
     新契约改为返回 bool=是否真送达, main() 送达才清零; 本用例桩返回 True 体现送达。)
  6. main() 未送达路径(#241 同族B波新契约): 达阈值但通知未确认送达 ⇒ 不清零, 保留计数
     下轮重试(不静默丢达标告警)。

注: 原脚本第 3 条里另有一个恒 True 的 `check("main 写失败仍累加计数(内存)", True, ...)`
占位(结论见打印日志, 无实际判定), 改造后以 rc==1(非零退出=fail-loud 置位)为硬断言,
占位 print 归并到 rc 断言失败信息中, 非删减。

跑法(pytest, CI ⑧同):
  python3 -m pytest -q scripts/tests/test_132_count_file_fail_loud.py
"""
import json
import stat
from pathlib import Path

import pytest

import retry_failed_metrics as rfm  # noqa: E402  (conftest 已注入 scripts/; CI 上第三方库已 stub)


def mk_ro_dir(tmp_path):
    """构造只读目录(owner r-x, 无 w)。"""
    d = tmp_path / "ro"
    d.mkdir()
    d.chmod(stat.S_IRUSR | stat.S_IXUSR)
    return d


def rm_tree_ro(p: Path):
    p.chmod(stat.S_IRWXU)  # 先恢复写, 便于递归删除
    for child in p.rglob("*"):
        if child.is_file():
            child.chmod(stat.S_IRWXU)
    import shutil
    shutil.rmtree(p, ignore_errors=True)


def patch_fail_chain(monkeypatch):
    """monkeypatch 重采链路: 交易日恒定 + 指标恒失败(触发累计/阈值/通知路径)。"""
    monkeypatch.setattr(rfm, "is_trading_day", lambda d: True, raising=False)
    monkeypatch.setattr(rfm, "get_failed_metrics",
                        lambda d: [{"metric_id": "a_fund_main", "message": "orig"}],
                        raising=False)
    monkeypatch.setattr(rfm, "retry_metric",
                        lambda *a: (False, "direct:market_fund_flow error: timeout"),
                        raising=False)


# ───────────────── 验证点逐条: 与原脚本 1..5 一一对应 ─────────────────
def test_1_writable_persist_and_accumulate(tmp_path):
    """可写目录: 计数正常持久化 + 跨轮累加正确。"""
    rfm.COUNT_FILE = tmp_path / "w" / "count.json"
    rfm.COUNT_FILE.parent.mkdir(parents=True)
    rfm._save_counts({"a": 1, "b": 3})
    c1 = rfm._load_counts()
    assert c1 == {"a": 1, "b": 3}, f"_load_counts={c1}"
    # 跨轮累加(模拟第二轮重采失败 +1)
    c1["a"] = c1.get("a", 0) + 1
    rfm._save_counts(c1)
    c2 = rfm._load_counts()
    assert c2 == {"a": 2, "b": 3}, f"第二轮后 _load_counts={c2}"


def test_2_readonly_fail_loud(tmp_path):
    """只读目录: _save_counts fail-loud(抛 OSError, 不再静默只打日志)。"""
    ro = mk_ro_dir(tmp_path)
    rfm.COUNT_FILE = ro / "count.json"
    with pytest.raises(OSError):
        rfm._save_counts({"a": 1})
    rm_tree_ro(ro)


def test_3_main_readonly_rc_nonzero(tmp_path, monkeypatch):
    """main() 全链路: 只读目录 + 重采持续失败 → 非零退出码 + 写失败告警(dry-run 不真发)。"""
    ro = mk_ro_dir(tmp_path)
    rfm.COUNT_FILE = ro / "count.json"
    patch_fail_chain(monkeypatch)
    monkeypatch.setenv("RETRY_NOTIFY_DRY_RUN", "1")  # 写失败告警走 notify.py --dry-run 不真发
    rc = rfm.main()
    assert rc == 1, f"rc={rc}(self_heal `||` 分支会接管 → audit log 标记)"
    rm_tree_ro(ro)


def test_4_restored_writable_persist(tmp_path):
    """恢复正常(可写): 计数继续正常持久化、跨轮累加。"""
    rfm.COUNT_FILE = tmp_path / "restore" / "count.json"
    rfm.COUNT_FILE.parent.mkdir(parents=True)
    rfm._save_counts({"a": 5})
    rfm._save_counts({"a": 6, "b": 1})
    c3 = rfm._load_counts()
    assert c3 == {"a": 6, "b": 1}, f"_load_counts={c3}"


def test_5_main_threshold_notify_then_reset(tmp_path, monkeypatch):
    """main() 达阈值路径: 第三轮 → 通知被调(送达)+ 清零落盘, 清零暂歇后重新累计不重复通知。

    #241 同族B波(2026-10-09): _notify_repeat_failure 新契约返回 bool=是否真送达,
    main() **送达才清零**。本用例桩显式 return True(体现送达) ⇒ 语义「达标→通知→
    清零暂歇」不变, 前提多了「送达」这一条。旧桩 lambda ...: notify_calls.append(...)
    返回 None(假值, §18 L48 类「桩不返回布尔被当假值」陷阱)⇒ 会被新代码判成「未送达」
    而不清零, 故必须显式返回 True。
    """
    rfm.COUNT_FILE = tmp_path / "thr" / "count.json"
    rfm.COUNT_FILE.parent.mkdir(parents=True)
    patch_fail_chain(monkeypatch)

    notify_calls = []

    def _notify_sent(mid, n, date, msg):
        notify_calls.append((mid, n))
        return True  # 新契约: 送达=True ⇒ 调用方清零暂歇

    monkeypatch.setattr(rfm, "_notify_repeat_failure", _notify_sent)

    rfm.main()  # 第 1 轮: n=1
    rfm.main()  # 第 2 轮: n=2
    assert len(notify_calls) == 0, f"第2轮未达阈值不得通知, notify_calls={notify_calls}"
    rfm.main()  # 第 3 轮: n=3 → 达阈值 → 通知 + 清零落盘
    assert len(notify_calls) == 1, f"第3轮达阈值应调通知, notify_calls={notify_calls}"
    c4 = json.loads(rfm.COUNT_FILE.read_text(encoding="utf-8"))
    assert c4 == {}, f"达阈值清零已落盘, count.json={c4}"
    rfm.main()  # 第 4 轮: 重新从 1 累计(清零暂歇)
    assert len(notify_calls) == 1, f"清零暂歇后重新累计(第4轮不重复通知), notify_calls={notify_calls}"


def test_6_main_threshold_not_sent_keeps_count(tmp_path, monkeypatch):
    """main() 未送达路径(#241 同族B波新契约): 达阈值但通知未确认送达 ⇒ **不清零**,
    计数保留 >= 阈值, 下轮继续重试通知(不静默丢达标告警, 也绝不占「已发一次」位)。

    这是 #241 同族B波的整个立意: 旧实现「先 counts.pop 后 fire-and-forget」= 通道全挂时
    计数已被清零暂歇 ⇒ 达标告警永久丢失(下轮从 0 重新累计)。此负向用例旧代码必 FAIL。
    """
    rfm.COUNT_FILE = tmp_path / "thr_unsent" / "count.json"
    rfm.COUNT_FILE.parent.mkdir(parents=True)
    patch_fail_chain(monkeypatch)

    notify_calls = []

    def _notify_unsent(mid, n, date, msg):
        notify_calls.append((mid, n))
        return False  # 通道全挂: 未送达 ⇒ 调用方不得清零

    monkeypatch.setattr(rfm, "_notify_repeat_failure", _notify_unsent)

    rfm.main()  # 第 1 轮: n=1
    rfm.main()  # 第 2 轮: n=2
    assert len(notify_calls) == 0, f"第2轮未达阈值不得通知, notify_calls={notify_calls}"
    rfm.main()  # 第 3 轮: n=3 达阈值 → 通知(未送达)
    assert len(notify_calls) == 1, f"第3轮达阈值应调通知, notify_calls={notify_calls}"
    c3 = json.loads(rfm.COUNT_FILE.read_text(encoding="utf-8"))
    assert c3 == {"a_fund_main": 3}, f"未送达不得清零(旧代码会 pop 掉), count.json={c3}"
    rfm.main()  # 第 4 轮: 计数保留 → n=4 仍达阈值 → 再试通知(不静默丢)
    assert len(notify_calls) == 2, f"未送达应下轮重试通知, notify_calls={notify_calls}"
    c4 = json.loads(rfm.COUNT_FILE.read_text(encoding="utf-8"))
    assert c4 == {"a_fund_main": 4}, f"未送达累加保留, count.json={c4}"