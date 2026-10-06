# #223 (1)(2)(3)「内层超时」生产触发取证(只读取证)

- 执行:2026-10-06(researcher,只读;云上仅 ls/head/tail/grep/sed -n/journalctl/find 类读命令,未执行任何业务脚本、未 start/stop/restart/daemon-reload 任何 unit、无任何真实外发、无 R2 写)
- 交付对象:#223 拍板(内层 120/300/300 vs 外层 systemd 600 的处置)
- 前提(引用主控已确认项,未重测):三处外层 systemd TimeoutStartSec 实测均 600;云上 .env `R2_UPLOAD_HTTP_TIMEOUT=600`;唯一禁止动作 = 内层抬过 600

## 0. 结论速览(三问三答)

| # | 位置 | 内层值 | 生产触发次数 | 关键证据 | 本次结论 |
|---|---|---|---|---|---|
| (1) | `scripts/gen_daily_brief.py:3119`(upload_to_r2 的 subprocess timeout) | 120 | **1 次**(2026-09-28) | daily_brief.log:189 `✗ R2_UPLOAD_TIMEOUT`;schedule_monitor_launchd.log:9978 SEVERE(20:45) | **(a) 不动 120** |
| (2) | `scripts/nextday_plan_generator.py:1181`(subprocess timeout) | 300 | **1 次**(2026-09-30) | nextday_plan_launchd.log:1642 `⚠ R2 上传超时(300s, 将告警)`;链 318s、退出码=1 | **(b) 抬至 480** |
| (3) | `scripts/nextday_gap_check.py:358`(_sync_r2_and_notify 内 timeout) | 300 | **0 次** | 触发串 `timed out after 300` 全日志 0 命中;窗口内唯一一次 R2 上传 rc=0 | **(a) 不动 300**(附 (c) 触发条件) |

(4) R2 单次上传耗时:**无此日志,不可推断**(三链走 `upload-data-files` 通道,该通道无耗时打印;可得间接上界见 §5)。

## 1. 通道与覆盖窗口(如实标注)

| 通道 | 云上路径 | 最早可追溯 | 最新 | 保留机制 | 说明 |
|---|---|---|---|---|---|
| daily_brief.log | data/logs/daily_brief.log | 2026-09-13 20:40(首行) | 2026-10-06 20:40 | 追加、无轮转 | 09-13 之前无留存;17842B |
| nextday_plan_launchd.log | data/logs/nextday_plan_launchd.log | 2026-09-15 09:52 | 2026-10-06 22:30 | 追加、无轮转 | 09-15 之前无留存;146364B |
| nextday_gap_check_launchd.log | data/logs/nextday_gap_check_launchd.log | 2026-09-18 09:26 | 2026-10-06 09:26 | 追加、无轮转 | 09-18 之前无留存;15031B |
| journal | journalctl -u trade-* | daily-brief / nextday-plan = 10-02;gap-check = 10-05 | 10-06 | journald SystemMaxUse=200M(当前 224M) | **09 月窗口已被轮转,09 月无 journal 可查** |
| schedule_monitor | data/logs/schedule_monitor_launchd.log | 2026-09-13 14:15(常规行) | 10-06 | 追加 | 15min 巡检台账;其首行为一条无时间戳的旧 warn 行 |
| alerts/latest.md | data/alerts/latest.md | 滚动 | — | **保留流水 50 条**(滚动) | 不当历史台账用 |

- 云上 /etc/logrotate.d 无 trade 项(无 logrotate);非交易日(周末 / 中秋 09-25 / 国庆 10-01~10-06)三链全跳过(日志可见「非交易日,跳过」),超时在这些日子不可能触发,不计样本。
- 三链探活:`ls -la` mtime 分别 10-06 20:40 / 10-06 22:30 / 10-06 09:26(当日报活,窗口新鲜)。

## 2. (1) gen_daily_brief.py:3119 timeout=120

### 2.1 触发计数 = 1 次

```
$ grep -n "R2_UPLOAD_TIMEOUT\|R2 上传超\|上传超 120" data/logs/daily_brief.log
189:✗ R2_UPLOAD_TIMEOUT: daily_brief R2 上传超 120s 未完成, 上传文件可能缺口(缺口由 17:50 deploy upload-all-data 或次日任务兜底), 请核对 R2 是否缺
```

- 该行上一条是 09-28 运行的通知行(`[notify][dedup] ... daily_brief_notify_20260928`),本行之后紧接下一次运行(09-29 20:40 开始生成)⇒ 触发时刻 = 2026-09-28 20:4x。
- 独立通道:**schedule_monitor** 同日亦捕获(行 9978):`SEVERE: gen_daily_brief log异常关键词<R2_UPLOAD_TIMEOUT> exit=None ... last_run=2026-09-28 20:42 ...`;此后逐轮 `[suppress] ... 异常持续中, last_alerted=2026-09-28 20:45:00`(行 9986→10757),2026-09-29 20:45 记 `[recovery] ... 已消失`(行 10779)。
- degrade 兜底分支(`⚠ R2 上传超 120s 但 R2 已有较新版 ...(兜底已生效)`)全日志 **0 命中**(grep -c=0)⇒ 唯一这次触发走的是 ✗ 真缺口分支(未查得 R2 已有新版)。

### 2.2 该链运行分布(窗口内 12 个交易日 20:40 全量)

- 有结束行(`[run_daily_brief] ✓ 完成`)= **4 次**:09-15 / 09-21 / 09-23 / 09-24。整链(开始生成 → ledger 开始)≈ **25~47s**;写入 run.log 的 python 段 17~37s(run.log 条目时间戳 20:40:17 / 20:40:28 / 20:40:20 / 20:40:37)。
- 无任何结束行(既无 ✓ 也无 ✗)= **8 次**:09-14 / 09-16 / 09-17 / 09-18 / 09-22 / 09-28 / 09-29 / 09-30。
  - 直证 ×2:09-14 的 run.log 条目写入于 20:50:09(启动 20:40:01 + **608s 仍存活**;且该条目 `"staticdata": 600.04` = 一次 staticdata_sync 打满其 600s timeout);09-28 存活至 ≥~120s(✗ 行为其能打印的“活体”证据)。
  - 推断 ×6(其余):同签名(无 ✓ 无 ✗ + 次日正常)= 被 systemd 超时 SIGKILL。09-14 当日外层仍为 900(收口 600 于 2026-09-16,见 docs/deploy/systemd-units-20260912.md 史),故 608s 存活不矛盾。
- **重点回答**:有——8/12 次直接把外层跑穿(≥600s),而正常日仅 25~50s。触发 120 的那次(09-28)其链路本身也在被杀名单里。
- 监控盲区(次生发现):8 次被杀在 schedule_monitor 的 20:40-21:00 窗口被判「OK 所有任务按计划执行,无漏跑,无退出失败」(原文见 §6.1);线上 schedule_stats.json 对该任务字段为 `last_exit=null, last_duration_sec=null, est_text="-"`(结构性无此数据,佐证盲区)。唯一被抓的 09-28 属“日志异常关键词”类检查命中。

### 2.3 结论:(a) 不动 120

为什么“不动”:
1. 观测正常上界 **26.61s**(run.log `timings.r2` 5 样本:4.0 / 4.19 / 6.13 / 10.58 / 26.61),120 = **4.5x 余量**;
2. **触发带缺口**:正常带 ≤27s 与坏夜事件(同基础设施、同通道,09-30 已直证某次上传 >300s)之间**无中间样本** ⇒ 抬到任何 <600 的 X 都**没有可覆盖的观测样本**,给不出“X 够”的证明;
3. 该链结构上最多容得下 X≈270(2 次上传 + 2 次 staticdata 共用一个 600 外层预算),可抬幅度小且不解决坏夜;
4. 8 次被杀的处置权不在 120:09-14 直证停滞发生在 staticdata 段(600.04s),与上传 120 无关;09-28 的 ✗ 之后链路照样被外层杀。**改 120 不改变任何一次结局**。
- 配套:该链真正的问题(2×upload + 2×sync 塞进一个 600 外层预算)已由主控登记 #227,建议随 #227 一并评估,不在此处单独动 120。

## 3. (2) nextday_plan_generator.py:1181 timeout=300

### 3.1 触发计数 = 1 次(2026-09-30)

```
$ grep -n "R2 上传超时" data/logs/nextday_plan_launchd.log
1642:[nextday_plan] ⚠ R2 上传超时(300s, 将告警)
```

上下文原文(行 1639-1655 摘):

```
[nextday_plan] R2: .../upload_r2.py upload-data-files nextday_plan.json auto_trade_steps.json signal_kelly_day_snapshot.json
[nextday_plan] ⚠ R2 上传超时(300s, 将告警)
[nextday_plan] severe 告警 rc=0
[nextday_plan] notify: 明日买入计划 20260930
[nextday_plan] notify 退出码=0
[nextday_plan] 落盘完成: ...
✗ 次日买入计划生成失败 rc=1
[notify] 邮件已发送至 ... ：[告警] [cloud] 次日买入计划生成失败 09-30 22:35
[notify][severe-mirror] 已镜像登记 .../data/alerts/latest.md
=== nextday_plan.sh 结束 2026-09-30 22:35:19 退出码=1 ===
```

- 链级证据:开始 22:30:01 → 结束 22:35:19 = **318s**(= 300s 超时 + 18s 告警/通知收尾);线上 schedule_stats.json 独立记录 `last_exit=1, last_duration_sec=318`(2026-09-30 22:30)。
- 同夜旁证:R2 处于故障窗——schedule_monitor 23:00 报 `[SEVERE] R2 直连不可达 ssd.fx8.store/data/overview.json error<curl rc=28>`(alerts/latest.md 行 215)。

### 3.2 该链运行分布(14 次)

| 场次 | 时长 | 退出码 | 场次 | 时长 | 退出码 |
|---|---|---|---|---|---|
| 09-15 09:52(演练 dry_run) | 2s | 0 | 09-23 21:24(手动) | 17s | 0 |
| 09-15 20:55 | 9s | 0 | 09-23 22:30 | 15s | 0 |
| 09-16 20:55 | 12s | 0 | 09-24 22:30 | 10s | 0 |
| 09-17 10:15(手动) | 8s | 0 | 09-28 22:30 | 13s | 0 |
| 09-17 22:30 | 13s | 0 | 09-29 22:30 | 11s | 0 |
| 09-18 22:30 | 13s | 0 | **09-30 22:30** | **318s** | **1** |
| 09-21 22:30 | 9s | 0 | | | |
| 09-22 22:30 | 12s | 0 | | | |

- 12 次带 R2 上传的场次全部 `R2 退出码=0`(行 165/257/344/440/539/638/741/1024/1122/1230/1348/1490);整链上界 17s(含上传)⇒ 常规上传+全链 ≤17s,离 600 很远;唯一异常日 = 09-30。

### 3.3 结论:(b) 抬至 480(<600,不动 systemd)

“为什么 480 够”算法(全部用实测数):
- 非上传段 + 超时后处理上界:上传前工作 ≤10s(全链 ≤17s,无慢步);超时后处理实测 = 18s(22:35:01→22:35:19);合计 ≤28s。
- 约束:480 + 28 = **508 < 600**(余量 92s ≈15%);同时 480 > 观测触发的下界 300s(给 09-30 那类事件再多 60% 忍耐),覆盖 300-480s 慢传带。
- 收益/代价:把“单次上传 ≤480s”的坏夜从 rc=1 救回为 rc=0(可用);失败夜语义不变(仍先于外层触发,severe 照发,只晚 3 分钟)。
- **诚实标注**:480 不能保证覆盖 R2 真故障(09-30 当夜 23:00 仍不可达;若该次上传本需 >480s,结局不变)——它是把慢传带纳入忍耐,不是消灭失败。
- 为什么不一并走 (c):(c) 需动云上 systemd;(2) 单上传、余量大,(c) 的增量(让 HTTP 层 600 完整生效)无观测证据支撑。若拍板要“内外层完全对齐 HTTP=600”,(2) 的 (c) 算式 = 外层 900 + 内层 600(600+28=628 < 900)。

## 4. (3) nextday_gap_check.py:358 timeout=300

### 4.1 触发计数 = 0 次

- 该处无专门 except 分支,TimeoutExpired 被 L363 `except Exception` 捕获,打到日志的串是 subprocess 异常文本 `timed out after 300 seconds`。

```
$ grep -c "timed out after 300\|R2 上传异常" data/logs/nextday_gap_check_launchd.log
0
```

- 该链窗口内唯一一次 R2 上传(09-23 15:30 场):`R2 退出码=0` + `共上传 1/1 ->` + `Cache purge ... purged=1`,整链 9s。

### 4.2 该链运行分布(10 次)

| 场次 | 时长 | 退出码 | 说明 |
|---|---|---|---|
| 09-18 09:26 | 19s | 0 | 首次拉起 |
| 09-21 09:26 | 338s | 0 | 开盘价拉取失败 → `等 300s 重试(9:26→9:31)` → 第 2 次成功 |
| 09-22 09:26 | 327s | 0 | 同上 |
| 09-23 09:26 | 339s | 2 | 重试后仍失败(开盘价就绪闸 FAIL) |
| 09-23 14:31(手动) | 344s | 2 | 同上,手动重跑 |
| 09-23 15:30(手动) | 9s | 2 | 同上;带 R2 上传 rc=0 |
| 09-24 09:26 | 0s | 0 | 无计划/快速返回 |
| 09-28 09:26 | 0s | 0 | |
| 09-29 09:26 | 340s | 0 | 重试成功 |
| 09-30 09:26 | 6s | 0 | |

- **重点**:出现过 327-344s(占 600 的 55-57%),其中 300s 是等待重试的 sleep、非工作;离 600 尚有 256s。rc=2 的三次(09-23)全部是「开盘价就绪闸 FAIL」(akshare `ConnectionError: RemoteDisconnected` 两次失败),**与 R2 300s 毫无关系**——同窗口日志无任何 R2 异常。

### 4.3 结论:(a) 不动 300

- 触发 0 次;唯一上传 rc=0;327-344s 档由重试 sleep 主导且与内层无关。
- 结构事实(供拍板):在重试路径上,预算 = 300(sleep)+ 实测收尾 ≈39s + 内层 X。X=300 时合计 ≈639s > 600 ⇒ **重试路径下内层 300 永不先触发,外层先杀**(该组合窗口内 0 次出现)。若要让内层在该路径也可先触发,只能 (b) 下修到 ≤240(与“抬”相反,且牺牲慢传忍耐)或 (c) 外层同抬(如 900:340+300=640 < 900)。
- 本报告结论:**现无观测数据支持为 (3) 改动**(触发 0、风险组合未出现);建议随 #227 一并处置该结构问题;若拍板做 (c),(3) 的算式按 900 外层重算。

## 5. (4) R2 单次上传耗时:无此日志,不可推断

- 代码:`upload-data-files`(三链共用)走 `_upload_glob`(scripts/upload_r2.py:985-1001),仅打印逐文件 `[N/M] ✓ name (sizeB)` 与 `共上传 N/N ->`,**无耗时**;带 `耗时 {elapsed:.1f}s` 的打印在 `_incremental_upload`(L1468),属 deploy 通道,三链不走。
- 日志:三链日志 grep `耗时` / `上传完成` 命中 **0**。
- 可得间接上界(标注为间接,非单次上传独立耗时):
  - (1) run.log `timings.r2`(其后紧跟 staticdata,计量点 gen_daily_brief.py:4389-4395)= 4.0 / 4.19 / 6.13 / 10.58 / 26.61s(5 样本,09-14~09-24);
  - (2) 12 次整链 ≤17s(含上传);
  - (3) 唯一一次整链 9s(含上传);
  - 09-30 直证某次上传 >300s。
- 结论:**单次上传耗时的独立分布无日志可测,不可推断**(勿在别处引用其“平均/分位”类数字)。

## 6. 次生发现(超 #223 三处范围,上报不越权)

1. (1) 链 8 次被 systemd 超时杀(§2.2),且 monitor 未逐日发现——建议另案(#227)。
2. staticdata_sync 侧无常规日志留存:全云树 `find ... -name "staticdata_sync*"` **0 份**(脚本仅在走 notify 分支时 `tee -a $LOG`,staticdata_sync.sh:69 / 153-158)⇒ 其停滞原因(锁等待 or 同步自身慢)**不可判定**。
3. 被杀运行中 (1) 自身 stdout 因块缓冲随 SIGKILL 丢失(09-28 ✗ 之后的 upload#2/sync 结果不可知);取证者注意此特性。

### 6.1 monitor 原文样例(杀日 20:45 窗口)

```
[2026-09-16 20:45:00] OK 所有任务按计划执行，无漏跑，无退出失败
[2026-09-22 20:45:00] 检测到 2 个告警: ...
[2026-09-29 20:45:00] OK 所有任务按计划执行，无漏跑，无退出失败
[2026-09-30 20:45:00] OK 所有任务按计划执行，无漏跑，无退出失败
```

## 7. 诚实标注(查不到的 / 窗口不足的 / 无日志可推的)

1. 09-13 之前((1))、09-15 之前((2))、09-18 之前((3))的触发历史:日志窗口外,**不可知**(!= 没发生)。
2. 09 月 journal 已被轮转(SystemMaxUse=200M),7 次被杀的 kill 时点无 systemd 侧逐日证据;“systemd 超时杀”= 高置信推断(签名 + 09-14/09-28 两次直证)。
3. 09-14 `staticdata=600.04s` 的停滞原因(锁等待 vs 同步自身)、其余各次被杀的卡点:现场无 sync 日志,**不可判定**(“锁等待”为候选假设,有 staticdata_backup_async.sh 注释「持锁小时级→队列占死 #149」同类先例,但未见当事日直接证据)。
4. R2 单次上传耗时:无日志,不可推断(§5)。
5. 09-28 ✗ 之后的后续步骤结果不可知(缓冲输出丢失)。
6. “8 次被杀”中 09-14 处于外层 900 时期(09-16 起为 600),口径差异已标注。
7. schedule_stats.json(线上)对 gen_daily_brief 无 exit/duration 字段(结构上不承载),勿当该链台账用。

## 8. 取证命令清单(只读,节选)

- `ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cd ~/code/trade-data && grep -n "R2_UPLOAD_TIMEOUT\|R2 上传超" data/logs/daily_brief.log'`
- `... grep -n "R2 上传超时" data/logs/nextday_plan_launchd.log`
- `... grep -c "timed out after 300\|R2 上传异常" data/logs/nextday_gap_check_launchd.log`
- `... grep -n "开始生成\|✓ 完成\|✗ 失败\|非交易日" data/logs/daily_brief.log`
- `... grep -n "开始\|结束" data/logs/nextday_plan_launchd.log` / 同 nextday_gap_check_launchd.log
- `... cat data/logs/daily_brief_run.log`(timings 样本)
- `... grep -n "gen_daily_brief" data/logs/schedule_monitor_launchd.log | grep -v suppress`
- `... journalctl -u trade-daily-brief --no-pager -o short-iso | head -1`(同 nextday 两 unit)
- `... sed -n "175,199p" data/logs/daily_brief.log` 等上下文窗口若干
- `curl -s https://ssd.fx8.store/data/schedule_stats.json -o /tmp/sched_stats_cloud.json`(线上台账,只读)
- 本地只读核对:scripts/gen_daily_brief.py:3099-3144/4375-4414、nextday_gap_check.py:160-240/336-380、nextday_plan_generator.py:1177-1210、run_daily_brief.sh 全文、staticdata_sync.sh:40-70、upload_r2.py:985-1001/1468

---

取证与落档:researcher agent,2026-10-06。只读取证,未改任何代码;结论均附原始出处,未能证实的均已在 §7 逐条标注。
