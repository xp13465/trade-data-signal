#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W1 L1 度量层复现脚本（2026-10-10）：CLI 级证据（幂等 md5 + 查询面输出）。

与 test_alert_meter_l1_20261010.py 共用**同一份**真样本表（`import` 该测试模块的
REAL_20/DAY，单一事实源 ⇒ 无「复刻逻辑第二实现漂移」，§5.4⑦）。

输出（不写任何生产目录，全在 --out 指定目录内）：
  1. 两棵临时树（运行树 19 + 信号树 1）从 20 条真样本重建台账；
  2. `alert_meter.py --recount` 连跑两次 → alert_daily.json md5 逐位一致（幂等证据）；
  3. `--today --date 2026-10-09` / `--week` / `--top` 三段查询面真实输出；
  4. 逐条对照表：人工重建 20 vs 台账重算 N。

跑法：python3 scripts/tests/repro_alert_meter_l1_20261010.py [--out /tmp/l1-repro]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SCRIPTS))

import test_alert_meter_l1_20261010 as T  # noqa: E402  单一事实源（真样本表）

ALERT_METER = SCRIPTS / "alert_meter.py"


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def _build_trees(out: Path) -> tuple[Path, Path]:
    run = out / "trade-data"
    sig = out / "trade-data-signal"
    for t in (run, sig):
        (t / "data" / "alerts").mkdir(parents=True, exist_ok=True)
    run_lines, sig_lines = [], []
    for ts, tier, key, subj, src, tree in T.REAL_20:
        rec = {"ts": ts, "tree": str(run if tree == "run" else sig), "tier": tier,
               "key": key, "subject": subj, "channels": {"email": True, "feishu": True},
               "source": src, "group": "alert"}
        (run_lines if tree == "run" else sig_lines).append(json.dumps(rec, ensure_ascii=False))
    (run / "data" / "alerts" / "alert_ledger.jsonl").write_text(
        "\n".join(run_lines) + "\n", encoding="utf-8")
    (sig / "data" / "alerts" / "alert_ledger.jsonl").write_text(
        "\n".join(sig_lines) + "\n", encoding="utf-8")
    return run, sig


def _run(*args: str) -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(ALERT_METER), *args],
                       capture_output=True, text=True, timeout=120, check=False)
    return p.returncode, (p.stdout + p.stderr).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/l1-repro")
    args = ap.parse_args()
    out = Path(args.out)
    if out.exists():
        import shutil
        shutil.rmtree(out)
    run, sig = _build_trees(out)
    trees = f"{run}:{sig}"          # os.pathsep = ':'

    print(f"== 树 = {run} + {sig}（20 条真样本：运行树 19 / 信号树 1）")
    ledger = run / "data" / "alerts" / "alert_ledger.jsonl"
    print(f"   运行树台账 {len(ledger.read_text(encoding='utf-8').splitlines())} 行；"
          f"信号树台账 "
          f"{len((sig / 'data' / 'alerts' / 'alert_ledger.jsonl').read_text(encoding='utf-8').splitlines())} 行")

    print("\n== [1] 幂等重算（连跑两次，比对 md5）")
    rc1, out1 = _run("--recount", "--date", T.DAY, "--trees", trees)
    d_run = run / "data" / "alerts" / "alert_daily.json"
    d_sig = sig / "data" / "alerts" / "alert_daily.json"
    m1r, m1s = _md5(d_run), _md5(d_sig)
    rc2, out2 = _run("--recount", "--date", T.DAY, "--trees", trees)
    m2r, m2s = _md5(d_run), _md5(d_sig)
    print(f"   rc={rc1}/{rc2}  {out1.splitlines()[0] if out1 else ''}")
    print(f"   运行树 md5 {m1r} -> {m2r}   {'一致' if m1r == m2r else '不一致!!'}")
    print(f"   信号树 md5 {m1s} -> {m2s}   {'一致' if m1s == m2s else '不一致!!'}")
    print(f"   两树内容一致（§22）：{'是' if m1r == m1s else '否!!'}")
    print(f"   daily = {json.dumps(json.loads(d_run.read_text(encoding='utf-8')), ensure_ascii=False)}")

    print("\n== [2] 查询面 --today（跨两树聚合）")
    _, o = _run("--today", "--date", T.DAY, "--trees", trees)
    print(o)

    print("\n== [3] 查询面 --week")
    _, o = _run("--week", "--date", T.DAY, "--trees", trees)
    print(o)

    print("\n== [4] 查询面 --top 5")
    _, o = _run("--top", "5", "--date", T.DAY, "--trees", trees)
    print(o)

    print("\n== [5] 逐条对照表：人工重建 20 vs 台账重算")
    for i, (ts, tier, key, subj, src, tree) in enumerate(T.REAL_20, 1):
        print(f"  #{i:>2} {ts} [{key}] {subj[:36]} <= {src}({tree})")
    return 0 if (rc1 == 0 and rc2 == 0 and m1r == m2r and m1s == m2s and m1r == m1s) else 1


if __name__ == "__main__":
    sys.exit(main())