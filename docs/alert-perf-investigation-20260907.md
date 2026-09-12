# 告警排查 + 定时脚本越跑越久性能审计(2026-09-07)

> 调研 agent 产出(只读不改)。分两节:A 告警排查表 / B 性能审计(耗时趋势表/阶段拆分/提速建议)。
> 结论均带可复核证据点(日志文件+数字)。扫描窗口:2026-09-07(最近 24h)。

## A. 最近 24h 告警排查

### A0 扫描范围(事件驱动扫描法,非只看登记点)
- 日志目录 `/Users/linhuichen/code/trade-data/data/logs`,`find -mmin -1440` 列出全部新鲜日志,逐个 tail 近段 + grep 错误/超时/失败关键词(update_all/pipeline_*/etf_national_team/backfill_evening/fetch_news/overfit_monitor/schedule_monitor/intraday_snapshot/各 backfill/update_lab 等 40+ 文件)
- 告警登记 `data/alerts/latest.md`:最新 severe = 2026-09-07 19:30:13「update_all 超时未完成 已运行100min」+ 20:45「耗时超1h(171分钟)」
- launchd 状态:`launchctl list | grep trade`(36 任务),exit 非 0:lab-auto=1、etf-national-team=1、public-fund-daily=1、futures-backfill=1、lhb-backfill=1(多为旧状态,以 schedule_stats/日志为准)

### A1 告警清单表
| # | 时间 | 脚本/任务 | 严重度 | 根因(证据) | 人工处理 |
|---|---|---|---|---|---|
| A1 | 09-07 19:30/20:41 | update_all(17:50) | **SEVERE 需人工** | 耗时 171min(17:50→20:41,update_all_20260907_1750.log 结束行)。见 B 瓶颈拆分。8-31 起连续 6 交易日 123~226min,非偶发 | 需决策 B4 提速方案 |
| A2 | 09-07 20:07(21:00/21:30 检测) | etf_national_team | SEVERE→21:45 已恢复 | deploy 失败 exit=1(etf_national_team_launchd.log 尾部):①deploy 在 fix/ab-anchor-py 分支被拒(L15561「✗ deploy 必须在 main 分支跑」)②§24⑤ 版本一致性校验 FAIL ③§23.12-1 zombie_crons 僵尸巡检 cron FAIL | **需 CronDelete 2 个真僵尸**(A2a) |
| A3 | 09-07 16:35(21:00 检测) | backfill_evening(指数补采兜底) | SEVERE→21:45 已恢复 | exit=1(backfill_20260907_1635.log 尾部「backfill_metrics.sh 结束 2026-09-07 17:00:04 退出码=1」)= sigkelly 回测停滞告警(signal_kelly_snapshot --check FAIL)触发非 0;采集/补采本身成功 | sigkelly 停滞单独立项(快照天 20260907, max_signal_date=20260904) |
| A4 | 09-07 21:40 | overfit_monitor | **SEVERE 唯一活跃**(schedule_monitor 21:45) | 组集一致性校验 FAIL rc=1(overfit_monitor_launchd.log 尾部「[ov-parity] 总结: FAIL ❌ C p9 fade 开启人口变小」「组集一致性校验 FAIL rc=1」) | **需判断是否预期**(fade 开启人口变小可能自然) |
| A5 | 09-07 19:00 | update_lab(策略实验室) | 连锁影响 | update_all 171min 长跑,lab 等 5400s 超时放弃(update_lab_20260907_1900.log「⚠ update_all 仍运行中(已等 5400s)，超时放弃本次 lab」) | update_all 提速后缓解 |
| A6 | 09-07 盘中 | fetch_news | 连锁影响(600s 超时后重试成功) | staticdata_sync 与 update_all git 锁竞争超时(「timed out after 600 seconds」),重试成功「同步上线完成」 | 无 |
| A7 | - | lhb/futures/rzhb/us_stock_morning/public_fund_quarterly/S06/intraday | 正常 | 各轮 exit=0(lhb 19:30 dur=677s / futures 20:05 2086s / us 05:00 1425s / S06 20:35 exit=0 / intraday 20:35 exit=0) | 无 |

### A2a 僵尸巡检 cron 明细(§23.12-1 机检 FAIL,挂 deploy 链阻断上线)
`python3 scripts/check_task_state.py` 实跑(只读)输出:
- ✗ cron d2fef6f7 → /tmp/agent-progress-implementer-sigkelly-silent-impl.md 不存在 → **真僵尸**(任务已结束 cron 未删)
- ✗ cron 0006585b → /tmp/agent-progress-implementer-local-audit-clean.md 不存在 → **真僵尸**
- ✗ cron 6bce6be3 → /tmp/agent-progress-researcher-alert-perf.md 不存在 → **路径误报**(本调研任务巡检 cron,实际进度文件是 /tmp/agent-progress-alert-perf.md,引用路径不一致)

→ 该 FAIL 已实际阻断 etf_nt 20:07/21:30 轮 deploy(§23.12-1「FAIL 阻断上线」),是 A2 告警触发一环。**建议:主控 CronDelete d2fef6f7 + 0006585b;6bce6be3 为活 cron 但路径写错,需修正引用为 /tmp/agent-progress-alert-perf.md(或本任务完成后随 CronDelete)。**

### A 结论
- **唯一待人工**:A1 update_all 耗时(决策提速)+ A4 overfit_monitor FAIL(判断是否预期)。
- **机械待办**:2 个僵尸 cron 删除 + 1 个误报路径修正(否则后续 etf_nt/backfill deploy 持续被拦)。
- A2/A3 已自愈(21:45 schedule_monitor「4 项异常恢复」)。

## B. update_all 越跑越久性能审计

### B1 耗时趋势(数据说话:38 次运行,update_all_*.log 提取开始/结束)
| 日期 | 总耗时 | 日期 | 总耗时 | 日期 | 总耗时 |
|---|---|---|---|---|---|
| 07-20 | 6min | 08-05 | 38min | 08-25 | **117min** |
| 07-21 | 12min | 08-06 | 49min | 08-26 | 20min* |
| 07-22 | 66min | 08-07 | 53min | 08-27 | **112min** |
| 07-23 | 76min | 08-10 | 54min | 08-28 | 21min* |
| 07-24 | 54min | 08-11 | 59min | 08-31 | **226min** |
| 07-27 | 27min | 08-12 | 21min | 09-01 | **123min** |
| 07-28 | 29min | 08-13 | 53min | 09-02 | **154min** |
| 07-29 | 28min | 08-14 | 60min | 09-03 | **166min** |
| 07-30 | 28min | 08-17 | 88min | 09-04 | **134min** |
| 07-31 | 25min | 08-18~24 | 37~57min | 09-07 | **171min** |
| 08-03 | 33min | 08-21 | 57min | | |
| 08-04 | 38min | 08-24(23:07 手动) | 42min | | |

\* 8-26/8-28 是 baostock 大量失败快速短路日(见 B2),非正常快。

**结论:非「单调越跑越久」,而是两段结构性平台**——7-20~8-24 在 6~88min 波动(多为 25~60min);**8-25 起进入 112~226min 平台**,8-31 起连续 6 个交易日全部 123min+。

### B2 瓶颈拆分(今日 171min 构成,pipeline_*_20260907_1750.log 头尾 + 主日志)
| 段 | 起止 | 耗时 | 性质 |
|---|---|---|---|
| core | 17:50:05→17:58:08 | 8min | 正常快核心 |
| width | 17:50:06→18:27:36 | **37min** | **新瓶颈①**:mootdx 疑似全停(「连续15只失败(阈值15)，mootdx 疑似全停服，剩余5185只改用 baostock fallback」)→ 5185 只串行 baostock fallback(~0.43s/只)。9-01 起同样全停;8-25/8-27 仅 70 只 fallback(部分停) |
| futures | 即时 | ~秒级 | 正常(636B 日志) |
| turnover | 17:50→20:02:44 | **132.6min** | **最大瓶颈**:baostock 全市场 5196 只,「parallel update done: ok=5196 fail=4 rows=5196 (5200 codes, 132.6min)」。**workers=1**(T1 2026-08-27 默认 3→1 防封禁,runner.py L399-405),每只 ~1.53s(含 0.4s QUERY_INTERVAL per-query 限速) |
| 串行导出段 | 20:02→20:41:16 | ~39min | 其中 O1 统一 deploy 20:03:54→20:29:35 = **25.7min**(deploy_20260907_2003.log L1/L946,board_etf_map 构建+export 增量+版本校验+git push);其余 etf_score_list 141s / etf_hist 4.6s / intraday 61.6s / alert_analyze 6.8s |

**历史对比(turnover 采集耗时)**:8-25=19.4min(ok=41 fail=5159 快速失败)、8-27=6min(ok=1082 fail=4118)、**8-31=109.3min(ok=5199)、9-01=93.2min、9-02=99.8min、9-04=103.7min、9-07=132.6min**。8-31 起 baostock 恢复稳定后,1 worker 全量真拉,每次 93~133min = 结构性固定成本。

### B3 根因判定:已优化过又复发 vs 新瓶颈
| 项 | 判定 | 说明 |
|---|---|---|
| turnover baostock 1 worker 慢 | **主动防封禁权衡(非复发)** | 8-14/8-25 两轮 10001011 黑名单封禁都发生在 3 并发时期(T1 注释,runner.py L399-410),8-27 降 1 worker+0.4s 限速是防再封;代价是 baostock 稳定后每次 93~133min。8-14 定位的 99min 根因同族 |
| mootdx 全停(9-01 起) | **新瓶颈(外部因素)** | 8-25/8-27 只 70 只 fallback,9-01/9-07 5185 只全停 fallback → width 从 ~4min 涨到 37min;且与 turnover 并发打 baostock 互相拖慢(9-07 width 37min+turnover 132.6min 双慢 vs 9-03 width 29min+turnover 68min) |
| O1 deploy 25.7min | 旧有固定成本 | 8-17 O1 收敛「4 遍 deploy→1 遍」已省 88min,剩余是单次完整 deploy(board_etf_map 全量重建) |

### B4 提速建议(§5.1 数据说话;不动手,供拍板)
> 共同前提:今日证据显示 width fallback 与 turnover 并发打 baostock 双慢 → **baostock 服务端疑似按 IP 连接限速,盲目加并发收益有限且引封禁风险**。

| # | 建议 | 预期收益(估) | 改动面 | 风险 | 备注 |
|---|---|---|---|---|---|
| B4-1 | **turnover 摘出 update_all 主链(后台/延后,仿 stock_daily 死端)** | 171→~76min(**减 ~95min**) | update_all.sh wait 列表去掉 turnover + 单独 launchd 延后跑 | **中:需拍板**。a_turnover 被前端(queries.py)+ AI 宏特征(gen_kelly_loss_features.py)+ width_history 消费,延后=当日前端/AI 宏缺当日值 1-2h | **主推候选**;接受延后则零封禁风险 |
| B4-2 | BAOSTOCK_WORKERS 1→2 + 保留 0.4s interval | turnover 132→~90~110min(收益 20~40min) | runner.py 默认值(env 可调) | **中:封禁风险**(两轮封禁在 3 并发;今日 2 并发实测未封) | 需 A/B 实测确认服务端是否限速,收益可能打折 |
| B4-3 | BAOSTOCK_QUERY_INTERVAL 0.4→0.2s | 省 ~17min(纯间隔 34.7→17.4min) | env 默认值 | 低-中(削限速余量) | 可与 B4-2 组合实测 |
| B4-4 | O1 deploy:board_etf_map 全量重建→增量/复用 | 串行 39→~25min(收益 ~14min) | deploy.sh/build_board_etf_map | 中(§22 一致性敏感,board_etf_map 是 N 展示位数据源) | 单独立项,不随本次 |
| B4-5 | mootdx 停服外部因素,等待恢复 | width 恢复 ~4min | 无 | 无 | 恢复前 mootdx fallback 持续;fallback 与 turnover 错峰可减互拖 |

**§5.2 说明**:本任务无 AI/重算,纯数据采集,模型参数层(thinking 开关)不适用;提速核心在采集并行度与数据链路编排。

### C. 主控线索核查:index_daily 9/7 覆盖率 & signal_daily 卖出笔(2026-09-06 追加)
> 主控线索:「sentiment.db index_daily 9/7 只有 112 条 vs 9/4 的 154 条,缺 42 条 csi_930xxx;signal_daily 无 9/7 卖出笔;疑似与采集异常同源」。核查结论:**非采集失败,是「源发布时点 + 镜像快照时点 + 美股时点」三层叠加,当前主库已补全**。

**C1. index_daily 9/7 双库对账(主库 vs 镜像)**
| 库 | mtime | 9/7 条数 | 9/4 条数 | 缺项 |
|---|---|---|---|---|
| trade-data/data/sentiment.db(主库) | 21:45 | **150** | 154 | 仅 us_dji/us_ixic/us_ndx/us_spx 美股 4 条(设计行为,见 C3) |
| trade/data/sentiment.db(镜像) | 20:12 | **112** | 154 | us_* 4 + csi_930 系 38 条 |

- 主控看到 112 = 镜像库(trade/data)20:12 快照。镜像仅 deploy.sh rsync 时同步(export_notifications.py L26「trade/ 是滞后镜像,仅 deploy.sh rsync 时同步」);今日 deploy 20:03-20:29 的 rsync 早于 21:00 补采 → 镜像缺 csi。
- csi_930 中证系列缺 38 条根因 = **中证指数源当日值 17:45 后才发布**:backfill_20260907_1635.log L82-99 已记「[gap] - csi_930050 latest=20260904 缺口但源无新数据(ok)」;backfill_20260907_2100.log L47-65「[gap] ✓ csi_930050 latest 20260904->20260907 (+1行)」—— 21:00 轮补采成功入主库。16:35/17:50 两轮采不到是源未发布,非采集逻辑失败。
- 结论:核心 A 股 150 条 9/7 全齐,**不存在「部分指数采集失败」**;镜像落后会在下次 deploy rsync 自然追上。

**C2. signal_daily 9/7 卖出笔:双库均有,无缺失**
- 主库(trade-data)9/7 共 11 条,含 4 条 sell:g.gold / g.comex_silver / s.cross_market / cgb_idx(max_date=20260907)。
- 镜像(trade)9/7 共 10 条,含同 4 条 sell。
- 主控「signal_daily 无 9/7 卖出笔」疑来自 signal.db(trade/ 与 trade-data/ 两个 signal.db 均**空库无表**,无 signal_daily)→ 该表在 sentiment.db,非 signal.db。凯利交易停更根因不在 signal_daily 缺失(信号生成正常)。

**C3. 美股 us_* 9/7 缺失 = 设计行为,非故障**
- index_backfill.py L395-403:美股走 index_us_stock_sina,北京时间晚 21:30+ 才开盘;A 股交易日时美股最新通常 T-1/T-2(跨周末),require_today=False + 校验「最新日期距今<=3 天」。
- 2026-09-07 周一,美股 9/7 收盘价北京时间 9/8 凌晨 04:00 才出 → 9/7 缺 us_* 正常,9/8 05:00 us_stock_morning 补写 date=20260907。
- us_stock_morning_20260907_0500.log 05:23 已跑 exit=0(dur=1425s),写的是 9/4(周五)收盘数据。

**C4. 与 A 告警/B 性能的关系**:csi 发布时点空窗对 update_all 耗时无影响(core 采集 8min 内正常,缺当日值不阻塞退出码);与本报告 A1(171min 慢)无因果关系。凯利交易停更需另查 signal_kelly_trades.json 生成链路,不在本报告范围。

## 复现
- 耗时趋势:`for f in /Users/linhuichen/code/trade-data/data/logs/update_all_*.log; do grep 'update_all.sh 开始\|update_all.sh 结束' $f; done` 提取 begin/end 算分钟(本次 38 次全量,窗口 2026-07-20~09-07)
- 瓶颈拆分:今日 `/Users/linhuichen/code/trade-data/data/logs/pipeline_{core,width,futures,turnover}_20260907_1750.log` 头尾 `=== pipeline[xxx] 开始/结束` 行;turnover 耗时 `grep 'all workers done' /Users/linhuichen/code/trade-data/data/logs/pipeline_turnover_20260907_1750.log`(132.6min)
- workers 配置:`grep -n 'BAOSTOCK_WORKERS' /Users/linhuichen/code/trade-data/app/collector/runner.py`(L399-405/L600-606 默认 1);`/Users/linhuichen/code/trade-data/app/collector/baostock_worker.py` L45-46(interval 0.4s / fail backoff 30s cap 120s)
- 僵尸 cron:`python3 /Users/linhuichen/code/trade/scripts/check_task_state.py`(只读,2 真僵尸 + 1 误报)
- 告警登记:`cat /Users/linhuichen/code/trade/data/alerts/latest.md`;schedule_monitor:`tail /Users/linhuichen/code/trade-data/data/logs/schedule_monitor_launchd.log`
