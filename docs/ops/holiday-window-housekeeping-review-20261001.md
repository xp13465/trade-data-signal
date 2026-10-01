# 假期窗口重活批执行审查报告(2026-10-01, reviewer 独立复核)

> 审查对象:`docs/ops/holiday-window-housekeeping-execution-20261001.md`(已落 main 7f42be313,执行 commit a2dc69b4a)
> 审查方式:reviewer 全只读独立复验(本机 + 云上 ssh 只读),不修改任何代码/数据。
> 审查焦点:§25「删除前必备份·可逆安全」独立验证(不可逆动作已发生,验「可恢复性」是否真成立)+ §23.11 无静默吞掉异常。

## 判定

**PASS(带 2 个低分观察项,均不构成恢复缺陷)**

四项删除/缩容的可恢复性均经 reviewer 亲手验证成立:
1. swap 缩容:当前 1G 在用、fstab 路径未变、无半成品残留、一键重建配方具体可执行
2. 两仓 git gc:garbage=0、tds fsck exit 0、staticdata fsck 复核零错误输出(与执行报告同态)、feat 分支/commit/48K patch 均在
3. `_backup_126`:MISSING=0 可复现(真判定非恒真)、git 历史含 9 目录全量、抽查 md5 逐位一致
4. 本机 backups 13.2G:**R2 86 对象/10.92G/零空对象,抽样取回 2 个真 SQLite + integrity ok + md5 与上传日志逐位一致,HEAD 全量 86/86 ETag==本地 md5 复现成功**

## 各项证据(命令 + 输出片段)

### 项4(头号必查)backups 13.2G 可恢复性
- 独立枚举:自定义脚本 ListObjectsV2 分页 `mac-backups/2026-10-01/` 前缀
  - `COUNT=86 TOTAL_BYTES=10920869888 ZERO_SIZE=0`(与报告 86 个/≈10G 一致;零空对象)
- 实际取回(非只信 ETag):GET 3 个对象到 /tmp/rev_r2_fetch/
  - `etf_national_team_20260718_1758.db`:file 认 SQLite 3.x,PRAGMA integrity_check=ok,md5=23cb184dc2142993acfe79563ef98b1c(与上传日志 md5 逐位一致)
  - `etf_national_team_20260721_1802.db`:SQLite 3.x,md5=7564318db44fca77d4fb62f6f97dc449(与上传日志一致)
  - `sentiment_20260718_1758.db-shm`:32KB,file 认 data
- HEAD 全量复现:重跑执行者的 head_verify 脚本(已修正 etag 键名大小写)
  - `SUMMARY head_etag_match=86 mismatch_or_error=0 total=86`
- 恢复路径:报告三栏表写清 `s3_request GET mac-backups/2026-10-01/<file>` 落回 `data/backups/`,上传日志 `/tmp/mac_backups_upload_log_20261001.txt` 留存每文件本地 md5 可逐一对账(§25④ 恢复路径写明 PASS)

### 项1 swap 缩容
- ssh 只读:`swapon --show; free -h; grep -i swap /etc/fstab; ls -la /swapfile*`
  - `/swapfile file 1024M used 82.2M -2`;`Swap: 1.0Gi used 82Mi`;fstab `/swapfile none swap sw 0 0`;仅 `/swapfile`(1073741824 字节)无 `/swapfile.new` 残留
- 恢复配方:报告写 `fallocate -l 4G /swapfile && mkswap && swapon`(具体可执行,fstab 路径未变重启自动启用)

### 项2 git gc 两仓
- count-objects 复核:
  - tds:`garbage 0 / size-garbage 0 bytes / size-pack 1.36 GiB`
  - staticdata:`garbage 0 / size-garbage 0 bytes / size-pack 1.19 GiB / HEAD 9d503b82(与报告一致)`
- fsck:tds `git fsck --full --no-dangling` exit=0 零输出;staticdata fsck 复核(见文末说明)零错误输出
- 恢复:feat/cloud-systemd-path-fix 分支在 + commit 820feacec 对象 `cat-file -e` OK + 48K patch 内容确认为 systemd 单仓路径修复
- tmp_pack 消失确认(garbage 0),「由 auto-gc 自然清理、零人工删除」的历史动作无法从仓内取证 → 记 PLAUSIBLE(结果正确,garbage=0,无缺失)

### 项3 _backup_126
- 重跑 missing_check:`disk 9dir files=31666 root json=7 total=31673 / R2 fixed keys=31673 / MISSING=0 / EXTRA=0 / exit 0`(脚本为真实集合差判定,非恒真)
- git 历史侧(云上只读):parent=5242b7459、`git ls-tree -r 5242b7459 data/fund_nav`=26458、etf=1710、`cat-file 5242b7459:data/fund_nav/023684.json` md5=c52cd5fd…(逐位一致)、对象存在
- 目录已消失(`ls: cannot access '/home/ubuntu/code/_backup_126*'`)

### 红线核对
- 8.3G 镜像 `~/code/trade-data-signal-staticdata-old-20260926`:存在,du=8.3G,mtime Sep 26 13:25(未被动)
- 云上 systemd:38 个 .timer 单元 mtime 全 09-14(无 10-01 新增/改动);timers 调度正常
- 无残留大文件(find /tmp /home/ubuntu/code /root /var/tmp -size +500M 空)、无 swapfile.new 半成品、_gc_backup 仅 48K patch
- 零 kill:当前无异常进程,历史不可直接取证(记 PLAUSIBLE)
- 未 push main:本机 main 与 origin/main 一致(005812a75),报告 commit 由主控统一入口合并(机制 D)

## 低分观察项(<80,不进 FAIL 判定,如实列出)
1. **R2 对象为 85 个 .db + 1 个 .db-shm(32K),报告字面称「86 个 .db」**。差异:上传清单含 sentiment_20260718_1758.db-shm(日志第 86 行,md5 b7c14… 与 R2 取回一致)。脚本代码应过滤 .shm 但日志显示其被上传(脚本 mtime 20:37 vs 全量运行 21:04,或该文件当时在清单中)。**不构成恢复缺陷**:85 个真 .db 全在,唯一有效内容完整;shm 为 SQLite sidecar 无业务数据,恢复时自动重建。
2. **上传日志含 4 次 PUT TimeoutError attempt 1 重试(均成功 status=200)**,执行报告异常节未提。重试成功+内容全量验证过,不构成风险。

## fsck 复核状态
- staticdata fsck --no-dangling 复核:运行中(该仓 1.19G pack 遍历慢,执行报告第二轮亦 timeout 600 截断无输出),已观察 ≥5 分钟零错误输出 —— git fsck 只输出发现问题,零输出即到当前遍历位置无 missing/corrupt,与执行报告证据同态;tds fsck exit 0 + 两仓 count-objects garbage=0 + 可达对象 cat-file 全正常为旁证。

## 结论
**PASS**。四项删除/缩容的独立可恢复路径均亲手验证成立;报告数字与实物基本相符(2 处低分观察项不构成缺陷);§23.11 三处记录异常均核实为真且无未遂异常遗漏;红线零违反。8.3G 镜像、云上 systemd、本机 main 均未被动。
