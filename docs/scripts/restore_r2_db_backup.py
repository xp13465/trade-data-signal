#!/usr/bin/env python3
"""从 R2 signal-backup2 私有桶流式拉回 DB 备份,供恢复/校验(2026-10-25 起)。

为什么不用 `scripts/upload_r2.py download-db`:
    那个命令一次 GET 把整个对象读进内存,再 gzip.decompress 把解压结果也放内存;
    public_fund.db 备份 = 0.79GB gz -> 2.9GB 解压,云主机 3.7GB RAM 会 OOM。
    本脚本改用 32MiB Range 分片(默认 6 线程)落盘,再流式解压,峰值内存约 200MiB。

用法:
    # 恢复最新一份 public_fund 备份到指定目录(保留 .gz 便于复核)
    python3 docs/scripts/restore_r2_db_backup.py --name public_fund --out-dir /data/restore

    # 指定日期
    python3 docs/scripts/restore_r2_db_backup.py --name public_fund --date 20261025 --out-dir /tmp/r

    # 拉回后与「源库当前状态」逐位对账(会额外生成 2.9GB 参考快照, 需要足够磁盘)
    python3 docs/scripts/restore_r2_db_backup.py --name public_fund --out-dir /tmp/v \
        --verify-against-src data/public_fund.db

校验内容:
    1) 对象存在 + Content-Length 与拉回字节数一致
    2) .gz 整文件 md5 落档
    3) 解压后 PRAGMA integrity_check == ok, 记录 page_count/page_size/表数
    4) --verify-against-src 时: 用 sqlite3 在线 backup 生成参考快照, 整文件 md5 +
       头/尾各 50MiB md5 逐位比对(与上传时同一快照口径)

退出码: 0 = 全部检查通过; 1 = 任一检查失败(明细见 <out-dir>/result.json)。
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import sys
import threading
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
os.environ.setdefault("REPO", str(REPO))

_spec = importlib.util.spec_from_file_location("upload_r2_restore", REPO / "scripts" / "upload_r2.py")
ur = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ur)


def md5_file(path, chunk=8 << 20):
    h = hashlib.md5()
    n = 0
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
            n += len(b)
    return h.hexdigest(), n


def md5_slice(path, offset, length, chunk=8 << 20):
    h = hashlib.md5()
    with open(path, "rb") as f:
        f.seek(offset)
        left = length
        while left > 0:
            b = f.read(min(chunk, left))
            if not b:
                break
            h.update(b)
            left -= len(b)
    return h.hexdigest()


def integrity(path):
    con = sqlite3.connect(str(path))
    try:
        return {
            "integrity_check": con.execute("PRAGMA integrity_check").fetchone()[0],
            "page_count": con.execute("PRAGMA page_count").fetchone()[0],
            "page_size": con.execute("PRAGMA page_size").fetchone()[0],
            "tables": con.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0],
        }
    finally:
        con.close()


def pick_key(name, date_str=None):
    """按日期降序取最新一份; 指定 date 时精确取 backup/<name>_<date>.db.gz。"""
    if date_str:
        key = f"backup/{name}_{date_str}.db.gz"
        status, _etag, length = ur.s3_head(key, bucket=ur.BACKUP_BUCKET, with_len=True)
        if status != 200:
            raise RuntimeError(f"对象不存在或 HEAD 失败: {ur.BACKUP_BUCKET}/{key} status={status}")
        return key, int(length or 0)
    dated = []
    for k in ur._list_keys(f"backup/{name}_", bucket=ur.BACKUP_BUCKET):
        m = re.search(r"(\d{8})\.db(?:\.gz)?$", k)
        if m:
            dated.append((m.group(1), k))
    if not dated:
        raise RuntimeError(f"无备份 key: {ur.BACKUP_BUCKET}/backup/{name}_*")
    dated.sort(reverse=True)
    date_str, key = dated[0]
    status, _etag, length = ur.s3_head(key, bucket=ur.BACKUP_BUCKET, with_len=True)
    if status != 200:
        raise RuntimeError(f"HEAD 失败: {key} status={status}")
    return key, int(length or 0)


def download(key, out_gz, total, part_size=32 << 20, threads=6):
    """Range GET 分片拉回, 每段写完即释放(峰值内存 = 线程数 × 段大小)。"""
    ranges = [(i, i * part_size, min((i + 1) * part_size, total) - 1)
              for i in range((total + part_size - 1) // part_size)]
    with open(out_gz, "wb") as f:
        f.truncate(total)
    errors = []
    lock = threading.Lock()
    queue = list(ranges)

    def worker():
        while True:
            with lock:
                if not queue:
                    return
                _i, start, end = queue.pop(0)
            try:
                status, data = ur.s3_request(
                    "GET", key, bucket=ur.BACKUP_BUCKET,
                    extra_headers={"range": f"bytes={start}-{end}"})
                if status not in (200, 206):
                    raise RuntimeError(f"http {status}")
                if len(data) != end - start + 1:
                    raise RuntimeError(f"len {len(data)} != {end - start + 1}")
                with open(out_gz, "r+b") as f:
                    f.seek(start)
                    f.write(data)
            except Exception as e:  # noqa: BLE001
                errors.append(f"bytes={start}-{end}: {e}")

    pool = [threading.Thread(target=worker) for _ in range(max(1, threads))]
    for t in pool:
        t.start()
    for t in pool:
        t.join()
    if errors:
        raise RuntimeError("下载失败: " + "; ".join(errors[:5]))
    if out_gz.stat().st_size != total:
        raise RuntimeError(f"拉回大小 {out_gz.stat().st_size} != Content-Length {total}")
    return {"bytes": total, "parts": len(ranges)}


def gunzip_stream(gz_path, out_path):
    h = hashlib.md5()
    n = 0
    with gzip.open(gz_path, "rb") as fi, open(out_path, "wb") as fo:
        while True:
            b = fi.read(4 << 20)
            if not b:
                break
            h.update(b)
            fo.write(b)
            n += len(b)
    return h.hexdigest(), n


def verify_against_src(src_path, pulled_path, pulled_md5, state_file=None):
    """与源库当前状态生成的参考快照逐位对账; 源库须与备份时一致, 否则对账无意义。"""
    out = {}
    if state_file and state_file.exists():
        state = json.loads(state_file.read_text()).get("public_fund.db") or {}
        st = src_path.stat()
        out["src_unchanged_since_backup"] = (
            state.get("size") == st.st_size and state.get("mtime_ns") == st.st_mtime_ns)
        out["state_entry"] = state
        if not out["src_unchanged_since_backup"]:
            raise RuntimeError("源库自备份后已变化, 与备份快照对账无效(请对照备份时台账)")
    ref = pulled_path.with_name("ref_" + pulled_path.name)
    src_con = sqlite3.connect(str(src_path))
    ref_con = sqlite3.connect(str(ref))
    try:
        src_con.backup(ref_con)
    finally:
        ref_con.close()
        src_con.close()
    ref_md5, ref_n = md5_file(ref)
    out["ref"] = {"md5": ref_md5, "bytes": ref_n}
    out["full_md5_match"] = (ref_md5 == pulled_md5 and ref_n == pulled_path.stat().st_size)
    size_50 = 50 << 20
    if ref_n >= 2 * size_50:
        head_ref = md5_slice(ref, 0, size_50)
        head_pulled = md5_slice(pulled_path, 0, size_50)
        tail_ref = md5_slice(ref, ref_n - size_50, size_50)
        tail_pulled = md5_slice(pulled_path, ref_n - size_50, size_50)
        out["sample_50mb"] = {
            "head_ref": head_ref, "head_pulled": head_pulled, "head_match": head_ref == head_pulled,
            "tail_ref": tail_ref, "tail_pulled": tail_pulled, "tail_match": tail_ref == tail_pulled,
        }
    out["ref_integrity"] = integrity(ref)
    if not out["full_md5_match"]:
        raise RuntimeError("解压后的库与参考快照整文件 md5 不一致")
    if out.get("sample_50mb") and not (out["sample_50mb"]["head_match"] and out["sample_50mb"]["tail_match"]):
        raise RuntimeError("头/尾 50MiB 抽样 md5 不一致")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="从 R2 私有桶流式拉回 DB 备份并校验")
    ap.add_argument("--name", required=True, help="备份名(如 public_fund / sentiment)")
    ap.add_argument("--date", help="YYYYMMDD; 省略取最新")
    ap.add_argument("--out-dir", required=True, help="输出目录(需预留 gz+解压后大小)")
    ap.add_argument("--part-size-mib", type=int, default=32, help="Range 分片大小 MiB(默认 32)")
    ap.add_argument("--threads", type=int, default=6, help="下载线程数(默认 6)")
    ap.add_argument("--verify-against-src", help="源库路径; 给出则与参考快照逐位对账(额外占一份磁盘)")
    ap.add_argument("--state-file", help="默认 <REPO>/data/.r2_db_backup_state.json")
    args = ap.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {"name": args.name, "bucket": ur.BACKUP_BUCKET, "checks": {}, "ok": False}
    try:
        key, total = pick_key(args.name, args.date)
        result["key"] = key
        if not key.endswith(".gz"):
            raise RuntimeError(f"仅支持 .db.gz 备份(2026-07-15 后格式), 该 key 为 {key}")
        result["checks"]["head"] = {"status": 200, "content_length": total}
        if total <= 0:
            raise RuntimeError("Content-Length 为 0/缺失")

        date_tag = re.search(r"(\d{8})\.db", key).group(1)
        gz = out_dir / f"{args.name}_{date_tag}.db.gz"
        db = out_dir / f"{args.name}_{date_tag}.db"

        result["checks"]["download"] = download(
            key, gz, total, part_size=args.part_size_mib << 20, threads=args.threads)
        gz_md5, gz_n = md5_file(gz)
        result["checks"]["gz"] = {"md5": gz_md5, "bytes": gz_n}

        pulled_md5, pulled_n = gunzip_stream(gz, db)
        result["checks"]["pulled"] = {"md5": pulled_md5, "bytes": pulled_n}
        result["checks"]["integrity_pulled"] = integrity(db)
        if result["checks"]["integrity_pulled"]["integrity_check"] != "ok":
            raise RuntimeError("拉回副本 PRAGMA integrity_check 不是 ok")

        if args.verify_against_src:
            state_file = Path(args.state_file) if args.state_file else REPO / "data" / ".r2_db_backup_state.json"
            result["checks"]["against_src"] = verify_against_src(
                Path(args.verify_against_src), db, pulled_md5, state_file)

        result["ok"] = True
        result["db_path"] = str(db)
    except Exception as e:  # noqa: BLE001
        result["error"] = f"{type(e).__name__}: {e}"
        result["traceback"] = traceback.format_exc()[-2000:]

    (out_dir / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps({"ok": result["ok"], "key": result.get("key"), "error": result.get("error")},
                     ensure_ascii=False))
    print("RESTORE " + ("PASS" if result["ok"] else "FAIL"))
    if result["ok"]:
        print(result["db_path"])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())