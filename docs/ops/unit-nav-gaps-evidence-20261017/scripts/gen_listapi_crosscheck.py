#!/usr/bin/env python3
"""#260 F1 独立交叉验证:用**采集器同一个端点**(akshare `fund_open_fund_daily_em`,即东财
Fund_JJJZ_Data.aspx 列表接口)做全量回查,并验证其「<日期>-单位净值」列是**日期语义**。

两段:
  [A] 全量:对「四日全空」2073 只,数列表接口两列(最新日 / 次新日)各有几只非空。
  [B] 语义判据:拿 220 抽样的已知 pingzhongdata 结果分组对账,证明该列 = 该基金该日净值
      (而非「该基金最新净值」),否则 [A] 的计数不能当证据。

产出:listapi_persist_20261017.csv(fund_code,fund_name,u_<d>...,a_<d>...)
用法:python3 gen_listapi_crosscheck.py --dir ../inputs --out ..
需网络 + akshare(与生产同版本 1.18.64);运行日不同则列名日期随之变(脚本自动取列,不写死)。
"""
import argparse
import csv
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))


def load(d, name):
    with open(os.path.join(d, name), encoding="utf-8") as f:
        return set(x.strip() for x in f if x.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(HERE, "..", "inputs"))
    ap.add_argument("--out", default=os.path.join(HERE, ".."))
    a = ap.parse_args()
    D = a.dir
    import akshare as ak
    persist = load(D, "nulls_20261012.txt") & load(D, "nulls_20261013.txt") \
        & load(D, "nulls_20261014.txt") & load(D, "nulls_20261015.txt")
    df = ak.fund_open_fund_daily_em()
    unit, acc = {}, {}
    for c in df.columns:
        s = str(c)
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})-单位净值$", s)
        if m:
            unit["".join(m.groups())] = s
            continue
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})-累计净值$", s)
        if m:
            acc["".join(m.groups())] = s
    ds = sorted(unit, reverse=True)
    print("[A] 列表接口日期列 =", ds, " df rows =", len(df), " persist =", len(persist))
    df["_code"] = df["基金代码"].astype(str)
    sub = df[df["_code"].isin(persist)].copy()
    print("    persist 命中 =", len(sub))

    def ne(col):
        s = sub[col].astype(str).str.strip()
        return int((s.ne("") & s.ne("nan") & s.ne("None")).sum())

    for d in ds:
        print("    列 %s-单位净值 非空 = %d   累计净值 非空 = %d" % (
            d, ne(unit[d]), ne(acc[d]) if d in acc else -1))

    with open(os.path.join(a.out, "listapi_persist_20261017.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["fund_code", "fund_name"] + ["u_" + d for d in ds] + ["a_" + d for d in ds])
        for _, r in sub.iterrows():
            w.writerow([r["_code"], r["基金简称"]] + [str(r[unit[d]]).strip() for d in ds]
                       + [str(r[acc[d]]).strip() if d in acc else "" for d in ds])

    print("[B] 语义判据(按抽样结果分组,列表接口两列非空数)")
    sm = list(csv.DictReader(open(os.path.join(a.out, "rand220.csv"), encoding="utf-8")))
    li = {r["fund_code"]: r for r in csv.DictReader(open(os.path.join(a.out, "listapi_persist_20261017.csv"),
                                                         encoding="utf-8"))}
    groups = {}
    for r in sm:
        k = ("X" if r["in_window"] in ("ERR", "") else ("G" if int(r["in_window"]) >= 1 else "OK"), r["up_last"])
        groups.setdefault(k, []).append(r)
    for k in sorted(groups):
        rs = groups[k]
        c = [sum(1 for r in rs if li.get(r["fund_code"], {}).get("u_" + d, "") not in ("", "nan")) for d in ds]
        print("    %s up_last=%-9s n=%-4d 非空数 %s" % (k[0], k[1] or "-", len(rs), c))


if __name__ == "__main__":
    main()