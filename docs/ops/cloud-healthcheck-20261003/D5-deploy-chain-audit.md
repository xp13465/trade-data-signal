# D5 发布/部署链路与回滚体检(2026-10-03)

> 调研:researcher | 只读(云上零写,本仓除本文件零写)| 报告路径:`docs/ops/cloud-healthcheck-20261003/D5-deploy-chain-audit.md`
> 维度:发布链全图 / 闸门逐个失效测试 / 位置与生产目录验证 / 守卫自锁 / 回滚能力 / 三站一致性 / 未收口项 / 反证项

## 0 结论速览

- **链路架构已正确**:main-merge.sh(本地唯一 push main 入口)→ 云上 deploy.sh 两段式(段1 锁外 export+校验+R2+rsync,段2 锁内秒级 git)→ R2/CF/三站。#149a 锁拆分 + export-guard 7 层防护均已合 main 且云上确认落地。
- **⭐fail-open 闸门清单(重点)**:
  1. **deploy.sh R2 上传 18 通道失败不阻断**(`deploy.sh:662-711` 累积 `R2_FAIL` 继续,收尾 `verify-channels` 对账后才告警)——有意设计,但 10-02 事故证明"普通增量 deploy + verify-r2 平日抽样 100"兜不住批量残留(`local-export-overwrote-r2-incident:120-121`)。
  2. **with_lock.py 排队超时 = 优雅跳过 exit 0**(`with_lock.py:149-152`)——deploy 段2 git push 若排队超 3600s,deploy 整体 rc=0 但 git 未推(数据已上 R2,代码 min 未推),属**静默丢代码**(概率低:段2 实测秒级)。
  3. **check_version_progress.py L222-224**:最近祖先链全无版本串 → `continue` 跳过该 asset(理论 fail-open,历史无触发)。
  4. **check_version_consistency.py L204-206**:源文件缺失 → skip 不 FAIL(与 build_min 缺源跳过语义一致,设计内)。
  5. **check_data_integrity.py `--deploy-mode` 下 warn 不阻断**(L2278-2279)——设计内;10-02 事故停更 6 天无人知根因是"FAIL 只 exit 无通知",L4(notify --severe)已上线收口。
  6. **main-merge feat base 新鲜校验纯软**(`main-merge.sh:183-187` BEHIND_COUNT>0 只 ⚠️ 提示)。
  7. **console 洁净度哨兵**:UNREACHABLE 放行 + `SKIP_CONSOLE_CLEAN=1` 逃生门(显式,打醒目提示)。
  8. **staticdata_write_guard rc=2 → 调用方 fail-open 继续**(文档明确"有意识取舍 L3",`staticdata_write_guard.py:35-38`)。
- **回滚能力结论**:能回滚,**最快 ~30 分钟**,不是"N 分钟内"。
  - 代码回滚:git revert → feat → main-merge(统一 bump 新串)→ push → 云上 pull,约 30-40min(过完整校验链)。最近实例:2026-09-16 `774e97ece revert(codex)`;最大批次:2026-08-25 `18cfa90e3 revert(#97移动端)`。
  - 数据回滚:R2 无 key 版本,靠恢复源 PUT 回。最近实例:**2026-10-03 04:55 restore fixed=541**(10-02 本机误传 R2 事故,清单 04:21 → 结果 04:55,约 34min,成功)。恢复源充足:云上树 / signal-backup pre-upload(7 天)/ R2 mac-backups / git 历史。
  - 版本串回滚:**只能是"前进式"**(check_version_progress A 拦倒退),SW 撕裂被规避,但无法"秒切上一版"。
  - **缺口:无集中"发布回滚预案"文档**(只有 backup-restore.md(DB)/r2-deployment.md(灾备)/data-deploy-quickstart(上线验证));SW 缓存+版本串回滚组合从未演练。
- **三站一致性(§22):核心校验器是死的**。`check_r2_consistency.py`(三版本一致性审计:local vs R2直链 vs CF r2-proxy)存在但**全仓无自动调度点**(schedule_monitor.sh 仅注释引用 L157,systemd 无)。§22 铁律"校验是否真在跑"答案 = **三站 HTTP 层一致性自动校验未跑**。
- **149d timer 错峰:未落地**(云上 timer 仍 futures 20:05/21:00、etf 20:07/21:30、public-fund-daily 16:30/17:00,与 149d 建议不符)。
- **149a 锁拆分 + export-guard:已落地且今天实测正常**。
- **反证**:今天(非交易日)主链全 PASS(check_version_consistency 3 项 + check_version_progress A/B),verify-r2 补传 35,段2 git 5 秒,退出码 0;云上 git = main fc951666a 干净;10-02 事故 562 key 已闭环(fixed=541 + skipped=21)。

## 1 发布链全图

```
本地改码(feat 分支, agent 只推 feat)
  │
  ▼
scripts/main-merge.sh(唯一 push main 入口,机制 D)
  ① check_disk_after(§14 安全窗口):交易日时点 15:35/16:00/17:50/20:35/22:00 ±5min → exit 3 拒绝;非交易日跳过
  ② fetch + main 最新化(rebase 冲突即停)
  ③ feat base 新鲜校验(⚠️ 只提示,BEHIND_COUNT>0 不阻断)
  ④ merge feat(冲突即停 §23.11)
  ⑤ 改前端源码(9 源) → build_min + bump_asset_version(机制C 版本串唯一入口)+ changelog 补登
  ⑥ 7: check_version_progress.py(机制A/B, FAIL exit 1)
  ⑦ 7.5 check_dual_src_sync.py(critical-css↔style.css, FAIL exit 1)
  ⑧ 7.6 check_doc_staleness.py(文档时点口径, FAIL exit 1)
  ⑨ 7.7 console 洁净度哨兵(exit1 违规阻断 / exit2 不可达放行 / SKIP_CONSOLE_CLEAN=1 逃生)
  ⑩ push main(non-ff → fetch+rebase+重试)
  ⑪ sync_cloud_pull:ssh 云上 git pull(失败 exit6 醒目告警)
  │
  ▼
云上 deploy.sh(定时:update_all 17:50 / backfill / public-fund 等,§14 时点)
  段1(锁外,可并发, export+校验+R2+rsync):
    export.py:生成 static-site/data JSON(EXPORT_SKIP_R2=1 跳过自动 R2;L0/L1/L2/L3 防本机误传)
    check_data_integrity.py(--deploy-mode, FAIL→notify --severe + exit 1)
    check_task_state.py + check_universe_alignment.py + check_dual_src_sync.py
    check_version_consistency.py(§24⑤, FAIL→notify + exit 1)
    占位残留闸门(check_data_gap_alerts --deploy-mode)
    rsync static-site/data → GIT_REPO(git 树,含 #119 4 文件 exclude)
    R2 上传 18 通道(run_r2_upload, 失败累积 R2_FAIL 继续= fail-open)
    verify-r2(平日抽样 100+changed, 自动补传, >50 差异告警)
    check_version_progress.py(FAIL exit 1)
    exec with_lock.py --block-timeout 3600 bash $0 --git-phase  → 段2
  段2(持 /tmp/trade_deploy.lock, 秒~分钟级):
    git add 6 个 min → commit → push main(分支校验 main + main:main 显式)
    staticdata_backup_async 异步触发(systemd-run)
    R2_FAIL 收尾 verify-channels 对账后告警 / MAP_STALE 告警
  │
  ▼
R2(signal-data) + upload 后 purge_cache(CF 边缘缓存) → 三站(ss.fx8.store 主站 / sss.sugas.site / s.sugas.site)
```

每步输入/产物/失败后果:
| 步骤 | 输入 | 产物 | 失败后果 |
|---|---|---|---|
| main-merge ①-④ | feat 分支 | merge 后 main | 时点冲突 exit3 / rebase 冲突停,人工处理 |
| main-merge ⑤ bump | 9 源变更 | 新版本串+新 min | 公示不上线(被 ⑥ 拦) |
| main-merge ⑥-⑨ 校验 | main 工作区 | PASS/FAIL | FAIL 阻断 push |
| main-merge ⑩ push | main | origin/main 前进 | 失败 fetch+rebase 重试 |
| main-merge ⑪ 云上 pull | origin/main | 云上 trade-data-signal 代码 | 失败 exit6 告警,云上跑旧校验 |
| deploy 段1 export | 采集 DB | static-site/data JSON | 校验失败 → 不上线,线上不变 |
| deploy 段1 R2 18 通道 | 云上树 JSON | R2 数据 + CF purge | 通道失败 → R2 缺文件,verify-r2 兜底 |
| deploy 段2 git | min+代码 | origin/main 前进 | 排队超时 → exit0 静默跳过(见 §2-12) |

## 2 ⭐闸门逐个失效测试表

| # | 闸门 | 拦什么 | 能否被绕过/失效 | 自己出错时 fail-open? | 位置 | 证据 |
|---|---|---|---|---|---|---|
| 1 | check_disk_after(§14) | 盘后时点 merge+push main | 非交易日跳过(§8 口径,设计内);交易日判断失败 exit2 保守拦不放开 | **fail-closed**(判断失败按交易日处理) | main-merge 第 2 步,merge/push 前 | main-merge.sh:97-123 |
| 2 | feat base 新鲜校验 | feat base 落后过多 | **纯软**:BEHIND_COUNT>0 只 ⚠️ echo 不阻断 | fail-open(有意,提示性) | main-merge 第 4 步 | main-merge.sh:180-187 |
| 3 | build_min+bump(机制C) | 改源码不 bump | 检测列表 9 源与 build_min 8 对已对齐;源不在列表=漏检(无实例) | 基本 fail-closed;build_min 失败 set -e 退出 | main-merge 第 6 步,merge 后 push 前 | main-merge.sh:217-241 |
| 4 | check_version_progress A(版本串倒退) | 版本串 < 祖先天花板 | **L222-224:最近祖先链全无版本串 → continue 跳过**(理论 fail-open);首提交 PASS(L351) | 非 git 仓库 → 宁拦不放(L344-347) | main-merge ⑦ + deploy 段1 末尾(双入口) | check_version_progress.py:197-224,344-352 |
| 5 | check_version_progress B(净回退) | 版本串未前进+内容改回旧态 | 版本串已前进 → 跳过 B(L277-280,设计);hist 无 → 宁拦不放(L301-303) | 同上 fail-closed | 同上 | check_version_progress.py:277-303 |
| 6 | check_version_consistency(§24⑤) | index 引用 vs sw CACHE_VERSION vs min 内容 | LEGACY_FILES(旧 md5 串)跳过(设计遗留);**L204-206 源缺失 → skip 不 FAIL** | **部分 fail-open(源缺失场景)**;sw.js 缺失/批次不一致 → problems FAIL | deploy 段1 L439-445 | check_version_consistency.py:96-160,204-226 |
| 7 | check_data_integrity(--deploy-mode) | 数据产物缺失/陈旧/结构 | **warn 不阻断(设计)**,只 FAIL 阻断;部分检查本身是 _warn(如 changelog 缺文件→warn) | 设计内 warn fail-open;FAIL 已加 notify --severe(L4) | deploy 段1 L323-329 | check_data_integrity.py:2278-2279 |
| 8 | check_task_state / check_universe / check_dual_src / 占位残留 | 任务状态/入样宇宙/双源 CSS/占位残留 | 无显式逃生门 | FAIL → notify + exit(基本 fail-closed) | deploy 段1 | deploy.sh:340-346,357-363,427-431,461-462 |
| 9 | export-guard L0/L1/L2/L3 | 本机误传 R2 | L0 默认跳过(仅 FORCE);L1 去 REPO 注入;L2 本机树写公共桶 exit2;**L3 ALLOW_FULL_UPLOAD=1 逃生门**(首次上线人工放行一次) | **fail-closed 为主**,逃生门显式+notify;云上 production writer 恒 True 全放行(设计) | export.py:1420-1458 + upload_r2.py:113-123 | export-guard-implementation:9-51 |
| 10 | upload_r2 guard_repo_default | 手动裸跑读旧库覆盖 R2 | REPO 显式→放行(信任调用方,deploy.sh 显式 export);A/B 白名单→放行 | 缺省拒绝 exit3(fail-closed);REPO 显式是信任点 | upload_r2.py:102-140 | upload_r2.py:124-140 |
| 11 | verify-r2 | R2 vs 云上树差异 | **平日抽样 100+changed,批量残留兜不住**(10-02 事故:lab/trade_sim changed=0,抽样 20 兜不住 482) | 补传失败不阻断只告警(有意);周日全量对账兜底 | deploy 段1 L704-711 | upload_r2.py:2703-2745,2811-2870;incident:119-121 |
| 12 | with_lock.py 排队超时(段2) | 并发 git 写 | **超时 → 优雅跳过 exit 0**(L150-152),notify warning;**deploy 段2 git push 跳过时 rc=0 静默丢代码**(数据已上 R2,代码 min 未推) | **fail-open(有意,3600s 超时)**,段2 实测秒级风险低 | deploy 段1 末尾 exec | with_lock.py:135-152;149a 报告 §2 |
| 13 | console 洁净度哨兵 | CSP 违规/pageerror 回归 | SKIP_CONSOLE_CLEAN=1 逃生(显式打醒目提示);UNREACHABLE(exit2)放行 | 逃生门 + 不可达放行(fail-open,有意) | main-merge 7.7 | main-merge.sh:371-408 |
| 14 | sync_cloud_pull | 云上忘 pull | 无逃生门;失败 exit6 醒目 [!!] 告警 | main 已 push 云上旧代码(fail-open 但显式告警) | main-merge 第 10 步 | main-merge.sh:496-538 |
| 15 | staticdata_write_guard | 非生产机写 staticdata git | --check-fresh:fetch 失败拒(fail-closed);**rc=2 内部错误 → 调用方 fail-open 继续(有意识取舍 L3,文档明确)** | **fail-open(文档明示)**:守卫 crash 不停灾备 | staticdata_backup_async.sh:251 / staticdata_sync.sh:145 | staticdata_write_guard.py:35-38 |

**fail-open 点名汇总**:R2 上传通道失败(#11 上方)+ verify-r2 平日抽样盲区 + with_lock 排队超时跳过 + check_data_integrity warn + console 哨兵逃生/不可达 + feat base 软校验 + check_version_consistency 源缺失 + staticdata 守卫 rc=2 + check_version_progress 祖先无串 skip。

## 3 位置与生产目录验证问题

- **deploy 段1 顺序正确**:export → check_data_integrity(L323)→ 其余 check → rsync(L523)→ R2(L661+)→ verify-r2(L704)→ check_version_progress(L735)。**校验在 rsync 与 R2 上传之前**,失败时线上不变(数据文件已在云上本地树生成但未上线)。对照「闸门位置决定爆炸半径」:放对了。
- **main-merge bump 在 merge 后、push 前**(第 6 步),check 在第 7 步。位置正确。
- **生产目录验证(memory「闸门必须在生产目录验证」)**:主要闸门(check_version_consistency / check_version_progress / check_dual_src)deploy.sh 全部在**云上生产树** `$GIT_REPO/static-site`(=`/home/ubuntu/code/trade-data-signal`)执行,已在真实生产目录绿过(10-03 今天日志 PASS)。**不是只在干净 worktree 绿**。✅
- **export-guard 云上验证缺口**:L5(pre-upload 备份 key)与 L4(告警)需"首次真增量/制造 check 失败"才触发,10-03 上线后尚无交易日样本(export-guard-implementation:76-78 诚实标注;今天非交易日 verify-r2 补传 35 个,未观察到 pre-upload 打点)。
- **check_version_progress 在 R2 上传之后**(L735):版本串回退时前面 R2 数据已传。但版本串只影响 min/代码(段2 git),数据 R2 不涉版本串,可接受。

## 4 守卫自锁风险

- **staticdata_write_guard check-fresh**:候选变更集 = `git diff --name-status origin/main` + `ls-files --others`(L141-148)。**用 git diff(工作树 vs 远端)判定,不经过已暂存区** → 若调用方先 `git add` 再跑守卫,staged 内容不在判定集。但实际调用方是"先守卫、拿 allow 清单、只 add 清单"(staticdata_write_guard.py:196-207 + 调用方 `_GATE_LIST` 驱动 add),**不存在"把该放的改动锁死"的自锁**。✅
- **deploy.sh 段2 git add**:精确 6 个 min 文件列表(deploy.sh:765-772),非 `git add -A` → 无自锁。
- **large_json_excludes --check-staged** 同风格守卫单一源(staticdata_write_guard.py:13-14 引用),无自锁实例。
- **结论:无自锁风险**。

## 5 回滚能力评估(含最近一次真实回滚)

### 5.1 最近两次真实回滚
| 维度 | 最近实例 | 时间 | 方式 | 成功? | 耗时 |
|---|---|---|---|---|---|
| 代码回滚 | `774e97ece revert(codex)`(回退伪跳空 finding 改动) | 2026-09-16 | git revert commit → feat → merge → bump | ✅ | 分钟~小时(含发版链) |
| 代码回滚(大批次) | `18cfa90e3 revert(#97移动端)`(批次A iOS 兼容+B 卡片化整体回滚) | 2026-08-25 | 同上 | ✅ | 同上 |
| 数据回滚 | **10-02 本机误传 R2 事故恢复**:云上树 md5 对账 → PUT 回 R2 541 key + purge CF | **2026-10-03 04:55** | restore_r2_v2.py(只写 R2 数据,不碰 git/systemd) | ✅(fixed=541,skipped=21,missing=0,failed=0) | **~34 分钟**(清单 04:21 → 结果 04:55) |

### 5.2 逐项回滚能力
- **代码回滚**:git revert → feat 分支 → `scripts/main-merge.sh`(统一 build_min+bump 新串 → 校验链 → push → 云上 pull)。**约 30-40 分钟**(受完整校验链约束)。文档化不充分(无专门回滚预案,靠规范流程)。
- **数据产物回滚**:R2 无 key 版本,回滚 = 从恢复源 PUT 回 + purge CF。恢复源四层:①云上树当前正确版(10-02 用的)②signal-backup/pre-upload(L5,10-03 上线,保留 7 天)③R2 mac-backups/ 历史快照(10-02 取回过 86/86)④git 历史(static-site/data 曾 tracked)。**约 30-60 分钟**。10-02 实测 34min。
- **版本串回滚(SW 缓存撕裂)**:版本串 = 日期+批次**单调前进**(bump_asset_version 每次强制换新串),`check_version_progress` A 任务**拦倒退**(倒退回旧串 → FAIL 阻断上线)。→ **回滚只能"前进式"**:revert 后 bump 新串,内容与引用匹配,**不会产生孤儿快照/不撕裂**;代价 = 无法"秒切上一发布",必须走完整 revert+bump 流程。SW 更新接管有壳芯配套+失败回退(sw.js 内部实现,§24③),但**从未演练过"回滚+SW 缓存"组合**。
- **结论**:能回滚,**最快 ~30 分钟**;"真出事时 N 分钟内回"的 N ≈ 30-40(代码)/30(数据),不是分钟级。

### 5.3 回滚预案文档现状
- **无集中"发布回滚预案"文档**。现有:docs/backup-restore.md(DB 三层备份恢复)、docs/r2-deployment.md(灾备 4 层)、docs/data-deploy-quickstart.md(上线验证)。**缺口**:代码回滚 + 版本串回滚 + SW 缓存回滚组合无预案。

## 6 三站一致性机制现状(§22)

- **在跑的**:deploy 段1 的 check_version_consistency(代码版本三校验)+ check_data_integrity(数据)+ verify-r2(R2 vs 云上树,平日抽样 100+changed,自动补传)+ upload 后自动 purge_cache(CF 边缘缓存失效回源 R2)→ 三站读同一 R2 数据源。
- **没跑的(核心缺口)**:`check_r2_consistency.py`(§22 三版本一致性审计器:local vs R2 直链 ssd.fx8.store vs CF r2-proxy ss.fx8.store/r2,受检=overview/board_etf_map/concepts/overfit_monitor/nextday_plan 等 9 个,正是 §22 三处展示位) **全仓无自动调度点**:schedule_monitor.sh:157 仅注释引用(非 exec),systemd 无 unit,日志无运行痕迹。
- **盲区**:主站 `/data/` 前缀(ss.fx8.store/data/rewrite → R2)与 GH Pages 备站(sss.sugas.site / s.sugas.site)的 HTTP 层一致性**不在任何自动校验内**(历史上 deploy.sh:168 注释记录过"R2 已上线但 CF/GH 没拿到 730 信号")。
- **结论**:§22"校验是否真在跑"= 数据层 verify-r2 在跑,**三站 HTTP 层版本一致性校验器是死的**。10-02 事故(overview/boot 被本机旧版覆盖 6 天无人知)正是此盲区 + L4 未上线时的叠加。

## 7 已知未收口项现状

| 项 | 状态 | 证据 |
|---|---|---|
| 149d timer 错峰(timer-offset-plan) | **未落地**:云上 timer 仍 futures 20:05/21:00、etf 20:07/21:30、public-fund-daily 16:30/17:00(149d 建议 futures→19:45、etf→20:25、public-fund→16:20)。feat 分支已合(文档),**云上 systemd 未改** | ssh OnCalendar 实测 + 149d §5 |
| 149a deploy 锁拆分(①a 两段式 + ①b 外层锁拆除 + #119) | **已落地**:云上 deploy.sh git-phase L44/751 在;10 处外层锁已拆;4 文件 rsync exclude 在;今天段2 git 实测 5 秒 | deploy.sh:44,751 + ssh 实测 |
| export-guard 7 层防护(10-02 事故) | **已落地**:云上 export.py L0/L1/L2/L3 + upload_r2.py L2 在;562 恢复完成(fixed=541);verify-r2 10-03 补传 35 | ssh export.py/upload_r2.py grep + /tmp/restore_result_v2.json |
| 149e large-json 增量 + async 锁分离 | **已落地**:async step3.5b 用 --nb trade_backup_r2.lock 独立非阻塞锁(10-03 18:13 进程在跑);large-json marker/状态文件在 | ssh ps + upload_r2.py:2526 |
| check_r2_consistency 接线 | **未落地**(见 §6) | schedule_monitor.sh:157 仅注释 |

## 8 反证项

- **今天(2026-10-03 非交易日)主链全 PASS**:check_version_consistency 3 项 PASS + check_version_progress A/B PASS + 占位残留 0 + verify-r2 补传 35 个 + 段2 git 5 秒(18:13:41→18:13:46)+ 退出码 0。**闸门在真实生产目录全部绿过**。
- **云上代码 = 本地 main = fc951666a**,git status 干净;main-merge.sh 的 sync_cloud_pull(云上自动 pull)工作正常(今天 merge 的 export-guard/149a/frontleft 等全同步)。
- **10-02 事故已闭环**:`/tmp/restore_result_v2.json` = fixed 541 / skipped 21 / missing 0 / failed 0;10-03 verify-r2 继续补传 35 个。
- **export-guard 判据零误伤**:`_is_production_writer() = sys.platform!="darwin" AND ROOT.startswith("/home/")`(upload_r2.py:82-83),云上恒 True 全放行,本机恒 False 全拒(export-guard-implementation:14)。
- **锁拆分根治实证**:149 根因"锁 5.6h 不空"结构性拆除(锁只包 git 写段,秒级);10-03 async 持 trade_backup_r2.lock 独立非阻塞,不排主队。
- **R2 灾备四层齐全**:signal-backup 分层备份(DB gz 30/28/365)+ pre-upload(L5)+ mac-backups + staticdata git 历史(r2-deployment.md §1.2)。

## 9 分级问题表

### P0 立即
| # | 现象 | 证据 | 影响 | 建议 |
|---|---|---|---|---|
| P0-1 | **§22 三站一致性校验器 check_r2_consistency.py 未接线**(local vs R2 vs CF r2-proxy 9 个核心产物),主站 /data/ 与 GH Pages 备站 HTTP 层一致性零自动校验 | schedule_monitor.sh:157 仅注释引用;systemd 无 unit;日志无运行痕迹;check_r2_consistency.py:44-117 受检清单 | 10-02 事故同款(overview/boot 旧版 6 天无人知)若再发生,无自动探测;§22 铁律"校验是否真在跑"不成立 | 接入 schedule_monitor(15min 巡检)或 deploy 段1(每次 deploy 后),FAIL → notify --severe;补主站 /data/ 与两备站受检 |
| P0-2 | **10-02 事故恢复后 verify-r2 平日模式仍兜不住批量残留**(lab/trade_sim changed=0 时抽样 100 查不到 482) | upload_r2.py:2811-2834 平日抽样逻辑;incident:120-121 | 批量"本地没变但 R2 被外部覆盖"场景只能等周日全量对账(最长 7 天) | verify-r2 平日对账加"全通道 key 数/规模指纹"级检查(全量 HEAD 成本可控化)或异源覆盖告警阈值降敏 |

### P1 本周
| # | 现象 | 证据 | 影响 | 建议 |
|---|---|---|---|---|
| P1-1 | **149d timer 错峰未执行**:20:05 futures 对 20:07 etf 双全量 deploy 段1 同刻并发(锁拆分后段1 无锁,并发=数据写中间态+R2 带宽双倍) | ssh OnCalendar 实测(futures 20:05/21:00,etf 20:07/21:30,public-fund 16:30/17:00) | 段1 并发窗口互相覆盖 static-site JSON 写中间态(§22 一致性)+ R2 带宽放大 | 按 149d §5 建议 1-4 执行(需云上 systemd 写授权):futures→19:45、public-fund→16:20、lhb→18:50、futures 点2→21:20 |
| P1-2 | **无集中发布回滚预案文档**;代码回滚约 30-40min 且流程靠 agent 规范,无文档化 | docs 无 rollback 集中文档(仅 backup-restore/r2-deployment/data-deploy-quickstart) | 真出 P0 事故时回滚决策链长,靠现场推演 | 新增 docs/ops/rollback-playbook.md:代码回滚(revert+bump 新串+校验链)、数据回滚(恢复源四层+顺序)、版本串/SW 回滚(前进式+验证)三步预案 |
| P1-3 | **with_lock.py 排队超时 = 优雅跳过 exit 0**:deploy 段2 git push 若排队超 3600s,deploy 整体 rc=0 但代码 min 未推(静默丢代码) | with_lock.py:149-152;deploy.sh:751 | 静默跳过;3600s 超时下段2 秒级风险低,但"rc=0≠git 已推"是认知盲区 | 段2 with_lock 超时改 exit 非 0 或超时前告警升级;至少日志标注"git 段被跳过" |

### P2 观察
| # | 现象 | 证据 | 影响 | 建议 |
|---|---|---|---|---|
| P2-1 | R2 上传 18 通道失败 fail-open(累积 R2_FAIL 继续部署,收尾 verify-channels 对账后告警) | deploy.sh:662-711,1092-1115 | 有意设计;单通道失败线上缺文件但 verify-r2 兜底 | 保持,观察 L6(异源覆盖阈值告警)上线后效果 |
| P2-2 | check_version_progress 祖先链无版本串 → skip(理论 fail-open) | check_version_progress.py:222-224 | 历史无触发(版本串一直存在) | 记录,不改 |
| P2-3 | check_version_consistency 源缺失 → skip 不 FAIL | check_version_consistency.py:204-206 | 与 build_min 缺源跳过语义一致(设计) | 记录;若未来源文件管理严格化可改 FAIL |
| P2-4 | console 洁净度哨兵 UNREACHABLE 放行 + SKIP_CONSOLE_CLEAN=1 逃生门 | main-merge.sh:374-407 | 显式设计;连续 UNREACHABLE 会形同虚设(有提示) | 保持;连续 N 次 UNREACHABLE 加告警 |
| P2-5 | check_data_integrity warn 不阻断 deploy(--deploy-mode) | check_data_integrity.py:2278-2279 | 设计内,防预存 warn 阻塞所有 deploy | 保持;关键 warn 已由 schedule_monitor 出口兜底 |
| P2-6 | export-guard L5(pre-upload 备份)10-03 上线后尚无交易日样本,未观察到 pre-upload key | 今天非交易日日志无 pre-upload 打点 | 首次真增量后才生效;未验证 | 首个交易日增量后巡检确认 L5 备份 key 出现 |

## 复现段

```bash
# 0) 云上代码落地状态(export-guard + 149a 两段式)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cd /home/ubuntu/code/trade-data-signal && git rev-parse --short HEAD && grep -n "git-phase" scripts/deploy.sh | head -3 && grep -n "本机开发树" scripts/upload_r2.py | head -2'

# 1) 云上 timer 错峰落地现状(149d 未执行)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'for f in trade-futures-backfill trade-etf-national-team trade-public-fund-daily trade-lhb-backfill; do echo -n "$f: "; grep -h "OnCalendar" /etc/systemd/system/$f.timer; done'

# 2) 云上锁文件 + 持锁进程(trade_deploy / trade_backup_r2 独立)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'ls -la /tmp/trade_deploy.lock /tmp/trade_backup_r2.lock; ps aux | grep -E "with_lock|staticdata_backup" | grep -v grep | head -5'

# 3) 今天主链全 PASS(校验在生产目录绿过)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cd /home/ubuntu/code/trade-data/data/logs && grep -E "check_version_consistency|check_version_progress|verify-r2|退出码" deploy_20261003_1750.log | tail -12'

# 4) 10-02 事故恢复结果(固定 541 + 跳过 21)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'python3 -c "import json; d=json.load(open(\"/tmp/restore_result_v2.json\")); print(d)"'

# 5) check_r2_consistency 未接线(§22 三版本审计器无调度点)
grep -rn "check_r2_consistency" /Users/linhuichen/code/trade/scripts/schedule_monitor.sh | head -3
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'grep -rl "check_r2_consistency" /etc/systemd/system/ 2>/dev/null; grep -c "check_r2_consistency" /home/ubuntu/code/trade-data/data/logs/schedule_monitor_launchd.log 2>/dev/null'

# 6) fail-open 闸门源码锚点
grep -n "排队等锁超时.*优雅跳过\|sys.exit(0)" /Users/linhuichen/code/trade/scripts/with_lock.py
grep -n "continue  # 无法比较\|continue$" /Users/linhuichen/code/trade/scripts/check_version_progress.py | head -4
grep -n "n_skipped += 1.*源缺失" /Users/linhuichen/code/trade/scripts/check_version_consistency.py
grep -n "R2_FAIL=\"\$R2_FAIL" /Users/linhuichen/code/trade/scripts/deploy.sh | head -4
```

**修复链说明**:本报告纯只读体检,未执行任何云上写入/git 写。P0/P1 项执行需:①check_r2_consistency 接线(改 schedule_monitor.sh 或 deploy.sh,走 agent)②timer 错峰(云上 systemd 写授权)③rollback-playbook 文档(本仓 docs/)。全部为后续动作,与本次体检隔离。
