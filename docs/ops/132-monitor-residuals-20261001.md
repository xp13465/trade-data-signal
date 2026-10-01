# #132 #131 修复的 3 条残留低风险项 — 实施报告(2026-10-01)

分支: `feat/132-monitor-fixups-20261001` | base: c792cbf70(origin/main)

本任务修 #132 台账的 3 条残留(凌晨槽时点漂移误判 / self_heal 并发双通知 / 计数文件写失败静默漏报)。
前两条为低风险项,第三条为「降噪反而制造新静默」同族(#131 病灶),按 §23.2 修 bug 三铁律处理。

---

## ① 02:00 槽时点漂移误判 → 假 SEVERE

### 病灶与改动前后对照
- **改动前**(`scripts/backfill_direct_metrics.py` `_is_morning_slot`):
  ```python
  slot = os.environ.get("BACKFILL_SLOT", "")
  return slot.startswith("02") if slot else False
  ```
  依赖 env 串前缀「02」。mac 休眠唤醒延迟致 02:00 槽在 03:00+ 才启动 → `BACKFILL_SLOT=0300`
  → 被判非凌晨 → 02:00 槽的结构性预期缺口(新浪源 T+1、目标日=当日必败)误判为真故障
  → exit 1 → schedule_monitor 假 SEVERE+恢复邮件循环。
- **改动后**: 改为按实际时点判定,不再依赖 env 串前缀:
  ```python
  def _is_morning_slot(now: dt.datetime | None = None) -> bool:
      slot = os.environ.get("BACKFILL_SLOT", "")
      if not slot:
          return False          # 手动/update_all 保守按非凌晨(不放过)
      now = now or dt.datetime.now()
      return now.hour < 5       # 宽限窗口: 实际时点 < 05:00 = 凌晨槽
  ```
  判定 = `BACKFILL_SLOT 存在`(槽语义= backfill-evening)且 `实际时点 < 05:00`(宽限窗口)。

### 哪些情形仍报 / 哪些不再报(逐条)
| 场景 | 之前 | 现在 |
|---|---|---|
| 02:00 整点正常启动, gap | 静默 | 仍静默(不变) |
| **02:00 槽唤醒漂移到 03:00/03:30/04:59, gap** | **假 SEVERE(病灶)** | **静默(修复)** |
| 非 gap 失败(direct:* error / 抛异常 / no config)任意时点 | fail→exit 1 | 仍 fail→exit 1(不变) |
| 16:35/21:00 兜底槽六源全败 | fail→exit 1 | 仍 fail→exit 1(不变,六源全败=真故障判别保留) |
| 05:00 后(唤醒延迟超整夜)仍六源全败 | fail→exit 1 | 仍 fail→exit 1(该有数据而没有=真故障,须报) |
| 手动跑/update_all 无 BACKFILL_SLOT, 凌晨 gap | fail→exit 1(保守) | 仍 fail→exit 1(保守不放过,不变) |

真故障判别维度(memory `alert-denoise-keep-fault-discriminator`)完整保留: gap 静默只适用
「BACKFILL_SLOT 存在 + 实际时点<05:00」;该条件外的 GAP_MARKER 一律按真故障计 fail,非 gap
失败无条件计 fail。

### 举一反三(§23.3 同模式): hkex CCASS 同病一并修复
`app/collector/hkex_ccass_quarterly.py` `_current_slot()` 原用 `slot.startswith("02")` 判
02:00 强制重算槽 —— 同病: 唤醒漂移致 BACKFILL_SLOT=0300 → 丢失 02:00 每日强制重算语义
(退化成季度闸门路径)。已并行修复为 `0 <= hh < 5` 时归一 `"0200"`(无 env 时实际小时 <5 同理),
与 backfill 修复同口径。

### 反例自测(真实输出)
命令: `/Users/linhuichen/code/trade-data/.venv/bin/python scripts/tests/test_132_morning_slot.py`
```
[PASS] morning_slot(0200, 02:00) — 02:00 整点正常启动=凌晨槽(基准语义)
[PASS] morning_slot(0200, 03:30) — 02:00 槽唤醒漂移到 03:30=仍凌晨槽(#132 核心修复)
[PASS] morning_slot(0300, 03:00) — BACKFILL_SLOT=0300(唤醒漂移)实际 03:00=仍凌晨槽
[PASS] morning_slot(0459, 04:59) — 宽限窗口内 04:59=仍凌晨槽
[PASS] morning_slot(0500, 05:00) — 窗口边界 05:00=不再凌晨槽(该有数据而没有=真故障须报)
[PASS] morning_slot(1750, 17:50) — 16:35 兜底槽漂移到 17:50=非凌晨槽(六源全败=真故障)
[PASS] morning_slot(2100, 21:00) — 21:00 兜底槽=非凌晨槽
[PASS] morning_slot(0200, 17:50) — env 残留 0200 但实际时点 17:50=非凌晨槽(按实际时点判)
[PASS] morning_slot(空, 03:00) — 无 env(手动/update_all)=保守非凌晨槽(不放过)
全部 PASS(9 项)
```
hkex 归一验证:`BACKFILL_SLOT=0205/0200/0300/0459→0200, 0500→0500, 1635→1635, 2100→2100` 全 PASS。

---

## ② self_heal 并发双通知

### 病灶与改动前后对照
- **改动前**(`scripts/self_heal.sh`): 直接调 `retry_failed_metrics.py`,无 flock —— 两个并发
  self_heal 可同时读到 n=2 → 双双跨阈值 → 发两次通知(实际每 15min 单轮、秒级完成不重叠,概率极低)。
- **改动后**: 复用仓内既有 `scripts/with_lock.py`(fcntl.flock,与 intraday_snapshot/update_all/
  turnover_backfill 同机制),`--nb`(非阻塞)包裹 retry 调用:
  ```bash
  "$REPO/.venv/bin/python" "$REPO/scripts/with_lock.py" --nb /tmp/trade_retry_failed_metrics.lock \
      "$REPO/.venv/bin/python" "$REPO/scripts/retry_failed_metrics.py" 2>&1 | tee -a ...audit.log || echo "⚠ ..."
  ```
  锁随进程退出自动释放,无残留锁风险。锁被占时 with_lock stderr 跳过标记会进 audit 日志。

### 互斥失败语义: 跳过本轮,不排队
理由: ①retry 是每 15min 一轮的轻量重采(秒级),锁被占=另一实例正在跑,本轮跳过让下一轮
(15min 后)再试即可——失败指标本就处于 error 态,晚 15min 无害;②排队阻塞反而会拖住
self_heal 的任务级 force-heal(它依赖 retry 结束后继续);③与仓内「重复跑跳过」惯例(update_all/
intraday_snapshot 均 --nb)一致;④flock 随进程退出自动释放,跳过不会造成永久锁。

### 反例自测(真实输出)
命令: `/Users/linhuichen/code/trade-data/.venv/bin/python scripts/tests/test_132_self_heal_mutex.py`
```
模拟结果: {'runs': 1, 'notifies': 1}
[PASS] 并发两实例只有一个进入 retry(runs=1)
[PASS] 通知只发生一次(notifies=1)
[PASS] 被跳过实例留 audit 标记(stderr 含 with_lock 跳过)
[PASS] 两实例均 exit 0(跳过非失败)
[PASS] 锁不残留(串行两轮都进, runs+2)
全部 PASS
```
另验证 self_heal `||` 分支链路(bash,pipefail):
```
链路1 rc=1 (期望 1: retry 失败被 pipefail 捕获 → || echo 接管)
链路2 rc=0 (期望 0: 锁被持锁进程占, --nb 跳过=exit 0,不误报)
self_heal 两条链路行为 PASS
```

---

## ③ 计数文件写失败静默漏报(最重要—— 一并修复「降噪制造新静默」同类)

### 病灶与改动前后对照
- **改动前**(`scripts/retry_failed_metrics.py` `_save_counts`): 写失败**仅打日志不抛** →
  计数永远写不进 → 连续失败永远到不了阈值 3 → 永久静默(正是 #131 要修的病灶同类:
  counter 写失败 = 防静默机制本身静默)。
- **改动后**:
  1. `_save_counts` **fail-loud**: 移除 try/except,写失败直接抛 → main 捕获置非零退出,由
     self_heal.sh 的 `|| echo "⚠"` 分支接管(自验确认链路: self_heal.sh 顶部 `set -uo pipefail`,
     管道中 retry 非零 → `|| echo` 触发 → audit 日志留「失败」标记)。
  2. 新增 `_notify_count_file_write_fail`: 写失败本身触发**独立告警**(notify.py,tier warning,
     dedup-key `retry_fm_count_file_write_fail` 6h 窗口)。用 notify 而非仅 audit 日志的理由:
     ①「latest.md 沉默≠无告警」(教训 L46)——audit 日志一行无人主动查=仍静默;②写失败=#131
     防静默机制本体降级,值得直达人;③数据级失败仍由内存计数在达阈值瞬间发 `_notify_repeat_failure`
     (不依赖写盘),不丢数据告警,故只给 warning 不需 SEVERE;④6h dedup 对齐 with_lock 排队超时
     (P2 降噪)惯例,持久故障最多 ~2-4 封/天,防轰炸。
  3. **先通知后落盘**: 达标路径原为 `_save_counts → _notify_repeat_failure`,一旦写失败直接冒泡
     会把本轮的阈值告警一起吞掉=双静默。改为先 `_notify_repeat_failure`(依赖内存计数)再落盘,
     通知不再依赖写盘成功。
  4. **计数落盘收敛为仅末尾一次**: 原实现「达标路径循环内 + 末尾各写一次」,注释却写
     「末尾一次性落盘」(注释与实现不符)。核对结论=**改代码不改注释**: ①写失败须 fail-loud,
     循环内预写的失败会冒泡吞掉阈值通知(见 3);②收敛后少一次 IO、注释变真;③代价=通知后进程
     被杀致清零未落盘,后果仅下轮多一轮计数(非静默类风险),可接受。

### 反例自测(真实输出)
命令: `/Users/linhuichen/code/trade-data/.venv/bin/python scripts/tests/test_132_count_file_fail_loud.py`
```
[PASS] 可写目录持久化 — _load_counts={'a': 1, 'b': 3}
[PASS] 跨轮累加正确 — 第二轮后 _load_counts={'a': 2, 'b': 3}
[PASS] 只读目录 fail-loud(抛异常) — 抛出 PermissionError ... count.json.tmp
[PASS] 只读目录确实抛异常(不再静默) — 原实现仅打日志不抛=永久静默, 此为修复核心
[retry] 计数文件原子写失败(连续失败告警机制失效, fail-loud): [Errno 13] Permission denied ...
[notify] 计数写失败告警已发(dedup 6h)
[PASS] main 写失败置非零退出 — rc=1(self_heal `||` 分支会接管 → audit log 标记)
[PASS] main 写失败仍累加计数(内存), 返回前已告警
[PASS] 恢复可写后持久化正常 — _load_counts={'a': 6, 'b': 1}
第2轮未达阈值不通知 / 第3轮达阈值调通知(仅1次) / 达阈值清零已落盘(count.json={})
/ 清零暂歇后重新累计(第4轮不重复通知)
全部 PASS
```

---

## 同类错误面清单(§23.2:「写失败只打日志不抛」全仓静默点)

grep 全仓 `except Exception` 附近写操作,监控/告警链内的同类静默点(均为**写失败被捕获后仅
打印/日志,不抛不退出**)——与 #132 ③ 完全同族:

| # | 位置 | 写什么 | 失败处理 | 影响 | 处置 |
|---|---|---|---|---|---|
| 1 | `scripts/alert_denoise_rules.py` ~L206 R4 规则状态写 | staticdata 备份连续失败天数/分级去重 | `except Exception: pass`(吞得最干净) | R4 分级状态静默丢失→分级/去重错乱 | 建议后续修(已上线功能,§23.7 须用户确认) |
| 2 | `scripts/check_data_gap_alerts.py:1361 _save_state_atomic` | 采集缺口告警去重/基线状态 | 打日志不抛(注释自认「静默归零」) | 去重/基线静默归零→告警重复轰炸或漏基线 | 同上 |
| 3 | `scripts/detect_intraday_anomaly.py:242-247` | 盘中异动去重文件 | 打日志不抛 | 去重失效→异动告警重复轰炸 | 同上 |
| 4 | `scripts/feishu_missed_fetch.py:98 _save_cursor` | 补拉游标(消息去重位置) | 打日志不抛 | 游标丢失→重复补拉/漏补拉 | 同上 |
| 5 | `scripts/sensenova-proxy-healthcheck.py:98 _save_state` | 代理健康检查去重状态 | 打日志不抛 | 去重丢失→告警反复 | 同上 |
| 6 | `scripts/agent_inbox_watcher.py:265-317` | codex 镜像同步/清扫状态 | 打日志不抛 | 镜像同步去重位置丢失(有降噪器补拉兜底,影响较低) | 同上 |

非静默对照(已 fail-loud,不在清单内): `check_signals.save_signal_notified/save_subs_notified/
FADE`、`check_nt_signals.save_nt_notified`、`brief_push.save_state`、`alert_ack._save_atomic`
——均无 try 包裹,写失败抛异常→脚本 exit≠0→可被上层监控。

**结论**: 本任务只修点名的 3 条(含 #132 ③ 自身);其余 6 处同族静默点列出但不直接改——
均为已上线功能且多数属 #123/#131 告警降噪刚评审过的敏感链,按 §23.7 冻结契约动老功能须用户
拍板,故列入清单待用户定夺(建议排入后续「静默点 fail-loud 专项」)。

---

## 复现段(§23.5)

1. 重建凌晨槽判定:`/Users/linhuichen/code/trade-data/.venv/bin/python scripts/tests/test_132_morning_slot.py`
   (打真实 `_is_morning_slot`,now 参数注入时点,无 DB 依赖,结果见上)。
2. 重建并发互斥:`/Users/linhuichen/code/trade-data/.venv/bin/python scripts/tests/test_132_self_heal_mutex.py`
   (打真实 `with_lock.py` + 与生产同构的 retry 造影,结果见上)。
3. 重建计数 fail-loud:`/Users/linhuichen/code/trade-data/.venv/bin/python scripts/tests/test_132_count_file_fail_loud.py`
   (monkeypatch `COUNT_FILE` 指向临时可写/只读目录,打真实 `_save_counts/_load_counts/main`;
   `RETRY_NOTIFY_DRY_RUN=1` 时写失败告警走 notify.py --dry-run,不真发)。
4. hkex 归一验证:`BACKFILL_SLOT=0205/0200/0300/0459→0200, 0500→0500, 1635→1635, 2100→2100`(包导入调 `_current_slot`)。
5. self_heal 两条链路(bash pipefail): 链路1 retry exit=1→rc=1(|| echo 接管);
   链路2 锁被占→--nb 跳过→rc=0(不误报),见上「真实输出」。

## 改动文件清单
- `scripts/backfill_direct_metrics.py` — ① `_is_morning_slot` 按时点判定时点(新增 now 参数注入测试)、模块 docstring 同步
- `scripts/backfill_metrics.sh` — ① 注释同步槽位判定口径
- `app/collector/hkex_ccass_quarterly.py` — ① 举一反三:同一「02 前缀」时点漂移修复
- `scripts/self_heal.sh` — ② retry 调用经 `with_lock.py --nb` 进程互斥
- `scripts/retry_failed_metrics.py` — ③ `_save_counts` fail-loud + 写失败独立告警 + 先通知后落盘 + 落盘收敛末尾一次
- `scripts/tests/test_132_morning_slot.py` / `test_132_count_file_fail_loud.py` / `test_132_self_heal_mutex.py` — 新赠三份反例自测(真实代码)
- `docs/ops/132-monitor-residuals-20261001.md` — 本报告