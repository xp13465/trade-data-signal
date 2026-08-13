# v4 降亏标志三梯队全量上线实施规格（施工图）

> 调研日期：2026-08-10 ｜ 只读调研产出，给实施 agent 当施工图用
> 依据：`docs/kelly/mining/kelly-v4-detail.md`(487行) + `docs/kelly/mining/kelly-loss-mining-v4.md` + pickle 精确 filter 提取 + 现有代码盘点
> 架构前提：降亏 toggle 过滤逻辑**全部在前端 lab.js**（`_kellyApplyFeeRecompute` L7293-7340），后端 `signal_kelly_backtest.py` 只生成 trades.json 全量交易，**不做 toggle 过滤**。v4 沿用同一架构，后端无需改 filter 逻辑。

---

## 1. 12 个新 toggle 清单（3 Greedy 组合 + 9 单标志）

### 1.1 第一梯队（稳健首选，3 个）

| # | toggle ID | state key | CSS class | 标签 | filter 条件（精确） | 比值 | n | 净影响 |
|---|-----------|-----------|-----------|------|---------------------|------|---|--------|
| ⑯ | g7 | `greedy7` | `.lab-sigkelly-toggle-g7` | Greedy-7组合(3.15) | **并集 OR**，见 §2.1 | 3.15 | 6,522 | +1,006,659 |
| ⑰ | v4c | `v4cSimple` | `.lab-sigkelly-toggle-v4c` | 3月+周三+辅关注(7.84) | `buy_month=3 & buy_weekday=2 & sig_dim=aux`（**简化版去 ts_bin**） | 7.84 | 366 | +112,532 |
| ⑱ | v4b | `v4b` | `.lab-sigkelly-toggle-v4b` | A股+5月+追关注+related(54.0) | `mkt_dim=a & buy_month=5 & sig_dim=special & etf_dim=related` | 53.96 | 210 | +40,120 |

### 1.2 第二梯队（收益更高，4 个）

| # | toggle ID | state key | CSS class | 标签 | filter 条件（精确） | 比值 | n | 净影响 |
|---|-----------|-----------|-----------|------|---------------------|------|---|--------|
| ⑲ | g10 | `greedy10` | `.lab-sigkelly-toggle-g10` | Greedy-10组合(3.06) | **并集 OR**，见 §2.2 | 3.06 | 7,986 | +1,230,180 |
| ⑳ | v4d | `v4d` | `.lab-sigkelly-toggle-v4d` | 12月+周二+辅关注+低分(12.20) | `buy_month=12 & buy_weekday=1 & sig_dim=aux & ts_bin<50`（**原始版含 ts_bin**） | 12.20 | 102 | +39,177 |
| ㉑ | v4j | `v4j` | `.lab-sigkelly-toggle-v4j` | 5月+极低价+追关注(15.55) | `buy_month=5 & buyprice_bin=vlow & sig_dim=special` | 15.55 | 192 | +62,941 |
| ㉒ | v4i | `v4i` | `.lab-sigkelly-toggle-v4i` | 5月+概念+周一+追关注(27.0) | `sig_dim=special & buy_month=5 & mkt_dim=concept & buy_weekday=0` | 27.04 | 186 | +53,672 |

### 1.3 第三梯队（高比值附监控，5 个）

| # | toggle ID | state key | CSS class | 标签 | filter 条件（精确） | 比值 | n | 净影响 | 风险/警告 |
|---|-----------|-----------|-----------|------|---------------------|------|---|--------|-----------|
| ㉓ | g15 | `greedy15` | `.lab-sigkelly-toggle-g15` | Greedy-15组合(3.29) | **并集 OR**，见 §2.3 | 3.29 | 9,000 | +1,490,054 | 损盈9.84%接近10%上限 |
| ㉔ | v4f | `v4f` | `.lab-sigkelly-toggle-v4f` | 6月+周三+主关注+related(999)⚠️ | `sig_dim=main & buy_month=6 & buy_weekday=2 & etf_dim=related` | 999 | 60 | +24,666 | **⚠️n=60太小 只3年 JEP虚高** |
| ㉕ | v4g | `v4g` | `.lab-sigkelly-toggle-v4g` | 全球+Q1+辅关注+低评级(6.25)⚠️ | `mkt_dim=global & buy_quarter=1 & sig_dim=aux & rating_dim=low` | 6.25 | 258 | +56,367 | **⚠️近年才转亏(2023-24子集盈利)** |
| ㉖ | v4m | `v4m` | `.lab-sigkelly-toggle-v4m` | 9月+周三+追关注(115.6)⚠️ | `sig_dim=special & buy_month=9 & buy_weekday=2` | 115.56 | 126 | +52,372 | **⚠️只3年数据 ratio虚高** |
| ㉗ | v4k | `v4k` | `.lab-sigkelly-toggle-v4k` | 1月+主关注+高价(10.11)⚠️ | `sig_dim=main & buy_month=1 & buyprice_bin=high` | 10.11 | 132 | +40,753 | **⚠️2017/2025有子集盈利年 3/5年净正** |

### 1.4 关键口径区分（§18 N1 教训：标签和 filter 必须一致）

| 维度 | 取值 | 精确含义 | 对应字段 | helper |
|------|------|---------|---------|--------|
| `buyprice_bin=vlow` | price ≤ 0.841441 | **极低价**（最低五分位） | `buy_price` | `_kellyBuypriceBin()` → `"vlow"` |
| `buyprice_bin=low` | 0.841 < price ≤ 1.015 | **低价**（第二五分位） | `buy_price` | `_kellyBuypriceBin()` → `"low"` |
| `buyprice_bin=high` | 1.195 < price ≤ 1.447 | **高价**（第四五分位） | `buy_price` | `_kellyBuypriceBin()` → `"high"` |
| `ts_bin<50` | track_score < 50 | **低跟踪分** | `track_score` | `Number(t[fIdx.track_score]) < 50` |
| `sig_dim=special` | signal = "buy_special" | **追关注** | `signal` | `t[fIdx.signal] === "buy_special"` |
| `sig_dim=aux` | signal = "buy_aux" | **辅关注** | `signal` | `t[fIdx.signal] === "buy_aux"` |
| `sig_dim=main` | signal = "buy" | **主关注** | `signal` | `t[fIdx.signal] === "buy"` |
| `etf_dim=related` | track_tier = "related" | **相关ETF** | `track_tier` | `t[fIdx.track_tier] === "related"` |
| `rating_dim=low` | rating = "low" | **低评级** | `rating` | `t[fIdx.rating] === "low"` |
| `mkt_dim=*` | quadrant key 查找 | **指数大类** | _tradeDims | `_dims3.mkt`（a/hk/global/industry/concept） |
| `buy_quarter` | Q1=1-3月 Q2=4-6月 Q3=7-9月 Q4=10-12月 | **买入季度** | buy_month | `Math.ceil(parseInt(mm)/3)`（**需新增 helper**） |

> ⚠️ **V4-J 用 vlow（极低价），V4-A/Greedy-step14 用 low（低价），标签必须区分**。V4-C 简化版**不含 ts_bin**（标签不含"低分"），V4-D 原始版**含 ts_bin**（标签含"低分"），标签和 filter 必须一致。

### 1.5 维度字段映射（trades.json → v4 维度）

trades.json 已含全部所需字段（`signal_kelly_backtest.py` L807-810 `TRADE_FIELDS`）：

```python
TRADE_FIELDS = ["signal_date", "index_id", "signal", "buy_date", "sell_date", "etf_code", "etf_name",
                "track_tier", "track_score", "match_method", "track_low_confidence",
                "buy_price", "sell_price", "shares", "profit", "return_pct",
                "hold_days", "sell_reason", "current_price", "market_state", "rating"]
```

| v4 维度 | 来源 trade 字段 | 已有 helper？ |
|---------|----------------|-------------|
| sig_dim | `signal` | 直接读 |
| buy_month | `buy_date` substring(4,6) | 直接 substring |
| buy_weekday | `buy_date` | ✅ `_kellyBuyWeekday()` L7191（**Python 约定 0=周一 1=周二 2=周三**） |
| buy_quarter | buy_month 计算 | **需新增** `_kellyBuyQuarter()` |
| buyprice_bin | `buy_price` | ✅ `_kellyBuypriceBin()` L7202 |
| mkt_dim | quadrant key 查找 | ✅ `_kellyBuildTradeDims()` L7211 |
| rating_dim | `rating` 字段 | 直接读 |
| etf_dim | `track_tier` 字段 | 直接读 |
| ts_bin<50 | `track_score` 字段 | `Number(track_score) < 50` |

---

## 2. Greedy-7/10/15 各自 step 清单（并集 OR 过滤）

### 2.1 Greedy-7（7 步并集，ratio 3.15，净 +1,006,659，PF 1.540，maxSh=0.28）

| Step | filter 条件（精确，从 pickle 提取） | 冗余条件 | 简化后 |
|------|-------------------------------------|---------|--------|
| 1 | `sig_dim=special & buy_month=5` | 无 | sig=special & mm=05 |
| 2 | `sig_dim=special & buy_month=11 & mkt_dim=concept & buy_quarter=4` | `buy_quarter=4`（11月必Q4） | sig=special & mm=11 & mkt=concept |
| 3 | `sig_dim=special & buy_month=3` | 无 | sig=special & mm=03 |
| 4 | `sig_dim=aux & buy_month=1` | 无 | sig=aux & mm=01 |
| 5 | `buy_quarter=2 & buyprice_bin=vlow & sig_dim=aux & mkt_dim=concept` | **无**（Q2覆盖4/5/6月非单月不可去） | Q=2 & bpb=vlow & sig=aux & mkt=concept |
| 6 | `sig_dim=main & buy_month=1` | 无 | sig=main & mm=01 |
| 7 | `buy_month=3 & buy_weekday=2 & mkt_dim=concept & rating_dim=low` | 无 | mm=03 & wd=2 & mkt=concept & rating=low |

### 2.2 Greedy-10（Greedy-7 + step 8-10，ratio 3.06，净 +1,230,180，PF 1.623）

| Step | filter 条件（精确） | 冗余条件 | 简化后 |
|------|---------------------|---------|--------|
| 8 | `sig_dim=aux & buy_month=12 & ts_bin<50` | 无 | sig=aux & mm=12 & ts<50 |
| 9 | `buy_month=6 & buyprice_bin=vlow & rating_dim=low & buy_quarter=2` | `buy_quarter=2`（6月必Q2） | mm=06 & bpb=vlow & rating=low |
| 10 | `sig_dim=aux & buy_month=5` | 无 | sig=aux & mm=05 |

> **注意**：Greedy step 8（`sig=aux & mm=12 & ts<50`，无 weekday 约束）**不等于** V4-D（`mm=12 & wd=1 & sig=aux & ts<50`，有 weekday=1）。V4-D 是 step 8 的子集。两者同时开启幂等无害。

### 2.3 Greedy-15（Greedy-10 + step 11-15，ratio 3.29，净 +1,490,054，PF 1.713）

| Step | filter 条件（精确） | 冗余条件 | 简化后 | 与现有/V4 关系 |
|------|---------------------|---------|--------|----------------|
| 11 | `sig_dim=special & buy_month=11 & mkt_dim=industry & buy_quarter=4` | `buy_quarter=4` | sig=special & mm=11 & mkt=industry | **= 现有 N2！精确相同** |
| 12 | `buy_month=4 & buy_weekday=1 & mkt_dim=concept & ts_bin<50` | 无 | mm=04 & wd=1 & mkt=concept & ts<50 | = V4-L（非独立 toggle，仅 Greedy 组件） |
| 13 | `mkt_dim=global & buy_quarter=1 & sig_dim=aux & rating_dim=low` | 无 | mkt=global & Q=1 & sig=aux & rating=low | **= V4-G 独立 toggle** |
| 14 | `buy_month=1 & buyprice_bin=low & sig_dim=special & mkt_dim=concept` | 无 | mm=01 & bpb=low & sig=special & mkt=concept | 无（注意 bpb=**low** 非 vlow） |
| 15 | `sig_dim=special & buy_month=9 & buy_weekday=2 & buy_quarter=3` | `buy_quarter=3`（9月必Q3） | sig=special & mm=09 & wd=2 | **= V4-M 独立 toggle** |

### 2.4 包含关系 + 重复幂等

```
Greedy-7 ⊂ Greedy-10 ⊂ Greedy-15（嵌套超集）
  Greedy-7  = steps 1-7
  Greedy-10 = steps 1-10（含 Greedy-7 全部）
  Greedy-15 = steps 1-15（含 Greedy-10 全部）
```

**重复幂等无害**：
- Greedy-15 step 11 = 现有 N2 -> 同时开启同一 filter 执行两次，幂等
- Greedy-15 step 13 = V4-G 独立 toggle -> 同时开启幂等
- Greedy-15 step 15 = V4-M 独立 toggle -> 同时开启幂等
- Greedy-15 step 8 ⊃ V4-D（step 8 无 weekday 约束更宽）-> V4-D 交易已被 step 8 排除，幂等

---

## 3. 后端改动点（signal_kelly_backtest.py / simulate_trade.py）

### 3.1 结论：后端无需改 filter 逻辑

现有架构：`signal_kelly_backtest.py` 生成全量 trades.json -> 前端 lab.js 加载后按 toggle 过滤重算。**toggle 过滤逻辑全部在前端**，后端只产出数据。

### 3.2 需确认：trades.json 已含全部所需字段

v4 toggle 需要的维度全部已在 `TRADE_FIELDS`（signal_kelly_backtest.py L807-810）中，**后端零改动**。

### 3.3 simulate_trade.py 无关

`simulate_trade.py` 是 trade_sim HTML 静态产物合规化，与信号凯利回测 toggle 无关（L111 注释明确"始终合规，无 toggle"）。

### 3.4 Python weekday 约定（§18 N1 教训：标签和 filter 一致）

后端 `_kellyBuyWeekday`（lab.js L7191-7200，前端 helper）使用 **Python 约定**：
```javascript
// Python: 0=周一 1=周二 2=周三 3=周四 4=周五
var jsDay = new Date(y, m - 1, d).getDay(); // JS: 0=Sun...6=Sat
return (jsDay + 6) % 7; // 转Python: 0=Mon 1=Tue 2=Wed...
```

v4 filter 中的 `buy_weekday` 必须用此 helper 计算值：
- `buy_weekday=0` = 周一（V4-I 用）
- `buy_weekday=1` = 周二（V4-D/Greedy-step12 用）
- `buy_weekday=2` = 周三（V4-C/V4-F/V4-M/Greedy-step7/step15 用）

---

## 4. 前端 lab.js 改动点

### 4.1 新增 helper：`_kellyBuyQuarter`（L7209 后插入）

```javascript
// 降亏标志v4 helper: 买入季度(buy_month -> Q1-Q4)
// Q1=1-3月 Q2=4-6月 Q3=7-9月 Q4=10-12月
function _kellyBuyQuarter(buyMonthStr) {
  var m = parseInt(buyMonthStr, 10);
  if (isNaN(m) || m < 1 || m > 12) return -1;
  return Math.ceil(m / 3);
}
```

### 4.2 扩展 `_kellyDefaultFilters`（L7231-7241）

在现有 15 个 key 后追加 12 个：

```javascript
function _kellyDefaultFilters() {
  return {
    // === 现有 15 toggle（不动）===
    n1MarTueHigh: false, n2NovSpecialIndustry: false, r8PureNonMay: false,
    n3NovSpecialMon: false, n4AMay: false, r7MayReinforced: false,
    n5MayVlow: false, n6MidMay: false, r10May6NonMay: false,
    excludeAuxCross: false, excludeSpecialBear: false, excludeMonth: false,
    excludeAux: false, marketTiming: false, excludeRatingLow: false,
    // === v4 新增 12 toggle ===
    // 第一梯队(3)
    greedy7: false, v4cSimple: false, v4b: false,
    // 第二梯队(4)
    greedy10: false, v4d: false, v4j: false, v4i: false,
    // 第三梯队(5,附监控)
    greedy15: false, v4f: false, v4g: false, v4m: false, v4k: false
  };
}
```

### 4.3 扩展 filter 逻辑（L7306-7338 后，`return true` 前插入 v4 块）

现有 v3 块（L7306-7338）已计算 `_mm3/_sig3/_wd3/_bpb3/_mktD3/_ratD3`。v4 块复用这些变量 + 新增 `_ts3/_etfD3/_q3`，然后检查 12 个 v4 toggle。

```javascript
// === v4 新增 toggle（按梯队分组）===
var _v4On = filters.greedy7 || filters.greedy10 || filters.greedy15 ||
            filters.v4cSimple || filters.v4b ||
            filters.v4d || filters.v4j || filters.v4i ||
            filters.v4f || filters.v4g || filters.v4m || filters.v4k;
if (_v4On) {
  // 复用 v3 块已计算的 _mm3/_sig3/_wd3/_bpb3/_mktD3/_ratD3
  // 新增 v4 维度
  var _ts3 = fIdx.track_score != null ? Number(t[fIdx.track_score]) : 999;  // ts_bin<50
  var _etfD3 = fIdx.track_tier != null ? String(t[fIdx.track_tier] || "") : "";  // etf_dim
  var _q3 = _kellyBuyQuarter(_mm3);  // buy_quarter 1-4

  // --- 第一梯队 ---
  // ⑯ Greedy-7 组合（7步并集OR，ratio 3.15，净+1,006,659，PF 1.540）
  if (filters.greedy7 && (
    (_sig3 === "buy_special" && _mm3 === "05") ||                                                    // step1: 追关注+5月
    (_sig3 === "buy_special" && _mm3 === "11" && _mktD3 === "concept") ||                             // step2: 追关注+11月+概念
    (_sig3 === "buy_special" && _mm3 === "03") ||                                                    // step3: 追关注+3月
    (_sig3 === "buy_aux" && _mm3 === "01") ||                                                        // step4: 辅关注+1月
    (_q3 === 2 && _bpb3 === "vlow" && _sig3 === "buy_aux" && _mktD3 === "concept") ||                // step5: Q2+极低价+辅关注+概念
    (_sig3 === "buy" && _mm3 === "01") ||                                                            // step6: 主关注+1月
    (_mm3 === "03" && _wd3 === 2 && _mktD3 === "concept" && _ratD3 === "low")                       // step7: 3月+周三+概念+低评级
  )) return false;

  // ⑰ V4-C 简化版（3月+周三+辅关注，去低分，ratio 7.84，n=366）
  if (filters.v4cSimple && _mm3 === "03" && _wd3 === 2 && _sig3 === "buy_aux") return false;

  // ⑱ V4-B（A股+5月+追关注+related，ratio 53.96，6年全正）
  if (filters.v4b && _mktD3 === "a" && _mm3 === "05" && _sig3 === "buy_special" && _etfD3 === "related") return false;

  // --- 第二梯队 ---
  // ⑲ Greedy-10 组合（10步并集OR = Greedy-7 + 3步，ratio 3.06）
  if (filters.greedy10 && (
    (_sig3 === "buy_special" && _mm3 === "05") ||                                                    // step1
    (_sig3 === "buy_special" && _mm3 === "11" && _mktD3 === "concept") ||                             // step2
    (_sig3 === "buy_special" && _mm3 === "03") ||                                                    // step3
    (_sig3 === "buy_aux" && _mm3 === "01") ||                                                        // step4
    (_q3 === 2 && _bpb3 === "vlow" && _sig3 === "buy_aux" && _mktD3 === "concept") ||                // step5
    (_sig3 === "buy" && _mm3 === "01") ||                                                            // step6
    (_mm3 === "03" && _wd3 === 2 && _mktD3 === "concept" && _ratD3 === "low") ||                    // step7
    (_sig3 === "buy_aux" && _mm3 === "12" && _ts3 < 50) ||                                          // step8: 辅关注+12月+低分
    (_mm3 === "06" && _bpb3 === "vlow" && _ratD3 === "low") ||                                      // step9: 6月+极低价+低评级
    (_sig3 === "buy_aux" && _mm3 === "05")                                                           // step10: 辅关注+5月
  )) return false;

  // ⑳ V4-D（12月+周二+辅关注+低分，原始版含 ts_bin，ratio 12.20，n=102）
  if (filters.v4d && _mm3 === "12" && _wd3 === 1 && _sig3 === "buy_aux" && _ts3 < 50) return false;

  // ㉑ V4-J（5月+极低价+追关注，ratio 15.55，n=192）
  // ⚠️ buyprice_bin=vlow（极低价），非 low（低价）
  if (filters.v4j && _mm3 === "05" && _bpb3 === "vlow" && _sig3 === "buy_special") return false;

  // ㉒ V4-I（5月+概念+周一+追关注，ratio 27.04，n=186）
  if (filters.v4i && _sig3 === "buy_special" && _mm3 === "05" && _mktD3 === "concept" && _wd3 === 0) return false;

  // --- 第三梯队 ---
  // ㉓ Greedy-15 组合（15步并集OR = Greedy-10 + 5步，ratio 3.29）
  // step11 = 现有N2，step13 = V4-G，step15 = V4-M（同时开启幂等无害）
  if (filters.greedy15 && (
    (_sig3 === "buy_special" && _mm3 === "05") ||                                                    // step1
    (_sig3 === "buy_special" && _mm3 === "11" && _mktD3 === "concept") ||                             // step2
    (_sig3 === "buy_special" && _mm3 === "03") ||                                                    // step3
    (_sig3 === "buy_aux" && _mm3 === "01") ||                                                        // step4
    (_q3 === 2 && _bpb3 === "vlow" && _sig3 === "buy_aux" && _mktD3 === "concept") ||                // step5
    (_sig3 === "buy" && _mm3 === "01") ||                                                            // step6
    (_mm3 === "03" && _wd3 === 2 && _mktD3 === "concept" && _ratD3 === "low") ||                    // step7
    (_sig3 === "buy_aux" && _mm3 === "12" && _ts3 < 50) ||                                          // step8
    (_mm3 === "06" && _bpb3 === "vlow" && _ratD3 === "low") ||                                      // step9
    (_sig3 === "buy_aux" && _mm3 === "05") ||                                                       // step10
    (_sig3 === "buy_special" && _mm3 === "11" && _mktD3 === "industry") ||                            // step11: =现有N2
    (_mm3 === "04" && _wd3 === 1 && _mktD3 === "concept" && _ts3 < 50) ||                           // step12: V4-L
    (_mktD3 === "global" && _q3 === 1 && _sig3 === "buy_aux" && _ratD3 === "low") ||                // step13: =V4-G
    (_mm3 === "01" && _bpb3 === "low" && _sig3 === "buy_special" && _mktD3 === "concept") ||        // step14: bpb=low非vlow
    (_sig3 === "buy_special" && _mm3 === "09" && _wd3 === 2)                                         // step15: =V4-M
  )) return false;

  // ㉔ V4-F（6月+周三+主关注+related，ratio 999 JEP，n=60⚠️）
  if (filters.v4f && _sig3 === "buy" && _mm3 === "06" && _wd3 === 2 && _etfD3 === "related") return false;

  // ㉕ V4-G（全球+Q1+辅关注+低评级，ratio 6.25，n=258⚠️近年才转亏）
  if (filters.v4g && _mktD3 === "global" && _q3 === 1 && _sig3 === "buy_aux" && _ratD3 === "low") return false;

  // ㉖ V4-M（9月+周三+追关注，ratio 115.56，n=126⚠️只3年数据）
  if (filters.v4m && _sig3 === "buy_special" && _mm3 === "09" && _wd3 === 2) return false;

  // ㉗ V4-K（1月+主关注+高价，ratio 10.11，n=132⚠️有子集盈利年）
  if (filters.v4k && _sig3 === "buy" && _mm3 === "01" && _bpb3 === "high") return false;
}
```

> **§18 N1 教训**：标签和 filter 必须一致。V4-J 标签写"极低价"对应 `bpb=vlow`；V4-C 简化版标签不含"低分"对应 filter 无 `ts_bin`；V4-D 标签含"低分"对应 filter 有 `ts_bin<50`。

### 4.4 toggleHTML 新增 12 个 toggle（L7588 R10 后、L7589 `比值<3` 标签前插入 v4 分组）

在现有 toggleHTML（L7577-7597）的 R10 toggle（L7588）之后、`比值<3` 分隔标签（L7589）之前，插入 v4 三组 toggle：

```javascript
// 在 L7588 R10 toggle 之后插入:
`<span class="lab-sigkelly-toggle-tier">v4 第一梯队(稳健首选)</span>` +
`<label class="lab-sigkelly-toggle" tabindex="0" data-no-pop="" data-tip="排除Greedy-7组合(7个toggle并集OR)。减亏22.5%/损盈7.16%/比值3.15。净增收+100.67万元。PF 1.285->1.540。maxSh=0.28强稳健(远低于⑦⑧的66%/71%)，11/16年净正，4窗口全>2。7条独立亏损逻辑线。不存在⑦⑧同类过拟合。"><input type="checkbox" class="lab-sigkelly-toggle-g7"${_filters.greedy7 ? " checked" : ""}> Greedy-7组合(3.15) <span class="lab-sigkelly-toggle-tip">ⓘ</span></label>` +
`<label class="lab-sigkelly-toggle" tabindex="0" data-no-pop="" data-tip="排除3月+周三+辅关注(简化版去低分)。比值7.84/n=366。净增收+11.25万元。4窗口极稳(y1/y3/y10均>7)。是v3 N1的信号维度变体可叠加。"><input type="checkbox" class="lab-sigkelly-toggle-v4c"${_filters.v4cSimple ? " checked" : ""}> 3月+周三+辅关注(7.84) <span class="lab-sigkelly-toggle-tip">ⓘ</span></label>` +
`<label class="lab-sigkelly-toggle" tabindex="0" data-no-pop="" data-tip="排除A股+5月+追关注+related。比值53.96/n=210。净增收+4.01万元。6年全正maxSh=0.37最低。5月系中最稳。"><input type="checkbox" class="lab-sigkelly-toggle-v4b"${_filters.v4b ? " checked" : ""}> A股+5月+追关注+related(54.0) <span class="lab-sigkelly-toggle-tip">ⓘ</span></label>` +
`<span class="lab-sigkelly-toggle-tier">v4 第二梯队(收益更高)</span>` +
`<label class="lab-sigkelly-toggle" tabindex="0" data-no-pop="" data-tip="排除Greedy-10组合(10个toggle并集OR=Greedy-7+3步)。减亏28.0%/损盈9.16%/比值3.06。净增收+123.02万元。PF 1.623。maxSh=0.28。损盈接近10%上限。"><input type="checkbox" class="lab-sigkelly-toggle-g10"${_filters.greedy10 ? " checked" : ""}> Greedy-10组合(3.06) <span class="lab-sigkelly-toggle-tip">ⓘ</span></label>` +
`<label class="lab-sigkelly-toggle" tabindex="0" data-no-pop="" data-tip="排除12月+周二+辅关注+低分(track_score<50)。比值12.20/n=102。净增收+3.92万元。5年全正maxSh=0.46。年末止损潮经济逻辑最强。n=102较小。"><input type="checkbox" class="lab-sigkelly-toggle-v4d"${_filters.v4d ? " checked" : ""}> 12月+周二+辅关注+低分(12.20) <span class="lab-sigkelly-toggle-tip">ⓘ</span></label>` +
`<label class="lab-sigkelly-toggle" tabindex="0" data-no-pop="" data-tip="排除5月+极低价(vlow)+追关注。比值15.55/n=192。净增收+6.29万元。5年全正maxSh=0.40。是⑦n5的细化版加了追关注条件后maxSh从66%降到40%过拟合风险显著降低。"><input type="checkbox" class="lab-sigkelly-toggle-v4j"${_filters.v4j ? " checked" : ""}> 5月+极低价+追关注(15.55) <span class="lab-sigkelly-toggle-tip">ⓘ</span></label>` +
`<label class="lab-sigkelly-toggle" tabindex="0" data-no-pop="" data-tip="排除5月+概念+周一+追关注。比值27.04/n=186。净增收+5.37万元。4年全正maxSh=0.57接近阈值。"><input type="checkbox" class="lab-sigkelly-toggle-v4i"${_filters.v4i ? " checked" : ""}> 5月+概念+周一+追关注(27.0) <span class="lab-sigkelly-toggle-tip">ⓘ</span></label>` +
`<span class="lab-sigkelly-toggle-tier">v4 第三梯队(高比值⚠️附监控)</span>` +
`<label class="lab-sigkelly-toggle" tabindex="0" data-no-pop="" data-tip="排除Greedy-15组合(15个toggle并集OR=Greedy-10+5步)。减亏32.4%/损盈9.84%/比值3.29。净增收+149.01万元。PF 1.713(超越现有最高)。排除20%交易接近10%上限。含step11=现有N2/step13=V4-G/step15=V4-M(同时开启幂等无害)。"><input type="checkbox" class="lab-sigkelly-toggle-g15"${_filters.greedy15 ? " checked" : ""}> Greedy-15组合(3.29) <span class="lab-sigkelly-toggle-tip">ⓘ</span></label>` +
`<label class="lab-sigkelly-toggle" tabindex="0" data-no-pop="" data-tip="排除6月+周三+主关注+related。比值999(JEP)/n=60。净增收+2.47万元。⚠️附监控:n=60太小只3年数据(2021/2024/2026)JEP ratio=999虚高小样本偶然无盈利笔可能性大。等n>=100+5年数据再评估。"><input type="checkbox" class="lab-sigkelly-toggle-v4f"${_filters.v4f ? " checked" : ""}> 6月+周三+主关注+related(999)⚠️监控 <span class="lab-sigkelly-toggle-tip">ⓘ</span></label>` +
`<label class="lab-sigkelly-toggle" tabindex="0" data-no-pop="" data-tip="排除全球指数+Q1+辅关注+低评级。比值6.25/n=258。净增收+5.64万元。⚠️附监控:近年才转亏(2023-2024子集盈利)2025-2026才大亏前向泛化性存疑。可能是近年市场结构变化而非稳定规律。"><input type="checkbox" class="lab-sigkelly-toggle-v4g"${_filters.v4g ? " checked" : ""}> 全球+Q1+辅关注+低评级(6.25)⚠️监控 <span class="lab-sigkelly-toggle-tip">ⓘ</span></label>` +
`<label class="lab-sigkelly-toggle" tabindex="0" data-no-pop="" data-tip="排除9月+周三+追关注。比值115.56/n=126。净增收+5.24万元。⚠️附监控:只3年数据(2021/2024/2026)ratio虚高数据不足。每年6月监控9月表现。"><input type="checkbox" class="lab-sigkelly-toggle-v4m"${_filters.v4m ? " checked" : ""}> 9月+周三+追关注(115.6)⚠️监控 <span class="lab-sigkelly-toggle-tip">ⓘ</span></label>` +
`<label class="lab-sigkelly-toggle" tabindex="0" data-no-pop="" data-tip="排除1月+主关注+高价。比值10.11/n=132。净增收+4.08万元。⚠️附监控:2017/2025有子集盈利年3/5年净正(非全正)稳定性不足。"><input type="checkbox" class="lab-sigkelly-toggle-v4k"${_filters.v4k ? " checked" : ""}> 1月+主关注+高价(10.11)⚠️监控 <span class="lab-sigkelly-toggle-tip">ⓘ</span></label>` +
```

### 4.5 toggle 事件处理器（L7630-7726 后追加 12 个）

每个 toggle 的 onchange 复用现有模式：

```javascript
// v4 第一梯队
var g7Cb = bar.querySelector(".lab-sigkelly-toggle-g7");
if (g7Cb) g7Cb.onchange = function () {
  if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
  state.labSigKellyFilters.greedy7 = g7Cb.checked; _kellyOnFilterChange();
};
var v4cCb = bar.querySelector(".lab-sigkelly-toggle-v4c");
if (v4cCb) v4cCb.onchange = function () {
  if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
  state.labSigKellyFilters.v4cSimple = v4cCb.checked; _kellyOnFilterChange();
};
var v4bCb = bar.querySelector(".lab-sigkelly-toggle-v4b");
if (v4bCb) v4bCb.onchange = function () {
  if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
  state.labSigKellyFilters.v4b = v4bCb.checked; _kellyOnFilterChange();
};
// v4 第二梯队
var g10Cb = bar.querySelector(".lab-sigkelly-toggle-g10");
if (g10Cb) g10Cb.onchange = function () {
  if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
  state.labSigKellyFilters.greedy10 = g10Cb.checked; _kellyOnFilterChange();
};
var v4dCb = bar.querySelector(".lab-sigkelly-toggle-v4d");
if (v4dCb) v4dCb.onchange = function () {
  if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
  state.labSigKellyFilters.v4d = v4dCb.checked; _kellyOnFilterChange();
};
var v4jCb = bar.querySelector(".lab-sigkelly-toggle-v4j");
if (v4jCb) v4jCb.onchange = function () {
  if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
  state.labSigKellyFilters.v4j = v4jCb.checked; _kellyOnFilterChange();
};
var v4iCb = bar.querySelector(".lab-sigkelly-toggle-v4i");
if (v4iCb) v4iCb.onchange = function () {
  if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
  state.labSigKellyFilters.v4i = v4iCb.checked; _kellyOnFilterChange();
};
// v4 第三梯队
var g15Cb = bar.querySelector(".lab-sigkelly-toggle-g15");
if (g15Cb) g15Cb.onchange = function () {
  if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
  state.labSigKellyFilters.greedy15 = g15Cb.checked; _kellyOnFilterChange();
};
var v4fCb = bar.querySelector(".lab-sigkelly-toggle-v4f");
if (v4fCb) v4fCb.onchange = function () {
  if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
  state.labSigKellyFilters.v4f = v4fCb.checked; _kellyOnFilterChange();
};
var v4gCb = bar.querySelector(".lab-sigkelly-toggle-v4g");
if (v4gCb) v4gCb.onchange = function () {
  if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
  state.labSigKellyFilters.v4g = v4gCb.checked; _kellyOnFilterChange();
};
var v4mCb = bar.querySelector(".lab-sigkelly-toggle-v4m");
if (v4mCb) v4mCb.onchange = function () {
  if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
  state.labSigKellyFilters.v4m = v4mCb.checked; _kellyOnFilterChange();
};
var v4kCb = bar.querySelector(".lab-sigkelly-toggle-v4k");
if (v4kCb) v4kCb.onchange = function () {
  if (!state.labSigKellyFilters) state.labSigKellyFilters = _kellyDefaultFilters();
  state.labSigKellyFilters.v4k = v4kCb.checked; _kellyOnFilterChange();
};
```

### 4.6 `_kellyBuildTradeDims` 确认

现有 `_kellyBuildTradeDims`（L7211-7229）已遍历所有 quadrant key（含 `etf_strong/related/approx/has_track`），构建的 `_tradeDims[key]` 含 `{mkt, rating, etf, sig}` 四维。但 V4-B/V4-F 的 `etf_dim=related` 直接从 `track_tier` 字段读（`t[fIdx.track_tier]`）更简洁，不需要 _tradeDims 查找。推荐直接读字段。

---

## 5. purpose-notes.js 改动点（§21 算法公示同步）

### 5.1 现有结构

`purpose-notes.js` L30 `lab.sigkelly` 是一个单行超长字符串，包含全部 15 toggle 的算法说明。现有文案以 `①-⑮` 编号，分"第一梯队(比值>3)"和"第二梯队(比值<3)"两组。

### 5.2 改动方式

在现有 `⑮排除低评级...` 描述之后、`buyprice_bin五分位` 之前，插入 v4 新增说明段落：

```
<b>v4新增降亏标志</b>（第三轮挖掘，引入对比集挖掘/涌现模式/闭项集去冗余/贪心组合优化4个新方法，基于44,832笔交易930候选贪心搜索）：<b>v4第一梯队(稳健首选)</b>：⑯Greedy-7组合:7个toggle并集OR排除(追关注+5月/追关注+11月+概念/追关注+3月/辅关注+1月/Q2+极低价+辅关注+概念/主关注+1月/3月+周三+概念+低评级),减亏22.5%/损盈7.16%/比值3.15,净增收+100.67万,PF1.285->1.540,maxSh=0.28强稳健11/16年净正,不存在⑦⑧同类过拟合;⑰3月+周三+辅关注(简化版去低分):排除buy_month=3&buy_weekday=2&sig_dim=aux,比值7.84/n=366,4窗口极稳,是N1的信号维度变体可叠加;⑱A股+5月+追关注+related:排除mkt=a&buy_month=5&sig=special&etf=related,比值53.96/6年全正maxSh=0.37最低,5月系中最稳。<b>v4第二梯队(收益更高)</b>：⑲Greedy-10组合:Greedy-7+3步(辅关注+12月+低分/6月+极低价+低评级/辅关注+5月),减亏28.0%/损盈9.16%/比值3.06,净增收+123.02万,PF1.623;⑳12月+周二+辅关注+低分:排除buy_month=12&buy_weekday=1&sig=aux&ts<50,比值12.20/5年全正,年末止损潮经济逻辑最强n=102较小;㉑5月+极低价+追关注:排除buy_month=5&buyprice_bin=vlow&sig=special,比值15.55/5年全正maxSh=0.40,是⑦n5细化版maxSh从66%降到40%过拟合风险显著降低;㉒5月+概念+周一+追关注:排除sig=special&buy_month=5&mkt=concept&buy_weekday=0,比值27.04/4年全正maxSh=0.57接近阈值。<b>v4第三梯队(高比值⚠️附监控)</b>：㉓Greedy-15组合:Greedy-10+5步(含step11=现有N2/step13=V4-G/step15=V4-M,同时开启幂等无害),减亏32.4%/损盈9.84%/比值3.29,净增收+149.01万,PF1.713超越现有最高,排除20%交易接近10%上限;㉔6月+周三+主关注+related⚠️:排除sig=main&buy_month=6&buy_weekday=2&etf=related,比值999(JEP)/n=60太小只3年数据等n>=100再评估;㉕全球+Q1+辅关注+低评级⚠️:排除mkt=global&buy_quarter=1&sig=aux&rating=low,比值6.25/n=258近年才转亏前向泛化存疑;㉖9月+周三+追关注⚠️:排除sig=special&buy_month=9&buy_weekday=2,比值115.56/n=126只3年数据ratio虚高;㉗1月+主关注+高价⚠️:排除sig=main&buy_month=1&buyprice_bin=high,比值10.11/n=132有2个子集盈利年非全正。v4新增维度说明:sig_dim=main/aux/special对应signal=buy/buy_aux/buy_special;etf_dim=related对应track_tier=related;ts_bin<50=track_score<50;buy_quarter:Q1=1-3月Q2=4-6月Q3=7-9月Q4=10-12月;buyprice_bin=vlow(≤0.841极低价)/low(0.841-1.015低价)需区分。V4-F/G/M/K附监控:每年6月检查表现子集转盈则暂停。Greedy-7/10/15为嵌套超集(G7⊂G10⊂G15),单checkbox=并集OR过滤,同时开启多个幂等无害。
```

---

## 6. V4-F/G/M/K 警告标注方案

### 6.1 前端 toggle 标签警告

| Toggle | 标签后缀 | data-tip 警告文案 |
|--------|---------|------------------|
| V4-F | `⚠️监控` | `⚠️附监控:n=60太小只3年数据(2021/2024/2026)JEP ratio=999虚高小样本偶然无盈利笔可能性大。等n>=100+5年数据再评估。` |
| V4-G | `⚠️监控` | `⚠️附监控:近年才转亏(2023-2024子集盈利)2025-2026才大亏前向泛化性存疑。可能是近年市场结构变化而非稳定规律。` |
| V4-M | `⚠️监控` | `⚠️附监控:只3年数据(2021/2024/2026)ratio虚高数据不足。每年6月监控9月表现。` |
| V4-K | `⚠️监控` | `⚠️附监控:2017/2025有子集盈利年3/5年净正(非全正)稳定性不足。` |

### 6.2 purpose-notes.js 公示警告

在 `lab.sigkelly` 文案中 V4-F/G/M/K 各后缀 `⚠️` 标注 + 具体风险说明（见 §5.2）。

### 6.3 监控建议（供用户后续全局整理）

| Toggle | 监控项 | 触发暂停条件 |
|--------|--------|-------------|
| V4-F | n 增长 + 逐年净影响 | n>=100 后重新评估比值是否仍>3 |
| V4-G | 逐年净影响 + 近3年比值 | 近3年比值<2 或 子集转盈 |
| V4-M | n 增长 + 逐年数据 | 有第4年数据后重新评估 |
| V4-K | 逐年净影响 + 子集盈利 | 子集盈利年增至>2个 |

---

## 7. Greedy 组合上线方式：单组合 toggle（不拆分）

### 7.1 推荐：Greedy-7/10/15 各作单组合 toggle（1 个 checkbox = 并集 OR 过滤）

### 7.2 理由

1. **ratio>3 只在并集成立**：Greedy-7 的 7 步中，个别 step 比值 <3（step4=2.61/step6=2.64/step8=2.87/step10=2.56）。拆成单 toggle 后用户单独开启某个低比值 step，无法达到 ratio>3 的降亏效果，误导用户。
2. **backtest 统计量是并集的**：净影响 +1,006,659 / PF 1.540 / ratio 3.15 / maxSh=0.28 都是 7 步并集的回测结果。单步没有对应的独立回测统计量。
3. **UI 简洁**：拆成 15 个单 step = 新增 15 toggle = 总 30 toggle，UI 过于杂乱。3 个组合 toggle 更清晰。
4. **嵌套超集语义清晰**：Greedy-7⊂10⊂15，用户从 G7 起步，逐步升级到 G10/G15，每级 +2~3k 净影响，损盈逐步接近 10% 上限。

### 7.3 不拆分的代价（可接受）

用户无法单独开关 Greedy 内某个 step。但 Greedy 组合与现有 15 toggle + 9 个 v4 单标志可自由组合，已有足够粒度控制。用户若想排除"追关注+5月"但不排除其他 6 步，可不开 Greedy-7 而开 V4-J（5月+极低价+追关注）或现有 n4（A股+5月）。

---

## 8. 去重后总 27 toggle（现有 15 + 新增 12，叠加非替换）

### 8.1 叠加非替换（v4 §8.2 定）

v4 的 761 新标志是在 v3 的 78 个基础上扩展，非替代。v3 的 9 个标志在 v4 数据上复现正确。Greedy-7 的 7 步覆盖 5 条独立亏损逻辑线，与现有 15 toggle 维度有重叠但不完全相同。

### 8.2 V4-J/V4-B 推荐保留不替换

| v4 新标志 | 现有重叠 | 替换建议 | 最终决定 |
|----------|---------|---------|---------|
| V4-J（5月+极低价+追关注 ratio 15.55 maxSh=0.40） | ⑦n5（5月+低价 ratio 4.02 maxSh=0.66⚠️） | V4-J 是 n5 细化版，maxSh 66%->40% | **保留两者**（叠加非替换） |
| V4-B（A股+5月+追关注+related ratio 53.96 maxSh=0.37） | n4（A股+5月 ratio 4.67） | V4-B 是 n4 细化版，比值更高更稳 | **保留两者**（叠加非替换） |

### 8.3 总 toggle 清单（27 个）

| 分组 | 编号 | toggle | 数量 |
|------|------|--------|------|
| 现有 v3 比值>3 | ①-⑨ | n1/n2/n3/n4/n5/n6/r7/r8/r10 | 9 |
| 现有 比值<3 | ⑩-⑮ | excludeAuxCross/excludeSpecialBear/excludeMonth/excludeAux/marketTiming/excludeRatingLow | 6 |
| v4 第一梯队 | ⑯-⑱ | greedy7/v4cSimple/v4b | 3 |
| v4 第二梯队 | ⑲-㉒ | greedy10/v4d/v4j/v4i | 4 |
| v4 第三梯队 | ㉓-㉗ | greedy15/v4f/v4g/v4m/v4k | 5 |
| **合计** | | | **27** |

### 8.4 Greedy-15 与现有/V4 的重叠关系（全部幂等无害）

| Greedy-15 step | 重叠对象 | 关系 | 同时开启影响 |
|----------------|---------|------|-------------|
| step 11 | 现有 N2（②） | **精确相同** filter | 幂等 |
| step 13 | V4-G（㉕） | **精确相同** filter | 幂等 |
| step 15 | V4-M（㉖） | **精确相同** filter | 幂等 |
| step 8 | V4-D（⑳） | step 8 ⊃ V4-D（无 weekday 约束更宽） | 幂等 |
| step 1 | 现有 n4（⑤） | 部分重叠（不同维度） | 各自排除不同子集 |
| step 7 | 现有 n1（①） | 部分重叠（不同第4条件） | 各自排除不同子集 |

---

## 附录：现有代码位置索引

| 文件 | 行号 | 功能 |
|------|------|------|
| `static-site/lab.js` L7191-7200 | `_kellyBuyWeekday` | 买入星期（Python 0=周一） |
| `static-site/lab.js` L7202-7209 | `_kellyBuypriceBin` | 买入价位五分位 |
| `static-site/lab.js` L7211-7229 | `_kellyBuildTradeDims` | 维度查找 map |
| `static-site/lab.js` L7231-7241 | `_kellyDefaultFilters` | 15 toggle 默认 state |
| `static-site/lab.js` L7293-7340 | filter 逻辑 | 交易过滤（cutoff + 15 toggle） |
| `static-site/lab.js` L7431-7444 | `_kellyOnFilterChange` | toggle 切换处理 |
| `static-site/lab.js` L7546-7727 | `_renderSigKellyBar` | toggle HTML 渲染 + 事件绑定 |
| `static-site/lab.js` L7577-7597 | toggleHTML | 15 toggle HTML |
| `static-site/lab.js` L7630-7726 | onchange handlers | 15 toggle 事件处理器 |
| `static-site/purpose-notes.js` L30 | `lab.sigkelly` | 算法公示文案 |
| `scripts/signal_kelly_backtest.py` L807-810 | `TRADE_FIELDS` | trades.json 字段定义 |
| `scripts/signal_kelly_backtest.py` L77-113 | `QUADRANT_META` | 象限 key 定义 |

---

## 附录：buy_quarter helper 实现

```javascript
// 降亏标志v4 helper: 买入季度(buy_month -> Q1-Q4)
// Q1=1-3月 Q2=4-6月 Q3=7-9月 Q4=10-12月
function _kellyBuyQuarter(buyMonthStr) {
  var m = parseInt(buyMonthStr, 10);
  if (isNaN(m) || m < 1 || m > 12) return -1;
  return Math.ceil(m / 3);
}
```

插入位置：L7209（`_kellyBuypriceBin` 函数结束后）之后。

---

Co-Authored-By: Claude <noreply@anthropic.com>
