# 告警量第二轮根因调研（RCA2）— 2026-10-27

> 触发：用户 2026-10-27 21:20「怎么告警依然这么多」。收敛目标：一天 0~3 条（`docs/ops/alert-convergence-plan-20261010.md` L4，2026-10-10 拍板）。
> 第一轮：`docs/ops/alert-noise-rca-20261015.md`。本轮回答「过了 12 天，六件套落了几件、量降到哪、剩余由哪层撑着」。
> 数据源：云上权威机 `122.51.111.173` 单本台账 `trade-data/data/alerts/alert_ledger.jsonl`（806 行，10-10 08:27 起）+ `suppression_ledger.jsonl`（2452 行，10-22 17:22 起）。
> 全程只读：云上零写、仓库零 commit/merge/push、无后台残留任务（未出现 moved to the background）。
> ⚠️ 口径替代：本机 mac 无 `timeout`/`gtimeout`（未装 coreutils），改用 Bash 工具自带 timeout 参数 ≤120000 秒级等价替代外层 `timeout 110`，每条命令均显式传入。

## 0. 摘要（结论先行）

**降噪确实在干活，但干的只是「频次」这一维：同一对象的重复轮询被挡掉约 8 倍（同期抑制 2452 vs 实发约 300）。而「哪些事件该发」和「哪个渠道发」两维没动 —— 所以总量原地踏步。**

- 最近 8 天（10-20~10-27）实发 **390 条，日均 48.8**；对比第一轮 10-10~10-15 的 268 条 / 日均 44.7 ⇒ **没有下降，略升 9%**。
- 五层结构：**A 业务订阅/报告流 47.0%（与第一轮 47% 一模一样，纹丝不动）**；B 同事件重复 19%→11.9%（域聚合的功劳）；C 机制噪声/常态日课 9%→**15.5%（涨 6.5 个点）**；D 真故障首报 13%→9.1%；E 其它 12%→16.5%。
- 六件套：**A/B/C/E/F 五件已真落地（有代码行号+运行产物），D 只落一半** —— 飞书分了四群，但**邮件仍只有一个收件人 `234058394@qq.com`，业务报告和故障告警混在同一邮箱**（`config/email.json` to 字段 + `notify.py` L1405 无条件发信）。
- 剩余量的构成：**每天固定日课 ~12 条 critical/notice（跨日零点重发 + 挂账对象每 24h 升级提醒 + 历史行改写常态事件 + kelly 冻结表 + 停摆巡检）+ 业务流 22 条/天（邮件侧）**。critical 免疫日预算（设计如此），所以这些日课每天必然到手机。
- 真该保留的真故障首报 30 条/7 天 ≈ **4.3 条/天**。也就是说「0~3 条」目标在结构上已接近临界：**把日课砍掉 + 业务流走邮件之外，才可能到 3 条以内；只继续加抑制窗永远到不了。**

## 1. ★1 最近 8 天实发量（10-20 ~ 10-27）

台账逐日（`alert_ledger.jsonl`，每封实际外发 1 行）：

| 日 | 总量 | critical | notice | warning | digest | subscribe | 告警群(alert) | 报告群(report) | 邮件封数 | 飞书条数 |
|---|---|---|---|---|---|---|---|---|---|---|
| 10-20 | 62 | 7 | 53 | 1 | 1 | 0 | 28 | 33 | 60 | 62 |
| 10-21 | 56 | 10 | 40 | 5 | 1 | 0 | 29 | 26 | 55 | 56 |
| 10-22 | 74 | 15 | 48 | 9 | 2 | 0 | 39 | 33 | 73 | 74 |
| 10-23 | 68 | 13 | 47 | 5 | 2 | 1 | 29 | 37 | 67 | 68 |
| 10-24 | 17 | 6 | 5 | 4 | 2 | 0 | 17 | 0 | 17 | 17 |
| 10-25 | 13 | 5 | 6 | 1 | 1 | 0 | 13 | 0 | 13 | 13 |
| 10-26 | 55 | 11 | 43 | 0 | 1 | 0 | 23 | 30 | 54 | 55 |
| 10-27 | 45 | 12 | 32 | 0 | 1 | 0 | 20 | 24 | 44 | 45 |
| **8天合计** | **390** | 79 | 274 | 25 | 11 | 1 | 198 | 210+ | 383 | 390 |

对照：
- 10-15 单日 83 → 10-27 单日 45（-46%）；但那是峰值日对普通日。
- **10-10~10-15 日均 44.7 → 10-20~10-27 日均 48.8（+9%）** ⇒ 以周为尺度看，量没有降。
- 10-24/10-25 是周末（业务流归零，只剩故障日课 17/13 条）⇒ **周末的 13~17 条几乎全是纯机制日课**，这是「结构性底噪」的直接读数。

手机可见估算（口径同第一轮 §5④，双渠道计）：
- **10-27：邮件 44 封 + 飞书 45 条 = 89 条消息**；其中「告警群」只有 20 条（critical 12 / notice 6 / digest 2），「报告群」24 条。
- 用户手机上的邮件通知会收到全部 44 封（含 24 封业务信号）——**这就是「感觉还是很多」的直接来源**。

## 2. ★2 最近 24h 逐条清单（10-26 21:20 ~ 10-27 21:15）

共 **55 条**：report 25 / alert 28（critical 15 + notice 11 + digest 2）/ follow 1 / agent_done 1。

按主题聚合 top 15：

| # | 次数 | 主题（归一化） | 时间点 | tier | 性质 |
|---|---|---|---|---|---|
| 1 | 9 | [盘中异动] N项异动 | 09:41,09:56,10:32,13:51,14:22,14:32,15:01,15:09,15:16 | notice | 业务流 |
| 2 | 4 | 【停摆】云上 unit 巡检发现异常(1 项) | 10-26 23:45, 10-27 00:00, 09:45, 21:00 | critical | **跨日+集合抖动重复** |
| 3 | 3 | 独立上传链产物与 R2 脱节(verify-r2 兜底补传) | 23:24, 07:23, 17:32 | notice | **域聚合未覆盖** |
| 4 | 3 | [状态说明] 监控结论异常(本轮无告警邮件) | 00:15, 10:00, 21:15 | notice | **元噪声（说"无告警"却发一封）** |
| 5 | 2 | R2 可能被异源覆盖(verify-r2 大量不一致) | 23:24, 17:32 | notice | 域聚合未覆盖 |
| 6 | 2 | [历史行改写] signal_daily 重写 ~1000 条 | 16:44, 18:01 | critical | **常态事件升 critical** |
| 7 | 1 | [买卖点信号] 主/辅/追买卖 | 09:27,09:43,10:22,10:47,18:31 | notice | 业务流 |
| 8 | 4 | ⚠️ 信号消失/变化 | 09:59,10:07,10:28,20:39 | notice | 业务流 |
| 9 | 1 | 【持续故障升级】nextday_gap_check | 09:30 | critical | 挂账 24h 提醒 |
| 10 | 1 | 次日买入计划伪跳空校验未完成 | 09:40 | critical | 真故障首报 |
| 11 | 1 | 【持续故障升级】overfit_monitor R2 锁连续 skip | 18:45 | critical | **挂账 33 天，每天提醒** |
| 12 | 1 | §22 三站一致性校验失败 | 23:35 | critical | 真故障 |
| 13 | 1 | [kelly] 冻结表缺失历史信号 12 个 | 02:13 | critical | 常态日课 |
| 14 | 1 | [kelly] 冻结表新增孤儿买 24 条 | 07:13 | notice | 常态日课 |
| 15 | 1 | [S06] 快照重生链路异常 rc=124 | 20:50 | critical | 真故障 |

同主题重复/循环：
- **同一 key 重复**：`failed_units_patrol` 4 次（跨日 00:00 + 集合变化）、`499ec8489d1f` 3 次、`621d8489dea6` 2 次、`history_overwrite:signal_daily:20261027` 2 次。
- **同一根因多路播报**（10-27 09:30~09:45，nextday_gap_check 一个故障）：`active_escalate`(09:30 critical) + `nextday_gap_check_fail`(09:40 critical) + `failed_units_patrol`(09:45 critical) + `[恢复]`(09:45 notice) = **15 分钟内 4 条，跨 2 个域 + 2 个豁免通道**。
- **元噪声**：「[状态说明] 监控结论异常(本轮无告警邮件)」24h 3 次——正文自述"本轮无告警邮件"，却本身走 notify 发出邮件+飞书。

## 3. ★3 五层分解（最近 7 天 10-21~10-27，同第一轮 §3 口径重算）

328 条，逐条归类（重叠处按最大主因；分类脚本规则见 §8 复现）：

| 分层 | 条数 | 占比 | 第一轮(10-15) | 变化 | 明细 |
|---|---|---|---|---|---|
| **A 业务订阅/报告流** | **154** | **47.0%** | 47% | **持平（0pt）** | report 150（盘中异动 40 / 买卖点+信号变化 ~70 / 每日速递 10 / 汪汪队 3 / 状态说明 4 / 其它）+ follow 4 |
| B 同事件重复播报 | 39 | 11.9% | 19% | **-7.1pt** | verify-r2 双 key 19（同 key 2+）、停摆 10、恢复 10→(归E)、cov_premium 7 |
| **C 机制噪声/常态日课** | **51** | **15.5%** | 9% | **+6.5pt** | kelly 孤儿买 6 + 缺失信号 8、active_escalate 14、history_overwrite 12、心跳 3、停摆升级 2、其它 |
| D 真故障首报 | 30 | 9.1% | 13% | -3.9pt | 计划任务异常 9、数据缺口 4、kelly 突变/停滞 3、过拟合 3、R2 一致性/verify_backup/deploy 3、S06 1、D1 同步 1、伪跳空 1 |
| E 其它 | 54 | 16.5% | 12% | +4.5pt | digest 10（每天 2 条）、恢复 11、warning 汇总 24（每天 3.4 条）、锁跳过 5、agent_done 4 |

逐日（A/B/C/D/E）：

| 日 | A | B | C | D | E | 合计 |
|---|---|---|---|---|---|---|
| 10-21 | 27 | 7 | 6 | 8 | 8 | 56 |
| 10-22 | 34 | 5 | 12 | 8 | 15 | 74 |
| 10-23 | 38 | 5 | 9 | 5 | 11 | 68 |
| 10-24 | 0 | 3 | 5 | 2 | 7 | 17 |
| 10-25 | 0 | 4 | 4 | 1 | 4 | 13 |
| 10-26 | 31 | 8 | 8 | 4 | 4 | 55 |
| 10-27 | 24 | 7 | 7 | 2 | 5 | 45 |

**一句话对照**：涨在 C（+6.5pt）和 E（+4.5pt），降在 B（-7.1pt）和 D（-3.9pt）；**A 层 47% 一分没动**。

补充口径证据：同期抑制台账 2452 条（10-22 17:22~10-27 21:15），实发约 300 条 ⇒ **抑制:实发 ≈ 8:1**。抑制构成：`active` 1338（挂账对象每 15 分钟轮询被挡）、`dedup` 1023、`budget` 40、`domain_aggregate` 31、`escalation_window` 10、`notice_budget` 7。
⚠️ 诚实标注：`active` 那 1338 条不是「本该外发的真告警」，而是「同一挂账对象每轮询一次就被挡一次」——8:1 说明的是**频次治理有效**，不能读成「挡掉了 8 倍真告警」。

## 4. ★4 六件套落地核查（读代码 + 运行产物，逐件定论）

### A 升级通道抑制窗 —— **已落地（升级档）；首报通道 window=0 按设计保留**
- `scripts/alert_denoise_rules.py:80` `ESCALATED_DEDUP_WINDOW_SECONDS = 259200`（72h），注释 L71-79 给出 24h/48h/72h 三档重放选值依据。
- `scripts/notify.py:3398-3431`：升级档用**通道自己的** `_esc_window`（`check_dedup(_esc_escalated_key, _esc_window)`，L3415），不再复用调用方窗口；窗口内抑制时**落回普通路径**（L3423）而非 `return 0` —— 修掉了第一轮点名的「升级档 suppress 直接中断首报」。
- `scripts/check_failed_units.py:506` 仍传 `--dedup-window 0`，但 L479-483 注释明确「只作用于首报通道」，升级档在 notify 侧判。
- **残余（实测）**：`stall_dedup_window(0) == 0`（`alert_denoise_rules.py:1384-1385`，云上模块实跑复核）——`failed_units_patrol` 属停摆键（`is_stall_key=True`），但调用方传 0 就**保留 0 = 不抑制**。结果：7 天 13 条（1.9/天），其中 **00:00 连续 5 天**。
- 结论：**升级档已修好；首报通道的「1 条/天 + 集合一变就发」是现存日课，未修（且有明确的"不吞真故障"设计理由，属需要拍板的取舍）。**

### B 判据事件化（#259）—— **已落地**
- `scripts/alert_denoise_rules.py:98` `ESCALATE_ROLLING_WINDOW_DAYS = 7`；`failed_units_patrol_state.json` 现存 `seen_dates` 7 项、`consecutive_days: 7`（有界，不再单调递增，第一轮是 8 且无界）。
- `data/alert_state.json`：**active 恒挂账 5 个**（第一轮 14 个）：`overfit_monitor|r2_skip_alert`（09-24 起，**已 33 天**）、`r2_consistency|exit!=0|1`、`r2_consistency|unit_exit!=0|124`、`nextday_gap_check|unit_exit!=0|2`、`conclusion_status|8e1a2a4c`。
- **残余**：`overfit_monitor|r2_skip_alert` 挂 33 天不消，被抑制 484 次，但每 24h 强制升级提醒一次（见 C 件）。

### C 故障域聚合层 / inhibition —— **已落地，但覆盖有 3 个实测盲区**
- 实现：`scripts/alert_denoise_rules.py:1018-1145`（`domain_of` / `domain_inhibit_judge` / 状态文件 `alert_domains.json`）；`scripts/notify.py:1316-1360`（gate，位于预算之前）。
- 运行产物：`data/alerts/alert_domains.json` → `r2_deploy` 域 **n_direct=28 / n_absorbed=302**（累计吸收 302 条），`kelly` 21、`data_gap` 6。**确实在工作。**
- **盲区 1（最大）**：`domain_of()` 用字面量匹配，**verify-r2 两个高频 key 实测返回 `None`**（云上模块实跑：`499ec8489d1f` → None、`621d8489dea6` → None）。判据只认 "R2 上传"/"双树"/"三站一致性"/"锁跳过"/key 前缀 `r2_`，而这两个 key 是 subject sha1，主题是「独立上传链产物与 **R2 脱节**」「**R2 可能被异源覆盖**」⇒ 不命中。**7 天 19~20 条完全不受域聚合约束。**
- **盲区 2**：`active_escalate|` 前缀被显式豁免（`DOMAIN_AGGREGATE_EXEMPT_PREFIXES`, L1039）；`history_overwrite:` 在 `domain_of` 里明确不并（L1063-1066）；恢复消息被 `_RECOVERY_PREFIX_RE` 豁免（`notify.py:1329`）。三类全部直发。
- **盲区 3**：域聚合只在「同域内」生效。10-27 09:30-09:45 一个 nextday_gap_check 根因 → `active_escalate`(None) + `gap_check`(first) + `unit`(first) + 恢复(豁免) = **4 条各发各的，跨域不聚合**。

### D 业务流分流 —— **部分落地（飞书分群已做；邮件未分流）**
- 飞书：四群 `alert/report/follow/agent_done`（`notify.py:11`、L659、L892 路由；L1482 调用方显式 `feishu_group`）。台账 group 字段确实记到 report/follow —— **飞书侧分流是真的**。
- **邮件侧没有分流**：`notify.py:1405` `email_ok = _send_email(...)` 在 `send_tiered` 里**无条件执行**（只要不是 `feishu_only`），`config/email.json` 只有单一收件人 **`to = 234058394@qq.com`**。所以 report 群的 24 条/天照样进同一个邮箱。
- 结论：**D 件只落了 50%** —— 这也是 A 类 47% 在「手机可见」口径下毫无下降的直接原因。

### E 预算+摘要 —— **已落地**
- `notify.py:1361-1400` 非 critical notice 预算 + 3 天 rollover 记忆（`ALERT_DIGEST_ROLLOVER_DAYS = 3`, `alert_denoise_rules.py:1182`）；`ALERT_NOTICE_BUDGET` 每类=1（实跑复核）。
- critical 结构性免疫预算：L1372 前置 `not severe`（物理不可达）。
- 运行读数：`alert_daily.json` `merged_in_digest` 10-27=2、10-26=18；`alert_digest.jsonl` 5 行；摘要正文自述「当日合并 7 条 / 8 条」。
- **残余**：**摘要本身每天固定 2 条**（23:30 当日 + 00:00 前日遗留），7 天 10 条。

### F 防复发四元组 —— **已落地**
- 登记表 `docs/ops/alert-checker-registry-20261015.md`（22.9KB，185 行）。
- 扫描工具 `scripts/alert_weekly_review.py:155` `scan_four_tuple()` + `--check-four-tuple`；调度器 `trade-alert-weekly-review.timer`（2026-10-16 装机，`docs/deploy/systemd-units-20260912.md:1660`）。
- 另加：停摆键/非停摆键双登记表（`alert_denoise_rules.py:1274/1294`）+ 防遗漏测试（扫全部 `--dedup-key` 字面量必须二者其一）。

## 5. ★5 为什么还这么多（主因判定）

**一句话：六件套修的全是「同一对象重复播报」（B 层，确实从 19% 压到 11.9%，域聚合累计吸收 302 条）；但「哪些事件算告警」（C 层日课）和「发到哪个渠道」（A 层邮件）两件从未动，而 critical 免疫预算 ⇒ 固定日课每天必然到手机。**

不是「A 类 47% 从来没人分流」的旧说法 —— 更准确是：**飞书分流了，邮件没分流**（D 件 50%）。也不是「C 类升级档还在日课」原样 —— 升级档 72h 窗已生效，**换成三个新的日课源**：

| 日课源 | 7 天条数 | 每条日频 | 为什么每天发 |
|---|---|---|---|
| `active_escalate`（挂账对象 24h 提醒） | 14 | 2.0/天 | `ACTIVE_ESCALATE_AFTER_HOURS=24` + `ACTIVE_REMIND_INTERVAL_HOURS=24`（`alert_denoise_rules.py:1579-1580`），overfit_monitor 挂 33 天、gen_daily_brief 连续失败 ⇒ 每天各 1 条 critical |
| `history_overwrite`（历史行改写） | 12 | 1.7/天 | `domain_of` 明确不并（L1063），index_daily 02:02 + signal_daily 16:44/18:00 每天固定重写 ⇒ 每天 1~2 条 critical |
| `kelly` 冻结表孤儿买/缺失信号 | 14 | 2.0/天 | 每天 1 条 notice + 周期性 critical |
| `failed_units_patrol`（停摆首报/跨日） | 13 | 1.9/天 | `stall_dedup_window(0)=0` + 集合抖动 + 跨日首报 |
| `schedule_monitor_heartbeat` | 3 | 0.4/天 | 监控器自身心跳超时 |
| digest 摘要 | 10 | 1.4/天 | 23:30 + 00:00 各一条 |

**新故障域进场？否。** 近 12 天新增 timer 6 个（10-22：daily-summary-supplement / freeze-orphan-cleanup / futures-backfill / lhb-backfill / public-fund-daily / rzhb-backfill）全是采集/补数据类，不直接产告警；没有新增 checker。但 **#282（10-22）新增的「停摆独立通道」把 failed_units_patrol 升成醒目的「【停摆】」直发**，属「为堵告警黑洞而变响」的改造。

**真故障首报占几条（应该保留的）**：30 条/7 天 = **4.3 条/天**（D 层）。
这个数字很关键：**目标 0~3 条/天 < 真故障首报 4.3 条/天**。说明「0~3 条」若要达成，除了砍 B/C/E，还必须把「计划任务异常 9 条/7天」「数据缺口 4 条/7天」这类原本该聚合或降级的真故障做分级（并非所有真故障都要即时推手机）。

## 6. ★6 / ★7 有无异常

### ★6 最近 24~48h 异常放大

| 类型 | 有无 | 证据 |
|---|---|---|
| 同一 key 反复 | **有** | `failed_units_patrol` 24h 4 次（23:45/00:00/09:45/21:00）；`499ec8489d1f` 3 次（23:24/07:23/17:32） |
| 任务失败重试循环 | **有（已自愈）** | `cov_premium_median` 重采失败：10-20 18:22~23:37 共 8 次 + 10-21 18:07~23:22 共 8 次，**45 分钟一轮连续 16 轮**，10-22 起消失 |
| 锁冲突 | **有（固定时点）** | `r2_upload_async_skip` 7 天 5 次：17:05×3（10-23/26/27）+ 00:10 + 22:50 ⇒ **17:05 与 update_all 固定撞车** |
| 跨日 rollover 重发 | **有** | `failed_units_patrol` 00:00 连续 5 天（10-23~10-27）；10-26 23:45 与 10-27 00:00 相隔 15 分钟两条同主题 |
| 重启后重发 | **无** | `journalctl` 近 48h 只有 3 次 unit 失败（r2-consistency 10-26 23:35、nextday-gap-check 10-27 09:41、s06 10-27 20:50），无重启循环；当前 failed unit 3 个 |
| 同根因多路播报 | **有** | 10-27 09:30-09:45 nextday_gap_check 一因 4 条（详见 §2） |

### ★7 降噪机制自己还在产噪吗（第一轮 §2.2④ 三例复核）

| 实例 | 现状 | 证据 |
|---|---|---|
| a. 升级通道抑制窗被关死（window=0） | **已修升级档；首报通道仍 0（按设计）** | `ESCALATED_DEDUP_WINDOW_SECONDS=259200`(L80)、`notify.py:3410-3431` 独立窗；但 `stall_dedup_window(0)=0` 实跑复核 ⇒ 停摆/跨日仍直发 |
| b. 跨日 rollover 重发 | **还在** | `failed_units_patrol` 00:00×5 天；digest 每天 23:30+00:00 两条 |
| c. L2 预算吞 severe | **已修** | `notify.py:1372` notice 预算分支前置 `not severe`（物理不可达），critical 永不入预算 |
| **新增 d（本轮发现）** | **元噪声** | 「[状态说明] 监控结论异常(本轮无告警邮件)」24h 3 次，正文自述"无告警邮件"却本身发出邮件+飞书 |
| **新增 e（本轮发现）** | **验活告警不受域聚合** | `domain_of` 对 verify-r2 两 key 返回 None（实跑），7 天 19~20 条，是当前单一最大重复源 |

## 7. 边界与口径差异（诚实标注）

1. **台账单出口已核实**：全云只有一份 `alert_ledger.jsonl`（`find` 确认）。`trade-data/scripts` 是 **symlink → `trade-data-signal/scripts`**（单份代码）；两棵树只是 data 目录不同，`REPO=trade-data`（所有 unit 实测），`GIT_REPO=trade-data-signal` 仅代码仓。signal 树 `data/alerts/latest.md` 停在 **10-09**，无 `alert_ledger.jsonl` ⇒ **无第二本台账、无双出口**。（先前 grep 到 "REPO=...signal" 是 `GIT_REPO=` 的子串误报，已用 `systemctl cat` 逐条纠正。）
2. **日志交叉验证不可靠**：10-27 全日志 grep「邮件已发送」只有 **8 行**（notify 的 stderr 不落各 launchd.log）⇒ 台账是唯一权威计数，日志只用于事件定性。第一轮 §1.1 的「日志口径低估」结论沿用。
3. **旁路出口**：`daily_summary_email.py` 直调 `smtplib`（不走 notify、不入台账），是**业务总结邮件非告警**；`brief_push.py` 直调 `notify._send_email`/`send_feishu`，经 `_ledger_depth` 重入计数**已入台账**（10-27 20:45 [每日速递] 在册）。
4. **三渠道**：`channels` 只有 email/feishu（telegram 未配置）；10-27 有 1 条 `email=False, feishu=True`（brief_push 的 feishu_only）。
5. **抑制台账起点晚**：`suppression_ledger.jsonl` 首行 **10-22 17:22**，只有 5.2 天；「抑制 2452」不能与 7 天实发直接比，本报告用**同期窗口**比（约 300 实发）。
6. **与第一轮口径差异**：①10-15 当日第一轮记 83，现台账为 **86**（后续补记/回填，非本轮变化）；②本轮 A 类含 follow 4 条（第一轮 follow 归 E 的「其它」）；③B 类用「同 key 第 2 次及以后」机械口径（第一轮用「完全同主题字符串」），故 B 数字不能逐位对比，趋势一致（降）。
7. **D 层「真故障」定性为主观**（按主题语义），边界与 B/E 重叠处按「消除该条所需动作」归类，与第一轮同法。
8. **抑制/实发 8:1 的口径**：见 §3 末段警示，active 类抑制是轮询去重不是真告警去重。
9. 本报告全程只读，未 commit；云上零写；无后台残留任务。

## 8. 复现命令（只读）

```bash
SSH='ssh -i /Users/linhuichen/tdsignal.pem -4 -o ConnectTimeout=10 ubuntu@122.51.111.173'
# 1) 逐日 x tier x group x channels
$SSH "python3 - <<'PY'
import json, collections
rows=[json.loads(l) for l in open('/home/ubuntu/code/trade-data/data/alerts/alert_ledger.jsonl') if l.strip()]
print(sorted(collections.Counter((r['ts'][:10],str(r.get('tier'))) for r in rows).items()))
print(sorted(collections.Counter((r['ts'][:10],str(r.get('group'))) for r in rows).items()))
PY"
# 2) 最近 24h 全量
$SSH "python3 -c \"
import json
rows=[json.loads(l) for l in open('/home/ubuntu/code/trade-data/data/alerts/alert_ledger.jsonl') if l.strip()]
[print(r['ts'],r['tier'],r['group'],r['source'],r['key'][:16],r['subject'][:90]) for r in rows if r['ts']>='2026-10-26 21:20']
\""
# 3) 抑制台账逐日 x mechanism
$SSH "python3 -c \"
import json,collections
S=[json.loads(l) for l in open('/home/ubuntu/code/trade-data/data/alerts/suppression_ledger.jsonl') if l.strip()]
print(collections.Counter((r['day'],r['mechanism']) for r in S if r['day']>='2026-10-21').most_common(40))
\""
# 4) 域映射实测（关键盲区证据）
$SSH 'cd /home/ubuntu/code/trade-data/scripts && python3 -c "
import sys; sys.path.insert(0,\".\")
import alert_denoise_rules as adr
print(adr.domain_of(\"499ec8489d1f\", \"[告警] 独立上传链产物与 R2 脱节(verify-r2 兜底补传)\"))   # -> None
print(adr.domain_of(\"621d8489dea6\", \"[告警] R2 可能被异源覆盖(verify-r2 大量不一致)\"))         # -> None
print(adr.stall_dedup_window(0), adr.is_stall_key(\"failed_units_patrol\"))                     # -> 0 True
"'
# 5) 邮件单收件人（不打印密钥）
$SSH 'python3 -c "
import json; d=json.load(open(\"/home/ubuntu/code/trade-data/config/email.json\")); print(d.get(\"to\"))"'
```

---
（报告完；未 commit。生成：2026-10-27，researcher 只读调研。）
