# 凯利 AI降亏宏 穷举回测报告(2026-08-12 跑,2026-08-13 落档)

> **背景**:本报告由穷举 search agent(ab15c554)产出,原始结论存于 /tmp(agent-progress-kelly-exhaustive.md + kelly_master_results.json 2728 配置),**当时未落档 docs/ 给用户看**——2026-08-13 用户指出"之前还有个 ai 降亏穷举的报告也美给我看",主控补落档于此。
> **数据**:2728 个去重配置(全扫),口径=AI宏基线/空基线 + 单键扫描 31×4 + 移除扫描 4×4 + 组合 2-5元(候选10键)×4 + 二阶交互扫描×4 + 全开参照。回测基于 signal_kelly_backtest。

## 一、穷举覆盖(2728 配置)

| 扫描类型 | 覆盖 |
|---|---|
| AI宏基线 / 空基线 | posK=1~4 各 phase0-3 |
| 单键扫描 | 31 键 × 4 posK |
| 移除扫描 | 4 × 4 |
| 组合 2-5 元(候选 10 键) | × 4 posK |
| 二阶交互扫描 | × 4 posK |
| 全开参照 | 1 |

## 二、推荐 AI 宏(穷举结论)

**推荐 AI宏(6 键:n2 + exclSpecialBear + J1 + J2 + excludeMonth + A45) posK2 全模式:**

| 模式 | 收益率 | vs 现默认(pp) | 净利 | 笔数 | concCap | 回撤 | calmar |
|---|---|---|---|---|---|---|---|
| A | 48.25% | **+10.36pp** | 10.6万 | 1889 | 22万 | 4.7万 | 10.41 |
| F | 51.04% | **+10.31pp** | 16.3万 | 1889 | 32万 | 6.7万 | 7.62 |
| G | 46.33% | **+3.33pp** | 106.6万 | 1889 | 230万 | 10.5万 | 4.48 |

**现默认(posK2 G)**:ret=43.00% / 净利127.7万 / n=2325 / concCap=297万 / 回撤4.95% / calmar=3.68

⚠️ **关键权衡(G 模式)**:推荐宏收益率 +3.33pp,但**净利从 127.7万 降到 106.6万(-21.1万)**,原因=宏过滤掉更多笔数(2325→1889)、concCap 降低(297万→230万)。A/F 模式收益+10pp 但绝对值小(净利 10-16万)。→ 收益率提升以缩小持仓规模和笔数为代价。

## 三、每 K 档最优(G 模式)

| K | 最优配置 | G 收益率 | 净利 |
|---|---|---|---|
| K1 | exclM+a45+v4m | 52.68% | 70.1万 |
| K2 | exclM+a45+v4f+v4m | 46.53% | 107.0万 |
| K3 | exclM+a45+v4m | 44.28% | 136.8万 |
| K4 | exclM+a45+v4m | 43.20% | 162.0万 |

**K 档排序(G 模式)**:K1>K2>K3>K4(单调);A/F 模式:K1>K3>(K4≈K2)。

## 四、现默认排名(验证)

- 现默认(AI宏 K2 G=43.00%)在 2728 配置中按 G ret 降序**排第 1436 位,被 1435 个配置超过**;其中 K2/K3/K4(非 K1)超过默认的有 **757 个**。
- → 现默认并非 G 模式最优,穷举找到明显更好配置。

## 五、非 K1 口径 G-mode TOP10(节选)

| K | 配置 | ret | profit | n | concCap |
|---|---|---|---|---|---|
| K2 | exclMonth+a45NovMidLateSpecial+v4f+v4m | 46.53% | 107.0万 | 1878 | 230万 |
| K2 | exclMonth+a45NovMidLateSpecial+a5NovMidSpecial+v4f+v4m | 46.53% | 107.0万 | 1878 | 230万 |
| K2 | exclMonth+a45NovMidLateSpecial+v4f+v4m+v4b | 46.53% | 107.0万 | 1878 | 230万 |
| K2 | exclMonth+a45NovMidLateSpecial+v4f+v4m+n6MidMay | 46.53% | 107.0万 | 1878 | 230万 |
| K2 | exclMonth+a45NovMidLateSpecial+v4m | 46.34% | 107.1万 | 1881 | 231万 |
| ... | ... | ... | ... | ... | ... |

## 六、每 posK 跨模式(A/F/G)最优(节选)

| K | 模式 | 配置 | ret | profit | concCap |
|---|---|---|---|---|---|
| K1 | A | exclMonth+a45NovMidLateSpecial+greedy15 | 73.25% | 8.1万 | 11万 |
| K2 | A | exclMonth+a45NovMidLateSpecial+greedy15 | 64.69% | 14.2万 | 22万 |
| K3 | A | exclMonth+a45NovMidLateSpecial+greedy15 | 66.42% | 21.9万 | 33万 |
| K4 | A | exclMonth+a45NovMidLateSpecial+greedy15 | 63.55% | 28.0万 | 44万 |

## 七、推荐 vs 现默认 分周期(G 模式 K2)

| 周期 | 现默认 ret | 推荐 ret | dRet | dProfit |
|---|---|---|---|---|
| y1 | 3.98% | 3.98% | +0.01pp | -1.5万 |
| y3 | 35.53% | 37.50% | +1.97pp | -18.9万 |
| y5 | 33.09% | 35.25% | +2.16pp | -17.2万 |
| y10 | 39.82% | 42.36% | +2.54pp | -20.8万 |
| all | 43.00% | 46.33% | +3.33pp | -21.2万 |

## 八、与已落地的「AI宏=新默认」的关系(重要对账)

- 已上线 commit 90f948e3c「AI宏=新默认(替换旧默认A45/A5, 开启n2)」——是**部分落地**,与穷举 6 键推荐(n2+exclSpecialBear+J1+J2+excludeMonth+A45)**不完全一致**(已落地只提了 n2 + 替换 A45/A5,未含 exclSpecialBear/J1/J2/excludeMonth 全量)。
- **2026-08-13 用户澄清 AI宏 真实需求**:①AI宏 3 级联动(父级勾选联动子级)**未做** ②AI宏独立一行+收起/展开**未做** ③AI宏对应默认推荐打勾**未做** ④**AI宏必含 4 个组合降亏排序打勾**(已知),其余 toggle 待穷举结果定。
- → 本报告即"其余 toggle 待穷举结果"的数据依据;AI宏 UI 三件套为任务 #39 剩余缺口。

## 九、数据文件
- 全量 2728 配置:`/tmp/kelly_master_results.json`(1.67MB,当时临时目录,建议后续迁入 data/ 或 git 落档)
- 分析脚本:`/tmp/kelly_rec.js` / `kelly_final_analysis2.js` / `kelly_final_analysis.js` / `kelly_master*.js` / `kelly_phase5.js` / `kelly_exhaustive_lib.js`
- 复跑方式:`cd /tmp && node kelly_final_analysis2.js` / `node kelly_rec.js`(需 kelly_exhaustive_lib.js + master_results.json 同目录)
