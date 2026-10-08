# trade-fapi-daily OOM 根因调研(2026-10-08)— 只读排查记录

> 调研方式:全程只读(零启停 / 零触发 / 零 R2 写 / 零真实外发;探针 static-only,§18 L50)。
> 云上接入:`ssh -4 -i /Users/linhuichen/tdsignal.pem ubuntu@122.51.111.173`,REPO=`/home/ubuntu/code/trade-data`。
> 背景证据(直接采信):`docs/ops/232-markerbuffer-prod-observe-20261008.md`、`docs/ops/cloud-recovery-runbook-20261008.md`。
> 代码版本核对:云上 `app/collector/fapi_daily.py` md5=`682e6b588b82833d8f00ce825792ffaf` == 本机 `/Users/linhuichen/code/trade/app/collector/fapi_daily.py`,**代码无漂移**,本文行号以本机/云上同一文件为准。

---

## 0. 一句话结论(主矛盾裁决)

**二选一裁决:「内存真的涨到 2GB」= 成立(实测且必然);「swap=0,所以一涨就死」= 不成立,需修正为「swap 有 1GB,事故时被 100% 用尽(Free swap=0kB / Total swap=1048572kB)」。**

- 真正的机制:处理 10 年全量 dump(10,322,144 行 / 181MB,行数平时 ×185.8)时 python 内存足迹冲到 **anon-rss 2.0GB / total-vm 5.1GB**,3.8GB RAM + 1GB swap **双满** → `global_oom` → 杀进程。
- **可治本的主矛盾 = 内存需求与机器量级的失配**(「10 年全量重建」这条路径从未在 3.6GB 小机上实测过);触发条件是 `STALE_DAYS=8`(自然日)这条阈值**被国庆 8 天休市精确击穿**——节后首跑必走 full。**这是周期性可复现的设计缺陷,不是随机事故。**
- **「明晚 10-09 18:10 同一 timer 必再犯」= 成立(强判定)**,证据链见 §4;唯一变数 = 人工干预(目前无迹象)。

---

## 1. 事故时间线(2026-10-08)

| 时刻(CST) | 事件 | 证据 |
|---|---|---|
| 18:10:00 | `trade-fapi-daily.service` 被 timer 拉起,ExecStart=`bash scripts/fapi_daily_syn.sh` | E11 / E8 / E9 |
| 18:10 起 | `dump=daily-k`(**非**平时的 `daily-k-10d`)→ 下载 `a_share_daily_k_1d_none_10y_20261008.parquet`(181MB) | E14 |
| ~18:22 | 打印 `parquet rows=10322144`(日志文件 mtime 18:22);随后进入 to_pandas/sort/groupby/map_frame,**再无输出** | E14 |
| ~18:30 | 内存压力开始外溢:`snapd.service Watchdog timeout (limit 5min)` @18:35:51 + SIGABRT ⇒ snapd 心跳在 ~18:30:51 前已丢失 | E21 |
| 18:36→19:23 | 整机用户态冻结(journal 活动骤停:18:42 仅 3 行、18:46:46 一行、18:47:30 一行,直到 OOM 爆发)。冻结窗口 18:37→19:24 采信背景文档 | E21 + 背景 |
| 19:23:39 | `global_oom` 杀掉 python(pid 1806845);unit `Failed with result 'oom-kill'`;冻结解除;Consumed CPU 仅 10min23s(stdout 走 append 文件无 journal 输出) | E11 / E12 |
| 19:23 后 | 链中止:bj_width / bj_width-export 两步未执行(链语义:步骤 1 失败即 exit 1) | E26 |
| 20:45 起 | 后续任务恢复(简报推送 20:45、backfill 21:35、22:30 次日计划等) | 云上 logs mtime |
| 23:47~23:50 | 本次取证:DB `fapi_daily_raw` 仍 latest=20260930、166489 行(**10-08 的 upsert 零落库**) | E17 |

---

## 2. 必查证据点逐条(§任务清单 1~6)

### 2.1 内存规模(现状实测,10-08 23:47)
```
$ free -h
              total        used        free      shared  buff/cache   available
Mem:           3.6Gi       277Mi       414Mi       2.0Mi       3.0Gi       3.1Gi
Swap:          1.0Gi        99Mi       924Mi
$ swapon --show
NAME       TYPE SIZE  USED PRIO
/swapfile  file 1024M 99.5M   -2
$ grep -E "MemTotal|SwapTotal" /proc/meminfo
MemTotal:        3808588 kB
SwapTotal:       1048572 kB
$ cat /etc/fstab   # 末行
/swapfile none swap sw 0 0
```
- **E1/E2/E3/E4**:RAM 3.8GB;**swap 存在且启用(1GB)**;fstab 有条目。
- **E5**:`stat /swapfile` → size 1073741824,Birth **2026-10-01 20:09:36**。
- **E6**:`/var/log/syslog.1` 实证 10-01 安装过程:
  `Oct 1 20:08:12 kernel: Adding 1048572k swap on /swapfile.new` → `Oct 1 20:09:56 kernel: Adding 1048572k swap on /swapfile`(先建 .new 验证后切换)。
  ⇒ **10-08 事故时 swap 1GB 确实在役**。背景里「Free swap = 0kB」是「被用尽」,不是「没有 swap」。

### 2.2 unit 的内存约束(先核 unit 真存在,§18 L49)
- **E7**:`systemctl list-units --all | grep fapi` → `trade-fapi-daily.service loaded failed failed`;`trade-fapi-daily.timer loaded active waiting` ⇒ unit 真实存在(非回填默认值的假对象)。
- **E8**:`systemctl show trade-fapi-daily.service`:
  `MemoryAccounting=yes` / **`MemoryHigh=infinity` / `MemoryMax=infinity` / `MemorySwapMax=infinity`**;`Type=oneshot` / `Restart=no` / **`TimeoutStartSec=0`(无限)**;
  `ExecStart=... start_time=[Thu 2026-10-08 18:10:00 CST] stop_time=[Thu 2026-10-08 19:23:39 CST] pid=1806833; code=killed; status=15/TERM`;`ExecMainStatus=15`。
  ⇒ **无任何单服务内存隔离/上限,失败即拖整机**。
- **E9**:unit 文件 `/etc/systemd/system/trade-fapi-daily.service`:`ExecStart=/bin/bash /home/ubuntu/code/trade-data/scripts/fapi_daily_syn.sh`;`StandardOutput=append:/home/ubuntu/code/trade-data/data/logs/fapi_daily_launchd.log`(stdout/stderr 走文件,journal 里看不到业务输出)。

### 2.3 被杀前的内存轨迹
- **E11**:`journalctl -u trade-fapi-daily --since "2026-10-08 17:00"` 全部输出仅 5 行:18:10:00 Starting → 19:23:39 "A process of this unit has been killed by the OOM killer" / "Failed with result 'oom-kill'" / "Consumed 10min 23.721s CPU time"。
- **E14**:`data/logs/fapi_daily_launchd.log`(mtime 18:22)尾部:
  `=== [fapi-daily-syn] 2026-10-08 18:10:00 start ===` → `[fapi_daily] dump=daily-k dry_run=False` → 下载 10y parquet → `[fapi_daily] parquet rows=10322144 schema=[(thscode,string),(currency,string),(interval,string),(adjusted,string),(date_ms,int64),(open/high/low/close_price,double),(volume,double),(turnover,double)]`,**之后无任何行**(没有 "upserted..." 行)。
- **E16**:残留物证 `data/daily-k.parquet` **181,295,012 B**(mtime 10-08 18:22)——成功路径才会 unlink(代码 L298),被杀导致残留。
- **CP 时间对照**:73 分钟窗口里只烧了 10min23s CPU(≈14%)——**其余在内存回收/swap thrash 等待**,与"冻结 47 分钟"敘事一致。
- 「处理条数异常放大」有据:**平时 55,552 行(10-07),当天 10,322,144 行(×185.8)**(E15/E14)。

### 2.4 触发者与下一次触发时点(不许凭印象)
- **E10**:`/etc/systemd/system/trade-fapi-daily.timer`:**`OnCalendar=*-*-* 18:10:00` + `Persistent=true`**。
  `systemctl list-timers --all`:LAST = `Thu 2026-10-08 18:10:00 CST`;NEXT = **`Fri 2026-10-09 18:10:00 CST (18h left)`**(查询时刻 10-08 23:46)。
  ⇒ **「下一次触发 = 10-09 18:10」实测钉死**。另:10-09 09:26 有 `trade-nextday-gap-check.timer`(与 fapi 无关,E27)。

### 2.5 是不是常态化(单次 vs 趋势)
- **E22**:journal 最早 fapi 记录 = **10-04 18:10**(journal 总量 208MB,保留约 4 天);10-04~10-07 每天正常:`Deactivated successfully`,耗时 2~3 分钟(18:10→18:11/18:12/18:13),CPU 38s。
- 旋转日志(kern.log.1~4 / syslog.1~4.gz,覆盖 09-12~10-08)中 **无任何 "Out of memory: Killed" 记录**。
  ⇒ **可见范围内首次 OOM,前科=无,单次事故**;但见 §4——它是"周期性缺陷"的首次爆发,不是随机。
- (诚实标注:09-25~10-03 的 fapi 运行史因 journal 轮转不可考。)

### 2.6 数据量假设(只读查证)
- **E15**:10-06 / 10-07 日志:`dump=daily-k-10d`,`parquet rows=55552`(10 交易日窗口,文件 ~1.1MB)。
- **E14**:10-08:`dump=daily-k`(全量),"10y" 后缀文件名,`rows=10322144`,文件 **181MB** ⇒ **行数 ×185.8 / 文件 ×164.8**。近 10 日库里并没有"数据量渐增":库 166489 行恒定(E17)。
- **E19**:dump 切换的精确算术(代码 `_stale`,fapi_daily.py L247-255):
  - 10-06:`today-20260930 = 6 <8` → 10d ✓(与日志符)
  - 10-07:`= 7 <8` → 10d ✓(与日志符)
  - **10-08:`= 8 ≥8` → full**(与日志符——dump=daily-k)
  - **10-09:`= 9 ≥8` → full**(推演,见 §4)
- **E24**:10-08 是交易日:mootdx_daily_raw MAX=20261008(492777 行)、baostock_daily_raw MAX=20261008(291998 行)。

---

## 3. 二选一逐项判定 + 主矛盾

### 3.1「内存真的涨到 2GB」→ **成立(实测)**
- **E12** kern.log 原文:
  `Out of memory: Killed process 1806845 (python) total-vm:5082240kB, anon-rss:2044904kB, file-rss:1944kB, shmem-rss:0kB, UID:1000 pgtables:6676kB oom_score_adj:0`
  `oom-kill:constraint=CONSTRAINT_NONE,...,global_oom,task_memcg=/system.slice/trade-fapi-daily.service,task=python,pid=1806845,uid=1000`
- 必然性(代码链,行号=fapi_daily.py):
  - L268 `pq.read_table(dest)` → L271 `table.to_pandas()`(Arrow 表 1032万×11 列 ≈0.8~1GB,转 pandas 再复制一份,4 个 string 列转 object dtype 放大)
  - L187 `df.sort_values(...).reset_index(drop=True)`(再复制)/ L188 `groupby().indices`
  - L283 `map_frame`:物化 **1032 万个 12 元素 tuple 的 list**(理论数 GB 级,被杀时还没到尾部)
  - L288 `upsert_rows`:executemany 一次性 1032 万行
  - 实测被杀点 anon-rss **2.0GB**、total-vm **5.1GB** ⇒ 单进程需求已达 2GB+ 且还在爬升(要不是被杀,峰值还要更高)。
- (估算部分是**推断**;实测锚点仅 anon-rss / total-vm 两个内核数字。)

### 3.2「swap=0,所以一涨就死」→ **不成立,修正版成立**
- **E13** journal kernel 原文:`Free swap = 0kB` / **`Total swap = 1048572kB`** / `Swap cache stats: add 10600024, delete 10591832, find 31533826/33346105` / `8196 pages in swap cache`。
- 读法:**swap 总量 1GB、事故时 0 空闲(被 100% 用尽)**;swap cache 约 1060 万页 in/out(≈40GB 量级换页)+ 3300 万次查找 ⇒ **极端 thrash**(整机冻结 47 分钟的直接来源)。
- 与「有 swap 就不会死」的直觉相反:**1GB swap 已陪跑到底也没救下它**——因为需求按"数 GB 级"(见 3.1)对"RAM 3.8GB + swap 1GB = 4.8GB 总承载"。
- 结论措辞:**不是"没 swap",是"swap 太小 + 需求太大"**,两者叠加。

### 3.3 主矛盾裁决(可治本判定)
| 候选 | 能否治本 | 判定 |
|---|---|---|
| 加 swap(放大器侧) | 缓解,不治本。专家化诚实标注:峰值需求未知,加到 4~6GB**不保证**跑通;且 swap 越大 thrash 越久,可能把"47 分钟冻结"拉成更长 |
| 给 unit 设 MemoryMax(隔离侧) | 治「拖垮整机」,不治 unit 本身(加了它 full 这条必然被杀) |
| **改 full 重建实现为流式分块(内存需求侧)** | **治本**:峰值可压到 <300MB,彻底消除路径级 OOM |
| **修正触发策略(阈值口径错)** | **治本(元二)且便宜**:见下 |
| 加告警 | 只治可见性(且已有覆盖,见 6.6) |

- **阈值口径错在哪(关键洞察)**:`STALE_DAYS=8` 是**自然日**。而 `daily-k-10d` dump 覆盖的是**最近 10 个交易日**——8 个自然日内的交易日数 ≤6~7,**10d 完全够补**。本次国庆 8 天休市后首跑,gap=8 自然日就切 full,**其实 10d dump 本来就能覆盖缺口(09-22~10-08 交易日都在窗口内)**。即:阈值 8 < dump 窗口能力 10 ⇒ **出现了"能补却走了全量"的过度保守切换**。(推断标注:10-08 的 10d dump 未实际下载验证其覆盖区间,但"10d=10 交易日"为代码 docstring L12/L26 明述。)
- **主矛盾一句话**:内存需求方(全量重建链在 3.6GB 小机上物化 1032 万行 × 多层 pandas 副本)与机器量级失配;**触发条件 = 8 天阈值被长假击穿,周期性可复现**。swap 与隔离都是防御层,不是根因。

---

## 4. 「明晚 10-09 18:10 必再犯」核实 → **成立(强)**

| # | 命题 | 证据 | 状态 |
|---|---|---|---|
| 1 | 下一次触发 = 10-09 18:10:00 | E10:NEXT=`Fri 2026-10-09 18:10:00 CST`,OnCalendar 原文 `*-*-* 18:10:00`,timer active waiting | 实测 |
| 2 | 届时时 `gap = 10-09 − 20260930 = 9 ≥ 8` → 走 full | E17(latest=20260930)+ E18(L247-255/L261) | 实测+推演 |
| 3 | latest 不会被别人"救活" | **E20**:全库 grep 确认 `INSERT INTO fapi_daily_raw` 仅存在于 `fapi_daily.py` L222;`width_history.py` L146/L174、`bj_width.py` 只读。⇒ 除 fapi 自己(下次 18:10)外,**没有任何进程会更新 latest** | 实测 |
| 4 | 同输入同规模 | E14/E16:10y dump 模式不变(残留 181MB 文件仍在);10-09 版只会 ≥1032 万行 | 实测+推演 |
| 5 | 环境未变 | 无 MemoryMax(E8)、swap 1GB(E1/E2)、RAM 3.8GB(E3)、代码 md5 未动(§头) | 实测 |
| 6 | systemd 语义:failed oneshot 不影响 timer 下次触发(OnCalendar 到点必 start;Persistent=true 另有补跑) | E8+E10(标准 systemd 行为,未实测重启) | 推断(高置信) |
| 7 | 唯一变数 = 人工干预(代码改/数据改/停 timer),现状无迹象 | 本轮只读排查所见 | 实测 |

**判定:若 10-09 18:10 前不做任何人工干预,同一 OOM 会精确重演**(时间线参考:18:22 进入重处理、18:30+ 开始拖累整机、19:2x OOM;若再次冻结 47 分钟,将波及 20:35 简报推送等后续任务——10-08 当晚 20:45 就是因为 19:24 已恢复才没连带)。

---

## 5. 连带影响

- **fapi 数据缺口**:10-08(交易日,已成前端数据链一环)的 FAPI 日线未入库;库 latest 停在 20260930(E17)。
- **bj_width 缺口**:`fapi_daily_syn.sh` 链步骤 2/3(bj_width 计算 + `fapi_bj_width_export.py` R2 上传)因步骤 1 失败中止(E26);按脚本注释,次日 17:50 runner 会重试(自带补偿设计)。
- **整机冻结 47 分钟(最大生产伤害)**:期间全部定时任务/监控停摆;生产环境一次「单服务拖垮整机」的活案例(违反 §14 精神——生产稳定性 P0)。
- fapi_mutex 互证:10-08 晚 backfill 的 FAPI↔mootdx 互证检查仍在正常执行(读路径,`backfill_evening_launchd.log`)。

---

## 6. 治本建议(完整四层 + 护栏,均只建议不实施)

### 6.1 【10-09 18:10 前护栏 —— 首选,改动最小且自愈】
- **A1(首选)** 临时改 `fapi_daily.py` `STALE_DAYS` 8 → ≥21(或加环境开关 `FAPI_FORCE_10D=1` 强制走 10d,更干净):
  - 效果 ①:10-09 走 10d 路径(55552 行,~2 分钟,内存 <几百 MB),不爆机;
  - 效果 ②:**10d dump 覆盖最近 10 个交易日**,能把 09-30 之后的缺口(含 10-08/10-09)一并补上 → latest 恢复新鲜 → gap 回落 → **自愈**;
  - 效果 ③:给"full 流式化改造"争取无压力窗口。
- **A2(叠加)** 同步加 unit 内存隔离(见 6.2)。
- **A3(备胎)** 若来不及改代码:`systemctl mask trade-fapi-daily.timer` 跳过当次(数据缺口+1 天,不推荐优于 A1)。
- 实施注意:避开 §14 禁区时点(15:35/16:00/17:50/20:35/22:00),建议白天低峰改+自测;生产改动走 review+§0。

### 6.2 unit 隔离(防"单服务拖垮整机",本次事故最大伤害的针对性解)
- `MemoryAccounting=yes` 已有,补 **`MemoryHigh=1.5G` + `MemoryMax=2G`**(可选 `MemorySwapMax=1G` 限制 thrash)。
- 效果:再爆时内核在 cgroup 层杀本 unit,**整机/其它任务/监控存活**(不会再有 47 分钟全站冻结;也消除"冻结期监控自身也卡死"的自监控悖论)。
- 注意:**必须与 6.1/6.3/6.4 配套**——单加隔离,full 路径必然被杀(full 需求 ≥2GB),unit 仍会失败。

### 6.3 swap 扩容(缓解,需配套 6.2 使用)
- `/` 尚有 **20GB** 可用(E23),可加 +4GB swapfile(总 5GB)。
- **诚实标注**:①单独扩容**不保证** full 能跑通(峰值未知);②**swap 越大 thrash 越久,若无 6.2 隔离,可能把劣化窗口从 47 分钟拉得更长**(反效果风险)——因此"扩 swap"必须与"MemoryMax 隔离"捆绑,且它的价值主要是给"流式化之前的过渡期"与常规抖动兜底,不是治本。

### 6.4 代码治本(第一优先):full 重建改流式分块
- 用 `pyarrow.parquet.ParquetFile(...).iter_batches(batch_size=100_000~500_000)` 分批读,批内 map + 分批 `executemany` upsert。
- **实现要点(给 implementer)**:`pct_change` 是"每个 thscode 组内前收"口径(L186-199)——分块必须保「同 thscode 组完整」:dump 已按 thscode 排序,按组切块/批尾未闭合组缓冲至下一批即可;`sort_values` 可退化为局部排序或省去。
- 断言机检保留(L274-281:dup / turnover>volume),改批级执行时用全局累计口径。
- **验收硬标准(防"未实测路径"再坑)**:以内存上限实测通关为准,例如 `systemd-run --scope -p MemoryMax=512M` 或 `/usr/bin/time -v` 全程峰值 RSS <500MB 跑完 full(dry-run 或影子库);**未实测不算 done**(本条正是本次事故根因的镜像:full 路径从落地起就没有在 3.6GB 环境实测过)。

### 6.5 触发策略修正(治本元二,便宜)
- 现状口径错:`STALE_DAYS=8` 自然日 < `10d` dump 的 10 交易日窗口能力 ⇒ 过度保守 + 长假必击穿。
- 修正候选(择一或组合):
  - (a) gap 改按**交易日**计(或直接"库 latest 距今 > 8~9 个交易日"才 full);
  - (b) 收紧 full 条件:仅当缺口超出 10d 窗口(>10 交易日)才 full;
  - (c) full 支持分片(`--since/--until` 分年跑),缺口大时也能分片补齐。
- 若 6.4 已落地(a~c 皆为防御层),但 (b)/(c) 成本极低、语义更正确,建议一并做。

### 6.6 告警/可见性(现状 + 补强)
- **已有覆盖(实测)**:`schedule_monitor_launchd.log` 已报出「云上 failed unit: trade-fapi-daily.service」(`check_failed_units` 通道,自身通道已发告警,E25)。watchman 无 fapi 专门检查项。
- 盲区:整机冻结期间监控自身也在卡死(47min 冻结 vs 心跳阈值 1800s——冻结跨越阈值是否最终告警,本轮未深挖,列为待核);**6.2 的隔离能让监控在事故中存活**,从根上消除该盲区。

### 6.7 缺口恢复路径
- 6.1-A1 一旦执行即自愈(10d 补 09-30 后缺口);若走 6.4 流式化,则修好后让 full 跑一次补齐(低峰时段、避开 §14 禁区)。
- bj_width 缺口:次日 17:50 runner 自动重试(fapi_daily_syn.sh 注释语义),无需单独动作。

---

## 7. 诚实标注(实测 vs 推断 vs 未取)

**实测(可复核,证据号见 §2)**:E1~E17、E19~E27 全部数字/行号/原始输出。
**推断(高置信但未实测)**:
- §3.1 内存链各环节的占用拆分(0.8~1GB / 复制 / tuple list 数 GB)= 估算,实测锚点仅 anon-rss 2.0GB + total-vm 5.1GB;
- §3.3「10-08 的 10d dump 本可覆盖缺口」= 基于"10d=10 交易日"的整数推算(未下载当日 10d dump 验证);
- §4-#6 systemd failed-oneshot 再触发语义 = 标准行为推断;
- 6.3「加 swap 到 5GB 能否让 full 跑通」= **不可知**,不承诺。
**未取(列明)**:
- 18:30→18:37 的内存爬升曲线(journal 无、无历史 ps 采样;与 232 报告 L130 同缺口);
- `map_frame` / rows-list 阶段的实测峰值(进程未活到那点);
- swap 中归属 fapi 进程的页数(swap cache stats 为全局口径);
- 09-25~10-03 fapi 运行史(journal 轮转,保留约 4 天);
- 10-09 的 A 股交易日历精确核实(判定不依赖它——gap 按自然日)。

**合规声明**:全程只读;未启停/重启 unit、未触发 timer、未跑业务脚本(仅 `sqlite3` 只读等价查询用 `python3` uri `mode=ro`)、未写 R2、未产生任何真实外发;本次唯一写入 = 本报告文件 + `/tmp/agent-progress-fapi-oom.md` 进度文件。

---

## 8. 复现命令清单(全部只读,按序可复现本报告)

```bash
SSH='ssh -4 -i /Users/linhuichen/tdsignal.pem -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=3 ubuntu@122.51.111.173'
# 内存/swap/fstab
$SSH 'timeout 30 free -h; timeout 10 swapon --show; timeout 10 grep -E "MemTotal|SwapTotal" /proc/meminfo; timeout 10 cat /etc/fstab; timeout 10 stat /swapfile'
# unit/timer(先核存在再判读;§18 L49)
$SSH 'timeout 10 systemctl list-units --all --no-pager | grep -i fapi; timeout 10 systemctl list-timers --all --no-pager | grep -iE "fapi|NEXT"; timeout 10 systemctl show trade-fapi-daily.service | grep -iE "Memory|OOMPolicy|ExecStart|TimeoutStartSec"; timeout 10 cat /etc/systemd/system/trade-fapi-daily.timer'
# 事故窗口 journal + OOM 原文
$SSH 'timeout 30 journalctl -u trade-fapi-daily --since "2026-10-08 17:00" --until "2026-10-08 20:30" --no-pager | tail -80'
$SSH 'timeout 20 sudo -n grep -a -B8 "Killed process 1806845" /var/log/kern.log; timeout 20 journalctl --since "2026-10-01" --no-pager | grep -iE "Free swap|Total swap|Swap cache"'
# 业务日志(exec 输出)+ 残留物证
$SSH 'timeout 10 tail -60 /home/ubuntu/code/trade-data/data/logs/fapi_daily_launchd.log; timeout 10 ls -la --time-style=long-iso /home/ubuntu/code/trade-data/data/daily-k.parquet'
# DB 只读(云上无 sqlite3 CLI;python3 uri mode=ro,只读)
$SSH 'timeout 60 python3 -c "import sqlite3;c=sqlite3.connect(\"file:/home/ubuntu/code/trade-data/data/stock_daily.db?mode=ro\",uri=True);print(c.execute(\"SELECT MAX(date),COUNT(*) FROM fapi_daily_raw\").fetchone())"'
# 历史前科(旋转日志)
$SSH 'timeout 20 sudo -n sh -c "zcat /var/log/kern.log*.gz | grep -a \"Out of memory: Killed\"; zcat /var/log/syslog*.gz | grep -a \"Out of memory: Killed\"; grep -a \"Out of memory: Killed\" /var/log/syslog.1"'
```
代码行号锚点(本机 == 云上 md5):`/Users/linhuichen/code/trade/app/collector/fapi_daily.py`:L60(STALE_DAYS=8)/L247-255(_stale)/L261(dump 选择)/L268-271(read_table→to_pandas)/L283(map_frame)/L288(upsert_rows);`/Users/linhuichen/code/trade/scripts/fapi_daily_syn.sh`(三步链)。
