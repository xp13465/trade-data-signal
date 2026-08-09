# 凯利回测卡间比较水印方案（调研产出，供实施 agent 用）

> 调研日期: 2026-08-08 ｜ 只读调研，未改代码 ｜ 数据源: `static-site/data/signal_kelly_backtest.json` + `scripts/signal_kelly_backtest.py` + `static-site/lab.js`

## 0. 需求复述

用户原话:"这个水印是用卡和卡之间比较。比如近1年里有10张卡。我想要的是综合成绩最好的那一张卡。或者最稳定的一张卡。来做水印标记。评级标准可以你来定"。

- **卡间比较**层（卡 vs 卡），区别于现有**卡内比较**层（commit 998d21023，卡内 A-F 模式组比较三态 TOP1·X/分化·X/淘汰）。
- 现有卡内水印**保留不回退**，卡间水印是**额外加的层**，不替换。
- 标记"综合成绩最好"或"最稳定"的卡。
- 评级标准主控定，本文档给默认公式。

用户观察"近1年里有10张卡""1w 跑近5年7张卡基本都红"——实际当前每周期 16 张卡全有数据（见 §1），用户记忆为粗略数；"基本都红"指现有水印多为 TOP1 态（全>0 盈亏）。

---

## 1. 卡的定义与数据结构

### 1.1 一张卡 = 一个象限(quadrant)在某周期(period)下的展示

`_renderSigKellyQuadrants`（lab.js L7464）按 **4 组**遍历渲染卡片，每组内每张卡调用 `_renderSigKellyCard`（L7687）：

| 组 | 标题 | 象限 key | 卡数 |
|---|---|---|---|
| 评级 | 按信号评级分组(10d score 评级) | rating_high / rating_mid / rating_low | 3 |
| ETF | 按 ETF 跟踪评分分组(track_tier 归类) | etf_strong / etf_related / etf_approx / etf_has_track | 4 |
| 信号类型 | 按信号类型分组(主/辅/追/备关注) | sig_main / sig_aux / sig_special / sig_backup | 4 |
| 市场大类 | 按指数大类分组(宽基/港股/全球/行业/概念) | mkt_a / mkt_hk / mkt_global / mkt_industry / mkt_concept | 5 |
| **合计** | | | **16** |

- 周期 5 个: y1 / y3 / y5 / y10 / all（`config.periods`，bar 顶部 tab 切换）。
- **每周期 16 张卡全有数据**（实测 y1~all 均 16 张，各卡 6 模式 n>0）。lab.js L7463 注释"16象限"已对，L7325 注释"6象限"已过时。
- 每张卡内含 **6 个卖出模式**（A-F，`config.sell_modes`）的宽表行，每模式独立 stats。
- `groups` 里列了 `mkt_concept`，JSON `quadrants` 也有该 key（之前 `list(keys)[:15]` 截断误判为 15，实际 16）。

### 1.2 周期切换重渲染

`_renderSigKellyBar`（L7396）周期 tab onclick → `_renderSigKellyQuadrants` 重渲染所有卡（L7448）。卡间水印随重渲染自动更新，和现有卡内水印一致。

### 1.3 费率客调

`_kellyApplyFeeRecompute`（L7184）重算 stats 存 `state.labSigKellyFeeStats`，结构 `{qk: {period: {mode: stats}}}` 与原始一致。`_renderSigKellyCard`（L7691）优先用 `feeStats` 替换原始 stats。**卡间比较必须前端实时算**（用 `feeStats || 原始`），保证费率客调后卡间水印同步更新，不能用后端预计算（预计算值与客调后不一致）。

---

## 2. 现有卡内水印（commit 998d21023，保留不回退）

### 2.1 逻辑

`_sigKellyWatermark(pdata)`（lab.js L7580）：卡内 6 模式按 `total_profit` 比较三态：
- **TOP1·X**（金）: 全>0，X=最高 tp 方案字母
- **分化·X**（橙）: 有正有负，X=最高 tp 方案字母
- **淘汰**（灰）: 全≤0
- 辅助小字（仅 TOP1/分化）: 风险橙（高仓 half_kelly≥60 / 样本少 n<100）+ 优势绿（高胜率≥0.5 / 低回撤≤15% / 高夏普≥1.0）

### 2.2 展示位置 + CSS

- **右上角**: `position:absolute; top:6px; right:8px`（lab.css L1434，`.lab-sigkelly-wm`）
- 类名: `.lab-sigkelly-wm lab-sigkelly-wm-{top1|mix|out}`（L7743）
- badge `opacity:0.82`，`pointer-events:auto`，hover/tap 弹 hoverpop（`_bindSigKellyWmPop` L7506）
- 配色: top1 金(#b8860b) / mix 橙(#ea580c) / out 灰(#64748b)；dark/redgold 主题有覆盖（L1442-1446）
- 移动端: top:4px right:6px font-size:10px（L1447）

**新卡间水印须避开右上角 + 金/橙/灰色系**，避免视觉撞车（见 §6）。

---

## 3. 指标可得性清单

### 3.1 `_compute_stats`（signal_kelly_backtest.py L482）返回字段

每个 `象限×周期×模式` 都有完整 stats（28 字段）:

| 指标 | 字段 | 单位/范围 | 卡间比较用途 |
|---|---|---|---|
| 样本数 | `n` | int | 过滤小样本 |
| 胜率 | `win_rate` | 0~1 比例 | 综合+稳定 |
| 盈亏比 | `pl_ratio` | 倍(全胜=999, 无=None) | 综合 |
| 单笔均收益率 | `mean_return` | % | 备选 |
| 年化收益 | `annualized_return` | % | 综合(主) |
| 夏普比率 | `sharpe` | per-trade, 无风险0 | 综合+稳定 |
| 最大回撤% | `max_drawdown_pct` | %(回撤/总投入×100) | 稳定(主) |
| 最大回撤额 | `max_drawdown` | 元 | 备选 |
| 卡尔玛 | `calmar` | 年化/最大回撤% | 稳定(备选) |
| 最终盈亏 | `total_profit` | 元 | **不宜卡间比较**(受 n 影响) |
| 总收益率 | `total_return_pct` | % | 备选 |
| 最大持仓收益率 | `return_pct_max_holding` | % | 备选 |
| 半凯利仓位 | `half_kelly` | % | 现有水印已用 |
| 凯利档位 | `kelly_tier` | 激进/均衡/保守 | 现有水印已用 |
| 连胜 max | `win_streak_max` | int | 稳定(备选) |
| 连败 max | `lose_streak_max` | int | 稳定(备选) |
| 最大单笔盈/亏 | `max_single_win`/`max_single_loss` | % | 备选 |
| 平均持仓天数 | `avg_hold_days` | 天 | 备选 |
| 持仓中笔数/资金 | `holding_count`/`holding_capital` | | 不用于比较 |

### 3.2 缺失指标

- **收益波动率(std)**: **无字段**。`sharpe = mean_return / std`（无风险利率 0），可反推 `std = mean_return / sharpe`（sharpe≠0 时），但直接用 sharpe 衡量风险调整收益更稳，无需反推 std。
- 替代方案: 稳定性用 `max_drawdown_pct` + `sharpe` + `win_rate` 组合（均已有字段），不依赖 std。

### 3.3 实测 y1 各卡卡级指标（6 模式均值，见下表量纲差异）

跨组指标差异极大，**说明跨组比较需归一化**:

| 象限 | n(均值) | win_rate | ann_ret% | sharpe | pl_ratio | maxDD% | calmar | tot_prof |
|---|---|---|---|---|---|---|---|---|
| rating_high | 44 | 73.9% | 3.46 | 0.69 | 3.07 | 0.20 | 28.59 | 15234 |
| rating_mid | 538 | 66.1% | 2.17 | 0.40 | 1.41 | 0.36 | 6.43 | 116519 |
| rating_low | 1503 | 54.5% | 0.38 | 0.07 | 1.01 | 0.58 | 0.66 | 56930 |
| sig_special | 1103 | 58.6% | 1.34 | 0.26 | 1.39 | 0.40 | 3.58 | 147847 |
| mkt_concept | 1244 | 60.7% | 1.28 | 0.21 | 1.13 | 0.62 | 2.03 | 159525 |
| sig_aux | 578 | 52.9% | -0.13 | -0.03 | 0.84 | 0.99 | -0.13 | -7672 |
| mkt_hk | 48 | 43.4% | -0.07 | -0.02 | 1.25 | 0.83 | 0.10 | -342 |

关键观察:
- **n 差 34 倍**（rating_high 44 vs rating_low 1503），`total_profit` 受 n 影响极大（大样本卡总盈亏虚高），**不宜用 total_profit 做卡间比较**，改用 `annualized_return`（已年化，不受 n 影响）。
- **跨组语义不同**: 评级组按信号质量分组（high 当然胜率高），ETF 组按跟踪质量分组，信号组按信号类型分组，市场组按指数大类分组。跨组比"谁最好"类似"苹果比橘子"（见 §4 scope 讨论）。

---

## 4. 卡间比较 Scope（需用户确认，附推荐）

### 4.1 三个选项

| 选项 | scope | 每周期标记数 | 优劣 |
|---|---|---|---|
| A 全局 | 16 张卡互比选 1 最佳 + 1 稳定 | 2 | 跨组语义不一（评级 high vs mkt_hk 不可比）；大样本卡指标虚高；用户"那一张卡"字面吻合 |
| B 同组内 | 每组(3~5 张)互比选 1 最佳 + 1 稳定 | 8 (4组×2) | **语义合理**（同组内可比）；每组各有最佳；信息量适中 |
| C 全局+比率 | 16 张互比，仅用比率指标(胜率/夏普/年化,不受 n 影响) + 排除 n<30 | 2 | 折中，但仍跨组语义不一 |

### 4.2 推荐: 选项 B（同组内比较）

理由:
1. **语义可比**: 同组内卡是同类分组内的细分（评级组内 high/mid/low 看哪段回测最好；ETF 组内看哪档跟踪质量回测最好），跨组无可比性。
2. **样本量同量级**: 同组内 n 差异小（评级组 44/538/1503 仍有差，但比跨组的 44 vs 1503 小）。归一化在同组内更稳。
3. **信息量**: 每组标 1 最佳 + 1 稳定，4 组共 8 个标记，用户一眼看到"每组里谁最好"，不过载。
4. 用户说"那一张卡"可理解为"每组里那一张"，且用户提到"10张卡"接近单组卡数或两组之和，非全局 16。

**若用户坚持全局选 1 张**，降级为选项 C（仅比率指标 + n<30 排除 + 全局 min-max 归一化），但需提示跨组语义风险。

### 4.3 每组选几张

- 默认每组选 **1 综合最佳 + 1 最稳定**（可同一张卡同时拿两个标记，若它两项都第一）。
- 组内卡数 < 2 不标（实际组内 3~5 张，都够）。

---

## 5. 评级公式

### 5.1 卡级指标定义（6 模式聚合）

一张卡有 6 模式(A-F)独立 stats。**卡级指标 = 卡内 6 模式该指标的均值**（等权，代表该象限跨卖出策略的平均表现）。

小样本处理:
- **模式级 n<30 排除**: 卡内 6 模式先过滤 `n < 30` 的，再取均值（比现有水印 n<100 更严，卡间比较需更稳）。
- **整卡样本不足**: 若过滤后无模式（全 n<30），该卡标"样本不足"不参与排名（实际 y1 rating_high n=44、mkt_hk n=48 均≥30，其余更大，基本不触发）。
- `pl_ratio = None`（无胜或全零）按 0 计；`pl_ratio = 999`（全胜）按上限截断（如 cap 5.0，避免极值拉偏归一化）。

备选（方案文档记录，不默认）: 卡级指标取"卡内最佳模式"（现有水印 TOP1·X 那个）代表。但最佳模式代表单点而非整体，均值更稳健，默认用均值。

### 5.2 归一化: 同组内 min-max

同组内（3~5 张卡）对每个指标做 min-max 归一化到 0~1:

```
norm = (x - min) / (max - min)     # 越大越好的指标(胜率/年化/夏普/盈亏比/卡尔玛)
norm = (max - x) / (max - min)     # 越小越好的指标(最大回撤/连败)，即 1 - 上面那个
```

选 min-max 而非 z-score 的理由: 同组内仅 3~5 张卡，z-score 样本太小标准差不稳；min-max 直观且不受分布假设。缺点是受极值影响（组内一张极端值压缩区分度），但组内卡数少极值影响有限。

边界: 组内某指标全同值（max==min）→ 该指标所有卡 norm=0.5（中性），权重保留但不影响排名（或该指标权重平摊到其他指标，二选一，默认前者简单）。

### 5.3 综合最佳分（用户默认公式，指标已验证可得）

```
综合分 = win_rate_norm × 30% + annualized_return_norm × 30% + sharpe_norm × 20% + pl_ratio_norm × 20%
```

- 4 指标均有字段（§3.1 验证 ✓）。
- 权重用户给定，主控采纳。
- 年化收益用 `annualized_return`（不受 n 影响），不用 `total_profit`（受 n 虚高）。
- 组内综合分最高的卡标"综合最佳"。

### 5.4 最稳定分（用户默认 + std 替代）

用户默认: 稳定分 = (1-最大回撤)×40% + 胜率×30% + (1-收益波动率)×30%。

**std 无字段（§3.2）**，调整为:

```
稳定分 = (1 - max_drawdown_pct_norm) × 40% + win_rate_norm × 30% + sharpe_norm × 30%
```

调整理由:
- `max_drawdown_pct`: 越小越稳定（回撤小），占 40%（保留用户权重）。
- `win_rate`: 胜率高→连亏少→稳定，占 30%（保留用户权重）。
- `sharpe` 替代 `(1-收益波动率)`: 夏普=均值/std，夏普高=风险调整收益好=波动相对收益小=稳定。用 sharpe 代替 std 反向，权重 30%（保留用户权重，sharpe 越大越好 = 1-波动率 越大越好，方向一致）。
- 组内稳定分最高的卡标"最稳定"。

备选稳定性指标（可替换 sharpe 的 30%）: `calmar`(年化/最大回撤，越高越稳) 或 `(1 - lose_streak_max_norm)`(连败短越稳)。默认用 sharpe（数据全且有代表性）。

---

## 6. 水印展示设计（不撞现有）

### 6.1 位置: 左上角

现有卡内水印在**右上角**（top:6px right:8px）。卡间水印放**左上角**（top:6px left:8px），完全不撞。

### 6.2 配色: 蓝/紫色系（区别现有金/橙/灰）

| 标记 | 文案 | 配色(浅色) | 配色(dark/redgold) |
|---|---|---|---|
| 综合最佳 | `★综合最佳` | 蓝 `#1d4ed8` bg `rgba(29,78,216,0.14)` border `rgba(29,78,216,0.4)` | `#7da8ff` bg `rgba(59,130,246,0.18)` |
| 最稳定 | `◆最稳定` | 紫 `#7c3aed` bg `rgba(124,58,237,0.14)` border `rgba(124,58,237,0.4)` | `#b899ff` bg `rgba(139,92,246,0.18)` |

- 与现有金/橙/灰视觉区分。
- ★/◆ 前缀图标增强辨识。
- badge `opacity:0.9`（比现有 0.82 略高，卡间标记更醒目）。
- 移动端: top:4px left:6px font-size:10px（与现有对称）。

### 6.3 hoverpop 说明（复用现有 pop 机制）

卡间水印 hover/tap 弹 hoverpop（复用 `_bindSigKellyWmPop` 的 hover/click/移动端关闭逻辑，或新增 `_bindSigKellyCwmPop`）:
- 评级公式说明（综合分/稳定分各项权重 + 指标含义）
- 该卡在组内的各指标排名 + 分值（如"综合分 0.82 组内第 1/4"）
- min-max 归一化说明
- 小样本排除规则（n<30 模式排除）

### 6.4 CSS 类名

```
.lab-sigkelly-cwm              /* 卡间水印基类: position:absolute; top:6px; left:8px; ... */
.lab-sigkelly-cwm-best         /* 综合最佳: 蓝色系 */
.lab-sigkelly-cwm-stable       /* 最稳定: 紫色系 */
.lab-sigkelly-cwm-badge        /* 文字 span */
.lab-sigkelly-cwm-pop-wrap     /* hoverpop 容器, 复用 .lab-sigkelly-wm-pop 样式 */
[data-theme="dark/redgold"] 覆盖
@media (max-width:760px) 移动端
```

### 6.5 一张卡同时拿两个标记

若一张卡综合分和稳定分都组内第一，左上角同时显示"★综合最佳 ◆最稳定"两个徽章（横向排列），或合并为"★综合最佳·最稳定"。默认横向排列两个 badge（信息独立）。

---

## 7. 实施切入点（供实施 agent）

### 7.1 lab.js 改动

**新增 `_sigKellyCardComparison(quads, period, groupKeys, feeStats)` 函数**:
- 输入: 全象限 quads、当前周期、组内 key 列表(如 `["rating_high","rating_mid","rating_low"]`)、feeStats(若客调)
- 逻辑:
  1. 遍历组内每张卡，取 `pdata = feeStats?.[qk]?.[period] || quads[qk].periods[period]`
  2. 卡级指标: 卡内 6 模式过滤 `n<30`，取均值（win_rate/annualized_return/sharpe/pl_ratio/max_drawdown_pct）
  3. 整卡样本不足(过滤后无模式)→ 标记 skip
  4. 同组内 min-max 归一化每个指标（越小越好指标反转）
  5. 算综合分(§5.3) + 稳定分(§5.4)
  6. 返回 `{ best: {qk, score, details}, stable: {qk, score, details}, allCards: [{qk, scores, ranks, skip}] }`
- `details` 含各指标原始值/归一化值/排名，供 hoverpop 展示

**`_renderSigKellyQuadrants`（L7473-7483）改动**:
- 每组渲染前调用 `_sigKellyCardComparison(quads, period, g.keys, feeStats)`
- 结果传给 `_renderSigKellyCard`（新增 `cardCmp` 参数）

**`_renderSigKellyCard`（L7687）改动**:
- 新增参数 `cardCmp`（该卡的比较结果: 是否 best/stable + 分值 + details）
- 在卡 HTML 顶部（现有 `wm` 之后）插入卡间水印 div:
  ```
  (cardCmp?.isBest ? `<div class="lab-sigkelly-cwm lab-sigkelly-cwm-best" data-cwm="1">★综合最佳<span class="lab-sigkelly-cwm-badge">...</span><div class="lab-sigkelly-cwm-pop-wrap">...</div></div>` : ``) +
  (cardCmp?.isStable ? `<div class="lab-sigkelly-cwm lab-sigkelly-cwm-stable" data-cwm="1">◆最稳定...</div>` : ``)
  ```
- hoverpop HTML: 新增 `_sigKellyCwmPopupHtml(cardCmp)` 渲染评级公式 + 该卡组内排名

**`_bindSigKellyWmPop`（L7506）扩展或新增 `_bindSigKellyCwmPop`**:
- 绑定 `[data-cwm="1"]` 的 hover/click/移动端关闭（复用现有 `_positionSigKellyWmPop` 定位逻辑）

### 7.2 lab.css 改动

新增 §6.4 列出的 `.lab-sigkelly-cwm*` 类（左上角定位 + 蓝/紫配色 + dark/redgold 覆盖 + 移动端）。

### 7.3 算法公示同步（§21）

卡间水印 hoverpop 必须含评级公式说明（综合分各项权重 + 稳定分各项权重 + 归一化方法 + 小样本排除规则），和现有卡内水印 hoverpop（`_sigKellyWmPopupHtml` 含三态定义）同模式。实施 agent 须 grep 确认无遗漏公示点。

### 7.4 费率客调同步

`_kellyOnFeeChange`（L7243）客调后重渲染（L7263-7264 / L7278-7279）已调用 `_renderSigKellyQuadrants`，卡间比较函数用 `feeStats` 自动同步，无需额外改动。

### 7.5 上线流程（§9）

`build_min.py` + `bump_asset_version.py` + **bump sw.js CACHE_VERSION**（三步缺一不可，§9 铁律）。min 版验证用字符串（`★综合最佳`/`lab-sigkelly-cwm-best`）非变量名（§9）。

### 7.6 回归（§15）

B 级大（逻辑，新增渲染+计算），派 reviewer agent: grep `lab-sigkelly-card`/`_renderSigKellyCard` 被谁引用 + 跑 P0 smoke + 确认现有卡内水印未受影响（不回退）+ 周期切换/费率客调后卡间水印更新。

---

## 8. 边界处理

| 场景 | 处理 |
|---|---|
| 组内卡数 < 2 | 不标（实际组内 3~5 张，不触发） |
| 组内某指标全同值(max==min) | 该指标所有卡 norm=0.5（中性），权重保留 |
| 整卡 6 模式全 n<30 | 标"样本不足"不参与排名（y1 rating_high n=44、mkt_hk n=48 均≥30，基本不触发） |
| pl_ratio=None | 按 0 计；pl_ratio=999(全胜) cap 5.0 |
| 负年化/负夏普 | min-max 归一化自动处理（负值卡 norm 低），无需特殊处理 |
| 一张卡综合+稳定都第一 | 左上角横向排列两个 badge |
| 费率客调后 | 用 feeStats 重算，自动同步 |
| 周期切换 | `_renderSigKellyQuadrants` 重渲染，自动更新 |

---

## 9. 待用户确认项

1. **Scope**: 选项 B（同组内比较，每组选 1 最佳 + 1 稳定，推荐）还是选项 A（全局 16 张选 1+1）？
2. **综合分权重**: 胜率 30% + 年化 30% + 夏普 20% + 盈亏比 20%（用户默认，采纳）？
3. **稳定分 std 替代**: 用 sharpe 替代 (1-收益波动率)（无 std 字段）？或用 calmar？
4. **卡级指标聚合**: 6 模式均值（默认）还是卡内最佳模式？
5. **每卡标记数**: 同时拿两个标记时横向排列两个 badge（默认）还是合并一个？

以上均有默认推荐，用户不否决即按默认实施。
