# 四档卡移入 KPI 行首张 · 独立审查报告(reviewer, 2026-09-25)

分支: feat/homepage-tiercard-kpirow @ e0f47a24e(3 commit: 81e6ed06c 源码 / b08a18945 build+bump / e0f47a24e 落档)
基线: main 729356692。审查方式: 只读 + 独立 Playwright 无痕实测(零 localStorage,脚本 /tmp,未碰生产 R2/生产路径)。

## 结论: 带条件 PASS(几何/折叠/回归全 PASS; 1 条低危建议 + 1 条观感待用户)

## 一、几何事实(我自己实测, 未复用 implementer 脚本)
条件: Playwright chromium 无痕, 线上 overview.json(20260924, 含 index_tiers)注入本地 server, 1280x900。
- **高度**: 四档卡 126.0px vs 同行 KPI 卡(第一行 5 张)全部 126.0px → **差值 0.0px** ✓(与 implementer 报一致)
  - 注意: 第二行起的某些卡(如 sentiment_csi500/high_alert/gold 等)高 141px, 因内容多 2 行——但这些**不在四档卡所在行**, 与同高要求无冲突。
- **宽度**: 四档卡 334.86px vs 2 格理论宽 = 首行 KPI 均宽 167.43×2 + gap12 = 346.86px → **比值 0.965**(±10% 达标)✓(implementer 报 334.9/346.8 → 一致)
  - 说明: 0.965 不是正好 2 格, 因 flex:2 1 300px 的 grow/shrink 按容器剩余空间分配, 比纯 2×KPI 略窄。**观感是否可接受由用户拍板**。
- 移动端 375:tierW 351px / tierH 88px 独立一行(首行无 KPI 卡相伴), 无横向溢出 ✓(与 implementer 报完全一致)
- 首卡位置: 四档卡是 .cards.kpi-row 第一个子元素,KPI 行首位 ✓

## 二、折叠逻辑(头号风险区, 实测 5 项)
1. PC 折叠 1 行:maxHeight=138px, 四档卡可见高 = 126px = 完整高度, value(58px)/sub(80px) 全部在卡内未被裁 ✓
2. 展开↔收起交替 5 轮: 状态稳定交替(collapsed/expanded 互换), 按钮文字同步, 零 console/page error ✓
3. resize 跨断点 1280→375→1280: 375 下 88px 完整可见无溢出, 回 1280 恢复 126px 折叠态, 无卡死错误高度 ✓
4. 移动端 375(4 行阈值): 折叠态四档卡 88px 完整可见, 点按钮展开正常 ✓
5. 边界: 29 张 KPI 卡场景已测; 卡数少(仅几行)时 _kpiCollapsedMaxHeight 返回 null 不裁剪(逻辑读码确认);
   - 注: "只有 1 张 KPI 卡"极端场景未实测(线上数据 29 卡), 但折叠逻辑不依赖具体卡数, 风险极低。

## 三、拖拽排序(4 项实测)
1. 拖 KPI 卡 a_sentiment 到第 4 位: 顺序变更生效, kpiCustomOrder 写入(29 个 key 全量), 刷新后顺序持久化 + 四档卡仍首位 ✓
2. 拖 KPI 卡到四档卡上: drop 被忽略(c.dataset.kpiKey 缺失短路), 不报错、不丢卡、四档卡仍首位 ✓
3. kpiCustomOrder 只含真 KPI key(29 个, 无四档卡污染)✓
4. 旧用户已有 kpiCustomOrder(模拟逆序存旧键): _kpiSortForRender 的 valid.length===kpiCards.length 校验通过(四档卡不在 kpiCards 里), 自定义顺序生效 + 四档卡仍首张 ✓
5. **dragstart 缺口(低危)**: 源码 dragstart handler 未排除无 data-kpi-key 卡, 理论上四档卡可被当拖拽源移走(tierPos 变 2)。但我实测 `tierCard.draggable = null(falsy)`——draggable 设置在四档卡插入 DOM **之前**执行, 四档卡从未被设 draggable=true, **真实用户拖不动四档卡**, 攻击面不成立。属防御性缺口, 建议后续把 dragstart 也加 `!c.dataset.kpiKey` 守卫(一行)。

## 四、回归(逐字比对)
- `_renderIndexTiersChip` 函数体: main vs feat 逐字一致 ✓(8 色点 + title=《8 宽基四档口径》)
- 线上实测横幅 chip: 8 色点 + 「科创50上升 / 5个主跌」 ✓(与 implementer 报一致)
- `_indexTiersSummarize` / `_renderTierTimelinePanel`: 逐字未变 ✓
- app.js diff 仅 4 个 hunk(卡片模板 / dragover / drop / 挂载点), 无一碰判定逻辑

## 五、旧产物兼容
r.index_tiers 缺失(route 删字段重放): 四档卡完全不渲染(KPI 行 29 卡正常, 折叠正常, 无溢出, 零 console/page error)✓
注: 首次 route 模式 `**/data/overview.json` 未匹配带 `?_=` 的 URL(Playwright glob 语法), 换正则后正确。实施若用 route 同样注意。

## 六、§24 三件(同 commit build+bump 验证)
- min == 源一致: 用 build_min 同逻辑(build_pairs_in_memory)从 feat HEAD 源重建, app.min.js md5 af2b3484 == feat 分支文件 ✓; style.min.css a7489ade == ✓
- 版本串: index.html 14 处 ?v= 全部 20260925-a617, about/guide/privacy 同步, 无 a616 残留 ✓
- sw.js CACHE_VERSION = v6-20260925-a617, 与 index 版本串一致 ✓
- 注: check_version_consistency.py 在非 feat worktree 直接跑会对 feat 产物报 FAIL——这是**环境错位**(脚本从 git HEAD 读源, 本 agent worktree HEAD=main), 非真问题; 在 feat worktree 上跑或 merge 后跑即正确。

## 七、§23.7 冻结契约 / §21 公示
- diff 只动布局(模板/CSS/挂载点/拖拽保护), 未动 tier 判定逻辑、未动 _INDEX_TIERS_TIP 文案(卡 title 保留原公示语)✓
- purpose-notes.js 不在改动面 ✓; 无需 §21 公示同步 ✓

## 八、举一反三复核(grep 独立验证)
- `index_tiers` 全站消费点 = 2 处: `_renderIndexTiersCard`(本次改) + `_renderIndexTiersChip`→renderSummaryChips(横幅, 未动)✓; lab.js 无消费。implementer 清单可信。
- `tier-card` 类仅本次 CSS 定义 + 新卡模板使用, 无其他 JS 消费者 ✓
- 「全宽卡内容偏少」候选(fg-dim-card L16531 / sig-card L16619 / ma-card / position-card / freeze-card)均为真实 chart-card 族(flex column 全宽), 清单**非拍脑袋** ✓; 本分支未改它们, 合理。

## 九、发现(按严重度)
1. **低危·防御缺口**: dragstart handler 未排除无 data-kpi-key 卡(与 dragover/drop 不对称)。当前无实际危害(四档卡 draggable=false, 实测真实鼠标拖不动), 但未来若有人给四档卡设 draggable 或加载顺序变化会踩坑。建议加一行 `if (!c || !c.dataset.kpiKey) return;`。复现: 仅能通过手动 dispatchEvent 伪造 dragstart 触发(实测 tierPos 变 2), 真实鼠标无法拖动四档卡。
2. **低危·观感/信息可及(待用户拍板)**: 移动端(触屏)tap 浮层显示正常(opacity 1/visible), 无显式关闭交互(再 tap 他处消失)。观感是否够好由用户判断, 不作为 FAIL。
3. **低分项(已滤, <80)**: 宽度 0.965 非正好 2 格(仅观感); 四档卡不在 _kpiCanDrag 拖拽集(有意设计); 无其他。

## 十、实测数字 vs implementer
| 项 | implementer | 我实测 | 一致 |
|---|---|---|---|
| PC 高度差 | 126.0 vs 126.0 (0.0) | 126.0 vs 126.0 (0.0) | ✓ |
| PC 宽度 | 334.9(比值0.97) | 334.86(比值0.965) | ✓ |
| 移动 375 | 351px/88px 独立行 | 351px/88px 独立行 | ✓ |
| 折叠可见 | 完整 | maxH138 完整126 可见 | ✓ |
| chip 文案 | 科创50上升/5个主跌 | 同 | ✓ |

## 十一、待主控决策
- 无必须拍板项。建议:(a) dragstart 一行守卫可顺手补(下个前端改动的 commit); (b) 宽度 0.965 与"2 格"有 3.5% 差距, 用户肉眼判断是否满意。
- §0 上线验证(主控): merge 后 curl 线上 app.min.js 含 `.tier-tooltip` 或 `tier-card` 字符串 + overview.json index_tiers 在位 + 移动端实测。

---

## delta 复验(2026-09-25, 追加)

针对 dragstart 守卫整改(3 commit: 02ecea62d 源码 / 272b63f01 重建min+bump / 38267de12 落档)的定向复验。
复验环境: 本 reviewer worktree `git checkout 38267de12`(detached 只读), 独立脚本 /tmp/delta-check.js + /tmp/delta-reload.js, 本地站点 /tmp/tier-review-site-delta(38267de12 前端 + 线上 overview.json), Playwright 无痕零 localStorage。

### 1. 三处守卫判据逐字对比(grep -A2 原始行)
- dragstart(L16328): `if (!c || !c.dataset.kpiKey) return; // 四档卡(无 data-kpi-key)不作拖拽源, 与 dragover/drop 同判据`
- dragover(L16342): `if (!c || !c.dataset.kpiKey) return; // 四档卡(无 data-kpi-key)不作拖放目标, 固定首张`
- drop(L16351): `if (!c || c === _draggedKpi || !c.dataset.kpiKey) return; // 四档卡(无 data-kpi-key)不作拖放目标`
- 结论: 判据逐字一致; drop 多出的 `c === _draggedKpi` 为防自拖(drop 特有语义, 非判据分歧)。

### 2. 独立复跑(自己脚本)
- [D1 PASS] 真 KPI 卡 dragstart: a_sentiment 拖到第 4 位 → 顺序变更生效, kpiCustomOrder 写入 29 key
- [D1.5 PASS] 刷新后: 渲染顺序 cross_market,fear_greed,a_sentiment,a_width_up_count == stored 前 3 一致, 四档卡仍首位
- [D2 PASS] 四档卡 dragstart 被忽略: dispatchEvent 伪造 dragstart 后 `.dragging` 未出现(dragstart 提前 return, _draggedKpi 未设), tierPos 保持 0, 未移位 → **修复前此场景 tierPos 会变 2, 现守卫生效**(修复验证闭合)
- [D3 PASS] PC 折叠: collapsed=true, maxH=138px, 四档卡可见 126px=完整
- [D4 PASS] 移动 375: collapsed=true, 可见 88px=完整, overflow=0
- [D5 PASS] 零 pageerror / console error
- [D6 PASS] 旧产物(route 删 index_tiers): 四档卡不渲染, KPI 行 29 卡正常, 零报错

### 3. §24 链复验(自己算 md5)
- build_min 同逻辑从 38267de12 git HEAD 源重建: app.min.js **6dc4e907**(rebuild)== 仓库文件 6dc4e907 ✓(实施报的 6dc4e907 独立核实一致)
- style.min.css: rebuild **a7489ade** == 仓库文件 a7489ade ✓(本次只改 app.js, style 未变, 合理)
- 版本串: index.html 14 处 `20260925-a618`, about/guide/privacy 各 2 处, sw.js 1 处; `a617` 残留 grep 全站 0 ✓
- sw.js: `CACHE_VERSION = 'v6-20260925-a618'` 与 index 版本串一致 ✓

### 4. 新发现
- 无新增问题。原报的 dragstart 防御缺口已按建议修复, 判据与 dragover/drop 完全对齐。
- delta 复验结论: **PASS**, 可进入 merge 流程。
