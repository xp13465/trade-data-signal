#!/usr/bin/env python3
"""云上 acc_nav 补数 UPDATE 脚本(只补 acc_nav IS NULL 行, 三层防护)。

用法: python3 /tmp/accnav_update.py <dates_csv> <fix_db_path>
  如: python3 /tmp/accnav_update.py 20260917 /tmp/accnav_fix.db
  只 UPDATE 指定日期的 acc_nav IS NULL 行, 且 fix 表有非空值才补。
  不碰其它列/其它日期。SQL 同调研报告 §4.3 三层防护。
"""
import sqlite3
import sys

DB = "/home/ubuntu/code/trade-data/data/public_fund.db"

dates = [d.strip() for d in sys.argv[1].split(",") if d.strip()]
fix_db = sys.argv[2]

conn = sqlite3.connect(DB)
# ATTACH 不支持参数绑定, fix_db 是受控路径
conn.execute(f"ATTACH DATABASE '{fix_db}' AS fix")
placeholders = ",".join("?" * len(dates))

# 三层防护 UPDATE: ①日期限定 ②只补 acc_nav IS NULL ③fix 表有非空值才补
sql = f"""
UPDATE fund_daily_nav SET acc_nav = (
  SELECT f.acc_nav FROM fix.fix f
  WHERE f.date = fund_daily_nav.date AND f.fund_code = fund_daily_nav.fund_code)
WHERE date IN ({placeholders})
  AND acc_nav IS NULL
  AND EXISTS (SELECT 1 FROM fix.fix f
              WHERE f.date = fund_daily_nav.date AND f.fund_code = fund_daily_nav.fund_code
                AND f.acc_nav IS NOT NULL)
"""
cur = conn.execute(sql, dates)
conn.commit()
print(f"UPDATE done: {cur.rowcount} rows, dates={dates}", flush=True)

# 对账: 更新后各日期 acc_nav 非空行数
rows = conn.execute(
    "SELECT date, SUM(acc_nav IS NOT NULL), COUNT(*) FROM fund_daily_nav "
    f"WHERE date IN ({placeholders}) GROUP BY date ORDER BY date",
    dates,
).fetchall()
for r in rows:
    print(f"  {r[0]}: acc_nav有值={r[1]} / total={r[2]}")
conn.execute("DETACH DATABASE fix")
conn.close()
