# 运维群告警现状盘点 + 逐条定性(2026-10-11 夜,只读)

- 执行:researcher 子 agent;全程只读(零写云上/本机业务文件;未跑任何业务脚本;无残留后台任务)
- 窗口:近 48h(10-09 22:20 ~ 10-11 22:20)+ 前溯对照(10-05 起 latest.md 全量 severe 流水)
- 权威源:云上 trade-data/data/alerts/{latest.md, alert_ledger.jsonl, alert_daily.json, alert_state.json} + 各 launchd 日志 + 库直查 + 本地代码对照
- 通道事实:所有条目 channels={email:true, feishu:true}(运维群 oc_7d8d3eb6b322ddeb6b8e3c53519fae7e);telegram=占位符跳过。**48h 内未发现「只进邮件不进群」的条目**

## 一、近 48h 实际外发告警全集(16 条,双通道)

| # | 时间 | 条目 | 级别 | 定性 | 处置 |
|---|---|---|---|---|---|
| 1 | 10-09 22:35:24 | [数据缺口] 交易记录断档: 8 个入样买入信号无对应交易 | severe | **真故障(未登记)** | §3-4 待立项回填 |
| 2 | 10-09 22:35:31 | [数据缺口] trades 最新信号日 20260930 落后(应≥20261008) | severe | **真故障(未登记)** | 同上 |
| 3 | 10-09 22:35:35 | [数据缺口] 公募 20261008 全 NULL 24218 行 | severe | **真故障(未登记)** | §3-4 待回填 |
| 4 | 10-09 23:30:07 | [告警] 云上 unit 巡检异常(1项 nextday-gap-check) | severe | 真故障残留,已排观察 | 等 Mon 09:26 自然验证 |
| 5 | 10-10 00:00:09 | failed unit 连续 3 天 升级 critical | critical | 同 #4(通道级计数) | 同 #4 |
| 6 | 10-10 08:27:04 | unit 与仓库快照漂移 | critical | 真故障,已修 | #248 已闭环(10-11 08:27 rc=0) |
| 7 | 10-10 17:16 | 独立上传链产物与 R2 脱节(verify-r2 兜底补传) | notice | 设计内(补传成功通知) | 可评估降日志级 |
| 8 | 10-10 21:12 | [kelly] 冻结表缺失历史信号事件 8 个 | report | 已知根因+拍板接受 | 常态噪音,待治(§3-3) |
| 9 | 10-11 00:00:06 | failed unit 连续 4 天 升级 critical | critical | 同 #4 | 同 #4 |
| 10 | 10-11 04:27:55 | R2上传失败(verify-r2 无输出) | severe | 真故障,已修 | B6 已闭环;22:30 实跑验证 |
| 11 | 10-11 04:30:15 | [告警·聚合] 1 条 warning 汇总 | warning | 聚合容器 | 内容见 §2-D |
| 12 | 10-11 05:00:07 | [恢复] fetch_news r2_skip_continuous | notice | 自愈循环恢复通知 | 正常 |
| 13 | 10-11 18:23:47 | 独立上传链产物与 R2 脱节(verify-r2 兜底补传) | notice | 同 #7 | 同 #7 |
| 14 | 10-11 18:45:20 | [告警·聚合] 1 条 warning 汇总 | warning | 聚合容器 | 见 §2-D |
| 15 | 10-11 19:00:13 | [恢复] fetch_news r2_skip_continuous | notice | 同 #12 | 正常 |
| 16 | 10-11 21:12:32 | [kelly] 冻结表缺失历史信号事件 8 个 | report | 同 #8 | 同 #8 |

按日汇总:10-09 下半夜 4 条 / 10-10 共 4 条(00:00 + 08:27 + 17:16 + 21:12)/ 10-11 共 8 条(alert_daily.json 实读 total=8:critical2/warning2/notice4)。

## 二、逐类定性(根因 8 类)

A. **failed unit 族(#4/#5/#9)= 真故障残留 + 已排观察**。unit=trade-nextday-gap-check(10-09 exit=2,东财 9:26 风控+旧兜底缺口;根因 #246 已修上云上,报告 docs/ops/gapcheck-failed-unit-rc-20261011.md)。「连续 N 天」= 通道级计数(failed_units_patrol_state.json:first=10-08,days=4)。Mon 00:00 会先发一条 critical(days=5),09:26 成功后自动清+恢复邮件;失败则按残余风险另立项。
B. **R2 上传族(#10 + 次生)= 真故障已修待验证 + 次生源活跃**。10-11 02:16 轮 verify-r2 抛 UnboundLocalError(standalone_files)→04:27 报。B6 修复 d9dbb97fa 已 merge+云上同步;今晚 22:30 update-all 周日 full 是修复后首次实战(观察点)。**次生活跃源**:upload-trade-sim 反复被看门狗「低速(近5min字节增量<1MB)」kill,10-11 三轮实证——16:51 轮/18:24 轮/21:16 轮。18:24 轮 kill 产生了 1 条「R2上传失败」告警但走 **over_budget digest**(alert_digest.jsonl 尾条,reason=over_budget:『通道 upload-trade-sim 本轮被看门狗超时 kill(force_full 未完成, PUT 未执行), 不适用轻量对账静音, 保留告警』)=即 18:45 ledger「warning 聚合 1 条」的来源;21:16 轮同形态 kill(日志明文)未见新告警条目(digest mtime 停在 18:24)=该轮被对账静音或缺口被覆盖。**结论:trade-sim 上传失败族在「发告警/不发告警」之间摇摆=不稳定次生源**(10-09 17:35 先例=直接 severe 上传流水)。
> **2026-10-11 夜更正注(watchdog 深挖实锤,报告 `watchdog-tradesim-slowkill-20261011.md`)**:本条三处表述更正——①「21:16 轮被对账静音」是误读:该轮 22:55 仍 active、从未跑到 finalize,告警尚未生成;②「18:24 轮」实为 16:51:48 启动的轮次;③「10-09 17:35 先例」实为 upload-index 通道(latest.md:280)。「发/不发摇摆」机制自洽非缺陷(dedup 6h+预算满→digest 幂等)。kill 根因三层(尾部等响应必然误判/梯度倒置 300s<600s 致内层自愈没机会跑/marker 残留→下轮全量)与治根方案见该报告。
C. **unit 漂移(#6)= 已闭环**。#248 三行同步 merge 后,10-11 08:27 patrol rc=0,是否再报=已止。
D. **warning 聚合容器(#11/#14)= 机制噪音/次生**。内容是单条 warning(04:30 与 18:45 各 1 条);18:45 那条来源已实锤=upload-trade-sim kill 的 over_budget digest 条目(见 §2-B)。04:30 那条内容同类(上传族 warning)。聚合器=schedule_monitor.sh;合并发送是本轮设计(防轰炸)。
E. **fetch_news r2_skip(#12/#15)= 自愈循环**。fetch_news 与 R2 上传锁竞争 SKIPPED_LOCKED→连续 3 轮发 severe(10-09 22:00 有)→恢复→先阻塞恢复通知轮换;10-11 05:00/19:00 两条恢复=两轮循环。属「设计内自愈」,但**每循环会产 severe+恢复 对**(10-09 22:00 一条 severe 入 severe 流水)。
F. **冻结表缺失(#8/#16)= 已知根因常态噪音**。_alert_frozen_missing(signal_kelly_backtest.py:316)每日 21:12 backfill_metrics 重生成时报「8 个事件」(信号类型漂移 buy→buy_aux 致缺键;9-21 sz_div 实例用户拍板「接受跳过」,根因未根治)。24h dedup 每日重置→每天一条 report。**每周 7 条级的固定噪音**。
G. **verify 脱节 notice(#7/#13)= 设计内**。verify-r2 兜底补传成功后的通知,10-10/10-11 各 2 轮(17:16、18:23)。性质=「补传成功了」的通知,可评估降为仅日志。
H. **恢复通知(#12/#15)= 正常机制输出**。

## 三、清零路径(分四区)

1. **已在轨、将自然收敛(预计 Mon 内)**:gap-check(#4/#5/#9):Mon 00:00 一条 critical 后,09:26 成功→自动清+恢复邮件;漂移(#6)已止。
2. **已修复待实战验证**:R2 上传族(#10):B6 修复后首次 full=今晚 22:30,明早核 rc/告警(本次已核实启动情况见附)。
3. **噪声待治(设计选择,需拍板)**:
   - 冻结表缺失 report 每天 1 条(治根:冻结键归一化;或降噪:改 info/白名单——须保留「真漂移」判别维度=错误类型区分,不可一刀切静音)。
   - verify 脱节 notice 每条补传 1 条(可降日志级:信息价值=已自动补齐,非需人工)。
   - fetch_news r2_skip 自愈对(severe+恢复成对;可评估 severe 降 warning/聚合)。
4. **真故障、无登记、需立项(窄口径「裸奔项」2 条)**:
   - **公募 10-08/10-09 净值全 NULL 未回填**:数据源早已有值(10-09 行 prev_unit_nav 非空 22089=10-08 净值,采集时已拿到,躺在错的行上);无自动回填路径——stage0-nav 周频增量按「基金代码 done_set」判定(10-09 01:43 那轮「待采 0」1 秒跳过 rc=0,不查日期完整性);backfill-nav 命令仅覆盖 200 只偏股。**时序**:10-12~10-16 每天 22:35 22:35 check_fund_nav_allnull 会照报 severe(检测:近 7 天窗内最近一个「非今日全 NULL 日」;10-17 出窗自然静默,但数据仍缺)。**行动**:一次性回填(全市场重采 10-08/10-09,或改 done_set 逻辑支持「日期缺口重采」)。
   - **trades 断档(最新 signal_date=20260930 落后)**:10-09 22:35 报 3 条族(断档 8 信号/信号日落后);10-12 22:35 复检必再报(kelly_coverage 检查)。**TASKS.md / pending-features-index.md / B 批残余汇总均无立项**(实查 grep 零命中)=真正未登记。**行动**:回填 etf_daily 10-08 起次日价→重跑 export/signal_kelly_backtest(告警原文建议路径);根因参考 docs/kelly/analysis/monitor-trades-stall-rootfix-20260908.md(9/7 断档同形态根治史)。
5. **可预期未来 72h 告警预判(基于机制实读,非黑盒)**:
   - Mon 00:00 critical(days=5)1 条;Mon 08:27 patrol rc=0 静默;Mon 09:26 gap-check 成功→恢复邮件 1 条(失败→次生按另案);
   - Mon 22:35 数据缺口族:公募 NULL severe 1 条 + trades 断档/落后 2 条(未回填则必报)=**3 条**;
   - 每天 21:12 冻结表 report 1 条(持续);
   - fetch_news r2_skip 视锁竞争 0~数条(自愈对)。

## 四、未登记/裸奔告警源(窄口径)

1. 公募净值回填(§3-4,无自动机制、无立项)
2. trades 断档(§3-4,无立项)
3. (减轻项)upload-trade-sim 低速 kill:不发告警但反复占用(18:24/21:16 轮),根因=上传速率低于看门狗阈;若某天对账兜不住会直接外发(10-09 17:35 先例)。

## 五、关键证据点(可复核)

- latest.md(云上 data/alerts/latest.md,369 行):severe 流水 10-05 13:30→10-11 04:27,本报告表 1 逐条对应;头部镜像当前=「10-11 19:00 恢复 fetch_news」
- alert_ledger.jsonl:10-10 08:27 起 11 行,10-11 的 8 条与 alert_daily.json total=8 逐一对齐
- failed_units_patrol_state.json:{"first_fail_date":"2026-10-08","consecutive_days":4,"last_grade_time":"2026-10-11 00:00:02"}
- alert_state.json:active 仅 2 键(nextday_gap_check 两键,first 10-09 09:45)
- check_fund_nav_allnull(本地 scripts/check_data_gap_alerts.py:807-869):dedup=同 key 每自然日 1 次(L85/L1592)
- fund_daily_nav 实查:10-08(24218 行,unit_nav 非空 0,prev_unit_nav 非空 22829)、10-09(24224,0,22089);9 月无全 NULL 先例
- stage0-nav:云上 trade-pf-stage0-nav.timer 周 5 01:43;10-09 01:43 轮日志「全市场27758只 days=1825, 已完成27758, 待采0」rc=0;增量判定=public_fund.py:5529-5531(done_set 按基金代码,与日期无关)
- backfill-nav 命令:public_fund.py:5472-5483(默认 200 只偏股,d500 天)
- r2_upload_async_20261011_211622.log:upload-trade-sim「低速(近5分钟字节增量<1MB), kill pid=...」→「失败/超时,继续」→purge 504/504 完成;service 22:11 后 inactive;ledger 无该轮新条目
- 本机:launchctl 仅 3 本地组件,无生产告警源(生产告警全在云上,本机不接收)
- 通道:表格逐条 channels={email:true,feishu:true};未发现 email-only 条目

## 六、22:30 #220/B6「周日 full」首实战观察(现场记录 22:30-22:32)

- **22:30:00** trade-update-all 触发;日志首行「交易日判断: IS_TRADING=0 FORCE=0 → 非交易日,跳过采集,仅 deploy 补推数据(不发信号邮件,force 可绕过)」;**22:30:01** 进入「deploy.sh 段1(锁外 export+R2+rsync)」;时段闸门放行(非交易日 22:30 不撞禁区);service=**activating**;截至 22:30:07 ledger 无新条目。
- **「首实战」的确切含义(本次实锤)**:verify-r2 在周日(weekday==6)走**「周日全量对账」**分支(本地 upload_r2.py:3610-3620,`full = today_weekday == 6`;每通道 HEAD 每本地文件、自动补传),而 10-11 02:16 轮崩溃点 standalone_files UnboundLocalError 恰在该 full 分支(代码注释 L3660-3661 原文:「必须两种模式都定义 —— 2026-10-11 hotfix: 原实现只在 else 分支赋值, full 模式 L3730 无条件引用 → UnboundLocalError, 周日全量对账崩溃、自动补传不执行」)⇒ **今晚 22:30 链内 verify-r2(full) = B6 修复后的直接重演现场**,验证价值高于普通轮。
- **明早观察点(核这几项)**:① update_all_20261011_2230.log rc/耗时(与 10-04 放慢日对照=#220)② deploy_20261011_2230*.log 的 verify-r2 段(不得再有 UnboundLocalError;补传计数)③ ledger 有无新「R2上传失败」④ r2_upload_async 新轮日志(如有)。
- 本记录止于 22:32(任务书要求不深挖,归明早观察点)。
