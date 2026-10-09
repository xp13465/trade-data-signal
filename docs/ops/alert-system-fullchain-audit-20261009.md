# 告警系统「全链审计 + 系统性收敛方案」(2026-10-09)

- 角色: researcher agent(全程只读); 时点: 2026-10-09 22:00 ~ 22:5x(CST)
- 安全声明: 全程只读——未改任何代码/数据(本报告文件除外)、未启停任何 unit、未跑任何业务脚本主体、无 R2 写、无任何真实通知外发(邮件/飞书全零)、探针 static-only(§18 L50)
- 用户口径(原话): 「今天怎么又这么多运维群的 cloud 的告警…我的预期是一天只能接受 0~3 个告警。现在都是两位数，我都不知道到底是真 bug 还是噪音」/「今天告警还是很多。所以我对告警一直以来的修复是不满意的」
- 任务性质: 不是再点状修一个根因, 而是把「告警从哪来 → 怎么变成用户手机上那条消息」整条链摊开, 量化每环放大倍数, 给系统性重构方案

## 0. 结论速览(第一屏)

**今日实测(10-09 截至 22:00)**: alert 群(运维群)实际外发 **20 条 severe**(云上运行树 `latest.md` 19 条 + 信号树 1 条) + 恢复 1 条(另 1 条被 6h 窗抑制) ≈ **21 条消息**; 归并 = **8 个独立事实** ⇒ 放大 ≈ **2.6×**(而用户预期 0~3 条/天)。

**20 条逐条分解**(见 §4 表): 真故障 5 / 机制噪音(例行重复+集合抖动) 9 / 假阳性(含嫌疑) 4 / 重复次生 2。单类最大 = **云上 unit 巡检 9 条(45%)**。

**三个结构性病灶**:
1. **没有度量层**——「一天几条」无任何可查数字: latest.md 是 cap-50 滚动流水(不计数)、dedup json 只记 per-key 最后时间、warning/info/恢复不留台账 ⇒ 「0~3 条」无法验收, 用户「不满意」也无客观判据 (§5)。
2. **#240 新判据「集合有变即报」把 failed-unit 集合的每次抖动实时变成一条消息**(含「变好」方向: failed 被清零=集合缩小也发)。今日 12:52 部署后 7 连发(13:00/16:30/16:45/17:00/18:15/18:30/20:15), 其中 **4 条是纯「集合缩小(=恢复进展)」**触发的 (见 §3-F3, §2-D3)。
3. **双树分裂 + 多键同事实**: notify.py 的 REPO 解析不接 env(`REPO = Path(__file__).absolute().parent.parent`, notify.py:86), 云上运行树 `~/code/trade-data` 与信号树 `~/code/trade-data-signal` **各有独立的 notify_dedup.json / alerts/latest.md**(实测 dedup 键 50 vs 52 个, 其中 24 键只在单树有窗、latest.md 各含不同条目)⇒ 跨树去重互相不可见; 同一事实(09:31 伪跳空)被 py 版+sh 版**两个不同 dedup key** 各发一遍 (见 §2-D1/D2)。

**方案**: 5 层收敛(度量/收敛/判别/逐源/验收), 预期把稳态压到 ≤3 条/天且保留真故障判别维度(§6)。三个最大杠杆见 §6.6。

## 1. 全链路图 + 每环放大/收敛量化

```
[产生源]                         [分级]                    [聚合 schedule_monitor 15min]        [去重+去噪]                          [送达]                 [留痕]                    [用户]
82 个文件引用 notify.py           critical → 直发            exit!=0 / 关键词扫描 / 耗时双通道      notify.py per-key dedup window       email(QQ 邮箱)          latest.md severe 流水 cap50   运维群(alert 群)
144 处 --severe 调用点            warning → 30min buffer     "[告警] N项计划任务异常" 合并 1 封     alert_state.json per-key + 各产品 state feishu alert 群          notify_dedup.json(per-key)    report 群(功能输出非告警)
dedup 键: 运行树 50 + 信号树 52   info → info_log 只落盘      R5 拥堵同根因日汇总(23:25)            任务级包装器抑制/6h恢复窗/降级计数      feishu report 群        info_log.jsonl / warning_buffer 邮箱
                                                                                               telegram(未配置, 永远跳过)        (warning/恢复 发送后无台账)
```

**表 1: 每环今日实测 + 放大/收敛量化**

| 环节 | 机制锚点 | 今日实测 | 放大/收敛 |
|---|---|---|---|
| 产生源 | 82 文件引用 notify.py / 144 处 `--severe`(grep 实测); dedup 键 = 运行树 50 + 信号树 52(云上 notify_dedup.json 实测) | 8 个独立事实 | 基准 |
| 分级 | 三级: critical 直发 / warning 入 30min buffer(`WARNING_BATCH_WINDOW=1800`, notify.py:142) / info 只落盘 | warning buffer **自 10-05 15:15 起零写入**(云上 `warning_buffer.jsonl` 0 字节, mtime 10-05); info 70 条(59 条=`staticdata 同步变更量超阈值跳过 commit`) | **收敛设施闲置**: warning 聚合链路在跑但主流量直发 severe, 没有策略规定「什么级别配什么 tier」 |
| 聚合 | schedule_monitor.sh 每 15min: 关键词扫描 + exit!=0 分支 + 耗时双通道 + 尾部 `--flush-warnings`(L914/L2868) | 4 条「[告警] N项计划任务异常」(01:45/09:45/10:45/22:00) + 2 条恢复(1 条被 6h 窗抑制) | 单轮多告警合并 1 封(收敛); 但**同一事实被「包装层自身 + 聚合层」两级各报**(§2-D2) |
| 去重 | notify.py `check_dedup/update_dedup`(L1247-1319, flock 串行; 发送成功才更新) + alert_state.json + 产品自身 state | ≥2 次重发被 suppress(01:12 R2 二次通知 `age=85s < window=21600s`; 11:00 后第 2 条恢复被 `age=11683s<6h` 吞) | 同 key/同树收敛; **跨 key/跨树不收敛** |
| 送达 | email + feishu(alert 群 oc_7d8d… / report 群 oc_edd9… 按 tier 路由); telegram 未配置恒跳过 | 今日 20 条每封均 `email=OK feishu=OK` | 无放大(双通道同内容, 设计使然) |
| 留痕 | severe → `_mirror_severe` latest.md 追加 cap50(notify.py:999-1003); warning→buffer 发完清理; info→info_log; **恢复/汇总无持久台账** | latest.md 今日 19 条; 恢复被抑制后**连痕迹都没有** | **度量缺口**(§5) |
| 用户 | 运维群 + 邮箱(用户「cloud 的告警」= `[cloud]` 前缀 = TRADE_HOST_TAG, notify.py `_host_tag_subject` L752-772) | **21 条消息 / 8 事实** | **放大 ≈2.6×** |

**表 2: 现有收敛机制清单(审计基线; 本方案建立在它们之上, 不推翻不重复)**
- R1~R5、R7(#123 降噪, 10-01): overview lag 连续≥2轮 / 超时-耗时双通道合并 / nextday_plan 包装层已发时聚合层不复述 / staticdata 分级 / **R5 R2 拥堵同根因日汇总(首条直发, 第2条起聚合, 23:25 发 1 条)** / r2_consistency 连续2日升 critical+同实例去重。规则模块 `scripts/alert_denoise_rules.py`(单一事实源)
- #196①②③(10-05): failed-unit 巡检 / 巡检者自身存活(WATCHMAN_UNITS) / 连续 3 天异常升 critical
- **#240(10-09 12:52 上线)**: ①multiprocessing Traceback 过滤 ②failed-units「每日一次/有变即报」 ③dur 碰线连续 2 轮 ④公募 NULL 分档
- #241: rc→`notify_sent()` 判据统一(3 处已修; Pattern B 3 处结构性卡住待决策)
- 三级分级(08-24) / 6h 恢复窗 + `_recurrence_suppressed` 折返抑制 / `alert_ack.py` 人工确认 24h / dur buffer 连续 2 轮 / marker_buffer degrade 连续≥3 轮 / 任务级包装器抑制(#123R3 nextday_plan、#160R7 r2_consistency、#196② cloud_unit_patrol)

## 2. 重复报根因清单(同一事实被报 2+ 次的路径)

### D1 双树分裂(结构性根因; 去重互相不可见)
- **机制**: `notify.py:86` `REPO = Path(__file__).absolute().parent.parent`(不 resolve、不接 env)⇒ 谁用什么路径调它, 状态就落谁的树: 调用方用 `Path(__file__).resolve()`(如 `nextday_gap_check.py:_severe_alert`)→ 状态落**信号树**; 调用方用 `$REPO/scripts/notify.py` 或 cwd=运行树的相对路径(如 `nextday_gap_check.sh:62-69`)→ 状态落**运行树**。
- **实测证据**(云上只读):
  - 运行树 `~/code/trade-data/data/notify_dedup.json` 50 个键(含 `nextday_gap_check_fail`/`failed_units_patrol`/`cloud_unit_patrol_drift`/`r2_*`); 信号树 `~/code/trade-data-signal/data/notify_dedup.json` 52 个键(含 `nextday_gap_check_gen_fail`/`daily_brief_notify_*`/`nextday_plan_*`/`verify_r2_*`)。两树键集**实测交集 39 键 / 运行树独有 11 键(`cloud_unit_patrol_drift`/`failed_units_patrol`/`r2_upload_trigger_fail`/`deploy_check_data_integrity_fail`/…) / 信号树独有 13 键(`nextday_gap_check_gen_fail`/`daily_brief_notify_*`/`nextday_plan_*`/`verify_r2_mass_mismatch`/…) ⇒ 24 个键(37%)的去重窗当前只存在于单树, 从另一树调用该键即**绕过窗口重新起计**; 39 个公共键也各树独立记窗(发送后另一树不可见)。
  - 两树 `data/alerts/latest.md` 各自独立 cap50: 运行树 = 10-04~10-09 条目; 信号树 = 09-23~09-30 + 今日 1 条。
- **后果**: ① 同一事实两侧各报一遍(今日 09:31 伪跳空: sh 版 `nextday_gap_check_fail` 落运行树 + py 版 `nextday_gap_check_gen_fail` 落信号树, latest.md 两条各一); ② 任一树的「包装器已发」抑制判据(`r7_r2_consistency_wrapper_alerted`/`wrapper_channel_alerted` 读的是**自己树**的 notify_dedup.json)会被另一树的写入绕过; ③ 用户视角「告警历史」散在两处, 排障必须两棵树都翻(本次审计实际如此执行才拼出 20 条全貌)。
- **行级证据**: `scripts/nextday_gap_check.sh:62-69` 注释原文「本条为包装层兜底重复告警(不同 dedup key 不互吞)」= 设计上承认两键都发。

### D2 包装层 + 聚合层两级复读
- **机制**: 各产品脚本(wrapper)自己先 notify 一次(自管 dedup key); schedule_monitor 再对 wrapper 日志做关键词扫描(SEVERE 行)+exit!=0 汇总, 用 `[告警] N项计划任务异常` 主题**再报一次**。虽有 R3/R7②/196② 的任务级抑制(只覆盖 nextday_plan/r2_consistency/cloud_unit_patrol 三个专案), 其余源无此待遇。
- **今日证据**: 09:31 伪跳空(2 个自身通道)+ 09:45「2项计划任务异常」(聚合层复读同一事实)= 1 事实 3 条消息; 01:45/10:45/22:00 的 fetch_news skip 为聚合层单通道(自身通道无独立推送, 只打日志 SEVERE 行供扫描)。

### D3 #240 集合签名「有变即报」放大集合抖动(**今日最大单一放大器**)
- **机制**: `alert_denoise_rules.py:111-127` `failed_units_daily_judge`: `if state.signature != signature: return True,"changed"` —— **对称判定, 不区分方向**。集合新增 failed unit(真信号)与集合缩小(unit 被清零/恢复)一视同仁「立即报」。
- **今日证据**(post-12:52 实测): 12:52 部署后 7 连发; 消息正文集合逐条缩小: 16:45=7 个 unit → 17:00=6(去 public-fund-daily) → 18:15=5(去 fapi-daily) → 18:30=4(去 lhb-backfill) → 20:15=2(去 etf-national-team/futures-backfill)。**17:00/18:15/18:30/20:15 四条均为纯「集合缩小」触发**; 集合本身在 89 轮巡检中今日变更 9 次(00:00/08:15/09:30/16:15/16:30/16:45/18:00/18:15/20:00, 按轮扫描 failed-units 列表签名实测), 每次变更 → 一条消息。
- **对照**: 旧 6h 窗机制今日产出 04:30/10:45 两条(同为陈旧 failed 状态重复), 即今日 unit 巡检 9 条 = 旧机制 3 条(04:30/10:45/13:00 首报) + 新判据 6-7 条抖动。

### D4 同族多键(设计使然, 列出供收敛方案取舍)
- R2 上传族: `r2_upload_trigger_fail`(触发碰撞) / `deploy_r2_upload_fail`(etf-hist 停滞) / `intraday_upload_index_r2_fail`+`r2_upload_*`(index 停滞) / fetch_news `r2_skip` 链 —— 每通道一条, 无「当日 R2 族总量」视图(除 R5 只认 R2 拥堵关键词类)。
- staticdata 族: 8+ 个键(`staticdata_backup_*`/`staticdata_sync_*` 各 fail/gate/reject/guard 分支)。
- 今日 R2 族 = 3 条(00:22/01:12/17:35), 均为不同子事实, 但三封邮件形态雷同, 用户感受=「又是 R2 告警」。

### D5 恢复被 6h 窗抑制 → 告警没有闭环信号
- **机制**: 恢复消息统一 `--dedup-key schedule_monitor_recovery --dedup-window 21600`(schedule_monitor.sh L2821-2822); 且 `r2_*` 恢复永远不发(L2787)。
- **今日证据**: 11:00 恢复发出; 第 2 条恢复被 suppress(`age=11683s < window=21600s`); 22:00 fetch_news SEVERE 后至审计时点无恢复消息 ⇒ **用户看到「告警」但看不到「已恢复」**, 同一 key 的告警/恢复经常配对不上, 判读负担加重。

### D6 跨群双面(同一事件两个群)
- 例: R2 锁跳过提示走 report 群(00:49「[提示] R2上传异步锁跳过」), 其升级版 SEVERE 走 alert 群; 盘中买卖点信号(功能输出)也带 `[cloud]` 前缀进 report 群并同时进邮箱 —— 用户感知的「cloud 消息」被功能输出拉上两位数(report 群今日 19 条 = 18 条盘中信号 + 1 条提示, 均非故障告警)。

## 3. 假阳性清单

### F1 #181①d 幻影 +1(轮标识取 mtime 竞态)——今日 3 条均已确认或高度疑似命中
- **机制**(已由 181 生产样本复核报告定位, 全文 `docs/ops/181-denoise-prod-sample-20261008.md` §5): r2-skip 计数的「轮标识」= `gen_schedule_stats.py` 的 `EXTRA_MARKER_SCANS[fetch_news].last_run` = **日志文件 mtime(分钟精度)**; fetch_news 每轮 `:01/:45:00` 先写「轮次开始」(flush, 立即刷新 mtime), 数十秒后才写「已写」。monitor 的 `:45` tick 与 fetch_news `:45:00` 轮同秒起跑 ⇒ 读到「**窗口=上一轮(含 SKIPPED_LOCKED) + mtime=新轮起跑**」组合 ⇒ `fresh✓ / same_round✗` ⇒ **幻影 +1**。现网实际阈值退化为「2 个连续真 skip 轮」(设计意图 3 轮)。
- **今日命中**: 01:45 与 10:45 两封 SEVERE 即 181 复核报告判定「疑为假阳性」(可考独立真 skip 轮各只有 2 个); 22:00 第 3 封为同族(链含 `:01` 轮, 计数 1/3→dup(last_round=21:02)→2/3→SEVERE, 而 fetch_news 真 skip 轮 21:01/21:45 各一次, 22:01 轮 skip 发生在告警**之后**)——高度疑似同一幻影机制。
- **在飞修复**: 后台 agent「#181 假阳性竞态修复」正在实施(本审计时点仍在跑)。本报告不改码, 仅登记为假阳性来源事实。

### F2 systemd-run 瞬时 unit 名冲突误报(00:22)
- **机制/证据**: `deploy_20261009_0013.log` L1474「Failed to start transient service unit: Unit r2-upload-002208.service already exists.」+ L1475「Running as unit: r2-upload-002208.service」同序列混写; 实际 002208 实例正常跑完(01:13:32 退出码=0)。同序列输出出现在 3 个日志文件均无 suppress 行 ⇒ 触发碰撞被当失败报出, 上传本体未受影响。
- 性质: 误报(触发层竞态; 同名已在跑应视为「已在执行」而非失败)。

### F3 #240 集合「缩小方向」也报(改进即告警; 与 §2-D3 同源)
- 今日 4 条(17:00/18:15/18:30/20:15)在语义上是「failed 状态被清除=恢复进展」的通知, 不是故障。判定依据见 §2-D3 逐条集合对比。**保留真故障判别维度的前提下可收敛**: 「新增 failed unit」才是需要人动作的信号(立即发); 「消失」可并入当日摘要或静默(`#196③` 连续 3 天不清仍升 critical 兜底持续未清的真故障)。

### F4 fetch_news r2-skip「SEVERE」语义错配(自愈重试被当严重故障)
- **证据**: 告警正文自身写着「缺口由下一轮 fetch_news 30min 后自动重试兜底」(fetch_news_launchd.log L3372 等原文); 且每轮跳过都由下一轮自愈(今日 21:01→21:45→22:01 连续 skip, 但此前 19:45 skip 后 20:01 轮恢复上传、链被清零)。
- 性质: 设计内自愈 + 紧升级阈值的组合 ⇒ 每 30min 的瞬时锁忙被 SEVERE 化。**是真实状态(锁确实忙)但不是需人动作的故障** = 典型案例「真状态/假告警」。方向: 降 warning tier(入 30min buffer, 若期间自愈则永远不打扰)或提高连续轮阈值/加「已自愈则不报」。

### F5 历史已修项(列出防重犯)
- multiprocessing Traceback 噪声(#240① 已过滤); telegram 占位符未配置被标 FAIL(09-11 已改为「未配置=跳过不显示」); `[r2-skip-stale]` 保链分支仍 0 生产样本(181 报告如实标注, 非假阳性但在飞观察点)。

## 4. 噪声占比(今日 20 条真实样本逐条分类)

| # | 时间 | 主题 | 同一事实 | 定性 |
|---|------|------|---------|------|
| 1 | 00:22 | R2上传异步触发失败 | R2 触发碰撞 | 假阳性(F2) |
| 2 | 01:12 | R2上传失败(etf-hist 停滞被杀) | R2 通道真断 | 真故障 |
| 3 | 01:45 | 1项计划任务异常(fetch_news skip) | 锁竞争次生+幻影嫌疑 | 假阳嫌疑(F1) |
| 4 | 04:30 | unit 巡检 | 陈旧 failed(旧 6h 机制) | 例行重复 |
| 5 | 08:27 | unit 快照漂移 | 3 字段配置差异 | 真(低危, 需人决策) |
| 6 | 09:31:43 | 伪跳空校验失败(sh, 运行树) | 东财接口被拒 | 真故障(外部接口) |
| 7 | 09:31:37 | 伪跳空校验未完成(py, 信号树) | 同上 | 重复(D1 双树) |
| 8 | 09:45 | 2项计划任务异常 | 同上+监控器自身 | 次生复读(D2) |
| 9 | 10:45 | unit 巡检 | 同 #4 | 例行重复 |
| 10 | 10:45 | 1项计划任务异常(fetch_news skip 第 2 段) | 锁竞争+幻影嫌疑 | 假阳嫌疑(F1) |
| 11 | 13:00 | unit 巡检 | #240 新判据首跑 | 例行(新机制一次性) |
| 12 | 16:30 | unit 巡检 | 集合抖动 | 机制噪音(D3) |
| 13 | 16:42 | deploy 数据产物校验失败 | fund_nav DB 领先产物 9 天(3 只代码) | 真故障(数据产物滞后, 拦部署) |
| 14 | 16:45 | unit 巡检 | 集合抖动 | 机制噪音(D3) |
| 15 | 17:00 | unit 巡检 | 集合缩小 | 机制噪音(D3/F3) |
| 16 | 17:35 | R2上传失败(upload-index 停滞被杀) | R2 通道真断 | 真故障 |
| 17 | 18:15 | unit 巡检 | 集合缩小 | 机制噪音(D3/F3) |
| 18 | 18:30 | unit 巡检 | 集合缩小 | 机制噪音(D3/F3) |
| 19 | 20:15 | unit 巡检 | 集合缩小 | 机制噪音(D3/F3) |
| 20 | 22:00 | 1项计划任务异常(fetch_news skip 第 3 段) | 锁竞争+幻影嫌疑 | 假阳嫌疑(F1) |

**统计**: 真故障 5 条(25%; 4 个独立事实) / 机制噪音 9 条(45%; 1 个事实类+新机制) / 假阳性(含嫌疑) 4 条(20%) / 重复次生 2 条(10%)。
**仅需人动作的独立事实 ≈ 4-5 个**(etf-hist 断、东财被拒、index 断、fund_nav 产物滞后、漂移决策), 其余 15 条本质是「同一批陈旧状态的机制化重播 + 自愈瞬态 + 已知竞态」。
**口径说明**: 未计入 report 群的 18 条盘中信号(功能输出)与 1 条锁跳过提示——但它们是用户「cloud 消息两位数」观感的另一半来源(同一飞书 App 内)。

## 5. 度量缺口(「一天几条」目前无任何可查数字)

**实测的现存「疑似度量源」及其缺口**(逐一核过, 云上 data/ 全量列表实读):

| 疑似源 | 实际内容 | 缺口 |
|---|---|---|
| `data/alerts/latest.md` | severe 流水, **追加式 cap 50 条**(`_mirror_severe`) | 滚动截断, 不计数; 非 severe(恢复/汇总/warning)不入 |
| `data/notify_dedup.json` | per-key 最后告警时间+窗口 | 无 per-day 计数; 键被覆盖写(如 `failed_units_patrol` 今日 04:30/10:45 时间戳被 13:00 覆盖) |
| `data/alert_state.json` | per-key status/last_alerted(monitor 维度) | 同上, per-key 无日计数 |
| `warning_buffer.jsonl` / `warning_dedup_state.json` | 发送后清理/状态 | 发完即清, **无 sent 台账**(00 字节自 10-05) |
| `info_log.jsonl` | info 级只落盘 | 70 条累计, 不推不计数 |
| 恢复消息 | 无状态文件 | 6h 抑制后**连痕迹也没有**(今日第 2 条恢复只能从日志推断) |
| `/tmp/schedule-monitor-heartbeat.txt` | `alerts=N` per 轮 | 单轮瞬时值, 每 15min 覆盖, 无日累计 |
| monitor/各通道日志 | 「检测到 N 个告警」「已发送」行 | **唯一可重建源, 但需人工解析**(本审计手工重建: 09-21~10-09 monitor 自身通道 1~12 条/天 + 恢复 1~7 条/天) |

**结论**: 「一天几条告警」在当前系统**没有任何单一权威数字**, 必须聚合 ≥5 个来源(两树 latest.md 各自 cap50 + monitor 日志 + 各通道日志 + dedup 状态)才能拼出近似值——这正是「0~3 条/天」无法验收、历次降噪修复无法判「满意/不满意」的根因。度量层是收敛方案的第一优先级(§6-L1)。

## 6. 系统性收敛方案(5 层; 每层改动点+预期收益+风险+真故障判别维度保留)

### L1 度量层(第一优先级:让「一天几条」变成可查数字)
- **改动点 1**: 单点台账 `data/alerts/alert_ledger.jsonl` —— 写点 = notify.py 唯一外发出口(`send()` 汇总处附近, 通用汇总 L2359/2368-2371), 每封实际外发追加一行 `{ts, tree(REPO), tier, key(dedup_key 或 subject 哈希), subject, channels{email,feishu}, source(sys.argv[0]/NOTIFY_SOURCE)}`。**notify.py = 冻结面(§23.7)** ⇒ 该改动是「纯新增追加写、零现有行为变更」, 需用户拍板; 且已有先例: notify.py 内 3 处已用 `Path(os.environ.get("REPO") or REPO)`(L2227/2267/2317), 说明「加法改动」在冻结面上有被判过的先例。
  - **备选 B(不碰 notify.py)**: schedule_monitor 每轮扫描两树 latest.md 增量 + 解析 flush 输出生成 ledger —— 弱化版(会漏「非 monitor 链路且非 severe」的直发), 保底可用但不推荐。
- **改动点 2**: 日计数产物 `data/alerts/alert_daily.json` `{date, by_tier, by_source, by_key, total, merged_in_digest}` —— 由 ledger 幂等重算(monitor 每轮末尾或 23:30 收尾轮), 无状态漂移风险。
- **改动点 3**: 查询面 `scripts/alert_meter.py --today/--week/--top`(或并入 alert_ack.py 家族), 输出「今日 X 条(severe Y, 摘要并入 Z) + top talkers + 与前 7 日均值对比」。
- **预期收益**: 「0~3 条/天」从口号变验收数字; 本次审计的 20 条/8 事实这类报表变成一条命令; 为 L2 预算层提供执行依据。
- **风险/兜底**: 台账写入 best-effort 不阻塞(同 `_mirror_severe` 模式); 台账自身绝不告警(防元噪声)。

### L2 收敛层(结构上限:预算+摘要, 不是靠静默)
- **改动点 1**: 泛化 R5 模式(`alert_denoise_rules.py:r5_congestion_process` 是现成先例)→ 新增 `alert_budget_process()` 纯函数: 按**类别**(unit 巡检 / R2 族 / 自愈类 / 其余)设日预算; 超预算的同类别告警不再即时直发, 现象并入当日摘要(复用 R5 的 `summary_hm` 收尾轮机制, 或新增 12:30/20:30 摘要轮)。
- **改动点 2**: 恢复闭环。恢复消息 = 「关闭告警」的信号, 当前 6h 窗会把它吞掉(今日第 2 条恢复被 suppress)⇒ 改为: key 当日有告警发出时, 其恢复不受窗限制(用同 key `last_alerted` 关联), 或恢复并入日摘要但**必须出现**。
- **改动点 3**: 分诊政策表单一事实源 —— 「什么级别配什么 tier + 什么类别进预算」写进 `alert_denoise_rules.py` 常量表; 现状 144 处 `--severe` 散落无政策(且 warning 聚合链 10-05 后零流量), 是「聚合设施闲置」的根因。
- **改动点 4**(可选, 用户拍板): 非 critical 级 23:00-07:00 入次日晨间摘要。
- **先例与判别维度保留**: 与 R5 同原则 —— **首报必达**(每 key 当日首报永远直发) / critical 永不入预算 / 新 key 永远直发。静默的只允许是「同一事实的当日重复」。
- **风险**: 过度收敛吞新故障 ⇒ 对策: 任何被预算合并的条目**必须出现在摘要里且注明「被合并 N 条」**; 每周 review top-talkers 抽查被吞条目; 各层独立 env 开关可回滚。

### L3 判别层(把每一类噪音在「该不该发」的判定上修对)
- **3a failed-unit 方向感知判定(#240② 精修)**: `failed_units_daily_judge` 拆 `changed` 为 `added`(新集合 − 旧集合非空 → 立即报) / `shrunk`(只有移除 → 入当日摘要或静默; 状态文件加 prev_signature)。判别维度保留: 新增 failed unit 立即报; 持续未清由 #196③ 连续 3 天升 critical 兜底; 跨日首报照旧。
- **3b #181 幻影修复(在飞, 勿重复动)**: 轮标识改用「轮次开始」时间戳(`gen_schedule_stats.py` 已有 `round_begin_re`)或 (窗口, mtime) 一致性校验 + 边界竞态 fixture。
- **3c fetch_news r2-skip 语义**: 自愈瞬态(设计内 30min 重试兜底)不该 SEVERE 化 ⇒ 降 `--tier warning`(入 30min buffer; 期间自愈则永不打扰) 或改判据为「连续 N 轮且最后一轮仍 skip 且未出现成功轮」。判别维度保留: 锁持续忙(无自愈轮)+ 缺口语义(`收盘版/每日版未上 R2`)在持续时仍升级。
- **3d #241 Pattern B 残留(与 #241 合并为一个待拍板项, 勿重开)**: `check_monitor_heartbeat.py` / `nextday_gap_check.py` / `nextday_plan_generator.py` 的 rc 判据卡在「notify.py dedup 抑制分支不打任何输出」——要么给冻结面加一行输出, 要么弱化 fail-safe, 需用户拍板。
- **3e 双树收口**: 推广既有 env 先例(`Path(os.environ.get("REPO") or REPO)`)到 `DEDUP_FILE/ALERTS_DIR` 解析, 使状态单树化; 或轻量版: 把「包装器已发」判据改为读两树并集。判别维度保留: dedup 语义不变, 只是从「两套」变「一套」。
- **预期收益**: 今日 4 条假阳嫌疑(§3-F1/F2/F4)+ 2 条双树重复(§2-D1)+ 1 条次生(§2-D2)全灭。
- **风险**: 3e 切换瞬间「窗口重启」= 短期重复增多一次 ⇒ 低时段切换 + 切换日观察; 3a 需防「added 抖动」(unit 反复 fail→clear→fail)⇒ 加最小抖动抑制(同集合 24h 内二次 added 并入摘要)。

### L4 逐源降噪层(今日贡献最大的源逐个给处置)
| 源 | 今日条数 | 病灶 | 处置(层) | 预期 | 判别维度保留 |
|---|---|---|---|---|---|
| unit 巡检 | 9 | 集合抖动+缩小方向也报 | L3a | 1-2/天 | 新增立即报; 3 天不清升 critical |
| fetch_news r2-skip | 3 | 自愈瞬态 SEVERE + 幻影阈值稀释 | L3b+L3c | 0-1/天 | 锁持续忙仍升级 |
| 伪跳空(东财) | 2 | 双树双键各发 | L3e | 1/事件 | 接口失败本身照发(真故障) |
| R2 通道族 | 3 | 触发碰撞误报 + 2 真断 | 00:22 修触发语义(同名已在跑=成功); 其余保留 | 2-3/天(真) | 通道真断必须报 |
| deploy 数据产物校验 | 1 | fund_nav DB 领先产物 9 天(长假后首日族) | 与 #235 族口径合并评估(产物重出流程) | 1/事件 | 校验本身保留(拦部署事故) |
| 漂移 | 1 | 真低危配置差异 | 保留(可加 24h 窗) | 1/事件 | 差异字段全列 |
| report 群功能输出 | 18 | 非告警(买卖点信号) | 维持标签分离(用户感知已由 [盘中实时] 标签区分) | — | — |

### L5 预算验收层(把「满意」定义成可验证的数字)
- **目标**: 稳态 ≤3 条/天(告警群即时消息), 硬上限 severe 直发 ≤3 + 摘要 ≤2; 用户 veto/调整口径后生效。
- **度量**: L1 ledger 的 per-day total; 验收判据 = 连续 7 天 P50 ≤3 且 P90 ≤5。
- **验收方法(每项改动)**: 用同一真实样本(今日 20 条)给「改造前 → 改造后」判定对照表(沿用 #240 惯例), 不臆断。
- **复查安排**: 每周 review top-talkers + 抽查「被预算吞掉的条目」是否都出现在摘要(宁少不吞: 任何被吞条目必须可在摘要中找回, 且摘要注明被合并条数)。
- **回滚**: 各层独立开关(常量/env), 单层失效可关; 不影响现有 R1-R7/#196/#240/#241 机制。

### 6.6 三个最大收敛杠杆(按今日消息数排序)
1. **unit 巡检集合抖动治理(L3a)**: 今日 9/20 条(45%), 预期降到 1-2; 改动最小(纯函数方向判定 + 状态多存一个 prev 集合), 判别维度保留(新增立刻报, #196③ 兜底)。
2. **度量层(L1: 台账+日计数+查询)**: 本身不减今日条数, 但让「0~3/天」从口号变验收数字——是用户「一直不满意的修复」以后能判满意的唯一路径, 也是 L2 预算的执行依据。
3. **判别修正批量(L3b/c/e)**: #181 幻影(已在飞)+ fetch_news 降 tier + 双树收口 —— 覆盖今日 3 条假阳嫌疑 + 2 条双树重复 + 1 条次生; 其中 #181 修复完成后只需回看样本验收。

## 7. 与在飞工作 #240 / #241 / #181 的关系

- **#240(10-09 12:52 已上线, 4 条)**: 本审计确认其治好的部分——旧 6h 窗「同一批 stale failed unit 一天 3 封」已不再 6h 重播(今日 04:30/10:45 为旧机制末班, 13:00 起为新判据); 但其 ②「集合有变即报」的**对称判定成为今日新的最大放大器**(§2-D3): 定性 =「机制生效但方向口径需精修」, 不是回滚。建议落点 = §6-L3a, **并入 #240 族作者上下文改**(防两处实现漂移)。
- **#241(rc→notify_sent, 已合)**: 本审计核对覆盖面: Pattern A 3 处已修(防静默丢告警, 不减当日噪音); **Pattern B 3 处结构性卡住**(`check_monitor_heartbeat.py` / `nextday_gap_check.py` / `nextday_plan_generator.py`)——卡点是 notify.py 通用路径 dedup 抑制分支不打任何输出(`if args.dedup_key and not check_dedup... return 0` 静默), 换判据必须动冻结面输出 ⇒ 与 §6-L3d 合并为一个待用户拍板项, 不要单独重开。
- **#181 假阳性竞态修复(在飞后台 agent, 本审计时点仍在跑)**: 直接覆盖今日 3 条假阳嫌疑的机制(§3-F1); 本审计不重复其工作, 只登记验收点: 修后回看 fetch_news r2-skip 链, 确认「2 真轮不再出 3/3」。
- **#236 F2 预警数据独立上传 R2 / #237 R2 覆盖备份闸门**: 与本方案无冲突(不同链路); 注意 #236 的 F2 跳过场景会产生新的告警文本, 设计时套用 L2 分诊政策表。
- **不重叠声明**: 本方案无一条与上述在飞工作重复——全部改动点集中在「度量层(新)+ 预算层(新)+ 既有判据精修(方向/幻影/tier/双树)」三类。

## 8. 复现命令(全部只读)

本机(代码锚点):
```bash
grep -n "WARNING_BATCH_WINDOW" scripts/notify.py                 # L142 = 1800
grep -n "_mirror_severe(" scripts/notify.py                      # L999-1003 仅 severe 路径镜像 latest.md
sed -n '111,127p' scripts/alert_denoise_rules.py                 # failed_units_daily_judge 对称 changed
sed -n '513,568p' scripts/alert_denoise_rules.py                 # R5 拥堵日汇总(收敛先例)
sed -n '2740,2830p' scripts/schedule_monitor.sh                  # 聚合层发送块 + 恢复 6h 窗(L2821)
sed -n '62,69p' scripts/nextday_gap_check.sh                     # 包装层「不同 dedup key 不互吞」原文
```

云上(只读固定形态 `ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'timeout N <cmd>'`; 复杂 python 用 stdin 管道):
```bash
# 两树 severe 日计数与逐条(将 <path> 换两树 latest.md 路径)
python3 -c "import re,pathlib;t=pathlib.Path('<path>').read_text(errors='replace');print(len([e for e in re.findall(r'^## \[severe\] (2026-\d\d-\d\d)',t,re.M) if e=='2026-10-09']))"
ls -la /home/ubuntu/code/trade-data/data/alerts/            # warning_buffer.jsonl=0B mtime 10-05; info_log.jsonl 70 条
python3 -c "import json;print(len(json.load(open('/home/ubuntu/code/trade-data/data/notify_dedup.json'))))"          # 50
python3 -c "import json;print(len(json.load(open('/home/ubuntu/code/trade-data-signal/data/notify_dedup.json'))))"   # 52
grep -nE "轮次开始|SKIPPED_LOCKED" ~/code/trade-data/data/logs/fetch_news_launchd.log | tail -24
grep -nE "r2-skip|SEVERE: fetch_news" ~/code/trade-data/data/logs/schedule_monitor_launchd.log | awk -F: '$1>16800' | tail -20
grep -nE "✗|FAIL" ~/code/trade-data/data/logs/deploy_20261009_1632.log | head -25   # 16:42 校验失败明细(fund_nav DB 领先产物 9 天)
```

## 9. 诚实标注(§5.1④)

- **计数口径**: 「20 条」= 两树 latest.md 中 `2026-10-09` 的 severe 条目数(运行树 19 + 信号树 1, 截至 22:00 审计时点; 22:00 后至收盘后更晚的条目未再核查——fetch_news 22:01 轮仍在 skip, 22:15 后巡检是否再发未验)。恢复按「实际发出 1 + 抑制 1」计。若用户「两位数」还包含 report 群功能输出(18 条盘中信号), 属另一口径(§2-D6 已说明)。
- **推断项**: ① unit 巡检集合变更 9 次的精确轮次为日志重建, 17:00/18:30 两次与告警的轮次归属可能有 ±1 轮错位(monitor shell 行与 python 行落盘次序错位, 同 181 报告 §5.3 边界); 「4 条为纯缩小方向」由连续消息正文集合逐条对比钉死(16:45=7 → 17:00=6 → 18:15=5 → 18:30=4 → 20:15=2), 不依赖轮次归属。② 22:00 fetch_news 第 3 封判「高度疑似幻影」基于 181 §5 机制 + 真 skip 轮清单(21:01/21:45 确认 skip, 22:01 轮 skip 发生在告警之后); 精确 +1 归属待 #181 修复后回看。
- **未覆盖**: 23:25 R5 收尾轮、次日 unit 巡检「是否只发 1 次」的观察点未核实(留待下一窗口)。
- **本审计未做**: 不改任何代码/状态(本报告文件除外); 不跑业务脚本; 无外发; §6 方案为设计建议, 实施需主控派单, 其中触碰冻结面(notify.py)的改动(台账、env 推广、Pattern B)需用户拍板。
