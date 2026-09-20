# review: feat/at-steps-hl-done-focus 绿框「已操作态焦点边框」(2026-09-18)

- 审查对象: branch `feat/at-steps-hl-done-focus`, commit `c3a0f5538`
- base: origin/main `c5da33b34`
- diff: `git diff c5da33b34...feat/at-steps-hl-done-focus -- static-site/lab.js static-site/lab.css`(17 insertions / 1 deletion)
- 结论: **PASS**(5 项审查点全过,0 FAIL,2 个低分观察项已滤见末尾)

## diff 摘要
- lab.js `_atRowHtml`(@14706): 原蓝框一行判定改为三分支
  - `nowKey = _atNowActKey(nowAct)`
  - `nowKey && nowKey === _atRowKey(d)` → 蓝框 `auto-trade-steps-day-hl`(原逻辑等价)
  - `else if (!nowAct && d && String(d.date||"") === String(today||""))` → 绿框 `auto-trade-steps-day-done`
  - 其余无框
- lab.css @2588-2595: 新增 `.auto-trade-steps-day-done td`(浅色绿 rgba(47,158,68,.55)) + `[data-theme="dark"]/[data-theme="redgold"]` 变体(亮绿 rgba(105,219,124,.6))

## 逐项结论
1. **三分支判定逻辑: PASS**
   - nowAct 非空命中行 → 蓝框; nowAct null 且 d.date===today → 绿框; 其余无框
   - node 复制逻辑跑 10 用例全 PASS: 今天买入X命中蓝 / 今天买入Y不误蓝 / 历史916不误蓝不误绿 / nowAct null 今天X·Y 绿 / nowAct null 历史916无框 / 今天到期卖出X命中蓝 / 未来到期卖出不误蓝 / null行不崩
   - nowAct=null 语义(读 `_atNowAction`@14336 + `_atPickTodayStep`@14299 + `_atFindSellDue`@14314): 今天买入全操作/落定 且 今天无未操作到期卖出 → null → 今天行全绿框。不会出现「绿框圈未操作行」(null 前提已排除未操作)
   - 卖出行 `_atSellRow`@14465 中 `date = sellDate`, 即卖出行 d.date=卖出日, 今天到期卖出行 d.date=today 才绿; 916/917 历史卖出(d.date=历史卖出日)不绿
2. **两处共用一致性: PASS**
   - `_atRowHtml` 调用点共 3 处(grep lab.js): `_atRemindGroupHtml`@14681(买)/@14685(卖) + `_atAllModalRender`@14990(全部计划弹窗), 无绕开, 传参一致(today, nowAct, byDate), 行为同步(§22 多展示位一致)
   - app.js 无 auto-trade-steps(实操面板仅 lab.js), 无第三展示位
3. **主题变体: PASS**
   - 浅色绿 rgba(47,158,68,.55) 与 `.auto-trade-steps-st-green`@2614 `#2f9e44` 同色(已操作(手动)绿语义一致)
   - dark/redgold 亮绿 rgba(105,219,124,.6) 与 `.auto-trade-steps-st-green` dark 变体@2623 `#69db7c` 同色, 深底亮绿可见
   - `data-theme` 选择器命名与全文件既有模式一致
4. **回归: PASS**
   - 原蓝框行为等价: 旧代码 nowAct=null 时 `null === _atRowKey(d)` 恒 false(行 key 非空串) → 无框; 新代码 `nowKey&&` 短路同样不蓝, 仅 today 行加绿
   - 历史行 916/917 无任何框(用例验证)
   - JS 语法 `node --check` 通过
5. **§21 算法公示: PASS(无需同步)**
   - diff 仅改渲染分支+CSS, 未动 track_score/评分/权重/口径/匹配规则任何数值
   - purpose-notes.js 中实操步骤公示定位为「纯展示不重算算法」(2026-09-10 新增段), 绿框属展示层, 不涉算法描述

## 低分观察项(<80 已滤, 供主控参考)
- 卖出行左侧琥珀竖条 `.auto-trade-steps-row-sell td.auto-trade-steps-date`(特异性 0,2,1)会覆盖日期单元格的绿框(0,1,1), 绿框在卖出行日期列缺一格——pre-existing 模式(原蓝框同样被覆盖), 视觉可接受, 非本次引入
- 主面板提醒视图(T0=今天)今天行也会绿框(需求只点名弹窗)——两展示位一致更符合 §22, 非 bug

## 流程提示(非审查项)
- feat commit 只改源码未 bump(机制 C 规定 main-merge.sh 统一 bump+build_min, 上次 c5da33b34 即 bump commit, 符合流程)
- 当前 static-site/data/auto_trade_steps.json 最新 20260914, 无 916/917/918 步骤; 今天(918)实际展示取决于盘中/盘后更新产物, 逻辑判定与数据无关, 数据到位自然生效
