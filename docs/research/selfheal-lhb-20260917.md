# self_heal log_anomaly 误判 + lhb NoneType 双链异常根因(2026-09-17 调研)

调研 agent 只读调研,不实施。两块异常同源触发(09-17 00:07 的 heal 是 A 块,heal 重跑又把 B 块带出来),分别定性如下。

## A. self_heal 触发 3 个 log_anomaly heal(exit=0 却 heal)

### 结论一句话
不是判定 bug 的"误判",也不是日志虚假:09-16 20:05/21:00 三份任务日志里**真的有 Traceback**(SDC 子进程真崩溃,被 export 设计为"不阻塞"吞掉,但 stderr 前缀含 `Traceback (most recent call last):` 被打进任务日志)→ 异常扫描按设计命中 → log_anomaly=True → self_heal 按"第4盲区修复"设计对 exit=0+log_anomaly 触发 heal。缺陷在**heal 目标错位 + stats 追尾 + 每日额度被 00:07 一次性用尽**。

### 根因链(证据锚点)
1. **真实崩溃**:`scripts/signal_kelly_backtest.py` SDC 模式(env `KELLY_BUY_NEXTDAY=0`)里 `_backtest_one` 两处 `round(real_buy, 6)`,QDII 净值 T+1 发布、信号日 close/open 都缺时 real_buy=None → `TypeError`。修复提交 `2f0da9ba3`(09-16 22:51,本地 git 可见):commit message 原文 "Bug1: QDII 净值 T+1 发布, 信号日 close/open 都缺时 real_buy=None, _backtest_one 两处 round(real_buy, 6) 崩 TypeError 致 sdc 生成失败 rc=1";diff 两处改 `round(real_buy, 6) if real_buy else 0`。
2. **吞掉但留痕**:`static-site/export.py` L1248-1262:`_sk_sdc = subprocess.run(...)` 后失败分支 `print(f"  signal_kelly_backtest_sdc.json: 失败 rc={_sk_sdc.returncode} stderr={_sk_sdc.stderr[:200]}(#91 对比档, 不阻塞 export)")`——stderr[:200] 恰好含 "Traceback (most recent call last):" 及第一帧。
3. **扫描误食**:`scripts/gen_schedule_stats.py` `scan_log_anomaly`(L214 起)的 `ANOMALY_RE` 第一分支 `Traceback \(most recent call last\)` 命中即报,不看 exit(L295-301);写进 `static-site/data/schedule_stats.json` 的 `log_anomaly/log_anomaly_keyword/log_anomaly_line` 字段。云上实读:三个任务 keyword="Traceback (most recent call last)"、line="signal_kelly_backtest_sdc.json: 失败 rc=1 stderr=Traceback (most recent call last):"。
4. **设计内触发**:`scripts/self_heal.sh` L192-195:`log_anomaly = s.get("log_anomaly", False)` + `if (exit_code is None or exit_code == 0) and not log_anomaly: continue`——log_anomaly=true 时 exit=0 也 heal,L194 注释"第4盲区修复: log_anomaly=true 时即使 exit=0 也 heal(脚本吞异常场景)"。这是设计行为,不是新 bug。
5. **时间线**(云上日志锚点):
   - 09-16 18:50 前后(update_all 17:50 窗口):SDC 生成成功(update_all_launchd.log L60 `signal_kelly_backtest_sdc.json (513139 bytes, #91 对比档)`,update_all 无 ANOMALY 标记)。
   - 09-16 20:40 前后(lhb 20:05 窗口,lhb_backfill_launchd.log L939)/ ~22:10(futures 21:00 窗口,futures_backfill_launchd.log L1168)/ ~22:40(backfill_evening 21:00 窗口,backfill_evening_launchd.log L5420):三次 export 的 SDC 子进程都崩,L1168 窗口上下文可见完整输出顺序(崩溃行前后是 export 文件清单)。
   - 09-16 22:51 本地 fix 提交 2f0da9ba3;09-16 23:11 merge(feat/sdc-real-buy-fallback) 入 main;云上 23:16 `pull --ff-only`(云 git reflog HEAD@{09-16 23:16})。
   - 09-17 00:07 self_heal 用**旧 stats**触发 3 个 heal(self_heal_audit.log `[2026-09-17 00:07:02] HEAL backfill_evening/futures_backfill/lhb_backfill reason=log_anomaly`)。此时 fix 已上线——heal 是"追尾自愈"。00:47 bfe heal 重跑 export 时 SDC 已成功(backfill_evening_heal.log L630 `signal_kelly_backtest_sdc.json (513675 bytes, #91 对比档)`)。
   - 09-17 02:00 bfe 常规跑:SDC 成功 513675B、log_anomaly=false(schedule_stats.json 当前值,backfill_evening_launchd.log L6278)。
6. **每日循环模式**:09-16 00:07 同样 heal 了 3 个(09-15 晚间同类异常:backfill_evening 21:00、intraday_snapshot 20:35、etf_nt exit=1),当天 3/3 额度用尽 → 09-16 全天 20:07 起 audit log 全是 `LIMIT 达上限 count=3`(每 15 分钟一条)→ 09-16 晚间新异常无法当天 heal,只能等 09-17 00:07 计数重置。即:A 块"为什么 00:07 才 heal"= 前一天的额度耗尽,不是调度延迟。

### 定性
- 日志真有问题:是(09-16 20:05-22:44 窗口 SDC 子进程真崩 3 次,已由 2f0da9ba3 修复,02:00 起恢复)。
- 判定误判:否(扫描机制按设计工作;判定的代价=把"已知非阻塞失败"升级为任务级异常)。
- 真正的缺陷:① wrapper 把 Traceback 文本打进共享任务日志,扫描无法区分"设计内非阻塞失败"与"真异常";② heal 对象错位(重跑 backfill/futures/lhb 修不了 sdc 崩溃);③ heal 读的 stats 可能已过时(不比对代码 HEAD 拉取时间);④ 00:07 用尽额度压死当天真异常(连带效应)。

### 建议修法(只建议)
1. export.py L1262/L1237:失败日志去掉 Traceback 文本,改打 `stderr` 最后一行(异常类型+消息)或 rc+文件名摘要;或 scan_log_anomaly 白名单:行匹配 `^\s*\S+\.json: 失败 rc=\d+ stderr=` 且文件名 ∈ EXPORT_MANIFEST_WARN 集 → 不报。
2. self_heal 触发 log_anomaly heal 前,比对 stats 生成时间与云 git HEAD 拉取时间,stats 早于最近一次 pull 且 fix 涉及该任务链 → 跳过(或 heal 后立即重跑 gen_stats)。
3. 根修已闭环(2f0da9ba3 已上线),无需再动。

## B. lhb 龙虎榜采集 NoneType(retry_failed_metrics 持续 2 error)

### 结论一句话
不是接口改版、不是反爬:是**查了"数据未发布"的日期**(09-17 00:07 heal 采"当天",龙虎榜 ~18:00 才发布),东财 API 对该日期返回 `{"result":null,"success":false,"code":9201,"message":"返回数据为空"}`,akshare `stock_lhb_detail_em`/`stock_lhb_jgmmtj_em` 对 result=null **无容错**直接 `data_json["result"]["pages"]` 抛 `TypeError: 'NoneType' object is not subscriptable`;我方 collect_snapshot 把它记成 collect_log error → retry_failed_metrics 每 15 分钟重试"当日" error → 永远失败直到当晚数据发布。**09-16 的 lhb 数据实际完好无缺口**(17:50/18:30/20:05 三次 ok=73 条)。

### 证据锚点
1. 东财 API 直连(curl,只读):filter 2026-09-17 → `{"version":null,"result":null,"success":false,"message":"返回数据为空","code":9201}`;filter 2026-09-16 → `{"result":{"pages":1,"data":[{"SECURITY_CODE":"000592"}...`(73 条)。
2. akshare 源码(本地 venv site-packages,版本 1.18.64 与云一致):`akshare/stock_feature/stock_lhb_em.py` L47 detail:`total_page_num = data_json["result"]["pages"]`;L255 jgmmtj:`total_page = data_json["result"]["pages"]`——result=None 时此处必抛 TypeError,无任何 null 检查。
3. 本地复现(同版本 venv,只读网络调用):`ak.stock_lhb_detail_em(start_date='20260917', end_date='20260917')` → `TypeError 'NoneType' object is not subscriptable`;`('20260916','20260916')` → `DataFrame len 73`。异常消息与云上 collect_log 逐字一致。
4. 云 collect_log(/home/ubuntu/code/trade-data/data/sentiment.db,表 collect_log):
   - 20260916 lhb_count/lhb_inst_net 三条 ok:17:50:30(update_all,73.0)、18:30:03(lhb单采 73)、20:05:29(lhb单采 73/5.207 亿)→ 09-16 无缺口。
   - 20260917 两条 error:run_at=2026-09-17T00:07:09/00:07:14,message=`stock_lhb_detail_em error: 'NoneType' object is not subscriptable` / jgmmtj 同款——**由 00:07 heal 自己写入**(lhb_backfill_heal.log:00:07:02 一轮 `[lhb] date=20260917 ok=0 fail=2`;09-15 00:07 那轮 `date=20260915` 同理)。
5. 日期口径:`scripts/lhb_backfill.sh` 采集 `date = last_trading_day()`;`app/calendar.py` L75-84 last_trading_day 从"今天"往回找第一个交易日,00:07 时 09-17 本身是交易日 → 返回 20260917(当天,未发布)。`scripts/retry_failed_metrics.py` main():`today = dt.date.today()`,只重试"当日"error(L~136),失败保留等 15 分钟再试 → 00:22/00:37 audit 可见持续 2 error 的自伤循环。
6. 社区/上游(L47):PyPI 最新 akshare 1.18.95(2026-09-16 发布),拉取 main 分支源码确认两个函数仍是裸 `data_json["result"]["pages"]`(L46/L255)未加 null 容错;GitHub 搜 stock_lhb_detail_em 共 4 条 issue(2022-2025,无此 NoneType 报告)→ **升 akshare 版本不能解决,必须本地兜底**。

### 定性
数据源外部原因(当日未发布是正常业务行为)+ akshare 上游无容错(久已有之,未修)+ 我方把"未发布"当 error 记录并进入重试循环。09-16 数据无缺口,retry 循环是虚惊,18:30 当晚正式采后自然清。

### 建议修法(只建议)
1. `app/collector/fetchers.py` collect_snapshot:DATE_RANGE_FUNCS 的调用若抛 TypeError 且消息含 "NoneType object is not subscriptable"(或东财 code=9201),识别为"源未发布/无数据",返回 `(None, "源未发布")` 并写 collect_log warn 而非 error(与 lhb_backfill.sh 已有的"无新数据 exit 0"分支语义对齐)。
2. heal 场景日期修正:lhb_backfill.sh(及其它单采脚本)force/heal 重跑时,若当前时间 < 18:00,date 取上一完整交易日(lhb 数据 T 日 18:00 后才完整),避免凌晨 heal 采"当天"。
3. retry_failed_metrics:error 消息含 "NoneType object is not subscriptable" 且当前时间 < 17:30 → 跳过不重试(等正式采集),不再每 15 分钟空转。

## 复现段
- A 块无脚本复现,证据=云日志行号 + git 提交 diff:
  `git -C /Users/linhuichen/code/trade show 2f0da9ba3 -- scripts/signal_kelly_backtest.py`
  `ssh ... 'grep -n "signal_kelly_backtest_sdc" /home/ubuntu/code/trade-data/data/logs/{futures,lhb,backfill_evening}_launchd.log'`
  `ssh ... 'git -C /home/ubuntu/code/trade-data-signal reflog -10'`
- B 块复现(本地,只读):
  `curl -s "https://datacenter-web.eastmoney.com/api/data/v1/get?...reportName=RPT_DAILYBILLBOARD_DETAILSNEW&filter=(TRADE_DATE<='2026-09-17')(TRADE_DATE>='2026-09-17')"`
  `/Users/linhuichen/code/trade-data/.venv/bin/python -c "import akshare as ak; ak.stock_lhb_detail_em(start_date='20260917', end_date='20260917')"`
  (0917 → TypeError;0916 → len 73)

## 证据锚点汇总
- 本地:`/Users/linhuichen/code/trade-data/scripts/self_heal.sh` L192-195、L280;`scripts/gen_schedule_stats.py` L214-301(scan_log_anomaly+ANOMALY_RE);`static-site/export.py` L1248-1262;`scripts/signal_kelly_backtest.py` L778/L827(fix 后);`app/calendar.py` L75-84;`app/collector/fetchers.py` L564-598;`scripts/retry_failed_metrics.py` L~136;`scripts/lhb_backfill.sh`(date=last_trading_day);venv akshare stock_lhb_em.py L47/L255。
- 云上:`data/logs/self_heal_audit.log` 09-16 20:07~23:52 LIMIT 串 + 09-17 00:07 HEAL×3;`futures_backfill_launchd.log` L1168/L1223;`lhb_backfill_launchd.log` L939/L994/L3114;`backfill_evening_launchd.log` L5420/L5475/L6278、窗口 L4089-6141(21:00)/L6157-6604(02:00);`*_heal.log`(00:07 重跑结果);`static-site/data/schedule_stats.json`(futures/lhb 仍 anomaly=true,futures last_run=09-16 21:00);`sentiment.db collect_log`(0916 ok×3 / 0917 error×2 run_at 00:07);云 git 仓库=/home/ubuntu/code/trade-data-signal,reflog 23:16 pull 0cd7bba1d。
- 上游:PyPI akshare 1.18.95(09-16);akshare main 分支 stock_lhb_em.py 仍裸下标(GitHub issue 检索 4 条均不相关)。

## 配套说明
纯日志/代码调研,无生成脚本;本文件即四件套(本体+复现段+证据锚点+上述命令)。commit 由主控收尾统一处理。
