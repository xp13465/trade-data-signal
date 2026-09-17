# 信号凯利回测弱网:y1 分片已就绪却不渲染 / 16片全下载完遮罩仍不消失(2026-09-17 调研)

## 现象(用户 2026-09-17 报)
1. 弱网下,信号凯利回测页先下载前 2 片(y2025+y2026,近1年两片)成功后,仍一直显示「⏳ 计算中…」,近1年结果不展示。
2. 后续补充:全部 16 片分片下载完后,「计算中」遮罩仍不消失(等了数分钟)。
3. console 报错:`fetchJSON timeout (120000ms): https://ss.fx8.store/r2/data/accum_nav_map.json`,调用链 renderSigKellyLab → _kellyOnFeeChange → _kellyRunRecompute → _kellyApplyFeeRecompute → _kellyRealNavEnsure → _gihRealNavEnsure(common) → fetchJSON。

## 结论(根因)
**根因一句话:遮罩与 y1 渲染都被同一把锁锁死——重算主链 `_kellyApplyFeeRecompute` 内三处串行 await,其中「GIH 真实净值映射 accum_nav_map」的 fetch 在弱网下每轮最多耗 8 分钟(120s R2 直链超时 + ./data/ 120s + fetchJSON 内部 fallback 重试 2×120s),且失败后无缓存无冷却、下一轮重算立刻再来一遍;y1 先渲染分支(L8365)的触发窗口(「y1 就绪&&全量未就绪」)在这 8 分钟里被后台阶段2(拉 14 片,并行)抢先闭合,分支永远错过 → 只能等第二轮全量重算(又一轮 8 分钟 nav 阻塞 + 全量 7s 重算)收尾时遮罩才收。**

具体为三段:
- **A. y1 分片就绪但结果不渲染**:y1 渲染唯一的提前出口是 `_kellyRunRecompute` do 循环内 L8365 分支(`_labKellyY1Ready && !_labKellyAllReady` 时 onResult 后立即 onDone 就地渲染)。但该检查前,主链要先过完 `await _kellyApplyFeeRecompute` 内的全部阻塞(含 accum_nav_map 480s 级超时)。这段阻塞与后台阶段2 并行,弱网下 nav 阻塞(8min)>> 14 片下载时间 → 检查时刻 `_labKellyAllReady` 已 true → 分支跳过,「y1 先渲染」从未发生(与 L8360 历史注释「从未发生」同病)。
- **B. 16 片全下载完遮罩仍不消失**:遮罩收起只发生在 `_kellyRunRecompute` 收尾(L8378 `host.classList.remove("lab-custom-host--loading")` + L8382 `onDone(host)`),前置条件=当前轮 `await _kellyApplyFeeRecompute` 完整走完(L8350)。阶段2 完成后 `_labKellyOnAllReady` → `_kellyOnFilterChange({silent})` → recompute busy 中只挂 pending(L8343)。第一轮结账后进入第二轮,第二轮开头**再次 await nav ensure**(上次失败已把单例清空,见证据点6)→ 又 8 分钟。所以用户 16 片下载完还要等「第二轮 nav 8 分钟 + 全量重算 ~7s」遮罩才收。等数分钟收不下来=必然。非永久卡死(所有 fetch 均有超时),是 8min/轮 的弱网放大阻塞。
- **C. 触发条件**:GIH 开关默认开(`_kellySharedGih()` L8002-8003 默认 `{on:true}`,注释「默认开 2026-08-30」),因此任何首次访问用户 recompute 每轮必过 nav ensure。

## 证据点(行号=最新工作区 static-site/lab.js 等)
1. 首屏初始重算入口:lab.js L9615 `_kellyOnFeeChange(state.labSigKellyFeePreset);`(renderSigKellyLab 尾部,fire-and-forget)。
2. 遮罩挂上:lab.js L8357 `if (!silent) host.classList.add("lab-custom-host--loading");`;收起:L8378 `host.classList.remove(...)` + L8382 `onDone(host)`(本轮无异常才走到)。
3. 重算主链三串行 await:lab.js L8772-8774 `await window._tdsS06StateEnsure()`(S06 默认基座;common.js L985-1010,fetchJSON 默认 15s、失败吞错返回 null——非卡点);L8778-8782 `await _labKellyTradesEnsure()`(阶段1 两片,分片超时 60s+重试 3 次,lab.js L8493-8508);L8782 `if (state.labSigKellyGihOn) await _kellyRealNavEnsure();`(←核心卡点)。
4. nav ensure 实现:lab.js L8043-8059 `_kellyRealNavEnsure` 优先代理 common 实例 `window._kkellyRealNavEnsure`;common.js L1246-1263:urls[0]=`https://ss.fx8.store/r2/data/accum_nav_map.json` → 失败 catch → urls[1]=`./data/accum_nav_map.json` → 再失败最外层 catch 返回 false,nav 单例保持 null。
5. 120s 超时来源(用户报错出处):app.js L9211 fetchJSON;调用传入 120000(lab.js L8050 / common.js L1249、L1253);超时抛出的 console 文案在 app.js L9369-9371:`console.error("fetchJSON timeout (" + _timeoutMs + "ms): " + url)` 与用户报错文本逐字一致。
6. fetchJSON 内部 fallback 放大约 3 倍耗时:app.js L9288-9327——`./data/` 请求失败后重试循环 2 次(`for (let i=0;i<2;i++)`),每次新 AbortController 且 `_timeoutMs`=120s → 单轮 nav ensure 最坏 = R2 120s + ./data/ 首次 120s + 重试 2×120s = 480s。且主站(非备站)不触发二级 R2 兜底(L9330 起 `_isBackupSite` 条件)。nav 失败后 common L1262 复位 `_kkellyRealNavPromise=null`、`_kkellyRealNav=null` → **下一轮重算重新发起整套 480s**(第二轮必再吃一遍)。
7. y1 先渲染分支与跳过条件:lab.js L8355-8368(#100 修复块),条件 `_labKellyY1Ready && !_labKellyAllReady`。弱网时序:阶段1 两片成功(L8592-8597 置 `_labKellyY1Ready=true`)后立即 L8601 `_labKellyLoadAllBackground()` 后台拉 14 片(与主链并行);主链仍卡在 nav 480s → 期间阶段2 完成 L8695 `_labKellyAllReady=true` → L8700+ `_labKellyOnAllReady()` → L8713 `_kellyOnFilterChange({keepS06:true,silent:true})` → L8343 busy 中 only `_kellyRecomputePending=true`。第一轮 onResult 后 L8365 检查时 allReady=true → 跳过。
8. y1 周期本身的门控是通的(非卡点):L8711-8721 `_labKellyPeriodIsReady`:y1 只需 2 片(`_labKellyPeriodShardNeed` L8404),两片就绪即 true;卡片渲染 gate L12594-12600 仅挡「未就绪周期」,y1 不挡。问题只在前文 A/B 的时序锁。
9. 次要同病点:演进表格操作池 L10441 / L12895 同样 `await _kellyRealNavEnsure()`——弱网开表格弹窗也会被 nav 卡数分钟。
10. 分片链路本身有兜底且可收尾(非本次卡点):L8590-8595 y1Fail 回退全量;阶段2 失败 L8686-8691 兜底全量。

## 已验证链条清单(回答主控三问)
| 问 | 答(证据) |
|---|---|
| accum_nav_map 超时/失败有无兜底 | 有,不中断计算:common L1256-1262 二级 fallback + 最外层 catch 返回 false;lab 的 L8057-8058 同理。失败=「图便利标缺价」语义,不抛异常。**但耗时被放大到 480s/轮,且下一轮重来一遍** |
| 「计算中」遮罩由谁收、前置是什么 | `_kellyRunRecompute` 收尾 L8378-8383;前置=`await _kellyApplyFeeRecompute`(L8350)完整返回;无异常才走到。nav 超时在它之前 → 遮罩被压住 |
| accum_nav_map 是首屏必拉还是 recompute 才拉 | recompute 才拉(且 GIH 默认开使得首屏 recompute 必拉);app 首页只有 sim 弹窗打开时拉(app.js L5772-5774,弹窗内兜底注释 L4452-4454)。不是整站首屏 request |

## 最小修复点(只定位,不改)
按改动从小到大:
1. **给 nav ensure 加「失败冷却+单例保底」**(lab.js L8043-8059 / common.js L1246-1263):失败后记 `{failedAt:Date.now()}` 或保留 `{nav:null}` 的单例标记,冷却期内(如 60s)直接 resolve(false) 不再发网络请求;R2 直链 120s 可降到与 fetchJSON 默认一致的 15s(fetchJSON 内部还有 retry 兜底)。→ 直接消掉「第二轮又 8 分钟」。
2. **摘掉重算主链与 nav ensure 的串行**:(首选方向,稍大)lab.js L8782 `/L10441/L12895` 三处 `await` 改为「发射后台预热 + G/H/I 相关行先按缺价渲染,nav 到达后再单独重算 G/H/I 行(或全量 silent 补一轮)」。这才能保证「y1 两片先渲染」的设计真正兑现,而不是继续赌 nav 先到。
3. **修 L8365 窗口脆弱性**(lab.js L8365):分支条件放宽为「onResult 时若已有可渲染数据即就地 onDone」,不依赖 `_labKellyAllReady` 恰为 false 的窄窗口;若 allReady 已 true,直接走全量 onDone 也不该再等一轮。
简单打法=1(最小);终极正确=1+2+3(符合 §5 一步到位不妥协)。

## 复现段
- 环境:静态读 source(static-site/lab.js@main、common.js、app.js),本调研未做页面实测(结论全部为代码控制流断言,不涉页面数字,不适用同构对账机检)。
- 弱网复现路径:DevTools Network throttling(low connectivity) → 打开信号凯利回测 tab → 观察:① 控制台出现 `fetchJSON timeout (120000ms): https://ss.fx8.store/r2/data/accum_nav_map.json`;② 前 2 片 t2025/t2026 下载完成(进度「近1年数据 2/2」)后卡片仍为「⏳ 计算中… · 后台补齐其余周期…」;③ 16 片全部下载完成后再等数分钟,遮罩才随第二轮全量重算收尾消失。
- 关键对账断言(与代码逐字对应):报错 URL=`_labKellyY1Years` 之外的文件(accum_nav_map,来自 lab L8050 硬编码),报错 120000ms=lab L8050 传入参数,双重确认「卡点是 nav 链不是分片链」。
