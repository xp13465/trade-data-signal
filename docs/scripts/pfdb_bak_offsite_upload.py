#!/usr/bin/env python3
"""#159 大文件异地归档「流式 multipart」上传(signal-backup 私有桶 decommissioned/ 前缀)。

比仓库既有 `_upload_multipart` 多的两点:
  1. 显式传 bucket(既有 `_upload_multipart` 内部 s3_request 未传 bucket → 会落公开主桶 signal-data 的结构陷阱);
  2. 分片从磁盘 seek 读(不把整个大文件读进内存)—— 云上仅 3.6G 内存,2.7G 整读会 OOM。

用法: REPO=<repo> TARGET_BUCKET=signal-backup2 python3 pfdb_bak_offsite_upload.py <local_file> <key_name>
  key = decommissioned/<key_name>(gzip/zstd 由调用方先压好,本脚本只搬运字节)。
"""
import os, sys, math
from pathlib import Path
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import upload_r2 as u  # noqa: E402

BUCKET = os.environ.get("TARGET_BUCKET") or u.BACKUP_BUCKET
PART_SIZE = 64 * 1024 * 1024
WORKERS = 4
CTYPE = "application/zstd"


def part_ranges(total):
    n = max(1, math.ceil(total / PART_SIZE))
    out, off = [], 0
    for i in range(1, n + 1):
        sz = min(PART_SIZE, total - off)
        out.append((i, off, sz))
        off += sz
    assert off == total, (off, total)
    return out


def upload_file(path, key):
    total = os.path.getsize(path)
    st, data = u.s3_request("POST", key, payload=b"", query="uploads=", bucket=BUCKET)
    if st != 200:
        sys.exit(f"create failed status={st} {data[:300]}")
    upid = u._parse_upload_id(data)
    if not upid:
        sys.exit("no upload_id")
    prs = part_ranges(total)

    def put(pn, off, sz):
        with open(path, "rb") as f:
            f.seek(off)
            buf = f.read(sz)
        q = "partNumber=%d&uploadId=%s" % (pn, quote(upid, safe=""))
        s, d, h = u.s3_request("PUT", key, payload=buf, query=q, bucket=BUCKET,
                               content_type=CTYPE, with_headers=True,
                               progress_label=f"{key} part{pn}/{len(prs)}")
        etag = u._header_lookup(h, "ETag") if s == 200 else None
        return pn, etag, (None if s == 200 and etag else f"status={s} {d[:150]}")

    results = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for fut in [pool.submit(put, *pr) for pr in prs]:
            pn, etag, err = fut.result()
            if err:
                u.s3_request("DELETE", key, query="uploadId=%s" % quote(upid, safe=""), bucket=BUCKET)
                sys.exit(f"part {pn} failed: {err}")
            results[pn] = etag
    xml = "".join("<Part><PartNumber>%d</PartNumber><ETag>%s</ETag></Part>" % (pn, results[pn])
                  for pn in sorted(results))
    body = ("<CompleteMultipartUpload>%s</CompleteMultipartUpload>" % xml).encode()
    st, data = u.s3_request("POST", key, payload=body, query="uploadId=%s" % quote(upid, safe=""),
                            bucket=BUCKET, content_type="application/xml")
    if st != 200:
        sys.exit(f"complete failed status={st} {data[:300]}")
    hs, etag, clen = u.s3_head(key, bucket=BUCKET, with_len=True)
    clen_i = int(clen) if clen is not None else -1
    ok = hs == 200 and clen_i == total
    print(f"[done] {BUCKET}/{key} head={hs} content_length={clen_i} expect={total} {'PASS' if ok else 'FAIL'}")
    if not ok:
        sys.exit("head verify FAIL")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    print(f"TARGET bucket = {BUCKET}")
    upload_file(sys.argv[1], f"decommissioned/{sys.argv[2]}")