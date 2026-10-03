# help-dblclick F1 补修增量复核报告(2026-10-03)

复核范围: `feat/help-dblclick-20261003` 增量 `be5f0edc4` → `b166e9071`(仅 F1 补修 + 自测脚本入库 + fix 文档修订),不重审主体(7975699ff)。

## 结论

**可 merge。**

- F1(`#pfIndHelpBtn` 移动端 tap 双弹)修法正确、与其余 7 处帮助图标同构(根因一次修,非单点补丁),无属性选择器冲突,modal 修后仍正常单弹。
- F2(自测证据不可独立复核)已根治:入库脚本 `docs/ops/test_help_dblclick_20261003.py` 由 reviewer 独立重跑,`EXIT=0 PASS`,修前双弹复现 → 修后单弹,before 显式 `git show 11073b291`、IIFE anchor 提取无截断。
- 穷举清单抽样 K/L 免修理由成立。
- 原 6 入口回归:委托 IIFE 全在位,独立重跑覆盖全部入口,after 全单弹。

## 一、F1 修法正确性(独立核实)

| 检查项 | 证据 |
|---|---|
| 改动范围 | `static-site/app.js` 仅 2 行:选择器 `_modalHelpSel` 加 `[data-ind-help]`(7873) + `#pfIndHelpBtn` span 加 `data-ind-help=""`(22065),未引入单点补丁 |
| 属性引用无冲突 | `git show b166e9071:static-site/app.js` grep `data-ind-help` 全站仅 2 处(选择器定义 + span 属性),无任何 CSS/JS 属性选择器再引用;其他 5 个 `data-*-help` 选择器不受影响 |
| 委托层排除生效 | `_initTermPop`(7858 IIFE)两处消费:8088(mouseover,`isTouch` 下 `closest(_modalHelpSel)` return)+ 8101(click,capture 注册更晚,同排除)→ term-pop 不再处理 `#pfIndHelpBtn` |
| modal 仍单弹 | `_showIndHelpModal`(22273)+ 绑定(22328,`_helpBtn.addEventListener("click", _showIndHelpModal)`)独立于委托层,排除后 click 仍正常弹 `pfIndHelpModal` |
| 桌面行为不回归 | 桌面(`isTouch=false`)mouseover 委托不排除,`#pfIndHelpBtn` 的 `title` 经 `findTipEl` 迁移成 data-tip 弹 term-pop 短文本 + click 弹完整 modal,与其余帮助图标「hover 短文本 + click 详版」有意设计一致 |

## 二、F2 自测脚本独立重跑(reviewer 独立执行)

运行环境: 临时 worktree checkout `b166e9071`(工作区文件 md5 与 `git show b166e9071` 一致)+ 主仓 `.venv` playwright + 本地 chromium headless。

关键输出(before=无 data-ind-help / after=拼入):

| 图标 | 修前 hover | 修前 click | 修前 modal | 修后 hover | 修后 click | 修后 modal |
|---|---|---|---|---|---|---|
| overfit ❓ | True | True | 1 | False | False | 1 |
| overfit「❓完整指南」 | True | True | 1 | False | False | 1 |
| ice-note(base 已修) | False | False | 1 | False | False | 1 |
| signal-help ❓ | True | True | 1 | False | False | 1 |
| strategy-help ❓ | True | True | 1 | False | False | 1 |
| data-glossary ❓ | True | True | 1 | False | False | 1 |
| **pfIndHelpBtn(F1)** | **True** | **True** | **1** | **False** | **False** | **1** |
| 普通 term-tip(对照) | True | True | 0 | True | True | 0 |

桌面 hover: signal-help 修前/修后均 hoverPop=True(不变)。

- ① 脚本能跑通:`EXIT=0`,输出 `PASS: 修前 6 图标(pfIndHelpBtn 在内)tap 双弹复现 → 修后全部单弹 modal;ice(base 已修)两版均单弹;plain term-tip 仍弹 tooltip 且无 modal;桌面 hover 行为不变。`
- ② 修前双弹真实复现:`pfIndHelpBtn` before 行 `hoverPop=True clickPop=True modals=1`(term-pop + modal 双弹层)→ after `False/False/1`(仅 modal 单弹)。修法对 F1 有效。
- ③ IIFE 提取无截断:`extract_anchor_iiife` anchor 定位首尾含 `})();`,脚本未抛 `IIFE closing not found`,全部委托块成功注入 Playwright DOM 并生效(否则断言不可能全 PASS)。

## 三、穷举清单抽样复核

- **K(`.sig-kbtn-help`,app.js:3072 附近,标「无需修」)理由成立**:代码确认 `data-no-pop=""` + `title=""` + 自带独立 hoverpop(`.sig-kbtn-help-pop-wrap` 内含 `_sigHelpPopHtml()`,自包含定位,注释明确「term-pop 让位,自管 pop」)。`findTipEl`(app.js:7897)首行 `if (target.closest("[data-no-pop]")) return null;` → term-pop 对该按钮根本不处理,无双弹。
- **L(`#pfIndFundModal`,app.js:22511,标「无需修」)理由成立**:`_showIndustryFunds` 是「点击行业柱/TreeMap → 弹 rule-modal 基金列表」的数据浏览 modal,触发源为 echarts canvas 点击,modal 内无 title/data-tip 参与 `findTipEl`,非帮助图标(无 ❓),不在 `_modalHelpSel` 集合内,无 term-pop 参与。免修正确。

## 四、原 6 入口回归

- 增量 diff 只动 app.js 2 行 + 文档/脚本,未触碰 6 入口元素与绑定。
- 6 入口委托 IIFE 在 `b166e9071` 全在位:app.js 1725(overfit)/7328(ice)/7826(signal)/8355(strategy)/7858(term-pop)+ lab.js 871(glossary delegation)/891(glossary hover)。
- 独立重跑自测覆盖全部 6+1 入口,after 全部单弹(`False/False/1`),其中 ice 与 signal 独立复跑结果与 fix 文档声称一致。
- 对照项(普通 term-tip、桌面 hover)行为不变,排除集合未误伤。

## 影响面

- 改动仅前端 app.js 2 行 + 自测脚本/文档(纯新增),无数据产物/后端/定时任务影响(§2 分级:B 级②,有隐藏影响面但本轮已覆盖全部委托消费方)。
- 本次 review 全程在临时 worktree 独立执行,未改动 implementer 工作区。
