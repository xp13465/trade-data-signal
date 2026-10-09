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
| `check_data_gap_alerts.py:1465-1467` `_notify` rc → `ok` 门控 `state[key].last_fired=today` | ✅ 落签 → 当日抑制(**同后果, 未修**) | 上报待拍板(见 §7) |
| `overfit_monitor.py:1439` `send_notify` rc → `a["sent"]` | ⚠ 非落签, 仅 JSON 里「已发」标志不实(观测不实) | 上报观察项 |
| `retry_failed_metrics.py:113/150`、`nextday_gap_check.py:66/374`、各 `scripts/*.sh` 调用 | ❌ 只打印 rc / 委托 notify 自身 `--dedup-key`(notify 内部占窗已按 `and ok` / `_tier_send_ok` 正确守卫) | 不同类, 不动 |

> 结论: 真正「同后果(落签抑制)」的同类面除本任务外 = `check_data_gap_alerts.py` 一处;
> 其余属观测性/不同类。**未擅自扩大改动**(§23.7 已上线功能冻结, 见 §7)。

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
2. `overfit_monitor.py:1439` `send_notify` 的 `a["sent"]` 标志 rc 判定(观测不实, 非丢告警),
   同上需拍板。
3. `notify.py` 自身**不改**(冻结面)。

## 8. 恢复路径(§25 精神)

- 本改动为**代码改动**, 无删除动作。回退 = `git revert <本 commit>`(或 `git checkout <base> -- scripts/...)`。
- 新增 `scripts/notify_sent.py` 与测试文件可独立删除而不影响既有调用(仅 2 处 import 需同删)。