# 凯利 AI宏穷举报告 — 审计修正(2026-08-13)

> 本文件是对 `docs/kelly/backtest-ai/kelly-ai-macro-exhaustive-report.md` 的审计结论。审计由 researcher 用 node 复跑全部数字 + git 溯源逐项核对完成。**原报告的数字基本忠实于 /tmp 脚本,但存在 1 个根因性错误(扫描空间漏掉用户基准"4组合全开")+ 多处结论性错误**。原报告"穷举覆盖 2728"的声称,对用户真正关心的"4组合全开"配置是**假的**。
>
> 状态:审计完成;原报告回炉重写为**待办**(见文末),由新会话推进。

## 总判定
报告里的数字本身基本忠实于 /tmp 脚本(排名 1436/2728、推荐 G 46.33%/+3.33pp、分周期、每K档最优等均复跑一致),但存在 **1 个根因性错误(扫描空间漏掉用户基准配置)+ 1 处对账事实错误 + 1 处推荐选错 + 2 处术语/计数错误**。报告"穷举覆盖 2728"的声称对用户真正关心的"4组合全开"配置是**假的**。

---

## 错误清单

### 错误 1(根因,最严重):扫描空间从未覆盖"4组合全开"配置,报告却以"穷举"自居
- **报告声称**:§一"2728 个去重配置(全扫)"覆盖了 AI宏基线/空基线+单键+移除+组合2-5元+二阶交互+全开参照;§二把"推荐 AI宏"(A 48.25% / F 51.04% / G 46.33%)当作穷举结论。
- **实际**:`/tmp/kelly_phase4.js` 的组合候选键 `CAND = [excludeMonth, a45, a5, v4g, n3, r8, v4f, v4m, v4b, n6MidMay]`(`/tmp/kelly_phase4.js:7-8`),**不含 v4d、不含 greedy15**;组合仅 2-5 元。`/tmp/kelly_phase5.js` 只做 `excludeMonth/a45 + 1 other` 的三元组。用户基准"4组合全开"= AI base + `n3+v4d+r8+greedy15`(4 个加键,见 `static-site/lab.js:8111-8148` `_kellyComboPresets`),因 v4d/greedy15 不在 CAND、且是 4 元组合超出三元扫描,从未被评估。
- **证据**:node 搜 master_results.json `["n3NovSpecialMon","v4d","r8PureNonMay","greedy15"]` 同时存在 -> `NOT FOUND (never scanned)`;全库含 v4d 仅 12 条、含 greedy15 仅 12 条(都是 phase1 单加 + phase5 三元,无完整组合)。
- **后果**:用户基准(4组合全开)实测 A 60-71%(K1 71.03% / K2 61.16% / K3 64.00%),而报告"推荐"仅 A 48.25%——**报告的"推荐"比用户已知可达水平低 13-23pp**,这正是用户说"这一看就没做到降亏第一要素"的根因。
- **根因**:穷举 agent 把"组合降亏预设宏"(`_kellyComboPresets` 4 个)与"单标志 toggle"割裂,候选集只取了 Phase1 单键正边际的 10 键,v4d(12月+周二+辅关注+低分)/greedy15(最大化降亏组合成员)因 standalone 比值/口径被排除在组合空间外,导致 4 组合的并集配置成盲区(违反 E12 字段覆盖核对)。

### 错误 2(对账事实错误):§八误称落地默认"未含 exclSpecialBear/J1/J2"
- **报告原文**(§八,第79行):已上线 90f948e3c "已落地只提了 n2 + 替换 A45/A5,**未含 exclSpecialBear/J1/J2/excludeMonth 全量**"。
- **实际**:`git show 90f948e3c` commit message 明写"_kellyDefaultFilters() 默认改为 AI宏 **5开关: excludeSpecialBear+J1+J2+n2NovSpecialIndustry+positionCap(K=2)**";`static-site/lab.js:7249-7273` `_kellyDefaultFilters()` 逐键确认 `excludeSpecialBear:true, janMidRating:true, janMidSpecial:true, n2NovSpecialIndustry:true, positionCap:true, positionCapK:2`。
- **正确关系**:落地默认 toggle 键 = {n2, exclSpecialBear, J1, J2}(4 个);穷举推荐 = 落地默认 + {excludeMonth, A45}(多 2 个)。即推荐 = 落地默认再加 excludeMonth+A45,而非报告说的"落地只提了 n2、其余都没含"。
- **J1/J2 语义已确认**:`lab.js:8285-8286` 标签 "J1 1月中旬+mid评级"=`janMidRating`,"J2 1月中旬+追关注"=`janMidSpecial`。报告"6 键(n2+exclSpecialBear+J1+J2+excludeMonth+A45)"的标签与 `makeFilters('ai',['excludeMonth','a45NovMidLateSpecial'],[],2)` 实际评估键集**一致**(AI_BASE 4 on + NEWAI 2 add = 6 toggle),**这点不是错误**。

### 错误 3(推荐选错):§二"推荐"既非扫描自身最优,也违反用户"降亏=收益高"原则
- **报告**:推荐 = AI base + excludeMonth + A45,G 46.33% / 净利 106.6万(-21万 vs 现默认 127.7万),A 48.25% / F 51.04%。
- **扫描自身更优者(报告 §六已列却未采用)**:K1 `exclM+a45+greedy15` A 73.25%/F 72.20%;K2 同配置 A 64.69%;K1 `exclM+a45+v4m` G 52.68%。推荐值全面低于这些。
- **§三内部矛盾**:§三列出 K2 G 最优 = `exclM+a45+v4f+v4m` 46.53%,但 §二推荐 46.33%(`exclM+a45`,少了 v4f+v4m),报告未解释为何不采用自己找到的 K2 最优。
- **违反用户原则**:推荐 G 收益率仅 +3.33pp 而**净利 -21万**,本质是"砍量提率"(concCap 297万->230万、笔数 2325->1889),`lab.js:8231` tooltip 明确警告这种口径是"收益率↑vs净利↓的权衡(砍量)"非真降亏。用户原话"降亏就等于收益会高,收益不是最高如何证明降亏有效"——推荐配置无法证明降亏有效。
- **4组合全开对比(同 K2)**:A 61.16%(+13pp vs 推荐 48.25%)且净利 13.5万(+5.2万 vs 推荐 8.3万);F 60.35%(+9pp)且净利 19.3万(+6.3万)。A/F 模式下 4组合全开**收益与净利双升**,才是符合用户原则的配置,但扫描漏掉了它。

### 错误 4(术语混淆):§一"全开参照 | 1"指 ALL_ON(全 31 toggle),≠ 用户的"4组合全开"
- **报告**:"全开参照 | 1"指 phase5 的 ALL_ON = AI base + 全部 27 个 off 键。
- **实测 ALL_ON**:K1 A 51.14% / F 46.55% / **G 6.11%**(灾难性);K2 A 48.65% / G 11.65%。这跟用户/项目的"4组合全开"(4 个预设宏,A 71% / G 47%)完全不是一回事。
- **后果**:报告用"全开参照"一词制造已覆盖"全开"的假象,实际覆盖的是无差别全开(含大量有害 toggle),恰好掩盖了"4组合全开从未被扫描"这一缺口。

### 错误 5(计数小错):§一"全开参照 | 1"应为 4
- phase5 对 posK=1/2/3/4 各生成 1 条 ALL_ON(`kelly_phase5.js:27-29`),master 去重后保留 4 条(K1/K2/K3/K4 各一,node 查 ALL_ON 输出 4 行)。报告写"1"。

---

## 报告里**可信**的数字(已 node 复跑逐项核对一致)
- §二推荐三模式数表 A 48.25%/F 51.04%/G 46.33% 及 +pp、净利、concCap、回撤、calmar -> 与 `kelly_rec.js` 输出逐位一致。
- §二"现默认 43.00% / 净利127.7万 / n=2325 / concCap=297万 / 回撤4.95% / calmar=3.68" -> 一致;且经 `git show 90f948e3c` + `lab.js:7249-7273` 确认 = 落地默认(口径正确)。
- §三每K档 G 最优(K1 52.68/K2 46.53/K3 44.28/K4 43.20)及 K 档排序 -> 与 `kelly_final_analysis.js` 一致。
- §四排名 1436/2728、被 1435 超过、非K1 757 -> 与 `kelly_final_analysis2.js` 一致。
- §五非K1 G TOP10、§六每posK跨模式最优(K1 A 73.25/K2 A 64.69/K3 A 66.42/K4 A 63.55) -> 一致。
- §七分周期(y1/y3/y5/y10/all 的 dRet、dProfit) -> 与 `kelly_rec.js` evaluatePeriod 输出一致。

## 报告里**不可信/需修正**的结论
- §二"推荐 AI宏"作为穷举结论 -> 不可信(扫描空间漏 4组合全开;且非扫描自身最优)。
- §八对账段落 -> 事实错误(误称落地默认未含 exclSpecialBear/J1/J2)。
- §一"全开参照" -> 术语混淆 + 计数错。
- 报告整体"穷举覆盖"自居 -> 对 4组合预设宏空间不成立。

---

## "推荐 AI宏"到底该是哪个配置(若可判断)
基于实测数据,符合用户"降亏=收益高"原则、且已在项目 UI 落地的配置是 **4组合全开 = AI base(落地默认) + n3 + v4d + r8 + greedy15**(即勾选 4 个组合预设宏:年末季节+稳健核心+最大化降亏+1月调整),`posK` 按需选档:

| K | A ret | A 净利 | F ret | F 净利 | G ret | G 净利 | G concCap |
|---|---|---|---|---|---|---|---|
| 1 | 71.03% | 7.8万 | 69.47% | 11.1万 | 46.77% | 64.1万 | 137万 |
| 2 | 61.16% | 13.5万 | 60.35% | 19.3万 | 40.84% | 103.7万 | 254万 |
| 3 | 64.00% | 21.1万 | 62.23% | 29.9万 | 40.52% | 134.1万 | 331万 |
| 4 | 61.73% | 27.2万 | 60.41% | 38.7万 | 40.65% | 160.2万 | 394万 |

- A/F 模式:4组合全开相比现默认收益与净利**双升**(K2 A +13pp/+5.2万,F +9pp/+6.3万),证明降亏有效。
- G 模式:4组合全开收益略降(40.84% vs 43.00%)、净利降,但 A/F 已达用户基准;G 模式下若要收益与净利兼顾,K1 `exclM+a45+v4m`(G 52.68%/70.1万)是扫描内可达的最高 G 收益,但属 K1 激进档。
- 该配置的 A 模式数(K1 71.03 / K2 61.16 / K3 64.00)已被 `lab.js:8207-8210` `_pcRating`(2026-08-13 另一位 researcher 回测定稿)采用并上线为"K档位评级标注"展示,口径=全开4组合+A模式+每笔1万+etf_def+全周期,与本审计复算逐位吻合。

---

## 待办:原报告回炉步骤(交新会话推进)
1. **补跑 4组合全开 + 4组合各子集(去一/叠加边际)纳入穷举空间**——把 v4d、greedy15 加入组合候选集,补全 4 元组合扫描,使其真正"穷举"用户基准。
2. **修正 §八对账**——落地默认实际含 exclSpecialBear/J1/J2(4 toggle),非"只提了 n2"。
3. **重选"推荐"为 4组合全开**(或明确说明 G 模式的取舍:A/F 双升已达用户基准,G 模式另有 K1 `exclM+a45+v4m` 极致档可选)。
4. **"全开参照"改称"ALL_ON 全 toggle"**并与"4组合全开"区分;计数 1->4。
5. 合格线口径(用户决定性校验):**现有默认打勾+4组合降亏 A/F/G 保底 60%+,K=1 可达 70%+**;任何"推荐 AI宏"若 A/F < 60% 或 K1 < 70% = 未达降亏第一要素,不合格。

## 已验证方法/数据源清单
- node 复跑 `/tmp/kelly_rec.js`、`kelly_final_analysis.js`、`kelly_final_analysis2.js`(依赖 `kelly_exhaustive_lib.js` + `master_results.json` 同目录)。
- node inline 评估 4组合全开配置(`makeFilters('ai',['n3NovSpecialMon','v4d','r8PureNonMay','greedy15'],[],K)`)与 ALL_ON。
- node 搜 `master_results.json` 键集存在性。
- `git show 90f948e3c` + 读 `static-site/lab.js:7249-7273`(_kellyDefaultFilters)、`8111-8148`(_kellyComboPresets)、`8207-8210`(_pcRating)、`8285-8286`(J1/J2 标签)。
- 读 `/tmp/kelly_phase4.js`(CAND)、`kelly_phase5.js`(triples+ALL_ON)、`kelly_master.js`(去重合并)。

## 相关文件(绝对路径)
- 被审计报告:`/Users/linhuichen/code/trade/docs/kelly/backtest-ai/kelly-ai-macro-exhaustive-report.md`
- 原始产物:`/tmp/kelly_master_results.json`、`/tmp/kelly_rec.js`、`/tmp/kelly_final_analysis.js`、`/tmp/kelly_final_analysis2.js`、`/tmp/kelly_exhaustive_lib.js`、`/tmp/kelly_phase4.js`、`/tmp/kelly_phase5.js`、`/tmp/kelly_master.js`、`/tmp/agent-progress-kelly-exhaustive.md`
- 落地默认/组合预设/K档评级:`/Users/linhuichen/code/trade/static-site/lab.js`(:7249-7273 / :8111-8148 / :8207-8210 / :8285-8286)
- 审计进度文件:`/tmp/agent-progress-exhaustive-audit.md`
