# deploy.sh 镜像侧排除 data/backups(根治无限堆积)

- 日期:2026-09-30
- 类型:运维修复(deploy.sh rsync 排除项)
- 方案:A(最小充分)——`--exclude=backups/`;不采纳 B(镜像侧补清理,落地后即死代码)
- 状态:已 commit + push feat(分支 `worktree-agent-ac60cb83bbdea434e`)

## 背景与根因(独立 researcher 已确证,实施侧复核通过)
- `scripts/deploy.sh:518-520` rsync 把 `$REPO/data/` 整树镜像进 `$GIT_REPO/data/`,无 `--delete`、未排除 `backups/`。`REPO(trade-data) != GIT_REPO(trade)` 双仓模式恒触发(update_all 17:50 + etf/futures/public_fund 等 8 个 deploy 调用方)。
- 镜像侧零清理:backup_db.sh 的 `find -mtime +7 -delete` 只作用于权威源 `trade-data/data/backups`(systemd timer 显式 `Environment=REPO=/home/ubuntu/code/trade-data`)。
- 权威备份 = `trade-data/data/backups` + R2;镜像那份无人消费(全仓无脚本读 `GIT_REPO/data/backups`;`data/.gitignore` = `*` 不进 git)。
- 完整根因报告:`docs/ops/backup-pileup-rootcause-20260930.md`(含复现段)。

## 唯一写入方复核(硬约束 1,已 PASS)
落地前 grep 全仓确认无第二链路往镜像 `data/backups` 写:
- `grep -rn "GIT_REPO/data" scripts/ app/`:仅 deploy.sh(L249 单文件 cp board_etf_map.json;L518-520 rsync 整树)+ sync_dev_from_r2.sh(L110-132 单文件冻结表双写)。
- `grep -rn "data/backups"` 全仓:仅 docs 说明 + backup_db.sh 自身(写权威源);staticdata_* 目标为 STATICDATA_REPO,且只同步 static-site/data 与 `*.db`,不含 data/backups 目录。
- **结论:deploy.sh:518 的 rsync 是镜像 data/backups 的唯一入口,无第二写入方。**

## 改动(方案 A,最小充分)
`scripts/deploy.sh:518-520` rsync 参数列表新增 `--exclude=backups/`,与既有 `--exclude=logs/`、`--exclude=alerts/` 完全同模式:
```diff
   rsync -a --exclude=logs/ --exclude=notify_dedup.json --exclude=alert_state.json \
-        --exclude=alerts/ --exclude=warning_* \
+        --exclude=alerts/ --exclude=warning_* --exclude=backups/ \
         "$REPO/data/" "$GIT_REPO/data/" 2>&1 | tee -a "$LOG"
```
- 不加 `--delete`(防误删 data/ 下 `*.db.bak-lof` / `*spikefix*` / `*accumnav*` 等历史安全快照)。
- 不给镜像侧补清理逻辑(方案 B 不采纳)。
- 不碰其他文件、不改 rsync 其他参数、不动 `data/.gitignore`。

## 自验
### 1. rsync dry-run 前后对照(硬约束 2,PASS)
本机双仓(trade-data 为 REPO 源)同参数 dry-run:

| 对照项 | 改动前 | 改动后 |
|---|---|---|
| 待传输清单总行数 | 437 | 322 |
| 其中 backups/ 行数 | 115 | 0 |
| 非 backups 清单 | — | diff 为空(逐条一致) |

- 改动前命令:`rsync -an --out-format='%n' --exclude=logs/ --exclude=notify_dedup.json --exclude=alert_state.json --exclude=alerts/ --exclude=warning_* /Users/linhuichen/code/trade-data/data/ /tmp/rsync-dryrun-target/`
- 改动后命令:同上 + `--exclude=backups/`,目标 `/tmp/rsync-dryrun-target2/`
- 输出:`diff <(grep -v '^backups/' /tmp/rsync-list-before.txt) <(grep -v '^backups/' /tmp/rsync-list-after.txt)` 无输出。
- **结论:①backups/ 不再出现在待传输清单(115→0)②其余 data 文件传输清单逐条不变。**

### 2. 语法与改动范围(硬约束 3,4,PASS)
- `bash -n scripts/deploy.sh` PASS。
- `git diff --stat`:1 file changed, 1 insertion(+), 1 deletion(-),仅 deploy.sh 一行。

### 3. §21 算法公示触发判断(硬约束 5,不触发)
- 本次仅改 deploy.sh 的 rsync 排除参数,零算法/数值/口径逻辑变更。
- `git diff --name-only` 无前端/公示文件(purpose-notes.js / app.js / lab.js 零改动)。
- **结论:不触发算法公示。**

## 复现段
1. `bash -n scripts/deploy.sh` → PASS。
2. 改动前后各跑一次同参数 `rsync -an` dry-run(见自验 1)→ backups 从清单消失、其余逐条不变。
3. `git diff scripts/deploy.sh` → 仅 1 行新增 `--exclude=backups/`。
