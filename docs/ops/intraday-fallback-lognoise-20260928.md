# 前端分时图:渲染 fallback 补腾讯源 + P0 日志降噪(2026-09-28)

## 一、背景与结论(诊断来源 /tmp/intraday-alert-diag.md,本改动自复核)

- **东财 push2 对高频连发做断连风控**(连发 → 000 空响应,冷却 5-10s 恢复;连沪深300 同样,非 bj50 特有)。腾讯源 `fetchQQMinute` 实测连发 6 次全 200 稳定。
- **现状缺口**:批量路径(`_fetchDynamicPcts` L2/L3)已是「东财+腾讯」双腿;但**渲染 fallback 只有东财单腿**(`_renderIntradayChart` 缓存 miss → 只调 `fetchTencentMinute`),东财一抽风用户点开分时图就掉快照,明明腾讯能通。
- 本次改动:**①渲染链补腾讯兜底(双腿)②三个 intraday warn 点日志降噪(单标的单轮 5~10 条 → 1 条)**。

## 二、改动明细

### 改动 A:P0 日志降噪(static-site/app.js)
| 位置 | 改动 | 理由 |
|---|---|---|
| `fetchTencentMinute`(约 L12575,EM 5 host 循环) | catch/HTTP 非 ok/rc!=0/空点 收集到 `emFails[]`(host+原因),循环结束全失败时**统一打一条**「[intraday] 东财分时失败 code N/M 个host均失败: host1:原因 \| host2:原因…」 | 逐 host warn → 单标的单轮 5 条 → 1 条;失败 host 列表+原因全保留,定位能力不丢 |
| `fetchQQMinute`(约 L12644,QQ 3 host 循环) | 同上收集 `qqFails[]` 统一打一条「[intraday] 腾讯分时失败…」 | 与 EM 同款聚合 |
| `fetchTHSBatchMinute`(约 L12779) | **不改逻辑**,仅加注释说明判断理由 | 该函数单请求单 catch(无逐 host 循环),每批尝试本就 1 条(含全部 codes+原因),无刷屏问题,不适用聚合 |

> 三处 warn 点统一处理结论:EM/QQ 两处为逐 host 循环需聚合(已改);THS 一处为单请求单条(保持原样,加注释记录判断)。降频提示 `_doIntradayRefresh` 的「连续失败N次降频」为状态提示(仅 3 次失败后 1 条/降频周期,约 5min 1 条),不属刷屏,保持。

### 改动 B:P1 渲染 fallback 补腾讯源(static-site/app.js)
- **新增 helper** `_fetchIntradayRenderSource(code)`(约 L13289):东财优先 → 失败/无数据补试腾讯 → 双源都失败返回 null。与批量 `_fetchDynamicPcts` L2/L3 双腿同构。
- **`_renderIntradayChart`**(约 L13305):缓存 miss 路径 `fetchTencentMinute(code)` → `_fetchIntradayRenderSource(code)`。
- **结构兼容核对(动手前必核对项)**:`fetchQQMinute` 返回 `{name, price, preClose:null, pct:null, date, points}`,`fetchTencentMinute` 返回 `{name, price, preClose, pct, date, points}` —— **points 子结构逐字段一致**;差异仅在腾讯 preClose/pct 为 null。而 `_renderIntradayChart` 的 preClose 由**调用方从 snap 传入**(`_snapPreClose(snap, code)`,三个调用点 L13417/L13489/L13614 均如此),渲染内 `const pc = preClose || result.preClose`(L13313)天然兼容 QQ 的 null;`result.pct != null` 守卫(L13306)让动态缓存填充对 QQ 自动跳过。**与批量路径 `applyResult`「从 snap 补 preClose」同思路,无需适配,可直接走同一套渲染逻辑**。
- **§23.3 举一反三全量清单**(全文件 `fetchTencentMinute`/`fetchQQMinute` 调用点逐项判断):

| 调用点 | 位置 | 判定 | 改动 |
|---|---|---|---|
| 批量 L2 toEm / toQq | L12931/L12932 | 双腿(同轮并行) | 不改 |
| 批量 L3 l3ToEm / l3ToQq | L12961/L12962 | 双腿 | 不改 |
| **渲染 miss 路径** | L13305 | **单腿无兜底** | **已改**(helper) |
| **新闻弹窗上证迷你图** | L28993 | **单腿**(有静态降级兜底) | **已改**(复用同一 helper) |
| `_refreshDynamicAll` | L13128 | 走 `_fetchDynamicPcts` 批量双腿 | 不改 |
| 其余(注释) | L28633/28663/13547 | 注释,非调用 | 不改 |

### §21 算法公示判断
本次是**取数链路**改动(数据源选择/失败兜底),**不是评分/权重/分段/匹配规则等算法口径**。已 grep purpose-notes.js + lab.js + app.js 公示文案,无「分时数据来源单一」类用户可见公示需同步。**结论:不需要改公示**(说明理由,非默认跳过)。

### 改动 C:P2-2 新闻弹窗迷你图缓存时效判定(static-site/app.js,2026-09-28 追加派单)

**现象**:`_newsModalSparkCached` 只在 null 时填充、永不失效,同一会话内迷你图永远停在首拉时刻——「挂一上午还是上午那条」。

**根因**:缓存无任何时效判断(§23.2 同类错误面:只在 null/undefined 时填充、无失效判定)。

**修法** `_ensureNewsModalSpark()`(约 L29003,打开弹窗与 5min 轮询共用):
- **①换日锚**:缓存以 `news_digest.date` 为锚(`_newsModalSparkForDate`),锚变必重拉(每 digest 日至多一次)。
- **锚为何用 digest 日而非 `_bjTodayStr()`(任务点名坑)**:非交易日 digest=周六、曲线=上一交易日(周五),锚匹配=不重拉;若写「必须等于今天」会在周末/盘前/盘初把上一交易日曲线误判过期,每开必重拉。锚 digest 日 = 「当前应显示日」跟随弹窗自身日期,周末/节假日/盘前一次锚定后不再拉。
- **②盘中追新**:北京工作日 + 交易时段(9:30~11:30 / 13:00~15:05) + 曲线末点早于当前时刻 → 重拉追曲线(午休 11:30~13:00 不探,曲线定格探了空转)。
- **③节假日/极早盘防护**:探活发现「曲线日仍 < digest 日」(无当日行情)→ 冷却 30min 再探,防每 5min 空转;交易日开盘瞬间(9:30 前后 EM 切新日)最迟 30min 内探到,曲线日追上后转末点判定正常追新。
- **④失败保留旧缓存不闪空**,下一轮/下次打开再试(与 `_loadNewsDigest` 保留旧内容同精神)。
- **配套**:静态降级 `_newsModalSparkStatic` 同加 digest 日锚(`_newsModalSparkStaticForDate`),换日重拉,不再跨日沿用昨日快照;弹窗 5min 轮询在列表渲染后补跑 spark 时效刷新,仅缓存对象实际更新才重渲染并恢复滚动位置(不闪回顶部)。
- 新增 `_dbNewsYMD()` 统一日期归一化(支持 2026-08-16 / 20260816)做字典序比较。

**§23.2 同类错误面清单**(grep 全文件「fill-once 无失效」缓存变量逐项判定):

| 缓存变量 | 位置 | 判定 |
|---|---|---|
| `_newsModalSparkCached` | L28633 | **已修**(本任务,digest 日锚+盘中追新) |
| `_newsModalSparkStatic` | L28634 | **已修**(同加 digest 日锚) |
| `_newsDigestModalElCached` | L28960 | 不需要时效——DOM 节点缓存,非数据,无「新鲜度」语义 |
| `_resultCache` | L9298 | 已有 `_CACHE_TTL` 时效,非同类 |
| `_newsDigestCache`+`_NEWS_DIGEST_TTL` | L28390 | 已有 5min TTL,非同类 |
| `_inflightFetch`/`_inflightMinute`/`_inflightBatchP` | L9297/12547/12843 | in-flight 去重,15s 强制清理,非同类 |
| `_batchMinuteCache` | L12710 | 每轮 `_fetchDynamicPcts` `clear()`(L12851),自清理 |
| `_dailyBriefState.cache` | L28298 | 每次打开弹窗重置 null(L29127),非同类 |
| `_simPoolCache` | L4552 | 按 `_simKellyData` 引用键整体 clear + LRU 上限 |
| `_emotionIndexCurveCache` | L1471 | **同类但判定不改**:历史日线静态序列(每日新增一根 K 线),仅「跨日不关页」才可见轻微滞后,且属另一展示位(情绪分走势);若要改走 TTL 即可,本次不动 |
| `_sigEtfCache` | L2582 | **同类但判定不改**:index→ETF 静态映射(配置型非盘中数据),按 index\|date 内容键控,裸 index 兜底键仅信号无日期时用,低频变化,影响轻微 |

**§21 公示判断(P2-2 同款结论)**:缓存时效是取数链路/加载策略,非评分/权重/匹配规则算法口径;公示文案无「迷你图数据实时性」承诺需同步。**不需要改公示**。

### §23.1 README 判断
非引用外部开源项目、非站点重大功能发布(仅可靠性修复),无需补 README。

## 三、复现段 / 验证

1. **语法**:`node --check static-site/app.js` → PASS。
2. **降噪验证**(浏览器控制台观察):盘中打开首页,东财抽风时每次轮询每标的只应出现 **1 条**「[intraday] 东财分时失败」/「[intraday] 腾讯分时失败」(内含全部失败 host+原因),不再逐 host 刷 5~10 条。
3. **渲染 fallback 验证**:清除分时缓存后点开某指数分时图,若东财失败应能看到腾讯实时曲线(不再直接掉快照/文字降级);双源全失败才降级快照(行为不变)。可用 DevTools Network 把 push2*.eastmoney.com 请求 block 后点开分时图复现。
4. **构建/版本(机制 C)**:源码改动已同分支重建 `app.min.js`(本地 build_min 从 git HEAD 读源);**版本串 bump 由主控 merge 走 `scripts/main-merge.sh` 统一执行**(worktree agent 不自行 bump,机制 C)。改动前版本串 `v6-20260926-a620`;merge 后由 main-merge.sh 统一 bump 新串并重建 min,部署后 deploy 链自动校验「min 内容哈希 == index 引用版本串」。
5. **P2-2 时效判定验证(逻辑推演四场景)**:
   - **正常交易日盘中**:打开弹窗首拉当日曲线;5min 轮询期间若末点早于当前时刻 → 重拉追新(曲线不再冻结)。
   - **周末**:digest=周六、曲线=周五,`forDate==digest` → 不重拉(不会每开必拉);dow 周末 → 轮询也不探。
   - **跨日**:digest 锚变 → 重拉;盘前 9:10 首拉得上一交易日曲线,9:30 后探活最迟 30min 内追到当日曲线。
   - **节假日工作日盘中**:探活一次发现曲线日仍<digest 日 → 冷却 30min,不再每 5min 空转。
   - 语法:`node --check static-site/app.js` / `app.min.js` → PASS;min 含 `_ensureNewsModalSpark`/`_newsModalSparkForDate`/`_newsModalSparkCooldown` 符号(grep 验证)。

## 四、配套 commit
- 本报告 + `static-site/app.js` + `static-site/app.min.js`(重建)→ feat 分支 `fix/intraday-fallback-log-noise`(push 完成见 git log)。
  - `9c8ac963d` 改动 A 日志降噪(EM/QQ 聚合)+ THS 判断注释
  - `e84fd540d` 重建 app.min.js(改动 A)
  - `dff2d1bed` 改动 B 渲染双腿 helper + 改动 C(P2-2)迷你图缓存时效判定
  - `e6f378833` 重建 app.min.js(改动 B/C)
- merge + push main 由主控 `scripts/main-merge.sh fix/intraday-fallback-log-noise` 执行(禁 agent push main,机制 D)。
- ⚠️ **盘中禁 deploy/push main**:本改动在交易时段内完成,merge/上线由主控按 §14 安全窗口调度。
