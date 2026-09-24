# r2_skip_alert 告警分诊(2026-09-24)

## 一句话结论
**噪音(对该条 overfit_monitor 实例)**:`overfit_monitor|r2_skip_alert` 是「r2_skip_count 窗口滞留 × monitor 跨轮计数」对**每日一轮低频任务**的语义误配产生的必然误报。单次良性锁竞争(SKIPPED_LOCKED)被放大成「连续 4 轮上传缺口持续」,且会挂 24h 直到次日 21:40 新一轮打点才恢复。数据缺口真实但轻微(overfit_monitor.json 滞后一天,deploy 日链兜底)。

## 6 条问题逐条证据

### 1. overfit_monitor 到底 skip 了什么?
- 云上 `overfit_monitor_launchd.log`(21:40:00 轮)首行: `[r2] SKIPPED_LOCKED: R2 上传锁忙, 本轮跳过(overfit_monitor.json 由 deploy 日链兜底)`
- 对应代码 `scripts/overfit_monitor.py:1822-1829`:`upload_r2.py --skip-if-locked upload-data-large`(overfit_monitor.json 主+ext 两文件的 R2 自传)
- **持锁者**:`etf_national_team_backfill.sh` 21:30 兜底轮(21:30:00 开始,21:48:15 结束)的 R2 上传段——`etf_national_team_backfill_20260924_2130.log` 显示 etf-hist 增量上传 1262/1710 耗时 267.2s,accum-nav per-ETF 拆分 54 keys purge,且在 21:41:22 触发 `deploy_20260924_2141.log`。21:40:00 撞锁=撞 etf 晚间兜底轮的 R2 上传窗口,同刻 `push_schedule_stats.sh` 21:40:41 也 SKIPPED_LOCKED(overfit log 尾部同证)。
- 对比:9-17/9-23 同期打点均 `overfit_monitor.json → R2 上传完成`(overfit log 241 行 9-17),**9-24 属偶发撞锁非常态**。

### 2. `--skip-if-locked` 是设计内良性重试路径吗?
- 是。语义见 `scripts/upload_r2.py:2367-2401`:`skip_if_locked` 为高频/下轮可重试通道 opt-in,拿不到锁立即打印 `SKIPPED_LOCKED` + exit 0,「跳过=本轮不传,下一轮 10min 后自然重试」;deploy 日链低频通道**不带**该 flag(排队语义不变)。
- overfit_monitor 的兜底链注释(`overfit_monitor.py:1822-1825`):「当日 R2 同步缺口由 deploy 日链 upload-data-large 兜底」,且 deploy 链 upload-data-large 含 overfit_monitor* 强制例外(L1810)。
- **但有「连续 N 轮后必须真上传成功」兜底缺失**:对每日一轮的 overfit_monitor,「下轮 10min 后重试」不成立——下一轮是**明天 21:40**。gap 最长 ~22h,唯一兜底是次日 17:50 deploy 日链。当前实现**没有**「次日 deploy 后 R2 仍非最新→告警」的判据。

### 3. 为什么是 overfit_monitor 而不是别人?
- **根因=窗口滞留**:`gen_schedule_stats.py:529` `skip_count = sum(1 for _l in window_lines if "SKIPPED_LOCKED" in _l)`——r2_skip_count 是「最近一次运行窗口内 SKIPPED_LOCKED 行数」。overfit_monitor 每日 21:40 只跑一轮(`systemctl list-timers` trade-overfit-monitor.timer 每日 21:40:00),21:40 轮 skip 后窗口滞留 1 行,`schedule_stats.json` 中该任务 `r2_skip_count` **恒=1 直到次日 21:40**(云上 22:45 快照实证:last_run=2026-09-24 21:40, r2_skip_count=1)。
- monitor 端(`schedule_monitor.sh:683-729`)把「r2_skip_count>0」当作「本轮 monitor 观察期有新 skip」逐轮 +1 → 21:45/22:00/22:15/22:30 四轮都看到同一份滞留值 → 计数 4 → 必达阈值。**单次 skip 被放大成「连续 4 轮缺口持续」**。
- 对照:fetch_news(30min/轮)中午同样触发过一次(12:00 告警→12:xx 恢复,`schedule_monitor_launchd.log:8003-8042`),因其高频,窗口滞留时间短、恢复快,该告警对高频任务有效;overfit_monitor 是唯一「撞一次锁后整天不再运行」的任务,必然误报且挂 24h。

### 4. 阈值合不合理?
- 阈值 `R2_SKIP_CONTINUOUS_THRESHOLD=3`(`schedule_monitor.sh:396`),monitor 15min/轮(`systemctl` trade-schedule-monitor.timer 22:45→23:00),连续 3 轮=45min。注释本意对齐 intraday_snapshot(10min/轮)≈连续 4-5 轮。
- **对高频任务合理,对每日一轮任务语义失效**:阈值再调高也没用——计数随 monitor 轮数**无限增长**(到次日 21:40 前约 96 轮),单次 skip 必然触发,且恢复要等次日 21:40 r2_skip_count=0 才清零。**问题不在阈值数值,在计数语义(「连续 N 轮」隐含任务高频)对低频任务失真**。

### 5. §14 判定
- **建议:保留告警机制,但修正对低频任务的计数语义;对该条告警降为不升级 SEVERE(单次 skip 由 deploy 日链兜底,不构成「缺口持续」)。**
- 理由:
  - 对高频任务(intraday_snapshot/fetch_news)该告警有效(fetch_news 中午实例真实验证了锁竞争+自愈),不能整体关。
  - 对每日一轮任务,「连续 N 轮 skip」=「单次 skip 的窗口滞留」,不是缺口持续。overfit_monitor.json 缺口最长一天且 deploy 日链兜底,SEVERE「需人工关注」与实际影响(低优先级监控数据滞后一天)不匹配。
  - 修复方向(择一):①monitor 端跳过 `last_run` 不在本轮观察期内的任务计数;②对「每日 ≤N 轮」任务,单次 skip 不升级,改为「次日 deploy 后 R2 generated_at 仍非最新」判据;③`gen_schedule_stats` 输出 r2_skip_count 时附 last_run,monitor 只对观察期内新增 skip 计数。
  - 与 §14 关系:这是**告警语义修正**(去重/聚合维度),非降频/后台暂停,不违反「通知即时性优先」。对高频任务仍即时 SEVERE。
- **顺带发现 bug**:`push_schedule_stats.sh:68-77`——upload_r2.py skip 时 exit 0,`if !` 不触发失败分支,直接打 `✓ schedule_stats.json R2 上传完成`(云上 21:40:41 日志实证 skip 后仍打 ✓)。假成功标记残留(r2-false-success-rootfix 未收口),应区分 SKIPPED_LOCKED 与真上传成功。

### 6. 响的时候数据真的没上传吗?
- **overfit_monitor.json:确实没上传**。线上 R2 `ssd.fx8.store/data/overfit_monitor.json` generated_at=**2026-09-23 21:40**(curl 实测),今天 21:40 版未上。缺口最长 ~22h,由次日 17:50 deploy 日链兜底(设计内,与 overfit_monitor.py:1810/1825 注释一致)。
- **schedule_stats.json:已由独立重试补上,无缺口**。21:40:41 那次 skip 后,`push_schedule_stats_20260924_2148.log` 21:48 重试成功(`[1/1] ✓ schedule_stats.json (6162B)`),R2 上 schedule_stats.json 已含 last_run=2026-09-24 21:40 / r2_skip_count=1(curl 实测)。
- 前端无直接展示 overfit_monitor(本地 grep app.js 无引用),真实影响更低。

## 建议动作
1. **修计数语义**(P1):对「每日一轮/低频」任务的 r2_skip_count,monitor 不做跨轮「连续 N 轮」计数(单次 skip 由 deploy 兜底),只保留高频任务(intraday_snapshot/fetch_news)的连续 N 轮 SEVERE。可选加「次日 deploy 后 R2 未更新→SEVERE」兜底判据。
2. **修 push_schedule_stats.sh 假成功标记**(P2):skip 时输出「已跳过(下轮重试)」而非「✓ 上传完成」。
3. 本条已挂告警会在**次日 21:40** overfit_monitor 新一轮打点(r2_skip_count=0)后由恢复循环自动恢复,无需手工干预。

## 证据文件清单
- `scripts/schedule_monitor.sh:392-396`(阈值 3)+ `:673-729`(消费逻辑)
- `scripts/gen_schedule_stats.py:527-529`(r2_skip_count 窗口滞留计数)+ `:910/:933`
- `scripts/upload_r2.py:2367-2432`(--skip-if-locked 语义 + SKIPPED_LOCKED 哨兵)
- `scripts/overfit_monitor.py:1809-1835`(撞锁打点自传 + deploy 兜底注释)
- `scripts/push_schedule_stats.sh:62-77`(skip 后仍打 ✓ 假成功)
- 云上:overfit_monitor_launchd.log(21:40 轮 SKIPPED_LOCKED)、etf_national_team_backfill_20260924_2130.log(21:30-21:48, etf-hist 267s)、deploy_20260924_2141.log(21:41:22)、push_schedule_stats_20260924_2140/2148.log(skip→重试成功)、schedule_monitor_launchd.log(8003-8054 计数链)、schedule_stats.json(r2_skip_count=1 滞留)
- R2 curl:ssd.fx8.store/data/overfit_monitor.json(generated_at=2026-09-23 21:40)、schedule_stats.json(21:40 版在位)
