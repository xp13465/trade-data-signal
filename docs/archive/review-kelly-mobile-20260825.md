# #97 凯利回测页移动端方案B — Reviewer 审查报告(2026-08-25)

- 对象:分支 `feat/kelly-mobile-b` 三批 commit(`6d6456f75` A-iOS专项 / `8db606186` B-卡片化bottom-sheet列选择器 / `353f40ad2` C-数据切片),base `048173a7a`
- 方法:role-reviewer SKILL §10 四视角独立审(B级③广涉及面:跨前端+数据产物+R2)+ 置信度过滤(<80 滤除)
- **结论:PASS-with-fixes**(3 条 findings 均 ≥80,不阻断 merge;F1 必须在 merge 时点处置,F3 一行补丁建议随批)

## 一、实施方声称逐项独立复核

| # | 声称 | 复核结果 | 证据 |
|---|---|---|---|
| 1 | 桌面零变化 | **成立** | CSS 全部改动在 `@media(max-width:768px)` 内或断点值改写(>768 区间无规则变化);lab.js `_renderSigKellyCard` 桌面路径仅抽 `_sigKellyRowModel`,逐条比对与原局部变量计算/HTML 模板逐字一致;`colDefs` 15 列顺序==原硬编码拼接顺序(lab.js L11581),cells 对象化后桌面全列输出逐字节一致;移动-only DOM(mopen/sheet/grip/cols-btn)桌面不出现 |
| 2 | py 只加导出不动判定 | **成立** | +95 行=纯增 `_export_lab_slices` + argparse 纯增 `--export-lab-slices-only`(main() 开头 early return,不重跑回测) + 主流程 try-warn 调用(沿用既有 parts 导出同模式);回测判定/口径零触碰 |
| 3 | 切片正确性 | **成立(reviewed 独立重跑全绿)** | 用 feat 版脚本对生产树 trades.json(md5 `693f2d8d…`,主树==trade-data 权威树)独立重导:144 组/303 片/meta 24.8KB/max 280.5KB<300KB;**274,284 行逐组拼接==原数组逐位一致**;meta.groups 键集与 quadrants 非空组对称;每片 fields/bytes 记录准确 |
| 4 | 口径诚实标注 | **成立** | 三处明示用户:①⚡提示条「未应用降亏过滤/仓位控制/费率重算,数字为回测原始口径」②分页条「(快速预览)」③整包失败红色条「当前仅快速预览(未含…)」;预览 cutoff 过滤 `(buy_date||"")>=cutoff` 与整包第一层 `<cutoff return false` 逻辑等价;竞态防护两个 await 点(meta 后/拼接后)均检查 `state.labSigKellyTradesData` 先赢弃预览 ✓ |
| 5 | iOS 四件 | **基本成立(F3 除外)** | 16px:`.lab-sigkelly-fee-custom .lab-input` 后代选择器覆盖费率区全部 5 个 number input(L9413-9417)+yearly-mode-select+filter-etf/filter-profit;dvh 均有 vh 基线级联兜底(L1779 90vh/L1837 95vh→L2083 dvh);44px 清单在位;overscroll contain+safe-area 在位。**漏网:JS 断点判定 L9388 仍 600px → F3** |
| 6 | 静默失败可控 | **部分成立(F2)** | R2→CF 双层 fallback 有出口、整包失败有错误 UI+重试;但预览链路任一环失败被外层 catch 吃成 `return false`,零提示 → F2 |
| 7 | R2 上传合规 | **成立(附 F1)** | 上传产物与我独立重导产物结构零差异(唯一 diff=generated_at 时间戳);purge 321 keys = 304 lab 片+17 既有 recent/t{YYYY} 片,全在 `signal_kelly_trades_parts/` 前缀下,**无误伤其他前缀**;R2 当前整包与切片同为 05:01 版自洽 |
| 8 | §21 公示 | **无需公示确认** | 算法/判定零改动,purpose-notes.js 未动;新增 tooltip 文案口语化(「交易记录 ›」「往下拉关闭」「显示列(点勾选显隐,至少保留一列)」) |

## 二、Findings(≥80 进正式报告)

### F1(85)|lab 切片数据版本治理缺口:本地已混版,merge 前每次回测都会落后一版
- **现象**:R2 线上整包 generated_at=`2026-08-25 05:01`、R2 lab_meta=`05:01`(线上自洽 ✓ 当前无用户可见问题);但本地 `static-site/data/signal_kelly_trades.json` 已是 `06:41` 版(今晨盘前重跑),`signal_kelly_trades_parts/lab_meta.json` mtime=06:15 停在 05:01 数据版。
- **根因**:feat 分支的 main 版脚本尚无 `_export_lab_slices` 调用,今晨 06:41 重跑(main 版)只更新了整包;merge 前任何一次「回测重跑+deploy」都会把「新整包+旧切片」同时推上线 → 移动端预览数字≠正式表数字(§22 违反),且无机检拦截。
- **佐证**:smoke.md 复现段数据版本标 `2026-08-23 05:09`,与实物(05:01)不符——版本标注链条三处(文档/R2/本地)各说各话。
- **整改**:①merge 本 feat 后立即跑一次 `--export-lab-slices-only` 同步到最新版再 deploy;②把「lab_meta.generated_at == signal_kelly_trades.json generated_at」+「片数==meta.parts 数」挂进 check_data_integrity/deploy 链(check_r2_consistency 也未覆盖该目录)。

### F2(80)|预览链路失败静默降级,弱网下卡 loading 无任何可见提示
- **证据**:`_sigKellyOpenTradesPreview` 整个包 try-catch,任一环失败(meta 404/片超时/JSON 解析错)`return false` 零痕迹;界面停留「⏳ 加载交易记录…」等 62MB 整包(移动端可达数十秒)。整包失败有错误 UI,但「预览已死+整包慢」中间态用户不可感知——移动端首屏提速这一核心卖点失效时无人知道。
- **整改**(一行级):预览失败时往 loading 容器追加一行「快速预览不可用,完整数据加载中…」,不改降级逻辑只补可见性。

### F3(80)|断点统一不彻底:`_renderSigKellyBar` 参数面板默认展开判定仍是 600px
- **证据**:feat 版 lab.js L9388 `matchMedia("(max-width: 600px)")`;而吸顶条折叠 CSS 段已随批次 A 改为 768。601~768 区间(iPad 竖屏/大屏手机)=CSS 移动折叠样式+JS 默认展开态,与 ≤600 行为不一致,也与 commit 自述「断点600·760统一768」矛盾。此错位由本次 diff 引入(CSS 改了 JS 没跟),非 pre-existing。
- **整改**:L9388 的 600 改 768(一行),或抽用 `_sigKellyIsMobile()`。

## 三、低分项(<80)已滤:6 个
①smoke.md 记录 A/B 批次 hash(f2cd6c219/b1673763e)与最终分支 hash 不符(rebase 后未同步,40)②details summary/cols-item 触控目标 32px<44 HIG(50)③matchMedia hook 挂载点在 renderSigKellyLab 中部、early return 时延后挂(30)④跨断点旋转重绘丢 details 展开态/滚动位置(35)⑤localStorage 空 catch 隐私模式记忆失效静默(25,惯例可接受)⑥预览表字段直读无格式化与正式表观感不同(提示条已声明,30)

## 四、pre-existing / 冻结契约核查(§23.7⑤)
- 无需上报的历史遗留新发现。「all 伪象限标题显示裸 all」为既有行为且预览/正式表一致,不动。
- 桌面 >768px 行为冻结成立(§23.7);非 sigkelly 组件的 6 个既有 600 断点(rank/signal/retest/fusion 等)未被顺手改动,符合最小改动原则。
- 举一反三:601~767 平板区间 sigkelly 与其他 lab 组件移动化断点暂不一致(前者 768/后者 600),属历史现状,本次只统一 sigkelly 自身,正确。

## 五、验收硬项小结
- 数据完整性:切片独立机检全绿(274,284 行逐位一致/键集对称/meta 一致);check_data_integrity 覆盖缺口见 F1
- §22 一致性:R2 当前自洽;混版风险见 F1
- smoke 四件套:报告本体+冒烟脚本 kelly_mobile_smoke.js/kelly_mobile_preview_diag.js+复现段齐,git tracked(feat 分支 blob 100644)
- 机检命令与输出见下方复现段

## 复现

```bash
cd /Users/linhuichen/code/trade

# 1) 独立重导切片(feat 版脚本, 读生产树 trades.json, 不重跑回测):
mkdir -p /tmp/rev-slices/data && cp static-site/data/signal_kelly_trades.json /tmp/rev-slices/data/
git show feat/kelly-mobile-b:scripts/signal_kelly_backtest.py > /tmp/rev-slices/skb_feat.py
PYTHONPATH=$PWD/scripts python3 /tmp/rev-slices/skb_feat.py --export-lab-slices-only \
  --trades-output /tmp/rev-slices/data/signal_kelly_trades.json
# 输出: 144 组 / 303 片 + lab_meta.json (24.8 KB)

# 2) 全量机检(逐位拼接==原数组 + 键集对称 + meta 字段一致 + bytes 准确 + 与上线目录 md5 对比):
#    校验脚本见本报告配套(内嵌于 review 会话, 关键断言): rows!=orig 即 FAIL;
#    本次实测: 组数144 片数303 总行274284 最大片280.5KB, 错误数0; md5 差异304 个文件,
#    逐字节排查唯一差异字段=generated_at(06:41 vs 05:01), 结构零差异 => F1 版本错位实证。

# 3) R2 线上版本核对(curl 带 UA, 不带 -v/-i 防 token 泄漏):
curl -s -A "Mozilla/5.0" "https://ss.fx8.store/data/signal_kelly_trades.json" | head -c 120   # 整包 generated_at
curl -s -A "Mozilla/5.0" "https://ss.fx8.store/data/signal_kelly_trades_parts/lab_meta.json" | head -c 120

# 4) 断点残留/F3 证据:
git show feat/kelly-mobile-b:static-site/lab.js | grep -n 'max-width: 600px'   # L9388
git show feat/kelly-mobile-b:static-site/lab.css | grep -nE 'max-width: *(600|760)px'  # 余6处均非sigkelly组件
```
- 输入依赖:`static-site/data/signal_kelly_trades.json`(md5 `693f2d8de60e19781e32479ee6cfa537`,主树==trade-data 权威树)+ feat 分支 lab.js/lab.css/py
- 数据截止:trades.json generated_at=2026-08-25 06:41(本地)/05:01(R2 线上)
- 关键口径:切片=(象限×模式)组内保持原序按「≤2000行 且 ≤280KB UTF-8字节」先到为准切 chunk,拼接==原数组逐位一致;预览=cutoff 过滤直读原始字段,不含 fade/positionCap/费率重算
