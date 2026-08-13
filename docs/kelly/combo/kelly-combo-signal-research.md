# 组合降亏标志：国外特征选择/组合方法论调研 + 科学实施方案

> 生成日期：2026-08-11 ｜ 只读调研（不改代码） ｜ 数据源：`static-site/data/signal_kelly_trades.json`（部署版 21 字段，66,591 笔 = 7399 基笔 × 9 模式）
> 上游：`docs/kelly/mining/kelly-loss-mining-v4.md` / `docs/kelly/mining/kelly-v4-detail.md` / `docs/kelly/mining/kelly-loss-round3-verify.md` / `docs/kelly/backtest-ai/kelly-backtest-comprehensive-review.md` / `docs/kelly/backtest-ai/kelly-backtest-deepseek-review.md` / `docs/kelly/backtest-ai/kelly-backtest-comparison.md` / `docs/kelly/mining/kelly-mining-literature.md` / 前端 `static-site/lab.js` L7349-7464（`_kellyPassesFadeFilters`）
> 任务来源：用户要求"最终缓解=组合使用的推荐环节"——把现有各种标志打包组合成「组合降亏标志」；UI 上组合标志也是多选框，点击组合→顶部对应单个降亏标志也打勾。用户两次强调：先调研完再实施，参考国外从业者特征选择/组合做法，不靠人工拍脑袋。
> 说明：本环境网络受限（WebSearch 空结果 / WebFetch 域名验证被拒，6 次搜索 + 3 次抓取均失败），故下文方法/文献/来源均来自既有领域知识（各方法为被广泛引用的经典著作与论文，来源已精确到作者/年份/出处，供后续人工核对）；本地项目文档已完整阅读，落地部分以本地数据为准。

---

## 0. 摘要（核心结论先讲）

1. **组合降亏标志的最科学形式 = 「预设宏 preset/macro」（UI 层聚合开关），不是新增独立过滤谓词。** 因为当前过滤模型已是"排除谓词的并集"（一个交易被任一激活 toggle 排除即剔除，`_kellyPassesFadeFilters` L7349-7464），组合若实现为"勾选一组成员 toggle"，天然幂等、无重复过滤、单一事实来源（`state.labSigKellyFilters` 只有成员开关，组合状态是派生的），且与 §22 数据一致性铁律兼容。
2. **选哪些标志进组合、排除哪些，已有本项目自己的科学口径兜底**：round3 已用「叠加边际」验证 A1/A2/A3 边际=0（被现有 toggle 覆盖）、excludeRatingLow/marketTiming 净破坏、N5/N6 单年主导过拟合。组合成员选择应复用这套口径 + 国外方法论补两块：**成员两两低重叠（去相关）** + **成员有独立经济逻辑线**。
3. **组合整体必须单独回测**（成员并集口径），不能靠成员指标加和；组合整体过 4 窗口稳定性 + maxSh + 逐年验证 + 叠加边际（round3 §5 口径全复用）。
4. **推荐 5 个命名组合**（稳健核心 / 5月系管理 / 年末季节 / 年初+周中 / 最大化降亏），成员与理由见 §5.2，全部基于现有已上线 toggle 的已验证指标。
5. **防过拟合补强**：多重检验校正（1502 个 itemset 挖掘对应的 Harvey 阈值）、walk-forward 滚动验证（t-1 选成员/t 年验证）、成员熔断（组合内 ⚠️ 监控成员透出，子集转盈自动提示移除）。

---

## Part I. 调研方法论清单（方法 → 来源 → 适用）

### A. 特征选择 Feature Selection（国外主流方法论 + 交易领域实践）

#### A.1 Filter 过滤式（先于模型，按统计量排序特征）

| 方法 | 来源 | 核心思想 | 适用本项目 |
|------|------|---------|-----------|
| 方差阈值 variance threshold | 通用 ML 教科书（Kuhn & Johnson 2013《Applied Predictive Modeling》Wiley） | 去除几乎不变的特征 | 对本项目弱（标志是组合谓词，非单维特征） |
| 相关性矩阵 / 多重共线性（Pearson/Spearman、VIF） | 通用计量（Greene 2018《Econometric Analysis》Pearson） | 高相关特征冗余，去重或合并 | **核心适用**：组合内成员交易集重叠（Jaccard）= 相关性的直接代理，低重叠=互补 |
| 互信息 mutual information | Peng, Long & Ding 2005（IEEE TPAMI）「mRMR: max-relevance min-redundancy」 | 非线性依赖度量 + 最小冗余 | 辅助：成员与"亏损标签"的互信息排序 |
| 卡方 chi-square | 通用分类特征选择 | 分类特征与目标独立性检验 | 辅助（标志=类别谓词） |
| **IV 信息值 / WoE** | Siddiqi 2006《Credit Risk Scorecards》Wiley（银行业/信用卡评分标准方法）；FICO 评分卡体系 | 二分类目标下特征强度：IV<0.02 无用 / 0.02-0.1 弱 / 0.1-0.3 中 / 0.3-0.5 强 / >0.5 可疑 | **最强类比**：本项目「比值=降亏%/损盈%」本质就是 WoE/IV 思想的交易版（亏损组 vs 盈利组的偏斜强度），国外银行界选特征就是按 IV 排序，本项目按比值排序同理 |

#### A.2 Wrapper 包装式（以模型表现评估特征子集）

| 方法 | 来源 | 核心思想 | 适用本项目 |
|------|------|---------|-----------|
| 前向/后向逐步选择 stepwise | 经典统计（Efroymson 1960；Hocking 1976） | 逐个加/删特征，模型表现为准 | **本项目 v4 贪心组合优化正是前向逐步的等价物**（930 候选，每步选净影响最大的 toggle），方法论一致 |
| 递归特征消除 RFE/RFECV | Guyon et al. 2002（Machine Learning）「Gene selection for cancer classification using SVM」 | 反复训练→删最不重要特征→交叉验证选子集大小 | 辅助：RFE 视角=组合成员逐一 drop 验证是否仍贡献（本项目 v4 Closed Itemset 去冗余已实现 drop 验证） |
| 穷举/贪心搜索 | 经典 wrapper | 特征子集空间搜索 | 已用（v4 贪心 Greedy-7/10/15） |

#### A.3 Embedded 嵌入式（模型自带重要性）

| 方法 | 来源 | 核心思想 | 适用本项目 |
|------|------|---------|-----------|
| Lasso / Elastic Net（L1 稀疏） | Tibshirani 1996（JRSS-B）；Zou & Hastie 2005 | 系数收缩到零=自动选特征 | 辅助：若做"成员加权评分"式组合，Lasso 可给成员稀疏权重 |
| Ridge（L2） | Hoerl & Kennard 1970 | 收缩但不清零，处理共线 | 辅助 |
| 树特征重要性（Gini/MDI） | Breiman 2001（Random Forests, Machine Learning） | 分裂减杂质的累积 | 项目 v3 已用手写 CART |
| **随机森林排列重要性（MDA）+ 方差** | Breiman 2001；López de Prado 2018 细化 | 打乱特征后 OOB 准确率下降量=重要性，带标准差 | 辅助：给成员做"排列重要性"验证（比 MDI 更抗偏） |
| Boruta | Kursa & Rudnicki 2010（Journal of Statistical Software） | 影子特征对比，判定"真正重要" | 辅助：判定哪些标志是噪声 |

#### A.4 交易领域专用（López de Prado 框架 + 过拟合度量）

| 方法 | 来源 | 核心思想 | 适用本项目 |
|------|------|---------|-----------|
| **MDI / MDA / SFI 特征重要性** | López de Prado 2018《Advances in Financial Machine Learning》Wiley，Ch.8「Feature Importance」 | MDI=Gini 重要性（有偏，偏爱高基数特征）；MDA=OOB 排列重要性（含 std err，更抗偏）；SFI=单特征分类精度 | 适用：把每个降亏标志当作"特征"，用 MDA 在亏损标签上验证其真实贡献；**核心洞察：重要性必须在 OOS 上算，且高相关特征会扭曲重要性 → 先正交化/去相关** |
| **多重共线性处理：特征聚类** | López de Prado 2018 Ch.8（层次聚类 + 每簇选代表/组合成"正交主特征"） | 相关特征会夸大/掩盖重要性，聚类后每簇取一代表 | **核心适用**：组合成员先做交易集重叠聚类，同簇只留最强代表 → 直接决定"哪些标志进组合、排除哪些" |
| **元标注 meta-labeling** | López de Prado 2018 Ch.10 | 二级模型决定是否执行一级模型信号（过滤） | 概念同构：本项目降亏标志=给主信号做"该不该下注"的二级过滤器 |
| **防过拟合度量：DSR / PBO / MinBTL / CSCV** | Bailey & López de Prado 2014「The Deflated Sharpe Ratio」（Journal of Portfolio Management）；Bailey, Borwein, López de Prado & Zhu 2017「The Probability of Backtest Overfitting」（Journal of Computational Finance） | 多次试验后 Sharpe 需折价（deflated）；PBO=回测过拟合概率（CSCV 组合对称交叉验证） | **核心适用**：挖掘了 1502 个 itemset，组合选择必须考虑多重试验惩罚；本项目已用 maxSh+4 窗口近似，正式化可用 PBO/CSCV |
| **净化+禁运交叉验证 purged & embargoed CV / CPCV** | López de Prado 2018 Ch.7 与论文 | 时序数据防信息泄漏（标签重叠）的 K 折 | 适用：组合 walk-forward 验证时防泄漏 |
| **多重检验校正（因子显著阈 t>3）** | Harvey, Liu & Zhu 2016（Review of Financial Studies）「…and the Cross-Section of Expected Returns」；Benjamini & Hochberg 1995（JRSS-B）FDR | 几千个因子被检验时，t>2 远不够，需 t>3 或 FDR 校正 | **核心适用**：1502 itemset 挖掘后，组合成员的比值阈值应比单次检验更严（对应 >2 之上再加样本/窗口约束） |
| **树模型不天然胜线性 + 收缩正则** | Israel, Kelly & Moskowitz 2020（Journal of Investment Management）「Can Machines 'Learn' Finance?」；Gu, Kelly & Xiu 2020（Review of Financial Studies）「Empirical Asset Pricing via Machine Learning」 | 金融里树/非线性模型若无正则并不稳胜线性收缩模型；验证纪律比模型复杂更重要 | 警示：组合别为了"复杂"而复杂，并集过滤 + 严格验证即可；简单可解释是优势 |

### B. 特征组合 Feature Combination（主流方法 + 交易实践）

#### B.1 交互 / 组合特征与规则组合

| 方法 | 来源 | 核心思想 | 适用本项目 |
|------|------|---------|-----------|
| 交叉项/多项式特征 | 通用 ML（sklearn PolynomialFeatures） | x1×x2 显式编码交互 | 已用（标志=多条件 AND 交叉，如 3月+周三+高价） |
| 逻辑规则 AND/OR/NOT | 规则学习（决策树/关联规则经典） | AND=更精准更窄（precision↑/coverage↓）；OR=更广覆盖；NOT=取反 | **核心**：本项目标志=AND（多条件必须同时满足）；组合=OR（任一成员谓词命中即排除）。AND 是"外科手术"，OR 是"广谱" |
| 子群发现 subgroup discovery | Lavrac, Flach & Kavsek 2002；Atzmueller 2015（已在 project 文献库） | 规则=高纯度子群（本项目比值=纯度度量） | 已用（v3 决策树路径提取） |
| **决策集 decision set（互斥规则集）** | Lakkaraju, Bach & Leskovec 2016（KDD）「Interpretable Decision Sets」 | 规则集内互斥（每样本至多命中一条），避免重复覆盖/冗余 | **核心适用**：组合若出现"成员重叠→同一交易被多条规则命中"，可解释性差；本项目现用并集幂等无害，但组合设计仍应优先低重叠成员（决策集思想的宽松版） |
| Closed itemset 去冗余 | Pasquier et al. 1999；Agrawal 关联规则 | 去掉冗余条件后 support 不变 | 已用（v4 Closed Itemset 简化） |

#### B.2 加权评分合成与降维

| 方法 | 来源 | 核心思想 | 适用本项目 |
|------|------|---------|-----------|
| 等权合成 | 朴素基准 | 各信号标准化后平均 | 不适用（本项目是二值过滤非评分） |
| **IC 加权 / 最优权重** | Grinold & Kahn 2000《Active Portfolio Management》McGraw-Hill；Fundamental Law: IR=IC·√Breadth | 信号权重 ∝ IC；考虑信号间协方差：最优权重 w ∝ Σ⁻¹·IC | 概念参考：成员若转成"评分"，权重应反比于成员重叠（协方差逆），不是等权 |
| **alpha 组合收缩** | Kakushadze 2016「101 Formulaic Alphas」（Wilmott / arXiv:1601.00991） | N 个相关 alpha 组合时权重收缩：w_i/(1-ρN)（ρ=平均相关性），防过拟合 | **核心适用**：本项目标志高度相关（都含季节+信号线），组合时"相关性越高、权重越应收缩"的直觉 → 组合应选低相关成员，或用重叠率惩罚 |
| 降维 PCA/因子分析 | Jolliffe；Barra/MSCI 风险模型（Rosenberg 1974） | 少数正交因子替代众多相关变量 | 不适用（过滤语义非评分语义），但"正交化去冗余"思想适用 |
| 特征聚类+主特征 | López de Prado 2018 Ch.8 | 见 A.4 | 组合选择的核心依据 |

#### B.3 集成与交易信号组合实践

| 方法 | 来源 | 核心思想 | 适用本项目 |
|------|------|---------|-----------|
| Bagging / Boosting / Stacking | Breiman 1996；Friedman 2001；Wolpert 1992 | 多模型集成，方差/偏差分解 | 不直接适用（本项目是规则过滤非模型） |
| **多因子模型（Fama-French）** | Fama & French 1993/2015（JFE）；Barra 风格因子 | 因子=资产定价的独立风险溢价；因子选择看 t 值显著性+经济解释 | 概念同构：组合成员=独立"亏损因子"，进组合的标准=显著+可解释+低相关 |
| **信号投票 / 排名聚合** | 多信号系统实践（rank average / Borda count） | 多信号排序/投票合成 | 可选演进：若未来从"过滤"走向"评分降仓"，可用排名聚合 |
| **条件分层（double sort / 先过滤再打分）** | 因子投资实践（Fama-French 双排序构造 SMB/HML）；Ang 2014《Asset Management: A Systematic Approach to Factor Investing》Oxford | 先按一个因子分层再按另一因子分组 | **同构**：当前模型=先"降亏过滤"（排除坏交易）再对剩余打分，正是条件分层 |
| **低相关因子分散组合** | Asness, Frazzini, Israel & Moskowitz 2014「Fact, Fiction, and Momentum Investing」（JPM） | 低相关因子（价值+动量）组合→分散化提升稳健 | **核心适用**：组合应跨"独立经济逻辑线"（5月系/11月系/3月系/1月系/12月），而非堆叠同逻辑标志 |

#### B.4 验证 / 防过拟合（组合层面）

| 方法 | 来源 | 核心思想 | 适用本项目 |
|------|------|---------|-----------|
| **Walk-forward 滚动验证** | Pardo 1992/2008《The Evaluation and Optimization of Trading Strategies》Wiley（交易系统验证经典） | 用 t-1 段选参数/t 段验证，模拟真实前向 | **核心适用**：组合成员选择必须 walk-forward（t-1 选、t 验），防"全历史挖掘的成员在未来失效" |
| 时间切分样本外 | 通用 ML | 前段训练/后段测试 | 适用（可作为 walk-forward 的简化版） |
| 逐年稳定性 + 单年主导 | 本项目 v3-stability（maxSh / neg 年占比） | 已有 | 已用，组合整体复用 |
| 熔断 / 自动停用 | DeepSeek 建议（`kelly-backtest-deepseek-review.md` §5-5） | 连续失效自动关闭 | 适用：组合内 ⚠️ 监控成员子集转盈 → 提示移除 |

---

## Part II. 组合降亏标志实施方案

### 1. 组合逻辑（核心设计：组合=预设宏，不是新谓词）

**当前过滤模型**（`lab.js` L7349-7464 `_kellyPassesFadeFilters`）：
- 语义 = **排除谓词的并集**：一个交易被"任一激活 toggle 的谓词命中"即剔除；保留条件 = 所有激活 toggle 的保留条件都满足（AND）。
- 已有两类 toggle：**原子**（N1、V4-B、excludeAux 等单谓词）+ **复合**（R8/R7/R10/Greedy-7/10/15 = 多个子谓词的并集，一个 checkbox）。purpose-notes.js 已注明"Greedy-7/10/15 嵌套组合（15⊃10⊃7），单 checkbox=并集 OR 过滤，同时开启幂等无害"。

**结论**：组合降亏标志应实现为**第三层——命名预设宏（preset macro）**：
- 组合 = 一组成员 toggle 的命名打包；点击组合 → 勾选/取消其全部成员 toggle。
- **过滤逻辑零改动**：组合不引入新的独立谓词，过滤仍走成员 toggle 各自的谓词并集。
- **幂等无重复**：因为过滤是并集语义，成员重叠（如同一交易命中两条成员规则）也不会重复过滤或改变结果（Greedy-15 注释已验证"同时开启幂等无害"）。
- **单一事实来源**：`state.labSigKellyFilters` 只有成员开关；组合勾选状态是派生的（组合 checked ⟺ 全成员 checked；半选 = 部分成员 checked）。不新增第三份过滤状态 → 满足 §22 数据一致性铁律、无状态漂移。
- **与用户需求精确匹配**：用户明确"UI 上组合标志也是多选框，点击组合→顶部对应单个降亏标志也打勾"= 宏语义。

**对比过的替代方案（不采用及理由）**：
- 方案 B：组合 = 新的独立复合谓词（仿 Greedy-7）。缺点：与成员 toggle 存在重复定义（同一过滤条件两处实现，双份逻辑=双份维护+口径漂移风险），且"点击组合→成员打勾"就变成纯视觉联动而非真实机制，可解释性差。Greedy-7/10/15 这类"挖掘产生的原子组合"保持现状即可，不纳入宏体系混用。
- 方案 C：组合 = 加权评分（把标志转成连续分再加权）。缺点：与现有二值过滤语义冲突，需重写过滤/展示/口径，超出"最终缓解=组合使用推荐"范围；方法论上 IC 加权/Kakushadze 收缩虽经典，但本场景是"排除坏交易"而非"排序下注"，并集过滤已够且更可解释（B.2 已判不适用）。

### 2. 组合成员选择（哪些进组合、排除哪些）

**先排除（依据 round3-verify + comprehensive/deepseek review 已有口径）**：

| 排除对象 | 理由 | 出处 |
|----------|------|------|
| excludeRatingLow（排除低评级） | 净影响 -81.0 万，最大破坏（砍周期性盈利群体） | comprehensive §4.1 ⑮ / deepseek §4 |
| marketTiming（MA60 大盘择时） | 净影响 -14.9 万（降亏强但损盈更多，全模式净负） | comprehensive §4.1 ⑭ |
| A1/A2（熊市+周二/周一+special）、A3（03月中旬+special） | 叠加边际 = 0，被 marketTiming/excludeMonth 完全覆盖（严格子集），加了不新增任何过滤 | round3 §2.1 边际列 |
| N5（5月+极低价）、N6（mid+5月） | 2026 年占全历史净影响 66%/71%，单年主导过拟合；只可"附监控"进激进档 | round3 / deepseek §4 ⑦⑧ |
| V4-F（6月 n=60）、V4-M（9月 3年数据）、V4-G（全球 近年才转亏）、V4-K（1月 有子集盈利年） | 样本不足/近年才显现，只可"附监控"进激进档，不进稳健组合 | v4-detail §6.2/§7.4 |
| B1 硬%止损（卖出侧） | 三档止损线净影响全负（-164k/-117k/-107k），误杀率 40-46% | round3 §4.3 |

**进组合的成员选择原则**（国外方法论 → 本项目落地）：
1. **去相关 / 低重叠**（López de Prado 特征聚类 + Asness 低相关分散 + mRMR 最小冗余）：组合内成员两两交易集 Jaccard 重叠率应低（建议 <40%，参考 round3 §2.4 已算过 A5/A45 与 greedy 重叠率 ~52% 属偏高一档）。重叠率是成员"相关性"的直接代理，先算重叠矩阵再聚类分组。
2. **独立经济逻辑线**（Fama-French 因子独立性 + Greedy-7"7 条独立亏损逻辑线"经验）：5月系 / 11月系 / 3月系 / 1月系 / 12月 / Q2 等季节+信号线各自独立，不跨线堆叠同质标志。
3. **经济可解释**（Harvey 因子需经济解释 + Greedy-7 逻辑线）：每个成员有明确经济故事（年报季调仓/年末止损潮/年初调整/追涨被套）。
4. **叠加边际 > 0**（round3 §18 经验"叠加边际验证"）：组合整体与每个成员都要在"现有已开启 toggle 之上"算边际，边际=0 的成员剔除（A1/A2/A3 教训）。
5. **强稳健优先**（v4-detail §6 分级）：优先 maxSh<0.4 + 4 窗口全>2 + n≥100 + 少负年 的成员。

### 3. 推荐组合（5 个命名组合，成员全部为已上线 toggle）

> 指标为各成员既有已验证值（v4-detail/comprehensive §4）；组合整体指标须按"成员并集"重新回测（见 §4 防过拟合与 §6 验证），不能加和。

| 组合名 | 成员 toggle | 逻辑线 | 定位 |
|--------|------------|--------|------|
| **稳健核心** | r8（纯非五月3稳定,5.87）+ v4csimple（3月+周三+辅关注,7.84）+ v4b（A股+5月+追关注+related,53.96） | 3/11月 + 5月细化 | 外科手术式、全强稳健、零 5 月 shift 争议、损盈最低；"最小干预"偏好（comprehensive §4.4 保守方案扩展） |
| **5月系管理** | n4（A股+5月,4.67）+ v4j（5月+vlow+追关注,15.55）+ v4i（追关注+5月+概念+周一,27.04）+ v4b（53.96） | 5月系集中 | 把 5 月系里"已替代 ⑦⑧"的稳健细化版打包，替代 N5/N6；附监控提示（N5/N6 不在此组合） |
| **年末季节** | n2（11月+追关注+行业,6.63）+ n3（11月+追关注+周一,5.24）+ v4d（12月+周二+辅关注+低分,12.20） | 11/12月末年末调仓 | 年末止损潮逻辑线，经济逻辑最强 |
| **年初+周中** | n1（3月+周三+高价,10.06）+ v4csimple（7.84）+ v4k（1月+主关注+高价,10.11⚠️） | 1/3月年初调整 | 年初调整线；v4k 为 ⚠️ 监控成员需透出标记 |
| **最大化降亏** | greedy15（比值3.29, 净+149万, 现成复合 toggle） | Greedy-15 全 15 步 | "最大化降亏"偏好（损盈9.84%接近上限，排除20%交易）；作为组合宏成员整体勾选 |

> 说明：A45/A5（11月系，实施中）上线后，可再增一个 **11月系组合**（A5+A45），成员按 round3 推荐排序（A5>A45>A45all）放入，并避与 greedy15 step11（11月+追关注+行业）重叠计数——并集幂等无碍，但组合 hover 指标按并集重算。

### 4. 防过拟合（组合层面，不重犯 ⑦⑧ / 量子科技式错误）

1. **组合整体回测，独立口径**：组合"成员并集"重算减亏%/损盈%/比值/净影响（复用 round3 §1 口径），过 4 窗口（y1/y3/y10/all）比值>2 + maxSh<0.60 + neg 年占比 + 逐年表现。**禁止用成员指标加和冒充组合指标**（§0 摘要第 3 条）。
2. **叠加边际验证**（round3 已立规）：组合在"用户当前已开 toggle 集合"之上的边际，边际≈0 的组合提示冗余（同 A1/A2/A3 教训）。
3. **多重检验校正**（Harvey t>3 / BH-FDR）：1502 itemset 挖掘出来的标志，成员进组合的阈值应比单次检验更严。本项目已有 4 窗口+n≥100+maxSh 约束，组合选择再加"低重叠+独立逻辑线"双重过滤。
4. **Walk-forward 滚动验证**（Pardo）：组合评估标准流程 = 用 t-1 年数据选成员、t 年验证，模拟真实前向。这是 v4 §8 未来方向 #2，本功能应作为组合上线前的必选验证（至少做时间切分：2011-2020 选、2021-2026 验）。
5. **熔断机制**（DeepSeek 建议）：组合内 ⚠️ 监控成员（v4k/v4f/v4g/v4m/N5/N6）在 hover 透出"附监控"标记；每年 6 月检查对应月份子集，子集转盈则提示从组合移除该成员（不自动删，提示用户）。
6. **与单标志比值的关系公开**：组合 hover 同时展示"组合整体比值"与"成员各自比值"，让用户看到组合边际来源，防"组合看似好、实际靠单个成员"的错觉。

### 5. UI 交互映射（组合多选框 → 成员打勾 → 统一生效）

1. **组件形态**：在 `_renderSigKellyBar` 的 toggle 区（L7872）上方新增一行「组合降亏」分组，组合 checkbox 组样式复用 `.lab-sigkelly-toggle` 体系 + `data-no-pop=""` + `data-tip`（避免 term-pop 盖住，L2389-2405 既有约束）。
2. **三态勾选（tristate）**：组合 checkbox 状态 = 派生（全成员勾选→checked；部分→半选 indeterminate；无→空）。成员 toggle 任一 onchange 后刷新组合 checkbox 态。
3. **点击组合 → 勾选成员**：组合 onchange = 设置其全部成员 `state.labSigKellyFilters[key] = checked`，再调 `_kellyOnFilterChange()`（L7333 既有入口）触发重算。**不改 `_kellyPassesFadeFilters` 一行**。
4. **组合状态持久化**：组合成员定义（`comboPresets: {name: [memberKeys...]}`）放前端常量或独立配置 JSON；勾选态不单独存（由成员派生，避免双份状态），持久化只存成员开关（沿用现有 `state.labSigKellyFilters` 保存机制）。
5. **hover 指标**：组合 `data-tip` 显示组合整体（成员并集）减亏/损盈/比值/净影响（离线/脚本算好，或复用 `_kellyApplyFeeRecompute` 重算能力前端算）；再列成员清单+各自比值。
6. **§21 算法公示同步**：组合功能改 `purpose-notes.js` 的 `lab.sigkelly` 文案（L30），补"组合=预设宏，勾选成员 toggle，过滤按成员并集，指标为组合并集口径"说明；组合成员定义变更 = 算法公示同步（§21 铁律，A45/A5 实施 agent 已踩过 gap）。

### 6. 与现有 toggle 的关系（不破坏老功能）

| 关系 | 处理 |
|------|------|
| 27 个现有 toggle | 全部保留为组合成员，行为零改动 |
| Greedy-7/10/15 等复合 toggle | 可作为组合宏的成员整体勾选（如最大化降亏组合=greedy15）；与其它成员重叠幂等无害（既有注释已验证） |
| 组合 vs 单成员双开 | 组合勾选成员后，成员已亮；用户再手动关某成员 → 组合变半选，过滤即时反映（真实联动，非假联动） |
| 破坏性 toggle | excludeRatingLow/marketTiming **不放入任何组合**，但保留为独立 toggle（用户知情可自选），避免组合"一键开全"误开破坏性开关 |
| 数据一致性 §22 | 组合不产生第三份数据/状态；成员状态即真相；hover 指标口径统一（组合=成员并集，与单成员口径同源） |

### 7. 实施建议（给后续实施 agent，本调研未改任何代码）

1. **避开在跑 agent**：lab.js 当前有 A45/A5 实施 agent 在改（任务约束明确不碰 lab.js），本方案落档 docs 后，等 A45/A5 上线再实施组合功能（避免撞车）。
2. **先跑验证脚本再定稿组合**：建议用 round3 的 `/tmp` 脚本模式（`kelly_r3_pop.py` 等）对 §3 的 5 个组合各算一遍"成员并集"口径（减亏/损盈/比值/净影响/4窗口/maxSh/逐年）+ 成员两两 Jaccard 重叠矩阵，产出数据报告供用户 veto/增删（memory `param-opt-test-driven`：参数/候选不硬选，给数据报告让用户选）。
3. **上线流程**：build_min + bump_asset_version + bump sw.js CACHE_VERSION 三步（§9）；改 lab.js 必 bump sw.js（§9 补）。
4. **review 分级**：组合功能若只加 UI 宏（不改 `_kellyPassesFadeFilters` 过滤逻辑）= 偏 A/B 级；若改过滤逻辑或加数据产物 = 升级 B/C 级派 reviewer + check_data_integrity（§15）。

---

## 来源清单（调研方法论部分，因网络受限来自领域知识，供人工核对）

- Kuhn & Johnson, *Applied Predictive Modeling* (Wiley, 2013) — filter/embedded 选特征基础
- Siddiqi, *Credit Risk Scorecards* (Wiley, 2006) — IV/WoE 评分卡标准
- Guyon et al., "Gene selection for cancer classification using SVMs" (Machine Learning, 2002) — RFE
- Peng, Long, Ding, "mRMR" (IEEE TPAMI, 2005) — 最大相关最小冗余
- Tibshirani, "Regression shrinkage and selection via the Lasso" (JRSS-B, 1996)；Zou & Hastie, Elastic Net (JRSS-B, 2005)
- Breiman, "Random Forests" (Machine Learning, 2001)；Kursa & Rudnicki, "Boruta" (JSS, 2010)
- **López de Prado, *Advances in Financial Machine Learning* (Wiley, 2018)** — Ch.7 净化/禁运 CV、Ch.8 MDI/MDA/SFI + 特征聚类、Ch.10 元标注
- Bailey & López de Prado, "The Deflated Sharpe Ratio" (JPM, 2014)；Bailey, Borwein, López de Prado & Zhu, "The Probability of Backtest Overfitting" (JCF, 2017)
- Harvey, Liu & Zhu, "…and the Cross-Section of Expected Returns" (RFS, 2016)；Benjamini & Hochberg, "FDR" (JRSS-B, 1995)
- Israel, Kelly & Moskowitz, "Can Machines 'Learn' Finance?" (JIM, 2020)；Gu, Kelly & Xiu, "Empirical Asset Pricing via ML" (RFS, 2020)
- Lakkaraju, Bach & Leskovec, "Interpretable Decision Sets" (KDD, 2016)
- Grinold & Kahn, *Active Portfolio Management* (McGraw-Hill, 2000)
- Kakushadze, "101 Formulaic Alphas" (Wilmott, 2016; arXiv:1601.00991)
- Fama & French, three-factor (JFE, 1993) / five-factor (JFE, 2015)
- Ang, *Asset Management: A Systematic Approach to Factor Investing* (Oxford, 2014)
- Asness, Frazzini, Israel & Moskowitz, "Fact, Fiction, and Momentum Investing" (JPM, 2014)
- Pardo, *The Evaluation and Optimization of Trading Strategies* (Wiley, 1992/2008) — walk-forward 经典
- 项目内：Lavrac et al. 2002 / Atzmueller 2015 / Bay & Pazzani 2001 / Dong & Li 1999 / Pasquier et al. 1999（见 `docs/kelly/mining/kelly-mining-literature.md` 已录）

## 与现有文档的关系
- `docs/kelly/mining/kelly-loss-round3-verify.md` — 叠加边际口径、A1/A2/A3 排除依据（本方案 §2 直接复用）
- `docs/kelly/mining/kelly-v4-detail.md` / `docs/kelly/mining/kelly-loss-mining-v4.md` — 成员指标、过拟合分级、Greedy 组合
- `docs/kelly/backtest-ai/kelly-backtest-comprehensive-review.md` / `-deepseek-review.md` / `-comparison.md` — 组合推荐、⑦⑧风险、熔断、破坏性 toggle
- `static-site/lab.js` L7349-7464（`_kellyPassesFadeFilters`）+ L7872（toggle HTML）+ L7333（`_kellyOnFilterChange`）— 前端落地锚点
- `static-site/purpose-notes.js` L30 — §21 算法公示同步点
- 关联规范：CLAUDE.md §18（叠加边际/数据挖掘教训）、§21（算法公示）、§22（数据一致性）、§9（构建三步）、§15（review 分级）

Co-Authored-By: Claude <noreply@anthropic.com>
