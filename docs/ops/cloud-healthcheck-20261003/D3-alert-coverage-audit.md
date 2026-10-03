# D3 告警体系覆盖面体检(云服务器系统性体检第 3 维,2026-10-03)

> 调研 agent | 只读诊断不治疗 | 观察窗口:2026-10-03(国庆休市),判"最近"= 09-20~10-03
> 范围:通道可用性 / 任务×告警覆盖矩阵 / 降噪反噬回放 / latest.md 双区结构 / 元监控 / 云本机差异 / 反证
> 硬约束:云上只读(ubuntu@122.51.111.173),本机只读,唯一写入=本报告

## 0 结论速览

1. **通道健康**:email(SMTP)+ feishu(open.feishu.cn app)双通道近 14 天(latest.md 50 条流水 09-24~10-03)发送 **50/50 全 email=OK feishu=OK,0 FAIL**;schedule_monitor 日志 254 条「邮件已发送至 234058394@qq.com」。telegram 未配置(notify.py 不显示)。
2. **⭐覆盖盲区核心**:38 个周期任务里 **12 个完全裸奔**(挂了没人知道),另有 brief_push(退出码恒 0=失败永久静默)和 schedule-monitor 自身(heartbeat 无消费方)2 个结构性盲区 → **P0**。
3. **降噪反噬风险总体低**:5 个历史真故障(09-30 nextday_plan / 09-18 冻结缺失 / us_stock 超时 / fetch_news 停摆 / staticdata 缺口)套现行 R1~R6 规则回放,**现行规则全部仍会发**。降噪只砍重复/聚合/时机,不吞真故障维度。
4. **latest.md 双区结构确有静默覆盖风险**:schedule_monitor 告警/恢复都写覆盖区互相覆盖,check_data_gap 与回测脚本的 severe 只进流水区 → 09-18 冻结表 severe 被后续"计划任务监控恢复"盖掉的现象机制成立。**现场证据**:10-03 00:45 头部区=「计划任务监控恢复」(无害),而流水区最新是 10-03 00:30 fetch_news R2 锁跳过 SEVERE(需人工关注)——**用户开工看头部=看不到真正的严重告警**。
5. **元监控**:self_heal 挂了 → schedule_monitor L1065 降级 SEVERE ✓(有);**schedule-monitor 自己挂了 → heartbeat(/tmp/schedule-monitor-heartbeat.txt)全仓 grep 无任何消费方 = 元监控盲区 P0**。monitor_72h 云上未迁未跑(72h_ 键全 mac 时代残留)。
6. **云上通道配置正确**:云上 notify.py 读云上 trade-data/config/email.json+feishu.json+.env(键名齐全非占位),**无指向已废弃 mac 通道的告警**。mac launchd 已废弃,本机纯开发。
7. **反证项**:主监控链(schedule_monitor 15+EXTRA 2)轮询正常、10-03 18:15 最新轮 OK 无漏跑无退出失败;systemd 近 7 天仅 fetch-news timeout 4 次(已被 EXTRA 监控覆盖);休市期行为正确(10-02/10-03 无交易日任务告警)。

## 1 通道全枚举 + 近期成功率实测

### 1.1 通道清单(云上 notify.py 实读)
| 通道 | 配置来源 | 状态 | 证据 |
|---|---|---|---|
| email | trade-data/config/email.json(smtp/port/user/password/from/to,无占位符) | 可用 | latest.md 50/50 email=OK |
| feishu | config/feishu.json(enabled/mode=app/chat_ids/webhook_urls/receive)+ .env FEISHU_APP_ID/FEISHU_APP_SECRET(只验键名不打印值) | 可用 | latest.md 50/50 feishu=OK |
| telegram | notify.py 未配置则不发 | 未配置(设计如此,非故障) | notify.py 通道枚举无 telegram |

### 1.2 近 14 天发送成功率(severe 流水 = latest.md 50 条上限滚动,09-24~10-03)
```
tail 50 行逐条核对:每条均含 [email=OK][feishu=OK],0 条 email=FAIL,0 条 feishu=FAIL
```
命中日期覆盖:09-24、09-25、09-27、09-28、09-30、10-01、10-03,跨时段(凌晨 R2 / 盘后 / 夜间),双通道全程 OK。

### 1.3 schedule_monitor 日志层发送计数
```
grep -c '邮件已发送至 234058394@qq.com' /home/ubuntu/code/trade-data/data/logs/schedule_monitor_launchd.log
→ 254
```
254 次 SMTP 发送成功(09-20 前后起,含告警+恢复)。

### 1.4 按日发送量(09-20~10-03,观察窗口)
```
09-20:22  09-21:14  09-22:13  09-23:7  09-24:11  09-25:2  09-26:0
09-27:8  09-28:11  09-29:12  09-30:13  10-01:3  10-02:0  10-03:2
合计 118 封,全部「邮件已发送至」(SMTP 层 100% 成功)
```
休市自然下降(09-26 周六 0、10-02 周三 0、10-03 国庆 2),符合预期。

### 1.5 今日(10-03)monitor 轮次健康
```
10-03 monitor 轮 75 条(每 15min 一轮,休市正常),18:15 最新轮 OK 所有任务按计划执行,无漏跑,无退出失败
```

## 2 ⭐任务 × 告警覆盖矩阵(38 个 systemd timer 任务)

### 2.1 监控源分层(6 层)
| 层 | 监控源 | 监控内容 |
|---|---|---|
| M1 | schedule_monitor TASKS 15 | 漏跑/超时/耗时(每 15min) |
| M2 | gen_schedule_stats 15+2 EXTRA | exit!=0 / log 异常 → static-site/data/schedule_stats.json |
| M3 | schedule_monitor LAUNCHCTL_LABELS 11 | systemctl is-active(unit 挂了=SEVERE) |
| M4 | 脚本自身 notify | kelly_intraday_rerun/gold_night/backup_db 自报 |
| M5 | 数据层 | check_data_gap checker 1-12(北向/accum_nav/宽度/资金面/交易断档/kelly_coverage/基金 nav 11-12)、check_s06_freshness、check_r2_consistency |
| M6 | 元层 | self_heal→schedule_monitor L1065 / heartbeat(无消费方=盲区) |

### 2.2 覆盖矩阵(38 任务逐行)
| 任务 | M1 漏跑/超时 | M2 exit/log | M3 unit 状态 | M4 自身 notify | M5 数据层 | 结论 |
|---|---|---|---|---|---|---|
| update_all | ✓ | ✓ | ✓ | — | ✓ | 完整 |
| intraday_snapshot | ✓ | ✓ | ✓ | — | ✓ | 完整 |
| kelly_intraday_rerun | — | — | — | ✓(退出码/对账/R2) | — | 半覆盖(漏跑无监控) |
| backfill_evening | ✓ | ✓ | ✓ | — | — | 完整 |
| etf_national_team | ✓ | ✓ | ✓ | — | — | 完整 |
| etf_track_index | — | — | — | — | — | **裸奔** |
| lof_track_index | — | — | — | — | — | **裸奔** |
| fapi_daily | — | — | — | — | — | **裸奔** |
| futures_backfill | ✓ | ✓ | ✓ | — | — | 完整 |
| gold_night | — | — | — | ✓(采集失败) | — | 半覆盖(漏跑无监控) |
| lhb_backfill | ✓ | ✓ | ✓ | — | — | 完整 |
| rzhb_backfill | ✓ | ✓ | ✓ | — | — | 完整 |
| turnover_backfill | ✓ | ✓ | ✓ | — | — | 完整 |
| ab_direction_anchor | — | — | — | — | — | **裸奔** |
| nextday_plan | ✓ | ✓ | — | ✓(自身 fail) | ✓(r2_consistency) | 完整 |
| nextday_gap_check | ✓ | ✓ | — | — | — | 完整 |
| s06_snapshot | ✓ | ✓ | — | — | ✓(check_s06) | 完整 |
| check_data_gap | ✓ | ✓ | — | — | ✓(自身即告警) | 完整 |
| daily_brief | — | ✓(EXTRA) | — | — | — | 半覆盖(漏跑无监控,log 异常有) |
| daily_summary_supplement | — | — | — | — | — | **裸奔** |
| brief_push | — | — | — | — | — | **裸奔+退出码恒0(见 §3-2)** |
| fetch_news | — | ✓(EXTRA) | — | — | — | 半覆盖(漏跑无监控,log 异常有) |
| pf_score_daily | — | — | — | — | — | **裸奔** |
| pf_score_weekly | — | — | — | — | — | **裸奔** |
| pf_stage0_nav | — | — | — | — | — | **裸奔** |
| pf_stage0_overview | — | — | — | — | — | **裸奔** |
| pf_stage0_risk | — | — | — | — | — | **裸奔** |
| pf_stage0_manager | — | — | — | — | — | **裸奔** |
| public_fund_daily | — | — | — | — | ✓(基金 nav checker 11/12) | 半覆盖(数据层兜底,任务层无) |
| public_fund_estimation | — | — | — | — | ✓(同上) | 半覆盖 |
| public_fund_full | — | — | — | — | ✓(同上) | 半覆盖 |
| public_fund_quarterly | — | — | — | — | ✓(同上) | 半覆盖 |
| overfit_monitor | ✓ | ✓ | — | — | — | 完整 |
| lab_auto | ✓ | ✓ | ✓ | — | — | 完整 |
| us_stock_morning | ✓ | ✓ | ✓ | — | — | 完整 |
| self_heal | — | — | ✓(schedule_monitor 查) | ✓(failed 降级 SEVERE) | — | 完整 |
| schedule_monitor | — | — | — | — | — | **元监控盲区(见 §6)** |
| backup_db | — | — | — | ✓(notify --severe) | — | 半覆盖(漏跑无监控) |

### 2.3 计数
- **完整监控 15 个**:update_all/intraday_snapshot/backfill_evening/etf_national_team/futures_backfill/lhb_backfill/rzhb_backfill/turnover_backfill/nextday_plan/nextday_gap_check/s06_snapshot/check_data_gap/overfit_monitor/lab_auto/us_stock_morning
- **EXTRA 半覆盖 2 个**:daily_brief/fetch_news(仅 log 异常,漏跑无)
- **自身 notify 半覆盖 3 个**:kelly_intraday_rerun/gold_night/backup_db(脚本真跑才有通知,timer 挂=静默)
- **数据层半覆盖 4 个**:public_fund 系列(任务层无监控,checker 11/12 兜数据)
- **完全裸奔 12 个**:etf_track_index/lof_track_index/fapi_daily/ab_direction_anchor/daily_summary_supplement/brief_push/pf_score_daily/pf_score_weekly/pf_stage0_nav/pf_stage0_overview/pf_stage0_risk/pf_stage0_manager
- **元任务盲区 1 个**:schedule_monitor 自身

## 3 完全无告警的任务(P0 盲区清单)

### 3-1 十二个完全裸奔(挂了没人知道)
```
etf_track_index / lof_track_index / fapi_daily / ab_direction_anchor / daily_summary_supplement /
brief_push / pf_score_daily / pf_score_weekly / pf_stage0_nav / pf_stage0_overview /
pf_stage0_risk / pf_stage0_manager
```
- 不在 schedule_monitor TASKS 15、不在 EXTRA 2、不在 LAUNCHCTL_LABELS 11、无自身 notify、无数据层兜底。
- **pf_stage0_* 4 个 + pf_score_* 2 个**(6 个)是 public_fund 数据链上游;public_fund 数据层有 checker 11/12 兜底,但这些 **stage0/score 任务本身挂了只会在最终 nav 缺失时被 checker 11/12 间接反映(滞后)**,直接挂没人知道。
- **etf_track_index/lof_track_index**:track 指数采集,若挂 → 相关跟踪指数评分用旧值,**无任何告警**。
- **fapi_daily**:fapi 数据日更,今日实测 exit 0(正常),但挂停无监控。
- **ab_direction_anchor**:A/B 方向锚,交易决策相关,挂停无监控。
- **daily_summary_supplement**:日报补充,挂停无监控。

### 3-2 brief_push 永久静默(最隐蔽的结构性盲区)
```
scripts/brief_push_wrapper.sh 设计 exit 0 恒 0;失败只记 brief_push.log,无 notify
```
- **判据**:wrapper 退出码恒 0 → schedule_monitor 漏跑/exit!=0 检查全部不触发;失败无任何 notify 通道。
- **含义**:用户订阅的盘后推送如果断了,**没有任何告警**——只有用户自己发现"没收到推送"。属 P0 盲区。

### 3-3 半覆盖但漏跑静默的 5 个(自身 notify 只在脚本真执行时触发)
kelly_intraday_rerun / gold_night / backup_db(自身 notify)+ daily_brief / fetch_news(EXTRA 只查 log)。
- **timer 整个挂停(不触发)时,自身 notify 永远不执行 = 完全静默**;EXTRA 只监控"跑了但 log 异常"。

## 4 降噪反噬回放(历史真故障套现行 R1~R6 规则,今天还发不发)

> 现行降噪规则 = `scripts/alert_denoise_rules.py` R1~R6(2026-10-01 落地,含 R5 双重致命修复)。

| 历史真故障 | 事件 | 现行规则判定 | 今天会发吗 | 依据 |
|---|---|---|---|---|
| 09-30 22:30 nextday_plan 生成失败 rc=1 | 产物未生成 | R3:产物今日未生成→双保险双响(self+monitor) | **会发(2 条)** | adr R3-B:product 未生成 → self=1 monitor=1 |
| 09-18 冻结表缺失告警 | backtest 拒绝补冻→notify --severe | 非降噪对象(kelly/fetch 保留 R6) | **会发(直发)** | R6 保留直发 |
| us_stock 超时+耗时双发 | 09-30 #4/#5 | R2:同 last_run 合并→发 1 条 | **会发(1 条)** | R2-A 合并只去双通道,不吞 |
| fetch_news 停摆 4h | 09-30 #13 | R6 保留 | **会发** | EXTRA_MARKER_SCANS |
| staticdata 备份连续缺口 | — | R4:连续≥2 天未追平→SEVERE;单日→info | **会发(SEVERE)** | R4-B 真 R2 备份缺口必 SEVERE |
| staticdata oversize(510 文件/872MB) | 例行提醒 | R4:降 info 不推送 | **不发(有意降噪)** | 设计明确,信息留 info_log.jsonl |

**结论:降噪反噬风险总体低。** 已回放的 5 个真故障现行规则都会发;唯一"不发"的是 staticdata oversize——这是设计有意降噪(例行提醒非故障),且留 info_log.jsonl 可追溯。**诚实标注**:降噪后的 info/warn 类(staticdata oversize / 单轮 R2 lag / ETF 净值时滞)只进 `data/alerts/info_log.jsonl`,该文件**无自动消费方**(文档承认"人工按需周查")——用户不看 info_log 时这些"降级但值得知道"的信息等于丢失(已知代价,文档已如实标注)。

## 5 latest.md 双区结构风险(严重告警可被静默覆盖)

### 5.1 机制
- **覆盖区**(头部):`--alert-issue` 走 write_alert(notify.py L1031,覆盖式写入)。
- **流水区**(追加):`--severe` 走 send() _mirror_severe(notify.py L1108,追加式,cap 50 条)。
- **schedule_monitor 告警和恢复都带 --alert-issue**:告警 L2174-2177「计划任务监控告警」,恢复 L2219-2222「计划任务监控恢复」——**两者互相覆盖头部区**。
- **check_data_gap / 回测脚本的 severe 不带 --alert-issue** → 只进流水区。

### 5.2 现场证据(10-03)
```
头部区:10-03 00:45 计划任务监控恢复(fetch_news 恢复,无害)
流水区最新:10-03 00:30 fetch_news R2 上传锁跳过 SEVERE(需人工关注)、10-01 18:30 fetch_news SEVERE
```
fetch_news R2 锁跳过从 09-24 持续到 10-03(9 天未恢复),但头部区显示的是「恢复」——**用户/Claude 开工看头部=看不到真正需要关注的严重告警**。

### 5.3 09-18 被盖掉机制成立性
- 09-18 冻结表 severe 由 backtest/check_data_gap 发(无 --alert-issue)→ 只进流水区。
- 随后 schedule_monitor 每 15min 一轮,任何一条带 --alert-issue 的告警/恢复都会覆盖头部区 → 09-18 severe 被「计划任务监控恢复」等无害消息盖掉。
- **结论:双区结构确实会让"最新一次 monitor 事件"永远压过"最新/最严重告警",严重告警可被静默覆盖。** 属 P0(用户视角:看到恢复=以为没事)。

## 6 元监控(告警任务自身被监控吗)

| 告警任务 | 自身挂停有无人知 | 证据 |
|---|---|---|
| self_heal | ✓ 有 | schedule_monitor LAUNCTL_LABELS 含 self-heal,is-active=failed → SEVERE;且 L1065 self-heal failed 降级 SEVERE |
| check_data_gap | ✓ 有 | schedule_monitor TASKS 含 check_data_gap(漏跑/exit!=0 会报) |
| **schedule-monitor 自身** | **✗ 无 = P0 盲区** | heartbeat 写 /tmp/schedule-monitor-heartbeat.txt,但**全仓 grep 无任何消费方**(grep schedule-monitor-heartbeat 无结果);heartbeat 只写不读 = 写了也没人知道它停了 |
| notify.py | 部分 | notify 发送失败会标 email=FAIL(可见);但 notify.py 自身崩溃 → latest.md 也写不进,无独立元监控 |

**monitor_72h 云上失效残留**:
```
/tmp/monitor_72h_start 不存在;list-timers 无 72h 相关;alert_state 72h_ 键 last_alerted 全在 08-10~08-12(mac 时代)
```
monitor_72h 是 mac 时代临时 72h 监控,云上未迁未跑,但 alert_state.json 里 72h_ 键残留未清理。

## 7 云上 vs 本机通道差异

- **云上 notify.py 读的是云上 trade-data/config**(email.json 字段 smtp/port/user/password/from/to 全有、feishu.json enabled/mode=app/chat_ids/webhook_urls/receive 全有、.env FEISHU_APP_ID/FEISHU_APP_SECRET 键存在)——**无指向已废弃 mac 通道的告警**。
- mac 本机纯开发(launchd 已废弃);云上脚本 schedule_monitor/self_heal 已把 launchctl 状态适配到 systemctl is-active(LAUNCHCTL_LABELS 11 个)。

## 8 反证项(没问题的地方)

1. **主监控链正常**:schedule_monitor 15+EXTRA 2 轮询正常,10-03 18:15 最新轮「OK 所有任务按计划执行,无漏跑,无退出失败」。
2. **通道 50/50 全成功**:近 14 天 50 条 severe 流水无一条 email=FAIL/feishu=FAIL;SMTP 层 254 次全成功。
3. **systemd 近 7 天无意外**:journalctl 仅 fetch-news timeout 4 次(已被 EXTRA 监控覆盖),其余 unit 无 failed。
4. **fapi_daily 今日正常**:10-03 18:10 exit 0(裸奔但当前健康)。
5. **休市期行为正确**:10-02/10-03 无交易日任务告警,只有 fetch_news 持续锁跳过(已告警)。
6. **数据层覆盖面可观**:check_data_gap checker 1-12(北向/accum_nav/宽度/资金面/交易断档/kelly_coverage/基金 nav 11-12)+ check_s06_freshness + check_r2_consistency。
7. **降噪测试完备**:R1~R6 35 项断言全 PASS(含跨轮场景),09-30 15→8 条回归逐条保留。

## 分级问题表

### P0(盲区,建议优先补)
| # | 盲区 | 影响 | 建议方向 |
|---|---|---|---|
| P0-1 | **schedule-monitor 自身挂停无告警**(heartbeat 无消费方) | 监控体系整体停摆无人知 | heartbeat 消费方(独立 cron 检查心跳新鲜度,超时告警) |
| P0-2 | **brief_push 退出码恒 0+无 notify** | 用户订阅推送断了没人知道 | wrapper 失败时 notify --severe;或 monitor 按产物新鲜度检查推送结果 |
| P0-3 | **12 个任务完全裸奔**(etf_track/lof_track/fapi_daily/ab_direction/daily_summary/pf_score×2/pf_stage0×4) | 挂停无人知,评分/指数/日报用旧值 | 纳入 monitor 漏跑名单(TASKS)+按产物新鲜度补数据层检查 |
| P0-4 | **latest.md 双区结构:严重告警被恢复/后续覆盖** | 用户开工看到"恢复"以为没事,真 severe 沉流水区 | 覆盖区语义改为"最新 severe"或覆盖区含最近一次 SEVERE 引用 |

### P1(半覆盖,建议补漏跑监控)
| # | 盲区 | 影响 | 建议方向 |
|---|---|---|---|
| P1-1 | kelly_intraday_rerun/gold_night/backup_db 自身 notify 只在真跑时触发,timer 挂=静默 | 漏跑无人知 | 纳入 monitor TASKS 漏跑名单 |
| P1-2 | daily_brief/fetch_news EXTRA 只查 log 异常,漏跑无 | 漏跑无人知 | 补漏跑名单或产物新鲜度检查 |
| P1-3 | public_fund 系列 4 个任务层无监控(数据层 checker 11/12 有兜) | 直接挂没人知道,滞后到 nav 缺才反映 | 任务层补漏跑监控(优先级低于 P0) |
| P1-4 | monitor_72h 失效残留(72h_ 键 + /tmp 哨兵缺失) | 曾承担 public_fund 漏跑检查,现无覆盖 | 清理残留 or 决定是否重建 72h 监控 |

### P2(观察项/已知代价)
| # | 项 | 说明 |
|---|---|---|
| P2-1 | info_log.jsonl 无自动消费方 | 降噪后的 info 类(staticdata oversize 等)用户不看=信息丢失,建议评估轻量周报 |
| P2-2 | systemd 层失败无自动化消费 | journalctl 只记录不消费(fetch-news timeout 恰被 EXTRA 覆盖,其余 unit 失败有 is-active 兜底) |
| P2-3 | 通道"实际到达率"不可验证 | SMTP/飞书发送成功≠用户收到(邮箱拒收/飞书 bot 异常不在本链);建议保留现有 email=OK 标记做基线 |

---

# 复现段

1. **覆盖矩阵逐行核对**:
   - `ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 "systemctl list-timers --all | grep trade- | wc -l"` → 38 个 trade-* timer
   - `grep -n "TASKS=" /home/ubuntu/code/trade/scripts/schedule_monitor.sh`(云上)→ TASKS 15 个;`grep -n "EXTRA_MARKER_SCANS" /home/ubuntu/code/trade/scripts/gen_schedule_stats.py` → EXTRA 2
   - `grep -n "LAUNCHCTL_LABELS" /home/ubuntu/code/trade/scripts/schedule_monitor.sh` → L958 附近 11 个
   - 裸奔判定:目标任务名依次 grep 上面三处 + grep 自身 notify(notify.py/`--severe`)均无 → 裸奔
2. **通道成功率**:`tail -50 /home/ubuntu/code/trade-data/data/alerts/latest.md` 逐条核对 [email=OK][feishu=OK];`grep -c '邮件已发送至 234058394@qq.com' /home/ubuntu/code/trade-data/data/logs/schedule_monitor_launchd.log` → 254
3. **双区结构**:`head -8 /home/ubuntu/code/trade-data/data/alerts/latest.md`(覆盖区=最近 monitor 事件)vs `tail -5 .../latest.md`(流水区=最新 severe);云上 `grep -n "_mirror_severe\|write_alert" /home/ubuntu/code/trade/scripts/notify.py` → L1108/L1031;`grep -n 'alert-issue' /home/ubuntu/code/trade/scripts/schedule_monitor.sh` → 告警 L2176/恢复 L2221
4. **heartbeat 无消费方**:`grep -r "schedule-monitor-heartbeat" /home/ubuntu/code/trade/scripts/ /home/ubuntu/code/trade-data/ 2>/dev/null | grep -v '\.log'` → 无结果(仅写无读)
5. **monitor_72h 失效**:`ls /tmp/monitor_72h_start`(不存在);`ssh ... "systemctl list-timers --all | grep -i 72h"`(无);alert_state.json 72h_ 键 last_alerted 全 08-10~08-12
6. **降噪反噬回放**:`scripts/tests/test_alert_denoise_20261001.py` 35 项断言(打真实 alert_denoise_rules.py,含 09-30 回归)
