#!/usr/bin/env python3
"""云上只读扫描:fund_daily_nav 全史「日级 unit_nav NULL 占比」+ 逐日 NULL 基金名单导出。

#260 F1 落档脚本之一(2026-10-17)。

产出(默认 /tmp/navscan/):
  daily.csv       每交易日一行:date,n,nul(行数 / unit_nav 为 NULL 的行数)
  funds.csv       每只基金一行:fund_code,fund_name,n,nu,first_nu,last_nu
                  (n=总行数;nu=unit_nav 非空行数;first_nu/last_nu=首个/末个非空日期)
  fund_basic.csv  fund_basic 表原样全量导出
  nulls_<date>.txt  指定日期的「unit_nav 为 NULL」基金代码,每行一只

用法(云上跑,只读):
  scp scripts/gen_scan_nav_nulls.py ubuntu@122.51.111.173:/tmp/navscan/
  ssh ubuntu@122.51.111.173 "python3 /tmp/navscan/gen_scan_nav_nulls.py"

纪律:必须连**云上权威库**(本机 mac 库是镜像、会陈旧,行数都不同);一律 `mode=ro`;
云上无 sqlite3 CLI,用 python3 标准库 sqlite3。
"""
import csv
import sqlite3
import time
from pathlib import Path

DB = "file:/home/ubuntu/code/trade-data/data/public_fund.db?mode=ro"
OUT = Path("/tmp/navscan")
DATES = ["20261016", "20261015", "20261014", "20261013", "20261012", "20261009", "20261008",
         "20260930", "20260929", "20260928", "20260924", "20260923", "20260922"]

t0 = time.time()
con = sqlite3.connect(DB, uri=True)
cur = con.cursor()
OUT.mkdir(parents=True, exist_ok=True)

with open(OUT / "daily.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["date", "n", "nul"])
    for date, n, nul in cur.execute(
            "SELECT date, count(*), sum(unit_nav IS NULL) FROM fund_daily_nav GROUP BY date ORDER BY date"):
        w.writerow([date, n, nul])
print("daily done %.1fs" % (time.time() - t0), flush=True)

with open(OUT / "funds.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["fund_code", "fund_name", "n", "nu", "first_nu", "last_nu"])
    for code, name, n, nu, fnu, lnu in cur.execute(
            "SELECT fund_code, max(fund_name), count(*), sum(unit_nav IS NOT NULL), "
            "min(CASE WHEN unit_nav IS NOT NULL THEN date END), "
            "max(CASE WHEN unit_nav IS NOT NULL THEN date END) "
            "FROM fund_daily_nav GROUP BY fund_code"):
        w.writerow([code, name, n, nu, fnu or "", lnu or ""])
print("funds done %.1fs" % (time.time() - t0), flush=True)

with open(OUT / "fund_basic.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["fund_code", "fund_name", "fund_type", "setup_date", "scale", "fund_company", "update_date"])
    try:
        rows = cur.execute("SELECT fund_code, fund_name, fund_type, setup_date, scale, fund_company, update_date "
                           "FROM fund_basic").fetchall()
    except sqlite3.OperationalError:
        rows = []
    w.writerows(rows)
print("fund_basic rows=%d" % len(rows), flush=True)

for d in DATES:
    codes = [r[0] for r in cur.execute(
        "SELECT fund_code FROM fund_daily_nav WHERE date=? AND unit_nav IS NULL ORDER BY fund_code", (d,))]
    with open(OUT / ("nulls_%s.txt" % d), "w") as f:
        f.write("\n".join(codes) + "\n")
    print("nulls %s = %d" % (d, len(codes)), flush=True)

con.close()
print("ALLDONE %.1fs" % (time.time() - t0))