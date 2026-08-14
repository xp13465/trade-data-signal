# 全信号操作建议指南 面板重构(降亏组合使用建议 → 全信号操作建议指南)

> 2026-08-14,纯前端重构(lab.js+lab.css+purpose-notes.js+README+sw.js bump)。不改任何回测计算口径,只改展示/文案/结构/样式。
> 触发:用户反馈「降亏组合使用建议」面板的 G 方法展示数据 329笔/146W 无实操性 + 标题/序号/收起展开/格式错位 4 项整理需求。

## 需求拆解(用户原话)
1. 标题:「降亏组合使用建议」→「全信号操作建议指南」
2. 去收起展开+去序号:「② 分投资习惯怎么用?+总建议」的收起展开去掉,整理出新标题,去序号
3. G 方法数据实操性:目前 G 展示 329笔/146W 无实操性,改可操作口径
4. 总结整理:最终展示「最优秀的玩法数据和操作指南」
5. 修格式错位:「投资习惯/建议/真实回测数据」3列表格过宽溢出屏幕

## 改动点(lab.js _kellyComboAdviceHtml + _sigKellyAfgRealtimeHtml)
- **标题两处统一**(9549 title + 9552 summary)→「全信号操作建议指南」,口径括注精简保留
- **去内层折叠+去序号**:删掉原内层 `<details open>`「② 分投资习惯怎么用?+总建议」wrapper(其 summary 有 ② 序号+收起展开),内容直接平铺;新增两个无序号分节标题 `.lab-sigkelly-advice-section-title`:「分投资习惯怎么用」+「总建议(最优秀玩法+操作指南)」。外层整体可收缩(advice-outer)保留,标题即收缩栏
- **G 行可操作口径**(afg 三玩法表 G 行,不再披露原始 329笔/146W):
  - GIH on: 读真实仿真 `feeStats.all.all["G__gihb1"]`(乐观口径,与卡片一致,全列有值),标「AI长线·开 {档}」
  - GIH off: 用报告权威参考 b0 保守值(净利/收益率/本金),标「P≤3d {档}·可操作」;样本/胜率/盈亏比标「—」并注明见「G/H/I 对比表」
  - 档位随 `_kellyGihGTier()`(localStorage tds_gih_g_tier,默认13万)联动
  - 参考数据来源:docs/kelly/position/kelly-g-mode-recheck.md(与 G/H/I 对比表/purpose-notes 同值,§21/§22)
- **总建议行加实操性说明**:47.22%/+642,184/峰136万 明确标注为「未套仓位管理原始口径=不可操作,须开 ai长线 套 P≤3d 可操作档(推荐13万=155.78%/+202,508)」,消除与可操作口径的矛盾观感
- **GIH on 提示文案同步**:注明 G 行已显示可操作口径、H/I 行仍为原始口径

## 可操作口径数字来源与数值
G=P≤3d「先卖年轻仓」三档(报告 b0 保守口径,峰持仓≤20倍本金=可操作,`docs/kelly/position/kelly-g-mode-recheck.md` #49):

| 档位 | 收益率(b0) | 净利 | 本金占用 | 性质 |
|---|---|---|---|---|
| 13万 | 155.78% | +202,508 | 13倍本金 | 激进·收益率最高(默认档) |
| 15万 | 147.34% | +221,016 | 15倍本金 | 折中 |
| 20万 | 131.25% | +262,509 | 20倍本金 | 最稳·绝对净利最高 |

- 可操作判据 = 峰值同时持仓资金 ≤20万 = 单次本金倍数≤20(memory `kelly-operability-20x-principal`,`docs/kelly/position/kelly-position-cap-20x-limit.md`)
- 原始 G 未套仓位管理峰持仓 136万/146万(329笔)= 136-146倍本金,**不可操作**,故不再作为推荐展示

## 格式错位修复(lab.css)
「投资习惯/建议/真实回测数据」3列表格过宽溢出屏幕 → 对 `.lab-sigkelly-advice-body > .lab-sigkelly-advice-table`(advice-body 直子,不误伤同 class 的 G/H/I 对比表,它在 table-scroll 内非 advice-body 直子):
- `table-layout: fixed; width: 100%`
- 单元格 `white-space: normal; word-break: break-word; vertical-align: top`
- 列宽分配 15% / 32% / 53%

## §21 公示同步
purpose-notes.js `lab.sigkelly` 段:①「组合使用建议」更名「全信号操作建议指南」;②补重构说明(去序号平铺/去折叠);③G 行补可操作口径说明(不再披露 329笔/146万,§22 与 ai长线对比表/卡片一致)。

## §22 一致性核对
展示位口径一致(每日池+top-K + 可操作20倍标准):
- 本面板 afg G 行可操作 P≤3d 档 ↔「G/H/I 对比表」(同报告权威值)↔ 卡片「最后结果」GIH on 值(__gihb1)↔ purpose-notes 说明 ↔ 首页「参考说明」rule-modal(操作描述层面,无数值矛盾)
- 不再出现「一处 146万、一处 13万」矛盾:原始 329笔/146W 已从本面板 G 行移除,仅总建议行保留 136万并明确标注「未套仓位管理原始口径=不可操作」

## 自验
- node 渲染验证:advice 面板 div/details/summary/table/tr 标签全平衡;无「② 分投资习惯」;afg G 行 GIH off 显示可操作 b0(155.78%/+202,508)、GIH on 显示真实 __gihb1;原始 329笔/146万 不再出现在 G 行
- lab.js/lab.css/purpose-notes 均过 terser build_min(语法+minify 通过)
- sw.js CACHE_VERSION a214→a216(避开 a215 汪汪队分支)
