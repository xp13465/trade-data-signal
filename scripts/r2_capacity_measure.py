#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""r2_capacity_measure.py — 只读测量 R2 桶容量(前缀级聚合 + 部分前缀对象明细)。零写调用(LIST only)。

用法(从任意目录):
    .venv/bin/python scripts/r2_capacity_measure.py <bucket> <out.json>
示例:
    .venv/bin/python scripts/r2_capacity_measure.py signal-backup  /tmp/r2cap_out/old.json
    .venv/bin/python scripts/r2_capacity_measure.py signal-backup2 /tmp/r2cap_out/new.json
    .venv/bin/python scripts/r2_capacity_measure.py signal-data    /tmp/r2cap_out/main.json

- 凭据从 repo/.env 读入 env(不打印任何密钥);桶路由经 scripts/upload_r2.py _route_bucket
  (signal-backup2 走新账号 R2_BACKUP2_*,其余走老账号)。
- 输出 JSON: total_objs/total_bytes/prefixes 聚合/pre_upload_days/large_json 分类;
  另写 <out.json>.detail.json(backup/weekly/monthly/claude-backup/decommissioned/mac-backups 对象级)。
- 硬红线:仅 LIST(GET bucket?list-type=2),零写(PUT/DELETE/COPY 一律无)。
- 溯源:2026-10-07 #233 容量查证 / 2026-10-10 #? 释放核查(本脚本首用版本)。"""
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

bucket = sys.argv[1]
outfile = sys.argv[2]

def list_all(prefix=""):
    out = []; token = ""; pages = 0
    while True:
        q = "list-type=2&max-keys=1000"
        if prefix: q += "&prefix=" + quote(prefix, safe="")
        if token: q += "&continuation-token=" + quote(token, safe="")
        st, data = u.s3_request("GET", "", query=q, bucket=bucket, keep_alive=True)
        if st != 200:
            print("ERROR list %s/%s status=%s" % (bucket, prefix, st), flush=True); sys.exit(2)
        text = data.decode("utf-8", errors="replace")
        for m in re.finditer(r"<Contents>(.*?)</Contents>", text, re.S):
            b = m.group(1)
            key = re.search(r"<Key>(.*?)</Key>", b, re.S).group(1)
            size = int(re.search(r"<Size>(\d+)</Size>", b).group(1))
            lm = re.search(r"<LastModified>(.*?)</LastModified>", b).group(1)
            out.append((key, size, lm))
        pages += 1
        if pages % 10 == 0:
            print("  ...%s pages=%d objs=%d" % (bucket, pages, len(out)), flush=True)
        if "<IsTruncated>true</IsTruncated>" not in text: break
        mm = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", text)
        if not mm: break
        token = mm.group(1)
    return out

t0 = time.time()
rows = list_all("")
agg = {}
for key, size, lm in rows:
    parts = key.split("/")
    t1 = parts[0] + "/" if len(parts) > 1 else "(root)"
    d = agg.setdefault(t1, {"objs": 0, "bytes": 0, "mmin": None, "mmax": None})
    d["objs"] += 1; d["bytes"] += size
    d["mmin"] = lm if d["mmin"] is None or lm < d["mmin"] else d["mmin"]
    d["mmax"] = lm if d["mmax"] is None or lm > d["mmax"] else d["mmax"]
pre = {}
for key, size, lm in rows:
    if key.startswith("pre-upload/"):
        seg = key.split("/")
        dname = seg[1] if len(seg) > 2 else "(loose)"
        e = pre.setdefault(dname, {"objs": 0, "bytes": 0, "mmin": None, "mmax": None})
        e["objs"] += 1; e["bytes"] += size
        e["mmin"] = lm if e["mmin"] is None or lm < e["mmin"] else e["mmin"]
        e["mmax"] = lm if e["mmax"] is None or lm > e["mmax"] else e["mmax"]
lj = {"legacy_dated": {"objs": 0, "bytes": 0}, "flat": {"objs": 0, "bytes": 0}}
for key, size, lm in rows:
    if key.startswith("large-json/"):
        if re.match(r"large-json/\d{4}-\d{2}-\d{2}/", key):
            lj["legacy_dated"]["objs"] += 1; lj["legacy_dated"]["bytes"] += size
        else:
            lj["flat"]["objs"] += 1; lj["flat"]["bytes"] += size
total_objs = len(rows); total_bytes = sum(r[1] for r in rows)
summary = {"bucket": bucket, "total_objs": total_objs, "total_bytes": total_bytes,
           "prefixes": agg, "pre_upload_days": pre, "large_json": lj,
           "taken_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
json.dump(summary, open(outfile, "w"), indent=1, ensure_ascii=False)
print("== %s: %d objs / %d B (%.3f GiB) in %.0fs" % (bucket, total_objs, total_bytes, total_bytes / 2**30, time.time() - t0), flush=True)
for p, d in sorted(agg.items()):
    print("  %s: %d objs / %d B (%.1f MiB) mtime %s ~ %s" % (p, d["objs"], d["bytes"], d["bytes"] / 2**20, d["mmin"], d["mmax"]), flush=True)
print("  pre-upload days: " + json.dumps(pre, ensure_ascii=False), flush=True)
print("  large-json: " + json.dumps(lj), flush=True)
detail = [{"key": k, "size": s, "mtime": lm} for k, s, lm in rows
          if k.split("/")[0] in ("backup", "weekly", "monthly", "claude-backup", "decommissioned", "mac-backups")]
json.dump(detail, open(outfile + ".detail.json", "w"), indent=0)
print("DONE", flush=True)
