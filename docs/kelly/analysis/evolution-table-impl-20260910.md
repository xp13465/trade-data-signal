# 演进弹窗·表格视图实施报告(方案B 前端实时重算, 2026-09-10)

## 一、需求与路线

- **需求**:信号凯利回测「📈 演进」弹窗新增**表格形态**= 日期行 × A/B/C/D/E/F/J/G/H/I 十种卖出模式列, 每格两行小字(累计净利元 + 峰值资金收益率%, ±着色), 按时间排列的快照。
- **路线 = 方案 B 前端实时重算**:表格数字不复读后端静态主档 `sig_main`(快照按当日全量重算落盘、改参数不跟随), 而是浏览器端直接从 `state.labSigKellyTradesData`(16 片渐进合并后的全量 trades)复用全信号卡同引擎重算——**目标 = 表格「末行/每格数字」与全信号卡「最后结果」逐位一致**。
- **历史行口径 = 截至该日已平仓(closed-by-D)**:每个买入日轴点 D 的行 = 到 D 为止已平仓(非空 sell_date ≤ D)的累计净利 + 峰值资金收益率(= 前缀累计净利 ÷ 前缀峰值资金 × 100)。已平仓卖价 = 历史收盘价固定 → 历史行天然稳定, 不受后期调档/快照重建影响。

## 二、实施内容(前端两文件 + 公示两文件)

| 文件 | 改动 |
|---|---|
| `static-site/lab.js` | ①`_labKellyEvoModalHTML` 改造:Tab「📊 曲线 / 📋 表格(按日快照)」+ 粒度「近60行/全史」+ 口径行 + 表格占位;②`_labKellyEvoOpen` 改 async(先 fetch index.json 再渲染);③新增 `_kellyOperationalPool()`(与 `_kellyApplyFeeRecompute` 同引擎同口径的 per-mode 过滤+费率重算链);④新增 `_kellyEvoSegForClosed()`(线段树区间加维护峰值资金, O(n log n));⑤新增 `_labKellyEvoTableBuild()`(轴点扫描 + closed-by-D 指针前缀);⑥新增 `_labKellyEvoBuildTable()`(门控 `_labKellyAllReady` 未就绪显示占位+自动补建);⑦新增 `_labKellyEvoRenderTable()`(渲染表格 + 📌 当前全量末行 + 污染日「—」);⑧新增 `_labKellyEvoCaliberHTML()`(口径标注行) |
| `static-site/lab.css` | 演进弹窗 max-width 980px + tabs/granbar/caliber/table-wrap/date/cell/polluted/pin-row 样式 |
| `static-site/purpose-notes.js` | `lab.sigkelly` 尾部补「演进表格视图(2026-09-10)」口径说明段(§21 公示) |
| `README.md` | 演进弹窗 bullet 补表格视图描述 + 报告链接(§23.1) |

## 三、口径与实现要点

- **数据源**:`state.labSigKellyTradesData`(signal_kelly_trades.json 16 片渐进合并全量, generated_at 2026-09-10 08:24, 字段 26 个, dedup 唯一交易 45732)。
- **入样宇宙**:评级三区(high+mid+low)并集(`quadsAll`), 与主引擎逐字同构。
- **降亏基座**:默认 S06 动态基座——按每笔 signal_date 取当日 `_tdsS06FiltersForDate` 的 effective_mode(a9/new14), 与全信号卡同一谓词 `passesFade`(fail-open + out_of_range_fallback 兜底计数一致, 表格 foot 展示 fail-open 警示行)。
- **AI仓位建议**:`positionCap` 开时按 K 档取 kept(passFade + 排序候选池), 每日只买最优 K 笔、每日资金池 1 万等分(`_kellyPerTradeAmount`);K 档读数随上方 toggle 联动。
- **费率**:`state.labSigKellyFeeParams`(默认 etf_main 主流费率), 走同一 `_kellyRecomputeTrade` 缓存。
- **G/H/I(长线)**:GIH 开时 `passesFadeNoBull`(基座键集 − bullAuxBackupStop) + `_kellyAihlineApply().real`(与卡 `__gihb1` 同源);GIH 关时走普通全量(与卡 G 模式口径一致)。
- **轴点**:池内全部(含未平仓)交易的唯一 buy_date 跨模式并集升序(实测 582 个)。
- **峰值资金**:`_kellyEvoSegForClosed` 线段树区间加 [idx(buy_date), idx(sell_date)) + amount, 全局 max = 树根——与 `_kellyMaxConcurrentCapital` 同日先减后加语义逐位一致。
- **末行「📌 当前全量」**:直接读 `state.labSigKellyFeeStats.all.all[modeKey]`(GIH 开时 `modeKey + "__gihb1"`), 保证与全信号卡逐位一致;缺失才从池内全量现算兜底。
- **污染日**:从 `signal_kelly_snapshots/index.json` days 的 polluted 标记取(如 2026-09-08 G/H/I tr:null), 轴点落集合显示「—」+ title「污染日已拦截」。
- **防前视**:历史行只累计已平仓(sell_date ≤ D)、卖价=历史收盘固定;当前全量行读卡 stats 含未平仓按最新价预估——两条都在 t 时刻可见信息内, 无后视。
- **性能**:全史 582 轴点 × 10 模式实测 954ms(第 1 次拉取含 S06 快照 ensure, 二次打开同理), 可接受;粒度默认「近60行」防首渲长表。

## 四、自测对账结果(Playwright 无痕, 拦截外部网络)

- **末行「📌 当前全量」 vs 卡 total_profit/return_pct_max_holding 逐位一致**:A +163,367 / +163.37%、E +78,972 / +157.94%、G +148,030 / +148.03%、H +112,334 / +224.67%、I +145,051 / +161.17%(G/H/I 对 `__gihb1`)——**5 模式全 OK**。
- **重开弹窗末行稳定**:两次打开表格末行 p/r 逐字段一致 OK。
- **全史粒度**:583 行(= 582 轴点 + 1 pin 行), 首行 2011-02-21。
- **耗时**:实时重算 954ms。
- **G/H/I 行量级**:G/H/I 各对 `__gihb1` 与卡逐位一致(G +148,030/H +112,334/I +145,051), 量级一致。
- 测试脚本 = `docs/kelly/analysis/scripts/evolution-table-verify.cjs`(Playwright 无痕浏览器, 重建命令见「## 复现」)。

## 五、诚实标注

1. 表格是全新增视图, 不改任何既有功能(曲线 Tab/演进入口/快照生成链不动), §23.7 纯新增。
2. 历史行 = 截至该日已平仓(未平仓不累计), 与「当前全量(含未平仓预估)」是两种语义, foot + 列 title 均已标注; 若用户希望历史行也含未平仓 MTM 可在后续版本切换。
3. 582 个轴点是 K=1 每日池口径下跨模式并集的买入日数(非全部 45732 笔信号的 signal_date 数); 切 K=2/3/4 或关 positionCap 轴点数随之上涨, 表格自动跟随。
4. 污染快照日仅 index.json 显式 polluted 标记的日期(当前=20260908)拦截; 未标记的历史快照日按当时数据正常累计。

## 六、举一反三(§23.3)

- **同一数据源消费点**:`signal_kelly_snapshots/index.json` 消费点全在演进弹窗内(曲线 Tab + 新表格 Tab 污染日标记), 无第三方展示位;`latest_posrating.json`(首页 K 档评级)是另一产物文件, 不共用, 未受影响。
- **同引擎其它展示位**:全信号卡/模式卡/交易记录弹窗仍是 `_kellyApplyFeeRecompute` 主入口消费链——本次表格**只读**复用该引擎结果与缓存, 未改动主入口任何内部逻辑, 卡片数字零影响。

## 复现

- **实现文件**:`static-site/lab.js`(演进弹窗区 L10175-10740 + `_kellyOperationalPool` L10297-10488)、`static-site/lab.css`(L1380-1413)、`static-site/purpose-notes.js`(lab.sigkelly 尾部)、`README.md`。
- **验证脚本**:`docs/kelly/analysis/scripts/evolution-table-verify.cjs`(死脚本, 一次性对账)。
- **输入依赖**:`static-site/data/signal_kelly_trades.json`(74MB, generated_at 2026-09-10 08:24)、`static-site/data/signal_kelly_snapshots/index.json`(20260904-20260910 7 快照日, version 1.0)、`static-site/data/signal_kelly_backtest.json`。
- **重跑命令**(一行):
  ```
  cd <repo>/static-site && python3 -m http.server 8898 & (另开终端) cd docs/kelly/analysis/scripts && node evolution-table-verify.cjs
  ```
  (脚本内已内置本地 http 服务地址 8898, 运行前需 `static-site/data` 指向真实数据、`node_modules/playwright` 可用; 脚本会拦截外部网络并用工作区 lab.js/app.js 源码, 离线可跑。)
- **数据截止日期**:signal_kelly_trades.json generated_at = 2026-09-10 08:24; 快照 index.json 更新至 20260910。
- **关键口径一句话**:买入=全信号(评级三区并集)经 S06 动态基座(按 signal_date 取 a9/new14)+AI仓位建议 K=1 每日只买最优 1 笔、每日资金池 1 万等分、ETF 主流费率重算; 表格历史行=截至该日已平仓(sell_date ≤ D)累计净利 + 峰值资金收益率, 末行=当前全量含未平仓按最新价预估、与全信号卡最后结果逐位一致。