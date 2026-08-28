# 首页「模拟回测」按钮 + 弹窗 实施方案调研

> 调研角色：researcher（只读，不改代码）
> 调研日期：2026-08-21
> 测试基准：v1.1.2（2026-08-18 四档 excludeSpecialBear，git tag v1.1.2@4766bfe0c）
> 落档规范：§23.5（本文件为纯调研方案，无自跑脚本）

---

## 〇、先纠错：用户两个前提都不成立（关键）

需求背景里用户说了两个前提，实测数据证伪，必须先在方案里讲清，否则会带偏实施：

1. ❌「回测最细只到近1年」 → ✅ **错**。`signal_kelly_trades.json` 是 **2011-2026 全历史**：
   - 实测：27 万条交易，`signal_date` 范围 `20110119 ~ 20260820`，跨 1564 个交易日（`static-site/data/signal_kelly_trades.json` 实测：TOTAL trades: 270954 / min/max signal_date: 20110119 20260820 ndistinct= 1564）
   - 前端早已按 period_cutoffs 切片（y1/y3/y5/y10/all），全历史一直都在，不止近1年。

2. ❌「不符合条件的信号只是置灰没真剔除」 → ✅ **错（对用户想做的事反而是好消息）**。`signal_kelly_trades.json` 文件本身**不含任何 fade 预剔除标记**（实测 `fields 含 fade? []`），它就是全量原始交易记录（含 `sell_reason="持有中"` 的未结算笔）。前端 `passesFade` 是**实时逐笔过滤**的——这正是用户要的「真剔除干净」能力，且前端已有现成函数。

> 结论：用户想要的「用真实过滤后的全历史看会触发哪些信号、交易记录长啥样」，在数据层和过滤层**都已具备**，不需要重算，只需把现有能力搬到首页弹窗里。

---

## 一、任务1：首页「推荐方法参考说明」按钮位置

**证据点（app.js）：**
- 渲染函数：`_sigSwitchHtml(_fadeOn, _k, _pcOn, signalsMeta)`（app.js L2292）
- 该函数返回一整个 `.sig-switch-row` 容器，内含：
  - AI降亏过滤总开关（checkbox `sig-switch-ai-cb`）
  - AI仓位建议 K 档按钮组 + off 按钮 + 评级 pop
  - **参考说明按钮 `_helpBtn`**（app.js L2329-2339，data-k="help"，文字「推荐方法 / 参考说明」）
- `_helpBtn` 定义处（app.js L2330-2339）即在 `sig-switch-poscap` 这一 `span` 内，位于 `off` 按钮、`_ratingPop` 之后。

**插入点结论：**
- 在 `_helpBtn` 之后、同 `.sig-switch-row` 内（或在 `_sigSwitchHtml` 返回字符串末尾的 `</div>` 之前），追加一个「模拟回测」按钮 `<button data-k="sim">模拟回测</button>`（复用 `.sig-kbtn` 样式）。
- 点击委托绑定：在现有 `_bindSigSwitchRow`（app.js 负责 `.sig-switch-row` 事件委托的函数，参考 L2347 之后 `_bindSigHelpPop` 同款模式）里识别 `data-k="sim"` → 弹新弹窗。
- 弹窗「推荐操作方法·参考说明」本身已实现（`_openRefHelpModal`，app.js L2451），新弹窗复用同一套 `.rule-modal` 机制即可（项目既有弹窗基础设施，不用新造）。

---

## 二、任务2：原始信号源 / 全历史数据源

**首页当前信号源（仅近15日）：**
- 首页 `_renderSignalGrid` 用 `overview.json` 的 `signals_today` 数组（app.js L2072-2080 加载，L2527 渲染）。
- 实测 `overview.json`：`signals_today` 仅 **176 条**，日期范围 `20260803 ~ 20260821`（**仅近15日**）。字段含 `date/index_id/signal/reason/etfs/_bt_in_universe/ai_macro` 等，但**不含已算好的交易记录**（无 buy_price/sell_price/profit/hold_days）。

**全历史交易记录源（可用，已全历史）：**
- 文件：`static-site/data/signal_kelly_trades.json`（R2 已部署，实测 `https://ss.fx8.store/data/signal_kelly_trades.json` → HTTP 200，35MB；lab.js L8056 已从 R2 拉取）。
- 结构：平行数组格式（`fields` 数组 + `quadrants[qk][mode]` = 平行数组列表）。
  - `fields`（24 字段，顺序即值数组顺序）：`['signal_date','index_id','signal','buy_date','sell_date','etf_code','etf_name','track_tier','track_score','match_method','track_low_confidence','buy_price','sell_price','shares','profit','return_pct','hold_days','sell_reason','current_price','market_state','market_tier','market_tier_all','market_tier_cyb','rating']`（lab.js L8098 同源）
  - `quadrants`：key = 子域（rating_high/rating_mid/rating_low/etf_strong/... 共16个），value = `{ A:[...], B:[...], ..., I:[...] }`，每模式 **30106 笔**（9模式 × 16子域全量）。
- 每条记录已是「买入信号 → 按该模式持有 → 卖出」的完整落地交易（含 profit/return_pct/hold_days/sell_reason）。

**结论：**
- 首页模拟回测**不该用** `overview.json`（只近15日、无交易记录）。
- **应直接用 `signal_kelly_trades.json`**：全历史、含完整交易记录、前端实时可过滤。这正是「真实过滤后的全历史」的正确数据源。
- 数据源可用性：R2 已在线（HTTP 200），无需后端新接口。

---

## 三、任务3：首页同款过滤逻辑（可全部复用 lab.js 现有函数）

**3.1 AI降亏过滤**
- 首页判定谓词：`_isAiFadeHit(it)`（app.js L2659）：
  ```js
  return _fadeOn && it.ai_macro?.hit && Array.isArray(it.ai_macro.filters)
    && it.ai_macro.filters.some(fk => _aiOnMembers[fk]);
  ```
  依赖：`_fadeOn`（读 `tds_home_fade`，app.js L2605-2613）+ 固定8键 `_aiOnMembers`（app.js L2608-2611，遍历 `_AI_MACRO_FILTER_NAMES` 全置 true）。
- 但 `trades.json` 的记录**没有 `ai_macro` 字段**（它是回测产物，降亏判定走另一套谓词）。
- 凯利侧等价谓词：`_kellyPassesFadeFilters(t, fIdx, filters, ...)`（lab.js L7405-7490+），基于 `t[fIdx.signal]/[fIdx.market_tier]/[fIdx.market_state]/[fIdx.buy_date]` + 特征（`_kellyTradeFeatures`，lab.js L7240 `_kellyBuildTradeDims`）。
- **口径对齐结论**：首页默认降亏 = v1.1.2 固定8键（基础5+核心3），与 lab.js `_kellyDefaultFilters()` 默认 filters 一致。弹窗「AI降亏过滤开关」应**复用首页同款** `tds_home_fade` + `_aiOnMembers` 的8键判定（保证与首页行为 1:1 一致），过滤时走 `_kellyPassesFadeFilters`（它接受 `filters` 对象；需把首页8键翻译成 filters 对象，或直接传首页 `_aiOnMembers` 等效的 filters）。

**3.2 AI仓位建议 K 档过滤**
- 首页 kept 计算：`_posCapKeptMap`（app.js L2666-2726），排序 `_posCapSortedFn`（track_score DESC → 评级 → 信号类型 → buy_date ASC），按 date 取 top-K。
- 凯利侧等价（更通用，跨模式去重）：`_kellyPositionCapKeptKeys(pool, fIdx, K)`（lab.js L7577）+ `_kellyCollectBasePool`（lab.js L7615，跨 rating 三分区 × 全模式去重收集基笔）。排序口径与首页完全一致（track_score DESC → rating → signal → buy_date ASC，lab.js L7590-7620）。
- **结论**：弹窗 K 档过滤直接复用 `_kellyPositionCapKeptKeys` + `_kellyCollectBasePool`，零漂移。

**3.3 交易模式 A-I**
- 语义源：`signal_kelly_backtest.json` 的 `config.sell_modes`（lab.js L8085 读取，前端动态生成下拉；app.js L2329 文案 A=固定10天/F=持有15天/G=卖出信号）。
- 实测 sell_modes（from `signal_kelly_backtest.json`）：
  - A=固定10天 / B=3%止盈 / C=5%止盈 / D=7%止盈 / E=持有5天 / F=持有15天 / G=卖出信号 / H=卖出+追止损 / I=追关注加追止损
- 数据组织：trades.quadrants[qk][mode] 已按模式分好数组。选某模式 = 直接取该 mode 下全部子域数组。
- **结论**：模式切换 = 切 `quadrants[qk][selectedMode]`；A 模式 hold_days 已固化=10（实测 A 模式 hold_days 分布 `{10:29928, ...}`），无需实时重算。

**3.4 日期区间**
- trades 每条含 `signal_date`（买入信号日）和 `buy_date`。前端按字符串比较切片（`cutoff` 逻辑见 lab.js L10725 `t[_fIdx.buy_date] < cutoff` return false）即可筛任意起止日期。

---

## 四、任务4：交易记录表格的列结构

**全信号表「点A/G 弹出交易记录」的列定义来源：**
- 凯利区「全信号表（最后结果）」按年聚合表（`_sigKellyAllSignalGroupHtml`，lab.js L9957）列：年份/笔数/净盈亏/累计净盈亏/胜率/峰值资金收益率/峰值资金回撤（这是聚合表，非逐笔）。
- 逐笔交易弹窗的列，应直接取自 trades 的 `fields`（24 字段，已是逐笔明细）。

**建议弹窗逐笔表格列（按用户需求「按日期倒序，列出真实信号交易记录」）：**

| 列 | 字段（trades.fields） | 含义 |
|---|---|---|
| 信号日期 | signal_date | 买入信号触发日（倒序排序键） |
| 信号类型 | signal | buy/buy_aux/buy_special/buy_backup |
| 指数 | index_id | 触发信号的指数 |
| ETF | etf_code + etf_name | 成交标的 |
| 买入日 | buy_date | 实际买入日 |
| 卖出日 | sell_date | 实际卖出日（持有中=空） |
| 买入价 | buy_price | 成交买入价 |
| 卖出价 | sell_price | 成交卖出价 |
| 股数 | shares | 成交股数 |
| 收益率 | return_pct | 单笔收益率% |
| 净盈亏 | profit | 单笔净盈亏（元） |
| 持有天数 | hold_days | 持有天数（交易日） |
| 卖出原因 | sell_reason | 到期/卖出信号/止盈/追止损卖出/持有中 |
| 评级 | rating | high/mid/low |
| 跟踪分 | track_score | ETF 跟踪评分 |

**复用结论**：列定义直接映射 trades.fields（无新字段需求），渲染函数可新建 `_renderSimBacktestTable(rows)` 或直接复用 lab.js 既有的 trade 行渲染片段。

---

## 五、任务5：可行性结论与实施方案

### 5.1 四个可行性判断
1. ✅ **原始全历史信号能否拿到**：能。直接用 R2 已部署的 `signal_kelly_trades.json`（全历史 27万条，HTTP 200）。不用 overview（只近15日）。
2. ✅ **4 个过滤块能否用现有函数**：能。降亏=`_kellyPassesFadeFilters`（或首页 `_isAiFadeHit` 口径）；K档=`_kellyPositionCapKeptKeys`+`_kellyCollectBasePool`；模式=trades.quadrants[qk][mode] 直取；日期=按 signal_date/buy_date 切片。全部前端实时算，真剔除。
3. ✅ **表格能否复用现有列定义**：能。直接映射 trades.fields（24字段），无需新算。
4. ⚠️ **纯前端 or 需后端**：**纯前端可行**（数据已在线），但首页 app.js 当前**未加载** 64MB/35MB 的 trades 文件，需新增加载逻辑。

### 5.2 阻塞点 / 待决
- **B1（主要）**：首页 app.js 未加载 `signal_kelly_trades.json`（64MB 源 / R2 35MB）。需新增：弹窗首次打开时 `fetchJSON(R2 url + ?v=)` 加载 + 解析平行数组 + 构建 `fIdx` + 缓存（一次加载，后续复用）。35MB 首加载约数秒，需 loading 态 + 缓存到内存（不必每次开弹窗都拉）。
- **B2**：首页 app.js 没有 `_kellyPassesFadeFilters` / `_kellyPositionCapKeptKeys` / `_kellyCollectBasePool` 这几个函数（都在 lab.js）。方案二选一：
  - (a) 把这几个函数 + `_kellyBuildTradeDims` + `_kellyBaseKey` 抽进共享层 `common.js`（clean，但动共享文件需 review 影响面）；
  - (b) 在首页 app.js 内复制一份轻量版（只依赖 fIdx + filters，不依赖 lab.js 全局态）。
  - 推荐 (a)，与 §21/§22 单一数据源精神一致，避免双份维护分叉。
- **B3（口径对齐，重要）**：首页「AI降亏过滤」判定 = `_isAiFadeHit`（依赖 `ai_macro` 字段，overview 信号才有）；而 trades 记录无 `ai_macro`，降亏判定走 `_kellyPassesFadeFilters`（依赖 signal/market_tier/buy_date 等）。两套**判定结果在默认8键下等价**（首页8键 ⊂ 凯利 filters 默认集），但实现路径不同。弹窗里必须**用 trades 侧的 `_kellyPassesFadeFilters`**（因为数据源是 trades），并把首页开关 `tds_home_fade` + 固定8键翻译成等价 filters 传入。需实施时核对：首页8键白名单 `_AI_MACRO_FILTER_NAMES` 与 `_kellyDefaultFilters` 默认集的键名映射是否 1:1（预测是，但实施须 grep 双向核对，防漏键）。
- **B4（性能/体积）**：打开弹窗才加载 35MB，且只加载一次缓存。表格渲染用虚拟滚动或分页（27万条按日期倒序，不能一次性 innerHTML 全渲染，否则卡死）。建议：默认只渲染筛选后前 N 条（如 500 条）+ 滚动加载更多 / 分页。

### 5.3 具体实施方案（改哪些文件 / 加什么）

**改动文件清单：**
1. `static-site/app.js`（首页，主要改动）
   - L2330-2339（`_helpBtn` 定义处）：在其后追加「模拟回测」按钮 `data-k="sim"`。
   - 新增事件绑定（在 `_bindSigSwitchRow` 或同委托处）：识别 `data-k="sim"` → 调 `_openSimBacktestModal()`。
   - 新增函数 `_openSimBacktestModal()`：复用 `.rule-modal` 机制（`_openRefHelpModal` 同款，app.js L2451），弹窗内 4 个操作块 + 结果区。
   - 新增函数 `_loadSimKellyData()`：首次 `fetchJSON('https://ss.fx8.store/data/signal_kelly_trades.json?v=' + v)`（参考 lab.js L8056 的 R2 url 取法），解析 `fields`→`fIdx`，缓存到模块级变量（避免重复拉）。同步加载 `signal_kelly_backtest.json` 取 `config.sell_modes`（模式下拉 + 标签，参考 lab.js L8085）。
   - 新增函数 `_renderSimBacktestTable(rows)`：按 §四 列定义渲染（映射 trades.fields），分页/虚拟滚动。
   - 新增或引用过滤函数：`_simPassesFade`（复用 `_kellyPassesFadeFilters`，来自 common.js 抽取版）/`_simPosCapKept`（复用 `_kellyPositionCapKeptKeys`）。
2. `static-site/common.js`（仅若选方案 a）
   - 从 lab.js 抽出 `_kellyPassesFadeFilters` / `_kellyPositionCapKeptKeys` / `_kellyCollectBasePool` / `_kellyBuildTradeDims` / `_kellyBaseKey` 到 common.js，lab.js 改为从 common 引用（保持 lab.js 行为不变）。
   - 本功能不改动算法，仅新增展示，无需改 purpose-notes 算法公示（但弹窗内操作块文案需与首页/凯利区术语一致，属 §22 一致性，非 §21 算法改动）。

**弹窗内 4 个操作块设计：**
- 块1 时间范围：两个 `<input type="date">`（起/止），绑定 `onchange` 重算过滤。
- 块2 AI降亏过滤：checkbox，读 `tds_home_fade` + 固定8键（与首页同款），勾选=剔除命中降亏笔。
- 块3 AI仓位建议 K：按钮组 关/1/2/3/4（与首页 `_kbtns` 同款，L2318-2324），影响 kept 集。
- 块4 交易模式 A-I：下拉单选，选项来自 `config.sell_modes`（lab.js L8655 动态生成方式可参考），默认 A。切模式=切 `quadrants[qk][mode]`。
- 结果区：筛选后按 `signal_date` 倒序的逐笔表格（§四 列），分页渲染。

**数据流程（点击「查询」或任一操作块变更时）：**
```
trades(全历史)
  → 按模式 selectedMode 取 quadrants[*][mode] 所有子域数组 concat
  → passesFade 过滤（降亏开关 on 时）
  → positionCapKept 过滤（K 档 on 时，基于 _kellyCollectBasePool 去重基笔）
  → 按 signal_date ∈ [起,止] 切片
  → 按 signal_date 倒序
  → 分页渲染前 N 条
```

### 5.4 实施建议（给主控定夺）
- **是否派 implementer**：是。纯前端改动，但涉及大文件（app.js 1.7MB）+ 可能动 common.js 共享层 + 数据加载性能，需派 implementer，并配 reviewer 查影响面（common.js 抽取是否影响 lab.js 既有行为，§15 回归）。
- **预计难度**：中。过滤逻辑已有现成函数可复用（降难度），难点在 ① 35MB 大文件前端加载 + 缓存 ② 表格分页/虚拟滚动 ③ 首页8键 ↔ 凯利 filters 口径对齐（B3）。
- **预估工时**：1.5~2.5 天（含自测：加载性能、分页、4 块联动、与凯利区数据一致性核对 §22）。
- **版本/冻结**：本功能为**纯新增展示**，不改任何已发布功能行为/布局/口径（符合 §23.7 默认只增不改）。不涉及 AI 推荐/降亏过滤核心算法改动，**不触发发版本号**（§5.4⑥：纯新增不影响默认行为可不动基准）。但需走 §24 前端 bump + 上线三查（main commit / 数据层 / 前端展示层）。

---

---

## 八、最终确认规格（用户拍板 2026-08-21）

> 本节为需求最终锁定版，派 implementer 以本节为准。前七节为调研证据。

### 8.1 弹窗 5 个操作块
| 块 | 控件 | 默认值 |
|---|---|---|
| ① 时间范围 | 起日期 + 止日期（两个 `<input type="date">`，任意选） | 空（不筛=全历史） |
| ② AI降亏过滤 | checkbox（同首页 `_isAiFadeHit` 语义，复用 `tds_home_fade`+固定8键） | 开 |
| ③ AI仓位建议 | K档按钮组（关/K1/K2/K3/K4，同首页 `_kbtns`） | K1 |
| ④ 交易模式 | 下拉单选 A-I（默认 A，来自 `config.sell_modes`） | A |
| ⑤ 费率设置 | 买入费率 + 卖出费率（两个数字输入框，百分比） | 各 0.03%（万3） |

### 8.2 结果表（11 列，按 signal_date 倒序渲染，累积列从最早逐笔累加）
| 列 | 字段 | 口径 | 来源 |
|---|---|---|---|
| 1 | 信号（AI建议N） | 4块过滤后保留的信号（同首页 AI建议 口径） | 过滤后 kept 集按 date 取 top-N 序号 |
| 2 | 关联跟踪ETF | 该笔 etf_code + etf_name（trades 已固化） | trades.etf_code/etf_name |
| 3 | 买入时间 | 信号日固化 → 次日开盘 | trades.buy_date（回测已按次日开盘算，核实即可） |
| 4 | 卖出时间 | 按 A-I 模式各自卖出规则离场 | trades.sell_date |
| 5 | 买入手续费¥ | 买入额 × 买入费率（买入额=¥10000×买入价/基准价，按份额折算） | 实时算 |
| 6 | 卖出手续费¥ | 卖出额 × 卖出费率 | 实时算 |
| 7 | 本笔盈亏%（费后） | (卖出额−买入额−两笔手续费) / 买入额 ×100 | 实时算（**不用 trades.return_pct**，因其未扣费） |
| 8 | 本笔盈亏¥（费后） | 每笔本金¥10000 口径下的净绝对额 | 实时算 |
| 9 | 累积收益%（费后） | 从最早日起逐笔累加 | 实时算 |
| 10 | 累积盈亏¥（费后） | 从最早日起逐笔累加 | 实时算 |
| 11 | 累积对错 / 准确率 | 逐行累加「N对/M错」+ 准确率% | 实时算（显示倒序，但累加方向从最早→当前行） |

### 8.3 关键口径说明
- **本金**：每笔固定 ¥10000（用户拍板"方便就按1万算"，与首页每笔1万口径一致）。
- **手续费**：trades.json 的 return_pct/profit **不含手续费**，弹窗必须按块⑤费率实时重算费后盈亏（不能直读 trades.return_pct）。
- **累积方向**：表格渲染倒序（最新在上），但第 9/10/11 列每行的累积值 = 从开始日（最早）累加到该行日期。实现：先按日期正序算累积，再倒序渲染。
- **卖出时间**：直接用 trades.sell_date（按所选 A-I 模式已固化），无需实时反推。
- **B3 口径对齐**：降亏过滤必须用 trades 侧 `_kellyPassesFadeFilters`，把首页8键翻译成等价 filters 传入；实施时 grep 双向核对键名 1:1。

### 8.4 实施清单（锁定）
1. app.js L2330-2339 后追加「模拟回测」按钮 `data-k="sim"`
2. 新增 `_openSimBacktestModal()`：复用 `.rule-modal`，5 块 + 结果区
3. 新增 `_loadSimKellyData()`：首次开弹窗 fetchJSON R2 trades + backtest config，缓存
4. 新增 `_renderSimBacktestTable(rows)`：11 列 + 分页（前 500 条）
5. common.js 抽 `_kellyPassesFadeFilters` / `_kellyPositionCapKeptKeys` / `_kellyCollectBasePool`（方案 a，配 reviewer 查 lab.js 回归 §15）
6. 费率块 + 费后重算逻辑
7. 纯新增展示，不触发发版本号，走 §24 bump + 上线三查



- 数据源：
  - `static-site/data/overview.json`（实测：signals_today 176条，仅近15日 20260803~20260821）
  - `static-site/data/signal_kelly_trades.json`（实测：270954 条，2011~2026 全历史，fields 24，quadrants[qk][mode] 每模式 30106 笔）
  - `static-site/data/signal_kelly_backtest.json`（实测：config.sell_modes 含 A-I 九模式标签）
  - R2：`https://ss.fx8.store/data/signal_kelly_trades.json`（HTTP 200，35MB，lab.js L8056 已在线拉取）
- 代码锚点：
  - 按钮位置：`static-site/app.js` L2292 `_sigSwitchHtml`、L2329-2339 `_helpBtn`、L2451 `_openRefHelpModal`、L2659 `_isAiFadeHit`
  - 过滤函数：`static-site/lab.js` L7405 `_kellyPassesFadeFilters`、L7577 `_kellyPositionCapKeptKeys`、L7615 `_kellyCollectBasePool`、L7240 `_kellyBuildTradeDims`、L8085/L8655 sell_modes 读取、L8056 R2 url
  - 首页开关：`static-site/app.js` L2605-2613 `_fadeOn`/`_aiOnMembers`、L2666-2726 `_posCapKeptMap`/`_posCapSortedFn`

---

## 七、复现（核对用）

- 全历史信号条数/日期范围：
  ```bash
  cd static-site/data && python3 -c "
  import json
  d=json.load(open('signal_kelly_trades.json'))
  fields=d['fields']
  dates=set(); total=0
  for qk,qv in d['quadrants'].items():
      for mk,mv in qv.items():
          for rec in mv: dates.add(rec[0]); total+=1
  print('TOTAL', total, 'min/max', min(dates), max(dates), 'ndistinct', len(dates))
  "
  # 输出: TOTAL 270954 min/max 20110119 20260820 ndistinct 1564
  ```
- R2 可用性：
  ```bash
  curl -s -o /dev/null -w "%{http_code}\n" "https://ss.fx8.store/data/signal_kelly_trades.json"
  # 输出: 200
  ```
- overview 仅近15日：
  ```bash
  cd static-site/data && python3 -c "
  import json
  st=json.load(open('overview.json'))['signals_today']
  print('count', len(st), 'range', min(x['date'] for x in st), max(x['date'] for x in st))
  "
  # 输出: count 176 range 20260803 20260821
  ```
