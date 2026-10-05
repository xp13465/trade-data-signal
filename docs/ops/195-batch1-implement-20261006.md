# #195 批1 实施报告:共享 `resolve_repo` lib + 首个脚本迁移

- 日期:2026-10-06
- 分支:`feat/195-resolve-repo-batch1-20261006`(worktree 隔离;只 push feat,**禁 push main / 禁 force**)
- 方案(唯一设计权威):`docs/ops/195-resolve-repo-plan-20261006.md`(§3/§4.1/§4.6/§5/§6.4/§6.5)
- 进度文件:`/tmp/agent-progress-195-batch1.md`

## 1. 结论

批1 全部交付项落地,**6 条验收点全绿**:lib 单测 PASS=10/0、patrol 自测 8/8、pytest 全量 232 passed(1 skipped)、ratchet R1-R3 RESULT=PASS、`bash -n` 6 文件全过、云上只读回归 env/推导逐字节一致。全程零外发(未跑任何 notify / R2 写 / unit / 业务脚本)。

## 2. 交付物(3 改 + 4 新)

| # | 文件 | 性质 | 说明 |
|---|---|---|---|
| 1 | `scripts/lib/repo_paths.sh` | 新增 | 单点 `resolve_repo`:`env 非空零改写 > $0 双布局推导 > fail-loud(exit 2 + `${TMPDIR:-/tmp}/resolve_repo_fatal.$(id -un).log`)`;只 assign 不 export;绝不 notify |
| 2 | `scripts/tests/test_resolve_repo.sh` | 新增 | §3.7 T1/T2/T3/T3b/T4/T5/T6 单测 |
| 3 | `scripts/tests/test_resolve_repo_pytest.py` | 新增 | §7.2 待拍板#4:把 bash 单测并入 pytest 全量(20 行 wrapper) |
| 4 | `scripts/check_repo_paths_ratchet.py` | 新增 | §4.6 R1/R2/R3 防回潮机检(**只创建,不挂 deploy 链 / 不设 cron**) |
| 5 | `scripts/check_r2_consistency.sh` | 迁移 | §3.5 两行模板;原 `export REPO GIT_REPO` 语义保留(§3.6) |
| 6 | `scripts/cloud_unit_patrol.sh` | 迁移 | 内联 symlink 推导块 → source lib(去重,行为不变);本脚本语境化 `_fatal` 校验保留 |
| 7 | `scripts/cloud_unit_patrol_selftest.sh` | 测试基建 | `mk_sbx` 增拷 lib;T4 断言由「patrol 内联推导」改判「共享 lib 推导」(结论不变) |
| 8 | `scripts/update_all.sh` | #207 订正 | 3 处注释(非逻辑):「云上单仓(REPO==GIT_REPO)→no-op」前提纠正为多仓布局 |

> `update_all.sh` 属 #207 顺手订正:云上 `REPO=/home/ubuntu/code/trade-data` ≠ `GIT_REPO=/home/ubuntu/code/trade-data-signal` ⇒ 那 3 处 rsync **实际会跑**,原注释断言 no-op 与实况相反。**只改注释/文案,零逻辑变更**(见 §6 复现段 F)。

## 3. 逐条验收(命令 + 实测输出)

| 验收点 | 命令 | 实测 |
|---|---|---|
| ① lib 单测 rc=0 | `bash scripts/tests/test_resolve_repo.sh` | `PASS=10 FAIL=0` rc=0 |
| ② 语法 | `bash -n {lib,test_resolve_repo.sh,check_r2_consistency.sh,cloud_unit_patrol.sh,cloud_unit_patrol_selftest.sh,update_all.sh}` | 全 OK |
| ③ patrol 自测 | `bash scripts/cloud_unit_patrol_selftest.sh` | `PASS=8 FAIL=0` rc=0 |
| ④ pytest 全量 | `<venv>/python -m pytest scripts/tests/ -q` | `232 passed, 1 skipped` |
| ④' 定点 | `pytest test_160_* test_196_* test_resolve_repo_pytest.py -q` | `67 passed` |
| ⑤ ratchet | `<venv>/python scripts/check_repo_paths_ratchet.py` | `pattern 命中 56(白名单外 0)` / `MIGRATED 2,PASS 2` / `RESULT=PASS` |
| ⑥ fail-loud 断言 | 由单测 **T4** 断言(非「env 给坏值跑 check_r2」) | `exit=2, 含 .venv/bin/python, 固定日志已写, 未继续执行`;`RESOLVE_REPO_NO_EXIT=1 → rc=0 仅 warn` |
| ⑦ 云上只读回归(§6.5) | 见 §5 | env 版 rc=0 source=env;unset 版 source=derived 且值逐字节一致 |

## 4. 复现段(逐验收点:命令 + 实测 + 修复链)

### A. lib 单测
```bash
bash scripts/tests/test_resolve_repo.sh          # → PASS=10 FAIL=0 ; rc=0
```
覆盖:T1 env 零改写 / T2 case A(symlink)/ T3 & T3b case B(姐妹 trade-data + 回退)/ T4 fail-loud(含逃生阀)/ T5 空值 env / T6 无副作用 + assign-only/export 语义。
**修复链(编造→修正,如实留痕)**:T6 首跑 FAIL(`added=[ADDED=GIT_REPO,PIPESTATUS,REPO,before,...]`)——单一脚本内 before/after `compgen -v` 漂移把 shell 记账变量(`PIPESTATUS`)与赋值本身算进来。改为**两次独立运行逐名 `comm -13`**(`t6.sh` 带/不带 `resolve` 参数)+ 独立 `t6b.sh` 查 assign-only/export,复跑 10/0。

### B. 语法
```bash
bash -n scripts/lib/repo_paths.sh scripts/tests/test_resolve_repo.sh \
        scripts/check_r2_consistency.sh scripts/cloud_unit_patrol.sh \
        scripts/cloud_unit_patrol_selftest.sh scripts/update_all.sh   # → 全 OK
```

### C. patrol 自测(迁移后)
```bash
bash scripts/cloud_unit_patrol_selftest.sh       # → PASS=8 FAIL=0 ; rc=0
```
**修复链**:迁移前预置 `mk_sbx` 增 `cp $HERE/lib/repo_paths.sh`(否则 T4-T7 因沙箱无 lib 必 FAIL);**保留** patrol 自身 `_fatal` 校验(不能把校验全甩给 lib —— lib 对 env 提供值非法**只 warn 不 exit**,而 selftest T1/T2/T3 断言 patrol 语境化文案)。

### D. pytest 全量
```bash
/Users/linhuichen/code/trade-data/.venv/bin/python -m pytest scripts/tests/ -q   # → 232 passed, 1 skipped
```
**修复链**:系统 `python3` 无 pytest;改用 `trade-data/.venv/bin/python`(含 pytest)。既有 231 例不动,新增 1 例(wrapper)⇒ 232。核过 test_160/test_196 均**未**直接断言被迁移的 REPO 行(逐文件读过)。

### E. ratchet
```bash
/Users/linhuichen/code/trade-data/.venv/bin/python scripts/check_repo_paths_ratchet.py   # → RESULT=PASS
```
**判读说明**:R1 按「已知集合 = `MIGRATED` ∪ `PENDING_BASELINE`」判定(非「全仓已迁移」)——批1 时刻仍有 56 个未迁移病灶,若字面读「必须全在 MIGRATED」必 FAIL。R2/R3 精确校验 2 个已迁移文件(各 1 行 source + 1 行 resolve_repo + 0 行 `:/Users/linhuichen` 代码行,注释提及允许)。

### F. #207 注释订正(仅注释)
```bash
grep -n "REPO==GIT_REPO\|REPO!=GIT_REPO\|多仓布局" scripts/update_all.sh
# L116/117、L200/201、L313/314 已改为多仓布局描述;逻辑零变更
bash -n scripts/update_all.sh                     # → OK
```
**修复链**:首改撞重复行(同一句在 L116 & L199 各现一次,Edit 报 2 matches)→ 带下一行上下文消歧;第 3 处改完与上一行重复「三条同族点」→ 删重复行(实测 `git diff --numstat` 6+/4-)。

### G. 尾换行修复(本轮新发现的真 bug)
```bash
python3 -c "..."  # 逐文件判末字节
# 修前:lib / test_resolve_repo.sh / test_resolve_repo_pytest.py / ratchet.py 均无尾换行
```
**现象**:`cat scripts/lib/repo_paths.sh <其它> > x.sh` 会把 lib 末行 `}` 与下一行首字符**粘成一体**(`}#...`),致 bash 报 `syntax error: unexpected end of file` —— 云上 probe 首跑即撞此(非 ssh 问题,是文件本身缺 EOL)。**修法**:4 个新文件各补尾换行(POSIX 文本文件要求),复跑全绿。
**已知遗留(非本任务引入)**:`check_r2_consistency.sh` / `cloud_unit_patrol.sh` / `cloud_unit_patrol_selftest.sh` 三项**上游 HEAD 即无尾换行**(`git show HEAD:<f>` 末字节核过),本批**不动**(避免无谓 diff 噪声),记录备查。

## 5. 云上只读回归(§6.5,全程零业务;01:10 跑,避 23:20)

```bash
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 \
  'readlink /home/ubuntu/code/trade-data/scripts; readlink -f ...; ls -d .../.venv .../trade-data-signal ...staticdata'
ssh ... 'systemctl show trade-r2-consistency.service -p Environment'
ssh ... 'grep -l "^Environment=REPO=" /etc/systemd/system/trade-*.service | wc -l'
```
| 项 | 实测 |
|---|---|
| ①布局 | `trade-data/scripts -> trade-data-signal/scripts`(symlink);`.venv` 在 trade-data;兄弟三件齐 |
| ②unit env | `Environment=GIT_REPO=/home/ubuntu/code/trade-data-signal REPO=/home/ubuntu/code/trade-data`;`41/41` service 带 `Environment=REPO=` |
| ③推导对照(env 版) | `resolve_repo: REPO=/home/ubuntu/code/trade-data (source=env) GIT_REPO=... (source=env)`;rc=0 |
| ③'推导对照(unset 版) | `resolve_repo: REPO=/home/ubuntu/code/trade-data (source=derived) GIT_REPO=/home/ubuntu/code/trade-data-signal (source=derived)`;值**与 env 逐字节一致** |
| ④failed unit | `systemctl --failed | grep -c trade-` = 0(未制造,无需 reset-failed) |

probe 做法:把 lib 全文经 stdin 管道送云上 `env -u REPO -u GIT_REPO bash -s` 执行(**不在云上写任何文件**),仅打印不跑业务;lib 校验三关全过(未 exit 2 ⇒ REPO/GIT_REPO/.venv 三真)。

**判读原则(§6.5 引用)**:①fail-loud 断言**只认单测 T4**(推导路径),不用「env 给坏值跑业务脚本」(env 非法值在 §3.3 语义下只 warn);②end-to-end 验收 = 自然 unit 运行 + journalctl/告警观察,**不手跑业务脚本**;③云上动作只读。

## 6. §23.2 修 bug 三铁律(本次两个"bug":尾换行 + #207 注释)

**同类错误面清单(尾换行)+ 逐项结果**:

| 同族文件 | 判别 | 处理 |
|---|---|---|
| 本批 4 新文件(lib/2×test/ratchet) | 均无 EOL | ✅ 全补 |
| 本批 3 迁移文件(check_r2/patrol/selftest) | 上游 HEAD 即无 EOL | 记录,不动(避免 diff 噪声) |
| 其余 51 个 scripts/*.sh | 不属本批改动面 | 不改(§23.3 清单列出,后续批处理) |

**#207 同类面**:`update_all.sh` 内**所有**「`REPO==GIT_REPO` → no-op」措辞已全量 grep 纠正(3 处),无遗漏。

**根因修复(非逐文件补丁)**:
- 尾换行 = 文件生成环节缺陷 ⇒ 修的是**生成源**(4 文件本体),非「cat 时插 newline」绕过。
- #207 = **注释与实况语义漂移** ⇒ 订正**前提描述本身**(多仓布局),非删注释。

## 7. §23.3 举一反三(同模式文件全清单;本批**只列出不动**)

同一模式(mac 默认值 `(REPO|GIT_REPO|TRADE_DIR|STATICDATA_REPO):-/Users/linhuichen`)代码行命中 **56 个**文件(plan §2 的 57 含本批已迁的 check_r2_consistency.sh)。ratchet `PENDING_BASELINE` 已登记全量;重点与批次归属:

- **批5 同族(第三变量 STATICDATA_REPO)**:`migrate_large_json_out_of_git.sh:17-19` / `staticdata_backup_async.sh:46-48` / `staticdata_sync.sh:30-32`(→ §7.2#1 `resolve_staticdata_repo` 随批5)。
- **高爆半径**(deploy 链上):`deploy.sh:24-25` / `update_all.sh:35-36` / `update_all_serial.sh:16` / `schedule_monitor.sh:50` / `self_heal.sh:19-20` / `s06_snapshot.sh:58-59`。
- **同模板批量派生**:`stage0_{full_manual,manager,nav,overview,risk}.sh`、`pf_score_{daily,weekly}.sh`、`r2_upload_skip_notify.sh` / `turnover_backfill_skip_notify.sh` / `on_skip_notify.sh`。
- 其余按 plan §4 分批;**本批一律不改**(逐文件补丁会把 57→1 的收敛目标做成 57 个补丁)。

## 8. 方案内部张力(如实登记,未私自改口径)

| # | 张力 | 本批处置 |
|---|---|---|
| 1 | §5 行2 主张硬断言 `REPO != GIT_REPO`,但 §3.2 case B 合法回退 `REPO=GIT_REPO`(克隆成 trade-data 名直跑) | **以 §3.2 三条规范校验为准**,**不加** `REPO != GIT_REPO` 硬断言(否则 case B 容错被误杀) |
| 2 | §3.7 出现 `resolve_staticdata_repo` 但 §7.2#1 标「可选/随批5」 | 批1 **不实现**(随批5,消尾巴一次到位) |
| 3 | §6.4 静态断言正则 `^export (REPO|GIT_REPO)=` 与 §3.6 规定的 `export REPO GIT_REPO` 形不匹配 | 迁移后 `n_exp=0` 属**正则可预期**;已由 ratchet R2 的 `source`/`resolve_repo` 双计数替代守护 |
| 4 | §4.6 R1 字面「已迁移集合」与「R1-R3 过」验收冲突 | 用 `MIGRATED ∪ PENDING_BASELINE` 双集合白名单(见 §4-E 判读) |
| 5 | §7.2#2 ratchet 挂载点未定 | **只创建不挂链/不设 cron**,独立手动跑(按倾向「先独立观察一周」) |

## 9. 零外发保证(§18 L48)

- 未跑 `update_all.sh`/`deploy.sh`/任何 unit/任何 `notify.py`/任何 R2 写;
- 跑过的 ssh 全为 `readlink/ls/grep/systemctl show/管道 bash -s(仅打印)`;
- 自测全在 `mktemp` 沙箱 + `env -u` 隔离;patrol selftest 的 notify 用**哨兵桩**(§18 L48),T5/T7 断言 sentinel **不存在**;
- lib 本体**不含**任何 notify/告警调用(设计约束)。

## 10. 返修段(2026-10-06 独立审 FAIL 返修,旧假绿结论保留可反查)

### 10.1 FAIL 内容(独立审 9 PASS / 1 FAIL)

**`scripts/check_repo_paths_ratchet.py` 的 R3 是空转 = 永不触发**(审查者已复现):
`MAC_DEFAULT = re.compile(r":/Users/linhuichen")` **匹配不到全仓主流形态 `:-/Users/linhuichen`**
⇒ 代码行命中恒 0 ⇒ R3 恒 PASS。变异证据:把已迁移文件的 export 行改回
`export REPO="${REPO:-/Users/linhuichen/code/trade-data}"` 仍 `RESULT=PASS`(本该 FAIL)。

> **旧假绿结论留痕(可反查,不删)**:§3 表 ⑤ 当时报的 `RESULT=PASS`、§4-E 的「R3 残留命中 0」均为
> **空转产生的假绿**,本人自验未识破(闸门自验只跑「绿」没跑「红」)。根因 = §18 L49「假样本养绿」
> 同族:**只验闸门能 PASS,没验闸门能 FAIL**。

### 10.2 修法(三件,全做)

**(1) 修 R3 正则 + 实测全仓命中数 > 0**
```python
MAC_DEFAULT = re.compile(r":-?/Users/linhuichen")   # 覆盖 ':-/'(主流) 与 ':/'
```
实测(代码行,注释跳过):`:-?/Users/linhuichen` 命中 **83 行 / 56 文件**(修前旧正则 `:/Users/linhuichen` = **0 行**)。
另加**恒在防空转自检**:每次运行都用标准病灶样本 `REPO="${REPO:-/Users/linhuichen/code/trade-data}"`
反查正则;匹配不到 → 直接 `FAIL(空转)` 并不许 PASS(即「正则自己失效」也不静默)。

**(2) 补「变异测试」把空转钉死(§18 L49:样本真失败才算通过)**
ratchet 内置 `--selftest`:造临时仓根 + 放两份**真实已迁移文件** → ①负对照(未变异)断言 **PASS**
(证自测装置本身非恒 FAIL)②把 `check_r2_consistency.sh` **代码行**的 env 默认值改回写死 mac 路径 →
断言 ratchet **必须 FAIL**。实测输出:
```
  PASS: 负对照(未变异样本)→ RESULT=PASS(装置本身非恒 FAIL)
  PASS: 变异样本(第 57 行代码)→ RESULT=FAIL(闸门真响);[ratchet] MIGRATED 2 个,PASS 1;R3 残留命中=1
[ratchet-selftest] PASS
```
> **注入点自身的坑(二次踩到 L49 变体,如实留痕)**:首版 `--selftest` 用裸
> `txt.replace("export REPO GIT_REPO", …, 1)`——该锚点在文件**头注释**里也出现过一次 ⇒ 变异落在了
> **注释行**上、被 `_code_lines` 跳过 ⇒ 又得到假 PASS(自测 FAIL 暴露)。改为**按整行精确匹配**
> (`ln.strip() == "export REPO GIT_REPO"`)定位代码行后通过。**变异样本必须落在被判定路径上**。
> 该自测同时并入 pytest 全量(`scripts/tests/test_repo_paths_ratchet_pytest.py`,2 例),以后改正则改坏立即可见。

**(3) 顺手修方案文档同源缺陷(批2 不照抄空转)**
`docs/ops/195-resolve-repo-plan-20261006.md` §6.4 批验收机检 `n_mac` 原为同款错正则
`grep -cE ':/Users/linhuichen'` → 已改 `':-?/Users/linhuichen'` + 一行返修注;§4.6 R3 规则文字
同步改为 `:-?/Users/linhuichen` 并标注返修来历。

### 10.3 返修后自测(全绿)

| 项 | 命令 | 实测 |
|---|---|---|
| ratchet 主检 | `python3 scripts/check_repo_paths_ratchet.py` | 命中 56 文件(白名单外 0)/ MIGRATED 2 PASS 2 / R3 残留命中=0 / 正则健康自检 OK / `RESULT=PASS` |
| ratchet 变异自测 | `... --selftest` | 负对照 PASS + 变异第 57 行 → `RESULT=FAIL(R3 残留命中=1)` / `[ratchet-selftest] PASS` |
| lib 单测(回归) | `bash scripts/tests/test_resolve_repo.sh` | `PASS=10 FAIL=0` rc=0 |
| patrol 自测(回归) | `bash scripts/cloud_unit_patrol_selftest.sh` | `PASS=8 FAIL=0` rc=0 |
| pytest 全量 | `<venv>/python -m pytest scripts/tests/ -q` | `234 passed, 1 skipped`(含新 2 例 ratchet) |
| 语法/lint | `bash -n` 6 文件 + pre-commit lint | 全过 |

### 10.4 非阻塞缺口(#208,本批不动,仅确认未引入)

审查者构造「祖先 symlink」反例:能 `rc=0` 静默得 `REPO=仓目录`(非 trade-data)。审查者实测
**两机祖先路径逐级 `ls -ld` 均无 symlink、41/41 unit ExecStart 根 = trade-data + env 在位 ⇒ 无触发路径**;
主控已登记 **#208**(批2 前补单测/双候选回退),**不在本批实施**。本批未引入该问题(推导逻辑未变,
返修只动 ratchet 机检 + 文档)。