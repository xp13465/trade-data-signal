# #227 只读定性报告:「外层无界 + 内层预算偏紧」5 条候选 + #228 残余 22 timer 任务级归因缺口盘点

- 任务来源:#227(pending-features-index L352,源自 #223④ 实施者举一反三「乙表」)+ 并入 #228 残余(22 个 trade timer 任务级归因缺口,源自 `docs/ops/228-monitor-dims-impl-20261007.md` §4/§11-1)
- 角色与方法:调研 agent,只读(未改任何代码/未写任何云上文件/未触发任何通知);本地代码逐行核查 + 云上只读 ssh(`ls`/`grep`/`awk`/`systemctl show`/`systemctl cat`/`journalctl`,全部套内层 timeout)+ 日志统计
- 日期:2026-10-10;云上取证时点约 16:41~16:57
- 前置纪律:全程 `timeout N` 包装;`find /` 未用;未跑任何业务脚本(§18 L50 static-only);未调用 notify;未动 systemd

**一句话结论**:#227 五条候选**全部 0 生产触发、全部「不偏紧」**(耗时余量 ≥15x~2000x),建议**不动**(附 1 条可选增强给出但不推荐主动改);#228 残余 22 timer 的「unit 级」可见性**已由 CFU 闭环**(10-08~10-10 失败风暴活体实证,已告警并升级 critical),真正的剩余缺口=**任务级归因**(为何失败/产物是否受影响/要不要补跑),补法建议按 P1(journal 事件通道)> P2(M1 扩表)> P3(产物新鲜度)分层,全部属新面改造须用户拍板。

---

## 1. #227 五条候选逐条定性

### 方法说明(统一定性口径)

每条候选核查 4 层:①行号核实(登记值 vs 现状,代码可能已漂移)②超时后行为(静默?告警?重试?)③外层是否有界(调用链 systemd 约束)④生产取证(触发次数 + 耗时分布)。**「不偏紧」判据 = 生产实测余量 + 超时后行为是否吞真故障**(参照 #223①②③ 先例:触发 0 次 + 正常耗时远离预算 ⇒ 不动,§23.7 冻结面)。

### 候选 1【首推】`scripts/check_signals.py:289` `timeout=30` → `sync_subscriptions_from_cf.py`

| 层 | 证据 |
|---|---|
| 行号核实 | **289 与登记值一致**。`_sync_subscriptions_from_cf()`(L276-296):subprocess.run(`[sys.executable, sync_script]`, capture_output, **timeout=30**) |
| 超时后行为 | `except Exception` → `log.warning("[sync_subscriptions] 同步异常：%s（用旧 config/subscriptions.json）")`(L295-296)。**仅 log.warning,不发通知、不重试** —— 登记描述准确 |
| 内部梯度 | `sync_subscriptions_from_cf.py` 内部网络调用 **timeout=15**(requests L68 / urllib L58)⇒ 15<30,内层先优雅退出,梯度方向正确;唯一能撞 30s 墙的是「内部 15s 也不生效」的卡死(DNS 解析类),那是任何超时值都拦不住的形态 |
| 设计语义 | 文件头(L4-9)自述 best-effort 同步:「失败不阻塞(网络错/密码错/KV 空),用旧 config/subscriptions.json 兜底」⇒ **「超时后静默」是刻意设计**,不是漏设计 |
| 外层约束 | `check_signals.sh` ← `intraday_snapshot.sh` L117(`--intraday`)/ `update_all.sh` / `update_all_serial.sh` / `deploy.sh`;盘中链外层 = **`trade-intraday-snapshot.service` `TimeoutStartSec=0`(=∞ 无界)**(云上快照 `docs/deploy/systemd-units-cloud-snapshot.txt:268` 逐位核实) |
| 生产取证 | **云上 480 轮 check_signals 日志(2026-09-13 ~ 2026-10-09,27 天)**:`[sync_subscriptions]` 行 **480/480 全部「同步成功：2 个订阅」**;**网络错误 0 / 同步异常(含超时)0 / HTTP 错 0 / 未配置密码 0** |
| 耗时分布 | 每轮「sync 完成日志行」与其上一打点行的时间差(取全量 480 文件):**427 轮 0s + 53 轮 1s ⇒ 全部 ≤2s**,对 30s 预算余量 >15x |
| 定性 | **不偏紧;超时后静默属刻意 best-effort 设计(有旧文件兜底),不吞真故障**(吞的只是「新增/变更订阅不回流」这种变更面,且本地旧文件继续生效) |
| 修法建议 | **不改超时值**(0 触发,§23.7)。可选增强(供拍板,低优先):对「连续 N 轮同步失败」加一条 warning 级聚合告警(现仅日志),让「CF 端点持续挂 ⇒ 订阅变更长期不生效」可被看见。因 27 天 0 失败,当前无观测依据,不建议主动实施 |

### 候选 2 `scripts/overfit_monitor.py:1445` `timeout=60` → `notify.py`

| 层 | 证据 |
|---|---|
| 行号核实 | 登记 1438 → **现 1445**(漂移 7 行,原因=#223④ 改过本文件;内容一致:`send_notify()` 内 subprocess.run(notify.py, **timeout=60**)) |
| 超时后行为 | `except Exception → return (False, str(e))`(L1448-1449);调用方 L1943-1946:`ok,err = send_notify(...)`;**`a["sent"]=ok` + `a["notify_error"]=err` 回写进 `overfit_monitor.json`(前端可见字段)⇒ 失败有记账、可追查,非静默** |
| 外层约束 | `trade-overfit-monitor.service` **`TimeoutStartUSec=infinity`**(云上只读实测;与 #223④ 报告一致)⇒ 60s 是唯一墙钟,但无「外层先杀」风险 |
| 生产取证 | 云上 `overfit_monitor_launchd.log`(全窗口):「发送成功」**14 次**、「发送失败」**1 次**;唯一那次 = **`[notify][dedup] suppress key=overfit_param_spike ... age=86394s < window=86400s, 不重发`**(提前 6 秒差 24h 的 dedup 抑制,**设计行为非故障**;notify_sent 判 False 合理)⇒ **timeout=60 生产触发 0 次** |
| 理论最坏核 | notify.py 单渠道超时 30s(SMTP_SSL L1046 / urlopen L547),三渠道**串行**(send() L1160-1165:email→telegram→feishu)⇒ 渠道全挂极端场景理论最坏 ~80-90s > 60s。但该场景=全渠道瘫痪,即使 60s 被杀也是「全失败」语义,且返回 False 有 JSON 记账 |
| 定性 | **不偏紧(0 触发;失败有记账)**。理论串行最坏 >60 属极端场景,无实测样本 |
| 修法建议 | **不改**(0 触发 + 有记账)。若要一律保险可 60→120(与候选 3 的 120 同档),但无观测依据,不建议主动动 |

### 候选 3 `scripts/detect_intraday_anomaly.py:290` `timeout=120` → `notify.py`

| 层 | 证据 |
|---|---|
| 行号核实 | 登记 268 → **现 290**(漂移 22 行)。该调用点 = `_notify_dedup_write_fail()`(**去重文件写失败**告警路径):subprocess.run(notify.py, tier=warning, **timeout=120**) |
| 超时后行为 | `except Exception → print(stderr)`,「不阻塞」(L291-292)。该路径前提=本地 `anomaly_notified.json` 写失败(罕见基础设施故障) |
| 生产取证 | **该路径本身 0 触发**:全云日志(3015 文件)搜「去重写失败告警发送异常」= **0**;**同脚本告警主路径**(`send_alert`, timeout=60,非本次候选)覆盖度:152 次「告警邮件已发」/ 0 次「未确认送达」/ 0 次「告警邮件发送失败」 |
| 外层约束 | 同候选 1:`intraday_snapshot.sh:216` 调本脚本,外层 `trade-intraday-snapshot` = ∞ |
| 定性 | **不偏紧**(120s 对 30s 单渠道的内部超时余量 4x+;且路径 0 触发) |
| 修法建议 | **不改** |

### 候选 4 `scripts/with_lock.py:129` `timeout=60` → `notify.py`

| 层 | 证据 |
|---|---|
| 行号核实 | **129 与登记值一致**。`_notify_block_timeout()`(L96-132):排队等锁超时跳过告警,subprocess.run(notify.py, tier=warning, dedup 6h, **timeout=60**) |
| 超时后行为 | `except Exception → print(stderr)`「不阻塞跳过」(L131-132) |
| 路径可达性 | 内置 notify 仅在「block_timeout>0 且**无 --on-timeout 钩子**」时走(L164-171);核实三处 --block-timeout 3600 调用点(`deploy.sh:656` / `staticdata_sync.sh:61` / `staticdata_backup_async.sh:219`)**均不带 on-timeout** ⇒ 内置 notify 路径生产可达(登记「update_all / lab-auto」措辞=用该锁的链,实际直调名单如上) |
| 生产取证 | 全云日志:「排队等锁超时」(该路径前置事件)**64 次**(27+ 天窗口);「排队超时告警发送失败」(timeout=60 异常)**0 次** |
| 降噪现状 | 该告警 2026-09-24/29 已两轮降噪(SEVERE→warning tier + dedup 30min→6h,注释 L119-125 在案) |
| 定性 | **不偏紧**(64 次前置事件 0 次发送异常) |
| 修法建议 | **不改** |

### 候选 5 `scripts/gen_schedule_stats.py:393,432,477` `timeout=10`(本地 systemctl/launchctl 查询)

| 层 | 证据 |
|---|---|
| 行号核实 | 登记 340,379 → **现 393(launchctl print,macOS 分支)/ 432(`_systemd_last_exit` 的 `systemctl show`)/ 477(`_unit_active_state` 的 `systemctl show`)**,数量从 2 处增为 3 处(#228 新增了 477 那处,同模式) |
| 超时后行为 | 三处均 `except Exception → return None`(降级「未知」,不猜 143,**fail-open**)—— 语义=读不到就不判,不会把超时误报成故障 |
| 耗时实测 | 云上 `systemctl show trade-intraday-snapshot.service -p LoadState` **3 次实测 3~5ms**(real 0m0.005s / 0m0.003s / 0m0.003s)⇒ 对 10s 余量 **~2000x** |
| 定性 | **既有判定「10s 够、不偏紧」核验 PASS** |
| 修法建议 | **不改** |

### 附 1:同族记录(不在候选清单,只报不改)

- `detect_intraday_anomaly.py:325` `send_alert` 调 notify.py `timeout=60`(登记乙表未含)。覆盖度:152 次已发 / 0 失败(见候选 3 表)。同族同定性。
- `overfit_monitor.py:1969` 起 R2 上传 subprocess:`--skip-if-locked`+1869 行处已由 #223④ 走查(180→900+R2_UPLOAD_HTTP_TIMEOUT=600,`OVERFIT_SKIP_R2`);本报告未重复核查。

### 附 2:`systemd_timeout_gradient_audit.py` 扩轴建议(登记原文要求核实)

- **现状自述核实(读码确认)**:脚本 docstring「局限」段原文:「只识别 shell 层 `run_to N` / `perl -e 'alarm ...' N`;**Python 侧 subprocess timeout(如 nextday_gap_check.py 的 60/300/120)不计入**——这类 service 无 shell 内层看门狗,外层 systemd 即唯一看门狗,不存在『内层 > 外层』倒挂。」
- **该自述的理由在 #223 场景成立,但 #227 场景暴露其盲区**:#223 域=外层有限(600),inner≤outer 即安全;#227 域=**外层 ∞,Python 侧 timeout 就是唯一墙钟**——它的「偏紧/偏松」「与外层谁先跑」完全不被审计覆盖(#223⑤ 的 `timeout=600 == systemd 600` 零梯度也是这一轴)。
- **建议(扩展方向,供拍板)**:审计加第 3 轴=「Python `subprocess.run(..., timeout=N)` 静态扫描(process 调用点,标注被调脚本)」,与 unit 的外层值比对,输出三类:**①内层>外层倒挂(危险)②内层==外层零梯度(危险,references #223⑤)③外层=∞ 内层有限(信息级,列余量)**。落地注意:Python 侧多为动态值/多分支,静态扫描须防误报(可用「仅扫字面量 timeout=N + 已知实参」起步,与本次 5 条候选一致口径);成本中等,建议与 P2 合批评估。

---

## 2. #228 残余:22 个 trade timer「任务级归因缺口」盘点

### 2.1 覆盖结构(41 = 19 + 22,逐名核对无误)

云上实测 `systemctl list-timers "trade-*"` = **41 个** trade timer(与 228-prod-verify 报告一致)。划分:
- **19 个已覆盖** = TASKS 表 17(`schedule_monitor.sh` L99-218:`update_all`/`backfill_evening`/`intraday_snapshot`/`futures_backfill`/`lhb_backfill`/`rzhb_backfill`/`etf_national_team`/`lab_auto`/`us_stock_morning`/`overfit_monitor`/`s06_snapshot`/`check_data_gap`/`r2_consistency`/`cloud_unit_patrol`/`turnover_backfill`/`nextday_plan`/`nextday_gap_check`)+ EXTRA 2(`gen_daily_brief`/`fetch_news`,M1/M2)。
- **22 个缺口**(名单复核与 impl 报告 §4 一致):`ab-direction-anchor`、`backup-db`、`brief-push`、`check-monitor-heartbeat`、`daily-summary-supplement`、`etf-track-index`、`fapi-daily`、`gold-night`、`kelly-intraday-rerun`、`lof-track-index`、`pf-score-daily`、`pf-score-weekly`、`pf-stage0-{manager,nav,overview,risk}`、`public-fund-{daily,estimation,full,quarterly}`、`schedule-monitor`、`self-heal`。

### 2.2 22 个缺口清单 + 现状表(云上实测,2026-10-10)

「外层墙」= `TimeoutStartSec`(0=∞ 结构性不会被 systemd 超时杀);「被杀暴露」= 会不会真被系统层杀;「日志形态」= 轮次标记素材。

| timer | 计划(云上实测) | 外层墙 | 日志(appender)与标记形态 | 备注 |
|---|---|---|---|---|
| ab-direction-anchor | 21:15 每日 | 600 | out.log 139 行,业务结论行,无标准开始/完成 | 21:15 单独槽 |
| backup-db | 21:00 每日 | **0(∞)** | 自管 per-run `backup_db_<ts>.log`,有「开始」+「✓ xx备份完成」 | 不会被 timeout 杀 |
| brief-push | 20:45 每日 | 600 | 固定 append,**已有 `[brief_push_wrapper] start` + `✓ 完成`**(M1 同构现成) | 简报推送,用户面 |
| check-monitor-heartbeat | 每 15min | 600 | 输出走 .log/.err,正常轮静默(OK 行在 .err);**CFU ②层 WATCHMAN 已覆盖其存活** | 心跳消费者 |
| daily-summary-supplement | 20:30 每日 | 600 | .log 0 行(输出静默),.err 兜底 | 摘要补充 |
| etf-track-index | 周日 03:30 | 600 | append 41 行,尾部「✓ 生成 etf_track_index.json…」;无开始行 | 周频产物 |
| fapi-daily | 18:10 每日 | **0(∞)** | append 801 行,「…done」标记 | **10-08 19:23 被 OOM-kill(活体,见 2.3)** |
| gold-night | 02:40 每日 | **0(∞)** | append,「开始」+「✓ …完成」;链尾含 push_schedule_stats | 不会被 timeout 杀 |
| kelly-intraday-rerun | 09:40 每日 | 600 | append,**「开始」+「主体完成…退出码=0」**;有锁重入段 | 盘中链 09:40 |
| lof-track-index | 周日 04:00 | **0(∞)** | append 45 行,业务行 | 不会被 timeout 杀 |
| pf-score-daily | 16:00 每日 | 600 | 自管 `pf-score-daily.log`(append);-launchd.log 仅 5 行 | public-fund 系 |
| pf-score-weekly | 周日 03:17 | **0(∞)** | 同上 | 周频 |
| pf-stage0-manager | 每月 01 02:47 | **0(∞)** | 自管 `stage0-manager.log`(append);-launchd.log 0 行 | 月频 |
| pf-stage0-nav | 周五 01:43 | **0(∞)** | 自管 `stage0-nav.log`(append,断点续采) | 周频 |
| pf-stage0-overview | 周日 02:17 | **0(∞)** | 自管 `stage0-overview.log`(.launchd.log 有历史 PermissionError 行) | 周频 |
| pf-stage0-risk | 每月 15 02:33(季度闸门) | **0(∞)** | 自管 `stage0-risk.log`(append) | 月频 |
| public-fund-daily | 16:30/17:00 | **900** | append 5877 行,「开始」+「结束…deploy=N」 | **10-08 两轮 exit-code failed(活体)** |
| public-fund-estimation | 10:00/11:00/13:30/14:30 | 600 | append 660 行,「开始」+「结束」 | 盘中链 |
| public-fund-full | 22:00 每日 | **0(∞)** | append 757 行 | 不会被 timeout 杀 |
| public-fund-quarterly | 03:00/04:00/07:00 | **0(∞)** | append 1602 行 | 不会被 timeout 杀 |
| schedule-monitor | 每 15min | 600 | append,**CFU ②层 WATCHMAN 已覆盖其存活**;自身即监控中枢 | 元监控 |
| self-heal | 每 15min | 600 | append 14774 行,按轮「HEAL 触发…」;**CFU ②层 WATCHMAN 已覆盖** | 自愈 |

统计:**11 个外层 ∞(结构性免被杀)** + 11 个有限(600×10 + 900×1,**可被杀**)。「可被杀」的 11 个 = ab-direction-anchor / brief-push / check-monitor-heartbeat / daily-summary-supplement / etf-track-index / kelly-intraday-rerun / pf-score-daily / public-fund-daily / public-fund-estimation / schedule-monitor / self-heal。

### 2.3 活体实证:10-08 ~ 10-10 失败风暴(新发现,修正「unit 级是否可见」悬疑)

**轮转窗口内 journal 全量扫描**(`--since 2026-10-02`)**发现 10-08 节后首日起一批 unit 失败**(228 报告 10-07 时点尚未出现):

```
10-08 09:40 kelly-intraday-rerun  exit-code      10-08 19:23 fapi-daily        OOM-kill(主机 OOM killer,task_memcg=trade-fapi-daily.service,被 kill python RSS≈2.0GB)
10-08 16:39/17:06 public-fund-daily exit-code    10-08 19:29/19:37 lhb-backfill  exit-code
10-08 20:12/21:10 futures-backfill  exit-code    10-08 20:18/21:52 etf-national-team exit-code
10-08 23:23 r2-consistency       exit-code      10-09 08:27 + 10-10 08:27 cloud-unit-patrol exit-code
10-09 09:31 nextday-gap-check    exit-code(2/INVALIDARGUMENT)
```

**CFU 通道对此全部有效(实测证据,修正此前疑问)**:
- `schedule_monitor_launchd.log` 中 `CHECK_FAILED_UNITS_FAIL` 输出共 **218 条**,逐条点名上述 unit(如 70 条 nextday-gap-check、36+28+9… 条 7-8 unit 大集合);schedule_monitor 汇总行为「`[196] 云上 unit 异常(自身通道已发告警): …`」。
- CFU 真发链核实:schedule_monitor L1792-1796 调 CFU 带 **`--notify`**(真发);`data/failed_units_patrol_state.json`:`first_fail_date=2026-10-08, consecutive_days=3, last_grade_time=2026-10-10 00:00:02`;`data/alerts/latest.md` 有 **「[severe] 2026-10-10 00:00:09 · [告警] 云上 failed unit 持续未清(连续 3 天, 升级 critical) email=OK feishu=OK」**。
- 当前(10-10 16:45)failed 存续:`trade-cloud-unit-patrol.service` + `trade-nextday-gap-check.service`(patrol 走包装器通道定向抑制)。

**这组风暴同时暴露「任务级缺口」的真实差距**(与 228 报告 §M3 三局限互相印证):
1. 告警只到 unit 级:「trade-public-fund-daily.service failed」,**「为什么失败/产物有没有受影响/要不要补跑」无归因**。抽查 public-fund-daily:两轮链内日志尾部均正常(「结束…deploy=1」+ push_schedule_stats 退出码=0),失败原因=**deploy.sh 返回码 1**(FINAL_RC 机制,脚本尾部 L41-47),需人工另行排查 deploy 侧;fapi-daily 的 OOM 归因只在 **journal**(内核 oom-kill 行),.err 日志 0 痕迹。
2. CFU 三局限原样成立:①只覆盖 failed **存续窗**(重试快/人工 reset 会漏)②unit 级、无恢复配对 ③历史盲窗(10-05 前不覆盖)。
3. **19 覆盖组内的任务**(etf-national-team/futures-backfill/lhb-backfill/r2-consistency/nextday-gap-check)同轮也失败——它们有 ②通道(exit!=0 任务级归因)兜底,与 22 缺口组的对比正好构成「注册 vs 未注册」差分(同 #228 §1.4 s06 对照精神)。

诚实标注:10-08 风暴的业务根因(节后首日数据量/deploy 侧问题/OOM 内存竞争)不在本报告范围,未逐链深挖;「fapi-daily OOM」为journal 逐行直证。

### 2.4 剩余面定性 + 补方案建议(供拍板;只读报告不实施)

**剩余面准确定义**(修正 228 报告一句「仅靠 CFU unit 级兜底」的模糊处):
- 已完成:**unit 级事件可见(CFU,10-05 起,含 10-08 风暴实证)**;
- 未完成:**任务级三件事**——(a)「轮次完整性/为何失败」归因 (b)「产物是否受影响」对账 (c)「恢复配对/补跑提示」。22 个中 3 个(`schedule-monitor`/`self-heal`/`check-monitor-heartbeat`)另有 CFU ②层 WATCHMAN 存活覆盖(LoadState/UnitFileState/timer ActiveState/脚本存在性),单独做任务级性价比低。

**补方案分层建议**:

- **P1(journal 事件通道,建议首选)**:schedule_monitor 每 15min 增一块,扫 journal 窗口:`systemctl` 无法给的**事件流**——`timed out. Terminating` / `Failed with result`(exit-code/oom-kill/timeout 全 Result 型)/ `killed by the OOM killer`,按 unit→任务映射表(复用 TASKS/LABEL_MAP + 22 个的补充映射)输出「<任务>(<unit>)在 <t> 被 <result> 失败」。**优势**:①不依赖脚本改造(22 条链的日志标记形态参差,见 2.2 表)②不依赖 failed 存续窗(CFU 局限①直接消掉:重试快于 15min 也抓得到)③一次覆盖全部 41 timer + 未来新增。**落地要点**:事件级降噪(同 unit+result 去重窗,复用 alert_denoise_rules 先例);事件流无恢复语义,只报事件、恢复仍由 CFU 集合通道承担(不冲突);`ubuntu` 用户 journalctl 可读(本报告取证即用)。成本:低(一个块 + 一张映射表)。
- **P2(M1 同构扩表,第二梯队)**:M1 机制(`EXTRA_MARKER_SCANS` + round_incomplete 通道)现成;**已有「开始+完成/结束」标记**的链可低成本扩表:`brief-push`(start/✓ 完成)、`kelly-intraday-rerun`(开始/主体完成/退出码)、`gold-night`(开始/✓)、`backup-db`(开始/✓)、`public-fund-daily/estimation/full/quarterly`(开始/结束行)——扩前须逐链核「完成标记覆盖全部正常出口 + 跳过行并入终态」(M1 上线时踩过的点)。⚠️ 但注意其中 gold-night/backup-db/public-fund-full/quarterly **外层 ∞,被 timeout 杀概率≈0**,优先级低于 P1。
- **P3(产物新鲜度扩展,劣后)**:对「产物可反证」的链加新鲜度检查(照 `check_s06_freshness.py` / `check_data_integrity` 模式):etf/lof track index(周频)、pf 系(周/月频)、fapi/gold-night 数据产物。**只对高价值产物面**,不是全部。
- **不做**:`schedule-monitor`/`self-heal`/`check-monitor-heartbeat`(CFU ②层已覆盖);`ab-direction-anchor`(夜间实验链、非用户面,暂不投)。

**边界与纪律**:方案动的是已上线功能(schedule_monitor)= §23.7 冻结面,**须用户拍板后另行派实施**;本报告只做定性+方案,未动任何代码。与 #223⑤ 已生效的外墙(1740/1080)关系:P1 的 journal 通道与外墙值解耦(记录事件本身,不消费预算值);P2 扩表时阈值注释按 M1 先例同步。

---

## 3. 维度完成度 + 诚实标注

维度清单(§5.1⑤ 自检):
1. 候选 1-5 逐条 4 层核查(行号/超时行为/外层/生产取证) — 完成(§1;行号漂移 3 处已逐处订正)
2. 生产触发次数 + 耗时分布(乙表要求的「判断→统计」升级) — 完成:候选 1(480 轮全成功 + 耗时 ≤2s)、2(15 发送 0 超时)、3(0 触发 + 152 主路径成功)、4(64 前置事件 0 异常)、5(3-5ms 实测)
3. 附项核验(同族记录 + audit 扩轴建议) — 完成(§1 附 1/附 2)
4. #228 残余 22 timer 全名单 + 当前态(计划/外层墙/日志形态) — 完成(§2.2,云上逐个实测)
5. 活体样本(10-08 风暴)+ CFU 有效性实证 — 完成(§2.3;此前未有任何报告记录该风暴)
6. 补方案建议(分层 + 优先级 + 不做清单 + §23.7 边界) — 完成(§2.4)
7. **未穷举项(如实列出)**:①各 22 链脚本的「开始/完成标记逐链完备性」未逐行审计(2.2 表只到「日志形态」粒度;P2 落地前须补)②10-08 风暴各链业务根因未深挖(出范围)③notify.py 渠道最坏耗时未实测(禁触发通知,推演值已标注)④60s/90s 的 Python 侧理论最坏只有推演,无实测样本。

诚实标注:
- 云上日志窗口:check_signals 起溯 2026-09-13(更早被清理);journal 起溯 2026-10-02(09 月已轮转)。「0 触发」口径=上述窗口内,窗口前不可追证。
- 候选 2/3 的行号漂移(1438→1445、268→290)由 #223/#241 系列改动造成;候选 5 增第 3 处(#228 新增 `_unit_active_state`),均已在表内订正。
- CFU 判定「抓到」的证据链=日志 218 条 FAIL 行 + state 文件 + latest.md 三处互证(未采信单一处)。
- P1/P2 为方案建议,未实施;成本/优先级为主观排序,基于「覆盖面 × 依赖改造量」两个可复核维度。
- 本报告仅新增 1 个文件,未 commit(遵任务纪律)。

## 4. 复现命令(已验证方法/数据源)

```
# 候选 1 生产统计(全窗口)
ssh ... 'cd /home/ubuntu/code/trade-data/data/logs && grep -h "sync_subscriptions" check_signals_*.log | grep -c "同步成功"'   # → 480
# 候选 1 耗时分布(全 480 文件「sync 行-上一打点」秒差)
ssh ... 'for f in $(grep -l "sync_subscriptions" check_signals_*.log); do awk ... done | sort -n | uniq -c'  # → 427×0s + 53×1s
# 候选 2/3/4 事件统计
ssh ... 'grep -c "发送失败" overfit_monitor_launchd.log; grep -h "排队超时告警发送失败" *.log | wc -l; grep -h "去重写失败告警发送异常" *.log | wc -l; grep -h "告警邮件已发" *.log | wc -l'
# 候选 5 耗时实测
ssh ... 'time systemctl show trade-intraday-snapshot.service -p LoadState'
# 22 timer 清单与 unit 详情
ssh ... 'systemctl list-timers "trade-*" --no-pager --no-legend; systemctl cat trade-<x>.service | grep -E "ExecStart|TimeoutStartSec|StandardOutput"'
# 10-08 风暴与 CFU 有效性
ssh ... 'journalctl --no-pager -o short-iso --since "2026-10-02" | grep -E "timed out. Terminating|Failed with result" | grep -i trade-'
ssh ... 'grep -c "CHECK_FAILED_UNITS_FAIL" schedule_monitor_launchd.log; cat data/failed_units_patrol_state.json; tail -12 data/alerts/latest.md'
# 本地锚点
scripts/check_signals.py:276-296 / scripts/overfit_monitor.py:1428-1449,1936-1952 / scripts/detect_intraday_anomaly.py:276-292,321-337
scripts/with_lock.py:96-132 / scripts/gen_schedule_stats.py:388-490 / scripts/check_failed_units.py / scripts/schedule_monitor.sh:99-218,1774-1824
docs/deploy/systemd-units-cloud-snapshot.txt:254-268(trade-intraday-snapshot TimeoutStartSec=0)
```
