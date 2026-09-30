# 抖音「万手哥」罗盘调研 + 模拟算法草案

> 调研日期:2026-09-30 | researcher 只读调研,未改任何业务代码、未跑 export/deploy
> 结论一句话:**「罗盘」在公开文字内容中零记录**——多通道穷举后确认它是抖音视频内口头/画面概念,没有任何平台文字转载;账号已甄别为**「万手哥投资圈」**(抖音财经自媒体,71.3 万粉,内容以股票知识/短线实盘为主)。我方 `a_sentiment`/`fear_greed` 已经是同形态的 0-100 综合情绪数值,「罗盘」即便拿到原文,大概率与恐贪/情绪分**同源**,增量在展示形态(仪表盘 UI)与盘中实时方向预测,不在算法本体。

---

## 半 1:「罗盘」多通道调研

### 1.1 账号甄别(结论 + 依据)

「万手哥」是常见昵称,甄别出 4 个不同实体,用户所指应为 **①**：

| 实体 | 依据 | 与用户描述关系 |
|---|---|---|
| **① 抖音「万手哥投资圈」** | 快懂百科【原文直引+URL】:baike.com/wiki/万手哥投资圈/7399278429709828115 ——"财经自媒体创作者,截止2024年8月5日,万手哥在平台发布作品73个,作品内容以分享股票知识为主,粉丝量71.3万,获赞354.2万"、"2023年3月26日,万手哥首次在抖音平台发布作品《你只要弄清楚最简单的2点就能判断一个题材有没有持续性》" | **最可能是用户所指**(抖音财经+分享方法论) |
| ② 打板文化术语「万手哥」 | 头条/东财股吧多处:【转述+URL】"经常打板的都知道股市里有'万手哥',经常出没在热门强势股里面,玩的就是气势和情绪"(和讯网问答)、"万手哥:唯一做到开盘3分钟内预测全日升跌"——指一次挂 1 万手大单的游资 | 非账号,是术语 |
| ③ B站「天机阁万手哥」 | B站 API:BV1DU4y1b7VE(2021-04-27,owner=天机阁万手哥) | B站账号,非抖音 |
| ④ 微博「万手波」 | 360 搜索命中 "#万手哥 #牛市来了" 微博原文 | 同名昵称变体 |

### 1.2 通道可达性表

| # | 通道 | 结果 | 备注 |
|---|---|---|---|
| A | WebSearch(内置工具,4 轮) | **全空** | 美国源,中文长尾词覆盖率差 |
| B | cn.bing.com `万手哥 罗盘 指标` | HTTP 200,命中全是「万」字字典释义 | 无关 |
| C | cn.bing.com `情绪罗盘 股市 指标 0-100` | HTTP 200,命中全是心理学「情绪罗盘」 | 无关 |
| D | baidu.com/s | HTTP 302 → 图形验证码页 | 反爬 |
| E | weixin.sogou.com type=1/type=2(两轮) | HTTP 200,搜索页存在但**0 篇文章条目** | 无收录或反爬 |
| F | so.com(360,3 轮) | ①「万手哥指标公式」系列=通达信公式 SEO 站(操盘罗盘/天机罗盘/多空罗盘等公式名);②头条文章标题「万手哥:唯一做到开盘3分钟内预测全日升跌 集合竞价」 | 公式站与抖音账号无关;①②聚焦「万手哥=预测全日升跌的集合竞价方法论」 |
| G | so.toutiao.com(头条,6 轮) | ①多次命中「万手哥」微头条/视频(游资术语+博主内容);②命中快懂百科「万手哥投资圈」;③**无任何「罗盘」命中** | 头条是抖音系,若罗盘有文字转载应在此出现——没有 |
| H | douyin.com/search(PC 壳) | HTTP 200 但 0 关键词,72KB 反爬壳 | 需登录/JS |
| I | douyin aweme/v1/web/search/item API | `{"search_nil_type":"params_check","search_nil_item":"invalid_app"}` | 需完整签名 |
| J | iesdouyin.com/web/api/v2 | `{"status_code":1,"status_msg":"Url doesn't match"}` | 接口已废弃 |
| K | m.douyin.com/search | HTTP 404 | 无此路由 |
| L | bilibili 搜索+view API | 「万手哥」相关视频 6 条(BV1xM411B7yr 等),UP 为交易员小郑/干了这杯果粒橙等;**无任何视频标题/描述含「罗盘数值」**;首屏混入大量风水罗盘视频 | 富媒体无罗盘 |
| M | xueqiu.com 搜索 API | HTTP 200 但返回非 JSON(登录墙) | 需登录 |
| N | zhihu.com api/v4/search_v3 | HTTP 400 | 需登录 |
| O | m.weibo.cn 搜索 | HTTP 302 | 需登录 |
| P | xiaohongshu.com/search_result | HTTP 301 | 跳登录 |
| Q | taoguba.com.cn 搜索 | HTTP 301 | 迁移 |
| R | so.eastmoney.com 搜索 | HTTP 200 但 JS 壳,0 关键词 | 需渲染 |
| S | quark.sm.cn(夸克) | 命中推荐词全是「八宝罗盘/抖音罗盘入口/平头哥罗盘」 | 风水类,无关 |
| T | juejin.cn/user/870468941256584 | HTML 空壳 + API 报「请求路由不存在」 | 掘金同名用户,无内容可读 |
| U | baike.com「万手哥投资圈」【唯一原文】 | HTTP 200,账号简介全文见 1.1 | **无「罗盘」字样** |
| V | YouTube | 网络失败(000) | - |

### 1.3 「罗盘」原文情况(诚实标注,分强弱)

- 【原文直引】**没有任何一条**。「罗盘」未在任何被索引的文字内容中出现。
- 【他人转述】**没有任何一条** 与「罗盘」数值定义相关的转述。
- 【我方推断,无原文】以下为此判断的证据链:
  1. 万手哥内容特征 = 分享股票知识/方法(百科)+ 头条同标题内容「万手哥:唯一做到开盘3分钟内预测全日升跌 集合竞价,今日买入,今日封涨停」(360 搜索命中的头条文章标题,未读到正文,文章页反爬)→ 他的方法论核心是**当日盘中方向判断**;
  2. 用户描述「罗盘是一个数值」+ 想融入 A股情绪/信号体系 → 该数值最可能是**市场情绪/多空强度的 0-100 或正负号数值**,用于判断当日情绪冷暖/方向;
  3. 「罗盘」大概率是他视频里展示的**仪表盘/圆形刻度 UI** 的名称(形似罗盘),数值即仪表盘指针读数。

---

## 半 2:映射我方数据源 → 算法草案

### 2.1 我方现有可直接用的数据(全部已生产,代码锚点)

**score_daily 情绪体系**(sentiment.db,源头 `app/compute/`):

| score_id | 定义 | 锚点 |
|---|---|---|
| a_sentiment | 6 分项加权 0-100:ratio(涨跌家数比 25%)+ zt(涨停数 20%)+ zhaban(炸板率 15%,反向)+ lianban(最高连板 15%)+ amount(成交额 10%)+ north(北向 15%),每项 120 日滚动百分位,缺项按可用重归一化;<20 冰点 / >80 过热 | sentiment.py:11-18, 47-64;normalize.py:9-10, 102-117 |
| sentiment_sz50/hs300/csi500/csi1000/cyb/kc50 | 各宽基情绪:RSI14 + 量偏离 + 涨跌幅(+QVIX)滚动百分位等权 | sentiment.py:67-118 |
| cross_market | 跨市场综合情绪(a_width + a_fund + a_sentiment + hk + global) | cross.py |
| fear_greed | 恐贪指数 = 上方 8 个情绪分**等权平均** 0-100,≥4 项可用才出分;标签 0-25 极度恐惧/25-40 恐惧/40-60 中性/60-75 贪婪/75-100 极度贪婪 | fear_greed.py:24-55 |
| signals | a_sentiment 等已有买卖点信号(卖=20 日高回落 5%+MA60 趋势过滤) | signals.py |

**daily_metric 原始指标(205 个,覆盖「罗盘」可能的全部输入)**:
- 涨跌家数族:`a_width_up_count / a_width_down_count / a_width_dt_count / a_width_zt_count / a_width_zhaban_rate / a_width_fengban_rate / a_width_seal_rate / a_width_max_lianban / a_width_zb_count / a_width_daban_premium`
- 成交额族:`a_amount / a_amount_ma20 / a_turnover_rate / a_turnover_gt5_pct / a_volume_ratio / a_amount_forecast(当日预估成交额!)`
- 资金族:`a_fund_margin(两融) / a_fund_north(北向,2024-08 起冻结缺项) / hk_south`
- 波动族:`a_qvix_300 / a_qvix_1000 / a_ad_line`
- 全球族:`us_futures_* (8 大指数期货 chg/price/signal) / gold / brent / oil / us10y / usdcnh`
- 盘中实时能力:`app/collector/intraday_snapshot.py`(实时 open/price/amount,27 次/日快照)+ `a_amount_forecast`(当日成交额预估)

### 2.2 算法草案(全部【我方推断】,非万手哥原文)

**草案 A:「罗盘」≈ 0-100 情绪综合值(最可能的形态)**
- 直接映射:**`罗盘值 = fear_greed`(8 分项等权平均)** 或 `a_sentiment`(6 分项加权)——两者都是「单一数值、0-100」,与用户描述同构。
- 若要求与现有指标**有差异**才值得做:给出「罗盘专用口径」= 从 daily_metric 重算一版**短线情绪取向**的组合:
  `罗盘值 = 100 × mean( 滚动分位(zt), 滚动分位(lianban), 100-滚动分位(zhaban_rate), 滚动分位(up/(up+down)), 滚动分位(seal_rate), 滚动分位(fengban_premium) )`
  - 阈值:`<20 冰点(宜低吸) / >80 过热(忌追高)`,与现有冰点口径一致避用户困惑
  - 与 a_sentiment 的差别:剔除 amount/north(长线资金项),聚焦**短线情绪 6 项**,等权不设主观权重
  - 直接可算:全部输入已在 daily_metric,口径对齐 `normalize.py:102 rolling_percentile(120)`

**草案 B:「罗盘」≈ 当日方向分(呼应「开盘3分钟内预测全日升跌」)**
- 用盘中可得数据,在 t 时刻(如 10:00)生成 0-100 方向分:
  输入(全部 t 时刻已可得,无前视):`a_amount_forecast/昨日 amount`(量能)、开盘后涨停/跌停家数、指数现价 vs 昨收、A50/全球期货信号(us_futures_*)
  `方向分 = 50 + Σ 每项(信号方向 × 权重)`(每项 ±25,共 4 项 → 0-100)
- 数据缺口:开盘涨停家数需实时采集(现有宽度族为盘后口径),盘中快照 infra 已就位(`intraday_snapshot.py`),需扩展采集涨停快照
- 防前视:t 时刻判定只用 t 之前数据(开盘集合竞价结果、昨日盘后情绪分),信号 t+1 才生效

**草案 C:直接改造展示形态(0 算法改动)**
- 我方已有单一数值(恐贪/情绪分),若用户喜欢的是「罗盘/仪表盘」形态 → 只做**前端 UI**(圆形刻度盘可视化 score_daily 里任一 score_id),不改任何算法。这是成本最低、最贴合「一个数值」体验的路径。

### 2.3 防前视保证(§5.1⑥,针对草案 B 型择时信号)

1. **分位阈值**:草案 A 全部复用 `rolling_percentile(120)` 滚动窗口(`normalize.py:102`,非全期分位)——已有的固化口径,天然防前视;
2. **时点硬约束**:盘中方向分 t 时点只用 t 前数据(集合竞价/昨日收盘/全球期货信号),t 收盘出信号 t+1 生效;
3. **穿越测试**:若实施草案 B,上线前必须做截断重算逐位一致测试(§5.1⑥ 机检 3)。

### 2.4 数据缺口与增量价值判断(诚实)

| 项 | 结论 |
|---|---|
| 与现有指标同源性 | **高度同源**。若「罗盘」= 0-100 情绪数值,它和我方 fear_greed(恐贪)/a_sentiment(情绪分)是同一类东西;拿不到原文前,不存在「我方没有、罗盘有」的算法价值 |
| 潜在增量 1 | **盘中实时方向**(「开盘3分钟预测」):我方情绪分为盘后口径,盘中只有快照行情,没有「开盘情绪综合值」——这是唯一可能与罗盘产生实质差别的点 |
| 潜在增量 2 | **展示形态**(仪表盘):零算法成本,只改 UI |
| 数据缺口 | ①「罗盘」原文定义(无)②快手宽度族盘中快照(涨停/炸板盘中实时计数)③万手哥视频画面(无法从文字渠道获取) |

---

## 半 3:找不到就如实说 + 建议

- **实际状态**:「罗盘」的定义、取值范围、计算输入、公式、用法,**全部无公开文字来源**;以上算法草案均为【我方推断】,不是「万手哥说过」。
- **用户提供以下任一即可继续**:
  1. 抖音视频链接/分享短链(v.douyin.com/xxx,或 万手哥投资圈 主页链接)→ 我可尝试解析页面元数据/文案;
  2. 「罗盘」出现的那条视频的**截图**(数值/仪表盘 UI/配文);
  3. 视频里念出的**台词回忆**(哪怕大意:「罗盘 80 以上代表什么」之类的关键句);
  4. 万手哥抖音号完整 ID(如 `万手哥投资圈` 的 `sec_uid`,可从分享链接获得)。

---

## 复现段

本报告不涉回测数字,复现对象 = 「通道穷举」与「我方数据摸底」:

```bash
# 1. 通道:各搜索 URL 原文见 1.2 表;关键证据文件已留存本地
ls -la /tmp/luopan_*.html /tmp/luopan_*.json 2>/dev/null
# 2. 账号甄别(百科原文)
curl -sL -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125.0.0.0" \
  "https://www.baike.com/wikiid/7399278429709828115" | grep -o "万手哥投资圈" | head -2
# 3. 我方数据摸底
sqlite3 /Users/linhuichen/code/trade/data/sentiment.db \
  "SELECT date,value,is_freeze FROM score_daily WHERE score_id='a_sentiment' ORDER BY date DESC LIMIT 3;"
sqlite3 /Users/linhuichen/code/trade/data/sentiment.db \
  "SELECT date,value FROM score_daily WHERE score_id='fear_greed' ORDER BY date DESC LIMIT 3;"
# 4. 口径复现(滚动百分位定义)
grep -n "_WINDOW\|rolling_percentile" /Users/linhuichen/code/trade/app/compute/normalize.py | head -5
```

> 修复链说明:无(本报告无假数字;所有「罗盘」相关内容均标注【我方推断】,无一写成"万手哥说过")。
