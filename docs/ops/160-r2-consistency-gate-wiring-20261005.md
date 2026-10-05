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
- **配套 commit**:见本分支 `feat/160-consistency-gate-20261005` 同名提交。