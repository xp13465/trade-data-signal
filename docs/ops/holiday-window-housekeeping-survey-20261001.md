# 假期窗口重活三件套 + 本地镜像残留 —— 精确勘查报告(2026-10-01)

> 调研:researcher agent(只读,全程零 kill,零写除本文档),2026-10-01。
> 全部数字为当日云上(122.51.111.173)+ 本机 mac 只读实测。原挂账理由「等 #126 收口验证通过」已满足(#126 收口 2026-10-01 01:17 commit `ee4a582c4` + 独立 reviewer PASS)。
> 结论先行:可回收合计 ≈ **20.4G(实测)**,其中**不可逆须用户点头 = _backup_126 3.2G + 本机 backups 13.2G(16.4G)**;可逆/低风险可直接做 = swap 缩容 3.0G + git gc ≈0.97G。
> 两条硬红线均遵守:8.3G 旧镜像 `~/code/trade-data-signal-staticdata-old-20260926` 未碰(到期 2026-10-30 复核);全程零 kill,判据 = PPID 属主链(仅用于描述,本任务未执行任何 kill)。

---

## 1. 项1 swapfile 缩容 4.0G→1.0G(省 ≈3.0G)

### 哪台机 / 当前实测
- **云上** ubuntu@122.51.111.173,非本机。mac 的 `vm.swapusage total 16G / used 14.9G` 是 macOS 动态交换,不可像 Linux swapfile 那样缩,且 mac 可用盘 120G 不紧张。
- `/swapfile` 4.0G(2026-09-12 17:11);`swapon --show` → 4G / used **100.8M**(2.5%)。
- 物理内存 MemTotal **3.6Gi**(3808588 kB);`free -h` → 总 3.6Gi / 用 280Mi / **可用 3.1Gi**。
- `/proc/pressure/memory` → some/full 的 avg10/60/300 全 **0.00**(零内存压力)。
- `/etc/fstab` 已登记 `/swapfile none swap sw 0 0`。

### 缩到多少 & 决定依据
- **目标 1.0G**(省 3.0G)。依据(数据三证):当前 swap 用量 ~100M(历史观测峰值 ~120M)→ 1G = 现用量的 ~10 倍余量;RAM 可用 3.1G + 压力 0.00;生产任务轻量(最重为 deploy/public_fund 导入,不碰 swap)。512M 也能撑但余量边界更紧,默认 1G。之前 B1 拍板口径即 4.1G→1G,保持一致。
- 注:云盘已从 92% 降到 77%(13G 可用),本项非紧急,属假期窗口优化。

### 执行方案卡
- **目标路径** `/swapfile`
- **当前实测** 4.0G swap(used 100.8M)
- **目标状态** 1.0G
- **完整命令**(安全顺序,**先建新 swap 再卸旧,全程 ≥1G swap、无零 swap 窗口**;fstab 已引用 `/swapfile`,改名后原条目仍有效)
  ```bash
  ssh -i ~/tdsignal.pem -o BatchMode=yes -o ConnectTimeout=15 ubuntu@122.51.111.173 \
    'sudo fallocate -l 1G /swapfile.new && sudo chmod 600 /swapfile.new && sudo mkswap /swapfile.new && sudo swapon /swapfile.new && sudo swapoff /swapfile && sudo rm /swapfile && sudo mv /swapfile.new /swapfile && swapon --show'
  ```
- **预计耗时** <1min
- **风险** 中低:swapoff 时 100M 需搬进 RAM(可用 3.1G,零压力);顺序法保证全程有 ≥1G swap。本操作不碰 R2 锁/DB,不与盘后定时任务冲突。
- **回退办法** 原样重建:`swapoff /swapfile && rm /swapfile && fallocate -l 4G /swapfile && mkswap && swapon`。
- **不可逆?** **否**(可重建)

---

## 2. 项2 git gc(省 ≈0.97G)

### 哪个仓 / 当前实测
- **两个都是云上仓**,本机无可回收:
  - tds `/home/ubuntu/code/trade-data-signal/.git` **2.1G**:garbage **16** / size-garbage **580.72M**(16 个 `tmp_pack_*` 中断残留)。
  - staticdata `/home/ubuntu/code/trade-data-signal-staticdata/.git` **4.3G**:garbage **2** / size-garbage **393.00M**(`tmp_pack_thsl6p` 355M + `tmp_pack_pCFugV` 56M)。
  - 本机 `~/code/trade/.git` **1.7G**:garbage **0**(count-objects 实测),无需 gc。
- **回收量实测**:580.72M + 393M ≈ **973M ≈0.97G**。注:此前预估 1.3G 把 staticdata garbage 455M 与其中含的 tmp_pack 340M 重复计数,实为 0.97G。另有 loose 对象(tds 3550 / staticdata 17628)随 gc 打包,回收量再加少量(未计入)。

### 跑 gc 期间哪些定时任务会撞(§14 盘后时点清单 + 实测)
- **会撞 git 锁**:staticdata 仓每 **:01/:45 fetch-news** 触发 `staticdata_backup_async` git commit(今日实测提交 18:01/18:46/19:01/19:45);**20:07 / 21:30 etf-national、21:00 backup-db** 亦触发 backup 提交;**05:00 us-stock、08:00/19:15 rzhb、17:50 update-all** 走 deploy.sh 链。gc 撞上 = git index.lock 竞争 → 该轮备份 commit 失败 → 发「staticdata 备份失败」告警(非致命,下轮 :01/:45 自愈)。
- **不必停 trade_deploy.lock 队列**:该锁是 deploy 流水线互斥,与 gc 的 object lock 不同;gc 启动前只需 `ps` 确认无 git/deploy/backup 进程 + `flock -n` 测锁空闲(本任务只读实测:此刻**无**相关进程、锁**空闲**)。
- **建议窗口**::02~:44 或 :46~:00(刚过 fetch-news 触发点),最长窗口 ~43min,足够。

### 执行方案卡
- **目标路径** 云上两仓 `.git`
- **当前实测** tds 2.1G / staticdata 4.3G
- **目标状态** 各回收 garbage(580M / 393M)
- **完整命令**
  ```bash
  ssh -i ~/tdsignal.pem -o BatchMode=yes -o ConnectTimeout=15 ubuntu@122.51.111.173 \
    'ps -eo pid,args | grep -E "staticdata_backup|deploy.sh|git " | grep -v grep; flock -n /tmp/trade_deploy.lock -c "echo LOCK_FREE" && cd /home/ubuntu/code/trade-data-signal && git gc --prune=now'
  ssh ... 'cd /home/ubuntu/code/trade-data-signal-staticdata && git gc --prune=now'
  # 收尾:git -C <repo> count-objects -vH | grep size-garbage;再验下轮 :01/:45 备份 commit 正常
  ```
- **预计耗时** 每仓 3~15min(staticdata 2.45G pack + 17628 loose 更久,选 :02~:44 窗口足够)
- **风险** 中低:与 backup commit 撞锁会有一轮告警(非致命,下轮自愈);**可达对象零删除**(9 目录历史 commit 仍是收口 `ee4a582c4` 的祖先链,不因 gc 丢);`--prune=now` 只清 unreachable/垃圾(tmp_pack)。
- **回退办法** 无(gc 删的是垃圾 tmp_pack,不可恢复但无价值);对可达数据零影响,不构成需回退场景。
- **不可逆?** **否**(对数据安全;gc 是标准维护,删除对象仅垃圾)

---

## 3. 项3 `_backup_126` 预迁移备份 3.2G

### 精确路径 / 内容
- `/home/ubuntu/code/_backup_126_staticdata_before_migrate` **3.2G** = `.git` pack **1.2G** + `data` 工作区 **2.0G**(fund_nav 578M / nav_bucket 533M / parts 342M 等迁移时点快照)+ config/docs/db 等小文件。
- 完整 clone:`git remote -v` origin → `/home/ubuntu/code/trade-data-signal-staticdata`;HEAD **5242b7459**(2026-09-28 19:01),rev-list --count = 1008 = 主仓迁移前 HEAD。

### #126 收口验证通过后还有没有回退价值(**对照 plan 文档 §8/§9,§3/§7 已作废**)
- **没有独立回退价值**。证据四证:
  1. **收口已 PASS**:commit `ee4a582c4`(2026-10-01 01:17)已 push origin/main,独立 reviewer 复核 PASS,9 目录磁盘文件与迁移前基线逐位一致(fund_nav 26458/etf 1718/accum 1717/trade_sim 504/lab 65),commit 内容纯净(31235 D 零混入)。
  2. **主仓 .git 仍含全部祖先 commit**:5242b7459 是 ee4a582c4 的 parent,9 目录 git 历史**未丢**;撤销收口可用主仓自身完成(把 9 目录 `git add` 回索引),无需 _backup_126。
  3. **R2 有完整异地副本**:fixed-prefix 31663 key / MISSING=0 / 5/5 md5 与磁盘一致(#130 固定前缀增量根治后,跨天可累积)。
  4. **plan 文档 §8 已证伪短窗分批/C 自然收敛,§9 记录 #130 已实现**;§3/§7 已作废。_backup_126 是 §3.5 step1「首窗前备份」的产物,其使命(迁移执行前回退保险)在收口 PASS 后**已终结**。
- ⚠️ 补充:迁移脚本首窗会 `rm -rf` 重建该目录(clone 计划 §3.5 step1),现副本冻结在 09-28。

### 执行方案卡
- **目标路径** `/home/ubuntu/code/_backup_126_staticdata_before_migrate`
- **当前实测** 3.2G(1.2G .git + 2.0G data)
- **目标状态** 删除
- **完整命令**
  ```bash
  ssh -i ~/tdsignal.pem -o BatchMode=yes -o ConnectTimeout=15 ubuntu@122.51.111.173 \
    'lsof +D /home/ubuntu/code/_backup_126_staticdata_before_migrate | head; sudo rm -rf /home/ubuntu/code/_backup_126_staticdata_before_migrate && df -h / | tail -2'
  ```
- **预计耗时** <1min
- **风险** 低:主仓即权威,数据仍三处留存(云上磁盘 / R2 / 主仓 git 历史)。删前 lsof 验无进程占用。
- **回退办法** 不可(删除不可恢复);可选替代:删除前 `git clone --no-hardlinks` 一份到 /tmp 留 24h 观察(非必需)。
- **不可逆?** **是**(删除类)

---

## 4. 项4 本机 mac 镜像仓 backups 残留 ≈13.2G

### 精确路径 + 逐项体积 + 每项是否还有用
| 路径 | 体积 | 内容 | 是否有用 |
|---|---|---|---|
| `~/code/trade/data/backups` | **10G** / 90 文件(88 纯 .db) | etf_national_team + sentiment 每日备份,07-18~09-11(7月 28 / 8月 42 / 9月 18) | **冻结残留,无用**:mac 迁云(09-13)后无新写入(最新 09-11 20:15);全仓 grep 唯一引用 `scripts/backup_db.sh:8` 只是路径注释,无任何消费方(与云上 deploy-backups-exclude 复核同型:镜像 backups 无消费方);双树 md5 与下条副本一致 |
| `~/code/trade-data/data/backups` | **3.2G** / 114 文件(22 纯 .db + 92 个 .shm/.wal 空壳) | 同源的重复子集(08-03~09-11,22 个 .db)+ 92 个 0 字节 sidecar | **纯重复残留,无用**:同批备份的双份副本;92 个 sidecar 是 SQLite 空壳垃圾 |

- **md5 抽查一致**:`etf_national_team_20260911_2015.db` 双树均 `c8f7b36d7d64504ba1323d049bb127af` → 同批备份双份。
- **价值评估**:live DB(public_fund/etf/sentiment)为累积型,旧快照内容大部分已被 live 库覆盖;云上有 7 天滚动备份 + R2 upload-db 异地;mac 侧无消费方。**基本无用**。唯一保留理由 = 它们是「mac 生产机时代(09-13 前)」留存的点快照,删除不可逆 → **必须用户拍板**。
- **旁注(同源但不在本项)**:`~/code/trade/data/release` **657M**(08-10 四 DB tar.gz:public_fund 552M/etf 51M/sentiment 36M/stock 19M)+ 两仓 `.bak*` 合计 **602M**(07-28~09-09 六文件)+ `~/code/trade-data/data/logs` **354M / 6018 文件**(部分活跃,sensenova-rotate.log 今日 19:50 在写 → 不宜当纯残留,可单列 logrotate 优化)。

### 执行方案卡(两目录同构)
- **目标路径** `~/code/trade/data/backups`(10G)/ `~/code/trade-data/data/backups`(3.2G)
- **当前实测** 10G(90 文件)/ 3.2G(114 文件)
- **目标状态** 删除
- **完整命令**
  ```bash
  du -sh ~/code/trade/data/backups ~/code/trade-data/data/backups   # 删除前留档
  rm -rf ~/code/trade/data/backups ~/code/trade-data/data/backups
  du -sh ~/code/trade ~/code/trade-data                              # 收尾
  ```
- **预计耗时** <1min
- **风险** 低(无消费方、数据冗余、双份重复);删除前可 tar 归档到 /tmp 留 24h 观察(可选)。
- **回退办法** 不可;可选替代:先 `tar czf /tmp/mac-backups-2026-10-01.tar.gz ~/code/trade/data/backups ~/code/trade-data/data/backups` 留档再删。
- **不可逆?** **是**(删除类)

---

## 5. 汇总:4 项合计可省 ≈20.4G,不可逆 16.4G

| # | 项 | 实测体积 | 不可逆? | 用户点头? |
|---|---|---|---|---|
| 1 | swap 4G→1G(云上) | **3.0G** | 否(可重建) | 否(低风险可做,建议主控确认一次) |
| 2 | git gc(云上 tds+staticdata) | **≈0.97G** | 否(对数据零影响) | 否(需定窗口,建议主控确认) |
| 3 | `_backup_126` 删除(云上) | **3.2G** | **是** | **必须** |
| 4 | 本机 backups ×2(mac) | **13.2G** | **是** | **必须** |
| **合计** | | **≈20.4G** | **不可逆 = #3+#4 = 16.4G** | |

- **可逆/低风险可直接做**:#1 swap 缩容、#2 git gc(选 :02~:44 或 :46~:00 窗口,先 ps 验无进程)。
- **不可逆必须用户点头**:#3 _backup_126(回退价值已耗尽,#126 收口 PASS 后)、#4 本机 backups(冻结残留双份,无消费方)。
- **红线遵守**:`~/code/trade-data-signal-staticdata-old-20260926`(**8.3G**,用户 09-30 拍板保留至 2026-10-30,memory `staticdata-old-mirror-keep-decision`)**未碰、未建议删**;全程**零 kill**(PPID 属主链判据仅用于说明,执行方仍须遵守)。

---

## 复现段(全部只读命令 + 关键输出)

```bash
# 云上(ssh -i ~/tdsignal.pem -o BatchMode=yes -o ConnectTimeout=15 ubuntu@122.51.111.173)
df -h /                                  # 44G 已用 / 13G 可用 / 77%
free -h; swapon --show; ls -lh /swapfile # 总 3.6Gi/用 280Mi/可用 3.1Gi;swap 4G used 100.8M;4.0G
cat /proc/meminfo | grep -E "MemTotal|SwapTotal|SwapFree"   # 3808588 / 4194300 / 4091068 kB
cat /proc/pressure/memory                # some/full avg10/60/300 = 0.00
grep -i swap /etc/fstab                  # /swapfile none swap sw 0 0
git -C /home/ubuntu/code/trade-data-signal count-objects -vH          # size-pack 1.38G / garbage 16 / 580.72M
git -C /home/ubuntu/code/trade-data-signal-staticdata count-objects -vH # size-pack 2.45G / garbage 2 / 393.00M
ls /home/ubuntu/code/trade-data-signal-staticdata/.git/objects/pack/ | grep tmp  # tmp_pack_thsl6p 355M + pCFugV 56M
du -sh /home/ubuntu/code/*/.git           # _backup_126 1.2G / tds 2.1G / staticdata 4.3G
du -shx /home/ubuntu/code/_backup_126_staticdata_before_migrate       # 3.2G(.git 1.2G + data 2.0G)
git -C .../_backup_126... log -1 --format="%h %ci %s"                  # 5242b7459 2026-09-28 19:01
git -C .../_backup_126... remote -v                                     # origin=staticdata 主仓
git -C /home/ubuntu/code/trade-data-signal-staticdata log --format="%h %ci %s" -5  # 收口 ee4a582c4 后备份已恢复(18:01/18:46/19:01/19:45)
ps -eo pid,ppid,args | grep -E "staticdata_backup|deploy.sh|git |migrate" | grep -v grep  # 空(无进程)
flock -n /tmp/trade_deploy.lock -c "echo lock_free"                    # lock_free(锁空闲)

# 本机 mac
swapon --show(无,命令不存在);sysctl vm.swapusage   # total 16G / used 14.9G(macOS 动态交换,不可缩)
du -sh ~/code/trade/data/backups ~/code/trade-data/data/backups        # 10G / 3.2G
ls ~/code/trade/data/backups | wc -l                                   # 90(88 纯 .db,07-18~09-11,按月 28/42/18)
ls ~/code/trade-data/data/backups | wc -l                              # 114(22 纯 .db + 92 个 .shm/.wal)
md5 -q ~/code/trade/data/backups/etf_national_team_20260911_2015.db ~/code/trade-data/data/backups/etf_national_team_20260911_2015.db  # c8f7b36d...(逐位一致)
grep -rn "data/backups" ~/code/trade/scripts ~/code/trade-data/scripts # 仅 backup_db.sh:8 路径注释,无消费方
git -C ~/code/trade count-objects -vH                                  # garbage 0(本机无需 gc)
ls -lt ~/code/trade/data/release | head -4                             # 08-10 四 DB tar.gz 657M
du -sh ~/code/trade-data/data/logs                                     # 354M / 6018 文件(部分活跃)
git branch --show-current                                              # main(本仓未切分支)
```
