# 10-11 夜「十多条告警」复盘:窗口内 17 条构成、根因与到零差距(2026-10-12 早晨,只读)

> 执行:researcher 子 agent(全程只读:未跑任何业务脚本;云上零写入;无 commit/push;本文件为唯一新增,配套 commit 由主控执行)。
> 窗口:北京时间 **2026-10-11 18:00 ~ 2026-10-12 07:02**(核查截止时 a_fund_main 循环仍在跑,下一条预计 ~07:22)。
> 权威源:云上 `trade-data/data/alerts/{alert_ledger.jsonl, alert_daily.json, latest.md}`(ledger 全 24 行,窗口=行 8-24)+ 各 launchd 日志 + 本地代码 + 纯函数日历复算。

## 0. 速答(对应任务 5 问)

1. **总数 = 17 条**(18:00~24:00 共 **6 条** + 跨零点 11 条);每条都走 **email+feishu 双通道**(ledger 逐条 channels={email:true,feishu:true})⇒ 手机可见消息 = 17×2 = **34 条**,这是"十多条"体感的最直接来源。
2. **4 类**:（a) 已修但未上线 **5** 条 /（b) 真故障 **1** 条 /（c) 已知未闭环(含机制内) **4** 条 /（d) 昨日盘点没覆盖的新兑 **7** 条。
3. **到 0 差距清单**见 §3(7 个动作;最紧 = 停 a_fund_main 45min 循环,它此刻仍在复利)。
4. **新增判断**:B6 周日 22:30 full 首实战**成功但没有消灭告警**(verify-r2 无 UnboundLocalError ✓,但该轮仍以 R2 上传失败 severe 收尾);days=5 critical **如期而至**(00:00:07);未预测到 a_fund_main 循环 / 02:16:59 凌晨信号邮件 / 停滞通道首次触发(详见 §4)。
5. **诚实核查**:数字对得上,但 17 条里**真故障只有 1 条**;若严格只看"晚上 18-24 点"实际是 6 条(双通道=12 条消息);6 条 a_fund_main 是**同一条**循环重复 6 次(同 key),不是 6 个独立问题。

## 1. 逐条清单(17 条,ledger 行 8-24)

| # | 时间 | 来源 | 级别 | 标题(关键词) | 触发原因(一句话) | 证据 |
|---|---|---|---|---|---|---|
| 1 | 10-11 18:23:47 | r2_upload_async.sh | notice | 独立上传链产物与 R2 脱节(verify-r2 兜底补传) | verify-r2 发现独立链产物未及时上 R2、兜底补传成功后报"已补齐"(设计内通知) | ledger#8 key=499ec8489d1f;10-10 17:16 同型(锚点#7) |
| 2 | 10-11 18:45:20 | schedule_monitor.sh | warning | [告警·聚合] 1 条 warning 汇总 | 聚合容器;内容实锤=16:51 轮 upload-trade-sim 被看门狗低速 kill 的 over_budget digest 条目 | ledger#9 merged_count=1;锚点§2-D 实锤 |
| 3 | 10-11 19:00:13 | schedule_monitor.sh | notice | [恢复] fetch_news r2_skip_continuous | 自愈对"恢复腿"(R2 锁竞争解除后报恢复) | ledger#10 key=schedule_monitor_recovery;schedule_monitor_launchd.log L18441-18447 |
| 4 | 10-11 21:12:32 | backfill_metrics.sh | notice | [kelly] 冻结表缺失历史信号事件 8 个 | 每日 21:12 重生成冻结表时对 8 个"事后回填被前视闸拒"的 (date,index) 报缺失(直觉上"接受"但未落数据层) | ledger#11 key=signal_kelly_frozen_missing_small;锚点#16 |
| 5 | 10-11 22:50:34 | r2_upload_async.sh | notice | R2上传异步锁跳过 10-11 22:50 | 21:16 长轮次仍持锁 + 22:30 周日 full 轮撞锁 ⇒ 本轮跳过并写 pending 标记(设计内,由在跑实例收尾补跑) | ledger#12 key=r2_upload_async_skip;deploy_20261011_2230.log L766(22:50:29) |
| 6 | 10-11 23:30:26 | schedule_monitor.sh | digest | [告警·摘要] 当日合并 1 条 (deploy 1) | 当日 deploy 类直发预算已满,21:16 轮 R2 上传失败被"并入当日摘要",到 23:30 finalize 成摘要邮件 | ledger#13;211622 日志 L55 `[notify][budget] 并入当日摘要 key=deploy_r2_upload_fail` |
| 7 | 10-12 00:00:07 | schedule_monitor.sh | critical | 云上 failed unit 持续未清(连续 5 天,升级 critical) | unit=nextday-gap-check 未清天数达 5(通道级计数,锚点已预测) | ledger#14 key=64e119273471;latest.md L351 |
| 8 | 10-12 00:00:18 | schedule_monitor.sh | critical | 1 项计划任务异常 10-12 00:00 | fetch_news 因 R2 锁被长轮次占用,连续 6 轮 SKIPPED_LOCKED 达升级阈值(6)⇒ 升 SEVERE | ledger#15;schedule_monitor_launchd.log L18606-18609;latest.md L358 |
| 9 | 10-12 00:15:55 | r2_upload_async.sh | critical | R2上传失败 | 21:16 轮 trade-sim 被低速判据 kill(收尾真空误杀)→ 深夜 pending 补跑实际成功(103/103,377.5s)→ **失败通道标志残留** + verify-channels 对 R2_KILLED 直接判 bad ⇒ 跨零点(预算重置)后直发 severe | ledger#16 key=deploy_r2_upload_fail;211622 日志尾部(补跑成功行仍带 ⚠/✗ 判定);latest.md L365 |
| 10 | 10-12 02:16:59 | backfill_metrics.sh | notice | [买卖点信号] 20261009 主买×1 法国CAC40｜辅买×1 德国DAX｜追买×1 纳斯达克100 | 设计内「增量晚补」:凌晨查前一交易日、去重后只补发尚未通知的新信号(3 条)——周五 21:42 轮未覆盖到这批晚生成信号 | ledger#17;check_signals_20261012_0216.log(38 信号→新 3/已通知 35) |
| 11 | 10-12 02:17:46 | backfill_metrics.sh | notice | [告警] 信号凯利回测停滞 | max_signal_date=20260930 落后今日 **3 个交易日、首达阈值**(周一,国庆 10-01~07 非交易日把 lag 压住了) | ledger#18 key=654a9fa3d849;backfill_evening_launchd.log L44836-44841;日历复算见 §6 |
| 12-17 | 10-12 02:52:17 / 03:37:18 / 04:22:18 / 05:07:18 / 05:52:25 / 06:37:18 | self_heal.sh | notice ×6 | [告警][重采失败] a_fund_main 连续 3 轮重采失败 | 02:00 槽 backfill 对 a_fund_main 写 collect_log=error(自身已判"02:00 槽预期缺口,静默",但状态仍落 error)→ retry 机制无此豁免 → 每 15min 重试、达 3 轮发通知、发送后清零 ⇒ **每 45 分钟一条,循环未止** | ledger#19-24,同 key=1dffc3c82f4c;self_heal_audit.log;retry_failed_metrics_count.json={"a_fund_main":1};backfill_20261012_0200.log [gap] 行 |

> 附注:10-09 的 4 条 severe(22:35 族/23:30)只在 latest.md 流水(L295-316),**不在 ledger**(ledger 自 10-10 08:27 起)。

## 2. 四类归属(每类一句根因)

### (a) 已修但还没上线的噪音 — 5 条(1/2/3/4/9)
根因一句话:**两个待 merge 分支已覆盖但未上线**——降噪三项(分支 `worktree-agent-a56e10357ddd5bda5`,f275698a1)覆盖 #1/3/4(verify 脱节小规模降日志①/②、r2_skip 恢复腿走 info 仅 dashboard③);看门狗修复(分支 `feat/watchdog-lowkill-fix`,9cbb9060a)覆盖 #2/9(a2 收尾豁免消除"收尾真空误杀"→ 无 kill→无失败标志残留→无 18:45 聚合与 00:15:55 severe)。诚实标注:#1 是否命中"小规模"(单轮<3 文件且<1MiB且连续<3 轮)未逐条核规模;21:16 轮补传 11 个属大规模,照报——降噪②只静默小规模。

### (b) 真故障 — 1 条(#11)
根因一句话:**trades/信号断档未立项未回填**(max_signal_date 停在 20260930;昨日盘点已定性"无登记"的真故障),今天经"快照停滞检测"通道**首次触发**(09-28 后再没响过,国庆周压住 lag,周一 lag=3 达阈)。不改数据/不立项,今日 22:35 的缺口族(公募 NULL + trades 2 条,锚点§3-4)还会再报。

### (c) 已知未闭环(含机制内) — 4 条(#5/6/7/8)
根因一句话:#7 gap-check=已排观察(今早 09:26 自然验证,成功即自动清+恢复);#8 fetch_news 自愈对(L3c 设计内,锁竞争触发升级;与 #9 同源=长轮次占锁,看门狗修复降低复发);#5 锁跳过=设计内(有实例在跑负责补跑);#6 digest=预算合并机制本体(本次触因=R2 失败被吸收)。

### (d) 昨日盘点没覆盖的新兑 — 7 条(#10 + #12-17)
根因一句话:①**a_fund_main 45min 误报循环**(机制缺陷:backfill 对 02:00 槽结构性预期缺口仍写 error,retry 链无豁免 ⇒ 重试→通知→清零→再重试的无限环,今天是周一(周末 retry 跳过)首次引爆,累计贡献 6/17 且**仍在增长**);②**凌晨 02:16:59 发信号邮件**(设计内"增量晚补"但时点/体感是新增量)。

## 3. 「到 0 条」差距清单(动词开头,最紧排前)

1. **停** a_fund_main 45min 循环:改 `retry_failed_metrics.py` 认「02:00 槽预期缺口」豁免(或 backfill_direct_metrics 对结构性预期缺口不写 error)→ 消 #12-17 及后续每 45min 1 条(**此刻仍在跑**)。
2. **merge** 降噪三项(`worktree-agent-a56e10357ddd5bda5`,f275698a1)→ 消 #4(及每天 21:12 固定条)、#1 类(小规模)、#3 类恢复腿。
3. **merge** 看门狗修复(`feat/watchdog-lowkill-fix`,9cbb9060a)→ 消 #9/#2 根因(trade-sim 误杀链),并降低 #5/#8 复发(轮次缩短→锁竞争减轻)。
4. **回填** trades/信号断档(etf_daily 10-08 起次日价 → 重跑 export/signal_kelly_backtest;锚点§3-4 同路径)→ 消 #11 + 今日 22:35 缺口族。
5. **等** 今早 09:26 gap-check 自然成功(已观察中;失败则按锚点残余风险另立项)→ 消 #7 并出恢复。
6. **拍板**「增量晚补」信号邮件时点(凌晨发信号邮件是否改晨间汇总/静默)→ 消 #10 体感。
7. **修**跨日 rollover 语义(预算/digest 吸收过的事件,次日 finalize 会重新直发;与"防轰炸"语义冲突;本次 #6 被吸收 vs #9 隔日重发的组合即此)→ 防"同一事件隔日再响一遍"复现(**本次新发现,建议立 pending 项**)。

## 4. 新出现/未预测到的项(④)

- **B6 周日 22:30 full 首实战:来了。** 22:30:00 触发、非交易日仅 deploy、22:40:50 退出码=0;其 R2 上传被锁跳过(22:50:29 写 pending)→ 由 21:16 实例收尾补跑;verify-r2(周日 full 分支)实跑 **`✓ 对账完成, 自动补传 11 个`,无 UnboundLocalError** ⇒ B6 修复生效(证据:211622 日志 L51;10-12 02:16/05:10 两轮 UnboundLocalError 计数=0)。**但该轮最终仍以"R2上传失败"severe 收尾**(#9)——修掉的是"崩溃",没修"误杀链"。
- **days=5 critical:如期而至**(00:00:07,与锚点预判一致);09:26 是否恢复待今日验证(alert_state.json 两个 nextday_gap_check 键仍 active)。
- **未预测到 3 项**:①a_fund_main 45min 循环(最大新增源,6/17);②02:16:59 凌晨信号邮件;③停滞通道首次触发(机制休眠 2 周后 09-28 以来第一次)。
- **锚点一处被证伪**:锚点曾预期 21:16 轮 R2 族"digest 幂等命中、不新增"——跨零点(budget 重置+dedup 6h 窗已过)导致 00:15:55 直发,rollover 未覆盖。

## 5. 与昨天那份(alert-triage-20261011.md)的关系 + 诚实反向核查(⑤)

- **关系 = 子集 + 延续 + 跨零点新增**:窗口 17 条中 4 条(#1-4)是昨天那份(16 条/8 类)已覆盖条目的延续;13 条(#5 起)为锚点写作(10-11 22:20)后新发生。锚点§5 预判兑现 3 项(days=5 / fetch_news 自愈对 / 每日 21:12 冻结表);待验 2 项(09:26 恢复 / 22:35 缺口族=今日)。
- **反向核查 1(数字)**:严格"晚上 18-24 点"= 6 条;双通道 ×2 = 12 条消息;含跨零点到 07:02 = 17 条(×2=34 消息)。"十多条"对得上,但**不要**理解成 17 个独立故障——真故障仅 1 条(#11),6 条是同 key 循环(#12-17),2 条是恢复/摘要机制输出(#3/#6)。
- **反向核查 2(登记点)**:没有发现"email-only 旁路"条目;恢复通知/摘要未被误当新故障(已剔除)。发现的登记不一致仅一处(非告警):latest.md 头部「最近一次 SEVERE」区块由 --alert-issue 覆盖式写入(仅计划任务监控路径),R2 族 severe 只进下方流水 ⇒ **头部(00:00:18)落后于流水末(00:15:55)**,单看头部会漏最新 severe(呼应 L46:单一登记点沉默≠无告警)。

## 6. 关键证据点与复算(可复核)

- ledger 行 8-24 见 §1 逐条;`alert_daily.json` 10-12:total=11(critical 3/notice 8)与跨零点 11 条逐一对齐(3=#7/8/9;8=#10/11+6 循环)。
- **停滞为何周一才响**(日历纯函数复算,本地只读):`trading_days_between('20260930','20261012')`=[0930,1008,1009,1012] → lag=3(达阈);而 10-09/10/11 复算 lag 均=2(国庆 10-01~07 全非交易日、10-10/11 周末,trading_days_between 只数交易日)⇒ "周末各轮通过、周一 02:17:46 首触发"与机制完全自洽。
- 211622 日志关键行:kill 行(近 5 分钟低速)→ `[verify-r2] ✓ 对账完成, 自动补传 11 个` → L55 预算并入 → `检测到并发跳过标记 ... 增量补跑` → `[trade-sim] ✓ 103/103, 377.5s(较全量少传 0 个)` → 尾部仍 `⚠ 失败通道`/`✗ rc=1` → 直发 severe(00:15:55)→ 镜像+ledger+dedup 全链。
- 循环链证据:`backfill_20261012_0200.log` `[gap] a_fund_main direct:market_fund_flow 多源皆败无数据 (02:00 槽预期缺口, 静默)` + collect_log(20261012,error,02:17:42) + self_heal_audit.log 每轮 `[retry] 发现 1 个 error 指标` → `[fail]` → 每 3 轮 `[notify]`。
- 本地代码锚点:signal_kelly_snapshot.py L392-409(detect_stagnation,STAGNATION_LAG_ALERT_TD=3)、L481(today_str=now)、L515-522(恢复去日期化 dedup key);retry_failed_metrics.py RETRY_NOTIFY_THRESHOLD=3;backfill_direct_metrics.py 02:00 槽预期缺口判定;r2_upload_async.sh 看门狗(L102-187,待上线分支已改)。

## 7. 复现命令(本次实际跑过的只读命令)

```bash
# 清单/逐条(云上,只读)
ssh -i /Users/linhuichen/tdsignal.pem ubuntu@122.51.111.173 \
  'python3 -c "import json; rows=[json.loads(l) for l in open(\"/home/ubuntu/code/trade-data/data/alerts/alert_ledger.jsonl\") if l.strip()]; print(len(rows)); [print(json.dumps(r,ensure_ascii=False)[:330]) for r in rows[-12:]]"'
# 停滞复算(本地纯函数,不触业务链)
.venv/bin/python -c "import sys; sys.path.insert(0,'/Users/linhuichen/code/trade'); from app.calendar import trading_days_between as tb; print(tb('20260930','20261012'))"
# 21:16 轮收尾(云上)
ssh ... 'grep -n "verify-r2|UnboundLocalError" data/logs/r2_upload_async_20261011_211622.log; tail -45 data/logs/r2_upload_async_20261011_211622.log'
```

## 8. 口径与边界(诚实标注)

- 只读边界:未执行任何业务/采集脚本;python 仅做日历纯函数复算(不 import 业务链、不落盘);云上零写入。
- 数据截止 2026-10-12 07:02;CST;a_fund_main 循环 06:37 后仍在(下一条 ~07:22),本报告 17 条为截至时刻口径。
- 未核实项:#1 的脱节规模(是否小规模)、#3 恢复腿的档位在降噪③口径下是否精确命中,均以实施分支口径为准。
