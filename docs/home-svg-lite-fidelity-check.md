# 首页全图表 SVG 化 — 一比一复刻外观验收报告

- 验收对象: commit `e07a9b2df`(feat(svg): 首页全部 echarts 换轻量 SVG — 信号弹窗接 lite + A股情绪分 bug 修复)+ 此前 `293b1d101`(sparkline 批)
- 对比基线: `git show e07a9b2df^:static-site/app.js`(sparkline 批已含, 其余为 echarts 原版)
- 检查方式: 只读逐函数比对原 echarts 配置 vs lite SVG 配置(函数: `_lwSVG`/`_lwLineCard`/`_lwSignalLiteCfg`/`_lwSignalMarkPoints`/`_kpiLiteCfg`/`_ntSparkSVG`/`_lwHeatmapSVG`/`_lwSetup`/`_lwBind` + 各 renderOverview 调用点)
- 日期: 2026-08-12
- 结论: **未达到"一比一复刻"标准**。静态外观大部分对齐, 但存在 **1 个高严重度交互缺失(dataZoom 全丢失)** + **1 个高严重度视觉 bug(市场宽度 y 轴非零基)** + **1 个系统性水平错位(boundaryGap)** 及多处中/低差异。详见下文。

---

## §0 最高优先级章节: dataZoom 时间区域缩放交互差异(**用户可感知交互差异**)

> 用户刚补充的关键维度。结论: **原版首页 8 类图表带 echarts dataZoom(inside 滚轮/双指缩放 + 底部 slider 滑块),lite 版全部缺失,无任何时间轴缩放/刷选/平移能力。**

原版 `dzOpts()`(app.js L205): `[{type:"inside"}, {type:"slider", height:18, bottom:8, textStyle:{color:--text-1}}]`。

| 图表 | 原版 dataZoom | lite 版 | 严重度 |
|---|---|---|---|
| 恐贪指数(首页 _lwLineCard, 原 lineChart) | ✅ inside+slider | ❌ 无 | **高** |
| A股综合情绪分(首页) | ✅ inside+slider | ❌ 无 | **高** |
| 跨市场综合评分(首页) | ✅ inside+slider | ❌ 无 | **高** |
| 盘面温测 恐贪/A股/细分/跨市场(原 valueChartWithSignals 含 dataZoom) | ✅ inside+slider | ❌ 无(共享 lite) | **高** |
| KPI 详情弹窗走势图 | ✅ inside+slider(grid bottom:45 为其留位) | ❌ 无 | **高** |
| 信号弹窗 valueChartWithSignals | ✅ inside+slider(grid bottom:50 为其留位) | ❌ 无 | **高** |
| AD 线(近120日) | ✅ inside+slider | ❌ 无 | **高** |
| 成交额与量比(近120日) | ✅ inside+slider | ❌ 无 | **高** |
| 新高新低(近120日) | ✅ inside+slider | ❌ 无 | **高** |
| 市场宽度(近1月, 原 mkCard 无 dataZoom) | ❌ 原版无 | 无 | —(一致) |
| 首页分时图(原版亦无 dataZoom) | ❌ 原版无 | 无 | —(一致) |
| 首页 sparkline(KPI/指数, 原版亦无) | ❌ 原版无 | 无 | —(一致) |
| 行业热力图(原版无 dataZoom, 有 visualMap calculable) | ❌ 原版无 | 无 | —(visualMap calculable 见 §B8) |

**修正方案**(建议独立排期, 工作量中):
在 lite 引擎(`_lwSVG`/`_lwBind`/`_lwHTML`)增加 dataZoom 支持:
1. **底部 slider**(复刻 echarts 外观: height 18, bottom 8, 背景 `--bg-card`, 边框/手柄 `--border-strong`, 文字 `--text-1`, 双段式轨道+左右手柄): cfg 增加 `zoomStart/zoomEnd ∈ [0,1]` 默认 [0,1]。
2. **inside 缩放**: svg 上 `wheel` 事件以鼠标为锚点缩放 zoomStart/zoomEnd; 拖拽手柄或轨道平移。
3. 重渲染时 `_lwSVG` 按 `[round(zoomStart*n), round(zoomEnd*n)]` 裁剪 `xLabels` + 各 series 数据 + markLine/markArea/pin 的 index 映射(x 轴标签 interval 重算)。注意 markArea/昨收等按原 index 的标记需随裁剪平移。
4. 对近120日/近6月/3m 的长序列(AD/成交额/新高新低/恐贪/情绪分/跨市场/KPI/信号弹窗)接入;短序列(市场宽度近1月、分时图、sparkline)可不接(原版无)。

---

## §1 逐图表对照表

### A. 系统性差异(影响多个图表)

| # | 差异点 | 原版 echarts | lite SVG | 受影响图表 | 严重度 |
|---|---|---|---|---|---|
| S1 | **dataZoom 交互缺失** | `dataZoom: dzOpts()` | 无任何缩放/slider | 见 §0 | **高** |
| S2 | **boundaryGap 水平错位** | category 轴默认 `boundaryGap:true` → 点居中于类别槽(首末点半格内缩, unitW=iw/n, x=PL+(i+0.5)*unitW) | `_lwSVG` 默认 `bg=false` → 点贴边(unitW=iw/(n-1), x=PL+i*unitW);各 cfg 均未传 `boundaryGap:true` | 恐贪/A股/跨市场(_lwLineCard)、信号弹窗、KPI 弹窗、市场宽度、AD、成交额、新高新低(折线点/柱/pin/x 标签整体平移 ~iw/(2n);短序列更明显;柱状首末柱贴轴边 vs 原版半格内缩) | **中-高**(短序列/柱状=高, 长线=中) |
| S3 | **坐标轴字号小 2px** | echarts 默认 axisLabel fontSize=12 | `_lwSVG` 轴标签 font-size=10, name/legend 11 | 除分时图(原版显式 10, 一致)外全部 lite 图 | 中 |
| S4 | **markLine/markArea 虚线规格** | echarts `type:"dashed"` → dash `[5,5]`, 阈值线 `width:1.5` | lite `stroke-dasharray="4 3"`, 阈值线 `width:1`(ml.width 默认 1) | 冰点/过热/20/80 阈值虚线(恐贪/A股/跨市场/盘面温测)、分时昨收、MA20 | 中 |
| S5 | **首帧无动画** | echarts 默认 ~1000ms 入场动画 | SVG 即时出现 | 全部 | 低 |
| S6 | **tooltip 浮层位置** | echarts tooltip 跟随鼠标/数据点 y | `_lwBind` 的 tooltip 固定垂直中部(PT+ih/2) | 全部 lite 折线 | 低 |
| S7 | **主题跟随** | echarts canvas 需 rethemeCharts() 手动重注入 | lite 用 CSS var 原生跟随 | —(lite 更优, 非差异) | 无 |

### B. 逐图表明细

**B1. 恐贪指数 / A股情绪分 / 跨市场综合评分(首页 _lwLineCard, 原 lineChart)**

| 维度 | 原版 | lite | 一致? |
|---|---|---|---|
| 背景/透明度 | 透明 | 透明 | ✅ |
| 网格线 | splitLine 色=--border | var(--border) | ✅ |
| 轴线 | --border-strong | var(--border-strong) | ✅ |
| 轴标签 | 12px --text-1 | 10px --text-1 | ❌ S3 |
| 线宽/平滑 | width 1.5 smooth connectNulls:true | width 1.5 smooth, connectNulls 未设(缺日断线) | ⚠️ 低 |
| 线色(visualMap 5 段) | 冰点#42a5f5/浅蓝#4fc3f7/灰#86909c/橙#e6a23c/红#e6492e | 同(_lwColorFn) | ✅ |
| 分段着色算法 | echarts visualMap 按段 | _lwSVG 同色 run 分段 | ⚠️ 边界段色可能差 1 段;单点 run 画 r=2 圆点(原 symbol:none) | 低 |
| markLine 冰点/过热 | dashed width1.5 dash[5,5], label 10px 位置 insideStartTop | dashed width1 dash"4 3", label 10px start | ❌ S4 |
| dataZoom | ✅ | ❌ | ❌ **高** |
| boundaryGap | true | false | ❌ S2 |
| tooltip | date+seriesName+value | date+value | ⚠️ 低(缺名) |
| 高度 | 恐贪300 / A股300→250 / 跨市场210 | 300 / _lwSetHeight 250 / 210 | ✅ |
| 涨跌红绿 | #e6492e/#2e8b57 | 同 | ✅ |
| 动画 | 有 | 无 | ⚠️ 低 |

**B2. 市场宽度(堆叠面积)**

| 维度 | 原版 | lite | 一致? |
|---|---|---|---|
| **y 轴零基** | `yAxis:{type:"value"}` 默认 zero-based(从 0 起) | `ys:[{splitLine:true}]` 未设 zeroBased → 从数据 min 起;**堆叠面积 closeY=_py(0) 在 yMin>0 时画到轴线下=面积悬挂** | ❌ **高** |
| 线宽/平滑 | width 默认 1.5 smooth | 1.5 smooth | ✅ |
| 面积透明度 | `areaStyle:{}` ECharts5 默认 opacity **0.7** | areaOpacity **0.6** | ❌ 中 |
| 堆叠顺序 | 上涨(红)底→下跌(绿)顶 | 同(series 顺序) | ✅ |
| 颜色 | #e6492e/#2e8b57 | 同 | ✅ |
| dataZoom | 原版无 | 无 | ✅ |
| boundaryGap | true | false | ❌ S2 |
| tooltip | date+name:value | date+上涨家数:值+下跌家数:值 | ✅(内容等价) |

**B3. AD 线 / 成交额与量比 / 新高新低(原 mkCard+setOption)**

| 维度 | 原版 | lite | 一致? |
|---|---|---|---|
| grid | AD{55,55,35,35} / 成交额{55,20,35,35} / 新高新低{55,55,35,35} | pl/pr/pt/pb 同 | ✅ |
| dataZoom | ✅(3 图都有 slider) | ❌ | ❌ **高** |
| boundaryGap | true | false | ❌ S2 |
| 主 bar 轴零基 | 默认 zero-based | 左轴/主轴 zeroBased:true | ✅ |
| **右轴零基** | AD 右轴"腾落线"/新高新低右轴"净新高"默认 zero-based | ys[1] 未设 zeroBased → 数据 min 起,线纵比/网格线与原版不同 | ❌ 中 |
| bar 宽/色 | 60%/涨红跌绿 / 40% | 60%/40% itemColor 同 | ✅ |
| 双 bar 并排 | echarts 对称 ±0.26 unitW | barOffset -0.3/+0.22 不对称,整体右偏 ~1-2px | ❌ 低 |
| MA20 dashed | width1.5 dash[5,5] | width1.5 dash"4 3" | ❌ 中(S4) |
| tooltip | 自定义 formatter | 复刻同款 | ✅ |
| 高度 | 210/300/196 | 同 | ✅ |

**B4. KPI 详情弹窗走势图(原 openKpiDetailModal)**

| 维度 | 原版 | lite | 一致? |
|---|---|---|---|
| grid | {65,25,35,45} | pl/pr/pt/pb 同 | ✅ |
| dataZoom | ✅ | ❌ | ❌ **高** |
| boundaryGap | true | false | ❌ S2 |
| 多系列线/areaStyle/symbol/connectNulls | 全支持 | _kpiLiteCfg 全映射(symbolR=size/2, areaOpacity, connectNulls:true) | ✅ |
| 预估灰 pin | circle symbolSize8 label top | r4 + labelInside "预估" | ⚠️ 低(label 位置 top vs 内嵌) |
| legend | `type:"scroll"` 顶部可滚动/换行 | 单行 lx 累加不换行,多系列(KPI 常 3-6 系列)可能溢出右缘 | ❌ 中 |
| 高度 | 380 | 380 | ✅ |
| tooltip | 多系列 marker+name+value+unit+盘中标注 | 同款复刻 | ✅ |

**B5. 信号弹窗 valueChartWithSignals(本轮新增 _lwSignalMarkPoints/_lwSignalLiteCfg)**

| 维度 | 原版 | lite | 一致? |
|---|---|---|---|
| grid | {55,20,30,50} | pl/pr/pt/pb 同 | ✅ |
| dataZoom | ✅(bottom:50 给 slider 留位) | ❌(pb:50 空置) | ❌ **高** |
| boundaryGap | true | false(折线点+信号 pin x 全平移) | ❌ S2 |
| 线 | width1.5 smooth connectNulls:true | 同 | ✅ |
| 单色 pin | symbolSize 34, label 11px _autoLabelColor | r13(总高~39px), label 11px | ❌ 中(比原版细高) |
| 多色拼色 pin | symbolSize 52 + 金描边 width3 + **光晕 shadowBlur8** + label 白11px 多行 lineHeight13 | r20(总高~60px) + 金描边 width3 + **无光晕** + label 白11px 多行 _lh13 | ❌ 中(pin 偏大偏长 + 缺光晕) |
| band_hold 圆点 | circle size6 offset[0,20] opacity0.5 label 隐藏 | r3 dy20 opacity0.5 隐藏 | ✅ |
| markLine 阈值 | width1.5 dash[5,5] | width1 dash"4 3" | ❌ S4 |
| hideOverlap | markPoint label hideOverlap:true | 未实现 | ⚠️ 低 |
| tooltip | date+value+信号 reason(含拼色●多色+band) | 同款复刻 | ✅ |
| 兼容 5 调用方 | getDom/getOption/setOption/resize | 已实现 getDom:()=>div / getOption 返 markData / setOption 合并 pin+markLine / resize 重渲染 | ✅ |

**B6. 首页分时图 _renderIntradayChart**

| 维度 | 原版 | lite | 一致? |
|---|---|---|---|
| grid | {38,6,8,18} | 同 | ✅ |
| boundaryGap | false | false | ✅ |
| 线 | width1.2 smooth:false 红涨绿跌 | 同 | ✅ |
| 面积 | areaStyle opacity0.1 | areaOpacity0.1 | ✅ |
| 昨收 | dashed --text-3 width1 label end 9px | 同(仅 dash 4 3 vs 5 5) | ⚠️ 低 |
| 午休 markArea | rgba(128,128,128,0.08) label 9px --text-4 | 同 | ✅ |
| y 轴 | scale:true splitNumber2 formatter toFixed(0) 10px | 同 | ✅ |
| tooltip | 时间+价+涨跌+幅度(红绿) | 同款复刻 | ✅ |
| dataZoom | 原版无 | 无 | ✅ |
| 高度 | 容器实测(100/80) | 同 | ✅ |

**B7. 首页 sparkline 批(KPI ~27 + 指数 spark-cell ~11, 原 echarts line+area)**

| 维度 | 原版 | lite(_ntSparkGeom/_ntSparkSVG) | 一致? |
|---|---|---|---|
| grid/边距 | {1,1,2,2} | PL1/PR1/PT2/PB2 | ✅ |
| 点位置 | category 默认 boundaryGap:true → 半格内缩 | `_px=(i+0.5)*unitW` 半格内缩 | ✅ |
| 线 | width1.5 smooth symbol:none | 1.5 smooth 无点 | ✅ |
| 面积 | opacity0.12 | 0.12 | ✅ |
| 轴 | 全隐藏 | 全隐藏 | ✅ |
| tooltip | 日期+收盘+涨跌% | 同款 | ✅ |
| dataZoom | 原版无 | 无 | ✅ |
| 高度 | KPI 30 / 指数 72 | 同 | ✅ |
| 动画 | 有 | 无 | ⚠️ 低 |

**B8. 行业热力图(renderIndustryHeatmap → _lwHeatmapSVG)**

| 维度 | 原版 | lite | 一致? |
|---|---|---|---|
| grid | {56,16,24,60} | 同 | ✅ |
| 色阶 | 绿→灰→红 5 停 [-5,5] | 同(5 停插值) | ✅ |
| 格内数值 | label 9px toFixed(1) #333 | 同 | ✅ |
| x 标签 | interval:0 10px 不旋转 | 同 | ✅ |
| y 标签 | 11px | 同 | ✅ |
| 渐变条 | visualMap horizontal +5%/-5% | 底部渐变条同款 | ✅ |
| 分隔线 | splitLine(主题色) | var(--border) 行列线 | ✅ |
| tooltip | 行业+幅度+净流入+领涨 | 同款 | ✅ |
| visualMap calculable | 可拖手柄过滤 | 静态条无拖动 | ⚠️ 低 |
| 切换 1d/5d/all | setOption | 就地重渲染 | ✅ |

---

## §2 已修复/对齐验证通过项

- **A股情绪分历史位置 bug**(本轮修复): 原 `asChart.getDom()`(lite 无 getDom) → `appendHistoryPos(asChart.card)`, 已修 ✅
- 高度全部对齐原版: 恐贪300/A股300→250/跨市场210/市场宽度182/AD210/成交额300/新高新低196/KPI380/信号300/热力280/分时响应式/spark 30+72
- 涨跌配色(红#e6492e涨/绿#2e8b57跌)、visualMap 5 段色阶、恐贪色阶全部一致
- 网格/轴线/坐标字色的主题 CSS 变量一致, 且 lite 原生跟随皮肤切换(优于 echarts 手动 retheme)
- 分时图/sparkline/热力图三个原版本就无 dataZoom 的图表, lite 也正确无(不误伤)

---

## §3 结论与修正优先级

**整体判定: 未达到"一比一复刻"标准。** 静态配色/线宽/边距/高度/透明度等主体外观逐项对等做得很完整(大部分 ✅), 但存在 3 个高严重度 + 7 个中严重度差异, 其中 dataZoom 是用户可感知的核心交互回归。

修正清单(按优先级):

1. **[高] 市场宽度 y 轴零基**: `renderOverview` 市场宽度 `_lwSetup` 的 `ys` 加 `zeroBased:true`(一行), 根治堆叠面积悬挂到轴线下。
2. **[高] boundaryGap 对齐**: 所有 lite cfg(恐贪/A股/跨市场 _lwLineCard、信号弹窗 _lwSignalLiteCfg、KPI _kpiLiteCfg、市场宽度/AD/成交额/新高新低 _lwSetup)统一加 `boundaryGap:true`(分时图/sparkline 不动)。
3. **[高] dataZoom 交互缺失**: 见 §0 修正方案(新增 lite slider+inside 缩放, 工作量中, 建议独立排期)。
4. **[中] 右轴零基**: AD 右轴"腾落线"/新高新低右轴"净新高"的 `ys[1]` 加 `zeroBased:true`(对齐原版默认零基)。
5. **[中] 轴字号**: `_lwSVG` 轴标签 font-size 10→12(对齐 echarts 默认; 若 10px 有意为之需确认)。name/legend 11 保持或对齐 12。
6. **[中] 虚线规格**: `_lwSVG` markLine/markArea/线 series 的 dash 统一 echarts `[5,5]`; 阈值虚线宽 1→1.5(markLine ml.width 默认 1)。
7. **[中] 信号 pin 尺寸**: 单色 `r:13`→`~11`(symbolSize34/3)、多色 `r:20`→`~17`(symbolSize52/3)以对等原版高度; 多色 pin 补光晕(可加 SVG filter 或外圈半透明圆模拟 shadowBlur8 rgba(255,215,0,0.6))。
8. **[中] KPI legend 单行溢出**: _lwSVG legend 加换行/或 KPI cfg 支持滚动。
9. **[低] 杂项**: 单点同色 run 的 r=2 圆点(原 symbol:none)、tooltip 位置跟随 y、首帧动画、connectNulls 缺失、hideOverlap、双 bar 偏移对称化(barOffset ±0.26)。

> 备注: 以上为代码层逐项比对结论(未做浏览器像素级截图对比, 模型不支持图片)。建议对 1-3 项修完后由 reviewer 跑 smoke + 用户目测红金皮肤下首页整体。

## 附: 本次检查涉及的关键函数与行号(当前工作区 static-site/app.js)

- lite 引擎: `_lwSVG`(L11140) `_lwBind`(L11660) `_lwHTML`(L11647) `_lwSetup`(L11729) `_lwLineCard`(L11877) `_lwCardShell`(L11866) `_lwSignalLiteCfg`(L3657) `_lwSignalMarkPoints`(L3628) `_kpiLiteCfg`(L11778) `_lwHeatmapSVG/Bind/Setup`(L11461/11520/11583) `_ntSparkGeom/SVG/Bind`(L10926/10956/10982)
- 调用点: 恐贪 L9992 / A股情绪分 L10063 / 市场宽度 L10274 / 跨市场 L10319 / AD L10448 / 成交额 L10546(约) / 新高新低 L10594(约) / 分时 L7178 / KPI 弹窗 L5409 / 信号弹窗 L3768 / 热力图 L16852
