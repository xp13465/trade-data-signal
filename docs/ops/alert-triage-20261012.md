# 2026-10-12 全天告警逐条定性(researcher 只读取证)

- 取证对象:云上 `data/alerts/alert_ledger.jsonl` 今日 68 条(notice 54 / critical 13 / warning 1)+ `latest.md` + `alert_state.json` + 各任务日志(`data/logs/`)。
- 方法:事件驱动(find 新鲜文件逐个 tail + 定点 grep),ssh 只读;未做任何生产写 / 配置改 / 通知发。
- 前置确认:账本今日 critical 实为 13 = failed unit ×4 + 1项计划任务异常 ×5 + R2上传失败 ×1 + nextday_gap ×1 + kelly ×1 + turnover ×1(「计划任务异常 ×6」为口头笔误,账本 5 条,与 13 总数自洽)。

## 一、分档表

### critical ×13

| # | 现象 | tier | 频次 | 根因(证据) | 状态 | 建议 |
|---|------|------|------|------------|------|------|
| 1 | 云上 failed unit 持续未清(升级 critical) | critical | 4(00:00/09:45/16:45/22:30) | `failed_units_patrol_state.json`: first_fail_date=10-08, consecutive_days=5;当前挂 3 个 unit:`trade-kelly-intraday-rerun`(exit5)/`trade-nextday-gap-check`(exit2)/`trade-turnover-backfill`(exit124),`systemctl --failed` 实证。升级阈值=3 天(`alert_denoise_rules.py:60` FAILED_UNITS_ESCALATE_DAYS=3),「连续5天」为实值;4 条=升级档独立 dedup key 窗口过期重发(`notify.py:2791-2825`)。unit 集合逐日在变:16:45 名单含 `trade-public-fund-daily.service`(latest.md 16:45 条),说明中间有人清过部分(从 10-08 的 6 个 unit 缩到 3 个) | 已知(各 unit 有独立案);「清了又回来」= 未修根因、failed 状态悬置(巡检只告警不 reset,`check_failed_units.py:54-62`) | ①排修 3 个 unit 根因(见 #4/#5/#6)②修后人工 `systemctl reset-failed` |
| 2 | 1项计划任务异常 00:00 | critical | 1 | `fetch_news R2 上传锁连续 6 轮跳过(SKIPPED_LOCKED)`,10-11 21:16 实例持锁至 10-12 00:15(日志 `schedule_monitor_launchd.log:18605-18607`) | 已自愈(00:15 实例结束) | 与 G1 同源(见噪声分析) |
| 3 | R2上传失败 00:15 | critical | 1 | `r2_upload_async_20261011_211622.log:5/37/53-54`:upload-trade-sim 通道「低速(近5分钟字节增量<1MB)」被 kill → verify-channels 缺口;随后重传成功(同日志:58 `[trade-sim] ✓ 103/103, 耗时377.5s`) | 已自愈(补传成功) | 忽略(可观察) |
| 4 | nextday_gap_check 伪跳空校验未完成 | critical | 1(09:29) | `nextday_gap_check_launchd.log` 10-12 09:26 段:akshare fund_etf_spot_em `ConnectionError: Remote end closed connection without response` + 新浪/腾讯双源全败,4 次拉取(初始+3 退避)全失败 → 开盘价就绪闸 fail-closed 标 pending rc=2;`systemctl show` ExecMainStatus=2;首次失败 10-08(已连续 5 天) | 待修(数据源侧,三源全挂) | 排查 09:26 时段三源可用性;根因非脚本 |
| 5 | kelly-intraday-rerun 退出码 5(09:40) | critical | 1 | **与 #254 台账一致**(`docs/pending-features-index.md:390`):159513/164508 当日 09:40 前零成交 → missing → 刻意 fail-closed exit5;方案 A 已于 10-12 上线(main b896f2a31),10-13 09:40 首跑待人工看闸报告 | 已修待验证(不需重查) | 10-13 09:40 人工确认首跑豁免 |
| 6 | turnover 独立链异常 22:27 + 22:30 | critical | 2(同因两通道) | `turnover_backfill_launchd.log` 尾部:四段 pipe=0/export=0/r2=0 皆过,`upload-data-large` 上传 275MB(accum_nav_map 25MB + signal_kelly_trades 83MB + sdc 84MB)停滞 900s 无输出被 kill,rc=124;`.r2_data_large_uploading.marker` 残留触发下次「强制全量重传(fail-closed)」;10-09 同任务 dur=3795s(63min)已完成,本次 21:10→22:27(77min)首次破线 | 待修/待拍板 | 大文件链跨链路慢传输治理(超时已按停滞判定,总预算不足);当日 a_turnover_* 未上线(前端 T-1 标红机制兜底) |
| 7 | 1项计划任务异常 16:15 | critical | 1 | `intraday_snapshot 执行耗时 940s 超阈值 900s last_run<15:35>`(`schedule_monitor_launchd.log:19081/19096-97`;dur_buffer 连续 2/2 轮判 SEVERE);仅超阈 40s(4.4%),非卡死 | 已恢复(21:00 `[恢复]`;20:35 轮 808s 正常) | 观察;阈值 900s 极贴近常态波动区,可评估(TBD) |
| 8 | 1项计划任务异常 21:15 | critical | 1 | fetch_news R2 锁连续 6 轮跳过(SKIPPED_LOCKED),即 10-12 21:11 实例持锁期(同 G1);state `fetch_news|r2_skip_alert` last_alerted 22:45→23:00 recovered | 已自愈(23:00 锁链清零) | 与 G1 同源 |
| 9 | 1项计划任务异常 21:45 | critical | 1 | `overfit_monitor R2 上传锁连续 3 轮跳过`(阈值 3,`schedule_monitor_launchd.log:19306-07`);同 G1 持锁期 | 持续中(state active,23:00 仍 3 轮) | 与 G1 同源;锁释放后应自愈 |
| 10 | 1项计划任务异常 22:30 | critical | 1 | `turnover_backfill 退出失败 last_exit=124`(日志 19340-41);同 #6 | 见 #6 | 见 #6 |

### warning ×1
| 现象 | 频次 | 定性 |
|---|---|---|
| [告警·聚合] 1条 warning 汇总 20:30 | 1 | = fetch_news R2 锁 skip 的 **warning 档**(升级 SEVERE 前的聚合缓冲档,`schedule_monitor_launchd.log:19245` @20:30)。**设计内降噪通道**,随后 21:15 按阈值升 SEVERE |

### notice ×54(分类)
| 组 | 条数 | 定性 |
|---|---|---|
| 盘中买卖点信号/盘中异动/减仓解除/信号变化(intraday_snapshot) | 29(09:27→15:08 盘中 28 条 + 20:40 盘后 1 条) | **设计内推送**(盘中实时信号产品本体) |
| 买卖点信号(backfill_metrics 16:51/21:41、update_all 18:31、02:16 补发 10-09) | 4 | 设计内推送 |
| [恢复] intraday_snapshot dur>900s(21:00) | 1 | 设计内恢复通知 |
| a_fund_main 重采失败(02:52→08:07,45min 间隔 ×8) | 8 | **真告警-误报环**(见 G3) |
| 信号凯利回测停滞(02:17) | 1 | 真告警(停滞检测独立通道 dedup24h,`backfill_evening_launchd.log:44839-41`);与交易记录落后/kelly 数据陈旧相关;10-12 22:35 `kelly_stale` 已恢复 |
| update_all 完成(18:48) | 1 | 设计内 |
| R2上传异步锁跳过(18:51) | 1 | **设计内降级**(锁被占→pending 标记补跑;`r2_upload_skip_notify.sh:47-51` dedup 6h,当日其余 5 次 skip 被 6h 窗吞) |
| 汪汪队信号(20:10,10-09 T-3) | 1 | 设计内推送 |
| 每日速递(20:40/20:45) | 2 | 设计内推送 |
| 过拟合监控 38 分(21:40) | 1 | 设计内推送(产品输出) |
| 明日买入计划(22:30) | 1 | 设计内推送 |
| 数据缺口(22:35 断档 warn 转发 + 恢复) | 2 | 见下(真告警+恢复) |
| verify-r2 两条(23:07) | 2 | 真告警-兜底链触发(见 G1) |

## 二、噪声结构分析

- **设计内推送(=非告警)**:29 盘中 + 4 买卖点 + 1 恢复 + 1 update_all 完成 + 1 锁跳过 + 1 汪汪队 + 2 速递 + 1 过拟合 + 1 明日计划 = **41 条**。
- **真告警**:critical 13 + warning 1(fetch_news 过渡档)+ a_fund 环 8 + 停滞 1 + 断档 2 + verify-r2 2 = **27 条**。41+27=68 ✓
- **同一病根重复刷分组**:
  - **G1 跨境慢链路/大文件上传链(最大组,合计约 8 条)**:10-12 21:11 r2_upload_async 实例持锁 2h→派生 fetch_news skip×2(21:15/22:45)+overfit skip×1(21:45)+锁跳过×1(18:51)+verify-r2×2(23:07)+turnover exit=124×2(22:27/22:30);凌晨的 00:00 skip(6 轮)同型(10-11 21:16 实例 3h)。2026-10-12 21:11 实例日志实锤:`upload-index 低速kill` + `upload-data-large 停滞900s kill (275MB,.marker 残留强制全量)`。
  - **G2 failed unit 三兄弟(合计约 8 条)**:kelly(#254/#5)+ nextday-gap(三源挂/#4)+ turnover(124/#6)三 unit 的链路告警 + 升级 critical 4 条叠加。
  - **G3 a_fund_main 45min 误报环(8 条)**:见下。

## 三、G3 专项:08 重采失败 ×8 与待审分支对应(确认)

- 根因(全链):02:00 槽 backfill_direct_metrics 把「market_fund_flow 多源皆败」判为 error(打印「静默」却 log_collect(error))→ retry_failed_metrics(只取 error)每 15min 重试(必败)→ 连续 3 轮通知 → 每段 45min 一条无限环;今日实测 02:52→08:07 共 8 条(45min 间隔)。
- **与待审分支 `worktree-agent-a3e38ce1838393e7e` 完全对应**:commit `9f106cc5a`「fix(backfill): 凌晨槽结构性缺口写 warn 非 error —— 根治 a_fund_main 45min 误报环」(worktree list 实证),修法=该分支 error→warn(单点治根,retry 只认 error 环断;warn 仍进 collect_health 黄点,保留 #84 P1-1 真故障判别)。
- 附加史实(分支 commit 载明):notify 路径自 09-30 起有 pre-existing NameError(10-09 17:57 #241 才修)⇒ 环 10-08 起存在但静默,10-12 首爆——**不是新故障**。
- 边缘证据:同夜 backfill 侧已有「(02:00 槽预期缺口, 静默)」处理(`backfill_evening_launchd.log:44833`),环出在 retry 链路。
- 自愈:末次 `[ok] a_fund_main: 1 rows`(self_heal 日志),当日白天源恢复后清场。

## 四、23:07 两条 R2 告警(最新,优先)定性

- 机制来源:`upload_r2.py:3767-3789`(对账不一致 >50 阈值 →「R2 可能被异源覆盖」告警,dedup 6h)+ `:3798-3817`(#188 独立链产物脱节告警,dedup 6h;台账实有池=a-stock-*/overview/news_digest/schedule_stats)。
- 本轮实况(`r2_upload_async_20261012_211112.log` 全文 74 行):21:11 实例中 `upload-index` 低速 kill(行 5)、`upload-data-large` 停滞 900s kill(行 20 前后,275MB)→ `verify-r2 兜底补传 237 个`(行 64,**名单全为 index/csi_* 类指数文件**)+ `verify-channels rc=1 缺口`(行 68-69)→ 两条 23:07 告警。
- **定性**:不是「异源覆盖」真风险,是**上传通道被杀 → R2 端陈旧 → 兜底机制正常触发并已补平**(补传完成)。属 G1 下游表现;文案中的「异源覆盖」两候选原因(周日全量对账/本机误跑)本轮均不成立。
- **与 22:4x 公募 nav 回填的关系核实:「无关」成立,三证**:①237 个不一致名单全为 `index/csi_*`(不含 public_fund/nav_bucket 任何键);②`static-site/data/nav_bucket` 目录 mtime=**18:20**(与 18:20 的 fund_nav_upload_async 同时点),22:4x-23:07 无改动 ⇒「回填未动 nav_bucket」与文件系统证据一致;③云上 22:4x 无任何公募/nav 任务运行记录(public_fund_full 22:00 因无新数据跳过;`systemctl list-timers` 22:4x 无 nav 类 timer)。
  - 诚实标注:未在云上日志找到「22:4x 公募 nav 回填」动作本身的运行痕迹(若该动作在本机/别处执行,云上侧不可见);上述三点仅证「23:07 与公募 nav 无关」。

## 五、降噪候选(均保真故障判别维度)

1. **[最高优先] G3 a_fund_main 环**:修复已在待审分支(9f106cc5a),合入即消 8 条/日;合前注意「NameError 掩盖期」史实,确认部署后首日观察。
2. **G1 根因治理(大文件链路)**:turnover upload-data-large 与 r2_upload_async upload-data-large 是同一 275MB 链,两次 kill(停滞 900s)是同一慢链路;建议评估上传超时总预算/大文件拆分(架构层,待拍板)——治理后 turnover/verify-r2/fetch_news skip/overfit skip 一组告警大概率同步消失。**不建议**对 verify-r2 两条单独降噪(它是兜底安全网,「大量不一致」告警是真信号)。
3. **failed unit 升级刷 ×4/日**:**不建议降频**(「人工处置超时」是真信号,6h 窗重发是设计)。可选待拍板项:对「已开案跟踪中」的 unit 走白名单降级汇总(新增 unit 仍立即报)——**需用户拍板**,当前不建议动。
4. 16:15 intraday 940s:超阈 40s 轻触发(连续 2/2 轮规则已是最小缓冲),可评估「超阈比例 <15% 先 warning、真卡死(>=1800s)仍 SEVERE」——低优先(TBD)。

## 六、诚实标注(未坐实/待澄清)

1. 「1项计划任务异常 ×6」:账本实为 5 条(与 13 critical 总数自洽),无第 6 条;若按其他口径计数请主控核定。
2. 16:45 latest.md 名单中 `trade-public-fund-daily.service` 何时被清、由谁清(reset-failed 或重载),未取证到直接记录(现象:failed 集合从 10-08 的 6 个缩到 3 个)。
3. 23:07「独立链产物脱节」的具体产物名单(stderr 不落本日志文件,未取到逐字名单);机制与池子已知(见四),本轮成因已由 237 名单+通道 kill 锁定。
4. **附:一条被降噪吞掉的 severe(不在 68 条账本内,建议上报)**:22:35 check_data_gap 检出 `[severe] 公募基金 20261009 采集全 NULL: 24224 行 unit_nav 全为空`,被 budget「并入当日摘要」未直发(`check_data_gap_launchd.log` 10-12 段:notify 未真发出 category=data_gap 今日直发 1/1);同族 10-08/10-09 各报过(nav 全 NULL 自 10-08 起)。是否已有在案跟踪未查证——**建议主控核实处置链**(真故障被摘要层挡住 vs 既有案降噪,二者需区分)。
5. 「信号凯利回测停滞」的 snapshot 具体判定细节(停滞=哪项产物无增量)未逐字取证;已证 10-12 22:35 `kelly_stale` 恢复。

## 附:今日时间线骨架(仅关键节点)

02:16 补发 10-09 买卖点信号 → 02:17 凯利回测停滞(独立通道)→ 02:52-08:07 a_fund 环 ×8 → 09:26/09:31 gap_check 三源挂 rc=2 → 09:40 kelly #254 → 09:27-15:08 盘中信号 ×28 → 15:35 快照 940s(16:15 SEVERE)→ 17:08 public_fund_daily OK → 18:20 nav 上传/桶(mtime 18:20)→ 18:48 update_all 完成 → 21:10 turnover 起跑 → 21:11 r2_upload_async 起跑(持锁 2h)→ 21:15/21:45/22:00/22:15/22:30/22:45 fetch_news/overfit skip 链 → 22:27 turnover kill 124 → 22:30 nextday_plan OK → 22:35 数据缺口(断档 15 + 公募 NULL 吞摘要 + kelly 恢复)→ 23:00 fetch_news 恢复 → 23:07 verify-r2 两条。
