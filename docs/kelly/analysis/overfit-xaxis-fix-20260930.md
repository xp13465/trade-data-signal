# 过拟合卡 x 轴末点标签修复实施记录(#147, 2026-09-30, 右锚定采样 + 按实际刻度串量宽 step)

> 实施 agent 产出。前置调研: `docs/kelly/analysis/overfit-xaxis-label-20260930.md`。
> 现象: #139 修复后准确率图数据末点已到 20260928, 但 x 轴最右刻度标签停在 20260922 —— 用户按标签读图会误以为没修好(L42 同款)。
> 本文档: 改动点 / 验收证据(五窗口 61/61, 含「不重叠」硬断言)/ 实测表现 / 复现段。
> **方案演进(主控指示)**: 第一版「补末点标签」被主控否决(末两标签固有重叠约 16.5px) → **右锚定采样**(末点必为采样点, 相邻间距=常规步进, 末两 36.9→55.4px, 固有拥挤消除) → 主控再指示**照 2026-09-05 先例按实际刻度串量宽传 cfg.xStep**(8 位日期真实宽 57.6 > 引擎按 "MM-DD" 估的 55.4, 差 2.2px 盒级重叠根因), 两图各自量宽重算 step, **五窗口硬断言全 PASS**。

## 0. 结论摘要

| # | 问题 | 结论 |
|---|---|---|
| 1 | 修了什么 | ① `_lwSVG` 引擎 `forceLastLabel` 开关(**默认 false/undefined**, 全站其他 lite 图行为零变化, §23.7 冻结), 开启时右锚定采样(起点=`_i1-floor((_i1-_i0)/_xStep)*_xStep`, 末点必为采样点) ② 只给过拟合两图 cfg 各开 `forceLastLabel: true` + **各传 `xStep`**(按本图实际刻度串 8 位日期量宽重算, 公式同 2026-09-05 净资产图先例: `floor(labelW*1.3/unitW)+1`) ③ echarts fallback 两处 xAxis `axisLabel: { showMaxLabel: true }`(**保留不动**)。**未碰** #139/#144 的 `_overfitAccSeries` 数据层逻辑、未动 `_etfXStep` |
| 2 | 修好没有 | **修好**。Playwright 无痕验收 **61/61 PASS**(§2): 五窗口(roll 10/15/30/60/100)× 两图 × lite 路径, 全部「最右标签==数据末点 20260928 + 相邻标签矩形不相交」; fallback 双图 showMaxLabel 生效、dataLast==20260928; 回归零差异 |
| 3 | 不重叠硬断言 | **五窗口全 PASS**(§2): acc 最差对 20260825->20260911 间距 73.8px 需≥57.6px, risk 最差对 20260914->20260928 间距 70px 需≥57.6px。**2.2px 根因已除**: xStep 按 8 位日期量宽(12px sans-serif "20260928"≈53.4, ×1.3≈69.4)重算 → 常规间距由 55.4 提至 70~73.8px, ≥ 页面实际字体渲染宽 57.6px |
| 4 | 末两标签实测 | acc/risk 全部窗口末两间距 70~73.8px ≥ 文本宽 57.6px, 无重叠 |
| 5 | 最左端标签 | 右锚定后 acc 最左标签由 20260323(x=81.5) 变为 20260427(x=85.4), 左端少一格并右移——可接受(轴起点不必有标签, 对齐 echarts showMaxLabel 语义), 已实测留档 |
| 6 | merge-base | `git merge-base HEAD origin/main` = **81c50965b35e93b3ed6ffae50918580652160654**(与 origin/main 持平, base 新鲜) |

## 1. 改动点(全在 `static-site/app.js`, diff 可反查)

| # | 位置 | 改动 |
|---|---|---|
| 1 | `_lwSVG` x 标签循环(app.js:18284 附近) | `forceLastLabel` 开启时右锚定采样: `_lbl0 = _i1 - floor((_i1-_i0)/_xStep)*_xStep`(= `_i0 + ((_i1-_i0)%_xStep)`, 恒落 `[_i0, _i0+_xStep)`), `for (let i = _lbl0; i <= _i1; i += _xStep)` → **末点 _i1 必为采样点且有标签**, 相邻间距恒为 `_xStep×unitW`。默认关/undefined = 走原左采样逻辑, 引擎行为零变化 |
| 2 | `_renderOverfitAcc` cfg(app.js:1822 附近) | `forceLastLabel: true` + **`xStep`**(IIFE: canvas measureText("20260928", 12px sans-serif)×1.3 → step=`floor(max(lw*1.3,7)/((容器实测宽-pl40-pr16)/n))+1`) |
| 3 | `_renderOverfitAcc` echarts fallback xAxis(app.js:1852 附近) | `axisLabel: { showMaxLabel: true }`(**保留不动**) |
| 4 | `_renderOverfitRisk` cfg(app.js:1929 附近) | `forceLastLabel: true` + **`xStep`**(同公式, 用 `_overfitRiskEl` 容器实测宽) |
| 5 | `_renderOverfitRisk` echarts fallback xAxis(app.js:1957 附近) | `axisLabel: { showMaxLabel: true }`(**保留不动**) |

- **xStep 量宽先例(照抄 2026-09-05)**: 净资产图 app.js:5830-5838 已有同款(注释「_etfXStep 按 "MM-DD" 量宽, 跨年带年刻度(10字符)宽一倍会连粘 → 按本图实际刻度串量宽重算 step(公式同 _etfXStep: floor(labelW*1.3/unitW)+1)」。⚠️ unitW 用**容器实测宽**估算(_lwBind 按 getBoundingClientRect 重设 viewBox), 不能写死 640)。过拟合图正是「8 位日期标签比 _etfXStep 假设的 "MM-DD" 宽」的场景, 当年漏接先例 = 2.2px 盒级重叠根因。
- 范围红线核对: **未动** `_overfitAccSeries`(#139/#144 数据层)、未动 `_etfXStep`(全站其他 lite 图量宽口径零影响)、未动任何其他图 cfg、未改 static-site/data、未 bump 版本串(机制 C)。

## 2. 验收证据(Playwright 无痕, 线上数据, 五窗口 × 双路径)

验收脚本: `scripts/playwright-accept/verify_overfit_xaxis_lastlabel.mjs`(入库)。**结果: PASS=61 FAIL=0**。

### ① lite 路径(改后 app.js)· 五窗口(roll 10/15/30/60/100)逐个
每窗口两图各 6 项, 共 30 PASS:
- `forceLastLabel` 均开启(PASS)
- **最右标签 == 数据末点 20260928**(PASS, acc/risk 各窗口)
- **不重叠硬断言: 全部相邻标签矩形不相交**(PASS, 最差对见下)
- 全程零 pageerror(PASS)

| 窗口(roll) | acc xLabels | acc 实际标签数 | acc xStep | acc 最差对(间距/需≥) | risk xLabels | risk 实际标签数 | risk xStep | risk 最差对(间距/需≥) |
|---|---|---|---|---|---|---|---|---|
| 10 | 65 | 9 | 8 | 20260825->20260911 73.8/57.6 | 60 | 9 | 7 | 20260914->20260928 70.0/57.6 |
| 15 | 65 | 9 | 8 | 同上 | 60 | 9 | 7 | 同上 |
| 30 | 65 | 9 | 8 | 同上 | 60 | 9 | 7 | 同上 |
| 60 | 65 | 9 | 8 | 同上 | 60 | 9 | 7 | 同上 |
| 100 | 65 | 9 | 8 | 同上 | 60 | 9 | 7 | 同上 |

> 注: 五窗口 xLabels 数不变(65/60)是**设计如此**——roll 是统计口径(数据源换 key), 显示范围 win=60 固定截取最近 60 交易日(`_overfitAccSeries` L1766 `slice(-w)`)。五档 roll 切换验证了两图数据源变化后标签布局仍全 PASS。

- hover 末点 tooltip 同日(默认 60 窗口): acc tip=`09-28实盘实际: 31.0%`, risk tip=`20260928`(PASS)
- 截图: `/tmp/xaxis147-acc-lite.png` / `/tmp/xaxis147-risk-lite.png`

### ② 回归(基线 = main 版 app.js `/tmp/app_main_baseline.js`)
- lite 图数量基线=改后(20 张非过拟合图), **每张日期标签(文本+位置 svgX)与基线逐个一致**(PASS)——证明 xStep 只加在过拟合两图 cfg、其他图量宽口径零变化
- 两图曲线数据末点 + seriesLen 基线=改后(PASS)——证明只改标签, 曲线/数据未被碰
- 基线/改后路径均零 pageerror(PASS)

### ③ fallback 路径(⚡ 关 → echarts, 改后 app.js + `sitecfg:charts.lightweight=false`)
- acc/risk 均走 echarts canvas(PASS), `showMaxLabel=true` 生效(PASS), `dataLast==20260928`(PASS)
- fallback 零 pageerror(PASS)
- 截图: `/tmp/xaxis147-acc-fallback.png` / `/tmp/xaxis147-risk-fallback.png`

## 3. 不重叠根因与修复(2.2px 已除)

- **根因**: `_etfXStep`(L25461)按 `"MM-DD"` 5字符量宽×1.3≈43px 算步进, 过拟合图标签是 **8 位日期 `YYYYMMDD`**, 页面实际字体(`-apple-system, PingFang SC...`)渲染宽 **57.6px**(DOM `getBoundingClientRect().width` == 页面字体 measureText, 均 57.6; 默认 `12px sans-serif` 是 53.4 低估) → 常规间距 55.4px < 57.6px, 2.2px 盒级重叠。基线/全站其他图同此间距, 引擎既有口径。
- **修复**: 照 2026-09-05 净资产图先例, 过拟合两图 cfg 各自量本图实际刻度串(8 位日期)重算 xStep: `measureText("20260928", "12px sans-serif")≈53.4 → ×1.3≈69.4 → step = floor(69.4/((容器实测宽-pl40-pr16)/n))+1`。**间距由 55.4 提至 70~73.8px ≥ 57.6px, 全窗口不重叠**。
- **xStep 随窗口自适应**: step 由 `n`(本窗口 xLabels 长度)和容器实测宽共同决定, 每次渲染 cfg 重建时 IIFE 重求值, 窗口变化自动换步进。
- **容器实测宽**: 用 `_overfitAccEl/_overfitRiskEl.getBoundingClientRect().width || offsetWidth || 640`(与 _lwBind 重设 viewBox 同源), 兜底 640。

## 4. 右锚定实测表现(最左端偏移/末两间距)

| 图 | 最左标签 | 最右标签(=末点) | 末两间距 | 全列相邻间距 |
|---|---|---|---|---|
| 准确率图(窗口60) | 20260427(x=85.4, 基线最左 20260323 x=81.5 → 右移 3.9px、左端少一格) | 20260928(x=635.4) | **73.8px** | 70~73.8px |
| 风险分图(窗口60) | 同基线偏移 | 20260928(x=635) | **70.0px** | 70px |

- 最左端偏移/少一格 = 右锚定预期行为(起点 = `_i0 + ((_i1-_i0)%_xStep)`, 首个采样点向右缩), 属可接受(轴起点不必有标签, 对齐 echarts showMaxLabel 语义)。
- 文本真实渲染宽(DOM rect == 页面实际字体 measureText): 57.6px; 默认 `12px sans-serif` 为 53.4px(低估)。

## 5. 诚实标注

- ① 第一版「补末点标签」(commit c2e85101c)末两标签重叠约 16.5px(间距 36.9 vs 文本宽 53.4)被主控否决 → 右锚定恢复常规步进 → 再按先例量宽 xStep 全窗口不重叠。方案演进如实记录, 最终态=右锚定 + 量宽 xStep。
- ② 截图已留档但**本会话模型不支持读图**(§13), 视觉判定基于 svg 文本 x 坐标 + DOM rect / measureText 数值证据, 非肉眼截图。
- ③ 数据层证据用线上 overfit_monitor.json(09-29 21:40 产物), 未用本地 9-11 旧产物(调研 §1.3 已指出其结构不符)。
- ④ 硬断言口径 = 主控指定「DOM getBoundingClientRect 实测相邻标签矩形不相交(保守: 中心距 ≥ 文本实测宽)」, 未降标准、未为凑 PASS 改口径。

## 6. 复现段(命令 + 实测值)

```bash
# ① 验收脚本(在 worktree 内, playwright-accept node_modules 已有)
cd /Users/linhuichen/code/trade/.claude/worktrees/agent-a25e29c4db5dba109/scripts/playwright-accept
# 前置: /tmp/overfit_online.json /tmp/overfit_ext_online.json(线上 09-29 21:40 产物), /tmp/app_main_baseline.js(main 未改版)
node verify_overfit_xaxis_lastlabel.mjs
# 输出: 结果: PASS=61 FAIL=0

# ② merge-base 实测
git merge-base HEAD origin/main
# 81c50965b35e93b3ed6ffae50918580652160654

# ③ 文本宽实测(页面实际字体 measureText / DOM rect)
# 20260729/20260928 = 57.6px; 默认 12px sans-serif = 53.4px(低估)
# acc 全列相邻间距 70~73.8px / risk 70px(右锚定 + xStep 量宽后)
```

## 7. 落档信息

- 实施 agent 产出, 改动全在 `static-site/app.js`(xStep 两图 cfg + 右锚定引擎), 验收脚本 `scripts/playwright-accept/verify_overfit_xaxis_lastlabel.mjs` 入库。
- feat 分支 `worktree-agent-a25e29c4db5dba109`, commit 见 git log, 已 push(只 push feat, 未动 main, 未 bump)。
- 涉及 #147(pending-index)。merge + push main 由主控走 main-merge.sh 统一入口。
