#!/usr/bin/env python3
# #198 只读核查:claude-backup/ mac-backups/ pre-upload/ 在新老桶的对象与 LastModified;路由解析。
# 只发 GET(ListObjectsV2),绝不写任何桶。用法:
#   python3 docs/scripts/198_backup_prefix_probe.py            # 枚举 6 组(2 桶 x 3 前缀)
#   python3 docs/scripts/198_backup_prefix_probe.py route      # 只打印路由解析值
# 输出:stdout 摘要 + /tmp/r2_list_198_out.json 全量
import sys, re, json
sys.path.insert(0, "/Users/linhuichen/code/trade/scripts")
import upload_r2 as u
u.load_env()
print("=== route check (host only, no keys) ===", flush=True)
print("BACKUP_BUCKET =", u.BACKUP_BUCKET, flush=True)
print("BACKUP2_BUCKET =", u.BACKUP2_BUCKET, flush=True)
print("BACKUP2_HOST =", u.BACKUP2_HOST, flush=True)
print("route(signal-backup)[0] =", u._route_bucket("signal-backup")[0], flush=True)
print("route(signal-backup2)[0] =", u._route_bucket("signal-backup2")[0], flush=True)

def list_with_time(prefix, bucket):
    out = []
    token = ""
    pages = 0
    while True:
        q = f"list-type=2&prefix={u.quote(prefix, safe='')}"
        if token:
            q += f"&continuation-token={u.quote(token, safe='')}"
        status, data = u.s3_request("GET", "", query=q, bucket=bucket)
        pages += 1
        if status != 200:
            print(f"ERR {bucket}/{prefix} status={status} p={pages} {data[:200]}", flush=True)
            return out, pages
        text = data.decode("utf-8", errors="replace")
        for b in text.split("</Contents>"):
            mk = re.search(r"<Key>([^<]+)</Key>", b)
            if not mk:
                continue
            ml = re.search(r"<LastModified>([^<]+)</LastModified>", b)
            out.append((mk.group(1), ml.group(1) if ml else None))
        if "<IsTruncated>true</IsTruncated>" not in text:
            break
        t = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", text)
        if not t:
            break
        token = t.group(1)
    return out, pages

BUCKETS = ["signal-backup", "signal-backup2"]
PREFIXES = ["claude-backup/", "mac-backups/", "pre-upload/"]
CUTOVER = "2026-10-05T05:30:00"
if len(sys.argv) > 1 and sys.argv[1] == "route":
    sys.exit(0)

result = {}
for bucket in BUCKETS:
    for prefix in PREFIXES:
        keys, pages = list_with_time(prefix, bucket)
        keys_sorted = sorted(keys, key=lambda kv: (kv[1] or ""), reverse=True)
        after = [kv for kv in keys if kv[1] and kv[1] >= CUTOVER]
        info = {"count": len(keys), "pages": pages, "latest5": keys_sorted[:5],
                "after_cutover_count": len(after), "after_cutover_sample": after[:12]}
        result[bucket + "::" + prefix] = info
        print("[" + bucket + "] " + prefix + ": " + str(len(keys)) + " objects; after-cutover=" + str(len(after)), flush=True)
        for k, t in keys_sorted[:3]:
            print("   " + str(t) + "  " + k, flush=True)
with open("/tmp/r2_list_198_out.json", "w") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)
print("JSON saved /tmp/r2_list_198_out.json", flush=True)
