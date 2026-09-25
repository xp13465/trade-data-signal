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

## commits
- `81e6ed06c` feat: 四档卡移入 KPI 行首张(源码 app.js + style.css)
- `b08a18945` chore: 重建 min + bump 版本串 v6-20260925-a617(产物)