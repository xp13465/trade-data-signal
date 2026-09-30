# 过拟合监控卡 x 轴标签落后根因调研(#147, 2026-09-30)

> 调研 agent 产出(只读调研, 未提交, 文件留在工作区由主控处理)。
> 现象: #139 修复后准确率图数据末点已到 20260928, 但 x 轴最右刻度标签仍显示 20260922 —— 用户按标签读图会误以为没修好(L42)。
> 本文档: 根因 / 可选修法(含推荐) / 与 #139·#144 冲突判断 / 用户视角验收口径 / 复现段。

## 0. 结论摘要(五问速答)

| # | 问题 | 结论 |
|---|---|---|
| 1 | 根因 | 两图共用自研轻量 SVG 引擎 `_lwSVG`(非 echarts; echarts 仅 ⚡ 开关关闭时的 fallback)。x 轴标签按固定步进 `_xStep` **从最左起采样**, `for (let i = _i0; i <= _i1; i += _xStep)` 不保证覆盖末点 index。实测: 数据末点 index=59, 最右标签 index=55, 落后 4 个交易日 → 09-28 数据、09-22 标签 |
| 2 | 是否可配 | 引擎有显式配置入口 `cfg.xStep`(app.js:18237), 但没有「末点必出标签」开关 —— 需新增(推荐)或改采样循环。业界惯例: echarts 官方 `AxisLabelBaseOption.showMaxLabel/showMinLabel`(官方 types 已核实)即「采样跳显时仍强制显示末/首标签」, 建议自研引擎对齐同语义 |
| 3 | 风险分图是否同病 | **同病**。共用同一引擎同一采样逻辑; main 现状(风险分数据末点 09-22)实测最右标签 09-16(同落后 4 交易日)。#144 merge 后数据末点到 09-28, **仍会出现「标签落后末点」同款现象**, 必须一起修 |
| 4 | 改动影响面 | 修标签动 `_lwSVG` 标签循环(app.js:18248)+ 两图 cfg + echarts fallback 两处 xAxis; **不碰** #139 已上线的 `_overfitAccSeries` 日期并集逻辑(数据层与渲染层独立)。**#139 与 #144 在 `_overfitAccSeries` 有已证实文本冲突**(见 §3), 但都未碰 `_lwSVG` 引擎, 修标签与二者的改动用例无重叠 |
| 5 | 验收口径 | Playwright 无痕打开首页 → 读 `#overfit-acc-chart svg` 最右 x 标签文本 == "20260928"(数据末点)且 hover 末点 tooltip 日期同为 20260928; 截图留档。禁用探针数字作最终证据 |

## 1. 根因(带证据)

### 1.1 渲染链路
- 两图(`#overfit-acc-chart` / `#overfit-risk-chart`)走 `_renderOverfitAcc`(app.js:1796)/ `_renderOverfitRisk`(app.js:1883) → `_lwSetup`(app.js:19019, charts.lightweight 默认 true, 实为 SVG) → `_lwHTML`(app.js:18775) → `_lwSVG`(app.js:18059)。
- echarts 只是 fallback(签约 `charts.lightweight=false` 时, app.js:1841-1858 / 1938-1960)。
- x 轴标签采样的关键代码:
  - app.js:18237 `const _xStep = cfg.xStep != null ? cfg.xStep : _etfXStep(_nView, _iw, _axFont);`
  - app.js:18248 `for (let i = _i0; i <= _i1; i += _xStep)` —— 标签从最左 index 起按步进采样,**末点 index 不整除步进时必然漏掉**
  - app.js:25418 `_etfXStep(n, iw, fs) = floor(标签最大宽 * 1.3 / 每点像素宽) + 1` —— 纯宽度自适应采样, 无「末点必出」语义
  - 对比刻度线循环 app.js:18239 `i <= _i1 + 1`(含末点后一格)——所以**刻度线画到了末端, 曲线也画到末端, 唯独标签采样停在半途**, 视觉上「曲线满右、标签停前」, 正是用户/tester 看到的景象
- 两图 cfg 均未传 `xStep`, 均走 `_etfXStep` 自动采样(boundaryGap:true, dataZoom 仅在 >80 点时开启, 默认 60 点不缩放, `_i1 = _n-1 = 59`)。

### 1.2 量化验证(与用户观测 09-22 完全吻合)
复刻 `_etfXStep` 计算(默认 win=60, viewBox 640 档):
- n=60, pl:40 pr:16, labelW≈30px → step=5 → 最右标签 index=55, 末点 index=59, **落后 4 个交易日**
- 09-28(周一)往回 4 个交易日: 25/24/23/22 → **09-22**。与 tester 观测、Playwright 实测逐字一致。

### 1.3 Playwright 页面实测(main 现状, 线上数据, 2026-09-30 17:00)
| 图 | 数据末点(线上 JSON) | 最右 x 标签(实测) | 标签序列末 3 个 |
|---|---|---|---|
| 准确率图 `#overfit-acc-chart` | `accuracy.rolling.actual["60"]` 末点 **20260928**(n=332, win_rate 34.34) | **20260922** | 20260826 → 20260911 → 20260922 |
| 风险分图 `#overfit-risk-chart` | `overfit.daily_by_win["60"]` 末点 **20260922**(main 现状, #144 未 merge) | **20260916** | 20260818 → 20260904 → 20260916 |
- 准确率图 3 个最右标签 x 坐标 436/492/548, 步进 56px; 风险分图 408.3/469/529.7, 步进 60.7px(两档容器宽度不同)。
- 这是**用户同一视角**的证据(L42 口径): 数据在文件里已到 09-28, 页面 SVG 里最右标签就是 09-22。
- 线下确认: 本地 static-site/data/overfit_monitor.json 是 9-11 旧产物(结构缺 rolling 键), **不能用本地文件判断**; 线上 https://ss.fx8.store/data/overfit_monitor.json(generated_at 2026-09-29 21:40)才是 #139 后的数据层。

## 2. 是否可配(业界依据)

### 2.1 自研引擎现状
- 显式入口: `cfg.xStep` 可传固定步进(app.js:18237), 但**固定步进同样不保证整除 `_i1`**, 传了也救不了末点。
- **没有**「末点/首点必出标签」开关 —— 需新增。

### 2.2 业界惯例(echarts 官方)
- echarts `AxisLabelBaseOption`(官方 npm 包 types, 经 cdn.jsdelivr.net/npm/echarts@5/types/dist/shared.d.ts 核实):
  - `showMinLabel?: boolean`(L2533)/ `showMaxLabel?: boolean`(L2534) —— 语义 = category/轴按 interval 跳显标签时, **仍强制显示最小/最大标签**(正是本项目要的「末点必出」)。
  - 附带 `alignMinLabel` / `alignMaxLabel`(对齐微调)。
- 结论: 「末点出标签」是主流图表库的标准能力, 本项目自研引擎缺失, 补上即可, 不需要换库。若走 echarts fallback 分支, 直接加 `axisLabel: { showMaxLabel: true }`(官方 API, 类型已核实)。
- 补充: 2026-09-29 晚 tester 独立复测报告的口径与本文档 §1.3 一致(#147 观察项来源)。

## 3. 与 #139 / #144 的关系与冲突判断

### 3.1 #139(已在 main, commit a8ec330e0)
- 只改 `_overfitAccSeries`(app.js:1762): 日期驱动改为「回测 ∪ 实盘」并集 + 缺失侧 null 桥接。**未碰 `_lwSVG` / `_etfXStep` / 两图 cfg**。
- 修标签不碰该函数 → **无冲突**。

### 3.2 #144(分支 worktree-agent-a7cbb8af4e8d8d9f0, HEAD 8ab0b5f31, 基于 4e99c2d6d)
- 改动: ① `_overfitAccSeries` 同样重写为并集驱动(但实现与 #139 不同: 回测空走单独分支、btMap 加 win_rate!=null 条件) ② `_renderOverfitRisk` 加末端 null 原因说明 ③ `_ovDeriveDaily` 复刻同步 ④ 后端 `scripts/overfit_monitor.py _derive_daily_series` 并集改造。
- **重大事实: #144 分支不含 #139**(`git merge-base --is-ancestor a8ec330e0 HEAD` = 否)。两者都改了 `_overfitAccSeries`, 已用 `git merge-tree --write-tree main worktree-agent-a7cbb8af4e8d8d9f0` 只读预演:
  - `Auto-merging scripts/overfit_monitor.py`(干净)
  - **`CONFLICT (content): Merge conflict in static-site/app.js`**(实锤)
- 即: **#144 直接 merge main 必撞 `_overfitAccSeries` 文本冲突**(语义趋同、两侧各自实现), 消解需人工二选一或合并两者语义(建议: #139 已在 main 且已过 §0 验收, 保留 main 版为主, #144 的 risk 图相关增量(末端说明)保留)。
- 与「修标签」的关系: #144 与 #139 都没碰 `_lwSVG` 引擎 → **修标签与 #139·#144 的改动用例零重叠**; 但若修标签的 feat 与 #144 并行, 会一起撞在同一条 merge 线上 —— 建议**先合 #144(消解冲突)再派修标签**, 或修标签直接基于 #144 分支之后的状态。

### 3.3 计划排布建议(默认推荐)
- 本轮: #144 先按现有流程 merge(手工消解 `_overfitAccSeries` 冲突, 保留 main 的 #139 语义 + #144 的 risk 增量)。
- 紧接: 派 implementer 修「末点标签」(改动如 §4 方案A+fallback), 单独 feat 分支。
- 验收见 §5。

## 4. 可选修法(含推荐)

### 方案 A(推荐, 一步到位)
**`_lwSVG` 新增「末点标签补出」机制(对齐 echarts showMaxLabel 语义)+ 两图开启 + fallback 同步**:
1. `_lwSVG`(app.js:18248 附近): x 标签循环改为 `for (let i = _i0; i < _i1; i += _xStep)` + 循环后补: 若 `(_i1 - _i0) % _xStep !== 0` 且 `cfg.forceLastLabel` 为真, 则在 `_px(_i1)` 处补画 `_xFmt(cfg.xLabels[_i1])` 标签(样式同现有标签)。
2. 新增 cfg 开关 `forceLastLabel`(默认 false/undefined → 全站其他 lite 图(走势/恐贪/情绪分等)行为零变化, 符合 §23.7 冻结契约)。过拟合两图 `_renderOverfitAcc`(1822 处 cfg)与 `_renderOverfitRisk`(1915 处 cfg)各加一行 `forceLastLabel: true`。
3. echarts fallback 两处 xAxis(1852 / 1944)加 `axisLabel: { showMaxLabel: true }`(官方属性, 已核实), 保证 ⚡ 切「完整版」时同样末点出标签 —— 否则只修 lite 不修 fallback, ⚡ 一关又退回原状(tester/用户切开关验证时必踩)。
- 工作量: 引擎 ~8-12 行 + 两图 cfg 各 1 行 + fallback 两处各 1 行。小。
- 风险: ① 末点与相邻标签的间距 = `余数 × unitW`, 余数=1 时可能轻微拥挤(echarts showMaxLabel 同款行为, 接受); ② 开关默认关闭, 全站其他图零影响; 仍需跑一次 lite 图回归(§15, 至少首页 KPI/恐贪/情绪分/分时 各看一眼)。
- 覆盖: lite 与 fallback 双路径都修 = 完整正确, 不存在「只修一半」。

### 方案 B(备选, 不推荐)
两图传固定 `xStep`, 使 `(n-1) % xStep == 0` 时恰好覆盖末点。缺点: 步进依赖容器宽度/点数, 固定值在不同视口(桌面/移动)必有一个不整除, 不可靠, 是偷懒版 → 不选。

### 方案 C(备选, 引擎全局强制)
`_lwSVG` 末点标签无条件补出(不加开关)。优点: 全站所有 lite 图一致改善; 缺点: 触碰全站所有图表渲染, 回归面大, 且某些图(如 180 点数据、dataZoom 图)末点标签可能与 slider 重叠, 违背 §23.7「默认只新增不改旧」 → 不推荐本轮做, 可留作后续全局优化项。

**推荐 = 方案 A**。理由: 完整正确(两图 + 双渲染路径全覆盖)、影响面收敛(开关默认关)、工作量小、对齐业界惯例(echarts showMaxLabel 同语义)。

## 5. 用户视角验收口径(#5 问)

1. **主证据(用户同一视角)**: Playwright 无痕打开首页 → `#overfit-acc-chart svg` 最右 x 标签文本 == **"20260928"**(与数据末点 `rolling.actual["60"]` 末点一致); 鼠标 hover 最右曲线点 tooltip 显示日期 == 20260928; 截图留档(标签读数 + 曲线末端位置)。
2. **风险分图同口径**: `#overfit-risk-chart` 最右标签 == 数据末点(#144 合入后应 == 20260928)。
3. **双渲染路径**: ⚡ 开关切「📈 完整版(echarts)」再测一次最右标签 == 数据末点(验证 fallback 的 showMaxLabel); 切回 ⚡ 再验一次(防撕裂双向)。
4. **回归**: 全站 lite 图(首页 KPI 走势/恐贪/情绪分/分时)肉眼 + console pageerror NONE; 过拟合卡 24 交互(win/roll/grade/sig/K 档)不回归(参照 #139 自验清单)。
5. 禁用「探针读代码/读 JSON」当唯一证据 —— 必须页面实测读数 == 数据末点才算修好(§5.4⑦ / L42)。

## 6. 复现段(命令 + 实测值)

```bash
# ① 起本地静态站(static-site 目录)
cd /Users/linhuichen/code/trade/static-site && python3 -m http.server 8347

# ② 拉线上数据层(别用本地 9-11 旧产物)
curl -s -A "Mozilla/5.0" https://ss.fx8.store/data/overfit_monitor.json -o /tmp/overfit_online.json
curl -s -A "Mozilla/5.0" https://ss.fx8.store/data/overfit_monitor_ext.json -o /tmp/overfit_ext_online.json

# ③ Playwright 实测(脚本 /tmp/xaxis-test.cjs, 读 svg 底部 y>H-60 的 text 按 x 排序取最后)
# 实测值(2026-09-30, main fb38c25bc, 线上数据):
#   准确率图最右标签 = 20260922   (数据末点 20260928, generated_at 2026-09-29 21:40)
#   风险分图最右标签 = 20260916   (数据末点 20260922 — #144 未 merge 的 main 现状)
#   两图均落后 4 个交易日, 与 _etfXStep(n=60)=step5、末点index59、最右标签index55 的复刻计算逐位一致

# ④ 冲突预演(只读, 不写工作区)
git merge-tree --write-tree main worktree-agent-a7cbb8af4e8d8d9f0
#   输出: CONFLICT (content): Merge conflict in static-site/app.js  (scripts/overfit_monitor.py auto-merge 干净)
```

## 7. 已验证方法 / 数据源清单(§1 skill 要求)

- 代码路径: `static-site/app.js` `_lwSVG`(18059)/ `_etfXStep`(25418)/ `_lwSetup`(19019)/ `_renderOverfitAcc`(1796)/ `_renderOverfitRisk`(1883)/ `_overfitAccSeries`(1762) —— 全文读取, 非猜。
- 数据产物层: 线上 `https://ss.fx8.store/data/overfit_monitor.json`(末点 20260928)✅ / 线上 ext ✅ / 本地 static-site/data 9-11 旧版(排除, 结构不符)✅ 三处对比过。
- 页面实测: Playwright(local playwright-accept node_modules, 无痕, route 覆写线上两 JSON)实测两图最右标签 —— 用户同一视角证据 ✅。
- 外部惯例: echarts 官方 types(jsdelivr npm echarts@5 types/dist/shared.d.ts)核实 `showMaxLabel/showMinLabel` ✅(WebFetch 官方文档域名被网络策略拦, 退而用官方 npm 类型即 API 契约, 同样权威)。
- 冲突预演: `git merge-tree --write-tree` 只读三路合并 ✅。
- **诚实标注**: ① 修标签的「末点补标签间距过近时的视觉表现」没实测过(需 implementer 落地后按 §5 验收); ② echarts 官方文档页面自身未能直接抓取(网络限制), 以官方 npm 类型定义替代, 属性语义(showMaxLabel=强制显示最大标签)由属性名 + echarts 通用语义推断, 与社区共识一致, 风险低; ③ #144 的 risk 图末端 null 说明与「末点标签」改动同文件相邻区域(都是 _renderOverfitRisk), 若并行改需注意行合并, 顺序执行则无此问题。

## 8. 落档信息

- 调研 agent 产出, 只读调研(仅写了本报告文件, 未 commit 未建分支)。
- 涉及 #147(pending-index), 主控随后安排 implementer 按方案 A 实施。
