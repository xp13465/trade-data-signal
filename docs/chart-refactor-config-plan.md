# 走势图组件统一改造 + 站点配置化 方案（2026-08-11 调研，待用户确认）

> 调研 agent 产出（只读调研 + 本方案文档落档）。用户 2026-08-11 想法归纳：
> 1. 走势图组件统一改造（TASKS L1198-1213 需求1/2/3）改为 canvas 轻量版
> 2. 保留当前模式兜底：改造后留"轻量切换"按钮，默认轻量，可切回现有版（防 bug 兜底 / 改配置默认即可切换）
> 3. 统一配置化：站点"默认策略/开关策略"收进配置文件，直接改配置切默认，不每次让 Claude 改代码
>
> 参考模式：AI 预测 gen_daily_brief.py 的 config/daily_brief.yaml（schedule_enabled/compliance_enabled 配置驱动）

---

## 0. 核心结论速览（TL;DR）

- **走势图现状**：全站约 20+ 处图表渲染点，**首页 11 个指数 sparkline + 27 个 KPI 卡 sparkline 用 echarts（line+area），首屏 12 个 echarts.init 串行卡顿 200-500ms**（NOTES L7164-7166 已落档的性能瓶颈 P0-3）。汪汪队份额折线（SVG）与 ETF 评分行迷你折线（SVG）已是轻量先例。**canvas 轻量版最大收益就在这两处 sparkline**
- **需求1 已完成**：ETF 评分弹窗近30日走势（2026-08-06 echarts 版，app.js L16885-16928）
- **需求2 数据已存在**：指数"30天外历史"已在信号弹窗 openSignalChartModal 实现（period 3m/6m/1y/3y/5y/all + R2 `index/{iid}-all.json`）；缺的是 **ETF 弹窗**的长周期 + ETF 自身历史数据产物
- **需求3 未做**：场外基金无走势；净值序列 DB 已有（fund_daily_nav），但无前端数据产物（fund_score_top.json 只 Top100 列表 34 字段无净值序列）
- **网络受限环境 → 自绘 canvas 2D**（不用 uPlot/lightweight-charts 外部库，仓库只有 vendor/echarts.min.js 1MB，drawShareCard L19961 已证明 canvas 自绘 + 主题色 getComputedStyle 可行）
- **配置化最佳挂点 = boot.json**：fetchBoot 已首屏合并 11 个 JSON（P1-8），新增 `config` key 零额外请求；后端 config/site.yaml → export.py 写入
- **双实现切换按钮**：挂在 "仅日图/仅分时/全展开" 分段控件（renderIntradaySection L6984-7065）旁，优先级 = 配置默认 > 用户 localStorage > 代码内置默认

---

## 1. 走势图改造待办详情（TASKS L1198-1222 需求1/2/3 现状核对）

| 需求 | 状态 | 现状核对（2026-08-11 grep/读代码） |
|---|---|---|
| 需求1：场内 ETF 弹窗补近30天走势 | ✅ 已上线 | `openEtfScoreDetailModal`（app.js L16731）弹窗 L16885-16928，复用卡片 sparkline 数据源 `e.ohlc`（etf_score_list.json 近30交易日 OHLC）放大到弹窗 echarts line+areaStyle，涨红跌绿跟主题。TASKS L1199-1203 待调研项（弹窗是哪个/数据源/卡片实现）均已落地 |
| 需求2：场内 ETF 弹窗看30天外历史 | ❌ 未做 | 指数侧**已实现**：信号弹窗 `openSignalChartModal`（L4617）period tab 3m/6m/1y/3y/5y/all，数据 `fetchJSON("https://ss.fx8.store/r2/index/{iid}-all.json")`（R2 单文件 ~158KB）；KPI 历史弹窗 `openKpiDetailModal`（L4875）同 pattern 按 period 分片拉 sentiment-/a-stock-{period}.json。**ETF 侧缺**：etf_score_list.json 只近30日 ohlc，ETF 长历史需新数据产物（fund_etf_hist_sina / 腾讯日K / akshare，需调研数据源上限） |
| 需求3：场外基金卡片近30天走势+弹窗历史+指标介绍 | ❌ 未做 | 场外基金 tab 有评分排行（`renderOffshoreFund` L17482，fund_score_top.json Top100 83KB 34字段），**无任何走势图**。净值历史 DB 已有（public_fund.db fund_daily_nav 表，collector/public_fund.py L274 nav_change_pct / L546 nav_history），但**前端无净值序列数据产物**。指标介绍依赖 fund_basic 字段补齐（TASKS L1213-1214，pf-fund-screener-real-requirements 关联） |
| 统一改造（用户 2026-08-11 想法1） | 📋 本方案 | 无历史专项调研（git log/NOTES 无"走势图统一改造"专项），仅有性能瓶颈落档（NOTES L7164-7166）+ 需求1/2/3 排期建议（TASKS L1216-1218："可能合并到走势图组件统一改造批次"） |

**为什么"统一改造"**：全站走势图 20+ 处散落，同一类图（30天日K走势 / mini sparkline）用三种实现（echarts / 自绘 SVG / 自绘 canvas）重复写；首页 sparkline 是最重 echarts 实例聚集地（性能瓶颈）；需求1/2/3 都落在"走势图组件"上，一次统一组件化可同时解决 3 需求 + 性能 + 一致性（§22）。

---

## 2. 全站走势图实现盘点（static-site/app.js + lab.js）

> 行号以 2026-08-11 02:1x app.js（21473 行）为准。⚠️ **app.js 正在被并发修改**（git status `M static-site/app.js`，本次调研期间行号漂移 ~180 行），实施前须重新 grep 定位。

### 2.1 图表渲染点清单

| # | 组件/函数 | 位置 | 渲染方式 | 数据源 | 数据量级 | 交互 |
|---|---|---|---|---|---|---|
| 1 | **首页指数 sparkline 网格**（renderOverview `.spark-cell`） | L9631-9665 + `ntIndexSparkline` L10408 + `_flushNtSpark` L10416 | **echarts** line+areaStyle+tooltip（方案A 2026-08-05 改，11 实例） | overview.json `indices_sparkline`（{id}_6m 同源） | 11 个 × ~30-240 点 | hover tooltip（日期+收盘+涨跌%）、盘中1min分时叠加 |
| 2 | **KPI 卡 sparkline**（`_kpiSparkHtml`） | L9271-9289 | **echarts**（复用 ntIndexSparkline） | overview.json `${id}_6m`（27 卡，零额外请求） | 27 个 × 140-210 点 | hover tooltip |
| 3 | **分时图**（`_renderIntradayChart`） | L6881-6967 + 主入口 L6984-7065 | **echarts** line+areaStyle+markLine昨收+markArea午休 | 腾讯分时 API 直拉（web.ifzq.gtimg.cn，CORS*） | 240 点/日 | hover tooltip（时间/价格/涨跌）、1min 动态刷新（S1-S5 自愈）、3 态显隐 |
| 4 | **ETF评分弹窗 近30日走势**（需求1） | L16885-16928 | **echarts** line+areaStyle | etf_score_list.json `e.ohlc`（近30日） | 30 点 | hover tooltip、resize |
| 5 | **ETF评分行迷你折线**（`_etfSparkline`） | L16536-16555（渲染点 L17025） | **SVG** polyline+circle（已轻量先例） | 同上 e.ohlc | 30 点 | 无（卡片标题 tooltip） |
| 6 | **汪汪队份额折线**（`ntSparkline` 汪汪队版） | L10385 注释 + L10400 | **SVG** currentColor 跟主题（已轻量先例） | overview.json 汪汪队份额 | ~30-60 点 | 无 |
| 7 | **信号弹窗走势图**（`openSignalChartModal` → `indexChart`/`valueChartWithSignals`） | L4617-4790 + indexChart L3500 / valueChart L3573 | **echarts** line + markPoint pin（拼色）+ dataZoom + T日预估点 | R2 `index/{iid}-all.json`（g./s. 走 sentiment-all/global-extras-all） | ~3-10年日线（~700-2500 点） | **period tab（3m/6m/1y/3y/5y/all）+ pin 悬停 + dataZoom 缩放 + 信号至今盈亏行** |
| 8 | **KPI 历史弹窗**（`openKpiDetailModal`） | L4836-4950 | **echarts** line+预估点+visualMap | sentiment-/a-stock-{period}.json、volume_ratio、global-extras-all | period 分片 ~60-2500 点 | period tab、T日预估点 |
| 9 | **行业 spark-cell 网格**（`renderIndustryGrid`） | L15826-15960 | **echarts** mini line + markPoint 买卖点 + 资金流/成交额/换手率 mini sparklines（L15958-16020） | industry.json（31 行业 ohlc+signals+heatmap） | 31-100 × ~500-1500 点 | 买卖点 pin、hover、视口懒加载 detail、B2 预取 |
| 10 | **板块分化 A股/港股/全球指数卡**（`renderAStock` L11424 / `renderHK` / `renderGlobal` L11661） | L11424+ | mkCard/lineChart（echarts）复用 | a-stock-{period}.json / hk-5y.json / global-extras-all.json | ~1000+ 点 | 买卖点 pin、period 切换 |
| 11 | **行业涨跌幅热力图**（`renderIndustryHeatmap`） | L15381-15400 | **echarts heatmap**（treemap/热力网格复杂组件） | industry.json heatmap pct_1d/pct_5d | 31×2 | 近1日/近5日/全部切换 |
| 12 | **指数情绪冰点/过热热力图** | L14626-14700 | **echarts heatmap** | sentiment 历史 | 6宽基×全历史 | 日期/标签采样 |
| 13 | **行业配置 treemap**（基金详情） | L13250 | **echarts treemap**（完整版 echarts 才含） | fund 持仓 | — | — |
| 14 | **恐贪/A股情绪分 lineChart** | L319（通用）+ L9632 注释 | echarts line | sentiment-{period}.json | period 分片 | hover |
| 15 | **期货机构持仓净多空折线** | L15360 | echarts 多序列 line + markLine 0 轴 | futures 持仓数据 | ~3-5 年 | hover |
| 16 | **策略实验室信号图**（lab.js） | lab.js L4996-5205 | echarts（91候选双图/6硬编码单图）line+K线参考 | lab index ohlc + 策略指标/signals | ~700-2500 点 | 买卖点、窗口切换、策略A/B分图 |
| 17 | **trade_sim 弹窗净值/曲线** | L19763+（`_tradeSimModalRender`） | echarts/HTML 表格混合 | trade_sim JSON（前端 replay 重算） | — | 视图/窗口/场景切换、费率客调 |
| 18 | **分享图品牌卡片**（`drawShareCard`） | L19961-20060 | **canvas 2D 自绘**（已 canvas 先例，含上证迷你走势 + getComputedStyle 主题色） | boot/overview 当日快照 | 迷你走势 ~30 点 | 无（导出 PNG） |

### 2.2 canvas 化分级评估

**适合 canvas 化（A 类，自绘 canvas/SVG 能功能等价）**：
- #1 首页指数 sparkline 网格、#2 KPI 卡 sparkline —— **最大收益点**（消灭 11+27 个 echarts.init，首屏 -200-500ms）；交互仅 hover tooltip，自绘 canvas 命中检测 + 浮层即可等价
- #4 ETF评分弹窗近30日 —— 30 点单线，canvas 秒画；tooltip 同 #1
- #5 ETF评分行迷你折线 / #6 汪汪队 —— 已 SVG，统一进组件（保持 SVG/canvas 二选一可配）

**中等（B 类，可 canvas 化但交互较复杂）**：
- #3 分时图 —— 240 点 + 昨收基准线 + 午休标注 + hover；canvas 可做，但 1min 轮询重绘 + 3 态显隐 + S1-S5 自愈逻辑需完整迁移，**风险中，建议二期或保留 echarts**
- #9 行业 spark-cell —— 31-100 卡 markPoint 买卖点 pin + 资金流子图；canvas 化工作量大（pin 命中/悬停），建议保留 echarts，仅把"纯缩略趋势"子图可配轻量

**不适合 canvas 化（C 类，保留 echarts）**：
- #7 信号弹窗走势图 / #8 KPI历史弹窗 —— period 切换 + dataZoom 缩放 + 拼色 pin + T日预估点 + 信号对错标注，交互密度高，echarts 成熟；canvas 重写功能等价成本高
- #11/#12 heatmap、#13 treemap —— 网格/矩形树组件自绘成本高且无收益
- #16 lab 信号图 —— 双图 + 多策略指标叠加，复杂
- #10 板块/港股/全球、#14、#15 —— mkCard/lineChart 已统一封装，改 canvas 收益低

**结论**：canvas 轻量版首期只覆盖 **A 类 4 处（#1/#2/#4/#5/#6）**（即"缩略/近30日趋势"类），B/C 类保留 echarts。这正好覆盖用户 3 需求的最小共通集（卡片 sparkline + 弹窗近30日走势），且直击首屏性能瓶颈。

---

## 3. 站点开关/配置盘点（现状）

### 3.1 后端配置（yaml 驱动，用户可直接改文件）
- **config/daily_brief.yaml**（AI 预测，2026-08-10 建的"配置驱动"先例）：`schedule_enabled`（调度开关，默认 false）/ `compliance_enabled`（合规开关，默认 true）/ model / timeout / disclaimer / cost_log 等，由 `scripts/gen_daily_brief.py` 读。**这就是用户说"参考 AI 预测已留的配置文件模式"**
- **config/indicators.yaml**（指标注册表）：metrics 清单 + enabled / transform / direction，fetchers.py 按此调 akshare。加减指标只改此文件
- 其他：无统一站点级配置文件；各类开关散在代码常量/launchd plist

### 3.2 前端 localStorage 开关（用户可选、跨会话记忆）
| key | 含义 | 默认 | 位置 |
|---|---|---|---|
| `compliance_mode` | 精简版/完整版（i18n 双字典 on/off） | on（精简） | i18n.js + index.html L55 head 同步读防闪烁 |
| `intraday-chart-mode` | 仅日图/仅分时/全展开（3 态，**这就是用户想法2说的布局**） | 时段自动（盘中仅分时/盘后全展开/其他仅日图） | renderIntradaySection L6994-7011 |
| `theme`（data-theme） | 皮肤（redgold 默认红金中国） | redgold | applyTheme |
| `kpiCustomOrder` | KPI 卡自定义排序 | A+B 默认 | L9006-9572 |
| `etf_dedup` / `etf_side_filter` / `etf_sort` / `etf_buy_expanded` | ETF 评分筛选偏好 | 各默认 | L17290-17422 |
| `fund_score_sort` | 场外基金排序 | score desc | L17739 |
| `pinned_indices` / `etf_holdings` / `sub_user_info` 等 | 用户数据 | — | — |

### 3.3 前端代码常量开关（改代码才能切，配置化目标对象）
- `fetchJSON` 的 `tryGz = false`（L3693，2026-08-01 全跳 .gz 根治 CF 缓存滞后）
- 轮询间隔：`INTRADAY_FETCH_TIMEOUT_MS = 8000`（L6366）/ `INTRADAY_REFRESH_MS`（1min）/ `NOTIFY_FETCH_INTERVAL_MS`（30s）/ `_CACHE_TTL`（fetchJSON 5min）
- 三态分段控件默认逻辑（renderIntradaySection L7000-7012 内置时段判断）
- 降亏 toggle（29 个，kelly 策略开关，hoverpop 显示）—— 这是"开关策略"，但属策略实验参数集，是否入配置化需用户定（建议留独立，不并站点配置）
- `_R2_LARGE_RANGE_RE` / `_R2_DATA_BASE` / `_R2_FALLBACK_BASE`（数据路由常量）

### 3.4 可复用的"配置驱动"模式
1. **AI 预测模式（后端 yaml → 脚本读）**：config/*.yaml + 生成脚本读 → 适合**后端**默认策略
2. **boot.json 合并模式（P1-8）**：首屏单 fetch 合并 11 JSON → 适合**前端默认策略下发**（新增 config key 零额外请求）
3. **compliance_mode 模式（localStorage 双字典）**：head 同步读 + 用户选择覆盖 → 适合**前端 UI 开关 + 用户记忆**
4. **intraday-chart-mode 模式（localStorage 覆盖默认）**：无记忆走默认、有记忆用户优先 → 正是"配置默认 > 用户选择"的现成实现

---

## 4. 方案：统一配置架构 + canvas 轻量走势图组件 + 双实现切换

### 4.1 统一配置架构（站点级"默认策略/开关策略"）

**设计**（三层，最小侵入）：
```
config/site.yaml          ← 用户直接改的配置文件（单一事实源，注释说明每项作用）
   └─ export.py 读（或新增 gen_site_config.py）→ 写入 boot.json 新增 "config" key（或独立 static-site/data/site-config.json）
        └─ 前端 _siteConfig 单例：代码内置默认 < 远程配置默认 < localStorage 用户选择
```

- **配置源**：`config/site.yaml`（对齐 config/daily_brief.yaml 风格，中文注释说明每项）。后端 `export.py` 末尾把 site.yaml 的"前端可见"子集写入 `boot.json.config`（boot.json 已有 `_meta` 合并机制，加一个 key 即零额外请求、首屏即达；如担心 boot.json 改动面，可独立 `site-config.json` 走 R2/CF，多 1 请求）
- **前端读取**：新增 `_siteConfig` 单例（app.js/i18n.js 级），`fetchBoot` 后从 boot.config 合并；未 fetch 到用代码内置默认兜底
- **通用读取 API**（最小侵入）：`siteCfg(key, codeDefault)`，形如 `siteCfg('charts.lightweight', true)`。**首批只接 2 个消费者**（走势图轻量开关 + intraday 默认态），后续存量开关（tryGz/轮询间隔/三态默认）按需逐个迁移，**不一次性改遍所有开关**（避免大 diff 回归）
- **优先级**：`localStorage 用户选择 > 远程配置默认 > 代码内置默认`（复用 intraday-chart-mode L6994 逻辑）
- **改动默认值 = 改 site.yaml → 跑 export.py + deploy.sh 推数据**（§8：static-site/data/ 是正常上线渠道）；用户不用再让 Claude 改代码
- **配套**：site.yaml 变更 → boot.json regenerated → §22 一致性（boot.json 是首屏合并源，改一处全站生效）；R2/CF 缓存靠现有 deploy purge

### 4.2 canvas 轻量走势图组件（架构）

**选型：自绘 canvas 2D**（不用 uPlot / lightweight-charts）：
- 仓库无这两个库；网络受限环境（CF Workers 静态托管）vendoring 外库有下载风险（uPlot ~40KB 可考虑 vendor，但 lightweight-charts 偏 K线/蜡烛图场景，本项目走势图 90% 是 line，自绘足够）
- **自绘先例已在库内**：`drawShareCard`（L19961）已用 canvas 2D + getComputedStyle 读主题色 + 迷你走势；`withTheme`/`rethemeCharts`（L219）已解决"canvas 不响应 CSS var，切皮肤重注入"——canvas 组件直接复用这两套机制
- **组件 API**（新文件 `static-site/chart-lite.js` 或 app.js 内模块）：
  ```
  chartLite.line({
    container, closes, dates,           // 数据
    color,                             // 涨跌色（红涨绿跌，跟主题）
    height, tooltip: (i) => html,      // hover 浮层（日期+收盘+涨跌%）
    areaStyle, baseline,               // 面积/昨收基准线（分时图复用）
    marks                            // pin 标注点（可选，二期）
  })
  ```
  - 实现：devicePixelRatio 缩放防模糊、resize 观察器、hover 命中检测（最近 x 索引）、tooltip 复用现有 `.chart-tooltip`/term-pop 样式、空数据/单点防御
  - 主题：init 时 getComputedStyle 读 `--mx-good-fg/--mx-bad-fg/--text-1/--border-strong`，`rethemeCharts` 挂钩重绘（同 withTheme 机制）
- **首期覆盖**：#1 首页指数 sparkline 网格 + #2 KPI 卡 sparkline + #4 ETF弹窗近30日 + #5/#6 已 SVG 的统一进组件（SVG/canvas 由配置 `charts.renderer` 二选一）
- **保留 echarts**：#7/#8 弹窗走势（period+zoom+pin）、#11/#12 heatmap、#13 treemap、#16 lab、#10 板块/港股/全球、#3 分时图（二期评估）、#9 行业网格（二期评估）

### 4.3 双实现切换机制（用户想法2）

- **切换按钮位置**：挂在首页"仅日图/仅分时/全展开"分段控件（`renderIntradaySection` L7014-7026 `intraday-seg-group`）**同行末尾**，加一个独立小按钮「⚡ 轻量」/「📈 完整」（当前轻量态高亮）。同一 seg-group 容器、独立 class，不污染三态逻辑
- **行为**：点击 → 切换 `_siteConfig` 的 `charts.lightweight` 用户覆盖 → re-render 首页走势图区（走 chartLite 或 echarts 路径）→ localStorage 记住（key `chart-lightweight`）→ 切回即回现有 echarts 版
- **默认走轻量**：`site.yaml` `charts.lightweight: true` 下发 → 首屏即轻量（性能收益直接生效）；**配置默认改 false = 全站回 echarts**（用户兜底，不依赖代码）
- **防 bug 兜底**：切换即回现有版，用户可自救；配置默认是"程序级切回"路径；两者都不需要改代码
- **实现要点**：走势图渲染统一走"渲染器分发"——`_chartRenderer(cfg)` 返回 chartLite 或 echarts 适配层，两实现共享同一数据准备函数（closes/dates/tooltip formatter），保证 **§22 一致性（同样数据、同样 tooltip 语义、两种渲染）**

### 4.4 功能等价性清单（canvas vs echarts，验收口径）

| 功能 | echarts 现有 | chartLite（canvas）等价要求 |
|---|---|---|
| hover tooltip | trigger:axis，日期+收盘+涨跌% | 最近点命中 + 同 HTML 浮层（复用 formatter 文案） |
| 涨跌色 | withTheme 注入 | getComputedStyle 读同变量 |
| 面积/昨收线/午休 | areaStyle/markLine/markArea | 二期内分时图用（首期 sparkline 无） |
| 空/单点/连接断点 | connectNulls | 空数据防御 + 单点占位 |
| resize（display:none→visible） | _flushNtSpark + echarts.resize | ResizeObserver + 三态显隐时重绘 |
| 皮肤切换 | rethemeCharts 重注入 | 挂 retheme 钩子重绘 |
| tooltip 在 pin/信号日 | indexChart 拼色 pin | 首期 sparkline 无 pin（二期评估） |
| 数据一致性 | — | 两实现读同一数据准备函数（§22） |

### 4.5 需求2/3 落地路径（挂到本方案的后续阶段）
- **需求2（ETF 30天外历史）**：① 数据源调研（fund_etf_hist_sina / 腾讯日K / akshare 历史上限，TASKS L1208 待调研①）② 后端新增 ETF 历史数据产物（如 `etf/{code}-all.json` 或合并文件，走 R2 大 range 架构 §8.1）③ 前端 ETF 弹窗加 period tab（复用信号弹窗 3m/6m/1y/3y/5y/all 交互 + chartLite canvas 渲染）
- **需求3（场外基金走势）**：① fund_daily_nav（DB 已有）→ 导出净值序列 JSON（如 `fund_nav/{code}.json` 或 Top100 合并文件，R2）② 场外基金卡片加净值走势 + 弹窗历史 + 指标介绍 ③ 依赖 fund_basic 字段补齐（pf-fund-screener-real-requirements，TASKS L1214）

---

## 5. 影响面 + 风险（C 级大改动评估）

1. **功能等价风险（canvas 重写 echarts）**：hover/tooltip/时间切换/缩放/pin 丢失即 §15 回归——首期只做 A 类（无 pin/无 zoom/无 period 的纯趋势 sparkline），把"复杂交互"整体排除在 canvas 化外，等价面最小
2. **性能对比验收**：改造后需测首屏（12 echarts.init → 0 或 1）+ 交互（hover 延迟）对比，落数据到 NOTES（对标 L7164 记录的 200-500ms）
3. **§22 一致性**：轻量/现有两实现同一数据源 + 同一 tooltip 文案；切换按钮后首屏 3 展示位（指数卡 sparkline / KPI 卡 sparkline / ETF弹窗走势）同步切换，不能出现一个 canvas 一个 echarts 混用不一致
4. **皮肤适配**：canvas 不响应 CSS var——复用 drawShareCard/withTheme 的 getComputedStyle + rethemeCharts 挂钩；15 皮肤都要验
5. **并发修改**：app.js 当前有并发 agent 在改（本次调研行号漂移 ~180 行）——实施前必须确认无在跑 agent / rebase 对齐，避免 cherry-pick 冲突（§18 教训6）
6. **SW 缓存**：改 app.js/chart-lite.js 必 build_min + bump_asset_version + bump sw.js CACHE_VERSION（§9 铁律）
7. **配置化回归**：boot.json 加 config key → 所有依赖 boot.json 的模块不受影响（纯增量字段）；site.yaml 改默认 → 需 deploy 推数据（§8 static-site/data/ 是上线渠道）；配置默认变更全站生效前按 §22 校验
8. **网络受限**：自绘 canvas 无外库依赖（uPlot/lightweight-charts 不引入）；chart-lite.js 是本仓库文件随 build_min 压缩
9. **数据源待调研（需求2/3 阻塞项）**：ETF 长历史数据源上限、场外净值序列导出格式——实施前派调研 agent 确认

---

## 6. 分阶段实施建议（每阶段独立验收 + 可独立上线回退）

| 阶段 | 内容 | 等级 | 验收口径 | 依赖 |
|---|---|---|---|---|
| **P0 统一配置框架** | config/site.yaml + export.py 写入 boot.json config key + `_siteConfig` 单例 + 首批接入 2 个开关（走势图轻量默认 + intraday 三态默认） | B 级（前端逻辑+数据产物 C 边界） | curl boot.json 含 config 字段值正确；改 site.yaml → export → 前端默认变；localStorage 覆盖仍优先；老功能无回归 | 无 |
| **P1 canvas 轻量走势图** | chart-lite.js + 双实现切换按钮（三态分段控件旁）+ 覆盖 A 类（首页指数 sparkline/KPI sparkline/ETF弹窗近30日/迷你折线统一）+ 默认走轻量 | **C 级大改动**（重写渲染）+ 需 reviewer | 首屏 echarts.init 计数下降（对标 200-500ms）；hover tooltip 语义等价；切换按钮回现有版工作；§22 三展示位一致；15 皮肤无异常 | P0 |
| **P2 需求2 ETF 30天外历史** | 数据源调研 → ETF 历史数据产物 → 弹窗 period tab（chartLite 渲染） | C 级（数据+前端） | ETF 弹窗 60/90/180天可看；R2/CF 数据一致；§22 多周期一致 | P1 + 调研 |
| **P3 需求3 场外基金走势** | fund_daily_nav → R2 净值序列 → 卡片/弹窗走势 + 指标介绍 | C 级（数据+前端） | 场外基金卡片有净值走势；弹窗历史；指标介绍字段补齐 | P1 + fund_basic 补齐 |

**先后顺序理由**：P0 先搭"配置框架"（小、低风险、用户想法3 的核心），P1 再动走势图（大改动挂在配置框架上，默认切换/兜底都现成）；P2/P3 是需求1/2/3 的延续，依赖 P1 组件 + 数据源调研。

---

## 7. 待用户确认的决策点

1. **配置源放 boot.json 合并 key 还是独立 site-config.json**（推荐 boot.json：零额外请求；代价是 boot.json 每次 export 会带上 config，改动需 deploy）
2. **降亏 toggle（29 个策略开关）是否纳入站点配置化**（建议不并：属策略实验参数集，独立维护）
3. **canvas 轻量首期覆盖范围**（建议只 A 类 4 处；分时图/行业网格二期评估）
4. **需求2/3 数据源调研**是否随 P0/P1 并行派（建议并行，不阻塞 P1）
