#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""孤儿冻结清理机制 (#124, 2026-10-01)。

背景: 冻结表 data/signal_kelly_etf_freeze.json 的键为 date|index_id|signal。
盘中冻结的信号在收盘重算后可能「严格消失」(detect_fade, check_signals.py:938),
signal_daily 不再有该事件, 冻结键成为永不命中的孤儿(回测只遍历 signal_daily,
_不会_查询孤儿键, 故孤儿键不影响回测结果, 但残留污染冻结表数据质量)。

本脚本: 扫描冻结表, 找出「该 (date,index_id) 在 signal_daily 完全无任何事件」的
孤儿键, 默认 dry-run 报告, --commit 才删除。核心防误删设计:

  1. 判据锚冻结键本身构成(date|index_id|signal), 绝不用「某字段顺手存在」当判据
     (memory data-source-switch-field-filter-blindspot)。
  2. 漂移豁免: (date,index_id) 在 signal_daily 仍有其他信号变体(如 buy→buy_aux,
     memory freeze-key-signal-type-drift)→ 不算孤儿, 绝不能清 ——
     signal_kelly_backtest._freeze_fallback(2026-09-22) 依赖这些变体键兜底。
  3. 冷却期: 冻结键 date 距今 < cooldown_days(默认 15)→ 跳过(等待收盘 signal_daily
     写入 / 延迟回填窗口, 防「暂时查不到但事后回来」误删 —— 09-22 sz_div 事后
     延迟回填先例)。
  4. 备份: --commit 前自动备份冻结表到同目录 .bak-<ts>, 可一键回退。

影响面(§23.7 冻结契约): 不改 signal_kelly_backtest.py / check_signals.py /
冻结写入链路; 只新增独立清理脚本 + 只读 signal_daily。冻结表读取侧
_freeze_fallback 不变, 真孤儿键在 signal_daily 无事件, 回测永不查询, 删除无影响。

运行建议: 盘后(收盘 signal_daily 定稿后)运行; 默认 dry-run 只报告,
确认后 --commit。云上部署为独立 systemd timer(不侵入 update_all 链)。
"""
import argparse
import json
import os
import shutil
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from util_atomic import atomic_write_json  # noqa: E402
FREEZE_PATH_ENV = "SIGNAL_KELLY_ETF_FREEZE_PATH"
DEFAULT_COOLDOWN_DAYS = 15


def _freeze_path_default():
    p = os.environ.get(FREEZE_PATH_ENV)
    if p:
        return p
    return os.path.join(ROOT, "data", "signal_kelly_etf_freeze.json")


def load_events(db_path=None, signals_file=None):
    """加载 signal_daily 全量事件。

    Returns:
        exact: set[(date, index_id, signal)] 精确事件集
        di:    set[(date, index_id)] 该日该指数有任何事件(任一变体)
    """
    exact, di = set(), set()
    if signals_file:
        with open(signals_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) < 3:
                    continue
                exact.add((parts[0], parts[1], parts[2]))
                di.add((parts[0], parts[1]))
        return exact, di
    import sqlite3

    conn = sqlite3.connect(db_path, timeout=30.0)
    for d, iid, sig in conn.execute(
        "SELECT date, index_id, signal FROM signal_daily"
    ):
        exact.add((d, iid, sig))
        di.add((d, iid))
    conn.close()
    return exact, di


def classify(freeze, exact, di, cooldown_days, today=None):
    """按冻结键构成分层分类。

    Returns:
        normal: 精确命中(正常)
        drift:  (date,index_id) 有变体事件(漂移, 不可清)
        cooldown: 真孤儿但冻结 date 距今 < cooldown_days(冷却期内, 不可清)
        orphan: 真孤儿且已过冷却期(可清)
    """
    today = today or datetime.now()
    normal, drift, cooldown, orphan = [], [], [], []
    for key in freeze:
        parts = key.split("|")
        if len(parts) != 3:
            continue  # 格式异常键, 不碰
        d, iid, sig = parts
        if (d, iid, sig) in exact:
            normal.append(key)
        elif (d, iid) in di:
            drift.append(key)
        else:
            try:
                days = (today - datetime.strptime(d, "%Y%m%d")).days
            except ValueError:
                days = cooldown_days  # 日期格式异常, 保守不进清理
            if days < cooldown_days:
                cooldown.append(key)
            else:
                orphan.append(key)
    return normal, drift, cooldown, orphan


def main():
    ap = argparse.ArgumentParser(description="孤儿冻结清理(dry-run 默认)")
    ap.add_argument("--freeze", default=None, help="冻结表路径(默认 SIGNAL_KELLY_ETF_FREEZE_PATH 或 data/signal_kelly_etf_freeze.json)")
    ap.add_argument("--db", default=None, help="sentiment.db 路径(signal_daily 读取源; 与 --signals 二选一)")
    ap.add_argument("--signals", default=None, help="signal_daily 三字段导出文件(date|index_id|signal 每行; 与 --db 二选一)")
    ap.add_argument("--cooldown-days", type=int, default=DEFAULT_COOLDOWN_DAYS, help=f"冷却期(默认 {DEFAULT_COOLDOWN_DAYS})")
    ap.add_argument("--commit", action="store_true", help="实际删除(默认 dry-run 只报告)")
    ap.add_argument("--audit-log", default=None, help="审计日志路径(默认 data/freeze_cleanup_audit.log)")
    args = ap.parse_args()

    freeze_path = args.freeze or _freeze_path_default()
    if not os.path.exists(freeze_path):
        print(f"冻结表不存在: {freeze_path}")
        sys.exit(1)
    if not args.db and not args.signals:
        print("必须指定 --db 或 --signals")
        sys.exit(1)
    with open(freeze_path, encoding="utf-8") as f:
        freeze = json.load(f)
    exact, di = load_events(args.db, args.signals)
    normal, drift, cooldown, orphan = classify(
        freeze, exact, di, args.cooldown_days
    )
    total = len(freeze)
    print(f"冻结表总键: {total}")
    print(f"  正常(精确命中): {len(normal)}")
    print(f"  漂移((date,index)有变体, 不可清): {len(drift)}")
    print(f"  孤儿候选-冷却期内(冻结未满{args.cooldown_days}天, 不可清): {len(cooldown)}")
    print(f"  孤儿-可清: {len(orphan)}")
    if drift:
        print("\n[漂移键(不可清, _freeze_fallback 依赖)]")
        for k in sorted(drift):
            print("   ", k)
    if cooldown:
        print(f"\n[冷却期内(暂不可清, 等回填窗口)]")
        for k in sorted(cooldown):
            print("   ", k)
    if orphan:
        print("\n[可清孤儿]")
        for k in sorted(orphan):
            print("   ", k)

    if not args.commit:
        print(f"\n[dry-run] 将删除 {len(orphan)} 键, 未执行。加 --commit 实际删除。")
        return
    if not orphan:
        print("\n[commit] 无可清孤儿, 无操作。")
        return
    # 备份 + 原子写 + 审计
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{freeze_path}.bak-{ts}"
    shutil.copy2(freeze_path, bak)
    for k in orphan:
        del freeze[k]
    atomic_write_json(freeze_path, freeze, separators=(",", ":"))
    audit_path = args.audit_log or os.path.join(ROOT, "data", "freeze_cleanup_audit.log")
    with open(audit_path, "a", encoding="utf-8") as f:
        for k in sorted(orphan):
            f.write(f"{ts} DEL {k}\n")
        f.write(f"{ts} # 共删 {len(orphan)} 键, 备份 {bak}\n")
    print(f"\n[commit] 已删 {len(orphan)} 键。备份: {bak}")
    print(f"       审计日志: {audit_path}")


if __name__ == "__main__":
    main()
