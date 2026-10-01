# #132 复审修复(第二轮)独立审查报告 — FAIL

分支: `feat/132-monitor-fixups-20261001` | commit: `fd3bbdaa3` | 审查: reviewer(独立复现,未改代码)
审查基线: 从 fd3bbdaa3 起(reviewer 本报告落 `feat/132-review2-20261001`);复现环境: `git archive fd3bbdaa3` 导出 /tmp/rev132b 隔离运行(不碰生产 data/buffer/lock)

## 结论: FAIL

本轮修复(对上一轮 C-1/C-2/C-3 三条 caveat)方向正确、dry_run 零污染、通用路径契约未动、报告订正属实;
但 **C-1 修复引入新的 P0 缺陷**:`_tier_send_ok` 的 warning 档判据恒真,「buffer 写失败」场景下消息**既没进 buffer 又占了 dedup 窗**——真告警被静默吞,正是 #123 R4「不是真发出就占据 dedup 窗」的同款翻版。且最坏场景恰是本修复的目标场景(retry_failed_metrics 写失败告警在磁盘满时自吞)。**必须修复后重新 review,不 merge。**

---

## 1. [FAIL·最高优先] `_tier_send_ok` warning 档 = 假成功占窗(#123 R4 翻版)

### 1.1 「已本地处理」的精确实现
`send_tiered` warning 分支无条件 `return {..., "deferred": True}`(notify.py L2023-2026),**`defer_warning(...)` 返回值被丢弃**;
`_tier_send_ok` warning 档 = `bool(res.get("deferred"))`(L2047-2048)→ **恒 True**,与 buffer 是否真的写入**零相关**。

### 1.2 buffer 写失败实测(独立构造,非读码臆测)
构造 `/tmp/rev132b/data/alerts/warning_buffer.jsonl` 为目录(append 必失败),跑真实 CLI:

第一次触发 `--tier warning --dedup-key rev2_test_abc --dedup-window 3600`:
```
[notify] jsonl 写入失败 warning_buffer.jsonl：[Errno 21] Is a directory: .../warning_buffer.jsonl
[notify][warning] buffer 追加失败（不入队、不登记指纹状态，后续同源将继续尝试）：REV2-测试-告警A
[notify][tier=warning] 路由完成：{'tier': 'warning', 'email': False, 'telegram': False, 'feishu': False, 'deferred': True}
[notify][dedup] 更新 key=rev2_test_abc last_alerted=now
```
→ `data/notify_dedup.json` 写入 `rev2_test_abc.last_alerted`(**占窗**)。消息**未进 buffer、未发任何渠道**。

第二次同 key(窗口内):
```
[notify][dedup] suppress key=rev2_test_abc last_alerted=... age=10s < window=3600s, 不重发
[notify][tier=warning] dedup 窗口内 suppress key=rev2_test_abc
```
→ return 0;buffer 目录仍 **0 条目**。→ **消息既没送达又占了窗,窗口内该 key 真告警全部被静默吞**。

### 1.3 buffer 有无「保证最终送达」路径
正常路径有:flush_warning_batch 发送成功才清已发条目、失败留下轮重试(L1788-1813)——写进 buffer 的条目**有**送达路径。
但本缺陷路径的条目**根本没进 buffer**,无任何送达可能;且窗口内下一次同 key 调用在 `send_tiered` 之前就被 `check_dedup` 挡掉(notify.py L2111),连 defer_warning 的「下轮重试」都进不去。

### 1.4 修复方 docstring 辩护不成立(两套 dedup 混淆)
`_tier_send_ok` docstring(L2038-2042)称「dedup 占窗只压制重试轰炸,不吞掉本轮到 buffer 的条目」——**实测证伪**:
- defer_warning **内部指纹 4h 窗**(warning_dedup_state.json):追加失败不登记状态 → 同源可重试(这一半是对的);
- main() **层通用 notify_dedup.json 窗**:`update_dedup` 被恒真判据无条件调用 → `check_dedup` 把后续同 key 调用挡在 `send_tiered` **之前**,「下轮重试」通道被堵死。
两套窗,修复方当成一套论证,结论方向错了。

### 1.5 最坏场景 = 本修复的目标场景反噬
`retry_failed_metrics.py` L107-109 的写失败告警 = `--tier warning --dedup-key retry_fm_count_file_write_fail --dedup-window 21600`。
**磁盘满** → 计数文件 `_save_counts` 写失败 → 触发写失败告警 → 同一磁盘满导致 warning_buffer.jsonl 也 append 失败 → 假成功占 6h 窗 → **用户收不到任何「计数文件写失败」告警,6h+ 静默**。
#132 修复的初衷(写失败必须 fail-loud)被本缺陷直接反噬,与 #123 R4 事故(灾备失败告警被静默吞一整天)同构。

### 1.6 正确修法(给实施方)
warning 档判定须基于「真实入队 / 真实抑制」:defer_warning 返回可区分结果(如 `deferred`/`suppressed`/`failed`),或 `send_tiered` 把 defer_warning 的真实处理结果放进 res;
`_tier_send_ok` warning 档只对「已入 buffer 或同源指纹抑制(真已处理)」返回 True,**追加失败/未入队绝不 update_dedup**。与 #123 R4 的判据(`severe 任一真实渠道发出才占窗`)同一把尺子。
另:test_132_notify_tier_dedup.py 8 项全 PASS 但**无「buffer 写失败」反例**,需补(§23.2 同类覆盖)。

---

## 2. [FAIL 附属] 引入「真告警被抑制」回归
构造「同 key 先失败后恢复再失败」时序:第一次 buffer 写失败 → 假占窗 → 恢复后窗口内再失败 → 被 suppress 吞(实测 1.2 的第二次调用即此形状)。
对照通用路径 L2157-2205 契约:通用路径**只有真实渠道发出才占窗**(`and ok`),失败不占窗 → 恢复后可重发。tier 分支 warning 档破坏了同契约。**修复前不占窗(无此抑制),修复后引入 → 本次改动新增的回归。**

---

## 3. 三个既有线上调用方(独立 grep 验证)

### 3.1 实施断言属实(独立 grep,非照抄)
- `scripts/with_lock.py` L114:`--tier warning --dedup-key with_lock_block_timeout:{lockpath} --dedup-window 21600`
- `scripts/staticdata_sync.sh` L248:`--tier info --dedup-key staticdata_sync_oversize_skip --dedup-window 21600`
- `scripts/staticdata_backup_async.sh` L394:`--tier info --dedup-key staticdata_backup_oversize_skip --dedup-window 21600`
全仓 `--tier` 调用方共 7 处(另 check_s06_freshness/schedule_monitor/self_heal 不带 dedup-key,行为不变),无任何调用方依赖「--tier 不去重」。

### 3.2 (a) 定性:修复未生效的设计意图,非改动已上线行为
三处调用方**自己注释写明期望去重**:staticdata_sync.sh L245「保留 dedup 防刷」、backup_async.sh L389「保留 dedup 防刷」、with_lock.py L112-114 注释。调用方显式传 `--dedup-key` + `--dedup-window` = 期望生效,只是 notify.py bug 让它静默失效。修复 = 让参数生效,**不算动已上线功能行为**。

### 3.3 (b) 6h 窗压掉 with_lock 排队超时
with_lock 自身注释(L111-113)声明:排队超时是 warning 级(高概率自愈),**真锁死(排队任务互相饿死)由 schedule_monitor exit/产物时效/进行中超时通道兜底不掩盖**,被跳过任务的漏跑检查按连续轮独立兜底。
→ 6h 一报是调用方自选的窗口(21600 自己传的),且真故障有其他通道兜底,**不构成「压掉真告警」的新风险**。
**判断:本条不需要用户拍板**(前提=修正第 1 条 FAIL 后;否则 6h 窗从「意图内降频」变成「故障场景意外吞告警」,性质变了)。

---

## 4. dry_run 修复:零污染 ✓ 闭环
- 独立重跑 `scripts/test_132_notify_tier_dedup.py`(8 项)全 PASS(tmp 目录隔离,走 notify.main 真实 CLI)。
- 独立实测:dry-run warning×2 + critical×1 后,`warning_buffer.jsonl` / `warning_dedup_state.json` / `notify_dedup.json` **全部不存在** → 真零污染。
- `defer_warning` dry_run 短路在**函数最前**(notify.py L1666-1669),早于一切状态副作用(buffer/指纹状态/日志)✓。
- 附带(非 finding,pre-existing):`log_info` 不接 dry_run,info 级 dry-run 仍写 info_log.jsonl(仅 dashboard 不推送)。C-2 修复范围=warning,不受影响。

## 5. 回归:契约未动 ✓
- `test_notify_dedup.py` 15 项 OK(含 test_u10 钉死「defer_warning 返回恒 True」)。
- `test_notify_flush_race.py` 6 OK、`test_notify_feishu_retry.py` 8 OK、`test_notify_reply.py` 3 OK。
- notify.py diff 仅 4 个 hunk(53 行增减),通用路径 L2185-2205(check_dedup + `and ok` + update_dedup)**未出现在 diff** → 未动 ✓。
- defer_warning 返回语义:dryn_run 短路返回 True 保持恒 True 契约,其余路径 return True 逻辑未动 ✓。

## 6. 上一轮 3 条 caveat 闭环情况
| caveat | 状态 | 证据 |
|---|---|---|
| C-1 `--tier` 丢 dedup-key | **部分闭环** | dedup 真生效了,但 warning 档判据引入假成功占窗(第 1 条 FAIL),且补了通用 dedup 后 `_tier_send_ok` 判据有 bug |
| C-2 dry_run 污染 | **闭环** | 第 4 节实测零污染 |
| C-3 代价评估错误 | **闭环** | 第 7 节订正与实测一致 |

## 7. C-3 报告订正 ✓ 与实测一致
订正段(docs/ops/132-monitor-residuals-20261001.md)声明:
- 原评估「仅下轮多一轮计数」**不实**;
- 实测写失败持续期间每轮重复阈值告警(3 轮 3 封),机制=`先通知后落盘` + 落盘失败文件保留旧值 → 下轮 reload 又达阈值;
- 定性 pre-existing(旧代码同样重复),本 diff 未新增;
- 新增=写失败独立告警(6h dedup)+ 阈值重复告警双通道叠加;
- 重复通知改否 = 待拍板项 A(补 `--dedup-key retry_fm_threshold_{mid}`)。
与上一轮复审实测(3 轮 3 封 `[告警][重采失败]`)逐项一致 ✓。

## 8. 发现的问题清单(分级)
| 级 | 问题 | 证据 | 建议 |
|---|---|---|---|
| P0 | `_tier_send_ok` warning 档恒真,buffer 写失败 → 假成功占窗 → 真告警被吞(#123 R4 翻版) | 1.2 独立实测:append 失败仍 update_dedup,窗口内同 key 第二次被 suppress,消息未进 buffer | defer_warning 返回可区分结果,仅「真入队/真抑制」才 update_dedup;补写失败反例测试 |
| P1 | 同 key「先失败后恢复再失败」时序,恢复后窗口内真告警被吞(本次引入的回归) | 1.2 第二次调用;对照通用路径 `and ok` 契约 | 同 P0 修法(失败不占窗,恢复后可重发) |
| P3 | retry_failed_metrics.py L117「计数写失败告警已发(dedup 6h)」打印误导未订正(上一轮 P3 建议项);C-1 后 suppress 时仍打「已发」 | 读码 L117 | 文案改「已入警告队列(30min 聚合批发)」/「已 suppress(窗口内)」 |

低分项(<80)已滤:1 项(25 分:log_info 不接 dry_run 的 info 级 dry-run 写 dashboard——pre-existing 低影响,未进正式清单)。

## 给主控的一句话结论(第 3 条不需要用户拍板)
C-1 修复让 with_lock/staticdata 等调用方自选的 6h dedup 从「静默失效」变「真生效」,是修复未生效的设计意图、非改动已上线行为,且 with_lock 注释声明真锁死有 schedule_monitor 兜底——**不需要用户拍板**;
但 `_tier_send_ok` warning 档的「buffer 写失败假成功占窗」是本次引入的 P0 新缺陷(真告警被静默吞 6h+,且磁盘满场景下连写失败告警自身都发不出),**必须修复后重新 review,不得 merge**。

## 复现清单
1. `git archive fd3bbdaa3 | tar -x -C /tmp/rev132b` 隔离
2. 把 `/tmp/rev132b/data/alerts/warning_buffer.jsonl` 建成目录 → `python3 notify.py "A" "b" --tier warning --dedup-key rev2_test_abc --dedup-window 3600` ×2 → 第一次占窗/第二次 suppress(1.2)
3. `python3 scripts/test_132_notify_tier_dedup.py` → 8 OK
4. `python3 scripts/test_notify_dedup.py` → 15 OK(含 test_u10)
5. dry-run 三层零污染实测(4 节)
