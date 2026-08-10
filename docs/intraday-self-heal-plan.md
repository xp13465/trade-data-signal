# 分时图1分钟轮询卡死 + 自愈机制调研

> 调研日期: 2026-08-10 | 只读调研,不改代码 | 关联 CLAUDE.md §14(生产稳定性P0,分时图是盘中实时功能)

## 一、用户现象

用户 9:14 进入首页不刷新,观察到:
1. 全局角标 9:25 正常(10分钟轮询正常),但分时图没曲线数据,分时图角标也 9:25(没跟上)
2. 其他浏览器刷新后分时图 9:34+曲线正常 → API 没全局宕机,是本浏览器侧问题
3. 9:38 不正常浏览器角标更新到 9:35 了,但分时图还是没恢复 → 角标被 overview 轮询更新,分时图独立死了
4. 有的分时图显示"实时拉取失败 显示快照"
5. console 无异常调试报错日志,无法定位

核心需求:看板打开永不刷新,7x24 自愈,哪怕中途卡死也能自己救活,不用手动刷新。

## 二、现有架构(代码层,app.js)

分时图数据链路:`_doIntradayRefresh()`(L7026)→ `await _refreshDynamicAll()`(L7044,批量拉取填缓存)→ `await Promise.all(_renderIntradayChart)`(L7052,逐图渲染)→ 判断成功/失败 → `_scheduleNextRefresh()`(L7004,递归 setTimeout 排下次)。

数据源三源互备(`_fetchDynamicPcts` L6523):同花顺批量(L0)+ 东财单只 + 腾讯 ifzq 单只(L2/L3 兜底)。`renderIntradaySection`(L6879)在 `renderOverview`(L9455)内调用,盘中 `_startIntradayRefresh()`(L6964/L6982)启动递归 setTimeout。

- 1分钟轮询:递归 setTimeout(`_scheduleNextRefresh` L7004),非 setInterval。失败渐进退避 1→2→4→8min。
- 10分钟/3分钟轮询:overview 自适应(`_doOverviewRefresh` L7225),`fetchJSON` 拉 overview.json(有 15s 超时)。两套轮询**独立**,overview 不触碰 intraday。
- 角标:被两套轮询都更新(`refreshCardTimeBadges` 在 `_doOverviewRefresh` L7260 和 `_doIntradayRefresh` L7054 都调)。

## 三、根因(grep 行号确认,非推测)

### RC1〔致命,最可能根因〕分时数据 fetch 无超时
- `fetchTencentMinute`(东财,L6324):L6335 `await fetch(url, { cache: 'no-store' })` **无 AbortController/超时**
- `fetchQQMinute`(腾讯,L6370):L6390 同上无超时
- `fetchTHSBatchMinute`(同花顺,L6437):L6441 同上无超时
- 对比:`fetchJSON`(L3629)有 15s AbortController 超时(L3666-3667)
- 后果:fetch 卡死(网络 stall/DNS/慢响应/TCP 挂起)→ Promise 永不 resolve → `_doIntradayRefresh` 的 `await _refreshDynamicAll`(L7044)/`await Promise.all(promises)`(L7052)永不返回 → `_scheduleNextRefresh()` 永不调用 → **递归 setTimeout 链断裂,1分钟轮询永久死亡**
- 注:`_renderIntradayChart` 的 `.catch`(L6861)只接 reject,不接"永不 resolve",卡死时 catch 也不触发

### RC2〔放大 RC1〕in-flight 去重 Map 卡死后毒化后续请求
- `_inflightMinute`(L6296):`fetchTencentMinute`/`fetchQQMinute` 用 `_inflightMinute.set(cacheKey, p)` + `p.finally(() => delete)`(L6381-6383)。**fetch 卡死时 finally 永不触发,entry 永不删除**,后续同 code 的 fetch 返回同一个卡死 Promise
- `_inflightBatchP`(`_fetchDynamicPcts` L6551):`finally(() => _inflightBatchP = null)`(L6729)同理,卡死时永不清理,后续**所有** `_refreshDynamicAll` 返回同一个卡死 Promise
- 后果:一次卡死 → 该 code(或全批量)后续所有请求被毒化。即使切 tab 回来 `visibilitychange` 触发 `_onIntradayVisChange`(L7072)→`_doIntradayRefresh`,也拿到卡死 Promise,**无法恢复**。这解释了"角标更新了但分时图不恢复"(切 tab 回来角标走 overview 轮询恢复,分时图被毒化的 in-flight 卡死)

### RC3〔fail-fast 场景〕6次失败后永久停止,无自愈
- `_doIntradayRefresh`(L7058-7066):`_intradayFailCount >= INTRADAY_MAX_FAILS(6)` → 显示 notice + `return` **不调 `_scheduleNextRefresh()`** → 定时器永久死亡
- `_intradayActive` 保持 true(不重置),`visibilitychange` 可触发一次 `_doIntradayRefresh` 重试,但若再失败 failCount=7 仍≥6 → return 不重排 → 再次死亡
- 唯一恢复:切 tab 触发 `_onIntradayVisChange` **且**恰逢网络恢复 + fetch 成功(failCount 重置0)。用户不切 tab = 永不恢复
- 对应现象:"实时拉取失败 显示快照"(`_renderIntradayFail` L6766 显示文案)→ 6 次后 notice"已暂停刷新"

### RC4〔用户指出的缺口〕overview 轮询不检查/唤起 intraday 轮询
- `_doOverviewRefresh`(L7225-7275):只刷 overview.json + `fetchIntradaySnapshot` + KPI badge,**不触碰** `_intradayRefreshTimer`/`_intradayActive`/`_intradayFailCount`
- `renderIntradaySection`(含 `_startIntradayRefresh`)只在 `renderOverview`(L9455)调用,而 `renderOverview` 只在切 tab(L5126 `renderTab`)时调用,**不被 overview 轮询周期调用**
- 后果:intraday 死了,overview 3min 轮询照常更新 badge(角标 9:35 正常),但从不检查 intraday 是否活着 → 分时图卡在旧时间(9:25)无救。**这正是用户看到的"角标更新但分时图不恢复"**

### RC5〔用户指出〕无日志机制,无法定位
- 整个 intraday 区段(L6239-7080)**零 console.* 调用**
- fetch 失败:`catch (e) { continue; }` 静默吞掉(L6380 东财 / L6425 腾讯 / L6485 同花顺)
- `_renderIntradayFail`(L6766)只改 DOM 文案,无 console
- 后果:卡死/失败时 console 无任何输出,无法定位为何没渲染

### RC6 无 online/offline 事件 + 无看门狗
- `grep addEventListener.*online|offline` = 空;`grep self_heal|watchdog|自愈|重连` = 空
- 无独立心跳检测 intraday 轮询是否存活

### 排除项(非根因)
- **午休机制正常**:`_isLunchPause`(L5884)+ `_scheduleNextRefresh`(L7015)/`_doIntradayRefresh`(L7024)午休(11:35-12:55)跳过请求但 `_scheduleNextRefresh()` 重新调度 → 13:00 自动恢复。非根因
- **SW 非致因**:sw.js L80 跨域请求不拦截(`if (url.origin !== self.location.origin) return`),分时 API(eastmoney/ths/qq)走裸 fetch 无 SW 层介入。排除 SW 缓存致卡死
- **overview 轮询本身健康**:`fetchJSON` 有 15s 超时 + networkOnly/networkFirst + 静默重试,3min 兜底铁律。角标正常即证 overview 轮询未死

## 四、自愈方案(按优先级)

### P0-根治卡死(必做,治本)

#### S1. 分时 fetch 加 AbortController 超时〔对应 RC1〕
- `fetchTencentMinute`(L6335)/`fetchQQMinute`(L6390)/`fetchTHSBatchMinute`(L6441)的每个 `fetch(url, {cache:'no-store'})` 加 `signal` + 8-10s 超时
- 模式同 `fetchJSON`(L3666-3667):`const c = new AbortController(); const t = setTimeout(() => c.abort(), 8000); try { const r = await fetch(url, {cache:'no-store', signal: c.signal}); ... } finally { clearTimeout(t); }`
- 超时触发 abort → fetch reject → 进现有 `catch (e) { continue; }` 换 host 重试(L6380 等)→ 全 host 失败返回 null → 走 RC3 fail 计数(但配合 S3 不再永久死)
- 效果:卡死 8s 后强制失败,不再永久挂起;`_doIntradayRefresh` 的 await 必然返回

#### S2. in-flight Map 加超时清理兜底〔对应 RC2〕
- `_inflightMinute`(L6296):entry 加 `setTimeout(() => _inflightMinute.delete(cacheKey), 15000)` 兜底(不依赖 finally,15s 强制清理)。或改用"超时即删"而非"resolve 才删"
- `_inflightBatchP`(L6551):同理 `setTimeout(() => { _inflightBatchP = null; }, 15000)` 兜底
- 效果:即使 S1 的 abort 因某种原因未触发(浏览器 bug),Map entry 15s 后也被清理,后续请求发新 fetch 不被毒化。双保险

### P1-自愈机制(必做,治标+治本)

#### S3. 6次失败不永久停,改长间隔兜底重试〔对应 RC3〕
- `_doIntradayRefresh`(L7061-7066):`_intradayFailCount >= 6` 时**不 return**,改为降频到 5min 兜底重试(`_scheduleNextRefresh` 用 `Math.max(delay, 5*60*1000)`),成功后 failCount 重置 0 恢复 1min
- notice 文案改"实时拉取异常,已降频重试中..."(非"已暂停")
- 效果:网络恢复后自动恢复,不需用户切 tab。符合"7x24 自愈"需求

#### S4. overview 轮询加 intraday 心跳检查唤起〔对应 RC4,用户建议〕
- `_doOverviewRefresh`(L7225)末尾加:盘中(`snap.is_closed===false`)时检查 intraday 是否健康,不健康则重启
- 健康判定:`_intradayActive === false`(被停了) OR `_intradayLastFetch` 距今 > 5min(卡死/超时,正常 1min 一次) OR `_intradayRefreshTimer === null && _intradayActive`(定时器丢了)
- 重启动作:调 `renderIntradaySection` 的轻量重启版,或直接 `_stopIntradayRefresh()` + `_startIntradayRefresh()` + 重设 `_intradayRenderCtx` + 立即 `_doIntradayRefresh()`。注意 `clearCharts`(L134)切 tab 时会 `_stopIntradayRefresh`,需 `_intradayRenderCtx` 重新绑定 DOM
- 注意幂等:overview 3min 一次,不会频繁重启;只在真异常时重启
- 效果:overview 轮询作为"看门狗"救 intraday,用户不切 tab 也能自愈。这是用户明确建议的方案

#### S5. visibilitychange 切回前台强清 in-flight 重连〔配合 S2/RC2〕
- `_onIntradayVisChange`(L7072):切回前台时先清 `_inflightMinute.clear()` + `_inflightBatchP = null`(丢弃可能卡死的 in-flight),再 `_doIntradayRefresh()`
- 效果:切 tab 回来必发新 fetch,不被毒化 Promise 卡死(当前 vis-change 拿毒化 Promise 无效)

### P2-兜底加固(建议)

#### S6. online 事件重连〔对应 RC6〕
- `window.addEventListener('online', ...)`:网络恢复时清 in-flight + 重启 intraday 轮询(同 S5 逻辑)
- 场景:笔记本休眠唤醒/切换 WiFi 后网络恢复,intraday 卡死需救活

#### S7. 独立看门狗 setInterval〔对应 RC6,终极兜底〕
- 独立 `setInterval`(如 2min,不受 document.hidden 影响)检查 `_intradayLastFetch` 距今 > 3min(盘中)→ 强制 `_stopIntradayRefresh` + `_startIntradayRefresh` + `_doIntradayRefresh`
- 和 S4 互补:S4 靠 overview 轮询(3min,后台可能被 throttle),S7 独立定时器更可靠但需注意后台 throttle(setInterval 后台也被 throttle,但 visibilitychange 配合)
- 效果:最后一道防线,任何原因 intraday 卡死都能救活

#### S8. 定期全量重载分时(可选)
- 每 30min 强制重跑 `_renderIntradayInSparkCells`(L6865)全量重渲染,清 echarts 实例避免内存泄漏累积
- 兜底:即使计数/状态机都乱,30min 一次硬刷新恢复正常

### P3-日志机制(必做,便于定位)

#### S9. console 调试日志〔对应 RC5〕
- fetch 失败/超时:`catch (e) { console.warn('[intraday] fetch fail', code, host, e.message); continue; }`(L6380/6425/6485)
- 6次降频:`console.warn('[intraday] 连续失败降频重试', failCount)`
- 心跳重启:`console.info('[intraday] watchdog 重启轮询', reason)`
- 卡死检测:`console.warn('[intraday] lastFetch 超时,疑似卡死,重启')`
- 可加 `localStorage.debug_intraday` 开关控制详略,默认 warn 级(不刷屏)
- 效果:下次卡死 console 有迹可循,不用盲猜

## 五、实施优先级与建议

| 优先级 | 方案 | 治 | 工作量 | 说明 |
|--------|------|----|--------|------|
| P0 | S1 fetch超时 | RC1 | 小 | 治本,8s 超时让 await 必返回 |
| P0 | S2 in-flight清理 | RC2 | 小 | 双保险,防毒化 |
| P1 | S3 降频不死 | RC3 | 小 | 改 return 为降频重排 |
| P1 | S4 overview心跳 | RC4 | 中 | 用户建议,overview 救 intraday |
| P1 | S5 vis-change清in-flight | RC2 | 小 | 配合 S2 |
| P2 | S6 online重连 | RC6 | 小 | 网络恢复自愈 |
| P2 | S7 看门狗 | RC6 | 中 | 终极兜底 |
| P2 | S8 定期重载 | - | 小 | 可选 |
| P3 | S9 日志 | RC5 | 小 | 便于定位 |

**最小有效集**:S1+S2+S3+S4+S9(P0+P1+P3)即可满足"7x24 自愈"核心需求。S1+S2 根治卡死,S3 防永久死,S4 让 overview 救 intraday(用户建议),S9 可定位。S5/S6/S7 是额外兜底加固。

## 六、验收口径(实施时用)

1. 模拟卡死:DevTools Network 对 eastmoney 请求设 Block,确认 8s 后 console.warn + 降频重试(非永久停) + notice 显示"降频重试中"
2. 解除 Block:确认 5min 内(或下轮)自动恢复 1min 正常刷新,failCount 归零
3. 模拟 in-flight 毒化:Block 后等 >15s 解除,确认 in-flight 已清理,新 fetch 正常(S2 生效)
4. overview 救 intraday:Block eastmoney 致 intraday 死,确认 overview 3min 轮询触发心跳重启(S4 生效,console.info 可见)
5. 切 tab 回来:确认 vis-change 清 in-flight + 新 fetch 正常(S5 生效)
6. console 有日志:全程 console.warn/info 可追溯(S9 生效)
7. 正常场景不误杀:网络正常时 S4 心跳不频繁重启(只真异常才重启),不影响正常 1min 刷新

## 七、相关代码位置速查(app.js)

| 功能 | 函数 | 行号 |
|------|------|------|
| 1min轮询启动 | `_startIntradayRefresh` | L6982 |
| 1min轮询停止 | `_stopIntradayRefresh` | L6995 |
| 调度下次(递归核心) | `_scheduleNextRefresh` | L7004 |
| 执行一轮刷新 | `_doIntradayRefresh` | L7026 |
| 6次失败永久停 | `_doIntradayRefresh` fail 分支 | L7058-7066 |
| 东财fetch(无超时) | `fetchTencentMinute` | L6324, fetch L6335 |
| 腾讯fetch(无超时) | `fetchQQMinute` | L6370, fetch L6390 |
| 同花顺批量fetch(无超时) | `fetchTHSBatchMinute` | L6437, fetch L6441 |
| 批量拉取调度 | `_fetchDynamicPcts` | L6523, in-flight L6551 |
| 动态值刷新 | `_refreshDynamicAll` | L6731 |
| 单图渲染(含fail) | `_renderIntradayChart` | L6776, catch L6861 |
| 失败文案 | `_renderIntradayFail` | L6766 |
| 分时主入口 | `renderIntradaySection` | L6879, 启动 L6964 |
| in-flight Map(毒化点) | `_inflightMinute` | L6296, set/finally L6381-6383 |
| vis-change(切tab) | `_onIntradayVisChange` | L7072 |
| 午休判断 | `_isLunchPause` | L5884 |
| overview轮询(不救intraday) | `_doOverviewRefresh` | L7225 |
| overview vis-change | `_onOverviewVisChange` | L7286 |
| 带超时的fetch(对比) | `fetchJSON` | L3629, 超时 L3666 |
| 切tab清intraday | `clearCharts` | L134 |
