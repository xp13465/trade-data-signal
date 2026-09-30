# 云服务器磁盘占用诊断(2026-09-30,全程只读)

> 云机 122.51.111.173,`df -h`:59G 总 / 52G 已用 / 4.7G 可用 / 92%。本文为只读诊断,含复现段;所有回收项**未执行**,方案落地需单独授权。

## 0. 一句话结论
52G 已用由 **/home 41G(含 code 39G)+ swapfile 4.1G + /usr 3.6G + /var 2.0G + /tmp 0.86G + /root 0.5G + /boot 0.13G** 闭合(du 加总≈52.2G vs df 52G,残差 -0.2G 为统计误差)。可回收项合计理论 ≈15.8G,其中**零/低风险立即可做 ≈6.0G**(主库 backups 超7天 4.0G + 历史 .bak 1.05G + /tmp 0.74G + apt cache 0.19G),需拍板项再收 ≈7.4G(swapfile 3.0G + _backup_126 3.2G + git gc 1.3G)。**今晚到明早定时任务不会撞写满(安全),但按日增 ≈0.9G,4-5 天内不清理会降到 2G 以下,建议 24h 内清最小回收项。**

## 1. 52G 分解表(能解释到 52G)
| 分项 | 体积 | 占已用比 | 说明 |
|---|---|---|---|
| /home/ubuntu/code/trade-data-signal | 16G | 31% | .git 2.1G + data 11G(backups 6.7G)+ static-site 2.5G |
| /home/ubuntu/code/trade-data-signal-staticdata | 11G | 21% | .git 5.1G + db 3.0G + data 2.7G(生产公开数据仓) |
| /home/ubuntu/code/trade-data | 9.2G | 18% | data 6.7G(backups 2.9G + public_fund 2.5G)+ static-site 2.6G(镜像) |
| /home/ubuntu/code/_backup_126_staticdata_before_migrate | 3.2G | 6% | staticdata 主仓 clone 快照(#126 预迁移备份) |
| /home/ubuntu/.npm | 1.9G | 4% | npm 全局缓存 |
| /swapfile | 4.1G | 8% | swap 4G,实际仅用 119.7M(3%) |
| /usr | 3.6G | 7% | firmware 1.2G / modules 457M / local/qcloud 562M 等(系统,不动) |
| /var | 2.0G | 4% | /var/log 695M(journal 657M)+ /var/lib 1.1G(snapd 719M)+ /var/cache 205M(apt 186M) |
| /tmp | 861M | 2% | 历史 probe/verify/migrate 临时产物 739M 可回收 |
| /root | 498M | 1% | root 家目录 |
| /boot | 133M | 0.3% | 单内核 5.15.0-181(无旧内核可清) |
| **合计** | **≈52.2G** | | vs df 已用 52G,闭合 |

## 2. code 之外 ~13G 已补齐(主控未定位部分)
code=39G 之外 = **swapfile 4.1G + /usr 3.6G + /var 2.0G + /tmp 0.86G + /root 0.5G + /boot 0.13G ≈ 11.2G**,加 /home/ubuntu 内 code 外 .npm 1.9G + .cache 214M ≈ 2.1G,**合计 ≈13.3G,全部有主,无黑洞残差**。

## 3. 四个大头下钻

### 3.1 trade-data-signal 16G
- `.git` 2.1G:`count-objects -vH` → in-pack 102358 / size-pack 1.38G(3 packs)/ **prune-packable 89 / garbage 16 / size-garbage 580.72M**(unreachable,git gc 可回收);最大 pack `pack-e66b2ea...pack` 1.4G。
- `data` 11G:
  - **`backups` 6.7G = 38 个文件(09-13~09-30 18 天)= 19 份 etf_national_team(4.3G)+ 19 份 sentiment(2.4G)**。每日 21:00 由 `trade-backup-db.timer`→`backup_db.sh` 生成;**与镜像 backups 文件 md5 完全一致(34b0fd8b...)= 镜像备份的副本累积,且无配套清理**(backup_db.sh 的 RETAIN_DAYS=7 清理只作用于 REPO=trade-data 镜像,主库副本从未清理)。**>7 天(09-23 前)≈ 4.0G 可回收**。
  - `public_fund.db` 2.5G / `etf_national_team.db` 243M / `stock_daily.db` 139M / `sentiment.db` 128M(生产 DB,不动)。
  - 历史 .bak:`etf_national_team.db.bak-accumnav-20260916` 221M + `.bak-lof-20260915-144248` 178M + `sentiment.db.bak-spikefix-20260915_101316` 126M(一个多月前的修复备份,主库/镜像 md5 一致=双副本,共 ≈1.05G 待确认可回收)。
- `static-site/data` 2.5G(站点上线产物,不动);`docs` 155M。
- 日志:主库无 data/logs(备份日志 fallback 机制)。

### 3.2 trade-data-signal-staticdata 11G(⚠️ 生产公开数据仓,只统计不动)
- `.git` 5.1G:`count-objects -vH` → size-pack 2.30G(11 packs)/ **garbage 3 / size-garbage 455.19M** + **中断残留 `tmp_pack_thsl6p` 340M**。**git 近 2 天 0 commit(09-28 后冻结)** → .git 为历史累积,无每日增长。
- `db` 3.0G:`public_fund.db` 2.5G(md5 与主库/镜像一致 a5a6d28e...)+ etf 243M + stock_daily 139M + sentiment 128M。
- `data` 2.7G:fund_nav 578M + nav_bucket 534M + trade_sim 369M + signal_kelly_trades_parts 178M + sdc_parts 164M + etf 116M 等(9 目录 31239 工作区文件 = 生产数据本体,禁删)。

### 3.3 trade-data 9.2G(镜像)
- `data` 6.7G:backups **2.9G(16 文件,09-23~09-30 8 天=符合 RETAIN_DAYS=7 策略,正常)** + public_fund.db 2.5G + etf 243M + stock_daily 139M + sentiment 128M + 同款 .bak 三件(1.05G 的另一副本)+ logs 97M。
- `data/logs` 97M **2088 个文件,最老 09-13,无轮转**(backfill_*.log / *_launchd.log 等,最大 backfill_evening_launchd.log 1.9M)。
- `static-site` 2.6G。

### 3.4 _backup_126_staticdata_before_migrate 3.2G
- **确认 = staticdata 主仓的完整 clone**:`git -C ... rev-list --count HEAD` = 1008 = 主仓 1008;`git remote -v` = origin→`/home/ubuntu/code/trade-data-signal-staticdata`;HEAD 与主仓一致(09-28 19:01)。
- 构成:.git pack 1.2G + data 2.0G(fund_nav 578M/nav_bucket 533M/parts 342M 等,= 迁移时点工作区快照)。
- **可回收时机:#126 迁移收口验证通过后**(staticdata 主仓 09-28 后已 0 commit 稳定;主仓即权威,clone 仅作回退保险)。**只确认,不动。**

## 4. 全盘大文件 top(只读采样,`find / -xdev -size +200M`)
4.1G /swapfile · 2.5G public_fund.db ×3(主库/镜像/staticdata,md5 一致=同库三副本)· 1.4G tds/.git pack · 1.2G _backup_126/.git pack · 345M+340M+296M+254M+252M+252M staticdata/.git packs(含 340M tmp_pack_thsl6p 中断残留)· 243M etf_national_team.db ×2 + backups 每日 etf 243M×N。

## 5. 可优化项清单(每项三件:回收量实测/风险/代价)

### A. 零/低风险,立即可做(合计 ≈6.0G)
| # | 项 | 回收量(实测) | 风险 | 代价/操作 |
|---|---|---|---|---|
| A1 | 主库 trade-data-signal/data/backups 清 >7 天(22 份) | **4.0G**(find -mtime +7 -exec du 实测 4001923072B) | 低:全是镜像备份的 md5 一致副本,R2 异地备份(upload-db)已存在,且镜像自身仅留 7 天 | 单条 `find .../backups -maxdepth 1 -name "*.db" -mtime +7 -delete`;可持续性:主库副本来源为镜像同步(09-30 两库 md5 一致),镜像保留 7 天→同步到主库后主库不会超 7 天;清理前建议再确认同步机制不重建 |
| A2 | 历史 .bak 三件(accumnav/lof/spikefix,主库+镜像双副本) | **≈1.05G**(221+178+126 M ×2) | 中低:2026-09-15/16 修复备份已 2 周稳定,对应修复已上线 | 需用户确认这 3 个修复无需回退后删(两仓同删) |
| A3 | /tmp 历史产物 739M | **0.74G**(09-23~09-27 的 tr_verify/kelly_trades probe、migrate_126 日志等,今天新文件 ov144_* 勿动) | 零:临时目录,重启即清 | 按 mtime 清 09-27 前 |
| A4 | apt cache clean | **0.19G**(/var/cache/apt 186M) | 零 | `apt-get clean` |
| A5 | journald 限容+vacuum | **≈0.46G**(656M→200M) | 低:日志,可 vacuum 到指定大小 | journald.conf 设 SystemMaxUse=200M(当前**未配置**,默认上限≈4G)+ vacuum;写操作需授权 |
| A6 | 镜像 data/logs 加轮转 | 现 97M 不大,防膨胀 | 低 | 设 logrotate 或按大小清 >30 天(2088 文件) |

### B. 需用户拍板(合计 ≈7.4G)
| # | 项 | 回收量 | 风险 | 代价 |
|---|---|---|---|---|
| B1 | swapfile 4.1G→1G | **≈3.0G** | 中:swap 现仅用 119.7M(3%),内存 3.6G 可用 3.1G;但 swapoff 重建有短暂内存压力窗口,生产机需谨慎 | swapoff + truncate + 重建 swapfile(单条,避开交易时点) |
| B2 | _backup_126 删除 | **3.2G** | 低(收口后):staticdata 主仓即权威,clone 冻结在 09-28 | **#126 迁移收口验证通过后**才删 |
| B3 | .git gc 回收 garbage | **≈1.3G**(tds garbage 580M + staticdata garbage 455M + tmp_pack 340M) | 中:git gc 是写操作(硬约束本次不执行);生产仓库 repack 需安全窗口 | 先 `git gc --prune=now`(可先 --aggressive 评估),tmp_pack 是中断残留可单独核验删除 |
| B4 | .npm 缓存 1.9G | **≈1.9G** | 低,但清后下次 npm install 重新下载 | `npm cache clean --force`(云上 build_min 用 node) |

### C. 不可动
- public_fund.db ×3(生产 DB 三副本,mtime 09-30 18:40 每日更新)
- static-site/data、staticdata data/db 9 目录(生产上线数据本体)
- /usr firmware/qcloud/snapd、swapfile 本体、/var/lib/snapd 719M、内核(仅 1 版无旧内核)

## 6. 紧急度判定(今晚到明早)
**明确判断:今晚到明早的定时任务不会撞写满,安全。**
- 依据:今日实测增量 = 静态产物 22.99MB(static-site/data mtime-0 累计)+ git 0(staticdata 2 天 0 commit)+ backups 每天 21:00 固定写镜像 371M + 主库副本同步 371M ≈ **0.74G/天**(+ public_fund.db 净值每日涨量 <100M,合 ≈0.9G/天)。
- 今晚剩余任务(23:15 监控/23:22 self-heal/23:45 news/00:00 logrotate/02:00 backfill/02:40 gold-night/05:00 us-stock/08:00 rzhb)写入量级 ≈ 今日白天的零头,**估计 300-600M**,4.7G 可用完全覆盖。
- 风险窗口:按日增 0.9G,可用 4.7G → **4-5 天内不清理将降到 <2G**(backup_db 的 21:00 写入 742M 是最刚性增长)。**建议 24h 内执行 A1+A3+A4(≈4.9G),回收后可用翻倍到 ~9.6G,一周边界宽松;A5/A2 顺带。**

## 7. 复现段(每条数字的原始命令,均 ssh -i ~/tdsignal.pem ubuntu@122.51.111.173)
- 顶层: `sudo du -shx /*` → /home 41G /swapfile 4.1G /usr 3.6G /var 2.0G /tmp 861M /root 498M /boot 133M
- code 四仓: `sudo du -shx /home/ubuntu/code/*` → 16G/11G/9.2G/3.2G
- 主库 backups: `du -shx .../data/backups` = 6.7G;`ls | wc -l`=38;`find ... -mtime +7 -exec du -cb {} +`=4001923072B(4.0G)
- 镜像 backups: 2.9G/16 文件(09-23~09-30)
- md5 副本证据: `md5sum 主库/镜像 .../etf_national_team_20260930_2100.db` 均为 `34b0fd8bf5257689141a7f64ba8faea2`;public_fund.db 三仓均为 `a5a6d28e088315146d50184830745c80`;bak-accumnav 双仓均为 `126e97f6c458160aee5db04efbd0c2a6`
- .git 对象: `git -C ... count-objects -vH` → tds size-pack 1.38G/garbage 580.72M;staticdata size-pack 2.30G/garbage 455.19M;`ls .../.git/objects/pack/tmp_pack_thsl6p` 340M
- _backup_126: `git -C ... rev-list --count HEAD`=1008;`git remote -v` origin=主仓路径;`git log -1 --format="%ci %s"`=2026-09-28 19:01 data backup [news-fetch]
- journald: `journalctl --disk-usage`=656.0M;`grep SystemMaxUse /etc/systemd/journald.conf`=注释(#),未配置;`journalctl --verify`=PASS
- 内核: `dpkg -l | grep linux-image` → 仅 linux-image-5.15.0-181-generic(+generic 元包)
- swap: `free -h` → Swap 4.0Gi used 119Mi;`swapon --show`=/swapfile 4G 119.7M
- 日志: `ls data/logs | wc -l`=2088;最老 09-13 09:01;`du -shx`=97M
- 今日增量: `find static-site/data -mtime 0 -exec du -cb {} +`=22990913B(22.99MB);`git -C staticdata rev-list --count --since="2 days ago" HEAD`=0
