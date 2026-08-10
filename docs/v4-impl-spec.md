# v4 降亏标志三梯队全量上线实施规格

> 来源：调研 agent 2026-08-10。v4 依据见 `docs/kelly-v4-detail.md`（487行）。
> 用户定：三梯队全量上线（含 V4-F/G/M/K 附监控），后续用户全局整理。
> 关键结论：**后端无需改动**，toggle 过滤全在前端 `lab.js`。现有⑭MA60 是后端注入的特殊 toggle，v4 新 toggle 不涉及。

## 一、12 个新增 toggle 清单

### 第一梯队（3）

| # | toggle ID | 名称 | 精确 filter 条件 | 比值 | n | 净影响 |
|---|-----------|------|-----------------|------|---|--------|
| 1 | `greedy7` | Greedy-7组合 | 7step并集（见二） | 3.15 | 6,522 | +1,006,659 |
| 2 | `v4cSimple` | V4-C简化 | `buy_month=3 & buy_weekday=2 & sig_dim=aux` | 7.84 | 366 | +112,532 |
| 3 | `v4b` | V4-B | `mkt_dim=a & buy_month=5 & sig_dim=special & etf_dim=related` | 53.96 | 210 | +40,120 |

### 第二梯队（4）

| # | toggle ID | 名称 | 精确 filter 条件 | 比值 | n | 净影响 |
|---|-----------|------|-----------------|------|---|--------|
| 4 | `greedy10` | Greedy-10组合 | 10step并集（=Greedy-7+step8-10） | 3.06 | 7,986 | +1,230,180 |
| 5 | `v4d` | V4-D | `buy_month=12 & buy_weekday=1 & sig_dim=aux & ts_bin<50` | 12.20 | 102 | +39,177 |
| 6 | `v4j` | V4-J | `buy_month=5 & buyprice_bin=vlow & sig_dim=special` | 15.55 | 192 | +62,941 |
| 7 | `v4i` | V4-I | `sig_dim=special & buy_month=5 & mkt_dim=concept & buy_weekday=0` | 27.04 | 186 | +53,672 |

### 第三梯队（5，附监控 ⚠️）

| # | toggle ID | 名称 | 精确 filter 条件 | 比值 | n | 净影响 | 风险/监控 |
|---|-----------|------|-----------------|------|---|--------|---------|
| 8 | `greedy15` | Greedy-15组合 | 15step并集（=Greedy-10+step11-15） | 3.29 | 9,000 | +1,490,054 | 损盈9.84%接近10%上限 |
| 9 | `v4f` | V4-F | `sig_dim=main & buy_month=6 & buy_weekday=2 & etf_dim=related` | 999(JEP) | 60 | +24,666 | **n=60太小**，只3年，JEP虚高 |
| 10 | `v4g` | V4-G | `mkt_dim=global & buy_quarter=1 & sig_dim=aux & rating_dim=low` | 6.25 | 258 | +56,367 | **近年才转亏**（2023-24子集盈利） |
| 11 | `v4m` | V4-M | `sig_dim=special & buy_month=9 & buy_weekday=2` | 115.56 | 126 | +52,372 | **只3年数据**，ratio虚高 |
| 12 | `v4k` | V4-K | `sig_dim=main & buy_month=1 & buyprice_bin=high` | 10.11 | 132 | +40,753 | **有子集盈利年**（2017/2025） |

## 二、Greedy 组合 step 定义（从 pickle 提取，已去冗余 buy_quarter）

**Greedy-7 = step 1-7：**
1. `sig_dim=special & buy_month=5`
2. `sig_dim=special & buy_month=11 & mkt_dim=concept`
3. `sig_dim=special & buy_month=3`
4. `sig_dim=aux & buy_month=1`
5. `buy_quarter=2 & buyprice_bin=vlow & sig_dim=aux & mkt_dim=concept`（Q2覆盖4/5/6月，非冗余）
6. `sig_dim=main & buy_month=1`
7. `buy_month=3 & buy_weekday=2 & mkt_dim=concept & rating_dim=low`

**Greedy-10 = Greedy-7 + step 8-10：**
8. `sig_dim=aux & buy_month=12 & ts_bin<50`
9. `buy_month=6 & buyprice_bin=vlow & rating_dim=low`
10. `sig_dim=aux & buy_month=5`

**Greedy-15 = Greedy-10 + step 11-15：**
11. `sig_dim=special & buy_month=11 & mkt_dim=industry`（**精确等于现有 N2**）
12. `buy_month=4 & buy_weekday=1 & mkt_dim=concept & ts_bin<50`（V4-L，仅在此组合中）
13. `mkt_dim=global & buy_quarter=1 & sig_dim=aux & rating_dim=low`（**= V4-G 单标志**）
14. `buy_month=1 & buyprice_bin=low & sig_dim=special & mkt_dim=concept`
15. `sig_dim=special & buy_month=9 & buy_weekday=2`（**= V4-M 单标志**）

**包含关系**：Greedy-15 ⊃ Greedy-10 ⊃ Greedy-7。同时开启多个幂等无害。

## 三、现有 toggle 实现盘点

**toggle 过滤全在前端 lab.js，不在后端。**

1. 过滤逻辑：`lab.js` L7244 `_kellyApplyFeeRecompute` 内 `.filter(function(t){...})`。后端 `signal_kelly_backtest.py` 只生成 trades.json 原始数据。
2. 默认 state：`_kellyDefaultFilters()` L7231-7241，15字段全 false。
3. helper（L7190-7229）：`_kellyBuyWeekday`（Python约定 0=周一 1=周二 2=周三）/ `_kellyBuypriceBin`（vlow≤0.841441/low≤1.015314/mid≤1.194593/high≤1.446645/vhigh>1.446645）/ `_kellyBuildTradeDims`（quadrant key 解析 mkt_dim/rating_dim）
4. toggle HTML：`_renderSigKellyBar` L7577-7597，按梯队两组（比值>3 / 比值<3）
5. checkbox 绑定：L7630-7726，每个 class 对应 `state.labSigKellyFilters.xxx = checked` + `_kellyOnFilterChange()`
6. purpose-notes.js L30 `"lab.sigkelly"` 巨型字符串，含15 toggle 公示

## 四、v4 实施规格

### 4.1 维度字段映射（trades.json -> v4 维度）

| v4 维度 | 来源 | 判定 |
|---------|------|------|
| `sig_dim` | `signal` | buy=main, buy_aux=aux, buy_special=special, buy_backup=backup |
| `buy_month` | `buy_date` | substring(4,6) "01".."12" |
| `buy_weekday` | `buy_date` | `_kellyBuyWeekday()` 0=Mon 1=Tue 2=Wed |
| `buy_quarter` | `buy_month` | Q1=01-03, Q2=04-06, Q3=07-09, Q4=10-12 |
| `buyprice_bin` | `buy_price` | `_kellyBuypriceBin()` vlow/low/mid/high/vhigh |
| `mkt_dim` | quadrant key | `_tradeDims` 查找 map |
| `rating_dim` | `rating` | 直接读 high/mid/low |
| `etf_dim` | `track_tier` | 直接读 strong/related/approx/none |
| `ts_bin<50` | `track_score` | `track_score < 50` |

### 4.2 后端改动
**无需改动。** toggle 过滤全在前端 lab.js。signal_kelly_backtest.py 已输出所有字段（signal/buy_date/buy_price/track_tier/track_score/rating/market_state）。

### 4.3 前端 lab.js 改动

**A. `_kellyDefaultFilters()` L7231 加 12 字段：**
```javascript
// v4 新标志(第一梯队)
greedy7: false, v4cSimple: false, v4b: false,
// v4 新标志(第二梯队)
greedy10: false, v4d: false, v4j: false, v4i: false,
// v4 新标志(第三梯队,附监控)
greedy15: false, v4f: false, v4g: false, v4m: false, v4k: false,
```

**B. 过滤逻辑 L7306-7338 后追加 v4 块**（现有 v3 块之后、return true 之前）：

新增维度变量（在现有 `_bd3/_mm3/_sig3/_wd3/_bpb3/_mktD3/_ratD3` 基础上）：
```javascript
var _ts3 = fIdx.track_score != null ? Number(t[fIdx.track_score]) : 999;  // ts_bin<50
var _etfD3 = fIdx.track_tier != null ? String(t[fIdx.track_tier] || "") : "";  // etf_dim
var _q3 = Math.ceil(parseInt(_mm3, 10) / 3);  // buy_quarter 1-4
```

12 toggle 过滤条件（`if (filters.xxx && 条件) return false;`）：

```javascript
// === v4 新标志 ===
var _v4On = filters.greedy7 || filters.greedy10 || filters.greedy15 || filters.v4cSimple || filters.v4b || filters.v4d || filters.v4j || filters.v4i || filters.v4f || filters.v4g || filters.v4m || filters.v4k;
if (_v4On) {
  // 第一梯队
  if (filters.v4cSimple && _mm3 === "03" && _wd3 === 2 && _sig3 === "buy_aux") return false;
  if (filters.v4b && _mktD3 === "a" && _mm3 === "05" && _sig3 === "buy_special" && _etfD3 === "related") return false;
  if (filters.greedy7 && (
    (_sig3 === "buy_special" && _mm3 === "05") ||
    (_sig3 === "buy_special" && _mm3 === "11" && _mktD3 === "concept") ||
    (_sig3 === "buy_special" && _mm3 === "03") ||
    (_sig3 === "buy_aux" && _mm3 === "01") ||
    (_q3 === 2 && _bpb3 === "vlow" && _sig3 === "buy_aux" && _mktD3 === "concept") ||
    (_sig3 === "buy" && _mm3 === "01") ||
    (_mm3 === "03" && _wd3 === 2 && _mktD3 === "concept" && _ratD3 === "low")
  )) return false;
  // 第二梯队
  if (filters.v4d && _mm3 === "12" && _wd3 === 1 && _sig3 === "buy_aux" && _ts3 < 50) return false;
  if (filters.v4j && _mm3 === "05" && _bpb3 === "vlow" && _sig3 === "buy_special") return false;
  if (filters.v4i && _sig3 === "buy_special" && _mm3 === "05" && _mktD3 === "concept" && _wd3 === 0) return false;
  if (filters.greedy10 && (
    (_sig3 === "buy_special" && _mm3 === "05") ||
    (_sig3 === "buy_special" && _mm3 === "11" && _mktD3 === "concept") ||
    (_sig3 === "buy_special" && _mm3 === "03") ||
    (_sig3 === "buy_aux" && _mm3 === "01") ||
    (_q3 === 2 && _bpb3 === "vlow" && _sig3 === "buy_aux" && _mktD3 === "concept") ||
    (_sig3 === "buy" && _mm3 === "01") ||
    (_mm3 === "03" && _wd3 === 2 && _mktD3 === "concept" && _ratD3 === "low") ||
    (_sig3 === "buy_aux" && _mm3 === "12" && _ts3 < 50) ||
    (_mm3 === "06" && _bpb3 === "vlow" && _ratD3 === "low") ||
    (_sig3 === "buy_aux" && _mm3 === "05")
  )) return false;
  // 第三梯队(附监控)
  if (filters.v4f && _sig3 === "buy" && _mm3 === "06" && _wd3 === 2 && _etfD3 === "related") return false;
  if (filters.v4g && _mktD3 === "global" && _q3 === 1 && _sig3 === "buy_aux" && _ratD3 === "low") return false;
  if (filters.v4m && _sig3 === "buy_special" && _mm3 === "09" && _wd3 === 2) return false;
  if (filters.v4k && _sig3 === "buy" && _mm3 === "01" && _bpb3 === "high") return false;
  if (filters.greedy15 && (
    (_sig3 === "buy_special" && _mm3 === "05") ||
    (_sig3 === "buy_special" && _mm3 === "11" && _mktD3 === "concept") ||
    (_sig3 === "buy_special" && _mm3 === "03") ||
    (_sig3 === "buy_aux" && _mm3 === "01") ||
    (_q3 === 2 && _bpb3 === "vlow" && _sig3 === "buy_aux" && _mktD3 === "concept") ||
    (_sig3 === "buy" && _mm3 === "01") ||
    (_mm3 === "03" && _wd3 === 2 && _mktD3 === "concept" && _ratD3 === "low") ||
    (_sig3 === "buy_aux" && _mm3 === "12" && _ts3 < 50) ||
    (_mm3 === "06" && _bpb3 === "vlow" && _ratD3 === "low") ||
    (_sig3 === "buy_aux" && _mm3 === "05") ||
    (_sig3 === "buy_special" && _mm3 === "11" && _mktD3 === "industry") ||
    (_mm3 === "04" && _wd3 === 1 && _mktD3 === "concept" && _ts3 < 50) ||
    (_mktD3 === "global" && _q3 === 1 && _sig3 === "buy_aux" && _ratD3 === "low") ||
    (_mm3 === "01" && _bpb3 === "low" && _sig3 === "buy_special" && _mktD3 === "concept") ||
    (_sig3 === "buy_special" && _mm3 === "09" && _wd3 === 2)
  )) return false;
}
```

**C. toggleHTML（L7577-7597）追加 v4 分组**：在现有"比值>3"和"比值<3"两组之间插入"v4新标志"分组，按三梯队分三段。复用现有 `<label class="lab-sigkelly-toggle" tabindex="0" data-no-pop="" data-tip="...">` 模式。⚠️监控项 toggle 加 `⚠️监控` 标注。

**D. checkbox 绑定（L7630-7726）追加 12 个 onchange**：每个新 toggle class 对应 `state.labSigKellyFilters.xxx = cb.checked; _kellyOnFilterChange();`。

### 4.4 purpose-notes.js 改动（§21 算法公示同步）

在 `"lab.sigkelly"` 字符串"降亏过滤"段落末尾追加：
```
第三梯队(v4新方法挖掘,4方法:Contrast Set/Emerging Pattern JEP/Closed Itemset去冗余/Greedy组合优化):
第一梯队:⑯Greedy-7(7组合,比值3.15,净+100.7万,PF1.54,maxSh0.28);⑰V4-C简化(3月+周三+辅关注,比值7.84,净+11.3万);⑱V4-B(A股+5月+追关注+related,比值53.96,6年全正)。
第二梯队:⑲Greedy-10(10组合,比值3.06,净+123万);⑳V4-D(12月+周二+辅关注+低分,比值12.20,5年全正);㉑V4-J(5月+vlow+追关注,比值15.55,⑦n5细化版maxSh66%->40%);㉒V4-I(追关注+5月+概念+周一,比值27.04)。
第三梯队(附监控):㉓Greedy-15(15组合,比值3.29,净+149万,损盈9.84%);㉔V4-F(6月+周三+主关注+related,比值999 JEP,⚠n=60太小);㉕V4-G(全球+Q1+辅关注+低评级,比值6.25,⚠近年才转亏);㉖V4-M(9月+周三+追关注,比值115.56,⚠只3年);㉗V4-K(1月+主关注+高价,比值10.11,⚠有子集盈利年)。
Greedy-7/10/15为嵌套组合(15⊃10⊃7),单checkbox=并集OR过滤。Greedy-15含step11=现有N2、step13=V4-G、step15=V4-M,同时开启幂等无害。
```

### 4.5 V4-F/G/M/K 监控警告标注

| toggle | tooltip 内容 |
|--------|-------------|
| v4f | n=60太小，只3年数据，JEP ratio=999虚高。每年6月检查，子集转盈则暂停。 |
| v4g | 2023-2024子集实际盈利，2025-2026才大亏。近年才显现，可能是市场结构变化。观察2年再决定。 |
| v4m | 只3年数据（2021/2024/2026），ratio=115.56虚高。数据不足，每年检查。 |
| v4k | 2017/2025有子集盈利年，3/5年净正非全正。稳定性不足。 |

## 五、去重后总 toggle 数

- 现有 15 + v4 新增 12 = **总计 27 toggle**
- **叠加非替换**：V4-J 可替代⑦n5、V4-B 可替代 n4，但按"全部上线"保留两者
- Greedy-15 step11=现有N2，同时开启幂等无害

## 六、Greedy 组合上线方式

**推荐：单组合 toggle（Greedy-7/10/15 各 1 checkbox = 并集 OR），不拆分单 step。**

理由：
1. ratio>3 只在并集成立（个别 step ratio<3：step4=2.61/step6=2.64/step8=2.87/step10=2.56），拆分后单 step 不满足门槛
2. backtest 统计量是并集的（净影响/PF/ratio/maxSh 都是 7/10/15 step 并集结果）
3. UI 简洁（3 组合 checkbox vs 拆 15 单 step = 30 总量过杂）
4. 嵌套幂等（15⊃10⊃7，同时开启无害）

## 关键文件路径
- v4 细说：`docs/kelly-v4-detail.md`（487行）
- v4 挖掘报告：`docs/kelly-loss-mining-v4.md`
- 前端 toggle 过滤：`static-site/lab.js` L7230-7727
- 算法公示：`static-site/purpose-notes.js` L30
- 后端 trades 生成（无需改）：`scripts/signal_kelly_backtest.py`
