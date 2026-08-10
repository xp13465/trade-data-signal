# AI 预测多角色协作式改造方案(2026-08-11 排查产出)

> 背景:用户看 deepseek API 请求日志后反馈——"没喂多少数据、没做多角色分析辩论、结果精简,和预期的 AI 预测设计和流程不一致"(原话:"ai预测内容这么少么。不是多agent 辩论了的么")。
> 本文件回答三件事:①当前实际是什么(设计 vs 实施差距) ②为什么内容少 ③多角色协作式改造方案(架构+阶段+成本)。
> 前置设计文档:`docs/daily-brief-optimization.md` §1.5 + P0-4/P1-11(2026-08-10 调研,340 行);`docs/daily-brief-research.md`(2026-08-04 调研,1036 行)。本文件为实施方案落档,与 P0-4 对齐。

## 一、现状(实施 vs 设计差距,逐项)

### 1.1 当前实施 = 单 prompt 一次调用(第一阶段,已上线)
- 生成脚本 `scripts/gen_daily_brief.py`(933 行,commit 8b7589c7b):
  - **单 agent、单次 deepseek-chat 调用**:`build_prompt()`(L442)构造 system(角色="专业金融分析师")+ user(注入 JSON 数据),`call_deepseek()`(L487)一次返回完整 JSON。
  - 模型 `deepseek-chat`(config/daily_brief.yaml `model`),temperature 0.4,timeout 60s,重试 2 次,429 退避。
  - 输出结构固定:`direction(up/down/flat) + watch_list(≤5) + risk_items(≤5) + text{review/trend/watch/risk}`。
  - **prompt 明确指令"总长 ≤300 字"**(L442 sys_text 规则 5),这就是"内容少"的直接原因——**精简是设计使然,不是 bug**。
- 数据喂入(load_data L196,实际 5364 prompt_tokens,20260810 实测):summary 20+ 字段、signals_today 20 条、name_map、recent_freeze、industry_heatmap_top 10、alert high/low 命中维度、signal_stats_buy_top 10、futures_acc_trend_tail、futures_acc_conclusion、funds 20 个 metric、north_quarterly、scores 8、indices 8。
  - 注:数据量其实不少(全量注入),但**全量杂烩 + 单次输出 4 段短文**,每维度浅尝辄止 = 用户观感"没喂多少/结果精简"。
- 机检回测已做(设计 P0-1 已落地):meta 断言 + 次日 hit 回填 + 30/90 命中率;合规指令词黑名单(P0-3 已落地);期货持仓+北向口径修正(P0-2 已落地)。

### 1.2 设计期望 = 多角色协作式(TradingAgents-CN 风格,P0-4,用户 2026-08-10 定方向)
- `docs/daily-brief-optimization.md` P0-4:推荐方案 A"轻量借鉴"——自研 6 角色子 prompt 编排(①技术面 ②资金面 ③情绪面 ④风控 ⑤研究员多空融合 ⑥主编),每角色只喂自己数据域(缩小数据域控制幻觉),角色可并行调用,研究员做"多头 vs 空头"对抗收敛,主编组装输出;不做交易员/组合经理(合规红线,输出只到"关注/观察/风险")。
- P1-11:研究员角色可选 deepseek-reasoner(R1)做深度辩论(论据互相反驳+回应后收敛)。
- 成本估算(设计 §1.5.5):6 次调用,单日 ~¥0.05,年 ~¥12-70。

### 1.3 差距清单(设计要什么 / 实际差在哪)
| # | 设计(P0-4) | 实际(第一阶段) | 差距 |
|---|---|---|---|
| 1 | 多角色视角(技术/资金/情绪/风控/研究员) | 单"专业金融分析师"一次输出 | **未实施**(核心差距) |
| 2 | 每角色独立数据域注入(缩小数据域控幻觉) | 全量数据一次注入 | 未实施 |
| 3 | 多空辩论对抗 + 收敛到倾向 | 单方向判断,无多空对抗展示 | 未实施 |
| 4 | 风控独立角色出风险清单+最坏情景 | risk_items 由主 prompt 顺带生成 | 未实施 |
| 5 | 输出可溯源(每角色论据+数据引用) | 终稿直接输出,无中间论据展示 | 未实施 |
| 6 | 输出篇幅=分角色论据+融合,内容充实 | 指令"总长≤300字",4 段短文 | 实施按设计(精简),但用户预期多角色版内容更充实 |

## 二、为什么 810 预测内容少(用户问题3逐条)

1. **"内容这么少"** = prompt 规则 5 明确要求"总长 ≤300 字"(review 约80/trend 约60/watch 约80/risk 约60)。单 prompt 版刻意精简,非生成失败。
2. **"没喂多少数据"** = 观感问题:数据其实喂了 5364 tokens(全量注入),但**一次性全量注入**导致模型每维度只能浅尝辄止,输出只挑几个点写,看起来像"没喂"。多角色版每角色只喂自己的数据域,反而每维度能深挖。
3. **"没做多角色分析辩论"** = 对。第一阶段(8b7589c7b)只实现了"单 prompt 主链路"(P0-1 机检/P0-2 口径/P0-3 合规 都做了,**P0-4 多角色协作式框架是明确未实施项**)。用户 2026-08-10 定方向引入 TradingAgents-CN,调研已落档(docs/daily-brief-optimization.md P0-4),但实施排期未到。
4. **watch_list 只有 5 条 + 固定格式** = `parse_ai_output`(L544)强制数据锚定:watch_list 只保留 `injected_ids`(signals_today ∪ signal_stats_buy_top)里真实存在的 index_id,防 AI 编造(设计 P1-8 已落地)。所以关注标的只能是"当日有信号/有 20 日胜率统计"的指数。

## 二.5 信号来源分类修复(2026-08-11 用户反馈:AI 预测"卖信号 5 个"实为情绪分模拟信号)
> 用户原话:AI 预测里说"08-10 卖信号 5 个",但实际真正可交易的卖信号是 0 个,那 5 个是情绪分的卖信号。要求规范区分"真是指数走势的信号"和"情绪上的模拟信号"。

### 2.5.1 证据链(810 实查,全部已验证)
1. `app/compute/market_summary.py` L203-211:summary.json `sell_count` = `SELECT COUNT(*) FROM signal_daily WHERE date=? AND signal='sell'`——**无 `s.%` 过滤**,情绪分模拟信号混入。
2. `app/queries.py` L535:首页信号列表(signals_today)用的是 `index_id NOT LIKE 's.%'`(2026-07-20 方案B 已过滤 s.*)——**两处口径不一致**(queries 过滤了,market_summary 没过滤)。
3. DB 实查 `signal_daily` date=20260810 signal='sell' **共 5 条,全部是 s.***(s.fear_greed / s.sentiment_csi1000 / s.sentiment_csi500 / s.sentiment_hs300 / s.sentiment_sz50);buy=0、buy_aux=0 → summary.json `sell_count=5, buy_count=0`。
4. `scripts/gen_daily_brief.py` L215-216 `load_data()` 把 `summary.buy_count(0)/sell_count(5)` 原样注入 deepseek prompt;`build_prompt()` L442 sys_text **没有任何"区分真实信号 vs 情绪分模拟信号"的规则**。
5. DeepSeek 输出(线上 daily_brief.json 实查)risk_items[1]="卖点信号5个，无买点，短期或有压力" + text.risk "卖点信号5个"——即把 5 个情绪分卖信号当真实卖信号表述。
6. 前端:AI 弹窗 `_dailyBriefItemHtml`(L18274)逐字展示 risk_items;横幅 chip `app.js` L6241-6242 `买${s.buy_count} 卖${s.sell_count}` 用同一 summary 计数——**首页横幅 chip 也显示"买0 卖5",同样口径问题**。

### 2.5.2 修复方案(用户要求:区分真实可交易信号 vs 情绪模拟信号)
- **A. summary.json 口径分层(根因,后端 C 级)** `app/compute/market_summary.py`:sell_count/buy_count SQL 加 `AND index_id NOT LIKE 's.%'`(只算真实可交易指数信号,与 queries.py L535 方案B 对齐),并**新增** `sell_sentiment_count` / `buy_sentiment_count`(统计 s.* 情绪分模拟信号数),summary.json 输出两类计数,字段语义明确。注意:改 market_summary.py 是数据产物改动,需重跑 summary.json + 同步 static-site/data + R2(§18 数据产物三步)+ reviewer。
- **B. prompt 注入+规则修正(gen_daily_brief.py L215-216 + build_prompt L442)**:
  - 注入字段改名:`summary.tradable_sell_count`(真实)/ `summary.sentiment_sell_count`(模拟),或保留原字段但加 `funds_note` 式口径说明;
  - sys_text 加规则:"引用卖/买信号数量时,必须区分:真实指数可交易信号(非 s.*)与情绪分模拟信号(s.* 前缀,0-100 衍生指标非可交易标的)。情绪分信号必须标注'情绪分信号',不得表述为'卖信号 N 个'。"(与站点 2026-07-20 方案B 的语义一致);
  - watch_list 数据锚定 `injected_ids` 本就来自 signals_today(已过滤 s.*),保持。
- **C. 前端展示(可选,防御性)**:横幅 chip L6241 改读真实计数(若 summary 提供);AI 弹窗 risk_items 由源端(A/B)修正后自然修正,前端可不改。
- **D. 多角色版天然根治(P0-4 角色分工)**:①技术面/资金面角色只喂真实指数信号(signals_today 已过滤 s.* + signal_stats),③情绪面角色单独喂 s.* 情绪分并在输出中**明确标注"情绪分信号(模拟,非可交易)"**,⑤研究员融合时对"真实信号论据 vs 情绪警示论据"分类呈现——每角色数据域分离,信号类型天然区分,不会再把情绪警示当真实卖信号。

### 2.5.3 验收口径
1. summary.json 含真实/情绪两类计数字段,真实 sell_count 与 overview signals_today 的 s.* 过滤口径一致(810 应为 0);
2. 重新生成 810 daily_brief,risk_items/text.risk 不再出现"卖点信号5个",情绪信号表述带"情绪分"标注;
3. 横幅 chip、AI 弹窗、3 站线上一致;
4. 多角色版技术/情绪角色输出分别标注信号来源类型。

## 三、多角色协作式改造方案(实施建议,对齐 P0-4)

### 3.1 总体架构(轻量借鉴,不自引 TradingAgents 依赖)
```
                              ┌─ ①技术面分析师(并行) ─┐
                              ├─ ②资金面分析师(并行) ─┤
  读数据(load_data 拆域) ────► ├─ ③情绪面分析师(并行) ─┼─► ⑤研究员(多空辩论,串行) ─► ⑥主编(组装+meta+合规) ─► daily_brief.json
                              ├─ ④风控(并行) ─────────┘       (R1 可选深度对抗)
                              └─ ④事件面(待数据采集后加)
```
- 角色与输入(每角色只喂自己的数据域,引用已有 load_data 拆分):
  - ①技术面:`ma_alignment` / `new_high_low` / `volume_ratio` / `signals_today` / `signal_stats`(对应信号胜率)→ 1 条趋势论据 + 1 条技术信号
  - ②资金面:`a_fund_main` / `a_fund_margin` / `futures_acc_trend`(机构净多变化) / `hk_south` / `a_fund_north_quarterly`(季度口径)→ 1 条资金面论据
  - ③情绪面:`fear_greed` / `a_sentiment` / 6 宽基情绪 / `recent_freeze` / `a_width_fengban_rate` / `a_width_max_lianban` / rotation → 1 条情绪位置论据 + 极端值逆向提示
  - ④风控:`alert.high/low dims` / `a_qvix` / 量价背离 → 3 条风险点 + 1 句最坏情景
  - ⑤研究员(多空融合):输入四角色论据 → 输出「多头论据 / 空头论据 / 倾向判断(涨/跌/震荡)+ 置信度」,倾向必须同时给支撑与风险,允许"震荡/看不清"
  - ⑥主编:组装 4 段输出 + meta 断言(direction/watch_list/risk_items)+ 指令词黑名单校验(复用 P0-3)
- 模型:主角色(①②③④)用 `deepseek-chat`(V3,稳定便宜);研究员⑤可选 `deepseek-reasoner`(R1,深度对抗,config 开关默认关,质量不满意再开)= P1-11。
- 调用编排:本地 Python 脚本,①②③④ 互不依赖**并行**(asyncio/concurrent.futures),⑤⑥ 串行;总时延目标 <2min,超时降级到现有单 prompt 链路(保底不破)。
- 输出:沿用现有 `daily_brief.json` / `daily_brief_history.json` 结构与前端渲染(零前端改动),可选在 meta 加 `debate` 字段存多空论据供前端"展开看辩论过程"(P1 可选)。

### 3.2 分阶段实施
- **阶段一(4-6h,对齐 P0-4,核心价值)**:新增 `scripts/gen_daily_brief_multi.py`(或改造 gen_daily_brief.py 加 `--multi` 开关),实现 6 角色并行编排 + 融合 + 主编组装;角色 prompt 设计参照设计文档 §1.5.4;保留现有单 prompt 链作降级兜底;`daily_brief.yaml` 加 `multi_agent_enabled: false` 开关(默认关,验证后开);§9 无前端改动(data 结构不变);自验取一个 signal 逐段对比单/多版输出。
- **阶段二(P1-11,可选增强)**:研究员角色切 `deepseek-reasoner` 深度辩论,`daily_brief.yaml` 加 `researcher_model: deepseek-chat|deepseek-reasoner` 开关;成本监控(config 已有 monthly_warn_yuan)。
- **阶段三(事件面,待数据采集)**:④事件/新闻面分析师,输入当日快讯摘要(需新增采集,非本次范围)。

### 3.3 API 成本估算(设计 §1.5.5 实测口径)
- 每角色 input ~2-3k token + output ~300 token;5 角色 + 1 融合 ≈ 6 次调用;单日 input ~15-18k ≈ ¥0.03-0.04 + output ~1.8-2k ≈ ¥0.015 → **单日约 ¥0.05,年(250 交易日)约 ¥12-15**;reasoner 版贵 3-5 倍,年 ¥50-70 仍可接受。
- 对比现状:单 prompt 单日 ~¥0.015(20260810 实测 ¥0.0151),多角色版约 3 倍,可接受。

### 3.4 验收口径(实施 agent 自验必含)
1. 单/多版输出结构均合法 JSON,字段与现有 daily_brief.json 一致;
2. 6 角色降级链完整:任一角色失败 → 该角色用现有全量数据兜底或整体降级单 prompt;
3. 合规:多角色输出过 P0-3 指令词黑名单(主编校验);
4. 数据锚定:watch_list 仍只保留 injected_ids;
5. 成本:跑一次记 cost log,确认 ~¥0.05 量级;
6. 前端零改动(数据结构不变),3 站线上验证 daily_brief.json 新内容。

## 四、与现状配套的已知待办(一并提醒)
- P0-4 已落档设计(docs/daily-brief-optimization.md),本文件是其实施方案;
- daily_brief.yaml `schedule_enabled: false`(默认不自动跑,主控/用户手动跑)——多角色版上线前维持手动触发,验证质量后再开调度;
- 多角色版上线后 §21 算法公示需同步(purpose-notes.js / AI 预测弹窗算法说明文案)。
