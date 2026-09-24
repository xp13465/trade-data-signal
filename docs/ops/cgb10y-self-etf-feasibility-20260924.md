# cgb_10y_etf(10年国债ETF)买信号「配上 vs 信号层不发」可行性调研(2026-09-24)

> 用户拍板: 先调研「有没有真能跟踪 10 年国债的场内 ETF」, 查证后再决定「配上」还是「信号层不发」。
> 本报告: 结论 + 证据(文件:行号/命令输出/数据值), 只给证据与建议, 不拍板。

## 0. 结论先行

1. **真能跟踪 10 年国债的场内 ETF 存在**: sh511260「十年国债ETF国泰」(国泰上证10年期国债交易型开放式指数证券投资基金), 跟踪标的=上证10年期国债指数, 2017-08-04 成立, 规模 198.80 亿元(2026-06-30), 今日(9-24)仍在交易。**用户拍板的问题答案: 有标的, 且系统里 cgb_10y_etf 这个"指数"本来就是这只 ETF 的净值序列——不是"指数冒充 ETF", 是"ETF 净值当指数"。**
2. **但「配上」(进交易计划/回测宇宙)的数据代价已由 2026-08-14 穷举回测证明: 债类(cgb_10y_etf)买信号 415 笔在全部 9 种卖出模式下净亏损**(-3,261 ~ -10,859 元), 胜率 20.7%~43.9%, 均单笔 -0.08%~-0.26% = 低波动资产短持有窗口的费耗水平。** 纳入后全表各模式总净利全部下降(如 A 模式 469,977→462,571)。
3. 「计划天天空」**不是事故, 是设计**: self-ETF 是「展示层兜底」, 入样宇宙判定(要求 track_score 非 None)把 self-ETF 判为未入样, 三处"说法不一致"实为三层语义不同。现行权威口径=config/universe_rules.yaml(§23.6 单一事实源)。
4. **推荐: 不配**(不进交易计划/不回测宇宙), 依据=回测数据 + 低波动资产短持范式不匹配; 但可做两个低成本改进消除"天天信号+空空计划"的困惑观感(见 §6)。

## 1. sh511260 是什么(上线查证证据)

| 项 | 值 | 证据 |
|---|---|---|
| 基金全称 | 国泰上证10年期国债交易型开放式指数证券投资基金 | 东财 F10 页面(2026-09-24 抓取, /tmp/f10_511260.html) |
| 简称/代码 | 十年国债ETF国泰 / 511260 | 天天基金 pingzhongdata/511260.js fS_name="十年国债ETF国泰" |
| 跟踪标的 | **上证10年期国债指数**(业绩比较基准=该指数收益率) | 东财 F10「跟踪标的 上证10年期国债指数」字段 |
| 成立日期 | 2017-08-04(发行 2017-07-17, 初始 2.186 亿份) | 东财 F10「成立日期/规模」字段 |
| 净资产规模 | 198.80 亿元(2026-06-30), 份额 1.4741 亿份 | 东财 F10「净资产规模」字段 |
| 管理人/托管 | 国泰基金 / 建设银行 | 东财 F10 |
| 今日行情 | 9-24 收盘 134.865(腾讯行情 qt.gtimg.cn/q=sh511260, 20260924161500 时间戳, 实时在交易) | 腾讯行情接口 |

**与 cgb_10y_etf 指数的关系**: cgb_10y_etf 不是独立指数, 它就是 sh511260 的净值序列——
- config/indicators.yaml:335: `{id: cgb_10y_etf, name: 10年国债ETF, market: global, func: fund_etf_hist_sina, symbol: "sh511260", enabled: true}`
- 数据实测: sentiment.db index_daily 中 cgb_10y_etf 2,201 行(2017-08-24 ~ 2026-09-17), 起步价 99.401(2017-08-24), 最新 135.97(9-17), 起点≈ETF 成立后首个净值日, 走势=ETF 净值, **就是 511260 自身**。
- match_method="self" 语义(queries.py:367-395 _self_etf_for docstring): 「index 本身就是 ETF(board_etf_map 无此 key)→ 直接用 symbol 剥 sh/sz/bj 前缀作 ETF 代码注入, match_method="self" 标识 index 即 ETF 自身」。实现=app/queries.py:378-391: func==fund_etf_hist_sina 且有 symbol → code=剥前缀 → 返回 {"etfs":[{code,name,match_method:"self",amount?}]}。
- amount 来源=index_daily.amount 最新行(queries.py:385-389, 注释示例 cgb_10y_etf 39.76 亿)。
## 2. self-ETF 机制「哪层认、哪层不认」对照表

根因一句话: **`_self_etf_for` 注入的 ETF 条目只有 {code, name, match_method, amount}, 没有 track_score; 全链路「入样宇宙」判定一律要求 `any(track_score is not None)`, 所以 self-ETF 是「展示层兜底」而非「宇宙层入样」。**

| 层 | 位置 | 行为 | 认不认 self-ETF |
|---|---|---|---|
| 注入机制 | app/queries.py:367-395 _self_etf_for | func=fund_etf_hist_sina 的指数 → 注入自身 ETF 条目(无 track_score) | 注入(展示兜底) |
| 首页走势卡/信号列表展示 | queries.py:1243 / 1973 / 2123 三处调用 | etfs 数组里有 511260(self), 带 etf_close/etf_since_return(实测 overview.json 有值) | **显示认** |
| 首页入样判定 | queries.py:1254 `_bt_in_universe = any(_e.get("track_score") is not None for _e in etfs)` | self-ETF 无 ts → False | **不认** |
| 首页 AI 建议 | static-site/app.js:6413 `it._bt_in_universe !== false` 才参与 | 未入样不参与 AI 建议 | **不认** |
| 首页未入样本标注 | app.js:6635 / 6258 / 3022-3024 | _bt_in_universe===false 买信号=删除线+灰显+「未入样本」标注; band_hold/sell 等非买豁免 | 标注为未入样本 |
| 邮件提醒 | check_signals.py:715/730 | 未入样本买信号归「AI过滤」类(提醒不推荐, 不入 AI 建议) | **不认** |
| 凯利回测主流程 | signal_kelly_backtest.py _build_best_etf 只读 board_etf_map.json | cgb 无 key → 债类信号 skipped_no_etf 跳过(trades 实测 cgb 出现 0 次) | **不认** |
| 回测 probe(研究) | signal_kelly_backtest_bond.py:274+ with_self_etf=True | 纳入 self-ETF 跑「纳入 vs 不纳入」对比, 独立产物不动现网 | 认(仅研究) |
| **交易计划生成** | **nextday_plan_generator.py:531 → 686-687** | _bt_in_universe(无 ts)→ False → 「未入样宇宙(无跟踪 ETF track_score)」→ continue 排除 | **不认**(计划空) |
| 宇宙对称校验 | check_universe_alignment.py:11-13 断言1注释 | 「self-ETF 注入无 track_score → 重算=False, 与注入值一致, 天然通过」 | 确认不认(设计内) |

**计划生成器不认的具体代码点**: scripts/nextday_plan_generator.py:524(_self_etf_for 注入)→ 531(_bt_in_universe=any(track_score is not None) → False)→ 686-687(未入样宇宙 → continue 剔除)。

**线上实锤**: curl ss.fx8.store/data/nextday_plan.json → {"date": "20260923", "empty": true}(9-23 空计划)。本地 data/nextday_plan.json 停在 9-11(非空, 恒生科技 513260), 9-12 后无新计划(本地不跑定时任务, 正常为旧产物)。

## 3. build_board_etf_map.py:395「无精准跨境ETF, 不列入」的由来与关系

- **由来**: 版本溯源 commit 9e001eb38(2026-08-09)「feat: 全球指数走势卡补定住/订阅/相关ETF(走势图问题2)」引入 GLOBAL_INDEX_KW 与注释「# cgb_idx/cgb_10y_etf/cgb_10y_future 国债类: 无精准跨境ETF, 不列入(留空)」+ 上文「无跨境 ETF 的指数(ftse100/kospi/cgb_*)留空, 前端显示"无ETF"」。
- **语义**: 该函数是「全球指数 → 跨境 ETF 名称匹配」(GLOBAL_INDEX_KW 是给境外指数找跨境 ETF 的), cgb 类国债没有跨境 ETF 可配, 故不列入。**它管的是「board_etf_map 宇宙构建」这一层, 与 self-ETF 展示兜底不冲突**(self 兜底在 queries.py 渲染层, 不走 board_etf_map)。
- **现行权威口径 = config/universe_rules.yaml**(§23.6 单一事实源, 机器校验挂 deploy 链):
  - L33-36: 债类 match: "cgb_" → mode: absent →「board_etf_map 无此 key(留空), 由 self-ETF 兜底(仅 cgb_10y_etf)单独展示」
  - L117-121: self_etf_exception: cgb_10y_etf: symbol sh511260, match_method self, note: "自我ETF唯一例外: 债类 cgb_10y_etf 是基金本身, 不入 board_etf_map, 由首页 self-ETF 兜底单独展示"
  - L12-13 inclusion_dependency: 入样必须 board_etf_map 有 key **且** track_score 非 None。
- **三处"说法不一致"的真相**: 是三层语义(宇宙构建层 vs 展示兜底层 vs 例外登记层), 不矛盾; 现行权威=universe_rules.yaml。

## 4. 配上会有什么代价

### 4a 前视检查(§5.1⑥)
- self-ETF 价格=index_daily.close(signal_kelly_backtest_bond.py:64-80 _load_index_close_price, 与首页 _enrich_etfs_since_return 同源)。
- 成交价口径=主回测同内核(signal_kelly_backtest.py:894-896): 信号日 d 取 **d 的下一交易日** 价格(next_date/dates[i+1])作买入价 → T 日信号、T+1 价买入, **无前视**(与全表一致)。
- 结论: match_method=self 用指数自身价格当 ETF 价格不引入前视; 低波动资产本身收益薄是另一回事(见 4c)。

### 4b 当前测试基准与版本
- 「配上」= 让 self-ETF 通过 _bt_in_universe 判定(给它 track_score 语义或改判定)→ **动 AI 推荐 / 降亏过滤核心实用功能**(AI 建议人口、未入样本标注、计划人口全部变化)→ 按 §5.4⑥ **必须发中间版本(v1.1.7 → v1.1.8)+ 更新基准定义(memory test-baseline-v112-anchor)+ 前端默认值 + §21 公示 + README + 全部键集登记点机检**(18 处全量表见 docs/kelly/analysis/v115-new14-baseline-alignment-audit.md)。

### 4c 回测代价(数据证据, 2026-08-14 穷举 probe)
来源: docs/kelly/analysis/kelly-bond-inclusion-probe.md(报告本体已落档, 复现命令在报告§5)。
- 债类(cgb_10y_etf)买信号 415 笔, **9 种卖出模式全净亏** -3,261 ~ -10,859 元, 胜率 20.7%~43.9%, 均单笔 -0.08%~-0.26%(费耗水平)。
- 追关注 buy_special 是最大亏损源(235 条占 57%, 全模式净亏 -1,829 ~ -5,613, 胜率 21.7%~30.6%)。
- 纳入后全表各模式总净利**全部下降**(A 469,977→462,571; E 131,045→120,186)。
- band_hold(持有状态)当买信号纳入更差(1,579 笔全净亏 -12,865~-36,274)= 过度交易。
- 归因: 十年国债 ETF 日波动 ~0.01% 量级, 短持有/止盈窗口收益无法覆盖约 0.3% 往返费率。
- 诚实标注: 该报告基于 2026-08-14 数据(当时基准 v1.1.0 前后), 当前基准=v1.1.7(8-26); 宇宙规则(cgb_ absent + self 兜底展示)至今未变, 债类低波动/费耗特征未变, 结论方向稳健; 严格口径下若用户仍想试「配」, 应先重跑(复现命令见报告§5)再切默认(§5 实施联动)。

### 4d §23.6 入样宇宙五项(现状 vs 配上)
| 项 | 现状 | 配上要动 |
|---|---|---|
| ① 显式声明 | ✓ universe_rules.yaml(cgb_ absent + self_etf_exception=cgb_10y_etf) | yaml 改: self_etf_exception 增 in_universe 语义 |
| ② 强制公示 | ✓ 前端 tooltip 已写明「未入样宇宙信号(债类cgb_*/...)=删除线+灰显+未入样本」(app.js:3022-3024) | 公示文案同步改(债类变为可入样/AI 建议可推荐) |
| ③ 首页1:1遵从 | ✓ queries.py:1254 与前端 app.js:6413 同源 | 判定层 + 前端同步改 |
| ④ 对称校验 | ✓ check_universe_alignment.py 4 断言挂 deploy 链(断言1 现为「天然通过」) | 断言1 调整(self-ETF 现应有入样语义) |
| ⑤ 变更联动 | ✓ yaml 头注释列 8 步联动 | 重跑 board_etf_map(若走映射)/回测/export/§22 三步同步 |

### 4e 数据新鲜度风险(本次新发现)
- index_daily cgb_10y_etf 最新 **2026-09-17**, 缺 9-18 / 9-21 / 9-22 / 9-23 四交易日(9-24 盘中腾讯价 134.865 vs 库内 9-17 价 135.97, 已差 -0.8%)。
- 采集配置 app/collector/index_backfill.py:426 ("cgb_10y_etf", "sh511260", False) — require_today=False(国债源 T+1 有时延), 宽阈值不告警 → 停更无感知。
- **配上之前必须先修数据新鲜度(补采 + 严阈值告警)**, 否则交易计划会推荐「行情已走掉 4 天」的标的。
## 5. 不配的代价(现状实际影响, 已取证)

| 展示位 | 现状表现 | 用户观感 |
|---|---|---|
| 首页信号列表 | cgb_10y_etf band_hold 每天 1 条(持有状态, 正常全亮显示, 带 511260 self-ETF); 买信号(buy_special 等, 9-16 一条)灰显+删除线+「未入样本」标注 | 「信号天天发」= band_hold 天天发(band_hold 语义是持仓状态非买点, 不进计划是正常) |
| 首页 AI 建议 | 债类不参与(AI 建议只在入样宇宙内选) | 看不到债类建议 |
| 邮件 | 未入样本买信号归「AI过滤」提醒类(标注意思是不推荐) | 收到信号但不推荐买 |
| 计划页 | 线上 9-23 {"date":"20260923","empty":true} 空计划; 本地 9-11 后无新计划 | 「天天有信号却空空计划」的困惑 |
| 数据一致性 | 全链路一致(展示有 ETF 但标注未入样本), §22 无冲突 | — |

**不配的真实代价 = 观感噪音**, 不是数据错误: 空计划本身是正确行为(当日无入样可买信号时计划就该空)。

## 6. 建议(数据说话, 供用户拍板)

### 主推: 不配(不把债类买信号纳入交易计划/回测宇宙)
- 标的存在性: ✓(sh511260, 已查证)。
- 但数据: 债类 415 笔 9 模式全净亏(费耗), 纳入拖累全表; 低波动资产短持有范式与信号体系(止盈/持有天数窗口)不匹配; buy_special 追涨上轨突破在低波动资产胜率 21.7%~30.6%。
- 「有真标的」≠「该交易」——这就是拍板问题「配上 or 信号层不发」的数据答案: **配上的收益为负, 不配无数据损失**。

### 配套改进(低成本、A 级, 消除观感噪音, 可选让用户挑)
1. **空计划文案明确化**: 计划页/页面上把「空计划」写清是「当日无符合交易计划的入样买信号」(行为正确, 非故障), 避免用户误以为系统坏了。(纯文案)
2. **信号层不发(用户拍板选项)**: 若嫌债类信号噪音, cgb_10y_etf 的 buy_special/buy_backup 买信号可评估在信号生成层停发(数据依据: buy_special 235 笔全模式净亏, 低波动资产上无操作价值)——这是 B 级改动(signals.py 生成逻辑), 需用户拍板后另派实施。

### 若用户仍要「配」(完整落地清单, 一步到位)
1. 先修数据: 补采 index_daily cgb_10y_etf 9-18 起 4 交易日 + backfill 阈值收紧(require_today=True 或独立告警);
2. 先重跑回测: signal_kelly_backtest_bond.py(当前基准口径)确认债类是否仍拖累——**数据定稿再切默认, 不作预设**;
3. 判定层改(不建 board_etf_map key): universe_rules.yaml self_etf_exception 增入样语义 → queries.py _bt_in_universe 判定读该配置(all 调用点: overview / global_market / index_detail / plan generator 同源) → 前端 app.js AI 建议/未入样本逻辑同步;
4. §23.6 五项全动(见 4d 表): yaml + 公示文案(purpose-notes.js/lab.js/app.js tooltip)+ check_universe_alignment 断言1 调整 + 重跑回测/export;
5. 发中间版本 v1.1.8(§5.4⑥): 同步基准定义 memory test-baseline-v112-anchor + 前端默认值 + README + 18 处键集登记点机检 PASS;
6. §22 三步同步 + §0 上线验证(线上 JSON 字段 + 前端展示)。

## 7. 诚实标注

- **已证实**: 511260 真实名称/跟踪标的/成立日/规模(东财 F10 官方页面 2026-09-24 抓取); 今日仍在交易(腾讯行情时间戳); cgb_10y_etf=sh511260 净值序列(index_daily 2017-08-24 起 2,201 行); 线上 9-23 计划 empty:true; overview 中 cgb 信号 116 条全 _bt_in_universe=false 且 etfs 有 self 值; board_etf_map.json(两棵树)均无 cgb 任何 key; signal_kelly_trades.json cgb 出现 0 次。
- **推断**(附依据): overfit_monitor.py:237 注释「cgb_10y_etf 是自我ETF唯一例外…board_etf_map 有 key 且有 ETF 时 ts 非 None」与实际不符(实际无 key 无 ts)——推断为过时/错误假设的注释, 非代码 bug(代码行为一致: ts None → 被过滤); 9-17 后 index_daily 缺数据根因未深挖(配置上 require_today=False 宽阈值无告警为已知事实)。
- **未证实**: 上证10年期国债指数的官方指数代码(外部网络受限未能检索, 名称与跟踪关系已由 F10 官方字段证实); 邮件最近实际发送内容(代码链路已确认, 云端日志未取); bond_probe 报告数据未在当前基准 v1.1.7 口径下重跑(报告 8-14 生成, 宇宙规则未变故结论方向稳健, 严格口径以重跑为准)。

## 复现段(证据可复核)

```bash
# 1. sh511260 基金概况(东财 F10, 2026-09-24)
curl -s "https://fundf10.eastmoney.com/jbgk_511260.html" -H "User-Agent: Mozilla/5.0" | grep -oE "跟踪标的[^<]{0,40}|成立日期[^<]{0,60}|净资产规模[^<]{0,60}"
# 2. 今日行情
curl -s "https://qt.gtimg.cn/q=sh511260" -H "User-Agent: Mozilla/5.0"   # 134.865, 20260924161500
# 3. 线上计划空
curl -s -H "User-Agent: Mozilla/5.0" "https://ss.fx8.store/data/nextday_plan.json"   # {"date":"20260923","empty":true}
# 4. index_daily 数据
python3 -c "
import sqlite3; c=sqlite3.connect('/Users/linhuichen/code/trade/data/sentiment.db')
print(c.execute(\"SELECT MIN(date),MAX(date),COUNT(*) FROM index_daily WHERE index_id='cgb_10y_etf'\").fetchone())
print(c.execute(\"SELECT date,close FROM index_daily WHERE index_id='cgb_10y_etf' ORDER BY date DESC LIMIT 4\").fetchall())"
# 5. 债类纳入回测(2026-08-14 报告数据, 本次未重跑)
python3 scripts/signal_kelly_backtest_bond.py --output docs/kelly/analysis/data/bond_probe_comparison.json
```

## 维度清单完成度

| 维度 | 完成 | 说明 |
|---|---|---|
| 标的查证(用户拍板核心) | ✓ | F10/天天基金/腾讯行情三方 |
| 各层生效对照 | ✓ | 10 层逐层代码+数据验证 |
| 线上产物实锤 | ✓ | 线上 nextday_plan empty + overview 字段 |
| 前视检查 | ✓ | T+1 价格口径核验 |
| 基准/版本影响 | ✓ | §5.4⑥ 变更清单 |
| §23.6 五项 | ✓ | 现状 vs 配上对照表 |
| 回测代价 | ✓ | 既有穷举报告引用(标注口径) |
| 诚实标注 | ✓ | 推断/未证实分列 |
