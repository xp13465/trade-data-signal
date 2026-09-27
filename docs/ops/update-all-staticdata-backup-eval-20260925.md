# update_all 主链 staticdata 备份积压拖慢:方案评估与影响面(pending #110)

> 2026-09-25 researcher 调研落档(只读,未改任何代码/数据)。背景:pending #110「update_all 主链 staticdata 备份积压拖慢」。结论均带证据(云上日志/commit 时间戳/代码行号)。

## 摘要(推荐)
- **staticdata 备份段(deploy.sh L946-1005)确实是 update_all 主链关键路径,且在 9-23 拆掉 fund-nav 上传后,它现在是主链最大单点**:9-24 update_all 总 71min,deploy 段 41.5min,其中 staticdata 段 ≈31-35min(占主链 ~44-50%)。
- **推荐方案 = (a) 拆出主链异步 + (b) 积压超阈值跳过 commit 仅磁盘留档作为兜底**,照 commit 4fdb52d88(fund-nav 异步先例)模式。**不选 (c) 独立定时器**。
- 关键事实:**staticdata 段有 ~20min 固定开销(rsync 全量比对 2.7G data + ~3GB DB,git add 32k 文件/3.2G .git),即使只变 58 个文件也照样付**(9-25 05:00 deploy 实测)。异步化只解决"主链不等",不解决备份自身耗时;需配合"触发点放 deploy.sh 内部(覆盖全部 5 个 deploy 调用方)"+"跳过 commit 兜底"一步到位。

## 一、耗时构成拆解(问题 1)
证据基于云上生产日志(/home/ubuntu/code/trade-data/data/logs/,update_all/deploy 主链日志)+ staticdata 仓库 git commit 时间戳。

| 日期 | update_all 总时长 | deploy 段 | staticdata 段 | staticdata commit(时间/文件数) | 备注 |
|---|---|---|---|---|---|
| 9-22 | 216min(17:50→21:26) | 18:14:51→21:19:03(184min) | ≈20:0x→21:19(≈70-75min) | 160030698 21:12:15 / 25789 files | fund-nav 上传 6225.8s 仍在主链(占 deploy 56%);9-21 deploy 因 build_board_etf_map 失败提前终止→9-22 积压 |
| 9-23 | 67min(17:50→18:56:51) | 18:15:35→18:49:49(34min) | ≈18:19→18:49:49(≈30min) | 62b595c3b 18:43:01 / 334 files | fund-nav 已异步(4fdb52d88 当日 merge) |
| 9-24 | 71min(17:50→19:01:41) | 18:13:34→18:55:05(41.5min) | ≈18:19→18:55(≈35min) | 64469f4ff 18:49:33 / 487 files | **staticdata 占主链 ~50%** |
| 9-25 05:00 | (凌晨补跑) | 05:00:17→05:23:40(23min) | L792→L826(≈22min) | b754eb5a3 05:22 / 58 files | **只变 58 文件也要 ~22min,证明固定开销 ~20min** |

段内 4 步(commit 时间戳=rsync 全完成+git add 完成时刻;deploy 结束=push 完成时刻):
1. rsync DB(deploy.sh L963):~3GB(sentiment 127M/etf_national_team 242M/stock_daily 133M/public_fund 2.5G,du -sh 实测)。同机本地拷贝+比对,量级分钟级,不是大头。
2. cp config + rsync 全量 JSON(L969-979):data/ 2.7G/32125 文件,每次 deploy **全量比对**(无白名单/无增量排除)。9-22 写 25789 文件(积压)拉长到 ~60min;正常日写几十~几百文件仍占 ~20-25min(固定比对开销)。
3. git add -A(L982)+ commit(L990):32k 文件工作区 + 3.2G .git,每次固定开销 1-3min 起;commit message 时间戳=add+commit 完成。
4. push(L991):9-24(487 files,含 2 个 82MB JSON)≈6min;9-22(25789 files)≈7min。9-22 日志 L3115-3119 有 GitHub 大文件警告(signal_kelly_trades.json 82.56MB / signal_kelly_trades_sdc.json 83.67MB > 50MB 建议上限)。
- **9-22 积压放大点 = rsync(25789 文件全量写盘)+ push(大 commit)**;git add/commit 相对固定。
- **诚实标注**:rsync 与 git add 谁占"固定 20min"的大头,当前日志无逐行时间戳无法精确拆分(rsync 静默、deploy 日志无秒级打点),需 implementer 实施时在 async 脚本内加 `date +%s` 打点实测。9-25 05:00 的 22min(58 files)证明固定开销确实存在且不小。

## 二、阻不阻塞主链(问题 2)——是,且在关键路径上
- **调用链**:update_all.sh L146 `with_lock.py --block-timeout 3600 /tmp/trade_deploy.lock bash deploy.sh all` 后 `DEPLOY_ALL_RC=$?` **同步串行等待**;deploy.sh 内部 L944 push main 完成后紧接 L946-1005 staticdata 段,之后仅 feishu 重启(L1006-1037,不依赖 staticdata)与收尾告警(L1039-1072,不依赖 staticdata)→ **staticdata 段之前无步骤依赖它,它是纯 side-effect 却同步执行,实打实卡在主链 wall clock**。
- 旁证:9-24 傍晚 news-fetch 的 staticdata commit 有缺口(17:45→18:01→19:05,缺 18:15/18:30/18:45 三条)——deploy 18:13-18:55 持 /tmp/trade_deploy.lock 期间,news-fetch 调 staticdata_sync.sh 被锁阻断约 1 小时。staticdata 段拖多久,这条锁链上的其他消费者就等多久。
- deploy.sh 调用方共 5 个(都持同锁调 `deploy.sh <name>`):update_all L146 / etf_national_team_backfill L123 / futures_backfill L97 / public_fund_daily L82 / backfill_metrics(经 index_backfill.main L884 内部触发)。**每个都会跑 staticdata 段**。

## 三、方案评估(问题 3)
### (a) 拆出主链异步(照 fund_nav 先例 4fdb52d88)
- 模板已存在:fund_nav_upload_async.sh(49 行)= with_lock.py 互斥(/tmp/trade_fund_nav_upload.lock)+ notify.py --severe --alert-issue 告警(写 latest.md,不静默)+ 独立日志;update_all.sh L126-137 用 systemd-run transient service(云上,独立 cgroup,update_all 退出不清理)/ nohup fallback(本地)。
- **staticdata 与 fund-nav 的关键差异**:fund-nav 产物在 deploy 前就绪(update_all export 后触发);staticdata 备份的是 **deploy 刚 push 完的最终产物**,所以**触发点应放在 deploy.sh 内部(把 L946-1005 段替换为"触发 async + 立即返回")**——这样 5 个 deploy 调用方全部天然覆盖,不用改 update_all/etf/futures/public_fund/backfill 任何一处。
- 谁保证跑完:systemd-run transient service + 失败 notify --severe(不静默,同 fund_nav L43-46)。
- 并发打架:async 持 /tmp/trade_deploy.lock;deploy 触发 async 时锁仍被 deploy 持有 → async 的 with_lock 阻塞等到 deploy 结束(秒级延迟)再开跑,零并发写;多次触发(如 17:50 的 async 还在跑时 20:07 etf deploy 又触发)→ with_lock 排队,不并发。
- **风险 1(必须处理)**:async 仍持锁 ~20-30min,news-fetch/其他 staticdata_sync 消费者每天在 18:55-19:2x 再被挡 1 小时(现状 18:19-18:55 已挡,只是窗口后移;若想根治需给 fetch_news 的 staticdata 调用改 NONBLOCK,属后续项)。
- **风险 2**:只异步不缩时长,async 自身 20min 固定开销仍存在(只是不占主链)。见推荐方案配套。

### (b) 积压超阈值跳过当次仅告警
- 阈值建议:async 内检测待提交文件数 > 5000 或待传字节 > ~300MB → 只 rsync 磁盘留档 + notify 告警,不 commit/push(次日 deploy rsync 全量自然追平,数据安全无损,只 git 历史缺一档)。
- **收益小**:跳过 commit 只省 push(~6-7min)+ git add,但 rsync 全量 20min 固定开销照付。**不解决主链问题的根**。
- **风险**:跳过窗口=灾备第 2 层 git 历史缺口,而积压恰恰是大变更时刻。**只适合做 (a) 的兜底,不适合单独作为主方案**。

### (c) 备份失败独立补跑/不进主链(独立 timer)
- 与 (a) 区别:(a) 是"异步照跑",(c) 是"完全独立调度(独立 timer,deploy 不管)"。
- **不推荐理由**:①备份完整性依赖"所有当日 deploy 都完成"的时点(update_all 18:55 / etf 20:07 / futures 02:15 / public_fund 16:30),独立 timer 要么早(漏当次产物)要么晚(备份滞后);②云上 21:00 已有 backup_db + daily_brief 20:40 + fapi 18:10 + lhb 18:30 + lab 19:00 等多个 timer,再加一个备份 timer 撞车面大(§14 生产稳定性 P0);③(a) 已含失败告警+补跑指引,(c) 不更彻底只是更绕。

### 推荐(一步到位合集)
1. 新建 `scripts/staticdata_backup_async.sh`(= deploy.sh L946-1005 逻辑 + STATICDATA_REPO 云上回退 L951-957 + with_lock /tmp/trade_deploy.lock + notify --severe 告警 + 独立日志 + commit 前变更量检测)。
2. deploy.sh 把 L946-1005 段替换为"systemd-run/nohup 触发 async + 立即返回"(覆盖全部 5 个 deploy 调用方,update_all 零改动)。
3. async 内加 **step 打点日志**(date +%s),实施时实测 rsync vs git add 谁是大头,若 git add 大仓库是主因,评估"只 add 变化子目录"或"降频 rsync DB"(DB 有独立 backup_db.sh 21:00 第 3 层兜底)。
4. **(b) 兜底**:变更量超阈值 → 仅 rsync 磁盘留档 + 告警不 commit(防大 push 拖死 async 自身)。
5. **不选 (c)**。

## 四、影响面/风险面(问题 4)
1. **消费方**:staticdata 仓库消费方 = ① `fetch_data.sh`(仓库根,复原脚本;数据本体从 R2 公开桶 ssd.fx8.store 按 manifest.json 下载,sha256 校验,不实时读 git 提交)② 用户/同事查看提交记录(用户原则:static-site/data 下产物都应进 staticdata)③ `gen_data_manifest.py`(手动)。**无脚本热依赖 git 提交时点**。
2. **云上回退逻辑(deploy.sh L953-957,GIT_REPO 派生 sibling)**:async 脚本照抄 staticdata_sync.sh L29-34 同款回退即可成立(云上 GIT_REPO=/home/ubuntu/code/trade-data-signal → ...-staticdata 实测存在)。
3. **静态站/前端**:无依赖(staticdata 不供前端,前端走 R2/static-site/data)。
4. **git add -A 大仓库已知坑**:staticdata 仓库 .git 已 3.2G(8.8G 总)、data/ 2.7G/32125 文件;9-22 push 触发 "Auto packing the repository in background"(git gc 后台);signal_kelly_trades*.json 82MB/83MB 每次变更都进 git 历史,GitHub 已告警(>50MB 建议上限);长期看 .git 会持续膨胀——**建议把 >50MB 的 kelly 大 JSON 加入 .gitignore(仅 rsync 磁盘留档,同现有 *.gz/index-* 先例),这是本次顺手该根治的同类病灶**。
5. **本机 staticdata 副本已陈旧 12 天**(最后 commit 9-13 news-fetch),生产在云上,本机纯开发(memory local-dev-cloud-prod-split)——改动只需在云上生效,本机无热消费方。

## 五、同类错误面(问题 5,§23.2 举一反三)
update_all 主链"非核心步骤同步阻塞"逐项核查:
1. **staticdata 备份段(本次,30-35min)= 最大同类项,唯一值得本次打包拆的**。
2. fund-nav 上传:已拆(4fdb52d88,先例)。
3. deploy R2 upload-data-large / upload-kelly-parts / upload-kelly-parts-sdc:已按字节量估算超时(9-23/9-24 优化,run_r2_upload 不传显式超时走 R2_BYTES_TOTAL 估算;9-23 21:00 backfill_evening 近全量 190MB 曾 900s 被 kill 事故已修)。**周日 force_full 全量仍可能拖 10-20min**,列为后续候选(非本次)。
4. export_fund_nav(桶化后 256 桶,9-24 实测 99.2s)+ etf_score_list --full-market(9-24 实测 124.5s)+ 基金评分 top2000(2min):分钟级,不值得拆。
5. push_schedule_stats(update_all L372):秒级。
6. verify-r2(超时 7200s,9-24 补传 33 个):9-24 几分钟,后续候选。
**结论:本次只需拆 staticdata 段;其他大项已优化/已拆,不做打包。**

## 复现段(关键结论怎么查的)
```
# 云上生产日志 + staticdata 仓库 git 时间戳(只读):
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173
# 9-22~9-24 主链时点:
grep -n -E 'O1 统一|deploy.sh 开始|deploy.sh 结束|staticdata 备份完成|update_all.sh 结束' /home/ubuntu/code/trade-data/data/logs/update_all_2026092{2,3,4}_1750.log
# 9-22 fund-nav 上传 6225.8s(占 deploy 段大头):
grep 'fund-nav' /home/ubuntu/code/trade-data/data/logs/deploy_20260922_1814.log
# staticdata commit 时间戳/文件数(9-22 积压 25789 文件 vs 正常日 334/487/58):
cd /home/ubuntu/code/trade-data-signal-staticdata && git log --since='2026-09-20' --format='%h %ci %s' | grep '\[all\]'
# 9-24 傍晚 news-fetch 缺口(证明 deploy 持锁阻断 staticdata_sync 消费者):
git log --since='2026-09-24 17:30' --until='2026-09-24 19:30' --format='%ci %s'
# 9-25 05:00 只变 58 文件仍 ~22min(固定开销证据):
grep -n -E 'deploy.sh 开始|deploy.sh 结束|staticdata 备份|data backup \[' /home/ubuntu/code/trade-data/data/logs/deploy_20260925_0500.log
# 灾备消费方/复原脚本:
head -40 /Users/linhuichen/code/trade-data-signal-staticdata/fetch_data.sh
# 模板先例完整 diff:
git show 4fdb52d88 -- scripts/deploy.sh scripts/update_all.sh scripts/fund_nav_upload_async.sh
```
