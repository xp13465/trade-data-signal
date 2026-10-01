# #149 `trade_deploy.lock` 队列结构性积压根因调研报告

- **日期**:2026-10-01(researcher 调研,只读,零写入云上/本仓除本文件)
- **调研对象**:`/tmp/trade_deploy.lock`(fcntl.flock,进程死即释放,无 stale 残留)
- **结论一句话**:**锁的本职(串行化 git 写)被「deploy 主链全量 export+R2」与「async 灾备 step3.5b upload_r2 3.1 万文件 HEAD 比对」拉长到每段 26~105 分钟,而盘后 16:30~22:00 有 ≥10 个定时调用方密集触发且每段 deploy 结束必触发 async → 锁吞吐(约 2~4 段/小时)远小于触发密度 → 09-30 晚 19:23~10-01 01:01 锁连续占满约 5.6 小时(观察器窗口 21:39~01:02 内从未空),连板写库三次窗口全被拒。**

---

## 1. 锁是谁的、怎么抢(获取点全表)

锁文件 `/tmp/trade_deploy.lock`,机制 = `scripts/with_lock.py`(`fcntl.flock` LOCK_EX,`--block-timeout N` 时 2s 间隔非阻塞轮询,累计超 N 秒 → notify 告警 + 优雅跳过 exit 0;超时是「排队等锁」超时,**不是持锁超时**)。获取点(全部阻塞模式除非注明):

| # | 调用方 | 位置 | 参数 | 持锁内干什么 |
|---|---|---|---|---|
| 1 | update_all.sh | scripts/update_all.sh:146 | `--block-timeout 3600` | deploy.sh all(17:50 timer,主链) |
| 2 | futures_backfill.sh | scripts/futures_backfill.sh:97 | `--block-timeout 3600` | deploy.sh futures(20:05 timer,09-30 实测排队超时跳过) |
| 3 | etf_national_team_backfill.sh | scripts/etf_national_team_backfill.sh:123 | `--block-timeout 3600` | deploy.sh etf-national-team(20:07 timer,09-28/29 实测排队超时跳过) |
| 4 | lhb_backfill.sh | scripts/lhb_backfill.sh:107 | `--block-timeout 3600` | deploy.sh lhb(18:30,09-29/30 排队超时) |
| 5 | rzhb_backfill.sh | scripts/rzhb_backfill.sh:134 | `--block-timeout 3600` | deploy.sh rzhb(08:00/19:15) |
| 6 | public_fund_daily.sh | scripts/public_fund_daily.sh:82 | `--block-timeout 3600` | deploy.sh public-fund(16:30) |
| 7 | public_fund_full.sh | scripts/public_fund_full.sh:87 | `--block-timeout 3600` | deploy.sh public-fund(22:00) |
| 8 | public_fund_quarterly.sh | scripts/public_fund_quarterly.sh:90 | `--block-timeout 3600` | deploy.sh public-fund(03:00) |
| 9 | index_backfill.py(backfill-evening) | app/collector/index_backfill.py:1125,1140 | `--block-timeout 3600` | deploy.sh backfill(21:00,观察器抓到 2961756 持锁者即它触发的 async backfill) |
| 10 | **staticdata_backup_async.sh(灾备,长跑主因)** | scripts/staticdata_backup_async.sh:66 | `--block-timeout 3600` | 整个灾备:rsync DB/JSON + **step3.5b upload_r2.py upload-large-json(3.1 万文件 HEAD 比对,R2 跨境)** + git add/commit/push。**每个 deploy 调用方结束时触发一次**(deploy.sh L963-1005),即「任何 deploy → 必多排一个 async」 |
| 11 | staticdata_sync.sh(news-fetch / daily-brief) | scripts/staticdata_sync.sh:63-66 | `--block-timeout 3600`(默认阻塞;intraday 用 `--nb`) | news-fetch 每 ~30min(fetch_news.py:744)、daily-brief 20:40(gen_daily_brief.py:3150) |
| 12 | intraday_snapshot.sh(盘中) | scripts/intraday_snapshot.sh 头注;staticdata_sync `--nb` | 非阻塞 | 盘中被锁占即跳过,不排队(盘中非本问题主战场) |
| 13 | kelly_intraday_rerun.sh | scripts/kelly_intraday_rerun.sh:50 | `--nb` 非阻塞 | 锁在位跳过本轮 |
| 14 | gold_night.sh | scripts/gold_night.sh(头注) | 阻塞 | 02:40 凌晨,低竞争 |

**`scripts/main-merge.sh` 不持锁**(grep 无 lock/with_lock 引用),排除在锁竞争面外。
**fetch_news.py 调 staticdata_sync.sh news-fetch 有 subprocess timeout=600**(fetch_news.py:744-746)——即 news-fetch 排队最多 10min 就被杀,30min 后重来,成了持续供给源。

## 2. 正常单次持锁时长(云上日志实测,`/home/ubuntu/code/trade-data/data/logs/`)

持锁区间 = async/deploy 日志起止(async 日志写在持锁 exec 之后,起止即持锁起止;deploy 日志同样)。09-30 晚关键段:

| 段(日志文件) | trigger | 持锁区间 | 时长 | 内部结构(step 打点) |
|---|---|---|---|---|
| async `_20260930_192301.log` | all | 19:23:01 → 21:08:50 | **1h45m49s** | **step3.5b upload_r2 = 6315s(卡死点)**;step1/2/3 合计 20s;变更 4070 文件/1207MB 超阈值跳过 commit |
| deploy `_2108.log` | ? | 21:08:51 → 21:40:00 | 31m09s | ETF 行情/board map/overlap/holdings 采集 + export + R2 + git |
| deploy `_2140.log` | ? | 21:40:01 → 22:14:39 | 34m38s | 同上 |
| deploy `_2214.log` | ? | 22:14:40 → 23:02:18 | 47m38s | 同上 |
| deploy `_2302.log` | ? | 23:02:20 → 23:40:37 | 38m17s | 同上 |
| async `_20260930_234038.log` | backfill | 23:40:38 → 00:31:29 | 50m51s | step3.5b 逐文件 HEAD 比对 28243 个已跳过 PUT |
| async `_20261001_003131.log` | etf-national-team | 00:31:31 → 01:01:22 | 29m51s | step3.5b 比对 31672 个 |
| async `_20261001_023540.log` | backfill | 02:35:40 → 03:02:27 | 26m47s | step3.5b |
| async `_20261001_052409.log` | all | 05:24:09 → 05:49:55 | 25m46s | step3.5b(热身后 25-30min 成常态) |
| async `_20261001_171748.log`(白天) | backfill | 17:17:48 → 17:50:37 | 32m49s | step3.5b |

对照(引入 step3.5b 之前/初始):09-25 18:13 的 async 日志无 step3.5 打点,全程 **13s**。09-26~09-28 async 持锁 10s~2min。**上传从秒级变成 26~105min 的分水岭 = step3.5b upload_r2.py upload-large-json 的引入(09-25/#126 fixed-prefix 改造后 31663 对象全量 HEAD 比对)**。09-29 P1(keep_alive+预算 10800s+熔断 30 次)上线后实测 2358 注释:keep-alive 下每文件 ~1.14s×31663 ≈10h(单线程);8 线程并行实测 26~105min/段。P1 是有界化(不再 10h 无限跑),不是缩短。

## 3. 调用方叠加来源(云上 systemctl list-timers 权威时点 + 脚本内触发链)

盘后持锁触发的定时时点(云上 53 timers 全量见复现段命令;这里只列能触发 deploy/async/staticdata_sync 的):

| 时点 | timer | 持锁动作 |
|---|---|---|
| 16:30 | trade-public-fund-daily | deploy public-fund |
| 17:50 | trade-update-all | deploy all(主链,采集+export+R2+git) |
| 18:30 | trade-lhb-backfill | deploy lhb |
| 19:15 | trade-rzhb-backfill | deploy rzhb |
| 20:01/20:31··· | trade-fetch-news(~30min) | staticdata_sync news-fetch(阻塞) |
| 20:05 | trade-futures-backfill | deploy futures |
| 20:07 | trade-etf-national-team | deploy etf-national-team |
| 20:40 | trade-daily-brief | staticdata_sync daily-brief(阻塞) |
| 21:00 | trade-backfill-evening | deploy backfill |
| 22:00 | trade-public-fund-full | deploy public-fund |
| 02:40 | trade-gold-night | 阻塞持锁(低竞争) |
| 15:35(每30min) | trade-intraday-snapshot | 盘中非阻塞,不排队 |
| 09:40 | trade-kelly-intraday-rerun | --nb 非阻塞 |

**叠加事实(实测)**:**每个 deploy 调用方结束都触发 async 备份单元**(deploy.sh:966-976 `systemd-run staticdata-backup-<HHMMSS>.service`),所以「N 个调用方 = 至少 N 个 async 排队」。09-30 晚实测 deploy 主链各段之间**无缝接力**(21:08→21:40→22:14→23:02→23:40,每段结束下一段立刻开跑),说明 multi 排队已到「锁一释放立刻有排队者接手」的饱和态。

## 4. 为什么 2.7h 不空 —— 数据判定(双因叠加,量化为证)

**不是单一因,是「持锁者长跑」×「触发密度 >> 锁吞吐」叠加:**

1. **持锁者单段时长远高于设计值**:deploy 主链 31~48min/段(含 export 全量 + R2 + git,在锁内);async 备份 26~105min/段(step3.5b 3.1 万文件 R2 跨境 HEAD)。设计基准(09-25 前)是秒~分钟级。
2. **排队者 3600s 超时上限 = 「排队者本身成为新的占位」的放大器**:with_lock 排队 2s 轮询累计 3600s 才放弃;每秒内锁释放后排队者转持锁者继续跑 30~105min。实测 09-30 20:05 futures 排队等超 3600s 在 21:05:03 优雅跳过(deploy=0,`futures_backfill_20260930_2005.log`);09-29 20:07 etf 等到 22:37 跳过;同样记录 09-28/09-29/09-30 有 futures/lhb/etf 共 7 条日志含「排队等锁超时」。排队者虽不占锁,但其进程(pgrep 命中 `staticdata_backup_async|staticdata_sync`)持续存在 → 观察器判「队列有活」,且 1h 内必有新触发(见 3)补位。
3. **结论数据化**:19:23~01:01 持锁者日志 8 段无缝(见 §2 表,覆盖 5.6h);观察器 8 次采样(21:39~00:3x)全部命中持锁者或等锁者。**队列 = 持锁者(约 8 段)× 排队者(每段 2~4 个)接力,1h 超时跳过的 futures/etf 与每 30min 重来的 news-fetch 提供持续补位 → 队列从不空。**

另外排除:证伪「单次偶发故障」——09-29(10h 弱网事故)已被 #129 P1 有界化,但 09-30 的 26~105min 是 P1 之后的**新常态**(keep-alive 8 线程 3.1 万文件 HEAD),非故障。

## 5. 根治方向(一步到位组合方案;均含副作用)

### 核心原则
锁的本职 = 串行化 **git 写**(staticdata 仓/trade 仓 index.lock 防冲突)。现在锁被 export/R2 上传(天然可并发、k8s R2 只约束同 key 并发 1/s)和灾备 R2 上传拉长到小时级,是**锁的职责错位**——根治 = 把「只应串行」的缩小到最小侧,把「可并发」的移出锁。

### ① 锁粒度拆分(根治主力,推荐)
- 拆两把:`trade_git.lock`(只包 deploy.sh 的 git add/commit/push + staticdata async/sync 的 git 段,秒~分钟级)+ `trade_r2_upload.lock`(export 后 upload-all-data / upload-data-large / 灾备 upload-large-json 等 R2 上传,可并发,不需要进程级串行)。
- 改法:deploy.sh 内部把「export + R2 上传段」与「git 段」解耦,git 段再单独取 `trade_git.lock`;各 backfill 的 with_lock 只包调用链中的 git 部分。改动面:deploy.sh + 各 backfill 持锁结构。
- 副作用:①static-site/data 可能「已生成未 push」的中间态(上线延迟,非错误;R2 已是生效通道,git 只是源码/代码通道)②并发 R2 上传同 key 仍受 R2 1 并发/s 限制(R2 客户端已处理)③需回归静态数据一致性(§22:三处产物同步策略不变,只是各通道不再被一把锁串行)。
- 风险:中等(结构改造),收益:持锁时长回到分钟级,队列自然不饱和。

### ② async 灾备锁分离 + `--skip-if-locked`(即 #129 P2 ① 登记项,与 ① 同批实施)
- staticdata_backup_async.sh step3.5b(upload-large-json)移出 trade_deploy.lock(改持独立 `trade_backup_r2.lock` 或自锁 `--nb`);抢不到直接跳过不排队;`--block-timeout` 不再适用于灾备 R2。
- 副作用:某轮灾备 R2 上传可能跳过 → 数据磁盘+git 留档,次日 rsync+HEAD ETag 幂等补传(灾备 1/2 层不丢,#129 已论证);见 #129 报告 §(评审建议)。
- 风险:低;收益:去掉最长 105min 持锁段 + 去除「每 deploy 必增一个 async 排队」的放大器。
- 附带(#129 P2 ④):砍 fund_nav 清单 3.2 万→~6000(nav_bucket 同源覆盖验证后),进一步缩短。

### ③ 排队上限调整(缓解,配合 ①②)
- `--block-timeout 3600` → 600s:排队者 10min 等不到就跳过,由兜底链(news-fetch 30min 重试/次日 deploy 全量追平)自愈;停留时间短 → 队列观察器不再见长队,排队告警 dedup 已存在(21600s 窗口)。
- 副作用:更多调用方被跳过 → 依赖兜底更频繁,可能出现「数据更新时点推迟」;对连板写库这类「必须这把锁」的任务,改小 timeout 不解决其无法拿窗(它的问题是锁长期被占,不是排队上限)——**所以 ③ 只是队列卫生,不是根治,降低 time-to-skip 让被卡的调用方更快失败重试**。
- 风险:低。

### ④ 时点错峰(缓解)
- 把 20:05 futures / 20:07 etf / 21:00 backfill-evening 的 timer 相互错开 ≥40min(如 futures 19:50、etf 20:20、backfill-evening 21:30,避开 20:40 daily-brief 与 22:00 public-fund-full),减少同刻多排队。
- 副作用:timer 变更需同步云上 systemd 单元 + 文档/memory + 公示;数据可用时点变化。即使全错开,单段 30~105min 的吞吐仍会在 22:00 后堆积 —— **必须与 ①② 搭配,单做 ④ 无效**。

### ⑤ 长任务本身缩短
- 灾备 upload-large-json(e 高点):用「本地快照状态」增量——复用 upload_r2.py 已有 `.r2_accum_nav_state.json` 模式,维护本地文件 mtime/size 清单,只对变化文件 HEAD/PUT;`fund_nav` 桶化验证后砍清单(见 ②附带)。实测 26~105min → 预期分钟级。
- deploy 主链 export+R2:属 ① 移出锁后的自然解耦;如再压,export.py 已有 incremental,主链余量在 ETF 行情采集(东财失败连 fallback 2053 只),属外部源耗时,非锁问题。
- 副作用:状态文件与 R2 实际可能 drift(HEAD 仍兜底),需保 HEAD 比对为「变化文件」而非全量;首日改造后仍一次全量 HEAD。

### 推荐组合
**① + ②(含 ② 附带清单)+ ⑤(upload 增量)= 根治;③(600s)+ ④(错峰)= 配套卫生**。全部实施后:持锁时间收敛到 git 段(分钟级,或更短),灾备 R2 与主链 R2 各自独立并发,锁队列回到「短暂偶发」而非「结构性不空」。验收判据:连续 3 个交易日 22:35~02:00 写库窗口可达 + 观察器连续采样出现空窗。

## 6. 同源任务确认

- **#129 P2 ①(灾备上传锁分离 + `--skip-if-locked`)与 #149 同源**:#149 的 105min 持锁段正是 #129 P2 ① 未实施的行为;§5 方案 ② 即 #129 P2 ① 内容。**建议 #149 与 #129 P2 批次合并实施**(同批锁分离改造,一处动多处,timer 错峰与锁拆分享同一回归面)。
- **#126(staticdata 收口)是被害方非同源**:收口动作与 async 的 git add 同仓互斥,队列长满导致拿不到窗口(#126 报告同述)。
- 无其他重复登记。

## 7. 复现段

所有数字的原始只读命令(云上 SSH 只读,本仓零写入除本文件):

```bash
# 云上定时任务权威表(53 timers,盘后时点见 §3)
ssh -i ~/tdsignal.pem -o BatchMode=yes ubuntu@122.51.111.173 'systemctl list-timers --all --no-pager | head -70'

# 持锁区间 = async/deploy 日志起止(日志写在持锁 exec 之后)
ssh -i ~/tdsignal.pem -o BatchMode=yes ubuntu@122.51.111.173 'cd /home/ubuntu/code/trade-data/data/logs && for f in staticdata_backup_async_20260930_192301.log staticdata_backup_async_20260930_234038.log staticdata_backup_async_20261001_003131.log; do echo "--- $f"; grep -m1 "staticdata_backup_async 开始" $f; grep "备份完成\|备份.*失败" $f | tail -1; done'

# step 打点(卡点=step3.5b upload_r2)
ssh -i ~/tdsignal.pem -o BatchMode=yes ubuntu@122.51.111.173 'grep "\[step\|⚠ PUT\|变更量" /home/ubuntu/code/trade-data/data/logs/staticdata_backup_async_20260930_192301.log | head -20'

# deploy 主链接力(21:08→21:40→22:14→23:02→23:40 无缝)
ssh -i ~/tdsignal.pem -o BatchMode=yes ubuntu@122.51.111.173 'cd /home/ubuntu/code/trade-data/data/logs && for f in deploy_20260930_2108.log deploy_20260930_2140.log deploy_20260930_2214.log deploy_20260930_2302.log; do grep -m1 "deploy.sh 开始" $f; grep "deploy.sh 结束" $f | tail -1; done'

# 排队超时实证(futures 20:05 排队等超 3600s 跳过,21:05:03 结束)
ssh -i ~/tdsignal.pem -o BatchMode=yes ubuntu@122.51.111.173 'grep -B2 -A6 "排队等锁超时" /home/ubuntu/code/trade-data/data/logs/futures_backfill_20260930_2005.log | head -20'

# 结构性反复(09-28/29/30 futures·etf·lhb 排队超时)
ssh -i ~/tdsignal.pem -o BatchMode=yes ubuntu@122.51.111.173 'grep -l "排队等锁超时" /home/ubuntu/code/trade-data/data/logs/*_backfill_2026092[89]*.log /home/ubuntu/code/trade-data/data/logs/*_backfill_20260930*.log 2>/dev/null'

# 逐文件 HEAD 比对量(单段 2.8~3.2 万)
ssh -i ~/tdsignal.pem -o BatchMode=yes ubuntu@122.51.111.173 'cd /home/ubuntu/code/trade-data/data/logs && grep -c "跳过 PUT" staticdata_backup_async_20260930_234038.log; grep -c "跳过 PUT" staticdata_backup_async_20261001_003131.log'

# 锁获取点(本地)
grep -rn "trade_deploy.lock" --include="*.sh" --include="*.py" /Users/linhuichen/code/trade/scripts /Users/linhuichen/code/trade/app/collector/index_backfill.py

# 当前锁状态(10-01 19:45 锁空闲,零字节,无持有者)
ssh -i ~/tdsignal.pem -o BatchMode=yes ubuntu@122.51.111.173 'lsof /tmp/trade_deploy.lock; ps aux | grep -E "with_lock|staticdata_backup_async|deploy.sh" | grep -v grep; ls -la /tmp/trade_deploy.lock'
```

**修复链说明**:本报告纯只读调研,无修复;若实施 §5 方案,需在锁拆分/时点变更后重跑 §7 复现段验证「观察器空窗出现 + 连板写库窗口可达」。

## 8. 维度清单完成度

| 维度 | 状态 |
|---|---|
| 锁获取点全量 grep | ✅ 14 处(§1) |
| 单次持锁时长实测(09-30 晚逐段) | ✅ 8 段(§2) |
| 调用方时点表(云上 timers + 脚本内链) | ✅(§3) |
| 单持有者 vs 叠加排队量化判定 | ✅ 双因叠加,数字支撑(§4) |
| --block-timeout 排队上限行为实证 | ✅ futures 20:05→21:05 超时跳过日志 |
| 结构性反复验证(多日) | ✅ 09-28/29/30 连续 3 天 7 条日志 |
| 根治方案 + 副作用 + 推荐 | ✅ 5 项(§5) |
| 同源任务核对 | ✅ #129 P2 ① 同源;#126 被害方(§6) |
| 只读合规 | ✅ 云上零写,本仓零提交,分支 main |
