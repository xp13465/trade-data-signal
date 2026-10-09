# W3 = #244「前端通知与邮件送达解耦」§0 生产上线核验报告

- 核验时间:2026-10-10 01:56~02:00(周六凌晨,休市)
- 核验人:测试 agent(role-tester);云上全程只读
- 云上仓根:`/home/ubuntu/code/trade-data-signal`(main)
- 结论:**7/7 项全 PASS**,0 FAIL,0 阻断

---

## 项1 链上 commit — PASS

| 项 | 实测值 |
|---|---|
| 云上 `git log --oneline -1` | `66efa9fcb merge(feat/feat/alert-w3-decouple-1010): 统一入口合并 feat/alert-w3-decouple-1010 入 main` |
| 云上 `git rev-parse HEAD` | `66efa9fcb7f08151288c92dc6784503869d8b53e` |
| 云上 `git rev-parse origin/main` | `66efa9fcb7f08151288c92dc6784503869d8b53e`(与 HEAD 一致) |
| 云上 `git branch --show-current` | `main` |
| 本机 `git rev-parse HEAD` / `origin/main` | 同为 `66efa9fcb7f08151288c92dc6784503869d8b53e` |

期望值 `66efa9fcb` 命中。

## 项2 文件逐位一致 — PASS

本机侧 md5 由本 agent 自行计算(`md5 -q`,工作区 clean),云上侧独立计算(`md5sum`):

| 文件 | 本机 main md5(自算) | 云上 md5 | 比对 |
|---|---|---|---|
| `scripts/detect_intraday_anomaly.py` | `45c8108259ecd9eaa70d378adbf30ead` | `45c8108259ecd9eaa70d378adbf30ead` | 逐位一致 |
| `scripts/export_notifications.py` | `82ec8b6190fe11cce063025c4a3033d9` | `82ec8b6190fe11cce063025c4a3033d9` | 逐位一致 |
| `static-site/app.js` | `60168b9363eac36acf2dde3fc66348df` | `60168b9363eac36acf2dde3fc66348df` | 逐位一致 |

**生产执行路径校验(额外补验,防「生产目录≠被核目录」)**:
- systemd service `ExecStart=/bin/bash /home/ubuntu/code/trade-data/scripts/intraday_snapshot.sh`(走 `trade-data` 树)
- `readlink -f /home/ubuntu/code/trade-data/scripts/detect_intraday_anomaly.py` → `/home/ubuntu/code/trade-data-signal/scripts/detect_intraday_anomaly.py`(`trade-data/scripts` 是 symlink 指向 `trade-data-signal/scripts`,2026-09-13 建)
- 经生产路径实测 md5 = `45c8108259ecd9eaa70d378adbf30ead`,与被核文件一致 ⇒ **被核文件 = 生产实际执行文件**
- 另一份 `trade-data/static-site/app.js`(非 symlink,独立实体)md5 = `60168b9363eac36acf2dde3fc66348df`,同样等于本机 main
- 云上 `git status --porcelain` 全树 0 行 ⇒ 三文件无本地改动,即等于 HEAD 内容

## 项3 新 helper 在位 — PASS

云上 grep 计数(`grep -c`,文件 `scripts/detect_intraday_anomaly.py`),并与本机逐项对齐:

| 符号 | 云上计数 | 本机计数 | 定义行(云上,`grep -n "^def ..."`) |
|---|---|---|---|
| `_load_email_pending` | 3 | 3 | L349 |
| `_write_email_pending` | 3 | 3 | L361 |
| `stage_email_pending` | 2 | 2 | L370 |
| `retry_pending_emails` | 4 | 4 | L382 |
| `send_or_stage` | 4 | 4 | L399 |

6 个 def 齐:另含 `record_notified`(L257)。云上计数 = 本机计数,逐一相等。

## 项4 旧门控已消失 — PASS

云上 `grep -n -A2 "if send_alert("` 全量输出(仅 2 处,无一后跟 `record_notified(`):

```
392:    if send_alert(alerts):
393-        _write_email_pending({})
394-        print(f"[anomaly] 补发暂存告警 {len(alerts)} 项成功, 邮件账本已清", flush=True)
--
401:    if send_alert(alerts):
402-        return True
403-    stage_email_pending(alerts)
```

`record_notified` 全文件仅 3 处(云上 `grep -c` = 3):L232 注释、L257 `def`、L433 调用点。L433 调用点上下文(云上 `sed -n 428,436p`)证明**落签已无条件**:

```
    record_notified(_dedup_pending)
    # 邮件送达**单独记账**: 未达 ⇒ 整 payload 暂存待下轮重试(不回归 B 波「全失败仍可重试」)。
    if not send_or_stage(new_alerts):
        print("[anomaly] 告警邮件未确认送达 ⇒ 已暂存待下轮重试(前端源已落签)", file=sys.stderr)
```

即:落签不再是 `if send_alert(...)` 的从属分支,邮件送达走 `send_or_stage` 单独记账。旧门控形态 0 命中。

## 项5 前端链未变 — PASS

见项2 表:`scripts/export_notifications.py` 与 `static-site/app.js` 云上 md5 = 本机 main md5,两份 static-site 副本(trade-data-signal 与 trade-data)app.js 同值。W3 改动面确认为后端 1 文件 + 1 测试文件,前端链零改动(与派单背景一致)。

## 项6 零外发/零副作用 — PASS

本次核验执行的**全部命令清单**(自证):

云上(经 ssh,全部为读命令):
1. `ls -d /home/ubuntu/code/trade-data-signal`、`ls -d /home/ubuntu/code/trade-data`、`readlink -f`
2. `ls -ld <dir>`、`ls -l <dir> | head -3`
3. `git -C <repo> log/rev-parse/branch/status`(纯读)
4. `md5sum <3 files>`(纯读)
5. `grep -c/-n/-A2`、`sed -n` 读文件(纯读)
6. `cat /etc/systemd/system/trade-intraday-snapshot.timer`、`ls /etc/systemd/system | grep -i intraday`(纯读)
7. `ls -l /home/ubuntu/code/`(纯读)

本机:`git log/rev-parse/status/git show 历史`、`md5 -q`、`grep -c/-n`、`sed -n`、`date`、python3 单行 `datetime.date(2026,10,10).strftime`(纯日历计算)。

证据点:
- **未触发任何邮件/飞书/告警**:无 `notify`/`send_alert`/`check_signals`/`feishu`/`resend` 相关调用;未执行任何业务 python(`python3` 仅跑一行纯日历 weekday 计算,不导入项目模块、不读项目文件);未跑任何 `.sh`。
- **未启停任何 unit**:命令清单内 `systemctl` 0 次(`start/stop/restart` 均未出现;timer/service 仅 `cat`+`ls` 读)。
- **未跑任何业务脚本**:`intraday_snapshot.sh`、`detect_intraday_anomaly.py` 等仅被 grep/sed 读文本,**无 source/exec/import**(§18 L50 static-only 合规)。
- **未写云上任何文件**:无 `>`/`tee`/`touch`/`git add|commit|pull|checkout`;云上 `git status --porcelain` 收尾仍 0 行。
- **探针纯静态**:未探针化执行也无 harness,验内容一律 grep/read。
- 本次核验**未出现**后台化命令(无 `moved to the background`),无残留后台任务。

## 项7 自然实跑窗口说明 — PASS(仅说明,无人为触发)

- 驱动链:`/etc/systemd/system/trade-intraday-snapshot.timer` → `trade-intraday-snapshot.service`(`ExecStart=/bin/bash /home/ubuntu/code/trade-data/scripts/intraday_snapshot.sh`)→ 脚本 L216 `if ! "$PY" "$REPO/scripts/detect_intraday_anomaly.py" 2>&1 | tee -a "$LOG"`(失败不阻塞快照,L217)。
- 节奏:`trade-intraday-snapshot.timer` 共 30 个 `OnCalendar` 时点,盘中 **09:25~15:02 每 10min** 一档(09:25/09:35/.../11:25/11:32/13:01/13:05.../14:55/15:02),另 15:35、20:35,`Persistent=true`。⇒ 与「盘中每 10min 跑一次」一致。
- **当前不会自然实跑**:今日 2026-10-10 为**星期六**(本机 `date` = `2026-10-10 01:58 星期六`,python `date(2026,10,10).strftime('%A')` = `Saturday`),休市,时点表内无周六专属档;且核验时刻 01:56 不在任何 OnCalendar 时点。
- **下一自然实跑窗口 = 下一交易日(2026-10-12 周一)盘后首档**;注意 timer 含 `Persistent=true`,只对**错过**的时点补跑一次(systemd 语义:上次触发之后若错过 OnCalendar 时点,重启后补最后一次),因此周一开盘首档 09:25 前需留意的补跑时点以 systemd 判定为准。
- **本次未人为触发**(未 start unit、未手工跑脚本),按派单要求保持只读。

---

## 汇总

| # | 核验项 | 结论 | 关键实测值 |
|---|---|---|---|
| 1 | 链上 commit | PASS | 云上 HEAD = origin/main = `66efa9fcb7f08151288c92dc6784503869d8b53e`,branch=main |
| 2 | 文件逐位一致 | PASS | detect_intraday_anomaly.py 云上/本机 md5 均 `45c8108259ecd9eaa70d378adbf30ead` |
| 3 | 新 helper 在位 | PASS | 5 符号计数 3/3/2/4/4,云上=本机;6 个 def 齐 |
| 4 | 旧门控消失 | PASS | `if send_alert(` 2 处均无 `record_notified(` 从属;L433 无条件落签 |
| 5 | 前端链未变 | PASS | export_notifications.py `82ec8b61...`、app.js `60168b93...` 云上=本机 |
| 6 | 零外发/零副作用 | PASS | 命令清单全读;systemctl 0 次;无业务脚本执行;云上 git status 0 行 |
| 7 | 自然实跑窗口 | PASS(说明) | 周六休市无自然实跑;下一窗口=下一交易日盘中;未人为触发 |

**FAIL 项:0。阻断项:0。**

## 遗留/备注(非阻断)

- 生产 service 走 `trade-data` 树,该树 `scripts` 为 symlink 指向 `trade-data-signal/scripts`(已实测解析到同一文件);若日后有人把该 symlink 换成实体目录,§0 核验需改核 `trade-data/scripts` 本体 —— 建议后续核验沿用「先 `readlink -f` 再 md5」的做法。
- `trade-data/static-site/` 与 `trade-data-signal/static-site/` 是两份独立实体目录(非 symlink),本次 app.js 两处同值;后续前端核验建议两边都核。
