# #238 fapi 18:10 实跑复核(云上只读)——2026-10-09

- 复核人: tester agent;执行时点: 2026-10-09 20:07~20:35 CST(云上 host 时间 UTC+8,SSH 实测 UTC 12:07 ⇒ 北京 20:07)
- 口径: 云上**只读**、探针 **static-only**(§18 L50);未跑业务脚本主体、未触发 unit、零 R2 写、零外发
- 场景: #238 治本链(unit 加 MemoryHigh/MemoryMax + swap 扩 5G + 补 MemorySwapMax + 代码侧 STALE 可配 + 流式分块)后的**首次合体实跑**,即 deadline 验收点

---

## 0. 声明(先说问题,不掩藏)

1. ⚠️ **违规自报(轻微、非业务)**:一条命令里有一处**冗余重定向**,在云上误写入 1 个临时文件 `/tmp/_NO_WRITE`(内容=18:10 段日志副本的 awk 中间输出,0 业务影响:不在业务目录、不涉 DB/R2/告警/通知)。违反"禁写任何文件"的字母要求,如实自报。
   清理:`rm -f /tmp/_NO_WRITE`(或下次云上作业顺手清)。
2. 残留后台任务: **无**(全程前台命令,每条 Bash 均带超时;无 `moved to the background`)。

---

## 1. 结论(四查)

| # | 检查项 | 结果 | 一句话 |
|---|---|---|---|
| 1 | unit 触发与结果 | ✅ **PASS** | 18:10:00 准点触发,18:10:53 正常退出,Result=success / ExecMainStatus=0 / NRestarts=0 |
| 2 | cgroup 内存峰值 | ⚠️ **不可读(观测缺口)** | 该机 systemd 249 + 内核 5.15 **均不支持** `MemoryPeak` / `memory.peak`,且 oneshot cgroup 已销毁 ⇒ 峰值无法事后读。可证"未触 MemoryMax=2G"(无 OOM kill) |
| 3 | OOM / thrash / 超时 / traceback | ✅ **PASS(无)** | 本次运行段 0 处告警关键词;内核日志 18:00 后无 OOM;stderr 仅 4 行 resolve_repo |
| 4 | 产物落地 | ✅ **PASS** | DB `fapi_daily_raw` 177,603 行 / 5,573 codes / max date=20261009(独立 SQL 复核);线上 overview.json 北交所当日值 6 项齐(source=fapi);7 文件 R2 上传日志 7/7 + CF purge 7/7 |

**门控结论:`#238 18:10 实跑 PASS`;唯一缺口 = 峰值读数不可得(见 §3),属观测手段缺口,非本次运行异常。**

---

## 2. 逐项证据(可复核)

### 2.1 触发与结果(第 1 条)

```
$ ssh ... 'systemctl show trade-fapi-daily.service -p ActiveState -p SubState -p Result \
    -p ExecMainStatus -p ExecMainStartTimestamp -p ExecMainExitTimestamp -p NRestarts ...'
Result=success
NRestarts=0
ExecMainStartTimestamp=Fri 2026-10-09 18:10:00 CST
ExecMainExitTimestamp=Fri 2026-10-09 18:10:53 CST
ExecMainStatus=0
ActiveState=inactive / SubState=dead        # oneshot 跑完的正常终态
```

- 定时器在册且下次已排:`trade-fapi-daily.timer` NEXT=2026-10-10 18:10,LAST=2026-10-09 18:10(1h57min ago)⇒ **今日准点触发,非"未触发"**
- 耗时 53s、CPU 15.824s(`journalctl` 原文 "Consumed 15.824s CPU time")

### 2.2 内存设置在位(治本链 ① ② 的落实)

```
$ systemctl show trade-fapi-daily.service -p MemoryHigh -p MemoryMax -p MemorySwapMax -p MemoryAccounting
MemoryAccounting=yes
MemoryHigh=1610612736           # 1.5G
MemoryMax=2147483648            # 2G
MemorySwapMax=536870912         # 512M  ← #238 ② 补的项,已在位
```

unit 文件(`systemctl cat`,只读)同时含 `MemoryHigh=1.5G` / `MemoryMax=2G` / `MemorySwapMax=512M` / `TimeoutStartSec=0`。
swap 扩容到位:`/proc/meminfo` ⇒ `SwapTotal: 5242872 kB`(≈5.0G);复核时 `SwapFree: 5127008 kB`(仅用 ~109MB)。

### 2.3 日志与 OOM(第 3 条)

- `journalctl -u trade-fapi-daily.service --since "2026-10-09 17:30:00"`:仅 3 行(18:10:00 Starting → 18:10:53 Deactivated/Finished)**无 OOM、无 thrash、无超时**
- 内核:`journalctl -k --since "2026-10-09 18:00:00" | grep -iE "oom|killed process|thrash"` ⇒ **空**
- 运行段日志扫描(`awk '/2026-10-09 18:10:00 start/{f=1} f'` 后 `grep -cE "WARN|ERROR|FATAL|Traceback"`)⇒ **0**
- stderr 文件 `fapi_daily_launchd.err` 全文 = 4 行 `resolve_repo: ... (source=env)`,**无 traceback**
- 对照(上一轮故障证据,仅在 dmesg 里可查):
  `Thu Oct 8 19:23:36 ... task_memcg=/system.slice/trade-fapi-daily.service, task=python, pid=1806845 ... anon-rss:2044904kB`(=1.95G,逼近 2G 上限被杀)—— 今日**无同类记录**

### 2.4 走的是增量路径(治本链 ① 约定的验收口径)

日志原文:

```
=== [fapi-daily-syn] 2026-10-09 18:10:00 start ===
[fapi_daily] dump=daily-k-10d dry_run=False
[fapi_daily] 下载 .../releases/20261009/a_share_daily_k_1d_none_10d_20261009.parquet
[fapi_daily] parquet rows=55563 ...
[fapi_daily] upserted 55563 rows; 库 177603 rows / 5573 codes, latest=20261009
```

- **dump=daily-k-10d(增量 10 交易日窗口)** ⇒ 符合 #238 定因报告"10-09 起 gap 变小即走增量、不再全量"的验收口径 ✓
- 对照 10-08 那次事故:走的是 `dump=daily-k`(全量,`rows=10322144`,10 年)⇒ 18:10 启动、19:23 被杀。今日本任务耗时 53s 完成,风险面完全不同

### 2.5 产物落地(第 4 条)—— 独立复核,不信日志转述

**(a) DB(独立 SQL,mode=ro 只读打开)**

```
tables= ['mootdx_daily_raw', 'baostock_daily_raw', 'fapi_daily_raw']
  fapi_daily_raw rows=177603
max_date/codes/rows: ('20261009', 5573, 177603)      # 与日志自述 177603 / 5573 / latest=20261009 逐位一致
recent dates:  20261009→5558 | 20261008→5556 | 20260930→5560 | ...
bj920 rows:    20261009→349  (北交所 920 段,与 bj_width 日志 "349 bj codes" 一致)
```

**(b) 线上数据层(CF/R2 直链,非本地推理)**

```
$ curl -s --max-time 25 -A "Mozilla/5.0" https://ssd.fx8.store/data/overview.json   → HTTP 200 / 1916262B
date = 20261009
today.metrics 里北交所 6 项全部 date=20261009 / source=fapi:
  a_bj_width_up_count=307.0 | down_count=37.0 | ad_line=-206.0 | amount=163.4388261092 | zt_count=0.0 | dt_count=0.0
```

- 内部自洽校验:`up 307 + down 37 = 344 ≤ 349`(当日 920 段总码数),数量级合理 ✓

**(c) 导出 + R2 上传(链路闭环)**

```
=== [fapi-bj-width-export] 2026-10-09 18:10:08 start (REPO=/home/ubuntu/code/trade-data) ===
  ✓ overview.json / a-stock-{3m,6m,1y,3y,5y,all}.json
共上传 7/7 -> https://ssd.fx8.store/data/
✓ Cache purge 完成: 全部 1 批成功, 共 purged 7/7 keys
=== [fapi-bj-width-export] 2026-10-09 18:10:52 done ===
=== [fapi-daily-syn] 2026-10-09 18:10:53 done ===
```

即 wrapper 三步(fapi_daily → bj_width → export/R2)**全部返回 0**、无 WARN 分支(`WARN: ... 不阻断` 字样未出现)。

### 2.6 §22 多展示位一致性(三处同值,PASS)

| 展示位 | 载体 | 北交所 up/down/ad_line/amount |
|---|---|---|
| ① 卡片当前值 | overview.json `today.metrics[id=a_bj_width_*]` | 307 / 37 / -206 / 163.4388261092(date 均 20261009) |
| ② 卡片 sparkline | overview.json `a_bj_width_*_6m` 末点 | 307 / 37 / -206 / 163.4388261092 |
| ③ range 弹窗序列 | a-stock-3m.json `metrics.a_bj_width_*.data` 末点 | 307 / 37 / -206 / 163.4388261092 |

⇒ 三处**逐位相同**(§22 用户视角一致),无"文件不一致/缓存不一致"

---

## 3. 观测缺口:为什么"峰值"读不到(诚实标注)

三条原因叠加,均为**环境能力**问题,非本次运行异常:

1. `systemctl show ... -p MemoryPeak -p MemorySwapPeak` ⇒ **属性不存在**(该机 `systemd 249 (249.11-0ubuntu3.20)`;`MemoryPeak` 是 v252+ 才有的属性)
2. `/sys/fs/cgroup/system.slice/memory.peak` ⇒ **No such file or directory**(该机内核 `5.15.0-181-generic`;cgroup v2 `memory.peak` 需 5.19+)
3. oneshot 服务退出后 cgroup 已销毁(`MemoryCurrent=[not set]`,cgroup 目录已不在)⇒ 即便支持也无从回读

**可证的边界(不是"没测"就等于"没问题",而是能证到哪一步就写到哪一步)**:

- ✅ 可证:**未触 MemoryMax=2G** —— 若触到,cgroup OOM kill 会落内核日志与 unit 日志,实测两处皆空
- ⚠️ 不可证:是否短时触到 `MemoryHigh=1.5G`(触到只会触发 reclaim/节流,不产生错误记录)⇒ **本项留白**
- 参考(不同口径,勿混用):#238 修复文档 §2 的本机探针实测 = 全量 1032 万行 dump 走流式峰值 **~298MB**(`scripts/tests/fapi_oom_mem_probe.py`,`ru_maxrss` 口径);今日云上走的是 10d(5.5 万行),量级更低但**未经云上实测**

**建议(要留云上峰值证据,三选一)**:
- ① 最省事:unit 的 `ExecStart` 前置 `/usr/bin/time -v`(任意内核可用,给出 Max RSS;注意会分别记录 wrapper 与子进程)
- ② 精准:`ExecStartPost` 里读 `.../trade-fapi-daily.service/memory.events`(5.15 支持;`max`/`high` 计数可直接回答"是否触过限")+ `memory.current`
- ③ 最贵:升级内核 ≥5.19 + systemd ≥252,才有 `memory.peak` / `MemoryPeak`

---

## 4. 归因澄清:18:10 那次的"中间态"已不可复现(不影响结论)

- 线上同批 7 文件的 **R2 对象头 Last-Modified = 10-09 19:49~19:54 CST**(11:49~11:54 GMT),即**晚于 18:10**
- 归因链(有据):19:30/19:41 有 deploy 链(`deploy_20261009_1930.log` / `deploy_20261009_1941.log`,均退出码 0),19:41 的 deploy 触发**异步 R2 上传**(`r2_upload_async_20261009_194124.log`,19:41:24 起、19:56 收尾)⇒ 同批 7 文件被**更晚版本覆盖**;本地 `static-site/data/*.json` mtime 亦已被 19:36 的导出刷成 19:36(非 18:10)
- 因此:**"18:10 当次上传成功"只能由其自身日志闭环(7/7 + purge 7/7 + 无 WARN + wrapper 退出 0)作为证据;线上现值归因于更晚那次上传**。两条都得证"当日北交所数据已上线"这一用户可见结果 ✓,但**18:10 时点的中间状态事后无法独立取证**——如实标注,不含糊

---

## 5. 附带发现(非本次验收项,交主控判断)

1. **17:50 pipeline 越界跑到 18:12:52**,与 18:10 fapi 任务重叠:`pipeline_width_20261009_1750.log` 尾部 `pipeline[width] 结束 2026-10-09 18:12:52`,`data/stock_daily.db` mtime=18:12(其 mootdx 步骤写 `mootdx_daily_raw`;fapi 的 upsert 在 18:10:0x,随后被这次写刷新 mtime)。
   - 今日后果 = 无(两进程写同一 sqlite,`timeout=10` 兜住,fapi 正常完成;结果一致)
   - 但属 §14 时点重叠,建议后续复核"17:50 任务常态时长 vs 18:10 撞点风险"
2. **同一时段两个 bj_width 各跑一次**(17:50 pipeline 一次、18:10 链一次,均 `written=60 / ad_line rows=28`):写库幂等,线上值三处一致(§2.6),今日无副作用
3. `check_data_integrity.py` **未在本任务执行**:其代码含 `subprocess.run`(signal_kelly 两件)分支,为守住"禁跑业务脚本主体"未跑;数据层改用"直读 SQL + 线上 JSON"独立校验(§2.5),口径更直接

---

## 6. 复核命令清单(可原样重跑,全部只读)

```bash
SSH='ssh -i /Users/linhuichen/tdsignal.pem -4 -o ConnectTimeout=10 ubuntu@122.51.111.173'
# ① 结果/触发
$SSH 'timeout 30 systemctl show trade-fapi-daily.service -p ActiveState -p Result -p ExecMainStatus \
  -p ExecMainStartTimestamp -p ExecMainExitTimestamp -p NRestarts -p MemoryHigh -p MemoryMax -p MemorySwapMax'
# ② 定时器
$SSH 'timeout 30 systemctl list-timers "trade-fapi*" --all --no-pager'
# ③ 日志/OOM
$SSH 'timeout 45 journalctl -u trade-fapi-daily.service --since "2026-10-09 17:30:00" --no-pager'
$SSH 'timeout 45 journalctl -k --since "2026-10-09 18:00:00" --no-pager | grep -iE "oom|killed process|thrash"'
# ④ DB 只读复核
$SSH 'timeout 45 /home/ubuntu/code/trade-data/.venv/bin/python -' <<'PY'
import sqlite3
c=sqlite3.connect("file:/home/ubuntu/code/trade-data/data/stock_daily.db?mode=ro", uri=True)
print(c.execute("select max(date), count(distinct code), count(*) from fapi_daily_raw").fetchone())
PY
# ⑤ 线上数据层
curl -s --max-time 25 -A "Mozilla/5.0" https://ssd.fx8.store/data/overview.json | python3 -c \
 "import sys,json;d=json.load(sys.stdin);print(d['date'],[ (m['id'],m['value'],m['date']) for m in d['today']['metrics'] if 'bj' in m['id']])"
```

---

*记录:tester agent | 2026-10-09 | 只读复核,未 commit/未 push(由主控落签)*

---

## 7. 尺子先验(red 先验,§5.2):先证明校验尺子能抓"坏的",PASS 才作数

自验断言若本身是坏的,一切 PASS 作废。故对本次"北交所当日值是否上线"的断言做了**坏样本实测**:

| 样本 | 构造 | 尺子输出 | 退出码 |
|---|---|---|---|
| 真样本 | 线上 overview.json 原样副本 | `RULER=PASS date=20261009 n_bj=6 vals={up:307, down:37, ad_line:-206, amount:163.4388261092, zt:0, dt:0}` | 0 |
| 坏样本 A | 删掉 `today.metrics` 中 6 项北交所项 | `RULER=FAIL missing=[6 项全列]` | 1 |
| 坏样本 B | 6 项 `date` 改成昨日 20261008 | `RULER=FAIL stale_date=[6 项全列]` | 1 |

⇒ 尺子有区分度(能抓"缺项"与"日期滞后"两类坏),真样本的 PASS 才成立。坏样本只造在 `/tmp` 副本,**未触碰生产数据产物**。
（尺子脚本为一次性临时文件 `/tmp/_bj_ruler.py`,核心逻辑与 §6 命令 ⑤ 等价,不落库不收编）

---

## 8. §0 违规闭环记录(自报即闭环)

| 项 | 内容 |
|---|---|
| 现象 | 2026-10-09 20:13:14 CST,复核探针的一条命令含冗余重定向 `> /tmp/_NO_WRITE`,在云上误写入 1 个临时文件(内容 = 18:10 段 fapi 日志副本) |
| 影响面 | 零——非业务目录、不涉 DB/R2/CF/告警/通知;云上无任何业务状态变更 |
| 处置(先确认后删) | 主控指令下的**唯一**写操作例外:①`ls -l /tmp/_NO_WRITE` + `head/tail/wc/md5sum` 确认 = 1918B / 31 行 / 自 "2026-10-09 18:10:00 start" 至 "18:10:53 done" 的日志副本(md5 `37adc90ddf061dda64f86478cc69d968`,mtime 20:13:14 与探针时刻吻合)⇒ 确认是本次误写物、非他人文件;②`rm -f /tmp/_NO_WRITE` ⇒ `RM_RC=0`,`ls` 复核 `No such file or directory`(LS_RC=2) |
| 处置时间 | 2026-10-09 20:2x CST(复核会话内,主控指令后即时执行) |
| 删后状态 | 云上 `/tmp` 已无该文件;仅删此一个路径,未触碰 `/tmp` 下其它文件;其余全程维持只读口径 |
| 防再犯 | 探针脚本里"取日志片段"用管道即可,不要用 `>` 重定向落盘;后续同类复核命令避免无意义重定向 |
