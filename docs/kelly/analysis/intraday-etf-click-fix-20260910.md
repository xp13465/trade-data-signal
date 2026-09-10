# 盘中增量表 etf 代码交互修复(2026-09-10)

## 结论
用户反馈「盘中增量回测表格里的 etf 代码没有 hover 样式、点击代码没有弹窗,与底下交易记录里的 etf 代码交互不一致」——已修复,根因+方案+自测见下。

## 根因(两条)
1. **点击无弹窗 = 绑定时机型 typeof 防御**。common.js `_bindEtfClicks`(旧实现)开头:
   `if (!rootEl || typeof window._openEtfTrendPinModal !== "function") return;`
   而 lab.min.js 是**懒加载**(index.html 不再预加载,切 lab tab 才由 app.js `loadLabScript()` 动态注入)。
   首页模拟回测弹窗盘中表渲染时,若用户从未进过 lab tab → `_openEtfTrendPinModal` 未定义 → 直接 return → td.onclick **永不绑定** → 点击无反应。
2. **hover 无样式 = style.css 对 `.kelly-intraday-etf` 零样式定义**(grep 无结果,无 cursor/hover)。

## 修复方案(common.js + style.css,不碰 lab.js/lab.css 主表本体)
- **common.js `_bindEtfClicks` 改容器级 click 事件委托**:
  - 在盘中表容器(rootEl)绑一个 click 委托监听,收到事件时 `ev.target.closest(".kelly-intraday-etf")` 取 td,再从 `td.dataset`(data-code/data-name)实时取参调用 `_openEtfTrendPinModal`——天然免疫 lab.js 加载时序,不依赖绑定时机。
  - 叠加自动懒加载:函数未注入时先走 `loadLabScript()`(app.js 全局,single promise)加载完成后立即弹——**任何展示位/任何加载时序点击都能弹**,首次点击可能多等 ~1s(lab.min.js 下载)。
  - 边界:data-code 缺失的 td 忽略;`loadLabScript` 也不可用(异常环境)才静默无害。
  - 幂等:render 每次新建容器元素 + 元素级 `__kellyIntradayEtfDelegated` 标记防重复绑。
  - `ev.preventDefault()/stopPropagation()` 保序(确认可处理后调用)。
- **common.js 渲染处**:etf 代码包一层 `<span class="kelly-intraday-etf-code-link">`,与主表 `.lab-sigkelly-etf-code-link` 同构(名称 sub-span 保留)。
- **style.css 补样式**(盘中表专用类,定义在 style.css 供两消费点共用,不依赖 lab.css):
  ```css
  .kelly-intraday-etf { cursor: pointer; position: relative; }
  .kelly-intraday-etf .kelly-intraday-etf-code-link {
    color: var(--acc, #4da3ff); text-decoration: underline dotted; text-underline-offset: 2px;
  }
  .kelly-intraday-etf .kelly-intraday-etf-code-link:hover {
    filter: brightness(1.25); background: rgba(77, 163, 255, 0.12); border-radius: 3px;
  }
  ```
  视觉语言与主表 `lab-sigkelly-trades-etfcode`(lab.css L2157-2167)逐项对齐(cursor/primary 蓝/dotted 下划线/hover 高亮)。

## 同类错误面清单(§23.2 修 bug 三铁律)
- **同根因(依赖懒加载全局函数 + 绑定时机 return)**:盘中表两消费点(首页模拟回测弹窗 app.js `_simRenderIntraday` / lab 凯利交易记录弹窗 lab.js L12701)共用 common.js `_bindEtfClicks` 单实现 → 一处修复两处生效(§22 单源)。
- **同组件其它可点击位**:盘中表仅 etf 代码列可点击(与主表一致,主表其它格子无点击交互)→ 无其它遗漏位。
- **同交互模式其它展示位**:主表交易记录 etf 交互(lab.js L12813/lab.css L2157)不受影响——本次未改 lab.js/lab.css 本体,只加样式。

## 自测证据(Playwright 无痕零 localStorage,真实 index.html + 本地 server + 拦截活跃盘中产物,15 项全 PASS,无 pageErrors)
- 盘中表渲染 ✓ / etf td 存在 ✓ / 代码包 link span ✓ / cursor=pointer(hover 样式生效)✓ / data-code/data-name 携带 ✓
- **时序复现**:初始未进 lab tab(`_openEtfTrendPinModal` undefined)→ 点击 etf → lab.min.js 自动懒加载注入 → `lab-etf-pin-overlay` 弹窗出现(display=flex)✓ / 弹窗标题「📈 510300 沪深300ETF · ETF 走势与买卖/强平点」✓
- 二次点击(函数已加载)直接弹 ✓
- **边界**:手动注入 data-code 缺失 td → 点击无害(不弹不崩)✓ / 其它列点击不弹(委托只认 `.kelly-intraday-etf`)✓
- **lab 消费点模拟**(同款 opts `{mode:A, modeId:s06, fadeOn:true, K:1}` 重渲染)→ 渲染 ✓ / 点击直接弹 ✓

## 举一反三(§23.3)
- 同组件消费点:首页弹窗 + lab 交易记录弹窗两处全验证。
- 同数据源(盘中产物):盘中视图降级态(17:50 后/换日不渲染)不涉及点击,无额外处理。
- 同交互模式:主表 etf 代码交互为对齐基准,已确认不受影响(未改其绑定/样式)。

## 复现
- 脚本:`/tmp/intraday-etf-click-test.mjs`(Playwright,启动本地 server 后执行)
- 输入依赖:worktree `static-site/`(含修复后源码 + build_min 产物)+ 首页 overview 等数据(用主仓库 static-site/data 软链)+ 盘中产物(测试脚本 route 拦截喂活跃数据:mode=intraday, next_open_date=今日)
- 重跑命令:
  ```bash
  python3 -m http.server 8130 -d /tmp/intraday-serve &   # /tmp/intraday-serve = worktree static-site 代码 + 主仓库 data 软链
  node /tmp/intraday-etf-click-test.mjs                   # 断言盘中表渲染/样式/点击弹窗/懒加载时序/边界/回归
  ```
- 数据截止:盘中产物测试用拦截数据(测试脚本内构造,非真实产物);真实线上数据验证见下方「验证口径」。
- 关键口径:盘中表渲染前提=`intraday.mode=='intraday' && next_open_date==今日 && 时间<17:50`(common.js `_bannerHtml`);etf 代码点击=容器事件委托 → `_openEtfTrendPinModal(code, nm, _lastUnique, [], d.fields, tr, null)`(事件源=过滤+top-K 后行集)。

## 验证口径(上线后由主控/测试补)
- 首页模拟回测弹窗盘中表:etf 代码蓝色 dotted 下划线 + hover 高亮 + pointer 光标;点击 → 走势弹窗弹出。
- 未进过 lab tab 直接点 etf → 首次点击稍等(lab.min.js 懒加载)后弹窗弹出。
- lab 凯利交易记录弹窗内嵌盘中表:同交互。
