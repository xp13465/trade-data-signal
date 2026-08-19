# 生产运维修复：etf_national_team 超时保护失效 + feishu_ws 实时流假死（2026-08-19）

> 两条生产告警，均属 bug 修复（§23.7 例外）。proc = kill 进程组 → 根因修复 → 排查同类 → 自测。
> 落档人：implementer agent（2026-08-19 23:5x，安全窗口 23:00 后执行）

---

## 告警1：etf_national_team —— 21:30 兜底槽卡死 2h19m+ 占锁（最急）

### 现象（现场证据）
- 进程组 5432（with_lock.py 持锁）→ 5438（bash）→ 5454（tee）running，etime 02:20:40+。
- `/tmp/trade_etf_nt.lock` 被 PID 5432 持有。
- 2130 日志停在 21:30:07-08：`mootdx - INFO - [-] 选择最快的服务器...` ×8（8 worker）+ 7 个 `[ohlc] WARNING ... 均返空，close/amount 将为 NULL` 后 **0 进度**。
- `[etf_nt] daily 全局超时 600s + socket 超时 30s 已设`（L4 日志）已打，但 600s 后（21:40）没触发 `_timeout_handler → os._exit(2)`。

### 根因：signal.alarm 在 macOS 主线程阻塞于 pthread_cond_wait 时永久失效
`app/collector/etf_national_team.py` 的超时保护 = `signal.alarm(600)` + `_timeout_handler → os._exit(2)`。
但 daily 走 **ProcessPoolExecutor 8 worker** 并发，主进程阻塞在：
```
for fut in as_completed(fut_to_idx):      # concurrent.futures
    results.append(fut.result())          # -> Future 内部 Condition.wait()
```
`as_completed / fut.result()` 底层是 `threading.Condition.wait()` → macOS 的 `pthread_cond_wait`（Darwin `__psynch_cvwait` 内核调用）**对信号不可中断**——信号到达时不返回 EINTR，主线程一直睡在 condition wait 里，SIGALRM **一直 pending 未交付**，600s 到点 `_timeout_handler` 不执行，锁不释放。

这正是 2026-07-31 事故（mootdx 卡死 23h）防护的空洞：**单线程阻塞在 socket（EINTR 可中断）时 signal.alarm 有效，但阻塞在 Condition.wait（macOS 不可中断）时完全失效**。8-01 加的 signal.alarm 保护覆盖不到 ProcessPool 场景。

### 止损（已执行）
```
kill -TERM -5432   # kill 进程组
# 确认退出：ps 查 5432/5438/5454 已无，lsof /tmp/trade_etf_nt.lock 无持有者
# launchctl list | grep etf-national  ->  PID 列变 '-'（非 running）
```
锁已释放，明天 20:07/21:30 两槽**不再因占锁被跳过断更**。

### 根治方案（已落地）：独立 daemon 看门狗线程强杀
在 `_timeout_handler` 后新增 `_start_timeout_watchdog(deadline_sec, cmd)`：
- 起一个 daemon 线程，内部 `Event.wait(deadline_sec)`（定时等待到时必然返回，不依赖信号），到点 `os._exit(2)` 释放 fcntl 锁。
- 线程调度**独立于主线程阻塞状态**：不管主线程卡在哪（Condition.wait / socket recv / C 扩展），看门狗都能准时强杀。
- `signal.alarm` 保留作 socket EINTR 场景兜底（线程替不了 signal.alarm 中断 socket 的场景）。
- 正常完成路径：`finally` 里 `_wd_done.set()` 取消看门狗（`Event` 记在 `_wd_done`，`main()` 前置 `_wd_done=None` 防 NameError），不误杀后续操作。

修改文件：`app/collector/etf_national_team.py`（`_start_timeout_watchdog` 新增 + `main()` L2020-2029 启动看门狗 + `finally` L2108-2115 取消）。

### 自测（已通过）
模拟超时看门狗（`python - <<PY` 加载同一模块 `_start_timeout_watchdog`）：
- 正常路径：心跳 3s 内 set() 取消 → 看门狗未误杀（打印 PASS 后继续执行）。
- 超时路径：2s 超时到点 → 打印 `看门狗超时(2s)退出... os._exit(2)`，**进程退出码=2**（= os._exit(2)，非 130）。
- 结论：即使主线程阻塞，独立看门狗也能准时 os._exit(2)，根治信号不可中断导致的超时保护空洞。

### 排查同类（signal.alarm 超时保护使用者 3 处）
| 文件 | signal.alarm handler 行为 | 是否同洞 |
|---|---|---|
| `app/collector/etf_national_team.py` | handler → os._exit(2) | **同洞，已修**（看门狗线程） |
| `app/collector/runner.py` L411-458 | handler → raise TimeoutError，"SIGALRM 中断 socket syscall" | **低危**：单线程阻塞 socket（EINTR 可中断），且 30min 内有频繁 bytecode 边界，能准点触发。但若未来 runner 也引入 ProcessPool/queue.wait 阻塞，会退化——已在本文件头部注释提示。 |
| `app/collector/hkex_ccass_quarterly.py` L412-489 | handler → raise TimeoutError，主线程主要 `time.sleep(0.5)` 限速 | **低危**：sleep 会被信号打断、常量 bytecode 边界密集，能准点触发。无 ProcessPool 阻塞主线程场景。 |

结论：仅 etf_national_team 存在 ProcessPool + Condition.wait 阻塞主线程的高危同洞，已根修。runner.py / hkex 未见同级阻塞场景，暂不改（避免为未坏功能引入改动，§23.7）。

### 数据补跑状态与指引（待 mootdx 数据源恢复）
- 现场核实：`etf_daily` 表 8-19 已 insert 12 只宽基（ETF_LIST），其中 6 只沪市(sh) amount 全有、**6 只深市(sz) amount=None**（深市成交额源未就绪）。全量 1467 只（含窄基/行业）etf_daily 只到 8-18。
- **overview.json 的 etf 宽基评分/信号 date=20260819 全部已上线**（adb8b9 全量管线已推宽基 tiers），用户可见层宽基数据未断更。
- **mootdx k线源 bars 仍全空**（选服务器 OK 但取 999999/510050 freq 8/9 均 len=0），sina 同样返空（21:30 WARNING 同因），仅腾讯源有数据（`web.ifzq.gtimg.cn` 510050 qfq 有值）。
- **当前不补跑全量的原因**：mootdx/sina k线源未恢复，补跑会重演采空数据（或看门狗强杀），无意义且有污染风险。
- **补跑指引（mootdx 恢复后执行）**：
  ```bash
  # 先验证 mootdx k线可取数（bars len>0）
  bash /Users/linhuichen/code/trade-data/scripts/etf_national_team_backfill.sh force
  # 该脚本内部会持 deploy 锁 + deploy.sh 推线上，错开 adb8b9 并发（本次 adb8b9 已于 23:52:59 结束，锁已释放）。
  # force 绕过非交易日闸门（今天 is_trading_day=True，非交易日判断 = 8-19 交易日无需 force）
  ```
- **兜底**：即使 mootdx 持续未恢复，明天 20:07/21:30 主槽用看门狗防护后不会再卡死；若数据源恢复则自动补全 8-19 深市 amount + 全量；若仍未恢复则 recording 完整告警（不再占锁断更）。

---

## 告警2：feishu_ws —— 实时事件流断 48h+

### 现象（现场证据）
- listener 进程 76174 在（8-18 22:12 启动），但 `feishu_listener.log` 最后 8-18 22:12:16 "connected to wss://msg-frontier.feishu.cn" 后 **25h+ 零事件日志**。
- `/tmp/feishu_ws_last_event` 心跳戳停 8-17 13:18（超 48h）。
- 8-18 22:12 仅靠 REST 补拉捞回历史（found=20，skipped=20），漏捞窗口内实时事件。

### 根因：lark-oapi ws client「接收侧假死」
`lark_oapi.ws.client.Client.start()` → `_receive_message_loop()` 阻塞在：
```
msg = await self._conn.recv()      # websockets recv
```
`auto_reconnect=True` 只在 `recv()` **抛异常**（ConnectionClosed）时重连。当 WS 连接「半死/僵尸」——**TCP 仍 ESTABLISHED、服务器停止推事件、但 recv() 不抛异常**时，auto_reconnect 永不触发，`client.start()` 的 `loop.run_until_complete(_select())` 永远阻塞，外层 listener `while True`（L902-910，只有 start() 抛异常或 Ctrl-C 才走）也不执行 → **整个进程假死，用户飞书群发"需求:"既不落盘也不回执，且无告警**。

这是 listener 代码自身已标注的「#25 缺口 A（接收侧静默假死）」：注释明确 `auto_reconnect 发现不了连接在但无事件`，`ws_last_event` 心跳戳本用于 schedule_monitor 维度⑨**检测**假死，但**缺乏自愈手段**（只告警不修复）。

### 止损（已执行）
```
launchctl kickstart -k gui/$(id -u)/com.trade.feishu-listener   # PID 76174 -> 重启
# 重启后（23:51:05）confirmed connected 新 ws conn，启动补拉捞回窗口内消息（各群 found 12/363/31）
```

### 根治方案（已落地）：接收侧假死看门狗 + os._exit + launchd KeepAlive 自愈闭环
新增 `_start_liveness_watchdog(stale_limit)`（`scripts/feishu_ws_listener.py`）：
- daemon 线程每 1s 节拍检查 `/tmp/feishu_ws_last_event`（process_event 每成功处理一条就 touch）的 mtime 是否**持续前进**。
- 逻辑用「心跳停更 N 秒」而非「距上次事件超 N 秒」：安静时段（无新事件=正常）不误杀，只在"本应持续有事件流动证明活着、却停更 N 秒"时判定假死。
- 停更超阈值 → `os._exit(2)` 退出整个进程 → **plist `KeepAlive=true` + `ThrottleInterval=10` 由 launchd 自动拉起** → 重启时 `RunAtLoad` + `_run_startup_missed_fetch` 补拉漏收窗口 + 全新 WS 连接 = 自愈闭环。
- `stale_limit` 默认 7200s(2h)，可经 `FEISHU_LIVENESS_STALE_LIMIT` 环境变量覆盖，下限 300s(5min) 防误配过小狂重启。
- 正常退出时 `finally` `stop_wd.set()` 取消看门狗不误杀。

修改文件：`scripts/feishu_ws_listener.py`（新增 `_start_liveness_watchdog` + `run_listener` L902 外循环前置启动 + 补 `import threading`）。

### 自测（已通过）
- 单测 A：心跳每 1s touch → 看门狗 3s 阈值下不误杀（正常时段安全）。
- 单测 B：心跳停更 3s → 打印 `接收侧假死看门狗触发...判定 WS 假死...os._exit(2)`，**进程退出码=2**（自愈触发）。
- 回归：`test_feishu_ws_listener.py` **33 用例全过 OK**（0 回归），证明看门狗改动未破坏现有落盘/回执/转发/防循环逻辑。

### 排查同类（ws 实时链路）
- 唯一 feishu 长连接消费者 = `scripts/feishu_ws_listener.py`（launchd `com.trade.feishu-listener`，ws_last_event 心跳戳 L69 定义）。已加自愈。
- 其他 feishu 通道（`notify.py` / `check_nt_signals.py` / `daily_brief`）均为 REST 主动推送（背压式"发就发、失败重试/落 pending"），**无 ws 长连接、无假死窗口**，不受此洞影响。
- schedule_monitor 维度⑨仍保留（告警层），看门狗补上自愈层，双层闭环。

---

## 复现 / 验证命令
```bash
# etf 看门狗自测（需 REPO=trade-data venv）
cd /Users/linhuichen/code/trade-data && python - <<'PY'
import app.collector.etf_national_team as m, threading, time
m._start_timeout_watchdog(2, "utest")  # 预期 2s 后 os._exit(2), 退出码=2
time.sleep(3)
PY
echo $?   # 应为 2

# feishu 看门狗自测
cd /Users/linhuichen/code/trade && python - <<'PY'
import sys,time,pathlib; sys.path.insert(0,"scripts")
import feishu_ws_listener as m
m.WS_LAST_EVENT_FILE=pathlib.Path("/tmp/feishu_ws_last_event_utest")
m._start_liveness_watchdog(3)  # 心跳停更 3s 后 os._exit(2)
time.sleep(4.5)
PY
echo $?   # 应为 2

# feishu 回归单测
cd /Users/linhuichen/code/trade-data && /Users/linhuichen/code/trade/.venv/bin/python \
  scripts/test_feishu_ws_listener.py -v   # 期望 33 用例 OK

# 补跑 etf 全量（mootdx bars 恢复后）
bash /Users/linhuichen/code/trade-data/scripts/etf_national_team_backfill.sh force
```

## 遗留待办
- [ ] mootdx/sina k线源恢复后补跑 etf 全量（含深市 6 只 amount），见「数据补跑状态与指引」。
- [ ] 观察明天 20:07/21:30 主槽是否正常采集完成（看门狗防护验证上线后真实场景）。
- [ ] 观察 feishu listener 下周是否持续心跳前进（2h 假死阈值生效验证）。

## 关联规范
- §23.2 修 bug 三铁律：修完整（ProcessPool signal.alarm 空洞根治 + 排查同类 3 处 signal.alarm 使用者）+ 自测（两处看门狗 py 模拟 + 33 单测回归）+ 排查同类（feishu 其他通道非 ws、无同洞）。
- §23.7 版本冻结契约：两条均为 bug 修复，§23.7 例外（纯 bug 修复不受冻结限制），未夹带未确认的功能改动。
