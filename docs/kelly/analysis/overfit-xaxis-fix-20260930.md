# 过拟合卡 x 轴末点标签修复实施记录(#147, 2026-09-30, 右锚定采样版)

> 实施 agent 产出。前置调研: `docs/kelly/analysis/overfit-xaxis-label-20260930.md`。
> 现象: #139 修复后准确率图数据末点已到 20260928, 但 x 轴最右刻度标签停在 20260922 —— 用户按标签读图会误以为没修好(L42 同款)。
> 本文档: 改动点 / 验收证据(含「不重叠」硬断言结果与 FAIL 如实上报)/ 视觉重叠实测 / 复现段。
> **方案演进(主控指示)**: 第一版「补末点标签」被主控否决(末两标签固有重叠约 16.5px), 改为**右锚定采样**——保证末点必为采样点且相邻标签间距恒为常规步进, 末两标签天然不重叠。

## 0. 结论摘要

| # | 问题 | 结论 |
|---|---|---|
| 1 | 修了什么 | ① 自研 `_lwSVG` 引擎新增 `forceLastLabel` 开关(**默认 false/undefined**, 全站其他 lite 图行为零变化, §23.7 冻结) ② 只给过拟合两图(准确率/风险分)cfg 各开 `forceLastLabel: true` ③ echarts fallback 两处 xAxis `axisLabel: { showMaxLabel: true }`(**保留不动**)。**未碰** #139/#144 的 `_overfitAccSeries` 数据层逻辑 |
| 2 | 修好没有 | **末点标签修好**(右锚定): lite 两图最右标签均 == 数据末点 **20260928**, hover 末点 tooltip 同日; fallback 双图 `showMaxLabel=true` 生效、dataLast==20260928。回归: 全站其他 lite 图标签(位置+文本)与基线逐个一致 |
| 3 | 硬断言(不重叠) | **35 PASS / 1 FAIL, 已如实上报**: acc(lite) 图**全列相邻标签**按 DOM `getBoundingClientRect()` 盒宽判定, 间距 55.3~55.4px < 真实文本宽 57.6px, 差 2.2px(最差对 20260622->20260729)。**risk(lite) 通过**(间距 60px ≥ 57.6px)。根因非右锚定引入: `_etfXStep` 按 `"MM-DD"` 5字符×1.3≈43px 算步进, 过拟合图标签是 8 位日期真实宽 57.6px——引擎**全局既有口径**, 基线/全站其他图同此间距(55.4px), 非本次改动产生 |
| 4 | 末两标签实测 | acc: 20260915->20260928 间距 **55.4px**; risk: 末两间距 **60.0px**。文本真实渲染宽(DOM rect == 页面实际字体 measureText)= **57.6px**(20260729/20260928)与 **55.2px**(20260915)。acc 末两标签间距 55.4 < 57.6 亦差 2.2px(与全站同口径); 相对被否决的补标签版(36.9px 间距)已大幅恢复至常规步进间距 |
| 5 | 最左端标签 | 右锚定后 acc 最左标签由 20260323(x=81.5) 变为 **20260427(x=85.4)**, 左端少了一格并右移 3.9px——属可接受偏移(轴起点不必有标签, 对齐 echarts showMaxLabel 语义), 已在 §3 说明实测 |
| 6 | merge-base | `git merge-base HEAD origin/main` = **81c50965b35e93b3ed6ffae50918580652160654**(与 origin/main 持平, base 新鲜, 开工前已 merge origin/main) |

## 1. 改动点(全在 `static-site/app.js`, diff 可反查)

| # | 位置 | 改动 |
|---|---|---|
| 1 | `_lwSVG` x 标签循环(app.js:18284 附近) | `forceLastLabel` 开启时采样起点右锚定: `_lbl0 = _i1 - Math.floor((_i1-_i0)/_xStep)*_xStep`(= `_i0 + ((_i1-_i0)%_xStep)`, 恒落 `[_i0, _i0+_xStep)`), 然后 `for (let i = _lbl0; i <= _i1; i += _xStep)` → **末点 _i1 必为采样点且有标签**, 相邻间距恒为 `_xStep×unitW`(常规步进)。开关默认关/undefined = 走原左采样逻辑, 引擎行为零变化 |
| 2 | `_renderOverfitAcc` cfg(app.js:1822 附近) | `forceLastLabel: true` |
| 3 | `_renderOverfitAcc` echarts fallback xAxis(app.js:1852 附近) | `axisLabel: { showMaxLabel: true }`(**保留不动**) |
| 4 | `_renderOverfitRisk` cfg(app.js:1931 附近) | `forceLastLabel: true` |
| 5 | `_renderOverfitRisk` echarts fallback xAxis(app.js:1957 附近) | `axisLabel: { showMaxLabel: true }`(**保留不动**) |

- 语义: 对齐 echarts 官方 `AxisLabelBaseOption.showMaxLabel`(调研 §2.2 已核实官方 npm types)。
- 范围红线核对: **未动** `_overfitAccSeries`(#139/#144 数据层)、未动 `_etfXStep`、未动任何其他图 cfg、未改 static-site/data、未 bump 版本串(机制 C)。
- 右锚定无需短格式/缩字号补丁: 只要 `_xStep > 0`, 相邻标签间距恒为步进整数倍, `_etfXStep` 按「标签最大宽×1.3÷每点px宽」保证不重叠(注: 其量宽对象是 `"MM-DD"` 5字符, 见 §3)。

## 2. 验收证据(Playwright 无痕, 线上数据)

验收脚本: `scripts/playwright-accept/verify_overfit_xaxis_lastlabel.mjs`(入库)。**结果: PASS=35 FAIL=1**(唯一 FAIL 为 acc lite 不重叠硬断言, 详见 §3)。

### ① lite 路径(改后 app.js)
- acc/risk 两图 `forceLastLabel` 均开启(PASS)
- acc 数据末点 == 最右标签 == **20260928**(PASS); risk 同(PASS)
- hover 两图末点 tooltip 日期同日 09-28(PASS, risk 末点 risk_score 为 null 时 tipFn 返回原始 8 位日期, 脚本兼容两种格式)
- **不重叠硬断言**: risk PASS(间距 60 ≥ 57.6); **acc FAIL**(最差对 20260622->20260729 间距 55.3 需 ≥ 57.6) —— 详 §3
- lite 路径零 pageerror(PASS)
- 截图: `/tmp/xaxis147-acc-lite.png` / `/tmp/xaxis147-risk-lite.png`

### ② 回归(基线 = main 版 app.js `/tmp/app_main_baseline.js`)
- lite 图数量基线=改后(20 张非过拟合图), **每张日期标签(文本+位置 svgX)与基线逐个一致**(PASS)——证明开关默认关 + 两图以外零变化
- 两图曲线数据末点 + seriesLen 基线=改后(PASS)——证明只加了标签, 曲线/数据未被碰
- 基线路径零 pageerror(PASS)

### ③ fallback 路径(⚡ 关 → echarts, 改后 app.js + `sitecfg:charts.lightweight=false`)
- acc/risk 均走 echarts canvas(PASS), `showMaxLabel=true` 生效(PASS), `dataLast==20260928`(PASS)
- fallback 零 pageerror(PASS)
- 截图: `/tmp/xaxis147-acc-fallback.png` / `/tmp/xaxis147-risk-fallback.png`

## 3. 不重叠硬断言结果与如实上报(不确定项①)

**主控口径**: 「断言相邻标签矩形不相交(保守: 相邻标签中心距 ≥ 文本实测宽 × 1.0)」, 要成为硬断言。

**实测结论(必须如实, 不造假 PASS)**:

1. **acc(lite) FAIL**: 全部相邻日期标签按 DOM `getBoundingClientRect()` 实测, 中心距 55.3~55.4px, 文本宽 57.6px(最差对 20260622->20260729 差 2.3px)。**不止末两, 是整列**。
2. **risk(lite) PASS**: 间距 60.0px ≥ 文本宽 57.6px。
3. **57.6 是真实渲染宽, 非测量误差**: 用页面实际字体 `12px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif` 的 canvas measureText 实测 = 57.6px, 与 DOM `getBoundingClientRect().width` 完全一致; 之前探针用的默认 `12px sans-serif` 测出 53.4px 是**低估**(差异来自字体栈, 非 svg 渲染盒虚宽)。
4. **根因不是右锚定, 是 `_etfXStep` 量宽对象**: L25461 `_etfXStep` 用 canvas measureText(`"MM-DD"`, fs px sans-serif)×1.3 ≈ 43px 算步进——这是给 ETF 走势图(MM-DD 标签)设计的口径; 过拟合图标签是 **8 位日期 `YYYYMMDD`**, 真实宽 57.6px > 43px → 常规步进间距(55.4px)天然小于文本宽。基线(左采样)/全站其他日期标签图均同此间距, **该 2.2px 盒级重叠是引擎既有状态, 非本次改动引入, 与开关默认关时完全一致**。
5. **末两标签主诉求已解决**: 被否决的补标签版 acc 末两间距 36.9px(重叠 16.5px)→ 右锚定 55.4px, 与全站常规间距一致; risk 60px。即「末点与前一采样标签特别拥挤」的固有缺陷已消除, 残余的 2.2px 盒级轻微重叠是引擎全局口径, 用户此前未对该口径报过异常(数字字符 ink 实际间距仍为正)。

**请主控拍板(§23.7, 不自行调整)**, 三选一:
- **A(接受, 推荐)**: 残余 2.2px 盒级重叠属引擎全局既有口径、与基线完全一致, 硬断言口径改为「间距 ≥ 页面实际字体 measureText 宽」并按全列记录(或仅保留末两标签不重叠断言)。需用户/主控确认后才能改脚本口径。
- **B(单图调距)**: 仅对过拟合两图 cfg 增 `xStep` 覆盖(使 acc 间距 ≥ 57.6px), 会减少 acc 标签数量(11→约 10)且属新增开关参数, 超原「只加 forceLastLabel」范围, 需主控批准。
- **C(全局修 `_etfXStep` 量宽)**: 把量宽对象从 `"MM-DD"` 改为实际标签格式(8 位日期), 会改变**全站**所有 lite 图标签密度 → 破坏②回归断言, 违反「其他图零变化」, 不建议。

**当前提交保持**: 代码已按右锚定落地(主诉求末点标签+末两不挤已解决), 硬断言 FAIL 如实记录于此并上报, 未为凑 PASS 改口径。

## 4. 右锚定实测表现(最左端偏移/末两间距)

Playwright 读 svg 文本 x 属性 + DOM rect 实测(改后 lite 两图):

| 图 | 标签数 | 最左标签 | 最右标签(=末点) | 末两间距 | 全列相邻间距 |
|---|---|---|---|---|---|
| 准确率图 | 11 | **20260427**(x=85.4, 基线最左为 20260323 x=81.5 → 右移 3.9px、左端少一格) | 20260928(x=635.4) | **55.4px** | 55.3~55.4px |
| 风险分图 | 10 | 最左标签同基线偏移 | 20260928(x=635) | **60.0px** | 60px |

- 最左端偏移/少一格 = 右锚定预期行为(起点 = `_i0 + ((_i1-_i0)%_xStep)`, 首个采样点向右缩), 属可接受(轴起点不必有标签, 对齐 echarts showMaxLabel 语义), 已实测留档。
- 文本真实渲染宽(DOM rect == 页面实际字体 measureText): 20260729/20260928 = 57.6px, 20260915 = 55.2px; 默认 `12px sans-serif` 为 53.4px。

## 5. 诚实标注

- ① acc(lite) 不重叠硬断言 FAIL(2.2px 盒级)是**如实上报的真实结果**, 未为凑 PASS 造假; 根因是 `_etfXStep` 量 `"MM-DD"` 口径对 8 位日期标签不足, 引擎全局既有、非本次引入, 与基线完全一致。
- ② 截图已留档但**本会话模型不支持读图**(§13), 视觉判定基于 svg 文本 x 坐标 + DOM rect / measureText 数值证据, 非肉眼截图。
- ③ 数据层证据用线上 overfit_monitor.json(09-29 21:40 产物), 未用本地 9-11 旧产物(调研 §1.3 已指出其结构不符)。
- ④ 方案演进如实记录: 第一版「补末点标签」(commit c2e85101c)被主控否决后改右锚定, 旧版实现已在后续 commit 中被替换, 本文档只描述右锚定版最终态。

## 6. 复现段(命令 + 实测值)

```bash
# ① 验收脚本(在 worktree 内, playwright-accept node_modules 已有)
cd /Users/linhuichen/code/trade/.claude/worktrees/agent-a25e29c4db5dba109/scripts/playwright-accept
# 前置: /tmp/overfit_online.json /tmp/overfit_ext_online.json(线上 09-29 21:40 产物), /tmp/app_main_baseline.js(main 未改版)
node verify_overfit_xaxis_lastlabel.mjs
# 输出: 结果: PASS=35 FAIL=1(FAIL=acc(lite) 不重叠硬断言, 详见 §3)

# ② merge-base 实测
git merge-base HEAD origin/main
# 81c50965b35e93b3ed6ffae50918580652160654

# ③ 文本宽/间距探针(已清理, 本报告含实测值)
# DOM rect width == 页面实际字体 measureText == 57.6px; 默认 12px sans-serif == 53.4px(低估)
# acc 全列相邻间距 55.3~55.4px / risk 60px
```

## 7. 落档信息

- 实施 agent 产出, 改动全在 `static-site/app.js`, 验收脚本 `scripts/playwright-accept/verify_overfit_xaxis_lastlabel.mjs` 入库。
- feat 分支 `worktree-agent-a25e29c4db5dba109`, commit 见 git log, 已 push(只 push feat, 未动 main, 未 bump)。
- 涉及 #147(pending-index)。merge + push main 由主控走 main-merge.sh 统一入口。
- 硬断言 FAIL 待主控拍板(§3 三选项 A/B/C), 拍板后如需调脚本口径或 cfg 再派跟进。
