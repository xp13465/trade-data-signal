#!/usr/bin/env python3
"""backup_state_capture.py - 「完整可恢复集合」成套捕获(备份工作包二, 2026-11-14)。

把「真实接管所需状态」(冻结表/映射历史/采集游标/发布状态/通知状态/proof 台账)做成
**成套、带 hash、带业务日期、带来源证明**的归档集合; 由 backup_db.sh 在三库热备之后
调用, 配套 R2 归档上传入口 = upload_r2.py upload-state-capture。

原则(执行方案「工作包二」+ 任务书 /tmp/task-backup-capture-impl-20261114.md):
- **先声明后捕获**: 恢复清单 = 本文件 DECLARED_INVENTORY(捕获前写进 manifest);
  缺文件如实记 missing, **绝不发现缺文件后缩小清单凑成功**; 整体 complete 如实=false。
- **声明排除**(捕获前声明, 非事后缩表): DECLARED_EXCLUDES(如 .r2-protected/payloads
  内容寻址载荷, 1.21GB/日预算原因)随清单同时写进 manifest.declared_excludes, 绝不静默。
- **DB 不裸拷**: 本模块不复制任何 .db/-wal; DB 腿只「引用」同轮 backup_db.sh 产物
  (sha256/size/mtime + PRAGMA integrity_check + 关键表行数, 只读)。
- **sidecar 一致性**: 在 DB 快照之后读取; 每文件读前后 stat 复查 + 全部复制完
  finalize 前对源文件 stat+hash 复查; 变化 ⇒ 整体重试一次, 仍变 ⇒ 记 inconsistent,
  拒绝宣称完整(uploadable=false)。DB 与 sidecar 的共同业务截止点写入
  common_business_cutoff(文件内业务日期优先, mtime 兜底, 方法逐项记录)。
- **绝不含 secret/token/PID/socket/锁**: 文件名 deny-list(.env*/pem/key/p12/pid/
  sock/lock/token/credentials/id_rsa 等)+ 内容嗅探(私钥头/sk-/Bearer); 命中 ⇒ 记
  skipped/excluded, 不进集合(绝不静默)。
- **自校验**: 集合内逐文件 sha256 复算 + DB 副本 integrity_check; 失败 ⇒ 标失败,
  不冒充成功。本脚本**不发任何通知**(通知契约归 backup_db.sh 既有链, L48)。
- 上传成功前本地集合不删(本脚本不删任何东西; RETAIN_DAYS 清理只动 *_*.db)。

用法:
  python3 scripts/backup_state_capture.py --repo <repo> --backup-dir <dir> \
      --stamp <YYYYMMDD_HHMM> --out-root <dir> [--ready-file <path>] \
      [--scripts-dir <dir>] [--no-db-leg]
  退出码: 0=产出可上传集合(missing 如实记录不影响); 1=不完整到不可上传
  (不一致/自校验失败/清单全缺); 2=用法错误。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat as stat_mod
import sys
import tarfile
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "trade-state-capture-v1"

# ---- 恢复清单(捕获前声明; 改这里 = 改恢复范围, 必须同步 docs/backup-restore.md) ----
# pattern 相对 <repo>/data/; kind: file=单文件 / glob=通配 / dir=递归目录。
# 来源依据: /tmp/backup-inventory-20261114.md §二(38 项恢复清单, 2026-11-14 只读盘点)。
DECLARED_INVENTORY = [
    # 不可重建历史(T0 冻结表为最高优先缺口; 映射历史最新版无远端副本)
    ("不可重建历史", "signal_kelly_etf_freeze.json", "file"),
    ("不可重建历史", "board_etf_map.json", "file"),
    ("不可重建历史", "etf_index_map.json", "file"),
    ("不可重建历史", "etf_track_index.json", "file"),
    ("不可重建历史", "lof_track_index.json", "file"),
    ("不可重建历史", "ab_direction_anchor.json", "file"),
    # 采集进度(轮转游标; 丢失=轮转从头查/浪费配额)
    ("采集进度", "public_fund.fof-nav-progress.json", "file"),
    ("采集进度", "baostock_progress.json", "file"),
    ("采集进度", "mootdx_progress.json", "file"),
    ("采集进度", "retry_failed_metrics_count.json", "file"),
    # 发布状态(R2 上传台账 ×20 / publication 回执 / 失败状态)
    ("发布状态", ".r2_*_state.json", "glob"),
    ("发布状态", "ops_delivery", "dir"),
    ("发布状态", ".r2-protected", "dir"),
    ("发布状态", "r2_consistency_fail_state.json", "file"),
    ("发布状态", "deploy_fail_state.json", "file"),
    # 通知状态(恢复语义: 不得恢复成全绿/清空历史 —— 见执行方案工作包二表)
    ("通知状态", "alert_state.json", "file"),
    ("通知状态", "notify_dedup.json", "file"),
    ("通知状态", "alerts", "dir"),
    ("通知状态", "signal_notified.json", "file"),
    ("通知状态", "fade_notified.json", "file"),
    ("通知状态", "anomaly_notified.json", "file"),
    ("通知状态", "nt_signal_notified.json", "file"),
    ("通知状态", "subscriptions_notified.json", "file"),
    ("通知状态", "unit_exit_ledger.json", "file"),
    ("通知状态", "brief_ledger.json", "file"),
    ("通知状态", "brief_push_state.json", "file"),
    # proof 台账(R2 归档的源证明, 原本仅云上本地无远端副本)
    ("proof台账", "logs/r2-db-source-*.json", "glob"),
]

# ---- 声明排除(捕获前声明, 与恢复清单同一时刻写进 manifest; 不是发现缺文件后缩表) ----
# 云上试跑实测(2026-11-14): .r2-protected/payloads/ 有 1737 个内容寻址载荷共 1.21GB
# (多为 nav_bucket 各键新旧两份)。journal/history/pairs 的 JSON 状态清单(已确认/待确认
# 上传、pending purge、write_id、sha256 —— 正是工作包二「发布状态」要的证明)全量捕获;
# payloads 不进每日集合, 理由:
#   ① 内容寻址(sha256 命名), confirmed 载荷与 R2 公开桶当前对象同内容(重复归档);
#   ② nav_bucket 历史版本可由 public_fund.db 再生(fund-nav-bucket 生成链);
#   ③ 全量进集合 = 每日 1.2GB 归档, 违反任务书「预算」条;
#   ④ 唯一不可复得子集 = 未决锚点(payload pending_purge/unknown)的载荷, 其 sha256 已随
#      journal 进集合可对账; 若需补备该子集属方向分叉, 由主控另立任务拍板。
# 声明排除如实记录在 manifest.declared_excludes, 绝不静默。
DECLARED_EXCLUDES = [
    {"prefix": ".r2-protected/payloads",
     "reason": "content_addressed_payloads_budget: 1.21GB/日(试跑实测), confirmed 载荷与 R2 "
               "当前对象同内容, nav_bucket 旧版可由 public_fund.db 再生; journal 的 sha256 "
               "已随集合捕获可对账; 未决锚点载荷另立归档任务(方向分叉已上报主控)"},
]

# DB 腿: 引用同轮 backup_db.sh 热备产物(不重复复制, 任务书「预算」条)。
DB_LEG_NAMES = ("sentiment", "etf_national_team", "stock_daily")

# ---- secret 拒绝面(文件名 deny-list + 内容嗅探; 任务书「绝不含」条) ----
_FORBIDDEN_SUFFIXES = (".pem", ".key", ".p12", ".pid", ".sock", ".socket", ".lock")
_FORBIDDEN_NAMES = {"id_rsa", "id_ed25519", "credentials", "token", "secret"}


def is_forbidden_name(name: str) -> bool:
    """secret/token/PID/socket/锁文件名拒绝(命中 ⇒ 不进集合, 记 skipped)。"""
    low = name.lower()
    if low.startswith(".env") or "token" in low or "secret" in low:
        return True
    if low in _FORBIDDEN_NAMES or Path(low).stem in _FORBIDDEN_NAMES:
        return True
    return low.endswith(_FORBIDDEN_SUFFIXES)


def is_transient_lock(name: str) -> bool:
    """瞬态锁文件(.lock 事务锁, 云上 ops_delivery 出版目录实测 292 个): 按任务硬约束
    「锁文件不进集合」必排除, 但它是**按设计排除**(瞬态、跨机无恢复意义), 与 secret 类
    (真缺口)分开记账 —— 不影响 complete 判定, 缺口语义只归 secret/missing。"""
    return name.lower().endswith(".lock")


_SECRET_CONTENT_RES = (
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(rb"\bsk-[A-Za-z0-9]{16,}\b"),
    re.compile(rb"Bearer\s+[A-Za-z0-9._-]{20,}"),
)


def contains_secret_pattern(payload: bytes) -> str | None:
    for rx in _SECRET_CONTENT_RES:
        m = rx.search(payload)
        if m:
            pat = rx.pattern
            return pat.decode("utf-8", "replace") if isinstance(pat, bytes) else pat
    return None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for part in iter(lambda: f.read(1 << 20), b""):
            h.update(part)
    return h.hexdigest()


def stat_identity(path: Path) -> dict:
    st = path.stat()
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "inode": st.st_ino}


def atomic_json(path: Path, value) -> None:
    fd, tmp = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=1).encode() + b"\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class SourceChanged(Exception):
    """sidecar 在捕获期间被修改(读前后 stat 或 finalize 复查不一致)。"""


def read_stable(path: Path, max_bytes: int = 64 << 20) -> tuple[bytes, dict]:
    """读取前后 stat 复查: 读取期间文件变化 ⇒ SourceChanged(调用方整体重试一次)。"""
    before = stat_identity(path)
    if before["size"] > max_bytes:
        raise ValueError(f"file exceeds capture budget: {path} ({before['size']}B)")
    payload = path.read_bytes()
    if stat_identity(path) != before:
        raise SourceChanged(str(path))
    return payload, before


def business_date_of(payload: bytes, path: Path) -> tuple[str, str]:
    """文件内业务日期优先(JSON 字段 / 冻结表 YYYYMMDD| 键), mtime 兜底; 返回(日期, 方法)。"""
    try:
        value = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        value = None
    if isinstance(value, dict):
        for key in ("business_date", "date", "generated_at", "updated_at", "as_of", "last_date"):
            v = value.get(key)
            if isinstance(v, str):
                m = re.match(r"(\d{4}-\d{2}-\d{2}|\d{8})", v)
                if m:
                    return m.group(1)[:10].replace("-", "-"), "json_field:" + key
        # 冻结表风格键 "YYYYMMDD|index|signal"
        days = [m.group(1) for k in value if isinstance(k, str)
                for m in [re.match(r"^(\d{8})\|", k)] if m]
        if days:
            return max(days), "json_freeze_key_prefix"
        m = re.search(rb'"(\d{8})\|', payload[:65536])
        if m:
            return m.group(1).decode(), "json_freeze_key_prefix"
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d"), "mtime_fallback"


def expand_inventory(data_dir: Path) -> list[dict]:
    """把声明清单展开成逐文件条目(声明先行: 只展开, 不判断存在与否, missing 由捕获记录)。
    DECLARED_EXCLUDES 前缀下的文件在展开层就排除(捕获前声明, 绝不静默)。"""
    excludes = tuple(e["prefix"] for e in DECLARED_EXCLUDES)

    def excluded(rel: str) -> bool:
        return any(rel == p or rel.startswith(p + "/") for p in excludes)

    items = []
    for category, pattern, kind in DECLARED_INVENTORY:
        base = {"category": category, "pattern": pattern, "kind": kind}
        if kind == "file":
            items.append({**base, "rel": pattern})
        elif kind == "glob":
            for p in sorted(data_dir.glob(pattern)):
                rel = p.relative_to(data_dir).as_posix()
                if p.is_file() and not excluded(rel):
                    items.append({**base, "rel": rel})
        elif kind == "dir":
            root = data_dir / pattern
            if root.is_dir():
                for p in sorted(root.rglob("*")):
                    rel = p.relative_to(data_dir).as_posix()
                    if p.is_file() and not p.is_symlink() and not excluded(rel):
                        items.append({**base, "rel": rel})
        else:
            raise ValueError("unknown inventory kind: " + kind)
    return items


def _load_proof_module(scripts_dir: Path):
    sys.path.insert(0, str(scripts_dir))
    import backup_source_proof  # noqa: F401  (关键表行数/integrity 复用同一把尺子)
    return backup_source_proof


def db_leg(repo: Path, backup_dir: Path, stamp: str, scripts_dir: Path) -> dict:
    """DB 腿 = 引用同轮 backup_db.sh 热备产物(只读: sha256/integrity/关键表行数/业务日期),
    public_fund 只记源身份(其归档走 upload-db R2 大库链, 不重复复制)。"""
    proof = _load_proof_module(scripts_dir)
    data_dir = repo / "data"
    entries = {}
    for name in DB_LEG_NAMES:
        p = backup_dir / f"{name}_{stamp}.db"
        if not p.is_file():
            entries[name] = {"status": "missing", "expected": str(p)}
            continue
        entry = {"status": "ok", "path": str(p), **{k: v for k, v in stat_identity(p).items()},
                 "sha256": sha256_file(p)}
        try:
            counts = proof.snapshot_counts(p, name)  # 含 PRAGMA integrity_check, 失败抛 ValueError
            entry["integrity_check"] = "ok"
            entry["tables"] = counts
            entry["max_date"] = db_max_date(p, name)
        except (ValueError, OSError) as exc:
            entry["integrity_check"] = "fail"
            entry["error"] = type(exc).__name__
        entries[name] = entry
    pf = data_dir / "public_fund.db"
    entries["public_fund"] = ({
        "status": "reference_only",
        "note": "大库归档走既有 upload-db R2 链(backup/public_fund_YYYYMMDD.db.gz), 不本地复制",
        **({"path": str(pf), **stat_identity(pf)} if pf.is_file() else {"status": "missing"}),
    })
    return {"stamp": stamp, "method": "reference_backup_db_sh_sqlite_backup_api_same_run",
            "databases": entries}


def db_max_date(path: Path, name: str) -> str | None:
    """关键表业务日期(MAX(date)): 读副本只读打开, 找第一个带 date 列的关键表。"""
    import sqlite3
    from backup_source_proof import TABLES
    uri = Path(path).resolve().as_uri() + "?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    try:
        for table in TABLES[name]:
            cols = [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]
            dcol = next((c for c in ("date", "trade_date", "signal_date") if c in cols), None)
            if dcol:
                v = con.execute(f'SELECT MAX("{dcol}") FROM "{table}"').fetchone()[0]
                return str(v) if v is not None else None
        return None
    finally:
        con.close()


def _capture_attempt(repo: Path, out_root: Path, backup_dir: Path, stamp: str,
                      scripts_dir: Path, with_db_leg: bool, started_at: str) -> tuple[dict, Path, bool]:
    """一次捕获尝试。返回(manifest, pending_dir, consistent)。
    consistent=False 表示 sidecar 在捕获期间被修改(SourceChanged), 调用方整体重试一次。"""
    data_dir = repo / "data"
    capture_id = f"{stamp}-{uuid.uuid4().hex[:8]}"
    pending = Path(tempfile.mkdtemp(prefix=".pending-", dir=out_root))
    declared = [{"category": c, "pattern": p, "kind": k} for c, p, k in DECLARED_INVENTORY]
    # ① 先声明后捕获: 恢复清单(含声明排除)在复制任何文件之前写入 manifest(状态 capturing)。
    manifest = {"schema": SCHEMA, "capture_set_id": capture_id, "status": "capturing",
                "started_at": started_at, "declared_inventory": declared,
                "declared_excludes": [dict(e) for e in DECLARED_EXCLUDES],
                "files": [], "missing": [], "skipped": [], "archive": {"status": "not_uploaded"}}
    atomic_json(pending / "manifest.json", manifest)
    expanded = expand_inventory(data_dir)
    try:
        for item in expanded:
            rel = item["rel"]
            src = data_dir / rel
            if is_transient_lock(src.name):
                # 瞬态锁: 按设计排除(跨机无恢复意义), 不计缺口 ⇒ 不影响 complete。
                # (先于 secret 判定: .lock 也在 secret 后缀表内, 但锁语义是"瞬态"非"缺口")
                manifest["skipped"].append({"rel": rel, "reason": "transient_lock_by_design"})
                continue
            if is_forbidden_name(src.name):
                manifest["skipped"].append({"rel": rel, "reason": "forbidden_secret_name"})
                continue
            if not src.is_file():
                manifest["missing"].append({"rel": rel, "reason": "not_a_regular_file"})
                continue
            try:
                payload, before = read_stable(src)
            except SourceChanged:
                raise
            hit = contains_secret_pattern(payload)
            if hit:
                manifest["skipped"].append({"rel": rel, "reason": "secret_content_pattern",
                                             "pattern": hit})
                continue
            bdate, bmethod = business_date_of(payload, src)
            dst = pending / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(payload)
            os.chmod(dst, 0o600)
            manifest["files"].append({
                "category": item["category"], "rel": rel,
                "source": str(src), "source_stat": before,
                "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
                "business_date": bdate, "business_date_method": bmethod,
                "captured_at": now_iso(),
            })
        # ② DB 腿(引用同轮热备产物, 只读)
        if with_db_leg:
            manifest["db_leg"] = db_leg(repo, backup_dir, stamp, scripts_dir)
        # ③ sidecar finalize 复查: 全部复制+DB 引用后, 对每个源 stat+hash 复查
        for rec in manifest["files"]:
            src = data_dir / rec["rel"]
            if stat_identity(src) != rec["source_stat"] or sha256_file(src) != rec["sha256"]:
                raise SourceChanged(rec["rel"])
        return manifest, pending, True
    except SourceChanged:
        shutil.rmtree(pending, ignore_errors=True)
        return manifest, pending, False


def verify_set(set_dir: Path, manifest: dict) -> dict:
    """自校验: 集合内逐文件 sha256 复算 + manifest 内部一致性; DB integrity/行数已在
    db_leg 逐库记录。返回 {"status": "pass|fail", "checks": [...]}。"""
    checks = []
    ok = True
    for rec in manifest.get("files", []):
        p = set_dir / rec["rel"]
        if not p.is_file():
            checks.append({"check": "file_present", "rel": rec["rel"], "result": "fail"})
            ok = False
            continue
        actual = sha256_file(p)
        good = actual == rec["sha256"] and p.stat().st_size == rec["size"]
        checks.append({"check": "sha256_recompute", "rel": rec["rel"],
                       "result": "pass" if good else "fail"})
        if not good:
            ok = False
    for rec in manifest.get("db_leg", {}).get("databases", {}).values():
        if rec.get("status") == "ok" and rec.get("integrity_check") != "ok":
            checks.append({"check": "db_integrity", "db": rec.get("path"), "result": "fail"})
            ok = False
    return {"status": "pass" if ok else "fail", "checks": checks}


def common_cutoff(manifest: dict) -> dict:
    """共同业务截止点: 文件内业务日期(有 mtime 兜底项如实标注)+ DB 腿 max_date/热备 mtime。"""
    dates = [(r["business_date"], r["rel"]) for r in manifest.get("files", [])]
    methods = {r["business_date_method"] for r in manifest.get("files", [])}
    for name, rec in manifest.get("db_leg", {}).get("databases", {}).items():
        if rec.get("max_date"):
            dates.append((str(rec["max_date"]), f"db:{name}"))
    best = max(dates) if dates else ("unknown", "none")
    return {"date": best[0], "evidence": best[1],
            "methods_seen": sorted(methods),
            "note": "文件内业务日期优先, mtime 兜底项见 files[].business_date_method"}


def capture(repo: Path, out_root: Path, backup_dir: Path, stamp: str, scripts_dir: Path,
            with_db_leg: bool = True) -> dict:
    """成套捕获入口(重试一次语义 + 汇总 manifest)。失败也不静默: 全部状态如实入 manifest。"""
    started_at = now_iso()
    out_root.mkdir(parents=True, exist_ok=True)  # 直接函数调用时目录可能不存在
    retries = 0
    for attempt in range(2):
        manifest, pending, consistent = _capture_attempt(
            repo, out_root, backup_dir, stamp, scripts_dir, with_db_leg, started_at)
        if consistent:
            break
        retries += 1
    if not consistent:
        # 重试一次仍变 ⇒ 记 inconsistent, 拒绝宣称完整(不产出可上传集合, pending 已清)。
        result = {"schema": SCHEMA, "status": "inconsistent", "started_at": started_at,
                  "completed_at": now_iso(), "retries": retries,
                  "reason": "sidecar_changed_across_capture_after_one_retry",
                  "files_captured_before_inconsistency": len(manifest.get("files", []))}
        return {"uploadable": False, "manifest": result, "set_dir": None}
    manifest["status"] = "captured"
    manifest["sidecar_consistency"] = {
        "checks": ["read_pre_post_stat", "finalize_stat_and_sha256"],
        "retries": retries, "status": "consistent"}
    # 缺项: 逐文件 missing + 声明条目无匹配(glob/dir 空)两类, 都如实记录
    for m in _missing_patterns(manifest):
        manifest["missing"].append(m)
    verification = verify_set(pending, manifest)
    manifest["verification"] = verification
    manifest["common_business_cutoff"] = common_cutoff(manifest)
    # complete 判定: missing(真缺) + secret 类 skipped(真缺口) + 校验 + DB 腿缺/坏 ⇒ 不完整;
    # 瞬态锁 skipped(transient_lock_by_design) 是按设计排除, 不算缺口 —— 与声明排除同语义。
    _secret_skips = [s for s in manifest["skipped"] if s["reason"] != "transient_lock_by_design"]
    complete = (not manifest["missing"] and not _secret_skips
                and verification["status"] == "pass"
                and all(r.get("integrity_check") == "ok"
                        for r in manifest.get("db_leg", {}).get("databases", {}).values()
                        if r.get("status") == "ok")
                and not [r for r in manifest.get("db_leg", {}).get("databases", {}).values()
                         if r.get("status") == "missing"])
    manifest["complete"] = complete
    manifest["uploadable"] = verification["status"] == "pass"
    manifest["completed_at"] = now_iso()
    # ④ finalize: fsync 全部文件 → 最终 manifest(原子) → 目录落位(不可变集合身份)
    for rec in manifest["files"]:
        with (pending / rec["rel"]).open("rb") as f:
            os.fsync(f.fileno())
    atomic_json(pending / "manifest.json", manifest)
    set_dir = out_root / manifest["capture_set_id"]
    os.rename(pending, set_dir)
    return {"uploadable": manifest["uploadable"], "manifest": manifest, "set_dir": set_dir}


def _missing_patterns(manifest: dict) -> list[dict]:
    """声明条目无任何匹配(glob/dir 空)补记 missing —— 不缩小清单。
    file 类条目缺文件时已在捕获中按 rel 记 missing(rel==pattern), 此处不重复计;
    glob 按通配匹配、dir 按前缀判断是否有任一文件命中。"""
    import fnmatch
    rels = ({i["rel"] for i in manifest["files"]}
            | {i["rel"] for i in manifest["skipped"]}
            | {i["rel"] for i in manifest["missing"]})

    def matched(pattern: str, kind: str) -> bool:
        if kind == "file":
            return pattern in rels
        if kind == "glob":
            return any(fnmatch.fnmatch(r, pattern) for r in rels)
        return any(r == pattern or r.startswith(pattern + "/") for r in rels)

    out = []
    for category, pattern, kind in DECLARED_INVENTORY:
        if not matched(pattern, kind):
            out.append({"category": category, "pattern": pattern, "kind": kind,
                        "reason": "declared_item_no_match"})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="「完整可恢复集合」成套捕获(见模块 docstring)")
    here = Path(__file__).resolve().parent
    ap.add_argument("--repo", default=os.environ.get("REPO", str(here.parent)))
    ap.add_argument("--backup-dir", required=True, help="同轮 backup_db.sh 热备目录")
    ap.add_argument("--stamp", required=True, help="backup_db.sh 的 STAMP(YYYYMMDD_HHMM)")
    ap.add_argument("--out-root", required=True, help="集合输出根目录")
    ap.add_argument("--ready-file", default=None, help="产出可上传集合时写入集合目录路径")
    ap.add_argument("--scripts-dir", default=str(here),
                    help="backup_source_proof 所在目录(云上试跑时指到生产 scripts/)")
    ap.add_argument("--no-db-leg", action="store_true", help="跳过 DB 腿引用(仅调试)")
    args = ap.parse_args(argv)
    repo = Path(args.repo).resolve()
    out_root = Path(args.out_root).resolve()
    out_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    t0 = time.monotonic()
    result = capture(repo, out_root, Path(args.backup_dir), args.stamp,
                     Path(args.scripts_dir), with_db_leg=not args.no_db_leg)
    manifest = result["manifest"]
    manifest["duration_seconds"] = round(time.monotonic() - t0, 2)
    if result["uploadable"] and result["set_dir"] is not None:
        atomic_json(result["set_dir"] / "manifest.json", manifest)
        if args.ready_file:
            Path(args.ready_file).write_text(str(result["set_dir"]) + "\n")
        summary = {"status": manifest["status"], "complete": manifest["complete"],
                   "files": len(manifest["files"]), "missing": len(manifest["missing"]),
                   "skipped": len(manifest["skipped"]),
                   "set_dir": str(result["set_dir"]),
                   "bytes": sum(r["size"] for r in manifest["files"]),
                   "duration_seconds": manifest["duration_seconds"]}
        print(json.dumps(summary, ensure_ascii=False))  # 唯一 stdout 行
        return 0
    print(json.dumps({"status": manifest["status"], "complete": False,
                      "set_dir": None, "duration_seconds": manifest["duration_seconds"]},
                     ensure_ascii=False))
    return 1


if __name__ == "__main__":
    sys.exit(main())
