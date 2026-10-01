# #123 告警降噪方案设计(2026-10-01)

> researcher 调研产出 | 只读不改代码/数据 | 前置:09-28 盘点(19条/天分档)+ 09-29 方案(9 条改动)已 merge `3ae347e51`/`f57cbb12b`/`0132e953c` 并在云上生效
> 本报告**核心发现:09-29 方案落地后,09-30 交易日仍发 15 条 SEVERE,目标 1~2 条未达成**。本文档给出:现状复核 + 6 条补强规则(每条带真故障反例实测 + 代码行)+ 误伤判定路径。

## 0. 结论摘要

- **09-30(交易日)实测 15 条 SEVERE**(权威口径:云上 `latest.md` L259-357 + `schedule_monitor_launchd.log` 检测明细 + `staticdata_backup_async_20260930_*.log` 邮件痕迹)。
- **15 条构成**:staticdata 备份部分失败 ×4(00:53/02:36/05:49/08:49)+ 单次滞后误报 overview lag ×2(14:30 主站+R2 各 1)+ 慢但完成的超时/耗时 ×7(us_stock 2 / intraday+s06 3 / backfill 2)+ nextday_plan 同事件双发 ×2(22:35/22:45)。
- **09-29 方案没压住的 3 个盲区**:①改动1"连续3轮"只覆盖 intraday R2 lag,`overview_lag_3domain`/`r2_overview_lag` 仍单次直发;②"超时未完成"(L893-903)与"执行耗时"(L707-718)是**两套独立 key**,同一任务同一轮双发;③nextday_plan 任务自身通道(`nextday_plan.sh:71-75`)与 schedule_monitor 汇总通道双发。
- **推荐 6 条补强规则(根治>缓解)+ 根因前提 #149**:告警侧全做 09-30 的 15 条 → 约 4~5 条(剩均为"慢但完成/低频真问题");叠加修 #149(trade_deploy.lock 拥堵,09-30 全天 R2/部署慢的系统根因)→ 1~2 条。
- **真故障反例实测**:13 项断言全部 PASS(模拟新规则判定,判定语义从源文件提取),无一条规则因过不了反例被砍。诚实标注:模拟测试非现有代码测试,实施后需按 §7 复验。

---

## 1. 现状复核(09-30 交易日 15 条明细)

| # | 时间 | 类别 | 告警 | 定性 | 真伪证据 |
|---|---|---|---|---|---|
| 1 | 00:53 | staticdata 备份部分失败 | upload_r2 大 JSON 预算耗尽 | 迁移期一次性(10-01 已追平) | `staticdata_backup_async_20260930_005057.log`:⚠预算耗尽 10800s,15798/31663 已传 |
| 2 | 02:36 | staticdata 备份部分失败 | 同上 | 同上 | `_023640.log` 同尾 |
| 3 | 05:36 | staticdata 备份部分失败 | 同上 | 同上 | `_054920.log`:剩余 15865 未传,次日 rsync 追平后补传 |
| 4 | 05:45 | us_stock_morning 超时未完成 | 45min 未完(计划05:00) | 慢但完成(06:00 报耗时 2968s) | schedule_monitor L893-903 通道 |
| 5 | 06:00 | us_stock_morning 执行耗时 | 2968s>1800s | 同 #4 双发 | L707-718 通道 |
| 6 | 08:49 | staticdata 备份部分失败 | 同上 | 迁移期 | latest.md L287 |
| 7 | 09:40 | kelly_intraday_rerun 退出码5 | 盘中回测失败 | 低频真问题(保留) | `kelly_intraday_rerun_20260930_0940.log` |
| 8 | 14:30 | 线上 overview lag 24min | 主站 ss.fx8.store | **单次滞后误报** | L1344-1390 单次直发;上传间隙 |
| 9 | 14:30 | R2 overview lag 24min | R2 ssd.fx8.store | 同上 #8 同源 | L1521-1561 单次直发 |
| 10 | 21:00 | intraday_snapshot 超时未完成 | 20:35 轮 25min 未完 | 慢但完成 | L893-903 |
| 11 | 21:00 | s06_snapshot 超时未完成 | 同上 | 慢但完成(21:15 S06_FRESH_OK) | L893-903 |
| 12 | 21:15 | intraday_snapshot 执行耗时 | 2081s>1800s | 同 #10 双发 | L707-718 |
| 13 | 21:45 | fetch_news 停摆(超4h未运行) | last_run=17:45 | 真问题已自愈(低频保留) | 定时 trade-fetch-news 45min 一轮 |
| 14 | 22:30 | backfill_evening 超时未完成 90min | 21:00 轮慢 | 慢但完成(根因=#149 deploy 48min) | L893-903 + deploy 22:14-23:02 |
| 15 | 22:35 | nextday_plan 生成失败 rc=1 | R2 上传 300s 超时 | 真问题(产物已落盘) | `nextday_plan_launchd.log` 尾部 ⚠R2 上传超时 |
| 16 | 22:45 | nextday_plan 退出失败 exit=1 | 同 #15 事件 schedule_monitor 确认 | 双发 | L486 exit!=0 通道 |
| 17 | 23:00 | R2 直连不可达 curl rc=28 | 网络抖动单次 | 瞬时(10-01 恢复) | L1451-1460 r2_unreachable |
| 18 | 23:15 | backfill_evening 执行耗时 7373s | 超 4500 | 同 #14 双发 | L707-718 |

> 注:15 条 vs 18 行——#4/#5、#10/#12、#14/#18 是同任务同轮双发,各计 2 条;#15/#16 双发计 2 条。表按 latest.md 标题条目数与 schedule_monitor 检测明细对齐(latest.md 保留 50 条流水,09-30 共 15 个 [severe] 标题 + staticdata 备份 3 标题)。

**09-29 方案落地现状(已生效,但没压住)**:
- 恢复邮件 6h dedup ✓ 生效(`schedule_monitor_recovery` 6h 窗命中,09-30 恢复邮件仅 1 封)
- 复现抑制 ✓ 生效(`[suppress] ... 不重发` 在 active 期间拦重复)
- **但每个异常面是独立 key 独立发第 1 条**——全天累计仍 15 条。

---

## 2. 降噪方案(6 条补强,根治>缓解)

### 规则 R1:overview lag 双 key 加连续轮(治 09-30 #8/#9 单次滞后 2 条)
- **命中范围**:`overview_lag_3domain`(主站 ss.fx8.store,`scripts/schedule_monitor.sh` L1344-1390)+ `r2_overview_lag`(R2 直连,L1521-1561)。当前均"单次 lag>20min 即发 SEVERE"。
- **改法**:复用既有 `R2_LAG_CONTINUOUS_THRESHOLD=3` 的 buffer 计数模式(L1572-1605 真实代码,`r2_intraday_lag` 已用)到这两个 key;连续 ≥2 轮(30min)仍滞后才 SEVERE;buffer key 带日期防跨天残留(仿 L1571 `|buffer|{YYYYMMDD}`)。阈值不动(20min)。
- **预计每天少几条**:单次滞后误报(上传间隙)不再直发。09-30 砍 2 条;09-28 的 13:45/14:15 同型也砍。
- **真故障反例实测(PASS)**:`/tmp/test_alert_denoise_20261001.py` R1-A 真断供 4 轮滞后 → 第 2 轮 SEVERE 必响;R1-B 连续 2 轮(30min)真断链 → 响;R1-C 单轮 24min 后恢复 → 不响;R1-D 2 轮均 <20min → 不响。
- **代码对应行**:`scripts/schedule_monitor.sh` L1344-1390(主站)/L1521-1561(R2)判定处 + L432 `R2_LAG_CONTINUOUS_THRESHOLD=3`(或新增 `OVERVIEW_LAG_CONTINUOUS_THRESHOLD=2`)。
- **最坏漏什么/对冲**:R2 真断供 20-30min 内不响(前端 TTL 60s+缓存仍可能短暂读旧)→ 连续 2 轮(30min)必响 + 数据缺口检测器(01:00 批次)兜底 + `r2_unreachable` 独立可达性检查保留。

### 规则 R2:超时未完成 + 执行耗时同任务同轮合并(治 #4/#5、#10/#12、#14/#18 双发 3 条)
- **命中范围**:进行中超时通道(key=`{task}|in_progress_timeout`,L893-903)+ 执行耗时通道(key=`{task}|dur>{thresh}s`,L707-718)。两通道对同一 `last_run` 先"超时未完"后"完成报耗时"双发。
- **改法**:两通道 dedup key 对齐到 `{task}|{last_run}`(带日期时点);先发通道独占,后发通道对同 last_run 抑制(保留各自阈值语义,只是不发重复)。
- **预计每天少几条**:09-30 双发 3 对 → 砍 3 条(us_stock 1 + intraday 1 + backfill 1)。s06 与 intraday 不同任务,各自合并后仍 2 条。
- **真故障反例实测(PASS)**:R2-A 同 last_run 超时+耗时 → 合并只 1 条且必响;R2-B 隔日再次卡死(新 last_run)→ 新 key 独立再响(不吞跨天);R2-C 单轮耗时超阈值 → 响 1 条(真退化保留)。
- **代码对应行**:`scripts/schedule_monitor.sh` L707-718(耗时通道 append)+ L893-903(超时通道 append),dedup key 构造处。
- **最坏漏什么/对冲**:真卡死后恢复运行又被判慢 → 新 last_run 新 key 必再响;耗时通道单次(无超时前序)仍响。

### 规则 R3:nextday_plan 双发去重(治 #15/#16 双发 1 条)
- **命中范围**:`scripts/nextday_plan.sh` L69-75(任务自身发 `nextday_plan_fail` dedup 3600)+ schedule_monitor 汇总通道(`{task}|exit!=0|{exit_code}`,L486)。
- **改法**:nextday_plan 自身通道保留(内容详细含日志尾部);schedule_monitor 对 `nextday_plan` 任务的 exit!=0 汇总,若 `nextday_plan_fail` dedup 本日已命中则不再汇总(或反之,schedule_monitor 汇总保留、任务自身对同一失败面不再发——按"哪个通道内容更全"二选一,推荐保留自身通道)。
- **预计每天少几条**:双发场景砍 1 条(09-30 22:35/22:45 → 1 条)。
- **真故障反例实测(PASS)**:R3-A 产物已生成但 R2 300s 超时 → 自身通道必响,monitor 去重;R3-B 产物未生成(真失败)→ 双通道都响(双保险不丢);R3-C 全成功 → 不响。
- **代码对应行**:`scripts/nextday_plan.sh:71-75` + `scripts/schedule_monitor.sh` L486 分支(对 nextday_plan 加 `nextday_plan_fail` 已发检查)。
- **最坏漏什么/对冲**:真失败产物未生成 → 双保险仍双响;产物生成但 R2 未传 → 自身通道 1 条 + R2 上传链路告警(r2_skip/upload fail)独立覆盖。

### 规则 R4:staticdata 备份部分失败分级 + dedup 拉长(治迁移期 4 条/天的重复轰炸)
- **命中范围**:`scripts/staticdata_backup_async.sh` L411-412(`--dedup-key staticdata_backup_fail --dedup-window 3600`)。现状:每次备份 R2 大 JSON 预算耗尽(10800s)即发 SEVERE,1h dedup,一天多轮备份各发。
- **改法**:①dedup 3600→21600(6h);②按"单日预算耗尽但 manifest 已重写、次日 rsync 追平(设计允许)"降 info(只记 dashboard);仅"连续 ≥2 天仍未追平(R2 备份缺口持续)"才 SEVERE。状态跨天需落盘(仿 data_gap_alert_state)。
- **预计每天少几条**:迁移期每天 4 条 → 0(追平后 info);真缺口每天 1 条 SEVERE。
- **真故障反例实测(PASS)**:R4-A 单日预算耗尽次日追平 → info(09-30→10-01 实证已追平:`staticdata_backup_async_20261001_171748.log` 尾部 ✓);R4-B 连续 2 天未追平 → SEVERE;R4-C manifest 未重写也未追平 → SEVERE。
- **代码对应行**:`scripts/staticdata_backup_async.sh` L411-412(dedup 参数)+ L341-347(oversize info 已落地,失败分级参照同模式)。
- **最坏漏什么/对冲**:R2 大 JSON 备份真断供多日 → 连续 2 天 SEVERE + #126 收口/R2 灾备监控(#130 通道)兜底。

### 规则 R5:R2/部署链路拥堵同根因日汇总(治 #17 + 关联告警的聚合)
- **命中范围**:R2 直连不可达(`r2_unreachable` L1451-1460)+ R2 上传超时 + `r2_skip_continuous` + intraday/backfill 慢,当同日多 R2 相关告警 = #149 同根因(09-30 全天 R2/部署拥堵)。
- **改法**:新增日级汇总 key(如 `r2_pipeline_congestion_{YYYYMMDD}`):同一自然日内触发 ≥2 种 R2 相关告警,第 1 条照发(保真故障即时性),后续同源告警并入当日 1 条"R2/部署链路拥堵汇总(现象清单+根因指针 #149)"(夜间 23:30 发),不再逐条 SEVERE。
- **预计每天少几条**:09-30 的 R2 相关(#17 + backfill/intraday 慢 + fetch_news 锁跳过)聚合后约砍 2-3 条;注意 `r2_unreachable` 单日孤立出现(非拥堵)仍直发。
- **真故障反例实测(说明)**:R5 不吞首条(首条仍即时 SEVERE),只合并后续同源;真 R2 全断供时首条必响,汇总条含全部现象。**反例断言**:单日 R2_unreachable + backfill 慢 → 首条(不可达)即时响 + 汇总 1 条(不逐条轰炸)。
- **代码对应行**:`scripts/schedule_monitor.sh` L1451-1460(r2_unreachable)+ L763-786(r2_skip_alert)+ 汇总逻辑新增处(靠近 L1152 通知分级注释)。
- **最坏漏什么/对冲**:R2 断供但当日无其他 R2 告警 → 仍单条直发;聚合只影响"多条同根因",单条真故障语义不变。

### 规则 R6:保留直发(不降,低频真问题)
- kelly_intraday_rerun 退出码 5(#7)、fetch_news 停摆 4h(#13):均低频/真问题,保持 SEVERE 直发,不做降噪。fetch_news 停摆已由 EXTRA_MARKER_SCANS(L393-395)覆盖,连续轮语义天然防刷。

---

## 3. 误伤风险评估:降噪后真故障用户还看得见吗

判定路径(对每条降噪规则,真故障的可见性链路):
1. **R1(overview 连续轮)**:R2 真断供 → 30min 内连续 2 轮 → SEVERE 直发;数据缺口检测器(01:00/17:50 批次,check_data_gap_alerts.py)+ 前端读旧(overview lag 是用户可感知症状)→ 3 层兜底。单次 20-30min 滞后属可接受抖动。
2. **R2(双通道合并)**:任务真卡死 → 超时通道必响(合并不影响该通道首次发出);耗时超阈值单次 → 仍响。
3. **R3(nextday 双发)**:产物未生成(真失败)→ 双保险双响;产物生成但 R2 未传 → 自身通道 + R2 链路告警双覆盖。
4. **R4(staticdata 分级)**:R2 大 JSON 缺口连续 2 天 → SEVERE;单日追平 → info 可追溯(info_log.jsonl)+ 灾备 4 层第 3/4 层监控兜底。
5. **R5(同根因汇总)**:首条真故障即时 SEVERE 不吞;汇总条全现象清单 + #149 指针。
6. **通用铁律**:所有降噪只动"重复/聚合/时机",**不降 SEVERE 级、不降频、不后台暂停**;每个异常面"首次真异常"照发(§14 即时性优先)。真故障判别维度(连续轮、跨天追平、产物未生成)作为每条的判别锚点保留。

**判定自检清单(用户问"有没有真故障时")**:
- 查 `latest.md` severe 流水 + 飞书 alert 群 + 邮件(三处同源一致)
- 查 `schedule_monitor_launchd.log` 的 `[suppress]/[recurrence-suppress]` 行——被抑制的都是"已 active 持续中"或"恢复后<6h 复现",非新事件
- 查 `data/alerts/info_log.jsonl`(降 info 项可追溯)
- 真故障形态(缺次日价/评级缺失/连续 N 天缺口/0 入账)按 §0-§2 的判别锚点仍 SEVERE 直发

---

## 4. 量化路径

| 步骤 | 09-30 条数 | 处置 | 砍/剩 |
|---|---|---|---|
| 现状 | 15 | — | 15 |
| R4 staticdata 分级 | 4 | 追平后 info | 砍 4 → 11 |
| R1 overview 连续轮 | 2 | 单次滞后不响 | 砍 2 → 9 |
| R2 双通道合并 | 3 对 | 合并 | 砍 3 → 6 |
| R3 nextday 双发 | 2 | 合并 | 砍 1 → 5 |
| R5 同根因汇总 | 2-3 | 汇总 | 砍 2 → 3~4 |
| **告警侧合计** | | | **≈4~5 条**(剩:慢但完成 3 条 + kelly/fetch_news 低频真问题) |
| **叠加修 #149(部署/R2 拥堵)** | | 慢但完成根因消失 | **≈1~2 条**(仅低频真问题) |

> 09-30 的"慢但完成"(us_stock/intraday/backfill)与 nextday R2 超时、R2 直连不可达、fetch_news 锁跳过,**同根因 = #149 trade_deploy.lock 队列拥堵**(deploy 48min、R2 上传 300s 超时)。告警侧合并只是减半,修 #149 才真达成 1~2 条目标。

---

## 5. 诚实标注

- **真故障反例实测是对"拟实施新规则"的逻辑模拟**(判定语义从 `schedule_monitor.sh` 源文件提取,如 R2 buffer 连续轮 L1572-1605、超时/耗时双通道 L707-718/L893-903),**非现有代码测试**;13 项断言 PASS 不代表规则已上线,实施 agent 落地后需按 §7 复验。
- **09-30 条数口径**:latest.md 保留 50 条流水(09-30 15 个 [severe] 标题)+ schedule_monitor 检测明细(09-30 检测到 19 次,其中含多次恢复)+ staticdata 备份日志邮件痕迹。staticdata 备份部分失败按日志文件计数 4 份(latest.md 标题 3 个,02:36 那次标题可能被流水覆盖,诚实标注)。
- **#149 根因**:登记于 pending-features-index(2026-09-30 索引段),本次调研仅从现象确认(09-30 全天 R2/部署慢的一致证据链),未做根因深挖(属 #149 单)。
- **fetch_news 停摆(09-30 21:45)**:journalctl 无 entries(可能未持久化),以 schedule_stats last_run=17:45 为唯一依据,真停摆约 4h 已自愈;低频,保留直发。
- **规则 R5 为新增聚合概念**,现有代码无对应实现(风险对冲表仅首条即时、汇总不吞首条的原则性说明);若实施侧评估复杂度过高可先只做 R1-R4,R5 作为可选项。

## 复现段
- 测试脚本:`/tmp/test_alert_denoise_20261001.py`(13 项反例断言,全部 PASS)
- 云上证据:latest.md(09-30 15 个 [severe])、schedule_monitor_launchd.log(09-30 检测明细)、staticdata_backup_async_20260930_*.log(预算耗尽)、staticdata_backup_async_20261001_171748.log(10-01 追平 ✓)、nextday_plan_launchd.log(R2 300s 超时 rc=1)
- 代码锚点:schedule_monitor.sh L707-718/L893-903/L1344-1390/L1451-1460/L1521-1561/L1572-1605;staticdata_backup_async.sh L411-412;nextday_plan.sh L69-75
