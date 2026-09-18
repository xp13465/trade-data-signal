# 移动端「数据优先 + 说明折叠」实现细则（sigkelly + 全站）

- 日期：2026-09-18。这是继两份评测后的**实施规格**（精确到 class / 文件 / 行号），供 implementer 直接执行。
- 目标：同一份 DOM 与 CSS，只在 `@media (max-width: 760px)` 内做信息层级降级，不改桌面端、不动核心逻辑。
- 现状锚点（390×844 实测）：16 卡回测网格 top≈4228px；首屏 75% 是免责/引导/说明。

## 0. 总原则（先读）
1. **数据优先**：移动端 DOM 顺序 = 一行结论 → `.lab-sigkelly-bar`(sticky) → `.lab-sigkelly-grid` → 其余说明后置。
2. **说明一律 `<details>` 默认收起** + localStorage 记住已读。
3. **免责去重**：`risk-banner` 与 `lab-top-disclaimer` 二合一。
4. **sticky 链条**：`.lab-sigkelly-bar` 的 `top` 依赖 `--tab-h / --lab-subnav-h / --lab-subnav-child-h`（lab.css:1367、lab.js:3759 计量）。改动顶部 nav 高度时必须同步这几个 CSS 变量，否则 sticky 悬空。

## 1. 免责二合一 + 移动端折叠（省 ~214px，首屏 223~437）
- 现状：全局 `risk-banner`（status 顶部，app.js:11220 附近，切 tab 不消失）+ lab 页 `lab-top-disclaimer`（lab.js:2438 恒渲染），文案重复（非持牌/不构成投资建议/历史不预示未来）。
- 改法（CSS 优先）：
  ```css
  @media (max-width:760px){
    .lab-top-disclaimer { display:none; }            /* lab 页沿用全局 risk-banner 即可 */
    .risk-banner { font-size:11px; line-height:1.5; } /* 只留一条，压到 2~3 行 */
  }
  ```
  若要保留全文：把 `lab-top-disclaimer` 包成 `<details><summary>📚 免责声明</summary>…</details>`（lab.js:2438 模板加 2 个标签）。
- 验收：lab 首屏 223~437 消失；剩余 disclaimer ≤3 行。

## 2. 新手引导默认收起 + 已读持久化（省 ~271px，首屏 450~769）
- 现状：lab.js:2578（sigkelly）等 9 处 `<details class="lab-newbie-guide" open>` **硬编码 open**，无 localStorage，每次进都展开 319px。
- 现成 CSS 已支持收起态：`.lab-newbie-guide:not([open])` 的 toggle 文案「展开 ▾」（lab.css:55-56）。
- 改法（JS 模板微调，9 处约 2451/2470/2488/2506/2524/2542/2560/2578/2597）：
  1) 模板 `<details class="lab-newbie-guide" open>` → `<details class="lab-newbie-guide">`（去 `open`）。
  2) render 后读 `localStorage['tds_lab_guide_'+sub]`，若为 `'open'` 且桌面端再 `setAttribute('open','')`。
  3) `toggle` 事件里写回该键（`open`/`closed`）。
- 备选（纯 CSS，但移动端不可展开）：`@media(max-width:760px){ .lab-newbie-guide .lab-newbie-guide-body{display:none} }`。
- 验收：390 宽刷新后 guide 高 319→48px；手动展开后刷新仍旧展开（已读记忆）。

## 3. purpose-note 移动端默认收起（省 ~309px，首屏 888~1241）
- 现状：lab.js:9507 `_pnEl.className = "purpose-note purpose-note-collapse lab-sm"`，外层 `<details>` 默认展开。已有折叠样式（lab.css:945-952）。
- 改法：生成时不要 `open`（若当前 `<details open>` 则去掉）；或移出 body。每 tab 一个，抽一个公共 helper 统一。
- 验收：888 处降到 summary 一行（~44px）。

## 4. 核心数据上移（最大项：grid 4228 → ~1500）
根因不是 grid 本身，是 `bar` 与 `grid` 之间插入了两大块非核心内容：
- `auto-trade-steps`（实操提醒，633px，lab.js:9519 生成）
- `lab-sigkelly-advice`（操作建议指南，798px，lab.css:1682 区域）
- 改法（最小侵入，推荐）：
  ```css
  @media (max-width:760px){
    .lab-sigkelly-advice .lab-sigkelly-advice-details,
    .lab-sigkelly-advice .lab-sigkelly-advice-outer { display:none; } /* 只留 .lab-sigkelly-advice-summary-short 一行 */
    .auto-trade-steps { display:none; }  /* 或包 details 默认收起；移动端入口在底部 nav 保留 */
  }
  ```
- 若产品要求移动端仍可见：给这两个块套 `<details>` 默认收起（约 60px 一节）。
- 验收：bar 之后下一个可见块 = 第一张数据卡；grid top 4228 → ≤1600。

## 5. 顶部条减负 + 版本 toast（首屏 0~57 噪音）
- 现状：h5-topbar 内含 分享/采集时间/动态/通知×2/主题/登录/策略实验 等，390px 挤成一团；版本更新 `.show` toast 在 623px 处横插。
- 改法：
  ```css
  @media (max-width:760px){
    .h5-topbar .h5-topbar-right > *:not(.h5-btn-essential){ display:none; } /* 按实际结构收敛到 标题+核心1~2 个 */
    .show{ max-height:40px; overflow:hidden; font-size:11px; } /* toast 单行小 pill */
  }
  ```
- 验收：首屏 0~57 只剩标题 + 关键切换。

## 6. 全站统一规范（其余 tab 同款）
- 全局 `risk-banner`、`chart-hint`、`hint-*`、`pf-help`、各「这板块有什么用」统一：`@media(max-width:760px)` 下默认折叠/单行，数据块优先。
- 落地方式：在 style.css 末尾加一个「mobile-progressive-disclosure」公共段 + 一个公共 JS helper `collapseOnMobile('.xx', storageKey)`，逐 tab 套用，避免逐页自造。

## 7. 实施注意 / 风险
- 事件委托：lab.js 大量用 `document.querySelector` 全局监听（如 guide 的 `.lab-sigkelly-guide-trigger` 在 12456 行附近有委托判断），**不要移除 DOM 节点，只折叠/隐藏**，避免委托失效。
- sticky 链条：第 5 条改动若影响 `.lab-subnav` 高度，需同步重算 `--lab-subnav-h`（lab.css:1367 的 top 表达式）。
- 全部改动限制在 `@media (max-width:760px)` 内，桌面端零影响；建议先上 CSS-only 项（1/4/5/6），再上 JS 项（2/3）小步验收。

## 8. 量化目标（验收口径）
首屏非数据 636px(75%) → <120px；`.lab-sigkelly-grid` top 4228 → ≤1600；解释/引导总占高 4200 → ≤600。
