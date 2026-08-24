#!/usr/bin/env python3
"""R2 (S3 兼容) 上传 - Python 标准库 SigV4 签名(不依赖 boto3/awscli)。

凭证从 .env 读(.gitignore 已忽略)。用法:
  python3 scripts/upload_r2.py list                       # 列 bucket 对象
  python3 scripts/upload_r2.py upload <本地> <r2key>      # 上传单文件
  python3 scripts/upload_r2.py upload-lab                 # 上传 lab/*.json
  python3 scripts/upload_r2.py upload-trade-sim           # 上传 trade_sim_*.html -> trade_sim/
  python3 scripts/upload_r2.py upload-index               # 上传 data/index/*.json -> index/
  python3 scripts/upload_r2.py upload-industry            # 上传 data/industry-* -> industry/
  python3 scripts/upload_r2.py upload-public-fund         # 上传 data/public_fund* -> public_fund/
  python3 scripts/upload_r2.py upload-offshore-fund       # 上传 data/offshore_fund* -> offshore_fund/ (定时链已停用,仅手动使用)
  python3 scripts/upload_r2.py upload-data-large          # 上传 data/ 顶层 >1MB .json -> data/
  python3 scripts/upload_r2.py upload-all-data            # 上传 data/ 全量小 .json -> data/ (阶段1a双写)
  python3 scripts/upload_r2.py upload-db                  # 每日 DB 备份推 R2(signal-backup)
  python3 scripts/upload_r2.py upload-claude-backup [path] # Claude 自我备份 tar.gz -> signal-backup/claude-backup/
  python3 scripts/upload_r2.py download-db <name> [dir]   # 下载最新备份(解压后.db路径到stdout)
"""
import os, sys, re, hashlib, hmac, http.client, datetime, ssl, json, time
from pathlib import Path
from urllib.parse import urlparse, quote

# stdout 行缓冲:遇换行就 flush,防止 `| tee -a` 管道时 block-buffered
# 致 industry(268文件~10分钟)等长任务日志静默被误判卡死。
# Python 3.7+ 支持。覆盖 intraday/deploy/手动所有调用场景。
sys.stdout.reconfigure(line_buffering=True)

ROOT = Path(__file__).resolve().parent.parent
# 静态数据目录：优先用 REPO env(launchd 设 trade-data,采集器写此处),
# 回退 ROOT(trade)。trade-data/scripts 是 trade/scripts 的 symlink,
# ROOT 经 .resolve() 解析到 trade/,但采集器写 trade-data/static-site/data/,
# 故 upload 命令必须用 REPO 才能读到采集器刚写的实时数据(非 deploy rsync 后的 trade/)。
STATIC_DIR = Path(os.environ.get("REPO", str(ROOT))) / "static-site"


# ---- REPO 缺省分级闸 (2026-08-22, #75) ----
# 捕获须在 load_env() 之前(下方 L146),防 .env setdefault 污染判定(加注释钉死顺序)。
_RAW_REPO = os.environ.get("REPO")            # 原始 env,捕获时机早于 load_env
REPO_EXPLICIT = bool(_RAW_REPO)

# A 类与 REPO 无关(读显式路径或私有桶固定 key)→ 放行
_A_CLASS = {"list", "upload", "upload-claude-backup", "download-db", "delete", "clean-data-backup"}
# B 类 design 合法回退:生成器按 __file__ 写 trade 树,trade-data 侧天然缺/滞后(update_lab.sh rsync 补偿)→ 白名单放行
_TRADE_FALLBACK_OK = {"upload-lab", "upload-trade-sim", "upload-trade-sim-json"}


def guard_repo_default(cmd: str) -> None:
    """REPO 缺省(手动裸跑)分级闸;dispatch 层 cmd 解析后立即调用(见 docs/r2-upload-repo-guard-plan-20260822.md)。

    显式态(launchd/force_env/export.py 注入 REPO)零行为变化,信任调用方;
    只拦真正危险的「缺省 + 非白名单」组合,防旧数据盖线上。
    未列入 A/B 白名单的其余命令(含 upload-kelly-parts / C 类 11 个数据上传命令)一律 exit 3 拒绝。
    """
    if REPO_EXPLICIT:
        return                                  # 显式态:launchd/force_env/export.py,信任调用方
    if cmd in _A_CLASS:
        return
    if cmd in _TRADE_FALLBACK_OK:
        print(f"ℹ REPO 未设,{cmd} 按 design 回退 trade 树产物", file=sys.stderr)
        return
    if cmd == "purge-low-freq":
        print("⚠ REPO 未设:purge 集合按 trade 侧扫描,可能与 trade-data 有差异", file=sys.stderr)
        return
    print(
        f"✗ REPO 未设:STATIC_DIR 将回退 {ROOT}/static-site(trade 旧库快照),\n"
        f"  拒绝上传 {cmd}(防旧数据盖线上,2026-08-19 intraday 事故同类)\n"
        f"  正确跑法:REPO=/Users/linhuichen/code/trade-data python scripts/upload_r2.py {cmd}",
        file=sys.stderr,
    )
    sys.exit(3)


# ---- 防「盘中手动 upload 未带 REPO → 读 trade 侧旧库整体覆盖 R2」哨兵 (2026-08-19) ----
# 事故:agent 手动跑 `upload_r2.py upload-intraday` 未带 REPO= env,STATIC_DIR 缺省回退到
# ROOT=trade/static-site,抓走 trade 侧 8-18 旧库整体覆盖 R2,线上退回旧数据。
# 定时链路安全:launchd intraday plist 显式设 REPO=trade-data,intraday_snapshot.sh:25-28 也 export REPO,
# 故定时读 trade-data 新库正确;唯一区别是手动命令没继承 REPO → 退化成读 trade 旧库。
# 正确手动跑法(必须显式 REPO,缺省即读 trade 旧库覆盖线上):
#   REPO=/Users/linhuichen/code/trade-data python scripts/upload_r2.py upload-intraday
_TRADE_STATIC = str((Path("/Users/linhuichen/code/trade") / "static-site").resolve())


def _is_trade_side_dir() -> bool:
    """当前 STATIC_DIR 是否落在 trade/static-site(非 trade-data/static-site)。

    launchd 定时(REPO=trade-data)解析到 trade-data/static-site,不命中;
    手动未带 REPO 时 STATIC_DIR=ROOT=trade/static-site,命中 → 读滞后库风险。
    """
    s = str(STATIC_DIR.resolve() if STATIC_DIR.is_absolute() else STATIC_DIR)
    return s == _TRADE_STATIC or "/trade/static-site" in s


def _is_trading_day() -> bool:
    """复用项目 app.calendar.is_trading_day(读 data/trade_dates.txt,__file__ 定位不受 cwd 影响);
    异常(如 app 不可导入)降级为周末判断。
    真实降级路径:`python scripts/upload_r2.py` 的 sys.path[0]=scripts/,`from app.calendar` 触发
    ModuleNotFoundError(scripts/ 下无 app 包)→ caught 降级到工作日(weekday<5)判断。
    工作日⊇交易日,降级只会多拦(工作日节假日盘中误拦本就不会有对应实时 upload),安全侧保守,不构成漏拦/数据风险。
    要严格读交易日历,须以 repo 根为 sys.path 跑(如 `python scripts/upload_r2.py`,`app` 在 repo 根可直接导入)。"""
    try:
        from app.calendar import is_trading_day
        return bool(is_trading_day())
    except Exception:
        return datetime.date.today().weekday() < 5


def _is_intraday_hours() -> bool:
    """北京时区 09:30-15:30 盘中窗口。"""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.datetime.now(ZoneInfo("Asia/Shanghai"))
    except Exception:
        now = datetime.datetime.now()  # 降级本地时区(本机即北京)
    hhmm = now.strftime("%H%M")
    return "0930" <= hhmm <= "1530"


def _guard_upload_intraday():
    """盘中 + 读 trade 侧 → abort,防旧库整体覆盖 R2。仅双条件同时成立才拒(盘后跑 trade 侧正常放行)。

    判别口径:①STATIC_DIR 落在 trade/static-site(非 trade-data) ②交易日盘中(09:30-15:30 北京)。
    退出码非 0,不执行上传。
    """
    if not _is_trade_side_dir():
        return
    if not (_is_trading_day() and _is_intraday_hours()):
        return
    print("⚠ 疑似读滞后库:STATIC_DIR 落在 trade 侧(非 trade-data),盘中拒绝 upload-intraday,防覆盖线上",
          file=sys.stderr)
    print("   正确手动跑法:REPO=/Users/linhuichen/code/trade-data python scripts/upload_r2.py upload-intraday",
          file=sys.stderr)
    sys.exit(2)


# ⚠ 方案4一致性兜底已废弃(2026-08-19 reviewer 返修):原想加「REPO 显式但 STATIC_DIR 源根≠REPO 拒传」
# 的独立闸(exit3),但结构上不成立:STATIC_DIR = Path(REPO or ROOT)/"static-site" 在模块加载时由 REPO
# 一次性派生,static_root==repo_root 恒成立,故「源根≠REPO」在物理上永不发生,该闸结构性不可达、无可拦截面。
# 实际拦截由上方方案2(`_guard_upload_intraday`)承担。此处只保留说明,不再实现假兜底,防后续误读为独立防护。
# 若未来有人想加「REPO 一致性校验」,须换掉「由 REPO 派生 STATIC_DIR」的既有机制(改模块级派生或运行时重解析),否则同样死锁。


def _find_env():
    """按优先级找 .env：脚本所在 ROOT/.env -> $GIT_REPO/.env -> $REPO/.env -> 默认 trade 仓库。
    背景：launchd 实际在 trade-data/（运行副本）下跑，trade-data/.env 不存在，
    需回退到 trade/.env（git 仓库，凭证源头）。"""
    candidates = [ROOT / ".env"]
    git_repo = os.environ.get("GIT_REPO")
    if git_repo:
        candidates.append(Path(git_repo) / ".env")
    # REPO/.env（trade-data/.env）含 PURGE_SECRET 等 Worker 相关凭证，
    # ROOT/.env（trade/.env）可能不含，需追加查找。
    repo = os.environ.get("REPO")
    if repo:
        candidates.append(Path(repo) / ".env")
    candidates.append(Path("/Users/linhuichen/code/trade/.env"))
    for c in candidates:
        if c.exists():
            return c
    return None


def load_env():
    envf = _find_env()
    if envf is None:
        sys.exit(f"无 .env: 尝试过 {[str(c) for c in [ROOT/'.env', Path(os.environ.get('GIT_REPO',''))/'.env'] if c]}")
    # 加载所有存在的 .env 文件（setdefault 不覆盖已设变量，后加载的只补充缺失的如 PURGE_SECRET）
    loaded_any = False
    for c in [ROOT / ".env",
              Path(os.environ.get("GIT_REPO", "")) / ".env" if os.environ.get("GIT_REPO") else None,
              Path(os.environ.get("REPO", "")) / ".env" if os.environ.get("REPO") else None,
              Path("/Users/linhuichen/code/trade/.env")]:
        if c and c.exists():
            for line in c.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
            loaded_any = True
    if not loaded_any:
        sys.exit(f"无 .env: 尝试过 {[str(c) for c in [ROOT/'.env'] if c]}")


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
    ".xml": "application/rss+xml; charset=utf-8",
    ".gz": "application/gzip",
    ".mp3": "audio/mpeg",  # edge-tts AI预测语音播报(docs/ai-predict/ai-predict-tts-plan.md)
}


def s3_request(method, key, payload=b"", query="", bucket=None, content_type=None):
    """path-style: /BUCKET/key, host = endpoint host。bucket=None 用默认 BUCKET。

    带连接超时(30s)+ 重试(5 次,SSL/连接错退避 1s/2s/4s/8s),防 R2 偶发断连致脚本挂死。
    content_type=None 时按 key 扩展名推断(_CONTENT_TYPE_MAP),未知扩展名回退 application/octet-stream。
    """
    if content_type is None:
        ext = os.path.splitext(key)[1].lower()
        content_type = _CONTENT_TYPE_MAP.get(ext, "application/octet-stream")
    bkt = bucket or BUCKET
    last_exc = None
    for attempt in range(5):
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
            # HTTP 5xx 重试(R2 S3 API 偶发 InternalError,与网络异常重试对称)。
            # R2 侧偶发 500 InternalError 自愈,重试 1-2 次通常即成功,避免单文件 5xx
            # 致整批 ok!=total -> intraday 告警邮件轰炸(2026-07-30 修复)。
            # attempt 0-3 重试(sleep 1s/2s/4s/8s),attempt 4(最后一次)return 让调用方记失败。
            if resp.status >= 500 and attempt < 4:
                import time
                wait = 2 ** attempt  # 1s, 2s, 4s, 8s
                print(f"  ⚠ {method} {key} HTTP {resp.status} attempt {attempt+1}, {wait}s 后重试", file=sys.stderr)
                time.sleep(wait)
                continue
            return resp.status, data
        except (ssl.SSLError, OSError, http.client.HTTPException) as e:
            last_exc = e
            if attempt < 4:
                import time
                wait = 2 ** attempt  # 1s, 2s, 4s, 8s
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
    # lab JSON 由 scripts/lab/*.py 按 __file__ 写 ROOT(trade/)static-site/data/lab/,
    # REPO=trade-data 时 trade-data/static-site/data/lab/ 可能不存在(或滞后),回退 ROOT。
    lab = STATIC_DIR / "data/lab"
    if not lab.exists() or not any(lab.glob("*.json")):
        lab = ROOT / "static-site" / "data" / "lab"
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


def _upload_glob(local_dir, glob_patterns, r2_prefix, include_gz=True, exclude_fn=None,
                 only_files=None):
    """通用 glob 上传：local_dir 下按 patterns 匹配文件，上传到 R2 r2_prefix/。

    R2 key = r2_prefix/{相对 local_dir 的路径}。返回 (ok, total, failed_rels, uploaded_keys)。
    only_files(可选, 2026-08-23): 显式文件列表(Path 列表, 须位于 local_dir 下), 非 None 时
    跳过 glob 直接上传该列表 —— cmd_upload_etf_hist 增量上传用(调用方先按状态清单筛出
    有变化的文件)。glob_patterns 此时仅占位不参与匹配; exclude_fn 同样不生效(调用方已筛)。
    failed_rels = 失败文件的 rel 列表(相对 local_dir 的路径,如 sw_801030-all.json),
    供调用方(cmd_upload_index)打印 FAILED_FILES 行供 intraday_snapshot.sh 抓取引用到告警 body。
    uploaded_keys = 成功上传的 R2 key 列表(如 ["industry/industry-all.json"]),
    供调用方调 purge_cache 清 CF edge 缓存。
    include_gz 参数已废弃(.gz 不再生成,CF 自动 br 压缩替代)。
    exclude_fn: 可选回调 (Path) -> bool,返回 True 则跳过该文件(如 upload-all-data 排除
    已在独立命令处理的文件,避免双副本上传)。
    单文件失败(重试3次仍错)不中断整批,继续上传后续文件。

    并发上传(ThreadPoolExecutor 8 线程)：186 文件串行 3-5min -> 并发约 30-60s。
    R2 S3 API 支持并发(AWS SDK 默认 10-20 并发),8 线程保守安全;
    每线程独立 HTTPSConnection(无共享状态),ssl.SSLContext 线程安全。
    2026-07-24: intraday 频率从 30min 缩 15min,采集需 <7min,R2 串行成瓶颈,改并发。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    local_dir = Path(local_dir)
    if only_files is not None:
        # 显式列表模式:跳过 glob 与 exclude_fn,直接用调用方筛好的文件集。
        files = sorted(set(Path(f) for f in only_files))
    else:
        files = []
        for pat in glob_patterns:
            files.extend(local_dir.glob(pat))
        # 去重 + 排序
        files = sorted(set(files))
        # exclude_fn 过滤(如 upload-all-data 排除已在独立命令处理的文件,避免双副本)
        if exclude_fn:
            before = len(files)
            files = [f for f in files if not exclude_fn(f)]
            excluded = before - len(files)
            if excluded:
                print(f"  排除 {excluded} 个文件(已在独立命令处理)")
    # 方案3 通用防护:过滤 broken symlink / 不存在文件(glob 把 broken symlink 也算匹配,
    # exists() 对 broken symlink 返回 False)。trade-data/static-site/ 的 trade_sim_*.html
    # symlink 指向 trade/static-site/,目标被删时 symlink 变 broken,read_bytes 会抛
    # FileNotFoundError;此处提前过滤避免 _upload_one 撞 broken symlink。
    broken = [f for f in files if not f.exists()]
    if broken:
        print(f"⚠ 跳过 {len(broken)} 个不存在/broken-symlink 文件(首个: {broken[0]})")
        files = [f for f in files if f.exists()]
    if not files:
        print(f"⚠ {local_dir} 下 {glob_patterns} 无匹配文件")
        return 0, 0, [], []
    total = len(files)

    def _upload_one(idx_f):
        i, f = idx_f
        rel = f.relative_to(local_dir)
        key = f"{r2_prefix}/{rel}"
        try:
            # 方案2:read_bytes 移进 try 块。broken symlink 的 read_bytes() 抛
            # FileNotFoundError,原代码在 try 外面不捕获致 _upload_glob 整批崩溃
            # (违背 docstring "单文件失败不中断整批"承诺)。移进 try 后单文件失败
            # 仅记日志跳过,不影响其他文件上传。
            payload = f.read_bytes()
            size = len(payload)
            status, data = s3_request("PUT", key, payload)
            if status == 200:
                return (i, True, rel, size, None, key)
            return (i, False, rel, size, f"status={status} {data[:200]}", None)
        except (OSError, FileNotFoundError) as e:
            # 文件读失败(broken symlink/权限/IO 错):size 未知填 0,跳过该文件继续整批
            return (i, False, rel, 0, f"读文件失败({type(e).__name__}: {e})", None)
        except Exception as e:
            return (i, False, rel, 0, f"异常({type(e).__name__}: {e})", None)

    ok = 0
    failed_rels = []
    uploaded_keys = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_upload_one, (i, f)) for i, f in enumerate(files, 1)]
        done = 0
        for fut in as_completed(futures):
            i, success, rel, size, err, key = fut.result()
            done += 1
            if success:
                ok += 1
                uploaded_keys.append(key)
                print(f"[{done}/{total}] ✓ {rel} ({size}B)")
            else:
                print(f"[{done}/{total}] ✗ {rel} {err}")
                failed_rels.append(str(rel))
    print(f"共上传 {ok}/{total} -> {PUBLIC}/{r2_prefix}/")
    return ok, total, failed_rels, uploaded_keys


def cmd_upload_trade_sim():
    """上传 static-site/trade_sim_*.html 到 R2 trade_sim/ 前缀。

    R2 key = trade_sim/trade_sim_{id}.html（保留原文件名）。
    前端改 href -> https://ssd.fx8.store/trade_sim/trade_sim_{id}.html。
    """
    # simulate_trade.py 按 __file__ 写 ROOT(trade/)static-site/trade_sim_*.html,
    # REPO=trade-data 时 trade-data/static-site/ 可能无 trade_sim_*.html,回退 ROOT。
    ts_dir = STATIC_DIR
    # 方案3:any() 判断用 exists() 过滤,避免 broken symlink 误判"有文件"不回退 ROOT。
    # glob 把 broken symlink 也算匹配(返回 symlink Path 对象),any() 为 True 不回退;
    # 用 exists()(对 broken symlink 返回 False)判断是否真有可上传文件。
    if not any(f.exists() for f in ts_dir.glob("trade_sim_*.html")):
        ts_dir = ROOT / "static-site"
    ok, total, _, _ = _upload_glob(ts_dir, ["trade_sim_*.html"], "trade_sim")
    if total == 0:
        sys.exit(f"无 trade_sim html: {ts_dir}/trade_sim_*.html")
    if ok != total:
        sys.exit(1)


def cmd_upload_trade_sim_json():
    """上传 static-site/data/trade_sim/*.json 到 R2 trade_sim_data/ 前缀。

    R2 key = trade_sim_data/trade_sim_{id}_stats.json + trade_sim_{id}_full.json。
    前端改 fetchJSON -> https://ssd.fx8.store/trade_sim_data/trade_sim_{id}_stats.json。
    用 trade_sim_data/ 前缀避开现有 trade_sim/ HTML 前缀冲突。
    export.py 生成 100 品种 × (stats+full) × (.json) = 400 文件 ~275M。
    deploy.sh 调本命令同步 R2（2026-07-22 迁出 git，解决 s.sugas.site 300MB 超限 404）。

    simulate_trade.py 按 __file__ 写 ROOT(trade/)static-site/data/trade_sim/（非 REPO）,
    REPO=trade-data 时 trade-data/static-site/data/trade_sim/ 不存在,回退 ROOT(trade/)。
    （2026-07-25 AZ28 根治:此前 deploy.sh 从 trade-data 跑时本命令 sys.exit 无文件）
    """
    ts_dir = STATIC_DIR / "data/trade_sim"
    if not ts_dir.exists() or not any(ts_dir.glob("*.json")):
        ts_dir = ROOT / "static-site" / "data" / "trade_sim"
    ok, total, _, uploaded_keys = _upload_glob(ts_dir, ["*.json"], "trade_sim_data")
    if total == 0:
        sys.exit(f"无 trade_sim json: {ts_dir}")
    if ok != total:
        sys.exit(1)
    # 清 CF 边缘缓存(同其他 R2 前缀命令模式):uploaded_keys 含 "trade_sim_data/" 前缀,
    # cache_prefix="/r2/" -> "/r2/trade_sim_data/{id}_stats.json" 匹配 r2ProxyHandler cacheKey。
    # 2026-08-19 补:此前本命令从不 purge, trade_sim JSON 在 CF edge 残留最长 4h,
    # 19:00 重跑后被旧快照遮挡新费率数据(cmd_purge_low_freq 也只扫 data/ 顶层不递归此子目录)。
    purge_cache(uploaded_keys, cache_prefix="/r2/")


def cmd_upload_index():
    """上传 static-site/data/index/*.json 到 R2 index/ 前缀。

    R2 key = index/{id}-all.json。
    前端改 fetchJSON -> https://ssd.fx8.store/index/{id}-all.json。
    intraday_snapshot 盘中会重写本地 index/{iid}-all.json，deploy.sh 调本命令同步 R2。
    """
    idx_dir = STATIC_DIR / "data/index"
    ok, total, failed_rels, uploaded_keys = _upload_glob(idx_dir, ["*.json"], "index")
    if total == 0:
        sys.exit(f"无 index json: {idx_dir}")
    if ok != total:
        # 打印失败文件清单供 intraday_snapshot.sh 抓取引用到告警 body(改动2)。
        # 格式: FAILED_FILES: rel1, rel2, ... (rel 是相对 static-site/data/index/ 的路径)
        print(f"FAILED_FILES: {', '.join(failed_rels)}")
        sys.exit(1)
    # 清 CF 边缘缓存(同 cmd_upload_industry 模式):uploaded_keys 含 "index/" 前缀,
    # cache_prefix="/r2/" -> "/r2/index/{id}-all.json" 匹配 r2ProxyHandler cacheKey。
    # 不用 "/r2/index/" 否则双 index 致 purge 无效。
    purge_cache(uploaded_keys, cache_prefix="/r2/")


def cmd_upload_etf_hist():
    """上传 static-site/data/etf/*.json 到 R2 etf/ 前缀(#10 ETF 弹窗长历史, 2026-08-22)。

    R2 key = etf/{code}-all.json(1532 只全史日K, scripts/export_etf_hist.py 生成)。
    前端 ETF 评分弹窗 period tab 懒加载 fetchJSON -> https://ss.fx8.store/r2/etf/{code}-all.json
    (同 cmd_upload_index 模式:硬编码 R2 URL + /r2/ 代理路由)。
    §8.1 按前缀建独立命令; etf/ 子目录不被 upload-data-large/upload-all-data 的非递归
    *.json glob 覆盖, 无双副本风险。update_all.sh / deploy.sh 已接入本命令。

    增量上传(2026-08-23, 根治 deploy upload-etf-hist 300s 超时告警):
      背景: export_etf_hist.py 每次(每日 update_all 17:50)无条件重写全部 1532 文件,
      且 payload 含当天 exported_at 字段 → 文件内容天天变 + 总量随每日新增 K 线累积
      缓慢变大, 全量 PUT ~87MB 在 run_r2_upload 的超时线上间歇性被 kill 触发告警。
      机制: 本地状态清单 data/.r2_etf_hist_state.json(code 文件名→数据本体指纹),
      只传指纹有变化的文件:
      - 指纹 = md5(json 规范化后序列化, 剔除 exported_at 字段)。为什么不用 size+mtime:
        export 每天全量重写所有文件 mtime 全变, mtime 口径会天天判「全变」致增量失效;
        为什么剔除 exported_at: 它天天变但与数据本体无关(前端零消费, 已 grep 核实),
        不剔除则同样天天判全变。数据本体(ohlc/name/count/date 等)真变了才传,
        免疫 touch/复制等纯 mtime 抖动。
      - 首跑/状态缺失或损坏 → 自动退化为全量;
      - 每周日强制全量一次(防「R2 侧对象丢失/损坏而本地状态无感知」的漂移);
      - 状态只在全部上传成功后 tmp+os.replace 原子更新;部分失败保持旧状态,
        下次重传面更大 —— 失败方向宁多传不漏传;
      - 并发不变(_upload_glob 内置 8 线程); purge_cache 只清本次实际上传的 key。
    """
    etf_dir = STATIC_DIR / "data/etf"
    all_json = sorted(p for p in etf_dir.glob("*.json") if p.is_file())
    if not all_json:
        sys.exit(f"无 etf json: {etf_dir} (先跑 scripts/export_etf_hist.py 生成)")

    # 状态清单与数据同仓: X/static-site/data/etf -> X/data/.r2_etf_hist_state.json
    state_path = etf_dir.parents[2] / "data" / ".r2_etf_hist_state.json"
    old_files = {}
    if state_path.exists():
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                st = json.load(f)
            if isinstance(st.get("files"), dict):
                old_files = st["files"]
        except (OSError, ValueError):
            print(f"[etf-hist] ⚠ 状态清单损坏/不可读({state_path}),退化为全量")
            old_files = {}

    def _fingerprint(path):
        """数据本体指纹: json 解析剔除 exported_at 后规范化序列化取 md5。
        解析失败(截断/坏 json)退化为整文件字节 md5 —— 坏文件必与上次不同 → 触发重传,
        失败方向宁多勿漏。json.dumps(sort_keys=True) 同一解释器内序列化稳定,
        若跨版本序列化差异导致误判变化也只是多传, 不漏传。"""
        raw = None
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                payload.pop("exported_at", None)
                raw = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":"))
        except (OSError, ValueError):
            raw = None
        if raw is None:
            return hashlib.md5(path.read_bytes()).hexdigest()
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    t0 = time.time()
    sigs = {p.name: _fingerprint(p) for p in all_json}
    today_weekday = datetime.date.today().weekday()   # Monday=0 ... Sunday=6
    force_full = (not old_files) or today_weekday == 6
    if force_full:
        mode = "周日强制全量" if today_weekday == 6 and old_files else "首次/无状态全量"
        changed = list(all_json)
    else:
        mode = "增量"
        changed = [p for p in all_json if old_files.get(p.name) != sigs[p.name]]
    print(f"[etf-hist] 模式={mode} 本次待传 {len(changed)}/{len(all_json)}"
          f"(其余 {len(all_json) - len(changed)} 个内容未变化跳过)")

    def _save_state(path, sig_map, run_mode):
        """原子写状态清单(tmp + os.replace, 防半截状态被读到); 仅在上传全部成功后调用。
        状态重建为本次扫描全集, 本地已删除的条目自然剔除(R2 残留旧 key 无害, 不做删除)。"""
        new_state = {
            "version": 1,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "mode": run_mode,
            "count": len(sig_map),
            "files": sig_map,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(path.name + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(new_state, f, ensure_ascii=False, sort_keys=True)
        os.replace(tmp_path, path)

    if not changed:
        # 增量 0 待传是正常路径(全部内容未变化): 直接完成, 不算失败。
        # (不能落到下方 total==0 判错 —— 那会让 deploy 把「今天没变化」当上传失败告警)
        elapsed = time.time() - t0
        print(f"[etf-hist] ✓ 全部 {len(all_json)} 个内容未变化, 无需上传, 耗时 {elapsed:.1f}s")
        _save_state(state_path, sigs, mode)
        return

    ok, total, failed_rels, uploaded_keys = _upload_glob(
        etf_dir, ["*.json"], "etf", only_files=changed)
    elapsed = time.time() - t0
    if total == 0:
        sys.exit(f"无 etf json 可传: {etf_dir}")
    print(f"[etf-hist] ✓ 上传完成 {ok}/{total},耗时 {elapsed:.1f}s "
          f"(较全量少传 {len(all_json) - total} 个)")

    if ok != total:
        # 有失败:保持旧状态不更新(本次成功的文件下次会重传, 宁多勿漏), 告警交由调用方。
        print(f"FAILED_FILES: {', '.join(failed_rels)}")
        sys.exit(1)

    # 全部成功才写状态(部分失败保持旧状态, 下次重传更多 —— 宁多勿漏)。
    _save_state(state_path, sigs, mode)

    # 清 CF 边缘缓存(同 cmd_upload_index 模式):cache_prefix="/r2/" ->
    # "/r2/etf/{code}-all.json" 匹配 r2ProxyHandler cacheKey。只 purge 本次实际上传的
    # key(未变化的文件 R2 上就是最新版, edge 缓存无需失效)。
    purge_cache(uploaded_keys, cache_prefix="/r2/")


def cmd_upload_fund_nav():
    """上传 static-site/data/fund_nav/*.json 到 R2 fund_nav/ 前缀(#11 基金弹窗净值走势, 2026-08-25)。

    R2 key = fund_nav/{code}.json(26118 只全史净值, scripts/export_fund_nav.py 生成)。
    前端基金评分弹窗「净值走势」period tab 懒加载 fetchJSON ->
    https://ss.fx8.store/r2/fund_nav/{code}.json(复刻 etf/{code}-all.json 模式:
    worker /r2/ 为通用 key 代理无前缀白名单, 新前缀零 worker 改动)。
    §8.1 按前缀建独立命令; fund_nav/ 子目录不被 upload-data-large/upload-all-data 的
    非递归 *.json glob 覆盖, 无双副本风险(已核 glob 实现 L809)。已接入 update_all.sh / deploy.sh。

    增量指纹上传(复刻 cmd_upload_etf_hist 机制, 简化点):
      - 指纹 = 整文件字节 md5。export_fund_nav.py **不放 exported_at 字段**(与 etf-hist
        的差异), 文件内容只在净值序列真变化时变化 -> 无需 json 解析剔除逻辑;
        清盘老基金序列冻结 -> 内容不变 -> 指纹不变 -> 自然跳过, 每日真重传仅活跃基金。
      - 首跑/状态缺失或损坏 → 自动退化为全量;
      - 每周日强制全量一次(防「R2 侧对象丢失而本地状态无感知」漂移, 同 etf-hist);
      - 状态只在全部上传成功后 tmp+os.replace 原子更新;部分失败保持旧状态下次重传
        —— 失败方向宁多传不漏传;
      - 体量提示: 全量 ~700MB(26118 只 x ~26KB), 日增量=当日有新净值的活跃基金
        (~1-2 万只 x 单文件整传); 上游超时由调用方 run_r2_upload 1800s 承接,
        失败不阻塞 deploy 主流程(与 upload-etf-hist 同策略)。
    """
    nav_dir = STATIC_DIR / "data/fund_nav"
    all_json = sorted(p for p in nav_dir.glob("*.json") if p.is_file())
    if not all_json:
        sys.exit(f"无 fund_nav json: {nav_dir} (先跑 scripts/export_fund_nav.py 生成)")

    # 状态清单与数据同仓: X/static-site/data/fund_nav -> X/data/.r2_fund_nav_state.json
    state_path = nav_dir.parents[2] / "data" / ".r2_fund_nav_state.json"
    old_files = {}
    if state_path.exists():
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                st = json.load(f)
            if isinstance(st.get("files"), dict):
                old_files = st["files"]
        except (OSError, ValueError):
            print(f"[fund-nav] ⚠ 状态清单损坏/不可读({state_path}),退化为全量")
            old_files = {}

    def _fingerprint(path):
        """数据本体指纹: 整文件字节 md5(payload 无 exported_at, 内容只在数据变时变)。"""
        return hashlib.md5(path.read_bytes()).hexdigest()

    t0 = time.time()
    sigs = {p.name: _fingerprint(p) for p in all_json}
    today_weekday = datetime.date.today().weekday()   # Monday=0 ... Sunday=6
    force_full = (not old_files) or today_weekday == 6
    if force_full:
        mode = "周日强制全量" if today_weekday == 6 and old_files else "首次/无状态全量"
        changed = list(all_json)
    else:
        mode = "增量"
        changed = [p for p in all_json if old_files.get(p.name) != sigs[p.name]]
    print(f"[fund-nav] 模式={mode} 本次待传 {len(changed)}/{len(all_json)}"
          f"(其余 {len(all_json) - len(changed)} 个内容未变化跳过)")

    def _save_state(path, sig_map, run_mode):
        """原子写状态清单(tmp + os.replace); 仅在上传全部成功后调用。
        状态重建为本次扫描全集, 本地已删除条目自然剔除(R2 残留旧 key 无害)。"""
        new_state = {
            "version": 1,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "mode": run_mode,
            "count": len(sig_map),
            "files": sig_map,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(path.name + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(new_state, f, ensure_ascii=False, sort_keys=True)
        os.replace(tmp_path, path)

    if not changed:
        elapsed = time.time() - t0
        print(f"[fund-nav] ✓ 全部 {len(all_json)} 个内容未变化, 无需上传, 耗时 {elapsed:.1f}s")
        _save_state(state_path, sigs, mode)
        return

    ok, total, failed_rels, uploaded_keys = _upload_glob(
        nav_dir, ["*.json"], "fund_nav", only_files=changed)
    elapsed = time.time() - t0
    if total == 0:
        sys.exit(f"无 fund_nav json 可传: {nav_dir}")
    print(f"[fund-nav] ✓ 上传完成 {ok}/{total},耗时 {elapsed:.1f}s "
          f"(较全量少传 {len(all_json) - total} 个)")

    if ok != total:
        print(f"FAILED_FILES: {', '.join(failed_rels)}")
        sys.exit(1)

    _save_state(state_path, sigs, mode)
    purge_cache(uploaded_keys, cache_prefix="/r2/")


def cmd_upload_industry():
    """上传 static-site/data/industry-* 到 R2 industry/ 前缀（保留原相对路径）。

    覆盖：
      - industry-{all,5y,3y}-indices/{iid}.json + {iid}-detail.json
      - industry-{all,5y,3y}-meta.json + -concepts.json
      - industry-{1y,3m,6m,1m}.json（非拆分 range 单文件）
    R2 key = industry/{原 data/ 下相对路径}，如 industry/industry-all-indices/{iid}.json。
    前端改 fetchJSON ./data/industry-X -> https://ssd.fx8.store/industry/industry-X。
    intraday_snapshot 盘中会重算 write_industry_split 重写本地文件，deploy.sh 调本命令同步 R2。
    """
    data_dir = STATIC_DIR / "data"
    # 3 个拆分目录 + 扁平 industry-*.json
    patterns = [
        "industry-all-indices/*",
        "industry-5y-indices/*",
        "industry-3y-indices/*",
        "industry-*.json",
    ]
    ok, total, _, uploaded_keys = _upload_glob(data_dir, patterns, "industry")
    if total == 0:
        sys.exit(f"无 industry 文件: {data_dir}/industry-*")
    if ok != total:
        sys.exit(1)
    purge_cache(uploaded_keys, cache_prefix="/r2/")


def cmd_upload_public_fund():
    """上传 static-site/data/public_fund*.json 到 R2 public_fund/ 前缀(按类别,无大小阈值)。

    覆盖当前 5 小样本 + 未来全量品种(public_fund-{id}-holdings-5y.json 等)。
    架构同 lab/index/industry(按路径前缀,非大小阈值),新增品种自动走 R2 零维护。
    """
    data_dir = STATIC_DIR / "data"
    ok, total, _, uploaded_keys = _upload_glob(data_dir, ["public_fund*.json"], "public_fund")
    if total == 0:
        print(f"⚠ 无 public_fund json: {data_dir}/public_fund*.json")
        return
    if ok != total:
        sys.exit(1)
    purge_cache(uploaded_keys, cache_prefix="/r2/")


def cmd_upload_offshore_fund():
    """上传 static-site/data/offshore_fund*.json 到 R2 offshore_fund/ 前缀。

    ⚠ 定时链已停用(2026-08-22 P2-15, 用户确认): update_all.sh/deploy.sh 不再调用, 仅手动使用(#84 未来用 export_offshore_fund.py 生成后手动上传)。
    筛选器阶段0(2026-08-02 新增): 7 类 JSON(5 大文件 >1MB + 2 小文件, 全量后均大)。
    按类别走 R2(§8.1 新类别按前缀建独立命令, 不依赖 1MB 阈值兜底)。
    offshore_fund_basic 13MB / performance 5.8MB / manager 6.7MB / purchase_status 4.9MB / rating 2.4MB。
    """
    data_dir = STATIC_DIR / "data"
    ok, total, _, uploaded_keys = _upload_glob(data_dir, ["offshore_fund*.json"], "offshore_fund")
    if total == 0:
        print(f"⚠ 无 offshore_fund json: {data_dir}/offshore_fund*.json")
        return
    if ok != total:
        sys.exit(1)
    purge_cache(uploaded_keys, cache_prefix="/r2/")


def cmd_upload_fund_score():
    """上传 static-site/data/fund_score*.json 到 R2 fund_score/ 前缀。

    阶段1 评分引擎(2026-07-20 新增): fund_score.json(头部2000) + fund_score_top.json(Top100)。
    按类别走 R2(§8.1 新类别按前缀建独立命令, 不依赖 1MB 阈值兜底)。
    """
    data_dir = STATIC_DIR / "data"
    ok, total, _, uploaded_keys = _upload_glob(data_dir, ["fund_score*.json"], "fund_score")
    if total == 0:
        print(f"⚠ 无 fund_score json: {data_dir}/fund_score*.json")
        return
    if ok != total:
        sys.exit(1)
    purge_cache(uploaded_keys, cache_prefix="/r2/")


def cmd_upload_etf_score():
    """上传 static-site/data/etf_score_list_*.json 到 R2 data/ 前缀。

    P0-2 (2026-08-05): 原 18MB 单文件 etf_score_list.json 拆 3 JSON (buy/sell/hold),
    前端懒加载 hold (初始只加载 buy+sell ~153KB br, hold 783KB br 点"持有观察"才加载)。
    3 文件均走 R2 data/ 前缀(前端硬编码 ssd.fx8.store/data/ URL), 不依赖 upload-data-large 阈值。
    §8.1 新类别按前缀建独立命令; upload-data-large exclude etf_score_list_ 防双副本。
    etf_score_list_buy.json ~1.4MB / sell ~1.2MB / hold ~13MB, 均 >1MB 但走独立命令非阈值兜底。
    """
    data_dir = STATIC_DIR / "data"
    ok, total, _, uploaded_keys = _upload_glob(data_dir, ["etf_score_list_*.json"], "data")
    if total == 0:
        print(f"⚠ 无 etf_score_list_* json: {data_dir}/etf_score_list_*.json")
        return
    if ok != total:
        sys.exit(1)
    purge_cache(uploaded_keys, cache_prefix="/r2/")


def cmd_upload_kelly_parts():
    """上传 static-site/data/signal_kelly_trades_parts/*.json 到 R2 data/signal_kelly_trades_parts/ 前缀。

    2026-08-22 首页模拟回测弹窗分片加载(recent.json 热区片 + t{YYYY}.json 年片)。
    §8.1 新类别按前缀建独立命令(子目录不被 upload-data-large/upload-all-data 的非递归
    *.json glob 覆盖, 必须独立命令)。前端走 /data/ rewrite 原生 URL, R2 key =
    data/signal_kelly_trades_parts/<name>, purge 用默认 cache_prefix="/"(匹配 dataRewriteHandler)。
    """
    parts_dir = STATIC_DIR / "data" / "signal_kelly_trades_parts"
    ok, total, _, uploaded_keys = _upload_glob(parts_dir, ["*.json"], "data/signal_kelly_trades_parts")
    if total == 0:
        print(f"⚠ 无分片文件: {parts_dir}/*.json (先跑 signal_kelly_backtest.py 生成分片)")
        return
    if ok != total:
        sys.exit(1)
    purge_cache(uploaded_keys)


def cmd_upload_data_large():
    """上传 static-site/data/ 顶层 >=1MB 或大 range(-all/-5y/-3y) 的 .json 到 R2 data/ 前缀。

    双源备份策略（2026-07-20 R2 优化根治 300MB）：
    - 前端暂未全改 R2 URL 的（a-stock/hk/global/sentiment/etf_national_team 大 range）：
      git 仍带（线上 ./data/ 读），R2 也有副本（前端改 URL 后可 .gitignore 移出 git）。
    - industry-* 已走 upload-industry（industry/ 前缀），此处排除避免重复。
    - public_fund* 已走 upload-public-fund（public_fund/ 前缀），此处排除避免重复。
    - index/industry-*-indices/lab/trade_sim 已各自独立命令，不在此上传。

    上传条件（满足任一）：
    1. 大 range 文件(all/5y/3y): 前端 dataUrl(_R2_LARGE_RANGE_RE) 强制走 R2,
       无大小限制上传(架构一致性; 2026-08-03 sentiment-3y 962KB<1MB 漏传致线上 404 修复)。
    2. >=1MB 的大文件: 阈值兜底,小文件留 git 减 R2 请求延迟。
    新增大文件自动覆盖（glob + 过滤，无需维护硬编码清单）。
    """
    data_dir = STATIC_DIR / "data"
    LARGE_THRESHOLD = 1 * 1024 * 1024  # 1MB
    # 大 range 文件前端 dataUrl 必走 R2(与 app.js _R2_LARGE_RANGE_RE 同规则), 无大小限制上传
    _LARGE_RANGE_RE = re.compile(r'-(?:all|5y|3y)\.json$')
    # 排除已走独立 R2 前缀的（industry-/public_fund/offshore_fund/fund_score/etf_score_list 由各自命令处理）
    # P0-2: etf_score_list (无下划线)同时排除旧单文件 etf_score_list.json 和新拆分 etf_score_list_*.json,
    # 旧文件不再生成但本地可能残留, upload-etf-score 只上传 etf_score_list_*.json(下划线 glob)
    exclude_prefixes = ("industry-", "public_fund", "offshore_fund", "fund_score", "etf_score_list")
    files = []
    for f in sorted(data_dir.glob("*.json")):
        if any(f.name.startswith(p) for p in exclude_prefixes):
            continue
        try:
            sz = f.stat().st_size
        except OSError:
            continue
        # 大 range 文件(前端强制走 R2)或 >=1MB 的大文件才上传 R2
        # overfit_monitor* 例外: 首页走势图盘后核心产物(需走 R2),
        # static-site/data/ 已整体 gitignore 移出 git, 不传 R2 则备站/主站 /data/ rewrite 拿不到。
        # 2026-08-24 B拆分: 前缀匹配覆盖主文件+ext(by_k/filtered_by_k 拆 overfit_monitor_ext.json)。
        _OVERFIT_FORCE = f.name.startswith("overfit_monitor")
        if sz >= LARGE_THRESHOLD or _LARGE_RANGE_RE.search(f.name) or _OVERFIT_FORCE:
            files.append(f)
    if not files:
        print(f"⚠ 无 >{LARGE_THRESHOLD // 1024}KB 的顶层 .json: {data_dir}")
        return
    ok = 0
    uploaded_keys = []
    total = len(files)
    for i, f in enumerate(files, 1):
        key = f"data/{f.name}"
        payload = f.read_bytes()
        size = len(payload)
        try:
            status, data = s3_request("PUT", key, payload)
            if status == 200:
                ok += 1
                uploaded_keys.append(key)
                print(f"[{i}/{total}] ✓ {f.name} ({size // 1024}KB)")
            else:
                print(f"[{i}/{total}] ✗ {f.name} status={status} {data[:200]}")
        except Exception as e:
            print(f"[{i}/{total}] ✗ {f.name} 异常({type(e).__name__}: {e})")
    print(f"共上传 {ok}/{total} -> {PUBLIC}/data/")
    # 清 CF 边缘缓存(同 cmd_upload_industry 模式):uploaded_keys 含 "data/" 前缀,
    # cache_prefix="/r2/" -> "/r2/data/{name}" 匹配 r2ProxyHandler cacheKey。
    # 不用 "/r2/data/" 否则双 data 致 purge 无效。
    # C补偿(2026-08-24 提速A+B+C+D): overfit_monitor*.json(主+ext)前端走 /data/ rewrite 原生 URL
    # 且已挪 MED 600s 缓存层(worker/headers.js dataCacheTtl), dataRewriteHandler 会写 edge cache,
    # cacheKey pathname = "/data/{name}" —— 必须用 cache_prefix="/" 清该路由, 原 "/r2/" 清不到
    # (不清则重演 2026-08-09 edge 4h 残留事故; 「重跑立即看」由本 purge 补偿保证)。
    _overfit_keys = [k for k in uploaded_keys if k.startswith("data/overfit_monitor")]
    _other_keys = [k for k in uploaded_keys if not k.startswith("data/overfit_monitor")]
    if _other_keys:
        purge_cache(_other_keys, cache_prefix="/r2/")
    if _overfit_keys:
        purge_cache(_overfit_keys, cache_prefix="/")


def purge_cache(r2_keys, cache_prefix="/"):
    """上传后调 POST /api/purge-cache 清 CF 边缘缓存，让前端读最新数据。

    r2_keys: R2 key 列表（如 ["data/overview.json"] 或 ["industry/industry-all.json"]）。
    cache_prefix: CF edge cache key 前缀，需匹配 Worker 写缓存时的 cacheKey pathname：
      - "/" (默认): /data/ rewrite 路由，如 /data/overview.json（dataRewriteHandler）
      - "/r2/": /r2/ 代理路由，如 /r2/industry/industry-all.json（r2ProxyHandler）
    Worker purgeCacheHandler 用 url.origin + keyPath 构造 cacheKey 并 caches.default.delete，
    故 keyPath 需与 Handler 写缓存时 cacheKey 的 pathname 一致（含 /r2/ 前缀）。
    读 PURGE_SECRET env var（trade-data/.env）。Worker 侧需 wrangler secret put PURGE_SECRET。
    失败不中断上传流程（purge 是次要操作，上传是主要操作）。

    分批 purge（2026-08-09 定）：Worker purgeCacheHandler 串行 await caches.default.delete
    遍历所有 keys，一次性发 400+ keys 致 Worker 超时 500（CPU/wall time 限制）。
    分批发送，每批 PURGE_BATCH_SIZE 个 keys，批间 sleep PURGE_BATCH_SLEEP 秒，
    每批独立 POST 请求，避免单请求 key 数过多触发 Worker 超时。
    """
    secret = os.environ.get("PURGE_SECRET", "")
    if not secret:
        print("⚠ PURGE_SECRET 未设，跳过 cache purge（Worker /api/purge-cache 会 403）")
        # 告警（不静默跳过）：通知管理员 PURGE_SECRET 丢失，edge cache 未清将致前端读旧数据。
        # 同一进程只告警一次（一次 deploy 跑多个 upload 命令，避免邮件轰炸）。
        if not getattr(purge_cache, "_warned", False):
            purge_cache._warned = True
            try:
                sys.path.insert(0, str(ROOT / "scripts"))
                import notify  # noqa: E402
                notify.send(
                    "[告警] PURGE_SECRET 未设 cache purge 跳过",
                    "PURGE_SECRET 未设，upload_r2.py 跳过 /api/purge-cache，CF edge cache 旧版将残留至自然过期，"
                    "前端可能读到旧数据。请检查 trade/.env 与 trade-data/.env 是否含 PURGE_SECRET。"
                    "（根治 2026-08-09 手动部署丢失 PURGE_SECRET 致 edge cache 不清事故）",
                    from_prefix="[告警]",
                )
            except Exception as e:
                print(f"⚠ notify 告警发送失败（不阻塞）：{e}")
        return

    cache_keys = [cache_prefix + k for k in r2_keys]  # 如 "/data/x" 或 "/r2/industry/x"
    if not cache_keys:
        print("ℹ 无需 purge 的 cache keys（空列表）")
        return

    # 分批 purge：每批 N 个 keys，避免单请求 key 数过多致 Worker 超时 500。
    # Worker purgeCacheHandler 串行 await caches.default.delete，400+ keys 超 Worker 时限。
    # 实测手动 purge 3 keys 成功(200 purged=3)，400+ 一次性 purge 超时 500。
    PURGE_BATCH_SIZE = 30   # 每批 keys 数（20-50 安全区间，避免 Worker 超时）
    PURGE_BATCH_SLEEP = 0.5  # 批间 sleep 秒（避免连续 POST 撞 CF 限流）

    total_keys = len(cache_keys)
    batches = [cache_keys[i:i + PURGE_BATCH_SIZE]
               for i in range(0, total_keys, PURGE_BATCH_SIZE)]
    total_batches = len(batches)
    total_purged = 0
    failed_batches = 0

    print(f"→ Cache purge 分批: {total_keys} keys / {total_batches} 批 "
          f"(每批 {PURGE_BATCH_SIZE} keys, 间隔 {PURGE_BATCH_SLEEP}s)")

    # 批次级重试（2026-08-23 防再犯）：偶发网络抖动/Worker 瞬时 5xx 会致单批失败即告警
    # （实测 2026-08-23 20:30 fetch_news 单批 11 keys 全失败、前后批次均正常=瞬时故障），
    # 失败批原样重试 PURGE_RETRY 次（退避递增），仍失败才计 failed_batches 触发告警。
    PURGE_RETRY = 2          # 每批失败后重试次数（首发 + 2 重试 = 最多 3 次）
    PURGE_RETRY_BACKOFF = 1  # 首次重试退避秒数，第 n 次重试退避 n * PURGE_RETRY_BACKOFF

    for idx, batch in enumerate(batches, 1):
        body = json.dumps({"secret": secret, "keys": batch}).encode()
        purged = None
        last_err = ""
        attempts = PURGE_RETRY + 1
        for attempt in range(attempts):
            conn = http.client.HTTPSConnection("ss.fx8.store", timeout=30, context=_CTX)
            try:
                conn.request("POST", "/api/purge-cache", body=body,
                             headers={"Content-Type": "application/json"})
                resp = conn.getresponse()
                data = resp.read().decode()
                if resp.status == 200:
                    # 解析 {purged: N, total: M} 累计进度
                    try:
                        j = json.loads(data)
                        purged = j.get("purged", len(batch))
                    except Exception:
                        purged = len(batch)
                    break
                last_err = f"HTTP {resp.status} {data[:200]}"
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
            finally:
                conn.close()
            if attempt < attempts - 1:
                time.sleep(PURGE_RETRY_BACKOFF * (attempt + 1))
        if purged is not None:
            total_purged += purged
            retried = f"（重试{attempt}次后成功）" if attempt > 0 else ""
            print(f"  ✓ 批次 {idx}/{total_batches}: purged={purged} "
                  f"(累计 {total_purged}/{total_keys}){retried}")
        else:
            failed_batches += 1
            print(f"  ⚠ 批次 {idx}/{total_batches} failed after {attempts} 次尝试: "
                  f"{last_err}")
        # 批间 sleep（最后一批不 sleep）
        if idx < total_batches:
            time.sleep(PURGE_BATCH_SLEEP)

    # 汇总
    if failed_batches == 0:
        print(f"✓ Cache purge 完成: 全部 {total_batches} 批成功, "
              f"共 purged {total_purged}/{total_keys} keys")
    else:
        print(f"⚠ Cache purge 部分失败: {failed_batches}/{total_batches} 批失败, "
              f"已 purged {total_purged}/{total_keys} keys（edge cache 部分残留）")
        # 告警（防轰炸）：通知管理员 cache purge 部分失败，edge cache 残留致前端可能读旧数据。
        # dedup_key=purge_batch_fail 跨进程去重（check_dedup/update_dedup 持久化到
        # data/notify_dedup.json），一次 deploy 跑多个 upload 命令 30min 内只告警一次。
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            import notify  # noqa: E402
            _dedup_key = "purge_batch_fail"
            _dedup_window = 1800  # 30min 内不重复告警
            if not notify.check_dedup(_dedup_key, _dedup_window):
                notify.send(
                    "[告警] Cache purge 部分失败 edge cache 残留",
                    f"upload_r2.py cache purge 部分失败: {failed_batches}/{total_batches} 批失败, "
                    f"已 purged {total_purged}/{total_keys} keys。CF edge cache 部分残留, "
                    f"前端可能读到旧数据。请查 upload_r2 日志看失败批次详情（HTTP status/异常）。"
                    f"（R2 审计 P2-1: 分批 purge 失败告警）",
                    from_prefix="[告警]",
                )
                notify.update_dedup(_dedup_key)
        except Exception as e:
            print(f"⚠ notify 告警发送失败（不阻塞）：{e}")


def cmd_upload_all_data():
    """上传 static-site/data/ 下所有小 .json 文件到 R2 data/ 前缀(阶段1a 双写准备)。

    为 R2 迁移阶段2(Worker /data/->R2 rewrite)准备全量 R2 数据。
    排除已在独立命令处理的文件(避免双副本上传):
      - index/ lab/ trade_sim/ 子目录: *.json glob 不递归,天然不匹配
      - industry-* (upload-industry -> industry/ 前缀)
      - public_fund* (upload-public-fund -> public_fund/ 前缀)
      - offshore_fund* (upload-offshore-fund -> offshore_fund/ 前缀; 定时链已停用 P2-15, exclude 保留防手动场景双副本)
      - fund_score* (upload-fund-score -> fund_score/ 前缀)
      - etf_score_list* (upload-etf-score -> data/ 前缀,独立命令已处理)
      - signal_kelly_trades* (5.84MB >=1MB,upload-data-large 已覆盖,防双副本)
      - signal_kelly_trades_parts/ 子目录(upload-kelly-parts 独立命令; *.json glob 不递归天然不匹配,此处记录防漏)
      - 大 range 文件 *-{all,5y,3y}.json (upload-data-large -> data/ 前缀)
      - .gz 不再生成(CF 自动 br 压缩替代),只传 *.json pattern
      - feed.xml: 非 .json,*.json glob 天然不匹配
    复用 _upload_glob 8 线程并发上传。
    """
    data_dir = STATIC_DIR / "data"
    # 排除已在独立命令处理的文件前缀(和 cmd_upload_data_large exclude_prefixes 一致)
    # signal_kelly_trades: 5.84MB >=1MB,upload-data-large 已覆盖,避免双副本上传
    exclude_prefixes = (
        "industry-", "public_fund", "offshore_fund", "fund_score", "etf_score_list",
        "signal_kelly_trades",
    )
    # 排除大 range 文件(upload-data-large 已处理)
    _LARGE_RANGE_RE = re.compile(r'-(?:all|5y|3y)\.json$')

    def _exclude_fn(f):
        name = f.name
        if any(name.startswith(p) for p in exclude_prefixes):
            return True
        if _LARGE_RANGE_RE.search(name):
            return True
        return False

    ok, total, _, _ = _upload_glob(data_dir, ["*.json"], "data", exclude_fn=_exclude_fn)
    if total == 0:
        print(f"⚠ 无小 .json 文件: {data_dir}/*.json")
        return
    if ok != total:
        sys.exit(1)
    # 阶段2：上传成功后清 CF 边缘缓存（purge_cache 失败不中断）
    purge_keys = [f"data/{f.name}" for f in sorted(set(data_dir.glob("*.json")))
                  if not _exclude_fn(f) and f.exists()]
    purge_cache(purge_keys)


def cmd_upload_intraday():
    """上传 intraday 盘中更新的数据文件到 R2 data/ 前缀(阶段1b 双写)。

    intraday_snapshot.sh 每10分钟跑,更新以下文件(对应 git push DATA_FILES 列表):
    - intraday_snapshot/overview/summary/summary_history/notifications/boot/schedule_stats
    - a-stock/hk/global/sentiment 的 3m/6m/1y
    - etf_national_team 的 1m/3m/6m/1y
    只传 .json(CF 自动 br 压缩)。8线程并发,~23文件秒级完成。
    index/ 已由 upload-index(intraday_snapshot.sh L249 独立调用)处理,不在此上传。
    部分文件可能不存在(notifications/summary_history 某些时点未生成),_upload_glob 自动过滤。

    盘中手动跑必须显式 REPO=/Users/linhuichen/code/trade-data(缺省 STATIC_DIR 回退 trade 侧旧库,
    会覆盖 R2,见顶部 _guard_upload_intraday 注释)。定时链路(intraday_snapshot.sh)已显式 export REPO。
    方案4一致性兜底已废弃(结构性死閪,见其废弃注释),实际拦截由 _guard_upload_intraday 单一承担。
    """
    _guard_upload_intraday()
    data_dir = STATIC_DIR / "data"
    files = [
        "intraday_snapshot.json", "overview.json", "summary.json",
        "summary_history.json", "notifications.json", "boot.json",
        "schedule_stats.json",
        # 大盘结构套件（2026-08-19 修复：随 intraday _recompute_scores 盘中重算后一并上传 R2，
        # 否则前端 position/ma_alignment/ad_line/new_high_low/volume_ratio 卡盘中停在 T-1，
        # 与情绪分/恐贪不同步；edge TTL=60s(_data_cache_ttl L837) 上传即近乎实时可见）
        "position.json", "ma_alignment.json", "ad_line.json",
        "new_high_low.json", "volume_ratio.json",
        "a-stock-3m.json", "a-stock-6m.json", "a-stock-1y.json",
        "hk-3m.json", "hk-6m.json", "hk-1y.json",
        "global-3m.json", "global-6m.json", "global-1y.json",
        "sentiment-3m.json", "sentiment-6m.json", "sentiment-1y.json",
        "etf_national_team-1m.json", "etf_national_team-3m.json",
        "etf_national_team-6m.json", "etf_national_team-1y.json",
    ]
    ok, total, _, _ = _upload_glob(data_dir, files, "data")
    if total == 0:
        print(f"⚠ 无 intraday 文件: {data_dir}")
        return
    if ok != total:
        sys.exit(1)
    # 阶段2：上传成功后清 CF 边缘缓存（purge_cache 失败不中断）
    purge_keys = [f"data/{f}" for f in files if (data_dir / f).exists()]
    purge_cache(purge_keys)


def cmd_upload_data_files(filenames):
    """上传指定文件列表到 R2 data/ 前缀（阶段3：替代各脚本 git push 数据）。

    filenames: 文件名列表（如 ["schedule_stats.json", "global-3m.json"]），
    相对 STATIC_DIR/data/。上传到 R2 data/{filename}。
    部分文件不存在自动跳过（如 notifications.json 某些时点未生成）。
    上传后调 purge_cache 清 CF 边缘缓存。
    """
    data_dir = STATIC_DIR / "data"
    existing = [f for f in filenames if (data_dir / f).exists()]
    if not existing:
        print(f"⚠ 无文件: {filenames}")
        return
    ok, total, _, _ = _upload_glob(data_dir, existing, "data")
    if ok != total:
        sys.exit(1)
    # 阶段3：上传成功后清 CF 边缘缓存（purge_cache 失败不中断）
    purge_keys = [f"data/{f}" for f in existing]
    purge_cache(purge_keys)


# ---- deploy 末尾统一 purge 低频文件(决策清单项5+项8, 2026-08-18) ----
# 背景: worker dataRewriteHandler 分层 TTL, 低频文件落 LOW_FREQ(3600s) 档。
#   CF 会把 3600s 实际拉长成 max-age=14400(4h) edge 残留, 上传时 purge 若失败/漏跑,
#   前端会读到最长 4h 的旧版。决策清单项5: deploy 末尾统一 purge 低频文件消除 4h 残留窗口;
#   项8: purge 失败 notify 告警(purge_cache 内部已对部分失败/无 secret 告警, 此处命令级失败由
#   deploy.sh 侧 notify 兜底)。
# 只 purge 低频档(3600s): 高频(60s)/关键(ttl=0)/MED(600s) 文件要么不缓存要么很快过期,
#   purge 无意义且浪费 R2 调用。低频档是 4h 残留的唯一来源。
#
# ⚠️ _data_cache_ttl 必须与 worker/headers.js dataCacheTtl 判定保持同步!
#   改 worker 分层 TTL 时同步改本函数, 否则 purge 集合与 edge 缓存实际残留集偏差(漏 purge 或多余)。
def _data_cache_ttl(pathname):
    """镜像 worker/headers.js dataCacheTtl 判定 /data/<name>.json 的 edge cache TTL 秒数。

    返回 0(no-cache)/60/600/3600(秒)。与 worker/headers.js dataCacheTtl 逐行对应。
    """
    import re as _re
    if _re.search(r'^/data/(?:overview|intraday_snapshot|board_etf_map|daily_brief|'
                  r'daily_brief_history|signal_kelly_backtest|signal_kelly_trades|'
                  r'overfit_monitor|news_digest|signal_stats)\.json$', pathname):
        return 0
    if _re.search(r'^/data/(?:boot|notifications|summary|summary_history|schedule_stats|alert)\.json$',
                  pathname) or pathname == '/data/feed.xml':
        return 60
    if _re.search(r'-(?:1m|3m|6m|1y)\.json$', pathname):
        return 60
    if _re.search(r'^/data/(?:futures|ad_line|new_high_low|position|rotation|volume_ratio|'
                  r'ma_alignment|signal_freq|etf_national_team_holders|etf_national_team_quarterly|'
                  r'global-extras-all)\.json$', pathname):
        return 60
    if _re.search(r'^/data/(?:signal_stats|futures_acc_trend|futures_acc_conclusion|'
                  r'fund_score_top|trade_sim_indices)\.json$', pathname):
        return 600
    return 3600


def cmd_purge_low_freq():
    """deploy 末尾统一 purge 低频文件(决策清单项5, 2026-08-18)。

    扫描 static-site/data/ 下所有 .json, 筛出落在 LOW_FREQ(3600s) 档的文件,
    调 purge_cache(prefix="/") 清 CF edge cache, 消除低频文件最长 4h 旧版残留窗口。
    高频/关键(ttl=0/60s)/MED(600s) 文件不 purge(不缓存或很快过期)。
    purge_cache 内部已对「部分批失败」「PURGE_SECRET 未设」notify 告警(项8);
    命令自身异常(如 HTTP 连接问题)由 deploy.sh 侧 run_r2_upload 失败分支 notify 兜底。
    """
    data_dir = STATIC_DIR / "data"
    keys = []
    for f in sorted(data_dir.glob("*.json")):
        pathname = f"/data/{f.name}"
        if _data_cache_ttl(pathname) == 3600 and f.exists():
            keys.append(f"data/{f.name}")
    if not keys:
        print("ℹ 无低频文件需 purge")
        return
    print(f"→ 低频文件统一 purge: {len(keys)} 个(决策清单项5, 消除 4h 旧版残留)")
    purge_cache(keys)


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


def cmd_upload_claude_backup(local_path=None):
    """上传 Claude 自我备份 tar.gz 到 R2 signal-backup 私有桶 claude-backup/ 前缀。

    backup_claude_self.sh(launchd 03:17)tar 打包后调本命令推云端异地备份。
    local_path=None 时取 ~/.claude/backups/daily/ 最新 claude-self-YYYYMMDD.tar.gz。
    R2 key = claude-backup/claude-self-YYYYMMDD.tar.gz(独立前缀,与 backup/ 的 .db.gz 区分)。
    按用户定"简单起见先不删 R2 旧的",R2 端不做滚动清理(R2 存储便宜,本地 30 天滚动已够)。
    content_type 显式 application/gzip(.tar.gz 不在 _CONTENT_TYPE_MAP,否则回退 octet-stream)。
    """
    import re
    if local_path:
        src = Path(local_path)
    else:
        backup_dir = Path.home() / ".claude/backups/daily"
        files = sorted(backup_dir.glob("claude-self-*.tar.gz"))
        if not files:
            sys.exit(f"无 claude-self 备份: {backup_dir}/claude-self-*.tar.gz")
        src = files[-1]
    if not src.exists():
        sys.exit(f"备份文件不存在: {src}")
    m = re.search(r"claude-self-(\d{8})\.tar\.gz$", src.name)
    if not m:
        sys.exit(f"文件名日期解析失败: {src.name}")
    date_str = m.group(1)
    key = f"claude-backup/claude-self-{date_str}.tar.gz"
    payload = src.read_bytes()
    status, data = s3_request("PUT", key, payload, bucket=BACKUP_BUCKET, content_type="application/gzip")
    if status == 200:
        print(f"✓ {src.name} ({len(payload) // 1024}KB) -> {BACKUP_BUCKET}/{key} (私有桶)")
    else:
        sys.exit(f"✗ 上传失败 status={status} {data.decode('utf-8', errors='replace')[:300]}")


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
    guard_repo_default(cmd)                     # #75 分级闸:REPO 缺省且非白名单命令 → exit 3
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
    elif cmd == "upload-etf-hist":
        # upload-etf-hist  ETF 全史日K etf/{code}-all.json -> R2 etf/ 前缀(#10, 2026-08-22)
        cmd_upload_etf_hist()
    elif cmd == "upload-fund-nav":
        # upload-fund-nav  基金全史净值 fund_nav/{code}.json -> R2 fund_nav/ 前缀(#11, 2026-08-25)
        cmd_upload_fund_nav()
    elif cmd == "upload-industry":
        cmd_upload_industry()
    elif cmd == "upload-public-fund":
        cmd_upload_public_fund()
    elif cmd == "upload-offshore-fund":
        cmd_upload_offshore_fund()
    elif cmd == "upload-fund-score":
        cmd_upload_fund_score()
    elif cmd == "upload-etf-score":
        cmd_upload_etf_score()
    elif cmd == "upload-data-large":
        cmd_upload_data_large()
    elif cmd == "upload-kelly-parts":
        # signal_kelly_trades_parts/ 分片(recent+tYYYY, 首页模拟回测弹窗分片加载)
        cmd_upload_kelly_parts()
    elif cmd == "upload-all-data":
        cmd_upload_all_data()
    elif cmd == "upload-intraday":
        cmd_upload_intraday()
    elif cmd == "upload-data-files":
        # upload-data-files <file1> [file2] ...  上传指定文件到 R2 data/ 前缀 + purge
        # 阶段3：替代 push_schedule_stats/gold_night/update_lab 的 git push 数据
        files = sys.argv[2:]
        if not files:
            sys.exit("用法: upload-data-files <file1> [file2] ...")
        cmd_upload_data_files(files)
    elif cmd == "purge-low-freq":
        # purge-low-freq  deploy 末尾统一 purge 低频文件(决策清单项5, 2026-08-18)
        cmd_purge_low_freq()
    elif cmd == "upload-db":
        cmd_upload_db()
    elif cmd == "upload-claude-backup":
        # upload-claude-backup [local_path]  Claude 自我备份 tar.gz -> signal-backup/claude-backup/
        local_path = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_upload_claude_backup(local_path)
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
            "upload-trade-sim-json|upload-index|upload-industry|upload-public-fund|"
            "upload-offshore-fund|upload-fund-score|upload-etf-score|upload-etf-hist|"
            "upload-fund-nav|upload-data-large|upload-kelly-parts|upload-db|"
            "upload <local> <key>|delete <key> [bucket]|clean-data-backup|"
            "upload-claude-backup [path]|upload-all-data|upload-intraday|purge-low-freq]"
        )
