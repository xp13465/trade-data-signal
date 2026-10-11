# 告警降噪三项 实施报告(2026-10-11,实施 agent)

- 任务:用户 2026-10-11 拍板「直接干」的三项告警降噪(来源 `docs/ops/alert-triage-20261011.md` §3-3)。
- 目标:平时零告警、出事才响。降的只是「已知/正常/信息性」条目;**新出现的/异常的/规模超常的照常告警**。
- 分支:`worktree-agent-a56e10357ddd5bda5`(feat 分支;未 push main)。
- 残留后台任务:无(`moved to the background (ID:` 本次零出现)。
- 验收口径总表:`①` 每日不再出「8 个事件」条目 + 新缺键事件仍报警;`②` 小规模=无外发 + 超常=仍告警;`③` 短暂锁=不再轰炸 + 长时锁=仍告警。**六条全绿**(见「测试结果」)。

---

## ① 冻结表缺失 report(每天 21:12「[kelly] 冻结表缺失历史信号事件 8 个」)

### 出处(告警发出点)
- `scripts/signal_kelly_backtest.py:340 _alert_frozen_missing(events)`(2026-09-24 分级版);
  调用点 `:1966-1967`(`if _FROZEN_MISSING_EVENTS: _alert_frozen_missing(...)`,backfill_metrics 每日重生成时)。
- 事件来源:`_resolve_etf()` `:457/480` 在「精确键缺失 + 无 (date,index) 兜底 + best_etf 存在 + date < latest_signal_date」时记入 `_FROZEN_MISSING_EVENTS`。

### 现状核实(**与盘点报告有偏离,已用代码+云上只读枚举核实**)
- 盘点报告 §2-F 的根因「信号类型漂移 buy→buy_aux 致缺键」**已过时**:`_freeze_fallback`(2026-09-22)已接住「同一 (date,index) 有其它 signal 变体」的漂移。
- 真实根因(云上只读枚举,`/tmp/enum_frozen_missing.py`,复刻 `_resolve_etf` 判据):
  这 8 个事件的 `(date,index)` 在冻结表里**完全无键**(不是有键换类型)——信号是**事后回填**进 `signal_daily` 的,而冻结分时点防御闸(2026-09-18)拒绝补冻历史信号(`date < latest_signal_date`)。
  实测读数:`latest_signal_date=20261009`, `buy_rows=42168`, `freeze_keys=28284`, `MISSING n=8`。
- 8 个事件(枚举原文):
  `20260922|sz_div|buy`、`20260929|gz_399395|buy_aux`、`20261002|cac40|buy`、`20261002|dax|buy_aux`、
  `20261005|hscei|buy_aux`、`20261005|hstech|buy`、`20261006|cac40|buy`、`20261006|hsi|buy_aux`。
- 「让它们自然通过」不可行/未授权:补冻需用**今日** `board_etf_map` 判 ETF = 前视,且会改冻结基线(v1.1.7)数字;用户 2026-09-21 已拍板「接受跳过」。

### 改法及依据(治根 = 把「已确认接受」落到数据层)
- 新增数据产物 `config/signal_kelly_frozen_missing_accepted.json`(单一事实源;`config/` 属 git-tracked,云上经 symlink 可达,而根 `data/` untracked 到不了云上):
  `accepted` = 上述 8 键;附 `_meta`(purpose/why/decision/discriminator_preserved/how_to_extend/**fail_safe**)与 `approval_log`。
- `_alert_frozen_missing` 改为**先过滤后分级**:命中 accepted 的**精确键**(`date|index|signal`)只打 stderr 日志;仅「表外新事件」进入原有分级路径(n≥10 SEVERE / n<10 WARN)。
- **fail-safe**:`_load_frozen_missing_accepted()` 对「文件缺失/损坏/格式异常」一律返回空集 ⇒ 退回**全量告警**,绝不静默。

### 保留判据(降噪不降真故障判别)
- 表外新缺键事件照常告警(n<10 → WARN 24h dedup;n≥10 → SEVERE 1h dedup 直发)。
- 新事件数只按**新事件**计,不会因 8 个已接受项把新事件推过/隐藏阈值;subject 只报新事件个数。

### 测试结果
`scripts/tests/test_alert_denoise_3x_20261011.py`(①段 8 例全绿):
- 验收①`test_1_denoise_effective_8_accepted_no_notify`:8 键全命中 ⇒ `subprocess.run` 零调用。
- 验收②`test_1_discriminator_new_event_still_alerts`:8 已接受 + 1 新事件 ⇒ 发 1 条,subject 含「1 个」,正文含新事件键。
- 加强`test_1_discriminator_bulk_new_severe`:8 + 10 新事件 ⇒ 走 `--severe` + severe dedup key。
- fail-safe`test_1_failsafe_all_alert_when_table_missing`:表缺失 ⇒ 按全量 8 个告警。
- 另有 loader 正常/缺失/损坏三例 + 零外发一例。

### 「零真实外发」证据
① 的 notify 出口是**假 `subprocess.run`**(记录 argv、不起子进程);见下方「全局零外发实测」。

---

## ② verify 脱节 notice 降日志(verify-r2 兜底补传成功通知)

### 出处(告警发出点)
- `scripts/upload_r2.py` `cmd_verify_r2()` 收尾块(原 L3793-3821):`if stale_standalone_names:` → `notify.check_dedup("verify_r2_standalone_stale", 21600)` + `notify.send(...)`(默认 email+feishu)。
- **不是** `check_r2_consistency.py`(盘点报告的猜测位);云上 ledger 实证 10-10 17:16:49 / 10-11 18:23:47 两轮。

### 现状核实
- 触发条件:`stale_standalone_names` 非空 = 对账发现「独立链产物」R2 副本与本地不一致/缺失并自动补传成功;每轮 1~2 个小 json 即可触发。
- 原实现**无任何规模判据**,单个几十字节小文件脱节也照发 notice。

### 改法及依据(小规模仅日志;规模/轮次判据保留升级)
- 新增阈值常量(`scripts/upload_r2.py`,数据自定,依据=历史常态轮脱节多为 1~2 个小 json/数 KB~数百 KB):
  - `_STALE_ALERT_COUNT_THRESHOLD = 3`(单轮脱节文件数 ≥3)
  - `_STALE_ALERT_BYTES_THRESHOLD = 1 MiB`(单轮脱节合计字节 ≥1MiB)
  - `_STALE_ALERT_CONSECUTIVE_THRESHOLD = 3`(连续轮次 ≥3)
  - `_STALE_CONSECUTIVE_WINDOW_HOURS = 24`(相邻两轮间隔 ≤24h 才算「连续」)
- 新增状态文件 `REPO/data/.r2_standalone_stale_state.json`(原子写;记录 `last_round_ts / consecutive_rounds / last_count / last_bytes`)。
- 判定:本轮脱节且**未**超数量/字节阈且**未**达连续轮次 ⇒ 只打日志(`[verify-r2] ... → 仅日志, 不告警`);否则照常 `notify.send`(正文新增「本轮规模 / 连续轮次 / 触发判据」)。
- 清零:有一轮**无脱节** ⇒ 连续计数归零(真恢复入口,保留)。
- 字节统计:对账失配且属独立链产物的文件逐个 `stat().st_size` 累加(stat 失败按 0,不阻断主链)。

### 保留判据(降噪不降真故障判别)
- 单轮规模超常(≥3 文件 或 ≥1MiB)⇒ 照常告警(真故障:某链连续失败/被截断,补传量暴增)。
- 连续多轮脱节(同一 24h 窗内累计 ≥3 轮)⇒ 照常告警(真故障:持续脱节,非一次性代差)。
- 两类判据在告警正文里显式写出「触发判据=单轮规模超常/连续多轮脱节」+ 阈值。

### 测试结果
`test_alert_denoise_3x_20261011.py`(②段 10 例,ast 提取**真源码块+真 helper** 后 exec,非抄副本):
- 验收①`test_2_small_single_round_only_logs`:1 文件/12KB ⇒ 零发送。
- 验收②`test_2_count_threshold_alerts`:3 文件 ⇒ 发 1 条 + `update_dedup`。
- 验收②`test_2_bytes_threshold_alerts`:1 文件但 1MiB ⇒ 发 1 条;`test_2_bytes_just_below_threshold_silent`(1MiB-1)⇒ 静默(边界)。
- 验收②`test_2_consecutive_rounds_alerts`:连续 3 轮小规模 ⇒ 第 3 轮告警。
- 清零/窗口:`test_2_clean_round_resets_consecutive`、`test_2_window_gap_resets_consecutive`(>24h 重置)。
- `test_2_dedup_suppresses`:dedup 命中不重发、不写回。
- `scripts/tests/test_verify_r2_full_standalone_20261011.py` 新增 `test_weekday_small_stale_only_logs_no_alert`(单文件小规模 ⇒ `nf.sent == []` 且 stdout 含「仅日志」)。

### 「零真实外发」证据
② 的 notify 出口是**假 notify 模块**(`monkeypatch.setitem(sys.modules, "notify", fake)`,用例收工自动还原);见「全局零外发实测」。

---

## ③ fetch_news r2_skip 自愈对降级(warning 档恢复不再进群/邮件)

### 出处(通知发出点)
- `scripts/schedule_monitor.sh` 内嵌 python 的**主恢复循环**(`for _key, _info in list(alert_state.items())` ~L1935)+ **恢复发送块**(原 `if _combined:` ~L3028-3087):`notify.py <subject> <body> --from-prefix [恢复] --dedup-key schedule_monitor_recovery --dedup-window 21600`(默认 email+feishu)。
- r2_skip 自愈键的告警侧:`{task}|r2_skip_alert` 在 `alert_state` 里带 `"tier": "warning"`(#245 批2 L3c)或 `"severe"`(升级后)。

### 现状核实(**部分已修,残留=恢复通知**)
- #245 L3c(`5a92e6f81`,2026-10-10 18:16)**已在 main、已在云上**:transient 任务(fetch_news/gen_daily_brief)在 n<6 轮时已走 `--tier warning`(30min 聚合),n≥6 才升级 SEVERE。云上 `latest.md` 显示最后一条 fetch_news r2_skip SEVERE = **10-09 22:00**(L3c 之前),之后无新 severe。
- 因此 ③ 的**残留噪音 = 恢复通知**:`schedule_monitor_recovery`(6h 窗)仍**每轮双通道**发——10-11 05:00:07 / 19:00:13 两条,即便原告警只是 warning 档。
- 口径确认:只有 r2_skip 的 transient 键带 `tier="warning"`(其余 `alert_state` 键用 `self_heal` 等,不带 tier)⇒ 本条改动**实际作用域 = r2_skip 自愈对**,不误伤其它恢复。

### 改法及依据(warning 档恢复改仅 dashboard;severe 档不变)
- 恢复循环构造 recovery dict 时**携带 `tier`**(`:2000` 处 `"tier": _info.get("tier")`);pending 桶条目同样保留 `tier`(补列重试时仍走原档)。
- 恢复发送块按档**拆批发送**(`_send_recovery_batch`):
  - `tier == "warning"` → `notify.py ... --tier info`(仅记 dashboard,不进群/邮件;不带 dedup key)。
  - 其余(severe/critical/无 tier)→ 原路径(双通道 + `--alert-issue` + `schedule_monitor_recovery` 6h dedup)。
- 批级成功 = 各非空批均 `sent`;否则并入 `monitor_recovery|pending` 重试(保留原闭环)。

### 保留判据(降噪不降真故障判别)
- severe 档恢复**照常双通道**(自愈类持续阻塞时告警侧已升级 severe,其恢复必达)。
- 无 `tier` 的历史/其它来源恢复**默认双通道**(保守向后兼容,不误降级)。
- 恢复闭环不丢:被吞/失败仍入 pending 桶重试。

### 测试结果
`test_alert_denoise_3x_20261011.py`(③段 6 例,ast 提取**真 `if _combined:` 块**后 exec):
- 验收①`test_3_warning_tier_recovery_info_only`:`--tier info` 且**不带** `--alert-issue`。
- 验收②`test_3_severe_tier_recovery_full_channels`:无 `--tier`、带 `--alert-issue` + `schedule_monitor_recovery`。
- `test_3_missing_tier_defaults_full_channels`:无 tier ⇒ 默认双通道(保守)。
- `test_3_mixed_batches_split`:warning+severe 混合 ⇒ 拆 2 批(1 info + 1 alert)。
- `test_3_pending_retains_tier`:发送失败 ⇒ pending 条目保留 `tier`。
- `scripts/tests/test_245_l2_budget_digest_20261010.py::test_08b_recovery_loop_has_skip_anchor` 的锚点 `notify_state(_rec_out)` **保持不变**(重构期保留原变量名,零改动该测试)。

### 「零真实外发」证据
③ 的出口是**假 subprocess**(按 argv 伪造 notify.py 输出文本,由**真实** `notify_state()` 解析),真子进程不起;见「全局零外发实测」。

---

## 全局零外发实测(§18 L48,L50 先打桩 + 先证沙箱生效)

- 打桩生效证据(跑前/跑后逐位对比,含 mtime+size):
  - 跑之前:`data/alerts/latest.md` mtime=1791684035 size=31311;`data/alerts/alert_ledger.jsonl` mtime=1791731092 size=41934;
  - 跑 `test_alert_denoise_3x_20261011.py` + `test_verify_r2_full_standalone_20261011.py` + `test_188_s06_sync_blindspot_pytest.py`(32 passed)之后:两文件 mtime/size **完全一致**;`data/alerts/` 目录列表**完全一致**。
  - `data/.r2_standalone_stale_state.json` **未生成**(② 的状态文件只在 tmpdir 写)。
- 三层防护:① 假 subprocess / 假 notify 模块;② `_zero_outbound.ZeroOutboundTrap`(包 `urllib.request.urlopen` / `smtplib.SMTP(_SSL)`,一触即 `AssertionError`,4 个用例收尾断言 `trap.hits == []`);③ 断言「假对象确被调用」(证明打桩真生效,不是「没跑所以没外发」)。

## 现状核实先行(红线 4)

- ① 偏离:根因非「类型漂移」(已被 `_freeze_fallback` 接住),而是 `(date,index)` 全无冻结键(信号事后回填)。已在代码 + 云上只读枚举双核实。
- ② 偏离:发出点确认为 `upload_r2.py cmd_verify_r2`(非 `check_r2_consistency.py`)。
- ③ 偏离:严重级降级(L3c)**已上线**,残留只是恢复通知;故 ③ 只动恢复发送侧,不动告警侧。

## 改动清单

| 文件 | 类型 | 说明 |
|---|---|---|
| `config/signal_kelly_frozen_missing_accepted.json` | 新增 | ① 已确认接受登记表(单一事实源,含 fail_safe) |
| `scripts/signal_kelly_backtest.py` | 改 | ① `_load_frozen_missing_accepted()` + `_alert_frozen_missing` 先过滤后分级 |
| `scripts/upload_r2.py` | 改 | ② 阈值常量 + 状态文件读写 helper + 脱节判定块(仅日志/告警分流) |
| `scripts/schedule_monitor.sh` | 改 | ③ recovery 带 tier + 恢复发送按档拆批(warning→`--tier info`) |
| `scripts/tests/test_alert_denoise_3x_20261011.py` | 新增 | 三项 24 例「降噪生效+判别保留」回归 |
| `scripts/tests/test_verify_r2_full_standalone_20261011.py` | 改(既有) | ② 行为变更适配:单文件小规模→仅日志(新增 1 例);onepage 正例改 3 文件驱动 |
| `scripts/test_188_s06_sync_blindspot.py` | 改(既有) | ② 同上,#188 正例改「规模超常(3 文件)」驱动 |
| `scripts/tests/test_223_timeout_gradient_copy.py` | 改(既有) | ② 正文渲染 env 补 4 个新字段(不改断言) |

> 说明:改既有测试 = 用户已拍板的**行为变更**(降噪)使旧断言(「1 个小文件也要告警」)不再成立;新断言改了**驱动规模**与**正文渲染 env**,原验收意图(不崩 / 补传 / 有等效告警输入 / 判别分支保留)全部保留。`test_245`、`test_212` 等其余测试**一字未改**。

## 举一反三 / 同类错误面清单(§23.2/§23.3)

- ① `冻结表缺失` 告警发出点全仓 sweep:仅 `signal_kelly_backtest.py` 一处(`hold_days_sweep.py:55` 是研究档把它替换为打印的研究接口,不受影响)。
- ② `verify-r2 兜底补传` notice 发出点:仅 `cmd_verify_r2` 一处;同文件相邻的「大量不一致(mass mismatch,阈值>50)」告警**未动**(仍是真故障信号,无需降噪)。
- ③ `alert_state` 中带 `tier` 的键全量核对:仅 r2_skip transient 键带 `tier="warning"`(其余用 `self_heal` 等)⇒ 本改动作用域天然限定 r2_skip 自愈对,不误伤 `overview_lag/r2_*/feishu_/missed|exit` 等恢复。
- 恢复通知的分级**不覆盖** pending 摘要尾链(`--defer-digest recovery`)——该尾链保持原状(test_245 全绿为证)。
- 数据一致性:① 新增 config 为 git-tracked,云上经 symlink 可达(`ROOT/config/...`);② 状态文件在 `REPO/data/`(untracked,与既有 `.r2_standalone_keys.json` 同目录同口径)。

## 命令附录

```bash
# ① 云上只读枚举真实缺键事件(不写云上/不 exec 业务脚本)
ssh -o IdentitiesOnly=yes -i /Users/linhuichen/tdsignal.pem ubuntu@122.51.111.173 \
    'python3 -' < /tmp/enum_frozen_missing.py
#   → latest_signal_date=20261009, buy_rows=42168, freeze_keys=28284, MISSING n=8

# 语法自检
python3 -c "import ast; ast.parse(open('scripts/signal_kelly_backtest.py',encoding='utf-8').read())"
python3 -c "import ast; ast.parse(open('scripts/upload_r2.py',encoding='utf-8').read())"
awk 'NR>=65 && /^PYEOF$/{exit} NR>=65' scripts/schedule_monitor.sh > /tmp/sm_check.py && \
  python3 -c "import ast; ast.parse(open('/tmp/sm_check.py',encoding='utf-8').read())"

# 新增测试套(三项 24 例)
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/test_alert_denoise_3x_20261011.py

# 全量回归
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/
#   → 780 passed, 1 skipped(唯一 FAIL=test_212 静态对照,见下「已知噪声」)

# 零外发实测(跑前/跑后告警目录对比)
stat -f "%m %z" data/alerts/latest.md data/alerts/alert_ledger.jsonl
ls data/alerts/ ; ls data/.r2_standalone_stale_state.json
```

## 已知噪声 / 诚实标注

- `scripts/tests/test_212_upload_onfail_loud_pytest.py::test_e_pre_change_source_static` 在**未提交**态必 FAIL:
  它用 `git show HEAD:scripts/upload_r2.py` 当「#212 改前版」与工作区比,要求 HEAD 版无 `_channel_on_fail`;而 #212 早已在 HEAD(#212 已 merge),该用例本意是「改动未提交时可对照」——任何**改动 upload_r2.py 的 worktree** 都会踩到。**提交后 HEAD==工作区 ⇒ 该用例自动 skip**(与 main 上一致)。本次提交后将复跑确认(不改该测试,属其自身设计,超出本任务授权范围)。
- ③ 的 `--tier info` 不带 dedup key ⇒ 每条 warning 档恢复各记一次 dashboard(每恢复事件一次,不重复;因状态已翻 recovered,不会逐轮重复)。
- 本次**未做** red-first(未回退旧码跑新测试);新测试的判别性由「旧断言在旧码下的反例」间接佐证(如 test_223 正文渲染对旧正文无新字段)。