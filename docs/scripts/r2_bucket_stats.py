import sys, time, argparse, xml.etree.ElementTree as ET
ROOT = "/Users/linhuichen/code/trade/.claude/worktrees/agent-ae8445feaaa1615ec"
sys.path.insert(0, ROOT + "/scripts")
import upload_r2 as u
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
def list_stats(bucket, max_objects=1000000, prefix="", max_pages=None):
    objs = 0; total = 0; top1 = {}; top2 = {}; calls = 0
    token = ""; trunc = True
    while trunc:
        if objs >= max_objects:
            print("!! %s objs>=%d stop" % (bucket, max_objects), file=sys.stderr)
            break
        q = "list-type=2&max-keys=1000"
        if prefix: q += "&prefix=" + u.quote(prefix, safe="")
        if token: q += "&continuation-token=" + u.quote(token, safe="")
        st, data = u.s3_request("GET", "", query=q, bucket=bucket, keep_alive=True)
        calls += 1
        if st != 200:
            print("  warn list %s status=%d" % (bucket, st), file=sys.stderr)
            break
        root = ET.fromstring(data)
        for c in root.findall(NS + "Contents"):
            k = c.findtext(NS + "Key") or ""
            sz = int(c.findtext(NS + "Size") or 0)
            objs += 1; total += sz
            parts = k.split("/")
            t1 = parts[0] if len(parts) >= 2 else "(root)"
            top1[t1] = top1.get(t1, 0) + 1
            t2 = "/".join(parts[:2]) if len(parts) >= 2 else "(root)"
            d = top2.get(t2)
            if d is None:
                d = dict(objs=0, bytes=0)
                top2[t2] = d
            d["objs"] += 1
            d["bytes"] += sz
        trunc = (root.findtext(NS + "IsTruncated") or "").strip().lower() == "true"
        token = root.findtext(NS + "NextContinuationToken") or ""
        if max_pages and calls >= max_pages:
            print("!! %s pages>=%d stop" % (bucket, max_pages), file=sys.stderr)
            break
    return objs, total, top1, top2, calls
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket")
    ap.add_argument("--prefix", default="")
    ap.add_argument("--max-objects", type=int, default=1000000)
    args = ap.parse_args()
    buckets = []
    if args.bucket:
        buckets.append(("spec", args.bucket))
    else:
        buckets.append(("MAIN", u.BUCKET))
        buckets.append(("BACKUP", u.BACKUP_BUCKET))
    t0 = time.time()
    go = 0; gb = 0; gc = 0
    for label, bkt in buckets:
        objs, byt, top1, top2, calls = list_stats(bkt, max_objects=args.max_objects, prefix=args.prefix)
        gi = byt / (1024.0 ** 3)
        print("")
        print("== %s [%s] prefix=%s ==" % (label, bkt, args.prefix or "(all)"))
        print("  objects=%d bytes=%d (%.3f GiB) list_calls=%d" % (objs, byt, gi, calls))
        print("  top1 by objects:")
        for k, v in sorted(top1.items(), key=lambda x: -x[1])[:40]:
            print("    %s: %d" % (k, v))
        print("  top2 by bytes:")
        for k, v in sorted(top2.items(), key=lambda x: -x[1]["bytes"])[:40]:
            print("    %s: objs=%d bytes=%d (%.3f GiB)" % (k, v["objs"], v["bytes"], v["bytes"] / (1024.0 ** 3)))
        go += objs; gb += byt; gc += calls
    print("")
    print("== sum ==")
    print("  objs=%d bytes=%d (%.3f GiB)" % (go, gb, gb / (1024.0 ** 3)))
    print("  list_calls=%d cost~$%.6f time=%.1fs" % (gc, gc * 4.5 / 1000000.0, time.time() - t0))
if __name__ == "__main__":
    main()
