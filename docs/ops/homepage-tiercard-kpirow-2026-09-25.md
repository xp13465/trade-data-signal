# 首页各指数四档卡移入 KPI 行首张(2026-09-25,用户拍板)

## 结论
首页「各指数四档状态」卡从全宽独立卡改为 **KPI 卡片行内首张 + 占 2 格宽 + 与 KPI 卡同高**。
只在 `feat/homepage-tiercard-kpirow` 分支(未 merge main),agent 只 push feat,merge 由主控 `scripts/main-merge.sh` 统一。

## 改动点
| 文件 | 位置 | 改动 |
|---|---|---|
| `static-site/app.js` | `_renderIndexTiersCard`(~12233) | 全宽 chart-card 形态 → 三行紧凑结构(`card-title`/`tier-value`/`card-sub`),8 色点复用 `_INDEX_TIERS_DOT_ORDER` 固定顺序,完整档位明细收进 hover `.tier-tooltip` 浮层;卡级 `title=_INDEX_TIERS_TIP` 保留(§21 公示位不丢) |
| `static-site/app.js` | 挂载点(~16425) | 删 grid 前置挂载,改 `cards.insertBefore(tier, cards.firstChild)` 插 KPI 行首位 + 插入后 `_applyKpiCollapse()` 重算折叠;`r.index_tiers` 缺失返回 "" 不渲染行为保持 |
| `static-site/app.js` | drag dragover/drop(~16342/16351) | 排除无 `data-kpi-key` 卡:四档卡固定首张、不可被当拖放目标,`kpiCustomOrder` 持久化不受污染 |
| `static-site/style.css` | `.card.kpi.tier-card`(~3032) | `flex: 2 1 300px; min-width: 0`。**必须 `.card.kpi.tier-card`(0,3,0) 才能覆盖 `.card.kpi`(0,2,0)**,单 `.tier-card`(0,1,0) 会被覆盖(踩过,已修);`tier-tooltip` hover 浮层复用 `.kpi-fg-tooltip` overlay 模式(absolute inset:0 + hover 显示) |

## 实测数字(Playwright 无痕浏览器,零 localStorage)
- **高度**:四档卡 `126.0px` vs 同行 KPI 卡中位 `126.0px`,差值 `0.0px`(≤4px 达标)
- **宽度**:四档卡 `334.9px`,2 格理论宽(1 格 ×2 + gap 12px)`346.8px`,比值 `0.97`(±10% 达标)
- **移动端 375**:四档卡独立一行 `351px`(无横向溢出),tierH `88px`(独立行不参与 stretch,视觉协调)

## 冒烟 8 条(脚本 /tmp/tier-kpirow-accept.mjs,正式 min 版)
1. 四档卡 KPI 行第一位 PASS
2. 高度差 0px PASS
3. PC 折叠 1 行四档卡完整可见 + 展开/收起 PASS
4. 拖拽排序变更+刷新持久化 PASS;拖到四档卡被忽略且四档卡仍首位 PASS
5. 移动端 375 无横向溢出、折叠可见 PASS
6. hover 显示 4 档具体指数 PASS
7. Console/页面零 error PASS(0 errors)
8. 回归:收盘分析横幅四档 chip 8 色点逐字未变 PASS(`科创50上升 / 5个主跌`)

截图留证:`/tmp/tier-pc-collapsed.png`、`/tmp/tier-pc-hover.png`、`/tmp/tier-mob.png`(脚本在 /tmp,未进生产)。

## §21 公示
纯布局改动,未动算法/判定源/文案语义(`_indexTiersSummarize` 未改,卡级 `_INDEX_TIERS_TIP` tooltip 保留)。无需改公示文案。

## §24 前端三件(同 commit 完成)
- `build_min.py` 重建 8 对 min 产物(PASS,机检 `check_version_consistency.py --site-dir static-site` §24⑤ PASS)
- `bump_asset_version.py`:版本串 `v6-20260924-a616 → v6-20260925-a617`
- `sw.js CACHE_VERSION` 同步为 `v6-20260925-a617`,index.html 各资产 `?v=20260925-a617` 一致
- **由 merge 后主控验线上**(agent 不 push main)

## 举一反三(§23.3)
`index_tiers` 消费点全站就 2 处:
- 首页四档卡(本次改造)
- 收盘分析横幅 `_renderIndexTiersChip`(~12308,**唯一 chip 调用点**,未动,已验证渲染逐字未变)

`_renderTierTimelinePanel`(~8920,沪深300 历史四档轨迹面板)不同功能,未碰。
「全宽独立卡内容偏少」同类候选(app.js 内 chart-card 渲染点,fx8 桌面首页上下层):`fg-dim-card`/`ma-card`/`position-card`/`freeze-card`/`sig-card` 等,是否同病需主控/用户评估,**本分支未改**。

## 待主控拍板/留意
1. 四档卡**不参与 KPI 拖拽排序**(固定首张、无 `data-kpi-key`),若用户希望它可排序需再做
2. 移动端四档卡独立一行(375 放不下 4 格+KPI),tierH=88 较 KPI(117)矮,视觉协调但非等高;若需等高可加 hero min-height,本次未加
3. 版本串 a616→a617 由 agent bump(main-merge.sh 机制 C 统一 bump 会在 merge 时再推进,无冲突风险)

## 审查整改(dragstart 守卫,2026-09-25)

### 背景
独立 reviewer(报告见同目录 `tiercard-kpirow-review-2026-09-25.md`)审出拖拽排序三个 handler 不对称:
`dragover`/`drop` 已用 `!c.dataset.kpiKey` 排除无 `data-kpi-key` 的四档卡作拖放目标,但 `dragstart`
没排除(四档卡理论上可被当作拖拽源)。reviewer 实测四档卡 `draggable` 设置时机在插入 DOM 之前、
从未被设为 `draggable=true`,真实用户拖不动它 → **低危纯防御性缺口**,无实际线上危害。

### 改动(一处,一行)
`static-site/app.js` KPI 拖拽排序 `dragstart` handler(worktree L16326-16328):
```
const c = e.target.closest(".card.kpi");
if (!c || !c.dataset.kpiKey) return; // 四档卡(无 data-kpi-key)不作拖拽源, 与 dragover/drop 同判据
_draggedKpi = c;
```
判据与 `dragover`/`drop` 的 `!c.dataset.kpiKey` **逐字一致**(同条件写法,未自创)。只改这一处逻辑,
未动折叠/布局/样式/其他 handler。

### §23.2 修 bug 三铁律自测
**同类错误面清单**:KPI 拖拽排序三个 handler(dragstart/dragover/drop)→ 本次补的正是 dragstart 这一侧;
`_kpiSortForRender`(排序应用)、`_syncKpiResetBtn`(重置)不涉及拖拽手势,已读码确认无同类缺口;
`tier-card` class 无其他 JS 消费者(§23.3 grep 复核,同 reviewer §八)。

**自测方式**:Playwright chromium 无痕(script `/tmp/playwright-pw/tiercard-guard-test.mjs`,
零 localStorage,route 注入线上 overview.json 到本地 server 8126,不碰生产 R2/不跑 deploy.sh),23/23 PASS:

| 组 | 断言 | 结果 |
|---|---|---|
| A 守卫两侧 | A1 四档卡 dragstart 被忽略(dragging class 未加) / A2 setData 未触发(null) / A3 真 KPI 卡 dragstart 照常(dragging 加了) / A4 真 KPI 卡 setData 触发(a_sentiment) / A5 零 pageerror | 5/5 PASS |
| B 拖拽回归 | B1 kpiCustomOrder 写入(len=29) / B2 DOM 改序生效(a_sentiment→idx2) / B3 持久化==DOM / B4 四档卡仍 DOM 首位+未入 kpiCustomOrder / B5 零 pageerror | 5/5 PASS |
| C PC 折叠 | C1 折叠态四档卡完整可见(tierH=126) / C2 折叠裁剪生效 / C3 展开后仍可见(126) / C3b 展开移除 collapsed / C4 零 pageerror | 5/5 PASS |
| D 移动 375 | D1 折叠态四档卡完整可见(tierH=88) / D2 无横向溢出(docW=375) / D3 展开后仍可见 / D3b collapsed 移除 / D4 零 pageerror | 5/5 PASS |
| E 刷新持久化 | E1 刷新后自定义顺序保持(savedLen=29) / E2 四档卡刷新后仍首位 / E3 零 pageerror | 3/3 PASS |

### §24 前端三件(同 commit)
- `build_min.py` 重建 8 对 min(PASS;worktree 下 build_min 因 `.git` 是文件 fallback 工作区源,
  刚 commit 工作区==HEAD,内容正确,已用「git HEAD 提取源→build_pairs_in_memory 同逻辑重建→md5 逐位比对」强对账:HEAD 重建 min md5 `6dc4e907` == 产物 app.min.js md5 `6dc4e907` 一致)
- `bump_asset_version.py`:版本串 `v6-20260925-a617 → v6-20260925-a618`
- `sw.js CACHE_VERSION` 同步 `v6-20260925-a618`,index.html 14 处 `?v=` about/guide/privacy 同步,无 a617 残留
- `check_version_consistency.py --site-dir static-site` 校验1/2 PASS、校验3 在 worktree 下因 `.git` 为文件解析不到 repo 而 skip(环境错位,同 reviewer §六 46 行预判),由上述手动同构对账等价覆盖 §24⑤
- **由 merge 后主控验线上**(agent 不 push main)

## 复现段
- **守卫被忽略(缺口存在时)**:对无 `data-kpi-key` 的四档卡 dispatchEvent `dragstart`
  (真实 `new DataTransfer()`)→ 旧版会设 `_draggedKpi`+加 dragging class+setData;新版无副作用。
- **守卫生效(修复后)**:上述操作四档卡 `dragging` class 未加、`dataTransfer` 内容为空(全 PASS)。
- **真拖回归**:对 `a_sentiment` KPI 卡 dispatch dragstart→dragover→drop(目标=fear_greed 右半)→
  DOM 顺序变化+`kpiCustomOrder` 写入 29 key,刷新后顺序保持(全 PASS)。
- 测试基准环境:`BASE_URL=http://localhost:8126`(本地 http.server serve worktree static-site,
  route 拦截 `**/data/boot.json`→`{config:{}}`、`**/data/overview.json`→线上 overview 20260924),零 localStorage admin。
- 执行:无痕 → `page.goto` → 等 12s 渲染 → evaluate 断言;确认页面 a618 版、tierH PC=126/移动=88 与 reviewer 一致。

## 待主控
- merge 后 §0 验线上:curl 线上 app.min.js 含 `tier-card` 字符串 + index 版本串 a618

## commits(全分支)
- `81e6ed06c` feat: 四档卡移入 KPI 行首张(源码 app.js + style.css)
- `b08a18945` chore: 重建 min + bump 版本串 v6-20260925-a617(产物)
- `02ecea62d` fix: dragstart 补 data-kpi-key 守卫(源码 app.js,审查整改)
- `272b63f01` chore: 重建 min + bump 版本串 v6-20260925-a618(产物,审查整改)