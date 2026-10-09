# #234 磁盘清理剩余批次(第三批)执行报告 —— 2026-10-10

> 执行:测试 agent(role-tester)。分支 **main**,**未 commit**(报告落 docs/ops/,待主控统一收)。
> 依据:`docs/ops/disk-cleanup-executed-20261009.md`(§一/§四/§七 待拍板 6 项)+ `docs/ops/disk-cleanup-verify-20261007.md`(用途核实);CLAUDE.md §25 铁律;用户 2026-10-10 拍板「磁盘清理做好备份就可以」(按 §25 授权,不必逐项请示)。
> **残留后台任务声明:无**。自查证据:本 agent 转录 81 条 Bash 调用(截至报告落档),`run_in_background` = 0 次;后台化标记(「moved to the background / running in background / Command timed out」)= 0 次——转录中另可见 3 处同类字样,经逐条核对均为本 agent 自查脚本「引用父会话历史」的输出文本,非本 agent 命令的后台化事件;is_error 仅 3 条普通报错(git ls-files exit 128、首次上传 PUT 超时后已换法成功、末次 grep exit 1)。
> 全程**零真实外发**(无邮件/飞书/告警);**零 git 状态写操作**(不 commit/push/checkout/reset/stash drop;收尾 `git status --porcelain` 仅本报告文件 untracked(无其它改动)、`git stash list` 空、分支 main)。

## 一、总览

| # | 项 | 审计值 | 本轮动作 | 结果 |
|---|---|---|---|---|
| 1 | 乙1 p0 快照 | 528M | R2 归档 → 实测可恢复 → 删 | ✅ **已删**(实测 2 份=369,221,632 B) |
| 2 | 甲5 旧大日志 | ≈93M | 只核实,**禁删** | ⛔ 未删(附改造点清单,§2.2) |
| 3 | 乙2-3/4 accum_nav | ≈54M | 先实测再定 | ⏸ **判定不做**(稳态再生,§2.3) |
| 4 | trade_sim html | ≈196M | 甄别 → 备份 → 验证 → 删 | ✅ **已删 109 个**(210,275,586 B) |
| 5 | stash ×3 | — | 导出 patch + 验证 → drop | ⚠️ **ref 已不存在,零 drop**(异常上报,§2.5/§五) |

**容量账(字节级为准)**
- 删除原件合计:579,497,218 B ≈ **552.7 MiB**(p0 369,221,632 + trade_sim 210,275,586)
- 新增本地持久备份:≈ 21.9 MB(21,860,352 B,`~/.claude/backups/cleanup-234-20261010/`)
- **净回收 ≈ 557,636,866 B ≈ 531.8 MiB(≈0.52 GiB)**
- 中转 scratch:峰值 769M(`/tmp/p0-b3`,含解包验证副本)→ 收尾已清场(§2.6),净 0
- R2 侧新增:2 个归档 108,580,309 B(≈103.6 MiB,异地,不占本机)
- **df(`/System/Volumes/Data`,1Gi 粒度)**:任务起点 07:04 `290Gi used / 141Gi avail` → scratch 峰值期 07:28~07:35 `290Gi / 140Gi`(scratch 盖过删除量) → **清场后 07:42 `289Gi used / 141Gi avail`**。解释见 §2.6。

## 二、逐项明细

### 2.1 乙1 p0 快照 —— ✅ 已删(归档 → 可恢复实测 → 删)

**删前核验**
- 现状实测 = **2 份**(10-09 报告记 3 份;其中两份逐位重复 ⇒ 实为 2 个不同版本,现存 2 份恰为这 2 个版本):
  - trade-data 侧 `data/etf_national_team.db.bak-p0-20260909` — mtime 09-09 09:46,184,610,816 B,md5 `55926b744cca11d69ed32e90e91d6eb1`
  - trade 侧 `data/etf_national_team.db.bak-p0-20260909-1345` — mtime 09-09 13:45,184,610,816 B,md5 `e79d3cc8003106f4bea86e78339c2c85`
  - ⚠️ 10-09 报告所列第三份(trade 侧**无后缀**重复副本,= 55926b74 同款)在本轮动手前已不存在且无记录 ⇒ **上报(§五.1)**;消失者是重复副本,**两个不同版本实体均完好且均归档,零独有数据损失**
- 用途:#87 P0 事故(2026-09-09)修复前快照(verify 报告已查明);引用方核查 = 无脚本读取;**非 git tracked**(`git ls-files data/` 零命中);`lsof` 无进程持有
- R2 归档前置核实:旧桶 `signal-data/decommissioned/` KeyCount=0;新桶 `signal-backup2/decommissioned/` 基线 KeyCount=6(既有 6 个归档在位)

**备份(写 R2,任务授权范围内)**
- 落地 2 key(新桶 signal-backup2,`decommissioned/` 前缀):
  - `decommissioned/etf_national_team.db.bak-p0-20260909.gz` — **54,290,591 B**(上传 79s)
  - `decommissioned/etf_national_team.db.bak-p0-20260909-1345.gz` — **54,289,718 B**(上传 3:03)
- 命令:`R2_UPLOAD_HTTP_TIMEOUT=600 perl -e 'alarm 570; exec @ARGV' python3 scripts/upload_r2.py upload-decommissioned <本地gz> <key名>`
- 过程注记:首次用默认 socket 超时(30s)上传 **失败**(PUT TimeoutError ×4,总 2:22)→ 失败后核查 R2 **无残留 key**(KeyCount 仍 6)→ 抬 `R2_UPLOAD_HTTP_TIMEOUT=600`(代码 L306 注释明示云上用 600,属既有 env 通道)后 2 份均成功。**后续大件归档先设此 env**。

**实测可恢复(证据)**
- list 全量比对:KeyCount 6 → **8**;新 key size 54,290,591 / 54,289,718 与本地 gz **逐位一致**(本地 gz 已删前实测同尺寸)
- `bash scripts/restore-r2-backup.sh --out-dir /tmp/p0-b3/restored <key.gz>` 真跑:✓ 命中桶 `signal-backup2`;网络取回 54,289,718 B → gunzip 后 **184,610,816 B**;用时 13.5s(两份同,网络往返+解压全程)
- 取回件 md5 逐位:`55926b744cca11d69ed32e90e91d6eb1`(=原件)✓、`e79d3cc8003106f4bea86e78339c2c85`(=原件)✓

**删除结果**:`rm` 2 份;两树 `data/*bak-p0*` glob **零命中** ✓

**恢复命令**
```bash
bash scripts/restore-r2-backup.sh --out-dir <目标目录> etf_national_team.db.bak-p0-20260909.gz        # → 09:46 版(55926b74…)
bash scripts/restore-r2-backup.sh --out-dir <目标目录> etf_national_team.db.bak-p0-20260909-1345.gz   # → 13:45 版(e79d3cc8…)
```

### 2.2 甲5 旧大日志 —— ⛔ 未删(禁删;附改造点清单)

**现状核实(2026-10-10 07:2x 实测)**:`trade-data/data/logs` 总 **355M**;top 大文件(大小 | mtime):

```
67,149,855 B | 10-05 11:58 | sensenova-rotate.log
47,732,126 B | 10-06 17:35 | agent_inbox_watcher_launchd.err
27,365,828 B | 09-13 14:45 | intraday_snapshot_launchd.log
19,401,095 B | 09-12 19:00 | update_lab_launchd.log
16,629,841 B | 10-05 11:58 | sensenova-rotate-req.log
11,908,064 B | 09-01 01:57 | thinking-proxy-req.log
 9,915,368 B | 08-25 07:30 | thinking-proxy.log
 4,243,885 B | 09-13 03:37 | backfill_evening_launchd.log
```

活跃持有(lsof 实测 4 个 fd):pid 4161 → `agent_inbox_watcher_launchd.log`(fd1)+ `.err`(fd2);pid 76212 → `feishu_listener.log`(fd1)+ `.err`(fd2)。`schedule_monitor_launchd.log` mtime 10-06 18:15、**无 fd 持有**(本机监控当前未在跑)。

**禁删理由(精确引用点,按文件名读取)**:
- `scripts/schedule_monitor.sh` L84 LOG_DIR + L402-403 `parse_last_run(log_path)` → L227-241(文件不存在 ⇒ 返回 None)⇒ L425-433(落计划窗口 + 连续 2 轮)⇒ **SEVERE 漏跑误报**
- 同脚本 L1931-1932(`etf_national_team_launchd.log` 存在性判定)、L2396-2397(`feishu_listener.err` 存在性判定)= 同款「缺失静默跳过」漏检
- `scripts/gen_schedule_stats.py` L640/L818(`not log_path.exists(): return` 静默跳过)+ L820 `_read_tail_lines`
- `scripts/com.trade.thinking-proxy.plist` L33/35(StdOut/Err → `sensenova-rotate.log/.err`,守护进程 append)

**改造点清单(先改后清;未改前禁删)**
1. 方案 A(容忍 .gz):上述引用点加「`.log` 不存在 → 回退 `<name>.log.gz`(gzip.open)」— parse_last_run / L1932 / L2397 / gen_schedule_stats L640/L818/_read_tail_lines 共 6 处
2. 方案 B(停机登记,更简):schedule_monitor.sh + gen_schedule_stats.py 任务表加「本机已停用/retired」标记(仿 trading_day_only 跳过模式),注明停机日期
3. 决策前置:先确认本机(纯开发机)是否还跑这些 launchd——实测 `schedule_monitor_launchd.log` 已无 fd 且 mtime 10-06;若永久不跑 → B;若保留 → A
4. 验证方法(尺子先验):改完先造坏样本(临时把某 `.log` 改名 `.gz` / 删除)跑监控单轮,确认**不误报 + 解析正常**,再压缩清理
5. 联动:A 方案需同步改 plist(thinking-proxy 守护 append 目标)

**本次动作:零删除**(仅核实 + 清单)。

### 2.3 乙2-3/4 accum_nav —— ⏸ 判定不做(实测:稳态再生)

**实测数据**
- 生成侧:`docs/kelly/position/scripts/accum_nav/`(28M,1,693 文件)+ `accum_nav_map.json`(26,010,868 B),mtime 均 **10-06 17:57**
- 与 deploy 链吻合:本机 `trade-data/data/logs/deploy_20261006_1750.log` L565-569 载明本次 deploy 生成 map + split accum_nav/ + `cp` 同步 static-site(路径 = 本机 `/Users/linhuichen/code/trade/...`),时间逐分钟吻合
- `scripts/deploy.sh` L296-317:`rm -rf static-site/data/accum_nav` + 全量重建 + cp(**每次 deploy 必重建**;生成/同步任一步失败 exit 1 阻断)
- 节奏:本机 deploy 近月 09-11/12/13/18/19/22、10-06(不定但持续);**云上每日 deploy 在跑**(10-08 云上日志含 accum 成功段)
- 引用全查:仅 deploy.sh(L298/309/315)+ 生成器自身;机检(`check_data_integrity.py` L998/L1027)读 **static-site 侧副本**,不读 position 侧

**结论**:稳态再生成立 ⇒ 删除 = **收益瞬态**(下一次 deploy 立即重建),且与 deploy 闸门同链 ⇒ **不做,未动任何文件**。

### 2.4 trade_sim html —— ✅ 已删 109 个(先甄别 → 备份 → 验证 → 删)

**甄别**
- trade-data/static-site:`trade_sim_*.html` **103 个真文件**(204,784,968 B,mtime 07-29);`trade_sim.html` 本体 = symlink → trade 侧(未动)
- trade 侧 static-site:同族 **6 个**(5,490,618 B);`.gitignore:109` 覆盖(untracked);`trade_sim.html` 本体 **git tracked**(2,547,478 B,**禁删,未动**)
- 线上实测:109 个 URL 全量 curl(`ss.fx8.store`,浏览器 UA)⇒ **全 404**(批1 55/55、批2 48/48、trade 侧 6/6)
- git 跟踪核查:trade-data 非 git 仓库(无 .git);trade 侧 6 个 untracked+ignored ⇒ 删的 109 个均非 tracked

**备份(本地)**
- `~/.claude/backups/cleanup-234-20261010/trade-data-trade_sim-html-20261010.tar.gz`(20,816,032 B,103 文件)
- `~/.claude/backups/cleanup-234-20261010/trade-side-trade_sim6-html-20261010.tar.gz`(520,391 B,6 文件)

**实测可恢复**:`tar -tzf` 清单计数 103 / 6;解包到临时目录后**全量 md5 逐位一致(103/103 + 6/6)**(对账文件留存:md5-orig-td/rest-td.txt、md5-orig-tr/rest-tr.txt;示例:`trade_sim_bj50.html 341ce0b08b49cf09975e05cb6ae60d12`、`trade_sim_cac40.html bb89a0f4426f489cb6107fefeeb907be`)✓

**删除结果**:`rm -v`(日志 103 行 + trade 侧 6 显式);两处 glob **零命中**;`trade_sim.html` 本体在位(2,547,478 B,含 symlink)✓

**恢复命令**
```bash
tar -xzf /Users/linhuichen/.claude/backups/cleanup-234-20261010/trade-data-trade_sim-html-20261010.tar.gz -C /Users/linhuichen/code/trade-data/static-site/
tar -xzf /Users/linhuichen/.claude/backups/cleanup-234-20261010/trade-side-trade_sim6-html-20261010.tar.gz -C /Users/linhuichen/code/trade/static-site/
```

### 2.5 stash ×3 —— ⚠️ ref 已不存在;能找回的已导出验证;零 drop

**现状(实测,与任务书预期不同)**
- `git stash list` **空**;`.git/refs/stash` **不存在**;`.git/logs/refs/stash` size=0、mtime **10-10 00:47**(=10-10 gc 窗口,见 10-09 报告 §八)
- ⚠️ 与 §八 gc 声明「**本轮只做对象库回收,不删任何 ref / 分支 / worktree**」**矛盾** ⇒ **上报(§五.2)**

**逐条处置(全部只读,零 git 写操作;顺序按「先导出备份 → 验证 → 才谈 drop」执行)**
- **stash@{2}(09-07 09:08)等价提交 `1cc5339d`** —— 从 fsck dangling 全量筛出(匹配 3 条中唯一同日命中,内容特征吻合)并**导出 patch + 验证**:
  - patch:`stash-2-20260907-agent_inbox_watcher.patch`(7,255 B / 36 行)
  - 验证:base 树 = `60185b511`(`git archive` 解出)→ `git apply --check` **PASS** → 真应用 → 与 `1cc5339d` 内容**逐位一致**(2 文件;唯一 warning = 文件 mode 100644 vs 100755,不影响内容)
  - 内容摘要:① `scripts/agent_inbox_watcher.py` failed 且 retry<MAX 时补 ready 重试(main 已演进为 retry-exhausted 终态,已被取代)② pending #91 标「已完成 2026-09-07」
- **stash@{0}(09-19)候选 6 条**(`3e8678f9/804a9be/9974b7c/963cdedf/e678a36e/f546f4f9`,单文件 accum_nav_map.json=管线产物,无法唯一确定归属)→ **未导出 patch**,候选手册已留档
- **stash@{1}(09-08,7 文件含 README 删两条)** —— **对象未找到**(全量 dangling 扫描 + 09-06~09-11 逐条无匹配;09-08 距今 32 天 > 30 天 prune 窗口,疑 10-10 00:47 gc 销毁)⇒ **上报(§五.3)**。内容摘要(来源 = verify 报告 §一.5):README 删 #101/#91 两条(该删**从未生效**,两条现仍在 main L64/70)、about/guide/privacy 版本串 a554→a555(**早被覆盖**)、kimi plist 删 40 行(main `536d62202` 已完成)、accum_nav_map=管线产物 ⇒ **无实质内容损失**
- **manifest**:`stash-candidates-manifest-20261010.txt`(1,963 B,6 条 stash@{0} 候选 + 1 条已导出,供反查)

**drop 结果**:**未执行任何 `git stash drop`**(无 ref 可 drop;本 agent 全程零 git 写操作)。

### 2.6 中转 scratch 清场(/tmp/p0-b3)—— 已清场

- 峰值 **769M**(p0 gz 副本 104M + R2 取回件 369M + 解包验证副本 205M + base-tree 等)
- 清场前核对:全部为**派生件**,其源均已独立备份并验证(p0 gz ↔ R2 对象(尺寸逐位对账 54,290,591 / 54,289,718)、解包 html ↔ 本备份 tar.gz、base-tree ↔ git commit 60185b511、md5 清单 ↔ 备份目录原件)
- `rm-td.log`(trade_sim 删除证据)已转存 `backup/cleanup-234-20261010/deletion-log-trade_sim-td-20261010.txt`
- 清场后:`/tmp/p0-b3` 不存在 ✓;df 回到 `289Gi used / 141Gi avail`

## 三、§25 合规声明(逐条)

- ① **先备份后删除**:p0(R2 归档 2 key)、trade_sim(本地 tar.gz 2 包)全部「备份完成于删除之前」;scratch 清场的源件均已备份验证 ✓
- ② **备份必须实测可恢复**:R2 走 `restore-r2-backup.sh` **真跑**取回(184,610,816 B ×2)+ md5 逐位一致;tar 走解包 + 全量 md5 逐位一致(103 + 6);本地 gz 尺寸与 R2 对象逐位对账 ✓
- ③ **验过即直接删**(用户 10-10 拍板授权);未出现「验不过仍删」✓
- ④ **恢复路径逐项写明**(§2.1/§2.4 各项末 + 报告恢复命令);
- ⑤ 未动**既有保留决定**:`staticdata-old` 8.3G(保留至 2026-10-30)未碰 ✓
- ⑥ 未删 **任何 git tracked 文件**(`trade_sim.html` 本体保留)、未碰根 `data/` 保护 DB、未碰 docs/配置/脚本 ✓
- ⑦ 异常不静默(§23.11 精神):p0 第三份消失、stash ref 消失与 gc 声明矛盾,均上报不吞 ✓

**硬约束遵守**:全程零真实外发(未触发任何邮件/飞书/告警,未运行通知脚本);零 git 状态写操作;禁 `find /`、禁无白名单 `grep -r`、未裸跑 pip/npm、未 Docker、token 不进 argv、禁 `curl -v/-i` 均遵守;全部命令有界(perl `alarm` 包裹 R2 脚本 / `curl --max-time 20` / Bash timeout)。

## 四、未做项 + 原因

| 项 | 原因 |
|---|---|
| 甲5 日志(≈93M) | **禁删**:被监控脚本按文件名读取 ⇒ 删除=漏跑误报的功能性风险;改造点清单见 §2.2,需先改监控(容忍 .gz 或停机登记)再清 |
| accum_nav(≈54M) | 实测**稳态再生**(每次 deploy 重建)⇒ 收益瞬态,判定不做 |
| stash drop | ref 已不存在(10-10 00:47),无对象可 drop;能找回的(09-07)已导出 patch 并验证 |
| 乙4 gc 后 1,635 loose(156M) | 属 gc「30 天窗口内不可达」保留物(10-10 §八刻意安全取舍),满 30 天后可再 gc;非本轮范围 |
| `/tmp/restore_test` 等他人 scratch | 非本轮范围,不擅动 |

## 五、上报主控(3 件)

1. **p0 第三份下落待核实**:10-09 报告所列 trade 侧「无后缀」副本(= 55926b74 同款重复件)在 10-09 之后、本轮动手(10-10 07:0x)之前消失且无记录 —— 请核实是否主控/其他 agent 前序动作。影响评估:消失者是**重复副本**,两个不同版本实体(55926b74 / e79d3cc8)在本轮动手时均完好、已全部归档 R2、本次已删并有恢复路径 ⇒ **零独有数据损失**。
2. **stash ref 消失与 gc 声明矛盾**:`.git/logs/refs/stash` 归零, mtime = **10-10 00:47**(= gc 窗口),但 10-09 报告 §八声明「不删任何 ref/分支/worktree」—— 事实与声明不符,请核实 10-10 00:47 操作序列(gc/reflog expire 是否连带清掉 `refs/stash` 及其 reflog)。
3. **stash@{1}(09-08)疑被 prune 销毁**:其实体在全量 dangling 扫描中不存在(32 天 > 30 天窗口)。经核内容**无实质损失**(README 删两条从未生效且现仍在 main、版本串早被覆盖、plist 改动 main 已完成)。防再犯建议:stash 若需长留,应 `git stash store` 建显式 ref 或 30 天窗口内导出 patch(本报告即按此口径给 09-07 那条做了 patch 备份)。

## 六、复现命令(核验用)

```bash
# 备份目录终态
ls -la /Users/linhuichen/.claude/backups/cleanup-234-20261010/
# p0:R2 在位(只读 list;期望 KeyCount=8,含 2 个 bak-p0 key)
python3 scripts/upload_r2.py list decommissioned/ signal-backup2
# p0:恢复路径实测(然后 md5 应为 55926b744cca11d69ed32e90e91d6eb1)
bash scripts/restore-r2-backup.sh --out-dir /tmp/verify-p0 etf_national_team.db.bak-p0-20260909.gz
md5 /tmp/verify-p0/etf_national_team.db.bak-p0-20260909
# trade_sim:备份包清单计数(期望 103 / 6)
tar -tzf /Users/linhuichen/.claude/backups/cleanup-234-20261010/trade-data-trade_sim-html-20261010.tar.gz | wc -l
tar -tzf /Users/linhuichen/.claude/backups/cleanup-234-20261010/trade-side-trade_sim6-html-20261010.tar.gz | wc -l
# 零命中复核
ls /Users/linhuichen/code/trade-data/data/*bak-p0* 2>&1 | head -1        # 期望 no matches
ls /Users/linhuichen/code/trade-data/static-site/trade_sim_*.html 2>&1 | head -1
```

> 落档:docs/ops/disk-cleanup-batch3-20261010.md(2026-10-10,**未 commit**,待主控统一收)。
