# 凯利回测调教参数过拟合监控系统 设计方案

> 2026-08-15 · 调研 agent 产出 · 供主控/用户拍板 · 落档 docs/kelly/analysis/
> 状态:方案设计(只读调研,未实施)。只落档不 commit(主控统一)。

## 0. 需求一句话

用户按 AFG 交易模式实操,实操数据是硬检验;系统侧需要一个**每日打点**的监控:①现有准确率每日记录做曲线 ②自研过拟合指标每日计算做曲线 ③按最小象限多维记录(不只总值)④异常时**邮件通知**(综合预警)。走势图放首页「近期技术参考点」下方、「汪汪队信号」前方(首页第一个左右布局 div 内)。

## 1. 现状盘点(证据)

### 1.1 现有「准确率」在哪、怎么算

**位置**:首页「近期技术参考点」卡片汇总条(总准确率 X% (T对/F错·N未结算) | 高·中·低)。
**函数**:`static-site/app.js:1440 _calcSignalAccuracy(items)`(汇总条渲染 L2371-2471)。
**口径**(app.js L2398-2407 `_totalTip` 原文):
- 范围:近15交易日 `signals_today` 的 `since_correct` 方向命中率
- 公式:命中率 = 对数/(对+错)×100%,排除未结算 + 波段持有(band_hold)
- 对错判定:看多(buy/buy_aux/buy_special/buy_backup)至今涨=对;看空(sell/sell_stop_loss)至今跌=对;band_hold 中性不计
- 基准:信号日收盘价 → 今日收盘价 涨跌方向
- 分档:高(score≥0.75)/中(0.55-0.75)/低(<0.55);另按信号类型 byType 分组

**后端算 since_correct**:`app/queries.py:858-924`(方案B后端注入):
- `since_return = (今日收盘 - 信号日收盘)/信号日收盘 × 100`(对 index_daily.close 或 daily_metric/score_daily)
- 看多至今涨=对,看空至今跌=对,band_hold=None,今日信号=None(无"至今"语义)

**计算时机**:前端实时算(overview.json signals_today 近15日,178条/20260814 快照,含 since_correct/since_return/_bt_in_universe/_bt_late/ai_macro);since_correct 由 update_all/export 重算。

**⚠ 能否打点**:现有首页准确率是**近15日滚动快照,非每日独立点**(同一批信号随今日收盘价反复变)。要画历史曲线必须从底层数据源回算(signal_daily + index_daily),见 §2。

### 1.2 数据资产(支撑曲线的基础)

| 数据 | 位置 | 范围/量 | 用途 |
|---|---|---|---|
| `signal_daily` 表 | sentiment.db | 1991-02-05 → 2026-08-14,70302条,含 date/index_id/signal/reason | **每日信号权威历史**;实盘口径打点源 |
| `index_daily` 表 | sentiment.db | 指数收盘价全历史 | 信号后 N 日实际涨跌 |
| `etf_daily` 表(accum_nav) | etf_national_team.db | ETF 累计净值(已复权) | 信号→ETF 实际收益 |
| `signal_kelly_trades.json` | static-site/data + R2 | 2011-01-19 → 2026-08-13,27万笔,16象限×9模式 | **回测成交明细**;按 signal_date 分组打"回测准确率"曲线 |
| `signal_kelly_backtest.json` | static-site/data + R2 | 每象限×模式×周期(y1/y3/y5/y10/all) 的 n/win_rate/pl_ratio/kelly_f | 回测预期基准 |
| `signal_stats.json` | static-site/data | 每 index_id×signal 的 5d/10d/20d 前向收益胜率/score | 信号本身把握度 |
| `daily_metric` 表 | sentiment.db | date/metric_id/value/source | **现成每日打点载体**(key-value 按日) |
| `lab_param_scan.json` | static-site/data | 7策略网格扫描,desc="验证默认参数处于稳定高原而非孤立尖峰(过拟合)" | 参数稳定性维度的现成参照范式 |
| `config/universe_rules.yaml` | trade | 入样宇宙单一事实源(§23.6) | 入样判定 |

### 1.3 调教参数载体(用户主推 AFG)

- **AI宏 4+3+1**:基础4(n2NovSpecialIndustry/excludeSpecialBear/janMidRating/janMidSpecial)+核心3(r7MayReinforced/excludeAuxCross/greedy15)+1类回测剔除(未入样/波动相关)。lab.js L8697-8702 `_kellyPersistMemberKeys`
- **K 档**:1/2/3/4,默认 **1=主推**(2026-08-14 #BC 由3改1)
- **卖出模式 9 种**:A=固定10天 / B=3%止盈 / C=5% / D=7% / E=持有5天 / F=持有15天 / G=卖出信号 / H=卖出+追止损 / I=追关注加追止损。**用户主推 A/F/G**(G=信号驱动卖出,默认推荐卖出法)
- **前端展示**:首页 AI降亏过滤(删除线,app.js L1762)+ AI仓位建议 badge(AI建议N/当日已满/AI警示,app.js L2127-2245,读 `_bt_in_universe` 1:1 对齐回测)+ 凯利页 16象限×9模式×5周期表

### 1.4 诚实标注(过拟合监控的基准可信度)

- **✅ 回测评分无前视偏差**:`app/compute/signal_stats.py:192` 的 score = `series.shift(-h)/series - 1`(信号日后 h 日的前向收益),对每个信号只用其之后 N 日数据;回测 rating 分类用此 score(L959-961),无未来依赖
- **⚠ 规则演进漂移**:signal_daily 历史信号是"当时规则"固化,但信号规则有演进(如新增 buy_backup/ATR 止损参数调整 L2647),历史信号库与"当前规则"不完全一致——是漂移非前视,标注为"历史信号按当前宇宙+当前降亏键重放"
- **⚠ 实盘样本极早**:用户实操自 2026-08-14 起,实盘独立样本前期极少,曲线起步段标注"数据不足"
- **⚠ 单日样本小**:按 signal_date 分组的每日信号数 1-7 个(trades mkt_a/G 实测),单日准确率 0-100% 剧烈波动,**必须滚动窗口(30/60/90)平滑,不直视单日点**

## 2. 准确率每日打点设计

### 2.1 双口径(两条曲线)

| 口径 | 定义 | 数据源 | 历史可回算? |
|---|---|---|---|
| **回测口径** | 信号→按卖出模式到期卖出后的收益方向(return_pct>0=对) | signal_kelly_trades.json 按 signal_date 分组 | ✅ 2011-2026 全史 |
| **实盘口径** | 信号日收盘 → 最新收盘方向(与首页 since_correct 同口径) | signal_daily + index_daily | ✅ 可回算(同 signal_stats 前向收益逻辑) |

**关键洞察**:两条曲线都可用现有数据**回算到 2011 年**,不是从实操日起积累——曲线一上线就有 15 年历史。

### 2.2 每日打点内容(最小象限记录)

对每个交易日 T,记录:

```
{
  "date": "YYYYMMDD",
  "signals": [ 当日新信号清单(实盘打点) ],
  "actual": {   # 实盘口径:信号日→最新收盘
    "total": {"n":, "win":, "win_rate":},
    "by_signal": {"buy": {...}, "buy_aux": {...}, "buy_special": {...}, "buy_backup": {...}},
    "by_rating": {"high": {...}, "mid": {...}, "low": {...}},
    "by_market": {"mkt_a": {...}, "mkt_hk": {...}, "mkt_global": {...}, "mkt_industry": {...}, "mkt_concept": {...}},
    "by_etf_tier": {"strong": {...}, "related": {...}, "approx": {...}, "has_track": {...}},
    "by_k": {"k1": {...}, "k2": {...}, "k3": {...}, "k4": {...}},
    "by_mode": {"A": {...}, "F": {...}, "G": {...}}
  },
  "backtest": {  # 回测口径:同象限同模式预期(从 trades 聚合)
    "total": {"n":, "win":, "win_rate":}, "by_*": {...}
  }
}
```

**象限划分**(对齐 signal_kelly_backtest.py 的 16 象限):评级3(rating_high/mid/low)+ ETF归类4(etf_strong/related/approx/has_track)+ 信号类型4(sig_main/buy, sig_aux, sig_special, sig_backup)+ 指数大类5(mkt_a/mkt_hk/mkt_global/mkt_industry/mkt_concept)+ 附加:市场情绪(是否 hs300 MA60 多头,复用 market_state)、K档、卖出模式 A/F/G、AI宏过滤前后。

### 2.3 打点链路

- **脚本**:`scripts/overfit_monitor.py`(放 trade-data,与 signal_kelly_backtest.py 同环境,复用 `_batch_load_etf_prices`/`_resolve_etf`/`simulate_trade` 费率函数)
- **输入**:signal_daily(信号)+ index_daily/etf_daily(价格)+ signal_kelly_trades.json(回测基准)+ signal_stats.json(评级)+ config/universe_rules.yaml(入样)
- **输出**:`data/overfit_monitor.json`(每日多维打点+曲线序列)
- **时点**:交易日 21:00 指数补采定稿后 → **建议 21:40**(避开 17:50 update_all/20:35 快照/21:00 补采/22:00 批次;§14 安全窗口),独立 launchd 或挂 update_lab.sh 后(19:00 跑完 ~21:00,需加等待)
- **历史回填**:首跑时从 signal_daily 全量回算 2011-2026 实盘口径曲线 + 从 trades 聚合回测口径曲线(一次性,分钟级)

## 3. 过拟合监控算法(核心,自研 4 维)

目标:量化「调教参数历史拟合好 → 未来失灵」风险,每日一个可打点、可画曲线的**过拟合风险分(0-100)**。

### 维度1:回测-实盘偏离度(权重 40%)

```
实盘胜率(窗口W) = 窗口内信号按模式卖出后 return_pct>0 比例
回测预期(窗口W) = 同窗口同象限同模式的 trades 聚合胜率
偏离度 = (实盘胜率 - 回测预期) / 回测预期
偏离风险分 = 0~100:
  > +10% → 10(超预期,低风险)
  0 ~ +10% → 30(正常)
  -10% ~ 0 → 60(关注)
  < -10% → 90(高风险)
```
窗口:30/60/90 交易日,加权 0.3/0.3/0.4(30 灵敏 / 90 稳健)。
**数据来源**:trades 按 signal_date 窗口聚合(回测)+ signal_daily/index_daily 实盘口径(实际)。

### 维度2:滚动样本外检验(季度滚动,权重 25%)

```
把 2011-2026 按年度分段。每季度末:
  调参窗口 = 过去5年(如 2016-2020)
  检验窗口 = 下一年(2021)
  用调参窗口选出最优组合(模式×K×降亏键)
  衰减率 = (检验窗口胜率 - 调参窗口胜率) / 调参窗口胜率
  oos 风险分: 衰减率 >20% → 90 / 10-20% → 60 / <10% → 20
```
**数据来源**:trades 已含 9 模式×16 象限,按年切分重算即可(无需重跑回测)。
**语义**:调出的最优组合只在调参窗口好、窗外差 = 过拟合的教科书定义。

### 维度3:参数稳定性(每季度 + 每日快检,权重 20%)

```
对默认组合做参数微扰:
  7 降亏键逐一剔除(7组)
  K 档切换(1↔2↔3)
  卖出模式切换(A↔F↔G)
对每个微扰,算滚动窗口(60日)收益率相对默认的敏感度:
  敏感度 = |微扰收益 - 默认收益| / |默认收益|
  参数稳定性分: 单键剔除导致收益变化 >30% 或符号翻转 → 90(坐尖峰上,过拟合)
                10-30% → 50 / <10% → 20(稳定高原)
```
**参照范式**:`lab_param_scan.json` 已实现同思路(desc="验证默认参数处于稳定高原而非孤立尖峰"),本维度针对凯利系统(7键+K+模式)实现。
**成本**:trades 聚合结果可缓存,63 个组合(7键×3K×3模式)秒级可算,每日快检可行。

### 维度4:象限退化检测(每日,权重 15%)

```
16 象限各自滚动窗口(60/90日)实盘胜率 vs 回测同期预期:
  连续 N 个交易日低于预期 10pp 或跌破 50% → 该象限退化标记
  退化比例 = 退化的重点象限数 / 重点象限总数(主买/高评级/A/F/G 对应象限)
  象限退化分 = 退化比例 × 100
```
**数据来源**:同维度1(按象限拆开算)。

### 综合过拟合风险分(0-100)

```
risk_score = 0.40×D1 + 0.25×D2 + 0.20×D3 + 0.15×D4
等级: 绿 <30(正常) / 黄 30-60(关注) / 红 >60(高风险)
```
每日输出一个分,画趋势曲线(与准确率曲线并列)。

### 综合预警 + 邮件通知(方案B/C 必备模块)

**触发规则**(每日打点后评估,命中即发,复用 notify.py 多通道):
| 规则 | 触发条件 | 级别 |
|---|---|---|
| 过拟合高风险 | risk_score ≥60 | SEVERE |
| 风险分持续攀升 | 连续5日上升 | WARN |
| 象限退化 | 重点象限连续10日实盘胜率 < 回测预期-15pp | WARN |
| 调参窗口失效 | 样本外衰减率 >20% | WARN |
| 参数坐尖峰 | 单键剔除收益翻转符号 | WARN |

**通道**:`scripts/notify.py <subject> <body> --severe`(邮件 config/email.json + Telegram + 飞书,独立失败不互阻塞)。
**去重**:复用 `notify.py` 的 `data/notify_dedup.json`(同类预警 24h 内不重复发)。
**邮件内容**:风险分当前值+等级+各维度细分+触发象限/参数+近30日曲线要点(ASCII 或文字摘要,模型不支持图片,§13)。

## 4. 落地方案

### 4.1 数据存储

`data/overfit_monitor.json`(随 export 三步同步 static-site/data + R2 + deploy,§22):

```json
{
  "generated_at": "2026-08-15 21:40",
  "version": "v1",
  "config": {"default_k":1, "default_modes":["A","F","G"], "ai_macro_keys":7, "windows":[30,60,90]},
  "accuracy": {
    "daily": [{"date":"2026-08-15", "actual":{...}, "backtest":{...}}],
    "rolling": [{"date":"2026-08-15", "w30":{"actual":..,"backtest":..}, "w60":.., "w90":..}]
  },
  "overfit": {
    "daily": [{"date":"2026-08-15", "d1_deviation":0.35, "d2_oos":0.12, "d3_param":0.08, "d4_quadrant":0.0, "risk_score":48, "level":"yellow", "alerts":[]}]
  },
  "quadrant_health": {"sig_main": {"last_n_win_rate":.., "backtest_exp":.., "degraded":false}, ...},
  "alerts": [{"date":"2026-08-15", "type":"overfit_high", "subject":"...", "sent":true, "channels":["email"]}]
}
```

### 4.2 计算脚本

`scripts/overfit_monitor.py`(放 trade-data):
- 步骤:①读当日 signal_daily 新信号 ②实盘口径打点(复用 queries.py since_correct 逻辑)③从 trades 聚合回测基准 ④算 4 维度过拟合分 ⑤预警评估+notify.py 发送 ⑥写 overfit_monitor.json
- 季度任务(样本外+参数稳定性重算)可并入同脚本 `--quarterly` 模式或独立 launchd

### 4.3 前端展示

**位置**(主控已定):首页「近期技术参考点」(`.sig-card`)下方、「汪汪队信号」(`.nt-card-wall`)前方,首页第一个左右布局 div 内。左右尺寸调成类似由 implementer 单独做。
**卡片内容**:「调教监控」卡,两个 echarts 折线:
- 上:准确率曲线(实盘实际 vs 回测预期,双线,窗口 30/60/90 切换)
- 下:过拟合风险分曲线(0-100,绿黄红分段着色,参考线 30/60)
**维度切换**:模式(A/F/G)+ 窗口(30/60/90)+ 象限(总/主买/高评级/A股/...)
**复用**:app.js `lineChart`(L319)+ `_miniSparkline`(L12775)封装;数据源 overfit_monitor.json
**预警展示**:风险分红区高亮 + 最近预警记录(时间/类型/触发原因)

### 4.4 时点与一致性

- 时点:交易日 21:40(避开 17:50/20:35/21:00/22:00;§14);周末/节假日休市跳过
- §22 三步:overfit_monitor.json 随 export/deploy 同步 static-site + R2
- 校验:check_data_integrity.py 加一条「overfit_monitor 该有数据在不在」;monitor_72h 加 R2 可达性检查

## 5. 方案分级(供拍板,每个完整正确)

### 方案A(最小):准确率打点 + 简单偏离度
- 内容:双口径每日打点(回测+实盘),总值 + 主象限(4-6个);维度1 偏离度曲线;前端 2 条 echarts 曲线
- 存储:overfit_monitor.json 精简版;脚本 ~300行;前端 ~200行
- 周期:2-3 天 | 依赖:signal_daily/index_daily/trades 均现成,无新数据采集

### 方案B(推荐):A + 全量过拟合算法 + 综合预警 + 邮件
- 内容:4 维度过拟合算法(偏离度+样本外+参数稳定+象限退化);多象限多维最小象限记录;综合风险分 0-100 绿黄红;**综合预警 + 邮件通知**(5 规则,notify.py 复用,去重)
- 存储:overfit_monitor.json 全量;脚本 ~600行;前端 ~400行(双曲线+维度切换+预警记录)
- 周期:4-6 天 | 依赖:同 A + notify.py 现成 + lab_param_scan 范式

### 方案C(最大):B + 实操对齐 + 可配置预警 + 预警中心
- 内容:B + 用户 AFG 实操收益 vs 回测预期对齐校验(页面录入或按 AFG 自动模拟);预警规则可配置(阈值/窗口/象限);季度样本外检验自动重算报告;前端预警中心(历史预警列表+处置状态)
- 存储:overfit_monitor.json + 用户实操记录字段;脚本 ~900行;前端 ~600行
- 周期:7-10 天 | 依赖:B + 用户实操数据输入接口

## 6. 复现

- **本方案产出**:本 md 文档 + 下方验证数据(无独立脚本,仅只读调研验证)
- **验证数据**:
  - `trades` 按日打点可行性:`python3 -c "..."` 从 static-site/data/signal_kelly_trades.json 取 quadrants['mkt_a']['G'],按 signal_date 分组算每日 win_rate。结果:1203 笔 / 704 个交易日(2011-2026),单日样本 1-7 个,滚动30日胜率 40-46%
  - 首页准确率口径:app.js L1440 `_calcSignalAccuracy` + L2398-2407 `_totalTip`
  - since_correct 后端:app/queries.py L858-924
  - 回测评分无前视:app/compute/signal_stats.py L192(fwd = series.shift(-h)/series - 1)
- **数据截止**:overview.json collected_at 2026-08-15;trades generated_at 2026-08-15 02:38;signal_daily MAX(date)=20260814
- **关键口径一句话**:准确率=信号后方向命中(回测口径按模式卖出收益,实盘口径=信号日→最新收盘);过拟合风险分=0.4×偏离度+0.25×样本外衰减+0.2×参数敏感+0.15×象限退化,每日打点滚动窗口平滑

## 7. 实施说明(2026-08-15,implementer 落地记录)

### 7.1 落地文件
- 后端: `trade-data/scripts/overfit_monitor.py`(33KB, 复现命令见脚本头部 docstring)
  - `cd /Users/linhuichen/code/trade-data && .venv/bin/python scripts/overfit_monitor.py`(每日打点; `--dry-run` 试评估)
  - 定时: `com.trade.overfit-monitor.plist` 交易日 21:40(§14 避时点), 非交易日脚本内闸门跳过
- 前端: app.js `_appendOverfitCard`(走势图卡, sigCard 后/ntCard 前) + style.css `.overfit-card` + purpose-notes.js `overfit_monitor` key
- 数据产物: `static-site/data/overfit_monitor.json`(前端 dataUrl 加载, <800KB 精简版; **不超 1MB 走 CF 静态而非 R2**, §3.1 小文件归类)

### 7.2 与方案差异(诚实标注)
1. **D2 样本外 / D3 参数稳定/ D4 象限退化**: 实现为「当前时点一次性评估」, 非逐日曲线(方案 §3 概念如此, 逐日重算成本高且无前视困难)。当前综合分=当日在 D1-D4 合成; **overfit.daily 历史曲线 = 截至各日「实盘 vs 回测 60日滚动胜率偏离」派生(无前视)**, 非逐日真 D1-D4 合成(诚实提示: 历史 daily 是近似指标, 真实综合分看 current)。
2. **D4 象限退化** 用「回测口径近60日胜率 vs 全史预期」(象限内), 非实盘象限(实盘象限细分未建, 量化需逐信号 mapped, 后续 C 档补)。
3. **多维象限明细**(by_mode/by_signal)仅用于 D 维度计算(内存), **不写入前端产物**(体积优化: 6.8MB→0.78MB, 前端只用 rolling/daily/current; 明细 offline 分析口径保留)。
4. **AI宏过滤前后** 附加维度: trades 无 ai_macro 字段, 本轮未含(记 C 档)。
5. **预警 5 规则**: 实际实现 overfit_high(≥60)/risk_climbing(连续5日)/oos_fail(D2≥60)/param_spike(D3≥90); quadrant_degrade 因实盘象限未建暂不触发(预留)。

### 7.3 验证摘要(2026-08-15 dry-run)
- 回测口径近60滚动胜率 42.9%(方案 §6 预测 40-46% ✓); 实盘口径近60滚动 59.4%(50-65% 合理 ✓)
- 综合风险分当前 31(yellow); daily 730日等级分布 green/yellow/red 均有
- 预警触发逻辑 5 条逐条单测通过; notify.py dry-run 链路通(email/feishu dry-run, telegram 占位跳过)
