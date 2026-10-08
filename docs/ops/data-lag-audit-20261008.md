# 2026-10-08 数据产物滞后面盘点(只读快速核查)

- 落档时间:2026-10-09 00:35(北京时间,以下均为 BJ 时间;命令与字段值均为本机/云上实测)
- 执行角色:调研 agent(全程只读:未启停/触发任何 unit、未跑任何业务脚本、未写 R2、未产生真实外发)
- 数据基准:只读排查,不涉回测口径(测试基准不适用)
- 关联文档:`docs/ops/deploy-integrity-selflock-20261008.md`(自锁背景,直接采信)、`docs/ops/postclose-1008-state-20261008.md`、`docs/ops/cloud-recovery-runbook-20261008.md`

## 0. 结论速览(先读这个)

1. **"停 09-30"= 国庆长假节前最后交易日(09-30 之后 10-01~10-07 无交易日,10-08 是节后首日)**,不是"数据没生成"。10-08 02:06 首轮 deploy 被拦的 6 个 fail(alert/notifications/ad_line/a_stock/accum_nav_map_fresh/s06_state,"滞后 8 天 > 7 天")是**长假后首日自然日阈值边界误伤**(5 项为假 FAIL,当日白天已被各自独立链追平)+ **alert 自锁**(唯一上传通道=deploy 自身,被 FAIL 卡死后死锁)。
2. **截至 00:1x,R2 上仍有 14 项产物停 10-07 版**(附录 A 表),全部走 deploy-only 的 upload-all-data 通道;**R2 上传已于 00:22:08 由自愈链启动并在跑**(见 §3),完成后这 14 项即追平。
3. **自愈链(self-heal)已在 00:07 自动代跑了 backfill→deploy→R2 上传**:两段式 deploy 00:13:54 段1 → 00:22:39 段2 结束退出码 0,push 成功;**结论:不需要(且不要)今晚手动补跑**——手动跑只会与正在跑的上传/backfill 撞车。
4. **02:00 backfill 链 = 兜底**(代码证据见 §4):补到新数据即触发**完整 deploy**(非只推指数);近 5 个槽位(10-06/10-07/10-08 02:00 + 10-08 16:35/21:00)全部触发了 deploy。
5. **风险提示:10-09 自愈额度已用完**(每日 3 次上限,00:07×2 + 00:22×1),今日若再出故障不会再自动 heal,需人工介入(§3.4)。

## 1. 方法与口径(三层对比)

| 层 | 位置 | 实测状态 |
|---|---|---|
| 本地(mac,参照) | `/Users/linhuichen/code/trade/static-site/data` | 已 git 移出(7d086b1b2),非权威,仅作 md5 参照 |
| 云上 REPO(生成层) | `ubuntu@122.51.111.173:/home/ubuntu/code/trade-data/static-site/data` | 10-08 版(00:13 deploy 段1 export 重写,00:17-00:19 文件 mtime) |
| 云上 GIT_REPO(deploy 段1 rsync 目标) | `/home/ubuntu/code/trade-data-signal` | 曾停 10-07 21:11;**00:22 由自愈 deploy 的 rsync 修复** |
| R2/线上(用户可见) | `ssd.fx8.store`(R2 直连;线上站点同源) | 122 项逐文件实测:FRESH 108 / **STALE 14**(00:1x);00:22 上传进行中 |

- R2 实测方法:对 122 个候选文件逐一 `curl -sI -H "User-Agent: Mozilla/5.0" https://ssd.fx8.store/data/<file>` 取 ETag(=R2 对象 md5)+ Last-Modified;与云上 REPO 当前文件 md5 逐位对比,不等=滞后。
- 变更检测三方证据(证明"00:22 的上传必带这 14 项"):`.r2_all_data_state.json` 里 14 项的登记 md5 **== R2 当前 ETag**(state 与 R2 同步),而云上文件当前 md5 **≠ state**,即下次 upload-all-data 必检出 changed 并上传。
- 以下命令均为实测原文(节选):见附录 C。

## 2. 问 1:滞后产物清单(截至 00:1x 实测)

### 2.1 仍滞后(14 项,R2 版本 vs 云上最新版 md5 不同)

| # | 文件 | R2 Last-Modified(BJ) | 通道 |
|---|---|---|---|
| 1 | board_etf_map.json | 10-07 02:28:06 | all-data |
| 2 | futures.json | 10-07 02:28:03 | all-data |
| 3 | futures_acc_conclusion.json | 10-07 02:28:00 | all-data |
| 4 | futures_acc_trend.json | 10-07 02:28:11 | all-data |
| 5 | market_tier_history.json | 10-07 02:28:11 | all-data |
| 6 | rotation.json | 10-07 02:28:10 | all-data |
| 7 | signal_freq.json | 10-07 02:28:11 | all-data |
| 8 | signal_kelly_backtest.json | 10-07 21:27:36 | all-data |
| 9 | signal_kelly_backtest_sdc.json | 10-07 21:27:34 | all-data |
| 10 | signal_stats.json | 10-07 21:27:47 | all-data |
| 11 | etf_national_team_holders.json | 10-07 21:27:30 | all-data |
| 12 | etf_national_team_quarterly.json | 10-07 21:27:28 | all-data |
| 13 | export_manifest.json | 10-07 21:27:28 | all-data |
| 14 | schedule_stats.json | 10-08 22:01:44 | all-data(注:该文件多通道,state 与 R2 亦脱节,见 §5) |

家族样本(同期滞后,同批追平):
- `signal_kelly_trades_parts/recent.json`:R2 LM 10-07 02:30:02,云上 md5 31808fa5(2,025,191B)≠ R2 etag 4f4b5f6e;`t2024.json` 同为旧版。
- `industry/industry-1y.json`:R2 LM 10-05 18:25(6,866,006B)vs 云上 6,871,749B(md5 32eebf12);`industry-3m.json` 同(R2 10-05 18:24)。
- `accum_nav/158000.json`:R2 LM 10-05 12:38(449B)vs 云上 467B(md5 3425a644)。

### 2.2 已追平(用户可见层面已新鲜,实测日期字段)

- overview date=20261008 / alert date=20261008 / notifications date=20261008 / ad_line 最后=20261008 / a-stock-3m metrics+indices 最后=20261008 / accum_nav_map 键尾=20261008 / signal_kelly_day_snapshot days 尾=20261008 / **kelly_mode_s06_state coverage_end=20261008(R2 LM 10-08 20:35:03,20:35 独立链)**。
- 70 个 `alert_analyze_*.json` + alert.json:22:40 手动定向上传(71/71),抽 4 样本 etag==云上 md5,全家族 70/70 无差异。
- a-stock 家族 1y/3m/6m、ad_line、notifications、boot、summary_history、overfit_monitor、nextday_plan、auto_trade_steps、kelly_mode_s06_state、news_digest、daily_brief 等 108 项 FRESH。
- 口径说明:上级文档提"58 条 alert_analyze 用户可见项",本轮实测 `alert_analyze_*.json` 文件数=70,22:40 上传量 71/71(=alert+70,自洽);"58"的定义未复核(见 §6 诚实标注)。

### 2.3 "停 09-30"的性质澄清(重要)

10-08 02:06 首轮 deploy 的 6 个 fail 原文(云上 `data/logs/backfill_20261008_0200.log` L177-200 与 `deploy_20261008_0206.log` L557-580):

    ✗ alert: alert.json date=20260930 滞后 8 天 > 7 天
    ✗ notifications: notifications.json date=20260930 滞后 8 天 > 7 天
    ✗ ad_line: ad_line.json 最后日期=20260930 滞后 8 天 > 7 天
    ✗ a_stock: a_amount 最后日期=20260930 滞后 8 天 > 7 天
    ✗ accum_nav_map_fresh: accum_nav_map.json 最新 nav 日期=20260930 滞后 8 天 > 7 天
    ✗ s06_state: 线上 S06 快照 coverage_end=20260930 滞后 8 天 > 7 天
    === 汇总: 34 ok / 2 warn / 6 fail ===

- 判据代码:`scripts/check_data_integrity.py` L57-58(`STALE_DAYS_WARN=3` / `STALE_DAYS_FAIL=7`,自然日 `_days_ago`)、L410-436(`check_alert`)、L2114-2185(`check_s06_state_snapshot`,含"本地新鲜≠线上新鲜"对比)。
- 09-30→10-08 跨 8 个自然日(长假 10-01~10-07 无交易日;数据佐证:`accum_nav_map/158000` 与 `signal_kelly_day_snapshot.days` 日期序列尾均为 `20260929, 20260930, 20261008`)⇒ 阈值 >7 天边界误伤。
- 6 项中 5 项(除 alert)在 10-08 白天被各自独立链追平(16:45 轮 check 为 39 ok/2 warn/1 fail,单剩 alert);**alert.json 因自锁(唯一 R2 上传通道=deploy 自身 L582)一直卡到 22:40 手动定向上传解锁**。自锁链全貌见 `docs/ops/deploy-integrity-selflock-20261008.md`(本次直接采信,未复核)。

## 3. 核心新事实:自愈链已在 00:07-00:22 自动代跑(本次实测抓到)

### 3.1 时间线(云上日志实测)

| 时刻 | 事件 | 证据 |
|---|---|---|
| 10-08 全天 | self-heal 每日 3 次已用完(20:22/20:37/20:52 全给 etf_national_team),23:22/23:37/23:52 均 "LIMIT 达上限跳过" | `data/logs/self_heal_audit.log` |
| 10-09 00:07:01 | 跨日重置;**HEAL backfill_evening(reason=log_anomaly** `last_exit=0 ... log_anomaly=True`**)** → 触发 `backfill_metrics.sh`;同时 HEAL etf_national_team(reason=exit=1) | 同上 |
| 00:07-00:13 | backfill 执行:etf_nt daily 00:09:18 / etf_nt accum-nav 00:12:07 | `backfill_20261009_0007.log` |
| 00:13:21 | index_backfill 补到新数据 → 触发 **deploy 段1**(`deploy_20261009_0013.log` 段1 00:13:54 开始) | `backfill_20261009_0007.log` L77 |
| 段1 内 | **check 汇总: 40 ok / 2 warn / 0 fail**(两遍均 0 fail)→ rsync → 触发 R2 异步上传(首次 systemd-run rc=1 失败,后成功:r2-upload-002208) | `deploy_20261009_0013.log` L1109/1265/1472-1476 |
| 00:22:24-00:22:39 | **deploy 段2**(`deploy_20261009_0022.log`):git push 成功(并发 deploy 幂等),退出码=0;附带 staticdata 备份异步(002224/002239) | `deploy_20261009_0022.log` 尾部 |
| 00:22:08- | **R2 全通道异步上传启动并在跑**(lab/trade-sim 未变;all-data/data-large/industry/accum_nav/kelly-parts 等按变更检测上传) | `r2_upload_async_20261009_002208.log`,`systemctl is-active`=active |
| 00:22:02- | self-heal 第二发 HEAL backfill_evening → `backfill_20261009_0022.log`(进行中);**并达当日上限 3 次** | `self_heal_audit.log` |

机制说明:`self_heal.sh`(云上 trade-self-heal.timer,每 15min、07/22/37/52 分)读 `schedule_stats.json` 对失败/日志异常任务做**白名单 force 重跑**(backfill_evening/update_all/etf_national_team 等),每日上限 3 次;判据含 `log_anomaly`(本次 backfill_evening 被 HEAL 的 reason=log_anomaly,即 10-08 21:00 槽 backfill 内 deploy 被拦留下的日志异常)。**正是这条链在跨日后把 10-08 遗留的 deploy 欠账自动补上了。**

### 3.2 对本任务四问的直接影响

- "要不要手动补跑":**不需要**。deploy 已完成(exit 0,push 成功,GIT_REPO 已 rsync),R2 上传正在跑;手动跑=与 r2-upload-002208 和 backfill_0022 撞车且无增量。
- 待观察(兜底验收点):R2 上传完成后,14 项 ETag 应变为云上最新 md5;若该上传失败(r2_upload_async 自带看门狗+失败告警),**02:00 链仍兜底**(§4),再往后 05:00 us-stock-morning(历史也触发 deploy)与 16:35/17:50 均为后备。

### 3.3 撞车核查(10-09 00:15 `systemctl list-timers` 实测)

- **正在跑**:r2-upload-002208(00:22:08-)、backfill_0022(00:22:02-)、staticdata-backup-002224/002239。
- **今晚剩余触发点**:pf-stage0-nav 01:43(上次 10-02,周频特征)/ backfill-evening 02:00 / gold-night 02:40 / public-fund-quarterly 03:00 / us-stock-morning 05:00 / rzhb-backfill 08:00 / intraday-snapshot 09:25 / nextday-gap-check 09:26 / kelly-intraday-rerun 09:40;16:00 pf-score-daily、16:30 pf-daily、17:50 update-all 等(次日盘后)。
- 结论:**现在(00:2x)已是"自有任务在跑"状态,任何手动 deploy 都会撞车**;若确实要人工干预,唯一合理空窗是**本轮上传/backfill 全部结束之后(约 00:3x-01:4x)且 02:00 之前**——但按 §3.2 无必要。
- §14 安全窗:00:00 后无推 main/评分/采集禁令,且当前非盘中、非盘后定时时点(15:35/16:00/17:50/20:35/22:00 均已过)。

### 3.4 风险提示(新发现)

- **10-09 自愈额度已耗尽**(state:count=3;00:07 backfill_evening、00:07 etf_national_team、00:22 backfill_evening)。此后今日若再出现任务失败/日志异常,self-heal 只会记录 LIMIT 不再重跑;若需自动修复须人工介入(或改额度)。
- 00:22 的 HEAL 是为"log_anomaly 尚存"而发的第二发 force(backfill_0022),它可能再触发一轮 deploy(若又补到新数据)——与上传/mutex 并发,属正常自愈行为,无需干预,但 00:3x 后看板/监控会有多轮 deploy 日志属预期。

## 4. 问 2:02:00 链的追平覆盖范围(代码证据)

- 定时器:`trade-backfill-evening.timer` OnCalendar=**16:35/21:00/02:00**;ExecStart=`/bin/bash /home/ubuntu/code/trade-data/scripts/backfill_metrics.sh`(NEXT=10-09 02:00,LAST=10-08 21:00)。
- `scripts/backfill_metrics.sh` L28-33:调 `index_backfill.main`(`"$REPO/.venv/bin/python" -c "from app.collector.index_backfill import main; main()"`);L85-91 注释明确"deploy.sh 在 backfill 内部被触发"。
- `app/collector/index_backfill.py` **L1119-1138**:

      if ok > 0 or s_has_today or gap_fixed > 0 or _extra_new:
          ... subprocess.run([sys.executable, "-m", "app.compute.runner"], ...)
          ... subprocess.run(["bash", "scripts/deploy.sh", "backfill"], cwd=repo,
                             env={**os.environ, "REPO": str(repo)}, check=False)

  ⇒ **补到新数据(任一条件成立)即触发完整 deploy(段1:export→build_board_etf_map→accum_nav→check 全链→rsync→R2 异步;段2:git add/commit/push)**,不是"只推指数/accum_nav"。
- 历史实证(云上 `data/logs/`,逐槽 grep):10-06 02:00 槽(段1 02:05:42 → 段2 02:16:26,exit 0,R2 上传 02:27 完成)、10-07 02:00 槽(02:05:40 → 02:16:32,exit 0,R2 上传 02:27:47 完成)、10-08 02:00 槽(02:06 触发,被 alert 拦)、10-08 16:35/21:00 槽(均触发 deploy,均被拦)。**5/5 槽位都"补到新数据→触发 deploy"**。
- 覆盖范围:deploy 成功后由 `r2_upload_async.sh` 全通道追平(L198-270:lab/trade-sim/index/industry/public-fund/etf-score/data-large/**all-data(14 项所在)**/kelly-snapshots/kelly-parts/feed + verify-r2 + purge)+ GIT_REPO rsync + git 段2。即 **02:00 若成功 = 14 项 + 家族样本 + industry + accum_nav 一次追平 + 修 GIT_REPO 树**(与 00:22 已完成的一致)。
- 诚实标注:02:00 是否"必然"补到新数据无法预证,按近 5 槽 5/5 高频推断;若否,05:00 us-stock-morning 链历史亦触发 deploy(10-08 05:00 有 `deploy_20261008_0500.log`),为下一兜底。

## 5. 问 3:要不要今晚手动补跑?

**结论:不要。自愈链已代跑(00:13-00:22 deploy exit 0 + R2 上传在跑),现在手动跑只有撞车风险,零增量收益。**

- 收益面(手动)已归零:deploy 已完成、push 已成功、GIT_REPO 已 rsync;剩下唯一事项=R2 异步上传完成(正在跑),这一步不是 deploy 能加速的。
- 风险面依旧:#237 pre-upload 备份护栏(跨账号 COPY 静默失败)对**手动/自动 deploy 同等失效**,覆盖不可逆程度相同;此外手动跑会与 r2-upload-002208、backfill_0022 并发(段1 锁外的 export/rsync 会互相踩写)。
- 若主控想"兜底保险":只需在 00:3x 观察 r2_upload 完成+抽样 14 项 ETag 追平即可,不需动手;失败时 02:00 链已在 1h30m 内兜底。

## 6. 问 4 + 诚实标注

**撞车核查结论**:见 §3.3。核心一句:今晚 00:22 起云上已有 3 个自有任务在跑(r2 上传/backfill/备份),02:00/02:40/03:00/05:00 等时点均有任务;任何人工动作在 00:3x-01:4x 之外都会撞车,而该窗口内也无必要动作。

**诚实标注(未覆盖/推断,分栏)**:
- [推断] 02:00 链"必然补到新数据"= 历史高频(5/5 槽);非保证,后备 05:00/16:35/17:50。
- [未覆盖] r2_upload_async_20261009_002208 的最终结果(报告落笔时仍在跑):完成/失败以届时日志与 ETag 实测为准;r2_upload 有失败告警通道(会发出去=非静默)。
- [未覆盖] 10-07 21:16 成功 deploy 为何未刷新 14 项(board_etf_map 等当时 md5 未变被变更检测跳过,深挖未做);不影响"00:22 上传会带这 14 项"结论(state md5==R2 ETag 且 cloud≠state,三方实测)。
- [未覆盖] trade_sim 前缀样本未逐项核(仅验证 lab 65/trade-sim 103"未变化"日志)。
- [口径] 上级文档"58 条 alert_analyze 用户可见项"未复核其定义;本轮实测 70 文件、上传 71/71(alert+70),以实测为准。
- [采信] 10-08 自锁链背景(12 轮零成功、22:4x 手动解锁 71/71、r2_consistency 23:23 已真发 severe 告警)直接采信上级文档,未逐条复核;其中 r2_consistency 的 GIT_REPO 滞后维度已被 00:22 自愈修复(下次检查时点 23:20)。

## 附录 A:14 项三方 md5 对照(state==R2,cloud≠state)

| 文件 | state md5(=R2 ETag) | 云上当前 md5 |
|---|---|---|
| board_etf_map.json | b4a420e3… | 60e7fa70… |
| futures.json | 4f8b1a6a… | 02ff3ccf… |
| futures_acc_conclusion.json | 469ea1b6… | 87129c76… |
| futures_acc_trend.json | 30c1313d… | 8204c376… |
| market_tier_history.json | 7ce0b24f… | 5e88b58d… |
| rotation.json | 3dbd8756… | 8bf97c72… |
| signal_freq.json | e1cb9427… | 00503c4f… |
| signal_kelly_backtest.json | d2f7292b… | 9adb0573… |
| signal_kelly_backtest_sdc.json | 803bd3a4… | bfefa6a8… |
| signal_stats.json | e574b822… | 70eafa74… |
| etf_national_team_holders.json | b2a22574… | 9ded30a8… |
| etf_national_team_quarterly.json | ac74a087… | 804b0ec4… |
| export_manifest.json | 71b215f5… | be9d54ac… |
| schedule_stats.json | 0b0a6f77…(state 与 R2 bc3ddfa6 亦不一致,多通道所致) | f441f19d… |

## 附录 B:已追平清单关键字段实测(00:1x)

    kelly_mode_s06_state => coverage_end=20261008   (R2 LM 10-08 20:35:03)
    alert => date=20261008 (R2 LM 10-08 22:40:43)
    notifications => date=20261008 (R2 LM 10-08 22:01:43)
    ad_line data 尾 => date=20261008
    a-stock-3m metrics/indices 尾 => 20261008
    accum_nav_map 键尾(158000) => 20261008
    signal_kelly_day_snapshot.days 尾 => 20261008
    overview => date=20261008

## 附录 C:关键命令原文(节选)

    # 三层对比(R2 侧,逐文件)
    curl -s --max-time 12 -sI -H "User-Agent: Mozilla/5.0" "https://ssd.fx8.store/data/<file>"
    # 云上(R2 别名前缀)
    curl -s --max-time 15 -sI -H "User-Agent: Mozilla/5.0" "https://ssd.fx8.store/industry/industry-1y.json"
    curl -s --max-time 15 -sI -H "User-Agent: Mozilla/5.0" "https://ssd.fx8.store/accum_nav/158000.json"
    # 云上日志(只读)
    tail data/logs/self_heal_audit.log
    grep -nE "段1|段2|终止部署|汇总|R2 上传|结束" data/logs/deploy_20261009_0013.log
    tail data/logs/r2_upload_async_20261009_002208.log
    systemctl list-timers --all --no-pager

## 7. 补记(00:42-00:50 实测更新,报告落档后追加)

### 7.1 etf-hist 通道本轮卡死被看门狗 kill(新发现)

`r2_upload_async_20261009_002208.log` 原文:

    ⚠ upload-etf-hist 停滞 900s 无日志输出, kill pid=1928109
      --- [upload-etf-hist] kill 前 tmp_log 尾部 30 行(定因材料) ---
      (tmp_log 无任何输出——进程启动即无日志/缓冲未刷)
    ⚠ upload-etf-hist 失败/超时,继续

- 只读侧证据:进程采样(`/proc/1928109/io` rchar 固定 1,907,668 不动、wchar=0、`wchan=hrtimer_nanosleep`、0 网络连接)⇒ 该进程自启动后即无有效动作(sleep 中),非"慢传输"。看门狗按"停滞 900s 无日志输出"判死并 kill(`r2_upload_async.sh` `run_r2_upload()` 停滞判据,R2_UPLOAD_STALL_SECS 默认 900)。
- 影响:该通道 kill 后**继续后续通道**(`|| {...继续; R2_FAIL+=...; }`),不阻塞 all-data(14 项);失败通道进收尾 `finalize_verify` 轻量对账(verify-channels 抽查),对账过=不告警,有缺口=发 `deploy_r2_upload_fail` 告警(dedup 6h)。
- etf 数据现状:R2 `etf/510300-all.json` LM=10-08 21:41(另一条链已近新鲜);`.r2_etf_hist_state.json` updated_at=2026-10-09T00:13:48(count=1718,增量,changed=108)——**00:13:48 另有一次 etf-hist 上传成功**(见 §7.2),其 state 已记录、R2 侧 10-08 版大体就位;本轮卡死影响=10-08 盘后 export 的新变化(若有)未在本次传完,下轮(02:00 后)会因 state 不匹配重试。
- 与 02:00 链的关系:若 02:00 链再遇该通道同症,会再耗 900s 后跳过,不阻塞其余通道(时序总时+15min)。

### 7.2 #237 pre-upload 备份护栏失效:今天 00:13 仍在实录(非历史遗留)

`etf_national_team_backfill_20261009_0007.log` L66-73 原文:

    [etf-hist] 模式=增量 本次待传 108/1718(其余 1610 个内容未变化跳过)
    [etf-hist] R2_BYTES_TOTAL=5856978
    [etf-hist] ⚠ 备份 etf/158010-all.json -> signal-backup2/pre-upload/20261009/etf/158010-all.json 失败 status=404 ... NoSuchBucket ...
    (同类行多条)

⇒ 00:07 HEAL 链里那次 etf-hist 上传(108 个文件)的**逐文件 pre-upload 备份全部 404 NoSuchBucket 失败且不阻断上传**,与 `233-r2-bucket-prod-observe-20261008.md` 描述一致:覆盖不可逆现状在今晚仍在,且不止 deploy 通道——**任何走 upload_r2.py 的上传(含自愈链)都面对同一护栏失效**。

### 7.3 其余通道传输健康(00:48 采样)

- `upload-accum-nav`(pid 1934592)在正常传输:`rchar 46,405,518→46,906,959`、`wchar 19,908,267→20,423,844`(4s 采样,持续增长),`wchan=futex_wait_queue_me`。⇒ etf-hist 卡死为该通道特例,非全局网络故障。
- 轮询时点本报告追加时(00:50),r2_upload_async 仍在 accum-nav 及后续通道,all-data(14 项)未到。

### 7.4 14 项追平最终验收(待定稿)

本报告落档后(`00:5x`)对 14 项 R2 ETag 复测的最终结果以回主控消息为准;若未追平且本轮 `finalize_verify` 未告警,02:00 backfill 链为下一次兜底(§4)。

### 7.5 终稿更新(01:14 实测,替代 §7.4 的"待定稿")

1. **14 项全部追平**:R2 ETag 与云上当前 md5 逐位一致(14/14;ETag 清单:board_etf_map=bf1bc257 / futures=02ff3ccf / futures_acc_conclusion=87129c76 / futures_acc_trend=8204c376 / market_tier_history=5e88b58d / rotation=8bf97c72 / signal_freq=00503c4f / signal_kelly_backtest=8984b076 / signal_kelly_backtest_sdc=856288c4 / signal_stats=b8ab33bb / etf_national_team_holders=3ed27a3d / etf_national_team_quarterly=8cbf13bf / export_manifest=21a905c1 / schedule_stats=db46adec),LM 全部=10-09 01:08:xx BJ(all-data 通道)。
2. **家族样本追平**:industry-1y=a07ab1a5(00:52)/ industry-3m=612405ab(00:51)/ accum_nav/158000=3425a644(00:45,==云上 md5)/ signal_kelly_trades_parts recent=31808fa5(01:03,==云上 md5)。
3. **etf-hist 通道卡死事件的定性与兜底**:
   - 卡死轮为 **force_full(全量)模式**(verify-channels 原文:"通道 upload-etf-hist 本轮被看门狗超时 kill(force_full 未完成, PUT 未执行)");900s 停滞 kill,PUT 零执行,tmp_log 空(进程级证据见 §7.1)。
   - 兜底链(三重):①`verify-r2` 层3 对账**自动补传 101 个**(index/csi_*-all.json + 约 98 个 etf/xxx-all.json);②`backfill_0022` 链内 etf-hist 增量上传 **01:12 成功写 state**(`.r2_etf_hist_state.json` mtime=01:12,marker 已清);③02:00 链 verify-r2 下轮再兜。etf 样本实测:158010/158001 LM=10-09 00:13:25、510300 LM=10-08 21:41,均为最新版。
   - 告警:**01:12:07 真发 1 封**(邮件 234058394@qq.com + 飞书 oc_7d8d…,subject「[告警] [cloud] R2上传失败」);第二封(01:13:32 补跑轮收尾)被 dedup 抑制(age=85s < window=21600s,不重发)。
4. **任务收官**:r2_upload_async_002208 于 **01:13:32 结束,退出码=0**。
5. **遗留隐患(建议单列跟进)**:etf-hist force_full 卡死根因未定位(增量轮正常、force_full 轮停滞 900s;若后续轮次再遇 force_full 会再耗 15min+并可能再告警);10-09 自愈额度已用尽(3/3),今日再出故障不会自动 heal。
