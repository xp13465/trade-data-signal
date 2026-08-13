# 首页 SVG 外观对等修正 — reviewer 审查报告

- 审查对象: 4 分块 commit(f301f7a38 / 0ee6800a1 / ade13bf2a / 6be7956b8, 分支 feat/daily-brief-backend), 基线 e9527f640
- 审查者: reviewer agent(独立 context, 只读不写码)
- 审查口径: §15 B 级改动(逻辑/dataZoom 交互, 有隐藏影响面) — 逐点核验 + 隔离测试 + smoke
- 审查日期: 2026-08-12
- 基线验收报告: docs/home-svg-lite-fidelity-check.md(§0 dataZoom 缺失 / S2 boundaryGap / S3 字号 / S4 虚线为本次 4 块的修正目标)

## 一、已验证 OK 项表(带证据)

| # | 验证项 | 结果 | 证据(file:line) |
|---|---|---|---|
| 1 | node --check app.js | OK | static-site/app.js 全量语法通过 |
| 2 | app.min.js 已重建且含新功能字符串 | OK | boundaryGrep: boundaryGap/dataZoom/lw-dz/lwzc/按指数级 各 1 处; md5=46bec89e 与 index.html v=46bec89e 一致 |
| 3 | 隔离测试 19/19 | OK | /tmp/svg-lite-test.js: pass=19 fail=0(zoom 窗口裁剪/slider/clipPath/x 标签裁剪/zeroBased 闭合/markLine 窗内外/pin 窗内外/分时字号10/轴字号12/legend 换行) |
| 4 | 边界: 仅 4 文件改动 | OK | git diff e9527f640 6be7956b8 --name-only = app.js/app.min.js/index.html/sw.js; 根 data/ 无暂存; static-site 无未跟踪 |
| 5 | purpose-notes.js / lab.js 未碰 | OK | diff 为空; purpose-notes.min.js 内容无变化(index.html hash f7647cf8=内容 md5, 是基线 hash 名不副实的修正, 无害) |
| 6 | sw.js CACHE_VERSION | OK | = v6-20260812-a147(改 app.js 必 bump, 符合 memory bump-sw-version-with-appjs) |
| 7 | dataZoom 接入 8 图 | OK | 6 个 cfg builder: _lwLineCard L12020(恐贪/A股/跨市场), _kpiLiteCfg L11980(KPI弹窗=恐贪+A股情绪分弹窗), _lwSignalLiteCfg L3676(信号弹窗), AD L10454, 成交额 L10526, 新高新低 L10591 |
| 8 | 原版无 dataZoom 的图正确不接 | OK | 市场宽度 L10276(仅 boundaryGap+zeroBased, 无 dataZoom), 分时 L7180(boundaryGap:false+axisFontSize:10, 无 dataZoom), sparkline(nt-spark/idx-spark/etf-spark 独立渲染器未碰), 热力图(_lwHeatmapSVG 独立), ETF走势图(_etfTrendSVG 独立) |
| 9 | boundaryGap:true 半格内缩 | OK | 7 cfg(L3675/L10278/L10453/L10525/L10590/L11979/L12019); 公式 PL+(i-i0+0.5)*unitW, unitW=iw/nView(L11160-11162) |
| 10 | 零基(含右轴) | OK | 市场宽度 L10280; AD 左轴 L10458 + 右轴腾落线 L10459; 成交额 L10528; 新高新低左轴家数 L10595 + 右轴净新高 L10596; 堆叠 area closeY=_py(ai,0)(L11383) + zeroBased → 闭合到底 |
| 11 | 字号 12 / 分时 10 / 阈值线 1.5 / 虚线 5 5 / 双柱 ±0.26 | OK | _axFont 默认 12(L11156), 分时显式 axisFontSize:10(L7183), markLine width 1.5 + dash 5 5(L11370/11379), barOffset ±0.26(L10603-10604, 40% 柱宽内不越界) |
| 12 | §21 公示: 纯显示改动 | OK | _lwSignalMarkPoints 仅 r 13→11/20→17 + glow(L3647-3655), 无 track_score/权重/匹配规则变更; posCapBadge 加"按指数级 top-K"口径说明(L1856-1861)属公示补强 |
| 13 | §22 数据一致性: 无数据产物改动 | OK | 未改任何 data JSON, 无 N 文件/R2/CF 同步需求 |
| 14 | 数据层 smoke | OK | ad_line.json 250 条, overview.json date=20260811(最近交易日), vol_ratio/width_1m/cross_market_6m/a_sentiment_6m/fear_greed_6m 存在 |
| 15 | 滚轮缩放鼠标锚点数学 | OK | ns=anchorData-anchor*size 保持锚点数据点不动(L11787-11800); [0,1] 裁剪+min 0.05 正确 |
| 16 | y-extent 按可见窗重算 | OK | L11179-11189 只在窗内取值(与 echarts dataZoom 过滤后重算轴一致); stack 累积仍全窗(cum 累积 L11399 全 range, 面积顶正确) |
| 17 | 缩放后 hover 几何重算 | OK | _lwBind _recalc/_px 与 _lwSVG 同口径(L11724-11736); tipFn 收全局 index i+_i0, 8 图 tipFn 均以全局 i 索引数据(L10469/10534/10560/12031/11811) |
| 18 | markLine/markArea/markPoints 窗内处理 | OK | 2 点 markLine 端点窗判+clipPath(L11368-11371), markArea 窗判+clip(L11385-11388), pin 窗外跳过(L11424), 全宽阈值线保留 |
| 19 | 回归: echarts 原版不受影响 | OK | 改动全在 _lwSVG/_lwBind/_lw*Cfg; dzOpts()/grid 原配置未动; _lwSetup echartsFn 分支未动 |
| 20 | _etfXStep 签名向后兼容 | OK | (n,iw,fs), _etfTrendSVG 调 2 参默认 fs=10(L18283), _lwSVG 调 3 参 L11252 |
| 21 | connectNulls 对齐 | OK | _lwLineCard 加 connectNulls:true 与原始 lineChart(L336)/valueChartWithSignals(L3748)一致; symbolR gate 去单点圆点符合 commit 意图(L11322/11343) |

## 二、问题清单

### P1-1 【视觉缺陷】x 轴日期标签被 dataZoom slider 上沿遮挡(6 图: 恐贪/A股/跨市场/AD/成交额/新高新低)
- 触发路径: 任意 pb=35 且 dataZoom 的图(恐贪/A股/跨市场 _lwLineCard h300 pb35; AD h210 pb35; 成交额 h300 pb35; 新高新低 h196 pb35)
- 几何: x 标签 baseline = _axisY+8+3.5 = H-PB+11.5 = H-23.5(L11264), 12px 字 glyph 上沿≈H-35.5、下沿≈H-20.5; slider 占 H-26..H-8(L11474)且**在文档序后绘制(覆盖标签)** + fill=var(--bg-card) 不透明(L11476) → 每个日期标签底部 ~5.5px(约半字)被滑块顶沿盖住
- 对照: 原版 echarts grid bottom:35 + slider bottom:8(L331/10488) 标签与滑块无遮挡; KPI弹窗(pb45)/信号弹窗(pb50) 本分支无重叠(留位正确, 基线报告 §0 已标注"grid bottom:45/50 为其留位")
- 修法: ①dataZoom 时 x 标签上移(如 baseline=H-26-14) ②或 dataZoom 图 pb 提到 ≥45(与 KPI/信号一致) ③或 slider 下移到 H-18
- 验收: 需真实浏览器视觉确认(模型只文本); 若用户确认原版同样略重叠可降级 P2

### P1-2 【交互回归(mobile 主设备)】slider 触摸拖拽不可用, iOS 无缩放
- 触发路径: 移动端触摸 slider 拖拽 → 不派发 mousemove → 仅 mousedown 点按可 jump 手柄(L11850-11860); iOS Safari 不派发 wheel(pinch) → 完全无缩放; Android pinch 派发 ctrl+wheel → wheel 缩放可用
- 对照: 原版 echarts slider 内置 touch 拖拽 + pinch, 站点 mobile-first PWA
- 修法: _lwBind dataZoom 分支补 touchstart/touchmove/touchend(或统一 pointer events), wheel 分支兼容 ctrlKey pinch
- 验收: 真机 iPhone/Android 各验一次 slider 拖拽 + 双指缩放

### P2-1 【脆弱实现】bar 系列缩放后窗外柱靠 NaN 坐标"恰好"隐藏
- 触发路径: AD/成交额/新高新低 bar 缩放后, _lwSVG bar 分支循环 `for (let i=0;i<n;i++)`(L11281)用 xs[i], 但 xs 仅填 _i0.._i1(L11270) → 窗外 i 得 x="NaN"
- 现行为: 按 SVG spec 无效几何元素不渲染 → 恰好=期望隐藏(无可见异常)
- 风险: 依赖浏览器 NaN 几何错误处理, 若某浏览器按 x=0 渲染则窗外柱堆叠在左缘; 隔离测试未覆盖 bar 缩放
- 修法: bar 循环改 `for (let i=_i0;i<=_i1;i++)`

### P2-2 【UX】缩放后旧 tooltip 残留 + 重渲染重置缩放
- _applyZoom 未调 _hide()(L11763-11772): wheel 缩放时鼠标不动则旧 tooltip 停旧位, 下次 mousemove 才更新
- _lwSetup/_lwBind 用 Object.assign 浅拷贝 cfg(L11874-11876), 缩放状态写在拷贝上 → 皮肤切换/⚡/KPI setOption 重渲染 → zoom 重置回 [0,1]
- 修法(可选): _applyZoom 内补 _hide(); 缩放状态存 _lwCfgMap 原始 cfg 或独立 state

### P2-3 【低危】tooltip 跟随 y 无底部 clamp
- L11755-11760: top = cssY-tipH-12, 负则翻到下方; 几何上 plot 底 hover cssY≤H-PB → top 仍在 wrap 内不溢出, 但 wrap 位于页面底部时可能超出可视区(原垂直居中无此问题)
- 修法(可选): 补 top+tipH>wrap 高 时上移

### P2-4 【低危】slider 区 mousedown preventDefault
- L11853 在 slider 26px 区域 mousedown 即 preventDefault + jump 手柄, 对页面纵向滚动影响极小; 真机验证时顺带确认

## 三、回归老功能结论
- **未开 lite 的 echarts 原版图: 不受影响**(所有改动封闭在 _lwSVG/_lwBind/_lw*Cfg, dzOpts/grid/withTheme 原配置未动, _lwSetup echartsFn 分支未动)
- **sparkline(KPI/指数)/行业热力图/ETF走势图/分时图: 走独立渲染器或已正确不接 dataZoom, 未误伤**(基线 §B6/B7/B8 同口径)
- **分时图**: 仅加 axisFontSize:10(对齐原版显式 10px), boundaryGap:false 保持, 无 dataZoom, 10px 字号在日内短序列仍可读
- **新增 hover 区域 guard**(L11775: 仅绘图区显示 tooltip)对全部 lite 图生效, 与 echarts trigger:axis(仅 grid 内)行为一致, 属对齐非回归
- **_lwSignalMarkPoints r 缩小**: 单色 pin r11 内 label(如"买入"2 字)约 22px 宽度接近 r11 圆直径, 边缘临界但与原版 symbolSize 34 语义一致; 多色 pin r17 空间充足
- **整体**: 未发现破坏既有老功能的改动; 8 图 dataZoom 接入完整、原版无 dataZoom 的图正确不接、boundaryGap/零基/字号/虚线/柱位均对齐

## 四、验收口径总结
**CONDITIONAL PASS**(核心目标全部达成: 8 图 dataZoom+boundaryGap+零基+字号+外观对等实现正确、边界/§21/§22/构建/测试/数据层全过)
- 合入 main 前须处理 2 个 P1:
  - P1-1 label/slider 遮挡(6 图, 一处几何修正即可)+ 用户视觉确认
  - P1-2 mobile 触摸 slider 缺失(补 touch/pointer 事件, 真机验)
- P2-1~P2-4 建议修复或记录待办, 不阻塞合入
- 提示: 合入后主控 §0 补验线上 app.min.js 含新功能字符串(本地 min 已验证, 线上需部署后验)

Co-Authored-By: Claude <noreply@anthropic.com>
