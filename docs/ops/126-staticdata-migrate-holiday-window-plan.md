# #126 staticdata 迁移·假期窗口执行方案(修订版)

> 2026-09-30 01:10 落档。本文档是 #126(staticdata 9 目录 31239 个 tracked 文件移出 git)的**假期窗口执行方案**,供主控后续派单直接照做。前置核查部分(02 节)包含**实测推翻原 B 方案窗口前提**的关键证据,请主控先读再派单。

## 0. 背景与根因(承接 #126 主任务)

- staticdata 仓(`/home/ubuntu/code/trade-data-signal-staticdata`)9 目录 tracked 残留 31239 文件(fund_nav 26458 / etf 1712 / accum_nav 1712 / nav_bucket 256 / parts 383 / sdc_parts 391 / index 173 / lab 65 / trade_sim 89),8 目录每日全量再生 → staging 4065 文件 ~1.2GB > 500MB 阈值 → git commit 跳过。
- 后果:staticdata 备份 git 段自 2026-09-28 19:01 停摆;磁盘留档 + R2 上传正常,仅灾备 git 层断裂。
- 前置:fix/staticdata-parts-exclude-20260928 已合 main(tip 95b82d845),云上已同步新脚本(grep -c fund_nav = 2)。
- 迁移脚本:云上 `scripts/migrate_large_json_out_of_git.sh`,硬顺序 ①R2 上传 → ②git rm --cached;幂等;脚本自身不 commit/push。

## 1. 硬约束(原任务口径,不可协商)

1. 必须用**新脚本版本**跑 migrate(--print 刷新 .gitignore 受管区块;旧版会重加 fund_nav 26k 文件 → 永久破坏)。
2. `git rm` 必带 `--cached`;**R2 上传成功才允许移除索引**(否则"git 无 + R2 无"= 真断链)。
3. 异常立即停下上报(§23.11),绝不静默吞掉。
4. 动手前备份 + 对账清单。
5. 只授权写 staticdata 仓迁移 + 备份;其余只读。
6. ssh 云上:`ssh -i ~/tdsignal.pem -o BatchMode=yes -o ConnectTimeout=15 ubuntu@122.51.111.173`。
7. 硬底线:**任何时刻 migrate 不得阻塞生产链**(05:00 deploy R2 推送、02:40 gold-night、其他定时 upload_r2 调用)。宁可迁移推后,不能让线上数据再停。

## 2. ⚠️ 前置核查实测结论(2026-09-30 01:05):B 方案"10-03 全天无任务"窗口前提不成立

**原 B 方案(协调器拍板)**假定 10-03 为"全天无任务"的干净窗口。**实测推翻此前提**,证据如下:

### 2.1 `systemctl list-timers` 只显示每个 timer 的"下一次"触发,不代表当日无任务

`systemctl list-timers --all`(2026-09-30 01:00 云上实测)中 10-03 无 NEXT 项,是因为所有 `*-*-*` 每日 timer 的**下一次**触发都在 09-30(当天),**并非 10-03 无任务**。逐一 `systemctl cat <timer>` 读 OnCalendar 原文:

| timer | OnCalendar | 假期(10-01~10-07)每天? | 是否碰 R2 锁 |
|---|---|---|---|
| trade-gold-night | `*-*-* 02:40:00` | **每天** | **是**(upload_r2 upload-data-large) |
| trade-us-stock-morning | `*-*-* 05:00:00` | **每天** | **是**(跑 deploy.sh→backup→upload-large-json) |
| trade-rzhb-backfill | `*-*-* 08:00:00` + 19:15 | **每天** | **是**(调 deploy.sh) |
| trade-update-all | `*-*-* 17:50:00` | **每天** | **是**(非交易日分支仍跑 deploy.sh 补推) |
| trade-etf-national-team | `*-*-* 20:07:00`+21:30 | **每天** | **是**(upload_r2=2) |
| trade-backup-db | `*-*-* 21:00:00` | **每天** | **是**(upload_r2=4) |
| trade-pf-score-daily | `*-*-* 16:00:00` | **每天** | **是**(upload_r2=2) |
| trade-public-fund-daily | `*-*-* 16:30/17:00` | 每天 | 否(upload_r2=0) |
| trade-daily-brief | `*-*-* 20:40:00` | 每天(有交易日判断) | 否 |
| trade-s06-snapshot | `Mon..Fri 20:35` | 10-03 周六不触发,10-01/02/06/07 触发 | 否 |
| trade-fetch-news | `*-*-* *:01,45` | **每天 24 次** | 否(仅采集) |
| trade-schedule-monitor | `*-*-* *:00,15,30,45` | **每天 96 次** | 否(监控,直连 R2 验证只读) |
| trade-intraday-snapshot | `*-*-* 09:25...15:35` | **每天**(10 行交易日判断,非交易日可能空转) | 是(upload_r2=13) |
| trade-fapi-daily | `*-*-* 18:10` | 每天 | 是(upload_r2=1) |
| trade-lab-auto | `*-*-* 19:00` | 每天 | 是(upload_r2=21) |
| trade-turnover-backfill | `Mon..Fri 21:10` | 10-03 周六不触发 | 是(upload_r2=3) |
| trade-backfill-evening | `*-*-* 02:00/16:35/21:00` | **每天** | 否 |
| trade-public-fund-quarterly | 每天 03:00 | 每天 | 否 |
| trade-pf-stage0-manager | `*-*-01 02:47` | 仅 10-01 | 否 |
| trade-pf-stage0-nav | `Fri 01:43` | 仅 10-02 | 否 |
| trade-pf-stage0-overview | `Sun 02:17` | 仅 10-04 | 否 |
| trade-pf-score-weekly | `Sun 03:17` | 仅 10-04 | **是**(upload_r2=2) |
| trade-etf-track-index | `Sun 03:30` | 仅 10-04 | 否 |
| trade-lof-track-index | `Sun 04:00` | 仅 10-04 | 否 |
| trade-pf-stage0-risk | `*-*-15 02:33` | 仅 10-15 | 否 |

### 2.2 关键确认:非交易日(假期)update-all / us-stock-morning 仍会跑 deploy.sh → 抢 R2 锁

- `update_all.sh` L68-69 实测:
  ```
  if [ "$IS_TRADING" != "1" ] && [ "$FORCE" != "1" ]; then
    echo "非交易日,跳过采集,仅 deploy 补推数据..." 
    bash "$REPO/scripts/deploy.sh" 2>&1 | tee -a "$LOG"
  ```
  → **假期 17:50 update-all 仍会跑完整 deploy.sh**,deploy.sh 会跑约 14 个 upload_r2 通道 + 触发 `staticdata_backup_async.sh`(L970 systemd-run)→ upload-large-json 全量上传。**假期无例外。**
- `us_stock_morning.sh` L71 每天 05:00 跑 deploy.sh(grep 交易日判断=0 行,注释明说"美股周末虽休但脚本仍启动")→ 每天抢锁。
- `gold_night.sh` L65/L69 每天 02:40 直接 upload_r2(upload-data-large + upload-data-files)。
- `rzhb_backfill.sh` L134 调 deploy.sh(有交易日判断,但需实测非交易日是否真跳过 deploy 段)。

### 2.3 结论

**不存在"连续 6h 无生产 upload_r2"的假期窗口。** 假期每天至少有:02:40 gold-night / 05:00 us-stock(deploy) / 08:00+19:15 rzhb(deploy) / 16:00 pf-score-daily / 17:50 update-all(deploy+backup) / 20:07+21:30 etf-national / 21:00 backup-db 会碰 R2 锁;且每 15min schedule-monitor、每 15/45min fetch-news 天天满格跑。

→ **migrate 不能以"独占锁长跑"方式执行**。必须改"短窗分批 + 让路"策略(见 03 节修订方案)。

## 3. 修订执行方案:短窗分批 + 让路(替代原 B 长跑)

### 3.1 策略核心

- **每次只跑一个有界短窗**,上传一部分即**主动释放 R2 锁**,让生产任务优先;绝不占锁跨过生产任务时点。
- upload_r2.py upload-large-json **HEAD ETag 幂等**,已传的下次跳过 → 分批推进越跑越快(已传的 HEAD 命中跳过,不重复 PUT)。
- 任一批跑完后**不执行 rm --cached**(避免"半完成态")。等某一批在完整短窗内能把剩余全部传完(HEAD 全跳过 / 剩余量小)时,才允许该批执行 rm --cached + commit + push 收口。

### 3.2 建议分批窗口(假期每天,避开生产锁高峰)

| 时段 | 状态 |
|---|---|
| 02:40 gold-night 之前 | gold-night 会碰锁,不宜 |
| **06:00~08:00**(us-stock 05:00 完成后) | us-stock deploy 收尾后窗口,**可用**(避开 08:00 rzhb) |
| **09:26~09:40** / **11:32~13:01** 等 intraday 间隙 | intraday 非交易日可能空转但 timer 在跑,**低优先级备选** |
| **16:01~16:30**(pf-score-daily 16:00 后,public-fund 16:30 前) | 短窗,**可用** |
| **18:11~19:00**(fapi 18:10 后,lab 19:00 前) | 短窗,**可用** |
| **19:01~20:07**(lab 19:00 后,etf-national 20:07 前) | 约 1h,**可用** |
| **22:35 之后**(check-data-gap 22:35,之后到 02:40 gold-night) | **最长单窗 ~4h,首选**(但需确认 22:35~02:40 间无其他 upload_r2) |

> **首选执行窗**:每假期日 23:00~02:30(约 3.5h),因为:
> - 22:35 check-data-gap 之后到 02:40 gold-night 之间,**实测无其他 upload_r2 任务**(详见 2.1 表,22:35~02:40 区间仅 backup-db 21:00 / nextday-plan 22:30 / check-data-gap 22:35,均为 22:35 前)。
> - 但 migrate 启动需避开 22:30/22:35(它们 22:35 前结束),故 **23:00 启动**最稳。
> - 若 3.5h 不够传完,次日 23:00 续跑(幂等跳过已传)。

### 3.3 `R2_LARGE_JSON_BUDGET` 设定

- 实测上传速度 ~0.6 文件/秒(154 文件 ~3min)。3.5h ≈ 12600s → 单窗可传约 **7560 个**。
- 预算设为略小于窗口,保证"传不完也在生产任务来之前干净退出、释放锁":
  ```
  R2_LARGE_JSON_BUDGET=10500   # ~2.9h,留 0.6h 缓冲让路给 02:40 gold-night
  R2_UPLOAD_LOCK_TIMEOUT=7300  # 保持默认;等锁超时 fail-closed(生产优先)
  ```
- 若某批只剩 <2000 个(约 0.5h),可放宽 budget 到 11000 一次传完 → 该批可执行收口。

### 3.4 让路策略(关键,硬底线)

- **R2 锁语义**:`upload_r2.py _acquire_r2_upload_lock` flock LOCK_EX|LOCK_NB,冲突时**排队**,timeout 默认 7300s fail-closed exit 1。任何生产 upload_r2 调用进来会排队等 migrate 释放。
- **绝不允许 migrate 让生产任务排队超时 fail-closed** → 所以 migrate 的 budget 必须**远小于**下一个生产任务到达时间,主动提前退出让路。
- 若生产任务在 migrate 持有锁时到达:生产会排队等待,migrate 到 budget 即退出放锁 → 生产拿到锁正常继续,只多等几十分钟(<7300s),不触发 fail-closed。**这是可接受的让路**。
- **反向(生产先持锁)**:migrate 启动时若生产正持锁,`R2_UPLOAD_LOCK_TIMEOUT` 内等待;超时 fail-closed 退出,日志留"等锁超时",下次短窗重试。**不自杀式抢锁。**

### 3.5 执行步骤(假期首窗)

```bash
# 1) 备份(仅首窗前做一次)
ssh ... 'rm -rf /home/ubuntu/code/_backup_126_staticdata_before_migrate \
  && git clone --no-hardlinks /home/ubuntu/code/trade-data-signal-staticdata /home/ubuntu/code/_backup_126_staticdata_before_migrate'
# 2) 确认 9 目录 tracked 计数(基线)
ssh ... 'cd /home/ubuntu/code/trade-data-signal-staticdata && for d in data/fund_nav data/etf data/accum_nav data/nav_bucket data/signal_kelly_trades_parts data/signal_kelly_trades_sdc_parts data/index data/lab data/trade_sim; do echo "$d : $(git ls-files "$d" | wc -l)"; done'
# 3) 短窗跑 migrate(每窗一次,直至收口批)
ssh ... 'cd /home/ubuntu/code/trade-data-signal && nohup env REPO=/home/ubuntu/code/trade-data GIT_REPO=/home/ubuntu/code/trade-data-signal STATICDATA_REPO=/home/ubuntu/code/trade-data-signal-staticdata R2_LARGE_JSON_BUDGET=10500 R2_UPLOAD_LOCK_TIMEOUT=7300 /bin/bash scripts/migrate_large_json_out_of_git.sh > /tmp/migrate_126_<日期>_<序号>.log 2>&1 &'
```

### 3.6 收口批(最后一窗)

- 当 `--print` 清单全部 HEAD 命中(已传)或剩余量 < 单窗可传量时,该窗执行完整 migrate 流程:上传剩余 → **rm --cached 9 目录 → 提交前检查 → 停**(脚本不自动 commit,见 §4)。

## 4. 收口步骤与验收口径(迁移最终完成)

### 4.1 git rm --cached + commit + push(收口批人工执行)

```bash
cd /home/ubuntu/code/trade-data-signal-staticdata
# 1) 9 目录 rm --cached(仅 R2 已确认上传成功后)
for d in data/fund_nav data/etf data/accum_nav data/nav_bucket data/signal_kelly_trades_parts data/signal_kelly_trades_sdc_parts data/index data/lab data/trade_sim; do
  git rm --cached -r "$d"
done
# 2) 更新 .gitignore(受管区块应已含 9 目录,确认)
git status --porcelain | head -20
# 3) commit + push(main 分支,灾备 git 段恢复)
git add -A  # 仅 staticdata 仓,不含根 data/
git commit -m "migrate: 9 dirs (31239 files) out of git tracking, R2 backup complete" 
git push origin main
# 4) 验证 push 成功
git log origin/main -1 --format="%h %ci %s"
```

### 4.2 验收口径(7 项,逐项留证据)

| # | 项 | 通过标准 | 命令 |
|---|---|---|---|
| ① | 云上脚本版本 | `grep -c fund_nav large_json_excludes.py` = 2(受管区块含新排除) | `grep -c fund_nav /home/ubuntu/code/trade-data-signal/scripts/large_json_excludes.py` |
| ② | 9 目录 tracked 逐个 = 0 | 每个 `git ls-files $d | wc -l` = 0 | 见 3.5 步骤 2 同款命令 |
| ③ | 磁盘文件数不变 | 迁移前后 2~3 目录 `find $d -type f | wc -l` 一致 | 迁移前记录基线,收口后对比 |
| ④ | --check-staged = 0 | `large_json_excludes.py --check-staged` 退出码 0(待提交 ~95MB < 500MB) | 云上执行脚本 `--check-staged` |
| ⑤ | staticdata 仓 commit+push | `git log origin/main -1` 显示新 commit hash + 已推 | 见 4.1 步骤 4 |
| ⑥ | 本地 feat 分支 commit | 本方案文档 commit hash + 分支名 | `git log --oneline -1` |
| ⑦ | 异常/偏差 | 如实记录(如"任务写 trade-data-signal,实际仓 -staticdata"已作为偏差上报) | 见 §5 |

## 5. 异常与偏差记录(截至 2026-09-30 01:10)

1. **路径偏差**:任务书写 `/home/ubuntu/code/trade-data-signal`,实际 staticdata 仓为 `/home/ubuntu/code/trade-data-signal-staticdata`(已向协调器确认),本方案全部使用 -staticdata 全名。
2. **上传速度瓶颈**:实测 ~0.6 文件/s → 31661 文件 ≈ 14h,远超任何单窗;原"4h 长跑"方案不可行,已改短窗分批。
3. **R2 日期前缀**:R2 key 为 `large-json/<当日日期>/...`,当天目录为空需全量上传;跨日不共享,分批只在同日续跑有效。
4. **误 kill 生产进程(本次重要事故,根因与教训见 §6)**:00:52 按命令名匹配 kill 了 upload_r2 进程(实为生产 `staticdata_backup_async.sh etf-national-team` 的 upload-large-json 子进程),导致该轮备份"部分失败"并发告警邮件/飞书。已如实上报(§23.11)。**教训已写入 §6,防再犯。**

## 6. ⚠️ 误 kill 根因与防再犯(2026-09-30 00:52)

- **现象**:排查"残留进程"时,`ps` 见 `upload_r2.py upload-large-json`(PID 2550799),按命令名判定为 migrate 残留,`kill 2550799`。
- **真身**:该进程 PPID=2550720 = 生产定时任务 `staticdata_backup_async.sh etf-national-team`(由 deploy.sh L970 systemd-run 异步触发,本次 00:50:57 启动,日志 `staticdata_backup_async_20260930_005057.log`)。kill 后该轮备份 `⚠ upload_r2.py upload-large-json 失败, 不阻塞` + 变更量超阈值跳过 commit → 发"staticdata 备份失败"告警(email+飞书)。
- **根因**:**"按命令名匹配 kill 残留进程"在生产环境不可靠** —— 同命令名 `upload_r2` 可能属于生产定时任务链,而非本任务残留。
- **正确做法(防再犯)**:kill 前必须先**核实 PPID 属主链**:`ps -o ppid= -p <pid>` → 逐级 `ps -p <ppid> -o args=` 查到脚本/unit;确认为**本任务自己启动的**残留才 kill;属于生产定时任务链(staticdata_backup_async / deploy / 任一 trade-*.service)→ **不 kill,停下上报主控**。
- **教训入档**:docs/ops/126-staticdata-migrate-holiday-window-plan.md §6;相关 memory 索引待主控更新。

## 7. 遗留事项(需主控/协调器拍板)

1. **窗口修订拍板**:原 B"10-03 全天无任务"前提被实测推翻(§2),建议按 §3 短窗分批执行,或协调器另选方案(如 C:靠生产 backup 自然收敛 R2 副本——09-29 backup 单日上传 11870 个,R2 缺口约 3~4 天可自然补齐,届时 migrate 仅做 git 收口)。**请主控确认走短窗分批还是自然收敛。**
2. `docs/pending-features-index.md` #126 状态由主控统一更新(本 agent 不碰)。
3. 云上 `systemctl list-timers` 是**状态型**清单(云上手动管理,git pull 不更新),假期派单前仍应重新实测当日时点,不依赖本文档快照。

## 复现段

- 本文档 02 节 timer 表:云上 `systemctl list-timers --all` + 逐 timer `systemctl cat <timer> | grep OnCalendar`(2026-09-30 01:00 实测)。
- 03 节上传速度:实测 154 文件 ~3min(2026-09-30 00:34 migrate 首轮日志)。
- 06 节误 kill:kill 前 PID 2550799 / PPID 2550720(staticdata_backup_async.sh etf-national-team);日志 `/home/ubuntu/code/trade-data/data/logs/staticdata_backup_async_20260930_005057.log`;相关迁移日志 `/tmp/migrate_126_rerun_0014.log`。

---

## 8. ⛔ 修订(2026-09-30 01:37):§3 短窗分批 与 §7.1 C 方案**双双证伪**,本文档 §3/§3.2/§7.1 作废

> 本节由主控依据独立 researcher 调研(2026-09-30 01:35 完成,只读 R2 全量分页 + 本地代码 + 云上日志)追加。**原 §3/§7 保留可反查,但不得再作为派单依据。**

### 8.1 原 C 方案(靠生产 backup 自然收敛 R2 副本)证伪

**根因:key 按「运行当天」前缀,跨天零复用。**

- `upload_r2.py:2237` `today = _dt.datetime.now().strftime("%Y-%m-%d")`(**动态取运行当天**);`:2267` `key = f"large-json/{today}/{relpath}.gz"`。
- `upload-large-json` 子命令(:2811-2815)**只支持 `--dry-run`,无 `--date`/固定前缀参数**;`migrate_large_json_out_of_git.sh:68` 直接调用、不传日期。
- **铁证**:09-30 00:50 轮(即 §6 被误 kill 那轮)全部写 `signal-backup/large-json/2026-09-30/`,09-29 已有的 11875 个**一个都没跳过**,从新目录 0 开始传到 243 被中断;R2 只读实测 09-30 目录 = **243**,与日志逐位吻合。
- §3.1「HEAD ETag 幂等 → 分批越跑越快」**只在同一天内成立**(09-29 同日多轮确有大量「已存在且内容未变,跳过 PUT」)。
- §7.1 C 方案「09-29 单日上传 11870 → 3~4 天自然补齐」的**前提错了**:每天目录从 0 开始,当天传的量**不会**跨天累积。"11870" 的真身 = R2 `2026-09-29` 目录的 key 数(实际 11875,差 5 为观测时刻抖动),是**全量 31239 的一部分**,不是"当日新数据"。

### 8.2 【重大发现】R2 从来就没有过完整快照 —— 这才是真问题

R2 桶 `signal-backup` 各日期目录只读全量分页实测(2026-09-30 01:30 快照):

| 日期目录 | 文件数 |
|---|---|
| 2026-09-26 / 09-27 / 09-28 | **各 8** |
| 2026-09-29 | **11875** |
| 2026-09-30 | 243 |
| 全桶合计 | 12142 |

9 个目录共 31239 文件,**从未在 R2 完整过**。09-29 那 11875 是旧版**无预算上限**的脚本从 05:22 连跑到 15:35(10h,断在 fund_nav/011957)才凑出来的;此后每轮受 `R2_LARGE_JSON_BUDGET`(默认 3h)限制,上限约 6500~7000 个。

→ **现状 = 这 9 个目录全球只有 git 里那一份完整副本。** 此时执行 `git rm --cached` 等于删掉唯一完整副本,正撞本任务 §1.2「R2 上传成功才允许移除索引(否则 git 无 + R2 无 = 真断链)」红线。**结论:必须先修上传层,再谈迁移。**

### 8.3 修正后的可行路径(待用户拍板后派单)

1. **【前置·必修】给 `upload_r2.py upload-large-json` 加固定日期/前缀参数**(如 `--date YYYY-MM-DD`,默认值=今天 → 纯新增、不改变现有生产行为)→ 多天/多窗接力全部落进**同一个**前缀,直到 31239 个 HEAD 全命中再收口。
2. **【配套】堵 `_prune_large_json`**:它是**14 天滚动清理** → 固定收集的前缀须在 14 天内收口(或临时豁免该前缀的清理);P1 评审另指出它无预算保护,此处再叠一层语义要求。
   - **同一天内可续传已实证**:`upload_r2.py:2266` gzip `mtime=0` 固定 → 同内容同字节 → 单 PUT ETag=内容 md5 可复现 → `:2288-2291` HEAD 命中跳过 PUT(且跳过行计入 ok 不记失败)。故**同一天内多短窗接力确定收敛**,跨天则作废。
   - **备选(不改脚本)**:选一日把当天目录凑满 ~14.4h 有效传输后当日收口;缺点=单日容错为零、跨天即作废(09-29 已证明单日凑不满的概率不低)。
3. 传满 → `git rm --cached` 9 目录 → 收口 commit+push(按原 §4.1/§4.2 验收)。
4. **【待用户拍板·§23.7 冻结范畴】深层缺陷**:这 9 目录每天要重传 31239 个(≈14h,实测 ~0.6 文件/s),而预算上限 3h → **生产备份对它们永远传不满**。三条候选:①放宽 budget(会拉长持锁时间)②改固定前缀做增量复用(不按天翻滚,行为变化最大)③把 9 目录排除出每日备份、另设低频全量通道。**均改变生产备份行为,须用户拍板,不擅自决定。**

### 8.4 旁证:发现的独立 bug(与 #126 无关,另案)

`upload_r2.py s3_request`(:340)**不做 SigV4 canonical query 参数排序** → **所有多参数 R2 list 请求返回 403**。项目 `verify-r2`(:2435)注释明说从不枚举 R2 key,故此缺陷从未暴露。本次调研用「参数按字母序 + token 二次 quote」绕过才拿到 8.2 的数据。**后续若有人要做 R2 list 分页会踩坑。**

### 8.5 §2 窗口前提的补充更正

§2 结论(B 假期窗口不存在)**仍然正确且已再次确认**。补充:`systemctl list-timers` 只显示每个 timer 的**下一次**触发,**不能**用来证明「某一天没有任务」;`systemctl cat <timer> | grep OnCalendar` 才是判据。§2.1 表中 23 个 timer 全是 `*-*-*` 每日触发。

### 9. ⛔ 修订(2026-09-30):#130 已落地,§8.3 待办路径作废

> 本节由主控依据 #130(commit `e01f2a045`)已实现结果追加。**§8.1-§8.4 保留可反查,§8.3 作为路径选择依据已过时,不再派单依据。**

#130 灾备上传通道根治(`fix(r2-large-json)` commit `e01f2a045`)已实现并合并,§8.3 的待办路径**全部走通,`--date` 参数方案不再是路径**:

- **固定前缀增量复用**(§8.3 候选 ② + ①合并):key 改为固定前缀 `large-json/<相对data路径>.gz`(唯一完整副本,增量复用、HEAD ETag 命中跳过 PUT)——不再按天翻滚,跨天可接力累积,直到 9 目录全部 rid 命中。
- **并行化 + SigV4 canonical query 排序 + list 分页**(对接 §8.4 发现的 403 隐患):`s3_request` 补参数排序,`_list_keys` 循环续页直到 NoMoreContents。
- **逃生门 `R2_LARGE_JSON_DATE_PREFIX=1`**:一键回旧按天键生成行为,保留旧分层滚动(日14/周8/月12)。

本次返工(2026-09-30)另修两条:

- **逃生门 prune 语义**:逃生门模式 key 回旧按天键,`_prune_large_json` 必须同步回旧分层保留逻辑(否则按新机制 7 天宽限误清逃生门按天快照),从 git 历史回读旧逻辑为独立函数,逃生门走旧档位、默认模式保持现行为。
- **`restore-large-json.sh --all` 部分态**:过渡期 `--all` 原先只要 flat 非空就用 flat,固定前缀首跑中断时(flat=少 vs legacy 目录=全)会**静默少还原**。改为取并集(固定前置 `∪` 最新 legacy 目录,同 rel 优先固定前缀,补缺时打印醒目警告)——绝不静默少还原。

§8.3 之后剩余动作(git rm --cached 9 目录 + 收口 push)及其验收仍按 §4.1/§4.2 口径。

