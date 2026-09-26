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
  python3 scripts/upload_r2.py upload-large-json [--dry-run]  # 大 JSON 私有桶备份(signal-backup/large-json/)

测试隔离三件套(F1, 2026-09-26, 严禁写生产 R2):
  1) STATICDATA_REPO=/tmp/xxx —— 指向 /tmp 临时 staticdata git 克隆(见 docs/ops/large-json-out-of-git-20260925.md §5.1)。
  2) R2_BACKUP_BUCKET=不存在的桶名(如 demo-nowhere)—— 指向不存在的桶实测 404, 不污染真实 signal-backup。
  3) upload-large-json --dry-run(或 async 侧 STATICDATA_BACKUP_SKIP_R2_UPLOAD=1)—— 只打印将上传清单与计划动作,
     不 PUT / 不 DELETE / 不重写 manifest / 不跑 prune, 全程零 R2 接触。
"""
import os, sys, re, hashlib, hmac, http.client, datetime, ssl, json, time, threading, fcntl
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

# --dry-run 全局标志(验收自测用, 设计文档 §7 验收①): 引擎只打印「将传 N/M」不 PUT。
# 由 __main__ 解析 --dry-run 后置 True; 各通道函数不逐处传参, 引擎默认 dry_run=None 时读此全局。
_DRY_RUN = False


# ---- REPO 缺省分级闸 (2026-08-22, #75) ----
# 捕获须在 load_env() 之前(下方 L146),防 .env setdefault 污染判定(加注释钉死顺序)。
_RAW_REPO = os.environ.get("REPO")            # 原始 env,捕获时机早于 load_env
REPO_EXPLICIT = bool(_RAW_REPO)

# A 类与 REPO 无关(读显式路径或私有桶固定 key)→ 放行
# upload-large-json(2026-09-25): 读 STATICDATA_REPO 显式路径 + 私有桶 signal-backup 固定 key, 与 REPO/STATIC_DIR 无关 → A 类
_A_CLASS = {"list", "upload", "upload-claude-backup", "upload-decommissioned", "download-db", "delete", "clean-data-backup", "upload-large-json"}
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
# 云上单仓(REPO=GIT_REPO)下 git 仓 = 唯一源树, 用 GIT_REPO env 派生; 默认 macOS 本机 trade。
_TRADE_STATIC = str((Path(os.environ.get("GIT_REPO", "/Users/linhuichen/code/trade")) / "static-site").resolve())
# 独立源树 trade-data(同 pick_repo.MAIN_REPO): 单仓判定须排除「trade-data 仍存在」的情况(2026-09-12 F1)
MAIN_REPO = Path(os.environ.get("MAIN_REPO", "/Users/linhuichen/code/trade-data"))


def _is_trade_side_dir() -> bool:
    """当前 STATIC_DIR 是否落在 trade/static-site(非 trade-data/static-site)。

    launchd 定时(REPO=trade-data)解析到 trade-data/static-site,不命中;
    手动未带 REPO 时 STATIC_DIR=ROOT=trade/static-site,命中 → 读滞后库风险。
    云上单仓(REPO==GIT_REPO)下 STATIC_DIR 与 git 仓同树, 无独立滞后镜像 → 放行(False)。
    单仓判定必须排除「独立源树 trade-data 仍存在」的情况(2026-09-12 F1):
    macOS 双仓下 REPO=GIT_REPO=trade 若 trade-data 仍在, 仍是滞后 trade 侧, 不算单仓。
    """
    repo = os.environ.get("REPO", "").strip()
    git = os.environ.get("GIT_REPO", "").strip()
    if (repo and git and Path(repo).resolve() == Path(git).resolve()
            and (MAIN_REPO.resolve() == Path(git).resolve() or not MAIN_REPO.exists())):
        return False  # 单仓: 无 trade/trade-data 之分, 不构成「滞后 trade 侧」
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

# R2 上传 HTTP 连接超时(秒):默认 30(本机带宽快够用);云上跨境上传带宽 ~1.2-1.6Mbps,
# >7MB 大文件(凯利交易明细 74.7MB/累积净值 18.5MB 等)必超时失败,云上 systemd 设
# R2_UPLOAD_HTTP_TIMEOUT=600。env 缺失/空 -> 30(向后兼容)。
# 命名注意:deploy.sh 已无同名 shell 变量 R2_UPLOAD_TIMEOUT(2026-09-24 round6 移除,现 run_r2_upload
# 超时 = 通道显式值 / 按字节估算 / 回退基线固定 900s),python 侧用 R2_UPLOAD_HTTP_TIMEOUT 区分语义
# (HTTP 连接超时),防 env 同名连锁。
try:
    R2_UPLOAD_HTTP_TIMEOUT = int(os.environ.get("R2_UPLOAD_HTTP_TIMEOUT") or "30")
except ValueError:
    # 非法值(如 "600s"/"abc")回退默认 30,不崩在 import(云上手写 env 写错不全线停摆)
    R2_UPLOAD_HTTP_TIMEOUT = 30

# macOS 系统 Python 缺 CA 束（CERTIFICATE_VERIFY_FAILED），用系统 /etc/ssl/cert.pem
_CA = "/etc/ssl/cert.pem"
_CTX = ssl.create_default_context(cafile=_CA) if Path(_CA).exists() else ssl._create_unverified_context()

# ---- keep-alive 连接复用 (2026-09-21 R2 上传失败根治: verify-r2 周日全量对账 ~3万 key 逐个 HEAD,
# 每个 HEAD 新建 HTTPSConnection 跨境握手 ~1s 结构性超时; 同一连接复用连续 HEAD 省 60%+ 对账时间)。
# 线程局部单连接: ThreadPoolExecutor worker 线程内连续请求复用, 连接失效自动重建。
_KA_TLS = threading.local()


def _get_keepalive_conn():
    conn = getattr(_KA_TLS, "conn", None)
    if conn is None:
        conn = http.client.HTTPSConnection(HOST, timeout=R2_UPLOAD_HTTP_TIMEOUT, context=_CTX)
        _KA_TLS.conn = conn
    return conn


def _drop_keepalive_conn():
    conn = getattr(_KA_TLS, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
    _KA_TLS.conn = None


# ---- multipart 大文件上传 (2026-09-21 R2 上传失败根治: >阈值单文件走 create-multipart-upload →
# 并行 upload-part → complete, 消除「单 PUT 卡 600s 超时重试 5 次」放大器)。
# 阈值/分片大小调研 R2 官方文档: multipart 分片 5MiB-5GiB, 最多 10000 片, >100MB 建议 multipart
# (单 PUT 上限 5GiB 但 `~100MB 以内建议单 PUT`)。本脚本按类别下发, 跨 1.1GB 全量周末大关,
# 取阈值 100MB、分片默认 64MiB(>5MiB 合法且单请求时长<看门狗/HTTP 超时至少 8:1 余量)。
_MULTIPART_THRESHOLD = 100 * 1024 * 1024      # 100MB
_MULTIPART_PART_SIZE = 64 * 1024 * 1024       # 64MiB/片
_MULTIPART_MAX_PARTS = 10000                   # R2 官方上限
_MULTIPART_WORKERS = 4                         # 分片并发(连接数适度, 与既有 8 线程区分防止叠加过多连接)


def _multipart_part_sizes(total):
    """按 64MiB 目标切片的实际各片字节数列表(片数 = ceil(total/64MiB))。

    A1 返修(2026-09-21 reviewer): 总大小 > 10000×64MiB(~640GiB)时 parts 被 cap 到 _MULTIPART_MAX_PARTS,
    原实现 cap 后循环切完不校验 rem, 切片和 < 文件大小 → complete 成功却静默截尾。现在循环后若 rem>0
    显式抛错(调用方 _upload_one 捕到按失败返回, 不静默传半个文件)。
    """
    import math
    parts = max(1, math.ceil(total / _MULTIPART_PART_SIZE))
    parts = min(parts, _MULTIPART_MAX_PARTS)
    sizes = []
    rem = total
    for _ in range(parts):
        sz = min(_MULTIPART_PART_SIZE, rem)
        sizes.append(sz)
        rem -= sz
    if rem > 0:
        raise ValueError(
            f"multipart 超 R2 上限: total={total} bytes 需 {math.ceil(total / _MULTIPART_PART_SIZE)} 片 "
            f"> _MULTIPART_MAX_PARTS={_MULTIPART_MAX_PARTS}, 无法完整分片, abort")
    return sizes


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


def s3_request(method, key, payload=b"", query="", bucket=None, content_type=None, with_headers=False, keep_alive=False):
    """path-style: /BUCKET/key, host = endpoint host。bucket=None 用默认 BUCKET。

    带连接超时(R2_UPLOAD_HTTP_TIMEOUT 秒,默认 30s)+ 重试(5 次,SSL/连接错退避 1s/2s/4s/8s),防 R2 偶发断连致脚本挂死。
    content_type=None 时按 key 扩展名推断(_CONTENT_TYPE_MAP),未知扩展名回退 application/octet-stream。
    with_headers=True: 返回 (status, data, resp_headers_dict)(upload-part 取 ETag 用)。
    keep_alive=True: 复用线程本地 HTTPSConnection(连续 HEAD/PUT 对账省跨境握手, 2026-09-21 R2 根治);
      失败/5xx 自动丢弃重建, 不影响正确性。
    """
    if content_type is None:
        ext = os.path.splitext(key)[1].lower()
        content_type = _CONTENT_TYPE_MAP.get(ext, "application/octet-stream")
    bkt = bucket or BUCKET
    last_exc = None
    for attempt in range(5):
        conn = None
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
            if method in ("PUT", "POST"):
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

            if keep_alive:
                conn = _get_keepalive_conn()
            else:
                conn = http.client.HTTPSConnection(HOST, timeout=R2_UPLOAD_HTTP_TIMEOUT, context=_CTX)
            uri = path + ("?" + query if query else "")
            body = payload if method in ("PUT", "POST") else None
            conn.request(method, uri, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            resp_headers = dict(resp.getheaders()) if with_headers else None
            if not keep_alive:
                conn.close()
            # HTTP 5xx 重试(R2 S3 API 偶发 InternalError,与网络异常重试对称)。
            # R2 侧偶发 500 InternalError 自愈,重试 1-2 次通常即成功,避免单文件 5xx
            # 致整批 ok!=total -> intraday 告警邮件轰炸(2026-07-30 修复)。
            # attempt 0-3 重试(sleep 1s/2s/4s/8s),attempt 4(最后一次)return 让调用方记失败。
            if resp.status >= 500 and attempt < 4:
                import time
                wait = 2 ** attempt  # 1s, 2s, 4s, 8s
                print(f"  ⚠ {method} {key} HTTP {resp.status} attempt {attempt+1}, {wait}s 后重试", file=sys.stderr)
                if keep_alive:
                    _drop_keepalive_conn()
                time.sleep(wait)
                continue
            if with_headers:
                return resp.status, data, resp_headers
            return resp.status, data
        except (ssl.SSLError, OSError, http.client.HTTPException) as e:
            last_exc = e
            if keep_alive:
                _drop_keepalive_conn()
            if attempt < 4:
                import time
                wait = 2 ** attempt  # 1s, 2s, 4s, 8s
                print(f"  ⚠ {method} {key} attempt {attempt+1} 失败({type(e).__name__}: {e}), {wait}s 后重试", file=sys.stderr)
                time.sleep(wait)
            else:
                raise
    raise last_exc  # 不可达,防 mypy


def s3_head(key, bucket=None, keep_alive=False, with_len=False):
    """HEAD 对象取 ETag(不下载 body)。返回 (status, etag_str_or_None) 或 with_len 时 (status, etag, content_length_or_None)。

    R2 单 PUT 的 ETag=内容 md5(本项目 upload_r2.py 单 PUT 走此判定; multipart 上传的对象
    ETag=分片 md5 组合(形如 xxxx-N) 不是内容 md5, 对账须改用「存在 + Content-Length==本地大小」,
    见 cmd_verify_r2._check / _upload_one)。层2 上传对账 + 层3 verify-r2 均用它: HEAD 快(单请求 RTT ~0.3s),
    比对「R2 对象 == 本地整文件 md5」验证上传正确性/查漏传。
    网络异常/5xx 退避重试 5 次, 最终失败返回 (0, None) —— 调用方按「不一致/缺失」处理
    (补传方向安全, 宁多传不漏传)。
    keep_alive=True(2026-09-21 R2 根治): 复用线程本地连接连续 HEAD, 省跨境握手(~1s/次)。
    """
    bkt = bucket or BUCKET
    for attempt in range(5):
        conn = None
        try:
            now = datetime.datetime.utcnow()
            amz_date = now.strftime("%Y%m%dT%H%M%SZ")
            date_stamp = now.strftime("%Y%m%d")
            payload_hash = hashlib.sha256(b"").hexdigest()
            path = f"/{bkt}"
            if key:
                path += "/" + quote(key, safe="/")
            headers = {
                "host": HOST,
                "x-amz-date": amz_date,
                "x-amz-content-sha256": payload_hash,
            }
            sorted_items = sorted(headers.items(), key=lambda x: x[0])
            canonical_headers = "".join(f"{k}:{v.strip()}\n" for k, v in sorted_items)
            signed_headers = ";".join(k for k, _ in sorted_items)
            canonical_request = "\n".join([
                "HEAD", path, "", canonical_headers, signed_headers, payload_hash,
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
            if keep_alive:
                conn = _get_keepalive_conn()
            else:
                conn = http.client.HTTPSConnection(HOST, timeout=R2_UPLOAD_HTTP_TIMEOUT, context=_CTX)
            conn.request("HEAD", path, headers=headers)
            resp = conn.getresponse()
            etag = resp.getheader("ETag")
            status = resp.status
            content_len = resp.getheader("Content-Length")
            resp.read()
            if not keep_alive:
                conn.close()
            if status >= 500 and attempt < 4:
                wait = 2 ** attempt
                if keep_alive:
                    _drop_keepalive_conn()
                print(f"  ⚠ HEAD {key} HTTP {status} attempt {attempt+1}, {wait}s 后重试", file=sys.stderr)
                time.sleep(wait)
                continue
            if with_len:
                return status, etag, content_len
            return status, etag
        except (ssl.SSLError, OSError, http.client.HTTPException) as e:
            if keep_alive:
                _drop_keepalive_conn()
            if attempt < 4:
                wait = 2 ** attempt
                print(f"  ⚠ HEAD {key} attempt {attempt+1} 失败({type(e).__name__}: {e}), {wait}s 后重试", file=sys.stderr)
                time.sleep(wait)
            else:
                if with_len:
                    return 0, None, None
                return 0, None
    if with_len:
        return 0, None, None
    return 0, None


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
        st, _ = s3_request("DELETE", key, bucket=BUCKET, keep_alive=True)
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
    """上传 static-site/data/lab/*.json 到 R2 lab/ 前缀(2026-09-15 迁增量引擎, A 档整文件 md5)。

    lab JSON 由 scripts/lab/*.py 按 __file__ 写 ROOT(trade/)static-site/data/lab/,
    REPO=trade-data 时 trade-data/static-site/data/lab/ 可能不存在(或滞后), 回退 ROOT。
    盘后 17:50 全重算, 非交易日全省(增量最大确定性收益); 原串行自写循环由引擎
    8 线程 + 状态清单 + 层2 ETag 对账替代(告警噪音根治 2026-09-11 语义保留在引擎:
    单文件失败不异常中断, 末尾 ok<total 才 exit 1)。
    """
    lab = STATIC_DIR / "data/lab"
    if not lab.exists() or not any(lab.glob("*.json")):
        lab = ROOT / "static-site" / "data" / "lab"
    if not any(f.exists() for f in lab.glob("*.json")):
        sys.exit(f"无 lab json: {lab}")
    # 失败时引擎内部已 print FAILED_FILES + exit 1
    _incremental_upload(
        lab, ["*.json"], "lab", ".r2_lab_state.json", label="lab")
    # lab 原命令不 purge(前端 lab 数据经 /data/ rewrite 读 R2, 短 TTL), 保持不 purge。


def _infer_content_type(key):
    ext = os.path.splitext(key)[1].lower()
    return _CONTENT_TYPE_MAP.get(ext, "application/octet-stream")


def _header_lookup(hdrs, name):
    """大小写不敏感取响应 header(A3 返修, 2026-09-21 reviewer): dict(resp.getheaders()) 的 key
    保留 wire 原始大小写, 若 R2/网关回小写 etag 等, 直接 hdrs.get("ETag") 会 miss → multipart
    永远判失败 abort。用统一小写比对兜底。"""
    if not hdrs:
        return None
    low = name.lower()
    for k, v in hdrs.items():
        if k.lower() == low:
            return v
    return None


def _parse_upload_id(resp_body):
    """从 InitiateMultipartUploadResult XML 解析 UploadId; 失败返回 None。"""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(resp_body)
        for el in root.iter():
            if el.tag.split("}")[-1] == "UploadId" and el.text:
                return el.text.strip()
    except ET.ParseError as e:
        print(f"  ⚠ multipart create 响应解析失败({e})", file=sys.stderr)
    return None


def _upload_multipart(key, payload, content_type):
    """大文件 multipart 上传: create -> 并行 upload-part -> complete(R2 官方流程)。

    2026-09-21 R2 上传失败根治: >100MB 单文件单 PUT 卡 600s 超时重试 5 次(放大器) →
    改 multipart 分片并行, 单片 64MiB 单请求时长 << HTTP/看门狗超时, 失败只重传片不整文件。
    注意: multipart 上传对象 ETag=分片组合(non-md5), 不参与 ETag=md5 对账(调用方以 complete
    200 视为内容就位; verify-r2 对 multipart 大文件改「存在 + Content-Length==本地大小」判定)。
    """
    # 1) create (POST /key?uploads=)
    st, data = s3_request("POST", key, payload=b"", query="uploads=", content_type=content_type)
    if st != 200:
        return st, data
    upload_id = _parse_upload_id(data)
    if not upload_id:
        return st, data

    # 2) 分片并行 upload-part (PUT /key?partNumber=N&uploadId=)
    sizes = _multipart_part_sizes(len(payload))
    from concurrent.futures import ThreadPoolExecutor, as_completed
    parts = {}
    offset = 0
    for i, sz in enumerate(sizes, 1):
        parts[i] = payload[offset:offset + sz]
        offset += sz

    def _put_part(pn):
        q = "partNumber=%d&uploadId=%s" % (pn, quote(upload_id, safe=""))
        # keep_alive(2026-09-22 同类根治): 每线程连续传多个 part 复用线程本地连接, 省 part 间握手
        s, d, hdrs = s3_request("PUT", key, payload=parts[pn], query=q,
                                content_type=content_type, with_headers=True, keep_alive=True)
        if s == 200:
            etag = _header_lookup(hdrs, "ETag")
            if etag:
                return pn, etag, None
        err = d[:200] if isinstance(d, (bytes, bytearray)) else d
        return pn, None, f"part {pn} status={s} {err}"

    uploaded = {}   # pn -> etag
    with ThreadPoolExecutor(max_workers=_MULTIPART_WORKERS) as pool:
        futs = {pool.submit(_put_part, pn): pn for pn in parts}
        for fut in as_completed(futs):
            pn, etag, err = fut.result()
            if err:
                try:
                    s3_request("DELETE", key, query="uploadId=%s" % quote(upload_id, safe=""))
                except Exception:
                    pass
                return 500, err.encode("utf-8", errors="replace")
            uploaded[pn] = etag

    # 3) complete (POST /key?uploadId= + CompleteMultipartUpload XML)
    if sorted(uploaded) != sorted(parts):
        try:
            s3_request("DELETE", key, query="uploadId=%s" % quote(upload_id, safe=""))
        except Exception:
            pass
        return 500, "multipart 缺分片, abort".encode("utf-8", errors="replace")
    parts_xml = "".join(
        "<Part><PartNumber>%d</PartNumber><ETag>%s</ETag></Part>" % (pn, uploaded[pn])
        for pn in sorted(uploaded))
    body = ("<CompleteMultipartUpload>%s</CompleteMultipartUpload>" % parts_xml).encode("utf-8")
    st, data = s3_request("POST", key, payload=body,
                          query="uploadId=%s" % quote(upload_id, safe=""),
                          content_type="application/xml")
    return st, data


def _upload_glob(local_dir, glob_patterns, r2_prefix, include_gz=True, exclude_fn=None,
                 only_files=None, on_success=None, verify_etag=False):
    """通用 glob 上传：local_dir 下按 patterns 匹配文件，上传到 R2 r2_prefix/。

    R2 key = r2_prefix/{相对 local_dir 的路径}。返回 (ok, total, failed_rels, uploaded_keys)。
    only_files(可选, 2026-08-23): 显式文件列表(Path 列表, 须位于 local_dir 下), 非 None 时
    跳过 glob 直接上传该列表 —— cmd_upload_etf_hist 增量上传用(调用方先按状态清单筛出
    有变化的文件)。glob_patterns 此时仅占位不参与匹配; exclude_fn 同样不生效(调用方已筛)。
    on_success(可选, 2026-08-25): 回调 (Path f, str rel) -> None, 每个文件 PUT 成功后
    在主线程 as_completed 循环内同步调用(非 worker 线程)—— cmd_upload_fund_nav 用它做
    分片 checkpoint 断点续传(kill 后从断点续传而非全量重跑, 治「超时 kill→状态缺失→
    下次更慢全量→再被 kill」恶性循环)。回调抛异常会中断整批(调用方自行保证幂等)。
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
            md5_local = hashlib.md5(payload).hexdigest()
            if size > _MULTIPART_THRESHOLD:
                # 大文件 multipart(2026-09-21 R2 根治): 单 PUT 卡 600s 超时重试 5 次放大器,
                # 改 create/并行 part/complete, 单片 64MiB 单请求时长可控。multipart 对象
                # ETag=分片组合(non-md5), complete 200 即内容就位, 不做 ETag=md5 对账。
                status, data = _upload_multipart(key, payload, _infer_content_type(key))
                if status == 200:
                    return (i, True, rel, size, None, key)
                return (i, False, rel, size,
                        f"multipart status={status} {data[:200] if isinstance(data, (bytes, bytearray)) else data}", None)
            status, data = s3_request("PUT", key, payload, keep_alive=True)
            if status == 200:
                # 层3 上传正确性对账(verify_etag=True 时): PUT 后 HEAD 取 ETag 与本地整文件
                # md5 比对, 不一致记上传失败(传上去的内容不对)。HEAD 失败(etag=None, 网络抖动/
                # 404)不判失败 —— 刚 PUT 成功, 对账通道传可信 ETag 更可能是 HEAD 抖动,
                # 若判失败会误报告警(09-10 事故链教训); 只有 ETag 明确存在且 != 本地 md5 才判失败。
                # keep_alive(2026-09-22 主上传通道补接, 2026-09-21 R2 根治只接了 verify-r2 通道):
                # PUT + 对账 HEAD 复用线程本地连接, 省每文件 2 次跨境握手(TCP 1.16s/首字节 2.10s),
                # 21957 文件(如 fund-nav)6225s -> ~1500-2000s, 治 deploy 攥锁 2h47m 连锁超时。
                if verify_etag:
                    _st, etag = s3_head(key, keep_alive=True)
                    if etag is not None and etag.strip('"') != md5_local:
                        return (i, False, rel, size,
                                f"ETag对账不一致 etag={etag} local_md5={md5_local}", None)
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
                if on_success is not None:
                    on_success(local_dir / str(rel), str(rel))
                print(f"[{done}/{total}] ✓ {rel} ({size}B)")
            else:
                print(f"[{done}/{total}] ✗ {rel} {err}")
                failed_rels.append(str(rel))
    print(f"共上传 {ok}/{total} -> {PUBLIC}/{r2_prefix}/")
    return ok, total, failed_rels, uploaded_keys


def _file_md5(path):
    """A 档指纹: 整文件字节 md5(大部分通道; 无天天变元数据字段的文件本体指纹)。"""
    return hashlib.md5(path.read_bytes()).hexdigest()


def _norm_state_val(v):
    """归一化状态 files 的值: 双字段 {size, md5} -> (size, md5); 旧单字段 md5 字符串 -> (None, md5)。"""
    if isinstance(v, dict):
        return (v.get("size"), v.get("md5"))
    if isinstance(v, str):
        return (None, v)  # etf-hist/fund-nav 旧状态: {name: md5字符串}, 迁移后兼容读取
    return (None, None)


def _kelly_parts_md5(path):
    """B 档指纹(kelly-parts / kelly-parts-sdc): 剔除 generated_at/period_cutoffs/buy_amount
    后规范化序列化 md5。

    三字段=生成器元数据(生成时刻+滚动周期切点+本金常量), 前端零消费(已 grep app.js/lab.js
    核实: _simParseTrades / _labKellyParseTrades 只取 fields/fIdx/quadrants, 顶层三字段不读);
    不剔除则天天变致增量失效(复现 etf-hist exported_at 先例)。json 解析失败退化为整文件字节
    md5(坏文件必与上次不同 -> 触发重传, 失败方向宁多勿漏)。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, dict):
            payload.pop("generated_at", None)
            payload.pop("period_cutoffs", None)
            payload.pop("buy_amount", None)
            raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            return hashlib.md5(raw.encode("utf-8")).hexdigest()
    except (OSError, ValueError):
        pass
    return hashlib.md5(path.read_bytes()).hexdigest()


def _etf_hist_md5(path):
    """C 档指纹(etf-hist): 剔除 exported_at 后规范化序列化 md5(先例原版 _fingerprint 同口径)。

    exported_at 天天变但与数据本体无关(前端零消费), 不剔除则天天判全变致增量失效。"""
    raw = None
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, dict):
            payload.pop("exported_at", None)
            raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (OSError, ValueError):
        raw = None
    if raw is None:
        return hashlib.md5(path.read_bytes()).hexdigest()
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _incremental_upload(local_dir, glob_patterns, r2_prefix, state_name, *,
                        fingerprint=None, exclude_fn=None, checkpoint_every=0,
                        dry_run=None, label=None):
    """通用增量上传引擎(2026-09-15 R2 上传增量化, 12 通道复用; 参数化 etf-hist 先例全套机制)。

    一次实现, 12 通道共用; 机制逐条继承 cmd_upload_etf_hist(scripts/upload_r2.py 先例):
      - 状态清单 data/.r2_<channel>_state.json 与数据同仓(untracked 不进 git), 结构
        {version, updated_at, mode, count, files:{rel:{size,md5}}, changed:[rel]};
        rel = 相对 local_dir 的路径(与 _upload_glob 的 rel 同口径, 便于 r2_key = r2_prefix/rel)。
      - 指纹: A 档整文件 md5(默认); B/C 档传 fingerprint 回调(结构化剔除)。size 字段按方案
        存双字段(结构对齐), 判定以 md5 为准(本地算 md5 快; 不做「size 快筛 + 上传后回填 md5」
        的 A/B 分叉优化, 少写抽象——见 CLAUDE.md §6.5)。
      - 首跑/状态缺失或损坏 -> 自动退化全量; 每周日强制全量一次(防 R2 侧对象丢失/状态漂移);
      - 增量 0 待传=正常完成(不报错, 防 deploy 把「今天没变化」当失败告警);
      - 状态只在全部上传成功后 tmp+os.replace 原子写; 部分失败保持旧状态下次重传面更大
        —— 失败方向宁多传不漏传;
      - fail-closed 未确认态(2026-09-23 ①): 上传开始前写 .r2_<channel>_uploading.marker,
        正常结束(全成功写状态)删除; 进程中途被 kill(看门狗 TERM/KILL)marker 残留 → 下轮
        scan 发现 → 强制全量重传(fail-closed: 宁可多传一次, 不可假成功)。兼容旧状态文件
        (无 marker 不触发全量, 首跑/周日仍按原逻辑)。
      - 待传字节量行 R2_BYTES_TOTAL=<N>(③): 看门狗(deploy.sh run_r2_upload)按 N/150KB/s×2
        余量+固定开销估算超时, 根治「固定 900s 杀近全量」的事故; 显式通道超时优先覆盖。
      - 层2 上传正确性对账: 本次 PUT 的 key 逐一 HEAD 取 ETag == 本地整文件 md5(_upload_glob
        verify_etag=True), 不一致记入 failed_rels(传上去的内容不对=失败, 触发调用方告警);
      - checkpoint_every>0 时启用分片 checkpoint 断点续传(fund-nav 模式, 治「超时 kill->状态
        缺失->下次更慢全量->再被 kill」恶性循环); checkpoint 落 data/.r2_<channel>_ckpt.json;
      - dry_run=True 只打印「将传 N/M」不 PUT(验收自测用)。
    返回 (ok, total, failed_rels, uploaded_keys) —— 与 _upload_glob 同签名, 调用方照旧拿
    uploaded_keys 调 purge_cache(引擎不负责 purge, 各通道 purge 口径不同由通道函数自理)。"""
    label = label or state_name
    local_dir = Path(local_dir)
    fingerprint = fingerprint or _file_md5
    state_path = STATIC_DIR.parent / "data" / state_name
    # 上传开始标记(fail-closed, 2026-09-23 ①假成功根治): 上传进程若在 PUT 中途被外部 kill
    # (看门狗超时 TERM/KILL), 状态文件不会写(引擎只在全成功后才写), 下轮只能基于上一轮状态
    # 判定增量——但若此前某轮状态文件已记录「新指纹」而 kill 发生在写入后的 R2 一致性验证之前,
    # 未真正落到 R2 的文件会被判「待传 0」永久跳过 → 静默缺口固化(9-23 事故: kelly-parts/
    # sdc-parts 共 27 个 R2 缺口 --dry-run 显示"待传 0")。上传开始前写 marker, 正常结束删除;
    # scan 发现残留 marker → 强制全量重传(fail-closed: 宁可多传一次, 不可假成功)。
    marker_path = state_path.with_name(state_name.replace("_state.json", "_uploading.marker"))
    if dry_run is None:
        dry_run = _DRY_RUN

    # 1. 收集文件(glob + exclude_fn + broken symlink 过滤), 与 _upload_glob 收集逻辑同口径
    files = []
    for pat in glob_patterns:
        files.extend(local_dir.glob(pat))
    files = sorted(set(files))
    if exclude_fn:
        before = len(files)
        files = [f for f in files if not exclude_fn(f)]
        excluded = before - len(files)
        if excluded:
            print(f"[{label}] 排除 {excluded} 个文件(exclude_fn)")
    broken = [f for f in files if not f.exists()]
    if broken:
        print(f"[{label}] ⚠ 跳过 {len(broken)} 个不存在/broken-symlink 文件(首个: {broken[0]})")
        files = [f for f in files if f.exists()]
    if not files:
        print(f"[{label}] ⚠ {local_dir} 下 {glob_patterns} 无匹配文件")
        return 0, 0, [], []
    all_json = sorted(files)

    # 2. 读状态(兼容 etf-hist/fund-nav 旧单字段格式, 归一化到 (size, md5))
    old_files = {}
    if state_path.exists():
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                st = json.load(f)
            if isinstance(st.get("files"), dict):
                old_files = st["files"]
        except (OSError, ValueError):
            print(f"[{label}] ⚠ 状态清单损坏/不可读({state_path}), 退化为全量")
            old_files = {}

    # 3. 指纹扫描 + 增量判定
    t0 = time.time()
    sigs = {}       # rel -> {size, md5}
    changed = []    # 待传文件(Path)
    for p in all_json:
        rel = str(p.relative_to(local_dir))
        try:
            sz = p.stat().st_size
        except OSError:
            continue
        md5 = fingerprint(p)
        sigs[rel] = {"size": sz, "md5": md5}
        old = _norm_state_val(old_files.get(rel))
        if old[1] is None or old[1] != md5:
            changed.append(p)

    today_weekday = datetime.date.today().weekday()   # Monday=0 ... Sunday=6
    marker_stale = marker_path.exists()
    if marker_stale:
        print(f"[{label}] ⚠ 检测到上次上传未正常结束({marker_path.name}), 强制全量重传(fail-closed)")
    force_full = (not old_files) or today_weekday == 6 or marker_stale
    if marker_stale:
        mode = "上次上传中断强制全量"
    elif today_weekday == 6 and old_files:
        mode = "周日强制全量"
    elif not old_files:
        mode = "首次/无状态全量"
    else:
        mode = "增量"
    if force_full:
        changed = list(all_json)

    print(f"[{label}] 模式={mode} 本次待传 {len(changed)}/{len(all_json)}"
          f"(其余 {len(all_json) - len(changed)} 个内容未变化跳过)")

    def _save_state(sig_map, run_mode, changed_rels):
        """原子写状态清单(tmp + os.replace); 仅在上传全部成功后调用。
        状态重建为本次扫描全集, 本地已删除条目自然剔除(R2 残留旧 key 无害, 不做删除)。
        changed 字段记录本次实际待传 rel 清单, 供 verify-r2 平日对账「当日增量通道的 key」。"""
        new_state = {
            "version": 1,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "mode": run_mode,
            "count": len(sig_map),
            "files": sig_map,
            "changed": changed_rels,
        }
        state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = state_path.with_name(state_path.name + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(new_state, f, ensure_ascii=False, sort_keys=True)
        os.replace(tmp_path, state_path)

    if not changed:
        elapsed = time.time() - t0
        print(f"[{label}] ✓ 全部 {len(all_json)} 个内容未变化, 无需上传, 耗时 {elapsed:.1f}s")
        if dry_run:
            print(f"[{label}] [dry-run] 无待传文件")
        else:
            _save_state(sigs, mode, [])
            try:
                marker_path.unlink(missing_ok=True)   # 本轮完整结束, 清理残留 marker
            except OSError:
                pass
        return 0, 0, [], []

    changed_rels = [str(p.relative_to(local_dir)) for p in changed]

    # 待传字节量(③ 看门狗按字节量估算超时): 机器可解析行 R2_BYTES_TOTAL=<N>。增量小 → 小超时;
    # 全量/周日/中断回退大 → 大超时(9-23 事故: 近全量 190MB@~150KB/s 需 950-1270s, 固定 900s
    # 零并发都可能被杀; 按字节量估算才不误杀)。dry-run 也打印供人工校验。
    total_pending = sum(p.stat().st_size for p in changed if p.exists())
    print(f"[{label}] R2_BYTES_TOTAL={total_pending}")

    if dry_run:
        print(f"[{label}] [dry-run] 将传 {len(changed)}/{len(all_json)} 个文件(不 PUT):")
        for rel in changed_rels:
            print(f"  - {r2_prefix}/{rel}")
        return len(changed), len(changed), [], []

    # 上传开始标记: 正常结束(_save_state)时删除; 中途被 kill(看门狗/系统)则残留 → 下轮强制全量。
    try:
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(time.strftime("%Y-%m-%dT%H:%M:%S") + f" pid={os.getpid()}", encoding="utf-8")
    except OSError as e:
        print(f"[{label}] ⚠ 上传标记写入失败({e})", file=sys.stderr)

    # 4. checkpoint 续传(checkpoint_every>0, fund-nav 模式)
    ckpt_path = None
    ckpt_files = {}
    if checkpoint_every > 0:
        ckpt_path = state_path.with_name(state_name.replace("_state.json", "_ckpt.json"))

        def _save_ckpt(done_map):
            """checkpoint 原子写(tmp + fsync + rename), 崩溃不留半截。"""
            ckpt_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = ckpt_path.with_name(ckpt_path.name + f".tmp.{os.getpid()}")
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump({"version": 1,
                               "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                               "count": len(done_map),
                               "files": done_map}, f, ensure_ascii=False, sort_keys=True)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, ckpt_path)
            except OSError:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
                raise

        try:
            with open(ckpt_path, "r", encoding="utf-8") as f:
                st = json.load(f)
            if isinstance(st.get("files"), dict):
                ckpt_files = st["files"]
        except (OSError, ValueError):
            ckpt_files = {}
        if ckpt_files:
            # 上次中断的 checkpoint 里, 指纹与当前仍一致的文件视为已传成功, 从待传清单剔除
            resumed_rels = {str(p.relative_to(local_dir)) for p in changed
                            if ckpt_files.get(str(p.relative_to(local_dir))) == sigs[str(p.relative_to(local_dir))]["md5"]}
            n_resumed = len(resumed_rels)
            changed = [p for p in changed if str(p.relative_to(local_dir)) not in resumed_rels]
            if n_resumed:
                print(f"[{label}] ↩ 断点续传: checkpoint 命中 {n_resumed} 个已上传(跳过), "
                      f"本次实传 {len(changed)} 个")

    # 5. 上传(only_files + 8 线程 + 层2 ETag 对账)
    done_map = dict(ckpt_files)   # 继承旧 checkpoint, 累积本次新成功
    since_ckpt = 0

    def _on_success(f, rel):
        nonlocal since_ckpt
        done_map[str(rel)] = sigs[str(rel)]["md5"]
        since_ckpt += 1
        if checkpoint_every > 0 and since_ckpt >= checkpoint_every:
            _save_ckpt(done_map)
            since_ckpt = 0

    ok, total, failed_rels, uploaded_keys = _upload_glob(
        local_dir, glob_patterns, r2_prefix, only_files=changed,
        on_success=_on_success if checkpoint_every > 0 else None,
        verify_etag=True)
    elapsed = time.time() - t0
    if total == 0:
        sys.exit(f"[{label}] 无文件可传: {local_dir}")
    print(f"[{label}] ✓ 上传完成 {ok}/{total}, 耗时 {elapsed:.1f}s "
          f"(较全量少传 {len(all_json) - total} 个)")

    if ok != total:
        # 失败也把已成功部分刷进 checkpoint(下轮续传), 但 state 保持旧值不写 —— 宁多传不漏传。
        if ckpt_path is not None:
            try:
                _save_ckpt(done_map)
            except OSError as e:
                print(f"[{label}] ⚠ checkpoint 落盘失败({e}), 下轮将从断点前续传")
        print(f"FAILED_FILES: {', '.join(failed_rels)}")
        sys.exit(1)

    _save_state(sigs, mode, changed_rels)
    try:
        marker_path.unlink(missing_ok=True)   # 全量成功 → 上传标记使命结束
    except OSError:
        pass
    if ckpt_path is not None:
        try:
            ckpt_path.unlink(missing_ok=True)  # 全量完成, checkpoint 使命结束清理
        except OSError:
            pass

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
    if not any(f.exists() for f in ts_dir.glob("trade_sim_*.html")):
        sys.exit(f"无 trade_sim html: {ts_dir}/trade_sim_*.html")
    # 失败时引擎内部已 print FAILED_FILES + exit 1
    _incremental_upload(
        ts_dir, ["trade_sim_*.html"], "trade_sim", ".r2_trade_sim_html_state.json", label="trade-sim")


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
    if not any(f.exists() for f in ts_dir.glob("*.json")):
        sys.exit(f"无 trade_sim json: {ts_dir}")
    # 失败时引擎内部已 print FAILED_FILES + exit 1
    _, _, _, uploaded_keys = _incremental_upload(
        ts_dir, ["*.json"], "trade_sim_data", ".r2_trade_sim_json_state.json", label="trade-sim-json")
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
    if not any(f.exists() for f in idx_dir.glob("*.json")):
        sys.exit(f"无 index json: {idx_dir}")
    # 失败时引擎内部已 print FAILED_FILES(rel 相对 index/, intraday_snapshot.sh 抓取引用告警 body)+ exit 1
    _, _, _, uploaded_keys = _incremental_upload(
        idx_dir, ["*.json"], "index", ".r2_index_state.json", label="index")
    # 清 CF 边缘缓存(同 cmd_upload_industry 模式):uploaded_keys 含 "index/" 前缀,
    # cache_prefix="/r2/" -> "/r2/index/{id}-all.json" 匹配 r2ProxyHandler cacheKey。
    # 不用 "/r2/index/" 否则双 index 致 purge 无效。
    purge_cache(uploaded_keys, cache_prefix="/r2/")


def cmd_upload_etf_hist():
    """上传 static-site/data/etf/*.json 到 R2 etf/ 前缀(#10 ETF 弹窗长历史, 2026-08-22)。

    R2 key = etf/{code}-all.json(1532 只全史日K, scripts/export_etf_hist.py 生成)。
    前端 ETF 评分弹窗 period tab 懒加载 fetchJSON -> https://ss.fx8.store/r2/etf/{code}-all.json。

    2026-09-15 迁移进通用增量引擎 _incremental_upload(口径零变化):
      - C 档指纹 _etf_hist_md5 = 剔除 exported_at 后规范化序列化 md5(前端零消费, 已 grep 核实),
        数据本体(ohlc/name/count/date 等)真变才传, 免疫 export 每天全量重写 mtime 抖动;
      - 沿用状态文件名 .r2_etf_hist_state.json(旧单字段 {name:md5} 格式引擎 _norm_state_val
        兼容读取); 首跑/状态损坏退化全量、周日强制全量、原子写状态、宁多传不漏传语义不变;
      - 新增层2 ETag 对账(本次 PUT 后 HEAD 对 ETag==本地 md5, 不一致判失败)。
    purge 只清本次实际上传 key(cache_prefix="/r2/")。
    """
    etf_dir = STATIC_DIR / "data/etf"
    if not any(f.exists() for f in etf_dir.glob("*.json")):
        sys.exit(f"无 etf json: {etf_dir} (先跑 scripts/export_etf_hist.py 生成)")
    _, _, _, uploaded_keys = _incremental_upload(
        etf_dir, ["*.json"], "etf", ".r2_etf_hist_state.json",
        fingerprint=_etf_hist_md5, label="etf-hist")
    purge_cache(uploaded_keys, cache_prefix="/r2/")


def cmd_upload_fund_nav():
    """上传 static-site/data/nav_bucket/*.json 到 R2 nav_bucket/ 前缀(#11 基金弹窗净值走势, 2026-08-25)。

    R2 key = nav_bucket/{xx}.json(256 桶全史净值, scripts/export_fund_nav.py 生成)。
    前端基金评分弹窗「净值走势」period tab 懒加载 fetchJSON ->
    https://ss.fx8.store/r2/nav_bucket/{xx}.json 取桶内 map[code](复刻 etf/{code}-all.json
    模式: worker /r2/ 为通用 key 代理无前缀白名单, 新前缀零 worker 改动)。
    §8.1 按前缀建独立命令; nav_bucket/ 子目录不被 upload-data-large/upload-all-data 的
    非递归 *.json glob 覆盖, 无双副本风险。已接入 update_all.sh / deploy.sh。

    **2026-09-23 桶化**(docs/ops/task-slow-rootcause-20260923.md §9B): 原 per-code 26458
    个文件(9-22 传 21957 个 6225s 占 deploy 56%) -> 桶化后 PUT 次数固定 256, 上传耗时
    有界。桶名 = FNV-1a hash(code) 末 8bit(00-ff), 前后端同构(_fund_bucket ==
    app.js _fundNavBucket, 防第二份实现漂移 §5.4⑦)。

    2026-09-15 迁移进通用增量引擎 _incremental_upload(口径零变化):
      - A 档整文件字节 md5。export_fund_nav.py **不放 exported_at 字段**(与 etf-hist 差异),
        桶内容只在净值序列真变化时变化; 清盘老基金序列冻结 -> 内容不变 -> 指纹不变 ->
        自然跳过, 每日真重传仅活跃桶;
      - 沿用状态文件名 .r2_fund_nav_state.json(旧单字段 {name:md5} 引擎 _norm_state_val 兼容)
        + checkpoint_every=500 断点续传(治「超时 kill→状态缺失→下次更慢全量→再被 kill」
        恶性循环), checkpoint 文件 .r2_fund_nav_ckpt.json 同名同仓;
      - 首跑/状态损坏退化全量、周日强制全量、原子写状态、宁多传不漏传语义不变;
      - 新增层2 ETag 对账(本次 PUT 后 HEAD 对 ETag==本地 md5, 不一致判失败)。
      - **跳过 purge(F3 主控拍板 NO_CACHE, 2026-08-25)**: worker 对 nav_bucket/ 前缀 no-store
        不查不写 edge cache, 前端每次回源 R2 拿最新; 日增量 256 keys 的 purge 本身秒级,
        但沿用 no-store 语义省掉(与旧 fund_nav/ 前缀一致)。
    """
    nav_dir = STATIC_DIR / "data/nav_bucket"
    if not any(f.exists() for f in nav_dir.glob("*.json")):
        sys.exit(f"无 nav_bucket json: {nav_dir} (先跑 scripts/export_fund_nav.py 生成)")
    # 失败时引擎内部已 print FAILED_FILES + exit 1(宁多传不漏传, checkpoint 续传语义在引擎内)
    _incremental_upload(
        nav_dir, ["*.json"], "nav_bucket", ".r2_fund_nav_state.json",
        checkpoint_every=500, label="fund-nav")
    # 不调 purge_cache(F3): 见 docstring。


def cmd_upload_accum_nav():
    """上传 static-site/data/accum_nav/*.json 到 R2 accum_nav/ 前缀(凯利 G/H/I 强平日真实净值 per-ETF 懒加载, 2026-09-17)。

    R2 key = accum_nav/{code}.json(~1554 只全史累计净值, export_accum_nav_map.py --all 生成拆分)。
    前端 common.js _kkellyRealNavEnsureCodes 懒加载 fetchJSON ->
    https://ss.fx8.store/r2/accum_nav/{code}.json(仅拉组合涉及的 ≤116 只, 复刻 etf/{code}-all.json
    模式: worker /r2/ 为通用 key 代理无前缀白名单, 新前缀零 worker 改动)。
    全量 accum_nav_map.json 继续每日生成+上传(data-large), 作回测本地源 + 对账对象 + 回退兜底(§23.7 新增不改旧)。

    2026-09-17 复用通用增量引擎 _incremental_upload(与 fund-nav 同口径):
      - A 档整文件 md5。accum_nav/{code}.json **不放 exported_at 字段**, 且历史日 nav append-only 永不变,
        文件内容只在「该 ETF 新增净值日」时变化 → 每日增量仅更新昨日新出的 code 子集;
      - 状态文件名 .r2_accum_nav_state.json; 首跑/状态损坏退化全量、周日强制全量、原子写状态、
        宁多传不漏传语义不变(与 fund-nav 同, 对象数仅 ~1554 无 checkpoint 需求);
      - 层2 ETag 对账(本次 PUT 后 HEAD 对 ETag==本地 md5, 不一致判失败)。
      - purge 用 etf 模式(非 fund_nav no-store): 边缘 3600s + 上传后 purge 本次 key(cache_prefix="/r2/"),
        nav 历史日 append-only 强平日都是历史日期, 1h 边缘缓存重开弹窗零流量(方案 §三 依据)。
    """
    nav_dir = STATIC_DIR / "data/accum_nav"
    if not any(f.exists() for f in nav_dir.glob("*.json")):
        sys.exit(f"无 accum_nav json: {nav_dir} (先跑 scripts/export_accum_nav_map.py --all 生成)")
    _, _, _, uploaded_keys = _incremental_upload(
        nav_dir, ["*.json"], "accum_nav", ".r2_accum_nav_state.json",
        label="accum-nav")
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

    2026-09-15 迁增量引擎(A 档整文件 md5, 4 组 glob pattern 保留): 非交易日全省, 盘中/盘后
    行情天天变时只传变化文件。
    """
    data_dir = STATIC_DIR / "data"
    # 3 个拆分目录 + 扁平 industry-*.json
    patterns = [
        "industry-all-indices/*",
        "industry-5y-indices/*",
        "industry-3y-indices/*",
        "industry-*.json",
    ]
    if not any(f.exists() for pat in patterns for f in data_dir.glob(pat)):
        sys.exit(f"无 industry 文件: {data_dir}/industry-*")
    _, _, _, uploaded_keys = _incremental_upload(
        data_dir, patterns, "industry", ".r2_industry_state.json", label="industry")
    purge_cache(uploaded_keys, cache_prefix="/r2/")


def cmd_upload_public_fund():
    """上传 static-site/data/public_fund*.json 到 R2 public_fund/ 前缀(按类别,无大小阈值)。

    覆盖当前 5 小样本 + 未来全量品种(public_fund-{id}-holdings-5y.json 等)。
    架构同 lab/index/industry(按路径前缀,非大小阈值),新增品种自动走 R2 零维护。
    2026-09-15 迁增量引擎(A 档整文件 md5); 无文件=正常(引擎返回 0 待传, 不 purge)。
    """
    data_dir = STATIC_DIR / "data"
    _, _, _, uploaded_keys = _incremental_upload(
        data_dir, ["public_fund*.json"], "public_fund",
        ".r2_public_fund_state.json", label="public-fund")
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
    2026-09-15 迁增量引擎(A 档整文件 md5): 盘后重算时天天变, 非交易日全省。
    """
    data_dir = STATIC_DIR / "data"
    _, _, _, uploaded_keys = _incremental_upload(
        data_dir, ["etf_score_list_*.json"], "data",
        ".r2_etf_score_state.json", label="etf-score")
    purge_cache(uploaded_keys, cache_prefix="/r2/")


def cmd_upload_kelly_parts():
    """上传 static-site/data/signal_kelly_trades_parts/*.json 到 R2 data/signal_kelly_trades_parts/ 前缀。

    2026-08-22 首页模拟回测弹窗分片加载(recent.json 热区片 + t{YYYY}.json 年片)。
    §8.1 新类别按前缀建独立命令(子目录不被 upload-data-large/upload-all-data 的非递归
    *.json glob 覆盖, 必须独立命令)。前端走 /data/ rewrite 原生 URL, R2 key =
    data/signal_kelly_trades_parts/<name>, purge 用默认 cache_prefix="/"(匹配 dataRewriteHandler)。
    2026-09-15 迁增量引擎(B 档结构化指纹: 剔除 generated_at/period_cutoffs/buy_amount 后
    md5, 前端零消费已 grep 核实) —— 深历史片(t2019/t2016 等)跨天本体一致可省, 工作日
    省 ~10-15MB, 非交易日全省。
    """
    parts_dir = STATIC_DIR / "data" / "signal_kelly_trades_parts"
    _, _, _, uploaded_keys = _incremental_upload(
        parts_dir, ["*.json"], "data/signal_kelly_trades_parts",
        ".r2_kelly_parts_state.json", fingerprint=_kelly_parts_md5, label="kelly-parts")
    purge_cache(uploaded_keys)


def cmd_upload_kelly_parts_sdc():
    """上传 static-site/data/signal_kelly_trades_sdc_parts/*.json 到 R2 data/signal_kelly_trades_sdc_parts/ 前缀。

    #91(2026-09-06) 当日收盘对比档分片: 凯利回测页「买入口径」切到「当日收盘」时按年分片渐进加载,
    产物与 NDO(次日开盘)完全独立(signal_kelly_trades_sdc_parts/), 由 signal_kelly_backtest.py
    KELLY_BUY_NEXTDAY=0 生成。§8.1 同规矩独立命令(子目录 glob 不递归); 前端 /data/ rewrite
    R2 key = data/signal_kelly_trades_sdc_parts/<name>, purge 默认 cache_prefix="/"。
    2026-09-15 迁增量引擎(B 档结构化指纹, 同 kelly-parts)。
    """
    parts_dir = STATIC_DIR / "data" / "signal_kelly_trades_sdc_parts"
    _, _, _, uploaded_keys = _incremental_upload(
        parts_dir, ["*.json"], "data/signal_kelly_trades_sdc_parts",
        ".r2_kelly_sdc_state.json", fingerprint=_kelly_parts_md5, label="kelly-parts-sdc")
    purge_cache(uploaded_keys)


def cmd_upload_kelly_snapshots():
    """上传 static-site/data/signal_kelly_snapshots/*.json 到 R2 data/signal_kelly_snapshots/ 前缀。

    2026-09-04 信号凯利回测断链根治配套(每日快照+演进 index, 见 scripts/signal_kelly_snapshot.py)。
    §8.1 新类别按前缀建独立命令(子目录不被 upload-data-large/upload-all-data 的非递归
    *.json glob 覆盖, 必须独立命令)。前端 lab 凯利区「演进」读 ./data/signal_kelly_snapshots/
    index.json(dataRewriteHandler 原生 URL), R2 key = data/signal_kelly_snapshots/<name>,
    purge 用默认 cache_prefix="/"(匹配 dataRewriteHandler)。
    2026-09-15 迁增量引擎(A 档整文件 md5): 每日新增快照=新文件自然增量, 旧快照不变跳过。
    """
    snap_dir = STATIC_DIR / "data" / "signal_kelly_snapshots"
    if not snap_dir.exists():
        print(f"ℹ 快照目录不存在(尚无快照): {snap_dir}")
        return
    _, _, _, uploaded_keys = _incremental_upload(
        snap_dir, ["*.json"], "data/signal_kelly_snapshots",
        ".r2_kelly_snapshots_state.json", label="kelly-snapshots")
    purge_cache(uploaded_keys)


# ---- data-large / all-data 文件集划分共享口径(2026-09-15 修双传, 设计文档 §1.1/§3.5) ----
# 两个命令都扫 static-site/data/ 顶层 *.json, 必须互斥(同 key 双传 = 纯浪费, 每天 ~34MB@4.2Mbps≈68s)。
# 口径: data-large 传「>=1MB 或 大 range 或 overfit_monitor 前缀」; all-data 传「其余小文件」。
# 互斥机检断言(data-large ∩ all-data = ∅)见 cmd_verify_r2 内部, 口径常量集中此处防两命令漂移。
_DATA_EXCLUDE_PREFIXES = ("industry-", "public_fund", "offshore_fund", "fund_score", "etf_score_list")
# 大 range 文件前端 dataUrl 必走 R2(与 app.js _R2_LARGE_RANGE_RE 同规则), 无大小限制上传
# (2026-08-03 sentiment-3y 962KB<1MB 漏传致线上 404 修复)
_LARGE_RANGE_RE = re.compile(r'-(?:all|5y|3y)\.json$')
LARGE_THRESHOLD = 1 * 1024 * 1024  # 1MB


def _is_data_large_file(f):
    """data-large 上传条件(满足任一): 大 range 文件(前端强制走 R2) / >=1MB 阈值兜底 /
    overfit_monitor 前缀(首页走势图盘后核心产物, static-site/data/ 已整体 gitignore 移出 git,
    不传 R2 则备站/主站 /data/ rewrite 拿不到; 2026-08-24 B拆分覆盖主文件+ext)。"""
    if any(f.name.startswith(p) for p in _DATA_EXCLUDE_PREFIXES):
        return False
    try:
        sz = f.stat().st_size
    except OSError:
        return False
    return (sz >= LARGE_THRESHOLD or bool(_LARGE_RANGE_RE.search(f.name))
            or f.name.startswith("overfit_monitor"))


def _is_all_data_excluded(f):
    """all-data 排除条件(True=跳过): 独立命令前缀 + signal_kelly_trades + 大 range + overfit_monitor
    + >=1MB。后两者与 data-large 文件集互斥(修双传, 设计文档 §3.5)。"""
    name = f.name
    if any(name.startswith(p) for p in _DATA_EXCLUDE_PREFIXES):
        return True
    if name.startswith("signal_kelly_trades"):
        return True
    if _LARGE_RANGE_RE.search(name):
        return True
    if name.startswith("overfit_monitor"):
        return True
    try:
        return f.stat().st_size >= LARGE_THRESHOLD
    except OSError:
        return False


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

    2026-09-15 迁增量引擎(A 档整文件 md5, 顺手改串行自写循环 → 8 线程): 稳定件
    (kelly_loss_features 等)跨天不变自然跳过, 工作日省稳定件, 非交易日全省。
    """
    data_dir = STATIC_DIR / "data"
    _, _, _, uploaded_keys = _incremental_upload(
        data_dir, ["*.json"], "data", ".r2_data_large_state.json",
        exclude_fn=lambda f: not _is_data_large_file(f), label="data-large")
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
            conn = http.client.HTTPSConnection("ss.fx8.store", timeout=R2_UPLOAD_HTTP_TIMEOUT, context=_CTX)
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
      - signal_kelly_trades* (>=1MB,upload-data-large 已覆盖,防双副本)
      - signal_kelly_trades_parts/ 子目录(upload-kelly-parts 独立命令; *.json glob 不递归天然不匹配,此处记录防漏)
      - signal_kelly_snapshots/ 子目录(upload-kelly-snapshots 独立命令; *.json glob 不递归天然不匹配,此处记录防漏)
      - 大 range 文件 *-{all,5y,3y}.json (upload-data-large -> data/ 前缀)
      - **>=1MB 或 overfit_monitor 前缀**(upload-data-large 已覆盖, 2026-09-15 修双传 §1.1:
        原口径漏排 >=1MB 文件, 与 data-large 每天双传同 key ~34MB; 现两命令文件集互斥)
      - .gz 不再生成(CF 自动 br 压缩替代),只传 *.json pattern
      - feed.xml: 非 .json,*.json glob 天然不匹配
    2026-09-15 迁增量引擎(A 档整文件 md5): purge 只清本次实际上传 key(未变化文件 R2 已最新)。
    """
    data_dir = STATIC_DIR / "data"
    _, _, _, uploaded_keys = _incremental_upload(
        data_dir, ["*.json"], "data", ".r2_all_data_state.json",
        exclude_fn=_is_all_data_excluded, label="all-data")
    # 阶段2：上传成功后清 CF 边缘缓存（purge_cache 失败不中断; 只 purge 本次实际上传 key）
    purge_cache(uploaded_keys)


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
                  r'overfit_monitor|news_digest|signal_stats|'
                  r'signal_kelly_trades_intraday|signal_kelly_backtest_intraday)\.json$', pathname):
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
            st, _ = s3_request("DELETE", key, bucket=bkt, keep_alive=True)
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


def cmd_upload_decommissioned(local, key_name):
    """退役归档上传到 R2 signal-backup 私有桶 decommissioned/ 前缀(独立前缀,不进 _prune)。

    用于本地大件/历史 bak 清理时的异地归档:git 不进大文件,manifest+恢复脚本进 git,
    数据本体进 R2 私有桶 decommissioned/(不受 backup//weekly//monthly/ 滚动清理影响,天然长期留存)。

    两个子模式:
      upload-decommissioned <local_path> <key_name>
        gzip 压缩上传,key = decommissioned/<key_name>。
        local 以 .gz/.tar.gz 结尾视为已压缩,直接读取原始字节上传(不二次 gzip)。
      参考 cmd_upload_claude_backup 的 gzip+s3_request(PUT) 范式;key_name=上传后 R2 文件名,
        自动加 decommissioned/ 前缀。R2 key 建议带日期(如 xxx-20260903.gz)便于反查上传时刻。
    """
    import gzip
    src = Path(local)
    if not src.exists():
        sys.exit(f"文件不存在: {src}")
    raw = src.read_bytes()
    if src.name.endswith((".gz", ".tar.gz")):
        payload = raw  # 已压缩，直接传
        size_note = f"{len(raw) // 1024}KB(已压缩直传)"
    else:
        payload = gzip.compress(raw, compresslevel=6)
        size_note = f"{len(raw) // 1024}KB -> {len(payload) // 1024}KB gzip"
    key = f"decommissioned/{key_name}"
    status, data = s3_request("PUT", key, payload, bucket=BACKUP_BUCKET)
    if status == 200:
        print(f"✓ {src.name} ({size_note}) -> {BACKUP_BUCKET}/{key} (私有桶,退役归档)")
        return key
    sys.exit(f"✗ 上传失败 {key} status={status} {data.decode('utf-8', errors='replace')[:300]}")


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


def _large_json_staticdata_repo():
    """解析 staticdata 备份 git 仓库路径(env STATICDATA_REPO > 默认), 云上单仓回退(同
    staticdata_backup_async.sh L50-52 / large_json_excludes.py)。"""
    repo = Path(os.environ.get("STATICDATA_REPO", "/Users/linhuichen/code/trade-data-signal-staticdata"))
    if not (repo / ".git").is_dir():
        git_repo = os.environ.get("GIT_REPO", "")
        if git_repo and Path(f"{git_repo}-staticdata/.git").is_dir():
            repo = Path(f"{git_repo}-staticdata")
    if not (repo / ".git").is_dir():
        sys.exit(f"✗ staticdata 仓库不存在(.git 缺失): {repo}")
    return repo


def _tier_of_today(today_str):
    """保留档位判定: 日(总是) + 周(周日那份) + 月(每月1号那份)。"""
    import datetime as _dt
    d = _dt.datetime.strptime(today_str, "%Y-%m-%d").date()
    tier = ["日"]
    if d.isoweekday() == 7:
        tier.append("周")
    if d.day == 1:
        tier.append("月")
    return "+".join(tier)


def _prune_large_json(bucket=None):
    """large-json/ 前缀分层滚动清理(复用 _list_keys 列取 + _prune_layer 逐 key DELETE 模式,
    DB 备份 backup/ weekly/ monthly/ 三层独立清理同构; key 日期在目录前缀故不能用 _prune_layer 正则):

      - 日档: 保留最近 14 天(含今天)的 large-json/<YYYY-MM-DD>/ 目录。
      - 周档: 周日生成的目录, 保留最近 8 个存在的周日目录(ISO 周日=一周最后一天)。
      - 月档: 每月1号生成的目录, 保留最近 12 个存在的1号目录。
    任一目录被任一层保留 = 整目录 key 保留; 否则 DELETE(幂等, 重跑无害)。"""
    import re
    import datetime as _dt
    bkt = bucket or BACKUP_BUCKET
    keys = _list_keys("large-json/", bucket=bkt)
    by_date = {}
    for k in keys:
        m = re.match(r"large-json/(\d{4}-\d{2}-\d{2})/", k)
        if m:
            by_date.setdefault(m.group(1), []).append(k)
    if not by_date:
        return 0
    dates = sorted(by_date)
    today = _dt.datetime.now().date()
    keep = set()
    # 日档: 最近 14 天(含今天)
    for d in dates:
        dd = _dt.datetime.strptime(d, "%Y-%m-%d").date()
        if (today - dd).days < 14:
            keep.add(d)
    # 周档: 最近 8 个存在的周日目录
    sundays = [d for d in dates
               if _dt.datetime.strptime(d, "%Y-%m-%d").date().isoweekday() == 7]
    keep.update(sundays[-8:])
    # 月档: 最近 12 个存在的每月1号目录
    firsts = [d for d in dates if d.endswith("-01")]
    keep.update(firsts[-12:])
    deleted = 0
    for d in dates:
        if d in keep:
            continue
        for k in by_date[d]:
            st, _ = s3_request("DELETE", k, bucket=bkt, keep_alive=True)
            if st in (204, 404):
                deleted += 1
            else:
                print(f"  ⚠ 删除失败 {bkt}/{k} status={st}")
    if deleted:
        print(f"{bkt} large-json/ 滚动清理共 {deleted} 个旧 key(保留 {len(keep)} 个目录: 日14天+周8周+月12月)")
    return deleted


def _write_large_json_manifest(rows, today_str):
    """自动重写 docs/large-json-backup-manifest.md(排除对象 ↔ R2 副本索引, 不手工维护)。

    固定头部内嵌恢复侧说明(2026-09-26 审查整改, feat/large-json-r2-core): 恢复侧分支
    feat/large-json-r2-restore 写的说明文要点并入生成器头部, 防整体重写把恢复指引覆盖成简表头。

    幂等(#115, 2026-09-26): 头部时间戳只到日期(not 时分秒)——否则同内容每次跑 manifest 都变一行,
    async 每跑必留一个 M 脏文件(sync 每 ~30min 一次 churn 更密)。表内「生成时间」列本来就只用日期, 不受影响。

    ⚠ 仓库里 docs/large-json-backup-manifest.md 那版(=恢复侧分支手写版)是「厚表头 + 空表骨架」,
    而生成器写的是「薄表头 + 带 sha256 的完整表」——两者暂时不等是 async 长期 `skip_oversize`
    未 commit 造成的滞后, 恢复正常 commit 后生成器版会自然入库, 不需要手工改那份 md。
    """
    import datetime as _dt
    out = ROOT / "docs" / "large-json-backup-manifest.md"
    now = _dt.datetime.now().strftime("%Y-%m-%d")
    tier = _tier_of_today(today_str)
    lines = [
        "# large-json 备份清单(large-json-backup-manifest)",
        "",
        f"> 由 `scripts/upload_r2.py upload-large-json` 自动生成({now}), 勿手改。",
        "",
        "## 机制一句话",
        "",
        "staticdata 备份仓库 7 个 >20MB JSON(共 ~319MB)已移出 git 跟踪(备份天天 `skip_oversize`",
        "不 commit 的根因), 改走 R2 私有桶 `signal-backup` 的 `large-json/` 前缀版本化快照。",
        "",
        "- key 格式: `large-json/<YYYY-MM-DD>/<相对 data/ 的路径>.gz`",
        "  - 例: `large-json/2026-09-25/signal_kelly_trades.json.gz`",
        "  - 例: `large-json/2026-09-25/signal_kelly_trades_parts/t2025.json.gz`",
        "- 保留档位: 日档 14 天 + 周档(周日那份) 8 周 + 月档(每月 1 号那份) 12 个月",
        "- 恢复: `bash scripts/restore-large-json.sh <文件名|--list|--date YYYY-MM-DD|--all> [--target <dir>]`",
        "  还原时先下同目录 `.tmp` 再原子覆盖, 覆盖前旧文件备份为 `<文件>.bak-<时间戳>`; 本清单",
        "  有 sha256 记录的会比对, 不匹配即中止(不改原文件)。默认还原目标 = 生产数据目录",
        "  `trade-data/data/`(`STATICDATA_REPO`/`--target` 可覆盖, 非默认目录会打醒目警告)。",
        "  (详见 `docs/backup-restore.md` 第八节)。",
        "- 相关脚本: `scripts/upload_r2.py`(上传) / `scripts/restore-large-json.sh`(恢复入口)。",
        "",
        "## 快照明细",
        "",
        "| 相对 data/ 路径 | 完整字节 | sha256 | 最新 R2 key | 保留档位 | 生成时间 |",
        "|---|---|---|---|---|---|",
    ]
    for relpath, size, sha, key in sorted(rows):
        lines.append(f"| {relpath} | {size} | {sha} | `{key}` | {tier} | {today_str} |")
    lines.append("")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".md.tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    os.replace(tmp, out)
    print(f"✓ manifest 已重写: {out}({len(rows)} 行)")


def cmd_upload_large_json():
    """大 JSON(staticdata 备份 git 排除对象)按日 gzip 推 R2 私有桶 signal-backup large-json/ 前缀 + 分层滚动保留。

    背景(2026-09-25): staticdata 备份 git 仓库 7 个大 JSON(>20MB, 共~320MB)天天变天天进 delta,
    .git 膨胀到 3.3G, 9-25 首跑撞「变更总字节 >300MB」积压阈值跳过 commit。本命令 = 排除对象异地备份:
      - 对象清单 = scripts/large_json_excludes.py --print(.gitignore 受管区块单一源; 迁移后仍持续备份,
        git rm --cached 只移出 git 不动磁盘/R2)。
      - key 格式 = large-json/<YYYY-MM-DD>/<相对 data/ 的路径>.gz(冻结接口, 主控定)。
      - 幂等: s3_head 比对 ETag(单 PUT ETag=内容 md5; gzip.compress 必须显式 mtime=0——
        Python 3.11 默认 mtime=当前时间, 同内容每次 gzip 字节不同 ETag 永不相等, 幂等失效,
        2026-09-25 实测发现修复), 内容没变跳过 PUT 不重复上传。
      - 滚动保留 = _prune_large_json(日14天 + 周档周日那份8周 + 月档每月1号那份12月)。
      - 跑完自动重写 docs/large-json-backup-manifest.md(相对路径/完整字节/sha256/最新key/档位/生成时间)。
      - dry-run(2026-09-26 F1): `upload-large-json --dry-run`(或 async 侧 STATICDATA_BACKUP_SKIP_R2_UPLOAD=1)
        只打印将上传清单 + 将做的事,**不 PUT / 不 DELETE / 不重写 manifest / 不跑 _prune_large_json,
        且全程不接触 R2**(纯本地计算)——测试隔离钩子, 防集成测试污染生产桶(2026-09-26 实际事故)。
    """
    import gzip
    import hashlib
    import subprocess
    import datetime as _dt
    dry_run = _DRY_RUN
    repo = _large_json_staticdata_repo()
    excludes = ROOT / "scripts" / "large_json_excludes.py"
    r = subprocess.run([sys.executable, str(excludes), "--print", "--repo", str(repo)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"✗ large_json_excludes.py --print 失败: {r.stderr[:500]}")
    entries = []  # (relpath 相对 data/, bytes)
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) == 2 and parts[1].isdigit():
            entries.append((parts[0], int(parts[1])))
    if not entries:
        print("✓ 无大 JSON 需备份(large-json 清单为空)")
        return
    today = _dt.datetime.now().strftime("%Y-%m-%d")
    ok = 0
    manifest_rows = []
    for relpath, size in sorted(entries):
        src = repo / "data" / relpath
        if not src.is_file():
            print(f"⚠ 跳过(源不存在): data/{relpath}")
            continue
        raw = src.read_bytes()
        payload = gzip.compress(raw, compresslevel=6, mtime=0)  # mtime=0 固定, 同内容同字节(幂等 ETag 前提)
        key = f"large-json/{today}/{relpath}.gz"
        local_md5 = hashlib.md5(payload).hexdigest()
        if dry_run:
            # F1 dry-run: 只打印将上传清单, 不 PUT / 不 HEAD, 全程零 R2 接触。
            print(f"[dry-run] 将上传 {relpath} ({size // 1024 // 1024}MB -> "
                  f"{len(payload) // 1024 // 1024}MB gzip, md5={local_md5[:10]}…) -> {BACKUP_BUCKET}/{key}")
            manifest_rows.append((relpath, size, hashlib.sha256(raw).hexdigest(), key))
            ok += 1
            continue
        st, etag = s3_head(key, bucket=BACKUP_BUCKET)
        if st == 200 and etag is not None and etag.strip('"') == local_md5:
            print(f"✓ 已存在且内容未变, 跳过 PUT: {BACKUP_BUCKET}/{key}")
            ok += 1
            # R2 已有同内容副本 = 真实成功, 进 manifest
            manifest_rows.append((relpath, size, hashlib.sha256(raw).hexdigest(), key))
        else:
            status, data = s3_request("PUT", key, payload, bucket=BACKUP_BUCKET, content_type="application/gzip")
            if status == 200:
                ok += 1
                print(f"✓ {relpath} ({size // 1024 // 1024}MB -> {len(payload) // 1024 // 1024}MB gzip)"
                      f" -> {BACKUP_BUCKET}/{key}")
                manifest_rows.append((relpath, size, hashlib.sha256(raw).hexdigest(), key))
            else:
                # 上传失败的行不得进 manifest(manifest 只能反映真实成功上传, 防机检误判已备份);
                # 失败详情走 stderr, 最终 ok != len(entries) 保持非 0 退出。
                print(f"✗ {relpath} status={status} {data.decode('utf-8', errors='replace')[:300]}",
                      file=sys.stderr)
    if dry_run:
        # F1 dry-run 收尾: 只打印「将做的事」, 不真跑 prune / 不重写 manifest。
        print("[dry-run] 将运行 _prune_large_json(日14天 + 周周日8周 + 月1号12月滚动保留)")
        print(f"[dry-run] 将重写 docs/large-json-backup-manifest.md({len(manifest_rows)} 行)")
        print(f"[dry-run] large-json 计划上传 {ok}/{len(entries)} -> {BACKUP_BUCKET}/large-json/{today}/ (私有桶, 未执行)")
        return
    _prune_large_json()
    _write_large_json_manifest(manifest_rows, today)
    print(f"large-json 上传 {ok}/{len(entries)} -> {BACKUP_BUCKET}/large-json/{today}/ (私有桶)")
    if ok != len(entries):
        sys.exit(1)


# ---- verify-r2 通道登记表(2026-09-15, 层3 防漏传对账) ----
# 每通道: label / local_dir(可调用, 镜像 cmd_upload_* 的 ROOT 回退) / patterns / r2_prefix /
# state_name(读 changed 字段做平日增量对账) / exclude_fn(镜像各通道口径) / sample(平日抽样上限,
# None=全量; fund-nav 平日抽样 100, 周日全量)。
def _resolve_lab_dir():
    lab = STATIC_DIR / "data/lab"
    if not lab.exists() or not any(lab.glob("*.json")):
        lab = ROOT / "static-site" / "data" / "lab"
    return lab


def _resolve_trade_sim_html_dir():
    ts_dir = STATIC_DIR
    if not any(f.exists() for f in ts_dir.glob("trade_sim_*.html")):
        ts_dir = ROOT / "static-site"
    return ts_dir


def _resolve_trade_sim_json_dir():
    ts_dir = STATIC_DIR / "data/trade_sim"
    if not ts_dir.exists() or not any(ts_dir.glob("*.json")):
        ts_dir = ROOT / "static-site" / "data" / "trade_sim"
    return ts_dir


_R2_CHANNELS = [
    {"label": "lab", "local_dir": _resolve_lab_dir, "patterns": ["*.json"], "r2_prefix": "lab",
     "state_name": ".r2_lab_state.json"},
    {"label": "trade-sim", "local_dir": _resolve_trade_sim_html_dir, "patterns": ["trade_sim_*.html"],
     "r2_prefix": "trade_sim", "state_name": ".r2_trade_sim_html_state.json"},
    {"label": "trade-sim-json", "local_dir": _resolve_trade_sim_json_dir, "patterns": ["*.json"],
     "r2_prefix": "trade_sim_data", "state_name": ".r2_trade_sim_json_state.json"},
    {"label": "index", "local_dir": lambda: STATIC_DIR / "data/index", "patterns": ["*.json"],
     "r2_prefix": "index", "state_name": ".r2_index_state.json"},
    {"label": "etf-hist", "local_dir": lambda: STATIC_DIR / "data/etf", "patterns": ["*.json"],
     "r2_prefix": "etf", "state_name": ".r2_etf_hist_state.json"},
    {"label": "fund-nav", "local_dir": lambda: STATIC_DIR / "data/nav_bucket", "patterns": ["*.json"],
     "r2_prefix": "nav_bucket", "state_name": ".r2_fund_nav_state.json", "sample": 100},
    {"label": "accum-nav", "local_dir": lambda: STATIC_DIR / "data/accum_nav", "patterns": ["*.json"],
     "r2_prefix": "accum_nav", "state_name": ".r2_accum_nav_state.json"},
    {"label": "industry", "local_dir": lambda: STATIC_DIR / "data",
     "patterns": ["industry-all-indices/*", "industry-5y-indices/*", "industry-3y-indices/*", "industry-*.json"],
     "r2_prefix": "industry", "state_name": ".r2_industry_state.json"},
    {"label": "public-fund", "local_dir": lambda: STATIC_DIR / "data", "patterns": ["public_fund*.json"],
     "r2_prefix": "public_fund", "state_name": ".r2_public_fund_state.json"},
    {"label": "etf-score", "local_dir": lambda: STATIC_DIR / "data", "patterns": ["etf_score_list_*.json"],
     "r2_prefix": "data", "state_name": ".r2_etf_score_state.json"},
    {"label": "kelly-parts", "local_dir": lambda: STATIC_DIR / "data/signal_kelly_trades_parts", "patterns": ["*.json"],
     "r2_prefix": "data/signal_kelly_trades_parts", "state_name": ".r2_kelly_parts_state.json"},
    {"label": "kelly-parts-sdc", "local_dir": lambda: STATIC_DIR / "data/signal_kelly_trades_sdc_parts", "patterns": ["*.json"],
     "r2_prefix": "data/signal_kelly_trades_sdc_parts", "state_name": ".r2_kelly_sdc_state.json"},
    {"label": "kelly-snapshots", "local_dir": lambda: STATIC_DIR / "data/signal_kelly_snapshots", "patterns": ["*.json"],
     "r2_prefix": "data/signal_kelly_snapshots", "state_name": ".r2_kelly_snapshots_state.json"},
    {"label": "data-large", "local_dir": lambda: STATIC_DIR / "data", "patterns": ["*.json"],
     "r2_prefix": "data", "state_name": ".r2_data_large_state.json",
     "exclude_fn": lambda f: not _is_data_large_file(f)},
    {"label": "all-data", "local_dir": lambda: STATIC_DIR / "data", "patterns": ["*.json"],
     "r2_prefix": "data", "state_name": ".r2_all_data_state.json", "exclude_fn": _is_all_data_excluded},
]


def _assert_no_double_upload(data_dir):
    """机检断言 all-data 文件集 ∩ data-large 文件集 = ∅(设计文档 §4 风险8 / §7 验收②)。"""
    large = set()
    small = set()
    for f in sorted(data_dir.glob("*.json")):
        if f.exists():
            if _is_data_large_file(f):
                large.add(f.name)
            if not _is_all_data_excluded(f):
                small.add(f.name)
    overlap = large & small
    if overlap:
        print(f"[verify-r2] ✗ 双传互斥断言 FAIL: {sorted(overlap)} 同时落入 data-large 与 all-data")
        return False
    print(f"[verify-r2] ✓ 双传互斥断言 PASS(data-large {len(large)} 文件 ∩ all-data {len(small)} 文件 = ∅)")
    return True


def _uniform_sample(files, n):
    """全量均匀抽样(2026-09-23 ②): 不用 mtime 取最新 —— 最新恰好与当日 changed 强相关,
    存量缺口(状态已记新指纹但 R2 旧/缺, 且不在最近 changed 里)按 mtime 永远查不到。
    files 已排序; 按均匀间隔取 n 个 + 末尾一个(防尾部遗漏), 保证全池范围覆盖近似均匀。
    文件数 < n 时全收。"""
    m = len(files)
    if m <= n:
        return list(files)
    k = m / float(n)
    idx = {int(i * k) for i in range(n)}
    idx.add(m - 1)
    return [files[i] for i in sorted(idx)]


def cmd_verify_r2():
    """verify-r2 周期全量对账(层3 防漏传机检, 设计文档 §3.4)。

    周日(weekday==6)全量对账: 每通道 HEAD 每个本地文件的 R2 key, ETag != 本地整文件 md5
    或 404(本地有 R2 无)→ 自动补传(_upload_glob only_files + 层2 ETag 对账)。R2 有本地无
    → 不删(残留无害; list-type-2 单页 1000 上限且残留无害, 不做 LIST 枚举孤儿 key)。
    平日只对账当日增量通道的 key 清单(读状态文件 changed 字段, 秒级; fund-nav 抽样 100)。
    补传失败 → exit 1 → deploy.sh R2_FAIL 收尾 notify(层4 告警链)。
    另含双传互斥断言(data-large ∩ all-data = ∅)。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    today_weekday = datetime.date.today().weekday()
    full = today_weekday == 6
    print(f"[verify-r2] 模式={'周日全量对账' if full else '平日增量对账'}")

    if not _assert_no_double_upload(STATIC_DIR / "data"):
        print("[verify-r2] ✗ 双传互斥断言 FAIL → 中止(exit 1), 走 deploy.sh R2_FAIL 收尾 notify")
        sys.exit(1)

    repaired_total = 0
    repair_failed = []

    for ch in _R2_CHANNELS:
        label = ch["label"]
        local_dir = ch["local_dir"]()
        r2_prefix = ch["r2_prefix"]
        if not local_dir.exists():
            print(f"[verify-r2] {label}: 本地目录不存在 {local_dir}, 跳过")
            continue
        # 收集本地文件(glob + exclude_fn + broken 过滤, 与引擎同口径)
        files = []
        for pat in ch["patterns"]:
            files.extend(local_dir.glob(pat))
        files = sorted(set(files))
        if ch.get("exclude_fn"):
            files = [f for f in files if not ch["exclude_fn"](f)]
        files = [f for f in files if f.exists()]
        if not files:
            continue

        if full:
            to_check = files
        else:
            # 平日: 当日增量 key(状态文件 changed 字段) + 全池均匀小抽样兜底。
            # 2026-09-23 ②根治: 单一 changed 盲区查不到「状态假成功」存量缺口(状态文件已记录
            # 新指纹但 R2 实际旧/缺, 该 key 不在 recent changed 里 → never 对账直到周日)。
            # 全池均匀取 ~20 个 key(不限 mtime), 让旧 key 也被覆盖; sample 上限口径保留。
            state_path = STATIC_DIR.parent / "data" / ch["state_name"]
            changed_rels = set()
            if state_path.exists():
                try:
                    with open(state_path, "r", encoding="utf-8") as f:
                        st = json.load(f)
                    changed_rels = set(st.get("changed") or [])
                except (OSError, ValueError):
                    changed_rels = set()
            to_check = [f for f in files if str(f.relative_to(local_dir)) in changed_rels]
            sample_n = 20
            sampled = _uniform_sample(files, sample_n)
            if sampled:
                print(f"[verify-r2] {label}: 平日增量 {len(to_check)} 个 + 全池抽样 {len(sampled)} 个")
            to_check = sorted(set(to_check) | set(sampled))
            if ch.get("sample") and len(to_check) > ch["sample"]:
                to_check = to_check[:ch["sample"]]
        if not to_check:
            print(f"[verify-r2] {label}: 无需对账 key, 跳过")
            continue

        def _check(f):
            rel = str(f.relative_to(local_dir))
            key = f"{r2_prefix}/{rel}"
            try:
                local_md5 = _file_md5(f)
                local_size = f.stat().st_size
            except OSError:
                return f, True  # 本地读失败, 视为一致跳过(不判失败)
            # keep_alive 连接复用(2026-09-21 R2 根治): 全量对账 ~3万 HEAD 每线程复用一个连接,
            # 省跨境握手(~1s/次)。multipart 大文件(>100MB)ETag=分片组合 non-md5, 改「存在 +
            # Content-Length==本地大小」判定(ETag 对账仅适用单 PUT 小文件)。
            if local_size > _MULTIPART_THRESHOLD:
                _st, _etag, clen = s3_head(key, keep_alive=True, with_len=True)
                ok = (_st == 200 and clen is not None and int(clen) == local_size)
            else:
                _st, etag = s3_head(key, keep_alive=True)
                ok = etag is not None and etag.strip('"') == local_md5
            return f, ok

        mismatches = []
        ch_checked = 0
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(_check, f) for f in to_check]
            for fut in as_completed(futures):
                f, ok = fut.result()
                ch_checked += 1
                if not ok:
                    mismatches.append(f)
        if mismatches:
            print(f"[verify-r2] {label}: 发现 {len(mismatches)} 个不一致/缺失 key(共查 {ch_checked}), 自动补传")
            ok, total, failed_rels, _ = _upload_glob(
                local_dir, ch["patterns"], r2_prefix, only_files=mismatches, verify_etag=True)
            repaired_total += ok
            if ok != total:
                repair_failed.extend(f"{label}/{r}" for r in failed_rels)
        else:
            print(f"[verify-r2] {label}: 共查 {ch_checked} key 全部一致 ✓")

    if repair_failed:
        print(f"FAILED_FILES: {', '.join(repair_failed)}")
        sys.exit(1)
    print(f"[verify-r2] ✓ 对账完成, 自动补传 {repaired_total} 个")


_LIGHT_CHECK_SAMPLE = 20  # 轻量对账每通道抽查文件数(decline 快速降噪, 不全量扫描)


def _light_check_single_file(r2_key, local_path, tag):
    """单个本地文件 ↔ R2 key 轻量比对。multipart 大文件按「存在+Content-Length==本地大小」,
    否则按 ETag==本地 md5。返回 (ok, why)。"""
    try:
        sz = local_path.stat().st_size
        md5 = hashlib.md5(local_path.read_bytes()).hexdigest()
    except OSError as e:
        return False, f"{tag} 本地读失败({type(e).__name__}: {e})"
    if sz > _MULTIPART_THRESHOLD:
        _st, _etag, clen = s3_head(r2_key, keep_alive=True, with_len=True)
        ok = (_st == 200 and clen is not None and int(clen) == sz)
        return ok, f"{tag} status={_st} clen={clen} local={sz}"
    _st, etag = s3_head(r2_key, keep_alive=True)
    ok = (_st == 200 and etag is not None and etag.strip('"') == md5)
    return ok, f"{tag} status={_st} etag={etag} md5={md5}"


def _light_check_channel(ch, label):
    """单通道轻量对账: 取本地最新 _LIGHT_CHECK_SAMPLE 个文件, 逐个 HEAD 抽查 R2 一致性。"""
    local_dir = ch["local_dir"]()
    if not local_dir.exists():
        return True, "本地目录不存在, 跳过"
    files = []
    for pat in ch["patterns"]:
        files.extend(local_dir.glob(pat))
    files = sorted(set(files))
    if ch.get("exclude_fn"):
        files = [f for f in files if not ch["exclude_fn"](f)]
    files = [f for f in files if f.exists()]
    if not files:
        return True, "无本地文件, 跳过"
    # 全池均匀抽样(2026-09-23 ②): 不再只抽「最新 mtime」—— 最新文件恰好是当日增量相关,
    # 查不到「状态假成功」存量缺口(状态已记新指纹但 R2 旧/缺, 且该 key 不在 recent changed)。
    # 均匀抽全池样本让旧 key 也被覆盖。
    sample = _uniform_sample(files, _LIGHT_CHECK_SAMPLE)
    bad = []
    for f in sample:
        rel = str(f.relative_to(local_dir))
        key = f"{ch['r2_prefix']}/{rel}"
        ok, why = _light_check_single_file(key, f, f"{label}/{rel}")
        if not ok:
            bad.append(why)
    if bad:
        return False, "; ".join(bad[:5])
    return True, f"抽查 {len(sample)} 个最新文件全部一致"


def cmd_verify_channels(desc_list):
    """deploy.sh 收尾降噪: 对 R2_FAIL 通道做轻量对账(2026-09-21 R2 根治)。

    告警噪音真相=看门狗超时 kill(数据已传完), 非上传失败。对失败通道抽查最近上传的
    关键文件 R2 HEAD(ETag/Content-Length vs 本地 md5/size), 全部一致 → exit 0
    (deploy.sh 改普通日志不告警); 任一缺失/不一致 → exit 1(照常告警, 保住「真缺文件」场景)。
    通道名 = deploy.sh R2_FAIL 里的 desc: "upload-<label>" 映射 _R2_CHANNELS;
    "upload-feed" 抽查 data/feed.xml; "verify-r2" 本身即对账命令超时, 不做降级(保守保留告警)。
    """
    if not desc_list:
        sys.exit(1)
    # D-1 返修(2026-09-21 reviewer): verify-r2 失败意味着「层3 对账未完成」, 缺口无法用轻量抽查兜底。
    # 只要 desc_list 含 verify-r2 就整体 exit 1 保守保留告警——即使同批有 upload-* 通道轻量对账通过,
    # 也不允许用它把 verify-r2 未完成的对账缺口静默。(原实现把 verify-r2 当未知通道 continue,
    # 会走到 checked_any/bad 判定, 若同批 upload 通道全通过 → exit 0 → deploy.sh 抑制告警 → 静默缺口。)
    if "verify-r2" in desc_list:
        sys.exit(1)
    bad = []
    checked_any = False
    for desc in desc_list:
        if desc == "upload-feed":
            ok, why = _light_check_single_file("data/feed.xml", STATIC_DIR / "data" / "feed.xml", "feed.xml")
            checked_any = True
            if not ok:
                bad.append(why)
            continue
        if not desc.startswith("upload-"):
            continue  # verify-r2/purge-low-freq 等不下探(保守保留告警)
        label = desc[len("upload-"):]
        ch = next((c for c in _R2_CHANNELS if c["label"] == label), None)
        if ch is None:
            continue
        ok, why = _light_check_channel(ch, label)
        checked_any = True
        if not ok:
            bad.append(why)
    if not checked_any:
        # 全部通道都跳过(如仅 verify-r2), 保守保留告警, 不降级。
        sys.exit(1)
    if bad:
        print(f"LIGHT_CHECK_FAILED: {'; '.join(bad)}")
        sys.exit(1)
    print("轻量对账通过: 失败通道 R2 数据完整, 降级为普通日志不告警")
    sys.exit(0)


# --skip-if-locked 拿不到锁时的哨兵返回值(区别于正常持锁 fd 与 None=锁不可用)。
_SKIP_R2_LOCKED = object()


def _acquire_r2_upload_lock(timeout=None, skip_if_locked=False):
    """R2 上传统一进程互斥锁(2026-09-23 ④: 直传通道无 deploy.lock → 三路并发抢带宽)。

    deploy 主链的 R2 段在 deploy.lock 内, 但 etf_national_team_backfill.sh:112(upload-etf-hist)、
    turnover_backfill.sh:143/146(upload-intraday/upload-data-large)等直调 upload_r2.py 不持锁,
    可与 deploy 主链 R2 段并发 → 跨境带宽互抢, 单通道变慢被看门狗 kill(9-23 事故诱因之一)。
    本锁收敛到 upload_r2.py 入口: 一切调用方(deploy/backfill/manual)天然互斥。

    默认行为 = 排队(绝不跳过): 拿不到锁就阻塞轮询(任务④硬约束), flock 由内核持有、
    持锁进程退出/被杀自动释放, 不会死持。timeout 只是极端兜底护栏: 超时 → stderr 提示
    + exit 1(fail-closed, 显式失败走调用方既有告警链, 不静默跳过、不造静默缺口)。
    正常等待时间 = 前一个上传通道实际耗时(有界, 见 deploy.sh run_r2_upload ③估算看门狗)。

    timeout 缺省读 env R2_UPLOAD_LOCK_TIMEOUT(默认 7300), 只约束「排队等锁」时长上限。
    与 deploy.sh run_r2_upload 看门狗的关系: 看门狗上限按通道显式/按字节量估算, 无单一统一值
    (大部分通道 900s, trade-sim-json 1800, verify-r2 7200, 估算通道上限 7200; fund-nav 已拆出
    deploy 主链改 fund_nav_upload_async.sh 异步上传(2026-09-23 P1 主链有界化), 不再受 deploy.sh
    看门狗约束——异步独立进程 + checkpoint 断点续传, 由 async 脚本 notify 告警兜底)。
    等锁方实际等待 = 持锁进程实际持有时间(持锁方 R2 段完成才释放锁; deploy 持锁时长受其
    看门狗 kill 约束, 实测远小于对应上限)。默认 7300 对任何通道都给足余量, 保证等锁方总能
    等得到锁、不因等锁超时误伤 deploy 正常长通道; 真死锁(持锁方 hang)则由本
    timeout 兜底 fail-closed(exit 1, 走调用方既有告警链), 不会 fail-open 无锁上传破互斥保证,
    也不会静默留缺口。

    skip_if_locked(opt-in, 2026-09-24 硬化 P1-A): 高频/下轮可重试通道专用。拿不到锁时
    立即返回 _SKIP_R2_LOCKED 哨兵(不排队), 由 __main__ 统一打印可 grep 的 SKIPPED_LOCKED
    行 + exit 0(不触发调用方 `|| 告警邮件` 分支)。跳过 = 本轮不传, 下一轮 10min 后自然重试,
    对 intraday_snapshot/overfit_monitor/fetch_news 这类高频或兜底链通道是安全的;
    对 deploy.sh 日链 data-large/kelly-parts 等「跳过就留数据缺口」的低频通道**不适用**(它们
    不带该 flag, 保持排队语义不变)。

    list/delete/download-db/clean-data-backup 等只读/低频调试命令不走本锁(避免排查时被上传阻塞);
    upload(单文件 <100KB)轻量命令豁免。upload-db/upload-claude-backup/upload-decommissioned
    等私有桶备份也持锁(与主数据上传互斥, 防抢带宽)。
    """
    if timeout is None:
        try:
            timeout = int(os.environ.get("R2_UPLOAD_LOCK_TIMEOUT", "7300"))
        except ValueError:
            timeout = 7300
    lock_path = Path(os.environ.get("R2_UPLOAD_LOCK", "/tmp/trade_r2_upload.lock"))
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    except OSError as e:
        print(f"⚠ 无法打开 R2 上传锁 {lock_path}({e}), 不持锁继续(并发风险自知)", file=sys.stderr)
        return None
    deadline = time.time() + timeout
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            if skip_if_locked:
                os.close(fd)
                print(
                    "SKIPPED_LOCKED: R2 上传锁被占用, 跳过本轮上传(--skip-if-locked, 下轮重试)",
                    file=sys.stderr,
                )
                return _SKIP_R2_LOCKED
            if time.time() >= deadline:
                print(
                    f"✗ R2 上传锁 {lock_path} 排队等待超 {timeout}s 仍被占用, 拒绝本次上传"
                    f"(fail-closed, 防与持锁进程并发抢带宽; 持锁进程退出自动释放锁, 若长期占用"
                    f"请人工 `lsof {lock_path}` 排查持锁进程, 等其结束或等 timeout 后重试)",
                    file=sys.stderr,
                )
                sys.exit(1)
            time.sleep(2)


if __name__ == "__main__":
    # --dry-run 全局标志(验收自测): 引擎只打印「将传 N/M」不 PUT(不写状态, 不 purgate)。
    if "--dry-run" in sys.argv:
        _DRY_RUN = True
        sys.argv = [a for a in sys.argv if a != "--dry-run"]
    # --skip-if-locked 全局标志(2026-09-24 硬化 P1-A): 高频/下轮可重试通道 opt-in——
    # 拿不到锁立即打印 SKIPPED_LOCKED 标记行 + exit 0(不排队, 不触发调用方 || 告警分支)。
    # 默认不带该 flag = 排队语义不变(deploy.sh 日链低频/漏传留缺口通道不受影响)。
    if "--skip-if-locked" in sys.argv:
        _SKIP_IF_LOCKED = True
        sys.argv = [a for a in sys.argv if a != "--skip-if-locked"]
    else:
        _SKIP_IF_LOCKED = False
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    guard_repo_default(cmd)                     # #75 分级闸:REPO 缺省且非白名单命令 → exit 3
    # ④ R2 上传统一互斥锁: 只读/单文件小命令豁免, 其余 upload_*/verify_*/purge_* 持锁排队。
    if cmd and cmd not in {"list", "delete", "download-db", "clean-data-backup", "upload"}:
        _lock = _acquire_r2_upload_lock(skip_if_locked=_SKIP_IF_LOCKED)
        if _lock is _SKIP_R2_LOCKED:
            sys.exit(0)   # SKIPPED_LOCKED 已在 _acquire 内打印到 stderr; 退出码 0 不触发告警邮件
    if cmd == "list":
        # list [prefix] [bucket]   bucket 默认 signal-data;查私有桶(如 signal-backup)时显式传
        prefix = sys.argv[2] if len(sys.argv) > 2 else ""
        bucket = sys.argv[3] if len(sys.argv) > 3 else None
        cmd_list(prefix, bucket)
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
        # upload-fund-nav  基金全史净值 nav_bucket/{xx}.json(256桶) -> R2 nav_bucket/ 前缀(#11, 2026-08-25)
        cmd_upload_fund_nav()
    elif cmd == "upload-accum-nav":
        # upload-accum-nav  ETF 全史累计净值 per-ETF 拆分 accum_nav/{code}.json -> R2 accum_nav/ 前缀(2026-09-17 懒加载)
        cmd_upload_accum_nav()
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
    elif cmd == "upload-kelly-parts-sdc":
        # #91(2026-09-06) 当日收盘对比档分片(signal_kelly_trades_sdc_parts/, 凯利页「买入口径」切换用)
        cmd_upload_kelly_parts_sdc()
    elif cmd == "upload-kelly-snapshots":
        # signal_kelly_snapshots/ 每日快照+演进 index(lab 凯利区「演进」入口)
        cmd_upload_kelly_snapshots()
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
    elif cmd == "verify-r2":
        # verify-r2  周期全量对账(层3 防漏传机检): 周日全量对账+平日增量对账, deploy.sh 每日调用
        cmd_verify_r2()
    elif cmd == "verify-channels":
        # verify-channels <desc...>  deploy.sh 收尾降噪轻量对账(改动1, 2026-09-21 R2 根治):
        # 对 R2_FAIL 失败通道抽查关键文件 R2 HEAD, 数据完整 exit 0(改普通日志不告警),
        # 真缺文件 exit 1(照常告警)。
        cmd_verify_channels(sys.argv[2:])
    elif cmd == "upload-db":
        cmd_upload_db()
    elif cmd == "upload-large-json":
        # upload-large-json [--dry-run]  staticdata 备份 git 排除的大 JSON -> 私有桶 large-json/<日期>/<路径>.gz
        # (2026-09-25, 排除对象清单来源 large_json_excludes.py --print)
        # --dry-run(2026-09-26 F1): 走全局 _DRY_RUN 标志, 只打印清单计划动作, 零 R2 接触。
        cmd_upload_large_json()
    elif cmd == "upload-claude-backup":
        # upload-claude-backup [local_path]  Claude 自我备份 tar.gz -> signal-backup/claude-backup/
        local_path = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_upload_claude_backup(local_path)
    elif cmd == "upload-decommissioned":
        # upload-decommissioned <local_path> <key_name>  退役归档 -> signal-backup/decommissioned/
        local = sys.argv[2]
        key_name = sys.argv[3]
        cmd_upload_decommissioned(local, key_name)
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
            "upload-fund-nav|upload-accum-nav|upload-data-large|upload-kelly-parts|upload-kelly-parts-sdc|upload-db|upload-large-json|"
            "upload <local> <key>|delete <key> [bucket]|clean-data-backup|"
            "upload-claude-backup [path]|upload-decommissioned <local> <key_name>|"
            "upload-all-data|upload-intraday|purge-low-freq|verify-r2|verify-channels <desc...>]"
        )
