# DB 恢复操作流程（restore-db.md）

sentiment.db / etf_national_team.db 出事故时的恢复手册。
三层备份 + 在线热备 + R2 异地，确保任意单点失效都能恢复。

## 一、恢复场景

| 场景 | 表现 | 应对 |
| --- | --- | --- |
| 本地 DB 文件损坏 | sqlite3 报 `database disk image is malformed` / `disk I/O error` | 用 R2 备份覆盖 |
| 误删 / rm 错删 | 文件不存在 | 用 R2 备份恢复 |
| 盘毁 / Mac 丢失 | 本地备份与 DB 同失 | 从 R2 异地拉取（异地防盘毁底线） |
| 数据被污染（切分支事故等） | 表行数异常 / 数据丢失 | 用 R2 备份回滚到前一天 |

每日 `backup_db.sh`（17:50 后）做本地热备 + R2 异地 + 恢复演练，最近一次可用备份 = 当日 19:03 前后的 R2 `backup/<name>_YYYYMMDD.db.gz`。

## 二、从 R2 下载最新备份

```bash
cd /Users/linhuichen/code/trade
.venv/bin/python scripts/upload_r2.py download-db sentiment.db      # 下载最新 sentiment 备份
.venv/bin/python scripts/upload_r2.py download-db etf_national_team # 下载最新 etf_nt 备份
```

`download-db <name>`：列出 R2 `signal-backup` 桶 `backup/<name>_YYYYMMDD.db[.gz]` 所有 key，按日期降序取最新，GET 下载，`.gz` 自动 gunzip 解压；解压后 `.db` 绝对路径打印到 stdout（进度到 stderr）。

可选第二参数指定输出目录（默认临时目录）：
```bash
.venv/bin/python scripts/upload_r2.py download-db sentiment /tmp/restore
```

## 三、完整性校验

对下载的 `.db` 跑完整性 + 关键表行数对比：

```bash
# 单文件快速 integrity_check（只读，零风险）
sqlite3 <下载的.db> "PRAGMA integrity_check;"   # 期望输出 ok

# 完整恢复演练（含行数对比，但注意它会与 data/*.db 本地对比，恢复时本地已损坏可能误报）
bash scripts/verify_backup.sh
```

`verify_backup.sh` 流程：从 R2 下载最新 -> `PRAGMA integrity_check` -> 关键表 `COUNT(*)` 与本地 `data/*.db` 对比 -> 失败发 severe 邮件告警。全程只读 mode=ro，不动真实 `data/*.db`。

## 四、恢复到生产路径

**生产路径**（launchd 实跑写入，非 symlink，直接文件）：

- `/Users/linhuichen/code/trade-data/data/sentiment.db`
- `/Users/linhuichen/code/trade-data/data/etf_national_team.db`

**注意**：`trade/data/sentiment.db` 与 `trade-data/data/sentiment.db` 是两个独立文件（同 inode 的 hard link 不存在，是两份副本），恢复只覆盖 `trade-data/data/`（launchd 实际写入路径），不要恢复到 `trade/data/` 否则下次 launchd 仍读旧版。

```bash
# 1) 停所有写入任务（防 launchd 在恢复中触发）
launchctl unload ~/Library/LaunchAgents/com.trade.update-all.plist
launchctl unload ~/Library/LaunchAgents/com.trade.intraday-snapshot.plist
launchctl unload ~/Library/LaunchAgents/com.trade.etf-national-team.plist
launchctl unload ~/Library/LaunchAgents/com.trade.lab-auto.plist

# 2) 备份当前损坏版本（防恢复出问题可回滚）
mv /Users/linhuichen/code/trade-data/data/sentiment.db \
   /Users/linhuichen/code/trade-data/data/sentiment.db.broken.$(date +%Y%m%d_%H%M)

# 3) 用下载的备份覆盖（download-db 已返回解压 .db 路径）
cp /tmp/restore/sentiment_YYYYMMDD.db /Users/linhuichen/code/trade-data/data/sentiment.db
chmod 644 /Users/linhuichen/code/trade-data/data/sentiment.db

# 4) 恢复后自检
sqlite3 /Users/linhuichen/code/trade-data/data/sentiment.db "PRAGMA integrity_check; SELECT COUNT(*) FROM score_daily; SELECT COUNT(*) FROM signal_daily;"

# 5) 重载 launchd 任务恢复写入
launchctl load ~/Library/LaunchAgents/com.trade.update-all.plist
launchctl load ~/Library/LaunchAgents/com.trade.intraday-snapshot.plist
launchctl load ~/Library/LaunchAgents/com.trade.etf-national-team.plist
launchctl load ~/Library/LaunchAgents/com.trade.lab-auto.plist
```

## 五、三层备份说明（R2 signal-backup 桶）

| 层级 | 路径 | 保留 | 用途 |
| --- | --- | --- | --- |
| 日备份 | `backup/<name>_YYYYMMDD.db.gz` | 30 天 | 每日恢复点（首选） |
| 周备份 | `weekly/<name>_YYYYMMDD.db.gz` | 28 天（4 周） | 本周首次上传，跨周损坏兜底 |
| 月备份 | `monthly/<name>_YYYYMMDD.db.gz` | 365 天（12 月） | 本月首次上传，长期归档 |

由 `scripts/upload_r2.py upload-db` 上传（`backup_db.sh` 自动调用），`_prune_r2_backup` 分层清理（代码 + R2 lifecycle 双保险）。

查可用备份列表：
```bash
.venv/bin/python scripts/upload_r2.py list "backup/sentiment_" --bucket signal-backup
.venv/bin/python scripts/upload_r2.py list "weekly/sentiment_" --bucket signal-backup
```

注意：`download-db` 默认只取 `backup/` 最新（日备份层）；周/月归档如需恢复，用 `upload_r2.py upload <local> <key>` 反向逻辑改写或手动 list + GET。

本地还有 `data/backups/` 14 天热备（`backup_db.sh` 直接 `.db` 不压缩，路径更直接，优先尝试本地再上 R2）。

## 六、紧急联系人 / 注意事项

- **恢复后必须验证**：`sqlite3 integrity_check` + 关键表 `COUNT(*)` 对比昨日（`score_daily / signal_daily / daily_metric` 等）。
- **恢复时禁推 git**：DB 已 untracked（CLAUDE.md §10），不要 `git add data/*.db` 否则切分支污染重现 2026-07-14 事故。
- **WAL/SHM 文件**：若存在 `sentiment.db-wal` / `sentiment.db-shm`，恢复主 db 后应一并删除（旧 WAL 会与新 db 冲突）：
  ```bash
  rm -f /Users/linhuichen/code/trade-data/data/sentiment.db-wal
  rm -f /Users/linhuichen/code/trade-data/data/sentiment.db-shm
  ```
- **告警链路**：恢复后 `scripts/verify_backup.sh` 会自跑恢复演练（备份时联动），失败发 severe 邮件 + `data/alerts/latest.md`，留意。
- **线上数据不受影响**：前端只读 `static-site/data/*.json` 静态产物（CLAUDE.md §9），DB 恢复不影响线上展示，只需保证下一轮 `update_all` 能正常写入。
- **日志排查**：`data/logs/backup_db_*.log` 看每日备份结果，`data/logs/verify_backup_*.log` 看演练结果。

## 七、相关脚本

- `scripts/backup_db.sh` —— 本地热备（Python `src.backup(dst)` 在线 API，WAL 一致快照）+ R2 异地 + verify 演练
- `scripts/upload_r2.py` —— R2 上传/下载/清理（`upload-db` / `download-db <name>` / `_prune_r2_backup`）
- `scripts/verify_backup.sh` —— 恢复演练（下载 + integrity_check + 行数对比，只读零风险）
