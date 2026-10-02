# 全站帮助图标「❓」移动端双弹修复(2026-10-03)

## 结论
修好 4 处帮助图标(overfit / signal-help / strategy-help / data-glossary)移动端 tap 双弹,并回归确认 10-02 已修的 ice-note 仍单弹。根因在公共委托层 `_initTermPop`(app.js),**根因处一次性修**,未打 4 处补丁。

base commit: `11073b291`(origin/main HEAD,开工时)
版本串:未自行 bump(机制 C),由主控 merge 走 main-merge.sh 统一处理。

## 根因
全站帮助图标都是「term-pop(data-tip)+ 各自 click 弹完整 modal」双绑定:

| 图标 | 生成处 | modal 委托 |
|---|---|---|
| 分析参考点AI监控卡 ❓ | `app.js:1673 _overfitHoverTip`(`data-overfit-help`) | `app.js:1725 _initOverfitHelpDelegation` |
| 监控卡「❓完整指南」 | `app.js:2363`(父级 `.overfit-tip` 带 data-tip) | 同上 |
| 情绪日历图例 ❓(10-02 已修) | `app.js:7278`(`data-ice-note`) | `app.js:7328 _initIceNoteDelegation` |
| 技术信号标题 ❓ | `app.js:7837 signalHelpTip`(`data-signal-help`) | `app.js:7826 _initSignalHelpDelegation` |
| 指数卡片 h3 ❓ | `app.js:8391 _appendStrategyHint`(`data-strategy-help`) | `app.js:8355 _initStrategyHelpDelegation` |
| lab 术语词典 ❓ | `lab.js:803`(`data-glossary`,hover 时由 `lab.js:891` 懒填充 data-tip) | `lab.js:871 _initLabGlossaryDelegation` |

移动端 tap 会合成 `mouseover + mousedown/mouseup + click` 双事件序列:
- 合成 mouseover → `_initTermPop` 的 mouseover 冒泡委托(bubble 阶段)命中 data-tip → 弹 term-pop;
- click → 各 modal 委托(capture,注册更早)先弹 modal,`stopPropagation` **拦不住同节点后续 capture listener**,`_initTermPop` 的 touch click 委托(capture,注册更晚)继续执行 → 再弹 term-pop。

同一个元素两个弹层同时出现 = 双弹。10-02 ice-note 的修法是在 `_initTermPop` 两处委托里逐个排除 `[data-ice-note]`(单点补丁)。

## 修改(根因处一次修)
`static-site/app.js` 的 `_initTermPop` 闭包内:
- 新增统一排除集合 `_modalHelpSel = "[data-ice-note],[data-overfit-help],[data-signal-help],[data-strategy-help],[data-glossary]"`(含全部 5 种帮助图标选择器);
- **mouseover 委托**:`isTouch && e.target.closest(_modalHelpSel)` 命中即 return(桌面 hover 短文本保留,仅移动端排除);
- **touch click 委托**:`e.target.closest(_modalHelpSel)` 命中即 return(该委托只在 isTouch 下注册,故不需重复判断)。

lab.js 的 glossary 的 term-pop 浮层由 app.js `_initTermPop` 冒泡委托显示(`lab.js:889` 注释自证),因此根因修在 app.js 一处即同时覆盖 glossary,lab.js 零改动。

## §23.2 同类错误面清单(reviewer 覆核点)
全站 grep 所有「帮助图标 + 双事件绑定」点(app.js / lab.js / common.js / purpose-notes.js + 各 html):

| # | 位置 | 状态 | 说明 |
|---|---|---|---|
| A | app.js 情绪日历图例 ❓ `[data-ice-note]` | 已修(10-02)+ 本次并入统一集合回归 | 10-02 单点补丁先修,本次并入 `_modalHelpSel` 防漏 |
| B | app.js 监控卡 ❓ `[data-overfit-help]`(term-tip 型,1673) | **本次修** | 移动端 hover+click 双弹(实测修前 2 弹/修后 1 弹) |
| C | app.js 监控卡「❓完整指南」`[data-overfit-help]`(父级 data-tip,2363) | **本次修** | closest 命中父级 data-tip,同根因 |
| D | app.js 技术信号标题 ❓ `[data-signal-help]`(7837) | **本次修** | 同根因 |
| E | app.js 指数卡片 h3 ❓ `[data-strategy-help]`(8391) | **本次修** | 同根因 |
| F | lab.js 术语词典 ❓ `[data-glossary]`(803) | **本次修** | data-tip 由 lab.js hover 懒填充后走 app.js term-pop,同根因 |
| G | app.js 各纯 tooltip `term-tip`(仅 data-tip,无 click modal,如 1184/7593/12691/17873/.../24266) | 无需修 | 仅 term-pop 无 modal,移动端弹 tooltip 是设计行为,无第二弹层 |
| H | common.js 各 `data-tip`(sig-drought-chip 等) | 无需修 | 仅 tooltip 无 modal 绑定 |
| I | lab.js sig-kelly 各 `data-tip`(`data-no-pop=""` 的 toggle/label) | 无需修 | `findTipEl` 对 `[data-no-pop]` 直接返回 null,term-pop 本就不处理;且无 modal 双绑定 |
| J | 各 html / purpose-notes.js | 无需修 | grep 无 `data-*-help`/`data-glossary`/`data-ice-note` 绑定点 |

面清单结论:全站帮助类图标共 6 处(A-F),均共享 `_initTermPop` 公共根因,现状 = 6/6 修毕或已修。

## 自测证据(Playwright + 真实 app.js/lab.js 代码提取,非复刻)

**方法**:从修前(HEAD)`git show` / 修后(worktree)分别提取真实 IIFE(`_initTermPop` 及各委托/lab 双委托),注入 Playwright 页面,`matchMedia("(hover: none)")` 内联 stub 模拟移动端/桌面,逐个图标 dispatch `mouseover→mousedown→mouseup→click`,断言 `.term-pop` 是否显示 + modal 委托计数 stub。

**移动端 tap 对比**(pop 显示计数 = term-pop 可见 + modal 计数,修前应 ≥2,修后应 =1):

| 图标 | 修前 hover 弹 | 修前 click 弹 | 修前 modal | 修后 hover 弹 | 修后 click 弹 | 修后 modal |
|---|---|---|---|---|---|---|
| overfit ❓ | True | True | 1 | **False** | **False** | 1 |
| overfit「❓完整指南」 | True | True | 1 | **False** | **False** | 1 |
| ice-note(回归) | False | False | 1 | False | False | 1 |
| signal-help ❓ | True | True | 1 | **False** | **False** | 1 |
| strategy-help ❓ | True | True | 1 | **False** | **False** | 1 |
| data-glossary ❓ | True | True | 1 | **False** | **False** | 1 |
| 普通 term-tip(对照) | True | True | 0 | True | True | 0 |

**桌面 hover 对照**(isTouch=false;有意设计 hover 短文本,应保持弹):signal-help 修前 hoverPop=True / 修后 hoverPop=True,不受影响。

**普通 tooltip 不被误伤**:普通 `term-tip`(无 modal 选择器)移动端 hover+click 仍弹 term-pop(modals=0),证明排除集合没有波及纯 tooltip。

由此:4 处(overfit / signal / strategy / glossary)修前 tap 弹 2 个层 → 修后只弹 1 个 modal;ice-note 修后仍单弹(回归过);桌面与普通 tooltip 行为不变。

## 影响面
- 改动单一:`app.js` `_initTermPop` 闭包内 3 处(mouseover 委托 1 行守卫 + click 委托 1 行守卫 + 1 个常量),**无 lab.js / common.js / 任何 html 改动**;
- lab.js glossary 因浮层显示链路走 app.js term-pop 而自动覆盖;
- 桌面 hover 短文本、普通 data-tip tooltip、`[data-no-pop]` 自有 pop 系统全部不受影响(有实测对照);
- 本次不 bump 版本串、不 build min,由主控 merge 统一处理(机制 C/D)。

## 复现
测试脚本:`/tmp/helpdbl_test.py` / `/tmp/helpdbl_debug.py`(本地临时,不入库;方法见上节,依赖 ~/Library/Caches/ms-playwright chromium)。