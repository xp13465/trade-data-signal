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
  finalize 前对源文件 stat+hash 复查; 变化 ⇒ 整体重试一次(间隔 RETRY_INTERVAL_SECONDS,
  受 RETRY_TOTAL_WINDOW_SECONDS 总窗口上限约束, 绝不无限等), 仍变 ⇒ 记 inconsistent,
  拒绝宣称完整(uploadable=false)。判死必须点名: 重试前与失败时都输出变化/消失文件名
  (changed_files/vanished_files + 总数, MAX_REPORTED_CHANGES 截断)与采样差异
  sample_diff, stderr 行 STATE_CAPTURE_RETRY / STATE_CAPTURE_INCONSISTENT。
  写入中间件(.receipt-*/ *.tmp*)按设计排除(transient_intermediate_by_design, 宁窄勿宽),
  真实状态文件一律纳判。业务截止点字段分两个(N1, 2026-11-15 审查三轮):
  **db_cutoff = DB 各库 MAX(date) 的最小值**(所有库共同覆盖到哪一天, 恢复/接管以它为准)与
  common_business_cutoff(文件内业务日期优先、mtime 兜底、方法逐项记录; **含文件 mtime 触点,
  不等于数据业务截止日** —— 云上 alert_state/unit_exit_ledger 的 mtime 是运行日, 会把该字段
  抬成运行日)。
- **绝不含 secret/token/PID/socket/锁**: 文件名 deny-list(.env*/pem/key/p12/pid/
  sock/lock/token/credentials/id_rsa 等)+ 内容嗅探(私钥头/sk-/Bearer); 命中 ⇒ 记
  skipped/excluded, 不进集合(绝不静默)。
- **自校验**: 集合内逐文件 sha256 复算 + DB 副本 integrity_check; 失败 ⇒ 标失败,
  不冒充成功。本脚本**不发任何通知**(通知契约归 backup_db.sh 既有链, L48)。
- **独立出根**(F1, 2026-11-14 审查): 集合根 = `$BACKUP_DIR/state-capture-sets`
  (`OUT_ROOT_SUBDIR`), 与 benefit_capture 的 C4 链 `$BACKUP_DIR/capture-sets` **完全分离**
  —— C4 的 capture_admission 要求目录名是纯 UUID(ops/monitoring/benefit_capture.py:285
  owned_set_bytes / :326 capture_admission 逐条严格审计), 本脚本集合名是
  `YYYYMMDD_HHMM-<8hex>`, 同根会让 C4 链每晚 CaptureError。两开关同开互不干扰。
- **预算超限不崩溃**(F2, 2026-11-14 审查): 单文件超 MAX_FILE_BYTES(64MB) ⇒ 记
  `budget_excluded` 如实入 manifest(不缩表; complete=false 如实标注, 条目仍算「已声明未捕获」);
  磁盘写失败/读取 IO 错误 ⇒ **finally 清掉 pending 临时目录**并如实标 status=failed
  (不 traceback 崩溃、不泄漏临时目录); 文件在捕获窗内被轮转删除 ⇒ 记 missing
  (`vanished_during_capture`), 不崩溃。
- **本地保留治理**(F3): `prune_capture_sets` 参数化天数(`--prune-days`, 由
  backup_db.sh 传 RETAIN_DAYS)+ **先验后删**(所有权校验 + 已上传才删)+ **只删本任务登记目录**
  (纯 UUID / `.pending-*` / 陌生目录一律不碰)+ **绝不删最新集合与唯一可用集合**。
  上传成功前本地集合不删(R2 归档确认后才允许清理)。
- **IO 异常全程不逃逸**(审查二轮 #1): 声明 manifest 原子写 + 清单展开(`expand_inventory`
  目录遍历)也在 try 内,`succeeded=False` 提前置位 ⇒ ENOSPC/EIO 同样记 `status=failed`、
  `finally` 清 `.pending-*`、capture()/main() 不 traceback(磁盘满不得泄漏临时目录)。
- **上传标记双保险**(审查二轮 #3): 上传成功后先在集合目录原子写 `.uploaded` 标记
  (object key + sha256 + 时间); prune 以「标记存在 **OR** `manifest.archive.status ==
  uploaded`」判定已上传 —— manifest 回写失败(磁盘满等)也不会让本地集合永久判 not_uploaded
  无限堆积。
- **符号链接不静默**(审查二轮 #4): 目录声明里的 symlink 记入 `skipped`
  (`symlink_not_followed_by_design`)并写进 manifest, 不跟随进集合也不漏记账;
  与瞬态锁同属「按设计排除」, 不影响 complete 判定。
- **secret 内容嗅探面**(审查二轮 #5): 私钥头 / `sk-…` / `Bearer …` + `password=` /
  `api_key=` / AWS `AKIA…`/`SKIA…` / GCP `private_key_id` / `aws_secret_access_key`。

用法:
  python3 scripts/backup_state_capture.py --repo <repo> --backup-dir <dir> \
      --stamp <YYYYMMDD_HHMM> [--out-root <dir>] [--prune-days N] \
      [--ready-file <path>] [--scripts-dir <dir>] [--no-db-leg]
  --out-root 缺省 = <backup-dir>/state-capture-sets(与 C4 的 capture-sets 分离, F1)。
  退出码: 0=产出可上传集合(missing 如实记录不影响); 1=不完整到不可上传
  (不一致/IO 失败/自校验失败); 2=用法错误。
"""
from __future__ import annotations

import argparse
import fnmatch
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

# F1(2026-11-14 审查): 集合默认出根 = <backup_dir>/state-capture-sets, 与 benefit_capture
# C4 链的 <backup_dir>/capture-sets 完全分离(C4 的 capture_admission 只认纯 UUID 目录)。
OUT_ROOT_SUBDIR = "state-capture-sets"

# F2: 单文件捕获预算(超限记 budget_excluded, 不崩溃不缩表)。
MAX_FILE_BYTES = 64 << 20

# F3: 只删本任务登记的集合目录名(YYYYMMDD_HHMM-8hex); 陌生目录一律不碰。
CAPTURE_SET_DIR_RE = re.compile(r"^\d{8}_\d{4}-[0-9a-f]{8}$")

# 审查二轮 #3: 上传成功后写在集合目录内的标记(manifest 回写失败时的第二证据源)。
# 由 upload_r2.py cmd_upload_state_capture 调 write_upload_marker 写入, prune 读它。
UPLOAD_MARKER_NAME = ".uploaded"
UPLOAD_MARKER_SCHEMA = "trade-state-capture-upload-marker-v1"

# 按设计排除的 skipped 原因(跨机无恢复意义/不跟随), 不算缺口, 不影响 complete。
BY_DESIGN_SKIP_REASONS = frozenset({
    "transient_lock_by_design",       # .lock 事务锁(瞬态, 云上 ops_delivery 实测 292 个)
    "transient_intermediate_by_design",  # 2026-11-17: .receipt-*/ *.tmp*(写入中间件, 见下方判定函数)
    "symlink_not_followed_by_design",  # 审查二轮 #4: symlink 不跟随(防跨出集合/重复)
})

# ---- 一致性重试与诊断(2026-11-17;依据 /tmp/rca-backup-nav-20261116.md 实测) ----
# 2026-11-16 21:00 首次正式槽位: 两轮各 ~16s、**间隔 0s**, 都在 finalize 复查判死 ⇒
# inconsistent 且只打状态不打文件名(32.06s ≈ 2 × 16.0s)。根因三条:
#   ① 判据要求「整个捕获窗口零变更」, 捕获集合本身含活跃写入面;
#   ② 重试间隔 0s ⇒ 两次落在同一繁忙区间;
#   ③ expand_inventory 的 rglob("*") 不过滤写入中间件(`.receipt-*` 实测由 C4 回执链在捕获
#      目录内 mkstemp 后 unlink, 见 scripts/delivery_evidence.py:242/249/268) ⇒ 展开时有、
#      finalize 时无, 被旧判据当成「源被修改」。
# 修法(有界, 不无限等待): 正间隔重试一次 + 总窗口上限 + 失败点名 offender + 只排除明显瞬态中间件。
RETRY_INTERVAL_SECONDS = 2.0        # 重试前等待(RCA 建议 ≥2s; 0s 已实测同区间必复现)
RETRY_TOTAL_WINDOW_SECONDS = 90.0   # 总窗口上限: 两次尝试 + 间隔合计超过即放弃重试(绝不无限等)
MAX_REPORTED_CHANGES = 20           # 诊断清单截断(另带总数, 防日志被大清单刷爆)

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
    # F6: staticdata 每日灾备心跳(证明第 2/3 层灾备在跑), 88B, 纳入
    ("发布状态", "staticdata_backup_heartbeat.json", "file"),
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
    # F6 审查二轮 #2: 盘点文档(:8/:83)明确把 audit/ 列为缺口(云上实测
    # audit/frozen_missing 1,155,828B / 201 文件, signal_kelly_backtest.py:492 写入)。
    # 冻结缺失诊断取证台账不可重建(过去某次运行的输入快照), 体积 1.16MB 在每日预算内 ⇒ 纳入。
    ("proof台账", "audit/frozen_missing", "dir"),
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
    # F6(2026-11-14 审查): 清单 vs 盘点 38 项的透明度缺口 —— 以下两项**未纳入**,
    # 但捕获前显式声明并标「待主控拍板」, 不再静默缺席。
    {"prefix": "signal_kelly_trades.json",
     "reason": "F6_pending_owner_decision: 32MB 旧回测产物(2026-09-12 后未更新), 盘点标"
               "「疑似已被新链路替代, 处置需主控确认」; 是否纳入恢复清单 待主控拍板"},
    {"prefix": "daily-k.parquet",
     "reason": "F6_pending_owner_decision: 181MB 超单文件 64MB 捕获预算, 且为旧快照"
               "(2026-10-08 后未更新), 是否已被新链路替代/是否仍需备份 待主控拍板"},
    {"prefix": "sw_components.json",
     "reason": "F6_rebuildable_static_reference: 52KB 静态参考, 可从源重建, 不占恢复集"},
    {"prefix": "stock_codes.json",
     "reason": "F6_rebuildable_static_reference: 55KB 静态参考, 可从源重建, 不占恢复集"},
    {"prefix": "trade_dates.txt",
     "reason": "F6_rebuildable_static_reference: 79KB 交易日表, 可从源重建, 不占恢复集"},
    {"prefix": "baostock_logs",
     "reason": "F6_pending_owner_decision: 采集分块诊断日志(6.9MB/67 文件), 无可恢复语义; "
               "是否纳入归档 待主控拍板"},
    # F6 审查二轮 #2: 云上实测的其余三个目录逐个显式处置(不许静默缺席)。
    {"prefix": "news_digest",
     "reason": "F6_already_archived_elsewhere: 新闻按日归档(云上实测 1.5MB/65 文件)由"
               "fetch_news.py:648-688 复制到 static-site/data/news_digest, 已有 R2 `news-digest` "
               "归档通道(upload_r2.py:5092, data/news_digest 前缀) + staticdata 同步双副本;"
               " 不重复进每日集合"},
    {"prefix": "d1_metrics_evidence",
     "reason": "F6_self_expiring_diagnostics: D1 同步证据(云上实测 203KB/9 文件)是带 30 天 TTL "
               "的自愈诊断(d1_metrics_evidence.py `MAX_AGE = 30 * 86400`, 超龄自动丢弃),"
               " 无接管恢复语义; 不占恢复集"},
    {"prefix": "d1_sync_state",
     "reason": "F6_no_restore_semantics: D1 同步失败可见化状态(云上实测 0 文件/空目录),"
               " 每次同步按设计覆盖写(d1_sync_state.py:14); 恢复旧失败态反而误导排查;"
               " 不占恢复集"},
    # N2(2026-11-15 审查三轮): 盘点第 6 类 logs/ 单位里的备份过程日志 —— 既未纳入也未声明
    # 属透明度缺口。备份过程日志是每次运行的诊断输出(与 proof 台账 logs/r2-db-source-*.json
    # 不同), 无恢复语义; 历史日志按 §25 保留策略(磁盘/R2 生命周期)另管, 不进恢复集。
    {"prefix": "logs/backup_db_*.log",
     "reason": "no_restore_semantics: 备份过程日志(backup_db.sh 每日运行的诊断输出, 非状态/"
               "非证明), 无恢复语义; 历史日志按 §25 保留策略(磁盘/R2 生命周期)另管;"
               " proof 证明项已由 logs/r2-db-source-*.json 纳入捕获"},
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


def is_transient_intermediate(name: str) -> bool:
    """明显瞬态中间件判定(2026-11-17): 只排「写入过程中短暂存在、与最终产物可区分」的名字。

    依据(2026-11-16 RCA /tmp/rca-backup-nav-20261116.md §A2, 逐条实测):
      ① `.receipt-*`: C4 回执链的 mkstemp 临时件 —— scripts/delivery_evidence.py:242 建、
         :249 `os.link` 成最终 `<receipt_id>.json`、:268 unlink。它在 rglob 展开时可能刚存在、
         finalize 复查时已消失 ⇒ 旧判据误判「源被修改」。
      ② `*.tmp` / `*.tmp.<随机>` / `*.tmp-<随机>`: 原子写临时名(r2_safe_write.durable 的
         `name + '.tmp.' + uuid` 等同款)。`.tmp` 必须是独立名字段: `x.json.tmpl` 这类不匹配。
    **宁窄勿宽**: 不排除 `.r2_*_state.json`(真实发布状态)、`.r2-protected/gc-manifest.json`
    (持久引用清单)、`ops_delivery/receipts/**` 最终回执、任何 `.json/.jsonl` 产物 —— 它们
    变了就是真缺口, 必须照旧判 inconsistent 并点名。
    """
    low = name.lower()
    if low.startswith(".receipt-"):
        return True
    return bool(re.search(r"\.tmp(?:[.\-_]|$)", low))


_SECRET_CONTENT_RES = (
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(rb"\bsk-[A-Za-z0-9]{16,}\b"),
    re.compile(rb"Bearer\s+[A-Za-z0-9._-]{20,}"),
    # 审查二轮 #5: 键值型凭据(password=/api_key=)与云厂商 key 形态
    # (JSON 风格 `"api_key": "…"` 允许键名后带引号, shell 风格 `api_key=…` 也覆盖)。
    re.compile(rb"(?i)\b(?:password|passwd|pwd)[\"']?\s*[:=]\s*[\"']?[^\s\"',}]{4,}"),
    re.compile(rb"(?i)\bapi[_-]?key[\"']?\s*[:=]\s*[\"']?[^\s\"',}]{8,}"),
    re.compile(rb"(?i)\baws_secret_access_key[\"']?\s*[:=]\s*[\"']?[^\s\"',}]{8,}"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),          # AWS access key id
    re.compile(rb"\bSKIA[0-9A-Z]{16}\b"),          # AWS 旧式 secret(审查点名形态)
    re.compile(rb"\"private_key_id\"\s*:\s*\"[0-9a-f]{20,64}\""),  # GCP service account key
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
    """sidecar 在捕获期间被修改(读前后 stat 或 finalize 复查不一致)。

    2026-11-17: 带上 offender 清单(changed/vanished 的 rel), 让失败可逐位定位(旧实现只抛
    第一个 rel、且最终输出只打状态)。"""
    def __init__(self, rel, changed=None, vanished=None):
        super().__init__(rel)
        self.rel = rel
        # 显式名单优先: 传空列表([])表示「这一类一个都没有」, 不得回退成 [rel](否则只有 vanished
        # 的场景会被错记成 changed, 诊断字段张冠李戴)。
        self.changed = [rel] if changed is None else list(changed)
        self.vanished = [] if vanished is None else list(vanished)


class CaptureBudgetExceeded(Exception):
    """单文件超捕获预算(F2): 调用方记 budget_excluded, 不崩溃、不缩表。"""

    def __init__(self, path: Path, size: int, limit: int):
        super().__init__(f"file exceeds capture budget: {path} ({size}B > {limit}B)")
        self.path = path
        self.size = size
        self.limit = limit


def read_stable(path: Path, max_bytes: int | None = None) -> tuple[bytes, dict]:
    """读取前后 stat 复查: 读取期间文件变化 ⇒ SourceChanged(调用方整体重试一次)。
    超预算 ⇒ CaptureBudgetExceeded(调用方记 budget_excluded)。max_bytes 默认取模块常量
    MAX_FILE_BYTES(运行期读取, 便于测试收紧预算); 文件已消失 ⇒ FileNotFoundError
    (调用方记 missing, 不崩溃)。"""
    limit = MAX_FILE_BYTES if max_bytes is None else max_bytes
    before = stat_identity(path)
    if before["size"] > limit:
        raise CaptureBudgetExceeded(path, before["size"], limit)
    payload = path.read_bytes()
    if stat_identity(path) != before:
        raise SourceChanged(str(path))
    return payload, before


def default_out_root(backup_dir: Path) -> Path:
    """集合默认出根(F1): 独立于 C4 的 capture-sets, 两开关同开互不干扰。"""
    return Path(backup_dir) / OUT_ROOT_SUBDIR


def write_bytes_0600(path: Path, payload: bytes) -> None:
    """写入集合内副本(权限 0600)。独立成函数便于 F2 磁盘满用例注入 OSError。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    os.chmod(path, 0o600)


_DATE_VALUE_RE = re.compile(r"^(\d{4})-?(\d{2})-?(\d{2})")


def normalize_business_date(value) -> str | None:
    """业务日期统一成 ISO `YYYY-MM-DD`(F5): 8 位 `YYYYMMDD` 与 10 位 `YYYY-MM-DD`
    混排时直接字典序比较会让 8 位恒赢('-'(45) < 数字), 必须归一后比较。"""
    if value is None:
        return None
    m = _DATE_VALUE_RE.match(str(value).strip())
    if not m:
        return None
    y, mo, d = m.groups()
    if not (1 <= int(mo) <= 12 and 1 <= int(d) <= 31):
        return None
    return f"{y}-{mo}-{d}"


def business_date_of(payload: bytes, path: Path) -> tuple[str, str]:
    """文件内业务日期优先(JSON 字段 / 冻结表 YYYYMMDD| 键), mtime 兜底; 返回(归一化日期, 方法)。"""
    try:
        value = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        value = None
    if isinstance(value, dict):
        for key in ("business_date", "date", "generated_at", "updated_at", "as_of", "last_date"):
            v = value.get(key)
            if isinstance(v, str):
                nd = normalize_business_date(v)
                if nd:
                    return nd, "json_field:" + key
        # 冻结表风格键 "YYYYMMDD|index|signal"
        days = [m.group(1) for k in value if isinstance(k, str)
                for m in [re.match(r"^(\d{8})\|", k)] if m]
        if days:
            norm = [nd for nd in (normalize_business_date(d) for d in days) if nd]
            if norm:
                return max(norm), "json_freeze_key_prefix"
        m = re.search(rb'"(\d{8})\|', payload[:65536])
        if m:
            nd = normalize_business_date(m.group(1).decode())
            if nd:
                return nd, "json_freeze_key_prefix"
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d"), "mtime_fallback"


def is_declared_excluded(rel: str) -> bool:
    """rel 是否落在 DECLARED_EXCLUDES 声明面内(捕获前声明, 非事后缩表)。

    前缀项按「完全相同 或 下钻子路径」匹配; 含通配符的项(如 `logs/backup_db_*.log`,
    N2 2026-11-15)按 fnmatch 匹配 —— 声明项即真生效, 不做「只写不生效」的空声明。
    """
    for entry in DECLARED_EXCLUDES:
        p = entry["prefix"]
        if rel == p or rel.startswith(p + "/"):
            return True
        if any(ch in p for ch in "*?[") and fnmatch.fnmatch(rel, p):
            return True
    return False


def expand_inventory(data_dir: Path) -> list[dict]:
    """把声明清单展开成逐文件条目(声明先行: 只展开, 不判断存在与否, missing 由捕获记录)。
    DECLARED_EXCLUDES 前缀下的文件在展开层就排除(捕获前声明, 绝不静默)。

    审查二轮 #4: 符号链接也展开成条目(is_symlink=True), 由捕获层记 `skipped`
    (`symlink_not_followed_by_design`)——不跟随进集合, 但绝不静默跳过不记账。"""
    def excluded(rel: str) -> bool:
        return is_declared_excluded(rel)

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
                    if p.is_symlink():
                        if not excluded(rel):
                            items.append({**base, "rel": rel, "is_symlink": True})
                        continue
                    if p.is_file() and not excluded(rel):
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
                      scripts_dir: Path, with_db_leg: bool, started_at: str) -> tuple[dict, Path, str, dict]:
    """一次捕获尝试。返回(manifest, pending_dir, outcome, diagnosis)。

    outcome: "consistent"=成功 / "inconsistent"=sidecar 捕获期间被修改(调用方整体
    重试一次) / "io_failed"=读取或写入 IO 失败(磁盘满等, 不重试、不崩溃, pending 已清)。
    单文件超预算记 budget_excluded 后继续; 文件在窗内消失记 missing。
    diagnosis: 本轮采样快照(sample: rel→stat_identity)+ 不一致时的 offender 清单
    (changed/vanished, 各截断到 MAX_REPORTED_CHANGES 并带总数), 供重试前后日志点名。"""
    data_dir = repo / "data"
    capture_id = f"{stamp}-{uuid.uuid4().hex[:8]}"
    pending = Path(tempfile.mkdtemp(prefix=".pending-", dir=out_root))
    declared = [{"category": c, "pattern": p, "kind": k} for c, p, k in DECLARED_INVENTORY]
    # ① 先声明后捕获: 恢复清单(含声明排除)在复制任何文件之前写入 manifest(状态 capturing)。
    manifest = {"schema": SCHEMA, "capture_set_id": capture_id, "status": "capturing",
                "started_at": started_at, "declared_inventory": declared,
                "declared_excludes": [dict(e) for e in DECLARED_EXCLUDES],
                "files": [], "missing": [], "skipped": [], "budget_excluded": [],
                "archive": {"status": "not_uploaded"}}
    # 本轮采样快照(展开时逐 rel stat): 仅用于「上一轮 vs 本轮」差异诊断, 不参与一致性判定。
    sample = {}
    diagnosis = {"changed": [], "changed_total": 0, "vanished": [], "vanished_total": 0,
                 "sample": sample}
    succeeded = False
    # 审查二轮 #1: 声明写入 + 清单展开也必须在 try 内 —— ENOSPC/EIO 不得逃出本函数
    # (旧实现这两步在 try 之前 ⇒ traceback + .pending-* 泄漏)。succeeded 已提前置 False,
    # 任何异常路径都会走 finally 清 pending。
    phase = "declare_or_expand"
    try:
        atomic_json(pending / "manifest.json", manifest)
        expanded = expand_inventory(data_dir)
        phase = "read_or_write"
        for item in expanded:
            rel = item["rel"]
            src = data_dir / rel
            try:
                sample[rel] = stat_identity(src)
            except OSError:
                sample[rel] = None   # 展开后即消失: 由下方 missing/vanished 语义处理
            if item.get("is_symlink"):
                # 审查二轮 #4: 不跟随符号链接(防跨出集合/重复), 但必须记账不静默。
                manifest["skipped"].append(
                    {"rel": rel, "reason": "symlink_not_followed_by_design"})
                continue
            if is_transient_intermediate(src.name):
                # 写入中间件(.receipt-* / *.tmp*): 展开时有、finalize 时无属正常; 不进集合、不参与
                # 一致性判定, 但按设计排除如实记账(2026-11-17, 见 is_transient_intermediate)。
                manifest["skipped"].append(
                    {"rel": rel, "reason": "transient_intermediate_by_design"})
                continue
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
                # 读前后 stat 不一致 ⇒ 点名本次 rel(诊断清单要的是集合内相对路径, 不是绝对路径)。
                raise SourceChanged(rel)
            except CaptureBudgetExceeded as exc:
                # F2: 超预算 ⇒ 如实记账(不缩表不崩溃), complete 由 budget_excluded 推出 false。
                manifest["budget_excluded"].append({
                    "rel": rel, "reason": "file_exceeds_capture_budget",
                    "size": exc.size, "limit": exc.limit})
                continue
            except FileNotFoundError:
                # 展开后在读取前被轮转删除: 记 missing(与 not_a_regular_file 同语义)。
                manifest["missing"].append({"rel": rel, "reason": "vanished_during_capture"})
                continue
            hit = contains_secret_pattern(payload)
            if hit:
                manifest["skipped"].append({"rel": rel, "reason": "secret_content_pattern",
                                             "pattern": hit})
                continue
            bdate, bmethod = business_date_of(payload, src)
            write_bytes_0600(pending / rel, payload)
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
        # ③ sidecar finalize 复查: 全部复制+DB 引用后, 对每个源 stat+hash 复查。
        # 2026-11-17: 不再「首个变化即抛」——枚举全部 offender(旧实现丢掉清单, 失败无法定位)。
        changed, vanished = [], []
        for rec in manifest["files"]:
            src = data_dir / rec["rel"]
            try:
                cur = stat_identity(src)
            except FileNotFoundError:
                vanished.append(rec["rel"])   # 读后轮转删除 ⇒ 与「被修改」同语义(整体重试)
                continue
            if cur != rec["source_stat"] or sha256_file(src) != rec["sha256"]:
                changed.append(rec["rel"])
        if changed or vanished:
            raise SourceChanged((changed + vanished)[0], changed=changed, vanished=vanished)
        succeeded = True
        return manifest, pending, "consistent", diagnosis
    except SourceChanged as exc:
        diagnosis.update({
            "changed": exc.changed[:MAX_REPORTED_CHANGES],
            "changed_total": len(set(exc.changed)),
            "vanished": exc.vanished[:MAX_REPORTED_CHANGES],
            "vanished_total": len(exc.vanished)})
        return manifest, pending, "inconsistent", diagnosis
    except OSError as exc:
        # F2: 读/写 IO 失败(磁盘满、权限等) ⇒ 不重试、不 traceback、不泄漏 pending;
        # 如实记 status=failed(调用方据此产出 failed manifest, 不冒充成功)。
        manifest["error"] = {
            "type": type(exc).__name__, "detail": str(exc), "phase": phase}
        return manifest, pending, "io_failed", diagnosis
    finally:
        # 非 consistent 路径一律清掉 pending 临时目录(源变化/IO 失败), 防堆积泄漏。
        if not succeeded:
            shutil.rmtree(pending, ignore_errors=True)


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
    """共同业务截止点(原义保留): 文件内业务日期(有 mtime 兜底项如实标注)+ DB 腿 max_date。

    ⚠️ N1(2026-11-15 审查三轮): 本字段**含文件 mtime 触点**(云上 alert_state/unit_exit_ledger
    的 mtime 是运行日), 因此**不等于数据业务截止日**; 它回答的是「集合里最新触点」。恢复/
    接管请以 `db_cutoff`(DB 各库 MAX(date) 的最小值)为准, 见 docs/backup-restore.md §九。
    """
    dates = [(r["business_date"], r["rel"]) for r in manifest.get("files", [])]
    methods = {r["business_date_method"] for r in manifest.get("files", [])}
    for name, rec in manifest.get("db_leg", {}).get("databases", {}).items():
        # F5: DB MAX(date) 可能是 8 位 YYYYMMDD, sidecar 已归一成 ISO; 混格式直接字典序
        # 会让 8 位恒赢('-'(45) < 数字) ⇒ 必须同一口径(ISO)后再比。
        nd = normalize_business_date(rec.get("max_date"))
        if nd:
            dates.append((nd, f"db:{name}"))
    best = max(dates) if dates else ("unknown", "none")
    return {"date": best[0], "evidence": best[1],
            "methods_seen": sorted(methods),
            "note": "文件内业务日期优先, mtime 兜底项见 files[].business_date_method; "
                    "含文件 mtime 触点, 不等于数据业务截止日 —— 接管以 db_cutoff 为准"}


def db_cutoff(manifest: dict) -> dict:
    """数据业务截止点 = DB 各库 MAX(date) 的**最小值**(「所有库共同覆盖到哪一天」)。

    N1(2026-11-15 审查三轮): common_business_cutoff 会被 sidecar 的 mtime 兜底(运行日)抬高,
    不能回答「数据到哪天了」。本字段只取 DB 腿(sentiment/etf_national_team/stock_daily)
    的归一化 MAX(date), 取最小; 任一库读不到 ⇒ all_databases_covered=false(不冒充全覆盖)。
    DB 腿缺失(调试 --no-db-leg)或全部无 date ⇒ date=None, 不得据此宣称可接管。
    """
    dbs = manifest.get("db_leg", {}).get("databases", {})
    per_db = {}
    for name in DB_LEG_NAMES:
        rec = dbs.get(name) or {}
        per_db[name] = (normalize_business_date(rec.get("max_date"))
                        if rec.get("status") == "ok" else None)
    covered = bool(dbs) and all(per_db.values())
    known = sorted((d, name) for name, d in per_db.items() if d)
    base = {"databases": per_db, "all_databases_covered": covered,
            "note": "DB 各库 MAX(date) 的最小值(所有库共同覆盖到该日); 不含文件 mtime 触点"}
    if not known:
        return {"date": None, "evidence": "none", **base}
    return {"date": known[0][0], "evidence": f"db:{known[0][1]}", **base}


def _sample_diff(prev: dict | None, cur: dict | None) -> dict:
    """两轮采样快照差异(rel 级): added / removed / changed, 各截断并带总数(诊断用)。"""
    prev, cur = prev or {}, cur or {}
    added = [rel for rel in cur if rel not in prev]
    removed = [rel for rel in prev if rel not in cur]
    changed = [rel for rel in cur if rel in prev and prev[rel] != cur[rel]]
    return {"added": added[:MAX_REPORTED_CHANGES], "added_total": len(added),
            "removed": removed[:MAX_REPORTED_CHANGES], "removed_total": len(removed),
            "changed": changed[:MAX_REPORTED_CHANGES], "changed_total": len(changed)}


def capture(repo: Path, out_root: Path, backup_dir: Path, stamp: str, scripts_dir: Path,
            with_db_leg: bool = True) -> dict:
    """成套捕获入口(重试一次语义 + 汇总 manifest)。失败也不静默: 全部状态如实入 manifest。

    2026-11-17: 重试前等待 RETRY_INTERVAL_SECONDS(正间隔, 不再 0s), 总窗口受
    RETRY_TOTAL_WINDOW_SECONDS 上限约束(超出即放弃重试, 绝不无限等); 失败时点名 offender。
    """
    started_at = now_iso()
    out_root.mkdir(parents=True, exist_ok=True)  # 直接函数调用时目录可能不存在
    deadline = time.monotonic() + RETRY_TOTAL_WINDOW_SECONDS
    retries = 0
    outcome = "io_failed"
    window_exhausted = False
    diagnosis = {"changed": [], "changed_total": 0, "vanished": [], "vanished_total": 0}
    samples = []
    for attempt in range(2):
        try:
            manifest, pending, outcome, diagnosis = _capture_attempt(
                repo, out_root, backup_dir, stamp, scripts_dir, with_db_leg, started_at)
        except OSError as exc:
            # 审查二轮 #1 兜底: mkdtemp/out_root 创建失败时 pending 还不存在(无目录可清),
            # 同样如实落 status=failed, 绝不 traceback 到 main()/backup_db.sh。
            manifest = {"files": [], "error": {"type": type(exc).__name__,
                                               "detail": str(exc),
                                               "phase": "create_pending"}}
            outcome = "io_failed"
        samples.append(diagnosis.get("sample") or {})
        if outcome == "consistent":
            break
        if outcome == "io_failed":
            break  # F2: IO 失败不重试(磁盘满重试无意义), 直接如实失败
        if attempt == 0:
            # 重试前把本轮 offender 清单 + 采样规模打到 stderr(日志可逐位定位;
            # stdout 只保留 main() 的唯一 JSON 摘要行)。
            print("STATE_CAPTURE_RETRY: " + json.dumps({
                "attempt": attempt + 1, "outcome": outcome,
                "retry_in_seconds": round(RETRY_INTERVAL_SECONDS, 3),
                "sampled_files": len(diagnosis.get("sample") or {}),
                "changed": diagnosis["changed"], "changed_total": diagnosis["changed_total"],
                "vanished": diagnosis["vanished"], "vanished_total": diagnosis["vanished_total"]},
                ensure_ascii=False), file=sys.stderr)
            if time.monotonic() + RETRY_INTERVAL_SECONDS > deadline:
                window_exhausted = True   # 有界: 总窗口上限已到, 不再等待/重试
                break
            retries += 1                  # 只有真进入下一轮才计一次重试(窗口耗尽记 0, 不虚记)
            time.sleep(RETRY_INTERVAL_SECONDS)
    if outcome == "io_failed":
        # F2: 读/写 IO 失败 ⇒ 如实标 failed(不崩溃、pending 已清), 不冒充成功。
        result = {"schema": SCHEMA, "status": "failed", "started_at": started_at,
                  "completed_at": now_iso(), "retries": retries,
                  "reason": "io_failure_during_capture",
                  "error": manifest.get("error", {}),
                  "files_captured_before_failure": len(manifest.get("files", []))}
        return {"uploadable": False, "manifest": result, "set_dir": None}
    if outcome == "inconsistent":
        # 重试一次仍变 ⇒ 记 inconsistent, 拒绝宣称完整(不产出可上传集合, pending 已清)。
        # 2026-11-17: **必须带文件名失败**(旧实现只打状态, 无法逐位定位是哪个文件在变);
        # 另附两轮采样快照差异, 便于下次直接看出是新增/删除/被改写。
        diff = _sample_diff(samples[0] if samples else None, samples[-1] if samples else None)
        result = {"schema": SCHEMA, "status": "inconsistent", "started_at": started_at,
                  "completed_at": now_iso(), "retries": retries,
                  "reason": "sidecar_changed_across_capture_after_one_retry",
                  "changed_files": diagnosis["changed"],
                  "changed_total": diagnosis["changed_total"],
                  "vanished_files": diagnosis["vanished"],
                  "vanished_total": diagnosis["vanished_total"],
                  "sample_diff": diff,
                  "retry_window_exhausted": window_exhausted,
                  "files_captured_before_inconsistency": len(manifest.get("files", []))}
        print("STATE_CAPTURE_INCONSISTENT: " + json.dumps({
            "changed_files": result["changed_files"], "changed_total": result["changed_total"],
            "vanished_files": result["vanished_files"],
            "vanished_total": result["vanished_total"], "sample_diff": diff},
            ensure_ascii=False), file=sys.stderr)
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
    # N1: 两个截止点各司其职 —— db_cutoff=DB 各库共同覆盖日(接管口径),
    # common_business_cutoff=集合最新触点(含 mtime, 见其 note 与 docs §九)。
    manifest["db_cutoff"] = db_cutoff(manifest)
    manifest["common_business_cutoff"] = common_cutoff(manifest)
    # 判定: missing(真缺) + secret 类 skipped(真缺口) + budget_excluded(F2 已声明
    # 未捕获) + 校验 + DB 腿缺/坏 ⇒ 不完整; 按设计排除的 skipped(瞬态锁/symlink, 见
    # BY_DESIGN_SKIP_REASONS)不算缺口 —— 与声明排除同语义。
    _secret_skips = [s for s in manifest["skipped"]
                     if s["reason"] not in BY_DESIGN_SKIP_REASONS]
    complete = (not manifest["missing"] and not _secret_skips
                and not manifest["budget_excluded"]
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
    try:
        for rec in manifest["files"]:
            with (pending / rec["rel"]).open("rb") as f:
                os.fsync(f.fileno())
        atomic_json(pending / "manifest.json", manifest)
        set_dir = out_root / manifest["capture_set_id"]
        os.rename(pending, set_dir)
    except OSError as exc:
        # F2: finalize 阶段写盘失败(磁盘满等) ⇒ 清 pending + 如实 failed, 不崩溃不泄漏。
        shutil.rmtree(pending, ignore_errors=True)
        result = {"schema": SCHEMA, "status": "failed", "started_at": started_at,
                  "completed_at": now_iso(), "retries": retries,
                  "reason": "io_failure_during_finalize",
                  "error": {"type": type(exc).__name__, "detail": str(exc),
                            "phase": "finalize"},
                  "files_captured_before_failure": len(manifest.get("files", []))}
        return {"uploadable": False, "manifest": result, "set_dir": None}
    return {"uploadable": manifest["uploadable"], "manifest": manifest, "set_dir": set_dir}


def _missing_patterns(manifest: dict) -> list[dict]:
    """声明条目无任何匹配(glob/dir 空)补记 missing —— 不缩小清单。
    file 类条目缺文件时已在捕获中按 rel 记 missing(rel==pattern), 此处不重复计;
    glob 按通配匹配、dir 按前缀判断是否有任一文件命中。"""
    import fnmatch
    # F2: budget_excluded 也属于「声明条目有匹配、只是未捕获」, 不能重复记成 no_match
    # (否则预算超限会被 missing 掩盖, complete 判定失去独立锚)。
    rels = ({i["rel"] for i in manifest["files"]}
            | {i["rel"] for i in manifest["skipped"]}
            | {i["rel"] for i in manifest.get("budget_excluded", [])}
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


def write_upload_marker(set_dir: Path, *, object_key: str, bucket: str,
                        gzip_sha256: str, gzip_size: int,
                        run_id: str | None = None) -> Path:
    """上传成功后写集合内 `.uploaded` 标记(审查二轮 #3)。

    manifest 回写失败(磁盘满等)时, 这个标记仍能让 prune 认出「已上传」——
    否则集合永远判 not_uploaded 无限堆积。原子写(atomic_json: tmp + fsync + replace)。
    """
    path = Path(set_dir) / UPLOAD_MARKER_NAME
    atomic_json(path, {
        "schema": UPLOAD_MARKER_SCHEMA,
        "object_key": object_key,
        "bucket": bucket,
        "gzip_sha256": gzip_sha256,
        "gzip_size": gzip_size,
        "run_id": run_id,
        "uploaded_at": now_iso(),
    })
    return path


def upload_evidence(set_dir: Path, manifest: dict) -> tuple[bool, dict]:
    """已上传判据(审查二轮 #3)= `.uploaded` 标记存在 **OR** manifest.archive.status==uploaded。

    返回(是否已上传, 归档信息)。标记存在但内容不可解析时仍认「已上传」(原子写保证
    「要么完整要么不存在」; 存在即上传成功过), 只是归档信息退回 manifest。
    """
    archive = manifest.get("archive") or {}
    marker_path = Path(set_dir) / UPLOAD_MARKER_NAME
    if marker_path.is_file():
        try:
            marker = json.loads(marker_path.read_text())
        except (OSError, ValueError):
            marker = {}
        return True, {**archive, **{k: v for k, v in marker.items() if k != "schema"}}
    return archive.get("status") == "uploaded", archive


def prune_capture_sets(out_root: Path, retain_days: int,
                       now: float | None = None) -> list[dict]:
    """F3 本地集合滚动清理(参数化保留天数 + 先验后删 + 只删本任务登记目录)。

    安全护栏(任一不满足 ⇒ 保留, 记 reason):
    - 目录名必须匹配 `YYYYMMDD_HHMM-8hex`(纯 UUID / `.pending-*` / 陌生目录一律不碰);
    - 目录必须非 symlink, 且 manifest.json 可读、`schema == SCHEMA`;
    - 已上传(R2 归档已确认)才允许删 —— 判据 = 集合内 `.uploaded` 标记存在 **OR**
      `manifest.archive.status == "uploaded"`(审查二轮 #3: manifest 回写失败但标记成功
      也算已上传, 防永久堆积); 未上传/上传失败的集合永不删(任务书「上传成功前不得删除
      本地集合」);
    - 不删最新集合、也不删唯一一个已上传集合(始终留至少一个可恢复点)。

    返回逐目录处置记录; 清理本身失败不抛出(不得影响备份主链)。
    """
    results: list[dict] = []
    if not out_root.is_dir() or retain_days <= 0:
        return results
    now_ts = time.time() if now is None else now
    cutoff = now_ts - retain_days * 86400
    owned = []
    for entry in sorted(out_root.iterdir(), key=lambda p: p.name):
        if not CAPTURE_SET_DIR_RE.match(entry.name):
            continue
        if entry.is_symlink() or not entry.is_dir():
            results.append({"name": entry.name, "action": "keep", "reason": "not_owned_dir"})
            continue
        try:
            manifest = json.loads((entry / "manifest.json").read_text())
        except (OSError, ValueError):
            results.append({"name": entry.name, "action": "keep", "reason": "manifest_unreadable"})
            continue
        if manifest.get("schema") != SCHEMA:
            results.append({"name": entry.name, "action": "keep", "reason": "foreign_schema"})
            continue
        owned.append((entry, manifest))
    evidence = {p.name: upload_evidence(p, m) for p, m in owned}
    uploaded = [(p, m) for p, m in owned if evidence[p.name][0]]
    keep_names = set()
    if owned:
        keep_names.add(max(owned, key=lambda pm: pm[0].name)[0].name)  # 最新集合
    if len(uploaded) <= 1 and uploaded:
        keep_names.add(uploaded[0][0].name)  # 唯一可恢复点
    for entry, manifest in owned:
        name = entry.name
        if name in keep_names:
            results.append({"name": name, "action": "keep", "reason": "newest_or_only_uploaded"})
            continue
        if not evidence[name][0]:
            results.append({"name": name, "action": "keep", "reason": "not_uploaded"})
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            results.append({"name": name, "action": "keep", "reason": "stat_failed"})
            continue
        if mtime > cutoff:
            results.append({"name": name, "action": "keep", "reason": "within_retain_days"})
            continue
        shutil.rmtree(entry, ignore_errors=True)
        results.append({"name": name,
                        "action": "deleted" if not entry.exists() else "delete_failed",
                        "reason": "older_than_retain_days",
                        "archive_key": evidence[name][1].get("object_key")
                        or evidence[name][1].get("key")})
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="「完整可恢复集合」成套捕获(见模块 docstring)")
    here = Path(__file__).resolve().parent
    ap.add_argument("--repo", default=os.environ.get("REPO", str(here.parent)))
    ap.add_argument("--backup-dir", required=True, help="同轮 backup_db.sh 热备目录")
    ap.add_argument("--stamp", required=True, help="backup_db.sh 的 STAMP(YYYYMMDD_HHMM)")
    ap.add_argument("--out-root", default=None,
                    help=f"集合输出根目录(缺省 <backup-dir>/{OUT_ROOT_SUBDIR}, F1 独立出根)")
    ap.add_argument("--prune-days", type=int, default=0,
                    help="F3 本地集合保留天数(<=0 不清理; backup_db.sh 传 RETAIN_DAYS; "
                         "只删已上传且超期的本任务集合)")
    ap.add_argument("--ready-file", default=None, help="产出可上传集合时写入集合目录路径")
    ap.add_argument("--scripts-dir", default=str(here),
                    help="backup_source_proof 所在目录(云上试跑时指到生产 scripts/)")
    ap.add_argument("--no-db-leg", action="store_true", help="跳过 DB 腿引用(仅调试)")
    args = ap.parse_args(argv)
    repo = Path(args.repo).resolve()
    backup_dir = Path(args.backup_dir).resolve()
    out_root = Path(args.out_root).resolve() if args.out_root else default_out_root(backup_dir)
    try:
        out_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        # 审查二轮 #1: 出根目录都建不出来(磁盘满/权限)同样如实失败, 不 traceback。
        print(json.dumps({"status": "failed", "complete": False, "set_dir": None,
                          "reason": "io_failure_during_out_root_create",
                          "error": {"type": type(exc).__name__, "detail": str(exc)}},
                         ensure_ascii=False))
        return 1
    # F3: 先清理超期的「已上传」旧集合(当前新集合 manifest.archive=not_uploaded, 不会被删)。
    # 清理属旁路, 任何异常都不得影响捕获主链。
    try:
        pruned = prune_capture_sets(out_root, args.prune_days)
    except OSError:
        pruned = []
    t0 = time.monotonic()
    result = capture(repo, out_root, backup_dir, args.stamp,
                     Path(args.scripts_dir), with_db_leg=not args.no_db_leg)
    manifest = result["manifest"]
    manifest["duration_seconds"] = round(time.monotonic() - t0, 2)
    if result["uploadable"] and result["set_dir"] is not None:
        try:
            atomic_json(result["set_dir"] / "manifest.json", manifest)
            if args.ready_file:
                Path(args.ready_file).write_text(str(result["set_dir"]) + "\n")
        except OSError as exc:
            # 审查二轮 #1: 收尾写 manifest / ready-file 时磁盘满同样不 traceback。
            print(json.dumps({"status": "failed", "complete": False,
                              "set_dir": str(result["set_dir"]),
                              "reason": "io_failure_during_main_finalize",
                              "error": {"type": type(exc).__name__, "detail": str(exc)}},
                             ensure_ascii=False))
            return 1
        summary = {"status": manifest["status"], "complete": manifest["complete"],
                   "files": len(manifest["files"]), "missing": len(manifest["missing"]),
                   "skipped": len(manifest["skipped"]),
                   "budget_excluded": len(manifest.get("budget_excluded", [])),
                   "set_dir": str(result["set_dir"]),
                   "bytes": sum(r["size"] for r in manifest["files"]),
                   "pruned": sum(1 for p in pruned if p["action"] == "deleted"),
                   "duration_seconds": manifest["duration_seconds"]}
        print(json.dumps(summary, ensure_ascii=False))  # 唯一 stdout 行
        return 0
    # 2026-11-17: 失败行带 offender 文件名(旧实现只有 status/set_dir/duration, 无法定位)。
    failure = {"status": manifest["status"], "complete": False,
               "set_dir": None, "duration_seconds": manifest["duration_seconds"]}
    for key in ("changed_files", "changed_total", "vanished_files", "vanished_total",
                "sample_diff", "retry_window_exhausted", "reason"):
        if key in manifest:
            failure[key] = manifest[key]
    print(json.dumps(failure, ensure_ascii=False))  # 唯一 stdout 行
    return 1


if __name__ == "__main__":
    sys.exit(main())
