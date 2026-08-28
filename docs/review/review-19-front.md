# Review #19 前端「首页近期冰点日区块→近90日情绪日历」(feat/ice-sentiment-calendar-front)

- 审查:reviewer agent | 日期:2026-08-19
- 分支:feat/ice-sentiment-calendar-front | commit:8abefd7c2 | base:e245c9a84(=当前 main)
- 改动范围:static-site/app.js 单文件 49 insertions / 2 deletions(新增 `_renderSentimentCalendar` 函数 + 冰点卡渲染行改条件分支)
- 分级:B 级(逻辑,有隐藏影响面——新增展示位消费新数据字段,但渲染复用既有函数/类/CSS)

## 结论:PASS

未发现阻塞性回归。即便后端 sentiment_calendar 字段未上线(main 数据层现状),前端单独上也不白屏、不破坏冰点区块原有展示,降级路径验证通过。

## 证据点

### 1. 功能正确性(全过)
- 语法:`node --check static-site/app.js` = SYNTAX_OK
- 新增 `_renderSentimentCalendar(cal)`(app.js L3038-3078):纯函数返回字符串,空日历返回 "",不依赖外部状态,无副作用
- 后端字段结构(queries.py L1256-1269)与前端读取(app.js L3044-3062)逐字段核对:
  - day.date → dt(YYYYMMDD)→ fmtDate(L3180)= "MM-DD"
  - day.freeze[{score_id,value}] → 冰点格;day.signals[{index_id,signal,reason}] → 信号格
  - 字段名 100% 对齐
- 同日双列并存:freezeCells + sigCells 拼接同一行(L3064),20260708/20260623 样例成立
- 组内排序 ord={buy:0, buy_aux:1, sell:2}(L3046)与后端(_sig_ord 同值)、与 renderSentimentSignalList(L18426)三方一致
- 冰点格(L3053)与原 freeze cell(L2876)逐属性一致:data-idx="s.${score_id}" / data-sig="freeze" / data-date / data-val 全同,仅新增 data-idx-name(增强)
- 信号格(L3062)与 renderSentimentSignalList cell(L18437)逐属性一致,仅新增 data-idx-name + _escAttr(title 转义,增强)
- 点击委托:freezeCard.addEventListener 委托(L11883-11889)已存在,覆盖新生成的 .sig-clickable;data-idx="s.*" → openSignalChartModal startsWith("s.") 分支 → sentiment-all.json 拉走势(L6185-6195),sentiment-all.json 存在(4.5MB)且 key 匹配(a_sentiment/sentiment_kc50/fear_greed 等全在);data-sig="freeze" → isFreeze=true(L6124)→ 标题"冰点(值)" + 追加 ≤20 蓝标注
- 冰点蓝:signalColor freeze=#42a5f5(L359)未被触碰;DOM 蓝值走 .freeze-val CSS(#2563eb,style.css L908)

### 2. §22 数据源一致性(全过)
- 情绪日历 signals 后端来源:signal_daily WHERE index_id LIKE 's.%'(queries.py L1238-1239)
- 市场温度 tab renderSentimentSignalList 消费 sentiment-{range}.json r.signals(renderSentimentMarketTemp L18055 fetch)
- 同源抽查:静态数据层 sentiment-all.json 与 sentiment-6m.json signals keys 完全相同,最近信号逐项一致(a_sentiment 20260623 sell / cross_market 20260708 buy_aux / sentiment_hs300 20260818 sell 等)—— 两者与 sentiment_calendar 同源 signal_daily s.*
- 渲染口径三方一致:HTML 结构(sig-day-row/sig-day-date/sig-items/sig-item)、signalLabel 文案、b.sell/buy/buy_aux 颜色 CSS、组内排序
- 唯一差异=窗口:日历近90日(标题写清"近 90 日情绪日历"),市场温度 tab 近15日(标题"近 15 日")。同源不同窗,非矛盾(§22 精神=同源同口径,窗口是策略)

### 3. 降级兜底(全过)
- `const _sentCal = Array.isArray(r.sentiment_calendar) ? r.sentiment_calendar : null;`(L11871)+ `_sentCal && _sentCal.length`(L11874)双保险:无字段/空数组/null/非数组 → 全部走 `_renderSignalGrid(r.recent_freeze, ...)` 原路径
- 当前 main 数据层实测:static-site/data/overview.json 无 sentiment_calendar 字段(后端未合并),recent_freeze 29 条 → 降级走原"近期冰点日(近 120 日)"展示,有内容不白屏
- 原 _renderSignalGrid 空 items 时返回 empty-note("无近期冰点日"),为既有行为,非新风险

### 4. 区域隔离(全过)
- git diff e245c9a84..8abefd7c2 --stat:仅 static-site/app.js,49+/2-,只改 2 处(L3026 后新增函数、L11822 冰点卡渲染行)
- 未触碰:signalColor(L359)/signalLabel(L401)/freeze 蓝 #42a5f5/indexChart tooltip(#73)/renderOverview 生命周期与新闻区(#12)/sigCard 与 signals_today 过滤逻辑
- 复用 CSS 类全部存在:style.css L893-932(sig-day-row/sig-day-date/sig-items/sig-item/sig-freeze-name/freeze-val/sig-clickable)

### 5. §22 展示位一致性(全过)
- 首页情绪日历与市场温度 tab 展示同一套情绪分信号(同源 signal_daily s.* + 同渲染口径),日历额外合并冰点列,窗口不同但标题各自写清
- 与原"近期冰点日"卡相比:数据更丰富(合并信号),不矛盾;addFreezeEventBadge 角标仍基于 recent_freeze[0] 正常保留

## 观察点(非阻塞,记录备查)
1. 情绪日历信号格 title 用 _escAttr 转义,renderSentimentSignalList 未转义——往更安全方向,非回归;如后续统一口径可顺手对齐
2. 信号格 `<b class="${s.signal}">` 若后端出现 signalLabel 未覆盖的信号值,label 走 fallback"趋势转弱"、CSS class 可能无定义——但 renderSentimentSignalList 同样处理、后端 s.* 类型固定(buy/buy_aux/sell),行为一致,非新风险
3. 情绪日历仅在后端字段上线后才会渲染;当前 main 上线前端 = 走降级原展示,视觉无变化,待后端 2a001855c 合并后需一并上线复验日历渲染

## 复现
- 语法:node --check /private/tmp/wt-ice-sentiment-front/static-site/app.js
- 降级数据现状:python3 -c "import json;d=json.load(open('/Users/linhuichen/code/trade/static-site/data/overview.json'));print('sentiment_calendar' in d, len(d.get('recent_freeze') or []))" → False, 29
- 同源抽查:对比 static-site/data/sentiment-all.json 与 sentiment-6m.json 的 signals keys 与最近信号
