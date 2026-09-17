# 凯利演进弹窗 accum_nav_map per-ETF 懒加载落地方案(2026-09-17 调研)

用户拍板方向:懒加载(只拉组合需重算的 ETF 净值),不做 gzip。
本调研只读不改码;产出消费方全清单 + 数据层现状 + 选型 + 函数级改动点 + 一致性验证 + §5.4⑥判定 + 风险兜底。

## 一、消费方全清单(accum_nav_map 前端 11 处,生产加载器唯一)

数据流:`common.js _gihRealNavEnsure`(唯一生产加载器,拉全量文件)→ 写入 `window._kkellyRealNav`({etf_code:{YYYYMMDD:accum_nav}}) → 各重算点读它。

| # | 位置 | 函数/行号 | 角色 |
|---|---|---|---|
| 1 | static-site/common.js | `_gihRealNavEnsure` L1245-1278 | **唯一生产加载器**(双 URL R2+./data,15s 超时,失败冷却 60s);挂载为 window._kkellyRealNavEnsure(L1337/L1749) |
| 2 | static-site/common.js | `_gihRealizeRealForce` L1280-1330+ | **重算内核**(读 nav)。L1281 门控:navReadyNow=window._kkellyRealNav 为 object;L1282-1283 `window._kkellyRealNav[sel.etf_code][dt]` 取价 |
| 3 | static-site/lab.js | `_kellyRealNavEnsure` L8045-8065 | lab 兜底加载器(优先用 common 单例,common 未挂载才自拉全量) |
| 4 | static-site/lab.js | `_kellyNavReadyNow` L8059 / `_kellyNavFlush` L8063 / `_kellyNavWhenReady` L8069 | 就绪判定 + 补算回调(waiter) |
| 5 | static-site/lab.js | `_kellyNavWarmup` L8074-8099 | 背景预热(不 await),成功→flush 补算 |
| 6 | static-site/lab.js | `_kellyAihlineRealizeReal` L8099+ | lab 重算入口(优先调 window._kkellyRealizeRealForce,兜底自读) |
| 7 | static-site/lab.js | `_kellyApplyFeeRecompute` 内 L9048 | 主卡 144 桶循环,G/H/I 套 `_kellyAihlineApply(recomputed,...)` → real 强平分桶统计 |
| 8 | static-site/lab.js | `_kellyOperationalPool` L10478-10655(入口 L10491 warmup;门控 L10595 `_kellyNavReadyNow()`;navPending 占位 L10591/L10618-10626) | **演进弹窗·表格视图(方案B)** 重算池,唯一「调度层面直接用 nav」的演进路径 |
| 9 | static-site/lab.js | `_openSigKellyTradesModal` L12996 `_kellyAihlineApply` | lab 交易记录弹窗 G/H/I real |
| 10 | static-site/app.js | `_simRender`/`_simRenderOnce` L4188/L4200;重算 L3880(读 window._kkellyRealNav 才调 `_kkellyRealizeRealForce`);管位 L4468 `_simGhiHoldCap(kept,...)`;nav 门控+补渲 L4451-4463 | 首页模拟回测弹窗(§22 与 lab 共享核) |
| 11 | static-site/app.js | `_simNetassetCurve` L5496 + `_simRenderNetassetChart` L5609-5786(L5623 读 nav;L5783-5786 就绪判定+ensure 后 _render) | 逐日总资产走势图(每持仓日 1 点,nav 全史) |

注意:lab.js L10179「📈 信号凯利回测演进」弹窗(每日快照迷你曲线)数据源是 `signal_kelly_snapshots/index.json`,与 accum_nav_map 无关;真正的 nav 消费演进弹窗=L10453 表格视图(方案B)。

后端/离线消费(不受前端懒加载影响):
- docs/kelly/position/scripts/kelly_ghi_real_price_rebase.mjs、kelly_ghi_avsp_sweep.mjs:读本地 docs/kelly/position/scripts/accum_nav_map.json(回测,非 R2)。
- scripts/check_data_integrity.py:`check_accum_nav_map_fresh` L1024(新鲜度)+ `check_accum_nav_map_price_sane` L1051(单日价格分布),挂在 main L1850-1853。
- scripts/deploy.sh L219-234:每日生成 `export_accum_nav_map.py --all` → cp static-site/data/accum_nav_map.json(R2 上传源)。

## 二、数据层现状

1. **没有现成 per-ETF accum_nav 文件。** `static-site/data/etf/{code}-all.json`(1553 个)是 **行情不是净值**:字段 {date, exported_at, code, name, count, adj:"forward_accum_nav", source, ohlc:[[d,o,h,l,c],...]}(实测 510300-all.json 头部,前复权日K OHLC 四元组),不能直接当 nav 用。
2. `fund_nav/{code}.json`(26370 个)是公募基金净值,另一系统,与 ETF accum_nav 无关。
3. accum_nav_map.json 结构:顶层 {etf_code: {YYYYMMDD: accum_nav}};本地(9/13 生成)=1554 codes × 1,086,591 日期行 = **18.5MB**;线上 R2 `https://ss.fx8.store/r2/data/accum_nav_map.json` HEAD content-length=**26,010,281B(26.0MB)**,cf-cache-status HIT、ACAO:*。两者行数口径有差(线上更新到 20260916、本地只到 0911,但差 5 天不可能差 8MB),差异根源未在本调研范围确认;一致性对账时以同源下载文件互比为准。
4. per-ETF 大小分布(本地全量实测):中位 374 行/只;单 code JSON 字节估算 = 行数×17B → 中位 ≈6.4KB,最大(5241 行)≈89KB。
5. **组合实际涉及的 ETF 只有 116 只**:signal_kelly_trades.json(78MB,9/13 版)10 模式 × 30,432 行 = 304,320 行,distinct etf_code = **116**(其中评级三区并集 G 模式 = 116)。即全量文件里 1554-116=1438 只 ETF 是前端组合永远不用的。懒加载载荷上限 = 116 × ~8KB混均值 ≈ **≤1MB**(vs 全量 br 6.7MB),削减 6-18 倍;典型窗口(近1年/已过滤)更小。
6. 生成器 `docs/kelly/position/scripts/export_accum_nav_map.py`:单 SQL「SELECT etf_code,date,accum_nav FROM etf_daily WHERE accum_nav IS NOT NULL ORDER BY etf_code,date」→ 按 code 组装 dict(先按 code 分组再 `_filter_placeholder` 过滤占位残留)→ `json.dump` 单文件。**按 code 拆写 = 循环里每 code 一个 dump,零额外逻辑**。

## 三、选型对比

| 方案 | 一致性 | 代价 | 结论 |
|---|---|---|---|
| (a) 拆 per-ETF 文件(全量 1554,`accum_nav/{code}.json`) | 同源同 dict 拆分,逐位一致有天然保证;上传后层2 ETag 对账(引擎内建) | 生成器 ~10 行改动;上传复用 `_incremental_upload` 引擎(8 线程+md5 指纹+ETag 对账+状态清单),1554 keys ≈30-60s/日,总字节与现全量持平 | **推荐(主推)** |
| (b) Worker 按 code+date 查询 API | 需新建查询逻辑(R2 对象键设计/D1),引入新组件 | 突破项目「纯静态+R2 通用代理」架构;每笔强平一次请求,弱网 RTT 主导反而慢;无先例 | 否决 |
| (c) 变体:只拆 116 活跃 ETF / 按日期列存分片 | 列存破坏「per-ETF 全史」重算语义 | 省 1438 文件无用(增量引擎只传内容变化的,首跑后每日两种拆分成本几乎相同);列存无法 per-ETF 取全史 | 否决(只拆 116 仅在首跑省几分钟,不构成理由) |

依据(内部先例已成体系,§5.1 外部调研无必要):
- worker/headers.js L118-129:`/r2/*` 是**通用 key 代理,无前缀白名单**,`key = pathname 去掉 /r2/`,`noEdgeCache` 特判目前只有 fund_nav(L129)→ **新前缀 accum_nav/ 零 worker 改动**(curl 实证 /r2/etf/510300-all.json 200 OK)。
- 已三次验证同模式:etf/{code}-all.json(cmd_upload_etf_hist L910-931,增量+指纹+purge changed keys)、fund_nav(cmd_upload_fund_nav L934-966)、industry 31 拆(memory industry-all-cloudflare-25mb-split)。本次完全复用该模式,无未知。
- 缓存策略:etf 模式 = Cache-Control public max-age=3600 + 上传后 purge 本次 key(cache_prefix="/r2/")。nav 文件 append-only(历史日 nav 永不变),强平日都是历史日期,3600s 边缘缓存残留 4h 也只影响「最新一天持仓市值」≤1 天,且 deploy 链有 purge 失败告警。**推荐 etf 模式(可让浏览器缓存 1h,重开弹窗秒开,弱网体验最好)**;备选 fund_nav 模式(no-store 免 purge,但每次打开重新回源 116 文件 ≈1MB,需 worker L129 加一行特判)——不推。

## 四、前端函数级改动点(不写码,实施照此)

核心不变式:重算内核 `_gihRealizeRealForce`/`_kellyAihlineRealizeReal` **完全不动**(同一取数函数+同一数据值),只换「map 如何组装到位」+「就绪判定细化到 per-code」。9/17 刚上的时序门控(占位→flush 补算)全复用。

1. **common.js `_gihRealNavEnsure`(L1245):拆分改造为按需 + 保留兼容**。新增 `window._kkellyRealNavEnsureCodes(codesArr)`:并行 fetch `${R2}/r2/accum_nav/{code}.json`(fallback ./data/accum_nav/{code}.json,15s),成功 merge 进 window._kkellyRealNav;per-code 失败记入 `_kkellyNavFailedCodes`(Set)+60s 冷却(与现 L1253 同口径);Promise.all 落定后 resolve。旧无参 `_gihRealNavEnsure()` 保留签名(内部改写为「对当前预扫出的 code 集拉取」或留作兜底);现有无参调用点仅 3 处待接(lab L8047、app L4459、app L5786,已 grep 核实),另有挂载点 common L1337/L1749 与 warmup 入口 lab L8830/L10491 改走按集预热。
2. **common.js `_gihRealizeRealForce` 门控细化(L1281-1290)**:navReadyNow 判定从「window._kkellyRealNav 是 object」改为「该 sel.etf_code 已载入 map」;新增 `window._kkellyNavCodeStatus(code)` 返回 loaded/failed/pending 三态,用于区分:L1284 时序窗口跳过(pending)+ 失败计数(failed,__gih_missing_px_+1)——防「懒加载下某 code 未及时载入被误吞为时序窗口、或零件齐全反而误计缺价」,这是懒加载改造最隐蔽的两个新 bug 点。
3. **lab.js `_kellyNavWarmup`(L8074)+ `_kellyNavReadyNow`(L8059)**:warmup 目标从全量改为「当前组合涉及 code 集」;ready 语义 = 涉及集全部 loaded。三个 warmup 调用点配套传集:L8830(主引擎)、L10491(演进池)、主卡入口。
4. **code 集收集点(关键新逻辑,4 处)**:G/H/I 重算需要 nav 的 code = 过滤+管位后 kept 行的 etf_code 并集(trades 全集 116,过滤后更少)。管位/过滤本身不依赖 nav(实测 `_kellyPassesFadeFilters`/posCap/s06 谓词纯特征,S6 快照另源),因此:
   - lab 主卡 `_kellyApplyFeeRecompute`:入口对 GIH 相关模式 quadsAll 行先做同谓词过滤(用现有 _labS06 分支同款谓词)或直接取「trades 全 116」预热(先粗后细,反正 ≤1MB);
   - lab 演进池 `_kellyOperationalPool`:在 L10595 `_kellyNavReadyNow()` 判定前,本期 toggled 行 collect etf_code → ensureCodes(fire,不 await;未就绪维持现有 navPending 占位 L10618-10626,nav 到位重建);
   - app.js `_simRender`:L4468 `_simGhiHoldCap` 之前 collect kept 的 etf_code 集 → ensureCodes(不 await),L4451-4463 补渲回调保留,判定条件从「map 是 object」改「涉及 codes 全 loaded」;
   - app.js `_simRenderNetassetChart`:L5631 调用 `_simNetassetCurve` 前同理;曲线 code 范围 = rows 涉及 etf_code ∪ 持仓中未平仓 code。
5. **lab.js `_openSigKellyTradesModal`(L12996)**:复用 #4 主卡同一 result(交易记录弹窗常与主卡同页,map 已合并)。

## 五、数据一致性验证(§5.4⑦)

1. **生成同源机检(硬)**:export_accum_nav_map.py 拆分循环用与全量同一 maps dict 逐 code dump;check_data_integrity.py 新增机检 `accum_nav_split_consistency`(L1850-1853 处挂):load 全量 + 目录下每个 per-ETF 文件,逐 code×逐 date 对账,不相符 FAIL 阻断。
2. **上传对账(硬)**:`_incremental_upload` 引擎层2 已内建「PUT 后 HEAD:ETag==本地整文件 md5」;外加 deploy 后抽查(异步)线上 accum_nav/{code}.json 与本地拆分产物逐位一致。
3. **前端同构对账机检(硬,§5.4⑦ 强制)**:新脚本 scripts/playwright-accept/verify_nav_lazy_consistency.mjs(骨架仿 verify_gih_nav_gate.mjs L1-40 的 recorder/计数):
   - 场景A:Playwright route **block 全量 accum_nav_map.json**、放行 accum_nav/* → G/H/I 各档数字;
   - 场景B:block accum_nav/*、放行全量 → 同档;
   - 断言 A 与 B 数字**逐位一致**(覆盖 G/H/I × y1/all 两周期 + 首页 sim 弹窗同档 + lab 演进表格视图),漂移 FAIL。
   - 单 code 缺失注入:route abort 某 code → 断言该行「— 缺价」红字 + __gih_missing_px_=1 + 其它行不受影响。
4. **上线实测锚点**:懒加载上线后 Playwright 无痕实测 G/H/I 权威数字,与 memory `test-baseline-v112-anchor`(v1.1.7 tag@384005e222)复现锚点对照。
5. 线上全量文件(26MB)与本地(18.5MB)差异:对账以「同源下载」互比,不拿本地对线上。

## 六、§5.4⑥ 版本升级判定

**结论:发一次中间版本标记(建议 v1.1.13),不回测测试基准定义。**
- 依据:v1.1.1 先例——「动到 AI推荐/降亏过滤相关数据层人口口径(非默认组合本身)也须发版本标记,但不回测基准定义」。本次动的是核心功能取数路径(数据供给链路),默认组合/算法/键集全不动,重算结果应逐位一致(同源数据 + 内核函数零改动)。
- 动作:版本标记 + 前端默认值/§21 公示(purpose-notes.js 若提及数据源说明)/README + 18 处键集登记点零改动(键集没变)——键集一致性机检照常跑证明零漂移。
- 由 §五.3 一致性机检 PASS 背书「逐位一致」,若机检出现任意档漂移=设计错误,停下重来。

## 七、风险/兜底

1. **某 code 文件 404/超时**:该 code 进 failed 集 + 60s 冷却 → `_kkellyNavCodeStatus`=failed → `_gihRealizeRealForce` 对涉及行硬报错标「— 缺价」红字 + __gih_missing_px_ 计数(用户铁律:无 b1 兜底,与现行语义一致);不阻塞其它 code。冷却期内不重拉(防 480s/轮旧病复发)。
2. **pending(code 尚在拉取)= 时序窗口**:L1284/L10618 现有两处时序门控语义不变,只是判定细化到 per-code——差异点必须覆在机检里(场景A 若全量被 block 且 acn 放行,正常网络下应 0 缺价)。
3. **全量文件保留**:R2 全量 accum_nav_map.json 继续每日生成+上传,作为:线上去全量路径的 fallback(必要时一键回退)、回测脚本本地数据源、check_data_integrity 两机检对象。前端新路径彻底失效且机检失败时,主控可仅回滚前端点(数据层两份并存,回滚独立)。
4. **缓存键**:URL = /r2/accum_nav/{code}.json,不带版本串(内容变 ETag 变);边缘 3600s + 上传后 purge 本次 key(etf 模式);浏览器缓存 1h 重开弹窗零流量。若用户后续要求「nav 最新一天必须即看」,切 fund_nav 模式(no-store + worker L129 一行)。
5. **cost 上限**:上传字节/日与现状全量单文件持平(~18.5-26MB/日);对象数 +1554(fund_nav 已有 26370 对象先例,R2 零障碍)。

## 复现段

本调研关键数字统计命令(全部只读,可复跑):
```
python3 -c "import json;d=json.load(open('static-site/data/accum_nav_map.json'));print(len(d),sum(len(v) for v in d.values()))"   # 1554 / 1086591
python3 -c "import json,collections;d=json.load(open('static-site/data/signal_kelly_trades.json'));f=d['fields'];e=f.index('etf_code');c=set();[c.add(t[e]) for rk in d['quadrants'] if isinstance(d['quadrants'][rk],dict) for m in d['quadrants'][rk] for t in d['quadrants'][rk][m]];print(len(c))"   # 116
curl -sI https://ss.fx8.store/r2/data/accum_nav_map.json            # content-length: 26010281
curl -sI https://ss.fx8.store/r2/etf/510300-all.json               # 200, per-ETF 先例
curl -s -r 0-1500 https://ss.fx8.store/r2/data/accum_nav_map.json  # 线上 4 位小数精度与本地一致,行数口径不同
head -c 600 static-site/data/etf/510300-all.json                    # ohlc 行情非净值
```
消费点行号与函数名:见第一节表(grep 锚点:accum_nav_map / _kkellyRealNav / _kellyNavReadyNow / _kellyNavWarmup / _kellyOperationalPool)。
