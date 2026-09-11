# 次日买入实操步骤增强 · 四需求设计方案(2026-09-10)

> 调研:researcher | 只读零改动 | 任务:出「次日买入实操步骤增强」设计(需求1-4)
> 关联实现:static-site/lab.js `_at` 区块(实操步骤,13939-14326)+ scripts/nextday_plan_generator.py + static-site/data/auto_trade_steps.json
> PRD:docs/auto-trade/next-day-buy-prd-20260910.md

## 0. 结论速览

| 需求 | 方案 | 分级 | 改动面 |
|---|---|---|---|
| 1 兜底步骤展示时点 | 生成器写 seq2/seq3 独立行 + 前端按「当前时间+盘中现价」派生推进(不写回 JSON) | P0 | 生成器 ~15 行 + 前端 ~100 行 |
| 2 操作标记 | 前端 localStorage 按钮「✓ 我已操作」 | P0 | 前端 ~60 行 |
| 3 盘中现价 | 前端直连腾讯行情 https://qt.gtimg.cn(实测 CORS `*` 开放)展示现价+相对挂单盈亏 | P0 | 前端 ~60 行,零后端 |
| 4 点击 ETF 出走势 | 复用 app.js 全局 `_etfTrendLiteHTML/_etfTrendLiteBind` + R2 `{code}-all.json` 新开轻量弹窗 | P0 | 前端 ~80 行,零后端 |

关键事实:**腾讯 A 股 ETF 实时行情 `https://qt.gtimg.cn/q=sh513080` 实测返回 现价/昨收/今开/最高/最低/时间/涨跌/涨幅,且 `Access-Control-Allow-Origin: *`**(前端可直连,零后端/零代理/零新增定时任务);**auto_trade_steps.json 唯一写入方 = 生成器(20:55 盘后一次),盘中无任何推进机制**(前端 `_at` 只读 status 不按时间推进)。

## 1. 现状梳理(证据)

### 1.1 auto_trade_steps.json 结构(当前)
- `static-site/data/auto_trade_steps.json`:`{schema_version:"v1", steps:[{date,seq,time_slot,action,etf_code,etf_name,order_price,expected_range,decision,amount,shares_planned,status,status_text,signal,track_score,trigger_note,updated_at}]}`
- 当前只有 **seq1 一行**:`date=20260911, seq=1, time_slot=09:15, order_price=1.762(昨收), status=pending, status_text=待执行`;`decision` 文案含「9:25 集合竞价: O ≤ 1.762? 是→按O成交; 否→高开等回落触及 1.762; 14:55 仍未触及→撤单市价兜底」但**无独立 seq2/seq3 步骤行**(static-site/data/auto_trade_steps.json L3-22)。
- 生成器只写 seq1:`nextday_plan_generator.py` L461-483 `step` 构造块(`seq: 1, time_slot: "09:15"` 硬编码,L463-466)。
- 唯一写入方:`nextday_plan_generator.py`(20:55 盘后,launchd `com.trade.nextday-plan` plist StartCalendarInterval 工作日 20:55);盘中无任何写入方。机检:`check_data_integrity.py` L1931-1942 校验 schema_version v1 + steps 数组。

### 1.2 前端实操步骤渲染(证据)
- 数据源:`_AT_URL_PLAN = "./data/nextday_plan.json"` / `_AT_URL_STEPS = "./data/auto_trade_steps.json"`(lab.js L13953-13954);`_atFetch` 复用全局 fetchJSON + `?_=` 破缓存(L14008-14014)。
- 状态机:`_AT_STATUS_CLS` pending灰/submitted蓝/filled绿/partial_filled橙/cancelled灰/tailback紫/skipped灰/done绿/failed红(lab.js L13955)。
- 主表:`_atBuildDays` 每日一行(L14121),`_atRowHtml` 7列「日期/计划动作/挂单价/金额份数/状态/实际成交价/触发条件摘要」(L14156-14170)。
- 「现在该干嘛」:`_atNowAction` 只取当日 pending/submitted 中 **seq 最小**者(L14141-14147)→ 永远指向 seq1,**不按 time_slot 时间推进**。
- 弹窗:`_atModalRowHtml` 按 seq 排序展示行 + 多日翻页(L14244-14308);ETF 代码是纯文本(L14258),**无点击事件**。
- 轮询:`_atPollingMs` 盘中(周一-五 9:00-17:50)60s / 盘后休市 5min(L14212-14217);`_atSchedule`/`_atInit` 就地更新(L14218-14242)。

### 1.3 需求3 盘中现价数据源(证据)
- **现状无「单 ETF 盘中现价」前端可读产物**:
  - akshare `fund_etf_fund_daily_em` 全市场 1639 只,列=「基金代码/基金简称/类型/单位净值/累计净值/增长值/增长率/**市价**/折价率」——**无今开/最高/最低**(实测输出,2026-09-10)。盘中管道 `pipeline_intraday_realtime` 只把 12 只汪汪队写 DB etf_daily 末日 close(etf_national_team.py L1474-1506),前端盘中预估值靠 export_json_files 的 share_change NULL 触发。
  - `intraday_snapshot.json` 只含 indices/industries/concepts/us_futures/global_realtime,**无单 ETF**(实测 keys)。
  - `signal_kelly_trades_intraday.json` 盘中档含 real_current_price(9:40 kelly-intraday-rerun 生成 + refresh_intraday_cur_prices 9:35-14:50 刷新,etf_national_team.py L1334-1438),但**只覆盖回测入账 ETF,非任意 ETF**。
  - `static-site/data/etf/{code}-all.json` 只有**日线全史**(export_etf_hist.py 生成,513080 有 1515 根,数据到 20260909),无盘中分时。
- **腾讯行情可直连**(index_backfill.py L560-598 解析先例,实测):`https://qt.gtimg.cn/q=sh513080` 返回 GBK,`~` 分隔;`Access-Control-Allow-Origin: *`(http/https 均实测)。字段下标:`[3]`现价 `[4]`昨收 `[5]`今开 `[30]`时间 `[31]`涨跌 `[32]`涨幅% `[33]`最高 `[34]`最低。

### 1.4 需求4 走势图复用点(证据)
- `_LAB_ETF_PIN_URL(code) = https://ss.fx8.store/r2/etf/{code}-all.json` / fallback `./data/etf/{code}-all.json`(lab.js L13415-13416)。
- 全局轻量 K 线组件:`_etfTrendLiteHTML(ohlc)`(app.js L25070,纯 ohlc `[[YYYYMMDD,o,h,l,c],...]` 输入输出 SVG)+ `_etfTrendLiteBind(svg, ohlc, opts)`(L25091,hover/缩放)+ `_etfTrendGeom(ohlc,w)`(L24941)。**零依赖、纯函数、同页全局可用**(25593 行既有复用)。
- `_openEtfTrendPinModal(code,name,trades,eliminated,fields,srcRow,srcKey)`(lab.js L13452)不可直接复用:内部 `_collectEtfPinEvents` 收集交易事件,`if (!allEvents.length) return;` 空事件直接不弹(L13456-13559);实操步骤场景无交易事件数据。
- `{code}-all.json` 数据就绪:513080-all.json 55KB/1515 根,已 R2 同步。

### 1.5 需求2 操作标记先例(证据)
- 无「操作状态标记」类交互先例;localStorage 全是**用户偏好记忆**(展开/收起 lab_sigkelly_params_open L10830、K 档 tds_poscap_lab L7906、filters tds_kelly_filters L9563、buy basis L8427 等),无「标记已完成」类。
- auto_trade_steps.json 只读展示,前端不写(唯一写方=生成器)。

## 2. 设计方案

### 2.1 需求1:兜底买入步骤展示时点

**建议方案(P0):seq2/seq3 独立行 + 前端时间线派生推进(不写回 JSON)**

1. **生成器写 seq2/seq3 静态行**(盘后 20:55 一次,幂等追加同 date 已存在跳过):
   - seq2 = 09:25 集合竞价判定:`time_slot=09:25, action=buy, order_price=昨收, decision=「9:25 竞价判定: 开盘价 O ≤ 昨收? 是→按 O 成交; 否→高开等回落触及 昨收」, status=pending`
   - seq3 = 14:55 尾盘兜底:`time_slot=14:55, action=buy, order_price=昨收, decision=「14:55 仍未触及昨收→撤单市价兜底」, status=pending`
   - 理由:让「兜底买入步骤」从 seq1 decision 文案中拆出为**可见的时间线步骤**(弹窗 `_atModalRowHtml` 已按 seq 排序),满足用户「兜底操作步骤什么时候更新显示出来」的第一层诉求=先可见。
2. **前端派生推进(核心)**:`_at` 区块新增「当前步骤判定」函数,输入=当前时间 + 当日步骤 + 盘中现价,输出=当前应高亮/提示的步骤行:
   - `<09:15` → seq1 待执行(挂单前)
   - `09:15-09:25` → seq1 已挂单(提示:已挂限价单)
   - `09:25-14:55` → seq2 竞价判定行(结合现价 vs 挂单价:现价 ≤ 挂单价→「已回落至挂单价下方,大概率成交」;现价 > 挂单价→「高开未回落,等尾盘兜底」)
   - `≥14:55` → seq3 兜底行
   - `_atNowAction` 从「只看 status」改为「status × time_slot 与当前时间」联合判定,「现在该干嘛」提示条 + 当日行高亮随之推进。
   - **不写回 JSON**(auto_trade_steps.json 保持只由生成器写):避免多写入方并发冲突(§23.11)、避免盘中每 60s 后端写 R2 的写放大;前端派生幂等、零写放大、零并发风险。
3. **推进数据源 = 腾讯行情前端直连**(与需求3共用):现价 `[3]`/今开 `[5]`/最低 `[34]`/时间 `[30]`。
   - ⚠ 诚实标注:干跑阶段(AUTO_EXEC_ON=false)无券商成交回报,**无法确认真实成交**,只做「时间线推进 + 现价辅助判定(可能已成交/等回落/等兜底)」,不做「确凿成交状态」。真实成交状态需接券商接口(P1,见方案分级)。
   - 数据供给链路:seq2/3 行 = 生成器 20:55 已有 launchd(`com.trade.nextday-plan`)+ 幂等 + `check_data_integrity.py` 校验(机检已在);盘中推进 = **前端直连腾讯实时源,天然最新,无过期风险,不新增定时任务**(§5.3 L45 教训的「谁每天更新它」= 实时源自更新)。

**改动点清单**:
- 生成器 `nextday_plan_generator.py`:L461-483 step 构造块,`for` 循环内追加 seq2/seq3 两行(~15 行)。
- 前端 `lab.js` `_at` 区块:`_atNowAction` 改为时间联合判定(~20 行)+ 新增现价派生状态函数(~30 行)+ 高亮/提示条适配(~20 行)+ `_atPollingMs` 循环并入腾讯行情 fetch(~20 行)。
- 数据源:无新增后端产物(前端直连腾讯);如需后端兜底 → P1 `etf_realtime_prices.json`。

### 2.2 需求2:操作标记

**建议方案(P0):前端 localStorage 按钮「✓ 我已操作」**

- 键:`at_steps_marked`,值 `{"20260911|513080|1": {marked_at:"2026-09-11 09:20"}, ...}`。
- 交互:弹窗 `_atModalRowHtml` 每行尾部加「✓ 我已操作」按钮;点击 → 本地标记 + 该行 status_text 变「已操作(手动)」+ 主表摘要行同步 + 高亮解除(退出「现在该干嘛」);再次点击取消标记。
- 理由:干跑阶段操作标记是**纯本地提醒**(计划非真实下单),localStorage 单设备零后端写入、零 R2、零并发冲突(§23.11 安全);与既有 localStorage 偏好先例同模式(lab.js L10830/L7906/L8427)。
- 跨设备(P1):需后端落盘 `user_marked` 字段 + 状态更新通道 + R2 同步(多写入方管理成本高),用户明确要多设备再排。
- 数据供给链路:localStorage 无链路;P1 后端版需新增状态更新 API/生成器回写。

**改动点清单**:
- 前端 `lab.js` `_at` 区块:localStorage 读写 helper(~15 行)+ 按钮渲染 + 状态合并(~30 行)+ 主表摘要同步(~15 行)。

### 2.3 需求3:盘中现价展示

**建议方案(P0):前端直连腾讯行情,行内展示现价 + 相对挂单价盈亏**

- 数据源:`https://qt.gtimg.cn/q=sh{six}|sz{six}`(按 etf_code 前缀 sh/sz,复用 etf_national_team.py `_etf_market` 同款判定:51/56/58→sh,15/16→sz)。**CORS `*` 已实测**(http/https 均 200 + Access-Control-Allow-Origin:*);页面 https 用 https 端点(实测 200)。
- 交互:主表第6列「实际成交价」语义扩展为「现价/成交」,弹窗同列同口径:
  - 现价 = 腾讯 `[3]`;相对挂单盈亏% = `(现价 - order_price) / order_price`,涨红跌绿(对齐站点涨跌色 #e6492e 红 / #2e8b57 绿)。
  - 盘后/休市:腾讯返回收盘快照(实测 20260910161500 时间戳)→ 显示收盘价 + 最终盈亏,语义正确。
  - 数据源不可达(网络/限流)→ 该列显示「-」+ tooltip「实时价不可达」,不阻塞主流程(与 `_atFetch` 的 catch→null 同精神)。
- 轮询复用:`_atPollingMs` 既有盘中 60s/盘后 5min 循环,新增一个 `_atFetch` 腾讯行情即可。
- 数据供给链路:前端直连实时源(天然最新,无过期,不新增定时/产物)。

**备选方案(P1,不想前端直连腾讯时)**:在 `pipeline_intraday_realtime` 内复用已拉 akshare 全市场 df,顺带落盘 `static-site/data/etf_realtime_prices.json`(code→市价)+ R2(与 `refresh_intraday_cur_prices` 2026-09-10 同构「复用 df 零额外拉取」);但 akshare df **无今开/最低**,只能给现价、给不了需求1的回落判定 → 不如腾讯直连完整。

**改动点清单**:
- 前端 `lab.js` `_at` 区块:`_atFetchRealtimePrice(code)`(~15 行)+ 主表/弹窗行现价列渲染(~30 行)+ 盈亏色(~10 行)。
- 零后端改动(腾讯直连)。

### 2.4 需求4:点击 ETF 代码出走势图

**建议方案(P0):复用 `_etfTrendLiteHTML` 新开轻量走势弹窗**

- 交互:主表/弹窗的 ETF 代码 td 加 `data-code` + 点击(参照 lab.js L13388 交易记录弹窗 etfcode 点击模式,但**不带交易事件上下文**)→ 新开 overlay 弹窗:
  1. fetch `_LAB_ETF_PIN_URL(code)`(R2 直链,15s 超时)fallback `_LAB_ETF_PIN_FALLBACK(code)`(本地);
  2. 校验 `hist.ohlc` 数组非空;
  3. `chartArea.innerHTML = '<div class="lab-etf-pin-wrap">' + _etfTrendLiteHTML(ohlc) + '</div>'` + `_etfTrendLiteBind(svg, ohlc, {panZoom:true})`(复用 L13467 模式);
  4. overlay 骨架参照 `_openEtfTrendPinModal` L13472-13483(overlay id 换 `lab-autotrade-etf-overlay`,z-index 10001 同款)。
- 理由:`_etfTrendLiteHTML/_etfTrendLiteBind/_etfTrendGeom` 是 app.js 全局纯函数,输入仅 ohlc,零依赖;`{code}-all.json` 数据已就绪(513080 1515 根,R2 已同步);R2 URL 常量已存在(`_LAB_ETF_PIN_URL` L13415)。
- **不可直接复用 `_openEtfTrendPinModal`**:它强依赖 trades/eliminated 交易事件,空事件直接 return 不弹(lab.js L13456-13459)。
- 数据供给链路:`{code}-all.json` 由 `scripts/export_etf_hist.py`(盘后 update-all 链)生成 + upload-etf-hist 传 R2,已有(launchd 17:50 update-all + 每日 deploy)。

**改动点清单**:
- 前端 `lab.js` `_at` 区块:`_atOpenEtfChart(code, name)`(~50 行)+ 主表/弹窗 ETF 代码单元格点击绑定(~30 行)。

## 3. 方案分级与改动面

### P0(必须做,一次上线)
1. 需求1:生成器 seq2/3 行 + 前端时间线推进 —— 生成器 ~15 行 + 前端 ~100 行
2. 需求2:localStorage 操作标记 —— 前端 ~60 行
3. 需求3:盘中现价 + 相对挂单盈亏(腾讯直连)—— 前端 ~60 行
4. 需求4:点击 ETF 出走势弹窗 —— 前端 ~80 行

**P0 汇总**:改动集中在 前端 lab.js `_at` 区块(13939-14326,单文件,前缀 `_at` 隔离,风险低)+ 生成器一个文件;零新增定时任务、零新增 R2 产物(腾讯直连)、零 DB 改动。前端改动遵循 §24(改源码同 commit bump 版本串 + build_min)。

### P1(可并行)
- 需求1 精确回落判定/真实成交确认:需券商接口(AUTO_EXEC_ON=true 阶段)或腾讯今开/最低接后端。
- 需求3 后端落盘 `etf_realtime_prices.json`(若用户不想前端直连腾讯;akshare df 只有市价)。
- 需求2 跨设备同步(后端 `user_marked` 字段 + 更新通道)。

### 可选
- 盘中分时图(1min K):mootdx bars 分钟线可拉但成本高,需求4 日K 已满足「走势图」诉求。
- 盘中现价触及挂单价的飞书/邮件预警:复用 notify 链路,超出本任务范围。

## 4. 数据供给链路自检(§5.3 L45 教训:动态展示必须有谁更新它)

| 展示项 | 谁生成 | 定时/触发 | 机检 | 告警 | 过期风险 |
|---|---|---|---|---|---|
| seq2/3 步骤行 | 生成器 nextday_plan_generator.py | 20:55 launchd(已有) | check_data_integrity L1931(已有) | 生成器 F2 severe(已有) | 低(盘后一次) |
| 盘中现价/推进 | **前端直连腾讯实时源** | 前端 60s 轮询(已有) | 腾讯源自身 | 不可达→列显「-」降级 | 无(实时源自更新) |
| 走势图 {code}-all.json | export_etf_hist.py | 17:50 update-all(已有) | check_data_integrity | deploy 链 | 低(日更) |
| 操作标记 | localStorage(用户动作) | 用户点击 | 无(单设备) | 无 | 单设备,不跨端 |

## 5. 关键证据引用(供 §0 单点验收)

- seq1 单行现状:`static-site/data/auto_trade_steps.json` L3-22(仅 seq1,decision 文案含兜底策略)
- 生成器只写 seq1:`scripts/nextday_plan_generator.py` L463-466(`seq:1, time_slot:"09:15"` 硬编码)
- 前端不按时间推进:`static-site/lab.js` L14141-14147(`_atNowAction` 只看 status × seq)
- 前端轮询已有:`static-site/lab.js` L14212-14217(盘中 60s)
- 现价列现状=空:`static-site/lab.js` L14167/L14262(`actual_price` 字段无值→「-」)
- 腾讯行情可用:`app/collector/index_backfill.py` L560-598 解析先例;实测 `curl "https://qt.gtimg.cn/q=sh513080"` 返回含现价/昨收/今开/最高/最低 + CORS `*`
- akshare df 无今开/最高/最低:实测 `fund_etf_fund_daily_em` 列=基金代码/基金简称/类型/单位净值/累计净值/增长值/增长率/市价/折价率
- 走势组件全局可复用:`static-site/app.js` L25070 `_etfTrendLiteHTML` / L25091 `_etfTrendLiteBind` / L24941 `_etfTrendGeom`
- 走势数据就绪:`static-site/data/etf/513080-all.json`(1515 根日K)+ R2 直链常量 `_LAB_ETF_PIN_URL` lab.js L13415
- `_openEtfTrendPinModal` 不可直接复用:`static-site/lab.js` L13456-13459(空事件 return)
- auto_trade_steps 唯一写方+机检:`scripts/check_data_integrity.py` L1931-1942;`nextday_plan_generator.py` L442-488(幂等追加)

## 复现

- **报告路径**:`docs/kelly/analysis/nextday-steps-enhance-design-20260910.md`(本文件)
- **输入依赖**:本设计为只读调研,无新增生成脚本;验证用命令:
  - 生成器 dry-run(验证 seq 结构不破坏现有追加):`REPO=/Users/linhuichen/code/trade-data GIT_REPO=/Users/linhuichen/code/trade python3 scripts/nextday_plan_generator.py --date 20260910 --dry-run`
  - 腾讯行情字段验证:`curl -s "https://qt.gtimg.cn/q=sh513080" | iconv -f gbk -t utf-8`(期望含 `~1.762~1.793~1.764~` 即 现价~昨收~今开 顺序,下标 [3][4][5])
  - 走势数据就绪:`python3 -c "import json;d=json.load(open('static-site/data/etf/513080-all.json'));print(len(d['ohlc']))"`(期望 ≥1500)
  - 前端渲染:浏览器打开 lab 页实操步骤区块;P0 上线后验主表现价列有值 + 弹窗时间线含 seq2/seq3 + ETF 代码可点击出走势
- **数据截止**:2026-09-10 收盘(auto_trade_steps.json updated_at 2026-09-10 22:23:54;513080-all.json date 20260909)
- **关键口径**:挂单价=昨收(T 日收盘);seq2=09:25 竞价判定;seq3=14:55 尾盘兜底;现价=腾讯行情 `[3]`;相对挂单盈亏=(现价-挂单价)/挂单价;干跑阶段无真实成交确认。
