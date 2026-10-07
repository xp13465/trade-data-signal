# #232 `schedule_monitor.sh` `marker_buffer` degrade 连续轮计数 —— 修复实施报告(2026-10-07)

- **任务**:#232 修 `marker_buffer` 降噪链(计数桶 seen 缺失 ⇒ SEVERE 结构性不可达/零报)。用户已拍板「修」(§23.7 冻结面),本报告=实施+自验。
- **分支**:`feat/232-markerbuffer-seen-20261007`(从 main 开)。
- **base commit**:`c233e63afec0225b55e9ef97edce7548907daf05`(开工时 `git rev-parse HEAD` = main 含 #232 定性报告 `c233e63af`)。
- **依据**:只读定性 `docs/ops/232-markerbuffer-qualitative-20261007.md`(推荐候选 A)。
- **零外发/边界**:全程**未运行** `scripts/schedule_monitor.sh` 本体(含真实邮件/飞书链路);探针 **static-only**(ast 提取内嵌 python heredoc 真块后 exec 纯逻辑块,不 source/exec 业务脚本主体);自测打桩 subprocess/urllib/socket,零真实外发(证据见 §8)。
- **残留后台任务**:无(未出现 `moved to the background`)。

---

## ① 改动逐行(为什么这 1-2 行就够)

改动文件:`scripts/schedule_monitor.sh`(仅 1 文件 +12 行,全为新增行,无删改)。

**改动 1(承重行)—— 计数桶补 `seen`(计数块 L770-776 写桶之后):**
```python
                            seen_keys_this_run.add(_bk)      # _bk = f"{task}|marker_buffer"
```
- **为什么够**:病根单点 = 计数桶 `_bk` 全脚本从无 `seen_keys_this_run.add`(定性 §1.1)。主恢复循环(schedule_monitor.sh L1676-1684)对「status==pending 且 **未 seen** 且非 `r2_`/`72h_` 前缀」的键每 tick 翻 `recovered` ⇒ 下 tick L768 `else` 分支把 `count` 重置为 1 ⇒ **count 恒 1,达阈(3)不可达**。补 seen 后,degrade tick 的桶被标记为「本轮仍活跃」,恢复循环跳过 ⇒ count 正常累积 1→2→3 ⇒ SEVERE 可达。
- **语义边界**:只在 `log_anomaly_severity=="degrade"` 分支内标记 ⇒ 链断(无 degrade / critical / 无异常)时不再 seen ⇒ 恢复循环/inline 照常清链、下轮从 1 起(**防抖语义保持**,不产生「只加不减」新 bug)。
- **与活样板对齐**:同款既有写法 = `r2_intraday_lag` 计数桶(L2142 `seen_keys_this_run.add(_r2_id_key)`)、`missed`(L381)、`dedup_key`(L718)、`not_loaded`(L1353)。**未自创**。

**改动 2(状态洁净,与活样板同款)—— inline 复位显式清 count(L826-831):**
```python
                        "consecutive_count": 0,
```
- 与 `r2_intraday_lag`(L2205-2211)/ `overview` judge(L250-253)完全同款。**非必需**(即使不清,下轮 degrade 读 `status==recovered` 走 L768 `else` 分支也会重置为 1),此处清 = 复位语义**显式化**(测试 t3 直接断言 count==0)。

**未做(遵定性 + 派单硬约束):**
- ⛔ **候选 C(照抄 #181 轮去重/保链)未做**:本链计数对象是 **monitor tick 轮**,与 r2_skip 的 **run 轮**语义不同;轮去重会把单 run 长跑/卡死压成 1 次计数,45min 哨**彻底消失**(测试 `test_source_has_seen_and_no_round_dedup` 钉死:块内不得出现 `last_round`/`skip_rounds`)。
- ⛔ **阈值常量未动**(`TRANSIENT_TIMEOUT_THRESHOLD` 保持 3;测试 `test_constants_unchanged` 同款断言)。
- ⛔ **未碰通用恢复循环**(L1676-1684):用 seen **局部**解决,不给 marker_buffer 加前缀豁免(测试 `test_generic_recovery_loop_untouched` 钉死)。

**§7.1 可逆性**:单点 2 行新增,无新增 state 字段、无 schema 迁移(`alert_state` 为自由 json,旧代码读新值字面兼容)= 与 #181 回滚论证同构。

---

## ② 修复前不可达 / 修复后可达(成对证据,负控成对)

同一份测试(`scripts/tests/test_232_marker_buffer_20261007.py`)对两版脚本运行:

| 版本 | 命令 | 结果 |
|---|---|---|
| **修复后**(工作树) | `pytest -q scripts/tests/test_232_marker_buffer_20261007.py` | **16 passed** |
| **修复前**(`git show HEAD:scripts/schedule_monitor.sh` = `c233e63af` 版) | `SCHEDULE_MONITOR_SH=/tmp/pre232-schedule_monitor.sh pytest ...` | **12 failed / 4 passed**(FAIL 集含 `test_reachability_three_degrade_ticks_fire_severe` / `test_source_has_seen_and_no_round_dedup` / `test_negative_control_without_seen_unreachable` 等) |

**可达性(修复后)**:连续 3 个 degrade tick ⇒ count `1→2→3`,第 3 tick 桶 `status=alerted` 且 append SEVERE **恰 1 次**(`test_reachability_three_degrade_ticks_fire_severe` 逐条断言:阈值前 0 告警 / 第 3 tick 1 封 / 正文含「已连续3轮未自愈」「(阈值3)」)。

**不可达(修复前)**:`test_negative_control_without_seen_unreachable` **在文件内永久钉死**——运行期从真块剥掉 `seen_keys_this_run.add(_bk)` 一行(还原修复前语义)⇒ 每 tick count 恒 1、桶每 tick 被恢复循环翻 `recovered`、**0 SEVERE**。此负控证明该 1 行是**承重的**(测试有检出力,不是「本来就绿」)。

**SUPPRESS(达阈后不重发)**:`test_suppress_after_threshold_no_repeat` — 达阈后持续 degrade,dedup_key 持续 active(seen 保护)⇒ tick4/tick5 **不重发**,桶保持 alerted。

---

## ③ 复位语义证据(真复位,非「只加不减」)

`L822-832` inline 复位块补 seen 后**确实活起来**(成为唯一真清零点,而非死代码):
- `test_reset_on_clean_tick`:degrade ×2 后 clean tick ⇒ 桶 `status=recovered` 且 **count==0**(显式复位),全程 0 告警。
- `test_reset_then_reaccumulate_fires`:degrade ×2 → clean → degrade ×3 ⇒ 复位后 count **重新从 1 起**,仅第二条链第 3 tick 告警。**证明无「残留续数」假升级**(排除「只加不减、永不复位」新 bug)。
- `test_single_degrade_never_fires_no_residue`:单 tick degrade + 复位 ⇒ 永不 SEVERE、count 归 0。

---

## ④ 不误报证据(判别力)

- `test_clean_task_never_counted`:无 anomaly 的任务 ⇒ 桶**根本不创建**(`{}`)、0 告警。
- `test_non_degrade_anomaly_not_counted`:critical(真失败)severity ⇒ 走既有**直报**通道(首 tick 即 SEVERE),**不进 marker_buffer 计数**(不拖 45min),桶始终为空。
- `test_boundary_two_vs_three_ticks`:阈值边界钉死 —— 2 tick(30min)不报 / 3 tick(45min)报(与 `r2_intraday_lag`「连续>=3轮≈45min」同族口径)。
- `test_two_ticks_then_break_no_false_positive`:2 tick degrade 后链断 ⇒ 不报。
- **残余理论误报面(诚实标注,承接定性 §5.2a)**:长任务 + ⚠ 组合在 30 天生产 0 例;本改动**未新增**任何计数对象(只在既有 degrade 分支配 seen),故不扩大误报面。上线观察期建议 2 周复核该链 SEVERE 数量与真伪。

---

## ⑤ 红先验结果(§18 L49 检出力)

1. **文件内永久负控**:`test_negative_control_without_seen_unreachable`(运行期剥 seen 行)⇒ 修复前语义下 **count 恒 1 / 0 SEVERE**,断言必须成立(PASS 于当前文件)。若未来有人删掉 `seen` 行,该测试立即 FAIL。
2. **外部 red-先验(可复现)**:`git show HEAD:scripts/schedule_monitor.sh > /tmp/pre232-schedule_monitor.sh`,`SCHEDULE_MONITOR_SH=/tmp/pre232-schedule_monitor.sh pytest ...` ⇒ **12 failed / 4 passed**(证明测试对本案有检出力;换回修复版 ⇒ 16 passed)。4 个 pre-fix 也 PASS 的用例=`test_generic_recovery_loop_untouched` + 3 个「不误报」用例(它们在两版都应 PASS,正确)。

---

## ⑥ 同类面复核(§23.2③ 修 bug 三铁律之排查同类;独立复算,不采信定性结论)

**独立重算**:`grep '"pending"'` 全脚本 + 逐点核对「每处 pending 桶是否 mark seen 或受前缀保护」:

| pending 桶 key | 定义行 | 免疫机制 | 判定 |
|---|---|---|---|
| `missed\|{task}\|{hm}\|{date}` | L380 | seen L381 | 健全 |
| `{task}\|marker_buffer` | L760 | **seen(本次补)** | **本次修复** |
| `{label}\|not_loaded` | L1352 | seen L1353 | 健全 |
| `r2_unreachable` | L1999 | r2_ 前缀 + seen L2000 | 健全 |
| `r2_intraday_lag\|buffer\|{date}` | L2139 | r2_ 前缀 | 健全 |
| `overview_lag_3domain\|buffer\|{date}`(adr judge) | L1905 | count 不依赖 status(`else: count+1`)+ 恢复清 count | 健全 |
| `r2_overview_lag\|buffer\|{date}`(adr judge) | L2080 | r2_ 前缀 + 同上 | 健全 |

**结论**:唯一病态 = `marker_buffer`(改前 ①∪②∪③ 三种免疫机制全空),与定性 §6 的 13 条穷举**一致**;**未发现第二条病态链**。若发现第二条应停下上报 —— 未触发。

**§23.3 举一反三(消费者/展示位清单)**:
- `grep -rn marker_buffer scripts/ static-site/ app/` ⇒ **仅** `schedule_monitor.sh` 自身(L760/774/779/820/823/830/832/2146 注释),**无专属消费者、无前端展示位**。
- `alert_state.json` 为云端运行时状态(非上线数据产物),一般读取方(notify/check_*)按键取值,不做全键遍历 ⇒ 无消费者破坏面(与定性 §5.2c 一致)。
- §21 算法公示:无对象(纯后端监控脚本,无前端公式/文案)。§22 数据一致性:无上线数据产物改动(不涉 static-site/data、不涉 R2/CF)。§24 前端:无前端改动。§23.15 数据就绪:无上线数据。

---

## ⑦ 可逆性与回滚

- 改动 = `scripts/schedule_monitor.sh` 单文件 **+12 行新增**(2 处:`seen_keys_this_run.add(_bk)` + `"consecutive_count": 0`);
  回滚 = `git revert <commit>`(无 state schema 变化、无数据迁移)。
- **恢复路径**:回到改前 = `git checkout c233e63af -- scripts/schedule_monitor.sh`(或 revert commit)。
- 不影响 r2_skip / feeder(`gen_schedule_stats.py`)/ 前端 / 数据产物。

---

## ⑧ 零真实外发自证(§18 L48/L50)

- **未运行** `scripts/schedule_monitor.sh` 本体(含真实邮件/飞书发送链)。所有自测在 **static-only 沙箱**下:ast 提取内嵌 heredoc 的**纯逻辑块**(只 append `alerts` list / 读写 `alert_state` dict,无网络/子进程)+ exec。
- `test_zero_real_outbound`:把 `subprocess.run/Popen`、`urllib.request.urlopen`、`socket.create_connection` 打桩为「一调用即 AssertionError」;**调用计数 == 0**(证明本次自测零真实外发)。
- **本次自测未产生任何真实外发**(无邮件/无飞书/无网络),无需上报外发事故。

---

## ⑨ 语法与测试结果

```
bash -n scripts/schedule_monitor.sh                                  => PASS
pytest -q -p no:cacheprovider scripts/tests/test_232_marker_buffer_20261007.py
                                                                     => 16 passed
pytest -q -p no:cacheprovider scripts/tests/                          => 373 passed, 2 skipped
```

- 新增测试:`scripts/tests/test_232_marker_buffer_20261007.py`(CI 可收集:`ci.yml` ⑧ `python3 -m pytest -q scripts/tests/`),含 `_MIN_ASSERTIONS = 40` 防 0 断言假绿(实测 69 条断言,`test_min_assertions_guard` PASS)。
- 该链测试覆盖现状 **0 → 16**。

---

## 附:关键行号(改后)

- 计数桶补 seen:`scripts/schedule_monitor.sh:784`(`seen_keys_this_run.add(_bk)`,原 L770-776 写桶块之后)。
- inline 复位清 count:`scripts/schedule_monitor.sh:840`。
- 病根链(未改):计数块 `L759-796`、主恢复循环 `L1676-1684`、inline 复位 `L822-832`。

## 附:commit / 分支

- 分支 `feat/232-markerbuffer-seen-20261007`,base `c233e63af`。

**编制**:implementer 子 agent(2026-10-07)。边界:static-only 探针 + 打桩自测,未运行 monitor 本体、零真实外发。