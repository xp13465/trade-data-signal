# 降亏标志(toggle)实施可行性调研 + 合并 A+B+D 实施计划

> 生成日期：2026-08-09 ｜ 只调研不改代码不commit ｜ 数据源：`signal_kelly_trades.json`(32MB, 177096笔) + `signal_kelly_backtest.py` + `lab.js` + `index_daily`表(hs300) + `overview.json` + docs/kelly-*.md
> 用户需求：把降亏方案(排除buy_aux + MA60大盘择时)做成**可切换toggle开关**，凯利回测页2个独立toggle可组合，未来首页信号旁同样标志开启=自动过滤信号

---

## 0. 摘要（核心结论先讲）

**可行性：完全可行，推荐后端注入 market_state + 前端 toggle 过滤方案。**

1. **buy_aux 排除**：trades.json 每笔交易已含 `signal` 字段（buy_aux 占 28.2%），前端在现有 `_kellyApplyFeeRecompute` 过滤链加一行 `signal != "buy_aux"` 即可，零后端改动。

2. **MA60 大盘择时**：trades.json **不含** market_state 字段，前端无 hs300 日频数据源无法实时算。**推荐后端注入**：`signal_kelly_backtest.py` 加 `_load_market_state`（hs300 MA60，kelly-timing-analysis.md §5.1 已有完整代码）+ 每笔 trade 追加 `market_state` 字段（true=多头进场/false=空头跳过，非A股类标 true 不过滤）。重跑 trades.json 即可。

3. **toggle + 费率客调叠加**：完全正交可叠加。降亏 toggle 改交易集合（filter），费率客调改 profit 计算（_kellyRecomputeTrade），两者在同一重算链 `filter -> recompute -> computeStats` 中互不干扰。

4. **合并 A+B+D**：后端一次改（D修正annualized + 注入market_state）+ 重跑一次 backtest.json/trades.json + 前端一次改（A突出total_profit + B前移return_pct_max_holding + 降亏2 toggle + §21公示）。重跑成本 ~2-3分钟（参考 docs 耗时 ~1.7s/次，含 ETF 价格批量加载）。

---

## 1. trades.json 结构确认

### 1.1 顶层结构

```
{
  "generated_at": "2026-08-09 19:22",
  "buy_amount": 10000,
  "period_cutoffs": {"y1":"20250809", "y3":"20230810", "y5":"20210810", "y10":"20160811", "all":"0"},
  "fields": [19个字段名, 见下],
  "quadrants": {16个象限 -> {A,B,C,D,E,F} -> trades数组}
}
```

### 1.2 fields 字段清单（19个，列式存储）

| 序号 | 字段 | sample值 |
|------|------|---------|
| 0 | signal_date | "20210607" |
| 1 | index_id | "thsc_308700" |
| 2 | **signal** | "buy_special" |
| 3 | buy_date | "20210607" |
| 4 | sell_date | "20210622" |
| 5 | etf_code | "512480" |
| 6 | etf_name | "半导体ETF国联安" |
| 7 | track_tier | "none" |
| 8 | track_score | 36.1 |
| 9 | match_method | "track_index" |
| 10 | track_low_confidence | false |
| 11 | buy_price | 2.246845 |
| 12 | sell_price | 2.396801 |
| 13 | shares | 4448.416259 |
| 14 | profit | 656.861 |
| 15 | return_pct | 6.5686 |
| 16 | hold_days | 10 |
| 17 | sell_reason | "到期" |
| 18 | current_price | 0 |

**关键**：每笔 trade 是**数组**（非 dict），按 fields 顺序排列。前端用 `fIdx = {}; fields.forEach((f,i)=>fIdx[f]=i)` 建索引访问。

### 1.3 signal 值分布（177096笔，全象限汇总）

| signal值 | 笔数 | 占比 |
|---------|------|------|
| buy_special | 80598 | 45.5% |
| **buy_aux** | **50016** | **28.2%** |
| buy | 33840 | 19.1% |
| buy_backup | 12642 | 7.1% |

### 1.4 象限结构

16个并列象限（非互斥，同一信号可归多组）：
- 评级3：rating_high/mid/low
- ETF归类4：etf_strong/related/approx/has_track
- 信号类型4：sig_main/buy, sig_aux/buy_aux, sig_special/buy_special, sig_backup/buy_backup
- 指数大类5：mkt_a/hk/global/industry/concept

每个象限下 6 个卖出模式（A=固定10天/B=3%止盈/C=5%/D=7%/E=5天/F=15天）。

**注意**：`sig_aux` 象限已单独归集 buy_aux 信号，但其他象限（rating_high/mkt_a 等）也含 buy_aux 交易（同一信号归多组）。所以"排除buy_aux"需在**所有**象限的 trades 里过滤，不能只隐藏 sig_aux 卡片。

---

## 2. buy_aux 前端过滤可行性

### 2.1 结论：完全可行，零后端改动

trades.json 每笔交易含 `signal` 字段（fIdx.signal = 2），前端过滤 `t[fIdx.signal] !== "buy_aux"` 即可。

### 2.2 代码切入点：_kellyApplyFeeRecompute（lab.js L7196-7240）

当前过滤逻辑（L7225-7228）：

```javascript
var trades = (cutoff && cutoff !== "0")
  ? rawTrades.filter(function (t) { return (t[fIdx.buy_date] || "") >= cutoff; })
  : rawTrades.slice();
```

**改法**：加 toggle filter 条件：

```javascript
var trades = rawTrades.filter(function (t) {
  if (cutoff && cutoff !== "0" && (t[fIdx.buy_date] || "") < cutoff) return false;
  if (filters.excludeAux && (t[fIdx.signal] || "") === "buy_aux") return false;  // 降亏toggle1
  if (filters.marketTiming && t[fIdx.market_state] !== true) return false;        // 降亏toggle2
  return true;
});
```

### 2.3 重算链不受影响

过滤后的 trades 子集进入 `_kellyRecomputeTrade`（重算费率 profit）-> `_kellyComputeStats`（统计），链路完整不变。`_kellyComputeStats` 接受任意 trades 子集重算（lab.js L7114，参数 `trades` 数组）。

---

## 3. MA60 market_state 注入方案

### 3.1 结论：需后端注入 trades.json，前端无法实时算

**前端无法实时算 MA60**：前端只有 trades.json，没有 hs300 日频数据（index_daily 表在 sentiment.db，前端无 DB 访问）。若前端实时算需额外 fetch hs300 全量日频 JSON（~5966行），且维护 MA60 计算逻辑，复杂且冗余。

**推荐后端注入**：在 `signal_kelly_backtest.py` 生成 trades 时，每笔 trade 追加 `market_state` 字段（bool：true=多头/允许进场，false=空头/跳过）。前端 toggle 开启时直接读字段过滤，零计算。

### 3.2 数据源确认（已验证）

| 项目 | 值 |
|------|-----|
| 表 | `index_daily`（sentiment.db，trade-data/data/ 主库） |
| index_id | `hs300`（非 sh000300，indicators.yaml 中 id=hs300 symbol=sh000300） |
| 行数 | 5966 行 |
| 日期范围 | 2002-01-04 ~ 2026-08-07 |
| 字段 | date, index_id, open, high, low, close, pct_change, amount, net_inflow |
| 2021+ 覆盖 | 1356 个交易日（回测起始 2021 年至今完全覆盖） |

验证命令：`SELECT date,close FROM index_daily WHERE index_id='hs300' ORDER BY date DESC LIMIT 3` -> 20260807/4694.44 等。

### 3.3 后端改代码点（signal_kelly_backtest.py）

**kelly-timing-analysis.md §5.1 已有完整可用代码**，直接采纳：

1. **新增常量**（L46附近）：
```python
MARKET_FILTER_MA_WINDOW = 60
A_STOCK_MARKETS = {"a", "concept", "industry"}
```

2. **新增函数** `_load_market_state(conn)` + `_is_market_bull(signal_date, market_state, market_dates)`（kelly-timing-analysis.md §5.1 完整代码，返回 {date: True/False}）。

3. **compute() 主流程改动**：
   - 读 signal_daily 后、close conn 前，调 `_load_market_state(conn)` 加载 hs300 MA60 状态（同一连接，无需额外数据源）
   - `_load_market_map()` 已存在（L136，返回 {index_id: market}），复用

4. **_backtest_one 返回值追加 market_state 字段**：
   - 传入 `market_state` 参数（bull/bear）
   - 返回 dict 追加 `"market_state": market_state`（bool）
   - **非 A 股类（hk/global）标 true**（不过滤，与 MA60 仅 A 股类策略一致）

5. **TRADE_FIELDS 追加 "market_state"**（L747，fields 从 19 增到 20）

6. **trades_output 写入**：`[t.get(f, "") for f in TRADE_FIELDS]` 自动包含新字段（L780）

### 3.4 体积影响

trades.json 32MB -> 增加约 177096笔 × 5字节("true"/"false") ≈ 0.9MB -> ~33MB。仍在 R2（ssd.fx8.store/data/），无影响。

### 3.5 market_state 字段语义

| 值 | 含义 | toggle开启时行为 |
|----|------|----------------|
| true | hs300 多头(close>MA60) 或 非A股类 | 保留（不过滤） |
| false | hs300 空头 且 A股类信号 | 过滤掉 |

前端 filter：`t[fIdx.market_state] !== true`（false 的过滤，true/undefined 的保留，安全降级）。

### 3.6 备选方案（不推荐）：前端 fetch hs300_ma60_state.json

生成单独 `{date: bool}` JSON，前端 fetch 后按信号日查。缺点：①额外请求 ②前端维护查表逻辑 ③和 trades.json 分离致一致性风险。后端注入更简洁。

---

## 4. toggle + 费率客调叠加可行性

### 4.1 结论：完全正交可叠加

| 维度 | 作用层 | 作用对象 |
|------|--------|---------|
| 降亏 toggle | filter 阶段 | 交易集合（去除 buy_aux / 空头信号） |
| 费率客调 | recompute 阶段 | 单笔 profit 计算（_kellyRecomputeTrade） |

两者在重算链 `filter(交易集) -> recompute(费率profit) -> computeStats(统计)` 中分别作用于不同阶段，互不干扰。

### 4.2 叠加后的重算链

```
_kellyApplyFeeRecompute(feeParams, filters):
  rawTrades -> filter(cutoff + excludeAux + marketTiming)  // 降亏toggle过滤
            -> map(_kellyRecomputeTrade(feeParams))         // 费率客调重算profit
            -> _kellyComputeStats                           // 统计
```

### 4.3 代码改动点

`_kellyApplyFeeRecompute` 当前签名 `(feeParams)`，改为读 `state.labSigKellyFilters`（{excludeAux, marketTiming}）。toggle 切换时调 `_kellyOnFilterChange()`（仿 `_kellyOnFeeChange`，L7257）触发重算。

费率消耗列在过滤后 trades 子集上重算，数值随 toggle 变化（过滤掉的交易不贡献费率消耗），逻辑正确。

---

## 5. toggle UI 设计

### 5.1 放置位置：_renderSigKellyBar 费率档区域（lab.js L7421）

当前 bar 结构（L7455-7468）：
```
<div class="lab-sigkelly-periods">周期tabs</div>
<div class="lab-sigkelly-params">买10000元 · 卖出模式 · 生成时间</div>
<div class="lab-sigkelly-fee-row">费率按钮 + 快捷键提示</div>
<div class="lab-sigkelly-fee-custom">费率输入区</div>
```

**新增 toggle 行**（在 fee-row 之后或之前）：
```
<div class="lab-sigkelly-toggle-row">
  <span class="lab-sigkelly-toggle-label">降亏过滤:</span>
  <label class="lab-sigkelly-toggle">
    <input type="checkbox" class="lab-sigkelly-toggle-aux"> 排除辅关注信号(buy_aux)
  </label>
  <label class="lab-sigkelly-toggle">
    <input type="checkbox" class="lab-sigkelly-toggle-mkt"> MA60大盘择时(仅A股类)
  </label>
  <span class="lab-sigkelly-toggle-hint">独立/组合开启，实时过滤重算</span>
</div>
```

### 5.2 交互逻辑

- 2个 checkbox 独立切换，可单独/组合开启（4种组合：全关/仅aux/仅MA60/组合）
- 切换时调 `_kellyOnFilterChange()`（仿 `_kellyOnFeeChange`）：
  1. 更新 `state.labSigKellyFilters`
  2. 显示 "⏳ 加载交易数据重算…" loading
  3. 调 `_kellyApplyFeeRecompute(feeParams, filters)` 重算
  4. `_renderSigKellyQuadrants` 重渲染卡片
- 费率消耗列随 toggle 变化（过滤掉的交易不贡献费率）

### 5.3 默认状态

toggle 默认**关闭**（显示原始全量数据）。用户开启后实时过滤。未来可加 localStorage 持久化用户偏好。

### 5.4 可选快捷键

仿费率快捷键 0-4+C，可加：
- `A`：切换排除aux
- `M`：切换MA60择时

---

## 6. 未来首页信号旁标志架构复用点

### 6.1 信号数据流

`overview.json` 的 `signals` 字段是 list，286条信号，每条结构：
```json
{
  "date": "20260807",
  "index_id": "cgb_10y_etf",
  "signal": "buy_special",
  "reason": "...",
  "name": "10年国债ETF",
  "symbol": "sh511260",
  "etfs": [...],
  "since_return": null,
  "since_correct": null
}
```

### 6.2 排除 buy_aux 复用（零成本）

首页信号含 `signal` 字段，过滤 `signal === "buy_aux"` 即可，和回测 toggle 逻辑完全一致。

### 6.3 MA60 大盘择时复用

首页信号都是**当日**信号（date 相同），只需一个当日大盘状态。两种方案：

**方案A（推荐）**：overview.json 顶部加 `market_state` 字段（当日 hs300 MA60 多头/空头）。前端 toggle 开启时，对 A股类信号过滤（market_state=false 且 A股类 -> 隐藏）。后端 export.py 生成 overview.json 时注入（复用 _load_market_state 逻辑取当日状态）。

**方案B**：首页信号每条加 `market_state` 字段（和 trades.json 一致）。冗余但统一。

推荐方案A：首页信号同日，一个全局字段足够，简洁。

### 6.4 A股类判断

首页信号有 `index_id`，需判断是否 A股类（a/concept/industry）。前端无 indicators.yaml，两种方式：
- 后端在信号里注入 `market` 字段（从 indicators.yaml 查）
- 前端用 index_id 前缀判断（thsc_/sw_/sh/sz/csi 等，但不严谨）

推荐后端注入 `market` 字段到 overview.json 信号，或前端用 index_id 前缀粗判（hk/global 类有明显前缀特征）。

### 6.5 复用点总结

| 降亏条件 | 回测页(trades.json) | 首页(overview.json) | 复用度 |
|---------|--------------------|--------------------|-------|
| 排除buy_aux | filter signal!=buy_aux | filter signal!=buy_aux | 100%相同 |
| MA60择时 | trade.market_state字段 | overview.market_state全局字段 | 逻辑相同数据源不同 |

---

## 7. 合并 A+B+D 实施计划

### 7.1 方案回顾（docs/kelly-return-linear-analysis.md §5）

| 方案 | 内容 | 改动层 |
|------|------|--------|
| A | 突出 total_profit（元）的窗口增长 | 前端展示 |
| B | 前移 return_pct_max_holding（最大持仓收益率） | 前端展示 |
| D | 修正 annualized_return（用累积收益率开方非平均化） | 后端计算+前端同步 |
| 降亏 | 2个toggle（排除aux + MA60择时） | 后端注入+前端toggle |

### 7.2 后端改动（signal_kelly_backtest.py，一次改完）

| 改点 | 位置 | 内容 |
|------|------|------|
| D-修正年化 | `_annualized_return` L444-466 | `r` 从 `total_return_pct/100`（平均化）改为 `return_pct_max_holding/100`（累积收益率）。y1/y3/y5/y10/all 统一用 `(1+r)^(1/年数)-1` |
| 降亏-注入market_state | `_backtest_one` L237 + compute() L604 | 加 `_load_market_state` + `_is_market_bull`（kelly-timing-analysis.md §5.1 代码），trade 追加 market_state 字段 |
| TRADE_FIELDS | L747 | 追加 "market_state" |
| _compute_stats | L550-552 | annualized 调用改传 return_pct_max_holding（注意：return_pct_max_holding 在 L550 算，annualized 在 L552 调，需调整顺序或先算 rmh 再算 annualized） |

**D修正细节**：
- 当前 `_annualized_return(total_return_pct, period_key, trades)` 接收 total_return_pct（平均化）
- 改为接收 `return_pct_max_holding`（累积收益率 = total_profit/峰值占用资金*100）
- `_compute_stats` L552 调用处改为 `_annualized_return(return_pct_max_holding, period_key, trades)`
- 注意顺序：return_pct_max_holding 依赖 max_concurrent_capital（L548），须在 L548 之后调 annualized（当前 L552 已在 L548 后，顺序OK）

### 7.3 前端改动（lab.js，一次改完）

| 改点 | 位置 | 内容 |
|------|------|------|
| D-同步年化 | `_kellyAnnualizedReturn` L7100-7118 | 同步后端改法：r 从 totalReturnPct/100 改为 returnPctMaxHolding/100 |
| D-调用处 | `_kellyComputeStats` L7154 | 传参改为 return_pct_max_holding（L7149 已算，顺序OK） |
| A-突出total_profit | `_renderSigKellyCard` L7856 | 强化视觉（加粗/配色/趋势箭头），位置第7列 |
| B-前移rmh | `_renderSigKellyCard` L7932 表头 | return_pct_max_holding 列前移到"最终盈亏"附近，改名"累积收益率(按峰值资金)" |
| 降亏-toggle UI | `_renderSigKellyBar` L7455 | 新增 toggle-row（2 checkbox） |
| 降亏-toggle逻辑 | 新增 `_kellyOnFilterChange` + `_kellyApplyFeeRecompute` 加 filters 参数 | 仿 `_kellyOnFeeChange` |
| 降亏-state | state 新增 `labSigKellyFilters` | {excludeAux:false, marketTiming:false} |
| §21-公示 | 算法说明文案 | grep 年化/annualized 更新文案"年化基于峰值资金累积收益率开方"；新增"降亏过滤：排除辅关注信号/A股类MA60择时"说明 |

### 7.4 重跑流程

1. cwd `/Users/linhuichen/code/trade-data`（§9 读主库）
2. `python3 scripts/signal_kelly_backtest.py` 重跑生成 backtest.json + trades.json（含 market_state 字段）
3. 生成 .gz（脚本内置）
4. **路径同步**（§9 衍生陷阱）：export 写 trade-data/static-site/data/，deploy.sh 从 trade/static-site/data/ 推，需 cp 或确认 rsync 同步
5. upload R2：trades.json 33MB 走 R2（ssd.fx8.store/data/），backtest.json 306KB 走 CF
6. 耗时参考：~1.7s/次（含 ETF 价格批量加载），21组模拟36s，单次重跑 <3分钟

### 7.5 §21 算法公示同步

实施后须更新前端算法说明文案（grep 以下关键词找全公示点）：
- `年化` / `annualized`：改为"年化基于峰值资金累积收益率开方"
- 新增"降亏过滤"说明：排除辅关注信号(buy_aux) / A股类信号在沪深300 MA60空头时不进场
- 公示位置：`_renderSigKellyCard` 卡片描述 L7918 + `_renderSigKellyBar` 说明区 + 卡间比较水印 hoverpop L7804

### 7.6 时序

1. 后端改 signal_kelly_backtest.py（D修正 + market_state注入）
2. 重跑 backtest.json + trades.json
3. 前端改 lab.js（D同步 + A突出 + B前移 + 降亏toggle + §21公示）
4. build_min.py + bump_asset_version.py + bump sw.js CACHE_VERSION（§9）
5. reviewer agent 验收（§15 B级逻辑改动：跨函数影响面 + smoke）
6. deploy.sh 上线（push feat + merge main + push main）
7. curl 验数据层（trades.json 含 market_state 字段 + 年化数值变化）（§8 验功能生效层）

### 7.7 耗时估算

- 后端改+重跑：~30分钟（改代码10分 + 重跑3分 + 验证）
- 前端改：~1-2小时（toggle + A/B展示 + D同步 + 公示）
- 总计：~2-3小时

---

## 8. 风险/坑

### 8.1 market_state 注入的 trade 体积

trades.json 32MB -> 33MB（+0.9MB）。仍走 R2，无影响。但 deploy.sh 需确认 upload-r2 覆盖 trades.json。

### 8.2 D修正年化的数值变化

年化数值会显著变化（如 sig_main A y5：当前0.18% -> 修正后~2.49%）。需 §21 公示同步，否则用户困惑。卡间比较水印的综合分（年化35%权重）也会变化，需确认排名合理性。

### 8.3 toggle 过滤后样本量

组合开启（排除aux + MA60）过滤53%信号（docs/kelly-loss-reduction-analysis.md §4.3，6152->2908笔）。部分象限（rating_high/sig_backup）样本可能 <100，统计意义弱。卡片已有 n<100 提示（L7496 legend），无需额外处理。

### 8.4 前端 _kellyAnnualizedReturn 与后端 _annualized_return 必须同步

D修正必须前后端同步改。前端 `_kellyAnnualizedReturn`（L7100）是费率客调/toggle 重算时用的，若只改后端不改前端，则默认显示用新公式、toggle切换后用旧公式，数据不一致（§22 数据一致性铁律）。

### 8.5 export 输出路径同步（§9 衍生陷阱）

signal_kelly_backtest.py cwd trade-data 写 JSON 落 trade-data/static-site/data/，但 deploy.sh 从 trade/static-site/data/ 推 git。重跑后必须 cp 或确认 rsync 同步，否则推旧版（§18 教训）。

### 8.6 MA60 仅 A股类的 market 字段判断

market_state 注入需判断信号是否 A股类（a/concept/industry）。`_load_market_map()`（L136）已存在返回 {index_id: market}，复用。非 A股类（hk/global/hk_industry）标 market_state=true（不过滤）。

### 8.7 持仓中 trade 的 market_state

持仓中 trade（sell_date=""）也有 buy_date，market_state 按买入日算。toggle 过滤持仓中 trade 时，其预估盈亏也被过滤，影响 holding_count 统计。逻辑正确（持仓中 trade 也是当时进场的信号）。

### 8.8 未来首页 MA60 的实时性

首页信号是当日，market_state 取当日 hs300 收盘 vs MA60。若盘中（hs300 未收盘）信号已出，market_state 应取前一日收盘状态（盘中当日 close 未定）。后端注入时用 `_is_market_bull` 的 bisect 查找 <= signal_date 的最近交易日，自动处理（kelly-timing-analysis.md §5.1 _is_market_bull 已实现此逻辑）。

---

## 附录 A：关键代码位置速查

| 文件 | 行号 | 函数/内容 |
|------|------|----------|
| signal_kelly_backtest.py | L49 | BUY_SIGNALS 元组 |
| signal_kelly_backtest.py | L136 | _load_market_map (复用) |
| signal_kelly_backtest.py | L237 | _backtest_one (加market_state参数) |
| signal_kelly_backtest.py | L444 | _annualized_return (D修正) |
| signal_kelly_backtest.py | L482 | _compute_stats |
| signal_kelly_backtest.py | L550 | return_pct_max_holding 计算 |
| signal_kelly_backtest.py | L552 | annualized 调用 (改传参) |
| signal_kelly_backtest.py | L604 | compute() 主循环 (加_load_market_state) |
| signal_kelly_backtest.py | L747 | TRADE_FIELDS (加market_state) |
| lab.js | L6979 | KELLY_FEE_PRESETS |
| lab.js | L6995 | _kellyRecomputeTrade (费率重算) |
| lab.js | L7100 | _kellyAnnualizedReturn (D同步) |
| lab.js | L7114 | _kellyComputeStats |
| lab.js | L7196 | _kellyApplyFeeRecompute (加filters) |
| lab.js | L7257 | _kellyOnFeeChange (仿写_kellyOnFilterChange) |
| lab.js | L7421 | _renderSigKellyBar (加toggle-row) |
| lab.js | L7830 | _renderSigKellyCard (A突出+B前移) |
| lab.js | L7804 | 卡间比较水印 (§21公示) |

## 附录 B：引用文档

- `docs/kelly-loss-reduction-analysis.md`：21组降亏穷举模拟，最佳组合 MA60+排除aux 减亏64%
- `docs/kelly-timing-analysis.md`：MA60大盘择时方案，§5.1 完整 _load_market_state/_is_market_bull 代码
- `docs/kelly-return-linear-analysis.md`：A+B+C+D 方案分析，D修正年化语义
- `docs/kelly-fee-adjust.md`：费率客调方案A（_kellyRecomputeTrade 重算链）
- `docs/kelly-fee-presets.md`：6档费率预设+快捷键

## 附录 C：MA60 _load_market_state / _is_market_bull 完整代码（kelly-timing-analysis.md §5.1，直接可用）

```python
MARKET_FILTER_MA_WINDOW = 60
A_STOCK_MARKETS = {"a", "concept", "industry"}

def _load_market_state(conn):
    """加载沪深300日频, 计算 MA60, 返回 {date: True(多头)/False(空头)}。"""
    rows = conn.execute(
        "SELECT date, close FROM index_daily WHERE index_id='hs300' "
        "AND close IS NOT NULL ORDER BY date"
    ).fetchall()
    if not rows:
        print("  ⚠ hs300 数据为空, 大盘择时过滤不生效", file=sys.stderr)
        return {}, []
    dates = [r[0] for r in rows]
    closes = [r[1] for r in rows]
    ma_window = MARKET_FILTER_MA_WINDOW
    state = {}
    for i in range(ma_window - 1, len(dates)):
        ma = sum(closes[i - ma_window + 1 : i + 1]) / ma_window
        state[dates[i]] = closes[i] > ma
    return state, dates

def _is_market_bull(signal_date, market_state, market_dates):
    """判断信号日的大盘状态。查找 <= signal_date 的最近有 MA60 的交易日。"""
    if not market_state:
        return True
    import bisect
    idx = bisect.bisect_right(market_dates, signal_date) - 1
    while idx >= 0:
        d = market_dates[idx]
        if d in market_state:
            return market_state[d]
        idx -= 1
    return True
```
