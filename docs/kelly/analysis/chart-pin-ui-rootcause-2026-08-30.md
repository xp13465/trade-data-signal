# 凯利走势图弹窗 pin UI 根因(2026-08-30)

> 调研对象=commit 5a7641692「ETF弹窗正式/淘汰区切换+popover固定顶部不遮pin+触发行配对pin高亮」引入的 ETF 走势+pin 弹窗。用户点 G 模式 516250 交易记录弹出走势图后发现 5 个问题。本文档只读查证,不改代码。

## 涉及代码(定位锚点)
- 弹窗主函数 `_openEtfTrendPinModal` @static-site/lab.js:12147
- 事件收集 `_collectEtfPinEvents` @static-site/lab.js:12120
- 坐标换算 `svgPointToWrap` @static-site/lab.js:12269
- pin 排布 `_placePins` @static-site/lab.js:12440
- pin 配对构建 @static-site/lab.js:12299-12304
- 走势几何 `_etfTrendGeom` @static-site/app.js:23613
- 走势渲染 `_etfTrendLiteHTML`/`_etfTrendLiteBind` @static-site/app.js:23742/23763
- pin 样式 @static-site/lab.css:2142-2284

## 问题1 pin 配对算法:为什么"1卖点只配1买点"
**代码做了什么**:每个 buy 事件从 `_sellByRow`(Map:交易行引用 t -> 该行 sell/force 事件)取同行的 sell。配对键=同一交易记录行引用 `b.t === sell.t`。
- 证据:lab.js:12293-12302 `_buyEvs.map((b)=>{ const sell = (b.t != null) ? (_sellByRow.get(b.t) || null) : null; return {pid,buy,sell,...}; })`;lab.js:12294-12297 `_sellByRow` 构建(每行至多一条 sell,异常重复留先到者防连线错配);lab.js:12288-12291 注释"不复用日期 FIFO+数组下标配对(交易交错时第N买!=第N卖会张冠李戴),改用原交易行引用 t:同 ETF 组内 buy.t===sell.t(同一行记录)才是确定的真对"。
**结论**:**这是设计,不是 bug**。凯利回测一笔交易=一行记录=1买+1卖(含强平);一行天然 1买1卖,故每个 sell 只配同行的那个 buy;持仓中无卖的单 buy 不配对、不连线(lab.js:12300 sell=null)。
**修复方向**:配对语义正确无需改。若用户期望"分批卖出(1买配多卖)"或"1卖配多买",是需求变更(需先确认回测数据是否支持分批结构,当前每行固定 1买1卖)。

## 问题2a 同一天多个 pin 横向排列(用户认为应竖向叠加)
**代码做了什么**:同日多事件按组内索引 `ei` 横向偏移 14px 排布。
- 证据:lab.js:12343-12344 注释"pin 横排:同日多事件水平微错";lab.js:12344 `evs.forEach((e, ei) => {` 把 ei 存入 pin 对象 `pobj.ei`(12349);lab.js:12445 `const x = pt.x + p.ei * 14;` 每个 pin 的 left = 曲线锚点 x + ei*14,横向错开。
**根因**:`p.ei * 14` 强制同日 pin 横向偏移(设计为"避免重叠"),但用户语义期望是同日=同一 x(竖向堆叠标签),横向错开会被误解为不同天。
**修复方向**:同日多 pin 改竖向叠加——dot 共用同一 (x,y) 锚点(ei 偏移归零或仅极小防压),标签 txt 改上下错开(把 `ei * 14` 从 x 偏移改到 txt 的 y 偏移,让标签竖向堆叠不压 dot)。**依赖问题2b 的 dot 定位先就位**。

## 问题2b pin 和走势线日期点"完全不挨着"(516250)— P0 根因
**代码做了什么**:pin 元素 = dot+txt 横向 flex 容器,CSS `transform: translate(-50%,-50%)` 把整个容器的几何中心对齐到锚点 (x,pt.y)。但 dot 在容器最左、txt 在右,导致 dot 实际中心偏离锚点左侧约 (txt宽+gap+dot)/2 约 27px。
- 证据:lab.css:2142-2150 `.lab-etf-pin { position:absolute; transform: translate(-50%, -50%); display:flex; align-items:center; gap:5px; }`;lab.css:2152-2160 dot 9x9px;lab.css:2172-2182 txt(font 11px、padding 2 5、宽约 50px);lab.js:12445-12447 `p.el.style.left = x; p.el.style.top = (pt.y - 4)` 设锚点(pin 中心对齐此点)。
- 连带:连线连的是 svgPointToWrap 返回的**锚点**(lab.js:12321-12322 `_arrangeLine` 用 `svgPointToWrap(p.buy.ix)`/`p.sell.ix`),不是 dot 实际位置,故连线与飘移的 dot 也分离(用户观感"不挨着"含此)。
**坐标数学本身正确(已验证,非坐标函数 bug)**:svgPointToWrap(lab.js:12269-12286)用 `_etfTrendGeom` 的 `_px(sl)`/`_py(close)` 做 viewBox->CSS 像素换算,ratioX=svgR.width/Wcur、ratioY=svgR.height/200;viewBox=0 0 _W 200 + `preserveAspectRatio="none"`(app.js:23751)下数学自洽,锚点 (x,pt.y) 就是曲线当日 close 点。
**数据验证(非 omitted 致 pin 不显示)**:516250-all.json 含 20260710(idx=131,close=0.9721),dateIdx 命中,pin 正常创建并定位;ohlc 为前复权(adj=forward_accum_nav,价格 0.9~1.0),pin y 锚用 ohlc close、走势线同源 close,y 方向本应重合。**问题纯在 CSS 定位基准**。
**根因**:`.lab-etf-pin` 的 `translate(-50%,-50%)` 作用于"dot+txt 整体"而非"dot 单点",dot 被推离曲线锚点;锚点是对的、dot 位置是错的。
**修复方向**:让 dot 中心对齐锚点,txt 作为 absolute 子元素挂在 dot 旁(不参与 flex 居中)。示例改法:
- `.lab-etf-pin` 去 translate(`transform:none`),保留 `position:absolute`;
- `.lab-etf-pin-dot` 加 `position:absolute; left:0; top:0; transform:translate(-50%,-50%)`(dot 中心=pin 的 left/top=锚点);
- `.lab-etf-pin-txt` 改 `position:absolute; left:8px; top:-13px`(相对 dot 右上,或按需上/下);
- 或最小改动:保持 DOM,把 `translate(-50%,-50%)` 从 `.lab-etf-pin` 移到 `.lab-etf-pin-dot`(只对 dot 居中),`.lab-etf-pin` 改 `transform:none` 并让 dot absolute。
修复后连线(连锚点)与 dot 重合,问题2a 竖向方案也能落地。

## 问题3 正式区/淘汰区走势图区间不统一
**代码做了什么**:切区时 renderZone 按当前区事件日期重算聚焦窗口 [dMin-60交易日, dMax+30交易日],两区事件日期范围不同->窗口起点终点不同->曲线区间不同。
- 证据:lab.js:12233-12235 `const evDates = events.map(e=>e.date).sort(); const dMin=evDates[0], dMax=evDates[evDates.length-1]`;lab.js:12237-12244 聚焦视图 i0/i1 算法(每区独立:`for i... if(ohlc[i][0]>=dMin) i0=max(0,i-60)...`);lab.js:12218-12219 `renderZone=(zone)=>{ const events = allEvents.filter(e=>e.src===zone); ... }`(切区只看本区事件)。
**根因**:每区独立算窗口,无统一基线。正式区与淘汰区事件日期跨度不同(淘汰区是被过滤的特定时段交易),自然窗口不同;切区重渲染整块图表(lab.js:12252 `chartArea.innerHTML=...`)使区间跳变更明显。
**修复方向**:统一区间基准——切区时复用"两区并集事件日期范围"或"全 ohlc 史"算 dMin/dMax 窗口,只过滤 pin 显隐(不重算曲线区间),让两区曲线同一段、只 pin 多寡不同。516250 仅 166 天可全显不窗口化(短期上市天然满足 `i1-i0<30` 退化全史分支 lab.js:12242-12244)。

## 问题4 hoverpop 滚动条+字体
**代码做了什么**:顶部 info 条 `.lab-etf-pin-infobar` 设 `min-height:56px; max-height:64px; overflow:auto`;详情态(is-detail)装 6 行内容(买入/卖出/持有/收益率/净利/费率,lab.js:12382-12403 `_popContent`),每行 line-height 1.6 x font 11px 约 17.6px x 6 约 106px + head + padding 约 145px,超 max-height 64px -> 触发纵向滚动条。
- 证据:lab.css:2324-2336 `.lab-etf-pin-infobar { min-height:56px; max-height:64px; padding:8px 12px; overflow:auto; }`;lab.css:2337 `.lab-etf-pin-infobar.is-detail { flex-direction:column; align-items:stretch; justify-content:center; gap:2px }`;lab.css:2270 `.lab-etf-pin-pop { font-size:11px; line-height:1.6 }`(详情行字体);lab.css:2284 `.lab-etf-pin-pop-fee { font-size:10px }`(费率更小);lab.css:2340-2342 `.lab-etf-pin-infobar-msg { font-size:12px }`(默认态字体)。
**根因**:max-height:64px 对详情态太矮(详情需约 145px),强制滚动;用户"横向空间够不该滚"实际是纵向滚动(内容超高),字体 11px 偏小、fee 缩到 10px 格式不统一。
**修复方向**:详情态取消 max-height 限制(改 `max-height:none` 或单独 `.is-detail { max-height:none; min-height:auto }`),让 info 条自适应内容高度不滚;字体统一 12-13px、fee 不再缩到 10px;或精简详情行数。注意改高度兼顾 modal `max-height:94vh`(lab.css:2350)不撑破弹窗(chart 区 flex:1 可压缩)。

## 修复优先级汇总
1. **P0 问题2b**:改 pin 定位基准(dot 居中锚点,txt absolute 挂旁)——根治"不挨着"+连带修连线分离。改 lab.css:2142-2182(+可选 lab.js DOM)。
2. **P0 问题2a**:同日 pin 竖向叠加(dot 共锚点 ei*0 或极小,txt 竖向错开)——改 lab.js:12445 `p.ei*14` 从 x 改到 txt 的 y。依赖 2b 先就位。
3. **P1 问题4**:info 条详情态去 max-height 64 限制 + 字体统一。改 lab.css:2324-2336/2337。
4. **P1 问题3**:切区统一区间基准(并集日期或全史)。改 lab.js:12233-12244。
5. **P2 问题1**:配对语义无需改(同行配对正确);若用户要分批卖出是需求变更。

## 复现
- 脚本路径:本报告配套验证脚本 3 支已归档 `docs/kelly/analysis/scripts/`(真实浏览器 smoke,Playwright,验证 pin 定位/竖叠/info条/缩放平移等修复项):`pin-zoom-smoke.cjs`(缩放/平移内核)、`pin-ui-fix-render-smoke.cjs`(2b dot 中心/2a 竖叠/4 infobar)、`pin-xn-aggregate-smoke.cjs`(卖 ×N 聚合标注)。另手动复现+数据校验命令如下。
- 输入依赖:`static-site/data/etf/{code}-all.json`(线上 R2 直链 https://ss.fx8.store/r2/etf/{code}-all.json,fallback 本地);凯利交易记录数据(signal_kelly_trades.json,经 `_renderSigKellyTradesModal` 渲染)。
- 重跑/复现命令:
  1. 验数据(确认 dateIdx 命中,排除 omitted 致 pin 不显示):`python3 -c "import json;d=json.load(open('static-site/data/etf/516250-all.json'));o=d['ohlc'];print(d['code'],d['name'],'n=',len(o),'20260710_idx=',[i for i,r in enumerate(o) if str(r[0])=='20260710'],'close=',[r[4] for r in o if str(r[0])=='20260710'])"` -> 输出 `516250 工程机械ETF富国 n= 166 20260710_idx= [131] close= [0.972...]`。
  2. 定位 CSS 锚点:`grep -n "translate(-50%" static-site/lab.css` -> `.lab-etf-pin { transform: translate(-50%, -50%); }`(2144 行,问题2b 根因)。
  3. 线上复现:打开 ss.fx8.store 凯利信号实验 -> G 模式 -> 点 516250 交易记录行的 ETF 代码格 -> 弹出走势图,观察:pin dot 飘离曲线点(左侧约27px)+ 同日多卖 pin 横向错开 + 切正式/淘汰区曲线区间变 + hover pin 顶部 info 条出纵向滚动条。
- 数据截止日期:516250-all.json 最新 20260827;调研日期 2026-08-30。
- 关键口径一句:pin 的 y 锚用 ohlc 当日 close(前复权)、标签显示真实成交价(不复权);走势线同源 ohlc close。坐标数学正确,bug 在 CSS `translate(-50%,-50%)` 作用于 dot+txt 整体致 dot 偏离锚点。
