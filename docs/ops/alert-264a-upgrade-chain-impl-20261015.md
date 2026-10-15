# #264 包1「升级链」实施报告 —— 件A 升级档独立抑制窗 + 件B 判据事件化

- 日期:2026-10-16(实施跨 10-15 夜 ~ 10-16 00:xx)
- 分支:`feat/264a-alert-upgrade-chain`
- 依据:`docs/ops/alert-noise-rca-20261015.md`(§1.3/§1.4/§2.2④/§4.1 A+B 段/§4.2);用户 2026-10-15 拍板「按建议修复」(A+B+C+E+F 打包,本包 = **只做 A+B**)
- 收束任务:`docs/pending-features-index.md` **#259**(`schedule_monitor` failed unit「连续 N 天」判据挂持久状态 ⇒ 必单向升级 critical);本包未与 #257/#258/#260 交叉(不同域),与并行包 **264b(notify.py 其它区)/264c** 无同区段冲突(见 §8)

---

## 0. 结论速览

| 项 | 结果 |
|---|---|
| 件A(升级档独立抑制窗) | ✅ 已实现:升级档改判**自己的窗**,与调用方首报窗彻底解耦。窗口取值经**实测重放**锚定 **72h**(RCA 建议 24h 实测**不达标**,偏离已逐条声明,见 §3/§5) |
| 件B(判据事件化) | ✅ 已实现:#196 两通道判据改**有界滚动窗「近 7 天出现天数」**;R7 通道(`rolling_window_days=None`)逐位不变 |
| A-①(重放 ≤2,现 18) | ✅ **2 封**(见 §3 表) |
| A-② 真故障反例(窗口外/首报必发) | ✅ PASS(测试 `test_a2`) |
| A-③ 真故障反例(首报必达不破坏) | ✅ 部分:首报通道 + 升 critical 首报均必达;**残余 1 项**(已处 critical 时的「新增单元」受窗约束)见 §5.2 |
| B-①(逐日重算 ≤2,现 18) | ✅ 2 封(与 A 同源,同一独立窗) |
| B-②(新增失败单元首日仍 critical) | ✅ PASS(测试 `test_a2`/`test_a3`) |
| B-③(alert_state 恒挂账 ≤3,现 14) | ❌ **未达成**:实测真正「挂账且在重复播报」的只有 1 个,其余为惰性残留;清理机制属另一域(不在本包声明区),**如实上报待拍板**(§5.3) |
| 测试 | 新增 `test_264_upgrade_chain_20261015.py`(10 例)+ 改 `test_196` 2 处过时断言;**全量 909 passed / 2 skipped**;判别力关 3 变异全红;TZ 跨 10-15/10-16 两自然日全绿 |
| 零真实外发 | ✅ `ZeroOutboundTrap` + 全层打桩,真实出口触达 **0**(§7) |

---

## 1. 改动清单(文件:行号)

| 文件 | 区段(改后行号) | 改了什么 |
|---|---|---|
| `scripts/alert_denoise_rules.py` | L64-89(新增常量块) | 新增 `ESCALATED_DEDUP_WINDOW_SECONDS = 259200`(72h,含取值依据注释)、`ESCALATE_ROLLING_WINDOW_DAYS = 7` |
| `scripts/alert_denoise_rules.py` | L224-225(签名) | `consecutive_days_escalate(..., rolling_window_days=None)` 新增可选参数(默认 None = 旧语义) |
| `scripts/alert_denoise_rules.py` | L231-239 | rolling 迁移:旧状态无 `seen_dates` 时用 `consecutive_days` + `last_fail_date` **反推补齐**(不丢历史连续性) |
| `scripts/alert_denoise_rules.py` | L240-264 | rolling 分支:`seen_dates` 记账 + 窗口过滤 + **有界计数** = 窗口内出现天数 |
| `scripts/alert_denoise_rules.py` | L313-314 | 落盘:`rolling` 时补写 `seen_dates`(字段仅在启用 rolling 时出现) |
| `scripts/notify.py` | L2816-2836 | #196 升级分支:①改判 `check_dedup(_esc_escalated_key, adr.ESCALATED_DEDUP_WINDOW_SECONDS)`(不再复用 `args.dedup_window`)②`consecutive_days_escalate(..., rolling_window_days=adr.ESCALATE_ROLLING_WINDOW_DAYS)`③subject/正文措辞随判据改(「近 7 天出现 N 天」) |
| `scripts/check_failed_units.py` | L267-272(仅 docstring) | 补说明:`--dedup-window 0` **只作用于首报通道**,升级档走独立窗 ⇒ **本脚本零逻辑改动**(调用参数 L282 不变) |
| `scripts/tests/test_196_patrol_visibility_20261005.py` | L524-525 / L539-540 | 2 处断言随实现同步(`"连续 3 天"` → `"近 7 天出现 3 天"`) |
| `scripts/tests/test_264_upgrade_chain_20261015.py` | 新增(10 例) | 件A 4 例 + 件B 5 例 + 零外发 1 例 |

**未改动**(刻意):R7 分支 `notify.py:2764-2791` 一行未动(仍 `args.dedup_window`);`schedule_monitor.sh` / `check_r2_consistency.sh` / `cloud_unit_patrol.sh` 零改动(它们传的 `--dedup-window 21600` 现在只作用于各自首报通道)。

---

## 2. 实施前置三验证清单(§5.7 依据三件)

### ① 问题真实性(实测证据,非推断)
- **云上台账** `/home/ubuntu/code/trade-data/data/alerts/alert_ledger.jsonl`(273 行,10-10 08:27 ~ 10-16 00:10)实查:「升级 critical」行 **21 封**(20 封 = `云上 failed unit 持续未清` + 1 封 = 10-15 23:22 §22 三站一致性 R7)。
- failed unit 升级逐日:**10-11 1 / 10-12 4 / 10-13 3 / 10-14 4 / 10-15 7 / 10-16 1**;10-15 单日 7 封(00:00/18:45/20:15/20:30/21:15/22:15/23:30),其中 00:00~22:15 六封同主题「(连续 8 天, 升级 critical)」= RCA §1.4「同主题 6 次」复现。
- `data/failed_units_patrol_state.json`:`consecutive_days` 自 10-08 起**只增不减**(10-15=8、10-16=9 见 subject 文本)⇒ 挂持久 failed state 必单向升级,**问题真实性成立**。
- 台账口径:该主题在 10-11~10-16 **零条首报行**(key=`failed_units_patrol`)⇒ 所有外发都经升级分支(升级分支 `return 0` 早退,吞掉普通 severe 路径),与 RCA 判断一致。

### ② 根因定位(代码实文)
- `scripts/notify.py:2825-2828`(改前 L2822):升级档调 `check_dedup(_esc_escalated_key, args.dedup_window)` —— **复用调用方窗口**。
- `scripts/check_failed_units.py:282`:该链路调 notify 时传 `--dedup-window 0`(「集合有变立即报」)。
- `scripts/notify.py:1479-1480`:`if not key or window <= 0: return False` ⇒ **`window=0` 恒放行** ⇒ 升级 critical **永不被抑制**(且 `update_dedup` 仍写时间戳,检查端从不读 ⇒ 死码)。
- 同型核查:`check_r2_consistency.sh:128` / `cloud_unit_patrol.sh:151` 传 `21600` ⇒ **不触发**该病灶(所以病灶是 failed_units 特有表现,但 #196 分支两个通道同码 ⇒ 一并修)。

### ③ 修复可行性
- 最小改法:升级档改判**独立常量窗**(单点);判据改**有界滚动窗**(纯函数加可选参数,默认 None 保旧语义)。
- 调用点穷举:`consecutive_days_escalate` 全仓**只有 2 个调用方** —— `adr.py:722`(R7 包装器,**不传** rolling ⇒ 逐位不变)与 `notify.py:2818`(#196,**传** rolling);状态文件**只有** `notify.py` 读写(前端/其它脚本零消费)⇒ 无第三处需同步。
- 测试可行:全链可打桩(发送层 + `check_dedup`)并**冻结运行日**(§18 L51)⇒ 零真实外发 + 隔天仍绿可证。

---

## 3. 预期 X→Y vs 实测(含窗口取值依据)

### 3.1 窗口重放(用云上 10-11~10-16 的 20 封 failed-unit 升级行逐条按窗判定)

| 窗口 | 10-12~10-15(现 18) | 10-11~10-16(现 20) | 10-15 单日(现 7) | 是否达 RCA 量化预期 |
|---|---|---|---|---|
| 24h(RCA 建议值) | **4** ✗ | 5 | 1 ✓ | ✗(> ≤2) |
| 48h | 2 ✓ | 3 | 1 ✓ | ✗(6 天 3 > RCA「6 天 18 条 → ≤2」) |
| **72h(采用)** | **2 ✓** | **2 ✓** | **0**(≤「同档 ≤1 封」✓) | ✅ 三项量化预期全达 |

72h 下的发送时点:`10-11 00:00`、`10-14 00:00`(← 即「凌晨零点日课」被消灭,RCA §1.3 点名的 0-8 时噪声项)。

**偏离声明(须拍板)**:RCA §4.1.A 建议 **24h**;实测 24h 在**派单钉的 A-① 验收口径(10-12~10-15 ≤2,现 18)上得 4 封 = 不达标**(机制必然:每天零点巡检恒跨过 24h 边界 ⇒ 日课不灭)。取 72h = **满足 RCA 全部量化预期的最小窗口**,且不快于「每 3 天 1 封」提醒节奏。**改动成本 = 1 个常量**(`adr.ESCALATED_DEDUP_WINDOW_SECONDS`),用户若偏好更敦促可一行改 48h/24h(表内数字已备)。

### 3.2 预期 X→Y 对照

| 项 | 预期(Y) | 实测 | 判定 |
|---|---|---|---|
| 升级 critical 抑制 | 「集合每变化/每天零点必发」→ 独立窗内同档 ≤1 封 | 由「窗口内已发恒放行」→ **窗口内真抑制**(`test_a1` + `test_a4`) | ✅ |
| 4 天重放 | ≤2(现 18) | **2** | ✅ |
| 10-15 单日 | 6 → 1 | **6 → 0**(≤1) | ✅(优于预期) |
| 6 天总量 | 18 → ≤2 | **2** | ✅ |
| 「连续天数」 | 单调无界 → 有界/事件化 | `consecutive_days` 由 **20 → 7**(窗口上限),稀疏出现 9 → 2;旧 8 天单调链不再增长 | ✅ |
| 首报必达 | 不破坏 | 首报窗仍 = 0(`test_a3`),升 critical 首报窗空必发(`test_a2`);R7 逐位不变(`test_b5`) | ✅ |
| 挂账 key 清理(B-③) | 30 天内 ≤3(现 14) | **未达成**(§5.3) | ❌ |

---

## 4. 证据用例逐条结果

| 用例 | 方法 | 结果 |
|---|---|---|
| A-① 历史重放 ≤2 | 云上 10-12~10-15 台账 18 行逐条按窗重放 | **2 封** ✅ |
| A-②「集合不变的一天」重放 | 状态已 critical + 升级档窗内已发 → 真跑 `notify.main`(调用方 `--dedup-window 0`) | **零外发**(`test_a1`: `assert not sent`) ✅ |
| A-③ 真故障反例 | ①窗口外/首报 → 必发 critical(`test_a2`)②首日(未 critical)→ 仍走 `send` 普通路径(`test_a3`) | ✅(**残余见 §5.2**) |
| B-① 逐日重算 ≤2 | 同 A-①(同一独立窗;滚动窗只改判据不改计数口径) | **2** ✅ |
| B-② 新增失败单元首日 critical | `test_a2`/`test_a3`(状态仅当日 1 天 → severe 立即发;昨日 2 天 → 今升 critical 立即发) | ✅ |
| B-③ 挂账 key ≤3 | 云上 `alert_state.json` 全量实查 | ❌ 未达成(§5.3) |
| 零外发 | `test_zero_real_outbound_full_chain` | `trap.hits == []` ✅ |

真实测试输出(节选):
```
$ /tmp/ci-venv/bin/python -m pytest -q scripts/tests/test_264_upgrade_chain_20261015.py scripts/tests/test_196_patrol_visibility_20261005.py
55 passed in 0.91s
$ /tmp/ci-venv/bin/python -m pytest -q scripts/tests/
909 passed, 2 skipped in 122.53s (0:02:02)
```
判别力关(§18 L49,3 变异全红,改后已还原并 md5 校验一致):
```
MUTATED-A: escalated window -> caller window(args.dedup_window)
  → 2 failed (test_a1 / test_a4)
MUTATED-B1: window filter removed → 2 failed (test_b1 / test_b2)
MUTATED-B2: migration synthesis removed → 4 failed (a1/a2/a4/b3)
restore verified: notify.py md5 a40f96a5… / adr.py md5 ea0d3879…(与备份逐位一致)
```
隔天仍绿(冻结运行日 + TZ 平移两自然日):`TZ=Pacific/Kiritimati(本地日 10-16)` / `TZ=Etc/GMT+12(本地日 10-15)` / `TZ=Asia/Shanghai(10-16)` → **三档全 55 passed**。

---

## 5. 10-15 时间线前后对照 + 残余

### 5.1 逐条对照(10-15 云上真实 7 封 → 改后)

| # | 旧(实发) | 新(重放判定) | 说明 |
|---|---|---|---|
| 1 | 10-15 00:00:06 critical | **抑制** | 上次升级外发 = 10-14 00:00(重放口径),距此仅 24h < 72h ⇒ 零点日课被抑制 |
| 2 | 10-15 18:45:06 critical | 抑制 | 同上 |
| 3 | 10-15 20:15:05 critical | 抑制 | 同上 |
| 4 | 10-15 20:30:06 critical | 抑制 | 同上 |
| 5 | 10-15 21:15:06 critical | 抑制 | 同上 |
| 6 | 10-15 22:15:06 critical | 抑制 | 同上 |
| 7 | 10-15 23:30:08 critical | **抑制** | 距 10-14 00:00 = 47.5h < 72h |

10-15 单日:**7 → 0**;6 天(10-11~10-16):**20 → 2**(发送日 10-11 00:00、10-14 00:00)。逐条重放脚本输出:

```
window=72h  10-12~10-15 外发=2 (现18) | 10-11~10-16 外发=2 (现20) | 10-15 单日=0 (现7)
     发送时点(10-11~10-16): ['10-11 00:00', '10-14 00:00']
```

> 注:重放假设「历史上每一次 notify 调用都是一次合法发送事件」—— 成立,因为 `check_failed_units.py` 只在 `_send=True`(added/daily-first/changed)时才调 notify(抖动类 added-jitter / same-set-same-day 在脚本内已静默)。

### 5.2 残余 1:已处 critical 时「当日新增失败单元」受窗约束(如实上报)

- 现象:当链路**已处 critical**(如连续 8 天)且升级窗未到期时,今日**新增**失败单元触发的通知会被升级窗抑制(最长延后一个窗)。旧代码 `window=0` 时不会。
- 影响面:仅「已 critical 且窗内」时段的**新增**事件;首报通道(未 critical)与升 critical 首报均不受影响。
- 为什么没顺手做:需把调用方的 `reason`(added/changed)透传给 notify(新增 CLI 参数 + 跨脚本耦合点),属 RCA **件 B 选项 2「当日新增/恶化才推进」** 的严格版;而历史 10-15 的 6 封里多数同属 added/changed 触发,**若直接 bypass 窗口会退回 6 封/日、不达 A-①**(即两条目标互斥)。故本包取「纯窗口制」并上报,不做未经数据验证的 bypass。
- 候选处置(待拍板,1 处小改):`check_failed_units` 在 `reason=="added"` 时追加 `--escalate-bypass`(notify 升级分支读到即跳过窗口并刷新时间戳)。需要先采 1~2 天真实 reason 分布(云上 `failed_units_sig_state.json` 只存最近一次,历史不可反推),以免 bypass 把噪声放回来。

### 5.3 未达成项:B-③(`alert_state` 恒挂账 key 30 天内 ≤3,现「14」)

云上 `data/alert_state.json` 全量实查(**181 keys**;`recovered` 151 / `active` 13 / 状态字段缺失 13 / `pending` 2 / `alerted` 2):

- **真挂账 ≥9 天不消 = 5 个**:`overfit_monitor|r2_skip_rounds`(21d)、`fetch_news|r2_skip_rounds`(21d)、`r2_intraday_lag|buffer|20260929`(16d)、`intraday_snapshot|r2_skip_rounds`(16d)、`fetch_news|marker_buffer`(9d)。
- 其中**仍在重复播报的 = 1 个**(`overfit_monitor|r2_skip_alert`,`last_alerted` 仍是当日 —— 由日常巡检刷新状态,非真发:台账中 `r2_skip` 相关行全期仅 **2 行**)⇒ **播报侧噪声贡献 ≈ 0**。
- 其余 12 条无非恢复态 key 是 10-13~10-15 的**活跃真故障**(≤2 天),外加 10 个 `r2_pipeline_congestion|YYYYMMDD` **日键**(设计即按日翻滚、无 recovered 语义)。
- 与 RCA「现 14」的口径差:RCA 计的是「非 recovered 态」全量(30),或者把日键/活跃真故障一并计入;本包按「挂账不消」严格口径拆开。
- **为什么不改**:到期清理/降级会触及 `alert_state` 生命周期(schedule_monitor.sh + notify.write_alert 的恢复循环),①不在本包声明区(与 264b/264c 有交集风险)②强制过期仍失败的 key 会让下次事件重新告警(re-trigger 噪声),若条件不再触发则等于**静默隐藏真故障**(违 memory `alert-denoise-keep-fault-discriminator`)⇒ 需专门设计 + 用户拍板,已如实上报。

---

## 6. 零真实外发声明(§18 L48 / memory `notify-script-selftest-must-stub`)

- **本次自测零真实外发**。打桩方式:monkeypatch `notify.send_tiered` / `send` / `check_dedup` / `update_dedup` / `write_alert`(发送层 + 落盘层全封),外加**最底层真实出口陷阱** `scripts/tests/_zero_outbound.py::ZeroOutboundTrap`(包 `urllib.request.urlopen` / `smtplib.SMTP` / `smtplib.SMTP_SSL`)。
- **打桩生效的正面证据**(先证沙箱再生效):`test_zero_real_outbound_full_chain` 同时断言 ①`trap.hits == []`(真实出口 0 触达)②`sent` 非空(发送确实发生了,只是被拦在内存)⇒ 不是「因为没发所以没外发」的假绿。
- `check_dedup` 打桩**复刻真实现语义**(`window <= 0` 恒放行),使「实现退回复用 0 窗」这类变异**真红**(已由判别力关实测)⇒ 非 L49「假样本养绿」。
- 本次未跑任何云上写操作;云上仅**只读**(`alert_ledger.jsonl` / `alert_state.json` 两文件读取)。

---

## 7. 并行区段声明(触碰函数清单)+ 举一反三

### 7.1 触碰的函数/区段(给 264b/264c 及主控 merge 排序用)
- `scripts/notify.py`:**仅** `main()` 内 #196 升级分支(L2812-2851 区段)。R7 分支(`main()` L2764-2791)、`check_dedup` / `update_dedup` / `send` / `send_tiered` / `_record_ledger` **均未触碰**。
- `scripts/alert_denoise_rules.py`:`consecutive_days_escalate`(签名 + rolling 分支)、常量块;**未触碰** `failed_units_daily_judge` / `r7_r2_consistency_escalate` / `wrapper_channel_alerted` 等其余函数。
- `scripts/check_failed_units.py`:仅 `_send_notify` docstring;调用参数/逻辑零改动。
- 新增文件:`scripts/tests/test_264_upgrade_chain_20261015.py`(新文件,无冲突面)。

### 7.2 同类错误面清单(§23.2 修 bug 三铁律:修完整 + 排查同类)
| 同类面 | 是否同病 | 处置 |
|---|---|---|
| #196 另一通道 `cloud_unit_patrol_drift`(patrol 漂移) | **同病**(同分支同 `args.dedup_window`) | ✅ 一并修(`test_a4` 覆盖) |
| R7 `r2_consistency` 升级档 | **不同病**(R7 分支独立、传 21600;且判据未改) | ✅ 一行未动 + 回归用例 `test_b4`(纯函数)/`test_b5`(真跑) |
| `check_r2_consistency.sh`(21600)/ `cloud_unit_patrol.sh`(21600) | 不同病(窗口 >0,抑制有效) | 零改动;现语义 = 「首报窗 6h」+「升级档独立 72h 窗」 |
| 其它传 `--dedup-window 0` 的调用方 | 全仓仅 `check_failed_units.py:282` 一处 | 已在 docstring 标注语义边界 |
| 其它用「连续天数/持久状态」推进档位的机制 | `schedule_monitor.sh` 的 `self_heal escalated`(L271/L1631/L2306)—— 按「连续 N 次」**运行计数**,非自然日持久状态 | 未动(语义不同、不在声明区);已登记为后续核查候选 |

### 7.3 举一反三(§23.3:同模式/同数据源/同组件还被谁用 + 相关展示位)
- **同数据源(状态文件)**:`failed_units_patrol_state.json` / `cloud_unit_patrol_drift_state.json` / `r2_consistency_fail_state.json` 三者的**唯一读者 = `notify.py`**(全仓 grep 确认),新增字段 `seen_dates` 无第三方消费者 ⇒ 不触发 §22 多展示位一致性联动(前端/邮件链路零引用)。
- **同组件(升级档通用实现)**:`consecutive_days_escalate` 2 个调用方全覆盖(见 §2③),无遗漏调用点。
- **相关展示位**:升级档文案出现在 ①邮件 subject ②飞书 alert 群(同 `send_tiered` 链路)③`alert_ledger.jsonl` 台账 ④`write_alert` 落 `alert_state.json`(issue 名)—— 措辞随实现三处同源(同一 `_esc_subject`/`_esc_body`)⇒ 天然一致;`test_196` 的 2 处断言已同步,防「文案与实现漂移」。
- **同模式(降噪不得吞真故障)**:首报窗/首报路径/真故障反例各留了正反用例(§4),不只做用户点名处。

---

## 8. 交付与后续

- 代码:`feat/264a-alert-upgrade-chain`(commit + push feat,**不 push main**;merge 由主控走 `scripts/main-merge.sh`)。
- 待拍板 3 项(本包不改):① 窗口取值 72h 是否接受(替代 RCA 建议 24h,备 24/48/72 数字)② §5.2 残余(已 critical 时新增单元受窗,是否加 `--escalate-bypass`)③ §5.3 B-③ 挂账 key 到期清理(另一域,须先设计防 re-trigger/防隐藏真故障)。
- 上线后观察锚点:RCA §4.1.A 证据用例①「改后连续 6 天 `alert_ledger.jsonl` 中『持续未清』行 ≤2」—— 建议主控在部署后第 3/6 天各核一次(云上只读 grep 即可)。