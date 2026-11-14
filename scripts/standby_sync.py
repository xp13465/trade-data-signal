#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""standby_sync.py — 备用机每日凌晨同步云端可恢复集合(D 批, 2026-11-14)。

依据: /tmp/codex-reports/claude-cloud-primary-local-backup-20261114-execution-plan.md
工作包三「每天凌晨同步至本机」+ /tmp/task-standby-sync-impl-20261114.md。
盘点缺口背景见 /tmp/backup-inventory-20261114.md(冻结表/游标/状态 JSON 的成套捕获是
C 批 feat/standby-capture-20261114 的活; 本工具只负责「读取可信 manifest → 核恢复
范围与空间 → 下载 staging → 校验 → 固化 → 原子切 latest_verified → 写状态」,
不生产集合、不接管、不回切)。

流程(严格按方案):
    读可信 manifest → 核恢复范围与空间 → 下载 staging → 校验全部文件
    → 隔离恢复检查(只读) → 固化版本目录 → 原子切 latest_verified → 写结果记录

== manifest 契约(schema_version=1, 防御式解析) ==
C 批尚在开发、契约未合入, 本文件先按任务书字段(文件清单/来源/sha256/业务日期/
生成时间/归档位置/缺项/校验结果)定义**宽容解析**契约; C 批合入后字段名如有出入
只需改 normalize_manifest 单一入口, 不动校验/固化/保留逻辑:

    {
      "schema_version": 1,
      "complete": true,                 # 缺项必须如实 false, 禁缩表凑成功
      "business_date": "2026-11-13",    # 集合共同业务截止点(YYYY-MM-DD)
      "generated_at": "2026-11-13T22:24:05+08:00",
      "source_run": "eaae26111d644...", # 来源轮次(backup run / proof id, 可空)
      "archive_hint": "backup/",       # 归档位置提示(可空)
      "files": [
        {
          "key": "backup/sentiment_20261113.db.gz",  # 源内相对路径(local 源 =
            源目录下相对路径; r2 源 = 桶内 key)
          "role": "db",                 # db | freeze | cursor | state | sidecar
          "name": "sentiment.db",       # 人类可读名(可空)
          "size": 56278590,             # 压缩态字节数(必须)
          "sha256_gz": "...",           # 下载字节 sha256(必须)
          "sha256_uncompressed": "...", # .gz 解压后 sha256(gz 文件必须)
          "business_date": "2026-11-13",# 对象级业务日期(可空; 与集合级不一致=拒)
          "tables": {"score_daily": 38856},   # 关键表→期望最少行数(可空)
          "probe": {"table": "score_daily", "col": "date", "min": "2026-11-12"}
                                         # 业务日期探针: MAX(col) 必须 >= min(可空)
        }
      ]
    }

== 通知四元组声明(alert-checker-registry 口径, implementer skill §0 清单项) ==
本脚本 4 个事件通道全部经 scripts/notify.py CLI 发出, 四元组一致:
  默认 tier = critical(--severe) / dedup window = 604800s(7 天) /
  聚合域 = backup / 首报策略 = 首报必达
  - standby_sync_corrupt_set          新集合损坏(坏 hash/缺 sidecar/SQLite 损坏/错业务日期)
  - standby_sync_window_fail           超窗口仍失败(尝试/共享总预算耗尽)
  - standby_sync_stale_recovery_point 最新可恢复点过期(默认 >2 天)
  - standby_sync_space_insufficient    空间不足(拒绝下载)
dedup window 取 7 天: 备用机同事件通常每日最多触发一次, 逐日重报=「按日期刷屏」
(方案通知规则明令禁止); 7 天后仍未恢复重报一次, 兼顾不无限沉默。
成功/无变化/窗口内重试成功 ⇒ 完全静默(只写状态, 零外发)。
故障恢复通知(执行方案第 120 行/任务书第 7 项): 故障事件**真发出过**后记入
``state["pending_recovery"]``; 真正恢复时对每个已通知事件发一次恢复通知
(事件身份 ``<event_key>_recovered``, 同 7 天去重窗, notify.py 身份/去重沿用),
发出成功即清账; **从未成功通知过的故障不发恢复**(避免「没收到告警却收到恢复」)。
dry-run 既不写状态也不发任何事件(含失败分支与恢复通知, README 承诺)。
测试全部打桩(monkeypatch emit_event, §18 L48 禁真发)。

== 空间估算口径 ==
check_space 按「staging gz 合计 + 最大对象解压后大小」估峰值; 解压后大小优先取
manifest 的 size_uncompressed, 缺省按实测解压比 DEFAULT_UNCOMPRESSED_RATIO=3.6
(盘点报告 3.61GiB 原始 / 0.996GiB gzip)估算, 保证 --min-free-gb 不被击穿。
下载/解压/写盘中途 ENOSPC 一律归 space_insufficient(不误报 window_fail)。

== 幂等/断点要点 ==
- 同一归档(同一 manifest 内容)⇒ 同一 version_id, 不产生冲突版本; 已固化已验的
  版本幂等复用(只对齐 latest_verified, 不重下载不重验)。
- 断点续传=对象粒度: staging 内 size+sha256 与 manifest 一致的对象直接复用;
  不完整/坏对象整对象重下(manifest 锚定的是整对象 hash, 不做字节级 Range 续传)。
- staging 残留只清自己登记命名的 work/staging-*。
- flock(跨进程)单实例; 每窗口最多 --max-attempts 次尝试 + 指数退避 +
  共享总截止 --deadline-minutes; 不跨窗口重试(每日 launchd 新窗, 单实例防重叠)。

== 退出码 ==
0 成功/无变化/only-if-missed 未到期; 1 超窗口失败等通用失败; 3 已有实例在跑;
4 空间不足(拒绝下载); 5 新集合损坏(拒绝生效)。
"""
from __future__ import annotations

import argparse
import datetime as dt
import errno
import fcntl
import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Asia/Shanghai")   # 本地时区固定(方案:90); 状态同时记 UTC

DEFAULT_ROOT = Path.home() / "trade-standby"
TOOL_NAME = "standby_sync"
MANIFEST_SCHEMA_VERSION = 1
DEDUP_WINDOW_SECONDS = 604800          # 7 天(四元组, 见模块 docstring)
EVENT_KEYS = {
    "corrupt_set": "standby_sync_corrupt_set",
    "window_fail": "standby_sync_window_fail",
    "stale_recovery_point": "standby_sync_stale_recovery_point",
    "space_insufficient": "standby_sync_space_insufficient",
}
# 启动校验 deny 清单: 目标目录不许指进开发树/生产库(任务书「目录」第 9 条)。
# 仅当路径真实存在才生效(CI/tmp 树不受影响); STANDBY_SYNC_DENY_PATHS 可追加(冒号分隔)。
DEFAULT_DENY_PATHS = [
    "/Users/linhuichen/code/trade",
    "/Users/linhuichen/code/trade-data",
]
ROLES = {"db", "freeze", "cursor", "state", "sidecar"}
REQUIRED_ROLES_DEFAULT = ["db"]        # 恢复范围下限: 必须含活跃 DB
# 解压比(盘点实测 3.61GiB 原始 / 0.996GiB gzip ≈ 3.6); manifest 可给
# size_uncompressed 覆盖, 缺省按本比值估峰值空间(staging 1 份 + 单份解压)。
DEFAULT_UNCOMPRESSED_RATIO = 3.6
RECOVERY_EVENT_SUFFIX = "_recovered"   # 恢复通知事件身份(notify.py dedup-key 同源)


def _now() -> dt.datetime:
    """当前时刻(Asia/Shanghai)。测试冻结运行日用(L51): monkeypatch 本函数。"""
    return dt.datetime.now(LOCAL_TZ)


def _utc(ts: dt.datetime) -> str:
    return ts.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sleep(seconds: float) -> None:
    """退避 sleep。测试 monkeypatch 本函数避免真实等待。"""
    if seconds > 0:
        time.sleep(seconds)


def _sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _disk_free(path: Path) -> int:
    """可用字节数。测试 monkeypatch 本函数模拟空间不足。"""
    return shutil.disk_usage(str(path)).free


def emit_event_once(state: dict, store: "StateStore", event_key: str,
                    subject: str, body: str, log) -> bool:
    """同日事件去重(本层): 同一事件当日已报过 ⇒ 不再进入外发路径。

    通知层(notify.py --dedup-key/--dedup-window 7 天)兜底跨进程/跨重启去重;
    本层再加同日守门, 保证「同一事件不按尝试次数和日期重新刷屏」在本进程
    状态内即成立(测试对 emit_event 打桩计数即验证本层行为)。
    """
    today = _now().strftime("%Y-%m-%d")
    noted = state.setdefault("events_notified", {})
    if noted.get(event_key) == today:
        log(f"[standby_sync] 事件 {event_key} 今日已报过, 同日不重复外发")
        return True
    ok = emit_event(event_key, subject, body, log=log)
    if ok:
        noted[event_key] = today
        _mark_pending_recovery(state, event_key)
        store.save(state)
    return ok


def _mark_pending_recovery(state: dict, event_key: str) -> None:
    """故障事件真发出后登记「待恢复」, 恢复时才能发恢复通知(未通知过不发)。"""
    pend = state.setdefault("pending_recovery", [])
    if event_key not in pend:
        pend.append(event_key)


def emit_recovery_once(state: dict, store: "StateStore", event_key: str,
                       detail: str, log) -> bool:
    """对**已通知过**的故障事件发一次恢复通知, 成功后清账。

    事件身份/去重沿用 notify.py: dedup-key = ``<event_key>_recovered``, 7 天窗
    (与故障事件身份不同 ⇒ 不被故障事件的去重窗吞掉)。发送失败保持待恢复,
    下次成功同步再补发; 未进入 pending_recovery(从未成功通知)⇒ 直接跳过。
    """
    pend = state.get("pending_recovery") or []
    if event_key not in pend:
        return False
    now = _now()
    rec_key = event_key + RECOVERY_EVENT_SUFFIX
    ok = emit_event(rec_key,
                    f"[恢复] {event_key} 已恢复 {now:%m-%d %H:%M}",
                    f"{detail}<br>时间(本地): {now:%Y-%m-%d %H:%M:%S}"
                    f"<br>本恢复通知只对已通知过的故障事件发送一次。",
                    log=log, from_prefix="[恢复]")
    if ok:
        pend.remove(event_key)
        state["pending_recovery"] = pend
        store.save(state)
        log(f"[standby_sync] 恢复通知已发 {rec_key}")
    return ok


def emit_event(event_key: str, subject: str, body: str,
               dry_run: bool = False, log=None,
               from_prefix: str = "[告警]") -> bool:
    """经 notify.py CLI 发事件(四元组见模块 docstring)。

    测试/演练全部打桩(monkeypatch 本函数, L48 禁真发); dry_run 透传 --dry-run。
    故障事件 from_prefix="[告警]", 恢复通知传 "[恢复]"(邮件标题不误导)。
    返回 True=CLI 退出 0(suppress 也算已路由), False=调用失败(只记日志不重试)。
    """
    log = log or (lambda m: print(m, flush=True))
    notify = Path(__file__).resolve().parent / "notify.py"
    if not notify.exists():
        log(f"[standby_sync] notify.py 不存在, 事件 {event_key} 只落日志")
        return False
    cmd = [sys.executable, str(notify), subject, body,
           "--severe", "--from-prefix", from_prefix,
           "--dedup-key", event_key,
           "--dedup-window", str(DEDUP_WINDOW_SECONDS),
           "--alert-issue", f"{TOOL_NAME} {event_key}"]
    if dry_run:
        cmd.append("--dry-run")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    except Exception as exc:              # 网络/超时等: 事件发送失败不吞主流程结论
        log(f"[standby_sync] 事件 {event_key} 发送异常: {exc}")
        return False
    if r.returncode != 0:
        log(f"[standby_sync] 事件 {event_key} 发送失败 rc={r.returncode} "
            f"stderr={r.stderr[-300:]}")
        return False
    return True


# ---------------------------------------------------------------- manifest --

class ManifestError(Exception):
    """集合完整性/可信度错误(确定性; 窗口内仍重试排除瞬态, 尽头报 corrupt_set)。"""


class SpaceError(Exception):
    """空间不足(不可重试; 拒绝下载+报事件)。"""


class WindowFailError(Exception):
    """窗口预算耗尽(报 window_fail 事件)。"""


def normalize_manifest(raw: dict) -> dict:
    """manifest 防御式解析(单一入口, C 批契约对齐只改这里)。

    返回规范化 dict; 结构性问题抛 ManifestError(带具体对象名, 供
    「问题能定位到具体对象」验收)。
    """
    if not isinstance(raw, dict):
        raise ManifestError("manifest 根不是 JSON object")
    if raw.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ManifestError(f"schema_version={raw.get('schema_version')!r} "
                            f"!= {MANIFEST_SCHEMA_VERSION}")
    bd = raw.get("business_date") or ""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", bd):
        raise ManifestError(f"集合 business_date={bd!r} 非法")
    files = raw.get("files")
    if not isinstance(files, list) or not files:
        raise ManifestError("files 为空/缺失")
    out_files = []
    for i, ent in enumerate(files):
        if not isinstance(ent, dict):
            raise ManifestError(f"files[{i}] 不是 object")
        key = ent.get("key") or ent.get("path") or ""
        if not key:
            raise ManifestError(f"files[{i}] 缺 key/path")
        role = ent.get("role") or "sidecar"
        if role not in ROLES:
            raise ManifestError(f"{key}: 未知 role={role!r}")
        size = ent.get("size")
        if not isinstance(size, int) or size < 0:
            raise ManifestError(f"{key}: size 缺失/非法({size!r})")
        sha = ent.get("sha256_gz") or ent.get("sha256") or ""
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ManifestError(f"{key}: sha256_gz 缺失/非法")
        fbd = ent.get("business_date") or bd
        if fbd and fbd != bd:
            raise ManifestError(
                f"{key}: 对象业务日期 {fbd} != 集合业务日期 {bd}(错业务日期)")
        # 解压后大小: manifest 显式给(精确)或用实测解压比估算(峰值空间口径)
        size_u = ent.get("size_uncompressed", ent.get("uncompressed_size"))
        if not isinstance(size_u, int) or isinstance(size_u, bool) or size_u < 0:
            size_u = (int(size * DEFAULT_UNCOMPRESSED_RATIO)
                      if key.endswith(".gz") else size)
        out_files.append({
            "key": key, "role": role, "name": ent.get("name") or Path(key).name,
            "size": size, "size_uncompressed": size_u, "sha256_gz": sha,
            "sha256_uncompressed": ent.get("sha256_uncompressed") or "",
            "business_date": fbd,
            "tables": ent.get("tables") or {},
            "probe": ent.get("probe") or {},
        })
    m = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "complete": bool(raw.get("complete", True)),
        "business_date": bd,
        "generated_at": raw.get("generated_at") or "",
        "source_run": raw.get("source_run") or "",
        "archive_hint": raw.get("archive_hint") or "",
        "files": out_files,
    }
    if not m["complete"]:
        miss = [f["key"] for f in out_files if f.get("missing")] or "(complete=false)"
        raise ManifestError(f"集合不完整(complete=false): {miss}")
    return m


def manifest_identity(m: dict, manifest_bytes: bytes) -> str:
    """version_id = 业务日期 + source_run + manifest sha 前 10 位。

    同一归档 ⇒ 同一 id(幂等不产冲突版本); 内容不同 ⇒ id 不同。
    """
    h = hashlib.sha256(manifest_bytes).hexdigest()[:10]
    run = re.sub(r"[^0-9A-Za-z_.-]", "_", m["source_run"] or "norun")[:24]
    return f"{m['business_date']}-{run}-{h}"


# ------------------------------------------------------------------ source --

class Source:
    """下载源抽象。local=本地目录(测试/演练/降级通道); r2=SigV4 GET。"""

    def fetch_manifest(self) -> tuple[bytes, dict]:
        raise NotImplementedError

    def fetch_file(self, key: str, dest: Path) -> None:
        raise NotImplementedError


class LocalSource(Source):
    def __init__(self, src_dir: Path, manifest_name: str = "manifest.json"):
        self.src_dir = Path(src_dir)
        self.manifest_path = self.src_dir / manifest_name

    def fetch_manifest(self) -> tuple[bytes, dict]:
        if not self.manifest_path.exists():
            raise FileNotFoundError(f"manifest 不存在: {self.manifest_path}")
        raw = self.manifest_path.read_bytes()
        return raw, json.loads(raw.decode("utf-8"))

    def fetch_file(self, key: str, dest: Path) -> None:
        src = (self.src_dir / key).resolve()
        # 防路径逃逸: key 不许翻出源目录
        if not str(src).startswith(str(self.src_dir.resolve()) + os.sep):
            raise ManifestError(f"{key}: 路径逃逸, 拒绝")
        if not src.exists():
            raise FileNotFoundError(f"{key}: 源缺文件(sidecar/对象缺失)")
        shutil.copyfile(src, dest)


class R2Source(Source):
    """R2 备份桶 GET(纯标准库 SigV4; 不 import upload_r2——其模块级 load_env
    会 sys.exit, import 即副作用)。凭据自 .env(R2_BACKUP2_* 键, 与
    upload_r2.py 同名), 值不打印不入命令行。manifest_key 待 C 批契约定案
    后对齐(当前缺省 standby/manifest_latest.json 为占位)。
    """

    def __init__(self, endpoint: str, bucket: str, ak: str, sk: str,
                 manifest_key: str, timeout: int = 300):
        from urllib.parse import urlparse
        self.host = urlparse(endpoint).hostname
        self.endpoint = endpoint.rstrip("/")
        self.bucket = bucket
        self.ak, self.sk = ak, sk
        self.manifest_key = manifest_key
        self.timeout = timeout

    def _s3_get(self, key: str) -> bytes:
        import hmac as _hmac
        from urllib.parse import quote
        now = dt.datetime.now(dt.timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(b"").hexdigest()
        path = f"/{self.bucket}/" + quote(key, safe="/")
        headers = {
            "host": self.host,
            "x-amz-date": amz_date,
            "x-amz-content-sha256": payload_hash,
        }
        signed = ";".join(sorted(headers))
        canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in sorted(headers))
        req = f"GET\n{path}\n\n{canonical_headers}\n{signed}\n{payload_hash}"
        scope = f"{date_stamp}/auto/s3/aws4_request"
        sts = (f"AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n"
               + hashlib.sha256(req.encode()).hexdigest())

        def _sign(msg: bytes, key_: bytes) -> bytes:
            return _hmac.new(key_, msg, hashlib.sha256).digest()

        k = _sign(("AWS4" + self.sk).encode(), b"")
        for part in (date_stamp, "auto", "s3", "aws4_request"):
            k = _sign(part.encode(), k)
        sig = _hmac.new(k, sts.encode(), hashlib.sha256).hexdigest()
        url = f"{self.endpoint}{path}"
        req_headers = dict(headers)
        req_headers["Authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={self.ak}/{scope}, "
            f"SignedHeaders={signed}, Signature={sig}")
        request = urllib.request.Request(url, headers=req_headers, method="GET")
        with urllib.request.urlopen(request, timeout=self.timeout) as resp:
            return resp.read()

    def fetch_manifest(self) -> tuple[bytes, dict]:
        raw = self._s3_get(self.manifest_key)
        return raw, json.loads(raw.decode("utf-8"))

    def fetch_file(self, key: str, dest: Path) -> None:
        data = self._s3_get(key)
        tmp = dest.with_name(dest.name + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, dest)


def build_source(args) -> Source:
    if args.source == "local":
        return LocalSource(Path(args.source_dir), args.manifest_name)
    # r2: 凭据优先级 CLI 参数 > .env(仓库根/REPO/GIT_REPO, 与 upload_r2 同键名)
    ak, sk = args.r2_access_key, args.r2_secret_key
    endpoint, bucket = args.r2_endpoint, args.r2_bucket
    if not (ak and sk and endpoint and bucket):
        for cand in [Path(args.repo_dir) / ".env",
                     Path(os.environ.get("REPO", "")) / ".env",
                     Path(os.environ.get("GIT_REPO", "")) / ".env"]:
            if cand and cand.exists():
                for line in cand.read_text().splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip())
        endpoint = endpoint or os.environ.get("R2_BACKUP2_ENDPOINT", "")
        bucket = bucket or os.environ.get("R2_BACKUP2_BUCKET", "signal-backup2")
        ak = ak or os.environ.get("R2_BACKUP2_ACCESS_KEY_ID", "")
        sk = sk or os.environ.get("R2_BACKUP2_SECRET_ACCESS_KEY", "")
    if not (ak and sk and endpoint):
        raise SystemExit("r2 源缺凭据(--r2-access-key/--r2-secret-key 或 .env "
                         "R2_BACKUP2_*)")
    return R2Source(endpoint, bucket, ak, sk, args.manifest_key)


# ------------------------------------------------------------------ guard ---

def assert_dirs_isolated(paths, log) -> None:
    """启动校验: 目标目录不许指进开发树/生产库(任务书「目录」第 9 条)。"""
    deny = list(DEFAULT_DENY_PATHS)
    extra = os.environ.get("STANDBY_SYNC_DENY_PATHS", "")
    deny += [p for p in extra.split(":") if p]
    for p in paths:
        rp = str(Path(p).resolve())
        for d in deny:
            if not os.path.exists(d):
                continue
            rd = str(Path(d).resolve())
            if rp == rd or rp.startswith(rd + os.sep) or rd.startswith(rp + os.sep):
                raise SystemExit(
                    f"[standby_sync] 目录 {p} 与开发树/生产路径 {d} 重叠, 拒绝执行"
                    "(备用机目录必须与开发树硬隔离, 见 ~/trade-standby 布局)")


# ------------------------------------------------------------------ verify --

def verify_staged(manifest: dict, staging: Path, scratch: Path,
                  log) -> list[str]:
    """校验 staging 全部文件, 返回错误清单(空=PASS)。

    隔离恢复检查(只读): SQLite 打开一律 file:...?mode=ro, 作用于解压副本,
    不触碰任何生产/开发库路径。
    """
    errors: list[str] = []
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        for f in manifest["files"]:
            key, role = f["key"], f["role"]
            local = staging / key
            if not local.exists():
                errors.append(f"{key}: staging 缺文件")
                continue
            if local.stat().st_size != f["size"]:
                errors.append(f"{key}: size 不符 "
                              f"(实际 {local.stat().st_size} != manifest {f['size']})")
                continue
            if _sha256_file(local) != f["sha256_gz"]:
                errors.append(f"{key}: sha256_gz 不符(下载字节损坏)")
                continue
            if key.endswith(".gz"):
                if not f["sha256_uncompressed"]:
                    errors.append(f"{key}: gz 对象缺 sha256_uncompressed")
                    continue
                h = hashlib.sha256()
                try:
                    with gzip.open(local, "rb") as gz:
                        for chunk in iter(lambda: gz.read(1 << 20), b""):
                            h.update(chunk)
                except OSError as exc:
                    if getattr(exc, "errno", None) == errno.ENOSPC:
                        # 解压/写盘中途磁盘满: 归 space_insufficient, 不误报损坏
                        raise SpaceError(
                            f"{key}: 解压/写盘中途磁盘满(ENOSPC): {exc}") from exc
                    errors.append(f"{key}: gunzip 失败({exc})")
                    continue
                if h.hexdigest() != f["sha256_uncompressed"]:
                    errors.append(f"{key}: sha256_uncompressed 不符(解压损坏)")
                    continue
            # role 级内容校验(db→SQLite 只读检查; json sidecar→解析)
            plain = scratch / f"{Path(key).name}.plain"
            try:
                if key.endswith(".gz"):
                    with gzip.open(local, "rb") as gz, open(plain, "wb") as out:
                        shutil.copyfileobj(gz, out)
                else:
                    shutil.copyfile(local, plain)
                if role == "db" or plain.suffix == ".db":
                    uri = f"file:{plain}?mode=ro"
                    con = sqlite3.connect(uri, uri=True)
                    try:
                        try:
                            row = con.execute(
                                "PRAGMA integrity_check").fetchone()
                        except sqlite3.DatabaseError as exc:
                            # 非 SQLite 字节流/文件头损坏: 定位到具体对象
                            errors.append(f"{key}: SQLite 打开/完整性检查失败"
                                          f"({exc})")
                            continue
                        if not row or row[0] != "ok":
                            errors.append(f"{key}: SQLite integrity_check != ok"
                                          f"({row[0] if row else '无结果'})")
                            continue
                        for tbl, min_rows in (f.get("tables") or {}).items():
                            try:
                                n = con.execute(
                                    f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0]
                            except sqlite3.Error as exc:
                                errors.append(f"{key}: 关键表 {tbl} 查询失败({exc})")
                                continue
                            if n < int(min_rows):
                                errors.append(f"{key}: 关键表 {tbl} 行数 {n} "
                                              f"< 期望 {min_rows}")
                        probe = f.get("probe") or {}
                        if probe:
                            tbl, col, minv = (probe.get("table"),
                                              probe.get("col"), probe.get("min"))
                            try:
                                mx = con.execute(
                                    f'SELECT MAX("{col}") FROM "{tbl}"'
                                ).fetchone()[0]
                            except sqlite3.Error as exc:
                                errors.append(f"{key}: 探针 {tbl}.{col} 失败({exc})")
                            else:
                                if str(mx or "") < str(minv):
                                    errors.append(
                                        f"{key}: {tbl}.{col} MAX={mx} < 业务日期 "
                                        f"下限 {minv}(错业务日期)")
                    finally:
                        con.close()
                elif plain.suffix == ".json":
                    try:
                        json.loads(plain.read_text(encoding="utf-8"))
                    except ValueError as exc:
                        errors.append(f"{key}: JSON 解析失败({exc})")
            finally:
                if plain.exists():
                    plain.unlink()
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    for e in errors:
        log(f"[standby_sync] 校验 FAIL: {e}")
    return errors


def check_recovery_scope(manifest: dict, required_roles: list[str]) -> None:
    """核恢复范围: manifest 必须覆盖配置要求的角色(默认活跃 db 全在)。"""
    have = {f["role"] for f in manifest["files"]}
    for role in required_roles:
        if role not in have:
            raise ManifestError(f"恢复范围不足: manifest 缺 role={role} 对象")


def check_space(free_probe_dir: Path, manifest: dict,
                margin: float = 1.1, min_free_after: int = 0) -> None:
    """核空间: staging gz 总量 + 最大对象**解压后**大小 + 余量必须放得下。

    解压需求按 size_uncompressed(manifest 精确值, 缺省按实测解压比 3.6 估算)
    计算 —— 用压缩大小估会低估峰值(实测 3.6 倍), 导致 --min-free-gb 被击穿。
    """
    total_gz = sum(f["size"] for f in manifest["files"])
    biggest = max((f.get("size_uncompressed") or f["size"]
                   for f in manifest["files"]), default=0)
    need = int((total_gz + biggest) * margin) + min_free_after
    free = _disk_free(free_probe_dir)
    if free < need:
        raise SpaceError(f"空间不足: 可用 {free}B < 需要 {need}B "
                         f"(staging gz 合计 {total_gz} + 最大解压 {biggest} "
                         f"× {margin} + 保底 {min_free_after})")


# ------------------------------------------------------------------- dirs ---

class Layout:
    """目录布局: root/{work,data,archive,state,logs}。全可配。

    work=staging 下载区; data=解压校验暂存; archive/versions=固化版本目录 +
    latest_verified 原子 symlink; state=状态 JSON+锁; logs=日志。
    """

    def __init__(self, args):
        root = Path(args.root).expanduser()
        self.root = root
        self.work = Path(args.work_dir).expanduser() if args.work_dir else root / "work"
        self.data = Path(args.data_dir).expanduser() if args.data_dir else root / "data"
        self.archive = (Path(args.archive_dir).expanduser()
                        if args.archive_dir else root / "archive")
        self.state = (Path(args.state_dir).expanduser()
                      if args.state_dir else root / "state")
        self.logs = Path(args.log_dir).expanduser() if args.log_dir else root / "logs"
        self.versions = self.archive / "versions"
        self.latest = self.archive / "latest_verified"
        self.lock_file = self.state / "standby_sync.lock"
        self.state_file = self.state / "standby_sync_state.json"

    def ensure(self):
        for d in (self.work, self.data, self.archive, self.versions,
                  self.state, self.logs):
            d.mkdir(parents=True, exist_ok=True)


class StateStore:
    """state JSON 原子读写(tmp+rename); 历史截尾 60 条。"""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("state 根不是 object")
            return data
        except FileNotFoundError:
            return {"last_success_ts": None, "last_success_date": None,
                    "history": []}
        except ValueError:
            # 状态损坏: 保留现场副本, 从空状态重启(漏跑补偿自然兜住缺口)
            bad = self.path.with_suffix(".corrupt")
            try:
                os.replace(self.path, bad)
            except OSError:
                pass
            return {"last_success_ts": None, "last_success_date": None,
                    "history": []}

    def save(self, state: dict) -> None:
        state["history"] = state.get("history", [])[-60:]
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, self.path)


def log_factory(log_dir: Path):
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{TOOL_NAME}_{_now():%Y%m%d}.log"

    def _log(msg: str) -> None:
        line = f"{_now():%Y-%m-%d %H:%M:%S} {msg}"
        # 日志走 stderr: status 的 stdout 只输出 JSON(供脚本化消费, 不混日志行)
        print(line, file=sys.stderr, flush=True)
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
    return _log


# -------------------------------------------------------------------- sync --

def _sweep_staging(layout: Layout, log) -> None:
    """staging 残留安全清理: 只清自己登记命名的 work/staging-*(锁内执行)。"""
    if not layout.work.exists():
        return
    for p in layout.work.glob("staging-*"):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
            log(f"[standby_sync] 清 staging 残留 {p}")


def _latest_vid(layout: Layout) -> str:
    try:
        if layout.latest.is_symlink():
            return os.readlink(layout.latest).split("/")[-1]
    except OSError:
        pass
    return "(none)"


def _finalize(layout: Layout, manifest: dict, staging: Path, vid: str,
              manifest_bytes: bytes, duration: float, log) -> None:
    """固化版本目录 + 原子切 latest_verified + 写版本内 verify_record。"""
    vdir = layout.versions / vid
    if vdir.exists():
        # 幂等: 同一归档已有固化目录, 不重复产生冲突版本
        log(f"[standby_sync] 版本 {vid} 已固化, 幂等复用(不重建)")
    else:
        record = {
            "version_id": vid,
            "business_date": manifest["business_date"],
            "source_run": manifest["source_run"],
            "generated_at": manifest["generated_at"],
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "verified_at_local": _now().strftime("%Y-%m-%d %H:%M:%S"),
            "verified_at_utc": _utc(_now()),
            "duration_seconds": round(duration, 1),
            "files": [{"key": f["key"], "role": f["role"],
                       "sha256_gz": f["sha256_gz"]} for f in manifest["files"]],
        }
        (staging / "verify_record.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        (staging / ".standby-managed").write_text(json.dumps({
            "tool": TOOL_NAME, "version_id": vid,
            "manifest_sha256": record["manifest_sha256"]}), encoding="utf-8")
        (staging / "manifest.json").write_bytes(manifest_bytes)
        os.rename(staging, vdir)          # 同 root 同 fs: 原子目录改名
        log(f"[standby_sync] 固化版本目录 {vdir}")
    # 原子切 latest_verified: 临时 symlink + rename(方案「同步与原子生效流程」)
    if layout.latest.is_symlink() and os.readlink(layout.latest) == \
            f"versions/{vid}":
        log(f"[standby_sync] latest_verified 已指向 {vid}, 无需切换")
        return
    if layout.latest.exists() and not layout.latest.is_symlink() \
            and layout.latest.is_dir():
        raise RuntimeError(f"{layout.latest} 是实体目录不是 symlink, 拒绝覆盖, "
                           "请人工核实现场")
    tmp = layout.archive / f".latest_verified.tmp.{os.getpid()}"
    if tmp.exists() or tmp.is_symlink():
        tmp.unlink()
    os.symlink(f"versions/{vid}", tmp)
    os.replace(tmp, layout.latest)
    log(f"[standby_sync] latest_verified → versions/{vid}(原子切换完成)")


def _record_success(state, store, now: dt.datetime, downloadable, verified,
                    manifest: dict, manifest_bytes: bytes, duration: float,
                    attempts: int, missed: int, outcome: str, log) -> None:
    """写成功结果记录(成功/无变化/复用都算当日同步成功; 静默不外发)。"""
    rec = {
        "ts_local": now.strftime("%Y-%m-%d %H:%M:%S"),
        "ts_utc": _utc(now),
        "outcome": outcome,
        "latest_downloadable": downloadable,
        "latest_verified": verified,
        "business_date": manifest["business_date"],
        "source_run": manifest["source_run"],
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest()[:16],
        "duration_seconds": round(duration, 1),
        "attempts": attempts,
        "missed_runs": missed,
    }
    state["last_success_ts"] = rec["ts_local"]
    state["last_success_date"] = now.strftime("%Y-%m-%d")
    state["last_success_utc"] = rec["ts_utc"]
    state["latest_downloadable"] = downloadable
    state["latest_verified"] = verified
    state["business_date"] = manifest["business_date"]
    state["source_run"] = manifest["source_run"]
    state["missed_runs_last"] = missed
    state["history"] = state.get("history", []) + [rec]
    store.save(state)
    log(f"[standby_sync] 成功记录 outcome={outcome} vid={verified} "
        f"business_date={manifest['business_date']} missed_runs={missed}")


def _check_stale(layout: Layout, store: StateStore, state: dict, args,
                 log) -> None:
    """最新可恢复点过期检测(成功/无变化路径都查: 远端停更要暴露, 不静默)。"""
    vid = _latest_vid(layout)
    if vid == "(none)":
        return
    bd = None
    rec = layout.versions / vid / "verify_record.json"
    if rec.exists():
        try:
            bd = json.loads(rec.read_text(encoding="utf-8"))["business_date"]
        except (ValueError, KeyError):
            pass
    if not bd:
        return
    age = (_now().date() - dt.datetime.strptime(bd, "%Y-%m-%d").date()).days
    state["latest_recovery_point_age_days"] = age
    store.save(state)
    if age > args.stale_days:
        now = _now()
        emit_event_once(
            state, store, EVENT_KEYS["stale_recovery_point"],
            f"[告警] standby_sync 最新可恢复点过期 {age}天 {now:%m-%d %H:%M}",
            f"备用机最新已验证恢复点业务日期 {bd}, 已 {age} 天"
            f"(阈值 {args.stale_days} 天)。<br>时间(本地): "
            f"{now:%Y-%m-%d %H:%M:%S}<br>latest_verified: {vid}"
            f"<br>需要动作: 排查云端备份链是否停更(C 批 capture 链)"
            f"<br>本告警 7 天去重窗内不重复, 期间每日静默只记状态。",
            log=log)
        log(f"[standby_sync] 恢复点过期告警已发(年龄 {age} 天)")
    else:
        log(f"[standby_sync] 恢复点年龄 {age} 天(阈值内)")
        # 过期告警曾发出且现已回到阈值内 ⇒ 对已通知事件发一次恢复通知
        key = EVENT_KEYS["stale_recovery_point"]
        if key in (state.get("pending_recovery") or []):
            emit_recovery_once(
                state, store, key,
                f"最新已验证恢复点已刷新: 业务日期 {bd}, 年龄 {age} 天 "
                f"≤ 阈值 {args.stale_days} 天, latest_verified: {vid}", log)


def _emit_sync_recoveries(layout: "Layout", state: dict, store: StateStore,
                          log) -> None:
    """同步成功后: 对已通知且已解除的三类故障事件各发一次恢复通知。

    只在本次同步真正成功(校验通过/reused/no-change)后调用; dry-run 在调用点
    之前已提前 return, 不会清账也不会外发。
    """
    for name in ("corrupt_set", "window_fail", "space_insufficient"):
        key = EVENT_KEYS[name]
        if key in (state.get("pending_recovery") or []):
            emit_recovery_once(
                state, store, key,
                f"备用机同步已恢复正常(本次同步成功), latest_verified: "
                f"{_latest_vid(layout)}", log)


def _handle_space_insufficient(args, layout: "Layout", state: dict,
                               store: StateStore, now: dt.datetime,
                               error: str, log) -> int:
    """空间不足处置(dry-run 不写状态不外发: README/CLI help 承诺)。"""
    if args.dry_run:
        log(f"[standby_sync] dry-run: {error}; rc=4 拒绝下载(不写状态不外发)")
        return 4
    state["last_failure"] = {
        "ts_local": now.strftime("%Y-%m-%d %H:%M:%S"),
        "rc": 4, "error": error}
    store.save(state)
    emit_event_once(
        state, store, EVENT_KEYS["space_insufficient"],
        f"[告警] standby_sync 空间不足 拒绝下载 {now:%m-%d %H:%M}",
        f"备用机同步空间不足, 已拒绝下载并保留全部旧版本。"
        f"<br>时间(本地): {now:%Y-%m-%d %H:%M:%S}<br>错误: {error}"
        f"<br>latest_verified: {_latest_vid(layout)}(不受影响)"
        f"<br>需要动作: 清理归档盘或调整 --min-free-gb。",
        log=log)
    log(f"[standby_sync] {error}; rc=4 拒绝下载")
    return 4


def _handle_corrupt_set(args, layout: "Layout", state: dict,
                        store: StateStore, now: dt.datetime,
                        error: str, log) -> int:
    """新集合损坏处置(dry-run 不写状态不外发)。"""
    if args.dry_run:
        log(f"[standby_sync] dry-run: 新集合损坏 {error}; rc=5(不写状态不外发)")
        return 5
    state["last_failure"] = {
        "ts_local": now.strftime("%Y-%m-%d %H:%M:%S"),
        "rc": 5, "error": error}
    store.save(state)
    emit_event_once(
        state, store, EVENT_KEYS["corrupt_set"],
        f"[告警] standby_sync 新集合损坏 {now:%m-%d %H:%M}",
        f"备用机新集合校验失败, 已拒绝生效, 旧版本保留可用。"
        f"<br>时间(本地): {now:%Y-%m-%d %H:%M:%S}<br>错误: {error}"
        f"<br>latest_verified: {_latest_vid(layout)}(不受影响)"
        f"<br>需要动作: 排查云端备份链/manifest(具体对象见错误信息)。",
        log=log)
    log(f"[standby_sync] 新集合损坏 rc=5: {error}")
    return 5


def _handle_window_fail(args, layout: "Layout", state: dict,
                        store: StateStore, now: dt.datetime,
                        error: str, log) -> int:
    """超窗口失败处置(dry-run 不写状态不外发)。"""
    if args.dry_run:
        log(f"[standby_sync] dry-run: 超窗口失败 {error}; rc=1(不写状态不外发)")
        return 1
    state["last_failure"] = {
        "ts_local": now.strftime("%Y-%m-%d %H:%M:%S"),
        "rc": 1, "error": error}
    store.save(state)
    emit_event_once(
        state, store, EVENT_KEYS["window_fail"],
        f"[告警] standby_sync 超窗口失败 {now:%m-%d %H:%M}",
        f"备用机同步窗口预算耗尽仍失败, 旧版本保留可用。"
        f"<br>时间(本地): {now:%Y-%m-%d %H:%M:%S}<br>错误: {error}"
        f"<br>latest_verified: {_latest_vid(layout)}"
        f"<br>需要动作: 排查网络/R2 可达性; 明日窗口自动重试。",
        log=log)
    log(f"[standby_sync] 超窗口失败 rc=1: {error}")
    return 1


def sync_command(args, log) -> int:
    layout = Layout(args)
    assert_dirs_isolated(
        [layout.root, layout.work, layout.data, layout.archive,
         layout.state, layout.logs], log)
    layout.ensure()
    store = StateStore(layout.state_file)
    state = store.load()
    now = _now()
    today = now.strftime("%Y-%m-%d")

    # 单实例 flock(跨进程): 拿不到锁 ⇒ 立即退出, 不排队不重叠
    lock_fd = os.open(layout.lock_file, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EAGAIN):
            log("[standby_sync] 已有实例在跑(flock), 本实例退出 rc=3")
            return 3
        raise
    try:
        # launchd 启动补偿模式: 今日已成功 ⇒ 静默退出
        if args.only_if_missed and state.get("last_success_date") == today:
            log("[standby_sync] 今日已成功, 补偿入口静默退出")
            return 0
        _sweep_staging(layout, log)

        # 漏跑补偿预算: 上次成功到今天的缺口只做「一次有效同步」, 记录漏跑天数
        # 与真实备份年龄, 不重写任何时间戳(方案「调度规则」第 5 条)
        missed = 0
        last_ok = state.get("last_success_date")
        if last_ok:
            d0 = dt.datetime.strptime(last_ok, "%Y-%m-%d").date()
            missed = max(0, (now.date() - d0).days - 1)

        source = build_source(args)
        deadline = now + dt.timedelta(minutes=args.deadline_minutes)
        backoff = args.backoff_seconds
        last_err: Exception | None = None

        for attempt in range(1, args.max_attempts + 1):
            if _now() > deadline:
                raise WindowFailError(
                    f"超共享总截止({args.deadline_minutes}min), "
                    f"已尝试 {attempt - 1} 次")
            log(f"[standby_sync] 第 {attempt}/{args.max_attempts} 次尝试")
            try:
                manifest_bytes, raw = source.fetch_manifest()
                manifest = normalize_manifest(raw)
                check_recovery_scope(manifest, args.required_roles)
                vid = manifest_identity(manifest, manifest_bytes)

                prev = _latest_vid(layout)
                if prev == vid and (layout.versions / vid /
                                    "verify_record.json").exists():
                    # 远端无新集合: 保留旧版本, 记真实年龄, 不伪造新备份
                    age = (now.date() - dt.datetime.strptime(
                        manifest["business_date"], "%Y-%m-%d").date()).days
                    log(f"[standby_sync] 远端无新集合(latest={prev}), "
                        f"真实备份年龄 {age} 天, 保留原版本")
                    if args.dry_run:
                        log("[standby_sync] dry-run: 无新集合, 不写状态")
                        return 0
                    _record_success(state, store, now, vid, vid, manifest,
                                    manifest_bytes, 0.0, attempt, missed,
                                    "no-change", log)
                    _emit_sync_recoveries(layout, state, store, log)
                    _check_stale(layout, store, state, args, log)
                    return 0

                vdir = layout.versions / vid
                if vdir.exists() and (vdir / "verify_record.json").exists():
                    # 同一归档已固化已验(如上次窗口验完但切链未及执行): 幂等复用
                    if args.dry_run:
                        log("[standby_sync] dry-run: 已固化版本幂等复用, "
                            "不切链不写状态")
                        return 0
                    _finalize(layout, manifest,
                              layout.work / "staging-absent", vid,
                              manifest_bytes, 0.0, log)
                    _record_success(state, store, now, vid, vid, manifest,
                                    manifest_bytes, 0.0, attempt, missed,
                                    "reused", log)
                    _emit_sync_recoveries(layout, state, store, log)
                    _check_stale(layout, store, state, args, log)
                    return 0

                # 核恢复范围与空间: 放不下 ⇒ 拒绝下载 + 报事件 + 不删旧版本
                check_space(layout.work, manifest,
                            min_free_after=int(args.min_free_gb * (1 << 30)))

                staging = layout.work / f"staging-{vid}"
                staging.mkdir(parents=True, exist_ok=True)
                t0 = time.monotonic()
                for f in manifest["files"]:
                    dest = staging / f["key"]
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if dest.exists() and dest.stat().st_size == f["size"] \
                            and _sha256_file(dest) == f["sha256_gz"]:
                        log(f"[standby_sync] 复用已下对象 {f['key']}(断点续传)")
                        continue
                    if dest.exists():
                        dest.unlink()
                    try:
                        source.fetch_file(f["key"], dest)
                    except FileNotFoundError as exc:
                        # 源缺对象(manifest 引用了不存在的 sidecar/文件)
                        # = 集合不完整, 属确定性损坏, 不是可重试传输错
                        raise ManifestError(
                            f"{f['key']}: 源缺对象(缺 sidecar/文件缺失)") from exc
                    log(f"[standby_sync] 下载完成 {f['key']} "
                        f"({dest.stat().st_size}B)")

                errors = verify_staged(manifest, staging,
                                       layout.data / "scratch", log)
                if errors:
                    raise ManifestError(
                        "新集合校验失败: " + "; ".join(errors[:5])
                        + ("..." if len(errors) > 5 else ""))
                duration = time.monotonic() - t0
                if args.dry_run:
                    log("[standby_sync] dry-run: 校验通过, 不固化不切链不写状态")
                    _sweep_staging(layout, log)
                    return 0
                _finalize(layout, manifest, staging, vid, manifest_bytes,
                          duration, log)
                _record_success(state, store, now, vid, vid, manifest,
                                manifest_bytes, duration, attempt, missed,
                                "synced", log)
                _emit_sync_recoveries(layout, state, store, log)
                retention_command(args, log, layout=layout,
                                  after_success=True)
                _check_stale(layout, store, state, args, log)
                _sweep_staging(layout, log)
                return 0
            except SpaceError as exc:
                return _handle_space_insufficient(
                    args, layout, state, store, now, str(exc), log)
            except ManifestError as exc:
                # 确定性损坏(hash/缺文件/错日期/integrity): 窗口内仍重试(排除
                # 瞬态传输错), 尽头报 corrupt_set; staging 不生效
                last_err = exc
                log(f"[standby_sync] 集合完整性错误: {exc}")
            except OSError as exc:
                if getattr(exc, "errno", None) == errno.ENOSPC:
                    # 下载/解压/写盘中途磁盘满: 不可重试, 归 space_insufficient
                    # (不能落进可重试分支最后误报 window_fail 误导排查方向)
                    return _handle_space_insufficient(
                        args, layout, state, store, now,
                        f"下载/解压写盘中途磁盘满(ENOSPC): {exc}", log)
                last_err = exc
                log(f"[standby_sync] 尝试失败(可重试): {exc!r}")
            except (ValueError, urllib.error.URLError,
                    subprocess.SubprocessError) as exc:
                # 传输/网络/本地 IO: 可重试
                last_err = exc
                log(f"[standby_sync] 尝试失败(可重试): {exc!r}")
            if attempt < args.max_attempts:
                if _now() > deadline:
                    break                       # 真截止: 不再重试
                wait = min(backoff, max(0.0, (deadline - _now()).total_seconds()))
                log(f"[standby_sync] 退避 {wait}s 后重试")
                _sleep(wait)                    # 0s 退避(桩/测试)也照走重试
                backoff *= 2
        # 窗口预算耗尽
        if isinstance(last_err, ManifestError):
            return _handle_corrupt_set(
                args, layout, state, store, now, str(last_err), log)
        raise WindowFailError(
            f"窗口预算耗尽({args.max_attempts} 次尝试), 最后错误: {last_err!r}")
    except WindowFailError as exc:
        return _handle_window_fail(
            args, layout, state, store, now, str(exc), log)
    finally:
        os.close(lock_fd)


# --------------------------------------------------------------- retention --

def _version_infos(layout: Layout) -> list[dict]:
    """枚举本任务登记的版本目录(带 .standby-managed 标记; 未登记目录一律不碰)。"""
    out = []
    if not layout.versions.exists():
        return out
    for d in layout.versions.iterdir():
        if not d.is_dir() or not (d / ".standby-managed").exists():
            continue                       # 未登记目录: retention 不管理
        rec = d / "verify_record.json"
        ok, bd = False, None
        if rec.exists():
            try:
                r = json.loads(rec.read_text(encoding="utf-8"))
                ok = True                  # verify_record.json 在位=曾验过
                bd = r.get("business_date")
            except ValueError:
                pass
        size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
        out.append({"vid": d.name, "dir": d, "verified": ok,
                    "business_date": bd, "size": size})
    out.sort(key=lambda v: v["business_date"] or "", reverse=True)
    return out


def plan_retention(infos: list[dict], latest_vid: str, now: dt.datetime,
                   keep_daily: int, keep_weekly: int, min_keep: int,
                   min_free_bytes: int, free_probe_dir: Path,
                   log) -> tuple[list[dict], list[dict]]:
    """产出(保留, 删除)计划。

    规则: latest_verified 永远保; keep_daily 天内日保; 最近 keep_weekly 个 ISO
    周各保最早一份周保; 至少保 min_keep 份已验版本; 无验证记录的版本跳过不动;
    空间投影不足 ⇒ 逐个放弃最老保留(不动 latest/不破 min_keep)= 自动降级。
    """
    verified = [v for v in infos if v["verified"]]
    for v in infos:
        if not v["verified"]:
            log(f"[standby_sync] 保留清理: {v['vid']} 无验证记录, 跳过不动")
    keep: dict[str, dict] = {}
    for v in verified:
        if v["vid"] == latest_vid:
            keep[v["vid"]] = v
    cutoff = now.date() - dt.timedelta(days=keep_daily)
    for v in verified:
        try:
            bd = dt.datetime.strptime(v["business_date"], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            keep[v["vid"]] = v            # 日期读不出 ⇒ 保守不删
            continue
        if bd >= cutoff:
            keep.setdefault(v["vid"], v)
    weeks: dict[str, dict] = {}
    for v in reversed(verified):           # 时间升序 ⇒ 每周最早一份先进表
        try:
            iso = dt.datetime.strptime(
                v["business_date"], "%Y-%m-%d").date().isocalendar()
            wk = f"{iso[0]}-W{iso[1]:02d}"
        except (TypeError, ValueError):
            continue
        if wk not in weeks:
            weeks[wk] = v
    for wk in sorted(weeks.keys())[-keep_weekly:]:
        keep.setdefault(weeks[wk]["vid"], weeks[wk])
    if len(keep) < min_keep:              # 保留下限(默认 2)
        for v in verified:
            keep.setdefault(v["vid"], v)
            if len(keep) >= min_keep:
                break
    deletable = [v for v in verified if v["vid"] not in keep]
    # 空间自适应降级: 删完计划后投影可用空间仍 < min_free ⇒ 放弃最老保留
    if min_free_bytes > 0:
        def _projected_free() -> int:
            return _disk_free(free_probe_dir) + sum(v["size"] for v in deletable)
        if _projected_free() < min_free_bytes:
            degraded = []
            for v in sorted(keep.values(),
                            key=lambda x: x["business_date"] or ""):
                if len(keep) <= min_keep:
                    break
                if v["vid"] == latest_vid:
                    continue
                if _projected_free() >= min_free_bytes:
                    break
                keep.pop(v["vid"], None)
                deletable.append(v)
                degraded.append(v["vid"])
            if degraded:
                log(f"[standby_sync] 空间不足触发保留降级: 放弃最老 {degraded};"
                    f"(日/周保参数自动降档, 报告已说明)")
    return list(keep.values()), deletable


def retention_command(args, log, layout=None, after_success=False) -> int:
    """保留清理入口。「先验后删」: 只删带验证记录的登记版本; 只在集合验证
    成功后才执行(sync 内部调用), 独立调用时也按同一计划。"""
    own = layout is None
    if own:
        layout = Layout(args)
        assert_dirs_isolated([layout.root, layout.archive], log)
        layout.ensure()
    infos = _version_infos(layout)
    if not infos:
        log("[standby_sync] retention: 无登记版本, 无事可做")
        return 0
    latest = _latest_vid(layout)
    keep, delete = plan_retention(
        infos, latest, _now(), args.keep_daily, args.keep_weekly,
        args.min_keep_versions, int(args.min_free_gb * (1 << 30)),
        layout.versions, log)
    if args.dry_run:
        log(f"[standby_sync] retention --dry-run: 保留 "
            f"{sorted(v['vid'] for v in keep)}; 拟删 "
            f"{sorted(v['vid'] for v in delete)}; latest={latest}")
        return 0
    # 执行前再核两道硬边界(防计划函数回归): 不删 latest; 不跌破最少保留数
    n_verified = len([v for v in infos if v["verified"]])
    for v in delete:
        if v["vid"] == latest:
            log(f"[standby_sync] 拒删 latest_verified {v['vid']}")
            return 1
    if delete and n_verified - len(delete) < args.min_keep_versions:
        log("[standby_sync] 拒删: 会跌破最少保留版本数 "
            f"{args.min_keep_versions}(现已验 {n_verified}, 拟删 {len(delete)})")
        return 1
    for v in delete:
        shutil.rmtree(v["dir"], ignore_errors=False)
        log(f"[standby_sync] retention 删除 {v['vid']} "
            f"({v['size']}B, business_date={v['business_date']})")
    log(f"[standby_sync] retention 完成: 删 {len(delete)} 留 {len(keep)}"
        f"(latest={latest}, 日保 {args.keep_daily} 天/周保 "
        f"{args.keep_weekly} 周/下限 {args.min_keep_versions})")
    return 0


# ------------------------------------------------------------------ verify --

def verify_command(args, log) -> int:
    """复验已固化版本(只读; 默认 latest_verified)。"""
    layout = Layout(args)
    assert_dirs_isolated([layout.root, layout.archive], log)
    vid = args.version or _latest_vid(layout)
    if vid == "(none)":
        log("[standby_sync] 无 latest_verified, 无可验版本")
        return 1
    vdir = layout.versions / vid
    mfile = vdir / "manifest.json"
    if not mfile.exists():
        log(f"[standby_sync] {vid} 缺 manifest.json, 无法复验")
        return 1
    manifest_bytes = mfile.read_bytes()
    manifest = normalize_manifest(json.loads(manifest_bytes.decode("utf-8")))
    errors = verify_staged(manifest, vdir, layout.data / "scratch-verify", log)
    if errors:
        log(f"[standby_sync] 复验 {vid} FAIL: {errors[:5]}")
        return 1
    log(f"[standby_sync] 复验 {vid} PASS "
        f"(business_date={manifest['business_date']}, "
        f"files={len(manifest['files'])})")
    return 0


# ------------------------------------------------------------------ status --

def status_command(args, log) -> int:
    """打印状态摘要(latest_verified/可下载点/真实年龄/版本清单)。"""
    layout = Layout(args)
    store = StateStore(layout.state_file)
    state = store.load()
    latest = _latest_vid(layout)
    now = _now()
    out = {
        "latest_verified": latest,
        "latest_downloadable": state.get("latest_downloadable"),
        "last_success_ts": state.get("last_success_ts"),
        "last_success_utc": state.get("last_success_utc"),
        "business_date": state.get("business_date"),
        "source_run": state.get("source_run"),
        "missed_runs_last": state.get("missed_runs_last"),
        "latest_recovery_point_age_days":
            state.get("latest_recovery_point_age_days"),
        "versions": [],
    }
    for v in _version_infos(layout):
        age = None
        if v["business_date"]:
            try:
                age = (now.date() - dt.datetime.strptime(
                    v["business_date"], "%Y-%m-%d").date()).days
            except ValueError:
                pass
        out["versions"].append({
            "vid": v["vid"], "verified": v["verified"],
            "business_date": v["business_date"], "age_days": age,
            "size_bytes": v["size"]})
    if state.get("last_success_ts"):
        try:
            ts = dt.datetime.strptime(state["last_success_ts"],
                                      "%Y-%m-%d %H:%M:%S").replace(
                                          tzinfo=LOCAL_TZ)
            out["last_success_age_hours"] = round(
                (now - ts).total_seconds() / 3600, 1)
        except ValueError:
            pass
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


# -------------------------------------------------------------------- cli ---

def _add_common(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--dry-run", action="store_true",
                   help="演练: sync=只下载+校验(不固化不切链不写状态不外发); "
                        "retention=只打印计划; 通知一律不真发")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="备用机每日凌晨同步云端可恢复集合(工作包三/D 批)。"
                    "子命令: sync / verify / status / retention")
    p.add_argument("--root", default=str(DEFAULT_ROOT),
                   help=f"备用根目录(默认 {DEFAULT_ROOT}, 与开发树硬隔离)")
    p.add_argument("--work-dir"), p.add_argument("--data-dir")
    p.add_argument("--archive-dir"), p.add_argument("--state-dir")
    p.add_argument("--log-dir")
    p.add_argument("--source", choices=["local", "r2"], default="r2",
                   help="下载源(默认 r2; local=本地目录, 测试/演练/降级通道)")
    p.add_argument("--source-dir", help="local 源目录")
    p.add_argument("--manifest-name", default="manifest.json",
                   help="local 源 manifest 文件名")
    p.add_argument("--manifest-key", default="standby/manifest_latest.json",
                   help="r2 源 manifest key(C 批契约定案后对齐)")
    p.add_argument("--repo-dir",
                   default=str(Path(__file__).resolve().parent.parent),
                   help="r2 凭据 .env 查找用仓库目录")
    p.add_argument("--r2-endpoint"), p.add_argument("--r2-bucket")
    p.add_argument("--r2-access-key"), p.add_argument("--r2-secret-key")
    p.add_argument("--required-roles", default=",".join(REQUIRED_ROLES_DEFAULT),
                   help="恢复范围下限角色(逗号分隔, 默认 db)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sync", help="主同步(读 manifest→下载→校验→固化→切链)")
    s.add_argument("--max-attempts", type=int, default=3,
                   help="每窗口最多总尝试次数(默认 3)")
    s.add_argument("--backoff-seconds", type=float, default=120.0,
                   help="指数退避基数(默认 120s: 120/240/...)")
    s.add_argument("--deadline-minutes", type=float, default=120.0,
                   help="共享总截止(默认 120 分钟)")
    s.add_argument("--stale-days", type=int, default=2,
                   help="恢复点过期阈值(默认 2 天)")
    s.add_argument("--min-free-gb", type=float, default=5.0,
                   help="下载前最低可用空间(默认 5GiB)")
    s.add_argument("--only-if-missed", action="store_true",
                   help="启动补偿模式: 今日已成功则静默退出(launchd 唤醒用)")
    s.add_argument("--keep-daily", type=int, default=7)
    s.add_argument("--keep-weekly", type=int, default=4)
    s.add_argument("--min-keep-versions", type=int, default=2)
    _add_common(s)

    r = sub.add_parser("retention", help="独立执行保留清理(只在集合验证成功后)")
    r.add_argument("--keep-daily", type=int, default=7)
    r.add_argument("--keep-weekly", type=int, default=4)
    r.add_argument("--min-keep-versions", type=int, default=2)
    r.add_argument("--min-free-gb", type=float, default=5.0)
    _add_common(r)

    v = sub.add_parser("verify", help="复验已固化版本(或 latest_verified, 只读)")
    v.add_argument("--version", default=None,
                   help="要复验的 version_id(默认 latest_verified)")
    _add_common(v)

    st = sub.add_parser("status", help="打印状态摘要")
    _add_common(st)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.required_roles = [r for r in args.required_roles.split(",") if r]
    log = log_factory(Layout(args).logs)
    log(f"[standby_sync] 启动 cmd={args.cmd} source={args.source} "
        f"dry_run={args.dry_run}")
    # dry-run: 事件不真发(notify.py --dry-run 透传)
    global emit_event
    _orig_emit = emit_event
    if args.dry_run:
        def _dry_emit(event_key, subject, body, dry_run=False, log=None,
                      **kwargs):
            (log or print)(f"[standby_sync][dry-run] 事件 {event_key} 未真发")
            return True
        emit_event = _dry_emit
    try:
        if args.cmd == "sync":
            return sync_command(args, log)
        if args.cmd == "retention":
            return retention_command(args, log)
        if args.cmd == "verify":
            return verify_command(args, log)
        if args.cmd == "status":
            return status_command(args, log)
    finally:
        emit_event = _orig_emit
    return 2


if __name__ == "__main__":
    sys.exit(main())
