# #97 信号凯利回测页移动端方案B — 实施与冒烟记录(2026-08-25)

方案文档: `docs/kelly/mobile-refactor-plan-20260826.md`(用户拍板根治路线)。本记录 = 三批次实施结论 + Playwright 冒烟证据,只记事实层(结构/几何/网络),观感留用户。

## 三批次 commit

| 批次 | commit | 内容 |
|---|---|---|
| A iOS 兼容 | `f2cd6c219` | 费率输入 font-size≥16px(防 iOS 聚焦缩放)/vh→dvh 级联/触控目标≥44px/overscroll-behavior-x:contain/safe-area-inset-bottom/sigkelly 区断点 600·760 统一全站 768 |
| B ≤768px 重排 | `b1673763e` | 卡内15列宽表→卡片化条目(半凯利仓位/胜率/最终盈亏/峰值资金收益率 4 关键列直读+details 收其余10项)/明细弹窗 bottom-sheet 抽屉(把手下拉关闭+首列冻结)/列选择器(localStorage 记忆默认8关键列) |
| C 数据切片 | (本批 commit) | signal_kelly_trades.json 62MB 按象限×模式预切片(144组/303片 max 280.5KB)+移动端弹窗预览快路径+整包后台懒加载 |

## 桌面零变化证明(验收硬项)

- Playwright 桌面 1280x900 渲染 `.lab-sigkelly-host` outerHTML 自定义 hash:改造前基线 `he5bffb1e`,批次A/B/C 后每次冒烟均 = `he5bffb1e`(逐字节一致)。
- 弹窗正式表 HTML:批次A 基线 modalHtml 24086 字节(30 个 th),批次C 后桌面弹窗仍走整包全口径(net.slices=0),列选择器按钮等移动-only DOM 不出现。
- CSS:全部改动位于 `@media (max-width:768px)` 断点内或新增类(仅移动 DOM 出现);断点外样式 diff 为空。

## 移动端冒烟断言(390x844 hasTouch,全部 PASS)

mrowCards=153 / legacyWideTables=0 / kpiCellsFirstCard=4 / detailItems=10 / sheetClass 含 lab-sigkelly-sheet / sheetGeom w=390 bottom=844=vh(贴底) / visibleCols=16(主表8+淘汰表8,默认8关键列生效) / colsBtn=true / frozenFirstCol=sticky / colsPopItems=15 / visibleColsAfterAdd=18(勾选加列链路) / closeBtnH=44 / inputFont=16px / gripPresent=true / noHorizOverflow=true。pageerror=0。

## 批次C 切片实测与机检

- 体积:304 个文件(303 片 + lab_meta.json 24.8KB),总量 62.5MB,**max 280.5KB < 300KB**,中位 280.3KB。
- 机检(PASS):144 组全部「片拼接 == 全量原数组」逐位一致(274,284 行零差异);meta 键集与实际 quadrants 非空组对称。
- 上传:`REPO=/Users/linhuichen/code/trade-data python scripts/upload_r2.py upload-kelly-parts`(复用既有 upload-kelly-parts 的 *.json glob,零上传端改动;前端 R2 直链→CF ./data 兜底)。
- 弱网链路诊断(kelly_mobile_preview_diag.js):route 拖慢整包 6s → 2.5s 时预览表已渲染(⚡快速预览提示条+明细行);整包就绪后自动替换为正式表(cols-btn 出现、提示条消失);R2 失败 CF 兜底逐文件生效。
- 竞态防护:切片拉取任一 await 点后检查 `state.labSigKellyTradesData`,整包先就绪则弃用预览让正式表接管(本地快网"整包先赢"属预期降级,线上弱网预览必现)。

## 口径诚实标注

- 移动端预览态**不含**降亏过滤(fade)/仓位控制(positionCap)/费率重算——三者依赖跨象限 dims 与基笔池,预览仅按周期 cutoff 过滤后直读回测原始字段,提示条已向用户明示;整包就绪后最终口径与桌面逐位一致(§22)。
- 卡片区统计本身仍需整包(进 tab 即后台拉取),这是口径要求;批次C 加速的是「弹窗首开」这一最大用户痛点场景。
- 桌面 >768px 行为冻结(§23.7):未改任何桌面控件/DOM/样式,列选择器等新控件仅移动 DOM 出现。

## 复现

```bash
# 冒烟服务(static-site 拷贝 + data 软链生产树):
cp -r static-site /tmp/kelly-smoke && ln -s /Users/linhuichen/code/trade-data/static-site/data /tmp/kelly-smoke/data
sed -i '' 's/lab\.min\.css?v=[^"]*/lab.css/g; s/lab\.min\.js?v=[^"]*/lab.js/g' /tmp/kelly-smoke/index.html
(cd /tmp/kelly-smoke && python3 -m http.server 8123 &)

# 切片重导(不重跑回测, 读生产树 trades.json):
python3 scripts/signal_kelly_backtest.py --export-lab-slices-only \
  --trades-output /Users/linhuichen/code/trade-data/static-site/data/signal_kelly_trades.json
# 输出: static-site/data/signal_kelly_trades_parts/lab_{quad}__{mode}_p{n}.json + lab_meta.json

# R2 上传:
REPO=/Users/linhuichen/code/trade-data python scripts/upload_r2.py upload-kelly-parts

# 冒烟(desktop=桌面零变化对比 / mobile=移动断言):
node docs/kelly/scripts/kelly_mobile_smoke.js desktop /tmp/kelly-desktop.json
node docs/kelly/scripts/kelly_mobile_smoke.js mobile  /tmp/kelly-mobile.json
# 依赖: playwright(npm i playwright + npx playwright install chromium)

# 预览弱网链路诊断:
node docs/kelly/scripts/kelly_mobile_preview_diag.js
```

- 输入依赖:signal_kelly_trades.json(2026-08-25 生产树版本, generated_at=2026-08-23 05:09)、static-site/lab.js·lab.css(worktree feat 分支)。
- 关键口径:切片=象限×模式组内保持原序按「≤2000行 且 ≤280KB(UTF-8字节)」先到为准切 chunk,拼接==原数组;预览=cutoff 过滤后原始字段直读。
