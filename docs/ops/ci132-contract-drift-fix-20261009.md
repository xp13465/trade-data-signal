# CI 红修复: test_132 与 #241B 新契约漂移(2026-10-09)

## 结论一句话
main tip `6fcd82e6e` CI ⑧(`pytest -q scripts/tests/`)红,根因 = **老测试 `test_132` 编码了已被
`#241` 同族B波废弃的旧契约**(桩返回 None 被当假值);新源码逻辑正确,只改测试。修后全量
**608 passed, 2 skipped**(纯绿)。

## 1. 根因复核(不照抄派单结论,自行取证)
- 派单称 #241B 的改动 commit = `47fbc42d4`。**实际核实**:`git show 47fbc42d4 --stat` **不含**
  `scripts/retry_failed_metrics.py`;改本文件的真身是**补漏续跑 commit `192800415`**
  (`fix(#241同族B波续跑): 补漏 retry_failed_metrics.py`)。病灶描述与派单一致,只是 commit hash 归属需订正。
- 本地复现(venv python,pytest 9.1.1):
  `pytest -q scripts/tests/test_132_count_file_fail_loud.py` ⇒
  `1 failed, 4 passed`,失败点 `test_5_main_threshold_notify_then_reset`:
  `AssertionError: 达阈值清零已落盘, count.json={'a_fund_main': 3}`。
- 源码契约(`scripts/retry_failed_metrics.py`):
  - `_notify_repeat_failure(...) -> bool`:`sent = notify_sent(out); ... return sent`(未送达/异常
    ⇒ `return False`)。**rc 不可信**(notify.py 全出口恒 return 0),故用 `notify_sent` 输出判据。
  - `main()` 达标分支:`if _notify_repeat_failure(mid, n, today, msg): counts.pop(mid, None)` /
    `else: counts[mid] = n`。**送达才清零,未送达保留计数下轮重试**。
- 老测试 `test_5` 的桩:`lambda mid, n, date, msg: notify_calls.append((mid, n))` ——
  **`list.append` 返回 `None`(假值)** ⇒ 新代码判为「未送达」⇒ 不清零 ⇒ `count.json` 保留
  `{'a_fund_main': 3}` ⇒ 断言炸。**典型「桩不返回布尔被当假值」陷阱。**
- **判定:源码正确(要保留),测试编码旧契约 → 改测试。** 依据:新逻辑消灭了「先清零后
  fire-and-forget」在通道全挂时「达标告警永久丢失」的病灶(旧序 = 先落签记「已发」再通知且丢返回值)。

## 2. 改动(只动测试文件 1 个)
文件:`scripts/tests/test_132_count_file_fail_loud.py`
1. **`test_5` 桩体现新契约**:改为命名函数 `_notify_sent(...)` 先 `notify_calls.append(...)`
   **再 `return True`**(送达)⇒ 语义「达标→通知→清零暂歇」不变,仅前提多了「送达」;三处断言不变。
2. **新增 `test_6_main_threshold_not_sent_keeps_count`(新契约负向用例)**:
   桩 `_notify_unsent(...)` 返回 **False**(未送达)⇒ 第 3 轮达阈值后断言
   `count.json == {"a_fund_main": 3}`(**保留不清零**;旧代码必 FAIL),第 4 轮断言
   `notify_calls` 增至 2(**下轮重试,不静默丢**)且 `count.json == {"a_fund_main": 4}`。
   (走真实 `_save_counts/_load_counts` + tmp_path,是集成级证据;与同 commit 的
   `test_241_family_b_retry_metrics_20261009.py` 的 monkeypatch 级 test_05/06 互补。)
3. 头部 docstring 覆盖清单同步(第 5/6 条 + #241 契约说明)。

## 3. §23.3 举一反三:同类「桩不返回布尔」扫描清单
本轮改成「返回 bool、调用方按返回值分支」的函数(即 #241 家族)全集 + 测试桩覆盖核查:

| 新契约函数(返回 bool) | 所在文件 | 相关测试 | 桩是否返回布尔 | 结论 |
|---|---|---|---|---|
| `_notify_repeat_failure` | scripts/retry_failed_metrics.py | test_132(旧) | ❌ append→None | **本次修** |
| 〃 | 〃 | test_241_family_b_retry_metrics_20261009.py | ✅(真实/subprocess 替身) | 已覆盖(含负向 test_05/06) |
| `send_alert` | scripts/detect_intraday_anomaly.py | test_241_family_b_consign_20261009.py | ✅ 调真实函数(未 stub) | 无漂移 |
| `_channels_sent` | scripts/gen_daily_brief.py | 同上(test_10) | ✅ 调真实函数 | 无漂移 |
| fade 回滚(`_rollback_fade_notified`) | scripts/check_signals.py | 同上(test_12/13) | ✅ 调真实函数 | 无漂移 |
| schedule_monitor.sh / monitor_72h.sh | §241B shell 站点 | test_241_family_rc_sent_sweep / consign | N/A(shell,非 lambda 桩) | 无漂移 |

- 全仓 `grep 'setattr(..., lambda'`(55 个测试文件)逐条核查:唯一「桩不返回布尔、且被新契约
  按返回值分支消费」的 = `test_132::test_5`(已修);其余 lambda 桩返回 dict/tuple/False/None
  但对应函数契约未在本轮改 bool(如 `check_dedup`→False 是真实契约、`update_dedup`/`write_alert`
  →None 非布尔消费),不属本波漂移。
- 另有 `test_241_family_b_consign/rc_sent_sweep/retry_metrics/s06_fresh_sent_criterion` 四个
  `test_241_*` 新文件 = 本波自带的新契约测试(全绿),非老桩。

## 4. 自测(CI 同命令,逐字)
- 单文件:`pytest -q scripts/tests/test_132_count_file_fail_loud.py` ⇒ **6 passed in 0.93s**
- 全量:`pytest -q scripts/tests/` ⇒ **608 passed, 2 skipped in 91.93s**
  (修前 = 607 passed / 1 failed / 2 skipped;修好 1 条 + 新增 1 条 ⇒ passed +2、total +1,自洽)
- 零外发:pytest 链路全程不 spawn 真 notify.py(test_5/6 用 monkeypatch 替身 `_notify_repeat_failure`,
  根本不进 subprocess);零 R2 写;探针 static-only。
- red-before-green 判别力:新增 test_6 对旧代码必 FAIL(旧序无条件 `counts.pop` ⇒ 断言
  `count.json=={'a_fund_main':3}` 落空);同 commit 的 test_241 文件已记录旧语义 9 failed/2 passed。

## 5. 关联
- 根因 commit:`192800415`(#241 同族B波续跑,补漏 retry_failed_metrics.py)
- 契约:CLAUDE.md §18 L48(桩不返回布尔陷阱)/ §23.2 修 bug 三铁律 / §23.3 举一反三
- 家族报告:`docs/ops/241-family-rc-sent-sweep-b-20261009.md`