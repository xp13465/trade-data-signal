# 全站帮助图标「❓」移动端双弹修复(2026-10-03)

## 结论
修好 5 处帮助图标(overfit / overfit2 / signal-help / strategy-help / data-glossary / **pfIndHelpBtn**)移动端 tap 双弹,并回归确认 10-02 已修的 ice-note 仍单弹。根因在公共委托层 `_initTermPop`(app.js),**根因处一次性修**,未打 N 处补丁。

本分支两轮:
- `7975699ff`:原修复(4 处 data-*-help 帮助图标:overfit/signal/strategy/glossary)
- 本次返工(**F1 漏修**):补齐 id 式帮助图标 `#pfIndHelpBtn`(公募基金·行业配置口径说明),reviewer 独立实测抓到

base commit: `11073b291`(origin/main HEAD,开工时;reviewer 报告 `be5f0edc4`)
版本串:未自行 bump(机制 C),由主控 merge 走 main-merge.sh 统一处理。

## 根因
全站帮助图标都是「term-pop(data-tip / title→data-tip 迁移)+ 各自 click 弹完整 modal」双绑定:

| 图标 | 生成处 | modal 委托 | 绑定形态 |
|---|---|---|---|
| 分析参考点AI监控卡 ❓ | `app.js:1673 _overfitHoverTip`(`data-overfit-help`) | `app.js:1725 _initOverfitHelpDelegation` | data 属性 |
| 监控卡「❓完整指南」 | `app.js:2363`(父级 `.overfit-tip` 带 data-tip) | 同上 | data 属性 |
| 情绪日历图例 ❓(10-02 已修) | `app.js:7278`(`data-ice-note`) | `app.js:7328 _initIceNoteDelegation` | data 属性 |
| 技术信号标题 ❓ | `app.js:7837 signalHelpTip`(`data-signal-help`) | `app.js:7826 _initSignalHelpDelegation` | data 属性 |
| 指数卡片 h3 ❓ | `app.js:8391 _appendStrategyHint`(`data-strategy-help`) | `app.js:8355 _initStrategyHelpDelegation` | data 属性 |
| lab 术语词典 ❓ | `lab.js:803`(`data-glossary`,hover 时由 `lab.js:891` 懒填充 data-tip) | `lab.js:871 _initLabGlossaryDelegation` | data 属性 |
| **公募基金行业配置口径 ❓(F1)** | **`app.js:22065`(`#pfIndHelpBtn`,`title="行业配置口径说明"`)** | **`app.js:22327`(`_helpBtn.addEventListener("click", _showIndHelpModal)`)** | **id + title 式** |

移动端 tap 会合成 `mouseover + mousedown/mouseup + click` 双事件序列:
- 合成 mouseover → `_initTermPop` 的 mouseover 冒泡委托(bubble 阶段)命中 data-tip / fallback title → 弹 term-pop;
- click → 各 modal 委托(capture,注册更早)先弹 modal,`stopPropagation` **拦不住同节点后续 capture listener**,`_initTermPop` 的 touch click 委托(capture,注册更晚)继续执行 → 再弹 term-pop。

同一个元素两个弹层同时出现 = 双弹。10-02 ice-note 的修法是在 `_initTermPop` 两处委托里逐个排除 `[data-ice-note]`(单点补丁)。

### F1 病灶(为什么 7975699ff 漏了它)
`#pfIndHelpBtn` **不带任何 `data-*-help` 属性**,而是 `id` 绑定 + `title` 属性(会被 `findTipEl` 的 mouseover 委托 fallback 迁移成 data-tip 弹 term-pop)。原修复的同类排查只 grep 了 `data-*-help` / `data-glossary` / `data-ice-note` **属性**,id 式帮助图标逃过排查。reviewer 独立 Playwright 实测复现:`pfIndHelpBtn: hoverPop=True clickPop=True pfModal=1`(term-pop z-index 9999 > rule-modal z-110,两个同时可见)。

## 修改(根因处一次修)
`static-site/app.js` 的 `_initTermPop` 闭包内(7975699ff):
- 新增统一排除集合 `_modalHelpSel = "[data-ice-note],[data-overfit-help],[data-signal-help],[data-strategy-help],[data-glossary]"`;
- **mouseover 委托**:`isTouch && e.target.closest(_modalHelpSel)` 命中即 return(桌面 hover 短文本保留,仅移动端排除);
- **touch click 委托**:`e.target.closest(_modalHelpSel)` 命中即 return(该委托只在 isTouch 下注册,故不需重复判断)。

### F1 修法(本次返工,与统一集合同一根因方案)
- `app.js:7873`:`_modalHelpSel` 加入 `[data-ind-help]` → `"[data-ice-note],[data-overfit-help],[data-signal-help],[data-strategy-help],[data-glossary],[data-ind-help]"`;
- `app.js:22065`:`#pfIndHelpBtn` span 加 `data-ind-help=""` 属性(与其余 6 处帮助图标同模式:data 属性 + 统一排除集合)。

**为什么不选「在委托里加单条排除」**:10-02 ice-note 的单点补丁已被本次 7975699ff 并入统一集合作架构先例——单条排除是逐图标打补丁,违背"根因一次修";统一集合新增 `[data-ind-help]` 与其余帮助图标同构,后续再新增帮助图标只需加属性入集合即可。
**不引入副作用**:全站 grep 无 `data-ind-help` 的 CSS 属性选择器 / JS 引用冲突;`data-*` 自定义属性无 HTML 语义变化(任务提示的"别改 DOM 语义/CSS 命中"已核对)。

lab.js 的 glossary 的 term-pop 浮层由 app.js `_initTermPop` 冒泡委托显示(`lab.js:889` 注释自证),因此根因修在 app.js 一处即同时覆盖 glossary,lab.js 零改动。

## §23.2 同类错误面清单(reviewer 覆核点)
全站穷举所有「帮助图标 + 双事件绑定」点。本次返工改用**更宽排查**(不只 grep data 属性):
- `cursor:help` 样式命中:`app.js:22065` **全站唯一一处** = `#pfIndHelpBtn`(reviewer 已核实,本次复核一致);
- `title="...">❓` / `title='...'>?` 组合:`lab.js:803`(`data-glossary`,已修)+ `app.js:22065`(F1,本次修),其余 ❓ 均为 data-tip / data-no-pop / 纯文本;
- `querySelector('#...Help')` / `getElementById('...Help')` / 变量名含 `Help|help|❓|glossary|tip`:见下表。

| # | 位置 | 状态 | 说明 |
|---|---|---|---|
| A | app.js 情绪日历图例 ❓ `[data-ice-note]`(7278) | 已修(10-02)+ 本次并入统一集合回归 | 10-02 单点补丁先修,本次并入 `_modalHelpSel` 防漏 |
| B | app.js 监控卡 ❓ `[data-overfit-help]`(term-tip 型,1673) | 已修(7975699ff) | 移动端 hover+click 双弹(实测修前 2 弹/修后 1 弹) |
| C | app.js 监控卡「❓完整指南」`[data-overfit-help]`(父级 data-tip,2363) | 已修(7975699ff) | closest 命中父级 data-tip,同根因 |
| D | app.js 技术信号标题 ❓ `[data-signal-help]`(7837) | 已修(7975699ff) | 同根因 |
| E | app.js 指数卡片 h3 ❓ `[data-strategy-help]`(8391) | 已修(7975699ff) | 同根因 |
| F | lab.js 术语词典 ❓ `[data-glossary]`(803) | 已修(7975699ff) | data-tip 由 lab.js hover 懒填充后走 app.js term-pop,同根因 |
| **J** | **app.js 公募基金行业配置口径 ❓ `#pfIndHelpBtn`(22065, id+title 式)** | **本次修(F1)** | **全站 `cursor:help` 唯一一处;id 绑定 click modal + title→data-tip 迁移弹 term-pop;grep data 属性漏网,reviewer 独立实测复现双弹** |
| G | app.js 各纯 tooltip `term-tip`(仅 data-tip,无 click modal,如 1184/7593/12691/17873/.../24266) | 无需修 | 仅 term-pop 无 modal,移动端弹 tooltip 是设计行为,无第二弹层 |
| H | common.js 各 `data-tip`(sig-drought-chip 等) | 无需修 | 仅 tooltip 无 modal 绑定 |
| I | lab.js sig-kelly 各 `data-tip`(`data-no-pop=""` 的 toggle/label) | 无需修 | `findTipEl` 对 `[data-no-pop]` 直接返回 null,term-pop 本就不处理;且无 modal 双绑定 |
| K | app.js 首页 `.sig-kbtn-help`(3072,「推荐方法·参考说明」) | 无需修 | `data-no-pop=""` + 自带独立 hoverpop(`.sig-kbtn-help-pop`),term-pop 让位,自管 pop,无双弹 |
| L | app.js 公募行业图表 `#pfIndFundModal`(22511,点击行业柱/TreeMap) | 无需修 | echarts canvas 点击,无 title/data-tip 参与 term-pop,非帮助图标 |
| M | lab.js:3012 `lab-rank-quality`(title 嵌 clickable rank 行) | pre-existing | reviewer 已过滤:非本次 diff 引入、非典型帮助图标,走上报通道 |
| N | lab.js:12933 `lab-sigkelly-guide-trigger[data-guide]` | 无需修 | 自建 pop 系统无 data-tip,无 term-pop 参与 |
| O | lab.js:12420 📌 pin-btn(title) | pre-existing | 功能按钮非帮助图标,reviewer 已过滤 |

面清单结论:全站帮助类图标共 **7 处**(A-F + J),均共享 `_initTermPop` 公共根因,现状 = 7/7 修毕或已修。

## 自测证据(Playwright + 真实代码提取,入库可重跑)

**方法**:入库脚本 `docs/ops/test_help_dblclick_20261003.py`,**修前/修后对比在同一次运行内完成**:
- before = `git show 11073b291:static-site/{app,lab}.js`(显式 base commit,**不依赖"当时 HEAD 是什么"**,F2 证据缺口根治);
- after = 当前工作区 `static-site/{app,lab}.js`;
- 真实提取 `_initTermPop` **完整 IIFE**(anchor 定位首尾含 `})();`,修前/修后各自定位,不靠行号范围截断——F2 指出的"IIFE 截断缺 `})();` 语法错未注册"根治)+ 5 个 modal 委托 + lab glossary 双委托;普通 modal 打开函数 stub 计数;
- `matchMedia("(hover: none)")` stub 模拟移动端/桌面,逐个图标 dispatch `mouseover→mousedown→mouseup→click`,断言 `.term-pop` 显示 + modal 计数。

**移动端 tap 对比**(pop 显示计数 = term-pop 可见 + modal 计数,修前应 =2 弹层、修后应 =1):

| 图标 | 修前 hover 弹 | 修前 click 弹 | 修前 modal | 修后 hover 弹 | 修后 click 弹 | 修后 modal |
|---|---|---|---|---|---|---|
| overfit ❓ | True | True | 1 | **False** | **False** | 1 |
| overfit「❓完整指南」 | True | True | 1 | **False** | **False** | 1 |
| ice-note(回归,10-02 已修) | False | False | 1 | False | False | 1 |
| signal-help ❓ | True | True | 1 | **False** | **False** | 1 |
| strategy-help ❓ | True | True | 1 | **False** | **False** | 1 |
| data-glossary ❓ | True | True | 1 | **False** | **False** | 1 |
| **pfIndHelpBtn ❓(F1)** | **True** | **True** | **1** | **False** | **False** | **1** |
| 普通 term-tip(对照) | True | True | 0 | True | True | 0 |

由此:5 处(overfit / overfit2 / signal / strategy / glossary)+ F1 `pfIndHelpBtn` 修前 tap 弹 2 个层 → 修后只弹 1 个 modal;ice-note 修后仍单弹(回归过);桌面与普通 tooltip 行为不变。

**桌面 hover 对照**(isTouch=false;有意设计 hover 短文本,应保持弹):signal-help 修前 hoverPop=True / 修后 hoverPop=True,不受影响(脚本 `desktop-hover-signal` 用例)。

**普通 tooltip 不被误伤**:普通 `term-tip`(无 modal 选择器)移动端 hover+click 仍弹 term-pop(modals=0),证明排除集合没有波及纯 tooltip。

脚本判定输出(PASS 节选):`修前 6 图标(pfIndHelpBtn 在内)tap 双弹复现 → 修后全部单弹 modal;ice(base 已修)两版均单弹;plain term-tip 仍弹 tooltip 且无 modal;桌面 hover 行为不变。`

## 影响面
- 改动单一:`app.js` `_initTermPop` 闭包内 3 处(mouseover 委托 1 行守卫 + click 委托 1 行守卫 + 1 个常量)+ `app.js:22065` `#pfIndHelpBtn` span 加 `data-ind-help`;**无 lab.js / common.js / 任何 html 改动**;
- lab.js glossary 因浮层显示链路走 app.js term-pop 而自动覆盖;
- 桌面 hover 短文本、普通 data-tip tooltip、`[data-no-pop]` 自有 pop 系统全部不受影响(有实测对照);
- 本次不 bump 版本串、不 build min,由主控 merge 统一处理(机制 C/D)。

## 复现
- 自测脚本已入库:`docs/ops/test_help_dblclick_20261003.py`,reviewer 直接 `python3 docs/ops/test_help_dblclick_20261003.py`(项目 .venv 已装 playwright;chromium 见脚本 `chromium_path()` 自动探测)即可在同一次运行内重跑修前/修后对比。
- reviewer 独立复现轨迹:reviewer 报告 `docs/ops/help-dblclick-review-20261003.md`(F1 实测复现 `hoverPop=True clickPop=True pfModal=1`;F2 指出旧 /tmp 脚本证据不可复核)。
