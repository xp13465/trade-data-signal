#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""r2_list_prefix.py — 只读列举某桶某前缀全部对象(key/size/mtime → JSON)。零写(LIST only)。

用法(从任意目录):
    .venv/bin/python scripts/r2_list_prefix.py <bucket> <prefix> <out.json>
示例:
    .venv/bin/python scripts/r2_list_prefix.py signal-backup "pre-upload/20261003/" /tmp/r2cap_out/pre1003.json

- 凭据从 repo/.env 读入(不打印);桶路由经 scripts/upload_r2.py _route_bucket。
- 硬红线:仅 LIST,零写。"""
import os, sys, json, time, re
from urllib.parse import quote
REPO = "/Users/linhuichen/code/trade"
os.chdir(REPO)
for line in open(os.path.join(REPO, ".env")):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import upload_r2 as u
bucket, prefix, outfile = sys.argv[1], sys.argv[2], sys.argv[3]
out = []; token = ""
while True:
    q = "list-type=2&max-keys=1000&prefix=" + quote(prefix, safe="")
    if token: q += "&continuation-token=" + quote(token, safe="")
    st, data = u.s3_request("GET", "", query=q, bucket=bucket, keep_alive=True)
    if st != 200:
        print("ERROR status=%s" % st, flush=True); sys.exit(2)
    text = data.decode("utf-8", errors="replace")
    for m in re.finditer(r"<Contents>(.*?)</Contents>", text, re.S):
        b = m.group(1)
        key = re.search(r"<Key>(.*?)</Key>", b, re.S).group(1)
        size = int(re.search(r"<Size>(\d+)</Size>", b).group(1))
        lm = re.search(r"<LastModified>(.*?)</LastModified>", b).group(1)
        out.append({"key": key, "size": size, "mtime": lm})
    if "<IsTruncated>true</IsTruncated>" not in text: break
    mm = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", text)
    if not mm: break
    token = mm.group(1)
json.dump(out, open(outfile, "w"), indent=0)
print("== %s %s: %d objs" % (bucket, prefix, len(out)), flush=True)
