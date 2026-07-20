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


def load_env():
    envf = ROOT / ".env"
    if not envf.exists():
        sys.exit(f"无 .env: {envf}")
    for line in envf.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


load_env()
BUCKET = os.environ["R2_BUCKET"]
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


def s3_request(method, key, payload=b"", query=""):
    """path-style: /BUCKET/key, host = endpoint host。"""
    now = datetime.datetime.utcnow()
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(payload).hexdigest()

    path = f"/{BUCKET}"
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


def cmd_list():
    status, data = s3_request("GET", "", query="list-type=2&max-keys=100")
    print(f"list status={status}")
    print(data.decode("utf-8", errors="replace")[:3000])


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


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "list":
        cmd_list()
    elif cmd == "upload":
        cmd_upload(sys.argv[2], sys.argv[3])
    elif cmd == "upload-lab":
        cmd_upload_lab()
    else:
        sys.exit("用法: upload_r2.py [list|upload-lab|upload <local> <key>]")
