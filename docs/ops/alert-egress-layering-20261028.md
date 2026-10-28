# #321 告警出口分层（2026-10-28）

一句话：把「该进汇总/该降级」的告警从飞书**告警群（alert）**里分出去，让 alert 群只留需要人立刻处置的东西；
**信息不丢**——改由「report 群 + 邮件」双通道，或并入 23:25 当日摘要。

证据报告（调研原件）：`/tmp/alert-egress-plan-20261028.md`（259 行，含 8 天台账逐条归类）
任务书：`/tmp/task-alert-egress-impl-20261028.md`

## 1. 依据（可复核）

| 事实 | 数字 / 锚点 |
|---|---|
| 现状 alert 群噪音 | 11 条/天（8 天台账口径），其中 digest 1~2、routine 2、repeat 3~4、escalation 0~1 |
| digest 落 alert 群 | 改前 `notify.py:3386` 同位置 `feishu_group="alert"` |
| 恢复 fail-open 实际落群 | 改前吸收失败只打印、**不 return 也不改群** ⇒ `send_feishu(chat_key=None)` → `_resolve_feishu_chat_key` 命中 `[恢复]` → **alert 群**（STEP 0 实文核对） |
| repeat 判重失效 | `upload_r2.py` 两处窗口 21600s=6h，实测重复间隔 6h05m（10-26 17:19→23:24）~ 10h09m（10-27 07:23→17:32）⇒ 每次刚好过期 |
| 尺子没人挂 | 云上 `systemctl list-timers --all`/`crontab -l`/`.github/` 均无 `alert_noise_count.py` 调用；只有 2 个 pytest 引用 ⇒ 改退出码安全 |
| 「升级 critical」不会被误吸收 | `check_failed_units.py` 走 `--severe`；吸收块条件含 `not severe` ⇒ 物理不可达（`notify.py:1412`） |

## 2. 逐处改动

### A. 摘要 / 恢复 → report 群（邮件保留）

| 位置 | 改前 | 改后 |
|---|---|---|
| `notify.py:3386`（`flush_digest` 发送调用） | `feishu_group="alert"` | `feishu_group="report"` |
| `notify.py:1621` | `_EMAIL_KEEP_PREFIXES = ("[状态说明]",)` | 加 `"[告警·摘要]"`（只加串，`_EMAIL_GROUPS` 不动） |
| `notify.py:1469-1471`（恢复 fail-open 分支） | 无（落 alert 群、无邮件） | `feishu_group="report"` + `_grp="report"` + `_keep_email=True` |
| `notify.py:1659`（latest.md 镜像条件） | `severe or _grp=="alert"` | `or _keep_email`（恢复 fail-open 仍留痕） |

口径：摘要 = 当日全量告警的汇总播报，不是「当前故障」⇒ 与业务报告同订阅方；邮件必须留（§23.10 双通道同源）。

### B. 持续故障升级 → 并入当日摘要

| 位置 | 改前 | 改后 |
|---|---|---|
| `schedule_monitor.sh:497-514`（`_active_escalate` 子进程） | `--severe` 直发 | `--digest-only --from-prefix "[告警]" --result-file <tmp>` |
| `schedule_monitor.sh` 判定 | 只看 rc | 读 `--result-file` 的 `status`；`sent`/`digested`/`suppressed` 都算已处置（`digested` 不进 `_ALERT_MAIL_COUNTER`），`last_escalated` 照记；其余下轮重试。`suppressed` = notify 24h 去重窗判定「窗内已发过」（monitor 状态文件丢/回滚而 dedup 台账仍在时才会出现）⇒ 同样算已处置，否则每 15min 重试、连续 24h（96 轮）刷日志且一封都发不出 |
| `notify.py:385/1445` | 无 | 新 reason `escalation_digest_only`；`category="escalation"`（按 subject 是否含升级标记判定） |

硬边界：`severe=True`（真故障）永不吸收；摘要链路不可用/append 失败 ⇒ fail-open 直发 alert 群。

### C. 尺子 `alert_noise_count.py` 三态退出码

| 位置 | 改前 | 改后 |
|---|---|---|
| `:98` docstring | 「永远 exit 0」 | 0=PASS / 1=FAIL / 2=测不了 |
| `:128` | `Path(__file__).resolve().parent.parent` | `.absolute()`（不穿透 `scripts` symlink，防默认台账落到另一棵树 ⇒ 假 pass=null） |
| `:525-536` | `return 0` | `no_data 或 totals.pass is None ⇒ 2`；`pass False ⇒ 1`；`True ⇒ 0`；JSON 加 `rc` 字段 |
| `:377` 新增 `count_diverted()` | — | 同日 `group=="report"` 且 `noise_class ∈ {digest,recovery,escalation}` 的条数，**只打印+JSON，不参与 PASS** |

### D. 例行提示 / repeat

| 位置 | 改前 | 改后 |
|---|---|---|
| `r2_upload_skip_notify.sh:57` | `--feishu-group alert` | `--feishu-group report`（docstring 同步写明新口径，含「#264D 为何当时改 alert」的对照） |
| `signal_kelly_backtest.py:624` | 直发 alert | 加 `--digest-only`（吸收为 `category="routine"`，reason `routine_digest_only`）；`--feishu-group alert` 保留 = 吸收前置条件 + fail-open 落点 |
| `upload_r2.py:4414 / :4465` | `check_dedup(key, 21600)` | `86400`（两处 repeat 源；首报必达，24h 内不重复） |

### 测试

- 新增 `scripts/tests/test_254_alert_egress_layering_20261028.py`（16 条：C1-C6 尺子/ROOT/diverted，A1-A3 摘要与恢复，B1-B2 升级与 critical，D1-D5 例行/去重窗/源码形状）。
- 新增 `test_282_alert_denoise3_20261022.py::test_b_escalate_suppressed_by_24h_dedup_counts_as_handled`（1 条：24h 去重窗内已发过 ⇒ 算已处置，防 15min 重试风暴）。
- 改既有断言 4 个文件 5 处，均为**语义确实变了或原断言已不成立**、断言只增不减（逐项见交付报告）：
  - `test_282...::test_b_escalate_keeps_own_key_despite_r4`：升级从「3 通道直发」变「并入摘要」；断言由「3 次调用」改为「0 次直发 + 摘要 1 条 escalation + 命令含 --digest-only 且不含 --severe + 不占 dedup 窗」，判别力更强。
  - `test_alert_noise_count_20261028.py::test_missing_ledger_file_is_zero_and_warns`：rc 0→2（#321 三态契约）；原名改 `..._rc2`。
  - 同文件 `test_no_wall_clock_dependency`：该 fixture 噪音 5>3，rc 0→1；并加 `payload["rc"]` 断言。另在 schema 用例加 `rc`/`diverted` 字段断言。
  - `test_245_l2_budget_digest_20261010.py`：摘要 flush 的断言群由 `alert` 改 `report`（本单 A 的语义变更本身）。
  - `test_business_channel_declaration_20261017.py`：登记表两行正则随出口参数同步（r2 跳过 report / kelly 孤儿买加 `--digest-only`），变异用例第 8 项同步；守卫判据（必须显式声明渠道）不变。
  - `test_212_upload_onfail_loud_pytest.py`：`test_e_pre_change_source_static` 原先拿 HEAD 与工作区比形状，`upload_r2.py` 改动后恒红；加 `_channel_on_fail` 已在 HEAD 时跳过（保留原意图，防未来未提交编辑期假红），未放宽任何业务断言。

## 3. 实现预期 vs 证据（§5.7）

| 预期（可观测） | 证据用例 | 结果 |
|---|---|---|
| 摘要实际发送到 report 群，且邮件仍发 | `test_a1_...`（捕获 `chat_key` + 邮件 + 台账 group==chat_key） | 通过 |
| 恢复 fail-open 落 report 群且邮件保留（原落 alert） | `test_a2_...` | 通过 |
| 恢复常态仍并入摘要（不直发） | `test_a3_...` | 通过 |
| 升级同日多次只 1 条摘要、hits 递增、不直发 | `test_b1_...` | 通过 |
| critical（--severe）永不吸收 | `test_b2_...` | 通过 |
| 孤儿买并入摘要且标为 routine（不是 escalation） | `test_d1_...` | 通过 |
| 6h05m 前发过的 repeat：旧 6h 窗放行、新 24h 窗抑制；24h01m 放行 | `test_d2_...` | 通过 |
| 尺子 rc：PASS 0 / FAIL 1 / 无数据 2，JSON 同步 `rc` | `test_c1/c2/c3` | 通过 |
| ROOT 不穿透 symlink | `test_c4`（真 symlink 装载探针） | 通过 |
| report 群 8 条不参与判定、仍打印 diverted | `test_c5` | 通过 |
| 留在 alert 群的升级仍算噪音 | `test_c6` | 通过 |

### 预期效果（云上 10-26~28 台账逐类相减，非重跑）

| 日期 | 改前噪音 | digest | recovery | escalation | routine | repeat | 改后噪音（投影） |
|---|---|---|---|---|---|---|---|
| 10-26 | 11 | 1 | 1 | 3 | 2 | 4 | 0 |
| 10-27 | 11 | 2 | 2 | 2 | 2 | 3 | 0 |
| 10-28 | 3 | 1 | 0 | 1 | 0 | 1 | 0 |

- 真故障（real）不设上限，仍直发 alert 群：同一窗口 10-26/27 各 12 条、10-28 5 条 ⇒ 告警群总量由 23/23/8 降为 12/12/5。
- **最坏情况（摘要链路不可用 ⇒ escalation/routine fail-open 直发）**：每天回到 +1~3 条机制噪音，仍 ≤3 达标；digest 不因链路坏而多发（flush 失败只留 buffer）。
- 口径不回退：分类谓词/阈值一字未改（`ci` 用例 `test_c5/c6` 锁「report 群单列、alert 群口径不变」）。

**变异测试（5 个，全部按预期红；改后均已还原并核 md5 逐位相同）**
1. `flush_digest` report→alert ⇒ `test_a1` 红
2. 尺子 `return rc`→`return 0` ⇒ `test_c2`/`test_c3` 红
3. 白名单删 `[告警·摘要]` ⇒ `test_a1` 红（邮件丢失）
4. `upload_r2` 86400→21600 ⇒ `test_d3` 红
5. 恢复 fail-open 不改群 ⇒ `test_a2` 红

## 4. 回退（逐项一行）

| 改动 | 回退 |
|---|---|
| 摘要移群 | `notify.py:3386` 改回 `feishu_group="alert"` |
| 摘要邮件白名单 | 删 `_EMAIL_KEEP_PREFIXES` 里的 `"[告警·摘要]"` |
| 恢复 fail-open | 删 `:1469-1471` 三行 + `:1659` 的 `or _keep_email` |
| 升级并入摘要 | `schedule_monitor.sh` 子进程参数改回 `--severe`（`--result-file` 判定块同时回退） |
| 尺子三态 | `return rc` → `return 0`（其余改动可留） |
| 例行改群/吸收 | 脚本参数去掉 `report` / `--digest-only` |
| repeat 窗 | 两处 `86400` → `21600` |

## 5. 已知代价 / 残留（如实标注）

1. **摘要最坏延迟 ~24h**：23:25 之后产生的升级提醒要等次日 23:25 摘要（原为即时一封）。这是「并入摘要」的固有代价，已由 fail-open 兜住「摘要链路坏」场景。
2. **report 群会淹没摘要**：10-28 report 群实测 44 条业务消息/天（盘中信号 34）。缓解 = 邮件照发 + 尺子打印 `diverted`；长期若要独立「告警日报」群，需另开一单。
3. **尺子仍未挂定时任务**：本单只改语义，未挂 cron/systemd（避免撞盘后时点）。建议后续以 23:55 挂每日一次，FAIL 非零退出走告警。
4. **00:00 摘要残量**：★5a（批次2）已把「只在 ≥23:25 发」写进 `_flush_digest_locked`；本单未再动该逻辑。理论上若 23:25 那轮发送失败、次日 00:00 仍在窗口外 ⇒ 不会重发（无残留多发路径）。
5. **r2 锁跳过改 report 群后不带邮件**：`_EMAIL_GROUPS={"alert"}` 不变（本单禁改），report 群业务播报默认无邮件；该提示的三处留痕（deploy 日志 / skip 流水 / latest.md）全部保留。

## 6. 一致性（§22）

- 台账 `group` 与实际 `send_feishu(chat_key=...)` 同源：`test_a1` 用「台账末行 group == 捕获的 chat_key == report」做机检，防「声明 report 实际发 alert」的漂移。
- 尺子口径始终 `group=="alert"`；报告群机制消息只单列 `diverted`，不参与 PASS。
- 摘要 subject 前缀 `[告警·摘要]` 同时承担「邮件白名单键」与「人读标识」，两处引用同一字面量，改一处必须两处同步（`notify.py:1621` / `:3386`）。