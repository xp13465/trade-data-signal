# 首页「模拟回测」弹窗新增「逐日净资产走势图」前置调研报告(2026-09-04,researcher 重派 #51)

## 一、结论摘要(5 维度可落地)
1. **表格结构**:弹窗 = 逐笔成交行渲染,14 列表头 + 顶部筛选条 + 汇总行 + 分页(每页500条)。G/H/I 长线管位三档定案 G@10万/H@5万/I@9万,PRIN 每笔 ¥10000。
2. **交易字段**:trades JSON 24 字段全部后端自带(buy_date/sell_date/etf_code/signal/buy_price/sell_price/profit/return_pct/hold_days/current_price...),前端运行时只算费用与费后盈亏(pnlYuan/buyFee/sellFee/pnlPct);双滑点修复已内置在 _simBtCalcRow(记录价÷(1±0.001)还原真实净值)。
3. **净资产公式(核心难点已解)**:trades **无逐日持仓快照**,必须前端按逐笔成交(buy_date/sell_date+金额)重建逐日持仓序列。公式=「净资产(日)=现金+持仓市值;现金=初始-Σ开仓本金+Σ卖出净额(PRIN+费后盈亏);市值=Σ未平仓份额×当日accum_nav(缺日向前取);初始=峰值同时持仓笔数×¥10000」。复刻脚本已跑通验证(H 档 K=1 窗口 20250901~20260831:峰值5笔→初始5万,曲线241点,期末净资产46886.46)。**⚠️ 诚实标注:复刻脚本对账差 -27770.11 根因=3 笔 sell_date=20260902 晚于 accum_nav_map 末日 20260828(数据版本时间差,非公式错误),尾段须截断到 nav 末日或特殊处理。**
4. **数据源**:走势图数据前端从「管位后+切片后的 kept rows」重算,不新增拉取文件;nav 复用弹窗已加载的 accum_nav_map(common.js _kkellyRealNavEnsure 单例)。每日粒度=逐交易日(持仓 ETF 的 nav 日期并集∩窗口),体积可控(年窗口≈240 点)。
5. **图表组件**:复用首页 _lwSetup 轻量 SVG 引擎(app.js L17784,分时图/恐贪/A股情绪分已用),或移植 lab.js _labSimSVG(lab.js L1879 纯 SVG 净值曲线,含起始/最低/峰值/期末标签+虚线基准线)。**不新造轮子。**

## 二、逐维度证据与结论

### 维度1:表格结构
- 弹窗打开:_openSimBacktestModal app.js L3771;innerHTML 每次打开全量重建,L3798 起 header「📊 模拟回测 · 全历史真实过滤」。
- 筛选条:L3808-3845 时间范围起止(默认最近30天)/交易模式下拉/长线管位·G/H/I 开关/持仓中提示。
- 表头 14 列(app.js L4979-4982):日期/当日持仓/当日信号/信号关联ETF/计划买入时间/买入手续费/计划卖出时间/卖出手续费/本笔交易盈亏%/本笔盈亏金额/累积盈亏/累积金额/累积对错/峰值同时持仓笔数。
- 汇总行(app.js L5028-5033):筛选结果 N 笔 · 本金每笔 ¥10000 · 长线管位·G/H/I 开关 · 累积收益率口径=累计金额÷(峰值同时持仓笔数×¥10000) · 费率档 · 含持仓中 N 笔 · 强平日缺价 N 笔。
- 分页 PAGE=500(L4944);数据加载 _simRenderOnce(L3983)→_simRenderTable(L4871)。

### 维度2:交易字段
- trades 字段清单(static-site/data/signal_kelly_trades.json fields,共 24):signal_date/index_id/signal/buy_date/sell_date/etf_code/etf_name/track_tier/track_score/match_method/track_low_confidence/buy_price/sell_price/shares/profit/return_pct/hold_days/sell_reason/current_price/market_state/market_tier/market_tier_all/market_tier_cyb/rating。
- 后端自带:买/卖日期、金额(buy_price/sell_price/shares/profit)、持仓天数、ETF 代码/名、信号类型、信号分/评级/市场状态、current_price(持仓中最新收盘)。
- 前端运行时算:_simBtCalcRow app.js L5185(buyFee/sellFee/pnlYuan/pnlPct,按用户费率档 fp 重算;双滑点修复 L5188 buy_price÷(1+0.001)还原真实净值)。G/H/I 强平行走 _simBtCalcRowRealForce L5213(共享核 accum_nav 真实净值重算)。
- 缺价行:真实净值缺失标 _gihNavMissing(app.js L3732/L3743),渲染层「— 缺价」红字、不计入统计。

### 维度3:净资产公式(核心难点)
- **trades 无逐日持仓明细/逐日净值字段**(字段清单见维度2,仅逐笔成交)。→ 必须前端按成交日期重建逐日持仓序列。
- accum_nav_map.json 结构:1541 只 ETF,每 ETF 中位数 365 天,日期并集 5231 天,范围 20050223~20260828,末日期 **20260828**。字段=etf_code → {YYYYMMDD: 净值}。
- 可复用:弹窗 G/H/I 管位已加载 accum_nav_map(common.js L1226 _kkellyRealNavEnsure,单例缓存 window._kkellyRealNav,`_simRenderOnce` L4226-4228 已 await),走势图直接复用不重复拉取。
- 复刻脚本已跑通:docs/kelly/analysis/sim-netasset-equity-chart-20260901/scripts/netasset_daily_repro.py(与原 app.js 管线同构:K 选样→GHI 管位→日期切片→峰值扫描,§3.2 对账铁律)。H 档 K=1 窗口 20250901~20260831 实测:
  - 信号 1843 → K1=197 → 管位后 58 | 峰值同时持仓=5 笔 → 初始资金=50000 元(H 档 5 万起步,与用户口径一致)
  - 曲线 241 点,区间 20250901~20260828;期末净资产 46886.46 = 现金 -1505.09 + 市值 48391.56(5 笔)
  - nav forward-fill 笔次=0(窗口内持仓 ETF 的 nav 全覆盖)
- **⚠️ 对账差异根因(诚实标注)**:脚本对账「净资产末 == 初始+cumYuan+(期末市值-按current_price市值)」输出差 -27770.11 ✗。逐笔核查根因:**trades generated_at=2026-09-04 02:17(含 sell_date=20260902 的 3 笔卖出),而 accum_nav_map.json 生成于 2026-08-30、末日期 20260828**——nav 数据滞后于 trades,这 3 笔在曲线日历中永远等不到卖出日,被曲线当作「仍持仓」计市值,但前端 cumYuan 已按已卖出计入。**不是公式错误,是数据版本时间差**。实施时须:曲线截断到 nav 末日(20260828)作为末点,或对 sell_date>nav 末日的笔按 current_price/sell_price 特殊处理,并在 UI 标注「曲线数据截至 X」。
- **初始资金口径(一句化)**:曲线起点=窗口峰值同时持仓笔数×¥10000(H 档管位开=5 笔=5 万;与累积盈亏%分母完全一致,§22)。

### 维度4:数据源
- trades 文件:static-site/data/signal_kelly_trades.json(72MB 全量,2011-2026);分片 signal_kelly_trades_parts/recent.json(热区,20260702~20260831)+ t2011~t2026.json(按年)。前端 _simRenderOnce 打开只拉 recent.json 秒开,超热区按年并行拉,失败回退全量(app.js L3557-3633)。
- **走势图数据来源结论**:不用新 JSON 文件,前端从「已渲染的 kept rows(管位后+切片后)」重算逐日净资产;nav 用弹窗已加载的 accum_nav_map。理由:①trades 是逐笔成交无逐日快照,必重算 ②kept rows 已按 K 档/管位/切片过滤,曲线与表格同源(§22 一致性)③不新增请求不拖慢弹窗。
- 粒度:逐交易日(持仓 ETF 的 nav 日期并集∩窗口),年窗口≈240 点、全史约 5200 点,数据量几 KB~几十 KB,体积可控(2026-08-22 分片加载先例 app.js L3217/L3633 已验证单 JSON 不超 3MB 秒开)。

### 维度5:图表组件(复用,不自研)
- **首页 _lwSetup**:app.js L17784 轻量 SVG 引擎,支持 line/area/markLine/markArea/tooltip,分时图(app.js L12421)、恐贪、A股情绪分、overfit 均已用。可直接复用渲染净资产曲线(line + area 渐变 + markLine 虚线=初始本金)。
- **lab.js _labSimSVG**:lab.js L1879 纯 SVG 净值曲线,含起始/最低/峰值/期末标签 + 虚线基准线 + 峰值/期末圆点,是现成「净资产曲线」范本,可移植到 app.js(纯字符串拼接无依赖)。lab 页模拟回测已用它(lab.js L2084「📈 净值曲线(虚线=初始本金)」)。
- 结论:复用 _lwSetup 或移植 _labSimSVG(二选一,前者与首页外观统一、后者自带 4 点标签)。不引第三方库、不新造。

## 三、回归面(3 类关注点+验证方式)
1. **表格逐笔数字/累积盈亏口径(§22 一致性)**:走势图是纯新增展示,不改 _simBtCalcRow/cumYuan/峰值扫描任何一行。曲线从 kept rows 派生,与表格同源同 K/管位/切片口径;曲线初始资金=峰值同时持仓×10000,与累积盈亏%分母逐位一致。验证:开弹窗后对比「汇总行峰值同时持仓」与「曲线初始资金」=同值。
2. **弹窗分片加载性能**:曲线重算只在 kept rows(已加载分片)上跑,不新增 fetch;nav 复用 G/H/I 管位已 await 的 _kkellyRealNavEnsure 单例(common.js L1226),管位关时也可按需延迟加载。验证:打开弹窗、切热区/超热区范围、切 K/模式/费率,网络面板无新增请求;曲线渲染在 _simRenderTable 之后同步完成不白屏。
3. **G/H/I 长线管位开关行为**:管位开关改变 kept rows(超容剔除/腾位改写卖出日),曲线必须跟随 kept rows 重算(与表格同数据)。管位开=初始资金=峰值5笔×10000=5万;管位关=raw 峰值。验证:开关切换后曲线首点初始资金与汇总行峰值笔数同步变化,无旧曲线残留。

## 四、已验证方法/数据源清单
- 数据产物层:signal_kelly_trades.json(逐笔成交,无逐日快照)、signal_kelly_trades_parts/recent.json(热区 20260702~20260831)+t2011~t2026、accum_nav_map.json(1541 ETF 逐日净值,末日 20260828)、signal_kelly_backtest.json(模式参数)。
- 渲染层:app.js L3771/L4871/L4979/L5028/L5185/_lwSetup L17784;lab.js L1879 _labSimSVG;common.js L1226 nav 加载。
- 复刻脚本:docs/kelly/analysis/sim-netasset-equity-chart-20260901/scripts/netasset_daily_repro.py 已跑通(H 档 K1 实测输出见上)。

## 五、方案推荐(按 §5 默认准则,一步到位)
- **实现位置**:在弹窗 `<div class="sim-table-wrap">` 上方(表格与汇总之间)插入 `<div class="sim-netasset-chart">`;在 _simRenderTable 内 kept rows 就绪后调用 `_simRenderNetassetChart(modal, kept, fIdx, nav)` 生成。
- **曲线口径**:逐交易日打点;首点=初始资金(峰值×10000);每点 {date, value, holdings, cash, mv};末点截断到 min(nav末日, 窗口末日),sell_date>nav 末日的笔按 current_price 计市值并 UI 标注「含持仓中笔按最新收盘」。
- **防前视**:只用 t 及 t 之前的数据(买入价还原真实净值、卖出用当日 nav),不引入未来收盘。
- **图表**:复用 _lwSetup(line+area+markLine 初始本金虚线)或移植 _labSimSVG(4 点标签)。

## 复现
- 脚本:docs/kelly/analysis/sim-netasset-equity-chart-20260901/scripts/netasset_daily_repro.py
- 输入依赖:static-site/data/signal_kelly_trades.json、static-site/data/accum_nav_map.json
- 重跑命令:`cd docs/kelly/analysis/sim-netasset-equity-chart-20260901 && python3 scripts/netasset_daily_repro.py H 1 20250901 20260831`(参数=模式 K 起日 止日;数据版本 trades=2026-09-04 02:17 / nav 末=20260828)
- 关键口径一句化:净资产(日)=现金+持仓市值;现金=初始-Σ开仓本金+Σ卖出净额(PRIN+费后盈亏);市值=Σ未平仓份额×当日accum_nav(缺日向前取);初始=峰值同时持仓笔数×¥10000(H 档管位开=5笔=5万)。
- 已知局限(诚实标注):复刻脚本对账差 -27770.11 根因=3 笔 sell_date=20260902 > nav 末日 20260828 的数据版本时间差,非公式错误;实施时曲线末点须按 nav 末日截断或对尾段笔按 current_price 特殊处理。
