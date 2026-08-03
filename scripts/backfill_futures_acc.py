"""一次性 backfill：逐日回算 compute_role_ih_detail 的15日窗口同向准确度，
写入 futures_ih_detail_acc 表（每日每角色一行）。

追踪 follow_ratio = same_count/total*100 的历史趋势，识别"同向越来越不准=风格转逆向"。
INSERT OR REPLACE 按 (date, role) 去重，重跑幂等不重复。

数据源：futures_position(IH/IF/IC/IM, long_chg/short_chg, 20240102-)+index_daily(sh close)。
回溯日期：从 20240110 起（前7个交易日做窗口预热），逐日回算 as_of_date 当天的15日窗口快照。

运行：cd /Users/linhuichen/code/trade-data && /Users/linhuichen/code/trade/.venv/bin/python /Users/linhuichen/code/trade/scripts/backfill_futures_acc.py
"""
import sys
from pathlib import Path

# 必须从 trade-data 侧 import app（trade-data/app 是指向 trade/app 的 symlink），
# 这样 app/db.py 的 __file__ 解析为 trade-data/app/db.py，
# DB_PATH = trade-data/data/sentiment.db (主库)。
TRADE_DATA = Path("/Users/linhuichen/code/trade-data")
sys.path.insert(0, str(TRADE_DATA))

from app.db import get_conn  # noqa: E402
from app.compute.futures_position import compute_role_ih_detail, record_ih_detail_acc  # noqa: E402


ROLES = [
    ("中信期货", "中信期货"),
    ("top20", "机构前20"),
    ("国泰君安", "国泰君安"),
]
START_DATE = "20240110"


def main():
    conn = get_conn()
    # 取所有可用快照日期：futures_position 有 IH/IF/IC/IM 四品种齐全且有 long_chg 的日期
    rows = conn.execute(
        "SELECT DISTINCT date FROM futures_position "
        "WHERE variety IN ('IH','IF','IC','IM') AND long_chg IS NOT NULL "
        "AND date >= ? ORDER BY date",
        (START_DATE,),
    ).fetchall()
    dates = [r["date"] for r in rows]
    print(f"=== backfill futures_ih_detail_acc: {len(dates)} 个日期 ({dates[0]}~{dates[-1]}) ===")

    total_written = 0
    skipped = 0
    for i, d in enumerate(dates):
        for role_key, role_label in ROLES:
            try:
                result = compute_role_ih_detail(role=role_key, n_days=15, as_of_date=d)
            except Exception as e:  # noqa: BLE001
                print(f"  [{d}] {role_label} compute 异常: {e}")
                skipped += 1
                continue
            if not result or not result.get("total"):
                skipped += 1
                continue
            ok = record_ih_detail_acc(role=role_key, result=result, conn=conn)
            if ok:
                total_written += 1
        # 每50个日期 commit 一次 + 进度输出
        if (i + 1) % 50 == 0 or i == len(dates) - 1:
            conn.commit()
            print(f"  进度 {i+1}/{len(dates)} ({d})，累计写入 {total_written} 行")
    conn.commit()
    conn.close()

    # 验收
    conn2 = get_conn()
    cnt = conn2.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM futures_ih_detail_acc").fetchone()
    by_role = conn2.execute(
        "SELECT role, COUNT(*), MIN(date), MAX(date) FROM futures_ih_detail_acc GROUP BY role"
    ).fetchall()
    conn2.close()
    print(f"\n=== backfill 完成: 写入 {total_written} 行 (skip {skipped}) ===")
    print(f"  总计: {cnt[0]} 行, 日期范围 {cnt[1]}~{cnt[2]}")
    for r in by_role:
        print(f"  {r[0]}: {r[1]} 行, {r[2]}~{r[3]}")


if __name__ == "__main__":
    main()
