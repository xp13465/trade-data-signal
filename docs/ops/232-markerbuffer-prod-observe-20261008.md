# #232 marker_buffer 新可达路径生产观察(2026-10-08 盘后)

> 生成:tester agent,2026-10-08 ~21:10(云上全程只读:未启停/未改 unit、未跑业务脚本主体、零 R2 写、零真实外发;未切分支/未 commit)
> 观察窗口:2026-10-07 20:16 至 2026-10-08 20:47(窗口起点=修复上云时点,脚本 mtime 10-07 20:17)

## 0. 结论摘要

| 项 | 结论 |
|---|---|
| ssh 连通性 | ✅ 通(真实第 1 次尝试成功;此前一次 exit 127 是本机无 `timeout` 命令,非 ssh 故障) |
| marker_buffer 窗口内 SEVERE | **未触发(未达 3 轮)**;一次 1/3 → 自愈,计数自洽,非回归 |
| 可达性生产样本 | **仍无(长尾)**——修复后 SEVERE 路径尚未真发过,继续观察 |
| 20:40 daily_brief / 20:35 s06 链 | ✅ 未受影响(全链退出码 0) |
| swap/内存 | 当前稳定(swap 99M,三次采样);白天冻结根因=fapi-daily python ~2GB 被 OOM kill(19:23:39),该进程已死、无大进程残留 |
| 顺带重大发现 | deploy 校验 FAIL 持续(16:39 起,20:25 最新仍 2 fail);**alert 项疑自锁**(≠ #235「自动归零」预期),需主控判定 |

## 1. ssh 连通性与方法

- 探测 1:`timeout 40 ssh ...` → `zsh: command not found: timeout`(exit 127)——本机 macOS 无 GNU `timeout`,ssh 未发出,**非 ssh 故障**
- 探测 2(远端真实连接第 1 次):`ssh -4 -i tdsignal.pem -o ConnectTimeout=15 -o ConnectionAttempts=1 -o BatchMode=yes ...` → `REMOTE_OK / VM-0-11-ubuntu / up 25 days, 7:44 / 20:47:33 / load 1.51 1.45 1.48` ✅
- 后续所有远端命令:`ssh -o ConnectTimeout=15`(单次)+ **远端 `timeout N`** 包裹 + 本机 Bash 层硬超时;全部只读

## 2. marker_buffer 窗口核查(任务 ①②)

### 2.1 alert_state.json(云上 `data/alert_state.json`,mtime 2026-10-08 20:45:10,47KB,161 键)

两条相关键:

| key | status | first_seen | consecutive_count | recovered_at / last_recovered | line_sample 要点 |
|---|---|---|---|---|---|
| `nextday_gap_check\|marker_buffer` | recovered | 2026-09-29 09:30:00 | 0 | **recovered_at=2026-10-08 09:45:00**,reason=`marker_buffer_self_healed` | `[nextday_gap_check] ⚠ 第 1 次拉开盘价失败: akshare fund_etf_spot_em 拉取失败: ConnectionErro` |
| `fetch_news\|marker_buffer` | recovered | 2026-10-06 02:00:01 | 1 | last_recovered=2026-10-06 02:00:01(**窗口外**) | `⚠ [fetch_news] R2 上传 rc=1` |

first_seen 保留 09-29 旧值 = 既有语义(schedule_monitor.sh L772 `_b.get("first_seen") or NOW`,state 复用不覆盖),非异常。

### 2.2 monitor 日志(`data/logs/schedule_monitor_launchd.log`,全文件 grep `marker_buffer` 共 6 行)

窗口内 2 行(其余 4 行属 09-29 与 10-06,窗口外):

- `[2026-10-08 09:15 轮] [marker_buffer] nextday_gap_check ConnectionError: 连续1/3 轮未自愈,暂不通知(降级/瞬时标记连续>=3轮才SEVERE)`
- `[2026-10-08 09:30 轮] [marker_buffer] nextday_gap_check 标记/超时抖动已自愈(连续计数重置)`

### 2.3 自洽性判定:✅ 自洽,非回归

- 计数链:1/3 → 下一轮行消失 → 自愈复位(consecutive_count→0 + recovered_at + recovery_reason),对应代码 L831-844(恢复检测分支)与 L1676+ 主恢复循环 —— 闭环完整
- **无计数跳变**(无 1→3 突跳)、**无短窗口连发**(窗口内仅 1 次;与上次事件相距 9 天)、**未达阈值不 SEVERE**(L795-800 语义)⇒ 预期内行为
- 修复版在云上在位:`schedule_monitor.sh` mtime **2026-10-07 20:17**,L784 `seen_keys_this_run.add(_bk)` + #232 注释齐全;窗口全程运行修复版
- 日志轮次连续性:该日志覆盖自 2026-09-13 起(1.6MB),窗口未被轮转截断 ✅

### 2.4 可达性结论

**窗口内 0 次达「连续 3 轮」⇒ SEVERE 路径修复后仍未真发过,可达性无生产样本(长尾),继续观察。** 未编造、未推定。

## 3. 20:40 daily_brief / 20:35 s06 链(任务 ③)—— 未受影响

- **s06(20:35)**:`s06_snapshot.sh` 20:35:23 退出码=0,上传 3/3 + cache purge 3/3;monitor 20:45 轮 `[s06] S06_FRESH_OK coverage_end=20261008 index末=20261008 落后=0个交易日 generated_at=2026-10-08T20:35:01` ✅
- **daily_brief(20:40)**:20:41:23 brief_ledger 写入(date=20261008 / signals_today=20);20:41:46 ledger 对账完成;`daily_brief_launchd.err` 仅 resolve_repo 正常环境行,无报错 ✅

## 4. 顺带发现:deploy 校验 FAIL 持续 + alert 项自锁疑点(与 #232 无关,已登记 #235 同族)

### 4.1 现象

- 10-08 全部 deploy 日志均被 check 拦(16:45 4fail / 17:00 3fail / 18:28 4fail / 19:30 4fail / 20:05 3fail / 20:11 2fail / **20:25 最新 2fail**),行原文:`✗ 数据产物校验失败(退出码 1)，终止部署（4 类事故拦截）`
- 20:25(最新)2 项:`✗ alert: alert.json date=20260930 滞后 8 天 > 7 天` + `✗ s06_state: 线上 S06 快照 coverage_end=20260930 滞后 8 天 > 7 天`
- 告警已发:16:39:14(last_alerted);其后 6h 去重窗抑制(20:25 日志 `suppress ... age=12798s < window=21600s`)

### 4.2 关键新观察(相对 #235 预期「17:50 后自动归零」——实测未兑现)

| 事实 | 证据 |
|---|---|
| check 读**线上 R2**(非本地源) | `check_data_integrity.py` L412-417(alert,注释「数据源=线上 R2(生产权威)」)+ L2190(s06_state,同 `_fetch_r2_json`) |
| 源侧已新 | 云上 `static-site/data/alert.json` = date **20261008** / generated_at 19:29:45;`kelly_mode_s06_state.json` generated_at 20:35:01 |
| 线上仍旧 | 实测 curl `ssd.fx8.store/data/alert.json` → date=**20260930** / generated_at 2026-09-30 18:37:24(~21 时点仍旧) |
| R2 数据通道=deploy 内部 | deploy.sh L582 触发 `r2_upload_async`(唯一 R2 数据通道,#235 复核报告 L16);10-08 全天无 r2_upload_async 日志(本次复核 `data/logs` ls 一致) |
| 无 SKIP 绕过 | deploy.sh L324-331:check fail → exit 1 硬终止(已 grep:`SKIP/FORCE` 仅作用于时段闸门,不作用于 check) |

⇒ **推断(标注:机制推断,未直读 R2 时间戳/未验证 alert.json 是否存在 deploy 之外的独立上传通道)**:alert 项构成**自锁**——线上 alert.json 变新的通道只有 deploy,而 deploy 因线上旧被拦、不跑通道 ⇒ 不自行归零;明晨 02:00(backfill-evening)/05:00(us-stock-morning)链 deploy 会持续拦。

- s06_state 项不同:20:35 `s06_snapshot.sh` **独立通道**已上传(signal_kelly_snapshots 3/3)⇒ 下次 deploy 该项**应**归零(**未实测**,待下次 deploy 日志验证)
- 待主控判定:①并入 #235 处置(选项①「不补跑等自动归零」预期至少对 alert 项已被证伪,或需修正);②用户视角一致性缺口(源 10-08 vs 线上 09-30,§22)

### 4.3 冻结段 deploy 日志尾部(任务 ④ 之「有无异常」)

- `deploy_20261008_1828.log`:18:28:38 起跑,mtime 19:26(被冻结拉长 ≈58min),尾部无崩溃痕迹,正常收尾于 check fail + dedup suppress ⇒ **冻结段 deploy 无新增崩溃类异常;唯一持续异常 = 上述 check FAIL 拦截**

## 5. swap/内存现状 + 冻结根因(任务 ④)

### 5.1 三次采样:「根因是否仍在累积」→ 当前无累积迹象

| 时刻 | Mem used/free/avail (MB) | Swap used | load |
|---|---|---|---|
| 20:48 | 386 / 586 / 3059 | 99.9M(总 1023M) | 1.51 |
| ~20:53 | 404 / 564 / 3041 | 99M | ~1.3 |
| ~21:05 | 429 / 538 / 3015 | 99M | 1.26 |

- top RSS(20:48):python 147MB / python 102MB / YDService 52MB —— **无 2GB 级进程残留**
- ⇒ swap 稳定 ≈99M(≈10%),短窗口无累积;96% 的曾用 swap 已收回

### 5.2 冻结根因实证(`/var/log/kern.log`,19:23:39 段)

```
packagekitd invoked oom-killer: gfp_mask=0x1100cca(GFP_HIGHUSER_MOVABLE), order=0, oom_score_adj=0
8196 pages in swap cache / Free swap = 0kB / Total swap = 1048572kB        ← swap 全满实锤
oom-kill:constraint=CONSTRAINT_NONE,...,global_oom,task_memcg=/system.slice/trade-fapi-daily.service,task=python,pid=1806845,uid=1000
Out of memory: Killed process 1806845 (python) total-vm:5082240kB, anon-rss:2044904kB, ... oom_score_adj:0
```

- 根因 = **trade-fapi-daily.service 的 python 进程膨胀至 ≈2.0GB anon-rss** → 3.7G 内存 + 1G swap 双满 → global OOM(19:23:39 kill 即恢复点)
- kern.log 仅含 18:35:58 与 19:23:39 两段(22KB),无更早记录
- 复现风险观察点:`trade-fapi-daily.timer` 下次 = **10-09 18:10**(今日 18:10 那次即被杀进程,OOM 后未立即重跑)——膨胀条件若不变存在重演风险(不预测,仅标记)

### 5.3 failed units(只读 `systemctl --failed`,6 项)

`trade-etf-national-team / trade-fapi-daily / trade-futures-backfill / trade-kelly-intraday-rerun / trade-lhb-backfill / trade-public-fund-daily` 全 failed。

- 演变:09:15 轮 monitor 报 failed=0 → 09:45 轮报 1 项(kelly-intraday-rerun)→ 20:45 轮报 6 项
- 各 timer last run 均在今天(18:10~20:07),next 多为明日 ⇒ 判为**冻结期任务被 kill 的残留子状态,待下次触发复位**;monitor 行:`[196] 云上 unit 异常(自身通道已发告警): CHECK_FAILED_UNITS_FAIL(1 项): ...`(20:45 轮)
- 观察点:futures-backfill(21:00)/ etf-national-team(21:30)触发后应复位;若仍 failed 需人工 `reset-failed`(建议主控明日核查)

### 5.4 monitor 轮次断档实证(冻结窗)

grep 轮次标记:`18:30:00 → 19:23:40(×2)→ 19:30:00` ⇒ 18:45/19:00/19:15 三轮缺失(≈45min),与 runbook 时间线一致。

## 6. 未测/未核项(诚实标注)

1. marker_buffer SEVERE 修复后仍未真发 → 无样本可取(长尾)
2. 「自锁」为机制推断:未直读 R2 对象时间戳;未验证 alert.json 是否有 deploy 之外的独立上传通道(建议主控派核)
3. s06_state 项下次 deploy 是否归零:未实测(需下次 deploy 日志)
4. failed units 是否被下次 timer 自动复位:窗外,未观察
5. swap 打满的**更上游累积过程**(18:30 告警 → 18:32 冻结之间的内存爬升曲线):本次未取(journal/dmesg 早期段缺)

## 7. 证据链(可复核命令)

```
# ssh 探测(本机无 timeout,用 ssh 自带超时)
ssh -4 -i tdsignal.pem -o ConnectTimeout=15 -o ConnectionAttempts=1 -o BatchMode=yes ubuntu@122.51.111.173 'echo REMOTE_OK; hostname; uptime'
# marker_buffer 全量
grep -n marker_buffer ~/code/trade-data/data/logs/schedule_monitor_launchd.log
python3 - alert_state.json(marker 子串键 + 值)
# deploy 汇总/明细
for f in deploy_20261008_16{45},...; grep -a 汇总|✗ $f
# 根因
grep -a -E "Out of memory|oom-kill|Free swap" /var/log/kern.log
free -m; swapon --show; ps -eo pid,rss,comm --sort=-rss | head -4
systemctl --failed --no-pager
# 线上一致性
curl -s --max-time 15 https://ssd.fx8.store/data/alert.json | head -c 400
```

---
*只读观察报告;未 commit(主控收口)。*
