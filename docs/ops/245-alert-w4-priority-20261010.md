# #245 告警收敛 W4+ 优先级调研（只读）

> 角色: researcher agent（全程只读——零写生产、零 R2 写、零告警外发、未跑任何业务脚本主体）
> 时点: 2026-10-10（周六,非交易日）12:48 ~ 13:1x CST
> 依据: `docs/ops/alert-convergence-plan-20261010.md`（W4+ 建议队列）· `docs/ops/alert-system-fullchain-audit-20261009.md`（全链审计）· `docs/ops/1009-real-faults-rootcause-design-20261009.md`（§C 双树根因）· 云上/本地实测数据（见 §1、§7）
> 任务: 给 **L3c / L3e / L2 / L5** 四条排序 + 实施路径（预期降噪量 / file:line 改点 / 风险 / 依赖顺序 / 与已上线 W1·W2·W3 交互 / §23.3 穷举扫描）

---

## 0. 一句话结论

**排序: L2(第一,唯一量级杠杆) > L3e(第二,1 行结构前提) > L3c(第三,便宜小修) > L5(绑定 L2 后置,验收协议)。**
**批次: 批1 = L3e（独立小批、低时段切换+观察日）→ 批2 = L2（含恢复闭环 + B4-3 遗留收口；L3c 同批顺手做掉）→ L5 随行常驻（即刻用 W1 起步量基线，正式判决在批2 后）。**
量级预演（10-09 全量 24 条回放）: 已上线修复后可减到 ≈14 条 → 批2（L2+L3c+收口）后可减到 **≈5~6 条直发 + 1 条摘要（≈6~7 条/事件日，-70%）**；稳态日（10-06/10-07/10-10 的 1~2 条）几乎都属「首报」不受预算影响，维持 ≤3。

---

## 1. 实测数据（含窗口标注）

### 1.1 W1 台账窗口(过短,显式标注:不单独支撑结论)

- 云上 W1 三件到达时间（mtime 实测）: `gen_schedule_stats.py` 10-09 23:08（#181race）、`alert_denoise_rules.py`/`check_failed_units.py` 10-09 23:46（#240②）、`schedule_monitor.sh`/`notify.py`/`alert_meter.py` 10-10 01:18（W1+W2）。
- **台账窗口 = 10-10 01:18 ~ 调研时点（≈11.7h），仅 1 条**: 10-10 08:27:04 `cloud_unit_patrol_drift`（tier=critical, group=alert, tree=运行树）。信号树无台账文件；两树 `alert_daily.json` 同内容（total=1, by_group={alert:1}, trees=[运行树,信号树]）——W1 §22 跨树一致已实证。
- **窗口太短 ⇒ 本报告主基线不用台账，改用两树 `latest.md` cap50 实测（覆盖 10-05~10-10 完整一周）+ 10-08/10-09 两份审计分解叠加。**

### 1.2 两树 latest.md 逐日 × 族矩阵(实测,week = 10-05 ~ 10-10)

运行树 50 条（cap50 满,最早 10-05）+ 信号树 10-09 独有 1 条 = **本周实测 51 条**（另 10-10 当天 2 条见下）:

| 日 | R2族 | deploy校验 | monitor批[N项] | unit巡检族 | §22一致性 | 伪跳空 | 凯利盘中 | 心跳 | 数据缺口族 | 合计 |
|---|---|---|---|---|---|---|---|---|---|---|
| 10-05 | 2 | | 3 | | | | | | | 5 |
| 10-06 | 1 | | | | | | | | | 1 |
| 10-07 | | | 2 | | | | | | | 2 |
| 10-08 | 2 | 2 | 6 | 3 | 1 | | 1 | 1 | 1 | 17 |
| 10-09 | 3 | 1 | 4 | 11 | | 1(运行树)+1(信号树) | | | 3 | **24** |
| 10-10 | | | | 2 | | | | | | 2 |

族周合计: unit 巡检族 16（32%，重灾日集中）、monitor 批 15（30%）、R2 族 8、数据缺口 4、deploy 校验 3、伪跳空 2、其余 3。
**结论锚点: 事件日（10-08/10-09）的量 = 15~24 条；稳态日（10-06/10-07/10-10）= 1~2 条**——「0~3/天」的缺口全在事件日。

### 1.3 10-09 全量 24 条分解(审计 §4 表 20 条 + 22:00 后增补 4 条,逐条定性)

审计 20 条（截至 22:00）: 真故障 5 / 机制噪音 9 / 假阳(含嫌疑) 4 / 重复次生 2。22:00 后增补: 22:35×3（数据缺口: 交易记录断档 / 交易记录落后 / 公募 NULL）+ 23:30×1（unit 巡检 1 项）。
关键次生结构（本报告用于 L2/L3e/收口的定量）:
- **unit 巡检族 11 条**: 9 条「巡检异常」+1 漂移（08:27）+1（23:30）; 其中 4 条纯集合缩小、2 条抖动（D3 放大器）。
- **monitor 批 4 条**: 01:45/10:45/22:00 = fetch_news r2-skip（单通道）; 09:45「2项」= 09:31 伪跳空的第 3 条复读（D2）。
- **伪跳空 2 条** = 同一事实 py/sh 双 key 双发（09:31:37 信号树 + 09:31:43 运行树）。
- **R2 族 3 条**: 00:22 触发碰撞假阳（F2） / 01:12 etf-hist 真断 / 17:35 index 真断。
- **数据缺口 3 条**: 同轮（22:35:24/31/35）3 个不同 key 各发一封。

### 1.4 已上线修复对本周基线的削减(用于「残余」估算)

- **#181race**（10-09 23:08 到云）: #181 复核实测 **13/13 个历史 SEVERE 样本皆命中幻影判据**（counted=3/distinctRounds=2）⇒ 10-09 的 3 条 fetch_news skip（01:45/10:45/22:00）属该类,修复后应不再出现（修复后至调研时点零新增,含 10-10 非交易日 —— 诚实标注: 无修复后生产样本,残余只能区间式估计）。
- **#240② 方向感知**（10-09 23:46 到云）: unit 族 9 条「巡检异常」中,纯缩小 4 条 + 同集合当日重复 1 条 + 抖动 2 条 ⇒ 约 7 条不再发; 残余 ≈「每日首报 1 + 真实新增/变更」。
- **量化回放**: 10-09 的 24 条在两条修复下 ≈ **14 条**（-10）。

### 1.5 关键机制实测(本轮新鲜复核,全部只读)

| 事实 | 实测值 | 出处 |
|---|---|---|
| R5 拥堵日汇总先例 | 云上 `alert_state.json` 共 10 个 `r2_pipeline_congestion|*` 键（10-01~10-10），**summary_sent 全 False、phenomena 最大 1** ⇒ R5 上线 10 天**从未发出过一次汇总**（机制空转,因按文本去重: 同文本重复不计现象数） | 云上 alert_state.json; `alert_denoise_rules.py:555(r5_is_...)` `:577(r5_congestion_process)`; 引用点 `schedule_monitor.sh:2803` |
| 双树 dedup 分裂 | 运行树 51 键 / 信号树 52 键 / 交集 39 / 运行树独有 12 / 信号树独有 13（37% 键窗仅存在于单树） | 两树 `data/notify_dedup.json` |
| 信号树独有 13 键 | `nextday_gap_check_gen_fail`·`nextday_plan_*`(4)·`nextday_plan_gen_fail`·`daily_brief_notify_*`(4)·`sigkelly_snapshot_stagnation_`·`verify_r2_mass_mismatch`·`verify_r2_standalone_stale` —— 全部对应 **py 侧 resolve 链**(nextday_gap_check/nextday_plan_generator/gen_daily_brief/signal_kelly_snapshot/check_data_integrity) | 同上 + `1009-real-faults` §C |
| 云上 symlink | `~/code/trade-data/scripts` → `~/code/trade-data-signal/scripts`（readlink 实测）; py `.resolve()` 落信号树、sh `Path.absolute()` 落运行树 = D1 根因 | 1009-real-faults §C + 本轮 readlink 复核 |
| units REPO env | `/etc/systemd/system/trade-*.service` **41 个,41/41 都是 `Environment=REPO=/home/ubuntu/code/trade-data`**（无第二个值） ⇒ notify.py 接 env 后可确定性单树化 | 云上实测 |
| fetch_news r2-skip 频率 | 窗口内 **8 次/6 天**（10-05 03:30/13:30/18:30、10-07 17:45/18:45、10-09 01:45/10:45/22:00），全部为 #181race 前样本 | 运行树 latest.md |
| W2 三态判据 | `notify_sent.py:notify_state` sent/suppressed/failed; 抑制行签名表 `_SUPPRESS_SIGNATURES` **行首锚定**; tier=warning 的 `defer_status='suppressed'` 必须判 **sent**（反向用例硬约束） | `scripts/notify_sent.py` 全文 |

---

## 2. 逐条评估（每条: 预期降噪量 / 实施路径 file:line / 风险 / 依赖 / 与 W1·W2·W3 交互）

### 2.1 L3c — fetch_news r2-skip 自愈瞬态降 tier

**预期降噪量**: **残余 ≈0~1 条/事件日**（诚实标注: 窗口内 8 次/6 天全为 #181race 前样本,13/13 实锤幻影已被 10-09 23:08 的 #181race 灭; 修复后零新增样本,10-10 周六）。价值定位 = ①语义修正（「真状态/假告警」不再 SEVERE 化）②**防长锁日（≥45min 连续锁忙）重现 SEVERE 轰炸**（10-08/10-09 型事件日本周出现 2 天）。工具性数字: 该通道周内 8 条占 monitor 批 15 条的 53%。

**实施路径(file:line 级改点草案)**:
1. `scripts/schedule_monitor.sh:1107-1134`（r2-skip SEVERE append 块）: 对 transient 任务集（`gen_daily_brief`/`fetch_news`,即 `gen_schedule_stats.py:142 EXTRA_MARKER_SCANS` 两个任务）达阈值后**不 append 到 `alerts`**,改直接调 `notify.py --tier warning --dedup-key {task}|r2_skip_warn --dedup-window 21600 --from-prefix "[告警]"`（先例: 同文件 `:1721-1729` 资源预警 warning 级发送 + 6h 窗）。
2. **升级判据保留**（「锁持续忙仍升级」）: 新增常量（`schedule_monitor.sh:591-600` 常量区,如 `R2_SKIP_ESCALATE_ROUNDS=6`）,连续轮数 ≥ 升级阈值仍走现 SEVERE 路径（独立 key 必达）。
3. 保留 alert_state 计数键/告警键 machinery（`:1112-1135`）不动,使恢复闭环继续成立。
4. **前提修正（本轮实证,必须写进方案否则谎报收益）**: `notify.py:2027-2110 flush_warning_batch` **没有「自愈则取消」机制**——条目满 30min（`WARNING_BATCH_WINDOW=1800`）即聚合成一封发出,不检查底层状态是否已恢复 ⇒ 「期间自愈则永不打扰」**不成立**。首版真实收益 = **延迟（≤30~45min,monitor 15min 一轮尾部 flush）+ 多條合 1 + 4h 指纹窗重复抑制**;要「自愈不打扰」须新增取消机制（flush 前按 key 查自愈状态 drop,或 flush 接受 cancel_keys）——列为**可选增强**,不计入首版收益。

**风险**: §23.7 改已发布判定行为（r2-skip 的 tier 语义）⇒ 需用户点头;判别维度保留=升级档;与 L2 同文件不同段（批 2 合并时注意同文件顺序/冲突面）。§21 无关。§22 无关（单树通道）。
**依赖**: 无前置;可与批 2 同批（改动小且局部）。
**与 W1·W2·W3 交互**: W2 三态逐字核对无打架——tier=warning 走 `路由完成：{... defer_status: suppressed/enqueued}` 形式,`notify_sent`/`notify_state` 判 **sent**（`notify_sent.py` docstring「反向用例」硬约束）;W1 台账会记 tier=warning 的 flush 消息（口径可见,不冒充 severe）;W3 不同链路。

### 2.2 L3e — 双树收口（notify.py REPO 接 env）

**预期降噪量**: **直接 ≈0~1 条/周**（诚实标注: 本周跨树痕量=10-09 伪跳空 1 对,且该对主因是**双 key**——L3e 单独灭不了它,需配 B4-3 统一 key）。**结构收益（真正价值）**: ①run-tree 读侧的「包装器已发不复述」判据族（`wrapper_channel_alerted`, `alert_denoise_rules.py:660`;消费点 `check_failed_units.py:326-327`、monitor 的 r7/196②/123R3 豁免）对 **py 侧告警当前全部失明**（py 写信号树）,修复后生效 ②37% 键窗单树化,跨调用路径不再各起一个窗 ③排障/latest.md 单树化。

**实施路径(file:line 级改点草案)**:
1. **核心 1 行**: `scripts/notify.py:88` → `REPO = Path(os.environ.get("REPO") or Path(__file__).absolute().parent.parent)`（`ALERTS_DIR:92`/`ALERTS_FILE:93`/`DEDUP_FILE:97`/`WARNING_BUFFER_FILE:232` 等全部派生自 REPO,一行即单树化;env 先例本文件已有 5 处实使用: `:118`/`:163`(台账路径/tree 字段)+ `:2406`/`:2446`/`:2496`(升级档)）。
2. 前置实证已齐: 云上 **41/41** units 已设 `Environment=REPO=/home/ubuntu/code/trade-data`（本轮实测）; 手动/无 env 场景回退 `absolute()` = 现行为,零回归。
3. **同类面登记（不必逐个改,修 L86 后自愈,但登记备查）**: `nextday_gap_check.py:44-48`（`ROOT=resolve`, `SCRIPT_DIR=resolve` 传物理路径给 notify）、`nextday_plan_generator.py:70-74`（同款）、`alert_denoise_rules.py:463`（`_root=resolve` 的 R4 状态写失败告警路径）、`gen_daily_brief.py:60`（resolve,其 `daily_brief_notify_*` 键现在落信号树）、`signal_kelly_snapshot.py`/`check_data_integrity.py`（同 13 个信号树独有键来源）。
4. 切换安排: 低时段切换 + 切换日观察（plan §6）; 切换瞬态 = 信号树 dedup 历史不迁移 ⇒ 修复后 ≤6h 窗内同 key 可能补发一次（低危;可选配套: 把信号树 dedup 的 last_alerted 合并进运行树,一次性）。

**风险**: §23.7 notify.py 冻结面（需用户点头,但属「1 行 + 既有先例推广」低风险类）; 切换瞬态一次性; 信号树 `latest.md` 停更（历史留存即可）。§22: 切换后「两树 latest.md 各自写」的一致性隐患**消除**（正是本条要治的）。§21 无关。
**依赖**: 无前置;**是批 2 内 py 侧收口（nextday-gap 双键统一 + 豁免闸）与 L2 单点执行设计的硬前置**。
**与 W1·W2·W3 交互**: W1 台账路径本就 env-first,不受影响且更一致（ledger 单树已是现状）; W2 判据纯文本解析,不受树影响; W3 不同链路。

### 2.3 L2 — 预算 + 摘要层（最大杠杆）

**预期降噪量（数字+数据支撑）**: 以 10-09 全量 24 条、叠加已上线修复的 ≈14 条基线回放: 数据缺口 3→1(+摘要)、unit 族 4→1~2(+摘要)、monitor 批复读 1→0、伪跳空 2→1、R2 族 3→1(+摘要) ⇒ **≈5~6 条直发 + 1 条摘要 ≈ 6~7 条/事件日（-70%）**;稳态日 0~1（首报类不吸收）。数据依据: §1.2 矩阵（monitor 批 15 + unit 族 16 = 62% 的量集中在可预算类）+ §1.5（R5 空转实证——**泛化前必须先治「按文本去重」,改按 key/事实聚合**）。

**实施路径(file:line 级改点草案)**:
1. **政策表单一事实源**: `scripts/alert_denoise_rules.py` 新增 `ALERT_BUDGET_POLICY`（category → 日预算,如 unit族/R2族/数据缺口族/monitor批）+ `category_of(key|subject)` 前缀映射;（audit L2 改动点 3 原案）。
2. **执行点（推荐单点版,与 §5「一步到位」一致）**: `scripts/notify.py` `--severe` 通用路径入口（check_dedup 之前,约 `:2520-2530` 区（实测通用路径 check_dedup 在 :2527））加 budget hook: 读日预算状态（新 `data/alerts/alert_budget_state.json`,day-scoped;或直接读 W1 台账当日计数）,超预算 → 入 digest buffer（新文件同 `warning_buffer.jsonl` 模式）+ stderr 行 `[notify][budget] <key> 并入当日摘要`;23:25 收尾轮由 monitor `--flush-digest`（新增,同 `--flush-warnings` `schedule_monitor.sh:2931` 模式）发 1 条摘要（**必须列出被并条目+条数**,不变式 4）。
3. **monitor 通道最小版（先落地子集,覆盖 30%）**: 泛化 `alert_denoise_rules.py:577 r5_congestion_process` → `alert_budget_process`（按 category,首条直发、超预算移入 summary;改「文本去重」为「key/事实去重」）;调用点 `schedule_monitor.sh:2803`;23:25 收尾轮机制沿用（`summary_hm="23:25"`）。
4. **恢复闭环（治 D5,audit L2 改动点 2）**: `schedule_monitor.sh:2860-2890` 恢复块——现 `--dedup-key schedule_monitor_recovery --dedup-window 21600` 会把**不同任务的第 2 条恢复**吞掉（10-09 实吞 1 条）⇒ 改「key 当日有告警发出 → 其恢复不受共享窗限制（同 key `last_alerted` 关联）」或「被吞恢复进 pending,下次恢复发送时一并列出+注明条数」;per-key `RECOVERY_COOLDOWN`（`:346-358`）保留。
5. 可选（用户拍板）: 非 critical 23:00-07:00 入次日晨间摘要（audit L2 改动点 4）。

**风险**: 过度收敛吞新故障 ⇒ 对策=不变式（首报必达/critical 免预算/摘要必列被并条目+条数）+ 每周 review 找回核对;notify.py 冻结面二次改动（若走单点版）;digest 口径须与 W1 对齐。
**依赖**: **L3e（若走单点版: py 被预算条目的状态必须单树,否则计数分裂）**;W1 已具备（台账即计数依据 + `alert_daily.json` 已有 `merged_in_digest` 字段,`alert_meter.py:137-154` 已读 `merged_count` —— **W1 设计时就预留了 L2 的接口**）。
**与 W1·W2·W3 交互**: ①W2 硬交互——任何新增「吞并/延迟」路径的 stderr 行必须同步进 `notify_sent.py:_SUPPRESS_SIGNATURES`（行首锚定+行内标记;现表 5 类）或复用 tier deferral 形式,否则存量 **9 个** `notify_sent` 调用方会把「并入摘要」误判 failed 而重试 ⇒ 双发。②W1: 摘要消息入台账 1 条 + `merged_count` 计 `merged_in_digest`（直发数+摘要数=总消息数,口径与 L5 判据直接对齐）。③W3 无关。
**范围诚实标注**: monitor 通道（`alerts` list）只覆盖 30% 的量;**unit 族/R2 族/数据缺口族都是各自 wrapper 直发**,不经 monitor list——单点版（notify.py 执行）才能全覆盖,wrapper 版（monitor 通道）只覆盖子集;两者并存为佳（先子集后全量,同批交付）。

### 2.4 L5 — 预算验收层

**预期降噪量**: **0（不直接减量）**。定位 = 把「满意」定义成可验证数字,并给 L2 配安全带。
**实施路径**: ①`scripts/alert_meter.py:272-290 cmd_week` 扩展 P50/P90 输出（或新增 `--budget` 视图: 连续 7 天 P50≤3 且 P90≤5 → PASS/FAIL）;②「被吞条目找回」核对（digest 记录 vs 台账 `merged_in_digest`,可做成 `alert_meter` 子命令）;③每周 review top-talkers（`--top` 已有）。
**风险**: 无冻结面（纯新增查询面）; 唯一注意=判据口径要写死（告警群 alert 口径,report 群/功能输出另列——`alert_meter.py:47 ALERT_GROUPS` 已分离）。
**依赖**: W1（已具备,`--today` 已输出「severe 直发 X / 摘要并入 Z」）;**正式判决价值在批 2 后最大**（L2 前判「0~3」会把预算收益漏算）;即刻可起步=用 W1 台账/两树 latest.md 起基线（本报告 §1.2 即基线）。
**与 W1·W2·W3 交互**: W1 是它的数据源;无冲突。

---

## 3. 排序建议 + 理由 + 批次

| 优先级 | 项 | 排序理由（三条轴） | 预期降噪量 | 风险 | 前置依赖 |
|---|---|---|---|---|---|
| 1 | **L2** | 唯一「量级杠杆」: 事件日 15~24 → ≈6~7（-70%），稳态日不动;W1 已预留接口（merged_in_digest/merged_count）;R5 空转实证已给出「怎么改才对」的教训 | ≈5-9 条/事件日 | 最高（吞并需不变式防护;单点版动冻结面） | L3e（仅单点版） |
| 2 | **L3e** | 1 行改点+41/41 env 实证的确定性;是批 2 内 py 侧收口与 L2 单点版的硬前置;防未来一整类跨树重复 | ≈0~1/周（直接） | 低（切换瞬态一次性） | 无 |
| 3 | **L3c** | 最便宜（局部段）;语义修正+防长锁日重现;残余小（#181race 已灭 13/13 幻影）;须诚实处理「自愈取消不成立」前提 | ≈0~1/事件日 | 低（同文件与 L2 分段） | 无（可与批 2 同批） |
| 4 | **L5** | 不直接减量;验收协议+防回退;判决价值在 L2 后 | 0 | 无 | W1（已具备） |

**批次建议**:
- **批 1 = L3e**（独立小批,1 行+验证+低时段切换+观察日;不与任何其他改动共享文件,先上先稳）。
- **批 2 = L2 + L3c + B4-3 遗留收口**（B4-3 遗留=`1009-real-faults` §B4-3 的 L2 py/sh 双键统一〔推荐 `nextday_gap_check_fail`〕+ L3 monitor 豁免闸〔复刻 r7/196② 模板,`schedule_monitor.sh` 現有豁免区〕——**依赖批 1 的 L3e 才生效**,三者同一「通道收口」主题,同批交付;L3c 改动小、同文件不同段,顺手做掉）。
- **L5 = 随行常驻**: 即刻用 §1.2 起基线;批 2 落地后开始 P50/P90 正式判决;每周 review top-talkers + 被吞条目找回。

**明确不做/后置（穷举扫描后的结论）**: 持续型故障的「每日重播」（漂移/failed unit 每日一条 + day3+ 升级每日续发）是否降频 = **用户政策题**（可能是刻意设计「持续提醒直到处理」）,不擅自归入 L2 预算;见 §5 清单 #5/#6。

---

## 4. 路径汇总（改点清单）

| 批 | 文件:行 | 改点 |
|---|---|---|
| 1 | `scripts/notify.py:88` | `REPO = Path(os.environ.get("REPO") or Path(__file__).absolute().parent.parent)`（L3e 核心 1 行） |
| 1 | 验证: 云上 41 units env / 两树 dedup 键对照 / `latest.md` 单树化观察 | 低时段切换 + 切换日观察 |
| 2 | `scripts/alert_denoise_rules.py` 新增 | `ALERT_BUDGET_POLICY` 政策表 + `category_of()` + `alert_budget_process()`（泛化 `:577` R5;治「按文本去重」） |
| 2 | `scripts/notify.py`（`--severe` 入口,约 `:2520-2530`） | budget hook（超预算 → digest buffer + 可识别 stderr 行） |
| 2 | `scripts/notify.py`（新增 `--flush-digest`） + `scripts/schedule_monitor.sh:2931` 区 | 23:25 摘要 flush（同 flush-warnings 模式） |
| 2 | `scripts/notify_sent.py` `_SUPPRESS_SIGNATURES` | 同步新抑制/延迟行签名（W2 契约,防 9 个调用方重试双发） |
| 2 | `scripts/schedule_monitor.sh:2803` | 调用 `alert_budget_process`（monitor 通道子集版） |
| 2 | `scripts/schedule_monitor.sh:2860-2890` | 恢复闭环: 共享 6h 窗改「配对必达」或「pending 并入下次」 |
| 2 | `scripts/nextday_gap_check.py:72` | `--dedup-key gen_fail` → `nextday_gap_check_fail`（统一,py 先发 sh 兜底） |
| 2 | `scripts/schedule_monitor.sh`（豁免区,复刻 `check_failed_units.py:326`/r7 模板） | nextday-gap 包装器已发时 monitor 不复述 |
| 2 | `scripts/schedule_monitor.sh:1107-1134` | L3c: transient 集降 `--tier warning`（先例 `:1721-1729`）+ 升级档保留 |
| 随行 | `scripts/alert_meter.py:272-290` | L5: `--week` 加 P50/P90 / `--budget` 视图 + 找回核对 |

---

## 5. §23.3 举一反三: 同模式降噪点穷举扫描清单

口径: 对「本周 51 条实测 + 审计 D1-D6/F1-F5 + 已上线修复面」全量扫描,列**未处置/半处置**的降噪点（含证据与归层）:

| # | 降噪点 | 证据（本周实测） | 处置归属 | 预期 |
|---|---|---|---|---|
| 1 | **F2 00:22 systemd-run 触发碰撞误报**（同名 transient unit already exists 被当失败） | 10-09 00:22 1 条;`1009-real-faults` F2 节（实际实例正常跑完 rc=0） | 源侧修（跨厂商语义=同名已在跑视为成功） | ~1/次碰撞 |
| 2 | **D2 包装层+聚合层复读**（wrapper 自身 + monitor 关键词/exit 段再报） | 10-09 09:45 1 条（同 09:31 事实第 3 报）;仅 3 专案（nextday_plan/r2_consistency/cloud_unit_patrol）有豁免闸 | 批 2 收口（豁免闸通用化,模板已在） | 灭 1/事件日+防全类 |
| 3 | **D4 同族多键无总量视图**（R2 族 5+ 键: `r2_upload_trigger_fail`/`deploy_r2_upload_fail`/`intraday_upload_index_r2_fail`/`fetch_news r2_skip`…） | 10-09 R2 族 3 条「三封雷同邮件」;周内 8 条 | L2 类别预算（R2 族） | 3→1+摘要 |
| 4 | **monitor 同轮 exit 段 + 关键词段双段**（1 事实 2 行,「2项」含复杂化） | 10-09 09:45;`1009-real-faults` B4-3 L3①原案（关键词段设计意图本就是 exit=0 盲区兜底） | 批 2 顺带（条件互斥） | 降 digest 噪音 |
| 5 | **漂移每日重播**（持续漂移: 每日 1 条 severe;day3+ 每日 1 条 critical 续发——升级档窗口 21600 < 24h） | 10-09 08:27 + 10-10 08:27 连两天;`cloud_unit_patrol.sh:151-153` 窗 6h | **用户政策题**（是否降 24h 窗/并入摘要） | 1/天（持续期） |
| 6 | **failed unit 每日重播 + day3+ 升级每日续发** | 10-10 00:00「连续 3 天升级 critical」;`notify.py:2485-2514`（#196 升级档; :2503 校验用 `args.dedup_window`=6h） ⇒ 24h 后每日再发 | **用户政策题**（同上） | 1/天（持续期） |
| 7 | **数据缺口 3 检查同轮 3 封**（同脚本同期发现） | 10-09 22:35×3（09-24/09-28 各 2）;`check_data_gap_alerts.py:1554 run_alerts` 单点循环 + `:1458 _notify`(def) 单点出口 ⇒ **本地即可合并**（一封信列 3 项） | L2 类别预算 或 脚本内合并（更便宜） | 3→1 |
| 8 | **恢复被共享 6h 窗吞**（D5） | 10-09 实吞 1 条（age=11683s<6h） | L2 恢复闭环（§2.3-4） | 闭环质量（非减量） |
| 9 | **R2 族 wrapper-direct 绕过 monitor/R5 视野** | 00:22/01:12/17:35 均 wrapper 直发,不进 `alerts` list;R5 只认 monitor 通道 | L2 单点版覆盖面（§2.3 范围标注） | 决定 L2 完整度 |
| 10 | `[提示] R2上传异步锁跳过` 走 report 群 / report 群 18 条盘中信号（功能输出） | 10-08/10-09 report 群 19 条=18 信号+1 提示 | **不降噪**（非告警群口径;`alert_meter.py:47` 已分离口径）;维持标签分离 | — |
| 11 | overfit_monitor `[r2-skip-dup]` 日志 155 行量级 | 日志噪声（非告警）;窗口内 log 观察 | 日志层（低优先,不告警） | — |
| 12 | 双树 `latest.md`/dedup 排障分裂（D1） | 两树各 cap50、键窗分裂 37% | L3e（§2.2） | 结构 |
| 13 | 9:26 东财时点性被拒（B4-4） | 连续 3 日常态;10-09 09:31 真故障 1 条 | 外部源兜底链（`1009-real-faults` §B4-1/B4-4 已列,待兜底修复后观测） | 跟踪项 |
| 14 | `nextday_plan` 系列双写（py/gen+sh） | 9-30 22:35:08 vs 22:35:19 两条同构;`1009-real-faults` §C | 批 2 收口（先例 R3 豁免已存在,py 侧键统一+L3e） | 灭 PVC 类 |

（扫描口径说明: 逐文件 grep 了 `notify.py` 全部引用（全仓 scripts/ 实测 271 行/72 个文件,含注释与字符串;真实子进程调用形态为其中子集）与 `dedup-key` 使用面;上图 14 项外的其余调用点均为「单 key 单通道」正常语义,无同模式可降。）

---

## 6. 复现命令（全部只读）

```bash
# 两树 latest.md 逐日×族矩阵（本报告 §1.2）
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'grep "^## \[severe\]" ~/code/trade-data/data/alerts/latest.md | wc -l'
# R5 空转实证（§1.5）
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'python3 -c "import json;st=json.load(open(\"/home/ubuntu/code/trade-data/data/alert_state.json\"));print([(k,v.get(\"summary_sent\"),v.get(\"phenomena\")) for k,v in st.items() if \"r2_pipeline\" in k])"'
# 双树 dedup 键分裂（§1.5）
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'python3 -c "import json;r=json.load(open(\"/home/ubuntu/code/trade-data/data/notify_dedup.json\"));s=json.load(open(\"/home/ubuntu/code/trade-data-signal/data/notify_dedup.json\"));print(len(r),len(s),len(set(r)&set(s)))"'
# units REPO env 全量（§1.5）
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'grep -h "^Environment=REPO" /etc/systemd/system/trade-*.service | sort | uniq -c'
# 台账/日计数（§1.1）
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'wc -l ~/code/trade-data/data/alerts/alert_ledger.jsonl; cat ~/code/trade-data/data/alerts/alert_daily.json'
# 代码锚点
grep -n "REPO = Path(__file__)" scripts/notify.py                # :88（L3e 改点）
sed -n '1107,1134p' scripts/schedule_monitor.sh                  # L3c 改点
sed -n '2795,2830p' scripts/schedule_monitor.sh                  # L2 调用点
sed -n '577,660p' scripts/alert_denoise_rules.py                 # R5 先例（泛化基线）
```

---

## 7. 诚实标注（§5.1④）

- **窗口与样本**: W1 台账窗口仅 ~11.7h/1 条,不支撑独立结论;主基线=两树 latest.md cap50（10-05~10-10,运行树满 50 早于窗口起点）+ 两份审计分解叠加。周日 10-11 起台账才进入可用期。
- **无修复后样本的项**: L3c 残余（#181race 之后零样本,10-10 周六）、#240② 对 unit 族的实际残余（以 10-09 回放推算,非实测）。均按区间标注,未按「已减」计。
- **L2 回放数字为设计推演**: 6~7 条/事件日 = 对 10-09 真实样本逐条过预算规则的推演（含 R2 族「第 2 条起入摘要」的延迟代价——若用户要求真故障第 2 条也直发,该日 ≈8~9 条）。实施后须按 plan §5 不变式用同一 24 条做「改造前→后」逐条对照表验收。
- **L3c 前提修正**: 原方案「期间自愈则永不打扰」与 `flush_warning_batch`（`notify.py:2027-2110`）代码事实不符（无自愈取消）;已按「延迟+聚合」修正预期。
- **未做**: 未跑任何生产脚本/未触发任何通知;未改任何代码/数据;云上全部只读（新鲜复核含 41 units/双树 dedup/台账/R5 状态 4 组）。
