# 告警降噪执行方案(2026-09-29 用户拍板)

> researcher 调研产出落档 | 依据 09-28 夜调研报告(14 天趋势/今日逐条分档/C 类根因/dedup 失效)
> 目标:一天 1~2 条甚至 0 条,告警不再像"任务通知"。实施 agent 按本文件 9 条改动逐一落地。

## 0. 结论摘要

- **今天(09-28)19 条告警 = A 类噪音 11 条(58%) + B 类判定缺陷 3 条 + C 类 4 条(3 条同一根因) + 待核 1 条**。A 类 11 条是"告警像任务通知"的主因:全是单次触发/阈值时机不当,发完就自愈,没有一条需要用户当天处理。
- **C 类定性(2026-09-29 已按权威根因修正,见 §3)**:signal_kelly_trades.json 停在 20260922 **不是流水线故障**——09-23 起宇宙内无新可入账信号(正常空窗),唯一真缺口=`sz_div@09-22` 被防前视冻结闸永久拒(1 笔历史)。已按用户拍板 #125 方案①「接受缺口 + 降噪」对冻结缺失降 WARN,不再每天 SEVERE。
- 按本方案 4 步走(①降 A 类 → ②修 dedup/合并同源 → ③C 类冻结缺失降噪 → ④修净值口径),日常可到 **0~1 条/天**;只做①可到 8 条/天。

---

## 1. 14 天趋势表(飞书 alert 群口径,告警/恢复分开;邮件与飞书同源一致)

| 日期 | 总条数 | 告警 | 恢复 | 备注 |
|---|---|---|---|---|
| 09-15 | 40 | 24 | 15 | 上周高水位 |
| 09-16 | 30 | 16 | 14 | |
| 09-17 | 20 | 13 | 6 | |
| 09-18 | 31 | 19 | 8 | |
| 09-19 | 17 | 7 | 9 | |
| 09-20 | 25 | 15 | 10 | |
| 09-21 | 24 | 13 | 8 | |
| 09-22 | 28 | 19 | 8 | 本周高水位 |
| 09-23 | 31 | 22 | 3 | 本周最高 |
| 09-24 | 26 | 14 | 5 | |
| **09-25** | **3** | **2** | **1** | 骤降(当日异常本就少) |
| **09-26** | **1** | **1** | **0** | 周六非交易日,只剩 staticdata oversize 1 条 |
| 09-27 | 8 | 6 | 2 | 周日 |
| **09-28** | **21** | **19** | **2** | 今天 |

- **近 7 天(09-22~09-28)告警日均 11.9 条;前 7 天日均 15.3 条**。今天 19 条告警 = 目标上限(2 条)的 **9.5 倍**,日均 = 目标上限的 **6 倍**。
- **09-25/26 骤降不是降噪生效,是当天异常本就少**(09-26 周六非交易日只剩 staticdata 备份 1 条例行提醒;09-25 周五 3 条)。09-28 周一恢复交易日,告警立刻回 21 条。
- **8 月底降噪确实生效一部分**:对比 09-10 盘点时"近 14 天 55 封",update_all 耗时告警、telegram FAIL 已消除(0 条);但新一批"单次触发误报"类告警(R2 lag/intraday 漏跑/超时/排队)顶上,日量仍在 15~20 条。

---

## 2. 今日(09-28)21 条逐条分档(A 噪音 / B 判定缺陷 / C 真 bug)

| # | 时间 | 消息 | 判定 | 类别 |
|---|---|---|---|---|
| 1 | 02:34 | 信号凯利回测停滞(第 1 次) | 真信号,同 C 根因 | C |
| 2 | 02:45 | [恢复] backfill_evening dur>4500s | 恢复通知 | 恢复 |
| 3 | 13:45 | R2 intraday_snapshot.json 时效滞后 lag=19min | 单次滞后误报(R2 仍有 13:25 版,检查落在上传间隙) | A |
| 4 | 14:15 | R2 intraday_snapshot.json 时效滞后 lag=19min | 同上第 2 次 | A |
| 5 | 15:15 | intraday_snapshot 漏跑(15:02) | 已自愈(15:35 轮 exit=0) | A |
| 6 | 16:00 | intraday_snapshot 907s 超阈值 600s | 一次性偏慢(正常 286s),已 exit=0 | A |
| 7 | 16:51 | 信号凯利回测停滞(第 2 次) | **dedup 失效**:同 key 24h 内 2 次 | B |
| 8 | 19:03 | staticdata 备份 oversize(510 文件/872MB) | 例行提醒,非故障(仅留档未 commit) | A |
| 9 | 19:45 | lhb_backfill 漏跑(19:30) | 已自愈(19:54 补跑 exit=0) | A |
| 10 | 19:54 | staticdata 同步 oversize(news-fetch 触发) | 例行提醒,同 #8 | A |
| 11 | 20:15 | [恢复] etf_national_team exit=1 | 恢复通知 | 恢复 |
| 12 | 20:45 | gen_daily_brief R2_UPLOAD_TIMEOUT | 误报/兜底已自愈(R2 data/daily_brief.json HTTP 200) | B |
| 13 | 21:00 | intraday+s06 超时未完成 25min | 误报(20:35 轮 exit=0,1505s 慢但完成;s06 机检 PASS) | A |
| 14 | 21:05 | with_lock 排队超时跳过 /tmp/trade_deploy.lock | 误报(deploy 实际 21:08-22:16 exit=0) | A |
| 15 | 21:40 | 过拟合 60 分综合红区 | 真信号(risk=60,近 45 天最高档) | C/真信号 |
| 16 | 21:40 | 卖出模式微扰翻转 D3=90 | 真信号(近 45 天唯一一次) | C/真信号 |
| 17 | 22:30 | backfill_evening 超时未完成 90min | 慢但完成(deploy 日志全 ✓) | A |
| 18 | 22:35 | ETF 累计净值新增缺价 227 条(warn) | 待核:含 512660 军工等 A 股 ETF 缺 09-28 当日净值,疑净值时点口径 | B 待核 |
| 19 | 22:35 | [严重] 交易记录断档:1 入样信号无交易(深度 3) | **C 类真 bug**(09-24 起每天发) | C |
| 20 | 22:35 | [严重] 交易记录最新信号日 20260922 落后 | **C 类真 bug**(同 #19 根因) | C |
| 21 | 22:35 | 最近 deploy 无成功标记(kelly 产物未刷新) | 误报(22:28 deploy 正常,22:35 检查时未跑完) | A |

**计数:19 告警 = A 11 + B 3 + C 4 + 待核 1**。恢复 2 条。

---

## 3. C 类定性(最新权威结论:链路正常,唯一真缺口=冻结闸拒,已降噪)

> ⚠️ 本段 2026-09-29 由实施 agent 依据 `docs/sigkelly-gap-rootcause-20260928` 分支 `docs/kelly/analysis/sigkelly-gap-20260923-rootcause.md`(09-28 权威根因调研)**修正**——原「C 类真 bug = signal_kelly_trades 停在 09-22 必须修链路」的初判已被证伪。

**结论一句话:不是流水线故障。** 09-23 起宇宙内没有新的可入账信号(市场 + 宇宙规则自然结果),`signal_kelly_trades.json` 停在 09-22 是**正确状态**;唯一真缺口 = `sz_div@09-22` 被防前视冻结闸永久拒(1 笔历史,不可自动修复)。

证据链(逐环节正常):
1. **流水线是活的**:09-28 SDC 档(当日收盘价规则)已含 `csi_H30199` 44 行,冻结表 `20260928|csi_H30199|buy_aux→159059`(frozen_at 22:24)已冻结;主档 NDO 无 09-28 行是 by design(次日 09-29 开盘价才入账)
2. **09-23 起无新可入账信号**:09-24 `cgb_10y_etf`/`hk_cesg10` 全命中宇宙排除类别(`universe_rules.yaml` excluded_categories:债类/港股行业等),不入样 = 正常空窗
3. **唯一宇宙内入样却缺 trade = `sz_div@09-22`**(09-23 09:40 intraday-rerun 也无声,事后延迟回填进 signal_daily,撞 `signal_kelly_backtest.py:436-440` 防前视冻结闸「date < latest_signal_date 且无冻结值 → 拒绝补冻」)→ **永久无法入账**
4. **09-23 sz_div「严格消失」是正常收盘修正 + 暴露孤儿冻结脏数据**:盘中推 buy → 收盘重算 RSI 不再上穿 30 → 信号移除,`20260923|sz_div|buy→159905` 冻结孤儿残留(不碍功能)

**处置(2026-09-29 用户已拍板 #125 方案①「接受缺口 + 降噪」)**:`check_data_gap_alerts.py` 对「冻结缺失但次日价已齐」这类历史回填信号降 WARN/豁免(本方案改动 8/附段落地),不再每天 SEVERE。孤儿冻结清理、`csi_H30199@09-28` 主档入账均无需实施侧处理(见权威根因文档 §7)。

---

## 4. 判定原则 + 点名任务通知类

**原则**:告警 = 需要用户/主控**当天采取动作或知道真相**的事件。任务执行结果/瞬时抖动/例行提醒一律不告警。

**今天点名的任务通知类(全部降级或删除)**:
- staticdata 备份/同步 oversize ×2(19:03/19:54):备份留档提醒 → 降 info,每周汇总一次
- R2 intraday 时效滞后 ×2(13:45/14:15):单次 19min 滞后 = 上传间隙,非断供 → 连续 ≥3 轮仍滞后才 SEVERE
- intraday 漏跑 ×1(15:15)与超时 ×2(16:00/21:00):单次自愈 → 连续 2 轮才 SEVERE 或并入日报
- lhb 漏跑(19:45)、with_lock 排队超时(21:05)、deploy 无成功标记(22:35)、gen_daily_brief R2 超时(20:45):全部"最终成功/已自愈" → 收尾确认后不发(参考 deploy R2 延迟到收尾先例)
- backfill_evening 超时 90min(22:30):任务变慢但完成 → 阈值重标或并入日报
- 信号凯利停滞 ×2(02:34/16:51):去重失效 + 与 data_gap 断档重复 → 修 dedup,停滞与断档二选一(断档更有信息量)

**保留(真告警)**:overfit 红区×2、数据缺口类。交易记录断档/落后×2 已按 #125 方案①对冻结缺失降 WARN(2026-09-29,见 §3);若出现真断档形态(缺次日价/评级缺失外的新缺口)仍正常 SEVERE。

---

## 5. 量化路径(①②③④ → 0~1 条)

| 步骤 | 砍掉 | 今天剩 |
|---|---|---|
| 现状 | — | 19 条告警 |
| ① A 类 11 条全降(阈值/连续轮/收尾确认/降 info) | 11 | **8 条** |
| ② 修 dedup + 合并同源(停滞+断档+落后→1 条,overfit×2→1 条) | 4 | **4 条** |
| ③ C 类冻结缺失降 WARN(#125 方案①,消停滞+断档+落后 3 条) | 3 | **1 条** |
| ④ ETF 净值缺价口径修(QDII/当日净值时点) | 1 | **0~1 条** |

- **目标达成**:①②③④ 全做 → 日常 0~1 条(仅 overfit 触发日 1 条),大部分交易日 0 条;真故障照发。
- 只做 ①② → 3~5 条/天;只做 ① → 8 条/天。**③ 是降 WARN 而非修 bug(2026-09-29 权威根因确认链路正常,见 §3),若未来出现真断档形态(缺次日价/新缺口)仍正常 SEVERE。**

---

## 6. 9 条可执行改动(实施 agent 按此落地)

> 每条:文件:行号 + 现状 + 改法 + 风险对冲(最坏漏什么)。全部只动告警判定/展示,不碰数据链路与产物。

### 改动 1:r2_intraday_lag 加连续轮 + 阈值放宽
- **文件:行号**:`scripts/schedule_monitor.sh` L1525-1559(R2 intraday_snapshot.json 时效检查)
- **现状**:单次 lag>15min 即发 SEVERE(`id_thresh_r2 = timedelta(minutes=15)` L1537,`if id_lag_r2 > id_thresh_r2` L1538)。13:45/14:15 各 1 封=检查落在上传间隙的瞬时滞后。
- **改法**:①阈值 15min→20min;②参照 L271/L529 连续 N 轮机制,同 key 连续 ≥3 轮(≈45min)仍滞后才 SEVERE(首次发现记 active 但只发 info/warn,连续才升 severe);恢复检测保留。
- **风险对冲(最坏漏什么)**:R2 真断供(intraday_snapshot.json 长期不更新,前端分时读旧)→ 对冲:连续 3 轮仍滞后必 SEVERE;且主站 overview 时效检查维度⑤(L1245-1360)仍单次拦,双保险;数据缺口检测器兜底。

### 改动 2:intraday 漏跑连续 2 轮才 SEVERE
- **文件:行号**:`scripts/schedule_monitor.sh` L274-329(漏跑检查,L315 首次即发 SEVERE)
- **现状**:单次漏跑(15:02 计划时点漏跑)即发 SEVERE,但 15:35 轮自动补跑 exit=0。
- **改法**:漏跑按 task|sch 连续 2 轮(30min)仍无运行才 SEVERE(复用 L278-281 已有 suppress key,加连续计数);单轮漏跑降 warn/info 或并入日报。
- **风险对冲(最坏漏什么)**:intraday 链路整体挂(盘中数据全断)→ 对冲:连续 2 轮必 SEVERE;收盘后次日检查;超时从"慢"改判"exit≠0/无新产物"。

### 改动 3:intraday DUR_THRESHOLDS 600→900s
- **文件:行号**:`scripts/schedule_monitor.sh` L405-406(`"intraday_snapshot": 600`)
- **现状**:600s(正常 286s,裕量 2 倍);16:00 一次 907s 触发(15:35 轮 dump+R2 上传);盘后 20:35 槽 1505s(dump+R2 上传)属正常却被判超时。
- **改法**:intraday_snapshot 阈值 600→900(盘中)+ 盘后 20:35 槽单独豁免(dump+上传),参照 L635-639 已有"盘后槽混入 dump+R2 上传"的注释说明。
- **风险对冲(最坏漏什么)**:intraday 进程真退化/卡死不触发告警 → 对冲:900s 对正常 286s 仍有 3 倍裕量;且"超时未完成"(运行超时 exit≠0)L333 级检查仍在,慢但完成的不会漏。

### 改动 4:staticdata 备份/同步 oversize 降 info
- **文件:行号**:`scripts/staticdata_backup_async.sh` L341-344(`--severe` → 去掉或改 info);`scripts/staticdata_sync.sh` L243-246(`--alert-issue` + dedup 21600)
- **现状**:备份变更量超阈值(>5000 文件或 >500MB)仅 rsync 磁盘留档未 commit,却发 SEVERE/告警(今天 19:03/19:54 各 1 封,每周必然出现)。
- **改法**:降 info(notify.py --info,只记 info_log 不推送)或并入周报;保留 dedup 防刷。
- **风险对冲(最坏漏什么)**:staticdata git 长期不同步,灾备第 2 层失效 → 对冲:灾备 4 层第 3/4 层(云上备份/R2)仍有监控;data_gap 检测器兜底;降周报后每周可见。

### 改动 5:四类"最终成功不发"(lhb 漏跑 / with_lock 排队 / R2 上传超时 / deploy 无成功标记)
- **文件:行号**:lhb 漏跑 → `scripts/schedule_monitor.sh` 漏跑检查(L315,补跑成功即静默);with_lock 排队 → with_lock.py/调用方(deploy 实际执行成功即不发);R2 上传超时 → `scripts/gen_daily_brief.py` L3990 附近(上传最终成功/次日兜底即不发);deploy 无成功标记 → `scripts/check_data_gap_alerts.py` C2(见改动 9)。
- **现状**:四类均在"任务中途/检查时机过早"发出,实际最终都成功(已逐条核实:lhb 19:54 exit=0、deploy 21:08-22:16 exit=0、daily_brief R2 data/ HTTP 200、deploy_2228 正常)。
- **改法**:统一"收尾确认"思路——任务最终成功则不告警(参考 deploy.sh L811-823 R2_FAIL 延迟到收尾的先例);瞬时失败走 TRANSIENT 稳定桶(连续 N 轮未自愈才发)。
- **风险对冲(最坏漏什么)**:真死锁/真卡死/真上传失败不告警 → 对冲:各任务都有"连续 N 轮仍失败"升级 SEVERE;最终 rc≠0 仍发;deploy 无成功标记只在"deploy 已完成但 rc≠0"才发。

### 改动 6:notify_dedup 双树分叉修复(去重失效根因)
- **文件:行号**:`scripts/deploy.sh` L513-514(`rsync -a --exclude=logs/ "$REPO/data/" "$GIT_REPO/data/"`);`scripts/notify.py` L1230-1257(update_dedup 读-改-写无锁)
- **现状**:双树(REPO=trade-data 数据树 + GIT_REPO=trade-data-signal git 树)各维护一份 data/notify_dedup.json;deploy 每次 rsync data/ 覆盖,rsync -a 保留 mtime → 两份 mtime 纳秒级相同但 key 互相覆盖丢失(已核实:sigkelly_snapshot_stagnation__20260928 在两份里都没有,update_dedup 却打印成功)→ 24h dedup 窗口失效(信号凯利停滞 16:51 第二次发出)。
- **改法**:①deploy.sh L513-514 rsync 加 `--exclude=notify_dedup.json --exclude=alert_state.json --exclude=alerts/ --exclude=warning_*`(状态文件不跨树同步,以 REPO 侧为准);②notify.py update_dedup 加 fcntl.flock 防并发读改写丢 key(参考 `scripts/util_atomic.py` 原子写);③可选:DEDUP_FILE 改绝对单源路径。
- **风险对冲(最坏漏什么)**:状态文件不同步导致某告警在双树各发一次 → 对冲:单源后同一进程只写一份;dedup 语义本身 fail-open(检查失败不 suppress),最多多发不漏发。

### 改动 7:sigkelly dedup key 去日期化
- **文件:行号**:`scripts/signal_kelly_snapshot.py` L515(`dedup_key = f"sigkelly_snapshot_{a['type']}_{a.get('mode', '')}_{days[-1]['d']}"`)
- **现状**:key 带快照日期(20260928),配合 24h 窗口本意"每日 1 次",但同一天 02:34+16:51 发 2 次 = key 丢失(dedup 文件被覆盖)+ 机制本身脆弱。
- **改法**:key 去掉日期(`sigkelly_snapshot_stagnation` / `sigkelly_snapshot_mutation`),24h 窗口天然每日一次;跨 repo 跑也不会因 data-dir 不同生成不同 key。
- **风险对冲(最坏漏什么)**:连续 2 天停滞,24h 窗口可能吞第 2 天第 1 条 → 对冲:停滞状态由 data_gap 断档 SEVERE(独立通道,见 C 类)兜底,信息不丢。

### 改动 8:check_data_gap 当日净值缺价 fresh 时点豁免(QDII/晚发布)
- **文件:行号**:`scripts/check_data_gap_alerts.py` L420-456(分类:regress 历史回归 / fresh 当日新缺 / QDII 豁免)
- **现状**:fresh(当日新缺,date>快照 latest_date)直接进 bad → WARN(L438/L453-456)。09-28 22:35 报 227 条当日新缺,含 512660 军工等 A 股 ETF——A 股 ETF 净值晚间/次日发布,22:35 检查时当日 nav 未入库 = 正常时滞;QDII 名称特征豁免(QDII_NAME_HINTS L346-348)只覆盖名称含"纳指/标普"等,覆盖不全。
- **改法**:①fresh 中"date==最新库日 且 当日(检查时点早于净值发布时点)"整体降 info(次日自然补齐),只对"date 落后 ≥2 交易日仍缺"才 WARN;②QDII/时滞识别补"恒生/港股/恒指/军工"等名称特征,或改按"close 有值 nav 缺且日期==当日"统一豁免。
- **风险对冲(最坏漏什么)**:真净值采集断供(全市场当日净值没入库)→ 对冲:次日仍缺才 WARN(隔日确认);该检测器已有 `--lookback 30` 补采通道;且 09-06 分析证明缺价日∩信号日∩强平日=0(影响面 0)。

### 改动 9:check_data_gap C2 deploy 无成功标记检查时机(deploy 在跑跳过)
- **文件:行号**:`scripts/check_data_gap_alerts.py` L1102-1126(C2:最新 deploy 尾部 rc 行找「退出码=0」)
- **现状**:C2 读最新 deploy_*.log 尾部 2000 字节找「退出码=0」,没有 → WARN。22:35 时 22:28 的 deploy 还在跑(22:49 才结束),尾部无成功行 → 误报"deploy 无成功标记"。
- **改法**:C2 先看最新 deploy 日志 mtime——距今 <30min(deploy 进行中)跳过 C2(等下一轮);只在"最新 deploy 已结束(日志不再增长)且尾部无退出码=0"才 WARN。
- **风险对冲(最坏漏什么)**:真 deploy 失败(kelly 产物未刷新)不漏报 → 对冲:deploy 结束且 rc≠0 时 C2 正常 WARN;C1(最近成功 deploy 距今 >2 天)L1094-1100 独立兜底。

### 附:C 类处置(2026-09-29 已拍板 #125 方案①「接受缺口 + 降噪」)
- **文件:行号**:`scripts/check_data_gap_alerts.py` L858-914(kelly_coverage 断档判定)+ L983-993(kelly_stale 信号缺席感知)
- **权威结论**(docs/sigkelly-gap-rootcause-20260928 分支 `sigkelly-gap-20260923-rootcause.md`):链路正常,09-23 起宇宙内无新可入账信号;唯一真缺口=`sz_div@09-22` 被 `signal_kelly_backtest.py:436-440` 防前视冻结闸永久拒(1 笔历史,不可自动修复)。09-23 sz_div「严格消失」是正常收盘修正;孤儿冻结 `20260923|sz_div|buy→159905` 是脏数据(不碍功能)。
- **改法**:①kelly_coverage 对 missing 全部为「已具备次日价仍无 trade(blocked=False,冻结/评级缺失)」→ 降 WARN(不再 SEVERE);②kelly_stale 的 `_kelly_missing_candidates` 缺失全部为冻结形态 → 视同信号缺席(`no_expected_buys=True`),B1/B3 不升 SEVERE。
- **不做**:不人工补冻结键(会破坏 09-18 防前视冻结闸设计前提);不清理孤儿冻结(非本方案范围,见权威根因 §7-2 待办)。

---

## 7. 风险对冲汇总(必答:降完最坏漏什么)

| 降噪项 | 最坏漏什么 | 对冲 |
|---|---|---|
| R2 lag 单次→连续 3 轮 | R2 真断供,前端分时读旧 | 连续 3 轮仍滞后 SEVERE + 主站维度⑤单次双保险 |
| intraday 漏跑/超时→连续 2 轮 | intraday 链路整体挂 | 连续漏跑 SEVERE + "exit≠0/无新产物"改判 |
| staticdata oversize 降 info | staticdata git 长期不同步(灾备2层失效) | 降周报 + 灾备 3/4 层监控 + data_gap 兜底 |
| with_lock/超时类收尾确认 | 真死锁/真卡死 | 最终 rc≠0 仍发 + 连续 N 轮升级 SEVERE |
| 信号凯利停滞去重/合并 | **不漏**(断档 SEVERE 独立通道照发) | 停滞与断档二选一,断档保留 |
| ETF 净值缺价时点豁免 | 真净值采集断供 | 次日仍缺才 WARN + --lookback 补采 |
| deploy 无标记检查时机 | 真 deploy 失败 kelly 未刷新 | C1 独立兜底 + deploy 结束 rc≠0 仍 WARN |

---

## 8. 复现与证据

- 14 天趋势:云上飞书 API 拉群 oc_7d8d3eb6b322ddeb6b8e3c53519fae7e(page_token 正确翻页);9-26 周六由 cal 核对
- 今日 21 条:飞书群消息 + `~/code/trade-data/data/alerts/latest.md` + `~/code/trade-data/data/logs/backfill_20260928_0200.log` L442-445 / `backfill_20260928_1635.log` L345-348
- 断档:云上 `static-site/data/signal_kelly_trades.json`(generated_at 09-28 22:31,max_signal_date=20260922)+ `data/sentiment.db` signal_daily(09-23 3 条/09-24 2 条 buy 均宇宙外;09-22 sz_div 入样缺 trade)+ `update_all_launchd.log` L2136(严格消失)
- dedup 失效:云上两份 notify_dedup.json 均无 sigkelly_snapshot_stagnation__20260928;deploy.sh L513-514 rsync data/ 覆盖;两份 mtime 纳秒级相同
- R2 daily_brief 误报:`curl https://ssd.fx8.store/data/daily_brief.json` HTTP 200
- 关键阈值口径:schedule_monitor.sh L70 TOLERANCE=30min、L271 连续 N 轮、L405-406 DUR_THRESHOLDS、L1537 R2 15min;notify.py L89 DEDUP_FILE、L1196/1230 dedup 读写;signal_kelly_snapshot.py L95 DEDUP_WINDOW=86400、L515 dedup_key

## 9. 诚实标注

- #18(ETF 净值缺价 227 条)未逐条核验 QDII 名称覆盖度,修复方案按"当日新缺时点豁免"通用化处理,实施后观察次日是否仍误报
- #15/#16(overfit)按告警口径(risk=60/D3=90)判真信号,未做独立回测
- C 类断档根因给出排查方向(backtest skipped/冻结/严格消失),未定位到最终根因行,需实施侧翻 skipped 明细
- 实施完成后的量化验收:连续 3 个交易日飞书告警数应 ≤2 条/天(overfit 触发日除外);若某天仍 >5 条,回查本文件改动 1/2/3/5 是否生效
