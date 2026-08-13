# 降亏 toggle v2 实施计划（4toggle 多选开关）

> 调研日期：2026-08-08 ｜ 只读调研，不改代码 ｜ 数据源：`static-site/data/signal_kelly_trades.json`（上线版 20 字段含 market_state）
> 前置：等 tooltip-fix + hover reviewer 完成后串行实施（都改 lab.js 避撞车）

## 0. 摘要

新增 2 个降亏 toggle（排除 3+5 月 + 排除 rating=low），和现有 2 个（excludeAux 排除 buy_aux + marketTiming MA60 大盘择时）组合成 **4toggle 独立多选开关**，都默认关闭，hover 标注风险说明。

**核心结论：**
- **排除 3+5 月**：纯前端过滤，`buy_date` 字段已有（YYYYMMDD 格式），**不需改后端**
- **排除 rating=low**：rating 不在 trade 记录里（只用于后端分 quadrant），**需改后端**注入 rating 字段 + 重跑 trades.json
- 4toggle 独立可组合，filter 叠加，null 安全

---

## 1. 字段确认结果

### 1.1 trades.json 字段（上线版 static-site/data/，20 字段）

```
fields: [signal_date, index_id, signal, buy_date, sell_date, etf_code, etf_name,
         track_tier, track_score, match_method, track_low_confidence,
         buy_price, sell_price, shares, profit, return_pct,
         hold_days, sell_reason, current_price, market_state]
```

| 字段 | index | 格式/值域 | 新toggle用途 | 现有toggle用途 | 结论 |
|------|-------|-----------|-------------|---------------|------|
| buy_date | 3 | YYYYMMDD（如 '20210607'） | 排除3+5月：`substring(4,6)` 提取月份 | cutoff周期过滤 | ✓ 已有，纯前端 |
| signal | 2 | buy/buy_aux/buy_special/buy_backup | - | excludeAux：`=== "buy_aux"` | ✓ 已有 |
| market_state | 19 | true/false（多头/空头） | - | marketTiming：`!== true` 排除 | ✓ 已有（上线版） |
| **rating** | **无** | high/mid/low | 排除rating=low：`=== "low"` | - | ✗ **不在trade记录里** |

### 1.2 rating 不在 trade 记录里的根因

后端 `signal_kelly_backtest.py`：
- rating 从 `signal_stats` 的 10d score 计算（L724-736）：
  - `score >= 0.75`（RATING_HIGH）→ "high"
  - `score >= 0.55`（RATING_MID）→ "mid"
  - `score < 0.55` → "low"
- rating **只用于分 quadrant**（L761：`quadrants[f"rating_{rating}"][mode_key].append(result)`）
- rating **不在 TRADE_FIELDS**（L805-808），不写入 trade 记录

### 1.3 两版本差异（注意）

| 版本 | 路径 | 字段数 | market_state | rating |
|------|------|--------|-------------|--------|
| 上线版 | `static-site/data/signal_kelly_trades.json` | 20 | ✓ 有 | ✗ 无 |
| 旧版 | `trade/data/signal_kelly_trades.json` | 19 | ✗ 无 | ✗ 无 |

- 上线版有 market_state，现有 marketTiming toggle **生效**（fIdx.market_state 有值）
- 旧版 trade/data/ 是历史遗留，前端不读（前端读 R2 或 static-site/data/）

---

## 2. 前端过滤路径

### 2.1 两处 filter 点（都需改）

| 位置 | 函数 | 行号 | 作用 |
|------|------|------|------|
| 主路径 | `_kellyApplyFeeRecompute` | L7235-7240 | quadrant 遍历里的 trade filter，重算所有统计 |
| 明细路径 | `_renderSigKellyQuadrants` 内 | L8040-8045 | 单象限明细展开的 trade filter（与卡片统计一致，§22 数据一致性） |

现有 filter 逻辑（两处相同）：
```js
var trades = rawTrades.filter(function (t) {
  if (cutoff && cutoff !== "0" && (t[fIdx.buy_date] || "") < cutoff) return false;
  if (filters.excludeAux && fIdx.signal != null && (t[fIdx.signal] || "") === "buy_aux") return false;
  if (filters.marketTiming && fIdx.market_state != null && t[fIdx.market_state] !== true) return false;
  return true;
});
```

### 2.2 新增 2 个 if 条件（叠加到现有 filter）

```js
// 排除3+5月（buy_date 月份 03/05）
if (filters.excludeMarMay && fIdx.buy_date != null) {
  var _m = (t[fIdx.buy_date] || "").substring(4, 6);
  if (_m === "03" || _m === "05") return false;
}
// 排除rating=low
if (filters.excludeRatingLow && fIdx.rating != null && t[fIdx.rating] === "low") return false;
```

### 2.3 组合逻辑

- 4toggle 独立可组合，4 个 if 条件串联在同一个 filter 函数里
- 开启多个 = filter 叠加（AND 关系，都满足才保留）
- 和费率改 profit（recompute）正交不互斥（现有设计，L7225 注释）

### 2.4 null 安全

| toggle | 字段缺失行为 | 参考 |
|--------|-------------|------|
| 排除3+5月 | buy_date 缺失→空字符串→substring(4,6)=""→不匹配03/05→**保留**（不排除） | - |
| 排除rating=low | rating 缺失→fIdx.rating=undefined(null)→`fIdx.rating != null` false→**保留**（不排除） | 同 marketTiming 的 `fIdx.market_state != null` 降级 |

---

## 3. toggle UI 设计

### 3.1 HTML 结构（照搬现有，加 2 个 label）

位置：`_renderSigKellyBar` L7477-7482 的 `toggleHTML`

```js
const toggleHTML = `<div class="lab-sigkelly-toggle-row">` +
    `<span class="lab-sigkelly-toggle-label">降亏过滤:</span>` +
    // 现有1: 排除buy_aux
    `<label class="lab-sigkelly-toggle" tabindex="0" data-no-pop="" data-tip="..."><input type="checkbox" class="lab-sigkelly-toggle-aux"${_filters.excludeAux ? " checked" : ""}> 排除辅关注(buy_aux) <span class="lab-sigkelly-toggle-tip">ⓘ</span></label>` +
    // 现有2: MA60大盘择时
    `<label class="lab-sigkelly-toggle" tabindex="0" data-no-pop="" data-tip="..."><input type="checkbox" class="lab-sigkelly-toggle-mkt"${_filters.marketTiming ? " checked" : ""}> MA60大盘择时(仅A股类) <span class="lab-sigkelly-toggle-tip">ⓘ</span></label>` +
    // 新增3: 排除3+5月
    `<label class="lab-sigkelly-toggle" tabindex="0" data-no-pop="" data-tip="季节性过滤。历史6年3/5月亏多盈少，系统性不强可能过拟合。组合aux+MA60+3 5月减亏73%净保留116%"><input type="checkbox" class="lab-sigkelly-toggle-mar"${_filters.excludeMarMay ? " checked" : ""}> 排除3+5月(季节性) <span class="lab-sigkelly-toggle-tip">ⓘ</span></label>` +
    // 新增4: 排除rating=low
    `<label class="lab-sigkelly-toggle" tabindex="0" data-no-pop="" data-tip="低评分信号是最大亏损源(占79%)，排除降亏显著但剩样本少可能过拟合"><input type="checkbox" class="lab-sigkelly-toggle-rating"${_filters.excludeRatingLow ? " checked" : ""}> 排除低评级(rating=low) <span class="lab-sigkelly-toggle-tip">ⓘ</span></label>` +
    `<span class="lab-sigkelly-toggle-hint">独立/组合开启,实时过滤重算</span>` +
  `</div>`;
```

### 3.2 class 命名

| toggle | checkbox class | state key |
|--------|---------------|-----------|
| 排除buy_aux（现有） | `.lab-sigkelly-toggle-aux` | `excludeAux` |
| MA60择时（现有） | `.lab-sigkelly-toggle-mkt` | `marketTiming` |
| 排除3+5月（新增） | `.lab-sigkelly-toggle-mar` | `excludeMarMay` |
| 排除rating=low（新增） | `.lab-sigkelly-toggle-rating` | `excludeRatingLow` |

### 3.3 事件绑定（照搬现有，加 2 个 onchange）

位置：`_renderSigKellyBar` L7515-7527

```js
// 新增3: 排除3+5月
var marCb = bar.querySelector(".lab-sigkelly-toggle-mar");
if (marCb) marCb.onchange = function () {
  if (!state.labSigKellyFilters) state.labSigKellyFilters = { excludeAux: false, marketTiming: false, excludeMarMay: false, excludeRatingLow: false };
  state.labSigKellyFilters.excludeMarMay = marCb.checked;
  _kellyOnFilterChange();
};
// 新增4: 排除rating=low
var ratingCb = bar.querySelector(".lab-sigkelly-toggle-rating");
if (ratingCb) ratingCb.onchange = function () {
  if (!state.labSigKellyFilters) state.labSigKellyFilters = { excludeAux: false, marketTiming: false, excludeMarMay: false, excludeRatingLow: false };
  state.labSigKellyFilters.excludeRatingLow = ratingCb.checked;
  _kellyOnFilterChange();
};
```

### 3.4 state 扩展

所有 `state.labSigKellyFilters` 默认值从 `{ excludeAux: false, marketTiming: false }` 改为 `{ excludeAux: false, marketTiming: false, excludeMarMay: false, excludeRatingLow: false }`。

涉及 4 处（grep `labSigKellyFilters` 全改）：
- L7226（_kellyApplyFeeRecompute）
- L7423（初始化）
- L7476（_renderSigKellyBar）
- L7519/7524（事件绑定里的 fallback）
- L8039（明细 filter）

### 3.5 CSS

现有 CSS（lab.css L1433-1443）无需改，新增 toggle 自动继承 `.lab-sigkelly-toggle` 样式 + `data-tip` CSS tooltip。

### 3.6 hover tooltip 注意（double-tooltip bug）

- 现有 toggle 用 `data-no-pop=""` + `data-tip`（CSS tooltip），跳过 app.js `_initTermPop` 的 term-pop
- app.js L2389-2405：`data-no-pop` 元素不触发 term-pop（避免 .term-pop z:9999 盖住 CSS tooltip）
- 新增 2 toggle 照搬 `data-no-pop=""` + `data-tip` 模式
- **等 tooltip-fix 完成后实施**（任务约束：都改 lab.js 避撞车）

---

## 4. hover 文案

| toggle | data-tip 文案 | 依据 |
|--------|-------------|------|
| 排除3+5月 | 季节性过滤。历史6年3/5月亏多盈少，系统性不强可能过拟合。组合aux+MA60+3 5月减亏73%净保留116% | v2文档§2.10+§3.3：3月净-36K/5月净-59K，6年3亏3盈系统性不强；aux+MA60+3+5月减亏72.8%净保留115.8% |
| 排除rating=low | 低评分信号是最大亏损源(占79%)，排除降亏显著但剩样本少可能过拟合 | v2文档§2.12：low档占78.8%是最大亏损源914K(占基准总亏83%)，排除牺牲72%利润净保留仅64.5% |

---

## 5. 后端是否需改

### 5.1 排除3+5月：不需改后端

- `buy_date` 字段已在 trades.json（字段 index 3，YYYYMMDD 格式）
- 纯前端 `substring(4,6)` 提取月份过滤

### 5.2 排除rating=low：需改后端（注入 rating 字段）

**后端改动（`scripts/signal_kelly_backtest.py`）：**

1. **TRADE_FIELDS 加 "rating"**（L805-808）：
   ```python
   TRADE_FIELDS = ["signal_date", "index_id", "signal", "buy_date", "sell_date", "etf_code", "etf_name",
                   "track_tier", "track_score", "match_method", "track_low_confidence",
                   "buy_price", "sell_price", "shares", "profit", "return_pct",
                   "hold_days", "sell_reason", "current_price", "market_state", "rating"]
   ```

2. **`_backtest_one` 参数加 rating**（L280-283）：
   ```python
   def _backtest_one(signal_date, prices, sorted_dates_list, etf_code, etf_name, stop_profit,
                     index_id=None, signal=None, track_tier=None, track_score=None,
                     match_method=None, track_low_confidence=None, today=None, hold_days=HOLD_DAYS,
                     market_state=None, rating=None):
   ```

3. **`_backtest_one` 两处返回 dict 加 "rating": rating**（L338-358 持有中 + L380-400 已卖出）

4. **主循环传 rating 给 `_backtest_one`**（L753-756）：
   ```python
   result = _backtest_one(date, prices, sdates, etf_code, be["name"], mode_def["stop_profit"],
                          iid, sig, be.get("track_tier"), be.get("track_score"),
                          be.get("match_method"), be.get("track_low_confidence"),
                          today=today_str, hold_days=mode_def["hold_days"], market_state=ms, rating=rating)
   ```

5. **重跑后端生成新 trades.json**：
   - `signal_kelly_backtest.py` 无 launchd 定时（已确认 launchctl list 无 kelly），需手动跑
   - 命令：`cd /Users/linhuichen/code/trade-data && /Users/linhuichen/code/trade/.venv/bin/python /Users/linhuichen/code/trade/scripts/signal_kelly_backtest.py`（cwd trade-data 读主库，§9）
   - 输出落在 `trade-data/data/signal_kelly_trades.json`，需 cp 或 rsync 同步到 `trade/static-site/data/`（§9 export 输出路径同步）
   - 上传 R2：`upload_r2.py upload-data-large` 或手动上传 signal_kelly_trades.json（§8.1）

### 5.3 重跑后 rating 字段在 trade 记录里

重跑后 trades.json 的 fields 变成 21 字段（加 rating），每笔 trade 数组末尾追加 rating 值（"high"/"mid"/"low"）。前端 `fIdx.rating` 有值，过滤生效。

---

## 6. 实施步骤（串行，等 tooltip-fix 完成后）

### Step 1: 后端改动（排除rating=low 需要）
1. 改 `scripts/signal_kelly_backtest.py`（4 处：TRADE_FIELDS + _backtest_one 参数 + 2 处返回 dict + 主循环传参）
2. 手动重跑：`cd trade-data && python signal_kelly_backtest.py`
3. 同步：cp `trade-data/data/signal_kelly_trades.json` → `trade/static-site/data/`
4. 上传 R2（signal_kelly_trades.json）
5. 验证：`python3 -c "import json; d=json.load(open('static-site/data/signal_kelly_trades.json')); print('fields:',d['fields']); print('has rating:', 'rating' in d['fields'])"` 确认 21 字段含 rating

### Step 2: 前端改动
1. `state.labSigKellyFilters` 默认值扩展为 4 字段（5 处 grep 全改）
2. `toggleHTML` 加 2 个 label（L7477-7482）
3. 事件绑定加 2 个 onchange（L7515-7527）
4. 两处 filter 加 2 个 if 条件（L7235-7240 + L8040-8045）

### Step 3: 构建+上线
1. `python3 scripts/build_min.py`（terser minify lab.js → lab.min.js）
2. `python3 scripts/bump_asset_version.py`（md5 前 8 位破缓存）
3. `bump sw.js CACHE_VERSION`（§9：改 lab.js 必 bump sw，否则旧 SW 缓存旧 lab.min.js）
4. 验 min 版用字符串非变量名（§9：terser mangle 重命名局部变量，grep 用 class 名/中文字符串如 "lab-sigkelly-toggle-mar"）
5. commit + push feat + merge main + push main
6. 避开定时任务时点（§14：盘中避开 intraday 每10分钟 + 盘后 15:35/16:00/17:50/20:35）

### Step 4: 验证上线
1. curl `https://ssd.fx8.store/data/signal_kelly_trades.json` 确认 fields 含 rating（21 字段）
2. curl `https://ss.fx8.store/` 打开策略实验室，确认 4toggle 显示
3. 开启"排除3+5月"：确认 3月5月的 trade 被过滤（统计变化）
4. 开启"排除rating=low"：确认 rating_low 象限的 trade 被过滤
5. 4toggle 组合开启：确认 filter 叠加生效
6. 让用户确认显示

---

## 7. 风险标注

| 风险 | 说明 | 缓解 |
|------|------|------|
| 3+5月过拟合 | 6年里3月3亏3盈、5月3亏3盈，系统性不强 | toggle 默认关闭，hover 标注"可能过拟合" |
| rating=low样本少 | 排除low后仅剩 high(83笔)+mid(1219笔)=1302笔，样本少 | toggle 默认关闭，hover 标注"剩样本少可能过拟合" |
| 后端重跑耗时 | signal_kelly_backtest.py 全量回测 7472 笔 × 6 模式 | trade-data 跑，预计几分钟（历史 backfill 已跑过） |
| trades.json 体积 | 加 rating 字段后 32MB→约 34MB | R2 已承载，前端走 R2 直链（§8.1） |

---

## 附录 A：现有 toggle 实现参考

| 项 | 现有实现 | 位置 |
|----|---------|------|
| 核心重算 | `_kellyApplyFeeRecompute(feeParams)` | lab.js L7191-7252 |
| filter 点1 | quadrant 遍历 trade filter | L7235-7240 |
| filter 点2 | 明细展开 trade filter | L8040-8045 |
| toggle 切换处理 | `_kellyOnFilterChange()` | L7333-7344 |
| toggle HTML | `_renderSigKellyBar` toggleHTML | L7477-7482 |
| 事件绑定 | `_renderSigKellyBar` onchange | L7515-7527 |
| state 初始化 | `state.labSigKellyFilters` | L7423 |
| CSS | lab.css L1433-1443 | data-tip CSS tooltip |
| term-pop 跳过 | `data-no-pop=""` | app.js L2389-2405 |

## 附录 B：v2 文档数据依据

| toggle | 减亏% | 净保留% | 胜率 | 盈亏比 | 来源 |
|--------|-------|---------|------|--------|------|
| 排除buy_aux（现有） | 37% | 110% | 54.8% | 1.29 | v2 §3.1 |
| MA60多头（现有） | 50% | 93% | 54.8% | 1.33 | v2 §3.1 |
| 排除aux+MA60（现有组合） | 64% | 98% | 55.8% | 1.50 | v2 §3.2 |
| 排除3+5月（新增） | 18% | 127% | 55.1% | 1.22 | v2 §3.1 |
| 排除rating>=mid（新增参考） | 83% | 65% | 59.2% | 1.56 | v2 §3.1（评级>=mid，过激进不推荐单独用） |
| aux+MA60+3+5月（4toggle组合） | 73% | 116% | 59.8% | 1.60 | v2 §3.3 |
