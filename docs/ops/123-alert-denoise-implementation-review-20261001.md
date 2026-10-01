# #123 告警降噪 R1~R6 实施独立审查报告(2026-10-01,reviewer)

> 审查对象:分支 `worktree-agent-af1e103df45f2939c` HEAD `6ff3c0bad`(已 push origin;未 merge main)
> 审查者:独立 reviewer(非实施者),全只读,不 commit 不改代码
> 判定:❌ **FAIL**(R5 命中头号判据「降噪静默真故障」;另有 R1 恢复循环交互误报 caveat)
> 权威口径:docs/ops/alert-denoise-design-20261001.md(设计,只读)+ 云上 09-30 latest.md/monitor 日志
> 头号判据(memory alert-denoise-keep-fault-discriminator):构造「看起来像噪音但其实是真故障」反例拿真实代码实测,不许只读报告;每条对冲规则(R1 30min 必响/R2 新 last_run 再响/R3 双保险/R4 连续2天 SEVERE/R5 首条照发+grep 出实现行)逐条找实现行。

## 结论

**FAIL**。六条规则(R1~R4/R6)经真实函数测试 + 调用点行号核对基本正确,但 **R5(同根因日汇总)存在双重致命缺陷**,与实施报告 §2.1「R5-A 同日多条→首条直发其余并入汇总」声称直达相反:

1. **R5 修改的 alert_state 不落盘 → 同轮第 2+ 种 R2 告警被吞且永久静默**(对 schedule_monitor 每轮独立进程而言,`r2_pipeline_congestion|{YYYYMMDD}` 状态从未持久化);
2. **R5 只在 `if alerts:` 内调用 → 23:25 收尾轮 alerts 为空时 R5 根本不运行,汇总永不发出**。

两者叠加:09-30 报告反复提到的「同轮 3 封 R2 告警(14:15/23:00 类)只发 1 封」场景,其余 2 封既无即时告警也进不了汇总 = 真故障被静默,与 memory `alert-denoise-keep-fault-discriminator` 警告的降噪翻车模式完全一致。修复需「R5 无条件调用(不在 if alerts 内)+ 调用后 save_alert_state」双修(experiment3 证明单修任一都不够),见报告末节。

caveat(不阻塞本轮但应修):**R1 与恢复循环交互误报**——恢复循环(L1178-1200)把 pending buffer key 置 recovered 但不清 consecutive_count,导致「滞后→恢复→再滞后」跨 3 轮被误判连续 2 轮发 SEVERE(测试脚本 r1_sim 未模拟恢复循环,测试盲区)。另:台账 #123 状态为 09-29 第一轮(6a6d7a173),本次 R1~R6 补强(6ff3c0bad)未登记,需主控补记。

---

## 1. 真故障反例实测(头号判据,全部真实代码)

### 反例①:R5 跨轮状态不持久化 → 每轮当首条照发,23:30 汇总缺失

```bash
# /tmp/review_r5_persist_test.py:模拟 3 轮独立 monitor 进程(每轮加载文件→处理→保存),
# 每轮 1 种 R2 告警(09-30 14:15/21:00/23:00 同源场景的跨轮版)
```
输出(已实跑):3 轮全部 `kept=[首条]`、summary=None,**第 2/3 种 R2 告警从未进任何汇总;`schedule_monitor.sh` 尾部(L2250-2273)只有 heartbeat 写入与 `--flush-warnings`,无 `save_alert_state`**(全文件 save_alert_state 仅 6 处:L1281/1450/1722/1809/1950/2088,全在 R5 调用点 L2151 之前;R5 修改后在 L2151-2176 写 `alert_state[_sk]` 但无任何落盘)。

### 反例②:同轮 ≥2 种 R2 告警 → 第 2+ 种永久静默(不落盘=进程退出即丢)

```bash
# /tmp/review_r5_same_round.py:同一轮 3 种 R2 告警,调真实 r5_congestion_process
```
输出(已实跑):`kept` 只剩首条,去重后 `summary=None`(14:30 未到 23:25)→ 第 2/3 种从 alerts 移除但**只在进程内存**,该轮结束即丢 → **真故障永久静默,用户不可见**。实施报告 §2.1 声称「R5-A 同轮 3 种→23:25 收尾轮出汇总」在真实代码路径下不成立。

### 反例③:即使修复持久化,`if alerts:` 条件仍让收尾轮汇总不发

```bash
# /tmp/review_r5_persist_patch.py:模拟「R5 状态已落盘」的修复版,23:30 收尾轮 alerts 为空
```
输出(已实跑):`alerts == []` 时不进入 L2150 `if alerts:` → r5_congestion_process 不调用 → 汇总永不生成。**必须「无条件调用 + save」双修**;且 r5_congestion_process 内部 bug 叠加:传入 `{}` 空 alert_state 时 `len(_st["phenomena"]) >= 2` 恒 False,即使调用也无汇总可出。

### 反例④:R1 恢复循环交互误报(滞后→恢复→再滞后,假 SEVERE)

```bash
# /tmp/review_r1_recover_loop.py:模拟真实执行序(恢复循环 L1178 先于 overview 块 L1402)
```
输出(已实跑):
```
轮1(lag): act=buffer, buffer状态=recovered, count=1   ← 轮1 末尾恢复循环已把 pending 置 recovered
轮2(恢复): act=ok, buffer状态=recovered, count=1        ← 恢复路径不清 recovered 状态的 count
轮3(再次lag): act=alert  ← 误报!count=1+1=2 触顶
```
根因:恢复循环(L1188-1194)对 pending 且未 seen 的 key 置 recovered **但不清 consecutive_count**;r1_buffer_judge 恢复路径(L56-59)只清 `status in ("pending","alerted")`,而恢复循环已把 pending 改成 recovered → 状态错位,count 残留。测试脚本 `r1_sim`(test L46-63)直接连调 r1_buffer_judge 未插入恢复循环,「R1-C 单轮滞后后恢复→不响」断言没覆盖「恢复后再滞后」的跨轮场景,是测试盲区。

---

## 2. 六条规则实现行核对(§1 审查点③④,逐条 grep)

| 规则 | 判定函数(alert_denoise_rules.py) | schedule_monitor.sh / notify.py 调用点 | 核对结果 |
|---|---|---|---|
| R1 overview 连续轮 | r1_buffer_judge L39-79(§报告称 L37-77,行号偏 2) | overview_lag_3domain 块 L1402;r2_overview_lag 块 L1578/L1611 | ✓ 两处均实调;阈值 2 轮=30min;buffer key 带 YYYYMMDD;恢复路径清 buffer |
| R2 超时/耗时合并 | r2_merge_key/already_sent/mark/cleanup L82-121 | dur 通道 L723/738;timeout 通道 L926/942;cleanup L1171;恢复循环跳过 merge\| L1181 | ✓ 双通道同 (task,last_run) 合并;last_run 提取 `s.get("last_run")` 正确;隔日新 last_run 新 key 独立再响;merge key 24h 清理 |
| R3 nextday 去重 | r3_nextday_product_generated_today L124-142 | exit!=0 通道 L495 | ✓ 产物今日生成→monitor 去重;未生成→双保险双响;mtime 按日判定 |
| R4 staticdata 分级 | r4_staticdata_grade L145-209(§报告称 L143-207,行号偏 2) | notify.py L2106 拦截块(`args.dedup_key == "staticdata_backup_fail"`)+ L2110 调用 + L2111 check_dedup(21600) | ✓ dedup 强制 21600(覆盖 CLI 3600);心跳 ok+ts>=上次 fail=追平 info;连续2天 SEVERE;心跳缺失保守未追平;send_tiered critical L2116/info L2121 |
| R5 R2 拥堵日汇总 | r5_is_r2_congestion_line L212-231;r5_congestion_process L234-281(§报告称 L210-269,行号偏 2) | L2151 调用(L2150 `if alerts:` 内),L2152-2154 追加 summary 后发信 | ❌ **双重致命缺陷**(见 §1 反例①②③):调用后有状态修改但无 save;且只在 if alerts 内调用 |
| R6 kelly/fetch 保留 | 未触碰 | kelly/fetch_news 走原通道 | ✓ 非 R2 行不进聚合,直发保留 |

另:报告 §1 声称 R5 在「L2151-2176」调用——L2151 确认是 r5_congestion_process 调用行,但报告未提 L2150 的外层 `if alerts:` 条件与 R5 后无 save 落盘,这两点是致命缺陷所在。

## 3. 09-30 15→8 条逐条复核(审查点⑤)

按报告 §2.2 表逐条核对代码行为(非仅文字):
- staticdata×4(#1/#2/#3/#6):r4_staticdata_grade 单日未追平→info + check_dedup 21600 窗口 suppress → 0 SEVERE ✓(报告标 3 suppress + 1 info;行为=不推送,与「0 邮件」目标一致;08:49 距 00:53 超 6h 会再走 grade 仍 info,报告 §0 已诚实标注差异)
- us_stock×2(#4/#5)/backfill×2(#14/#18)/intraday×2(#10/#12):R2 同 last_run merge → 各 1 条 ✓
- s06(#11)/kelly(#7)/fetch_news(#13):独立 key 保留 ✓
- overview×2(#8/#9):R1 单轮 buffer 不响 ✓(09-30 次日如出现「滞后-恢复-再滞后」会误报,见 §1 反例④)
- nextday×2(#15/#16):R3 自身通道保留+monitor 去重 ✓
- **R2 直连(#17 23:00)**:R5 场景,「首条照发」✓ 但这是因 R5 状态不落盘每轮当首条——若 23:00 轮内同时有第 2 种 R2 告警,该告警永久静默(R5 缺陷)
- 结论:15→8 的数字本身成立;但「无一条是静默」的 §3 声称对 R5 场景不成立(见反例②)

## 4. §23.10 飞书抄送与邮件一致性(专项核)

- R4 拦截:critical 走 send_tiered(TIER_CRITICAL, L2116)→ send() 全渠道(邮件+飞书同源);info 走 log_info(L2121)→ 只记 dashboard 不推送 → 无「邮件发飞书不发」分叉 ✓
- R5 汇总走通用 alerts 通道(notify.py 无 feishu 参数,send() 按既有渠道)→ 与邮件来源一致 ✓
- 结论:不违反 §23.10

## 5. §15 回归/影响面(审查点⑦)

- schedule_monitor.sh 8 处 adr. 调用点(含 heredoc 顶部 import)已逐一核对,未波及其他告警路径;r2_/72h_ 前缀恢复跳过逻辑保留
- notify.py:仅 staticdata_backup_fail 一个 dedup_key 走 R4 拦截(L2106),通用 dedup L2133 不受影响 ✓
- #132 重叠面(审查点⑨):#132 是 #131 资金面监控 3 条残留(02:00 槽假 SEVERE/self_heal 并发/计数写失败静默),与本改动文件(schedule_monitor/notify.py/alert_denoise_rules.py)无重叠、无冲突 ✓

## 6. 回退办法(审查点⑩)

实施报告 §6 整体 revert 可行(单 commit `6ff3c0bad` 原子:alert_denoise_rules.py 新文件删除 + 两脚本调用点回归,无半态);但**建议不整体回退**——R1-R4/R6 是正确收益,只撤 R5:删 L2150-2158 的 R5 处理块 + alert_denoise_rules.py 中 r5_* 两函数即可(恢复循环跳过 r2_pipeline_congestion| 前缀的 L1181 行同步删)。

## 复现段

- 测试脚本(实施侧):`scripts/tests/test_alert_denoise_20261001.py` 26 项断言,PASS(已重跑确认;注意 R5 断言 r5_sim 直调不落盘场景,故 PASS 不代表调度侧正确)
- R5 缺陷实测(本审查):`/tmp/review_r5_persist_test.py`(跨轮)/`/tmp/review_r5_same_round.py`(同轮)/`/tmp/review_r5_persist_patch.py`(修复版仍不发)
- R1 误报实测(本审查):`/tmp/review_r1_recover_loop.py`(滞后-恢复-再滞后=误报 alert)
- 关键代码位:schedule_monitor.sh L2150(`if alerts:`)+ 文件尾 L2250-2273(无 save);save_alert_state 全表 L1281/1450/1722/1809/1950/2088;r1_buffer_judge L56-59(恢复路径只清 pending/alerted)

## 结论摘要(给主控)

**FAIL,推荐:撤 R5 保留 R1-R4/R6 后 merge;或修复 R5 =「无条件调用 + 调用后 save_alert_state」双修后复审**。R1「滞后-恢复-再滞后」误报建议同批修(r1_buffer_judge 恢复路径或恢复循环对 buffer key 清 consecutive_count)。台账 #123 需补记本次 R1~R6 补强 commit。
