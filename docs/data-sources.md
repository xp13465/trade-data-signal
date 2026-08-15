# 数据源说明 · tdsignal

> 本文件列出 tdsignal 看板使用的所有数据源、各源覆盖的数据范围、更新频率、延迟说明。
>
> 采集器代码在 [`app/collector/`](../app/collector/)。指标配置在 [`config/indicators.yaml`](../config/indicators.yaml)（增删指标只改此文件，fetchers.py 按此调用）。
>
> 全部为**公开免费数据源，无 API key**。

---

## 数据源总览

| 源 | 协议 | 覆盖数据 | 更新频率 | 延迟 |
|---|---|---|---|---|
| [akshare](https://akshare.akshare.xyz/) | HTTP（Python 库封装多源） | A 股宽度 / 资金 / 指数 / 行业 / 龙虎榜 / 解禁 / IPO / 可转债 / 港股 / 全球 / 商品 / 债券 | T+0 盘后 | 当日 |
| mootdx（通达信） | TCP 7709 | 全 A 股日线 OHLC（10 年+） | T+0 盘后 | 当日 |
| BaoStock | HTTPS（baostock.com） | 全 A 股日线 OHLC（1990 起，含换手率） | T+1 | 次日 |
| HKEX 官方 | HTTPS JS 模板 | 北向资金成交总额 | T+0 | 当日 |
| HKEX CCASS | HTTPS ASP.NET | 北向持股季度快照 | 季度 | 季度末+20 天 |
| 东财直爬（em_get） | HTTP | 主力资金流 / 行业资金流 / 行业换手率 / 指数 | T+0 | 当日 |
| 同花顺（THS） | HTTP（akshare 封装） | 行业/概念板块指数 / 行业实时涨跌幅 | T+1 偶发 | 当日或次日 |
| 申万（swsresearch.com） | HTTPS | 申万一级 31 行业指数全历史 | T+1 偶发 | 当日或次日 |
| 中证指数公司（csindex） | HTTP | 中证红利 / 红利低波指数 | T+0 | 当日 |
| 新浪财经 | HTTP | A 股/港股/美股指数 / 商品期货 / 外盘期货 / 国债收益率 | T+0 | 当日 |
| 腾讯财经（qt.gtimg.cn） | HTTP（GBK） | 实时行情 / 换手率 / 北证50 兜底 | 实时 | 实时 |
| CFFEX（中金所） | HTTP（akshare 封装） | IF/IC/IH/IM 期货前 20 会员持仓 | T+0 盘后 | 当日 |
| cninfo（巨潮资讯） | HTTP / PDF | ETF 持有人结构（年报/半年报）/ IPO 数据 | 半年 | 滞后 2-3 月 |
| legulegu | HTTPS | 申万行业成分股映射（当前快照） | 不定期 | 当前 |

---

## 1. akshare（主力数据源）

[akshare](https://akshare.akshare.xyz/) 是开源 Python 财经数据库，封装了东财/新浪/腾讯/同花顺/申万/中证指数公司/CFFEX/cninfo 等多源接口。

**采集器**：[`app/collector/fetchers.py`](../app/collector/fetchers.py)

**调用方式**：按 [`config/indicators.yaml`](../config/indicators.yaml) 注册的 `func` 字段调用对应 akshare 函数。分 4 类：

1. **序列型**（`collect_series`）：一次拉全部历史，逐日入库（自动回填）。如 `stock_zh_a_spot`（A 股实时快照）、`stock_margin_sse`（沪市融资余额）、`stock_zt_pool_em`（涨停板池）等。
2. **快照型**（`collect_snapshot`）：只采当日值。如 `stock_lhb_detail_em`（龙虎榜）、`stock_restricted_release_summary_em`（解禁）。
3. **直爬型**（`direct:xxx`）：akshare 部分函数被反爬封，走 [`app/collector/direct.py`](../app/collector/direct.py) 用 `em_get` 防封层直连东财接口。如 `direct:north_fund_total`（北向成交总额）、`direct:market_fund_flow`（主力净流入）。
4. **指数型**（`collect_index`）：拉指数 OHLC 历史。如 `stock_zh_index_daily`（新浪 A 股指数）、`stock_hk_index_daily_sina`（港股指数）、`index_us_stock_sina`（美股指数）、`index_hist_sw`（申万行业）、`stock_board_concept_index_ths`（同花顺概念）。

**覆盖指标**（详见 indicators.yaml）：
- A 股宽度：涨跌家数 / 涨停跌停 / 连板高度 / 炸板率 / 封板率 / 打板溢价（`stock_zh_a_spot` + `stock_zt_pool_*`）
- A 股资金：两融余额（`stock_margin_sse`）/ 主力净流入（`direct:market_fund_flow`）/ 北向成交总额（`direct:north_fund_total`）
- A 股情绪：QVIX（`index_option_300etf_qvix` / `index_option_50etf_qvix`）/ 成交额（`stock_zh_a_spot`）/ 股息率（`stock_a_gxl_lg`）
- 龙虎榜 / 解禁 / IPO / 可转债（`stock_lhb_*` / `stock_restricted_*` / `stock_ipo_summary_cninfo` / `bond_zh_cov*`）
- 全球商品：沪金 / INE 原油 / WTI / COMEX 白银 / 布伦特（`futures_main_sina` / `futures_foreign_hist`）
- 汇率/债券：离岸人民币（`currency_boc_sina`）/ 中美国债收益率（`bond_china_yield` / `bond_zh_us_rate`）

---

## 2. mootdx（通达信 TCP 日线）

[ mootdx](https://github.com/mootdx/mootdx) 通过通达信 TCP 7709 协议拉全 A 股日线，**不走 HTTP 不被东财 IP 封锁**。

**采集器**：[`app/collector/mootdx_daily.py`](../app/collector/mootdx_daily.py)

**用途**：
- 全 A 股日线 OHLC + 成交额（10 年+ 历史，5200 只串行约 10 分钟）
- 存 `data/stock_daily.db` 的 `mootdx_daily_raw` 表
- [`app/collector/width_history.py`](../app/collector/width_history.py) 从它聚合算 10 年历史宽度（涨跌家数/涨停跌停/炸板数/封板率/成交额）
- [`app/collector/industry_width.py`](../app/collector/industry_width.py) 从它算 31 行业内宽度
- ETF OHLC（[`app/collector/etf_national_team.py`](../app/collector/etf_national_team.py) 用其拉 ETF 行情替代东财 push2his）

**字段**：`code/date/open/high/low/close/volume/amount/pct_change`（自算）/`turnover`（留 NULL，由 BaoStock 补）。**无 ST 标记**，故 ST 5% 涨跌停规则不单独处理（误差说明在 REQUIREMENTS.md）。**不覆盖北交所**（430/830/920）。

**单次硬上限**：800 行/页，循环 start=0→800→1600 拉全历史。不复权（与 D1 akshare `adjust=""` 一致）。

**fallback**：mootdx 通达信行情接口全 empty 停服时（2026-07-17+ 曾回归，80 节点 0 可用），自动切 BaoStock 采剩余 code。

---

## 3. BaoStock（封锁期替代源）

[BaoStock](http://baostock.com) 走自己服务（baostock.com），不受东财封锁影响。

**采集器**：[`app/collector/baostock_daily.py`](../app/collector/baostock_daily.py) + [`baostock_parallel.py`](../app/collector/baostock_parallel.py) + [`baostock_worker.py`](../app/collector/baostock_worker.py)

**用途**：
- 全 A 股日线（1990-2026 全段，作 D1 封锁期替代主力源）
- 含 `turnover`（换手率），补 mootdx 无换手率字段
- [`app/collector/cleanup_d3d2.py`](../app/collector/cleanup_d3d2.py) 从 `baostock_daily_raw.turnover` 按日聚合算全市场换手率分布（均值/中位数/p90/p10/>5%占比），回填 2016-2026 ~2550 日

**限制**：
- 单连接串行（login 后用同一连接），加 0.3s 节流 + 0.1s jitter 防服务端风控
- 不支持北交所（920xxx / 8xxxxx / 4xxxxx），跳过并记 `data/baostock_skipped_bj.txt`
- 不返振幅/涨跌额，故缺 amplitude/pct_amt

**并发**：[`baostock_parallel.py`](../app/collector/baostock_parallel.py) 起多个独立子进程，每个子进程处理一段 code 列表（baostock 单连接不支持并发，多进程绕开）。

---

## 4. HKEX 官方（北向资金成交总额）

香港交易所官方每日统计 JS 模板。

**采集器**：[`app/collector/direct.py`](../app/collector/direct.py) 的 `fetch_north_fund_total` / `fetch_north_fund_hkex`

**URL**：`https://www.hkex.com.hk/eng/csm/DailyStat/data_tab_daily_{date}e.js`
**Referer**：`https://www.hkex.com.hk/Mutual-Market/Stock-Connect/Statistics/Historical-Daily`

**返回**：`tabData = [...]` JSON 数组，含 SSE/SZSE Northbound/Southbound 4 条记录。

**为何用 HKEX 官方源**：2024-08 港交所新规取消盘中净买额披露后，东财 `NET_DEAL_AMT`（净买额）全 null 停更。改用 `DEAL_AMT`（成交总额=买+卖），语义从「净流入方向」变「市场活跃度」。HKEX 官方源权威且反爬风险低，作为主源；东财 datacenter RPT_MUTUAL_DEAL_HISTORY 全量历史作 fallback 1，东财 kamt/get 当日作 fallback 2。

**指标**：`a_fund_north`（北向资金成交总额，亿元）

---

## 5. HKEX CCASS（北向季度净买额反算）

[HKEX CCASS](https://www3.hkexnews.hk/sdw/search/mutualmarket.aspx) 北向持股查询页（ASP.NET WebForm POST）。

**采集器**：[`app/collector/hkex_ccass_quarterly.py`](../app/collector/hkex_ccass_quarterly.py)

**背景**：2024-08 港交所新规后，北向持股明细改**季度披露**，CCASS mutualmarket.aspx 只返回"上季度末"快照。无法日频反算，但可拿连续两个季度末快照反算季度净买额。

**反算公式**：`季度净买额 = sum( (Q_curr持股 - Q_prev持股) × Q_curr收盘价 )`
- 持股差 = Q_curr - Q_prev（股数，正=净买入）
- 收盘价用 Q_curr（最近季度末）A 股收盘价，从 baostock `query_history_k_data_plus` 逐只拿
- 单位：股数 × 元 = 元，/1e8 = 亿元

**发布规则**：季度末后约 15 天 CCASS 才发布数据（实测 6/30 数据 7/15 发布），故"已发布"= 季度末 + 20 天 < 今天。

**合理性校验**：北向单季净买入历史范围约 -2000~+3000 亿（极端行情可超），异常值报错跳过。覆盖率 < 50% 或异常值（万亿级）跳过。

**指标**：`a_fund_north_quarterly`（北向资金季度净买额，亿元）

---

## 6. 东财直爬（em_get 防封层）

akshare 部分函数被东财反爬封（如 `stock_market_fund_flow` 主力资金流），走 [`app/collector/direct.py`](../app/collector/direct.py) 的 `em_get` 防封层直连。

**em_get 特性**（[`app/collector/base.py`](../app/collector/base.py)）：
- 全局关闭 `trust_env`（绕 Clash 代理直连东财，避免代理把东财流量走境外被东财封 IP）
- UA 伪装 + 限频 + 重试

**覆盖**：
- 主力净流入（`push2his.eastmoney.com/api/qt/stock/fflow/daykline/get`）：三源兜底，主源封禁时走 `push2.eastmoney.com/api/qt/clist/get`（个股排名接口聚合）
- 行业资金流 + 换手率（[`app/collector/industry_extras.py`](../app/collector/industry_extras.py)）：`push2his.eastmoney.com` 的 fflow daykline + kline 端点（非 clist，未被反爬封）。申万一级 801xxx → 东财 BKxxxx 映射通过 clist `m:90 t:2` 按名称匹配
- 北向资金（HKEX 主源失败时 fallback 东财 datacenter RPT_MUTUAL_DEAL_HISTORY 全量历史 + kamt/get 当日）

**已知限制**：
- IP 风控可能联动（同 eastmoney.com，触发阈值后 push2his + push2 联动封）
- 第三源 push2/api/qt/clist/get 只能拿当日（排名是实时数据），无历史

---

## 7. 同花顺（THS）

akshare 封装的同花顺接口。

**采集器**：[`app/collector/fetchers.py`](../app/collector/fetchers.py) 的 `collect_index`（func=`index_hist_ths_concept` / `stock_board_concept_index_ths`）+ [`app/collector/intraday_snapshot.py`](../app/collector/intraday_snapshot.py)（实时行业涨跌幅）

**覆盖**：
- 27 个同花顺概念板块指数（`thsc_300816` 机器人概念 等，见 indicators.yaml）：`stock_board_concept_index_ths` 拉历史序列（T+1，次日才出当日点）+ `stock_board_concept_info_ths` 当日快照合成 OHLC 补采当日行
- 31 申万一级行业实时涨跌幅（盘中快照用）：`stock_board_industry_summary_ths`（90 子行业聚合到 31 一级，涨跌幅按成交额加权、净流入求和、领涨股取涨幅最高子行业）
- 申万一级 OHLC 兜底（[`app/collector/index_backfill.py`](../app/collector/index_backfill.py)）：申万 trend API SSL 故障时走同花顺聚合（90 子行业聚合 31 一级 + 锚定申万末日避免绝对值跳变）

---

## 8. 申万（swsresearch.com）

申万官方 trend API：`swsresearch.com`。

**采集器**：[`app/collector/fetchers.py`](../app/collector/fetchers.py) 的 `collect_index`（func=`index_hist_sw`）

**覆盖**：31 个申万一级行业指数全历史（1999 起），无 start/end 参数返全量。

**已知问题**：
- 本地 DNS 失败，[`app/collector/base.py`](../app/collector/base.py) 已 monkey-patch `socket.getaddrinfo` 走 8.8.8.8 解析的 IP
- T+1 发布延迟（周五数据可能要到周一才更新）
- 2026-07-13 起 trend API 持续 SSL 故障，已加同花顺聚合兜底（`SW_OHLC_SOURCE=="ths"` 时走同花顺；`=="sw"` 时走申万，恢复后回切）

**多源补采**：[`app/collector/index_backfill.py`](../app/collector/index_backfill.py) 在主源采完后校验 8 个核心 A 股指数今日数据是否到位，缺失则按 baostock → 腾讯 回退补采。避免单一数据源当日延迟导致首页"上证涨幅 0.00%"或恐贪卡片缺失。

---

## 9. 中证指数公司（csindex）

中证指数公司官网。

**采集器**：[`app/collector/fetchers.py`](../app/collector/fetchers.py) 的 `collect_index`（func=`stock_zh_index_hist_csindex`）

**覆盖**：中证红利（000922）/ 红利低波（930955）。新浪源 sh000922 数据停在 2019、930955 sina 无此代码，故走中证指数公司源。`start_date`/`end_date` 是服务端过滤参数，始终从 20100101 拉全量。

---

## 10. 新浪财经

**采集器**：[`app/collector/fetchers.py`](../app/collector/fetchers.py) 的 `collect_index` + [`app/collector/us_futures.py`](../app/collector/us_futures.py)

**覆盖**：
- A 股指数（func=`stock_zh_index_daily`，symbol=`sh000001` 等）：全覆盖，close/pct，快
- 港股指数（func=`stock_hk_index_daily_sina`，symbol=`HSI`/`HSTECH`/`HSCEI` + 8 港股板块）：返全量历史 7 列 `date/open/high/low/close/volume/amount`，大量采集会被封 IP（每只 sleep 3s）
- 美股指数（func=`index_us_stock_sina`，symbol=`.DJI`/`.IXIC`/`.INX`/`.NDX`）：返 2004 起 ~5600 行全量历史，`trust_env=False` 直连可访问无需代理
- 全球指数（func=`index_global_hist_sina`，日经/KOSPI/富时100/DAX/CAC40）
- 商品期货（func=`futures_main_sina` 沪金 AU0 / INE 原油 sc0 / 国债期货 T0；func=`futures_foreign_hist` WTI CL / COMEX 白银 SI / 布伦特 OIL）
- 汇率（func=`currency_boc_sina` 离岸人民币）
- 美股期货 ES/NQ（[`us_futures.py`](../app/collector/us_futures.py)，URL `http://hq.sinajs.cn/list=hf_ES,hf_NQ`，需 Referer `https://finance.sina.com.cn` 头，GBK 解码）：A 股收盘时美股未开盘，ES 期货（标普500）↔ 标普500 收盘相关性 ≈ 0.95，NQ（纳指100）↔ 纳指100 同理。CME GLOBEX 电子盘亚盘仍在交易，ES/NQ 实时价反映美股当晚预期方向

---

## 11. 腾讯财经（qt.gtimg.cn）

**采集器**：[`app/collector/tencent.py`](../app/collector/tencent.py) + [`app/collector/intraday_snapshot.py`](../app/collector/intraday_snapshot.py)

**URL**：`https://qt.gtimg.cn/q=` + 逗号分隔代码（如 `sh000001,sz399006`）

**特性**：不封 IP，GBK 编码，`~` 分隔 88 字段。

**覆盖**：
- 换手率（[`app/collector/fetchers.py`](../app/collector/fetchers.py) func=`tencent:index_turnover`）：mootdx 无换手率、sina 全 A 无换手率列，故用腾讯
- 盘中实时行情（[`intraday_snapshot.py`](../app/collector/intraday_snapshot.py)）：9 指数实时主源，新浪逐个降级备
- 北证50 兜底（[`index_backfill.py`](../app/collector/index_backfill.py)）：baostock 无北证50，腾讯 `bj899050` 补
- 国债指数（func=`stock_zh_index_daily_tx`，symbol=`sh000012`）

---

## 12. CFFEX（中金所）

中国金融期货交易所前 20 会员持仓排名数据。

**采集器**：[`app/collector/futures_position.py`](../app/collector/futures_position.py) + [`app/collector/fetchers.py`](../app/collector/fetchers.py) 的 `fetch_futures_position`

**接口**：akshare `get_cffex_rank_table(date=date, vars_list=['IF', 'IC', 'IH', 'IM'])`

**覆盖**：4 个股指期货品种（IF 沪深300 / IC 中证500 / IH 上证50 / IM 中证1000）前 20 会员净多空持仓，按品种汇总计算机构(前20) / 中信期货 / 国泰君安 三角色净持仓。

**用途**：
- 同向准确率（跟随机构）+ 逆向准确率（对冲思维）
- 30d/60d/120d 滚动窗口准确率时序

---

## 13. cninfo（巨潮资讯）

**采集器**：[`app/collector/etf_national_team.py`](../app/collector/etf_national_team.py) 的持有人拉取 + akshare `stock_ipo_summary_cninfo`

**覆盖**：
- ETF 持有人结构（年报/半年报 PDF §9.2 期末上市基金前十名持有人，用 pdfplumber 解析）：机构/散户/内部占比，半年一次，滞后 2-3 月
- IPO 数据（akshare `stock_ipo_summary_cninfo`）

**限制**：仅深市 5 只 ETF 有 cninfo orgId；沪市 7 只待补。持有人类型按名称关键词识别汇金/证金/社保/外管局。

---

## 14. legulegu（申万成分股映射）

**采集器**：[`app/collector/industry_width.py`](../app/collector/industry_width.py)

**URL**：`stockdata/index-composition?industryCode=801xxx.SI`（HTTPS，`trust_env=False` 全局已由 base.py patch）

**用途**：申万一级 31 行业指数的成分股列表（用于行业内宽度计算）。

**限制**：akshare `index_component_sw` 仅返"releasedetail"指数（如申万50 801001）成分，不含 31 个一级行业指数，故改用 legulegu。⚠ 返回**当前**成分股，非历史。申万 2021 修订为最近一次大改，2016-2021 段用当前成分算宽度存在偏差（已退市股不在当前列表 → 漏算；行业变更股按当前行业归属）。整体趋势仍可用，单日绝对值有 ~5-10% 偏差。

---

## 采集时点（launchd 8 个任务）

| 任务 | 时间（CST） | 说明 |
|---|---|---|
| `com.trade.sentiment` | 15:33 | 主调度（旧入口，已切 update_all） |
| `com.trade.update-all` | 17:50 | 主采集：4 条并行 pipeline（core/width/futures/stock_daily），约 31 分钟 |
| `com.trade.intraday-snapshot` | 09:35 起每 15 分钟（09:35/09:50/10:05/...） | 盘中实时快照 + 指数反哺 + 推 intraday_snapshot.json |
| `com.trade.futures-backfill` | 20:05, 21:00 | 期货机构持仓补采 |
| `com.trade.lhb-backfill` | 18:30, 19:30 | 龙虎榜补采 |
| `com.trade.rzhb-backfill` | 19:15 | 融资融券补采 |
| `com.trade.etf-national-team` | 20:07, 21:30 | 国家队 ETF 份额 + 信号 |
| `com.trade.backfill-evening` | 16:35, 02:00 | 多源补采兜底（指数/宽度） |
| `com.trade.lab-auto` | 19:00 | 策略实验室自动回测 |
| `com.trade.schedule-monitor` | 0/15/30/45 每 15 分钟 | 调度监控告警 |

**交易日闸门**：`update_all.sh` 内置交易日判断（`app.calendar.is_trading_day()`），非交易日跳过采集仅 deploy + check_signals。传 `force` 参数可绕过（周末补数据/校准）。

**盘中时段闸门**：`deploy.sh` 在交易日 09:30-15:30 拒跑全量 export+deploy（防覆盖 intraday 实时版），force 可绕过。

**mac 休眠根治**：launchd 触发时 mac 在睡眠边缘会漏跑，已配 `pmset` 工作日 17:48 唤醒 + `caffeinate -i -w $$` 防跑期间睡。

---

## 数据完整性兜底

1. **多源补采**：[`index_backfill.py`](../app/collector/index_backfill.py) 主源采后校验 8 核心 A 股指数，缺失则 baostock（7/8）→ 腾讯（兜底 kc50/bj50）补采
2. **CFFEX 双时点**：20:05 + 21:00 两次拉期货持仓（避免 CFFEX 当晚数据延迟）
3. **mootdx → BaoStock fallback**：mootdx 通达信行情接口全 empty 时自动切 BaoStock 采剩余
4. **ETF 份额双源**：沪市 `fund_etf_scale_sse`（上交所）+ 深市 `fund_scale_daily_szse`（深交所）+ mootdx bars 兜底
5. **backfill-evening 02:00 + 16:35**：凌晨 + 下午两次兜底补漏
6. **进程互斥**：`update_all.sh` 用 `fcntl.flock --nb` 独占锁，防止多个 update_all 并发跑（撞 mootdx/stock_daily progress 原子写 + 通达信/东财并发限流全 empty 空转）

---

## 数据准确性声明

- 本看板数据准确性受数据源限制，请以官方披露为准
- 申万行业指数 2016-2021 段用当前成分股算宽度存在 ~5-10% 偏差
- 主力净流入/北向资金等东财源偶发 IP 封锁，可能缺当日值（`collect_health` 会标注 error）
- 北向资金 2024-08 港交所新规后改季度披露，日频净买额停更，改用成交总额 + 季度反算
- mootdx 不复权原始价，跨除权日 pct_change 失真（记录不修）
- ETF 国家队信号为代理推断，非真实国家队席位数据

详见 [README.md 声明](../README.md#-声明)。

---

## 15. 异源兜底矩阵(2026-08-15 调研)

> 用户原则(2026-08-15):任何数据源必须有异源兜底(不同 host/协议/供应商),fallback 走同一源=伪多源=方案没做好;优先免费多源自动切换多重兜底。
> 全项目单源/伪多源指标 → 免费异源组合,逐源实测(数据截止 2026-08-15)。所有"实测可达"均有本次 curl 实测支撑,非文档推断。

### 15.1 真异源互备标杆(项目已有范式)
核心指数(新浪→baostock→腾讯)、主力净流入(东财→同花顺)、北向(HKEX→东财)、盘中实时(腾讯→新浪)、申万行业(申万→同花顺)、分时1min(同花顺→东财)、ETF日线(fetch_etf_ohlc sina+mootdx)。

### 15.2 可直接上(数值逐位互证)
| 指标 | 现主源 | 免费兜底源 | 验证 |
|---|---|---|---|
| us10y | 东财 bond_zh_us_rate | **美国财政部官方 CSV**(home.treasury.gov daily-treasury-rates.csv) | 8/14 逐位一致 4.68 |
| hk_south | 东财 stock_hsgt_hist_em | **HKEX 官方 JS**(data_tab_daily_{date}e.js)反算南向净买额 | 逐位一致 -13.16亿 |
| cn10y | 中债 bond_china_yield | 东财 bond_zh_us_rate(datacenter) | 完全一致 1.6964 |
| a_turnover_rate | 腾讯 index_turnover | 东财 push2delay secid=1.000001 f168 | 完全一致 1.03% |
| 美股指数 | 新浪 index_us_stock_sina | 东财 push2delay 100.NDX 等 | 逐位一致 纳指 26729.16 |
| 全球指数 | 新浪 index_global_hist_sina | 东财 push2delay(日经/DAX/富时/KOSPI) | 实测可达 |
| gold(沪金AU0) | 新浪 futures_main_sina | 东财 futsseapi aum 沪金主连 | 差 0.06 元 |
| wti/comex_silver/brent | 新浪 futures_foreign_hist | 东财 futsseapi 国际期货 620条 | 实测可达 |

### 15.3 次优先(需映射/互补)
| 指标 | 现主源 | 兜底源 | 说明 |
|---|---|---|---|
| a_width_up/down_count、a_amount | **新浪** stock_zh_a_spot(认知修正:非东财) | ①东财 push2delay clist 全A 5549只 ②mootdx 自算 | 东财实时+ mootdx 盘后/历史互补 |
| a_width_zt/dt/max_lianban | 东财 push2ex 四池 | ①同花顺涨停池 limit_up_pool ②mootdx 自算 | 同花顺 8-14 实测 62 vs 东财 63 只 |
| a_width_zhaban_rate | 东财双池(伪双源) | 同花顺 limit_up + mootdx seal_rate | 主东财兜同花顺/mootdx |
| 同花顺概念27 | 同花顺 | 东财概念板块 clist(m:90+t:3) | 两套概念体系需映射表 |
| 国证主题399xxx | 新浪 | 东财 push2delay/腾讯 | 真异源 |
| 中证主题930xxx/931xxx | csindex 官方 | 东财快照(无 kline 历史) | 历史单源(官方权威),快照校验 |

### 15.4 刷不到/证伪(诚实标注)
1. a_div_yield 乐咕同口径无免费异源:中证上证综指股息率(2.36%)是成分股口径,乐咕(2.66%)是全A口径,只能方向参考/离群告警,不直接替换。
2. 东财 push2his kline 全家族被封(ConnectionError),美股/中证主题历史不能走东财 kline,东财仅作实时快照校验。
3. FRED 需 API key(400),美国财政部 CSV 替代成功。
4. 英为/investing 403 反爬;新浪 hf_TNX 美债实时返回空;SGE 官方无公开 JSON。

### 15.5 实施优先级(按性价比)
1. 立即:a_turnover_rate(东财)/us10y(美财政部)/cn10y(东财)/hk_south(HKEX官方)/gold(东财)/美股全球(东财)
2. 次优先:宽度三组(东财clist+mootdx)/wti银布(东财futsseapi)/中证主题快照校验
3. 需映射:概念27↔东财概念、oil主连合约归属对齐

### 复现(实测命令,2026-08-15)
```bash
# HKEX 南向净买额反算(8/14收盘)
curl 'https://www.hkex.com.hk/eng/csm/DailyStat/data_tab_daily_20260814e.js' -H 'Referer: https://www.hkex.com.hk/Mutual-Market/Stock-Connect/Statistics/Historical-Daily'
# 东财国内期货沪金主连
curl 'https://futsseapi.eastmoney.com/list/SHFE,DCE,INE,CZCE,GFEX?orderBy=dm&sort=asc&pageSize=1200&pageIndex=0&token=58b2fa8f54638b60b87d69b31969089c&field=dm,sc,name,p,zdf&blockName=callback'
# 美国财政部 10Y(2026全部)
curl 'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/2026/all?type=daily_treasury_yield_curve&field_tdr_date_value=2026&page&_format=csv'
# 东财美股指数
curl 'https://push2delay.eastmoney.com/api/qt/stock/get?secid=100.NDX'
# 东财全A clist(分页100,总5549)
curl 'https://push2delay.eastmoney.com/api/qt/clist/get?pn=1&pz=100&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f3,f6'
# 同花顺涨停池(8/14)
curl 'https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool'
```

## 相关文档

- [data-dictionary.md](data-dictionary.md) - 数据字典（JSON 字段说明）
- [LICENSE-data.md](LICENSE-data.md) - 数据集 CC BY 4.0 授权
- [REQUIREMENTS.md](../REQUIREMENTS.md) - 需求 + 指标公式披露 + 宽度指标口径
- [../README.md](../README.md) - 项目总览
