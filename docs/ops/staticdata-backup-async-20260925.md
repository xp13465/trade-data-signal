# staticdata 备份拆出主链异步实施记录(pending #110,2026-09-25)

> implementer 实施落档。前置调研:docs/ops/update-all-staticdata-backup-eval-20260925.md(researcher,只读)。
> 本任务 = 把 staticdata 备份段(deploy.sh 原 L946-1005)拆出 deploy/update_all 主链异步执行,消除主链最大耗时单点。

## 改动文件
1. **新增 scripts/staticdata_backup_async.sh**(193 行):staticdata 灾备第2层备份异步本体
   - 逻辑 = 原 deploy.sh L946-1005 全量搬入(①rsync DB 到 staticdata/db/ ②cp 配置脱敏 ③rsync 全量 JSON ④git add+commit+push)
   - **云上路径回退 L44-46**(deploy.sh L951-957 同款):`STATICDATA_REPO` 硬编码路径不存在 → 回退 `${GIT_REPO}-staticdata`,防云上静默跳过
   - 持 `/tmp/trade_deploy.lock`(with_lock.py `--block-timeout 3600`):先经系统锁重入,deploy 触发时锁仍被 deploy 持有 → 阻塞等到 deploy 退出秒级延迟再开跑,零并发写
   - 积压兜底 L120-134:**变更文件 >5000 或 总字节 >300MB → 仅 rsync 磁盘留档 + notify --severe 告警,跳过 commit/push**(当日 git 历史缺一档,次日 rsync 全量自然追平,数据不丢);文件数阈值短路省 32k 次 wc
   - 失败告警:rsync/commit/push 任一失败 → `notify.py --severe --alert-issue`(写 latest.md,不静默,让 schedule_monitor 发现)
   - push 超时保护 900s(防卡 GitHub 22 端口死拽 deploy 锁,2026-09-15 事故同根因)
   - step 打点(`date +%s`)落日志,供复盘 rsync vs git add 谁是大头(报告推荐项 3)
   - 测试钩子:`STATICDATA_BACKUP_NOTIFY_DRY_RUN=1` → notify 走 --dry-run(沿用 WITH_LOCK_NOTIFY_DRY_RUN / ON_SKIP_DRY_RUN 惯例)
2. **改 scripts/deploy.sh**(L946-971,L946-1005 段替换):触发 async + 立即返回
   - deploy 内部触发(不是 update_all.sh)→ 全部 deploy 调用方(update_all/etf_national_team_backfill/futures_backfill/public_fund_daily/lhb_backfill/rzhb_backfill/public_fund_full/public_fund_quarterly)零改动全覆盖
   - 云上 systemd-run transient service(独立 cgroup,deploy 退出不清理);无 systemd(本地)fallback nohup
   - **update_all.sh 零改动**(任务约束,满足)
   - 原静态备份逻辑从 deploy.sh 彻底删除(零 STATICDATA 残留引用,不留双跑)
3. 顺手修一个原代码潜在 bug:async 脚本内补 `mkdir -p config/launchd`(原 deploy.sh 假设目录已存在,新仓库首跑 sed 重定向失败)

## 兜底阈值定值+依据
- **文件数 >5000 或 字节 >300MB**(各一,OR)。依据(报告 §三(b)):正常日 58~487 文件;9-22 积压 25789 文件。5000 = 正常日最大值 ~10x,积压 ~1/5,间隔清晰。字节口径 = 变更文件当前 `wc -c` 总和(保守:大 JSON 只改 100B 也按全文件计,与 GitHub 仓库膨胀口径一致,宁高勿低触发跳过)。
- 9-22 的 165MB(82+83MB kelly JSON)低于 300MB 阈值,不误触发;周日 force_full 全量 + 大 JSON 才可能触发。

## 锁方案+持锁时长
- 锁文件:`/tmp/trade_deploy.lock`(与 deploy/staticdata_sync/intraday_snapshot/kelly_intraday_rerun 全部消费者同一把锁,天然串行)
- 模式:with_lock.py `--block-timeout 3600`(阻塞 + 排队超时护栏;deploy 触发时锁仍被 deploy 持有 → 阻塞秒级后开跑)
- 持锁时长:async 自身 ~20-35min(rsync 2.7G 固定开销 + git add/push);积压走 skip 路径 ~20-30min(不 commit)
- 排队:17:50 async 未跑完时 20:07 etf 又触发 → with_lock 排队串行,不并发堆叠

## §14 时点检查结论
云上 timer 实测(`ssh systemctl list-timers`)+ 原有锁消费方分析:
- **deploy 触发 async 的时点链**:16:30 public-fund / 17:50 update-all / 19:15 rzhb / 20:05 futures / 20:07 etf / 22:00 public-fund-full。每个 deploy 主链缩短 ~30-35min(staticdata 不再同步跑)。
- **async 锁占用总时长 ≈ 原 deploy 持锁时长**(现 deploy 主段+async 接棒,合计与原来相当);新增碰撞点:
  - **20:05 futures async + 20:07 etf deploy 的 async 会排队**:A(futures,~20:10-20:45)→ B(etf,~20:45-21:20 起)。与现状(两 deploy 排队的静态段)相当,无新碰撞类别。
  - **20:40 daily_brief / 20:45 brief-push 的 staticdata_sync 可能等锁 ~5-10min**(等 etf async 释放),60min 超时内正常完成,不告警。
  - **17:50 update_all async 不会撞 20:05**(最坏 75min 积压也 19:30 前释放);backup_db 21:00 不持 deploy 锁(已核实),无影响。
- 结论:无新增 §14 冲突类别,仅锁占用窗口后移;等锁时长仍在 with_lock 3600s 超时内。**无需改时点/错峰**。

## 自验 7 条(全部 /tmp 临时仓库,未碰生产 staticdata/未跑真 deploy.sh)
测试环境:`/tmp/staticdata-async-test/`(fake-repo 假数据 + 临时 staticdata git 仓库 + 临时 bare remote,STATICDATA_REPO env 指向临时仓库,STATICDATA_BACKUP_NOTIFY_DRY_RUN=1)

| # | 项 | PASS/FAIL | 证据 |
|---|---|---|---|
| ① | 正常路径 rsync+commit+push | PASS | commit `6b70890` [test-normal] 落临时 remote bare;重构后 `e76a39c` [test-refactor-normal] 落 remote2 |
| ② | 兜底路径 >5000 文件只 rsync 不 commit+告警 | PASS | 5041/5043 文件触发「变更量超阈值跳过 commit」,bare 无新 commit,5001 bulk 文件留 staticdata/data/ 磁盘,notify dry-run 告警发出 |
| ③ | 锁:等待/并发不破坏 | PASS | 持锁 25s 期间启动 async → 阻塞 ~16s 后开跑(总 25.7s);并发 par-a/par-b → par-b 脚本体启动 13:24:58 > par-a 完成 13:24:57,串行证据;临时仓库 git fsck 干净 |
| ④ | 云上路径回退 STATICDATA_REPO 不存在+GIT_REPO 有值 | PASS | STATICDATA_REPO 指向不存在路径 + GIT_REPO=test-git(sibling test-git-staticdata 存在)→ 自动回退到 sibling,commit `48081bb` 41 files 落 remote2 |
| ⑤ | 失败告警 --severe + dedup-key | PASS | origin 指向坏 remote → push rc=128 → `[告警] staticdata备份失败`(notify dry-run 发出)+ 脚本 exit 1;dedup-key `staticdata_backup_fail`/`staticdata_backup_oversize_skip` 传参正确(notify.py L718/743 生产模式执行 check_dedup/update_dedup,dry-run 全路径只读 L977 不污染真实 state) |
| ⑥ | deploy.sh 改动后主链其余步骤不受影响 | PASS | `bash -n` 双文件通过;代码走查:替换块为纯 fire-and-forget if/else,后续 feishu 重启/R2 收尾告警/board_etf_map 告警/exit 全在且用到的 $NAME/$LOG/$GIT_REPO/$REPO 均在文件头部定义 |
| ⑦ | 老路径彻底移除不留双跑 | PASS | `grep STATICDATA scripts/deploy.sh` = none(零残留);备份逻辑唯一在 async 脚本 |

## 举一反三(§23.3)
### 1. scripts/staticdata_sync.sh 与本次关系
- **它是独立生成器链路**(news-fetch/daily-brief/intraday-snapshot 只写 static-site/data + R2,不跑 deploy)的 staticdata 同步入口,触发名 news-fetch/daily-brief/intraday,均传**具体文件列表**(files 模式,轻量 cp,不走全量 rsync)。**与 deploy 的 staticdata 段不是重复实现,不删不改**。
- 它与 async 持同一把 /tmp/trade_deploy.lock → **不会并发写**(async 跑时它阻塞等锁,现状同:deploy 静态段跑时它也阻塞)。异步化对它零影响。
- 注意:fetch_news.py L744 调 staticdata_sync **阻塞模式**,async 持锁 ~30min 时会等(与现状 deploy 静态段堵它一致,窗口后移);报告 §四.2 已列「给 fetch_news 改 NONBLOCK」为后续项,本次不改。

### 2. deploy.sh 其他「非核心步骤同步阻塞主链」同类项(只报告不改)
| 项 | 位置 | 耗时 | 结论 |
|---|---|---|---|
| fund-nav R2 上传 | deploy.sh run_r2_upload upload-fund-nav | 曾 6225s | **已拆**(4fdb52d88),本次不重复 |
| R2 upload-data-large / verify-r2 | deploy.sh 中段 | 周日 force_full 10-20min | 后续候选,非本次 |
| export_fund_nav / etf_score_list --full-market / 基金评分 | deploy.sh 中段 | 99s/124.5s/2min | 分钟级,不值得拆 |
| push_schedule_stats | update_all L372 | 秒级 | 不值得 |
| verify-r2 | deploy 收尾 | 数分钟 | 后续候选 |

### 3. 谁在读写 staticdata 仓库(异步化影响面)
| 消费者 | 操作 | 异步化影响 |
|---|---|---|
| scripts/deploy.sh | 曾是写(静态段)→ 现仅触发 async | 不再直接写,零影响 |
| scripts/staticdata_backup_async.sh(新) | 写(commit+push) | 本体 |
| scripts/staticdata_sync.sh | 写(news-fetch/dayly-brief/intraday 文件级) | 同锁串行,等 async 释放后照跑,零破坏 |
| scripts/intraday_snapshot.sh | 写(NONBLOCK,锁忙跳过) | 照旧,锁忙时跳过由后备 deploy 兜底 |
| scripts/gen_daily_brief.py | 写(20:40,files 模式) | 可能等多 5-10min(etf async),60min 超时内完成 |
| scripts/gen_schedule_stats.py | 只读(监控告警正则匹配) | 零影响 |
| scripts/pick_repo.py | repo 路径解析 helper | 零影响 |
| staticdata 库内 fetch_data.sh / gen_data_manifest.py | 消费(复原脚本,读 R2 不读 git 提交时点) | 零影响(报告 §四.1 实证) |

## 遗留建议(需主控拍板)
1. **>50MB kelly 大 JSON(signal_kelly_trades*.json 82/83MB)入 staticdata 仓库 .gitignore**(仅 rsync 磁盘留档,同 *.gz/index-* 先例;报告 §四.4 推荐「顺手根治」,本次按任务约束未动)——能治仓库 3.2G .git 持续膨胀 + GitHub 大文件警告。
2. **fetch_news 的 staticdata_sync 改 NONBLOCK**(报告 §四风险1 后续项):async 持锁 ~30min 时 news-fetch 每天被挡一档,改 NONBLOCK 可根治。
3. **20:40 daily_brief staticdata_sync** 若连续验证被 etf async 拖累超时,同 2 方案(NONBLOCK 或 async 内按 trigger 降优先级)。

## 复现段(可 grep 自验)
```
# 临时测试环境(已留 /tmp/staticdata-async-test,可直接重跑)
REPO=/tmp/.../fake-repo GIT_REPO=/tmp/.../test-git STATICDATA_REPO=/tmp/.../staticdata \
 PY=.../trade/.venv/bin/python STATICDATA_BACKUP_NOTIFY_DRY_RUN=1 \
 bash scripts/staticdata_backup_async.sh <trigger>
# 生产只读核对(云上,勿跑命令本身):
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 "systemctl list-timers | grep trade-(update-all|etf|futures|public-fund)"
```