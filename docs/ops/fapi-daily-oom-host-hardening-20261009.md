# trade-fapi-daily OOM 主机侧加固(2026-10-09)— 实施记录

> 任务:#238 治本·云上主机层(隔离边界:只动云上主机配置 + systemd unit,不改业务代码/脚本逻辑,仓库侧只写本报告)。
> 依据:只读定因报告 `docs/ops/fapi-daily-oom-rootcause-20261008.md`(238 行)。
> 云上接入:`ssh -4 -i /Users/linhuichen/tdsignal.pem ubuntu@122.51.111.173`(每条命令带 `ConnectTimeout=10 / ServerAliveInterval=5 / ServerAliveCountMax=3`,远端命令 `timeout N` 包裹)。
> 实施时间窗:2026-10-09 **07:13~07:16 CST**(deadline = 当日 18:10,提前约 11 小时)。
> 合规声明:全程 **零 start/restart/stop/触发 unit**;零业务脚本执行(含禁跑 `fapi_daily_syn.sh`/`fapi_daily.py`);零 R2 写;零真实外发(邮件/飞书/告警)。探针 static-only(§18 L50)。

---

## 0. 一句话结论

**① unit 内存隔离已生效**:`trade-fapi-daily.service` 加 `MemoryHigh=1.5G` + `MemoryMax=2G`,`systemctl show` 复读命中(`MemoryHigh=1610612736` / `MemoryMax=2147483648`),`FragmentPath` 证实值来自本 unit 文件而非编译期默认(默认=`infinity`)。
**② swap 已扩容至 5G**:新增 `/swapfile2`(4G)并写入 `/etc/fstab`,`free -h` Total swap=5.0Gi(改前 1.0Gi)。
**③ deadline 已钉死**:timer NEXT=`Fri 2026-10-09 18:10:00 CST`,改动早于该点约 11h,届时自然带新约束跑。
**④ 举一反三**:全机 41 个 `trade-*.service` 中,**加固前 41/41 无任何内存上限**;加固后仅 fapi 一个有限制,其余 40 个仍无(只报不改)。历史 OOM 仅 fapi 一次,无其他 unit 内存型事故记录。
**⑤ 仓库副本**:仓库**无 `.service` 文件**;但有云上 unit 的**快照副本** 2 处(见 §5)。

---

## 1. unit 内存隔离(必做项)完成记录

### 1.1 改前前置核查(§18 L49:先核 unit 真存在)
```
$ systemctl is-active trade-fapi-daily      → failed      # 未在运行,可安全改(硬前提满足)
$ systemctl list-units --all | grep fapi
  ● trade-fapi-daily.service  loaded  failed  failed   Trade fapi-daily (源 com.trade.fapi-daily)
    trade-fapi-daily.timer    loaded  active  waiting  Trade fapi-daily daily 18:10 (源 com.trade.fapi-daily)
  ⇒ unit 真实存在(非回填默认值的假对象)
$ systemctl show trade-fapi-daily -p MemoryMax -p MemoryHigh -p MemorySwapMax -p MemoryAccounting
  MemoryAccounting=yes
  MemoryHigh=infinity          # 改前:无上限
  MemoryMax=infinity           # 改前:无上限
  MemorySwapMax=infinity
```

### 1.2 备份(§25 精神:改前先备份 + md5 核对)
```
$ sudo cp -a /etc/systemd/system/trade-fapi-daily.service \
            /etc/systemd/system/trade-fapi-daily.service.bak-20261009-0713
$ md5sum /etc/systemd/system/trade-fapi-daily.service .bak-20261009-0713
  b43c6f6ac8919569808947c3e47f5089  /etc/systemd/system/trade-fapi-daily.service
  b43c6f6ac8919569808947c3e47f5089  /etc/systemd/system/trade-fapi-daily.service.bak-20261009-0713   # 备份==原件
```
(旁注:目录内另有历史备份 `.bak-20260916`(673B);本任务未触碰。)

### 1.3 改前 unit 原文(改动基线)
```ini
[Unit]
Description=Trade fapi-daily (源 com.trade.fapi-daily)

[Service]
User=ubuntu
EnvironmentFile=/home/ubuntu/code/trade-data/.env
Type=oneshot
WorkingDirectory=/home/ubuntu/code/trade-data
Environment=GIT_REPO=/home/ubuntu/code/trade-data-signal
Environment=REPO=/home/ubuntu/code/trade-data
Environment=MAIN_REPO=/home/ubuntu/code/trade-data
ExecStart=/bin/bash /home/ubuntu/code/trade-data/scripts/fapi_daily_syn.sh
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
TimeoutStartSec=0
StandardOutput=append:/home/ubuntu/code/trade-data/data/logs/fapi_daily_launchd.log
StandardError=append:/home/ubuntu/code/trade-data/data/logs/fapi_daily_launchd.err
```

### 1.4 改后 unit 原文(新增 2 行,其余逐字不变)
```ini
[Unit]
Description=Trade fapi-daily (源 com.trade.fapi-daily)

[Service]
User=ubuntu
EnvironmentFile=/home/ubuntu/code/trade-data/.env
Type=oneshot
WorkingDirectory=/home/ubuntu/code/trade-data
Environment=GIT_REPO=/home/ubuntu/code/trade-data-signal
Environment=REPO=/home/ubuntu/code/trade-data
Environment=MAIN_REPO=/home/ubuntu/code/trade-data
ExecStart=/bin/bash /home/ubuntu/code/trade-data/scripts/fapi_daily_syn.sh
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
TimeoutStartSec=0
MemoryHigh=1.5G          # ← 新增
MemoryMax=2G             # ← 新增
StandardOutput=append:/home/ubuntu/code/trade-data/data/logs/fapi_daily_launchd.log
StandardError=append:/home/ubuntu/code/trade-data/data/logs/fapi_daily_launchd.err
```
> 改动方式:`sudo tee` 全量重写(内容 = 改前原文逐字 + 2 行),非 sed 局部插,避免误伤中文 Description 等行。

### 1.5 daemon-reload + 生效复读(§18 L49:核值来自本行,非默认)
```
$ sudo systemctl daemon-reload              → reload_ok
$ systemctl show trade-fapi-daily -p MemoryHigh -p MemoryMax -p MemoryAccounting -p FragmentPath
  MemoryAccounting=yes
  MemoryHigh=1610612736                     # = 1.5 GiB ✓
  MemoryMax=2147483648                      # = 2 GiB   ✓
  FragmentPath=/etc/systemd/system/trade-fapi-daily.service   # ← 值来自我们写的文件
$ systemctl list-units --all | grep "trade-fapi-daily"   # 复核 unit 仍真存在
  ● trade-fapi-daily.service  loaded  failed  failed
```
- **三重佐证值非默认**:①`FragmentPath` 指向本文件;②数值 == 我写的 1.5G/2G(默认应为 `MemoryMax=18446744073709551615`=infinity);③unit 经 `list-units` 确认真存在(非 L49 的假对象)。
- **`is-active` 仍为 `failed`**:是 10-08 那次真实 OOM 的残留失败态,`daemon-reload` 不重置(本任务**不做** `reset-failed`,以免任何非预期动作;timer 到点仍会 start,见 §3)。

### 1.6 cgroup 能力佐证(不执行任何 unit 的替代验证)
```
$ stat -fc %T /sys/fs/cgroup   → cgroup2fs
$ cat /sys/fs/cgroup/cgroup.controllers → cpuset cpu io memory hugetlb pids rdma misc   # memory 控制器在
$ systemctl --version | head -1 → systemd 249 (249.11-0ubuntu3.20)
```
⇒ cgroup v2 `memory.max`/`memory.high` 语义可用(`MemoryAccounting=yes` 本就生效)。**注**:因硬约束禁 start,未用 `systemd-run … MemoryMax` 起真进程实测 cgroup 施加(此为 run 类动作),此为**替代验证**、诚实标注。

### 1.7 回退命令(恢复备份 + daemon-reload)
```bash
ssh -4 -i /Users/linhuichen/tdsignal.pem ubuntu@122.51.111.173 \
  'sudo cp -a /etc/systemd/system/trade-fapi-daily.service.bak-20261009-0713 \
             /etc/systemd/system/trade-fapi-daily.service && sudo systemctl daemon-reload'
```
> 校验:`systemctl show trade-fapi-daily -p MemoryMax -p MemoryHigh` 应回 `infinity`。备份文件保留在云上 `/etc/systemd/system/trade-fapi-daily.service.bak-20261009-0713`。

---

## 2. swap 扩容(先复核再决定)完成记录

### 2.1 改前现状
```
$ free -h   → Mem: 3.6Gi(used 274Mi) / Swap: 1.0Gi(used 103Mi)
$ swapon --show
  NAME       TYPE SIZE   USED PRIO
  /swapfile  file 1024M  103.7M   -2
$ cat /proc/swaps → /swapfile  file  1048572  106164  -2
$ /etc/fstab 末行 → /swapfile none swap sw 0 0
$ sudo -n true → SUDO_OK            # ubuntu 有可用免密 sudo ⇒ 可实施
$ df -h / → /dev/vda2  59G  38G  20G  66%   # 剩 20G,足够 +4G
```

### 2.2 选型:新增 `/swapfile2`(而非扩展现有 `/swapfile`)
**理由**:①**非破坏性**——无需 `swapoff` 在役的 `/swapfile`(其上有 ~103MB 活跃页),避免动到正被使用的交换区;②**可逆面最干净**——回退=swapoff + 删文件 + 删 fstab 行,不触及既有换区;③既有 `/swapfile`(Birth 2026-10-01,经 `.new` 验证后切换)原封不动,风险最低。

### 2.3 实施 + 实测
```
$ sudo fallocate -l 4G /swapfile2                → fallocate_ok
$ sudo chmod 600 /swapfile2                      → chmod_ok
$ sudo mkswap /swapfile2
  Setting up swapspace version 1, size = 4 GiB (4294963200 bytes)
  UUID=1595f754-efb3-4c20-9629-a50bed1595ce
$ sudo swapon /swapfile2                          → swapon_ok
$ echo "/swapfile2 none swap sw 0 0" | sudo tee -a /etc/fstab
```
**实测验证三件**:
```
$ swapon --show
  NAME        TYPE SIZE   USED PRIO
  /swapfile   file 1024M  100.9M   -2
  /swapfile2  file    4G     0B    -3
$ swapon --summary
  /swapfile     file  1048572  103348  -2
  /swapfile2    file  4194300       0  -3        # 4194300 KB ≈ 4 GiB
$ free -h  → Swap: 5.0Gi  total(used 100Mi / free 4.9Gi)   # 改前 1.0Gi ⇒ 1.0G + 4.0G = 5.0G ✓
$ tail -4 /etc/fstab
  /dev/disk/by-uuid/7bccaefa-… / ext4 defaults 0 1
  /swapfile  none swap sw 0 0
  /swapfile2 none swap sw 0 0        # ← 新增行
$ sudo findmnt --verify → 0 parse errors, 0 errors, 3 warnings
  (warning 仅「swapfile 是普通文件」×2 + 「target 重复」,对既有 /swapfile 同样存在,属正常)
```
⇒ **fstab 语法机检 0 parse errors**,重启后 swap 自动 5G。PRIO:`/swapfile2`=-3(内核默认,低于 /swapfile 的 -2)⇒ 先填满高优先级、再用新增页,不影响现有行为。

### 2.4 回退命令(swapoff + 删文件 + 删 fstab 行)
```bash
ssh -4 -i /Users/linhuichen/tdsignal.pem ubuntu@122.51.111.173 \
  'sudo swapoff /swapfile2 && sudo rm -f /swapfile2 && sudo sed -i "\|^/swapfile2 |d" /etc/fstab && swapon --show'
```
> 校验:`swapon --show` 应只剩 `/swapfile`、`free -h` Total swap 回 1.0Gi。**删前无数据丢失风险**(swap 非持久数据,且当前 USED=0)。

### 2.5 诚实标注(承接定因报告 §6.3)
- swap 扩容是**缓解层,非治本**:full 路径峰值需求未知,"加到 5G 不保证 full 跑通"。
- **swap 越大 thrash 可能越久**——但它已与 ①`MemoryMax=2G` 隔离**捆绑**实施(隔离让峰值进程在 cgroup 层被杀,不会再有 47 分钟整机冻结),故不构成"单独扩 swap 反效果"。
- 未见 `MemorySwapMax` 收窄(仍 `infinity`):**此处存在一个方向性分叉,留给主控/用户拍板**——定因报告 §6.2 曾提"可选 `MemorySwapMax=1G` 限制 thrash"。本任务 prompt 明确只要求 `MemoryHigh/MemoryMax` 两项,故**未擅自加**。若加,进程超 2G RAM 后仅能再借 1G swap 即被 cgroup 杀,失败更快、thrash 更短;不加则可能长时间慢速 thrash(但整机已被隔离保护)。

---

## 3. deadline 核实(只读,OnCalendar 原文)

```
$ systemctl list-timers --all | grep -i fapi
  NEXT: Fri 2026-10-09 18:10:00 CST   LEFT: 10h left
  LAST: Thu 2026-10-08 18:10:00 CST   (13h ago)
  UNIT: trade-fapi-daily.timer  → ACTIVATES: trade-fapi-daily.service
$ grep -E "OnCalendar|Persistent" /etc/systemd/system/trade-fapi-daily.timer
  OnCalendar=*-*-* 18:10:00
  Persistent=true
```
- NEXT `Fri 2026-10-09 18:10:00 CST` **实测钉死**(非凭印象)。
- 本次改动完成于 07:16 ⇒ **早于触发点约 11 小时**,`daemon-reload` 已应用,**届时 timer start 的进程将带新内存约束**。
- systemd 语义:上次 `failed`(oneshot)不阻止 OnCalendar 到点 start(定因报告 §4-#6),故无需 reset-failed 也能生效。

---

## 4. 举一反三:同类无隔离 unit 清单(只报不改)

### 4.1 全机 trade-* unit 内存上限覆盖扫描
```
$ ls /etc/systemd/system/trade-*.service | wc -l   → 41
$ grep -L -E "MemoryMax|MemoryHigh" /etc/systemd/system/trade-*.service | wc -l
  加固前:41(全无)          加固后:40(仅 fapi 有限制)   # 无 drop-in(.service.d 不存在)
```
⇒ **加固前 41/41 无内存上限**;加固后**仅 `trade-fapi-daily.service` 一个有限制,其余 40 个全部裸奔**。

### 4.2 历史内存型事故核查(跨全量日志 + journal)
```
$ kern.log / kern.log.1 / kern.log*.gz / syslog / syslog.1 / syslog*.gz / journalctl
  grep "Out of memory: Killed"
  ⇒ 全库唯一命中:Oct 8 19:23:39  python(pid 1806845)  anon-rss:2044904kB  = 本次 fapi 事故
$ journalctl grep "Failed with result"
  trade-fapi-daily.service: Failed with result 'oom-kill'   ← 唯一 oom-kill
  其余全为 'exit-code'(非内存型)/ snapd 'watchdog'/'timeout'(10-08 被拖累的旁证)
```
⇒ **严格结论:除 fapi 外,无任何 unit 有内存型(oom-kill/OOM)事故记录**。故"缺上限 + 有内存前科"的交集 = **仅 fapi 自己(已加固)**。

### 4.3 风险候选清单(缺上限 + 跑同类内存密集型任务,建议后续评估;只报不改)
以下 unit **无内存上限**、且执行"进程内 python 重活/全量批处理"同模式任务(与 fapi full 路径同族),是潜在"下一个拖垮整机"候选:
| unit | ExecStart | 备注 |
|---|---|---|
| `trade-update-all.service` | `update_all.sh` | **定因/恢复报告已点名**:`docs/ops/cloud-recovery-runbook-20261008.md:290` 建议给它加 `MemoryHigh` 兜底(并提示"慎用 MemoryMax") |
| `trade-lab-auto.service` | `update_lab.sh` | lab 全量重算 |
| `trade-public-fund-full.service` | `public_fund_full.sh` | 公募全量 |
| `trade-pf-stage0-nav/-risk/-overview/-manager.service` | `stage0_*.sh` | 公募阶段0 |
| `trade-backfill-evening.service` | `backfill_metrics.sh` | 傍晚回填 |
| `trade-rzhb-backfill.service` / `trade-lhb-backfill.service` / `trade-futures-backfill.service` / `trade-turnover-backfill.service` | `*_backfill.sh` | 回填链 |
| `trade-etf-track-index.service` / `trade-lof-track-index.service` | `fetch_*_track_index.py` | 直接 python 进程 |
| `trade-fetch-news.service` | `fetch_news.py` | 直接 python 进程 |
| `trade-s06-snapshot.service` / `trade-kelly-intraday-rerun.service` | `*_intraday*.sh` / `s06_snapshot.sh` | 快照/盘中重算 |
> 诚实标注:4.3 是**基于 ExecStart 形态的推断候选**,非实测内存足迹;是否真需加限,应由后续调研(峰值 RSS 实测)定,本任务只做清单不做结论。

---

## 5. 仓库侧副本核查

- **仓库无 `.service` 文件**:`git ls-files | grep -iE '\.(service|timer)$'` 无输出(云上 unit 为**手管**,`git pull` 不更新——符合 §14 现状)。
- **但存在 2 处云上 unit 快照副本(内容含 fapi unit,均为"改前"版、现属过时)**:
  1. `docs/deploy/systemd-units-cloud-snapshot.txt:187`(`@@@FILE:trade-fapi-daily.service`,内容 **无** `MemoryHigh/MemoryMax`)
  2. `docs/deploy/systemd-units-20260912.md:402`(同 unit 文档版,亦无内存行)
- **含义**:云上手管 ⇒ 云上改了、仓里这份**不会自动跟**;这两处快照/doc 现与云上实际**不一致**。按隔离边界,**本任务不去改仓库那份**,仅在此报告登记"需有人同步"。
- 另有 `scripts/gen_systemd_units.py`(unit 生成器)与 `scripts/systemd_timeout_gradient_audit.py`(超时梯度审计):**均未涉及 `MemoryMax/MemoryHigh`**(`grep` 无命中)⇒ 现有生成/审计机制不覆盖内存上限,若后续批量加固需扩这两处。

---

## 6. 自验逐项结果(对照任务验收口径)

| # | 验收点 | 结果 |
|---|---|---|
| 1 | unit 改了 + `systemctl show` 实测值 | ✅ `MemoryHigh=1610612736`/`MemoryMax=2147483648`(1.5G/2G) |
| 2 | 值来自我们那行(非默认假绿) | ✅ `FragmentPath=/etc/systemd/system/trade-fapi-daily.service` + unit 经 list-units 确认真存在 |
| 3 | 改前确认 unit 未运行 | ✅ `is-active=failed`(未运行)后才改 |
| 4 | 改前备份 + md5 核对 | ✅ `.bak-20261009-0713`,md5 `b43c6f6a…` 与原一致 |
| 5 | `daemon-reload` 已执行 | ✅ reload_ok |
| 6 | swap 现状复核(swapon/free//proc/swaps/fstab) | ✅ 见 §2.1 |
| 7 | swap 扩到 5G + 实测(总量/Total/--summary) | ✅ 1.0G+4.0G=5.0G;`swapon --summary` 4194300KB;`free -h` 5.0Gi |
| 8 | swap 回退命令 | ✅ swapoff+rm+删 fstab 行(§2.4) |
| 9 | fstab 语法机检 | ✅ `findmnt --verify` 0 parse errors |
| 10 | deadline NEXT=18:10 + OnCalendar 原文 | ✅ `Fri 2026-10-09 18:10:00 CST` + `OnCalendar=*-*-* 18:10:00` |
| 11 | 改动早于该时点 | ✅ 07:16 完成,约 11h 提前 |
| 12 | 同类无隔离 unit 清单 | ✅ §4(40/41 仍无;历史 OOM 仅 fapi) |
| 13 | 仓库有无副本 | ✅ §5(无 .service;有 2 处快照副本,已登记) |
| 14 | 零 start/restart/触发 + 零业务脚本 + 零 R2 + 零外发 | ✅ 全程只读 + 上述配置改动 |
| 15 | 破坏性操作可逆 | ✅ unit / swap 均附回退命令 |

---

## 7. 未实施项 / 待拍板分叉

1. ~~**`MemorySwapMax` 未设**(仍 `infinity`):定因报告 §6.2 曾提"可选 1G 限 thrash",本任务 prompt 只要 `MemoryHigh/MemoryMax` 两项,**未擅自加**。加与不加是行为分叉(见 §2.5),**待主控/用户拍板**。~~ → ✅ **已于 2026-10-09 07:24 补上 `MemorySwapMax=512M`**(见文末「补强:MemorySwapMax」节,已生效复读 `MemorySwapMax=536870912`)。
2. **其余 40 个 unit 未加内存隔离**:§4.3 候选清单等**后续评估**(需先实测峰值 RSS)。
3. **仓库 2 处快照副本未同步**(§5):属"需有人管",本任务按边界不碰仓库那份;建议后续派单同步或注明"云上为准"。
4. **unit 失败态未 reset**(§1.5):`trade-fapi-daily.service` 仍 `failed`(10-08 真实事件残留),本任务不 reset-failed;如需清告警由主控/后续决定。

---

## 8. 复现命令清单(只读为主)

```bash
SSH='ssh -4 -i /Users/linhuichen/tdsignal.pem -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=3 ubuntu@122.51.111.173'
# unit 生效复读
$SSH 'timeout 10 systemctl show trade-fapi-daily -p MemoryHigh -p MemoryMax -p MemoryAccounting -p FragmentPath; timeout 10 systemctl list-units --all --no-pager | grep fapi'
# swap 实测
$SSH 'timeout 10 swapon --show; timeout 10 swapon --summary; timeout 10 free -h; timeout 10 tail -4 /etc/fstab'
# deadline
$SSH 'timeout 10 systemctl list-timers --all --no-pager | grep -i fapi; timeout 10 grep -E "OnCalendar|Persistent" /etc/systemd/system/trade-fapi-daily.timer'
# 同类无隔离
$SSH 'timeout 10 ls /etc/systemd/system/trade-*.service | wc -l; timeout 10 grep -L -E "MemoryMax|MemoryHigh" /etc/systemd/system/trade-*.service'
# 备份在位
$SSH 'timeout 10 sudo ls -la /etc/systemd/system/trade-fapi-daily.service.bak-20261009-0713'
```

---

## 补强:MemorySwapMax(2026-10-09 07:24)

> 任务:#238 补强项,承接 §7 未实施项 1(原 `MemorySwapMax` 仍 `infinity`)。硬约束:改后**只许** `daemon-reload`,禁 start/restart/stop/触发;禁业务脚本;禁真实外发(邮件/飞书/R2/告警)。实施时间窗 07:24 CST(deadline=当日 18:10,提前约 10.8h)。

### A. 为什么补这一项
10-08 该 unit 是**主机级 global_oom**(被杀进程 `anon-rss≈1.95GiB`),当时 `/swapfile`(1G)被榨干,导致 **47 分钟极度 thrash 冻结**。07:13 第一次加固只设了 `MemoryHigh=1.5G`/`MemoryMax=2G`,**漏了 `MemorySwapMax`**;systemd 该项默认=`infinity`,进程仍可无限往 swap 灌 ⇒ thrash 风险仍在。本次补 `MemorySwapMax=512M`,给 swap 侧也钉上边界。

### B. 改了什么(只加一行,零其它改动)
`/etc/systemd/system/trade-fapi-daily.service` 的 `[Service]` 段中,**`MemoryMax=2G` 之后新增一行**:

```ini
MemoryHigh=1.5G
MemoryMax=2G
MemorySwapMax=512M    # ← 本次唯一新增
```

改动方式:`sudo sed -i '/^MemoryMax=2G$/a MemorySwapMax=512M'`(定点插行)。改后 `sudo diff 备份 → 现文件` **仅 1 行新增,无任何其它差异**:

```
$ sudo diff /etc/systemd/system/trade-fapi-daily.service.bak-20261009-0724 \
            /etc/systemd/system/trade-fapi-daily.service
16a17
> MemorySwapMax=512M
```
(`diff` 返回码 1 = 有差异,为正常;差异块仅此一处 `16a17`。)

### C. 备份路径与 md5(§25 改前先备份)
```
$ sudo cp -a .../trade-fapi-daily.service .../trade-fapi-daily.service.bak-20261009-0724
$ sudo md5sum .../trade-fapi-daily.service .../trade-fapi-daily.service.bak-20261009-0724
d9c86230fc4b0f3bb21a8964dda21b86  /etc/systemd/system/trade-fapi-daily.service
d9c86230fc4b0f3bb21a8964dda21b86  /etc/systemd/system/trade-fapi-daily.service.bak-20261009-0724
```
- 改前 md5 = `d9c86230fc4b0f3bb21a8964dda21b86`(双文件一致,备份 = 改前状态)。
- 改后新 md5 = `d949ac07dc93a93f6ac90d2633de1bb0`(仅多一行所致)。
- 备份保留在云上:`/etc/systemd/system/trade-fapi-daily.service.bak-20261009-0724`。
- 注:上一轮 `.../trade-fapi-daily.service.bak-20261009-0713`(671B,首次加固前基线)保留不动。

### D. 逐项验证证据(daemon-reload 后复读)
```
$ sudo systemctl daemon-reload                → reload_rc=0
$ systemctl show trade-fapi-daily.service -p MemoryHigh -p MemoryMax -p MemorySwapMax -p FragmentPath -p ActiveState
  MemoryHigh=1610612736        # = 1.5 GiB  ✓
  MemoryMax=2147483648         # = 2 GiB    ✓(未动)
  MemorySwapMax=536870912      # = 512 MiB  ✓(本次新增项,已生效)
  FragmentPath=/etc/systemd/system/trade-fapi-daily.service   # ← 值来自本 unit 文件,非默认(默认=infinity)
  ActiveState=failed           # 10-08 残留失败态,未 reset(按约束不动)
```

| 项 | 期望 | 实测 | 结果 |
|---|---|---|---|
| MemoryHigh | 1610612736 | 1610612736 | ✅ |
| MemoryMax | 2147483648 | 2147483648 | ✅(未动,保持 2G) |
| MemorySwapMax | 536870912 | 536870912 | ✅(本次新增) |
| FragmentPath | 本 unit 文件 | 本 unit 文件 | ✅ |
| ActiveState | failed(保持) | failed | ✅(未 reset) |
| diff 仅 1 行新增 | 仅 `MemorySwapMax=512M` | `16a17` 一处 | ✅ |

### E. 主机规格(供后续评估)
```
MemTotal:        3808588 kB      # ≈ 3.63 GiB
nproc:           4
free -h:
               total        used        free      shared  buff/cache   available
Mem:           3.6Gi       277Mi       196Mi       2.0Mi       3.2Gi       3.1Gi
Swap:          5.0Gi       100Mi       4.9Gi
swapon --summary:
Filename        Type   Size      Used    Priority
/swapfile       file   1048572   103092  -2
/swapfile2      file   4194300   0       -3
```
> 观察:整机 RAM 仅 3.6Gi,`MemoryMax=2G` 已占约 55% 物理内存;`MemorySwapMax=512M` 首跑时 systemd v249 对 swap 上限的施加需后续实测佐证(本任务禁 start 无法实跑,诚实标注)。

### F. 回滚命令
```bash
ssh -4 -i /Users/linhuichen/tdsignal.pem ubuntu@122.51.111.173 \
  'sudo -n cp -a /etc/systemd/system/trade-fapi-daily.service.bak-20261009-0724 \
             /etc/systemd/system/trade-fapi-daily.service && sudo -n systemctl daemon-reload'
```
> 校验:`systemctl show trade-fapi-daily -p MemorySwapMax` 应回 `infinity`。回滚后 md5 应回到 `d9c86230fc4b0f3bb21a8964dda21b86`。