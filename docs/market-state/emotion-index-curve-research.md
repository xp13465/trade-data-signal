# 「可关联指数情绪分走势图」全站展示位调研(2026-08-19, 只读)

> 前置调研,供实施「情绪分走势图叠加对应指数曲线」定位用。纯读代码,未改任何文件。
> 判据(用户定义):情绪分**名字明确对应单一指数**才叠曲线(如「科创50情绪分」→ 科创50指数);综合类(恐贪/综合情绪分/跨市场)不叠。

## 1. 情绪分 9 类分类结论

| 情绪分 id | 名称 | 是否明确对应指数 | 对应指数 id | 指数名 |
|---|---|---|---|---|
| `sentiment_sz50` | 上证50情绪分 | ✅ | `sz50` | 上证50 |
| `sentiment_hs300` | 沪深300情绪分 | ✅ | `hs300` | 沪深300 |
| `sentiment_csi500` | 中证500情绪分 | ✅ | `csi500` | 中证500 |
| `sentiment_csi1000` | 中证1000情绪分 | ✅ | `csi1000` | 中证1000 |
| `sentiment_cyb` | 创业板情绪分 | ✅ | `cyb` | 创业板指 |
| `sentiment_kc50` | 科创50情绪分 | ✅ | `kc50` | 科创50 |
| `a_sentiment` | A股综合情绪分 | ❌ | — | 6项A股指标加权,非单一指数 |
| `cross_market` | 跨市场综合评分 | ❌ | — | A股+港股+全球等多维等权 |
| `fear_greed` | 恐贪指数 | ❌ | — | 综合5类市场情绪 |

- 索引锚点:`_INDEX_NAME_MAP` static-site/app.js L1259-1310(指数名 `kc50:'科创50'` 与情绪分名 `sentiment_kc50:'科创50情绪分'` 并存);`indexIdToName` L1364-1368(去 `s.`/`g.` 前缀查表)。
- **id 映射规则**:情绪分 id `sentiment_{idx}` → 对应指数 id 即去 `sentiment_` 前缀 = `{idx}`(6 个全命中 _INDEX_NAME_MAP 宽基表 L1261-1262)。

## 2. 可关联指数情绪分走势点清单(4 类展示位)

### 展示位 A:信号弹窗走势卡(用户点名①「情绪弹窗的走势卡」)
- **渲染函数**:`openSignalChartModal()` s.* 分支,static-site/app.js **L6113-6126**(读 `sentiment-all.json[key]` → `chartData=[{date,value}]`);图表绘制 `isValue=true` → `valueChartWithSignals()` **L6244**。
- **情绪分类型**:全部 9 类 s.*(其中 6 宽基可关联)。冰点模式追加 ≤20 蓝 pin(L6149-6153,freeze 蓝不动)。
- **对应指数**:6 宽基 → sz50/hs300/csi500/csi1000/cyb/kc50。
- **数据源**:
  - 情绪曲线:`sentiment-all.json[key]`(`dataUrl` L5015 对 `-all` 走 R2 `/r2/` 代理)。
  - 指数曲线(待叠加):`index/{指数id}-all.json` 的 `ohlc` 字段(全史,如 `index/kc50-all.json` 1607 条;实盘文件已存在 sz50/hs300/csi500/csi1000/cyb/kc50 全在,见 static-site/data/index/)。
- **入口(共享同一弹窗,全走 s.* 分支)**:
  1. 首页冰点日卡点击:main 上 `renderOverview` freezeCard L11834-11840 → `openSignalChartModal(item.dataset.idx="s.{score_id}", "freeze", ...)`。
  2. 市场温度页情绪分信号列表点击:`renderSentimentSignalList` L18396-18401 → `openSignalChartModal(item.dataset.idx, ...)`(idx=`s.sentiment_*` 或 `s.fear_greed` 等)。
  3. 首页近 90 日情绪日历点击(feat/ice-sentiment-calendar-front 分支):`_renderSentimentCalendar` 冰点格/信号格 data-idx=`s.*`(该分支 L3037,click 委托沿用首页 .sig-clickable → 同上弹窗)。
- **与在跑任务重叠**:⚠️ **与 #19 共享该弹窗,但 #19 未改弹窗本体**。`git diff main feat/ice-sentiment-calendar-front -- static-site/app.js` 只改了 renderOverview 的 freezeCard 渲染区 + 新增 `_renderSentimentCalendar`(见 §4)。实施改 s.* 分支的绘制逻辑 = 同时让 #19 新日历点击也叠加指数(正是用户要的),**不冲突**;但若改 renderOverview 本体 → 与 #19 冲突,需错开。

### 展示位 B:市场温度页 6 宽基情绪分卡(用户点名②「市场温度页的情绪走势卡」)
- **渲染函数**:`renderSentimentMarketTemp()`,static-site/app.js **L18151-18199**(`idxNames` 6 宽基循环,每卡 `valueChartWithSignals(title, data, sig[key], {visualMap}, stats[key], strat[key], key, cell)` **L18167-18180**;图表高度 240 + 冰点/过热阈值线 L18182-18188)。
- **数据源**:
  - 情绪曲线:`sentiment-{state.range}.json[key]`(L18009)。
  - 指数曲线(待叠加):`index/{指数id}-all.json`。
- **重叠**:无。#19/#73/#12 均未动此函数。

### 展示位 C:KPI 详情弹窗走势图(举一反三新增,用户未点名但同判据适用)
- **渲染函数**:首页 6 宽基情绪分小卡 → `openKpiDetailModal()` static-site/app.js **L6526-6651** → `_loadKpiHistory()` sentiment 分支 **L6344-6363**(读 `sentiment-{period}.json[kpiId]`,返回 `series:[{name,data}]` + visualMap 5 段着色)。
- **小卡渲染/点击**:KPI 卡 L11478(`data-kpi-id`),点击绑定 L11497(移动)/L11510(PC)→ `openKpiDetailModal(c.dataset.kpiId)`。
- **数据源**:情绪 `sentiment-{period}.json[kpiId]`;指数曲线 `index/{指数id}-all.json`。
- **重叠**:无。
- **实施友好度**:`_loadKpiHistory` 已返回 series 数组,`openKpiDetailModal` seriesOpt 已是多系列(L6589-6616),`_kpiLiteCfg`(L13957)已支持多系列循环(series+legend)——**叠加第二系列成本最低**,仅需扩展 y 轴双轴。

### 展示位 D:情绪分买卖点信号列表(非走势卡,但点击落点在 A)
- `renderSentimentSignalList` static-site/app.js L18352-18402,列表本身不是走势图,点击弹 A 的走势图。纳入范围 = A 的处理自动覆盖。

## 3. 不可关联(不需要加曲线)清单

| 展示位 | 渲染位置 | 排除原因 |
|---|---|---|
| 恐贪指数卡(市场温度页) | renderSentimentMarketTemp L18040-18113(`valueChartWithSignals` L18047) | 综合5类市场情绪,非单一指数 |
| A股综合情绪分卡(市场温度页) | L18115-18150(`valueChartWithSignals` L18121) | 6项A股指标加权,非单一指数 |
| 跨市场综合评分卡(市场温度页) | L18200-18233(`valueChartWithSignals` L18206) | A股+港股+全球等多维等权 |
| 恐贪分项条 | L18082-18111(恐贪卡下方 8 项横向进度条,含 6 宽基分项) | 非走势图(横向进度条),不适用叠加 |
| 指数情绪冰点/过热热力图 | renderSentimentHeatmap L18238-18344 | 热力日历矩阵(X=日期,Y=指数),非折线走势图,不适用叠指数曲线 |
| 首页 KPI 卡:恐贪/综合/跨市场小卡 | KPI_HISTORY_SOURCE L6264-6266 | 同上 3 个综合类,不可关联 |
| lab.js | 无情绪走势渲染(grep 仅回测结论文案) | 不涉及 |

> 实施注意:上面 3 个综合类在**展示位 A(信号弹窗)与 C(KPI 弹窗)同样存在**,实施叠加逻辑时须按 `indexId` 白名单(6 个 `sentiment_*`)判断,不能全局叠加。

## 4. 与在跑任务区域隔离(关键)

| 在跑任务 | 改动区域 | 与情绪走势卡的关系 |
|---|---|---|
| #19 首页近90日情绪日历(feat/ice-sentiment-calendar-front @8abefd7c2) | `git diff main feat/ice-sentiment-calendar-front`:①renderOverview freezeCard 渲染区(app.js L11822-11864)+49 行 ②新增 `_renderSentimentCalendar`(该分支 L3037) | ⚠️ 只改 renderOverview 渲染区 + 新增函数,**未动** openSignalChartModal / valueChartWithSignals / renderSentimentMarketTemp / _loadKpiHistory。实施改 A/C 的绘制逻辑不冲突;#19 新日历点击落 A 弹窗,叠加后行为一致(正是用户要的)。**禁止实施改 renderOverview 本体/freezeCard 区**(会撞 #19) |
| #12 renderOverview 生命周期/新闻区(保留给 #12) | renderOverview 内(新闻区 _homeNews*) | 不重叠:实施只动情绪走势卡绘制,不动 renderOverview 本体/新闻区 |
| #73 indexChart tooltip 四档色带(commit 7872cccbf 已 merge main) | indexChart() L4584(yAxis 数组 L4650 + yAxisIndex:1) | 不重叠:indexChart 是普通指数卡走势图,情绪叠加曲线**不调用 indexChart**。约束「不碰 indexChart」已注意 |

**共享函数注意**:`valueChartWithSignals` 被 6 处调用(L6244 信号弹窗 / L15466 全球extras / L18047 恐贪 / L18121 A股综合 / L18167 6宽基 / L18206 跨市场)。若实施在该函数内做叠加,必须按 `indexId` 白名单(6 个 `sentiment_*`)判断,全球指标(extras)/恐贪/综合/跨市场不可叠加。

## 5. 数据源汇总与 id 映射

- 情绪曲线:`sentiment-{period}.json[key]`,元素 `{date:'YYYYMMDD', value, is_freeze, is_overheat, components}`(已验证 sentiment-3m.json sentiment_kc50 64 条)。
- 指数曲线:`index/{指数id}-all.json.ohlc`,元素 `{date, open, high, low, close, pct_change, amount}`(已验证 index/kc50-all.json 1607 条全史)。
- 获取:`dataUrl()` app.js L5015 —— `-all` 命中 `_R2_LARGE_RANGE` 走 `_R2_DATA_BASE`(/r2/ 代理);普通周期文件走 `./data/`。指数曲线叠加需同样经 dataUrl(`index/kc50-all.json` 属大 range → R2)。
- **⚠️ 空壳陷阱**:static-site/data/index/ 下存在 `s.sentiment_*-all.json` 6 个文件,但它们是**空壳**(ohlc=[] 空数组,只含 signals/stats/strategy/etfs 统计),**不是**指数价格曲线。真实指数曲线 = `index/{宽基id}-all.json`(如 index/kc50-all.json),两者勿混。

## 6. 实施可行性观察(供实施 agent 参考,非本调研结论)

- 4 类展示位目前都是**单系列 + 单 yAxis(情绪 0-100)**;叠加指数曲线量级差异大(情绪 0-100 vs 指数 1000-4000),需**双 yAxis**(左=情绪分 0-100,右=指数价格)。
- echarts 双轴先例:indexChart L4650(yAxis 数组 + series yAxisIndex:1)、L12266/12404(腾落线右轴)、L14876(收盘价+成交额双轴)。
- 轻量 SVG 引擎:默认 `charts.lightweight=true` 走 `_lwSignalLiteCfg`(L4827)/`_kpiLiteCfg`(L13957)。`_kpiLiteCfg` 已支持多系列;**`_lwSignalLiteCfg` 当前单 series + ys 单轴,叠加指数需扩展轻量引擎多系列+双 yAxis**(这是最大实施工作量点)。
- 展示位 C(KPI 弹窗)因 `_kpiLiteCfg` 已多系列,实施最轻。

## 7. 约束提醒(实施时)

- 不碰 `indexChart`(L4584,普通指数卡走势图)。
- 不碰 `signalColor`/`signalLabel`/freeze 蓝(信号 pin 语义,只新增指数曲线 series,不改 pin)。
- 不碰 `_homeNews*`(#12 保留区)。
- 数据一致性(§22):情绪与指数曲线同日期对齐(都是 YYYYMMDD),叠加时按日期 key 合并;指数曲线数据截止日可能与情绪不一致(全史 vs 周期),取交集即可。
- 落档:本文档 + README 索引已更新。

## 复现

- 只读调研,无脚本。证据点:`grep -n` 关键词 + `git diff main feat/ice-sentiment-calendar-front -- static-site/app.js` + 数据样例验证(见 §5)。
- 数据截止:static-site/data/ 当前版本(2026-08-19)。关键行号以 main 分支 static-site/app.js 为准(26890 行)。
