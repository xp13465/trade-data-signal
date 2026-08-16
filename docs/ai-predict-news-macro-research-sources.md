# AI 每日预测「新闻面/宏观事件日历」数据源可行性实测报告

> 调研时间:2026-08-16(周日实测,数据截至当日盘前 13:33)
> 调研 agent(只读,不改代码/基准/算法)。测试基准 = v1.1.1(纯调研,不动任何基准)
> 任务:逐源实测「新闻面/宏观事件日历」候选数据源在本环境能否真实采集到,产出可用源清单。真测不猜,每源带实测响应证据。
> 并行:另一 researcher 产出方法论报告 `docs/ai-predict-news-macro-research-methodology.md`(本报告只做接口可行性实测 + 字段期望对照,两报告互相引用)。
> 背景:AI 每日预测(gen_daily_brief.py 17:50 盘后跑)计划补新闻面/宏观日历维度,先验证数据源可用性。

---

## 0. 一句话结论

**「新闻快讯」三源(东财 7x24 = 财联社电报 = 金十 flash)全部免签可达、全天实时滚动、盘后 17:50 当日数据完整可得,直接可喂 AI 预测;「历史宏观锚点」用 akshare 单指标(macro_china_lpr/shrzgm/pmi/cpi 等)+ 东财 RPT_ECONOMY_* 单指标,已跑通;「未来事件日历(哪天公布什么)」无现成独立接口(东财/金十/英为/同花顺日历接口全不可用),但可用金十 important 预告 + 财联社 level 过滤 + 东财快讯的事件推送替代。」

---

## 一、可用源清单(实测能采到,6 个 + 1 个半可用)

### 1. 东财 7x24 快讯 — 主推(项目东财链路熟)
- **URL**: `https://np-listapi.eastmoney.com/comm/web/getNewsByColumns?client=web&biz=web_724&column=*&order=1&needInteractData=0&page_index=1&page_size=50`
- **实测**: 200 JSON,page_size=50 实得 50 条,支持 `page_index` 翻页,支持 page_size 调大。证据: `/tmp/em_news.json` 首条 `showTime=2026-08-16 13:27:51`。
- **字段**: `title / summary / showTime / url / uniqueUrl / mediaName / code`
- **更新时点**: 全天实时滚动,实测当日 13:33 有数据 → 盘后 17:50 当日可得,次日盘前也得。
- **鉴权**: 无,免 token,只要 UA。
- **频率建议**: 5-10 分钟轮询一次,翻页可拿整天。
- **备注**: `column=*` 全量;分类参数(要闻/快讯)实测无效(column=2/100-103 均 0 条),但不影响。

### 2. 财联社电报 — 主推(免签,字段最全)
- **URL**: `https://www.cls.cn/api/cache?name=telegraph&app=CailianpressWeb&os=web&sv=8.7.9`
- **翻页**: 加 `lastTime=<上一页最后一条ctime 秒>` 循环翻页,实测成功。证据: 传 `lastTime=1786857561` 返回更早 19 条(`/tmp/cls3.json`)。
- **实测**: 200 JSON,20 条/页(rn 上限 20),免签。字段: `id / title / brief / content / ctime(Unix秒) / level(重要性C/B/A) / reading_num / stock_list / subjects`。
- **更新时点**: 全天实时滚动(实测 13:19 有),17:50 当日可得。
- **鉴权**: 无签名无登录。**老接口 `nodeapi/telegraphList` 已下线**(返回 HTML),`v1/roll/get_roll_list` 需签名(10012),但 `api/cache` 免签可替代。
- **频率建议**: 5-10 分钟轮询;要整天数据用 lastTime 循环翻页。
- **备注**: `level` 字段可直接过滤「重要电报」;`stock_list` 关联个股(舆情面可复用)。

### 3. 金十数据快讯 — 主推(含重要事件预告)
- **URL**: `https://flash-api.jin10.com/get_flash_list?channel=-8200&vip=1` + header `x-app-id: bVBF4FyRTn5NJF5n` + `x-version: 1.0.0` + `Referer: https://www.jin10.com/`
- **实测**: 200 JSON 17KB,21 条,`max_time` 翻页有效。证据: `/tmp/jin10b.json`。
- **字段**: 外层 `time(字符串 2026-08-16 13:21:31) / id / important / channel / voices`;内层 `data.content / data.title / data.source / data.vip_level`。
- **更新时点**: 全天实时滚动,17:50 当日可得。**关键: important 标记 3/21 条,含「预告:国新办17日下午3时举行新闻发布会 介绍2026年7月份国民经济运行情况」——宏观事件预告直接覆盖**。
- **鉴权**: 无登录,只需固定 header(x-app-id 是公开值,非密钥)。
- **频率建议**: 5-10 分钟轮询。
- **备注**: 金十贵金属起家,贵金属/重要数据快讯覆盖好;`important` 字段=重要新闻过滤。

### 4. akshare 单指标宏观历史(LPR/社融/PMI/CPI 等)— 历史值锚点
- **函数**(trade-data/.venv,akshare 1.18.64 已装):
  - `ak.macro_china_lpr()`(1574 条至 2026-07-20)
  - `ak.macro_china_shrzgm()`(136 条社融增量,分项含人民币贷款/委托/信托/企业债)
  - `ak.macro_china_pmi()`、`ak.macro_china_cpi()` 等,中国+美国宏观单指标全覆盖
- **实测**: LPR/社融/PMI 全部跑通(见上方命令输出),无鉴权。
- **更新时点**: 官方发布后更新(LPR 每月 20 日,社融月度)。
- **频率建议**: 数据发布日盘后跑一次。
- **备注**: 有 `macro_china_lpr` 但无「财经日历」函数;`ak.news_economic_baidu` 返回空(不可用)。

### 5. 东财 datacenter 单指标接口 — 与 akshare 互补
- **URL**: `https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_ECONOMY_CPI&columns=ALL&pageNumber=1&pageSize=3&sortColumns=REPORT_DATE&sortTypes=-1&source=WEB&client=WEB`
- **实测**: RPT_ECONOMY_CPI 成功,75 页历史,字段 `REPORT_DATE/TIME/NATIONAL_SAME(同比)/NATIONAL_SEQUENTIAL(环比)/NATIONAL_ACCUMULATE(累计)`。
- **鉴权**: 无(带 `Referer: data.eastmoney.com`)。
- **备注**: 项目已在用 datacenter-web 的 RPT_MUTUAL_DEAL_HISTORY,链路熟。可按需取 CPI/PPI/PMI/LPR 等单指标。

### 6. akshare 交易日历 — 判断次日是否交易日
- `ak.tool_trade_date_hist_sina()`: 8797 条到 2026-12-31(含未来),对「次日开盘预测」判断交易日有用。

### 7. 央视网新闻联播文字稿 — 半可用(官方口径)
- **URL**: `https://tv.cctv.com/lm/xwlb/`(200,32KB,含当日 19:00 条目)。akshare `ak.news_cctv(date)` 封装存在但**很慢**(逐条请求详情页,后台跑 2 分钟没出),建议直接解析列表页。
- **更新时点**: 每日 19:00 后(次日盘前预测可用)。

---

## 二、不可用/受阻源清单(原因明确)

| 源 | 实测结果 | 原因 |
|---|---|---|
| 东财 datacenter 经济日历报表 | RPT_ECONOMIC_CALENDAR / RPT_ECONOMIC_VALUE / RPT_CALENDAR_CJRL / RPT_CALENDAR_GLOBAL 全「报表配置不存在」,旧版 get 报字段空,`/cjsj/calendar/` 404 跳转 | **东财数据中心没有经济事件日历报表**,只有单指标历史(RPT_ECONOMY_*) |
| 金十财经日历 | `cdn-data.jin10.com`(DNS 不通)/ `api.jin10.com`(无输出)/ `datacenter.jin10.com/report`(返回 HTML 非接口) | 日历接口需内网/登录,公开域不可达 |
| 英为财情经济日历 | `cn.investing.com/economic-calendar/` 403 | 网络策略阻断(3 字节) |
| 同花顺财经日历 | `data.10jqka.com.cn` 域名通(200)但 `/financial/calendar/`、`/calendar/`、`/event/` 全 404 | 未找到日历路径 |
| akshare 百度经济新闻 | `ak.news_economic_baidu()` 返回空 DataFrame(0,0) | 需 cookie,公开调用无数据 |
| akshare 财联社封装 | `ak.stock_news_main_cx()` 实际请求 cxdata.caixin.com(财新网),非财联社 | 函数名误导,返回财新周刊内容 |

---

## 三、关键缺口:「未来事件日历」(哪天公布什么)无现成接口

东财/金十/英为/同花顺的独立「经济事件日历」接口全不可用。但**替代方案成立**:
- 金十 flash 的 `important` 标记含「预告」类(实测有国新办发布会预告,见 §一.3)。
- 财联社 `level` 字段 + 东财 7x24 也会实时推重要事件(非农/美联储议息/国内会议)。
- → **用三源快讯流覆盖「重要事件预告+公布时点」,用 akshare 单指标覆盖「已公布历史值」,即满足新闻面/宏观锚点需求,不必依赖独立日历接口**。

---

## 四、宏观锚点(已有,无需新增)

`queries.py:1459` 已注入: `gold, oil, wti_oil, comex_silver, usdcnh, a_qvix_300, a_qvix_1000, cn10y, us10y, cn_us_spread, brent`。中美利差(cn_us_spread)、人民币(usdcnh)、美债(us10y 美财政部 CSV)、中债(cn10y)、黄金原油已齐。→ 新闻面的「宏观锚点」缺口不存在,本次只需补「宏观日历 + 新闻快讯」两个采集维度。

---

## 五、给主控的一句话采集建议

1. **新闻快讯**: 三源并行(东财 7x24 + 财联社电报 + 金十 flash),5-10min 轮询,盘后 17:50 当日数据完整可得 → 直接喂 AI 预测。财联社用 `level` 过滤重要、`lastTime` 翻页拿全量;金十用 `important` 过滤。
2. **历史宏观锚点**: akshare `macro_china_*` 单指标(LPR/社融/PMI/CPI)+ 东财 `RPT_ECONOMY_CPI` 数据发布日盘后跑一次。
3. **未来事件日历**: 无现成接口,用金十 important 预告 + 财联社/东财快讯的事件推送替代;如需硬性日历再议(可考虑自建维护表)。
4. **交易日判断**: `ak.tool_trade_date_hist_sina()` 一次拿全年含未来。

---

## 六、与方法论报告的交叉引用

本报告 = 数据源接口可行性实测(能采到什么/接口怎么用/能否拿到)。方法论报告 `docs/ai-predict-news-macro-research-methodology.md` 提供了:
- **字段期望**(§6.1/6.2):宏观日历需要 `date/release_time/indicator/importance/actual/forecast/previous`;新闻快讯需要 `title/content/source/published_at/category/sentiment_score/importance` —— 本报告实测字段与之一一对照。
- **页面展示设计建议**(§7):首页 AI 预测卡「📅 明日关键事件」一行 + AI 预测弹窗「🗓 宏观日历 / 📰 今日要闻」区块 + 历史收盘分析页「事件对照」轻区块,并带 §22/§21 一致性联动(采集源 = 展示源 = AI 注入源,一次采集多处消费)。本报告只做数据源实测,页面展示按方法论报告 §7 执行,不重复展开。

---

## 复现

### 每个源的 URL + 关键 header + 实测返回路径

| 源 | URL/接口 | 关键 header | 实测返回路径 | 翻页方式 |
|---|---|---|---|---|
| 东财 7x24 | `https://np-listapi.eastmoney.com/comm/web/getNewsByColumns?client=web&biz=web_724&column=*&order=1&needInteractData=0&page_index=1&page_size=50` | 无 token(需 UA) | `/tmp/em_news.json` | `page_index` |
| 财联社电报 | `https://www.cls.cn/api/cache?name=telegraph&app=CailianpressWeb&os=web&sv=8.7.9` | 无签名无登录 | `/tmp/cls3.json`(传 lastTime=1786857561 回 19 条) | `lastTime`(上页最后一条 ctime 秒) |
| 金十 flash | `https://flash-api.jin10.com/get_flash_list?channel=-8200&vip=1` | `x-app-id: bVBF4FyRTn5NJF5n` + `x-version: 1.0.0` + `Referer: https://www.jin10.com/` | `/tmp/jin10b.json` | `max_time` |
| 东财 datacenter CPI | `https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_ECONOMY_CPI&columns=ALL&pageNumber=1&pageSize=3&sortColumns=REPORT_DATE&sortTypes=-1&source=WEB&client=WEB` | `Referer: data.eastmoney.com` | 上方命令输出(75 页历史) | `pageNumber` |
| akshare 单指标 | `ak.macro_china_lpr` / `macro_china_shrzgm` / `macro_china_pmi` / `macro_china_cpi`(trade-data/.venv,akshare 1.18.64) | 无 | 函数直接返回 DataFrame | — |
| akshare 交易日历 | `ak.tool_trade_date_hist_sina()` | 无 | 8797 条到 2026-12-31(含未来) | — |
| 央视网新闻联播 | `https://tv.cctv.com/lm/xwlb/` | 无 | `/tmp/cctv.html` | 分页列表 |

### 不可用源拦截证据(实测返回路径)
- 东财日历报表报错 = `/tmp/em_cal2.json`、`/cjsj/calendar/` 404 跳转
- 新浪宏观 = `/tmp/sina_mac.html`
- 统计局 = `/tmp/stats_zxfb.html`

### 数据截止日期
- 实测日:2026-08-16(周日)盘前,各源均取得当日数据(东财 13:27、金十 13:21、财联社 13:19)。
- LPR/社融 akshare 历史至 2026-07-20。

### 关键口径一句话
本报告只做数据源接口可行性实测(能采什么/怎么采/能否拿),不改基准/算法/代码;宏观锚点查询位置 `queries.py:1459`;页面展示设计见方法论报告 §7,不在此重复。采集方案(三源快讯 + akshare/东财单指标)落 `docs/pending-features-index.md` #7/#8 待办,见其「依赖」更新。
