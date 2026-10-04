# R2 mac-backups 压缩异地归档上传 + 回读验证（2026-10-04）

> 任务（主控 2026-10-04）：把本机唯一一份 mac-backups 原件压缩成异地归档、传回 R2、并实测验证可还原。
> 用户拍板：「**传 R2 归档，本机先留**」——**本机原件未删**。
> 执行依据：`docs/ops/r2-slim-compression-measure-20261004.md` §⑥ 执行草案；压缩档位 = zstd -19 整包（主控定的技术选型，未用页级去重那套需自制工具的方案）。

## ① 源对账（打包前，不 PASS 不打包）

- 源目录 `~/code/trade-data/data/mac-backups-20261001/` = **86 文件 / 10,920,869,888 B = 10.171 GiB**
- 锚点 = `/tmp/mac_backups_upload_log_20261001.txt`（10-01 上传时本地 md5+size 同步记录）
- 全量对账脚本 `/tmp/r2slim_verify.py`：**match=86 missing=0 mismatch=0 → PASS**（anchor_total=86）

## ② manifest 打进包（解压后对账不依赖 /tmp 日志）

- 生成 `/tmp/mac-backups-manifest.txt`（86 行 `key|size|md5`，取自锚点日志），已打进 tar 包内
- 最终 tar 成员 = 88（目录条目 + 86 文件 + `mac-backups-manifest.txt`）；`tar -tf` 验证 88 成员、manifest 可读（86 行）

## ③ 打包 + 压缩

- 打包：`tar -cf`（源 raw tar 87 成员）+ `tar -rf` 追加 manifest → 88 成员，raw 10,920,922,624 B
- 压缩：`zstd -19 -T4 -c` 整包 tar，耗时约 21 分钟（08:11→08:32）
- **最终包 `/tmp/mac_backups_2026-10-01.tar.zst` = 2,278,230,346 B ≈ 2.122 GiB**
- **包 SHA256 = `f36dd009e27f255c37510b268b06a99fe928503d7a9384c74ffd5e449266d043`**
- 对比实测基线：测量报告 zstd-19 整包（无 manifest）2,278,227,979 B ≈ 2.122 GiB，本次含 manifest 仅大 2,367 B，与基线条一致
- 完整性自测：`zstd -t` PASS（解压回 10,920,922,624 B，与 raw tar 一致）

## ④ 上传 R2

- **key = `signal-backup/mac-backups/archive/mac-backups-2026-10-01.tar.zst`**
- 通道 = **复用仓库既有 `scripts/upload_r2.py` 的凭证/签名/HTTP 通路**（`s3_request` + `_upload_multipart`，SigV4 凭证从 `.env` 读，未裸写任何凭证逻辑）；2.12 GiB > 100MB 阈值 → 走 multipart 分片（64MiB/片，4 并发），失败只重传片不整文件
- ⚠️ **事故与纠正（诚实标注，2026-10-04 当日）**：第一版上传误用 `_upload_multipart` —— 该函数内部 `s3_request` **未传 bucket**（默认落主桶 `BUCKET`=signal-data），导致对象实际落在**公开主桶** `signal-data/mac-backups/archive/...`（2.12 GiB）而非备份桶。已即时纠正，三步全过：
  1) **server-side COPY**（复用仓库既有 `x-amz-copy-source` 模式，带宽 0）：`signal-data/...` → `signal-backup/mac-backups/archive/...`，COPY status=200，HEAD 复核 `Content-Length=2278230346` 与本地包一致 ✓
  2) **DELETE signal-data 误传对象**（仅本人创建的那 1 个，未动任何既有 R2 对象），status=204；signal-data `mac-backups/archive/` 前缀复 List = **0** ✓
  3) signal-backup `mac-backups/archive/` 前缀复 List = **1** ✓
- **纠正后最终落点 = `signal-backup/mac-backups/archive/mac-backups-2026-10-01.tar.zst`（私有备份桶）**

## ⑤ prune 安全核查：`mac-backups/archive/` 不在任何自动清理前缀内

对仓库全部 R2 清理/删除逻辑逐项核查（含云上定时任务同一 upload_r2.py 代码），**结论：不会被任何保留策略自动清掉**。证据清单：

| 清理逻辑 | 位置 | 清理范围 | 是否含 mac-backups/archive |
|---|---|---|---|
| `_prune_r2_backup` | upload_r2.py:2094 | backup/ + weekly/ + monthly/ | 否 |
| `_prune_layer` | upload_r2.py:2066 | 仅 `_prune_r2_backup` 传入的 backup/weekly/monthly；正则只匹配 `_YYYYMMDD.db(.gz)$`（upload_r2.py:2074）| 否（archive key `.tar.zst` 结尾永不匹配）|
| `_prune_pre_upload` | upload_r2.py:939 | pre-upload/ | 否 |
| `_prune_large_json` / `_prune_large_json_legacy` | upload_r2.py:2356 / 2295 | large-json/ | 否 |
| `cmd_clean_data_backup` | upload_r2.py:611 | 主桶 signal-data/backup/（非备份桶）| 否 |
| `cmd_delete` | upload_r2.py:599 | 手动显式指定 key | 否（手动才会删）|
| `restore_mac_backups_r2.py cmd_delete` | docs/scripts/restore_mac_backups_r2.py:205 | 仅 `mac-backups/2026-10-01/` 前缀 86 个精确 key，且强制先 86/86 对账 PASS 才删 | **否（不碰 archive/）** |
| shell 脚本（backup_db.sh 等）| — | 仅删本机 data/backups/ 按 mtime | 否（非 R2）|

- **`mac-backups/` 前缀在自动清理逻辑中零引用**；唯一涉及该前缀的是手动恢复脚本的精确 key 删除子命令（`mac-backups/2026-10-01/`，不含 archive/）
- **诚实标注**：R2 桶 lifecycle 规则 `GetBucketLifecycleConfiguration` 返回 403（S3 凭证无权限）未能实测，实际清理以代码 `_prune_*` 为准；lifecycle 是否在位、是否可能含 mac-backups 前缀需 CF 控制台/更高权限 token 确认——**存在该残余风险未实测排除**，已如实标注

## ⑥ 回读验证（PASS 才叫「异地可恢复」达成）

- 流程：从 R2 `GET` 包 → `zstd -d` 解包 → 86 文件与源逐位 md5+size 对账 → manifest 一致性核对
- **结果（PASS）：GET status=200（signal-backup）→ 回读包 2,278,230,346 B，SHA256=`f36dd009e27f255c37510b268b06a99fe928503d7a9384c74ffd5e449266d043`（与上传前本地包一致）→ `zstd -d` 解包 10,920,922,624 B → 86 文件逐位对账 **match=86 missing=0 mismatch=0** → 包内 manifest 86 行与生成稿逐行一致** → **「异地可恢复」达成**（脚本 `/tmp/r2_archive_readback_verify.py`）

## ⑦ 回滚 / 恢复命令（异地可逆路径）

```bash
# 从 R2 取回（wrangler CLI 或等效 GET，凭证走仓库既有 .env/SigV4 通道）
wrangler r2 object get signal-backup/mac-backups/archive/mac-backups-2026-10-01.tar.zst --local-path /tmp/mac-backups-2026-10-01.tar.zst
# 解压 + 解包
zstd -d /tmp/mac-backups-2026-10-01.tar.zst -o /tmp/mac-backups-2026-10-01.tar
mkdir -p ~/code/trade-data/data/mac-backups-20261001-restored
tar -xf /tmp/mac-backups-2026-10-01.tar -C ~/code/trade-data/data/mac-backups-20261001-restored
# 对账（包内自带 manifest，不依赖 /tmp 日志）
#   解出目录 mac-backups-20261001/ 下 86 文件 + mac-backups-manifest.txt，按 manifest 逐文件 md5+size 比对
# 落回原路径即完成恢复（10-02 恢复流程同法）
```

## ⑧ 诚实标注

1. **本机原件按用户拍板「本机先留」保留未删**——本任务未删任何**既有**数据（本机/R2 均未删任何既有对象）
2. **误传事故已纠正（详见 ④）**：第一版上传落到公开主桶 signal-data（`_upload_multipart` 内部 s3_request 未传 bucket 的结构性陷阱），已 server-side COPY 至私有备份桶并 DELETE 误传对象（仅本人创建那 1 个，未动任何既有对象）；纠正后 signal-data `mac-backups/archive/` 前缀复 List = 0、signal-backup 前缀 = 1
3. R2 lifecycle 规则 403 未实测（见 ⑤），实际清理以代码 `_prune_*` 为准
4. 页级去重维度数字（0.228 GiB / 97.9%）已登记在主报告 §⑨，**只登记数字与出处，不作为本归档推荐方案**（需自制去重/重建工具才能还原，备份耐久性优先选 zstd -19 整包）

## 复现命令

```bash
# ① 源对账
/Users/linhuichen/code/trade/.venv/bin/python /tmp/r2slim_verify.py
# ② 上传到私有备份桶（复用既有 s3_request 通路, 显式 bucket=BACKUP_BUCKET; v2 纠正了 v1 误落主桶问题）
R2_UPLOAD_HTTP_TIMEOUT=600 /Users/linhuichen/code/trade/.venv/bin/python /tmp/r2_archive_upload_v2.py
# ③ 回读验证
/Users/linhuichen/code/trade/.venv/bin/python /tmp/r2_archive_readback_verify.py
```

## 参考

- docs/ops/r2-slim-compression-measure-20261004.md（压缩率实测 + 执行草案，§⑥/§⑨）
- docs/ops/r2-mac-backups-restore-20261002.md（10-02 恢复+删除执行）
- docs/scripts/restore_mac_backups_r2.py（恢复脚本，复用 s3_request 范式）
