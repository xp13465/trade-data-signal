#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""r2_delete_prefix.py — 删除 R2 某桶某前缀下的全部对象(批量 DeleteObjects)。

用途:清理历史遗留前缀(如 B3 fund_nav 桶化后遗留的 signal-data `fund_nav/`)。
配套验证报告:docs/ops/next-steps-b3-verify-20261011.md(清理前 §25 备份核验 PASS)。

安全设计(§25 删除前必备份 + 白名单硬校验):
  1) **默认 dry-run**:不加 --yes 只 LIST + 打印将删对象计数/体积,零写。
  2) **--yes 门控**:显式确认才真删。
  3) **桶/前缀白名单硬校验**:只允许 ALLOWED 白名单内的 (bucket, prefix);其余一律 abort(exit 2)。
     防手滑/参数错导致误删现役前缀(如 nav_bucket/ 或备份桶 large-json/)。
  4) **--expect N 计数闸门**:给定期望对象数时,实际 LIST 数不符则 abort(exit 2),防删错对象面。
  5) **删后复查**:删完重新 LIST,计数必须为 0,否则 exit 3(删不全如实报)。
  6) **前置于备份**:调用方须先确认 large-json 备份完整(本脚本不复核备份,由验证报告承担)。

用法(从任意目录):
    # 1) dry-run(看将删什么)
    .venv/bin/python scripts/r2_delete_prefix.py --bucket signal-data --prefix fund_nav/ \
        --expect 26458 --out /tmp/b3/r2_fund_nav_pre.json
    # 2) 真删(确认后)
    .venv/bin/python scripts/r2_delete_prefix.py --bucket signal-data --prefix fund_nav/ \
        --expect 26458 --yes

实现:SigV4 走 scripts/upload_r2.py:s3_request(与全项目同一签名/路由),POST /?delete 批量删除
(1000 key/批),Content-MD5 + XML body。
"""
import os
import sys
import json
import base64
import hashlib
import argparse
import re
from urllib.parse import quote

REPO = "/Users/linhuichen/code/trade"
os.chdir(REPO)
for line in open(os.path.join(REPO, ".env")):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import upload_r2 as u  # noqa: E402

# 白名单:只允许这些 (bucket, prefix) 组合。新增清理对象须显式在此登记(防误删)。
ALLOWED = {
    ("signal-data", "fund_nav/"),
}
BATCH = 1000


def _list_all(bucket, prefix):
    """分页 LIST 前缀下全部对象,返回 [{"key","size","mtime"}]。"""
    out = []
    token = ""
    while True:
        q = "list-type=2&max-keys=1000&prefix=" + quote(prefix, safe="")
        if token:
            q += "&continuation-token=" + quote(token, safe="")
        st, data = u.s3_request("GET", "", query=q, bucket=bucket, keep_alive=True)
        if st != 200:
            print("ERROR LIST status=%s" % st, flush=True)
            sys.exit(2)
        text = data.decode("utf-8", errors="replace")
        for m in re.finditer(r"<Contents>(.*?)</Contents>", text, re.S):
            b = m.group(1)
            key = re.search(r"<Key>(.*?)</Key>", b, re.S).group(1)
            size = int(re.search(r"<Size>(\d+)</Size>", b).group(1))
            lm = re.search(r"<LastModified>(.*?)</LastModified>", b).group(1)
            out.append({"key": key, "size": size, "mtime": lm})
        if "<IsTruncated>true</IsTruncated>" not in text:
            break
        mm = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", text)
        if not mm:
            break
        token = mm.group(1)
    return out


def _xml_escape(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;").replace("'", "&apos;"))


def _delete_batch(bucket, keys):
    """POST /?delete 批量删一批 key(<=1000)。返回 (deleted_n, error_n)。"""
    objs = "".join("<Object><Key>%s</Key></Object>" % _xml_escape(k) for k in keys)
    body = ('<?xml version="1.0" encoding="UTF-8"?>'
            "<Delete><Quiet>false</Quiet>%s</Delete>" % objs).encode("utf-8")
    md5_b64 = base64.b64encode(hashlib.md5(body).digest()).decode("ascii")
    st, data = u.s3_request(
        "POST", "", payload=body, query="delete=", bucket=bucket,
        content_type="application/xml", keep_alive=True,
        extra_headers={"content-md5": md5_b64},
    )
    text = data.decode("utf-8", errors="replace")
    if st != 200:
        print("ERROR DELETE status=%s body=%s" % (st, text[:400]), flush=True)
        return 0, len(keys)
    errs = len(re.findall(r"<Error>", text))
    deleted = len(re.findall(r"<Deleted>", text))
    return deleted, errs


def main():
    ap = argparse.ArgumentParser(description="删除 R2 某桶某前缀全部对象(默认 dry-run)")
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--expect", type=int, default=None, help="期望对象数(不符则 abort)")
    ap.add_argument("--out", default=None, help="将删对象清单落盘(JSON,便于审计/恢复)")
    ap.add_argument("--yes", action="store_true", help="确认真删(缺失=dry-run)")
    args = ap.parse_args()

    key_pair = (args.bucket, args.prefix)
    if key_pair not in ALLOWED:
        print("ABORT 桶/前缀不在白名单: (%s, %s)" % key_pair, flush=True)
        print("允许:%s" % sorted(ALLOWED), flush=True)
        sys.exit(2)

    objs = _list_all(args.bucket, args.prefix)
    total_size = sum(o["size"] for o in objs)
    print("LIST %s %s: %d objs / %d B (%.1f MiB)"
          % (args.bucket, args.prefix, len(objs), total_size, total_size / 1048576.0),
          flush=True)
    if args.out:
        json.dump(objs, open(args.out, "w"), indent=0)
        print("清单已落盘:%s" % args.out, flush=True)

    if args.expect is not None and len(objs) != args.expect:
        print("ABORT 计数不符: 实际 %d != 期望 %d" % (len(objs), args.expect), flush=True)
        sys.exit(2)

    if not args.yes:
        print("DRY-RUN(未加 --yes,零写)。如确认删除请加 --yes。", flush=True)
        return

    if not objs:
        print("无对象可删(已空)。", flush=True)
        return

    keys = [o["key"] for o in objs]
    total_deleted = 0
    total_err = 0
    for i in range(0, len(keys), BATCH):
        chunk = keys[i:i + BATCH]
        d, e = _delete_batch(args.bucket, chunk)
        total_deleted += d
        total_err += e
        print("  批 %d/%d: deleted=%d err=%d"
              % (i // BATCH + 1, (len(keys) + BATCH - 1) // BATCH, d, e), flush=True)

    print("删除完成: deleted=%d err=%d" % (total_deleted, total_err), flush=True)

    remain = _list_all(args.bucket, args.prefix)
    print("删后 LIST: %d objs" % len(remain), flush=True)
    if remain or total_err:
        print("FAIL 删后残留 %d / 错误 %d" % (len(remain), total_err), flush=True)
        sys.exit(3)
    print("OK 前缀已清空。", flush=True)


if __name__ == "__main__":
    main()