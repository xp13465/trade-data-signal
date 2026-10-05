#!/usr/bin/env python3
"""#159 从 R2 私有备份桶 signal-backup2 取回 public_fund.db.bak-20261003_104704 异地归档。

背景:#159 —— 云上 public_fund.db.bak(accnav 回填 STEP2 回滚快照)10G 残留,先补异地备份(R2)再删。
数据本体 = signal-backup2/decommissioned/{public_fund.db.bak-20261003_104704.zst, public_fund.db.wal-20261003_104704.bak.zst}
  (桶名走 upload_r2.BACKUP_BUCKET,即 #178 迁移后的新账号备份桶;如需读老桶,设 R2_BACKUP_BUCKET=signal-backup)
(各 558,045,5xx B, zstd -12 压缩;解压后各 2,670,219,264 B = 10-03 10:47 完整 SQLite 快照)。

用法:
  python3 docs/scripts/restore_pfdb_bak_r2.py verify                       # 全量 key + 抽样 sha256 对账(恢复演练)
  python3 docs/scripts/restore_pfdb_bak_r2.py list
  python3 docs/scripts/restore_pfdb_bak_r2.py get <key> <outdir>           # 下载 .zst(不解压)
  python3 docs/scripts/restore_pfdb_bak_r2.py restore <key> <outdir>       # 下载 + zstd 解压为 .bak

恢复为可用库(§25④ 恢复路径):
  1) restore 取回 public_fund.db.bak-20261003_104704
  2) 停写 public_fund 的写入端(相关 systemd 服务/timer),再 cp 覆盖 trade-data/data/public_fund.db
  3) 重跑当日基金评分 / deploy 同步三库(快照比现行库旧)

安全硬约束:只读 GET decommissioned/ 前缀下 2 个 key;绝不写/删任何 R2 对象。
复用仓库既有 scripts/upload_r2.py 的 SigV4 通路(s3_request),不裸写凭证逻辑。
"""
import os, sys, hashlib
from pathlib import Path

os.environ.setdefault("R2_UPLOAD_HTTP_TIMEOUT", "600")  # 下行慢链路加大 HTTP 超时

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import upload_r2  # 复用 SigV4 / BACKUP_BUCKET / s3_head / _list_keys

BKT = upload_r2.BACKUP_BUCKET
PREFIX = "decommissioned/"

# key -> (zst_size, zst_sha256, src_size, src_sha256)  ← 上传时实测锚点(2026-10-05)
MANIFEST = {
    "decommissioned/public_fund.db.bak-20261003_104704.zst":
        (558045538, "5c597c069425e60c1d541f01ee90fbe020dec24516165aac69aa221ffdf45246",
         2670219264, "dda553c3b918539eacc2078fa06d71763ce2df4c10fdc23720cc88b5567658b9"),
    "decommissioned/public_fund.db.wal-20261003_104704.bak.zst":
        (558045533, "2363fcf25ffae1e4783e02191210e5bf693a86a78aa27aa9d10eb2f416b445df",
         2670219264, "8509b421242ec50d082d602e6fa8d3f526473470d29e08c866a884e0b6985025"),
}


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _download(key, out):
    st, data = upload_r2.s3_request("GET", key, bucket=BKT)
    if st != 200:
        sys.exit(f"GET {key} fail status={st}")
    with open(out, "wb") as f:
        f.write(data)
    return len(data)


def cmd_list():
    keys = upload_r2._list_keys(PREFIX, bucket=BKT)
    print(f"{BKT}/{PREFIX} -> {len(keys)} keys")
    for k in sorted(keys):
        hs, etag, clen = upload_r2.s3_head(k, bucket=BKT, with_len=True)
        print(f"   {k}  len={clen} head={hs}")


def cmd_get(key, outdir):
    Path(outdir).mkdir(parents=True, exist_ok=True)
    out = str(Path(outdir) / os.path.basename(key))
    print(f"GET {key} -> {out} size={_download(key, out)}")


def cmd_restore(key, outdir):
    Path(outdir).mkdir(parents=True, exist_ok=True)
    zst = str(Path(outdir) / os.path.basename(key))
    _download(key, zst)
    exp = MANIFEST.get(key)
    if exp and sha256_file(zst) != exp[1]:
        sys.exit("zst sha256 mismatch")
    out = zst[:-4] if zst.endswith(".zst") else zst + ".dec"
    os.system(f"zstd -d -f -q -o '{out}' '{zst}'")
    print(f"restored -> {out} size={os.path.getsize(out)}")
    if exp:
        got = sha256_file(out)
        print(f"decompressed sha256={got} {'PASS' if got == exp[3] else 'FAIL'}")
        if got != exp[3]:
            sys.exit(1)


def cmd_verify():
    keys = upload_r2._list_keys(PREFIX, bucket=BKT)
    present = set(keys)
    bad = 0
    for key, (zs, zsha, ss, ssha) in MANIFEST.items():
        if key not in present:
            print(f"MISSING {key}")
            bad += 1
            continue
        hs, etag, clen = upload_r2.s3_head(key, bucket=BKT, with_len=True)
        clen_i = int(clen) if clen is not None else -1
        ok = hs == 200 and clen_i == zs
        print(f"{'OK  ' if ok else 'BAD '} {key} head={hs} len={clen_i} expect={zs}")
        bad += 0 if ok else 1
    print(f"=== MISSING/BAD={bad} (expect 0) ===")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == "list":
        cmd_list()
    elif cmd == "get":
        cmd_get(sys.argv[2], sys.argv[3])
    elif cmd == "restore":
        cmd_restore(sys.argv[2], sys.argv[3])
    elif cmd == "verify":
        cmd_verify()
    else:
        sys.exit(__doc__)