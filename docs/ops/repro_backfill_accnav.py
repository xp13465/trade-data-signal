#!/usr/bin/env python3
"""复现段/准备脚本: 天天基金全量拉累计净值走势 -> 生成 acc_nav 补数中间表。

来源: accnav-backfill-0923-0924-20261003.md §4.2(9-17/21/23/24 acc_nav 补数, 2026-10-03)。
背景: 2026-10-02 stage0-nav 二轮 INSERT OR REPLACE 把 9-17/21/23/24 acc_nav 从 88646 清到 123
(审计 docs/ops/fund-nav-accnav-clobber-audit-20261002.md)。9-23/9-24 无现成快照
(R2 旧 fund_nav/ 9-22 已上传, 当时无这两日), 唯一来源 = 天天基金累计净值走势接口重取。
本脚本即全量拉取器: 本机跑, 只读天天基金 + 写输出 db, 零生产触碰。

用法(实施侧, 需主控授权)：
  GIT_REPO=/Users/linhuichen/code/trade python3 docs/ops/repro_backfill_accnav.py \
    --dates 20260917,20260921,20260923,20260924 --out /tmp/accnav_fix.db
  # 调试: --limit 5  只拉前 5 只
  # 顺带补 9-28/29/30(主控拍板): --dates 20260917,20260921,20260923,20260924,20260928,20260929,20260930

输出: --out 指定 sqlite 文件, 表 fix(date TEXT, fund_code TEXT, acc_nav REAL, PRIMARY KEY(date,fund_code))。
  行 = 目标日期 acc_nav 非 null 的唯一 (date, fund_code)。
  预期 ~2.2万/日(货币基金等无累计净值披露的基金无行, 正常)。

对账(实施侧必做, §5.4⑦ 同构对账精神):
  000001 目标日值 vs R2 旧快照 fund_nav/000001.json(9-17=3.871/9-21=3.905)逐位一致;
  与云上主库 UPDATE 后 SELECT 抽样逐位一致。
"""
import argparse
import json
import os
import sqlite3
import sys
import time

import akshare as ak

OUT_FLAT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts")
sys.path.insert(0, OUT_FLAT)


def list_fund_codes(limit=0):
    import upload_r2
    import xml.etree.ElementTree as ET
    NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
    keys, ct, n = [], None, 0
    while True:
        q = "list-type=2&max-keys=1000&prefix=fund_nav/"
        if ct:
            q += "&continuation-token=" + ct
        r = upload_r2.s3_request("GET", "", query=q, bucket="signal-data")
        body = r[1].decode("utf-8") if isinstance(r[1], bytes) else r[1]
        root = ET.fromstring(body)
        keys += [e.find("s3:Key", NS).text for e in root.findall(".//s3:Contents", NS)]
        tok = root.find(".//s3:NextContinuationToken", NS)
        if tok is None:
            break
        ct = tok.text
        n += 1
        if n > 100:
            raise RuntimeError("翻页过多")
    codes = sorted(k.split("/")[-1].replace(".json", "") for k in keys)
    return codes[:limit] if limit else codes


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", default="20260917,20260921,20260923,20260924", help="目标日期逗号分隔 YYYYMMDD")
    ap.add_argument("--out", default="/tmp/accnav_fix.db")
    ap.add_argument("--limit", type=int, default=0, help="仅前 N 只(调试)")
    ap.add_argument("--codes", default="", help="指定 code 列表(覆盖 R2 key 集)")
    ap.add_argument("--progress", default="/tmp/accnav_fix_progress.json", help="断点续传进度文件")
    args = ap.parse_args()

    dates = [d.strip() for d in args.dates.split(",") if d.strip()]
    conn = sqlite3.connect(args.out)
    conn.execute("CREATE TABLE IF NOT EXISTS fix(date TEXT, fund_code TEXT, acc_nav REAL, PRIMARY KEY(date, fund_code))")

    done_set = set()
    if os.path.exists(args.progress):
        try:
            done_set = set(json.load(open(args.progress)))
        except Exception:
            done_set = set()
    codes = [c.strip() for c in args.codes.split(",") if c.strip()] if args.codes else list_fund_codes(args.limit)
    print(f"目标 {len(codes)} 只, 日期 {dates}, 已完成 {len(done_set)} 只", flush=True)

    t0 = time.time()
    ok = skip = fail = 0
    for i, code in enumerate(codes, 1):
        if code in done_set:
            skip += 1
            continue
        try:
            df = ak.fund_open_fund_info_em(symbol=code, indicator="累计净值走势")
            if df is None or len(df) == 0:
                fail += 1
            else:
                rows = []
                for _, r in df.iterrows():
                    d0 = str(r.get("净值日期", ""))
                    d = "".join(d0.split("-")) if "-" in d0 else d0
                    if d in dates:
                        acc = r.get("累计净值")
                        if acc is not None:
                            rows.append((d, code, float(acc)))
                if rows:
                    conn.executemany("INSERT OR IGNORE INTO fix VALUES (?,?,?)", rows)
                    conn.commit()
                ok += 1
        except Exception as e:
            fail += 1
            if fail <= 3:
                print(f"  {code} 异常: {type(e).__name__} {e}", flush=True)
        done_set.add(code)
        if i % 500 == 0 or len(done_set) % 500 == 0:
            json.dump(sorted(done_set), open(args.progress, "w"))
            print(f"  [{i}/{len(codes)}] ok={ok} skip={skip} fail={fail} elapsed={time.time()-t0:.0f}s", flush=True)
        time.sleep(0.3)
    json.dump(sorted(done_set), open(args.progress, "w"))

    n_fix = conn.execute("SELECT COUNT(*) FROM fix").fetchone()[0]
    by_date = conn.execute("SELECT date, COUNT(*) FROM fix GROUP BY date ORDER BY date").fetchall()
    print(f"完成 {len(codes)} 只: ok={ok} skip={skip} fail={fail} 中间表行数={n_fix}")
    print("  按日期:", by_date)
    print(f"  输出: {args.out}  (上传云上后按报告 §4.3 UPDATE)")


if __name__ == "__main__":
    main()
