# 首页 SVG fix2 复查审查报告(P1-1 标签上移 / P1-2 pointer+pinch / P2-1 bar 限窗)

- 审查对象: 3 commit(df2a88260 P1-1+P2-1 / 2fb56e680 P1-2 pointer/pinch / e5e237993 §9 产物), 分支 feat/daily-brief-backend, 基线 87cd5da68
- 审查者: reviewer agent(独立 context, 只读不写码)
- 审查口径: §15 B 级(逻辑/dataZoom 交互) — 上轮 CONDITIONAL PASS 的 2P1+P2-1 修复复核 + 新回归排查
- 审查日期: 2026-08-12

## 一、已验证 OK 项表(带证据)

| # | 验证项 | 结果 | 证据(file:line) |
|---|---|---|---|
| 1 | 改动边界: 仅 4 文件 | OK | git diff 87cd5da68 e5e237993 --name-only = app.js/app.min.js/index.html/sw.js; 根 data/ 与 static-site/data/ 均未动(§22 无数据产物变更) |
| 2 | node --check app.js | OK | 全量语法通过 |
| 3 | §9 产物一致 | OK | app.min.js md5 前8=5039aab7 = index.html `app.min.js?v=5039aab7`; sw.js L17 CACHE_VERSION a147→a148(改 app.js 必 bump ✓ memory bump-sw-version-with-appjs) |
| 4 | P1-1 几何公式落位 | OK | app.js L11261 `_xLabelY = cfg.dataZoom ? Math.min(_axisY+8+3.5, H-31.5) : _axisY+8+3.5`; min 版已含 `t.dataZoom?Math.min(v+8+3.5,a-31.5):v+8+3.5` |
| 5 | P1-1 仅 6 图触发(pb35 dataZoom), 其余不位移 | OK | 触发阈值 pb<43(公式推得); 6 图=恐贪/情绪/跨市场(_lwLineCard h300 pb35 L12083)+AD(h210 pb35 L10454)+成交额(h300 pb35 L10526)+新高新低(h196 pb35 L10591); KPI(h380 pb45 L12041)/信号弹窗(h300 pb50 L3676) Math.min 取原值不位移; 市场宽度(h182 pb35 L10276)非 dataZoom 走 else 原值不位移 |
| 6 | P1-2 pointer 事件覆盖鼠标 | OK | pointerdown L11863(鼠标左键过滤 L11864)/pointermove L11896/pointerup+cancel L11917-11918; 鼠标 slider 拖拽与滚轮缩放行为保留(preventDefault L11803 先于 pinch return, 防 Android 合成 ctrl+wheel 双倍缩放 ✓) |
| 7 | setPointerCapture 语义 | OK | L11892 捕获 → L11843 releasePointerCapture 统一在 _dzOnUp(up/cancel 均经 _dzOnPointerEnd L11908-11916), 无泄漏; 滑出 svg 不丢事件 ✓ |
| 8 | touch-action 作用域 | OK | svg `touch-action:pan-y` L11698(竖向=页面滚动保留, 禁页级 pinch 交 JS)+slider `g.lw-dz touch-action:none` L11468(触摸拖拽接管); 有效值=元素与祖先交集, slider 区=none、plot 区=pan-y, 语义正确 |
| 9 | P2-1 bar 限窗 | OK | L11286 `for (let i=_i0; i<=_i1; i++)`, xs 仅填窗内 L11271(全局 index), 窗外柱不再依赖 x="NaN" 隐藏; 窗口与 _lwSVG zoom 裁剪同口径, 无 off-by-one(_i1=min(n-1, round(zoomEnd*n)-1)) |
| 10 | 缩放后 hover/pin/markLine 窗口处理未破坏 | OK | _lwBind _recalc/_px 与 _lwSVG 同口径 L11724-11730; markLine/markArea/pin 窗判 L11371/11389/11428 未改 |
| 11 | 无事件泄漏 | OK | 每次 _lwSetup.render/_lwHTML 重建 svg 元素(旧元素连同其监听 GC), _lwBind 单次绑定; up/cancel 均释放捕获 |
| 12 | §21/§22 | OK | 纯显示+交互改动, 无算法(track_score/权重/匹配规则)与数据产物变更; lab.js/purpose-notes.js 未碰 |
| 13 | 其他独立渲染器未误伤 | OK | _etfTrendSVG(L18353 独立硬编码标签)/_lwHeatmapSVG/分时/市场宽度均未走 _lwSVG dataZoom 分支; _lwSVG 仅 2 调用方(L11699/L11734) |

## 二、问题清单

### P1-1 【新回归】6 图 x 日期标签现在跨轴线、压入绘图区底部(修了"被 slider 遮"却引入"标签盖 plot")
- 触发路径: 任意 pb35 dataZoom 图(恐贪/A股/跨市场/AD/成交额/新高新低)
- 几何(实测数值, 见下): 轴线 _axisY=H-35; slider 顶沿=H-26 → 两者仅 9px 间隙, 12px 字根因放不下; fix2 把 baseline 从 H-23.5 上移 8px 到 H-31.5 → 标签 glyph 上沿≈H-40.5..H-43.5,**高出轴线 5.5~8.5px 压进绘图区**,且轴线(H-35)穿标签中下部而过
  - H=196: 新 baseline=164.5, glyph 上沿≈155.5(高于轴线 161 约 5.5px); H=210/300 同理, 均 5.5px
  - 后果: zeroBased 柱图(AD 涨跌比 L10458 / 成交额 L10528 / 新高新低 L10595)柱底/零基线被日期文字覆盖; 折线卡轴线+底部网格线被文字穿过
- 根因: 9px 间隙(轴线 H-35 到 slider 顶沿 H-26)物理放不下 12px 标签, 任何"标签放间隙里"方案必然压一侧; fix2 把旧缺陷(压 slider)换成新缺陷(压 plot/跨轴)
- 修法: 与 KPI(pb45)/信号(pb50)同口径 —— 6 个 dataZoom 图 pb 提至 ≥44(间隙≥18px, 标签可完全落在轴线下、slider 上; KPI pb45 已验证无遮挡); 或 slider 下移/降高让出空间; 不建议继续用 Math.min 压字
- 验收: 需真实浏览器视觉确认(模型只文本); 但几何确定(12px 字 vs 9px 间隙), 当前实现大概率可见"日期字跨轴线"

### P2-1 【UX】双指 pinch 方向与平台惯例/echarts 相反(张开=缩小窗口)
- 触发路径: iOS/触屏双指缩放 L11845-11862
- 数学: `size = (z1-z0)*(d/d0)`, 张开(d↑)→size↑→窗口变大=缩出; 平台惯例与 echarts inside 均为"张开=放大(缩入)"; 与代码自身 wheel 语义(deltaY>0 缩出)映射也相反
- 影响: 功能可用但方向反, 用户"张开放大"实际看到窗口变宽
- 修法: `size = (z1-z0)*(d0/d)`(或 size 取倒数再 clamp); 一行
- 验收: 真机 iOS 双指张开/收拢各验一次方向

### P2-2 【低危】pinch 每 move 重渲染 SVG + 注释精度
- _dzPinchZoom 每 pointermove 调 _applyZoom→_render() 重建整 SVG(60Hz 触摸下低端机可能卡顿; 小 SVG 可接受, P3)
- 注释"仅 pb<41 触发"实际阈值为 pb<43(L11260), 口径不精确(无 41/42 图受影响, 无实害)

### P2-3 【低危】非 dataZoom 图 svg 也加了 touch-action:pan-y(L11698)
- 市场宽度/分时/热力图等图表区域: 页级双指 pinch-zoom 在图表上方被抑制(pan-y 下 pinch 非浏览器默认手势), 页面其余区域不受影响; 属"防误触"取舍, 真机顺带确认无感知

## 三、回归老功能结论
- **鼠标用户**: pointer 事件天然覆盖 mouse, slider 拖拽/jump/滚轮缩放/ hover 全部保留(旧 mousedown/mousemove/mouseup 替换语义等价且多出"滑出 svg 不丢事件"改善)
- **KPI(pb45)/信号弹窗(pb50)/市场宽度(非 dataZoom)**: 公式验证均不位移, 不破坏上轮已验外观
- **echarts 原版(⚡ 关闭 lite 时)**: _lwSetup echartsFn 分支未动, 不受影响
- **独立渲染器**(ETF走势/热力图/分时/sparkline): 未碰
- **node --check / §9 产物 / 边界 / §21 / §22**: 全过(见 OK 表)

## 四、验收口径总结
**CONDITIONAL PASS** — P1-2(pointer+pinch 交互)与 P2-1(bar 限窗)修好且实现正确; §9/边界/回归全过。
- **P1-1 未彻底修好**: 标签清出 slider 顶沿 ✓, 但引入"标签跨轴线/压 plot 底 5.5px"新回归(P1)。合入 main 前须改走 pb 提至 ≥44(与 KPI/信号同口径)或等用户视觉确认接受; 不建议按当前 Math.min 实现合入
- P2-1(pinch 方向)建议合入前反转(一行), 否则 iOS 用户手势方向反
- 真机 iOS/Android 各验: slider 触摸拖拽 + 双指 pinch 方向 + 页面纵向滚动保留
- 合入后主控 §0 补验线上 app.min.js 含新功能字符串(本地 min 已验, 线上待部署)

Co-Authored-By: Claude <noreply@anthropic.com>
