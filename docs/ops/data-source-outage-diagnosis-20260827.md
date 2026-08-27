# 数据源三线故障全链路诊断 + zb/seal_rate 慢性病根因 + 兜底韧性盘点

> 调研日期:2026-08-27 晚(只读调研,未改任何代码)
> 触发:8-27 17:56「baostock 封禁熔断(10001011)」严重告警 + `a_width_zb_count`/`a_width_seal_rate` 停更 37 天 + mootdx/东财同日多源恶化

## TL;DR(四句话)

1. **今晚是多源联合故障**:mootdx 通达信协议停服(实测 bars EMPTY,7/12 起持续)+ baostock 账号/IP 级封禁 10001011(8/25 起,18:49 实测仍封,连续 3 天未自解)+ 东财封 IP(行业换手率三连败提前结束)。三条互不兜底的链同时塌,5200 只增量采集仅 1082 成功(79% 失败)。
2. **zb/seal_rate 停更 37 天 = 已弃指标的慢性死亡,非活性故障**:KPI 前端实际消费的炸板率/封板率是 `a_width_zhaban_rate`(intraday,东财炸板池)/`a_width_fengban_rate`(derived),两者 8/27 仍有值;旧 `a_width_zb_count`/`a_width_seal_rate` 在 queries.py L48-49 注释明标「已弃」。但**上游 mootdx_daily_raw 全 A 日线表 8/25 起真断供**(mootdx_progress.json 宇宙缩水至 85 只的隐性 bug),行业宽度表 8/24 起停更。
3. **真实损失面**:mootdx_daily_raw 缺 8/25-8/27 全 A 日线;industry_width_daily 停 8/24;a_turnover_* 5 项(KPI 直展)停 8/24;bump:今晚 O1 统一 deploy 被 fund_nav 校验 FAIL 拦截终止,17:50 轮新产物未走完整 §22 上线三步。
4. **E28 韧性盘点**:multisource.py(2026-08-15)只覆盖指数级指标(us10y/cn10y/qvix 等),**个股日线/换手率分布/全市场宽度三条链无异源兜底或兜底空置**(akshare stock_daily 备源从未 backfill)。

---

## ① 错误码语义与熔断机制解剖

### 错误码
| 码 | 含义 | 证据 |
|---|---|---|
| **10001011** | baostock 服务端「黑名单用户」= 账号/IP 级封禁,relogin 无法解封 | 18:49 实测 `bs.login()` 返 `10001011 黑名单用户，请与管理员联系`(本机直测);baostock_worker.py L56-64 注释 8-14 事故复盘同结论 |
| **10002007** | baostock「网络接收错误」= 登录/查询阶段网络层失败(与黑名单不同,可重试) | 今晚日志 L128:`baostock login failed: 10002007 网络接收错误`,出自 baostock_daily.py L117 `_ensure_login` raise |

注:10002007 在封禁背景下出现,是服务端对被封 IP 的连接请求另一种表现(连接被掐),两者同根:本机 IP/账号已被 baostock 风控标记。

### 熔断机制(ab-#37,2026-08-14 落地)
- **实现位置**:`app/collector/baostock_worker.py` L28-39(本地 circuit_open + 共享 flag)+ `app/collector/baostock_parallel.py` L22-28(并行层)
- **共享短路 state**:`data/baostock_blacklist.flag` 文件(写时间戳);任一 worker 撞 10001011 写 flag,其余 worker 下一个 code 读到即短路(baostock_worker.py L126-131);本地 `circuit_open` 布尔短路后续所有 code(L119-125)
- **退出码**:熔断 worker exit 3(`[CIRCUIT-BREAK]` L226-230);parallel 层 `returncode==3 or flag 存在` 判定本轮封禁(baostock_parallel.py L228)
- **冷却/解禁**:**无冷却期机制**——flag 在每轮 run_update_parallel 启动/结束时清理(baostock_parallel.py L56/77/121/139),即每轮重新盲试。因为封禁是服务端账号/IP 级,重试无意义,熔断只是止损(避免 8-14 那种 825 code×2 次 relogin 盲试 70-80min)
- **自愈性**:否。实测 18:49 login 仍 10001011;8/25/26/27 连续三天告警。错误文案「请与管理员联系」→ 需人工干预(换 IP/联系官方/换源)
- **告警 relay**:runner.py L406-415(日线)/L579-588(turnover)→ notify.py,dedup_key=`baostock_blacklist`,window 86400s(一天一封防轰炸);今晚 17:56 告警邮件即此链发出

## ② mootdx「疑似全停」诊断:慢性病,已坏 45+ 天

**不是今晚偶发抖动,也不是版本问题:**
- 本机 mootdx **0.11.7 = PyPI latest(0.11.7),无新版可升**;pytdx 同协议层
- 18:48 实测:`Quotes.factory(bestip=True)` 选优后 `bars('000001')` 返回 **EMPTY**,耗时 63s ——「TCP 可达但行情返回空」(协议升级/停服),与 mootdx_daily.py L107-108 注释「2026-07-12 回归:_TDX_SERVERS 全部 TCP 可达但 bars() 空」完全一致
- 历史日志时间轴(每日 update_all_*.log grep「疑似全停服」):8/3、8/4、8/5、8/6、8/7、8/10~8/14、8/17~8/21、8/25~8/27 **每个交易日都触发** fallback(周末自然无);runner.py L434 注释「mootdx 7/17 起 bestip 全空」
- **mootdx_daily_raw 表按 turnover 是否 NULL 区分写入者**(mootdx 恒 NULL,baostock fallback 带 turn):主源最后一次成功写入 = 20260824(84 只,恰为 progress 全部);fallback 最后一次成功 = 20260821

**结论:mootdx 主源自 7/12 起实质性停服(45+ 天),8 月全靠 baostock fallback 扛,今晚 fallback 也被封 → 三天全线断粮。**

## ③ zb/seal_rate 停更 37 天合并诊断(重要修正)

### 与今晚故障的关系:同一病灶(mootdx 断供)的两种表现,但严重性分级不同

**上游供给链**(width 指标真源头):
```
mootdx TCP7709(主) ─┐
                     ├→ mootdx_daily_raw 表 → width_history.run_recent(days=30) → a_width_zt/dt/zb/seal_rate
baostock fallback ──┘                       └→ industry_width.run_recent(F3) → industry_width_daily
```
(width_history.py L1-66 头注释;industry_width.py L1-6)

**慢性病精确时间轴**:
| 日期 | 事件 | 证据 |
|---|---|---|
| 2026-07-12 | mootdx 协议回归:_TDX_SERVERS bars 全空 | mootdx_daily.py L107-108 注释 |
| 07-10~07-17 | mootdx_daily_raw 每日仅 84-85 只 | SQL: `SELECT date,COUNT(DISTINCT code) FROM mootdx_daily_raw GROUP BY date` |
| 07-20~07-21 | baostock fallback 大批量成功,表内两日各 5199 只 | 同上 SQL;a_width_zb_count 最后值 20260721(source=mootdx) |
| 07-21 18:03 | fallback 串行 5527 只阻塞 width pipeline,SIGTERM 杀,fallback 只打到 50/5527(`[fallback 50/5527] 000089`) | runner.py L434-437 注释 + update_all_20260721_1750.log L33 |
| 07-22 起 | **mootdx_progress.json 宇宙缩水至 85 只**(code 000001~000428 连续段),每日增量只处理这 85 只,mootdx_daily_raw 每日只 +84~85 行 < width_history 的 MIN_CODES_PER_DAY=1000 保护线 → 近 30 天写入窗口内所有日期被过滤 → `width_history skip (no data in write window)` | progress 文件实测 85 codes;SQL 每日计数;今晚日志 L~128 width_history skip;width_history.py L96-98(L202 过滤) |
| 08-25 起 | baostock 封禁开始,连 fallback 的 84 只也断 → mootdx_daily_raw MAX 停在 0824 | baostock_daily_raw 0824=5199 只/0825=1489/0826=1489/0827=1082;10001011 首现 8/25 日志 |

**zb/seal_rate 停在 20260721 的直接机制**:7/22 起表内每日 <1000 只被 MIN_CODES_PER_DAY 拦截,写入窗口全空。

### 关键定性修正(防误判,§22/§23.13 三源核对)
- 前端 KPI 卡消费清单 queries.py L36-61:**不含** `a_width_zb_count`/`a_width_seal_rate`;消费的是 `a_width_zhaban_rate`(炸板率,新源,intraday_snapshot.py L1611 从东财炸板池 stock_zt_pool_zbgc_em 算)+ `a_width_fengban_rate`(封板率,compute/derived.py = 1-炸板率)
- SQL 实测:`a_width_zhaban_rate` 8/27 有值(source=intraday)、`a_width_fengban_rate` 8/27 有值(source=derived)→ **UI 主展示位没断粮**
- queries.py L48-49 原注释:「旧 a_width_zb_count 数/旧源东财 stock_zt_pool_em 停7-16 **已弃**」「旧 a_width_seal_rate func=TODO 停7-16」→ 旧指标 37 天前就计划性下线,data-gap 告警把它们列为 gap 属于**告警清单未跟上指标下线状态**(噪音),但也歪打正着暴露了 mootdx_daily_raw 断供这个真问题

**结论:zb/seal_rate 停更 ≠ 活性数据事故,但它和今晚故障共享同一上游病灶 mootdx_daily_raw 断供——该表的真下游损失见④。**

## ④ 今晚实际损失面量化

### 库表层(20260827 bar 缺失)
| 库表 | 缺口 | 前端/下游可见性 |
|---|---|---|
| stock_daily.db `mootdx_daily_raw` | 8/25-8/27 全 A 日线(MAX=0824) | 行业宽度/全市场宽度的计算源 |
| sentiment.db `industry_width_daily` | 停 8/24(MAX 实测) | 31 行业内宽度展示 |
| sentiment.db `daily_metric` a_turnover_mean/median/p90/p10/gt5_pct | 停 8/24 | **KPI 换手率分布卡片明早起显异常/缺今日** |
| sentiment.db `daily_metric` a_width_zt/dt/up/down、a_amount | 无缺(8/27 齐) | intraday/akshare/东财替代源顶住 ✓ |

### 下游产物层
- tonight D2 WARN:「跳过 53 个采集不全日期(code数<1000)」+ width_history `skip (no data in write window)`;F3-recent 仅 300 rows(25 ind × 12 dates, since 20260807)
- turnover 链防护正确:当日覆盖率 20.8%<95% → cleanup_d3d2 拦截不写脏数据 + skipped_partial 告警(待回补)
- **O1 统一 deploy 失败(连带损失)**:校验 35 ok / 1 fail——`fund_nav: DB↔产物不一致`(022402/004107/010522 三只,DB 尾 20260819 vs 产物尾 20260818)→ `✗ 数据产物校验失败(退出码 1)，终止部署`(日志 L898-921)。17:50 轮所有 export 产物未走完整上线;static-site/data/overview.json 停在 8/27 05:01(晨盘版)。fund_nav 不一致是公募基金链独立 bug,但门禁一票否决殃及全部产物——需单独修

### 为何核心指数/行业/概念校验仍「齐全」
- `[校验] 10 核心指数/31 申万行业/27 概念指数今日齐全 ✓`——这些走 index_backfill/腾讯等行业指数专用链(非 mootdx/baostock 个股链),资金流 31/31 走同花顺(ths 源)——**个股级链死了,指数级链活着**,恰好证明单点依赖的上游差异

## ⑤ 韧性盘点(E28 对照:任一源必须有异源兜底,fallback 不走同源)

| 链 | 源顺序(现状) | 今晚表现 | E28 判定 |
|---|---|---|---|
| **个股日线 stock_daily** | mootdx TCP7709(主,停服中)→ baostock HTTP(fallback)→ akshare 东财 stock_daily.py(第三源) | mootdx EMPTY;fallback 被封 0 成功;akshare 源 `skip (no progress yet, run stock_daily full manually)` **从未初始化** | **不合格**:仅两活源且今晚双亡;第三源空置(伪兜底:代码在位无数据,紧急切不过去);mootdx 与 fallback 挂同一 update_all 同一 step,无错峰 |
| **全市场宽度 width_history / 行业宽度 industry_width** | 单点依赖 mootdx_daily_raw | 无数据可算,skip | **不合格**:单源零兜底;唯一缓冲是 zt/dt/up/down 有 intraday/akshare 平行指标,但 zb/seal/行业宽度无替代 |
| **换手率分布 turnover** | baostock(唯一源)→ cleanup_d3d2 | 封禁,3 天覆盖率 28%/28.6%/20.8% | **不合格**:单源零兜底;东财 index_turnover f168 兜底是指数级换手率(multisource.fetch_em_index_turnover),**非个股分布口径,不能替代** a_turnover_* |
| 行业换手率 industry_extras | 东财 push2his | 封 IP,连续 3 败提前结束 28 个 | 无异源兜底 |
| 对照组(合格) | 指数级:us10y/cn10y/qvix/南向/全球指数 | 正常 | multisource.py 异源兜底 ✓(但覆盖面只有指数级指标) |

**单源点清单**:mootdx_daily_raw(个股日线唯一落库表)、a_turnover_* 个股分布、zb/seal_rate(历史段)、industry_extras 东财。
**伪兜底**:akshare stock_daily.py(从未 backfill,progress 空);fallback 里 baostock 与主链共担同一时段(同晚同窗口),无错峰互备。

## ⑥ 修复方案(完整正确版)+ 任务拆单建议

### 根治方案矩阵
| # | 坏点 | 根治方案 | 备选源优先级 | 礼貌限流参数 |
|---|---|---|---|---|
| T1 | baostock 封禁不自解 | ①降并发 BAOSTOCK_WORKERS 3→1 + 连接间隔 2s(官方单连接串行模型,3 并发本身即风控诱因;8-14 起 3 worker 已两次撞墙) ②封禁期间自动改走 T3/T4 替代源,不空转 ③rebackfill 命令保留作人工通道 | 东财 push2his(带 turn?无,需算)→ 腾讯日线 → 新浪 | 单 worker;login 间隔 ≥3s;查询间隔 ≥0.5s;失败指数退避 30/60/120s |
| T2 | mootdx_progress 宇宙缩水至 85 只(隐性 bug,覆盖性写入) | ①启动时 reconcile:progress ∪ mootdx_daily_raw 的 DISTINCT code 对齐(库是事实源,progress 只是缓存) ②fallback save_progress 前与 DB 对账,禁止用残缺 dict 覆盖超集 ③本次先一次性全量重建(表内 5199 只真实在库,重跑 `mootdx_daily full` 断点续传只补 8/25 起) | — | mootdx 恢复前不消耗;恢复后单连接串行 0.12s/只 |
| T3 | mootdx 主源长期停服,全 A 日线无第二活源 | 启用并初始化 akshare stock_daily.py(东财 push2his,代码在位):手动 `stock_daily full` backfill 一次,此后 runner 的 stock_daily step 自动增量;东财 1s 节流已有 | ①akshare push2his ②腾讯 qt.gtimg 日线(含换手率!) ③新浪 | 东财 ≥1s/只+jitter(现档);腾讯批量接口 0.5s/批 |
| T4 | a_turnover_* 个股分布单源(baostock) | 腾讯日线接口含换手率字段(与 baostock turn 同口径),写 stock_daily 链新表或直补 cleanup_d3d2 入参;保留 baostock 为校验源 | ①腾讯 ②baostock(解封后) | 腾讯 0.3-0.5s/批 |
| T5 | width_history 上游单点 | 短期:industry_width/F3 与 D2 已有数据保持,断供日由 zhaban_rate(intraday)兜住前端;中期:T3 修复后 mootdx_daily_raw 恢复供给,width_history 自愈(run_recent 30 天窗口自动补回漏日) | — | — |
| T6 | fund_nav 门禁殃及全产物 | 独立修公募链 DB↔产物不一致(022402 等 3 只差 1 天,疑 export 快照窗口/时区),修前可临时将 fund_nav 校验降为 warn 不阻断(须用户拍板,§23.7⑤) | — | — |
| T7 | 三源同时恶化无错峰 | 关键链夜班错峰:mootdx/TCP 类 21:30 后跑(避开 17:50 高峰窗口);东财类 22:00 后;baostock 解封后仅跑增量补缺(不全量);update_all 各 pipeline 失败收口统一汇总为一条「今日缺口清单」告警 | — | — |

### 两个专项判断
- **baostock 封禁会否自解**:不会短期内自解。证据:8/25-8/27 连续三天同窗口被封;18:49 实测仍 10001011;错误文案「请与管理员联系」为账号/IP 级风控。方向:换出口 IP(代理/家宽切换)验证是否 IP 级;若是账号级则只能联系官方或弃用该源。注:baostock 官方无公开封禁时长文档,本结论基于自身三天观测+实测,外部公开资料未查到(T37 补充:社区无可靠解封时长先例)。
- **mootdx 要不要升级**:不需要。本机 0.11.7 = PyPI 最新,升级无解;根因是服务端「TCP 可达但 bars 空」(协议/停服),与客户端版本无关。换登录节点(_TDX_SERVERS)7/12 已试过全灭,bestip 动态选优也 EMPTY。结论:通达信免费 TCP 行情对本环境已实质不可用,把 T3 备源转正才是根治,不应继续把 mootdx 当主力等待。

## 复现

```bash
# 1. 今晚日志关键行(封禁/熔断/损失面)
grep -a -n 'parallel update done\|blacklist\|10002007\|疑似全停服\|东财封IP\|终止部署' \
  /Users/linhuichen/code/trade-data/data/logs/update_all_20260827_1750.log

# 2. 熔断机制与错误码(代码)
sed -n '55,80p;117,135p;160,180p' /Users/linhuichen/code/trade/app/collector/baostock_worker.py
sed -n '22,30p;226,241p' /Users/linhuichen/code/trade/app/collector/baostock_parallel.py
sed -n '433,453p;556,613p' /Users/linhuichen/code/trade/app/collector/runner.py

# 3. 慢性病时间轴(mootdx_daily_raw 每日覆盖数,7/22 起全 <1000)
sqlite3 /Users/linhuichen/code/trade-data/data/stock_daily.db \
  "SELECT date,COUNT(DISTINCT code) FROM mootdx_daily_raw WHERE date>='20260710' GROUP BY date ORDER BY date;"
# 4. progress 宇宙缩水(85 只)
python3 -c "import json;p=json.load(open('/Users/linhuichen/code/trade-data/data/mootdx_progress.json'));print(len(p),sorted(p)[:3],sorted(p)[-2:])"
# 5. 指标存活状态对比(旧已弃 vs 新在更 vs turnover 断)
sqlite3 /Users/linhuichen/code/trade-data/data/sentiment.db \
  "SELECT metric_id,MAX(date),source FROM daily_metric WHERE metric_id IN ('a_width_zb_count','a_width_seal_rate','a_width_zhaban_rate','a_width_fengban_rate','a_width_zt_count','a_turnover_mean') GROUP BY metric_id;"
# 6. baostock 封禁现测(预期 10001011)
/Users/linhuichen/code/trade/.venv/bin/python -c "import baostock as bs;lg=bs.login();print(lg.error_code,lg.error_msg)"
# 7. mootdx 现测(预期 EMPTY)
/Users/linhuichen/code/trade/.venv/bin/python -c "from mootdx.quotes import Quotes;c=Quotes.factory(market='std',bestip=True);d=c.bars(symbol='000001',frequency=9,offset=5,start=0);print('rows=',0 if d is None else len(d))"

# 数据截止:2026-08-27 18:50;关键口径:mootdx_daily_raw.turnover IS NULL=mootdx 写入/NOT NULL=baostock fallback 写入
```

