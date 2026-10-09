# #241 `check_s06_freshness.py` 落签判据同病根(rc 当 sent)修复报告

- 日期: 2026-10-09
- 任务: #241(`docs/pending-features-index.md` 第 241 行)
- 来源: #240 二次确认 reviewer `docs/ops/alert-denoise-batch2-rereview-20261009.md` P-3
- 同族先例: #240 F1(`docs/ops/alert-denoise-batch2-20261009.md`)
- 改动分支: `worktree-agent-aec6dd505e576120a`(feat,base commit `81d41bea9`)

## 1. 病灶与根因

- 旧判据: `scripts/check_s06_freshness.py:135` `sent_ok = proc.returncode == 0`。
- 为什么错: `scripts/notify.py` 的 `main()` **所有出口恒 `return 0`** —— 包括通用路径
  「全部渠道未发出」(`notify.py:2371`)与 `--tier` 分支 `defer_status='append_failed'`
  (`notify.py:2190`)。故 **子进程 rc 完全不含「告警送达/入队」的告知力**: 渠道全挂也 rc=0。
- 后果链: 通知全失败 → `sent_ok=True` → `_record_state` 落签 → 后续同状态被
  `_state_matches` 抑制 → **S06 快照过期告警静默丢失**(前端超覆盖期 fail-open 不拦截=档位静默退化)。

## 2. 修法(与 #240 F1 共用**唯一判据**)

- 新增 `scripts/notify_sent.py:notify_sent(output)` —— 「notify 子进程是否真发出/入队」的
  唯一实现, **不看 rc, 只解析输出文本里的真实路由结果**; fail-safe: 判不出 → False(不落签 → 下轮重试)。
  覆盖形态(逐字对齐 notify.py):
  | 形态 | 输出锚 | 判定 |
  |---|---|---|
  | 通用成功 | `[notify] 汇总：已发出 ...`(notify.py:2368) | True |
  | 通用全败 | `[notify] 汇总：全部渠道未发出（...）`(notify.py:2371) | False |
  | #196③ 升级档 | `[notify][196] 升级档路由完成：{...}`(notify.py:2334) | res 有 True→True |
  | `--tier` 分级 | `[notify][tier=<t>] 路由完成：{...}`(notify.py:2190) | res 有 True→True |
  - `--tier warning`: 真处理 ⇔ `deferred=True`(`defer_status ∈ {enqueued, suppressed}`);
    `append_failed` ⇒ `deferred=False` ⇒ **不得当发出**(否则漏告警)。
- `scripts/check_failed_units.py`(`_notify_sent`): 改为**委托**共享实现(符号保留, 行为不变,
  #240 已验收面零回归 —— `test_240::test_02d_notify_sent_parser` 7 例全过)。
- `scripts/notify.py` **一字未改**(冻结面 §23.7)。

## 3. 改动点(file:line)

| 文件 | 改动 |
|---|---|
| `scripts/notify_sent.py`(新) | `notify_sent(output)` 唯一判据 + 全形态 docstring |
| `scripts/check_failed_units.py:89` | 新增 `from notify_sent import notify_sent` |
| `scripts/check_failed_units.py:216-224` | `_notify_sent` 改为 `return notify_sent(output)`(委托) |
| `scripts/check_s06_freshness.py:46-47` | `sys.path.insert` + `from notify_sent import notify_sent` |
| `scripts/check_s06_freshness.py:143-148` | `out=(stdout+stderr)` + `sent_ok = notify_sent(out)`(替换 `rc==0`) |
| `scripts/check_s06_freshness.py:24-26 / 170-173` | docstring 同步(不再表述「notify 返回 0 后落盘」) |
| `scripts/tests/test_241_s06_fresh_sent_criterion_20261009.py`(新) | 判据判别力 + e2e 负控/正控 + red-before-green |

## 4. 自测证据(§18 L48 打桩铁律 + §5.4⑦ 同构对账)

打桩前提: 全 e2e 用例 monkeypatch `check_s06_freshness.subprocess.run`(notify 子进程整体打桩,
根本不 spawn)+ `ZeroOutboundTrap` 包裹; `trap.hits == []` 全程断言。

- ① 打桩生效自证: `test_00` 先证 `ZeroOutboundTrap` 确已武装(真触达出口即 raise + 计数 1)。
- ② **负控**(必修): `test_03` / `test_03b`
  - 「通用全渠道未发出」与「`--tier` append_failed」两种全失败输出(rc=0)⇒ **不落签**
    + 下轮**再次**调 notify(不吞真告警)。
- ③ 正控: `test_04` / `test_04b`
  - 「`--tier` enqueued / suppressed」(deferred=True)⇒ **落签**(含 coverage_end/n 内容)
    + 下轮同状态被抑制(不重发)。
- ④ **red-before-green**: 临时把 `sent_ok = notify_sent(out)` 回退为 `sent_ok = proc.returncode == 0`,
  跑 `test_03` ⇒ **FAIL**(`全渠道失败**不得**落签状态文件` 断言炸)——证明判据有判别力, 非假样本养绿。
  另有 `test_05`(旧 rc 语义 `lambda out: True` 复现 bug:落签 + 下轮被抑制)作为常驻判别力证据。
  静态锁 `test_02b`: 断言 `check_s06_freshness.py` 不再含 `returncode == 0` 且已用 `notify_sent(`。
- ⑤ 全量回归: `python3 -m pytest -q scripts/tests/` ⇒ **462 passed, 2 skipped**(92.39s), 含 #240 全 28 例。
- 运行器: `/Users/linhuichen/code/trade/.venv/bin/python -m pytest`(系统 python 无 pytest)。

复现命令:
```
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/test_241_s06_fresh_sent_criterion_20261009.py
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/
```

## 5. 同类错误面清单(§23.2 排查同类 —— 全仓 `grep` 判据「notify 子进程 rc 当 sent」)

| 位置 | 是否落签抑制(同后果) | 处置 |
|---|---|---|
| `check_s06_freshness.py:135`(#241) | ✅ 落签 → 当日抑制 | **本任务已修** |
| `check_data_gap_alerts.py:1465-1467` `_notify` rc → `ok` 门控 `state[key].last_fired=today`(`:1569` 抑制 / `:1573-1575` 落签) | ✅ 落签 → 当日抑制(**同后果, 未修**) | 上报待拍板(见 §7-1) |
| `sensenova-proxy-healthcheck.py:142-146` `_notify` rc → `ok` → `:230-232` 门控 `_save_state({"fired": True})` 落签 → `:221-222` `if fired:` 抑制重复告警 | ✅ 落签 → **此后每轮被抑制, 告警永不送达、永不重试**(**同后果, 未修**) | 上报待拍板(见 §7-2) |
| `check_monitor_heartbeat.py:101-105` | ⚠ 观测类: rc!=0 才报错, rc 恒 0 ⇒ 全渠道失败也印「已发起告警」(标记不实, 不落签) | 观察项 |
| `detect_intraday_anomaly.py:244/301` | ⚠ 观测类: `:301` 印「告警邮件已发」未看 rc(标记不实); `:244` 去重文件先写后发(降噪同日同标的本即只报一次) | 观察项 |
| `signal_kelly_backtest.py:343-348` | ⚠ 观测类: 印 `冻结缺失告警 rc={r.returncode}` 未看真实发送(标记不实) | 观察项 |
| `nextday_plan_generator.py:1247-1254` | ⚠ 观测类: rc!=0 才置 `notify_rc=1`, rc 恒 0 ⇒ 全渠道失败不置位(标记不实; 包装层 `nextday_plan.sh` 为兜底) | 观察项 |
| `overfit_monitor.py:1439` `send_notify` rc → `a["sent"]` | ⚠ 观测类: 仅 JSON 里「已发」标志不实(不落签) | 观察项 |
| `retry_failed_metrics.py:113/150`、`nextday_gap_check.py:66/374`、各 `scripts/*.sh` 调用 | ❌ 只打印 rc / 委托 notify 自身 `--dedup-key`(notify 内部占窗已按 `and ok` / `_tier_send_ok` 正确守卫) | 不同类, 不动 |

> 结论: 真正「同后果(落签抑制 ⇒ 真告警丢失)」的同类面除本任务外 = **两处**
> (`check_data_gap_alerts.py` + `sensenova-proxy-healthcheck.py`); 其余为观测类/不同类。
> **未擅自扩大改动**(§23.7 已上线功能冻结, 见 §7)。
>
> ⚠️ **复审修订(2026-10-09, 维度 6 FAIL → 本表补齐)**: 首版 §5 曾把同后果面误判为「仅
> `check_data_gap_alerts.py` 一处」, 漏了 `sensenova-proxy-healthcheck.py`(其 `:234` 注释
> 自证「参考 check_s06 同款契约」= 病根从 #241 这处抄过去)。观测类 4 处亦为复审补记。

## 6. 举一反三清单(§23.3)

- 同模式(rc 当 sent)消费点: 见 §5 表(全仓 `grep` 穷举)。
- 判据复用点: `notify_sent` 唯一实现 2 处消费(`check_failed_units` / `check_s06_freshness`),
  第二份实现漂移风险已消除(memory `repro-script-second-implementation-drift` 同精神)。
- 数据/前端展示位: **不涉及** —— 本改动只改监控脚本的**落签判据**, 不产生任何数据产物、
  不改前端、不动 R2/static-site, 故 §22 三步/§24 版本串无关。
- §21 算法公示: **不涉及**(未改任何算法/评分/权重/数值)。

## 7. 未做项 / 待拍板

1. **`check_data_gap_alerts.py` 同后果同类面(未修)**: `_notify` 用 `rc!=0` 判失败 →
   `ok=True` 时写 `data_gap_alert_state.json` 的 `last_fired=today` → 通知全失败当日同 key 被
   `if state[key].last_fired == today: skip` 抑制 = **当日真告警丢失**(与 #241 同后果)。
   - 证据: `scripts/check_data_gap_alerts.py:1457-1467`(判据)+ `:1573-1575`(落签门控)+ `:1569`(抑制)。
   - 修法同构: `_notify` 改判 `notify_sent((r.stdout or "")+(r.stderr or ""))`(它走默认 send 路径,
     输出「已发出」/「全部渠道未发出」, 共享判据直接适用)。
   - **为何未做**: 属另一 PRD 功能(已上线), 动其落签语义触 §23.7 冻结契约, 需用户确认后另派单。
2. **`sensenova-proxy-healthcheck.py` 同后果同类面(未修, 复审补列)**: `_notify`(`:142-146`)
   用 `rc!=0` 判失败(rc 恒 0 ⇒ 该分支死, 恒返回 True)→ `ok` 门控 `_save_state({"fired": True})`
   落签(`:230-232`)→ `:221-222` `if fired:` 抑制重复告警。
   - 后果: 商汤代理**持续异常** + 当轮通知**全渠道未发出**(rc 仍 0)→ `fired` 落盘 →
     **此后每轮被抑制, 告警永不送达、永不重试**。
   - 佐证: `:234` 注释自证「参考 check_s06 同款契约」(病根从 #241 这处抄过去)。
   - 修法同构: `_notify` 改判 `notify_sent((r.stdout or "")+(r.stderr or ""))`(走默认 send 路径,
     输出「已发出」/「全部渠道未发出」, 共享判据直接适用)。
   - **为何未做**: 同 §7-1, 属已上线功能, 动其落签语义触 §23.7 冻结, 需用户确认后另派单。
3. **观测类(5 处, 非丢告警, 仅标记不实)**: `check_monitor_heartbeat.py:101-105`、
   `detect_intraday_anomaly.py:244/301`、`signal_kelly_backtest.py:343-348`、
   `nextday_plan_generator.py:1247-1254`、`overfit_monitor.py:1439` `a["sent"]`。
   共性是「以 rc 判『已发』并打日志/写标志, rc 恒 0 ⇒ 全渠道失败也标『已发』」;
   均**不落签抑制**故不丢真告警, 列为观察项(是否收口同判据由主控/用户定)。
4. `notify.py` 自身**不改**(冻结面)。

## 8. 恢复路径(§25 精神)

- 本改动为**代码改动**, 无删除动作。回退 = `git revert <本 commit>`(或 `git checkout <base> -- scripts/...)`。
- 新增 `scripts/notify_sent.py` 与测试文件可独立删除而不影响既有调用(仅 2 处 import 需同删)。