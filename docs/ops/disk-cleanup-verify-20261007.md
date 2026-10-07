# 磁盘清理「用途待核」四项权威核实 + 全面执行清单(2026-10-07,只读)

> 执行:调研 agent(role-researcher),2026-10-07 晚。**全程只读**:未删/未移动任何文件、未跑 `git gc`/`git prune`、未写 R2(仅 `upload_r2.py list` 只读列举)、未写 GitHub(仅 REST GET + `gh` 不可用改 curl)。本文件是本任务唯一落盘产出(报告本体)。
> 输入:`docs/ops/disk-usage-audit-20261007.md`(17:12~17:40 前轮审计,本报告**不重复**其已做工作,只补「用途待核」项)。
> 关联:`docs/decommissioned-backups.md`、`docs/ops/r2-slim-compression-measure-20261004.md`、`scripts/restore-r2-backup.sh`、memory `staticdata-old-mirror-keep-decision`。

---

## 一、五项核实结论

### 1. `data/release/`(657M,4 个 DB tar.gz)→ **判定:可删**(公开异地副本已到位)

**身份已查明**(此前标「用途待核/疑似历史迁移发布包」):
- 档案来源 = `scripts/release_db.sh`(该脚本已在 `0547f6733`「迁移数据开源到独立仓库 trade-data-signal-staticdata」2026-08-10 22:37 被 `git rm`,原文 `git show 0547f6733^:scripts/release_db.sh` 可读)。脚本头注明「**资产来源: data/release/*.tar.gz**」,用途=「把 SQLite 数据库归档包上传到 GitHub Release(开源完整化)」,REPO=`xp13465/trade-data-signal`。
- 目录 mtime 8-10 21:46~21:47,与迁移 commit 同晚 ⇒ 是**开源发布用的一次性 DB 归档包**,不是线上消费数据。

**异地副本已核实在位**(关键判据):
```
curl -s https://api.github.com/repos/xp13465/trade-data-signal-staticdata/releases
→ tag db-archive-2026-08-10, 4 assets, state=uploaded
  etf_national_team.db.tar.gz  size=52511320   (本地 52,511,320 ✓ 逐位一致)
  public_fund.db.tar.gz        size=578428929  (本地 578,428,929 ✓)
  sentiment.db.tar.gz          size=37396124   (本地 37,396,124 ✓)
  stock_daily.db.tar.gz        size=19547655   (本地 19,547,655 ✓)
```
> 注:`xp13465/trade-data-signal` 仓 releases=**0 条**;归档实际落在**数据仓库** `trade-data-signal-staticdata`(迁移语义正确)。

**引用检索**:`grep -rn "release/" docs scripts config --include='*.py' --include='*.sh'` → **零命中**;且 README.md:363 现行对外指引=「打包 tar.gz 挂在数据仓库 GitHub Releases(...staticdata/releases)」⇒ **GitHub Releases 就是正式对外分发点**,本地副本非分发所需;docs 仅历史清理报告旁注提及(`docs/ops/holiday-window-housekeeping-survey-20261001.md:111/174`、`docs/deploy/resource-benchmark-20260912.md:30`),无消费方。

**删了影响什么**:无。发布动作早已完成(assets 已在线,并有下载记录 downloads=1~2);本地这份是上传源残留。

**§25 恢复路径**:从 GitHub Release 取回 ——
`https://github.com/xp13465/trade-data-signal-staticdata/releases/tag/db-archive-2026-08-10`(4 assets 直下)。

---

### 2. p0 备份 ×3(528M)→ **判定:用途已查明;「先归档 → 可删」,建议保 1 份或全部归档后清(需用户点头)**

**用途已查明**(此前「无任何引用文档」):
- `docs/tasks-done-list.md:312` = **`#87 P0:盘中增量 5 笔交易定价污染(已根治上线 2026-09-09)`**:根因 9/8 全市场 `accum_nav=1.5` 占位事故污染定价链,**「两库清理(1441 真实 + 38 NULL)+ 重跑」**。⇒ `etf_national_team.db.bak-p0-20260909` = **该 P0 修复动作的清理前快照**(09:46 打);`-1345` 版 = 当日 13:45 第二次快照(同一批修复过程中的重打)。
- 该 P0 已根治+上线+防御固化(p0-nav-placeholder-defense 哨兵+deploy gate),备份使命(修复前保险)已于当日完成。

**检索**:`grep -rn "bak-p0" scripts docs` → 仅命中前轮审计报告本身;**无脚本、无文档、非 git 跟踪**(`git ls-files data/` 零命中)。⇒ 人工 `cp` 命名,非管线产物。

**三份保留哪几份合理**:
| 文件 | 树 | md5 | 判定 |
|---|---|---|---|
| `data/etf_national_team.db.bak-p0-20260909` | trade | `55926b74…` | 与 trade-data 侧**完全相同** ⇒ 可去重 |
| `/trade-data/data/etf_national_team.db.bak-p0-20260909` | trade-data | `55926b74…` | 建议**保留 1 份**(两侧任选,建议 trade-data 侧=ctime 原始源) |
| `data/etf_national_team.db.bak-p0-20260909-1345` | trade | (13:45 版) | 与 09:46 版同为当日过程快照,时效价值已耗尽 |
> 建议:**R2 `decommissioned/` 归档 1 份(或全部)→ 删本机其余**;若用户希望留 1 份本机,留 trade-data 侧那份即可。⚠️ **当前无任何归档** ⇒ 想删必须先补归档(§25)。

**§25 恢复路径**:前置=先补 R2 归档(如 `python3 scripts/upload_r2.py upload-decommissioned data/etf_national_team.db.bak-p0-20260909 etf_national_team.db.bak-p0-20260909.gz`,需用户拍板后由执行方做);恢复=`bash scripts/restore-r2-backup.sh etf_national_team.db.bak-p0-20260909.gz`。**未归档前标「不可删」**。

---

### 3. 107 个 `trade-data/static-site/trade_sim_*.html`(196M)+ trade 侧 7 个同族 → **判定:可删**(线上 404,已停用)

**线上可达性(实测 curl)**:线上**不可达** ⇒
```
https://ss.fx8.store/trade_sim_bj50.html    → 404
https://ss.fx8.store/trade_sim_cgb_idx.html → 404
https://ss.fx8.store/trade_sim.html         → 307 → /trade_sim(CF 路由去后缀); /trade_sim → 200(是 SPA 路由页,与这些 HTML 文件无关)
```

**停用声明(脚本注释,权威)** `scripts/update_lab.sh`:
- L22-23:「注：static-site/trade_sim.html（旧版全品种打包 HTML）已停用，不再每日重生 + commit（**2026-08-21 清理**）」
- L254-255:「旧版 static-site/trade_sim.html（全品种打包 HTML）已停用：2026-08-21 清理——前端走 R2 上按指数拆开的 `trade_sim_{iid}_stats.json` + `_full.json`」

**引用检索**:`static-site/*.html + *.js` 内对具体文件名(`trade_sim_bj50`/`trade_sim_cac40`/`trade_sim_cgb_idx`)**零命中**(排除自身);`guide.html`/`about.html` 提到的只是**数据路径** `static-site/data/trade_sim/*.json`(≠根 html)。

**上传链路**:`scripts/upload_r2.py` 只上传 `STATIC_DIR/data/trade_sim/*.json`(`upload_r2.py:1546` `ts_dir = STATIC_DIR / "data/trade_sim"`,子命令 `upload-trade-sim-json`),**从不涉及 static-site 根 html** ⇒ R2/CF 侧本就没有这些文件(与线上 404 互证)。

**git 跟踪**:`git ls-files static-site | grep '.html$'` = **7 个**(about/databrief/guide/index/privacy/trade_sim.html/admin-feedback.html);**103 个 `trade_sim_*.html` 全部未跟踪** ⇒ 恢复不在 git。
> ⚠️ 同目录混着**活跃 symlink**(trade-data/static-site 下 25 个 symlink,如 `index.html`/`trade_sim.html` → trade 侧;`about/index/privacy` 同)⇒ **删时必须白名单 `trade_sim_*.html` 模式,勿按"根 html"通配**。

**§25 恢复路径**:`python3 scripts/simulate_trade.py --html`(脚本在位 117KB,`simulate_trade.py:33 OUTPUT=static-site/trade_sim.html`)可重建同族 HTML(属已停用形态,不建议重建);或删前 tar 归档。⇒ 判「可删」成立。

**trade 侧 12 个 html 分解**:5 个**活跃站点文件**(about/guide/index/privacy/databrief,10-04 更新,**不可动**)+ `trade_sim.html`(2.5MB,8-21,git 跟踪)+ 6 个 `trade_sim_*.html`(8-2,1 个与 trade-data 侧实体同名)→ 可清 = **7 个**(trade_sim.html + 6 同族)。

---

### 4. 甲3 矛盾(`decommissioned-backups.md` 记「已清理」但文件仍在)→ **判定:原因=「被恢复」;R2 归档真在位 ⇒ 可删**

**R2 归档核实(只读 list,实测在位)**:
```
python3 scripts/upload_r2.py list decommissioned/ signal-backup → status=200, KeyCount=2
  decommissioned/etf_national_team.db.bak-backfill-20260728-232308.gz  10,968,910 B  LastModified 2026-09-03T11:35:43Z
  decommissioned/decommissioned-small-baks-20260903.tar.gz             11,259 B      LastModified 2026-09-03T11:37:34Z
```
与 `docs/decommissioned-backups.md` 记载**逐项一致** ⇒ 文档「已上传归档」部分无误。

**本地文件「为何仍在」— ctime 指纹破案**:
```
trade 侧(被动过):
  data/etf_national_team.db.bak-backfill-20260728-232308 | mtime=07-28 23:23:08 | ctime=2026-09-04 23:31:28 | birth=07-28
  data/alert_state.json.bak-68c51a59-20260804-234731     | mtime=08-04 23:47:31 | ctime=2026-09-04 23:31:27 | birth=08-04
  data/alert_state.json.bak-fix-20260814-191445          | mtime=08-14 19:14:45 | ctime=2026-09-04 23:31:27 | birth=08-14
trade-data 侧(未被动):
  同名三文件 | ctime == mtime == birth(原始) ⇒ 是「源」
```
**结论:09-03 清理确实执行过;09-04 23:31:27~28(三个文件同秒)有一批复制动作把这三个文件从 trade-data 侧带回 trade 侧**（`cp -p`/rsync 指纹:保留 mtime/birth、更新 ctime、三文件同秒）。
**旁证**:同一 `decommissioned-backups.md` 里同批清理的另两个小 .bak(`daily_brief.json.bak-20260814-legacy`、`news_digest.json.bak-rewash-html-20260816-161103`)在本地**已不存在** ⇒ 09-03 删除动作真的执行了,不是"只记不删"的记录偏差;后两文件未被带回。

⇒ 原因判定 = **①被恢复(09-04 批量复制)**,排除 ②记录偏差(删除确已执行)、③生成脚本重现(`grep` 全仓无任何脚本生成 `alert_state.json.bak-*`/`bak-backfill-*` 命名)。

**§25 恢复路径**:`bash scripts/restore-r2-backup.sh etf_national_team.db.bak-backfill-20260728-232308.gz`(及 `decommissioned-small-baks-20260903.tar.gz` 解包取 alert_state ×2)。⇒ 判**可删**。

**诚实标注(缺口)**:09-04 23:31 的**具体触发者/操作(谁、为什么)**未定位——docs/TASKS/memory 无该时点操作记载(非 git 操作:文件未被 git 跟踪)。**「原因=被恢复」已由 ctime 指纹+旁证定性,但「触发动作」未查明**;若主控在意可再查 09-04 会话转录。

---

### 5. 3 条 stash → **判定:3 条全可丢**(改动均已被后续演进取代或从未生效)

`git stash list` + 逐条 `git diff 'stash@{N}^1' 'stash@{N}'` 核对:

| stash | 日期 | 内容 | 与 main 现状对比 | 判定 |
|---|---|---|---|---|
| `stash@{0}` | 09-19 | `docs/kelly/position/scripts/accum_nav_map.json` 1 行(整行大 JSON) | **每日管线自动产物**(deploy.sh L298-311 显示由生成器产出+同步 static-site/data/) | **可丢**(现文件每日重生成) |
| `stash@{1}` | 09-08(原标「归属待用户定」) | 7 文件:README(删 2 条功能描述)/TASKS(交接段)/about+guide+privacy(版本串 a554→a555)/`scripts/com.trade.thinking-proxy-kimi.plist`(删 40 行)/accum_nav_map | ①README 所删的 #101+ #91 两条**现仍在** main(`README.md:64/70`)⇒ 该删**从未生效**;②版本串 a554→a555 早已被后续 bump 覆盖;③**kimi-plist 删除已由 main `536d62202` 完成**(现文件不存在);④accum_nav_map=管线产物 | **可丢**(逐项均被取代/未生效);README 文案属用户口味项 ⇒ **建议随本清单一并呈用户点头** |
| `stash@{2}` | 09-07 | `scripts/agent_inbox_watcher.py` +12 行(failed→补 ready 重试)+ pending #91 行 | main 已演进为 `sync_git_refs blocked {rid}: retry exhausted`(`agent_inbox_watcher.py:251-253`,含 blocked 终态,比 stash 更完备);pending #91 现为「✅ 已完成,2026-09-12 核销」 | **可丢**(被取代) |

**§25 恢复路径**:stash 条目在 `git stash pop/drop` 前始终可由 `git stash apply stash@{N}` 取回;丢=内容无独立价值(见上表),无需额外归档。若用户对 README 删两条有意见,`git stash show -p stash@{1}` 全文可取。

---

## 二、全面执行清单(可执行排序;非重复报告,是执行编排)

> 全部删除动作须走 §25(先备份 → 实测可恢复 → 再删);**执行前一律先复查现状**(仓库活跃,数字会漂)。**任何一项写不出恢复路径 ⇒ 标「不可删」**(本表无此项)。

| # | 项 | 判定 | 前置(备份/归档动作) | 恢复路径 | 建议批次 | 排除/注意 |
|---|---|---|---|---|---|---|
| 甲1 | `trade-data/data/mac-backups-20261001/` **10.2G** | 可删(异地归档已在位) | **补回读对账**:R2 归档 `mac-backups/archive/mac-backups-2026-10-01.tar.zst`(2,278,230,346 B ≈2.12 GiB,10-04,已实测在位)解压 vs **本机原件**(删前仍在=天然锚点)逐文件 md5+size 对账 86/86;r2-slim 报告 §⑥ 明示「回读验证(删除唯一前提)**本报告未做**」 | 本机原件(删前)或 R2 归档 `zstd -d` 解压;`python3 docs/scripts/restore_mac_backups_r2.py put-restore` | **单独串行**(大项,压缩包已在 R2,只差验证+删) | ⚠️ 原对账锚点 `/tmp/mac_backups_upload_log_20261001.txt` 已不在本机 ⇒ 用本机原件替代 |
| 甲2 | `data/release/` **657M** | **可删**(§一.1) | 无(GitHub Release 已在位,size 逐位一致) | Release `db-archive-2026-08-10` 下载 | 并行(与甲3/甲4/甲6 同批) | 仅 trade 侧;trade-data 侧无此目录 |
| 甲3 | `data/etf_national_team.db.bak-backfill-20260728-232308` 37M + `alert_state.json.bak-*`×2 | **可删**(§一.4) | 无(R2 `decommissioned/` 2 key 已实测在位) | `bash scripts/restore-r2-backup.sh etf_national_team.db.bak-backfill-20260728-232308.gz` | 并行 | 双树各一份 backfill ⇒ 两棵都删(先各删一次) |
| 甲4 | `.git/lost-found/` **17M** | 可删 | 无 | 重跑 `git fsck --lost-found`(内容无业务价值) | 并行 | 不动 `.git` 其它;禁 gc 于本轮 |
| 甲5 | `trade-data/data/logs` 旧大日志 死亡段≈**153M**(7 个 >10M 中) | 死亡段可清;**活跃段不可** | 死亡段可先 gzip 归档(可选) | 日志无需恢复 | **串行**(须逐文件 mtime 判活,执行前重跑) | 活跃排除:`feishu_listener.log`(10-07 16:46 仍在写)、`senssenova-rotate.log`(10-05)、`agent_inbox_watcher.err`(46M 仍在长)等;活跃文件只可轮转不可删 |
| 甲6 | `/tmp/AweSun_*.dmg/pkg` **198M** | 可删 | 无 | 重新下载 | 并行 | 非项目文件 |
| 乙1 | p0 备份 **528M**(trade 2 + trade-data 1) | **先归档 → 可删**(需用户点头)(§一.2) | **补 R2 `decommissioned/` 归档**(当前无任何归档) | 归档后 `restore-r2-backup.sh <key>.gz` | **串行**(先归档验过再删) | 建议保 1 份(trade-data 侧)或全归档 |
| 乙2 | 研究中间产物 ≈**183M**(`signal_kelly_stock_trades.json` 103M + `hold_sweep_trades.json` 27M + `position/scripts/accum_nav/` 28M + `accum_nav_map.json` 25M) | 可删(gitignored,脚本可重建) | 无(或 tar 归档) | 重跑对应脚本(etf-weight-leader/scripts/、`export_accum_nav_map.py` 在位) | 并行 | 确认无在跑研究依赖该中间产物 |
| 乙3 | `~/.claude/projects/` 4 个旧会话 ≈**2.3G** | 先打包归档 → 可删 | 打包到 `~/.claude/backups/`(§25) | 从归档恢复;无归档=不可恢复 | **串行**(先打包) | **排除当前会话 `d08c47ab-…`**(活跃) |
| 乙4 | `.git` 松散对象 gc + dangling 清理 116M+576 对象 | 可做(非删文件) | 无 | 无需恢复(gc 只压缩/清理) | **单独窗口**(须用户批准 + 避盘中/盘后任务时点 15:35/16:00/17:50/20:35/22:00) | 本轮**未执行**;`git count-objects -vH`/`fsck` 只读已跑 |
| 乙5 | `/tmp/restore_test/` 164M | **排除(活跃)** | — | — | 不动 | 10-07 仍在更新,由对应 agent 自清 |
| — | 3 条 stash | 可丢(§一.5) | 无 | `git stash apply stash@{N}`(丢前随时可取) | 并行(建议与用户点头同批) | 用户口味项(README)建议一并呈 |

### 活跃项必排除清单(硬排除)
- `/tmp/restore_test/`(10-07 17:05+ 仍在更新)
- 活跃 worktree `.claude/worktrees/agent-abef716d45a426513`(pid 9789,locked;分支 feat/212-upload-onfail-20261007)
- `trade-data-signal-staticdata-old-20260926`(**8.3G**,用户拍板保留至 2026-10-30,cron 541d860f 到期复核)
- `trade-data-signal-staticdata` blobless 镜像(4.7G,在用)
- 当前会话 jsonl(`d08c47ab-…`,10-07 活跃)
- 双树活跃 `data/`(设计结构,两侧均有近期 mtime 更新)
- 根 `data/` 保护项(public_fund/etf_national_team/sentiment/signal_stats 等)
- `trade-data/data/logs` 中仍在写的活跃日志文件

### 批次建议(三项串行 + 一批并行)
1. **并行批**(无前置、恢复路径已备):甲2(data/release)+ 甲3(.bak 三件)+ 甲4(lost-found)+ 甲6(AweSun)≈ **1.29G**,恢复路径全在(R2/GitHub/重扫/重下)。
2. **串行 A**(乙1 p0 528M):先归档 R2 → 对账 → 删本机。
3. **串行 B**(甲1 mac-backups 10.2G):解压归档 vs 本机原件逐位对账 86/86 → 验过删本机(单步最大收益 10.2G)。
4. **串行 C**(甲5 日志死亡段 153M):逐文件 mtime 判活 → 只打死段/活跃段轮转。
5. **窗口项**(乙4 git gc ~116M+):须用户批准 + 择时。
6. **归档后项**(乙3 旧会话 2.3G、乙2 183M):按需。
> 预计净收益 ≈ **13.4G**(甲1 10.2 + 甲2 0.66 + 甲3 0.037 + 甲4 0.017 + 甲5 0.153 + 甲6 0.198 + 乙1 0.53 + 乙2 0.18 + 乙3 2.3 + 乙4 0.116)。

---

## 三、诚实标注(缺口 / 未做)

1. **甲5 未逐文件实测 mtime 判活**:本轮只复查了 logs 目录 top 文件(`feishu_listener.log` 10-07 16:46 仍在写、`claude_self_backup.log` 10-07 03:17),确认该目录**整体活跃**;逐文件死亡段判定沿用审计 §② 甲5,执行前**必须重跑**(日志活跃集已变化)。
2. **09-04 23:31 恢复动作的触发者未定位**(原因已定性=被恢复,触发动作无 docs 记载)。
3. **甲1 回读对账未做**:仅核实 R2 归档对象在位(size/LastModified 来自 list HEAD);`zstd -d` 解压 vs 本机原件逐位对账属删除前置,未在本轮执行(本轮只读不跑重活)。
4. **GitHub asset 完整性**:只核了 size 逐位一致(API 返回 size==本地 size);**未下载回读**(674M 下载属重活)。
5. **R2 只做 list**:`upload_r2.py list` 两前缀(decommissioned/、mac-backups/)只读列举;未 GET/未写。⚠️ `--dry-run` 对 list 无意义(非写命令)。
6. **p0 备份内容未做表级核验**(是否真为 9/8 污染前状态)——依据是文件名+mtime+`tasks-done-list.md:312` 的 #87 记载;表级比对(如占位行数)未做。
7. 前轮审计的时点漂移提示仍有效:执行前**逐项复查**(仓库活跃)。

---

## 四、复现命令(关键,全部只读)

```bash
# 1. data/release 身份 + 异地副本
git show 0547f6733^:scripts/release_db.sh | head -20        # 脚本头「资产来源: data/release/*.tar.gz」
ls -la data/release/                                        # 4 tar.gz, 8-10 21:46
curl -s "https://api.github.com/repos/xp13465/trade-data-signal-staticdata/releases?per_page=10" \
  | python3 -c "import sys,json;[print(r['tag_name'],[(a['name'],a['size'],a['state']) for a in r['assets']]) for r in json.load(sys.stdin)]"
grep -rn "release/" docs scripts config --include='*.py' --include='*.sh'   # 零命中

# 2. p0 溯源
grep -rn "bak-p0" scripts docs --include='*.py' --include='*.sh' --include='*.md'  # 仅审计报告
grep -n "P0:盘中增量" docs/tasks-done-list.md                # L312 = #87
for f in data/etf_national_team.db.bak-p0-20260909*; do stat -f "%N %Sm %Sc %SB" -t "%F %T" "$f"; done

# 3. html
curl -s -o /dev/null -w "%{http_code}\n" --max-time 15 -A "Mozilla/5.0 Chrome/120" https://ss.fx8.store/trade_sim_bj50.html   # 404
grep -n "trade_sim" scripts/update_lab.sh | head            # L22/254 停用注释
grep -n "STATIC_DIR / \"data/trade_sim\"" scripts/upload_r2.py   # L1546 仅传 JSON
git ls-files static-site | grep '\.html$'                   # 7 个,无 trade_sim_*

# 4. 甲3
python3 scripts/upload_r2.py list decommissioned/ signal-backup      # 2 key 在位
stat -f "%N mtime=%Sm ctime=%Sc birth=%SB" -t "%F %T" data/etf_national_team.db.bak-backfill-20260728-232308
stat -f "%N mtime=%Sm ctime=%Sc birth=%SB" -t "%F %T" /Users/linhuichen/code/trade-data/data/etf_national_team.db.bak-backfill-20260728-232308

# 5. stash
git stash list
git stash show --stat 'stash@{0}'; git stash show --stat 'stash@{1}'; git stash show --stat 'stash@{2}'
git diff 'stash@{1}^1' 'stash@{1}' -- README.md TASKS.md static-site/*.html scripts/com.trade.thinking-proxy-kimi.plist
grep -n "北交所宽度独立指标\|买入口径双档切换" README.md     # 64/70 两条仍在
grep -n "retry exhausted" scripts/agent_inbox_watcher.py     # 251/253 已演进

# 6. mac-backups 归档
python3 scripts/upload_r2.py list mac-backups/ signal-backup  # 1 key 2,278,230,346 B
```

> 报告落档:`docs/ops/disk-cleanup-verify-20261007.md`(2026-10-07,role-researcher,只读核实;**未 commit**)。
