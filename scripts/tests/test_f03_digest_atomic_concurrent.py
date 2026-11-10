# -*- coding: utf-8 -*-
"""F03(2026-11-04): 摘要同签名并发吸收原子性测试。

两个**真进程**(multiprocessing fork + Barrier 同步栅栏)同日同签名并发吸收
→ 摘要文件只有 1 行, hits=2。
红先验: 把临界区退回旧逻辑(读-释放-判-写分步), 本用例必须红。
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent))
sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import notify  # noqa: E402
from _notify_sandbox import notify_sandbox, run_workers  # noqa: E402


# ---- 模块级 worker(fork 子进程继承父进程已 patch 的 notify) ----
_BARRIER = None  # 由测试函数注入


def _fork_worker(subject, body, key, category):
    """fork 子进程入口: 等 Barrier 同步 → 吸收一条 → exit 0。"""
    _BARRIER.wait()
    notify._absorb_to_digest(subject, body, key=key, category=category, bump_hits=True)


def test_concurrent_same_signature_one_row_hits2(notify_sandbox):
    """两个真进程同日同签名并发 → 只有 1 行, hits=2。"""
    import multiprocessing as mp
    ctx = mp.get_context("fork")  # fork = 真进程, 继承已 patch 的 notify
    alerts = notify_sandbox["digest"].parent

    global _BARRIER
    _BARRIER = ctx.Barrier(2)
    p1 = ctx.Process(target=_fork_worker,
                     args=("并发主题", "并发正文", "conc_key", "r2"))
    p2 = ctx.Process(target=_fork_worker,
                     args=("并发主题", "并发正文", "conc_key", "r2"))
    run_workers(p1, p2, timeout=15)

    digest_path = alerts / "alert_digest.jsonl"
    lines = [l for l in digest_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1, f"并发吸收应只 1 行, 得 {len(lines)} 行:\n{lines}"
    rec = json.loads(lines[0])
    assert rec["key"] == "conc_key", f"key 不符: {rec['key']}"
    assert rec.get("hits") == 2, f"hits 应为 2(两进程各并入一次), 得 {rec.get('hits')}"
    print(f"[F03] 并发同签名 PASS: {len(lines)} 行, hits={rec['hits']}")


def test_sequential_same_signature_bump_hits(notify_sandbox):
    """单进程顺序两次同 key(bump_hits=True) → 1 行 hits=2(回归保护)。"""
    alerts = notify_sandbox["digest"].parent

    ok1 = notify._absorb_to_digest("顺序主题", "正文", key="seq_key",
                                   category="r2", bump_hits=True)
    ok2 = notify._absorb_to_digest("顺序主题", "正文", key="seq_key",
                                   category="r2", bump_hits=True)
    assert ok1 and ok2, "两次吸收都应返回 True"
    lines = [l for l in (alerts / "alert_digest.jsonl").read_text(encoding="utf-8").splitlines()
             if l.strip()]
    assert len(lines) == 1, f"顺序同 key 应只 1 行, 得 {len(lines)}"
    rec = json.loads(lines[0])
    assert rec.get("hits") == 2, f"hits 应为 2, 得 {rec.get('hits')}"
    print(f"[F03] 顺序回归 PASS: {len(lines)} 行, hits={rec['hits']}")


def test_concurrent_different_keys_two_rows(notify_sandbox):
    """两个进程不同 key 并发 → 各 1 行(2 行)。"""
    import multiprocessing as mp
    ctx = mp.get_context("fork")
    alerts = notify_sandbox["digest"].parent

    global _BARRIER
    _BARRIER = ctx.Barrier(2)
    p1 = ctx.Process(target=_fork_worker,
                     args=("不同key", "正文A", "diff_a", "r2"))
    p2 = ctx.Process(target=_fork_worker,
                     args=("不同key", "正文B", "diff_b", "r2"))
    run_workers(p1, p2, timeout=15)

    digest_path = alerts / "alert_digest.jsonl"
    lines = [l for l in digest_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 2, f"不同 key 并发应 2 行, 得 {len(lines)} 行"
    keys = {json.loads(l)["key"] for l in lines}
    assert keys == {"diff_a", "diff_b"}, f"key 集合不符: {keys}"
    print(f"[F03] 并发不同key PASS: {len(lines)} 行")


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(pytest.main([__file__, "-q"]))
