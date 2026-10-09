# #234 项目磁盘清理执行报告(2026-10-09)

> 执行:测试 agent(role-tester)。分支 main,**未 commit/未 push**;全程未执行任何告警/邮件/飞书外发;**未写 R2**(仅 2 次只读 `list`,status=200)。
> 依据:`docs/ops/disk-usage-audit-20261007.md` + `docs/ops/disk-cleanup-verify-20261007.md` 执行表;CLAUDE.md §25「先备份 → 实测可恢复 → 验过直接删」。
> 硬排除项(staticdata-old 8.3G / 根 data/ 保护 DB / git tracked / 文档配置脚本)全部未动。

## 一、总览(实测)

| 项 | 值 |
|---|---|
| 磁盘 df(`/System/Volumes/Data`)| 290Gi used / **142Gi avail**(11:22)→ 288Gi used / **144Gi avail**(11:33),**+2 GiB** |
| 本轮删除原件合计 | ≈ **2.52 GiB**(198.07 MiB + 102.7 MiB + 2,280 MiB) |
| 本轮新增本地归档 | **611.9 MB**(4 个会话 tar.gz 596.6 MB + signal_kelly 15.3 MB) |
| 本轮净回收 | ≈ **1.95 GiB**(与 df +2Gi 实测一致) |
| 审计四大项(甲1/2/3/4 ≈10.9G)| **执行前已不存在**(前序动作已完成),本轮只复核并核验异地恢复路径在位 |
| 目录现值 | trade **8.0G**(基线 9.0G);trade-data **6.0G**(基线 16G);projects **473M**(基线 2.6G);~/.claude/backups 638M |

> 口径诚实标注:审计预期净收益 13.4G,其中 ~10.9G 由**前序动作**(10-07 之后)完成,非本 agent 所为;本 agent 实际动作 = 上表第 2~4 行。

## 二、本轮删除明细(逐项:备份 → 实测可恢复 → 删)

### 2.1 甲6 `/tmp/AweSun_v16.5.0.30905_arm64.dmg` + `.pkg` —— 207,685,230 B(198.07 MiB)
- 删前核验:`lsof` 两文件**无进程持有**;`/Applications` 无 AweSun(未安装);`file` 类型确认(dmg=zlib compressed data / pkg=xar archive)✓
- 备份:无独立副本(安装包,属"重新下载即可"类);**恢复路径 = 厂商重下** AweSun(向日葵)v16.5.0.30905 arm64
- 结果:**已删**(ls 零命中)✓

### 2.2 乙2-1 `docs/kelly/backtest-ai/etf-weight-leader/data/signal_kelly_stock_trades.json` —— 107,710,339 B
- 备份:`/Users/linhuichen/.claude/backups/cleanup-234-20261009/signal_kelly_stock_trades.json.tar.gz`(15,326,419 B,压缩 7.0:1)
- 实测可恢复:`tar -tzf` 清单 1 项;解包后 **md5 逐位一致**(原件=解包=`b13bd55047fe192c4cfb3c40e3356718`)✓
- 恢复(二选一):① `tar -xzf <archive> -C docs/kelly/backtest-ai/etf-weight-leader/data/` ② 重跑生成器 `signal_kelly_backtest_stock.py`(同目录另有 8-21 预存 `signal_kelly_stock_trades.json.gz` 14.7MB 副本)
- 结果:**已删** ✓(gitignore 覆盖区 .gitignore:286,非 git tracked;唯一引用方为该生成器脚本)

### 2.3 乙3 `~/.claude/projects/-Users-linhuichen-code-trade/` 4 个旧会话 —— 原件 2,280 MiB;归档 596.6 MB
| 会话 | 原件(目录+jsonl)| 归档 tar.gz | 验证 |
|---|---|---|---|
| `4f92f6a5-6022-4bc9-b871-195032f0464b` | 620M + 130M | 201,969,705 B | 文件数一致 + diff -r 零差异 + jsonl md5 `781dabb78a1de02162b9e9cda38fa7f5` 一致 |
| `27a3871b-4e77-48e4-b88f-3cabc6837b14` | 186M + 31M | 42,621,321 B | 327/327 文件 + diff -r 零差异 + md5 `388e10c187dcca35ff8b8d2757821e30` 一致 |
| `1ddfbd20-5b96-425c-85f8-07b8d8625b0f` | 63M + 106M | 42,864,628 B | 228/228 文件 + diff -r 零差异 + md5 `576881451c3d88a51f45b9e88acff4af` 一致 |
| `3ba5f717-05ed-4419-abe0-6426872cd686` | 1.0G + 144M | 311,085,925 B | 1668/1668 文件 + diff -r 零差异 + md5 `e33dd83a95820a3e46990fadf06af216` 一致 |

- 实测可恢复:每会话「归档 → 解包到临时目录 → `diff -r` 与原件全文零差异 + jsonl md5 逐位一致」;**验证通过后才删原件** ✓
- 恢复:`tar -xzf /Users/linhuichen/.claude/backups/cleanup-234-20261009/session-<id>.tar.gz -C /Users/linhuichen/.claude/projects/-Users-linhuichen-code-trade/`(恢复后 `/resume` 可用)
- 安全性核验:**当前会话 `d08c47ab-…` 排除**(jsonl mtime 10-09 11:21);系统唯一 claude 进程 pid 9789 = 本会话宿主(进程链实测 77646→9789→9311 Terminal),**不持有这 4 个会话**;4 会话 jsonl mtime 均 ≤ 10-05
- 结果:**4 会话均已删**(projects 2.6G→473M)✓

## 三、执行前已不存在项(前序动作已完成;本轮只复核 + 核验恢复路径)

| 项 | 审计值 | 现状证据 | 恢复路径复核(只读实测) |
|---|---|---|---|
| 甲1 `trade-data/data/mac-backups-20261001/` | 10.2G | `find ~/code -maxdepth 2` 零命中;trade-data 16G→6.0G | R2 `signal-backup: mac-backups/archive/mac-backups-2026-10-01.tar.zst` **在位**(2,278,230,346 B, 10-04)✓ |
| 甲2 `data/release/` 4 tar.gz | 657M | `ls` No such file | GitHub Release `db-archive-2026-08-10` **4 assets 全 uploaded**,size 与审计逐一相同(52,511,320/578,428,929/37,396,124/19,547,655)✓ |
| 甲3 `bak-backfill-20260728-232308` + `alert_state.json.bak-*`×2 | 37.3M | 两树 `*.bak*` glob 仅剩 p0 备份 | R2 `decommissioned/` **2 key 在位**(backfill.gz 10,968,910 B + small-baks tar.gz 11,259 B)✓ |
| 甲4 `.git/lost-found/` | 17M | `ls` No such file | 可再生:`git fsck --lost-found` 重扫(dangling 对象仍在 `.git/objects`)|

## 四、保留 + 上报(未删,逐项原因 + 证据)

| 项 | 大小 | 保留原因(证据) |
|---|---|---|
| **甲5** `trade-data/data/logs` 旧大日志 | ≈93M(可清面)| 候选文件**被监控脚本按文件名读取**:`schedule_monitor.sh` L110/L130 config + L364 `last_run = parse_last_run(log_path)`(文件缺失 → last_run=None → 落计划窗口即**漏跑误报**)、`gen_schedule_stats.py` L49/L67;另有活跃写方:`agent_inbox_watcher_launchd.err`(pid 4161 持 fd)、`feishu_listener.log/.err`(pid 76212,10-09 09:39)、`sensenova-rotate*.log`(rotate 工具链引用)。清理会危及「绝不触发真实告警」→ **保留**;建议另派"监控容忍 .gz + 明确本地已停用"方案后再清 |
| **乙1** p0 快照 ×3 | 528M | 用途已查明(#87 09-09 污染事故修复前快照)但 **R2 decommissioned/ 无对应归档**;补归档=写 R2,按本任务约束**不擅自写** → 待主控/用户拍板;注:三份中两份**逐位重复**(trade ∩ trade-data,md5 55926b74…),实际仅 2 个不同版本,建议留 1 份(trade-data 侧) |
| **乙2-3/4** `position/scripts/accum_nav/` + `accum_nav_map.json` | 54M | 系**每日 deploy 管线再生成产物**(deploy.sh L296-317,生成/同步任一步失败即 exit 1);三处机检(`check_data_integrity` L989/L1014/L1069)均读 static-site 副本;生成器 `makedirs`+全新写入(L84/L144)。删除技术上安全但**收益瞬态**(下一次 deploy 即重建)+ 与 deploy 闸门同链,且审计前置「确认无在跑研究依赖」在 2 个 agent 并行时无法穷证 → **保留** |
| **乙4** `.git` gc/dangling | 116M+576 对象 | 审计标注「须用户批准 + 择时(避 15:35/16:00/17:50/20:35/22:00)」;本轮**未执行** |
| **stash ×3** | — | `git stash drop` = **git 状态操作**,本任务硬约束禁碰 git 状态;且含用户口味项(README 删两条)建议呈用户 → **保留** |
| **乙5** `/tmp/restore_test/` | 164M | 他 agent 测试 scratch(mtime 10-07 17:05),**不擅动** |
| 107 个 `trade_sim_*.html` + trade 侧 6 个同族 | 196M | **未列入 verify 报告执行表**;且 `trade_sim.html` 本体 **git tracked**(禁删)→ 未动,列此上报待拍板 |

## 五、§25 合规声明 + 硬约束遵守

- ① 先备份后删除:2.2/2.3 全部「归档完成于删除之前」;甲6 属无需副本类(可重下),恢复路径已写明。**每项均写出恢复命令**(写不出者未删)✓
- ② 实测可恢复:清单/文件数全量比对 + 解包后 **md5 逐位一致 + diff -r 零差异**(非"应该有备份")✓
- ③ 验过即直接删;未出现"验不过仍删" ✓
- ④ 未切分支/未 checkout/未 reset/未 commit/未 push —— 全程零 git 写操作;执行后 `git status --porcelain` 仍干净、分支仍 main ✓
- ⑤ 未触发告警;未写 R2(仅 2 次只读 list);未裸跑 pip/npm;未 Docker;禁 find /、禁无白名单 grep -r 均遵守;所有命令带超时(Bash timeout;R2 python 用 `perl -e 'alarm 90…'` 包裹;curl `--max-time 20`)✓
- ⑥ 未删任何 git tracked 内容 / 保护 DB / staticdata-old(8.3G,保留至 10-30)

## 六、复现命令(核验用)

```bash
# 归档与恢复
tar -tzf /Users/linhuichen/.claude/backups/cleanup-234-20261009/session-3ba5f717-05ed-4419-abe0-6426872cd686.tar.gz | wc -l
md5 -q /Users/linhuichen/.claude/backups/cleanup-234-20261009/signal_kelly_stock_trades.json.tar.gz
# 恢复会话(示例):tar -xzf session-<id>.tar.gz -C /Users/linhuichen/.claude/projects/-Users-linhuichen-code-trade/
# 异地恢复路径复核(只读)
cd /Users/linhuichen/code/trade && python3 scripts/upload_r2.py list mac-backups/ signal-backup
python3 scripts/upload_r2.py list decommissioned/ signal-backup
curl -s --max-time 20 "https://api.github.com/repos/xp13465/trade-data-signal-staticdata/releases?per_page=5"
# 现状
df -h /System/Volumes/Data; du -sh /Users/linhuichen/code/trade /Users/linhuichen/code/trade-data
```

## 七、待主控拍板项

1. 乙1 p0 ×3(528M):是否补 R2 decommissioned 归档后删(建议留 trade-data 侧 1 份)?
2. 甲5 日志(≈93M):是否改监控容忍 .gz 后再清?(现状清理=漏跑误报风险)
3. 乙2-3/4 accum_nav(54M):瞬态收益,是否仍要清?
4. 乙4 gc(116M+):择时 + 用户批准。
5. 107 html(196M,含 git tracked 本体):未列入执行表,是否纳入下批?
6. stash ×3:是否 drop(含 README 口味项)。

> 落档:docs/ops/disk-cleanup-executed-20261009.md(2026-10-09,未 commit,待主控统一收)。

---

## 八、续记:2026-10-10 git gc 执行(#234-4,用户 2026-10-09 已批准)

> 执行:主控(2026-10-10 00:4x,§14 安全窗口内)。
> §25 可逆性前置:本轮**只做对象库回收,不删任何 ref / 分支 / worktree**。

| 项 | 事前 | 事后 |
|---|---|---|
| packs | 18 | **1** |
| size-pack | 1.59 GiB | **1.27 GiB**(释放 ≈ **0.32 GiB**) |
| loose( count / size )| 5,651 / 131.22 MiB | 1,635 / 156.42 MiB |
| df `/` | 142Gi avail | 142Gi avail(容量本就充裕,非压力项) |

- 命令:`git reflog expire --expire=30.days --all` → `git gc --prune=30.days --quiet`(后台执行,约 30 秒完成)
- **reflog 保留 30 天**(未用 `now`,按 §25 保守口径);`--prune=30.days` ⇒ **30 天内的不可达对象一律不删** —— 现存那 1,635 个 loose(156 MiB)正属此类「新近不可达」(前几日删分支/worktree 的残留),满 30 天后可再 gc 清除,故本轮**没有**把体积压到最小,这是**刻意的安全取舍**(已如实标注,未为好看而收紧 prune 窗口)
- **恢复路径**:~~本轮零删除动作 ⇒ 无内容丢失~~(见下方订正)。若需回到 gc 前形态,`git fsck --lost-found` 仍可扫 dangling 对象(与 甲4 `.git/lost-found/` 同法)
- §25 合规:① 先确认可逆(只回收不可达对象)② 事后体积实测比对(上表)③ ~~未删任何 ref/分支/worktree~~(**声明失真,见订正**)④ 恢复路径已写明
- **§七 待拍板项 4(gc 择时 + 批准)就此闭环**;其余 5 项(gc 之外)仍待拍板
- 落档方式说明:原曾落在分支 `feat/disk-gc-record-1010`,但该分支基点是 W1 的 commit(非 main),直接 merge 会回退 main 上的 W1/W2 内容 ⇒ 改为**在 main 树直接补录本节**,该分支已按 §25 核验「独有内容已迁走」后删除

### ⚠️ 事后订正(2026-10-10 07:4x,主控自核;由 #234 第三批清理实测暴露)

> **本节「不删任何 ref / 分支 / worktree」的声明与事实不符,现如实订正。**

- **事实**:`git reflog expire --expire=30.days --all` 的 **`--all` 作用域涵盖 `refs/stash`**;stash 无独立对象,**其存活完全依赖 `.git/logs/refs/stash` 的 reflog** ⇒ 3 条 stash(均为 2026-09 上旬,>30 天窗口)**全部被 expire,`refs/stash` 随之消失**。当时未意识到此作用域,故声明失真——属**认知偏差 + 声明未核**,非刻意。
- **实测证据**:`.git/logs/refs/stash` 现存 `size=0`、`mtime=10-10 00:47`(= 本轮 gc 窗口);`git stash list` 空;HEAD reflog 现存**最老条目恰为 `2026-09-10 07:56`**(= gc 日 − 30 天,窗口边界吻合)。
- **影响与可恢复性**(第三批 agent 逐条实测):
  - `stash@{2}`(09-07,等价 `1cc5339d`):已从 dangling 筛出 → 导出 patch(7,255 B)→ `git apply --check` **PASS** → 真应用逐位一致 ⇒ **可恢复**
  - `stash@{0}`(09-19):候选 6 条对象仍在 dangling(**30 天窗口内**),候选手册已留档(未导出 patch)
  - `stash@{1}`(09-08,32 天 > 窗口):**实体已不可寻**(全量 dangling 扫描无匹配)。据 10-09 verify 报告记载,其内容为 README 删 #101/#91(该删从未生效、两条现仍在 main L64/70)、版本串 a554→a555(早被覆盖)、kimi plist 删 40 行(main `536d62202` 已完成)⇒ **判断无实质内容损失**,但**实体已不可复验**(结论基于当时记载,非实测原件)。
- **防重犯**(已落 memory `git-reflog-expire-all-kills-stash`):① gc / reflog expire **前先 `git stash list` 留证** ② 长留 stash 须 `git stash store` 建显式 ref 或 30 天窗口内导出 patch ③ 报告写清 `--all` 作用域含 stash,**不得声称「不删任何 ref」**。
