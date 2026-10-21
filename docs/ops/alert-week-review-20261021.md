> **落档元信息(2026-10-21,机械落档)**
> - **来源**:云上只读调研产出 `/tmp/alert-week-report.md`,**正文原样落档,正文数字未改**(仅本元信息块为落档时新增)。
> - **统计窗口**:2026-10-14 00:00:09 ～ 2026-10-21 22:45:36(云上时间)。
> - **数据源(生产权威源)**:云上 `122.51.111.173` 的 `/home/ubuntu/code/trade-data` —— `data/alerts/`(alert_ledger / alert_digest / alert_domains / alert_daily / notify_dedup / failed_units_patrol_state)、`data/logs/`(deploy / self_heal / check_data_gap / schedule_monitor 等近 8 天新鲜日志)、`systemctl list-units/list-timers` 状态、产物与 DB 交叉核对。
> - **调研方式**:事件驱动(新鲜日志逐个 tail + 台账聚合 + systemd 状态 + 产物/DB 交叉核对)。
> - **只读声明**:全程只读 —— 未写入云上任何文件、未改 DB、未改 systemd unit/timer、未发任何通知(全文见文末 §⑤)。
> - **关联立案**:#269 告警黑洞 / #270 部署闸门级联 / #271 cov_premium_median 列漂移 / #272 history_overwrite 误报(登记于 `docs/pending-features-index.md` 模块二十)。

---

# 最近一周告警盘点与归因报告（只读调研）

窗口：2026-10-14 00:00:09 ～ 2026-10-21 22:45:36（云上时间）
生产权威源：云上 122.51.111.173 的 /home/ubuntu/code/trade-data
调研方式：事件驱动（新鲜日志逐个 tail + 台账聚合 + systemd 状态 + 产物/DB 交叉核对）
全程只读：未写入云上任何文件、未改 DB、未改 systemd、未发任何通知。

---

## ① 一周总览（数字 + 来源）

### 台账总盘（来源：data/alerts/alert_ledger.jsonl，窗口内 394 行）
- 按 group：alert 210、report 172（盘中信号播报，非告警）、follow 6、agent_done 2、无 group 4
- 真实告警（group=alert）210 条，按 tier：critical 118 / notice 62 / warning 21 / digest 9
- 按天（group=alert）：
  | 日期 | 条数 |
  |---|---|
  | 10-14 | 24 |
  | 10-15 | 52 |
  | 10-16 | 38 |
  | 10-17 | 9 |
  | 10-18 | 11 |
  | 10-19 | 21 |
  | 10-20 | 28 |
  | 10-21 | 27 |
- 按故障域（同窗口，group=alert）：r2_upload 59、refetch_fail 23、task_anomaly 21、history_overwrite 20、failed_unit 16、data_gap 9、deploy_gate 6、kelly_freeze 6、overfit 4、consistency 4、nextday_plan 2、heartbeat 1

### 被摘要/域抑制吞掉、未以独立告警呈现的量（来源：alert_digest.jsonl / alert_domains.json / alert_daily.json）
- alert_digest 合并：10-16 97 条、10-17 79 条、10-20 18 条（合并条目仍进台账，但正文被折叠）
- alert_domains.json：r2_deploy n_direct 14 / n_absorbed 275；kelly 6 / 16；data_gap 4 / 2
- alert_daily.json（10-21）：total 51，by_tier critical 9 / notice 37 / warning 4 / digest 1，merged_in_digest 7

### 发布链成败（来源：data/logs/deploy_YYYYMMDD_*.log，脚本统计）
| 日期 | 成功次数(退出码=0) | 失败次数 |
|---|---|---|
| 10-14 | 10 | 3(integrity_fail) |
| 10-15 | 8 | 9 |
| 10-16 | 0 | 17 |
| 10-17 | 0 | 6 |
| 10-18 | 5 | 0 |
| 10-19 | 15 | 1 |
| 10-20 | 0 | 20 |
| 10-21 | 0 | 19 |
- **最后一次成功 deploy：2026-10-19 23:25:47**（已连续 2 天无一次完整成功）

### 云上 unit 状态（来源：systemctl list-units --state=failed，10-21 22:5x）
- 当前 failed 7 个：fwupd-refresh、trade-etf-national-team、trade-futures-backfill、trade-lhb-backfill、trade-public-fund-daily、trade-public-fund-quarterly、trade-r2-consistency
- failed_units_patrol_state.json：consecutive_days=7，first_fail_date=2026-10-15，last_grade_time=2026-10-21 22:45:02

---

## ② 问题清单（五类）

### 类1：真故障、仍在活跃

**1-1【P0】deploy 全链停摆 2 天：单项硬闸门阻断整条流水线**
- 现象：10-20、10-21 两天 39 次 deploy 零成功；最后成功 10-19 23:25:47。
- 证据：
  - 10-20 全部失败于 `✗ a_fund_north_quarterly: 最新季度行 date=20260630 != 期望 20260930`（21 次）
  - 10-21 全部失败于 `✗ nextday_plan: date=20261019 不是最近交易日/当前交易日/下一交易日 (允许=['20261020','20261021','20261022'])`（19 次）
  - 代码：scripts/deploy.sh:318-375 调 `check_data_integrity.py --deploy-mode`，FAIL 即 `notify.py "[告警] deploy 数据产物校验失败"` 后 `exit "$CHECK_RC"`；闸门位于 export 之后、rsync（deploy.sh:549）/R2 批量上传（deploy.sh:600+）之前。
  - scripts/check_data_integrity.py:2160-2215 `check_nextday_plan()` **从 R2 拉取** `_fetch_r2_json("nextday_plan.json")`，不是读本地。
- 根因：10-20 22:30 nextday_plan 的 R2 上传 480s 超时（nextday_plan_launchd.log：`⚠ R2 上传超时(480s, 将告警)` → `✗ 次日买入计划生成失败 rc=1`），导致 R2 上 nextday_plan.json 停在 20261019；此后每次 deploy 的下一交易日计划校验都判旧版 → 阻断 → **下一次 export 也就没机会把产物刷新，形成自锁**。
- 影响（下游全部不执行）：R2 批量上传、static-site rsync、staticdata 异步备份。已见后果：
  - staticdata 异步备份日志最新一份 = staticdata_backup_async_20261019_232547.log（10-19 23:31 之后完全无新文件）
  - local 与线上已漂移：board_etf_map.json 本地 md5 c8d08efb…（mtime 10-21 21:58:11）vs 线上 cb25eab6…；schedule_stats.json 本地 dc902fa4…（22:45）vs 线上 fad15a95…
  - r2_consistency 10-20 23:24 exit=1：local 落后（overview date local 20261019 vs 其余 20261020；accum_nav_map 1730 vs 1734 codes）
- 现状：10-21 22:30 nextday_plan 重跑成功，**线上 nextday_plan.json 已实测为 date=20261021**（curl ss.fx8.store），本地同文件 date=20261021；因此下一次 deploy 的阻断条件应已消除，但**尚无一次成功 deploy 复核**。
- 附带：6 个 trade-* unit 的 exit=1 全部是 deploy 下游，不是 unit 自身采集失败——
  public_fund_daily 17:07:01、public_fund_quarterly 07:12:43、futures_backfill 21:07:42、lhb_backfill 19:37:14、etf_national_team 22:01:53 日志均以 `✗ 数据产物校验失败(退出码 1)，终止部署` + `deploy=1` 收尾；r2_consistency 是独立的 local 漂移 exit=1。

**1-2【P0】failed unit 告警静默黑洞：坏了 2 天，一条告警都没发出去**
- 现象：7-8 个 unit 持续 failed（10-15 起连续 7 天），但台账里「云上 failed unit 持续未清」最后一条是 **2026-10-19 11:00:06**，之后 10-19/10-20/10-21 再无任何 unit 异常告警。
- 证据链（三处互证）：
  1. data/failed_units_patrol_state.json：consecutive_days=7、last_grade_time=2026-10-21 22:45:02（说明巡检每轮都在跑、都判出异常）
  2. data/notify_dedup.json：`failed_units_patrol` 与 `failed_units_patrol_escalated` 的 last_alerted **都停在 2026-10-19 11:00:06**
  3. data/failed_units_patrol_sig.json：`updated_at=2026-10-19 17:00:03`，items 还停在 `["trade-kelly-intraday-rerun.service"]` —— 签名状态 2.5 天没更新过
  4. schedule_monitor_launchd.log 每轮打印：`[196] 云上 unit 异常(自身通道已发告警): CHECK_FAILED_UNITS_FAIL(1 项): 云上 failed unit: …`，即"相信自身通道已发"，不再复核
- 代码根因（scripts/notify.py:3238-3250）：
  - 升级档判定 TIER_CRITICAL 后，先查 `check_dedup(_esc_escalated_key, _esc_window)`（`adr.ESCALATED_DEDUP_WINDOW_SECONDS` 实测 72h）；窗内命中就打印 `[notify][196] 升级档窗口内已发, suppress` 并 **`return 0`**
  - 这个 return 在**普通首报路径之前**（普通路径在 3262 行之后），所以设计注释里承诺的「首报『新增立即报』不受影响」在升级档期间**实际不成立**：新出现的 failed unit（10-20 起新挂的 etf_national_team 等）全部被一起吞掉
- 调用方放大（scripts/check_failed_units.py:420-450）：只在 `_notify_sent(out)` 为真（notify.py 输出含「汇总：已发出」）时才落签名状态；升级档 suppress 的输出没有这个标记 → 判为"未发出" → 不落状态 → 下一轮（15min 后）继续重试 → 永远重试、永远不落状态、永远发不出
- 影响：**整个失败单元监控链路对真实故障失明 2 天**，而这 7 个 unit 恰好是本轮 deploy 停摆的产物（见 1-1）

**1-3【P1】cov_premium_median 抓取失败（外部接口结构变化，不会自愈）**
- 证据：self_heal_audit.log `[fail] cov_premium_median: bond_zh_cov_value_analysis error: Length mismatch: Expected axis has 15 elements, new values have 13 elements`；每 15min 一轮、每 45min 报一次（今日 15 次），`LIMIT 达上限 count=3` 只限制 task 自愈，retry_failed_metrics 不受上限
- 用户可见：线上 overview.json `collect_health.level=error`，items 就是这条（curl 实测）
- 根因：新浪可转债接口列数 15→13，解析器按位置取列 → 必然异常

**1-4【P1】data_gap 交易断档（#252 家族）**
- 证据：check_data_gap_launchd.log 10-21 `交易记录断档: 3 个入样买入信号无对应交易(断档深度 1 交易日)`；10-19 15 个、10-20 7 个、10-16 4 个
- latest.md 明细：160225 新能源汽车LOF（20261016, 已具备次日价仍缺）、159708 红利ETF西部利得（20261019）、159757 电池ETF景顺（20261020 缺次日价）
- 根因：signal_daily 每日全量重算导致历史信号事件消失/出现，冻结表/评级链路接不住（与 history_overwrite 同源）

**1-5【P2】r2_consistency 本地落后（deploy 停摆的直接产物）**
- 10-20 23:24 exit=1；最新一轮 10-21 23:20 尚未到期。细分：R2/CF/MAIN 三方一致，只有 local 落后（overview date 20261019 vs 20261020；accum_nav_map 1730 vs 1734）

**1-6【P2】其它活跃但低频**
- overfit_param_spike：40 分(10-14) → 41(10-16) → 42(10-19) → 49(10-21)，单调升高
- preupload 备份护栏：`PREUPLOAD_FAIL day=20261021 备份失败 failed=2 (copied=19284 skipped=17 runs=147 landed=2643)`，每日如此，但**具体哪 2 个文件失败无法取证**（护栏只报计数）
- fetch_news / overfit_monitor 的 R2 上传锁忙跳过（warning buffer 22:15:02 `连续 3 轮跳过`）

### 类2：真故障已修复/已自愈（复核过，不是遗留）
- S06 快照 #258：10-15 exit=124、10-16 exit=1（FAILED_FILES 一长串）→ 10-19 / 10-20 / 10-21 均 exit=0
- nav_bucket #255：mtime 10-21 18:17 新鲜
- fund_index_daily #257：最新 20261020，滞后 1 交易日 = 正常 T+1
- a_fund_north_quarterly:最新季度行 20260930 已在库，10-21 18:30 的 deploy 已通过该项
- nextday_plan 10-20 22:38 失败（R2 480s 超时）→ 10-21 22:30 成功，R2 date=20261021（curl 实测）
- fund_nav DB↔产物不一致（10-21 16:31-17:00，005343/021103/000084 净值修正）：21:55 deploy 汇总 `43 ok / 0 warn / 1 fail`，唯一失败项只剩 nextday_plan，判断已重建对齐
- turnover_backfill：10-14/10-15 两次 critical（r2large=124）→ 之后 exit=0
- 10-15~10-17 的 R2 403 / CF 502 / MAIN 404：10-18 起恢复

### 类3：机制噪声（报了但不是真故障，给根因）
- **history_overwrite（每日 2 条 critical，最大噪音源）**：signal_daily 每日两次「历史行被重写 ~1000 条(消失/出现各半)」；history_overwrite_audit 表逐日行数 10-14 51270、10-15 51269、10-16 51233、10-19 50213、10-20 51238、10-21 49212 —— 每日全量重算的**稳定产物**，不是数据损坏。当前口径把"设计行为"报成 critical，长期钝化告警敏感度
- failed unit 升级档「连续 N 天」：10-11~10-16 共 19 封同题告警，后加 72h 窗压噪，但压法有缺陷（见 1-2）
- schedule_stats_r2_fail 10 条（10-16 01:12~08:00）：R2 NotEntitled 期间连发，非独立故障
- r2_upload_async_skip / fetch_news / overfit_monitor 锁忙跳过：notice 级，属并发保护
- nextday_gap_check ConnectionError 自 2026-10-13 09:30 起长期 suppress（实际任务 exit=0）→ 误判型噪声
- gen_daily_brief R2_UPLOAD_TIMEOUT 长期 suppress
- data_gap「最近 deploy(deploy_20261021_2155.log)无成功标记」= 1-1 的重复表达，被 domain_inhibited 抑制

### 类4：外部数据源/第三方故障
- **Cloudflare R2 403 `<Code>NotEntitled</Code><Message>Please enable R2 through the Cloudflare Dashboard.</Message>`**（10-15~10-17，nextday_plan 22:30 连续 3 次），叠加 CF 502 / MAIN 404 → 10-16、10-17 deploy 零成功
- 新浪可转债接口列结构 15→13（cov_premium_median，见 1-3）
- board_etf_map 构建失败（10-19 两次 deploy：`✗ build_board_etf_map.py 失败(退出码 1，14 宽基校验未过/akshare 兜底也失败)`）→ deploy.sh:224 降级为旧版兜底 + deploy.sh:1036 发 `board_etf_map_stale` critical（10-19 19:36:23，一次）

### 类5：覆盖盲区（"停了却没人报"）
1. **failed unit 静默 2 天**（1-2）——最严重，见上
2. **staticdata 异步备份停摆 2 天**：日志停在 10-19 23:31，只有 schedule_monitor 的 `[suppress] staticdata_backup 异步备份停摆持续中, last_alerted=2026-10-21 11:45:01`，本窗口台账里没有任何一条独立"备份停摆"告警（只有一条 10-18 的恢复记录）
3. **preupload failed=2 不可定位**：护栏只输出计数，不输出失败文件名，人工无法处置
4. **deploy 连续失败无专门告警项**：靠下游 data_gap 间接表达（"最近 deploy 无成功标记"），语义弱
5. **r2_consistency 判定窗口**：每天 23:20 才跑一次，10-21 的漂移在 23:20 前无人知晓
6. **schedule_monitor 的"自身通道已发告警"是自证**：不做送达复核（notify_sent 只覆盖 check_failed_units 内部，schedule_monitor 侧未复核）

---

## ③ 最该先修的 3 件事（排序 + 理由 + 预估改动面）

**第 1 件：修 failed-unit 告警黑洞（1-2）**
- 理由：这是"监控坏了没人知道"的元故障——本轮 deploy 停摆 2 天、7 个 unit 挂着，全靠人工发现。不修它，后面所有故障都可能静默。
- 改动面：`scripts/notify.py` 升级档分支（suppress 时不要 `return 0` 吞掉首报，改为让普通路径继续或返回可判别状态）+ `scripts/check_failed_units.py` 落状态判据（区分"升级档已发/被窗抑制/真未发出"）。2 个文件，逻辑改动小，风险集中在告警语义，需配单测覆盖"72h 窗内新增 unit 必须报"。

**第 2 件：拆开 deploy 单项闸门与全链阻断（1-1）**
- 理由：一个非核心产物（nextday_plan / 季度行）判旧，就把 R2 批量上传 + rsync + staticdata 备份全部停掉 2 天，爆炸半径与故障严重度不匹配。这也是 6 个 unit failed 的根。
- 改动面：`scripts/check_data_integrity.py` 的 fail 分级（区分阻断级/告警级产物）+ `scripts/deploy.sh:318-375` 退出策略 + 新增"连续 N 次 deploy 失败"独立告警。中等改动，需回归各产物上传链。

**第 3 件：修 cov_premium_median 数据源（1-3）**
- 理由：每天都在报、每天都失败、用户端 overview collect_health 直接显示 error，属确定性失败（不会自愈）。
- 改动面：可转债抓取器按列名对齐（不按位置），15→13 结构变化降级或换源；1 个抓取器 + 单测。

---

## ④ 覆盖边界（诚实标注）
- 已核：trade-data 树 data/logs 近 8 天 1101 个新鲜文件、data/alerts 全部台账/摘要/域抑制/去重状态、systemd failed 列表与 timer LAST、关键产物本地 vs 线上 md5、sentiment.db 的 signal_daily 与 history_overwrite_audit（只读 `mode=ro`）
- **未核/不可核**：
  - systemd journal（未 sudo，且受只读约束未尝试提权）
  - 邮件/飞书实际到达情况（只读，未查投放日志；台账 channels 字段只记录"路由目标"）
  - staticdata 备份桶内部对象（未 LIST R2 备份桶）
  - 小程序侧、其它仓库/通道
  - preupload failed=2 的具体文件（护栏不输出文件名）
- 数值口径：deploy "成功次数"按日志尾行 `退出码=0` 计；"失败次数"按日志内出现校验失败/退出码非 0 计；台账统计按 `ts` 落窗口且 `group=alert`
- 本报告未复核 22:45 之后新产生的告警（窗口截止 22:45:36）

---

## ⑤ 只读声明
- 云上：**零写入**。未创建/修改/删除任何文件，未改 DB（sqlite 全部以 `file:...?mode=ro` 只读打开），未改 systemd unit/timer，未执行任何 notify/邮件/飞书发送，未执行 deploy/export/采集
- 执行的远程命令均为只读：`ls/stat/tail/awk/grep/wc/systemctl list-units/list-timers/curl GET/sqlite3 ro/python3 只读解析`
- 本地仅写 /tmp：/tmp/step*.py、/tmp/step*.sh、/tmp/agent-progress-alert-week-review.md、本文件
- 未出现 `moved to the background` 残留后台任务
