# R2 mac-backups 归档上传独立复核（2026-10-04）

> 任务（主控 2026-10-04）：对 `docs/ops/r2-archive-upload-20261004.md` 记载的 R2 mac-backups 归档上传 + 回读验证做**独立复核**。
> **复核方式：reviewer 独立重跑回读，非采信作者自述**（对象存在性、残留扫描、回读对账、函数行为逐项独立取证）。

## 复核对象

- 归档对象：`signal-backup/mac-backups/archive/mac-backups-2026-10-01.tar.zst`（私有备份桶 `signal-backup`）
- 原始任务文档：`docs/ops/r2-archive-upload-20261004.md`（2026-10-04 上传执行 + 回读验证记录）
- 任务结论：归档已上传、回读可还原、泄漏面已封堵

## 结论

**PASS —— 0 个 P0 / 0 个 P1 / 3 个 P2（泄漏面已封堵）**

- P0：无（不存在会误删既有对象、或公开暴露归档内容、或回读不可还原的缺陷）
- P1：无
- P2：3 条（文档与实际措辞不符 / lifecycle 未实测 / 结构性加固建议，均非阻断）

## 复核证据逐条落表

| # | 证据点 | 复核方式 | 复核结果 |
|---|---|---|---|
| 1 | **归档对象存在且仅 1 个，size/etag 与 2,278,230,346 一致** | reviewer 独立 List + HEAD 私有桶 `signal-backup/mac-backups/archive/` 前缀 | **PASS**：对象存在且仅 1 个，`Content-Length=2278230346`（= 2,278,230,346 B）、etag 与本地包一致 |
| 2 | **public 主桶 `signal-data` 零残留** | ① 4 个候选前缀逐个查 ② 两法全量分页扫描（主桶 31,478 对象 / 备份桶 62,429 对象）| **PASS**：`mac-backups/tar.zst` 签名全库仅命中 **1 次且位于备份桶**；主桶任何前缀零残留 |
| 3 | **清理脚本为单 key DELETE（精准），无任何既有对象被删** | reviewer 核对 DELETE 动作仅针对本次误传的 1 个对象（`signal-data/mac-backups/archive/...`）| **PASS**：单 key 精准 DELETE，非前缀批量删；复核期间未发现任何既有对象被删 |
| 4 | **回读验证（独立重跑，非采信作者自述）** | reviewer 独立执行：GET → SHA256 比对 → `zstd -d` → 逐文件对账 | **PASS**：GET status=200（signal-backup）；包 SHA256=`f36dd009e27f255c37510b268b06a99fe928503d7a9384c74ffd5e449266d043` 与上传前一致；`zstd -d` 解包 10,920,922,624 B；对账 `files=86 match=86 missing=0 mismatch=0`；包内 manifest 86/86 与生成稿逐行相等 |
| 5 | **`_upload_multipart`（`scripts/upload_r2.py:691`）仍为主桶专用，无生产路径风险** | reviewer 读代码确认函数目标桶 + 唯一调用方 | **PASS**：`_upload_multipart` 目标为主桶（`BUCKET`=signal-data），唯一调用方为 `_upload_glob`，本次归档已改走显式 `bucket=BACKUP_BUCKET` 的单次 PUT 通道，无生产路径风险 |
| 6 | **`_prune_layer`（`scripts/upload_r2.py:2066`）不会匹配 `.tar.zst`** | reviewer 读代码核对正则 | **PASS**：正则 `(\d{8})\.db(?:\.gz)?$` 只匹配 `_YYYYMMDD.db(.gz)` 形态，`.tar.zst` 结尾永不匹配；`mac-backups/archive/` 不在任何自动清理前缀内 |

## P2 三条逐条

### P2-1（已随本次收尾修复）
- **描述**：`docs/ops/r2-archive-upload-20261004.md` §④ 措辞写 "multipart"，但复现命令实际是单次 PUT（S3 PUT 接口）—— 文档与实际不符。
- **判定**：措辞问题，非功能缺陷；归档对象与回读结论不受影响。
- **处置**：已由实施收尾任务同步修订 §④ 措辞为「单次 PUT / S3 PUT 接口」（见 `docs/ops/r2-archive-upload-20261004.md` 修订后版本），只改措辞、不动任何数字与结论。

### P2-2（残留风险，需用户 dashboard 核对）
- **描述**：R2 bucket lifecycle 规则 `GetBucketLifecycleConfiguration` 返回 403（S3 凭证无权限）**未实测**；实际清理以代码 `_prune_*` 为准，但 lifecycle 是否在位、是否可能含 `mac-backups/` 前缀**无法由代码侧排除**。
- **判定**：残余风险如实保留，非阻断；`mac-backups/archive/` 在全部 `_prune_*` 自动清理逻辑中零引用（见原文档 ⑤ 证据表）。
- **待用户动作**：dashboard 核对 R2 → `signal-backup` → Lifecycle rules 是否存在会删 `mac-backups/archive/` 的规则（已登记 pending-features-index #169）。

### P2-3（结构性加固建议，仅建议后续）
- **描述**：`_upload_multipart`（`scripts/upload_r2.py:691`）内部 `s3_request` **未传 bucket 参数**（默认落主桶 `BUCKET`=signal-data），对私有备份桶上传是结构性坑——本次误传事故即由此触发。
- **判定**：本次已通过「显式 `bucket=BACKUP_BUCKET` 的单次 PUT + 复 List 双确认」规避；但函数本身缺 bucket 参数，建议后续为 `_upload_multipart` 增加 bucket 显式传参加固。
- **待办**：已登记 pending-features-index #168（B 级，延后）。

## 复核日期

2026-10-04

## 参考

- `docs/ops/r2-archive-upload-20261004.md`（被复核的原始执行 + 回读记录）
- `docs/ops/r2-slim-compression-measure-20261004.md`（压缩率实测 + 执行草案）
- `docs/ops/r2-mac-backups-restore-20261002.md`（10-02 恢复 + 删除执行）
- `docs/scripts/restore_mac_backups_r2.py`（恢复脚本）
