# 首页信号「推荐方法&参考说明」按钮独立化

- 日期：2026-08-14
- 类型：纯前端（app.js + style.css），无后端/数据/算法改动
- 归属：首页信号列表「AI仓位建议 K 档」开关行
- 关联功能：a211 引入的「参考说明」按钮；本改动将其独立化（§23.3 举一反三延伸）

## 背景

首页信号列表「AI仓位建议 K 档」开关行有一个「参考说明」按钮（data-k=help，点击弹「推荐操作方法」说明弹窗）。
原实现**复用 `.sig-kbtn` 样式**（与 off/K 按钮同款），且 `data-no-pop=""` 禁用了 hoverpop（只有 title）。

需求：该按钮需**独立**——不跟「关OFF」按钮一样的 hoverpop 和样式，要有独立样式 + 独立 hoverpop，按钮文字改「推荐方法&参考说明」。

## 改动

### 1. 独立样式（style.css）
- `.sig-kbtn-help-wrap`：自包含定位容器（position: relative），承接独立 hoverpop。
- `.sig-kbtn-help`：独立按钮样式——**主色系描边 + 浅底**（`border: 1px solid var(--primary); background: var(--primary-bg); color: var(--primary)`），hover 反色填充主色。与 off 按钮（红色警示 .sig-kbtn-off）、K 档按钮（普通描边 .sig-kbtn）明显区分。
- `.sig-kbtn-help-pop-wrap` / `.sig-kbtn-help-pop` 等：独立 hoverpop 浮层样式（absolute 定位、自包含、宽 330px、移动端自适应）。

### 2. 独立 hoverpop（app.js）
- `_sigHelpPopHtml()`：独立 hoverpop 内容，**不复用** K 评级表 `_aiPoscapRatingPopHtml`（仓位评级表语义不符）。
- `_bindSigHelpPop()`：绑定函数，**自包含定位**（相对 .sig-kbtn-help-wrap 右对齐、右越界左移），桌面 hover 显示。
- 点击 help 由 `_bindSigSwitchRow` 委托弹说明弹窗（`_openRefHelpModal`），hoverpop **不拦截点击**（无 stopPropagation），桌面/移动端点击均弹弹窗。
- help 按钮移出 `.lab-sigkelly-posrate`（K 评级 trigger），避免与 K 评级 pop 冲突（各管各的 pop）。
- 绑定点：`_bindSigSwitchRow` 首次渲染 + `_rerenderSigCardContent` 重绘后重绑（与 K 评级 pop 同模式）。

### 3. 按钮文字
- 由「参考 / 说明」改为「推荐方法 / 参考说明」（两 span 换行结构保留）。

### 4. hoverpop 内容（与 rule-modal 弹窗口径一致 §22）
- 标题：📖 推荐方法 · 参考说明
- 🔵 短线 A/F：A=买入后固定持有10天卖出；F=买入后持有15天卖出。快进快出，适合波段/资金周转快的玩法。
- 🟢 中长线 G：买入后一直持有，仅当对应指数「卖出信号」触发才离场，无信号就拿着（总建议主选）。可选加 G 仓位管理：持仓超上限先卖「未满3天」年轻仓（保老仓、砍新仓）。
- 底部：💡 点击按钮查看完整操作指南，并可跳转「信号凯利回测」校验 A/F/G 各模式回测数据。

与 `_openRefHelpModal` 弹窗（A=固定10天 / F=持有15天 / G=指数卖出信号触发离场、无信号持有 / P≤3d 先卖年轻仓 / 引导跳转信号凯利回测）逐口径一致。

## 版本

- sw.js CACHE_VERSION：`v6-20260814-a216` → `v6-20260814-a217`
- index.html 等 `?v=` 哈希经 bump_asset_version 刷新（style.min.css 3b674d6f→8ed4717d 等）。

## 自验

1. 按钮文字「推荐方法&参考说明」grep 通过。
2. 独立 class `.sig-kbtn-help` / `.sig-kbtn-help-wrap` 与 off（`.sig-kbtn-off` 红）区分，CSS 独立（20 处 sig-kbtn-help 相关）。
3. `_sigHelpPopHtml` / `_bindSigHelpPop` 独立实现，不复用 `_aiPoscapRatingPopHtml`（后者仅 K 评级表用）。
4. hoverpop 内容与 rule-modal 弹窗口径逐条一致（§22）。
5. node + jsdom 集成测试：mouseenter 显示 pop / mouseleave 隐藏 / help 点击冒泡到行级委托弹弹窗，全部通过；app.js/sw.js `node --check` 语法 OK。
6. sw.js 已 bump 至 a217。
7. 举一反三（§23.3）：K 评级 pop 仍在 `.lab-sigkelly-posrate` 内复用 `_bindAiPoscapRatePop`，不受影响；off/K 按钮逻辑未动；弹窗机制未动。

## 同类面/同模式核对（§23.2 三铁律③ + §23.3）

- 本改动只动 help 按钮样式/文字/hoverpop，off/K 按钮、开关逻辑、弹窗本身均不改。
- 首页「参考说明」按钮（本改）与凯利回测页 A/F/G 三玩法提示（lab.js `_sigKellyAfgRealtimeHtml`）同数据语义，文案口径一致（§21/§22）。
- 无同根因 bug 待修（本任务是功能增强非 bug 修复）。

## 冲突情况

- 本任务在共享主工作区执行（隔离 worktree 未生效），与主控并发修复 staleTxt（app.js L10524 附近）撞车：
  - 我的 app.js help 改动（函数定义/按钮/结构）在编辑期间被主控 commit 29861c890 意外带入（同文件并发）。
  - 我的 style.css 未受影响（主控未改 style.css），正常进入本分支 commit。
  - 已 rebase 到最新 main（e5ec5c940）保证构建产物一致；本 commit 仅含未落入 base 的残留（2 处 `_bindSigHelpPop` 调用 + style.css + 构建产物 + sw a217）。
- 代码逻辑完整正确（函数定义在 base、调用在 commit，缺一不可才生效）。

## 文件

- static-site/app.js（按钮结构 + `_sigHelpPopHtml` + `_bindSigHelpPop` + 2 处调用点 + 结构调整）
- static-site/style.css（独立样式 + hoverpop 浮层样式）
- static-site/app.min.js / static-site/style.min.css（build_min 生成）
- static-site/index.html / about.html / privacy.html（bump_asset_version 刷新哈希）
- static-site/sw.js（CACHE_VERSION a216→a217）
- README.md（功能描述同步 §23.1）
