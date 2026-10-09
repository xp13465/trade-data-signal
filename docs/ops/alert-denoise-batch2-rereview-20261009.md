# #240 告警降噪第二批 —— 复审修复「二次确认」报告

**审查者**:reviewer agent(第二轮独立复审,全程只读,零外发)
**审查对象**:分支 `worktree-agent-a53be26f39c0827d8`(feat,已 push 远端)
- 新 commit:`57148888b`(代码+测试)、`c9bf6c7cc`(报告+索引)
- 上一轮基线:`a477d48b8`;上一轮报告:`docs/ops/alert-denoise-batch2-review-20261009.md`(F1~F4 判据出处)
- 改动全集(`git diff main...branch --stat`,8 文件):`scripts/alert_denoise_rules.py` / `scripts/check_failed_units.py` / `scripts/schedule_monitor.sh` / `scripts/tests/test_240_alert_denoise_batch2_20261009.py` / `scripts/gen_schedule_stats.py` / `scripts/check_data_gap_alerts.py` / 报告 / 索引。**`scripts/notify.py` 零改动**(已用 branch-vs-main 全量 stat 核实 ⇒ 「冻结面未动」属实)
**方式**:`git show <branch>:<path>` 逐字读分支版本(不切分支)+ 本机独立跑测试(绿/红两态)+ 全仓 grep 影响面;**未 ssh 云上、未跑任何生产脚本、未触任何真实外发**
**日期**:2026-10-09

---

## 0. 结论摘要(逐项)

| 项 | 上轮判据 | 本轮结论 | 关键证据 |
|---|---|---|---|
| **F1** 落签判据(必修) | rc==0 不可信 ⇒ 全渠道失败仍落签 = 当天失报 | **PASS(已根治)** | `_notify_sent`(:216)三判据与 notify.py 实际输出形态**逐字一致**;全渠道失败 resol 到 False ⇒ 不落签(:405-412,test_02e 锁死) |
| **F2** dur=None 盲区(必修) | 恢复环把 pending 桶静默翻 recovered ⇒ 盘中 900~1800s 结构性静默 | **PASS(已根治)** | 恢复环豁免(:1771)只命中桶键;真键 `<task>|dur>Ns` 恢复链路原样;陈旧保护 + 三条新用例锁行为;1 run/日 灵敏度保回 |
| **F3** 文案/数字/基线(低) | docstring 21600 过时 / 红绿数字不符 / 复现钉 HEAD | **PASS** | docstring `--dedup-window 0`(:51)+F1 说明;报告 §6 数字 = 本机实测 **6 failed / 22 passed** 逐位一致;§8 改 `git show 491bda2d9:` |
| **F4** 同类面补齐(低) | ② 的 21600 同类面清单不完备 | **PASS(上轮点名 4 文件已补)** | `upload_r2.py:1761/3669/3699`、`with_lock.py:128`、`staticdata_sync.sh:158/171/177/189/249`、`staticdata_backup_async.sh:128/263/276/290/302/398` 全部核对为真 |
| 回归 | — | **PASS** | 新用例 28 passed;基线源红 6 failed/22 passed;引用改动模块的既有 7 套测试 164 passed/1 skipped |

**merge 建议**:**建议 merge(F1/F2 两必修均已根治,红绿独立复现,无阻塞项)**。本轮新发现 5 条**全部为低**(文档措辞/观察项/维护耦合/既有同根项),不阻塞;其中 P-1、P-5 是**文档级**顺手订正(1~2 行),P-3 是**非本批引入**的同根既有问题(建议单列小任务)。

---

## 1. 逐项核验记录

### F1 落签判据 —— PASS

**(a) 解析器对 real notify.py 输出形态的覆盖率(逐一比,非读注释)**

本调用签名为:`notify.py <subject> <body> --severe --from-prefix "[告警]" --dedup-key failed_units_patrol --dedup-window 0`(`scripts/check_failed_units.py:241-262`)。据此把 `scripts/notify.py` main() 的全部出口**穷举**了一遍:

| 可能的出口 | 条件 | 输出形态 | `_notify_sent` 判 | 一致? |
|---|---|---|---|---|
| `--flush-warnings` | 未传 | — | — | n/a |
| `--tier` 分支 | 未传 | — | — | n/a |
| `--agent-done` | 未传 | — | — | n/a |
| R4 `staticdata_backup_fail` | key 不等于该值 | — | — | n/a |
| R7 `r2_consistency` | key 不等于该值 | — | — | n/a |
| **#196③ 升级档 CRITICAL** | `_ESCALATE_CHANNELS`(:2306)命中 `failed_units_patrol` 且连续≥3 天 | `[notify][196] 升级档路由完成：{results}`(:2335) | 取 marker 后首个 `}` 前段含 `True` ⇒ True | ✓(与 notify 自己 `_tier_send_ok(critical)` 同判据) |
| #196③ 升级档 suppress | 同上 + `check_dedup(esc_key, window)` | `[notify][196] 升级档窗口内已发, suppress`(:2325) | 无三标记 ⇒ False | ✓ 且**本调用不可达**(window=0 ⇒ `check_dedup` 恒 False,`notify.py:1256-1257`) |
| **通用路径成功** | 上述均不命中 | `[notify] 汇总：已发出 {ch}`(:2359) | `已发出` ⇒ True | ✓ |
| **通用路径全败** | 同上 | `[notify] 汇总：全部渠道未发出（…）`(:2362) | `全部渠道未发出` ⇒ False | ✓ |
| 通用路径 dedup suppress | `check_dedup(key, 0)` | — | — | **不可达**(同 window=0) |
| 未捕获异常 / rc≠0 | — | traceback | 无标记 ⇒ False | ✓(fail-safe 方向正确) |

- **「已发出」不会与「全部渠道未发出」同帧出现**(通用路径二选一;升级档路径 early return 不发通用汇总行)⇒ 判据优先级无歧义。
- 三处标记字符串**逐字节比对一致**(`notify.py` ↔ `check_failed_units.py` 同为全角冒号 `：`)——已用 Python 字符串包含性实测确认。
- 主体/标题文本**不会**污染判据:notify.py 只在 dry-run 里打印 body(:900),`--notify` 路径不打印 body;标题虽会出现在部分失败行(:633/:659),但 `check_failed_units` 的标题是固定文案 + 计数 + 时间,不含三标记。

**(b) fail-safe 的代价量化(本轮重点问)**

- 方向对(宁重不吞):认不出 ⇒ False ⇒ 不落签 ⇒ 下轮重试,不吞真故障 ✓。
- 代价上界:该脚本每 **15min** 一轮(`schedule_monitor.sh:1720` 每 tick 子进程调 `--notify`,96 次/日),且 `--dedup-window 0` 已把 notify 侧兜底窗关掉 ⇒ **若将来 notify.py 新增一条「会真发但不打印现有标记」的路径,退化为每 15min 一封 = 96 封/日**(不是失报,是轰炸)。
- **现状不触发**:上表穷举表明当前全部真发路径都有标记覆盖 ⇒ 无需扣分,但属**维护耦合**(见 P-4 观察项)。
- 反方向(误判为已发出 ⇒ 当天失报)也核了:True 只在「ok 非空」(:2361)或升级档 dict 含 `True` 时产生,与 notify 自身占窗判据同源 ⇒ 无假 True。

**(c) 「daily-first 会不会退化成每天都发」**:不会——真发出路径 `sent=True` ⇒ 写签名状态 ⇒ 当日同集合仍被 `failed_units_daily_judge` 抑制;只有「真失败」才重试(那本来就该重试)。test_02e 把「全渠道失败 ⇒ 不落签 + 第二轮仍调用」锁死(calls==2 + 状态文件不存在 + `trap.hits == []`)。

**(d) 其它**:`notify.py` 零改动 ✓(冻结面);`detail` 截尾 300 字仅用于日志,判据用的是**全量输出**(`_send_notify:261-262`)✓。

### F2 dur=None 盲区 —— PASS

**(a) 豁免只命中桶键,真告警键恢复链路原样保留** ✓

- 桶键 = `f"{task}|dur_buffer|{thresh}"`(:934 构造 / :1000 复位构造),命中 `adr.DUR_BUFFER_KEY_MARK = "|dur_buffer|"`(alert_denoise_rules.py:96)。
- 真告警键 = `f"{task}|dur>{thresh}s"`(:921),**不含**该标记 ⇒ 恢复环(:1763 起)对它照常处理:`pending` 静默恢复、`active` 走 `recoveries` 出恢复邮件(:1820-1840 区间逻辑未改)。全仓 grep `dur_buffer` 仅命中 `alert_denoise_rules.py`(常量)+`schedule_monitor.sh`(构造/复位/豁免/日志)+ 测试 ⇒ 无第三处耦合。
- 恢复环的豁免位置正确(`:1771`,在 merge/r2-summary 前缀 skip 之后、`status=="pending"` 分支之前 —— 位置错则豁免失效,test_03c 用源码索引断言 `loop < 豁免 < pending` 锁死)。

**(b) 24h 陈旧保护正反核** ✓

- 正向(防滞留):`last_seen` 距今 >24h ⇒ 按新建处理 ⇒ 停跑/稀疏任务恢复运行时,不会拿陈年计数假达阈(test_03e:4 天前的桶 + 单轮超阈 ⇒ 不报,count 归 1,并刷新 last_seen)。
- 反向(会不会让停跑任务的桶**永滞留**):核了 —— 桶键**无论改前改后都永久留在 `alert_state.json`**(改前只是状态被翻成 `recovered`;`alerted` 状态在改前同样不被恢复环处理,`status != "active"` 直接 continue)。即:改后唯一差异 = 停跑任务的桶状态停在 `pending/alerted` 而非 `recovered`。消费方核查:`monitor_72h.sh:800` 只处理 `72h_` 前缀 ⇒ 不碰;`alert_ack.py` 只加 acknowledged;`notify.py`/`deploy.sh`/`check_data_gap_alerts.py`/`check_s06_freshness.py` 只读**指定键**/指定前缀 ⇒ **无消费者会因此改变行为**(仅文件里多一条 pending 记录,与 `marker_buffer` 桶同构先例)。判定:非新问题,可接受。
- 解析异常兜底:last_seen 格式坏 ⇒ `except (ValueError, TypeError)` ⇒ 按陈旧处理(方向=宁少勿误报)✓。

**(c) 修法与我上轮建议的差异(需点名)**:我上轮建议的 (a) 是「桶记 last_run + 同一 run 重复观测不增计数」;实施选了**不按 run 去重**,改为「观测轮次」计数,并在代码注释(:596-599)与报告 §0.1 诚实标注残余:同一超阈 run 被连续两轮观测(**且中间无新 run 介入**,典型=盘后单槽/午休)会被计为 2 ⇒ SEVERE。评估:**理由成立**(盘后 20:35 单 run/日的槽靠这一途径才能达阈;按 run 去重会把盘后真退化降回静默),且该残余 = **#240③ 之前的旧行为**(旧代码单轮即报)⇒ 不是新引入的假阳性,属可接受的灵敏度保留代价。**接受该修法**。

**(d) 灵敏度是否真恢复**(修的核心目的):核了计数状态机 —— 复位只发生在「观测到 ≤ 阈值的已完成 run」(:997 复位分支);`dur=None` 的 tick 现在既不复位也不清 seen(豁免),任意两次超阈观测(可跨 dur=None tick)即可达 2 ⇒ 比修复前严格放宽,「连续 2 轮」不再结构性不可达。`≥2×阈值` 单轮立即报的旁路未动(:935)。

### F3 文案/数字/基线 —— PASS(附一条低分残余)

| 子项 | 核验 |
|---|---|
| `check_failed_units.py:51` docstring `--dedup-window 21600` → `0` | ✓(并补了 F1 说明,:55-57) |
| 报告 §6 红绿数字 | ✓ 本机独立复现 = **6 failed / 22 passed**(与新报告逐位一致;上轮报告误写的「2 failed/1 passed」已订正) |
| 报告 §8 复现基线 | ✓ 已改为 `git show 491bda2d9:...` 并写明「HEAD 会漂移」 |
| 报告 §0.1 F2 引用的行号(:600/:934/:938-947/:963/:971/:1000/:1771) | ✓ 逐一核对全部命中(仅 `last_run` 实际在 :962 而非 :963,无碍) |

- **残余 P-1(低)**:`check_failed_units.py:221-222` 的 docstring 写 `notify.py:2368`(已发出)/`notify.py:2371`(全部渠道未发出),**实际是 :2359 / :2362**;而同一文件 :55/:219/:250 又写 :2362(正确)⇒ 同文件内自相矛盾(P-1 详见 §3)。

### F4 同类面补齐 —— PASS(上轮点名项全中)+ 残余 P-5

- 独立 grep 复核上轮点名的 4 个文件与行号:**全部为真**(`upload_r2.py:1761/3669/3699`、`with_lock.py:128`、`staticdata_sync.sh` 5 处、`staticdata_backup_async.sh` 6 处)。
- 形态判定抽查(`upload_r2.py:1761`、`staticdata_sync.sh:158`)维持「事件驱动/成功即静默」结论 ⇒ **「不需同款改造」的方向结论不变** ✓。
- **残余 P-5(低)**:报告自称「`grep -rn 21600 scripts/` **全量命中 10 个文件**」,**实测为 14 个非测试文件**(见 §3 P-5),说明措辞应改为「已核查 N 处」而非「全量」。

---

## 2. 红绿与测试独立复核(不信自述)

```bash
WT=/Users/linhuichen/code/trade/.claude/worktrees/agent-a53be26f39c0827d8
PY=/Users/linhuichen/code/trade-data/.venv/bin/python
# ① 新版绿
cd $WT && PYTHONDONTWRITEBYTECODE=1 $PY -m pytest -p no:cacheprovider \
  scripts/tests/test_240_alert_denoise_batch2_20261009.py -q      # → 28 passed in 0.40s ✓
# ② 基线(491bda2d9)监控源红 —— 红先绿后
git show 491bda2d9:scripts/schedule_monitor.sh > /tmp/pre240_monitor_491bda2d9.sh
cd $WT && SCHEDULE_MONITOR_SH=/tmp/pre240_monitor_491bda2d9.sh PYTHONDONTWRITEBYTECODE=1 $PY \
  -m pytest -p no:cacheprovider scripts/tests/test_240_alert_denoise_batch2_20261009.py -q
# → 6 failed, 22 passed(失败:test_03/03b/03c/03d/03e + test_99 断言数兜底 54<58)✓ 与报告逐位一致
# ③ 回归面:引用改动模块(alert_denoise_rules / schedule_monitor.sh / check_failed_units)的既有 7 套
cd $WT && $PY -m pytest -p no:cacheprovider -q scripts/tests/test_196_patrol_visibility_20261005.py \
  scripts/tests/test_232_marker_buffer_20261007.py scripts/tests/test_181_fetchnews_denoise_20261007.py \
  scripts/tests/test_228_round_incomplete_20261007.py scripts/tests/test_alertchain_hardening_20261003.py \
  scripts/tests/test_alert_denoise_20261001.py scripts/tests/test_monitor_resource_inprogress_20261005.py
# → 164 passed, 1 skipped in 2.09s ✓
# ④ 零外发:三处子进程调用点已逐行核实安全 —— test_02c(dry-run 子进程)、test_196(CFU 无 --notify + --repo tmp)、
#    test_160(本次未跑,见下);跑完本机 git status 干净(两棵树均无新增文件/pycache)✓
```

- **测试用例是否「真锁行为」而非第二份实现** ✓:`test_03c/03d/03e` 用 `ast.get_source_segment` 从 `schedule_monitor.sh` **真源码**抽块(`_dur_block()` 抽 `if _dur is not None` 整块 + `_in_progress_state` + 常量;`_recovery_loop_code()` 抽恢复环 For 节点,全文件仅一处候选 `:1761`,目标名 `_key/_info` 唯一)⇒ exec 的是生产代码,不是副本。
- **新用例是否测坏既有行为** ✓:`test_03c` 带对照键(`other_task|dur>900s` pending 仍被静默恢复)、`test_03e` 带陈旧反例、`test_03` 带真退化反例(2081s 盘后照报、≥2× 单轮照报)⇒ 负控方向正确。
- **未独立复跑**:①全量 `scripts/tests/`(自述 439 passed/2 skipped;主控若需可让 tester 补跑,注意 `scripts/test_160_*` 会真跑 `check_r2_consistency.sh` 包装器,本机有真实凭据环境,我按「零外发」硬约束**未跑**)②`check_data_gap_alerts.py --self-test`(自述 PASS,非本批 diff 面)。**算术旁证**:428→439 = +11 用例 = 新增用例数(17→28)✓ 自洽。

---

## 3. 新问题清单(severity + file:line)

> 全部**不阻塞 merge**;P-1/P-5 为文档级,P-2/P-4 为观察/维护项,P-3 为**非本批引入**的同根既有问题(按 §23.7⑤ 上报通道,不当本次 finding 但也绝不静默)。

### P-1【低·文档】`check_failed_units.py:221-222` 引 notify.py 行号错(2368/2371 实为 2359/2362)
- trace:`diff_range=57148888b scripts/check_failed_units.py:221-222`;`linkage=不满足`(F3 修正只做了主项,漏了这两行);`user_request=reviewer_own`
- verifier:`command=grep -n "汇总：已发出\|汇总：全部渠道未发出" scripts/notify.py`;`expected=2359/2362`;`observed=2359/2362`(文件内 :55/:219/:250 写的是 2362,与这两行自相矛盾)
- over_engineering:`action=simplify`;`saves_lines=0`;`rationale=改两个数字或直接删行号(行号会漂,措辞锚点足够)`

### P-2【低·观察】F1 的「响亮打日志」在生产调用链被父进程吞掉
- 事实:`schedule_monitor.sh:1720-1726` 用 `capture_output=True` 调 CFU,rc=1 分支**只打印子进程 stdout**(`_cfu_out`),而 `check_failed_units.py:412` 的「告警未发出(不落抑制,下轮重试)」在 **stderr** ⇒ 渠道全失败时,monitor 日志显示的是「云上 unit 异常(**自身通道已发告警**)」(与实际相反),未发出明细不进任何日志。
- 性质:**rc 语义标签是既有行为**(改前同样显示「已发」;改前更糟——当天直接失报),本次改动**没有让它变差**,但「响亮」这一自述在生产链上打了折。
- 建议(非阻塞,任选其一):CFU 把该行同时打到 stdout;或 monitor rc=1 分支附加 stderr 尾部。可与 P-3 合并成一个「告警链 sent 语义收口」小任务。

### P-3【低·既存同根,§23.7⑤】`check_s06_freshness.py:135` `sent_ok = proc.returncode == 0` 与 F1 同根(守卫空转)
- 证据:`check_s06_freshness.py:135` + `:126-134` 调 `notify.py --tier warning` ⇒ notify 的 tier 分支(`notify.py:2189-2198`)恒 `return 0`(含 `defer_status='append_failed'`)⇒「发送成功(rc==0)才落盘去重状态」的守卫**在 append 失败时也成立** ⇒ 该轮告警既没进聚合 buffer、状态又被记为已告警 = 该状态后续被抑制(静默丢失)。
- **非本批引入**(#188 F3 的历史实现),但正是 F1 的同一病根(拿 rc 当 sent 判据)⇒ §23.3 举一反三应覆盖。
- 建议:单列小任务(修法与 F1 同构:解析 tier 分支的 `defer_status`);**不要**塞进本批(会扩大 diff 面)。

### P-4【低·维护耦合/watch】`_notify_sent` 依赖 notify.py 打印文案,无机检护栏
- 现状:三标记覆盖穷举已核尽(§1 F1a)⇒ 今天正确;但 notify.py 新增一条「真发但不打印现有标记」的路由时,本调用会退化为**每 15min 一封(96/日)**(比失报更刺眼,但同样要避免)。
- 建议(可选):在 notify.py 汇总行附近加一行契约注释(「改此文案须同步 scripts/check_failed_units.py:_notify_sent」),或在 CFU 里把「判不出形态」单独计数打点,便于生产首日观察;本批**不必**做。

### P-5【低·文档】报告 §0.1/§2 自称「21600 全量命中 10 个文件」不准确
- verifier:`command=grep -rn "21600" scripts/ | grep -v "scripts/tests\|scripts/test_"`;`expected=报告口径 10 个文件`;`observed=**14 个非测试文件**`,报告未列:`notify.py`(R4 强制窗 :2231)、`retry_failed_metrics.py:109`、`r2_upload_async.sh:243`、`r2_upload_skip_notify.sh:51`、`schedule_monitor.sh:1676/2822`。
- 抽查方向结论仍成立(事件驱动/自带分档/非同一状态定时重报);但「全量」措辞应改为「已核查 N 处」,或把 5 处补进表并各给一句形态判定。
- trace:`diff_range=c9bf6c7cc docs/ops/alert-denoise-batch2-20261009.md §0.1 F4`;`linkage=部分满足`;`user_request=reviewer_own`

---

## 4. 影响面清单(grep 改动文件被谁引用)

| 改动文件 | 消费者 | 影响判定 |
|---|---|---|
| `alert_denoise_rules.py`(+常量 1 个) | `schedule_monitor.sh`(桶键构造/复位/豁免三处共用)、`check_failed_units.py`、`notify.py`、各测试 | 纯新增常量 ⇒ 无行为变化;两文件需**同 commit 上线**(已满足) |
| `schedule_monitor.sh`(dur 块 + 恢复环) | 自身主循环;alert_state 消费方 5 个脚本 | 豁免 `continue` 只命中 `|dur_buffer|` 键(已核全仓无第三处构造点);恢复环对其它 key 行为**逐位不变** |
| `check_failed_units.py` | `schedule_monitor.sh:1720`(每 15min,rc 映射 0/1/3/else) | 返回码语义未变(仍 1=发现异常);新增「未发出」路径见 P-2 |
| `alert_state.json` 结构 | `monitor_72h.sh:800`(只碰 `72h_`)、`alert_ack.py`、`notify.py`(指定键) | 桶新增 `last_run`/`last_seen` 字段 ⇒ 均按 dict 透传,无 schema 校验 ⇒ 兼容 ✓ |

---

## 5. 规范判定(独立)

- **§21 公示**:不适用(后端监控脚本,未动用户可见算法/评分/权重)。
- **§22 一致性**:不适用(无用户展示位数据产物;alert_state 是内部状态,非多展示位源)。
- **§24 防撕裂**:不适用(零前端源/min/SW/版本串;未 bump=正确)。
- **§23.2 修 bug 三铁律**:F2 是结构性缺陷 ⇒ 修在机制层(不再靠「记得 add seen」的口头约束),√;F1 同类面(rc 当 sent)见 P-3(既有面,已上报)。
- **§23.3 举一反三**:F4 补齐动作符合上轮点名;穷举自述仍不完整(P-5)。
- **§23.7 冻结契约**:F1 明确「notify.py 一字未动」并已核实 ⇒ 正确选择(rc 契约是全项目共享面)。
- **§10.4 静默失败专查**(diff 含 `except Exception`):`_send_notify` 的宽捕 ⇒ 返回 False + 明细 + 主流程打日志 + 下轮重试,**未吞**;`_write_sig_state` 落盘失败 ⇒ 打日志 + 显式说明「下轮或重复报一次, 不吞真故障」√;陈旧保护解析异常 ⇒ 方向保守 √。唯一「不可见」面是 P-2(父进程吞 stderr),已列为低项。
- **§10.6 删除清单**:本轮改动无「可删冗余」项(`_notify_sent` 三判据均为必要分支;豁免/陈旧保护各锁一个已复现缺陷)。

---

## 6. 置信度过滤说明

- 进正文:5 条(全为低分但均带 trace/verifier;本次任务明确要求给「新问题清单」,故按低分档一并列明而非仅报数)。
- 已滤(<80)2 项:
  1. `test_02e` 对「旧代码」的判别力偏弱(它 stub 掉 `_send_notify`,靠**文案断言**才在旧码触红)⇒ 真红绿判别来自 `test_02d` + `:262` 绑定静态核实(置信 60,不影响结论);
  2. `monitor_72h.sh` 与 `schedule_monitor.sh` 均整文件读写 `alert_state.json`、无跨进程锁 ⇒ 理论上存在「后写覆盖前写」的丢更新(可能让桶计数偶发回退)⇒ **既有结构性问题**(所有 key 同暴露,`marker_buffer` 先例同款),非本批引入,置信 60 不上报为 finding,记录备查。

---

## 7. 复现命令(本次审查)

见 §2 代码块(①绿 ②红 ③回归面 ④零外发核查)。另:

```bash
# 解析器覆盖穷举(静态)
grep -n "汇总：已发出\|汇总：全部渠道未发出\|升级档路由完成\|_ESCALATE_CHANNELS = {" scripts/notify.py
#  → 2359 / 2362 / 2335(196) / 2306
# 豁免范围核查
grep -n "dur_buffer" scripts/schedule_monitor.sh scripts/alert_denoise_rules.py
# 真键不含标记
grep -n '_dur_key = f"\|DUR_BUFFER_KEY_MARK in _key' scripts/schedule_monitor.sh
```

**报告落档**:本文件(主控统一收;审查者未 commit / 未 push / 未切分支 / 未改任何业务文件;两棵 git 树跑测后 status 干净)。
