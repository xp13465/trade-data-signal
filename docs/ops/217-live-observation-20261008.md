# #217 告警降噪 §0 上线后生产观察(2026-10-08 首个交易日盘后)

> 测试 agent 只读观察,2026-10-08 22:08~22:35。云上只读:未启停/未改 unit、未跑业务脚本主体(§18 L50)、零 R2 写、零外发;未切分支/未 commit(主工作树 main,文件仅落盘)。
> 观察对象:main `64597a0af`(merge feat/217-alert-denoise-20261006),动 4 生产脚本 `scripts/{upload_r2.py,r2_upload_async.sh,fetch_news.py,overfit_monitor.py}`。
> 混淆因素(须区分):今日 deploy 因 `check_data_integrity.alert` 滞后 8 自然日**自锁**(`docs/ops/deploy-integrity-selflock-20261008.md`),与 #217 无关。

## 0. 结论摘要

| 项 | 结论 | 关键证据 |
|---|---|---|
| ① 回归(生产链正常/无新误报) | **PASS(但 ②③ 面本日零覆盖)** | 10-08 severe 14 条**无一条属 #217 改动面**;monitor 22:15 tick「OK 所有任务按计划执行，无漏跑，无退出失败」 |
| ② 等锁重试真行为 | **本日出现 SKIPPED_LOCKED 且均为「60s 窗口耗尽」,非瞬时吸收**;瞬时(<60s)被吸收场景**无日志痕迹⇒不可实证** | 4 份日志实证「已等锁重试 60s 仍未拿到」+ 时长恰 +60s;fetch_news 3 次 skip;计数 2/3 未达阈值,无 severe |
| ③ kill 尾部上下文 | **未出现场景**(本日无 kill;亦无 r2_upload_async 运行) | 10-08 无 `r2_upload_async_*.log`;`kill pid=`/`硬兜底`/`停滞` 全 0 命中 |
| ④ 是否与后续轮次撞车 | **未撞车**(实测上界 +60s 成立;相关 unit 余量充足) | 4 次等待全程 rc=0、恰 60s;fetch-news unit 1080s、rzhb 600s(vs 实跑 4s+60s);无「超时未完成」severe |
| ⑤ deploy 自锁对观察的干扰 | **① 有效、②③ 被完全遮蔽** | 自锁使 R2 异步上传链(deploy 通道)全天未运行 |

## 1. 证据来源与口径

- 云上路径:`/home/ubuntu/code/trade-data/data/logs/*`(2786 文件)、`data/alerts/latest.md`(severe 流水,50 条上限)、`data/alerts/info_log.jsonl`
- 生产代码树:`/home/ubuntu/code/trade-data-signal`(deploy 链 git pull 对象);云上脚本已含 #217 标记(`upload_r2.py` L3939 `已等锁重试 {skip_retry_secs}s 仍未拿到`;`r2_upload_async.sh` L120 `${R2_UPLOAD_STALL_SECS:-900}`、`_dump_kill_tail` 5 处)
- 云上 `.env` 实测(仅两个 R2 键):`R2_UPLOAD_HTTP_TIMEOUT=600`;**`R2_UPLOAD_STALL_SECS` / `R2_UPLOAD_SKIP_RETRY_SECS` 未设** ⇒ 生效值 = 900(>600 梯度成立)/ 60s 重试窗口

## 2. ① 回归:各日 severe 计数对照

**口径 A:canonical severe 流水**(`data/alerts/latest.md`,`## [severe]` 追加式登记,dedup 后,全通道,**上限 50 条**)

| 日期 | 条数 | 备注 |
|---|---|---|
| 09-28 / 09-29 | n/a | 已被 50 条上限滚掉(现覆盖 09-30 05:36 → 10-08 22:15) |
| 09-30(节前最后交易日) | **14(≥,头部被截)** | 静态备份失败×2 / 凯利盘中×1 / 计划任务×10 / 次日买入计划×1 |
| 10-01 | 1 | |
| 10-03 | 1 | |
| 10-04 | 12 | 长假内 |
| 10-05 | 6 | 含 R2上传失败×1 + purge×1 |
| 10-06 | 1 | R2上传失败×1(17:16,pre-merge 的 kill 案) |
| 10-07 | 2 | |
| **10-08** | **14**(22:15 终值) | 见下表分类 |

**口径 B:schedule_monitor 自身 SEVERE 发现数**(`schedule_monitor_launchd.log`,逐日可归,不受 50 条上限)

| 日期 | 09-28 | 09-29 | 09-30 | 10-01 | 10-03 | 10-04 | 10-05 | 10-07 | 10-08 |
|---|---|---|---|---|---|---|---|---|---|
| 发现数 | 11 | 13 | 12 | 1 | 1 | 15 | 4 | 2 | **5** |

⇒ 两个口径下 10-08 都**低于**节前同口径交易日(09-28~09-30),**没有因 #217 阈值/重试改动产生新误报**。

**10-08 逐条分类(14 条,无一条属 #217 面)**:

| # | 时间 | 主题 | 定性 |
|---|---|---|---|
| 1 | 02:16 | deploy 数据产物校验失败 | **自锁(干扰)** |
| 2 | 09:40 | 凯利盘中增量回测失败(退出码 5) | pre-existing(09-30 同款) |
| 3 | 09:45 | 云上 unit 巡检发现异常(1 项) | pre-existing 通道 |
| 4 | 15:30 | 计划任务异常 = `intraday_snapshot 执行耗时 928s 超阈值 900s`(15:02 轮) | pre-existing 同款(09-28 907s / 09-29 4045s / 09-30 2081s);该轮 `SKIPPED_LOCKED=0`,与 #217 无关 |
| 5 | 16:00 | 云上 unit 巡检发现异常 | pre-existing |
| 6 | 16:39 | deploy 数据产物校验失败(dedup 刷新) | **自锁(干扰)** |
| 7 | 18:30 | 计划任务异常 = 主机 swap 100% | 主机层,非 #217 |
| 8 | 19:23 | schedule-monitor 心跳超时(监控停摆) | 监控自身通道 |
| 9 | 19:36 | fund-nav R2 异步上传失败(255/256,`FAILED_FILES: 2c.json`,耗时 4089.8s) | 独立脚本 `fund_nav_upload_async.sh`(无 skip 标志,**非 #217 改动面**) |
| 10 | 19:38 | update_all 耗时超90min 统一deploy失败(1) | **自锁传导(干扰)** |
| 11 | 20:30 | 计划任务异常 = etf_national_team 退出失败 | pre-existing |
| 12 | 21:15 | 计划任务异常 = backfill_evening Traceback | pre-existing |
| 13 | 21:30 | 计划任务异常 = etf_national_team log异常关键词 | pre-existing |
| 14 | 22:15 | 云上 unit 巡检发现异常 | pre-existing |

**#217 相关通道本日零 severe**:无「R2上传失败」、无「R2 上传锁连续 3 轮跳过」、无「停滞/kill」类 severe。
**关键轮次**:17:50 update_all 已跑(其 deploy 步死于自锁=干扰);20:35 S06 快照 `S06_FRESH_OK coverage_end=20261008`;21:00/21:08/21:27/21:45 deploy 轮全部 `✗ 数据产物校验失败…终止部署`(自锁,dedup 抑制未再发新 severe);monitor 21:45/22:00/22:15 三 tick 均 OK。

**#217 相关计数器逐日对照**(R2 锁 skip 是 #217① 的唯一噪声源)

| 指标 | 09-28 | 09-29 | 09-30 | 10-06 | 10-07 | 10-08 |
|---|---|---|---|---|---|---|
| push_schedule_stats 带 skip 的轮数 / 总轮数 | 4/18 | 8/19 | 10/19 | 0/3 | 0/3 | **4/20** |
| fetch_news `SKIPPED_LOCKED` 次数 | (rolling 日志旧格式不可归日) | | | | 3 | **3** |

⇒ skip 现象在节前更密集(09-29/09-30 达 8~10 轮),10-08 处于正常偏低水平,**未新增噪声**。

## 3. ② 等锁重试真行为(实测)

**本日出现 SKIPPED_LOCKED,且实测证据显示都是「60s 窗口耗尽后的真跳过」**:

| 日志(全部 4 份 10-08) | 原文 | 起止 | 实测等待 |
|---|---|---|---|
| `push_schedule_stats_20261008_1923.log` | `SKIPPED_LOCKED: …(--skip-if-locked, 已等锁重试 60s 仍未拿到, 下轮重试)` | 19:23:44 → 19:24:44 | **+60s** |
| `push_schedule_stats_20261008_1928.log` | 同上 | 19:28:14 → 19:29:14 | **+60s** |
| `push_schedule_stats_20261008_2109.log` | 同上 | 21:09:11 → 21:10:11 | **+60s** |
| `push_schedule_stats_20261008_2141.log` | 同上 | 21:41:48 → 21:42:48 | **+60s** |

- 消息文本里的 `60s` = 生效重试窗口(`R2_UPLOAD_SKIP_RETRY_SECS` 未设 ⇒ 默认 60);`已等锁重试…仍未拿到` = **窗口被真实用满**,即撞锁时长 >60s。
- `fetch_news`:10-08 共 44 轮,`R2 同步 OK` 41 次 / `SKIPPED_LOCKED` 3 次(轮起点 19:23:40、20:01:00、21:01:00)。
- **阈值判别保持**:monitor 逐轮打印 `[r2-skip] fetch_news R2 锁skip 连续2/3 轮(未达阈值, 不告警)`、`[r2-skip] overfit_monitor R2 锁skip 连续1/3 轮(未达阈值, 不告警)`,随后 `[r2-skip] fetch_news R2 锁连续skip清零(本轮无skip)` ⇒ **3 轮阈值未放松、也未触发误报**。
- **撞锁成因(独立于 #217)**:同锁 `/tmp/trade_r2_upload.lock`(upload_r2.py L3981 `__main__` 入口统一持锁)被长时上传进程长久持有 —— `fund_nav_upload_async` 18:28:38→19:36(4089.8s,255/256)覆盖 19:23/19:28 两次 skip;**交叉验证**:fund-nav 释放后 19:37:24 那次 push 立即上传成功(`✓ schedule_stats.json R2 上传完成`,无等待)。
- **持锁方定位(诚实标注)**:19:23/19:28 两次已由 fund-nav(18:28:38→19:36)取证闭合;21:09/21:41 两次与 fetch_news 三次的持锁方**未直接取证**,候选为该时段长跑任务(`backfill_metrics.sh` 21:00 起、>`21:30` 仍在跑,`pipeline[turnover]` 21:10:02→22:01:21)——不影响「窗口耗尽 = 非瞬时撞锁」的判定。
- **未实证项(诚实标注)**:「瞬时撞锁(<60s)被重试吸收、重试后成功上传」这一**收益方向无日志痕迹**(设计上吸收=静默不打印),无法事后从生产日志证实或证伪;本日能确认的是**未因重试产生漏报或新误报**。

## 4. ③ kill 尾部上下文:未出现场景

- 10-08 `data/logs/` **无任何 `r2_upload_async_*.log`**(最新 `r2_upload_async_20261007_211623.log`);`r2_upload_async_skip.log` mtime 停在 10-05 → 该脚本全天未运行。
- 10-08 全部 `*20261008*.log` 中:`kill pid=` 0 命中、`总时长超 7200s 硬兜底` 0 命中、`停滞` 0 命中 ⇒ **无 kill 事件,无从核验尾部 30 行正文**(标:未出现场景,不推断)。
- 代码在位核验(静态):云上 `scripts/r2_upload_async.sh` `_dump_kill_tail` 5 处(1 注释 + 1 定义 + 3 调用 L142/L152/L174),`R2_KILL_CTX` 只进唯一 severe 口。
- **扫描尺子先验(§5.2)**:同一 `kill pid=` / `停滞` 模式在已知 kill 样本 `r2_upload_async_20261006_165223.log` 上各命中 1 次 ⇒ 10-08 的「0 命中」有效,非尺子失效。
- 参考基线:历史 kill 集中在 10-05(14 次)/10-06(1 次,verify-r2 真卡死),最后一次 kill = **10-06 16:52**(在 #217 merge 之前)⇒ ③ 改动**尚无生产 kill 样本**。

## 5. ④ 是否与后续轮次撞车:未撞车

- **实测上界 +60s 成立**(4 次等待均恰 60s,脚本 rc=0,不静默不阻塞:`push_schedule_stats` 被各 backfill 以 `|| echo` 容错 + `trap refresh_stats EXIT` 调用)。
- 相关 unit 超时余量(云上 `/etc/systemd/system/*.service` 实测):`trade-fetch-news=1080s`(评审时记 600,现更大;10-08 每轮按时启动无漏跑)、`trade-rzhb-backfill=600s`(实跑 ~4s + 60s)、`trade-schedule-monitor=600s`(不涉)、`overfit-monitor / intraday-snapshot / backfill-* = 0(不设超时)`。
- 10-08 无「超时未完成 / 进程退化」类 severe;monitor 22:15「OK 所有任务按计划执行，无漏跑，无退出失败」。
- 与评审报告 §14 节结论一致(时点安全);本次实测把「+60s 上界」从推演升级为**生产实测**(4 次恰 60s)。

## 6. ⑤ deploy 自锁的干扰程度(必须分开记账)

| 面 | 干扰程度 | 说明 |
|---|---|---|
| #217① (等锁重试) | **无干扰,观察到实证** | fetch_news / overfit_monitor / push_schedule_stats 三条调用链不依赖 deploy,10-08 照常运行(≥41 次成功上传 + 7 次 skip 实证) |
| #217② (900s 停滞阈值+防倒置守卫) | **完全遮蔽,零覆盖** | ② 作用于 `r2_upload_async.sh` 通道,该脚本 10-08 全天未运行(被自锁挡在 deploy L582 之后)⇒ 本日无 kill/无 stall,无法观察 |
| #217③ (kill 尾部) | **完全遮蔽,零覆盖** | 同 ②;kills 必发生在该通道内 |
| 当日 severe 计数 | **部分推高** | 14 条里 3 条(02:16、16:39、19:38)由自锁及其传导产生,记账归自锁,不归 #217 |

## 7. 未测项(不得当作结论)

1. ② 900s 阈值 / 防倒置守卫的生产行为(10-08 该通道未运行;最后一次运行 10-07 21:16 亦无 kill)⇒ 需等 deploy 自锁解除后的首个正常运行日。
2. ③ kill 告警正文是否真带 30 行尾部(无 kill 样本)⇒ 同上。
3. ①「瞬时撞锁被吸收」的正向收益(无痕迹设计)⇒ 生产日志不可实证,如需闭环须加轻量埋点(本次只读不改)。
4. 非 skip 排队调用方与 skip 等待叠加的极端情形(本次未观测到)。

## 8. 复现命令(全部只读)

```bash
KEY=/Users/linhuichen/tdsignal.pem; H=ubuntu@122.51.111.173
SSH="ssh -4 -i $KEY -o ConnectTimeout=15 -o BatchMode=yes"
# ① severe 流水逐日
$SSH $H "timeout 60 grep '^## \[severe\]' /home/ubuntu/code/trade-data/data/alerts/latest.md"
# ② 等锁重试实证(含窗口秒数)
$SSH $H "timeout 60 grep -n '已等锁重试' /home/ubuntu/code/trade-data/data/logs/push_schedule_stats_20261008_1923.log"
# ② 计数判别保持
$SSH $H "timeout 60 grep 'r2-skip' /home/ubuntu/code/trade-data/data/logs/schedule_monitor_launchd.log | tail -8"
# ③ kill 扫描(限定 10-08 日志文件)
$SSH $H "timeout 60 bash -c 'cd /home/ubuntu/code/trade-data/data/logs; grep -l \"kill pid=\" *20261008*.log | head'"
# ④ 相关 unit 超时
$SSH $H "timeout 60 grep -H TimeoutStartSec /etc/systemd/system/trade-{fetch-news,rzhb-backfill,overfit-monitor}.service"
# 云上生效参数(仅两键)
$SSH $H "timeout 60 grep -E '^R2_UPLOAD_(STALL_SECS|HTTP_TIMEOUT|SKIP_RETRY_SECS)=' /home/ubuntu/code/trade-data/.env"
```
