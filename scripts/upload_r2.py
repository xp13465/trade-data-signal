#!/usr/bin/env python3
"""R2 (S3 兼容) 上传 - Python 标准库 SigV4 签名(不依赖 boto3/awscli)。

凭证从 .env 读(.gitignore 已忽略)。用法:
  python3 scripts/upload_r2.py list                       # 列 bucket 对象
  python3 scripts/upload_r2.py upload <本地> <r2key>      # 上传单文件
  python3 scripts/upload_r2.py upload-lab                 # 上传 lab/*.json
"""
import os, sys, hashlib, hmac, http.client, datetime, ssl
from pathlib import Path
from urllib.parse import urlparse, quote

ROOT = Path(__file__).resolve().parent.parent


def _find_env():
    """按优先级找 .env：脚本所在 ROOT/.env -> $GIT_REPO/.env -> 默认 trade 仓库。
    背景：launchd 实际在 trade-data/（运行副本）下跑，trade-data/.env 不存在，
    需回退到 trade/.env（git 仓库，凭证源头）。"""
    candidates = [ROOT / ".env"]
    git_repo = os.environ.get("GIT_REPO")
    if git_repo:
        candidates.append(Path(git_repo) / ".env")
    candidates.append(Path("/Users/linhuichen/code/trade/.env"))
    for c in candidates:
        if c.exists():
            return c
    return None


def load_env():
    envf = _find_env()
    if envf is None:
        sys.exit(f"无 .env: 尝试过 {[str(c) for c in [ROOT/'.env', Path(os.environ.get('GIT_REPO',''))/'.env'] if c]}")
    for line in envf.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


load_env()
BUCKET = os.environ["R2_BUCKET"]
# backup 用独立私有桶(不绑公开域名,解决 signal-data 公开可读隐患)。
# .env 可配 R2_BACKUP_BUCKET 覆盖,默认 signal-backup(不 commit .env)。
BACKUP_BUCKET = os.environ.get("R2_BACKUP_BUCKET", "signal-backup")
ENDPOINT = os.environ["R2_S3_ENDPOINT"]
AK = os.environ["R2_S3_ACCESS_KEY_ID"]
SK = os.environ["R2_S3_SECRET_ACCESS_KEY"]
PUBLIC = os.environ.get("R2_PUBLIC_DOMAIN", "").rstrip("/")
REGION = "auto"
SERVICE = "s3"

HOST = urlparse(ENDPOINT).hostname

# macOS 系统 Python 缺 CA 束（CERTIFICATE_VERIFY_FAILED），用系统 /etc/ssl/cert.pem
_CA = "/etc/ssl/cert.pem"
_CTX = ssl.create_default_context(cafile=_CA) if Path(_CA).exists() else ssl._create_unverified_context()


def _hmac(key_bytes, msg):
    return hmac.new(key_bytes, msg.encode("utf-8"), hashlib.sha256).digest()


def _hmac_hex(key_bytes, msg):
    return hmac.new(key_bytes, msg.encode("utf-8"), hashlib.sha256).hexdigest()


def signing_key(date_stamp):
    k = _hmac(("AWS4" + SK).encode("utf-8"), date_stamp)
    k = _hmac(k, REGION)
    k = _hmac(k, SERVICE)
    k = _hmac(k, "aws4_request")
    return k


def s3_request(method, key, payload=b"", query="", bucket=None):
    """path-style: /BUCKET/key, host = endpoint host。bucket=None 用默认 BUCKET。"""
    bkt = bucket or BUCKET
    now = datetime.datetime.utcnow()
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(payload).hexdigest()

    path = f"/{bkt}"
    if key:
        path += "/" + quote(key, safe="/")

    headers = {
        "host": HOST,
        "x-amz-date": amz_date,
        "x-amz-content-sha256": payload_hash,
    }
    if method == "PUT":
        headers["content-type"] = "application/octet-stream"

    sorted_items = sorted(headers.items(), key=lambda x: x[0])
    canonical_headers = "".join(f"{k}:{v.strip()}\n" for k, v in sorted_items)
    signed_headers = ";".join(k for k, _ in sorted_items)

    canonical_request = "\n".join([
        method, path, query, canonical_headers, signed_headers, payload_hash,
    ])

    scope = f"{date_stamp}/{REGION}/{SERVICE}/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", amz_date, scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])

    signature = _hmac_hex(signing_key(date_stamp), string_to_sign)
    headers["authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={AK}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    conn = http.client.HTTPSConnection(HOST, context=_CTX)
    uri = path + ("?" + query if query else "")
    body = payload if method in ("PUT", "POST") else None
    conn.request(method, uri, body=body, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


def cmd_list(prefix="", bucket=None):
    q = "list-type=2&max-keys=100"
    if prefix:
        q += f"&prefix={quote(prefix, safe='')}"
    status, data = s3_request("GET", "", query=q, bucket=bucket)
    bkt = bucket or BUCKET
    print(f"list {bkt} prefix={prefix or '(root)'} status={status}")
    print(data.decode("utf-8", errors="replace")[:3000])


def cmd_delete(key, bucket=None):
    """SigV4 DELETE 单 key。bucket=None 用默认 BUCKET(signal-data)。
    用于迁移后清理 signal-data/backup/ 旧 key。"""
    bkt = bucket or BUCKET
    status, data = s3_request("DELETE", key, bucket=bkt)
    if status == 204:
        print(f"✓ 删除 {bkt}/{key}")
    else:
        print(f"✗ 删除 {bkt}/{key} status={status} {data.decode('utf-8', errors='replace')[:300]}")


def cmd_clean_data_backup():
    """清理 signal-data/backup/ 全部旧 key（迁移到 signal-backup 后一次性清理）。
    列 signal-data(BUCKET)/backup/ 下所有 key 并 DELETE。"""
    keys = _list_keys("backup/", bucket=BUCKET)
    if not keys:
        print(f"{BUCKET}/backup/ 无 key,无需清理")
        return
    print(f"待清理 {BUCKET}/backup/ 共 {len(keys)} 个 key:")
    for k in keys:
        print(f"  - {k}")
    deleted = 0
    for key in keys:
        st, _ = s3_request("DELETE", key, bucket=BUCKET)
        if st == 204:
            deleted += 1
            print(f"  删除 {BUCKET}/{key}")
        else:
            print(f"  ⚠ 删除失败 {BUCKET}/{key} status={st}")
    print(f"{BUCKET}/backup/ 清理 {deleted}/{len(keys)}")


def cmd_upload(local, key):
    payload = Path(local).read_bytes()
    status, data = s3_request("PUT", key, payload)
    if status == 200:
        print(f"✓ {local} ({len(payload)}B) -> {PUBLIC}/{key}")
    else:
        print(f"✗ status={status}\n{data.decode('utf-8', errors='replace')[:1500]}")


def cmd_upload_lab():
    lab = ROOT / "static-site/data/lab"
    files = sorted(lab.glob("*.json"))
    if not files:
        sys.exit(f"无 lab json: {lab}")
    ok = 0
    for f in files:
        key = f"lab/{f.name}"
        payload = f.read_bytes()
        status, data = s3_request("PUT", key, payload)
        if status == 200:
            ok += 1
            print(f"✓ {f.name} ({len(payload) // 1024}KB)")
        else:
            print(f"✗ {f.name} status={status} {data[:200]}")
    print(f"共上传 {ok}/{len(files)} -> {PUBLIC}/lab/")


def _list_keys(prefix, bucket=None):
    """list bucket 下 prefix 的对象 key 列表（list-type=2）。"""
    import re
    q = f"list-type=2&prefix={quote(prefix, safe='')}"
    status, data = s3_request("GET", "", query=q, bucket=bucket)
    if status != 200:
        print(f"⚠ list prefix={prefix} bucket={bucket or BUCKET} 失败 status={status} {data[:200]}")
        return []
    text = data.decode("utf-8", errors="replace")
    return re.findall(r"<Key>([^<]+)</Key>", text)


def _prune_r2_backup(keep_days=30, bucket=None):
    """删 backup/ 下日期 >keep_days 的 key（从 key 名解析 YYYYMMDD）。
    默认清理 BACKUP_BUCKET(signal-backup);迁移后清理 signal-data 用 bucket=BUCKET。

    keep_days=30：与 R2 桶 lifecycle 规则(backup/ prefix,30天过期)一致。
    历史 key 为 backup/<name>_YYYYMMDD.db，2026-07-15 起改压缩上传
    backup/<name>_YYYYMMDD.db.gz。正则同时匹配两者，避免旧 .db 残留堆积。"""
    import re, datetime as _dt
    bkt = bucket or BACKUP_BUCKET
    keys = _list_keys("backup/", bucket=bkt)
    cutoff = _dt.datetime.now() - _dt.timedelta(days=keep_days)
    deleted = 0
    for key in keys:
        # 兼容 .db（旧）与 .db.gz（新,压缩上传后）
        m = re.search(r"(\d{8})\.db(?:\.gz)?$", key)
        if not m:
            continue
        try:
            kd = _dt.datetime.strptime(m.group(1), "%Y%m%d")
        except ValueError:
            continue
        if kd < cutoff:
            st, _ = s3_request("DELETE", key, bucket=bkt)
            if st == 204:
                deleted += 1
                print(f"  删除旧 {bkt}/{key}")
            else:
                print(f"  ⚠ 删除失败 {bkt}/{key} status={st}")
    if deleted:
        print(f"{bkt} 清理 {deleted} 个 >{keep_days}天 旧备份")


def cmd_upload_db():
    """每日 DB 备份推 R2（异地防盘毁）+ 30天滚动清理。
    sentiment.db -> backup/sentiment_YYYYMMDD.db.gz
    etf_national_team.db -> backup/etf_national_team_YYYYMMDD.db.gz
    上传前 gzip 压缩（实测 sentiment.db 82MB->24MB,29%），R2 key 带 .gz 后缀。
    本地 .db 备份不变（backup_db.sh 仍存 .db，方便直接恢复），仅 R2 侧压缩。
    上传到 BACKUP_BUCKET(signal-backup 私有桶,不绑公开域名);
    _prune_r2_backup 默认也清 signal-backup，keep_days=30 与 R2 lifecycle 一致。
    DB 路径取 $REPO/data（与 backup_db.sh 一致，launchd 下 REPO=trade-data）。"""
    import datetime as _dt, gzip
    repo = Path(os.environ.get("REPO", str(ROOT)))
    dbdir = repo / "data"
    today = _dt.datetime.now().strftime("%Y%m%d")
    targets = [
        ("sentiment.db", "sentiment"),
        ("etf_national_team.db", "etf_national_team"),
    ]
    ok = 0
    for fname, name in targets:
        src = dbdir / fname
        if not src.exists():
            print(f"⚠ {src} 不存在，跳过")
            continue
        raw = src.read_bytes()
        payload = gzip.compress(raw, compresslevel=6)  # gzip 压缩后上传(原 .db 本地不动)
        key = f"backup/{name}_{today}.db.gz"
        status, data = s3_request("PUT", key, payload, bucket=BACKUP_BUCKET)
        if status == 200:
            ok += 1
            print(f"✓ {fname} ({len(raw) // 1024}KB -> {len(payload) // 1024}KB gzip) "
                  f"-> {BACKUP_BUCKET}/{key} (私有桶)")
        else:
            print(f"✗ {fname} status={status} {data.decode('utf-8', errors='replace')[:300]}")
    _prune_r2_backup(keep_days=30)
    print(f"DB 上传 {ok}/{len(targets)} -> {BACKUP_BUCKET}/backup/ ({today})")
    if ok != len(targets):
        sys.exit(1)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "list":
        prefix = sys.argv[2] if len(sys.argv) > 2 else ""
        cmd_list(prefix)
    elif cmd == "upload":
        cmd_upload(sys.argv[2], sys.argv[3])
    elif cmd == "upload-lab":
        cmd_upload_lab()
    elif cmd == "upload-db":
        cmd_upload_db()
    elif cmd == "delete":
        # delete <key> [bucket]  bucket 默认 signal-data
        key = sys.argv[2]
        bucket = sys.argv[3] if len(sys.argv) > 3 else None
        cmd_delete(key, bucket)
    elif cmd == "clean-data-backup":
        cmd_clean_data_backup()
    else:
        sys.exit(
            "用法: upload_r2.py [list [prefix]|upload-lab|upload-db|"
            "upload <local> <key>|delete <key> [bucket]|clean-data-backup]"
        )
