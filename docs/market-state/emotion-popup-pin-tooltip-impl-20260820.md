# 情绪分弹窗冰点 pin 恒显 + hover tooltip 增强 实施报告(#26, 2026-08-20)

> 任务 #26。根因见 `docs/market-state/sentiment-popup-freeze-pin-rootcause-20260820.md`(主控定位)。
> 用户报:"情绪分点击的弹窗走势图里怎么没有冰点的 pin" + 情绪分/冰点弹窗 tooltip 要像指数曲线那样带标题。

## 根因一句话
- **需求 A**: 冰点 pin 追加逻辑 `if (isFreeze)`(仅入口 signal==="freeze" 时执行)只在**点冰点 cell**时追加冰点蓝 pin。从**买卖点信号 cell**(data-sig=buy/sell 点进)打开的情绪分弹窗, `isFreeze=false` → 冰点日不追加蓝 pin。数据层 sentiment_* 元素**已含 is_freeze=1 标记冰点**(线上 sentiment-all.json 实测 1197 个元素 is_freeze=1),但前端 L6294 chartData 只保留 value 丢弃 is_freeze。
- **需求 B**: 情绪分弹窗/冰点弹窗走势图 tooltip 只显示单数字(hover 出 "15.82"),没像数值指数曲线那样带"标题"(指数名、情绪分 标签、对应指数值)。

## 改动清单(static-site/app.js, 5 处逻辑 + 签名)
| # | 位置 | 改动 | 作用 |
|---|---|---|---|
| A1 | `openSignalChartModal` s.* 分支 L6295 | `chartData` map 保留 `is_freeze` | 冰点判定读数据标记(防漂移) |
| A2 | `openSignalChartModal` L6327-6333 | 冰点追加条件 `if (isFreeze)` → **`if (indexId.startsWith("s."))` 恒显**;判定 `is_freeze===1 \|\| value<=20` 双保险 | 从买卖点信号 cell 进 s.* 弹窗,冰点日也恒有蓝 pin |
| B1 | `valueChartWithSignals` 签名加第11参 `isSentiment=false` | echarts 态 tooltip formatter 增强 | 情绪分类带"指数名 情绪分"标签、综合类带"情绪分"、全球extras 保持原子格式 |
| B2 | `_lwSignalLiteCfg` 签名加第6参 `isSentiment` | lite 态 tipFn 增强(与 echarts 态同口径) | 轻量 SVG 引擎默认态 tooltip 一致 |
| B3 | 调用点传 isSentiment:弹窗 `indexId.startsWith("s.")`、B卡6宽基=true、恐贪/a_sentiment/跨市场=true、全球extras 不传(默认 false) | 白名单精确生效 | 综合/恐贪/跨市场带"情绪分",全球extras 不误伤 |

### 需求 B tooltip 输出格式(用户示例确认)
```
07-17  科创50 情绪分 15.82
─ 科创50指数:1715.40
```
- 第一行: `日期 + 空格 + <指数名>情绪分 + <b>情绪值</b>`(s.* 弹窗/B卡6宽基,叠 indexOverlay.name 如"科创50")
- 综合类(恐贪/A股综合/跨市场, indexOverlay=null): 第一行 `日期 + 情绪分 + <b>值</b>`,无指数行
- 全球extras(g.* gold/usdcnh 等指标),isSentiment=false: 保持 `日期<br/>裸值`,**不贴标签不误伤**
- 第二行(仅叠指数): 棕色横条 + `<指数名>指数:` + 指数值(对齐 #24 指数曲线)

## 范围控制(§23.3 同类覆盖清单)
`valueChartWithSignals` 6 处调用点逐一判定:

| 调用点 | indexOverlay | isSentiment | 冰点挂删? | tooltip |
|---|---|---|---|---|
| s.* 情绪分弹窗(L6425) | 6宽基非空 / 非6宽基空 | `indexId.startsWith("s.")` | ✅ s.* 恒显(需求A) | indexName 情绪分 + 指数值 |
| B卡6宽基(L18397) | keyOverlay 非空 | true | ✅(同走 s.* 恒显) | indexName 情绪分 + 指数值 |
| 恐贪 fear_greed(L18275) | null | true | 无(不叠指数) | 情绪分 + 值 |
| A股综合 a_sentiment(L18349) | null | true | 无 | 情绪分 + 值 |
| 跨市场 cross_market(L18436) | null | true | 无 | 情绪分 + 值 |
| 全球extras g.*(L15694) | null | **false** | 无 | 保持 日期+裸值(不误伤) |

**不覆盖/不误伤**: renderOverview 本体/新闻域(#12)/signalColor·signalLabel·freeze 蓝定义(#20)/indexChart(#73)/费率 均未触碰。freeze 蓝 pin 复用现成 `signalColor(s)==#42a5f5` + `signalLabel=="冰点"+round(value)`(E04 同源),不重复定义。

## 自验(§23.2 三铁律 + §23.3)
### 需求 A 仿真(真实线上数据 sentiment_sz50) — `scripts/emotion-freeze-pin-sim.mjs`
- 场景1 买卖点cell进 s.* 弹窗 → 冰点 pin 数 **166** ✓
- 场景2 冰点cell进 s.* 弹窗 → 冰点 pin 数 **166**(恒显不减, #20 不回归)✓
- is_freeze=1(166) ⟺ value<=20(166) 两口径逐位一致(纯对齐,行为不变)✓
- 全球extras(gold)/恐贪 非 s.* → 冰点 pin **0**(不误伤)✓

### 需求 B 仿真(真实格式断言) — `scripts/emotion-tooltip-sim.mjs`
- T1 s.* 弹窗叠指数 → `2026-07-17  科创50 情绪分 <b>15.82</b><br/>...科创50指数: 1715.40`(含"科创50 情绪分"+"科创50指数:", 无"创业指数"误拼)✓
- T2 综合类(isSentiment, 无指数) → `... 情绪分 <b>55.30</b>`(无指数行)✓
- T3 全球extras(isSentiment=false) → `2026-07-17<br/>550.20`(原子格式, 无标签)✓
- T4 lite 态与 echarts 态输出**逐字节一致**(两态行为一致)✓

### 编译/语法
- `node --check static-site/app.js` PASS
- terser 压改后源码成功, min 语法 OK, 含 "科创50"/"指数: " 关键串 ✓

### 同类错误面清单(§23.2①)
用户报单点(情绪分弹窗无冰点 pin)。grep 全站 `s.` 弹窗入口来源(情绪日历信号格 data-sig=buy/sell L3097 / 市场温度信号列表 L2920)确认均为 `s.sentiment_*` indexId → 全部走新恒显分支,同类覆盖完成。

## 回归红线
- #20 冰点 cell(入口 isFreeze=true)4 蓝 pin: 恒显逻辑为 s.* 全史追加,窗口内 ≤20 日均画蓝 pin,**必然包含原 4 pin,不减** ✓
- 综合/恐贪/跨市场/全球extras 不随手加 indexName(它们 indexOverlay=null 天然排除)✓
- #24 已叠指数曲线(双轴)行为不变, 仅 tooltip 加"指数名/情绪分"标题 ✓

## §21 算法公示
不触发: 纯前端展示增强(冰点 pin 恒定展示 + tooltip 标签), 未改任何 track_score/评分/权重/分段函数/匹配规则等算法逻辑。不 bump 版本(非 AI 推荐/降亏过滤核心算法改动, §5.4⑥)。

## §22 数据一致性
不涉及数据产物/后端: only 前端 app.js 展示逻辑。sentiment-all.json 本身已含 is_freeze(数据层无需改动/重跑/R2 同步)。前端上线走 `main-merge.sh` 统一 build_min+bump(版本串)。

## 复现(§23.5 四件套)
- **脚本**: `docs/market-state/scripts/emotion-freeze-pin-sim.mjs`(需求A 冰点 pin 判定仿真, 依赖线上 `https://ss.fx8.store/data/sentiment-all.json`)、`docs/market-state/scripts/emotion-tooltip-sim.mjs`(需求B tooltip 格式断言)
- **重跑**:
  ```
  curl -s "https://ss.fx8.store/data/sentiment-all.json" -o /tmp/sentiment-all.json
  node docs/market-state/scripts/emotion-freeze-pin-sim.mjs
  node docs/market-state/scripts/emotion-tooltip-sim.mjs
  ```
- **输入依赖**: 线上 sentiment-all.json(真实数据)
- **代码口径**: 冰点判定 = `s.* 弹窗恒显`, `is_freeze===1 || value<=20`; tooltip = `日期 + indexName情绪分 + 值`, 叠指数加 `<indexName>指数: 值`
- **关键证据**: 线上 sentiment-all.json 实测 1197 元素含 is_freeze=1; s.sentiment_sz50 全史 166 冰点日两口径逐位一致

## 相关联
- 根因文档: `docs/market-state/sentiment-popup-freeze-pin-rootcause-20260820.md`(主控)
- 前端共享函数: `static-site/app.js` `valueChartWithSignals`(L5000) / `_lwSignalLiteCfg`(L4913) / `_emotionIndexCurve`(L1391,#24)
