# 告警降量 5 项改造 —— 实施规格（只读调研产出，2026-10-27）

> 上游依据：`docs/ops/alert-noise-rca2-20261027.md`（根因）、`/tmp/task-alert-design-20261027.md`（任务书）。
> 用户已拍板（不可改）：①**邮件只发告警和真故障**，业务报告（买卖点/盘中异动/速递/完成通知 agent_done/跟单）只走飞书报告群；②**目标 = 机制噪音 0~3 条/天，真故障不设上限**。
> 数据源：云上 `data/alerts/alert_ledger.jsonl`（807 行，2026-10-10 08:27 ~ 10-27 21:42）、`data/notify_dedup.json`、`data/alert_state.json`、`data/sentiment.db:history_overwrite_audit`、`data/alerts/alert_domains.json`。本地代码行号对应当前 main（457201a5e）。
> 台账口径：只记**实际外发**（至少一个真实渠道发出）的行（`scripts/notify.py:200-260`）；被抑制/并入摘要的条目**不落台账**。

## 0. 一页总表

| 项 | 改哪个文件:行 | 预期 X→Y（7 天台账口径） | 吞真故障风险 | 可机检 |
|---|---|---|---|---|
| ★1 邮件分流 | `scripts/notify.py:1405`（+L1404 白名单） | 邮件 54.9/天 → 29.0/天（−25.9；速递 2 封/天另计） | 低（唯一例外 [状态说明] 白名单） | 是（台账+单测） |
| ★2 停摆跨日重发 | `alert_denoise_rules.py:258` + `check_failed_units.py:784` + notify 新 `--escalation-only` | failed_units_patrol 13/7d → 8~9/7d（−4~5） | 中（升级档必须保住，见风险） | 是（纯函数单测） |
| ★3 verify-r2 两 key | `alert_denoise_rules.py:1079-1082` | 17/7d → 3 条直发（−14） | 低（只影响同域 2h 吸收） | 是（纯函数） |
| ★4 历史改写/kelly 降级 | `app/compute/signals.py:1448-1467` + `app/history_audit.py:305-344` + `signal_kelly_backtest.py:347-395/508-545` | 约 −4~5 条/天 | 中（index_daily 2062 类必须保住） | 是（回放+单测） |
| ★5 摘要合并+元噪声 | `notify.py:2890` + `schedule_monitor.sh:1091-1094/1177-1213` | 摘要 1.57/天 → 1.00/天；状态说明 ≤1/天 | 低（保 24h 提醒） | 是（纯函数） |
| ★6 目标口径 | `docs/ops/alert-convergence-plan-20261010.md:4` + 新计数脚本 | 口径可算：现基线噪音 22.0/天 | — | 是（脚本） |

**一句话结论（数据说话）**：5 项全做完，机制噪音从约 **22 条/天降到约 15 条/天**，**单靠这 5 项达不到 0~3 条/天**。缺口在 5 项之外（重采失败重复 3.1/天、warning 汇总 3.6/天、升级提醒 2.6/天等），完整算术见 §★6 与附录 A。

---

## ★1 邮件分流 —— 精确落点与风险面（第一优先）

### 现状
- 主路径：`scripts/notify.py:1405`
  `email_ok = _send_email(subject, body, dry_run=dry_run, from_prefix=from_prefix) if not feishu_only else False`
  → **邮件无条件发，不判群**。
- 群变量 `_grp` 在 `scripts/notify.py:1272` 已算出：
  `_grp = feishu_group or _resolve_feishu_chat_key(subject, from_prefix, severe)`
  L1272→L1405 之间只有四段逻辑（停摆通道 L1273-1294 / L2 预算 L1295-1315 / 域聚合 L1316-1360 / 通知预算 L1361-1397），全部**只读** `_grp`，**无重算/覆盖** ⇒ L1405 可直接用。
- 四群判定 `scripts/notify.py:889-907`（`_resolve_feishu_chat_key`）：`severe` → alert；主题含 `[告警|恢复|监控]` → alert；`[完成]` → agent_done；其余 → report。

### 全部发信路径（逐条）
| # | 位置 | 触发面 | 收件人 | 本次处置 |
|---|---|---|---|---|
| 1 | `scripts/notify.py:1405`（`send()` 内） | 所有业务/告警主路径、warning 批发 L2725、摘要 L2972、agent_done L1897 | `config/email.json` 的 `to`（**单个字符串**） | **按群收敛：仅 alert 群发** |
| 2 | `scripts/notify.py:943`（`_alert_feishu_config_missing`） | 飞书配置缺失兜底，独立调 `_send_email(..., from_prefix="[告警]")` | 同上 | **保留**（真故障，独立于群） |
| 3 | `scripts/notify.py:1489`（`send_to()`） | 订阅者定向推送（显式 `to=email`） | 显式收件人 | **保留**（订阅者主动订阅，不是告警噪音） |
| 4 | `scripts/notify.py:1086` / `:1162`（`_send_email` / `_send_email_core`） | 底层实现（L1181-1203 有台账包装） | — | 不改 |
| 5 | `scripts/daily_summary_email.py:1575`（直连 `smtplib.SMTP_SSL`） | 情绪速递（main）+ 20:25 补充速递（supplement） | `cfg["to"]`（**仅管理员**；`_resolve_recipients` L1531-1540，`config/subscriptions.json` 只用于正文个性化，不参与收件人） | **改走飞书报告群，停邮件**（见下） |
| 6 | `scripts/brief_push.py:182-199`（`push_email`） | 每日速递订阅者 | 订阅者 email | **保留**（订阅者） |

> 无 `send_many`/批量发送函数；warning 批发、摘要、agent_done 全部走 `send()` 同一出口，改一处即可覆盖。

### 群 → 是否还发邮件（近 7 天台账实测）
| 群 | 7 天条数 | 内容 | 改后是否发邮件 |
|---|---|---|---|
| alert | 199 | 告警/恢复/监控/摘要/预警汇总 | **发** |
| report | 183 | 盘中异动 47、盘中实时·买卖点信号、买卖点信号、汪汪队、每日速递、订阅 + `[状态说明]` 4 | **不发**（`[状态说明]` 例外：发） |
| follow | 5 | 明日买入计划 | **不发** |
| agent_done | 4 | `[完成] update_all Nmin` | **不发** |

- 邮箱通道覆盖：近 7 天 391 行里 **384 行 `channels.email=true`**（= 54.9/天）；改后只剩 alert 群 199 行 + `[状态说明]` 4 行 = 203 行 ≈ **29.0/天**，比现在 **−25.9/天（−47%）**。另每日 2 封情绪速递走 smtplib 不入台账，改后归零。
- 单日实测（10-27）：45 条消息、44 封邮件、45 条飞书 → 改后约 **23 封**（alert 群 20 + 报告群里的 [状态说明] 3）。
- 飞书零损失：391/391 行 `channels.feishu=true`（report/follow/agent_done 192 行全部有飞书通道）。

### 反例扫描（群 ≠ alert 但其实是真故障）
近 7 天 report/follow/agent_done 共 **192 条**逐条扫主题族：
- **唯一非业务项 = `[状态说明] 监控结论异常(本轮无告警邮件)` 4 条**。它是「监控自判异常、但本轮没有任何告警邮件」的兜底可见性（#309 F2，`scripts/schedule_monitor.sh:1177-1213`），**属真故障通道 → 必须保留邮件**。
- 其余 188 条全是业务播报：盘中异动 47、盘中实时·买卖点（多族合计约 77）、买卖点信号、汪汪队、每日速递、明日买入计划、`[完成] update_all`。
- **未发现**「用 report 前缀发上传失败」的伪装故障。

### `daily_summary_email.py` 结论
- 它是**业务报告**（情绪速递：恐贪/情绪/涨跌/成交额/板块/冰点；补充：期货/汪汪队/公募），收件人只有管理员 `cfg["to"]`，订阅者列表只用于正文 → **停邮件不影响外部订阅者**。
- 但飞书**没有对应产物**（`brief_push.push_feishu` 的 `[每日速递]` 是 AI 方向/区间，不是情绪速递）→ **不能直接停**，否则业务内容整块消失。
- 结论：把 `send_email(...)` 换成 `notify.send_feishu(subject, text_body, chat_key="report")`，两个入口都改：main（`scripts/update_all.sh:431-438`）+ supplement（systemd 单元 `trade-daily-summary-supplement` 20:25）。预期 **−2 邮件/天、报告群 +2 条/天**。

### `--feishu-only` 影响面
- 语义：调试用跳过邮件/Telegram（`notify.py:3144` help、`:3473` 传入）。改后它是生产常态的子集，**不冲突，保留**。
- 依赖「邮件必达」的调用方：`check_failed_units.py:_send_notify` 用 `--result-file` 的 `status ∈ {sent,digested}` 判送达（L521）；改后若某条只剩飞书，`send()` 的 `email_ok=False/fs_ok=True`，`status` 仍判 `sent`（至少一个真实渠道）→ **行为不变**，但需回归（证据用例 E1-3）。

### 改法（最小 diff）
在 `scripts/notify.py` L1404 前加常量/判定，L1405 加条件：
```python
# 2026-10-27 用户拍板：邮件只发告警和真故障；业务报告只走飞书报告群。
# [状态说明] 是「监控自判异常但本轮无告警邮件」的兜底，属真故障通道，保留邮件。
_EMAIL_GROUPS = frozenset({"alert"})
_EMAIL_KEEP_PREFIXES = ("[状态说明]",)
_email_wanted = (_grp in _EMAIL_GROUPS
                 or str(subject).lstrip().startswith(_EMAIL_KEEP_PREFIXES))
email_ok = (_send_email(subject, body, dry_run=dry_run, from_prefix=from_prefix)
            if (not feishu_only and _email_wanted) else False)
```
- 不要改 `send_to()`（L1489）、不要改 L943、不要改 `_send_email` 实现。
- `subject` 在 L1398-1399 可能被加 `SEVERE_PREFIX`，但 severe 时 `_grp` 必为 alert，无影响；`[状态说明]` 非 severe，不会被加前缀。

### 预期 X→Y
- 邮件：54.9/天 → 29.0/天（7 天台账口径，另加速递 2/天）；10-27 单日 44 → 约 23。
- 飞书条数不变；报告群业务可见性不变。
- **注意：本项只降邮件，不降消息条数，不计入「机制噪音 ≤3/天」指标。**

### 证据用例
- E1-1 单测（monkeypatch `_send_email`/`send_feishu`）：
  `send(subject="[盘中异动] 1项异动", feishu_group=None)` → `email_ok=False, fs_ok=True`；
  `send(subject="[告警] X", severe=True)` → `email_ok=True`；
  `send(subject="[状态说明] 监控结论异常", feishu_group=None)` → `email_ok=True`。
- E1-2 回归 `check_failed_units._send_notify`：mock result JSON `status=sent, channels={email:false,feishu:true}` → 断言 `sent=True`。
- E1-3 上线后 24h 台账断言（云上只读）：
  `group in {report,follow,agent_done} 且 channels.email=true` 的行，subject 必须匹配 `[状态说明]`，否则 FAIL。
- E1-4 每日速递改飞书后：报告群能看到「情绪速递」主题；管理员邮箱不再收到（查台账 `source=daily_summary_email` 无 email 通道）。

### 风险 / 反例
- 吞真故障风险 = 某个真故障被路由到 report/follow/agent_done 且只靠邮件。7 天 192 条扫描无此情况；唯一例外已白名单。
- 未来新增非 alert 群的真故障：要么保证主题含「告警/恢复/监控」字样（会进 alert 群），要么加进 `_EMAIL_KEEP_PREFIXES`。机检兜底见下。

### 机检
- **可机检（是）**：脚本扫 `alert_ledger.jsonl`，断言非 alert 群的 `channels.email=true` 行 100% 命中白名单前缀；单测覆盖三种群。

---

## ★2 停摆通道跨日重发 —— 根因与最小改法

### 现状（根因已钉死）
- 发送点：`scripts/check_failed_units.py:786`（`_send_notify`），由 `scripts/schedule_monitor.sh:2851-2870` 每 15 分钟调用。
- 判定：`scripts/alert_denoise_rules.py:213-260` `failed_units_daily_judge`；**L258-259**：
  ```python
  if last_alert_date != today_str:
      return True, "daily-first"
  ```
  每天第一次观测到**非空、且与昨天完全相同**的集合 → 直接返回 True。
- `check_failed_units.py:506` 无条件传 `--dedup-window 0` ⇒ notify 通用去重不拦 ⇒ 每天 00:00 必发。
- **不是零点重置**：状态文件 `data/failed_units_patrol_sig.json` 无按日清零逻辑；`last_alert_date` 只在真发出时写（`_write_sig_state` L446-449）。
- **不是集合抖动**：抖动抑制（L240-249）只在「24h 内同签名二次 added」时生效；这里 `added` 为空，走 daily-first。
- 台账证据：`failed_units_patrol` 7 天 13 条；其中 **00:00 连续 5 天**（10-23、10-24、10-25、10-27 的跨日同集合首报 + 10-26 的 72h 升级提醒），10-27 09:45/21:00、10-23 16:15/21:00、10-25 16:15 等是真正的集合变化。
- **耦合风险**：#196 升级档（`notify.py:3375-3448`，`_ESCALATE_CHANNELS`）与首报共用 `failed_units_patrol` 这个 key，且**只在调用 notify 时才有机会触发** → 简单「跨日不调用 notify」会把「持续 3 天升级 critical」的提醒一起杀死。

### 改法（最小，保升级）
1. 判定加一条（`alert_denoise_rules.py:258` 前）：
```python
if last_alert_date != today_str:
    _last_sent_sig = str(state.get("signature") or "")
    if _last_sent_sig and signature == _last_sent_sig:
        return True, "same-set-prev-day"   # 跨日同集合：不直发，转摘要 + 升级档
    return True, "daily-first"
```
（`signature` = 最近一次**真发出**的集合签名，见 `check_failed_units.py:434/446`。）
2. 调用方分流（`check_failed_units.py` 发送分支，L777）：
```python
if _reason == "same-set-prev-day":
    _send_notify(repo, subject, body, escalation_only=True)   # 只跑升级档，不直发
    _defer_digest(repo, subject, body)                         # 并入当日摘要（可见性）
    _write_sig_state(..., sent=True, reason=_reason, ...)      # 一天只做一次
    return _merge_d1_rc(1, _d1_rc)
```
3. `notify.py` 新增 `--escalation-only`：
   - argparse 加 `parser.add_argument("--escalation-only", action="store_true")`；
   - 在 `_ESCALATE_CHANNELS` 块**之后**、通用 dedup **之前**加：
     ```python
     if args.escalation_only:
         return _finish(0, "noop", "escalation-only: 仅跑升级判定, 未直发")
     ```
   - `_send_notify` 增参数拼 `--escalation-only`。
4. `_defer_digest` = 子进程 `notify.py <subject> <body> --defer-digest --digest-category unit --from-prefix "[告警]"`。
   ⚠️ **陷阱**：现有 `--defer-digest` 返回 `status="noop"`（`notify.py:3193`），而 `_send_notify` 只认 `{sent,digested}`（L521）⇒ 直接复用会被判未送达、rc=4 打出假 SEVERE。**不要复用它**；用独立 `subprocess.run` 接受 rc=0，或把 `--defer-digest` 的 status 改成 `digested`（与 gate 路径 L3467 对齐，推荐后者，顺带修一致性）。

### 预期 X→Y
- `failed_units_patrol` 直发：13/7d → 只保留真正「新增/变化」的 3~4 条/7d（如 10-23 16:15/21:00、10-25 16:15、10-27 09:45/21:00）；跨日同集合的 00:00 四条（10-23/24/25/27；另 10-22 01:30 疑为当天首轮）消失（**−4~5/7d ≈ −0.6~0.7/天**）；真正的集合变化与 2 条 72h 升级提醒保留。
- 摘要多 1 行/天（无新增独立消息）。
- 升级档不变：72h 窗内仍最多 1 封；「新增立即报」不受影响。

### 证据用例
- E2-1 纯函数：`failed_units_daily_judge({"signature":"S1","last_alert_date":"2026-10-26"}, "S1", same_items, "2026-10-27")` → `(True,"same-set-prev-day")`；signature 变 → `added`/`changed`；`last_alert_date=""` → `daily-first`。
- E2-2 dry-run：伪造状态跑两轮 `check_failed_units.py --dry-run` → 第二轮不直发、reason 正确。
- E2-3 升级不丢：伪造 `data/failed_units_patrol_state.json` 近 3 天出现 → `notify.py ... --dedup-key failed_units_patrol --escalation-only --dry-run` → stderr 出现 `[notify][196] ... 分级=critical`。
- E2-4 上线后：台账断言「key=failed_units_patrol 且 subject 含『云上 unit 巡检发现异常』」不再出现于 00:00-00:30（集合未变时）。

### 风险 / 反例
- **新增失败单元首报**：`added` 分支在 daily 分支之前，不受影响（L240-249）。
- **持续故障提醒**：`--escalation-only` 每天仍跑一次，rolling 7 天窗与 72h 升级窗继续推进。
- 若集合天天不变，以后只有 72h 升级提醒（这是设计目标：长期未清 = 升级，不是每天重复）。
- `--defer-digest` 的 `noop` status 陷阱是本项最容易踩的坑，必须写进验收。

### 机检
- **可机检（是）**：纯函数单测（4 种 reason）+ 台账断言（00:00 同集合直发为 0）。

---

## ★3 verify-r2 两个 key 补域映射

### 现状
- 域映射实现在 `scripts/alert_denoise_rules.py:1053-1097` `domain_of(key, subject)`，纯函数，返回域或 `None`（不聚合）。
- 匹配顺序（首个命中胜出）：①显式类别（数据缺口/伪跳空）→ ②R2/双树/部署链路 → ③其余单脚本域（snapshot/unit/kelly/fund_nav/collect）。
- subject 关键词表在 **L1079-1082**：
  `"R2 上传" / "R2上传" / "ssd.fx8.store" / "双树" / "三站一致性" / "锁跳过" / "计划任务异常" / "统一deploy" / "数据产物校验失败"`。
- 两个 key 的 subject：
  - `499ec8489d1f` = `[告警] 独立上传链产物与 R2 脱节(verify-r2 兜底补传)`
  - `621d8489dea6` = `[告警] R2 可能被异源覆盖(verify-r2 大量不一致)`
  → 都不含上述关键词，`domain_of` 返回 `None`（云上实跑已复核）。
- `data/alerts/alert_domains.json` 是**状态数据**（各域 `last_seen`/计数），不是映射配置；映射写死在代码里。
- **不是前缀问题**：这两个 key 是 subject 哈希（调用方没传显式 `--dedup-key`）→ 只能加 subject 关键词，加 key 前缀无效。

### 改法（最小）
`alert_denoise_rules.py:1079-1082` 的关键词条件追加两项：
```python
or "R2 脱节" in _s or "R2脱节" in _s or "异源覆盖" in _s
```
- 不要写裸 `"R2 " in _s`（会把「R2 上传」以外的无关主题也吸进来）。
- 位置保持在 ② 分支内（R2 域优先于 snapshot/kelly），符合预期。

### 预期 X→Y
- 7 天台账：`499ec8489d1f` 12 条 + `621d8489dea6` 5 条 = **17 条**（任务书估 19~20 条，实测 17 条，属 7 天窗口/口径差异）→ 域内首报（每 2h 首条直发）约 **3 条**，其余 **14 条并入 23:30 摘要**（**−14/7 天 = −2.0/天**）。
- `alert_domains.json` 的 `r2_deploy.n_absorbed` 预计 +14（`n_direct` +3）。

### 证据用例
- E3-1 纯函数：
  `domain_of("499ec8489d1f", "[告警] 独立上传链产物与 R2 脱节(verify-r2 兜底补传)") == "r2_deploy"`；
  `domain_of("621d8489dea6", "[告警] R2 可能被异源覆盖(verify-r2 大量不一致)") == "r2_deploy"`。
- E3-2 反例（不误吸）：
  `domain_of("x", "[告警] 历史行改写 index_daily 历史行被重写 1 条") is None`；
  `domain_of("x", "[数据缺口] index_daily 缺失") == "data_gap"`（显式类别优先，不被 r2 抢）。
- E3-3 回放：把近 7 天 alert 群 subject 逐条过新 `domain_of`，断言 r2_deploy 命中 17 条、吸收 14 条（±2）。

### 风险 / 反例
- 误吸范围：任何含 `R2 脱节/异源覆盖` 的告警都会归 r2_deploy 并受 2h 静默窗约束。但「首报」永远直发（`domain_inhibit_judge` 无跨日正式窗口），且跨日不吸收 → 不会吞掉首报。
- 若这两个 key 其实是两个独立故障，最多延迟到当天摘要（可见性不丢）。

### 机检
- **可机检（是）**：纯函数单测 + 7 天回放脚本断言命中/吸收条数。

---

## ★4 history_overwrite / kelly 常态事件降级

> ⚠️ 2026-10-28 复核：本段数字前提（4.3 万行/天、2062 条真异常、pending+2h）已被真实数据推翻，实施请看 docs/ops/alert-denoise-a4-research-20261028.md §6。

### 现状
- `[历史行改写]` 发送点：`app/history_audit.py:275-350` `_alert`。
  - critical 判据 **L305-308**：`critical = n_pure > 0`（`pure_lost` 为空才 notice；`pure_lost=None`（index_daily）恒 critical，L323）。
  - dedup key **L340-341**：`history_overwrite:{src_table}:{run_date}:{critical|notice}`；
  - 窗口 **L344**：critical 用传入的 1h/24h，notice 用 `max(window,86400)`。
- signal_daily 计算入口：`app/compute/signals.py:1448-1467`（重算前 snapshot → 重算 → diff → `audit_signal_daily_store`）。
- index_daily 入口：`app/collector/runner.py:142-143`、`app/collector/index_backfill.py:77-78` → `audit_index_rows_upsert`；`_INDEX_DEDUP_WINDOW = 86400`（`history_audit.py:43`）。
- kelly：`scripts/signal_kelly_backtest.py:347-395`（缺失历史信号，阈值 `FROZEN_MISSING_SEVERE_THRESHOLD=10`：≥10 severe、<10 notice，notice dedup 86400）；`:508-545`（孤儿买，notice，dedup 86400）。

### 为什么 signal_daily 每天 2 条 critical（根因，数据）
- signal_daily **每天两次全量重算**（约 16:44 / 18:00，docstring 自述设计行为）。
- 每次重算都是「先删后插」的**一个阶段**；按**单批次**配对：16:44 消失 442 / 出现 557 → 442 条在同批找不到配对 → `pure_lost=442` → critical。
- 但**跨批次**配对（云上审计表实测）：
  - 10-23：早批消失 442 vs 晚批出现 442 → **未配对 0**；
  - 10-27：442 vs 443 → **未配对 0**（+1 合法新增）。
  → **单批 `pure_lost` 是两阶段重算的假象，日级真实纯丢失 = 0**。
- **因此「调大阈值」是错解**：假丢失 442-563 与真故障在数量上重叠，靠数量分不开；正确判据是**日级净变化 / 宽限复核**。
- index_daily 反例（必须保住）：正常 **1 条/天**（值改写1）；**10-22 02:02 出现 2062 条**（值改写2062）= 真异常，降级后仍必须能发现。

### 附加发现（P0，超出本项但必须上报）：大批量改写被 24h dedup 静默吞掉
- 云上 `history_overwrite_audit` 显示每天 17:59 / 21:03 各有一批 index_daily 历史行改写，合计约 **2.4 万 + 1.9 万 = 4.3 万行/天**（接近整表）。
- 但台账里当天只有 02:02 的「**1 条**」critical；`data/notify_dedup.json` 证据：
  `history_overwrite:index_daily:20261027:critical → last_alerted=2026-10-27 02:02:35`
  → 02:02 的 1 条小改写占了 24h 窗，**17:59/21:03 的大改写全部被 suppress，台账零记录**。
- 抽样看改写内容：既有**修复**（`csi_000330` 前值 OHLC 全等于 close 的占位 → 后值真实 OHLC；`csi_000102` 6562→3367 纠正错值），也有 `-`→`nan` 的表示变化。**必须先诊断这批改写是计划内回填还是异常**，再决定阈值——不能直接降级掩盖。
- 这是「降噪吞真故障」的现网实例，建议单独立项（见附录 A1）。

### 改法
**(a) signal_daily：改成「宽限复核」日级判定（推荐）**
1. `history_audit.audit_signal_daily_store` 内，把本批 `pure_lost` 候选写入 `data/alerts/signal_pure_lost_pending.json`（key=`(date,index_id,signal)`，带 `first_seen`）。
2. 每次运行先复核 pending：若该 tuple 已回到表中 → 移除（说明是两阶段重算的中间态）；仍缺失且 `now - first_seen >= 2h` → 才计入 critical 的 pure_lost。
3. 效果：16:44 的 442 条进 pending；18:00 全部回归 → 清空；critical=0 → 发 notice（或只进摘要）。
4. 真丢失（删了不再回来）→ 2h 后仍缺失 → critical，判别力不降。
5. 需要给函数加可注入的 `now` 参数（单测冻结时间，避免 L51 类「当天绿次日红」）。

**(b) index_daily：按调用来源 + 数量级分键，不再让 1 条占掉全天**
1. `audit_index_rows_upsert` 增 `source` 参数（`runner` / `index_backfill`），`audit_index_row_partial` 传 `partial`。
2. dedup key 加来源/数量级桶：`history_overwrite:index_daily:{run_date}:{source}:{large|mid|small}`（`small<50`、`mid 50-999`、`large>=1000`）。
3. 分级：`index_backfill`（每日计划内回填）→ notice + 进摘要；`runner/partial` 且 `mid/large` → critical；`small` → notice。
4. `_INDEX_DEDUP_WINDOW` 保持 86400（同桶一天一条），不同桶互不占窗。

**(c) kelly 缺失历史信号：阈值保留，只改「常态重复」**
- 阈值 10 保留：18 天实测分布 `3,5,6×5,7,8×7,11,12,14`，正常最大 8，10 = +25% 余量；11/12/14 是真异常，继续 critical。
- notice 改为「缺失 key 集合变化才发」：`dedup_key = signal_kelly_frozen_missing_small:{md5(sorted(missing_keys))[:8]}`，窗口 86400 → 常态 8 个不变时不再每天一条。

**(d) kelly 孤儿买：只报新增**
- 现在发的是**累计总数**（台账：2→11→16→21→21→21→24），不是当天新增 → 改为「delta>0 才发」，正文写「新增 N 条（累计 M）」。

### 预期 X→Y
- signal_daily：2 条 critical/天 → **0 直发**（或 1 条 notice/天，取决于是否保留摘要外提示）。
- index_daily：1 条/天 critical → notice/摘要；**2062 类真异常仍 critical**；同时大回填批次不再静默（可见性修复）。
- kelly 缺失：notice 15 条/18 天 → 约 2-3 条/18 天；critical 3 条/18 天不变。
- kelly 孤儿买：7 条/9 天 → 2-3 条（有新增时）。
- 合计：约 **−4~5 条/天**。

### 证据用例
- E4-1 回放：用云上 `history_overwrite_audit` 近 7 天数据跑「宽限复核」算法，断言 signal_daily 日级 pure_lost=0（10-23、10-27 已有人工验证；10-26 单批 11 条需单独断言）。
- E4-2 反例：构造「早快照 500 行，晚快照少 500 行且无新增」→ **必须 critical**。
- E4-3 反例：构造 index_daily 2062 条值改写 → critical；构造 1 条 → notice。
- E4-4 现网 24h：17:59/21:03 批次必须出现在摘要或台账（不再被 02:02 占窗静默）。

### 风险 / 反例
- 宽限复核依赖「2h 内会再跑一次」；若第二次重算失败，pending 会在 2h 后的下一次运行判 critical（不会永远沉默）。
- 若某天真的发生「两阶段之间整表丢失且第二段没跑」，pending 复核仍会 critical。
- **不许**简单删掉 `[历史行改写]`：它是 2026-10-14 trades 全表被抹事故的防线（`history_audit.py` docstring L78-84）。

### 机检
- **可机检（是）**：回放脚本 + 单测（critical/notice 两态 + 冻结时间）。

---

## ★5 摘要合并 + 元噪声

### 现状（摘要两条）
- 发送点：`scripts/notify.py:316` `ALERT_DIGEST_HM = "23:25"`；`flush_digest` L2820 / `_flush_digest_locked` L2855。
- 触发条件 **L2890**：
  ```python
  if not (bool(stale) or (_hm_ok and bool(due) and _last_day < _today)):
      return {...}
  ```
  其中 `stale` = day != 今天（前日遗留），`due` = 今天。
- 调度：`scripts/schedule_monitor.sh` 每 15 分钟（:00/:15/:30/:45）尾部调 `notify.py --flush-digest`；`23:25` 后的第一个网格 = **23:30**（台账实测 23:30:xx）。
- 第二条 00:00 = **前日遗留 stale 分支**：23:30 之后（23:45、00:00 轮）吸收进 buffer 的条目 `day=前一日` → 00:00 命中 `bool(stale)` 直接发。
- 台账：近 7 天摘要 11 条（1.57/天）；**00:00 条不是每天都有**——10-24 23:30 之后无 10-25 00:00、10-25 23:30 之后无 10-26 00:00；有遗留时才有（10-27 00:00 "含前日遗留 2 条(r2 2)"）。
- 内容：00:00 那条只含 23:30 之后的遗留（1-2 条），与 23:30 不重叠，但属同一批事件的尾巴。

### 改法（摘要合并，最小一行）
`notify.py:2890` 条件改为「只在 ≥23:25 窗口发」：
```python
if not (_hm_ok and (bool(stale) or bool(due)) and _last_day < _today):
    return {...}
```
- 效果：00:00 不再单独发；前日遗留等下一个 23:30 并入（subject 自带 `(含前日遗留 N 条)`，可见性不丢）；条目保留不丢（发送失败不清理，契约不变）。
- **不建议**只把 HM 从 23:25 改 23:45：只能把窗口从 30 分钟缩到 15 分钟，23:45-00:00 的条目仍会在 00:00 发第二条。

### 现状（状态说明 / 元噪声）
- 发送点：`scripts/schedule_monitor.sh:329`（前缀）、**L1091-1094** `_conclusion_digest = md5(结论全文)[:8]`、**L1177-1213** `_conclusion_status_decision`、**L1250-1300** `_maybe_send_conclusion_status_email`（子进程调 `notify.py ... --from-prefix [状态说明]`）。
- 触发：结论非 OK ∧ 本轮告警邮件数=0 ∧ 同 digest 未 active ∧ 6h 复发冷却已过。
- 台账：**10-26 1 条；10-27 3 条**（00:15 / 10:00 / 21:15，三个不同 digest：`8797987a838b` / `5038ca2069b6` / `6eea3858fa55`）。
- **任务书「每天 3 条」需修正为**：「结论内容变化就发；10-27 是 3 条，10-26 只有 1 条」（诚实标注）。
- 为什么 3 次：结论文本含**每次运行的时间戳/耗时**（state `line_sample`：`nextday-gap-check(...09:26:00→09:41:00); r2-consistency(...23:20:00→23:35:04)`），每次文本都不同 → md5 不同 → 新 key → 立即发；发送时旧 key 被 pop（L1265-1268），所以 state 只留最后一条。
- 它算不算噪音：**是元噪音，但不是可删项**——它是「监控自判异常、但本轮没有任何告警邮件」的防假绿保险。

### 改法（保真降噪，不删）
1. **归一化签名**：`_conclusion_digest` 改为对「任务名 + Result + exit code」三元组取 md5，丢掉时间戳/耗时/计数：
   ```python
   def _conclusion_signature(concl):
       pairs = re.findall(r"([A-Za-z0-9_.-]+)\(Result=([a-z-]+), exit=(\d+)", concl)
       return ";".join(sorted(f"{n}|{r}|{e}" for n, r, e in pairs)) or concl.strip()
   ```
   `_conclusion_digest = md5(_conclusion_signature(concl))[:8]`。
   （若结论里还有「漏跑 X 个任务」类信息，把漏跑任务名也纳入签名。）
2. **加 24h 再提醒**：同一签名 `status=="active"` 且 `now - last_alerted >= 24h` → 再发（防止归一化后长期失声）。
3. 保留「本轮无告警邮件」门、6h 复发冷却、`CONCLUSION_STATUS_EMAIL_ENV` 开关。
4. 群保持 **report**（不改路由，避免被 alert 群预算/域聚合改语义）；邮件按 ★1 白名单保留。

### 预期 X→Y
- 状态说明：3/天 → **≤1/天**（同签名一天最多 1 条；签名变化才再发；持续异常每 24h 一条）。
- 7 天口径：4 条 → 1-2 条。
- 摘要：1.57/天 → **1.00/天**。

### 证据用例
- E5-1 纯函数：三段「任务集相同、时间戳不同」的结论 → 同一 digest。
- E5-2 反例：任务集 `{A}` → `{A,B}` → digest 变 → 发。
- E5-3 24h：同签名 active 25h → 发；6h → 不发。
- E5-4 摘要：buffer 塞「前日 2 条 + 当日 0 条」，模拟 00:00 → **不发**；模拟次日 23:30 → 发 1 条且 subject 含 `(含前日遗留 2 条)`。

### 风险 / 反例
- 归一化丢信息：只留 task/Result/exit，可能把「同一任务换了失败原因」当成同一签名 → 建议签名至少含 exit code；若结论正文有「原因」字段，纳入签名。
- regex 不匹配时 fallback 用原文（当前行为），不会静默消失。
- 摘要合并后前日遗留最多延迟 24h；若监控整体停摆，摘要本来就发不出，风险等同现状。

### 机检
- **可机检（是）**：纯函数单测 + 台账断言「同一结论签名 24h 内 ≤1 条」。

---

## ★6 目标口径落档 + 可机检的「噪音」定义

### 目标句逐字替换
文件：`docs/ops/alert-convergence-plan-20261010.md` **L4**
- 原文：`> 用户验收标准:**告警群即时消息 一天 0~3 条**`
- 新文（逐字，直接替换 L4）：
```markdown
> 用户验收标准（**2026-10-27 用户拍板改口径**）：**机制噪音 0~3 条/天，真故障不设上限**。
> 口径定义：机制噪音 = 飞书告警群（alert）里「非真故障首报」的消息（摘要、预警汇总、跨日重复、升级提醒、恢复留痕、常态提示、元状态）；真故障首报不设上限。
> 配套：邮件只发告警和真故障；业务报告（买卖点/盘中异动/速递/完成通知/跟单）只走飞书报告群。
```

### 「噪音」的可机检定义（能直接写进脚本）
**主口径（推荐，最稳）：发送时打标，统计时只数标**
1. `scripts/notify.py:_record_ledger` 增加可选字段 `noise_class`（最好由 `send()`/`send_tiered()` 透传）。
2. 各发送点显式标注（**未标注 = 真故障/业务，不计数**）：

| noise_class | 发送点 | 含义 |
|---|---|---|
| `digest` | `flush_digest`（notify.py:2972） | 当日摘要 |
| `warning_batch` | `flush_warning_batch`（notify.py:2725） | warning 汇总 |
| `repeat` | ★2 跨日同集合 / ★4 常态重复 / ★3 域吸收后的补发 | 同一事实重复 |
| `escalation` | `active_escalate|*` / `[告警] ...升级 critical` | 持续故障提醒 |
| `recovery` | `[恢复] ...` | 恢复留痕 |
| `routine_notice` | 历史行改写-提示 / kelly 常态 / 锁跳过 | 常态提示 |
| `meta_status` | `[状态说明]`（report 群，默认不计入 alert 噪音） | 监控自检兜底 |

3. 计数脚本规格 `scripts/alert_noise_count.py --date YYYY-MM-DD [--json]`：
```python
noise = [r for r in ledger(date) if r["group"] == "alert" and r.get("noise_class")]
real  = [r for r in ledger(date) if r["group"] == "alert" and not r.get("noise_class")]
print(len(noise), len(real))   # 验收只看 noise <= 3；real 不设上限
```
4. **交叉校验（防漏标）**：对未标注行按下面谓词回算，若某行命中谓词却未标注 → 输出 WARN 清单（不直接 FAIL，避免误伤）。

**交叉校验谓词表（近 7 天台账实测条数，作为回算基准）**
| 类 | 谓词 | 7 天条数 |
|---|---|---|
| digest | `tier == "digest"` | 11 |
| warning_batch | subject 以 `[告警·聚合]` 开头 | 25 |
| escalation | subject 含 `升级 critical` / `持续故障升级` | 18 |
| recovery | subject 以 `[恢复]` 开头 | 11 |
| routine | subject 含 `孤儿买` / `缺失历史信号` / `历史行改写-提示` / `锁跳过` | 21 |
| repeat | 同 `(tier, 归一化 subject)` 在 24h 内已出现过 | 70 |

> 归一化 = 去掉日期/时间/纯数字（保留任务名/单位名）。类别间可重叠（如 digest 行的 subject 也会撞重复），故上表合计 156 > 154，主口径打标时 `noise_class` 取单值互斥、以打标结果为准。⚠️ 该归一化会把「1项计划任务异常」的不同任务误并成同一签名 → 必须先修附录 A3（subject 带任务名），否则 repeat 会被高估、真故障会被误判成噪音。

### 当前基线（近 7 天台账，按上述主口径回算）
- 告警群 199 条/7 天（28.4/天）：
  - **噪音 154 条 = 22.0/天**
  - **真故障首报 45 条 = 6.4/天**（与 RCA「真故障首报 4.3/天」同量级）
- 噪音构成：repeat24h 68、warning_batch 25、escalation 18、routine_kelly 16、digest 11、recovery 11、lock_skip 5。

### 诚实结论：5 项做完到不了 0~3/天
| 步骤 | 变化 | 噪音/天 |
|---|---|---|
| 现状 | — | **22.0** |
| ★2 停摆跨日（−5/7d） | −0.7 | 21.3 |
| ★3 verify-r2（−14/7d） | −2.0 | 19.3 |
| ★4 历史改写 + kelly 常态（−27~29/7d，保守取 27） | −3.9 | 15.4 |
| ★5 摘要合并（−4/7d） | −0.6 | **14.8** |
| ★1 邮件分流 | 0（只降邮件） | 14.8 |

**剩余 14.8/天 的大头在 5 项之外**：
| 缺口 | 7 天 | 每天 | 处置建议（超出本批，需用户拍板） |
|---|---|---|---|
| 重采失败重复（cov_premium_median 15 + a_fund_north_quarterly 7） | 22 | 3.1 | `scripts/retry_failed_metrics.py:153` 调用 notify 时**没传 `--dedup-key`** → 每 3 轮必发；加 `--dedup-key retry_failed_<mid> --dedup-window 86400`（或集合变化才发） |
| warning 汇总 | 25 | 3.6 | `flush_warning_batch` 改并入摘要（合并成 1 条/天） |
| 升级提醒 | 18 | 2.6 | 若按「真故障不设上限」可**不计噪音**（它是未清除的真故障提醒） |
| 计划任务异常重复 | 6 | 0.9 | subject 带任务名 + 按 (任务集) 去重（见 A3） |
| 恢复留痕 | 11 | 1.6 | 并入摘要 |
| digest + 锁跳过 + 其余 | 13 | 1.9 | 保留（digest 1/天是交付载体） |

→ 若采纳「升级提醒算真故障 + warning/恢复并入摘要 + 重采失败去重」三项额外改动，噪音可降到 **约 2.4-3.1/天**，**0~3/天可达**。这一步需要主控拍板后再派实施（不在本次 5 项范围内）。

---

## 实施顺序 + 相互依赖

| 顺序 | 项 | 为什么这个顺序 | 依赖 | 冲突/注意 |
|---|---|---|---|---|
| 1 | **★1 邮件分流** | 风险最低、用户第一优先、单点 3 行 | 无 | 与 ★5 的 `[状态说明]` 白名单耦合：★1 必须先把白名单写进去，否则状态说明会失邮件 |
| 2 | **★3 域映射** | 纯函数 +2 关键词，零依赖 | 无 | 与 ★4 都改 `alert_denoise_rules.py`，但不同函数，无冲突 |
| 3 | **★2 停摆跨日** | 需要 notify 新 `--escalation-only`；越早做越早止血 | notify CLI | 与 ★5 都改 notify CLI（不同分支）；`--defer-digest` 的 noop status 必须处理 |
| 4 | **★5 摘要合并 + 状态说明** | 依赖 ★1 白名单；状态说明归一化独立 | ★1 | 改 `notify.py:_flush_digest_locked` + `schedule_monitor.sh`，与 ★2 不同段 |
| 5 | **★4 历史改写/kelly** | 工作量最大、要动 `app/` + 回放验证；先有 ★6 口径才能验收 | ★6 口径 | 与 A1（index_daily 大批量静默）同文件，建议同批或先立项 |
| 6 | **★6 口径落档 + 计数脚本** | 最后定基线；但**脚本骨架可先写**，前 5 项每完成一项就记一次基线 | 全部 | 纯文档 + 新脚本，不动业务 |

**建议合并派单**：★1+★3（小改动，同日）→ ★2+★5（都动 notify CLI，同批省回归）→ ★4（单独一个大单，带回放证据）→ ★6（收尾）。
**上线顺序注意**：★1 先上（用户最关心，且能立刻把邮件降一半）；★2/★5 同批上（都改 notify 的分发逻辑，同批回归更省）；★4 最后（数据口径类，需回放验证）。

---

## 附录 A：额外发现（不在 5 项内，但影响「真故障不设上限」的成立）

### A1（P0）index_daily 每天约 4.3 万行历史改写被 24h dedup 静默
- 证据：云上 `history_overwrite_audit`，10-27 17:59 批 23,931 行、21:03 批 19,476 行；`notify_dedup.json` 显示 `history_overwrite:index_daily:20261027:critical` 在 02:02:35 已被 1 条小改写占用 → 全天大批次零台账。
- 内容抽样：`csi_000330` 占位 OHLC → 真实 OHLC（修复）；`csi_000102` 6562.71→3367.89（纠错）；`-`→`nan`（表示变化）。**必须先诊断这是计划内每日回填还是异常**。
- 建议：按 ★4(b) 分来源/数量级分键；在诊断完成前**不要**直接把大批次降级掩盖。

### A2 重采失败重复发送（3.1/天）
- `scripts/retry_failed_metrics.py:153-166`：调 notify 时**没有 `--dedup-key`/`--dedup-window`** → 每累计 3 轮失败就发一条，send 后清零再来。7 天 22 条。
- 修法：加 `--dedup-key retry_failed_<mid> --dedup-window 86400`，或集合变化才发。

### A3 `计划任务异常` subject 不含任务名
- `scripts/schedule_monitor.sh:4049`：`f"[告警] {len(alerts)}项计划任务异常 {_sm_time}"` → 台账/去重无法区分「同一故障重复」和「不同故障」。
- 修法：subject 带失败任务名（或按任务集生成 dedup key），否则「噪音」口径里的 repeat 会误并真故障。

### A4 任务书「状态说明每天 3 条」需修正
- 实测：10-26 1 条、10-27 3 条；不是每天固定 3 条，而是「结论内容变化就发」。已在 ★5 按此修正口径。

---

## 附录 B：数据来源与口径声明
- 台账：云上 `/home/ubuntu/code/trade-data/data/alerts/alert_ledger.jsonl`，807 行（10-10 08:27 ~ 10-27 21:42）；近 7 天 391 行；只记实际外发。
- 群分布（7 天）：alert 199 / report 183 / follow 5 / agent_done 4。
- 邮件通道：384/391 行有 email；飞书 391/391。
- 审计表：`/home/ubuntu/code/trade-data/data/sentiment.db:history_overwrite_audit`（列：detected_at/run_date/src_table/kind/date/index_id/signal/before_val/after_val）。
- kelly 分布样本：18 天（台账最早 10-10，不足 30 天；**诚实标注：阈值依据是 18 天，不是 30 天**）。
- 本地代码基线：main `457201a5e`（2026-10-27）。
- 本报告只读产出，未 commit、未部署、云上零写。
