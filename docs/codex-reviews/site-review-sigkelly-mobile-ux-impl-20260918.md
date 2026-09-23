# 移动端「数据优先 + 说明折叠」实现细则（sigkelly + 全站）

- 日期：2026-09-18。这是继两份评测后的**实施规格**（精确到 class / 文件 / 行号），供 implementer 直接执行。
- 目标：同一份 DOM 与 CSS，只在 `@media (max-width: 760px)` 内做信息层级降级，不改桌面端、不动核心逻辑。
- 现状锚点（390×844 实测）：16 卡回测网格 top≈4228px；首屏 75% 是免责/引导/说明。

> ## ⚠️ 作用域红线：本次改动**只影响移动端**，桌面端零回归
> 1. 所有 CSS 改动**只允许写在 `@media (max-width: 760px)` 内**；禁止改全局规则。
> 2. 所有 JS 改动（去 `<details open>`、localStorage 已读、动态隐藏）必须用 `window.matchMedia('(max-width:760px)')` 门控——桌面端(>760px)行为与现状逐像素一致（引导默认展开、免责可见、实操表格可见、建议指南可见）。
> 3. 提交前跑双视口验收：`scripts/playwright-accept/accept_mobile_ux_sigkelly.mjs`，390(移动) + 1280(桌面) 都 PASS 才可合。

## 0. 总原则（先读）
1. **数据优先**：移动端 DOM 顺序 = 一行结论 → `.lab-sigkelly-bar`(sticky) → `.lab-sigkelly-grid` → 其余说明后置。
2. **说明一律 `<details>` 默认收起** + localStorage 记住已读。
3. **免责去重**：`risk-banner` 与 `lab-top-disclaimer` 二合一。
4. **sticky 链条**：`.lab-sigkelly-bar` 的 `top` 依赖 `--tab-h / --lab-subnav-h / --lab-subnav-child-h`（lab.css:1367、lab.js:3759 计量）。改动顶部 nav 高度时必须同步这几个 CSS 变量，否则 sticky 悬空。

## 1. 免责二合一 + 移动端折叠（省 ~214px，首屏 223~437）
- 现状：全局 `risk-banner`（status 顶部，app.js:11220 附近，切 tab 不消失）+ lab 页 `lab-top-disclaimer`（lab.js:2438 恒渲染），文案大部分重复（非持牌/不构成投资建议），但 lab 条可能含 lab 专属合规口径。
- **前置（必须，先于任何 CSS）**：三源核对两条免责文案差异（§23.13），确认 lab 专属措辞（回测历史不预示未来、非操作建议等）在合并后有承接，再动手——**不得盲藏**。
- 改法（核对后二选一）：
  - 合并：把 lab 专属句并入全局 `risk-banner`，然后移动端只留一条：
    ```css
    @media (max-width:760px){
      .lab-top-disclaimer { display:none; }          /* 仅当 lab 专属句已并入他处方可 */
    }
    ```
  - 折叠：把 `lab-top-disclaimer` 包成 `<details><summary>📚 免责声明</summary>…</details>` 默认收起，保留全文。
- 验收：合规措辞不丢（核对记录可追溯）；移动端免责收成一条/一行（≤~100px）。

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
根因不是 grid 本身，是 `bar` 与 `grid` 之间插入两大块：
- `auto-trade-steps`（633px，lab.js:9519）= 下一交易日买卖计划 / 蓝框「现在该干嘛」载体，**核心功能，严禁 `display:none`**。
- `lab-sigkelly-advice`（798px，lab.css:1682）。
- 改法：
  - `auto-trade-steps` 外层改 `<details><summary>📋 实操步骤 · 待执行 N 笔</summary>…</details>`，**默认收起成一行 + 保留展开入口**（约 60px），移动端仍能展开看「今天买什么/卖什么」。
  - `lab-sigkelly-advice` 只留 `.lab-sigkelly-advice-summary-short` 一行结论，其余折叠：
    ```css
    @media (max-width:760px){
      .lab-sigkelly-advice .lab-sigkelly-advice-details,
      .lab-sigkelly-advice .lab-sigkelly-advice-outer { display:none; }
    }
    ```
- 验收：auto-trade-steps 默认一行(≤~80px)且可展开；advice 只留一行(≤120px)；grid top 4228 → ≤1600。

## 5. 顶部条减负 + 版本 toast（首屏 0~57 噪音）
- 现状：h5-topbar 含 分享/采集时间/动态/通知×2/主题/登录/策略实验 等，390px 挤作一团；版本更新 `.show` toast 在 623px 处横插。
- 改法：只收敛「采集时间/动态/主题」等**非关键**项；**「通知」入口（`.notify-btn`）必须保留**——通知即时性优先，只可改小图标，不可隐藏。
  ```css
  @media (max-width:760px){
    .h5-topbar .h5-xxx-nonessential { display:none; } /* 按实际 class，仅非关键项 */
    .show { max-height:40px; overflow:hidden; font-size:11px; }  /* toast 单行小 pill */
  }
  ```
- 验收：首屏 0~57 收敛为「标题 + 核心切换 + 通知入口」；`.notify-btn` 仍可见可点。

## 6. 全站统一规范（其余 tab 同款）
- 全局 `risk-banner`、`chart-hint`、`hint-*`、`pf-help`、各「这板块有什么用」统一：`@media(max-width:760px)` 下默认折叠/单行，数据块优先。
- 落地方式：在 style.css 末尾加一个「mobile-progressive-disclosure」公共段 + 一个公共 JS helper `collapseOnMobile('.xx', storageKey)`，逐 tab 套用，避免逐页自造。

## 7. 实施注意 / 风险
- 事件委托：lab.js 大量用 `document.querySelector` 全局监听（如 guide 的 `.lab-sigkelly-guide-trigger` 在 12456 行附近有委托判断），**不要移除 DOM 节点，只折叠/隐藏**，避免委托失效。
- sticky 链条：第 5 条改动若影响 `.lab-subnav` 高度，需同步重算 `--lab-subnav-h`（lab.css:1367 的 top 表达式）。
- 全部改动限制在 `@media (max-width:760px)` 内，桌面端零影响；建议先上 CSS-only 项（1/4/5/6），再上 JS 项（2/3）小步验收。

## 8. 量化目标（验收口径）
移动端(390)：首屏非数据 636px(75%) → <120px；`.lab-sigkelly-grid` top 4228 → ≤1600；解释/引导总占高 4200 → ≤600。
桌面端(1280)：`.lab-top-disclaimer` 可见；`.lab-newbie-guide` 默认展开；`.auto-trade-steps` 可见；`.lab-sigkelly-advice` 可见——与改前一致。

## 9. 复审修正 v3（2026-09-21）：回退「点击≥44px」+ 参数抽屉化
- 背景：上线走查发现外审结论4「点击≥44px」被 implementer 全量套到筛选区每个 chip/按钮（lab.css:2836 起 `min-height:44px` 一串），导致 `.lab-sigkelly-bar` 82→145px（换行成两行）、`.lab-sigkelly-params-body` 展开 644px 占满整屏——判定为回归，用户拍板修正。
- 修正：
  1) **回退「点击≥44px」**：删除 lab.css:2836 起 `min-height:44px` 全套（`.lab-sigkelly-period-btn / -params-toggle / -fee-btn / -toggle-combo / -toggle / -buybasis-btn / -ai-switch-btn` 等），**恢复原紧凑 chip 尺寸**；**不再另设 32~36px 下限**（用户拍板原尺寸足够，热区靠整行/留白，不靠撑高每个按钮）。
  2) **保留**：字号 ≥11px（可读性，未造成问题）+ §1~§6 的数据优先/折叠/免责收敛。
  3) **参数面板底部抽屉化**：`.lab-sigkelly-params-body` 改底部 sheet（`max-height:65vh` + 内部滚动），展开不占满屏、不把主内容顶飞。
- 验收新增哨兵：`M9` 筛选条高 ≤100px（现状 145 会 flag）；`M10` 参数面板展开 ≤55% 视口（现状 76% 会 flag）。

## 10. 实施记录（2026-09-21，feat/mobile-ux-revert-44px，commit f20d9af1e）
- **删除筛选区 44px 全套**：lab.css 原 L2837-2841 + L2848-2852（`.lab-sigkelly-periods .lab-sigkelly-period-btn`/`.lab-sigkelly-params-toggle`/`.lab-sigkelly-fee-btn`/`.lab-sigkelly-toggle-combo`/`.lab-sigkelly-toggle`/`.lab-sigkelly-toggle-more-summary`/`.lab-sigkelly-toggle-tier-cat`/`.lab-sigkelly-toggle-detail-btn`/`.lab-sigkelly-buybasis-btn`/`.lab-sigkelly-ai-switch-btn` 的 `min-height:44px` 及配套 min-width/inline-flex），恢复原紧凑 chip 尺寸；**未另设 32~36px 下限**。
- **保留不回退**：①L2810-2835 移动端字号 ≥11px 覆盖整段 ②L2840-2842 折叠/免责/公示 summary 44px（`.lab-sigkelly-collapse > summary`/`.auto-trade-steps-collapse-summary`/`.lab-sigkelly-advice-outer > summary`/`.lab-top-disclaimer summary`/`.purpose-note-summary`）。
- **参数面板底部抽屉**：`.lab-sigkelly-params-body.lab-sigkelly-params-open` 由 `display:block;width:100%` 改为 `display:block;width:100%;margin-top:4px;max-height:54vh;overflow-y:auto`。
  - ⚠️ **65vh → 54vh 修正**：按 §9 写 65vh 时,390×844 下截断后 ratio=0.65 仍 > M10 硬门槛 55%（0.55）。实测内容自然高 885px（> 视口 844），必须把 max-height 压到 ≤55vh 才可能 PASS；取 54vh，展开 456px / ratio=0.54，M10 PASS。
- **验收**（本地 `BASE_URL=http://localhost:8123`，数据软链主仓库 static-site/data）：M1~M10 全 PASS（M9 barH=83 ≤100；M10 h=456 ratio=0.54 ≤0.55）+ 桌面 D1~D5 全 PASS = 15/15。
- 仅 commit `static-site/lab.css`（1 文件，+3/-13）；`lab.min.css` 本地验证产物已还原，版本串 bump 由 main-merge.sh 统一。

## 10. 复审修正 v4（2026-09-23）：a11y「点击≥44px」全站误伤回退（市场全景等）

- 背景：v3 只回退了 lab.css（凯利区），**style.css 整个漏了**，导致同一批 a11y「点击≥44px」在市场全景等处仍生效，布局变差（用户点名：顶部「每日速递/更多」、周期条）。
- 全量落点（`git grep min-height:44px static-site/*.css`）：

| # | 文件:行 | 选择器 | 处置 |
|---|---|---|---|
| 1 | style.css:4027 | `.summary-ai-btn, .summary-history-btn`（每日速递/更多） | **回退**（实测确认 h=44，桌面 24，是真回归）：删 `min-height:44px`，恢复 `padding:2px 10px` 紧凑 pill |
| 2 | style.css:3937 | `.h5-periods button`（周期条） | **回退**：删 `min-height:44px`（注：**市场全景页该条本就 display:none**，`app.js:11130`；此条仅影响「大盘/情绪」tab 的周期条，仍应回退） |
| 3 | style.css:4065 | `.h5-bottomnav button`（底部主导航） | **保留** 44px（底部主导航，合理） |
| 4 | style.css:2716 | `.futures-*-grid .chart-card h3` | **不动**（标题等高对齐设计，非 a11y 影响） |
| 5 | lab.css 折叠 summary / 免责 summary | `.lab-sigkelly-collapse>summary` 等 | **保留**（折叠触发器，44px 不占版面） |

- 「近期技术分析参考点」区（`sig-acc-*`）：**实测确认 a11y 未碰**——chip 19~21px、12px 字号、padding 0，与桌面同款；观感变差更可能是顶部速递/更多被撑高带偏，或字号 11px 覆盖的连带（待用户指认具体按钮）。
- 范围红线同 §0：仅在 `@media (max-width:760px)` 内改，桌面端零回归。
- 验收哨兵见 `scripts/playwright-accept/accept_market_overview_buttons.mjs`（市场全景两处按钮尺寸）。

