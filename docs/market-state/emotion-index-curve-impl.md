# 情绪分走势图叠加对应指数曲线·实施落档(2026-08-19)

> 前置调研:`docs/market-state/emotion-index-curve-research.md`。实施新功能(只增不改既有展示默认行为),用户判据=情绪分名字**明确对应单一指数**才叠曲线。

## 1. 做了什么

给「能明确对应单一指数」的情绪分走势图,叠加对应指数价格曲线,对照情绪与指数走势。
- **可关联 = 6 宽基情绪分**:`sentiment_{sz50|hs300|csi500|csi1000|cyb|kc50}` → 对应指数 `index/{宽基id}-all.json`(ohlc 收盘价)。白名单过滤在数据源层统一判定。
- **综合类不叠**:恐贪 `fear_greed` / A股综合 `a_sentiment` / 跨市场 `cross_market` —— 不明确对应单指数,排除。

### 改动的展示位(A/B/C)
| 展示位 | 函数 | 形态 |
|---|---|---|
| A 信号弹窗走势卡 | `openSignalChartModal()` s.* 分支 → `valueChartWithSignals` | 弹窗走势图,周期可切(3m/6m/1y/3y/5y/all) |
| B 市场温度页 6 宽基情绪分卡 | `renderSentimentMarketTemp()` 循环 → `valueChartWithSignals` | 6 张卡,`sentiment-{range}.json` 短窗 |
| C KPI 详情弹窗(举一反三新增) | `openKpiDetailModal()` → `_loadKpiHistory()` sentiment 分支 → `_kpiLiteCfg` / echarts | 首页 6 小卡点击弹窗,period 切换 |

### 共享实现(全部走这套)
1. **白名单 helper** `_emotionIndexBaseId(key)` + 数据源 `_emotionIndexCurve(key)`(带缓存)新增在 `indexIdToName` 后。只对 6 宽基返回叠加数据,综合类/未知一律 null。
2. **`_lwSignalLiteCfg`/`valueChartWithSignals`**(A/B 共享)新增可选第 10 参数 `indexOverlay`:
   - 叠加时加右侧专属 y 轴(指数量级 1000-4000 vs 情绪 0-100)、第二条**棕色虚线细线**、legend 两条、tooltip 增加指数行、`grid.pr` 加宽到 50。
   - 轻量 SVG 引擎与完整 echarts 兜底(`charts.lightweight` 开关两态)行为一致。
3. **`_loadKpiHistory`/`openKpiDetailModal`/`_kpiLiteCfg`**(C)**:情绪分支拉指数曲线 push 第二 series(`_idxAxis:true`),裁剪到情绪分当前 period 日期窗(防全史撑爆 x 轴)。echarts 双 yAxis 数组 + `yAxisIndex`;`_kpiLiteCfg` 加第二 `ys:{side:'right'}` + `yIndex:1`。visualMap 分段色加 `seriesIndex:[0]`,防指数线被情绪 0-100 分段色误染色。
4. **§21 公示**:6 宽基卡 termTip + KPI 卡 termTip(6 处)+ purpose-notes.js sentiment 段,补「走势图叠加对应指数价格曲线(右轴,虚线)对照」说明。

## 2. 关键设计点(陷阱处理)
- **空壳陷阱**:`static-site/data/` 下 `s.sentiment_*-all.json` 是空壳(ohlc=[]),真实指数曲线走 `index/{宽基id}-all.json`。叠加数据源用 `_emotionIndexCurve` 拉 `index/{id}-all.json.ohlc`,不碰空壳文件。
- **轻量 SVG 引擎双轴**:`_lwHTML`/`_lwSVG`(L13020+)原生支持多 `ys` + 每系列 `yIndex` + `ys.side`(left/right),故 A/B/C 默认 `charts.lightweight=true` 时也能正确渲染双轴双线,无需降级完整 echarts;两态行为一致。
- **轴不撑爆**:A/B 的 x 轴取自情绪分 `data`(已周期过滤),指数按日期对齐(缺失留 null,connectNulls 桥接)。C 因 x 轴取所有 series 日期并集,叠加前把指数裁剪到情绪分日期窗。
- **区域隔离**:只动 A/B/C 三函数 + `valueChartWithSignals`/`_lwSignalLiteCfg`/`_kpiLiteCfg`/`_loadKpiHistory` + 白名单 helper + KPI 卡 termTip 文案。**未碰** `renderOverview` 本体/render 逻辑/freezeCard(#19 地盘)、`indexChart`(#73)、`_homeNews*`(#12)、signalColor/signalLabel/freeze 蓝。

## 3. 验证 / 自测
- 语法:`node --check static-site/app.js` PASS、`node --check static-site/purpose-notes.js` PASS。
- 白名单过滤(隔离 node 复验 19 组输入):6 宽基(s. 前缀与无前缀)全命中,`fear_greed`/`a_sentiment`/`cross_market`/`sentiment_foo`/空 全部 null。→ **6 宽基叠、综合类不叠** ✓
- 对齐逻辑(隔离 node 复验):指数序列按情绪分日期轴对齐,窗口外日期被裁,值正确。✓
- 6 处 `valueChartWithSignals` 调用点核对:仅 A(弹窗 6 宽基)/B(6 宽基卡)传 overlay;恐贪/综合/跨市场/全球extras 4 处不传 → 保持单轴单线不叠 ✓(_emotionIndexCurve 白名单双重兜底)。

## 4. 同类排查清单(§23.2③ / 举一反三 §23.3)
- [x] A 信号弹窗(s.sentiment_* 全 9 类,6 宽基叠,综合类不叠)
- [x] B 市场温度页 6 宽基卡叠;恐贪/综合/跨市场卡不叠
- [x] C KPI 详情弹窗 6 宽基叠;恐贪/综合/跨市场 KPI 卡不叠
- [x] D 信号列表(非走势图,点击落 A 弹窗,已随 A 生效)
- [x] 热力图/恐贪分项条(横向进度条/热力矩阵,非折线走势图,不适用叠加——不叠)

## 5. 已知边界(诚实标注)
- 指数曲线只显示在情绪分对应日期窗内(±同 A 股交易日,两者日期基本重合,缺失处 connectNulls 桥接)。
- 指数取 `-all.json` 全史收盘,周期切换(3m/6m/all)时按情绪分窗口自动裁剪。
- 叠加为增量展示,不改任何既有展示默认行为(既有单线图在传 null overlay 时行为完全不变)。

## 复现
- 改动文件:`static-site/app.js`(235 行 diff)、`static-site/purpose-notes.js`(1 行)。改动前版本串=主控 merge 时统一 bump(本分支不 bump/min,机制 C)。
- 复现现场:浏览器打开站点 → 情绪 tab 市场温度 6 宽基卡(KPI 详情弹窗)→ 看是否有右轴棕色虚线指数曲线与 0-100 情绪分同步;信号弹窗 s.sentiment_sz50 等;综合类(恐贪/跨市场)走势图应无叠加线。
- 数据依赖:`sentiment-{range}.json`(情绪)+ `index/{宽基id}-all.json`(指数,经 dataUrl 走 R2 `/r2/` 代理)。
- 数据截止:static-site/data/ 当前版本(2026-08-19)。基础分支=origin/main e245c9a84。
