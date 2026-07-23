#!/usr/bin/env python3
"""R2 (S3 兼容) 上传 - Python 标准库 SigV4 签名(不依赖 boto3/awscli)。

凭证从 .env 读(.gitignore 已忽略)。用法:
  python3 scripts/upload_r2.py list                       # 列 bucket 对象
  python3 scripts/upload_r2.py upload <本地> <r2key>      # 上传单文件
  python3 scripts/upload_r2.py upload-lab                 # 上传 lab/*.json
  python3 scripts/upload_r2.py upload-trade-sim           # 上传 trade_sim_*.html -> trade_sim/
  python3 scripts/upload_r2.py upload-index               # 上传 data/index/*.json+.gz -> index/
  python3 scripts/upload_r2.py upload-industry            # 上传 data/industry-* -> industry/
  python3 scripts/upload_r2.py upload-db                  # 每日 DB 备份推 R2(signal-backup)
  python3 scripts/upload_r2.py download-db <name> [dir]   # 下载最新备份(解压后.db路径到stdout)
"""
import os, sys, hashlib, hmac, http.client, datetime, ssl
from pathlib import Path
from urllib.parse import urlparse, quote

ROOT = Path(__file__).resolve().parent.parent
# 静态数据目录：优先用 REPO env(launchd 设 trade-data,采集器写此处),
# 回退 ROOT(trade)。trade-data/scripts 是 trade/scripts 的 symlink,
# ROOT 经 .resolve() 解析到 trade/,但采集器写 trade-data/static-site/data/,
# 故 upload 命令必须用 REPO 才能读到采集器刚写的实时数据(非 deploy rsync 后的 trade/)。
STATIC_DIR = Path(os.environ.get("REPO", str(ROOT))) / "static-site"


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


_CONTENT_TYPE_MAP = {
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".gz": "application/gzip",
}


def s3_request(method, key, payload=b"", query="", bucket=None, content_type=None):
    """path-style: /BUCKET/key, host = endpoint host。bucket=None 用默认 BUCKET。

    带连接超时(30s)+ 重试(3 次,SSL/连接错退避 1s/2s/4s),防 R2 偶发断连致脚本挂死。
    content_type=None 时按 key 扩展名推断(_CONTENT_TYPE_MAP),未知扩展名回退 application/octet-stream。
    """
    if content_type is None:
        ext = os.path.splitext(key)[1].lower()
        content_type = _CONTENT_TYPE_MAP.get(ext, "application/octet-stream")
    bkt = bucket or BUCKET
    last_exc = None
    for attempt in range(3):
        try:
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
                headers["content-type"] = content_type

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

            conn = http.client.HTTPSConnection(HOST, timeout=30, context=_CTX)
            uri = path + ("?" + query if query else "")
            body = payload if method in ("PUT", "POST") else None
            conn.request(method, uri, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            conn.close()
            return resp.status, data
        except (ssl.SSLError, OSError, http.client.HTTPException) as e:
            last_exc = e
            if attempt < 2:
                import time
                wait = 2 ** attempt  # 1s, 2s
                print(f"  ⚠ {method} {key} attempt {attempt+1} 失败({type(e).__name__}: {e}), {wait}s 后重试", file=sys.stderr)
                time.sleep(wait)
            else:
                raise
    raise last_exc  # 不可达,防 mypy


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
    lab = STATIC_DIR / "data/lab"
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


def _upload_glob(local_dir, glob_patterns, r2_prefix, include_gz=True):
    """通用 glob 上传：local_dir 下按 patterns 匹配文件，上传到 R2 r2_prefix/。

    R2 key = r2_prefix/{相对 local_dir 的路径}。返回 (ok, total)。
    include_gz=True 时同时上传 .gz（若存在）。
    单文件失败(重试3次仍错)不中断整批,继续上传后续文件。
    """
    local_dir = Path(local_dir)
    files = []
    for pat in glob_patterns:
        files.extend(local_dir.glob(pat))
    # 去重 + 排序
    files = sorted(set(files))
    if not files:
        print(f"⚠ {local_dir} 下 {glob_patterns} 无匹配文件")
        return 0, 0
    ok = 0
    total = len(files)
    for i, f in enumerate(files, 1):
        rel = f.relative_to(local_dir)
        key = f"{r2_prefix}/{rel}"
        payload = f.read_bytes()
        size = len(payload)
        try:
            status, data = s3_request("PUT", key, payload)
            if status == 200:
                ok += 1
                print(f"[{i}/{total}] ✓ {rel} ({size}B)")
            else:
                print(f"[{i}/{total}] ✗ {rel} status={status} {data[:200]}")
        except Exception as e:
            print(f"[{i}/{total}] ✗ {rel} 异常({type(e).__name__}: {e})")
    print(f"共上传 {ok}/{total} -> {PUBLIC}/{r2_prefix}/")
    return ok, total


def cmd_upload_trade_sim():
    """上传 static-site/trade_sim_*.html 到 R2 trade_sim/ 前缀。

    R2 key = trade_sim/trade_sim_{id}.html（保留原文件名）。
    前端改 href -> https://ssd.fx8.store/trade_sim/trade_sim_{id}.html。
    """
    ts_dir = STATIC_DIR
    ok, total = _upload_glob(ts_dir, ["trade_sim_*.html"], "trade_sim")
    if total == 0:
        sys.exit(f"无 trade_sim html: {ts_dir}/trade_sim_*.html")
    if ok != total:
        sys.exit(1)


def cmd_upload_trade_sim_json():
    """上传 static-site/data/trade_sim/*.json + .gz 到 R2 trade_sim_data/ 前缀。

    R2 key = trade_sim_data/trade_sim_{id}_stats.json[.gz] + trade_sim_{id}_full.json[.gz]。
    前端改 fetchJSON -> https://ssd.fx8.store/trade_sim_data/trade_sim_{id}_stats.json。
    用 trade_sim_data/ 前缀避开现有 trade_sim/ HTML 前缀冲突。
    export.py 生成 100 品种 × (stats+full) × (.json+.gz) = 400 文件 ~275M。
    deploy.sh 调本命令同步 R2（2026-07-22 迁出 git，解决 s.sugas.site 300MB 超限 404）。
    """
    ts_dir = STATIC_DIR / "data/trade_sim"
    ok, total = _upload_glob(ts_dir, ["*.json", "*.json.gz"], "trade_sim_data")
    if total == 0:
        sys.exit(f"无 trade_sim json: {ts_dir}")
    if ok != total:
        sys.exit(1)


def cmd_upload_index():
    """上传 static-site/data/index/*.json + .gz 到 R2 index/ 前缀。

    R2 key = index/{id}-all.json[.gz]。
    前端改 fetchJSON -> https://ssd.fx8.store/index/{id}-all.json。
    intraday_snapshot 盘中会重写本地 index/{iid}-all.json，deploy.sh 调本命令同步 R2。
    """
    idx_dir = STATIC_DIR / "data/index"
    ok, total = _upload_glob(idx_dir, ["*.json", "*.json.gz"], "index")
    if total == 0:
        sys.exit(f"无 index json: {idx_dir}")
    if ok != total:
        sys.exit(1)


def cmd_upload_industry():
    """上传 static-site/data/industry-* 到 R2 industry/ 前缀（保留原相对路径）。

    覆盖：
      - industry-{all,5y,3y}-indices/{iid}.json + {iid}-detail.json + .gz
      - industry-{all,5y,3y}-meta.json + -concepts.json + .gz
      - industry-{1y,3m,6m,1m}.json + .gz（非拆分 range 单文件）
    R2 key = industry/{原 data/ 下相对路径}，如 industry/industry-all-indices/{iid}.json。
    前端改 fetchJSON ./data/industry-X -> https://ssd.fx8.store/industry/industry-X。
    intraday_snapshot 盘中会重算 write_industry_split 重写本地文件，deploy.sh 调本命令同步 R2。
    """
    data_dir = STATIC_DIR / "data"
    # 3 个拆分目录 + 扁平 industry-*.json[.gz]
    patterns = [
        "industry-all-indices/*", "industry-all-indices/*.gz",
        "industry-5y-indices/*", "industry-5y-indices/*.gz",
        "industry-3y-indices/*", "industry-3y-indices/*.gz",
        "industry-*.json", "industry-*.json.gz",
    ]
    ok, total = _upload_glob(data_dir, patterns, "industry")
    if total == 0:
        sys.exit(f"无 industry 文件: {data_dir}/industry-*")
    if ok != total:
        sys.exit(1)


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


def _latest_dated_key(prefix, name, bucket=None):
    """查 prefix/<name>_ 下最新带日期的 key,返回 (date_str, key) 或 None。
    用于周/月备份的"本周/本月首次"判断:对比最新 key 的日期与今天。"""
    import re
    bkt = bucket or BACKUP_BUCKET
    keys = _list_keys(f"{prefix}{name}_", bucket=bkt)
    dated = []
    for k in keys:
        m = re.search(r"(\d{8})\.db(?:\.gz)?$", k)
        if m:
            dated.append((m.group(1), k))
    if not dated:
        return None
    dated.sort(reverse=True)  # 日期降序,取最新
    return dated[0]


def _maybe_upload_weekly(name, payload, today_str, bucket=None):
    """若本周(ISO 周)尚未上传周备份,则上传一份(payload 复用日备份压缩内容)。

    判断:查 weekly/<name>_ 最新 key 日期,若与今天不在同一 ISO 年+周则上传。
    用 ISO week 而非自然周一,节假日跳过自动顺延到本周首个交易日上传。
    周备份 = 当日日备份的副本(同 gz 内容,不同 prefix),不额外压缩。"""
    import datetime as _dt
    bkt = bucket or BACKUP_BUCKET
    today = _dt.datetime.strptime(today_str, "%Y%m%d").date()
    today_iso = today.isocalendar()  # (ISO year, ISO week, ISO weekday)
    latest = _latest_dated_key("weekly/", name, bucket=bkt)
    if latest is not None:
        latest_date = _dt.datetime.strptime(latest[0], "%Y%m%d").date()
        latest_iso = latest_date.isocalendar()
        if latest_iso[:2] == today_iso[:2]:  # 同 ISO 年 + 周
            print(f"  周备份: 本周已有 {latest[1]}, 跳过")
            return False
    key = f"weekly/{name}_{today_str}.db.gz"
    status, data = s3_request("PUT", key, payload, bucket=bkt)
    if status == 200:
        print(f"  ✓ 周备份副本 -> {bkt}/{key} (本周首次)")
        return True
    print(f"  ⚠ 周备份上传失败 status={status} {data.decode('utf-8', errors='replace')[:200]}")
    return False


def _maybe_upload_monthly(name, payload, today_str, bucket=None):
    """若本月尚未上传月备份,则上传一份(payload 复用日备份压缩内容)。

    判断:查 monthly/<name>_ 最新 key 日期,若与今天不在同一年+月则上传。
    月备份 = 当日日备份的副本,保留 365 天(12 月),防长期损坏/误删。"""
    import datetime as _dt
    bkt = bucket or BACKUP_BUCKET
    today = _dt.datetime.strptime(today_str, "%Y%m%d").date()
    latest = _latest_dated_key("monthly/", name, bucket=bkt)
    if latest is not None:
        latest_date = _dt.datetime.strptime(latest[0], "%Y%m%d").date()
        if latest_date.year == today.year and latest_date.month == today.month:
            print(f"  月备份: 本月已有 {latest[1]}, 跳过")
            return False
    key = f"monthly/{name}_{today_str}.db.gz"
    status, data = s3_request("PUT", key, payload, bucket=bkt)
    if status == 200:
        print(f"  ✓ 月备份副本 -> {bkt}/{key} (本月首次)")
        return True
    print(f"  ⚠ 月备份上传失败 status={status} {data.decode('utf-8', errors='replace')[:200]}")
    return False


def _prune_layer(prefix, keep_days, bucket=None):
    """删 prefix 下日期 >keep_days 的 key(从 key 名解析 YYYYMMDD)。

    泛化版清理:backup/ weekly/ monthly/ 三层共用此函数。
    正则兼容 .db(旧)与 .db.gz(新,压缩上传后),避免旧 .db 残留堆积。"""
    import re, datetime as _dt
    bkt = bucket or BACKUP_BUCKET
    keys = _list_keys(prefix, bucket=bkt)
    cutoff = _dt.datetime.now() - _dt.timedelta(days=keep_days)
    deleted = 0
    for key in keys:
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
    return deleted


def _prune_r2_backup(keep_days=30, bucket=None):
    """分层清理 R2 备份(日/周/月三层独立清理):
      - backup/  日备份: keep_days (默认 30 天)
      - weekly/  周备份: 28 天 (4 周)
      - monthly/ 月备份: 365 天 (12 月)

    三层独立清理,防 7-30 天外及长期的损坏/误删。
    R2 桶 lifecycle 规则也配了同样天数(双保险:代码清理 + R2 自动过期)。
    历史 key 为 backup/<name>_YYYYMMDD.db,2026-07-15 起改压缩上传
    backup/<name>_YYYYMMDD.db.gz;weekly/monthly 自 2026-07 起新增,均为 .db.gz。"""
    bkt = bucket or BACKUP_BUCKET
    total = 0
    total += _prune_layer("backup/", keep_days, bucket=bkt)
    total += _prune_layer("weekly/", 28, bucket=bkt)
    total += _prune_layer("monthly/", 365, bucket=bkt)
    if total:
        print(f"{bkt} 分层清理共 {total} 个旧备份"
              f" (backup/ {keep_days}天 + weekly/ 28天 + monthly/ 365天)")


def cmd_upload_db():
    """每日 DB 备份推 R2（异地防盘毁）+ 分层滚动清理(日/周/月)。

    sentiment.db -> backup/sentiment_YYYYMMDD.db.gz (日备份,30天)
                -> weekly/sentiment_YYYYMMDD.db.gz  (周备份,本周首次,28天/4周)
                -> monthly/sentiment_YYYYMMDD.db.gz (月备份,本月首次,365天/12月)
    etf_national_team.db 同上(<name>=etf_national_team)。

    上传前 gzip 压缩（实测 sentiment.db 82MB->24MB,29%），R2 key 带 .gz 后缀。
    本地 .db 备份不变（backup_db.sh 仍存 .db，方便直接恢复），仅 R2 侧压缩。
    周月副本复用日备份已压缩的 payload(同 gz 内容,不同 prefix),不额外压缩。

    上传到 BACKUP_BUCKET(signal-backup 私有桶,不绑公开域名);
    _prune_r2_backup 分层清 signal-backup(backup/30 + weekly/28 + monthly/365)。
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
            # 日备份成功后,判断是否本周/本月首次,是则上传周/月副本(复用 payload)
            _maybe_upload_weekly(name, payload, today)
            _maybe_upload_monthly(name, payload, today)
        else:
            print(f"✗ {fname} status={status} {data.decode('utf-8', errors='replace')[:300]}")
    _prune_r2_backup(keep_days=30)
    print(f"DB 上传 {ok}/{len(targets)} -> {BACKUP_BUCKET}/backup/ ({today})")
    if ok != len(targets):
        sys.exit(1)


def cmd_download_latest_db(name, out_dir=None):
    """从 BACKUP_BUCKET 下载 backup/<name>_YYYYMMDD.db[.gz] 最新一份，返回解压后 .db 路径。

    用于 verify_backup.sh 恢复演练：列 backup/<name>_ 下所有 key，按 key 名日期降序
    取最新，GET 下载；若 key 带 .gz 后缀则 gunzip 解压后返回 .db 路径。
    兼容 .db（旧，2026-07-15 前）与 .db.gz（新，压缩上传后）两种格式（与
    _prune_r2_backup 正则一致）。

    进度信息 print 到 stderr，最终 .db 绝对路径 print 到 stdout（便于 bash 捕获）。
    out_dir=None 用临时目录；指定则放指定目录（verify_backup.sh 传统一临时目录）。
    """
    import re, gzip, tempfile
    keys = _list_keys(f"backup/{name}_", bucket=BACKUP_BUCKET)
    dated = []
    for k in keys:
        m = re.search(r"(\d{8})\.db(?:\.gz)?$", k)
        if m:
            dated.append((m.group(1), k))
    if not dated:
        sys.exit(f"无 {name} 备份 key in {BACKUP_BUCKET}/backup/{name}_*")
    dated.sort(reverse=True)  # 日期降序，取最新
    date_str, latest_key = dated[0]
    is_gz = latest_key.endswith(".gz")
    print(f"最新 {name} 备份: {BACKUP_BUCKET}/{latest_key} (日期 {date_str})", file=sys.stderr)
    status, data = s3_request("GET", latest_key, bucket=BACKUP_BUCKET)
    if status != 200:
        sys.exit(f"下载失败 {latest_key} status={status} {data.decode('utf-8', errors='replace')[:300]}")
    out_dir = out_dir or tempfile.mkdtemp(prefix=f"verify-{name}-")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / f"{name}_{date_str}.db"
    if is_gz:
        db_path.write_bytes(gzip.decompress(data))
        print(f"✓ 下载 {len(data)}B(gz) -> gunzip -> {db_path} ({db_path.stat().st_size}B)", file=sys.stderr)
    else:
        db_path.write_bytes(data)
        print(f"✓ 下载 {len(data)}B -> {db_path}", file=sys.stderr)
    print(str(db_path))  # 路径到 stdout，供 bash 捕获
    return str(db_path)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "list":
        prefix = sys.argv[2] if len(sys.argv) > 2 else ""
        cmd_list(prefix)
    elif cmd == "upload":
        cmd_upload(sys.argv[2], sys.argv[3])
    elif cmd == "upload-lab":
        cmd_upload_lab()
    elif cmd == "upload-trade-sim":
        cmd_upload_trade_sim()
    elif cmd == "upload-trade-sim-json":
        cmd_upload_trade_sim_json()
    elif cmd == "upload-index":
        cmd_upload_index()
    elif cmd == "upload-industry":
        cmd_upload_industry()
    elif cmd == "upload-db":
        cmd_upload_db()
    elif cmd == "download-db":
        # download-db <name> [out_dir]  从 signal-backup 下载最新 backup/<name>_YYYYMMDD.db[.gz]
        # 返回解压后 .db 路径(stdout)。用于 verify_backup.sh 恢复演练。
        name = sys.argv[2]
        out_dir = sys.argv[3] if len(sys.argv) > 3 else None
        cmd_download_latest_db(name, out_dir)
    elif cmd == "delete":
        # delete <key> [bucket]  bucket 默认 signal-data
        key = sys.argv[2]
        bucket = sys.argv[3] if len(sys.argv) > 3 else None
        cmd_delete(key, bucket)
    elif cmd == "clean-data-backup":
        cmd_clean_data_backup()
    else:
        sys.exit(
            "用法: upload_r2.py [list [prefix]|upload-lab|upload-trade-sim|"
            "upload-trade-sim-json|upload-index|upload-industry|upload-db|"
            "upload <local> <key>|delete <key> [bucket]|clean-data-backup]"
        )
