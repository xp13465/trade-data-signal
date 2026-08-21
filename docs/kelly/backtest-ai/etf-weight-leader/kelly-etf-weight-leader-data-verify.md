# ETF→权重龙头个股 分支回测:数据验证 + 方案文档

> 状态:数据验证已完成(2026-08-20) / 全量回测待实施
> 关联待办:docs/pending-features-index.md 模块三 #93
> 用户拍板:选股口径 B1/B2/B3 全跑,本轮先数据验证,不直接全量回测

## 一、背景与目标

现信号凯利回测(scripts/signal_kelly_backtest.py)的映射链为:
**信号(sentiment.db signal_daily) → 指数(index_id) → board_etf_map.json 取 track_score 最高 1 只 ETF → 信号日收盘买 10000 元 → 9 卖出模式**。

#93 新方向:信号出来后,不买 ETF 本身,而是买「跟踪分第一/前三名 ETF」的**持股权重最高个股 TOP1**(借 ETF 管理方筛选,比自找行业龙头靠谱),回测对比:
- ① 是否提高收益
- ② ETF 第一名 vs 前 3 名综合体的龙头个股哪个更稳定
- ③ 补全各周期(熊市/各时间窗口)

**已定口径(用户拍板)**:B1/B2/B3 全跑
- 基准 A = ETF 本身(现有逻辑,对照组)
- B1 = 第一 ETF 持仓 TOP1 个股
- B2 = 前 3 ETF 各 TOP1 个股去重等权
- B3 = 前 3 ETF 按 track_score 加权或 TOP3 并集

## 二、可行性结论(数据已通)

### 2.1 ETF 持仓数据源可用(东财 fundf10)

`app/collector/public_fund.py` `fetch_fund_portfolio_hold`(L1278-1420)已实测对**场内 ETF 100% 可用**,返回每季度前十大重仓股(股票代码/名称/占净值比例)。接口:
`https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code=XXXXXX&topline=10000&year=YYYY`,带 Referer+UA。2019Q1 至今历史季度全可拿。

### 2.2 数据验证结果(Step1)

覆盖率:**113 只 track_score 第一 ETF** / **108 只有持仓(95.6%)** / 季度快照 **1626 条**(2019Q1~2026Q2);唯一无持仓=nikkei225(境外)。
TOP1-3 个股去重集合:**A 股 337 只 + 境外 34 只**。
TOP1 权重分布(整体 108 只有持仓):**>5% 强 96(88.9%) / 1-5% 中 10(9.3%) / <1% 弱 2(1.9%)**,中位 **9.98%**。

| 指数大类 | n | >5% 强 | 1-5% 中 | <1% 弱 | TOP1 中位权重 |
|---|---|---|---|---|---|
| 行业 | 36 | 35 | 1 | 0 | 10.78% |
| 主题 | 40 | 39 | 1 | 0 | 9.71% |
| 境外(有持仓) | 9 | 9 | 0 | 0 | 8.63% |
| 宽基 | 21 | 11 | 8 | 2 | 5.39% |
| 其他(bj50 等) | 2 | 2 | 0 | 0 | 16.96%/9.79% |

按 tier:strong(33)>5%强28中位9.93% / related(34)>5%强28中位10.02% / approx(12)>5%强11中位10.17% / none(29)全>5%中位9.71% —— **tier 对 TOP1 集中度几乎无区分,关键区分维度是指数大类(宽基弱 vs 行业/主题强)**。

> 详见 `docs/kelly/backtest-ai/etf-weight-leader/etf-weight-leader-data-validation-report.md`(完整 §2.2/龙头效应/数据可用性/映射链/局限)。

### 2.3 个股历史日线补采

113 只 track_score 第一 ETF(108 有持仓)的 TOP1-3 个股去重集合(预期 50-200 只 A 股)已通过 baostock 前复权日线补采完成(独立库 `data/stock_top_weights.db`,不污染生产 stock_daily.db)。

### 2.4 映射链确认(锚点)

- 信号源:sentiment.db `signal_daily`(index_id, buy/buy_aux/buy_special/buy_backup)
- 指数→ETF:scripts/signal_kelly_backtest.py L362-381 `_build_best_etf`,每指数取 track_score 最高 ETF;BUY_SIGNALS L73
- 买入:信号日当日收盘价,每笔 10000 元(L474/L69),9 模式卖出(L75-93 SELL_MODES)

## 三、选股三档口径定义

| 档位 | 定义 | 逻辑 |
|---|---|---|
| A(基准) | 信号指数 track_score 第一 ETF 本身 | 现有逻辑,对照组 |
| B1 | 第一 ETF 持仓 TOP1 个股 | 借最优 ETF 管理方筛龙头 |
| B2 | 前 3 ETF 各 TOP1 个股,去重等权 | 3 家管理方交叉,稳健性 |
| B3 | 前 3 ETF 按 track_score 加权 或 TOP3 并集 | 权重敏感度 / 集中度 |

> 前 3 ETF = board_etf_map 该指数 track_score 前三(去重不同 ETF)。

## 四、持仓快照对齐防未来函数

个股持仓来自**季度披露前十大重仓股**,报告期与实际披露日有滞后,信号日使用持仓必须用「≤信号日 D 且已披露」的最近快照。披露滞后近似(保守):

| 报告期 | 披露日近似 | 可用起始 |
|---|---|---|
| Q1(3/31) | 4 月底 | 5/1 |
| Q2(6/30) | 8 月底 | 9/1 |
| Q3(9/30) | 10 月底 | 11/1 |
| Q4(12/31) | 次年 3 月底 | 次年 4/1 |

即信号日 D 用「报告期 + 披露滞后 ≤ D」的最近一期持仓;D 早于首期可用快照则跳过该信号(个股法 2019Q2 起才有首个可用快照)。

## 五、成交与费率(个股版)

| 项 | 值 | 说明 |
|---|---|---|
| 每笔金额 | 10000 元 | 与基准 BUY_AMOUNT 同 |
| 买入价 | 信号日当日个股收盘价(前复权) | 与基准"信号日收盘"同语义 |
| 佣金 | 万 3 单边,min 5 元 | simulate_trade.py DEFAULT_FEE_CONFIG |
| 印花税 | 万 5 卖出单边 | 个股现行标准(ETF 免,个股版需启用) |
| 过户费 | 万 0.1 买卖都收 | 沪深统一 |
| 滑点 | 千 1 单边固定 | 同上 |
| 卖出模式 | 9 模式 A-I 全部 | SELL_MODES 同基准,含 G/H/I 信号驱动卖出 |

> 关键差异:个股印花税万 5(ETF 0),且个股日线为前复权(除权跳空已抹平),基准 ETF 用 accum_nav 累计净值。

## 六、回测窗口

- 个股法(B1/B2/B3):2019Q2 起(首个持仓快照可用,Q1→5/1 后)
- 基准 A:全窗口(信号自起始,不受持仓快照限制)
- 主对比:共同窗口 2019+ 全周期对比 + 各周期 y1/y3/y5/all 分别对比

## 七、周期维度补全清单(§5.1⑤ 全局核心问题报告必全)

> 本报告为数据验证+方案,回测实施阶段报告必须包含以下全部维度,缺一验收不过:

| # | 维度 | 说明 |
|---|---|---|
| 1 | 基线复现 | 基准 A 必须复现 v1.1.2 推荐最优组合(§5.4:基础5+核心3=8键+1类)对应信号凯利基线 |
| 2 | 按年分解 | B1/B2/B3 vs A 逐年收益/净利,确认领先是否靠近期行情撑起 |
| 3 | 稳定性 | 按年方向一致率 / 分半对比 / cap 敏感性 |
| 4 | 回撤与恢复 | 最大回撤金额·占本金%/谷日/恢复日/恢复期 |
| 5 | 大熊市及极端窗口 | 单边熊/阴跌/独立走弱窗口逐一测(2018/2022/2024 等) |
| 6 | 不同周期/参数变体 | 9 模式矩阵 + K 档 + 组合规则(A/B2/B3 全对比) |
| 7 | 口径诚实标注 | 龙头效应弱档(宽基)/境外 ETF 信号 fallback/前十大披露局限等如实标注 |

## 八、数据源局限诚实标注

1. **境外指数信号无 A 股个股可买**:112 只 track_score 第一 ETF 中 10 只是境外指数(hsi/hstech/hscei/us_dji/us_spx/us_ndx/us_ixic/nikkei225/dax/cac40),持仓为美股/港股/日股/德股/法股,个股法无法补采 A 股日线 → 该批信号在 B1/B2/B3 中 fallback 回 ETF 本身或剔除(方案待定,倾向 fallback 回 A)。
2. **债类信号**:cgb_idx(2116 信号)/cgb_10y_etf/cgb_10y_future 等无股票持仓,不在 112 只 ETF 覆盖内,个股法天然不适用。
3. **前十大重仓股披露**:ETF 季度披露前十大,非全持仓;龙头效应评估基于前十大,TOP1 是有效代理,但完整持仓未知。
4. **披露滞后近似**:Q1→5/1 等为保守近似,实际披露日不一(指数基金通常快),个别信号日快照可能用稍旧的持仓。
5. **指数增强 ETF**:如 562810(上证指数增强ETF嘉实)持仓为增强组合,非纯跟踪,TOP1 与指数成分龙头有偏差,但仍是"管理方筛选"语义。
6. **未复权/除权跳空**:个股日线已用前复权抹平除权跳空;涨跌停约束个股版需保留(前复权价涨停价判定与不复权不同,需评估)。
7. **中小盘龙头效应弱**:宽基/中小盘 ETF TOP1 权重 <5%,龙头效应弱,个股法与 ETF 收益差异可能小(需数据验证)。
8. **起点受限**:个股法 2019Q2 起,2019 前信号无法回测(持仓快照无)。

## 九、实施改动点(独立分支脚本,不碰基准)

> **⚠️ 隔离红线(2026-08-21 用户定,最高优先级)**:#95 结果**未决定上线前**,所有相关开发 + 回测**一律不得影响生产环境、不得污染生产数据文件**;只有决定要上线(排定)才允许融合进生产。任何同 commit bump 版本串 / 覆盖线上产物 / 写生产 DB / 改生产代码 / push main 融合 = 违规(§23.11 静默吞掉同理)。回测产出只落独立新文件,生产侧零改动(§8 改完必须推送、§24 前端部署、§23.7 版本冻结契约均不在本阶段触发)。

新建 `scripts/signal_kelly_backtest_stock.py`(复制 signal_kelly_backtest.py 改造):
0. **隔离**:只读 sentiment.db(信号)/etf_national_team.db(ETF日线)/stock_top_weights.db(个股)/board_etf_map.json/signal_stats.json;**绝不写任何生产 DB、不覆盖任何线上产物**;输出全落独立新文件(`signal_kelly_backtest_stock.json`/`signal_kelly_stock_trades.json` 等,不碰 `signal_kelly_backtest.json`/`signal_kelly_trades.json`);不 bump 版本串、不 deploy、不推 main
1. 选股函数 `_build_best_stock`:信号指数 → track_score 第一/前三 ETF → 读 `data/stock_top_weights.db` 快照表 → 按 D 日披露滞后取 TOP1/TOP3 个股
2. 价格源:ETF accum_nav → 个股前复权 close(从 stock_top_daily)
3. 费率:个股版 fee_config(印花税万 5 启用)
4. 快照对齐:§四披露滞后表
5. 输出:trades 落独立结果文件,不覆盖 signal_kelly_trades.json(同红线 0)
6. 9 模式卖出逻辑复用,G/H/I 信号驱动卖出基于指数卖出信号(与基准同)

## 十、待办 #93 关联

本报告为 #93 的数据验证阶段产出。完成后:①数据已通(ETF 持仓 + 个股日线补采) ②方案已定(B1/B2/B3 口径 + 快照对齐 + 费率 + 窗口) ③回测实施派 implementer 建独立脚本。回测完成后回填 #93 状态并同步用户。

## 十一、复现

- Step1 脚本:`docs/kelly/backtest-ai/etf-weight-leader/scripts/etf_hold_verify.py`
  - 命令:`.venv/bin/python docs/kelly/backtest-ai/etf-weight-leader/scripts/etf_hold_verify.py`
  - 依赖:static-site/data/board_etf_map.json + 东财 fundf10 网络
  - 输出:data/etf_hold_verify_result.json
- Step2 脚本:`docs/kelly/backtest-ai/etf-weight-leader/scripts/stock_daily_backfill.py`
  - 命令:`.venv/bin/python docs/kelly/backtest-ai/etf-weight-leader/scripts/stock_daily_backfill.py`
  - 依赖:Step1 结果 + baostock(前复权)
  - 输出:data/stock_top_weights.db(stock_top_daily 表)
- 数据截止:ETF 持仓 2026Q2 / 个股日线拉取当日
- 关键口径一句话:信号 → 指数 → track_score 第一/前三 ETF → 披露滞后对齐持仓快照 → TOP1/TOP3 个股 → 前复权日线买 10000 元 → 9 模式

## 十二、结论(2026-08-21)
无实际价值，不推荐。详见 etf-weight-leader-conclusion.md。
