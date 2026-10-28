# 腾磁盘第一批：部署不再复制 DB + staticdata 不再留 DB 副本 + 补 stock_daily 备份缺口

日期：2026-10-28　角色：实施 agent　分支：`fix/disk-reclaim-20261028`
任务：`#322`(docs/pending-features-index.md)　依据：`docs/ops/system-health-audit-20261028.md` §P0-3 + `/tmp/disk-reclaim-plan-20261028.md`
**本单只改代码 + 测试 + 文档，零删除、零部署、零云上写。**

---

## 1. 依据：三份库副本实测数字（改前）

云上 `df -h /` = 59G 总 / 44G 用 / **13G 可用 / 78%**（2026-10-28 实测）。

| 对象 | 位置 | 改前规模 | 是否有人读 |
|---|---|---|---|
| 代码仓 DB 副本 | `/home/ubuntu/code/trade-data-signal/data/*.db` | **3.63 GB**（19 个 `*.db*`，其中 10 个 `.db`：public_fund 2.95G + etf 258M + sentiment 231M + stock_daily 183M，其余 6 个为空库或 `-wal/-shm` 侧文件） | **零读取方**（所有 unit 带 `REPO=trade-data`；镜像兜底 `gen_daily_brief.py pick_db` / `aggregate_shadow.py _pick_db` 遇文件不存在直接跳过） |
| 灾备仓 DB 副本 | `/home/ubuntu/code/trade-data-signal-staticdata/db/` | **3.38 GB**（16 文件） | **零读取方**（恢复演练一律走 R2：`scripts/verify_backup.sh` + `docs/scripts/restore_r2_db_backup.py`） |
| 主库（唯一活副本） | `/home/ubuntu/code/trade-data/data/*.db` | 3.6 GB 级 | 是（生产链路全部指向它） |

**本单实施中实测补证的两条关键事实：**
1. **R2 上没有 stock_daily 的任何备份对象** —— 只读列举 `signal-backup2` 桶三个前缀，命中数全 0：
   `backup/stock_daily*` = 0、`weekly/stock_daily*` = 0、`monthly/stock_daily*` = 0
   （命令：`REPO=/Users/linhuichen/code/trade-data .venv/bin/python scripts/upload_r2.py list backup/stock_daily signal-backup2`，status=200）。
   ⇒ 两处本地副本停掉后，`stock_daily.db` 真的只剩主库一份，**必须先补 R2 才能删副本**（§25 顺序不可颠倒）。
2. **两份本地 stock_daily.db 都不新**：本机 `trade/data` 与 `trade-data/data` 各 116,633,600 B（mtime 9-12），云上主库 175M 级 —— 说明"副本"是陈旧拷贝，停掉不损数据。

**本次改动解决的浪费**：每次真实部署最多把整个 `data/`（含 DB）再复制一份（10-28 Dry-Run 实测待传 491MB；public_fund 刷新日 ≈3.5G 写放大）；staticdata 每次备份把 3.38G DB 整体重写一遍。

---

## 2. 改动三点（改前 → 改后）

### A. `scripts/deploy.sh` —— 部署不再把 DB 复制进代码仓

- 位置：`scripts/deploy.sh:657-662`（1.7 段「rsync 采集数据」）。
- **改前**：`rsync -a --exclude=logs/ ... "$REPO/data/" "$GIT_REPO/data/"`，只排日志/告警状态/backups/4 个 clone 种子，**DB 全部照搬**。
- **改后**：排除列表**增补** `--exclude='*.db' --exclude='*.db-wal' --exclude='*.db-shm'`（`scripts/deploy.sh:661`）；段首注释与完成日志文案同步改为「数据文件同步…（不含 DB）」（`scripts/deploy.sh:629-631`、`:667`）。
- **为什么不整段删**：这条 rsync 还搬 `daily-k.parquet`(173M)、`holdings_overlap_cache.json`(112M)、`signal_kelly_*` 等非 DB 文件的镜像 —— 只加排除，影响面最小。
- **反例检查（第二处把 DB 复制进代码仓？）**：`grep -rn "GIT_REPO/data" scripts/*.sh` 只剩 `deploy.sh`（`board_etf_map.json` 的 `cp`，JSON 不受影响）与 `sync_dev_from_r2.sh`。**但 `sync_dev_from_r2.sh` 并不只搬 JSON**：实文 `scripts/sync_dev_from_r2.sh:76-79` 把 `sentiment.db` / `etf_national_team.db` 两个库 `cp` 进本机代码仓 `trade/data/`（同时刷 `trade-data/data/`）；它是本机手动跑的 dev 同步脚本（路径写死本机），不在云上部署链里。云上部署链路侧仍由用例 ② 机检守死（新增任何未排除的 rsync / 搬 `.db` 的 cp 都会红）。
- **由此带来的影响（本单之后）**：云上部署不再复制 DB ⇒ 本机 `trade/data` 那份镜像**今后不再被自动刷新**（只有手动跑 `sync_dev_from_r2.sh` 才会更新）。所以「本机读镜像」这件事，要么显式改指 `trade-data/data/`，要么别再假设它是最新的。

### B. `scripts/staticdata_backup_async.sh` —— 本地 DB 副本默认不复制

- 位置：`scripts/staticdata_backup_async.sh:147-161`（step1）。
- **改前**：`rsync -a "$REPO/data/"*.db "$STATICDATA_REPO/db/"` 无条件执行。
- **改后**：整块包进 `if [ "${STATICDATA_DB_LOCAL_COPY:-0}" = "1" ]; then ... fi`，**默认跳过**；跳过时打一行
  `[step1 DB rsync] skipped (DB 本地副本已关闭,需 STATICDATA_DB_LOCAL_COPY=1 开启)`，`STATICDATA_FAIL` 保持 0（不会被误置成失败、心跳结论不变）。
- 心跳语义不变：step 行照打（一条 `skipped`），心跳 result 判定没动。

### C. 补 `stock_daily.db` 备份缺口（本单新发现，先补才敢停副本）

- **只读核实结论**：
  - 本地热备清单：`scripts/backup_db.sh:81-82` 改前只有 `sentiment.db` / `etf_national_team.db`；
  - R2 清单：`scripts/upload_r2.py cmd_upload_db` 的 `targets` 改前只有 `sentiment` / `etf_national_team`（`public_fund` 走单独大库链路）；
  - **R2 上 stock_daily 对象数 = 0**（见 §1）。
- **改后（形态照抄 etf_national_team，不另创风格）**：
  - `scripts/backup_db.sh:82`：`backup_one "$DBDIR/stock_daily.db" stock_daily || RC=1`（失败计入退出码 → 走既有 severe 告警）；
  - `scripts/upload_r2.py:3342`：`targets` 增 `("stock_daily.db", "stock_daily")`，走同一套日/周/月分层（`backup/ weekly/ monthly/`）+ 同一天数（14/28/365）；
  - 文档口径同步：`docs/r2-deployment.md:61`、`:341`、`:350`（DB 清单补 stock_daily；删掉「本地双副本」的旧说法）。
- **没动的东西（按任务约束）**：保留天数（`RETAIN_DAYS=7`、14/28/365、public_fund 7/28/180）一个没改；public_fund 大库链没碰。
- **预算诚实标注**：stock_daily 进链后新增约 **本地 +110MB/天**（7 天 ≈ 0.77GB，落主库 `data/backups/`，与 §P0-3 的 R4「保留天数降到 3 天」是两件事，需另行拍板）；**R2 +≈0.9GB 稳态**（gz 约 30MB/份 × 14+4+12）。这是补缺口的必要成本，不补则是盘毁全失。

---

## 3. 实现预期（X → Y，可观测）

| # | 观测点 | 改前 X | 预期 Y |
|---|---|---|---|
| Y1 | 下次真实部署日志 | 出现 `✓ rsync data/ 完成（DB 同步到 …）` | 出现 `✓ rsync data/ 完成（数据文件同步到 …(不含 DB)）`，全文不再有「DB 同步到」 |
| Y2 | 部署后代码仓 `data/*.db` | 每次部署都被刷新/新建 | 不再新增、不再更新（存量文件要等删除单才清） |
| Y3 | 空转部署待传字节 | 491,109,559 B（含 DB） | 不含任何 `.db`；只剩 JSON/parquet 量级 |
| Y4 | 下轮 staticdata 备份 | step1 搬 3.38G DB、日志 `[step1 DB rsync] 12s` | 日志 `[step1 DB rsync] skipped (…)`，`db/` 不再被写 |
| Y5 | 下轮 `backup_db.sh`（云上 21:00，`trade-backup-db.timer` 的 `OnCalendar=*-*-* 21:00:00`） | 日志只有 sentiment/etf 两条备份成功 | 多一条 `✓ stock_daily 备份完成`，`data/backups/` 出现 `stock_daily_YYYYMMDD_HHMM.db` |
| Y6 | 下轮 `upload-db` | `DB 上传 2/2 → signal-backup2/backup/` | `DB 上传 3/3 …`；R2 出现 `backup/stock_daily_<today>.db.gz` |

> Y5/Y6 依赖云上定时链下一轮实跑（本单不跑脚本、不碰云上）；验证时以日志 + R2 列举为准，不看代码推断。

---

## 4. 证据用例清单（= `scripts/tests/test_253_disk_reclaim_20261028.py`，5 条）

| 用例 | 断言 | 变异判红验证（做过的） |
|---|---|---|
| ① `test_c1_deploy_rsync_excludes_db` | data rsync 逻辑命令含三项 `*.db` 排除；原有 4 个 clone 种子排除仍在；日志文案无「DB 同步到」 | 删掉排除行 ⇒ **红**（实测 1 红 + ② 连带红） |
| ② `test_c2_no_other_db_copy_into_git_repo` | 扫全部逻辑命令（含续行合并）：目标 `$GIT_REPO/data/` 的 rsync 必须三项排除齐全；`cp/mv/tar` 不许搬 `.db` | 同上（漏排除即红） |
| ③ `test_c3_staticdata_db_rsync_gated` | 源码含门控且默认 0；**行为守卫**：把这一块源码抽出来喂 `bash -s` + 假 `rsync`，默认不调用 / `STATICDATA_DB_LOCAL_COPY=1` 才调用 | 把门控改成 `if true` ⇒ **红**（实测） |
| ④ `test_c4_backup_db_includes_stock_daily` | `backup_db.sh` 恰有 1 条 stock_daily 热备调用且带 `|| RC=1`；原两库仍在 | — |
| ⑤ `test_c5_upload_db_includes_stock_daily` | ast 取 `cmd_upload_db` 的 `targets` 实值含 `("stock_daily","stock_daily")`；`_PUBLIC_FUND_RETENTION_DAYS` 里不含 stock_daily（天数不动） | — |

**零执行保证**：不跑 deploy.sh / staticdata_backup_async.sh / backup_db.sh（§18 L48：它们有真实外发能力），③ 只跑抽出来的片段 + 假 rsync；不碰网络；临时目录用完即删。

全量回归：`pytest -q scripts/tests/`（改 `scripts/` 必须全量，L52 —— tests/ 里有源码形状守卫）。

---

## 5. 删除阶段（下一单，本单不执行）：顺序 + §25 前置

**顺序不可颠倒，颠倒会静默建空库 / 丢唯一副本：**

1. **先补备份并验可恢复**：云上跑一轮 `backup_db.sh`（或 `upload-db`），确认 R2 出现 `backup/stock_daily_<today>.db.gz` 且 `verify_backup` 可下载解压 —— 见 `verify_backup.sh` 目前只演练 sentiment/etf，**stock_daily 的恢复演练是遗留缺口**，删除单开工前要么先补进 verify 的 `CHECKS`，要么人工下载 + `PRAGMA integrity_check` 一次并落档（§25②「备份必须实测验证」）。
2. **本单（A/B/C）先 merge 上线**，否则删完下一次部署/备份又把 DB 搬回来。
3. 再停/删存量：代码仓 `data/*.db`（3.51G，保留 0B `trade.db` 种子）+ 代码仓 `data/backups/`（2.88G 僵尸）+ staticdata `db/`（3.38G）+ 代码仓 `*.bak-*`（0.14G）。
   - staticdata 侧注意：`.gitignore` 只排 `db/*.db`，`db/*-shm` / `db/*-wal` **被 git 跟踪**（6 个文件 98KB）⇒ 先 `git rm --cached db/*-shm db/*-wal` 单独提交，再删目录；否则下一次备份 `git add -A` 会在提交里带删除、可能撞大文件闸门。
4. 主库 `data/backups/`（3.46G）只保留 3 天另案拍板，不在本轮。
5. 每一步删除前按 §25：**先备份（tar 到 R2 `decommissioned/` 或异地）→ 全量清单比对 + 抽样 md5 验可恢复 → 再删**；恢复路径写进单里（例：`upload_r2.py download-db sentiment <dir>` / `decommissioned/` 取包）。

---

## 6. 回退办法（每个开关怎么关回去）

| 改动 | 回退动作 | 后果 |
|---|---|---|
| A deploy.sh 排除 | 删掉 `--exclude='*.db' …` 那一行（其余不动） | 下次部署 DB 自动补齐回代码仓（源在主库），不用手工拷 |
| B staticdata 副本 | ①临时要开 = 手动带 `STATICDATA_DB_LOCAL_COPY=1` 跑一次 `staticdata_backup_async.sh`；②长期开回 = 改 `scripts/deploy.sh:1030` 附近的 `systemd-run --setenv`，把该变量传进去（云上**没有** staticdata 常驻 unit：`deploy.sh:1030` 是 `systemd-run` 瞬态起，所以「在 unit 里加环境变量」这条路不存在） | `db/` 立即恢复为最新副本；临时开不改代码，长期开需改 deploy.sh 一行 |
| C stock_daily 备份 | 从 `targets` / `backup_one` 去掉那两行 | 回到"stock_daily 无异地备份"的旧状态（**不建议**，等于回到单副本风险） |

单文件级回滚：`git checkout <merge-base> -- scripts/deploy.sh scripts/staticdata_backup_async.sh scripts/backup_db.sh scripts/upload_r2.py`。

---

## 7. 边界维度清单（⑦ 轴，供审查关独立复核对账）

| 维度 | 测 / 不测 | 说明与理由 |
|---|---|---|
| 输入域（脚本参数/环境变量） | 测 | ③ 行为守卫实测「开关未设」与「=1」两态；A 的排除项按逻辑命令断言三项齐全 |
| 状态组合（部署 vs 手动 / 首次 vs 重复） | 部分测 | 幂等性靠 rsync/git add 天然幂等，未在云上实跑（本单禁部署）⇒ 归下一单观察锚点 Y1–Y4 |
| 时序（定时链时点） | 不测 | 本单不改任何时点、不改调度（禁改项）；下一轮 21:30 backup / 部署日志验证归观察期 |
| 上下游依赖（R2 配额 / staticdata git 闸门 / verify_backup） | 部分测 | R2 增量已估算（≈0.9GB）并落档；`verify_backup.sh` 未加 stock_daily = 已知遗留缺口，已在 §5.1 写明处置，**不静默放过** |
| 极端值（磁盘满 / 大库 183MB 进内存） | 不测 | `cmd_upload_db` 走 `read_bytes()`，116–183MB 与小库同量级（sentiment 221M 早已如此），无新增风险面；磁盘满场景由既有 upload 失败→非零退出覆盖 |
| 回退路径 | 测（静态） | §6 三个开关逐条给出回退动作 + 单文件回滚命令 |
| 并发与重入 | 不测 | 改动只在单条 rsync / 单条备份调用内，不引入新锁、不改 async 的持锁结构 |

来源：A/B/C 三个改动点 + 任务书 D 的五条用例 + §P0-3 的删除阶段顺序。