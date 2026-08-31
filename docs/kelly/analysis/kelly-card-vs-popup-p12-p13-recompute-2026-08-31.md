# codex 外审 rev-20260830-002 P1-2/P1-3 数据复算收尾(2026-08-31)

> 触发:codex 外审 rev-20260830-002 FAIL 报告两条 P1 收尾(用户拍板 ref 链清理任务第 6 件)。P0(min 未重建/未合 main)已随 main-merge 闭环;P1-1 浏览器实测随 sim 分支收尾,不在本单。
> 测试基准:当前基准 v1.1.7 S06 基线(卡面=S06 动态+posCapK1+每日池+etf_main 费率;G/H/I 卡面套 NoBull 豁免+GIH sim)。
> 数据:signal_kelly_trades.json generated_at=2026-08-31 07:17;kelly_mode_s06_state.json=2026-08-28 21:16;accum_nav_map.json=2026-08-30 12:46。

## 结论一句话

**P1-2 共享核两份实现主路径逐位一致(48/48 nav 命中用例 pr/rp/hd/sell_price/flag 全同),唯一行为差异=null 入参防御深度(lab 版抛错 vs common 版防御返回),生产输入域不含 null,无数值漂移风险。P1-3 修复后口径下卡面与弹窗凡不涉及 GIH 仿真的指标全部逐位一致(非 GIH 42 行 total+holding 全同,G/I total 647=647 全同),剩余差异全部且仅来自「卡面 G/H/I 套 GIH 仿真、弹窗显示原始交易记录」这一方案 B 文档已声明的设计语义,非谓词/池 bug。**

## 三档互证

- **白话(P1-2)**:G/H/I 强平日的盈亏计算逻辑在首页弹窗(common.js)和实验室弹窗(lab.js)各写了一份,这份复算拿同一批真实交易、同一份净值表喂给两个函数,逐个数字对比——算出来的钱一分不差;只有"喂 null 会怎样"这种不该发生的输入,一份报错一份兜底。
- **白话(P1-3)**:评分卡上的笔数和点开弹窗看到的笔数,8-30 修复前用两套不同的过滤规则(所以对不上);修复后两边用同一套规则了,这份复算把修复后的弹窗口径重新算一遍——所有不涉及"仿真强平"的笔数全部对上。
- **场景**:什么时候看这份报告?①再有人质疑"卡面 N 笔 vs 弹窗 N 笔对不上"时,先分清问的是不是 G/H/I 的持仓中(那是仿真语义差,不是 bug);②动 G/H/I 强平/共享核代码后,重跑两个脚本确认没把对齐改破。
- **1:1 举例(P1-3)**:A 模式@全部周期,修复前弹窗(静态 NEW14 池)共 431 笔、持仓中 3 笔,卡面 611 笔/持仓中 5 笔——对不上;修复后弹窗(同走 S06 动态谓词+posCapK1)共 611 笔、持仓中 5 笔,与卡面 611/5 **逐位一致**。G 模式@全部周期:弹窗与卡面行集同为 647 笔(NoBull 池),卡面「持仓中」=10(套 P≤3d@10万 sim 强平后的仿真持仓),弹窗「持仓中」=50(原始交易记录未卖行)——数字不同是**两边指标定义不同**,弹窗从设计上就不做仿真。H 模式@全部周期:弹窗 647 笔 vs 卡面 373 笔,因为 H 卡面套「满仓不买@5万」仿真,持仓满 5 笔后不再买入,原始 647 行里只有 373 行真的成交——分母不同非计算错误。
- **1:1 举例(P1-2)**:拿 512480 这笔 G 模式真实买入(buy_price>0)在净值表命中日强平:common `_gihRealizeRealForce` 与 lab `_kellyAihlineRealizeReal` 返回 pr/rp/hd/sell_price/flag 五个字段**逐位相同**;把强平日换成 19990101(净值表没有的日子),两份都返回 `{pr:null, rp:null, flag:"nav_missing"}`(缺价硬报错,禁 b1 兜底的用户铁律两边都守住了),lab 版只多一个内部字段 `closed:null`。

## P1-2 共享核双份实现跨文件独立复算(99 用例)

对象:`common.js _gihRealizeRealForce`(L1185 起,首页 sim 弹窗用) vs `lab.js _kellyAihlineRealizeReal`(L7912,lab 卡面/弹窗用)。方法:node vm 分别提取两函数源码,注入同一份 accum_nav_map.json,用 G/H/I 真实交易行(buy_price>0)×(净值命中日/缺失日)+3 个边界用例,共 99 例,逐字段(pr/rp/hd/sell_price/flag)对比。

| 用例类 | 数量 | 结果 |
|---|---|---|
| real_nav_hit(净值命中,主路径) | 48 | **逐位一致**(field_diff=0) |
| real_nav_missing(净值缺失) | 48 | 数值字段全同;lab 版多 1 个结构字段 `closed:null`(lab 内部 kept 行私有,common 无此键) |
| edge_no_code / edge_buy_price_0(无代码/零买价) | 2 | 同上(nav 缺失分支先行),数值字段全同 |
| edge_null_sel(sel=null) | 1 | **行为差异**:common 返回 nav_missing(`sel && sel.xxx` 防御);lab 抛 `Cannot read properties of null (reading 'buy_date')`(假设非 null) |

- 差异定性:①`closed` 字段=lab 版独有结构字段,统计口径不受影响;②null 防御差异与 codex 报告 why 原文("sel&&sel.xxx 防御null vs 假设非null")吻合——两条调用链(app.js L3703/L5191、lab.js 内部)构造 sel 时均为非空对象字面量,null 不在生产输入域,属防御深度差异,**无数值漂移**。如需拉平防御可后续小改(属代码变更,本单只复算不动业务代码)。

## P1-3 card-vs-popup 一致性:两层数据回算

### 第一层:原脚本 verify_card_vs_popup.mjs(内置弹窗链=静态 NEW14,即修复前口径)

2026-08-31 重跑成功(先修 harness,见下节),60 行(10 模式×6 周期,周期键含 all 重复一次为脚本原行为)落 `data/card-vs-popup-consistency-20260831-baseline-run.json`(8-30 原版存证 `data/card-vs-popup-consistency.json` 保持不动, 方案 B 文档引用不受影响)。跑出的差异(非 GIH 卡面 611 vs 弹窗 431、G 10 vs 29 等)与 `kelly-card-vs-popup-consistency-20260830.md`(8-30 修复根因调研)记录的**修复前差异样本逐位吻合**(「卡面5/弹窗3」「G卡面10/弹窗29」)——证明该脚本模拟的是修复前口径,反证 8-30 修复确实落在 lab.js 源码中(修复后弹窗注释 L11651-11655:G/H/I 恒走 NoBull per-date、A-F/J 走普通 per-date,与卡面同源)。

### 第二层:修复后口径对齐回算(recompute 脚本,弹窗链切 S06/NoBull 同源口径)

| 模式组 | 行数 | 弹窗 total vs 卡面 n | 弹窗持仓中 vs 卡面 holding |
|---|---|---|---|
| A-F/J(短线 7 模式) | 42 | **42/42 逐位一致** | **42/42 逐位一致** |
| G / I(长线 P3d) | 12 | **12/12 逐位一致**(647=647) | 设计语义差:卡面=sim 强平后(G 10/I 9),弹窗=原始未卖行(G 50/I 42) |
| H(满仓不买) | 6 | NEQ(弹窗 647 vs 卡面 373) | 同为 sim 语义:卡面 n=373 只含实际成交行(满 5 仓后不买),弹窗=原始行集 |

- 54/60 行 total 一致;6 个 NEQ 全部是 H,根因=「卡面套 GIH 仿真、弹窗不套」的**指标定义差异**(方案 B 文档已声明,弹窗注释 L11805 自认"未套 ai 长线仓管理"),非谓词/池计算错误。
- 定性:8-30 修复(弹窗谓词/池换源 S06 per-date + G/H/I NoBull)已达成的目标=**两链行集同源**;本复算用数据证实行集逐位一致。「持仓中」在 G/H/I 上的差与 H 上的 total 差是弹窗与卡面指标语义本不同,若要求两者也一致,属新需求(需用户拍板,如弹窗加仿真视角),不在本复算范围。

## verify_card_vs_popup.mjs harness 运行方式修复记录(不改对比逻辑)

脚本写于 8-30 real 链切换之前,在当前 lab.js(origin/main 81d4ed411)下跑需补三处运行方式(全部标注 harness fix 2026-08-31,对比逻辑/池构建/统计口径零改动):

1. LAB_SYMBOLS 补提取 `_kellyAihlineRealizeReal`(lab.js real 链新增函数,清单漏项导致 ReferenceError);
2. 沙箱 stub `var _kellyRealNav = null;` 并注入 `static-site/data/accum_nav_map.json`(lab.js 模块级懒加载变量,沙箱无 fetch,直接注入同源数据;`_kellyAihlineApply` 内部必然执行 real 链);
3. 数据依赖:脚本读 `static-site/data/` 5 个 JSON(signal_kelly_trades/signal_kelly_backtest/kelly_mode_s06_state/kelly_loss_features/accum_nav_map),前 4 个+accum_nav_map 不入 git(worktree 需从主仓拷入)。

复算脚本 `recompute_p12_shared_core_and_popup_align.mjs` 同款依赖,独立自含(不 import verify 脚本),sliceDecl 与 verify 原版逐行一致。

## 复现

```bash
# 前置: 在仓库根(worktree 需先拷数据, 见 harness 修复记录③)
#   static-site/data/ 下需有 signal_kelly_trades.json / signal_kelly_backtest.json /
#   kelly_mode_s06_state.json / kelly_loss_features.json / accum_nav_map.json(本地生成产物, 不入 git)
node docs/kelly/analysis/scripts/verify_card_vs_popup.mjs
#   → docs/kelly/analysis/data/card-vs-popup-consistency.json(脚本固定输出路径; 本单运行结果另存
#     card-vs-popup-consistency-20260831-baseline-run.json, git 内 8-30 版存证不动)
node docs/kelly/analysis/scripts/recompute_p12_shared_core_and_popup_align.mjs
#   → docs/kelly/analysis/data/p12-recompute-out.json(P1-2 99 用例 + P1-3 修复后口径 60 行)
```

- 脚本:`docs/kelly/analysis/scripts/verify_card_vs_popup.mjs`(8-30 已有,本单 harness 修复)、`docs/kelly/analysis/scripts/recompute_p12_shared_core_and_popup_align.mjs`(本单新增)
- 输入依赖:上列 5 个 JSON + static-site/{common.js,lab.js}(origin/main 81d4ed411 版)
- 数据版本:trades=2026-08-31 07:17 / s06=2026-08-28 21:16 / accum_nav_map=2026-08-30 12:46
- 关键口径:卡面=S06 动态谓词+posCapK1+每日池金额 1万/当日保留数+etf_main 费率+(G/H/I NoBull 豁免+GIH sim:G=P≤3d@10万/H=满仓不买@5万/I=P≤3d@9万);弹窗(修复后)=同谓词同池+cutoff,不套 sim
