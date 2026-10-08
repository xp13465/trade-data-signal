# 云主机停摆恢复 Runbook(2026-10-08 17:50 盘后链 swap 冻结事故)

> 生成: researcher agent,2026-10-08 19:57 BJ(全程只读:未 ssh、未执行生产脚本、未写数据产物/R2、未切分支/commit)
> ⚠️ 时效警告:本文结论基于 19:25~20:00 的线上实测(curl R2/公仓 API)。**主机在 19:23 起已自行恢复并继续跑链**,使用前请先跑 §4.0 现场核查刷新认识,再按 §4.1 场景分支走。
> 🔁 重大修正(相对 19:24 首版状态文档):①"链死在 18:29" 不成立 —— 17:50 链是**冻住约 50 分钟后自行续跑完**(证据 §2.3);②"等待重启"不必再无条件执行 —— 是否重启已变成判断题,见 §0.2。

---

## 0. 摘要(一句话结论 + 关键事实)

**一句话:主机 18:32~19:23 经历了约 50 分钟的内存/swap 冻结(非宕机),19:23 起 systemd 排队任务与在跑进程陆续恢复;17:50 盘后链已自行跑完(墙钟 6484s,19:38:04 收尾,RC=0),R2 数据正在异步追平;默认建议今晚不重启,以现场核查 + 按需补缺为主。**

### 0.1 实测时间线(2026-10-08,北京时间;全部带来源)

| 时刻 | 事件 | 证据 |
|---|---|---|
| 15:35~15:39 | 盘中快照槽正常(overview/ad_line/notifications/intraday_snapshot 15:39 批次上线 R2) | ssd.fx8.store LM: overview 07:39:59GMT=15:39:59; notifications 07:39:53GMT; intraday_snapshot.json 07:39:52GMT |
| 16:00 | 指数补采兜底(16:35 槽)按计划 exit 0 | schedule_stats: 指数补采兜底 last_run 10-08 16:35 exit 0 |
| 16:35 | 指数补采兜底槽跑完 | 同上 |
| 17:50 | update_all(收盘全量)启动 | schedule_stats: last_run 2026-10-08 17:50 |
| ~18:01 | 新闻采集槽跑完 + 备份推送(staticdata 仓 commit efa0e539) | 公仓 commit "data backup [news-fetch] 2026-10-08_18:01" @10:01:23GMT |
| ~18:25 | 4 条 pipeline(采集+计算)完成(推定;链按序进入 export_fund_nav) | 推断依据:fund_nav 导出产物 18:29 起上传(下两行) |
| 18:29:49 | fund-nav 异步上传前段(bucket 01)上线 R2 | ssd.fx8.store/nav_bucket/01.json LM 10:29:49GMT=18:29:49 |
| 18:30:10 | **swap 100% SEVERE 告警**(监控正常发声) | 前序状态文档 + 用户收到的告警 |
| 18:32~19:23 | **冻结期**:sshd 无响应、18:45 新闻槽静默、心跳缺失、nav_bucket 上传与 update_all 全链停摆 | 18:45 news 无备份 commit;nav_bucket 02~5f 桶在 19:25 前无新上传 |
| 19:23 | **恢复开始**:两融 19:15 槽(排队)实际跑完 exit 0;策略实验室 19:00 槽(排队)实际启动 | schedule_stats: 两融 last_run 19:23 exit 0;策略实验室 last_run 19:23(exit=None=仍在跑) |
| 19:25:05 | 新闻采集恢复(19:25 槽跑完+备份) | staticdata commit 1807bb26b @11:25:05GMT |
| 19:25~19:36:47 | fund-nav 异步上传**续传并跑完**(256 桶全部上线) | nav_bucket/60.json LM 19:26:12、nav_bucket/ff.json LM 11:36:47GMT=19:36:47 |
| ~19:30 | 龙虎榜 19:30 槽跑完 exit 0 | schedule_stats: 龙虎榜 last_run 10-08 19:30 exit 0 |
| 19:36:55 / 19:37:11 | etf_score_list_buy / hold 上线 R2 | ssd LM 11:36:55GMT / 11:37:11GMT |
| 19:38:04 | **update_all 链收尾**(17:50 起墙钟 6484s,含冻结 50min) | schedule_stats: 收盘全量 dur=6484s exit 0(6484s=17:50:00→19:38:04) |
| 19:38:18 | schedule_stats.json 推送上线 R2 | ssd LM 11:38:18GMT |
| 19:45:06 / 19:45:24 | 新闻 19:45 槽跑完 + 备份 | ssd news_digest LM 11:45:06GMT;staticdata commit bc325c4b @11:45:24GMT |
| 19:57(本文件生成时) | fund_score_top.json 内容日期=**20261008**(Top100 已是今日);R2 上 overview/boot/alert/board_etf_map 等"大盘数据通道"仍为旧版,**异步上传器追赶中未超预期**(见 §2.2) | ss.fx8.store/r2/fund_score/fund_score_top.json 内容 date=20261008;ssd LM 见 §2.2 表 |

### 0.2 现在还要不要重启?(判断题,给事实和选项)

**事实**:主机已恢复活动(19:23 起连续有任务完成:两融/新闻/龙虎榜/实验室/fund-nav 上传/etf_score 上传),17:50 链已自行跑完。**当前处于"已自愈、正在收尾"状态。**

- **默认建议(如无新告警):今晚不重启。** 现在重启会打断正在跑的任务(策略实验室 19:23 启动仍在跑、R2 异步上传器在追赶),且冻结已过去,收益小风险反大。让 20:35/20:40/22:30 等夜间任务照常跑;内存加固(§5)安排到明日安全窗口或下次维护窗口做。
- **例外 1(再冻/再告警)**:若再次收到 swap SEVERE / 无响应告警 → 立即走控制台重启,重启后按 §4.1 场景 A 执行。
- **例外 2(用户已决定必须今晚重启)**:可以重启,但选时点:避开发版/重任务分钟点(20:35 s06+盘中快照、20:40 AI 速递、21:00 回填+备份、22:00 场外基金全量、22:30 次日计划;§14 禁区精神)。重启后 100% 按 §4.1 场景 A 走(有任务会丢:策略实验室当轮、R2 异步上传器残余通道——都已给补跑命令)。
- **若重启落在明日开盘时段(09:30~15:30)**:切 §4.2 等收盘分支。

---

## 1. 盘后链路全序列(17:50 到链尾;只读梳理,行号=git 内脚本)

### 1.1 update_all 主链 20 步(`scripts/update_all.sh`;总墙钟正常 ~55min,今晚含冻结 108min)

| # | 步骤 | 命令/入口 | 产物 | 正常耗时 | 幂等/重跑风险 |
|---|---|---|---|---|---|
| 0 | 进程互斥 | `with_lock.py --nb /tmp/trade_update_all.lock`(L49-52) | 双跑自动跳过+通知 | - | 安全(重复触发=跳过) |
| 1 | 交易日闸门 | 非交易日 → 仅 deploy 补推后 exit 0(L60-76) | - | - | 幂等 |
| 2 | 4 条 pipeline 并行 | core/width/futures 前台 + stock_daily 后台死端(L85-99) | 采集入库+compute(DB) | ~35-40min | 增量采集,可重跑;慢任务大头 |
| 3 | 净值导出 | `export_fund_nav.py`(L106-108,rc 硬闸门) | `static-site/data/nav_bucket/*.json`(256 桶) | ~3-5min | 全量重算,幂等 |
| 4 | 净值镜像 rsync + **异步上传触发** | L120-140:`fund_nav_upload_async.sh`(systemd transient,独立 cgroup) | R2 `nav_bucket/`(今晚已完成 19:36:47) | 上传后台 ~10min | 幂等(md5 指纹+checkpoint);锁 `/tmp/trade_fund_nav_upload.lock` |
| 5 | **统一 deploy** | `deploy.sh all`(L151-159,失败不阻塞但 SEVERE) | 见 §1.3(整段 1+段 2) | ~10-25min | 见 §1.3;幂等 |
| 6 | 信号检查 | `check_signals.sh`(L163) | 信号邮件(按 signal_notified.json 当日去重) | ~1-2min | 去重键=日期+index_id+signal,重跑不重发 |
| 7 | 盘中快照顺带刷新 | `intraday_snapshot.sh`(L171,槽外应为快跳过) | intraday_snapshot.json(槽外不写) | 秒级 | 槽门控,重跑安全 |
| 8 | 高位/低位预警 | `export_alert.py`(L177) | `alert.json` | 秒级-1min | 纯导出,重跑安全 |
| 9 | 预警分析 | `export_alert_analyze.py`(L183) | `alert_analyze_{iid}.json`(约40个) | ~1min | 纯导出,重跑安全 |
| 10 | ETF 评分三大榜 | `export_etf_score_list.py --full-market` +rsync+upload(L191,今晚 19:36:55 已上线) | `etf_score_list_buy/sell/hold.json` | ~2-5min | 纯导出+上传,重跑安全 |
| 11 | 通知面板 | `export_notifications.py`(L218) | `notifications.json` | 秒级 | 纯导出,重跑安全 |
| 12 | 场外基金 stage0 | `public_fund_full.sh stage0-daily`(L225) | 场外库(fund_basic/净值等) | ~数分钟 | 增量,重跑安全 |
| 13 | 场外评分 | `compute_all_scores.py --top_n 2000` + `export_fund_score.py` + upload(L232-247) | `fund_score.json`/`fund_score_top.json`(今日 date=20261008 已上线) | ~数分钟 | 重算+幂等上传 |
| 14 | 数据时效断言 | L262-294:overview.date 与最近交易日一致、intraday_snapshot 日期一致 | 失败→SEVERE 告警 | 秒级 | - |
| 15 | 汇总通知 | L296-359:耗时/各 rc 汇总(SEVERE 判据含 deploy rc/fund_nav rc/score rc/rsync rc/时效) | 告警邮件 | 秒级 | - |
| 16 | 收盘邮件 | `daily_summary_email.py --mode main`(L366) | **用户邮箱「收盘全量」邮件**(今晚推定 19:37-38 已发,请核收件箱) | 秒级 | 重跑会再发,非必要不重跑 |
| 17 | 统计刷新 | `gen_schedule_stats.py`(L389) + `push_schedule_stats.sh`(L393) | schedule_stats.json(19:38:18 已上线) | 秒级 | 幂等,重跑安全 |
| 18 | 退出码 | `exit RC_CORE`(L396,**只反映 core pipeline rc**,deploy 失败不体现在这) | - | - | - |

> 判读要点:**last_exit=0 ≠ 全链每一步都成功**。deploy/尾部步骤失败只进"汇总通知"(告警邮件+SEVERE 行),不进退出码。所以"deploy 是否成功"要靠 §4.4 的 R2 验收 + 邮箱邮件正文核。

### 1.2 17:50 之后的夜间定时任务(全部云上 systemd timer;41 个 trade-* 单元均为 `Persistent=true`——错过会在系统可用后补跑,今晚 19:23 两融/实验室的"迟到执行"就是这个机制)

| 时点 | 任务(unit/脚本) | 产物/作用 | 今晚状态(20:00 视角) |
|---|---|---|---|
| 18:10 | fapi_daily_syn.sh | 期货 API 日同步 | 未知(未测;通常与链并行) |
| 18:30 / 19:30 | lhb_backfill.sh | 龙虎榜回填 | 19:30 槽 exit 0(18:30 槽被冻结吞掉,19:30 已兜) |
| 19:00 | update_lab.sh | 策略实验室(长任务,ExitTimeOut 7200) | **19:23 启动仍在跑**(exit=None);其末尾会刷 schedule_stats+trade_sim/lab R2 |
| 19:15 | rzhb_backfill.sh | 两融回填 | 19:23 跑完 exit 0 |
| 20:05 / 21:00 | futures_backfill.sh | 期货机构持仓回填 | 20:05 槽即将到点 |
| 20:07 / 21:30 | etf_national_team_backfill.sh | ETF 汪汪队 | last_run 还停在 09-30(节后首日,待今晚槽) |
| 20:30 | daily_summary_email --mode supplement | 收盘邮件补充 | 待跑 |
| 20:35 | **intraday_snapshot.sh(当日最终轮 FINAL_DAY_RUN)** | overview/ad_line/notifications/intraday_snapshot **重新导出+上传**(这是盘后这些展示位的主要刷新点) | 待跑(关键) |
| 20:35 | s06_snapshot.sh | `kelly_mode_s06_state.json`(当前 coverage_end 停在 20260930) | 待跑(关键:跑完 coverage_end 应=20261008) |
| 20:40 | run_daily_brief.sh --multi | AI 每日速递(deepseek 官方 API,低谷价) | 待跑 |
| 20:45 | brief_push_wrapper.sh | 速递推送 | 待跑 |
| 21:00 | backfill_metrics.sh | 指数/direct 指标兜底(内部可能触发 deploy) | 待跑 |
| 21:00 | backup_db.sh | DB 备份(保留 7 天) | 待跑 |
| 21:10 | turnover_backfill.sh | 换手率延后补 | 待跑 |
| 21:15 | run_ab_direction_anchor.sh | A/B 方向锚 | 待跑 |
| 21:40 | overfit_monitor.sh(一~五) | 过拟合监控 | 待跑 |
| 22:00 | public_fund_full.sh(全量,ExitTimeOut 21600) | 场外基金全量 | 待跑(重) |
| 22:30 | nextday_plan.sh(一~五) | `nextday_plan.json`(次日买入计划;当前内容=09-30 生成、next_trading_day=20261008) | 待跑(关键:跑完 date 应=20261008,next=20261009) |
| 22:35 | check_data_gap_alerts.sh(一~五) | 数据缺口检测 | 待跑 |
| 23:20 | check_r2_consistency.sh | 三站一致性巡检 | 待跑 |
| :01/:45 | fetch_news | 新闻(19:45 已正常) | 正常 |
| :07/:22/:37/:52 | self_heal.sh | 自愈巡逻 | 正常(推定) |
| :00/:15/:30/:45 | schedule_monitor.sh | 看板/告警(含资源维度) | 正常(推定) |

### 1.3 deploy.sh all 一段/二段要点(#149 两段式;细节行号见脚本)

- **段 1(锁外,并发友好)**:时段闸门(09:30-15:30 盘中拒跑 exit 1,L142-156)→ gen_etf_index_map+build_board_etf_map(失败降级 SKIP_MAP_SYNC)→ `export.py --incremental`(全量数据 JSON 导出;前端各展示位数据从这出来)→ 数据完整性/任务状态/宇宙对齐/键对齐/过拟合/双源/版本一致性等一串机检(FAIL 阻断)→ gen_rss.py(feed.xml)→ build_min.py → rsync 静态 JSON/DB 到 GIT_REPO → **触发 R2 异步上传器**(systemd-run `r2-upload-HHMMSS` → `r2_upload_async.sh`,17 通道,见下)→ check_version_progress(机制A/B,FAIL 阻断)。
- **段 2(锁内 `/tmp/trade_deploy.lock`)**:git add 6 个 min 产物 → **有变更才 commit+push**(分支必须=main)。今晚代码无变更 → 无 commit 属正常,**"没有新 commit"≠"deploy 没跑"**。
- **R2 异步上传器 17 通道顺序**(`r2_upload_async.sh` L200+):lab → trade-sim → trade-sim-json → index → etf-hist → accum-nav → industry → public-fund → etf-score(19:36:55 已见)→ data-large → kelly-parts → kelly-parts-sdc → **all-data**(overview/boot/alert/notifications 等大盘数据在这条,排第 13)→ kelly-snapshots → feed(第 15)。**这解释了为什么 20:00 时 overview 等还是旧版:通道未轮到,不是必然故障。**对空转/卡死的判别见 §4.0。
- 失败链:段 1 任一机检 FAIL 会阻断 deploy(update_all 记 SEVERE 但不中断后续步骤);上传器有 stall 看门狗(滞留 900s 判停滞;硬上限 7200s)。

---

## 2. 断点定位(截至 20:00 实测;结论:链没死,冻结段+自愈段已厘清)

### 2.1 冻结边界(精确定位)

- **冻结发生点**:update_all 第 3~4 步之间(export_fund_nav 已完成、fund-nav 异步上传刚触发),约 18:30-18:32。证据:nav_bucket/01.json 18:29:49 上线(冻结前最后一笔),之后所有产物停更。
- **冻结期**:~18:32 → ~19:23(约 50 分钟;sshd 无响应、18:45 新闻槽静默、无任何数据产物更新)。**注意:不是宕机** —— ping/TCP22/banner 可用,进程没死,内存压力缓解后自行恢复。
- **自愈段**(19:23 → 19:45):systemd 排队任务补跑(两融 19:23、实验室 19:23、龙虎榜 19:30、新闻 19:25/19:45)+ fund-nav 上传续传完成(19:36:47)+ update_all 链主体续跑并收尾(19:38:04,RC=0)。
- **当前状态(20:00)**:链已跑完;**R2 异步上传器(17 通道)仍在追赶**——大盘数据通道(all-data,排第 13)未轮到,属正常排队,不是故障(判别法见 §2.2)。

### 2.2 已更新 / 未更新产物清单(截至 19:57 实测证据)

**已更新(10-08 新数据):**

| 产物 | 状态 | 证据 |
|---|---|---|
| DB 采集+计算(4 pipeline 产物) | 完成 | update_all 链走到尾(19:38);两融/龙虎榜等回填 exit 0 |
| R2 `nav_bucket/*.json`(256 桶,含今日净值) | **完成** | 01.json LM 18:29:49(BJ)→ 60.json 19:26:12 → ff.json 19:36:47(BJ) |
| R2 `etf_score_list_buy/hold.json` | 完成 | LM 11:36:55GMT / 11:37:11GMT(=19:36:55/19:37:11 BJ) |
| R2 `fund_score_top.json`(场外基金 Top100) | 完成 | **内容 date=20261008**,n=100 |
| R2 `schedule_stats.json` | 完成 | LM 11:38:18GMT(=19:38:18 BJ) |
| R2 `news_digest.json` + staticdata 新闻备份 | 完成 | LM 11:45:06GMT;公仓 commit "news-fetch 19:45" |
| 本地(REPO/GIT_REPO 内,推定) | 推定完成 | alert/notifications/fund_score 等本地产物由链尾步骤重写(待 R2 追平或邮件核 rc) |

**未更新(R2 仍旧版;随通道追赶/夜间任务陆续刷新):**

| 产物 | 当前线上版本 | 预期刷新途径 / 期限 |
|---|---|---|
| `overview.json` / `boot.json` / `ad_line.json` / `notifications.json` / `intraday_snapshot.json` | 15:39 批次(内容 date=20261008,`collected_at`=15:35:52,即盘中快照版) | ①deploy 的 all-data 通道(异步,~20:0x-20:40)或 ②20:35 当日最终轮快照(兜底)**。20:40 后仍 15:39 版才需动作** |
| `alert.json` / `alert_analyze_*.json` | 10-07 02:2x 批次,**内容 date=20260930** | all-data 通道;若 deploy 未成功则跑 `export_alert.py`+`export_alert_analyze.py`(§4.3) |
| `board_etf_map.json` | 10-07 02:2x 批次(09-30 态) | deploy 的 export 产物 → all-data 通道;或补跑 deploy |
| `kelly_mode_s06_state.json` | 10-07 批次,**coverage_end=20260930** | **20:35 `s06_snapshot.sh`**(到期仍 09-30 才需动作) |
| `nextday_plan.json` | 09-30 生成(next_trading_day=20261008,属节前生成的合法态) | **22:30 `nextday_plan.sh`**(跑完 date 应=20261008) |
| `signal_kelly_trades*` / `signal_kelly_snapshots/index.json` | 10-07 02:32 / 10-07 21:28 | 21:00 回填触发 deploy + kelly-parts 通道 |
| `feed.xml` | 10-07 21:28 | deploy 的 feed 通道(排最后)+ 21:00 回填 |
| 策略实验室 lab_*/trade_sim 数据 | 19:23 启动的实验室任务**仍在跑** | 其末尾自行上传;不必人工动 |

> ⚠️ 读 LM 的两个坑:①R2 上传是 md5 增量,**内容不变不会重传,LM 不动≠没跑**;②`ss.fx8.store/r2/...`(CF Worker 路由)不透出 Last-Modified,判版本用**内容里的日期字段**;`ssd.fx8.store/data/...` 直连 R2 才有 LM 头。

### 2.3 "deploy 这一步到底成功没有"的判别树(20:00 时点未决,按此收敛)

1. **查邮箱(首选,强证据)**:用户是否收到 **19:37-38 的「收盘全量」邮件**?
   - 收到 + 正文无 SEVERE 行 → deploy/尾部各步按判据通过,只需等 R2 追平;
   - 收到 + 含 SEVERE 行 → 按行定位失败步骤 → §4.3 单独补跑该步;
   - 完全没收到 → 查垃圾箱;仍无 → 按"链尾邮件未发"处理(§4.3 补 check_signals/提醒核查)。
2. **查 R2 追平(次选)**:20:15~20:40 之间轮播 §4.4 表;若 `overview.json` LM 仍=15:39 且 20:35 最终轮后依旧 → 疑 deploy 导出未上线 → 走 §4.3-①(重跑 deploy all)。
3. **ssh 现场(可选,有人工权限时)**:`pgrep -af "update_all|deploy.sh|r2_upload_async"` + `ls -t /home/ubuntu/code/trade-data/data/logs/ | head -30` → 直接看 18:30 那趟 deploy 日志尾部。

---

## 3. 一致性风险判定(§22:多展示位必须一致)

**结论:存在三层混搭(10-08 盘中态 / 10-08 尾盘态(R2 追赶中) / 09-30 节前态),其中 2 个用户可见不一致点需要关注;大部分会在今晚 20:35~22:30 自愈。**

### 3.1 实测混搭表(20:00)

| 展示位/数据 | 内容日期 | 版本时点 | 一致性判定 |
|---|---|---|---|
| 首页 overview/boot/summary | 20261008 | 15:35 盘中快照版 | ✅ 日期与今日一致(盘中态) |
| 首页 alert(预警条) | **20260930** | 09-30 18:37 生成 | ❌ **与同屏 overview(10-08)混搭**;当前 high/low 均 triggered=false,**预警条不显示**——表面看不出问题,但等于用节前判定覆盖今日 |
| 首页 ad_line 情绪线 | 20261008 | 15:35 版 | ✅(盘中态) |
| notifications 通知面板 | 20261008 | 15:38 版 | ✅(盘中态) |
| ETF 页 board_etf_map(跟踪分/板图) | **20260930** | 10-07 02:2x 批 | ❌ **与"今日"数据并存的第二处不一致**(若用户今天打开 ETF 页,看到的是节前跟踪分) |
| S06 动态状态页 kelly_mode_s06_state | coverage_end=**20260930** | 10-07 批 | ❌ 显示停留在节前(20:35 应自愈) |
| nextday_plan 次日计划 | date=20260930(面向 20261008) | 10-07 批 | ⚠️ 中性:节前生成、面向今日开盘,属合法态;22:30 换新 |
| signal_kelly 各页 | 10-07 上传批 | 10-07 | ⚠️ 待核(未解析末笔成交日;21:00 链会刷) |
| nav_bucket 基金净值弹窗 | **20261008** | 今晚已上线 | ✅ |
| 场外基金评分 | **20261008** | 今晚已上线 | ✅ |

### 3.2 需要用户知情的两点

1. **首页预警条 + ETF 跟踪分是当前仅有的两处"节前旧态"**:它们不影响"今日大盘数据正确性",但会影响"今日预警/跟踪分参考价值"。自愈路径:alert/board_etf_map 走 deploy 的 all-data 通道或 21:00 回填触发 deploy;断网到 21:30 后仍未刷新 → §4.3 补跑。
2. **预警条"不显示"≠"无预警"**:09-30 版判定 high/low 均未触发,视觉上空白;若今日实际触发了(数据已入库,新版 alert 待上线),用户会漏看 → 验收时务必核 `alert.json` 内容 date 是否翻到 20261008。

### 3.3 自愈时间表(若主机保持健康,无需人工)

- **~20:0x-20:40**:deploy 的 all-data/feed 通道追平 → overview/boot/alert/alert_analyze/board_etf_map/feed 翻新;
- **20:35**:当日最终轮快照(overview/ad_line/notifications/intraday 兜底刷新)+ s06_snapshot(coverage_end→20261008);
- **21:00**:backfill(含 deploy 触发,再兜一层);
- **22:30**:nextday_plan 翻新(date→20261008)。
- 若某位到点未翻新 → 按 §4.3 对应补跑命令处理(逐条给)。
---

## 4. 恢复/验收清单(核心交付)

### 4.0 现场核查(重启后或任何时候,只读,~5 分钟;需要 ssh)

```bash
ssh ubuntu@122.51.111.173        # key: tdsignal.pem
date; uptime; free -h; swapon --show          # 现状 + swap 水位
pgrep -af "update_all|deploy.sh|r2_upload_async|fund_nav_upload" | grep -v pgrep   # 有没有链/上传器在跑
ls -t ~/code/trade-data/data/logs/update_all_*.log | head -3
L=$(ls -t ~/code/trade-data/data/logs/update_all_*.log | head -1)
tail -25 "$L"; grep -nE "开始|结束|退出码|SEVERE|✗|⚠" "$L" | tail -40   # 今天这趟链跑到哪、rc 如何
sudo systemctl --failed --no-pager | head -40    # 冻结产生的 failed 单元(含 transient)
sudo systemctl list-timers 'trade-*' --no-pager | head -30   # 各定时器上次/下次(看 catch-up 面)
ls /tmp/trade_*.lock 2>/dev/null; ls ~/code/trade-data-signal/.git/index.lock 2>/dev/null
dmesg -T | grep -iE "oom|killed process" | tail -20   # OOM 证据(治本取证,§5)
```

**判读**:①若 `update_all` 日志有今天的"结束"行 → 今天这趟链已完成,直接跳 §4.3 只补缺;②若无"结束"行且进程不在跑 → 链死了,走 §4.1 A-2 整链补跑;③若无"结束"行但进程在跑 → 别动,等它跑完(再核 §4.3)。④注意 `Persistent=true`:主机若在某个定时任务槽位时刻是停的,**开机后 systemd 会自动补跑该任务**——重启后先等 5~10 分钟再判"缺不缺",别抢跑。

### 4.1 分支 A:主机已恢复/重启完成(复盘今晚)

- **A-1 链已跑完(最可能;今晚已成立)**:不重跑整链。动作 = ①§2.3 邮件核对;②按 §4.4 轮播验收;③缺什么补什么(§4.3);④等 20:35/22:30 夜间任务自然跑。
- **A-2 链死了(日志无结束行)**:整链补跑(推荐用 unit,环境与生产完全一致):
  ```bash
  cd ~/code/trade-data
  sudo systemctl start trade-update-all.service     # 日志: data/logs/update_all_*.log;耗时 55~110min
  # 手动等价(不推荐,仅无 unit 时):
  # REPO=/home/ubuntu/code/trade-data GIT_REPO=/home/ubuntu/code/trade-data-signal \
  #   MAIN_REPO=/home/ubuntu/code/trade-data bash scripts/update_all.sh
  ```
  幂等:锁(`/tmp/trade_update_all.lock`)防双跑;采集增量;邮件按 `signal_notified.json` 当日去重(不会重复发信号邮件;收盘邮件会重发一封,可接受)。**跑之前确认没有旧链在跑**(pgrep)。
- **A-3 链跑完但个别产物缺/旧**:按 §4.3 逐项补,不要整链重跑。

### 4.2 分支 B:重启落在盘中(交易日 09:30-15:30)—— 等收盘

1. **盘中一律不跑**:`update_all.sh` 整链、`deploy.sh`(盘中闸门会拒 export+deploy,exit 1)、全量 export。
2. 现场只做 §4.0 只读核查 + 让 systemd catch-up 自跑(采集类任务盘中补跑影响可控)。
3. **等 15:30 收盘后**再执行补跑:优先让 **15:35 快照槽**与 **17:50 收盘链**自然跑;若当日 17:50 前需要手工补前一日(或今日)缺口,选 **15:40~17:40** 窗口(避开 15:35 快照、16:00/16:35 补采槽的分钟点),且 §14 禁区时点(15:35/16:00/17:50/20:35/22:00)前后几分钟不启动重任务。
4. 次日 17:50 链跑完后按 §4.4 验收双日数据。

### 4.3 单点补跑表(缺哪补哪;全部在云上 `~/code/trade-data` 下执行)

| 缺什么(判据见 §4.4) | 补跑命令 | 幂等性/风险 | 备注 |
|---|---|---|---|
| deploy 产物未上线(overview/board_etf_map/alert 等 R2 未翻新,或邮件报 deploy rc≠0) | `bash scripts/deploy.sh all` | 幂等;export 增量、机检 FAIL 会阻断(修因再跑);~10-25min | 会重触发 R2 异步上传器(17 通道) |
| 本地产物已新、只是 R2 落后(异步上传器未跑完/被重启打断) | `bash scripts/r2_upload_async.sh` | 幂等(md5 增量+断点);锁 `/tmp/trade_r2_upload_async.lock`(--block-timeout 600) | 覆盖全部 17 通道,含 all-data(overview/boot/alert/board_etf_map)、feed |
| overview/boot/notifications/intraday_snapshot 等"盘中五件"仍旧版 | 优先等 **20:35 当日最终轮**;它若被错过,重启后 Persistent 会自动补跑;手动重跑 `bash scripts/intraday_snapshot.sh`(云上自带 REPO env) | 槽位语义,重跑安全(upload-intraday 秒级) | 这五个文件的常规刷新点就是 15:35/20:35 |
| `alert.json`/`alert_analyze_*.json` 内容 date 仍=20260930 | `python scripts/export_alert.py && python scripts/export_alert_analyze.py` 然后 `python scripts/upload_r2.py upload-all-data`(或等 r2_upload_async.sh) | 纯导出+上传,重跑安全 | update_all 专属产物,deploy 不带 |
| `kelly_mode_s06_state.json` coverage_end 仍=20260930(>20:40 时点) | `bash scripts/s06_snapshot.sh` | 幂等(每日重生) | 20:35 定时任务为主 |
| `nextday_plan.json` date 仍=20260930(>22:35 时点) | `bash scripts/nextday_plan.sh` | 幂等 | 22:30 定时任务为主;注意上次运行 exit=1 历史,跑完看日志 |
| 信号邮件缺失/可疑 | `bash scripts/check_signals.sh` | 当日去重键(signal_notified.json),重跑不重发已发信号 | 邮件发送量核对用 |
| schedule_stats 旧 | `python scripts/gen_schedule_stats.py && bash scripts/push_schedule_stats.sh` | 幂等 | 通常链尾/各任务自动刷 |

### 4.4 验收判据表(curl;`UA="Mozilla/5.0 (Macintosh…Chrome/125.0 Safari/537.36"`,全部 `--max-time 20 -sL -A "$UA"`,禁 -v/-i)

| # | 检查 | 命令(要点) | 期望值 | 期限 |
|---|---|---|---|---|
| 1 | 首页大盘 | `curl -sD- -o /tmp/ov.json ssd.fx8.store/data/overview.json` → 内容 `date`,`collected_at` | date=20261008;**collected_at ≥ 19:25**(追平)或 ≥20:35(最终轮) | 20:40 后仍 15:35 → 补跑 |
| 2 | 预警 | 同法取 `alert.json` 内容 `date` | **date=20261008** | 21:30 后仍 20260930 → §4.3 |
| 3 | 板图跟踪分 | `board_etf_map.json` 的 Last-Modified(ssd) | LM ≥ 今日 19:2x | 21:30 |
| 4 | S06 状态 | `kelly_mode_s06_state.json` 的 `coverage_end` | =20261008 | 20:50 |
| 5 | 次日计划 | `nextday_plan.json` 的 `date`/`next_trading_day` | =20261008 / 20261009 | 22:50 |
| 6 | 净值桶 | `nav_bucket/ff.json`(ssd 根路径)LM | ≥ 11:36:47GMT(19:36:47 BJ) | 已达 ✅ |
| 7 | ETF 评分 | `etf_score_list_buy.json` LM | ≥ 11:36:55GMT | 已达 ✅(sell 待首次验收时一并看) |
| 8 | 场外评分 | `r2/fund_score/fund_score_top.json`(ss.fx8.store)内容 `date` | =20261008 | 已达 ✅ |
| 9 | 新闻 | `news_digest.json` LM | 持续 ≥ 最新 :45/:01 槽 | 常态 |
| 10 | 统计 | `schedule_stats.json` LM | ≥ 各任务最近完成点 | 常态 |
| 11 | 邮件 | 收件箱: 19:37-38「收盘全量」、20:30 补充、20:40 AI 速递 | 按点到达;正文无 SEVERE | 各时点+15min |
| 12 | 信号凯利 | `signal_kelly_trades_parts/t2026.json` LM | ≥ 21:0x(回填+deploy 触发) | 22:00 |

> 全部 12 项通过 = 恢复闭环(§22 多展示位一致)。核心三项:**#1/#2(首页两卡)+ #11(邮件)** 是"用户视角是否恢复正常"的硬判据。

### 4.5 半成品清理(重启后一次;什么都别多删)

1. **锁文件**:`/tmp/trade_*.lock` 全是 fcntl 锁,**进程一死自动释放**,残留空文件无害,**不手删**;只确认没有对应僵尸进程(`pgrep`)。
2. **failed 单元**:`sudo systemctl reset-failed 'trade-*'`(清冻结产生的 failed 记录,尤其 transient 的 `fund-nav-upload-*`/`r2-upload-*`;单元若还在跑就别 reset)。
3. **git index.lock**:若 `~/code/trade-data-signal/.git/index.lock` 残留(冻结时 git 被杀)→ 确认无 git 进程后 `rm` 之,否则后续 deploy 段 2 会卡。
4. **不用清的**:R2 checkpoint/state(`.r2_*_ckpt.json`/`.r2_*_state.json`)—— 幂等自愈;`/tmp/trade_deploy.lock` 若有残留同上(无进程即无害)。
5. 清空本次无关:**不做 `git gc`/清日志集/清缓存**等额外动作(§25 删除铁律:非必要不删)。

---

## 5. 内存/swap 治本建议(只建议,不执行;依据=18:30:10 swap 100% SEVERE + 50 分钟冻结)

### 5.1 现场取证(定了性再动手;下次上线做)

- `dmesg -T | grep -iE "oom|killed process"` + `journalctl -k --since "18:20" --until "19:30"` → 有没有 OOM kill 谁;
- `cat /proc/pressure/memory`(PSI: some/full 的 avg10/60 在 18:30 前后的水位);
- `free -h; swapon --show`(现状)+ `vmstat 1 5`(si/so 是否仍在换页);
- 复盘期用 `journalctl --since "17:50" --until "19:30"` 找 RSS 峰值大户(或下次链跑时 `ps -eo pid,rss,etime,cmd --sort=-rss | head` 定时采样)。

### 5.2 建议动作(按性价比排序;具体数值待取证后定,不在本单拍板)

1. **扩 swap(立即可做)**:现 2G 档小内存机加 2~4G swapfile(`fallocate`+`mkswap`+`swapon`,写入 `/etc/fstab` 持久化),并把 `vm.swappiness` 调到 10~20(减少无谓换出)。防"再冻",不解决根本。
2. **升配内存(最治本)**:2C2G → 2C4G 一档,评估月成本后拍板;17:50 链(4 pipeline 并发 + 导出 + R2 上传并存)对 2G 机型偏紧。
3. **链内限流/错峰(如需)**:
   - 给 `trade-update-all.service` 加 **MemoryHigh(软限)** 兜底降速,**慎用 MemoryMax**(硬杀=半成品,是比冻结更糟的形态);
   - 可选:fund-nav 上传并发线程数下调、pipeline 并行度 4→3(先用数据证明内存峰值再动);
   - 评估 R2 异步上传与 17:50 采集重叠窗口的内存叠加(今晚链条印证:上传器与链并存)。
4. **监控增强**:保留现有 swap 100% SEVERE;补 ①swap 高水位持续(如 >85% 持续 10min)②si/so 持续非零③OOM-killer 事件(内核日志旁路)④心跳双拍缺失 告警(本次 18:45 静默靠人工发现,**需机检**)。资源维度监控已于 2026-10-05 上线(见 memory),核对它今晚是否发了 swap 告警链即可。
5. **结构性观察**:节后首日(今日)数据量大、16:35 指数补采+17:50 全链+18:10 期货+18:30 龙虎榜等密度高,建议观察 1~2 周同类峰值的 swap/PSI 曲线再定配置档。

---

## 6. 未测项与残留(诚实标注)

- **未测**:①云上进程/日志实况(本任务禁 ssh)②deploy 段 1/2 的 rc(靠 §2.3 邮件+R2 判别树收敛)③`signal_kelly_trades_parts/t2026.json` 体积 74MB 未解析末笔成交日(只记 LM)④`etf_score_list_sell.json` 未单独探 LM⑤18:10 fapi/18:30 龙虎榜首槽/20:05 后任务的实际 rc(时点未到或未核)⑥邮件是否真到达(需用户核收件箱)。
- **活跃后台任务**:无(本次调研全程 `--max-time`/显式 timeout,无 `moved to the background` 残留)。
- **对读者**:本文 20:00 前所有结论均为实测(URL+LM/内容字段见正文);20:00 后状态请按 §4 清单重新验收,勿直接引用本文"当前状态"描述。

## 附录 A:本次实测证据索引(20:00 前)

- `ssd.fx8.store/data/overview.json` LM=Thu 08 Oct 2026 07:39:59 GMT(15:39:59 BJ),内容 date=20261008 collected_at=20261008 15:35:52
- `.../ad_line.json` LM=07:39:45GMT;内容末点 date=20261008(250 点)
- `.../alert.json` LM=Tue 06 Oct 2026 18:27:47 GMT(10-07 02:27:47 BJ),内容 date=20260930 generated_at=2026-09-30 18:37:24
- `.../alert_analyze_hs300.json` LM=06 Oct 18:27:53GMT
- `.../board_etf_map.json` LM=06 Oct 18:28:06GMT
- `.../kelly_mode_s06_state.json` LM=06 Oct 18:28:09GMT,内容 coverage_end=20260930
- `.../nextday_plan.json` LM=06 Oct 18:28:10GMT,内容 date=20260930 next_trading_day=20261008
- `.../news_digest.json` LM=08 Oct 11:45:06GMT(19:45:06 BJ),内容 date=2026-10-08
- `.../notifications.json` LM=07:39:53GMT,内容 date=20261008 generated_at=2026-10-08 15:38:40
- `.../boot.json` LM=07:39:54GMT,内容 overview.date=20261008 + alert.date=20260930(同屏混搭实锤)
- `.../intraday_snapshot.json` LM=07:39:52GMT
- `.../feed.xml` LM=Wed 07 Oct 2026 13:28:10 GMT(10-07 21:28:10 BJ)
- `.../signal_kelly_snapshots/index.json` LM=07 Oct 13:28:01GMT,updated_at=2026-10-07 21:12
- `.../signal_kelly_trades_parts/t2026.json` LM=06 Oct 18:32:04GMT(10-07 02:32:04 BJ)
- `.../data/etf_score_list_buy.json` LM=08 Oct 11:36:55GMT;`..._hold.json` LM=08 Oct 11:37:11GMT(更新 ✅)
- `.../data/schedule_stats.json` LM=08 Oct 11:38:18GMT;内容:update_all last_run 10-08 17:50 dur=6484s exit=0;两融 19:23 exit0;龙虎榜 19:30 exit0;策略实验室 19:23 在跑;新闻 19:25 在跑
- `ssd.fx8.store/nav_bucket/01.json` LM=08 Oct 10:29:49GMT;`.../60.json` LM=11:26:12GMT;`.../ff.json` LM=11:36:47GMT(文件名 00-ff,全 256 桶;ss.fx8.store/r2/ 路由拿到但无 LM 头,用 ssd 根路径才有)
- `ss.fx8.store/r2/fund_score/fund_score_top.json` 内容 date=20261008 count=100(Workers 路由无 LM 头)
- GitHub `xp13465/trade-data-signal-staticdata` commits:news-fetch 18:01(efa0e539)/19:25(1807bb26b)/19:45(bc325c4b),intraday 15:17/15:40;`xp13465/trade-data-signal` 今日最新 commit 05:06Z(本机提交,云上无 19:3x 新 push——因 min 无变更不 commit,属正常)
- 4 pipeline 采集完成、冻结边界、恢复时刻等:见 §0.1/§2.1 与 schedule_stats 行

## 附录 B:与 19:24 首版状态文档(`postclose-1008-state-20261008.md`)的差异对账

1. "链死在 18:29:49" → **修正**:链未死,冻结 ~50min 后自行续跑完(19:38:04,RC=0)。
2. "等用户重启再恢复" → **修正**:主机 19:23 起已自愈;是否重启变判断题(§0.2,默认不重启)。
3. "最后成功=nav_bucket 18:29:49" → **补充**:fund-nav 上传 19:25 续传、19:36:47 全部完成(ff.json 实锤);无需再担心净值数据缺失。
4. 其余冻结时间线/重启建议(VNC 优先等)与本文不冲突;以本文为准。
