# 降亏过滤方法论调研档案(二轮挖掘前置调研,2026-08-22)

> 触发:一轮挖掘(docs/kelly/analysis/sim-window-loss-mining-20260822.md)只在「市场四档×信号类型(+vol/dd)」框架内穷举 246 条,用户定调"能力不应该只挖掘出这4个,应该还可以更多,去网上学习下再来试试"。本档案 = 阶段一上网调研产物:全量收录业界可用方法,**平等收录不下优劣结论**(用户定调),标注来源类型与可测性,最后由阶段三回测同台比武分胜负。
> 来源类型标签:「主流量化」= 学术/主流量化社区;「国内特色」= A股本土打法/券商金工;「国外经典」= 海外经典技术分析/宏观择时;「非主流」= 学术边角/另类,只要可回测就收。
> 每条格式:一句话原理 / 需要什么数据 / 本项目可测性(✓全史=2011起可得,△近段=2014后,✗缺数据)/ 参考链接。

## A. 主流量化

### A1. Equity Curve Trading(策略自身净值线 MA 过滤)
- 原理:把策略自己的盈亏累积线当输入——净值线跌破其 MA(N 笔已平仓交易)就停开新仓,升回再恢复;趋势型系统(赢亏成串)适用下穿停,均值回归型反而不适用。
- 数据:策略自身逐笔盈亏序列,无需外部数据。
- 可测性:**✓ 全史**(trades 自身);N 扫描 10/20/30/60 笔。业界经验:~150-200笔/年→20笔MA;短窗抖动长窗迟钝。
- 参考:http://www.adaptrade.com/MSA/crossover.htm ; https://trendsandbreakouts.com/equity-curve-trading (分层响应:1.5×平均回撤减半仓/更深暂停/2×全面复查);https://www.luxalgo.com/library/concept/equity-curve-based-throttling/

### A2. Market Breadth 市场宽度(AD线/新高新低/均线之上占比)
- 原理:指数由少数大票扛或普涨普跌,宽度指标度量"参与度";负宽度确认下跌、宽度背离预警顶;业界共识=单独作择时信号弱(QuantifiedStrategies SPY 回测 profit factor 仅1.55),作**确认过滤器**或多因子组件有价值(PENTAD 模型回撤 -13% vs 买入持有 -55%)。
- 数据:A/D 线、52周新高新低差(NH-NL)、均线之上个股占比、涨跌家数比。
- 可测性:**✓ 全史**:a_ma_bullish/a_ma_bearish/a_ma_cross(1991起)、a_nhnl_52w/a_nh_20d/a_nl_20d(1990起);**△2016起**:a_ad_line/a_up_down_ratio/a_width_up_count/down_count。
- 参考:https://www.quantifiedstrategies.com/market-breadth/ ; https://www.quantifiedstrategies.com/advance-decline-indicator/ ; https://articles.stockcharts.com/article/three-breadth-signals-that-help-confirm-market-trends/

### A3. 波动率目标/波动率管理(Volatility Targeting)
- 原理:高波动期降风险(Moreira & Muir JOF 2016:波动变化不被预期收益抵消,产生 alpha);VIX 类前瞻波动率比已实现波动更优(Božović 2024);反方证据:Bongaerts FAJ 2020 无条件 vol targeting 不稳定;"中间带"有时优于极值过滤(VIX 18-28 带 Sharpe 1.51 vs >30 只 0.89)。
- 数据:已实现波动(自算)或期权隐含波动率指数。
- 可测性:**✓**:QVIX(a_qvix_1000,2005起;a_qvix_300,2012起)= A股期权波指≈中国版VIX;已实现vol一轮已测(vol≥20%落选),本轮测 **vol 变化率(升波/降波 regime)** 新口径。
- 参考:https://onlinelibrary.wiley.com/doi/10.1111/jofi.12513 ; https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4507634 ; https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3636727 ; https://optionspilot.app/blog/vix-filter-iron-condor-entries-backtesting-timing

### A4. Risk-On/Risk-Off 多资产 regime
- 原理:多资产(股债商品加密)各自对 200 日 MA 的位置投票,≥N 个在上方=risk-on 满仓,否则空仓(SPY 回测年化12.9%、回撤33%→16%)。
- 数据:多资产行情。
- 可测性:**✓ 部分**:本地有 hs300/gold(oil/wti/us10y/cn10y 2016 起)→ 可组「hs300+gold 双资产 MA 投票」简化版;完整多资产 ✗(债券指数/加密历史缺)。四档(market_tier)本质已是单资产 MA regime,本轮不重复,只补跨资产确认变体。
- 参考:https://www.quantifiedstrategies.com/risk-on-risk-off-trading-strategy/

### A5. 量能/量价结构过滤(成交量萎缩·放量·换手分布)
- 原理:缩量上涨=情绪不足、放量下跌=系统性抛压;StatOasis 经验法则:**量能过滤器须影响≥15%的交易**才可能不是曲线拟合;ATR 扩张 regime 过滤 Donchian 突破(扩张期才交易)4 配置仅 1 个成立——regime 过滤不给 edge,只是防止市场拿走你的 edge。
- 数据:成交额/量比/换手率分布。
- 可测性:**✓ 全史**:hs300 amount(index_daily 表 2002 起,自算量比=amount/MA20);**△2016起**:a_volume_ratio(全A量比)/a_amount_ma5_ma20/a_turnover_mean/p10/p90。
- 参考:https://statoasis.com/post/supercharge-your-trading-how-volume-filters-impact-your-strategy ; https://www.fractiz.com/strategies/pattern-rotation/ ; https://www.anupshinde.com/pattern-rotation-backtested/

### A6. 子群发现/决策树规则提取(Subgroup Discovery · CART/SIRUS)
- 原理:pysubgroup 的 BeamSearch/Apriori 在特征×标签空间找高纯度子群(合取规则直接可读);SIRUS 从浅树森林提取紧凑加性规则集,抗扰动;纪律=黑盒模型不给结论,只取叶路径转人工规则再过三道门。
- 数据:特征矩阵+标签(单笔盈亏正负)。
- 可测性:**✓**(sklearn/pysubgroup 未装,手写 beam search + 穷举叶路径,一轮 mine3 已有同款经验);特征=本轮全部新特征+tier/sig/mktD 一轮维度。
- 参考:https://github.com/flemmerich/pysubgroup ; https://pysubgroup.readthedocs.io/en/stable/readme.html

### A7. 策略失效统计检测(CUSUM/SPC/贝叶斯变点)
- 原理:对滚动单笔 R 做 CUSUM 累积偏离,Wald 阈值 = -ln(α)/|badIR-goodIR| 控制误报率;固定回撤止损被批"停了路径而非过程"(区分不了波动冲击与 alpha 缓慢失血);贝叶斯在线变点检测输出"结构性衰减"后验概率作 kill switch。
- 数据:策略自身逐笔盈亏。
- 可测性:**✓ 简化族可测**:滚动 N 笔均 pnl<0 停 / 连续 S 笔亏损停(S∈{3,4,5,6})/ CUSUM 标准实现;完整 BOCPD 本轮不做(复杂度高,标注未来)。
- 参考:https://trading.glass/en/academy/trading-intelligence/advanced-statistical-thinking/edge-degradation ; https://www.morganstanley.com/content/dam/im/assets/publication/thought-leadership/article/article_whengoodmanagersstumble_en.pdf ; https://www.quantbeckman.com/p/with-code-switch-off-bayesian-online ; https://bettersystemtrader.com/6-ways-to-detect-a-failing-trading-strategy-with-kevin-davey/

### A8. 时序动量 regime(TSMOM/MA 斜率)
- 原理:资产自身过去 N 日收益符号决定持有/离场(Moskowitz Ooi Pedersen 2012);MA 斜率比 MA 排列更敏感(领先性)。
- 数据:hs300 日线自算。
- 可测性:**✓ 全史**(一轮已测 MA 排列「非多头排列全停」=双重不合格落选;本轮测 **MA20 斜率** 新变体+20日涨幅分位)。
- 参考:Moskowitz et al. "Time Series Momentum" JFE 2012。

## B. 国内特色

### B1. A股情绪周期打法(涨停家数/连板高度/炸板率/晋级率/赚钱效应)
- 原理:游资体系四阶段——主升(涨停>60家+炸板率<30%)、分歧(30-60家/断板)、退潮冰点(<30家+炸板率>50%+跌停一片,"空仓为最优选择");广发《交易策论》按活跃资金仓位划分涨潮/退潮/混沌期;中银证券快慢线四象限(慢线低位+快线低位=底部买点,双高=高潮警戒)。
- 数据:涨停/跌停家数、炸板率、连板高度、昨日涨停溢价。
- 可测性:**△2016起**:a_width_zt_count/dt_count(涨停跌停家数,2016起)可代理情绪周期;**✗ 缺历史**:炸板率(a_width_zhaban_rate 仅2026-06起50天)/连板高度(max_lianban 同)/晋级率/昨日涨停溢价(daban_premium 同)——标注未来数据补齐后重试。
- 参考:https://caifuhao.eastmoney.com/news/20260313205738664266030 ; https://ag.yueniuzq.com/market-review/judge-emotion-cycle-via-broken-and-upgrade-rate/ ; 广发证券《交易策论(第7期)》 https://www.microbell.com/repinfodetail_4378600.html ; 中银证券快慢线 https://finance.sina.com.cn/stock/stockzmt/2025-02-13/doc-inekhynn8599460.shtml

### B2. 券商金工常用择时(两融变化率/换手率分位)
- 原理:华泰金工情绪温度计——融资净买入 MA20 滚动 60 日 z-score 作杠杆情绪因子(单因子弱,右侧确认改进);换手率分位(历史分位>80%=过热)。
- 数据:两融余额、换手率。
- 可测性:**△两融 a_fund_margin 2021起**(覆盖短,近5年观察口径);**△换手 a_turnover_mean/p10/p90 2016起**。
- 参考:https://finance.sina.com.cn/roll/2026-03-17/doc-inhrhttn5371022.shtml (华泰:A股情绪温度计)

### B3. 北向资金流向(A股特色资金流)
- 原理:北向净流入+两融回升+温和放量=内外共振看多;北向流出+放量=警惕系统性风险(EasyQuant 实现:5日净流入>50亿看多加仓,<-50亿降仓)。
- 数据:北向每日净买入。
- 可测性:**△ a_fund_north 2014-11 起**(近11年口径;注:2024-08 后交易所停止披露实时额度,存量数据为日度净买入口径,边际变化仍可算)。
- 参考:https://github.com/AlanFokCo/EasyQuant/blob/main/docs/tutorials/10-ashare-data-risk.md ; https://ag.yueniuzq.com/stock/northbound-fund-flow-analysis/

### B4. 华泰式恐贪反转(恐慌买·贪婪停,右侧确认)
- 原理:fear_greed≤10% 恐慌买入、≥90% 贪婪空仓;"触及10%不买、回归10%之上再买"右侧确认规避流动性负反馈;2020以来绝对收益97%超额40%(华泰回测)。
- 数据:恐贪指数。
- 可测性:**✓ fear_greed 2005 起**(score_daily 表)+ a_sentiment(2016起)双源。
- 参考:同 B2 华泰链接。

## C. 国外经典

### C1. VIX 期限结构/SKEW/PutCall Ratio
- 原理:VIX/VIX3M>1(backwardation)=压力进行时;SKEW>145+深 contango="Divergence" regime 先于 10%+ 回撤(80%命中/30%误报,2006-2025 回测);P/C>1.5 反向买、<0.4 自满风险。
- 数据:VIX 期限/期权衍生指标。
- 可测性:**✗ 完全不可得**(A股无对应免费历史:SKEW/期限结构/PutCall 均无);qvix 单点近似已在 A3 覆盖。标未来重试。
- 参考:Quant Decoded "SKEW + VIX Term Structure Backtest 2006–2025";https://github.com/(VIX Term Structure Pro)

### C2. FOMC/宏观日历效应
- 原理:FOMC 会议前后的 risk premia 剥离(FOMC drift);宏观事件前降风险。
- 数据:美联储议息日历+本地事件响应。
- 可测性:**✗ 未测**(无现成 FOMC 日历表入库;且 A股短线 ETF 组合对 FOMC 的传导链路弱,优先级低)。标未来可从 Fed 官网抓历史日期表后重试。
- 参考:Lucca & Moench "The Pre-FOMC Announcement Drift" JF 2015。

### C3. Hussman/GMO 式估值-趋势双因子
- 原理:估值分位(贵/便宜)×趋势(牛/熊)联合决定暴露——估值高位+趋势走坏=最危险象限(Hussman 回测该象限年化深负);估值单独不择时,趋势单独滞后,乘起来才锋利。
- 数据:估值指标(股息率/PE 分位)+价格趋势。
- 可测性:**✓ a_div_yield 全A股息率 2005 起**(2005-2026 共 21 年)×hs300 四档/MA 趋势,可测联合象限。
- 参考:Hussman Funds weekly commentaries(GNU 估值×趋势联合模型);GMO 7-year asset class forecasts 方法论。

### C4. 日历效应(A股:春节效应/二月效应/月末旬/星期几)
- 原理:A股最稳健异常=春节前后(CNY 前3天+后1天集中为正,McGuinness & Harris 2011);二月效应替代美股一月效应(IMF WP 2016);星期几效应不稳定(Friday→Tuesday 漂移);turn-of-month 在 A股弱于港股/B股。
- 数据:交易日历+农历节日表。
- 可测性:**✓ 全史**(春节/中秋日期硬编码 2011-2026 对照表;旬/星期直接算)。一轮 greedy15 已含月份规则(5月/11月等),本轮补春节窗口/旬/星期几全月扫描。
- 参考:https://www.imf.org/en/publications/wp/issues/2016/12/31/seasonalities-in-china-s-stock-markets-cultural-or-structural-18720 ; https://ideas.repec.org/a/taf/apfiec/v21y2011i13p917-929.html ; Liang Liu Zebedee SSRN 4038196(农历一月效应)

## D. 非主流(平等收录,待回测检验)

### D1. 月相效应(满月/新月)
- 原理:Yuan Zheng Zhu (JEF 2006) 48 国证据——满月附近收益低于新月附近,年化差 3-5%;新兴市场更强。
- 数据:月相日期(天文算法:朔望周期 29.53 天自锚点推算)。
- 可测性:**✓ 全史**(简化算法精度 ±1 天足够窗口检验)。
- 参考:https://www.sciencedirect.com/science/article/abs/pii/S0927539805000691 ; https://papers.ssrn.com/sol3/papers.cfm?abstract_id=281665

### D2. 中秋节效应(East Asia 特有)
- 原力: nostalgia/满月负面联想/收获不确定性 → 中秋前后约 2 周换手、波动、收益下降,中日韩台最强(Yuan et al. 后续研究)。
- 数据:农历八月十五公历对照表(硬编码 2011-2026)。
- 可测性:**✓ 全史**。
- 参考:"The lunar moon festival and the dark side of the moon", Applied Financial Economics 2010。

### D3. 道氏理论相互确认
- 原理:工业指数与铁路指数互证才有效——量化子集=大盘(hs300)与小盘/成长(csi1000/cyb)趋势互证:两者同向=趋势有效,背离=顶部风险。
- 数据:两个指数日线。
- 可测性:**✓**(csi1000/cyb 日线 index json 有;注意 csi1000 基期较晚,查覆盖后定)。
- 参考:Robert Rhea《道氏理论》;经典六定理量化化。

### D4. 缠论中枢可量化子集(Donchian 区间突破)
- 原理:缠论"中枢=N 笔重叠区间",严格识别复杂;可量化近似=N 日高低点区间(Donchian),突破上沿=多头中枢上方,跌破下沿=中枢破坏。
- 数据:日线 OHLC 自算。
- 可测性:**✓ 全史**(20日 Donchian 上下沿位置分档)。
- 参考:缠中说禅《教你炒股票》108 课;Donchian channel 通道突破(Turtle)。

### D5. 节气效应(二十四节气)
- 原理:中国传统时间节律与市场情绪(国内民间打法,无严谨学术证据);太阳黄经每 15° 为一节气,日期每年漂移 ≤2 天。
- 数据:节气日期表(天文公式可算或查表)。
- 可测性:**✓ 可测但优先级低**(需先建 24 节气日期表;样本分散到 24 个桶,每桶 n 小)。标注:若做,合并为"节气±2 日窗口 vs 其他"二元口径。
- 参考:民间量化圈流传打法(无权威文献)。

## E. 数据可得性总表(阶段二映射)

| 特征 | 指标源 | 覆盖起点 | 全史可用 |
|---|---|---|---|
| 均线之上占比 | a_ma_bullish/bearish/cross | 1991 | ✓(实测值域0-8整数,疑为"多头指数计数"非百分比,语义待确认但可测单调阈值;2026-07中旬后有零值段) |
| 52周新高新低差 | a_nhnl_52w/nh_20d/nl_20d | 1990 | ✓(实测值域-8~+8整数,疑为"新高指数数-新低指数数"计数差;81%交易日为0,信息集中在尾部) |
| QVIX 期权波指 | a_qvix_1000 / a_qvix_300 | 2005/2012 | ✓/△ |
| 恐贪指数 | score_daily.fear_greed | 2005 | ✓ |
| hs300情绪分 | score_daily.sentiment_hs300 | 2002 | ✓ |
| 轮动速度 | a_rotation_5d/10d/20d | 2000 | ✓ |
| hs300 量能 | sentiment.db index_daily.amount | 2002 | ✗(实测 amount 全部 NULL,hs300-all.json amount 也 None——量能只能用全A口径 a_volume_ratio/a_amount,2016起) |
| hs300 价格衍生 | static-site/data/index/hs300-all.json | 2010 | ✓(MA排列/斜率/dd/vol/vol变化率/20日涨幅) |
| 四档 | market_tier_history.json | 2002 | ✓(一轮已用) |
| 全A股息率 | a_div_yield | 2005 | ✓ |
| AD线/涨跌比 | a_ad_line / a_up_down_ratio | 2016 | △ |
| 涨停/跌停家数 | a_width_zt_count / dt_count | 2016 | △ |
| 全A量比/成交额 | a_volume_ratio / a_amount(_ma5/ma20) | 2016 | △ |
| 换手率分布 | a_turnover_mean/p10/p90 | 2016 | △ |
| A股情绪分 | score_daily.a_sentiment | 2016 | △(注意在 score_daily 表不在 daily_metric) |
| 北向资金 | a_fund_north | 2014-11 | △ |
| 两融 | a_fund_margin | 2021 | △(覆盖短) |
| 炸板率/连板高度/涨停溢价/晋级率 | a_width_zhaban_rate/max_lianban/daban_premium | 2026-06 | ✗ 未来重试 |
| VIX期限结构/SKEW/PutCall | — | — | ✗ 未来重试 |
| FOMC 日历 | — | — | ✗ 未来重试 |

## 复现
- 本档案为纯调研文档,无脚本依赖;搜索执行于 2026-08-22(WebSearch,关键词见各条参考链接)。
