# #238 云上主机加固 —— tester 只读独立复核报告(2026-10-09)

总判:**9/9 项 PASS —— 加固确实在位,且 systemd 已重载生效;swap 已实盘启用;定时器 NEXT = 今日 18:10 CST,deadline 前生效无疑。**
唯一需主控留意的是附加风险项 R1(2G 上限与 10-08 实际被杀进程 RSS 1.95G 只差 2.5%)。

## 0. 复核方式与偏差声明(重要,先读)
- 本报告所有结论来自我自己在云上跑的只读命令,**未采用 implementer 的任何自述**。
- **ssh 用户偏差**:任务给的 `root@122.51.111.173` 实测被拒 —— `root@122.51.111.173: Permission denied (publickey)`(root_exit=255);按 memory `ssh-cloud-uses-tdsignal-pem` 改用 **`ubuntu@122.51.111.173` + `-i /Users/linhuichen/tdsignal.pem`** 连通更成功(`whoami`→ubuntu)。读系统文件走 `sudo -n`(免密可用)。命令形式:`ssh -i ... -4 -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=3 ubuntu@122.51.111.173 'timeout 25 <远端命令>'`。
- **只读边界**:全程无 start/stop/restart/enable/disable/daemon-reload/swapon-swapoff 写操作、无文件编辑、无业务脚本执行、无任何外发、无 git 写。`swapon --summary/--show`、`systemctl show/list-*`、`journalctl`、`sudo -n cat/grep/md5sum/diff/ls/findmnt --verify` 均为读。
- 本机干扰项一次:mac 版 `cat` 无 `-A` 参数(报 `cat: illegal option -- A`),已改用远端 `cat -n`/`sed`;不涉及云上状态。
- 无后台残留任务(本次无命令被 moved to the background)。

## 1. 逐项结论表
| # | 项 | 结论 | 关键证据 |
|---|---|---|---|
| 1 | unit 文件本体 | **PASS** | 见 §2.1 |
| 2 | systemd 侧生效值 | **PASS** | 见 §2.2(FragmentPath 指向真文件,非编译默认回填) |
| 3 | unit 真实登记 | **PASS** | 见 §2.3 |
| 4 | 备份在位 | **PASS** | 见 §2.4(备份=改动前版本,现文件=备份+2 行) |
| 5 | swap | **PASS** | 见 §2.5(5.00GiB 总量,/swapfile2 已 swapon,fstab 有行,findmnt 0 error) |
| 6 | 定时器时点 | **PASS** | 见 §2.6(NEXT = Fri 2026-10-09 18:10:00 CST) |
| 7 | 时区核对 | **PASS** | 见 §2.7(Asia/Shanghai CST +0800,非 UTC 误读) |
| 8 | 只有 fapi 有内存限制 | **PASS** | 见 §2.8(全量 grep 仅 fapi;无 drop-in/lib 旁路) |
| 9 | 老 swapfile 保留 | **PASS** | 见 §2.9 |

## 2. 分项证据(原始输出摘录)

### 2.1 项1 unit 文件本体 —— PASS
`sudo -n cat -n /etc/systemd/system/trade-fapi-daily.service` 全文(18 行):
```
 1 [Unit]
 2 Description=Trade fapi-daily (源 com.trade.fapi-daily)
 4 [Service]
 5 User=ubuntu
 6 EnvironmentFile=/home/ubuntu/code/trade-data/.env
 7 Type=oneshot
 8 WorkingDirectory=/home/ubuntu/code/trade-data
 9 Environment=GIT_REPO=/home/ubuntu/code/trade-data-signal
10 Environment=REPO=/home/ubuntu/code/trade-data
11 Environment=MAIN_REPO=/home/ubuntu/code/trade-data
12 ExecStart=/bin/bash /home/ubuntu/code/trade-data/scripts/fapi_daily_syn.sh
13 Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
14 TimeoutStartSec=0
15 MemoryHigh=1.5G
16 MemoryMax=2G
17 StandardOutput=append:/home/ubuntu/code/trade-data/data/logs/fapi_daily_launchd.log
18 StandardError=append:/home/ubuntu/code/trade-data/data/logs/fapi_daily_launchd.err
```
- 两行内存限制在位(L15/L16)。
- **「其它意外改动」核法 = 与昨前版本逐行 diff**(见 §2.4):今天相对 07:13 备份**只有 +2 行**,无任何其它改动;其余行(含日志 append 重定向)均早于今日。
- 观察 O1(非今日改动、不判 FAIL):现文件与 `bak-20260916` 相比**另有一处差异 `TimeoutStartSec=600 → 0`**,该差异在今日 07:13 备份里**已经存在**,故属 09-16 之后的既有改动,不计入本次加固。

### 2.2 项2 systemd 侧生效值 —— PASS
```
Result=oom-kill
MemoryHigh=1610612736      # = 1.5 * 1024^3,正式生效值 ✓
MemoryMax=2147483648       # = 2 * 1024^3 ✓
ActiveState=failed
SubState=failed
FragmentPath=/etc/systemd/system/trade-fapi-daily.service   # 指向真实文件 ✓
UnitFileState=static
```
- 幽灵 unit 陷阱已双重排除:①`FragmentPath` 指向真实存在的文件(非 systemd 编译期默认回填)②该文件用 `cat -n` 实读到 L15/L16 原文 ③`systemctl list-units --all` 里该 unit 为 loaded。
- 生效链闭合:文件 mtime = Oct 9 07:13,日志显示 07:13:59 `systemctl daemon-reload` → `Reloading.`,且此后无再次写文件(见 §2.4 审计链),故 systemd 装载的即当前文件内容。
- `ActiveState=failed / Result=oom-kill` **是 10-08 那次运行的残留状态**(ExecMainStart=Thu 2026-10-08 18:10:00 CST,ExecMainExit=19:23:39),与本次加固无关;见附加项 R1。
- 注:`MemoryHigh=1610612736` 是 **systemd 装载值**(非从文件推算),与文件一致 = 配置真的进了 manager。

### 2.3 项3 unit 真实登记 —— PASS
```
== list-unit-files ==            == list-units --all ==
trade-fapi-daily.service  static  -   ● trade-fapi-daily.service  loaded failed failed
trade-fapi-daily.timer    enabled enabled trade-fapi-daily.timer    loaded active waiting
```
非幽灵、非空壳:timer enabled、service static(由 timer 触发,[Install] 缺省属正常形态)。

### 2.4 项4 备份在位 —— PASS
```
-rw-r--r-- 1 root root 700 Oct  9 07:13 /etc/systemd/system/trade-fapi-daily.service
-rw-r--r-- 1 root root 671 Sep 16 05:11 /etc/systemd/system/trade-fapi-daily.service.bak-20261009-0713
d9c86230fc4b0f3bb21a8964dda21b86  /etc/systemd/system/trade-fapi-daily.service
b43c6f6ac8919569808947c3e47f5089  /etc/systemd/system/trade-fapi-daily.service.bak-20261009-0713
== grep 备份里的 Memory 行 ==  (无输出, grep_exit=1)
== diff 备份 → 现文件 ==
14a15,16
> MemoryHigh=1.5G
> MemoryMax=2G
```
- 备份存在,内容**不含** MemoryHigh/MemoryMax(即改动前版本),现文件含;md5 不同。
- 操作审计链(journal,sudo 记录)顺序正确、无静默:
```
07:13:48  /usr/bin/cp -a trade-fapi-daily.service → .bak-20261009-0713   # 先备份
07:13:55  /usr/bin/tee /etc/systemd/system/trade-fapi-daily.service      # 再改写
07:13:59  /usr/bin/systemctl daemon-reload  →  systemd[1]: Reloading.    # 再重载
07:14     fallocate -l 4G /swapfile2 → chmod 600 → mkswap → swapon → tee -a /etc/fstab → findmnt --verify
```

### 2.5 项5 swap —— PASS
```
== swapon --summary ==
Filename    Type  Size      Used    Priority
/swapfile   file  1048572   103092  -2
/swapfile2  file  4194300   0       -3
== free -h ==   Mem: 3.6Gi total / Swap: 5.0Gi total, 100Mi used, 4.9Gi free
-rw------- 1 root root 1073741824 Oct  1 20:09 /swapfile
-rw------- 1 root root 4294967296 Oct  9 07:14 /swapfile2
== fstab ==  10:/swapfile none swap sw 0 0   11:/swapfile2 none swap sw 0 0
== findmnt --verify ==  0 parse errors, 0 errors, 3 warnings
   [W] target specified more than once / [W] non-bind mount source /swapfile(2) is a directory or regular file
```
- ①Total swap = 1048572 + 4194300 KiB = 5242872 KiB = **5.0000 GiB** ✓(与 free -h 的 5.0Gi 逐位一致)
- ②`/swapfile2` 磁盘实体 4294967296B = **4 GiB**,mtime Oct 9 07:14,**已在 swapon 表内(已启用)**;内核日志佐证:`Oct 9 07:14:17 kernel: Adding 4194300k swap on /swapfile2. Priority:-3 extents:241`
- ③fstab 对应行在位(L10/L11,持久化重启有效)
- ④findmnt --verify **0 parse errors / 0 errors**;3 条 warning 均为 swap 文件常规告警(挂载点 none 重复 + 源为普通文件),非配置错误。

### 2.6 项6 定时器时点 —— PASS
```
== trade-fapi-daily.timer ==  [Timer] OnCalendar=*-*-* 18:10:00 / Persistent=true
== systemctl list-timers --all | grep -i fapi ==
NEXT                        LEFT      LAST                         PASSED   UNIT
Fri 2026-10-09 18:10:00 CST 10h left  Thu 2026-10-08 18:10:00 CST 13h ago  trade-fapi-daily.timer → trade-fapi-daily.service
```
timer `active waiting`,NEXT 正是今日 18:10 CST。service 当前 failed 不阻断 timer 到期再触发(oneshot 无 Restart 语义,每次由 timer 全新启动)。

### 2.7 项7 时区核对 —— PASS
```
Fri Oct  9 07:19:57 AM CST 2026
Local time: Fri 2026-10-09 07:19:57 CST     Time zone: Asia/Shanghai (CST, +0800)
Universal time: Thu 2026-10-08 23:19:57 UTC   System clock synchronized: yes
```
时区为 **Asia/Shanghai(CST,+0800)**,不是 UTC 机器:`18:10` 定时即本地 18:10 北京时间,距复核时点(07:19:57 CST)约 **10 小时 50 分**,deadline 余量充足。旁证:unit 的 ExecMainStart 也标 CST。

### 2.8 项8 「只有 fapi 有内存限制」抽查 —— PASS
```
== sudo grep -rn -E "MemoryHigh=|MemoryMax=|MemorySwapMax=" /etc/systemd/system/ (排除 .bak) ==
/etc/systemd/system/trade-fapi-daily.service:15:MemoryHigh=1.5G
/etc/systemd/system/trade-fapi-daily.service:16:MemoryMax=2G      # 全盘仅此两处
== ls -d /etc/systemd/system/trade-*.service.d ==  No such file or directory   # 无 drop-in 旁路
== ls /usr/lib/systemd/system/trade-* ==           No such file or directory   # 无 lib 侧副本
== systemctl show "trade-*.service" -p Id -p MemoryMax == 仅 trade-fapi-daily.service = 2147483648
   (trade-lhb-backfill / futures-backfill / public-fund-daily / etf-national-team / kelly-intraday-rerun / r2-consistency 均 infinity)
```
- 文件层全量(不只看已加载的 7 个):**只有 fapi 有**内存限制声明;且**今日 07:00 后 /etc/systemd/system 内被改文件只有 trade-fapi-daily.service 一个**(`find -newermt` 实测),不存在"顺手改了别的 unit"。

### 2.9 项9 老 swapfile 保留 —— PASS
`/swapfile`(1 GiB,Oct 1 20:09)仍在 swapon 表内、Priority `-2`(高于新盘 `-3`,即优先使用老的)、Used 103092KB(≈100MB 在用),与「新增 /swapfile2、老的保留」描述一致。

## 3. 声称 vs 实测对照表
| 声称 | 实测 | 判定 |
|---|---|---|
| trade-fapi-daily.service 加 MemoryHigh=1.5G | 文件 L15 + systemd 装载值 1610612736 | 一致 PASS |
| 加 MemoryMax=2G | 文件 L16 + systemd 装载值 2147483648 | 一致 PASS |
| (隐含)只加这两行、无其它改动 | diff 备份→现文件仅 `14a15,16` 两行新增 | 一致 PASS |
| (隐含)改动前已备份 | .bak-20261009-0713 在位、内容无 Memory 行、审计链 cp→tee→reload 顺序正确 | 一致 PASS |
| swap 扩至 5G | 1G+4G=5.0000GiB(swapon/free 双口径一致) | 一致 PASS |
| 新增 /swapfile2 约 4G | 磁盘 4294967296B=4GiB,已 swapon,内核日志 adding 4194300k | 一致 PASS |
| (隐含)fstab 持久化 | L10/L11 双行,fstab findmnt --verify 0 error | 一致 PASS |
| 定时器 18:10 触发 | NEXT=Fri 2026-10-09 18:10:00 CST | 一致 PASS |
| (隐含)老的 /swapfile 保留 | 仍在启用,Priority -2 | 一致 PASS |
| — 未声称项(我主动抽的) — | 服务当前 `failed / Result=oom-kill`(10-08 残留);现文件 vs 09-16 版另差 `TimeoutStartSec 600→0`(今日之前既改) | 观察项 O1/O2,不判 FAIL |

## 4. 未测项清单(如实标注)
1. **MemoryMax 运行时强制生效**:禁 start/restart,无法观察真实运行中的 cgroup 限制落地情况。已验证的是静态配置 + systemd 装载值 + daemon-reload 时序,三链闭合;**运行时行为未实测**。
2. **swap 压力下实际换页/避免 OOM 的效果**:制造内存压力属写操作/风险动作,未做。
3. **今日 18:10 运行的成败**:无法预知(见 R1 提示的风险)。
4. 服务当前 failed 状态**未做**任何清除动作(reset-failed 属写,禁做)。

## 5. 附加发现(供主控判断,均不改变上述 9 项 PASS)
- **R1(风险,建议关注)**:10-08 那次事故是**主机级 OOM**(`constraint=CONSTRAINT_NONE ... global_oom`,不是 cgroup 限额触发),被杀进程正是本服务 cgroup 内 python:
  `Out of memory: Killed process 1806845 (python) total-vm:5082240kB, anon-rss:2044904kB, oom_score_adj:0`
  被杀时 **anon-rss ≈ 1.95 GiB**,而新上限 MemoryMax=**2 GiB**,两者只差约 **50 MiB(2.5%)**。含义:该负载在压力下的内存足迹贴着新上限走,新增 4G swap(1.5G MemoryHigh 处的软回收会把冷页换出)大概率是这次加固真正起作用的部分;但**"2G 硬上限是否足以让同一个作业跑完"存在不确定性**,18:10 那次运行是第一次实跑验证。建议主控把 18:10 运行结果(成功/again oom-kill)纳入观察,若再次被杀则需调 MemoryMax 或降低该作业峰值。
  另注:`memory.max` 与换出页的记账口径属内核语义细节,本报告不做断言,只报上述实测数字。
- **O1(历史差异,非今日)**:现 unit 与 `bak-20260916` 相比,除内存两行外还有 `TimeoutStartSec=600 → 0`;该差异在今日 07:13 备份中已存在,属 09-16 之后的既有改动(效果=不再有 systemd 启动超时兜底)。
- **O2(状态残留)**:服务当前 `failed / oom-kill` 是 10-08 18:10 那次运行的残留,不阻断今日 18:10 再触发;`systemctl status` 会显红属既有现象。
- **环境项**:`root@` 登录被拒(publickey),复核全程用 `ubuntu@` + `tdsignal.pem`(与 memory `ssh-cloud-uses-tdsignal-pem` 一致)。

## 6. 一句话总判
**加固真的在位:两行内存限制已写入 unit 并经 daemon-reload 被 systemd 装载(FragmentPath/生效值双证)、改动前版本已备份且 diff 干净只有 +2 行、swap 5.0GiB 中新增 4G 已启用且 fstab 持久化、定时器 NEXT = 今日 18:10 CST —— 9/9 项 PASS,deadline 前必然生效;唯一遗留不确定性是 2G 硬上限对同一作业是否够用(10-08 被杀进程 RSS 1.95G),建议盯 18:10 实跑结果。**
