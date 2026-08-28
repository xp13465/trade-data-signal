# 情绪分弹窗走势图冰点无 pin 根因(2026-08-20)

## 结论(一句话)

**前端漏接,非数据缺标记**:openSignalChartModal 的冰点 pin 追加逻辑 `if (isFreeze)`(static-site/app.js L6311-6314)只在「点击冰点 cell(`signal==="freeze"`)」入口生效;从**买卖点信号 cell**(情绪日历信号列 / 市场温度情绪分买卖点列表)点开情绪分弹窗时 `isFreeze=false`,sigs 只含该情绪分的买卖点信号,不追加冰点标注 → 弹窗走势图 3m 窗口内明明有冰点日(value≤20)却一个蓝色 pin 都没有。#20(acfae398a)只修了「点冰点 cell」入口,同一条 `if (isFreeze)` 门控没覆盖非冰点入口。

## 证据

### 1. 冰点 pin 追加只在 isFreeze(点冰点 cell)时执行 —— 根因点
- `static-site/app.js L6310-6314`:
  ```js
  // 冰点模式：在原买卖点标注基础上追加冰点标注（≤20 蓝色），走势图同时显示买卖点+冰点
  if (isFreeze) {
    const freezePts = chartData.filter((d) => d.value != null && d.value <= 20).map((d) => ({ date: d.date, signal: "freeze", value: d.value }));
    sigs = [...sigs, ...freezePts];
  }
  ```
- `isFreeze` 定义 L6238:`const isFreeze = signal === "freeze";`
- s.* 分支(L6271-6287):`sigs = r.signals[key] || []` 只取买卖点信号;`chartData = data.map(d=>({date, value}))` 丢弃 is_freeze。

### 2. 从买卖点信号入口点开弹窗 → isFreeze=false → 无冰点 pin(两处入口)
- 首页近90日情绪日历**信号格** `static-site/app.js L3099-3107`:cell 的 `data-sig="${s.signal}"`(buy/buy_aux/sell),点击走 L12036 → `openSignalChartModal(idx, "sell"/"buy"...)` → isFreeze=false。
- 市场温度 tab **情绪分买卖点信号列表** `static-site/app.js L18590-18606`:同样 `data-sig="${s.signal}"`,点击 L18606 → isFreeze=false。
- 对照组(已修好的入口):情绪日历**冰点格** L3094-3097 `data-sig="freeze"` → isFreeze=true → 追加 freezePts(#20 已修)。

### 3. 数据源有 is_freeze 标记,前端却不用
- `static-site/data/sentiment-all.json` sentiment_* 元素:含 `is_freeze`(0/1)+ `is_overheat` + `components`。抽样 `sentiment_sz50`:is_freeze=1 共 166 条 == value≤20 共 166 条(当前一致)。
- 但前端 L6278 `chartData = data.map(d=>({date:d.date, value:d.value}))` **丢弃 is_freeze**,冰点判定用 `value<=20` 前端阈值重算(L6312)。当前两口径一致,未来数据层口径若变化会漂移(数据层单一事实源未被前端消费)。

### 4. 模拟复现(数据说话)
对 sentiment_kc50(3m 窗口内 4 个冰点日:20260717=15.82/20260728=18.98/20260730=14.2/20260803=16.13):
- 入口A 点冰点 cell:freezePts 追加 4 条 → markData 92 条,蓝色 #42a5f5 pin **4 个**,label "冰点16/冰点14/冰点19/冰点16"。→ 正常(#20 已修)。
- 入口B 点买卖点 sell cell:sigs 88 条(仅买卖点)→ markData 88 条,蓝色 #42a5f5 pin **0 个**。→ **冰点日无 pin,复现用户所报**。

### 5. #24 情绪叠指数不背锅
- `8bc405caa`(#24)只给 valueChartWithSignals/_lwSignalLiteCfg 加第 10 参 indexOverlay(双轴叠指数),commit 注释明确「区域隔离:未碰 renderOverview本体/indexChart/_homeNews(freeze蓝等)」。
- 弹窗调用 `static-site/app.js L6405`:第 10 参=chartOverlay 位置正确(`150249e06` 已补第 9 参 undefined 占位,keyOverlay 落第 10 参)。
- #24 未动 freezePts/isFreeze/markPoint 处理,不影响冰点 pin;它只是也没修「非冰点入口无 pin」。

### 6. 线上已部署 #20,但只覆盖入口A
- `acfae398a fix(app.js): 冰点弹窗 pin 错渲绿修蓝+带冰点数值` 在 main(d6804a1f8 bump 前 merge),改 3 行:signalColor + freeze 蓝、signalLabel + 冰点数值、freezePts 追加带 value。
- 线上 `https://ss.fx8.store/app.min.js` grep `#42a5f5` 命中 3 处(已部署)。但 freezePts 追加逻辑仍是 `if (isFreeze)` 门控 → 非冰点入口不生效。

## 同类排查(§23.2③/§23.3)

| 展示位 | 代码位置 | 是否恒显冰点 pin | 备注 |
|---|---|---|---|
| 情绪分弹窗·冰点cell入口(A) | app.js L6311-6314 + L3094-3097 | ✅ 有(#20 已修) | 4 个冰点蓝 pin |
| 情绪分弹窗·买卖点信号入口(B) | app.js L6311 + L3106 / L18596 | ❌ 无 | **用户所报主 bug** |
| 市场温度 tab 6宽基卡(B卡) | app.js L18364-18405 valueChartWithSignals | ❌ 无 | 只传买卖点 sig + markLine y=20 阈值线,冰点日无 pin |
| 市场温度 tab 恐贪卡 | app.js L18251-18263 | ❌ 无 | 只 markLine y=25/75 |
| 市场温度 tab A股综合情绪分卡 | app.js L18325-18337 | ❌ 无 | 只 markLine y=20/80 |
| 市场温度 tab 跨市场卡 | app.js L18412 | ❌ 无 | 只 markLine |
| 首页 A股综合情绪分折线 | app.js L11987-12005 _lwLineCard | ❌ 无 | 只 markLine y=20/80 |
| KPI 详情弹窗(C) | app.js L6707-6843 openKpiDetailModal | ❌ 无 | KPI 不用信号 pin 是设计(app.js L25890 注释),非本次 bug |
| g.* 全球 extras 弹窗 | app.js L6257-6270 | 不适用 | 值域非 0-100(如 gold 100-1249),≤20 不命中,无冰点入口 |

## 修复方向(前端漏接为主,数据层对齐为辅)

1. **主修(openSignalChartModal)**:冰点标注不应依赖入口信号 `isFreeze`,应对 0-100 情绪分类走势图(s.* 分支)恒显——把 `if (isFreeze)` 改为「isFreeze 或 indexId 属 s.* 情绪分类」时,均把 chartData 中冰点日追加为 freeze 信号 pin。修复后:无论从冰点 cell 还是买卖点信号 cell 点进情绪分弹窗,冰点日恒有蓝色 pin。
2. **数据层对齐(防漂移)**:L6278 chartData 映射保留 `is_freeze` 字段,冰点判定改读 `is_freeze===1`(数据层单一事实源,与恐贪/情绪分 visualMap ≤20 口径由数据层统一),避免前端阈值重算与数据层口径漂移。当前 value<=20==is_freeze(166==166),改读数据标记无行为变化,纯口径对齐。
3. **同类覆盖(§23.3,产品决策项)**:市场温度 tab 6宽基卡/恐贪/A股综合/跨市场卡若也要冰点恒显 pin,与主修同规则(valueChartWithSignals 内统一处理或调用方传 freezePts);KPI 详情弹窗(C)KPI 不用信号 pin 是既有设计,非本次 bug,是否加冰点标注由产品拍板。
4. 修后自验:①点情绪日历冰点 cell 仍有 4 蓝 pin(不回归 #20)②点信号 sell cell 弹窗 3m 窗口冰点日现蓝色 pin(新修)③市场温度情绪分买卖点列表点 sell 弹窗同样有 ④g.*/常规指数弹窗不受影响。

## 复现

- **脚本**:本报告无独立脚本,复现=Node 模拟 + 浏览器手动。模拟脚本逻辑=复刻 app.js `_buildSignalMarkData`(L447-508)+ `_lwSignalMarkPoints`(L4884-4910)+ openSignalChartModal s.* 分支(chartData 映射 L6278 + isFreeze 追加 L6311-6314),输入 sentiment_kc50 数据。
- **数据依赖**:`static-site/data/sentiment-all.json`(6 宽基 sentiment_* 含 is_freeze)+ `static-site/data/overview.json`(sentiment_calendar 冰点 score_id="sentiment_kc50" 格式)。
- **重跑命令**(模拟,node ≥14):
  ```bash
  node -e '
  const fs=require("fs");const d=JSON.parse(fs.readFileSync("static-site/data/sentiment-all.json","utf8"));
  const key="sentiment_kc50",arr=d[key],dates=arr.map(x=>x.date);
  const chartData=arr.filter(x=>x.date>=dates[dates.length-64]).map(x=>({date:x.date,value:x.value}));
  const sigs=d.signals[key]||[];
  // 入口A: isFreeze=true
  let a=sigs.slice();const fp=chartData.filter(x=>x.value!=null&&x.value<=20).map(x=>({date:x.date,signal:"freeze",value:x.value}));a=[...a,...fp];
  // 入口B: isFreeze=false
  console.log("入口A freeze pin 数:",a.filter(s=>s.signal==="freeze").length,"| 入口B freeze pin 数:",sigs.filter(s=>s.signal==="freeze").length);
  console.log("3m窗口冰点日:",chartData.filter(x=>x.value<=20).map(x=>x.date+"="+x.value).join(", "));
  '
  ```
- **数据截止**:2026-08-20(overview/sentiment-all 数据末日 20260819)。
- **关键口径**:冰点 = 情绪分 value≤20(前端阈值,当前 == 数据层 is_freeze=1);3m 窗口 = _signalModalCutoff 按自然月回推 3 个月。
