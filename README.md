<!-- SVG-BANNER-START -->
<p align="center">
  <svg xmlns="http://www.w3.org/2000/svg" width="780" height="180" viewBox="0 0 780 180">
    <defs>
      <linearGradient id="tdg" x1="0%" y1="0%" x2="100%" y2="0%">
        <stop offset="0%" stop-color="#00D4FF" />
        <stop offset="48%" stop-color="#7B2FFC" />
        <stop offset="100%" stop-color="#00FF88" />
      </linearGradient>
      <linearGradient id="line" x1="0%" y1="0%" x2="100%" y2="0%">
        <stop offset="0%" stop-color="#00D4FF" stop-opacity="0" />
        <stop offset="50%" stop-color="#00D4FF" stop-opacity="0.4" />
        <stop offset="100%" stop-color="#00D4FF" stop-opacity="0" />
      </linearGradient>
      <filter id="glow">
        <feGaussianBlur stdDeviation="2" result="coloredBlur"/>
        <feMerge>
          <feMergeNode in="coloredBlur"/>
          <feMergeNode in="SourceGraphic"/>
        </feMerge>
      </filter>
    </defs>
    <rect width="780" height="180" rx="18" fill="#0D1117" />
    <rect x="30" y="30" width="720" height="120" rx="10" fill="none" stroke="url(#line)" stroke-width="1.5" />
    <text x="390" y="105" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif" font-size="76" font-weight="900" fill="url(#tdg)" text-anchor="middle" letter-spacing="12" filter="url(#glow)">TDSIGNAL</text>
    <circle cx="170" cy="138" r="4.5" fill="#00FF88" />
    <circle cx="170" cy="138" r="8" fill="#00FF88" opacity="0.3" />
    <text x="192" y="143" font-family="'Courier New', Courier, monospace" font-size="14" fill="#00D4FF" font-weight="bold" opacity="0.9">A股 · 港股 · 全球</text>
    <text x="560" y="143" font-family="'Courier New', Courier, monospace" font-size="14" fill="#7B2FFC" font-weight="bold" opacity="0.9">◆  ONLINE  ◆</text>
    <path d="M 80 158 Q 160 140 240 158 T 400 158 T 560 158 T 700 158" stroke="#00D4FF" stroke-width="1.2" fill="none" opacity="0.25" />
    <path d="M 120 165 Q 200 152 280 165 T 440 165 T 600 165" stroke="#7B2FFC" stroke-width="0.8" fill="none" opacity="0.15" />
  </svg>
</p>
<!-- SVG-BANNER-END -->

# 📊 信号实验室 · tdsignal

> **A股/港股/全球盘后复盘情绪数据看板** —— 把散落各处的情绪值、涨跌家数、连板高度、买卖点信号、ETF 评分、策略实验室汇总到一处，
> 攒成历史序列，用**数据挖掘**从数千笔回测交易中反推出"降亏过滤标志"，每日用 **AI** 生成白话速递，
> 辅助判断市场情绪拐点与买卖时机。

**一句话**：免费数据源 + 情绪指数 + ETF 评分 + 凯利仓位回测 + 数据挖掘降亏过滤 + AI 每日速递，
一个把「数据采集 → 计算 → 可视化 → 交易信号 → 信号质量挖掘 → AI 解读 → 自动交易执行」全链路打通的开源情绪数据看板。

![market-status](https://img.shields.io/badge/语言-中文-brightgreen)
![python](https://img.shields.io/badge/Python-3.11-3776AB)
![fastapi](https://img.shields.io/badge/FastAPI-✓-009688)
![frontend](https://img.shields.io/badge/前端-原生JS%20%2B%20ECharts-FF6384)
![storage](https://img.shields.io/badge/存储-Cloudflare%20Workers%20%2B%20R2-F38020)
![ai](https://img.shields.io/badge/AI-DeepSeek%20每日速递-4D6BFE)
![mining](https://img.shields.io/badge/挖掘-子群发现%20·%20决策树%20·%20对比集-8A2BE2)
![schedule](https://img.shields.io/badge/调度-macOS%20launchd-lightgrey)
![license-code](https://img.shields.io/badge/代码-MIT-green)
![license-data](https://img.shields.io/badge/数据-CC%20BY%204.0-yellowgreen)

---

**在线体验**：<https://ss.fx8.store/>（CF Workers 主站，wrangler.jsonc 绑定，push main 自动 deploy，支持 br 压缩 + `_headers` CSP/HSTS）

**备用站点**：
- <https://sss.sugas.site/>（GitHub Pages）
- <https://s.sugas.site/>（MaoziYun，300MB 总大小限制）
- <https://ssd.fx8.store/>（R2 CDN，大 JSON 产物）

![信号实验室 · tdsignal](static-site/og.png)

`trade-data-signal` / `tdsignal`

---

## ✨ 功能亮点

> **全站数字单位直白化（2026-08-13）**：所有数字类卡片/图表标题/汇总 chips 条件允许即显示对应单位（金额 亿/万亿、量 只/家、波指 点、黄金 元/克、收益率 %、回撤 %、凯利账户 元 等），同一数据主值 / hover / 图表多展示位单位口径统一（§22），避免"纯数字靠猜单位"。

### 🌡️ 情绪温度计
- **A股综合情绪分**（0-100，6 指标加权：涨跌比/涨停数/炸板率/连板高度/成交额/北向资金），10 年历史回溯
- **跨市场综合评分**（去极值截尾均值，跨 A股/港股/全球）+ **恐贪指数**（8 情绪分等权合成）
- 6 个宽基指数独立情绪分：上证50 / 沪深300 / 中证500 / 中证1000 / 创业板 / 科创50
- 阈值标注：< 20 = 冰点 🔵，> 80 = 过热 🔴
- **情绪分买卖点信号列表**（市场温度顶行，与冰点/过热热力图同排同高）：首页信号列表已过滤情绪分信号（情绪分是 0-100 衍生指标非可交易标的、无 ETF 参考），此处单独列出 A股综合/跨市场/恐贪/6 宽基共 9 类情绪分的买卖点信号作情绪拐点逆向参考，红=卖（高位回落）、紫=辅买（下轨拐点）、绿=买（超卖拐点），点击查看走势+标注

### 📈 买卖点信号（事件化 + 回测验证）
- **主买**：RSI(14) 上穿 30（超卖反弹拐点）；**辅买**：布林下轨回归（强势市更敏感）；**卖点**：20 日高点回落 5% + MA60 多头过滤 + MACD 死叉确认
- 每个信号附 **回测统计**（胜率/盈亏比/样本数/**凯利仓位**），样本不足自动标注
- **113 品种模拟回测**：全历史信号 × 5/10/20 日 forward 收益
- **两段式信号固化（2026-08-14 新增）**：首页信号按固化时点展示，A 股指数信号 15:03 收盘价首轮定稿后**不会再消失**（不看邮件也能知道 15 点后可操作哪些信号）。后端 `overview.json` 注入 `signals_meta` 三态（`a-share-close` A股已固化 / `full` 17:50 完整版含港股/欧股/国债 / `evening` 20:36 当天最终，由服务端真实时点判定，前端不硬编码时间）+ 每条信号补 `close`/`etf_close`（复用 index_daily/etf_daily 已有价格，零新增采集）。前端信号区标题下三态提示条 + AI 建议区「⏰ 已固化·可操作（盘后窗口）」标签 + 参考说明弹窗/hoverpop 补「⏰ 当日实操建议」段（15:05-15:30 盘后固定价格窗口可按当日收盘价操作，当日可执行标的=AI 建议 1/2/3）。§21 公示同步（purpose-notes `lab.sigkelly` 补信号固化时点说明），详见 [`docs/signal-finalize-time.md`](docs/signal-finalize-time.md)。

### 🎯 ETF 评分弹窗（5 区块）
- 决策头 / 手数 or 卖出 / 置信度 / 8 维度评分 / 历史类比，仓位红线断线保护，指数↔ETF 全匹配
- **🐶 汪汪队信号卡"数据日期 vs 信号日期"语义（2026-08-14 修复）**：汪汪队（ETF 国家队份额变动）信号仅在**有异动触发**时写入信号表，无触发时"最近信号"会停在最后一次触发日（曾卡 7/31）。修复后卡片以 `etf_daily` 的**数据日期**（每日健康更新）为基准展示，当信号距今超过阈值未触发时灰色标注"⚠ 近 N 个交易日无信号触发（数据仍更新至 MM-DD）"，不把旧的最后信号日伪装成"今日有信号"；AI 每日速递同步注入新鲜度提示，避免把旧信号当实时数据呈现（§23.2 修 bug 三铁律 + §23.3 举一反三，§22 展示位一致性）。

### 🚦 信号灯 + 降亏过滤 toggle
- 信号列表信号灯统一配色（分级档位 + 低置信灰蓝虚线），hover 显示减亏/损盈/比值三项
- **降亏过滤开关**：数据挖掘发现的"系统性亏损特征组合"一键 toggle（详见「参考与致敬」段）
- **组合降亏预设宏（2026-08-11 新增，1月调整为 2026-08-11 元素级重组追加）**：4 个命名组合（年末季节 / 稳健核心 / 最大化降亏 / 1月调整），点击组合自动勾选成员 toggle、过滤仍走成员谓词并集（幂等可叠加，多组合=成员并集 OR）；组合勾选态由成员派生（全勾=勾选/部分=半选），hover 显示组合并集口径指标（年末季节 6.50 / 稳健核心 5.95 / 最大化降亏 greedy15——⚠2026-08-13 穷举v2 已并入 AI降亏过滤 默认 核心3键（r7+exclAuxCross+greedy15），本组合成员与 核心3键 完全重复，勾选幂等无害勿单独勾，勿误解为默认全开 / 1月调整 J1 4.71、J2 4.49）；⚠2026-08-14 #48 口径修正（每日池）：4 组合全开=可选分析非默认推荐，与 AI宏7键默认差仅 **0.3-0.7pt**（G K1 47.22% vs 46.54%，旧 fixed 结论「低 6.33pp」基于每笔1万已过时）；G 模式（推荐卖出法）最优=AI宏7键去 greedy15/excludeAuxCross/r7 + 加 a45 → K1 51.66%（净+82.6万），A/F 短持维持现状默认；成员选择依据国外特征选择/组合方法论（IV/WoE、mRMR、RFE、Lasso、López de Prado 特征聚类等，见「参考与致敬」段）
- **1月调整组合（2026-08-11 元素级重组挖掘；2026-08-12 用户拍板并入默认推荐组合默认开启——"只要有增幅就做"，fixed 口径 G 模式 all 增量 +1.2 万/+0.77pp，全 9 模式正增量合计 +7.0 万）**：18,047 个元素交叉组合全扫描发现的唯一新边际——1 月中旬（11-20 日）+ mid 评级（J1，比值 4.71 / 4 窗口全 >2 / 与现有标志 90% 不重叠，附监控 maxSh 0.62）与 1 月中旬+追关注（J2，比值 4.49，覆盖更广）；只做中旬（1 月上旬=盈利口袋全负 -56 万不可动），验证见 [`docs/kelly/combo/kelly-jan-adjust-combo-verify.md`](docs/kelly/combo/kelly-jan-adjust-combo-verify.md)
- **组合使用建议 + 全信号表（2026-08-12 新增，真实回测口径）**：凯利回测区顶部置顶两块——①**全信号操作建议指南**（原「降亏组合使用建议」，2026-08-14 重构更名；整体可收缩默认折叠、标题一行概览点击展开；内部分节去序号平铺「分投资习惯」与「总建议」两节，去掉原「②分投资习惯」收起展开；原「4 组合全开」折叠区因 fixed 每笔 1 万口径过时已删除；G 行数据改**可操作口径**（P≤3d「先卖年轻」三档 13/15/20 万，峰持仓≤20 倍本金，不再披露原始 329 笔/146 万无操作性数字，§22 与 ai长线对比表/卡片一致）；§21 公示同步 purpose-notes）：回答"默认组合怎么用 + 投资习惯对照 + 总建议"（A/F/G 三玩法实时并列（2026-08-12 #18 推荐区：A=固定10天短线 / F=持有15天短线 / G=卖出信号长线，各披露峰值资金收益率+最大持仓+所需最小本金[≈峰值同时持仓资金÷20，20倍资金约束折算]，实时随降亏组合/费率联动、与全信号表同源）+ 追高/保守投资习惯 + 总建议=全信号都看+完全遵守交易页面交易方法（卖出信号 G 模式）），全部数字来自复刻本页过滤/统计管线的真实回测，分析文档 [`docs/kelly/combo/kelly-combo-usage-advice.md`](docs/kelly/combo/kelly-combo-usage-advice.md)；②**全信号表（最后结果）**：全信号=评级高低分区并集（全量信号不拆分），实时随降亏组合勾选/费率档/周期切换联动 + 按年窗口增长表（净盈亏/累计/胜率/峰值资金收益率——峰值资金收益率=该年累计净盈亏/该年峰值同时持仓资金×100，与卡面/建议面板同口径；**2026-08-14 #BC 归正+扩展：按年窗口增长表各模式（A-G）各自独立，下拉切换查看**（原全 9 模式累加量级虚高；2026-08-14 归正为各模式独立聚合非混算，表上方下拉选择 A-G 任一模式查看其各自的按年窗口增长，默认 G 模式=当前推荐卖出法，对齐「总建议=遵守G模式卖出」语义；**2026-08-14 布局优化：按年窗口表格限高（不超「强关联ETF」卡片高度，超出部分表内滚动，`_applySigKellyYearlyMaxHeight` 实时测量 etf_strong 卡高度设为滚动容器 max-height）**；**2026-08-15 #83 移除「AI仓位建议 · 历史回测(G模式口径)」面板**（每笔固定 1 万·裸 G 旧口径已废弃，核心结论被 K 按钮评级(common.js 每日池) + 按年窗口增长表(每日池实时) + 全信号建议指南完整继承，详见 removal-check.md §5.3）；G 模式每日池 K=1 口径净 +64.2 万/n=1,202；旧「4 组合全开 2019 起累计增长 2024 +429 万/2025 +986 万/2026 +1,087 万；2023 -48 万」为可选分析非默认的多模式视角静态表，与 G 模式口径不同属正常 §22）；交易记录弹窗中被降亏/仓位控制淘汰的交易以**删除线灰化**展示（不计入统计，仅对照哪些被淘汰）；**卡片置顶（2026-08-13 新增）**：全信号表卡+16 子域卡每张卡头加 📌 按钮，置顶卡集中显示在最前部「📌 已置顶」区（置顶子域卡从原分组剔除、样式金边高亮），localStorage 持久化刷新保留、点击可取消置顶回到原分组，只影响展示顺序不动卡片内容/排序算法——方便调试降亏排序等条件时只盯关心的卡组；**2026-08-14 费率默认改 ETF主流 + 来源条件提示 + 首列合并**：①**费率默认档=ETF 主流**（万0.5 最低0.1，原 ETF 默认 万3 最低5 为历史默认），页面加载/重置默认即按 ETF 主流口径渲染，渲染数据随费率档联动重算（§22 一致性）；②**按年窗口增长表上方「当前[模式]+[k档]+[降亏N标志]+[费率口径](+[G档])」来源条件归纳提示**（2026-08-14 新增）：动态读当前勾选/费率档/K档/G档实时拼出本表数据实际使用的来源条件（G 模式额外补 G 三档 13W/15W/20W），不写死；③**表格首列模式字母+描述合并为一行**（模式名+描述 inline 同处一行，消除「描述独立一行拉高行高」，AI长线/淘汰角标仍同格展示）；**2026-08-15 #84 报告查看弹窗改完整正文**（原仅摘要+目录，现=完整报告 HTML 正文）：全站各「🔍查看报告」按钮（建议指南/ai长线对比表/G玩法教学等）点开弹窗放大（1024px/移动端 96vw）展示对应报告 md 的**完整正文**（h1-h4 结构 + 表格 + 代码块 + 引用都保留，正文区独立滚动），目录(TOC)收敛为可折叠 details 段——10 份调研报告正文由 `scripts/kelly_reports_html.py` 从 `docs/kelly/**/*.md` 经 GFM markdown(表格+代码块)预生成到 `kelly-reports-content.js`(§23.5 数据来源一致)，lab.js `_kellyReportModalHTML` 读取完整正文而非仅目录
- **仓位控制过滤 positionCap（2026-08-12 新增，K 敏感性回测；2026-08-12 起默认开启 K=2（2026-08-13 默认 K 调为 3）+ 4 个降亏推荐（AI降亏过滤=新默认：追关注×熊市/J1/J2/n2，2026-08-12 用户拍板"替换默认(AI降亏过滤=新默认)"，A45/A5 移出默认；2026-08-13 穷举 v2 落档：[`docs/kelly/backtest-ai/kelly-ai-macro-exhaustive-report.md`](docs/kelly/backtest-ai/kelly-ai-macro-exhaustive-report.md)（406,336 配置全量穷举，修正 v1 三缺陷），AI降亏过滤默认推荐升级为 **核心3键配置 r7MayReinforced+excludeAuxCross+greedy15 叠加 AI_BASE**（r7 5月强化+3稳定非5月 / 辅关注×3/5月交叉 / Greedy-15组合；K1 A=77.36%/净利8.51万/n1184；K1 仅微低于 A 全局最优 5 元配置 0.35pp，K2-K4 三档反超 5 元，更简洁防过拟合；「4组合全开」定位为可选分析非默认推荐——每日池口径下与默认差仅 0.3-0.7pt（旧 fixed 6.33pp 已过时））——7 个降亏默认推荐 toggle + AI仓位建议（AI降亏过滤总开关独立行另1处徽标，共9处⭐ 徽标）以金色高亮+⭐ 推荐徽标（2026-08-13 精简文案：原「默认推荐」→「推荐」）+hover 推荐理由展示；**AI降亏过滤 三级级联 UI**：第1级 AI降亏过滤 总开关独立行（可收起展开，勾选联动 全部7个默认推荐子复选框（基础4+核心3）、三态由7键派生，语义=「AI降亏过滤默认推荐(7键)」开合；2026-08-13 #54 bug1 修复：原仅联动核心3键扩为7键全联动），第2级 组合降亏 4 预设宏（可选分析非默认推荐），第3级 单标志降亏；**2026-08-13 融合优化（#39+#45 落地）**：第2级 组合降亏 4 预设宏改为**顶部快捷按钮**（一键勾选/取消成员，active=全选/semi=半选，hover 显示组合并集口径指标）；第3级 单标志降亏 **31 个单标志全量默认展开合并进主区块，移除原「细标志(24)展开」折叠按钮**，按 **4 大分类组**（日历效应·季节调仓 19 / 复合并集·广谱管理 7 / 信号质量·弱信号 3 / 市场防御·大盘择时 2，单一事实来源 `_kellyFadeFlagGroups` 数组驱动渲染，组间固定序=组内代表比值降序、组内比值降序、⚠监控成员带「监控」标记置尾、⚠慎用成员标注、白话名，2026-08-12/08-13 纯展示层重归类不改过滤逻辑）分组展示，**每组标题可点击折叠**（caret ▶/▼），默认推荐 7 键全标 ⭐（基础4 只标 ⭐ 默认推荐不标 linked；核心3 标 ⭐+🔗核心3键 linked 受总开关控制））**：金额口径=**每日资金池等分 + top-K**（2026-08-14 #48 页面口径对齐；2026-08-12 曾临时切"每笔固定 1 万"5d047aef2，用户原话"1w 还分 30 个信号买 30 份没意义"，2026-08-13 用户纠正理解错误——反对的是"每日池+买全部"每份太小、非每日池本身，恢复每日池等分+top-K c951dafa8/263bc9298：每日总投入恒 1 万、当日保留 N 个信号则每笔=10000/N）；不勾仓位控制=每日池+买全部信号，勾上=每日池+只买当日最优 K 个。**仓位控制过滤**=按 signal_date 分组当日基笔信号，组内按 跟踪分→评级→信号类型→买入日 排序保留前 K 个，K 可配置 1-4 默认 1=主推（2026-08-14 #BC 由 3 改 1；每日池+费率重算含最低5元 AI宏7键 A模式 K1=86.60%/K2=67.61%/K3=66.24%/K4=63.17%，doc 明细 docs/kelly/position/kelly-dailypool-exhaustive-rerun.md；旧 fixed 每笔1万 G模式历史:关=32.27%/K1=48.58%/K2=40.41%/K3=38.96 与 #48 比例法 均为历史基准；K=1 每日池收益率最高（86.60%）+回撤最小+样本最少=主推★；⚠每日池口径 K=1 与每笔1万等价、K>1 每笔1万为虚假杠杆）。交易页整个信号列表（近15交易日）联动（2026-08-12 #4 rename+范围扩展）：每个日期各自按同一排序算 top-K，前 K 个标「AI建议」、其余「当日已满」灰显（历史日期为复盘视角，口径与回测一致；原「仓位控制过滤」更名为「AI仓位建议（技术别名：仓位控制过滤）」）。与降亏同开仅推荐 AI降亏过滤 默认组合（excludeSpecialBear/janMidRating/janMidSpecial/n2NovSpecialIndustry/r7MayReinforced/excludeAuxCross/greedy15，默认已开启；默认 toggle 维持 AI宏7键不改；最佳 K=1 主推（2026-08-14 #BC 默认档 3→1）；每日池+费率重算 A K1=86.60% 主推（K2=67.61%/K3=66.24%/K4=63.17%），旧 fixed 穷举v2 K2 A=66.22% 较基础 37.90% +28pp、G 净利 127.7→103.1 万 以降净利换收益率为历史基准）；绝不同开 live4/COMBO4 全开；勿再叠加 greedy7/10 等其他广谱（greedy15 已在 AI降亏过滤 默认内，详见 §21 算法公示与 [`docs/kelly/position/kelly-position-cap-k-sensitivity.md`](docs/kelly/position/kelly-position-cap-k-sensitivity.md)）。**K 档位评级标注（2026-08-13 新增，展示层不改算法）**：档位按钮直接标注评级 1=最激进（主推★）/ 2=次稳健 / 3=最稳健 / 4=最保守，hover K 按钮弹评级理由表格（收益率/峰值资金回撤/风险调整/样本+一句话理由）；K 按钮与评级表行按主推行置顶 **1342 排序**（K=1 主推置顶，默认 active K=1（2026-08-14 #BC 默认档 3→1））；评级口径=AI降亏过滤默认 AI宏7键 + A模式(固定10天) + 每日资金池等分+top-K + 费率etf_def(含最低5元) + 全周期回测（2026-08-14 #BC 费率重算口径：K1 86.60%/回撤15.99%/样本1,202 主推 → K2 67.61%/回撤18.64%/1,930 → K3 66.24%/回撤16.19%/2,461 → K4 63.17%/回撤17.84%/2,870，与 AI降亏过滤 提示口径一致；旧 fixed 每笔1万 K1 77.36%/K3 68.40% 与 #48 比例法均为历史基准）；**2026-08-13 #54 hoverpop 动态化**：AI仓位建议开启时，评级表随当前降亏勾选（7键或自定义）/费率档/最新数据由前端同一重算管线实时重算（`_AI_POSCAP_RATING_DYNAMIC` 共享单一数据源，首页/凯利区两处 §22 一致），标注「实时·当前配置/费率/数据(日期·费率)」，未开启/未重算时回退静态快照 08-14 标注「快照」（每日池口径，K1 86.60% 等）——用户可在页面直观看到「86.60 对应当前数据的值」随配置/数据变化；⭐ 默认推荐徽标同步（2026-08-13 #54）：rec=true 但当前勾选已关=降级显示「已关」灰虚样式，随勾选实时同步；**2026-08-13 统一布局升级（凯利区调序+OFF+共享评级数据）**：凯利区「AI仓位建议」行已调序至「AI降亏过滤(总开关)」行上方（对齐首页布局：3124 K 按钮 + OFF + 简短标题在前），标题精简为「AI仓位建议 K:」（技术别名「仓位控制过滤」+ 每日只买最优K个/按 signal_date 分组排序保留前K个等口径说明全进 ⓘ tooltip，不丢信息只重新分层），K 按钮组加「关」OFF 按钮（写 tds_poscap {on:false} 退化普通列表、再点某 K 档恢复，与首页/交易页同键联动 §22）；评级 hoverpop 数据/HTML/绑定抽到 common.js 共享单一数据源（`_AI_POSCAP_RATING`/`_aiPoscapRatingPopHtml`/`_bindAiPoscapRatePop`），首页 K 按钮 hoverpop 同步升级为凯利区同款评级表格（§22 两处数据/口径一致）；AI降亏过滤总开关语义澄清（2026-08-13 #54 bug1 修复）：勾选联动全部7个默认推荐子复选框（基础4 追关注×熊市/J1/J2/n2 + 核心3键 r7/exclAuxCross/greedy15），三态由7键派生；详情收起按钮后新增「重置为AI默认推荐」按钮（2026-08-13 #54）——一键恢复默认7键全开+AI仓位建议 K=1主推（2026-08-14 #BC 默认档 3→1）、重写本地记忆 tds_kelly_filters/tds_poscap 并刷新统计与评级，toast 确认
- **首页 AI 开关 + 信号级降亏标记（2026-08-13 新增；2026-08-13 reviewer 修复：灰显改成员级+加 A股/仅买守卫）**：首页信号列表标题下第一行新增「AI 降亏过滤开关 + AI仓位建议 K 档按钮组」——①AI 降亏过滤开关（总开关，2026-08-13 重构：原「AI降亏过滤」+「AI降亏显示」两开关合并为一个按钮，首页独立作用域，localStorage `tds_home_fade` 默认开启，与凯利区 `tds_kelly_filters` 解耦互不影响）：开启=首页按降亏策略判定（固定 7 键成员级：基础4 追关注×熊市交叉/J1/J2/n2 + 核心3键 r7/辅关注×3/5月/Greedy-15，**默认=穷举最大化推荐（核心3键：A模式每日池 K1=86.60% 最激进 / 默认档 K=3 A=78.91%（2026-08-14 #48 每日池口径；旧 fixed K1=77.36%/K3=68.40% 为历史基准）**），命中降亏条件的信号灰显+删除线+「AI降亏」标注+hover原因+不占AI建议位；关闭=首页完全不判降亏、信号恢复正常样式、AI仓位建议 top-K 正常取；后端 overview.json 生成时（app/queries.py）给每条信号注入 `ai_macro: {hit, filters}`（7 个降亏谓词同源凯利回测：追关注×熊市交叉/J1/J2/n2/r7/辅关注×3/5月/Greedy-15，price_bin 依赖子条件信号级不可判定时诚实降级不误标；⚠2026-08-13 修复：excludeSpecialBear 仅对 A股类(a/concept/industry)按 hs300 MA60 判熊、非A hk/global/hk_industry 不过滤与凯利同源，全部谓词仅买信号守卫——非买 band_hold/sell/sell_stop_loss 不判降亏）；该信号命中降亏条件（固定 7 键成员级，2026-08-13 重构后开关开=基础4+核心3键全生效）→ 信号灰显+删除线+「AI降亏」标注（hover 信号本体或「AI降亏」标注均显示命中的降亏条件与删除线原因，建议回避；2026-08-13 加 hoverpop 删除线原因说明；**2026-08-13 重构合并为总开关**——点击后若列表无任何变化弹 toast 提示"当前无命中降亏条件的信号"，避免用户误以为开关坏了）；②AI仓位建议 K 档按钮组（1342 排序，K=1 默认主推★，2026-08-14 #BC 默认档 3→1）：直接切换 K 并联动「AI建议/当日已满」灰显（2026-08-13 AI建议加序号「AI建议1/2/3」=当日跟踪分降序第 N 名（与凯利回测 K 档口径一致，不随 K 档跳变；2026-08-13 编号修复：原按渲染序→道琼斯质量第1却显示 AI建议3，改为质量序编号，列表视觉位置不变仅编号=质量序）；**2026-08-13 融合口径：AI仓位建议 top-K 与 AI降亏 对齐回测（lab.js 先滤降亏、再选 top-K）——命中降亏的信号不占 AI建议位、顺延补位给未命中信号；被降亏划掉的信号不显示「AI建议」也不显示「当日已满」（非满员，是被过滤），仅以删除线+「AI降亏」标注兜底展示**；补位随首页「AI降亏过滤」开关门控（开关开=先滤降亏再选 top-K 顺延补位；开关关=不滤、top-K 正常取，与回测一致）；与凯利区/交易页共享 tds_poscap；**2026-08-13 hoverpop 升级**：K 按钮组复用凯利区同款评级表格 hoverpop（共享 common.js 单一数据源 `_AI_POSCAP_RATING`/`_aiPoscapRatingPopHtml`/`_bindAiPoscapRatePop`，悬停 K 按钮区弹评级理由表：收益率/峰值回撤/风险调整/样本+一句话理由，口径=AI降亏过滤默认核心3键+A模式+每笔1万+费率etf_def+全周期，与凯利区两处数据一致 §22）；**2026-08-13 补强**：③「关」按钮——写 tds_poscap {on:false}，与凯利区 toggle 同键联动（§22），关闭后该区域退化为普通信号列表（无 AI建议/当日已满 badge），再点某 K 档恢复；④（2026-08-13 重构：原「AI降亏显示」开关已合并进「AI降亏过滤」总开关、不再独立存在，旧键 tds_poscap_aiDisplay 废弃；显示随过滤开关走——过滤开=命中降亏信号显示删除线+「AI降亏」标注+hover原因，过滤关=完全不显示；与凯利区完全解耦，不改凯利区任何计算）；**2026-08-14 参考说明按钮（独立化升级 2026-08-14）**：K 档按钮组「关 off」后新增「推荐方法&参考说明」按钮——**独立样式 + 独立 hoverpop，不复用 K 档/off 按钮的 sig-kbtn 样式与评级表 hoverpop**（`.sig-kbtn-help` 主色系描边+浅底，`.sig-kbtn-help-wrap` 自包含定位；`_sigHelpPopHtml`/`_bindSigHelpPop` 独立实现，悬浮弹「推荐方法·参考说明」要点：短线 A/F 固定持有 10/15 天快进快出 + 中长线 G 指数卖出信号触发离场、无信号持有（总建议主选，可选 P≤3d 先卖年轻仓仓位管理）+ 底部引导点击查看完整说明；内容口径与下方弹窗一致 §22）；点击弹「推荐操作方法」说明弹窗（复用既有 rule-modal 机制）：讲清短线 A/F 玩法（A=固定10天短线/ F=持有15天短线，快进快出）+ 中长线 G 玩法（指数卖出信号触发离场、无信号持有至回测结束，最贴近交易页信号驱动跟单、总建议主选，可选加 G 仓位管理 P≤3d 先卖年轻仓），并引导跳转「信号凯利回测」（#lab?sub=sigkelly）定位 A/F/G 模式回测数据校验；文案口径与凯利回测页 A/F/G 三玩法实时并列表一致（§21/§22）；**2026-08-15 次日玩法接入**：参考说明弹窗+hoverpop 补「🆕 次日玩法」——推荐操作更好放次日而非当日收盘：次日开盘直接买比当日收盘买几乎不输（净利仅低 0.01%、胜率反升），更稳=分 N 单挂「次日开盘价 -1%」限价 + 未触达尾盘按现价补满把 1 万预算买满，回测（2011-2026，87.9% 交易日日内最低点低于开盘=免费搭日内下探便车；K=1 每日池 G 模式 80.0→86.1 万，比次日开盘直接买多赚约 6 万、收益率 +3.8pt、均价 -0.37%）比次日开盘直接买多赚，数据支撑 [`docs/kelly/position/kelly-nextday-batch-limit-sop.md`](docs/kelly/position/kelly-nextday-batch-limit-sop.md) §3.4，§22 三处（弹窗/hoverpop/凯利建议面板）同口径；**2026-08-14 首页信号八/一四空态+迟到补齐（P1-1/P1-2/P0-2**）：①**空态提示横条**——某日无「入样宇宙买入信号」（如全为风控/持有类或仅债类 cgb_*，§23.6 规则）时，日期组标题下方渲染灰色横条「当日无入样宇宙买入信号，仅有风险/持有状态」，替代静默零标注（基于全量 signals_today 判定，不受用户子筛选影响）；②**「当日已满」补入样判**——未入样宇宙(uni=false)的买入类信号不再误标「当日已满」（修 8/10 csi_931892/gz_399440、8/12 thsc_306380），与空态/零标注口径一致；③**「盘后补齐」角标接口**——迟到信号（17:50 后、21:00 backfill-evening 指数补采才进的）挂「盘后补齐」角标，字段 `_bt_late` 由后端 P0-1 注入，前端已预留渲染；定稿文案对齐 21:00 补采（signals_meta.finalized_note + 前端 banner + purpose-notes 同步，不再宣称「20:36 后最终定稿」）
- **首页 AI 过滤视图（2026-08-14 用户新视图口径「只显 AI 推荐，其余直接过滤置灰并标原因」，两开关正交不绑定）**：首页信号「AI降亏过滤」与「AI仓位建议 K」是两个独立正交开关、各自管一层、不互相触发——**开关1「AI降亏」=删除线过滤层**（`tds_home_fade`）：开启时 ①命中降亏条件（固定 7 键）的买入信号=灰色删除线+「AI降亏」标注（现状已有）+ ②未入样宇宙信号（债类 cgb_*/情绪 s.*/全球商品 g.*/港股行业 hk_*/未收录/凯利模式剔除/4+3+1 剔除，后端 `_bt_in_universe===false`）=删除线+弱化灰显+「**未入样本**」标注（表达"被凯利模式剔除过滤掉"）；**开关2「AI仓位」=badge 标注层**（`tds_poscap`）：开启时 ①买入进 top-K=「**AI建议N**」（现状）+ ②买入超 K=「**当日已满**」+ ③**入宇宙卖出**（sell/sell_stop_loss/波段减仓）=亮色「**AI警示**」（醒目警示橙，卖无K约束不判K，卖出=离场保护非过滤不置灰）；**全关=全量视图**所有信号正常亮显不标注；band_hold 波段持有=中性不标不置灰；边界不重叠（未入宇宙走「未入样本」、入宇宙未进 K 走「当日已满」）；空态横条改「今日无 AI 建议买入信号，仅风险/持有状态」（按 AI仓位开关门控）；迟到的入宇宙卖出（如 8/14 中证银行 sell）「AI警示」+「盘后补齐」角标共存不冲突；§21 公示同步（purpose-notes + lab.js 凯利 toggle + app.js 两开关 tooltip）
- **凯利回测 AI 分析报告（3AI 新版 + 双AI 历史切换，2026-08-12 升级；2026-08-14 移页尾作历史留存）**：报告区顶部新增「3AI 新版（默认）/ 双AI 历史」切换（localStorage 记忆）：3AI 模式=3AI 结论对比（主控综合 vs DeepSeek vs Claude 第三角色，含 6→9 卖出模式数据换代迁移）+ 主控综合 + DeepSeek 独立 + Claude 第三角色独立分析（deepseek-v4-flash，基于新版 9 模式数据）；双AI 历史模式=旧双AI 对比 + 主控综合 + DeepSeek 独立（基于旧 6 模式数据，2026-08-09，完整保留可切回对照）；**2026-08-14 用户定：「AI 报告版本已过时」，整个 AI 报告折叠区（切换条 + 3AI/双AI 全部报告块含 claude-v4）从页面中部移到凯利回测页尾（所有数据表格/图表/「最后结果」全信号表之后）作历史留存**——加「📦 历史 AI 报告存档（结论已过时 · 仅供回溯）」归档标注 + 灰色弱化边框，默认折叠收起；切换 3AI/双AI、localStorage 记忆、KELLY_REVIEW_NOTES 内容原样保留，只调位置不删内容；页中部只留「当前有效」数据，过时 AI 结论沉底供回溯；内容由 [`docs/kelly/backtest-ai/kelly-backtest-3ai-comparison.md`](docs/kelly/backtest-ai/kelly-backtest-3ai-comparison.md) / [`docs/kelly/backtest-ai/kelly-backtest-claude-v4-review.md`](docs/kelly/backtest-ai/kelly-backtest-claude-v4-review.md) 经 `scripts/md_to_html.py` 生成，非投资建议
- **ai长线模式(G/H/I)仓位管理（2026-08-14 #49 新增 + #xx 三模式独立策略，默认关，叠加现有判断不改 A-F）**：`策略实验室`凯利回测区新增「ai长线模式(G/H/I)仓位管理」独立开关（长线族群总入口）——**G/H/I 三中长线模式各配独立最优仓位策略（不再统一 FIFO 20万）**，目标=本金可控化（关态 G/H/I 峰值持仓超 20 倍单次本金=不可操作）：**G**=P≤3d「先卖年轻仓」（手段P，超仓先卖≤3天新仓、无年轻仓才卖最老，保21-100天利润引擎砍新仓）+**13/15/20 三档自选**（开关行内嵌档位切换，存 `tds_gih_g_tier` 默认13万，切换全消费点实时联动）；**H**=满仓不买@7万（手段A，到7万停买不强制平仓）；**I**=满仓不买@15万（手段A）。架构=模式→策略映射（`_kellyGihStrategyKey` + `AIHLINE_STRATS` 策略表，后续某模式优化只改该模式策略、不动按钮整体；前端仿真内核按 strategy.method 分发 B=FIFO/P=P≤3d/A=满仓不买）；默认关，开启后 G/H/I 卡片行套各模式仓位法值（乐观 b1 口径、标「AI长线·开」角标+当前策略名）+「G/H/I 对比表」展示关/开(保守b0)/开(乐观b1)三态（数据来源 G=[`docs/kelly/position/kelly-g-mode-recheck.md`](docs/kelly/position/kelly-g-mode-recheck.md)、H/I=[`docs/kelly/position/kelly-ghi-continuous-cap-sweep.md`](docs/kelly/position/kelly-ghi-continuous-cap-sweep.md)，推荐 K=1 参考口径，前端仿真内核与报告逐位对齐 §21）；效果按模式区分：**G** 关 47.2%/+64.2万/136万 → 开 现档三选（13万=155.8%/+20.3万、15万=147.3%/+22.1万、20万=131.3%/+26.3万），P≤3d 全面超旧FIFO（15起始年全胜/随机30点0/30负/b0-b1区间窄4-24pp更可信）+第三档可切换；**H** 关 34.3%/+15.4万/45万 → 开@7万 107.6%/+7.5万/7倍本金；**I** 关 39.5%/+43.9万/111万 → 开@15万 90.0%/+13.5万/15倍本金；H/I 手段A 无强平 b0=b1 完全确定（但 H 小本金档净利绝对值低 7.5万，绝对盈利目标可放宽）；诚实标注：仅 G(P手段)有强平日，真实盈亏不可知（保守 b0=按 0 利 / 乐观 b1=按持有时间线性，真实值在区间，不把乐观当承诺），H/I 无此问题；开 cap 后 G/H/I 全为 K=1 最优（2026-08-14 #BC 前端默认即 K=1 主推,与推荐一致）；A-F 短线模式天然≤20 倍不受影响。***#xx G 档位三档全部展示给用户自选**（13万激进收益率最高/15万折中/20万最稳绝对净利最高，资金宽选高档吃绝对净利、偏紧选低档吃收益率，峰持仓全≤20倍=可操作）
- **不可操作淘汰标注 + TOP1 推荐算法修正（2026-08-14 #25 A包 新增，仅展示层不改任何回测算法/数据）**：以「峰持仓≤20万（=20倍单次本金）视为可操作」为统一判据，峰持仓超限的记录在 卡片行/全信号表/三玩法表/水印/交易记录弹窗 以 **删除线灰化 + 「淘汰」角标 + hoverpop/弹窗淘汰理由** 展示（不消失，用户仍可查看数据验证，与降亏淘汰同交互语义）——①需求②：ai长线(G/H/I)未开、G/H/I 原始仓位峰持仓超 20 倍（关态需 45-148 倍本金）→ 标「淘汰·无操作性」，开上方「ai长线(G/H/I)仓位管理」套各模式仓位法（G=P≤3d三档/H=满仓不买7万/I=满仓不买15万，峰持仓≤20倍可操作）后恢复；②需求D：AI仓位建议 K 档「关」（positionCap OFF，无仓位限制、每笔固定 1 万全买致峰持仓疯长）→ 标「淘汰·无仓位限制·无法实操」，切 K=1-4（每笔=10000/当日保留数有仓位控制）后恢复；K=1-4 开启的正常记录不误标。**TOP1 推荐算法修正**：推荐排序由「按净盈亏 total_profit」改为「先可操作层过滤（不可操作模式不参与推荐）→ 再按收益率（峰值资金收益率 return_pct_max_holding）降序」选 TOP1，净盈亏/最大持仓仅作佐证不参与排序（修掉按净盈亏致 TOP1 偏向高持仓模式 bug，如 F 大净利压过 A → 默认可操作层 TOP1=A）；GIH 开时 G/H/I 读各模式仓位法后（乐观 b1）值参与推荐

### 📊 市场宽度 / 🏭 行业轮动 / 🏦 期货机构持仓
- 涨跌家数、涨停/跌停、连板高度、炸板率、封板率、腾落线、52 周新高新低
- 申万 31 行业热力图（1 日/5 日）+ 行业资金流 + 轮动速度 + 对应 ETF 标注
- 中金所 IF/IC/IH/IM 前 20 会员净多空持仓，同向/逆向准确率

### 🤖 每日 AI 速递（deepseek）
- 收盘后自动生成 **daily_brief 白话解读**（deepseek 生成，本地合规 gating），邮件直发
- **首页并排展示**：横幅「🤖 AI 预测」与「📜 历史收盘分析」并排，弹窗内历史列表分页反查（点开某日=预测内容+meta断言+次日实际涨跌+命中标记）+ 近30/90日命中率（meta机检次日回填）；2026-08-15 起为**三层全命中**：预测给出明确方向 + **中间层 7 个全押**（深证成指/创业板指/科创50/北证50/恒生指数/恒生科技涨跌幅% + **10年国债收益率变化基点**）+ 大盘上证与领涨/领跌板块次日涨跌幅区间（宽度≤0.5%、越窄越准），次日实测落进大盘区间 **且中间层 7 个全部命中 且** 所有预测板块全中=✅三层命中（大盘+中间层7+板块）；10年国债命中=（次日 cn10y − 当日 cn10y）×100 落在预测基点区间；改造前老条目无区间/无中间层不伪造，只保留旧"方向相等"判定（✅仅方向命中），区间命中标"层级N/A"（不算中不算不中，任一层数据缺失整体不硬判）
- **多角色协作式预测**：6 角色子 prompt 编排（技术面/资金面/情绪面/风控分析师并行 → 研究员多空辩论 → 主编组装合规），每角色只喂自己数据域（缩小数据域控幻觉），任一环节失败自动降级单 prompt 主链路；`--multi` 开关或配置 `multi_agent_enabled` 开启，研究员可切 `deepseek-reasoner` 深度辩论（P1-11）
- **辩论详情 + 结论 + 弃用标志**：每条预测首行显示 `🧭 结论`（融合结论=研究员多空辩论收敛结果，不展开即可见）与版本徽标（弃用标志：`🤖 多角色`=6角色完整版（默认）／`旧版单模型`=多角色版上线前旧版（已被取代）／`⚠️ 降级版`=AI生成失败规则兜底（无多角色辩论）／`⚠️ 精简版`=最小兜底，降级/精简版仅供参考）；「🧠 多角色讨论详情」折叠面板可展开看四角色结论与多空论据（标题标角色数与论据数）；AI 预测弹窗 / 历史收盘分析结合展示 / 公示行三处统一（2026-08-12）
- **卖信号口径分层**：买/卖计数只算**真实指数可交易信号**（非 `s.*`，与首页信号列表过滤口径一致）；情绪分模拟信号（`s.*` 前缀 0-100 衍生指标，非可交易标的）单独统计为「情绪买/卖」并标注"情绪分"，横幅 chip / AI 预测 / 历史收盘分析三处口径统一
- **预测把握度 confidence（0-100）**：每次预测必带把握度评分（合规风控）——主编基于多空辩论收敛结果（论据充分性/分歧度/数据支持度）输出整数 0-100 把握度 + 1 句把握度理由：高把握 70-100 / 中等 55-70 / 低把握 30-55 / 看不清 0-30，低把握时方向更倾向震荡不硬猜；规则版/最小版兜底默认 50 保前端零破坏
- **历史收盘分析结合 AI 预测**：弹窗内每日收盘分析下方并排展示对应日期 AI 预测（方向断言+把握度+四段解读+命中标记），AI 预测弹窗默认展开预测内容
- 邮件正文**白话化**：期货风向 + 公募基金解读，非模板套话

### 🤖 飞书机器人通知（2026-08-11 新增，通知分级到 3 群 + 群内提需求）
- **发送链路**：`notify.py` 新增飞书渠道（企业自建应用 `tenant_access_token` + `im/v1/messages` API），按通知类别路由到 3 群——**运维群**（SEVERE 告警 + 计划任务异常）/ **开发群**（agent 完成通知）/ **报告群**（收盘分析 + 盘中信号 + 小时级节点），`--feishu-group` 可显式覆盖，`--feishu-only` 调试单渠道
- **接收链路**：`feishu_ws_listener.py` 长连接常驻（lark-oapi WS Client + launchd KeepAlive，免公网回调），订阅 `im.message.receive_v1`，白名单群 + `需求:`/`t:` 前缀过滤后落盘 `data/feishu_requests/`，主控 cron 轮询整理进 TASKS 待办（补齐 harness 无可靠入向通知的空缺）；落盘成功后**立即秒级回执**「已收到需求…，主控 1 分钟内开始处理」（引用回复用户那条具体消息 reply_to_message_id，best-effort，发送失败不阻塞落盘）
- **邮件兜底保留**：飞书失败不阻塞邮件（best-effort），SEVERE 告警邮件始终发（防飞书故障无通知）
- 实现见 [`docs/feishu-bot-integration-plan.md`](docs/feishu-bot-integration-plan.md)，飞书开放平台能力见「参考与致敬」段

### 📱 体验与扩展
- 盘中**分时多源批量实时**（同花顺批量 + 东财 push2delay2，3 请求根治降并发，1 分钟自愈轮询机制）
- **PWA 移动端**（可安装 + 离线缓存 + iOS 安全区 + 通知面板）
- **4 主题皮肤**（default/dark/redgold/morandi），默认红金中国；皮肤弹窗卡片化（2×2 渐变预览卡 + hover 整页预览 + 当前皮肤角标 + 胶囊关闭按钮 + 5 弹窗统一进出场动画）
- **走势图轻量渲染（2026-08-12）**：首页**全部** ECharts 图表换**轻量 SVG**（外观逐项对等：网格/坐标轴/图例/平滑曲线 + 面积 + 涨跌分色 + 阈值线/买卖点信号 pin(含多信号拼色渐变)/热力图 + hover tooltip），消灭首页全部 echarts.init（~39 sparkline + 恐贪/A股情绪分/市场宽度/跨市场/腾落线/成交额与量比/新高新低 + 行业热力图 + KPI 详情弹窗 + 信号弹窗 + 分时图）提速 200-500ms；皮肤弹窗「⚡ 走势图渲染」一键切回 ECharts 完整版（localStorage 记忆，即时双向重渲染），ETF 评分弹窗近30日走势同开关
- **策略实验室** `/lab`（备买 chip 三档 + 参数优化 + 凯利回测 + 费率/收益口径客调）
- 数据挖掘方法论实战（决策树/beam search/对比集/贪心，详见「参考与致敬」）

---

## 🏗️ 系统架构

```
                    ┌─────────────────────────────────────────────────────┐
                    │                 采集层（多源互备）                  │
                    │   mootdx(TCP)  BaoStock  腾讯  东财  同花顺  申万   │
                    │   中证指数  HKEX/CCASS  CFFEX  cninfo  美指/黄金    │
                    └─────────────────────────────────────────────────────┘
                                               │  launchd 定时调度
        ┌─────────────────────────────┬───────────────────────────┬────────────────────┐
        │ 17:50 update_all 并行流水线 │ 盘中每10min intraday 快照 │ 盘后 export+deploy │
        │ (core/width/futures/stock)  │    (R2 实时,不推 main)    │  (静态 JSON 产物)  │
        └─────────────────────────────┴───────────────────────────┴────────────────────┘
                                               ▼
                    ┌─────────────────────────────────────────────────────┐
                    │           存储层（R2 / CF Static Assets）           │
                    │   全量品种/大range历史序列 → R2 桶 ssd.fx8.store    │
                    │        小状态文件 → CF Workers Static Assets        │
                    └─────────────────────────────────────────────────────┘
                                               │  git push main → CF 自动 deploy
                    ┌──────────────────────────▼──────────────────────────┐
                    │                 前端层（多端一致）                  │
                    │   主站 ss.fx8.store  CF Workers (br压缩+_headers)   │
                    │          备站 sss.sugas.site  GitHub Pages          │
                    │            备站 s.sugas.site   MaoziYun             │
                    │          dataUrl: -all/5y/3y 大文件直连 R2          │
                    └─────────────────────────────────────────────────────┘
                                               │
                    ┌──────────────────────────▼──────────────────────────┐
                    │                浏览器端（SPA + SW）                 │
                    │    原生JS + ECharts · Service Worker 版本化缓存     │
                    │        PWA · 4主题 · 分时1min自愈轮询 · 通知        │
                    └─────────────────────────────────────────────────────┘
                                               │  交易信号（可选接执行）
                    ┌──────────────────────────▼──────────────────────────┐
                    │       自动交易执行（可选 · 独立仓库 thsautoorder）    │
                    │      easytrader 二次开发 · 验证码识别 · API 队列监听  │
                    │        看板交易信号 → 自动下单（程序化需备案）        │
                    └─────────────────────────────────────────────────────┘
```

**数据流**：多源采集（防单源封禁，互备降并发）→ SQLite 主库（`sentiment.db` / `etf_national_team.db`）→
指标计算 → 静态 JSON 产物 → R2/CF 分发 → 前端渲染；小文件走 CF，大文件走 R2 直链，`manifest.json + sha256` 全程可校验。
前端展示的交易信号可接**自动交易执行**（可选，easytrader 二次开发 → [thsautoorder](https://github.com/xp13465/thsautoorder)，独立仓库）。

---

## 🛠️ 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11 + FastAPI + SQLite（`sentiment.db` / `etf_national_team.db`） |
| 采集 | mootdx（TCP 全 A 日线 16M 行）+ BaoStock（校验）+ 腾讯/东财/同花顺（互备）+ 申万/中证/HKEX/CCASS/CFFEX/cninfo |
| 前端 | 原生 JS + ECharts（分时/恐贪/评分弹窗/信号卡/策略实验室）+ Service Worker + PWA，`build_min.py` 压缩 + 版本号破缓存 |
| 存储 | Cloudflare Workers（主站）+ R2 对象存储（全量品种/大 range 历史序列）+ GitHub Pages / MaoziYun（备站） |
| AI | DeepSeek（每日速递白话生成 + 邮件白话化 + 本地 thinking 代理：官方 DeepSeek 直连 /anthropic + thinking disabled 注入，per-role 省 token，scripts/thinking_proxy.py） |
| 交易执行 | easytrader 二次开发 → [thsautoorder](https://github.com/xp13465/thsautoorder)（独立仓库）：验证码识别 / API 接口队列监听 / 可用性提升 |
| 调度 | macOS launchd：17:50 主采集并行流水线 / 盘中每 10min intraday 快照 / 盘后 export+deploy / futures/lhb/rzhb/etf-national-team/backfill/lab-auto/schedule-monitor |
| 部署 | GH Actions deploy-cf.yml + wrangler deploy（加速 20min→1-2min），push main 自动上线 |

**特点**：
- 全量免费数据源，无 API key；多源互备防单源封禁
- 指标配置驱动（`config/indicators.yaml`），增删改不动核心代码
- 双部署：动态版（FastAPI 实时查询）+ 静态版（预生成 JSON，CF Workers + R2 CDN 加速）
- 历史 10 年回溯 + 数据一致性铁律（N 展示位 / N 缓存同版同步）

---

## 🎓 参考与致敬（References & Acknowledgements）

> 本项目的很多模块站在开源社区 / 学术界 / 公开数据源的肩膀上。在此逐一致谢 —— **致敬不是贴标签，是"我真的用了，且说清用在哪"**。

### 📐 数据挖掘方法论（降亏过滤多轮挖掘）

**用途**：`策略实验室` 的凯利回测，从 **44,832 笔真实模拟交易** 中反推「系统性亏损特征组合」作为降亏过滤开关（v1→v4 四轮挖掘，最终 Greedy 组合净提升 PF 1.285→1.713，净 +149 万）。

| 方法 | 致敬来源 | 本项目用在哪 |
|---|---|---|
| **子群发现 Subgroup Discovery** | Lavrac/Flach/Kavsek《Adapting classification rule induction to subgroup discovery》(2002)；Atzmueller (2015) 综述；[pysubgroup](https://github.com/flemmerich/pysubgroup) WRAccQF | v3 找高纯度"亏损显著过代表"子群，支撑"比值>2 高纯度子群"路线 |
| **决策树 CART** | Breiman et al. (1984)；手写多路分裂（非 sklearn） | v3 路径提取 = 规则，路径亏损率 = 规则纯度 |
| **Beam Search** | 子群发现精炼启发式 (Valmarska/Lavrač/Fürnkranz 2017) | v3 子群候选搜索（depth4 beam30） |
| **对比集挖掘 Contrast Set Mining** | Webb et al.; growth rate = supp_loss/supp_gain | v4 找"亏损组显著过代表"条件集（1-4 itemset 主路线） |
| **涌现模式 / JEP** | Dong & Li (1999) Emerging Pattern | v4 识别"只出现在亏损组的模式"（盈利组 support=0） |
| **Apriori / Closed Itemset** | Agrawal & Srikant (1994) | v4 4-itemset Apriori（1502 个 ratio>3）+ 去冗余验证 |
| **贪心组合优化** | 经典贪心逐步选择 | v4 Greedy-7/15 从 930 候选产出最终 toggle 集 |
| **Walk-forward 滚动验证** | 时间序列前向验证范式 | 未来 v5 方向：t-1 年选 toggle、t 年验证，防过拟合 |
| **Decision Set 互斥规则集** | 规则集互斥设计 | 未来 v5 方向：每笔交易至多命中一条规则 |
| **PSM 倾向得分匹配** | Rosenbaum & Rubin (1983) | 未来 v5 方向：消除选择偏差、验证净效果非混淆因素所致 |
| **漂移检测 Drift Detection** | 概念漂移 (concept drift) | 未来 v5 方向：检测标志有效性随时间漂移（5 月 shift 发现雏形） |
| **4 窗口稳定性验证** | out-of-sample 验证共识 | 历轮：比值>2 + maxSh<0.60 + 逐年验证，防 5 月 shift 类过拟合 |

> 完整推导、文献清单与代码见项目内文档：
> - [`docs/kelly/mining/kelly-loss-mining-methods.md`](docs/kelly/mining/kelly-loss-mining-methods.md) — 8 种方法 Python 代码 + CrossRef 学术文献完整清单 + 推荐流程
> - [`docs/kelly/mining/kelly-mining-literature.md`](docs/kelly/mining/kelly-mining-literature.md) — 文献/方法论/方案引导速查（fresh context agent 复用）
> - [`docs/kelly/mining/kelly-loss-mining-v3.md`](docs/kelly/mining/kelly-loss-mining-v3.md) / [`-v4.md`](docs/kelly/mining/kelly-loss-mining-v4.md) — 各轮完整推导与候选清单
> - 方法论也受 **"信号过滤 = 训练分类器预测信号质量，过滤低质量信号即减亏"** 这一交易行业共识启发（Kissell《Machine Learning Techniques》; Zhang & Pinsky 策略-分类模型类比）

### 📐 组合降亏（特征选择 / 组合方法论，2026-08-11 新增）

**用途**：`策略实验室` 凯利回测的「组合降亏预设宏」——把已有降亏 toggle 打包成命名组合（年末季节/稳健核心/最大化降亏/1月调整），成员选择与组合验证复用国外特征选择/组合方法论（详见 [`docs/kelly/combo/kelly-combo-signal-research.md`](docs/kelly/combo/kelly-combo-signal-research.md) 调研 + [`docs/kelly/combo/kelly-combo-round3-verify.md`](docs/kelly/combo/kelly-combo-round3-verify.md) 数据验证 + [`docs/kelly/combo/kelly-jan-adjust-combo-verify.md`](docs/kelly/combo/kelly-jan-adjust-combo-verify.md) 1月调整元素级验证）。「1月调整」组合来自元素级重组挖掘（18,047 组合全扫描，用户"摘取要素交叉成新标志"直觉的直接产出）：5 标志要素拆解后 1 月是真空地带，1 月中旬（11-20 日）+ mid 评级为唯一新边际（比值 4.71、4 窗口全 >2、与现有标志 90% 不重叠、AI降亏过滤结构内边际 +0.3 万（2026-08-12 重跑，旧 live4 口径 +14.4 万已过时））。组合=成员 toggle 的打包宏，过滤仍走成员谓词并集（零新增过滤逻辑、幂等可叠加、组合勾选态由成员派生），满足「用户视角 N 展示位数据一致」铁律。

| 方法 | 致敬来源 | 本项目用在哪 |
|---|---|---|
| **IV 信息值 / WoE（评分卡）** | Siddiqi《Credit Risk Scorecards》(Wiley, 2006)，FICO 评分卡标准 | 比值（降亏%/损盈%）= 本项目"亏损组 vs 盈利组偏斜强度"的 WoE/IV 交易版，按比值排序选成员 |
| **mRMR 最小冗余最大相关** | Peng, Long & Ding (IEEE TPAMI, 2005) | 组合成员两两 Jaccard 重叠率 <40% 判据（低重叠=去相关互补） |
| **RFE 递归特征消除** | Guyon et al. (Machine Learning, 2002) | 组合成员逐一 drop 验证边际贡献（v4 Closed Itemset 去冗余已实现） |
| **Lasso / Elastic Net（L1 稀疏）** | Tibshirani (JRSS-B, 1996)；Zou & Hastie (JRSS-B, 2005) | 若未来做"成员加权评分"式组合，Lasso 给成员稀疏权重 |
| **特征聚类 + 多重共线性** | López de Prado《Advances in Financial Machine Learning》(Wiley, 2018) Ch.8 | 组合成员先做交易集重叠聚类（同簇只留最强代表），直接决定"进组合/排除谁"；重要性须 OOS 算、高相关特征先正交化 |
| **DSR / PBO 防过拟合度量** | Bailey & López de Prado (JPM 2014 / JCF 2017) | 1502 itemset 挖掘后组合选择的多重试验惩罚（本项目用 maxSh+4 窗口近似） |
| **多重检验校正（t>3 / FDR）** | Harvey, Liu & Zhu (RFS 2016)；Benjamini & Hochberg (JRSS-B 1995) | 成员进组合阈值比单次检验更严（4 窗口全>2 + maxSh<0.6 双门槛） |
| **alpha 组合收缩** | Kakushadze《101 Formulaic Alphas》(2016) | 标志高度相关时组合权重应收缩→组合选低相关成员 |
| **低相关因子分散组合** | Asness, Frazzini, Israel & Moskowitz (JPM 2014) | 组合跨独立经济逻辑线（11/12 月末、纯非五月、广谱 Greedy），不堆叠同逻辑标志 |
| **Walk-forward 滚动验证** | Pardo《The Evaluation and Optimization of Trading Strategies》(Wiley, 1992/2008) | 组合评估标准流程：t-1 年选成员、t 年验证（pre2025 选样/2025+ 验证两段全 >2 才稳） |
| **决策集互斥规则集** | Lakkaraju, Bach & Leskovec (KDD 2016) | 组合优先低重叠成员（决策集宽松版），现用并集幂等无害 |

### 🤖 多 Agent 协作模式（traderagent 启发）

**用途**：本项目用**多 agent 分工做开发协作**——调研 agent（只读定位根因）→ 实施 agent（写码）→
reviewer agent（独立批判性查影响面 + 回归 smoke）→ 测试 agent，配 cron 兜底轮询 + 进度文件回写，
借鉴 **traderagent 风格的多智能体团队模式**（[原版 tradingagents](https://github.com/tauricresearch/tradingagents) / [中文改版 TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN)，分析师/研究员/交易员/风控分工协作）来组织工程流水线：
- 数据产品线：采集 agent（多源互备）→ 计算 agent → 上线 agent（deploy 三站验证）
- 开发质量线：实施 → reviewer（独立 review 防改坏老功能）→ 主控逐字验收
- 复盘线：总结 agent（过错/经验沉淀）→ 复核 agent（独立复核防总结跑偏）
- 内容生产线：`每日 AI 速递` 的预测同样借鉴 **TradingAgents-CN 的多角色辩论方案**——6 个角色子 prompt（技术/资金/情绪/风控/研究员/主编）各自只注入对应数据域、独立分析后互相校验/辩驳，再由主编合成白话解读（不做交易决策角色，合规）

> 工程规范与协作机制详见 [`CLAUDE.md`](CLAUDE.md)（§2 监工 loop / §11 通知兜底 / §15 回归 / §16 agent 画像）。

### 🧠 AI 预测与解读（DeepSeek）

**用途**：`每日速递` 邮件 —— 收盘后由 [DeepSeek](https://platform.deepseek.com/) 生成 **daily_brief 白话解读**（情绪拐点 + 信号汇总 + 合规 gating），
邮件正文对 **期货风向 / 公募基金** 做白话化改写，让"机器算出来的数字"变成"人读得懂的话"。

### 🎨 顶部 SVG banner 艺术字（DeepSeek 辅助设计）

**用途**：README 顶部 `TDSIGNAL` 渐变辉光 banner（A股 · 港股 · 全球 + ◆ ONLINE ◆）——由 [DeepSeek](https://www.deepseek.com/) 设计艺术字方案、本项目做主题适配（无线电主题标签改为项目实际覆盖范围）。

### 🔁 自动交易执行（easytrader → thsautoorder）

**用途**：把看板交易信号接上真实下单执行（**可选独立模块**，不进主站点运行链路）。基于开源库
[easytrader](https://github.com/shidenggui/easytrader)（MIT，模拟操作同花顺等客户端 + miniQMT 官方接口模式）做二次开发，
产出独立仓库 [thsautoorder](https://github.com/xp13465/thsautoorder) 独立迭代。二次开发点：**验证码识别**（登录稳定性）、
**API 接口队列监听**（看板信号 → 下单指令）、**可用性提升**（客户端版本变化自愈）。
> 📦 本仓库以 **git submodule** 方式关联 thsautoorder：`easytrader_deploy/` 目录 = submodule，指向 `https://github.com/xp13465/thsautoorder`（自动跟随新仓库迭代）。**git clone 本项目需加 `--recurse-submodules`** 才会拉取该子模块；已 clone 的项目用 `git submodule update --init` 补拉。
> ⚠️ 合规：程序化交易（含低频）须备案，未备案即交易 = 违规（详见 NOTES.md 调研）。本看板只出信号不自动下单，自动执行模块独立可选。

### 📚 公开数据源致谢

本看板 100% 使用免费公开数据源，无 API key。没有这些开源项目与公开接口，就没有这个看板：

| 数据源 | 用途 | 类型 |
|---|---|---|
| [mootdx](https://github.com/mootdx/mootdx) | 全 A 股 TCP 日线（历史 10 年回溯） | 开源库 |
| [BaoStock](https://github.com/baostock) | 指数/日线校验与补采（8/10 指数 + kc50 兜底） | 开源库 |
| [akshare](https://github.com/akfamily/akshare) | 东财/新浪/腾讯行情统一接口 | 开源库 |
| [a-stock-data](https://github.com/simonlin1212/a-stock-data) | 策略实验室回测信号生成（`scripts/lab/*.py` runtime import `gen_buy_signals` / `gen_sell_signals`）+ 采集层东财防封 / 腾讯行情实现参考其 SKILL.md | 开源仓库（代码复用） |
| 腾讯行情 / 东财 push2 | 盘中分时批量实时 + 主力资金 | 公开接口 |
| 同花顺 | 概念板块/行情批量 | 公开接口 |
| 申万宏源 / 中证指数公司 | 行业分类与指数行情 | 公开数据 |
| HKEX / CCASS | 港股指数 + 北向持仓披露 | 公开数据 |
| CFFEX | 期货机构持仓 | 公开数据 |
| cninfo | 公募基金 / ETF 持有人结构 | 公开数据 |

> 数据源细节、采集时点与合规说明见 [`docs/data-sources.md`](docs/data-sources.md)。

### 🤖 飞书开放平台（lark-oapi）

**用途**：`notify.py` 飞书发送渠道 + `feishu_ws_listener.py` 长连接接收进程（企业自建应用收发一体）。

| 能力 | 致敬来源 | 本项目用在哪 |
|---|---|---|
| **飞书开放平台**（自建应用） | [飞书开放平台](https://open.feishu.cn)（中国版域名 open.feishu.cn） | 发消息 API `im/v1/messages`（tenant_access_token 鉴权）+ 长连接事件订阅 `im.message.receive_v1`；应用进 3 群按 chat_id 分组路由 |
| **lark-oapi 官方 SDK** | [lark-oapi](https://github.com/larksuite/oapi-sdk-python)（官方 Python SDK） | `feishu_ws_listener.py` 用 `lark_oapi.ws.Client`（WS 长连接，SDK 自带断线重连）收群消息，事件分发器 `EventDispatcherHandler.register_p2_im_message_receive_v1` |

> 完整实现、3 群映射与接收落盘格式见 [`docs/feishu-bot-integration-plan.md`](docs/feishu-bot-integration-plan.md)。

---

## 📊 数据开源（全量数据在独立数据仓库）

本看板**代码 MIT 开源**；每日盘后产出的**全量数据在独立数据开源仓库**
[trade-data-signal-staticdata](https://github.com/xp13465/trade-data-signal-staticdata)（数据开源门面）：

- **JSON 数据产物**（857 个文件 / 约 943MB）：情绪指数 / A股宽度 / 港股 / 全球 / 行业概念 / ETF 国家队 / 44 指数全历史 等，
  在 R2 公开桶 `https://ssd.fx8.store/` 直链下载，无鉴权、无需 API key
- **原始 SQLite 数据库**：`sentiment.db` / `etf_national_team.db` / `stock_daily.db` / `public_fund.db`
  打包 tar.gz 挂在数据仓库 GitHub [Releases](https://github.com/xp13465/trade-data-signal-staticdata/releases)
- **授权**：[CC BY 4.0](https://github.com/xp13465/trade-data-signal-staticdata/blob/main/DATA_LICENSE)，第三方声明见数据仓库 [NOTICE](https://github.com/xp13465/trade-data-signal-staticdata/blob/main/NOTICE)

**研究 / 复现 / 离线使用**时一键复原全部数据集：

```bash
git clone https://github.com/xp13465/trade-data-signal-staticdata.git
cd trade-data-signal-staticdata
bash fetch_data.sh        # 按 manifest.json 从 R2 下载全部 JSON（约 1GB，可重复跑，已下载自动跳过）
```

- 数据清单 `manifest.json`（含 `url` / `size` / `sha256` 校验）与还原脚本 `fetch_data.sh` 均在数据仓库
- 在线按需拉取单个文件（无需 clone）：`curl -o overview.json https://ssd.fx8.store/data/overview.json`
- 核心数据文件：`overview.json` 今日快照 / `sentiment-*.json` 情绪历史 / `a-stock-*.json` A股 32 指标 / `industry-*.json` 行业概念 / `etf_national_team-*.json` 国家队 ETF / `futures.json` 期货持仓 / `index/{id}-all.json` 44 指数全历史 / `intraday_snapshot.json` 盘中快照
- 字段说明与数据字典：见 [`docs/data-dictionary.md`](docs/data-dictionary.md)（字段说明）与 [`docs/data-sources.md`](docs/data-sources.md)（数据源与采集时点）

---

## 🚀 快速开始

```bash
# 1. 安装依赖（国内镜像）
python3 -m venv .venv
.venv/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# 2. 初始化数据库
.venv/bin/python -m app.db

# 3. 首次回填历史数据
.venv/bin/python -m app.backfill

# 4. 启动看板（二选一）
cd /Users/linhuichen/code/trade-data && /Users/linhuichen/code/trade/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000   # 动态版:看页面 + 调 /api/* 读 DB
# ⚠️ cwd=trade-data/ 让 app/db.py .absolute() 读最新主库(trade-data/data/sentiment.db),非 trade/ 滞后镜像
# 或纯静态:python -m http.server -d static-site --port 8000
# 浏览器打开 http://localhost:8000
```

### 定时采集（每交易日 17:50，update_all 主采集）

共 8 个 launchd 计划任务（主采集 `com.trade.sentiment.plist` + 7 辅助任务在 `~/Library/LaunchAgents/`，7/18 重构后日志在 `trade-data/data/logs/`）。

```bash
cp launchd/com.trade.sentiment.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.trade.sentiment.plist
```

或一键脚本 `bash scripts/update_all.sh`（采集 + 静态导出 + 推送部署）。

### 采集时点

- **17:50（CST）** 主采集 [`scripts/update_all.sh`](scripts/update_all.sh)：4 条并行 pipeline（core 快核心 / width 慢宽度 / futures 期货 / stock_daily 后台死端），约 31 分钟跑完，当日下午即可看到当日数据
- **09:35–15:00 盘中** 每 10 分钟跑 `intraday_snapshot` 推 `intraday_snapshot.json` 实时快照（走 R2 实时，不推 main）
- 另有 7 个辅助 launchd 任务（futures/lhb/rzhb/etf-national-team/backfill-evening/lab-auto/schedule-monitor）
- 非交易日跳过采集仅 deploy + check_signals；交易日盘中 09:30-15:30 拒跑全量 export+deploy（防覆盖 intraday 实时版）

---

## 📁 项目结构

```
app/
├── collector/          # 采集层（mootdx/baostock/腾讯/东财 多源互备 + em_get 防封）
├── compute/            # 计算层（signals 买卖点 / sentiment 情绪分 / cross 跨市场分）
├── queries.py          # 共享查询层（22 函数 DRY，main.py/export.py 共用）
├── db.py               # SQLite schema
└── main.py             # FastAPI 端点（挂载 static-site/ 到根 /，/api/* 读 DB）
static-site/            # 前端（Cloudflare Workers 部署；FastAPI 动态版挂载根 /）
config/indicators.yaml  # 指标注册表（增删改这里）
scripts/                # 采集/部署/一键更新/构建压缩脚本
launchd/                # macOS 定时任务 plist
docs/                   # 文档（数据字典/数据源/数据挖掘文献/回测分析/许可声明）
docs/kelly/             # 凯利回测专题文档子目录（2026-08-14 按主题拆分: mining挖掘/combo组合/position仓位/backtest-ai多AI回测/toggle降亏开关/analysis费率·分析）
```

**详细文档**：
- [REQUIREMENTS.md](REQUIREMENTS.md) - 需求 + 数据字典 + 公式披露
- [NOTES.md](NOTES.md) - 调研笔记 + 修复历史
- [docs/data-dictionary.md](docs/data-dictionary.md) - 数据字典（`static-site/data/` JSON 字段说明）
- [docs/data-sources.md](docs/data-sources.md) - 数据源说明 + 采集时点
- [docs/kelly/mining/kelly-loss-mining-methods.md](docs/kelly/mining/kelly-loss-mining-methods.md) - 数据挖掘方法论 + 文献（降亏过滤）
- [docs/LICENSE-data.md](docs/LICENSE-data.md) - 数据集 CC BY 4.0 授权声明

---

## 📡 监控与告警

- **schedule_monitor**：launchd 定时任务状态监控，异常自动发邮件（告警去重，15min 周期不轰炸）
- **check_data_integrity**：数据产物完整性校验（deploy 前置，关键 JSON 空值率超标即阻断上线）
- **check_r2_consistency**：本地 vs R2 一致性审计（数据一致性铁律）
- **check_universe_alignment**：凯利回测/首页AI建议「入样宇宙规则」对称校验（deploy 前置，CLAUDE.md §23.6 治理）——自动比对 overview 每信号 `_bt_in_universe` ⟺ board_etf_map 重算入样判定、候选信号类型 ⊆ 白名单（config/universe_rules.yaml buy_whitelist）、回测交易无排除类别（债类 cgb_*/情绪 s.*/商品 g.*/港股行业 hk_*/空数组 ftse100·kospi）记录、yaml 排除类别 ⟺ map 实际缺失 key，任一 FAIL 阻断上线（同 §22 数据一致性校验逻辑）
- **self_heal**：盘中保护 update_all，脚本吞异常（exit=0 假成功）自动识别
- **分时自愈轮询**：前端 1min 轮询 5 阶段自愈（超时/去重/降频/心跳/切前台清 in-flight），7x24 不卡死
- **mac 休眠根治**：pmset 工作日唤醒 + caffeinate 防跑期间休眠

---

## ⚠️ 声明

本看板仅供学习研究，**不构成投资建议**。买卖点信号为历史回测参考，胜率接近随机，不可作为独立交易依据。
数据准确性受数据源限制，请以官方披露为准。数据挖掘发现的降亏标志为统计特征，存在过拟合与漂移风险，使用前请复核 4 窗口稳定性。

## 📄 License

- **代码**：[MIT](LICENSE)（`app/` / `scripts/` / `static-site/` 的 `.py` / `.js` / `.css` / `.html` 等）
- **数据集**：[CC BY 4.0](https://github.com/xp13465/trade-data-signal-staticdata/blob/main/DATA_LICENSE)
  —— 全量数据（JSON 产物 + 原始 SQLite 数据库）授权声明在**数据开源仓库**
  [trade-data-signal-staticdata](https://github.com/xp13465/trade-data-signal-staticdata)
- **第三方声明**：见数据仓库 [NOTICE](https://github.com/xp13465/trade-data-signal-staticdata/blob/main/NOTICE)
- 简述版见 [docs/LICENSE-data.md](docs/LICENSE-data.md)

数据来源均为公开免费数据源（akshare / mootdx / BaoStock / HKEX / CCASS / 东财 / 同花顺 / 申万 / 中证指数公司 / 新浪 / 腾讯 / CFFEX / cninfo），详见 [docs/data-sources.md](docs/data-sources.md) 与上方「参考与致敬」段。

本看板仅供学习研究，**不构成投资建议**，详见上方免责声明。
