# B4② 本地对账批报告 — #218 六条对账 / #205 裸调用+docs / #149④ timer 现状 / #217④ 文案复核

- 日期: 2026-10-11;角色: researcher(只读);基准=docs/ops/next-steps-plan-20261011.md §1 B4②;产出=喂拍板 D6/D7/D11。
- 纪律: 只读(本报告为唯一写入);无 commit/push/切分支/云上写;ssh 全部 BatchMode 只读;禁 find /、禁裸 pip/npm。本批 4 条命令被 harness 自动转后台(见 §6),均已 exit 0 完成,无残留。
- ⚠ 引用注意(kill 数勘误): #218 kill = **20 次**(非 15),分布 10-05 18 / 10-06 2(出处: pending-features-index #218 行 + docs/ops/218-uploadchain-rootcause-20261006.md §6)。

---

## 1. #218 六条建议 vs 现状逐条对账(D11 材料)

建议原文 = docs/ops/218-uploadchain-rootcause-20261006.md §7(六条,各附风险)。

| # | 建议(218 §7) | 判定 | 依据/证据 |
|---|---|---|---|
| 1 | #217②③ 修复同步云上(停滞阈值 900 + 自抬 + kill 前 30 行) | **已被覆盖** | 64597a0af 在 origin/main(本地 `git merge-base --is-ancestor` PASS)+ 云上 trade-data-signal HEAD(f93de7713)含之(§5);云上 r2_upload_async.sh L120 `R2_UPLOAD_STALL_SECS:-900` + L123 防倒置守卫在位 |
| 2 | 保持 marker fail-closed(不建议改动) | **建议不做(现状保持)** | upload_r2.py L1382-1385 / L3300-3304 marker fail-closed 未变;W 批(#245)未触碰该逻辑 |
| 3 | standalone_stale 文案修改 + mass_mismatch/standalone_stale N 动态带出 | **已被覆盖** | 70a6c31ed(10-06 23:08)→ main dc0f3a124(本地 ancestry PASS)+ 云上含之(§5);现状正文=建议稿:mass_mismatch(upload_r2.py L3758-3770)带 N 动态值 +「N 不可逐字考/>50 已证/≈114」;standalone_stale(L3788-3801)列台账实有池 + 双因结构 |
| 4 | schedule_monitor「跑前 gen」降噪(方案 A/B,中期可选;218 明示短期维持现状) | **仍未做;按 218 建议=维持现状不动机制** | schedule_monitor.sh L501-511 subprocess.run(gen_schedule_stats.py, timeout=60) 仍在;W 批(预算/摘要层)未动机制,方案 A 未评审 |
| 5 | 不给 schedule_stats 加噪音豁免 | **建议不做;现状无豁免** | #245 批2 引入 ALERT_BUDGET(7 类各 1/日)= 预算非豁免,无 schedule_stats 豁免分支;语义与 #219「绝不整类豁免」一致 |
| 6 | 告警镜像(standalone_stale/mass_mismatch 非 severe 不进 latest.md) | **仍未做,待拍板** | notify.py L1202-1207 `if severe and not dry_run: _mirror_severe(...)` 现状未变;W1 台账(L1208+)是新增层,非镜像改动 |

小结: 6 条中 2 条已被覆盖(①③)、3 条判定建议不做/维持现状(②④⑤)、1 条仍未做待拍板(⑥)。未发现"被 W 批顺带改动"的意外项。

---

## 2. #205 裸调用现状核(D6 材料)

### 2.1 restore 类脚本 resolve 推导覆盖: **2/2 未接引**

- restore 类脚本共 2 个(`ls scripts | grep ^restore`): `scripts/restore-r2-backup.sh`、`scripts/restore-large-json.sh`,**均未 source scripts/lib/repo_paths.sh**(`grep -l repo_paths scripts/restore*.sh` = 空)。
- 对照组(已接 lib、非 restore 类): `scripts/verify_backup.sh` L26-27、`scripts/staticdata_backup_async.sh` L46-47;全仓 59/75 .sh 已接(#195 批1-5)。
- restore-r2-backup.sh 细节(裸调用缺口根源):
  - L66 `REPO="${REPO:-$(pwd)}"` = **假兜底**:赋值后整个脚本既未使用也未 export(死代码);
  - L68 `PY="${PYTHON:-python3}"` 裸 python3;python 内 L74 `sys.path.insert(0,"scripts")` 依赖 CWD=仓根;
  - 子进程只传 RESTORE_KEY_NAME / RESTORE_BUCKET_OVERRIDE / RESTORE_OUT_DIR(L71-72),**REPO/GIT_REPO 不进子进程 env**;
  - ⇒ 云上裸调用(文档只给 mac 调用形式)时 upload_r2._find_env(ROOT/.env → $GIT_REPO/.env → $REPO/.env → mac 硬编码)全落空 ⇒ 「无法加载 R2 凭证」exit=1(旧版同,既有缺口非本次引入;出处 docs/ops/restore-bucket-route-0verify-20261008.md §4.1)。
  - 桶语义本身已修: L83-102 跨桶候选探测(BACKUP_BUCKET 新桶 → legacy signal-backup → R2_RESTORE_BUCKET_FALLBACKS 追加),e4fecce2c 已合 main。
- restore-large-json.sh 细节: 不 source lib;L50 `cd "$(dirname "$0")/.."` 靠 $0 定位仓根;L86 `BUCKET = upload_r2.BACKUP_BUCKET`(默认 signal-backup2);L89/L165 缺省为 mac 字面量;头注释 4 行仍写老桶名(见 §2.2 附加)。
- 修法线索(D6 可选,二选一):
  - (甲,推荐·与全仓一致)两脚本接两行模板:`source "$(...)/lib/repo_paths.sh" || exit 2; resolve_repo "${BASH_SOURCE[0]}"; export REPO GIT_REPO` + `PY="$REPO/.venv/bin/python"`;
  - (乙)统一改 upload_r2._find_env 回退顺序(消 mac 硬编码兜底;改动面更大、影响面广,须单独评审)。

### 2.2 docs 侧 3 处老桶名 legacy 逐处判(禁一把梭)

三处均"只含 signal-backup、0 处 signal-backup2"(与 #205 行登记 10/0、10/0、7/0 一致)。逐处判定:

**(A) docs/site-deployment.md — 10 行匹配 / 形态=现行部署指引 ⇒ 过时,需更新(9 处真桶名 + 1 处误报)**
- L424(备份描述)、L448(桶表行,同格引用 upload_r2.py BACKUP_BUCKET)、L467(upload-db 落点)、L885/L895(DB 下载链)、L899(claude-backup 前缀)、L911(第2层描述)→ 描述"当前行为"却用老桶名,与「BACKUP_BUCKET 默认=signal-backup2」矛盾 ⇒ 应改新桶名(或注明双桶);
- L498/L781 `npx wrangler r2 bucket create signal-backup` → 新部署指引应建 signal-backup2(老桶=legacy 资产,不建);
- L883 `trade-data-signal-backup` = **Worker 名,非桶名,不改**(误报)。

**(B) docs/backup-restore.md — 10 行匹配 / 形态=操作手册 ⇒ 过时,须区分「现行写入桶=signal-backup2」vs「legacy 老桶历史对象」**
- L42-44 可执行命令 `upload_r2.py list ... --bucket signal-backup` **照跑仍能执行但只列老桶**(10-05 #178 切桶后新备份全落 signal-backup2 ⇒ 照文档操作观感「数据停在 10-05」);
- L72 download-db 描述(现默认读 signal-backup2,`cmd_download_latest_db`)、L19/L32 叙述、L156/164/227/231 large-json 全节 → 均写老桶名。

**(C) docs/ops/r2-archive-upload-20261004.md — 7 行匹配 / 形态=历史归档叙述 ⇒ 写老桶名基本正确(历史事实),仅 1 处复现命令需标注**
- L29/32/34/35/58/64/77: 对象物理落在老桶 `signal-backup/mac-backups/archive/...`(跨账号迁移前),历史叙述保留老桶名=正确;
- L86(复现命令块)「显式 bucket=BACKUP_BUCKET」: 当年 BACKUP_BUCKET=老桶、现在=新桶 ⇒ 今天照跑落点漂移(会落新桶),建议补一句「按当年语义 BACKUP_BUCKET=signal-backup」标注。

**附加(第 4 处·脚本注释层,非 #205 登记册)**: scripts/restore-large-json.sh 头注释 L2/L5/L12/L44 仍写 "signal-backup",而行为=读当前 BACKUP_BUCKET(新桶)——注释与行为不一致;对照 scripts/restore-r2-backup.sh L19 已写明「历史归档在老桶 signal-backup legacy,#178 后新写入落新桶 signal-backup2」=正确范例。

---

## 3. #149④ timer 错峰: 云上时点现状(产出待授权)

采集: **2026-10-11 ssh 只读**(systemd unit OnCalendar 真值);对照 docs/ops/149d-timer-offset-plan-20261003.md(2026-10-03 采集)。

- trade 前缀 timer 现状 **41 个**(149d 时 38)。
- 新增 3 个(149d 之后): `trade-check-monitor-heartbeat`(mtime 10-03 22:19;`*:11,26,41,56`)、`trade-cloud-unit-patrol`(10-05 20:38;08:27)、`trade-r2-consistency`(10-05 14:31;23:20)。
- 相对 149d 的 2 处漂移: `trade-update-all` 现为「Mon..Sat 17:50 + Sun 22:30」(149d 记纯 17:50);`trade-rzhb-backfill` 现为「08:00 + 19:15」(149d 只有 19:15)。
- **149d §5 错峰建议 5 条 = 全部未执行**(逐字比对): ①futures 20:05 未挪 19:45 ②public-fund-daily 16:30 未挪 16:20 ③lhb 18:30 未挪 18:50 ④futures 点2 21:00 未挪 21:20 ⑤supplement 20:30 未挪 20:25。重叠组 1(20:05 vs 20:07 双段1)/组2(16:30 vs 16:35)/组4(21:00 三连)现状全部仍在。
- 全表见附录 A。执行错峰需云上 /etc/systemd/system 写授权(本项未动任何云上文件)。

---

## 4. #217④ 文案真伪复核(D7 材料)

「④改文案」所指 = **scripts/upload_r2.py verify-r2 两处告警正文**: standalone_stale(L3788-3801 现文)+ mass_mismatch(L3758-3770 现文)。判定与证据:

- **真错三处(复核结论=确为真错,已修)**:
  1. 举例池错位: 原文案举例(s06 / nextday_plan / daily_brief)与台账实际对账池(fapi a-stock 家族 / overview / news_digest / schedule_stats)**零重叠**(出处: pending #217 行 ④ 段 + 218 报告 §5);
  2. 归因单因错位: 「连续失败/被截断」单因对 schedule_stats 命中不成立——schedule_monitor 每 15min「跑前 gen」=设计内生成(现状实码 schedule_monitor.sh L501-511);
  3. 「intraday 链」来源描述对 10-06(非交易日)命中不适用。
- **设计内部分(复核防护点,未被误改)**: 10-06 18:19 命中 schedule_stats = **机制按设计工作**(在 35 项台账内、非归因错位);修复后现状文案保留「双因结构」: (a)【设计内,无需处置】/ (b)【真故障】两分支俱全(upload_r2.py L3788-3801)⇒ 设计内命中未被当成错位改掉 ✔。
- **实施事实**: commit 70a6c31ed(2026-10-06 23:08「#217④ 告警文案订正 + #223 超时梯度修」)→ 合 main dc0f3a124;本地 + 云上 ancestry 双 PASS(§5)。改动=纯文案(commit message 自证: subject/dedup key 未动、逻辑/阈值零变更);独立审 PASS 10/10。
- **登记滞后**: pending-features-index #217 行 ④ 仍标「待拍板」,但事实=已修并合 main 且云上生效 ⇒ D7 拍板时可确认现状 + 销账。

---

## 5. 云上只读核验清单(支撑 §1-① / §4)

ssh(ubuntu@122.51.111.173, BatchMode, 只读)结果摘录(2026-10-11):

- `cd /home/ubuntu/code/trade-data-signal; git log --oneline -1` → `f93de7713 fix(#248): systemd unit 漂移仓库侧同步...`(与本地 main 同点);
- `git merge-base --is-ancestor 64597a0af HEAD` → **HAS_217FIX**(云上含 #217①②③ 修复);
- `git merge-base --is-ancestor 70a6c31ed HEAD` → **HAS_217DOC**(云上含 #217④ 文案订正);
- 云上 scripts/r2_upload_async.sh L120 `R2_UPLOAD_STALL_SECS:-900` + L123 防倒置守卫在位;
- 云上 scripts/upload_r2.py 含「台账实有池」字样(grep=1)⇒ 新文案生产在位;
- 3 个新增 timer 的 unit 文件 mtime: check-monitor-heartbeat 2026-10-03 22:19 / cloud-unit-patrol 2026-10-05 20:38 / r2-consistency 2026-10-05 14:31。

---

## 6. 环境与残留说明

本批 4 条命令被 harness 自动转后台(bionw2cgl / bhrbr9sci / b87qt2x18 / brz5vckqa),**均已 exit 0 完成,无残留后台任务**。

---

## 附录 A: 云上 trade-*.timer OnCalendar 全表(41 个,2026-10-11 只读采集)

| timer | OnCalendar |
|---|---|
| trade-ab-direction-anchor | 21:15 |
| trade-backfill-evening | 16:35 / 21:00 / 02:00 |
| trade-backup-db | 21:00 |
| trade-brief-push | 20:45 |
| trade-check-data-gap | Mon..Fri 22:35 |
| trade-check-monitor-heartbeat | *:11,26,41,56 |
| trade-cloud-unit-patrol | 08:27 |
| trade-daily-brief | 20:40 |
| trade-daily-summary-supplement | 20:30 |
| trade-etf-national-team | 20:07 / 21:30 |
| trade-etf-track-index | Sun 03:30 |
| trade-fapi-daily | 18:10 |
| trade-fetch-news | *:01,45 |
| trade-futures-backfill | 20:05 / 21:00 |
| trade-gold-night | 02:40 |
| trade-intraday-snapshot | 09:25~15:35 共 30 档(含 15:35、20:35 盘后档) |
| trade-kelly-intraday-rerun | 09:40 |
| trade-lab-auto | 19:00 |
| trade-lhb-backfill | 18:30 / 19:30 |
| trade-lof-track-index | Sun 04:00 |
| trade-nextday-gap-check | Mon..Fri 09:26 |
| trade-nextday-plan | Mon..Fri 22:30 |
| trade-overfit-monitor | Mon..Fri 21:40 |
| trade-pf-score-daily | 16:00 |
| trade-pf-score-weekly | Sun 03:17 |
| trade-pf-stage0-manager | 每月1日 02:47 |
| trade-pf-stage0-nav | Fri 01:43 |
| trade-pf-stage0-overview | Sun 02:17 |
| trade-pf-stage0-risk | 每月15日 02:33 |
| trade-public-fund-daily | 16:30 / 17:00 |
| trade-public-fund-estimation | 10:00 / 11:00 / 13:30 / 14:30 |
| trade-public-fund-full | 22:00 |
| trade-public-fund-quarterly | 03:00 / 04:00 / 07:00 |
| trade-r2-consistency | 23:20 |
| trade-rzhb-backfill | 08:00 / 19:15 |
| trade-s06-snapshot | Mon..Fri 20:35 |
| trade-schedule-monitor | *:00,15,30,45 |
| trade-self-heal | *:07,22,37,52 |
| trade-turnover-backfill | Mon..Fri 21:10 |
| trade-update-all | Mon..Sat 17:50 / Sun 22:30 |
| trade-us-stock-morning | 05:00 |

(采集命令: `for f in /etc/systemd/system/trade-*.timer; do printf "%s | " ...; grep -hE "^OnCalendar" "$f" ...; done`,ssh BatchMode 只读。)
