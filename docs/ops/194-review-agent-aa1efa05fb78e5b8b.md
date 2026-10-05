# #194 独立审查报告(云上巡检脚本 `cloud_unit_patrol.sh` 加固:fail-fast + 去 mac 硬编码)—— reviewer agent-aa1efa05fb78e5b8b

> 审查对象:`feat/194-cloud-patrol-hardening-20261005` @ `8a74e779bbce3a92d5ecb454e01992026cd875b8`(base = `origin/main 50090c642`,已 push、未入 main;分支仅此 1 commit)。
> 改动:`scripts/cloud_unit_patrol.sh`(+54/−4)+ `scripts/cloud_unit_patrol_selftest.sh`(新,93 行)。md5:新脚本 `de593ab5e91db56ad920c781be11cd0a` / 自测 `3da2b82bc3a1709007fe4a237cd3fca3` / main 版 `e51a270ddb662ed476e77ed3b841ae57`。
> 审查方式:**只读**。云上真跑采用 `unshare -m` + `mount --bind` 把新脚本临时挂到**真实生产路径**执行(namespace 内生效、生产文件零改动,附 namespace 内外 md5 双证);唯一生产写动作 = 生产日志「备份→跑→按字节复原」,复原已 md5 双向验证。**本人造成一次真实假告警,已 §0.2 完整自报**。
> 日期:2026-10-05。测试基准口径:N/A(非回测类改动)。

## 0. 结论

**PASS(不阻塞 merge)**。P0 = 0,P1 = 0,**P2 = 4**(均为「登记后续/清理项」级,不阻塞),低分滤除 3 条(§3)。

### 0.1 头条风险「加固会不会变成新的每日误报源」——实测证伪 ✅

云上**生产同构**实测(生产 env + 真实生产路径 + 真配 `/etc/systemd/system`,`bind-mount` 替换出新脚本后 namespace 内 md5 = `de593…` = 新脚本,确保跑的是新代码):

| 场景 | 命令形态 | 实测 |
|---|---|---|
| A 带生产 env(unit 同款) | `REPO=/home/ubuntu/code/trade-data GIT_REPO=/home/ubuntu/code/trade-data-signal bash /home/ubuntu/code/trade-data/scripts/cloud_unit_patrol.sh` | **rc=0**,日志新增行 = `✓ 云上 unit 与仓库快照一致(82 unit,逐字段全量比对通过)`——**与基线(生产日志 21:00:37 那条)逐字一致** |
| B 不带 env(纯 `$0` 推导,经生产 symlink 路径) | 同上但 `env -u REPO -u GIT_REPO -u PY`,`bash -x` 全量留痕 | **rc=0**;trace 实测派生子:**`REPO=/home/ubuntu/code/trade-data`** / **`GIT_REPO=/home/ubuntu/code/trade-data-signal`** / `PY=$REPO/.venv/bin/python` / `cd /home/ubuntu/code/trade-data` / `SNAPSHOT=/home/ubuntu/code/trade-data-signal/docs/deploy/systemd-units-cloud-snapshot.txt`——**四项全对** |

路径链实证:云上 `trade-data/scripts` → symlink → `trade-data-signal/scripts`;`dirname(未解)`→ trade-data、`cd+pwd -P(解 symlink)后 dirname`→ trade-data-signal(推导两条腿各自命中,非"碰巧")。
fail-fast 四项前置校验在**当前生产真值下全部通过**(逐项实测):`REPO` 目录在 ✓、`GIT_REPO` 目录在 ✓、`trade-data/.venv/bin/python`(-f 跟随 symlink 链 `.venv→trade-data-signal/.venv`、`python→python3.11`)**-f/-x 均 OK** ✓、`LOGDIR` 已存在 ✓。**另核 `EnvironmentFile=trade-data/.env` 不含 `REPO/GIT_REPO/PY/TMPDIR` 任何键**(键名全表已列,0 命中)→ 不存在"`.env` 反向覆盖 unit env 把新校验打坏"的路径。**结论:新校验在生产零触发风险;不会成为新误报源。**

### 0.2 ⚠️ 事故自报:我(审查者本人)触发一次真实假告警 —— 请主控速转告用户

- **发生了什么**:我做自测脚本「变异测试」(拿 main 版旧脚本跑同一套 selftest)时,旧脚本**没有 `$0` 推导、写死 mac 路径,且不理会沙箱 env** → 它直接用了真实 mac `REPO/GIT_REPO` 跑真实 audit → mac 无 `/etc/systemd/system` → `未读到任何 trade-*.service / trade-*.timer` rc=2 → **notify 真发**:邮件 `234058394@qq.com` + 飞书 `oc_7d8d3eb6…`,标题「[告警] 云上 systemd unit 与仓库快照漂移」= **假告警**(我未设 `CLOUD_UNIT_PATROL_NOTIFY_DRYRUN=1`,是我的操作错误)。
- **落地残留(我造成的,处置建议见 F2/F3/§5)**:①`/Users/linhuichen/code/trade-data/data/logs/cloud_unit_patrol_launchd.log` 本次**新建**(968B,全部是我的失败块)②`trade-data/data/alerts/latest.md` 尾部新增 `[severe] 2026-10-05 21:24:34` 假条目(**行 356–361**,文件共 361 行;精确回退=删 356–361)③`trade-data/data/notify_dedup.json` `cloud_unit_patrol_drift.last_alerted=2026-10-05 21:24:34`(6h 去重窗 → 03:24 过期,**不影响**次日 08:27 巡检;其余 26 键未动)。
- **反向证据价值**:同一沙箱条件下新脚本(有 `$0` 推导)全程留在沙箱、零外溢——**#194 的修法方向被这次事故反向验证为有效**(旧脚本"跑个副本就打到生产"的病,新脚本已治)。
- **不静默**:本条即是上报(§23.11);正文与进度文件 `/tmp/agent-progress-review194.md` 双落。

### 0.3 md5 / 复原三方核(§25/§23.11 关键项)——全部干净 ✅

| # | 核对项 | 实测 |
|---|---|---|
| ① | 仓库(分支)脚本 == 云上实测版本 | `de593ab5e91db56ad920c781be11cd0a` 三处一致(本地 `git show` / 云上实测拷贝 / bind-mount 生效后 namespace 内) |
| ② | 云上生产文件**现在** == main 版 | `md5sum /home/ubuntu/code/trade-data-signal/scripts/cloud_unit_patrol.sh` = **`e51a270ddb662ed476e77ed3b841ae57`** == `git show 50090c642:scripts/cloud_unit_patrol.sh` 逐位同 |
| ③ | `.bak` / 临时件清理 | 实施者的 `cloud_unit_patrol.sh.bak-20261005` **已删**(scripts/ 目录与全盘 find `*patrol*` 均无);`scripts/` 目录近期只有 patrol 一件被改;云上 git 仓 `git status` = 干净(唯一 untracked `scripts/sysaudit_tmp.py` 属**另一任务**(s06-timeout-grad,15:19),非本次) |
| ④ | 生产日志复原 | 我跑前备份/跑后 `cp -p` 回滚,**md5 双向一致**=`f86f414ce0b4ab3516a54280cf658966`,内容 = 仅 21:00:37 基线 3 行(实施者此前同样做过日志复原,我做之前它就是干净基线态) |
| ⑤ | 生产 unit/timer 未被动 | `systemctl cat trade-cloud-unit-patrol.service` 读数与 doc §2.38 / 快照逐字一致(实施者是只读方,无 systemd 写动作) |

### 0.4 改动范围核(防「偷偷动别的」):✅ 只有 2 文件

`git diff --stat origin/main...feat/194-…` = **仅** `scripts/cloud_unit_patrol.sh` + `scripts/cloud_unit_patrol_selftest.sh`;`docs/deploy/`(含 `systemd-units-20260912.md` §2 与 `systemd-units-cloud-snapshot.txt`)、`/etc/systemd/system/*`、`main-merge.sh` 7.8 闸门**零改动** → **不会撞 #189 merge 7.8 一致性闸门**(P0 风险排除)。

## 1. 任务书七项逐条复核矩阵

| # | 任务点 | 独立证据(非照抄实施者) | 结论 |
|---|---|---|---|
| 1 | 头条:误报源 | §0.1 表(A rc=0+逐字一致 / B 四项派生值逐条实测) | ✅ 不会误报 |
| 2 | fail-fast 正确性 + 两出口 + systemd `failed` | C1 `REPO=/nonexistent/xyz`→rc=**2** + stderr 含实际取值与「Environment=REPO= 可能丢失」提示 + 固定日志同步落行;C2 `GIT_REPO=/nonexistent` →rc=2 同构;C4 `TMPDIR=/nonexistent-tmpdir`(出口②写失败)→ **仍 rc=2 + stderr 有话**(bash 打印 redirect 失败行 + FATAL 行,`\|\| true` 兜住不崩)。**systemd 环境独立复现**:`systemd-run --unit=r194failtest --wait --setenv=REPO=/nonexistent/xyz …` → unit `Active: failed (Result: exit-code)`、`status=2/INVALIDARGUMENT`、journal 有完整 FATAL 行(已 `reset-failed` 清理)。`TMPDIR` 实证:unit 同款(带 `User=ubuntu` 的 transient 探针)`TMPDIR=[UNSET]` → `${TMPDIR:-/tmp}` = `/tmp` ✓;unit **无** `PrivateTmp/ProtectSystem`,/tmp 可写 ✓ | ✅ |
| 3 | md5/复原三方核 | 见 §0.3 五项全绿;另:实施者"云上实测 de593 == 本地逐位一致"**独立复现成立** | ✅ |
| 4 | 有没有偷偷动别的 | §0.4;unit/doc/快照零改动 | ✅ |
| 5 | 回归 | `bash -n` 两文件 OK;`bash scripts/cloud_unit_patrol_selftest.sh` **独立复跑 PASS=5 FAIL=0 rc=0**;worktree `lint_scripts.sh`(**含全角吞变量名机检**)对两新文件 `OK` = **lint 全通过**;**假绿排查=变异测试**(见下) | ✅ |
| 6 | §23.3「~50 脚本同款写死」真伪 | 点名 5 个(`check_r2_consistency.sh:52-53`/`update_all.sh:35-36`/`s06_snapshot.sh:55-56`/`nextday_plan.sh:30-31`/`overfit_monitor.sh:25-26`)**逐个属实**;精确总数=**全仓 57 个 .sh 同款 `(REPO\|GIT_REPO):-/Users/linhuichen`**(`scripts/` 内 65 个含 `/Users/linhuichen`、全仓 66);其中 **36 个正被云上 unit 以 `ExecStart` 调用** = 同一「靠 unit env 兜底」家族。**建议(不开任务,登记候选)**:抽共享 `resolve_repo` 单点守卫值得做——但注意 36 个中多数是 `Type=oneshot` 生产任务,改动面大,建议**单独立项**(先在 `pending-features-index.md` 登记),不要顺手改 | ✅ 属实 |
| 7 | §23.5 报告落档 | **未落**——分支仅 2 个脚本文件,无 `docs/ops/194-*.md`;worktree 干净无未提交;`pending-features-index.md` 亦无 #194 行(见 F4) | ⚠️ 指出 |

**假绿专项(任务书点 5)**:我对自测脚本做**两个变异**验证其判别力——①把被测脚本换回 main 旧版 → `PASS=2 FAIL=3`(T1/T2/T4 全抓到;rc=1)②只把派生腿打坏(`_gitrepo_derived="$_repo_derived"`)→ `PASS=4 FAIL=1`(T4 精确抓 "snapshot 路径错")。**结论:自测不是假绿**——它断言的是**内容**(stderr 文案 + 固定日志内容 + 日志落位 + snapshot 路径),不只看 rc。

## 2. 正式 findings(≥80 分,均不阻塞 merge)

### F1 [P2] fail-fast 路径**不发告警**,且全站无「failed-unit 巡检」→ 「巡检死亡」仍是静默的(残余盲区,非本次引入)

- **trace**:`diff_range` = `8a74e779b` 新增 `_fatal()`(L70-76)与四处校验(L79-87);`linkage` = 不满足(本任务目标是"失败也有出口",此为其**边界**);`user_request` = 任务书点 2「失败出口是否真能用」,`origin` = reviewer_own。
- **事实**:`_fatal` 的出口只有 ①stderr→journal ②`/tmp` 固定日志,**没有 notify**;且全仓/云上仓 grep `systemctl --failed\|--state=failed\|is-failed` = **0 命中**,`schedule_monitor.sh`/`self_heal.sh`/`gen_schedule_stats.py` 也不含 patrol(与 #191 审查 P2-1 同源残留)。即:**合并后若 unit env 丢失,巡检会 loud 地失败(rc=2 + journal 一行),但没人在看 journal** → 巡检停摆无人知(与旧版"静默失败"相比只是"失败更可读",未解决"没人被通知")。
- **判断**:不阻塞本次(这是全 patrol 功能的既有设计边界,本次改动**提升了**失败可读性:旧版 rc=127 只有 bash 噪声)。**建议(登记后续,二选一)**:①把 patrol 纳入 `schedule_monitor`/`self_heal` 的 unit 清单 ②补一条"`systemctl --failed` 非空即告警"的通用巡检(对 36 个 oneshot 全家收益)。
- **verifier**:`command` = `grep -rn "systemctl --failed\|--state=failed\|is-failed" scripts/ app/`(本地+云上仓各跑);`expected` = 若已有兜底应有命中;`observed` = **0 命中**;另 `grep -n cloud_unit_patrol scripts/schedule_monitor.sh scripts/self_heal.sh scripts/gen_schedule_stats.py` = 0。
- **over_engineering**:`action` = none(无删除/简化建议;7 级阶梯复核:该缺口属"缺功能"非"多代码")。
- **置信度:88**。

### F2 [P2/pre-existing] 非云上环境跑该脚本 = **真发 severe 假告警**(新旧版同病;我本人实测触发,见 §0.2)

- **trace**:`diff_range` = 旧版 L36-37(main)/新版派生分支(L63-67)——**两者同病**:在 mac(或任何无 `/etc/systemd/system` 的机器)从仓库根跑 `bash scripts/cloud_unit_patrol.sh`,audit 必然 `未读到任何 trade-*.service` → rc=2 → **notify 真发**(`--severe`,无 dry-run 保护);`linkage` = 不满足/边界;`user_request` = 任务书点「误报源」反向面,`origin` = reviewer_own(实测事故触发)。
- **事实**:旧版 = 硬编码 mac 默认 → 直接打到真实 mac 路径(我的事故);新版 = `$0` 推导,在 mac 上派生 `REPO=GIT_REPO=/Users/linhuichen/code/trade`(实测 dirname 原语复算 + repo `.venv/bin/python` 存在 → **fail-fast 不拦**,一路跑到 notify)→ **同样真发**。差异只在"从 /tmp 副本跑"时:旧版仍打到真实 mac(事故根因),新版留在沙箱(已修)。
- **判断**:非本次引入(§23.7⑤ 上报通道),不阻塞。**建议(登记)**:加一道环境守卫——如 audit 侧把「未读到任何 unit」判为"环境不适用(rc=0 + 明确文案)"而非"漂移",或在包装层检测非 Linux/systemd 时 `exit 0` 静默并备注;顺带把 mac 手动跑改为强制 `CLOUD_UNIT_PATROL_NOTIFY_DRYRUN=1`。
- **verifier**:`command` = mac 上 `bash scripts/cloud_unit_patrol.sh`(无 env,无 dry-run);`expected` = 若安全应不发送;`observed` = `[notify] 邮件已发送至 234058394@qq.com` + 飞书已发送 + `alerts/latest.md` 落一条 `[severe] … 漂移`(2026-10-05 21:24:34)。
- **over_engineering**:`action` = simplify(P2 落地时);`saves_lines` ≈ 0(加守卫约 +3 行,但消除一类假告警)。
- **置信度:100**(实测触发)。

### F3 [P2] 云上残留:root 所属 `/tmp/cloud_unit_patrol_fatal.log` 会让「出口②」在 ubuntu 身份下失效(且是实施者测试残留)

- **trace**:`diff_range` = L69/L74(`_FATAL_LOG` + `\|\| true`);`linkage` = 满足(任务书点 2 明确问"两个出口是否都真能用");`origin` = reviewer_own。
- **事实**:该文件由实施者 `systemd-run`(root)测试创建于 21:15:33(root:root 0644,314B;我 D2 复现测试又追加 1 行 → 现 567B,**此 1 行为我所致,已披露**)。ubuntu(生产 unit 的 User)身份写它 = **Permission denied**(bash 在 stderr 打一行,`\|\| true` 吞掉)→ **出口②实测降级不可用**(出口① journal 仍完整)。属"失败出口的隐性降级",且是**未清理的测试残留**(§23.11)。
- **判断**:不阻塞(仅在"先有 root 跑过"这一罕见前提下降低冗余度;而 stderr/bash 报错仍留 journal 痕迹)。**建议**:`sudo rm /tmp/cloud_unit_patrol_fatal.log`(内容我已全文留档于本报告 §0.2/本节,删前可另存),此后首条真实失败会由 ubuntu 自建、可写、可增量。
- **verifier**:`command` = `sudo ls -la /tmp/cloud_unit_patrol_fatal.log` + `env REPO=/nonexistent/xyz bash scripts/cloud_unit_patrol.sh`;`expected` = 两出口均可写;`observed` = 文件属 `root root`;ubuntu 跑 → `rc=2` 但 stderr 多一行 `/tmp/cloud_unit_patrol_fatal.log: Permission denied`(挺:exit code 与非静默 stderr 都还在)。
- **over_engineering**:`action` = delete(残留文件);`saves_lines` = N/A;`rationale` = 命中"7 级阶梯之 YAGNI/清理"——测试残留不该留生产机。
- **置信度:95**。

### F4 [P2] §23.5 报告未落 + `pending-features-index.md` 未登记 #194

- **trace**:`diff_range` = `8a74e779b`(仅 2 脚本);`linkage` = 不满足;`user_request` = 任务书点 7,`origin` = reviewer_own。
- **事实**:①`docs/ops/194-*.md` 不存在(分支/ worktree / main 全无)②`pending-features-index.md` 无 `\| 194 \|` 行(193/194 均缺)③云上 `/tmp/r194test/`(我的审查产物)与我本机 `/tmp/r194/` 亦属临时件(见 §5)。对 B 级改动,§23.5「四件套」的报告本体缺位——不阻塞 runtime 正确性,但违背"新产物当场落档"。
- **判断**:**merge 前建议补齐**(可极简:一段改动说明 + 复现命令 + 回滚 = 两行 git),由主控裁定;若接受简式补档,可直接引用本报告 §4「复现命令全集」作为复现段。
- **置信度:95**。

## 3. 滤除项(<80 分,另 3 条,如实列出防黑箱)

1. **[50] `[ -f "$REPO/.venv/bin/python" ]` 在「`PY` 显式指向别处 + `REPO` 无 .venv」时会误杀**:逻辑属实,但该组合在生产不存在(unit 不设 `PY`,`.env` 无 `PY` 键),属过度严格的设计取义(它的本意是"REPO 是否指错目录"),不改。
2. **[50] mac 手动跑派生出 `REPO=trade`(git 仓)而非 `trade-data`(运行目录)**:与旧版默认值语义不同;但 mac 是纯开发机(`local-dev-cloud-prod-split`),且 repo `data/.gitignore` 为 `*`(实测 `git check-ignore` 命中)→ 无仓库污染风险,纯语境差异。
3. **[35] 风格 nitpick**:`cloud_unit_patrol_selftest.sh` 文件**尾缺换行**(`tail -c1` = `]`,非 `\n`);lint 不拦、bash 无影响。

## 4. 复现(命令全集,均为本次独立复跑过的)

1. **本地**:`git show origin/feat/194-…:scripts/cloud_unit_patrol.sh | md5 -q` → `de593ab5e91db56ad920c781be11cd0a`;`bash -n` 两文件;`bash scripts/cloud_unit_patrol_selftest.sh` → `PASS=5 FAIL=0`;worktree 内 `bash scripts/lint_scripts.sh` → 全通过。
2. **变异测试(判别力)**:把 selftest 与「main 版脚本」同目录跑 → `PASS=2 FAIL=3`;把派生腿改 `_gitrepo_derived="$_repo_derived"` → `PASS=4 FAIL=1`(注:此变异务必加 `CLOUD_UNIT_PATROL_NOTIFY_DRYRUN=1` —— 我漏加,导致 §0.2 事故)。
3. **云上·生产同构真跑(bind-mount,零改生产)**:
   ```
   sudo unshare -m bash -c '
     mount --bind /tmp/r194test/cloud_unit_patrol.sh /home/ubuntu/code/trade-data-signal/scripts/cloud_unit_patrol.sh
     md5sum /home/ubuntu/code/trade-data/scripts/cloud_unit_patrol.sh          # 应=de593…(证明跑的是新码)
     sudo -u ubuntu env REPO=/home/ubuntu/code/trade-data GIT_REPO=/home/ubuntu/code/trade-data-signal \
        bash /home/ubuntu/code/trade-data/scripts/cloud_unit_patrol.sh; echo rc=$?          # A:应 rc=0
     sudo -u ubuntu env -u REPO -u GIT_REPO -u PY bash -x \
        /home/ubuntu/code/trade-data/scripts/cloud_unit_patrol.sh 2>/tmp/r194test/trace_B.txt # B:看派生
   '
   grep "REPO=\|GIT_REPO=\|SNAPSHOT=" /tmp/r194test/trace_B.txt
   md5sum /home/ubuntu/code/trade-data-signal/scripts/cloud_unit_patrol.sh   # namespace 外仍=e51a…(生产未动)
   ```
4. **systemd 侧独立复现**:`sudo systemd-run --unit=r194failtest --wait --setenv=REPO=/nonexistent/xyz --setenv=GIT_REPO=… /bin/bash /tmp/r194test/cloud_unit_patrol.sh` → `systemctl status` = `failed (Result: exit-code)` / `status=2` / journal 含 FATAL;`sudo systemctl reset-failed r194failtest`。`TMPDIR` 探针:`sudo systemd-run --unit=r194envprobe2 --wait --pipe -p User=ubuntu … bash -c 'echo ${TMPDIR:-UNSET}'` → `UNSET`。
5. **复原验证**:生产日志 `cp -p` 回滚后 `md5sum` = `f86f414ce0b4ab3516a54280cf658966`(备份同值);生产脚本 `old==new md5` 双向;`mount | grep patrol` = 0。

## 5. 残留清单(全量,含非本次)

| 位置 | 内容 | 归属 | 建议 |
|---|---|---|---|
| 云上 `/tmp/cloud_unit_patrol_fatal.log` | root:root 567B(=实施者 21:15 一行 + 我 21:23 一行) | **本次**(见 F3) | `sudo rm`(删前可另存) |
| 云上 `/tmp/r194test/` | 我的审查产物(脚本副本/driver/trace/log.bak/f1-f3.log) | **我(本次审查)** | 可随时 `rm -rf`(log.bak 是生产日志备份,复原已验) |
| 云上 `/tmp/review191-patrol.sh`、`/tmp/review191-cr/` | #191 审查残留 | #191 审查 | 可清 |
| 云上 `/home/ubuntu/backup/191-cloud-unit-patrol/` | #191 证据(units-after/timers-after) | #191 | 建议保留(证据) |
| 云上 `trade-data-signal/scripts/sysaudit_tmp.py`(untracked) | 另一任务(s06-timeout-grad,15:19)产物 | 非本次 | 上报给该任务收口 |
| 本机 `/tmp/r194/` | 我的审查产物 | 我 | 可清 |
| 本机 `trade-data/data/logs/cloud_unit_patrol_launchd.log` | 我事故新建(968B) | **我**(§0.2) | 建议删或保留作事故留痕(主控定) |
| 本机 `trade-data/data/alerts/latest.md` 行 356–361 | 我事故的假 severe 条目 | **我**(§0.2) | 建议删 356–361 行恢复 |

## 6. 其余确认(§21/§22/§24/§5.1 等适用性)

- **§21 算法公示**:不适用(无算法/评分/权重改动)。
- **§22 一致性**:该脚本产物仅日志与告警;`README.md:458` 对 patrol 的描述未涉及本次改动点,无双写点位不一致风险;§22 三处同值对象(static-site/R2/CF)零触碰。
- **§24 前端防撕裂**:不适用(无前端/版本串)。
- **§5.1 防前视 / §5.4 基准**:不适用(非回测)。
- **§14 生产稳定性**:改动不改 unit/时点,08:27 巡检时点不变;`Env` 语义、`ExecStart` 不变 → 不引入撞车风险。
- **§23.4/§23.5 团队协作**:分支 base = main 最新(50090c642),与在跑分支无文件重叠;预留位检查 N/A(无展示位/常量位);索引登记缺位见 F4。
- **§23.11 绝不静默**:全审查中未发现任何"静默吞冲突/覆盖/倒退";反而我自己制造了一次"未加 dry-run 的真告警",已按本条公开上报。

## 7. 结论汇总

**PASS(可 merge,建议按序:①主控裁定 F4 补档方式 ②merge 后云上 pull 自动生效 ③清理 §5 残留项 ④登记 F1/F2 后续)。** P0=0,P1=0,P2=4(F1 巡检死亡静默 / F2 非云上环境假告警(含我的事故) / F3 root 残留阻塞出口② / F4 报告与索引缺位)。
