# #149a deploy 锁拆分 review(独立 reviewer)

日期:2026-10-02 | 分支:`feat/149a-deploy-git-lock-20261002`(commit `98e5ee4c7`,base `main@887664cdd`) | reviewer

## 0. 判定(第一行)

**有条件可上生产。** 并发段1 的核心威胁(R2 同 key 并发写互相覆盖成旧版)已被 **`upload_r2.py` 入口级 R2 上传互斥锁 `/tmp/trade_r2_upload.lock`**(2026-09-23 落地,生产中生效)化解 —— implementer **没有漏这把锁**,锁不在 deploy.sh 层而在 upload_r2.py 入口,deploy 段1 的全部 15 个 R2 通道命令都持它排队。单文件写全部原子(util_atomic tmp+fsync+os.replace),rsync 无 --inplace 原子替换。残留风险(上传串行链拉长/并发 export 目录混合/段2 超时丢失 R2_FAIL 明细)均有告警兜底、非静默,云上验证通过后可放行。**前提**:①云上 upload_r2.py 已是含 R2 锁版本(已确认云上 grep `_acquire_r2_upload_lock` = 2 处 + `/tmp/trade_r2_upload.lock` 已存在);②上线后按 §5 云上验证命令观测一轮盘后 17:50~22:00 锁队列与 deploy 日志。

## 1. 核心:外层锁拆除后的并发安全(最高优先)

### 1.1 R2 上传并发 —— 已安全(关键证据)

原设计 #149 §5① 的 `trade_r2_upload.lock` **已经存在并生产中生效**:
- `scripts/upload_r2.py:2984` `_acquire_r2_upload_lock()`:所有 `upload_*/verify_*/purge_*` 命令持 `/tmp/trade_r2_upload.lock`(env `R2_UPLOAD_LOCK` 可覆写)排队,默认 timeout 7300s,fail-closed(超时 exit 1 不无锁上传)。非 skip-if-locked 的 deploy 日链通道保留排队语义。
- 云上实测:upload_r2.py 含该函数(2 处),`/tmp/trade_r2_upload.lock` 锁文件在 → **锁已在生产生效**,早于本分支落地。
- 后果:任意两个 deploy 的段1 并发调 upload-all-data 等,后到者排队等先到者传完,同 key 绝不并发写 → **不会出现「后完成者反而内容旧=版本回退」的随机竞争**。上传链最终读「最后一次 export 完成后的 static-site/data 目录」,线上最终一致于最后完成的 export 产物。

### 1.2 并发写 static-site/data/*.json —— 单文件原子,目录级混合被后完成上传抹平

- `export.py` 全部 353 产物走 `util_atomic.py` `atomic_write_text/atomic_write_json`(同目录 `{path}.{pid}.{rand}.tmp` + write+flush+fsync+`os.replace`),**无半截 JSON**。
- rsync 无 `--inplace`(deploy.sh 两处 rsync 均 `rsync -a --checksum` / `rsync -a --exclude=...`),默认临时文件+rename,**原子**。
- 残余:`--incremental` 增量导出下,两进程交错写同一目录 → 文件集可能短暂混合;`_save_manifest`(`static-site/export.py:936` atomic_write_json)共享 manifest 有低概率竞态(多算=安全,少算=依赖表 MAX(date) 未变才发生,被后完成 upload 的「全量目录」覆盖抹平)。
- build_min.py(段1,写 min JS)是**非原子裸写**(`build_min.py:235` `open(dst,"wb")`),但两进程同源(git HEAD 读源)输出内容相同,覆盖顺序无差异,实际无害(文件小、ms 级写完)。

### 1.3 真实并发对(云上 systemctl list-timers 实测时点,2026-10-02 周五)

| 对 | 时点 | 段1 重叠 | 后果 |
|---|---|---|---|
| update_all(主链) vs lhb-backfill | 17:50 vs 18:30 | 重叠(update_all 尾部 vs lhb 全周期) | export 混合被 lhb 的 upload 抹平;lhb 数据当晚正常上线 |
| lhb vs rzhb | 18:30 vs 19:15 | 临界(update_all 延迟会压入) | 同上 |
| futures vs etf-national-team | 20:05 vs 20:07 | 几乎同时全重叠 | 同上;R2 上传经锁串行 |
| public-fund-full(22:00)/quarterly(03:00) | 22:00 / 03:00 | 与前段错开 | 无 |
| **昨天实测排队延迟**(改前,佐证 #149) | lhb 18:30→19:30、futures 20:05→21:00、etf 20:07→21:30 | 锁排队 1~1.5h | 改后段1 锁外准点,排队只落在秒级 git 段 |

### 1.4 git 段(段2)串行

所有调用方的段2 持同一把 `/tmp/trade_deploy.lock`,与 staticdata async/sync 的 git 段同队列,秒~分钟级;不再有小时级持锁者。符合 #149 根治目标。

## 2. 其它必查项结果

### 2.1 段2 变量/函数作用域完备性(独立复核)

对 feat 分支 `deploy.sh` 753-1118 行(段2)全部 `${VAR}` 引用与段1/公共区定义逐一比对:
- 公共区(顶部):REPO/GIT_REPO/PY/LOG/NAME/git_fetch_timeout/git_push_timeout ✓
- env 恢复:R2_FAIL←DEPLOY_R2_FAIL、MAP_STALE←DEPLOY_MAP_STALE ✓
- 段2 自定:DATA_FILES/pop_rebase_stash/COMMIT_*/PUSH_RC/CUR_BRANCH/STASH_*/REBASE_*/CONFLICTED*/NON_DATA*/_FEISHU_*/_vc_* ✓
- **未发现任何「段1 定义、段2 引用」的漏网变量**(implementer 自测揪出的 git_fetch_timeout/git_push_timeout 是唯一一处,已移公共区;`run_r2_upload` 段2 不引用)。

### 2.2 锁点对照表 11/12 行核对

- 行 11(段1 锁外,0 持锁):`if [ "$GIT_PHASE" != "1" ]` 包住 139-742 行(export+校验+R2+rsync),末尾 `exec with_lock.py --block-timeout 3600 ... bash $0 --git-phase "$@"` ✓
- 行 12(段2 持锁秒~分钟):744 行起 `R2_FAIL/MAP_STALE` 恢复 + git add/commit/push + 收尾 ✓
- `LOCK="${DEPLOY_LOCK:-/tmp/trade_deploy.lock}"` 与 async/sync git 段同锁 ✓

### 2.3 失败语义(implementer 自述「推送时机/顺序/失败语义不变」)

- 推送时机:段1 全过 → 段2 push;段1 任一步 exit(export/校验/rsync 失败)→ 段2 不跑,git 不 push —— **与原一致** ✓
- 顺序:R2(段1)→ git(段2),R2 在 git 前 —— **不变** ✓
- 退出码:段1 失败非 0、段2 commit/push 失败非 0 → 调用方 DEPLOY_RC 告警 —— **不变** ✓
- **新增差异 1**:段2 排队超时从外层 `--block-timeout 600`(原整体跳过=数据+代码全不上线)变为内部 3600s(数据已上 R2,仅代码通道延迟,语义更优) ✓
- **新增差异 2(F1)**:段2 排队超时跳过(3600s)时,**段1 累积的 R2_FAIL 收尾 verify-channels/告警不会执行** → R2 失败通道明细丢失。with_lock 自身会发「排队超时跳过告警」(非静默,`with_lock.py:83` `_notify_block_timeout`),但**不含 R2_FAIL 通道明细**(明细在段1 日志可人工查)。概率极低(段2 排队 1h),属静默失败专查命中项,建议后续把 R2_FAIL 透传进 with_lock 超时告警或降 `GIT_LOCK_TIMEOUT`。

### 2.4 #119 rsync exclude 4 种子文件

- 4 个精确文件名 exclude(index_etf_map.json/stock_codes.json/trade.db/trade_dates.txt),不误伤其它;代码仓(GIT_REPO)侧保留 clone 种子不再被覆盖写 → 云上 git status data/ 不再 M 脏 → git pull 不再被挡 ✓
- 语义保持:消费方优先读 REPO 数据仓侧(`_trade_calendar_dates` 遍历 db_path.parent→ROOT/data→REPO/data 先命中);trade_dates.txt 有代码仓 fallback 消费方(nextday_plan_generator.py:169-170),exclude 后 GIT_REPO 侧停留 clone 时点,但 REPO 侧新版先命中 ✓
- **残余**:从 GIT_REPO 侧直接启动的进程读这 4 文件会拿到 clone 时点旧种子(行为与云上一致,风险低)

### 2.5 全仓残留扫描

对 feat 分支全仓 `with_lock ... trade_deploy.lock ... deploy.sh` 形态 grep:
- 10 处调用方(update_all/futures/etf/lhb/rzhb/public_fund_daily/full/quarterly/pipeline/index_backfill.py)全部拆除外层锁 ✓(与 diff 逐一核对)
- 保留原状且不调 deploy.sh 的持锁方:kelly_intraday_rerun.sh(`--nb` 盘中防撞)、staticdata async/sync(git 段同锁,正确)、intraday_snapshot.sh/gold_night.sh(进程互斥形态,非调 deploy 外层锁)✓
- **无漏网**
- deploy.sh 963-1044 行 async(staticdata 备份)触发段在新两段式中落在段2(锁内),async 等 deploy 段2 释放锁后开跑;多触发 with_lock 排队不堆叠 —— 语义一致 ✓

### 2.6 对外行为新增(报告未声明项)

- **段1 并发 export 目录混合中间态**:static-site/data 目录在两 deploy 交错 export 期间是混合文件集,但被后完成 upload 抹平(见 1.2)。这是本次改动唯一的**行为新增**(原单进程无此中间态),风险有告警兜底,云上验证时可观测。
- **LOG 跨分钟分文件**:段1 与段2 重入若跨分钟,`STAMP` 重新计算 → `LOG` 指向不同文件(`deploy_<T1>.log` / `deploy_<T2>.log`)。149a 报告 §2.2「LOG 经重入沿用同一文件」**不准确**(顶部重新定义会重算 STAMP)。排障需翻两个日志文件,建议后续段2 沿用段1 LOG(env 传递)。

## 3. 置信度过滤

另 4 个低分项(<80)已滤:build_min 并发非原子写(无害,同源)、GIT_REPO/data 镜像 rsync 旧版覆盖新版(消费方优先 REPO 侧)、R2 锁排队极端超时 7300s(周末并发概率极低)、concurrent manifest 竞态多算(安全)。

## 4. findings 汇总(trace + verifier)

| # | finding | 置信度 | trace(diff_range) | verifier(command/expected/observed) |
|---|---|---|---|---|
| F1 | 段2 排队超时(3600s)跳过时 R2_FAIL 收尾告警不执行,通道明细丢失(替代为 with_lock 排队超时告警,非完全静默) | 75 | deploy.sh 741-746(exec→段2),with_lock.py:83 | 预占 trade_deploy.lock 1h 后跑段1→段2;预期 with_lock 告警但不含 R2_FAIL 明细;代码路径确认,概率极低 |
| F2 | STAMP/LOG 跨分钟分文件,149a 报告「LOG 沿用同一文件」说法不准确 | 80 | deploy.sh 顶部 STAMP/LOG 定义 + 741 exec | `date +%Y%m%d_%H%M` 跨分钟重入 → LOG 不同;diff 确认顶部重新定义 |
| F3 | 并发 export 目录混合中间态(行为新增) | 90 | deploy.sh 139 段1 if 块 / static-site/export.py --incremental | 两个 deploy 并发段1;预期单文件原子无半截、目录短暂混合;observed:util_atomic+rsync 无 --inplace 确认 |
| F4 | R2 锁已存在且生效(非漏锁) | 100 | scripts/upload_r2.py:2984 _acquire_r2_upload_lock | ssh 云上 grep 函数=2 处 + /tmp/trade_r2_upload.lock 存在;expected 有锁、observed 有 ✓ |

## 5. §14 生产稳定性与上线验证

- deploy.sh 生产主链,改动分级 **C 级(数据/后端/定时任务)**。影响老功能面:全部 10 个盘后/盘中 deploy 调用方(锁形态)、staticdata async/sync 的 git 段(同锁串行)、R2 上传串行链、云上 git pull(#119)。
- **时点**:review 全程只读,未触发生产 deploy;上线推送建议走主控 main-merge.sh 安全窗口。
- **上线后必验(云上)**:①一轮盘后 17:50~22:00 观察 deploy 日志:段1「锁外 export+R2」与段2「锁内 git」打点齐全、段2 持锁秒级;②`systemctl list-timers` 各 backfill 准点(不再 1~1.5h 排队);③云上 `git pull` 不再被 data/ 脏 M 挡;④R2 上传链不出现 verify-r2/upload-* 排队超时告警。

## 6. 复现段

- 本 review 全部证据取自:feat 分支代码 `git show 98e5ee4c7:scripts/deploy.sh` 全文通读 + 段2 变量引用机械提取 + 云上只读 `systemctl list-timers` / grep upload_r2.py / ls 锁文件。
- 并发安全结论基于代码事实(R2 锁/原子写/rsync 无 --inplace),未真跑并发 deploy(§14)。
