# 情绪分买卖点信号 × 近期冰点日 合并展示调研(2026-08-19)

> 只读调研产物。用户需求:把「市场温度·情绪分买卖点信号」补进首页「近期冰点日(近120日)」表格内部(非旁置独立区块),按日期分类展示(每行日期,标该日是冰点/情绪买点/卖点),配合看更直观。
> 主控澄清:用户反馈两个入口点开是同一图表/pin,期望 = 首页一个表格把冰点日+情绪信号合并按日期分类。

## 1. 两处现状

### 1.1 「情绪分买卖点信号 · 近 12 日」(市场温度 tab)
- **前端**:`static-site/app.js` L18347-18397 `renderSentimentSignalList(host, r, snap)`,唯一调用点 L18028(`renderSentimentMarketTemp` 市场温度 subtab)。标题 L18367 `🧭 情绪分买卖点信号 · 近 ${recentDates.length} 日`(当前 12 日 = 近 3 月内有信号的日期数)。
- **展示**:按日期降序,每日一行,组内 buy>buy_aux>sell 排序;每条 = 信号标签(红=卖/紫=辅买/绿=买)+ 情绪分名称。点击弹窗 `openSignalChartModal`。
- **数据源**:`static-site/data/sentiment-{3m}.json` `r.signals` = `{score_id: [{date, index_id, signal, reason}]}`,9 类情绪分(`a_sentiment/cross_market/sentiment_sz50/hs300/csi500/csi1000/cyb/kc50/fear_greed`),index_id 带 `s.` 前缀。
- **后端**:`app/queries.py` L1656 `sentiment()` L1669-1679 组 signals ← `signal_daily` 表 `s.%` 记录;信号算法 `app/compute/signals.py`(买 buy=RSI(14)上穿30、辅买 buy_aux=BB下轨回归、卖 sell=20日高回落5%),signal_daily 由 signals.py L1449 DELETE+INSERT 全量重建。
- **口径一句话**:情绪分买卖点 = 情绪分指数自身曲线的技术事件化(超卖反弹/高位回落),与冰点无直接因果。

### 1.2 「近期冰点日(近 120 日)」(首页右列)
- **前端**:`static-site/app.js` L11820-11836 首页右列 colA2。L11823 `_renderSignalGrid(r.recent_freeze, r.date, "近期冰点日(近120日)", "freeze", "无近期冰点日")`。freeze cell 渲染 L2874:`data-idx="s.${score_id}" data-sig="freeze" data-val=value`,显示 `<指数名>=<值>`。
- **数据源**:`overview.json` `recent_freeze` = `[{date, score_id, value}]`,近 120 日 is_freeze=1 的日期,**最多 9 个日期**(LIMIT 9),每日期多条。
- **后端**:`app/queries.py` L1219-1230:`score_daily WHERE is_freeze=1 AND date >= score_date-120 天, DISTINCT date ORDER BY date DESC LIMIT 9`。
- **判定**:`score_daily.is_freeze=1`,**两类口径混标**:
  - 情绪分值 < 20:`app/compute/sentiment.py` L134 `int(val<20)`、`cross.py` L89 `int(v<20)`、`fear_greed.py` 同。
  - `low_alert > 75`(低位机会分高,≠<20):`app/collector/intraday_snapshot.py` L1808-1809。recent_freeze 当前 29 条含 4 条 low_alert(value 76-77)。
- **口径一句话**:冰点日 = 任一情绪分指数 value<20(超卖极值)或 low_alert>75(低位机会显现)当天。

## 2. 弹窗同源核实(用户情报验证)

- **冰点入口**:freeze cell click(L11830-11835)→ `openSignalChartModal(data-idx=s.<score_id>, signal="freeze", date, val, "3m")` → s.* 分支(L6108-6121):`fetchJSON(sentiment-all.json)`,`chartData=r[key]`(key=score_id),`sigs=r.signals[key]`;isFreeze 追加 L6144-6148:`sigs + chartData.filter(value<=20).map({signal:"freeze"})` 蓝色冰点标注。
- **情绪信号入口**:renderSentimentSignalList click(L18391-18396)→ `openSignalChartModal(data-idx=s.<index_id 已带 s.>, signal, date, undefined, "3m")` → 同一 s.* 分支:`sentiment-all.json` 同一 score_id 走势 + `r.signals[key]` 同一批 pin。
- **结论:两入口点开是同一底层图(同一 score_id 的 sentiment-all.json 走势)+ 同一批 pin(signals[key])。唯一区别:冰点入口多追加 ≤20 冰点蓝色标注。**用户观察完全正确。
- **现存坑**:recent_freeze 含 low_alert 记录,freeze cell `data-idx="s.low_alert"`,但 `sentiment-all.json` 无 low_alert key → 点 low_alert 弹窗显示「暂无数据」。合并方案需一并处理。

## 3. 同源可比性(核心)

- **同源**:两处都基于同一批 9 个情绪分指数(score_daily 存分值+is_freeze, signal_daily 存 s.* 信号),同一 DB `data/sentiment.db`,同一日期键 `date`(YYYYMMDD)。
- **不同判定**:冰点=分值阈值(<20 或 low_alert>75);信号=RSI/布林/20日高回落事件化。两套独立判定、无因果依赖。
- **按日期对齐:技术上可(同 date 键),但数据现实需注意**:
  - 近120日 17 个冰点日中,仅 2 天(20260708/20260623)恰好有当日情绪信号;
  - **用户实际看到的 overview 9 个冰点日(20260715~20260803)当天 9/9 无信号**;
  - 冰点日前后 8 交易日内也无情绪买点确认(9/9 无)。
  - 近90日(对齐情绪信号区块口径)合并日历 = 27 天:15 纯冰点日 + 10 纯信号日 + 2 冰点∩信号同日。
- **结论**:「在现有 9 个冰点日行内加当日信号列」= 9/9 全"无",无信息量不可行。**必须把日期范围扩到近90日(或120日)合并成"情绪日历"才有内容**(27 天样例见 §5)。

## 4. 展示形态 schema 提案(推荐:合并「近90日情绪日历」)

| 日期 | 冰点(该日冰点情绪分,可多个) | 情绪分信号(该日买卖点,可多个) |
|---|---|---|
| 20260818 | — | 恐贪:卖;沪深300:卖;科创50:卖;创业板:卖;中证500:卖;中证1000:卖 |
| 20260803 | 低位机会=77.5;科创50=16.1 | — |
| 20260730 | 低位机会=76.3;科创50=14.2;创业板=18.8;中证500=18.0;中证1000=18.8 | — |
| 20260717 | 中证1000=7.9;中证500=13.0;创业板=13.4;沪深300=10.4;科创50=15.8;上证50=18.3 | — |
| 20260708 | 中证1000=15.3 | 跨市场:辅买(buy_aux) |
| 20260701 | — | 中证500:卖 |
| 20260623 | 沪深300=18.1 | A股综合:卖 |
| 20260601 | — | 中证1000:辅买(buy_aux) |

- **范围**:近90日(对齐情绪信号区块口径,有内容的日期约 27 天;也可近120日约 32 天)。数据字段全现成(score_daily is_freeze + signal_daily s.* 按 date join),无需新算。
- **同日双标注**:20260708/20260623 两类并存(冰点列 + 信号列同时有值)。
- **交互**:每格点击复用 `openSignalChartModal`(同一批 pin);low_alert 格特殊处理(无走势数据,改文本展示"低位机会分=77.5"或点击时说明无走势)。
- **实现路径**:① 后端 overview.json 或新 endpoint 注入按日期的合并数组(date → {freeze:[{score_id,value}], signals:[{index_id,signal}]});② 前端 `_renderSignalGrid` 新增 kind="freeze_signal"(或独立渲染),复用 freeze/signal 两分支 cell 渲染;③ low_alert 过滤或降级展示。

### 备选形态(不推荐,数据现实不支持)
- 保留 9 冰点日 + 每行加"当日信号"列 → 9/9 无,不可行。
- 9 冰点日 + 每行加"冰点后 N 交易日买点确认" → 9/9 无(后 8 交易日内无 buy/buy_aux),不可行。

## 5. 影响面(§23.3 举一反三)

- `_renderSignalGrid` 共享渲染,调用点:app.js L11823(freeze 冰点卡)/ L11841(signal 技术信号卡)/ L3063(signal 重绘)。改 freeze 分支(排序 L2701-2702、cell L2874)只影响冰点卡;signal 分支不受影响。lab.js 无调用。
- `openSignalChartModal` 共享弹窗,被首页信号卡/冰点卡/情绪信号列表/市场温度复用。改冰点弹窗(追加 freezePts)会影响所有 isFreeze 调用。
- `sentiment-{3m,6m,1y,3y,5y,all}.json` 被市场温度 tab 全部图 + 弹窗 s.* 分支 + 冰点弹窗共用;新增合并字段不影响存量消费(前端按需读)。
- `recent_freeze` 的 low_alert 弹窗「暂无数据」是现存展示坑(非本任务引入),合并方案应一并治理。
- 首页「近期技术分析参考点」信号卡是独立数据(signals_today, 非 s.*),与本次合并无关,不受影响。

## 复现

- 数据:`data/sentiment.db`(score_daily + signal_daily)+ `static-site/data/overview.json`(recent_freeze)+ `static-site/data/sentiment-3m.json`(signals)。
- 复现命令(近90日合并日历,截至 2026-08-19):
  ```bash
  python3 -c "
  import sqlite3
  conn = sqlite3.connect('/Users/linhuichen/code/trade/data/sentiment.db')
  START='20260521'
  freeze = conn.execute(\"SELECT date,score_id,value FROM score_daily WHERE is_freeze=1 AND date>=?\", (START,)).fetchall()
  sigs = conn.execute(\"SELECT date,index_id,signal FROM signal_daily WHERE index_id LIKE 's.%' AND date>=?\", (START,)).fetchall()
  ...  # 按 date 分组 join, 见调研报告 §3/§4
  "
  ```
- 关键口径:冰点 is_freeze=1(情绪分<20 或 low_alert>75);情绪信号 s.* 前缀(signal_daily);日期键 date=YYYYMMDD。
- 数据截止:2026-08-19 收盘(sentiment.db 20:17 / overview 20:12)。
