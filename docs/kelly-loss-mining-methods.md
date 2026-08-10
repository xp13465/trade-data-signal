# 数据挖掘/机器学习方法论：交易亏损模式识别 + 降亏标志发现

> 调研日期：2026-08-10
> 任务背景：43656 笔交易，21 字段，目标找「排除后减亏%/损盈% 比值 > 3」的高比值降亏标志
> 数据来源：scikit-learn / pysubgroup / mlxtend / SHAP / imbalanced-learn 官方文档 + CrossRef 学术文献
> 方法：WebSearch + WebFetch + curl 抓取官方文档源码验证 API

---

## 0. 核心问题形式化

**输入**：43656 笔交易记录 × 21 字段（含特征字段 + 结果字段如盈亏金额/收益率等）

**目标**：找到交易子集 S（由若干特征的合取条件定义，如 `market_state=震荡 AND holding_hours>4 AND entry_signal=弱`），使得：

```
减亏% = (总亏损 - 排除S后亏损) / 总亏损 × 100%
损盈% = 排除S的交易数 / 总交易数 × 100%    （即"为减亏牺牲了多少交易机会"）
比值 = 减亏% / 损盈% > 3                    （排除 1% 的交易减亏 > 3%）
```

**本质**：找一个子群，其中亏损占比显著高于整体——子群越小且亏损越集中，比值越高。

**数学等价**：设整体亏损率 p₀ = 亏损交易数 / 总交易数，子群亏损率 p_s，子群占比 |S|/N。则：
- 减亏% ≈ (|S| · p_s - |S| · p₀) / (N · p₀) = (|S|/N) · (p_s - p₀) / p₀
- 损盈% = |S|/N
- **比值 = (p_s - p₀) / p₀ = p_s/p₀ - 1 = Lift - 1**

比值 > 3 等价于 **Lift > 4**（子群亏损率是整体的 4 倍以上）。这是子群发现中 Lift 质量函数的直接应用。

---

## 1. 子群发现（Subgroup Discovery）— **最推荐方法**

### 原理
子群发现是一种已建立的数据挖掘技术，目标是识别「目标变量分布显著偏离整体」的数据子集。给定一个目标概念（如 `is_loss=True`），算法搜索特征条件的合取（如 `market_state=震荡 AND holding_hours∈[4,8]`），找到目标率显著高于（或低于）整体的子群。

> pysubgroup 官方文档原文："The goal of subgroup discovery is to identify descriptions of data subsets that show an interesting distribution with respect to a pre-specified target concept." — 例："While in general the operation is successful in only 60% of the cases, for the subgroup of female patients under 50 that also have been treated with drug d, the success rate was 82%."

### 适用场景
- 找「亏损率异常高的交易子集」= 直接对应本任务
- 结果是可解释的合取规则（`条件1 AND 条件2 AND ...`），天然就是"降亏标志"
- 不需要训练/预测，直接在完整数据上搜索——是无监督+有监督的混合方法

### Python 实现要点（pysubgroup 库）

```python
import pysubgroup as ps
import pandas as pd

# 1. 准备数据：43656行 × 21列 DataFrame
#    需将目标变量设为二值：is_loss = (pnl < 0)
df['is_loss'] = (df['pnl'] < 0).astype(bool)

# 2. 定义目标
target = ps.BinaryTarget('is_loss', True)

# 3. 创建搜索空间（自动从 DataFrame 列生成选择器）
#    数值列自动离散化为区间，分类列生成等值条件
searchspace = ps.create_selectors(df, ignore=['is_loss', 'pnl', 'return_pct'])

# 4. 定义子群发现任务
task = ps.SubgroupDiscoveryTask(
    df,
    target,
    searchspace,
    result_set_size=20,    # 返回 Top-20 子群
    depth=3,               # 最多 3 个条件合取（可解释性 vs 表达力权衡）
    qf=ps.WRAccQF()        # 质量函数（见下）
)

# 5. 执行搜索
result = ps.DFS().execute(task)  # 或 ps.BestFirstSearch() / ps.GpGrowth()

# 6. 查看结果
print(result.to_dataframe())
```

### 质量函数选择（关键）

pysubgroup 的 `StandardQF(a)` 公式为：

```
QF(S) = (|S|/N)^a × (p_s - p₀)
```

其中 `|S|/N` = 子群相对大小，`p_s - p₀` = 子群亏损率偏离整体的程度，`a` 控制大小与偏离的权衡。

| 质量函数 | a 值 | 行为 | 适用性 |
|----------|------|------|--------|
| **WRAccQF** | a=1 | 加权相对准确度，平衡子群大小和偏离 | **推荐首选**：大子群+显著偏离，实用 |
| **StandardQF(a=0.5)** | a=0.5 | 介于 Lift 和 WRAcc 之间 | 折中方案，可调参 |
| **LiftQF** | a=0 | 纯 Lift（只看偏离，忽略大小） | 会找到极小子群（如 5 笔全亏），需加 min_size 约束 |
| **SimpleBinomialQF** | a=0.5 | 二项检验质量 | 统计显著性视角 |
| **ChiSquaredQF** | — | 卡方独立性检验 | 统计显著性视角，但计算较慢 |

**对本任务的推荐**：
- 首选 **WRAccQF**（a=1）：平衡子群大小和亏损率偏离，找到的子群既有统计意义又有实际覆盖
- 可配合 `StandardQF(a=0.5)` 对比，找到更小但偏离更大的子群
- **关键发现**：本任务的"比值 = Lift - 1"直接对应 Lift 概念，LiftQF 最贴合数学定义但需加约束防极小子群

### 约束机制（防极小子群）
```python
# 通过 constraints 参数限制子群最小大小
from pysubgroup.constraints import MinSupportConstraint
task = ps.SubgroupDiscoveryTask(
    df, target, searchspace,
    result_set_size=20, depth=3, qf=ps.WRAccQF(),
    constraints=[MinSupportConstraint(min_support=200)]  # 至少 200 笔交易
)
```

### 搜索算法

| 算法 | 特点 | 推荐场景 |
|------|------|----------|
| **DFS** | 深度优先穷举搜索 | depth ≤ 3 时可用，结果最完整 |
| **BestFirstSearch** | 最佳优先搜索（beam search 变体） | depth > 3 或搜索空间大时 |
| **GpGrowth** | 基于 FP-tree 的高效算法 | 大数据集（4万行完全够用），速度最快 |
| **Apriori** | 逐层搜索 | 传统方法，可选用 |

### 对本任务的适用性评估：★★★★★（最推荐）

1. **语义完全对齐**：子群发现 = "找目标率偏离整体的子集" = "找亏损率异常高的交易子集"
2. **结果天然可解释**：输出是 `条件1 AND 条件2` 合取规则，直接作为降亏标志
3. **质量函数直接对应比值**：WRAccQF/StandardQF 的数学公式直接优化"子群大小 × 亏损率偏离"，和减亏%/损盈%比值同构
4. **pysubgroup 库成熟**：PyPI 可装，pandas DataFrame 直接输入，API 简洁
5. **计算可行**：43656 行 × 21 列，depth=3，DFS 可秒级完成
6. **唯一限制**：原始库不支持自定义质量函数"比值>3"的直接优化，但可通过 WRAccQF 搜索 + 后过滤（计算每个结果的比值）两步实现

---

## 2. 决策树路径提取（Decision Tree Path Extraction）— **次推荐方法**

### 原理
训练一棵决策树分类器（目标 = is_loss），树的每条从根到叶的路径就是一条 if-then 规则。高亏损率的叶子节点对应的路径条件就是降亏标志。决策树通过信息增益/Gini 系数自动选择最优分裂特征和阈值，无需手动选特征。

### 适用场景
- 需要自动选择"最重要的分裂特征"+ "最优阈值"
- 结果是 if-then 规则（路径），天然可解释
- 和子群发现类似，但分裂标准是纯度（Gini/entropy）而非子群质量函数

### Python 实现要点（scikit-learn）

```python
from sklearn.tree import DecisionTreeClassifier, export_text
import pandas as pd
import numpy as np

# 1. 准备数据
feature_cols = [c for c in df.columns if c not in ['is_loss', 'pnl']]
X = df[feature_cols]
y = df['is_loss']

# 2. 训练决策树（限制深度保证可解释性）
clf = DecisionTreeClassifier(
    max_depth=4,              # 4层 = 最多4个条件，可解释
    min_samples_leaf=100,     # 叶子至少100笔，防止过拟合极小子群
    criterion='gini',         # 或 'entropy'
    class_weight='balanced',  # 处理不平衡（亏损可能少数类）
    random_state=42
)
clf.fit(X, y)

# 3. 提取规则文本
rules = export_text(clf, feature_names=feature_cols, show_weights=True)
print(rules)
# 输出示例：
# |--- holding_hours <= 2.50
# |   |--- market_state <= 1.50
# |   |   |--- entry_signal <= 0.50
# |   |   |   |--- weights: [50, 200]  ← 200亏损 vs 50盈利 = 80%亏损率
# |   |   |--- entry_signal >  0.50
# |   |   |   |--- weights: [150, 80]  ← 80亏损 vs 150盈利 = 35%亏损率

# 4. 提取每条路径的规则 + 亏损率（程序化提取）
from sklearn.tree import _tree

def extract_rules_with_stats(clf, feature_names):
    """提取所有根到叶路径，返回 (规则列表, 样本数, 亏损率) """
    tree = clf.tree_
    rules = []

    def recurse(node, conditions):
        if tree.children_left[node] == _tree.TREE_LEAF:  # 叶子节点
            # tree.value[node] = [[n_class0, n_class1]] (class0=非亏损, class1=亏损)
            value = tree.value[node][0]
            n_total = value.sum()
            loss_rate = value[1] / n_total if n_total > 0 else 0
            rules.append({
                'conditions': conditions.copy(),
                'n_samples': int(n_total),
                'loss_rate': loss_rate
            })
        else:
            feat = feature_names[tree.feature[node]]
            thresh = tree.threshold[node]
            # 左子树（<= 阈值）
            recurse(tree.children_left[node], conditions + [f"{feat} <= {thresh:.2f}"])
            # 右子树（> 阈值）
            recurse(tree.children_right[node], conditions + [f"{feat} > {thresh:.2f}"])

    recurse(0, [])
    return rules

all_rules = extract_rules_with_stats(clf, feature_cols)

# 5. 计算每条规则的降亏比值
overall_loss_rate = y.mean()
for r in all_rules:
    r['lift'] = r['loss_rate'] / overall_loss_rate
    r['ratio'] = r['lift'] - 1  # = 减亏%/损盈%
    if r['ratio'] > 3:
        print(f"★ 比值={r['ratio']:.1f} | 亏损率={r['loss_rate']:.1%} | "
              f"样本={r['n_samples']} | 条件: {' AND '.join(r['conditions'])}")
```

### 特征重要性（副产品）
```python
# 决策树自动给出特征重要性
importances = pd.Series(clf.feature_importances_, index=feature_cols)
print(importances.sort_values(ascending=False).head(10))
```

### 决策树 vs 随机森林

| 方面 | 单棵决策树 | 随机森林 |
|------|-----------|---------|
| 规则提取 | ✓ 直接提取路径 | ✗ 多棵树路径无法直接合并 |
| 特征重要性 | 粗略（单树偏差） | ✓ 更稳定（多树平均） |
| 预测精度 | 较低 | ✓ 更高 |
| 可解释性 | ✓ 高 | ✗ 低（黑箱） |

**推荐方案**：用随机森林的 `feature_importances_` 选 Top 特征 → 再用单棵决策树在这些特征上提取规则。

### 对本任务的适用性评估：★★★★☆（次推荐）

1. **规则提取直接可用**：每条路径就是一个降亏标志候选，`export_text` + `tree_` 结构程序化提取
2. **自动选特征+阈值**：决策树通过信息增益自动选择分裂特征和阈值，不需手动调参
3. **可解释性高**：if-then 规则清晰，可直接展示给用户
4. **与子群发现的区别**：决策树优化全局纯度（Gini），子群发现优化局部偏离（WRAcc/Lift）。子群发现更直接对齐"找偏离子群"目标
5. **限制**：单棵决策树的分裂是贪心的，可能错过某些高比值子群（因为某次分裂不是全局最优）。可通过多棵决策树（不同 max_depth/min_samples_leaf）取并集缓解
6. **优势**：sklearn 内置无需额外安装，`export_text` + `tree_.children_left/right/feature/threshold/value` API 成熟稳定

---

## 3. 随机森林 + 特征重要性（Random Forest Feature Importance）

### 原理
训练随机森林分类器（目标 = is_loss），通过 Gini 重要性（MDI）或排列重要性（permutation importance）识别哪些特征对预测亏损最重要。特征重要性高 = 该特征是亏损的关键预测因子。

### 适用场景
- 粗筛阶段：快速识别哪些字段与亏损最相关
- 作为子群发现/决策树的前置步骤：先用 Top-N 特征缩小搜索空间

### Python 实现要点

```python
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance

# 训练随机森林
rf = RandomForestClassifier(
    n_estimators=200,
    max_depth=8,
    min_samples_leaf=50,
    class_weight='balanced',
    n_jobs=-1,
    random_state=42
)
rf.fit(X, y)

# 方法1：Gini 重要性（MDI）— 快但有多重共线性偏差
mdi_importance = pd.Series(rf.feature_importances_, index=feature_cols)

# 方法2：排列重要性 — 更可靠，但计算慢
perm_result = permutation_importance(rf, X, y, n_repeats=10, random_state=42, n_jobs=-1)
perm_importance = pd.Series(perm_result.importances_mean, index=feature_cols)

# 对比两种重要性
importance_df = pd.DataFrame({
    'MDI': mdi_importance.sort_values(ascending=False),
    'Permutation': perm_importance.sort_values(ascending=False)
})
print(importance_df.head(10))
```

### 对本任务的适用性评估：★★★☆☆（辅助方法）

1. **只给特征排名，不给规则**：知道"holding_hours 最重要"但不知道"holding_hours > 4.5 时亏损率 70%"
2. **适合作为前置步骤**：先用随机森林选 Top-5 特征，再用子群发现/决策树在这些特征上找规则
3. **MDI 的已知问题**：当特征有多重共线性时，MDI 会分散重要性。排列重要性更可靠但计算慢
4. **不直接产出降亏标志**：需要和其他方法配合

---

## 4. 关联规则挖掘（Association Rule Mining）

### 原理
Apriori/FP-growth 算法找频繁项集（frequent itemsets），再生成关联规则 `前件 → 后件`。将交易特征离散化为"项"（如 `holding_hours=长`、`market_state=震荡`），后件设为 `is_loss=True`，找到频繁出现的高亏损特征组合。

### 适用场景
- 找"哪些特征组合频繁地与亏损共现"
- 结果是 `条件1 AND 条件2 → loss=True (支持度, 置信度, 提升度)` 格式

### Python 实现要点（mlxtend 库）

```python
from mlxtend.frequent_patterns import apriori, association_rules, fpgrowth
import pandas as pd

# 1. 将特征离散化为 one-hot 编码（关联规则需要布尔矩阵）
#    数值列用分位数离散化，分类列直接 one-hot
def discretize_for_arm(df, feature_cols, n_bins=3):
    """将特征离散化为布尔列"""
    arm_df = pd.DataFrame(index=df.index)
    for col in feature_cols:
        if df[col].dtype in ['float64', 'int64']:
            # 数值列：分位数离散化
            try:
                cats = pd.qcut(df[col], q=n_bins, labels=[f'{col}_低', f'{col}_中', f'{col}_高'],
                               duplicates='drop')
                dummies = pd.get_dummies(cats, prefix='')
                arm_df = pd.concat([arm_df, dummies], axis=1)
            except Exception:
                arm_df[col] = df[col].astype(bool)
        else:
            # 分类列：直接 one-hot
            dummies = pd.get_dummies(df[col], prefix=col)
            arm_df = pd.concat([arm_df, dummies], axis=1)
    # 加目标列
    arm_df['is_loss=True'] = df['is_loss']
    return arm_df.astype(bool)

arm_data = discretize_for_arm(df, feature_cols)

# 2. 挖掘频繁项集（min_support = 最小支持度，如 1%）
#    用 fpgrowth 比 apriori 快
frequent_itemsets = fpgrowth(arm_data, min_support=0.01, use_colnames=True)

# 3. 生成关联规则（后件含 is_loss=True）
rules = association_rules(frequent_itemsets, metric='confidence', min_threshold=0.5,
                          output='list')

# 4. 筛选后件为 is_loss=True 的规则，按 lift 排序
loss_rules = rules[rules['consequents'].apply(lambda x: 'is_loss=True' in x)]
loss_rules = loss_rules.sort_values('lift', ascending=False)

# 关键指标解读：
# - support:    前件+后件同时出现的比例 = 该子群占总交易的比例
# - confidence: 前件出现时后件也出现的概率 = 子群内亏损率
# - lift:       confidence / 整体亏损率 = 子群亏损率 / 整体亏损率
#               lift > 1 = 亏损率高于整体，lift > 4 = 比值 > 3

print(loss_rules[['antecedents', 'support', 'confidence', 'lift']].head(20))
```

### 关键指标与本任务的对应

| 关联规则指标 | 本任务对应 | 说明 |
|-------------|-----------|------|
| support | 损盈% | 前件（子群）占总交易的比例 |
| confidence | 子群亏损率 | 前件出现时亏损的概率 |
| lift | 比值 + 1 | 子群亏损率 / 整体亏损率，lift > 4 = 比值 > 3 |
| leverage | 绝对偏离 | 亏损率的绝对差值 × 子群大小 |
| conviction | 规则强度 | 依赖性度量 |

### Apriori vs FP-growth vs FPmax

| 算法 | 特点 | 推荐 |
|------|------|------|
| **FP-growth** | 基于 FP-tree，比 Apriori 快 2-10 倍 | **推荐**：4万行数据首选 |
| **Apriori** | 逐层候选生成，经典但较慢 | 可选 |
| **FPmax** | 只挖最大频繁项集（不含超集） | 去重场景用 |

### 对本任务的适用性评估：★★★★☆（推荐）

1. **lift 直接对应比值**：关联规则的 lift = 子群亏损率/整体亏损率，lift > 4 直接对应比值 > 3
2. **结果可解释**：`前件 → loss=True (lift=5.2)` 就是降亏标志
3. **适合找特征组合**：天然找多特征频繁共现，和降亏标志"特征组合"语义一致
4. **需要离散化**：数值特征必须先离散化（分位数/等频），可能丢失信息。离散化策略影响结果质量
5. **限制**：min_support 设太低会爆炸（太多频繁项集），设太高会漏掉小子群。4万行 × 21列需谨慎设参
6. **与子群发现的关系**：关联规则是子群发现的前身（SD 从 ARM 演化而来），但子群发现有更丰富的质量函数（WRAcc 等），而关联规则固定用 support/confidence/lift

---

## 5. 聚类分析（Clustering）

### 原理
对亏损交易子集做无监督聚类（K-means/DBSCAN），将亏损交易分成若干模式组。每组代表一种亏损模式（如"长时间持有+震荡市"型亏损 vs "短线+趋势市"型亏损）。

### 适用场景
- 亏损模式分组（探索性分析）
- 不预设目标变量，纯特征空间分组

### Python 实现要点

```python
from sklearn.cluster import KMeans, DBSCAN
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score

# 只取亏损交易
loss_df = df[df['is_loss']].copy()
X_loss = loss_df[feature_cols]

# 标准化（K-means 对尺度敏感）
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X_loss)

# 方法1：K-means（需指定 K）
# 用 silhouette score 选 K
for k in range(3, 10):
    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = km.fit_predict(X_scaled)
    score = silhouette_score(X_scaled, labels)
    print(f"K={k}, silhouette={score:.3f}")

best_k = 5  # 选最佳 K
km = KMeans(n_clusters=best_k, random_state=42, n_init=10)
loss_df['cluster'] = km.fit_predict(X_scaled)

# 分析每个聚类的特征
for c in range(best_k):
    cluster_data = loss_df[loss_df['cluster'] == c]
    print(f"\n=== 聚类 {c} ({len(cluster_data)} 笔) ===")
    print(cluster_data[feature_cols].mean())  # 各特征均值

# 方法2：DBSCAN（无需指定簇数，自动识别噪声点）
dbscan = DBSCAN(eps=0.5, min_samples=50)
loss_df['dbscan_cluster'] = dbscan.fit_predict(X_scaled)
# -1 = 噪声点（异常交易），其余 = 簇编号
```

### K-means vs DBSCAN vs HDBSCAN

| 方法 | 需指定 K | 处理噪声 | 簇形状 | 推荐场景 |
|------|---------|---------|--------|---------|
| **K-means** | 是 | 否 | 球形 | 簇数已知，大数据集快速 |
| **DBSCAN** | eps+min_samples | ✓（标-1） | 任意 | 密度不均，需识别异常 |
| **HDBSCAN** | min_cluster_size | ✓ | 任意+层次 | 密度变化大（推荐） |

### 对本任务的适用性评估：★★☆☆☆（探索性辅助）

1. **不直接产出降亏标志**：聚类只给分组，不直接给"排除后减亏%/损盈%比值"
2. **需要后处理**：聚类后还需对每个簇计算亏损率/比值，再人工解读特征
3. **只看亏损交易**：只在亏损子集上聚类，丢失了"亏损率 vs 整体"的对比信息
4. **K-means 局限**：假设球形簇，交易数据通常非球形
5. **价值**：适合作为探索性分析，发现亏损模式的自然分组（如"止损过晚型"vs"逆势型"），但不是找降亏标志的直接方法
6. **如果要用**：HDBSCAN > DBSCAN > K-means，因交易数据密度不均

---

## 6. 特征选择方法（Feature Selection）

### 原理
通过统计检验（互信息/卡方）或模型权重（递归特征消除 RFE）筛选与亏损最相关的特征，作为降亏标志的候选特征。

### 适用场景
- 前置步骤：从 21 个字段中筛选 Top-N 与亏损最相关的特征
- 为子群发现/决策树/关联规则缩小搜索空间

### Python 实现要点

```python
from sklearn.feature_selection import (
    mutual_info_classif, chi2, SelectKBest,
    RFE, RFECV, SelectFromModel
)
from sklearn.ensemble import RandomForestClassifier

# 方法1：互信息（捕捉任意统计依赖，非线性）
mi_scores = mutual_info_classif(X, y, random_state=42)
mi_series = pd.Series(mi_scores, index=feature_cols).sort_values(ascending=False)

# 方法2：卡方检验（只捕捉线性依赖，需要非负特征）
chi2_scores, chi2_pvalues = chi2(X.abs(), y)  # 注意：chi2 要求非负
chi2_series = pd.Series(chi2_scores, index=feature_cols).sort_values(ascending=False)

# 方法3：RFE（递归特征消除，基于模型权重）
rf = RandomForestClassifier(n_estimators=100, class_weight='balanced', n_jobs=-1)
rfe = RFE(rf, n_features_to_select=5)
rfe.fit(X, y)
rfe_selected = [f for f, sel in zip(feature_cols, rfe.support_) if sel]

# 方法4：RFECV（自动选最优特征数，交叉验证）
rfecv = RFECV(rf, cv=5, scoring='f1')
rfecv.fit(X, y)
rfecv_selected = [f for f, sel in zip(feature_cols, rfecv.support_) if sel]

# 方法5：SelectFromModel（基于特征重要性阈值）
sfm = SelectFromModel(rf, threshold='median')
sfm.fit(X, y)
sfm_selected = [f for f, sel in zip(feature_cols, sfm.get_support()) if sel]
```

### 方法对比

| 方法 | 捕捉非线性 | 考虑特征交互 | 计算量 | 推荐 |
|------|-----------|-------------|--------|------|
| **互信息** | ✓ | ✗（单变量） | 中 | ★★★★ 首选单变量方法 |
| **卡方** | ✗（线性） | ✗ | 低 | ★★★ 需非负特征 |
| **RFE** | ✓（取决于模型） | ✓（模型内） | 高 | ★★★ 模型驱动 |
| **RFECV** | ✓ | ✓ | 很高 | ★★★ 自动选数 |
| **SelectFromModel** | ✓ | ✓ | 中 | ★★★ 快速 |

### 对本任务的适用性评估：★★★☆☆（辅助前置步骤）

1. **不直接产出降亏标志**：只给"哪些特征重要"，不给"特征 > 什么阈值时亏损率高"
2. **适合缩小搜索空间**：从 21 个字段选 Top-5，再用于子群发现/决策树
3. **互信息推荐首选**：能捕捉非线性依赖（如 U 型关系），比卡方更全面
4. **和随机森林特征重要性重叠**：RFE/SelectFromModel 都基于随机森林，和 §3 重复
5. **建议**：用互信息做单变量筛选 + 随机森林做多变量筛选，取交集作为 Top 特征

---

## 7. 不平衡分类（Imbalanced Classification）

### 原理
如果亏损交易是少数类（如 30% 亏损 vs 70% 盈利），分类器会偏向多数类。使用 SMOTE（合成少数类过采样）或 class_weight='balanced' 处理不平衡，提高亏损类预测召回率。

### 适用场景
- 亏损交易占比 < 40% 时，分类器需要不平衡处理
- 作为决策树/随机森林的前置步骤

### Python 实现要点

```python
from imblearn.over_sampling import SMOTE, ADASYN, BorderlineSMOTE, SMOTENC
from imblearn.under_sampling import RandomUnderSampler
from imblearn.combine import SMOTETomek

# 方法1：class_weight='balanced'（最简单，推荐首选）
clf = DecisionTreeClassifier(class_weight='balanced', max_depth=4)

# 方法2：SMOTE（合成少数类样本）
smote = SMOTE(random_state=42)
X_res, y_res = smote.fit_resample(X, y)

# 方法3：SMOTENC（混合数值+分类特征）
smotenc = SMOTENC(categorical_features=[0, 2], random_state=42)
X_res, y_res = smotenc.fit_resample(X, y)

# 方法4：BorderlineSMOTE（只对边界样本过采样，更精准）
bsmote = BorderlineSMOTE(random_state=42)
X_res, y_res = bsmote.fit_resample(X, y)

# 方法5：组合过采样+欠采样
combined = SMOTETomek(random_state=42)
X_res, y_res = combined.fit_resample(X, y)
```

### 方法选择

| 方法 | 适用场景 | 推荐度 |
|------|---------|--------|
| **class_weight='balanced'** | 所有分类器内置，无数据变换 | ★★★★★ 首选 |
| **SMOTE** | 纯数值特征 | ★★★ 需要更多训练数据时 |
| **SMOTENC** | 混合数值+分类特征 | ★★★★ 更适合本任务 |
| **BorderlineSMOTE** | 关注边界样本 | ★★★ 精准过采样 |
| **RandomUnderSampler** | 多数类过多时 | ★★ 会丢信息 |

### 对本任务的适用性评估：★★★☆☆（辅助调优步骤）

1. **不是独立方法**：不平衡处理是分类器的辅助步骤，不直接产出降亏标志
2. **43656 笔中亏损比例决定必要性**：如果亏损率 ~40%，不平衡程度轻，`class_weight='balanced'` 足够
3. **如果亏损率 < 30%**：建议用 SMOTENC（因有分类+数值混合特征）
4. **对子群发现无影响**：子群发现不需要训练分类器，不受不平衡问题影响
5. **对关联规则无影响**：关联规则基于支持度/置信度，不需分类器
6. **主要影响决策树/随机森林**：使用决策树路径提取时，`class_weight='balanced'` 防止树偏向多数类

---

## 8. 可解释 ML（SHAP + 规则提取）

### 原理
SHAP（SHapley Additive exPlanations）基于博弈论的 Shapley 值，量化每个特征对单笔交易预测结果的贡献方向和大小。全局聚合后可看到哪些特征整体上推动预测向"亏损"方向。

### 适用场景
- 解释"为什么模型预测这笔交易会亏"
- 全局特征重要性（比 Gini importance 更严谨）
- 特征-目标关系可视化（dependence plot）

### Python 实现要点

```python
import shap
from sklearn.ensemble import RandomForestClassifier

# 1. 训练模型
rf = RandomForestClassifier(n_estimators=200, class_weight='balanced', n_jobs=-1, random_state=42)
rf.fit(X, y)

# 2. 计算 SHAP 值（TreeExplainer 对树模型高效）
explainer = shap.TreeExplainer(rf)
shap_values = explainer.shap_values(X)
# 对于二分类: shap_values[1] = 亏损类的 SHAP 值

# 3. 全局特征重要性（SHAP 值绝对值平均）
shap_importance = pd.Series(
    np.abs(shap_values[1]).mean(axis=0),
    index=feature_cols
).sort_values(ascending=False)

# 4. 可视化
# Beeswarm plot: 每个特征的 SHAP 值分布
shap.summary_plot(shap_values[1], X, feature_names=feature_cols)

# Dependence plot: 单个特征值 vs SHAP 值
shap.dependence_plot('holding_hours', shap_values[1], X)

# Waterfall plot: 单笔交易的预测解释
shap.plots.waterfall(shap_values[0, :, 1])
```

### SHAP 核心API

| API | 用途 |
|-----|------|
| `shap.TreeExplainer(model)` | 树模型专用解释器（高效精确） |
| `shap.Explainer(model)` | 通用解释器（任何模型） |
| `explainer.shap_values(X)` | 计算 SHAP 值矩阵 |
| `shap.summary_plot(shap_values, X)` | Beeswarm 全局重要性图 |
| `shap.plots.bar(shap_values)` | 条形图全局重要性 |
| `shap.plots.waterfall(shap_values[i])` | 单样本瀑布图 |
| `shap.dependence_plot(feat, shap_values, X)` | 特征-SHAP 依赖图 |

### SHAP vs 决策树路径 vs 子群发现

| 方面 | SHAP | 决策树路径 | 子群发现 |
|------|------|-----------|---------|
| 产出 | 特征贡献度 | if-then 规则 | 合取条件子群 |
| 可解释性 | 中（需解读 SHAP 值） | 高（直接规则） | 高（直接规则） |
| 给阈值 | ✗（只给方向） | ✓（自动分裂阈值） | ✓（搜索最优阈值） |
| 给子群 | ✗（需后处理） | ✓（叶子=子群） | ✓（直接输出子群） |

### 对本任务的适用性评估：★★★☆☆（辅助解释方法）

1. **不直接产出降亏标志**：SHAP 给"特征贡献度"，不直接给"特征组合+阈值"规则
2. **解释价值高**：能回答"为什么这笔交易亏了"（单笔瀑布图）和"整体什么特征推动亏损"（beeswarm）
3. **和随机森林特征重要性重叠**：SHAP 全局重要性比 Gini MDI 更严谨，但结论通常一致
4. **适合作为验证工具**：用 SHAP 验证子群发现/决策树找到的降亏标志是否合理
5. **限制**：需要训练分类器（黑箱模型）作为前置，增加复杂度。SHAP 值计算对 4 万行 × 200 棵树约需 10-30 秒
6. **推荐用法**：不作为主要方法，作为"验证+解释"辅助工具

---

## 9. 量化交易亏损归因文献调研

### 学术文献要点

通过 CrossRef API 搜索 trading + machine learning + loss + classification 相关文献：

1. **"The Application of Machine Learning to Algorithmic Trading in Financial Markets"** (Feng, DOI:10.5220/0013264200004568) — ML 用于算法交易的一般框架
2. **"Comparing algorithmic trading strategies by analogies to machine learning"** (Zhang & Pinsky, DOI:10.1177/21576203251360571) — 将技术分析交易策略类比为 ML，用历史价格模式预测未来
3. **"Multi-Timeframe Signal Confirmation in Algorithmic Cryptocurrency Trading"** (Goswami, DOI:10.2139/ssrn.6683818) — 短时间框架信号多为噪声，需多时间框架确认（和"降亏标志"思路一致：过滤掉噪声信号=减亏）
4. **"Machine Learning Techniques"** (Kissell, DOI:10.1016/b978-0-12-815630-8.00009-0) — ML 技术在交易中的系统应用

### 子群发现学术文献

5. **"Adapting classification rule induction to subgroup discovery"** (Lavrac, Flach, Kavsek, DOI:10.1109/icdm.2002.1183912) — 经典论文：将分类规则归纳适配到子群发现
6. **"Refinement and selection heuristics in subgroup discovery and classification rule learning"** (Valmarska, Lavrač, Fürnkranz, DOI:10.1016/j.eswa.2017.03.041) — 子群发现中的精炼和选择启发式
7. **Atzmueller, "Subgroup discovery"** (WIREs Data Min. Knowl. Discov., 2015) — 子群发现综述
8. **Herrera et al., "An overview on subgroup discovery: foundations and applications"** (Knowl. Inf. Syst., 2011) — 子群发现基础与应用综述

### 行业实践要点（综合文献共识）

- **亏损归因**：量化交易行业常用"归因分析"（attribution analysis）拆解亏损来源（市场因子/策略因子/执行因子），ML 方法可自动化归因
- **策略回测亏损归因**：将回测交易按特征分组，统计各组盈亏，找出"系统性亏损特征组合"——本质上就是子群发现
- **信号过滤**：用分类器预测信号质量（盈利 vs 亏损），过滤低质量信号=减亏。等价于本任务的"降亏标志"
- **过拟合警惕**：在历史交易上找到的降亏标志可能过拟合（只对历史有效），需 out-of-sample 验证

---

## 10. 综合推荐排序

### 推荐实施方案（按优先级）

| 排名 | 方法 | 推荐度 | 角色 | 理由 |
|------|------|--------|------|------|
| **1** | **子群发现（pysubgroup）** | ★★★★★ | 主力方法 | 语义完全对齐"找亏损率偏离整体的子集"，WRAccQF 直接优化子群大小×偏离，输出可解释合取规则，4万行秒级完成 |
| **2** | **决策树路径提取（sklearn）** | ★★★★☆ | 主力方法 | 自动选特征+阈值，export_text+tree_结构程序化提取规则，和子群发现互补（分裂标准不同，可能发现不同子群） |
| **3** | **关联规则挖掘（mlxtend）** | ★★★★☆ | 验证方法 | lift 直接对应比值，fpgrowth 高效，结果格式和子群发现类似。可交叉验证子群发现的结果 |
| **4** | **随机森林特征重要性** | ★★★☆☆ | 前置步骤 | 粗筛 Top 特征，缩小子群发现/决策树搜索空间。排列重要性更可靠 |
| **5** | **互信息特征选择** | ★★★☆☆ | 前置步骤 | 单变量非线性依赖检测，和随机森林互补 |
| **6** | **SHAP 解释** | ★★★☆☆ | 验证工具 | 验证降亏标志的合理性，解释单笔交易亏损原因 |
| **7** | **不平衡分类处理** | ★★★☆☆ | 调优步骤 | class_weight='balanced' 配合决策树，SMOTENC 处理混合特征 |
| **8** | **聚类分析** | ★★☆☆☆ | 探索分析 | 亏损模式分组，不直接产出降亏标志 |

### 推荐实施流程

```
Step 1: 数据准备
  ├── is_loss = (pnl < 0)  二值化目标
  ├── 数值特征分位数离散化（供关联规则用）
  └── 原始数值特征保留（供决策树/子群使用）

Step 2: 前置特征筛选（可选）
  ├── 互信息：mutual_info_classif → Top-10 单变量相关特征
  └── 随机森林：feature_importances_ → Top-10 多变量相关特征
  → 取交集或并集作为 Top 特征集

Step 3: 主力方法并行运行
  ├── 子群发现：pysubgroup + WRAccQF + depth=3 + min_support=200
  │   → Top-20 子群（合取规则 + 亏损率 + size）
  ├── 决策树路径：DecisionTreeClassifier(max_depth=4, min_samples_leaf=100, class_weight='balanced')
  │   → 所有叶子节点的路径规则 + 亏损率
  └── 关联规则：mlxtend fpgrowth + association_rules
      → lift > 4 的规则（= 比值 > 3）

Step 4: 后处理 + 比值计算
  ├── 对所有候选规则计算：减亏% / 损盈% = Lift - 1
  ├── 筛选比值 > 3 的规则
  ├── 去重（合并重叠子群，overlap_filter）
  └── 按比值排序

Step 5: 验证
  ├── SHAP 验证：降亏标志的特征是否在 SHAP 全局重要性 Top-N
  ├── 统计检验：子群亏损率是否显著高于整体（卡方/fisher exact）
  └── Out-of-sample：按时间切分训练/验证集，验证降亏标志稳定性
```

### 重点评估：子群发现 vs 决策树路径（最贴合本任务的两类）

| 维度 | 子群发现（pysubgroup） | 决策树路径（sklearn） |
|------|----------------------|---------------------|
| **优化目标** | WRAccQF = 子群大小 × 亏损率偏离（直接对齐任务） | Gini 纯度（间接对齐） |
| **搜索策略** | 穷举/beam search，找 Top-K 最优子群 | 贪心分裂，一条路径到叶子 |
| **结果质量** | 保证找到全局 Top-K 子群（给定 depth） | 可能错过非贪心最优的子群 |
| **阈值选择** | 从预定义离散化区间选（create_selectors） | 从连续值选最优分裂点（更精细） |
| **多子群** | 直接返回 Top-20 互不重叠子群 | 一棵树有多个叶子（但叶子互斥） |
| **可调参** | depth, result_set_size, qf, constraints | max_depth, min_samples_leaf, criterion |
| **额外依赖** | 需 pip install pysubgroup | sklearn 内置 |
| **速度** | 4万行 depth=3 秒级 | 即时 |
| **推荐** | **首选**（优化目标更对齐） | **次选**（互补，自动阈值更精细） |

**关键差异**：子群发现直接优化"子群大小 × 亏损率偏离"（WRAccQF），这正是减亏%/损盈%比值的近似。决策树优化全局 Gini 纯度，虽然高 Gini 叶子通常也是高亏损子群，但不保证找到比值最高的子群。

**互补使用**：子群发现可能因离散化粒度错过最优阈值，决策树自动选连续阈值更精细。两者并运行后取并集去重，覆盖最全。

---

## 附：环境依赖

```bash
# 已安装（项目 .venv 内）
# scikit-learn — 决策树/随机森林/聚类/特征选择

# 需新增安装
pip install pysubgroup     # 子群发现
pip install mlxtend        # 关联规则（apriori/fpgrowth）
pip install shap           # SHAP 解释
pip install imbalanced-learn  # 不平衡分类（SMOTE 等）
```

---

## 附：数据来源说明

本文档基于以下官方文档和学术文献调研（2026-08-10）：

- **pysubgroup**：GitHub README + 源码（binary_target.py/measures.py/algorithms.py），确认 BinaryTarget/WRAccQF/StandardQF/LiftQF/ChiSquaredQF/SimpleBinomialQF + DFS/Apriori/GpGrowth/BestFirstSearch 算法 + StandardQF(a) 公式 `(|S|/N)^a × (p_s - p₀)`
- **scikit-learn**：官方文档 1.9.0 — DecisionTreeClassifier（CART 算法/Gini/entropy/export_text/tree_ 结构/feature_importances_）+ feature_selection（mutual_info_classif/chi2/RFE/RFECV/SelectFromModel/SelectKBest）+ clustering（KMeans/DBSCAN/HDBSCAN）
- **mlxtend**：官方文档 — fpgrowth/apriori/association_rules/fpmax + lift_score
- **SHAP**：GitHub README — TreeExplainer/shap.Explainer/summary_plot/beeswarm/bar/waterfall/dependence_plot
- **imbalanced-learn**：官方文档 — SMOTE/ADASYN/BorderlineSMOTE/SMOTENC/SMOTEN/RandomOverSampler
- **CrossRef 学术文献**：子群发现经典论文（Lavrac 2002/Valmarska 2017/Atzmueller 2015/Herrera 2011）+ 交易 ML 应用文献
