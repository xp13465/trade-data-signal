# README 精简(按 stash@{1} 意图重做,2026-10-09)

> 任务:「按 `stash@{1}` 的意图重做 README 精简(用户已拍板;只做 README 这一件)」。
> 归属:docs/ops/(运维/一次性操作报告)。来源:docs/ops/disk-cleanup-batch2-20261009.md §③ 的后续小任务。
> 分支:worktree-agent-a26a585537f5c637c(base=16dfee5aa,base-fresh)。**未 apply/pop/drop/save 任何 stash(全程只读 `git stash show` / `git diff stash@{1}^1 stash@{1}`)**。

## 结论一句话

**只做「删 5 条描述」这一件,已完成(README −5 行);H 档数字不动(现网/README 均为 230.83%,stash 的 224.92% 是过时值);stash 里的其余 README 改写(FAPI 行/回测买入价行/模拟回测行/verify_sigkelly 段)与全部非 README 项(plist 整删/版本串/TASKS 头句/accum_nav_map)一律不做。**

## 一、逐条核对结果(删/不删 + 理由)

核对方式:①在**当前 main(HEAD=16dfee5aa)** 里 grep 确认 5 条仍在(5 条全部在,行号 64/82/83/460/461);
②在代码/数据产物里确认对应功能/工具**是否仍存活**(全部存活,即描述**仍然有效**,无一条过时)。

| # | 条目(当前 README 行) | 现状核对(是否仍存活) | 判定 | 理由 |
|---|---|---|---|---|
| 1 | `#101 北交所宽度独立指标`(A 段功能,行 64) | 存活:`config/indicators.yaml` + `scripts/fapi_bj_width_export.py`/`backfill_mootdx_from_fapi.py`/`fapi_daily_syn.sh` + `static-site/app.js`/`purpose-notes.js` 均有 `a_bj_*`;README「同花顺 FAPI」数据源行(删后行 315)仍保留「北交所 920 段 341 只日线源(独立 30% 档宽度 a_bj_* 指标)」 | **删** | 描述有效,但属「市场宽度」的**子指标细节**(341 只/30% 档/6m 分位/sparkline 等实施级措辞),非 README 主干;且「北交所独立宽度」概念在 FAPI 数据源行仍有保留(未全丢)。⚠️**本组里最「贴功能」的一条**,详见 §三 备注(保留可一行恢复) |
| 2 | `#100 lab 凯利区两阶段渐进加载`(B 段功能,行 82) | 存活:`static-site/lab.js` 仍有 `_labKellyY1Ready` | **删** | 纯**性能实现细节**(16 分片两阶段拉取/缓存签名 parts/状态机);「lab 凯利区」功能本体在 README 别处已有(长线三玩法行、信号凯利快照行的「lab 凯利区 演进」)→ 冗余 |
| 3 | `#99 更新新版气泡预览`(B 段功能,行 83) | 存活:`static-site/changelog.json` + `static-site/sw.js`(SW_UPDATED) | **删** | 更新 toast 的 **UI 实现细节**;用户拍板精简项 |
| 4 | `check_task_state`(监控与告警工具,行 460) | 存活:`scripts/check_task_state.py`(29KB) | **删** | **内部开发期门禁**(CLAUDE.md §23.12-1 治理对账),权威在 CLAUDE.md + 脚本本身,非用户面 README 条目 |
| 5 | `数据缺口告警``check_data_gap_alerts`(监控与告警工具,行 461) | 存活:`scripts/check_data_gap_alerts.sh` + 云上 systemd timer `trade-check-data-gap` | **删** | 内部监控工具,描述极冗长(五项+三项检查器逐条),权威在 docs/;监控区主干(8 条)不动 |

删后自验:5 锚点 grep 计数 = 0(lab 两阶段/气泡预览/check_task_state/数据缺口告警);`北交所` 仅余数据源表 1 处(符合预期)。README 491 → **486 行**;`git diff --stat` = `README.md | 5 -----,1 file changed,5 deletions(-)`。

## 二、H 档数字处理方式(不动,保留 230.83%)

任务提示勿盲从 stash 的「230.83%→224.92%」,须以当前基准重核。**核对结论:改 = 错误,故不动。**

- **现网/README 现值 = 230.83%**:`static-site/lab.min.js` 内 `230.83` 多处命中,`224.92` 在 `static-site/` **命中数 = 0**(即线上/README 已统一为 230.83)。
- **230.83 是「兜底态 V2」权威口径**(`docs/kelly/analysis/trade-method-final-recommendation-20260901.md`:off_base=new14 真过滤,用户实际所见即此值)。
- **224.92 是 2026-09-03 数据重算中间态**(`docs/kelly/analysis/v1114-rerun-alignment-20260903.md`:当前数据下旧引擎输出 224.92),但**2026-09-07 已由 #29 全站对齐 224.92→230.83**(`docs/tasks-done-list.md` #29:16 处 H 数字 224.92→230.83 全站对齐,§22)。
- **stash@{1}(09-08)带的是更早的 224.92** → 若照抄即把现网值**回退**(破坏 §22「README ≠ 站点」一致性)。→ **数字一律不动**,README 保持 230.83%。

## 三、未做项及原因(任务明示「一律不做」+ 我的判断)

| 未做项(stash@{1} 里有的) | 原因 |
|---|---|
| **H 档数字 224.92%** | 过时值(见 §二),照抄会回退现网值、破坏 §22 一致性 |
| **改写 FAPI 数据源行** | stash 版是**旧版**(把「3 职(兜底/北交所源/双源互证)」缩成「兜底,观察期」);当前 main 行更完整(2026-09 已转正 + 双源互证)→ 照抄=回退新内容 |
| **改写「回测买入价口径」行(删 #91 尾)** | stash 删掉了现网已有的「#91 买入口径双档切换」说明;#91 功能仍在线 → 删=丢有效功能信息 |
| **改写「首页模拟回测弹窗」行** | stash 版缺现网的「全史峰值口径 #51」「渐进加载」等新内容 → 照抄=回退 |
| **删 `verify_sigkelly_y1_render.mjs` 段** | 该段在当前 main 仍有效(Playwright 验收脚本),且非「5 条描述」范围 |
| **stash 里各式「云上 systemd timer→macOS launchd」「规则版→AI 速递」等** | stash 全面**落后于当前 main**(亏损/规则版/桶化/云上调度等现网均已更新),一律不回退 |
| **TASKS 头句 / plist 整删 / about·guide·privacy 版本串 / accum_nav_map** | 任务明示全为过时项(plist 已被 `536d62202` 取代;html 版本串现为 20261004-a642,远新于 a555),一律不做 |

**§23.3 举一反三(同类面清单,仅报告不擅改)**:B 段功能列表中另有若干条同属「实现级超细描述」(如「盘中增量回测档」「实操步骤表格」「信号凯利快照」等)。**本次不扩删**(遵 §7/L11「不加需求外改动」)——如需进一步瘦身,建议另派任务、由用户逐条点名,不在本任务擅自扩大。

## 四、恢复路径(§25 可逆)

删除内容全部可反查恢复:①本分支 commit 前一版 = HEAD `16dfee5aa`;②本地备份 `/tmp/README.before.md`(491 行);③`git show 16dfee5aa:README.md`。恢复 = 从上述任一源取回被删的 5 行。

## 五、自验清单(逐条)

- [x] 取 stash@{1} 原文:`git stash show --stat` + `git diff stash@{1}^1 stash@{1} -- README.md` + `git diff HEAD stash@{1} -- README.md`(**全程只读,未 apply/pop/drop/save**)
- [x] 5 条现状逐条核对(见 §一表格,全部含「代码/产物是否存活」证据)
- [x] 删除后 5 锚点 grep=0(北交所仅余数据源表 1 处,符合预期)
- [x] `git diff --stat` = 纯 5 删除,零其它改动
- [x] 数字:230.83 保留(1 处),224.92 = 0,不动
- [x] 除 README 外零文件改动(plist/版本串/TASKS/accum_nav_map 全未碰)
- [x] base-fresh(`git merge-base --is-ancestor origin/main HEAD` = PASS)
- [x] 零外发:未触发告警/邮件/飞书;未写 R2;未裸跑 pip/npm;未 Docker;未 `find /`;未无白名单 `grep -r`

## 六、产出

- 改动:`README.md`(−5 行)
- 报告:本文件