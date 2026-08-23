# g2 门疑似失真完整影响面审计(2026-08-23,researcher 只读核查)

> 触发:mine23-24-review E7 发现 `r2_common.py` L113 附近 `ma_impr = base - new` 疑似反号 + `mine22_joint.py` L139 疑似二次取反,历史 json 里所有组合的 `gates_pass`/`g2` 字段可信度存疑。
> 本文只读核查,未改任何既有报告/json/脚本;全部数字现算,锚点 P0=+66,530.38 / P1=+73,102.53 已核对(`data/mine24_compare.json` anchor / `data/mine24_global_search.json` anchor 逐位一致)。

## 结论一句话

**门②确实失真,根因只有一处:`r2_common.py` L113 把「5-8月改善」算成了 base−new(与字段名 improve 相反),导致 `ma_impr>=2500` 的实际语义=「过滤后 5-8 月比基线至少多亏 2500 才过门」。** `mine22_joint.py` L139 不参与门判定(门只在 three_gates 内判一次),它污染的是导出列 d_mayaug/d_apr → 帕累托支配判定与 dual_top3 筛选,性质是「把恶化当改善参与越大越好比较」。错误方向是**双向的**:把真实改善≥+2500 的组合误判挂门(false→true 方向翻转居多),也把真实恶化≥2500 的组合误判过门(true→false,如 mine11 h_slope20)。数学上两口径不可能同时 PASS(要求 base−new≥2500 且 ≤−2500),实测全库两口径同过=0,验证自洽。

## ① 代码定真相

### 取反链(生成端→消费端→门比较)

```
r2_common.py three_gates() (L104-132):
  L112  apr_hurt = apr_new['total'] - apr_base['total']     # = new − base ✓ 正确(负=4月误伤)
  L113  ma_impr = may_aug_base['total'] - may_aug_new['total']  # = base − new ✗ 反了!
  L128  g2 = apr_hurt >= -1500 and ma_impr >= 2500          # 第二条实际语义=5-8月多亏≥2500 才过
同文件自相矛盾证据:
  L95   diff_detail.net_improve = -blocked_pnl + added_pnl  # 改善为正(new−base 口径)
  L137  forward_2024_26.net_improve = n24 - b24             # 改善为正(new−base 口径)
  → 同一引擎里三个"改善"量,两个 new−base、一个 base−new,L113 属笔误级反号。
```

消费端(mine22_joint.py L139 / mine21_bigtour.py L171 / mine19_pareto.py L111 同款):
```python
d_mayaug=g['mayaug_improve'], d_apr=-g['apr_hurt'],
```
- 门判定只发生在 three_gates 内部一次;L139 不改 gates_pass/g2 布尔值(纠正任务假设:「二次取反叠加搞反门」不成立)。
- 但 d_mayaug/d_apr 进入 KEYS 8 维帕累托支配(mine19 L124 / mine21 L191 / mine22 L156,`all(a[k]>=b[k]-EPS)` 全维度越大越好):d_mayaug 实际是「5-8月恶化额」、d_apr=-apr_hurt=base-new 实际是「4月恶化额」,均被当成收益最大化 → **前沿偏好坏组合**。
- mine22_joint.py L178 dual_top3 筛选 `d_1y>0 and d_mayaug>0 and d_apr>=-250`:本意「近端双正」,实际选出的是 5-8 月恶化的组合(见下)。
- 打印标签错位:mine16_candidates.py L105 把 mayaug_improve 标成「5-8月改善」;mine19/21/22 把 d_apr 标成「4月保」——标签语义与实际值方向相反。

### 正确语义权威定义

round2 报告 §3 标题(L62)/three_gates docstring(L105):「门② 2026双向(4月误伤>=-1500 且 5-8月改善>=+2500)」。改善=过滤后相对基线多赚=new−base。

### 独立铁证(不经 r2_common,用 mine24_compare.json 月度绝对值直接算)

`projects[*].months26`(键 '2026-04'/'2026-05~08'):

| 项目 | 4月绝对 | 5-8月绝对 | 全年 |
|---|---|---|---|
| P0_8键 | +13,283 | −5,166 | +5,626 |
| P1_9键 | +13,283 | −1,030 | +7,490 |
| A_on9 | +14,842 | +1,131 | +15,574 |
| NEW_14键 | +11,222 | −1,340 | +10,016 |

直接算真实改善(new−base):
- A_on9 vs P1:4月 **+1,558.34**(= mine22 存档 apr_hurt +1558.34 ✓)、5-8月 **+2,161.38**(= −(存档 mayaug −2161.38) ✓)
- NEW vs P0:4月 **−2,061.67**(= 存档 apr_hurt ✓)、5-8月 **+3,825.35**(= −(存档 mayaug −3825.35)✓)

→ 字段映射坐实:`apr_hurt=new−base`(正确)、json 里 `mayaug/d_mayaug/mayaug_improve` 一律=base−new,**真实改善取负号才对**。

### round3 脚本独立实现,符号正确不受影响

`scripts/sim_loss_mining_round3_substitute_20260822/mine14_substitute_validate.py`:
- L66 `apr2026 = new − base`、L67 `mayaug = new − base`、L108 `g2 = delta>=1500 and apr2026>=-1500 and mayaug>=0` —— 全对。
→ round3 报告(R2a/R2b/R2g 四重检验全过等结论)**可信,无需修正**。一轮 `mine11_positionfill_recheck.py` L151-152 自实现门同样符号正确(imp58/hurt4 均 new−base),一轮报告 §14.3 不受影响。

## ② 数据影响面(json 全量重算,正确 g2=(apr_hurt>=−1500 and −mayaug>=2500))

| json | 组合数 | g2翻转 | 方向拆分 | 三门全过(g1+g2+g3) 存档→正确 |
|---|---|---|---|---|
| mine11_univariate.json | 429 | 7 | 6 false→true + 1 true→false(h_slope20) | 0 → **1**(div_yield q0.5low,net_improve +14,392) |
| mine12_equity.json | 9 | 2 | 2 false→true(consec3/consec5;g3 仍挂,pass_all 不变) | 0 → 0 |
| mine13_calendar.json | 17 | 0 | — | 0 → 0 |
| mine14_subgroup.json | 3,824 | 242 | 双向都有 | 0 → **67**(top=div_yieldL0&牛主升 +10,808) |
| mine16_candidates.json | 5 | 0 | —(但打印/表格数字方向错) | — |
| mine18_combos.json | 31 | 0 | — | — |
| mine19_pareto.json | 31 | — | 前沿 7 个 → 正确口径 **11 个**(新增 N1+D1+N2/N1+T1+D1+N2/N1+T1+N2/T1+D1,踢出 0) | — |
| mine20_pool.json | 18 | 2 | D2/A1 false→true | — |
| mine21_tour.json | 2,047 | 124 | 全 false→true | 0 → **108**;帕累托 40 非劣 → **34**(保留27/踢出13/新增7) |
| mine22_joint.json | 16,383 | **1,086** | 全 false→true | 0 → **907**;gates_pass 分布 {1:7372,2:9011} → {1:7193,2:8283,3:907};帕累托 83 非劣 → **63**(保留34/踢出49/新增29);dual_top3 三条全错(真实全是 5-8月恶化 −309/−309/−97 且前两条 4月误伤 1,648) |
| mine24_global_search.json robust | 12 | 0 | g2 全 false 不翻(apr_hurt −2,061.67/−5,721.04 <−1500 挂死第一条);但 mayaug 数值方向解读须反转(NEW 真实 5-8月改善 +3,825 达标) | — |

不受影响(已逐一排查):mine23_final_compare.py / mine23_compare.json / mine24_compare.json / mine25_longline_operable.json(均不用 three_gates,无门字段);round3 全部脚本与数据;一轮 results.json/mine11_positionfill_recheck。

关键新事实(正确口径下):
- mine22 三门全过 top:`T1+Q1+M1+P1+V1+R1+R2a+R2b+R2g` d_full=+43,964 / 4月仅误伤787 / 5-8月改善+3,790(次席 T1+Q1+M1+P1+R1+R2abc +42,465)。「三道门无组合全过」结论被推翻。
- A/B/C 三方案的 g2 与 gates_pass **布尔均不翻**(A 2/3、B 2/3、C 2/3 维持):A 挂因=5-8月改善+2,161<2,500(真实);B 挂因=5-8月改善−97(微恶化,非存档含义的"+97");C 挂因=4月误伤2,651。
- abs_top/safe_top3 名单不变(d_full 排序+d_1y>0 筛选不涉符号);dual_top3 全错需重选。
- NEW(14键)门②:两条中「5-8月改善≥2500」其实达标(+3,825),唯一挂因=4月误伤 2,061(>1,500)。

## ③ 报告结论影响清单

### sim-loss-mining-round2-20260822.md(重灾区)

| 位置 | 当前表述 | 重算后翻不翻 | 应改成 |
|---|---|---|---|
| L32(N2 行) | 「5-8月改善 +1,594 差一门」 | 结论✗不变,**数字方向反** | N2 真实 5-8月改善=−1,594(反向恶化),差门更远 |
| L62(§3 标题) | 三道门定义 | 定义本身对 | 补注:历史数据 g2 由带 bug 引擎产出,以本文审计为准 |
| L65 | 「g1 过425/g2 过1/g3 过16,**无一同时过三门**」 | **翻** | 正确口径:g2 过6,三门全过1(div_yield q0.5low) |
| L73(§3.2 equity 族 9 条全落选) | 全落选 | 部分**翻** | consec3/consec5 的 g2 在正确口径下过(g3 仍挂,维持落选,但挂因表述要改) |
| L79(§3.3 日历族) | 16 条全落选 | 不翻 | — |
| L86 | 「g2 只有 34 条过(全是 buy_aux 类且 G3 全挂)」 | **翻** | 正确口径 g2 过208,其中 67 条三门全过(非全 buy_aux) |
| L94-96(§4 五候选表+核心句) | N1「5-8月-76」/D1「5-8月-930」/N2「5-8月+1,594 差一门」;「没有一条通过G2…候选1仍是唯一…」 | 判定✗全不翻,**括号内数字方向多数反**;「候选1唯一」须限定范围 | 表内 5-8 月数字取负(真实改善 +76/+930/−1,594);核心句改为「本批5条无一过G2」并注明全库层面见修正后统计 |
| L167/L170/L303/L317(§15.7 mine21) | 「帕累托40」「2047 中2007被支配,40个非劣」 | **变** | 正确口径 34 非劣;前沿名单 13 出 7 进 |
| L245-267(§15.5 mine19) | 「收敛到7个非劣」+四型推荐 | **变** | 正确口径 11 非劣(新增4);四型推荐须重选 |
| L361(§15.10) | 「83 非劣/16,300 被支配」 | **变** | 63 非劣/16,320 被支配 |
| L368(B 行「前沿内双正王」) | B=T1+Q1+M1+R1+R2b+R2g,gates_pass=2/3 | gp 不翻,**「双正王」名头错** | B 真实 4月零误伤/5-8月改善 −97(持平微负),名头改「近端持平王」或重选 |
| L383(A 的 G2 挂因) | 「挂因=5-8月改善+2,161未达+2,500;4月经核实不误伤反多赚+1,558」 | **表述恰好正确**(此前审查者已换算对) | 不改数字;建议删去「原表述4月误伤」的历史包袱保留现句 |
| L575 | 「三道门仍无组合全过(A 门2/3,G2挂在5-8月改善幅度未达标…)」 | 半翻 | A 部分(门2/3、挂因5-8月)对;「无组合全过」全局表述删/限定 |
| L611(NEW 门②行) | 「4月误伤−2,061.67 / 5-8月比8键基线多亏 −3,825.35」 | **方向反** | 5-8月实为比基线**多赚 +3,825.35(达标)**;门②FAIL 唯一挂因=4月误伤2,061>1,500 |
| L622 | 「非『改善幅度不足』而是实打实多亏…窄门天然不适用」 | **方向反+论证弱化** | NEW 其实过了「5-8月改善」那条,只挂4月一条;「窄门不适用」辩解不再成立,改为如实标「仅4月一项超限」 |
| L628 | 同上 mayaug 解读 | **方向反** | 同上;「A 同口径+1,558/+6,297」这句本身对(vs8键),保留 |
| L716 | 「5-8月 NEW −1,340 未转正(A +1,131)」 | 不翻(绝对额口径,正确) | — |

### mine23-24-review-20260823.md
- L112/L134:引用 gates 数字本身对,但解读列「mayaug=−3,825.35(5-8月比8键基线多亏3,825)」方向反 → 改为「5-8月改善+3,825(达标)」。
- L142(E6):同一句里 A 用了正确的 new−base 口径(+1,558/+6,297),NEW 却直读字段当「多亏」——自相矛盾,统一为 new−base 后重写:E6 的「近端弱项」结论仍成立(NEW 4月−2,062 vs A +1,558;5-8月 NEW+3,825 vs A+6,297),但理由从「实打实多亏」改「4月单项超限+5-8月改善弱于A」。

### memory(sim-loss-mining-combo-race-20260822.md)
- 「A …2026 当期负(4月-1,558/5-8月-2,161)」:**双重错**(把增量写成当期绝对额+符号反)。真实:A 当期 4月+14,842/5-8月+1,131 均为正;vs9键改善 +1,558/+2,161 均为正。
- 「B 双正王…4月零误伤/5-8月+97(2026当期最优段)」:**符号反**。真实 5-8月改善 −97(微恶化),「双正王」名头不成立。
- C 行、锚点、「83 非劣」提及(16383组合/83非劣)→ 待重跑后同步为 63。

### 不受影响报告
sim-loss-mining-round3-substitute-20260822.md(独立脚本符号正确)、sim-window-loss-mining-20260822.md(一轮门为另一套自实现,符号对)、sim-longline-operable-20260823.md、sim-combo-cheatsheet-20260823.md(无门字段;速查卡权威值取 mine24_compare.json,干净)。

## ④ 修正方案(implementer 工单草稿)

### 代码最小改动(3 处文件、共约 6 行)
1. `scripts/sim_window_loss_mining_20260822/r2_common.py` L113:
   `ma_impr = may_aug_base['total'] - may_aug_new['total']` → `ma_impr = may_aug_new['total'] - may_aug_base['total']`
   (docstring L105 同步写明「改善=new−base」;返回字段名 mayaug_improve 语义即归位)
2. `mine22_joint.py` L139 / `mine21_bigtour.py` L171 / `mine19_pareto.py` L111:
   `d_mayaug=g['mayaug_improve'], d_apr=-g['apr_hurt']` → `d_mayaug=g['mayaug_improve'], d_apr=g['apr_hurt']`
   (修好源头后 mayaug_improve 已=new−base;d_apr 去掉多余取负,即 4月改善、负=误伤,dual 条件 `d_apr>=-250` 语义自动恢复本意)
3. 标签/注释同步:dims_doc(mine19 L159-160「d_mayaug 5-8月减亏」「d_apr 4月保利润(=-apr_hurt)」→「5-8月改善(new−base)」「4月改善(负=误伤)」)、打印格式串里的「4月保」→「4月改善」、mine16 L105 标签已对不动。
- 注意 §23.7 冻结契约:这些是一次性回测脚本(非线上功能),修复属纯 bug 修复(§23.7④例外),不涉前端/生产。

### 需重跑的数据(命令;均在 scripts/sim_window_loss_mining_20260822/,依赖链从上到下)
```bash
cd docs/kelly/analysis/scripts/sim_window_loss_mining_20260822
python3 mine11_univariate.py && python3 mine12_equity.py && python3 mine13_calendar.py \
  && python3 mine14_subgroup.py && python3 mine16_candidates.py \
  && python3 mine18_detail.py && python3 mine18_combos.py && python3 mine19_pareto.py \
  && python3 mine20_pool.py && python3 mine21_bigtour.py && python3 mine22_joint.py \
  && python3 mine24_global_search.py
```
(mine17_modes 为被导入模块不单独跑;mine23_final_compare/mine24_compare/mine25 无门字段可不跑,但 mine24_global_search 重跑后建议复跑 mine24_compare 交叉断言一遍以防输入变化。)每脚本自带锚点断言:P1=+73,102.53(mine21/22)、P0=+66,530.38/P1=+73,102.53(mine23/24 系),断言不过立即停。
重跑后必做人工复核点(数据会说话,勿预设):①mine22 新 frontier/reps(尤其 dual_top3 重选)②三门全过 907 条名单是否稳定 ③robust.gates 的 mayaug 符号应全部转正。

### 报告文字修改清单
- round2 报告:按本文 §③ 表逐处(L32/L65/L73/L86/L94-96/L167/L170/L245/L303/L317/L361/L368/L575/L611/L622/L628;L383 保留)。
- mine23-24-review:L112/L134/L142 解读方向反转(E6 结论保留、理由重写)。
- memory `sim-loss-mining-combo-race-20260822.md`:A/B 两行方向修正 + 「83 非劣」→重跑后新值。
- README.md 索引:round2/round2 相关行补一句「g2 门 bug 修正见 g2-gate-audit-20260823.md」。

### 若选择不修正的替代口径
也可不改代码,统一在消费端约定「mayaug 字段一律取负读」——不推荐:字段名 improve 与值方向相反是长期地雷,且 mine19/21/22 帕累托支配判定已在用污染维度选方案(83 非劣名单、dual_top3 直接喂给了 A/B/C 提名),必须重算才有干净名单。

## 复现

- 脚本:本文所有重算均为一次性核查命令(内嵌于审计过程),核心可复现命令两段:
  1)字段映射交叉验证:`python3 - <<'EOF'`(读 `data/mine24_compare.json` projects[*].months26,计算 A_on9−P1_9键、NEW−P0_8键 的 2026-04 与 2026-05~08 差值,对照 `data/mine22_joint.json` combos[A_SUB].d_apr/d_mayaug 与 `data/mine24_global_search.json` robust[NEW].gates.apr_hurt/mayaug)
  2)全库重算:遍历 data/mine{11,12,13,14,16,18,20,21,22}_*.json 的 gates/d_mayaug/d_apr 字段,按 `correct_g2=(apr_hurt>=-1500 and -mayaug_stored>=2500)` 重算并与存档 g2 对比(本文 §② 表即输出)。
- 输入依赖:data/mine24_compare.json、data/mine22_joint.json、data/mine24_global_search.json、data/mine11_univariate.json、data/mine14_subgroup.json、data/mine21_tour.json 等(均 git 已跟踪于 docs/kelly/analysis/scripts/sim_window_loss_mining_20260822/data/)。
- 数据截止:signal_kelly_trades.json generated_at 2026-08-22 16:58(v1.1.4 弹窗口径,与挖掘轮一致)。
- 关键口径:门②=「4月误伤≥−1,500 且 5-8月改善≥+2,500」,改善一律=new−base;补位口径 K1 vs 9键(mine22 系)/vs 8键(mine24 robust 系)。
