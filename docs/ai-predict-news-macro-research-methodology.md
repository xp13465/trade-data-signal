# AI 每日预测「新闻面/宏观事件日历/其他变量面全景」调研报告

> 调研时间:2026-08-16
> 调研 agent(只读,不改代码/基准/算法)。测试基准 = v1.1.1(纯调研,不动任何基准)
> 任务:评估 AI 预测(gen_daily_brief.py 17:50 盘后跑)是否应加入新闻面/宏观事件日历/其他变量维度;含现状盘点 + tradeagentcn 实锤 + 业界方法论 + 完整变量面全景 + 页面展示设计建议。
> 并行:另一 researcher 实测金十/东财快讯/财联社/宏观日历接口可行性(本报告只给字段期望,供其对照)。
> 前置文档:`docs/daily-brief-optimization.md`(#7/#8/P1-5/P1-6)、`docs/ai-predict-multiagent-plan.md`(阶段三事件面)、`docs/daily-brief-range-prediction-spec.md`(三层命中口径)、`scripts/gen_daily_brief.py`(现状)。

---

## 0. 一句话结论

**AI 预测当前喂的是「技术/资金/情绪」三面,缺新闻面/宏观日历/事件面;但项目里已经有一大批「采集了但没喂给 AI」的高价值数据(估值位置面/美股期货/龙虎榜/腾落线/新高新低/解禁/行业资金流/打板情绪),接入成本几乎为零,优先级最高;新闻面与宏观日历需采集,业界实证其有效(尤其宏观公告日波动效应、美股隔夜对 A股开盘领先性、新闻情绪经 NLP 量化有增量),建议 P1 采集接入,页面同步加「明日关键事件」展示位。**

**优先级总排序:先补「已有未注入」(P0,零成本),再采「宏观日历 + 新闻快讯」(P1,低成本高价值),最后评估「政策/日历/打板」等增强(低优先)。**

---

## 1. 现状盘点:AI 预测实际吃到的全部变量维度

> 事实源:`scripts/gen_daily_brief.py` `load_data()` L214-518(数据注入)+ `build_prompt()` L651-747(system 规则)+ 多角色版 `_split_role_domains()` L938-988 + `build_role_messages` L1013。生产配置 `config/daily_brief.yaml`: `multi_agent_enabled: true`(生产走 6 角色编排:技术/资金/情绪/风控 并行 → 研究员多空辩论 → 主编组装)。

### 1.1 单 prompt 主链路注入清单(load_data L214-518)

| 维度面 | 注入变量 | 数据源 | 状态 |
|---|---|---|---|
| 行情/技术 | summary(均线多空 ma_bullish/ma_bearish、涨跌家数、涨跌停数、成交额、量能 label)、signals_today(20条买点/卖点/波段)、industry_heatmap_top(10板块)、middle_indices(sz/cyb/kc50/bj50/hsi/hstech 当日涨跌幅)、cn10y(10年国债收益率) | summary.json/overview.json/index_daily/daily_metric | ✅ 已注入 |
| 信号胜率 | signal_stats_buy_top(买系20日胜率 top10) | signal_stats.json | ✅ 已注入 |
| 资金 | a_fund_main(主力)、a_fund_margin(两融)、a_fund_north(北向成交额,恒正,口径已标注)、a_fund_north_quarterly(季度)、hk_south(南向) | daily_metric | ✅ 已注入 |
| 机构/期货 | futures_acc_trend_tail/latest(机构净多5日)、futures_acc_conclusion、inst_ih_trend(中信/机构top20/国泰君安 席位净加仓15日) | futures*.json | ✅ 已注入 |
| ETF汪汪队 | etf_national_team(异动信号+共振)、etf_national_team_share(12只近5日份额)、etf_national_team_holders(季报机构占比) | overview/etf_national_team-1m.json | ✅ 已注入 |
| 情绪 | a_sentiment/fear_greed/6宽基情绪分(scores)、recent_freeze(冰点)、a_rotation_5d/10d/20d(板块轮动)、a_rotation_concept_*、a_width_fengban_rate(封板率)/a_width_max_lianban(最大连板)/a_width_zhaban_rate(炸板率) | score_daily/daily_metric | ✅ 已注入 |
| 波动/量价 | a_qvix_300/a_qvix_1000(期权波动)、a_turnover_mean/p90/gt5_pct(换手)、a_volume_ratio/a_volume_signal(量比)、a_amount/ma5/ma20(成交额) | daily_metric | ✅ 已注入 |
| 预警 | alert.high/low(8维命中 dims) | alert.json | ✅ 已注入 |
| **新闻面** | **无** | — | ❌ 无任何新闻/舆情 |
| **宏观事件日历** | **无**(cn10y 是收益率,非日历) | — | ❌ 无 CPI/非农/FOMC 公布日历 |
| **估值/位置** | **无** | — | ❌ 有数据未注入(见 §2) |
| **跨市场** | **无**(cn10y 有;美股期货/gold/oil/usdcnh/cn_us_spread 均未注入) | — | ❌ 有数据未注入(见 §2) |

### 1.2 多角色版数据域(split_role_domains L938-988)确认:四角色都不含下述「已有未注入」面

- **tech 域**:indices + signals_today + signal_stats_buy_top + summary(均线多空/涨跌家数/量能)
- **fund 域**:funds + futures_acc_trend + inst_ih_trend + north_quarterly
- **sentiment 域**:scores + freeze + industry_heatmap + alert_low + rotation_width(封板/连板/炸板) + etf_national_team
- **risk 域**:alert + risk_funds(qvix/volume/main/hk_south/turnover) + industry_heatmap

**四角色均未覆盖**:估值位置(positions)、美股/全球期货(us_futures_*)、龙虎榜(lhb_*)、腾落线(ad_line)、新高新低(52w)、行业资金流(ind_flow_sw_*)、解禁/IPO(unlock_*/ipo_*)、打板溢价(daban_premium)、中美利差(cn_us_spread)、离岸人民币(usdcnh)。→ 这些就是「已有但没喂」的接入成本≈0 面,详见 §2。

### 1.3 文档已标缺口(前置文档原文)

- `docs/daily-brief-optimization.md` P1-5(L234-239):「日历效应/节假日/月末季末提示」**未实施**(「A股有真实日历效应(月末/季末资金面考核、长假前避险缩量、财报季波动、LPR/CPI 等数据披露日前后波动)」;P2 级,数据可用性 🔶 需采集)
- 同文档 P1-6(L241-246):「新闻舆情/宏观事件维度」**未实施依赖采集**(「AI 预测若只喂行情数据,会漏掉当日重大政策/公告/外围事件对次日的影响」;若短期不采集,**AI 预测必须显式声明"不含新闻/舆情维度"**)
- `docs/ai-predict-multiagent-plan.md` 阶段三(L91):「事件/新闻面分析师,输入当日快讯摘要(需新增采集,非本次范围)」—— 多角色 6 角色编排中 ⑤⑥ 已有,④事件面缺

---

## 2. 「项目已有数据但没喂给 AI 预测」清单(接入成本≈0,优先级最高)

> 事实源:`data/sentiment.db` daily_metric 全量 + `static-site/data/` 产物。以下均验证过**有真实值**(抽查 20260814 最新值),但 gen_daily_brief.py `load_data`/`_split_role_domains` 均未引用。

### 2.1 估值/位置面(基本面,项目已有)
| 数据 | 验证值(20260814) | 说明 |
|---|---|---|
| `*_position_1y/3y/5y`(sh/sz/hs300/csi500/csi1000/cyb/kc50/sz50) | sh_position_1y=40.4 | **宽基指数估值位置百分位**(position.json `positions` 数组,含 current 点位/1y/3y/5y 百分位) |
| `a_div_yield` | 2.66 | 上证股息率(%) |

### 2.2 跨市场/全球面(项目已有,全未注入)
| 数据 | 验证值 | 说明 |
|---|---|---|
| `us_futures_es/nq/ym/rty_chg` | es_chg=0.098(20260814) | **美股期货涨跌幅**(intraday_snapshot.json `us_futures` + daily_metric) |
| `us_futures_dax/cac40/ftse100/sx5e/asx200/hsi/kospi/nikkei225/sensex_chg` | 有值(11条) | 欧股/亚太期货 |
| `usdcnh` | 678.78 | 离岸人民币(注意量纲:疑似×100,实施需确认) |
| `cn_us_spread` | -2.98 | 中美利差(10Y) |
| `gold`/`wti_oil`/`brent`/`comex_silver` | 有值 | 贵金属/原油 |

### 2.3 宽度/技术面(项目已有,仅 summary 当日部分值注入,历史序列未注入)
| 数据 | 验证值 | 说明 |
|---|---|---|
| `ma_alignment.json`(bullish/bearish/cross 全历史) | 有值 | 均线多空/金叉死叉(现仅 summary 注入当日 ma_bullish/bearish,无 cross、无历史) |
| `new_high_low.json`(nh_20d/nl_20d/nhnl_52w/nh_52w/nl_52w 全历史) | 有值 | **新高新低 52w**(现仅 summary 注入当日 nh_count/nl_count/nhnl) |
| `ad_line.json`(腾落线 ADL + ma5/ma20 + 涨跌比) | ad_line=-133737 | **腾落线**(涨跌家数累计差,经典宽度指标) |
| `a_up_down_ratio` | 有值 | 涨跌比 |

### 2.4 资金面增量(项目已有,未注入)
| 数据 | 验证值 | 说明 |
|---|---|---|
| `lhb_count`/`lhb_inst_net` | lhb_inst_net=5.22 | **龙虎榜机构净买额**(152条) |
| `ind_flow_sw_*`(31申万行业资金流) | 有值(144条) | **行业主力资金流** |
| `ind_turn_sw_*`(行业换手率) | 有值 | 行业换手 |

### 2.5 情绪/打板增强(项目已有,部分未注入)
| 数据 | 验证值 | 说明 |
|---|---|---|
| `a_width_daban_premium` | 0.06/1.27 | **打板溢价**(封板资金强度) |
| `a_width_seal_rate` | 有值 | 封单率 |
| `a_width_zb_count` | 有值 | 炸板数(现只注入炸板率) |

### 2.6 供给/事件面(项目已有,未注入)
| 数据 | 验证值 | 说明 |
|---|---|---|
| `unlock_count`/`unlock_amount` | unlock_amount=4264.59 | **解禁股数量/金额**(供给面,30条) |
| `ipo_count`/`ipo_amount` | 有值 | IPO 数量/金额 |

**小结**:上述 6 组 ≈ 20 个指标/序列全部真实有值、全部未注入 load_data。**接入 = load_data 加字段 + prompt/角色域加引用,零采集成本**。这是「用户要的:把已有数据用足」的直接兑现。

---

## 3. tradeagentcn 实锤做法(用户点名参考,拉 GitHub 原文)

> 事实源:GitHub `hsliuping/TradingAgents-CN` raw 拉取:`docs/features/news/NEWS_SENTIMENT_ANALYSIS.md`、`NEWS_SYNC_FEATURE.md`、`docs/guides/news_data_system/README.md`、`docs/agents/v0.1.13/analysts.md`、`data/analysis_results/detailed/000001/2025-07-28/reports/news_report.md`。

### 3.1 分析师团队架构(4 分析师 + 研究员 + 交易员/风控/组合)
- **基本面分析师**(fundamentals_analyst.py):公司财务/估值/健康度
- **市场分析师**(market_analyst.py):RSI/MACD/布林/趋势/支撑阻力
- **新闻分析师**(news_analyst.py):**新闻事件影响 + 宏观经济数据解读 + 政策影响 + 行业动态**(数据源 Google News/FinnHub/实时流/经济数据发布)
- **情绪分析师**(sentiment_analyst):散户/机构情绪(StockTwits/Reddit/股吧)
- 研究员多空辩论 → 交易员决策 → 风控/组合经理(本项目不做交易决策,合规红线)

### 3.2 新闻系统实锤(可借鉴的关键实现)
1. **多数据源**:Tushare 9 源(sina/eastmoney/10jqka/wallstreetcn/cls/yicai/jinrongjie/yuncaijing/fenghuang)+ AKShare(东财个股 `stock_news_em`/CCTV 市场新闻)
2. **情绪分析 = 关键词词典打分法(非深度模型)**:积极/消极关键词表 + 权重(涨停+1.0/跌停-1.0/暴涨+0.9/利好+0.6/上涨+0.5...),情绪分 **-1.0~1.0**
3. **关键词提取**:最多 10 个,按类别(政策/财务/资本运作/行业...)
4. **新闻分类**:company_announcement / policy_news / industry_news / market_news / research_report / general
5. **重要性评估**:high / medium / low(业绩/监管/重大事项=high)
6. **智能去重**:URL+标题+时间 唯一标识,跨源去重
7. **存储**:MongoDB,三层架构(REST API / 业务服务 / 数据提供);APScheduler 定时同步;MongoDB→API→本地缓存多层降级
8. **新闻分析师输出样例**(news_report.md 实拉):关键新闻提取 → 股价潜在影响(正/负/中)→ 建议+风险+关键价格位——**与项目 daily_brief 的「复盘/趋势/关注/风险」结构异曲同工**

### 3.3 对本项目的可借鉴结论
- **情绪打分用词典法就够**(本项目可直接实现:东财快讯标题/正文 按关键词表打分,无需大模型),tradeagentcn 就是这么干的,成本≈0
- **新闻分类 + 重要性过滤**是控制信噪比的关键(业界共识:新闻低信噪比,需去重+重要性筛选,见 §4.2)
- **事件/新闻面分析师 = 多角色编排的④角色**,本项目阶段三已预留(ai-predict-multiagent-plan.md L91),喂「当日快讯 top N + 宏观日历近 3 日」即可

---

## 4. 业界主流方法论与量化证据(§5.1 上网调研)

### 4.1 新闻情绪量化(News Sentiment NLP)—— 有效,但有边界
| 证据 | 结论 |
|---|---|
| 华泰证券 HAN 混合注意力(2019.1-2022.3,沪深300成分股):新闻情绪预测**个股次日涨跌**,TopK-Dropout 策略年化超额 **15.96%** | 新闻情绪对 A股次日有效 |
| 无监督财经新闻情绪指数 + 技术指标拼接:次日涨跌预测**准确率提升 3-5%**(T 检验显著) | 情绪指数有增量 |
| SSRN 2025:隔夜新闻情绪单看有预测价值,**纳入 A50 期货收益变量后增量消失** | 增量可能被市场价格变量吸收(冗余风险) |
| 多源金融大语言模型研究:新闻**低信噪比**,高相似重复新闻隐藏较少增量信号,需去重 | 去重/重要性过滤是前提 |
| LLM+GNN(西南证券 2025):Llama-8B 微调 + 双通道 GNN,提升组合夏普 | 前沿但实施成本高,本项目用词典法够用 |

### 4.2 宏观公告日效应(CPI/非农/FOMC)—— 波动率放大是主渠道
| 证据 | 结论 |
|---|---|
| SPY/QQQ 5分钟日内(2020-2025,630公告):公告后 30 分钟已实现波动率 +2.5 倍;通胀类(CPI)**+3.6~4.1 倍**,反应最大 | CPI 公布日波动放大显著 |
| Fama-MacBeth(1964-2021):公告日日均超额收益 9.14 bps vs 非公告日 1.87 bps;PPI/劳动/FOMC 公告日 11.8 bps vs 2.5 bps | **公告日溢价真实存在** |
| FOMC 冲击持续性最强;NFP/ISM/GDP 每年预公告收益 3.41% > FOMC 2.25%(次数多) | FOMC 最重要,其他按频次累计 |
| 预公告收益/方差比 35.53(显著),公告前 VIX 上升(不确定积累)、公告日 VIX 回落 | 公告日前不确定性溢价,公告后消解 |
| **A股注意**:以上多为美股证据;A股 CPI/PPI 公布日效应相对更弱但存在,中国数据公布集中在 09:30(CPI/PPI/社融)与 20:30-21:00(金融数据),**盘后 17:50 跑预测时,次日 09:30 公布的数据是「公布前夜」——正是预公告不确定性窗口,提示价值合理** | 接次日 CPI 等日历作「明日事件提示」逻辑成立 |

### 4.3 跨市场面(美股隔夜→A股)—— 强领先证据,项目已有数据
| 证据 | 结论 |
|---|---|
| 国泰君安期货:美股隔夜剧烈波动时,A股开盘方向与美股隔夜收盘方向一致 **~90%** | 隔夜美股对 A股开盘强领先 |
| Copula(2005-2025,4924交易日):S&P500 收盘→上证隔夜收益 Pearson 相关 **0.45**(R²≈0.20) | 相关可观 |
| 2018-2026 量化:S&P500 日涨跌解释沪深300 次日 **2.9%**(p<0.0001) | 日频显著但幅度小 |
| Granger 因果:**美股→A股单向**,反向不成立;S&P500 信息溢出占主导 | 方向确定 |
| 不对称:美股**跌的传染远强于涨**;周频相关 > 日频 | 下跌日更需关注 |

### 4.4 资金面(北向/龙虎榜/两融/主力)—— 项目已有大部分
- PACE 七维框架:资金维度权重最高(25/100),北向单日净买>10亿=强利多,主力净流入率>+5%=积极
- 机器学习 SHAP:北向 `hk_hold_chg_60d` 有预测价值;龙虎榜游资/机构席位活跃度、两融 `mg_short_chg_20d` 均进特征集
- **注意**:北向日频净买额 2024-08 港交所新规后已停更(项目已用「成交总额+季度反算+南向替代」,正确);龙虎榜仅盘后数据、覆盖有限;大盘类因子高度共线会损害模型(剔除后 lift +0.428)——提示本项目补维度要**防冗余**,美股期货 vs 全球指数选其一即可

### 4.5 估值/股债性价比(ERP)—— 中期有效,极端值最有用
- 中信:风险溢价对未来 1 年股债相对收益预测精度 **79%**;极值后 1/2/3 个月万得全A平均涨幅 +12.27%/+18.08%/+23.01%
- 国盛:ERP 股债轮动 A股年化 16%、夏普 1.2;大盘宽基(沪深300/上证50)胜率高
- **局限**:PE 滚动百分位与未来收益相关性弱(国海);ERP 中枢移动导致失效(中金,2011-14/2022-至今两次上移);股债跷跷板仅约六成
- **对本项目**:position.json 的 1y/3y/5y 百分位 + a_div_yield + cn10y 即可算 ERP 提示(如「股息率-10Y=2.66%-1.70%≈0.96%,处于历史 X 分位」),作**中期位置参考**,不作次日方向主依据(符合 P1-3「慢变量只作中期风格参考」同逻辑)

### 4.6 情绪面(涨停/打板/PCR)—— 项目已覆盖主要,补 2 个零成本
- 恐贪/涨跌家数/封板率/连板/炸板率 已注入;**打板溢价(daban_premium)、封单率(seal_rate)、炸板数(zb_count) 已有未注入**(打板溢价反映打板资金次日兑现意愿,是「打板情绪周期」经典指标)
- **认沽认购比 PCR**:50ETF 期权持仓量衍生,项目无此数据(需期权接口),采集成本中,优先级 P2

---

## 5. AI 预测输入变量面全景图(横轴=维度面,纵轴=当前状态 × 优先级)

| 维度面 | 已注入 | 已有未注入(零成本,优先级) | 缺需采集(优先级) | 不建议 |
|---|---|---|---|---|
| **技术面** | 指数涨跌/行业热力图/信号胜率/均线多空(当日) | ma_alignment(cross+历史)、new_high_low(52w)、ad_line 腾落线、a_up_down_ratio | — | — |
| **资金面** | 南向/机构席位/ETF汪汪队/主力/两融/北向(季度口径) | **龙虎榜 lhb_inst_net**、**行业资金流 ind_flow_sw**、解禁 unlock、IPO | 北向实时(2024 新规停更,不可得) | 大宗交易(数据少价值低) |
| **情绪面** | 恐贪/涨跌家数/QVIX/封板率/连板/炸板率 | **打板溢价 daban_premium**、封单率 seal_rate、炸板数 zb_count | PCR 认沽认购比(P2,需期权数据) | 百度指数/搜索热度(需采购) |
| **跨市场/全球面** | (任务背景称有,实查 load_data 未注入) | **美股期货 us_futures_es/nq/ym/rty**、欧亚期货、**usdcnh**、**cn_us_spread**、gold/oil/brent/silver | — | 比特币/加密(与A股关联弱,可 P2) |
| **基本面/估值面** | cn10y(收益率) | **position.json 全宽基 1y/3y/5y 百分位**、**a_div_yield**(→可算 ERP) | 盈利一致预期/景气度(需采集,中成本,P2) | 个股财务(项目只做指数/ETF级) |
| **政策/事件面** | — | — | **新闻快讯**(东财/财联社/金十,分类 policy_news 子集即政策面,P1) | — |
| **天气/季节/日历面** | — | — | **宏观数据公布日历**(CPI/PPI/PMI/社融/LPR/非农/FOMC,P1)+ 节假日/月末季末日历(硬编码低成本,P2) | 天气(量化证据弱) |
| **技术指标衍生** | 信号引擎(RSI/MACD/唐奇安/布林,在信号体系内) | — | 乖离率/动量因子(信号引擎已覆盖,无需另补) | 另建技术指标(冗余) |

### 5.1 优先级总排序(结论)
1. **P0 补「已有未注入」**(零采集成本,接入=load_data 加字段+prompt/角色域引用):
   - 估值位置面(position 1y/3y/5y + div_yield,可加 ERP 提示)
   - 跨市场面(us_futures es/nq/ym/rty + usdcnh + cn_us_spread;美股期货已证实对 A股开盘领先,跌时更强)
   - 宽度/技术面(ma_alignment cross + new_high_low 52w + ad_line + up_down_ratio)
   - 资金面(lhb_inst_net + ind_flow_sw + unlock/ipo)
   - 打板情绪(daban_premium + seal_rate + zb_count)
2. **P1 采「宏观日历 + 新闻快讯」**(需采集,低成本高价值,业界实证有效):
   - 宏观数据公布日历(次日及近 3 日,供「明日关键事件」提示 + 波动预警)
   - 新闻快讯(东财/财联社/金十,词典法情绪打分 + 分类 + 重要性过滤,参考 tradeagentcn)
3. **P1/P2 增强**:
   - 节假日/月末/季末/财报季日历(硬编码低成本;财报季+A股日历效应弱但存在)
   - 政策面 = 新闻快讯的 policy_news 子集(无需单独采集)
4. **P2/不建议**:
   - PCR(需期权持仓数据,采集成本中)
   - 盈利一致预期/景气度(中成本)
   - 大宗交易/个股新闻(与项目指数/ETF 级定位不匹配)
   - 技术指标另建(信号引擎已覆盖)

---

## 6. 候选维度字段期望(供并行数据源可行性 researcher 对照)

### 6.1 宏观数据公布日历(优先级最高)
- **需要字段**:date(YYYY-MM-DD)、release_time(北京时间 HH:MM,如 09:30/20:30)、country(中国/美国)、indicator(CPI/PPI/PMI/社融/LPR/非农/FOMC 议息/零售/工业增加值/GDP...)、importance(高/中/低)、actual/forecast/previous(实际/预期/前值,公布后回填)
- **更新时点**:中国数据 09:30(CPI/PPI)、约 20:00-21:00(社融/金融数据)、LPR 每月 20 日 09:00;美国数据 20:30/21:30(冬夏令);FOMC 每年 8 次
- **供 AI 用法**:次日是重要数据公布日 → 「明日 X 公布,公布前波动不确定性高,谨慎判断方向」
- **数据源候选**:akshare `news_economic_baidu()`(百度财经日历)、金十日历、RSSHub

### 6.2 新闻快讯(东财/财联社/金十)
- **需要字段**:title、content(或 summary)、source(东财/财联社/金十/华尔街见闻)、published_at、category(company/policy/industry/market)、sentiment_score(-1~1,词典法)、importance(high/med/low)
- **更新时点**:盘后 17:00-17:50 拉当日 17:50 前全部快讯,取重要性 top N(N≈10-20)
- **供 AI 用法**:【事件面】段注入「当日重大政策/监管/外围事件 top N」,作事件驱动提示;前端同步展示

### 6.3 节假日/日历
- **需要字段**:date、holiday_name、is_trading_day(否/是)、月末/季末标记、财报季区间
- **更新时点**:静态硬编码 + 每季度核对

---

## 7. 页面展示设计建议(用户特别问)

**总原则**:采集了就要展示(§22 N 展示位一致),展示的都要进 AI 注入(§21 公示),不展示裸采。建议分三级落位:

1. **首页 AI 预测卡片(横幅 chip 下方加 1 行)**:「📅 明日关键事件:09:30 中国 8 月 CPI」—— 仅当明日有高重要性数据/事件时显示,无则隐藏;点击进弹窗看详情。联动:该事件同时注入 AI prompt,AI 在 risk/highlights 里引用。
2. **AI 预测弹窗/详情(新增 2 个区块)**:
   - 「🗓 宏观日历」:近 3 日重要数据(日期/时间/指标/实际 vs 预期),公布后自动回填 actual 并高亮偏差
   - 「📰 今日要闻」:当日 top N 快讯(标题+来源+时间+情绪标签🟢/🔴/⚪),每条可折叠看摘要
3. **历史收盘分析页(新增「事件对照」轻区块)**:某日预测命中/未命中时,旁挂当日是否有重大事件(如 FOMC/CPI 公布),帮助用户理解「预测失败是否因突发事件」—— 这是新闻面最有价值的「事后解释」用途,比「事前预测」更稳。

**一致性联动(§22/§21)**:
- AI 注入的新闻/日历数据 = 页面展示数据 = 同一数据源,一次采集多处消费
- 若新增「新闻/宏观日历维度」,前端 AI 预测算法公示(purpose-notes.js/lab.js tooltip)必须同步声明「含新闻面/宏观日历维度」;若**短期不采集**,AI 预测须显式声明「不含新闻/舆情维度」(P1-6 已定)
- 展示位避免做「新闻情绪指数 → 必涨」式因果误导,只做「事件提示」,符合 P1-7 前视防护 + P0-3 合规

---

## 8. 调研结论(逐条带证据)

1. **现状**:AI 预测吃技术/资金/情绪三面,无新闻/宏观日历/事件面(§1.1);多角色 6 角色编排的④事件面角色未实现(ai-predict-multiagent-plan.md L91)。
2. **最高性价比 = 补「已有未注入」**(§2):~20 个指标/序列真实有值未注入(估值位置/美股期货/龙虎榜/腾落线/新高新低/解禁/行业资金流/打板溢价),零采集成本,直接兑现「把已有数据用足」。
3. **tradeagentcn 实锤**(§3):新闻面 = 多源采集(Tushare 9 源/AKShare)+ **词典法情绪打分(-1~1)+ 分类 + 重要性过滤 + 去重**,无深度模型;本项目可直接复刻该轻量方案。
4. **业界证据**:新闻情绪经 NLP 量化对 A股次日有效(华泰 15.96% 年化超额,§4.1);宏观公告日波动放大 2.5-4 倍、公告日溢价 9-11 bps(§4.2,接次日日历作事件提示逻辑成立);美股隔夜对 A股开盘领先(相关 0.45、跌时更强,§4.3,项目 us_futures 已有未注入);ERP 极值中期有效(§4.5,可作位置参考)。
5. **优先级**:P0 补已有未注入 → P1 采宏观日历+新闻快讯 → P2 节假日/政策面增强;PCR/一致预期/大宗交易不建议优先(§5.1)。
6. **页面**:首页「明日关键事件」1 行 + 弹窗「宏观日历/今日要闻」2 区块 + 历史「事件对照」,与 AI 注入同源(§7,§22/§21 联动)。

---

## 复现

### 本文外部资料 URL(WebSearch/WebFetch/GitHub raw 实拉)
1. TradingAgents-CN 仓库:https://github.com/hsliuping/TradingAgents-CN
2. TradingAgents-CN 新闻情绪分析:https://raw.githubusercontent.com/hsliuping/TradingAgents-CN/main/docs/features/news/NEWS_SENTIMENT_ANALYSIS.md
3. TradingAgents-CN 新闻同步:https://raw.githubusercontent.com/hsliuping/TradingAgents-CN/main/docs/features/news/NEWS_SYNC_FEATURE.md
4. TradingAgents-CN 新闻数据系统:https://raw.githubusercontent.com/hsliuping/TradingAgents-CN/main/docs/guides/news_data_system/README.md
5. TradingAgents-CN 分析师团队:https://raw.githubusercontent.com/hsliuping/TradingAgents-CN/main/docs/agents/v0.1.13/analysts.md
6. TradingAgents-CN 新闻报告样例:https://raw.githubusercontent.com/hsliuping/TradingAgents-CN/main/data/analysis_results/detailed/000001/2025-07-28/reports/news_report.md
7. 新闻情绪对 A股实证(华泰 HAN 等):搜索关键词「A股 新闻情绪 量化 次日预测 news sentiment NLP」—— 华泰 15.96%、情绪指数+3-5%、SSRN 2025 冗余性、低信噪比
8. 宏观公告日效应:搜索关键词「CPI 非农 FOMC 公布日效应 波动率」—— 波动率 2.5-4 倍、公告日溢价 9-11bps、预公告收益/方差比 35.53
9. 美股隔夜→A股:搜索关键词「US equity futures overnight S&P 500 A-share correlation」—— 相关 0.45、解释 2.9%、Granger 单向、跌传染更强
10. ERP/股债性价比:搜索关键词「股债性价比 风险溢价 ERP PE百分位 预测」—— 1年 79% 精度、极值后 3 个月 +12-23%、PE 百分位弱、中枢移动失效
11. 资金面因子:搜索关键词「北向资金 龙虎榜 两融 主力资金流 次日收益 预测」—— PACE 25/100、SHAP 排名、共线性陷阱

### 本项目事实源(本地验证)
- `scripts/gen_daily_brief.py`:load_data L214-518 / build_prompt L651-747 / _split_role_domains L938-988 / run_multi_agent L1987
- `data/sentiment.db` daily_metric(全量 metric_id 见 §2,抽查 20260814 最新值)
- `static-site/data/`:position.json / new_high_low.json / ma_alignment.json / ad_line.json / global-3m.json / intraday_snapshot.json(us_futures/global_realtime)
- `docs/daily-brief-optimization.md` P1-5 L234-239 / P1-6 L241-246
- `docs/ai-predict-multiagent-plan.md` 阶段三 L91
- `config/daily_brief.yaml`(multi_agent_enabled: true)

### 复现命令(本地验证「已有未注入」断言)
```bash
# 1) 确认 load_data 未注入估值/跨市场/龙虎榜等:
grep -n "position\|us_futures\|lhb\|cn_us_spread\|usdcnh\|div_yield\|ad_line\|unlock" scripts/gen_daily_brief.py
# 2) 确认数据真实有值:
sqlite3 data/sentiment.db "SELECT metric_id,value,date FROM daily_metric WHERE metric_id IN ('sh_position_1y','a_div_yield','lhb_inst_net','us_futures_es_chg','cn_us_spread','a_width_daban_premium','a_ad_line','unlock_amount') ORDER BY date DESC LIMIT 8"
# 3) 确认多角色数据域不含上述面:
sed -n '938,988p' scripts/gen_daily_brief.py
```
关键口径一句话:本报告只做方法论与现状盘点,不动基准/算法/代码;并行 researcher 负责数据源接口实测。
