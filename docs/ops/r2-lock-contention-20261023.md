# R2 全局上传锁竞争调研(2026-10-23,只读)

> **日期**:2026-10-23(调研发起 2026-10-22 22:38 云上 `trade-nextday-plan` 失败 exit 1 之后)
> **范围**:云上 `/home/ubuntu/code/trade-data` 只读核查 —— nextday-plan / r2_consistency / fetch_news / daily brief / etf-hist / turnover(data-large)/ update_all / r2_upload_async 八个任务 2026-10-20～10-22 的运行日志与告警台账;以及与 2026-09-30 gold-night 同一锁历史事故的对照。
> **方法**:日志逐行读(grep + 按行号定位)、按任务配对起止时间算耗时、按 key 比对等锁时长;不做任何写操作、不跑任何业务脚本、不改云上任何文件(与 §18 L50 / memory `probe-harness-must-not-exec-prod-scripts` 一致)。
> **数据源(云上,权威)**:
> - 任务日志 `/home/ubuntu/code/trade-data/data/logs/*.log`(nextday_plan_launchd / turnover_backfill_launchd / r2_upload_async_* / etf_national_team_backfill_* / gold_night_20260930_0240 / schedule_monitor_launchd)
> - 告警台账 `data/alerts/alert_ledger.jsonl`
> - 代码 `scripts/upload_r2.py` / `scripts/nextday_plan_generator.py`(origin/main 现行版本,行号即本报告引用行号)
>
> **一句话结论**:不是偶发。主因 = **R2 全局上传锁 `/tmp/trade_r2_upload.lock` 被 data-large 长任务长期占用**(单次持锁 25–43 分钟),`nextday-plan` 的 480s 内层窗口在当前节奏下必输;10-21 只是碰巧没撞锁。三个候选方向见 §6(**仅列出,未实施**)。

---

## 1. 失败链(2026-10-22)

时间线(全程 **492s**,小于 systemd `TimeoutStartSec=600s`,**没有重试**):

| 时刻 | 事件 |
|---|---|
| 22:30:01 | `trade-nextday-plan` 启动 |
| 22:30:08 | 调 `upload_r2.py upload-data-files` 传 2 个小 JSON |
| 22:38:08 | 内层 **480s** 超时 |
| 22:38:08 | severe 告警已发 |
| 22:38:13 | 退出码 **1** |

证据(云上路径):

- `/home/ubuntu/code/trade-data/data/logs/nextday_plan_launchd.log:3500`(开始)、`:3680`(R2 命令)、`:3681`(480s 超时)、`:3682`(severe 已发)、`:3686`(rc=1)、`:3688`(结束)
- `scripts/nextday_plan_generator.py:1199`(`timeout=480`)、`:1213`、`:1216`

**注**:该处用 `capture_output=True` 调子进程,把 upload_r2.py 的**等锁心跳输出吞掉了** ⇒ nextday 自己的日志看不到「正在等锁」,只能从子进程 480s 无返回反推。

## 2. 近三天同类失败(2026-10-20 ～ 2026-10-22)

| 任务 | 10-20 | 10-21 | 10-22 |
|---|---|---|---|
| nextday-plan | **480s 超时 exit 1** | 成功(3/3 + purge,22:30:11 exit 0) | **480s 超时 exit 1** |
| r2_consistency | 5 文件不一致,23:24:06 exit 1 | 2 文件不一致,23:24:15 exit 1(可能是 local mirror 差异) | PASS,23:22:37 exit 0 |
| r2_consistency 耗时 | 246s | 255s | 157s |

其他同窗口证据:

- **fetch_news** 10-22 22:30 因 R2 锁**连续 skip**,升级为 critical
- **daily brief** 三天都有 120s 超时,但业务数据未丢(r2 = 121.89 / 123.55 / 123.67 / 8.15)
- **etf-hist** 首次等锁 30s → 到 **3990s** 才拿到(22:44:23 deploy 开始)
- **turnover data-large 持锁**:10-20 **2574.8s** / 10-21 **1420.8s** / 10-22 **1501.9s**
- **update_all 等锁**:10-20 **1380s** / 10-21 **1200s** / 10-22 **930s**
- **async 单例** 10-22 共 **11 次**跳过

## 3. 吞吐趋势(关键证据)

**data-large 成功耗时在恶化**:

| 日期 | 耗时 |
|---|---|
| 2026-10-08 | 472.2s |
| 2026-10-09 | 473.8s |
| 2026-10-19 | 1181.4s |
| 2026-10-20 | 2574.8s |
| 2026-10-21 | 1420.8s |
| 2026-10-22 | 1501.9s |

⇒ 相对 10-08/10-09 的基线,**慢 2.5–5.4 倍**。

**小文件 index 通道三天中位吞吐稳定**(不是全链路变慢):

- 全天中位:175,729 / 197,072 / 194,504 B/s
- 20:35 段:191,829 / 208,898 / 199,123 B/s

**等锁最长**:etf-hist **3990s**、async **1860s / 1530s**。

**下载侧无超时证据**。

证据行号:

- turnover 日志 `:3546`(10-08)、`:3937`(10-09)、`:6111`(10-19)、`:6493`(10-20)、`:6864`(10-21)、`:7244`(10-22)
- 等锁:`r2_upload_async_20261022_213215.log:55`(1530s)、`r2_upload_async_20261022_183253.log:63`(1860s)、`etf_national_team_backfill_20261022_2130.log:190`(3990s)

## 4. 与 2026-09-30 gold-night 的同一性

- **同一把锁**:`/tmp/trade_r2_upload.lock`
- 09-30 gold-night:等满 **7300s** 后 **fail-closed**(全程总 **10615s**)
- 今晚 nextday:**480s 内层超时**提前失败(外层 systemd 600s 都没到)
- etf-hist **3990s 能等到** ⇒ **不是死锁**,锁最终会释放,**无 stale lock 证据**

证据:

- `scripts/upload_r2.py:4213`(锁路径)、`:4163`(acquire)、`:4181`(默认 7300s)、`:4257`(fail-closed)
- `gold_night_20260930_0240.log:16`(7300s 超时)、`:27`(05:36:56 结束,总 10615s)

## 5. 告警侧

**首报没被吞**(这点是好的,问题不在通知丢失):

- 22:38:08 critical `nextday_plan_fail` 邮件 + 飞书**已发**
- 22:38:13 计划通知已发
- wrapper 重复告警 5s 后被 **dedup**
- `schedule_monitor` 每 15 分钟报 SEVERE,但**并入 `r2_deploy` 域摘要**

**文案问题**:告警写「**R2 上传超时**」,实际是「**等锁超时**」,容易误诊成网络/服务端慢。

证据:

- `data/alerts/alert_ledger.jsonl:602`、`:603`、`:600`、`:606-607`、`:608`
- `nextday_plan_launchd.log:3682`、`:3687`
- `schedule_monitor_launchd.log:33093 / 33111 / 33129 / 33146 / 33134-33137`

**长期抑制项**(与本次无关,但同台账可见,登记备查):overfit **673.8h**、fetch_news **683.5h**、gen_daily_brief R2_UPLOAD_TIMEOUT **47.5h**、nextday_gap_check **230h**。

## 6. 结论 + 三个候选方向(不实施)

### 6.1 结论

**系统性,不是偶发。** 主因 = R2 全局上传锁被 data-large 长期占用(单次持锁 **25–43 分钟**),nextday 的 **480s** 窗口在当前节奏下**必输**;10-21 只是碰巧没撞锁。

**放大因素**:

- pre-upload 备份是**客户端 GET + PUT 中转**(`upload_r2.py:1147-1295`),10-19 起每天备份 **18–21 个 key**,都在锁内 ⇒ 持锁时间被拉长
- 大文件路径 10-22 出现 `SSLEOFError` / `HTTP 500`(`turnover_backfill_launchd.log:7163-7164`)
- 磁盘 **88%** 预警**不是主因**
- Cloudflare 官方事件(10-22 03:02–03:05,ENAM R2/DO 3 分钟)**不在**失败窗口内

### 6.2 三个候选方向(仅列出,未实施,待拍板)

1. **nextday 走独立小通道**:两个小 JSON 走独立小通道 / 跳过全局锁;或改「本地落盘成功即返回、异步补传」
2. **缩短 data-large 持锁时间**:pre-upload 备份移出锁外 / 减量 / 拆分 89MB 大文件;或把 nextday 挪出占锁窗口
3. **超时可见性**:超时分支打印子进程 stderr(等锁心跳)+ `lsof` 记录持锁者,区分「等锁」与「上传慢」

## 7. 诚实标注

1. nextday 的等锁心跳被 `capture_output=True` 吞掉,**锁归因是「同期持锁者反推 + 10-21 自然实验」**,不是 nextday 日志直接可见。
2. **R2 服务端 vs 云上出口网络未最终分离**;Cloudflare 官方事件不能解释 20:40–23:45 的持续慢。
3. daily brief 的 120s 超时是**主文件 / run_log 两类**,业务数据未丢。
4. 10-16 的 **871.7s** 是 `0/24` **失败**,不是「慢成功」,**已排除出基线**。
5. 10-22 nextday 数据最终 **23:12:32** 上线(比生成晚 **42 分钟**),数据没丢但用户可见延迟。

## 8. 复现命令

以下均在云上执行(`ssh -o ConnectTimeout=10 -i ~/tdsignal.pem ubuntu@122.51.111.173`),**全程只读**。

```bash
cd /home/ubuntu/code/trade-data

# §1 nextday 失败链(22:30 起那一段)
sed -n '3495,3690p' data/logs/nextday_plan_launchd.log | grep -nE '22:3|480|severe|rc='

# §1 内层超时值
grep -n "timeout=480" scripts/nextday_plan_generator.py

# §2 r2_consistency 三天的退出码与耗时
grep -nE '2026-10-2[012]' data/logs/r2_consistency_launchd.log | grep -E 'exit|rc|PASS|不一致' | tail -30

# §3 data-large 成功耗时(取 §3 所列行号前后各 1 行)
sed -n '3546p;3937p;6111p;6493p;6864p;7244p' data/logs/turnover_backfill_launchd.log

# §3 等锁最长三条
sed -n '55p' data/logs/r2_upload_async_20261022_213215.log
sed -n '63p' data/logs/r2_upload_async_20261022_183253.log
sed -n '190p' data/logs/etf_national_team_backfill_20261022_2130.log

# §3/§4 锁路径与默认等待上限、fail-closed 分支
sed -n '4160,4165p;4178,4185p;4210,4215p;4253,4260p' scripts/upload_r2.py

# §4 gold-night 7300s 超时与总时长
sed -n '14,30p' data/logs/gold_night_20260930_0240.log

# §5 告警台账对应条目
sed -n '598,610p' data/alerts/alert_ledger.jsonl
sed -n '3680,3690p' data/logs/nextday_plan_launchd.log
sed -n '33090,33150p' data/logs/schedule_monitor_launchd.log

# §5 当前是否有人持锁(只读,不 printf 进文件)
lsof /tmp/trade_r2_upload.lock 2>/dev/null || echo "当前无人持锁"

# §2 今日各 async 跳过次数
grep -c "skip" data/logs/r2_upload_async_*.log 2>/dev/null | tail -20
```