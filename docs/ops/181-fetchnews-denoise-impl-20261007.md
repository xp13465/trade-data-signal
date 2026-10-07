# #181 `fetch_news` R2 skip SEVERE 告警降噪 —— 实施报告(①d 方案)

- 日期:2026-10-07
- 分支:`feat/181-fetchnews-denoise-20261007`(base = `d8087f67d`,worktree 隔离)
- 授权:用户已拍板动此冻结面(§23.7),仅实施 **①d**(计数语义治本),**不**实现任何 dial
  (③X=2h 窗口 / ②B 夜间降级均未做,阈值常量未动)。
- 上游:调研判决 `docs/ops/181-fetchnews-denoise-verdict-20261007.md`(本报告独立复算,
  未采信其数字,见 §5)。

## 1. 结论(先说结果)

**①d 实施完成,反事实复算通过:SEVERE 13 → 5(逐时点对上),「SEVERE → 15min 假恢复 → 1h 重报」
循环消失,真持续缺口仍告警(负控通过)。** 回归测试 14/14 全绿,全量 `scripts/tests/` 357 passed / 2 skipped。

## 2. 改动清单(逐行)

单文件 `scripts/schedule_monitor.sh`(79 insertions / 58 deletions,3 处):
bump/前端 min 无关(纯后端监控脚本,不入前端产物)。

### 2.1 常量注释同步(`R2_SKIP_OBS_WINDOW` 语义变更说明)
- `scripts/schedule_monitor.sh:558-566`(`R2_SKIP_OBS_WINDOW = timedelta(minutes=30)` 上方注释):
  `不参与连续计数并清零` → `不参与连续计数【#181(2026-10-07)起保留连续链不清零:旧「滞留即清零」
  会造成「stale 清零 → 下一 tick 假恢复 → 1h 后重报」结构性循环;现唯一清零点 = 本轮无 skip 分支】`。
  **常量数值未变**(仍 `R2_SKIP_CONTINUOUS_THRESHOLD=3` @ L556、`R2_SKIP_OBS_WINDOW=30min` @ L566)。

### 2.2 r2_skip 状态机三改(`schedule_monitor.sh:919-1021`)
原 L916-1001 的 `if _r2_skip_cnt > 0 / else` 两分支重写为:
- **块首注释(919-940)**:补 `[#181 2026-10-07 fetchnews-denoise, ①d 三改]` 说明(根因 + 三改 + 保 else)。
- **① 轮去重(957-963)**:`count_key` 增 `last_round` 字段(= stats `last_run` 分钟串)。
  `_r2_same_round = bool(_r2_lr) and _r2_lr == _r2_prev.get("last_round")`;
  仅 `_r2_fresh and not _r2_same_round` 才 `_r2_n += 1` 并更新 `last_round`。
  → 同一轮被 :00/:15/:30 多个 tick 消费时不再重复 +1(治根因)。
- **② 去假清零(965-1013)**:删除原 `if not _r2_fresh:` 的 `skip_rounds = 0` 滞留清零分支;
  滞留轮改为「保链不计数」(只打印 `[r2-skip-stale] ... 保链不计数(连续 n/3)`)。
- **③ seen 补全(972-973)**:`_r2_n >= THRESHOLD` 时**任何** skip tick(新轮/重复轮/滞留轮)
  都 `seen_keys_this_run.add(f"{task}|r2_skip_alert")` → 通用恢复循环(L1644-1716,本轮不改)
  不再把仍在持续的告警 key 误判「消失」→ 杜绝假恢复 → 1h 重报链断。
- **保 else 清零点(1014-1021)**:`else`(本轮无 skip)分支**原样保留**为唯一合法清零点
  (真恢复入口):`skip_rounds=0` + 新增 `last_round=None`;不 mark seen,交恢复循环发恢复邮件。
- **告警/抑制正文**:未达阈值三态打印(`[r2-skip-dup]` / `[r2-skip-stale]` / `[r2-skip]`);
  SEVERE 文案不变(仍 `连续 {n} 轮`,此时 n 已是真实 distinct 轮数);suppress 分支不变。

### 2.3 未改(边界确认)
- 通用恢复循环 `L1644-1716`:**未改**(①d 只改计数语义 + seen,靠 seen 补全消循环)。
- `gen_schedule_stats.py`(喂数侧 `EXTRA_MARKER_SCANS` / `scan_marker_log`):**未改**
  (r2_skip_count 语义保持「最近轮窗口内 SKIPPED_LOCKED 行数」)。

## 3. 回归测试(新增,防第二份实现漂移)

- 新增 `scripts/tests/test_181_fetchnews_denoise_20261007.py`(14 test)。
- 新增样本 `scripts/tests/fixtures/181/ticks.csv`(372 行,真实生产导出,见 §4)。
- 取用方式=**从 `schedule_monitor.sh` heredoc 里 AST 提取 r2_skip 真源码块**后 exec
  (同一份实现,不抄副本;与 `test_228_round_incomplete_20261007.py` 同法)。
  ⚠ 提取用「原始行切片 + `textwrap.dedent`」而非 `ast.get_source_segment`——后者不 dedent,
  `else:` 伙伴会 IndentationError。
- 覆盖:常量漂移守卫 / 块含 ①d 三标记(且无旧 stale 清零残留) / 13→5 时点 / 每封 distinct=3 诚实性 /
  文案 / 无假恢复循环(恢复恰 5 次) / seen 补全机制级 / dup 不重复计 / 新轮累积 / 滞留保链 /
  真恢复入口 / 负控持续缺口仍告警 / 零真实外发自证 / 断言下限守卫(`_MIN_ASSERTIONS=30`,仿 #201 薄包装)。

命令与结果:
```
$ /Users/linhuichen/code/trade/.venv/bin/python -m pytest scripts/tests/test_181_fetchnews_denoise_20261007.py -q
14 passed in 0.12s
$ /Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/   # = CI 门禁 ⑧ 命令
357 passed, 2 skipped in 12.01s
$ bash -n scripts/schedule_monitor.sh            # BASH_SYNTAX_OK
$ python -c "ast.parse(heredoc)"                 # PY_HEREDOC_SYNTAX_OK lines=2712
```
CI 收集确认:`.github/workflows/ci.yml:112` = `python3 -m pytest -q scripts/tests/`,本测试在
`scripts/tests/` 下 → 必被收集(非孤立测试)。

## 4. 零真实外发自证(§18 L48/L50)

`schedule_monitor.sh` 有真实外发(邮件+飞书+alarm),严格禁跑。
- 本测试**从未 source/exec 业务脚本主体**,只读文件 + exec「从 heredoc 提取的纯逻辑块」
  (该块结构上只 `alerts.append(...)` + 改 `alert_state` dict,**无 notify/网络/子进程出口**)。
- 硬闸:`test_zero_real_outbound` 对 `subprocess.run` / `urllib.request.urlopen` /
  `socket.create_connection` 打桩「一调用即 `AssertionError`」+ 调用计数,驱动全 372 tick 后断言
  `calls==0`。
- **evidence:本次自测零真实外发**(无 email/feishu 发送;无 `/tmp` 外发痕迹)。

## 5. 反事实复算(验收核心,自主完成,未采信报告)

独立重放脚本(static-only)自行从**原始云上日志**重建轮次 + 每 tick 输入表,并用**旧语义模型**
与生产 monitor 日志里**真实事件行**(ground truth,与本模型无关)对账,**93/93 零差集**才认花名册可信
(独立搜得对齐偏移 `o0=797` + 被杀轮 `j=51`(start `2026-10-04T20:01:00`,唯一无 Deactivated 轮),
**未抄报告 b_of_j**)。然后把输入表喂给「从 .sh AST 提取的真代码块」。

| 项 | 旧语义(ground truth 同) | ①d(修复后) |
|---|---|---|
| 事件总行 | 93(skip43/stale20/severe13/recovery13/clear4) | — |
| **SEVERE** | **13** | **5** |
| 恢复 | 13 | 5 |
| OLD 模型 vs 生产真值 | — | **MATCH 93/93** |
| REAL 块 vs ①d 模型 | — | **True** |

修复后 5 封 SEVERE 时点(逐位复算)+ 每封「真实连续 skip 轮」:
| # | 时点 | counted n | distinctRounds | 计入轮(last_run) |
|---|---|---|---|---|
| 1 | 10-04 04:00 | 3 | **3** | 02:45 / 03:01 / 03:45 |
| 2 | 10-04 07:00 | 3 | **3** | 05:45 / 06:01 / 06:45 |
| 3 | 10-04 18:15 | 3 | **3** | 17:01 / 17:45 / 18:01 |
| 4 | 10-05 04:00 | 3 | **3** | 02:45 / 03:01 / 03:45 |
| 5 | 10-05 18:15 | 3 | **3** | 17:01 / 17:45 / 18:01 |

每封 `distinctRounds >= 3` ✓(修复前 13/13 皆 `counted=3, distinctRounds=2`,消息自称 3 轮是假话)。

- **恢复点**:10-04 05:00 / 10-04 08:00 / 10-05 01:15 / 10-05 04:15 / 10-05 19:00(恰 5 次,每事件 1 次,
  非旧的 13 次)。「SEVERE → 15min 假恢复 → 1h 重报」循环**已消失**(实测 fire 后紧邻的 04:15/04:30/04:45
  是 suppress(n=4,seen=True,fire=False),真恢复在 skip 停止的 05:00)。
- **负控(§memory `alert-denoise-keep-fault-discriminator`)**:真持续缺口(每轮皆新轮且 skip ×10)
  → **仍恰好首报 1 次** @ base+1h → 降噪未豁免真故障判别维度 ✓。
- **dup 负控**:同轮被 tick ×3 → `skip_rounds=1`、`alerts=0`(去重生效)✓。

## 6. §23.2 同类错误面清单(修 bug 三铁律·排查同类)

「同轮被多 tick 重复消费 / 滞留误清零 / active 未 mark seen」三类病灶在 `schedule_monitor.sh` 内逐处排查:

| # | 位置 | 模式 | 结论 |
|---|---|---|---|
| 1 | `L947-1013` r2_skip 状态机 | 同轮重复计数 + 滞留清零 + seen 缺 | **本次已修(①d)** |
| 2 | `L759-796` `marker_buffer`(degrade 连续轮) | 连续轮计数,日志尾部窗口跨 tick 同异常被反复计 | **未改**:同模式,但语义是「log 尾部异常跨 tick」(非「任务轮」),且 `dedup_key` 有 6h recurrence-suppress 兜底;**且不在 #181 授权面**。已记录,建议另立任务评估(不在本冻结面擅动)。 |
| 3 | `L376-411` `missed|` 漏跑连续轮 | 连续 2 轮计数 | **安全**:`TOLERANCE=30min` 使每个 sch 最多被查 2 轮,key 含日期+时点独立,且已 `seen_keys_this_run.add`(L381)。非同类。 |
| 4 | `L1046-1062` `extra_stale` | 停摆告警 | **安全**:已 `seen.add`(L1047)。非同类。 |
| 5 | `L1095` `_ri_key`(running-in-progress) | 进行中告警 | **安全**:已 `seen.add`。非同类。 |
| 6 | `L603-619` exit!=0 dedup(`is_stale`) | stale 不触发误恢复 | **安全**:显式 `seen.add`(L616)+ stale 保 active 注释,已按正确 semantics。非同类。 |
| 7 | 喂数侧 `gen_schedule_stats.py` `scan_marker_log`/`EXTRA_MARKER_SCANS` | r2_skip_count 来源 | 语义未变(未改);同轮窗口说明见 §2.3。 |

**根因层**:本次未逐文件打补丁,而是在唯一消费点(r2_skip 状态机)做「轮标识去重 + seen 补全 + 保链」
三件治本;其余同模式面(#2)已定位并上报,不越权改冻结面。

## 7. §23.3 举一反三清单(同模式/同数据源/同组件 + 相关展示位)

- **同数据源(r2_skip_count)**:消费方唯一 = `schedule_monitor.sh` r2_skip 状态机(grep
  `r2_skip_count` 仅 .sh L920/941/976/993 + gen L1055/1100)。喂数侧语义未改,无第二消费方。
  任务覆盖面:`stats` 循环覆盖 TASKS 表任务 + EXTRA(fetch_news/gen_daily_brief),改动对**所有**
  任务生效(fetch_news 之外如 intraday 等一并受益,行为不退化——高频任务本就恒新鲜)。
- **同组件(告警去重/恢复链)**:`{task}|r2_skip_rounds`(计数 key)+ `{task}|r2_skip_alert`
  (去重 key)+ 通用恢复循环(`L1644-1716`)。三件已互校对:计数 key 不写去重 key;告警 key
  seen 补全后恢复循环只在 else 清零点判消失。
- **相关展示位**:本文为纯后端监控脚本,不入前端产物(app.min.js/lab.js/sw.js 零改动),
  不存在「用户可见展示位」一致性问题(§22 不适用);无 §21 算法公示对象(非评分/算法逻辑)。
- **同模式跨文件**:见 §6 #2(已上报)。

## 8. §23.4 同模块扫描(开工前)

`docs/pending-features-index.md` 同模块(schedule_monitor.sh / alarm chain)活跃项:
- #181(本任务)、#217①(不同文件,互补)、#223(M1 已入 base,diff 只碰别处)、#228/#229/#230。
- 结论:**无文件级冲突**;`schedule_monitor.sh` 近期改动(#228 M1)已在 base 且不碰 r2_skip 块。
  续跑遵循原 feat 分支。

## 9. 残留风险

1. `marker_buffer`(#6-2)同模式面未修,**可能仍有类似重复计数/未 seen 假恢复**——已上报主控,
   建议另立任务(需评估其 log-tail 语义是否真的同病,避免误改)。
2. ①d 使滞留轮 `skip_rounds` 保链不归零:若某任务**长期滞留(永不运行)**且历史链未清零,
   计数停在某值但 `>= 阈值` 时也会持续 mark seen → 不重复报,但也**不会自动恢复**(直到本轮无 skip)。
   评估:滞留=「本轮无新运行」,任务彻底停摆由 `missed|`/extra_stale 两个独立告警覆盖,不靠本链;
   `else` 清零点(L1014)在任务恢复运行的下一轮即触发真恢复 → 无长期卡死风险。
3. 阈值仍是 3(未做 dial):若后续仍嫌多,可按用户拍板再上 ③X/②B(本次未做)。

## 10. 可逆性

- 纯单文件改动(`scripts/schedule_monitor.sh`)+ 新增测试/样本,`git revert <commit>` 即回退;
  `alert_state` 仅新增 `last_round` 字段(旧代码不读它,回退后自然忽略)+ 计数语义,无数据迁移。
- 恢复路径:`git revert` 该 feat commit(或 `git checkout <base> -- scripts/schedule_monitor.sh`)。

## 11. 落档四件套

- 本体:本报告。
- 代码:`scripts/schedule_monitor.sh`(①d)。
- 测试+样本:`scripts/tests/test_181_fetchnews_denoise_20261007.py`、`scripts/tests/fixtures/181/ticks.csv`。
- 配套 commit:见分支 `feat/181-fetchnews-denoise-20261007`(hash 见交接)。
- 复现:见 §3 命令块;提取器逻辑见测试文件 `_heredoc_lines`/`_raw_seg`。