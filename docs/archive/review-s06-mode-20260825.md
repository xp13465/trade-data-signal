# S06 大盘领先切换 merge 前独立审查报告(2026-08-25)

> reviewer agent(fresh context,只读不改)。对象=feat 分支 `worktree-agent-afb3ea18c2e3ff411` @ f174dbf54(rebased 至 main b646f10ff)。
> 验收标准权威=`docs/codex-reviews/s06-mode-implementation-handoff-20260825.md` §五。codex verdict=PASS 仅作参考,本报告全部结论独立复核。

## 结论:PASS(带 2 个 P2 findings,均不阻断 merge)

九项审查重点 7 项全 PASS、2 项带缺口(F1 消费点一致性尾注/F2 落档索引),无 C/P0 级问题,默认档零触碰,机检 4/4 PASS,降级契约实测生效。

## 一、九项重点逐项证据

### 1. 默认档冻结红线 — PASS
- diff 中 `_KELLY_FADE_DEFAULT_MODE = "new14"` 为 context 行未动;new14 预设 keys 逐字未改。
- smoke 实测:首页下拉初始 `value=new14`,9 个选项(7 预设+自定义+s06)。
- s06 排 new15 后、`dynamic:true` 无静态 keys、手动勾键转「自定义组合」逻辑在位(common.js Apply 对 dynamic 返回 false)。
- §5.4⑥ 判定:纯新增可选档不动测试基准 v1.1.6,README 已显式声明。

### 2. 四消费点齐全且 per-date — PASS(F1 见下)
- common.js 注册单源;app.js 首页 AI 降亏过滤(`_renderSignalGrid._isAiFadeHit`)、sim 弹窗(`_simRenderOnce`)、监控卡组集(`_ovAggregateRecent` a9/new15 双成员集+`memberSetForRow`)、lab.js 凯利区(passesFade per-date)全部遇 s06 读 `_tdsS06BaseForDate(date).base` 再套键集,grep 无静态展开。
- smoke 实测快照层:`20260609→a9(decisionDate 20260608)`、`20260428→new15(20260427)`、期外 `ok:false reason=out_of_range`;per-date 键集 a9 日含 bullAuxBackupStop、new15 日含 excludeTierNone。
- 后端登记点:overfit_monitor.py RECENT_KEYS 已覆盖 a9/new15 全部键,无第二阈值事实源(A4 ast 抽取断言保障)。

### 3. 无前视 — PASS
- 状态机 build_daily 仅用 `spread.get(prev)` 判当日生效(T 收盘→T+1 生效);CONFIRM/MIN_HOLD 只累计历史日。
- 阈值 `-3.524224785046781` 硬编码冻结常量非计算值;A4 断言生成器常量与公示数值单源。
- A1 用独立第二实现复算全表 2863 行逐位相等;A2 全表 decision_date 时序无穿越。

### 4. 降级契约 — PASS
- `_tdsS06BaseForDate` 五级 reason(not_loaded/load_err/no_row/out_of_range/bad_mode),消费点 fail-open 该笔不拦+计数+可见警示,无静默回退其他模式路径(§10.4 专查通过)。
- smoke 实测(route abort 快照):红字「⚠ S06 快照不可用(快照加载失败: Failed to fetch), AI降亏过滤暂不拦(未回退其他模式)」可见;全程零新增 JS error。

### 5. lab.js 并行边界 — PASS
- renderSigKellyLab 主体零触碰,仅 2 处共约 8 行最小改(keepS06 补渲+Apply false 回落参考底座)。并行 feat/kelly-mobile-b 冲突面极小。

### 6. 机检复跑 — PASS(worktree 实跑)
```
python3 scripts/check_s06_state.py → EXIT=0
[A1] 独立状态机复算 2863 行 effective_mode 逐位一致 ... PASS
[A2] decision_date = 前交易日时序校验 ... PASS
[A3] a9/new15 键集与预设对齐(+ALL_KEYS 在位) ... PASS
[A4] 阈值/参数公示数值单源(ast 抽取)+公示串 6 处 ... PASS
```

### 7. §21 公示 — PASS(F2 另计)
- purpose-notes.js lab.sigkelly 新增三档互证段(白话规则/实验场景/1:1 例);README 功能亮点补全。
- 1:1 数字独立核实:20260608 spread=-4.0488(-4.049%)→06-09 生效 a9;20260427 spread=+1.6871(+1.687%)→04-28 生效 new15;对照 +93,813 vs +83,718 与 handoff 表逐位一致。

### 8. 工程验收 — PASS(机制C 口径)
- worktree 未自行 bump/重建 min 属机制 C 正常(main-merge.sh 统一 build_min+bump+sw CACHE_VERSION);worktree 工作区干净无脏文件。
- smoke 独立复跑:实施方 /tmp/s06_smoke.js 的宿主页(smoke-index/no-sw.html)已不在、无法原样复跑;改为自建精简 smoke(min→源路由+禁 SW+本地静态服务)**10/10 PASS**(下拉在位/默认 new14/锚点×2/期外拒绝/per-date 键集/s06 生效文案/记忆写入/断供警示/零 JS error)。
- **lab 运行时未能本地独立复现**:lab 区挂载依赖远端数据链,sandbox 环境 2 次尝试(导航点击+25s 等待)未挂载且零报错;可信度依据=lab.js diff 逐行核+实施方 smoke 的 lab 链断言设计+codex PASS 三方叠加。此为环境受限如实记录,非代码缺陷证据。

### 9. 静默失败专查 — PASS
新增代码所有 except/catch/fallback 逐处核对:均有计数暴露(_s6OpenCnt/_openCnt/s6Open)+可见警示(_s6warn/sim-s06-note/home-sig-s06-state-slot/#lab-kelly-s06-state)+事件(tds-s06-state-ready/error),无静默吞掉。

## 二、Findings 分级

### F1(P2,置信度 85):lab 凯利区枯竭 chip 在 s06 态口径不一致+缺尾注
- 位置:`static-site/lab.js:9086`(modeKeys 从 `state.labSigKellyFilters` 取静态键=s06 态实为参考底座 new14 键)、`lab.js:9090`(`_tdsDroughtChipHtml(info)` 未传 caliberNote)。
- 对照:首页两处(app.js:2988/3013)均已传 `_homeDroughtCaliberNote()` 且 modeKeys 用函数型 per-date——同模式举一反三只做了首页半边。
- 加重因素:L9079 注释自己声明「与首页 AI 建议区 chip 同源同数字(§22 一致性)」,s06 态下两处数字会分叉,恰与声明相悖。
- 影响:仅用户选 s06 实验档时的展示口径(数字本身对其参考底座是正确的),默认档不受影响。
- 建议:merge 不阻断;merge 后小改一行传 caliberNote+per-date 键集,或主控拍板随 kelly-mobile-b 一并处理。

### F2(P2,置信度 85):落档索引未登记(§23.5)
- feat 分支 `docs/kelly/analysis/README.md` 有 20260825 warn-signal 报告行但无 `s06-mode-implement-report-20260825.md` 行(grep 's06|S06' 零命中);报告本体+复现段均在。
- 建议:merge 前顺手补一行索引(成本一行),或 merge commit 一并带上。

### 低分滤除明细(<80,按 §10.2 列数不进正文)
| # | 描述 | 分 | 缓解 |
|---|---|---|---|
| 1 | common.min.js 版本过旧时 _ovAggregateRecent 返回 null 走回退链而标签仍显 s06 | 40 | 需 min 撕裂前提,§24⑤哈希校验+main-merge 统一重建缓解 |
| 2 | localStorage 残留 s06+旧 common.js 时静默落 FALLBACK new14 | 40 | TTL 18h 自然过期;旧 common 无 s06 选项本身即回默认态 |
| 3 | main 仓快照时间戳(06:38)与 trade-data(07:16)两次生成 | 25 | daily 已验三处逐位一致,无害 |

## 三、Pre-existing 上报清单(§23.7⑤,不吞不擅修)
- no-sw 场景控制台 "Unexpected token '.'" 基线噪音:实施方 smoke 自带对照实验证实与本次改动无关(/tmp/s06_errcheck.js 在干净基线同样复现)。留档待主控决定是否另派排查,本次不修。

## 四、merge 提醒(主控动作)
1. 走 `scripts/main-merge.sh <feat>` 统一入口(build_min+bump 版本串+sw.js CACHE_VERSION 同步,机制 C/§24)。
2. 快照上线渠道:static-site/data/kelly_mode_s06_state.json 不入 git,经 trade-data rsync/deploy 渠道推三站+R2;merge 后验线上 curl 快照在位且阈值一致(§22 三步)。
3. codex review 已闭环(status=completed/PASS,/tmp/codex-reports/codex-task-20260825-001.json),§23.14 双保险齐。

## 复现
- 机检(worktree):`cd /Users/linhuichen/code/trade/.claude/worktrees/agent-afb3ea18c2e3ff411 && python3 scripts/check_s06_state.py`
- diff 范围:`git diff b646f10ff...worktree-agent-afb3ea18c2e3ff411 --stat`
- reviewer 独立 smoke:/tmp/s06_review_smoke.js(worktree static-site 起 `python3 -m http.server 8911` + playwright,min→源路由+serviceWorkers block;依赖 /Users/linhuichen/node_modules/playwright)
- 数据截止:快照 coverage 至 20260824(current.mode=a9 since 20260609);关键口径:S06=csi1000_ret20−hs300_ret20<−3.524224785046781 次日切 a9 否则 new15,confirm15/min_hold10,T+1 生效。
