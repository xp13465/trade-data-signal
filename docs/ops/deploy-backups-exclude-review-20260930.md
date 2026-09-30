# reviewer 独立复核:deploy.sh rsync 镜像侧加 --exclude=backups/

- 复核对象:feat 分支 `worktree-agent-ac60cb83bbdea434e`,commit `c4756a8ee`
- 复核时间:2026-09-30
- 复核人:reviewer agent(独立复核,不复用实施者脚本/结论)
- 结论:**PASS**(无阻断级 finding)

## 0. 改动内容
`scripts/deploy.sh:518-520` 的 data/ 镜像 rsync(trade-data -> trade 双仓)在既有排除链
`logs/ notify_dedup.json alert_state.json alerts/ warning_*` 之后加 `--exclude=backups/`,不引入 `--delete`。
commit 仅含 deploy.sh 1 行改动 + 修复落档文档(docs/ops/deploy-backups-exclude-fix-20260930.md),无夹带。

## 1. dry-run 前后对照(独立复现,本机双仓)
命令:
```bash
rsync -an --out-format='%n' --exclude='logs/' --exclude='notify_dedup.json' \
  --exclude='alert_state.json' --exclude='alerts/' --exclude='warning_*' \
  /Users/linhuichen/code/trade-data/data/ /Users/linhuichen/code/trade/data/ > /tmp/rsync_old.txt
rsync -an --out-format='%n' --exclude='logs/' --exclude='notify_dedup.json' \
  --exclude='alert_state.json' --exclude='alerts/' --exclude='warning_*' --exclude='backups/' \
  /Users/linhuichen/code/trade-data/data/ /Users/linhuichen/code/trade/data/ > /tmp/rsync_new.txt
diff /tmp/rsync_old.txt /tmp/rsync_new.txt
```
结果:
- 旧命令待传 112 条,新命令待传 19 条。
- diff 仅删 `backups/` 及其下 93 个 .db/.db-shm/.db-wal(6,98d5),**其余 19 条逐条不变**(无新增/无修改)。
- ①backups/ 不再出现在待传清单 ✓ ②其余待传清单逐条不变 ✓ ③确认命令无 --delete(实测 grep 0 处)。

## 2. 反向查「谁在读镜像 data/backups」——无消费方
全仓 grep(scripts/app/worker/static-site/upload_r2.py/restore 链)逐条核:
- `backup_db.sh`:写**权威源** `$REPO/data/backups`(trade-data 侧),不读镜像;RETAIN_DAYS=7 正常清理源侧。
- `verify_backup.sh`:从 R2 `signal-backup` 桶下载到 /tmp 临时目录演练,只读 `$REPO/data/*.db` 实时 DB 对比,不读镜像 backups。
- `restore-r2-backup.sh`:从 R2 `decommissioned/` 前缀恢复,不读镜像。
- `upload_r2.py cmd_upload_db`:读权威源 `$REPO/data/*.db`(实时 DB),非 backups 目录。
- R2 大 JSON 通道(upload-data-large/upload-all-data/upload-data-files/...):源 = `STATIC_DIR/data` = `static-site/data/*.json`,**不含** `data/backups`。
- app/ 的 "backup" 全部为 `buy_backup` 信号类型,与目录无关;worker/ 无引用。
- 镜像 `data/.gitignore` = `*`(仅保留 .gitignore),git 不 track,无任何代码路径消费。
**结论:镜像 data/backups 无任何消费方;本次加排除只断增量,不影响任何老功能。**

## 3. --exclude=backups/ vs --exclude=/backups/ 语义差别 + 误伤实测
- 语义:`backups/`(无前导斜杠)匹配 rsync 源根下**任意层级**名为 backups 的目录;
  `/backups/` 仅锚定**根层**。
- 实测(临时目录构造 src/a/backups/ + src/backups/):
  - `--exclude='backups/'` → 两者均排除(剩 a/ normal.txt)
  - `--exclude='/backups/'` → 仅根层排除(a/backups/ 仍传)
- 本仓 `find data/ -type d -name backups` 结果:**仅根层一个** `/Users/linhuichen/code/trade-data/data/backups`,无嵌套、无同名非目录实体 ⇒ `backups/` 不误伤任何嵌套路径,与 `/backups/` 在本场景等价。

## 4. 影响面(调用方)
- 该 rsync 位于 `deploy.sh` 内 `[ "$REPO" != "$GIT_REPO" ]` 分支,仅双仓(trade-data 采集侧)触发;
  调用方 = update_all.sh 主链 + 各 backfill(etf_national_team_backfill 等),均只把 deploy.sh 当 push 入口,不依赖镜像 backups 内容。
- 新行为下:backups 不再镜像堆积;权威源仍由 backup_db.sh 写+7 天清理;R2 备份链、verify 演练、restore 链全走 R2/权威源,零退化。
- 唯一需要留意的读镜像路径:`build_board_etf_map.py:338` 回退读 `trade/data/etf_national_team.db`(镜像根层 DB,非 backups),本改动不影响根层 DB 同步。

## 5. 语法/夹带
- `bash -n scripts/deploy.sh` → 语法 OK。
- 完整 diff = 1 行(deploy.sh)+ 修复落档文档,无其他参数/逻辑变化,无 `--delete`。

## 6. §23.7 冻结契约边界
改动 = 只加 exclude(只断增量),**不清存量**(镜像历史残留仍在),**不动恢复能力**
(恢复链路全部走 R2 私有桶 + 权威源,镜像 backups 本就无消费方)。与用户拍板「低风险档(推荐)…同时根治防止再堆」一致,未超出边界。

## 7. 结论
**PASS**,无阻断级 finding。

## 8. 备注(非阻断)
- 存量:镜像侧历史残留(本机 10G / 云上据根因报告 6.7G/38 份)本次**有意不清**;因无消费方且 .gitignore=*,
  后续如需释放磁盘可人工删除(建议主控单独安排,不进本次改动)。
- 低风险:`backups/` 匹配任意层级,若未来 data/ 下新增嵌套同名 backups 目录会被一并排除;
  当前无实害(仅根层一个),若求严格可改 `/backups/` 锚定根层,非必须。
