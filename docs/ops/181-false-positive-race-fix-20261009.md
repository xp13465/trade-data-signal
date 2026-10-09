# #181 降噪「幻影 +1」竞态假阳性修复报告(2026-10-09)

- 实施角色: implementer agent(worktree 隔离;本任务全程无云上写、无 R2 写、无真实外发)
- 用户已批准改已上线逻辑(§23.7 版本冻结契约确认在位 —— 派单明示「用户已批准」)
- base commit: `4325a27d5`(开工 `git merge-base --is-ancestor origin/main HEAD` = base-fresh)
- 前置证据源: `docs/ops/181-denoise-prod-sample-20261008.md`(tester 云上只读复核,125 行,含原始行号)

## 0. 结论速览

- **根因复现 = 成立**(tester 机制正确,本 agent 读码 + 构造复现独立确认,见 §1)
- **修向 = 有细化**(tester 建议「轮标识直接用最新 `轮次开始` 时间戳」**不足**,须锚到**拥有 skip 窗口那一轮**的 `轮次开始` 时间戳;见 §2.1 + 反事实证据 §3.2)
- **改动 = 2 处生产 + 2 处测试**(§2);阈值语义「连续 3 轮」与告警链其它部分**零改动**
- **测试 = 全通过**(相关 46 项 + 全量 482 passed / 2 skipped;§3)
- **影响面 = 面收敛**(仅 EXTRA 任务的 r2_skip 轮去重标识 + 新增 info 字段;§4)

## 1. 根因独立复现(不采信 tester 结论,独立确认)

### 1.1 机制(代码 + 时序)
- **轮标识源**: `gen_schedule_stats.py` 的 EXTRA_MARKER_SCANS 循环把 `last_run` 设为**日志文件
  mtime**(round_start_re=`[fetch_news] 已写 ` 窗口 **之外** 的另一路输入),见改动前 L1149-1153。
- **计数窗口源**: `scan_marker_log` 的 skip 窗口 = `[最后一条 round_start_re(`已写`)行, EOF)`,
  `SKIPPED_LOCKED` 数在此窗口内统计(见 `gen_schedule_stats.py` `scan_marker_log`)。
- 两者**异源**:fetch_news 每轮 `:01/:45:00` 先 `print(... 轮次开始 <ts> ..., flush=True)`(瞬间
  刷新文件 mtime),数十秒后才写 `已写`(skip 窗口才前移)。
- monitor 恰在 `:45` tick 与 fetch_news `:45:00` 轮**同秒起跑**时读到错配组合 =
  「窗口仍指上一轮(**含** SKIPPED_LOCKED)、mtime 已是新值」⇒ `_r2_same_round=False` ⇒ **+1 幻影**。
- 后果:阈值 `R2_SKIP_CONTINUOUS_THRESHOLD=3` 实际退化为「连续 **2** 真轮」⇒ 多报(非漏报)。

### 1.2 构造性复现(本 agent 独立于 tester)
用真 `fetch_news` 行格式构造竞态日志(01:01 轮含 SKIP,01:45 轮「轮次开始」已 flush 无「已写」),
调真 `scan_marker_log`:输出 `skip_count=1`、`round_start_ts=2026-10-09 01:45:00`(M1 用的最新开始
时间戳)、`window_round_ts=2026-10-09 01:01:00`(本修复新增,窗口所属轮)。**同一日志里 M1 的
`round_start_ts` 已是新轮 01:45**,这正是「直接用最新 `轮次开始` 当轮标识仍会幻影」的实证。

### 1.3 tester 机制成立性 = 确认
报告 §5.1 链 E 的「唯一自洽解」(dup 行 L15899 已证 `last_round=01:02`,`01:45` 轮本身同步 OK)
与本 agent 读码 + 复现一致 ⇒ **tester 机制成立,不另起炉灶**。

## 2. 改动

### 2.1 修向细化(为何不能「直接用最新轮次开始时间戳」)
- `:45` tick 的幻影源于**标识与窗口异源**。文件 mtime 与「最新 `轮次开始` 时间戳」**都在 `:45:00`
  同一瞬刷新**(同一条 flush 行),二者与「skip 窗口」(在 `已写` 时前移)**同样异源** ⇒ 换成
  最新 `轮次开始` **不减幻影**(见 §3.2 反事实机检:fixture 下旧标识恰在 01:45:02 tick 幻影告警)。
- 正解:**轮标识锚到窗口本身** —— 取窗口起点行(`round_start_re` 命中行)**之前或同位**的最后一个
  `round_begin_re` 命中行的时间戳。窗口 `[该 start 行, EOF)` 恒不随新轮起跑前移,故标识恒锚在
  **窗口所属那一轮**(新轮 01:45 的「轮次开始」虽已进入窗口,但窗口起点仍是 01:01 轮「已写」⇒
  标识仍 = 01:01)⇒ 同轮 tick 一致,幻影消除。这与 tester 建议取的是**同一种**「轮次开始时间戳」,
  只是锚点取「窗口所属轮」而非「最新轮」。

### 2.2 生产改动
**`scripts/gen_schedule_stats.py`**
- `scan_marker_log`:新增跟踪 `window_start_idx`(窗口起点行下标);新增计算 `window_round_ts` =
  窗口起点行之前(含同位)最后一个 `round_begin_re` 行的时间戳;返回值 4 元组 → **5 元组**
  (末位 `window_round_ts`;`round_start_ts` 语义不变,仍供 M1)。
- EXTRA 循环:新增输出字段 **`r2_round_id`** = `_window_round_ts`(None ⇒ 消费端回退 `last_run`)。
  `last_run`(mtime)**不变**。

**`scripts/schedule_monitor.sh`**(r2_skip 消费块,唯一改动点)
- 新增 `_r2_round = s.get("r2_round_id") or _r2_lr`;轮去重标识 `last_round` 改存 `_r2_round`
  (不再存 mtime)。**新鲜度判据 `_r2_fresh` 仍用 `last_run`(mtime),逐字不变**;阈值 / 保链 /
  seen 补全 / 清零点 / 恢复循环**零改动**。
- dup 日志行打印 `last_round={_r2_round}`(信息性,不改判别)。

### 2.3 测试改动
- **新增边界竞态 fixture** `scripts/tests/fixtures/181/race_ticks.csv`(列 NOW,last_run,skip,
  `r2_round_id`;编码「:45 tick 与 :45 轮同秒起跑」场账,逐行引用报告 §5.1/§5.2 真实原始行号)。
  - **fixture 列粒度口径(诚实标注)**:`r2_round_id` 列用**分钟粒度**(`2026-10-09 00:45`),因
    §5.1 链 E 生产样本只给到分钟级锚点(dup 行 `last_round=2026-10-09 01:02`);**生产实测 `r2_round_id`
    实为带秒**(`2026-10-09 01:01:00`,见 §4.1)。本 fixture 测的是**竞态判别逻辑**(纯字符串相等去重,
    与粒度无关),故分钟粒度不影响被测行为;但它**不覆盖**「旧分钟串 vs 新秒串」的**升级瞬变**面 ——
    该面见 §4.5(由审查探针 P1 生产实测覆盖,非本 fixture)。
- `test_181_fetchnews_denoise_20261007.py`:`_drive` 支持 4 元组 tick(带 `r2_round_id`);
  新增 8 个用例(见 §3.1)。
- `test_228_round_incomplete_20261007.py`:解包由 4 → 5 元组(`scan_marker_log` 返回值加 1)。

## 3. 测试(自验逐项结果)

### 3.1 新增用例(全 PASS)
| 用例 | 断言 | 结果 |
|---|---|---|
| `test_race_fixture_shape` | fixture 真编码竞态(last_run 跳变而 r2_round_id 不变) | PASS |
| `test_race_phantom_plus1_eliminated` | 竞态 tick 判同轮 dup ⇒ 计数止于 2、**无 SEVERE** | PASS |
| `test_race_fixture_counterfactual_would_fire_with_mtime_id` | **反事实**:旧 mtime 标识下同一 fixture 恰在 01:45:02 幻影告警 | PASS |
| `test_race_genuine_three_rounds_still_fires` | 正向对照:3 个**真不同轮**仍 1→2→3 告警(未过度抑制) | PASS |
| `test_block_uses_window_coupled_round_id` | 生产块必含 `r2_round_id` 消费 + 无 `last_round=_r2_lr` 旧写法 | PASS |
| `test_scan_window_round_ts_race_shape` | 数据层:竞态形态 ⇒ 标识锚 01:01(上一轮)非 01:45 | PASS |
| `test_scan_window_round_ts_advances_after_completion` | 新轮收尾后标识推进到 01:45(非「永不前进」⇒ 不会永久 suppress) | PASS |
| `test_scan_window_round_ts_none_when_no_window_start` | 无窗口起点 ⇒ None(消费端回退,向后兼容) | PASS |
| `test_field_name_wired_producer_to_consumer` | 跨文件字段名一致性机检(§22):gen 产 / monitor 消费同名 | PASS |

### 3.2 反事实机检(修向必要性硬证据)
同一 `race_ticks.csv`:
- **旧标识(last_run=mtime,`strip_round=True`)** ⇒ 恰在 **01:45:02** 幻影告警(`fires == ["01:45:02"]`);
- **新标识(r2_round_id)** ⇒ 全程无告警、计数止于 2。
⇒ 证明场景具判别力、且「最新轮次开始/mtime」不足、本修向有效。

### 3.3 回归
| 范围 | 命令 | 结果 |
|---|---|---|
| #181 + #228 | `pytest test_181... test_228... -q` | **46 passed** |
| schedule_monitor 相关 11 文件 | `pytest test_181/160/196/212/223/228/232/240/alertchain_hardening/alert_denoise_20261001/monitor_resource_inprogress -q` | **271 passed, 2 skipped** |
| 全量 | `pytest scripts/tests -q` | **482 passed, 2 skipped**(91.0s) |
| 语法 | `py_compile` ×3 + `bash -n schedule_monitor.sh` + 内嵌 PYEOF heredoc `ast.parse` | 全 OK |

### 3.4 零真实外发自证(§18 L48/L50)
- 测试仅 ast 提取 monitor heredoc 内 r2_skip 状态机**纯逻辑块**(只 append `alerts`/改 `alert_state`
  dict,结构上无 notify/网络/子进程),沿用既有 `test_zero_real_outbound`(打桩 subprocess/urllib/
  socket「一调用即 AssertionError」+ 调用计数 = 0)兜底。**本次自测零真实外发、零 R2 写、零云上写。**

## 4. 影响面

### 4.1 面收敛清单
| 受影响 | 说明 |
|---|---|
| EXTRA 任务(fetch_news / gen_daily_brief)r2_skip 轮去重标识 | 由 mtime → 窗口所属轮 `轮次开始` 时间戳;**`last_round` 状态值格式由分钟粒度 → 带秒**:旧值 = mtime 经 `gen_schedule_stats.py:1181` `strftime("%Y-%m-%d %H:%M")`(**分钟** `YYYY-MM-DD HH:MM`),新值 = `轮次开始` 行经 `gen_schedule_stats.py:198` `_TS` 正则 `\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}` 抽出的**带秒** `YYYY-MM-DD HH:MM:SS`(= `fetch_news.py:585` 真 print 的 `%Y-%m-%d %H:%M:%S`)。**格式迁移面**:因标识粒度 + 标识源同时变更,升级首个 tick 新旧串必不相等 ⇒ 同轮 +1(见 §4.5 升级瞬变,一次性+自愈)。|
| `schedule_stats.json` | 新增 info 字段 `r2_round_id`(前端**不读**,无展示改动) |
| TASKS 表任务(如 overfit_monitor) | `r2_round_id` 缺失 ⇒ 回退 `last_run`,**行为逐字不变**(overfit 89-dup 样本不受影响) |
| `last_run` 语义 / 前端执行统计表 `last_run` 展示 | **不变**(仍 mtime) |
| 阈值 / 保链 / seen 补全 / 清零点 / 恢复循环 / M1 通道 | **零改动** |

### 4.2 §21 算法公示(已核查)
前端 `app.js:33231` r2_skip tooltip 文案为「schedule_monitor 检测**连续多轮** skip 会发 SEVERE
告警」——**无阈值数字**,阈值语义也未变(仍连续 3 轮;本修复只是让实际行为回归该语义)。
⇒ **无需改公示**(已 grep `static-site/app.js` + `purpose-notes.js` 确认无 `r2_skip` 数值公示点)。

### 4.3 §23.3 举一反三(同模式扫描:用文件 mtime 当轮标识 / 同步起跑竞态)
全仓 grep `st_mtime`/`getmtime`(见下表)逐处归类:
| 位置 | 用途 | 是否同模式 |
|---|---|---|
| `gen_schedule_stats.py` EXTRA `last_run`→r2_skip 标识 | **轮标识** | **是(本案,已修)** |
| `schedule_monitor.sh` 心跳/ws `mtime`(L2453/2582) | 活跃/新鲜度(90min/24h 阈值) | 否(年龄阈值 ≫ 秒级竞态) |
| `check_data_gap_alerts.py`(mtime 缓存 + generated_at 新鲜度) | 缓存失效键 / 新鲜度 | 否 |
| `alert_denoise_rules.py` R3 nextday_plan「今日生成」 | 日级「已落盘」判据 | 否 |
| `lock_watchdog.py` / `check_monitor_heartbeat.py` / `check_task_state.py` / `check_data_integrity.py` / `staticdata_write_guard.py` / `r2_upload_async.sh`(stall) / `feishu_ws_listener.py` / `push_schedule_stats.sh`(信息性) / `sensenova-rotate-proxy*.py`(reqdump 排序) | 新鲜度 / stall / 缓存 / 排序 / 信息性 | 否 |
- **结论:mtime-as-round-identity 反模式全仓唯此一处**,已根治;其余均为正当的「新鲜度/年龄/stall/
  缓存」用途(年龄阈值均 ≫ 秒级,同秒起跑不产生计数错配)。
- **M1 通道同类排查**:`round_state`/`round_start_ts` 用**内容**(`轮次开始`)时间戳,且有
  `unit_active_state` + `ROUND_INCOMPLETE_GRACE`/age 双护栏 —— 同秒起跑时 age≈0 或 unit=active 均
  被护栏拦下,**不产生同款幻影**(无需改)。

### 4.4 诚实边界
- `[r2-skip-stale] 保链不计数` 分支仍缺生产样本(承接 tester 报告 §3.2/§6,本修复未触及该分支,留待后续窗口)。
- 边界 fixture 为**构造竞态形态**(行格式逐字取自 `fetch_news.py` 真 print;机制来自报告 §5 生产
  构造性论证 §18 L49),非直接取自云上原始日志切片 —— 但反事实(§3.2)证明该形态具判别力且被真代码驱动。

### 4.5 升级瞬变披露(审查补正 F2,无需改码)

- **现象**:升级部署后**首个 tick**,`alert_state` 里持久化的 `last_round` 是**旧分钟串**
  (`YYYY-MM-DD HH:MM`),而新代码产出**秒串**(`YYYY-MM-DD HH:MM:SS`),二者**必不相等** ⇒ 该 tick
  对**同一轮**误判为「新一轮」,`_r2_n` +1(审查探针 P1 生产实测:`n` 由 1→2)。本质 = 与本案所修**同类**
  的幻影 +1,但触发源是**跨版本格式差异**(非 mtime/窗口异源)。
- **影响半径**:**一次性 + 自愈** —— 该 tick 后状态即写入秒串,后续 tick 同源同格式,回归正常去重;
  唯一恶化解 = 升级恰落在 `n=2` 的链上(则该 tick 把 2→3 ⇒ **多发一次 SEVERE**),此后清零不再复发。
- **现网风险 ≈ 0**:生产样本链 E 在升级前已**清零**(报告 §5.1 dup 行后 SEVERE→清零),升级时
  `n` 从 1 起,远低于阈值 3 ⇒ 不发告警。故**不阻断上线、无需改码**;此处如实披露,备后续任何
  `alert_state` 跨格式迁移复用同一判据时留档。

## 5. 复现命令(只读)
```
# 数据层(竞态形态 ⇒ 标识锚窗口所属轮)
pytest scripts/tests/test_181_fetchnews_denoise_20261007.py -q
# 反事实:旧 mtime 标识仍幻影告警 / 新标识无告警(同 fixture)
pytest scripts/tests/test_181_fetchnews_denoise_20261007.py::test_race_fixture_counterfactual_would_fire_with_mtime_id -q
# 全量回归
pytest scripts/tests -q
```

## 6. 残留后台任务
无(全程无 `moved to the background` 事件)。