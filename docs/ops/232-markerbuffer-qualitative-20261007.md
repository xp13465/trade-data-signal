# #232 marker_buffer degrade 连续轮计数 —— 只读定性报告(2026-10-07)

- **任务**:#232 定性("marker_buffer degrade 连续轮计数"是否与 #181 同病 / 该怎么修 / 误伤风险)。主控已转述用户拍板"修",本报告只做定性+候选修法,不含实施。
- **授权边界**:只读不改。全程未写业务代码、未 commit、未切分支;未运行 `scripts/schedule_monitor.sh` 本体(其含真实邮件/飞书发送链路,一次真跑=一次真外发事故,§18 L48);探针 static-only(§18 L50):仅以 `sed` 静态导出 python heredoc 段外部 exec(打桩后纯逻辑),不 source/exec 业务脚本主体,零外发出口(提取块仅 append list / 读写 dict / print)。
- **时间窗**:生产证据取自主控提供的全量 monitor 日志(09-13→10-07,`/tmp/181-monitor-full.log`,157 万行)+ 云上只读拉取(ssh,`/home/ubuntu/code/trade-data/data/alert_state.json` 等)。macOS 无 coreutils `timeout`,所有命令以工具级 timeout 参数等效(已注明)。
- **结论一句话**:属于 #181 同**病族**(缓冲计数 + seen 缺失的写法坑)但症状相反 —— r2_skip 是"跨 tick 重复计数(过量报)",marker_buffer 是"**计数锁死 = SEVERE 结构性不可达(零报/假阴性)**";最小正确修法 = 一行(计数桶补 `seen`),**照抄 #181 轮去重反而会换一种方式废掉该链**(证据见 ④/⑤)。

---

## ① 结论

### 1.1 病理链(逐行状态机,均带行号)

对象:`scripts/schedule_monitor.sh`(每 15min 一 tick,`NOW` 于 tick 起始捕获 L85;tick 总结行打印于脚本末尾 L2661/L2684,用 tick 起点 `now_str` L2643)。

1. **计数分支**(L759-796):某任务 stats 条目 `log_anomaly_severity == "degrade"`(feeder `gen_schedule_stats.py` Fix C 对"⚠ 瞬态行 + run 进行中(last_exit=None)且无成功行"的标注,L652-662)时:
   - `_bk = f"{s.get('task')}|marker_buffer"`(L760);读桶 `_bs = 桶.status`;
   - 计数:L763-769 —— `pending` → count+1;`alerted` → 锁阈值 3;**`else`(含 `recovered`/无)→ `_c = 1`(重置)**;
   - 写桶 L770-776(status = `alerted` if `_c >= 3` else `pending`);
   - `_c < 3` 打 `"[marker_buffer] ... 连续{_c}/3 轮未自愈,暂不通知"`(L777-782);`_c >= 3` append SEVERE + 写告警去重 key `dedup_key` active(L783-796)。
2. **inline 恢复**(L822-832):同一扫描循环内,`if not s.get("log_anomaly")`(本轮该任务无异常)→ 桶 status ∈ {pending, alerted} → 翻 `recovered`(打印 `"...抖动已自愈(连续计数重置)"`)。注意:**不清 `consecutive_count`**。
3. **主恢复循环**(L1665-1737,扫描之后):对 alert_state 全部键 —— **pending 且未 seen 且非 `r2_`/`72h_` 前缀** → 翻 `recovered` + 打印 `"[silent recovery] {key} 自愈类异常已消失(未通知过)"`(L1676-1684)。

**缺陷(全脚本唯一)**:计数桶 `_bk` **从未 `seen_keys_this_run.add`** — `grep -n "_bk"` 全部出现点为 L760/761/770(计数)与 L823/824/826(inline 恢复),无任何 add。而同块 `dedup_key` 有 seen(L718)。

**由此的状态机(与生产逐位吻合)**,记 tick N 时桶状态是 tick N-1 末值:

| tick | 计数分支(L762 判 status) | 桶写入 | 恢复循环(L1676-1684) | 净结果 |
|---|---|---|---|---|
| N | 上轮末恒为 `recovered` → `else` 分支 `_c=1` | pending(count=1) | 桶 pending **未 seen** → 翻 recovered + silent recovery 打印 | 日志:连续1/3 + silent recovery,各 1 行 |
| N+1 | 同 N(又见 recovered) | pending(1) | 同 N | **无限循环,count 恒 1** |

`alerted`(=_c>=3)仅当 status==pending 才可能到达,而桶**从不存活到下一 tick** ⇒ **SEVERE 结构性不可达**。附带两死代码:①` alerted → _c=3` 分支(L765-767)不可达;②inline 恢复打印 `"...抖动已自愈(连续计数重置)"` 结构性不可达(进入时桶总已是 recovered),生产 grep = 0 命中(见 ③.3)。

### 1.2 建议改什么 / 能不能不改

**建议修(候选 A,最小)**:L770-776 写桶之后加一行 `seen_keys_this_run.add(_bk)`(计数分支内,degrade tick 才 mark)。语义 = "本轮该计数键仍活跃",与 dedup_key L718、missed L381、r2_intraday_lag L2142 同款既有写法。可选叠加 1 行硬化:inline 恢复(L826-831)加 `"consecutive_count": 0`(状态洁净;非必需,因 L768 `else` 分支已把残留 count 重置为 1)。
- 效果:连续 degrade 的 tick 计数正常累积 1→2→3(驱动 S3 实证:tick3 达阈 append SEVERE);链断(degrade 消失)时,inline 恢复照旧翻桶→下轮重建从 1 起(驱动 S1b/S4 tail 实证);不改恢复循环通用代码,零跨链影响。
- 语义:阈值 3 轮 = **连续 3 个 15min tick(≈45min)该任务持续处于"有运行但结局未定论"**——与同族 `r2_intraday_lag`(注释 L2144-2148 "连续>=3轮(≈45min)仍滞后才 SEVERE")、`overview`(阈值 2 轮)口径一致,都是**按 tick 计**。

**能不能不改(维持现状)?不建议,但后果有限、可决策**。
- 现状唯一后果:①该链应有的探测能力为零(假阴性)——"单 run 长跑/卡死 ≥45min 未定论"这个场景没有任何其他链覆盖(见 ⑤ 覆盖矩阵);②每 tick 两行自相矛盾日志("连续1/3 未自愈"+"自愈类异常已消失"同 tick 连打),生产 30 天出现 2 组;③桶在 alert_state 里以 recovered+count=1 冻结(前端/巡检若读会误认为"曾活动过已自愈")。
- 若用户接受"该场景由 in_progress_timeout(L1117-1191)/EXTRA M1(L1063-1113)/systemd 硬闸兜底"而放弃这 45min 前置哨,也可以**选择不改 + 仅在文档标注哑火**。本报告倾向修:改动 1 行、且 30 天生产实测误报面 ≈ 0(见 ⑤)。

### 1.3 与 #181 独立审 §7 判定的不一致(显式指出,§23.11 不静默)

#181 报告 `docs/ops/181-fetchnews-denoise-review-20261007.md` §7 表格第 2 行原文:

> `#2 marker_buffer(pending 态每 tick +1 / degrade marker 轮窗口内跨 tick 重计) | **确为同模式**(「跨 tick 重复计数」同病)...附注:其假恢复被既有 dedup_key seen 挡住,与 r2_skip「假话+假恢复+1h 重报」三症不完全同病`

**出入 3 点**(均附本报告证据):

1. **症状判反**:§7 判"跨 tick 重复计数同病"——实测**本案从未发生重复计数**:生产 2 案例 count 全程=1(云上桶 evidence ③.2),驱动 S1/S2 用真代码复现恒 1/3。本案病理是**计数锁死、SEVERE 不可达(假阴性)**;而"跨 tick 重复计数"恰是 r2_skip 的病(fetch_news 一个 skip 轮被 3 tick 各计 1)。两者是同一写法坑(缓冲计数+seen 缺失)的**相反方向症状**,修法也因此不同。
2. **"假恢复被 dedup_key seen 挡住"不完整/错层**:被假恢复的不是 `dedup_key`(它确被 L718 seen 保护,且**只在达阈值后才存在**——现状从未存在过),而是**计数桶 `_bk`**;桶层假恢复**每 tick 100% 发生**(L1676-1684),正是病理根因。§7 未识别桶层假恢复,故把"假恢复被挡住"当结论,直接掩盖了致死链。
3. **"pending 态每 tick +1"实为死代码**:桶从不存活到下一 tick(每轮末被静默翻),`pending → +1` 分支在生产永不执行;§7 将其列为症状与实际运行态不符。
   **保留一致的部分**:§7"确为同模式(同病族)"的归类成立、"另立任务判对"的立案结论成立(本报告即该任务)。

---

## ② 逐维度对照表(r2_skip #181 修复后 vs marker_buffer 现状)

| 维度 | r2_skip(#181 已修,L918-1022) | marker_buffer(现状,L759-832) |
|---|---|---|
| 计数键结构 | 双键:`{task}\|r2_skip_rounds`(计数)+ `{task}\|r2_skip_alert`(告警去重) | 单键:`{task}\|marker_buffer`(桶=计数+升级闸) |
| 计数对象 | **事件**(每 run 轮发生的 SKIPPED_LOCKED),按"run 轮"计 | **状态**(degrade=run 进行中未定论),按 monitor tick 计(设计意图) |
| 去重依据 | 轮标识 `last_round` = stats `last_run` 分钟串(L957-962),同轮多 tick 不重复 | 无轮去重(每 tick 计;现状因死链恒 1) |
| 新鲜/滞留判据 | `R2_SKIP_OBS_WINDOW=30min`:fresh 才计数;滞留(stale)保链不计数不清零(L946-951/L996-1004) | 无(不判新鲜) |
| 清零条件 | **唯一合法清零点** = else 分支"本轮无 skip"(L1013-1022,不 mark seen,交恢复循环) | 三条:(a) L768 `else` 重置为 1(死链掩盖者);(b) inline L822-832;(c) 恢复循环误翻 L1676-1684(病理) |
| seen 恢复语义 | 达阈值后**每** skip tick(新轮/重复/滞留)mark 告警 key seen(L967-973),仅"skip 停止"才恢复 | **计数桶无 seen**(dedup_key 有 seen L718)。桶每 tick 被恢复循环判"已消失" |
| 消费者告警去向 | 达阈 SEVERE → alerts → notify(邮件/飞书);恢复由恢复循环/独立 key | 同设计;但达阈分支(L783-796)**不可达**,生产 0 封 |
| 生产实测 | 修复前 13/13 封 SEVERE 皆 counted=3/distinctRounds=2(假 3 轮);修复后 5 封均真实 3 distinct 轮(#181 报告 ②) | 2 组"连续1/3+silent recovery",0 封 SEVERE,0 次 count=2;桶 first_seen==last_recovered 同秒(③.2) |

**同族第 3、4 个实例(健全样本,本报告新增对照)**:`scripts/alert_denoise_rules.py` L226-273 `r1_buffer_judge`(overview_lag_3domain / r2_overview_lag 两处消费,H920 `_ov_buf_key`=L1893、L2068)与 inline 版 r2_intraday_lag(L2139-2211)。四实例的"防死链"免疫机制共 **3 种,marker_buffer 三缺俱全**:

| 免疫机制 | 谁在用 | marker_buffer |
|---|---|---|
| ① key 前缀保护(`r2_`/`72h_` 在恢复循环 L1678/L1687 显式跳过) | r2_intraday_lag\|buffer、r2_overview_lag\|buffer、r2_unreachable | 无(键为 `{task}\|marker_buffer`) |
| ② 计数键 mark seen | missed\|(L381)、not_loaded(L1341)、in_progress_timeout(L1166)、r2_skip 告警键(L973) | 无 |
| ③ 计数不依赖 status(被翻 recovered 也 count+1) | r1_buffer_judge L259-262(`else: count+1`);配套恢复路径清 count L250-253 + 日期维度 key | 无(else 分支是 `_c=1` 重置,被翻即死) |

→ 病理可一句话总结:同族四个实例中,**唯一一个(①∪②∪③)全空的是 marker_buffer**,死链是必然结果;三个活样板各自用不同机制避险,反证了"补 seen"是根治且与全族兼容。

---

## ③ 真实日志证据

### 3.1 生产 monitor 日志(全量 09-13→10-07):marker_buffer 全部事件 = 2 组 4 行

`/tmp/181-monitor-full.log`(157 万行)中 `grep -n "marker_buffer"` 全部命中:

```
10366:[marker_buffer] nextday_gap_check ConnectionError: 连续1/3 轮未自愈,暂不通知(降级/瞬时标记连续>=3轮才SEVERE)
10370:[silent recovery] nextday_gap_check|marker_buffer 自愈类异常已消失(未通知过)
14217:[marker_buffer] fetch_news ⚠ [fetch_news] R2 上传 rc 连续1/3 轮未自愈,暂不通知(降级/瞬时标记连续>=3轮才SEVERE)
14219:[silent recovery] fetch_news|marker_buffer 自愈类异常已消失(未通知过)
```

两组均为"同 tick 内 先建 pending(1/3) → 再被静默翻 recovered"的两行连打,组内行号相距 4 行(同一 tick 内)。事件归属(tick 起点口径,`NOW` L85 捕获于 tick 开始):

- 第 1 组 = 2026-09-29 **09:30 tick**:该日 nextday_gap_check run 运行区间 09:26:01→09:31:41(`/tmp/232-nextday-gap.log`,云端拉取),09:30 tick 落在 run 进行中(last_exit=None)+ 窗口内有 ⚠ ConnectionError 行 ⇒ feeder Fix C 判 degrade(L652-662);09:45 tick 时 run 已结束(exit=0)⇒ 无 degrade、链断。
- 第 2 组 = 2026-10-06 **02:00 tick**:fetch_news 轮次开始 02:00:01 秒级,桶 first_seen=2026-10-06 02:00:01 与之一致(见 3.2)。

### 3.2 云上 alert_state.json 两个桶(只读 ssh 拉取):first_seen == last_recovered 同秒

`/home/ubuntu/code/trade-data/data/alert_state.json`(活树;另一份 `trade-data-signal/data/` 同名文件无 marker_buffer 条目):

```
L1179: "nextday_gap_check|marker_buffer": {
L1180:   "status": "recovered",
L1181:   "first_seen": "2026-09-29 09:30:00",
L1182:   "consecutive_count": 1,
L1184:   "line_sample": "....ConnectionErro",
L1185:   "last_recovered": "2026-09-29 09:30:00"     <- 与 first_seen 同一秒

L1255: "fetch_news|marker_buffer": {
L1256:   "status": "recovered",
L1257:   "first_seen": "2026-10-06 02:00:01",
L1258:   "consecutive_count": 1,
L1260:   "line_sample": "⚠ [fetch_news] R2 上传 rc=1 ...",
L1261:   "last_recovered": "2026-10-06 02:00:01"     <- 与 first_seen 同一秒
```

**同一秒创建+恢复 = "建 pending 后在同一 tick 内被翻 recovered"的物证**(驱动 S1/S2 预测的状态轨迹与生产逐位一致)。两桶 count 均=1,至今无任何 count=2/3 的桶存在。

### 3.3 反证组(全部 0 命中;命令可复核)

| grep(对象 `/tmp/181-monitor-full.log`) | 命中数 |
|---|---|
| `连续2/3 轮未自愈` / `连续3/3 轮未自愈`(marker_buffer 专属文案) | 0 / 0 |
| `SEVERE.*marker_buffer`(\|marker_buffer 相关 SEVERE) | 0 |
| `已自愈(连续计数重置)`(inline 恢复打印,L832) | 0(结构性不可达) |
| `silent recovery`(全脚本,任何链) | 121(marker_buffer 占 2) |

### 3.4 自建提取块驱动复现(/tmp/232-driver.py,纯本地逻辑、零外发出口)

方法(static-only):`sed -n '64,2775p' scripts/schedule_monitor.sh` 静态导出 python heredoc 段 → AST 校验(2712 行)→ 外部 exec 三个真代码块:`_recurrence_suppressed`、log_anomaly 块含 L759-832 计数+inline、恢复循环 L1676-1684(打桩外部依赖,模拟"无数值 stats 条目/无网络")。驱动指纹:`232-driver.py` sha256 `b47327ab1e16ca88...`;提取产物 `232-monitor-py.py` sha256 `ef0a994e4d5e97a3...`。

关键输出(节选):

```
######## S1 现状=同run同行 degrade x3 tick ########
[marker_buffer] fetch_news ConnectionError 连续1/3 轮未自愈,暂不通知
[silent recovery] fetch_news|marker_buffer 自愈类异常已消失(未通知过)
-- tick1 09:00 state={'fetch_news|marker_buffer': 'recovered'}      (tick2/tick3 同样逐字重复; 无 SEVERE)
######## S3 只补seen(无轮去重):同run同行 degrade x3 tick ########
-- tick1 09:00 state={'...': 'pending'}           打印: 连续1/3
-- tick2 09:15 state={'...': 'pending'}           打印: 连续2/3
-- tick3 09:30 state={'...': 'alerted', 'fetch_news|ConnectionError|ca9232a8': 'active'}  >>> [ALERT-APPENDED] x1
######## S1b 现状=degrade x2 + clean x2 ########
(tick1/2 恒 连续1/3+silent recovery; tick3/4 clean -> recovered)
######## S4 拟修法模拟(轮去重按 last_run 分钟串, 保链, 达阈值 mark seen) ########   [模拟脚本, 非真代码路径]
-- tick1-3 run=08:45 -> 连续1/3 (同轮不重计 x3)
-- tick4-5 run=09:15 -> 连续2/3 (同轮不重计 x1)
-- tick6-8 run=10:45 -> SEVERE(模拟未实现 suppress, 达阈后每 tick 重复打; 真代码 L811-816 有 suppress 不重发)
```

- **S1/S2**:现状恒 1/3,SEVERE 不可达 —— 生产 2 案例(S1 同行/S2 行变)同构复现。
- **S3**:候选 A 行为 —— 同 run 跨 3 tick(45min 未定论)→ tick3 达阈 append SEVERE(设计语义,期望行为)。
- **S1b**:degrade 仅 2 tick 后消失 → 永不 SEVERE(防抖语义保持)。
- **S4**(模拟,仅演示轮去重节奏):同 run 多 tick 被压成 1 次 —— 纯轮去重下"单 run 长跑 45min"凑不满 3 轮 ⇒ 换成"连续 3 个 distinct run"才触发,而 run 结束必清链,SEVERE 实际极难到达(候选 C 反证,见 ④/⑤)。

### 3.5 运行时长坐标(误伤评估的事实基础)

- `nextday_gap_check`:稳态秒级~分钟级(云上 stats `last_exit=0, last_duration_sec=6`;9-29 事件轮 09:26:01→09:31:41=5.7min)。`DUR_THRESHOLDS` L575-588 该任务=900s(注释"最坏 ~600s")⇒ 常态远小于 45min。
- `fetch_news`:常态 **24s**(代码注释 L532-533,云上 2026-10-07 实测);10-07 全天 12 轮(轮次开始 10:45/11:01/11:45/…/16:01,相邻 16/44min,每轮 3 行完成标记、秒级完成;`/tmp/181-fetchnews-full.log`)。其 stats `last_exit`/`last_duration_sec` 恒 null(不走 standard 退出码通道),degrade 是其 ⚠ 类异常的唯一升级出口(✗ 类走直报 L671)。
- ⇒ 这两个任务"连续 3 tick(45min)degrade"= 常态时长的 3~180 倍,「45min 未定论」本身即强异常信号。

---

## ④ 候选修法对比(均精确到行;可逆性/测试见 ⑦)

### 候选 A(推荐):计数桶补 seen(1 行,可选叠加 1 行)

- **改动**:L770-776 写桶后加 `seen_keys_this_run.add(_bk)`;可选 L826-831 inline 恢复加 `"consecutive_count": 0`。
- **效果**:连续 degrade 累计 1→2→3 → SEVERE(驱动 S3);alerted 后 dedup_key(=L718)持续 seen、有 suppress(L811-816)不重发;链断→inline/恢复循环照常清、下轮从 1 起(驱动 S1b)。语义=**按 tick 的 45min 未定论哨**。
- **误伤**:仅新增"跨 ≥3 个连续 tick degrade"才发的告警(生产 30 天 0 例);长跑任务(update_all 类,常态 85-175min)+ ⚠ 的组合理论上有误报面(30 天 0 例),缓解见 ⑤。
- **可逆**:单点 1-2 行,无新增 state 字段、无 state 迁移(alert_state 为自由 json,旧代码兼容)。

### 候选 B(函数化同构):整块换 `adr.r1_buffer_judge` 调用(overview 同款)

- **改动**:L759-832 替换为 judge 调用(~20-30 行)+ `_bk` 加日期维度(`{task}|marker_buffer|YYYYMMDD`)+ 三类 tick(degrade/非 degrade 异常/无异常)都要覆盖调用以清理计数。
- **效果**:与 overview/r2_overview 完全同构,复用已测试函数(`test_alert_denoise_20261001.py`)。
- **代价/风险**:judge 的 `else: count+1`(L262)对"被恢复循环翻 recovered 不清 count"是电感(靠 L243-253 恢复路径清 + 日期维度防残留);移植到 marker_buffer 需补齐"非 degrade 异常 tick 也清"的覆盖,否则有"残留 count 续数假升级"新风险;改动面大、跨文件。
- **结论**:可行但有真实新增风险,收益(模式统一)低于成本。

### 候选 C(照抄 #181 三改:轮去重 + 保链 + seen)——**评估结论:不适用,勿采用**

- 轮去重键=stats `last_run`(分钟串)。r2_skip 的"轮"=**run 轮**(skip 是每轮发生的事件,同 run 被 3 tick 看到=同一事件);degrade 的"轮"=**monitor tick 轮**(是"未定论状态持续"而不是"每轮发生的事件")。
- 照抄后果(驱动 S4 演示):单个长跑/卡死 run 整段被压成 1 次计数 ⇒ "3 个 distinct run"又几乎不可能连续出现(run 结束/dedupt 清链)⇒ **把已死的链换成另一种死法,45min 卡死前置哨彻底消失** —— 这不是修复,是删除功能。
- 附:`r2_lag` 注释(L2144-2148)与 miss|(窗口 30min÷15min=最多 2 tick)均证明:本脚本内"按 tick 的连续轮"是既有且正确的一族口径,marker_buffer 属于该族。

---

## ⑤ 误伤风险(什么改法会破坏判别力)

### 5.1 会破坏判别力的改法(排除项)

1. **照抄 #181 轮去重(候选 C)**:把"按 tick 的 45min 未定论哨"改成"按 run 去重" ⇒ 单 run 长跑/卡死被压成 1 次计数 ⇒ SEVERE 实际不可达(驱动 S4)。= 换一种方式废掉已死的链,判别力再降一级。
2. **只动恢复循环通用代码**(给 marker_buffer 加豁免前缀等):L1676-1684 是 30 天 121 次 silent recovery 的全链公共路径,动它=跨链回归面;候选 A 用 seen 局部解决,无需碰通用代码。
3. **单独把 L768 `else: _c=1` 改 `count+1`(judge 式)而不配恢复清零点**:被恢复循环翻 recovered 时 count 残留 → 下次单次 degrade 续数 ⇒ 假升级(这正是 r1_buffer_judge 必须配 L243-253 恢复清 count + 日期维度 key 的原因)。单独改动=新增误报面。
4. **调阈值/调文案常量**:`TRANSIENT_TIMEOUT_THRESHOLD=3`(45min)与 r2_lag 同族口径;调小(2)= 防抖受损,调大 = 现状已零报、无意义。建议不动常量。

### 5.2 候选 A 的残余误伤面(诚实标注)

- (a) **长任务 + ⚠ 行组合**:update_all 类常态 85-175min,若其在运行中命中 ⚠ 瞬态行,3 tick(45min)后会 SEVERE 而任务实际正常(最后自愈发恢复邮件)。生产 30 天实测 **0 例**(degrade 仅出现于 nextday_gap_check 5.7min / fetch_news 24s 两个短任务);属"理论面>实测面"。缓解:上线观察期(建议 2 周)复核该链 SEVERE 数量与真伪。
- (b) **与已有通道的时间叠加(非重复)**:`nextday_gap_check` 同时在 `DUR_THRESHOLDS`(900s)⇒ in_progress_timeout 在 run 开始+15min(≈09:41)已可报"疑似卡死";marker_buffer(≈+45min)与最终 exit!=0 通道(run 结束)是"未定论→定论"的过程通知,三封可能先后出现。语义不同(卡死初筛/卡死确认/真失败),v1 不做通道合并(合并需按任务 dur 表,复杂度高于收益);`fetch_news` 不在 DUR_THRESHOLDS、last_exit 恒 null,marker_buffer 是其 ⚠ 类异常的**唯一**升级出口(✗ 类另有直报 L671),不可简单删这条通道。
- (c) **状态文件可见性**:修复后桶会产出真正存活的 `pending`(1/3、2/3)/`alerted` 态。已穷举:全 scripts/ grep `marker_buffer` 仅 schedule_monitor.sh 自身(无其他专属消费者);alert_state 的一般读取方(notify.py/alert_ack.py/check_*.py 等)按各自 key 取值,不做全键遍历假设 ⇒ 无消费者破坏面。
- (d) **不动的代价(供决策对照)**:维持死链 = 该场景零报 + 每 tick 自相矛盾日志 + 桶冻结态;维持现状的"误伤"是**假阴性**(该报不报),在"疑似卡死"场景风险高于 (a) 的假阳性(最多一封自愈告警)。

---

## ⑥ 同类穷举(全脚本缓冲/计数链终表)

复核方式:本轮独立读码 + `grep "_bk"` / `grep "|buffer"` / `grep "consecutive_count"` / `grep "seen_keys"` 全出现点交叉。

| # | 链 | key | 计数 | seen | 恢复/清零 | 判定 |
|---|---|---|---|---|---|---|
| 1 | **marker_buffer** | `{task}\|marker_buffer` L760 | L763-769(else 重置) | **无** | inline L822-832 + 恢复循环误翻 | **病态(本案)** |
| 2 | r2_skip | `r2_skip_rounds`+`r2_skip_alert` L954/972 | L957-963(轮去重) | 告警键 L973 | else 清零点 L1013-1022 | #181 已修,健全 |
| 3 | r2_intraday_lag | `r2_intraday_lag\|buffer\|YYYYMMDD` L2139 | L2149-2161(按 tick) | 告警键 L2142 | 前缀保护 L1678 + inline 清 count L2205-2211 | 健全(活样板) |
| 4 | overview_lag_3domain | `...\|buffer\|YYYYMMDD` L1893 | judge L259-262(count+1) | dedup L1898 | judge L250-253 清 count + 日期维度 | 健全(有测试) |
| 5 | r2_overview_lag | `...\|buffer\|YYYYMMDD` L2068 | judge(同上) | L2103 同款 | 同上 + 前缀保护 | 健全 |
| 6 | missed\| | `missed\|{task}\|{hm}\|{date}` L380 | L390-410(pending→2) | **有** L381 | 跨日清理 L1711-1714;窗口 30min÷15min=最多 2 tick | 健全(复核 #181 判非同病:一致) |
| 7 | extra_stale | `{task}\|extra_stale` L1046 | 单次性(无计数链) | 有 | 恢复循环 | 健全(复核一致) |
| 8 | round_incomplete(_ri_key) | `{task}\|round_incomplete` L1094 | 单次性 | **有** L1095 | 下轮 completed ⇒ 未 seen 恢复 L1067 | 健全(复核一致) |
| 9 | exit!=0 | `{task}\|exit!=0\|{code}` L615 | 无计数(stale 保 active) | **有** L616 | 任务跑 exit=0/null 恢复 | 健全(复核一致) |
| 10 | dur 超标 | 见 L859-917 | 单次性 | 有 | dur 回落恢复 | 健全 |
| 11 | in_progress_timeout | `{task}\|in_progress_timeout` L1165 | 单次性 | **有** L1166;hold L1703-1705 | 任务完成恢复 | 健全(生产 328 条实证) |
| 12 | self_heal not_loaded | `{label}\|not_loaded` L1340 | L1356-1368(pending→2) | **有** L1341 | 未 seen 恢复循环 | 健全 |
| 13 | r2_unreachable | `r2_unreachable` L1999 | L2013-2027(pending→2) | **有** L2000 + 前缀保护 | inline L2031-2034 | 健全 |

**结论**:全脚本 13 条链中,**唯一病态=marker_buffer**(①∪②∪③ 三种免疫机制全空,②表);其余 12 条各有至少一种防护。两类"轮"语义并存且各自成立:r2_skip=**run 轮**(事件按轮去重),marker_buffer/r2_lag/overview/missed=**tick 轮**(状态/窗口按 tick),修法选择必须匹配语义。

---

## ⑦ 可逆性与测试方案

### 7.1 可逆性

- 改动=单点 1-2 行(L770-776 后加 `seen_keys_this_run.add(_bk)`;(可选)L826-831 加 `"consecutive_count": 0`)。
- revert=单 commit 反向;无 state schema 变化、无数据迁移(候选 A 不新增字段;alert_state 为自由 json,旧代码读新值字面兼容 — 与 #181 回滚论证同构)。
- 不影响:r2_skip/feeder/前端/数据产物;§21 公示无对象(纯后端监控脚本);§22 一致性无涉(仅本地 alert_state 态)。

### 7.2 测试现状

- `grep -rn "marker_buffer" scripts/tests/` = **0 命中** ⇒ 该链**零测试覆盖**(#181 三改有 test_181_fetchnews_denoise_20261007.py 全套;judge 有 test_alert_denoise_20261001.py;M1 有 test_228)。修复时应同步补测,否则同类第三次复发无人拦。

### 7.3 测试方案(实施时落地,建议 test_232_marker_buffer _*.py)

- t1 源码断言(仿 test_181 L219/L240 风格):计数块含 `seen_keys_this_run.add(_bk)`;且不含 `last_round`/轮去重代码(防误移植)。
- t2 行为驱动(仿本报告驱动):真代码块 exec——tick1-3 连续 degrade ⇒ 打印 1/3、2/3、append SEVERE 恰 1 次;tick4+ ⇒ suppress(L811-816)不重发;clean tick ⇒ 桶 recovered+count 归 0;单 tick degrade ⇒ 无 SEVERE、无残留。
- t3 负控:在未修复版本跑 t2 必红(证明测试对本案有检出能力)。
- t4 零外发哨兵(仿 test_181 L310-325):monkeypatch subprocess/urllib/socket 一调用即断言失败,证明提取块无外发出口。

### 7.4 复现段(报告数字的再生命令)

```bash
# 1) 静态导出 monitor 的 python heredoc 段(不 source/exec 业务脚本主体)
sed -n '64,2775p' scripts/schedule_monitor.sh > /tmp/232-monitor-py.py
python3 -c "import ast;ast.parse(open('/tmp/232-monitor-py.py').read());print('AST OK')"
# 2) 驱动(本次会话临时产物,未入库;sha256 b47327ab1e16ca88...,提取产物 ef0a994e4d5e97a3...)
#    外部 exec 三真块: _recurrence_suppressed(py≈L259-276)、log_anomaly+计数+inline(py≈L645-832)、
#    恢复循环 pending 分支(py≈L1607-1674);打桩外部依赖, 场景 S1/S2/S3/S1b/S4, sh行号=py行号+63
python3 /tmp/232-driver.py
# 3) 生产证据(主控已备的临时文件): /tmp/181-monitor-full.log(2 组 4 行)、/tmp/232-nextday-gap.log(9-29 run 时刻)
grep -n "marker_buffer" /tmp/181-monitor-full.log
```

### 7.5 诚实标注(残余未知,未闭环项)

- F1:update_all 类长任务 + ⚠ 长跑的误报组合概率,30 天生产 0 例但样本窗有限,上线后建议观察期复核(§5.2a)。
- F2:已穷举(marker_buffer 无其他专属消费者);一般 alert_state 读取方按键取值未见全键遍历——若实施时改桶结构(候选 B 的日期维度)仍需二次确认。
- F3:fetch_news `last_exit` 恒 null 的供给链细节属 #181 面,本报告未展开(#181 已审)。
- F4:SEVERE→恢复 的实际邮件文案/静默窗口未实测(未真跑 monitor,遵守 L48 不外发)。

---

**编制**:researcher 子 agent(只读定性,2026-10-07)。方法与边界:static-only 探针 + 提取块驱动 + 云上只读 ssh + 生产日志;未运行 schedule_monitor.sh 本体、未写业务代码、未 commit。本报告与 #181 §7 的逐点出入已显式列于 1.3。
