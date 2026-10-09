# W2 — 告警收敛三态判据实施报告（路线 B，2026-10-10）

分支 `feat/alert-w2-tri-state-1010`（base = `6ad3c742e`）。关联：`docs/ops/alert-convergence-plan-20261010.md` §3、
独立调研 `docs/ops/notify-contract-survey-20261010.md`、#241 Pattern B / #240 F1。

## 0. 结论

3 个巡检站点（`check_monitor_heartbeat` / `nextday_gap_check` / `nextday_plan_generator`）此前用
**子进程退出码**判「notify 是否真发出」；而 `notify.py` 的 **CLI 13 个分支恒 `return 0`** ⇒ rc 零判别力。
现改判 **三态 `notify_sent.notify_state(out) -> "sent"|"suppressed"|"failed"`**：

| 三态 | 判据 | 站点动作 |
|---|---|---|
| `sent` | 与既有 `notify_sent()` 逐字同源的「真发出/真入队」判据命中 | 成功（不重试不报错） |
| `suppressed` | 命中 `notify.py` **既有抑制行的 stderr 输出**（5 类，行首锚定） | **成功且已知**（不重试不报错） |
| `failed`/未知 | 其余（全渠道失败 / 空输出 / 无法判定） | **保守**：站点回非 0（交包装层告警/下轮重试），沿用 #241「不吞真故障」 |

**零改 `notify.py`**（另一 implementer 正独立改它）；既有 `notify_sent()` 函数体**一字不改** ⇒ 存量 **9** 个调用方零回归（7 个 .py 直调：`detect_intraday_anomaly` / `overfit_monitor` / `check_s06_freshness` / `check_data_gap_alerts` / `retry_failed_metrics` / `sensenova-proxy-healthcheck` / `check_failed_units`；2 个 .sh 内嵌 python：`monitor_72h.sh:919`、`schedule_monitor.sh:2837`）。

## 1. 病灶订正（写回 plan，§2/§3 各一处）

- **plan §2（写点）**：原述「写点 = 通用汇总处 L2359/2368-2371 附近」**证伪** —— 那只是通用分支的打印；
  tier/agent-done/R4/R7/#196/flush 六分支与全部 10 个库直调脚本都不经过它。**订正为**：写点 = **3 个渠道函数**
  `send_feishu`/`send_telegram`/`_send_email`（CLI 13 分支 + 10 库直调脚本的共同必经点）。已改 plan §2 该行。
- **plan §3（静默）**：原述「dedup 抑制分支静默 `return 0`（不打任何输出）」**与代码事实不符** —— 抑制路径
  **有 stderr 输出（7 处）**；真正病灶 = **CLI 13 个分支恒 `return 0`，rc 无判别力**。故走**路线 B**。已改 plan §3 该段。

## 2. 5 类抑制行的行首锚点表（`scripts/notify_sent.py:_SUPPRESS_SIGNATURES`）

行首锚定 + 行内必需标记**同时满足**才算抑制行；**严禁裸 `suppress` 子串分类**（tier 成功行也含 `suppressed` 子串）。

| # | 锚点（行首前缀） | 行内必需标记 | notify.py 行 | 触发分支 |
|---|---|---|---|---|
| 1 | `[notify][dedup] suppress key=` | — | 1272-1273 | 通用/tier 的 `check_dedup` 窗口抑制 |
| 2 | `[notify][dedup] 同源抑制(` | — | 1779-1780 | `defer_warning` 4h 指纹层（返回 `"suppressed"`） |
| 3 | `[notify][tier=` | `dedup 窗口内 suppress` | 2183-2184 | `--tier` 窗口抑制（tier 名变 ⇒ 前缀+固定标记） |
| 4 | `[notify][r4] staticdata_backup_fail 21600s 窗口内已发, suppress` | — | 2232 | R4 升级档抑制 |
| 5 | `[notify][r7] 升级档窗口内已发, suppress` | — | 2274 | R7 升级档抑制 |
| 6 | `[notify][196] 升级档窗口内已发, suppress` | — | 2325 | #196 升级档抑制 |
| 7 | `[notify][agent-done] suppress` | — | 1348 | agent-done 5min 抑制 |

> 表列 7 处（=调研报告的 7 处），归为「5 类」：通用/tier `check_dedup`（1）、指纹层（2）、tier 层（3）、
> R4/R7/#196 升级档（4-6 同一措辞族）、agent-done（7）。
> **这些行措辞被冻结**：唯一文本消费者 `retry_failed_metrics.py:130` 按 `"dedup 窗口内 suppress"` 匹配
> notify.py:2183 那行 ⇒ 本波**未改其措辞**（也未碰 notify.py）。

## 3. 判据设计（反向用例是硬约束）

- 判定顺序 **sent → suppressed → failed**：
  - **反向用例（必测）**：`[notify][tier=warning] 路由完成：{... 'defer_status': 'suppressed'}` 行**同时含**
    `路由完成：` + `True` ⇒ `notify_sent` 为真 ⇒ **判 `sent`**（**不得**因行内 `suppressed` 子串误判 suppressed）。
  - 真抑制路径（`check_dedup`）只打抑制行、不打任何 `已发出`/`路由完成：` ⇒ `notify_sent` 假 ⇒ 落到 suppressed。
- 空输出 / 未知形态 ⇒ `failed`（保守）。`notify_sent()` 保持原判据不变（**9** 调用方零回归，口径见 §0）。

## 4. 3 站点改动 diff 摘要

| 文件 | 改动 |
|---|---|
| `scripts/check_monitor_heartbeat.py` | import `notify_state`；L96-107 rc 判据 → 三态（`sent`/`suppressed` ⇒ return 0；否则 return 2）；模块 docstring 退出码说明同步。 |
| `scripts/nextday_gap_check.py` | import `notify_state`；`_sync_r2_and_notify` notify 块 rc → 三态（非 sent/suppressed ⇒ `notify_rc=1`）；**举一反三**：`_severe_alert` fire-and-forget 日志把 `rc` 换为可读 `state`。 |
| `scripts/nextday_plan_generator.py` | import `notify_state`；`main()` notify 块 rc → 三态（非 sent/suppressed ⇒ `notify_rc=1`）；**举一反三**：`_severe_alert` 日志 `rc` → `state`。 |
| `scripts/notify_sent.py` | **只新增** 三态函数 `notify_state` + `_SUPPRESS_SIGNATURES` + `_is_suppress_line`；既有 `notify_sent()` 一字不改；模块 docstring 漂移行号订正（2368/2371→2359/2362、2190→2189、2334→2335）。 |
| `scripts/tests/test_alertchain_hardening_20261003.py` | `_run_heartbeat` 的 fake subprocess 由「空 stdout/stderr」改为**真实汇总行**（否则换三态判据后空输出 ⇒ failed ⇒ 用例必挂）。 |
| `scripts/tests/test_alert_w2_tri_state_20261010.py` | **新增**：notify_state 分类单元（含反向用例）+ 3 站点正/负控 + suppressed 分类 + red-before-green + 静态锁。 |

## 5. 改前 / 改后 rc 语义对照（为什么「原来恒 0 ⇒ 判不出」）

- `notify.py` 的 `main()` 13 个出口（L2171/2185/2199/2207/2217/2233/2257/2275/2293/2326/2344/2349/2372）
  **全部 `return 0`** —— 包括「全部渠道未发出」（通用路径）与 dedup 抑制分支。⇒ 子进程 `returncode` **恒 0**，
  对「送达 vs 抑制 vs 全失败」零告知力，旧判据只能当「永远成功」。
- 改后：站点读**输出文本**三态 ⇒ `failed`（旧 rc 也会=0）第一次被识别为非 0 ⇒ 交包装层告警 / 下轮重试。
- **red-before-green 实证**：用旧 rc 语义（`notify_state = lambda out: "sent"`）跑 cmh 负控（全渠道失败、rc=0）
  ⇒ `rc = 0`（复现「全失败被当成功」）；真判据下同场景 ⇒ `rc = 2`（见 test_12 / test_40）。

## 6. 自测（验收）

- **全量 pytest**：`/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/`
  ⇒ **624 passed, 2 skipped in 93.52s**（0 failed）。
- **新增/改动测试单跑**：
  - `test_alert_w2_tri_state_20261010.py` ⇒ **14 passed**；
  - `test_alertchain_hardening_20261003.py` ⇒ **9 passed**。
- **三态双向用例**：summarized 误判 sent 方向（tier res dict `defer_status=suppressed` + `路由完成：`+`True` ⇒ **sent**）、
  failed 误判 suppressed 方向（非抑制的同前缀行 `[notify][r4] 分级=info` / `[notify][r7] 连续失败分级=` ⇒ **failed**）
  均有负控（test_01 / test_12 / test_22 / test_32）。
- **零外发证据（§18 L48）**：全部用例经 `_zero_outbound.ZeroOutboundTrap` 包裹且**整体打桩 notify 子进程**
  （`subprocess.run` 替身，绝不 spawn）；`test_00` 先证 trap 武装生效；各用例收尾断言 `trap.hits == []`。
  ⇒ **本次自测未产生任何真实邮件 / 飞书 / Telegram / 告警**（R2/上传亦未触达：gap_check 用 `no_r2=True`、
  各处 subprocess 全打桩）。

## 7. 自验清单（规范对照）

- **§23.2 修 bug 三铁律 —— 同类错误面清单（同根因 = 「用 rc 判 notify 真发出」）**：
  - 本波 3 站点（heartbeat / gap / plan）⇒ 已改三态。
  - 另 3 站点（`check_data_gap_alerts` / `sensenova-proxy-healthcheck` / `overfit_monitor`）已在 #241 波改判
    `notify_sent`（rc 不参与）⇒ 本波无需再动（它们无「抑制 vs 失败」区分需求：全失败即重试，语义已对）。
  - `detect_intraday_anomaly` / `check_s06_freshness` / `check_failed_units` / `retry_failed_metrics` /
    `monitor_72h.sh` / `schedule_monitor.sh` 均用 `notify_sent`（rc 不参与）⇒ 保持。
  - ⇒ 全库 grep `notify_sent` 调用面已穷举核对，**无遗漏的 rc 判据站点**。
- **§23.3 举一反三 —— 同模式/同组件还被谁用**：`_severe_alert`（gap_check / plan_generator）是同族
  fire-and-forget notify 调用 ⇒ 已一并把日志 `rc` 换三态 `state`（不改行为，仅使日志真实）。
- **§23.4 团队协作**：已 scan `docs/pending-features-index.md`；与本模块（告警/notify）相关的在跑项为 W1
  （`feat/alert-l1-meter-1010`，改 notify.py）+ W3；**本波与 W1 无文件冲突**（本波零改 notify.py）；
  W3 复用本波契约（软依赖，见调研 Q4-C/Q5）。同模块占用已核对（worktree list：W1 = `agent-a34bf0abba0b5dde7`）。
- **§21 算法公示**：本波不涉评分/权重/匹配/分段等算法逻辑，**无公示点需同步**（不适用）。
- **§22 数据一致性**：本波不产生数据产物、不动 R2/static-site，**无 N 展示位同步面**（不适用）。

## 8. 回滚方式

- **单 commit revert**：`git revert <w2_commit>`（本波所有改动集中一个提交；`notify_sent.py` 新增函数、
  3 站点判据、测试、文档）。
- 无 env / 常量开关（三态判据是判据替换，非可切换档位）；回滚后 3 站点恢复「rc 判据」语义。
- 回滚不影响 `notify.py` / W1 / #240 / #241 既有机制。

## 9. 遗留 / 未做（诚实标注）

- `notify_sent.py` 内**函数体内注释** `(#196③ notify.py:2334 / --tier notify.py:2190)`（L69 附近）仍为旧行号 ——
  该行在 `notify_sent()` 函数体内，受「既有 `notify_sent()` 一字不改」约束，**本波未动**；模块 docstring 的行号已订正。
  建议后续 W1 合入后统一复核 notify.py 全量行号（W1 会平移行号，届时本表/docstring 行号需再核）。
- 建议主控 merge 时走 `scripts/main-merge.sh feat/alert-w2-tri-state-1010`（agent 只 push feat）。