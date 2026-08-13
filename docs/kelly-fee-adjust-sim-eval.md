# 模拟回测费率客调可实施性评估

> 调研日期: 2026-08-08 | 只读调研不改代码 | 产出供主控整理给用户确认后实施
> 关联: docs/kelly-fee-adjust.md(凯利费率客调方案A 已实施)

## 0. 结论速览

**可实施,且比凯利更容易。** 模拟回测费率模型只有 commission_rate+slippage 两个参数(无最低佣金/过户费/印花税),默认费率=0(毛收益),trades 存了 bp/sp/at/cp 可完整重算。凯利费率客调代码可复用约 50%,工作量约 330 行 JS+CSS。

核心决策点:模拟回测费率客调用简单模型(和 lab_simulate.py 一致,2 参数)还是复杂模型(和凯利/simulate_trade.py 一致,5 参数)。推荐简单模型(和数据生成逻辑一致)。

---

## 1. 数据架构(前端读什么)

### 1.1 前端模拟回测卡片数据源

| 文件 | 生成脚本 | 大小 | 内容 |
|------|---------|------|------|
| `lab_sim_{index}_stats.json` | `scripts/lab/lab_simulate.py` | ~几百KB | stats(每窗口) + strategies + pairs 结构 |
| `lab_sim_{index}_full.json` | `scripts/lab/lab_simulate.py` | 大(按需加载) | trades + equity_curve + win_trades + open_positions |
| `lab_cost_compare.json` | `scripts/lab/lab_cost_compare.py` | 小 | 成本对比预设3档(gross/low/high),只覆盖top10配对×2窗口 |

前端加载流程(lab.js):
- `fetchLabSimData(index)` -> R2 加载 stats JSON,缓存 `state.labSimDataMap[index]`
- `fetchLabSimFullData(index)` -> R2 加载 full JSON,合并 trades/equity_curve/win_trades/open_positions 到 stats 缓存
- `fetchLabCostCompare()` -> CF 加载成本对比 JSON,缓存 `state._labCostCompare`

### 1.2 stats JSON 结构

```
simData = {
  index_id, index_name, initial_capital: 100000,
  etf_code, etf_name, etf_approx,       // <-- etf_code 在顶层(L1820),前端可读
  commission_rate: 0, slippage: 0,       // <-- 费率常量(默认0!)
  windows: [{k,l,s,e}, ...],
  strategies: {key: {side, partners}},
  pairs: {"buy_key|sell_key": {
    full_in:   {stats: {all,y10,y5,y3,y1: {total_ret,annual_ret,max_drawdown,win_rate,n_trades,final_total,years,sharpe,sortino,profit_factor,payoff_ratio,expectancy}}},
    fixed_10k: {stats: {all,y10,y5,y3,y1: {...同上}}}
  }}
}
```

### 1.3 full JSON 结构(按需合并入 stats 缓存)

```
pairs[pairKey][mode] = {
  equity_curve: {all,y10,y5,y3,y1: [{date,value},...]},  // 采样100点
  trades: [{bd,bp,sd,sp,ret,hd,at,cp},...],              // 全史trades
  tw: {all,y10,y5,y3,y1: [start_idx, end_idx]},          // 窗口切片索引
  win_trades: {all,y10,y5,y3,y1: [{...trade},...]},       // 每窗口独立sim的trades
  win_base_cp: {all,y10,y5,y3,y1: float},                 // 窗口起点基准盈亏
  open_positions: {all,y10,y5,y3,y1: [{buy_date,buy_price,last_close,shares,hold_days,unrealized_pnl,unrealized_pnl_pct}]}
}
```

---

## 2. 凯利费率客调代码分析(已实现)

### 2.1 已实现组件(lab.js L6975-7369)

| 组件 | 行号 | 功能 |
|------|------|------|
| `KELLY_FEE_PRESETS` | L6979-6986 | 6档预设(zero/etf_def/etf_main/etf_cheap/stock_def/custom),每档5参数 |
| `KELLY_ORIG_SLIPPAGE` | L6978 | 原始滑点0.001,用于还原close价 |
| `_kellyIsShEtf(etfCode)` | L6989-6992 | 沪市ETF判断(51/58开头) |
| `_kellyRecomputeTrade` | L6995-7033 | 按新费率重算单笔trade的profit/return_pct/fee_cost |
| `_kellyComputeKelly` | L7036-7044 | 凯利公式 |
| `_kellyMaxConcurrent` | L7047-7060 | 最大同时持仓 |
| `_kellyMaxDrawdown` | L7082-7098 | 最大回撤(按sell_date排序profit累积) |
| `_kellyAnnualizedReturn` | L7103-7113 | 年化收益率 |
| `_kellyComputeStats` | L7116-7188 | 完整统计20+指标 |
| `_kellyApplyFeeRecompute` | L7191-7252 | 加载trades.json+遍历quadrant×period×mode重算 |
| `_kellyOnFeeChange` | L7255-7291 | 费率切换处理(预设档) |
| `_kellyOnFormChange` | L7294-7312 | 自定义输入处理 |
| `_kellyReadCustomParams` | L7315-7329 | 读取自定义费率输入框值 |
| 费率控件UI | L7456 | 预设档按钮HTML |
| 快捷键 | L7353-7369 | 0-4+C快捷切换 |

### 2.2 凯利重算链

```
用户调费率 -> _kellyOnFeeChange(presetKey)
  -> 更新 state.labSigKellyFeeParams
  -> _kellyApplyFeeRecompute(feeParams)
    -> 加载 trades.json (32MB, R2+CF兜底)
    -> 遍历 quadrant × period × mode
      -> 每笔 trade: _kellyRecomputeTrade(tradeArr, fIdx, feeParams, buyAmount)
        -> 还原 close: closeBuy = buy_price / (1 + KELLY_ORIG_SLIPPAGE)
        -> 重算买入: sharesNew = buyAmount / (buyPriceNew * (1 + c + sh))
        -> 重算卖出: netNew = sellAmountNew - commSell - transferFee - stampDuty
        -> 费率消耗: feeCost = profit0 - profitNew
      -> 聚合: _kellyComputeStats(recomputed, periodKey, buyAmount)
  -> _renderSigKellyQuadrants(host, data, period)  // 重新渲染
```

凯利每笔独立固定买额 BUY_AMOUNT=10000,费率只影响每笔 profit,可独立重算再聚合。

---

## 3. 模拟回测费率现状

### 3.1 当前费率: 0(毛收益!)

`lab_simulate.py` 的 simulate_full_in / simulate_fixed_10k 默认参数:
```python
def simulate_full_in(df, buy_mask, sell_mask, w_start=None, commission_rate=0.0, slippage=0.0):
def simulate_fixed_10k(df, buy_mask, sell_mask, w_start=None, commission_rate=0.0, slippage=0.0):
```

`build_pair_result` 调用时**不传费率参数**(L579):
```python
raw = sim_func(df, buy_mask, sell_mask, w_start=w_start)
# commission_rate=0.0, slippage=0.0 (默认值)
```

**结论: 模拟回测卡片当前展示的是毛收益(费率=0),无任何费率客调控件。**

### 3.2 成本对比块(预设3档,不可调)

前端 `_labSimModeBlock` (L2067-2094) 展示成本对比表:
- 数据源: `lab_cost_compare.json` (由 `scripts/lab/lab_cost_compare.py` 生成)
- 预设3档: gross(毛/0费) / low(万3+千1) / high(万5+千2)
- 覆盖范围: top10配对×2窗口(all/y5),非全覆盖
- **只展示不可调**,无交互控件

### 3.3 stats JSON 中的费率字段

stats_json 顶层有费率常量(simulate_trade.py 的 _generate_json L1816-1819):
```python
'commission_rate': COMMISSION_RATE,   # 0.0003
'slippage': SLIPPAGE,                 # 0.001
```

但这是 simulate_trade.py(trade_sim_{index}_stats.json)的输出。**lab_simulate.py 的输出没有费率字段**(因为默认0,没必要存)。

注意: 前端模拟回测卡片读的是 `lab_sim_{index}_stats.json`(lab_simulate.py 生成),不是 `trade_sim_{index}_stats.json`(simulate_trade.py 生成)。两个是不同功能:
- lab_sim -> 策略实验室配对交易回测(128组配对×2模式×5窗口)
- trade_sim -> 单信号回测详情弹窗(app.js _tradeSimOpenModal)

---

## 4. 费率模型对比(凯利 vs 模拟回测)

### 4.1 凯利费率模型(simulate_trade.py + signal_kelly_backtest.py)

```
5参数: commission_rate, min_commission, slippage, transfer_fee_rate_sh, stamp_duty_rate

买入 _buy_with_fees(budget, close, etf_code):
  buy_price = close * (1 + SLIPPAGE)
  shares = budget / (buy_price * (1 + COMMISSION_RATE + sh_rate))
  commission = shares * buy_price * COMMISSION_RATE
  if commission < MIN_COMMISSION:  # 最低佣金分支
    shares = (budget - MIN_COMMISSION) / (buy_price * (1 + sh_rate))
    commission = MIN_COMMISSION
  transfer_fee = gross * sh_rate  # 沪市过户费

卖出 _sell_with_fees(shares, close, etf_code):
  sell_price = close * (1 - SLIPPAGE)
  commission = max(sell_amount * COMMISSION_RATE, MIN_COMMISSION)
  transfer_fee = sell_amount * sh_rate
  net = sell_amount - commission - transfer_fee  # 无印花税(ETF)
```

### 4.2 模拟回测费率模型(lab_simulate.py)

```
2参数: commission_rate, slippage

买入(simulate_full_in L326-327):
  buy_price = close * (1 + slippage)
  shares = cash / (buy_price * (1 + commission_rate))

卖出(simulate_full_in L335-339):
  sell_price = close * (1 - slippage)
  sell_amount = shares * sell_price
  cash = sell_amount * (1 - commission_rate)  # 简单扣费

fixed_10k 买入(L412-413):
  buy_price = close * (1 + slippage)
  shares = POSITION_SIZE / (buy_price * (1 + commission_rate))

fixed_10k 卖出(L423-429):
  sell_price = close * (1 - slippage)
  sell_amount = total_shares * sell_price
  cash += sell_amount * (1 - commission_rate)
```

### 4.3 关键差异

| 维度 | 凯利(simulate_trade.py) | 模拟回测(lab_simulate.py) |
|------|------------------------|--------------------------|
| 参数数 | 5(commission/min/slippage/transfer/stamp) | **2(commission/slippage)** |
| 默认费率 | 万3+千1+最低5+过户费 | **0(毛收益)** |
| 最低佣金 | 5元(小单兜底) | **无** |
| 过户费 | 沪市万0.1 | **无** |
| 印花税 | 股票万5 | **无** |
| 买入公式 | 含最低佣金分支(复杂) | 简单除法 shares=budget/(price*(1+c)) |
| 卖出公式 | 含最低佣金+过户费 | 简单乘法 cash=amount*(1-c) |
| 前端费率客调 | 已实现(6档预设+自定义) | **无** |

---

## 5. trades 字段与重算可行性

### 5.1 trades 字段(lab_simulate.py L343-352)

```python
{
  'bd': '2025-01-15',    # 买入日期
  'bp': 3.45,            # 买入价(含滑点, 默认slippage=0时=close)
  'sd': '2025-02-20',    # 卖出日期
  'sp': 3.52,            # 卖出价(含滑点, 默认slippage=0时=close)
  'ret': 2.03,           # 收益率% = (sp-bp)/bp*100
  'hd': 36,              # 持有天数
  'at': 102030.5,        # 账户总资金(卖出后)
  'cp': 2030.5,          # 累计盈亏 = at - INITIAL_CAPITAL
}
```

### 5.2 重算可行性分析

**默认 slippage=0 -> bp=close_buy, sp=close_sell, 无需还原!**

#### full_in(全仓复利)重算:

```
budget[0] = INITIAL_CAPITAL (100000)
对每笔 trade i:
  close_buy = trade.bp   (因为 original slippage=0)
  close_sell = trade.sp  (因为 original slippage=0)

  # 用新费率重算
  buy_price_new = close_buy * (1 + new_slippage)
  shares_new = budget[i] / (buy_price_new * (1 + new_commission))
  sell_price_new = close_sell * (1 - new_slippage)
  sell_amount_new = shares_new * sell_price_new
  net_proceeds_new = sell_amount_new * (1 - new_commission)

  # 递推
  at_new[i] = net_proceeds_new   (全仓, 卖出后全部现金)
  cp_new[i] = at_new[i] - INITIAL_CAPITAL
  ret_new[i] = (sell_price_new - buy_price_new) / buy_price_new * 100
  budget[i+1] = net_proceeds_new  (复利: 下次买入=本次卖出净到账)
```

**可精确重算!** full_in 一次只持一笔, budget 递推链完整。

#### fixed_10k(定额10%)重算:

```
每笔买入: budget = POSITION_SIZE (10000, 固定)
  close_buy = trade.bp  (avg_buy_price, original slippage=0)
  shares_new = POSITION_SIZE / (close_buy * (1+new_s) * (1+new_c))

清仓卖出:
  close_sell = trade.sp
  sell_price_new = close_sell * (1 - new_s)
  sell_amount_new = total_shares_new * sell_price_new
  net_proceeds_new = sell_amount_new * (1 - new_c)

  ret_new = (sell_price_new - buy_price_new) / buy_price_new * 100
  # ret 可精确重算

  # at/cp 递推
  cash -= POSITION_SIZE (每次买入)
  cash += net_proceeds_new (每次清仓)
  at_new = cash
  cp_new = at_new - INITIAL_CAPITAL
```

**ret 可精确重算; at/cp 有小精度问题**: fixed_10k 多笔持仓汇总(avg_buy_price), 不知每笔的 close, total_shares_new 只能近似(用 avg_buy_price 代替各笔 close)。但误差不大(avg_buy_price 是加权平均, 近似合理)。

#### equity_curve 重建:

```
equity_curve = [{date: start, value: INITIAL_CAPITAL}]
对每笔 trade:
  # 买入日打点(C方案: cash + 持仓市值)
  equity_curve.push({date: trade.bd, value: cash_before_buy + shares_new * close_buy})
  # 卖出日打点
  equity_curve.push({date: trade.sd, value: at_new})
# 期末打点
equity_curve.push({date: last_date, value: final_total_new})
```

**可重建!** 因为 bp=close(默认slippage=0), 可算买入日打点。

#### max_drawdown 重算:

```
从重建的 equity_curve 算(L210-219):
  vals = equity_curve.map(e => e.value)
  peak = vals[0]
  for v in vals[1:]:
    if v > peak: peak = v
    dd = (peak - v) / peak * 100
    max_dd = max(max_dd, dd)
```

**可重算!** max_drawdown 基于采样 equity_curve(100点), 重建的 equity_curve 精度和后端一致(相同打点逻辑)。

### 5.3 stats 重算

| stats 字段 | 重算方式 | 精度 |
|-----------|---------|------|
| total_ret | (final_total_new - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100 | 精确 |
| annual_ret | ((final_total_new / INITIAL_CAPITAL) ** (1/years) - 1) * 100 | 精确(years不变) |
| max_drawdown | 从重建 equity_curve 算 | 精确(同打点逻辑) |
| win_rate | len(trades.filter(t=>t.ret_new>0)) / len(trades) * 100 | 精确 |
| n_trades | len(trades) | 不变 |
| final_total | 递推 cash + 持仓市值 | 精确(full_in) / 近似(fixed_10k) |
| sharpe | 从重建 equity_curve 算 | 精确 |
| sortino | 从重建 equity_curve 算 | 精确 |
| profit_factor | sum(win_rets) / abs(sum(loss_rets)) | 精确 |
| payoff_ratio | avg_win / abs(avg_loss) | 精确 |
| expectancy | win_rate*avg_win + loss_rate*avg_loss | 精确 |

---

## 6. 凯利代码复用方案

### 6.1 逐组件复用率

| 凯利代码组件 | 复用率 | 适配说明 |
|-------------|--------|---------|
| `KELLY_FEE_PRESETS` (6档5参数) | 60% | 简化为2参数(commission+slippage), 预设档改为: 0%剥离/0.3%真实/1%保守/自定义 |
| `KELLY_ORIG_SLIPPAGE` | 0% | 模拟回测默认slippage=0, bp=close, 无需还原 |
| `_kellyIsShEtf` | 0% | 模拟回测无过户费, 不需要 |
| `_kellyRecomputeTrade` | 70% | 逻辑通用, 适配: 字段名(trades.bp/sp vs tradeArr[fIdx]) + full_in复利递推 + 简单费率模型(无最低佣金) |
| `_kellyComputeKelly` | 0% | 模拟回测无凯利公式 |
| `_kellyMaxConcurrent` | 0% | 模拟回测不展示最大持仓 |
| `_kellyMaxDrawdown` | 30% | 模拟回测从equity_curve算(不是profit累积), 逻辑不同 |
| `_kellyAnnualizedReturn` | 80% | 公式相同, 适配参数 |
| `_kellyComputeStats` | 20% | 指标不同(模拟回测有sharpe/sortino/profit_factor, 无凯利/最大持仓/连胜连败) |
| `_kellyApplyFeeRecompute` | 40% | 遍历结构不同(pairs×mode×win vs quadrant×period×mode), 数据加载不同 |
| `_kellyOnFeeChange` | 70% | 交互逻辑通用, 改渲染目标(_rerenderSim) |
| `_kellyOnFormChange` | 70% | 同上 |
| `_kellyReadCustomParams` | 50% | 简化为2参数(commission+slippage) |
| 费率控件UI(预设档+自定义) | 80% | HTML结构复用, 适配位置/样式/预设档简化 |
| 快捷键 | 80% | 逻辑复用, 适配labSubMode判断 |

### 6.2 整体复用率: 约 50%

主要复用: 预设档数据结构、费率控件UI、重算框架、交互逻辑。
主要新写: _simRecomputeTrade(适配字段名+复利递推)、_simRecomputeStats(适配指标)、_simRebuildEquityCurve(重建净值曲线)、_simApplyFeeRecompute(适配遍历结构)。

---

## 7. 工作量估算

| 任务 | 行数 | 说明 |
|------|------|------|
| 费率控件UI (HTML+CSS) | ~50 | 复用凯利预设档, 简化为2参数(佣金率+滑点), 放模拟回测卡片顶部 |
| `_simRecomputeTrade` | ~60 | 适配字段名(trades.bp/sp) + full_in复利递推 + fixed_10k固定买额 + 简单费率模型 |
| `_simRecomputeStats` | ~70 | 适配模拟回测stats(total_ret/annual_ret/max_drawdown/win_rate/sharpe/sortino/profit_factor) |
| `_simRebuildEquityCurve` | ~30 | 从重算trades重建equity_curve(买卖日打点+期末) |
| `_simApplyFeeRecompute` | ~60 | 遍历pairs×mode×win重算, 需full数据已加载 |
| 交易记录表同步 | ~30 | profit/ret/at/cp列用新值, 保留原值对比(可选) |
| `_simOnFeeChange` | ~30 | 仿凯利交互, 改渲染目标(_rerenderSim) |
| 合计 | **~330行 JS+CSS** | |

---

## 8. 障碍点与风险

### 8.1 费率模型决策(需用户确认)

**问题**: 模拟回测费率客调用简单模型(2参数, 和lab_simulate.py一致)还是复杂模型(5参数, 和凯利/simulate_trade.py一致)?

| 方案 | 优点 | 缺点 |
|------|------|------|
| 简单模型(2参数) | 和数据生成逻辑一致; 重算简单; 交互直观 | 无最低佣金/过户费, 和凯利费率档不完全对应 |
| 复杂模型(5参数) | 和凯利一致; 更精确 | 和lab_simulate.py模型不一致; 重算复杂; 需额外实现最低佣金分支 |

**推荐**: 简单模型(2参数)。理由:
1. 和 lab_simulate.py 的数据生成逻辑一致, 重算结果和后端一致
2. 如果用复杂模型, 前端重算的费率逻辑和后端不同(后端是简单模型), 结果不可验证
3. 模拟回测是配对交易(ETF/指数), 无印花税, 最低佣金影响小(买额10000时佣金3元<5元, 但简单模型不收最低佣金)
4. 用户可调 commission+slippage 看费率影响, 已足够直观

### 8.2 fixed_10k 的 at/cp 精度

fixed_10k 多笔持仓汇总(avg_buy_price), 不知每笔的 close, total_shares_new 只能近似。
- **影响**: at/cp 列有轻微误差, 但 ret(收益率)精确
- **缓解**: 可标注"近似重算", 或后续后端补每笔 close 字段

### 8.3 full 数据依赖

费率重算需要 full 数据(trades/win_trades), 用户首次调费率时需等 full 加载(大文件, 有进度条)。
- **影响**: 首次调费率有延迟(取决于网络)
- **缓解**: 显示 loading "正在加载交易数据重算费率...", 复用凯利的 loading 文案

### 8.4 多配对×多窗口遍历性能

9指数×128配对×2模式×5窗口 = 11520 组合, 但:
- 用户只看当前选中指数的当前配对, 不需要全量重算
- 只重算当前配对×2模式×5窗口 = 10组, 每组几十到几百笔trade, 重算<10ms
- **性能无忧**

### 8.5 equity_curve 重建精度

重建的 equity_curve 只有买卖日打点(和后端一致), 但后端还有买入日打点(C方案 cash+持仓市值)。
- full_in: 买入后cash=0, 打点=shares*close, 可用bp(=close)算
- fixed_10k: 买入后cash-=10000, 打点=cash+sum(shares*close), 需要各笔close
- **fixed_10k 买入日打点有小精度问题**, 但对max_drawdown影响小(买入日总资产变化主要是cash减少, 不是峰值)

---

## 9. 实施计划

### Phase 1: 费率控件UI (~50行)
- 复用凯利预设档HTML结构, 简化为2参数
- 预设档: 0%剥离(commission=0,slippage=0) / 0.3%真实(0.0003,0.001) / 1%保守(0.0005,0.002) / 自定义
- 位置: 模拟回测卡片顶部, 和窗口切换条同行或上方

### Phase 2: _simRecomputeTrade (~60行)
- 输入: trade对象(bp/sp/bd/sd), feeParams(commission+slippage), mode(full_in/fixed_10k), budget/INITIAL_CAPITAL
- full_in: 递推budget, 重算shares/sell_amount/net_proceeds/at/cp/ret
- fixed_10k: 固定POSITION_SIZE, 重算shares(近似)/ret(精确)/at/cp(递推)

### Phase 3: _simRebuildEquityCurve + _simRecomputeStats (~100行)
- 从重算trades重建equity_curve(买卖日打点+期末)
- 从重建equity_curve算max_drawdown/sharpe/sortino
- 从重算trades算total_ret/annual_ret/win_rate/profit_factor/payoff_ratio/expectancy

### Phase 4: _simApplyFeeRecompute + 渲染同步 (~90行)
- 遍历当前配对的pairs×mode×win重算
- 交易记录表: ret/at/cp列用新值
- 卡片stats: total_ret/annual_ret/max_drawdown/win_rate用新值
- equity_curve SVG: 用重建曲线
- 成本对比块: 隐藏或标注"已切换到费率客调模式"

### Phase 5: 交互绑定 (~30行)
- _simOnFeeChange: 仿凯利, 调费率->重算->重渲染
- 自定义输入: _simReadCustomParams(2参数)
- 快捷键(可选)

### Phase 6: 测试
- 验证: 0%费率重算 == 原始数据(因为默认就是0费率)
- 验证: 0.3%费率重算 vs lab_cost_compare.json 的 low 档(近似对比)
- 边界: 空trades/单笔trades/持仓中/open_positions

---

## 10. 与凯利费率客调的关系

### 10.1 代码关系

```
凯利费率客调(已实现)               模拟回测费率客调(待实施)
├── KELLY_FEE_PRESETS (6档5参数)   ├── SIM_FEE_PRESETS (4档2参数, 简化)
├── _kellyRecomputeTrade           ├── _simRecomputeTrade (适配字段+复利)
├── _kellyComputeStats (20+指标)   ├── _simRecomputeStats (12指标, 适配)
├── _kellyApplyFeeRecompute        ├── _simApplyFeeRecompute (适配遍历)
├── _kellyOnFeeChange              ├── _simOnFeeChange (改渲染目标)
├── 费率控件UI                      ├── 费率控件UI (复用, 简化)
└── 快捷键 0-4+C                   └── 快捷键 (可选)
```

### 10.2 数据一致性

- 凯利费率客调: 前端重算, 不改后端 trades.json
- 模拟回测费率客调: 前端重算, 不改后端 lab_sim_{index}_stats/full.json
- 两者都只影响前端展示, 后端数据不变

### 10.3 用户体验一致性

如果模拟回测用简单模型(2参数), 和凯利的复杂模型(5参数)在相同 commission_rate 下结果不同(因为凯利有最低佣金/过户费)。
- **方案**: 预设档标签对齐(都叫"0%剥离"/"0.3%真实"/"1%保守"), 但参数不同(模拟回测只有commission+slippage)
- **用户感知**: 模拟回测的"0.3%真实"和凯利的"0.3%真实"含义近似但数值不完全相同(因费率模型不同), 可在tooltip说明

---

## 11. 替代方案

### 方案B: 后端加费率参数重跑

给 lab_simulate.py 的 build_pair_result 调用加 commission_rate/slippage 参数, 重跑生成新 JSON。
- **优点**: 最精确(直接用后端逻辑)
- **缺点**: 慢(128配对×2模式×5窗口, 几分钟); 不实时; 需后端API触发; 违背"直观测试"需求
- **不推荐**(除非用户要绝对精确)

### 方案C: 后端预计算多档

预跑 0/0.3%/1% 三档, 前端切换。
- **优点**: 切换快
- **缺点**: 不灵活(不能任意费率); 存储翻倍(每档一个full JSON); 只3档不够
- **不推荐**

### 方案D: 混合(前端近似+后端按需精确)

默认前端重算(快速看趋势), 用户点"精确重算"按钮->后端重跑。
- **优点**: 兼顾速度和精度
- **缺点**: 实现复杂; 两套逻辑维护成本高
- **不推荐**(过度设计)

### 推荐: 方案A(前端重算)

理由:
1. 模拟回测费率模型简单(2参数), 重算逻辑简单
2. 默认slippage=0, bp=close, 无需还原
3. trades有at/cp, 可重建equity_curve和max_drawdown
4. 性能好(只重算当前配对, <10ms)
5. 实时交互(调费率即时看效果)
6. 后端无需改动

---

## 附录A: lab_simulate.py 费率模型详解

### simulate_full_in (L289-374)

```python
# 买入(L326-329):
buy_price = close * (1 + slippage)           # 含滑点买入价
shares = cash / (buy_price * (1 + commission_rate))  # 扣佣金后份额
cash = 0.0  # 全仓

# 卖出(L335-342):
sell_price = close * (1 - slippage)          # 含滑点卖出价
sell_amount = shares * sell_price
cash = sell_amount * (1 - commission_rate)   # 扣佣金后到账
account_total = cash
cum_profit = account_total - INITIAL_CAPITAL

# 期末(L359-366):
final_total = cash + shares * last_close  # 持仓中
# 或 final_total = cash  # 空仓
```

### simulate_fixed_10k (L377-463)

```python
# 买入(L412-415):
buy_price = close * (1 + slippage)
shares = POSITION_SIZE / (buy_price * (1 + commission_rate))
cash -= POSITION_SIZE  # 固定扣1万

# 清仓卖出(L423-431):
sell_price = close * (1 - slippage)
sell_amount = total_shares * sell_price
cash += sell_amount * (1 - commission_rate)

# 期末(L448-449):
hv = sum(shares * last_close for open positions)
final_total = cash + hv
```

### _build_stats (L177-286)

```python
total_ret = (final_total - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
annual_ret = ((final_total / INITIAL_CAPITAL) ** (1/years) - 1) * 100
max_dd = 从 equity_curve value 序列算 peak-trough
win_rate = len([t for t in trades if t['ret'] > 0]) / len(trades) * 100
sharpe = 从 equity_curve 相邻点收益率算 mean/std * sqrt(252)
sortino = 从 equity_curve 下行波动算
profit_factor = sum(win_rets) / abs(sum(loss_rets))
payoff_ratio = avg_win / abs(avg_loss)
expectancy = win_rate * avg_win + loss_rate * avg_loss
```

## 附录B: 前端数据流

```
用户打开策略实验室 -> renderSimCard()
  -> fetchLabSimData(index)  // R2 加载 stats JSON
  -> fetchLabCostCompare()   // CF 加载成本对比 JSON
  -> _labSimCardHTML(key, simData)  // 渲染卡片(stats数字+成本对比表)
  -> fetchLabSimFullData(index)     // 异步加载 full JSON
    -> 合并 trades/equity_curve/win_trades/open_positions 到 simData
    -> _rerenderSim()  // 重渲染(净值曲线+交易记录)

用户切窗口/配对/指数 -> _rerenderSim()
  -> _labSimCardHTML(key, simData)  // 用已缓存数据重渲染
  -> _labPairWinData(pairData, mode, win, simData)  // 取窗口数据
  -> _labSimModeBlock(mode, winData, ...)  // 渲染stats+曲线+交易记录
```

费率客调插入点:
- _labSimCardHTML: 加费率控件UI
- _labSimAttachHandlers: 加费率切换交互
- _rerenderSim: 调费率后重算+重渲染
- _labSimModeBlock: stats/trades用重算值
