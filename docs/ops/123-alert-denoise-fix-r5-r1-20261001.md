# #123 告警降噪复审 FAIL 修复报告(R5 双重致命 + R1 恢复循环误报,2026-10-01,implementer)

> 本报告针对独立审查 `docs/ops/123-alert-denoise-implementation-review-20261001.md` 判 FAIL 的
> 缺陷做修复,交付「每处缺陷定位 + 改法 diff + 复现实验前后对照 + 举一反三清单 + 其余规则行为不变证明」。
> 审批链:审查报告 FAIL → 本报告修复 → reviewer 复验(待主控派单)。

---

## 结论

三件事全部完成,修复 commit `9dc1ca3a8`(feat 分支 `worktree-agent-af1e103df45f2939c`):

| # | 缺陷 | 修复 | 复现实验 | 状态 |
|---|---|---|---|---|
| ①a | R5 改状态不落盘(同轮第 2+ 种 R2 告警被吞且永久静默) | R5 调用后立即 `save_alert_state` | 4 场景全 PASS | 已修 |
| ①b | R5 只在 `if alerts:` 内调用(23:25 收尾轮空 alerts 时汇总永不发) | R5 无条件调用 + `_orig_has_alerts` 区分提示 | 同上 | 已修 |
| ② | R1 恢复循环交互误报(滞后→恢复→再滞后跨 3 轮假 SEVERE) | `r1_buffer_judge` 恢复路径支持 recovered 清 count | 三连场景 5 变体全 PASS | 已修 |
| ③ | 测试盲区(原 26 项全 PASS 但无跨轮场景) | 补 9 项跨轮断言(26→35) | 35 项全 PASS | 已修 |

---

## 1. 缺陷①:R5 双重致命(修复必双修,单修任一不够)

### 定位

`scripts/schedule_monitor.sh` 尾部告警输出区(修复前 L2150 附近):
- **缺陷 a(不落盘)**:R5 修改 `r2_pipeline_congestion|{YYYYMMDD}` 状态,但**全文件 6 处
  `save_alert_state`(L1281/1450/1722/1809/1950/2088)全在 R5 之前**。schedule_monitor 每轮 = 独立
  bash 进程(heredoc python 退出即丢内存),改的 alert_state 从未落盘 → 下一轮 load 读到旧状态。
  后果:同轮第 2+ 种 R2 告警被并入聚合后,现象既不落盘也不进汇总 → **真故障永久静默**。
- **缺陷 b(if 内调用)**:R5 只在 `if alerts:` 分支内调用 → 23:25 收尾轮若当日告警已被此前轮处理
  (alerts 为空),R5 不运行 → **当日已聚合现象永远进不了汇总**。

两者叠加:09-30 报告所述「同轮 3 封 R2 告警只发 1 封」场景,剩 2 封既无即时告警又进不了汇总,
与 memory `alert-denoise-keep-fault-discriminator` 的降噪翻车模式一致。

### 改法 diff(schedule_monitor.sh,原 L2147-2178 → 新)

```diff
 # 判定/聚合函数 scripts/alert_denoise_rules.py:r5_congestion_process。状态 key 不进恢复循环
 # (已在恢复循环开头跳过 R2_CONGESTION_SUMMARY_KEY_PREFIX)。
+# 2026-10-01 复审修复(R5 双重致命缺陷, 见 docs/ops/123-alert-denoise-implementation-review-20261001.md):
+# ① R5 无条件调用(移出 if alerts)——23:25 收尾轮 alerts 为空时也必须运行, 否则当日已聚合
+#    现象永远进不了汇总;
+# ② 调用后立即 save_alert_state 落盘——否则 r2_pipeline_congestion|{YYYYMMDD} 状态只存在
+#    进程内存, 每轮独立进程退出即丢, 同轮第 2+ 种 R2 告警被吞且永久静默。
+_orig_has_alerts = bool(alerts)
+alerts, _r5_summary = adr.r5_congestion_process(alert_state, alerts, NOW)
+if _r5_summary:
+    alerts.append(_r5_summary)
+save_alert_state(alert_state)
 if alerts:
-    alerts, _r5_summary = adr.r5_congestion_process(alert_state, alerts, NOW)
-    if _r5_summary:
-        alerts.append(_r5_summary)
-    if not alerts:
-        print(f"[{now_str}] 本轮告警已由 R2 拥堵日汇总接管, 见 r2_pipeline_congestion 状态")
-    else:
-        print(f"[{now_str}] 检测到 {len(alerts)} 个告警:")
-        for a in alerts:
-            print(a)
-        # ...(发邮件逻辑原样保留)
+    print(f"[{now_str}] 检测到 {len(alerts)} 个告警:")
+    for a in alerts:
+        print(a)
+    # ...(发邮件逻辑原样保留)
+elif _orig_has_alerts:
+    print(f"[{now_str}] 本轮告警已由 R2 拥堵日汇总接管, 见 r2_pipeline_congestion 状态")
 else:
     print(f"[{now_str}] OK 所有任务按计划执行，无漏跑，无退出失败")
```

关键设计点:
- **无条件调用**:R5 每轮都跑,收尾轮空 alerts 也跑(缺陷 b 修)。
- **调用后立即落盘**:R5 的结果在进程退出前写盘(缺陷 a 修)。
- **`_orig_has_alerts` 记录**:保原「已由汇总接管」提示分支语义——R5 把 alerts 处理为空时打接管
  提示,原本就空时打 OK,原 else 语义不破坏。
- **发邮件逻辑零改动**:`body/subject/notify.py 调用` 原样保留,§23.10 飞书一致不受影响。

---

## 2. 缺陷②:R1 恢复循环交互误报(修复位置必须正确选择)

### 定位

- `scripts/schedule_monitor.sh` L1178-1200 恢复循环:每轮开头把「上轮遗留 pending buffer 未 seen」置
  recovered,但**不清 `consecutive_count`**。
- `scripts/alert_denoise_rules.py` `r1_buffer_judge` 恢复路径(修复前 L52-59):`_bf.get("status") in
  ("pending", "alerted")` 才清 count,`status="recovered"` 的 buffer **不清 count** → 计数残留。

交互时序(每轮 15min):
1. 轮 1:滞后 24min → buffer 记 count=1,status=pending
2. 轮 2:正常 → 恢复循环把该 buffer 置 recovered(但仍 count=1);overview 块走恢复路径,
   status=recovered → 不清 count
3. 轮 3:再滞后 24min → status=recovered 走「非 alerted」分支 count=1+1=2 ≥ 阈值 → **假 SEVERE**

### 改法 diff(alert_denoise_rules.py L63)

```diff
-        if _bf and _bf.get("status") in ("pending", "alerted"):
+        if _bf and _bf.get("status") in ("pending", "alerted", "recovered"):
             _bf["status"] = "recovered"
             _bf["consecutive_count"] = 0
             _bf["recovered_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
```

### 为什么不能改在恢复循环(自我纠正,保真故障头号判据)

恢复循环比 overview 块**每轮更早运行**。若在恢复循环 L1188-1192 清 count:真连续 2 轮滞后时,
轮 2 开头恢复循环会把轮 1 遗留 buffer 置 recovered 并清 0 → 轮 2 滞后分支读到 count=0+1=1(而非
1+1=2)→ **真故障被吞**。所以清 count 的位置必须放在 `r1_buffer_judge` 恢复路径(且仅恢复路径):
- 真连续 2 轮:轮 2 走滞后分支(count 不清,1+1=2 → alert),不吞真故障;
- 滞后→恢复→再滞后:轮 2 走恢复分支清 count,轮 3 从 0 起 → 不回 alert。

---

## 3. 缺陷③:测试盲区补齐(26→35 项断言,全部打真实函数)

原测试 `scripts/tests/test_alert_denoise_20261001.py` 26 项全 PASS 但**无跨轮场景**(FAIL 暴露根因)。

### R1 修复场景(在 R1 跨天 E 后新增)

`r1_with_recovery_loop` helper:按 schedule_monitor 真实执行序逐轮——先恢复循环(上轮遗留
pending→recovered 不清 count)→ 再调真实 `r1_buffer_judge`,4 场景:

| 场景 | 输入(滞后分钟序列) | 期望 | 断言 |
|---|---|---|---|
| F(复审反例④) | [24,3,24] 滞后→恢复→再滞后 | `["buffer","ok","buffer"]` 不回 alert | `r_F == [...]` |
| G(真故障不吞) | [24,25,3,24] 真连续 2 轮后恢复再滞后 | 前 2 轮 buffer→alert,恢复后从 0 | `r_G[0]=="buffer" and r_G[1]=="alert" and r_G[3]=="buffer"` |
| H(对照组) | [24,3,24] 不插恢复循环 | 同 F,原 r1_sim 语义不回退 | `r_H == ["buffer","ok","buffer"]` |

### R5 修复场景(在 R5 非 R2 用例后新增)

`r5_monitor_sim` helper:模拟每轮独立进程 load→r5(无条件)→save→下一轮 load,打真实
`r5_congestion_process` + 真实 alert_state.json 文件读写,4 场景:

| 场景 | 轮次输入 | 复现的审查反例 | 断言要点 |
|---|---|---|---|
| A | 跨轮 3 轮各 1 种 R2(14:15/21:00/23:00) | 反例①跨轮状态不持久化 | 首条直发、中间轮不发汇总、23:30 收尾轮必发汇总、state 含 `r2_pipeline_congestion\|20260930` |
| B | 同轮 3 种 R2 @23:30 | 反例②同轮第 2+ 种静默 | 首条直发 + 汇总必发(不静默) |
| C | 前 2 轮聚合,收尾轮 alerts=[] | 反例③收尾轮空肯定不发 | 收尾轮 summary 必发(无条件调用生效) |
| D | 读 C 的最终 state | 缺陷 a 落盘可读回 | 现象列表 ≥2(第 2+ 种不静默) |

### 跑法

```bash
cd worktree && /Users/linhuichen/code/trade-data/.venv/bin/python \
  scripts/tests/test_alert_denoise_20261001.py
# === 13+ 项真故障反例断言 + 09-30 回归断言全部 PASS ===(35 项)
```

---

## 4. 举一反三(§23.3,两个模式全仓核查)

### 模式一:「改了状态但没落盘」

schedule_monitor 每轮独立进程,任何 alert_state 写入必须在进程退出前落盘。全仓 grep 结果:

| 位置 | 写入点 | 后随落盘 | 结论 |
|---|---|---|---|
| schedule_monitor.sh | L332/341(L1281 前) | save@1281 | 有 |
| schedule_monitor.sh | L523/601/621/635/657/731/789/806/859/935/1067/1087/1149(L1281 前) | save@1281 | 有 |
| schedule_monitor.sh | L1414(overview 块) | save@1450(块内补存) | 有 |
| schedule_monitor.sh | L1511/1593/1663/1683/1715(R2 块) | save@1722(块内补存) | 有 |
| schedule_monitor.sh | L1782(飞书块) | save@1809(块内补存) | 有 |
| schedule_monitor.sh | L1918(飞书心跳) | save@1950(块内补存) | 有 |
| schedule_monitor.sh | L2062(维度⑨) | save@2088(块内补存) | 有 |
| **schedule_monitor.sh** | **R5 L2150(修复前)** | **无(修复后 save@2159)** | **唯一遗漏→已修** |
| notify.py | R4 `r4_staticdata_grade` 内部状态 | 函数内原子写 state_path | 有(自带落盘) |
| notify.py | dedup 状态 | `notify_dedup.json`(update_dedup) | 有 |
| monitor_72h.sh | L205/232 | save@820 | 有 |

**结论:全仓唯一「改状态不落盘」点 = R5,已修;其余均正确。**

### 模式二:「只在 if alerts: 内调用导致收尾轮不跑」

| 位置 | 模式 | 结论 |
|---|---|---|
| schedule_monitor.sh R5(修复前) | 收尾汇总逻辑仅在 `if alerts:` 内 | **唯一同类→已修** |
| notify.py | 单告警触发模型(每次调用处理 1 条),无「收尾轮」概念 | 无此模式 |
| schedule_monitor.sh 其余规则 R1/R2/R3/R4 | 各块逐轮直接判定并即时落盘,不依赖收尾轮 | 无此模式 |
| monitor_72h.sh | 每次运行 = 完整一轮(load→处理→save),无收尾轮 | 无此模式 |

**结论:全仓唯一「收尾轮因 if 盲区不跑」点 = R5,已修。**

### 关联安全核查(防修漏)

- **恢复循环跳 R5 key**:L1178-1200 恢复循环开头
  `if _key.startswith(adr.MERGE_PREFIX) or _key.startswith(adr.R2_CONGESTION_SUMMARY_KEY_PREFIX): continue`
  ——`r2_pipeline_congestion|{日期}` 不参与恢复检测,不会被误置 recovered 清掉跨轮累计现象。已确认。
- **恢复邮件只读不写**:R5 之后代码(recoveries 过滤/发恢复邮件/S06 检查/heartbeat/flush-warnings)
  只读 alert_state 或调 notify.py,无额外写 alert_state 点。

---

## 5. 「其余规则行为不变」证明(§23.7 冻结契约)

| 规则 | 是否触碰 | 证明 |
|---|---|---|
| R1 | 只改恢复路径判定(加一个 status 枚举值) | 滞后分支 L71-86 零改动;真连续 2 轮测试 G/r1_sim 反例 A/B 全 PASS(26→35 项里的旧断言全数保留通过) |
| R2 | 未触碰 | R2 反例 A/B/正例 C/清理 D + 09-30 回归(us_stock/intraday/s06/backfill 合并)全 PASS |
| R3 | 未触碰 | R3 反例 A/B/正例 C + 09-30 回归(nextday)全 PASS |
| R4 | 未触碰 | R4 反例 A/B/C + 补充 D + 09-30 回归(staticdata×4→SEVERE 0)全 PASS |
| R6 | 未触碰 | R6 保留断言 + 09-30 回归(kelly)全 PASS |
| 发邮件/飞书 | 零改动 | R5 修复里 `body/subject/notify.py 调用/--from-prefix` 原样保留,仅把发信块上移到无条件 R5 之后的 `if alerts` 内 |

09-30 十五条第 18 行回归断言(15→8 口径)全部原样保留并通过:staticdata×4→0、overview×2→0、
us_stock×2→1、kelly→1、intraday/s06×3→2、backfill×2→1、nextday×2→1。

---

## 复现段

- 审查 FAIL 反例脚本(reviewer 侧原样):`/tmp/review_r5_persist_test.py`(反例①)、
  `/tmp/review_r5_same_round.py`(反例②)、`/tmp/review_r5_persist_patch.py`(反例③)、
  `/tmp/review_r1_recover_loop.py`(反例④)——审查报告 §1 已含运行输出(FAIL 现场)。
- 修复对照实验(本报告 agent 侧):
  - `/tmp/repro_r5_fix_test.py`:4 场景(跨轮 3 种/同轮 3 种@23:30/收尾轮空/状态落盘读回)全 PASS;
  - `/tmp/repro_r1_full.py`:三连 5 变体(滞后→恢复→再滞后不回 alert、真连续 2 轮照常响、
    连续 2 轮后恢复再滞后从 0 计)全 PASS;
  - `scripts/tests/test_alert_denoise_20261001.py`:35 项断言全部 PASS(含新增 9 项跨轮)。
- 修复后全仓 grep 清单(本报告 §4 两表结果)。

## 结论摘要(给主控)

1. R5 双重致命缺陷已双修:无条件调用 + 调用后立即落盘,发信逻辑零改动;
2. R1 恢复循环交互误报已修:清 count 放在 r1_buffer_judge 恢复路径(含 recovered),不吞真连续 2 轮;
3. 测试盲区补齐 26→35 项跨轮断言,全 PASS;
4. 举一反三:两个模式全仓核查,唯一遗漏点均为 R5 本身,其余写入点全有落盘、其余逻辑无收尾轮盲区;
5. 冻结契约:仅 R1 恢复路径加 1 个枚举值,R2/R3/R4/R6 与发信链路零改动,09-30 回归口经全部保留通过。