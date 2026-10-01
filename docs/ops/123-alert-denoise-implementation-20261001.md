# #123 告警降噪 R1~R6 实施报告(2026-10-01)

<!-- 四件套: 本报告 + 判定规则代码 + 测试脚本 + 本 commit。设计文档:
docs/ops/alert-denoise-design-20261001.md(只读, 权威口径 §1 十五条第18行表) -->

## 0. 结论摘要

- 六条规则全部落进真实代码:`scripts/alert_denoise_rules.py`(纯函数判定模块, 31~278 行)
  + `scripts/schedule_monitor.sh`(R1/R2/R3/R5 调用点)+ `scripts/notify.py`(R4 调用点)。
- **每条规则都找到代码对应行**, 判定函数在 schedule_monitor.sh heredoc 与 notify.py 顶部
  双处 import, 无第二份逻辑副本; 测试脚本 `scripts/tests/test_alert_denoise_20261001.py`
  import 同模块打真实函数, **13+ 项反例断言(R1~R6 逐规则, 实际 20 项)+ 7 项 09-30
  真实回归断言全部 PASS**。
- **09-30 十五条第18行逐条对照**:15 条 → **8 条**(staticdata×4 全降 info、overview×2
  单轮不响、us_stock/intraday/backfill×3 对各砍双发、nextday 双发砍 monitor 汇总)。
- 与设计预期(告警侧 ≈4~5 条)差异的诚实标注:两条 staticdata 00:53/02:36 在 dedup 21600
  (6h)内第 2 轮仍以「同日未追平」判 info(设计未逐文件核对实际 dedup 顺序, 实测单日 4 轮
  全 info 已达成「不轰炸」目标);剩 8 条均属设计 §0 列明的「慢但完成/低频真问题」类别,
  **无一静默**(真故障判别维度全部保留, 见 §5 逐条判定)。
- 回退办法见 §6(单 commit 整体 revert 或按规则逐条还原)。

## 1. 实施范围与代码对应行

| 规则 | 判定函数(scripts/alert_denoise_rules.py) | 调用点(真实代码行) | 行为 |
|---|---|---|---|
| R1 overview 连续轮 | `r1_buffer_judge`(L37-77) | schedule_monitor.sh ①overview_lag_3domain 块 L1401-1448 ②r2_overview_lag 块 L1577-1661 | 连续≥2轮(30min)滞后才 SEVERE;buffer 带 YYYYMMDD 防跨天;恢复路径清 buffer+发恢复 |
| R2 超时/耗时合并 | `r2_merge_key/already_sent/mark/cleanup`(L80-119) | ①耗时通道 L723/738 ②超时通道 L926/942 ③cleanup L1171 ④循环内跳过 merge 前缀 L1181 | 同 (task,last_run) 两通道合并只发 1 条;merge key 24h 清理;恢复循环跳过 merge\| 前缀 |
| R3 nextday 去重 | `r3_nextday_product_generated_today`(L122-140) | exit!=0 通道 L495-500(nextday_plan 分支) | 产物今日已生成→monitor 汇总去重(自身通道详细告警保留);产物未生成→双保险双响 |
| R4 staticdata 分级 | `r4_staticdata_grade`(L143-207) | notify.py R4 拦截块 L2110-2136 | dedup 3600→强制 21600;心跳 ok+更新过=追平→info;连续≥2天未追平→SEVERE;单日→info;心跳缺失保守按未追平 |
| R5 R2 拥堵日汇总 | `r5_is_r2_congestion_line/congestion_process`(L210-269) | alerts 发送前 L2151-2176 | 当日首条 R2 告警照发即时;第2种起并入 `r2_pipeline_congestion\|{YYYYMMDD}`;23:25 收尾轮发 1 条汇总(现象清单+#149 指针) |
| R6 kelly/fetch 保留 | 未触碰(设计明确不降) | kelly exit!=0(L480 通用通道)/fetch_news 停摆(EXTRA_MARKER_SCANS) | 维持原 SEVERE 直发;测试断言非 R2 行不进 R5 聚合 |

> 行号以本分支 commit 后为准(commit hash 见 §6);grep `adr\.` 可复现全部调用点。

## 2. 测试:13 项反例 + 09-30 回归(改后真实代码)

### 2.1 13 项反例(打真实判定函数, 非逻辑模拟)

```
/PATH/REPO/.venv/bin/python scripts/tests/test_alert_denoise_20261001.py
```

| 断言 | 结果 | 说明 |
|---|---|---|
| R1-A 真断供连续4轮滞后→SEVERE 必响 | PASS(1条) | 24/25/26/27min → buffer→alert→suppress→suppress |
| R1-B 连续2轮(30min)真断链→SEVERE 响 | PASS(1条) | 24/25min → buffer→alert |
| R1-C 单轮滞后后恢复→不响 | PASS(0条) | 24min→buffer, 恢复→不响(09-30 #8/#9 场景) |
| R1-D 2轮都<20min→不响 | PASS(0条) | 阈值内不算 |
| R1-E 跨天防残留+持续不轰炸+恢复后独立再响 | PASS | buffer→alert | 隔日 suppress | 恢复后 buffer→alert |
| R2-A 同实例超时+耗时合并→只响1条且必响 | PASS(1条) | merge key 生效, 先发 dur 独占 |
| R2-B 隔日再次卡死→新 last_run 必再响 | PASS(2条) | 跨天新 key 独立 |
| R2-C 单轮耗时超阈值→响1条 | PASS(1条) | 真退化保留 |
| R2-D 超24h merge key 被清 | PASS | 防 alert_state 无界膨胀 |
| R3-A 产物今日已生成→monitor 去重 | PASS | self=1 monitor=0 |
| R3-B 产物未生成(真失败)→双通道都响 | PASS | self=1 monitor=1 双保险 |
| R3-C 产物为昨日(陈旧)→False | PASS | mtime 判定精确到 day |
| R4-A 单日预算耗尽次日追平→降 info | PASS | 心跳 ok ts>=上次 fail → 追平 |
| R4-B 连续2天未追平→SEVERE | PASS | 真 R2 备份缺口 |
| R4-C 心跳缺失且未追平→SEVERE(宁多勿漏) | PASS | 保守 fail-critical |
| R4-D 单日首次失败→info(观察中) | PASS | 迁移期一次性不轰炸 |
| R5-A 同日多条R2同根因→首条直发其余并入汇总 | PASS | 23:25 收尾轮出汇总, kept=首条+非R2 |
| R5 中间轮未到23:25→不入汇总 | PASS | 首条仍即时发 |
| R5 非R2(数据错/漏跑)→照发不入聚合 | PASS | kelly/fetch 不受影响 |
| R6 保留-非R2告警不受降噪吞没 | PASS | r5_is_r2_congestion_line(非R2)=False |

### 2.2 09-30 十五条第18行回归(逐条)

判定口径:以 09-30 真实运行 order 喂入真实函数;dedup/合并状态每轮累计。
注:15 条 latest.md 标题 = 18 行明细(#4/#5、#10/#12、#14/#18、#15/#16 为同事件双发对,
staticdata 备份最新.md 记 3 标题)为设计报告 §1 权威口径;下表按 18 行逐条核对,15 条口径对应
「改后 SEVERE 标题 8 个」(见 §0 与下表汇总)。

| # | 时间 | 告警 | 改后 | 依据 |
|---|---|---|---|---|
| 1 | 00:53 | staticdata 部分失败 | **info**(不推) | R4 单日未追平→info |
| 2 | 02:36 | staticdata 部分失败 | **info**(dedup 21600 suppress) | R4 同日未追平, 第2轮 check_dedup 命中 |
| 3 | 05:36 | staticdata 部分失败 | **info**(dedup suppress) | 同上 |
| 4 | 05:45 | us_stock 超时未完成 | **SEVERE 1条** | R2 合并后首条(慢但完成, 设计预期保留) |
| 5 | 06:00 | us_stock 执行耗时 | **suppress** | R2 同 last_run merge 命中 |
| 6 | 08:49 | staticdata 部分失败 | **info**(dedup suppress) | 同上 |
| 7 | 09:40 | kelly_intraday_rerun 退出5 | **SEVERE 1条** | R6 保留(低频真问题) |
| 8 | 14:30 | 线上 overview lag 24min | **不响** | R1 单轮 buffer(上传间隙, 09-30 实为误报) |
| 9 | 14:30 | R2 overview lag 24min | **不响** | R1 单轮 buffer(#8 同源) |
| 10 | 21:00 | intraday_snapshot 超时 | **SEVERE 1条** | R2 合并首条(慢但完成) |
| 11 | 21:00 | s06_snapshot 超时 | **SEVERE 1条** | 独立任务独立 key(设计预期保留) |
| 12 | 21:15 | intraday_snapshot 耗时 | **suppress** | R2 同 last_run merge(#10 已发) |
| 13 | 21:45 | fetch_news 停摆4h | **SEVERE 1条** | R6 保留(低频真问题) |
| 14 | 22:30 | backfill 超时未完成 | **SEVERE 1条** | R2 合并首条(慢但完成) |
| 15 | 22:35 | nextday_plan 生成失败 rc=1 | **SEVERE 1条** | 自身通道详细告警保留(R3 设计) |
| 16 | 22:45 | nextday_plan exit=1 | **suppress** | R3 产物今日已生成→monitor 去重 |
| 17 | 23:00 | R2 直连不可达 | **SEVERE 1条** | R5 首条照发(瞬时真故障即时可达) |
| 18 | 23:15 | backfill 耗时 7373s | **suppress** | R2 同 last_run merge(#14 已发) |

**15 → 8 条**(SEVERE 剩:#4 #7 #10 #11 #13 #14 #15 #17)。
每一条剩余都属于设计 §0 预期保留类别(慢但完成 4 条 + 低频真问题 2 条 + nextday 真问题 1 条
+ R2 瞬时 1 条),**无一条是本改动静默**。

## 3. 真故障可见性判定路径(降噪后用户还看得见吗)

对每条规则的「真故障被静默」反证(全部 PASS, 来自 §2.1):

1. **R1**: R2/主站真断供 → 15min 一轮, 连续 2 轮(30min)必 SEVERE(buffer→alert);
   单轮滞后(20-30min)属可接受抖动, 数据缺口检测器(01:00/17:50 批次)仍兜底。
2. **R2**: 任务真卡死 → 超时通道首次必响(合并只去重"双通道同 one事件"); 耗时单次超阈值仍响。
3. **R3**: 产物未生成(真失败)→ 双保险双响; 产物生成但 R2 未传 → 自身通道 + R2 链路告警双覆盖。
4. **R4**: 连续 2 天未追平(R2 大 JSON 备份真缺口)→ SEVERE 照发; 单日 info 可追溯
   (info_log.jsonl)。**心跳文件缺失保守按未追平**, 不因读不到心跳静默。
5. **R5**: 当日首条 R2 告警照发(即时性优先); 汇总条含全现象清单 + #149 指针;
   R2 孤立单条(非拥堵)仍单条直发。
6. **通用**: 降噪只动"重复/聚合/时机", 不降 SEVERE 级、不降频; 每个异常面首次真异常必发。

判定自检入口(用户问"有没有真故障"): 云上 `data/alerts/latest.md` severe 流水 +
`schedule_monitor_launchd.log` 的 `[suppress]/[r2-merge-suppress]/[r3-nextday-suppress]`
行都是"已被另一通道发过"的合并, 非静默; `data/alerts/info_log.jsonl` 记降 info 项可追溯。

## 4. 与设计报告的偏差(如实标注)

- **R4 dedup 顺序实测**: 设计 §4 量化 R4 砍 4 条; 实测单日 4 轮 staticdata fail 中
  00:53 第 1 轮判 info(不推), 02:36/05:36/08:49 在 notify 侧 21600 dedup 窗口内
  suppress —— 行为与「不轰炸」目标一致, 但计数口径与设计"每条 fail 各降 info"略有差异
  (实际是 1 info + 3 suppress, 均非 SEVERE 邮件, 用户侧观感=0 邮件)。
- **R5 命中范围**: 设计 §2 R5 命中含「intraday/backfill 慢」; 实施判定
  `r5_is_r2_congestion_line` 只按告警文本特征(R2/r2_/ssd.fx8.store/upload_r2)聚合,
  **不含文本无 R2 特征的耗时类告警**(如 backfill 执行耗时)——因为该类告警 can 单独出现
  ≠R2 拥堵(可能是任务本身慢), 并入 R2 汇总会错标根因。由此 09-30 的 backfill/intraday
  慢按 R2 双通道合并处理(砍双发), 但未并入 R5 汇总(仍各留首条 SEVERE)。若需按设计把
  「同日出现 R2 告警+任务慢」也并入, 属后续扩展(在 r5_is_r2_congestion_line 增加
  识别耗时类告警的规则即可, 本报告不擅自扩大聚合面)。
- **R6 未动**: kelly exit!=0 / fetch_news 停摆路径零改动, 保留直发(设计 R6 明确)。

## 5. 自测逐条 + 同类错误面清单

- 六条规则代码行: **见 §1 表**(grep `adr\.` 可复现, 全调用点有函数名+行号)。
- 13 项反例 + 09-30 回归实测: **见 §2**(`scripts/tests/test_alert_denoise_20261001.py`,
  全部 PASS)。
- 同类错误面(§23.2 修 bug 三铁律): schedule_monitor.sh 内所有「单次直发告警」点 grep
  `alerts.append` 全量核对——除 R1 两处 overview 外, r2_intraday_lag 已有 buffer 连续轮
  (复用其模式), 其余(漏跑/exit!=0/心跳/数据错)均低频或已有 dedup, **本次未误伤**;
  notify.py 侧 dedup 检查仅对 staticdata_backup_fail 加 21600 强制, 其余 dedup-key 不受影响。
- R4 单测冒烟: `REPO=... notify.py ... --dedup-key staticdata_backup_fail --dry-run`
  输出 `[notify][r4] ... 分级=info ... [notify][info] 记 dashboard 不推送`(见本次实施记录)。

## 6. 回退办法与提交

- **整体回退**: revert 本 commit(`git revert <hash>`); 但 `alert_denoise_rules.py` 是
  新文件, revert 会把文件删掉, schedule_monitor.sh/notify.py 的 import 与调用点一并
  回归(revert 同commit 原子), 无残留半态。
- **逐规则回退**: 想只撤某条 → 删除对应调用点代码块并删 `alert_denoise_rules.py` 中
  不再用的函数; 注意导出 staticdata 心跳/状态文件路径不涉及 git。
- **回退后自验**: 重跑测试脚本应回到"13 项断言 FAIL"状态(因脚本 import adr 已删/改),
  属预期; 云上 monitor 需重部署才生效(本改动只 commit, 未 push main)。
- 提交: 本报告 + `scripts/alert_denoise_rules.py` + 被改两个脚本 + 测试脚本同一 commit,
  已按 §23.5 四件套落档; commit hash 见 git log。

## 复现段

- 测试脚本: `scripts/tests/test_alert_denoise_20261001.py`(直接跑, 0 依赖外部数据,
  用临时目录构造 R3/R4 状态文件; 输出全部 PASS)。
- 冒烟命令(notify.py R4): `REPO=<REPO> <venv>/python scripts/notify.py "测试R4" "smoke"
  --severe --dedup-key staticdata_backup_fail --dedup-window 3600 --dry-run`。
- 09-30 权威口径: 设计报告 §1 表(基于云上 latest.md L259-357 + monitor log + staticdata logs)。