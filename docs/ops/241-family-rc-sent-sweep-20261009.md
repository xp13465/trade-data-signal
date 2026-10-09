# #241 同族: 「用 rc 判 notify 是否真发出」全站点穷举 + 统一到 notify_sent()(2026-10-09)

> 分支: `feat/worktree-agent-af679d5bb8c12336c`(base = origin/main `8b06e0960`)
> 性质: B 级(跨 3 文件逻辑改动 + 新测试);**未动 notify.py 本体(§23.7 冻结)**;无前端改动 → 不动版本串。
> 上游: #240 F1(`check_failed_units`)/ #241(`check_s06_freshness`)已用 `scripts/notify_sent.py` 修同类;本批收口同病根剩余站点。

## 0. 病根(一句话)

`scripts/notify.py` 的 `main()` **所有出口恒 `return 0`** —— 含通用路径「全部渠道未发出」
(notify.py:2371 附近)与 `--tier` 分支 `defer_status='append_failed'`(notify.py:2190 附近)。
⇒ 子进程 `returncode == 0` **完全不含「告警送达/入队」的告知力**: 渠道全挂也 rc=0。

任何「按 rc 判 notify 真发出」的判据都失真。失真方向决定后果:
- 判据把「全失败」当「成功」→ **落签 / 置 fired** → 后续轮次被去重抑制 → **静默丢告警 / 永不重试**(本批 3 处);
- 判据把「成功」当「失败」→ 误升级(本批不改, 见 §3 Pattern B)。

修法(唯一实现 `scripts/notify_sent.py:notify_sent`,**不看 rc, 解析 notify.py 输出里的真实路由结果**;
fail-safe: 判不出 ⇒ `False` ⇒ 不落签 ⇒ 下轮重试)。本批三处全部委托它, 与 #240/#241 共用同一份判据
(杜绝第二份实现漂移, memory `repro-script-second-implementation-drift`)。

## 1. 穷举清单(核心验收点: 全 scripts/ + app/ 交叉扫; 本清单只覆盖 **rc 轴** —— **rc 轴无第 4 处同后果站点**,
「落签轴」另有 ≥4 类站点见 **§7**)

扫描口径: `grep -rln "notify.py" scripts`(含 .py/.sh)+ `grep -rn notify app` + 对「含 notify 且含 returncode」
的文件逐个人读。结论按后果分 5 类:

### Pattern A — rc 判 sent 且据此**落签/置 fired/抑制**(→ 静默丢告警)。**本批已修 3 处** ✅
| # | 文件 | 站点 | 后果 | 处置 |
|---|---|---|---|---|
| ① | `scripts/check_data_gap_alerts.py` | `_notify()`(修前 `returncode != 0 → False`) | 返回 `ok` 被 `run_alerts` 用于 `state[key].last_fired=today`(当日去重)⇒ 全渠道失败当日被抑制 = **当天失报** | ✅ 改判 `notify_sent` |
| ② | `scripts/sensenova-proxy-healthcheck.py` | `_notify()`(修前 `returncode != 0 → False`) | 返回 `ok` 被 `main` 用于 `_save_state({"fired": True})`;后续轮次 `if fired: 抑制` ⇒ **告警永不送达、永不重试** | ✅ 改判 `notify_sent`(抑制链随之解除) |
| ③ | `scripts/overfit_monitor.py` | `send_notify()`(修前 `returncode == 0`) | 返回 `ok` 写 `alerts[].sent` 观测标志(不触发抑制, 但误标「已送达」误导排障) | ✅ 改判 `notify_sent` |

### Pattern B — rc 判 notify「失败」用于 **return code / exit 2 交包装层升级**(同类 rc 失真, 后果不同)。**列出·未改** ⚠️
| 文件 | 站点(修前) | 后果 | 为何不动 |
|---|---|---|---|
| `scripts/check_monitor_heartbeat.py` | `if r.returncode != 0: … return 2` | rc 恒 0 ⇒ 「告警未发出 → 交包装层升级」分支**恒不触发** | 见下 |
| `scripts/nextday_gap_check.py` | `if r.returncode != 0: notify_rc = 1` | 同上(计划/剔除通知未送达不暴露) | 见下 |
| `scripts/nextday_plan_generator.py` | `if r.returncode != 0: notify_rc = 1` | 同上(「计划已生成但通知未送达」注释意在非 0) | 见下 |

**不动理由(不弱化现有判据 + 防误升级)**:
1. **同一 rc 失真, 但后果不是「抑制」而是「升级」**——不在 #241「落签沉默」事故面内, 属独立行为变更(会**新增**
   包装层 severe 告警), 触及已上线行为 → §23.7 需用户确认, 不擅自改。
2. **朴素换 `notify_sent` 会引入假升级**: notify.py **通用路径**的 dedup 抑制分支
   (`if args.dedup_key and not args.dry_run and check_dedup(...): return 0`)**不打任何输出** ⇒
   `notify_sent("") → False`。而这三处都带日/窗口级 `--dedup-key`(如 `nextday_gap_excluded_{today}`、`nextday_plan_{T}`),
   **当日内重跑会被 dedup 静默抑制** ⇒ 朴素换法会误判「未送达」→ 假升级。
3. 要正确修需先让 `notify_sent` 能区分「通用路径 dedup 抑制」——但 notify.py 在此分支**不打印**, 唯一出路是改
   notify.py 输出(**冻结面, 禁止**);或把「空输出 + rc==0」当「已抑制=成功」——那会**弱化 fail-safe 判据**
   (违反本批约束「不许弱化现有判据」)。⇒ **结构性卡住, 上报主控/用户决策**, 本次不擅动。

### Pattern C — rc 仅进**日志/痕迹文案**, 不作判据、不落签。**不动**
- `app/collector/runner.py:_notify`(`if r.returncode != 0: _notify_fail_trace(...)` —— 仅失败留痕分支, 不落签;
  且属 app/ 非本次 scripts/ 范围; 其 `--dedup-key` 同 Pattern B 的 dedup-抑制隐患)。
- `scripts/nextday_gap_check.py:_severe_alert` / `scripts/nextday_plan_generator.py:_severe_alert` /
  `scripts/signal_kelly_backtest.py`(冻结缺失告警)/ `scripts/retry_failed_metrics.py`(计数写失败 + 重采失败)
  —— 均只把 rc 打进日志/消息, 不据此落签或抑制。
- `scripts/detect_intraday_anomaly.py` / `scripts/feishu_missed_fetch.py:_notify_cursor_write_fail` /
  `scripts/alert_denoise_rules.py:_notify_r4_state_write_fail` / `scripts/pick_repo.py` /
  `scripts/check_data_gap_alerts.py:_notify_state_write_fail` / `scripts/with_lock.py:_notify_block_timeout`
  —— fire-and-forget, 完全忽略返回值(连 rc 都不看)。不属 rc 判定, 且均带 dedup-key; 不改。

### Pattern D — 进程内 `notify.send()`/`send_feishu()`, 用**返回值 res 判**(非 rc)。**已正确形态, 不动**
- `scripts/signal_kelly_snapshot.py:_send_notify`:`ok = res and any(res.values())` ✅(参考正解)。
- `scripts/upload_r2.py`(L1366 附近):进程内 `notify.send(...)` 后**不判 res 直接 `update_dedup`** ——
  **adjacent 病灶(「sent 判定缺失」而非「用 rc」)**:全渠道失败也会占 30min 窗。**列出·未改**:非本次 rc-pattern
  范围, 且修它=动 upload_r2 冻结链路, 需独立决策(见 §4 上报项)。
- `scripts/check_nt_signals.py` / `codex_notify_bridge.py` / `feishu_ws_listener.py` / `brief_push.py` /
  `gen_daily_brief.py` / `feishu_chat_hook.py`:进程内调 notify, 无 rc 判 sent, 不改。

### Pattern E — `.sh` 调 notify。**不属本模式**
deploy.sh / backup_db.sh / check_r2_consistency.sh / gold_night.sh / fund_nav_upload_async.sh / brief_push_wrapper.sh /
cloud_unit_patrol.sh / nextday_plan.sh … 这些 shell 里 `rc=$RC` 是**触发检查自己的 rc**(内嵌进告警正文),
**不是 notify 的 rc**;且多为 `2>&1 | tee` / `|| true` fire-and-forget, 不据 notify rc 落签。不属「用 rc 判 notify sent」。

### 结论(2026-10-09 独立审补正)
**rc 轴 = Pattern A(3, 已修)+ Pattern B(3, 结构性卡住已上报)+ Pattern C(仅留痕, 不改)——
「rc 轴」无第 4 处遗漏。**
⚠️ **但「落签轴」另有 ≥4 类站点(独立审给出反例, 见 §7)**:这些站点**不出现 rc**, 却同样
**先落签/占窗、通知 fire-and-forget**(或进程内 `update_dedup` 不判 res)⇒ 通道全挂时**告警丢失
且 state 已落签 ⇒ 条件持续期间永不重发**,与本批修的三处**同后果**。本批扫描口径只覆盖了 rc 轴,
遗漏了落签轴——故原先「无第 4 处『同后果』遗漏」的表述**不成立, 已更正为**:
「**rc 轴无第 4 处; 落签轴另有 ≥4 类站点(见 §7), 属动已上线行为, 已由主控另派 agent 处理**」。
另 Pattern D `upload_r2` 的落签点计数由「1 处」更正为 **≥6 处**(见 §7.5)。

## 2. 代码改动(3 文件)

| 文件 | 改动 |
|---|---|
| `scripts/check_data_gap_alerts.py` | 加 `from notify_sent import notify_sent`;`_notify()` 判据 `returncode != 0 → False` 改为合并 stdout+stderr 后 `notify_sent(out)`;rc 仅留日志。(`run_alerts` 既有门 `if ok or dry_run: 落 last_fired` 不变, ok 现在准确 ⇒ 失败不落签、下轮重试。) |
| `scripts/sensenova-proxy-healthcheck.py` | 加 `sys.path` + `from notify_sent import notify_sent`;`_notify()` 同上改判 `notify_sent(out)`。**抑制链随之解除**:`main` 既有 `if ok and not dry_run: _save_state({"fired": True})` —— 送达失败 ⇒ ok=False ⇒ 不落 fired ⇒ 下轮重试;恢复同理。 |
| `scripts/overfit_monitor.py` | 加 `from notify_sent import notify_sent`;`send_notify()` 的 `return r.returncode == 0, r.stderr` 改为 `return notify_sent(out), r.stderr`。 |

均**未动 notify.py 一行**;均复用唯一实现 `scripts/notify_sent.py`。

## 3. 自测结果(零外发)

新增 `scripts/tests/test_241_family_rc_sent_sweep_20261009.py`(11 用例)。

```
$ /Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/test_241_family_rc_sent_sweep_20261009.py
11 passed in 0.14s

# 相关既有测试防回归
$ … -m pytest -q test_240_alert_denoise_batch2 test_223_overfit_monitor_timeout \
      test_241_s06_fresh_sent_criterion test_184_notify_dryrun_gate test_132_notify_tier_dedup_pytest
55 passed in 0.65s
```

覆盖点:
- `test_00`:先证 `ZeroOutboundTrap` 武装生效(hits==1);
- `test_01`/`test_06`:sensenova / overfit 的 `_notify`/`send_notify` 判据(真发出→True;全失败/空输出→False;
  **rc 不参与**:rc=1+「已发出」→ True;dry-run 通用路径→True 保 `--self-test` 不退化);
- `test_02`/`test_04`(**负控=必修**):sensenova 告警全失败 /  data_gap notify 全失败 ⇒ **不落签/不落 fired**
  ⇒ **下轮必须重试**;
- `test_03`/`test_05`(正控):真发出 ⇒ 落签 ⇒ 次轮被去重抑制(不重发);
- `test_07`(静态锁):三处判据 = `notify_sent(out)`, 不再有 `returncode == 0` / `if r.returncode != 0` 当 sent;
- `test_08`/`test_09`(**red-before-green 判别力证据**):用旧 rc 语义(`notify 恒 0 ⇒ 判 True`)跑同一负控,
  **复现 bug**(全失败却落签/落 fired)⇒ 证明 `test_02`/`test_04` 有判别力(旧代码必 FAIL);
- `test_99`:断言计数下限(防假绿, §18 L49)。

**零外发证据(§18 L48)**:全部用例 notify 子进程整体打桩(`subprocess.run` 替身, 不 spawn)+ `ZeroOutboundTrap`
包裹, 收尾 `trap.hits == []`。**本次自测未产生任何真实外发**。判据/上下文均为逐字照 notify.py 打点行构造。

## 4. §23.3 举一反三(同模式别处 + 上报项)

- **同类 rc 失真已全列**(§1):A 修 3 / B 列出 3(结构性卡住)/ C 仅留痕不改 / E 非本模式;
- **adjacent 病灶(上报)**:`scripts/upload_r2.py` 进程内 `notify.send(...)` 后**不判 res 直接 `update_dedup`** ——
  全渠道失败也占窗(「sent 判定缺失」, 非「用 rc」)。**计数更正:非「1 处」,实为 ≥6 处**
  (L1368/1369/1376、L1761/1762/1770、L2150/2151/2159、L3669/3670/3684、L3699/3700/3714、L3727/3728/3739;
  另 L2057 仅 send 无 dedup=仅观测)。修它=动 upload_r2 冻结链路, 需用户/主控决策, 本次**未动**(详见 §7.5)。
- **上报项(需主控/用户拍板)**:Pattern B 三处(check_monitor_heartbeat / nextday_gap_check / nextday_plan_generator)
  的「告警升级 rc 判据」修复——需先解决 `notify_sent` 无法区分通用路径 dedup 抑制的结构性问题(见 §1 Pattern B 理由 2/3)。

## 5. 已知限制(诚实标注)

- `overfit_monitor.send_notify` 带 `--dedup-key`(24h 窗):同类型告警当日重跑被 notify 通用路径 **dedup 静默抑制**
  ⇒ 输出为空 ⇒ `notify_sent → False` ⇒ `alerts[].sent=False`。方向是 **fail-safe 的 under-report**(只可能少报「已送达」,
  绝不误报), 且 `sent`/`notify_error` 全仓无消费方(仅观测), 无实际影响。
- 判据只解析输出文本, 调用方须合并 stdout+stderr 后传入(本批三处均已合并)。
- **扫描口径局限(独立审补正)**:本批扫描只覆盖「**含 rc**」轴, 未覆盖「**不出现 rc、却先落签/占窗、通知
  fire-and-forget**」的落签轴 ⇒ **落签轴另有 ≥4 类同后果站点未纳入本批**(见 §7), 属独立行为变更,
  需主控/用户另决。

## 6. 关联

- 上游: #240 F1(`check_failed_units`) / #241(`check_s06_freshness`);判据唯一实现 `scripts/notify_sent.py`。
- 规范: §23.2(修 bug 三铁律: 根因修不逐文件补丁——判据只此一份)、§23.3(举一反三: §1/§4)、§18 L48(自测零外发)、
  §18 L49(断言计数)、§18 L50(探针 static-only: overfit 用 AST 抽取不 import)。

## 7. 落签轴遗漏(2026-10-09 独立审补正;行号本 agent 自核)

> **本轮不改任何代码。** 下列站点与本批修的三处**同一后果**(告警丢失/丢升级 + state 已落签 ⇒ 条件持续期间
> 永不重发), 但因**不以 rc 为判据**(而是「先落签/占窗、通知 fire-and-forget」或「进程内 update_dedup 不判 res」),
> 未被本批「含 rc」扫描口径命中。**修它们=动已上线行为(§23.7 冻结契约), 已由主控另派 agent 处理(have dispatched)。**
> 标签:「**同后果**」= 告警丢失/升级丢失且 state 已落签 ⇒ 持续期间静默不重发;「**仅观测**」= 只误标日志/标志, 无落签抑制。

### 7.1 `scripts/schedule_monitor.sh` — 最严重 · **同后果**
- `save_alert_state(alert_state)` @ **L2757**, 紧随 `if alerts:` @ **L2758**;notify `subprocess.run([... notify.py
  ... "--severe" ... ], check=False)` @ **L2767-2778**(notify 路径 L2769)。
- ⇒ **告警状态先落签、再 fire-and-forget 通知且 `check=False` 完全忽略结果**。通道全挂时**当晚计划任务
  异常告警彻底丢失, 而 alert_state 已落签** ⇒ 条件持续期间**永不重发**(本批修的三处同后果, 且此处覆盖面更广=
  全站计划任务监控总闸)。

### 7.2 `scripts/detect_intraday_anomaly.py` — **同后果**
- `filter_and_record` 先 `atomic_write_json(DEDUP_FILE, dedup)` 落 `data/anomaly_notified.json` @ **L244**;
  之后 `send_alert` 才 `subprocess.run([... notify.py ...], timeout=60, check=False, ...)` @ **L296-300**, 结果丢弃。
- ⇒ 盘中异动告警**先占当日去重窗、再 best-effort 发送**;发送全挂 ⇒ **该异动当日不再重发** = 静默丢告警。

### 7.3 `scripts/gen_daily_brief.py` — **同后果**
- `notify.check_dedup(dedup_key, 86400)` @ **L4038** → `results = notify.send(...)` @ **L4041** →
  `notify.update_dedup(dedup_key)` @ **L4044**(**仅由 `if not dry_run` 守卫, 不判 `results`**)。
- ⇒ 进程内 `notify.send` 返回 res 表示「渠道发出成功」, 但 **`update_dedup` 不看 res** ⇒ 全渠道失败仍**占 24h 窗**
  ⇒ 每日速递通知当日不再重发。属「sent 判定缺失」的同后果病灶(与 upload_r2 同类)。

### 7.4 `scripts/check_signals.py`(fade 告警)— **同后果**
- `filter_fade_alerts_intraday(alerts, date)`(def @ **L238**, 落 `data/fade_notified.json` @ **L252-271**)
  在 **L1007** 被调用;随后本次 fade 告警才进邮件/通知发送链。`_reset_fade_notified` @ **L1027** 只做「再现即清」。
- ⇒ fade 告警**先落 `fade_notified.json` 去重窗、再发送**;发送失败 ⇒ **当日同 key 不再重发** = 静默丢 fade 告警。

### 7.5 `scripts/upload_r2.py` — 落签点计数更正:**≥6 处** · **同后果**
- 6 处 `check_dedup → notify.send → update_dedup`(update_dedup **不判 send 的 res**), 行号:
  **L1368/1369/1376**、**L1761/1762/1770**、**L2150/2151/2159**、**L3669/3670/3684**、**L3699/3700/3714**、
  **L3727/3728/3739**。
- 另 **L2057** `notify.send(...)` 无配套 dedup = **仅观测**(不影响去重/抑制)。
- ⇒ 原报告 §4 记「adjacent 病灶 **1 处**」**不准确, 更正为 ≥6 处**(均由「send 后不判 res 直接 update_dedup」导致
  全渠道失败仍占窗)。修它=动 upload_r2 冻结链路, 需主控/用户决策。

### 7.6 处置说明
上述 5 类**均属动已上线行为(§23.7)**, 会改变通知/去重时序, **已由主控另派 agent 处理(have dispatched),
本批(commit 面)不含这些代码改动**。本批只做「rc 轴 3 处」的收口 + 落档。