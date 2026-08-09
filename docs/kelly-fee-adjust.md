# 凯利回测费率客调方案调研

> 调研日期: 2026-08-09 | 只调研不改代码 | 产出供主控整理给用户确认后实施

## 1. 费率计算逻辑（已读透）

### 1.1 费率常量（scripts/simulate_trade.py L44-47）

| 参数 | 值 | 说明 |
|------|-----|------|
| COMMISSION_RATE | 0.0003 (万3) | 券商佣金，单边按成交金额计 |
| SLIPPAGE | 0.001 (千1) | 滑点，买入价升高/卖出价降低 |
| MIN_COMMISSION | 5.0 元 | 单笔最低佣金（小单兜底） |
| TRANSFER_FEE_RATE_SH | 0.00001 (万0.1) | 沪市过户费，仅 51xxxx/58xxxx ETF 收 |

signal_kelly_backtest.py L40-43 从 simulate_trade.py 导入这些常量和函数，无独立费率定义。

### 1.2 买入扣费 _buy_with_fees(budget, close, etf_code)（L378-410）

```
buy_price = close * (1 + SLIPPAGE)          # 含滑点买入价
sh_rate = TRANSFER_FEE_RATE_SH if 沪市ETF else 0
# 一般情况：
shares = budget / (buy_price * (1 + COMMISSION_RATE + sh_rate))
commission = shares * buy_price * COMMISSION_RATE
# 最低佣金触发（commission < 5元）：
shares = (budget - MIN_COMMISSION) / (buy_price * (1 + sh_rate))
commission = MIN_COMMISSION
```
budget 花光为止，shares 是扣佣金+过户费后实际买到的份额。

### 1.3 卖出扣费 _sell_with_fees(shares, close, etf_code)（L413-429）

```
sell_price = close * (1 - SLIPPAGE)         # 含滑点卖出价
sell_amount = shares * sell_price
commission = max(sell_amount * COMMISSION_RATE, MIN_COMMISSION)
transfer_fee = sell_amount * sh_rate
net = sell_amount - commission - transfer_fee  # 实际到账
```

### 1.4 profit / return_pct（signal_kelly_backtest.py L283-284, L330-331）

```
profit = net - BUY_AMOUNT                    # 净到账 - 投入本金
return_pct = profit / BUY_AMOUNT * 100
```

BUY_AMOUNT = 10000（L47，已从 1000 改为 10000，注释"降低最低佣金占比 往返费率~1%->~0.3%"）。

### 1.5 费率对 1000 vs 10000 的影响

| 买额 | 佣金(万3) | 最低佣金 | 实际佣金 | 佣金占比 | 往返费率(含滑点) |
|------|-----------|----------|----------|----------|------------------|
| 1000元 | 0.3元 | 5元 | 5元 | 0.5% | ~1.1% |
| 10000元 | 3元 | 5元 | 3元 | 0.03% | ~0.3% |

1000->10000 的本质：佣金超过最低佣金门槛(5/0.0003≈16667元)，不再触发最低佣金兜底，费率占比从 1% 降到 0.3%。**这是降低最低佣金占比，不是调费率参数本身。**

---

## 2. trades.json 字段可重算性（已验证）

### 2.1 文件概况

- 路径: `static-site/data/signal_kelly_trades.json`
- 大小: **32MB**（非 6MB，实际更大）
- 总笔数: 177096（跨 16 象限 × 6 模式重复计数，同一信号归入评级+ETF归类+信号类型+指数大类多组）
- 去重笔数: **43548**（按 signal_date+etf_code+mode 去重）
- 最大单象限×模式: rating_low = **5870 笔**
- 存储格式: 列式（每笔 trade 是 19 元素数组，fields 定义列顺序）

### 2.2 19 个字段

```
signal_date, index_id, signal, buy_date, sell_date,
etf_code, etf_name, track_tier, track_score, match_method, track_low_confidence,
buy_price, sell_price, shares, profit, return_pct,
hold_days, sell_reason, current_price
```

### 2.3 前端重算数学推导（已验证精确匹配）

trades.json 存的 buy_price/sell_price 含滑点，shares 含费扣减。可还原原始 close：

```
# 还原无滑点收盘价
close_buy  = buy_price / (1 + SLIPPAGE)       # SLIPPAGE=0.001
close_sell = sell_price / (1 - SLIPPAGE)       # 已卖出(sell_date 非空)
close_sell = current_price                      # 持仓中(sell_date 空, current_price 本身是原始 nav)

# 无费重算（费率全 0）
shares_nofee = BUY_AMOUNT / close_buy
profit_nofee = shares_nofee * close_sell - BUY_AMOUNT
return_pct_nofee = profit_nofee / BUY_AMOUNT * 100

# 任意费率重算（新佣金率 c, 新滑点 s, 新最低佣金 min_c, 新过户费率 sh）
buy_price_new = close_buy * (1 + s)
# _buy_with_fees 逻辑(含最低佣金分支)
shares_new = BUY_AMOUNT / (buy_price_new * (1 + c + sh))
if shares_new * buy_price_new * c < min_c:
    shares_new = (BUY_AMOUNT - min_c) / (buy_price_new * (1 + sh))
sell_price_new = close_sell * (1 - s)
sell_amount_new = shares_new * sell_price_new
commission_sell = max(sell_amount_new * c, min_c)
net_new = sell_amount_new - commission_sell - sell_amount_new * sh
profit_new = net_new - BUY_AMOUNT
return_pct_new = profit_new / BUY_AMOUNT * 100
```

### 2.4 验证结果（trade[0]: 512480 半导体ETF国联安）

| 指标 | 存储值 | 重算值 | 匹配 |
|------|--------|--------|------|
| 含费 profit | 656.861 | 656.8619 | ✓ |
| 含费 return_pct | 6.5686 | 6.5686 | ✓ |
| 无费 profit | - | 688.7631 | (费率影响 31.9 元) |
| 0费率重算 profit | - | 688.7631 | ✓ (=无费) |

**结论：前端可从 buy_price/sell_price/shares/etf_code/current_price 精确重算任意费率下的 profit/return_pct。**

---

## 3. 三方案对比

### 方案A：前端动态重算（推荐）

**原理**: 前端读 trades.json，按用户输入费率重算每笔 profit/return_pct，重新聚合统计（胜率/盈亏比/凯利/夏普/最大回撤等 20+ 指标），用新统计替换卡片显示。

**可行性**:
- trades.json 已有足够字段重算（见 §2.3 验证）
- 前端已有懒加载机制（lab.js L7392-7411，R2+CF 兜底，存 state.labSigKellyTradesData）
- 最大单象限 5870 笔重算 < 10ms；全部 43548 笔去重重算 < 50ms
- 重新聚合 16 象限 × 6 模式 × 5 周期统计 < 200ms
- **瓶颈在 32MB JSON 首次加载**：R2 br 压缩后约 3-5MB，首次 1-3 秒（有 loading 提示可接受），缓存后即时

**需做的工作**:
1. 前端 JS 移植 _buy_with_fees / _sell_with_fees / _compute_stats 逻辑（约 150 行 JS）
2. 费率控件 UI（滑块/输入框/预设档）
3. 调费率 -> 重算 trades -> 重新聚合 -> 重新渲染卡片
4. 交易记录弹窗的 profit/return_pct 列也同步重算

**优点**: 实时交互（调费率即时看效果），后端无需改动，用户可调任意费率
**缺点**: 32MB JSON 首次加载有延迟；_compute_stats 移植需精确（20+ 指标）

**性能优化**:
- trades.json 只在用户首次调费率时懒加载（不进页面就加载）
- br 压缩（CF Workers/R2 自动）
- 重算用 Web Worker 避免阻塞 UI（可选，43548 笔 < 50ms 可能不需要）

### 方案B：后端重跑

**原理**: 用户调费率 -> 后端重跑 signal_kelly_backtest.py -> 重新生成 JSON -> 前端刷新。

**可行性**: 需给 signal_kelly_backtest.py 加 --commission/--slippage 等 CLI 参数（当前没有，费率硬编码常量）。重跑 2-3 分钟。

**优点**: 最准确（直接用后端逻辑）
**缺点**: 慢 2-3 分钟不实时；每次调费率都要重跑后端；需要后端 API 触发；违背"直观测试"需求

### 方案C：后端预计算多档

**原理**: 预跑 0/0.3%/1% 等几档费率，前端切换。

**可行性**: 可预跑几档存 separate JSON。但无法支持任意费率。

**优点**: 切换快
**缺点**: 不灵活（不能任意费率）；存储翻倍（每档 32MB trades）

### 推荐：方案A

理由：
1. 用户要"直观测试"暗示实时交互，方案A 唯一满足
2. 前端重算已验证精确匹配后端逻辑
3. 后端无需改动，trades.json 已有足够字段
4. 性能可接受（首次加载 1-3 秒，重算 < 200ms）

---

## 4. trade_sim 费率客调现状

### 4.1 现状：无费率客调控件

- **simulate_trade.py**：费率是硬编码常量（L44-47），CLI 参数只有 --index/--all/--output/--html（L1957-1961），**没有 --commission/--slippage 参数**
- **app.js L18600-18616**：infoBar 显示费率明细（从 sd.commission_rate/slippage/transfer_fee_rate_sh/min_commission 读取），但**只显示不可调**
- **lab.js L2085-2094**：有"成本对比"展示（低档=万3+千1 vs 高档=万5+千2），但**预设对比不可调**

### 4.2 trade_sim 也需做费率客调

用户提到"本身也有一个模拟回测费率客调的需求"。trade_sim 目前完全没有费率客调控件，需要新建。

**可复用**:
- 凯利回测的费率重算 JS 逻辑（_buy_with_fees/_sell_with_fees 移植）可直接复用
- 费率控件 UI 组件可复用
- 但 trade_sim 的数据结构不同（trade_sim JSON 按 index_id 存，每品种一条回测序列），重算逻辑需适配

**trade_sim 差异**:
- trade_sim 是单品种连续回测（有仓位管理/资金曲线），不是单笔独立交易
- 费率影响每笔买卖的成交价和份额，连续回测中费率会复利累积
- trade_sim 的 trades 记录是否存了足够的字段重算？需单独调研 trade_sim JSON 结构

---

## 5. 前端交互方案（方案A）

### 5.1 费率控件位置

放 `_renderSigKellyBar` 顶部 bar（lab.js L7041-7065），与周期切换 tabs 同行。

```
[近1年] [近3年] [近5年] [近10年] [全部]   |  费率: [0% 剥离] [0.3% 真实] [1% 保守] [自定义]  |  买10000元 · 生成: 2026-08-09
```

### 5.2 费率输入控件

**预设档**（按钮一键切换）:
- **0% 剥离费率**: 佣金0 + 滑点0 + 过户费0（看本质）
- **0.3% 真实费率**: 佣金万3 + 滑点千1 + 最低5元 + 沪市过户费万0.1（当前默认）
- **1% 保守费率**: 佣金万5 + 滑点千2 + 最低5元（个股常规/高估费率侵蚀）
- **自定义**: 展开输入框，可调 佣金率/最低佣金/滑点/过户费率 4 个参数

**自定义展开**:
```
佣金率: [____] 万  最低佣金: [____] 元
滑点:   [____] 千  过户费率: [____] 万(沪市)
```

### 5.3 重算展示流程

1. 用户调费率 -> 首次需加载 trades.json（32MB，显示 loading "正在加载交易数据重算..."）
2. 按 16 象限 × 6 模式遍历 trades，按当前 period cutoff 过滤 buy_date
3. 每笔 trade 按新费率重算 profit/return_pct
4. 重新聚合统计（复制 _compute_stats 逻辑：胜率/盈亏比/凯利/夏普/最大回撤/年化/卡尔玛等 20+ 指标）
5. 用新统计重新渲染所有卡片（_renderSigKellyQuadrants）
6. 交易记录弹窗的 profit/return_pct 列也用新值

### 5.4 性能预期

| 步骤 | 耗时 |
|------|------|
| 首次加载 trades.json (32MB, br 压缩后 ~4MB) | 1-3 秒 |
| 重算 43548 笔 profit/return_pct | < 50ms |
| 重新聚合 96 组合统计 (16 象限 × 6 模式) | < 200ms |
| 重新渲染卡片 DOM | < 100ms |
| **总计（首次）** | **1.5-3.5 秒** |
| **总计（缓存后）** | **< 500ms** |

---

## 6. 与 10000 重跑的关系

### 6.1 10000 重跑已实施

- `BUY_AMOUNT = 10000`（signal_kelly_backtest.py L47，注释"1000->10000"）
- trades.json 的 buy_amount 字段 = 10000
- backtest.json config.buy_amount = 10000

### 6.2 费率客调 vs 10000 重跑

| 维度 | 10000 重跑 | 费率客调 |
|------|-----------|----------|
| 调什么 | 买入金额 1000->10000 | 佣金率/滑点/过户费 |
| 效果 | 降低最低佣金占比(1%->0.3%) | 可调任意费率(含0%全剥离) |
| 看本质 | 部分(仍有0.3%费率) | 完全(0%剥离所有费率) |
| 灵活性 | 固定不可调 | 任意可调 |

### 6.3 结论：费率客调是 10000 重跑的超集，可替代

- 费率客调 0% 比固定 10000 更彻底（完全无费 vs 降低费率占比）
- 费率客调 0.3%（佣金万3+滑点千1）在 buy_amount=10000 下等价当前默认
- **10000 重跑的 BUY_AMOUNT=10000 保留不变**（作为 trades.json 的固定买额），费率客调在此买额基础上调费率参数
- 不需要回退 BUY_AMOUNT 到 1000（10000 是合理的买额，降低最低佣金占比本身正确）
- **费率客调上线后，"10000 重跑"作为独立功能可去掉**（已被费率客调覆盖），但 BUY_AMOUNT=10000 的值保留

### 6.4 实施建议

- BUY_AMOUNT=10000 保留（不回退）
- 费率客调作为新功能加在 10000 基础上
- 如果之前有"10000 重跑"的独立 commit/代码分支，其 BUY_AMOUNT 改动保留，其他部分（如有独立的重跑逻辑）可被费率客调替代

---

## 7. 实施工作量估算（供参考，非本次调研产出）

| 任务 | 工作量 | 说明 |
|------|--------|------|
| JS 移植 _buy_with_fees/_sell_with_fees | 小 | ~30 行，逻辑简单 |
| JS 移植 _compute_stats | 中 | ~150 行，20+ 指标需精确复制 |
| 费率控件 UI | 中 | 预设档+自定义展开，CSS+交互 |
| 重算+重渲染流程 | 中 | 遍历 trades -> 重算 -> 聚合 -> 渲染 |
| 交易记录弹窗同步 | 小 | profit/return_pct 列用新值 |
| trade_sim 费率客调 | 大 | 需单独调研 trade_sim JSON 结构+适配 |
| 合计（凯利回测部分） | 中 | ~400 行 JS + CSS |

---

## 8. 风险与注意事项

1. **_compute_stats 移植精度**: 20+ 指标（胜率/盈亏比/凯利/夏普/最大回撤/年化/卡尔玛/连胜连败/最大持仓等）需精确复制 Python 逻辑到 JS，边界处理（全胜 pl_ratio=999、无数据、持仓中 trade 等）要一致
2. **32MB JSON 加载**: 首次 1-3 秒，需 loading 提示。考虑是否精简 trades.json（去掉重算不需要的字符串字段如 etf_name/index_id/signal，只留 buy_price/sell_price/shares/etf_code/buy_date/sell_date/current_price，可减到 ~15MB）
3. **持仓中 trade**: sell_date 空 + current_price 是原始 nav（非含滑点），重算时用 current_price 作为 close_sell
4. **沪市 ETF 判断**: etf_code.startswith('51') or startswith('58')，前端 JS 需复制 _is_sh_etf 逻辑
5. **最低佣金边界**: buy_amount=10000 时佣金=3元<5元，触发最低佣金。费率客调时如果佣金率调高到万5(0.0005)，10000*0.0005=5元刚好=最低佣金，边界需正确处理
6. **数据一致性**: 费率客调只影响前端展示重算，不改变后端 trades.json/backtest.json。后端数据仍用默认费率(万3+千1)生成，前端按用户选择重算展示
