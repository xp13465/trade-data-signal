# 移动端可视/可用度专项评测 —— 信号凯利回测（sigkelly）+ 全站

- 日期：2026-09-18；视口 390×844（iPhone UA）实测
- 触发：用户反馈「信号凯利回测在移动端说明和筛选太多，影响主要数据查看」
- 结论：布局层面已 responsive（无横向溢出、无报错），但**手机专属的「可视/可用度」优化确实还没做**——桌面版的全量说明/免责/引导/参数，手机端只是原样向下堆叠，把核心回测数据埋到了约 5 屏之后。

## 一、实测首屏占位（用户打开到底先看到什么）
核心「16 卡凯利回测」网格 top ≈ 4228px，约等于 **5 个首屏**（844px/屏）之后。自顶向下依次是：

| 位置(top) | 区块 | 高度 | 性质 |
|---|---|---|---|
| 0 | h5-topbar | 57px | 导航（图标拥挤） |
| 65 | risk-banner | 104px | 全局免责 |
| 177 | market-status-banner | 34px | 盘中状态 |
| 223 | lab-top-disclaimer | 214px | 实验室免责（与全局免责重复） |
| 450 | lab-newbie-guide | 319px | 新手引导（`<details open>` 默认展开，无持久化） |
| 783 | lab-subnav + h5-bottomnav | 53px | 二级导航 |
| 842 | lab-subnav-child | 34px | 三级导航 |
| 888 | purpose-note | 353px | 「这板块有什么用」说明 |
| 1263 | lab-sigkelly-bar | 82px | 核心筛选（周期/买入口径/费率/参数） |
| 1357 | auto-trade-steps | 633px | 实操提醒（下一交易日买卖计划） |
| 2002 | lab-sigkelly-advice | 798px | 全信号操作建议指南 + 一堆口径说明 |
| 2814 | 第一张数据组卡 | — | 开始出现数据 |
| 4228 | lab-sigkelly-grid | — | **16 卡回测网格（本来该第一眼看到的东西）** |

> 首屏(0~844px)里非数据占 ~636px（约 75%）。用户要看主要数据，得先滚过 ~4200px 的免责/引导/说明/建议。

## 二、问题定性（三类，都指向同一根因：信息层级没做移动端降级）
1. **说明重复堆叠**：`risk-banner`(104px) 与 `lab-top-disclaimer`(214px) 内容几乎重复；`purpose-note`(353px)、`lab-newbie-guide` 三步说明、`lab-sigkelly-advice` 的口径说明/核实源也多次重复。
2. **默认展开且无记忆**：`<details class="lab-newbie-guide" open>` 硬编码 default open；purpose-note、advice 指南默认展开；没有「已读即收起」的 localStorage 持久化，每次进都重新吃一遍。
3. **核心筛选不在首屏、且被夹在说明中间**：筛选条在 y=1263，数据在 y=4228。

## 三、整改建议（不动整体布局，只做信息层级 + 折叠/固定）
### sigkelly 页
1. **数据优先排序**：首屏 = 一行核心结论 + 筛选条(sticky) + 16 卡网格；说明全部后置。
2. **筛选条 sticky 化**：`lab-sigkelly-bar` 顶置，完整参数（⚙️ 参数/演进/费率档）收进底部抽屉，选中态一行常驻。
3. **免责二合一 + 折叠**：`risk-banner` × `lab-top-disclaimer` 合并成一个可折叠 summary（318px → 48px）。
4. **引导/说明默认收起**：`lab-newbie-guide`、`purpose-note` 默认只留 summary 一行 +「?」触发，localStorage 记住已读；`lab-sigkelly-advice` 只留 1~2 行结论 + 折叠全文。
5. **实操提醒移出主数据流**：`auto-trade-steps`(633px) 与「看回测结果」不是同一任务，移动端默认折叠/移到页面底部或独立入口。
6. **顶部条减负**：topbar 去掉次级图标（通知×2/主题等），只留标题 + 核心切换；版本更新 toast 改小 pill 且自动消失。

### 全站通用原则
- 所有 tab 的 `risk-banner`、`chart-hint`、`hint-*`、`pf-help`、各「这板块有什么用」统一走「**折叠式说明 + 数据优先**」规范，不要逐页自造。
- 立一条移动端铁律：**首屏只放数据/结果，说明与口径一律进二级「帮助/说明」抽屉**；筛选选中态 sticky，细项底部抽屉。

## 四、量化预期
- 首屏非数据从 ~636px(75%) 降到 <100px；16 卡网格从 4228px 提到 ~500px 内，用户少滚约 4 屏。

## 五、评测局限
headless Chromium（iPhone UA + 390×844），非真机 Safari；折叠交互的可用性建议真机点一轮复核。
