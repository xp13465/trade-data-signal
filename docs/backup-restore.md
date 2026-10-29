# DB 备份与恢复手册（backup-restore.md）

sentiment.db / etf_national_team.db / public_fund.db 的备份机制 + 事故恢复流程。
三层备份 + 在线热备 + R2 异地 + 每日恢复演练，确保任意单点失效都能恢复。

> 本文档为 DB 灾备唯一权威文档（合并原 `docs/restore-db.md`，A7 2026-07-20 整理）。
> 相关脚本：`scripts/backup_db.sh`（备份）/ `scripts/upload_r2.py`（R2 上传下载）/ `scripts/verify_backup.sh`（恢复演练）。

---

## 一、备份机制（每日自动，云上 21:00 起）

`scripts/backup_db.sh` 由云上独立 timer `trade-backup-db.timer`（`OnCalendar=*-*-* 21:00:00`，`Persistent=true`）每日拉起，**不再由 `update_all.sh` 串接**（2026-10-25 核对：`update_all.sh:450` 已写明从主链移除，避免双跑）；无需手动触发。`trade-backup-db.service` 的 `ExecStart=backup_db.sh`、`TimeoutStartSec=12600`（3.5 小时）。流程：

1. **本地在线热备**（`backup_db.sh` L42-52）：Python `sqlite3.Connection.backup()`（SQLite 在线 backup API）
   - 不锁库、不阻塞读写（WAL 模式下也拿一致快照），比直接 `cp` 文件安全（cp 可能拷到半写状态）
   - 产出 `data/backups/<name>_YYYYMMDD_HHMM.db`，保留 **7 天**滚动（`RETAIN_DAYS` 默认 7，云上 unit `Environment=RETAIN_DAYS=7`；`find -mtime +"$RETAIN_DAYS" -delete`）
2. **R2 异地备份**（`backup_db.sh` L82-88 调 `upload_r2.py upload-db`）：
   - gzip 压缩上传（102MB→30MB），私有桶 `signal-backup2`（独立 CF 账号；#178 2026-10-05 起的新写入桶，老桶 `signal-backup` 为迁移前 legacy 存量、只读不搬）
   - 覆盖 sentiment.db + etf_national_team.db + **public_fund.db**（2026-10-25 补入；2.9GB 大库走「SQLite 在线 backup 快照 → 4MiB 分块流式 gzip → 64MiB 分片流式上传」，不整库进内存；源文件 size+mtime 未变时跳过上传，台账 `data/.r2_db_backup_state.json`）
   - 三层保留：日 `backup/` 14 天 + 周 `weekly/` 28 天 + 月 `monthly/` 365 天（日备份 2026-10-03 由 30 天缩减至 14 天，方案见 docs/ops/r2-backup-bucket-capacity-20261002.md）；public_fund 因单份约 0.79GB（790,650,717 B，2026-10-25 实测），单独缩短为 7/28/180 天
   - `_prune_r2_backup` 分层清理（代码为主；R2 lifecycle 是否在位未实测——GetBucketLifecycleConfiguration 403，需 CF 控制台/更高权限 token 确认）
3. **恢复演练**（`backup_db.sh` L95-101 调 `verify_backup.sh`）：
   - 从 R2 下载最新 → `PRAGMA integrity_check` → 关键表 `COUNT(*)` 与本地对比
   - 全程只读 `mode=ro`，不动真实 `data/*.db`
   - 失败发 severe 邮件告警 + 写 `data/alerts/latest.md`
   - 拉回范围：**sentiment / etf_national_team / stock_daily** 每日拉回（`stock_daily` 2026-10-29 21:00 首备，首备日之前无 key 记 SKIP、过了首备日仍无 key 记 FAIL 告警）；**public_fund 周频**（默认仅周日跑，`VERIFY_PUBLIC_FUND=auto|1|0` 门控），因单份 0.79GB gz / 解压 2.76GiB，`download-db` 整对象进内存会在云上 OOM，改走 `docs/scripts/restore_r2_db_backup.py` 6 线程 32MiB Range GET 流式拉回 → gunzip → `integrity_check` → 关键表行数比对（口径见 docs/ops/backup-drill-20261028.md；2026-10-25 首备份实测见 docs/ops/pfdb-r2-backup-20261025.md）
4. **失败告警**（`backup_db.sh` L109-119）：本地热备失败（退出码非 0）时 `notify.py --severe` 发邮件

**最近一次可用备份** = 当日 21:00 起的 R2 `backup/<name>_YYYYMMDD.db.gz`（常态约 23-25 分钟完成上传+演练 ⇒ 约 21:25 前后；2026-10-25 首备实测约 70 分钟。「演练」= `verify_backup.sh` 每日拉回 sentiment / etf_national_team / stock_daily 三个小库，public_fund 大库仅周日跑一次流式拉回演练；public_fund 源库自上次备份未变时整条上传跳过）。

**日志**：`data/logs/backup_db_YYYYMMDD_HHMM.log`（备份）/ `data/logs/verify_backup_*.log`（演练）。

### 三层备份说明（R2 signal-backup2 桶）

| 层级 | 路径 | 保留 | 用途 |
| --- | --- | --- | --- |
| 日备份 | `backup/<name>_YYYYMMDD.db.gz` | 14 天 | 每日恢复点（首选） |
| 周备份 | `weekly/<name>_YYYYMMDD.db.gz` | 28 天（4 周） | 本周首次上传，跨周损坏兜底 |
| 月备份 | `monthly/<name>_YYYYMMDD.db.gz` | 365 天（12 月） | 本月首次上传，长期归档 |

查可用备份列表：
```bash
.venv/bin/python scripts/upload_r2.py list "backup/sentiment_" --bucket signal-backup2
.venv/bin/python scripts/upload_r2.py list "weekly/sentiment_" --bucket signal-backup2
.venv/bin/python scripts/upload_r2.py list "monthly/sentiment_" --bucket signal-backup2
```

> **如需读老桶快照**（#178 迁移前存量）：临时 `R2_BACKUP_BUCKET=signal-backup` 覆盖后 `upload_r2.py list` / `download-db`，
> 读完即恢复默认，勿常态指向老桶（老桶只读、存量不搬；相关说明见 [r2-deployment.md](r2-deployment.md)）。

注意：`download-db` 默认只取 `backup/` 最新（日备份层）；周/月归档如需恢复，用 `upload_r2.py list` 查 key 后手动 GET。

本地还有 `data/backups/` 7 天热备（`RETAIN_DAYS` 默认 7、云上 unit 注入同为 7；`backup_db.sh` 直接 `.db` 不压缩，路径更直接，优先尝试本地再上 R2）。

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

`download-db <name>`（`upload_r2.py` L582-589 `cmd_download_latest_db`）：列出 R2 `signal-backup2` 桶 `backup/<name>_YYYYMMDD.db[.gz]` 所有 key，按日期降序取最新，GET 下载，`.gz` 自动 gunzip 解压；解压后 `.db` 绝对路径打印到 stdout（进度到 stderr）。

可选第二参数指定输出目录（默认临时目录）：
```bash
.venv/bin/python scripts/upload_r2.py download-db sentiment /tmp/restore
```

⚠️ **public_fund 大库不要用 `download-db`**：它整对象 GET 进内存再 `gzip.decompress`，0.79GB gz + 2.9GB 解压同时驻留，云主机 3.7G RAM 可能 OOM。改用流式脚本（Range 分片落盘 + 流式解压 + `integrity_check`）：
```bash
# 先确认输出盘余量 ≥ gz 0.79GB + 解压后 2.9GB
python3 docs/scripts/restore_r2_db_backup.py --name public_fund --out-dir /home/ubuntu/restore
# 可选：与源库当前状态生成的参考快照逐位对账（额外再占 2.9GB）
python3 docs/scripts/restore_r2_db_backup.py --name public_fund --out-dir /tmp/verify \
    --verify-against-src /home/ubuntu/code/trade-data/data/public_fund.db
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

**生产路径**（云上 systemd timer 实跑写入，非 symlink，直接文件；2026-09-12 起生产采集迁云上）：

- 云上生产主库：`/home/ubuntu/code/trade-data/data/sentiment.db`
- 云上生产主库：`/home/ubuntu/code/trade-data/data/etf_national_team.db`
- 云上生产主库：`/home/ubuntu/code/trade-data/data/public_fund.db`（2.9G，恢复前先停采集/写库进程，旧库留一份）
- 本机开发库：`/Users/linhuichen/code/trade-data/data/`（本机 mac 纯开发不跑生产定时任务）

**注意**：`trade/data/sentiment.db` 与 `trade-data/data/sentiment.db` 是两个独立文件（同 inode 的 hard link 不存在，是两份副本）。**生产恢复必须 ssh 云上对云上 `data/` 操作**，不要恢复到代码仓侧目录；本机开发库恢复直接覆盖本机 `trade-data/data/` 即可（本机无生产定时任务，无需停任务）。

```bash
# 0) 生产恢复先登录云上（本机开发库恢复可跳过停/重载步骤）
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173

# 1) 停所有写入任务（防 systemd timer 在恢复中触发；写 sentiment/etf 库的主要任务）
sudo systemctl stop trade-update-all.timer trade-intraday-snapshot.timer \
     trade-etf-national-team.timer trade-lab-auto.timer

# 2) 备份当前损坏版本（防恢复出问题可回滚；下方以云上路径为例，本机开发库换本机路径）
mv /home/ubuntu/code/trade-data/data/sentiment.db \
   /home/ubuntu/code/trade-data/data/sentiment.db.broken.$(date +%Y%m%d_%H%M)

# 3) 用下载的备份覆盖（download-db 已返回解压 .db 路径；本机下载后传到云上，或云上直接跑 download-db）
cp /tmp/restore/sentiment_YYYYMMDD.db /home/ubuntu/code/trade-data/data/sentiment.db
chmod 644 /home/ubuntu/code/trade-data/data/sentiment.db

# 4) 删除旧 WAL/SHM（旧 WAL 会与新 db 冲突）
rm -f /home/ubuntu/code/trade-data/data/sentiment.db-wal
rm -f /home/ubuntu/code/trade-data/data/sentiment.db-shm

# 5) 恢复后自检
sqlite3 /home/ubuntu/code/trade-data/data/sentiment.db "PRAGMA integrity_check; SELECT COUNT(*) FROM score_daily; SELECT COUNT(*) FROM signal_daily;"

# 6) 重载 systemd timer 恢复写入
sudo systemctl start trade-update-all.timer trade-intraday-snapshot.timer \
     trade-etf-national-team.timer trade-lab-auto.timer
```

---

## 六、紧急注意事项

- **恢复后必须验证**：`sqlite3 integrity_check` + 关键表 `COUNT(*)` 对比昨日（`score_daily / signal_daily / daily_metric` 等）。
- **恢复时禁推 git**：DB 已 untracked（docs/archive/CLAUDE-history.md，原 §10 切分支保护 DB），不要 `git add data/*.db` 否则切分支污染重现 2026-07-14 事故。
- **WAL/SHM 文件**：若存在 `sentiment.db-wal` / `sentiment.db-shm`，恢复主 db 后应一并删除（步骤 4 已含），旧 WAL 会与新 db 冲突。
- **告警链路**：恢复后 `scripts/verify_backup.sh` 会自跑恢复演练（备份时联动），失败发 severe 邮件 + `data/alerts/latest.md`，留意。
- **线上数据不受影响**：前端只读 `static-site/data/*.json` 静态产物（.claude/skills/role-implementer §1，原 §9 单版前端铁律），DB 恢复不影响线上展示，只需保证下一轮 `update_all` 能正常写入。
- **日志排查**：`data/logs/backup_db_*.log` 看每日备份结果，`data/logs/verify_backup_*.log` 看演练结果。

---

## 七、相关脚本

- `scripts/backup_db.sh` -- 本地热备（Python `src.backup(dst)` 在线 API，WAL 一致快照）+ R2 异地 + verify 演练 + 失败邮件告警
- `scripts/upload_r2.py` -- R2 上传/下载/清理（`upload-db` / `download-db <name>` / `_prune_r2_backup` 三层分层）
- `scripts/verify_backup.sh` -- 恢复演练（下载 + integrity_check + 行数对比，只读零风险）

---

## 八、大 JSON 私有桶备份与恢复（signal-backup2 桶 large-json/ 前缀）

### 背景：为什么大 JSON 不进 git

staticdata 备份仓库里跟踪着 7 个 >20MB 的 JSON（共 319MB，如 `signal_kelly_trades.json` 等，
明细见 `<staticdata 备份仓库>/docs/large-json-backup-manifest.md`——#115 起该清单已迁至 staticdata 仓库，
trade 仓库的 `docs/large-json-backup-manifest.md` 只是指针说明）。它们天天变化、天天进 delta，把备份的「变更量」
顶到 357MB > 300MB 阈值 → 备份天天 `skip_oversize` 不 commit。**已把它们移出 staticdata git 跟踪**，
改走 R2 私有桶 `signal-backup2` 的 `large-json/` 前缀版本化快照（gzip 压缩，只留小文件 + 上传/恢复脚本在 git）。

### 备份机制

- 上传：`scripts/upload_r2.py upload-large-json`（活脚本，由核心侧每日挂载，本手册只写恢复侧；默认 8 线程并行，env `R2_LARGE_JSON_WORKERS` 调）
- key 格式（#126，2026-09-30 固定前缀；唯一完整副本，增量复用，内容未变 HEAD ETag 命中跳过 PUT）：
  `large-json/<相对 data/ 的路径>.gz`
  - 例：`large-json/signal_kelly_trades.json.gz`
  - 例：`large-json/signal_kelly_trades_parts/t2025.json.gz`
- legacy 旧按天键（过渡期历史快照）：`large-json/<YYYY-MM-DD>/<相对 data/ 的路径>.gz`，保留 7 天宽限期后由 `_prune_large_json` 自动清理
- 保留档位：固定前缀永久保留（唯一副本，不滚动删，删除=丢数据）；legacy 旧日期目录 7 天宽限期后清理
- 逃生门：env `R2_LARGE_JSON_DATE_PREFIX=1` 回旧按天键生成行为（一键回退用）
- 索引/校验依据：`<staticdata 备份仓库>/docs/large-json-backup-manifest.md`（含 sha256，自动生成勿手编）。
  #115(2026-09-27)清单从 trade 仓库迁到 staticdata 仓库(async/sync 的 git add -A 提交对象)；恢复脚本
  `restore-large-json.sh` 已双路径兼容：先读 staticdata 仓库新路径，回退 trade 仓库旧路径。

### 恢复（restore-large-json.sh，只读 R2）

```bash
cd /Users/linhuichen/code/trade
# ① 列出所有可用快照（当前固定前缀「最新完整副本」+ 历史日期分组）
bash scripts/restore-large-json.sh --list

# ② 单个还原：优先取固定前缀（当前完整副本），无则取该文件最新历史日期快照
bash scripts/restore-large-json.sh signal_kelly_trades.json
bash scripts/restore-large-json.sh signal_kelly_trades_parts/t2025.json

# ③ 只读旧按天键快照（过渡期历史；固定前缀无日期，该模式对固定前缀无意义）
bash scripts/restore-large-json.sh --date 2026-09-25

# ④ 还原全部文件（并集）：固定前缀全部文件（最新完整副本）∪ 所有 legacy 历史日期目录
#    全部文件池；每个文件取「含它的最新一个日期」快照，同文件固定前缀优先。过渡期最新
#    legacy 目录可能是首跑中断半截（有文件只在更老日期有快照），并集保证不漏任何一个
#    R2 上存在的备份对象；固定前缀缺文件时会打印醒目警告（含 N 个来自非最新 legacy 日期）。
bash scripts/restore-large-json.sh --all

# ⑤ 可选 [--target <dir>] 显式指定目标目录（默认见下；可加在任意位置）
bash scripts/restore-large-json.sh --list --target /tmp/restore-test
```

**云上 / mac 恢复示例（默认路径已随 REPO 推导，无需再传 --target）**：

```bash
# 云上（生产数据仓库 = /home/ubuntu/code/trade-data）：裸调用即落到生产原位
#   注：云上无 /home/ubuntu/code/trade/（那是本机 mac 代码仓路径）；云上代码仓 = trade-data-signal，
#   经 trade-data/scripts → trade-data-signal/scripts 符号链接访问（2026-10-18 ssh 只读实核）
ssh ubuntu@<云上> 'bash /home/ubuntu/code/trade-data/scripts/restore-large-json.sh signal_kelly_trades.json'
# mac（生产数据仓库 = /Users/linhuichen/code/trade-data）：默认同样落生产原位
bash scripts/restore-large-json.sh signal_kelly_trades.json
```

**恢复目标**（2026-10-17 用户拍板改**随 REPO 推导**，推翻 09-25 mac 常量默认）：默认
= `<生产数据仓库根>/data/`，三级回退 **① `STATICDATA_REPO`（显式覆盖/测试用）② 随
`REPO`/`GIT_REPO` 推导（`GIT_REPO` 的兄弟 `trade-data` 优先，其次 `REPO` 本身；由
`lib/repo_paths.sh` 的 `resolve_repo` 解析）③ mac 常量 `/Users/linhuichen/code/trade-data`
末位兜底**。云上裸调用时不再误指 mac 路径 ⇒ 落到生产数据目录 `trade-data/data/`。这些大 JSON
的生产"家"就是 `trade-data/data/`（git 不再跟踪它们），恢复回生产原位与 `db.py`/`export.py`
读的库同源，不随 cwd 漂移。**非默认目标目录（覆盖了 `STATICDATA_REPO` 或传 `--target`）会打印醒目
警告**：可能是别的目录，直接覆盖有风险，测试临时目录也应看清再继续。

**还原行为安全网（全在脚本内）**：
- 先下到同目录 `.tmp`（pid+随机）再 `os.replace` 原子覆盖，读侧要么旧完整要么新完整，绝不半截
- 覆盖前把原文件备份成 `<文件>.bak-<时间戳>`（`copy2` 副本，旧文件在替换前始终在位，无短暂缺失窗口，可回滚）
- gzip 解压；manifest（先 `<staticdata 备份仓库>/docs/large-json-backup-manifest.md`，回退 trade 仓库旧路径）有该完整 R2 key（固定前缀或旧按天键均可）的 sha256 记录则比对，不匹配即中止（不改名跳过并汇总非 0 退出）
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
| 第 2 层 | R2 私有桶 `signal-backup2` 的 `backup/`（DB）/ `decommissioned/`（退役归档） | **`large-json/` 前缀固定格式完整副本**（#126，唯一副本不滚动删）+ legacy 按天旧快照（7 天宽限期后清理） |
| 第 3 层 | 本地 `data/backups/` 热备 | 大 JSON 本地保留当前副本（`data/` 下），历史版本只在 R2 |
| 第 4 层 | 公开桶（对外只读） | 不涉及（大 JSON 体积大且频繁变，不进公开层） |

**一句话**：大 JSON 从 git 层搬到 R2 私有桶版本化层，`signal-backup2` 桶仍是 DB + 大 JSON 的
统一异地灾备锚点；恢复侧统一入口 = `restore-large-json.sh`。
