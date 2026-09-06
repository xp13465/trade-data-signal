# 信号凯利回测「近1年按需先算先展示 + 后台全量覆盖」可行性评估(2026-09-04)

> 结论:**技术可行,准确无损**(硬约束"不能为快舍弃准确度与真实性"通过)。核心依据=各周期统计是**窗口内独立口径**而非全史累计曲线切片;y1 窗口基笔 100% 只落在 t2025+t2026 两片,两片与全量在 y1 窗口的每日 top-K kept 集合 K=1/2/3/4 四档逐位一致。拦点在「渐进覆盖的数字跳变」,用就绪状态机(未就绪周期只显示占位,不显示残缺数)可完整规避。

---

## ① 各周期统计口径判定:**窗口内独立口径(非全史累计切片)**

- 周期筛选=在「toggle/positionCap 过滤后的全量 trades」里按 `buy_date >= cutoff` 取子集,再对子集独立聚合。
  - 证据:`lab.js L8596-8600` `trades = toggled.filter(t => t[fIdx.buy_date] >= cutoff)`,cutoff 来自 `data.config.period_cutoffs`(L8431)。
  - `period_cutoffs` 是生成时固化的日期串(非运行时窗口):`t2026.json` 内 `{"y1":"20250905","y3":"20230906","y5":"20210906","y10":"20160907","all":"0"}`。
- 所有统计子函数是纯函数,只基于传入 trades 数组:**`_kellyComputeStats`(L7172)、`_kellyMaxConcurrent`(L7093)、`_kellyMaxConcurrentCapital`(L7727)、`_kellyMaxDrawdown`(L7137)全无全史累计曲线依赖**。
- 年化:`y1/y3/y5/y10` 用**固定年数开方**(L7162-7165),仅 `all` 用 `_kellyYearsFromTrades`(trades 自身 buy_date 跨度,L7166)。窗口内独立。
- 无"峰值资金/回撤依赖全史"的隐性耦合——峰值/回撤也是窗口内 trades 的重叠/累计计算。

**结论:各周期=窗口内成交记录独立聚合。近1年只统计近1年成交,天然适合按需加载。**

## ② 按需近1年是否准确无损:**可行,且已数据实证**

- **y1 窗口基笔 100% 只落在 t2025+t2026 两片**:全量 16 片扫描,buy_date>=20250905 的记录只有 2025 片(16360行/409基笔)+2026 片(56720行/1418基笔),其余 14 片 0 行。y1 总基笔 1827 = 两片相加(409+1418),完全闭合。
- **两片 vs 全量的 positionCap(每日池 top-K)kept 集合逐位一致**:node 复刻 `_kellyPositionCapKeptKeys` 排序逻辑,K=1/2/3/4 在 y1 窗口的 kept 分别为 196/366/509/637 条,**两片与全量完全相同**。
- 各跨窗口依赖点的处理(均不失真):
  - **跨窗口持仓**:y1 口径=买侧窗口(`buy_date>=cutoff`),窗口起点前买入的持仓完全排除(全量 9464 条 buy<20250905 且 sell>=20250905 的持仓对 y1 不可见)。**渐进两片与全量算 y1 行为一致**(都排除),非渐进引入的失真。
  - **每日池等分 top-K**:按 signal_date 当日分组独立排序(L7646-7682),不依赖前日持仓;y1 窗口的每日候选都在两片内,金额(10000/当日保留数)正确。
  - **S06 per-date 过滤**:`_s6F6(t)` 按每笔 signal_date 查 `kelly_mode_s06_state.json`(4030 天 daily,独立查表非状态链,L8483-8495)。该文件整体加载(607KB),近1年窗口只取窗口段,判定与全量逐笔一致。
  - **v3/v4/v4/降亏特征**:单笔纯判定(`_kellyPassesFadeFilters` L7523,特征缓存键=单笔),`_tradeDims` 由窗口内 quadrants 构建(L8452-8455),单笔维度固定不变,窗口内命中一致。
  - **GIH 真实净值 / 降亏特征 JSON**:独立文件加载,与分片无关。
- **真实上限(用户问"2 年够不够")**:分片严格按年切(每片内 signal_date==buy_date 范围一致),年边界无跨足;最长持仓 880 天(2023-01 G 模式长线持有未卖),但 buy_date<20250905 的长线持仓对 y1 不可见(买侧窗口口径),不影响 y1。**近1年准确只需 2025+2026 两片,已实证。**

## ③ 最小落地方案(若做)

- **前端两阶段加载(lab.js)**:
  1. 拆 `_labKellyLoadYearParts`(L8324)为两阶段:先 `Promise.all(["2025","2026"])` 拉两片 → 合并 → 置 `_labKellyY1Ready=true` → 触发 y1 渲染;后台再并行拉其余 14 片 → 全量合并 → 置 `_labKellyAllReady=true` → 全量重算覆盖。
  2. `_kellyApplyFeeRecompute`(L8406)数据源分级:y1 且仅 `_labKellyY1Ready` → 用两片 td 算(只算 y1 周期,其余周期 result 标记未就绪);全量就绪 → 用 16 片 td 算全部分期。
  3. 就绪状态机:周期→所需片数映射 `{y1:2片, y3:4片, y5:6片, y10:11片, all:16片}`(数据实证各周期基笔分片分布);切到未就绪周期 → 沿用现有「⏳ 计算中…」占位(`_labKellyProgressTickUI` L8388),片到位自动重算刷新。**未就绪周期只显示占位,不显示残缺数。**
  4. **K 档评级必须门控**:`_AI_POSCAP_RATING_DYNAMIC` 计算块(L8712-8787)用 **all 周期全史**口径(`_kellyComputeStats(_recomp, "all", ...)` L8762)。阶段1 两片算 all=残缺,必须**阶段1 不发布动态源**(保持 null→首页/凯利区回退静态快照并标注),全量就绪后再写入。否则用户会看到 K 档评级数字跳变。
  5. **缓存签名必须加"分片完整度"**:`_kellyStatsCacheKey`(L8466)不含数据源版本,阶段1 两片 result 若不区分会被阶段2 误命中缓存。必须加 `partsReady` 标记。
- **与 impl-54 方案B 的关系**:首页 K 档与 lab 凯利区**同一数据源**(common.js `_aiPoscapRatingSrc` L495 = 动态 `_AI_POSCAP_RATING_DYNAMIC` 优先 / 静态快照回退,首页 app.js 与 lab.js 共用 `_aiPoscapRatingPopHtml`)。本方案的"K 档评级门控"直接影响首页 K 按钮——**阶段1 首页 K 档必须显示静态快照+「全量计算中」标注**,全量就绪后自动切动态。两者天然联动,不冲突。
- **可选后端增强**:前端两片首屏下载约 30MB(t2025=16.4MB + t2026=13.5MB),省 57%(全量 69MB)。若要更小首屏,后端生成 `recent-1y.json`(近1年窗口片,预估~17MB),首屏只拉一个文件。但注意 recent.json(60 天热区,2.6MB)是模拟回测弹窗专用,不是近1年。

## ④ 数字跳变边界(用户在意 impl-54 的跳变 bug)

- **y1 卡片/收益数字:渐进覆盖逐位不变**(两片 vs 全量,过滤+每日池+统计全窗口内独立,kept 集合已实证逐位一致)。这就是"渐进加载"与"impl-54 跳变 bug"的本质区别:impl-54 是同一周期内数字随数据源切换变化,本方案 y1 承诺稳定。
- **非 y1 周期:未就绪只显示占位,全量就绪才首次出现完整数字**(不是"先看残缺数后变全量数")。
- **K 档评级:阶段1 门控(静态快照标注),全量后首次切动态**。
- **按年聚合表(allYearly)**:阶段1 只有 2025/2026 两行,全量后补齐 2011-2024 行(表按年分块,补行非改值),可加「全量加载中」轻标注。

## ⑤ 工作量与风险

- **量级:中改**(前端 lab.js 一处加载模块拆分 + 计算入口数据源分级 + 渲染层就绪门控 + K 档评级门控 + 缓存签名修正),无后端改动即可落地。
- **风险清单**:
  1. **缓存污染(最高风险)**:两片 result 进 `_kellyStatsCacheKey` 缓存,全量后误命中 → 必须加 partsReady 签名。
  2. **_tradeDims / 特征缓存重建**:两片 td 构建的维度表/特征缓存,全量后必须重建(`_kellyClearComputeCaches` 已有)。
  3. **K 档评级残缺发布**:阶段1 忘记门控 → 首页 K 档显示近2年伪全史 → 全量后跳变。
  4. **就绪判定边界**:y3/y5/y10 需要多片,切周期时片未到齐 → 占位逻辑要兜住"切周期时后台正在加载"的重入。
  5. **与 impl-54b worktree 并发**:方案B 首页 K 档动态源正在 worktree 改 lab.js/app.js/common.js,本方案若实施须等其 merge 后在同一基线上改(避免双改同一文件冲突)。

---

## 复现段
- 本文全部数据实证命令为一次性 node 内联脚本(只读 data/),未落盘为脚本文件。
- 输入依赖:`static-site/data/signal_kelly_trades_parts/t{YYYY}.json`(16 片)+ `kelly_mode_s06_state.json`。
- 关键结论可复验命令:
  1. y1 窗口片分布:`node -e '...扫16片统计 buy_date>=20250905 记录'`(结果:t2025=16360行/409基笔, t2026=56720行/1418基笔, 其余0)。
  2. kept 集合对账:复刻 `_kellyPositionCapKeptKeys` 排序(track_score DESC→rating→signal→buy_date ASC),比较两片合并 vs 全量在 y1 窗口 kept(K=1/2/3/4=196/366/509/637,逐位一致)。
- 数据截止:2026-09-04 收盘数据(分片 generated_at=2026-09-05 05:10,period_cutoffs y1=20250905)。
- 关键口径一句话:y1=窗口内(buy_date>=20250905)独立聚合;每日池=10000/当日保留前K数;统计=窗口内 trades 纯函数聚合,无全史累计依赖。

---

## ⑥ 补充:用户拍板「近1年2片轻量 + 快照承载全史 + 后台全量替换」快照化评估(2026-09-04 主控转达)

### 已实测事实(修正主控转达的前提)
- **F1:latest_posrating.json 快照先例已存在** `static-site/data/signal_kelly_snapshots/latest_posrating.json`(2026-09-05 13:23):`{computed:true, mode:"s06", values:{1..4:{name,ret,dd,ra,n,retNum,ddNum,nNum}}}`,K1=163.47%/dd3.89%/n542,每日池口径。生成者=**并行 worktree agent-a25288cbf(impl-54 方案B)的 `scripts/kelly_posrating.py`**(复刻 lab `_kellyApplyFeeRecompute` K 档段 + `check_posrating_parity.mjs` 对账机检,头注释声明「与 lab 同构对账过 §5.4⑦」)。
- **F2:主数据 signal_kelly_backtest.json 的 quadrants cells 已含全峰值资金字段**:`max_concurrent/max_concurrent_capital/return_pct_max_holding/max_drawdown/max_drawdown_pct/calmar/holding_count/holding_capital`(实测 rating_high y1:A 模式 n=28/max_conc=15/concCap=150000/ret_pct_max_holding=4.6596)。后端 `scripts/signal_kelly_backtest.py` L827 `_max_concurrent`/L862 `_max_drawdown`/L998-1049 已计算。**主控转达"计算层不成立"的判断需修正:字段缺在「快照摘取层(KEY_METRICS 6 字段)」,不在计算层**。
- **F3:口径红线(§22 核心拦点)**:backtest.json 峰值资金是 **fixed 每笔固定 10000 口径**(`total_invest=n×10000` L994、`max_concurrent_capital=max_conc×10000` L999),而 lab 动态是 **每日池等分+top-K 口径**(前端 `_kellyPerTradeAmount` L7721 摊薄)。两者 `max_concurrent_capital`/`return_pct_max_holding` 数值不同 → **快照扩展峰值资金不能直接摘 backtest.json,必须按每日池口径重算**,否则与 lab 动态不一致 = §22 违反 = 替换跳变。

### ① 快照字段扩展(加峰值资金系)可行性/工作量
- **可行,计算层已具备,工作量中改**。三选一路径:
  - 路径 A(最稳):泛化 worktree `kelly_posrating.py` 的 `compute_posrating` 内核(已实现每日池口径 S06 per-date 过滤 + 每日池 top-K + 峰值资金统计),从「仅 K 档评级(A 模式 all 伪象限)」扩到「全 16 象限 × 5 周期 × 10 模式」,每日快照链输出 `signal_kelly_snapshots/YYYYMMDD.json` 峰值资金字段。改动面:posrating 内核泛化 + snapshot.py `write_posrating_file` 扩展 + `KEY_METRICS` 加字段 + parity 机检覆盖。**与现有 worktree 直接咬合,复用其对账基础设施**。
  - 路径 B(快但口径错):snapshot.py `KEY_METRICS` 从 6 字段扩到 ~13 字段直接摘 backtest.json。改动 3 行但**口径是 fixed,与 lab 动态每日池不一致 → 不可取**(除非同时把 backtest.py 生成口径改每日池,但那是动核心静态产物,§23.7 冻结风险大)。
  - 路径 C(最小演示):仅扩展 latest_posrating.json 模式(已含 ret/dd),全象限峰值资金延后。不适应用户"各方法峰值资金"期望。
  - **推荐路径 A**。注意:快照=每日一次静态生成,只能承载**默认配置(S06 动态基座 + 默认费率 etf_main)** 下的全史数字;用户切 toggle/费率后快照数字不适用,必须前端实时计算修正(见 ②)。

### ② 字段缺口是否阻塞
- **分场景**:
  - 「近1年 2 片轻量 + 后台全量分片 + 前端实时全史」流程:**峰值资金字段缺口不阻塞**——前端 lab.js 已具备全部分期峰值资金实时计算能力(y1 两片准确性已实证),无需静态快照扩展即可落地。
  - 「静态快照直接承载全史卡片(首屏读快照)」流程:**部分阻塞**——K 档评级已有(latest_posrating.json),但全象限×模式×周期峰值资金字段缺(需路径 A 扩展);且静态快照只覆盖默认配置,无法反映用户实时 toggle/费率。
  - **核心判断**:快照的准确定位=「默认配置全史底图 + 演进曲线 + K 档评级首屏源」;**不是**「替代前端实时计算的完整数据源」。渐进加载的目标态必须是前端全量分片实时计算(随 toggle/费率/S06 实时),静态快照只做首屏/兜底/演进。

### ③ 替换快照的时机/一致性边界(§22)
- **替换场景 A(首屏 y1 两片 → 全量实时)**:y1 卡片数字逐位不变(kept 集合 K=1/2/3/4=196/366/509/637 两片 vs 全量逐位一致,实证)。替换时机=全量 14 片加载完触发重算覆盖。非 y1 周期在首屏阶段门控为占位(未就绪不显示残缺数),全量后首次出现。**不跳变**。
- **替换场景 B(静态快照 → 实时计算)**:kelly_posrating.py 已声明与 lab 同构对账(worktree `check_posrating_parity.mjs`),这是方案B的一致性保障。替换时机=快照生成(每日 export)后,首页 K 档注入;一致性=parity 机检逐位 PASS 才允许替换,漂移 FAIL 阻断(§5.4⑦ 同精神)。
- **不一致风险点(替换前必须机检)**:①口径 fixed vs 每日池(backtest.json 峰值资金不可直接用于每日池展示)②S06 per-date 判定(快照用快照基座,前端实时用当前 S06 状态;覆盖期外兜底语义要同源)③费率档(快照=默认 etf_main,前端用户可能切自定义 → 切了费率必须脱离快照走实时)④降亏 toggle(快照=默认键集,用户改勾选必须脱离快照走实时)。
- **落地铁律**:任何「快照数字 → 页面展示」的替换,先跑对账机检(输出 vs 页面实时渲染逐位一致),PASS 才替换;不一致=停,查根因(§5.4⑦ repro 假数字事故同源教训)。
