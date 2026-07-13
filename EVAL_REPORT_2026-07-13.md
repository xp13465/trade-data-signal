# 站点全面评估报告 · 2026-07-13

> 范围：web/ + static-site/ 前端双版 + app/ 后端 API。只读调研，不改代码。
> 评估基线：web/app.js (2689行) + web/lab.js (2260行) + web/index.html + static-site 对应文件 + app/main.py + static-site/export.py + data/。

## 严重度说明
- **P0 阻断**：功能不可用/数据错误/崩溃，必须立即修
- **P1 重要**：影响核心体验或存在数据准确性风险，应尽快修
- **P2 一般**：体验瑕疵/性能问题/边界处理不足，可排期修
- **P3 优化**：代码质量/一致性/小优化，有空再做

---

## 一、概览 Tab（overview）

### O1. [P1] 位置感卡片依赖均线排列卡片成功才加载
**问题**：`renderOverview` 中 `fetchJSON("/api/position")` 嵌套在 `fetchJSON("/api/ma_alignment").then()` 内部（app.js:1143 在 1115 的 .then 块里）。若 `/api/ma_alignment` 失败（外层 `.catch(function(){})` 吞掉错误），`/api/position` 永远不会发起请求，位置感卡片静默消失，用户无任何提示。
**建议**：两个 fetch 应独立并行（Promise.all 或各自 `.then().catch()`），互不依赖。

### O2. [P2] 多处静默吞错（blank card 无提示）
**问题**：overview 有 3 处 `.catch(() => {})`/`.catch(function(){})`（行 890 summary 横幅、1170-1171 ma_alignment+position、728 频率统计）。AD Line（1184 try/catch 静默）和 volume_ratio（1220 try/catch 静默）同理。任一失败用户只看到空白列，不知是"无数据"还是"加载失败"。
**建议**：失败时渲染轻量错误占位（如"数据加载失败，点此重试"），与空数据 `empty-note` 区分。

### O3. [P3] 分享图重复请求 overview
**问题**：`openShareModal`（行 2603）每次点分享都重新 `fetchJSON("/api/overview")`，即使概览页已加载过同样数据。
**建议**：复用已缓存的 overview 数据，或缓存分享 canvas。

---

## 二、大盘 Tab（market）

### M1. [P2] 全球子 tab 逐个串行请求指数信号
**问题**：`renderGlobal`（行 1406-1409）对 `r.indices` 逐个 `await fetchJSON(/api/index/${id}...)`，4 个美股指数 = 4 次串行请求，移动端慢网络叠加延迟明显。A股/港股子 tab 用了 `renderIndicesSection`（局部刷新+缓存），全球 tab 没复用此模式。
**建议**：改用 `Promise.all` 并发，或复用 `renderIndicesSection`。

### M2. [P3] renderGlobal 对 r.indices 无 null 守卫
**问题**：行 1406 `Object.entries(r.indices)`，若 API 返回异常（indices 为 null）直接抛错。renderTab 的 catch 兜底显示"出错了"，但错误信息不友好。
**建议**：加 `r.indices || {}` 兜底 + 空数据提示。

### M3. [P2] 北向资金数据冻结提示仅在分组 hint，KPI 卡片无说明
**问题**：KPI 卡片（行 932 `isStaleMetric` 判断 >30 天停更则隐藏）对北向资金直接隐藏。但 a-stock tab 的资金面分组 hint 明确说"北向资金 2024-08 起停更，1 年窗口内为空属正常"。两处处理策略不一致：概览隐藏、大盘 tab 显示空图+hint。
**建议**：统一策略——要么都隐藏，要么都显示带"已停更"标签。

---

## 三、综合情绪 Tab（sentiment）

### S1. [P2] 期货数据单独串行请求
**问题**：`renderSentiment`（行 1504）在情绪图渲染完后才 `await fetchJSON("/api/futures")`，是串行的额外往返。期货数据与情绪数据无依赖关系。
**建议**：与 `/api/sentiment` 并行请求（Promise.all）。

### S2. [P3] 信号频率"月均"用当前月份计算，年初误导
**问题**：`/api/signal_freq` 后端（main.py:955）`monthly_avg = round(year / max(cur_month, 1), 2)`。1 月查看时 monthly_avg = 全年次数/1 = 全年次数显示为"月均"，数值虚高。
**建议**：改为按已有数据月份计算，或标注"今年 X 月均"。

### S3. [P2] 冰点/过热热力图日期标签可能过密
**问题**：`renderSentimentHeatmap`（行 1574）`labelInterval = Math.floor(dates.length/10)`，全历史时 dates 可达数百个，即便 interval 取整，45° 旋转的日期标签在窄屏仍可能重叠。
**建议**：限制标签数量上限（如最多 10 个），或改用 dataZoom 交互。

---

## 四、行业概念 Tab（industry）

### I1. [P1] 行业搜索每次输入都重新请求全量 API
**问题**：`industrySearchBar`（行 565-571）oninput 防抖 250ms 后调 `renderTab()` -> `renderIndustry()` -> `_loadIndustryData()` -> `fetchJSON(/api/industry?range=...)`。每次搜索都重新请求整个行业 payload（"all" range 含 31 行业+27 概念的全历史 OHLC+signals+stats+fund_flow+turnover+width），并重新渲染全部 mini 图表（58+ 个 ECharts 实例）。
**对比**：大盘 tab 的 `renderIndicesSection` 正确做了缓存（signalsCache 闭包级缓存，筛选只局部刷新不 refetch）。行业 tab 没复用此模式。
**建议**：缓存 `r`（industry 响应），搜索时只调 `filterIndicesByName` + `renderIndustryGrid` 局部刷新，不调 renderTab/refetch。

### I2. [P3] 概念板块无搜索筛选
**问题**：`industrySearchBar` 只加到申万行业区（行 2253），概念板块区（行 2264-2274）没有搜索条。27 个概念无法筛选。
**建议**：概念区也加搜索条，或共用一个搜索条同时过滤两区。

### I3. [P3] 行业锚点导航条无 scrollspy 高亮
**问题**：锚点按钮（行 2234-2242）点击后高亮，但滚动到另一区时不会自动切换高亮（无 IntersectionObserver/scrollspy）。
**建议**：加 scrollspy 让当前可视区对应按钮自动高亮。

---

## 五、策略实验室 Tab（lab）

### L1. [P2] 买卖信号弹窗始终下载全历史再前端切片
**问题**：`_labSignalModalRender`（lab.js:2031）总是 `fetchJSON(/api/index/${m.index}?range=all)`，即使选"近1年"窗口也下载全历史（sh: 4010 条），再前端切片。移动端 + 大指数（sh 1.2MB JSON）较慢。
**建议**：动态版按窗口传 range（后端支持 1y/3y/5y），静态版无 API 只能前端切（可接受）。

### L2. [P3] 实验图表窗口与模拟回测窗口互相独立
**问题**：实验图表用 `state.labChartWin`（默认 y5），模拟回测用 `state.labSimWindow`（默认 y1）。用户切了模拟回测窗口，实验图表窗口不联动。
**说明**：设计如此（两者语义不同），但用户可能期望联动。可加"同步窗口"开关。

### L3. [P3] 规则弹窗频率统计缓存不刷新
**问题**：`initRuleButton` 的 open 回调里 `freqDiv.dataset.loaded="1"` 后不再重新请求（行 726）。跨天后数据更新但弹窗仍显示旧频率。
**建议**：去掉 dataset.loaded 缓存，每次打开重新请求（频率接口很轻）。

### L4. [P3] 推荐榜弹窗 full 数据加载 15s 超时提示但仍等待
**问题**：`_labRankEnsureFull`（行 1868）15s 后显示"加载较慢"，但不取消请求，用户无"取消/重试"选项。
**建议**：加超时取消 + 重试按钮。

---

## 六、交叉检查

### X1. [P2] /api/new_high_low 端点+JSON 已生成但前端从未使用
**问题**：后端有 `/api/new_high_low`（main.py:724），static-site 有 `new_high_low.json`，但 web/app.js 和 lab.js 中 grep 不到任何引用。新高新低数据采了、算了、导出了，却没有任何 UI 消费——死端功能。
**建议**：要么在概览/大盘 tab 加"新高新低"图表（REQUIREMENTS 提过此功能），要么从采集流水线移除减少浪费。

### X2. [P3] _headers 缺 qr.js 的 immutable 缓存规则
**问题**：`static-site/_headers` 对 style.css/app.js/lab.js/lab.css/echarts.min.js 都设了 `immutable`，但漏了 `qr.js`。qr.js 改动后虽靠 `?v=` 破缓存能更新，但无 immutable 头导致每次都需 revalidate。
**建议**：_headers 加 `/qr.js` 规则，与 bump_asset_version.py 的 ASSETS 列表一致（该脚本已含 qr.js）。

### X3. [P3] 版本号基于 mtime 非 content hash，双版同内容不同版本号
**问题**：`bump_asset_version.py` 用 `os.path.getmtime` 生成版本号。style.css/lab.css/qr.js 双版内容完全一致（md5 相同），但版本号不同（web style.css=6a541f7c vs static=6a541f7d）。功能无碍，但无法通过版本号判断内容是否同步——若只改了 web/style.css 忘同步 static-site，两版版本号都会变但内容已漂移，无检测机制。
**建议**：改用内容哈希（如 md5 前 8 位），内容相同则版本号相同，便于一致性校验。

### X4. [P2] 错误处理策略不统一
**问题**：
- 顶层 renderTab：catch 显示"出错了：${e}"
- 子 fetch（summary/ma_alignment/position/ad_line/volume_ratio）：`.catch(() => {})` 静默
- 弹窗内（openSignalChartModal）：catch 显示"加载失败：${e}"
- 行业搜索：无错误处理
三套策略，用户体感不一致：有时看到红字错误，有时看到空白，有时看到 loading 转圈不动。
**建议**：统一错误处理工具函数，区分"网络错误/空数据/服务端错误"三类，分别给一致的 UI 反馈。

### X5. [P2] 静态版信号弹窗日期过滤基于"今天"而非数据末日
**问题**：静态版 `openSignalChartModal`（static-site/app.js 内）用 `new Date()` 减年份算 filterDate，而动态版把 range 传给 API（后端按数据末日算）。若数据滞后（如周末数据止于周五、今天周日），静态版 1 年窗口会比动态版多包含几天数据。差异小但不一致。
**建议**：静态版从 ohlc 末日回推算截止日（lab.js 的 `_labSignalCutoffDate` 已是此实现，可复用）。

### X6. [P3] 信号频率字段命名双轨
**问题**：全局 `/api/signal_freq` 返回 `{year, total, monthly_avg}`（前端读 `f.year`/`f.total`，app.js:722）；per-index stats 返回 `{year_count, total_count, monthly_avg, months}`（前端读 `f.year_count`/`f.total_count`，app.js:391）。两套字段名指同一概念，易混淆。
**说明**：后端 main.py:949 聚合时把 `year_count`→`year`、`total_count`→`total` 重命名了。功能正确，纯命名不一致。
**建议**：统一字段名（都用 year_count/total_count 或都用 year/total）。

---

## 七、用户近期反馈领域残留检查

| 反馈项 | 状态 | 说明 |
|---|---|---|
| 图表标题最新数值（全加+高亮） | ✅ 基本完成 | `latestSuffix`/`latestSuffixMulti` 覆盖 indexChart/lineChart/折线图/行业卡片。valueChartWithSignals 由调用方加 suffix（renderSentiment/renderGlobal/openSignalChartModal 均已加）。唯一例外：恐贪指数标题用 `latestSuffix(data)` 但恐贪标签在前，顺序略不同（非缺失）。 |
| 弹窗默认1年+周期切换 | ✅ 完成 | signalChartModal 默认 1y active + 1y/3y/5y/全历史 按钮（app.js:757）。lab signal modal 默认 y1 + all/y10/y5/y3/y1 按钮（lab.js:1997-1999）。 |
| 实验室窗口/指数切换联动 | ✅ 完成 | 模拟回测窗口切换时 `_labUpdateMatrixRowHighlight` 同步矩阵行高亮（lab.js:686/1411）。指数切换重置配对/分页状态后重渲染（lab.js:1675-1683）。 |
| 净值曲线每窗口独立起算 | ✅ 完成 | equity_curve 为 dict `{all,y10,y5,y3,y1}` 每窗口独立从 INITIAL_CAPITAL 起算（lab.js:590-598 `_labPairWinData` 按 win 取 ec[win]）。 |

**结论**：4 项近期反馈均已落实，无残留。

---

## 八、汇总

| 严重度 | 数量 | 编号 |
|---|---|---|
| P0 阻断 | 0 | — |
| P1 重要 | 2 | O1, I1 |
| P2 一般 | 9 | O2, M1, M3, S1, S3, L1, X1, X4, X5 |
| P3 优化 | 11 | O3, M2, S2, I2, I3, L2, L3, L4, X2, X3, X6 |
| **合计** | **22** | |

### 最严重的 5 条摘要
1. **[P1] O1 位置感卡片依赖均线排列成功才加载** — position fetch 嵌套在 ma_alignment 的 .then() 内，ma_alignment 失败则位置感卡片永不加载且无提示。修复简单（拆成独立 fetch）。
2. **[P1] I1 行业搜索每次输入都重新请求全量 API** — 每次搜索（防抖 250ms）重新 fetch /api/industry + 重建 58+ 个 ECharts。"all" range 下 payload 大、图表多，移动端卡顿明显。应缓存响应只做客户端筛选（大盘 tab 已有正确范式 renderIndicesSection）。
3. **[P2] X1 new_high_low 死端功能** — 后端采集+计算+导出全做了，前端零消费，算力/存储浪费。
4. **[P2] X4 错误处理策略不统一** — 顶层红字/子 fetch 静默/弹窗灰字三套策略，用户体感不一致，故障排查困难。
5. **[P2] M1 全球 tab 串行请求** — 4 个美股指数信号逐个 await，应 Promise.all 并发；与 A股/港股 tab 的 renderIndicesSection 模式不统一。

### 整体评价
站点功能完整度高，5 个 tab 均无半成品/占位符，双版同步机制（export.py + bump_asset_version.py + _headers）设计合理。近期反馈的 4 项（标题数值/弹窗周期/实验室联动/净值独立起算）均已落实。主要问题集中在：①错误处理一致性（静默吞错多）；②行业搜索性能（I1）；③个别 fetch 依赖耦合（O1）和串行化（M1/S1）。无 P0 阻断问题。
