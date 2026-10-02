#!/usr/bin/env python3
"""从 R2 私有备份桶 signal-backup 取回 mac-backups/2026-10-01/ 的 86 个对象到本机,md5 对账,对账 PASS 后可删 R2。

背景:#151 调研,R2 备份桶超免费额度 10GiB 的唯一元凶 = mac-backups/2026-10-01/(10.171 GiB,86 对象)。
流程:list → speedtest(8 并发测速,决定是否继续) → download(8 并发全量) → verify(md5+size 对账锚点日志)
→ delete(仅 86/86 PASS 后) → put-restore(恢复路径,本地传回 R2)。

用法:
  python3 docs/scripts/restore_mac_backups_r2.py list
  python3 docs/scripts/restore_mac_backups_r2.py speedtest
  python3 docs/scripts/restore_mac_backups_r2.py download
  python3 docs/scripts/restore_mac_backups_r2.py verify
  python3 docs/scripts/restore_mac_backups_r2.py delete
  python3 docs/scripts/restore_mac_backups_r2.py put-restore

安全硬约束(必须遵守):
  1. 只删明确列出的 86 个 key(mac-backups/2026-10-01/ 前缀),绝不前缀批量删、绝不碰其他前缀。
  2. 对账 86/86 PASS 之前绝不允许 delete(本脚本 delete 前强制跑 verify,非 PASS 直接 abort)。
  3. 下载落点 = ~/code/trade-data/data/mac-backups-20261001/(git 仓外),不 commit 数据。
"""
import os, sys, re, hashlib, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

os.environ.setdefault("R2_UPLOAD_HTTP_TIMEOUT", "600")  # 下行慢链路加大 HTTP 超时

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import upload_r2  # 复用既有 s3_request / BACKUP_BUCKET / _list_keys(SigV4 签名已封装)

PREFIX = "mac-backups/2026-10-01/"
DEST_DIR = Path("/Users/linhuichen/code/trade-data/data/mac-backups-20261001")
LOG = Path("/tmp/mac_backups_upload_log_20261001.txt")
WORKERS = 8
BKT = upload_r2.BACKUP_BUCKET


# ---------- 基础 ----------

def log_parse():
    """解析锚点日志 → {basename: (size, md5)}。格式:key|size=N|md5=HASH|status=200|etag=|match=False"""
    out = {}
    for line in LOG.read_text().splitlines():
        line = line.strip()
        if "|size=" not in line:
            continue
        parts = line.split("|")
        key = parts[0]
        size = None
        md5 = None
        for p in parts[1:]:
            if p.startswith("size="):
                size = int(p.split("=", 1)[1])
            elif p.startswith("md5="):
                md5 = p.split("=", 1)[1]
        if size is None or md5 is None:
            raise ValueError(f"日志行字段缺失: {line!r}")
        out[key.split("/")[-1]] = (size, md5)
    return out


def r2_keys():
    """R2 侧 mac-backups/2026-10-01/ 全部 key(分页全量)。"""
    keys = upload_r2._list_keys(PREFIX, bucket=BKT)
    return [k for k in keys if k.startswith(PREFIX)]


def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def get_one(key, dest):
    """GET 单个对象落盘,返回字节数。keep_alive 复用线程连接。"""
    status, data = upload_r2.s3_request("GET", key, bucket=BKT, keep_alive=True)
    if status != 200:
        raise RuntimeError(f"GET {key} status={status} {data[:200]!r}")
    dest.write_bytes(data)
    return len(data)


def human(n):
    for u in ("B", "KB", "MB", "GB", "TiB"):
        if n < 1024 or u == "TiB":
            return f"{n:.1f} {u}" if u != "B" else f"{n} {u}"
        n /= 1024


# ---------- 子命令 ----------

def cmd_list():
    keys = r2_keys()
    print(f"R2 {BKT}/{PREFIX}: 共 {len(keys)} 个对象")
    for k in sorted(keys):
        print(" ", k)


def cmd_speedtest():
    """挑 8 个 50-150MB 的中等文件并发 GET,测聚合吞吐。文件同时落盘到 DEST_DIR。"""
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    log = log_parse()
    mids = [n for n, (sz, _) in log.items() if 50 * 1024 * 1024 <= sz <= 150 * 1024 * 1024]
    if len(mids) < WORKERS:
        print(f"⚠ 中等文件不足 8 个(只有 {len(mids)}),改用最大的 8 个")
        mids = sorted(log, key=lambda n: log[n][0], reverse=True)[:WORKERS]
    pick = mids[:WORKERS]
    total_bytes = sum(log[n][0] for n in pick)
    print(f"测速文件 {len(pick)} 个,合计 {human(total_bytes)},8 路并发 GET ...")
    t0 = time.time()
    ok = 0
    sizes = {}
    errors = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(get_one, PREFIX + n, DEST_DIR / n): n for n in pick}
        for fut in as_completed(futs):
            n = futs[fut]
            try:
                sizes[n] = fut.result()
                ok += 1
                dt = time.time() - t0
                print(f"  完成 {n} {human(sizes[n])} ({ok}/{len(pick)}),已用 {dt:.0f}s")
            except Exception as e:
                errors.append((n, str(e)))
    dt = time.time() - t0
    got = sum(sizes.values())
    agg = got / dt / 1024 / 1024 if dt > 0 else 0
    for n, e in errors:
        print(f"  ✗ {n}: {e}")
    print(f"测速: ok={ok}/{len(pick)}, 共 {human(got)}, 用时 {dt:.1f}s, 聚合 {agg:.2f} MB/s")
    return agg


def cmd_download():
    """8 路并发 GET 全部对象落盘。本地已存在且 size 匹配的跳过(支持续跑)。"""
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    log = log_parse()
    all_keys = sorted(PREFIX + n for n in log)
    todo = []
    skip = 0
    for k in all_keys:
        name = k.split("/")[-1]
        sz = log[name][0]
        f = DEST_DIR / name
        if f.exists() and f.stat().st_size == sz:
            skip += 1
        else:
            todo.append(k)
    print(f"下载: 共 {len(all_keys)} 个,跳过已存在 {skip},待下 {len(todo)}")
    total = 0
    t0 = time.time()
    done = skip
    errors = []
    if todo:
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = {ex.submit(get_one, k, DEST_DIR / k.split("/")[-1]): k for k in todo}
            for fut in as_completed(futs):
                k = futs[fut]
                try:
                    total += fut.result()
                    done += 1
                    if done % 20 == 0 or done == len(all_keys):
                        print(f"  已下 {done}/{len(all_keys)},累计 {human(total)}")
                except Exception as e:
                    errors.append((k, str(e)))
    dt = time.time() - t0
    agg = total / dt / 1024 / 1024 if dt > 0 else 0
    print(f"下载完成: ok={done}/{len(all_keys)}, 本次下载 {human(total)}, 用时 {dt:.0f}s, 聚合 {agg:.2f} MB/s")
    if errors:
        print("以下文件下载失败(可重跑 download 续传):")
        for k, e in errors:
            print(" ", k, e)
        sys.exit(1)
    return done


def cmd_verify():
    """本地 md5+size vs 锚点日志逐行比对,输出 86/86 PASS 或 MISSING/MISMATCH 清单。"""
    log = log_parse()
    missing = []
    mismatch = []
    pass_n = 0
    for name, (sz, md5) in sorted(log.items()):
        f = DEST_DIR / name
        if not f.exists():
            missing.append(name)
            continue
        lmd5 = md5_file(f)
        if f.stat().st_size != sz or lmd5 != md5:
            mismatch.append((name, sz, f.stat().st_size, md5, lmd5))
        else:
            pass_n += 1
    print(f"对账结果: PASS {pass_n}/{len(log)}, MISSING {len(missing)}, MISMATCH {len(mismatch)}")
    for n in missing:
        print(f"  MISSING {n}")
    for n, es, ls, em, lm in mismatch:
        print(f"  MISMATCH {n} size {es}/{ls} md5 {em}/{lm}")
    if missing or mismatch:
        return False
    return True


def cmd_delete():
    """仅 86/86 PASS 后删 R2 明确列出的 86 个 key。前置强制 verify。"""
    if not cmd_verify():
        print("✗ 对账未全 PASS,拒绝删除。")
        sys.exit(2)
    log = log_parse()
    keys = sorted(PREFIX + n for n in log)
    print(f"对账 86/86 PASS,准备删除 R2 {BKT}/{PREFIX} 的 {len(keys)} 个 key")
    ok = 0
    for i, k in enumerate(keys, 1):
        st, data = upload_r2.s3_request("DELETE", k, bucket=BKT, keep_alive=True)
        if st in (204, 200):
            ok += 1
            print(f"  删 {i}/{len(keys)} {k} status={st}")
        else:
            print(f"  ⚠ 删除失败 {k} status={st} {data[:200]!r}")
    print(f"删除完成: ok={ok}/{len(keys)}")
    if ok != len(keys):
        sys.exit(1)


def cmd_put_restore():
    """恢复路径:把本地 mac-backups-20261001/ 下文件 PUT 回 R2 同前缀(逆向恢复用)。"""
    log = log_parse()
    keys = sorted(PREFIX + n for n in log)
    print(f"恢复上传: {len(keys)} 个对象到 {BKT}/{PREFIX}")
    ok = 0
    for i, n in enumerate(keys, 1):
        name = n.split("/")[-1]
        f = DEST_DIR / name
        if not f.exists():
            print(f"  ⚠ 本地缺失 {name},跳过")
            continue
        payload = f.read_bytes()
        st, data = upload_r2.s3_request("PUT", n, payload, bucket=BKT)
        if st == 200:
            ok += 1
            print(f"  传 {i}/{len(keys)} {name} ok")
        else:
            print(f"  ✗ 上传失败 {name} status={st} {data[:200]!r}")
    print(f"恢复上传完成: ok={ok}/{len(keys)}")
    if ok != len(keys):
        sys.exit(1)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "list":
        cmd_list()
    elif cmd == "speedtest":
        agg = cmd_speedtest()
        if agg < 3:
            print("⚠ 聚合吞吐 < 3 MB/s:按铁律停止全量下载,不删 R2。")
            sys.exit(3)
    elif cmd == "download":
        cmd_download()
    elif cmd == "verify":
        if cmd_verify():
            print("对账 86/86 PASS")
        else:
            sys.exit(1)
    elif cmd == "delete":
        cmd_delete()
    elif cmd == "put-restore":
        cmd_put_restore()
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
