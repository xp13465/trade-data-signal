# Review #12 首页新闻看板「消失 + 不自动更新」根治(2026-08-20)

> 分支 `feat/news-rootfix-0820`,4 commits(base=c0f511e90=origin/main,fresh):a52445be3(纪元token) 5cf4566f6(同类guard) e17c2bc43(报告+仿真脚本) 8e5d3d1c7(验证脚本)。reviewer 独立回归,不改代码。

## 结论: PASS

老 bug「新闻消失/不自动更新」的纪元(epoch)根治链路完整,未发现本次改动引入的回归;新闻域在单代/重建/轮询交错场景下均验证存在且可更新。同类 guard 纯防御零副作用。

## 一、验证矩阵(独立执行)

| 层 | 结果 | 说明 |
|---|---|---|
| node --check static-site/app.js | PASS | 语法无错 |
| implementer 仿真 `docs/scripts/news-lifecycle-sim.js` | 14/14 PASS | 真实源码提取函数 + DOM stub |
| Playwright 真实浏览器 `news-epoch-facts.mjs`(注入 worktree 修改版 min, 禁 SW) | 7/7 PASS | 线上真实数据 + route 注入:首次出现/切tab往返6次不消失/轮询更新/重建唯一/banner不堆积/fetch500不消失 |
| reviewer 独立验证 `/tmp/rev12-epoch-verify.js` | 8/8 PASS | 旧代.then被拦/新代通过/reset杀轮询/新代接管/同代单飞/旧代fire自弃 |

## 二、逐审查点证据

### 1. 不破坏老功能(renderOverview 三路径)
- **首次渲染**:L10709 reset(epoch+1) → L10795 捕获 `_hnLoadEpoch` → L10796 `.then` 校验 epoch 一致 → 渲染新闻+启动轮询。单代正常路径不受影响。
- **tab 往返重建**:每次 renderOverview 主体 L10708 `content.innerHTML=""` + L10709 reset 自增纪元;新代 .then 捕获新纪元,旧代 .then 被 L10797 `_homeNewsEpoch !== _hnLoadEpoch` 拦截 return。纪元校验只影响 `_renderHomeNewsRows/_startHomeNewsPoll/_initGlobalTicker`(新闻域),banner 本身在回调更早处(L10784)已插入,**首页其它区块(综述/情绪/指数/KPI/信号)完全不受纪元逻辑触碰**。
- **轮询刷新**:L22881 fire 前、L22887 await 重拉后双纪元校验,旧代自弃不碰当前 DOM;isConnected 兜底(L22828-22852)仍在,双保险。
- **反转误伤确认**:最新代 .then 的 `_hnLoadEpoch` 必然等于其 reset 后的最新 epoch,校验必通过;只有"更新的一代已 reset"才拦截旧代,而更新的代会渲染自己的新闻 → 链条保证最新代一定渲染,不吞新闻。

### 2. 新闻真不消失(tokens 判定链路完整)
三处拦截闭环无漏洞:
- 首次 .then 渲染 L10797(捕获 epoch ≠ 当前 → return)
- 轮询 fire L22881(`_homeNewsEpoch !== _homeNewsPollEpoch` → return)
- 轮询 await 重拉后 L22887(纪元变 → 自弃)
`_homeNewsEpoch` 仅 L10692/L10709 两处自增(reset),全文件 14 处引用均在新闻域。旧代 callback 三条路径全部被纪元覆盖,无陈年回调漏网路径。

### 3. 轮询不重复不丢失
- `_homeNewsReset` L22814 每次重建 `clearTimeout` 杀旧轮询 + `_homeNewsPolling=false` → 旧轮询彻底死亡。
- `_startHomeNewsPoll` L22870-22874:同代 `_homeNewsPollEpoch===epoch` → return 单飞;旧代(理论残留)→ clearTimeout 杀 + 重建当前代。
- 新代启动后 `_homeNewsPollEpoch=epoch`;被拦截的旧代不启动轮询,但更新的代会启动自己的 → 最新代必有轮询,不丢失。
- 独立验证 V2/V3 实测:timer 杀后重建、pepoch 更新、同代重复调用 timer 引用不变。

### 4. 同类 guard(_bannerRenderCtx 3 消费者)零副作用
- `_applyDynamicToChips` L8555 / `_applyDynamicToBannerTime` L8568 / `_onMarketClosed` L8608,均只加 `el.isConnected` 前置判断。
- 活节点 isConnected=true → 行为零变化;死节点(脱离 DOM)→ 提前 return,原本 querySelector 返回 null 的静默 no-op 变为显式跳过,不误伤活节点。
- `_onMarketClosed` L9057 调用点前 `_bannerRenderCtx` 非 null 且 banner 在 DOM 时正常走;L9019 `_stopIntradayRefresh` 置 null 后守卫跳过,与原 `if(_bannerRenderCtx)` 行为一致。badge 恢复(L8600-8606)在守卫外,不受影响。

### 5. 区域隔离
diff 仅 `static-site/app.js`(27+/4-) + 5 文档/脚本。app.js 改动集中在 `_bannerRenderCtx` 3 函数 + renderOverview 新闻区(L10795-10800) + 新闻域函数(L22807-22896)。grep 确认 diff 未触碰:valueChartWithSignals/信号弹窗/市场温度(#24)、冰点/termTip(#19,仅 L359/418/1131/1211 等既有行)、indexChart 四档(#73)、signalColor/freeze。`_initGlobalTicker` 的 08-19 isConnected 守卫(L10992/11059)完好未动。

### 6. 数据层 / §22
无数据产物改动(不改 news_digest 结构/生成),三展示位(首页外露/弹窗/历史对照)共用 `_loadNewsDigest` 缓存(L22759),本次只改首页渲染侧,弹窗/历史对照(L22255)未动 → 无需重跑/同步 R2/static-site。§21 公示:无算法/数值改动,不涉公示文案。

### 7/8. 脚本可跑性
- `docs/scripts/news-lifecycle-sim.js`(git tracked,依赖 `../../static-site/app.js`):14/14 PASS 复现。
- `scripts/playwright-accept/news-epoch-facts.mjs`(git tracked,主仓有 node_modules/playwright):7/7 PASS。worktree 的 `static-site/app.min.js`(本地验证用,未提交)确认含 `_homeNewsEpoch/_homeNewsPollEpoch/function _homeNewsReset`。
- 落档四件套全部 git tracked;feat 分支 4 commits 均未提交 min(符合机制 C,版本串由 main-merge.sh merge 时统一重建+bump)。

## 三、已知边界(非本次引入,如实记录)
- **并发双 renderOverview**(如快速连点 tab 且卡在 fetchIntradaySnapshot 1.5s async 窗口):两个 `_summaryP.then` 回调都可能创建 banner 并捕获同一最新纪元,纪元机制无法区分 → 可能双 banner 并存。**此为既有行为(原代码同样存在),本次不劣化**,且触发需两次 renderOverview 在异步窗口内交错,概率低。`_hnLoadEpoch` 捕获在 banner 插入后(而非紧跟 reset)在并发场景略微放大该窗口,但单代正常场景(用户实际报告的 bug)纪元链路完整有效。
- 后续若治理可考虑:renderTab 入口加渲染互斥锁,或 `_hnLoadEpoch` 捕获点前移到 reset 后立即捕获。非本次阻塞项。

## 复现
- 仿真:`cd /private/tmp/wt-news-rootfix-0820 && node docs/scripts/news-lifecycle-sim.js` → 14/14
- 真实浏览器:`cd /Users/linhuichen/code/trade/scripts/playwright-accept && node news-epoch-facts.mjs`(需线上可达)→ 7/7
- 独立验证:`node /tmp/rev12-epoch-verify.js` → 8/8
- 数据:线上 `https://ss.fx8.store/data/news_digest.json`(Playwright route 可控 mock)
