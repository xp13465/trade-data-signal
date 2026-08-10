# 凯利模拟回测·降亏过滤交互优化(打勾卡顿/整卡重载闪烁)调研与方案

> 调研 agent 产出(2026-08-11),只读调研 + 方案设计,不实施 lab.js 改动。实施待方案确认后派实施 agent。
> 触发:用户反馈降亏过滤 toggle 打勾/取消时"卡片一闪一闪(重载)",无法对照打勾前后数值变化。

## 1. 用户原话与诉求

> "凯利模拟回测的降亏过滤 之前的版本我时说交互时卡顿 想要 loading 这该层或怎样。结果你给的方案优化为里页面重载。这个交互难受死了 一闪一闪。都不方便我对照着看打勾不打勾数值变化了。变成卡片一闪一闪(重载)了。"

诉求拆解(任务书):
1. **打勾不打勾时数值增量更新** — 不打勾的卡也实时对照,不是整卡重载闪烁
2. **整卡/页面不重载** — 卡片保持挂载,只更新数值
3. **计算慢要有 loading 态** — 非整卡清空式 loading

## 2. 根因定位

### 2.1 当前 toggle 交互链路(lab.js)

toggle checkbox `onchange`(L8019-8200,29 个独立 toggle + 3 组合宏)→ 改 `state.labSigKellyFilters[xxx]` → `_kellyOnFilterChange()`(L7701)→ `_kellyRunRecompute(host, loadingHtml, onResult, onDone)`(L7489)。

`_kellyRunRecompute` 核心两行是闪烁根因:

```js
// L7494: ① 整卡区域被清空成 loading 占位 —— 卡片全部消失
host.innerHTML = loadingHtml;
await _kellyNextPaint();              // 双 rAF 让 loading 先 paint
var stats = await _kellyApplyFeeRecompute(...);  // 同步重算(主线程阻塞 ~400-700ms)
onResult(stats);
// onDone(L7716) → _renderSigKellyQuadrants(host, ...)
```

`_renderSigKellyQuadrants`(L8233):

```js
// L8264: ② 16 张卡整卡从零重建(host.innerHTML = html)
host.innerHTML = html;
```

**完整闪烁序列**:打勾 → 整卡区域被 `innerHTML = loadingHtml` 清空(卡片全消失)→ loading 占位 paint → 主线程同步重算 ~400-700ms(loading 冻结)→ `_renderSigKellyQuadrants` 16 卡从零重建 → 卡片重新出现。用户看到的"一闪一闪(重载)"= 卡片消失 → 空 loading → 卡片回来,期间无法对照打勾前后数值。

### 2.2 哪个 commit 引入"整卡重载"行为

- **引入前**(`5e0865d7f` 之前):`_kellyOnFilterChange` 是 `await _kellyApplyFeeRecompute(...)` → `_renderSigKellyQuadrants(host,...)` 整卡重建,但**没有 loading 层**。此时打勾 = 页面冻结 ~1.3-1.4s 然后整卡重建(用户说的"交互时卡顿")。
- **引入**(commit `5e0865d7f` "perf(kelly): 降亏过滤点击卡顿优化(方案A…方案B loading真显示+防重入…)",2026-08-10):方案 B 加了 `host.innerHTML = loadingHtml` 整卡清空 + 双 rAF loading 真 paint + 防重入 busy flag。用户要求"loading 这一层",实现的却是"整卡清空成 loading + 整卡重建" = 用户现在骂的"页面重载"。
- **关键**:两个版本的**渲染层都是整卡 `host.innerHTML` 重建**,区别只在有没有整卡清空。所以修复方向 = **渲染层改为局部增量更新**,让卡片保持挂载。

## 3. 性能瓶颈(打勾后重算什么)

`_kellyApplyFeeRecompute`(L7501)每次 toggle 变化全量重算:

1. **首次打勾**:懒加载 `signal_kelly_trades.json`(**51MB 未压缩**,本地实测 `static-site/data/signal_kelly_trades.json` 51,534,835B;CF Workers br 压缩后网络 ~9MB),R2 `https://ss.fx8.store/data/signal_kelly_trades.json` → CF `./data/...` 兜底(L7506-7529)。**首次 toggle 的网络+解析是大头延迟**(1-3s 量级)。
2. **计算主体**:遍历 `quadMeta`(16 象限)× `sellModes`(9 模式)× 过滤谓词 + `_kellyComputeStats`(720 桶,每桶含 streak 排序/最大回撤/夏普等)。经 `5e0865d7f` 缓存优化后(特征缓存/费率重算缓存/逐桶 stats 缓存/签名缓存),**残余 ~400-700ms 同步主线程计算**(commit 实测: N1 1380→704ms、N2 1382→492、V4B 1363→428、Greedy7 1324→711、全开 452→239、连点 0ms;残余大头 = `_kellyComputeStats` 720 桶 streak 排序)。
3. 缓存命中情况:签名缓存只对"同状态连点" 0ms;每次 toggle 状态变 → 全 144 桶 `toggled` 数组都变(所有象限同一过滤集)→ 逐桶缓存基本失效重算(但 `_kellyRecomputeCache` 按 trade 复用费率重算结果)。

**结论**:计算本身无法即时(残余 ~500ms),但**渲染层必须改**——不能让用户看整卡消失。

## 4. 方案设计

### 4.1 核心原则

- **卡片保持挂载,永不整 host 清空**:去掉 `host.innerHTML = loadingHtml`(L7494)与 toggle 路径的整 `host.innerHTML` 重建(L8264)。
- **局部增量更新**:toggle/费率变化后,只更新受影响的数值 DOM。
- **loading 用"旧内容保留 + 顶部细条"模式**:项目已有现成实现 `.lab-custom-host--loading`(style.css L4392-4413,"不全屏清空,旧内容半透明保留+顶部细条 spinner",lab.js L6045/L6137 用于 aiwarn 切换标的)——sigkelly 复用同模式。

### 4.2 方案一(推荐):保留卡片挂载 + 卡片级就地替换 + 复用现成 loading 模式

**改动点(全部在 `static-site/lab.js`)**

1. **`_kellyRunRecompute`(L7489)**:删 `host.innerHTML = loadingHtml`(L7494),改为给 host 加 `lab-custom-host--loading` class(旧内容半透明 + 顶部细条 spinner,style.css 现成)。`.lab-sigkelly-host` 需补 `position: relative`(style.css,否则 `::before` absolute 定位基准错)。loading 在重算完成后移除。签名不变(host/onResult/onDone 复用),**三个调用方(`_kellyOnFilterChange` L7707 / `_kellyOnFeeChange` L7671 / `_kellyOnFormChange` L7637)无需改调用**。
   - ⚠️ 同步计算期主线程阻塞,顶部 spinner 动画会冻结——可接受(卡片仍在屏、非整卡消失);若要在计算期动画,需 §4.4 非阻塞化。
2. **`_renderSigKellyQuadrants`(L8233)拆分两阶段**:
   - 保留整卡渲染作为**首次渲染 + 周期切换**(L7836 初始 / L8003 周期切换仍走整建,用户未抱怨周期切换,可不动)。
   - 新增 **`_updateSigKellyQuadrantsInPlace(host, data, period)`**:对每张卡调 `_renderSigKellyCard(qk, q, period, cmp.map[qk])` 生成新卡 HTML,定位已挂载的 `.lab-sigkelly-card[data-quad="${qk}"]`,**仅替换该卡节点**(`oldEl.outerHTML = newHtml`),不触碰 group/grid 容器;替换后重绑:行点击(`_openSigKellyTradesModal`)、`_bindSigKellyWmPop`、`_bindSigKellyGuidePop`(复用 L8256-8265 现有绑定逻辑,抽公共函数)。
   - 需给卡根节点加 `data-quad="${qk}"` 属性(`_renderSigKellyCard` 返回的 `<div class="lab-sigkelly-card">` 处,L8630 附近)。
3. **toggle/fee 路径的 onDone 改走 in-place 更新**:`_kellyOnFilterChange` L7716 的 `_renderSigKellyQuadrants(host, ...)` 改为 `_updateSigKellyQuadrantsInPlace(host, ...)`;`_kellyOnFeeChange` L7654 同理(注意 fee change 的 onDone 还 `_renderSigKellyBar` 重渲染 bar——bar 是费率/过滤控件区,保留重渲染不涉及卡片闪烁,可不动)。
4. **数据流不变**:`state.labSigKellyFeeStats`(重算 stats,`{qk: {period: {mode: stats}}}`)仍为唯一数值源;`_sigKellyCardComparison`(cwm 水印)与 `_sigKellyWatermark`(wm 水印)随 feeStats 重算,卡片级替换天然覆盖。§22 数据一致性不受影响(所有展示位读同一 `labSigKellyFeeStats`)。

**效果**:打勾 → 卡片全部留在屏上(半透明 + 顶部细条)→ ~500ms 重算 → 每张卡就地更新数值 → 用户可对照打勾前后变化。无整卡消失/重建,无闪烁。

### 4.3 方案二(更细粒度,可选进阶):行/单元格级 textContent diff

若卡片级替换仍被接受不了(每卡 DOM 重建会丢失卡内 hoverpop/滚动态),可进一步做单元格级:

- 抽 `_renderSigKellyCardRow(qk, m, r, period, modeLabels)` 返回单行 `<tr>`(现 L8600-8648 rows 拼接处)。
- `_updateSigKellyQuadrantsInPlace` 对每行按 `data-quad/data-mode/data-period` 定位旧行,逐个 `<td>` 对比新值,只更新变化的 `textContent`(14 列:半凯利/胜率/盈亏比/单笔均收益/样本/最终盈亏/峰值收益率/费率消耗/最大持仓/持仓中/年化/夏普/最大回撤/卡尔玛)。
- 水印(wm badge + cwm badge)单独更新(卡头部小 DOM)。
- 收益:零 DOM 重建、保留行内状态;成本:需拆分 row 渲染 + diff 逻辑,改动更大。

**建议**:先做方案一(改动小、稳定、满足"不闪+对照+loading"),若用户仍觉卡内有感再上方案二。

### 4.4 可选增强(按需)

1. **trades 预取**:首次渲染 sigkelly(L7836 前)后台预取 51MB trades.json 到 `state.labSigKellyTradesData`,首次 toggle 不再撞大下载延迟(消除 1-3s 的首打勾等待)。
2. **非阻塞计算**:`_kellyApplyFeeRecompute` 桶循环(`for (var qk in quadMeta)`,L7562 起)每 N 桶 `await new Promise(r => setTimeout(r, 0))` 让出主线程,顶部 spinner 可动画 + 主线程不冻结。改造中等(把同步函数变 async yield)。残余 ~500ms 若用户仍觉"卡"再上。
3. **数值变化高亮**:in-place 更新时给数值变化的 `<td>` 加短暂背景脉冲(如 600ms `--cell-changed` class),让"对照打勾前后变化"更直观。
4. **周期切换也走 in-place**(可选):目前周期切换整 host 重建,用户未抱怨,可后续统一。

## 5. 改动清单(实施 agent 对照)

| # | 文件 | 位置 | 改动 |
|---|------|------|------|
| 1 | `static-site/lab.js` | L7489-7498 `_kellyRunRecompute` | 删 `host.innerHTML = loadingHtml`(L7494),改加/移 `lab-custom-host--loading` class;loading 文案参数可保留(不再需要整卡 HTML) |
| 2 | `static-site/lab.js` | L8598 `_renderSigKellyCard` | 卡根节点加 `data-quad="${qk}"` |
| 3 | `static-site/lab.js` | L8233-8265 `_renderSigKellyQuadrants` | 抽公共绑定函数(行点击/wm pop/guide pop);新增 `_updateSigKellyQuadrantsInPlace(host, data, period)` 卡片级就地替换 |
| 4 | `static-site/lab.js` | L7701-7720 `_kellyOnFilterChange` | onDone 改调 `_updateSigKellyQuadrantsInPlace` |
| 5 | `static-site/lab.js` | L7616-7660 `_kellyOnFeeChange` | onDone 的 quadrants 渲染改调 in-place(bar 重渲染保留) |
| 6 | `static-site/lab.js` | L7663-7682 `_kellyOnFormChange` | onDone 改调 in-place |
| 7 | `static-site/lab.css` | (新增) | `.lab-sigkelly-host { position: relative; }`(loading `::before` 定位基准);如需高亮加 `.lab-sigkelly-cell-changed` 动画 |
| 8 | `static-site/lab.css` 或 style.css | (可选) | sigkelly 复用 `.lab-custom-host--loading`(style.css L4392 已有,不需新增) |
| 9 | `static-site/lab.js` | L7836 renderSigKellyLab 初始 | (可选)后台预取 trades.json |

**构建上线三步**(改 lab.js 必做):`bash scripts/build_min.py` + `bash scripts/bump_asset_version.py` + **bump `sw.js` CACHE_VERSION**,否则旧 Service Worker 缓存旧 lab.min.js(CLAUDE.md §9)。

**§21 算法公示**:本次不改算法语义,只改交互渲染层;仍建议 grep `purpose-notes.js` 确认无"实时整卡刷新"类描述需同步(降亏过滤说明文案不涉及)。

## 6. 验收口径(实施 agent 自验 / reviewer 查)

1. 打勾/取消任一降亏 toggle:**卡片不消失、不整卡重建**;数值 ~0.5-0.7s 后就地更新(计算期间旧内容半透明 + 顶部细条)。
2. 打勾前后可对照:变化数值与 `5e0865d7f` 之前的口径一致(用同一 `_kellyApplyFeeRecompute` 结果,无算法改动)。
3. 连点多个 toggle / 组合宏:busy flag 防重入仍生效(`_kellyRunRecompute` 保留),最终渲染一次。
4. 周期切换 / 费率切换 / 费率输入框 change:正常(费率 change 不重渲染 bar 保留输入焦点 — L7663 逻辑不变)。
5. 卡内交互不坏:行点击弹交易记录 modal、wm/cwm 水印 hoverpop、卖出模式说明 pop 重绑正常。
6. 首次打勾(未预取时)有 loading 指示,无白屏。
7. min 版验证用**字符串/class 名**(`lab-sigkelly-card`/`data-quad`/`lab-custom-host--loading`)非变量名(terser mangle)。
8. reviewer:`grep` 确认所有 `host.innerHTML =`(sigkelly 路径)只剩首次渲染/周期切换,无 toggle 路径整卡清空残留;跑 docs/smoke-checklist.md 相关 smoke。
