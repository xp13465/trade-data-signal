# staticdata mac 侧写入路径调研(为 C 方案定稿)
调研人: researcher | 日期: 2026-09-26 | 全部只读(生产 staticdata mac/云上均未做任何写操作)

## 一、结论总览
1. mac 侧会 commit/push staticdata 仓库的脚本 = 2 个核心(staticdata_sync.sh / staticdata_backup_async.sh),
   **没有第三个 git 写入路径**(全仓 15 个 staticdata 引用文件逐一核验 + 无 hooks + 无 cron/launchd 引用)。
2. mac 数据**默认旧**: 实测 mac trade-data/static-site/data/ 最新 mtime = 9-23 09:36, 9-13 迁移后 mac 无自动任务,
   更新仅来自手动 deploy 残留(9-18/9-19/9-22 三笔)。
3. 两端差异方向钉死: 7/7 抽查文件全部 mac 旧、云上新(云上今天 17:12 还在推)。
4. **9-26 事故直接来源 = 手动跑 staticdata_backup_async.sh**(trigger=test 13:26 / manual-closeout 14:52),
   14:52 那笔 commit a2a57a0a0c 1955 文件, push 恰好被 non-fast-forward 拒(远端领先)才没覆盖生产。
   下次远端落后时再跑就能推上去 = 旧数据覆盖 DR 仓库。
5. C 推荐 = 结构根治(非生产机默认禁 git 段, 单一源守卫)+ 数据闸门(只增不覆盖), 云上行为零变化。
6. B 可行 = blobless clone(实测 3.2G 仓库只需 13MB 秒级对齐), 根治 fetch 失败。

## 二、问题1: mac 写入路径全清单(穷举完毕)
### A. 会 commit/push 的两个核心脚本
1. scripts/staticdata_sync.sh(行 108-122 git 段): rsync static-site/data/ → staticdata/data/ + `git add -A`
   + commit "data backup [$TRIGGER] ... - N files" + `push origin main`。
   调用方(全):
   - scripts/intraday_snapshot.sh:202 —— STATICDATA_SYNC_NONBLOCK=1, 盘中每 10 分钟同步 22 个文件
   - scripts/fetch_news.py:744 —— news-fetch 触发
   - scripts/gen_daily_brief.py:4348 + 4386 —— daily-brief 触发(含 run_log)
   - 可手动: bash scripts/staticdata_sync.sh <trigger>
2. scripts/staticdata_backup_async.sh(行 178-284 git 段): rsync DB/JSON + large-json .gitignore 区块 +
   R2 私有桶 + `git add -A` + commit + push(900s 超时保护)。
   调用方(全):
   - scripts/deploy.sh:961-991 —— push main 成功后触发(云上 systemd-run / mac nohup fallback)
   - 可手动: bash scripts/staticdata_backup_async.sh <trigger>
   → 9-26 13:26 trigger=test、14:52 trigger=manual-closeout 日志实证(直接打在 mac 生产路径, 非 /tmp 测试)

### B. 写 staticdata 仓库但非 commit/push 的路径
3. scripts/large_json_excludes.py 默认模式 —— 写 staticdata/.gitignore 受管区块(async step3.5a 调用; 可手动)
4. scripts/migrate_large_json_out_of_git.sh —— git rm --cached(一次性迁移, 人工跑, 自己绝不 commit/push)
5. scripts/upload_r2.py upload-large-json —— 读 staticdata 传 R2(不写 git)

### C. 只读引用(不写)
pick_repo.py / restore-large-json.sh(读) / check_large_json_excluded.py(机检) / schedule_monitor.sh(读心跳) /
overfit_monitor.sh(注释) / gen_schedule_stats.py(读日志) / update_all.sh(无 staticdata 段)

### D. 无第三个 git 写入路径的证据
- 全仓 scripts/ 15 个 staticdata 引用文件逐一核验(见上 A/B/C 分类)
- mac staticdata 仓库无 git hooks(ls .git/hooks 无非 sample 文件)
- ~/Library/LaunchAgents/ 无 plist 引用 staticdata; launchctl 活 job 只有常驻类
- worktree agent 测试已隔离(9-25 22:44 日志 STATICDATA_REPO=/tmp/largejson-test-staticdata)

## 三、问题2: 合法性判定(mac 数据新旧来源)
- mac trade-data/static-site/data/ 更新源:
  * 9-13 前 mac 是生产机: deploy 日志 9-12 17:50/18:14/21:07、9-13 02:08/05:00 等每天多次(定时任务痕迹)
  * 9-13 迁移云上后: mac 无自动任务(launchctl 活 job = agent-inbox-watcher/feishu-listener/thinking-proxy/
    sensenova-healthcheck/token-cache-stats/env, 均为常驻类; 盘后定时 plist 存在但未加载)
  * mac 手动 deploy 残留: 9-18 03:55 / 9-19 12:29 / 9-22 22:46 三笔(9-22 那笔 akshare RemoteDisconnected
    采集失败早退, 22:48 accum_nav 等部分产物落盘)
  * mac 数据最新 mtime = 9-23 09:36(auto_trade_steps.json), 之后静止(find -mtime -3 空)
- 结论: mac 数据默认旧; "mac 比云上新的合法数据"仅在用户手动跑生成器(deploy/gen_daily_brief 等)且
  云上尚未覆盖同一路径时出现(9-22 手动 deploy 即此例, 但 9-22 当天云上也已运行, 实际仍是 mac 旧)。

## 四、问题3: 两端实测差异(7 文件抽查)
| 文件 | mac md5/mtime | 云上 md5/mtime | 方向 |
|---|---|---|---|
| news_digest.json | 077e4c1de5d2 / 09-13 | 7913bd3fcbe0 / 09-26 17:01 | 云新 |
| overview.json | f87ba9369566 / 09-22 | 04d7ff74d1bc / 09-26 16:47 | 云新 |
| daily_brief.json | 13be2aa89059 / 09-11 | 345d39c7f5a2 / 09-24 20:40 | 云新 |
| boot.json | 5cda69355c17 / 09-22 | 4544681f80da / 09-26 16:48 | 云新 |
| summary.json | f1efb841d43d / 09-22 | 7996d3ec435c / 09-26 16:47 | 云新 |
| schedule_stats.json | d2802baee695 / 09-13 | 784f6721d4f0 / 09-26 17:00 | 云新 |
| accum_nav_map.json | 5adc1dfacd9c / 09-22 | 35117d12e440 / 09-26 16:49 | 云新 |
→ 7/7 全部 mac 旧、云上新。mac 事故 commit a2a57a0a0c 相对过期 origin(9-13) = 1697 A + 252 M + 8 D(迁移),
  均为 mac 旧镜像快照。云上 staticdata HEAD=77e8f77(今天 17:12 backfill), status 干净, ref 17:12 更新。

## 五、问题4: C 方案(候选评估 + 推荐)
### 候选对比
a) mac 侧 async/sync 跳过 git commit/push(只 rsync + R2)
   优: 结构根治, mac 不再有任何推生产 DR 仓库的路径; 数据不丢(磁盘留档 + R2 已上传); 实现最简
   劣: mac 合法数据不版本化(云上才是版本化职责方)
b) mac 只 fetch 不 push
   优: mac 保持只读镜像 + 自动跟进远端
   劣: 不解决"用户想从 mac 推合法数据"; 3.2G fetch 本身失败(B 问题)
c) mac 只 commit 本次 rsync 变化的文件(非 add -A)
   优: 缩小爆炸半径
   劣: 治标不治本——单文件仍可能用旧数据覆盖远端同路径(mac 9-22 overview.json 覆盖云 9-26)
d) push 前对比远端, 本地落后就跳过
   优: 数据层兜底, 防一切"旧覆盖新"
   劣: 单独用不可靠——"远端 HEAD 新" 不等于 "本地数据旧"; 需要 fetch(ref 新鲜), 而 fetch 本身失败(B)
### 推荐(综合 a+d+单一源, 三件套)
1. 结构根治: 新建 scripts/staticdata_write_guard.py(单一源, 风格同 large_json_excludes.py --check-staged):
   - --check-write-auth: 判定本机是否生产机(路径特征 /home/ubuntu/ vs /Users/linhuichen/)
     → 非生产机默认 rc=1(跳过 git 段, 仅 rsync+R2+降级通知), 云上 rc=0(行为零变化)
   - --check-fresh: 显式 STATICDATA_ALLOW_PUSH=1 时, 先 git fetch origin(失败即拒绝), 只推"远端不存在的
     新增路径(A)", 修改(M)中本地旧于远端同路径的排除出 add 清单 → 只增不覆盖
2. 收口: staticdata_backup_async.sh + staticdata_sync.sh 的 git commit/push 段前调用守卫(消除双实现,
   两脚本共用单一源, 与 feat/large-json-guard-sync 下沉风格一致)
3. 云上行为完全不变: 守卫在生产机路径判定 PASS, 原逻辑不删不改
### 满足硬约束
- 两脚本共用逻辑单一源(守卫进一个 py, sh 只调用)
- 云上行为零变化(生产机 PASS)
- 风格与 large_json_excludes.py --check-staged 同款

## 六、问题5: B 方案(3.2G 仓库 fetch 失败解法, 已实测)
### 实测: blobless clone 秒级成功
`git clone --filter=blob:none --no-checkout --single-branch -b main git@github.com:xp13465/trade-data-signal-staticdata.git /tmp/sd-blobless-test`
→ 成功, .git 仅 13MB(in-pack 13300 对象, 完整 commit+tree 历史), HEAD=77e8f77(与云上最新一致)
### 可执行步骤(推荐, mac 副本对齐远端)
1. 全新 blobless clone(13MB 秒级, 根治 3.2G 全量传输失败)
2. 数据层从云上 rsync(2G data/, 云上最新), 或 blobless clone + checkout(按需拉 blob)
3. 日常 mac 只读维护: fetch --filter=blob:none(增量小) 即可跟进, 不再全量
### 备选(社区解法, 缓解用)
- git config core.compression 0 / pack.windowMemory 10m / pack.packSizeLimit 20m
- git config http.postBuffer 524288000 / http.version HTTP/1.1(curl 18 HTTP/2 stream reset 案例)
- ulimit -n unlimited(mac 已 1048576, 满足)
- fetch 多次续传(fetch 失败对象保留, 重跑推进, SO 高票解法)
- git pull --depth=1 / fetch --depth=1(浅)
### 注意
- mac 旧副本的本地 commit a2a57a0a0c 不该保留(全是旧镜像), 替换前留档工作树(1963 文件)到 /tmp 即可
- 云上只读, 不动

## 七、硬约束遵守声明
生产 staticdata 仓库(mac /home... 云上)全程零写操作: 未 reset/checkout/commit/push/改文件。
ssh 云上仅跑只读命令(git log/status/ls/stat/systemctl list-timers)。
试验仅在 /tmp/sd-blobless-test(全新克隆)进行。
