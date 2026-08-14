# 信号凯利回测首列 SPAN 独立换行(#firstcol)

> 日期:2026-08-14
> 类型:纯前端样式改动(不动计算口径/渲染结构)
> 触发需求:用户原话——信号凯利回测表格首列里「AI长线·开 满仓不买@15万」和「淘汰·无仓位限制·无法实操」这些 SPAN 需**独立换一行**,不再挤同一行。

## 一、改动内容

只改 CSS,不改 lab.js 渲染结构(侵入最小,§9 单版前端铁律)。

| 文件 | 选择器 | 改动 | 效果 |
|---|---|---|---|
| `static-site/lab.css` | `.lab-sigkelly-modelbl` | `display:inline` → `display:block; margin-left:0` | 模式描述独立一行 |
| `static-site/lab.css` | `.lab-sigkelly-exec-badge` | 加 `display:block; margin-top:2px; margin-left:0` | 淘汰角标独立一行 |
| `static-site/style.css` | `.lab-sigkelly-gih-badge` | `display:inline-block` → `display:block; margin-top:2px; margin-left:0` | AI长线·开+策略标签独立一行 |

- 策略标签「满仓不买@15万」**不是独立 span**,而是嵌在 `.lab-sigkelly-gih-badge` 的文本内(`AI长线·开 ${_kellyGihStratShort(m)}`,lab.js L10206)。gih-badge 独立成行后,「AI长线·开 满仓不买@15万」整体独占一行,满足用户需求。
- 模式字母 `<b>` 保持 inline(首行),其后 modelbl/exec/gih 三 span 各自 block 下行。

## 二、覆盖首列全部渲染位(§23.3 举一反三)

全部首列展示位清单(模式字母+描述+AI长线角标+策略标签+淘汰角标组合),统一独立换行,样式一致(§22 一致性,各表文案/角标含义不变):

| # | lab.js 位置 | 表 | 首列结构 | 覆盖方式 |
|---|---|---|---|---|
| 1 | L9045 | AI长线对比表(G/H/I advice) | `<b>模式字母</b><span modelbl>描述</span>` | modelbl block |
| 2 | L9610 | 三玩法各自披露表 | `<b>玩法名</b>${afgBadge(exec-badge)}` | exec-badge block |
| 3 | L10214 | 主信号表「无数据」行 | `<b>模式字母</b><span modelbl>描述</span>` | modelbl block |
| 4 | L10253 | 主信号表(用户点名处) | `<b>模式字母</b><span modelbl>描述</span>${gih-badge}${exec-badge}` | 三个类 block |

- 全信号表/卡片行共用上述渲染函数(L9650 `_sigKellyAllSignalGroupHtml` → `_renderSigKellyCard`,L10253 主信号表渲染),同 CSS 规则自动覆盖。
- 相关组件还被谁用(grep):`modelbl` 仅 L9045/10214/10253(全首列);`gih-badge` 仅 L10206(渲染在 L10253 首列);`exec-badge` 仅 L9609(三玩法表首列)/L10250(主信号表首列)。三个类全部只出现在首列,`display:block` 无副作用。

## 三、验收口径

- [x] grep 确认三个角标类均 display:block(lab.min.css/style.min.css 已含)
- [x] 全部 4 处首列展示位逐项覆盖(见上表)
- [x] 渲染效果:Chrome headless 实测 —— `b_top=13 / mbl_top=30 / gih_top=46 / exec_top=67` 各自独立行、逐行递增;`gih` 含「满仓不买@15万」、`exec` 含「淘汰·无仓位限制·无法实操」,文案完整
- [x] sw.js CACHE_VERSION a214→a215→a216(汪汪队已占 a215,本功能取 a216)
- [x] commit 已含;lab.js 无改动无冲突;rebase 冲突已在 sw.js 语义合并(版本号取高 a216,双注释保留)+构建产物取 origin/main 后重跑 build_min+bump

## 四、§21 公示

只改样式不改展示文案/算法,不涉及算法公示,未动 purpose-notes。

## 五、相关

- 历史对照:sw.js a211->a212 曾把 modelbl 改 `display:inline` 以"消除描述独立一行拉高行高";本次用户新需求(首列各 SPAN 独立行)将其还原为 block 布局,属用户主动要求,非回归。
- 触发场景:信号凯利回测(sigkelly)各表首列信息拥挤时,可参照本方案用 display:block 让首列各信息独立成行。
