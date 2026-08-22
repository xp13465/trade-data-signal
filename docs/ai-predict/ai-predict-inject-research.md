# AI 预测注入面调研:已有数据逐项实测 + 注入设计

> 调研时间:2026-08-16(周日,数据截至 20260814 周五收盘)
> 调研 agent(只读,不改任何代码/基准/算法)。测试基准 = v1.1.1(纯调研,不动基准)
> 任务:为 P0「已有指标接入 AI 预测」做准备——理清 gen_daily_brief.py 当前实际注入字段,并逐项实测方法论文档 ~20 个候选指标的数据可用性,给出注入设计。
> 前置文档:`docs/ai-predict-news-macro-research-methodology.md`(P0 候选清单 + 优先级)、`scripts/gen_daily_brief.py`(现状)。

---

## 0. 一句话结论

**gen_daily_brief.py 单 prompt 主链路当前注入 25 项(技术/资金/情绪/机构/汪汪队五面),无估值、无跨市场、无龙虎榜、无腾落线;queries.py:1459 的 11 个宏观锚点只有 3 个(cn10y/a_qvix_300/a_qvix_1000)进了 AI prompt,其余 8 个(gold/oil/wti_oil/comex_silver/usdcnh/us10y/cn_us_spread/brent)只进 overview 前端展示没进 AI。候选 ~20 指标经逐项实测:14 组真实有值可注入(估值位置/美股期货/欧亚期货/汇率利差/腾落线/均线金叉/龙虎榜/行业资金流/解禁/IPO/打板溢价/涨跌比),4 项不可用需标注(新高新低 168/250 天=0、封单率/炸板数停更 07-21、行业换手覆盖 10/31)。**

---

## 1. 当前实际注入 AI 预测的完整字段清单

> 事实源:`scripts/gen_daily_brief.py` `load_data()` L226-530(数据注入)+ `build_prompt()` L663-759(system 规则 + user.data)+ 多角色 `split_domains()` L974-1025。生产配置 `config/daily_brief.yaml` `multi_agent_enabled`(生产走 6 角色编排,主链路单 prompt 为降级保底)。
> 实测:load_data('static-site/data', 'data/sentiment.db', '20260814') 返回 26 个顶层 key,JSON 32,428 字节 ≈ 2.2 万 token。

### 1.1 单 prompt 主链路注入清单(load_data 逐项)

| # | 注入变量 | 来源文件 | 有值(20260814) |
|---|---|---|---|
| 1 | summary(24 字段:summary_short/sentiment_label/fear_greed/sh_pct/up_count/down_count/zt_count/dt_count/buy_count/sell_count/tradable_*/sentiment_*/volume_amount/volume_label/ma_bullish/ma_bearish/top_industries[3]/bottom_industries[3]) | static-site/data/summary.json | ✅ sh_pct=0.67,ma_bullish=6 |
| 2 | signals_note(信号口径静态说明) | 代码内常量 | ✅ |
| 3 | signals_today(20 条:index_id/name/signal/reason[:80]) | overview.json | ✅ |
| 4 | name_map(index_id→name) | overview.json signals_today | ✅ |
| 5 | signals_today_count | overview.json | ✅ |
| 6 | recent_freeze(最近 5 个冰点日) | overview.json | ✅ |
| 7 | industry_heatmap_top(10 板块:id/name/pct_1d) | overview.json industry_heatmap | ✅ |
| 8 | alert(high/low score/level/hit_dims) | alert.json | ✅ |
| 9 | signal_stats_buy_top(买系 20d 胜率 top10) | signal_stats.json | ✅ |
| 10 | futures_acc_trend_tail(机构净多 5 日 last/trend/d5_chg) | futures_acc_trend.json series | ✅ |
| 11 | futures_acc_trend_latest(当日最新 roles) | futures_acc_trend.json latest | ✅ |
| 12 | futures_acc_conclusion(当前状态) | futures_acc_conclusion.json | ✅ |
| 13 | inst_ih_trend(中信/机构top20/国泰君安 15日席位净加仓) | futures.json citic/inst/guotai_ih_detail | ✅ |
| 14 | inst_ih_note(口径说明) | 代码内常量 | ✅ |
| 15 | etf_national_team(汪汪队异动信号+共振) | overview.json nt_signals_today | ✅ |
| 16 | etf_national_team_share(12 只近 5 日份额) | etf_national_team-1m.json | ✅ |
| 17 | etf_national_team_holders(季报机构占比) | etf_national_team_quarterly.json | ✅ |
| 18 | etf_national_team_note(口径+新鲜度) | 代码内常量 | ✅ |
| 19 | funds(24 个 metric:a_fund_main/a_fund_margin/a_fund_north/a_fund_north_quarterly/hk_south/a_qvix_300/a_qvix_1000/a_rotation_5d/10d/20d/a_rotation_concept_5d/10d/20d/a_width_fengban_rate/a_width_max_lianban/a_width_zhaban_rate/a_turnover_mean/p90/gt5_pct/a_volume_ratio/a_volume_signal/a_amount/ma5/ma20) | sentiment.db daily_metric | ✅ 全有值 |
| 20 | north_quarterly(季度反算,滞后) | daily_metric 最近一行 | ✅ |
| 21 | funds_note(资金口径说明) | 代码内常量 | ✅ |
| 22 | scores(a_sentiment/fear_greed/6 宽基情绪分) | sentiment.db score_daily | ✅ |
| 23 | indices(8 宽基 pct_change/close) | index_daily | ✅ |
| 24 | middle_indices(sz/cyb/kc50/bj50/hsi/hstech 涨跌幅) | index_daily | ✅ |
| 25 | cn10y(10 年国债收益率,单值) | daily_metric | ✅ 1.6964 |

**已注入面覆盖**:行情技术/信号胜率/资金/机构期货/ETF汪汪队/情绪/波动量价/预警。**未覆盖**:估值位置、跨市场(美股期货/汇率/利差/商品)、宽度历史(腾落线/均线金叉/新高新低)、龙虎榜、行业资金流、供给(解禁/IPO)、打板溢价。

### 1.2 多角色版数据域(split_domains L974-1025)确认

- **tech 域**:indices + signals_today + signal_stats_buy_top + summary 子集(sh_pct/ma_bullish/nh_count/nl_count/nhnl/volume/tradable_buy_count/sell_count)
  - ⚠️ 发现隐性缺口:tech 域 summary 引用了 `nh_count/nl_count/nhnl`(L985),但 load_data 的 d["summary"] **未带这三个字段**(L232-264 无),`s.get("nh_count")` 恒取 None → tech 域实际从未注入新高新低。这是 load_data 与 split_domains 的字段漂移,恰好印证"有数据未注入"。
- **fund 域**:funds + futures_acc_trend_tail/latest + inst_ih_trend + north_quarterly
- **sentiment 域**:scores + freeze + industry_heatmap + alert_low + rotation_width(封板/连板/炸板率)+ etf_national_team
- **risk 域**:alert + risk_funds(qvix/volume/main/hk_south/turnover)+ industry_heatmap

**四角色均未覆盖**:估值/跨市场/龙虎榜/腾落线/新高新低/行业资金流/解禁/IPO/打板溢价。

---

## 2. queries.py:1459 宏观锚点归属(11 个)

> 事实源:`app/queries.py` L1459-1463 `/api/overview` extras 注入 11 锚点(gold/oil/wti_oil/comex_silver/usdcnh/a_qvix_300/a_qvix_1000/cn10y/us10y/cn_us_spread/brent)。导出产物 `static-site/data/overview.json` 只落 3 个(gold_6m/cn10y_6m/a_qvix_300_6m,6m 序列)。

| 锚点 | 进 `/api/overview`(前端展示) | 进 overview.json 产物 | 进 AI 预测 prompt |
|---|---|---|---|
| cn10y | ✅ | ✅ cn10y_6m(20260814=1.6964) | ✅ load_data L525-527 从 daily_metric 读单值 |
| a_qvix_300 | ✅ | ✅ a_qvix_300_6m(20260814=19.658) | ✅ load_data funds L476-486 |
| a_qvix_1000 | ✅ | ❌ | ✅ load_data funds L476-486 |
| gold | ✅ | ✅ gold_6m(20260814=943.16) | ❌ |
| oil | ✅ | ❌ | ❌ |
| wti_oil | ✅ | ❌ | ❌(daily_metric 20260814=82.4 有值) |
| comex_silver | ✅ | ❌ | ❌(20260814=64.815 有值) |
| usdcnh | ✅ | ❌ | ❌(20260814=678.78 有值) |
| us10y | ✅ | ❌ | ❌(20260814=4.68 有值) |
| cn_us_spread | ✅ | ❌ | ❌(20260814=-2.9836 有值) |
| brent | ✅ | ❌ | ❌(20260814=88.66 有值) |

**结论**:11 锚点中 3 个已进 AI(cn10y/a_qvix_300/a_qvix_1000),8 个只进 overview 展示没进 AI(gold/oil/wti_oil/comex_silver/usdcnh/us10y/cn_us_spread/brent)——这 8 个正是方法论文档 P0「跨市场面」的核心,数据真实有值,接入成本≈0。

---

## 3. 候选指标逐项实测(方法论文档 §2 的 6 组 ≈ 20 项)

> 实测数据源:`data/sentiment.db` daily_metric(20260814 最新完整交易日)+ `static-site/data/` JSON 产物。**每个指标都读了实际文件,给真实样本值,非 null/空/0 污染才判「可注入」**。

### 3.1 估值/位置面 —— ✅ 全部可注入

| 指标 | 来源 | 字段路径 | 样本值(20260814) |
|---|---|---|---|
| 宽基估值百分位 | `static-site/data/position.json` | `positions[]` → `{index_id, current, percentile_1y, percentile_3y, percentile_5y, label}` | sh: 1y40.4/3y80.1/5y88.1 label=合理;sz 1y70.0;cyb 1y75.2 偏高;kc50 1y80.8 高位;sz50 1y20.8 低位 |
| 上证股息率 | daily_metric | `a_div_yield` | 2.66 |
| 同源单值(备选) | daily_metric | `sh_position_1y/3y/5y` 等 8 指数×3 档=24 条 | sh_position_1y=40.4 |

> 说明:position.json 是权威源(含 current 点位 + label 语义),daily_metric 的 *_position_* 是单值版。8 指数 × 1y/3y/5y 全部有值。可顺带算 ERP 提示:股息率 2.66% − cn10y 1.70% ≈ +0.96%(中期位置参考)。

### 3.2 跨市场/全球面 —— ✅ 全部可注入(注意 usdcnh 量纲)

| 指标 | 来源 | 字段路径 | 样本值(20260814) |
|---|---|---|---|
| 美股期货 4 | daily_metric | `us_futures_es/nq/ym/rty_chg` | es +0.10 / nq +0.28 / ym −0.15 / rty +0.97 |
| 欧亚期货 9 | daily_metric | `us_futures_dax/cac40/ftse100/sx5e/sensex/asx200/kospi/nikkei225/hsi_chg` | dax +0.82 / kospi +2.42 / asx200 −1.0 / hsi +0.43 |
| 期货快照(别名) | `static-site/data/intraday_snapshot.json` | `us_futures` → `hf_ES/hf_NQ/hf_YM/hf_RTY/hf_HSI/b_DAX/b_CAC/b_UKX/b_SX5E/b_SENSEX/b_KOSPI/b_AS51/b_NKY` → `{chg_pct, expect, display_name}` | hf_ES chg_pct=0.098 expect=持平 |
| 全球指数实时(别名) | intraday_snapshot.json | `global_realtime` → 7 国际(含 hk 8 行业) | nikkei225 chg_pct=0.59 / kospi 2.42 |
| 离岸人民币 | daily_metric | `usdcnh` | 678.78 ⚠️ **量纲×100,实为 6.7878**(注入需 ÷100 或注明) |
| 中美利差 | daily_metric | `cn_us_spread` | −2.9836(10Y,cn10y 1.70 − us10y 4.68 ≈ −2.98 自洽) |
| 美 10 年收益率 | daily_metric | `us10y` | 4.68 |
| 贵金属/原油 | daily_metric | `gold` / `wti_oil` / `brent` / `comex_silver` | 943.16 / 82.4 / 88.66 / 64.815 |

> 13 个 us_futures_*_chg 品种 20260814 全有值。intraday_snapshot.json 的 us_futures 更丰富(含 expect 预涨/预跌语义,chg_pct 与 daily_metric 同源一致)。

### 3.3 宽度/技术面 —— ✅ 腾落线/均线金叉可注入,⚠️ 新高新低不可用

| 指标 | 来源 | 字段路径 | 样本值(20260814) |
|---|---|---|---|
| 腾落线 | `static-site/data/ad_line.json` | `data[-1]` → `{ad_line, ad_line_ma5, ad_line_ma20, up_count, down_count, ratio}` | ad_line=−133737, ma5=−132084, ratio=0.447 |
| 涨跌比 | daily_metric | `a_up_down_ratio` | 0.447(与 ad_line.ratio 同源一致) |
| 均线金叉/死叉 | `static-site/data/ma_alignment.json` | `data[-1]` → `{bullish, bearish, cross}` | bullish=0 / bearish=0 / cross=8(当日全指数交叉) |
| 新高新低 | `static-site/data/new_high_low.json` | `data[-1]` → `{nh_52w, nl_52w, nhnl_52w, nh_20d, nl_20d}` | **全 0** ⚠️ |

> ⚠️ **新高新低可用性存疑(诚实标注)**:new_high_low.json 全历史 250 天中 **168 天(67%)nh_52w=nl_52w=0**,daily_metric 的 a_nh_20d 近 8 日全 0。此「0」疑为采集失败而非真实「无新高新低」,作为方向指标几乎恒 0、无判别力。**不建议注入**(或注入前先修采集 + 换源验证)。summary.json 的 nh_count/nl_count/nhnl 同源也是 0,且 load_data 未带(见 1.2 缺口)。

### 3.4 资金面增量 —— ✅ 龙虎榜/行业资金流可注入

| 指标 | 来源 | 字段路径 | 样本值(20260814) |
|---|---|---|---|
| 龙虎榜机构净买 | daily_metric | `lhb_count` / `lhb_inst_net` | 74 条 / +5.22 亿 |
| 行业主力资金流 | daily_metric | `ind_flow_sw_*`(31 申万一级) | 31 行业全有值,值域 −106.21 ~ +117.72 亿,top3 净流入 / bottom3 净流出有判别力 |
| 行业换手率 | daily_metric | `ind_turn_sw_*` | ⚠️ 20260814 仅 10/31 行业有值,覆盖不全,暂缓 |

> lhb_inst_net 近 8 日有真实波动(−14.2 ~ +18.6 亿),非 0 污染,有效。ind_flow_sw 31 行业 20260814 全覆盖(抽样非 null 非 0),是方法论文档 §4.4「资金面权重最高」的直接补充。

### 3.5 情绪/打板增强 —— ⚠️ 打板溢价可注入,封单率/炸板数停更

| 指标 | 来源 | 字段路径 | 样本值 |
|---|---|---|---|
| 打板溢价 | daily_metric | `a_width_daban_premium` | 20260814=0.0608 ✅ |
| 封单率 | daily_metric | `a_width_seal_rate` | ⚠️ **最新 20260721=0.915,停更 24 天** |
| 炸板数 | daily_metric | `a_width_zb_count` | ⚠️ **最新 20260721=11.0,停更 24 天** |

> seal_rate/zb_count 自 07-21 后无更新(20260814 无当日行),属停更/降级数据,**不可注入**(注入=喂过期数据)。打板溢价 20260814 有值可注入。

### 3.6 供给/事件面 —— ✅ 可注入

| 指标 | 来源 | 字段路径 | 样本值(20260814) |
|---|---|---|---|
| 解禁 | daily_metric | `unlock_count` / `unlock_amount` | 4 只 / 4264.59 亿 |
| IPO | daily_metric | `ipo_count` / `ipo_amount` | 1 只 / 17.60 亿 |

### 3.7 可用性判定汇总

| 判定 | 指标 |
|---|---|
| ✅ 可注入(14 组) | 估值位置(8指数×1y/3y/5y+股息率)、美股期货4、欧亚期货9、usdcnh、cn_us_spread、us10y、gold/oil/brent/silver、腾落线+涨跌比、均线金叉、龙虎榜、行业资金流、解禁、IPO、打板溢价 |
| ⚠️ 存疑不可注入(3 项) | 新高新低(67% 天=0)、封单率/炸板数(停更 07-21)、行业换手(覆盖 10/31) |

---

## 4. 注入设计建议

### 4.1 新增注入字段清单(14 组,load_data 聚合为精简结构)

| 新增 key | 字段/内容 | 来源 | prompt 表述示例 |
|---|---|---|---|
| `positions` | 8 宽基 percentile_1y/3y + label(5y 可省) | position.json positions | "宽基估值位置:上证 1y40/3y80(合理),上证50 1y21(低位),科创50 1y81(高位);股息率2.66%,股息-10Y利差≈+0.96%" |
| `cross_market` | us_futures es/nq/ym/rty + dax/cac40/ftse100/sx5e/kospi/nikkei225/hsi/sensex/asx200 chg | daily_metric us_futures_*_chg | "美股期货:标普+0.10/纳指+0.28/道指-0.15/罗素+0.97;欧亚:dax+0.82/kospi+2.42/asx-1.0——隔夜跌时对A股开盘领先更强" |
| `forex_commodity` | usdcnh(÷100=6.79)、cn_us_spread、us10y、gold、wti_oil、brent、comex_silver | daily_metric | "离岸人民币6.79;中美10Y利差-2.98(中1.70/美4.68);黄金943/原油82/布油89/银65" |
| `ad_line` | ad_line + ma5 + ratio | ad_line.json data[-1] | "腾落线-133737(ma5-132084),涨跌比0.45(2400涨:2969跌)——宽度偏弱" |
| `ma_cross` | bullish/bearish/cross | ma_alignment.json data[-1] | "均线状态:8指数全交叉(cross=8,多0/空0)" |
| `lhb` | lhb_count/lhb_inst_net | daily_metric | "龙虎榜74条,机构净买+5.2亿(近8日-14~+19亿波动)" |
| `ind_flow` | 31 行业资金流 top3/bottom3 | daily_metric ind_flow_sw_* | "行业资金流:净流入前三(电子+118/…),净流出前三(…-106)" |
| `unlock_ipo` | unlock_count/unlock_amount + ipo_count/ipo_amount | daily_metric | "解禁4只4265亿,IPO 1只18亿——供给压力" |
| `daban` | a_width_daban_premium | daily_metric | "打板溢价0.06(打板资金兑现意愿低)" |

> 多角色路径:split_domains 新增 1 个 **macro 域**(估值+跨市场+汇率商品+宽度+供给+打板)或并入 fund/sentiment 域;主编 build_editor_messages 的 role 顺序加 macro。建议独立 macro 域(与多角色 6 角色编排的「事件面/宏观」定位一致,ai-predict-multiagent-plan.md 阶段三④角色)。

### 4.2 prompt 组织方式与长度控制

- **现状**:单 prompt 主链路 user.data = 整个 load_data dict(26 keys,JSON 32,428 字节 ≈ **2.2 万 token**,实测);sys_text 规则 ~1,800 字。call_deepseek `max_tokens=1200`(输出侧,`payload` L792-798)。
- **新增往哪塞**:load_data 聚合后加 key(user.data 自动带入),并在 build_prompt sys_text 的规则 4c 后补一条「可引用宏观/跨市场数据(估值位置/美股期货/中美利差/腾落线/龙虎榜/行业资金流/解禁),作方向与风险参考」;多角色走 split_domains 新增 macro 域。
- **长度预算**:新增 9 组精简聚合段预计 +4~6 KB(≈0.3~0.4 万 token),单 prompt 总输入 ≈ 2.6 万 token,仍在 deepseek-chat 64K context 内,余量充足。**控制手段**:
  1. position 只注 1y+3y 百分位+label,5y 可省(极端位置才提)
  2. us_futures 13 品种合并为一行 chg 序列,不注 price/signal/expect 全字段(只取 chg_pct + 个别 expect)
  3. 行业资金流只注 top3/bottom3(不注 31 全量)
  4. 全量序列(ad_line/ma_alignment/new_high_low)只取 data[-1] 当日,不注历史数组

### 4.3 guard 策略(无值/不可用不注入)

1. **停更过滤**:load_data 聚合时按「字段最新日期 == 当日 data date」过滤——seal_rate/zb_count(停更 07-21)自动跳过,不注入过期值。
2. **None 过滤**:聚合函数 `if v is None: skip`;prompt 只出现有值字段,None 字段整体不渲染。
3. **大面积 0 拦截**:新高新低(new_high_low)因 67% 天=0 无判别力,本次**不注入**,先修采集换源;注入前在代码里做「近N日非0占比」守卫,低于阈值不渲染。
4. **量纲标注**:usdcnh=678.78 为 ×100 量纲,注入时 ÷100 得 6.79 或明确写「离岸人民币 6.79(原始 678.78)」,防 AI 误解为 678 元。
5. **覆盖不全降级**:行业换手 ind_turn_sw 覆盖 10/31,本次不注入,等采集补全。

### 4.4 实施提醒(不属本次改动,供主控派单参考)

- 改 load_data/split_domains = 纯新增注入字段,不破坏既有字段(符合 §23.7 版本冻结契约「只增不改」)。
- **但**动到「AI 预测」核心实用功能的输入面,按 §5.4⑥ 需发中间版本标记 + §21 算法公示同步(前端 AI 预测 tooltip 声明「含估值/跨市场/龙虎榜/腾落线/供给面」);§22 数据一致性(注入面 = 前端展示面 = 同一数据源)。
- load_data 与 split_domains 存在字段漂移(tech 域引 nh_count 但 load_data 未带,见 1.2),实施时顺手对齐或移除幽灵引用。

---

## 复现

### 数据文件
- `scripts/gen_daily_brief.py`(load_data L226-530 / build_prompt L663-759 / call_deepseek L763-827 / split_domains L974-1025 / run_multi_agent L2024-2082)
- `app/queries.py` L1459-1463(/api/overview extras 11 锚点)
- `data/sentiment.db` daily_metric / score_daily / index_daily
- `static-site/data/`:overview.json / summary.json / position.json / ad_line.json / ma_alignment.json / new_high_low.json / intraday_snapshot.json / futures*.json / signal_stats.json / alert.json / etf_national_team*.json

### 关键命令(复现本文实测结论)
```bash
# 1) 确认 gen_daily_brief.py 未注入候选字段(仅 L985 幽灵引用 nh_count 等):
grep -n "position\|us_futures\|lhb\|cn_us_spread\|usdcnh\|div_yield\|ad_line\|unlock\|ind_flow\|daban\|seal_rate\|zb_count" scripts/gen_daily_brief.py

# 2) 候选指标当日值(sentiment.db):
sqlite3 data/sentiment.db "SELECT metric_id,value FROM daily_metric WHERE date='20260814' AND metric_id IN ('sh_position_1y','a_div_yield','lhb_inst_net','lhb_count','us_futures_es_chg','us_futures_dax_chg','cn_us_spread','usdcnh','us10y','gold','wti_oil','brent','comex_silver','a_width_daban_premium','unlock_amount','ipo_count','a_up_down_ratio','a_ad_line') ORDER BY metric_id;"

# 3) 停更/污染核查:
sqlite3 data/sentiment.db "SELECT metric_id,MAX(date) FROM daily_metric WHERE metric_id IN ('a_width_seal_rate','a_width_zb_count') GROUP BY metric_id;"   # 停更 20260721
sqlite3 data/sentiment.db "SELECT COUNT(*) FROM daily_metric WHERE date='20260814' AND metric_id LIKE 'ind_flow_sw%';"   # 31 行业全覆盖
sqlite3 data/sentiment.db "SELECT COUNT(*) FROM daily_metric WHERE date='20260814' AND metric_id LIKE 'ind_turn_sw%';"   # 仅 10/31

# 4) JSON 产物最新值:
python3 -c "import json; d=json.load(open('static-site/data/ad_line.json'))['data'][-1]; print(d)"
python3 -c "import json; d=json.load(open('static-site/data/ma_alignment.json'))['data'][-1]; print(d)"
python3 -c "import json; d=json.load(open('static-site/data/position.json'))['positions']; print([(x['index_id'],x['percentile_1y'],x['label']) for x in d])"
python3 -c "import json; d=json.load(open('static-site/data/new_high_low.json'))['data']; print('nh=nl=0 天数:', sum(1 for r in d if (r.get('nh_52w') or 0)==0 and (r.get('nl_52w') or 0)==0), '/', len(d))"

# 5) 当前 prompt 输入体积:
python3 -c "
import sys; sys.path.insert(0,'scripts')
from gen_daily_brief import load_data, pick_repo, pick_db
d=load_data(pick_repo()/'static-site'/'data', pick_db(pick_repo()), '20260814')
raw=__import__('json').dumps(d, ensure_ascii=False)
print('data JSON 字节:', len(raw.encode('utf-8')), '≈token:', int(len(raw.encode('utf-8'))/1.5))"
```

关键口径一句话:本报告只做注入面调研与设计,不改任何代码/基准;候选指标以 20260814(周五收盘,最新完整交易日)实测,停更/0 污染/覆盖不全均已诚实标注。
