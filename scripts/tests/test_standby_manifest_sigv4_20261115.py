# -*- coding: utf-8 -*-
"""standby 真实可用性修复回归用例(G5 签名 / G6 TLS / G3-G4 manifest 生产者)。

任务书 /tmp/task-standby-sync-fix-20261115.md;缺陷取证 /tmp/standby-d-report.md。
全部用例纯本地(零网络、零 R2 写入), 契约以 standby_sync.normalize_manifest 为单一事实源。
- G5: standby_sync 的 SigV4 首步 HMAC 曾参数写反(空 key 派生)⇒ R2 403; 本文件用
  「同一请求分别由 standby_sync 与 upload_r2 两套实现签名, Authorization 逐字相等」做离线对照。
- G6: TLS 上下文必须保持校验开启(certifi/系统 CA), 不许 unverified。
- G3/G4: standby/manifest_latest.json 生产者 —— business_date 必须取 db_cutoff(禁取
  含文件 mtime 的 common_business_cutoff)、字段不编造、失败不覆盖旧清单、默认关。
"""
import datetime as dt
import gzip
import hashlib
import hmac
import io
import json
import os
import ssl
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

import standby_manifest
import standby_sync
import upload_r2

ROOT = Path(__file__).absolute().parent.parent.parent
SCRIPTS = ROOT / "scripts"

ENDPOINT = "https://acct123.r2.cloudflarestorage.com"
BUCKET = "signal-backup2"
AK = "AKIAEXAMPLEKEY0001"
SK = "sk-example-secret-value-0001"
FIXED_NOW = dt.datetime(2026, 11, 15, 6, 30, 5, tzinfo=dt.timezone.utc)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------- G5 签名对照 ---

def _upload_r2_style_authorization(key: str) -> str:
    """用 upload_r2 的签名原语 + AWS SigV4 文档步骤独立重算 Authorization。

    刻意不调用 standby_sync.build_signed_get —— 两套实现各自构造, 结果必须逐字相等。
    """
    from urllib.parse import quote, urlparse
    host = urlparse(ENDPOINT).hostname
    amz_date = FIXED_NOW.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = FIXED_NOW.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(b"").hexdigest()
    path = f"/{BUCKET}/" + quote(key, safe="/")
    headers = {"host": host, "x-amz-date": amz_date,
               "x-amz-content-sha256": payload_hash}
    signed = ";".join(sorted(headers))
    canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in sorted(headers))
    canonical_request = f"GET\n{path}\n\n{canonical_headers}\n{signed}\n{payload_hash}"
    scope = f"{date_stamp}/auto/s3/aws4_request"
    sts = (f"AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n"
           + hashlib.sha256(canonical_request.encode("utf-8")).hexdigest())
    # upload_r2.signing_key 首步 = HMAC(key="AWS4"+SK, msg=date_stamp) —— 与 AWS 文档一致
    sig = upload_r2._hmac_hex(upload_r2.signing_key(date_stamp, SK), sts)
    return (f"AWS4-HMAC-SHA256 Credential={AK}/{scope}, "
            f"SignedHeaders={signed}, Signature={sig}")


def test_sigv4_authorization_matches_upload_r2_signer():
    key = "standby/manifest_latest.json"
    url, headers = standby_sync.build_signed_get(ENDPOINT, BUCKET, key, AK, SK, FIXED_NOW)
    assert url == f"{ENDPOINT}/{BUCKET}/{key}"
    assert headers["Authorization"] == _upload_r2_style_authorization(key)


def test_sigv4_signing_key_differs_from_reversed_first_step():
    """旧 bug 形态(首步把 date 当 key、`AWS4`+SK 当 msg, 或空 key)必须算出不同签名。"""
    date_stamp = FIXED_NOW.strftime("%Y%m%d")
    correct = standby_sync.aws_signing_key(date_stamp, SK)
    assert correct == upload_r2.signing_key(date_stamp, SK)
    reversed_first = hmac.new(date_stamp.encode("utf-8"), ("AWS4" + SK).encode("utf-8"),
                              hashlib.sha256).digest()
    for part in ("auto", "s3", "aws4_request"):
        reversed_first = hmac.new(reversed_first, part.encode("utf-8"),
                                  hashlib.sha256).digest()
    assert correct != reversed_first


# ---------------------------------------------------------------- G6 TLS ---

def test_tls_context_keeps_certificate_verification():
    ctx = standby_sync.tls_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True
    assert ctx.get_ca_certs(), "CA 证书集为空 = 证书校验形同虚设"


# ------------------------------------------------- G3/G4 manifest 生产者 ---

RUN_ID = "run-20261115-1"
STATE_KEY = "backup/state_20261115_0630.tar.gz"


def _make_set(tmp_path: Path, db_cutoff: str = "2026-11-12",
              common_date: str = "2026-11-14") -> Path:
    set_dir = tmp_path / "set-1"
    set_dir.mkdir(parents=True)
    (set_dir / "manifest.json").write_text(json.dumps({
        "schema": "trade-state-capture-v1",
        "capture_set_id": "cs-1",
        "status": "captured",
        "uploadable": True,
        "complete": True,
        "db_cutoff": {"date": db_cutoff, "all_databases_covered": True},
        "common_business_cutoff": {"date": common_date},
        "archive": {"status": "uploaded", "key": STATE_KEY, "bucket": BUCKET},
    }), encoding="utf-8")
    return set_dir


def _db_receipt(run_id: str = RUN_ID) -> dict:
    objs = {}
    for name in ("sentiment", "etf_national_team", "stock_daily"):
        raw = f"{name}-raw-bytes".encode()
        gz = b"GZ" + raw
        objs[name] = {
            "run_id": run_id, "name": name, "bucket": BUCKET,
            "key": f"backup/{name}_20261115.db.gz",
            "raw": {"sha256": _sha(raw), "size": len(raw)},
            "gzip": {"sha256": _sha(gz), "size": len(gz)},
            "tables": {"score_daily": 3},
        }
    return {"schema": 1, "run_id": run_id, "complete": True, "objects": objs}


def _state_receipt(run_id: str = RUN_ID) -> dict:
    tar_bytes = b"tar-body-bytes"
    return {"schema": 1, "run_id": run_id, "complete": True, "objects": {
        "state_capture": {
            "run_id": run_id, "name": "state_capture", "bucket": BUCKET,
            "key": STATE_KEY,
            "gzip": {"sha256": _sha(b"gz-bytes"), "size": 8,
                     "uncompressed_sha256": _sha(tar_bytes),
                     "uncompressed_size": len(tar_bytes)},
        }}}


def test_manifest_business_date_must_be_db_cutoff_not_common(tmp_path):
    manifest = standby_manifest.build_standby_manifest(
        _make_set(tmp_path, db_cutoff="2026-11-12", common_date="2026-11-14"),
        _db_receipt(), _state_receipt())
    assert manifest["business_date"] == "2026-11-12"   # db_cutoff, 不是 common
    assert manifest["business_date"] != "2026-11-14"
    assert manifest["schema_version"] == 1 and manifest["complete"] is True
    assert manifest["source_run"] == RUN_ID
    roles = sorted(f["role"] for f in manifest["files"])
    assert roles == ["db", "db", "db", "state"]
    by_key = {f["key"]: f for f in manifest["files"]}
    sent = by_key["backup/sentiment_20261115.db.gz"]
    assert sent["size"] == len(b"GZsentiment-raw-bytes")
    assert sent["sha256_gz"] == _sha(b"GZsentiment-raw-bytes")
    assert sent["sha256_uncompressed"] == _sha(b"sentiment-raw-bytes")
    # 对象级 business_date 一律省略(缺省继承集合日期, 防把各库 MAX(date) 误报成集合日期)
    assert all("business_date" not in f for f in manifest["files"])
    st = by_key[STATE_KEY]
    assert st["sha256_uncompressed"] == _sha(b"tar-body-bytes")
    assert st["size_uncompressed"] == len(b"tar-body-bytes")
    assert manifest["excluded"][0]["name"] == "public_fund"
    # 契约校验以 standby_sync 为准(单一事实源)
    standby_sync.normalize_manifest(manifest)


def test_manifest_rejects_incomplete_or_uncovered_inputs(tmp_path):
    set_dir = _make_set(tmp_path)
    bad = _db_receipt()
    bad["complete"] = False
    with pytest.raises(standby_manifest.StandbyManifestError):
        standby_manifest.build_standby_manifest(set_dir, bad, _state_receipt())
    # db_cutoff 未覆盖全部库 ⇒ 不许宣称可接管
    cap = json.loads((set_dir / "manifest.json").read_text(encoding="utf-8"))
    cap["db_cutoff"]["all_databases_covered"] = False
    (set_dir / "manifest.json").write_text(json.dumps(cap), encoding="utf-8")
    with pytest.raises(standby_manifest.StandbyManifestError):
        standby_manifest.build_standby_manifest(set_dir, _db_receipt(), _state_receipt())
    # 缺 sha256(不编造)⇒ 拒绝
    set_dir2 = _make_set(tmp_path / "b")
    db = _db_receipt()
    del db["objects"]["stock_daily"]["gzip"]["sha256"]
    with pytest.raises(standby_manifest.StandbyManifestError):
        standby_manifest.build_standby_manifest(set_dir2, db, _state_receipt())


class _StubS3:
    def __init__(self, put_status=200, head_len=None, copy_status=200):
        self.put_status = put_status
        self.copy_status = copy_status
        self.head_len = head_len
        self.calls = []
        self.tmp_body = b""

    def request(self, method, key, payload=b"", **kwargs):
        self.calls.append((method, key))
        if method == "PUT" and key.startswith(standby_manifest.TMP_PREFIX):
            if self.put_status == 200:
                self.tmp_body = payload
                return 200, b""
            return self.put_status, b"boom"
        if method == "PUT" and key == standby_manifest.LATEST_KEY:
            if self.copy_status != 200:
                return self.copy_status, (b"<Error><Code>InternalError</Code></Error>")
            return 200, b"<CopyObjectResult><ETag>\"x\"</ETag></CopyObjectResult>"
        return 200, b""

    def head(self, key, bucket=None, with_len=False):
        body_len = self.head_len if self.head_len is not None else len(self.tmp_body)
        return (200, "etag", body_len)


@pytest.fixture()
def manifest(tmp_path):
    return standby_manifest.build_standby_manifest(
        _make_set(tmp_path), _db_receipt(), _state_receipt())


def test_publish_success_order(manifest):
    stub = _StubS3(head_len=None)   # head 回读长度取实际写入体长
    key = standby_manifest.publish_standby_manifest(
        manifest, s3_request=stub.request, s3_head=stub.head, bucket=BUCKET)
    assert key == standby_manifest.LATEST_KEY
    methods = [(m, k) for m, k in stub.calls]
    assert methods[0][0] == "PUT" and methods[0][1].startswith(standby_manifest.TMP_PREFIX)
    assert methods[-1] == ("DELETE", methods[0][1])
    assert ("PUT", standby_manifest.LATEST_KEY) in methods


def test_publish_temp_put_failure_never_touches_latest(manifest):
    stub = _StubS3(put_status=500, head_len=1)
    key = standby_manifest.publish_standby_manifest(
        manifest, s3_request=stub.request, s3_head=stub.head, bucket=BUCKET)
    assert key is None
    assert all(k != standby_manifest.LATEST_KEY for _, k in stub.calls)   # 旧清单保留
    assert all(m != "DELETE" for m, _ in stub.calls)                      # 临时对象未建成


def test_publish_copy_failure_keeps_old_manifest_and_cleans_temp(manifest):
    stub = _StubS3(copy_status=503)
    body_len = len(json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                              indent=2).encode("utf-8"))
    stub.head_len = body_len
    key = standby_manifest.publish_standby_manifest(
        manifest, s3_request=stub.request, s3_head=stub.head, bucket=BUCKET)
    assert key is None
    tmp_key = stub.calls[0][1]
    assert ("DELETE", tmp_key) in stub.calls


def test_publish_length_mismatch_never_copies(manifest):
    stub = _StubS3(head_len=1)      # 回读长度对不上 ⇒ 不发布
    key = standby_manifest.publish_standby_manifest(
        manifest, s3_request=stub.request, s3_head=stub.head, bucket=BUCKET)
    assert key is None
    assert ("PUT", standby_manifest.LATEST_KEY) not in stub.calls


def test_cmd_enabled_uses_injected_s3_and_publishes(tmp_path, monkeypatch):
    monkeypatch.setenv("STANDBY_MANIFEST_ENABLED", "1")
    set_dir = _make_set(tmp_path)
    db_path = tmp_path / "db.json"
    db_path.write_text(json.dumps(_db_receipt()), encoding="utf-8")
    st_path = tmp_path / "st.json"
    st_path.write_text(json.dumps(_state_receipt()), encoding="utf-8")
    stub = _StubS3()
    rc = standby_manifest.cmd_standby_manifest(
        str(set_dir), str(db_path), str(st_path),
        s3_request=stub.request, s3_head=stub.head, bucket=BUCKET)
    assert rc == 0
    assert ("PUT", standby_manifest.LATEST_KEY) in stub.calls


def test_cmd_disabled_touches_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("STANDBY_MANIFEST_ENABLED", "0")

    def _boom(*a, **kw):
        raise AssertionError("默认关闭时不许触 R2")

    monkeypatch.setattr(standby_manifest, "publish_standby_manifest", _boom)
    rc = standby_manifest.cmd_standby_manifest(
        str(tmp_path / "nope"), str(tmp_path / "db.json"), str(tmp_path / "st.json"))
    assert rc == 0


def test_upload_r2_cli_default_off_is_noop(tmp_path, monkeypatch):
    """经 upload_r2.py 真实 dispatch, 默认关时 exit 0 且零 R2 接触。"""
    env = dict(**os.environ)
    env["STANDBY_MANIFEST_ENABLED"] = "0"
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "upload_r2.py"), "standby-manifest",
         str(tmp_path / "nope"), str(tmp_path / "db.json"), str(tmp_path / "st.json")],
        capture_output=True, text=True, timeout=120, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "跳过" in (proc.stdout + proc.stderr)


# --------------------------------------------------- state receipt 指纹助手 ---

def test_gzip_uncompressed_fingerprint_matches_decompressed_bytes(tmp_path):
    payload = bytes(range(256)) * 64
    gz_path = tmp_path / "s.tar.gz"
    with tarfile.open(gz_path, "w:gz") as tar:
        info = tarfile.TarInfo("hello.txt")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    with gzip.open(gz_path, "rb") as f:
        expected = f.read()
    sha, size = upload_r2._gzip_uncompressed_fingerprint(gz_path)
    assert sha == _sha(expected)
    assert size == len(expected)


# -------------------------------------------------- backup_db.sh 接线(行为) ---

def test_backup_db_gate_defaults_off_and_runs_after_upload_db():
    text = (SCRIPTS / "backup_db.sh").read_text(encoding="utf-8")
    assert "${STANDBY_MANIFEST_ENABLED:-0}" in text          # 默认关
    gate = text.index('${STANDBY_MANIFEST_ENABLED:-0}" = "1"')
    manifest_call = text.index('"$PY" "$REPO/scripts/upload_r2.py" standby-manifest')
    upload_db_call = text.index('upload_r2.py" upload-db')
    # 仍必须在 upload-db(receipt 落盘)之后、且在门控块内
    assert upload_db_call < gate < manifest_call
