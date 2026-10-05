# #195 批3 实施报告 —— 生产主链 9 个脚本迁移到单点 `resolve_repo`

> 日期 2026-10-06(实施 agent,worktree 隔离 `/Users/linhuichen/code/trade/.claude/worktrees/agent-afc4aec9e058059e6`)
> 分支 `feat/195-resolve-repo-batch3-20261006`,base = `origin/main` = **`c784568d7`**(= #195 批2 合并点)
> 方案:`docs/ops/195-resolve-repo-plan-20261006.md` §3.5 / §3.6 / §4.3 / §4.6 / §6.4
> 上游:`docs/ops/195-batch1-implement-20261006.md` / `docs/ops/195-batch2-implement-20261006.md`

## 0. 结论速览

批3 的 9 个「写生产数据 / 推 main / 对外可见」主链脚本全部迁到单点 `resolve_repo`,**自测/自验 9 条全绿**(静态断言 9/9、`bash -n` 9/9、单测 11/11、patrol 8/8、pytest 234 passed/1 skipped、ratchet PASS 46→37 + `--selftest` 变异→FAIL、本机 probe 27/27、云上只读 36/36、lint 全通过、零外发逐位一致)。**全程零真实外发、零生产写、零 unit 启停、云上零写**。

**一条验收点被主控收紧(已记录,§3)**:§4.3 验收点 2 原写「云上手跑 `intraday_snapshot.sh` 之一档 rc=0」被主控否决(手跑即写盘中数据),改用 **resolve-only probe**(§6.5 同法)替代,9/9 覆盖。

⚠️ **诚实缺口**:本批新代码**至今未在生产跑过**(见 §8);云上是「落云前」态,`落云后 md5 == 本批字节` 属**merge 后**步骤(命令见 §7.3)。

## 1. 改动清单(10 文件)

| # | 文件 | 改动 | export before/after |
|---|---|---|---|
| 1 | `scripts/backup_db.sh` | header 3→3 行(REPO/GIT_REPO 赋值 → source+resolve) | 1 / 1 |
| 2 | `scripts/brief_push_wrapper.sh` | header 2→3 行 | 0 / 0 |
| 3 | `scripts/deploy.sh` | header 3→3 行 | 1 / 1 |
| 4 | `scripts/intraday_snapshot.sh` | header 4→5 行 | 2 / 2 |
| 5 | `scripts/kelly_intraday_rerun.sh` | header 3→3 行 | 1 / 1 |
| 6 | `scripts/nextday_plan.sh` | header 2→4 行 | 2 / 2 |
| 7 | `scripts/run_daily_brief.sh` | header 2→2 行 | 0 / 0 |
| 8 | `scripts/s06_snapshot.sh` | header 2→4 行 | 2 / 2 |
| 9 | `scripts/update_all.sh` | header 3→3 行 | 1 / 1 |
| 10 | `scripts/check_repo_paths_ratchet.py` | 9 文件 `PENDING_BASELINE`→`MIGRATED` + 计数注释 | — |

`git diff --stat` = **10 files changed, 34 insertions(+), 28 deletions(-)**。

**export 语义(§3.6 硬约束)逐文件 before/after(口径 `grep -cE '^[[:space:]]*export (REPO|GIT_REPO|TRADE_DIR)'`)—— 9/9 相等,合计 10/10**:

```
backup_db 1/1  brief_push_wrapper 0/0  deploy 1/1  intraday_snapshot 2/2  kelly_intraday_rerun 1/1
nextday_plan 2/2  run_daily_brief 0/0  s06_snapshot 2/2  update_all 1/1
```

- 原 `export REPO="${REPO:-…}"` + `export GIT_REPO=…`(nextday_plan / s06_snapshot)= 2 行 → 迁移后 `export REPO` + `export GIT_REPO` 两行(**保住行数=保住计数口径**)。
- 原 `export REPO GIT_REPO`(backup_db / deploy / kelly_intraday_rerun / update_all)= 1 行 → **原样保留**。
- 原 `export REPO` + `export GIT_REPO` 分列(intraday_snapshot)= 2 行 → 保留两行原注释。
- 原本无 export 的(brief_push_wrapper / run_daily_brief)**不得**变成 export ⇒ 保持 assign-only,**lib 不 export,py 子进程 `os.environ` 可见性逐字节不变**。

### ⚠️ 与方案 §4.3 的口径差异(实测 vs 文档,按「读代码现状」为准)

- 方案 §4.3 写「**export 类 3 个**(s06_snapshot / nextday_plan;另 check 类不含)」——**与代码现状不符**。实测(`grep -nE '^[[:space:]]*export (REPO|GIT_REPO|TRADE_DIR)'`)= **7 个文件带 export**(backup_db / deploy / intraday_snapshot / kelly_intraday_rerun / nextday_plan / s06_snapshot / update_all),2 个不带(brief_push_wrapper / run_daily_brief)。**本批按实测执行**(派单已指示:批2 审查证实该文档口径不可靠,以代码现状为准)。

### 1.1 同模式残留(sensenova 系,非本批范围)

`grep -rl ':-/Users/linhuichen' scripts/*.sh` = **40 文件**,其中 ratchet `PATTERN`(4 变量前缀)命中 **37**;差 3 = `scripts/lib/repo_paths.sh`(仅注释举例)+ `scripts/sensenova-rotate-proxy.sh` / `-kimi.sh`(`SENSENOVA_ENV_FILE:-/Users/...`,**另一变量族**)。三者均已在方案 §2.3「57 之外的同族」边界表声明,**本批不动**(§23.7 不扩范围)。

## 2. 逐文件 header 迁移形态(§3.5 两行模板 + §5-1 兜底版)

```bash
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/repo_paths.sh" || { echo "FATAL: repo_paths.sh missing" >&2; exit 2; }
resolve_repo "${BASH_SOURCE[0]}"
```

- **只动 header**(9 文件 diff 面 = REPO/GIT_REPO 赋值行 → source+resolve 行;export 行原样),**不动其它逻辑、不动被调 python、不动 `docs/`**。
- 各文件原 `GIT_REPO` 行尾注释(如「git 始终在 trade 仓库…」)随该行一并移除;有信息价值的 export 行注释**全部保留**。
- `lib/repo_paths.sh` **未改**(批2 后含 #208 修复:`-L "$_raw_dir"` + 双候选回退),`bash -n` rc=0。

## 3. ⚠️ 对方案 §4.3 验收点 2 的收紧记录(主控决定,如实记录)

- **原文**:「云上回归窗口选非交易时段(避免 09:25-15:35 盘中档):env 版手跑 `intraday_snapshot.sh` 之一档 rc=0;unset 版推导一致」。
- **主控否决理由**:本批 9 个脚本**全部会写生产数据 / 推 main / 对外可见**,`intraday_snapshot` 手跑即写盘中数据 ⇒ 违反「绝不允许任何真实外发/生产写」铁律。
- **替代方案(本批执行)**:`resolve-only probe` —— `source lib` + `resolve_repo <path>` + `echo REPO/GIT_REPO`,**零业务**,9/9 全跑;云上同法(lib 经 **stdin 管道**喂 `bash -s`,不落任何文件)。见 §6.2 / §7。
- **另:§4.3 验收点 3/4 的处置** —— 验收点 3「merge 时点避盘后/盘中」= **主控 `main-merge.sh` 职责**(agent 不 push main);验收点 4「deploy.sh 叠加 §24 版本串/哈希校验」= 本批**未改 deploy.sh 逻辑**(仅 header 两行),既有 deploy 自验链口径不变,**本批未跑 deploy**。

## 4. 自测/自验逐项结果(9 条全绿)

### 4.1 静态断言 9/9(§6.4 修正版 · 逐文件)

```
src=1 res=1 mac=0  backup_db / brief_push_wrapper / deploy / intraday_snapshot / kelly_intraday_rerun
                   nextday_plan / run_daily_brief / s06_snapshot / update_all   → 9/9 PASS
```
- `n_src = grep -c 'lib/repo_paths\.sh'` = 1;`n_res = grep -cE '^resolve_repo '` = 1;`n_mac = grep -cE ':-?/Users/linhuichen'` = **0**。
- diff 面断言(§6.4):`git diff -U0` 的 `+/-` 行**全部**落在白名单模式(source / resolve / export / 原病灶行)内,**无越界改动**(见 §2 打印)。

### 4.2 `bash -n` 9/9 + lib(rc 全 0)

```
backup_db 0 / brief_push_wrapper 0 / deploy 0 / intraday_snapshot 0 / kelly_intraday_rerun 0
nextday_plan 0 / run_daily_brief 0 / s06_snapshot 0 / update_all 0 / lib/repo_paths.sh 0
```

### 4.3 `test_resolve_repo.sh` T1-T7 全过(**11/11**)

```
== 汇总: PASS=11 FAIL=0 ==
```
(含 T2 case A symlink 推导、T3b 容错回退、T4 fail-loud exit 2 + 固定日志、T6 assign-only export 语义、**T7 #208 祖先 symlink 不静默**)

### 4.4 pytest 全量不回归

```
/Users/linhuichen/code/trade/.venv/bin/python -m pytest scripts/tests -q
→ 234 passed, 1 skipped in 7.49s
```
(与批1 §0 报告口径一致:**234 passed / 1 skipped**;batch3 未改任何测试文件,无新增/丢失)

### 4.5 ratchet PASS(命中 46→37)+ `--selftest`

```
BEFORE: [ratchet] 扫描 scripts/**/*.sh:pattern 命中 46 个(白名单外 0) | MIGRATED 12 个,PASS 12 | RESULT=PASS
AFTER : [ratchet] 扫描 scripts/**/*.sh:pattern 命中 37 个(白名单外 0) | MIGRATED 21 个,PASS 21 | RESULT=PASS
        [ratchet] R3 正则健康自检: ':-?/Users/linhuichen' 命中标准样本 OK
--selftest: PASS: 负对照(未变异样本)→ RESULT=PASS  |  PASS: 变异样本(第 57 行代码)→ RESULT=FAIL(闸门真响;R3 残留命中=1)
```
- **46 → 37**(9 个从 `PENDING_BASELINE` 移入 `MIGRATED`);`MIGRATED` 12 → 21。
- ⚠️ ratchet **仍不挂任何链**(方案 §7.2 待拍板#2 未决,本批未改挂链状态)。

### 4.6 云上只读 36/36 —— 见 §7

### 4.7 零外发证据 —— 见 §8

### 4.8 `lint_scripts.sh` 全通过

```
=== lint 全通过 ===   (rc=0;含 scripts/*.sh + *.py)
```
`python3 -m py_compile scripts/check_repo_paths_ratchet.py` → OK。

## 5. 复现段(§23.5 复现段)

> 全部为**一次性验收工具**(零业务 / 只读),按批2 先例**不入仓**(入仓会与 `scripts/tests/` 下已有单测重复)。

```bash
# (A) 静态断言 9/9 + export before/after —— 见 §4.1 表格口径
for f in backup_db brief_push_wrapper deploy intraday_snapshot kelly_intraday_rerun \
         nextday_plan run_daily_brief s06_snapshot update_all; do
  p="scripts/$f.sh"
  echo "$f src=$(grep -c 'lib/repo_paths\.sh' $p) res=$(grep -cE '^resolve_repo ' $p) \
mac=$(grep -cE ':-?/Users/linhuichen' $p) exp=$(grep -cE '^export (REPO|GIT_REPO|TRADE_DIR)(=| )' $p)"
done
# (B) bash -n 9/9
for f in <同上 9 个>; do bash -n "scripts/$f.sh"; done
# (C) 单测 + patrol selftest
bash scripts/tests/test_resolve_repo.sh          # PASS=11 FAIL=0
bash scripts/cloud_unit_patrol_selftest.sh       # PASS=8  FAIL=0
# (D) pytest 全量
/Users/linhuichen/code/trade/.venv/bin/python -m pytest scripts/tests -q   # 234 passed, 1 skipped
# (E) ratchet + 变异自测
python3 scripts/check_repo_paths_ratchet.py              # RESULT=PASS(命中 37 / MIGRATED 21)
python3 scripts/check_repo_paths_ratchet.py --selftest   # [ratchet-selftest] PASS
# (F) 本机 resolve-only probe(/tmp 快照树,27 断言)
bash /tmp/195b3_probe.sh                                  # PASS=27 FAIL=0
# (G) 云上只读 probe(lib 经 stdin 管道,零写)
bash /tmp/195b3_cloud_probe.sh                            # PASS=36 FAIL=0
# (H) 零外发证据(md5+mtime 前后逐位一致)
bash /tmp/195b3_state_snap.sh > /tmp/A.txt; <跑 F/D 电池>; bash /tmp/195b3_state_snap.sh > /tmp/B.txt; diff A.txt B.txt
# (I) lint
bash scripts/lint_scripts.sh
```

## 6. 本机 resolve-only probe 27/27(§4 自测 6)

- 装置:`/tmp/195b3_probe.sh`,在 `/private/tmp/195b3/` 搭 **mac 生产布局**复刻(`gitsrc/scripts` 真目录 + `trade-data/scripts -> gitsrc/scripts` symlink + `trade-data/.venv/bin/python` dummy)。
- 三组断言 **9 文件 × 3 = 27**:
  - **A** 模板 source 行路径可解析 → `lib/repo_paths.sh` 存在(9/9);
  - **B** `unset REPO/GIT_REPO` → 推导值 == 期望 `trade-data | gitsrc`(9/9);
  - **C** env 版 → 值逐字保留零改写(9/9)。
- ⇒ 9 个脚本的模板 source 行在真实布局下**都能定位 lib**,推导值与 env 值一致。
- **注**:首轮 B 组曾 9/9 报 FAIL,根因 = macOS `/tmp -> /private/tmp` 物理路径差异(`pwd -P` 给 `/private/tmp/...`),**非迁移缺陷**;把装置根改为 `/private/tmp/195b3` 后 27/27 PASS。(该现象与单测 T2 用 `mktemp -d && pwd -P` 的处理同源。)

## 7. 云上只读 36/36(§4 自测 7)

### 7.1 云上现状(只读 ssh,零写)

```
readlink /home/ubuntu/code/trade-data/scripts  → /home/ubuntu/code/trade-data-signal/scripts   (symlink ✓)
ls -d …  → trade-data/.venv 在;trade-data-signal(仓) + trade-data-signal-staticdata 都在
ls …/scripts/lib/ → repo_paths.sh 在位(批1 已落云)
云上仓 HEAD = main = c784568d7(与本批 base 同,工作树干净)
```
- 8 个 unit 的 `Environment`(只读 `systemctl show -p Environment`)= **`REPO=/home/ubuntu/code/trade-data`、`GIT_REPO=/home/ubuntu/code/trade-data-signal`**(8/8 一致;deploy.sh 无专属 unit,系链内被调)。

### 7.2 四组断言 9×4 = 36 PASS(§6.5 同法,lib 经 **stdin 管道**喂远端 `bash -s`,不落云)

| 组 | 断言 | 结果 |
|---|---|---|
| ① | `env -u REPO -u GIT_REPO` → `$0` 推导 == unit Environment(逐字节) | 9/9 PASS |
| ② | env 版 → rc=0 且值零改写 | 9/9 PASS |
| ③ | 本批迁移文件 `bash -n /dev/stdin`(**云上 bash 版本**语法校验,不落云) | 9/9 PASS |
| ④ | 云上现存文件 md5 == base blob(证云上**干净停在 base**,merge 后 pull 即得本批字节的前身) | 9/9 PASS |

⇒ 云上 `<REPO>/scripts` 是 symlink,`$0` 推导**自愈跑对**;env 有值时**零改写**(已配 env 的云上机器行为零变化)。

### 7.3 ⚠️ 「落云后 md5 == 本批字节」= merge 后步骤(本批无法完成,如实标注)

- 云上 integration 只到 `c784568d7`,**本批 commit 尚未 merge ⇒ 9 文件新版不在云上**;agent 不 push main(§8 机制 D)⇒ 该断言**只能由主控 merge + 云上同步后执行**。
- 主控 merge 后执行(只读):
```bash
md5sum /home/ubuntu/code/trade-data/scripts/{backup_db,brief_push_wrapper,deploy,intraday_snapshot,kelly_intraday_rerun,nextday_plan,run_daily_brief,s06_snapshot,update_all}.sh
```
- 期望值(本机迁移后 md5,逐位对照):

| 文件 | md5 | blob sha(git) |
|---|---|---|
| backup_db.sh | `ddaf792384cd381c0f8ea0f1c9553626` | `d95c860b18d13bdea7add7f90535bf69d5b965d8` |
| brief_push_wrapper.sh | `feb1996c7e837785f7b40a8d2b642eb8` | `2a78328a3dbf0cf7784dfd0f8d93d3e4e22443b7` |
| deploy.sh | `b5c14d55b5b05526a93b1fb10f1a2ac9` | `b81b414a7158d248d547463f737b27be19907ca1` |
| intraday_snapshot.sh | `4f428f1e1c44467820a352ae593ac795` | `c8544ae8f6473eb59fa57465acb8ce0e87c4530c` |
| kelly_intraday_rerun.sh | `4f365689c8ad1e796777a92a440280ff` | `77d96b6ee7247989dfd66c9160cd6f35ef862f5c` |
| nextday_plan.sh | `9c9e66a9be8d4c2278c705d997d60d9f` | `9c4f4b2f81f1df3634696a57781a07da3157be7e` |
| run_daily_brief.sh | `62ae0ce16c4802ab71149c45bdc3dbb9` | `635d66c8fb7820c0fb002ab59d2f426bc5588cac` |
| s06_snapshot.sh | `8714e569dd8b709b467a140a1f697124` | `ab8e8d03ddf0b58d937dda87bea08acb53ff0f42` |
| update_all.sh | `b3a2824dc2c2e3f5556015b3cd40b0eb` | `131ab5cee04541adf507fc6a24b7da4db4bae4e0` |

- (云上 base md5 供对账:`backup_db 8556eb30…` / `brief_push 2f44ef02…` / `deploy 00f5bd4e…` / `intraday 7032fa48…` / `kelly 7b24d65d…` / `nextday 5f60d2a9…` / `run_daily 31000e9a…` / `s06 d97a29ab…` / `update_all 60ac041f…`)

## 8. 零外发 / 零生产写证据(§4 自测 8)

**硬约束遵守**:全程**未跑任何 unit / 未 `systemctl start|stop|restart` / 未执行这 9 个脚本本体 / 未跑 `update_all.sh`·`deploy.sh`·`intraday_snapshot.sh` / 未发任何 notify·邮件·飞书 / 未做任何 R2 写 / 未 push main**。全部自测 = 静态断言 + `bash -n` + resolve-only probe + pytest(测试自身打桩)。

```
== BEFORE / AFTER 逐位比对(§6 F/D 电池前后各取一次)==
alert_state.json                 mtime=1789246808 md5=6151e5567c949455ce684614485562ac
anomaly_notified.json            mtime=1789130521 md5=87071b33d486524f9d76e512b35deda2
brief_push_state.json            mtime=1789130709 md5=7706673354dab3d47ecebe197b4d1ab7
alerts/latest.md                 mtime=1790748455 md5=334f0ac79790d97a3537c671d17b8a02
alerts/data_gap_alert_state.json mtime=1789137327 md5=2aeae351bf34a1ac7004f09cf8cea963
resolve_repo_fatal.<user>.log    lines=13 md5=39fac7e6f85d3c78780ccaf02c074e00
→ diff A B = 空 ⇒ STATE-UNCHANGED(md5+mtime 前后逐位一致)
```
- `pgrep -fl 'notify.py|brief_push|intraday_snapshot|update_all|deploy.sh'` → **空(rc=1)**:无任何被调进程残留。
- **FATAL 日志行数/ md5 未变** ⇒ 本批自测**未触发任何 fail-loud**、未产生新日志(probe 全走「推导成功」或「env 提供值」通路)。
- 云上侧零写:全部 ssh 命令 = `readlink/ls/systemctl show/list-timers/md5sum/cat/grep/git log/rev-parse` + `bash -s`(**stdin 管道,不落文件**)+ `bash -n /dev/stdin`;**未 start 任何 unit、未 `reset-failed`**(未人为制造 failed)。
- 桩先验:probe / pytest 全程未调用 notify(证据 = 上表状态文件零变化 + FATAL 日志零变化)。

## 9. §23.2 同类错误面清单 / §23.3 举一反三 / §23.4 同模块

### 9.1 §23.2 同类错误面清单(同根因「写死 mac 默认路径」的**全部**模块 + 逐项处置)

| 面 | 数量 | 本批处置 |
|---|---|---|
| **本批 9 文件** | 9 | ✅ 已迁(静态断言 9/9 + probe 9/9 + 云上 9/9) |
| 批1/批2 已迁(MIGRATED) | 12 | 已迁,本批未动(ratchet R2/R3 复核 PASS 21/21) |
| 剩余 `PENDING_BASELINE`(批4 21 + 批5 16) | **37** | ⏳ 未迁,方案 §4.4/§4.5 待派;ratchet R1 已登记防回潮 |
| **非 4 变量前缀同族**(sensenova 系 2 文件 + lib 注释) | 3 | 方案 §2.3 边界已声明,**不动**(§23.7) |
| 硬编码无 env 兜底变体(sync_dev_from_r2 / backup_claude_self / restore-large-json…) | 见 §2.3 | 方案列为「批5 可选」,**本批不动** |
| **python 侧同族**(≥51 个 `.py`,≥12 处 `os.environ.get("REPO", mac默认)`) | ≥51 | **另登记 #206**(方案 §2.3「二阶同族」),**不与 shell 批混做** |
| unit 侧 / `.env` / launchd plist | — | 方案 §7.1 明定**不动**(不是病灶本体) |

### 9.2 §23.3 举一反三:同模式/同数据源/同组件「还被谁用」+ 相关展示位

- **同组件消费者(被谁 source/调用)**:`lib/repo_paths.sh` 现被 **13 个脚本** source(批1 2 + 批2 10 + 批3 9 = 21 个 MIGRATED 中含 lib 自身);本批新增 9 个调用点,ratchet R2 逐文件断言「恰好 1 行 source + 恰好 1 行 resolve」= **21/21 PASS**,无重复/漏接。
- **被调子链(同数据源 → 父脚本 export 继承)**:9 脚本内的 `.sh` 子调用 —— `backup_db→verify_backup.sh`、`intraday_snapshot→check_signals.sh / staticdata_sync.sh`、`deploy→r2_upload_async.sh`、`update_all→deploy.sh / pipeline.sh / check_signals.sh / fund_nav_upload_async.sh / push_schedule_stats.sh / on_skip_notify.sh`。这些子脚本**自身仍带 mac 默认**(多在 `PENDING_BASELINE`,批5 收),但父脚本以 `bash "$REPO/scripts/x.sh"` 调用且**父脚本 export REPO/GIT_REPO 在位**(backup_db/deploy/intraday/kelly/update_all 全部 export)⇒ 子进程 `${REPO:-mac}` 取到**继承值** ⇒ **本批迁移不破坏子链**;deploy.sh 另有显式 `REPO=… GIT_REPO=… bash r2_upload_async.sh` 双保险。⇒ 这正是 §3.6「保持原 export 集合」的原因之一,**逐文件 export 行数相等 = 子链可见性零变化**。
- **相关展示位(§22 一致性)**:本批**不涉前端 / 不涉数据产物 / 不涉 R2 / 不涉 JSON 字段** ⇒ 无 N 展示位同步需求(§22「数据一致性三步」不适用);**未 bump 版本串**(前端零改动)。
- **同模式「默认值」另一处**:`docs/*.md` 内的示例命令若含 mac 路径 —— **不是运行病灶**,不在本族(方案 §2.3 未收)。
- **本机 launchd plist**(`launchd/*.plist` 内 `REPO`/`GIT_REPO` EnvironmentVariables)—— **同供给面但明定不动**(方案 §7.1;且本机 launchd 已废弃,生产在云上 systemd)。**注**:若将来 launchd 复活,plist 侧是「同模式」第二展示位,已识别未处理,**上报留痕**。

### 9.3 §23.4 同模块冲突预防 + 预留位置 + 待办对账

- **scan `docs/pending-features-index.md`**:#195 行(318 行)状态「批2 实施完成→独立审」;**批4/批5 未派**。`git worktree list` 仅本 worktree(分支 `feat/195-resolve-repo-batch3-20261006`)⇒ **无同模块并发任务,无后覆盖前风险**。
- **预留位置**:`ratchet` 的 `MIGRATED` / `PENDING_BASELINE` 是**批级唯一登记点**,本批只在两集合间搬 9 项(46→37)+ 更新计数注释,**不新增结构** ⇒ 批4/批5 按同一模式续搬,零覆盖风险。
- **待办对账**:方案 §4.3 的「export 类 3 个」与代码现状不符(§1 已记);其余假设(9 文件清单 / 两行模板 / ratchet 集合)与当前代码**一致**,可动手。
- 相关未决项:#206(py 侧同族)/ #207(已完成)/ #208(批2 已修)/ #209(`.env` 覆盖,今天无触发路径)——**本批不涉**。

## 10. ⚠️ 生产实跑缺口诚实标注(不造证据)

**今天(2026-10-06,国庆休市)本批 9 脚本的「自然实跑」情况**:

| 脚本 | unit | 计划时点 | 今天是否自然跑 |
|---|---|---|---|
| backup_db.sh | trade-backup-db | **每日 21:00** | ✅ **会跑**(无交易日闸门) |
| brief_push_wrapper.sh | trade-brief-push | **每日 20:45** | ✅ **会跑**(非交易日判断在 py 内,早退) |
| run_daily_brief.sh | trade-daily-brief | **每日 20:40** | ✅ 会触发(是否真跑看 `config/daily_brief.yaml` 的 `schedule_enabled`) |
| intraday_snapshot.sh | trade-intraday-snapshot | 每日 30 档(09:25…20:35) | ⏸ 触发但**交易日闸门跳过**(休市早退) |
| kelly_intraday_rerun.sh | trade-kelly-intraday-rerun | 每日 09:40 | ⏸ 闸门跳过 |
| nextday_plan.sh | trade-nextday-plan | Mon..Fri 22:30 | ⏸ 闸门跳过(今日周二但休市) |
| s06_snapshot.sh | trade-s06-snapshot | Mon..Fri 20:35 | ⏸ 闸门跳过 |
| update_all.sh | trade-update-all | Mon..Sat 17:50 / Sun 22:30 | ⏸ 闸门跳过(需 force) |
| deploy.sh | (无专属 unit) | 链内 17:50 | ⏸ 随 update_all 闸门跳过 |

- **关键澄清(对「实跑与否」的正确理解)**:**即使闸门跳过的脚本,`source lib; resolve_repo` 也在闸门判断**之前**执行** ⇒ 只要 unit 被触发(多数每日都触发),迁移行就被真实执行一次;休市只让**业务段**早退,不影响迁移行的实跑覆盖。
- **但「云上实跑」以 merge 后云上同步为前提** —— 现阶段云上仍是 base(c784568d7),**本批代码尚未在云上跑过**。最早的自然实跑窗口 = **主控 merge + 云上同步之后**的最近一个触发点(示例:若今晚前落地 → `trade-daily-brief 20:40` / `trade-brief-push 20:45` / `trade-backup-db 21:00` 三个无闸门脚本当晚即实跑)。
- **本实施未为造证据跑任何 unit / 任何脚本本体**(§8 硬约束);上表为**时点推断**,非实测。

## 11. 交付四件套(§23.5)

1. **本体**:本报告 + 10 个改动文件(§1)。
2. **生成/复现脚本**:`/tmp/195b3_probe.sh`(本机 resolve-only probe 27 断言)、`/tmp/195b3_cloud_probe.sh`(云上只读 probe 36 断言,lib 经 stdin 管道零写)、`/tmp/195b3_state_snap.sh`(零外发 md5+mtime 快照)、`/tmp/195b3_base_md5.txt`(base md5 对照表)。**均为零业务/只读**;按批2 先例**不入仓**(与 `scripts/tests/` 已有单测重复),复现命令内联 §5。
3. **复现段**:§5(A-I)。
4. **配套 commit**:分支 `feat/195-resolve-repo-batch3-20261006`,base `c784568d7`;commit message 带 `Co-Authored-By: Claude Code <noreply@anthropic.com>`。

## 12. 未决 / 上报项

1. ⚠️ **§4.3 验收点 2 已被主控收紧为 resolve-only probe**(§3 已记录)—— 请主控复核此收紧与「代方案」是否满足原验收意图。
2. ⚠️ **§4.3 验收点 2 的 md5 段(「落云后 md5 逐位一致」)本批无法完成** —— 需 merge + 云上同步后执行(命令 + 期望 md5 见 §7.3)。**请主控在 §0 上线验证时补做**。
3. ⚠️ **方案 §4.3「export 类 3 个」与代码现状不符(实为 7 个)** —— 建议在方案文档订正(本批按实测执行,未改方案文档;§23.7 不擅改上游文档)。
4. **ratchet 仍未挂任何链**(§7.2 待拍板)—— 本批未改挂链状态。
5. 本批**未 bump 版本串**(前端零改动,§24 不适用)。