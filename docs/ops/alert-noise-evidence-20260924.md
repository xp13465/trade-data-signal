# 告警噪音取证报告(2026-09-24)

> 调研 researcher 产出 | 只读不改代码/数据 | 近 7 天告警按类计数 + 逐类定性 + 降噪建议
> 口径:云上真实邮件发送痕迹(权威)+ latest.md severe 镜像 + notify_dedup(被吞痕迹类)
> 任务书:m真告警还是噪音?| 仅真故障保持直发,severe 不静默(§14 即时性优先)

## 0. 结论摘要(先说人话)

**近 7 天(09-17~09-24)用户实际收到告警邮件约 131+17=148 封,其中约 2/3 是"真问题但重复轰炸",约 1/3 是"一次性真故障已自愈"。真正需要动手的根因只有 1 个:board_etf_map 旧版兜底(32 封,持续 3 天未止)。**

按类:
- **真问题(需修根因)**:board_etf_map 旧版兜底 32 封(持续中,9-24 18:55 仍在发)
- **真问题但低频(保留直发)**:nextday 伪跳空 2、turnover 1、kelly盘中失败 4、S06 1、数据缺口 1、overfit WARN 1
- **半噪音(有信息量但频率过高)**:计划任务异常 57、deploy R2 上传失败 23、kelly 冻结缺键 12、with_lock 8
- **噪音(信息量低)**:self_heal 自愈上限 2、update_all 耗时 3(多与计划任务异常重叠)

---

## 1. 近 7 天按类计数表

### 1.1 邮件痕迹级(权威口径=云上 sent-final.tsv,[notify] 邮件已发送至 691 行过滤 09-17~09-24)

| 类别 | 次数 | 首次 | 末次 | 触发源脚本 | 严重级 |
|---|---|---|---|---|---|
| 计划任务异常(汇总) | 57 | 09-17 15:00 | 09-24 14:15 | schedule_monitor.sh(15min 轮询,detected N alerts) | SEVERE |
| board_etf_map 旧版兜底 | 32 | 09-22 18:30 | 09-24 18:55 | deploy.sh L1062-1069(9-22 F1 引入,--dedup-window 3600) | SEVERE |
| deploy R2 上传失败 | 23 | 09-17 | 09-23 22:27 | deploy.sh 收尾(9-11 P1-2 延迟收尾)+ verify-channels | SEVERE |
| with_lock 排队超时 | 8 | 09-21 | 09-22 22:32 | deploy.sh + 各 backfill 撞 /tmp/trade_deploy.lock | SEVERE |
| kelly 盘中增量失败 | 4 | 09-17 09:40 | 09-23 09:40 | kelly_intraday_rerun(09:40 timer) | SEVERE |
| update_all 耗时/失败 | 3 | 09-18 | 09-22 21:00 | update_all.sh(5400s 阈值,与计划任务异常重叠) | SEVERE |
| nextday 伪跳空校验失败 | 2 | 09-23 09:31 | 09-23 14:37 | nextday_gap_check.sh | SEVERE |
| turnover 链路异常 | 1 | 09-18 22:40 | — | turnover_backfill.sh | SEVERE |
| kelly 回测停滞 | 1 | 09-22 | — | signal_kelly_backtest.py | SEVERE |
| **小计** | **131** | | | | |

### 1.2 镜像/补充级(latest.md severe 流水 + notify_dedup,capture_output 吞痕迹类)

| 类别 | 次数 | 首次 | 末次 | 触发源 | 严重级 |
|---|---|---|---|---|---|
| kelly 冻结缺键 | 12(9-18 622 集中 1 次 + 9-21 起每天 1 个×11) | 09-18 10:54 | 09-24 18:14 | signal_kelly_backtest.py `_alert_frozen_missing`(L~310) | SEVERE |
| self_heal 自愈达上限 | 2 | 09-22 00:52 | 09-23 00:22 | self_heal.sh notify_severe(L154/L181/L235) | SEVERE |
| S06 快照失败 | 1 | 09-21 20:35 | — | s06_snapshot | SEVERE |
| 数据缺口(交易断档) | 1 | 09-21 22:35 | — | check_data_gap | SEVERE |
| overfit 参数尖峰 | 1(WARN) | 09-23 21:40 | — | overfit_monitor.py param_spike | WARN |
| **小计** | **17** | | | | |

**合计 ≈ 148 封**(计划任务异常 57 中部分与 1.1 各行在时间上重叠但主题不同,按主题不互斥)。

---

## 2. 逐类定性

### 2.1 计划任务异常 57 封 —— 半噪音(真信息:任务确曾异常;但已 100% 自愈,15min 轮询反复轰炸)

- 事件驱动证据(schedule_monitor_launchd.log 逐条 "检测到 N 个告警"):R2 直连 16、backfill_evening 15、update_all 6、etf_national_team 5、lab_auto 3、lhb 3、service未加载 3、nextday 3、turnover 2、us_stock 2、s06 2、futures 1、intraday 2。
- **关键:alert_state-main.json 129 个 key 全部 recovered**——没有一条停留在 active。即每封邮件背后都是"曾经异常,现已恢复",但 15min 轮询每次 detected 都发,一天可 13 封(09-18)。
- 依据:latest.md 51 条 [severe] 标题 + alert_state 全 recovered + schedule_monitor 邮件与 detected 次数一一对应(88 次 1 项 + 16 次 2 项 + 2 次 3 项)。

### 2.2 board_etf_map 旧版兜底 32 封 —— **真问题持续中,唯一需要修根因的** ★

- 根因链:build_board_etf_map.py L1789 附近 `ak.fund_etf_spot_em()` 抛 `requests.exceptions.ConnectionError: ('Connection aborted.', RemoteDisconnected())`(东财反爬)→ 主源失败 → 新浪/腾讯兜底(9-24 已成功生成 2045 只/138 指数,deploy 层兜底可用)→ build 退出码 1 → 各任务(deploy/backfill/us_stock/update_all 各自触发)发"旧版兜底"告警。
- 9-23 曾验证 deploy_20260923_2128.log L2147-2148 R2 缺口为真;board_etf_map 同日志 L173 附近 build 失败确认。
- dedup-window 3600s = 每小时每任务各 1 封 → 一天多封;9-24 18:55 仍末次(未止)。
- 分解:有日期 23 + launchd 无日期 9(映射 9-22~9-24)= 32。

### 2.3 deploy R2 上传失败 23 封 —— 半噪音(9-20 1 天 8 封是网络波动;9-23 22:27 对账真缺口)

- 9-11 P1-2 已延迟到收尾,当前形态 = "deploy 整体 rc=0 但某通道失败 → 收尾统一告警 + verify-channels 轻量对账"。
- 9-23 22:27:verify-channels rc=1 确认真缺口(upload-data-large/upload-kelly-parts)≠误报。
- 9-20 一天 8 封(15:00/16:00...每小时 1 封)—— P1-2b upload_r2 try/except 已修单文件超时,但大文件/高频时段仍可能通道级失败。
- 有日期 16 + 无日期 7(9-17~9-23)= 23。

### 2.4 kelly 冻结缺键 12 次 —— 半噪音(9-18 622 大事件真 P0;9-21 起每天 1 个重复键,读侧兜底 9-22 已接住但告警仍直发)

- 9-18 10:54:622 个历史信号一次性暴露(样例 20001114|sw_801030|buy_backup 等)——真 P0,冻结键与信号类型漂移所致(freeze-key-signal-type-drift 根因,9-22 已读侧兜底根治)。
- 9-21 22:56 起 11 次每次 1 个——重复键 20260918|sz_div|buy_aux 等,读侧已兜底不影响回测结果,但 SEVERE 邮件仍每日 1 封。

### 2.5 with_lock 排队超时 8 封 —— 半噪音(撞 deploy.lock 排队超时,锁竞争瞬时,已自愈)

- 9-21(2 封,lhb)+ 9-22(6 封,backfill_evening/futures/deploy 等),随后锁释放任务补跑正常。

### 2.6 kelly 盘中增量 4 封 —— 真问题低频(9-17 对账 FAIL 退出码 3;9-23 失败退出码 5)

- 09-23 09:40 盘中回测失败(akshare 数据未就绪/校验失败),17:50 全量回测兜底覆盖,当日正常。保留直发。

### 2.7 self_heal 自愈达上限 2 封 —— 噪音(信息量低:今日 3 次自愈额度用光,次日自动重置)

- 09-22/09-23 各 1 封,内容="已达每日上限 3 次停止自愈。今日 healed:[etf_national_team×3]"——这是自愈机制正常工作的信号,不是故障。

### 2.8 nextday 2 / turnover 1 / update_all 3 / S06 1 / 数据缺口 1 / overfit 1 —— 真问题低频或例行,保留

- nextday 伪跳空 2:9-23 09:31 + 14:37 两次校验失败(akshare ConnectionError),补采后正常,低频率保留。
- turnover 1:9-18 22:40 TimeoutError,当日换手率数据缺失,已补。
- update_all 3:9-18(175min 超时)/9-21(21:00 exit=143)/9-22(21:00),阈值 5400s 已够,与计划任务异常重叠,低频保留。
- overfit 1:9-23 21:40 param_spike WARN(d3 卖出模式敏感 90),24h dedup,发送成功无镜像(WARN 不镜像 latest.md,依赖 notify_dedup 佐证),低频真信号保留。

---

## 3. 降噪建议(带代价,severe 不静默,不降频不后台暂停)

| 类 | 建议 | 代价 | 优先级 |
|---|---|---|---|
| board_etf_map 32 封 | ①根因:build_board_etf_map.py 东财失败换道新浪/腾讯兜底重试逻辑(9-24 兜底已成功说明可用,失败点是主源+校验链);②dedup-window 3600→21600(6h) | 6h 内不重复轰炸,真问题仍会报;根因修好后自然归零 | **P0(唯一根因)** |
| 计划任务异常 57 封 | ①15min detected **合并去重窗口**(如同 key 已发且状态已 recovered 不再发,只保留"recovered 汇总");②每 6h 聚合 1 封"当日 N 项计划任务异常均在 X 时恢复" | 已恢复的重复轰炸消失;若任务真卡死仍 15min 内直发(recovered 前不合并) | P1 |
| deploy R2 23 封 | 同 key 去重窗口 3600→21600(6h),verify-channels 真缺口保留 | 6h 内多次失败合并 1 封 | P1 |
| kelly 冻结缺键 12 封 | 1 个/次的小缺口降级为 WARN(dedup 24h),622 级大事件仍 SEVERE 直发 | 小缺口当日可能只进 WARN 不直发(读侧已兜底,结果不受影响) | P1 |
| with_lock 8 封 | 降 INFO 日志或 dedup 24h(锁排队瞬时,非数据问题) | 真锁死(任务互相饿死)可能漏,但 schedule_monitor 的 exit!=0 会兜底 | P2 |
| self_heal 上限 2 封 | 降 INFO(自愈额度用光是正常状态,次日重置) | 长期自愈失败会被 schedule_monitor 兜底捕获 | P2 |
| nextday/turnover/kelly盘中/overfit/S06/数据缺口 | **保持直发不变** | 无 | — |

---

## 4. 诚实空白标注

- **board_etf_map 32 的分解**:23 条有日期 + 9 条 launchd 无日期(用 "=== 任务名开始 2026-09-XX" 锚点行号映射钉到 9-22~9-24,非逐条独立时间戳)。
- **9-18 10:54 ~ 9-21 22:35 之间的 kelly 冻结缺键次数可能被低估**:latest.md cap 50 滚动 + capture_output 吞痕迹,只能靠 notify_dedup.last_alerted 佐证,9-18 622 大事件有本地 latest.md 佐证,9-19/9-20 若有 1 个级小缺口无法确认(诚实标注:该区间只有 9-18 622 一条可证实)。
- **计划任务异常 57 与 1.1 其他类可能存在同一事件双计数角度的重叠**(如 update_all 异常既被 schedule_monitor 汇总又被 update_all.sh 直发),按主题计数不互斥,已注明。
- **overfit 9-23 发送**:notify_dedup.overfit_param_spike last=9-23 21:40:42 + overfit_monitor 日志发送成功,但 latest.md 无镜像(WARN 级不镜像),sent-final 未抓到(可能 subject 无 [告警] 前缀)。
- **无法计数的类别**:telegram 通道(从未启用,占位符,非计数对象)。

## 复现

- **sent-final.tsv**:云上 691 行 [notify] 邮件痕迹合并修正时间戳,见 /tmp/cloud-alert/sent-final.tsv(本机临时分析副本)。
- **latest-main.md**:云上 data/alerts/latest.md 9-21 22:35~9-24 18:55 共 51 条 [severe],/tmp/cloud-alert/latest-main.md。
- **alert_state-main.json**:129 key 全 recovered,/tmp/cloud-alert/alert_state-main.json。
- **notify_dedup-main.json**:board_etf_map_stale last=9-24 18:55 等,/tmp/cloud-alert/notify_dedup-main.json。
- **schedule_monitor 检测事件分布**:schedule_monitor_launchd.log grep "检测到 N 个告警"。

## 配套文档

- 无新脚本;全部为既有日志/状态文件的查证,上轮降噪实施记录见 docs/alerts/alert-noise-rootfix-20260910.md(commit a0d919c5f,update_all 3600→5400s/dedup 去分钟数/telegram 占位符不算 FAIL/deploy R2 延迟收尾 + upload_r2 try/except 均已生效)。
