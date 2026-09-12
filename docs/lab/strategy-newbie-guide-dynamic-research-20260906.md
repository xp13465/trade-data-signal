# 策略实验页新手引导卡「固化内容 vs 当前 tab 脱节」调研(2026-09-06)

> TaskList #55 · 纯调研(只读不改代码,结论供主控/实施 agent 参考)

- **目的**:定位 lab 策略实验页新手引导卡固化实现的现状与作用范围,盘点全部 tab/子模式,给出引导文案动态化方案与 §21 公示点,供后续实施动态化。
- **方法口径**:基于当前 main(8e386294a)`static-site/lab.js` 源码 grep -n 精准定位 + `git show 6e7b112` 回溯首建 commit;不整读大文件,不跑回测。测试基准 = current baseline(纯调研,不涉及回测数字)。
- **结论一句话**:新手引导卡 `_labNewbieGuideHTML()` 是硬编码统一文案(L2444-2470),在 `renderSignalLab()` L5845-5846 无条件插入,9 个子模式全显示且不随 tab 变化;其中 sigkelly/aiwarn/aiscore/ablation/symmetry/paramscan 等 6 个子模式的引导内容与页面实际内容完全不相关,建议动态化——推荐方案①`_labNewbieGuideHTML(subMode)` 收参 + 内部文案表 switch。

---

## 1. 现状

### 1.1 固化文案原文(`static-site/lab.js` L2444-2470)

函数 `_labNewbieGuideHTML()`(无参数,返回固定 HTML,`<details>` 原生折叠默认展开):

- 标题:`🧭 新手引导 · 不熟悉回测?先看这三步`
- **①** 先看「推荐榜(综合评分)」:综合评分 = 收益率(35%)+胜率(25%)+回撤倒数(15%)+风险调整(15%)+样本量(10%),评分越高综合表现越好,从高到低看起。
- **②** 点开看回测净值曲线:点击任意配对查看完整净值曲线与逐笔交易记录,确认收益曲线是否平滑向上、回撤是否可承受。
- **③** 看「二次测试」三切片是否稳健:标⭐️的配对可进入二次测试,看①分年回测(防某年暴利拉高)②样本外(防过拟合)③极端行情(2015股灾/2018熊/2020疫情/2024反弹各 regime 回撤),三者都稳才是真稳健。
- **💡 提示**:融合实验中 `n<30` 的候选已标灰「样本不足,仅供参考」——样本量小统计意义弱,收益/胜率易被极端值拉偏,谨慎参考。

### 1.2 无条件插入点

`renderSignalLab()`(L5831)内,`content.innerHTML = ""` 之后:

- L5845-5846:`// P2-3: 新手引导卡(置顶常驻,可折叠,全子模式可见)` + `content.insertAdjacentHTML("beforeend", _labNewbieGuideHTML());`
- 位置:合规声明(`_labTopDisclaimerHTML`)之后、二级导航(`_renderLabSubNav`)之前。
- **作用范围**:9 个子模式(`fusion/retest/ablation/symmetry/paramscan/aiwarn/aiscore/sigkelly/single`)列表页全显示;**无任何按 tab/子模式变化的条件**。
- **详情页除外**:`renderSignalLab()` L5833-5838 有选中策略且非上述子模式时提前 `await renderLabDetail()` 并 return,引导卡不显示。

### 1.3 历史 commit 6e7b112(首建)当时做了什么

`git show 6e7b112`(2026-07-19,feat: P2策略实验室新手引导卡+融合候选n<30标灰)确认:

1. 新增 `_labNewbieGuideHTML()` 置顶引导卡(三步导览:推荐榜起点/净值曲线/二次测试三切片),**全子模式常驻**——首建时就是固化统一文案,未按 tab 区分。
2. 融合候选(91对:fusion/buy_buy/sell_sell)n<30 标灰「样本不足,仅供参考」;单一配对(buy_sell)沿用 n<10 门槛。
3. 榜单 legend 按子模式切换说明文案(fusion vs 非 fusion,`_labRankHTML` L3011-3017 `sampleNote`)。
4. lab.css 配套:蓝主题引导卡 + 灰态 `.lab-rank-low-n` + 橙底标签。

> 结论:6e7b112 只做了「legend 按子模式变」,引导卡本体从出生起就是统一的,「脱节」是设计遗留非回归。

---

## 2. 全部 tab/子模式清单(9 子模式 + 详情页)

| labSubMode | tab 名 | 核心内容 | 引导卡错位点 |
|---|---|---|---|
| single(默认) | 单一信号实验 | 策略卡列表(左)+ 配对排行(右:推荐/收益率/胜率榜,近5/3/1年窗口) | 现有三步基本对口 |
| fusion | 融合信号实验 | 融合策略卡(阶段一仅元数据)+ 回测配对对比榜 | ①勉强、💡n<30 对口;②③部分对口 |
| retest | 🔬 二次测试实验 | 标⭐️配对三切片验证(分年/样本外/极端行情) | ③对口;①②无关 |
| ablation | 🧩 信号拆解 | 6硬编码融合策略 × 3指数 N-1 消融 + 组件贡献柱状图 | 完全不相关 |
| symmetry | ⚖️ 多空对称 | top8 配对做多/做空 + 各指数对比柱状图 | 完全不相关 |
| paramscan | 🎛 参数扫描 | 7策略概览 + 参数网格热力图/柱状图 | 完全不相关 |
| aiwarn | 🚨 AI预警 | 情绪告警 + 维度拆解 + 历史类比 | 完全不对口(非回测) |
| aiscore | 📈 AI评分 | ETF 买清单/卖清单 + 持仓自查 | 完全不对口(非回测) |
| sigkelly | 📊 信号凯利回测 | 6象限×4模式×3周期半凯利仓位回测 + AI报告 | 完全不对口(现有三步是配对回测,与凯利无关) |
| 详情页 | renderLabDetail | 单一策略完整净值曲线 + 逐笔交易 | 引导卡不显示(提前 return) |

子模式结构(`_renderLabSubNav` L3629-3721):二级 nav 4 父 tab `scan(信号扫描)/experiment(信号实验)/retest/custom(自定义分析)`,三级子 tab:scan→ablation/symmetry/paramscan,experiment→single/fusion,custom→aiwarn/aiscore/sigkelly。hash 格式 `#lab?sub={labSubMode}` 保位(L12968-12989)。

### 各模式引导文案建议(不写代码,给实施方向)

- **single**:保留现有三步原文(①推荐榜→②净值曲线→③二次测试),最对口,微调即可。
- **fusion**:第①步改为「看融合配对榜」,第③步保留,💡 提示保留融合 n<30 灰态说明(已是融合专有);补一句「阶段一仅元数据」定位。
- **retest**:三步聚焦「①选标⭐️配对 ②看三切片(分年/样本外/极端)③三切片都稳才是真稳健」,去掉①②回测榜步骤。
- **ablation**:「①选指数 ②看 6 策略 N-1 子集消融(N-1=去掉某组件看贡献)③右栏组件贡献柱状图定主次」。
- **symmetry**:「①选指数 ②top8 配对做多/做空对照 ③右栏指数对比柱状图」。
- **paramscan**:「①选策略 ②选指数 ③参数网格热力图/柱状图看参数敏感性(颜色深浅=指标好坏)」。
- **aiwarn**:「①选标的 ②看情绪告警信号 ③维度拆解 + 历史类比」——注意这是 AI 分析非回测,三步文案要换语义。
- **aiscore**:「①输入持仓 ETF 自查 ②看买清单/卖清单 ③持有建议」——非回测语义。
- **sigkelly**:「①选周期/参数 ②6象限半凯利仓位回测 ③AI 报告(Kelly 比例=仓位建议)」——凯利口径,完全替换现有三步。

---

## 3. 动态化方案对比

### 方案①(推荐):`_labNewbieGuideHTML(subMode)` 收参 + 内部文案表 switch

- **改动范围**:
  - `static-site/lab.js:2444-2470` `_labNewbieGuideHTML()` 函数签名加 `subMode` 参数,内部按 9 个模式各配一段三步文案(文案表/switch,默认 single=现状原文)
  - `static-site/lab.js:5845-5846` 调用处改为 `_labNewbieGuideHTML(state.labSubMode)`
- **影响面**:单函数集中式,一处改一处调用;新加子模式只加一个分支;文案表一眼看全,易 review。
- **§23.7 兼容性**:默认行为会变(引导文案随 tab 变化)——这是需求本意,属「修正体验」,建议经用户确认后实施;single 默认文案=现状原文,不破坏单一信号模式既有展示。

### 方案②(备选):切 tab 时 DOM 替换引导卡 body 某区块

- **改动范围**:9 个子模式渲染函数(`renderFusionLab/RetestLab/AblationLab/SymmetryLab/ParamScanLab/CustomAnalyzeLab/AIScoreListLab/SigKellyLab`)各自 querySelector 引导卡并替换 body,或每次 `renderSignalLab` 后按 subMode 重插。
- **影响面**:分散 9 处、易漏、与各模式渲染耦合;引导卡 body 选择器与结构耦合,后续改结构易破。
- **§23.7 兼容性**:同上;但分散改动回归面更大。

### 推荐

**方案①**。理由:集中式单点、易维护、默认 single 文案不变、回归面最小,符合「改造现有 details 卡按 tab 渲染不同文案」的最小侵入路径。

---

## 4. §21 公示点

引导卡文案与 `purpose-notes.js` 的 `lab.single / lab.fusion / lab.retest / lab.ablation / lab.symmetry / lab.paramscan / lab.aiscore / lab.sigkelly` 各 `PURPOSE_NOTES` 块为**同口径来源**:

- 改引导卡时若引用公式/规则(综合评分权重 35/25/15/15/10、⭐️进二次测试门槛、凯利比例含义等),必须与 purpose-notes 逐字对齐,防两处说法打架(§23.13 口径三源核对)。
- 引导卡本身是纯前端文案,不动后端算法,不要求 bump 测试基准(§5.4⑥ 只约束 AI推荐/降亏过滤核心算法默认组合)。
- 若从 purpose-notes 拷贝规则文案,注意 purpose-notes 是单一事实源,引导卡不写变体。

---

## 5. 证据锚点清单

| 证据 | 位置 |
|---|---|
| 引导卡固化文案本体 | `static-site/lab.js:2444-2470`(`_labNewbieGuideHTML()`) |
| 无条件插入点 | `static-site/lab.js:5845-5846` |
| 子模式分发逻辑 | `static-site/lab.js:5831-5915`(`renderSignalLab()`) |
| 子模式导航定义 | `static-site/lab.js:3629-3721`(`_renderLabSubNav()`) |
| 子模式 hash 保位 | `static-site/lab.js:12968-12989` |
| 各子模式渲染函数入口 | `renderFusionLab:3724` / `renderRetestLab:4496` / `renderAblationLab:5397` / `renderSymmetryLab:5518` / `renderParamScanLab:5633` / `renderCustomAnalyzeLab:6058` / `renderAIScoreListLab:6297` / `renderSigKellyLab:9111` / `renderLabDetail:2474` |
| 首建 commit | `6e7b112`(2026-07-19,feat: P2策略实验室新手引导卡+融合候选n<30标灰) |
| legend 按子模式切换(6e7b112 同步做的) | `static-site/lab.js:3011-3017`(`_labRankHTML` `sampleNote`) |

---

## 复现

- **脚本**:无(纯静态源码调研,无回测脚本)。
- **输入依赖**:`static-site/lab.js`(当前 main 8e386294a);`git show 6e7b112`。
- **重跑命令**:`grep -n "_labNewbieGuideHTML" static-site/lab.js` 定位插入点;`sed -n '2444,2470p' static-site/lab.js` 读固化文案;`git show 6e7b112 -- static-site/lab.js` 回溯首建 diff。
- **数据截止/版本**:代码 = main @ 8e386294a(2026-09-06 调研当日 HEAD)。
- **关键口径**:引导卡固化文案 = `_labNewbieGuideHTML()` 返回的固定 HTML,9 子模式列表页全显示,详情页(有选中策略)不显示;动态化推荐方案①收参 + switch。
