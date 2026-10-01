#!/usr/bin/env python3
"""a_sentiment 影响实测:回补 lianban 前后各算一遍 a_sentiment,对比差异。

P2-5:注入 lianban 复用 `app.backfill_lianban._upsert`(消灭第二份手抄 SQL,§5.4⑦)。

用法(在仓库根运行,以便 import app):
  /Users/linhuichen/code/trade/.venv/bin/python /tmp/lianban_dryrun/sent_impact.py \
      --prod /tmp/lianban_dryrun/prod_sentiment_copy.db \
      --rows /tmp/lianban_dryrun/full_dryrun.json \
      --work /tmp/lianban_dryrun
"""
import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path

from app.backfill_lianban import _upsert


def run_sentiment(db_path: Path):
    """在指定库上重算并写入 score_daily.a_sentiment,返回写行数。"""
    import app.db as dbmod
    dbmod.DB_PATH = Path(db_path)
    dbmod._schema_ensured = False  # 强制对新路径做 schema 幂等检查
    from app.compute import sentiment
    score, comps = sentiment.compute()
    n = sentiment.store(score, comps)
    return n


def inject_lianban(db_path: Path, rows: list[dict]):
    """把回补 (date,value) upsert 进库 —— 复用 app.backfill_lianban._upsert(P2-5,
    消灭第二份手抄 SQL)。_upsert 内嵌 manual 保护(WHERE source != 'manual')。
    这里逐行调用(替代 executemany),与 verify 脚本同源同实现。"""
    conn = sqlite3.connect(db_path, timeout=30.0)
    for r in rows:
        _upsert(conn, r["date"], float(r["value"]))
    conn.commit()
    n = len(rows)
    conn.close()
    return n


def read_score(db_path: Path) -> dict[str, dict]:
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT date, value, is_freeze, is_overheat FROM score_daily "
        "WHERE score_id='a_sentiment' ORDER BY date"
    ).fetchall()
    conn.close()
    return {r["date"]: {"value": r["value"], "is_freeze": r["is_freeze"],
                        "is_overheat": r["is_overheat"]} for r in rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prod", required=True)
    ap.add_argument("--rows", required=True, help="backfill_lianban --out 的 JSON")
    ap.add_argument("--work", required=True, help="工作目录")
    args = ap.parse_args()

    work = Path(args.work)
    before_db = work / "sent_before.db"
    after_db = work / "sent_after.db"
    # 重新拷贝,保证干净
    shutil.copyfile(args.prod, before_db)
    shutil.copyfile(args.prod, after_db)

    data = json.load(open(args.rows))
    rows = data.get("computed") or []
    print(f"注入回补 lianban {len(rows)} 天到 after 库", flush=True)
    inj = inject_lianban(after_db, rows)
    print(f"注入行数(executemany 生效): {inj}", flush=True)

    n_before = run_sentiment(before_db)
    print(f"before 库重算 a_sentiment 写入 {n_before} 行", flush=True)
    n_after = run_sentiment(after_db)
    print(f"after 库重算 a_sentiment 写入 {n_after} 行", flush=True)

    b = read_score(before_db)
    a = read_score(after_db)
    all_dates = sorted(set(b) | set(a))

    # 对比
    diffs = []
    freeze_flips = []
    for d in all_dates:
        bv = b.get(d)
        av = a.get(d)
        # 仅对比两个库都有的日期
        if bv is None or av is None:
            continue
        delta = round(av["value"] - bv["value"], 4) if (bv["value"] is not None and av["value"] is not None) else None
        if delta is not None and abs(delta) > 1e-9:
            diffs.append({"date": d, "before": bv["value"], "after": av["value"], "delta": delta})
        # is_freeze 翻转
        bf = bool(bv["is_freeze"]) if bv["is_freeze"] is not None else None
        af = bool(av["is_freeze"]) if av["is_freeze"] is not None else None
        if bf is not None and af is not None and bf != af:
            freeze_flips.append({"date": d, "before_freeze": bf, "after_freeze": af,
                                 "before_val": bv["value"], "after_val": av["value"]})

    print(f"\n===== a_sentiment 影响对比(共对比 {len(all_dates)} 个日期) =====")
    # 今日值
    today = max(all_dates)
    tv_b = b.get(today)
    tv_a = a.get(today)
    if tv_b and tv_a:
        print(f"今日({today}): before={tv_b['value']} after={tv_a['value']} "
              f"delta={round(tv_a['value']-tv_b['value'],4)} "
              f"freeze={tv_b['is_freeze']}->{tv_a['is_freeze']}")

    # 近 60 交易日
    recent = all_dates[-60:]
    recent_diffs = [x for x in diffs if x["date"] in set(recent)]
    print(f"近 60 交易日:变了 {len(recent_diffs)} 天")
    if recent_diffs:
        deltas = [x["delta"] for x in recent_diffs]
        print(f"  最大变化(绝对值): {max(abs(x) for x in deltas):.4f} (在 {[x['date'] for x in recent_diffs if abs(x['delta'])==max(abs(d) for d in deltas)]})")
        print(f"  变化分布: min={min(deltas):.4f} max={max(deltas):.4f} mean={sum(deltas)/len(deltas):.4f}")

    # 全段差异统计
    print(f"\n全段:共变 {len(diffs)} 天(占 {len(all_dates)} 天)")
    if diffs:
        deltas = [x["delta"] for x in diffs]
        print(f"  delta min={min(deltas):.4f} max={max(deltas):.4f} mean={sum(deltas)/len(deltas):.4f}")
        # 绝对值最大的前 10 天
        top = sorted(diffs, key=lambda x: abs(x["delta"]), reverse=True)[:10]
        print("  绝对值最大前10天:")
        for x in top:
            print(f"    {x['date']}: {x['before']} -> {x['after']} (delta={x['delta']:+.4f})")

    print(f"\nis_freeze 翻转:{len(freeze_flips)} 天")
    for x in freeze_flips:
        print(f"  {x['date']}: freeze {x['before_freeze']}->{x['after_freeze']} "
              f"(val {x['before_val']}->{x['after_val']})")

    # 落盘对比明细
    out = work / "sent_impact.json"
    json.dump({
        "today": {"date": today,
                  "before": tv_b.get("value") if tv_b else None,
                  "after": tv_a.get("value") if tv_a else None,
                  "before_freeze": tv_b.get("is_freeze") if tv_b else None,
                  "after_freeze": tv_a.get("is_freeze") if tv_a else None},
        "recent60_changed_days": len(recent_diffs),
        "recent60_max_abs_delta": max((abs(x["delta"]) for x in recent_diffs), default=None),
        "all_changed_days": len(diffs),
        "freeze_flips": freeze_flips,
        "top_deltas": [{k: (v if k == "date" else v) for k, v in x.items()} for x in top],
    }, open(out, "w"), ensure_ascii=False, indent=2, default=str)
    print(f"\n影响明细已写 {out}")


if __name__ == "__main__":
    main()
