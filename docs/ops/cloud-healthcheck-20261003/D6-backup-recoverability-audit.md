# D6 备份/灾备可恢复性实测(2026-10-03)

> 云服务器系统性体检 7 维度之 D6。本维度核心 = **实测恢复**(每层抽样取回 + 逐位对账),不是"应该有"。只诊断不治疗。
> 全程只读:云上零写,本机仅临时目录 `/tmp/d6-restore-test/` 取回实测。
> 结论总览:**4 层中 3 层抽样恢复全 PASS,1 层(DB 子集)存在 P0 缺口 —— public_fund.db / stock_daily.db 无任何 R2/git 异地备份,本机副本过时。**

## 0 结论速览

| # | 结论 | 严重度 |
|---|---|---|
| 1 | 4 层灾备主体可恢复:①trade git ②staticdata git ③R2 私有桶(DB+large-json)④R2 公开桶,**全部抽样取回 + md5/逻辑对账 PASS** | — |
| 2 | large-json 固定前缀**全量清单一一对应**:R2 31673 key = 云上磁盘 31673,**MISSING=0 / EXTRA=0**(与 upload_r2 状态文件 count=31673 三方吻合) | PASS |
| 3 | **P0 缺口**:public_fund.db(2.76GB)+ stock_daily.db(145MB)**无 R2/git 备份**,本机副本停 9-12/9-13,唯一最新副本 = 云上同一台机器 3 处 → 盘毁即丢近 3 周数据 | **P0** |
| 4 | 每日 21:00 系统级自动恢复演练(verify_backup.sh)已跑 21 天,最近 3 次全 PASS(integrity+行数) | PASS |
| 5 | 备份失败可见性多层告警链存在且有真实历史实证(staticdata 超阈值 4 条、R2 verify LIGHT_CHECK_FAILED) | PASS |
| 6 | 本机 staticdata 镜像落后 7 天(09-26 vs 10-03)且无自动同步 → 异地副本时效性失效(靠 R2 兜底) | **P1** |
| 7 | 非交易日窗口:数据实证 10-03~10-08 A 股无行情,是做真实恢复演练的最佳窗口(本次仅评估未执行) | — |

## 1 4 层灾备现状表

| 层 | 备份对象 | 存放位置 | 最近备份 | 增量/全量 | 保留策略 |
|---|---|---|---|---|---|
| ① trade git | 代码(app/scripts/static-site 源码,不含 data/) | 本机 main + GitHub 远端 + 云上 trade-data-signal 三处 | 今天 18:25 merge `101073af8`(三处 hash 一致) | 增量 commit | GitHub 永久 |
| ② staticdata git | 差异日志(小 JSON/news_digest/signal_kelly_snapshots)+ config/launchd(历史 plist 存档);**9 大目录 31239 文件 2026-09-30 已 git rm --cached 移出** | 云上 staticdata 仓 + GitHub 远端 + 本机镜像(过时) | 今天 18:19 `0a64585`(backup all 10 files) | 增量,deploy/生成器触发 | GitHub 永久 |
| ③ R2 signal-backup 私有桶 | DB(sentiment / etf_national_team .gz)+ large-json 固定前缀(9 目录唯一完整副本)+ decommissioned + claude-backup | R2(Cloudflare) | DB 昨天 21:00;large-json 今天 17:25(状态文件) | DB 日备;large-json 增量复用 | backup 14 天(2026-10-03 由 30 减)/ weekly 28 / monthly 365;large-json 唯一副本不滚动删 |
| ④ R2 signal-data 公开桶 | 线上数据产物(fund_nav 26458 / etf 1718 / accum_nav 1718 / index / lab / trade_sim 等 31476 对象) | R2(CF,ssd.fx8.store) | 每日 deploy 上传;verify-r2 周日全量对账 | 增量引擎 + 周日全量 HEAD | 分发层,源 = static-site,无独立滚动删 |

**补充事实(DB 子集)**:
- backup_db.sh 只热备 **sentiment.db + etf_national_team.db 两个**(`scripts/backup_db.sh:77-78`)。**public_fund.db / stock_daily.db 不在备份清单**。
- `db/*.db` 全部被 staticdata 仓 `.gitignore` 排除(超 GitHub 100MB,git-lfs 未装)→ 不进 git。
- R2 枚举实测:signal-backup / signal-data 两桶 **均无 public_fund / stock_daily 任何 DB 备份**。
- public_fund.db / stock_daily.db 云上 3 处副本(**同一台机器**):trade-data/data、trade-data-signal/data、staticdata/db。本机副本:~/code/trade-data/data 的 public_fund.db 停 **9-13 08:03**、stock_daily.db 停 **9-12 18:10**(迁云旧快照,3 周未更新)。
- 唯一异地最近副本 = **无**。旧镜像 `~/code/trade-data-signal-staticdata-old-20260926`(8.3G)为 9-26 全量旧镜像(回退保险,保留至 10-30),也非最新。

## 2 ⭐逐层实测恢复证据(md5 对账)

### ① trade git — PASS
```bash
git clone --bare --filter=blob:none git@github.com:xp13465/trade-data-signal.git /tmp/d6-restore-test/trade-repo.git
git fetch origin main
git log -1 FETCH_HEAD   # -> 00a9a5c42 2026-10-03 18:24 merge(feat/feat/ci-pytest-review...)
git -C ... show FETCH_HEAD:scripts/deploy.sh | md5   # -> 6d0281ea20c7b5cd28d17b8d3cc245f1
md5 -q /Users/linhuichen/code/trade/scripts/deploy.sh # -> 6d0281ea20c7b5cd28d17b8d3cc245f1  ✓
git -C ... show FETCH_HEAD:scripts/upload_r2.py | md5 # -> 9f42511b564410b577c29ae54746f615
md5 -q /Users/linhuichen/code/trade/scripts/upload_r2.py # -> 9f42511b564410b577c29ae54746f615 ✓
```
- 远端 main = 本机 main = 云上 main = `101073af8`(三处 hash 一致,18:25 同步后)。
- 取回 deploy.sh / upload_r2.py 逐位一致 → **远端 git 仓可完整恢复代码**。

### ② staticdata git — PASS
```bash
git clone --filter=blob:none git@github.com:xp13465/trade-data-signal-staticdata.git /tmp/d6-restore-test/staticdata-repo
git log -1   # -> 0a64585 2026-10-03 18:19 data backup [all] 2026-10-03_18:19 - 10 files (= 云上 HEAD)
git -C staticdata-repo show HEAD:data/news_digest/2026/2026-08-16.json | md5  # -> 9fdc6f9dfb88e57fd52fb079d2319b8c
ssh 云上 md5sum .../data/news_digest/2026/2026-08-16.json                    # -> 9fdc6f9dfb88e57fd52fb079d2319b8c ✓
git -C staticdata-repo show HEAD:README.md | md5                            # -> 488538e208a5d3eda8f1566d7bf45c9d
ssh 云上 md5sum .../README.md                                               # -> 488538e208a5d3eda8f1566d7bf45c9d ✓
```
- clone 远端 HEAD 与云上静态仓完全一致;取回 tracked 文件 md5 逐位一致 → **staticdata git 可恢复**(9 目录之外差异日志层)。

### ③ R2 私有桶 large-json — PASS
```bash
# 取回: GET signal-backup/large-json/fund_nav/000011.json.gz → gunzip
# 本地 md5: 02cb43fdd988c1735394f961a6d553e2
# 云上磁盘 md5sum .../data/fund_nav/000011.json: 02cb43fdd988c1735394f961a6d553e2  ✓ PASS
```
- 从 R2 唯一副本取回单个大 JSON 与云上磁盘逐位一致 → 9 目录可恢复。

### ③ R2 私有桶 DB 备份 — PASS(逻辑级;md5 差异为物化方式,已确证)
```bash
# 取回: GET signal-backup/backup/sentiment_20261002.db.gz → gunzip → 133570560B
# md5 vs 云上本地备份 sentiment_20261002_2100.db: 65d596d2... vs b4c30ee0... → 不一致
```
- **诚实标注**:初次 md5 对比 MISMATCH。深查根因 = 物化方式不同:本地备份用 sqlite `.backup` API(**重建页布局**,`backup_db.sh:41-53`),R2 备份 upload-db 压缩的是**活跃 `$REPO/data/sentiment.db` 原始字节**(`cmd_upload_db`,`backup_db.sh:93`)。同一份 10-02 21:00 快照的两种物化,字节不同是设计预期。
- **逻辑级对账 PASS**:sqlite3 integrity_check = `ok`(有效 SQLite);7 个关键表行数与云上本地备份逐表一致:
  - score_daily 38555 / daily_metric 232257 / signal_daily 71371 / index_daily 494512 / industry_width_daily 80780 / futures_position 9975 / futures_accuracy 44340(两边全等)。
- 系统自带的每日演练(verify_backup.sh)本就只用 **integrity + 行数对账**(`verify_backup.sh:11-15`),10-02 日志亦 PASS —— md5 不一致并非缺陷。

### ④ R2 公开桶(signal-data)— PASS
```bash
# 取回: GET signal-data/industry/industry-5y-concepts.json → 15741370B
# 本地 md5: 5d81db76aa509cfa985518364115e5bc
# 云上 static-site/data/industry-5y-concepts.json md5sum: 5d81db76aa509cfa985518364115e5bc  ✓ PASS
```

## 3 清单完整性比对(MISSING 数)

| 层 | 应有集合 | 实有(R2) | MISSING | EXTRA | 结论 |
|---|---|---|---|---|---|
| large-json 固定前缀 | 云上磁盘 9 目录 + 根级 7 大 JSON = **31673** | 枚举 31673 key | **0** | **0** | **MISSING=0** ✓ |
| large-json 状态文件 | upload_r2 `.r2_large_json_state.json` count | **31673**(2026-10-03T17:25, 增量) | — | — | 三方吻合 ✓ |
| R2 backup/ DB | 每日 2 DB × 14 天(2026-10-03 由 30 减) | 54 对象 = 27 天 × 2(09-03~10-02) | 迁云前空窗 09-05/06/12(共 3 天,当时云上未建成) | 0 | 09-13 起逐日连续 ✓;下次 upload-db 起按 14 天窗口滚动 |
| R2 公开桶 | static-site/data 全部产物 | 31476 对象(抽样 PASS) | 未逐对象比对(分发层,verify-r2 周日全量对账机制覆盖) | — | 抽样 PASS |

**memory「R2 大 JSON 灾备从无完整快照 + key 按天翻滚」当前状态(核实结论)**:该缺陷**已由 #126 根治**。2026-09-30 起 large-json key 改**固定前缀** `large-json/<相对data路径>.gz`(无日期),内容不变跨天复用(HEAD ETag 幂等),不再按天翻滚归零。**实测当前 R2 large-json 固定前缀 = 完整快照(31673/31673,MISSING=0)**。legacy 按天目录(09-25~09-30)仍在(27689 对象 ≈0.44GiB),7 天宽限期后由 `_prune_large_json` 自动清理(10-07 前后),逃生门 `R2_LARGE_JSON_DATE_PREFIX=1` 保留。

## 4 恢复路径(每层一行命令)

| 层 | 恢复命令(一行) | 可逆性 |
|---|---|---|
| ① trade git | `git clone git@github.com:xp13465/trade-data-signal.git && cd trade-data-signal && git checkout main` | ✓ 可写 |
| ② staticdata git | `git clone git@github.com:xp13465/trade-data-signal-staticdata.git`(差异日志层) | ✓ 可写 |
| ③ R2 DB | `python3 scripts/upload_r2.py download-db sentiment <dir> && python3 scripts/upload_r2.py download-db etf_national_team <dir>`(verify_backup.sh 同款;云上 `bash scripts/verify_backup.sh` 即完整演练) | ✓ 可写 |
| ③ R2 large-json(9 目录) | `bash scripts/restore-large-json.sh --all --target <dir>`(固定前缀全量并集拉回,原子写 + .bak 备份) | ✓ 可写 |
| ③ R2 decommissioned | `bash scripts/restore-r2-backup.sh <key_name>` | ✓ 可写 |
| ④ R2 公开桶 | 重新 `bash scripts/deploy.sh`(源码在①,产物从 static-site 重建上传);单对象可直接 s3 GET | ✓ 可写 |
| **public_fund.db / stock_daily.db** | **写不出来 —— 无异地备份通道。仅能:回本机 9-12/9-13 旧快照,或云上同机 3 处副本(非异地)** | **✗ P0** |

## 5 恢复演练历史

- **每日自动化恢复演练**:verify_backup.sh 内嵌 backup_db.sh,每日 21:00 从 R2 下载最新 DB 备份 → gunzip → integrity_check → 关键表行数对账。云上日志 **21 条**(最早 2026-09-13_1437 迁云日,此后每日),最近 3 次(09-30 / 10-01 / 10-02)全 **PASS**。
- **10-02 真实恢复操作**:r2-mac-backups-restore —— 从 R2 `mac-backups/2026-10-01/` 全量下载 86 对象(10.171GiB)+ 逐文件 md5+size 与上传锚点日志对账,**86/86 PASS**,随后删 R2(已留本地)。
- **#126 precheck**:R2 large-json 5/5 文件 md5 与磁盘一致。
- **本次 D6(首次真实取回)**:① trade git clone + 2 文件 md5 ② staticdata git clone + 2 文件 md5 ③ large-json 单文件真实取回 + md5 ④ DB 备份逻辑对账 ⑤ 公开桶单文件取回 + md5。
- **缺口点名**:large-json **从未做过 `--all` 全量取回演练**(本次仅单文件);public_fund/stock_daily **从未做过任何恢复演练**(因无异地备份)。

## 6 备份失败的可见性

| 环节 | 失败告警机制 | 实证 |
|---|---|---|
| backup_db.sh 本地热备失败(rc≠0) | notify.py `--severe` 邮件 + 写 data/alerts/latest.md(`backup_db.sh:110-125`) | 代码确认 |
| verify_backup.sh 演练失败 | 内部 notify `--severe` + 退出码(60s 重试 1 次) | 代码确认 |
| staticdata 备份超阈值/失败 | notify + 写 latest.md;STATICDATA_FAIL=1 → heartbeat fail | **实证 4 条告警**:09-25/09-26/09-28/09-29 超阈值(变更字节 >300/500MB)均留档 latest.md |
| upload-large-json 熔断/预算耗尽 | 熔断/预算 → ok≠len → sys.exit(1) → staticdata_backup_async STATICDATA_FAIL=1 → notify severe(#129 已实施) | 代码确认 |
| deploy R2 上传通道失败 | deploy.sh R2_FAIL → notify;verify-r2 补传失败 exit 1 | **实证**:latest.md 有 kelly-parts LIGHT_CHECK_FAILED(etag≠md5 缺口)告警 |
| 备份"悄悄停"(timer 停用/机器离线) | **无独立自动告警**——靠 `systemctl list-timers` 巡检 + 每日日志是否新增判断 | 观察项 |

## 7 非交易日演练窗口评估

- **数据实证**(云上 sentiment.db index_daily 逐日行数):09-28/29/30 = **158 行**(正常交易日);10-01/02 = **4 行**(非 A 股,仅境外/贵金属类);10-03/05/06/07/08 = **0 行**。→ **A 股 10-01~10-08 无行情**。
- 2026-10-03 为周六;10-04 周日;10-05~10-08 为国庆假期(2026 国庆+中秋连休;首个可能交易日 **10-09 周五**,精确以交易所公告为准,外部查询受限未获官方链接)。
- **窗口评估**:10-03~10-08 至少 6 天无盘中数据生成,无 15:35/16:00/17:50/20:35 盘中/盘后全量 export 冲突;21:00 backup_db+verify_backup 每日照跑(正好可顺带观测演练)。**是真实恢复演练的理想窗口**。
- **建议(本次不执行,仅评估)**:① `bash scripts/restore-large-json.sh --all` 全量取回 31673 文件到临时目录并抽样 md5(首次全量演练,验证 --all 并集逻辑与 atomic 写);② `bash scripts/verify_backup.sh` 手动复跑(已有每日跑,可选);③ P0 缺口修复前,把 public_fund.db 从云上拉一份到本机异地验证可恢复性。全部只读(restore 目标指向 /tmp),不碰生产 data/。

## 8 反证项(确认可恢复的层,附 md5 证据)

| 层 | 证据 |
|---|---|
| ① trade git | clone 远端 → HEAD=本机=云上=`101073af8`;deploy.sh md5 `6d0281ea`==`6d0281ea`;upload_r2.py md5 `9f42511b`==`9f42511b` |
| ② staticdata git | clone 远端 → HEAD=云上=`0a64585`;news_digest 文件 md5 `9fdc6f9d`==`9fdc6f9d`;README.md `488538e2`==`488538e2` |
| ③ R2 large-json | 固定前缀 31673 key == 磁盘 31673,**MISSING=0**;抽样 fund_nav/000011.json md5 `02cb43fd`==`02cb43fd` |
| ③ R2 DB | sentiment_20261002.db.gz 取回:integrity `ok`,7 关键表行数 vs 云上本地备份逐表一致(38555/232257/71371/494512/80780/9975/44340) |
| ④ R2 公开桶 | industry-5y-concepts.json md5 `5d81db76`==`5d81db76`(15741370B) |

## 9 分级问题表

### P0(立即)
**P0-1 public_fund.db(2.76GB)+ stock_daily.db(145MB)无任何异地备份,唯一最新副本=云上单机**
- 现象:upload-db 只备份 sentiment/etf_national_team;R2 两桶枚举无 public_fund/stock_daily 任何 key;`db/*.db` 被 staticdata .gitignore 排除不进 git;本机副本过时(public_fund 9-13、stock_daily 9-12)。
- 证据命令:
  - `grep -n "backup_one" scripts/backup_db.sh` → 仅 `sentiment` / `etf_national_team` 两行(L77-78)
  - R2 枚举 `signal-backup/public_fund` → 0 key;`signal-backup/stock_daily` → 0 key;`signal-data/public_fund` → 仅派生 JSON 产物(非 DB)
  - 本机 `ls -la ~/code/trade-data/data/public_fund.db` → `9 13 08:03`(2498605056B);`stock_daily.db` → `9 12 18:10`
  - 云上 3 处副本全在同机:trade-data/data、trade-data-signal/data、staticdata/db(同 mtime 10-03 16:01 / 18:10)
- 影响:云上机器盘毁 / R2 数据损坏同时发生时,场外基金持仓净值(近 3 周)+ 日行情数据只能回退到 9-12/9-13 本机旧快照,期间数据全丢。
- 建议:①将两个 DB 纳入每日异地备份(upload-db 扩展 targets 或走 R2 大文件通道;public_fund 2.76GB gz 压缩后预计 ~15-25min,21:00 备份窗口可容纳)②或至少建"云上→本机每日同步"异地副本 ③修复前 P0 悬置,不销账。

### P1(本周)
**P1-1 本机 staticdata 镜像过时且无自动同步**
- 现象:本机 `~/code/trade-data-signal-staticdata` HEAD `c8a0a46`(09-26)vs 远端 `0a64585`(10-03),落后 7 天;本机 mac 无相关 launchd(已迁云,定时任务全在云上),镜像仅人工更新。
- 证据:本机/远端 `git log -1` 对比;`ls ~/Library/LaunchAgents/` 无 staticdata 同步 job。 <!-- staleness-ok: 证据命令输出,描述本机 LaunchAgents 无 staticdata 同步 job(否定声明),非现行调度口径 -->
- 影响:本机作为"异地副本"的时效性失效(9 目录外的小文件差异日志也不最新);当前靠 R2 large-json(最新完整)兜底,风险可控。
- 建议:①明确"本机 staticdata 镜像非实时灾备、仅回退保险"降级标注 ②或加周度手动 `git fetch origin && git merge --ff-only origin/main`。

**P1-2 large-json 唯一完整副本无版本历史(固定前缀覆盖,旧版即丢)**
- 现象:#126 后 large-json key 固定前缀,R2 只保留"当前最新快照",昨天内容被今天覆盖。
- 证据:`cmd_upload_large_json` key = `large-json/<rel>.gz`(无日期),HEAD ETag 命中跳过 PUT,内容变则覆盖同 key。
- 影响:只能恢复到"最近一次完整上传"的快照,无法恢复到特定历史日。属设计决策(唯一完整副本),但建议纳入知情范围并做年度全量取回演练兜底。
- 建议:保持现状;每季度 `restore-large-json.sh --all` 演练一次,确认全量可拉回。

### P2(观察)
- **P2-1 前端产物无 R2 独立备份**:app.min.js 等走 CF 静态部署,源码在 trade git 可 rebuild,单点风险低。恢复 = 从 git 重新 build + deploy。
- **P2-2 systemd backup timer 停用无自动告警**:backup timer 被 stop/disable 时无独立告警,靠 `systemctl list-timers` 巡检发现。建议在每日巡检项里加"backup timer 最近成功时间"检查。
- **P2-3 R2 lifecycle 配置未实测**:代码注释声称桶 lifecycle 与代码保留天数双保险,但 S3 API GetBucketLifecycleConfiguration 返回 403 未验证(2026-10-02 容量报告已标注)。若 R2 侧 lifecycle 缺失,DB 层清理只靠代码 `_prune_r2_backup` 单一机制。
- **P2-4 每日演练只覆盖 2 个 DB**:verify_backup.sh 只演练 sentiment/etf_national_team;public_fund 无演练(见 P0-1),large-json 无全量演练(见 P1-2)。

## 复现段

```bash
# ① trade git 恢复实测
git clone --bare --filter=blob:none git@github.com:xp13465/trade-data-signal.git /tmp/d6-restore-test/trade-repo.git
git -C /tmp/d6-restore-test/trade-repo.git fetch origin main
git -C /tmp/d6-restore-test/trade-repo.git show FETCH_HEAD:scripts/deploy.sh | md5     # 6d0281ea20c7b5cd28d17b8d3cc245f1
md5 -q /Users/linhuichen/code/trade/scripts/deploy.sh                                  # 6d0281ea20c7b5cd28d17b8d3cc245f1

# ② staticdata git 恢复实测
git clone --filter=blob:none git@github.com:xp13465/trade-data-signal-staticdata.git /tmp/d6-restore-test/staticdata-repo
git -C /tmp/d6-restore-test/staticdata-repo show HEAD:data/news_digest/2026/2026-08-16.json | md5   # 9fdc6f9d...
ssh -i ~/tdsignal.pem -o BatchMode=yes ubuntu@122.51.111.173 'md5sum /home/ubuntu/code/trade-data-signal-staticdata/data/news_digest/2026/2026-08-16.json'

# ③ R2 large-json 取回 + md5(枚举脚本 /tmp/d6-restore-test/enum_r2_keys.py + fetch_verify.py)
#    枚举 31673 key vs 磁盘 31673 => MISSING=0 / EXTRA=0
/Users/linhuichen/code/trade/.venv/bin/python /tmp/d6-restore-test/enum_r2_keys.py
#    取回 fund_nav/000011.json.gz -> md5 02cb43fd==云上磁盘

# ③ R2 DB 备份逻辑对账
/Users/linhuichen/code/trade/.venv/bin/python /tmp/d6-restore-test/fetch_verify.py   # GET backup/sentiment_20261002.db.gz -> gunzip
sqlite3 /tmp/d6-restore-test/r2_sentiment_20261002.db "PRAGMA integrity_check"        # ok
# 7 关键表行数 vs 云上备份逐表对比(全等)

# ④ R2 公开桶取回 + md5
#    GET signal-data/industry/industry-5y-concepts.json -> md5 5d81db76==云上 static-site

# P0 证据
grep -n "backup_one" scripts/backup_db.sh                                    # 仅 sentiment/etf_national_team
# R2 枚举 signal-backup/public_fund 与 signal-backup/stock_daily -> 0 key
ls -la ~/code/trade-data/data/public_fund.db ~/code/trade-data/data/stock_daily.db   # 9-13 / 9-12(过时)

# 每日演练日志(云上)
ssh ... 'cat /home/ubuntu/code/trade-data/data/logs/verify_backup_20261002_2103.log'   # 结论: ✓ 通过
ssh ... 'ls /home/ubuntu/code/trade-data/data/logs/ | grep verify_backup | wc -l'      # 21(09-13 起每日)

# 非交易日窗口实证(云上)
ssh ... 'python3 -c "... index_daily 10-03~10-08 count=0 ..."'                          # 10-01/02=4, 10-03..08=0
```

### 诚实标注
1. **DB md5 不一致已确认非缺陷**:R2 备份(md5 65d596d2)与本地 .backup 备份(md5 b4c30ee0)字节不同,根因 = sqlite `.backup` API 重建页布局 vs 原始文件物化;逻辑数据逐表一致(integrity ok + 7 表行数全等),系统每日演练亦用行数口径(verify_backup.sh 设计)。
2. **国庆休市精确日**:10-05~10-08 休市为数据实证(0 行)+ 惯例推断,首个交易日 10-09 为推测,官方公告因外部查询受限未取得链接。
3. **未做正式 --all 全量取回演练**:本次只评估窗口 + 单文件实测,正式全量演练按任务口径未执行。
4. **R2 lifecycle 未实测**(403),P2-3。
