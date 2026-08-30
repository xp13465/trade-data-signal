# 卡片看板 vs 交易记录弹窗 持仓数字不一致 根因调研

> 触发场景:凯利区(全信号/模式卡)卡片「持仓中」数字 vs 点卡弹出的交易记录弹窗「含 N 笔预估」数字不一致。
> 用户报告:G 模式下卡面峰 10 笔 vs 弹窗「含 29 笔预估」;A-F/J 模式卡面 A=5/E=2/J=7 vs 弹窗「含 3 笔预估」。
> 调研口径:测试基准 = 当前基准 v1.1.7 S06 基线(G=P≤3d@10万 / H=满仓不买@5万 / I=P≤3d@9万,静态 NEW14 为非基准对照口径)。
> 结论一句话:两展示位各自内部计算都正确,但**两链用了不同的降亏谓词口径**——卡面走 S06 按日动态谓词,弹窗走静态 NEW14 键集谓词,且 G/H/I 卡面套 GIH 长线仿真、弹窗不套——所以同一批原始交易得出不同持仓数,属 §22 数据一致性违例(展示位口径未对齐)。

## 一、两链数据源与口径完整数据链(问题①)

两处展示位**共用同一份数据源** `static-site/data/signal_kelly_trades.json`(quadrants = rating_high/mid/low × 9 卖出模式列的原始交易行),但各自走独立的重算链路,降亏谓词与后处理不同。

### 卡面链(lab.js `_kellyApplyFeeRecompute` L8380-8563,卡片渲染 `_renderSigKellyCard` L11392 起)

1. 数据源:signal_kelly_trades.json 的 quadrants[rating][mode] 原始交易行。
2. 降亏谓词(**此处与弹窗不同**):S06 态(`_KELLY_FADE_DEFAULT_MODE="s06"` common.js L792)下,C 名 passesFade 用 **per-date 按日谓词** `_tdsS06FiltersForDate(signal_date)`(common.js L915-1023,S06 快照按日基座 a9/new15 的键开关表)——每笔信号用它自己 signal_date 当天生效的基座键集来判定。
   - G/H/I 三模式额外走 **NoBull 变体**(强制 bullAuxBackupStop=false,即长线模式豁免「牛市不追买」键)。
3. 基笔池 + posCap K1:`_kellyPositionCapKeptKeys`(lab.js L7646)按 signal_date 分组、track_score DESC 排序、每日只保留 K=1 笔 → **卡面池 611 基笔(G/I NoBull 池 647)**。
4. 每日池金额:BUY_AMOUNT(10000)/当日保留数,`_kellyRecomputeTrade` 按 etf_main 真实费率(万0.5 + 规费)重算单笔。
5. G/H/I 且 GIH 开关 on:`pdata[m+"__gihb1"]` 走 `_kellyAihlineApply(strat)` 的 **b1 仿真结果**(P≤3d@10万 / 满仓不买@5万 / P≤3d@9万,lab.js `_kellyGihStrategyKey` 映射 G→p3d10w / H→hold5w / I→p3d9w),再 `_kellyComputeStats`。
6. `holding_count = stats.holding_count` = trades.filter(无 sell_date).length(lab.js L7226-28)。

### 弹窗链(lab.js `_openSigKellyTradesModal` L11507-11637,持仓行区 L11702)

1. 数据源:同一份 signal_kelly_trades.json。
2. 降亏谓词:**
   `filters = state.labSigKellyFilters || _kellyDefaultFilters()`(L11507 附近;`_kellyDefaultFilters` lab.js L7304)→ **静态 NEW14 键集**(14 键全开,S06 是 dynamic 预设、`_tdsFadeModeApply`(common.js L813)对 dynamic 返回 false、不落 state,所以弹窗永远取默认静态 NEW14)。
3. 过滤:`_pcFadeFn`(静态 NEW14 谓词)+ 周期 cutoff(全部/近1/3/5/10年)+ posCap K1(在**静态池**上跑)→ 弹窗共 431 笔。
4. **未套 GIH 仿真**(弹窗代码注释 L11805 自认「本弹窗...未套 ai 长线仓管理...与卡片可能不一致」)。
5. `holdingCount = trades.filter(t => !t[fIdx.sell_date]).length` → 「含 N 笔预估」。

### 两链差异点汇总

| 环节 | 卡面链 | 弹窗链 |
|---|---|---|
| 降亏谓词 | **S06 按日动态** `_tdsS06FiltersForDate(signal_date)`(G/H/I 再套 NoBull) | **静态 NEW14** `_kellyDefaultFilters()` |
| 基笔池 /\ posCap K1 | **611**(G/I 647)** | **431** |
| 每日池金额 | 10000/当日保留数(与卡面池同源) | 10000/当日保留数(与弹窗池同源) |
| G/H/I 仿真 | **套 aihline sim b1**(P≤3d@10万 等) | **不套** |
| 周期 cutoff | stats 窗口内子集 | 交易子集(同逻辑) |

> 注意:G 卡面 n=647 与弹窗共=431 的差异是两链池基数不同(647/611 vs 431);E 卡面 n=611 与 G 647 的差异是 G 走 NoBull 池更大。


## 二、复现结果:卡面 vs 弹窗 持仓数字全表(核心数据)

复现脚本:`docs/kelly/analysis/scripts/verify_card_vs_popup.mjs`(从 static-site/lab.js + common.js 用 vm 提取上线函数,驱动两链重建,与线上同源码同口径),存证 `docs/kelly/analysis/data/card-vs-popup-consistency.json`(60 rows,10 模式 × 6 周期,2026-08-30 01:25Z 生成)。

### 全周期(all)对比全表

| 模式 | 卡面持仓中 | 卡面峰并发 | 卡面n | 弹窗持仓中 | 弹窗共 | 差额诊断 |
|---|---|---|---|---|---|---|
| A | 5 | 10 | 611 | 3 | 431 | 弹窗少2(8/17/8/18/8/20 三笔卡面独有,总差 3-1) |
| B | 5 | 9 | 611 | 3 | 431 | 同 A |
| C | 5 | 9 | 611 | 3 | 431 | 同 A |
| D | 5 | 10 | 611 | 3 | 431 | 同 A |
| E | 2 | 5 | 611 | 3 | 431 | **反向差异**：弹窗 8/26 513260 有、卡面无(两链双向不一致) |
| F | 6 | 14 | 611 | 3 | 431 | 卡面多 8/17/8/18/8/20 等 |
| J | 7 | 18 | 611 | 3 | 431 | 卡面多 5 笔(含 8/07、8/10 backup) |
| G | 10 | 10 | 647 | 29 | 431 | **弹窗未套 GIH sim，原始未平仓 29 笔** |
| H | 5 | 5 | 373 | 5 | 431 | 一致(恰合) |
| I | 9 | 9 | 647 | 25 | 431 | **弹窗未套 GIH sim，原始未平仓 25 笔** |

（卡面 n=611(G/I=647)为卡面 basePool+posCap K1 后的交易总数，弹窗共=431 为弹窗链过滤后的总数。全部周期与近1/3/5/10年对比见 JSON，这里只列全周期。）

### 关键逐笔证据

1. **A/J/E 卡面独有持仓 8/17/8/18/8/20 三笔,逐笔判定是「谓词口径差异」不是 posCap/cutoff**(诊断输出见脚本 stdout 或重跑):

```
20260817 516390 buy_special | s06谓词=true 静态NEW14谓词=false | posCapK1 @s06池=true 静态池=false | 当日保留数 s06=1 静态=0 金额 s06=10000 静态=10000
20260818 512580 buy_special | s06谓词=true 静态NEW14谓词=false | posCapK1 @s06池=true 静态池=false | ...
20260820 516250 buy_aux      | s06谓词=true 静态NEW14谓词=false | posCapK1 @s06池=true 静态池=false | ...
```

   即:**这三笔在 S06 当日键集下被放行、在静态 NEW14 键集下被拦**,posCap 只是跟随(静态池里根本没有这三笔,自然不会被 K1 保留),cutoff 不影响(all 周期也差)。

2. **E 反向差异证明两链谓词「双向不对等」**:E 卡面持仓 2 笔(8/24、8/25),弹窗 3 笔(8/24、8/25、**8/26 513260 恒生科技 buy_aux hold=2d**)——8/26 这笔在弹窗静态 NEW14 下放行、E 模式卡面 S06 关键集下被拦。不是简单「卡面比弹窗全」,是两套判据各有取舍。

3. **G 弹窗 29 笔构成** = 未套 GIH 仿真的原始未平仓交易(2023-07-07 至 2026-08-26 累计,非近期集中持仓):标普500ETF南方 3 笔(20231030/20231107/20250312,hold 357~687d)、法国ETF华安 3 笔(20230707 hold 761d 最长/20241114/20250430)、道琼斯ETF鹏华 4 笔、红利低波ETF天弘 4 笔、恒生ETF易方达、光伏ETF富国 2、智能汽车ETF、军工ETF、证券ETF嘉实、工程机械ETF、恒生科技ETF 等 29 笔。持有时长中位约 200d,最长 761d。卡面 10 笔 = 套 P≤3d@10万 sim b1 后的「活跃未平仓」,即每个时点最多留 10 笔以内的短线强平后残余。

## 三、4 条核心问题逐条定性(问题②③④)

### Q1 两链各自数据源与口径完整链 —— 见上一节,两链同源不同谓词

### Q2 A 5笔 vs 弹窗 3笔、E 2笔、J 7笔 —— 判定:**口径差异(非单边 bug),§22 违规**

- **不是 posCap/cutoff 的锅**:8/17/8/18/8/20 三笔卡面独有持仓,逐笔判定 s06谓词=true、静态NEW14谓词=false,posCap 只是跟随结果(静态池无此笔自然不保留);cutoff 用 all 周期也差,排除周期因素。
- **根因 = 两链降亏谓词不同**:卡面走 S06 按日动态键集(`_tdsS06FiltersForDate`),弹窗走静态 NEW14 键集(`_kellyDefaultFilters()` 默认)——池基数 611 vs 431,差 180 笔就是两套判据各自放开/拦拦的组合。E 反向差异(8/26 恒生科技弹窗有卡面无)进一步坐实这是两套谓词的双向取舍,不是全包含关系。
- **定性**:两链各自的数字在各自口径下计算正确(卡面=所见的评分卡,弹窗=它自己声明的过滤集),但**展示位之间不一致,违反 §22 多展示位一致性铁律**。弹窗注释只声明了 G/H/I「未套 ai 长线仓管理」,**没有声明 A-F/J 用了与卡面不同的降亏谓词**,用户无法从界面得知两处为什么不一样。

### Q3 G 卡面 10 笔 vs 弹窗 29 笔 —— 判定:**口径差异(弹窗未套 GIH 仿真),弹窗注释已局部自认但覆盖不足**

- 29 笔 = 弹窗链用静态 NEW14 + 不套 GIH sim 的**原始未平仓**交易(2023-07 ~ 2026-08,hold 最长 761d)——这正是「长线持仓原貌」。卡面 10 笔 = 套 P≤3d@10万 仿真 **b1 后**的活跃未平仓(每个时点最多 10 笔,把长持超过 3 天的旧仓强制平掉换新)。两者是「真实长持清单」vs「模拟策略当前持仓」,数字本身都「对」,但口径不同 → §22 违规。
- 弹窗顶部代码注释(L11805)明确自认「本弹窗为未套 ai长线仓管理的原始交易…此处净盈亏/峰值与卡片可能不一致」——**设计者知道有差异,但用户视角的 UI 文案没有把这个差异讲透**(注释不足以让用户理解为什么 G 卡面 10、弹窗 29)。

### Q4 每条差异判定汇总(问题④)

| 差异 | 判定 | 依据 |
|---|---|---|
| A-F/J/E 卡面持仓 vs 弹窗 3 笔差 | **口径差异(两链谓词不同:S06 动态 vs 静态 NEW14)、非 bug、但 §22 违规** | 逐笔诊断 s06=…true/静态=false;E 反向差异证明双向 |
| G 卡面10 vs 弹窗29 | **口径差异(未套 GIH sim)、弹窗注释已局部自认、覆盖不足=§22 违规重点** | 29 笔明细=未平仓原始长持列表;卡面=sim b1 后 |
| I 卡面9 vs 弹窗25 | 同 G | 同 G |
| H 卡面5 vs 弹窗5 | **一致**(恰合) | 但 H 卡面 n=373 与弹窗 431 仍不同,只是持仓数恰好凑齐 |
| 池基数 611/647 vs 431 | 两链谓词不同导致,非独立 bug | - |

## 四、阶段 2 最小改动面建议(问题④)

> 只读调研,方案供主控验收拍板;依 §23.7 动既有功能前须用户确认。

### 方案 A(最小改动,治标:让两处口径「讲清」)——推荐先做

**目标**:不改计算,只消除「用户无法理解差异」的困惑。
1. lab.js `_openSigKellyTradesModal` 弹窗顶部注释/文案补充:
   - 把「本弹窗为未套 ai 长线仓管理的原始交易」扩展为明确声明:**A-F/J 弹窗走静态 NEW14 过滤、卡面走 S06 按日动态过滤,两处持仓数/池不同**(把 Q2 的谓词差异也讲出来)。
   - 明确「卡面显示的是 S06 当日生效基座过滤后的持仓,弹窗显示静态 NEW14 过滤后的持仓」。
2. 同步 §21 公示 mouth:lab 凯利区/卡片 hover 提示加一句"卡片与弹窗分母/持仓口径差异说明"。
- 改动面:弹窗文案 1 处 + §21 公示词 1 处,前端重算逻辑零改动。

### 方案 B(治本:弹窗对齐卡面口径,推荐终极目标)

**目标**:弹窗与卡面 1:1 同源,彻底消除同一数据两处不同数字。
- 让弹窗在 S06 态下复用卡面同款谓词:`_tdsS06FiltersForDate(signal_date)` 逐笔判定 + S06 池做 posCap K1(G/H/I 额外套 NoBull + GIH sim b1)。这样弹窗的「持仓中」= 卡面「持仓中」逐笔吻合。
- 改动面:`_openSigKellyTradesModal` 的谓词函数换源(从静态 `_kellyDefaultFilters` 切 `_tdsS06FiltersForDate`)+ posCap 池换源(从静态池切 s06 池)+ G/H/I 判断是否套 sim b1;work 集中在弹窗函数内,约 3 处换源 + 1 个 GIH sim 分支,卡面链不动。
- 风险:弹窗历史上展示的是「长线未平仓原貌」(G 29笔),切到 sim b1 后用户可能想保留「原始长持清单」视图——建议方案 B 做 **gih 开关联动**:GIH 开=弹窗套 sim 与卡面一致;GIH 关=保留原始视图并明确标注。即 B 是 A 的上位合流。

### 阶段 2 验收口径(供主控)
- ①弹窗与卡面「持仓中」数字逐笔比对一致(重跑本报告脚本出 diff=0)或②弹窗新增文案完整声明两条链口径差异(重跑脚本确认差异如旧但文案覆盖 Q2/Q3 两处)——两者至少居其一;
- §22 全展示位一致性机检:新增断言「S06 态下弹窗谓词 == 卡面谓词」或「弹窗文案含口径声明」。


---

## 五、诚实标注与已知边界

- **口径对照不纯声明**:本报告「弹窗」侧 = 静态 NEW14 默认键集(非当前基准 S06)。S06 是动态模式,弹窗无静态 keys、永远回落到默认 NEW14(B 方案改弹窗源后此对照才消失)。这是这次差异的**根**,也是 B 方案要治的点。
- **H 模式「一致」是巧合不是对齐**:H 卡面持仓 5 = 弹窗 5,但卡面 n=373 vs 弹窗共=431 ——持仓(a9)数组恰好都 5,但分母不同;若未来再加键/改 NoBull 会重新裂开。H 只是「当前恰好相等」,不代表两链已一致。
- **posCap 每日保留数**:诊断打印显示「当日保留数 s06=1 静态=0」,即 S06 池当天有候选保留 1、静态池当天 0 候选(被谓词拦光)——这正面证明差异发生在**谓词(是否放行)环节**,posCap K1 只对已放行的候选排序保留,不是差异来源。
- **cutoff 排除**:all 周期有差异即排除周期截断因素;y1/y3/y5/y10 的差额、方向与 all 相同(见 JSON 全表),无周期依赖。
- **每日池金额**:两链金额算法相同(10000/当日保留数),金额不是差异来源;差异纯粹来自「保留数」不同(谓词→池→K1)。

## 六、数据截止与复现

- 数据源:`static-site/data/signal_kelly_trades.json`(trades_generated_at=2026-08-30 05:02)、`static-site/data/kelly_mode_s06_state.json`(s06 快照 at=2026-08-28T21:16:31)、`static-site/data/kelly_loss_features.json`、`static-site/data/signal_kelly_backtest.json`。
- 基准:v1.1.7 S06 基线样式口径;本次只读对比展示,不输出买卖建议。
- 复现命令:

```bash
cd /Users/linhuichen/code/trade
node docs/kelly/analysis/scripts/verify_card_vs_popup.mjs   # stdout 全量对比+逐笔诊断;JSON 写 docs/kelly/analysis/data/card-vs-popup-consistency.json
```

- 口径一句话:卡面 = S06 按日动态谓词 + posCap K1 + 每日池金额 + (G/H/I 套 GIH sim b1);弹窗 = 静态 NEW14 默认键集 + cutoff + posCap K1(不套 GIH sim);两链同源 signal_kelly_trades.json,差异根因=降亏谓词口径不同 + G/H/I 是否套仿真。

## 附:落档

- 报告:`docs/kelly/analysis/kelly-card-vs-popup-consistency.md`
- 脚本:`docs/kelly/analysis/scripts/verify_card_vs_popup.mjs`(头部注释含目的/依赖/口径/复现)
- 数据:`docs/kelly/analysis/data/card-vs-popup-consistency.json`
- 索引:docs/kelly/analysis/README.md 本报告加索引行
