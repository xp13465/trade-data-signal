# 过拟合卡 x 轴末点标签修复实施记录(#147, 2026-09-30)

> 实施 agent 产出。前置调研: `docs/kelly/analysis/overfit-xaxis-label-20260930.md`(方案 A 推荐)。
> 现象: #139 修复后准确率图数据末点已到 20260928, 但 x 轴最右刻度标签停在 20260922 —— 用户按标签读图会误以为没修好(L42 同款)。
> 本文档: 改动点 / 验收证据(双路径 34/34)/ 视觉重叠不确定项①如实标注 / 复现段。

## 0. 结论摘要

| # | 问题 | 结论 |
|---|---|---|
| 1 | 修了什么 | 按调研方案 A 落地: ① 自研 `_lwSVG` 引擎新增 `forceLastLabel` 开关(**默认 false/undefined**, 全站其他 lite 图行为零变化, §23.7 冻结) ② 只给过拟合两图(准确率/风险分)cfg 各开 `forceLastLabel: true` ③ echarts fallback 两处 xAxis 加 `axisLabel: { showMaxLabel: true }`。**未碰** #139/#144 的 `_overfitAccSeries` 数据层逻辑 |
| 2 | 修好没有 | **修好**。Playwright 无痕验收 34/34 PASS(见 §2): lite 两图最右标签均 == 数据末点 **20260928**, hover 末点 tooltip 同日; fallback 双图 `showMaxLabel=true` 生效、dataLast==20260928 |
| 3 | 回归 | 开关默认关 → 全站其他 20 张 lite 图日期标签与基线(main 未改版)逐个一致, 两图曲线数据末点/seriesLen 未被改动, 双路径零 pageerror |
| 4 | 视觉重叠(不确定项①) | **如实上报, 未自行拍板**: 末点补出标签后, 准确率图末两标签间距 36.9px < 文本宽 53.4px → **明确重叠约 16.5px**; 风险分图末两标签间距 50px < 53.4px → **轻微临界**。此即调研报告 §4 方案 A 风险①(echarts showMaxLabel 同款行为)的实测确认。**默认行为(开关关)无任何变化, 是否进一步调整末段密度由用户拍板** |
| 5 | merge-base | `git merge-base HEAD origin/main` = **81c50965b35e93b3ed6ffae50918580652160654**(= 与 origin/main 持平, base 新鲜, 开工前已 merge origin/main) |

## 1. 改动点(5 处, 全在 `static-site/app.js`, diff 可反查)

| # | 位置 | 改动 |
|---|---|---|
| 1 | `_lwSVG`(app.js:18248 附近, x 标签循环后) | 新增补画逻辑: `if (cfg.forceLastLabel && _xStep > 0 && (_i1 - _i0) % _xStep !== 0)` 时, 在 `_px(_i1)` 补画 `_xFmt(cfg.xLabels[_i1])` 同样式标签。开关默认关 = 引擎行为零变化 |
| 2 | `_renderOverfitAcc` cfg(app.js:1822 附近) | 加 `forceLastLabel: true` |
| 3 | `_renderOverfitAcc` echarts fallback xAxis(app.js:1852 附近) | 加 `axisLabel: { showMaxLabel: true }` |
| 4 | `_renderOverfitRisk` cfg(app.js:1931 附近) | 加 `forceLastLabel: true` |
| 5 | `_renderOverfitRisk` echarts fallback xAxis(app.js:1957 附近) | 加 `axisLabel: { showMaxLabel: true }` |

- 语义: 对齐 echarts 官方 `AxisLabelBaseOption.showMaxLabel`(调研 §2.2 已核实官方 npm types)。
- 范围红线核对: **未动** `_overfitAccSeries`(#139/#144 已上线的数据层并集驱动)、未动 `_etfXStep`、未动任何其他图 cfg、未改 static-site/data、未 bump 版本串(机制 C)。

## 2. 验收证据(Playwright 无痕, 线上数据)

验收脚本: `scripts/playwright-accept/verify_overfit_xaxis_lastlabel.mjs`(**入库, 34/34 PASS**)。

### ① lite 路径(改后 app.js)
- acc/risk 两图 `forceLastLabel` 均开启(PASS)
- acc 数据末点 == 最右标签 == **20260928**(PASS); risk 同(PASS)
- hover 两图末点 tooltip 日期同日 09-28(PASS, risk 末点 risk_score 为 null 时 tipFn 返回原始 8 位日期, 脚本兼容两种格式)
- lite 路径零 pageerror(PASS)
- 截图: `/tmp/xaxis147-acc-lite.png`(656×181)/ `/tmp/xaxis147-risk-lite.png`(656×161)

### ② 回归(基线 = main 版 app.js `/tmp/app_main_baseline.js`)
- lite 图数量基线=改后(20 张非过拟合图), **每张日期标签与基线逐个一致**(PASS)
- 两图曲线数据末点 + seriesLen 基线=改后(PASS)——证明只加了标签, 曲线/数据未被碰
- 基线路径零 pageerror(PASS)

### ③ fallback 路径(⚡ 关 → echarts, 改后 app.js + `sitecfg:charts.lightweight=false`)
- acc/risk 均走 echarts canvas(PASS), `showMaxLabel=true` 生效(PASS), `dataLast==20260928`(PASS)
- fallback 零 pageerror(PASS)
- 截图: `/tmp/xaxis147-acc-fallback.png` / `/tmp/xaxis147-risk-fallback.png`

## 3. 视觉重叠(不确定项①)实测与如实上报

**结论: 末点补出标签后末两标签拥挤, 准确率图明确重叠, 风险分图临界。已如实上报, 未自行拍板调整方案。**

量化证据(Playwright 读 svg 文本 x 属性 + canvas measureText 12px 实测):

| 图 | 末两标签(文本, x) | 间距 | 文本宽(12px 8 位数字) | 判定 |
|---|---|---|---|---|
| 准确率图 | 20260917(x=598.5) → 20260928(x=635.4) | **36.9px** | **53.4px** | **重叠约 16.5px**(中心距 < 文本宽) |
| 风险分图 | 末两标签 | **50px** | **53.4px** | 轻微重叠/临界(差 3.4px) |

- 根因: 末点补出后, 末点与前一采样标签的间距 = `(_i1-_i0) % _xStep × unitW` = 本场景 4×9.23 ≈ 36.9px, 小于常规步进间距(55.4px)与文本宽度。
- 这与调研报告 §4 方案 A 风险①(「余数=1 时可能轻微拥挤」)的预期方向一致——实测是余数=4 场景, 拥挤更明显。
- 权衡: ① echarts 官方 `showMaxLabel` 本身就是同款行为(末点硬出, 不保证不挤); ② 若不出末点标签则回到「标签落后末点」的原始 bug; ③ 默认开关关, 全站其他图不受影响。**是否进一步优化末段标签密度(如末点标签改短格式/让步进吸附), 属新改动, 按 §23.7 需用户拍板, 不在本次范围**。

## 4. 复现段(命令 + 实测值)

```bash
# ① 验收脚本(在 worktree 内, playwright-accept node_modules 已有)
cd /Users/linhuichen/code/trade/.claude/worktrees/agent-a25e29c4db5dba109/scripts/playwright-accept
# 前置: /tmp/overfit_online.json /tmp/overfit_ext_online.json(线上 09-29 21:40 产物), /tmp/app_main_baseline.js(main 未改版)
node verify_overfit_xaxis_lastlabel.mjs
# 输出: 结果: PASS=34 FAIL=0

# ② merge-base 实测
git merge-base HEAD origin/main
# 81c50965b35e93b3ed6ffae50918580652160654

# ③ 视觉重叠量化(改动后 lite 图 svg 文本 x 属性 + 12px measureText)
# acc 末两标签 20260917(x=598.5) / 20260928(x=635.4), 间距 36.9px, 文本宽 53.4px → 重叠
```

## 5. 诚实标注

- ① 末点标签与前采样标签重叠(acc 明确 16.5px / risk 临界 3.4px)是**本轮引入的真实视觉表现**, 已如实上报, 未自行拍板; 默认关不影响全站。
- ② 截图已留档但**本会话模型不支持读图**(§13), 视觉判定基于 svg 文本 x 坐标 + measureText 数值证据, 非肉眼截图。
- ③ 数据层证据用线上 overfit_monitor.json(09-29 21:40 产物), 未用本地 9-11 旧产物(调研 §1.3 已指出其结构不符)。

## 6. 落档信息

- 实施 agent 产出, 改动全在 `static-site/app.js`(5 处 diff), 验收脚本 `scripts/playwright-accept/verify_overfit_xaxis_lastlabel.mjs` 入库。
- feat 分支 `worktree-agent-a25e29c4db5dba109`, commit 见 git log, 已 push(只 push feat, 未动 main, 未 bump)。
- 涉及 #147(pending-index)。merge + push main 由主控走 main-merge.sh 统一入口。
