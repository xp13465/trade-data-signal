# 首页三张分段色图「尖角+分段色不对」终版根因调研(a320 上线后独立从零验证)

> 2026-08-17 | researcher | 只读不改,独立从零验证,不信任何"已修好"结论
> 任务:用户 3 次隐私窗口确认未修好,前三次 implementer 自验「色变点折角 0.00°」。本文档给出证据链 + 1:1 复刻 echarts 完整版的修复方案。
> 前置文档:docs/lite-svg-corner-vertex-investigation.md(8/17 修复前调研)+ docs/lite-svg-corner-vertex-geom.py(旧脚本)

## 0. 一句话结论

**当前部署代码(a320)几何上已全平滑——三张图每个数据点折角 0.00°(未舍入)、toFixed(1) 舍入后色变边界最大 2.5~4.6°(全部 <5° 人眼不可见),不存在几何尖角。用户反复看到"尖角不平滑+分段颜色不对"的真相是:SVG 轻量版把整条线切成 100 段独立纯色 path(斑马纹),颜色每 1.4 个数据点大跨度突变一次(恐贪 71% 相邻点换色),视觉上呈现参差锯齿感;而 echarts 完整版是 1 条连续平滑 path + 垂直渐变(颜色随值域平滑过渡,仅阈值处硬切)。「尖角」= 斑马纹观感(非几何折角),「分段颜色不对」= 纯色段硬切 vs 渐变平滑的语义差异。修复 = SVG 轻量版 perColor 分支改为复刻 echarts 的单 path + 垂直线性渐变。**

## 1. 三张图渲染链(已确认,全部走 SVG 轻量版)

| 图 | 调用点 | 数据字段 | 色函数档位 |
|---|---|---|---|
| 恐贪指数 | app.js L11132 `_lwLineCard` | `fear_greed_6m` | 25/40/60/75(蓝/浅蓝/灰/橙/红) |
| A股综合情绪分 | app.js L11203 | `a_sentiment_6m` | 20/40/60/80 |
| 跨市场综合评分 | app.js L11505 | `cross_market_6m` | 20/40/60/80 |

渲染链:`_lwLineCard` → `_lwSetup`(L13284, `charts.lightweight` 默认 true = SVG 轻量版)→ `_lwHTML`/`_lwSVG` → connectNulls 分支(L12597)→ perColor 分支(L12612-12642)→ `_lwLineDIdxCtx`(L12378)。
线型 = catmull-rom→cubic bezier(smooth:true 恒 true),非 polyline。

## 2. 核心证据:当前代码几何全平滑(穷举全点折角)

### 2.1 未舍入几何折角(全部数据点,含色变点+普通点)
复刻 `_lwLineDIdxCtx` + connectNulls + perColor 分支(脚本 `docs/scripts/lite-corner-allpoints-geom.py`):
```
恐贪 n=141:  全部139点 avg=0.00° min=0.00° max=0.00°, 色变点99 avg=0.00°, 普通点40 avg=0.00°
情绪 n=140:  全部138点 avg=0.00° min=0.00° max=0.00°, 色变点102 avg=0.00°, 普通点36 avg=0.00°
跨市场 n=153: 全部151点 avg=0.00° min=0.00° max=0.00°, 色变点56 avg=0.00°, 普通点95 avg=0.00°
```
结论:每个数据点到达切线与离开切线完全共线(C1 连续)。「普通点全体尖角」假设不成立。

### 2.2 舍入后(toFixed(1) 坐标,浏览器实际渲染坐标)色变边界折角
脚本 `docs/scripts/lite-corner-junction-emitted-geom.py`(已修正共享端点匹配 bug,见 §5 修正记录):
```
恐贪: 色变边界99个 avg=0.098° max=2.473° >5°=0
情绪: 色变边界102个 avg=0.380° max=2.990° >5°=0
跨市场: 色变边界56个 avg=0.105° max=4.574° >5°=0
```
全部 <5°,人眼不可见。前三次 implementer 自验「色变点折角 0.00°」与本文档一致,数据本身没有错。

### 2.3 关键:当前部署代码含修复,非旧版
- 主站 ss.fx8.store 与 s.sugas.site 的 app.min.js **md5 完全一致** = 11f64f55535a1be32b8b689516ea7862(818711B = 本地构建)
- 备站 sss.sugas.site app.min.js(428095B)虽体积小近半,但 `_lwLineDIdxCtx` 函数体与主站**逐字符一致**(含段首借点 `l===n&&n>0&&a[n]-a[n-1]===1?n-1:l` + 段尾延伸 `Math.min(i,l+2)` + 跨 null 钳制)
- 即:**三个域名都部署了 2026-08-17 修复版**,用户访问任何域名几何都平滑

### 2.4 三张图 liteCfg 均无 areaOpacity/symbolR(纯色线,无面积/圆点干扰)

## 3. 真凶:斑马纹观感(视觉尖角) + 纯色段 vs 渐变语义(颜色不对)

### 3.1 斑马纹量化(线上真实数据 overview.json 20260817)
```
恐贪: 100个色段, 段长≤2点占91%, 色变点99个, 平均段长1.4点 → 每1.4个数据点换一次色
情绪: 103个色段, 段长≤2点占93%, 色变点102个, 平均段长1.4点
跨市场: 58个色段, 段长≤2点占65%, 色变点57个, 平均段长2.6点
```
即:当前 SVG 轻量版把整条平滑曲线切成 100 段独立 path,每段一个纯色(蓝/浅蓝/灰/橙/红大跨度),段与段之间颜色硬切。**即使每条线段几何上 0° 平滑,颜色每 1-2 点突变一次,人眼看到的是参差斑马纹/锯齿感——这就是用户感知的"尖角"**。

### 3.2 echarts 完整版(lightweight=false)真实输出 = 1 条 path + 垂直渐变
用 echarts SSR + 真实恐贪配置(`docs/scripts/lite-echarts-ssr-baseline.js`)渲染:
```
数据 polyline path 数量: 1   ← 整线一条 path(连续平滑)
stroke="url(#zr0-g0)"
<linearGradient gradientUnits="userSpaceOnUse" x1="0" y1="82.5" x2="0" y2="217.5">
  <stop offset="7.41%" stop-color="#e6492e"/>  ← 顶=值大=红
  <stop offset="7.41%" stop-color="#e6a23c"/>  ← 阈值硬切(同 offset 双 stop)
  <stop offset="32.96%" ... 橙→灰
  <stop offset="67.04%" ... 灰→浅蓝
  <stop offset="92.59%" ... 浅蓝→蓝(底=值小)
</linearGradient>
```
**echarts 完整版 = 1 条连续平滑 path,颜色由「该点 y 值」经垂直渐变决定(值域内连续渐变,仅阈值处硬切)。** 这与 SVG 轻量版「100 段独立纯色 path(去向色)」的渲染方式根本不同。

### 3.3 定性结论
- 「尖角不平滑」:当前代码无几何尖角(§2 数据);用户看到的 = 100 段斑马纹的视觉参差感
- 「分段颜色不对」:SVG 用「每段去向色纯色 + 段间硬切」vs echarts 用「按 y 值垂直渐变(平滑过渡)」,两者颜色呈现语义不同,观感差异巨大

## 4. 1:1 复刻 echarts 完整版的修复方案

改动点:`static-site/app.js` `_lwSVG` 的 connectNulls+perColor 分支(**L12612-12642**),把「按色段切 N 条独立纯色 path」改为「1 条连续 path + 垂直 linearGradient」,复刻 echarts SSR 输出结构。

### 改动 1:整线画 1 条连续平滑 path(替代色段循环)
```js
// 替代 L12616-12641 的 while 色段循环
const dAll = _lwLineDIdxCtx(xs, ys, _idx, 0, _idx.length - 1, _idx.length - 1, ser.smooth === true);
s += '<path d="' + dAll + '" fill="none" stroke="url(#lwGrad-' + _serIdx + ')" stroke-width="' + (ser.width || 1.5) + '"' + _dashAttr + _opacityAttr + ' stroke-linejoin="round" stroke-linecap="round"/>';
```
- 跨 null:由 `_lwLineDIdxCtx` 内部 `idx[k+1] > idx[k]+1` 直线连接处理(语义同 echarts connectNulls:true)
- 单点段/末点 symbol:保留原 L12630-12631 的 circle 逻辑(三张图无 symbolR,可不处理)
- `_serIdx` = 当前 series 序号,用于唯一渐变 id

### 改动 2:defs 生成垂直渐变(复用现成 `_grads`/`_defs` 机制, L12477-12485)
```js
// 值域 = _lwValueExtent 的 yMin/yMax(图区 PT..PT+ih,值大在上方=渐变顶部)
// 阈值 = 色函数分档点(恐贪 25/40/60/75,情绪/跨市场 20/40/60/80)
// offset(t) = (yMax - t) / (yMax - yMin)  ← 值越大越靠顶,与 echarts 一致
// 每个阈值两个 stop 硬切: <stop offset="X%" stop-color=旧色/> + <stop offset="X%" stop-color=新色/>
```
- 渐变 y1/y2:SVG 轻量版图区为 PT(顶,值最大)→ PT+ih(底,值最小),x 用默认(水平无色变)
- 颜色与阈值:直接用 `_perColor` 判定,阈值 = 相邻档位边界(从色函数反推或用 stops 表)
- 若 `_grads` 默认 x1=0 y1=0 x2=0 y2=1(objectBoundingBox),顶部=bbox 顶=值最大,方向天然正确,无需 userSpaceOnUse

### 改动 3:areaOpacity(如需)
三张图当前无 areaOpacity;若未来有,area 用渐变或单色即可(本次不涉及)。

### 与 echarts 配置的对应关系(复刻基准)
| echarts 完整版配置 | SVG 轻量版复刻 |
|---|---|
| `smooth:true` | `_lwLineDIdxCtx(..., smooth)` catmull-rom→cubic(c1=p1+(p2-p0)/6, c2=p2-(p3-p1)/6) |
| 1 条 path | 改动 1(整线 1 条 path,不再切段) |
| visualMap pieces 阈值 | 改动 2 渐变 stops 按阈值硬切(恐贪 25/40/60/75) |
| 垂直 linearGradient(userSpaceOnUse) | 改动 2 垂直渐变(值域 PT..PT+ih,offset=(yMax-t)/(yMax-yMin)) |
| 颜色由点自身 y 值决定 | 渐变 stroke 天然按 y 值着色(去掉了「去向色/起向色」语义分歧) |

## 5. 调研脚本修正记录(重要,防误判传播)

`docs/scripts/lite-corner-junction-emitted-geom.py` 原脚本有一个匹配 bug:色段边界用 `prev.re == ds-1` 匹配上一段(共享端点应为 `prev.re == ds`,因为 `drawStart = prevRe = 上一段 re`),导致算出假角 78-169°(`>5°` 大量),与真实代码不符。**已修正**(by_re 字典 + `x.re === s.ds`),修正后输出 §2.2 的 <5° 结果。任何人复现本结论必须用修正后版本,否则会得出「色变点全是尖角」的错误结论(这正是把"已修复"误判为"没修好"的可能来源之一)。

## 6. 诚实标注(局限)
- 本文档证明**代码几何平滑 + 三域名部署最新 + echarts 完整版是渐变**,但无法直接"看到"用户浏览器里的像素。用户看到"尖角"最可信解释 = 斑马纹观感(§3.1 数据支撑);次要可能 = 浏览器 SW/CF edge 缓存滞留旧版(§24 已知风险,需强刷/隐私窗口+禁用缓存验证)
- 修复方案改动 `app.js` 需 implementer 实施,且必须走 §21 公示(算法/展示变化)+ §22 三步同步(static-site + R2 三域名)+ §24 bump 版本串
- 建议:修复后请用户**隐私窗口 + 强刷(禁用缓存)**验证;若仍报尖角,则需直接看用户浏览器实际 DOM/截图(超出本文档纯代码验证范围)

## 7. 复现

- 脚本:
  - `docs/scripts/lite-corner-allpoints-geom.py`(全点几何折角,§2.1)
  - `docs/scripts/lite-corner-junction-emitted-geom.py`(舍入后色变边界折角,§2.2,**修正后版本**)
  - `docs/scripts/lite-echarts-ssr-baseline.js`(echarts 完整版 SSR 1:1 基准,§3.2)
  - `docs/scripts/lite-echarts-ssr-all3.js`(三图 SSR 全跑)
- 输入依赖:`/tmp/overview_online.json` = 线上 `https://ss.fx8.store/data/overview.json`(20260817,恐贪 141 点/情绪 140 点/跨市场 153 点,均无 null)
- 重跑命令:
  - `python3 docs/scripts/lite-corner-allpoints-geom.py`
  - `python3 docs/scripts/lite-corner-junction-emitted-geom.py`
  - `cd static-site && node ../docs/scripts/lite-echarts-ssr-baseline.js`(依赖 `static-site/vendor/echarts.min.js`)
- 数据截止:2026-08-17
- 关键口径:catmull-rom→cubic(c1=p1+(p2-p0)/6, c2=p2-(p3-p1)/6);折角=该点到达切线 vs 离开切线夹角;共享端点=上一色段末点 re==本段起点 ds(drawStart=prevRe);toFixed(1) 舍入后坐标
