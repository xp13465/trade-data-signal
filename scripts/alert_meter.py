#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""告警度量查询面（W1 L1 度量层，2026-10-10）。

让「一天几条告警」从口号变成可查数字：读单点台账 data/alerts/alert_ledger.jsonl
（由 scripts/notify.py 每次**实际外发**追加一行），按日聚合为 data/alerts/alert_daily.json，
并提供 --today / --week / --top 查询。

设计要点
--------
1. 台账写点见 notify.py（消息级 send/send_to + 底层直调包装 send_feishu/_send_email）。
2. **跨两树聚合**：云上运行树 ~/code/trade-data 与信号树 ~/code/trade-data-signal 各有
   独立台账（双树分裂是审计 D1 结构性根因）；若不跨树会「又变成两个数字」，违反 §22
   一致性铁律。故本查询面默认聚合 REPO 及其**兄弟树**(trade-data / trade-data-signal)；
   可用 `--trees a:b` 或 env ALERT_METER_TREES(os.pathsep 分隔) 显式覆盖。
3. **幂等重算**：alert_daily.json 只由台账重算（非累加，无状态漂移），且把同一聚合结果
   写入**每棵树**的 data/alerts/alert_daily.json（N 展示位一致，§22）。
   重算不写任何墙钟时间戳 ⇒ 同一台账两次重算输出**逐位一致**（可机检幂等）。
4. 口径分离：台账含全部真实外发（含 report 群功能输出/agent_done），查询面按 group 拆分
   ——「告警群(alert)」为主口径，report/agent_done 另列，避免功能输出污染「0~3 条/天」判据。
5. 本脚本纯派生（读台账写日计数），**自身绝不告警**（防元噪声）。

用法
----
  python scripts/alert_meter.py --today            # 今日一行 + top talkers + 前 7 日均值对比
  python scripts/alert_meter.py --week             # 近 7 天逐日表 + P50/P90
  python scripts/alert_meter.py --budget           # L5 验收视图：近 7 天 P50/P90 → PASS/FAIL
  python scripts/alert_meter.py --top 20           # 近 7 天 top talkers
  python scripts/alert_meter.py --recount          # 幂等重算 alert_daily.json（写每棵树）
  python scripts/alert_meter.py --today --json     # 机读 JSON 输出
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(os.environ.get("REPO") or Path(__file__).resolve().parent.parent)

LEDGER_FILENAME = "alert_ledger.jsonl"
DAILY_FILENAME = "alert_daily.json"

# 告警群口径（用户「0~3 条/天」判据的主口径）：飞书 alert 群。
ALERT_GROUPS = {"alert"}

# L5 预算验收口径（2026-10-10, priority doc §2.4）：
# 「连续 7 天告警群条数 P50<=3 且 P90<=5」→ PASS。口径=告警群 alert（report/功能输出另列,
# 见 ALERT_GROUPS 分离）。分位数=线性插值（numpy.percentile 'linear' 同款, 确定性可机检）。
L5_WINDOW_DAYS = 7
L5_P50_MAX = 3
L5_P90_MAX = 5


def _percentile(vals: list[int] | list[float], p: float) -> float:
    """线性插值分位数（numpy.percentile 'linear'）。空列表 → 0.0（无样本按最保守=0）。"""
    xs = sorted(float(v) for v in vals)
    if not xs:
        return 0.0
    if len(xs) == 1:
        return xs[0]
    rank = (p / 100.0) * (len(xs) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (rank - lo) * (xs[hi] - xs[lo])


# ----------------------------------------------------------------------------
# 树解析（跨两树聚合）
# ----------------------------------------------------------------------------
def resolve_trees(explicit: list[str] | None = None) -> list[Path]:
    """解析要聚合的树根列表（去重、保序、解析符号链接）。

    优先级：--trees 参数 > ALERT_METER_TREES env > 默认（REPO + 兄弟 trade-data /
    trade-data-signal）。默认值使云上「运行树 + 信号树」自动双树聚合，本地开发树
    只有一个也不报错（缺目录自动跳过）。
    """
    if explicit:
        raw = explicit
    elif os.environ.get("ALERT_METER_TREES"):
        raw = os.environ["ALERT_METER_TREES"].split(os.pathsep)
    else:
        cands = [REPO]
        parent = REPO.parent
        for name in ("trade-data", "trade-data-signal"):
            p = parent / name
            if p != REPO and p.is_dir():
                cands.append(p)
        raw = [str(p) for p in cands]

    trees: list[Path] = []
    seen: set[str] = set()
    for r in raw:
        r = str(r).strip()
        if not r:
            continue
        p = Path(r)
        key = str(p.resolve()) if p.exists() else str(p)
        if key in seen:
            continue
        seen.add(key)
        trees.append(p)
    return trees


def ledger_path(tree: Path) -> Path:
    return tree / "data" / "alerts" / LEDGER_FILENAME


def daily_path(tree: Path) -> Path:
    return tree / "data" / "alerts" / DAILY_FILENAME


# ----------------------------------------------------------------------------
# 读台账
# ----------------------------------------------------------------------------
def _iter_records(trees: list[Path]):
    """产出所有树台账里的记录（坏行 best-effort 跳过，不静默丢整文件）。"""
    for tree in trees:
        p = ledger_path(tree)
        if not p.exists():
            continue
        try:
            with open(p, encoding="utf-8") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        rec = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(rec, dict) and rec.get("ts"):
                        yield rec
        except OSError as e:
            print(f"[alert_meter] 读取台账失败(跳过该树)：{p}: {e}", file=sys.stderr)


def _date_of(rec: dict) -> str:
    return str(rec.get("ts", ""))[:10]


def load_day(trees: list[Path], day: str) -> list[dict]:
    return [r for r in _iter_records(trees) if _date_of(r) == day]


# ----------------------------------------------------------------------------
# 聚合（幂等）
# ----------------------------------------------------------------------------
def aggregate(records: list[dict]) -> dict:
    by_tier: Counter = Counter()
    by_source: Counter = Counter()
    by_key: Counter = Counter()
    by_group: Counter = Counter()
    merged_in_digest = 0
    for r in records:
        by_tier[str(r.get("tier") or "notice")] += 1
        by_source[str(r.get("source") or "unknown")] += 1
        by_key[str(r.get("key") or "unknown")] += 1
        by_group[str(r.get("group") or "unknown")] += 1
        try:
            merged_in_digest += int(r.get("merged_count") or 0)
        except (TypeError, ValueError):
            pass
    return {
        "total": len(records),
        "by_tier": dict(sorted(by_tier.items())),
        "by_source": dict(sorted(by_source.items())),
        "by_key": dict(sorted(by_key.items())),
        "by_group": dict(sorted(by_group.items())),
        "merged_in_digest": merged_in_digest,
    }


def alert_count(agg: dict) -> int:
    """告警群口径条数（group 属于 ALERT_GROUPS）。"""
    return sum(v for g, v in agg["by_group"].items() if g in ALERT_GROUPS)


def severe_count(agg: dict) -> int:
    return int(agg["by_tier"].get("critical", 0))


def build_daily(trees: list[Path], day: str) -> dict:
    """幂等构建某日的 alert_daily 内容（无墙钟时间戳 ⇒ 同输入两次逐位一致）。"""
    agg = aggregate(load_day(trees, day))
    return {
        "date": day,
        "total": agg["total"],
        "by_tier": agg["by_tier"],
        "by_source": agg["by_source"],
        "by_key": agg["by_key"],
        "by_group": agg["by_group"],
        "merged_in_digest": agg["merged_in_digest"],
        "trees": sorted(str(t) for t in trees),
    }


def _atomic_write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def recount(trees: list[Path], day: str | None = None) -> dict:
    """幂等重算某一日（默认今日）的 alert_daily.json，写入**每棵树**（§22 一致）。"""
    day = day or date.today().isoformat()
    obj = build_daily(trees, day)
    written = []
    for t in trees:
        try:
            _atomic_write_json(daily_path(t), obj)
            written.append(str(daily_path(t)))
        except OSError as e:
            print(f"[alert_meter] 写日计数失败(跳过该树)：{daily_path(t)}: {e}", file=sys.stderr)
    return {"day": day, "written": written, "daily": obj}


# ----------------------------------------------------------------------------
# 查询
# ----------------------------------------------------------------------------
def _top_talkers(records: list[dict], n: int = 8) -> list[tuple[str, int, str, str]]:
    """(key, count, 样本 subject, source) 按 count 降序。"""
    cnt: Counter = Counter()
    sample: dict[str, tuple[str, str]] = {}
    for r in records:
        k = str(r.get("key") or "unknown")
        cnt[k] += 1
        sample.setdefault(k, (str(r.get("subject") or ""), str(r.get("source") or "")))
    out = []
    for k, c in cnt.most_common(n):
        subj, src = sample.get(k, ("", ""))
        out.append((k, c, subj, src))
    return out


def _daily_totals(trees: list[Path], days: list[str]) -> dict[str, dict]:
    buckets: dict[str, list[dict]] = {d: [] for d in days}
    for r in _iter_records(trees):
        d = _date_of(r)
        if d in buckets:
            buckets[d].append(r)
    return {d: aggregate(buckets[d]) for d in days}


def cmd_today(trees: list[Path], day: str, as_json: bool) -> int:
    agg = aggregate(load_day(trees, day))
    # 前 7 日均值（自然日，不含当日）
    d0 = datetime.strptime(day, "%Y-%m-%d").date()
    prev_days = [(d0 - timedelta(days=i)).isoformat() for i in range(1, 8)]
    prev = _daily_totals(trees, prev_days)
    prev_alert = [alert_count(prev[d]) for d in prev_days]
    avg_alert = round(sum(prev_alert) / len(prev_days), 2) if prev_days else 0.0
    talkers = _top_talkers(load_day(trees, day), 8)
    payload = {
        "date": day,
        "alert": alert_count(agg),
        "severe": severe_count(agg),
        "merged_in_digest": agg["merged_in_digest"],
        "total_all_groups": agg["total"],
        "by_group": agg["by_group"],
        "by_tier": agg["by_tier"],
        "by_source": agg["by_source"],
        "top_talkers": [{"key": k, "count": c, "subject": s, "source": src}
                        for k, c, s, src in talkers],
        "prev7_avg_alert": avg_alert,
        "prev7_days": {d: alert_count(prev[d]) for d in prev_days},
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"今日 {day}：告警群(alert) {payload['alert']} 条"
          f"（severe 直发 {payload['severe']} / 摘要并入 {payload['merged_in_digest']}）"
          f"；全量外发 {payload['total_all_groups']} 条")
    other = {g: v for g, v in agg["by_group"].items() if g not in ALERT_GROUPS}
    if other:
        print(f"  非告警群分布：{', '.join(f'{g}={v}' for g, v in sorted(other.items()))}")
    print(f"  前 7 日均值：{avg_alert} 条/天"
          f"（{', '.join(f'{d}:{alert_count(prev[d])}' for d in prev_days)}）")
    if talkers:
        print("  top talkers：")
        for k, c, s, src in talkers:
            s_short = (s[:60] + "…") if len(s) > 60 else s
            print(f"    {c:>3}× [{k}] {s_short}  (src={src})")
    return 0


def cmd_week(trees: list[Path], end_day: str, as_json: bool) -> int:
    d0 = datetime.strptime(end_day, "%Y-%m-%d").date()
    days = [(d0 - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    per = _daily_totals(trees, days)
    rows = [{"date": d, "alert": alert_count(per[d]), "severe": severe_count(per[d]),
             "merged_in_digest": per[d]["merged_in_digest"], "total_all_groups": per[d]["total"]}
            for d in days]
    alerts = [r["alert"] for r in rows]
    p50 = round(_percentile(alerts, 50), 2)
    p90 = round(_percentile(alerts, 90), 2)
    ok = p50 <= L5_P50_MAX and p90 <= L5_P90_MAX
    if as_json:
        print(json.dumps({"window": [days[0], days[-1]], "rows": rows,
                          "p50": p50, "p90": p90,
                          "criterion": f"P50<={L5_P50_MAX} 且 P90<={L5_P90_MAX}",
                          "pass": ok}, ensure_ascii=False, indent=2))
        return 0
    print(f"近 7 天（{days[0]} ~ {days[-1]}）：")
    print(f"  {'日期':<12}{'告警群':>6}{'severe':>8}{'并入':>6}{'全量':>6}")
    for r in rows:
        print(f"  {r['date']:<12}{r['alert']:>6}{r['severe']:>8}"
              f"{r['merged_in_digest']:>6}{r['total_all_groups']:>6}")
    if alerts:
        print(f"  均值 {round(sum(alerts) / len(alerts), 2)} 条/天（告警群口径）")
    print(f"  P50 {p50} / P90 {p90} 条/天 → {'PASS' if ok else 'FAIL'}"
          f"（L5 判据 连续 {L5_WINDOW_DAYS} 天 P50<={L5_P50_MAX} 且 P90<={L5_P90_MAX}）")
    return 0


def cmd_budget(trees: list[Path], end_day: str, as_json: bool) -> int:
    """L5 验收视图（priority doc §2.4）：近 7 天告警群条数 P50/P90 → PASS/FAIL。

    判据 = 连续 7 天 P50<=3 且 P90<=5（告警群 alert 口径）。纯查询面, 不写任何文件。
    """
    d0 = datetime.strptime(end_day, "%Y-%m-%d").date()
    days = [(d0 - timedelta(days=i)).isoformat() for i in range(L5_WINDOW_DAYS - 1, -1, -1)]
    per = _daily_totals(trees, days)
    counts = [alert_count(per[d]) for d in days]
    p50 = round(_percentile(counts, 50), 2)
    p90 = round(_percentile(counts, 90), 2)
    ok = p50 <= L5_P50_MAX and p90 <= L5_P90_MAX
    payload = {
        "window": [days[0], days[-1]],
        "days": {d: c for d, c in zip(days, counts)},
        "p50": p50, "p90": p90,
        "p50_max": L5_P50_MAX, "p90_max": L5_P90_MAX,
        "criterion": f"连续 {L5_WINDOW_DAYS} 天 P50<={L5_P50_MAX} 且 P90<={L5_P90_MAX}",
        "pass": ok,
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"L5 预算验收（{days[0]} ~ {days[-1]}，告警群口径）：")
    print(f"  逐日：{', '.join(f'{d}:{c}' for d, c in zip(days, counts))}")
    print(f"  P50 = {p50}（判据 <= {L5_P50_MAX}）  P90 = {p90}（判据 <= {L5_P90_MAX}）")
    print(f"  ⇒ {'PASS' if ok else 'FAIL'}（{payload['criterion']}）")
    return 0


def cmd_top(trees: list[Path], n: int, as_json: bool) -> int:
    d0 = date.today()
    days = [(d0 - timedelta(days=i)).isoformat() for i in range(0, 7)]
    recs = [r for r in _iter_records(trees) if _date_of(r) in set(days)]
    talkers = _top_talkers(recs, n)
    if as_json:
        print(json.dumps([{"key": k, "count": c, "subject": s, "source": src}
                          for k, c, s, src in talkers], ensure_ascii=False, indent=2))
        return 0
    print(f"近 7 天 top {n} talkers（全部群口径）：")
    for k, c, s, src in talkers:
        s_short = (s[:70] + "…") if len(s) > 70 else s
        print(f"  {c:>3}× [{k}] {s_short}  (src={src})")
    return 0


# ----------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="告警度量查询面（L1 度量层，跨树聚合）")
    ap.add_argument("--today", action="store_true", help="今日条数 + top talkers + 前 7 日均值对比")
    ap.add_argument("--week", action="store_true", help="近 7 天逐日表 + P50/P90")
    ap.add_argument("--budget", action="store_true",
                    help="L5 验收视图：近 7 天告警群 P50/P90 → PASS/FAIL（连续 7 天 P50<=3 且 P90<=5）")
    ap.add_argument("--top", type=int, nargs="?", const=10, default=None,
                    help="近 7 天 top talkers（默认 10）")
    ap.add_argument("--recount", action="store_true",
                    help="幂等重算 alert_daily.json（写每棵树；巡检每轮末尾/23:30 收尾轮调用）")
    ap.add_argument("--date", default=None, help="指定日期 YYYY-MM-DD（默认今日）")
    ap.add_argument("--trees", default=None,
                    help=f"树根列表（{os.pathsep} 分隔），默认 REPO + 兄弟树")
    ap.add_argument("--json", action="store_true", dest="as_json", help="机读 JSON 输出")
    args = ap.parse_args(argv)

    trees = resolve_trees(args.trees.split(os.pathsep) if args.trees else None)
    day = args.date or date.today().isoformat()

    if args.recount:
        r = recount(trees, args.date)
        print(f"[alert_meter] recount {r['day']}：共 {r['daily']['total']} 条，"
              f"写入 {len(r['written'])} 棵树")
        for w in r["written"]:
            print(f"  {w}")
        return 0

    if args.today:
        return cmd_today(trees, day, args.as_json)
    if args.week:
        return cmd_week(trees, day, args.as_json)
    if args.budget:
        return cmd_budget(trees, day, args.as_json)
    if args.top is not None:
        return cmd_top(trees, args.top, args.as_json)

    # 缺省 = --today
    return cmd_today(trees, day, args.as_json)


if __name__ == "__main__":
    sys.exit(main())