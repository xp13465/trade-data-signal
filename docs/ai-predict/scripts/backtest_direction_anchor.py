#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""方向锚确定性规则(_compute_direction_anchor)全历史回测脚本(死脚本,副本落档 §23.5)。

目的:量化「AI 预测的方向锚规则」全历史胜率几何、可不可用。AI 输出(deepseek)无法全历史
     重放(实时模型,无输入快照),方向锚是纯确定性规则,可对 sentiment.db 每交易日重放。
    报告:docs/ai-predict/ai-predict-backtest-feasibility-20260831.md(本脚本=该报告的实施落地)。

方法口径:
    - 对 [start, end] 每个 sentiment.db futures_position 交易日 date,调用
      gen_daily_brief._compute_direction_anchor(db, date) 取因子 -> _shadow_lean 合成
      lean(up/down/flat,现版对称规则含 8-24 R4 down 分支)。
    - 找 date 之后第一个真实交易日(下一个 sh 交易日)的 sh pct_change,
      _actual_direction 按 HIT_THRESHOLD=0.5 判实际方向 up/down/flat。
    - 命中 = lean == actual(纯方向相等口径,非三层严格命中)。
    - 押方向口径(dir_win_rate) = lean in {up,down} 且 actual in {up,down}(真正"押方向"的命中)。

输入依赖:
    - data/sentiment.db(futures_position / index_daily / daily_metric)
    - scripts/gen_daily_brief.py(_compute_direction_anchor L221 / _shadow_lean L397 /
      _actual_direction L2333 / HIT_THRESHOLD L2232)——以 import 复用,不复制实现(防双份分叉)

输出:
    - docs/ai-predict/scripts/out/direction_anchor_backtest_results.json(全量明细+全部指标)
    - docs/ai-predict/scripts/out/direction_anchor_backtest_summary.csv(指标扁平表)
    - 终端打印摘要

关键参数:
    - HIT_THRESHOLD = 0.5(现版,2026-08-14 由 0.1 变更;本脚本默认复用现版,可 --threshold 覆盖做敏感度)
    - NQ_THRESHOLD = -0.8(_compute_direction_anchor 内 nq_open_low 判定,nq<=-0.8%,L3 压制)
    - nq 因子仅 20260716 起,2026-07 前 nq=None -> nq_open_low=False(L3 压制分支不生效,诚实标注)
    - ma20/us10y ma20 起点缓冲:数据起点前 20 交易日无足够历史,ma_bull/rate_down_channel=None,
      lean 走 flat(不污染起点样本)

复现命令:
    python docs/ai-predict/scripts/backtest_direction_anchor.py \
        --db data/sentiment.db --start 20240102 --end 20260830
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent  # trade/
DB_PATH = ROOT / "data" / "sentiment.db"

# ── 复用生产实现:import gen_daily_brief(模块级仅常量+函数定义,无 import 副作用)──
_GB = ROOT / "scripts" / "gen_daily_brief.py"
_spec = importlib.util.spec_from_file_location("gen_daily_brief", _GB)
_gdb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gdb)
_compute_direction_anchor = _gdb._compute_direction_anchor
_shadow_lean = _gdb._shadow_lean
_actual_direction = _gdb._actual_direction
GEN_HIT_THRESHOLD = _gdb.HIT_THRESHOLD  # 0.5(现版)

# nq 因子起点(诚实标注:2026-07 前 nq 缺失 -> L3 压制分支不生效)
NQ_START = "20260716"
_ROLE_LABEL = {"中信期货": "中信", "top20": "机构top20", "国泰君安": "国泰君安"}


# ── 数据层 ────────────────────────────────────────────────────────────────
def _load_sh(db, start, end):
    """返回 (升序日期list, {date: pct_change})(sh 全部交易日)。"""
    cur = db.cursor()
    rows = cur.execute(
        "SELECT date, pct_change FROM index_daily WHERE index_id='sh' "
        "AND date>=? AND date<=? AND pct_change IS NOT NULL ORDER BY date",
        (start, end),
    ).fetchall()
    pct = {d: float(p) for d, p in rows}
    return [d for d, _ in rows], pct


def _load_futures_dates(db, start, end):
    """sentiment.db futures_position 交易日(方向锚重放天数)。"""
    cur = db.cursor()
    rows = cur.execute(
        "SELECT DISTINCT date FROM futures_position WHERE date>=? AND date<=? ORDER BY date",
        (start, end),
    ).fetchall()
    return [r[0] for r in rows]


# ── 指标聚合 ──────────────────────────────────────────────────────────────
def _stat(items):
    """items = list of (lean, actual, meta)。返回总体+分桶。"""
    n = len(items)
    hit = sum(1 for l, a, _ in items if l == a)
    dir_items = [(l, a) for l, a, _ in items if l in ("up", "down") and a in ("up", "down")]
    dir_hit = sum(1 for l, a in dir_items if l == a)
    return {
        "n": n,
        "hit_rate": round(hit / n, 4) if n else None,
        "dir_n": len(dir_items),
        "dir_win_rate": round(dir_hit / len(dir_items), 4) if dir_items else None,
    }


def _bucket(items, key_fn):
    """按 key_fn(整个 item=(lean,actual,meta)) 分桶。"""
    groups = {}
    for it in items:
        k = key_fn(it)
        if k is None:
            continue
        groups.setdefault(k, []).append(it)
    return {k: _stat(g) for k, g in groups.items()}


# ── 因子快照(供子群分解/条件命中)─────────────────────────────────────────
def _factor_snapshot(db_path, date):
    """取方向锚因子精简版,供子群分解(T/role/strength/nq/L 通道)。"""
    f = _compute_direction_anchor(db_path, date)
    return f


# ── 主流程 ────────────────────────────────────────────────────────────────
def _build_items(db_path, db, sh_dates, sh_pct, fut_dates, threshold):
    """构造明细行。threshold 用于 _actual_direction(可覆盖做敏感度)。"""
    # 覆盖生产 HIT_THRESHOLD 做敏感度(不改全局常量,直接局部判定)
    def actual_dir(pct):
        if pct is None:
            return None
        if pct > threshold:
            return "up"
        if pct < -threshold:
            return "down"
        return "flat"

    sh_set = set(sh_dates)
    # 合并升序日期轴
    all_dates_sorted = sorted(set(sh_dates) | set(fut_dates))
    idx = {d: i for i, d in enumerate(all_dates_sorted)}

    rows = []
    for date in fut_dates:
        i = idx[date]
        nxt = None
        for j in range(i + 1, len(all_dates_sorted)):
            if all_dates_sorted[j] in sh_set:
                nxt = all_dates_sorted[j]
                break
        if nxt is None:
            continue
        pct = sh_pct.get(nxt)
        if pct is None:
            continue
        actual = actual_dir(pct)
        if actual is None:
            continue
        try:
            f = _factor_snapshot(db_path, date)
        except Exception:
            continue
        sl = _shadow_lean(f)
        lean = sl["lean"]
        strength = sl["strength"]
        # T 子群:最强转向方向
        to_long = [t for t in (f.get("turns") or []) if t.get("turn_type") == "to_long"]
        to_short = [t for t in (f.get("turns") or []) if t.get("turn_type") == "to_short"]
        T = "both"
        if to_long and not to_short:
            T = "to_long"
        elif to_short and not to_long:
            T = "to_short"
        elif not to_long and not to_short:
            T = "none"
        # role 集合(转向信号的席位)
        roles = sorted({t.get("role") for t in to_long + to_short if t.get("role")})
        # L 通道
        us10y = f.get("us10y")
        gold = f.get("gold")
        nq_chg = f.get("nq_chg")
        rate_down = f.get("rate_down_channel")  # None=数据不足
        nq_present = date >= NQ_START
        nq_low = bool(f.get("nq_open_low"))
        meta = {
            "date": date, "T": T, "roles": roles, "role0": roles[0] if roles else None,
            "strength": strength, "rate_down": rate_down,
            "gold_pos": bool(gold is not None and gold > 0),
            "nq_low": nq_low, "nq_present": nq_present,
        }
        rows.append((lean, actual, meta))
    return rows


def _time_travel_check(db_path, db, sh_dates, sh_pct, fut_dates, threshold, cuts):
    """时点穿越测试(§5.1⑥):把日期轴截断到 t,重算信号序列,与全量逐位一致才 PASS。

    未实现(诚实标注):本脚本核心是方向锚确定性规则重放,_compute_direction_anchor/_shadow_lean
    都是纯确定性规则(基于 date 当日因子,t 时点只读 t 及之前数据,无全期统计量/未来数据),
    因子经 gen_daily_brief 生产逻辑复用,前视风险低;故此处不补截断重算,在 results meta 诚实
    标注「时点穿越测试未实现」,而非输出假 PASS。
    """
    return {"_not_implemented": True}


def run(db_path, start, end):
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
    try:
        sh_dates, sh_pct = _load_sh(db, start, end)
        fut_dates = _load_futures_dates(db, start, end)
    finally:
        db.close()

    # 主口径(现版 HIT_THRESHOLD=0.5)
    items = _build_items(db_path, None, sh_dates, sh_pct, fut_dates, GEN_HIT_THRESHOLD)

    detail = []
    for lean, actual, meta in items:
        detail.append({
            "date": meta["date"], "lean": lean, "actual": actual,
            "T": meta["T"], "roles": meta["roles"],
            "strength": meta["strength"], "rate_down": meta["rate_down"],
            "gold_pos": meta["gold_pos"], "nq_low": meta["nq_low"],
            "nq_present": meta["nq_present"], "hit": lean == actual,
        })

    results = {
        "meta": {
            "db": str(db_path), "start": start, "end": end,
            "data_cutoff": "20260831",
            "HIT_THRESHOLD": GEN_HIT_THRESHOLD,
            "NQ_START": NQ_START,
            "caliber": "方向锚重放现版对称规则(_shadow_lean 含8-24 R4 down分支),命中=lean==actual"
                       "(纯方向相等口径),HIT_THRESHOLD=0.5;nq 因子仅 20260716 起,此前 L3 压制不生效",
            "time_travel_check": "NOT_IMPLEMENTED(方向锚为纯确定性规则,因子只读 t 当日及之前数据,"
                                 "无全期统计量/未来数据,前视风险低;未补截断重算,诚实标注而非假 PASS)",
        },
        "total_sample": len(items),
        "overall": _stat(items),
        "by_lean": _bucket(items, lambda it: it[0]),
        "detail": detail,
    }
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--start", default="20240102")
    ap.add_argument("--end", default="20260830")
    args = ap.parse_args()

    results = run(args.db, args.start, args.end)
    out_dir = Path(__file__).resolve().parent / "out"
    out_dir.mkdir(exist_ok=True)
    json_path = out_dir / "direction_anchor_backtest_results.json"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"total_sample={results['total_sample']}")
    print(f"overall={results['overall']}")
    print(f"json -> {json_path}")


if __name__ == "__main__":
    main()
