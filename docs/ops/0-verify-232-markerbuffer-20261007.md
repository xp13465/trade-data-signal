# #232 §0 上线验证报告(marker_buffer seen 修复,云上只读)

- **日期**:2026-10-07;执行:测试 agent(tester);范围:§0 上线验证七项(云上只读)
- **验证对象**:`scripts/schedule_monitor.sh` #232 修复 —— 承重行 L784 `seen_keys_this_run.add(_bk)`;inline 复位 L840 `"consecutive_count": 0`
- **基线**:本地 main `30a62ef99`(含合并点 `586693f7a` + 独立审记账);云上 `trade-data-signal` HEAD `586693f7a`(= origin/main)
- **硬约束遵守声明**:全程零真实外发(未触发邮件/飞书/告警/R2 写);未启停任何 systemd unit(仅 `systemctl list-timers` / `systemctl show` 只读);未执行任何业务脚本主体(仅 `bash -n`、grep、sed、cat、awk;§18 L50 static-only);本地未跑任何改数据命令;云上仅只读命令;无 `find /`、无白名单外 `grep -r`、无 curl、无 pip/npm 裸跑;token 未出现在任何 argv。
- **残留后台任务**:无(本次未出现 `moved to the background`)。

## 结论总表

| # | 验证项 | 结论 |
|---|---|---|
| 1 | 本地 main 含 commit | **PASS** |
| 2 | 云上代码一致(md5 逐位) | **PASS** |
| 3 | 承重行在位 | **PASS**(含红先验) |
| 4 | 语法 | **PASS** |
| 5 | 云上实跑无异常 | **PASS**(新码 2 个 tick 实证) |
| 6 | 无新告警风暴 | **PASS**(如实分档,见 §6) |
| 7 | 诚实缺口 | 已标注:可达性无生产样本,长尾观察项 |

---

## 1. 本地 main 含 commit —— PASS

```bash
git log --oneline -1; git log origin/main --oneline -3; git branch --show-current
```
输出(节选):
```
30a62ef99 docs(#232): 独立审 PASS 10/10 + 已合 main 586693f7a 收口记账
---
30a62ef99 docs(#232): 独立审 PASS 10/10 + 已合 main 586693f7a 收口记账
586693f7a merge(feat/feat/232-markerbuffer-seen-20261007): 统一入口合并 feat/232-markerbuffer-seen-20261007 入 main
e177f07a4 docs(#232): 修复实施完成记账(tip 91bea3778)+ 已派独立审
---
main
```
`586693f7a` 与记账 commit `30a62ef99` 均在链上;本地 main 与 origin/main 同点。

## 2. 云上代码一致 —— PASS

- 云上入口 `ssh -i ~/tdsignal.pem ubuntu@122.51.111.173`;**仓库/实跑路径为实际读 unit 确认,非猜**:
  `cat /etc/systemd/system/trade-schedule-monitor.service` ⇒
  `WorkingDirectory=/home/ubuntu/code/trade-data`;`ExecStart=/bin/bash /home/ubuntu/code/trade-data/scripts/schedule_monitor.sh`;
  `Environment=GIT_REPO=/home/ubuntu/code/trade-data-signal`;`Environment=REPO=/home/ubuntu/code/trade-data`。
  ⇒ **实跑份 = `/home/ubuntu/code/trade-data/scripts/schedule_monitor.sh`(不是 trade-data-signal;两份为并列目录非 symlink,`readlink -f` 返回自身)**。
- 云上 git 仓:`cd /home/ubuntu/code/trade-data-signal && git log --oneline -1` ⇒ `586693f7a ...`(= `origin/main`);`git status --porcelain` 输出空(工作区 clean)。
- md5 三份逐位比对(`md5sum` / macOS `md5 -q`):

| 位置 | md5 |
|---|---|
| 本地 `/Users/linhuichen/code/trade/scripts/schedule_monitor.sh` | `0291c26b44efc08e9815560eaf201350` |
| 云上**实跑份** `/home/ubuntu/code/trade-data/scripts/schedule_monitor.sh` | `0291c26b44efc08e9815560eaf201350` |
| 云上 git 仓 `/home/ubuntu/code/trade-data-signal/scripts/schedule_monitor.sh` | `0291c26b44efc08e9815560eaf201350` |

⇒ **MATCH(逐位一致)**。

## 3. 承重行在位 —— PASS

云上实跑份 grep 原文:
```
784:                            seen_keys_this_run.add(_bk)
840:                        "consecutive_count": 0,
```
L840 上下文(`sed -n '838,842p'`)含 `"recovery_reason": "marker_buffer_self_healed"` ⇒ 确认为 marker_buffer inline 复位块(与 L2221 的 r2_intraday_lag 同类行区分开)。

**红先验(§5.2 尺子自检,证判据能区分修复前后)**:
- `git show 91bea3778^:scripts/schedule_monitor.sh | grep -c "seen_keys_this_run.add(_bk)"` ⇒ `0`(修复前无承重行);同段 sed 查 `consecutive_count` ⇒ 空(修复前 inline 块无显式复位行)
- `git show HEAD:scripts/schedule_monitor.sh | grep -c ...` ⇒ `1`
⇒ 判据有效,非"永远绿"的坏尺子。

## 4. 语法 —— PASS

- 本地 `bash -n scripts/schedule_monitor.sh` ⇒ rc=0
- 云上实跑份同命令 ⇒ rc=0

## 5. 云上实跑无异常 —— PASS(新码 2 个 tick)

- 上线时点:实跑份 mtime `Oct 7 20:17`;`trade-schedule-monitor.timer` `OnCalendar=*:00,15,30,45:00`;`systemctl list-timers` LAST=20:15:01(旧码)⇒ **20:30 为新码首跑,20:45 为第二跑**(均在本报告窗口内实证)。
- `systemctl show trade-schedule-monitor.service -p ExecMainStatus -p ExecMainExitTimestamp`:
  - 20:15 次(旧码)rc=0 @20:15:14
  - **20:30 次 rc=0 @20:30:06**
  - **20:45 次 rc=0 @20:45:12**
- 日志 `/home/ubuntu/code/trade-data/data/logs/schedule_monitor_launchd.log` 两个新码 tick 块原文(行号 15118-15127):
```
15118 [in-progress-stale] s06_snapshot dur=null 但 last_run=2026-09-30 20:35 距今 > 6h(无结束行的陈旧起点, 任务实际已结束), 不判进行中(不 hold 其历史告警)
15119 [info] nextday_plan 退出失败 last_exit=1 last_run=2026-09-30 22:30 距今>24h, 旧告警已过期,等下次任务跑更新(不重复 SEVERE)
15120 [196] CHECK_FAILED_UNITS_OK failed=0 watchman=7 个 timer 全部在跑
15121 [2026-10-07 20:30:01] OK 所有任务按计划执行，无漏跑，无退出失败
15122 [s06] S06_FRESH_OK coverage_end=20260930 index末=20260930 落后=0个交易日 generated_at=2026-09-30T20:35:01
15123 [in-progress-stale] s06_snapshot dur=null ...(同 15118)
15124 [info] nextday_plan 退出失败 ...(同 15119)
15125 [196] CHECK_FAILED_UNITS_OK failed=0 watchman=7 个 timer 全部在跑
15126 [2026-10-07 20:45:01] OK 所有任务按计划执行，无漏跑，无退出失败
15127 [s06] S06_FRESH_OK coverage_end=20260930 index末=20260930 落后=0个交易日 generated_at=2026-09-30T20:35:01
```
- **rc=0 属弱证据的说明**:脚本末尾 L2790-2791 `exit 0`(注释:总是 exit 0,告警已发邮件,避免重试)⇒ rc 恒 0,**不以 rc 单独判定**;交叉证据四件:
  1. heartbeat `/tmp/schedule-monitor-heartbeat.txt` = `2026-10-07 20:30:01` / `alerts=0`,及 `2026-10-07 20:45:01` / `alerts=0`(由脚本 L2763-2771 在 s06 检查之后写)⇒ 两次 tick 均完整跑至收尾段且**零告警**;
  2. stderr 文件 `schedule_monitor_launchd.err` 20:30/20:45 后新增行全为 `resolve_repo: REPO=... GIT_REPO=...` 常态行(全文件 170 行 100% 为 resolve_repo,无 traceback);
  3. 告警落盘 `data/alerts/latest.md` mtime 停在 18:45(20:30/20:45 均未写);
  4. tick 输出逐段完整(in-progress-stale / info / [196] / OK / s06 五段齐,无截断)。
- **块结构备注(供后续验证者,防误判)**:monitor 日志中每 tick 块的实际顺序为 `[in-progress-stale][info][196][OK 行][s06]`,**OK 行不总在块首**;按"OK 行为块首"统计会把"下一 tick 的前缀 3 行"算成上一 tick 的尾部,诱出"缺 3 行"假象(本次一度误判,经 20:45 tick 复验 + 源码打印点行号对照 L866/L1647/L2696/L2754 纠正)。

## 6. 无新告警风暴 —— PASS(如实分档)

- `data/alert_state.json`(20:30、20:45 各被 tick 重写一次,46753 字节不变):`marker_buffer` 相关键 **2 个,无新增**:
  - `nextday_gap_check|marker_buffer` → `status=recovered`,`consecutive_count=1`,first_seen 2026-09-29 09:30
  - `fetch_news|marker_buffer` → `status=recovered`,`consecutive_count=1`,first_seen 2026-10-06 02:00
  ⇒ 无计数跳变、无自相矛盾;两键均为修复前历史项。
- 20:16 后日志**无任何 `SEVERE` 行、无 `检测到 N 个告警` 行**(最后一条 SEVERE 位于 15081 行 = 18:45:01,fetch_news R2 上传锁,与 #232 无关)。
- alert_state 当前 `active` 键仅 `nextday_plan|exit!=0|1`(既有项,日志对应 `[info] ... 不重复 SEVERE`,与 #232 无关)。
- **分档陈述(按派单口径)**:本次窗口**未出现** marker_buffer degrade 事件 ⇒ 既无「预期内第一条 SEVERE」也无「计数跳变告警」;若后续真出现一条且 line_sample/计数自洽(连续轮计数真达 3),按派单口径 = **预期内、不算回归**。
- 旁证病理真实存在:修复前两个历史 marker_buffer 键 `consecutive_count` 均锁死为 1(结构性不可达 ⇒ 计数恒 1),与定性报告 §1.1 状态机逐位吻合。

## 7. 诚实缺口 —— 已标注

- **marker_buffer 链 SEVERE 可达性尚无生产样本**:实证"补 seen 后连续轮计数 1→2→3 可达阈"需要**真实 degrade 事件**(某任务连续 3 个 tick ≈45min 处于"有运行但结局未定论"),本次窗口无该事件 ⇒ 列为**长尾观察项**,后续巡检时留意首个 marker_buffer SEVERE 是否出现且计数自洽。
- **不得用合成/人为构造样本冒充生产样本**(§18 L49):本报告未构造任何 degrade 样本;行为层证据上限 = "新码 2 个 tick 实跑正常 + 零新增告警 + 输出完整"。
- 未验证项(超本次只读边界,如实列出):(a) 计数累积 1→2→3 的行为级实证(需 degrade 事件或行为测试);(b) 长期多 tick 稳定性。

## 复现命令清单(可复核)

```bash
# 本地
git log --oneline -1; git log origin/main --oneline -3
md5 -q scripts/schedule_monitor.sh
bash -n scripts/schedule_monitor.sh
git show 91bea3778^:scripts/schedule_monitor.sh | grep -c "seen_keys_this_run.add(_bk)"   # 期望 0
# 云上(只读)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cat /etc/systemd/system/trade-schedule-monitor.service'
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cd /home/ubuntu/code/trade-data && md5sum scripts/schedule_monitor.sh && grep -n "seen_keys_this_run.add(_bk)" scripts/schedule_monitor.sh'
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cd /home/ubuntu/code/trade-data-signal && git log --oneline -1'
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'systemctl show trade-schedule-monitor.service -p ExecMainStatus; cat /tmp/schedule-monitor-heartbeat.txt; tail -12 /home/ubuntu/code/trade-data/data/logs/schedule_monitor_launchd.log'
```
