# a_fund_main 凌晨 45min 误报环:核实 + 最小修法(2026-10-12)

> 执行:implementer 子 agent(worktree `agent-a3e38ce1838393e7e`,分支 `worktree-agent-a3e38ce1838393e7e`,base=origin/main `28380a78f`)。
> 边界:改动**只在 worktree 内**(代码 + 新增测试),**未 push / 未 merge / 未动 main**;云上全程只读(ssh 查询,零写入);未跑任何采集/业务脚本本体(探针一律 static-only)。
> 上游:`docs/ops/alert-night-triage-20261012.md`(取证报告);本文件=按该报告结论做**代码级证实/证伪 + 修法**。

## 0. 速答(对应派单 4 问)

1. **链路实证 = 证实**(不是证伪)。报告说的「打印静默 vs 计入统计不一致」**成立**:凌晨槽分支既打「静默」又在**数据库层**写 `status='error'`(`scripts/backfill_direct_metrics.py:140`,旧行号 `:126`)。
2. **环成立条件 = 已用云上时间序列坐实**(02:22→02:52 首次 notify,每 15min 一跳、每 3 跳一条,45min 精确对齐;`count.json={"a_fund_main":2}`)。**额外发现**:该环自 2026-10-08 就存在,只是 notify 路径有 pre-existing `NameError` 崩溃(#241 B 波 10-09 17:57 才修)⇒ 10-08/10-09 静默、**10-12(修复后首个交易日)首爆**。
3. **最小修法一句话**:把凌晨结构性预期缺口从 `log_collect(..., "error")` 改成 `log_collect(..., "warn")`(单点,1 行行为改动 + 注释)。
4. **反证结果 = PASS**:非凌晨槽 6 源全败 / 配置缺失 / 抛异常仍写 error + 计 fail(exit 1);`warn` 行不被 retry 拾取(环断)、`error` 行仍被拾取(真故障照报)。
5. **止血选项**:有(给 retry 的 notify 加长 dedup),见 §5,与治根取舍见该节。
6. **自测**:新增 10 用例 + 相关既有 4 测 + 全 `scripts/tests` 套件 = **765 passed / 2 skipped**,见 §6。
7. **改动文件**:`scripts/backfill_direct_metrics.py`(改)+ `scripts/tests/test_fundmain_morning_gap_no_retry_loop_20261012.py`(新增)。

## 1. 链路实证(逐环节 `文件:行` + 关键代码 + 云上证据)

四环节,`A → B → C → D`,闭环。

### A. 谁把「02:00 槽预期缺口」写进失败/gap 记录 —— `scripts/backfill_direct_metrics.py`

凌晨槽判定与缺口归属(现 L123-140):
```python
if morning:                                   # _is_morning_slot(): BACKFILL_SLOT 存在 且 实际时点 < 05:00
    gap += 1
    print(f"[gap] {mid} {msg} (02:00 槽预期缺口, 静默)", flush=True)
    log_collect(date, mid, "error", msg)      # ← 断点: 打印说「静默」, DB 却写 error
else:
    fail += 1
    print(f"[fail] {mid} {msg} (非凌晨槽多源全败=真故障, 计入退出码)", flush=True)
    log_collect(date, mid, "error", msg)
```
- 「静默」= **只对退出码**(`gap` 不计 `fail` → `return 1 if fail else 0` → exit 0 → `schedule_monitor` 退出码维度看不见);
- 「error」= **数据库层事实**(`app/collector/base.py:151 log_collect` 无条件 `INSERT` 进 `collect_log`)。
- **结论:报告「打印静默与计入统计不一致」= 证实**。这不是"静默",是"只静默了退出码、没静默 DB"。

云上证据(2026-10-12 02:00 槽):
- `data/logs/backfill_20261012_0200.log:503` `[gap] a_fund_main direct:market_fund_flow 多源皆败无数据 (02:00 槽预期缺口, 静默)`;`:504` `=== direct metrics 补采 ok=2 gap=1 fail=0 ===`(exit 0)。
- `collect_log` 实查:`('20261012','a_fund_main','error','direct:market_fund_flow 多源皆败无数据','2026-10-12T02:17:42')` —— **error 行确已落库**。

### B. 谁据此重试 —— `scripts/retry_failed_metrics.py`(每 15min,由 `self_heal.sh:39` 驱动)

```python
# get_failed_metrics(): 只取最新一条、只认 status=='error'
rows = conn.execute("SELECT metric_id, status, message FROM collect_log WHERE run_date=? ORDER BY run_at DESC", (date,))
...
if r["status"] != "error":     # 仅豁免 msg 含「指数今日数据缺失」且 index_daily 已有当日 close 的一类
    continue
```
- 无任何「凌晨槽预期缺口」豁免(消息串 `direct:market_fund_flow 多源皆败无数据` **与真故障同串**,retry 层**无法区分** —— 这正是不能只在 retry 侧修的原因,见 §4)。
- `self_heal.sh` 每 15min(`Minute=7/22/37/52`)调本脚本;非交易日跳过(故 10-10/10-11 周末零重试)。

云上证据:audit log 每 15min 一轮 `[retry] 20261012 发现 1 个 error 指标: ['a_fund_main']` → `[fail] a_fund_main: ... (原 error: ...)`。

### C. 谁发通知 —— `scripts/retry_failed_metrics.py:_notify_repeat_failure`(连续 3 轮)

```python
n = counts.get(mid, 0) + 1
if n >= RETRY_NOTIFY_THRESHOLD:            # = 3
    if _notify_repeat_failure(mid, n, today, msg):   # 调 notify.py(邮件+飞书), 送达才返回 True
        counts.pop(mid, None)                        # ← D: 送达后清零
    else:
        counts[mid] = n
```
云上证据:`retry_failed_metrics_count.json` = `{"a_fund_main": 2}`(当前累计 2,下轮达 3 → 再发)。

### D. 谁把计数清零 —— 同上 `counts.pop(mid, None)`(送达即清零)

清零后下一轮从 0 重新累计 ⇒ 再 3 轮 ⇒ 再发。「清零→再计→再重试→再发」= **环**。

云上证据(`self_heal_audit.log`):
```
[notify] a_fund_main 连续 3 轮失败已发通知     (02:52:25)
...                                            (03:37:18 / 04:22:18 / 05:07:18 / 05:52:25)
[notify] a_fund_main 连续 3 轮失败已发通知     (06:37:19)
```

## 2. 环的成立条件 + 支持证据

**成立条件(全部满足才成环)**:
1. 凌晨槽(02:00)对该 direct 指标判为「结构性预期缺口」**且仍写 `status='error'`**(A);
2. `retry_failed_metrics` 每 15min 跑(self_heal)、**非交易日跳过**(所以周末不复利);
3. retry **必然失败**(目标日=当日收盘后才有数据/该槽本就无用)→ 连续 3 轮必达阈值(C);
4. 通知**送达后清零**(D)→ 计数重新累计;
5. `collect_log` 的 error 行**在 16:35/21:00 兜底槽成功前一直存在**(成功槽会 `DELETE ... status<>'ok'` 清掉)→ 环整夜+整个上午持续。

**时间序列对齐(02:00 起,每 15min 一跳,每 3 跳一条 = 45min)**:
| 时刻 | 事件 | 证据 |
|---|---|---|
| 02:17:42 | A 写 error 行 | collect_log run_at |
| 02:22 / 02:37 / 02:52 | B 三轮重试失败 → **C 首次 notify** | audit log;ledger#19 = 02:52:17 |
| 03:07…05:52 | D 清零后再累计,每 45min 一条 | ledger#20-23 = 03:37 / 04:22 / 05:07 / 05:52 |
| 06:37:19 | 第 6 条 | ledger#24;count.json 归 `{"a_fund_main":2}` |
| 07:07 起 | 仍在跑(截至核查时刻) | audit log 07:07:22 |

**为何 10-12 才「新增/首爆」(关键,报告未点透)**:该 notify 路径自 2026-09-30(#131,`0a42e6bac`)起有 **pre-existing `NameError: name 'subj' is not defined`**(`_notify_repeat_failure` 组 cmd 时用了未定义名 `subj`),在 **2026-10-09 17:57**(#241 B 波,`192800415`)才修。证据:
```
2026-10-09 03:22 audit log:
  [fail] a_fund_main: direct:market_fund_flow 多源皆败无数据 ...
  Traceback ... File ".../retry_failed_metrics.py", line 145, in _notify_repeat_failure
    NameError: name 'subj' is not defined
```
即:环自 **10-08 起每个交易日都在**(retry 发现 a_fund_main error 的次数:10-08=27 轮 / 10-09=36 轮 / 10-12=20 轮),只是 notify 处崩溃 → **静默**;10-09 傍晚修好后,**10-12 成为首个 notify 真正生效的交易日 ⇒ 45min 环首次「响」**。这解释了「最大**新增**来源」的真实机理 = 修好 notify 反而暴露了这个此前静默的环。

## 3. 最小修法(治根)

**单点改动**:`scripts/backfill_direct_metrics.py` 凌晨槽分支
```diff
                 if morning:
                     gap += 1
                     print(f"[gap] {mid} {msg} (02:00 槽预期缺口, 静默)", flush=True)
-                    log_collect(date, mid, "error", msg)
+                    log_collect(date, mid, "warn", msg)     # + 17 行说明注释
```
理由:
- **在计数层(DB status)而非仅打印层豁免**:retry 只认 `error`,写 `warn` 后 retry **永不拾取** → 重试/通知环**从根断**;
- `warn` **仍进 `collect_health`**(`app/queries.py:1765` 判 `status != "ok"` 即计入 item)⇒ 保留 **#84 reviewer P1-1**「让 collect_health 通道反映」的原意,只是 level 由红(error)降黄(warn);
- **与既有约定一致**:`app/collector/index_backfill.py:246` 对同性质「补后仍缺」早就写 `warn`(既有先例,非新发明);`app/collector/base.py:151 log_collect` 接受任意 status 串;前端 `static-site/app.js:16434` 只为 `error/disabled` 建「采集异常」灰卡(`warn` 不建),且 `a_fund_main` 本就是 KPI 卡(`_existingKpiIds` 命中)⇒ **无新增前端灰卡**;
- **不改判据**:`else` 分支(非凌晨槽 6 源全败)与异常分支**一字未动**(见 §4 反证)。

## 4. 影响面量化 + 反证(硬要求:保留真故障判别维度)

### 4.1 改后会不会掩盖真故障?—— 不会。豁免极窄,只覆盖「凌晨槽 + 结构性预期缺口」一种情形

| 场景 | 改前 | 改后 | 是否仍告警 |
|---|---|---|---|
| 凌晨槽结构性预期缺口(目标日=当日、T+1 源) | 红点 + 45min 环 | 黄点,**无环** | 否(本就不该报) |
| **非凌晨槽(16:35/21:00)6 源全败 = 真故障** | error + fail + exit1 + schedule_monitor SEVERE | **不变** | **是** ✅ |
| 凌晨槽**非 gap** 失败(no config / direct:* error / 抛异常) | error + fail + exit1 | **不变** | **是** ✅ |
| **数据连续多日没进来**(真断供) | — | **不变**:`check_data_gap_alerts.check_fund_freshness`(checker 9)按 `daily_metric` MAX(date) 落后 ≥2 交易日 WARN / ≥5 SEVERE | **是** ✅ |
| 其他指标真失败 | retry 重试 + 3 轮 notify | **不变**(retry 只认 error 的逻辑未动) | **是** ✅ |

**关键**:豁免条件 = `BACKFILL_SLOT 存在 && 实际时点 < 05:00 && msg 含「多源皆败无数据」`,即代码**早已**判为「不算 fail」的那一类;改动只是让**DB 状态**与**退出码判定**口径一致(此前二者矛盾)。**真故障判别维度(非凌晨槽/非 gap/数据断供)全部落在未改动的分支上。**

> ⚠️ 诚实标注(本题唯一「变小」的可见面):02:00~16:35 之间,若当天 6 源在凌晨确实无数据,前端 `collect_health` 由**红点降为黄点**。这属**改掉一个误报**(凌晨结构性缺口本非 error),但**是已上线功能的可见行为变更** ⇒ 需用户拍板(见 §8)。

### 4.2 反证:构造「真坏」场景,证明改后仍会响

用可执行测试反证(见 §6 文件 `test_fundmain_morning_gap_no_retry_loop_20261012.py`):
1. **非凌晨槽真故障**:`BACKFILL_SLOT=2100` + 6 源全败 → 实测 `log_collect` 写 **error**、`exit=1`(照常告警)✅;
2. **凌晨槽非 gap 真失败**(`direct:market_fund_flow error: HTTP 403`)→ 写 **error**、`exit=1` ✅;
3. **凌晨槽抛异常** → 写 **error**、`exit=1` ✅;
4. **环断正面**:凌晨槽写出的行直接喂给 `retry.get_failed_metrics()` → 返回 `[]`(不被拾取 ⇒ 无重试 ⇒ 无通知)✅;
5. **环断反面**:同一 DB 里放 `error` 行 → 被拾取、`a_fund_main` 命中(真故障照报)✅。
   (用例 1/4 在**旧代码上必 FAIL** —— 已实测红前绿,见 §6。)

## 5. 止血 vs 治根(取舍)

**治根(§3,本次已实施,推荐)**:凌晨槽 error→warn。改动 1 行 + 注释,**单文件**;彻底消除误报 error 行(环消失、红点转黄点),同时保留 collect_health 反映。代价 = 前端可见面变化(红→黄),需用户拍板。

**止血(仅掐环、不动判据;备选,未实施)**:保留凌晨槽写 error 的现状,只在 `retry_failed_metrics._notify_repeat_failure` 给通知加长去重窗(notify.py 原生支持 `--dedup-key/--dedup-window`):
```diff
     cmd = [sys.executable, str(_ROOT / "scripts" / "notify.py"),
-           subject, body, "--from-prefix", "[告警]"]
+           subject, body, "--from-prefix", "[告警]",
+           "--dedup-key", f"retry_failed_{mid}", "--dedup-window", "21600"]   # 同 mid 6h 内至多一条
```
- **效果**:3 轮检测照旧(真故障仍会在 ~45min 内首次通知),但**同一 mid 6h 内不再重复**⇒ 环从「每 45min 一条」变「至多 ~3-4 条/天」,**判据与 DB 状态一字不改**(前端红点不变)。
- **取舍**:①治根**更彻底**(从源头消灭误报 error,DB 与退出码口径一致),但**动可见面**需拍板;②止血**完全不碰可见面、不碰采集层**,风险最低,但**保留**「凌晨结构性缺口仍被记为 error」这一口径矛盾(每天上午仍短暂红点),且对**任何**连续失败的 mid 都会 6h 才响一次(含真故障 ⇒ 真故障首报会被 delayed 抑制?**不会**:首报在 6h 窗内第一次即发,只是后续重复被压)。
- **建议**:若用户接受「凌晨结构性缺口不算 error」这一口径修正 → 用治根;若用户希望**零可见面变化**先止血 → 用止血(可后续再治根)。两者**不冲突**,可先止血上线、治根另行拍板。

## 6. 自测结果(全部实跑)

| 命令 | 结果 |
|---|---|
| `pytest -q scripts/tests/test_fundmain_morning_gap_no_retry_loop_20261012.py`(新增 10 用例) | **10 passed** |
| **红前绿**:临时把改动回退为 `error` 重跑上测 | **1 failed / 9 passed**(`test_morning_gap_writes_warn_not_error` FAIL:实际 error)⇒ 用例有判别力,非空转 |
| `pytest -q` 新测 + `test_132_morning_slot.py` + `test_241_family_b_retry_metrics_20261009.py` + `test_132_count_file_fail_loud.py` + `test_132_self_heal_mutex.py` | **38 passed** |
| `pytest -q scripts/tests`(全量套件) | **765 passed, 2 skipped**(93.97s) |
| `python -m py_compile scripts/backfill_direct_metrics.py` | OK |

**零外发**:新测全程不触 notify / 不 spawn 子进程,并用 `ZeroOutboundTrap` 包裹断言 `hits==[]`(§18 L48)。

## 7. 同类错误面清单(§23.2 根因修,非逐文件打补丁)+ 举一反三(§23.3)

**同根因(「预期缺口误记 error」)全站排查**(grep 所有 `log_collect(..., "error")` 站点):
- `scripts/backfill_direct_metrics.py:140` —— **唯一命中**(本次修)。
- `app/collector/index_backfill.py:246` —— 同性质「补后仍缺」**已写 warn**(早合规,无需改)。
- `app/collector/runner.py:189/197/207/216/219`、`app/backfill.py:79`、`app/collector/index_backfill.py:838`、`app/collector/intraday_snapshot.py:1714+` —— 均为**真失败/异常**(17:50 主采集后、盘后该有数据;intraday 另有一段注释显式「不 log error 消除红点误判」)⇒ 保持 error 正确,**不动**。
- 结论:**单点根因修**,无同族漏网;不新增去重/抽象(`§6.5 少写抽象`)。

**举一反三(同数据源/同组件还被谁用)**:
- 本次改动作用于**所有 `direct:` 指标**(代码按 `func.startswith("direct:")` 通用,不特指 a_fund_main)。当前 `config/indicators.yaml` 的 direct 指标:`a_fund_main`(`:61`)、`a_fund_north`(`:47`)、`a_fund_north_quarterly`(`:55`)—— 三者共用同一凌晨槽分支,修复**自动覆盖**;若未来新增 direct 指标亦自动受益(无需再改)。
- 下游消费方:`retry_failed_metrics`(已断开)、`queries.collect_health`(warn 仍反映)、前端 `app.js`(warn 不建灰卡)。**无第三个消费方依赖「凌晨槽 error」**。

## 8. 待用户拍板 / 交接(§23.7 冻结契约)

1. **治根动到已上线可见面**(collect_health 红→黄),按 §23.7 需用户确认后才可合并上线。本改动**已备好但未 push/未 merge**(worktree 内)。
2. **止血选项**(§5)若用户偏好零可见面变化,可改用/并用。
3. **上线时机**(若拍板治根):云上需 `git pull` 拉新脚本 + 无需重跑数据(collect_health 由 export 实时从 DB 算,非落盘产物)。**时点**:避开盘后 15:35/16:00/17:50/20:35/22:00;本脚本由 `backfill-evening` timer 02:00/16:35/21:00 调用 ⇒ 换脚本本身无冲突,但 merge/push main 须走 `main-merge.sh`(主控职责)。
4. **登记**:`docs/pending-features-index.md` 未见本条立项(#250=gap 自测/#251=公募回填/#252=trades 断档,均非本条)⇒ 建议由主控新登记(编号由主控定)。

## 9. 附:核实用到的原始证据命令(只读,可复核)

```bash
# A: 02:00 槽日志 [gap] 行 + exit
ssh -i /Users/linhuichen/tdsignal.pem ubuntu@122.51.111.173 \
  'grep -n "a_fund_main" /home/ubuntu/code/trade-data/data/logs/backfill_20261012_0200.log | head'
# A: collect_log error 行
ssh ... 'python3 -c "import sqlite3;c=sqlite3.connect(\"file:/home/ubuntu/code/trade-data/data/sentiment.db?mode=ro\",uri=True);print(c.execute(\"SELECT * FROM collect_log WHERE run_date=? AND metric_id=?\",(\"20261012\",\"a_fund_main\")).fetchall())"'
# C/D: 计数 + notify 序列
ssh ... 'cat /home/ubuntu/code/trade-data/data/retry_failed_metrics_count.json; grep "notify] a_fund_main" /home/ubuntu/code/trade-data/data/logs/self_heal_audit.log'
# 为何 10-12 首爆: 10-09 的 NameError traceback
ssh ... 'sed -n "11520,11536p" /home/ubuntu/code/trade-data/data/logs/self_heal_audit.log'
```

## 10. 诚实标注(边界)

- 只读边界:未执行任何采集/业务脚本;云上零写入;python 仅只读查 DB/日志;无 push/merge。
- 「10-08/10-09 环数」取 audit log `retry 发现 a_fund_main error` 计数(27/36 轮),为「发现轮数」口径,未逐轮核对是否每次都 fail(机制上 retry 发现 error 即重试)。
- 未验证:16:35 槽是否**必然**清掉该 error(取决于当天 16:35 是否采集成功;若 16:35 也失败则走 fail/SEVERE 另一条通道)——不影响本修法成立。