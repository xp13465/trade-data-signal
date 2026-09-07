# sigkelly 渐进加载「补齐后灰蒙层锁屏」+ 静默化 + 首页弹窗渐进(2026-09-07)

> 排查+方案(不实施)。对应 user 2026-09-07 诉求 4 点;前两轮已修 y1 先渲染(8b4e8a239 上线 a550)+ 阶段2失败自愈(ccafb9c8f),本次为残留问题。
> 测试基准=当前线上行为(§5.4⑦ 页面实测锚点优先,Playwright 无痕零缓存)。

## 一、结论摘要

| # | 结论 | 证据 |
|---|---|---|
| A | 线上 = 本地最新版(lab.min.js md5 双端一致),用户非看旧缓存 | md5 b01f481f…,版本串 20260907-a554 |
| B | 「补齐后再次灰蒙层锁屏」= 初始 recompute 遮罩全程只 ON 一次(7.8~20.4s 连续 12.6s),全量补齐后并没有「重新加遮罩」;用户感知的「又锁屏」= 同一遮罩在阶段2 下载完成(13.5s)后进入全量重算(~7s)期间持续存在,全程 pointer-events:none 锁交互 | 实测时间线见「## 复现」 |
| C | 全量重算必要但遮罩非必要:重算期间 UI 各区域显示已就绪数据/占位,无残缺数(§23.15 gate),遮罩只带来「数据已出还锁着」的误导 | 区域状态分析见 §三.1 |
| D | 阶段2 进度提示「全量补全 N/16(近1年已可看)」来自 _labKellyProgStr(),显示在占位元素;可降级 console 或去数字保留轻提示 | L8645/L11327/L11449/L12010 |
| E | 首页「模拟回测」弹窗根因:2026-09-05 #51 加「净资产曲线初始资金=全史峰值×¥10000 恒值」后,_simRenderOnce 无条件 _simEnsureRange("20110101",…) 拉全史 16 片,默认 3 个月窗口也被迫等 16 片 | app.js L4153-4163 |
| F | recent 热区实测覆盖 20260706~20260903(约 60 天);默认 3 个月窗口只需 t2026 1 片、500 天窗口只需 t2025+t2026 2 片 | recent.json 实测 |

## 二、现象①「2/2 加载完还提示全量补齐 5/16,数据展示后没过几秒又锁 loading」

时间线(线上实测,headless chromium 无痕零缓存,offset 校准,详见「## 复现」):

| 相对秒 | 事件 |
|---|---|
| 7.81 | recompute#1 加遮罩(HOST_LOADING_ON),占位文本「⏳ 计算中… · 近1年数据 0/2」 |
| 10.59 | 近1年数据 1/2 |
| 10.82 | 近1年数据 2/2 → Y1_READY,阶段1 完成,y1 数据就地渲染;PROG 立即变「全量补全 2/16(近1年已可看)」 |
| 11.7~13.5 | 其余 14 片下载完成 |
| 13.52 | ALL_READY,阶段2 完成 → _labKellyOnAllReady 清缓存 + 触发全量重算,遮罩保持 ON |
| 20.41 | 全量重算完成 HOST_LOADING_OFF(遮罩移除) |

- 最终状态:loading=false,y1/all 就绪,主卡 10 行,无占位残留,无 pageerror。
- 关键结论:遮罩只 ON 一次(7.8s),从未中途 OFF;全量补齐完成(13.5s)后没有「再次」加遮罩。用户描述「数据展示出来后没过几秒全量补齐好,页面又进灰朦层锁住 loading」实际 = 遮罩连续存在,阶段2 补齐到全量重算完成期间(13.5~20.4s,约 7s)用户看到灰蒙 + 锁交互。
- 现象①后半句「担心补齐后又一次计算会覆盖前一次、最终全量算完才展示」:覆盖确实发生(全量 recompute 重写 state.labSigKellyFeeStats),但 y1 周期数字与阶段1 渲染逐 cell 一致(缓存签名 |parts=Y1/A 隔离 + 既有验收脚本 B1 断言 PASS);且 y1 在 10.82s 已展示,并非「全量算完才展示」。
## 三、现象②根因(补齐后灰蒙层锁屏)+ 现象③隐私窗口同象

### 3.1 源码链路(补齐全过程有两个「遮罩/占位」机制,需区分)

**机制一:loading 遮罩(用户感知的灰蒙层)** — `.lab-custom-host--loading`(style.css L5035-5037):opacity 0.5 + pointer-events:none + 顶部细条动画。
加遮罩入口统一在 `_kellyRunRecompute`(lab.js L8342):
- L8350 `host.classList.add("lab-custom-host--loading")` → await _kellyNextPaint(双 rAF)→ 同步重算 → 收尾 L8381 `classList.remove`
- 触发链:阶段2 下载完成 → `_labKellyOnAllReady`(L8698)→ `_kellyClearComputeCaches()` + `state.labSigKellyTradeDims = null` + `_kellyOnFilterChange({keepS06:true})`(L8705)→ `_kellyRunRecompute` → 加遮罩。
- **注意:实测此遮罩在 recompute#1 时已加上且从未移除(所有 recompute 都在 busy/pending 合批中连成一条),全量重算就是同一遮罩的最后一程,并非「补齐后重新加」。**

**机制二:占位文本(「⏳ 全量分片加载中… / 计算中… 全量补全 N/16」)** — `.lab-sigkelly-all-loading`(lab.css L1768),三处:
- L11327 推荐区 A/F/J/G 实时表(依赖 feeStats.all.all,阶段1 未就绪 → 占位)
- L11449 全信号表(feeStats.all 未就绪 → 占位)
- L12010 K 档评级/周期卡(该周期片数不够 → 占位卡)

### 3.2 全量重算期间各区域显示分析(「遮罩非必要」的证据)

阶段2 完成(ALL_READY,13.5s)→ 全量重算完成(20.4s)之间的 7s,若去掉遮罩,各区域显示:
- 主卡 y1:**
```
已就绪(10.82s 已渲染,数字正确)**
全信号表(默认周期 y1):已就绪(y1 阶段 feeStats.all.y1 有效,L8953 就绪周期正常算)**
推荐区 A/F/J/G(all 口径):占位「⏳ 全量分片加载中…」(y1 stats 中 all=null,L8980 gate)**
K 档评级:阶段1 门控静态快照(L10388-10389 标注「阶段1完成但全量未就绪 → K档评级仍为静态快照」)
```
→ 无任何区域显示残缺数(§23.15 gate:未就绪周期只占位不产数)。遮罩唯一作用是「锁交互」,而交互(切周期/toggle)本身会触发带遮罩的新 recompute(busy/pending 合批),不存在竞态脏数据。

### 3.3 全量重算为什么需要 ~7s(遮罩时间长的加重因素)

- `_labKellyOnAllReady`(L8698)清空三层缓存:_kellyClearComputeCaches(全特征/重算/桶缓存)+ state.labSigKellyTradeDims=null(维度表基于两片构建必须重建,L8539 重建)。
- 全量 16 片数据(约 69MB,t2026=13.5MB/t2025=16.4MB)是 y1 两片的 ~2.3 倍,特征/重算/桶全部从头,7s 为本地带宽下实测(卡在计算非下载)。
- 缓存签名带 parts 标记(L8819 `|parts=Y1/A`):y1 阶段 vs 全量阶段 cacheKey 必不同,强制全量重算(正确,防 y1 缓存被全量误命中污染)。

## 四、现象②方案(补齐后灰蒙层)

### 方案 A(推荐,标注:「纯 bug 修复」— 补齐路径遮罩非必要,静默重算不改变任何展示数字/口径)
目标:全量补齐→全量重算全程后台,完成才无缝覆盖,不锁屏不遮罩。

**最小改动**:
1. `_kellyRunRecompute(host, loadingHtml, onResult, onDone, silent)` 加第 5 参 `silent`,为真时跳过 L8350 的 `host.classList.add(...)`(收尾 remove 无害保留,防状态残留)。
2. `_kellyOnFilterChange(_opts)` 支持 `_opts.silent` 透传(仅一处调用点 L9346 的 _kellyRunRecompute)。
3. `_labKellyOnAllReady`(L8705)改调 `_kellyOnFilterChange({ keepS06: true, silent: true })`。

**影响面**:仅阶段2 完成路径。用户主动交互(切周期/toggle/费率/K档)仍带遮罩(正常反馈)。驳斥「会看到旧数字」的论证见 §3.2。
**风险**:
- 全量重算期间若用户切到非 y1 周期(如 y10),`_labKellyPeriodIsReady` 已 true(ALL_READY),但 feeStats 还是 y1 版(该周期 null)→ 理论渲染空表;但切周期本身触发 `_kellyOnFilterChange`(带遮罩的新 recompute,busy/pending 合批),空表窗口被切周期自己的遮罩覆盖,无残影。
- `pointer-events:none` 移除后,全量重算期间用户可点 toggle——recompute busy 中到点置 pending,收尾按最新态重跑(既有合批机制,与现状一致)。
- §5.4⑥ 不含动默认组合/算法,不改缓存签名不下发新版本。
- **K 档评级间隙(L9082 门控铁律:阶段1 不发布动态源)**:ALL_READY 后、全量重算完成前(~7s),`_labKellyAllReady=true` 但 `_AI_POSCAP_RATING_DYNAMIC_LAB.computed` 仍是 false → common.js `_aiPoscapRatingSrc` 回退静态快照(v1.1.4 历史口径)。同时 L10389 的「⏳ 全量计算中」标注条件(`_labKellyY1Ready && !_labKellyAllReady`)已不满足 → 标注消失,用户看到「无标注的静态快照数字」,与全量后实时数字不同,可能短暂困惑。
  → **方案 A 配套微调**:`_pcProgNote`(L10388-10389)条件改为 `_labKellyY1Ready && !(_AI_POSCAP_RATING_DYNAMIC_LAB && _AI_POSCAP_RATING_DYNAMIC_LAB.computed)`(即动态源未就绪即标注),保证间隙期用户仍能看到「全量计算中」标注;全量重算完成写 computed:true → 标注消失 + 数字原地刷新。此项一并归入「纯 bug 修复」。

### 方案 B(可选叠加,「改已上线功能」待用户 §23.7 确认):白嫖式减少全量重算时长
Y1 周期的 stats 在两阶段间数字相同(已实证逐 cell 一致),全量重算时 y1 周期可复用 y1 阶段桶结果——但缓存签名 parts 标记已强制全量重算,简化做法=把「y1 周期」从重算中省出需动 statsByPeriod 结构,复杂度高。若 A 落地后 7s 无遮罩已可接受,B 可不做(§3.2b 别过度建模:量化影响为 0,不新增维度)。

## 五、现象③(静默化提示)

**现状**:阶段2 进度提示「全量补全 N/16(近1年已可看)」来自 `_labKellyProgStr()`(L8647-8659 阶段2 分支),显示在三个占位元素(§3.1 机制二);每片加载完成已 console.log(`[sigkelly] 已加载 tYYYY`,L8610-8611)。

**判定**:
- 提示的本质信息 = 「还有区域(推荐区/K档评级/非 y1 周期)在后台补」,因为 §23.15 不能显残缺数,这些区域必然有占位;占位文本是否带「N/16」,不改变「区域未就绪」这一事实。
- 用户诉求「只要后台/console 展示即可」→ 建议:占位文本降级为无数字轻提示「⏳ 后台补齐其余周期,完成后自动展示…」(保留存在感防用户误以为卡死),进度数字 N/16 完全进 console(已具备);或更进一步「⏳ 计算中…」完全静默。
- 两条都改已上线功能(提示文案 #fix555 2026-09-07 刚上线),需用户拍板选「去数字轻提示」还是「完全静默」。推荐前者(静默到底=用户无法区分「卡死」与「后台补」,§5.1④ 诚实标注精神)。

## 六、现象④(首页模拟回测弹窗 16 片阻塞)

### 6.1 根因(2026-09-05 #51 引入)
- `_simRenderOnce`(app.js L4153-4163):「#51 净资产曲线全史口径:曲线初始资金=全史峰值×¥10000 恒值,不随窗口切换 → 必须加载全史分片」→ **每次渲染无条件** `await _simEnsureRange("20110101", _simHotMaxDate||endD, …)` 拉全部缺失年片(t2011..t2026 共 16 片),全部到位才渲染表格。
- 全史峰值(peakAllHist)同时用作表格「累积盈亏%」分母(L5027-5029)与净资产曲线初始资金(L5408-5409)。
- recent 热区实测覆盖 20260706~20260903(约 60 天,2.6MB);默认 3 个月窗口(90 天)需 recent + t2026 共覆盖,500 天窗口需 t2025+t2026 两片——与用户「500 天 2 片就够」直觉一致,16 片阻塞全是 #51 全史口径的连带。

### 6.2 方案(「改已上线功能」,核心口径变更需用户 §23.7 确认:窗口期分母/曲线初始资金用哪口径)
目标:sigkelly 同款两阶段——表格先按窗口渲染(recent 热区+窗口内年片),全史分片后台补齐完成再刷新净资产曲线与「全史峰值」相关列。

**最小改动**(app.js 单文件):
1. L4162 `_simEnsureRange("20110101", …)` 改为「窗口范围」: `_simEnsureRange(startD, endD, onStep)`(函数已支持任意范围,只改调用参数)。
2. 新增后台补齐:窗口渲染后 `_simEnsureBackgroundAll()`(复用 _simFetchTrades + _simPartsCache,不重复拉已缓存的 recent/窗口片),完成回调里:合并全史 → 刷新 peakAllHist 相关显示(净资产曲线 + 累积盈亏%分母列)。
3. 渲染函数兼容「全史未就绪」:peakAllHist 未就绪时表格分母先用窗口内峰值并标注「全史校准中」,或分母列暂空待补(两种口径二选一,用户拍板)。
4. 净资产曲线区域补全前显示「⏳ 后台补全全史数据,曲线稍后自动刷新…」。

**影响面**:app.js _simRenderOnce/_simRenderTable/_simRenderNetassetChart;改的是 #51(2026-09-05 用户拍板「全史恒值」)在窗口期的口径呈现,必须用户确认(§23.7)。

## 七、复现

- 实测脚本:`scripts/playwright-accept/timeline_sigkelly_silent_fill.mjs`(本轮新建,untracked)
- 命令:`cd scripts/playwright-accept && node timeline_sigkelly_silent_fill.mjs`(需 playwright-accept/node_modules;真实线上 ss.fx8.store;headless chromium 无痕 context 零 localStorage;for 循环 max 6 分钟)
- 数据版本:线上 signal_kelly_trades_parts t{YYYY}.json(2026-09-07 数据,labsigkelly 分片);lab.min.js = 本地双向 md5 b01f481f86d722a67e8aaed0eedcc8fc(版本串 20260907-a554)
- 关键时间线(offset 校准后):HOST_LOADING_ON=7.81s / Y1_READY=10.82s / ALL_READY=13.52s / HOST_LOADING_OFF=20.41s;遮罩全程 ON 一次
- 另参考既有验收脚本 `scripts/playwright-accept/verify_sigkelly_y1_render.mjs`(y1 先渲染 + 全量逐 cell 对账,8b4e8a239 配套,B1 断言 PASS)

## 八、改动文件清单(实施时)

| 项 | 文件 | 位置 | 分类 |
|---|---|---|---|
| ① 补齐后灰蒙层(静默重算) | static-site/lab.js | L8342 _kellyRunRecompute 加 silent 参;L9346 _kellyOnFilterChange 透传;L8705 _labKellyOnAllReady 传 silent | 纯 bug 修复 |
| ③ 进度提示静默 | static-site/lab.js | L8647-8659 _labKellyProgStr 阶段2 分支 | 改已上线功能(用户拍板)|
| ④ 首页弹窗渐进 | static-site/app.js | L4153-4163 _simRenderOnce;_simRenderTable 分母;_simRenderNetassetChart | 改已上线功能(用户拍板口径)|

## 九、实施记录(2026-09-07 用户拍板后实施,feat/sigkelly-silent-fill)

**commit 链**:`3f35b1ea6`(feat 源码 app.js+lab.js) + `a2221cb98`(build min+bump 版本串 a556,§24② 同 commit) + 本次(报告+验收脚本落档)。

**落地明细**(相对方案的最小差异说明):
| 方案项 | 落地 | 额外说明 |
|---|---|---|
| ① A 静默重算 | `_kellyRunRecompute(host,loadingHtml,onResult,onDone,silent)` 第5参跳过 L8350 加遮罩;`_kellyOnFilterChange(_opts)` 透传 `!!(_opts&&_opts.silent)`;_labKellyOnAllReady 改调 `{keepS06:true, silent:true}` 并加 console.log(补齐进度进 console) | 收尾 remove 保留(防状态残留);其余 4 处 `_kellyRunRecompute` 调用点(L9213/L9250/L11018/L11107)保持带遮罩(用户交互正常反馈) |
| ① 配套微调 | `_pcProgNote`(L10388)条件改 `_labKellyY1Ready && !(_AI_POSCAP_RATING_DYNAMIC_LAB && _AI_POSCAP_RATING_DYNAMIC_LAB.computed)` | ALL_READY 后、动态源未就绪间隙仍显示「⏳ 全量计算中」标注 |
| ③ B 轻提示 | `_labKellyProgStr` 阶段2 分支 → `" · 后台补齐其余周期, 完成后自动展示…"`,去「全量补全 N/16」 | 三处占位元素(L11327/L11449/L12010)拼该函数自动跟随;每片加载 console.log、「补齐完成」console.log |
| ④ C 弹窗渐进 | `_simRenderOnce` L4195 改 `_simEnsureRange(startD, endD, …)`(窗口范围);新增 `_simEnsureBackgroundAll(modal)`(复用 `_simEnsureRange("20110101", hotMax)` + `_simPartsCache`,不重复拉已缓存);`_simAllHistReady/_simAllHistCached()` 标记;表格峰值标注「⛳ 全史校准中(后台补齐, 完成后自动刷新)」;曲线 note「⏳ 后台补全全史数据, 曲线稍后自动刷新…」;补齐完成 `_simRender(modal)` 原地重渲染刷全史口径 | 关键调平:kept 窗口筛选本来滤掉窗口外信号 → 窗口内展示数字与全史路径逐位一致(§23.15 不显残缺数);`_simFullFallback`(全量回退)时 `_simAllHistCached()` 恒 true 不误标 |

**自验(§5.4⑦ 页面实测锚点,全脚本无痕 context 零 localStorage)**:
| 脚本 | 断言 | 结果 |
|---|---|---|
| `scripts/playwright-accept/verify_sigkelly_y1_render.mjs`(既有回归) | y1 先渲染 + 全量逐 cell 对账 B1 | 9 pass / 0 fail |
| `scripts/playwright-accept/accept_sigkelly_silent.mjs`(本轮新增) | A1 补齐完成后不再 HOST_LOADING_ON(静默无遮罩)/ A2 最终解锁 / B1 占位轻提示无 N/16 / A3 主卡有行 / A4 无 pageerror | 6 pass / 0 fail |
| `scripts/playwright-accept/accept_sim_progressive.mjs`(本轮新增) | C1 表格先渲染 / C2 全史未就绪标注「全史校准中」/ C3 曲线补全提示 / C4 标注消失 / C5 提示消失 / C6 无 pageerror | 8 pass / 0 fail |

**§23.2 修 bug 三铁律(方案 A 属纯 bug 修复)+ §23.3 举一反三清单**:
- `_kellyRunRecompute` 5 处调用:仅 `_kellyOnFilterChange` 透传 silent,其余 4 处保持遮罩(用户交互反馈)。
- `_kellyOnFilterChange` 全站调用点(~40 处):仅 `_labKellyOnAllReady` 传 silent,其余不传(默认带遮罩)。
- `_labKellyProgStr` 三处占位自动跟随,无遗漏数字提示点。
- 首页 sim 弹窗与凯利区同链(全史口径 #51):C 改动窗口期标注透明、补齐后回全史,未改任何展示数字。
