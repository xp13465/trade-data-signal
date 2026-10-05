# #160 §22 三站一致性校验器接线(闸门位置 + 爆炸半径 + 实跑证据)

> 日期:2026-10-05 | 任务:#160 | 分支:`feat/160-consistency-gate-20261005`
> 来源:`docs/ops/cloud-healthcheck-20261003/D5-deploy-chain-audit.md` **P0-1**(local vs R2 vs CF r2-proxy 9 个核心产物一致性零自动校验)
> 关联:§22 数据一致性铁律 / §14 生产稳定性 / §24 前端部署 / D5 P0-1

## 0. 结论速览

| 项 | 结论 |
|---|---|
| 闸门位置 | **独立每日云上 timer(23:20)+ 仅告警**,**不放 deploy 链**(爆炸半径分析见 §2) |
| 判定口径 | local / R2直链(ssd) / CF r2-proxy(ss/r2) / 主站同源(ss/data) **四源指纹比对** 9 个核心产物 |
| FAIL 处置 | **仅告警不阻断**(rc!=0 → `notify --severe` 去重 6h);不在任何推送链上,无「阻断谁」的动作 |
| 生产目录实跑 | 云上 `/home/ubuntu/code/trade-data`(真实产物)**9/9 各源一致 rc=0**,耗时 2m05s(详见 §5) |
| 实跑发现并修复 | concepts 误加 MAIN 腿 → 云上实测 404(worker 无 `/industry/` rewrite,前端读 `/r2/industry/`)→ 按实测路由移除该腿 |
| 举一反三 | 补主站同源(`/data/`)腿、核两备站 `/data/` 面、并发现计时器计数口径历史漂移(§7,已上报不擅改) |

## 1. 先验实物(§23.11)

| 核实物 | 实测 |
|---|---|
| 校验器存在? | `scripts/check_r2_consistency.py` **存在**(438 行,已能跑),云上 md5 == 本地 HEAD md5 |
| 有无调度? | **无**。云上无 `trade-r2-*` unit;`schedule_monitor.sh:157` 仅注释引用;日志无运行痕迹 → D5「已死」属实 |
| 能否跑? | 能跑,但云上(阿里云境内)→ CF 边缘 **未压缩下载极慢**(concepts 32.3MB 需 95.5s,identity 下行 ~0.34MB/s),全量四源裸跑 >12min → 已加 `Accept-Encoding: gzip`(同文件 7.6MB/7.1s,13.4x) |

> 结论:D5 P0-1 描述属实(非照抄),校验器是「有器无梭」——本体在、调度缺。

## 2. 闸门位置方案 + 爆炸半径分析(不默默选)

### 倾向方案(采用):独立每日云上 timer + 仅告警

- **位置**:新 `trade-r2-consistency.timer`,每日 **23:20**(安全窗口 23:00 后;当日晚链终态后:overfit 21:40 / public-fund-full 22:00 / nextday-plan 22:30 / check-data-gap 22:35)。
- **处置**:rc!=0 → `notify --severe`(去重 6h);rc=0 静默。
- **每日跑不限交易日**:「各源一致」是不变量,周末被外部覆盖同样要抓。

### 为何不放 deploy 链(爆炸半径论证)

1. **结构性假阳**:deploy.sh 段1 末尾 R2 上传已**异步化**(`r2_upload_async.sh`,2026-10-04)——该时刻 R2 可能**正在写**、CF purge 未生效,此刻比对必假阳。
2. **半完成态**(`main-merge-fail-leaves-half-merged-main` / §23.11):卡 deploy = 数据已上 R2 而 min 未推的**半完成态**;FAIL 停在 deploy 中段,恢复路径复杂(deploy 非幂等,重跑风险)。
3. **覆盖面更窄**:deploy 链闸门只在**跑了 deploy 时**触发;**「deploy 根本没跑 / R2 被外部覆盖」的持续态抓不到**——而 10-02 事故(overview 旧版 6 天无人知)恰是持续态。周期采样器天然覆盖持续态。
4. **零 deploy 爆炸半径**:独立 timer 采样点在稳定态(当日晚链完成后),不夹在任何推送链中间,FAIL 无下游影响。

### 备选(未采用)及否决理由

| 备选 | 否决理由 |
|---|---|
| 接入 `schedule_monitor` 15min 巡检 | 全量四源 ~152MB/run → ~14.6GB/天(实测量级),且改动**在跑的**监控脚本 = 放大爆炸半径 |
| deploy 段1 末尾同步闸门 | 见上 1/2/3:异步上传致假阳 + 半完成态 |
| 前端 fetch 时实时校验 | 用户侧开销 + 无集中告警出口 |

## 3. 接线实现(交付物 + 登记点)

| 产物 | 说明 |
|---|---|
| `scripts/check_r2_consistency.py`(改) | FILES 由三元组改为**多腿**结构;新增 **MAIN 主站同源腿**;gzip 传输;TIMEOUT 12→25;concepts 按实测路由改两腿 |
| `scripts/check_r2_consistency.sh`(新) | 包装(`check_data_gap_alerts.sh` 同款:`run_to` 超时、固定名 `r2_consistency_launchd.log` 标准开始/结束行、rc!=0 → notify --severe 去重 6h) |
| `scripts/schedule_monitor.sh`(改) | TASKS 补 `r2_consistency`(漏跑+进行中超时监控;`trading_day_only=False`) |
| `scripts/gen_schedule_stats.py`(改) | TASKS + **LABEL_MAP** 同步注册(缺 LABEL_MAP → standard 模式启发式误报 exit 143) |
| `docs/deploy/systemd-units-20260912.md`(改) | §2.37 unit 内容 + §9 append 例外清单 5→6 |
| **云上 unit 安装** | `trade-r2-consistency.timer/.service` 已装 + `enable --now`(含 `ConditionPathExists` 守卫,见下) |

**顺序坑根治**:service 含 `ConditionPathExists=/home/ubuntu/code/trade-data/scripts/check_r2_consistency.sh`——脚本未 merge+云上 git pull 到位前,timer 触发 service **直接 skip(不算 failed)**,到位后自动生效(同 `trade-check-monitor-heartbeat` 先例)。2026-10-05 实测:list-timers 已挂 NEXT=23:20,手动 start 得「Condition check resulted in ... being skipped」。

**无 StandardOutput append**:脚本自己写同名 `r2_consistency_launchd.log`,按 systemd-units §1.4 例外条款(2026-09-15 root 属主冲突根治)刻意不设 append。外层 `TimeoutStartSec=960` > 内层 `run_to 900`,留梯度防 systemd SIGKILL 打断「结束」日志行(否则 schedule_monitor 漏跑检查误判 runaway)。

## 4. FAIL 阻断 vs 仅告警 的取舍与依据

**选仅告警**。依据:本检查**不在任何推送/发布链上**(独立 timer),因此**不存在「阻断谁」的动作**,「阻断」在此无对象;告警本身即收敛出口。若硬要「阻断」,只能落到 deploy 链,而 deploy 链闸门已被 §2 论证否决(假阳+半完成态)。故本场景下「阻断」不是更严,而是更错。

告警噪音控制:去重键 `r2_consistency_fail`、窗口 21600s(6h)——持续态 6h 内只报一次;瞬态网络抖动由 `_fetch_json` 内 2 次重试吸收(不升级为假警)(`alert-denoise-keep-fault-discriminator`:真故障持续不可达重试后仍报,判别维度不丢)。

## 5. 生产目录实跑真实结果(当前真实产物)

**命令**(云上生产目录,untracked 临时副本,跑完即删):
```
cd /home/ubuntu/code/trade-data
time REPO=/home/ubuntu/code/trade-data GIT_REPO=/home/ubuntu/code/trade-data-signal \
  /home/ubuntu/code/trade-data/.venv/bin/python /home/ubuntu/code/trade-data-signal/scripts/_tmp_check_r2_160c.py
```

**真实输出**(2026-10-05,9/9 一致 rc=0,real 2m04.8s):
```
=== R2 产物多源一致性审计 ===
  local: /home/ubuntu/code/trade-data-signal/static-site/data
  R2:    ssd.fx8.store/data    CF: ss.fx8.store/r2/data    MAIN: ss.fx8.store/data
  ✓ overview (18 项指纹)  ✓ board_etf_map (5)  ✓ concepts (5)  ✓ overfit_monitor (7)
  ✓ overfit_monitor_ext (3)  ✓ nextday_plan (4)  ✓ auto_trade_steps (4)
  ✓ signal_kelly_day_snapshot (8)  ✓ accum_nav_map (7)
=== 各源一致 ===  EXIT=0
```

**过程中发现并修复的真实问题(非只报 PASS)**:
- 首跑(未加 gzip)9/9 一致但 **MAIN 腿 concepts 报 404**。核查:`worker/headers.js` 只 rewrite `/data/*` 与 `/r2/*`,**无 `/industry/` 路由**;前端 concepts 实读 `ss.fx8.store/r2/industry/industry-${range}-concepts.json`(`app.js:25457`)。→ 指 **误加 MAIN 腿 = 假阳**,已按实测路由改为 R2+CF 两腿(`check_r2_consistency.py` concepts 条目注释留证)。
- 云上→CF 未压缩下载 >12min → 加 gzip 后 2m05s。

## 6. 举一反三(§23.3:同模式/同数据源/同组件还被谁用 + 相关展示位)

| 面 | 清单 / 覆盖结果 |
|---|---|
| **同数据源的展示位** | 主站同源 `/data/`(MAIN,**本次补**)、CF r2-proxy `/r2/`(CF)、R2 直链 `ssd`(R2)——前端 `dataUrl()`(app.js:9662)大 range 走 `/r2/`、常规走 `./data/`;两腿并存故 MAIN 有真实价值 |
| **两备站** | sss.sugas.site / s.sugas.site 实测 `/data/` 均 **404**(经 CF/R2 回退取数)→ **无需独立腿**,由 CF/MAIN 两腿覆盖(已注释留证) |
| **同模式的调度巡检** | `check_data_gap`(22:35)为本任务同款先例;其 3 个登记点(schedule_monitor / gen_schedule_stats 双处 / systemd-units doc)本次全部对齐 |
| **同组件(worker 路由)** | 逐条核 `worker/headers.js` 路由(`/data/*` rewrite、`/r2/*` proxy、`/industry/` 无)→ 决定各产物腿数,非拍脑袋 |

## 7. 相关发现(上报,未擅改;§23.7/§23.13)

**systemd-units doc 计数口径历史漂移**:该 doc §0 称「37 个周期任务」、§1.4 称「其余 32 个」、§1.7 称「36 service」,而**云上实测 40 个 `trade-*.timer` / doc §2 共 40 个 `.timer` 单元块**(差异项 = `trade-update-all.timer`,因标题带括号 `(云上实际配置…)` 致 `gen_systemd_units.py` 少解析 1 个 → doc 生成器出 39、+update-all = 40 吻合)。「37」疑为 2026-09-12 迁移批基线而非实时总数。**已在 doc §0 加一行**「37=迁移批基线,截至 2026-10-05 云上共 40」的防误读注,**未改写历史数字**(避免 §23.13 自行选边);是否统一重算计数请主控/用户拍板。

## 8. 复现段(§23.5 四件套:本体+脚本+复现段+commit)

- **本体**:本节文档 + §3 五个代码产物。
- **生成/运行脚本**:`scripts/check_r2_consistency.sh` → `scripts/check_r2_consistency.py`。
- **复现命令**:
  - 本地语法/静态:`python -m py_compile scripts/check_r2_consistency.py scripts/gen_schedule_stats.py && bash -n scripts/check_r2_consistency.sh && bash scripts/lint_scripts.sh`
  - 云上生产目录实跑:见 §5 命令(跑完删 untracked 临时副本)。
  - unit 生成校验:`python scripts/gen_systemd_units.py --check`(应含 `trade-r2-consistency.timer/.service`)。

## 9. 收口(2026-10-05 reviewer 遗留 1 P1 + 3 P2 + 用户追加增强)

> 处置对象:本任务 reviewer 报告的 P1-1 / P2-1 / P2-2 / P2-3 + 用户 2026-10-05 拍板的「连续 2 天 FAIL 升 critical」增强。
> 全部落同一分支 `feat/160-consistency-gate-20261005`(§0.2 续跑不新开分支)。

### 9.1 P1-1 周日 23:20 假 SEVERE(必须在 2026-10-11 首次暴露前落地)

**根因(实测证据,非推断)**:云上 `trade-update-all.timer` = `OnCalendar=Mon..Sat 17:50:00` **+ `OnCalendar=Sun 22:30:00`**(错峰档)、`Persistent=true`;实测一次真实更新 `=== update_all.sh 开始 2026-10-04 22:30:00 ===` → `结束(非交易日)2026-10-05 00:49:02` = **139 分钟**。⇒ 周日链跑 22:30→约 00:49,而 #160 的 23:20 采样点**必落在 update-all 半进程中**:`export` 已写本地 `static-site/data`,而 `r2_upload_async.sh`(段1 末尾已异步化)仍在往 R2 写 ⇒ 此刻 local≠R2 是**过渡态而非故障** ⇒ **每周日 23:20 假 SEVERE**。

**选型 = 方案 (c) preflight(采用)**,三个候选逐条对比:

| 候选 | 内容 | 判定 |
|---|---|---|
| (a) timer 排除周日 | 改 `trade-r2-consistency.timer` 的 OnCalendar 去掉周日 | 否决:只挡「周日这一档」,工作日链一旦延后同样假阳;**且需动云上生产 unit(§25 备份+恢复路径)** |
| (b) 采样点后移到 01:30 | 挪到 update-all 结束之后 | 否决:周日链实测结束 00:49 且 `Persistent=true` 补跑会让时长浮动;01:30 后紧邻 02:00/02:17 深夜档,样本点仍不稳 |
| **(c) preflight 跳过** | `update-all.service` 处于 active(= 晚链在跑)→ 跳过本次检查、写日志、rc=0、**不发告警** | **采用**:对**任意**晚链意外延后(不限周日档)免疫;零云上配置变更(不改 timer/unit ⇒ 无 §25 备份义务);跳过痕留日志可反查 |

**实现**:`scripts/check_r2_consistency.sh` 在 `开始` 行之后、正式比对之前加 `update_all_running()` 判据:①systemd 环境走 `systemctl is-active --quiet trade-update-all.service`(云上服务名已实测确认)②非 systemd(mac 开发)回退 `pgrep -f update_all.sh`③自测用 `R2_CONSISTENCY_PREFLIGHT_STUB=active|inactive` 强制分支(生产不设)。跳过时**刻意写标准结束行** `=== ... 结束 <ts> 退出码=0 ===` 以匹配 `gen_schedule_stats` 的 `END_RE`,让跳过被记为一次正常的 exit-0 运行(**不产生漏跑告警**)。

**判据两态实测(云上只读,未 start/stop update-all)**:
- `systemctl is-active --quiet systemd-journald.service` → **rc=0**(active 语义)
- `systemctl is-active --quiet trade-update-all.service` → **rc=3**(inactive 语义;`is-active` 明文 `inactive`)
⇒ `&& return 0` / `return 1` 两条分支都被真实 systemctl 语义证明;本地测试另覆盖 stub 两态与 pgrep 回退路径。

**代价(如实登记)**:跳过当次 ⇒ 该日一致性**未校验**,由次日 23:20 覆盖。可接受依据:一致性是**持续不变量**(10-02 事故正是持续 6 天无人知),漏一天采样不产生「已确认一致」的假信号;且 update-all 自身失败有独立告警链,**此跳过不吞任何故障**。

### 9.2 P2-1 同一 FAIL 双通道告警 → 加同实例抑制(不削真故障判别)

**问题**:一次 FAIL 会发两封 —— ①包装器 `rc!=0` → `notify --severe --dedup-key r2_consistency_fail`(6h 窗);②`gen_schedule_stats` 记 `last_exit=RC≠0` → `schedule_monitor.sh` 的 `exit!=0` 汇总通道再发一封(other key `f"{task}|exit!=0|{code}"`)。参考先例:`nextday_plan` 有 R3 抑制、`staticdata` 有 R4 抑制,**r2_consistency 此前没有任何抑制**。

**修法**:`scripts/alert_denoise_rules.py` 新增 R7② `r7_r2_consistency_wrapper_alerted(repo, last_run, dedup_key="r2_consistency_fail")` —— 判定依据是**包装器自身通道实际投递的证据**(`data/notify_dedup.json[<key>].last_alerted`),且与 **`last_run` 比较而非与「今天」比较**(故持续到次日也不会在早晨重述)。`schedule_monitor.sh` 在 nextday_plan 的 R3 elif 之后加 R7② elif:成立则**只刷新 alert_state 的 last_alerted 并静默**,不再发汇总封。

**真故障判别维度保留(硬要求)**:`r7_r2_consistency_wrapper_alerted` 任何解析/文件/键缺失错误一律**返回 False(fail-open)**⇒ 包装器若发送失败/被 `run_to` 杀掉/去重文件缺失,汇总通道**照样发**。即「第二封抑制」而非「故障抑制」,真 FAIL 至少 1 封必达。

### 9.3 P2-2 同文档自相矛盾(systemd-units doc 计数)

`docs/deploy/systemd-units-20260912.md:55` 写「共 **5** 个 shell 型」而 `:1616`(§9)已更新为 **6** 个含 `trade-r2-consistency(2026-10-05 追加)` ⇒ 同文档自相矛盾。**已修 L55 → 6 并补单元名**;6+2+32=40 与云上实测总数吻合,**未改写历史计数**(§23.13 不自行选边)。

### 9.4 P2-3 注释与实现不符(进行中超时覆盖实际不存在)

`scripts/schedule_monitor.sh:152-154` 原注释称「只管漏跑+进行中超时」,但 r2_consistency **不在** `DUR_THRESHOLDS` 中,进行中收集还要求 `_dur_task in DUR_THRESHOLDS` ⇒ 进行中覆盖**名义存在、实际不生效**。

**选型 = 改注释对齐实现,不补 DUR_THRESHOLDS(采用)**,理由(在注释里写明):
- 取 **900** ⇒ 被内层 `run_to 900` 杀掉的 hung python **仍会写入标准结束行**(dur≈901s),转而触发 monitor 的 exit≠0 通道 ⇒ 与包装器自身 severe **重复出现**,违背 P2-1 的同一目的;
- 取 **>960** ⇒ systemd `TimeoutStartSec=960` 会先杀掉进程,**配置恒不触发 = 死配置**;
- 进行中超时触发点约 23:35,而 systemd 强杀在 23:36、monitor 轮次为 :00/:15/:30/:45 ⇒ **永远不可能落入窗口**。
- 结论:卡死防护已由**内层 `run_to 900` + 外层 `TimeoutStartSec=960` 双重硬门 + exit-failure 通道**三层覆盖,无需第四层。已把注释改为「此处只管漏跑」并附上上述 ⚠️ 推导。

### 9.5 用户追加增强:连续 2 天 FAIL 升 critical

**动机**:单次 severe 若正落在 6h 去重窗内(如 23:20 与次日 09:00 的相邻告警)可能被吞,持续缺口被静默。

**档位定义与首日/次日行为**(实现落 `notify.py` 的 R7① 拦截,匹配 R4 先例 `--dedup-key staticdata_backup_fail` 的写法,**包装器不改**):

| 场景 | 档位 | 出口 | 去重 key |
|---|---|---|---|
| **第 1 天 FAIL** | severe(**与历史行为一字不差**) | 走通用 `--severe` 路径(邮件 + 飞书 alert 群 + 镜像 `latest.md`) | `r2_consistency_fail`(6h) |
| **连续第 2 天及以后 FAIL** | **critical(升级)** | `send_tiered(TIER_CRITICAL)`,主题 `[告警] §22 三站一致性校验失败(连续 N 天, 升级 critical)` | `r2_consistency_fail_escalated`(独立窗,**不复用首日 6h 窗**)+ 同时占 `r2_consistency_fail` |
| 间隔中断(非连续日) | 重置为 1 天 → severe | 同第 1 天 | — |

- **连续天数状态**:`data/r2_consistency_fail_state.json`(`{last_fail_date, consecutive_days, first_fail_date}`,原子写 tmp+replace;写失败只 stderr 不抛)。同日重复不累加;间隔**恰好 1 个自然日**才 +1,否则重置为 1。
- **L46 无旁路**:`send_tiered(critical)` → `send(severe=True)` → 同样镜像 `data/alerts/latest.md`,飞书经 `_resolve_feishu_chat_key`(`if severe: return "alert"`)路由到 **alert 群**,不存在「升级档绕过镜像」的旁路出口。
- **升级日同步占首日 key**:保证同日 monitor 的同实例抑制(§9.2)在升级日**依然生效**,不会因升级档换 key 而多出第三封。

### 9.6 举一反三 + 同族扫描(§23.2 同类错误面 / §23.3 同模式)

| 面 | 清单与逐项结论 |
|---|---|
| **同类错误面(「preflight 缺失致过渡态假阳」)** | 全部 40 个 `trade-*.timer` 逐个核时点与当日 update-all 链关系:①**只有 r2-consistency 暴露在周日**(其余 checker 均 Mon..Fri 门控,周日不跑)②`check-data-gap` 22:35 有**交易日闸门**而周日非交易日 ⇒ 不跑 ⇒ 无风险 ③工作日 update-all 17:50 + 实测 112–139min → 约 19:42–20:09 结束,远早于 21:40/22:00/22:30/22:35 各采样点。**结论:同类错误面仅此一处,已修**。 |
| **同族脚本扫描(`check_data_gap_alerts` 等)** | 发现同一不实注释模板「此处只管漏跑+进行中超时」**也存在于 `check_data_gap`(TimeoutStartSec=600)及其它不在 `DUR_THRESHOLDS` 的 TASKS 条目**上 ⇒ 属**同一类陈述失真**(非本次功能 bug)。依 **§23.7 冻结契约**「不顺手改老功能、发现历史遗留上报」**本次只报告不擅改**,交主控/用户拍板是否统一。 |
| **残留观察项** | 工作日 update-all 若超 **约 230 分钟**(当前最大 139min,余量约 90min),其结束点将越过 21:40 采样点,届时 21:40 档 checker 会落入同样的半进程窗口。当前有 90min 余量,**登记为观察项**(非本次改动引入)。 |

### 9.7 收口自验逐项

| 项 | 结果 |
|---|---|
| 分支延续(§0.2) | `git branch --show-current` = `feat/160-consistency-gate-20261005` ✓(未新开分支) |
| 专项测试 | `pytest -q scripts/tests/test_160_r2_consistency_followup_20261005.py` → **23 passed** |
| 全量回归 | `pytest -q scripts/tests/` → **188 passed, 1 skipped** |
| 语法 | `py_compile`(notify/alert_denoise_rules/test)×3 OK;`bash -n`(check_r2_consistency / schedule_monitor)OK |
| 判据两态 | 云上只读:journald `is-active --quiet` rc=**0** / update-all rc=**3**(见 §9.5);本地 stub 两态 + pgrep 回退均覆盖 |
| 「真 FAIL 仍报 1 封、不报 2 封」两态实测 | `test_two_channels_one_alert_normal_state`(包装器已投递 → 汇总静默=1 封)、`test_two_channels_one_alert_wrapper_send_failed`(包装器投递失败 → 汇总照发=1 封);两态均**恰好 1 封** |
| 同实例抑制不打折 | day1 落回 severe(1 封)/ day2 升 critical(1 封)/ 升级窗内 suppress(0 封)三态均实测 |
| §14 不触发定时任务 | 本次纯代码+文档改动,**未启动/停止/daemon-reload 任何云上 unit**;云上故障排查仅只读 |
| §25 | 未删任何文件、未动任何云上配置 ⇒ 无备份义务(§9.1 选型 (c) 即为规避动 unit) |
| §23.11 无静默 | 全程无冲突/覆盖/倒退;`check_r2_consistency.sh` 等文件为单 agent 独占改 |

### 9.8 收口复现命令

```
# 专项(23 项)
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/test_160_r2_consistency_followup_20261005.py
# 全量回归
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/
# 语法
python -m py_compile scripts/notify.py scripts/alert_denoise_rules.py && bash -n scripts/check_r2_consistency.sh && bash -n scripts/schedule_monitor.sh
# preflight 判据两态(本地, 不碰云上)
R2_CONSISTENCY_PREFLIGHT_STUB=active   bash scripts/check_r2_consistency.sh; echo rc=$?   # 期望 0 + 日志 [preflight-skip]
R2_CONSISTENCY_PREFLIGHT_STUB=inactive bash scripts/check_r2_consistency.sh; echo rc=$?   # 期望走真实比对
# 判据语义(云上只读)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'systemctl is-active --quiet systemd-journald.service; echo $?; systemctl is-active --quiet trade-update-all.service; echo $?'
```
- **配套 commit**:见本分支 `feat/160-consistency-gate-20261005` 同名提交。