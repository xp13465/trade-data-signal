# AI 预测「方向锚改造」离线回放 A/B 可行性调研(2026-08-20)

> 调研 agent 产出,只读不改,证据全可复核。主控验收用。
> 一句话结论:**离线回放 A/B「可行」——`gen_daily_brief.py --date` 已支持历史日期,核心因子(期货转向/利率/跨市场)全部按日期可从 sentiment.db 取到(8/14/8/17/8/18 三天数据已验证在库);但有 2 个障碍需小改造点解决(JSON 侧当前文件污染 + main() 会覆盖生产产物),改造不碰生产逻辑。**

## ① 结论:离线回放 A/B 可行,当前"半支持"

| 层 | 现状 | 证据 |
|---|---|---|
| `--date` 参数 | 已存在,`WHERE date=?` 查 DB | gen_daily_brief.py L3160 `ap.add_argument("--date")` |
| DB 侧(score_daily/index_daily/daily_metric/futures_position/futures_accuracy) | **历史可取**(查询全带 date 参数) | load_data L669-724 DB 查询全 `WHERE date=?` |
| news 注入 | **已支持历史归档重跑**(date != 今日读归档) | `_load_news_inject` L258 注释"模式 A(重跑历史日期,date != 今日,可复现)" |
| reflections 反思注入 | **已时间隔离**(只注入 backfilled_via < date) | `build_reflection_inject` L2708 |
| JSON 侧(summary/overview/futures.json/futures_acc_trend.json/position/ad_line/ma_alignment) | **读当前文件,不随 date 变** ← 障碍① | load_data L428/L470/L530/L564/L817/L837/L849 |
| main() 完整跑 | write_outputs 覆盖当日 daily_brief.json + history + notify + R2 上传 ← 障碍② | main() L3382/L3390 |

**障碍①(JSON 污染)**:直接 `--date 20260814` 跑,DB 是 8/14 历史,但 summary/overview/futures.json 是今天(8/20)最新 → 混合快照。尤其 `inst_ih_trend`(中信/机构/国泰 15日,方向判断最关键)读当前 futures.json(L564-584),会被今天的数据污染。

**障碍②(生产污染)**:main() 完整链路会 `write_outputs` 覆盖 `static-site/data/daily_brief.json` + 追加 history + `notify_daily_brief` 发邮件 + R2 上传。离线回放 8/14 若直接跑,会把当天的 daily_brief.json 覆盖成 8/14 预测 → **生产数据事故**。必须加回放模式跳过写盘/通知/上传。

## ② 最小改造点(不碰生产逻辑,2 种方案)

### 方案 A(推荐,零侵入):独立回放脚本
新增 `docs/ai-predict-offline-ab-frontvalidate-20260820/scripts/offline_replay.py`:
- `import gen_daily_brief` 复用 `build_prompt`/`build_editor_messages`/`parse_ai_output`(改造后)
- 从 sentiment.db 按 date 构造 data 域(复用 load_data 的 DB 查询逻辑 + 从 futures_position 重建 inst_ih_trend)
- 调 `call_deepseek` 生成,只打印 direction/range,对比实际次日方向
- 生产 main() 零改动

### 方案 B(侵入最小):gen_daily_brief.py 加 `--replay` 开关
- L3160 附近加 `--replay`(配合 `--date` 历史日期)
- load_data 内 inst_ih_trend/futures_acc_trend_tail/cross_market/forex_commodity(L525-767)加"replay 模式从 DB 重建"分支,覆盖当前 JSON 值
- main() L3382-3390:`--replay` 时跳过 write_outputs/notify/upload/backfill_hits/record_reflections

> **方向锚改造本身**(加 T1-T5/L1-L6 因子语义)落点 = `build_prompt` sys_text(单 prompt,L1005-1108)+ `build_editor_messages` sys_text(多角色主编,L1496-1603)。生产默认走多角色(`multi_agent_enabled: true`),但离线回放建议先用单 prompt 快速验证(3 次调用 vs 18 次),单 prompt 与主编的因子语义应同文同步改。

## ③ 8/14/8/17/8/18 三天因子状态——全部可取(已实证)

### DB 数据在位
| 数据 | 8/14 | 8/17 | 8/18 | 命令 |
|---|---|---|---|---|
| futures_position | 15 条 | 15 条 | 15 条 | `SELECT date,variety,role,long_chg,short_chg FROM futures_position WHERE date IN (...)` |
| futures_accuracy | 75 条 | 75 条 | 75 条 | 同上表名 |
| daily_metric 关键因子(us10y/cn10y/gold/cn_us_spread/us_futures_*) | 全有 | 全有 | 全有 | `SELECT metric_id,value FROM daily_metric WHERE date=?` |
| index_daily sh | +0.005 | +1.41(8/17 实际) | +0.19(8/18 实际) | `SELECT pct_change FROM index_daily WHERE date=? AND index_id='sh'` |

### 三样本转向信号(按 mine 口径 net_chg=long_chg-short_chg)
| 样本 | 信号日因子状态 | 次日实际 | 旧 AI | T/L 因子判定 |
|---|---|---|---|---|
| 8/14→8/17 | 中信综合 net_chg -213(转空)、top20 IC -1293(转空);均线多头(sh 3927>ma20 3862) | **+1.41 涨** | down(-0.8~-0.3)猜反 | T2/T3「转空逆势看涨」→ 应 up |
| 8/17→8/18 | 中信IM +997(转多)、国泰综合 +3447(大幅转多) | **+0.19 微涨** | up(0.3~0.8)方向对区间偏高 | T1「转多顺势看涨」→ up 但幅度小 |
| 8/18→8/19 | 全席位大幅转多(中信综合 +4858、top20 IM +4382、top20 综合 +8137);**L3 纳指期货 nq_chg=-1.302 大跌** | **-2.40 暴跌** | down 方向对区间差3倍 | **T 因子失效**(转多但暴跌),需 L3 压制 → down |

> **关键洞察**:纯 T1-T5 能修正 8/14/8/17,但 **8/18 是"T 因子失效样本"**——全机构大幅转多却次日暴跌。改进后 prompt 必须在 8/18 正确权衡「T 主权重 vs L3 纳指期货大跌(辅助压制)」,这正是报告 C5「方向合成:转折因子主权重、联动因子辅助」的设计点。**离线回放的核心看点 = 改进后模型是否在 8/18 用 L3 压住 T1。**

## ④ 成本与时段(§5.6)

- 单 prompt:3 样本 × 1 次 = 3 次调用(便宜,推荐首轮)
- 多角色:3 样本 × (4 角色 + 研究员 + 主编) ≈ 18 次调用
- **时段**:现在(13:24)14:00 进高峰。官方 API(api.deepseek.com)高峰 9-12/14-18 不可用(§5.6)→ 要么 14:00 前跑完,要么 `config/daily_brief.yaml` provider 切 `ark`(方舟计费独立),要么 18:00 后跑
- 防污染必须:`--replay`(或独立脚本)天然不写盘/不通知/不上传

## ⑤ 替代验证路径(不调模型,0 成本,可立即做)

用现成胜率表 `docs/ai-predict-direction-market-winning-signals-20260820/scripts/out/final_rules_bull.json` 做规则前测:
- 8/14:top20IC转空+均线多头 = 84.2%(n=38,2026 10/10=100%)→ 应 up → 旧 AI down 错 ✓
- 8/17:中信IM转多 64.2%(n=67)/国泰IH转多 66.2%(n=71)→ 应 up → 旧 AI 方向对 ✓
- 8/18:无 T 因子看跌,但 L3 纳指期货大跌 → 需 L 因子 → **规则前测直接暴露"纯 T 不够,8/18 需 L"**
- 结论:**规则前测可先在 10 分钟内用现成胜率表判三样本方向,作为调模型前的逻辑自检**,与离线回放互补。

## ⑥ 诚实标注

- **3 样本统计意义有限**,只能看"是否能修正那几天明显误判",是**方向性前测非严格 A/B**;严格 A/B 仍需真实交易日跑 7 天。
- 8/18 是 T 因子失效样本,离线回放若改进后仍给 up,说明单纯加 T 语义不够,需组合过滤(T3 均线)或 L 因子权重 → **这正是要测的**。
- 8/14 news 无归档(8/16 才迁 2026/ 子目录),回放 8/14 时 news 面 skipped(影响小)。
- known_bias 注入(`compute_known_bias` L3242 用当前全量 history)在单 prompt 回放时含 8/14 之后信息,严格回放应截断到回放日或关 review_enabled;reflections 已时间隔离不受影响。

## 复现

- **数据文件**(全部只读):`/Users/linhuichen/code/trade-data/data/sentiment.db`(futures_position/futures_accuracy/daily_metric/index_daily)、`/Users/linhuichen/code/trade/static-site/data/futures.json`(中信 16 天明细)、`/Users/linhuichen/code/trade/static-site/data/daily_brief_history.json`(8 条预测)、`docs/ai-predict-direction-market-winning-signals-20260820/scripts/out/final_rules_bull.json`(现成胜率表)
- **关键代码**:`/Users/linhuichen/code/trade/scripts/gen_daily_brief.py` — `--date` L3160、load_data L423、build_prompt L1005、split_domains L1323、build_editor_messages L1496、run_multi_agent L2830、_load_news_inject L258、build_reflection_inject L2694
- **重跑命令**(验证三样本因子状态):
  ```bash
  # 期货持仓转向
  python3 -c "import sqlite3;c=sqlite3.connect('file:/Users/linhuichen/code/trade-data/data/sentiment.db?mode=ro',uri=True);[print(d, c.execute('SELECT variety,role,long_chg,short_chg FROM futures_position WHERE date=?',(d,)).fetchall()) for d in ['20260814','20260817','20260818']]"
  # 利率/跨市场因子
  python3 -c "import sqlite3;c=sqlite3.connect('file:/Users/linhuichen/code/trade-data/data/sentiment.db?mode=ro',uri=True);[print(d, c.execute(\"SELECT metric_id,value FROM daily_metric WHERE date=? AND metric_id IN ('us10y','cn10y','gold','cn_us_spread','us_futures_nq_chg','us_futures_es_chg')\",(d,)).fetchall()) for d in ['20260814','20260817','20260818']]"
  # 次日实际方向
  python3 -c "import sqlite3;c=sqlite3.connect('file:/Users/linhuichen/code/trade-data/data/sentiment.db?mode=ro',uri=True);[print(d, c.execute(\"SELECT pct_change FROM index_daily WHERE date=? AND index_id='sh'\",(d,)).fetchone()) for d in ['20260817','20260818','20260819']]"
  # 历史预测方向
  python3 -c "import json;d=json.load(open('static-site/data/daily_brief_history.json'));[print(i['date'],i['meta']['direction'],i['meta'].get('range'),i['meta']['hit']) for i in d['items']]"
  ```
- **数据截止**:2026-08-20 13:24;8/19 预测(hit=null)待 8/20 20:40 回填
- **关键口径**:预测 = 基于 date 收盘数据预测**次日**;net_chg = long_chg - short_chg(已验证与 futures.json total_chg 逐位一致,如 20260729=-2209)
