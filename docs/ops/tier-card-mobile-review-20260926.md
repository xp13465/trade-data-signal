# feat/tier-card-mobile-height 独立审查报告(reviewer, 2026-09-26)

分支: feat/tier-card-mobile-height @ 5aa9ed5ec(base = main ebec809ea),只动 static-site/style.css +12 行。
审查方式: 只读 + 独立 Playwright(线上 ss.fx8.store 数据 + route.fulfill 拦截 .css 换分支文件), 不信任实施 agent 自述。

## 结论: 可 merge(附带 1 条低危 self-report 失实 + 1 条低危魔数耦合建议 + 1 条注释残留待收尾)

## 必查项证据

### ① 最坏情形: 实测 vs 推算 —— 半推算, 且 320/375 真最坏 cutBy≠0(self-report 失实, 但文字零裁切)
- 线上数据(2026-09-26)只有 3 档有人(熊市·主跌 5 / 下降期 2 / 上升期 1),**不含"4 档全有人"**,因此实施 agent 的「cutBy=0 最坏」对线上数据是真的(实测 320/375/390/414 全 cutBy=0)。
- 但「4 档全有人」属**推算外推**:其自带 tier-4tier-probe.mjs 只测了 375(4 指数行不换行 → cutBy=0);320 最坏未真测。
- **reviewer 独立构造真最坏**(4 档全有人 + 一档 5 指数 = 对齐现网「一档 5 指数」分布, 8 个追踪指数 5/1/1/1):
  - 320px: tierH=117 / tooltip 自然高 123.94 / **cutBy=3**(scrollH−clientH)
  - 375px: tierH=117 / 自然高 123.94 / **cutBy=3**
  - 414px: 自然高 107.75 / cutBy=0
- **但文字零裁切**(375 最坏逐元素量): 末行 bottom 1019.53 < 容器 bottom 1023.06(整行含文字全可见, 可见高 35.91 > 行高 32.38);title top 909.59 全可见。3px 溢出只吃 padding(justify-content:center 上下对称 3.5px, 两侧 padding 各 7px 吸收)。
- **判定**: 功能上够(文字无裁切), 但实施 agent 报给主控的「320 最坏 cutBy=0」**不实**(实际 3)。代码注释倒诚实(≈123px 可接受轻微富余)。**建议**: 记录修正为「最坏 4 档全有人 320/375 自然高≈124px, 溢 3px 只入 padding, 文字零裁切」;若追求零溢出可把 min-height 提到 ~124px 或水平 padding 12→10 让 5 指数行 375 不换行(非必改)。

### ② 魔数耦合(min-height: 117px)—— 可接受, 建议加变量
- 117 是相邻 KPI 卡行高硬编码;移动端四档卡被 flex-wrap 挤单行, `align-items:stretch` 只对同行生效,**无法天然等高**(这是本次修复的根因), 因此写死像素是当前最简正解。
- 更稳写法评估: `--kpi-card-min-h:117px` 共享变量仍要硬编码 117, 耦合只搬位置;真联动需 KPI 卡高度由同 token 驱动(现为内容驱动: padding 10 12 + card-value 20px), 属结构性改造, 不值得为本次小改引入。
- 现有注释已详述耦合背景, **警示充分**;建议(不实施): 后续若动移动端 .card.kpi padding/字号, 顺手核对 117;或抽 var 便于单点改。

### ③ 移动端限定严密性 —— PASS
- 四条规则(L4005-4008)全部在 `@media (max-width: 768px)` 块内(L3930 开、L4155 下一块前), 无漏出。
- 桌面 1280 独立改前(base ebec809ea 抽出 CSS)/改后逐位一致: tierH 126=126, kpiH 126=126, sameRow true, cutBy 0, detailRows [18,18,36], tierTop 549.90625。**零回归确认**。

### ④ 同类排查复核(§23.3) —— PASS(一处小不实)
- 全仓 grep `.tier-card/.tier-tooltip/.tier-detail-row/.tier-tooltip-title`: 消费点仅 style.css(L3033-3056 基 + L4005-4008 新)与 app.js L12244/L12246(`_renderIndexTiersCard` 一个函数内)。lab.js/common.js/purpose-notes.js/sw.js/index.html 的 "tier" 命中全是无关的 kelly_tier/market_tier/track_tier/仓位档位。
- 实施 agent 说「app.js:12246 一处」——实际是 12244(detail 行模板)+12246(卡模板)两处, 同函数内, 不实质。
- 残留: 本次注释写「#74 四档卡移动端」,但 #74 属模块三已完成(首页模拟回测弹窗), **引用过期任务号**——pending-index #115 已登记「待收尾同批顺手改掉」,随本分支上线会带上, 属注释级低危。

### ⑤ 浮层全局节奏副作用 —— 可接受
- 正常 2~3 档情形(线上实测): 行高 16.19px(12px 字号 1.35 行距), gap 3, padding 7/12, title margin 1——密度略升但 1.35 行距仍在可读区间(≥1.2), 无过挤;自然高≈105px < 117px 有富余。收紧是本次修复的必要组成部分(压浮层自然高), 副作用可控。

### ⑥ §21 公示 —— 无同步点(核实)
- 纯 CSS;app.js/purpose-notes.js 零改动;四档算法(`_indexTiersSummarize`/后端 classify)与 `_INDEX_TIERS_TIP` 文案未动。无公示点需同步。

### ⑦ §24 前端发版链 —— PASS
- worktree git status 干净;commit 只含 style.css(+12)。
- style.min.css 未含新规则(grep `min-height:117px` = 0), 构建产物未混入 commit;版本串未 bump——符合机制 C(main-merge.sh 统一 build_min+bump)。主控 merge 后须补验 §0③(线上 style.min.css 含新规则)。

## finding 清单(按严重度)
1. **[低危] self-report 失实**: 「320 最坏 cutBy=0」不实(实测 3);文字零裁切故功能 OK。trace: style.css L4005 / 分支 commit message;verifier: /tmp/tier-reviewer-worst2.mjs + /tmp/tier-reviewer-textcheck.mjs(实测数字见上)。
2. **[低危] 魔数耦合**: min-height:117 硬编码 KPI 行高, 未来 KPI 卡字号/padding 变更会静默失配;注释已警示, 建议抽 var 或后续核对(不实施)。
3. **[注释级] 过期任务号 #74**: 注释引用已完成任务 #74, pending-index #115 已登记待收尾。
4. 其余必查项全 PASS(③④⑤⑥⑦)。

## 复现段
- 改前/改后全宽度: `node scripts/playwright-accept/measure-tier-card-static.mjs <style.css> 320 375 390 414 1280`(live 3 档): 改后 tierH=117=kpiH(cutBy 0)于 320-414, 1280 126=126 零回归。
- 最坏构造: `/tmp/tier-reviewer-worst2.mjs`(注入 index_tiers 5/1/1/1)→ 320/375 cutBy=3、414 cutBy=0;文字可见性: `/tmp/tier-reviewer-textcheck.mjs` → 末行全可见。
