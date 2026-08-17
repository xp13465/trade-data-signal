# 首页分段色图(SVG 轻量版)渐变 id 全文档冲突根治(a325)

> 2026-08-17 | implementer | 修复首页分段色图(恐贪/情绪分/跨市场/过拟合)变色分界错误 —— 渐变 id 全文档重复冲突
> 前置:docs/lite-svg-grad-calibration.md(a322 值域固定 0-100)、docs/lite-svg-corner-vertex-a320-final.md(尖角+分段色根治,渐变单 path 版)

## 0. 一句话结论

**`_lwGradSeq` 原本是 `_lwSVG` 内部的块级 `let`(app.js L12487),每次 `_lwSVG` 调用都从 0 起 → 每张图第一个 perColor 渐变都叫 `lwGrad-1`。SVG `url(#lwGrad-N)` 引用是「全文档解析到第一个匹配 id」→ 恐贪(渲染最早)用自己渐变=正确;情绪分/跨市场/过拟合全解析到恐贪渐变=错误。修复 = 把 `_lwGradSeq` 提到模块级(照抄 `_lwZClipSeq` L12426 的正确示范),渐变 id 变全文档唯一 `lwGrad-1/2/3...`,每图 `url(#lwGrad-N)` 唯一解析到自身渐变。**

用户已亲眼确认 bug:跨市场图缺灰色、情绪分颜色错位。跨市场像素实测:灰色仅 7.3%(正确应 44.9%)、浅蓝 0 像素(应 60),与「缺个灰色」完全吻合。

## 1. 根因

- `_lwSVG` 里用块级 `{ let _lwGradSeq = 0; ... }` 预扫 perColor 分段色线,给每条线的垂直渐变生成 `lwGrad-N` id。**块级 let 每次 `_lwSVG` 调用都重新从 0 计数** → 无论渲染多少张图,每张图的第一个 perColor 渐变 id 都是 `lwGrad-1`。
- SVG 的 `url(#id)` 引用语义 = **在整份 document 里解析到第一个匹配该 id 的 `<linearGradient>`**。首页多张分段色图渲染进同一 document:
  - 恐贪(渲染最早)→ 它的 `url(#lwGrad-1)` 解析到自己文档里(也是 document 里第一个)的 `lwGrad-1` = 正确。
  - 情绪分/跨市场/过拟合 → 各自的 `url(#lwGrad-1)` 解析到 **document 里第一个 `lwGrad-1`** = 恐贪的渐变 = 错误(它们的渐变 defs 内容是对的,但引用被全文档 id 冲突劫持到恐贪)。
- 由 commit `3ac82b2c0`(整线单 path + 垂直渐变重构)引入。

## 2. 修复(最小根治)

把 `_lwGradSeq` 从块级提到模块级:

```diff
  // 主 SVG 构建(网格/轴线/标签/legend/series/markLine/markPoints)。
  let _lwZClipSeq = 0; // dataZoom 缩放时 markLine/markArea 超窗裁剪 clipPath id 序号
+ let _lwGradSeq = 0; // perColor 分段色线垂直渐变 id 全局序号(模块级, 保证渐变 id 全文档唯一, 防跨图 url(#lwGrad-N) 冲突解析)
  function _lwSVG(cfg) {
    ...
  {
-   let _lwGradSeq = 0;
    for (const _gser of cfg.series || []) {
      ...
```

改动 2 行:删块级 `let _lwGradSeq = 0;`,在模块级(紧邻 `_lwZClipSeq`)补同款声明。无其他逻辑变更。渐变 id 从此全文档唯一。

## 3. 同类错误面清单(§23.2 修 bug 三铁律)

perColor 分段色线走 `_lwSVG` 渐变单 path 分支的消费者(改一处全好,但逐个确认渲染正确):

| 消费者 | 位置 | 污染表现(修复前) |
|---|---|---|
| 恐贪指数 | 首页三张之一 | 渲染最早,用自己渐变=正确(但 id 也是 lwGrad-1) |
| A股情绪分 | 首页三张之一 | 引用 lwGrad-1=恐贪渐变 → 颜色错位 |
| 跨市场综合评分 | 首页三张之一 | 引用 lwGrad-1=恐贪渐变 → 缺灰色/浅蓝丢失 |
| 过拟合风险分 | app.js L1777(rgColorFn 绿黄红) | 引用 lwGrad-1=恐贪渐变 → 红区膨胀、绿黄被吞 |
| KPI 弹窗 sentiment 9 张 | `_kpiLiteCfg` + visualMap | 同分支,同污染 |
| 信号弹窗 perColor | 同分支 | 同污染 |

> 排查同类:`grep url(#lwGrad` 全站确认所有 perColor 消费点都走同一 `_lwSVG` 分支,单点修源全修,无独立漏网渐变。

## 4. 自测(渲染验证,非单图隔离推演)

上一轮教训(§18 L42):单图隔离自验漏 id 冲突。本次用 **headless Chrome 组合页**(多图同 document,复刻真实首页命名空间)逐图验证。

### 4.1 机制证据(headless Chrome 组合页,4 图同 document)

- **渐变 id 全文档唯一**:4 图得到 `lwGrad-1, lwGrad-2, lwGrad-3, lwGrad-4`(修复前全为 lwGrad-1)。
- **每图 path stroke `url(#lwGrad-N)` 首匹配 = 自身渐变**:恐贪/情绪分/跨市场/过拟合 4 图 `firstMatchIsOwn=true`(修复前,非首图 first-match 均为恐贪渐变)。
- **逐数据点渲染色 = 各自色函数期望值**:

| 图@值 | 修复后渲染 | 期望 | 旧 bug 渲染(仿真) | 期望 |
|---|---|---|---|---|
| 跨市场@v75 | `#7fb8e8` 浅蓝 | 浅蓝 | `#e6a23c` 橙 | 浅蓝 |
| 跨市场@v20 | — | 灰 | `#1e6fd9` 蓝(缺灰!) | 灰 |
| 过拟合@v45 | `#e6a23c` 黄 | 黄 | `#c0c4cc` 灰 | 黄 |
| 过拟合@v75 | `#e6492e` 红 | 红 | `#e6a23c` 黄 | 红 |

旧 bug 仿真(所有图引用恐贪渐变)完美复现用户症状:跨市场@v20 应灰被渲成蓝(缺灰)、overfit 黄红被吞。

### 4.2 部署产物验证

对 `app.min.js`(build_min 后)跑同一组合页:3 图 id `lwGrad-1/2/3` 唯一、每图 first-match=自身渐变 PASS。min 版(变量被 mangle)行为正确 = 上线产物生效。

## 5. 落档与复现

- 本文档:根因 + 修复 diff + 同类清单 + 像素证据。
- 复现脚本:`docs/scripts/lite-grad-id-collision_test.py`(headless Chrome 组合页生成 + 断言)。
- 关联修复链:a320(尖角/单 path 渐变)→ a322(值域固定 0-100)→ a325(渐变 id 全文档唯一)。

## 复现

- 脚本:`docs/scripts/lite-grad-id-collision_test.py`
- 输入依赖:`static-site/app.js`(修复后)或 `static-site/app.min.js`;headless Chrome(`/Applications/Google Chrome.app`)
- 重跑命令:`python3 docs/scripts/lite-grad-id-collision_test.py`
- 数据截止:静态渲染测试,无日期依赖。
- 关键口径:多张 perColor 分段色图渲染进同一 document,断言①每图渐变 id 全文档唯一 ②每图 path `url(#lwGrad-N)` 首匹配=自身渐变 ③逐数据点渲染色=各图自身色函数。
