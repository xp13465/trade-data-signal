# AI宏「4+3+1」调研:特殊信号(债类/波段)是否应纳入 AI 建议(2026-08-14)

> 结论先行:**不做「+1」**。三重验证证明特殊信号(债类 cgb_*/波段 band)本就不该入宇宙、也从未真正入样,无需专门的「+1 机制」;#25 的 `_bt_in_universe` 过滤正是「4+3+1 里那个 1(排除)」的正确固化落点,已上线覆盖;§23.6(入样宇宙规则治理,CLAUDE.md 2026-08-14)规范兜底防再犯。

## 0. 背景与动机(调研问题)

- 用户提出「AI宏 4+3+1」想法:在现有「AI宏7 = 基础4 + 核心3」基础上,加第 8 个特殊信号,把债类/波段类等「特殊信号」纳入 AI 建议。
- 现状核对:AI宏7 = 基础4 + 核心3 的默认过滤定义在 `static-site/lab.js _kellyDefaultFilters()`(L7253;调用点 L8043/8564/8570/8681/8741/8877/8960 等),包含 positionCap(默认 K1)、excludeAuxCross、excludeSpecialBear、n2NovSpecialIndustry、r7MayReinforced、greedy15、janMidRating、janMidSpecial 等默认开启项。
- 调研问题核心:AI 建议(首页 top-K 候选)是否应把债类/波段这类「特殊信号」纳入「选择标的做推荐」的候选集?
- 结论:不该,也不必专门设计「+1 机制」。理由见 §2 三重验证 + §3 #25 覆盖 + §4 §23.6 兜底。

## 1. 方法(复现/核证口径)

本调研为**现场代码/数据核证型分析**(researcher 对既有代码与产物做 grep/数据点核证,非新跑回测),不产生新独立回测脚本。复现依赖以下既有文件与数据点:

- 回测白名单与入样逻辑:`scripts/signal_kelly_backtest.py`(BUY_SIGNALS L55、`_resolve_etf`/`skipped_no_etf` L939/946-950)
- 债类入样穷举对比(已落档):`docs/kelly/analysis/kelly-bond-inclusion-probe.md` + 数据 `docs/kelly/analysis/data/bond_probe_comparison.json` + 脚本 `docs/kelly/scripts/signal_kelly_backtest_bond.py`
- 交易产物:`data/signal_kelly_trades.json`(local,`signal` 字段=字段索引 2)
- #25 入样宇宙标记:`app/queries.py L799`(后端注入 `_bt_in_universe`)+ `static-site/app.js L2087/2092`(前端过滤)
- 默认过滤现状:`static-site/lab.js _kellyDefaultFilters()`(L7253)

> 注:本调研**未单独产生新分析脚本**,结论由 researcher 现场 grep/数据点核证得出;复现依赖上述代码/数据点,复现命令见 §5。

## 2. 三重验证证据(逐条,附代码/数据出处)

### 证据 1:债类全 `skipped_no_etf`(无 ETF 匹配 → 从不入样)

- 出处:`scripts/signal_kelly_backtest.py` L939 `_resolve_etf(...)` 返回 None 时 `skipped_no_etf += 1; continue`(L946-950)。
- 债类指数 cgb_*(如 cgb_10y_etf)在 `board_etf_map.json` 无指数→ETF 映射,`_resolve_etf` 匹配不到 ETF → 全部跳过,从不进入回测/入样。
- 交叉验证:已落档 `kelly-bond-inclusion-probe.md` 实测——`skipped_no_etf` 基线 13,425;即便给债类加 self-ETF 兜底,纳入的 415 笔 cgb_10y_etf 买信号在全部 9 种卖出模式下均净亏损(-3,261 ~ -10,859 元)、胜率仅 20.7%~43.9%,纳入后各模式总净利全降。**债类不入样本就是正确设计**。

### 证据 2:band 波段类不在 BUY_SIGNALS 白名单(本就不入样)

- 出处:`scripts/signal_kelly_backtest.py` L55 `BUY_SIGNALS = ("buy", "buy_aux", "buy_special", "buy_backup")`。
- 回测只遍历这 4 种买信号;波段类 `band_*`(band_sell/band_hold)不在白名单 → 本就不入样。
- 语义补充(源自 `kelly-bond-inclusion-probe.md` §2.3):`band_sell` 在 signal_daily 中不存在(0 行);国债波段仓位管理(signals.py `sig_map`)把「减仓/止损」映射为 `sell`、「接回」映射为 `buy_aux`、「持有」映射为 `band_hold`。「波段调整」实际是 `sell`(已在卖出时间线),「接回」已是 `buy_aux`(已纳入买信号)。`band_hold` 是每日「持有状态」信号,非买入点——作为买入信号入样在语义上就不成立。

### 证据 3:trades 无 band 记录 + 宇宙内无稳定净亏组合

- 出处:`data/signal_kelly_trades.json`(local)实查:总交易 177,096 条,`signal` 字段(索引 2)分布 = `{buy_special: 80598, buy_backup: 12642, buy: 33840, buy_aux: 50016}`,**band 记录 0 条**。全部入样交易均来自白名单 4 类,无任何波段记录。
- 宇宙内无稳定净亏组合(与「加第 8 个特殊信号」会引入亏损组合相对照):AI宏7 默认组合为正向最优(穷举已定),债类(证据 1)与波段(证据 2)均非净利来源,纳入反而拉低。

### 三重验证综合

债类从「无 ETF 匹配」层面跳过(证据 1)、波段从「白名单」层面排除(证据 2)、交易产物无任何 band(证据 3)——特殊信号**从未真正入样,也本就不该入样**。「+1」想解决的是「特殊信号入 AI 建议」问题,而该问题的前提(特殊信号本该入样)不成立,故无需专门的「+1 机制」。

## 3. 结论:不做 + 缘由 + #25 如何覆盖

- **结论:不做「AI宏 4+3+1」**。三重验证说明特殊信号(债类/波段)本就不该入宇宙、也从未真正入样,不存在「值得纳入但被漏掉」的候选信号,故不需要第 8 个特殊信号位。
- **#25 如何覆盖「+1 的排除」**:#25(2026-08-14 上线)把入样宇宙判定固化为 `_bt_in_universe`:
  - 后端 `app/queries.py` L799:`_s["_bt_in_universe"] = any(_e.get("track_score") is not None for _e in (_s.get("etfs") or []))`——信号有跟踪 ETF 且带 track_score 才算入样(等价回测 `_build_best_etf` 判定),债类(无 ETF 匹配)、band(不在白名单)天然 `_bt_in_universe=false`。
  - 前端 `static-site/app.js` L2087/2092:AI 建议 top-K 过滤 `it._bt_in_universe !== false`(未入样信号不参与 AI 建议),1:1 对齐回测。
  - **「4+3+1 里那个 1(排除)」的正确固化落点正是 #25 的 `_bt_in_universe` 过滤**——它已经完成了「把不该入样的特殊信号排除在 AI 建议外」这一目的,无需再设计独立的「+1」排除机制。
- **§23.6 规范兜底**:CLAUDE.md 2026-08-14 新增 §23.6「入样宇宙规则治理」,要求宇宙规则(入样白名单/排除类别/自我 ETF 唯一例外)①显式声明于 `config/universe_rules.yaml` ②强制公示(purpose-notes.js + lab.js + app.js tooltip)③首页 1:1 遵从 `_bt_in_universe` ④对称校验(`scripts/check_universe_alignment.py`)⑤变更联动(8 步)。任何想改「哪些信号入样」的变更(含未来再提「+1」)都必须走这套治理,防「隐式规则未公示」再犯。

## 4. 防重犯(§23.6 触发词)

本报告结论依赖的「入样宇宙规则」属 §23.6 触发范围。后续任何改回测宇宙 / 改 BUY_SIGNALS / 改 board_etf_map 收录规则 / 新增排除类别 / 首页 AI 建议选标的的判定变更,必须走 §23.6 八步联动(改 yaml → 重跑 map → 重跑 backtest → 重跑 export → 首页跟随 → 公示 → 对称校验 → 三步同步上线),并同步本报告结论核证。

## 5. 复现/核证方法(读哪些文件、跑什么能复核)

1. **核对白名单**:`sed -n '50,60p' scripts/signal_kelly_backtest.py`(看 BUY_SIGNALS L55)。
2. **核对 skipped_no_etf 逻辑**:`sed -n '935,955p' scripts/signal_kelly_backtest.py`(看 `_resolve_etf` None → `skipped_no_etf += 1`)。
3. **核对债类入样穷举**:读 `docs/kelly/analysis/kelly-bond-inclusion-probe.md` §2;数据 `data/bond_probe_comparison.json`;重跑 `python3 docs/kelly/scripts/signal_kelly_backtest_bond.py`(若需复核债类 415 笔全模式净亏)。
4. **核对 trades 无 band**:`python3 -c` 读 `data/signal_kelly_trades.json`,统计 `signal`(字段索引 2)分布,验证零 band、总数 177,096。
5. **核对 #25 落点**:`grep -n "_bt_in_universe" app/queries.py static-site/app.js`(后端 L799 + 前端 L2087/2092)。
6. **核对默认过滤现状**:`sed -n '7253,7290p' static-site/lab.js`(看 `_kellyDefaultFilters` AI宏7 组成)。

## 6. 备注

- 本报告为**纯调研/落档**,不改代码逻辑、不改回测宇宙、不改前端选择逻辑;#25 已上线,本报告仅固化「不做 +1」的结论与证据,供未来「再提 +1」时反查。
- 本调研未产生新独立脚本(证据均为既有代码/数据点核证),未归档新脚本;债类入样穷举脚本已在 `docs/kelly/scripts/signal_kelly_backtest_bond.py` 落档(见 §1)。
