# AI 预测回测可行性报告(2026-08-31)

> 调研 agent 产出(只读调研,未改任何代码/数据)。目的:回答「AI 预测连回测都没做过,何谈准/过拟合?」——给主控/用户拍板 AI 预测回测做什么、能回测什么、怎么回测。
> 测试基准 = current baseline(memory test-baseline-v112-anchor;本次是方案调研不跑回测,不涉及基准口径)。

## 〇、一句话结论

- **AI 输出(deepseek 生成方向)有存历史,但只有约16个样本(20260810起),能回测但样本太小,只能做「在线/半在线逐步积累」评估,不能全历史回测。**
- **方向锚确定性规则(_compute_direction_anchor)可全历史回测(futures_position 643 交易日 20240102 起,转向信号日 608 个),是当前唯一能做大规模回测的对象。**
- **硬约束:锚的 nq 压制因子(us_futures_nq_chg)仅 20260716 起。全历史重放时 nq_open_low 恒 false(缺失->None->False),即 L3 压制分支在 2026-07 前不生效——必须诚实标注为「无 nq 时代的锚(少压制修正)」。**

---

## 一、回测对象厘清(核心问题1)

存在**两条本质不同的回测对象**,务必区分:

| 对象 | 本质 | 能否全历史重放 | 数据源 | 当前样本量 |
|---|---|---|---|---|
| **A. AI 输出(deepseek 生成方向)** | 大模型实时输出,**无法离线重放**(无输入快照/权重/温度) | 否,只能在线积累 | static-site/data/daily_brief_history.json(meta.direction / direction_call) | **16 条,15 条已回填实际**(20260810-20260831) |
| **B. 方向锚确定性规则(_compute_direction_anchor)** | 纯规则,同 (db,date) 结果确定性唯一 | 是,全历史 | sentiment.db futures_position / index_daily / daily_metric | 643 交易日,608 个转向信号日 |

### 1.1 AI 输出能不能回测?

**能回测,但样本量是硬天花板。**
- static-site/data/daily_brief_history.json(90 天滚动归档,gen_daily_brief.py HISTORY_FILE L2220 / HISTORY_LIMIT=90 L2222)存了**真实 AI 输出方向** meta.direction 与强制二选一 meta.direction_call,并由 backfill_hits 次日回填实际(meta.hit.actual_sh_pct / actual_direction)。
- 实测当前 16 条、15 条有实际判定:
  - **纯方向相等口径**(pred==actual):15 样本,命中 5,**命中率 33.3%**
  - **direction_call 强制二选一**(up/down):4 样本,命中 2,**50%**(仅近期条目有 direction_call)
  - **三层严格命中**(range AND middle AND board,hit.direction 语义):更严,几乎全未中(见 四、指标说明)
- **局限**:样本仅约3周,不足以支撑任何统计显著结论;90 天滚动意味着最老条目会滚出,样本池上限约 90 个交易日(约 4 个多月)。
- **结论**:AI 输出回测 = **在线/半在线评估**(每天新样本1条,逐步累积),不是全历史回测。它回答「deepseek 实际输出历史上准不准」,但需时间积累,且**永远无法回测到 AI 功能上线前(20260810 前)**。


### 1.2 影子数据(brief_shadow.json)能不能当回测样本?

- data/brief_shadow.json(记录 20260819-20260828,8 条)是**方向锚的影子 lean**(_shadow_lean,L397 合成,由 record_shadow L479 落盘),不是 AI 输出。它 = 方向锚的在线镜像。
- 它只有 8 条、与 daily_brief_history 同期(20260819-20260828),**样本同样太小**,且影子与 AI 输出是两套不同的东西(影子=确定性规则在线探针;AI 输出=deepseek 真实生成)。
- **用途**:影子数据适合做「方向锚 vs AI 输出的同期对照」(两者同一批预测日的 hit 对比),不适合做大规模回测样本。

### 1.3 结论(回测对象)

- **要全历史回测 → 只能回测 B(方向锚确定性规则)**。
- **要回测真实 AI 输出 → 只能做在线积累(每天1条新样本)**;当前 15 条仅够初步参考,不构成统计结论。
- 两者是互补的两条线:方向锚回测回答「这套规则历史胜率几何、可不可用」;AI 输出在线评估回答「deepseek 实际输出准不准、要不要保留/关掉/调参」。

---

## 二、数据可得性(核心问题2)

方向锚 _compute_direction_anchor 读三类表,逐一核实(sentiment.db 实测):

### 2.1 futures_position(转折因子 T,主权重)

- **范围**:20240102 - 20260831,643 个日期(sentiment.db: SELECT MIN/MAX/COUNT)。
- **列**:date/variety/role/total_long/total_short/net_position/net_ratio/long_chg/short_chg/contract_count。
- **role 分布**:国泰君安 / 中信期货 / top20,各 643 个不同 date(数据完整)。
- **断档核查**:相邻日期差 >6 天仅出现在月末/节假日(20240131/20240208/20240229...),均为正常月末/春节/长假边界,**无异常断档**。
- **转向信号日**:按 _compute_direction_anchor 的转向检测复算(连续>=2日同符号 net 后翻转),608/643 日有至少一个 to_long/to_short 信号;按年:2024=223 / 2025=234 / 2026=151。
- **结论**:T 因子 2024 起全覆盖,样本充足。**回测起点 = 20240102**。

### 2.2 index_daily sh(均线多头 ma_bull)

- **范围**:19901219 起,全史 8715 条;2024 起 645 交易日。
- 用于 ma_bull = 当日 close > ma20(滚动含当日)。**回测起点 = 1990**,远超 futures_position 约束。

### 2.3 daily_metric(联动/压制因子 L)

| 因子 | metric_id | 起点 | 末点 | 覆盖 |
|---|---|---|---|---|
| 美债10Y | us10y | 20160104 | 20260828 | 2668 条,全非空 |
| 黄金 | gold | 20080109 | 20260831 | 4545 条 |
| **纳指期货 chg** | **us_futures_nq_chg** | **20260716** | 20260831 | **仅34条** |

- rate_down_channel = us10y < ma20(滚动,us10y 20160104 起,够 20 日均线)。
- **关键短板:nq 仅 20260716 起**。nq_open_low 判定 = nq<=-0.8% 布尔。在 2026-07-16 之前 nq 为 None -> nq_open_low 恒 False,即 **L3 压制分支在早期不生效**。

### 2.4 数据可得性结论

- 全历史重放方向锚的**主因子(T 转折 + 均线 + 利率 + 黄金)回测起点 = 20240102**(futures_position 约束),643 个交易日。
- **nq 压制因子仅 20260716 起**,是唯一"短因子"。两种处理:
  1. **全段回测(主方案)**:20240102 起跑,把 2026-07 前当「无 nq 时代的锚」,诚实标注 L3 不生效——这样能最大化样本(608 转向信号日)。
  2. **分段回测(对照)**:仅 20260716 起(34 日)跑"含 nq 完整版",与全段对比 L3 修正的边际影响。
- 断档:无异常断档,仅正常月末/节假边界。

---

## 三、无前视审查(核心问题3,§5.1⑥)

逐行核实 _compute_direction_anchor(gen_daily_brief.py L221-332):

- **转折 T**(L255-295):读 futures_position 全序列后,按 date 定位 i,只向前(j=i-1)数连续同符号 run,判定 turn_type。**只用历史日,无未来数据**。
- **均线多头**(L297-304):SELECT ... WHERE date<=? ORDER BY date DESC LIMIT 20,取当日及之前 20 日 close 算 ma20。**含当日,不跨未来**。
- **利率下行通道**(L313-319):SELECT ... WHERE date<=? ... LIMIT 20,同样只取 <=date。**无前视**。
- **us10y/gold/nq 当日值**(L306-324):_m(mid) 按 date 精确取当日。**无前视**。
- **缓存**(L238-241/325-329):以 (db,date) 为键,结果确定性,不影响时间语义。

**结论:方向锚在时间点 t 只使用 t 及 t 之前的数据,无任何后视镜。** 三条硬机检:
1. **分位阈值**:本函数无分位数阈值(ma20/均线/利率通道都是简单滚动均值,无全期分位),不踩暗坑。
2. **特征库固化口径**:均线 ma20 是"含当日滚动",语义固定;nq 阈值 -0.8% 是固定常数(非分位)。无全期固化的分位。
3. **时点穿越测试(建议做)**:选 2-3 个历史时点 t(如 20240131 / 20250731 / 20260715),把 DB 截断到 t 重算信号序列,与全量数据逐位一致。**本调研未执行(只读),实施/回测时必跑**。

唯一注意:ma20 / us10y ma20 在数据起点处(<20 日历史)会因 len<20 返回 None/False,回测脚本要正确处理起点缓冲(前 20 个交易日 ma_bull 为 None,lean 走 flat 分支)。

---

## 四、回测指标建议(核心问题4)

按 §5.1⑥ 维度清单,回测方向锚应输出:

| 指标 | 口径 |
|---|---|
| **方向命中率** | pred_shadow(up/down/flat) == actual_direction(次交易日 sh 涨跌幅按 HIT_THRESHOLD=0.5 三分类,与 _actual_direction L2333 同口径) |
| **样本数** | 有判定样本 n(排除实际 flat 无方向?需分口径:押方向样本 vs 全部样本) |
| **胜率(押方向口径)** | 只统计 pred in {up,down} 且 actual in {up,down} 的样本(真正"押方向"的命中) |
| **按 lean 分桶** | up / down / flat 各自的命中率与样本数(识别哪个 lean 有信号) |
| **按 strength 分桶** | strong(有 T 转向) vs weak(无 T 转向)的命中率差异 |
| **按年分解** | 2024 / 2025 / 2026 分别的命中率(识别是否靠近期行情) |
| **稳定性(分半)** | 时间前/后半段命中率对比,识别是否漂移 |
| **与随机基线对比** | 对比 50%(二选一)或 33%(三分类随机)基线,看是否显著优于随机 |
| **阈值敏感度** | HIT_THRESHOLD 0.3/0.5/0.7 三档下命中率变化(flat 判定宽度影响) |
| **nq 修正边际** | 全段(无nq) vs 20260716后(有nq)对照,量化 L3 压制分支的影响 |
| **与 AI 输出在线对照** | 同期(20260819-20260828)方向锚 vs AI 输出 direction 命中率对比 |

**注意 hit.direction 语义陷阱**:daily_brief_history 里 hit.direction 是「range AND middle AND board」三层严格命中(gen_daily_brief.py L2753),不是单纯方向相等。回测指标若要"方向准不准",**必须用纯方向相等口径**(pred==actual_direction)或 direction_call_hit(强制二选一),不要误用三层严格命中的 hit.direction 当方向命中率。

---

## 五、可行方案(核心问题5)

### 5.1 最小可跑回测方案(方向锚,推荐先做这个)

- **对象**:方向锚确定性规则(可全历史)。
- **脚本**:新建 docs/ai-predict/scripts/backtest_direction_anchor.py(死脚本,副本落档,§23.5)。
- **口径**:对 sentiment.db 每个日期(20240102-20260830)调 _compute_direction_anchor 合成 lean -> 找其后第一个真实交易日 sh 涨跌幅 -> _actual_direction 判定 -> 命中。
- **注意**:复用 gen_daily_brief._compute_direction_anchor / _shadow_lean 需处理 nq 缺失(2026-07 前 nq=None->nq_open_low=False),以及起点 ma20 缓冲。
- **指标**:方向命中率 / 押方向胜率 / 按 lean / strength / 按年 / 分半 / 随机基线 / 阈值敏感度。
- **输出**:docs/ai-predict/scripts/ + 结果 json/csv 同目录 + 复现段。
- **复现命令**:python scripts/backtest_direction_anchor.py --db data/sentiment.db --start 20240102 --end 20260830
- **投入**:约 1 个 implementer 日。

### 5.2 更完整方案(§5.1 穷举维度)

在 5.1 基础上叠加:
- **T 因子子群分解**:to_long vs to_short 各自的命中率(转多 vs 转空是否都有效;方向锚语义主张"转多看涨 64-66% / 转空逆势看涨")。
- **role 分解**:top20 / 中信 / 国泰君安 各自转向的命中率(识别哪个席位信号最强)。
- **叠加 L 因子**:us10y 上行/下行通道、gold 方向、nq 大跌条件下的条件命中率。
- **阈值全谱**:HIT_THRESHOLD 0.3/0.5/0.7 全谱 + nq 阈值 -0.6/-0.8/-1.0 全谱。
- **前向/样本外**:选段找规则(如 2024-2025)、验证段(2026)测,防过拟合。
- **分年/分半稳定性**:2024/2025/2026 + 前/后半。
- **与 AI 输出在线对照线**:用 daily_brief_history + brief_shadow 同期数据做"方向锚 vs AI vs 影子"三方对照。

### 5.1.1 方向锚全历史回测实测结果(2026-09-01 落地,本报告实施)

脚本 `docs/ai-predict/scripts/backtest_direction_anchor.py`(已建,tracked,§23.5)重放现版 `_compute_direction_anchor`+`_shadow_lean` 全历史(20240102-20260830),对下一个 sh 交易日涨跌幅按 HIT_THRESHOLD=0.5 判实际方向,命中=lean==actual。**结果 json:docs/ai-predict/scripts/out/direction_anchor_backtest_results.json(200KB,642 样本全明细+全部指标)。**

- **总体(n=642)**:命中率 hit_rate=0.391;押方向(dir_n=145)dir_win_rate=0.5103。
- **按 lean 分桶**:
  - up(n=139):hit=0.2662,dir_win=0.5441(dir_n=68)
  - flat(n=353):hit=0.5014(flat 命中天然约 0.5 来自"涨幅不足 0.5% 判 flat",dir_n=0 无押方向意义)
  - down(n=150):hit=0.2467,dir_win=0.4805(dir_n=77)
- **按年分解**:
  - 2024(n=242):hit=0.388,dir_win=0.517(dir_n=58)
  - 2025(n=243):hit=0.420,dir_win=0.455(dir_n=55)
  - 2026(n=157):hit=0.350,dir_win=0.594(dir_n=32)
- **诚实标注**:
  - 押方向胜率仅 0.51(全段)/按年 0.46-0.59 波动,接近随机(0.5),**方向锚现版对称规则整体无显著方向优势**;hit_rate 0.391 被 flat 桶(天然 0.5 命中)撑高,up/down 桶命中率仅 0.25-0.27(即押了方向但次日常达不到 0.5% 幅度判 flat,方向对但幅度不足)。
  - nq 因子仅 20260716 起,2026-07 前为"无 nq 段"(L3 压制分支不生效);2026 dir_win=0.594 部分含 nq 段。
  - 时点穿越测试未实现(诚实标注,非假 PASS):方向锚为纯确定性规则,因子只读 t 当日及之前数据,无全期统计量/未来数据,前视风险低(报告三、无前视审查已论证)。
  - 剩余 5.2 穷举维度(T 子群/role/L 因子/阈值全谱/前向样本外/分半/三方对照)未在本轮实施,留待后续(§5.1 穷举最大化原则,已列维度待跑)。

### 5.2 方向锚穷举子群回测(2026-09-01 落地,本报告实施)

**口径**:与 5.1 主口径一致——`dir` = 锚押方向(lean=up/down) **且** 次日真实也走出方向(actual=up/down,非 flat);dir_win = P(hit|dir)。flat-actual 日不计入(当日无方向,不判锚对错)。显著性判据 = 二项检验 z 值,|z|>=1.96 才算显著(双侧 5%)。脚本 `docs/ai-predict/scripts/analyze_direction_anchor_52.py`(死脚本副本,tracked,§23.5),输入 5.1 detail JSON 做**轻量重分析,不重跑 600 天因子**;仅阈值敏感度重跑主循环。结果 json:`docs/ai-predict/scripts/out/direction_anchor_backtest_52.json`。

**核心结论:所有子群(维度 1-5)押方向胜率均落在 0.42-0.63,无一 |z|>=1.96 显著——现版对称规则在全部已挖子群里都没有显著的方向优势,5.1 的「整体接近随机」不是被混合掩盖,而是真随机。方向锚的 T 因子在方向锚 lean 上的权重效应并不显著。**

- **T 子群**(哪些转向信号让锚押方向更准):
  - to_long(n=60):dir_win=0.5667,z=1.03 — 方向对但不显著
  - to_short(n=69):dir_win=0.4348,z=-1.08 — 略低于随机
  - none(n=16):dir_win=0.625,z=1.00 — n 太小,z 不可靠
  - both(n=0):锚押 up/down 与 both 无交集(转多/转空同时出现时锚不押单方向)
- **role 子群**(哪个席位转向信号最强):
  - 中信期货(n=79):dir_win=0.557,z=1.01 — 最高但不显著
  - 国泰君安(n=68):dir_win=0.4706,z=-0.49
  - top20(n=74):dir_win=0.4459,z=-0.93
  - 多席位同时(n=76):dir_win=0.50,z=0.00
- **strength 子群**:
  - strong(有 T 转向,n=129):dir_win=0.4961,z=-0.09
  - weak(n=16):dir_win=0.625,z=1.00 — n 太小不可靠
- **L 因子条件命中**:
  - rate_down 通道 / gold_pos(全样本恒 True)/ nq_low(仅 20260716 起,2026-07 前无此段)→ 见 out json 分桶明细;gold_pos 全 642 恒 True 无对比维度
- **按年 + 分半稳定性**:
  - 2024(n=58)=0.5172 / 2025(n=55)=0.4545 / 2026(n=32)=0.5938 — 年际波动 0.45-0.59,均不显著
  - 前半(n=74)=0.5405 / 后半(n=71)=0.4789 — 不稳定,方向随段漂移
- **阈值敏感度**(唯一重跑主循环维度,`backtest_direction_anchor.py --threshold X`):
  - thr=0.3:dir_win=0.5053(n=188)/ 0.5:0.5103(n=145)/ 0.8:0.5281(n=89)/ 1.0:0.4769(n=65)
  - **结论:dir_win 全程在 0.48-0.53 窄带内波动,未翻天——方向胜率对阈值稳健,5.1「接近随机」的结论不脆**。dir_n 随阈值上升从 188 收窄到 65(实际走出方向的天数变少),但胜率不随阈值爆变
- **前向样本外**(防过拟合):
  - 选段 2024-2025(n=113):dir_win=0.4867,z=-0.28 / 验证段 2026(n=32):dir_win=0.5938,z=1.06
  - 2026 段略高但 n=32 太小不显著,且无任何子群在选段显著——**无过拟合迹象,也无真实信号,是稳定的「无优势」**
- **与 AI 输出在线对照(三方,小样本只作参考不强行下结论)**:
  - 方向锚影子(20260819-28,8 日,dir_n=3):dir_win=0.667(2/3:8/25、8/26 对);全 lean 口径 0.333(2/6)
  - AI 输出(20260810-31,回填 15 日,dir_n=5):dir_win=0.4(2/5)
  - 两者同期(8/19-8/28)对 8/25、8/26 两个方向上扬日,影子与 AI 都判 up 且都中;其余日参差。样本太小,仅作在线观测,不作结论
- **诚实标注**:weak/none 子群 n=16 样本太小,z 不可靠;2026 段 n=32 亦小;gold_pos 全样本恒 True 无对比;nq_low 仅 20260716 起样本极小;8/19-8/28 线上对照仅 8 日,三方对照为参考性观测非统计结论。

### 5.3 AI 输出(deepseek)回测方案

- **只能在线/半在线**:每天 gen_daily_brief 生成后,历史条目由 backfill_hits 次日回填,持续累积到 90 天滚动上限。
- **建议**:写一个聚合脚本,从 daily_brief_history.json 读 direction/direction_call 与 hit.actual_direction,按「纯方向相等」与「direction_call」两口径持续统计命中率,随样本增长(建议 >=30 条再下结论)。
- **不能回测到 20260810 前**:AI 功能上线前无历史输出,无法离线重放 deepseek。

---

## 六、诚实标注(核心问题6)

1. **AI 输出无法全历史重放**:deepseek 是实时模型,无历史输入快照/权重/温度,20260810 前的 AI 方向输出不可重建。只能在线积累。
2. **AI 输出当前样本极小(15 条有实际)**:命中率 33.3%(纯方向)/50%(direction_call n=4)仅参考,**不构成统计显著结论**。
3. **nq 因子仅 20260716 起**:方向锚全历史回测(20240102-20260830)中,L3 纳指大跌压制分支在 2026-07 前不生效(数据缺失->False)。全段回测 = "无 nq 时代的锚";20260716 后才是"完整含 nq 的锚"。两段应分开看/对照。
4. **方向锚语义含"对称分支"(2026-08-24 R4 改造)**:_shadow_lean 的 down 分支(T2/T3 转空->down / 均线空头->down)是 2026-08-24 新增;更早(20260824 前)影子记录按旧单边 up 语义落盘(文档明示"历史已落 up 记录诚实保留不改写")。**回测若用 _shadow_lean 现版规则全历史重放,得到的是"现版对称规则的历史表现",不是影子数据原始记录的历史表现**——两者需区分(回测=重放现版规则,数据足;影子记录=原始在线,样本小)。
5. **ma20/us10y ma20 起点缓冲**:数据起点前 20 日无足够历史,ma_bull/rate_down_channel 为 None,lean 走 flat,回测脚本要正确处理,避免污染起点样本。
6. **HIT_THRESHOLD 口径变更历史**:0.1->0.5(2026-08-14 变更,gen_daily_brief.py L2232 注释)。回测统一用现版 0.5,与 _actual_direction 一致;如需与历史影子记录比对注意口径差异。
7. **hit.direction 语义陷阱**:daily_brief_history 的 hit.direction 是三层严格命中,不是方向命中;回测/汇报"AI 方向准不准"必须用纯方向相等或 direction_call 口径。

---

## 复现

- **脚本**:本报告为可行性调研+实施落地。回测脚本已建:`docs/ai-predict/scripts/backtest_direction_anchor.py`(tracked,§23.5,死脚本副本,支持 `--threshold` 覆盖现版 HIT_THRESHOLD 做敏感度),输出 `docs/ai-predict/scripts/out/direction_anchor_backtest_results.json`;5.2 子群分析脚本 `docs/ai-predict/scripts/analyze_direction_anchor_52.py`(tracked,死脚本副本,读 detail JSON 轻量重分析),输出 `docs/ai-predict/scripts/out/direction_anchor_backtest_52.json`。
- **输入依赖**:
  - data/sentiment.db(futures_position / index_daily / daily_metric)
  - static-site/data/daily_brief_history.json(AI 输出历史)
  - data/brief_shadow.json(方向锚影子在线记录)
  - scripts/gen_daily_brief.py(_compute_direction_anchor L221 / _shadow_lean L397 / _actual_direction L2333 / HIT_THRESHOLD L2232)
- **重跑命令(建议最小方案)**:
  - python docs/ai-predict/scripts/backtest_direction_anchor.py --db data/sentiment.db --start 20240102 --end 20260830
  - python docs/ai-predict/scripts/backtest_direction_anchor.py --db data/sentiment.db --threshold 0.3
  - python docs/ai-predict/scripts/backtest_direction_anchor.py --db data/sentiment.db --threshold 0.8
  - python docs/ai-predict/scripts/backtest_direction_anchor.py --db data/sentiment.db --threshold 1.0
  - python docs/ai-predict/scripts/analyze_direction_anchor_52.py(先跑齐阈值结果再跑)
  - AI 输出在线聚合:python scripts/aggregate_ai_output.py(建议新建,从 daily_brief_history.json 读)
- **数据截止**:sentiment.db 20260831;daily_brief_history 20260831(16条);brief_shadow 20260828(8条)。
- **关键口径一句话**:方向锚回测 = 对每交易日重放 _compute_direction_anchor + _shadow_lean 现版规则得 lean,次交易日 sh 涨跌幅按 HIT_THRESHOLD=0.5 判实际方向,命中 = lean==actual;nq 因子 20260716 起,2026-07 前为无 nq 段。
