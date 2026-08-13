# 降亏挖掘 文献/方法论/方案引导沉淀

> 用途：把历轮降亏挖掘（kelly loss mining，2026-08-07~08-10 v1→v4）用到的**文献、方法论、方案引导**沉淀为速查文档，供后续 fresh context agent 直接复用（§20 快速上手机制）。
> 数据来源：`docs/kelly/mining/kelly-loss-mining-methods.md` + 历轮分析报告（v1/v2/v2.1/v3/v3-stability/v4）+ 3 份 AI 报告 + toggle 计划 2 份 + 回测费率/收益口径 2 份 + memory `kelly-loss-toggle-ratio-standard.md`。全文表格化，末尾列"与现有文档的关系"（链接，不重复正文）。
> 数据背景：数据源 `static-site/data/signal_kelly_trades.json`（33MB，44,832 笔去重，去重 key `(signal_date, index_id, signal, buy_date, etf_code, sell_date, sell_reason, mode)`），基准 PF≈1.285，净 ≈ +215.9 万。

---

## ① 文献 / 著作清单

### 学术文献（CrossRef，来源：`kelly-loss-mining-methods.md` §9）

| 文献 | 作者/来源 | 核心方法 | 哪一轮用到 | 怎么用 | 效果 |
|------|-----------|----------|------------|--------|------|
| Adapting classification rule induction to subgroup discovery | Lavrac, Flach, Kavsek (2002)，DOI:10.1109/icdm.2002.1183912 | 子群发现（subgroup discovery）经典论文：把分类规则归纳适配到子群发现 | v3（手写 CART + beam search 的方法论基础） | 用 `pysubgroup` 的 WRAccQF 质量函数找高纯度子群（亏损率显著高于整体） | 支撑"比值>2 高纯度子群"发现路线，v3 找到 buy_weekday 维度（比值 10.06） |
| Refinement and selection heuristics in subgroup discovery and classification rule learning | Valmarska, Lavrač, Fürnkranz (2017)，DOI:10.1016/j.eswa.2017.03.041 | 子群发现的精炼与选择启发式 | v3 | 子群候选剪枝/选择策略参考 | 支撑 beam search 的 beam width 与候选淘汰设计 |
| Subgroup discovery（综述） | Atzmueller (2015)，WIREs Data Min. Knowl. Discov. | 子群发现综述 | v3 | 方法全景参考 | 确认子群发现为"找差异化亏损共性"的标准范式 |
| An overview on subgroup discovery: foundations and applications | Herrera et al. (2011)，Knowl. Inf. Syst. | 子群发现基础与应用综述 | v3 | 方法全景参考 | 同上 |
| The Application of Machine Learning to Algorithmic Trading in Financial Markets | Feng，DOI:10.5220/0013264200004568 | ML 用于算法交易的一般框架 | methods 调研（历轮背景） | 算法交易 ML 应用框架参考 | 方法选型背景 |
| Comparing algorithmic trading strategies by analogies to machine learning | Zhang & Pinsky，DOI:10.1177/21576203251360571 | 技术分析交易策略类比为 ML，历史价格模式预测未来 | methods 调研（历轮背景） | 策略=分类模型视角参考 | 把"降亏标志"理解为"亏损 vs 盈利分类器" |
| Multi-Timeframe Signal Confirmation in Algorithmic Cryptocurrency Trading | Goswami，DOI:10.2139/ssrn.6683818 | 短时间框架信号多为噪声，需多时间框架确认 | v3（与"降亏标志=过滤噪声信号"思路一致） | 过滤低质量信号=减亏 | 支撑"降亏标志"作为信号过滤器的定位 |
| Machine Learning Techniques | Kissell，DOI:10.1016/b978-0-12-815630-8.00009-0 | ML 技术在交易中的系统应用 | methods 调研（历轮背景） | ML 技术交易应用参考 | 方法选型背景 |

### 行业实践要点（综合文献共识，来源：methods §9 末段）

| 要点 | 与降亏挖掘的对应 |
|------|-------------------|
| 亏损归因（attribution analysis）拆解亏损来源（市场/策略/执行因子） | 本任务 = 按特征分组统计各组盈亏，找"系统性亏损特征组合"（本质就是子群发现） |
| 信号过滤：用分类器预测信号质量（盈利 vs 亏损），过滤低质量信号=减亏 | 等价于本任务的"降亏标志"（把某特征组合的交易从策略里排除） |
| 过拟合警惕：历史交易上找到的标志可能只对历史有效，需 out-of-sample 验证 | 历轮用 **4 窗口稳定性验证**（v3-stability）+ maxSh/neg 年占比判断过拟合 |

---

## ② 挖掘方法论清单

### 已落地方法（按历轮顺序）

| 方法 | 定义 | 在哪一轮用 | 落地方式 | 关键结果 |
|------|------|-----------|----------|----------|
| 穷举模拟（21 组） | 对候选 toggle 逐一重跑 backtest 模拟 | v1 | 21 组模拟对比 | 排除 buy_aux 减亏 37% 增收 10%；MA60+排除 aux 减亏 64% 最优；止损反效果（54% 误杀） |
| 13 维度穷举 + 31 组合搜索 | 单维穷举后做组合搜索 | v2 | 维度穷举 + 组合搜索 | 排除 3+5 月（+27%）；v1 交叉验证通过（净保留 98%/减亏 64%） |
| 差异化视角 over_rep | over_rep = 亏损占比/盈利占比，>1 表示亏损过代表 | v2.1（43,656 笔全 6 模式去重） | 差异化共性 + 大亏(≥3%)特征 + 交叉标志 + 评级逐年验证 | "排除 3+5 月"被低估（单条件净影响最高 +527,996，比值 2.11）；排除 low 评级破坏性（净 -810,319） |
| 手写 CART 决策树（基尼多路分裂 depth4） | 决策树路径提取：路径=规则，路径亏损率=规则纯度 | v3 | 手写实现（非 sklearn，多路分裂 depth4） | 全特征可泛化；找到 buy_weekday 维度 |
| beam search（depth4 beam30） | 子群发现的启发式搜索 | v3 | pysubgroup / 手写 beam | 子群候选探索 |
| 2-3 特征交叉穷举 | 多特征组合穷举找高纯度子群 | v3 | 交叉枚举 + 跨年稳定性 | **比值 10.06（N1：3月+周三+高价，7/7 全亏）**；R7/R8/R10 组合 |
| 4 窗口稳定性验证（y1/y3/y10/all） | 用数据自带 period_cutoffs 在 4 窗口验证比值>2 | v3-stability | 9 候选全通过 4 窗口>2 | 5 月 shift（2021-2023 盈/2024-2026 亏）机制确认；判定标准 §4.1 |
| 对比集挖掘（Contrast Set Mining，growth rate = supp_loss/supp_gain） | 找"亏损组显著过代表"的条件集 | v4 | 1/2/3/4-itemset | v4 主路线 |
| 涌现模式 / JEP（Emerging Pattern，ratio=999 当盈利组 support=0） | 只出现在亏损组的模式 | v4 | 盈利组 support=0 识别 | 识别 V4-A/V4-F 等 |
| 4-itemset Apriori | 从 3-itemset ratio>2 扩展到 4 项 | v4 | Apriori | 1502 个 ratio>3（严格筛选 n≥100 + 4 窗口>2 + maxSh<0.65） |
| Closed Itemset 去冗余 | 逐一 drop 条件验证是否冗余（覆盖-比值 tradeoff） | v4 | 8 个 top 标志全部验证 | 报告同时给原版+简化版 |
| 贪心组合优化（Greedy-7/10/15） | 930 候选，15 步，约束 ratio>3 & sacr<10% | v4 | 贪心逐步加入 | **Greedy-7（比值 3.15/净 +100.7 万/PF 1.540）/ Greedy-15（净 +149 万/PF 1.713）**，761 新标志 |
| 特征等价去重 | signal=sig_dim、etf_dim=track_tier 验证去冗余 | v4 | 等价验证 | 降特征冗余 |
| 跨年稳定性 | 标志在各年表现是否持续 | v3/v4 | 逐年验证（含 5 月 shift 发现） | 结构性 vs 偶然判断依据 |

### 辅助方法（methods 调研未主用，历轮作验证/解释备选）

| 方法 | 定义 | 落地方式 | 适用评估 |
|------|------|----------|----------|
| 子群发现（pysubgroup WRAccQF） | 找高纯度子群的标准库方法 | v3 主用（WRAccQF 质量函数，constraints 防极小子群） | ★★★★★ 最推荐 |
| 决策树路径提取（sklearn） | 训练决策树后提取规则+亏损率 | v3 主用（手写版等价） | ★★★★☆ 次推荐 |
| 关联规则挖掘（mlxtend fpgrowth） | one-hot 后挖频繁项集，lift=比值 | v3 用 2-itemset；v4 用 4-itemset Apriori | ★★★★☆ 推荐 |
| 随机森林特征重要性（MDI/排列） | 特征重要性排序 | 辅助（未主用） | ★★★☆☆ |
| 聚类（K-means/DBSCAN） | 亏损交易聚类看共性 | 未主用 | ★★☆☆☆ 探索性 |
| 特征选择（互信息/卡方/RFE/RFECV） | 前置降维 | 未主用 | ★★★☆☆ 前置 |
| 不平衡分类（class_weight/SMOTE/SMOTENC） | 处理亏损:盈利≈1:1 的平衡问题 | 未主用 | ★★★☆☆ 调优 |
| SHAP（TreeExplainer） | 验证+解释降亏标志合理性 | 未主用（验证工具） | ★★★☆☆ 辅助 |

### 第3轮后新引入 / 未来方向（任务指定方法，历轮文档未落地）

| 方法 | 定义 | 状态 | 来源 |
|------|------|------|------|
| Walk-forward 滚动验证 | 按年滚动，用 t-1 年数据选 toggle，t 年验证，模拟真实前向使用 | 未落地（v4 §8 未来方向 #2；v3 §7.3 已承认"无前向 walk-forward 验证"局限） | kelly-loss-mining-v4.md §8 |
| Decision set 互斥规则集 | 规则集内互斥（每笔交易至多命中一条），避免多规则重叠覆盖 | 未落地（v5 可选方向） | 任务指定，历轮文档未实施 |
| PSM 倾向得分匹配 | 构造对照组消除选择偏差，验证"排除该组交易"的净效果非混淆因素所致 | 未落地（v5 可选方向） | 任务指定，历轮文档未实施 |
| 漂移检测（drift detection） | 检测标志有效性随时间漂移（如 5 月 shift 的正式化） | 未落地（v5 可选方向；v3-stability 的 5 月 shift 发现是雏形） | 任务指定，历轮文档未实施 |
| NSGA-II 多目标优化 | 贪心只优化净影响，NSGA-II 同时优化比值+覆盖+稳定性，产出 Pareto 前沿 | 未落地（v4 §8 未来方向 #1） | kelly-loss-mining-v4.md §8 |

---

## ③ 用户推荐学习站点（2 个）

| 站点名 | URL | 用途 | 在项目哪里借鉴 |
|--------|-----|------|---------------|
| TradingAgents（原版） | <https://github.com/tauricresearch/tradingagents> | 多 agent 交易系统实现逻辑，供借鉴「多 agent 分析架构」 | README「参考与致敬」→「🤖 多 Agent 协作模式（traderagent 启发）」段 |
| TradingAgents-CN（中文改版） | <https://github.com/hsliuping/TradingAgents-CN> | 除实现逻辑外更多国内可落地实施，供借鉴「国内 A 股落地做法」 | README「参考与致敬」→「🤖 多 Agent 协作模式（traderagent 启发）」段 |

---

## ④ 方案引导流程（防盲区，最重要）

> 核心一句话：历轮"再来一次"挖新降亏标志时，**先读前几轮报告避免重复，再识别数据维度盲区（尤其新增字段从未挖过），换方法换数据源不轻断"不可改善"，候选用比值口径>2 过滤，回测验证产出数据报告供用户选**。

### 降亏挖掘任务的标准做对步骤

1. **先读前几轮报告 + 现有 toggle 口径**（防重复、防口径漂移）：
   - 读 v1→v4 全部报告（含 v2.1）+ `toggle-plan`/`toggle-v2-plan`（现有 toggle 口径）+ memory `kelly-loss-toggle-ratio-standard.md`（比值>2 才满意）
   - 确认已挖过哪些维度/组合/方法（v3 §7.4 / v4 §7.4 有"已验证方法清单"自证），避免重复劳动
2. **识别数据维度盲区（历轮最大发现的来源）**：
   - 对比"数据源字段列表" vs "历轮实际挖过的字段"——如 v3/v4 用 19 字段版无 `market_state`，部署版（20 字段）已注入但**从未挖过** → 第 3 轮最大发现
   - 每轮先列出数据源全部字段，标注每个字段是否已被挖掘覆盖；未覆盖字段 = 优先挖掘目标
3. **换方法换数据源，不轻断"不可改善"**：
   - 一个算法/数据源挖不出 ≠ 没有标志。v3 教训：同花顺（第三方平台）能搜到当前算法匹配不到的 ETF；调研"无/0/不可改善"类结论必须换方法/换数据源/换关联维度（持仓重叠 vs 成分重叠）验证后再下结论
4. **候选清单 + 比值口径 >2 过滤**：
   - 比值 = 降亏% / 损盈%（= Lift - 1，子群亏损率/整体亏损率 - 1），**>2 满意，>3 更佳**；hoverpop 显示减亏/损盈/比值 3 项
   - 低比值保留备选迭代淘汰，不直接丢弃；排除低评级（破坏性 -810k）这类"砍牛利润"的禁止
5. **回测验证 + 稳定性校验**：
   - 候选跑 4 窗口稳定性（y1/y3/y10/all），判断标准：比值>2 + maxSh<0.60 + neg 年占比 + 逐年表现（防 5 月 shift 类过拟合）
   - 净影响必须为正（排除亏损额 > 排除盈利额），否则是破坏性标志
6. **产出数据报告供用户选**（参数/标志候选不硬选）：
   - 报告列候选标志表格（降亏%/损盈%/比值/净影响/逐年稳定性/推荐度），用户 veto/增删，不替用户硬选

### 历轮发现速查（避免重复挖已发现物）

| 已发现 | 结论 | 出处 |
|--------|------|------|
| 排除 buy_aux（辅关注） | 减亏 37% 增收 10%；唯一净负信号类型，确认合理 | v1 / v2.1 |
| MA60 + 排除 aux | 减亏 64% 最优（v1）；全模式净负 -148,749（v2.1） | v1 / v2.1 |
| 止损（止盈型） | 反效果（54% 误杀） | v1 |
| 排除 3+5 月 | 单条件净影响最高 +527,996，比值 2.11；有 5 月 shift 过拟合风险，作可选 toggle | v2 / v2.1 / v3-stability |
| 排除 low 评级 | 破坏性净 -810,319（砍牛市利润），禁止 | v2.1 |
| 3月+周三+高价 | 比值 10.06，7/7 全亏（buy_weekday 维度） | v3 |
| Greedy-7 / Greedy-15 组合 | 比值 3.15/PF 1.540 净 +100.7 万；PF 1.713 净 +149 万 | v4 |

---

## 与现有文档的关系（链接，不重复正文）

- `docs/kelly/mining/kelly-loss-mining-methods.md` — 8 种方法的详细 Python 代码 + CrossRef 学术文献完整清单（§9）+ 推荐实施流程（Step 1-5）。**本文献清单/methods 部分均出自此文，代码细节请看原文**
- `docs/kelly/mining/kelly-loss-reduction-analysis.md`（v1）/ `-v2.md`（v2） — 21 组穷举模拟 / 13 维度+31 组合搜索结果，方法论的 v1/v2 落地
- `docs/kelly/mining/kelly-loss-trades-mining.md`（v2.1） — over_rep 差异化视角 + 43,656 笔全模式去重，评级逐年验证
- `docs/kelly/mining/kelly-loss-mining-v3.md` / `-v3-stability.md` / `-v4.md` — CART/beam/交叉（v3）、4 窗口稳定性（v3-stability）、对比集/JEP/贪心（v4）的完整推导与候选清单
- `docs/kelly/toggle/kelly-loss-reduction-toggle-plan.md` / `-toggle-v2-plan.md` — 现有 toggle 口径（后端注入 market_state / 4 toggle 计划），实施时读原文
- `docs/kelly/backtest-ai/kelly-backtest-comparison.md` / `-comprehensive-review.md` / `-deepseek-review.md` — 双 AI 对候选的标志/组合评审（F vs A 模式分歧等），决策参考
- `docs/kelly/analysis/kelly-fee-adjust-sim-eval.md` / `-return-linear-analysis.md` — 回测费率客调 / 收益口径（return_pct_max_holding 是唯一随窗口累积指标），回测口径定义参考
- memory `kelly-loss-toggle-ratio-standard.md` — 比值>2 标准 + hoverpop 3 项显示，本项目硬口径
- 关联规范：CLAUDE.md §18（降亏/数据挖掘教训）、§21（算法改动同步公示文案）、§22（数据一致性铁律）、§20（快速上手机制）
