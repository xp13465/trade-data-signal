# #249 独立审查报告: staticdata_backup_async.sh step3.5b R2 上传守卫(2026-10-11)

> reviewer 独立审查(fresh context, 只读);对象 = feat 分支 `feat/249-step35b-upload-guard`, commit `ff9432175`(base `f2325144a`)。
> 审查口径:全部结论为 reviewer **独立复算/复跑**取证,不采信实施报告自述;引用行号 = worktree 内文件当前行号。
> 残留后台任务声明:无(本次审查全程未出现 `moved to the background (ID:`)。

## 结论

**Verdict = PASS;must-fix = 0 条。**

修法(step3.5b 前置 `staticdata_write_guard.py --check-write-auth`、生产 rc=0 原逻辑不动、非生产 rc=1 默认跳过+降级通知+逃生门、rc=2 fail-closed)与病灶(§6.7)一一对应;原上传逻辑逐字节保留;生产链零变化;测试隔离成立且互补反证真实;举一反三清单经核实无遗漏。1 条 should-fix(防御性,不阻塞 merge)+ 4 条 nit/过滤项见下。

---

## 一、逐项必查结论(7 项)

### Q1 diff 通读/判据复用/原调用段逐字节保留 ✓
- 分支相对 base 仅 3 个文件:脚本 +42/-0、新增测试(214 行)、实施报告;无其它误改(`git diff --stat f2325144a..ff9432175` 独立复核)。
- 原 `with_lock.py --nb ... upload-large-json` 上传段(新 L232-250)**逐字节保留**实证:base 版 L191-209 vs 新版对应段,`diff` 空 + md5 双侧均 `6f141100c7f621691a3a609d4d9bcdd6`;仅被 `if [ "$_R2_SKIP" = "0" ]`(L230)包一层。
- 判据复用:调用同名脚本同 flag 同 rc 契约(`--check-write-auth --repo "$STATICDATA_REPO"`,L203),未新起判据;`_R2_GA_MSG/_R2_GA_RC/_R2_SKIP` 与既有变量无命名冲突。
- `bash -n` PASS;`lint_scripts.sh` 全通过。

### Q2 rc0/1/2 逻辑与生产误判 rc1 现实场景 ✓
- reviewer 实测复算:生产路径 → rc0;mac/tmp 路径 → rc1(直跑真 guard 脚本,与测试①断言一致)。
- 生产误判 rc1 的现实场景不存在:云上 `STATICDATA_REPO` 派生自 `GIT_REPO=/home/ubuntu/code/trade-data-signal` → `/home/ubuntu/…-staticdata`(多份文档实证),判据 `str(path).startswith("/home/ubuntu/")` 与 git 段同源同变量;该判据自 2026-09-26 起已在生产按 rc=0 运行,两条链路路径同值。
- PY 缺失使 rc=127 → 走 else fail-closed;但同一 PY 缺失下 upload 本身也跑不起来(调用同 `$PY`)⇒ 无净损失、无误伤新增。

### Q3 rc2 fail-closed 取舍 ✓(论证成立,误伤推演通过)
- 取舍成立:R2 `large-json/<rel>.gz` 是**固定 key 覆盖写、唯一完整副本、不可逆**(upload_r2.py `cmd_upload_large_json`);异常态 fail-open 会把「mac 覆盖正本」在守卫 crash 时重开。跳过代价极低(磁盘+git 留档在;云上下一轮 ETag 幂等补传,非破坏)。
- 过严误伤推演:生产机若 rc≠0 ⇒ 同脚本 git 段(段2)同样 rc≠0 ⇒ 本来就会置 FAIL/告警,不新增噪音维度;mac 本地 rc=2 时仅本机 latest.md 降级通知,不达云上监控(R4 分级阈值在云上链)。
- 与 git 段 L3 fail-open 的差异已显式文档化(脚本 L191-201 注释 + 实施报告 §1.1),属「同族不同策略显式声明」,非疏漏。

### Q4 测试审查(断言真伪/防假绿/隔离/复跑) ✓
- 新增 5 用例 reviewer 独立复跑:**5 passed in 6.58s**(实施声称 6.60s,一致)。
- 「②非生产机 upload 桩零调用」与「③生产机桩被调用一次」**互为反证成立**:reviewer 用 `--basetemp=/tmp/249-bt` 保留制品核验——生产机形态 upload 桩命中 1 次且心跳为 `{"result":"ok","files":6,"bytes":3847}`(证脚本确实跑到了 step3.5b,②的「空」是真拦不是早退);非生产机形态 upload 空 + notify 桩含 `staticdata_backup_r2_nonprod_skip` + 心跳 `skip_nonprod`;逃生门形态放行且 git 段仍拦;rc=2 形态零上传 + [告警] notify + exit 1。
- 隔离 static-only 事实成立:with_lock/notify/upload 全桩,路径全 tmp;硬编码 /tmp 锁因 with_lock 被桩而未触及;真 guard/large_json_excludes 仅只读判定(stdlib)。**不 exec 生产脚本主体**;无「环境变量齐不齐」式可绕过门控(与 L50 事故形态不同)。
- 相关既有 8 文件集独立复跑:**89 passed, 1 skipped in 21.83s**(计数与声称逐位一致;耗时差异为机器抖动);`test_132_notify_tier_dedup.py` 13 passed;`check_repo_paths_ratchet.py` PASS;CI ⑧ 自动收集新测试,依赖仅 stdlib,不受 mac/CI requests 差异影响。
- **零真实通知外发**(L48):跑前跑后主仓+worktree 的 `data/notify_dedup.json`/`data/alerts/latest.md` mtime 未变;运行窗口内限定目录 find 零新文件;主仓 git status 仍只有原有 3 个 M;worktree status 干净。

### Q5 §23.3 举一反三核实 ✓(三条事实全部独立复核)
- `staticdata_sync.sh` 确无 R2 上传(grep `upload_r2` 零命中)⇒ 无同类缺口,实施清单 #2 属实。
- `migrate_large_json_out_of_git.sh:68` 第二 caller 事实成立(直接调 `upload-large-json`,同 hazard,未改——已披露待拍板,不属本任务范围)。
- `backup_db.sh` 弱同族判断正确:key = `backup/{name}_{YYYYMMDD}.db.gz` 日期化(同日撞才覆盖当日),与 fixed-key large-json 风险量级不同;判定与披露无误。
- 其余 `upload_r2` caller 写公共桶且已被 export-guard L2(`_is_production_writer`)覆盖;#8(git 段 #114 守卫)属实。

### Q6 §15 回归面(生产链零变化/降级通知/零外发) ✓
- 生产链零变化:rc=0 分支只 `:` 注释不做任何事(守卫消息仅在 rc≠0 时被打日志),云上行为与改动前逐字节等价(同判据+原段逐字节保留+云上路径实证);云上 systemd timer 无需改动。
- 新 notify key 语法合法:`staticdata_backup_r2_nonprod_skip` / `staticdata_backup_r2_guard_error` 走通用 send 路径(未知 key 不 suppress 正常发,`check_dedup` 语义),dedup 6h;低危(mac 本地 latest.md,云上无此分支触发路径)。
- 零真实通知外发证据见 Q4(§18 L48 验收点满足)。
- 站点 smoke(docs/smoke-checklist.md)无 staticdata/备份项 ⇒ 不适用,无回归动作可跑。

### Q7 自由发现
见「发现分级」。

---

## 二、发现分级

### must-fix
**0 条。**

### should-fix(1 条, 防御性, 不阻塞 merge)
- **S1 新测试缺 L50 式「正面白名单」运行时护栏**。当前隔离事实成立(全桩+tmp),但护栏依赖 `_mk_env` 的构造正确性;未来若有人改 `_mk_env`(如 GIT_REPO 丢失/指向真仓),隔离可能静默失效(极端情形会走到真 `upload_r2.py`+真桶)。同目录 `test_188_s06_sync_blindspot_pytest.py` 已有「正面白名单三重护栏」先例(L50 精神:只许执行显式声明的文件)。建议后续小改:在 `_mk_env`/`_run` 处断言 REPO/GIT_REPO 均在 tmp_path 之下 + 桩目录核对。**属测试健壮性增量,非本 diff 缺陷**(本 diff 内隔离已验证成立)。

### nit / 过滤项(4 条)
- **N1** mac 场景 rc=2 时心跳标 `skip_nonprod` 而非 `fail`(收口优先级 _SKIP_NONPROD > FAIL):与 #117 M1「心跳 fail 不被 skip_nonprod 语义污染」的意图有边角张力;mac 本地无监控消费,影响为零。置信度 ≥80,收录。
- **N2** header 用法段未登记 `STATICDATA_ALLOW_R2_UPLOAD`(但既存 `STATICDATA_ALLOW_PUSH` 同样未登记于 header,风格一致)⇒ 与现约定一致,不算漂移,提及备查。
- **N3** 生产 rc=0 时守卫消息(`_R2_GA_MSG`)被丢弃不落日志,排障时云上无「守卫放行」痕迹;当前为静默不变量,低危。
- **N4(follow-up 设计输入)** 根因下沉 `upload_r2.py`(实施报告 §四根因候选)时,注意 `upload_r2.py` 既有判据是 `/home/`(`_is_production_writer`),会把 CI runner `/home/runner/...` 视作生产;而 #249 的 `/home/ubuntu/` 更紧。既有事实不属本次 diff,但下沉方案勿照抄 `/home/`。
- 过滤项数量:**0 条**(所有初步候选置信度 ≥80,已归入上述 nit)。

---

## 三、证据附录(独立复算命令/制品)

| # | 证据 | 结果 |
|---|---|---|
| E1 | 逐字节保留: base L191-209 vs 新 L232-250 `diff`+md5 | 空 diff;md5 双侧 `6f141100c7f621691a3a609d4d9bcdd6` |
| E2 | 新增 5 用例复跑 | 5 passed in 6.58s(声称 6.60s ✓) |
| E3 | 相关 8 文件集复跑 | 89 passed, 1 skipped in 21.83s(声称 25.51s, 计数一致) |
| E4 | 制品级反证 `--basetemp=/tmp/249-bt` | 生产机形态 upload 桩×1 + 心跳 ok/files=6/bytes=3847;非生产 upload 空 + skip_nonprod;rc=2 零上传+exit 1 |
| E5 | 判据直测 `--check-write-auth` | /home/ubuntu/...→rc0;/tmp→rc1 |
| E6 | 零真实外发: dedup.json/latest.md mtime + 限定 find + git status | 未变/零新文件/主仓仅原 3 M, worktree 干净 |
| E7 | 机检: lint_scripts / ratchet / test_132 / CI⑧ 收集 | PASS / PASS / 13 passed / 自动收集(依赖仅 stdlib) |
| E8 | §23.3 三事实: sync.sh 无 upload_r2 / migrate L68 caller / backup_db 日期 key | 全部独立核实属实 |
| E9 | 云上路径: STATICDATA_REPO=/home/ubuntu/code/trade-data-signal-staticdata | 多份 docs 实证 → rc=0 |

## 四、merge 后交接提醒(给主控)
1. 本报告 + 实施报告落 feat 分支(报告不 commit 由主控统一处理亦可);merge 用 `scripts/main-merge.sh feat/249-step35b-upload-guard`。
2. merge 后按 §23.12-1 更新 pending-features-index #249 状态列(现「待实施」)。
3. follow-up 登记(建议): 根因下沉 `upload_r2.py`(一次覆盖 async+migrate 双 caller, 判据勿照抄 `/home/`) + `migrate_large_json_out_of_git.sh` 第二 caller 处置,均由用户拍板。
