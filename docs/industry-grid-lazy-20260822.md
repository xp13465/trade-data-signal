# 板块分化 subtab spark 格懒渲染(P2-11 同根因延伸)+ main-merge.sh 销账软提醒 — 实施报告

> 日期:2026-08-22(周六非交易日) | 分支:`feat/industry-grid-lazy-merge-remind` | base:origin/main@df809cf03
> 关联:pending-index #80(P2-11 遗留段「板块分化 renderIndustryGrid 753ms 同根因」)/ P2-11 报告 docs/p2-11-dapan-lazy-plan.md

## 件① 板块分化懒渲染

### 根因
`renderIndustryGrid`(static-site/app.js,A股申万行业+概念板块+港股板块三路径共用)每格同步 `echarts.init` 主 spark + F2 迷你×3 + F3 宽度共 4-5 个实例,119 格 ≈ 303 实例一次性同帧创建,切 subtab 单帧长任务 747ms(实测,与任务给的 753ms 同量级)。

### 方案(复用 P2-11 基础设施,改动最小)
1. **`_mktLazyProxy` 泛化**(大盘路径行为等价):`firstOpt` 支持传函数(option 延迟构建,init 时才读实时皮肤色);新增 `chartEl.__mktLazyProxy` DOM→代理反查标记。大盘传对象用法逐分支行为不变。
2. **`_disposeContainerCharts` 认懒卡**(评审项B闭环):选择器补 `.ind-metric-chart`(仅行业格使用),命中 `__mktLazyProxy` 先走 `proxy.dispose()`(unobserve+出 charts+清 pending)再 return;无懒卡容器反查不命中,原路径逐行为等价。搜索过滤 `_applyIndustryFilter` 的 `_disposeContainerCharts(swGridWrap)` 直接受益。
3. **`renderIndustryGrid` 图表全部延迟**:DOM 骨架同步建(CSS min-height 120px/32px 保布局零变化),每格图表经 `_mktLazyProxy` 入全局 charts(resize/retheme/dispose 消费面同真实实例),option 以闭包函数传入;格尾 `_marketLazyRegister(cell, () => _indLazyEnqueue(_cellProxies))` 进视口(rootMargin 250px,复用 P2-11 IO 单例)才 init。
4. **时间切片排水** `_indLazyEnqueue/_indLazyDrainStep`(新增,板块分化专用):行业格小(~260px×4列),可视区一次可达 60+ 图,若 IO 回调同步 init 仍是数百 ms 长任务;改为入队+每 tick 时间盒 12ms 分帧排空,单任务恒 <<50ms。已 dispose 代理出队即弃(`_mktInit` disposed 幂等双保险)。
5. **§23.7 冻结**:大盘 tab(P2-11)调用点一行未动;港股/A股行业/概念三路径同函数自动覆盖(举一反三:概念板块 grid 与申万 grid 共用 renderIndustryGrid,一处改双生效)。

### 自验(Playwright headless,真实数据,双站点对照)
base=改前 HEAD~1 版本(/tmp/site-base@8124),lazy=本改动(/tmp/site-lazy@8123),viewport 1440x900 dpr1,动画冻结,最终轮次 base3/lazy3:

| 指标 | base3 | lazy3 | 结论 |
|---|---|---|---|
| 切板块分化 >50ms 长任务 | **[761, 60]** | **[58]** | spark 格 753ms 量级长任务消除 |
| 未滚动 early canvas(行业格) | 303(全量同步 init) | 10(仅可视带) | 懒生效 |
| 滚动全页后主 spark 图 | 119/119,missing 0 | 119/119,missing 0 | 出图总数等价 |
| 滚动全页后迷你图(F2+F3) | 184,missing 0 | 184,missing 0 | 等价 |
| 搜索"银行"过滤后 | 3 格 3 图 | 3 格 3 图,missing 0 | _disposeContainerCharts 销毁+重渲链路 OK |
| 清空搜索恢复后 | 119/119 | 119/119,missing 0 | 全量重建链路 OK |
| 港股 subtab 切换长任务 | [64] | [](无) | 同函数复用路径同步受益 |
| 港股 8 格出图 | 8/8 | 8/8 | 等价 |
| 大盘 a-stock early/full canvas(P2-11 回归) | 5 / 15 | 5 / 15 | 零变化 |
| pageerror(JS 异常) | 0 | 0 | 零 JS 错误(lazy 有 1 条网络层 console ERR_CONNECTION_RESET,资源加载抖动非 JS 异常,base 轮次亦出现过) |

**像素 diff(pixdiff,逐像素 RGBA 对比)**:
- industry-full(申万+概念 119 格整页,1440x48012):**diffPixels=0(0.00000%)**
- astock-full(大盘 P2-11 回归整页):**diffPixels=0(0.00000%)**
- hk-full(港股整页):19 px(0.00021%,噪声级)
- industry-filtered(过滤区截图):34 px(0.00237%,噪声级)

### 残余项上报(§23.7 冻结契约,不在本任务授权范围)
切板块分化仍有单条约 58-81ms 任务(base 同窗口亦有 54-78ms 同源任务,非本次引入)。CDP Profiler 实证无单点热点:renderIndustryGrid self 仅 17.7ms + GC 16.6ms + 热力图 echarts init/DOM 杂项拼接。构成=申万热力图 `renderIndustryHeatmap`(独立单图 echarts.init)+ 119 格 DOM innerHTML 构建,均非「spark 格图表」范畴;要彻底压到 <50ms 需热力图懒渲染或 DOM 构建分帧,**属新授权范围,请主控拍板是否另开任务**(pending-index #80 P2 段可挂)。

### 已知边界(诚实标注)
- 懒渲染只延迟初始化;滚动到可见后渲染结果与一次性渲染逐像素一致(pixdiff 验证)。
- IO 不支持环境(老 webview):`_marketLazyRegister` 同步兜底调 initFn → 入队后照样分帧排空,退化为渐进渲染不白屏。
- 本地测试环境的 `industry-all-indices/*-detail.json` R2 子路径无 CORS 头(capture 已 route mock),线上同源不存在此问题;detail 失败本有静默降级 catch(tooltip 退化用内联数据),不影响渲染。

## 件② main-merge.sh 销账软提醒

### 逻辑
merge 完成后(§24⑤ 校验后、commit+push 前,新增 8.5 步):从 `git log --format=%B <merge前origin/main>..HEAD` 提取 `#\d+` 编号,对照 `docs/pending-features-index.md` 检查活跃形态——①行内词边界精确 `#NN` 引用(#15 不误配 #150) ②表格行首列裸编号 `| NN |`(pending-index 主表行主键形态);先 `sed` 剔除 `~~…~~` 划线墓碑段再查。命中 echo 软提醒,**只提醒不阻断不自动改文件**;dry-run 跳过;纯 bash+grep 零新依赖。

### 测试用例(沙箱 git 仓,块从脚本原文提取防手抄漂移)
| 用例 | 期望 | 实际 |
|---|---|---|
| commit 引用 #10,pending-index 有活跃行 `\| 10 \|` | 命中 | ✓ |
| #15 与 #150 并存(词边界) | 各自精确命中,不互误配 | ✓ |
| #41 仅以交叉引用形态出现 | 命中 | ✓ |
| ~~#37~~ 墓碑行 | 不命中 | ✓ |
| 同行混合 ~~#40~~ + 活跃 #52 | 只命中 #52 | ✓ |
| 无编号 commit | 干净输出 | ✓ |
| --dry-run | 跳过 | ✓ |
| 真实脚本 --dry-run 端到端 | 8.5 块位置正确(§24⑤ 后 push 前),整体不炸 | ✓ |

## 复现

```bash
# 前置: feat 分支 checkout;起两个本地 server(base=改前版本 / lazy=改后)
bash scripts/build_min.py   # 从 HEAD 源生成 min(改前端源后必须)
rm -rf /tmp/site-lazy /tmp/site-base && mkdir -p /tmp/site-lazy /tmp/site-base
cp -R static-site/ /tmp/site-lazy/
cp -R static-site/ /tmp/site-base/
git show 'HEAD~1':static-site/app.js    > /tmp/site-base/static-site/app.js
git show 'HEAD~1':static-site/app.min.js > /tmp/site-base/static-site/app.min.js
(python3 -m http.server -d /tmp/site-lazy 8123 &)
(python3 -m http.server -d /tmp/site-base 8124 &)

# 捕获(各 ~1-2 分钟): 长任务/canvas 计数/截图 → /tmp/igcap/{base,lazy}/
node docs/scripts/industry-grid-lazy-capture.js --label base --outdir /tmp/igcap/base --url http://localhost:8124/index.html
node docs/scripts/industry-grid-lazy-capture.js --label lazy --outdir /tmp/igcap/lazy --url http://localhost:8123/index.html

# 像素 diff(逐图对比,期望 diffPct≈0)
node docs/scripts/industry-grid-lazy-pixdiff.js /tmp/igcap/base/industry-full.png /tmp/igcap/lazy/industry-full.png
node docs/scripts/industry-grid-lazy-pixdiff.js /tmp/igcap/base/astock-full.png   /tmp/igcap/lazy/astock-full.png
node docs/scripts/industry-grid-lazy-pixdiff.js /tmp/igcap/base/hk-full.png       /tmp/igcap/lazy/hk-full.png
node docs/scripts/industry-grid-lazy-pixdiff.js /tmp/igcap/base/industry-filtered.png /tmp/igcap/lazy/industry-filtered.png

# 件②沙箱测试(块从脚本原文 sed 提取,变量桩替换)
# 见报告「测试用例」表;核心管道: git log --format=%B BASE..HEAD | grep -oE '#[0-9]+' | sort -un 逐个对 pending-index 词边界匹配
```

- 输入依赖:本地 static-site/(含 min)+ R2 线上数据(industry-3m.json 等,周六静态不变)+ localhost 双 server
- 数据截止:2026-08-22(周末静态数据)
- 关键口径:viewport 1440x900 dpr1;动画冻结;长任务=PerformanceObserver longtask(>50ms);懒渲染只延迟 init 不改渲染结果
