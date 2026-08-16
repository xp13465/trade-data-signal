# 样本外榜「低过拟合」维度 min-max 归一化被极端离群值压平 —— 调研与修复报告

- 日期:2026-08-17
- 状态:已修复上线(纯前端展示/排序改动,不动任何算法口径/数据产物/主功能)
- 涉及文件:`static-site/lab.js`
- 复现脚本:`docs/scripts/analyze_oos_normalization_bias.py`(本报告同目录 `scripts/`)

## 0. 一句话结论

样本外榜「低过拟合」维度(overfit=|train_ret-test_ret|, 154 行 min-max 归一)被 `full_in` 全仓复利模式的极端离群值(最大 519.63)压平,导致 94.2% 行「低过拟合」≥0.95 满分、维度失去区分度。修复方案 = **95% 分位截断抗极端值**(超 p95 钳到 p95,实测 p95≈61.85),替补🔵排序拉开(full_in 行 ≥0.95 从 88.3%→57.1%),**主候选⭐️ Top12 排序逐位不变**(主候选 overfit 全 ≤1.56 ≪ 61.85,截断零影响),⭐️入选判定不受影响(后端 winsorize 算法不涉及此处)。

## 1. 离群值定位

样本外榜 `_labRetestRankRows` 用 `_labRetestMinMax(raw, "overfit")` 对全部 9 指数 × 全仓(full_in)+定额(fixed_10k)共 154 行做 min-max 归一化。raw overfit 数组存在极端离群值,均来自 `full_in` 全仓复利模式(复利放大使 train_ret 高达数百):

| overfit | train | test | mode | 指数 | 配对 |
|---|---|---|---|---|---|
| 519.63 | 519.63 | 0.735 | full_in | sz | Donchian20_up\|MACD_death |
| 516.02 | 516.02 | 0.420 | full_in | sh | Donchian20_up\|MACD_death |
| 355.93 | 355.93 | 0.180 | full_in | sh | Donchian20_up\|MA_death_5_20 |
| 324.52 | 324.52 | 0.577 | full_in | sz | Donchian20_up\|BB_middle_break |
| 213.70 | 213.70 | 0.354 | full_in | sh | MACD_golden\|BB_middle_break |
| 148.47 | 148.47 | 0.348 | full_in | sz | MA_golden_5_20\|BB_middle_break |
| 129.57 | 129.57 | 0.313 | full_in | sh | Donchian55_up\|MACD_death |
| 62.24 | 62.24 | 0.646 | full_in | sz | Donchian55_up\|MACD_death |

max = 519.63,直接把整个 min-max 轴拉平。

## 2. 失真占比

当前归一化(全部行 min-max, max=519.63):

- 低过拟合 ≥0.95:**145/154 (94.2%)**,≥0.99:129 (83.8%),中位数 0.9986
  - [full_in] ≥0.95:68/77 (88.3%),中位 0.9962
  - [fixed_10k] ≥0.95:77/77 (100.0%),中位 0.9996

→ 94.2% 行几乎满分,「低过拟合」维度对排序几乎不提供区分度,该维度被离群值压平失效。

## 3. 修复方案对比

### 方案A(采用):95% 分位截断
`_labRetestMinMax` 增加可选 `pctCap` 参数,对 overfit 数组做 95% 分位截断(超 p95 钳到 p95,实测 p95=61.85),再算 min/max;归一化时输入同样钳到 cap。与全站 `_labWinsor`(lab.js L2787)抗极端惯例一致。

截断重算(p95=61.85)结果:

- 低过拟合 ≥0.95:**120/154 (77.9%)**,中位数 0.9884
  - [full_in] ≥0.95:**44/77 (57.1%)**,中位 0.9681
  - [fixed_10k] ≥0.95:76/77 (98.7%),中位 0.9964

→ full_in 行 ≥0.95 从 88.3% 降至 57.1%,替补🔵维度区分度显著恢复。

### 方案B:99% 分位截断(p99=431.17)
截断重算(p99)结果:

- 低过拟合 ≥0.95:145/154 (94.2%),中位数 0.9983
  - [full_in] ≥0.95:68/77 (88.3%),中位 0.9954

→ 99% 分位只钳掉 519.63/516.02 两个最大离群,p95 内仍有大量数百级离群,区分度几乎未恢复。**不采用**(抗极端不足)。

### 方案C:对 full_in / fixed_10k 分行池分别归一
两套收益尺度(全仓复利数百 vs 定额)各自独立归一,彻底消除同池问题。但会改变 oos 综合分跨模式可比口径,影响范围大、需更大改动力度。**作为后续可选方向**,本次采用方案A(改动最小、根治「单点压平」)。

## 4. 截断前后排序对照

### 主候选⭐️ Top12(截断前后逐位对比)

主候选 6 对(6×2 模式 = 12 行)overfit 最大仅 1.56:

```
kc50|Donchian20_up|F_D1_S1_MACD|full_in|kc50|Donchian20_up|MACD_death|full_in|kc50|Donchian20_up|MA_death_5_20|full_in|kc50|Donchian20_up|F_D1_S1_MACD|fixed_10k|kc50|Donchian20_up|BB_middle_break|full_in|kc50|Donchian20_up|MACD_death|fixed_10k|kc50|Donchian20_up|Donchian10_down|full_in|kc50|Donchian20_up|MA_death_5_20|fixed_10k|kc50|Donchian20_up|BB_middle_break|fixed_10k|kc50|Donchian20_up|Donchian10_down|fixed_10k|bj50|Donchian20_up|MA_death_5_20|full_in|bj50|Donchian20_up|MA_death_5_20|fixed_10k
```

截断前后 **Top12 逐位完全相同**。原因:所有主候选 overfit ≤1.56 ≪ p95 截断值 61.85,`min(v, 61.85)=v`,overfitN 完全不变;其余所有维度(整体4维/分年/oos test收益/oos胜率/regime)均未改动 → 每个主候选的 oos 综合分与综合分不变 → 排序逐位不变。⭐️入选判定由后端 winsorize 算法控制,不涉及此前端归一化,不受影响。

### 替补🔵
full_in 行低过拟合 ≥0.95 从 88.3%→57.1%,维度区分度恢复,替补排序拉开。

## 5. 诚实标注

- 本次修复只解决「单个极端离群值把 min-max 轴压平」的失真(方案A,95% 分位截断)。
- **未解决**「全仓复利(full_in)与定额(fixed_10k)两种收益尺度同池」的结构性问题——fixed_10k 行经截断后 ≥0.95 仍占 98.7%,跨模式比较(全仓 vs 定额)仍需谨慎。legend 已标注此局限。
- 方案A 是纯前端展示/排序改动,不改任何算法口径、数据产物、后端 winsorize、主功能(信号凯利/AI仓位/主候选榜)。

## 6. 实施与自测摘要

- 改动点:`static-site/lab.js`
  - `_labRetestMinMax(rows, key, pctCap)` 增加 95% 分位截断能力(仅 overfit 维度调用 `_labRetestMinMax(raw, "overfit", 0.95)`)
  - 样本外榜 legend 补「低过拟合维度已按 95% 分位截断抗极端值」,更新 1:1 例(科创50·唐奇安20上轨买×MACD死叉卖:低过拟合 0.998→0.983,样本外分 0.90→0.89),并更新「本维度当前局限」标注(已截断,但全仓复利与定额两种收益尺度仍同池,跨模式比较需谨慎)
- 自测:node --check 语法通过;复现脚本跑出截断前后分布对照;node 验主候选 Top12 逐位不变;9 指数全部配对不崩;成本对比有覆盖/无覆盖两分支正常。
- 同 commit:build_min.py + bump_asset_version.py + sw.js CACHE_VERSION 同步。

## 复现

- 脚本:`docs/scripts/analyze_oos_normalization_bias.py`(本报告同目录 `scripts/`)
- 输入依赖:`static-site/data/lab/lab_retest_{sh,sz,bj50,csi500,csi1000,cyb,hs300,kc50,sz50}.json`(生成于 2026-08-14 19:00,scripts/lab/lab_retest.py,与线上 R2 同源)
- 重跑命令(从项目根):
  ```
  python3 docs/scripts/analyze_oos_normalization_bias.py
  ```
  (脚本头部 `BASE` 自动回退到 `static-site/data/lab`,支持从项目根或 docs/scripts/ 直接跑)
- 数据版本:lab_retest_*.json 2026-08-14 19:00 生成,与线上 R2 同源。
- 关键口径一句话:overfit=|train_ret-test_ret|(前70%训练/后30%验证切片,小数);低过拟合 = 1-minmax(overfit) across 全部 9 指数 154 行(full_in 77 + fixed_10k 77);修复后 overfit 归一化前先做 95% 分位截断(p95≈61.85)。
