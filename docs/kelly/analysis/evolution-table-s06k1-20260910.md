# 演进弹窗改表格 = S06+K=1 实操快照 完整调研方案(供用户拍板)

- 日期: 2026-09-10
- 调研人: researcher(只读调研, 未改代码/未重算/未 deploy)
- 测试基准: current baseline(memory `test-baseline-v112-anchor`, 默认=S06 动态基座 + AI仓位建议 K=1)
- 结论先行: **演进表格建议走「方案 B 前端实时」**(复用卡同引擎, 逐位一致零漂移), 同时**后端 `kelly_posrating.py` 已是「S06 实操快照」事实统一后端源**(K1=163.37% 与卡 A=163% 命中, parity 机检在), 演进表格不必等后端; 「S06 per-date 基座全史可用」已实测成立(2010-02-01→2026-09-09, 4033 行)。

---

## 0. 一句话总结(给用户的版本)

你要的「演进表格 = 日期行 × A-I 列, 格子 = 最终收益(元)+峰值资金收益率(%)」, 口径 = 全信号卡(全部信号 = 评级三区并集 7607 笔/模式, 套 S06 per-date 过滤 + K=1 每日只买最优 1 笔 + ETF 费率重算)。

两个关键技术事实决定方案:
1. **S06 per-date 基座全史可用, 且是确定性的** — 前端 `_tdsS06FiltersForDate(date)` 背后 = `kelly_mode_s06_state.json`, 覆盖 **2010-02-01→今天共 4033 个交易日**, 每天一个 effective_mode(a9 进攻 1871 天 / new14 防守 2162 天)。`_tdsS06BaseForDate` 取任意历史日 => 全史每笔信号都能按自己的 signal_date 判定当日基座, **9/4~今天任意历史日都能取**(回填无死角)。
2. **后端已有一条跑通且通过同构对账的 S06+K 实操引擎** — `scripts/kelly_posrating.py` 复刻了 lab.js K 档段(A 模式 all 伪象限 + S06 per-date passesFade + 每日池等分 top-K + 费率重算 + 峰值资金统计), 有 `scripts/check_posrating_parity.mjs` 背书。**今天(9/10)它算出的 A 模式 K=1 `return_pct_max_holding = 163.37%`, 与你 9/4 实测锚点「全信号卡 A=163%」逐位吻合** — 这证明「后端固化实操口径」这条路已经存在且数字可信, 也证明全站只要提到「S06+K=1 A 模式实操收益」, 163% 这个数全站能对上。

所以两条路都是可行的, 差别只在「演进表格自己用哪条」。推荐用前者(方案 B 前端实时), 因为**表格数字要跟卡逐位对得上, 用卡自己的引擎最保险**, 也不引入第二份实现(§5.4⑦)。

---

## 1. 现状盘点: 演进弹窗今天显示的是什么(先认清病灶)

| 项 | 现状 | 问题 |
|---|---|---|
| 演进弹窗数据源 | `signal_kelly_snapshots/index.json`(每日 signal_kelly_snapshot.py 生成) | 每行 modes 只存 `{tr, n}`, tr=静态主档 sig_main all 周期 total_return |
| 静态主档口径 | `signal_kelly_backtest.json` sig_main 象限, **无 S06 过滤、无 K 选样、n=1415/模式** | 跟卡(全信号 7607/模式 + S06+K=1)完全不同体量 |
| 卡的全信号口径 | lab 全信号卡 qk="all" = rating_high+mid+low 三区并集(7607/模式)× S06 per-date × K=1 × 费率重算 | 用户 9/4 锚点 A=163% / H=224.92%(%口径) |
| 一致性现状 | 演进弹窗 ↔ 卡 **数字天然对不上**(静态主档 A total_return_pct=81.25% vs 卡 A≈163%) | 你想根除的就是这个(调研目标 B 核心根源) |
| 9/8 污染 | index.json 9/8 行 G/H/I 曾固化 accum_nav 占位污染(~虚高82%), 9/9 da1064998 已修;**线上 index.json 9/8 污染行未清**(implementer a38e41b 在修) | 与本次调研正交, 不重复处理 |

补充证据(9/10 实测):
- `signal_kelly_trades.json`(前端实际读取, 74.9MB): fields 26 列(signal_date/index_id/signal/buy_date/sell_date/etf_code/etf_name/track_tier/track_score/match_method/track_low_confidence/buy_price/sell_price/shares/profit/return_pct/hold_days/sell_reason/current_price/real_buy_price/real_current_price/market_state/market_tier/market_tier_all/market_tier_cyb/rating), **无 S06 过滤标记**(每行是独立信号, 判定在前端按 signal_date 动态做) — 与任务书一致。
- 各象限计数(9/10 生成): rating_high=860 / rating_mid=14,940 / rating_low=60,270 → **评级三区并集 = 76,070(=7607×10 模式)**; sig_main 象限仅 14,150(=1415×10)。
- 信号日期跨度: 2011-01-19 → 2026-09-08, 1573 个唯一 signal_date。

---

## 2. 调研目标 A: 前端卡计算链路完整梳理(可复用函数清单)

核心函数 = **`_kellyApplyFeeRecompute(feeParams)`**(lab.js L8764, 唯一入口, `async`)。全流程:

```
L8775-8781  td = state.labSigKellyTradesData(16 片渐进合并后的全量 trades)
L8776-8779  fields/fIdx = td.fields 列号映射
L8782       buyAmount = td.buy_amount(默认10000)
L8785       quads = td.quadrants(16 象限 × 10 模式)
L8798-8805  全信号伪象限 quadsAll = rating_high+mid+low 三区模式并集(qk="all" 专用)
L8809-8812  filters = state.labSigKellyFilters || _kellyDefaultFilters()(默认含 positionCap:true, positionCapK:1)
L8838-8897  S06 per-date passesFade / passesFadeNoBull:
               _s6F6(t) = _tdsS06FiltersForDate(t[signal_date])  ← 每笔按 signal_date 取当日基座 58 键布尔
               passesFade     : 基座键集过滤 + 快照缺行 fail-open(_s6OpenSet) + 覆盖期外按 off_base(new14) 兜底(_s6FallbackSet)
               passesFadeNoBull(G/H/I): 当日基座键集 − bullAuxBackupStop(a9 含、new14 不含, 长线豁免)
L8915-8925  positionCap 开启时: basePool = _kellyCollectBasePool(quads, sellModes, fIdx, passesFade)(跨全部卖出模式×评级三分区, baseKey 去重, 只留通过谓词)
L8919       posCapKept = _kellyPositionCapKeptKeys(basePool, fIdx, K=1)  ← 每日只买最优 1 笔(排序: track_score DESC → rating high>mid>low → signal buy_backup>buy>buy_aux>buy_special → buy_date ASC)
L8920       posDayCounts = _kellyKeptDayCounts(posCapKept)   ← 日期→当日保留基笔数(每笔金额=10000/当日保留数)
L8936-8946  阶段1(qk,mode)各桶: toggledByMode = rawTrades.filter(_pf(t) && posCapKept[baseKey]) 
               rawTrades(qk="all") = quadsAll[mode](评级三区该模式并集)
L8950-8990  阶段2: 各 period 从 toggled 子集按 cutoff 取 {buy_date >= cutoff}, 逐笔 _kellyRecomputeTrade(费率重算) → _kellyComputeStats → statsByPeriod
L9040-9060  全信号伪象限按年聚合 allYearlyByMode(「最后结果」按年窗口表):
               _aggYearlyMap(trades) = 按 buy_date 年份分组 → profit/n/wins → peak_capital=_kellyMaxConcurrentCapital → peak_return_pct = 年累计净盈亏/年峰值同时持仓资金×100
L9086-9120  AI仓位建议 K 档评级(A 模式 all 伪象限)写 _AI_POSCAP_RATING_DYNAMIC_LAB(k=1..4)
L9170-9200  result._s6warn(S06 降级警示: fail-open 笔数/覆盖期外笔数)
```

### 可复用「任意轴点重算」的核心函数(全部已模块化, 无闭包内嵌硬编码)

| 函数 | 位置 | 作用 | 演进表格复用点 |
|---|---|---|---|
| `_kellyDefaultFilters()` | L7455 | 默认降亏组合(positionCap:true, K=1) | 固定基准参数 |
| `_kellyPassesFadeFilters(t,fIdx,filters,featCache,tradeDims,monthMask)` | L7677 | 58 键衰减谓词(FRONT10+GATE27+T1 20+X1) | 单笔判定核心 |
| `_kellyCollectBasePool(quads,sellModes,fIdx,passFn,skipRatingKey)` | L7842 | 基笔池(评级三区×10 模式去重) | 每日池 K 选样输入 |
| `_kellyPositionCapKeptKeys(pool,fIdx,K)` | L7800 | K 档每日保留 key 集 | K=1 选样 |
| `_kellyKeptDayCounts(kept)` | L7865 | 日期→当日保留基笔数 | 金额分派 |
| `_kellyPerTradeAmount(t,fIdx,buyAmount,dayKeptCount)` | L7875 | 每笔=10000/当日保留数 | 金额口径 |
| `_kellyRecomputeTrade(t,fIdx,feeParams,amt)` | L7190 | 费率重算(还原无滑点收盘→含费净盈亏) | 单笔利润 |
| `_kellyComputeStats(trades,periodKey,buyAmount)` | L7323 | 全量统计(n/win_rate/total_profit/total_return_pct/max_concurrent_capital/return_pct_max_holding/max_drawdown…) | **格子统计核心** |
| `_kellyMaxConcurrentCapital(trades)` | L7881 | 峰值同时持仓资金(按日期分桶先减后加) | 峰值资金收益率分母 |
| `_kellyBaseKey(t,fIdx)` | L7796 | signal_date\|index_id\|signal\|buy_date\|etf_code | 去重 |
| `_kellyAihlineApply(recomputed,strategy,periodKey)` | L8960 区 | G/H/I 各模式仓位策略(G=P≤3d@10万/H=满仓不买@5万/I=P≤3d@9万, real nav) | G/H/I 格子必用 |
| `_tdsS06FiltersForDate(date)` / `_tdsS06BaseForDate(date)` | common.js L1038/1065 | 日期→当日基座 58 键 / (ok,base,reason) | **每笔 S06 判定的唯一事实源** |

依赖的全局状态(演进表格复用必须同理满足):
- `state.labSigKellyTradesData`(16 片渐进合并, `_labKellyY1Ready/_labKellyAllReady` 标记就绪态, `#100 渐进加载`)
- `state.labSigKellyFilters`(默认 = `_kellyDefaultFilters()`), `state.labSigKellyFadeModeBase`(默认 s06), `state.labSigKellyGihOn`(默认开)
- `_kellyTradeFeatureCache`/`_kellyRecomputeCache`(性能缓存, 口径无关)
- S06 快照 `./data/kelly_mode_s06_state.json`(common.js `_tdsS06StateEnsure` 单例加载)

### 关键事实: S06 per-date 基座历史可用性(命门已实答)

- 数据源 = `static-site/data/kelly_mode_s06_state.json`(生成器 `scripts/gen_kelly_mode_s06_state.py`), 9/10 文件:
  - `coverage_start=20100201, coverage_end=20260909`, `daily=4033 行`, `on_base=a9, off_base=new14`, `threshold=-3.5242…`
  - 每天 `{date, size_spread, premise, effective_mode, decision_date}`; 分布 new14=2162 / a9=1871
  - **确定性**: 生成器只依赖收盘历史序列, 同输入同输出, 新交易日只 append, 重跑不改变历史 daily(3×4 段前侧 2011-2014 用 csi500 代理因子 prepend 覆盖)
- 前端 `_tdsS06BaseForDate`: 日期落在覆盖期内 → 当日 effective_mode(a9/new14)**(ok:true)**; 早于 coverage_start/晚于 coverage_end → 按 off_base(new14) 兜底(**ok:true, reason=out_of_range_fallback**, 不 fail-open); 仅当整个快照缺失/字段缺/覆盖期内缺行 → ok:false(fail-open)。
- **结论: 任意历史日期(2011-01-19 首笔信号 ~ 今天)都能取到确定基座**, 方案 B(前端实时)与方案 A(后端固化)的历史回填均无障碍。覆盖期外兜底只影响"未来边界", 对全史回填无影响。

---

## 3. 调研目标 B: 两候选方案全面对比

### 方案 A — 后端快照实操化(`signal_kelly_snapshot.py` / `kelly_posrating.py` 扩展)

**做什么**: 把每日快照的 sig_main(静态无过滤)替换/增补为「S06+K=1 实操口径」每模式统计; index.json 每行 modes 从 `{tr,n}` 升级为 `{profit_yuan, return_pct_max_holding, n}`(或并存新旧字段对比期)。

**既有基础(关键利好)**: `kelly_posrating.py compute_posrating`(L829)已实现:
- S06 per-date 判定(`S06Resolver.base_for_date/filters_for_date` L339-396, 与 common.js `_tdsS06BaseForDate` 同构: no_row/not_loaded fail-open, out_of_range/bad_mode 按 off_base 兜底)
- FRONT10+GATE27+T1(20+X1) 完整谓词链(`make_passes_fade` L494, 依赖 `kelly_loss_features.json` meta.rules 规格)
- 每日池等分 top-K + 费率重算 + `_compute_stats`(return_pct_max_holding = 总盈亏/峰值同时持仓资金×100)
- **同构对账机检 `check_posrating_parity.mjs`(§5.4⑦)**: 不重写判定, 直接从 lab.js/common.js 切片源码进 vm 沙箱执行对比, 保证验的就是上线代码本身 — **这就是"第二份实现漂移"的既定缓解手段, 已存在**
- **今天实测锚点**: A 模式 K=1 ret=**163.37%** vs 卡 A≈163% 逐位吻合 → 后端实操引擎数字可信

**扩展量**(从 A-only → 每模式 / 每日期):
1. compute_posrating 目前只算 A 模式 all 伪象限 K=1..4; 演进表格需要 **A..I×J 每模式** → 需要一个按模式循环的变体(`_collect_base_pool` 本身已跨全部模式, kept 逻辑复用)。
2. **G/H/I 需要 NoBull 变体**(G/H/I 长线豁免 bullAuxBackupStop, lab 走 passesFadeNoBull)+ **GIH 仓位策略**(G=P≤3d@10万/H=满仓不买@5万/I=P≤3d@9万, real nav 强平日)-> Python 目前没有; 需补(或按口径标注"G/H/I 行仅 raw 未套仓位法", 与卡不一致不可取)。`_kellyAihlineApply` 是 lab 的, 后端要么复刻要么演进表格 G/H/I 另行处理 — **这是方案 A 的最大工作量点**。
3. 「截至 D 日已平仓」语义(trades 集合按 sell_date ≤ D 截断)需新参数; 每快照日 D 一行 = 一次全史统计(每行 O(7607 log 7607))。
4. 后端 index.json 已有每日生成链(export.py L1221 17:50 调 signal_kelly_snapshot.py + s06_snapshot.sh 20:35 链重算 latest_posrating+R2 即时上传); 扩展后新增字段随既有 `upload-kelly-snapshots`(R2)与 deploy 渠道上线。

**评估**:
- ①过滤复刻范围: per-date 基座后端**自己就有**(`S06Resolver` 读同一个 kelly_mode_s06_state.json), 不用从前端产物读。既有 parity 机检锚定, 重建 index 后跑 `check_posrating_parity.mjs` 扩展版即可。
- ②第二份实现漂移风险: 已在治理中(parity 机检 + 单源键集 FADE_MODE_PRESETS/LEGACY_SPECS 转录 + `kelly_loss_features.json` meta.rules)。风险**集中在 G/H/I 仓位策略与 real nav**, 需要新对账或诚实标注。
- ③历史回填(9/4~9/10): **可行**。S06 全史可用 + 已平仓卖价=历史收盘价稳定(closed-by-D 逐位稳定); but 「当天卡上看到的数字」与「今日回填 D 行」在未平仓部分有小差(采用 closed-by-D 语义则撇除未平仓, 无此差)。更早历史(2011 起)按 closed-by-D 同样可回填(不需要当日快照文件)。
- 劣势: 数字是"第二份实现"产出, 用户逐位比对卡仍可能发现微小漂移点; 每天一次全史每模式统计计算量适度(7607×10 模式费率重算缓存 + 每行统计 O(n log n), 秒级)。

### 方案 B — 前端演进表格实时重算(lab 页内)

**做什么**: 演进弹窗改表格, 直接读已加载的 `state.labSigKellyTradesData`(16 片渐进, 现在就在内存里), 复用 `_kellyApplyFeeRecompute` 同款链路按「快照日 D 行 = 每模式 closed-by-D 前缀统计」渲染, 不 fetch index.json 的 ops 数字。

**实现要点**:
- 轴点 = 全部 signal_date(1573 个)/ 默认近 N 行可切换;"截至 D 日已平仓" = toggledByMode[mode] 按 sell_date ≤ D 前缀。
- **性能**(关键): 每模式原始集 7607 笔。若对每个轴点每模式跑一次 `_kellyComputeStats` = 1573×10=15,730 次全统计, 每个 O(n log n) → **不可接受**。需增量扫描:
  - 累计净利 = 按 sell_date 排序的前缀和(一次性 O(n log n) 排序 + O(n) 前缀和)
  - 峰值同时持仓资金(D) = 前 N 笔(已平仓)的最大同时持仓 → 事件差量 + 区间加/线段树维护全局最大值一次扫描 O(n log n) → 得所有前缀的峰值资金
  - 巅峰资金收益率(D) = 前缀累计净利 ÷ 前缀峰值资金 × 100
  - 结果: 全史 1573 行 × 10 模式 ≈ 每模式 O(n log n), 总计毫秒~百毫秒级(**可行**)
- 分片就绪门控: 表格应加 `_labKellyAllReady` 门(阶段 2 全量前不渲染全史行, 与卡同款「全量计算中」占位, §23.15 精神)。
- 数据就绪性: trades 已在页面上(16 片渐进, recent.json 标记版本), **零新增 fetch**; S06 状态已在(`_tdsS06StateEnsure`)。

**评估**:
- ①演进轴点: 全部 signal_date(1573 行)或快照日(现状 7 行)+ 默认近 N 行; 建议默认近 60 行/近 12 月, 全史可滚动。
- ②性能: 增量扫描后可控制(见上), 但需一位 implementer 认真做前缀扫描(自测 1573 行×10 模式耗时)。无法接受时退化为「每轴点全统计」+ 默认近 30 行。
- ③每日固化含义: **closed-by-D 语义下历史行天然稳定**(已平仓卖价固定 + S06 基座确定性 + K=1 选样确定性), 实时重算 ≠ 数字漂移; 未平仓部分随 current_price 浮动的盘面在 closed-by-D 下被撇除, 只有「最新一行」的横段差异(卡 all 周期含未平仓, 表格行撇除)。**需要向用户说明这个语义差异**(见 §5 诚实标注)。
- ④实时联动: 表格数字随降亏组合勾选/费率档变化(与卡同源同步联动) — 这支持"探索", 但若用户想要"固定口径的演进快照"(不随勾选变), 需在表格上加「基准口径=默认 S06+K=1」标注或冻结参数快照。

**关键可行性(已实答)**: S06 per-date 基座全史可用(§2), 方案 B 无历史障碍。

### 方案对比表

| 维度 | A 后端固化 | B 前端实时 |
|---|---|---|
| 与卡逐位一致性 | 需 parity 机检维持(已存在, 但 G/H/I 仓位法需新对账) | **天然逐位一致(同一引擎)** |
| 历史回填 | closed-by-D 可行 | **无需回填**(当前数据直接算全史) |
| 数据就绪 | 每日生成 + R2/deploy 渠道 | **页面内已有**(16 片渐进, 零新增 fetch) |
| 计算成本 | 每日一次后端全史统计(秒级) | 打开弹窗时前端增量扫描(毫秒~百毫秒级) |
| G/H/I 仓位法 | 需补 NoBull+策略+real nav(最大工作量点) | 复用 lab `_kellyAihlineApply`(现成) |
| 数字稳定性 | 固化冻结(留存历史记录) | closed-by-D 下历史行稳定; 未平仓撇除 |
| 变更联动 | 改算发时点/口径需重跑+回填 | 自动跟随卡口径 |
| §5.4⑦ 漂移风险 | 中(有 parity 兜底) | 低(零第二实现) |
| 是否服务其他消费点(K评级/排序) | 是(latest_posrating 现成) | 否(K评级已另走后端) |

### 统一数据源问题的裁决(协调者补充维度)

用户定调「全站消费 S06+K=1 实操快照做快速展示/评级/排序」→ 盘点消费点(§23.3):

| 消费点 | 当前数据源 | 口径 | 一致性 |
|---|---|---|---|
| 首页 AI仓位建议 K 按钮评级 hoverpop | **后端 `latest_posrating.json`**(kelly_posrating.py, 每 20:35 s06 链生成 + R2 即时上传) | S06 + A 模式 all 伪象限 K=1..4(ret/dd/ra/n), **K1=163.37%** | ✅ 与卡 A=163% 吻合(parity 机检) |
| 凯利区 K 档评级(卡内/AI仓位建议面板) | lab `_kellyApplyFeeRecompute` 实时 | 同上, 实时 | ✅ 同引擎 |
| 凯利区全信号卡 / 最后结果全信号表 | lab 实时(评级三区并集) | S06+K=1+费率(含 GIH) | ✅ 用户锚点 A=163%/H=224.92% |
| 首页 AI建议 1/2/3 + 当日已满 | **实时信号列表**(overview/_bt_in_universe + 按 track_score 排序 top-K) | 活信号层, 非凯利历史层 | ⚠ 不同层(table 语义), 与快照互补不冲突 |
| **演进弹窗** | **静态主档 sig_main**(无过滤/K) | sig_main n=1415/模式 | ❌ **不一致(本次改造目标)** |
| 静态兜底 _AI_POSCAP_RATING(86.60% 八键历史) | common.js 静态常量 | 旧基座快照, 仅回退用 | 已标注历史, 仅兜底 |

**结论**: 「S06 实操快照」已经事实上有后端统一源(`latest_posrating.json`, K 评级在消费、parity 在保持)。**缺的不是"再建一个统一源", 而是「演进弹窗这一个消费点没接上实操口径」+「后端源只有 A 模式, 未扩展到每模式/每日期」**。两条路线统一为:
- 演进表格本体 → 方案 B(前端实时, 与卡同引擎, 零额外数据链路)
- 后端统一源 → 可选增强: 把 kelly_posrating.py 扩到每模式(顺带格林 with G/H/I), 供未来任何"快速展示该口径"的需求; 演进表格若需要"无 JS 页面的静态表格/SEO"才读它, 否则不依赖。

---

## 4. 调研目标 C: 演进表格 UI 形态建议(Implementable spec)

- **结构**: `[日期 行] × [A B C D E F J G H I 列], 每格两行小字: 第一行 = 累计净利(元, +/− 着色), 第二行 = 峰值资金收益率(%, +/− 着色)`。参考现「全信号表·按年窗口增长」(lab.js L11480-11530)呈现(表头 sticky, 金额右对齐, 正负 class)。
- **沿用能力**: `_labKellyEvoModalHTML` 现已有的 `modeKeys=["A","B","C","D","E","F","J","G","H","I"]` 列顺序、`lab-kelly-evo-table` 表样式(lab.css L1391-1394)可复用。
- **轴点范围**: 默认展示**近 60 个交易日(约 3 个月)** 行 + 日期粒度切换(快照日/自然日); 全史 1573 行可滚动(lazy/virtualize 或「加载更多」)。曲线视图(现有 SVG)保留, 作为表格上方可选 Tab「曲线 / 表格」切换(共存不互相替换)。
- **空值/污染日**: 9/8 污染行已由防污染逻辑置 None(index.json modes.{m}.polluted=true)➔ 表格格显示「—” + title 标注「污染日已拦截」; 数据未就绪(阶段 2 未全量)显示「…」+ 全量加载中徽标。
- **口径标注(§21 公示)**: 表格上方一行说明: 「口径 = 全信号卡(评级三区并集)× S06 动态基座(按每笔 signal_date 取当日 a9/new14)× AI仓位建议 K=1(每日只买最优 1 笔, 每日资金池 1 万等分)× ETF 主流费率重算; 历史上行 = 截至该日已平仓口径」; 数字与全信号卡「最后结果」同源实时重算(方案 B)或 daily 快照(方案 A 标注快照日)。
- **「最终收益/峰值资金收益率」与卡字段映射**: 累净利(元) = `total_profit`; 峰值资金收益率(%) = `return_pct_max_holding`(= 累计净利 ÷ 峰值同时持仓资金 × 100, 与卡/按年表 peak_return_pct 同口径公式, §22)。

---

## 5. 调研目标 D: 数据就绪 / 定时 / 上线联动

- **方案 B(推荐)**: 纯前端, 无后端数据就绪问题。依赖: `signal_kelly_trades.json`(16 片)已在 lab 页面加载; `kelly_mode_s06_state.json` 每日 20:35 重生(s06_snapshot.sh, launchd `com.trade.s06-snapshot`)+ 17:50 export 链也生成 → 基座当日权威。**上线=改 lab.js/lab.css + bump + deploy**。R2/deploy 零新增。
- **方案 A**: 扩展 `signal_kelly_snapshot.py`(export.py L1221 17:50 链)与 s06_snapshot.sh(20:35 链)一起生成新字段; 随 `upload-kelly-snapshots`(R2)+ deploy 渠道上线; 需要新 parity 或新对账脚本(§5.4⑦)。挂机时点注意 §14(17:50 不推 main, deploy 安全窗口)。
- **版本策略(§5.4⑥)**: 演进表格是**展示层换数据源 + 口径标记**, 不改 AI 推荐/降亏过滤的默认组合/算法本身 → 属「纯新增展示」, 可作常规发版(不强制升基准)。但**若改动让「演进」入口展示的口径被用户当作权威快照, 建议随版本公示 §21 注明**; 保守派可发中间版本(v1.1.17→v1.1.18)同步公示与 README。

---

## 6. 调研目标 E: 结论与实施步骤化清单

### 结论

**推荐「方案 B: 演进表格前端实时重算」**:
1. **零第二份实现**(§5.4⑦), 表格与全信号卡逐位一致, 用户拿卡数字对表格必对得上 — 这是本次需求验证的硬标准。
2. **S06 per-date 基座全史可用已实测**(2010-02-01→今, 4033 行确定性), 历史回填无死角; **当前数据即可算全史 2011-01-19→今的 closed-by-D 曲线**, 无需每日固化、无需等回填。
3. **页面数据已就绪**(16 片渐进加载在 lab 内存, 零新增 fetch / R2 / cron)。
4. 性能风险可控: 单模式 7607 笔, 增量扫描(前缀和 + 事件差量线段树)获 1573 行×10 模式在毫秒~百毫秒级; 兜底退化为近 30 行全统计。
5. 后端 `latest_posrating.json` 已是「S06 实操快照」统一源(K1=163.37% 与卡 A=163% 命中), 供 K 评级等快速展示位, 不与 B 冲突 — **演进表格不需要 A**, 但 A 作为「顺带扩展全模式后端源」可后置为可选增强。

**不建议** 用 A 做演进表格主路: 主要卡在 G/H/I(NoBull + 仓位策略 + real nav)的第二份仿真是最贵的工作量, 且用户会拿它与卡逐位比对, 任何漂移都要返工; B 天然规避。

### 1:1 数字举例(给用户的三档互证, §23.9)

> 「9/9 快照的 A 模式」= **截至 9/9 已平仓** 的 A 模式 S06+K=1 操作集: 每笔金额 = 10000 ÷ 当日保留基笔数(K=1 每日最多 1 笔 → 基本恒 1 万/笔, 当天最多 1 笔时即 1 万; 若当日多信号同分池才摊薄), 每笔按 ETF 主流费率(万 0.5/最低 0.1 元/滑点 0.001, 强卖无印花税)重算净盈亏, 累计得 X 元; 峰值资金收益率 = X ÷ 截至 9/9 历史上同时持仓占用过的最大资金 × 100 = Y%。
> 数字校验即可信锚: 今天(9/10)`latest_posrating.json` K1(A 模式·全史·含未平仓)= **163.37%**, 与你 9/4 锚点 A=163% 一致; 演进表格「最新一行」若按 closed-by-D 应略低/接近 163%(撇除少量未平仓), 「9/9 行」应≈今日 9/10 行(9/9~9/10 已平仓增量小); H 模式「满仓不买@5万 real」≈ **224.92%(你 9/4 实测)** vs 卡内 tooltip 硬编码 230.83%(9/3 拍板数)→ 表格应显示**实时重算值**, 不写死, 两者差异即「静态文案 vs 实时口径」的活例子, 建议一并把硬编码 tooltip 改标注「实时值以卡/表格为准」。

### 实施步骤化清单(拍板后)

- **(角色: implementer, B 级)**
  1. lab.js 新增 `_labKellyEvoTableBuild()`: 取 `state.labSigKellyTradesData`, 复用 `_kellyApplyFeeRecompute` 的 toggledByMode 逻辑(抽出一个 `_kellyOperationalPool()` 返回 {perModeTrades 按 sell_date 排序}), 增量前缀扫描算每轴点每模式 {profit_yuan, return_pct_max_holding, n}。
  2. G/H/I: 遍历时用 passesFadeNoBull + `_kellyAihlineApply`(GIH 开时), 与卡同口径。
  3. `_labKellyEvoModalHTML` 改造: 表格主体 = 每行日期 × 10 列每格两行小字; 保留曲线 Tab; 加「近 60 行 / 全史」粒度切换; 门控 `_labKellyAllReady`。
  4. 口径标注一行(§21)+ tooltip; 空白/污染日渲染。
  5. 自测: 1573 日×10 模式全史耗时; 最新行 vs 卡「最后结果」A/H 逐位对账(§5.4⑦ 页面实测)。
  6. CSS(lab.css)+ README(功能亮点/口径)+ bump 版本串 + build_min + deploy; 不推 main(走 feat 分支+main-merge.sh)。
- **可选增强(后置)**: kelly_posrating.py 扩到每模式(含 G/H/I 策略), 扩展 `check_posrating_parity.mjs` 到每模式对账, 输出每模式全史实操统计 → 供未来快速展示位; 不改演进表格主路。
- **验收口径**(reviewer): 「方案 B 无第二实现 + 表格 vs 卡逐位一致(report 含对账行)+ §21 口径标注已加 + README 同步 + 全史 1573 行渲染性能审计」。

---

## 诚实标注(不能建立在未验证假设上)

1. **closed-by-D 语义 vs 「卡 all 周期含未平仓」**: 演进表格历史行采用「截至该日已平仓」是**推荐语义**(稳定、可回填、可实时算), 但与该日卡上看到的「all 周期」数字在**未平仓部分**有差 — **需用户拍板是否接受**。若坚持「跟卡 exactly 同数」, 则每轴点含未平仓(按 current_price 预估), 历史行会随数据源漂移且不能精确回填过去。
2. **G/H/I 行 = 默认 GIH 开下的仓位法口径**(G=P≤3d@10万 / H=满仓不买@5万 / I=P≤3d@9万, real nav 强平日 >20 倍本金即 rep期仓法成为方差): 该口径好于定位, 但 real nav 依赖外部数据(real_buy_price/real_current_price 字段已在 trades 26 列)+ `_kellyRealNavEnsure` 单例; 演进表格如需 H/I 逐位=卡, 必须 GIH on 同路径算; **未拍板前不臆断 G/H/I 用 raw 口径**。
3. **方案 B 全史性能是「增量扫描」设计, 未在真实 74MB 数据上压测**: 理论 O(n log n) 可行, 但需 implementer 实测; 兜底方案(近 60 行全统计)已给。**此点是全案最需实测验证处**。
4. **历史行「每日固化冻结 vs 当前数据 closed-by-D 等价」** 的论证依赖「已平仓卖价=历史收盘价固定」+「S06 基座确定性」, 已从数据源性质验证(静态断言), 未做逐位抽样核; 若数据源历史 K 线被复权修正(gen_kelly_mode_s06_state.py 自述场景)则 S06 或卖价会重算 → 表格历史行会整体漂移一次(属数据源修正非算法漂移, 诚实标注)。
5. **9/8 index.json 污染行清理属 implementer a38e41b 在途任务**, 本次调研未动; 方案 B 下演进表格不读 index.json 的 ops 数字(只读日期序列), 污染行天然失效。
6. **静态主档与卡的数字来源本质不同**(同款 7607 vs 1415、total_return 口径单位不同)在 §1 已实据确认, 不作为「谁对谁错」判定 — 只是「演进弹窗不能再挂静态主档」的根因证据。

---

## 复现

- 脚本路径: 本文档为只读调研, 无生成脚本。所有断言可复现命令如下(均为只读):
  - S06 覆盖断言: `python3 -c "import json;d=json.load(open('static-site/data/kelly_mode_s06_state.json'));print(d['coverage_start'],d['coverage_end'],len(d['daily']))"`
  - 卡链路锚点: `grep -n "_kellyApplyFeeRecompute\|_kellyComputeStats\|_kellyPassesFadeFilters\|_kellyPositionCapKeptKeys\|_tdsS06FiltersForDate\|peak_return_pct" static-site/lab.js | head`
  - 象限计数: `python3 -c "import json;q=json.load(open('static-site/data/signal_kelly_trades.json'))['quadrants'];[print(k,sum(len(q.get(k,{}).get(m,[])) for m in ['A','B','C','D','E','F','J','G','H','I'])) for k in ['rating_high','rating_mid','rating_low','sig_main']]"`
  - 后端实操锚点: `python3 -m json.tool static-site/data/signal_kelly_snapshots/latest_posrating.json | head -40`(K1 ret=163.37%)
  - parity 机检(方案 A/后端源): `TRADES_JSON=... BT_JSON=... S06_JSON=... FEAT_JSON=... node scripts/check_posrating_parity.mjs`
- 输入依赖(只读): `static-site/data/signal_kelly_trades.json`(74.9M, 2026-09-10 08:24)、`static-site/data/signal_kelly_backtest.json`(2026-09-10 08:24)、`static-site/data/kelly_mode_s06_state.json`(2026-09-09 20:35, 覆盖 20100201→20260909)、`static-site/data/signal_kelly_snapshots/index.json`(9/10 08:47, 7 快照日)、`static-site/data/signal_kelly_snapshots/latest_posrating.json`(9/10 08:24)。
- 数据截止: 2026-09-10。
- 关键口径一句话: 全信号卡 = 评级三区(rating_high+mid+low)并集 × S06 per-date(每笔按 signal_date 取 kelly_mode_s06_state.json 当日 a9/new14 基座 58 键) × AI仓位建议 K=1(每日按 track_score desc 等序只留 1 笔基笔, 每日资金池 1 万等分) × ETF 主流费率(万0.5/最低0.1/滑点0.001) 重算; `峰值资金收益率 = 累计净盈亏 ÷ 峰值同时持仓资金 × 100`(=卡 return_pct_max_holding / 按年表 peak_return_pct 同公式)。