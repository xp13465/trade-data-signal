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

## reviewer fixes 回归(review-kelly-mobile-20260825.md F1/F2/F3,2026-08-25)

- **F3 断点统一**:`_renderSigKellyBar` 参数面板默认展开判定改抽 `_sigKellyIsMobile()`(768,与吸顶折叠 CSS/卡片化同源),原 600 致 601~768 区间「CSS 已折叠+JS 默认展开」错位。自验:390 宽清 localStorage → toggle=「⚙️ 参数 ▼」收起态+无 `lab-sigkelly-params-open` class;1280 宽 → 照旧展开(periodBtn display=block)。
- **F2 预览失败可见化**:预览链路 catch 不再零提示——loading 态插红色提示条「⚠️ 快速预览不可用（切片加载失败），正在后台加载完整数据…」(复用整包失败红条样式 rgba(220,53,69,.12));降级逻辑未动。自验(Playwright route:meta abort+整包延迟):t1.5s 红条与 loading 共存 ✓ → 整包就绪 t10.5s 正式表渲染、红条零残留 ✓;整包先就绪/整包失败 UI 在场时不插条(竞态防护)。
- **F1 机检**:check_data_integrity.py 新增 `check_kelly_lab_slices`——lab_meta.generated_at ⟂ 整包 generated_at 混版 FAIL、片缺失/残留孤儿片 FAIL、无切片 WARN 兼容老环境;三路径实测(生产树混版当场拦下 / tmp 同版 144组303片 OK / 无 meta WARN)。merge 后由主控跑 `--export-lab-slices-only` 同步切片(混版即解除)。
- **桌面零变化复验(fix 后)**:同数据源下 fix 版 vs git HEAD 版 `.lab-sigkelly-host` outerHTML hash 一致(`5c194994`,双版本对照法排除数据版本因素)。
- ⚠️ 测试坑注记:本站有 Service Worker(CacheFirst),Playwright `page.route` 拦不到 SW 发起的请求——做网络失败/弱网模拟必须 `newContext({ serviceWorkers: "block" })`,否则 meta"abort"实际被 SW 放行成功、断言全歪(本次 v1/v2 假阴性根因)。

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

# reviewer fixes 自验(2026-08-25; F2 失败窗口+F3 断点, 需先起上面冒烟服务):
node docs/kelly/scripts/kelly_fix_f2f3_window.js   # F3 移动收起态 + F2 红条/loading 共存(serviceWorkers:"block" 必须)
node docs/kelly/scripts/kelly_fix_f2_replace.js    # 整包就绪后正式表替换红条零残留
python3 scripts/check_data_integrity.py --data-dir /Users/linhuichen/code/trade-data/static-site/data  # F1: 本地混版应 FAIL(exit 1), merge 后同步切片转 OK
```

- 输入依赖:signal_kelly_trades.json(2026-08-25 冒烟时生产树版本 generated_at=2026-08-25 05:01, 与当时 R2 切片同版; 当日 06:41 盘前重跑后本地整包已更新而切片停在 05:01 = review-kelly-mobile-20260825.md F1 混版实证, merge 后跑 --export-lab-slices-only 同步)、static-site/lab.js·lab.css(worktree feat 分支)。
- 关键口径:切片=象限×模式组内保持原序按「≤2000行 且 ≤280KB(UTF-8字节)」先到为准切 chunk,拼接==原数组;预览=cutoff 过滤后原始字段直读。
