# A 短线第10天未盈利单转等 H 长线卖出信号出场 —— 机制现状 + 回测口径设计

> 调研/researcher 产出,只读,不跑写库/写产物命令。交付主控拍板。
> 生成日期:2026-09-06(文件名按派单规格用 20260908);数据快照 static-site/data/signal_kelly_trades.json 生成于 2026-09-08 09:15。
> 数据截止:2026-09-04(最近信号日);当前 S06 生效基座=new14(快照 current.mode=new14, since 20260831)。

---

## 摘要(结论先行)

1. **A/H 机制**:A=固定持有 10 个交易日到期卖出(无任何止盈止损);H=信号驱动卖出,等对应指数后续第一个 `sell` 或 `sell_stop_loss` 信号(取最早日)触发,无信号则持有至回测结束。两者买入口径一致(信号次日开盘,费后)。
2. **A 第10日亏损单规模**:全部有评级信号 47.6%(3616/7598,rating 三象限互斥);高评级(rating_high)34.9%(30/86),中评级 40.7%,低评级 49.5%。**评级越高,第10日亏损占比越低**。
3. **亏损单转 H 的代价/收益不对称(关键事实)**:
   - 高评级亏损单转 H 平均能转正(rating_high 30 笔转 H 合计 +6,127,8/30 转盈)→ 换挡在「高评级」有价值;
   - 中/低评级亏损单转 H 平均**更亏**(rating_mid -115,137;rating_low -666,512,仅 17% 转盈)→ 换挡在低评级是「把浮亏拖成实亏」。
   - 所以该规则的收益来源 = **只在高评级/盈利环境吃 H 的二次机会,同时保留 A 盈利单的短周期快速止盈**。proxy 混合(rating_high all 周期)+39,350 vs A +26,404 / H +36,320,且胜率 74.4% 显著更高。
4. **最大持仓堆积(用户点名指标)**:原始逐笔引擎下 H 峰并发本就高(rating_high H=36 倍本金 vs A=15);转档把亏损单持有期拉长(A 第10日→H 信号日,平均 +10~20 交易日),混合 proxy 峰并发 rating_high 21 / rating_mid 157 / rating_low 199,均介于 A 与 H 之间。**真实资金面(转档后能否再开新仓)必须用渐进仓位引擎(满仓不买@N万)测,原始逐笔引擎无资金约束会高估堆积与总收益**。
5. **待拍板参数**:触发日 D、盈利阈值、出场信号集、强制到期 C、资金模型(原始/渐进+cap)、宇宙口径(S06 动态 a9/new14 vs 静态),详见 §2.5。

---

## 第 1 章 机制现状(代码证据)

### 1.1 A(短线)= 固定 10 交易日到期卖出

- **定义**:`scripts/signal_kelly_backtest.py` L85 `"A": {"label": "固定10天", "hold_days": 10, "stop_profit": None}`。
- **实现**:`_backtest_one()` L590 `future_dates = dates[idx:idx+hold_days]`(`idx = bisect_right(dates, signal_date)`,即信号日后的未来交易日序列);A 的 `stop_profit=None` → 走 L640-657「模式 A/E/F:最后一天卖出」分支,`sell_date = future_dates[-1]`,即 **信号日后第 10 个交易日收盘卖出**,`sell_reason="到期"`。无任何止盈/止损/跟踪。
- **买入价**:`KELLY_BUY_NEXTDAY=1`(v1.1.4 起默认,L561-569):信号日收盘后固化,实际以**信号次日开盘价**成交(scale-free 换算进 accum_nav);伪跳空 >20% 整笔剔除。
- **A 单特征(trades 文件四象限行合计 30,392 行 = 7,598 个有评级信号 ×4 类象限;rating_high 86 笔)**:所有 A 单 `hold_days=10`、`sell_reason="到期"`。近1年/近3年/近5年/全周期收益见 §1.5 表。
- **公开文案**:lab 公示「10 种卖出模式(A 固定10天…)」,A 即「买入后持有 10 个交易日到期卖出」。

### 1.2 H(长线)= 信号驱动卖出(sell 或 sell_stop_loss 任一,取最早)

- **定义**:`scripts/signal_kelly_backtest.py` L97-99
  ```python
  "H": {"label": "卖出+追止损", "hold_days": None, "stop_profit": None, "signal": True,
        "sell_types": ("sell", "sell_stop_loss"), "desc": "卖出或追止损信号触发",
        "guidance_desc": "对应指数卖出信号(sell)或追止损信号(sell_stop_loss)任一触发卖出"}
  ```
- **实现**:`_backtest_signal_sell()` L687-796。对每笔交易:找买入日(`signal_date`)之后**第一个** `sell` 或 `sell_stop_loss` 信号日(遍历 `sell_signals = sell_timeline[iid]`,要求该 ETF 当日有价可卖),卖出价=**信号日 ETF 收盘 accum_nav**,`sell_reason = "追止损卖出"/"卖出信号"`;若无匹配信号 → 持有至回测结束,按当前价预估盈亏(`sell_reason="持有中"`)。
- **买入价与 A 完全相同**(同一 `_backtest_one` 前置逻辑,同一信号事件同买价)。
- **全象限出场分布**:卖出信号 11,256 / 追止损卖出 18,264 / 持有中 872(数据见 static-site/data/signal_kelly_trades.json)。

### 1.3 卖出信号源(signal_daily)——H 的出场信号是谁生成的

- 回测侧消费:`signal_kelly_backtest.py` L1093-1100 一次性读 `signal_daily` 中 `signal IN ('sell','sell_stop_loss')` 按 index_id 组时间线 `sell_timeline`,供 G/H/I 模式按指数查后续信号。
- 信号生成(`app/compute/signals.py`),两类语义完全不同:

| 信号 | 中文 | 触发规则 | 源码行 | 语义 |
|---|---|---|---|---|
| `sell` | 卖(止盈减仓) | 20日高回落 5%(正序列;负/窄幅序列 2σ)+ MA60 多头过滤 + MACD 死叉确认 | L832-857 | 趋势反转/冲高回落,止盈减仓提示 |
| `sell_stop_loss` | 追止损卖 | Chandelier Exit:`近20日最高(不含当日) − 3.5×ATR(14)` 首次跌破触发 | L1052-1059 | 移动止损线跟随高点,防深套 |

- **两者都是指数级(index_id)信号,不是 ETF 级**。H 的出场 = 买信号所在指数的后续 sell/sell_stop_loss 信号日,卖信号日**当日 ETF 收盘价**成交。
- 全量信号清单(入样 vs 展示):入样买白名单 `BUY_SIGNALS = (buy, buy_aux, buy_special, buy_backup)`(L82);`sell/sell_stop_loss/band_hold/band_sell` 为展示/离场类不入样(`scripts/check_universe_alignment.py` L58 `DISPLAY_ONLY_SIGNALS`)。`buy_special`=Donchian 20日上轨突破+5日站稳确认(追涨);`buy_backup`=Supertrend 翻多+3日二次确认(备选)。

### 1.4 最大持仓(当前口径)

- 原始逐笔引擎(`signal_kelly_backtest.py`)无资金约束,`_compute_stats` L997-1001:`max_concurrent`(扫描线并发持仓笔数)× 10000 = `max_concurrent_capital`;`return_pct_max_holding = total_profit / max_concurrent_capital`(峰值资金收益率,年化开方基数)。

| 象限 | A 峰并发 | A 峰值资本 | H 峰并发 | H 峰值资本 |
|---|---|---|---|---|
| rating_high | 15 | 15 万 | **36** | **36 万** |
| rating_mid | 156 | 156 万 | **314** | 314 万 |
| rating_low | 167 | 167 万 | **351** | 351 万 |

(数据:static-site/data/signal_kelly_backtest.json quadrants.*.periods.all,all 周期,逐笔 1 万;`max_concurrent` 同 `_max_concurrent` 扫描线口径,同日先买后卖=保守。)

- **可操作标准**:前端 `_KELLY_OPERABLE_CAP = 200000`(20 倍单次本金,lab.js L7948);H 原始峰持仓远超 20 倍 → 前端「ai长线(G/H/I)仓位管理」开后方可操作,H 映射 **满仓不买@5万**(method A,cap 50000,lab.js L7927,定案 2026-08-30/09-03):到 cap 就停买(当日超容整批跳过),不强制平仓,自然卖出腾位再买 → 峰值并发 ≤5 笔(5 倍本金)。
- **结论**:H 的「主推成绩」(净+115,416/收益 230.83%/峰并发≤5笔,2026-09-03 权威口径)来自**渐进仓位引擎**,不是原始逐笔引擎。设计回测必须分两层引擎(见 §2.3)。

### 1.5 样例单(A 与 H 同信号对比)+ 成绩基线

- **样例(同一信号 thsc_308700 buy_special → 512480 半导体ETF,2021-06-07)**:
  - A:买 2.264883 → 第10交易日(20210622)卖 2.396801,+5.72%,持有 10 日,`到期`。
  - H:买 2.264883 → 20210715 卖出信号卖 2.615382,+15.37%,持有 27 日,`卖出信号`。
  - 说明:H 的卖出信号**晚于 A 的第10日**(H 在 20210715 才触发),正是「A 第10日后等 H 信号」的真实样本;但同信号也有 H 在第10日前就出场的情况(见 §2.6 乐观偏差)。

- **rating_high 周期成绩(A vs H,逐笔引擎,source=signal_kelly_backtest.json)**:

| 周期 | A 净利 | A 胜率 | A 峰并发 | H 净利 | H 胜率 | H 峰并发 | H avg_hold |
|---|---|---|---|---|---|---|---|
| all | +26,404 | 65.1% | 15 | +36,320 | 55.8% | 36 | 31.5 日 |
| y1(近1年) | **+6,989** | 67.9% | 15 | **-1,869** | 28.6% | 17 | 15.1 日 |
| y3 | +23,181 | 65.3% | 15 | +33,037 | 55.6% | 36 | 35.1 日 |
| y5 | +24,645 | 64.3% | 15 | +33,278 | 54.8% | 36 | 31.7 日 |

- **关键**:H 全周期「最高成绩」成立,但**近1年 H 为负**(-1,869,胜率仅 28.6%)。这直接决定报告必须做「按年分解+稳定性」(§3.3/§3.4),否则会被全周期数字误导。

### 1.6 A 第10日亏损单画像(换挡规则的人口)

| 象限 | A 总数 | 第10日亏损(profit≤0) | 占比 | 该批转 H 合计盈亏 | 转盈笔数 |
|---|---|---|---|---|---|
| rating_high | 86 | 30 | 34.9% | +6,127 | 8/30 |
| rating_mid | 1,494 | 608 | 40.7% | **-115,137** | 89/608 |
| rating_low | 6,018 | 2,978 | 49.5% | **-666,512** | 526/2,978 |
| 全部有评级信号(互斥) | 7,598 | 3,616 | 47.6% | — | — |

(data:static-site/data/signal_kelly_trades.json。评级高/中/低三象限互斥覆盖全体有 score 信号(86+1,494+6,018=7,598);`A_bad` 配对同信号 H 单的出场结果,含 H 在第10日前出场的乐观情形,详见 §2.6。⚠ 勿用四象限∑(30,392/14,464)当总数——同一信号在 rating×etf×sig×mkt 各占一行重复计数,占比仍是 47.6% 但笔数是 4 倍虚高。)

### 1.7 混合 proxy 成绩(先看大方向,非结论)

口径:每信号取「A 第10日盈利 → 保留 A 出场;A 第10日亏损 → 套 H 出场」,逐笔引擎。

| 象限/周期 | A 净利 | H 净利 | 混合 proxy | 混合胜率 |
|---|---|---|---|---|
| rating_high all | +26,404 | +36,320 | **+39,350** | 74.4% |
| rating_high y1 | +6,989 | -1,869 | **+4,875** | 67.9% |
| rating_high y3 | +23,181 | +33,037 | **+36,633** | 76.4% |
| rating_low all | +148,743 | +651,079 | +599,931 | — |

混合 proxy 峰并发(同 `_max_concurrent` 扫描线口径):rating_high 21(A15/H36)、rating_mid 157(A156/H314)、rating_low 199(A167/H351),均介于 A 与 H 之间——转档确实推高堆积,但不如直接 H 严重。

---

## 第 2 章 回测口径规格(给主控/实施,字段级)

### 2.1 规则语义(核心定义,默认值粗体)

1. **触发日 D(默认 10)** = 信号日后第 **10 个交易日**(与 A 的 `hold_days` 同定义:ETF 交易日序列 `dates[idx:idx+hold_days]` 的最后一格)。
2. **盈利判定(默认 profit≤0)** = 用 **D 日收盘价**按 `_sell_with_fees`(含卖费)算 `net − BUY_AMOUNT ≤ 0` 判定「未盈利」。**判定价默认 = A 自己的出场价(第 D 日收盘)**,保证与 A 原规则可比;变体:第 D 日最低 / 次日开盘。
3. **转档触发** = 判定「未盈利」 → **不卖**,继续持有同一只 ETF(同 shares,同冻结标的,见 §2.2),进入「等 H 卖出信号」状态。
4. **转档出场** = 找 **严格晚于第 D 日** 的第一个 `sell` 或 `sell_stop_loss` 信号(`d > sell_date_D`,要求该 ETF 当日有价,与 H 的 `_backtest_signal_sell` L710-716 同搜索语义),**信号日 ETF 收盘 accum_nav 卖出**,`sell_reason` 沿用 `卖出信号/追止损卖出`。**H 出场信号集 = sell+sell_stop_loss(默认)**;变体:仅 sell(G 语义)。
5. **信号永不来(最坏情况)** = 持有至回测结束,按当前价预估(`sell_reason="持有中"`,与 H L718-760 同口径);变体加**强制到期 C** = 30/60 个交易日后强卖(锁死资本上限)。
6. **转档后仓位语义** = 冻结在 A 的同一仓位:同一信号事件 `(date, index_id, signal)` 冻结的同一只 ETF(`_resolve_etf` L284-310,历史成交固化防换标),同 shares,不换标的、不加仓。
7. **接口/成本** = 转档不产生额外买卖费用(不卖不买);仅在最终出场时付一次卖费。与 A 相比:A 在第 D 日付一次卖费,转档在更晚的出场日付一次(或永不付 → 持有中按当前价预估 = 未实现)。

### 2.2 冻结与宇宙(§23.6 同精神)

- 换挡不改变入样宇宙:宇宙仍由 `config/universe_rules.yaml` 排除类别 + `BUY_SIGNALS` 白名单决定,新增卖出模式 AR 不扩展/不缩减入样集合。
- ETF 冻结查表 `data/signal_kelly_etf_freeze.json` 照常生效;AR 只在既有 A 单基础上改出场路径,不动 `_resolve_etf`。

### 2.3 资金面模型(用户点名「转档后还能不能再开短线新仓」的唯一正解)

原始逐笔引擎(A/H/AR 三模式)每笔独立 1 万,**无资金约束**,只测 `max_concurrent_capital` 作「堆积」代理指标(与现有 A/H 数字可比)。但真实资金面必须再跑**渐进仓位引擎**:

- 复用 lab.js `AIHLINE_STRATS`(L7920-7943)仓位法:默认 **满仓不买@N万(method A)**(到 cap 就停买,当日超容整批跳过,不强制平仓)。N 取 {5万(默认,与 H 现行一致)、10万、20万}。
- 与「A 盈利单继续开短线新仓」的关系:**AR 转档单在第 D 日后仍占资金槽位**,满仓不买模式下会挤占后续新开仓 → 度量两个新指标:
  - `blocked_buys`(因 cap 被挤拒掉/跳过的信号日数);
  - `trapped_capital`(AR 转档单中持有至期末未卖出的资金 = 卡死槽位)。
- 说明:该引擎当前在 lab.js 前端 replay 实现;回测侧若在 Python 重建需按「同构对账」与页面逐位核对(§5.4⑦)。**若本轮只做逐笔引擎,堆积口径仅报告 max_concurrent,不计「不能开新仓」,须在报告显式标注范围。**

### 2.4 接口/成本明细

- 费率沿用 `_KELLY_FEE_CONFIG`(卖出佣金万3 + 滑点千1 + 沪市过户费万0.1 + 印花税恒0 + min佣金5元;L55-68)。
- 买入 = A 原单同一笔(A 会买,AR 也会买,买价/买费逐位一致);AR = A 的逻辑 + 第 D 日改判 + 延后出场,无第二次买入,**无转档费**。

### 2.5 参数矩阵(给主控/用户拍板)

| 维度 | 默认(建议) | 变体(一并跑) | 说明 |
|---|---|---|---|
| 触发日 D | **10**(对齐 A) | 5 / 15 / 20 | 5 太短转档率高;20 太长等于半 H |
| 盈利阈值 | **profit ≤ 0** | <0 / ≤-2% / ≤-5% | 阈值越严转档越少,只救深亏 |
| 出场信号集 | **sell + sell_stop_loss(H)** | 仅 sell(G) | H 含追止损更早释放槽位 |
| 强制到期 C | **无(持有至回测结束)** | 30 交易日 / 60 交易日 | 锁死「永不卖」资本上限 |
| 判定价 | **第 D 日收盘**(=A 出场价) | 第 D 日最低 / 次日开盘 | 收盘是 A 同口径 |
| 宇宙 | **S06 动态 a9/new14 按日切(现生产默认)** | 静态 new14 / 静态 a9 | 现快照 current.mode=new14 |
| 引擎 | **原始逐笔(主报告)** | 渐进满仓不买@{5万=默认,10万,20万} | 资金面/堆积/被挤新仓 |
| positionCap | **K=1(现默认)** | K=2/3/4 | 每日 top-K 基笔口径 |

### 2.6 口径诚实标注(何谓 proxy、何谓真实)

- **本章 §1.6/§1.7 数字是「proxy」**:直接用 H 单的出场结果替换 A 单,而 H 的出场可能发生在第 10 日**之前**(例:rating_high 30 笔亏损单中有 6 笔 H 在第 10 日前已出场)。**真实 AR 规则必须等「第 10 日之后的下一信号」**,会比 proxy 更晚出场、更慢释放槽位 → **proxy 对收益与堆积都偏乐观**。
- 正式回测 = 在 `signal_kelly_backtest.py` 加真实 AR 分支(建议新增 SELL_MODES 键 `AR`),逐笔重算第 D 日后的下一信号,数字以正式回测为准,proxy 仅用于先导定性。
- 买入价口径:AR 与 A/H 同用次日开盘(v1.1.4 默认);若对比需要,可加当日收盘旧基线作灵敏度(显式声明非基准口径)。

### 2.7 基线锚定(§5.4 / memory `test-baseline-v112-anchor`)

- 回测前**先逐位复现当前基线**:rating_high A/H/E/F/G/I 各周期 `n/win_rate/total_profit/max_concurrent` 必须与 `static-site/data/signal_kelly_backtest.json` 一致(该文件 2026-09-08 09:15 生成,随 09:15 回测链)。
- **⚠ 基准口径有一处待主控/用户确认**:memory 锚点 v1.1.7 写作「S06 动态 a9/**new15** 按日切」,但生产代码自 2026-09-01 起 `OFF_BASE="new14"`(`scripts/gen_kelly_mode_s06_state.py` L70;现快照 new14 since 20260831)。**本次按「现生产实际 = S06 动态 a9/new14」标口径**,并在报告中明示该漂移,请主控确认测试基准锚点是否应随 v1.1.8+ 升版(发版三件:基准定义/tag/记忆锚点)。

---

## 第 3 章 报告维度清单(§5.1 穷举最大化)

正式回测报告须一次给全下列维度,缺=验收不过:

| 编号 | 维度 | 内容 |
|---|---|---|
| R1 | **基线复现** | A/H/AR 三模式全周期+近1/3/5年逐位对账 signal_kelly_backtest.json;S06 锚点数字(净利/mdd, 标注 off_base 口径 new14 vs 锚点 new15) |
| R2 | **核心对比表** | AR vs A vs H:净利/胜率/盈亏比/mean_return/峰并发/峰资本/峰值资金收益率/年化/最大回撤/卡尔玛/平均持有日,全部象限(rating×sig×mkt×etf) |
| R3 | **按年分解** | 2011-2026 每年 AR vs A vs H 净利+盈亏;标注「领先是否靠近期行情撑起」(H 近1年为负已证) |
| R4 | **稳定性** | 分半(前半/后半)/触发日 D 敏感性/盈利阈值敏感性/cap 敏感性;S06 on-base(a9)与 off-base(new14)分年拆解 |
| R5 | **回撤与恢复** | 最大回撤元/%、恢复天数、回撤窗口对照(AR 是否比 H 更早收复) |
| R6 | **大熊市及极端窗口** | 2015 股灾、2018 熊市、2022 全年、2024-01/02 流动性危机;大熊市窗口内 AR 是否比 A 更晚/更早套牢 |
| R7 | **参数变体矩阵** | D∈{5,10,15,20} × 阈值∈{≤0,<0,≤-2%,≤-5%} × 信号集∈{H,G} × C∈{无,30,60} 全矩阵(样板优先全组合,超样本量按主效应先粗筛再细跑,诚实标注) |
| R8 | **持仓堆积专项** | max_concurrent_capital(原始引擎)+ 渐进引擎 blocked_buys/trapped_capital/永不卖单数占比 + 与 20 倍可操作上限比对 |
| R9 | **诚实标注** | proxy vs 真实差值、乐观偏差、宇宙口径、基准漂移、买入价口径、费率口径、null/缺数据跳过的笔数 |

---

## 复现

- **数据产物**:`static-site/data/signal_kelly_trades.json`(列式全量,2026-09-08 09:15 生成)、`static-site/data/signal_kelly_backtest.json`(统计,2026-09-08 09:15 生成)、`static-site/data/kelly_mode_s06_state.json`(S06 快照,2026-09-07 20:35 生成)。
- **生成命令(已存在)**:`cd /Users/linhuichen/code/trade && python3 scripts/signal_kelly_backtest.py`(写 static-site/data/ 三个产物);S06 快照 `python3 scripts/gen_kelly_mode_s06_state.py`。
- **正式 AR 回测脚本(待实施)**:在 `scripts/signal_kelly_backtest.py` 增 SELL_MODES 键 `AR`,分录修改点:`_backtest_one` 在 `sell_mode=="AR"` 时走「第 D 日判盈亏 → 不盈则 `_backtest_signal_sell(..., start_after=day_D)`」;`_backtest_signal_sell` 增加 `start_after` 参数(搜索 `d > start_after`);`SELL_MODES["AR"] = {"label": "A转等H", "hold_days": 10, "signal": True, "sell_types": ("sell","sell_stop_loss"), "rollover": True}`。脚本头部按 §23.5 补目的/口径/依赖/复现命令。
- **数据依赖**:根目录信号库 DB(只读,signal_daily/index_daily)+ `config/universe_rules.yaml`(宇宙排除)+ `config/indicators.yaml`(market 分类)+ `data/signal_kelly_etf_freeze.json`(冻结)。
- **关键口径一句话**:买=信号次日开盘(费后),A=固定 10 交易日收盘到期卖;AR=第 10 日收盘亏损则持同等同标的,等指数后续首条 sell|sell_stop_loss(严格于第 10 日后)信号日收盘卖,信号永不来则持至期末按当前价估;H=无 A 前10日、直接从买入日后找第一条 sell|sell_stop_loss 信号。
- **数据截止**:2026-09-04;S06 快照覆盖至 2026-09-07(status 当前 new14)。本次 proxy 数字非正式回测,不可引作结论。