# #228 调研报告:调度监控盲区 —— unit 被 systemd TimeoutStartSec 硬杀,schedule_monitor 仍报「OK 无漏跑」

- 任务来源:#228(pending-features-index 登记行;源自 #223①②③ 取证次生发现,登记 commit `89cd02bc7`)+ 主控附加核查项(问④:CI FAIL 窗口云上影响)
- 角色与方法:调研 agent,只读。本地代码锚点逐行核查 + 云上只读 ssh(事件驱动扫描:`find -mmin` / `journalctl --since` / `latest.md` 双侧 tail / `systemctl show|cat`);全程未执行任何业务脚本(§18 L50 static-only),零真实外发
- 日期:2026-10-07(凌晨);云上扫描时点约 00:32-01:00
- 来源文档:`docs/ops/223-123-inner-timeout-evidence-20261006.md`(已合 main `83db1189f`)

**一句话结论**:`gen_daily_brief` / `fetch_news` 两个「部署外生成器」(EXTRA)不在 schedule_monitor 的任何有效判定通道内,被 systemd 杀是**结构性不可见**;10-04 20:11 `trade-fetch-news` 600s 被杀为 10 月活体直证(监控同期报 OK)。补维度按 §3 的 M1(轮次完整性通道,检测 ≤1-2 个监控轮)主推;`check_failed_units` 全量 failed 通道(10-05 起)已部分兜住但需登记其盲窗与局限;`staticdata_sync` 0 日志为代码结构必然;CI FAIL 窗口(10-06 23:57→00:10)云上**零 deploy 落点、零相关告警**。

---

## 1. 问①:判定源是什么 / 为何 unit 被杀仍判 OK

### 1.1 schedule_monitor 五通道全景(含 EXTRA 扩展,代码锚点)

| 通道 | 判据源 | 锚点 |
|---|---|---|
| ① 漏跑 | TASKS 表(仅 launchd 时代登记任务,last_run<计划时点) | `scripts/schedule_monitor.sh` L94-216(TASKS 表,不含 daily_brief/fetch_news)、L345-422 |
| ② 退出失败 | schedule_stats.json `last_exit`(`null`=进行中/无数据,**不算失败**);standard 任务经 launchctl/systemd 读真实码 | `schedule_monitor.sh` L574-684;`gen_schedule_stats.py` L312-402(`launchctl_last_exit`/`_systemd_last_exit`)、L182-207(LABEL_MAP 17 任务) |
| ②b log 异常关键词 | EXTRA 两任务的轮次作用域标记扫描(⚠→degrade 缓冲 3 轮、✗/R2_UPLOAD_TIMEOUT→critical 首报) | `gen_schedule_stats.py` L142-165(EXTRA_MARKER_SCANS)、L634-696(scan_marker_log) |
| ③ 执行耗时/进行中超时 | DUR_THRESHOLDS 内任务 + IN_PROGRESS_BUFFER(仅 8 任务) | `schedule_monitor.sh` L555-570(DUR_THRESHOLDS 无 daily_brief/fetch_news)、L449-499(`_in_progress_state`:不在 DUR_THRESHOLDS 直接返回 `no`) |
| ④ failed-unit | `check_failed_units.py` 全量 `systemctl list-units --state=failed`(10-05 起) | `schedule_monitor.sh` L1520-1570(调用,rc=1 时 CFU 自身通道发告警)、`scripts/check_failed_units.py` L103-109 |
| ⑤ EXTRA 停摆 | EXTRA 两任务 last_run(=日志文件 mtime)超 26h/4h | `schedule_monitor.sh` L517-520(EXTRA_MARKER_STALE_LOOPS)、L984-1025(判定块) |

OK 行:`schedule_monitor.sh` L2594 `print(f"[{now_str}] OK 所有任务按计划执行，无漏跑，无退出失败")`(alerts 为空时即打印)。

### 1.2 EXTRA 两任务逐通道判定:被杀在每条通道上都被结构性豁免

| 通道 | gen_daily_brief | fetch_news | 机制原因 |
|---|---|---|---|
| ① 漏跑 | 不判定 | 不判定 | 不在 TASKS 表(L94-216) |
| ② 退出失败 | 恒不触发 | 恒不触发 | schedules_stats.json EXTRA 条目 `"last_exit": None`(`gen_schedule_stats.py` L980),消费端「null 不算失败」(L578-581) |
| ②b log 关键词 | 仅当被杀前恰好打出 ✗/⚠ 标记才命中(09 月 8 次中仅 09-28 一次) | 被杀轮次**日志零痕迹**(见 1.3 机制) | 幸运命中=偶然而非覆盖;fetch_news python stdout 块缓冲,SIGTERM 即丢 |
| ③ 进行中超时 | 不判定 | 不判定 | 不在 DUR_THRESHOLDS(`_in_progress_state` L488 直接返回 no) |
| ④ failed-unit | **10-05 合入、10-06 00:15 云上首见**(见 §3 M3) | 同左 | 10-04 时该机制尚不存在;且窗口受 failed 状态保留期限制 |
| ⑤ EXTRA 停摆 | 不触发 | 不触发 | 被杀发生在「开始生成」行写出**之后**(mtime 已刷新 20:40),26h 停摆 26h 内必被下一次运行/跳过行刷新 ⇒ 永不触发;fetch_news 同理(下轮成功即刷新) |

关键补充:`run_daily_brief.sh` 退出码恒 0(L6 注释「失败不阻塞主流程…退出码恒 0」),**脚本自身失败不传导 systemd**;唯一能让 unit 进入 failed 的途径 = 超时被杀(systemd Result=timeout)。因此对这两个任务,「unit FAIL/timeout」与「监控告警」之间此前的唯一桥梁 ②/③ 通道全被上述口径排除。

### 1.3 10-04 fetch-news 活体直证(10 月,与 09 月 8 次同族机制)

云上 journal(仍在库,10-02 起):

- `2026-10-04T20:01:00` Starting Trade fetch-news(:01 轮,timer OnCalendar=*-*-* *:01,45:00)
- `2026-10-04T20:11:00` `trade-fetch-news.service: start operation timed out. Terminating.` → `Main process exited, code=killed, status=15/TERM` → `Failed with result 'timeout'.`(600s 外墙杀死)
- `2026-10-04T20:45:01` 下一轮启动,20:45:25 成功(24s)——**failed 状态保留窗 20:11→20:45 = 34 分钟**
- 同期 `schedule_monitor_launchd.log`:20:15:00 / 20:30:00 / 21:00:02 / 21:15:00 四轮 **全部「OK 所有任务按计划执行，无漏跑，无退出失败」**;20:45:01 轮的 1 个告警经逐行核对 = `update_all 执行耗时 10055s 超阈值 8100s`(并见 14067 行 `[recovery] update_all ...`),**与 fetch-news 无关**;19:30 轮的 fetch_news 告警是另一通道(R2 上传锁连续 3 轮跳过 SKIPPED_LOCKED),亦非被杀。
- 被杀轮在 `fetch_news_launchd.log` **零痕迹**:该脚本全部 print 无 `flush=True`(全文件 0 处),重定向到文件皆块缓冲;SIGTERM 被杀 = 缓冲丢弃(成功轮才有「已写/同步上线完成」两行)。

⇒ 这是「unit 被系统层杀、监控报 OK」在 10 月的完整直证(09 月 8 次只有 2 次有同级直证,见 1.5)。

### 1.4 s06 对照:同死法在「标准任务」上是可见的(证明可行性)

`s06_snapshot` 是 LABEL_MAP 注册任务 ⇒ 走 systemd 真实退出码通道:`_systemd_last_exit` 读 `ExecMainCode=1`(真实码)或 2/3(128+signal,SIGTERM=143)。实证:09-28 被杀发出的 `s06_snapshot 退出失败 last_exit=143` SEVERE 落 `alerts/latest.md`(09-28 23:45 条目),且 10-04 监控日志中该告警 key 仍在 hold(`[hold] s06_snapshot|exit!=0|143 ...`)。**同一次系统行为,s06 有号码告警、daily_brief 零报告——差异只在注册与否。**

### 1.5 09 月 8 次与今日复查口径

- 来源文档口径:12 交易日 8 次杀(09-14/16/17/18/22/28/29/30),其中 2 次直证(09-14 608s 存活 + staticdata 撞满 600.04s;09-28)、6 次高置信推断。
- 今日复查:09 月 journal 已轮转(云上 journal 最早 10-02,`SystemMaxUse=200M`)⇒ 6 次推断**不可再直证**(诚实标注,不夸大)。
- 10 月(10-02 起)新的全量 trade unit 被杀扫描:仅 2 例 —— 10-03 22:19 `trade-check-monitor-heartbeat` 首启失败(exit 2,安装瞬态,当场修复,见 §7)与 10-04 20:11 fetch-news timeout(本报告 1.3)。10-05 后无新例(与 #223⑤ 10-06 23:48 抬外墙后窗口叠加,样本尚少)。

## 2. 问④(主控承诺项):CI FAIL 窗口云上核查

**事实口径**:10-06 23:57→00:10 主仓 CI `check_task_state.py` tasks_refs FAIL(文档机检误报类)。

核查与结论(云上只读实证):

1. **窗口内无 deploy 链落点**。10 月全部 60 份 `deploy_*.log` 清单核对:10-06 末位 = `deploy_20261006_2116.log`(tail:`deploy.sh 结束 2026-10-06 21:16:47 退出码=0`),其后至扫描时(10-07 00:5x)无任何 deploy 日志;10-07 档 zero。常规 deploy 档位(10-01~10-06 规律):02:05 / 05:00 / 16:40 / 17:50 / 21:05(±,多数档位伴随 +10min 第二发);23:57-00:10 不在任何常规档;夜间额外落点仅出现于非例行日(10-02 23:13/23:44、10-05 00:32/00:48,与当晚人工/agent 活动对应)。
2. **journal 窗口扫描**(23:40-00:25):trade 活动仅 heartbeat/fetch-news/schedule-monitor/self-heal 常规轮 + 23:48:13 `#223⑤` 两条 sudo sed(修 unit);无 deploy 相关单元/脚本活动。
3. **deploy_check_task_state_fail 类告警零发出**:`alerts/latest.md` / `alert_state.json` / `notify_dedup.json` 三处 grep = 0/0/0(10-07 复测)。
4. **修复链已闭合**:修复 commit = `2e1a564d5`(10-07 00:03,「修文档机检误报(#227 行 launchctl 引用性提及加 staleness-ok)」);云上 `trade-data-signal` 仓 HEAD=`38c172461`(10-07 00:26),`83475df76` 为其祖先(`merge-base --is-ancestor` 实测 YES)⇒ **修复代码已在云上仓**;下一 deploy 轮(10-07 02:05 档)面对的是已修复树。
5. ⇒ 结论:**该 FAIL 窗口对云上生产 deploy 链零影响**(无落点可拦、无告警需发);fail 属主仓 CI 侧文档机检误报,已在 main 修复并同步至云上仓。
- 诚实标注:「引入 FAIL 的具体 commit」未逐一锁定(以修复 commit 内容与 FAIL 类别匹配为准,引入点非本任务核查对象)。

## 3. 问②:补维度方案(改哪个脚本哪一段)

> 原则:不破坏既有降噪(§降噪必须保留真故障判别维度);复用现成通道结构(dedup/recovered/merge);云上单元与 TASKS 表不动(不新增漏跑口径)。

### M1(主推):schedule_monitor EXTRA「轮次完整性」通道 —— 直接判「开始了没跑完」

**判据(三元素,时钟无关 + systemd 状态增强)**:
①`round_state == "started_unfinished"`:EXTRA 扫描内,最后一轮「开始标记」之后**既无完成标记也无失败标记**(纯日志判据,不依赖 systemd);
②unit 非运行态:读 `systemctl show <unit> -p ActiveState` ∉ {active, activating, reloading}(读不到时退化为纯 age 判据);
③宽限:开始标记时间戳距 NOW > GRACE(建议 10min,覆盖正常短跑 + systemd 状态迟到)。

**改动点**:
- `scripts/gen_schedule_stats.py`:
  - `EXTRA_MARKER_SCANS`(L142-165)每条新增:`completion_re`(完成/失败标记正则)与 `systemd_label`(gen_daily_brief=`com.trade.daily-brief`、fetch_news=`com.trade.fetch-news`;`_label_to_systemd_unit` 映射即 `trade-daily-brief.service` / `trade-fetch-news.service`,复用 L312-402 现成实现)。
  - 完成标记(实测文本,均已存在):gen_daily_brief = `[run_daily_brief] ✓ 完成` / `[run_daily_brief] ✗ 失败 rc=`(`run_daily_brief.sh` L45 起:「开始生成」行 L45、✓ 行 L48、✗ 行 L51);fetch_news = 依赖 M2 新增启动标记(completion = 现有 `[fetch_news] 已写` / `✗ [fetch_news]` 行)。
  - `scan_marker_log`(L634-696)返回值扩展:`round_start_ts`、`completion_seen`(轮次作用域内是否出现 completion_re)。
  - EXTRA 条目组装(L977-990)新增字段:`round_state`、`round_start_ts`、`unit_active_state`、`unit_last_exit`(读法同 standard `_systemd_last_exit`,仅用于文案)。
- `scripts/schedule_monitor.sh`(EXTRA 停摆块 L984-1025 之后插平级块):
  - 新常量(放 L511-520 常量区):`EXTRA_ROUND_INCOMPLETE = {"gen_daily_brief": timedelta(minutes=45), "fetch_news": timedelta(minutes=30)}` + `ROUND_INCOMPLETE_GRACE = timedelta(minutes=10)`(注释:阈值须 > 对应 unit 现 `TimeoutStartSec` 且 << 停摆阈值;仅当读不到 unit 状态时作主判据)。
  - 判定:满足三元素 → key=`f"{task}|round_incomplete"`,走 `seen_keys_this_run.add` + `alert_state` 挂 active(结构完全对齐 L984-1025 停摆块,恢复由既有恢复循环自动发)。
  - 告警文案示例:`SEVERE: gen_daily_brief 轮次未正常收尾(开始 2026-10-XX 20:40,无完成/失败标记,疑被 systemd 超时杀;unit last_exit=143)`。
- **降噪/防双响规则**:同轮 `log_anomaly` 已命中(✗/⚠)→ M1 不报(更具体信号优先;✗ 存在时 started_unfinished 本就为假,⚠ 中途中被杀场景由本规则覆盖);与停摆通道天然互斥(停摆=无开始标记,完整性=有开始无收尾);与 CFU 同事件双报(unit 级+任务级两视角)保留为设计选择——若实施方要单条化,M1 文案可注明「同轮 failed-unit 巡检亦会点名该 unit」。
- **效果**:被杀后 ≤1-2 个监控轮(15-30min)内报出,当晚可见(对照:现状永不;CFU 通道对 fetch_news ~15-30min 见 §M3,对 daily-brief 同为 ≤15min 但语义无归因)。

### M2(fetch_news 前置,一行级):加「轮次开始」标记

`scripts/fetch_news.py` 主流程入口加一行 `print(f"[fetch_news] 轮次开始 {…时间戳…}", flush=True)`。理由(实测证据):现全文件无 `flush=True`(0 处);首处 print 在 L130(HTTP 错误路径);现存 `round_start_re` 实为「已写」行(L142-165 注释明示=采集成功写盘后)——**成功后才写,被杀轮零痕迹**,M1 需要独立「开始」信号。加行后 fetch_news 与 daily_brief 的完整性判据同构。
(可选一并:把被 M1 消费的关键行加 flush;最小化只加启动行。)

### M3(check_failed_units 覆盖确认 + 登记,零代码)

- 现状:全量 `--state=failed` 扫描每 15min 轮随 schedule_monitor 执行(`schedule_monitor.sh` L1538-1557),rc=1 时 CFU 自身通道 `notify --severe --dedup-key failed_units_patrol --dedup-window 21600`(`check_failed_units.py` L191-192)。云上日志首见 10-06 00:15:01(`[196] CHECK_FAILED_UNITS_OK failed=0 watchman=7 个 timer 全部在跑`),至 10-07 00:4x 共 97 条全 OK、错误行 0 条。
- 覆盖力实证(10-04 案例反推):fetch-news 被杀后 failed 状态保留 34min(20:11→20:45),≥2 个巡检节拍 ⇒ 若机制在位,20:15/20:30 轮必抓;daily-brief 被杀 failed 保留至次日运行(近 24h)⇒ 必抓。**即 10-05 之后,本类杀的 unit 级发现已闭环。**
- 诚实局限(登记即可):(a) 仅覆盖 failed 状态存续窗(重试快于 15min 或人工 `reset-failed` 会漏;本项目两任务实测窗 34min/24h,安全);(b) 告警是 unit 级、无任务归因与恢复配对;(c) 09-14~10-04 的 9 次杀发生时该通道不存在(历史盲窗,不可追补)。

### M4:staticdata_sync 日志(见 §4,独立于 M1-M3)

### M5(不推荐,备档说明):systemd `OnFailure=` 单元 / 把 EXTRA last_exit 填真码走②通道

- `OnFailure=`:与 CFU 功能重叠、增加云上手管 unit 面(unit 手动管理、git pull 不更新),不引入。
- 填`last_exit`:会与 CFU + M1 同事件三通道并发,且 EXTRA 语义非标准槽位(现 None 有设计含义),维持 None 不动,M1 文案带出真实码即可。

### 与相邻任务的边界

- #223⑤(外墙 600→1740/1080,10-06 23:48 已生效):M1 阈值设计以新墙为常量前提;M1 不改变任何超时预算,不涉「新墙撞下一轮」议题(该议题属 #223⑤ 独立审头号必答)。
- #227(外层无界+内层偏紧):纯预算轴,与 M1 监控轴独立;若 #227 后续调整链路预算,M1 只需同步阈值注释。
- #212(静默失败家族):本报告为其在「调度监控」侧的实例化,补 M1 属该家族根治动作之一。

## 4. 问③:staticdata_sync 全云树 0 份日志 —— 根因与补法

**代码事实(本地 HEAD 逐行)**:
- `scripts/staticdata_sync.sh` L68-70:`LOGDIR="${LOGDIR:-$REPO/data/logs}"`;`LOG="$LOGDIR/staticdata_sync_$(date +%Y%m%d_%H%M%S).log"`;`mkdir -p "$LOGDIR"`——只建目录,不创建文件。
- 全文件对 `$LOG` 的引用仅 4 处:定义 L69、mkdir L70、注释 L153、**唯一写入点 L158**(guard 错误分支 `2>&1 | tee -a "$LOG"`)。**正常生产路径从不创建 $LOG 文件** ⇒ 结构性必然 0 份(非清理/非轮转)。
- 传播方式:其余输出全部裸 stdout,经调用方 `gen_daily_brief.py` L3147-3178 `subprocess.run(..., timeout=600, capture_output=True)` 捕获,且只打最后一行(L3173-3174)⇒ 中间过程(含锁等待、rsync 进度)不落任何地方。
- 锁等待:L56-63 `exec with_lock.py --block-timeout 3600` 阻塞等锁期间无任何输出通道;被杀时(Python 缓冲 + exec 后新进程)亦无痕。

**云上实测**:`find /home/ubuntu/code -name "staticdata_sync*"` 仅 3 个 `.sh` 副本(assertion4-review-cloud[-old]/trade-data-signal 仓库),0 份 `.log`;全盘 maxdepth 5 扫描 + 全 code 树扫描均 0(见 §6 命令)。

**补法(使「锁等待 vs 同步慢」可判定,一步到位)**:
1. 改固定 append 主日志(如 `$LOGDIR/staticdata_sync.log`),把 L158 guard tee 与主流程关键点统一指向它(避免 per-run 时间戳文件碎片化;如需保留 per-run 名可双写)。
2. 等锁打点两行:exec with_lock **之前**打 `[sync] 等锁开始 <ts>`;持锁重入后(exec 以 `bash "$0"` 重来,L71 一带)打 `[sync] 已获锁 <ts>`——两行时差 = 锁等待时长。
3. 主流程节点打点(rsync/push 前后、总耗时)进同一文件;stdout 行为不变(调用方 capture 不在乎)。
影响面:纯观测增强,不改任何控制流/退出码;无前端/无数据产物结构变化。

## 5. 维度完成度 + 诚实标注

维度清单(§5.1⑤ 自检):
1. 判定源逐通道代码级核查 — 完成(§1.1/1.2,全部锚点)
2. 活体直证(10 月) — 完成(§1.3 fetch-news;§1.4 s06 对照)
3. 09 月 8 次复核 — **部分不可再证**(journal 轮转,§1.5,如实标注)
4. 补维度方案(判据/阈值/去重/恢复/边界) — 完成(§3,含 M5 不推荐理由)
5. staticdata 根因(代码结构 + 云上实测双证) — 完成(§4)
6. CI FAIL 窗口(落点/告警/修复链) — 完成(§2)
7. 全 trade unit 被杀全量扫描(10-02 起) — 完成(§1.5,仅 2 例,含归属定性)
8. 未穷举项(如实列出):`check_data_integrity` 是否覆盖 daily_brief 产物新鲜度(本轮仅单文件 grep 未见条目,未全量核查,若需要另派);fetch_news 除被杀外的其它监控通道全链路(本轮只核到判 OK 所需范围);09 月 journal。

诚实标注汇总:
- journal 最早 10-02;09 月 6 次推断不可再直证;10-04 为 10 月直证。
- `journalctl _SYSTEMD_UNIT=<unit> -S/-U` 组合过滤在本环境返回空(疑字段差异),全部改用「全窗口 + grep」方式,结论不受影响(方法差异记录在案)。
- M1/M2 为方案,未实施(本任务只读);阈值 45/30min 为建议值,须以实施时点的 unit 实值复核注释。
- 云上仓库 HEAD=`38c172461`(10-07 00:26,含 `83475df76`;其后 main 新提交未同步,均为 docs)。

## 6. 复现命令清单(已验证方法/数据源)

云上只读(全部可复跑):
```
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'journalctl --no-pager -o short-iso --since "2026-10-02" | grep -E "timed out. Terminating|Failed with result" | grep -i trade'
ssh ... 'journalctl --no-pager -o short-iso --since "2026-10-04 19:55" --until "2026-10-04 22:30" | grep -E "fetch-news"'
ssh ... 'systemctl show trade-daily-brief.service trade-fetch-news.service -p ActiveState -p Result -p ExecMainCode -p ExecMainStatus -p ExecMainExitTimestamp'
ssh ... 'systemctl cat trade-fetch-news.timer trade-check-monitor-heartbeat.service'
ssh ... 'L=/home/ubuntu/code/trade-data/data/logs; ls $L/deploy_202610*.log; grep "\[196\]" $L/schedule_monitor_launchd.log | tail; sed -n "13427,13460p" $L/schedule_monitor_launchd.log'
ssh ... 'find /home/ubuntu/code -name "staticdata_sync*"'
ssh ... 'for f in $(find /home/ubuntu/code/trade-data -maxdepth 4 \( -name latest.md -o -name alert_state.json -o -name notify_dedup.json \) | head -8); do echo "== $f"; grep -c deploy_check_task_state_fail "$f"; done'
ssh ... 'git -C /home/ubuntu/code/trade-data-signal log --oneline -2; git -C /home/ubuntu/code/trade-data-signal merge-base --is-ancestor 83475df76 HEAD && echo ANCESTOR'
```
本地:
```
grep -n 锚点:scripts/schedule_monitor.sh(num): TASKS L94-216 / DUR_THRESHOLDS L555-570 / EXTRA 常量 L511-520 / EXTRA 停摆 L984-1025 / CFU L1520-1570 / OK L2594
scripts/gen_schedule_stats.py: EXTRA_MARKER_SCANS L142-165 / LABEL_MAP L182-207 / 系统码读 L312-402 / scan_marker_log L634-696 / EXTRA 组装 L977-990
scripts/run_daily_brief.sh L6/L45-53;scripts/staticdata_sync.sh L56-70/L153-158;scripts/fetch_news.py L130/L624/L738/L759
git log --format="%h %ad %s" --date=format:"%m-%d %H:%M" -16 origin/main   # 00:03 2e1a564d5 修复 / 00:09 83475df76 收口
```

## 7. 附带发现(本轮扫描中顺带落档)

1. `trade-check-monitor-heartbeat` 10-03 22:19 安装瞬态:首启 `status=2/INVALIDARGUMENT`(unit 文件 `ConditionPathExists` 误置 [Service] 段被 systemd 警告忽略),当场修好(22:19:46 重写 unit);当前健康(err 日志 10-07 00:26:01 仍在写 `OK heartbeat age≈650s <= 1800s`)。非持续隐患,仅记录。
2. deploy 档位规律(§2 所用):02:05/05:00/16:40/17:50/21:05 ±(+10min 第二发),10 月 60 份日志全貌已核。
3. fetch-news 另有两条独立告警通道在正常工作(佐证其监控面并非裸奔):R2 锁 skip 连续计数(10-04 19:30/21:30 告警-恢复往复)、✗/⚠ 标记通道。
4. `deploy_20261006_2116.log` 尾:`deploy.sh 结束 2026-10-06 21:16:47 退出码=0`(窗口前最后一次 deploy 健康)。

---
(报告完;本任务只读,方案实施另派)
