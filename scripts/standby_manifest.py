#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""standby_manifest.py — 备用机同步清单(standby/manifest_latest.json)生产者(G3/G4, 2026-11-15)。

背景(实测 /tmp/standby-d-report.md): standby_sync.py 只认 schema_version=1 契约的 manifest,
而状态集捕获产物用另一套字段(schema / capture_set_id / files[].rel / 未压缩 sha256 / 无顶层
business_date), 且 R2 上没有任何生产者 ⇒ 备用机首次同步拿到 404 NoSuchKey。本模块把
「同一次备份轮已上传的产物」映射成 standby_sync 契约的清单, 由既有上传链调用
(backup_db.sh → upload_r2.py standby-manifest → 本模块, upload-db 之后), 不新开进程/定时任务。

设计要点(逐条对应任务书 G3/G4):
- `business_date` **只取捕获集合 manifest 的 `db_cutoff.date`**(N1 口径: DB 各库 MAX(date)
  的最小值 = 所有库共同覆盖到哪天); `common_business_cutoff`(含文件 mtime 触点, 可能是运行日)
  不得当业务日期。`all_databases_covered=false` / date 缺失 ⇒ 拒绝写(不宣称可接管)。
- 不编造字段: DB 对象的 `size`/`sha256_gz`/`sha256_uncompressed` 全部取自同轮 upload-db
  receipt 里对**实际上传字节**算出的 gzip/raw 指纹; 状态集 tar.gz 的 gzip sha/size 与解压体
  sha/size 取自 upload-state-capture receipt。任一必需字段缺失/形状非法 ⇒ 拒绝写(旧清单保留)。
- 对象级 `business_date` 一律**省略**(standby_sync 缺省继承集合级日期): 各 DB 的 MAX(date)
  可能晚于 db_cutoff, 显式写会误报「该对象业务日期 == 集合日期」; 省略 = 只声明「覆盖到
  集合共同截止点」这层真实语义。
- `public_fund` 显式排除并写明理由(其归档走独立大库流式链, db_cutoff 口径不含它; 见
  docs/backup-restore.md §九), 记在顶层 `excluded`(standby_sync 忽略未知字段)。
- 发布走「临时 key → 同桶 CopyObject 覆盖 standby/manifest_latest.json → 删临时 key」:
  任何一步失败都不碰 latest(上一份可用清单保留); 写前用 standby_sync.normalize_manifest
  逐项校验契约(单一事实源, 防生产者自说自话)。
- 默认关闭: 未设 `STANDBY_MANIFEST_ENABLED=1` 时零 R2 接触、零调用; 不改变既有上传链
  默认行为与退出码。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import uuid
from pathlib import Path

LATEST_KEY = "standby/manifest_latest.json"
TMP_PREFIX = "standby/manifest_tmp_"      # 临时对象前缀(发布成功后删除)
SCHEMA_VERSION = 1
CAPTURE_SCHEMA = "trade-state-capture-v1"
# 恢复范围必需的小库(db_cutoff 也由这几个库推出, 见 backup_state_capture.db_cutoff)。
REQUIRED_DBS = ("sentiment", "etf_national_team", "stock_daily")
PUBLIC_FUND_EXCLUSION = {
    "name": "public_fund",
    "reason": ("大库(public_fund.db)归档走独立 upload-db 流式链, db_cutoff 口径不含它; "
               "接管时按 docs/backup-restore.md 手册单独拉取"),
}
_SHA64 = re.compile(r"[0-9a-f]{64}")


class StandbyManifestError(Exception):
    """输入不完整/契约不符 —— 拒绝发布(不覆盖旧清单)。"""


def _load_json(path, what: str) -> dict:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StandbyManifestError(f"{what} 不存在: {p}") from exc
    except ValueError as exc:
        raise StandbyManifestError(f"{what} 不是合法 JSON: {p} ({exc})") from exc
    if not isinstance(data, dict):
        raise StandbyManifestError(f"{what} 根不是 JSON object: {p}")
    return data


def _check_receipt(receipt: dict, what: str) -> dict:
    """上传 receipt 形状/完成度校验(同 backup_source_proof 契约: schema=1 + run_id + complete)。"""
    if receipt.get("schema") != 1:
        raise StandbyManifestError(f"{what} receipt schema != 1")
    if not receipt.get("run_id"):
        raise StandbyManifestError(f"{what} receipt 缺 run_id")
    if receipt.get("complete") is not True:
        raise StandbyManifestError(f"{what} receipt complete != true(本轮上传未完成)")
    if not isinstance(receipt.get("objects"), dict):
        raise StandbyManifestError(f"{what} receipt 缺 objects")
    return receipt


def _sha_or_raise(entry: dict, field: str, where: str) -> str:
    val = entry.get(field)
    if not isinstance(val, str) or not _SHA64.fullmatch(val):
        raise StandbyManifestError(f"{where}: {field} 缺失/非法, 拒绝编造")
    return val


def _size_or_raise(entry: dict, field: str, where: str) -> int:
    val = entry.get(field)
    if not isinstance(val, int) or isinstance(val, bool) or val < 0:
        raise StandbyManifestError(f"{where}: {field} 缺失/非法, 拒绝编造")
    return val


def build_standby_manifest(set_dir, db_receipt: dict, state_receipt: dict,
                           generated_at: str | None = None) -> dict:
    """把「同轮已上传的捕获集合 + DB 备份」映射成 standby_sync 契约 manifest。

    纯函数(不触网/不写盘): 输入 = 本地捕获集合目录(manifest.json) + 两个上传 receipt,
    输出 = 已通过 standby_sync.normalize_manifest 校验的 manifest dict。
    任何必需信息缺失 ⇒ StandbyManifestError(调用方据此不发布, 旧清单保留)。
    """
    from standby_sync import ManifestError, normalize_manifest  # 契约单一事实源

    set_dir = Path(set_dir)
    cap = _load_json(set_dir / "manifest.json", "捕获集合 manifest")
    if cap.get("schema") != CAPTURE_SCHEMA:
        raise StandbyManifestError(
            f"捕获集合 schema={cap.get('schema')!r} != {CAPTURE_SCHEMA}")
    if cap.get("status") != "captured" or cap.get("uploadable") is not True \
            or cap.get("complete") is not True:
        raise StandbyManifestError(
            f"捕获集合不可作恢复点(status={cap.get('status')!r} "
            f"uploadable={cap.get('uploadable')!r} complete={cap.get('complete')!r})")
    archive = cap.get("archive") or {}
    if archive.get("status") != "uploaded" or not archive.get("key"):
        raise StandbyManifestError("捕获集合尚未归档上传(archive.status != uploaded)")

    # business_date: 只认 db_cutoff(N1); common_business_cutoff 不得当业务日期。
    cutoff = cap.get("db_cutoff") or {}
    business_date = cutoff.get("date")
    if cutoff.get("all_databases_covered") is not True:
        raise StandbyManifestError(
            "db_cutoff.all_databases_covered != true(不宣称所有库共同覆盖)")
    if not isinstance(business_date, str) or \
            not re.fullmatch(r"\d{4}-\d{2}-\d{2}", business_date):
        raise StandbyManifestError(f"db_cutoff.date={business_date!r} 非法/缺失")

    db = _check_receipt(db_receipt, "upload-db")
    st = _check_receipt(state_receipt, "upload-state-capture")
    if db.get("run_id") != st.get("run_id"):
        raise StandbyManifestError(
            f"两份 receipt run_id 不一致({db.get('run_id')!r} != {st.get('run_id')!r})")

    # ---- DB 腿: 只用 receipt 里对已上传字节算出的真实指纹 ----
    files: list[dict] = []
    for name in REQUIRED_DBS:
        ent = db["objects"].get(name)
        if not isinstance(ent, dict):
            raise StandbyManifestError(f"upload-db receipt 缺 {name} 对象(不宣称完整)")
        key = ent.get("key")
        if not isinstance(key, str) or not key.startswith("backup/") or \
                not key.endswith(".db.gz"):
            raise StandbyManifestError(f"{name}: receipt key 非法({key!r})")
        gz = ent.get("gzip") or {}
        raw = ent.get("raw") or {}
        tables = {k: v for k, v in (ent.get("tables") or {}).items()
                  if isinstance(v, int) and not isinstance(v, bool) and v >= 0}
        files.append({
            "key": key,
            "role": "db",
            "name": f"{name}.db",
            "size": _size_or_raise(gz, "size", f"{name} gzip"),
            "sha256_gz": _sha_or_raise(gz, "sha256", f"{name} gzip"),
            "sha256_uncompressed": _sha_or_raise(raw, "sha256", f"{name} raw"),
            "size_uncompressed": _size_or_raise(raw, "size", f"{name} raw"),
            "tables": tables,
            # business_date 故意省略(见模块 docstring)
        })

    # ---- 状态集 tar.gz: gzip sha/size + 解压体 sha/size 来自 upload-state-capture receipt ----
    obj = st["objects"].get("state_capture")
    if not isinstance(obj, dict):
        raise StandbyManifestError("upload-state-capture receipt 缺 state_capture 对象")
    if obj.get("bucket") and archive.get("bucket") and obj["bucket"] != archive["bucket"]:
        raise StandbyManifestError("状态集 receipt bucket 与本地 archive 回写不一致")
    if obj.get("key") != archive.get("key"):
        raise StandbyManifestError(
            f"状态集 receipt key({obj.get('key')!r}) 与本地 archive({archive.get('key')!r}) 不一致")
    gz = obj.get("gzip") or {}
    files.append({
        "key": archive["key"],
        "role": "state",
        "name": "state-capture.tar.gz",
        "size": _size_or_raise(gz, "size", "state_capture gzip"),
        "sha256_gz": _sha_or_raise(gz, "sha256", "state_capture gzip"),
        "sha256_uncompressed": _sha_or_raise(
            gz, "uncompressed_sha256", "state_capture gzip"),
        "size_uncompressed": _size_or_raise(
            gz, "uncompressed_size", "state_capture gzip"),
        # business_date 故意省略(见模块 docstring)
    })

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "complete": True,
        "business_date": business_date,
        "generated_at": generated_at or dt.datetime.now(
            dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source_run": db["run_id"],
        "archive_hint": "backup/",
        "files": files,
        "excluded": [dict(PUBLIC_FUND_EXCLUSION)],
    }
    try:
        normalize_manifest(manifest)   # 以 standby_sync 契约校验(单一事实源)
    except ManifestError as exc:
        raise StandbyManifestError(f"产物不符合 standby_sync 契约: {exc}") from exc
    return manifest


def publish_standby_manifest(manifest: dict, s3_request=None, s3_head=None,
                             bucket: str | None = None) -> str | None:
    """发布 manifest 到 R2(临时 key → 同桶 CopyObject 覆盖 latest → 删临时 key)。

    任一步失败返回 None 且**不碰** standby/manifest_latest.json(上一份可用清单保留)。
    成功返回 latest key。s3_request/s3_head 可注入(测试桩; 缺省用 upload_r2 的实现)。
    """
    if s3_request is None or s3_head is None:
        import upload_r2
        s3_request = s3_request or upload_r2.s3_request
        s3_head = s3_head or upload_r2.s3_head
        bucket = bucket or upload_r2.BACKUP_BUCKET
    bkt = bucket
    body = json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                      indent=2).encode("utf-8")
    tmp_key = f"{TMP_PREFIX}{uuid.uuid4().hex}.json"
    temp_ok = False
    try:
        status, data = s3_request("PUT", tmp_key, body, bucket=bkt,
                                  content_type="application/json")
        if status != 200:
            print(f"✗ standby manifest 临时对象写入失败 status={status} "
                  f"{data.decode('utf-8', errors='replace')[:200]}", file=sys.stderr)
            return None
        temp_ok = True
        h_st, _etag, clen = s3_head(tmp_key, bucket=bkt, with_len=True)
        if h_st != 200 or clen is None or int(clen) != len(body):
            print(f"✗ standby manifest 临时对象回读核对失败(status={h_st} "
                  f"len={clen} != {len(body)}), 不覆盖 latest", file=sys.stderr)
            return None
        # 同桶同账号服务端复制(S3 CopyObject; R2 要求 copy-source 带前导 `/`)。
        from urllib.parse import quote
        status, data = s3_request(
            "PUT", LATEST_KEY, bucket=bkt, content_type="application/json",
            extra_headers={"x-amz-copy-source":
                           f"/{bkt}/{quote(tmp_key, safe='/')}"})
        if not (status == 200 and b"<CopyObjectResult" in data
                and b"<Error>" not in data):
            print(f"✗ standby manifest 覆盖 latest 失败 status={status} "
                  f"{data.decode('utf-8', errors='replace')[:200]}(旧清单保留)",
                  file=sys.stderr)
            return None
        return LATEST_KEY
    finally:
        if temp_ok:   # 只清自己建的临时对象; 删除失败只留孤儿, 不影响 latest
            try:
                s3_request("DELETE", tmp_key, bucket=bkt)
            except Exception as exc:  # noqa: BLE001
                print(f"⚠ standby manifest 临时对象清理失败({type(exc).__name__}: {exc}), "
                      f"孤儿 key={tmp_key}", file=sys.stderr)


def cmd_standby_manifest(set_dir, db_proof, state_proof, s3_request=None,
                         s3_head=None, bucket=None) -> int:
    """CLI 入口(upload_r2.py standby-manifest 子命令): 默认关, 失败不改调用方退出码语义。

    s3_request/s3_head/bucket 允许调用方(即 upload_r2.py 的 dispatch)注入自身实现 ——
    避免 python upload_r2.py 作为 __main__ 运行后再 `import upload_r2` 加载第二份模块
    (模块级 load_env 等副作用重复执行); 独立运行本文件时才走缺省 import。
    """
    if os.environ.get("STANDBY_MANIFEST_ENABLED", "0") != "1":
        print("standby manifest: STANDBY_MANIFEST_ENABLED != 1(默认关), 跳过(未触 R2)")
        return 0
    try:
        manifest = build_standby_manifest(
            set_dir, _load_json(db_proof, "upload-db receipt"),
            _load_json(state_proof, "upload-state-capture receipt"))
    except (StandbyManifestError, OSError, ValueError) as exc:
        print(f"✗ standby manifest 未写(旧清单保留): {exc}", file=sys.stderr)
        return 1
    key = publish_standby_manifest(manifest, s3_request=s3_request,
                                   s3_head=s3_head, bucket=bucket)
    if key is None:
        print("✗ standby manifest 发布失败(旧清单保留)", file=sys.stderr)
        return 1
    print(f"✓ standby manifest -> {key} business_date={manifest['business_date']} "
          f"files={len(manifest['files'])} run={manifest['source_run']}")
    return 0


def main(argv: list[str], **publish_kw) -> int:
    """调用入口; 生产链走 upload_r2.py standby-manifest(由 dispatch 注入自己的 s3 实现)。"""
    if len(argv) != 3:
        print("用法: standby_manifest.py <set_dir> <db_proof.json> <state_proof.json>",
              file=sys.stderr)
        return 2
    return cmd_standby_manifest(*argv, **publish_kw)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
