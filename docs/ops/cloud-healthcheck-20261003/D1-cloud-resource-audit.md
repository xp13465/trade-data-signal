# D1 云服务器资源与配置体检(2026-10-03)

> 体检窗口:2026-10-03 18:13-18:25 CST(国庆休市日,A 股 10-08 开市)。全程只读命令,无任何写操作。
> 对比基线:09-12 部署基准 `docs/deploy/resource-benchmark-20260912.md`(mac 侧)、09-30 磁盘诊断 `docs/ops/cloud-disk-usage-20260930.md`、09-12 systemd 配置 `docs/deploy/systemd-units-20260912.md`。

## 0 结论速览

1. **磁盘比 09-30 好转:可用 4.7G → 11G(已用 52G→47G,83%)**。09-30 报告建议的清理绝大部分已执行(swap 4G→1G、_backup_126 已删、主库 backups 超 7 天已清、journal 656M→228M 并设 SystemMaxUse=200M、staticdata .git gc 5.1G→1.2G、npm 1.9G→550M)。**但今日 10:47 新出现 public_fund.db.bak 双仓各 5G(共 10G)一次性残留,未找到脚本生成者**(疑似手动备份),是当前最大单点风险。
2. **新增 public_fund.db.bak-20261003_104704(+同 size .wal 副本)双仓各 5G = 10G,10:47 生成,scripts 全量 grep 无生成者,当天无计划任务在 10:47** → 疑似当天手动/agent 一次性备份,需人工确认来源与用途;若确认可删,磁盘可用回到 21G(P1)。
3. **37+1 个周期任务 systemd timer 全部在位:38/38 enabled+active,时点与 09-12 文档逐项一致,0 failed 单元**。文档之外新增 1 个 transient 服务 `staticdata-backup-181346.service`(deploy 异步触发的 staticdata 灾备,2026-09-25 设计,文档未记载)——非漂移,是新机制。
4. **主库 trade-data-signal/data/backups 停更于 09-30,镜像 trade-data/data/backups 正常到 10-02**。backup_db.sh 只写镜像(BACKUP_DIR=$REPO/data/backups),主库 backups 是历史残留副本(09-30 清理后留 09-23~30,之后无同步者);主库与镜像 inode 不同、且全仓 grep 无同步脚本 → 主库 2.9G 冗余残留,不会再增长也不会自清理(P2)。
5. **磁盘/内存/inode 阈值告警是盲区**:schedule_monitor 9 个维度(漏跑/退出/异常关键词/耗时/加载/产物时效/R2/飞书x2/心跳)均不覆盖磁盘使用率、inode、内存;当前 4.7G→11G 可用完全是 09-30 清理的功劳,无任何自动告警会在磁盘降到 20%/5% 前提醒(P1)。

## 1 与 09-12 基准的三周漂移表

| 项 | 09-12 基准(mac 实测) | 09-30 诊断(云上) | 10-03 实测(云上) | 三周漂移判定 |
|---|---|---|---|---|
| CPU | 8 核(M1) | 4 vCPU(推断) | 4 vCPU(nproc=4) | 与迁移设计一致,匹配 |
| 内存 | 16G | 4G 档 | 3719MiB 总,used 247M,available 3176M(86%) | 健康,余量足 |
| swap | - | 4G(用 119M) | 1G(用 95.9M) | 10-01 swapfile 4G→1G 重建(B1 执行) |
| 磁盘总/可用 | 57G 本地机(33G 已用) | 59G / 4.7G 可用(92%) | 59G / 11G 可用(83%) | **好转 +6.3G**;已用 52→47G |
| 根分区 inode | - | - | 275531/3932160 = **8%** | 无 inode 风险 |
| 内核 | macOS | 5.15.0-181(单内核) | 5.15.0-181(单内核) | 无漂移 |
| 时区/NTP | 北京时间 | Asia/Shanghai | Asia/Shanghai, NTP sync=yes | 无漂移 ✓ |
| uptime | - | 09-13 迁云 | 09-13 13:02 起 20 天 | 无重启,稳定 |
| 负载 | - | - | 0.19/0.19/0.24 | 极低,健康 |
| journald | - | 656M(未限容) | 228M(SystemMaxUse=200M) | 10-01 后已设限容+vacuum |
| 主库 backups | 604M/天本地双仓 | 38 文件/6.7G(无清理) | 16 文件/2.9G(09-23~30) | 超 7 天已清(A1);**10-01 起停更(详见 §2.2)** |
| 镜像 backups | - | 16 文件/2.9G(8 天) | 16 文件/2.9G(09-25~10-02) | 正常,RETAIN_DAYS=7 生效 |
| trade-data-signal | - | 16G | 17G | +1G(public_fund.bak 5G - 主库 backups 3.8G) |
| staticdata 仓 | - | 11G(.git 5.1G) | 8.4G(.git 1.2G) | .git gc 执行:5.1G→1.2G |
| trade-data(镜像) | - | 9.2G | 14G | +4.8G(public_fund.bak 5G 双份之一) |
| logs(项目) | 354M(mac 双仓) | 97M/2088 文件 | 120M/2304 文件,最老 09-13 | 20 天无轮转,日均 ~7.7M(§3) |
| systemd timers | 37+1 设计 | - | 38/38 enabled+active | 零缺失零漂移(§4) |

## 2 磁盘与增长速率

### 2.1 现状分解(闭合至 47G 已用)

```
df -h: /dev/vda2 59G 47G 11G 83% / ; df -i: 8% / (3932160 总 inode 用 275531)
code 四仓: trade-data-signal 17G / trade-data 14G / staticdata 8.4G(其余 <15M)
主库 data 12G = public_fund.db 2.6G + public_fund.db.bak 2.5G + .wal 副本 2.5G + backups 2.9G
           + etf 243M + sentiment 128M + stock_daily 139M
镜像 data 12G(与主库同构:public_fund.bak 同款 5G)
staticdata: data 2.7G(fund_nav 578M/nav_bucket 537M/trade_sim 369M 等 9 目录)
          + db 3.1G(public_fund 2.6G/etf 243M/stock_daily 139M/sentiment 128M)
          + .git 1.2G(5 packs,10-03 18:01 仍活)
```

### 2.2 09-30 清理落地核对(9 项建议逐项实证)

| 09-30 建议 | 是否执行 | 证据 |
|---|---|---|
| A1 主库 backups 清 >7 天(4.0G) | **已执行** | tds backups 38→16 文件(09-23~30) |
| A2 历史 .bak 三件(1.05G) | 未确认 | data 下未见 accumnav/lof/spikefix 三件(可能已删,当前 ls 无) |
| A3 /tmp 739M | 部分 | 861M→578M |
| A4 apt cache | 未测 | (未取到证据) |
| A5 journald 限容+vacuum | **已执行** | 656M→228M,`SystemMaxUse=200M` 已写入 journald.conf |
| B1 swapfile 4G→1G | **已执行** | /swapfile ls -lh = 1.0G,mtime 10-01 20:09 |
| B2 _backup_126 删除(3.2G) | **已执行** | 目录不存在,code 下仅 _gc_backup 52K |
| B3 .git gc(1.3G 起) | **已执行** | tds garbage 0/size-pack 1.36G;staticdata .git 5.1G→1.2G,pack 10-01 后重建 |
| B4 npm cache(1.9G) | **已执行** | 1.9G→550M |

### 2.3 当前日增与磁盘寿命(按 2026-10-03 实测)

| 增长源 | 速率(实测) | 证据 |
|---|---|---|
| 镜像 DB 备份(backup_db 21:00) | **+388M/天**(etf 254M + sentiment 134M) | 09-25~10-02 16 文件/8 天 |
| public_fund.db | +~100M/天 | 2.5G(09-30)→2.6G(10-03) |
| logs | +7.7M/天(近 3 天 97M→120M) | 09-30 文档 vs 实测 |
| static-site 产物 | +23M/天(常规交易日) | 今日休市 10.6M;09-30 文档 22.99MB/日 |
| 合计常态 | **≈+0.52G/天** | |

**磁盘寿命(11G 可用)**:常态约 **21 天**(第 4 周初风险);若 public_fund.bak 10G 保留不清理 → 可用仅 1G,本周内即紧张。每日最刚性消耗 = 21:00 backup_db 写 388M(休市日 update_all 空转仅 ~10M)。
**结论:磁盘安全但不宽裕,21 天是"不清理"的上限;清理 public_fund.bak 后回到 ~40 天+。**

### 2.4 staticdata git backlog 事件(09-30~10-01,已自愈)

09-30 16:01→10-01 01:01 共 9 次告警「staticdata 变更量超阈值跳过 commit」(文件 4069-4071 / 字节 1.2GB > 500MB 阈值),根因见 `staticdata_backup_async_20260930_192301.log`:**09-30 首次全量 large-json R2 上传 31663/31663(耗时 6315s)导致单轮变更 1.2GB** → 触发积压兜底设计(磁盘留档不 commit,push 后由次日 deploy 全量 rsync 追平)。10-02/10-03 已恢复(今日 commit:21/10/3 文件,心跳 ok)。系统日志/监控均正常上报,非静默。

## 3 日志与轮转

| 项 | 实测 | 判定 |
|---|---|---|
| journald | 228M,`SystemMaxUse=200M` 已配置,journalctl --verify PASS | 有界,健康 |
| /var/log | 302M(syslog 46M/auth.log 10M) | 小 |
| logrotate.d | 10 个系统配置 + logrotate.timer enabled,每日 00:00 跑;syslog/auth.log 实测每周轮转(.1 每周旋转,.2-.4.gz) | 系统日志有轮转 ✓ |
| 项目 data/logs | **120M / 2304 文件,最老 09-13 07:43,20 天零轮转** | **定时炸弹候选(§P2-1)** |
| 项目 logs 大头 | intraday_snapshot_launchd.log 10.4M / update_lab_launchd.log 9.7M / staticdata_backup_async 每日 ~2.9M×N | 单文件不大,但只增不删 |
| fetch_news err | 9 月残留 PermissionError(2026-09-13.json)已修(文件现属主 ubuntu 644);10-01 曾 4 次 service timeout(16:55/17:11/21:55/22:11)已恢复,今日 18:01 成功 | 历史问题,当前正常 |

**结论:系统层日志全有轮转;项目 data/logs 无任何轮转策略,20 天 120M(日均 ~7.7M),约 13 个月到 3G。** 不是近日风险,但无轮转=终将失控,参照 09-30 A6 建议仍未落地。

## 4 systemd 单元 vs 文档差异表

基线:docs/deploy/systemd-units-20260912.md(37 周期任务 + 1 backup-db)。

| 文档有 / 实际无 | 实际有 / 文档无 | 时点不符 |
|---|---|---|
| 无(全部在位) | `staticdata-backup-181346.service`(transient,deploy 异步触发 staticdata 灾备,09-25 新机制,非漂移) | 无(list-timers 时点与文档 OnCalendar 全一致) |

- **38/38 timer 全部 enabled+active**(list-unit-files 38 行逐一 is-enabled/is-active)
- 0 failed units(systemctl --failed 空)
- 近 24h 实际触发抽查:update-all 10-03 17:50:01 ✓ / backfill-evening 16:35:01 ✓ / intraday-snapshot 15:35:01 ✓ / schedule-monitor 每 15min ✓ / self-heal 每 15min ✓ / pf-stage0-manager 10-01 02:47 ✓ / pf-stage0-risk 09-15 02:33(月度)✓ / etf-track-index 09-27 Sun 03:30 ✓
- 服务进程:39 个 trade 单元 loaded(38 + staticdata transient),无残留常驻
- 今日 update_all 休市空转正常:17:50→18:13:46 退出码 0,deploy push main 成功,触发 staticdata 异步备份(18:13 完成,心跳 ok)

## 5 资源告警覆盖

**现状:磁盘/内存/inode 阈值告警 = 盲区。**
- schedule_monitor.sh 9 维度:①漏跑 ②退出失败 ③异常关键词 ④耗时阈值 ⑤launchctl/systemd 加载 ⑥产物时效+R2 直连 ⑦飞书配置 ⑧飞书 hook 心跳 ⑨ws listener 心跳——**均不检查 df 使用率/inode/内存/swap**
- 只读 grep 证据:schedule_monitor.sh 全文无 `df -`/`inode`/`disk` 维度;backup_db.sh 只在备份失败时告警(磁盘满会间接显形,但被动且当晚才发现);check_data_gap 只查数据缺口(非资源)
- 09-30 磁盘 92% 是**人工**诊断发现,不是告警拉响;11G 可用没有自动兜底

## 6 反证项(查过没问题的)

| 项 | 证据 | 结论 |
|---|---|---|
| 时区/时间同步 | timedatectl Asia/Shanghai, System clock synchronized: yes | ✓ |
| CPU/负载 | 4 vCPU,load 0.19-0.42,top 98.4% idle | ✓ 无饱和 |
| 内存 | 2.7G avail(buff/cache),swap 用 96M/1G,无 OOM(syslog 0 命中) | ✓ |
| inode | 根分区 8%,远低于 90% | ✓ |
| 内核/启动 | 单内核无旧内核冗余;09-13 13:02 起 20 天无重启 | ✓ |
| 网络出口 | ss:无 TIME_WAIT/orphan 堆积(12 ESTAB);ss.fx8.store overview 200,1.34s;CF 边缘探测另有专报(东财腿 502 属源站风控,另见专报 docs/ops/cf-edge-egress-probe-20261002.md,非资源问题) | ✓ |
| journal 完整性 | journalctl --verify PASS | ✓ |
| 系统日志轮转 | syslog/auth.log 每周轮转(见 §3) | ✓ |
| staticdata 备份健康度 | heartbeat {"result":"ok","duration_s":351};schedule_monitor C3(36h 心跳)已接线(1118-1145 行) | ✓ |
| 静态产物与 DB | public_fund.db 16:01 每日刷新;staticdata 数据 9 目录与 09-30 分解一致无爆炸 | ✓ |
| 备份恢复演练 | backup_db.sh 内 verify_backup.sh(下载 R2 + integrity_check),Result=success | ✓ |
| 出网超时频次 | /var/log/syslog 近 7 天无连接超时类记录;journal -p err 仅 fetch-news 10-01 4 次(已恢复)+ ssh 扫描噪音 | ✓ |

## 7 分级问题表

### P0(立即)
**无。** 磁盘未满、备份在跑、任务全在位、站点连通正常。

### P1(本周)
| # | 现象 | 证据 | 影响 | 建议 |
|---|---|---|---|---|
| P1-1 | **磁盘/内存/inode 无阈值告警** | schedule_monitor 9 维度清单无资源维度(grep 全文);09-30 92% 靠人工发现 | 磁盘写满→任务失败/DB 报错/告警链断裂,无人最先知道 | 在 schedule_monitor 加维度⑩:df 使用率≥85%→warn / ≥95%→severe,inode≥90%,内存可用<500M 或 swap>80%;或独立 `df -h + notify.py` 每小时检查 |
| P1-2 | **public_fund.db.bak 双仓各 5G(共 10G),10-03 10:47 生成,无脚本生成者** | ls -lt:2.5G×2×2 仓,10:47;BAT 无计划任务该时点;`grep -rn "public_fund.db.bak"` 全 scripts 仅命中注释;16:31 .bak-shm 仍被 touch | 占可用磁盘 45%;若每日生成将 5 天打满(当前证据=单次) | 主控确认 10-03 上午是否有手动备份(#154 相关?);确认用途后两仓同删,mtime 已 3 天且 R2 signal-backup 有 db 备份+verify 演练可恢复;若确认是重复性操作→修脚本进 backup_db.sh 并加保留策略 |
| P1-3 | fetch-news 10-01 4 次 timeout 失败且 09-30 曾 permission 崩溃 | journal:16:55/17:11/21:55/22:11 "Failed with result timeout";err 文件残留 9-13 PermissionError | 10-01 新闻采集缺口(告警 recover 显示 r2_skip_continuous 10-03 恢复) | 已自愈(success 10-03 18:01);补充观察:若再 timeout,查 journal 该时点锁竞争(deploy_lock 排队超时 09-30 曾 5 次) |

### P2(观察/本周可做)
| # | 现象 | 证据 | 影响 | 建议 |
|---|---|---|---|---|
| P2-1 | 项目 data/logs 120M/2304 文件 **20 天零轮转** | 最老 09-13 07:43;logrotate.d 无 trade 项;日增 ~7.7M | 年化 ~3G;高写入任务(staticdata_backup_async 每日 2.9M×4+)会更快 | 落地 09-30 A6 logrotate:data/logs 按大小/天数轮转(如 >200M 或 30 天,保留 30 份) |
| P2-2 | 主库 tds/data/backups 残留 2.9G 停更(09-30 后无同步者),inode 与镜像不同 | stat 64514:1310722 vs 64514:1182462;backup_db.sh 只写 BACKUP_DIR=镜像;全仓 grep 无同步脚本 | 冗余磁盘 2.9G;内容 09-23~30 与镜像 09-25~10-02 部分重叠 | 确认只需镜像+R2 一套 → 删 tds/data/backups 残留;历史双份时代遗留 |
| P2-3 | backup/tools 10-03 有 2 次 fetch_news "SKIPPED_LOCKED R2 上传锁忙" | fetch_news_launchd.log 多条 SKIPPED_LOCKED;warning_dedup_state 有 deploy_lock 排队超时 5 次(09-30) | 单轮缺口由下轮 30min 后重试补,已设计兜底 | 观察;若每日多次,考虑 R2 上传锁粒度拆分 |
| P2-4 | journal 8 分钟 8 次 sshd kex 报错(16:11:51) | journal -p err(见复现段) | 疑似扫描,无功能影响 | 无需动作(安全组/密钥策略另议) |
| P2-5 | A2(历史 .bak 三件)/A4(apt cache)未确认是否清理 | 现 data 无三件;apt cache 未测 | 可能已随 10-01 清理,或仍在 /var/cache | 复查后随 P1-2 一并收口 |

## 复现段(全程只读,ssh -i ~/tdsignal.pem ubuntu@122.51.111.173)

```
# 1 资源现状
date "+%F %T %Z"; uptime; free -m; swapon --show; nproc; timedatectl; df -h; df -i; uname -r
# 2 磁盘分解
du -shx /home/ubuntu/code/*
ls -lt /home/ubuntu/code/trade-data-signal/data/ | grep -E "public_fund|\.bak|\.wal"   # public_fund.bak 5G 证据
# 3 备份
ls -l /home/ubuntu/code/trade-data-signal/data/backups; ls -l /home/ubuntu/code/trade-data/data/backups
stat -c "%d:%i %n" /home/ubuntu/code/trade-data-signal/data/backups /home/ubuntu/code/trade-data/data/backups
systemctl show trade-backup-db.service -p Result -p ExecMainStatus   # Result=success
# 4 日志
journalctl --disk-usage; journalctl --verify | tail -2; grep SystemMaxUse /etc/systemd/journald.conf
du -shx /home/ubuntu/code/trade-data/data/logs; ls /home/ubuntu/code/trade-data/data/logs | wc -l
ls -ltr /home/ubuntu/code/trade-data/data/logs | head -2; ls -l /var/log/syslog* /var/log/auth.log*
# 5 systemd
systemctl list-timers --all | grep trade; systemctl list-unit-files --type=timer | grep "^trade-"
systemctl --failed --all
# 6 告警盲区
grep -n "df \|inode\|磁盘" /home/ubuntu/code/trade-data/scripts/schedule_monitor.sh | head   # 无资源维度
# 7 网络
ss -s; ss -tan | awk '{print $1}' | sort | uniq -c
timeout 8 curl -sI -o /dev/null -w "%{http_code} %{time_total}s\n" https://ss.fx8.store/data/overview.json
journalctl -p err --since "3 days ago" --no-pager | head -30   # 16:11:51 sshd kex 8 连发
```

> 注:报告发现「public_fund.db.bak 双仓 5G」为 10-03 当天出现,无法从 git 历史反查生成者(未执行任何写/搜索仓库历史,本报告仅只读)。
