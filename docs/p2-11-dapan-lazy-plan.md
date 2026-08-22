# P2-11 大盘 tab SVG 懒渲染优化 · 实施方案(已实施,懒渲染半边交付)

> 状态:**已实施(2026-08-22)**——按用户拍板范围收窄:只做懒渲染(切大盘 tab 不卡顿),外观零变化,
> 大盘 tab 默认仍是完整 ECharts;`_lwSetup` lite 包装(SVG 半边)不激活,`charts.lightweight` 开关对大盘 tab 行为不变。
> 实施内容=本文档方案 A(懒渲染)+ 方案 C(indexChart 纯搬运重构);方案 B(lite 包装)待后续独立任务放行后接入。
> 分支:feat/p2-11-dapan-lazy(旧 a956cbe5a 零 commit 分支已删,重建于 origin/main@436f6d6bf)。
> 自验结论(Playwright headless,本地 mock 确定性数据):首帧 init 数 A股 23→5、全球 12→2;init 长任务 59/65ms→0;
> 展开+滚动后图表总数与改动前逐 tab 一致(A股23/港股20/全球12canvas+11svg);切走切回无重复初始化;
> 全页截图像素 diff 0.000%(唯一差异为角标时间戳分钟位);retheme 对未 init 代理排队回放正常;无 JS 报错。

## 一、根因(已核实,grep+读码确认)

切大盘 tab(`renderMarket`)时,四个 subtab 的渲染函数在**同一帧内同步执行 30+ 次 `echarts.init` + `setOption`**,构成单帧长任务,即用户感知的 500-1000ms 卡顿。数据 fetch 不是主因(A股指标数据一次 fetch;指数数据已是并发预取)。

## 一、根因(已核实,grep+读码确认)

切大盘 tab(`renderMarket`)时,四个 subtab 的渲染函数在**同一帧内同步执行 30+ 次 `echarts.init` + `setOption`**,构成单帧长任务,即用户感知的 500-1000ms 卡顿。数据 fetch 不是主因(A股指标数据一次 fetch;指数数据已是并发预取)。

各 subtab 的图表创建点:

| subtab | 函数 | 图表来源 | 数量 |
|---|---|---|---|
| A股 | `renderAStock` | 指标分组卡 `lineChart` ×10组 + 指数卡 `indexChart`(经 `renderIndicesSection`) | ~11 + ~10 |
| 板块分化 | `renderIndustry` | 行业网格(本次不动,独立函数) | — |
| 港股 | `renderHK` | 港股通净买入 `lineChart` ×1 + 指数卡 `indexChart`(经 `renderIndicesSection`)+ 港股板块网格 | ~1 + ~11 |
| 全球 | `renderGlobal` | 指数卡 `indexChart` ×9 + extras 卡 `valueChartWithSignals` ×11 | ~20 |

轻量切换现状(第二个根因):
- `lineChart`(L319)与 `indexChart`(L5574)**无条件 `echarts.init`,没有 lite 分支** → 皮肤弹窗"⚡SVG轻量/📈echarts完整"开关(`siteCfg("charts.lightweight")`)对大盘 tab 完全无效。
- `valueChartWithSignals`(L5913)**已内置 lite 分支**(L6019),全球 extras 卡实际已走 SVG,无需改造。

## 二、方案(两条修法结合)

### A. 懒渲染:IntersectionObserver 单例

新增模块级辅助(app.js,插在 `renderAStock` 定义前):

```js
let _marketLazyIO = null;
function _ensureMarketLazyIO() {
  if (_marketLazyIO) return _marketLazyIO;
  _marketLazyIO = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.isIntersecting) {
        const fn = e.target._mktLazyFn;
        if (fn) { e.target._mktLazyFn = null; try { fn(); } catch (err) {} }
        _marketLazyIO.unobserve(e.target);
      }
    }
  }, { rootMargin: "250px 0px" });  // 提前 250px 预渲染,滚动无白卡感
  return _marketLazyIO;
}
function _marketLazy(cardEl, initFn) {
  // IO 不支持(老浏览器)兜底:直接同步 init,行为退回现状
  if (typeof IntersectionObserver === "undefined") { initFn(); return; }
  cardEl._mktLazyFn = initFn;
  _ensureMarketLazyIO().observe(cardEl);
}
```

- 首屏可见卡:IO 对已在视口的元素**下一帧立即回调**,等于把 30+ 同步 init 拆散到多个事件循环帧,单帧长任务消除。
- 视口外卡:滚入视口(rootMargin 提前量)才 init。
- `renderMarket()` 开头(subtab 切换重建时)`_marketLazyIO` 上残留的旧卡 target 已随 `content.innerHTML=""` 脱离文档,IO 自动不再回调 disconnected 目标;再加一行防御:`if (_marketLazyIO) _marketLazyIO.disconnect(), _marketLazyIO = null;` 每次 renderMarket 重建,防跨 subtab 泄漏。

### B. 轻量切换接入:market 专用 lite-aware 包装(零冲突设计)

**核心原则:不改 sim 弹窗/场外基金的行为。** sim 弹窗(`openSignalChartModal` L7345-7346)继续调原 `indexChart(..., body, _signalModalCharts, ...)`;场外基金区(L22405+)完全不动。market 包装只在大盘 tab 渲染链路替换调用点。

新增两个包装函数(插在 `renderAStock` 前):

#### B1. `_marketIndexCard(title, ohlc, signals, stats, strategy, container, indexId, tiers)`
```
lite 开(siteCfg("charts.lightweight", true), 默认):
  ① _lwCardShell(title+suffix, 300, hint, container) 建卡(零 echarts.init)
  ② card 上补 _prependSimBtn / _bindFreqPopupToHintRows(与 indexChart 内部一致)
  ③ 数据转换:data = ohlc.map(d=>({date:d.date, value:d.close}))
     markData = _buildSignalMarkData(signals, date→close)(与 indexChart L5593-5596 同口径)
  ④ liteCfg = _lwSignalLiteCfg(title+suffix, data, markData, {}, null, false)
     (复用现成引擎:单序列折线+信号拼色pin+tooltip;四档色带 lite 下省略,见风险点⑤)
  ⑤ suffix 计算(日期+收盘+pct badge)复制 indexChart L5577-5582 同款
  ⑥ 返回兼容对象 { getDom:()=>div, card, resize, getOption, setOption, dispose }
     (对齐 valueChartWithSignals lite 分支 L6030-6064 的接口形状 + 补 dispose)
完整开(charts.lightweight=false):
  直接 return indexChart(title+suffix, ohlc, signals, stats, strategy, container, charts, indexId, tiers)
  —— 原 echarts 全能力保留(含四档色带 bar series),零回归
懒渲染:两种模式的"真正出图"都包进 _marketLazy(card, fn):
  lite 分支 fn = () => _lwSetup(div, liteCfg, noopEchartsFn)
  完整分支 fn = () => indexChart(...)  ← 注意:indexChart 会往 container append 自己建的卡,
  所以完整分支的懒渲染采用"占位卡"法:先建空 .chart-card 占位(h3+hint),
  IO 触发时把占位卡移除、在原位置调 indexChart(...) 再回填附加按钮。
  (更简替代见"实施取舍"③)
```

#### B2. `_marketLineCard(title, series, opts, hint, container, height)`(多序列指标卡)
```
lite 开:_lwCardShell 建占位卡 → 多序列 liteCfg(参照 _kpiLiteCfg L15137 多系列格式:
  xLabels=合并排序 dates, series=arr.map(s=>({type:"line", data:date对齐后的vals数组,
  color, width:1.5, smooth:true, connectNulls:true})), ys:[{scale:true}], legend,
  tipFn 含序列名+值+unit/scale 口径)→ _marketLazy 包 _lwSetup
完整开:占位卡 + _marketLazy(() => lineChart(...)) 同 B1 完整分支策略
```

#### B3. 全球 extras(`valueChartWithSignals` L16653)**不改**
已内置 lite 分支;其同步建卡开销占比小(extras 卡数据短)。如实测仍卡,二期再把它的建卡也包 `_marketLazy`(接口已兼容,改动一行)。

### C. 抽取共享 option 应用函数(可选深化,首推简化版)

`indexChart` 的 setOption 配置块(L5614-5697,含 tooltip formatter/tierBand/markPoint)可抽成模块级 `_indexChartApplyOption(c, ...)`,`indexChart` 改为 mkCard+调用(对外行为逐字节不变,sim 弹窗无感)。价值:B1 完整分支可在占位 div 上直接 `echarts.init(div)` + `_indexChartApplyOption(inst,...)`,避免"占位卡移除回填"的绕法。
**取舍**:抽取属全局函数内部重构(签名不变),收益是懒渲染路径更干净;风险是多动一处全局函数。两案都可落地,推荐先做抽取(一步到位,§5 准则),reviewer 重点核对 diff 为纯搬运。

## 三、涉及函数锚点(static-site/app.js,base a956cbe5a)

| 符号 | 行号 | 角色 |
|---|---|---|
| `mkCard` / `lineChart` | L306 / L319 | echarts.init 入口(L312);lineChart 无 lite 分支 |
| `indexChart` | L5574-5699 | 指数卡,纯 echarts;setOption 块 L5614-5697(四档色带 L5602-5613) |
| `_lwSignalMarkPoints` / `_lwSignalLiteCfg` | L5797 / L5826 | 现成 lite 引擎件,B1 直接复用 |
| `valueChartWithSignals` | L5913-6074 | **已 lite-aware**(L6019),不改 |
| `renderIndicesSection` | L6623-6805 | indexChart 调用点 L6748;`disposeSectionCharts` L6633(依赖 c.dispose());`sectionCharts.push` L6749 |
| `setupOneRowToggle` | L6411 | A股指标卡 1 行折叠(懒渲染下卡 DOM 先建,折叠不受影响) |
| `renderMarket` | L13632-13674 | subtab 切换入口;L13669 await loadEcharts;observer 重置插入点 L13633 |
| `renderAStock` | L16269-16371 | groups L16282;lineChart 循环 L16343-16354;renderIndicesSection L16365 |
| `renderHK` | L16416-16470+ | lineChart L16431;renderIndicesSection L16448 |
| `renderGlobal` | L16519-16678 | indexChart L16608;valueChartWithSignals L16653(不改) |
| `addCardTimeBadge` | L8142 | 依赖 `chart.getDom().parentElement` → 兼容对象必须实现 getDom() |
| `_lwSetup` / `_lwRenderers` / `_reRenderHomeCharts` | L15088 / L15086 / L15127 | ⚡开关即时重渲染遍历 _lwRenderers 全部注册项 → market 卡注册进去后**开关切换自动生效,无需新写重渲染函数** |
| `_lwCardShell` | L15234 | 等价 mkCard 但零 init |
| sim 弹窗调用(冻结区外,但不许破坏) | L7345-7346 | `valueChartWithSignals(..., _signalModalCharts, ...)` / `indexChart(..., _signalModalCharts, ...)` |

## 四、实施步骤清单

1. 抽取 `_indexChartApplyOption`(纯搬运 L5575-5697 到模块级函数,返回 suffix 供标题拼接);`indexChart` 改为 `mkCard + _prependSimBtn/_bindFreqPopupToHintRows + _indexChartApplyOption + return c`(对外行为不变)。
2. 新增 `_ensureMarketLazyIO` + `_marketLazy`(上文 A 节代码)。
3. 新增 `_marketIndexCard`(B1)与 `_marketLineCard`(B2),均返回 `{getDom, card, resize, getOption?, setOption?, dispose}` 兼容对象;`dispose()` 实现:lite 态清 `_lwRenderers` 注册+清 innerHTML;echarts 态转发实例 dispose 并从 `charts` 数组 splice。
4. 替换调用点(共 4 处):
   - `renderAStock` L16346:`lineChart(...)` → `_marketLineCard(g+..., series, {}, groupHints[g]||null, grid2col)`(后续 `chart.getDom().parentElement` 用法不变)
   - `renderHK` L16431:同上
   - `renderIndicesSection` L6748:`indexChart(...)` → `_marketIndexCard(..., parent, id, sig.tiers)`(`sectionCharts.push(c)` 与 `c.dispose()` 走兼容对象)
   - `renderGlobal` L16608:`indexChart(...)` → `_marketIndexCard(...)`
5. `renderMarket` L13633 后加 observer 重置(disconnect+置 null)。
6. 自验(见五)→ `node --check static-site/app.js` → 本地 uvicorn(trade-data cwd)人工过五项验收。
7. 完成后:只 commit+push feat(分支策略听主控安排,见"待主控确认"),不 bump 版本串(机制 C),进度文件 `/tmp/agent-progress-p2-11.txt` 全程 echo。

## 五、自验清单(对照派单 5 项)

1. `node --check app.js` 过。
2. 本地起服务切大盘 tab:console 打点对比改造前后(改造前单帧 long task >300ms;拆散后单帧 <50ms);滚动下方指数卡,Network/console 可见图延迟初始化(IO 触发打 log)。
3. 皮肤弹窗切 ⚡轻量:大盘 A股指标卡/指数卡出 SVG(无 canvas);切 📈完整:同卡出 echarts 且**四档色带在**;开关来回切即时重渲染(_reRenderHomeCharts 遍历 _lwRenderers 覆盖 market 卡)。
4. 完整模式与改造前逐项对比:指标卡数值/legend/dataZoom、指数卡信号 pin/四档色带/tooltip reason 一致。
5. sim 弹窗(点任一指数信号 pin)出图正常(原 indexChart 路径未被破坏);场外基金 tab 不受影响;`git diff` 确认未触碰 L2459-3060 / L22405-23087 区间。
6. 举一反三核对(§23.3):lineChart/indexChart 全调用点已列全(第三节表),除 market 4 处外其余(sim 弹窗/情绪 tab)保持原路径;`renderFutures`/`renderNationalTeam` 不在本任务范围(图表少且独立,卡顿不在此)。

## 六、回归风险点

1. **sim 弹窗回归**(最高优先):`indexChart` 若做 C 步抽取,diff 必须纯搬运;自验第 5 项强制过。不放心可砍掉 C 步用"占位卡回填"法,indexChart 一行不动。
2. **disposeSectionCharts 类型假设**:L6633 直接 `c.dispose()`;兼容对象必须实现 dispose,漏实现会在切筛选条时报 TypeError。
3. **getDom 形状**:`addCardTimeBadge`/`_appendStrategyHint`/`_appendPinBtn`/`anchorBar._observeIndexCard` 全部拿 `c.getDom().parentElement`;兼容对象 getDom 必须返回 .chart div(parent 即 .chart-card)。
4. **默认外观变化(须用户知情)**:`charts.lightweight` 默认 true,上线后大盘 tab 默认从 echarts 变 SVG 轻量外观(这正是任务目的"开关生效"),但属**默认展示位变化**,汇报时显式声明,由主控/用户拍板;不接受则把 siteCfg 默认判断改为 market 强制读 localStorage 显式值(默认 false 保持 echarts)。
5. **四档色带 lite 缺省**:lite 模式省略底部四档色带(lite 引擎无 bar series 支持);完整模式保留。属轻量降级(与首页 KPI lite 卡同哲学),汇报中声明。
6. **IO 兜底**:IntersectionObserver 不存在时直接同步 init(退回现状,不白屏)。
7. **observer 泄漏**:每次 renderMarket 重建时 disconnect;脱离文档的旧卡 IO 自动失效双保险。
8. **折叠卡与 IO 交互**:setupOneRowToggle 折叠(display:none)的卡不进视口不渲染,展开时 IO 正常触发——预期行为,自验覆盖"更多指标展开后图出现"。
9. **resize 链**:echarts 实例仍在 `charts` 数组,既有 window resize 监听照常;lite 卡靠 _lwBind 自身机制(首页同款)。

## 七、待主控确认后再动手

1. **分支/worktree 安排**:主仓库当前被 P2-15 占用,本任务实施是否改走 worktree 隔离,还是排队等 P2-15 收尾;我此前切的 `feat/p2-11-dapan-lazy` 分支(基于 a956cbe5a,无任何 commit)如何处置听主控安排。
2. **默认外观变化**(风险点4)是否接受默认走 SVG。
3. C 步(抽 `_indexChartApplyOption`)做不做(推荐做,理由见第二节)。

## 复现(本文档为方案文档,无数据产物;实施后的复现命令将随实施 commit 落在代码注释与本节更新)

- 关键路径复核命令:
  `grep -n "function lineChart\|function indexChart\|function valueChartWithSignals\|function renderMarket\|function renderAStock\|function renderHK\|function renderGlobal\|function renderIndicesSection" static-site/app.js`
- 口径一句话:大盘 tab 四 subtab 切换时 30+ 张图同步 echarts.init 致单帧长任务;修法=IO 懒渲染拆帧 + market 专用 _lwSetup lite 包装接通皮肤开关;冻结 sim 弹窗/场外基金原路径。
