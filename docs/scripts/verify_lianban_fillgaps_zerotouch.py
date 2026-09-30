#!/usr/bin/env python3
"""逐行零触碰证明:把「只补缺口」dry-run 计划写入行重放到副本库,
逐行对比 副本 vs 原始,证明除新增缺口行外(metric+date 键级)零变化。

计划写入行来自 dry-run 落盘 json:computed(全量 date→value)∩ increment_dates
(=planned 缺口集合)。不独立重算 value,只重放 dry-run 已判定的计划写,i无第二
份判定逻辑 → drift 面最小。

用法:
  python3 verify_zerotouch.py <plan_json> <src_db> <dst_db>
"""
import datetime as _dt
import json
import shutil
import sqlite3
import sys

METRIC = "a_width_max_lianban"


def planned_rows(data):
    """从落盘 json 恢复「计划写入」行:(date,value) ∈ computed 且 date ∈ increment_dates。"""
    inc = set(data.get("increment_dates", []))
    cmap = {r["date"]: r["value"] for r in data.get("computed", [])}
    rows = [{"date": d, "value": cmap[d]} for d in sorted(inc) if d in cmap]
    # 校验守恒:计划写入数须与 json.planned_write 一致
    assert len(rows) == data.get("planned_write"), \
        f"恢复行数 {len(rows)} != planned_write {data.get('planned_write')}"
    return rows


def key_map(conn):
    """(metric_id,date) -> (value,source)"""
    return {(r[0], r[1]): (r[2], r[3]) for r in conn.execute(
        "SELECT metric_id,date,value,source FROM daily_metric")}


def main():
    plan, src, dst = sys.argv[1], sys.argv[2], sys.argv[3]
    data = json.load(open(plan, encoding="utf-8"))
    rows = planned_rows(data)
    print(f"计划写入行数={len(rows)}(应=planned_write {data['planned_write']})")

    # 1) 重放:副本写库(与 app.backfill_lianban._upsert 同 SQL,manual 保护)
    shutil.copy(src, dst)
    conn = sqlite3.connect(dst)
    now = _dt.datetime.now().isoformat()
    for r in rows:
        conn.execute(
            "INSERT INTO daily_metric (date, metric_id, value, source, updated_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(date, metric_id) DO UPDATE SET "
            "value=excluded.value, source=excluded.source, updated_at=excluded.updated_at "
            "WHERE daily_metric.source != 'manual'",
            (r["date"], METRIC, float(r["value"]), "fapi", now))
    conn.commit()

    # 2) 逐行对比
    src_k = key_map(sqlite3.connect(src))
    dst_k = key_map(conn)
    added = sorted(set(dst_k) - set(src_k))
    removed = sorted(set(src_k) - set(dst_k))
    changed = sorted(k for k in set(src_k) & set(dst_k)
                     if abs(src_k[k][0] - dst_k[k][0]) > 1e-9 or src_k[k][1] != dst_k[k][1])

    print(f"src total rows={len(src_k)} | dst total rows={len(dst_k)}")
    print(f"added_rows={len(added)}(应=1154) removed_rows={len(removed)}(应0) changed_rows={len(changed)}(应0)")
    lianban_changed = [k for k in changed if k[0] == METRIC]
    print(f"「现有段」a_width_max_lianban changed(应0=77天逐位零触碰): {len(lianban_changed)}")
    only_lianban_added = all(k[0] == METRIC for k in added)
    print(f"added 全部为 a_width_max_lianban? : {only_lianban_added}")

    ok = (not removed) and (not changed) and only_lianban_added and len(added) == len(rows)
    print("结果:", "PASS 除新增缺口行外全库逐行零变化" if ok else "FAIL 存在差异")
    if not ok:
        for k in added[:3]: print(" ADD", k, dst_k[k])
        for k in changed[:3]: print(" CHG", k, "src=", src_k[k], "dst=", dst_k[k])
        for k in removed[:3]: print(" DEL", k, src_k[k])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())