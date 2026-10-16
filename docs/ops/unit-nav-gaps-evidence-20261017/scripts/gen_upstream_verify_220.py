#!/usr/bin/env python3
"""#260 F1 分层判定脚本:对「四日全空」集合做**随机抽样**,用上游官方历史净值判定层1/层2。

判定源:东财逐只基金历史序列 `http://fund.eastmoney.com/pingzhongdata/<code>.js`
        (字段 `Data_netWorthTrend`,元素 x = 净值日期的毫秒时间戳,**按北京时间 +8h 换算**)。
判据(窗口固定):|该基金净值日期集合 ∩ {20261012,20261013,20261014,20261015}| >= 1 ⇒ G(采集缺口);
                = 0 ⇒ OK(可接受);序列取不到/为空 ⇒ X(原因未核)。

抽样:random.seed(260260) + random.sample(sorted(persist), 220) —— 固定种子,任何人可逐位复算。
产出:rand220.csv(fund_code,fund_type,db_nu,db_last_nu,up_last,in_window)

用法:python3 gen_upstream_verify_220.py --dir ../inputs [--n 220] [--sleep 0.2]
需网络(逐只抓,220 只约 90~120s,按每只 sleep 0.2s 限速)。
"""
import argparse
import csv
import datetime
import json
import os
import random
import re
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WIN = {"20261012", "20261013", "20261014", "20261015"}


def load(d, name):
    with open(os.path.join(d, name), encoding="utf-8") as f:
        return set(x.strip() for x in f if x.strip())


def rd(d, name):
    with open(os.path.join(d, name), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def upnav(code, timeout=20):
    try:
        req = urllib.request.Request("http://fund.eastmoney.com/pingzhongdata/%s.js" % code,
                                     headers={"User-Agent": "Mozilla/5.0"})
        t = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")
        m = re.search(r"Data_netWorthTrend = (\[.*?\]);", t)
        if not m:
            return None, None
        a = json.loads(m.group(1))
        if not a:
            return None, None
        ds = [datetime.datetime.utcfromtimestamp(x["x"] / 1000 + 8 * 3600).strftime("%Y%m%d") for x in a]
        return max(ds), len(WIN & set(ds))
    except Exception:
        return "ERR", "ERR"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(HERE, "..", "inputs"))
    ap.add_argument("--out", default=os.path.join(HERE, ".."))
    ap.add_argument("--n", type=int, default=220)
    ap.add_argument("--sleep", type=float, default=0.2)
    a = ap.parse_args()
    D = a.dir
    persist = load(D, "nulls_20261012.txt") & load(D, "nulls_20261013.txt") \
        & load(D, "nulls_20261014.txt") & load(D, "nulls_20261015.txt")
    basic = {r["fund_code"]: r for r in rd(D, "fund_basic.csv")}
    funds = {r["fund_code"]: r for r in rd(D, "funds.csv")}
    random.seed(260260)
    sample = random.sample(sorted(persist), a.n)
    print("persist=%d  sample=%d  seed=260260" % (len(persist), len(sample)), flush=True)
    outp = os.path.join(a.out, "rand220.csv")
    with open(outp, "w", newline="") as out:
        w = csv.writer(out)
        w.writerow(["fund_code", "fund_type", "db_nu", "db_last_nu", "up_last", "in_window"])
        for i, c in enumerate(sample, 1):
            v = funds.get(c, {})
            ul, iw = upnav(c)
            w.writerow([c, (basic.get(c) or {}).get("fund_type", ""), v.get("nu", ""), v.get("last_nu", ""), ul, iw])
            out.flush()
            time.sleep(a.sleep)
            if i % 40 == 0:
                print("done", i, flush=True)
    print("WROTE", outp)


if __name__ == "__main__":
    main()