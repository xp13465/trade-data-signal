#!/usr/bin/env python3
"""复现段: 从 R2 signal-data 主桶下载旧 `fund_nav/` 前缀全部 per-code JSON(26458 个)。

用途: 补数源核查(fund-nav-accnav-clobber-audit-20261002.md §10/§11)。R2 旧 fund_nav/
前缀是 9-20/9-21/9-22 上传的损坏前快照, 9-22 批 21957 只含 9-17/9-21 acc_nav 有值。

依赖: upload_r2.py(s3_request), 需 GIT_REPO/REPO 环境变量指向 trade/trade-data。
用法:
  GIT_REPO=/Users/linhuichen/code/trade REPO=/Users/linhuichen/code/trade-data \
  python3 docs/ops/repro_download_fundnav_r2.py --out /tmp/fund_nav_r2

输出: /tmp/fund_nav_r2/fund_nav_<code>.json(26458 个)
"""
import argparse
import os
import sys
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "../../scripts"))
import upload_r2  # noqa: E402

NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}


def list_all(prefix: str) -> list[tuple[str, str]]:
    keys = []
    ct = None
    n = 0
    while True:
        q = "list-type=2&max-keys=1000&prefix=" + prefix
        if ct:
            q += f"&continuation-token={ct}"
        r = upload_r2.s3_request("GET", "", query=q, bucket="signal-data")
        body = r[1].decode("utf-8") if isinstance(r[1], bytes) else r[1]
        root = ET.fromstring(body)
        batch = [
            (e.find("s3:Key", NS).text, e.find("s3:LastModified", NS).text)
            for e in root.findall(".//s3:Contents", NS)
        ]
        keys += batch
        tok = root.find(".//s3:NextContinuationToken", NS)
        if tok is None:
            break
        ct = tok.text
        n += 1
        if n > 100:
            raise RuntimeError("翻页过多, 疑似死循环")
    return keys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/fund_nav_r2")
    ap.add_argument("--limit", type=int, default=0, help="仅下载前 N 个(调试), 0=全部")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    keys = list_all("fund_nav/")
    print("fund_nav/ key 数:", len(keys))
    sel = keys[: args.limit] if args.limit else keys
    for i, (k, _lm) in enumerate(sel):
        fname = os.path.basename(k)  # fund_nav_<code>.json → <code>.json
        dst = os.path.join(args.out, fname)
        if os.path.exists(dst):
            continue
        r = upload_r2.s3_request("GET", k, bucket="signal-data")
        with open(dst, "wb") as f:
            f.write(r[1])
        if (i + 1) % 2000 == 0:
            print(f"  已下载 {i+1}/{len(sel)}")
    print("下载完成:", len(sel))


if __name__ == "__main__":
    main()
