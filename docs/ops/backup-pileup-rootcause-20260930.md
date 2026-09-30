# 云上主库备份无限堆积根因(2026-09-30,researcher 只读调查)

> 任务:定位 `/home/ubuntu/code/trade-data-signal/data/backups`(6.7G/38个/最老 20260913_1434)堆积根因。
> 全程只读(ssh BatchMode,零写/零 kill/零 git 写)。文档含复现段,每条结论附原始命令。

## 一、三问直答

1. **哪份备份权威?** → `trade-data/data/backups`(systemd 每日 21:00 backup_db 生成+7天清理生效)+ R2 `signal-backup`(upload-db 异地,日/周/月分层,verify_backup 从 R2 演练恢复)。
   `trade-data-signal/data/backups` = 无清理的过期镜像,**恢复时不该读它**。
2. **堆积的确切环节** → **deploy.sh 1.7 的 rsync**(L518-519):每次部署把 `$REPO/data/`(trade-data 数据树)**整树**(含 `data/backups/`)镜像到 `$GIT_REPO/data/`(trade-data-signal),**无 `--delete` 且未排除 `backups/`** → 源侧被 backup_db 清理掉的旧文件在镜像侧永远残留。
3. **清理为何没生效** → 双因叠加:①backup_db 的 `find -mtime +7 -delete`(L80-82)只作用于 `$BACKUP_DIR`(systemd REPO=trade-data → 只清 trade-data/data/backups),镜像侧无任何清理逻辑;②deploy 的 rsync 无 `--delete` → 目的端多余文件永不删。只增不减。

## 二、证据链

| # | 结论 | 证据 |
|---|---|---|
| E1 | systemd backup 显式 REPO=trade-data,写 trade-data/data/backups | `systemctl cat trade-backup-db`:`Environment=REPO=/home/ubuntu/code/trade-data`,`ExecStart=/bin/bash /home/ubuntu/code/trade-data/scripts/backup_db.sh` |
| E2 | 两仓 backups 文件名+mtime+大小逐日一致(09-23~09-30),堆积仓多 09-13~09-22 共 20 个旧文件 | 两仓 `ls -la data/backups/`:如 `sentiment_20260930_2100.db` 两边同为 133480448 B、mtime `Sep 30 21:00`;堆积仓最老 `etf_national_team_20260913_1434.db`(迁移日手动备份) |
| E3 | md5 逐位一致 → 同文件复制,非独立生成 | `md5sum 两仓 sentiment_20260930_2100.db` 均 `80e4ac404dfa60a62acffe1156f50163`;etf 均 `34b0fd8bf5257689141a7f64ba8faea2` |
| E4 | **复制链路 = deploy.sh 1.7** | `scripts/deploy.sh:518-519`(云上同):`rsync -a --exclude=logs/ --exclude=notify_dedup.json --exclude=alert_state.json --exclude=alerts/ --exclude=warning_* "$REPO/data/" "$GIT_REPO/data/"` — **无 --delete、未排除 backups/** |
| E5 | deploy 在云上以双仓模式跑(触发 1.7) | `systemctl cat trade-update-all`:REPO=/home/ubuntu/code/trade-data,GIT_REPO=/home/ubuntu/code/trade-data-signal;1.7 条件 `[ "$REPO" != "$GIT_REPO" ]` 恒真。触发点=deploy 全部调用方(update_all 17:50 + etf/futures/public_fund_daily/lhb/rzhb/public_fund_full/quarterly) |
| E6 | 镜像侧无任何清理 | 两仓 `grep -rn "backups" scripts/*.sh` 无对 `data/backups` 的 find -delete;backup_db 全仓唯一调用点=systemd trade-backup-db(REPO=trade-data);`crontab -l` 无相关项 |
| E7 | 镜像侧不进 git,纯磁盘 | `trade-data-signal/data/.gitignore` 内容 `*` + `!.gitignore`(tracked);`git check-ignore -v data/backups` 命中,`git status` 无输出 |
| E8 | 恢复路径不读镜像 | verify_backup.sh 从 R2 signal-backup 下载演练;upload_r2.py `cmd_upload_db` 读 `$REPO/data`(REPO=trade-data);restore-r2-backup.sh 从 R2 decommissioned/ 恢复。全仓无脚本读 GIT_REPO/data/backups |
| E9 | 清理逻辑本身在源侧正常 | `trade-data/data/backups` 仅 16 个文件(09-23~09-30,7 天边界),backup_db.sh L22 `BACKUP_DIR=$DBDIR/backups`、L23 `RETAIN_DAYS=7`、L80-82 `find "$BACKUP_DIR" -maxdepth 1 -name '*_*.db' -mtime "+7" -print -delete` |

## 三、根治方案(用户已授权另一 agent 做一次性历史清理,本方案只管增量+未来)

### 方案 A(推荐,改动 1 行):deploy.sh 1.7 的 rsync 加 `--exclude=backups/`
- **改哪个文件哪几行**:`scripts/deploy.sh` L518(云上 `/home/ubuntu/code/trade-data-signal/scripts/deploy.sh` 同),在 `--exclude=warning_* \` 后加 `--exclude=backups/ \`
- **改动性质**:纯新增排除项,与已有 `logs/`、`alerts/`、`notify_dedup.json` 同模式(镜像侧不需要备份副本)
- **改变生产行为**:是,但范围极小 — `trade-data-signal/data/backups` 停止增长。该目录无任何消费方(见 E8),恢复走 trade-data + R2,零影响
- **§5.4⑥ 版本升级**:不触发(不碰 AI 推荐/降亏过滤,不动数据产物口径)
- **取舍**:存量 6.7G 不在本方案内(已另派一次性清理 agent);`--delete` 不加(会把 data/ 下其他目的端独有文件如 `*.db.bak-lof/spikefix/accumnav` 历史安全快照一并删掉,破坏恢复能力)——排除式根治,不引入 delete

### 方案 B(可选加固,防御未来同类):backup_db.sh 或部署链对镜像目录补一条同款清理
- 在 deploy.sh 1.7 rsync 成功后追加:`find "$GIT_REPO/data/backups" -maxdepth 1 -name '*_*.db' -mtime "+7" -delete`(与 backup_db.sh L80-82 同款)
- **取舍**:A 已断源头,B 是兜底。两者可并用;若只做 B 不做 A,每日仍白拷 ~400-500MB(增量镜像持续存在,浪费 IO/磁盘) → **A 为主,B 可选**

### 一次性历史清理(已授权另一 agent,非本方案)
- 清 `trade-data-signal/data/backups/` 全部 38 个文件(6.7G)。依据:它们全部是 trade-data 的过期镜像副本(09-23~09-30 有 trade-data 现役正本,09-13~09-22 源侧已按 7 天策略删除、属过期历史),恢复权威=trade-data + R2,删除零风险
- 目标态:该目录删空(或留空壳),后续由方案 A 保证不再增长

## 四、复现段(每条结论的原始命令)

```bash
# E1 备份服务定义(REPO=trade-data)
ssh -i ~/tdsignal.pem -o BatchMode=yes -o ConnectTimeout=15 ubuntu@122.51.111.173 'systemctl cat trade-backup-db'
# E2 两仓备份列表(mtime/大小逐日一致;堆积仓多 09-13~09-22)
ssh ... 'ls -la /home/ubuntu/code/trade-data-signal/data/backups/'
ssh ... 'ls -la /home/ubuntu/code/trade-data/data/backups/'
# E3 md5 逐位一致
ssh ... 'md5sum /home/ubuntu/code/trade-data/data/backups/sentiment_20260930_2100.db /home/ubuntu/code/trade-data-signal/data/backups/sentiment_20260930_2100.db'
# E4 复制链路 deploy.sh 1.7(无 --delete、未排除 backups/)
sed -n '509,526p' /Users/linhuichen/code/trade/scripts/deploy.sh
ssh ... 'sed -n "509,526p" /home/ubuntu/code/trade-data-signal/scripts/deploy.sh'   # 云上同款
# E5 deploy 双仓模式
ssh ... 'grep -E "Environment=|ExecStart|WorkingDirectory" /etc/systemd/system/trade-update-all.service'
# E6 镜像侧无清理 + backup_db 唯一调用点
ssh ... 'grep -rn "backup_db" /etc/systemd/system/'
ssh ... 'grep -rn "backups" /home/ubuntu/code/trade-data-signal/scripts/*.sh /home/ubuntu/code/trade-data/scripts/*.sh'
ssh ... 'crontab -l'
# E7 镜像不进 git
ssh ... 'cd /home/ubuntu/code/trade-data-signal && git check-ignore -v data/backups && git status --porcelain -- data/backups'
# E8 恢复路径(verify/R2/restore 均不读镜像)
grep -nE "download|R2|backups" /home/ubuntu/code/trade-data-signal/scripts/verify_backup.sh
sed -n '1958,1975p' /home/ubuntu/code/trade-data-signal/scripts/upload_r2.py   # cmd_upload_db 读 $REPO/data
# E9 源侧清理正常(16 个=7 天边界)
sed -n '20,23p;78,82p' /Users/linhuichen/code/trade/scripts/backup_db.sh
ssh ... 'systemctl cat trade-backup-db'   # RETAIN_DAYS=7
```

## 五、时间线佐证(为什么最老 09-13)
云上生产环境 ~09-12/09-13 建成(数据文件批量 09-12 落盘),09-13 14:34 为迁移日手动备份(14:34 非 21:00 定时),deploy 双仓 rsync 自迁移起每日复制当日备份入镜像;源侧 7 天清理正常,镜像侧只增不减,累计 38 个 ≈ 6.7G(09-13 大小 131~185MB → 现 253MB,与日均增长 ~400MB 吻合)。

## 六、维度自检
- 基线复现:系统定时任务全在云上,本机纯开发(local-dev-cloud-prod-split),无版本/回测维度 → 不适用
- 已查清单:systemd 全部 40+ timer/unit、crontab、两仓全部 scripts grep(backups/rsync/backup_db/upload-db)、git check-ignore/ls-files、md5 抽样、upload_r2 cmd_upload_db 源路径、verify/restore 恢复路径、云上 deploy.sh 与本地逐字对版
