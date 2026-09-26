# DB 备份与恢复手册（backup-restore.md）

sentiment.db / etf_national_team.db 的备份机制 + 事故恢复流程。
三层备份 + 在线热备 + R2 异地 + 每日恢复演练，确保任意单点失效都能恢复。

> 本文档为 DB 灾备唯一权威文档（合并原 `docs/restore-db.md`，A7 2026-07-20 整理）。
> 相关脚本：`scripts/backup_db.sh`（备份）/ `scripts/upload_r2.py`（R2 上传下载）/ `scripts/verify_backup.sh`（恢复演练）。

---

## 一、备份机制（每日自动，17:50 后）

`scripts/backup_db.sh` 由 `update_all.sh` L202 串接，交易日收盘后自动跑，无需手动触发。流程：

1. **本地在线热备**（`backup_db.sh` L42-52）：Python `sqlite3.Connection.backup()`（SQLite 在线 backup API）
   - 不锁库、不阻塞读写（WAL 模式下也拿一致快照），比直接 `cp` 文件安全（cp 可能拷到半写状态）
   - 产出 `data/backups/<name>_YYYYMMDD_HHMM.db`，保留 14 天滚动（`find -mtime +14 -delete`）
2. **R2 异地备份**（`backup_db.sh` L82-88 调 `upload_r2.py upload-db`）：
   - gzip 压缩上传（102MB→30MB），私有桶 `signal-backup`
   - 三层保留：日 `backup/` 30 天 + 周 `weekly/` 28 天 + 月 `monthly/` 365 天
   - `_prune_r2_backup` 分层清理（代码 + R2 lifecycle 双保险）
3. **恢复演练**（`backup_db.sh` L95-101 调 `verify_backup.sh`）：
   - 从 R2 下载最新 → `PRAGMA integrity_check` → 关键表 `COUNT(*)` 与本地对比
   - 全程只读 `mode=ro`，不动真实 `data/*.db`
   - 失败发 severe 邮件告警 + 写 `data/alerts/latest.md`
4. **失败告警**（`backup_db.sh` L109-119）：本地热备失败（退出码非 0）时 `notify.py --severe` 发邮件

**最近一次可用备份** = 当日 17:50 后的 R2 `backup/<name>_YYYYMMDD.db.gz`（约 19:03 前后完成上传+演练）。

**日志**：`data/logs/backup_db_YYYYMMDD_HHMM.log`（备份）/ `data/logs/verify_backup_*.log`（演练）。

### 三层备份说明（R2 signal-backup 桶）

| 层级 | 路径 | 保留 | 用途 |
| --- | --- | --- | --- |
| 日备份 | `backup/<name>_YYYYMMDD.db.gz` | 30 天 | 每日恢复点（首选） |
| 周备份 | `weekly/<name>_YYYYMMDD.db.gz` | 28 天（4 周） | 本周首次上传，跨周损坏兜底 |
| 月备份 | `monthly/<name>_YYYYMMDD.db.gz` | 365 天（12 月） | 本月首次上传，长期归档 |

查可用备份列表：
```bash
.venv/bin/python scripts/upload_r2.py list "backup/sentiment_" --bucket signal-backup
.venv/bin/python scripts/upload_r2.py list "weekly/sentiment_" --bucket signal-backup
.venv/bin/python scripts/upload_r2.py list "monthly/sentiment_" --bucket signal-backup
```

注意：`download-db` 默认只取 `backup/` 最新（日备份层）；周/月归档如需恢复，用 `upload_r2.py list` 查 key 后手动 GET。

本地还有 `data/backups/` 14 天热备（`backup_db.sh` 直接 `.db` 不压缩，路径更直接，优先尝试本地再上 R2）。

---

## 二、恢复场景

| 场景 | 表现 | 应对 |
| --- | --- | --- |
| 本地 DB 文件损坏 | sqlite3 报 `database disk image is malformed` / `disk I/O error` | 用 R2 备份覆盖 |
| 误删 / rm 错删 | 文件不存在 | 用 R2 备份恢复 |
| 盘毁 / Mac 丢失 | 本地备份与 DB 同失 | 从 R2 异地拉取（异地防盘毁底线） |
| 数据被污染（切分支事故等） | 表行数异常 / 数据丢失 | 用 R2 备份回滚到前一天 |

---

## 三、从 R2 下载最新备份

```bash
cd /Users/linhuichen/code/trade
.venv/bin/python scripts/upload_r2.py download-db sentiment.db      # 下载最新 sentiment 备份
.venv/bin/python scripts/upload_r2.py download-db etf_national_team # 下载最新 etf_nt 备份
```

`download-db <name>`（`upload_r2.py` L582-589 `cmd_download_latest_db`）：列出 R2 `signal-backup` 桶 `backup/<name>_YYYYMMDD.db[.gz]` 所有 key，按日期降序取最新，GET 下载，`.gz` 自动 gunzip 解压；解压后 `.db` 绝对路径打印到 stdout（进度到 stderr）。

可选第二参数指定输出目录（默认临时目录）：
```bash
.venv/bin/python scripts/upload_r2.py download-db sentiment /tmp/restore
```

---

## 四、完整性校验

对下载的 `.db` 跑完整性 + 关键表行数对比：

```bash
# 单文件快速 integrity_check（只读，零风险）
sqlite3 <下载的.db> "PRAGMA integrity_check;"   # 期望输出 ok

# 完整恢复演练（含行数对比，但注意它会与 data/*.db 本地对比，恢复时本地已损坏可能误报）
bash scripts/verify_backup.sh
```

`verify_backup.sh` 流程：从 R2 下载最新 → `PRAGMA integrity_check` → 关键表 `COUNT(*)` 与本地 `data/*.db` 对比 → 失败发 severe 邮件告警。全程只读 mode=ro，不动真实 `data/*.db`。

---

## 五、恢复到生产路径

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

# 4) 删除旧 WAL/SHM（旧 WAL 会与新 db 冲突）
rm -f /Users/linhuichen/code/trade-data/data/sentiment.db-wal
rm -f /Users/linhuichen/code/trade-data/data/sentiment.db-shm

# 5) 恢复后自检
sqlite3 /Users/linhuichen/code/trade-data/data/sentiment.db "PRAGMA integrity_check; SELECT COUNT(*) FROM score_daily; SELECT COUNT(*) FROM signal_daily;"

# 6) 重载 launchd 任务恢复写入
launchctl load ~/Library/LaunchAgents/com.trade.update-all.plist
launchctl load ~/Library/LaunchAgents/com.trade.intraday-snapshot.plist
launchctl load ~/Library/LaunchAgents/com.trade.etf-national-team.plist
launchctl load ~/Library/LaunchAgents/com.trade.lab-auto.plist
```

---

## 六、紧急注意事项

- **恢复后必须验证**：`sqlite3 integrity_check` + 关键表 `COUNT(*)` 对比昨日（`score_daily / signal_daily / daily_metric` 等）。
- **恢复时禁推 git**：DB 已 untracked（CLAUDE.md §10），不要 `git add data/*.db` 否则切分支污染重现 2026-07-14 事故。
- **WAL/SHM 文件**：若存在 `sentiment.db-wal` / `sentiment.db-shm`，恢复主 db 后应一并删除（步骤 4 已含），旧 WAL 会与新 db 冲突。
- **告警链路**：恢复后 `scripts/verify_backup.sh` 会自跑恢复演练（备份时联动），失败发 severe 邮件 + `data/alerts/latest.md`，留意。
- **线上数据不受影响**：前端只读 `static-site/data/*.json` 静态产物（CLAUDE.md §9），DB 恢复不影响线上展示，只需保证下一轮 `update_all` 能正常写入。
- **日志排查**：`data/logs/backup_db_*.log` 看每日备份结果，`data/logs/verify_backup_*.log` 看演练结果。

---

## 七、相关脚本

- `scripts/backup_db.sh` -- 本地热备（Python `src.backup(dst)` 在线 API，WAL 一致快照）+ R2 异地 + verify 演练 + 失败邮件告警
- `scripts/upload_r2.py` -- R2 上传/下载/清理（`upload-db` / `download-db <name>` / `_prune_r2_backup` 三层分层）
- `scripts/verify_backup.sh` -- 恢复演练（下载 + integrity_check + 行数对比，只读零风险）

---

## 八、大 JSON 私有桶备份与恢复（signal-backup 桶 large-json/ 前缀）

### 背景：为什么大 JSON 不进 git

staticdata 备份仓库里跟踪着 7 个 >20MB 的 JSON（共 319MB，如 `signal_kelly_trades.json` 等，
见 `docs/large-json-backup-manifest.md` 明细）。它们天天变化、天天进 delta，把备份的「变更量」
顶到 357MB > 300MB 阈值 → 备份天天 `skip_oversize` 不 commit。**已把它们移出 staticdata git 跟踪**，
改走 R2 私有桶 `signal-backup` 的 `large-json/` 前缀版本化快照（gzip 压缩，只留小文件 + 上传/恢复脚本在 git）。

### 备份机制

- 上传：`scripts/upload_r2.py upload-large-json`（活脚本，由核心侧每日挂载，本手册只写恢复侧）
- key 格式：`large-json/<YYYY-MM-DD>/<相对 data/ 的路径>.gz`
  - 例：`large-json/2026-09-25/signal_kelly_trades.json.gz`
  - 例：`large-json/2026-09-25/signal_kelly_trades_parts/t2025.json.gz`
- 保留档位：日档 14 天 + 周档（周日那份）8 周 + 月档（每月 1 号那份）12 个月
- 索引/校验依据：`docs/large-json-backup-manifest.md`（含 sha256，自动生成勿手编）

### 恢复（restore-large-json.sh，只读 R2）

```bash
cd /Users/linhuichen/code/trade
# ① 列出所有可用快照（按日期分组 + 每个文件大小）
bash scripts/restore-large-json.sh --list

# ② 单个还原：默认取该文件最新快照，写回 <目标目录>/<原相对路径>
bash scripts/restore-large-json.sh signal_kelly_trades.json
bash scripts/restore-large-json.sh signal_kelly_trades_parts/t2025.json

# ③ 还原指定日期的全部快照（也支持 --date=YYYY-MM-DD 等号形式）
bash scripts/restore-large-json.sh --date 2026-09-25

# ④ 还原最新日期那一份的全部文件
bash scripts/restore-large-json.sh --all

# ⑤ 可选 [--target <dir>] 显式指定目标目录（默认见下；可加在任意位置）
bash scripts/restore-large-json.sh --list --target /tmp/restore-test
```

**恢复目标**：默认 = `$STATICDATA_REPO/data/`（环境变量 `STATICDATA_REPO` 仅测试用，缺省
`/Users/linhuichen/code/trade-data`）= **生产数据目录 `trade-data/data/`**。这些大 JSON 的生产
"家"就是 `trade-data/data/`（git 不再跟踪它们），恢复回生产原位与 `db.py`/`export.py` 读的库
同源，不随 cwd 漂移。**非默认目标目录（覆盖了 `STATICDATA_REPO` 或传 `--target`）会打印醒目
警告**：可能是别的目录，直接覆盖有风险，测试临时目录也应看清再继续。

**还原行为安全网（全在脚本内）**：
- 先下到同目录 `.tmp`（pid+随机）再 `os.replace` 原子覆盖，读侧要么旧完整要么新完整，绝不半截
- 覆盖前把原文件备份成 `<文件>.bak-<时间戳>`（`copy2` 副本，旧文件在替换前始终在位，无短暂缺失窗口，可回滚）
- gzip 解压；`docs/large-json-backup-manifest.md` 有该完整 R2 key（含日期）的 sha256 记录则比对，不匹配即中止（不改名跳过并汇总非 0 退出）
- 路径安全：恢复写入前校验相对路径（非空/不含 `..` 段/不以 `/` 开头/realpath 落在目标根内），非法跳过并汇总
- 网络快速失败：S3 调用注入 10s 连接超时（不受外部 `R2_UPLOAD_HTTP_TIMEOUT` 大值影响），网络不可达/超时立即报错，不做无限等待
- 收尾总结：打印「成功 N 个 / 失败 M 个 / 跳过 K 个」三计数（跳过=该日期该文件在 R2 不存在/路径非法；失败=下载/写入出错）；失败数 > 0 或存在跳过均非 0 退出，不静默当成功
- **绝不写 R2 上任何对象、绝不删除 R2 上任何对象**（本脚本只有 GET/LIST）

**凭证**：复用 `scripts/upload_r2.py` 的 `s3_request()`（`sys.path.insert(0,"scripts"); import upload_r2`，
import 时 `load_env()` 自动载入 `.env` 的 `R2_S3_ENDPOINT` / `R2_S3_ACCESS_KEY_ID` / `R2_S3_SECRET_ACCESS_KEY`）。凭证缺失打印清晰报错并退出码非 0。

### 与原有四层灾备的关系

| 层 | 原四层 | 大 JSON（本机制） |
| --- | --- | --- |
| 第 1 层 | git 仓库（trade + staticdata） | **移出 staticdata git 跟踪**，不再走 git |
| 第 2 层 | R2 私有桶 `signal-backup` 的 `backup/`（DB）/ `decommissioned/`（退役归档） | **新增 `large-json/` 前缀**（版本化快照，同桶不同前缀） |
| 第 3 层 | 本地 `data/backups/` 热备 | 大 JSON 本地保留当前副本（`data/` 下），历史版本只在 R2 |
| 第 4 层 | 公开桶（对外只读） | 不涉及（大 JSON 体积大且频繁变，不进公开层） |

**一句话**：大 JSON 从 git 层搬到 R2 私有桶版本化层，`signal-backup` 桶仍是 DB + 大 JSON 的
统一异地灾备锚点；恢复侧统一入口 = `restore-large-json.sh`。
