# 告警邮件 + 定时任务耗时审计(第二轮,2026-09-08)

> 调研 agent 产出(只读不改)。本轮扫描窗口:2026-09-02~09-08(近 7 天),重点 09-08 当天。
> 第一轮(09-07,告警排查+update_all 瓶颈拆分)见 `docs/alert-perf-investigation-20260907.md`。本报告在 A 节(告警清单)以 7 天全量口径补充,B/C 节聚焦 09-08 现状与优化空间。
> 结论均带可复核证据点(日志文件+行号+数字)。

## A. 告警邮件清单(近 7 天)

### A0 邮件量总览(来源 = schedule_monitor 日志 + check_signals 每日发送轮数)

| 日期 | schedule_monitor 邮件数(告警/恢复) | check_signals 信号邮件数 | 日合计 |
|---|---|---|---|
| 09-02 | 5(2/3) | 11 | ~16 |
| 09-03 | 5(3/2) | 8 | ~13 |
| 09-04 | 11(6/5) | 8 | ~19 |
| 09-05 | 3(1/2) | 周末无 | ~3 |
| 09-06 | 12(7/5) | 周末无 | ~12 |
| 09-07 | 16(9/7) | 16 | ~32 |
| 09-08 | 14(8/6) | 13 | ~27 |
| **合计** | **66** | **56** | **~122/7天(平均 ~17/天)** |

- schedule_monitor 近 60 封邮件主题流:trade-data/data/logs/schedule_monitor_launchd.log 尾部 grep「邮件已发送至」。
- check_signals 发送数:近 5 个交易日 8~16 封/天(34 轮检测中发信轮数,`grep -l 邮件已发送 check_signals_2026090{2,3,4,7,8}_*.log | wc -l`)。

### A1 告警逐项核对表(09-08 当天 8 条 severe + 恢复 6 条)

| # | 时间 | 主题 | 核判定性 | 证据 |
|---|---|---|---|---|
| A1 | 01:15 | 飞书 hook 心跳陈旧 | **误报(假阳性,常态)** | schedule_monitor L303 hook 90min 无触发即报;用户不活跃的夜晚/上午必炸;09-08 01:15 发现→08:30 恢复,18:00 又发现。无 Claude 会话活动时"抄送停摆"无实际损失 |
| A2 | 02:45 | backfill_evening 退出失败 exit=1 | **连锁误报(采集本身成功)** | backfill_20260908_1635.log 尾部:「direct metrics 补采 ok=3 fail=0」「[notify] 邮件已发送…[告警] 信号凯利回测停滞」「signal_kelly_snapshot --check 检测到告警(停滞/突变,正常路径),不阻塞 backfill」→ exit=1 来自 sigkelly 停滞检查非 0,采集/补采成功。与 09-07 A3 同根因(sigkelly 停滞已单独立项) |
| A3 | 19:30 | update_all 超时未完成 100min | **阈值失真的常态轰炸** | schedule_monitor.sh L321 DUR_THRESHOLDS update_all=4200s(70min);近 5 天实测 154/166/135/171/175min(L317 注释自述「阈值必须 > 实测 max,否则复发假 SEVERE」,当前实际已 2 倍于 max 时的阈值) |
| A4 | 20:30 | etf_national_team 退出失败 | **真故障,根因=ov-parity C 项 FAIL 阻断 deploy** | etf_national_team_launchd.log 尾部:「[ov-parity] 总结: FAIL ❌ C p9 fade 开启人口变小」「✗ AI监控卡组集一致性校验失败(退出码 1),终止部署」「[etf_nt] daily 完成 171.4s exit=1」;deploy.sh L239/L251-255 ov-parity 挂 deploy 链(2026-08-25),FAIL 阻断全部走 deploy.sh 的任务 |
| A5 | 20:45 | update_all 耗时超1h(175min) + 统一 deploy 失败(1) | **半真**:耗时 175min 属实;**deploy 失败=changelog 缺版本条目漏补(人为一致性缺口)** | update_all 主日志 L1429:changelog.json 缺 20260908-a562 条目(登记停在 a558);check_data_integrity.py L1705 check_changelog_current_version(#fix555 2026-09-07 新机检);39 ok/1 warn/**1 fail** → O1 统一 deploy 失败 rc=1 → 线上**当晚 21:07:53 才由 futures 链 deploy 补推 first** |
| A6 | 21:00/21:30 | backfill/etf_nt 「pending但上次exit非0」 | 连锁(exiton 状态悬挂) | schedule_monitor 对「pending 但上次 exit 非 0」的二次检测;21:00 backfill exit=0(1262s),21:30 etf_nt exit=1(A4 同根因) |
| A7 | 21:40 | overfit_monitor 过拟合红区 61 分 + FAIL rc=1 | **半真**:红区 61 分(D1=90/D2=20/D3=90)真实信号;**rc=1 = 同一 ov-parity C 项 FAIL**(与 A4 同根因) | overfit_monitor_launchd.log 尾部:「[ov-parity] 总结: FAIL ❌ C p9 fade 开启人口变小 (off=165 on=180 blockableRows=0 memberHit=6 tNullRows=38)」「overfit_monitor.sh 结束 rc=1」 |
| A8 | 22:15 | lab_auto 退出失败 exit fixed=None | **连锁(update_all 变慢饿死 lab)** | update_lab_20260908_1900.log 尾部:「update_all 仍在运行,等待…(5400s)」「⚠ update_all 仍运行中(已等 5400s),超时放弃本次 lab」;09-07 同款(L5) |

### A2 可疑/轰炸判定汇总

1. **update_all 三连轰(19:30+20:0x+20:45)每天 2-3 封,7 天 16+ 封** —— 阈值 4200s 严重过时,内容零新增信息(每天同一句"耗时超1h")。**认定:疲劳轰炸,非误报但无决策价值**。
2. **飞书 hook 心跳 09-02~09-08 共 6 对告警+恢复(每天 1-2 封)** —— **认定:假阳性误报**。在用户无 Claude Code 会话活动时段无条件触发,"恢复"邮件再翻倍。详见 B 节定位。
3. **backfill_evening exit=1 系列(09-07/09-08 各 2 封)** —— 采集成功、sigkelly 停滞检查"设计内非 0"(日志原文「正常路径」),但 exit=1 向上传导成"退出失败"。**认定:误报,应把 sigkelly 停滞检查移出 backfill 退出码依赖(或按设计降级为非阻塞)**,但 sigkelly 停滞本身属实需单独立项(09-07 已立项)。
4. **etf_nt/overfit 的 ov-parity C 项 FAIL(09-07/09-08 连续两天,每天合计 ~4 封链接邮件)** —— **真故障,校验逻辑与实现口径不匹配**(开 fade 后近窗人口 on=180 > off=165,与"开启变小"预期相反),每日固定炸+阻断 deploy 链。**当前最高优修复点**。
5. **overfit 红区 61 分(21:40)** —— 真实信号(D1=90 D2=20 D3=90),非误报;与 C 项 FAIL 是两件事,注意区分。
6. check_data_gap:09-08 10:43 盘中 3 条 warn / 22:35 1 条 warn + 3 条 recovered —— **正常,无 severe,量可控**。

## B. 定时任务耗时大表(09-08 最近一次运行)

| 任务 | 时点 | 起止 | 耗时 | exit | 大头拆解 |
|---|---|---|---|---|---|
| update_all(全量收盘) | 17:50 | 17:50:01→20:45:00 | **175min** | 0(deploy_all=1) | core 8min(17:50→17:58)+ width **36min**(18:26 结束,mootdx 全停 5185 只 baostock fallback)+ turnover **90.8min**(19:20:52,ok=5199 fail=1,workers=1)+ 导出串行 ~45min + O1 deploy 20:16 失败 |
| backfill_evening | 16:35/21:00/02:00 | 16:35:01→17:02:17 / 21:00:03→21:21:05 | 27min / 21min | 1 / 0 | 采集本身 ok=3 fail=0;exit=1 = sigkelly 停滞检查非 0(16:35 轮) |
| etf_national_team | 20:07+21:30 兜底 | 21:30:04→21:44:00 | 14min | 1 | 采集 171.4s 成功,deploy 被 ov-parity C 项 FAIL 挡 |
| futures_backfill | 20:05+21:00 兜底 | 21:00:03→21:11:22 | 11min | 0 | 含 deploy(21:07 成功推 overview) |
| lhb_backfill | 18:30+19:30 兜底 | 19:30:03→19:43:41 | 14min | 0 | 含 deploy |
| rzhb_backfill(两融) | 19:15 | 19:15:00→19:15:01 | 1s | 0 | T+1 数据,秒完成 |
| us_stock_morning | 05:00 | 05:00:04→05:24:22 | 24min | 0 | 含 deploy;09-06 曾 84min(5076s 超时告警,偶发,exit=0) |
| public_fund_daily | 17:00 | 17:00:04→17:12:59 | 13min | 0 | 含 deploy |
| public_fund_full | 22:00 | 22:00:01→22:00:03 | 2s | 0(无新数据) | fresh 检查 should_run=False(report_date=20260630 已采全),跳过 |
| update_lab | 19:00 | 19:00:05→(无结束行) | **饿死(等 update_all 5400s 超时放弃)** | None | 09-07/09-08 连续两天未产出 |
| overfit_monitor | 21:40 | 21:40:0x→21:42:02 | 2min | 1 | ov-parity C 项 FAIL |
| s06_snapshot | 20:35 | 20:35:05→20:35:17 | 12s | 0 | 秒级 |
| intraday_snapshot | 盘中10min | 20:35:04→20:42:01 | 7min | 0 | 反哺+重算+export |
| daily_brief | 20:40 | 20:40:21(末次) | ~10min | 0 | run 表 20260908 20:40:21 rule 档,staticdata 5.71s |

### B1 update_all 近 5 个交易日耗时(所有日志起止)
| 日期 | 起止 | 耗时 | 备注 |
|---|---|---|---|
| 09-02 | 17:50:05→20:24:05 | 154min | — |
| 09-03 | 17:50:05→20:36:31 | 166min | — |
| 09-04 | 17:50:05→20:05:04 | 135min | deploy_all=1 |
| 09-07 | 17:50:05→20:41:16 | 171min | 昨天报告 B 节已拆分 |
| 09-08 | 17:50:01→20:45:00 | 175min | 今天:core 8 + width 36 + turnover 90.8 + 导出 ~45 |

## C. 优化空间清单(收益/成本)

### 告警侧
| # | 候选 | 收益 | 成本/风险 | 证据 |
|---|---|---|---|---|
| C1 | **修 ov-parity C 项校验与实现口径不匹配(最高优先)** | 每天减 3~5 封 severe + 恢复 overfit_monitor/etf_nt 正常 exit + 解除 deploy 链梗阻(23:07 deploy 仍被它拦) | 需判明 off=165/on=180 中 on>off 是真语义(近窗 fade 放行更多行)还是校验假设错;改动校验脚本(只读审计即可,修复派 implementer) | deploy_20260908_2307.log L801;overfit_monitor_launchd.log 尾部;check_overfit_recent_parity.mjs L189-221 |
| C2 | update_all 阈值失真 → 治本(B4-1 turnover 摘出主链)或过渡抬阈值至 ~10000s(近 10 次 P90≈11000s) | 每天减 2-3 封无信息量轰炸;治本再减 95min 总链 | 抬阈值=掩埋退化信号,须与优化 deadline 绑定;(过渡)无风险 | schedule_monitor.sh L321;sleep 上一次审计 B4-1 |
| C3 | 飞书 hook 心跳报告只在「会话活跃期」触发(或降级为 warn 只记日志) | 每天减 1-2 封(09-02~08 共 12 封) | 需在 hook 侧打"会话最后活动时间"标记,检测侧对比;小改 | schedule_monitor_launchd.log「suppress/恢复 feishu_hb」流 |
| C4 | sigkelly 停滞检查从 backfill_evening 退出码剥离(或按 ok=3 主采集成功不置非 0) | 每天减 1-2 封 backfill exit=1 误报;sigkelly 停滞另走独立告警 | sigkelly 停滞本身仍在(09-04 起)——真修复=回测停滞根因(已立项),此处仅解除误报耦合 | backfill_20260908_1635.log 尾部「正常路径,不阻塞 backfill」仍 exit=1 |
| C5 | lab_auto 等待超时后**立即重跑**(等 update_all 完成条件变为可重入)或 update_all 提速后自动缓解 | lab 09-07/09-08 连续两天零产出,每天 1 封 exit 告警+用户策略实验无数据 | 重跑需确认不与 update_all 写开盘数据撞;或等 update_all 提速落地(15min 内自然恢复) | update_lab_20260908_1900.log 尾部 |

### 耗时侧(继续昨天 B4,今天的增量证据)
| # | 候选 | 收益 | 成本/风险 | 证据 |
|---|---|---|---|---|
| C6 | turnover 摘出 update_all 主链(昨天 B4-1,今日更新数据:90.8min) | 175→~85min(减 ~90min) | 前次审计已述:次日 AI 宏/前端缺当日值 1-2h,需拍板 | pipeline_turnover_20260908_1750.log「all workers done in 90.8min」 |
| C7 | width mootdx 全停 fallback(9-01 起常态)与 turnover 并发打 baostock 双慢互相拖累 | 错峰可各减 ~10~15min | baostock 服务端按 IP 限速证据:9-07 width 37min+turnover 132.6min 双慢 vs 今日 width 36min+turnover 90.8min | 今日 width 结束 18:26(36min)+turnover 结束 19:20(90.8min),两段部分重叠 |
| C8 | **changelog 漏补条目(今天 O1 deploy 直接失败根因)** —— 已是机检(#fix555 09-07 上线),但 bump 方(main-merge.sh)与 changelog 补登分离,今天漏了 | 避免 O1 失败→线上数据延迟 ~1h 上线+1 封"统一deploy失败"severe | 把 changelog 补登并入 main-merge.sh bump 步骤(实施侧);今天事后 23:07 才修复补推 | update_all_20260908_1750.log L1429;deploy_20260908_2307.log L683「✓ 已登记 a562」 |

## D. 结论
- **真优化点(证据在)**:C1 ov-parity 口径修复(连续 2 天,每天 4+ 封+deploy 梗阻,当前最高优);C8 changelog 补登并入 bump(一次事故今天刚发生);C6 turnover 摘出主链(90.8min 是主链最大单块)。
- **合理现状(不用动)**:rzhb 秒级/两融、s06_snapshot 12s、public_fund_full fresh 短路 2s、intraday 7min、futures/lhb 11~14min、us_stock_morning 24min、check_data_gap 量可控。
- **需用户拍板**:C6(turnover 延后,次日特征缺 1-2h);C2 抬高阈值(若 C6 落地则无需抬);C5(lab 超时重跑或等 C6 落地);C4(sigkelly 停滞检查剥离,真修复已立项)。
- **巧合验证**:今天 changelog 漏补 → O1 失败 → 20:45 告警 → 22:35 data_gap 报「kelly 产物可能未刷新」→ 23:07 人工补 changelog 后重 deploy 成功但又被 ov-parity 拦 → **C1 一天内已实际造成 2 个 deploy 失败**,优先级明确。

## 复现
- 邮件量统计:`grep "邮件已发送至" /Users/linhuichen/code/trade-data/data/logs/schedule_monitor_launchd.log | grep "09-0X" | wc -l`(按天);`grep -l "邮件已发送" /Users/linhuichen/code/trade-data/data/logs/check_signals_2026090X_*.log | wc -l`
- 耗时大表:各任务日志头尾(`grep "开始\|结束" {任务}_20260908_*.log`);update_all 分步:`grep "=== pipeline" /Users/linhuichen/code/trade-data/data/logs/pipeline_{core,width,futures,turnover}_20260908_1750.log | grep 开始\|结束`
- ov-parity 校验:`$REPO/.venv/bin/node /Users/linhuichen/code/trade/scripts/check_overfit_recent_parity.mjs`(只读,读 static-site/data/overfit_monitor.json)
- changelog 机检:`python3 /Users/linhuichen/code/trade/scripts/check_data_integrity.py`(check_changelog_current_version 段,只读)
- 阈值:`grep -n DUR_THRESHOLDS /Users/linhuichen/code/trade-data/scripts/schedule_monitor.sh`(L321)
- 数据截止:2026-09-08 23:15 日志(含 23:07 最后一条 deploy)
