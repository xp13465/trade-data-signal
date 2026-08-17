# 首页三张分段色图(SVG 轻量版)变色分界点校准(a322)

> 2026-08-17 | implementer | 修复首页恐贪/情绪分/跨市场三张 0-100 温度计图变色分界与 echarts 不一致
> 前置:docs/lite-svg-corner-vertex-a320-final.md(尖角+分段色根治,渐变单path版)

## 0. 一句话结论

**三张 0-100 温度计图(SVG 轻量版)的值域原先走数据自适应 `_lwValueExtent`(nice extent),而非固定 0-100——恐贪得 [20,90]、跨市场得 [30,100]。值域被数据压缩/拉伸,渐变与曲线虽共用同一 `_py` 像素映射(彼此逐像素一致),但用户在图上看到的颜色切点位置偏离「0-100 温度计」直觉:黄红分界读成 ~75(预期 80)、蓝灰分界贴底读成 ~10(预期 20)。修复 = `_lwLineCard`(首页三张)与 `_kpiLiteCfg`(KPI 弹窗 9 张 sentiment)+ 各自 echarts fallback 统一固定 min:0 / max:100,颜色切点精确落在 20/40/60/80(恐贪 25/40/60/75),与既有过拟合风险分图/准确率图(早已固定 0-100)对齐。**

## 1. 根因

- 首页三张 `_lwLineCard`(app.js L13476)liteCfg `ys:[{splitLine:true}]` 未设 min/max → `_lwValueExtent(vals,undefined,false,undefined,undefined)` 走数据自适应分支:
  - 恐贪数据 min=20.62 max=83.87 → nice extent **yMin=20, yMax=90**
  - 情绪分数据 min=6.44 max=90.18 → nice extent **yMin=0, yMax=100**(恰好,无偏移)
  - 跨市场数据 min=32.36 max=95.97 → nice extent **yMin=30, yMax=100**
- 值域非固定 0-100 → 渐变 y1/y2 像素区间与 0-100 温度计刻度错位。渐变与曲线虽同 `_py` 映射(差 0.000px),但用户读图(0-100 直觉)时切点位置偏离预期:
  - 恐贪黄红分界(值75): 在 [20,90] 值域下图高 21.4%(0-100 直觉 ~78);蓝灰分界(值25): 图高 92.9%(贴底,0-100 直觉 ~10)
  - 跨市场黄红分界(值80): 在 [30,100] 值域下图高 28.6%(0-100 直觉 ~71)
- 既有同类图已固定 0-100(过拟合风险分 L1774、准确率 L1681),**首页三张是漏网** → 与 echarts/同类图不一致。

## 2. 修复

1. `_lwLineCard`(app.js):liteCfg `ys` 加 `min:0, max:100`(L13477);echarts fallback `yAxis` 加 `min:0, max:100`(L13492)。
2. `_loadKpiHistory` sentiment 分支返回加 `yRange:[0,100]`(L6188);`_kpiLiteCfg` ys 与 echarts yAxis 读 `result.yRange`(L13437/L6454)。

## 3. 自验(线上真实数据 overview.json 20260817)

脚本 `docs/scripts/lite-svg-grad-calibration.py` 输出:三图固定 0-100 后,每阈值 `渐变 stop 像素 == 曲线同值像素(差 0.000px)`,`实际最近 stop 值` 与阈值偏差仅 0.12(渐变采样粒度 gspan/800=0.125)。

| 图 | 值域 | 阈值 | 渐变stop像素=曲线像素 | 实际切点值 | 偏差 |
|---|---|---|---|---|---|
| 恐贪 | [0,100] | 25/40/60/75 | 200.75/167.60/123.40/90.25 | 25.12/40.12/60.12/75.12 | 0.12 |
| 情绪分 | [0,100] | 20/40/60/80 | 211.80/167.60/123.40/79.20 | 20.12/40.12/60.12/80.12 | 0.12 |
| 跨市场 | [0,100] | 20/40/60/80 | 211.80/167.60/123.40/79.20 | 20.12/40.12/60.12/80.12 | 0.12 |

图区:W=900,H=300,PL=55,PR=20,PT=35,PB=44,ih=221;渐变 y1=35(顶/100) y2=256(底/0)。用户读 y 轴刻度(0..100)即精确读到 20/40/60/80。

## 4. 举一反三覆盖(§23.3)

- 首页三张(`_lwLineCard`)✓
- KPI 详情弹窗 9 张 sentiment 情绪分(`_kpiLiteCfg`+echarts,`result.yRange`)✓
- 信号弹窗 `_lwSignalLiteCfg`(L4687)= 信号值非温度计,保持自适应 ✓
- 分时图(L8272)/家数(L11464)/涨跌比(L11641,11778)= 非 0-100 温度计,保持自适应 ✓
- 过拟合风险分(L1774)/准确率(L1681)= 已固定 0-100,无需改 ✓

## 5. 诚实标注

- 渐变切点偏差 0.12 值来自采样检测(`_gstep=gspan/800`),人眼不可见(<0.2 值),非算法错误;如需<0.01 可加密采样,但无必要。
- 本次为纯展示层值域修复,不动色函数阈值/评分/权重,不触发 §21 算法公示(阈值语义未变)。

## 6. 复现

- 脚本:`docs/scripts/lite-svg-grad-calibration.py`
- 输入依赖:`/tmp/overview_online.json` = 线上 `https://ss.fx8.store/data/overview.json`(20260817)
- 重跑命令:
  ```
  curl -s https://ss.fx8.store/data/overview.json -o /tmp/overview_online.json
  python3 docs/scripts/lite-svg-grad-calibration.py
  ```
- 数据截止:2026-08-17
- 关键口径:固定值域 min:0 max:100;渐变采样 `_gstep=gspan/800` 阈值双 stop 硬切;像素 `_py=PT+ih-((v-yMin)/(yMax-yMin))*ih`
