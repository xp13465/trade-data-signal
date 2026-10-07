# 项目目录磁盘占用审计 + 可清理候选盘点(2026-10-07,只读)

> 执行:调研 agent(role-researcher),2026-10-07 17:12~17:40。
> **本报告为纯只读实测**:未删任何文件、未跑 git gc/prune、未做任何外发(R2/邮件/飞书零写)。
> 审计期间仓库处于**活跃状态**(观察到 main 推进 010282316→6a6bb432f、worktree 17:13 重建、/tmp scratch 17:05 更新);个别数字标"时点值",以复查时点为准。
> 磁盘背景:460Gi 总 / 259Gi 已用 / **174Gi 可用**(60%)——空间不紧张,本报告回答"有什么可清",不构成"必须清"。

## 〇、总览(只读实测,时点 2026-10-07 17:12~17:35)

| # | 位置 | 实测占用 | 一句话角色 |
|---|---|---|---|
| 1 | `/Users/linhuichen/code/trade`(主仓) | **9.0G** | 源码+数据+`.git` 1.7G |
| 2 | `/Users/linhuichen/code/trade-data` | **16G** | 数据工作树,含 10.2G mac-backups 备份 |
| 3 | `/Users/linhuichen/code/trade-data-signal-staticdata` | 4.7G | staticdata blobless 镜像(健康,在用) |
| 4 | `/Users/linhuichen/code/trade-data-signal-staticdata-old-20260926` | 8.3G | **用户拍板保留至 2026-10-30,不是垃圾** |
| 5 | `~/.claude/projects/-Users-linhuichen-code-trade` | 2.6G | Claude 会话历史(jsonl+子目录) |
| 6 | `~/.claude` 其余(jobs/backups/file-history/plugins) | ~0.2G | — |
| 7 | `/tmp/restore_test`(项目相关 scratch) | 164M | **10-07 17:05 仍在更新=活跃,勿动** |
| 8 | `/tmp/AweSun_*.dmg/pkg` | 198M | 非项目(AweSun 安装包残留) |
| 9 | `~/code/wt` / `微话dev` / `trade-data-dataset` | 294M / 26M / 108K | 非本项目 |
| | **合计(1~8)** | **≈41G** | |

## ① 占用统计表

### 1.1 主仓 `/Users/linhuichen/code/trade` 顶层分解(du -sh,17:12 时点)

| 目录 | 占用 | 备注 |
|---|---|---|
| `data/` | 4.2G | 本地数据(gitignored 为主) |
| `static-site/` | 1.8G | 其中 `static-site/data/` 1.8G |
| `.git/` | 1.7G | 见 1.3 |
| `.venv/` | 652M | Python 虚拟环境(可再生) |
| `docs/` | 279M | 其中 `docs/kelly/` 266M(见 1.2) |
| `.claude/` | **271M→130M(时点值)** | 首测 271M;17:13 复查 130M(仅 1 个活跃 worktree);以现值为准 |
| `scripts/` | 43M | |
| `data_packs/` | 5.6M | |
| 其余(app/a-stock-data/config/worker/relay 等) | 均 <5M | |

`.claude/worktrees/` 现值 **130M**,仅 `agent-abef716d45a426513`(分支 `feat/212-upload-onfail-20261007`,locked,pid 9789 `claude --resume` 已运行 23.5h)= **活跃 worktree,保留**。`git worktree list` 共 2 项(主仓 main+此 worktree)。

### 1.2 大文件 Top(主仓 >50MB 逐个,含 1 个 103M docs 研究文件)

| 文件 | 大小 | 性质 |
|---|---|---|
| `data/public_fund.db` | 2.3G | 本地 DB(保护项) |
| `data/release/public_fund.db.tar.gz` | 552M | 8-10 备份包,**用途待核** |
| `data/etf_national_team.db` | 240M | 保护项 |
| `data/etf_national_team.db.bak-p0-20260909-1345` | 176M | 9-9 P0 备份,无文档 |
| `data/etf_national_team.db.bak-p0-20260909` | 176M | 同上(与 trade-data 同名文件 md5 相同=重复) |
| `data/daily-k.parquet` | 173M | 保护项 |
| `data/sentiment.db` | 126M | 保护项 |
| `.venv/.../playwright/driver/node` | 116M | venv 内部 |
| `data/stock_daily.db` | 111M | 保护项 |
| `docs/kelly/backtest-ai/etf-weight-leader/data/signal_kelly_stock_trades.json` | 103M | **gitignored 研究中间产物** |
| `data/stock_top_weights.db` | 93M | 保护项 |
| `static-site/data/signal_kelly_trades.json` | 82M | 上线数据 |
| `static-site/data/signal_kelly_trades_sdc.json` | 75M | 上线数据 |
| `data/release/etf_national_team.db.tar.gz` | 50M | 待核 |
| `.venv/.../py_mini_racer/libmini_racer.dylib` | 50M | venv 内部 |

### 1.3 `.git` 内部构成(只读)

| 项 | 实测 |
|---|---|
| `objects/pack` | 1.6G(18 个 pack,最大两个 286M+287M) |
| 松散对象 | **4,872 个 / 116.54 MiB**(count-objects:size=116.54 MiB,in-pack 108,824,packs 18,prune-packable 0,garbage 0) |
| `lost-found/` | 17M(498 commit + 190 other,8-26 一次 `fsck --lost-found` 产物) |
| `fsck --connectivity-only`(只读) | 无 missing/corrupt;**dangling:442 commit + 96 blob + 38 tree** |
| `logs/` 2.7M / `worktrees/` 488K / `modules/` 224K | — |
| `stash` | **3 条**(含「主worktree脏改动09-08…归属待用户定」) |

> 口径说明:云上两仓已于 10-01 做过 `git gc`(holiday-window 执行报告),**本机仓从未 gc**,116M 松散对象与 576 个 dangling 是 gc 可回收面(预估释放 ~100M+,精确值需 gc 后实测)。

### 1.4 `trade-data`(16G)分解

| 子项 | 占用 | 备注 |
|---|---|---|
| `data/mac-backups-20261001/` | **10.2G** | 86 文件(43 etf + 42 sentiment 的每日 DB 快照,7-18~9-11);8.3.1 详述 |
| `data/public_fund.db` | 2.3G | 与 trade 侧近同(见 1.5) |
| `data/etf_national_team.db` | 240M | 与 trade 侧 md5 一致 |
| `data/etf_national_team.db.bak-p0-20260909` | 176M | 与 trade 侧同名文件 md5 一致(重复) |
| `data/daily-k.parquet` | 173M | 与 trade 侧 md5 一致 |
| `data/logs/` | 354M | 见 3.2(大头:rotate 64M / inbox err 46M / snapshot 26M / lab 19M / req-dump 17M / rotate-req 16M / proxy-req 11M) |
| `data/sentiment.db` | 126M | 与 trade 侧**不同**(10-06 更新版) |
| `data/stock_daily.db` | 111M | 与 trade 侧 md5 一致 |
| `static-site/` | 2.0G | 其中 `data/` 1.8G + 根下 **107 个 html 196M**(见 3.4) |
| `.venv/` | 430M | 可再生 |
| 其余 | <10M | |

#### 1.4b trade-data >50MB 逐项(不含 mac-backups 内部,后者 41 个 150-177M 文件已汇总为 10.2G)

| 文件 | 大小 |
|---|---|
| `data/public_fund.db` | 2.3G |
| `data/etf_national_team.db` | 240M |
| `data/etf_national_team.db.bak-p0-20260909` | 176M |
| `data/daily-k.parquet` | 173M |
| `data/sentiment.db` | 126M |
| `data/stock_daily.db` | 111M |
| `static-site/data/signal_kelly_trades_sdc.json` | 84M |
| `static-site/data/signal_kelly_trades.json` | 82M |
| `data/logs/sensenova-rotate.log` | 64M |
| `.venv/.../py_mini_racer/libmini_racer.dylib` | 50M |
| `data/mac-backups-20261001/`(41 个 >150M + 其余) | 10.2G(整) |

### 1.5 双树同名文件重复度抽查(md5 逐位)

| 文件 | trade 侧 | trade-data 侧 | 判定 |
|---|---|---|---|
| `etf_national_team.db`(240M) | 182745b6… | 182745b6… | **完全一致** |
| `stock_daily.db`(111M) | e13f68b2… | e13f68b2… | **完全一致** |
| `daily-k.parquet`(173M) | d50d52cc… | d50d52cc… | **完全一致** |
| `sentiment.db`(126M) | 38a805d2… | 5f6fcb97… | **不同**(trade-data 侧 10-06 更新) |
| `public_fund.db`(2.3G) | size 2,498,482,176(9-13 05:12) | size 2,498,605,056(9-13 08:03) | 未 md5(体积大),近似不同 |
| `etf_national_team.db.bak-p0-20260909`(176M) | 55926b74… | 55926b74… | **完全一致**(跨树重复) |

> 双树(memory `trade-data-code-dirs-are-symlinks`:代码 symlink、数据实体)是设计结构,**两侧数据均活跃**(近期 mtime 更新),不是冗余垃圾,列入保留。

### 1.6 `~/.claude/projects/-Users-linhuichen-code-trade`(2.6G)分解

| 会话 | 顶层 jsonl | 子目录(subagents+tool-results) | 最近活动 |
|---|---|---|---|
| `3ba5f717-…` | 144M | **1.0G** | 10-05 |
| `4f92f6a5-…` | 124M | 620M | (旧) |
| `d08c47ab-…` | 39M | 306M | **10-07 活跃(当前会话)** |
| `27a3871b-…` | 31M | 186M | (旧) |
| `1ddfbd20-…` | 106M | 63M | 10-05 |
| 其余 2 个 | <0.5M | — | — |
| `memory/`(245 项) | — | 1.2M | 10-07 |

### 1.7 邻近目录(只读核对)

- `trade-data-signal-staticdata`(4.7G):blobless 镜像+工作区,在用(9-30 复核健康,memory `staticdata-old-mirror-keep-decision`)。
- `trade-data-signal-staticdata-old-20260926`(8.3G):**用户拍板保留至 2026-10-30**(已挂 cron 541d860f 到期复核),不得擅动。
- symlink 核对(实测 `ls -la`):`trade-data/{app,config,scripts,a-stock-data,docs,web}` 均为 symlink → trade 对应目录(与 memory 一致);`data`、`static-site` 为实体。

## ② 可清理候选分级(甲乙丙;每项带判据+§25 恢复路径)

> **本轮只出清单,不执行任何删除**;所有删除动作须走 §25(先备份→实测可恢复→再删),执行另行派单。

### 甲类 = 有独立副本/可重建,可安全清(⚑=已有拍板或明确归档可查)

| # | 项 | 大小 | 判据 | §25 恢复路径(一行) |
|---|---|---|---|---|
| 甲1⚑ | `trade-data/data/mac-backups-20261001/`(整目录) | **10.2G** | 备份目的已完成(10-02 从 R2 取回全量对账 86/86 PASS);处置方向用户已拍板=**压缩(zstd -19,整包 2.122 GiB)异地归档 R2 + 删本机原件**(docs/ops/r2-slim-compression-measure-20261004.md 定稿;执行与否待主控核 pending #186) | `python3 docs/scripts/restore_mac_backups_r2.py put-restore`(或从 R2 归档包取回解压);⚠️ 原对账锚点 `/tmp/mac_backups_upload_log_20261001.txt` 已不在本机 |
| 甲2 | `data/release/`(4 个 db tar.gz) | 657M | 8-10 一次性备份包;**检索 scripts/docs 无引用**(用途待核,疑似历史迁移发布包) | 无自动恢复;先核实用途(建议主控查 8-10 前后会话/任务),确认后移 R2 decommissioned 归档 |
| 甲3⚑ | `data/etf_national_team.db.bak-backfill-20260728-232308`(37M)+ `data/alert_state.json.bak-*`×2 | 37M+16K | **R2 `signal-backup/decommissioned/` 已有 .gz/tar.gz 归档**(docs/decommissioned-backups.md);⚠️ 该文档记「已清理」但**实测文件仍在本地**(诚实标注,疑被恢复或记录偏差) | `bash scripts/restore-r2-backup.sh etf_national_team.db.bak-backfill-20260728-232308.gz`(及 `decommissioned-small-baks-20260903.tar.gz`) |
| 甲4 | `.git/lost-found/` | 17M | 8-26 `fsck --lost-found` 输出副本;dangling 内容无引用价值(Dangling 对象可随时重扫) | 重跑 `git fsck --lost-found`;内容无业务价值,可弃 |
| 甲5 | 旧大日志(trade-data/data/logs 中 7 个 >10M,合计 ≈199M) | 死亡段≈153M | 逐文件 mtime 判活:update_lab 9-12、intraday_snapshot 9-13、thinking-proxy(-req)8-25/9-1、sensenova-rotate 10-05、agent_inbox_watcher err 10-06(**仍在长,46M**);死亡段可归档后清,**活跃的用轮转不删** | 日志无需恢复(如需留存 gzip 归档);活跃文件建议截断/轮转(另派) |
| 甲6 | `/tmp/AweSun_*.dmg/pkg` | 198M | 非项目文件(安装包残留) | 重新下载即可,无恢复需求 |

### 乙类 = 备份/归档后可删(§25 流程)

| # | 项 | 大小 | 判据 | 恢复路径 |
|---|---|---|---|---|
| 乙1 | `data/etf_national_team.db.bak-p0-20260909`(trade)+ 同名(trade-data)+ `-1345` 版 | 176M×2(重复)+176M | 9-9 时点备份;**全库检索 docs/ops 无任何引用文档**(用途待核);其中两份 md5 相同=跨树重复 | 无归档;删前须先归档(如 R2 decommissioned);⚠️ 用途未核前不建议动 |
| 乙2 | 研究中间产物:`etf-weight-leader/data/signal_kelly_stock_trades.json` 103M + `hold-days-sweep/hold_sweep_trades.json` 27M + `position/scripts/accum_nav/` 28M + `accum_nav_map.json` 25M | ≈183M | gitignored(.gitignore:286/242/245),不进 git;**可由脚本+源 DB 重建**(etf-weight-leader/scripts/、export_accum_nav_map.py 在位) | 重跑对应脚本重建(重建成本:分钟级);或归档 |
| 乙3 | `~/.claude/projects/` 4 个旧会话(3ba5f717/4f92f6a5/27a3871b/1ddfbd20) | ≈2.3G | 会话历史=/resume 原料,**删则失去对应会话恢复能力**;当前会话 d08c47ab 必须保留 | §25:先打包归档(如 `~/.claude/backups/`)再删;无则不可恢复 |
| 乙4 | `.git` 松散对象 gc 化 + dangling 清理 | 116M + 576 对象 | 松对象 4,872 个未 pack;576 dangling 可 prune;`git gc` 即可,**非删文件** | 无需恢复(gc 只做压缩/清理);**须用户批准+择时**(活跃仓,建议避开盘中/盘后任务时点) |
| 乙5 | `/tmp/restore_test/`(164M) | 164M | **10-07 17:05 仍在更新=活跃**(疑为 #212/#231 相关测试 scratch) | 勿动;测试收尾由对应 agent 自清 |

### 丙类 = 保留(不得动)

| 项 | 大小 | 原因 |
|---|---|---|
| `staticdata-old-20260926` | 8.3G | **用户拍板保留至 2026-10-30**(cron 541d860f 到期复核) |
| `staticdata` blobless 镜像 | 4.7G | 在用,9-30 复核健康 |
| 双树 `data/` 活跃数据(含重复副本) | 4.2G+14G | 设计结构,两侧均活跃(1.5 表) |
| 根 `data/` 保护项(public_fund/etf_national_team/sentiment/signal_stats 等) | — | 任务书明令不动 |
| 活跃 worktree `agent-abef716d45a426513` | 130M | pid 9789 存活,正在使用 |
| `.venv`×2(trade 652M + trade-data 430M) | 1.1G | 可再生但重装成本高,链在路上 |
| 0 字节 DB 空壳 ×7(board_concept/fund/etf_daily/mootdx_daily/signal/signal_stats/trade.db) | 0 | 运行期自建,无害 |

## ③ 过期/无效识别(专项)

1. **僵尸 worktree 残留:0**。`git worktree list` 仅 2 项(主仓+1 活跃);`.claude/worktrees/` 130M;`.git/worktrees/` 仅 1 个活跃记录。10-03/10-05 已有两轮清理落档(docs/ops/worktree-cleanup-20261003.md、branch-residual-triage-20261005.md)。
2. **未跟踪大文件残留**:`git status --porcelain` 主仓 **干净(0 条)**;大文件均在 gitignore 覆盖区(static-site/data、docs/kelly/*/data 等)。最大未跟踪项=1.2/1.5/乙 各表。
3. **可再生缓存**:`__pycache__` 24 个目录/373 个 .pyc 合计 **12M**(小);`.pytest_cache` 40K;`static-site/__pycache__` 148K;`.wrangler` 208K;`test-results` 4K——合计 <13M,**不值得专项清**。
4. **旧版 HTML 兜底产物**(trade-data/static-site 根下 107 个 `trade_sim_*.html`,103 个 mtime=7-29,4 个 7-23,合计 196M):JSON 模式已替代 HTML 兜底(update_lab.sh 注释「旧版 trade_sim.html 已停用(2026-08-21 清理)」);**用途待核**(线上可能仍有链接或从未上线)。trade/static-site 侧另有 12 个 html(其中 7 个 8-2 的 trade_sim_* 同族)。
5. **旧备份包**:data/release 657M(甲2)、p0 备份 528M(乙1)、mac-backups 10.2G(甲1)。
6. **/tmp scratch**:项目相关仅 restore_test(164M,活跃)+ mac_backups 相关文件已清;AweSun 198M 非项目。
7. **stash 3 条**:含「归属待用户定」条目(09-08),建议主控转呈用户拍板去留(互相独立,勿静默清)。

## ④ 诚实标注(推断 vs 实测 / 无法确认项)

1. 全部数字为**只读实测**(du/md5/ls/git 命令输出);仅以下为**推断**:①`public_fund.db` 双树"近似不同"(未 md5,仅 size+mtime 不同)②.git gc 可释放"~100M+"(未执行 gc,精确值不可得)③data/release「历史迁移包」性质(检索无引用,未见创建文档)。
2 **审计期间仓库活跃**导致时点漂移:`.claude/worktrees` 271M(17:12 首测)→130M(17:13 复查);main HEAD 010282316→6a6bb432f;`/tmp/restore_test` 17:05 仍在更新。所有"可删除"判定请以**执行前复查**为准。
3. **用途待核**项(勿轻删):data/release(657M)、p0 备份 ×3(528M)、107 html(196M)、mac-backups 的执行状态(方案已定稿,是否已派单未在本轮确认)。
4. 「decommissioned 文档说已清理 vs 实测文件仍在」:backfill .bak 37M 与 alert_state 2 个 .bak 实测存在于 data/ 下,与 docs/decommissioned-backups.md「已清理」记载**不符**;矛盾原因未查明(可能被恢复/重现),删除前请以 R2 归档实际在位为准复核。
5. **mac-backups 处置已有多轮论证**:10-01 家清(备份到 R2 后删本机)→10-02 取回(为缩 R2 桶)→10-04 压缩率实测定稿方案。本轮仅确认其占 10.2G 且方案文本在位,**未执行任何动作**。
6. 边界再声明:本报告不含云上磁盘(122.51.111.173)与 R2 桶占用;~/.claude 的 jobs(71M)/backups(28M)/file-history(27M)未深挖构成。

## ⑤ 附:关键证据命令(可复跑)

```bash
du -sh /Users/linhuichen/code/trade /Users/linhuichen/code/trade-data
du -sh /Users/linhuichen/code/trade/.git/*  | sort -rh
git -C /Users/linhuichen/code/trade count-objects -vH
git -C /Users/linhuichen/code/trade fsck --connectivity-only --no-progress | awk '{print $2}' | sort | uniq -c
ls -lhS /Users/linhuichen/.claude/projects/-Users-linhuichen-code-trade/*.jsonl
md5 -q .../etf_national_team.db(双树对账,见 1.5)
git -C /Users/linhuichen/code/trade worktree list
```

> 报告落档:docs/ops/disk-usage-audit-20261007.md(2026-10-07,role-researcher,只读审计)。
