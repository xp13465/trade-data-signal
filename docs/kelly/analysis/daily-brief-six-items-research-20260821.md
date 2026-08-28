# daily_brief 6 项待实施优化调研报告(2026-08-21)

> 调研 agent: researcher 角色(只读)
> 基准: v1.1.2(2026-08-18 四档 excludeSpecialBear, git tag v1.1.2@4766bfe0c)
> 前置文档: docs/daily-brief-optimization.md, docs/ai-predict-multiagent-plan.md
> 数据源: scripts/gen_daily_brief.py(L1-1500+), static-site/data/daily_brief.json, config/daily_brief.yaml

---

## #3 P1-1 周期定位/钟摆位置模板

### 现状(已有什么)
1. **恐贪指数已注入**: load_data L740-741 读 `summary.fear_greed_value/fear_greed_label`, 直接进 prompt data.summary
2. **情绪分已注入**: L1004-1008 从 `score_daily` 读 a_sentiment + 6 宽基情绪分 → data.scores
3. **冰点历史已注入**: L789 读 `overview.recent_freeze`(近 120 日冰点日期) → data.recent_freeze
4. **估值百分位已注入**: L1122-1140 读 `position.json` 8 宽基 1y/3y 百分位 → data.positions(含 label: 偏低/适中/偏高)
5. **summary_history 存在但只有 15 条**: `static-site/data/summary_history.json` 含 15 个历史条目, 每条有 fear_greed_value/sentiment_score/sh_pct/up_count/down_count/volume_amount 等字段
6. **新高新低/量能**: a_volume_ratio/a_amount_ma5/a_amount_ma20 已注入(L987-989); 新高新低数据被 guard 拦截(大面积 0 不注入)
7. **均线多空已注入**: L1154-1162 读 `ma_alignment.json`(bullish/bearish/cross)

### 缺什么
- **无周期定位模板**: prompt 中没有"当前位置=历史分位+极端提示"的结构化指令
- **30 日历史序列不够**: summary_history 只有 15 条(约 15 个交易日), 不足 30 日。但 positions 有 1y/3y 百分位, 可替代"历史分位"
- **极端值逆向提示规则未显式化**: prompt 没有"恐贪>85=亢奋降温/恐贪<15=冰点反向"的模板规则(规则版 generate_rule_brief L1238-1240 有, 但 AI 版 prompt 无)

### 实施方案
在 build_prompt 的 sys_text 中增加"周期定位模板"规则:
- 注入数据已覆盖: 恐贪值(positions 有 1y/3y 百分位) + 情绪分(scores) + 冰点(recent_freeze) + 量能(volume_ratio) + 封板率(fengban_rate) + 均线多空(ma_cross)
- 只需在 prompt 规则中新增一条: "趋势研判先做周期定位:引用恐贪值+情绪分在 1y/3y 历史分位,极端值给逆向提示(恐贪>85=情绪亢奋注意降温, 恐贪<15=冰点区域观察反转)"
- summary_history 可补充到 30 条(从 DB 读 daily_metric 近 30 日 fear_greed/sentiment), 但 positions 百分位已能覆盖"分位"需求

### 难度: 1-2h(Prompt 规则新增, 数据已全部就位)
### 优先级: P1(中, 增强趋势研判专业度)
### 阻塞项: 无

---

## #4 P1-3 公募基金持仓/行业配置注入

### 现状(已有什么)
1. **public_fund_summary.json 存在**: report_date=20260630(二季报), 含 8 个 metrics(平均仓位 96.1%/抱团度/行业集中度/净申赎率等)
2. **public_fund_sw_industry_alloc.json 存在**: 32 申万一级行业权重数据, 每行 [industry_name, total_weight, total_value, fund_count, avg_weight]
3. **public_fund_industry.json 存在**: 113 个行业(含二级), report_date=20260630
4. **public_fund_industry_rotation_ts.json 存在**: 行业轮动时序
5. **当前 gen_daily_brief.py 未读取任何 public_fund_* 数据**: load_data(L729-1178) 中无 public_fund 引用

### 缺什么
- load_data 需新增读取 public_fund_sw_industry_alloc.json(Top 加仓/减仓行业)
- prompt 需新增规则: 注入"公募基金行业配置"到 trend 段, 标注"季报滞后, 反映中期风格, 非明日方向"
- 需计算"加仓/减仓行业": 当前只有静态权重, 无环比变化(需对比上期或用 position_change_ratio 推断)

### 实施方案
1. load_data 新增: 读 `public_fund_sw_industry_alloc.json`, 取 top5 高权重行业 + top5 低权重行业
2. 如果有 `public_fund_industry_rotation_ts.json` 的时序, 可算环比变化(加仓/减仓方向)
3. prompt 规则新增: "公募基金行业配置(中期风格参考,季报滞后,非明日方向): 注入行业权重 top5/减仓 top5"
4. 前端零改动(数据在 daily_brief.json meta/text 中展示)

### 难度: 2-3h(数据读取+prompt 注入+口径标注)
### 优先级: P1(中, 补中期视角)
### 阻塞项: 无(数据已存在, 只需接入)

---

## #5 P1-4 明日关注排序分

### 现状(已有什么)
1. **signal_stats 20d 胜率已注入**: L814-829 读 signal_stats.json, 按 20d 胜率排序取 buy 系 top10 → data.signal_stats_buy_top
2. **signal_kelly_backtest.json 可用**: quadrants 含 win_rate/total_return/kelly_f/half_kelly/max_drawdown 等字段, 按象限(A-I)+周期(y1/y3/y5/y10/all)+档位(high/mid/low)组织
3. **watch_list 排序当前逻辑**: AI 输出的 watch_list 由模型自行选择, prompt 只要求"引用注入数据中真实存在的 index_id", 无结构化排序分
4. **规则版排序**: generate_rule_brief L1204-1213 用 signal_stats_buy_top 按 20d 胜率排序

### 缺什么
- **完整排序分公式未实现**: 原设计"20d 胜率 × 凯利仓位 × 一致性加分 × 近期确认"未落地
- **凯利仓位(signal_kelly_backtest)未注入 prompt**: 当前 load_data 未读 signal_kelly_backtest
- **多窗口一致性(5d/10d/20d 均>50%)未计算**: signal_stats 有 5d/10d/20d 三个窗口的 win_rate, 但未做一致性判断

### 实施方案
1. load_data 新增: 读 `signal_kelly_backtest.json`, 按 index_id 匹配 signal_stats, 注入凯利仓位(kelly_f/half_kelly) + 期望收益(mean_return)
2. 计算排序分: `sort_score = win_rate_20d * kelly_f * consistency_bonus * recency_bonus`
   - consistency_bonus: 5d/10d/20d win_rate 均>0.5 → +0.2; 两个>0.5 → +0.1
   - recency_bonus: 信号日期=当日 → +0.1
3. prompt 规则新增: "明日关注标的按 sort_score 排序, 前 5 个输出, 每个附参考胜率和凯利仓位"
4. 前端零改动(数据在 watch_list 中展示)

### 难度: 3-4h(凯利数据接入+排序分公式+prompt 规则)
### 优先级: P1(中高, 用站点独有回测数据提升关注列表质量)
### 阻塞项: 无(数据已存在, 只需接入和计算)

---

## #6 P1-5 日历效应/节假日/月末季末提示

### 现状(已有什么)
1. **app/calendar.py 已有交易日历**: 基于 akshare 的 `tool_trade_dates_hist_sina()`, 缓存到 `data/trade_dates.txt`, 支持 `is_trade_date(date)` 判断
2. **当前 gen_daily_brief.py 未使用交易日历**: load_data 无日历相关读取
3. **无节假日/月末/季末/财报季数据源**: 需硬编码或从日历推算

### 缺什么
- 无"明日是否月末/季末/长假前/财报季"的判断逻辑
- 无硬编码节假日表(2026 年 A 股休市日)
- 无财报季时间节点(一季报 4/30, 中报 8/31, 三季报 10/31, 年报 4/30)

### 实施方案
1. 在 gen_daily_brief.py 中新增 `_calendar_hint(date)` 函数:
   - 月末: date 是当月最后一个交易日(或前一个交易日)
   - 季末: 3/6/9/12 月最后一个交易日
   - 长假前: 对照硬编码节假日表(春节/国庆/五一/清明/端午/中秋), 假前最后 1-2 个交易日
   - 财报季: 4 月/8 月/10 月/4 月为财报密集期
2. load_data 新增: data["calendar_hint"] = _calendar_hint(date)
3. prompt 规则新增: "若存在 calendar_hint, 在 trend 段附加日历提示(如'明日为月末,注意资金面扰动')"
4. 前端零改动

### 难度: 1-2h(日历判断函数+硬编码节假日表+prompt 注入)
### 优先级: P2(低, 弱效应, 仅提示性)
### 阻塞项: 无(已有交易日历基础设施)

---

## #8 多角色阶段三: 事件/新闻面分析师

### 现状(已有什么)
1. **news 数据采集已上线**: `data/news_digest/2026/` 目录有每日归档(2026-08-16 起), 每条含 source/time/title/summary/important/kind 字段
2. **news 注入 prompt 已实现**: `_load_news_inject()` L564-726 支持增量续接(游标+跨日拼接), load_data L1165-1177 将 news 注入 data.news
3. **prompt 已引用 news**: sys_text L1378 "若存在 news 字段则可用于当日政策/外围事件提示(事件驱动)"
4. **daily_brief.json 当前无 news 字段**: 今日(8/20)生成的 daily_brief.json meta 无 news, 说明 news 数据未被 AI 输出结构化使用
5. **多角色版已上线 multi_agent_enabled=true**: 当前 4 角色(tech/fund/sentiment/risk), 无独立"事件面分析师"角色
6. **news 已进 risk 域**: risk 角色的数据域包含 news(从多角色编排代码推断)

### 缺什么
- 独立的"事件/新闻面分析师"角色未新增(当前 news 融入 risk 角色)
- AI 输出无结构化的"事件面"段落(如 news 驱动的方向提示)
- 无 news 关键词热度/情绪分析(当前只有原始标题+摘要)

### 评估: 是否需要独立角色?
- **不需要**: news 数据已注入 prompt, risk 角色已消费。独立角色的增量价值 = "把 news 从 risk 中分离, 让事件面分析更聚焦"
- **当前够用**: news 已在 prompt 中, AI 已可在 trend/risk 段引用新闻事件。独立角色是 P0-4 多角色框架的"阶段三", 当前 4 角色已足够
- **如需增强**: 可在现有 4 角色基础上, 将 news 从 risk 域独立出来给 sentiment 或新增 event 角色, 但成本增量(多一次 API 调用 ¥0.01)vs 收益(事件面分析更聚焦)不明显

### 实施方案(可选增强)
- **轻量版(推荐)**: 不新增角色, 在 prompt 规则中强化"news 字段使用指令": "若 news 可用, 在 trend 段引用 1-2 条重要新闻事件作为方向/风险依据"
- **完整版**: 新增第 5 角色"事件面分析师", 只喂 news+upcoming, 输出 1 条事件驱动论据, 参与研究员多空辩论

### 难度: 轻量版 0.5h(强化 prompt 规则) / 完整版 2-3h(新增角色+编排)
### 优先级: P2(低, 当前 news 已注入 prompt, 独立角色增量有限)
### 阻塞项: 无

---

## #9 P1-11 reasoner(R1)深度辩论增强

### 现状(已有什么)
1. **配置已支持**: daily_brief.yaml L29 `researcher_model: deepseek-chat`, gen_daily_brief.py L168 `cfg.setdefault("researcher_model", "deepseek-chat")`
2. **多角色编排已上线**: multi_agent_enabled=true, 4 角色并行→研究员多空辩论→主编组装
3. **研究员当前用 deepseek-chat(V3)**: 未启用 deepseek-reasoner(R1)
4. **call_deepseek 支持双 provider**: official(DeepSeek 官方) + ark(火山方舟), thinking 配置已就绪(L1423-1447)
5. **reasoner 成本**: 约 3-5 倍于 chat, 年成本 ¥50-70(设计文档 §1.5.5 估算)

### 缺什么
- 研究员角色的 model 选择逻辑未实现: 当前 call_deepseek 对所有角色用同一 model, 未按角色切换
- 无"reasoner 可选开关": 需要 `researcher_use_reasoner: false` 配置项
- 无 reasoner 超时保护: R1 推理时间更长, 需独立超时配置

### 实施方案
1. 在多角色编排代码中, 研究员角色(⑤)的 call_deepseek 调用传入 `model=cfg.researcher_model`
2. daily_brief.yaml 新增: `researcher_use_reasoner: false`(默认关, 验证质量后再开)
3. 当 researcher_use_reasoner=true 时, 研究员 model 切为 `deepseek-reasoner`
4. 新增 reasoner 专用超时: `researcher_timeout_seconds: 120`(比普通角色 90s 更长)
5. 成本监控: 在 cost_log 中标注 reasoner 调用, 便于追踪

### 难度: 1-2h(配置项+model 切换逻辑+超时保护)
### 优先级: P1(中, 可选增强, 默认关不影响现有功能)
### 阻塞项: 无(基础设施已就绪, 只需加开关和切换逻辑)

---

## 优先级排序(综合价值/难度/依赖)

| 排序 | 项目 | 难度 | 价值 | 依赖 | 建议 |
|------|------|------|------|------|------|
| 1 | #3 周期定位/钟摆位置 | 1-2h | 中高 | 无 | 先做, 数据已就位, 只改 prompt |
| 2 | #5 明日关注排序分 | 3-4h | 高 | 无 | 核心价值(站点独有回测数据), 数据已就位 |
| 3 | #4 公募基金行业配置 | 2-3h | 中 | 无 | 补中期视角, 数据已就位 |
| 4 | #9 reasoner 深度辩论 | 1-2h | 中 | 无 | 可选增强, 默认关不影响 |
| 5 | #6 日历效应/节假日 | 1-2h | 低 | 无 | 弱效应, 仅提示性 |
| 6 | #8 事件/新闻面分析师 | 0.5-3h | 低 | 无 | 当前 news 已注入, 独立角色增量有限 |

### 阻塞项汇总
- **零阻塞**: 全部 6 项数据源均已就位, 无外部依赖
- **#3/#5/#4**: 只需 load_data 新增读取 + prompt 规则新增, 前端零改动
- #9 只需配置开关 + model 切换逻辑
- #6 只需日历判断函数 + 硬编码节假日表
- #8 当前已够用, 增强可选

### 实施建议
1. **第一批(最快见效)**: #3(周期定位) + #9(reasoner 开关) → 2-4h, 数据/配置已就位
2. **第二批(核心价值)**: #5(排序分) + #4(公募行业) → 5-7h, 数据已就位需计算逻辑
3. **第三批(锦上添花)**: #6(日历) + #8(事件面增强) → 1.5-5h, 可选

---

> 调研完成。本报告只读不改, 所有结论带证据点(文件:行号/数据值)。
> 复现: 数据源均在 static-site/data/ 和 sentiment.db, 可用 `python3 -c "import json; print(json.load(open('文件'))['字段'])"` 验证。
