# signal_kelly 滚动窗口重算方案调研(2026-09-23)

> 任务:治「每次全量重算全历史 → 耗时随历史线性增长」的隐患(背景 docs/ops/task-slow-rootcause-20260923.md §6/§9D)。
> 结论先行:**该问题前提不成立——实测全量重算仅 ~19s/次(NDO),增长也远未触顶;滚动窗口收益 <15%/晚,风险成本巨大,建议不做全量滚动,只做两个廉价小项**。全文给出字段依赖清单/滚动边界/防前视设计,供若前提变化(如日多跑几轮/口径变更频率上升)时直接落地。
> 方法:云上只读实测(compute 各段分阶段计时 + NDO/SDC 端到端计时,输出全部指 /tmp,冻结表 no-op/指 /tmp 副本,零生产写入)+ 本地 DB 只读查询 + 代码研读。证据点全部可复核。

## 0. 结论摘要(一句话版)

1. **现状全量重算不慢**:云上端到端实测 NDO(次日开盘主档)= **19s**,SDC(当日收盘对比档,KELLY_BUY_NEXTDAY=0)= **21s**,合计 ~40s。背景文档的 157s(9-22)是**估算**(原文 §11 自认"日志无逐行时间戳,估算"),且 9-22 是 fund-nav 上传风暴(6225s)重负载日,大概率是被并发 I/O 挤出来的瞬态值,不是"随历史增长"的稳态值。
2. **增长有界且远未触顶**:compute 里唯一随历史线性的是分类回测循环(云上实测 **2.8s**);价格加载 0.6s、输入加载 0.6s、聚合 ~5s、序列化+gzip+分片 ~7s。按现在增速外推 10 年,总时长 ~40s→~70-90s,远低于 export.py 超时(NDO 180s / SDC 300s)。**不是近期隐患**。
3. **滚动窗口收益极小**:即使做对,每晚省 ~4s(19s→~15s,减 20%),搁整条 export.py 段(~15-20min)和 update_all 链里 = 零头;与已定 P1 fund-nav 异步解耦(25-100min)完全不在一个量级。
4. **滚动窗口风险成本大**:历史成交一旦冻结,①signal_daily 信号类型漂移(9/18 实证买→buy_aux)不再自愈 ②数据源回修历史 accum_nav/open/close 时冻结价陈旧 ③任何口径/算法/键集变更(本项目高频:v1.1.x 系列、K 档 11→9 天 9-22 刚改)必须显式触发全量重建,漏触发=页面陈旧数静默上线。而现状全量重算天然自愈这一切——这是被低估的核心价值。
5. **推荐**:不做滚动窗口。两个廉价可选小项(需用户拍板):a) SDC 对比档降频(省 21s/晚);b) NDO 超时 180s 暂不动(余量 ~9 倍)。真正治慢 = P1 fund-nav 异步解耦 + 已 merge 的 keep_alive。

## 1. 现状:每次全量重算哪些字段/数据(依赖分类清单)

### 1.1 每次运行读取的输入(全量)
| 输入 | 来源 | 量级/耗时(云上实测) | 性质 |
|---|---|---|---|
| signal_stats.json | static-site/data/ | 小,<0.1s | 全史(10d score,分类评级用) |
| board_etf_map.json | data/ 根 | 小 | 全史,仅影响新信号事件(历史已走冻结表) |
| signal_kelly_etf_freeze.json | data/ 根 **已固化的运行时持久化快照** | 5.8MB | 每信号事件 ETF 选择,已在用"冻结"模型(§1.4) |
| indicators.yaml | config/ | 小,静态 | 指数大类映射 |
| signal_daily 买信号 | sentiment.db | 42,043 行,0.1s | 全史(SELECT 无日期过滤,1991-2026) |
| signal_daily 卖信号 | sentiment.db | 21,667 行 | 全史(G/H/I 卖出时间线) |
| index_daily hs300/cyb MA60+四档 | sentiment.db | 0.5s | 全史(大盘择时,按日查 t 当日态) |
| **etf_daily 价格** | etf_national_team.db | **129,914 行/131 ETF,0.6s**(库总 147 万行) | 每需要 ETF 的**全上市史** accum_nav/open/close |

### 1.2 每笔交易逐字段依赖分类(L180 TRADE_FIELDS,27 列)
**局部可算类(只看 [t-1, t+持有期] 窗口就够;卖出后再不变化)**
- 价格/成交字段:buy_price(信号日 accum_nav × 次日开/当日收,gap 换算)、sell_price(卖出日 accum_nav)、shares、profit、return_pct、hold_days、sell_reason、current_price、real_buy_price、real_buy_date、real_current_price —— 依赖仅 [signal_date±1, 卖出日] 的价格行 + 费率常量
- 分类字段:track_tier/track_score/match_method/track_low_confidence(冻结表/board map 在 t 的值)、rating(signal_stats 10d score at t)、market_state/market_tier/market_tier_all/market_tier_cyb(大盘态在 t 的值) —— 全部只是"t 当日的历史判定值",定值后不变

**全局聚合类(依赖该组全部交易,峰值/序列/回撤性质)**
- `_compute_stats`(L1328)全字段:n/win_rate/pl_ratio/mean_return/total_return/kelly_f/连胜连败/总投入/总盈亏/total_return_pct/**max_concurrent(L1224,全期持仓叠加最大并发)**/max_concurrent_capital/**return_pct_max_holding(锚点口径字段)**/annualized/sharpe/**max_drawdown(L1259,全序列累积曲线)**/calmar/holding_count
- 组合维度=16 象限 × 11 模式 × 5 周期(880 组,每组独立聚合)

### 1.3 每次运行写出(全量)
| 产物 | 大小 | 消费方 |
|---|---|---|
| signal_kelly_backtest.json | 0.56MB | lab.js 16 卡视图、signal_kelly_snapshot.py、overfit_monitor |
| signal_kelly_trades.json | 74-86MB(R2) | **前端全信号表实时重算(lab.js,锚点口径源头)**、app.js 模拟弹窗、overfit_monitor、posrating、plan_generator、check_* 对齐机检 |
| signal_kelly_trades_parts/(16 年片+recent) | ~45MB | app.js 弹窗渐进加载 |
| *.gz | 14MB trades/80KB stats | 传输优化 |
| signal_kelly_backtest_sdc.json / trades_sdc | 同规格 | lab #91 对比档 |
| freeze 文件增量 | 小 | 下一轮回测输入(唯一跨轮持久化状态) |

### 1.4 关键洞察:项目已有"冻结"先例
**ETF 冻结表(signal_kelly_etf_freeze.json)** 已经是"历史成交固化、board_etf_map 变更只影响新信号"的滚动语义 —— 换标漂移修复(L581 注释)就是"历史成交不应随当前映射变更而被重算"的既有设计。滚动窗口是同一哲学的延伸,但**只冻结 ETF 选择,不冻结成交价/盈亏/象限归属**,这是和历史冻结最本质的差别,也是最大风险源(见 §6)。

## 2. 三个难点的定性

### 难点①峰值占用资金(全局量)
- `_max_concurrent`(L1224)按 (qk, mode, period) 组对全组交易做扫描线求最大并发;`return_pct_max_holding` 等锚点口径字段依赖它。
- **解:聚合层不做滚动,每晚从「合并后的完整交易列表」重新聚合**。max_concurrent 是 O(N) 扫描,880 组聚合在云上 ~5s 且不随历史长度变快变慢(只随交易笔数)。滚动只作用于"单笔生成"层,聚合永远全量 → 峰值/回撤/序列类全局量零失真,不存在"滚动窗口下峰值低估"的问题。
- 若将来真要做"聚合也滚动":max 具有结合律,global_peak = max(冻结历史峰值, 窗口内峰值),但窗口内曲线必须包含"卖出日在窗口内或未卖出的全部交易"(开仓集要跨轮携带),且 G/H/I 长持交易卖出瞬间窗口曲线会**下降**(非单调),每周期(y1/y3/all)峰值要分开记账 —— 极易错,不推荐(设计上直接排除,Approach A 为本方案推荐)。

### 难点②accum_nav 复权(自上市累计)
- accum_nav 的"累计"性质只体现在**数值本身在 DB 行里**;取出 t 日的行即得 t 日复权值,与加载范围无关。窗口内交易的买卖价只需 [t-1, 卖出日] 的行 → **价格加载可以按窗口截断**(现 129k 行→窗口 ~9k 行)。
- 例外:未卖出的持仓中交易(G/H/I 长持),当前价/止盈检查需要其 buy_date→今天的完整价格段 → 对该 ETF 走"尾部查询"(date >= buy_date),行数 = 未卖出交易 ETF 数 × 持有天数,量级小。
- **风险:数据源回修历史 accum_nav/open/close** → 冻结的卖出价/买入价与"今天全量重算"不一致。现状全量重算自动吸收回修;滚动后需漂移检测兜底(§5)。

### 难点③每日资金池 K=1 排序
- **它是前端概念,不在本脚本里**。lab.js L9101-9103:_kellyCollectBasePool → _kellyPositionCapKeptKeys(top-K)→ _kellyKeptDayCounts(按日计数),每笔金额=10000/当日保留数(K=1 即每天 1 笔 1 万);锚点 A=161.63%/峰值资金 10 万 即此前端重算结果(后端 trades 文件实测单日最多 71 笔,L 无任何每日筛选)。
- 对滚动的影响:**零**。前端从完整 trades 文件按日局部排序,后端只要保证 trades 文件完整+单笔正确,每日池/峰值全部由前端照常算对。若将来 K=1 选择下沉到后端,它也是"按天分组局部排序",天然可局部算 —— 与难点③任务描述一致。

## 3. 滚动边界设计(若实施)

### 3.1 分层:单笔生成滚动,聚合全量
| 层 | 每盘后动作 | 量级(云上) |
|---|---|---|
| 输入加载 | buy_rows WHERE date >= 窗口起;sell_rows 下限=min(窗口起, 未卖出笔最早 buy_date);大盘态/统计表/tiers 全量(0.5s 不变) | ~0.2s |
| 价格加载 | 只 Load 窗口交易+未卖出交易涉及 ETF,date >= 窗口起(-1) | ~0.1s(现 0.6s) |
| **单笔生成(滚动)** | 只重算窗口内交易 + 全部未卖出(持仓中)交易;其余读上一轮 trades 文件原样保留 | ~0.3s(现 2.8s) |
| **聚合(全量)** | 从合并后完整交易列表重算 880 组 stats(含 max_concurrent/return_pct_max_holding/max_drawdown) | ~5s(不变) |
| 写出(全量) | 完整 trades 文件 dump+gzip+分片+freeze 增量 | ~7s(不变) |

### 3.2 窗口边界定义(具体数字)
- **窗口 W = 最大固定持有交易日(J=20)+ 缓冲 5 交易日 = 25 交易日**,理由:固定持有模式(A/B/C/D/E/F/K/J)交易自 buy_date 起最多 hold_days 个交易日内必卖出,卖出后单笔字段永不再变;早于 25 交易日的固定持有交易必已了结 → 只读冻结。
- **例外集(必须每夜重算)**:a) signal_date 在窗口内的全部交易;b) **sell_date="" 的全部持仓中交易**(无年头,G/H/I 长持;实测未卖出唯一基笔 **1041 个**(跨 G/H/I 去重:模式组合 G=420/G+I=480/G+H+I=141,四象限行数 7212)——这些交易当前价每夜变、且可能因新卖出信号转卖出。
- 每夜重算笔数 ≈ 窗口新信号(~250 笔,近90天买信号643条≈7条/交易日×25交易日)+ 未卖出(1041 基笔)≈ **~1300 基笔**,vs 现全量 42k 行扫描。

### 3.3 固化物与读写方
| 固化物 | 内容 | 谁写 | 谁读 |
|---|---|---|---|
| signal_kelly_trades.json(本体即固化桶) | 全史完整交易列表(旧交易冻结 + 新窗口重算后合并,唯一输出) | signal_kelly_backtest.py --rolling(新增模式) | lab.js/app.js(前端)、overfit_monitor、snapshot、posrating、plan_generator、check_* |
| signal_kelly_runtime_meta.json(新增 sidecar) | 窗口边界 cutoff、pre-cutoff 交易哈希(L1855 `_main_pre_date_hash` 同构)、口径版本戳(config/SELL_MODES/费率/键集 hash)、上次全量重建日 | 同 --rolling | 下一轮 --rolling(漂移检测);check_data_integrity 可挂机检 |
| signal_kelly_etf_freeze.json | 每信号事件 ETF 选择(已有,不新增) | 同现逻辑 | --rolling 同现逻辑 |
| 全量重算 oracle | 完整 compute()(零改动,保留) | 周期全量(建议每月/口径变更时)+ 漂移触发 | --rolling 的对照基准 |

- 依赖铁律:rolling 与全量共用 `_classify_buy_rows`/`_build_outputs`/`_backtest_one` 单一实现(L1803/1834 注释既有原则 §5.4⑦),rolling 只是"输入范围截断+输出合并",不新写第二份算法。
- 全量重算保留为 reconciliation oracle:每月或漂移检测触发时跑一次,结果逐位覆盖合并,重置滚动基线。

## 4. 防前视对账机检设计(§5.1⑥ 硬约束)

滚动本身不引入前视(窗口交易的计算输入与全量同构,判定只取 ≤t 态、未来段仅作"买入后模拟",与现状一致)。对账机检要守的是:**冻结段必须与"今天全量重算出来的同段"逐位一致**。

1. **时点穿越测试(上线前必跑,2-3 个历史时点)**:
   - 取 t0(如 60/120/250 交易日前的历史时点),把全部输入截断到 t0(buy_rows≤t0/sell_rows≤t0/价格≤t0/today=t0,复用 compute_intraday L1950 同款截断模式)。
   - 全量跑出 t0 前交易集 F0;再用滚动模式(窗口=W)跑出冻结+窗口合并集 R0;断言 R0 中 signal_date≤t0 部分与 F0 **逐位一致**(qk/mk 归属 + 27 列全部字段),不一致=FAIL 不出方案。
   - 代码进 scripts 同目录可复跑(如 scripts/signal_kelly_rolling_time_travel_test.py),对齐 researcher §3.1⑥ 时点穿越测试范式。
2. **逐夜漂移哈希(滚动上线后的日常闸)**:复用 `_main_pre_date_hash`(L1855,盘中档对账已在用,零新造):rolling 跑时记录 pre-cutoff 哈希,A) 与 sidecar 里上一夜哈希比对(冻结段被改动即 FAIL→告警+触发全量重建);B) 每次全量 oracle 跑时对账 rolling 合并结果逐位(或哈希)一致。
3. **口径版本戳**:sidecar 记录 config/SELL_MODES(含 K 档=hold 9 天)/费率/键集/TRADE_FIELDS 的指纹,下一轮不一致 → 滚动失效,自动降级全量(防"K 11→9 改了但忘了全量重建"这类静默陈旧)。
4. **页面锚点对账(§3.2 铁律)**:每月全量 oracle 后,取页面 Playwright 无痕实测锚点 all A=161.63%/K=162.12% 对账,漂移即停。

## 5. 收益评估(数据说话)

### 5.1 现状耗时(云上直接实测,2026-09-23,非估算)
- NDO 端到端(含启动/就绪闸/计算/写出/分片/gzip): **19s**
- SDC 端到端: **21s**
- compute() 分阶段: 输入加载 0.6s + 价格加载 0.6s + 分类回测循环 2.8s + 聚合 ~5s = ~9.7s;dumps 2.0s + atomic write 0.2s + gzip 2.0s + 分片 3.1s
- 对照:背景文档 157s(9-22)为估算(§11 自认),且当日 fund-nav 上传风暴(6225s)并发挤压,现直接实测为其 1/8。

### 5.2 滚动后预期
- compute 9.7s → ~6.5s(省分类循环 ~2.5s + 价格加载 ~0.5s);写出/聚合/输入加载基本不变 → 每晚 NDO 省 ~3-4s,SDC 同,合计省 ~8s/晚。
- **占更新链(<15%)、占 export.py 段(~15-20min)不到 1%**。

### 5.3 增长外推(10 年)
| 项 | 现状 | 10 年后(按当前增速) | 触顶对比 |
|---|---|---|---|
| 分类循环 2.8s | 线性随信号量 | ~5s | 超时余量 ~9 倍 |
| etf_daily 加载 0.6s(年+17%) | 线性随库行数 | ~2s | 同上 |
| trades 文件 74MB 写入/压缩/分片 ~7s | 随基笔数(+~7%/年) | ~12s | 同上 |
| 合计 | ~40s(NDO+SDC) | ~70-90s | NDO 180s / SDC 300s 超时安全 |

### 5.4 结论:该做/不该做
- **不推荐做全量滚动窗口**:收益 ~8s/晚 = P1(A/B)收益(25-100min)的 0.1%,风险却动基准口径全链路(触碰 v1.1.7 锚点高风险区,按 §5.4⑥ 动核心默认组合必须发版本+全站 18 处登记点同步)。**优先级:不做**。
- 两个廉价小项(可选,需用户拍板):a) SDC 对比档(21s/晚)若非常态查看,改"有 #91 对比需求时才跑"或降频;b) NDO 超时 180s 余量充足暂不动,10 年后再议。
- 真正治"慢":P1 fund-nav 异步解耦(6225s 条目不再计入主链)+ keep_alive(已 merge,9-23 晚首效)。

## 6. 风险清单(滚动后语义变化,必须用户拍板才能动)

| # | 风险 | 现状(全量) | 滚动后 | 缓解 |
|---|---|---|---|---|
| 1 | **signal_daily 信号类型漂移**(9/18 实证 buy→buy_aux;冻结表兜底 L236-278 即为此设) | 每晚全量自愈,象限归属跟着变 | 冻结段不重算,漂移只影响窗口 → 历史象限归属冻结在"冻结时点" | 漂移哈希 FAIL→全量重建;或冻结语义正式化(用户认可"信号类型也冻结") |
| 2 | **数据源回修历史 accum_nav/open/close** | 每晚全量自愈,买卖价跟着修订 | 冻结段成交价/盈亏陈旧,直到下次全量 | 漂移检测+月度全量 oracle |
| 3 | **口径/算法/键集变更**(v1.1.x 系列高频;K 档 11→9 天 9-22 刚改) | 每晚全量,变更自动全局生效 | 必须显式触发全量重建,漏触发=页面陈旧数静默上线 | sidecar 口径版本戳,不一致自动降级全量 |
| 4 | 峰值资金/回撤等全局聚合量 | 全量聚合 | 采用 Approach A(聚合全量)= 零失真;若贪心连聚合也滚动=低估峰值风险 | 设计直接排除聚合滚动 |
| 5 | 冻结分时点防御闸(2026-09-18 根治) | 全量下语义完整 | 窗口重算时新信号补冻逻辑必须逐字保持,漂移重入窗口的信号可能被闸挡住 | 时点穿越测试覆盖 |
| 6 | **SDC 对比档**(KELLY_BUY_NEXTDAY=0) | 双全量 | 必须 NDO+SDC 同滚同冻,复杂度×2;或 SDC 整体降频(见 §5.4a) | 与用户拍板 SDC 定位 |
| 7 | 冻结后的历史不可自愈 = 牺牲现状最大隐性价值 | — | — | 见 §1.4:除非用户明确"历史成交=sacred,变更只向前",否则不引入 |

## 7. 维度清单完成度(§5.1⑤ 报告维度自查)

| 维度 | 完成度 |
|---|---|
| 基线复现(基准锚点 A=161.63%/K=162.12%) | 基准口径如实转引(memory kelly-backtest-caliber-authority);实数测量以页面一致的数据源/脚本路径为准,本轮不重复复跑锚点(全量脚本输出数值与页面口径由既有对账闸管) |
| 现状分阶段实测(非估算) | ✅ 云上 NDO/SDC 端到端 + compute 五段分项 |
| 增长外推 10 年 | ✅ §5.3 按增速测算 |
| 收益量化对比 P1 | ✅ §5.4 |
| 防前视机检设计 | ✅ §4(时点穿越+漂移哈希+口径戳+页面锚点) |
| 风险清单(语义变化) | ✅ §6(7 项,+ 诚实标注:157s 原始数字为估算非实测,被直接测量推翻) |
| 边界方案完整(含固化物/读写方) | ✅ §3 |

## 复现命令

```bash
# 云上分阶段计时(只读;冻结表 no-op;输出 /tmp 不落生产)
# NDO/SDC 端到端(输出 /tmp,freeze 指 /tmp 副本,零生产写入):
#   SIGNAL_KELLY_ETF_FREEZE_PATH=/tmp/fz.json python3 scripts/signal_kelly_backtest.py \
#     --output /tmp/bt.json --trades-output /tmp/tr.json
#   KELLY_BUY_NEXTDAY=0 同参跑 SDC
# 本地只读: 价格加载耗时/行数(§5.1 同 SQL)、signal_daily 漂移痕迹 SQL 见调研过程记录
```
