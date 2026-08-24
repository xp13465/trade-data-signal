# 信号凯利回测页移动端样式独立重构——现状盘点 + 多方案设计(2026-08-26 落档,待用户拍板)

> 性质:只读调研产物,未改任何代码。等用户选定方案后再派实施。
> 页面实物:「策略实验」tab → 🎯自定义分析 → 📊信号凯利回测(hash `#lab?sub=sigkelly`)。
> 载体 = 主站 index.html(非独立 HTML),渲染逻辑 static-site/lab.js(L8615 `renderSigKellyLab` 起,约 3000 行凯利区代码),样式 static-site/lab.css(sigkelly 相关 476 处规则)。线上版本 lab.min.js?v=20260825-a418(已 curl 实证含「信号凯利回测」字符串)。

## 一、区块结构清单(DOM 实物)

| 区块 | 代码位置(lab.js) | 内容/列数 |
|---|---|---|
| 顶部说明 details | L8620-8633 | purpose-note 折叠(~3000 字文案) |
| 吸顶参数条 bar | L9365 `_renderSigKellyBar` | 周期 tab(y1/y3/all)+费率预设+5 个费率 number input+降亏 toggle 全家桶(NEW14 高亮区+更多开关折叠区) |
| 组合建议+全信号表 | L10512 `_sigKellyAllSignalGroupHtml` | 全信号卡 + 按年窗口表(7 列:年份/笔数/净盈亏/累计/胜率/峰值收益率/峰值回撤)+ A-G 模式下拉 |
| 6 类分组卡片网格 | L10578 `_renderSigKellyQuadrants` | 置顶区+评级3卡+ETF4卡+信号类型4卡+指数5卡,共 16 张卡 |
| 单卡内表格 | L11066 `_renderSigKellyCard` | **15 列宽表**(模式/半凯利/胜率/盈亏比/单笔均收益/样本/最终盈亏/峰值资金收益率/费率消耗/最大持仓/持仓中/年化/夏普/最大回撤/卡尔玛,L11170 thead) |
| 卡间比较水印/hoverpop | L10790/L10841/L10916 | 蓝★紫◆徽章 + wm-pop/cwm-pop 弹层 |
| 明细弹窗 overlay | L11181 `_openSigKellyTradesModal` / L11321 | **15 列交易明细表**(L11334 colDefs)+筛选+分页 |
| 报告查看弹窗 | lab-kelly-repo-modal(L2005 起 CSS) | markdown 正文+TOC |

注:任务书提到的「13 列费后累积表」= 首页模拟回测弹窗(app.js),不在本页;本页对应物是上述 15 列明细弹窗。本区无 SVG/echarts 图表(纯表格+弹层),图表适配不适用。

## 二、现状问题盘点(逐项带证据)

### 先说清:不是没做过移动适配
2026-08-15 已落过一轮 B 级补丁式适配(lab.css L1910-1950「移动端整体布局/样式优化」段):
- 吸顶参数条 ≤600px 默认折叠成 1 行(lab.js L9366-9380,localStorage 记忆)
- toggle 高亮区/更多开关 600px 下 2 列网格(L1926-1936)
- 卡片单列撑满+表格 cell padding 压缩到 10.5px 字号(L1938-1946)
- 明细弹窗 760px 下 max-width:100%/95vh(L1837-1841);报告弹窗 600px 近全屏(L2059)
- wm-pop/posrate-pop 宽度 min(x, calc(100vw - 16px))(L1408/L1595);all-main 1080px 断点纵排(L1750)

**用户仍觉得差,是因为这轮只是"补丁",以下根因一个都没解:**

### P0(最重根因,性能):trades.json 整包 62MB 拉取
- 数据实物:`data/signal_kelly_trades.json` = **65,394,900 字节 ≈ 62MB**(gz 9.7MB)
- 触发点①:点任意卡内行开明细弹窗整包 fetch(lab.js L11199-11213,R2 直链→CF 兜底)
- 触发点②:**切费率档/自定义费率**也拉同一整包重算(`_kellyApplyFeeRecompute` L8137-8158)——用户在手机上动一下费率就触发 62MB 下载
- 线上实测(iPhone UA,gzip 已开):**10,199,115 字节 ≈ 10.2MB,快网耗时 4.9s**(2MB/s);4G/弱网 30-60 秒级
- 之后 `resp.json()` 全量解析 62MB 文本:手机端 JSON.parse 数秒~十几秒、内存峰值数百 MB,iOS Safari 有直接崩标签页的风险
- 对照:主数据 signal_kelly_backtest.json 线上 gzip 后仅 61KB(实测 1.0s),无压力

### P1 布局/交互问题
1. **15 列宽表的窄屏方案只有"横滚"**:卡内表(lab.css L1753 table-scroll overflow-x)+明细表(L1790 nowrap)都是横向滑;字号压到 10.5px(L1942)、padding 压到 3px(L1943)。横向滑走之后既看不到行首模式名也看不到列头,**不知道自己在看哪个数**
2. **明细弹窗无首列冻结**:th 只 sticky top(L1792),横向滚动时「触发信号/ETF名称」列跟着滚走;分页按钮贴 modal 底部,iPhone 底部工具栏/安全区可能遮挡(modal 95vh,L1838)
3. **三层吸顶叠加占屏**:lab-subnav(top:var(--tab-h),L843-850)→ lab-subnav-child(L875-881)→ lab-sigkelly-bar(L1367,top 三变量相加),折叠态约 100-110px;展开参数控制台后更高。折叠方案(08-15)已缓解但展开态仍压内容。移动端 nav.tabs 隐藏使 --tab-h 实测为 0(app.js L24905 initStickyOffset 量 display:none 的 offsetHeight),吸顶链实际从屏幕顶开始,行为正确但高度全留给三层导航
4. **触控目标普遍小于 Apple 44×44pt 建议**:period-btn padding 3px 8px 字号 11px(L1908)、fee-btn padding 2px 6px 字号 10px(L1913)、toggle padding 3px 5px(L1930)——手机上难点准、易误触
5. **断点不统一**:全站 h5 模式切换 = 768px(app.js L26281 matchMedia 驱动 body.h5),lab.css 主断点 = 600px/760px,style.css = 768px。600~768px 区间(iPad mini 竖屏/大屏手机横屏/桌面小窗)=「h5 导航已切换但 lab 移动样式未生效」的中间态

### P2 iOS Safari 兼容坑(逐项实证)
| 坑 | 证据 | 后果 | 修法 |
|---|---|---|---|
| input font-size<16px 聚焦自动放大 | `.lab-sigkelly-fee-custom .lab-input{font-size:11px}`(lab.css L1478);yearly-mode-select 12px(L1741);明细筛选 input 同类 | iPhone 一点费率输入框页面整体放大,布局错乱需手动缩回 | 移动端 input/select font-size 提到 ≥16px(或 JS focus 时临时 scale 抑制,首选前者) |
| vh 不随 iOS 地址栏伸缩 | modal max-height 90vh(L1780)/95vh(L1838);repo-modal min(92vh)(L2010);review-body 70vh(L1870) | 地址栏收起时 95vh > 可视高,弹窗底部(分页按钮/关闭钮)被工具栏遮住点不到 | 改 `dvh`(iOS16+/现代浏览器)+ `svh` 兜底,老 iOS 保底 vh |
| 安全区未覆盖弹窗层 | viewport-fit=cover 已有(index.html L5);overlay padding 20px 无 safe-area(L1778);modal 分页条贴底 | 全面屏底部 home indicator 压住分页按钮 | 弹窗底部 padding 加 `env(safe-area-inset-bottom)`(首页 h5-bottomnav 已有同款先例 style.css @media 段) |
| 横滚与竖滚手势冲突 | table-scroll 横滚区(-webkit-overflow-scrolling:touch,L1753)嵌在整页竖滚里 | 斜着滑容易误触发整页滚动,横滑体验差 | overscroll-behavior-x: contain + 关键列冻结减少横滑需求 |
| sticky 表头在弹窗滚动容器内 | trades-table th sticky top:0(L1792) | 本身正常,但配合上面 vh 问题,表头吸的位置会随视口漂移 | dvh 修复后自愈 |

### P3 数据体积事实(只记录)
- signal_kelly_backtest.json:本地 462KB / 线上 gzip 61KB —— 无压力
- signal_kelly_trades.json:本地 62MB / 线上 gzip 10.2MB —— 见 P0
- lab.min.js 766KB(gz 约 190KB 量级)+ app.js 1.89MB(首页共用,与本页无关)—— 移动首屏有感知但不属本页专项

## 三、三个完整方案(无一为偷懒版)

### 方案A:响应式补齐 + iOS 兼容专项(公共底座)
- **核心手段**:现有 DOM/渲染路径完全不动,只在 lab.css 追加/修正断点规则 + lab.js 个别属性:
  ①iOS 专项四件套(input≥16px / vh→dvh+svh / 弹窗 safe-area / overscroll-behavior-x)
  ②断点统一:lab 区移动断点对齐全站 768px(600/760 并入 768,或加一层 768 规则保留 600 微调)
  ③触控目标放大至 ≥44×44pt(period/fee/toggle 按钮 padding 提升)
  ④15 列表低成本改良:**首列 position:sticky left 冻结 + 列头随横滚可见 + 右缘渐隐遮罩提示可滑**,仍是横滚范式但可用性大幅提升
- **改动范围**:lab.css(+150~250 行)/ lab.js(<20 行,input 属性级)。不新增文件
- **移动端收益**:输入不再触发页面缩放、弹窗按钮不再被工具栏吃掉、按钮好点准、横滚有方向感;**性能瓶颈(62MB)完全不动**
- **工作量**:0.5~1 agent·天
- **风险与回归面**:极低。全部是断点内新增规则,桌面(>768px)零变化——保证方式=所有新规则都写在 `@media (max-width:768px)` 内,merge 前 diff 逐条核对无断点外规则。回归面=sigkelly 区块移动端各弹层冒烟
- **维护成本**:低(纯 CSS 断点,后续改凯利区无需双处维护)

### 方案B:移动优先重排 + 数据切片根治(含 A 全部)【推荐】
- **核心手段**:A 的全部,再加两层:
  ①**布局级重构(≤768px 分支内)**:
    - 卡内 15 列表 → 「摘要行 + 展开」卡片化:每模式一行直显 4 个关键列(半凯利仓位/胜率/最终盈亏/峰值资金收益率),其余 11 列收进行内展开(details 或点击翻转),不再横向滑
    - 明细弹窗 → 移动端 bottom-sheet 抽屉(自下滑入、顶部下拉关闭)+ 列选择器(默认显 6~8 关键列,其余勾选按需)+ ETF 名称首列冻结
    - 参数控制台展开态 → 底部 sheet;toggle 全家桶保持 2 列但加大命中区
  ②**trades.json 性能根治(数据产物层)**:
    - export 链新增按 `quadrant × period`(或 quadrant×mode×period)预切片小 JSON(单片预计 <300KB),前端弹窗/费率重算只拉当前所需切片
    - 现有 signal_kelly_trades.json 原样保留(PC 继续用),切片属**纯新增产物**,每日重跑链(§22 三步:重跑+static-site+R2)同步生成
- **改动范围**:lab.css(+400 行级)/ lab.js 渲染分支(+300 行级:卡片渲染与弹窗各加移动分支)/ scripts/export.py 或 signal_kelly_backtest.py(+切片导出 ~100 行)/ R2 上传链登记。DOM 结构调整仅存在于移动分支
- **移动端收益**:首开弹窗从 10MB/5s+ 变 <300KB/亚秒;费率切换不再整包拉;15 列变 4 关键列直读;抽屉式交互符合拇指热区;叠加 A 的兼容修复
- **工作量**:2~3 agent·天(含切片联调+R2 同步验证)
- **风险与回归面**:中。
  - 桌面零变化保证:渲染函数入口处 matchMedia 分流,≤768 走新分支,>768 走原 `_renderSigKellyCard`/`_renderSigKellyTradesModal` 原 path 原样不动(代码上物理隔离,diff 可验);切片是新增文件不改现有 JSON 结构
  - 回归面:sigkelly 全区块移动+桌面双侧冒烟 / export 重跑链 / R2 新类别上传(§23.2③同类排查:确认新切片类别走了 R2 上传通道)/ §22 一致性(切片数字必须与整包重算逐位一致,校验脚本挂 check_data_integrity)
- **维护成本**:中。切片产物加入每日重跑链,后续新增象限/键集时切片自动跟随(脚本化,非人工)

### 方案C:独立移动视图(专用渲染树,类似 lite SVG 思路)
- **核心手段**:≤768px 时 `renderSigKellyLab` 整体切到独立轻量渲染器:KPI 摘要卡流(每象限一张浓缩卡)+ 分区锚点导航(替代三层吸顶)+ 原生感 bottom-sheet 组件族 + 骨架屏;桌面渲染树完全隔离零接触。数据侧同样需要 B 的切片方案(否则 62MB 瓶颈仍在,C 单独做不成)
- **改动范围**:lab.js 新增移动渲染模块(+800~1200 行)/ 新建 lab-mobile.css(+500 行级)/ 数据切片同 B
- **移动端收益**:三者中上限最高,可做到接近原生 App 的浏览体验
- **工作量**:4~6 agent·天
- **风险与回归面**:中高。同一功能两套渲染树长期共存:后续每次动凯利区(公示 §21/一致性 §22/键集登记 §22 代码常量点)都要双处核对,**漂移风险随时间累积**;与「敏捷快速迭代」取向有张力
- **维护成本**:高(双路径永久性维护)

### 推荐排序:B > A > C
理由:
1. 用户痛点 = 一半性能(P0 62MB,手机上基本不可用)+ 一半 15 列表交互。A 只修体验细节,两个大头都不解;C 的体验收益与 B 几乎相同,成本和维护翻倍
2. B 符合「完整正确一步到位不妥协」默认准则(§5):布局重构+数据根治一次做完,且桌面零变化技术上可保证(分流隔离)
3. A 与 B 不冲突:**若想先快速止血,A 可先行上线(0.5~1 天),B 作为二期迭代**——B 天然包含 A
4. C 仅在未来移动端成为主力使用场景、且要把凯利页做成类 App 形态时才值得

### 兼容性专项的归属判断
iOS 四件套(input 缩放/vh/safe-area/overscroll)属**客观缺陷修复级**,不依赖方案选型——判定为「三方案公共底座」,先行落地(即 A 单独可先做);B/C 直接继承。

## 四、约束核查(§23.4 / §23.7 / §21)

- **§23.4 与既有待办关系**:pending-features-index.md 中 #49/#50 已于 2026-08-20 批量完成移入 done-list(L66 注释行实证,非活跃项);#94(AUTO 模式)已销号但注明「观察期后切 14+1 打 v1.1.7 即定稿动作」(L148);#17 凯利 v5/#21 远期待办。**先后关系建议:v1.1.7 定稿动作(bj50 剪枝)先行,移动端重构随后**——避免切片产物的口径基座跟着变两次;本任务不动回测口径/默认组合,与 v1.1.7 无冲突,但切片脚本依赖 trades 产物结构,v1.1.7 动结构则切片需在其后联调。本任务立项后应登记进 pending-features-index.md(由主控执行,调研 agent 未越权写入)
- **§23.7 冻结契约**:方案 A/B/C 均标注「纯新增断点样式/纯新增渲染分支,桌面 >768px 默认行为零变化」。其中唯一需要实施时特别小心(但不需要额外用户确认)的点:B 的明细弹窗改造如果实现为共享 DOM 结构修改而非断点分支,会触及桌面路径——实施规范要求用渲染分支物理隔离,reviewer 按「桌面 diff 为空」验收。**无标红项**:三方案都不动算法/口径/默认组合
- **§21 公示判断**:本次为展示层样式/渲染重构,不涉 track_score/评分/权重/分段函数/匹配规则等算法逻辑,预期**无需公示**。唯一低成本稳妥动作:B 的切片方案改变「费率重算数字的来源路径」(数字本身不变),可在 purpose-notes `lab.sigkelly` 复现段补一句说明,非强制

## 五、复现(核验本文档事实的命令)

```bash
# 1) 页面载体与线上版本(第一节)
grep -c '策略实验' static-site/index.html          # ≥2(tab+h5 导航)
curl -s -A 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)' https://ss.fx8.store/ | grep -o 'lab\.min\.js?v=[^"]*'
curl -s https://ss.fx8.store/lab.min.js?v=20260825-a418 | grep -c '信号凯利回测'   # ≥1

# 2) 区块与列数(第一节/二节 P1-1)
grep -n 'function renderSigKellyLab\|function _renderSigKellyBar\|function _renderSigKellyCard\|function _openSigKellyTradesModal' static-site/lab.js
grep -n '<thead><tr><th>模式</th>' static-site/lab.js            # 卡内 15 列表 L11170
sed -n '11334,11349p' static-site/lab.js                          # 明细弹窗 colDefs 15 列

# 3) 已做适配与断点覆盖(第二节开头/P1-5)
grep -n '@media' static-site/lab.css                              # 600/760/768/1080 分布
sed -n '1910,1950p' static-site/lab.css                           # 2026-08-15 移动端优化段
grep -n 'matchMedia("(max-width: 768px)")' static-site/app.js     # 全站 h5 断点 L26281

# 4) P0 数据体积(第二节 P0)
ls -la data/signal_kelly_trades.json data/signal_kelly_backtest.json
curl -s -A 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)' --compressed -o /dev/null \
  -w 'bytes=%{size_download} time=%{time_total}s\n' https://ss.fx8.store/data/signal_kelly_trades.json
# 实测(2026-08-25): bytes=10199115 time≈4.9s
sed -n '11199,11213p' static-site/lab.js                          # 弹窗整包 fetch
sed -n '8137,8158p' static-site/lab.js                            # 费率重算同文件

# 5) iOS 坑证据(第二节 P2 表)
grep -n 'font-size: 11px' static-site/lab.css                     # L1478 fee-input 等 <16px
grep -n '90vh\|95vh\|92vh\|70vh' static-site/lab.css              # vh 族 L1780/L1838/L2010/L1870
grep -n 'viewport' static-site/index.html                         # L5 viewport-fit=cover 已有

# 6) 待办关系(第四节)
grep -n '#49/#50\|#49.*#50' docs/pending-features-index.md        # L66 已完成移入 done-list
```

数据截止:本地产物 2026-08-25(signal_kelly_trades.json 04:08);线上版本串 20260825-a418;curl 实测 2026-08-25。
关键口径一句话:本文档只盘展示层数据链路与样式现状,未动任何回测口径;「15 列」指卡内宽表与明细弹窗两处 thead 实数,「13 列费后累积表」属首页模拟回测弹窗不在本页范围。
