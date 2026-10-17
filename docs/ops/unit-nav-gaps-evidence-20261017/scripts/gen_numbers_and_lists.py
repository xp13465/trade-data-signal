#!/usr/bin/env python3
"""#260 F1 复算脚本:从扫描产物复算主报告全部数字,并生成四份名单(幂等,可离线跑)。

用法:
  python3 gen_numbers_and_lists.py                       # 输入取同目录 ../inputs,输出到同目录 ..
  python3 gen_numbers_and_lists.py --dir /tmp/navscan --out /tmp/out

口径(与主报告一致,勿改):
  691  = |NULL(20261013) ∩ NULL(20261009)|
  2073 = |NULL(1012) ∩ NULL(1013) ∩ NULL(1014) ∩ NULL(1015)|
  31   = 入库以来 unit_nav 从未非空的基金(funds.csv 中 nu==0)
"""
import argparse
import csv
import gzip
import os
import shutil
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
WIN = ("20261012", "20261013", "20261014", "20261015")


def op_maybe_gz(p):
    return gzip.open(p, "rt", encoding="utf-8") if p.endswith(".gz") else open(p, encoding="utf-8")


def rd(d, name):
    for cand in (os.path.join(d, name), os.path.join(d, name + ".gz")):
        if os.path.exists(cand):
            return list(csv.DictReader(op_maybe_gz(cand)))
    raise SystemExit("missing input: %s in %s" % (name, d))


def load(d, name):
    for cand in (os.path.join(d, name), os.path.join(d, name + ".gz")):
        if os.path.exists(cand):
            with op_maybe_gz(cand) as f:
                return set(x.strip() for x in f if x.strip())
    raise SystemExit("missing input: %s in %s" % (name, d))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(HERE, "..", "inputs"))
    ap.add_argument("--out", default=os.path.join(HERE, ".."))
    a = ap.parse_args()
    D, OUT = a.dir, a.out
    os.makedirs(OUT, exist_ok=True)

    daily = rd(D, "daily.csv")
    funds = {r["fund_code"]: r for r in rd(D, "funds.csv")}
    basic = {r["fund_code"]: r for r in rd(D, "fund_basic.csv")}
    n = {d: load(D, "nulls_2026%s.txt" % d) for d in ("1008", "1009", "1012", "1013", "1014", "1015")}
    g691 = n["1013"] & n["1009"]
    persist = n["1012"] & n["1013"] & n["1014"] & n["1015"]
    never = set(c for c, r in funds.items() if r["nu"] == "0")
    s220 = rd(D, "rand220.csv")

    def kind(r):
        if r["in_window"] in ("ERR", ""):
            return "X"
        return "G" if int(r["in_window"]) >= 1 else "OK"

    print("=== 口径 A:日级 NULL 占比 ===")
    print("  覆盖日数=%d  行区间=%s..%s" % (len(daily), daily[0]["date"], daily[-1]["date"]))
    print("  100%% NULL 日=%d   >=95%% NULL 日=%d" % (
        sum(1 for r in daily if int(r["nul"]) == int(r["n"])),
        sum(1 for r in daily if int(r["n"]) > 0 and int(r["nul"]) / int(r["n"]) >= 0.95)))
    top = max(daily, key=lambda r: int(r["nul"]) / int(r["n"]))
    print("  最高 NULL 日=%s  %s/%s=%.2f%%" % (top["date"], top["nul"], top["n"],
                                            100 * int(top["nul"]) / int(top["n"])))
    for r in daily:
        if r["date"] >= "20261008":
            print("    %s %s/%s=%.2f%%" % (r["date"], r["nul"], r["n"], 100 * int(r["nul"]) / int(r["n"])))

    print("=== 口径 B / C / 名单 ===")
    print("  691  = %d(其中落在 2073 内 %d)" % (len(g691), len(g691 & persist)))
    print("  2073 = %d" % len(persist))
    print("  31   = %d(其中在四日窗口内 %d)" % (len(never), len(never & persist)))
    print("  691 类型 top5:", Counter((basic.get(c) or {}).get("fund_type", "?") for c in g691).most_common(5))

    print("=== 分层(220 抽样,seed 260260) ===")
    cc = Counter(kind(r) for r in s220)
    print("  G(采集缺口)=%d(%.1f%%)  OK(可接受)=%d(%.1f%%)  X(未核)=%d(%.1f%%)" % (
        cc["G"], 100 * cc["G"] / len(s220), cc["OK"], 100 * cc["OK"] / len(s220),
        cc["X"], 100 * cc["X"] / len(s220)))
    print("  外推:层1 ≈ %.0f 只 / 层2 ≈ %.0f 只" % (cc["G"] * len(persist) / len(s220),
                                                cc["OK"] * len(persist) / len(s220)))
    ok = [r for r in s220 if r["db_nu"] != "0" and kind(r) == "OK"]
    print("  层2 中 up_last 分布:", Counter(r["up_last"] for r in ok).most_common(5))

    with open(os.path.join(OUT, "never_valued_since_intake_31.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["fund_code", "fund_name", "fund_type", "db_rows", "in_4d_window_1012_1015"])
        for c in sorted(never):
            w.writerow([c, funds[c]["fund_name"], (basic.get(c) or {}).get("fund_type", ""), funds[c]["n"],
                        "Y" if c in persist else "N"])
    with open(os.path.join(OUT, "persistent_gap_4d_2073.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["fund_code", "fund_name", "fund_type", "db_nonnull_unit_nav_rows", "db_last_nonnull_date"])
        for c in sorted(persist):
            w.writerow([c, funds.get(c, {}).get("fund_name", ""), (basic.get(c) or {}).get("fund_type", ""),
                        funds.get(c, {}).get("nu", ""), funds.get(c, {}).get("last_nu", "")])
    with gzip.open(os.path.join(OUT, "persistent_gap_4d_2073.csv.gz"), "wb", 9) as fo, \
            open(os.path.join(OUT, "persistent_gap_4d_2073.csv"), "rb") as fi:
        shutil.copyfileobj(fi, fo)
    os.remove(os.path.join(OUT, "persistent_gap_4d_2073.csv"))
    with open(os.path.join(OUT, "gap_691_1013_and_1009.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["fund_code", "fund_name", "fund_type", "db_nonnull_unit_nav_rows",
                    "db_last_nonnull_date", "in_4d_window_1012_1015"])
        for c in sorted(g691):
            w.writerow([c, funds.get(c, {}).get("fund_name", ""), (basic.get(c) or {}).get("fund_type", ""),
                        funds.get(c, {}).get("nu", ""), funds.get(c, {}).get("last_nu", ""),
                        "Y" if c in persist else "N"])
    with open(os.path.join(OUT, "sample_220_upstream_verify.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["fund_code", "fund_type", "db_nonnull_rows", "db_last_nonnull_date",
                    "upstream_last_nav_date", "upstream_values_in_1012_1015", "layer"])
        for r in s220:
            w.writerow([r["fund_code"], r["fund_type"], r["db_nu"], r["db_last_nu"],
                        r["up_last"], r["in_window"], kind(r)])
    print("名单已写入 %s" % os.path.abspath(OUT))


if __name__ == "__main__":
    main()