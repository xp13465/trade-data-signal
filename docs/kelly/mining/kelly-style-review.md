# kelly-style-review — commit bca96c9e5 独立审查报告

- 审查 commit: `bca96c9e5` "凯利区样式合群调整"(组合建议对齐 AI 报告 db-* 风格 + 全信号表按年表右移横向并排)
- 审查日期: 2026-08-12
- 审查人: 独立 task-reviewer(fresh context, 只读)
- 结论: **PASS** — 改动只影响凯利区目标区域, 无老功能受影响, 内容未变, 线上已生效

## 1. 改动文件清单(核实)

`git show bca96c9e5 --name-only` 确认只改 5 文件, 与实施 agent 报告一致:
- static-site/lab.css, lab.js, lab.min.css, lab.min.js, sw.js

**未碰** app.js / index.html / style.css(style.css 是 AI 报告 db-* 样式定义处, 未被改, 见 §3)。

commit 已在 main 链上(`git merge-base --is-ancestor bca96c9e5 origin/main` = ON_MAIN)。

## 2. 影响面(grep 改动 class 被谁消费)

| 改动 class | 消费者 | 结论 |
|---|---|---|
| lab-sigkelly-all-main / all-card / all-yearly | 仅 lab.js `_sigKellyAllSignalGroupHtml`(L8373-8375)+ lab.css(L1562-1566) | 无外部消费 |
| lab-sigkelly-advice-* (advice-title/details/verdict/li/note) | 仅 lab.js `_kellyComboAdviceHtml`(L8314 起)+ lab.css | 无外部消费 |
| lab-sigkelly-grid | 仍用于 16 卡分组(`_renderSigKellyQuadrants` L8405), CSS L1459 仍在 | 全信号表弃用该 wrapper, 不影响 16 卡分组 |
| lab-sigkelly-bar(index.html 有引用) | 独立 nav class, diff 未触碰 | 不受影响 |

- **app.js 0 处 sigkelly 引用**;index.html 仅 `.lab-sigkelly-bar`(nav 样式, 未改)。凯利区样式只在策略实验室 tab 内生效, 首页/其他 tab 不消费这些 class。
- `_updateSigKellyQuadrantsInPlace`(L8439): query `.lab-sigkelly-all-group`(容器 class **未变**, 含 loading 占位 L8351 也用同容器), outerHTML 整组替换为新结构。**不依赖旧 grid wrapper**, 与首次渲染同源(`_sigKellyAllSignalGroupHtml`), 轮询/事件/跨函数无别处引用旧结构。3 处调用(L7703/7729/7765)同一函数, 均走新结构。

## 3. db-* 对齐未误改原样式(核实)

- 本 commit **未 touch style.css**(db-* 定义文件)。lab.css 中 db-* 仅出现在注释(L1535-1536, 记录对齐依据)。
- 对齐是"复制 db-* 样式值进 lab-* 独立 class", 非修改 AI 报告原样式。AI 报告 db-highlights/db-debate-wrap/db-note 原样式零改动。

## 4. 内容未变验证(亲自 diff, 不轻信报告)

- lab.js 整个 diff 只 1 个 hunk(`_sigKellyAllSignalGroupHtml`), 仅改 wrapper 结构(去掉 `lab-sigkelly-grid` 包层, 换 `lab-sigkelly-all-main` flex 包层), `cardHtml`/`yRows` 文本原样内联, **无任何数字/文案改动**。
- `_kellyComboAdviceHtml`(组合建议内容, 含全部数字 50,661/66,726/+10,867,390 等)在 diff 中 **0 改动**。
- lab.css 只改 advice 样式值(字号/颜色/行高/背景)+ 新增 flex 布局, 无逻辑。

## 5. 布局风险点(≤1080px 回退)

- 新增 `@media (max-width: 1080px)` 回退列堆叠(flex-direction: column + width 100%), 覆盖窄屏。全信号卡 `flex:1 1 500px` + 按年表 `flex:0 1 auto` 横向并排; 中间宽度段靠 `flex-wrap: wrap` 自然换行, 不会溢出。
- 按年表内 td `white-space: nowrap` 仍被 `.lab-sigkelly-table-scroll`(overflow-x auto)保护, 不会撑破布局。该 wrapper 未变。

## 6. 线上生效 smoke(curl ss.fx8.store, 已验证)

| 检查项 | 结果 |
|---|---|
| 线上 lab.min.js 含 `lab-sigkelly-all-main` | ✅ |
| 线上 lab.min.css 含 `c87a1a`(琥珀标题色) | ✅ |
| 线上 lab.js(源码)含新结构 `lab-sigkelly-all-main` | ✅ |
| 线上 sw.js CACHE_VERSION | ✅ `v6-20260812-a143` |
| 本地 min 与源一致 | ✅ (lab.min.js 含 all-main / lab.min.css 含 c87a1a) |

## 7. 观察项(非阻断, 记录不判 FAIL)

- **未跑 bump_asset_version**: index.html 仍引用 `lab.min.js?v=6848510f` / `lab.min.css?v=771f478e`(旧 hash)。commit 说明为与并行 agent 改 index.html 规避撞车。风险评估: SW CACHE_VERSION 已 bump a143 + cacheFirst 按全 URL 键 + a143 新缓存容器为空 → SW 用户首访必 fetch 新内容(cache miss → 网络 → put 新), 旧 v= hash 仅影响无 SW 的返回用户 HTTP 缓存边缘路径。**不阻断上线**, 属实施 agent 明示的并行规避决策。后续并行 agent 跑 bump_asset_version(index.html 提交)会一并补上新 hash, 建议在 TASKS 标注待确认。

## 问题清单

- [x] 无 P0/P1 问题, 无老功能受影响。
- [x] 组合建议内容数字零改动(亲自 diff 验证)。
- [x] db-* 原样式未动(commit 未 touch style.css)。
- [x] 线上三查(代码 main 链 / 数据层样式产物 / 前端展示层 min+sw)全通过。

**结论: PASS**
