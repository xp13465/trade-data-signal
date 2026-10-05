# 【独立审查报告】同族小尾巴三件(#200/#199/#202)— feat/silence-family-tails-20261006

- 审查者:reviewer agent(独立上下文);日期 2026-10-06
- 审查对象:分支 `feat/silence-family-tails-20261006`(4 commit;base=`origin/main`=`43b0bae53`)
- **总结论:PASS(具备合并资格),0 FAIL**
- 新发现:P2×1(注释事实性偏差,零行为影响)+ P3 观察若干(见「未覆盖项」);#204/#205 已由主控登记,本次独立证实
- 全程只读:仓内零改动(写仅 /tmp)、未 commit/push/checkout;全程零真实外发(§6)
- 落位说明:受「只读不改仓内文件」硬约束,本报告未写入仓内 `docs/ops/`,现位于 `/tmp/rev-silence/silence-family-tails-review-20261006.md`(主控如需正式落档可直接取用)

---

## 判据 1 — #200(a) 同类错误面穷举复查 → PASS

「update_all.sh 全部失败点独立清单」(分支版行号;提取= `git show <branch>:scripts/update_all.sh | grep -n '||'` + 上下文逐行读):

| 行 | 点 | 独立判定 |
|---|---|---|
| 119-121 | nav_bucket rsync 失败 | **本次修复**(rc 捕获 L120 + echo L121)✓ |
| 201-203 | etf_score_list rsync 失败 | **本次修复** ✓ |
| 240-242 | fund_score rsync 失败(#200 主项) | **本次修复** ✓ |
| 134 | fund-nav 异步上传触发失败(systemd-run) | 异机制(触发动作 vs 上传本身);真上传失败由 `fund_nav_upload_async.sh:41-45` 内部 notify 覆盖 → 判定成立(低分观察④) |
| 164 | check_signals rc≠0 | 自带独立邮件链(信号邮件),异机制 → 成立 |
| 171 | intraday_snapshot 失败 | FRESH_OK 数据时效断言覆盖(SEVERE 判据 L305)→ 成立 |
| 177 / 183 | export_alert / export_alert_analyze 失败 | 异机制(二级预警产物);echo-only 为 pre-existing 设计 → 成立(低分观察④) |
| 205 | upload-etf-score R2 上传失败 | **独立证实**:`upload_r2.py cmd_upload_etf_score`(L1759)无 `_notify_channel_upload_fail` 调用(该函数仅 L1731 offshore-fund / L1753 fund-score 两处)→ 归 #193/#201 R2 家族正确,非 #200 遗漏;主控已登记 **#204** ✓ |
| 217 / 224 / 231 | export_notifications / stage0-daily / compute_all_scores | 二级「不阻塞」产物,pre-existing 设计 → 成立 |
| 244 | upload-fund-score 失败 | `upload_r2.py:1753` 内部 notify 覆盖 ✓ |
| 368 | daily_summary_email 失败 | 紧接 notify(L369-371)✓ |
| 388 / 391 | gen_schedule_stats / push_schedule_stats 失败 | 二级统计兜底,pre-existing → 成立 |
| 108 / 152-154 / 191 / 233 | FUND_NAV_RC / DEPLOY_ALL_RC / SCORE_LIST_RC / FUND_SCORE_RC | 既有聚合族(SEVERE L306-309 / ISSUE 对应行),非本次范围 ✓ |

结论:三条同族点(同机制/同后果/同写法)全修;其余点逐条判定成立,唯一 R2 侧遗漏(upload-etf-score)归 #193/#201 家族且已登记 #204。

## 判据 2 — #200(b) 聚合语义逐字一致 + 无误报 + 判别维度保留 → PASS

- **逐字同款**:SEVERE 3 行(分支版 L313-315:`[ "${X_RSYNC_RC:-0}" -ne 0 ] && SEVERE=1`)+ ISSUE 3 行(L345-347:`名称镜像rsync失败(rc=N,镜像未同步) `)与既有导出失败族(L306-309 / 对应 ISSUE 行)同结构同措辞(「样板抄齐」成立)
- **通道/去重/退出码零变化**:notify 调用(L354)复用 `--severe --dedup-key "update_all_severe:${ISSUE}" --dedup-window 1800`;退出码仍唯一 `exit "$RC_CORE"`(L394),无新增失败退出路径;dedup key 含完整 ISSUE(问题组合变化=新 key 不漏报;同组合 30min 去重防轰炸)
- **误报实测**(独立复现,真 rsync 真 rc;/tmp/rev-silence/t200_repro2.sh):
  - 失败场景:nav rc=12 / list rc=23 / fund rc=23 → SEVERE=1;ISSUE 含三条目;3 行 echo 全出 ✓
  - 成功场景:三变量 unset → SEVERE=0 ✓(成功时 `|| RC=$?` 不执行 → `${..:-0}`=0)
  - REPO==GIT_REPO 场景:unset → SEVERE=0 ✓
- **云上防噪音**(只读实测):27 个历史 update_all 日志(2026-09-15→10-05)「rsync 同步失败」= **0** → 三条 rsync 云上长期成功,上线不引入新告警;nav_bucket 两仓目录在位
- **真故障判别维度保留**(记忆 alert-denoise-keep-fault-discriminator):rsync rc≠0=镜像未同步/发布不全,与「导出失败=产物未刷新」文案可分,dedup key 不同不互相掩盖

## 判据 3 — 防 L49「假样本养绿」专项 → PASS(不构成)

- **harness 源码核真**:`t200_harness.sh` 的 SRC(worktree 内 update_all.sh)md5=`17d5665341d7c92e119ae1b04dbf1500` == 分支 tip 版本 md5;`t200_before.sh` 源 md5=`e346e3353c6834975c63dab59c2a9875` == origin/main 版本 md5 → 抽的是真实生产行(119-121/201-203/240-242/313-315/345-347 + notify L354)
- **独立最小复现(非复用 harness)**:/tmp/rev-silence/t200_repro2.sh,失败构造=删除 GIT_REPO nav_bucket 子目录 + chmod 500 父目录(rsync mkdir 失败)→ 真 rc=12/23 被捕获 → 与 harness 语义一致;且我自己的 harness v1 构造(chmod 目标目录 500)曾被 macOS rsync 2.6.9 的 `-a` 权限重写绕过(假绿)→ 换构造重做 → 说明「样本是否真失败」经独立判定,未采信 harness 自报
- **before 对照**:改前同场景 SEVERE=0 且 ISSUE 无条目(病灶确证);改后=1(修复生效)→ 非假样本养绿

## 判据 4 — #202 行为等价 + 状态键安全 → PASS

- **结构接线**(独立 AST 复跑 /tmp/rev-silence/t202_repro.py,真 adr 常量注入):`_ESCALATE_CHANNELS` 两通道各 4 元组;`patrol[3] is PATROL_DRIFT_ESCALATE_DAYS`、`failed[3] is FAILED_UNITS_ESCALATE_DAYS`(非捏造值);两常量现值同为 3(adr L58/L61)
- **行为等价**:30 组同输入对比(2 通道×5 连续天数×3 间隔),改前(硬传 FAILED_UNITS)vs 改后(各通道自常量)mismatch=**0**
- **分支版快照树 pytest**:`/tmp/rev-silence/snapshot`(git archive 分支版)+ 导入探针(证明 notify/adr 从快照树加载)→ `test_196` **39 passed**(conftest 自动注入 REPO + 第三方库桩 + stubbed_notify fixture)
- **_cfu_key 改名安全**:
  - 全仓 `self|dead` 仅 `schedule_monitor.sh:1531` 一处;读写三点自洽(seen L1553 / alert_state 读 L1554 / 写 L1557 / 恢复循环同变量)
  - 恢复文案 task=`_key.split("|",1)[0]` → 改后显示 `check_failed_units`(达成订正目的)
  - `check_failed_units` 不在 schedule_monitor 任务清单 / gen_schedule_stats 任务清单 → 新键首段不命中 in_progress_tasks,恢复判定无偏差
  - 云上两处 alert_state.json(repo 154 键 / signal 140 键)与本地 93 键均**无任何 patrol/dead 相关旧键** → 「历史键读成新键致计数重置」无现实触发面
- 低分备注(影响 0,不动作):若旧键曾存在,恢复循环对其 in_progress-hold 语义与新键略异(旧首段=真实任务名会被 hold);云上无旧键

## 判据 5 — #199 零逻辑变更 → PASS

- 去注释 diff:唯一差异=`backup_claude_self.sh` L50 echo 行(去掉 `signal-backup/` 前缀只留 key);L8/L23 注释 + 新增 L47 说明行全为注释 → **无任何可执行语义变化**
- 分支版全文 grep `signal-backup` = **0 残留**;`bash -n` 通过
- 信息完整性成立:真实桶名由上一行 `upload_r2.py upload-claude-backup` 输出(`BACKUP_BUCKET` 路由 `signal-backup2` 新账号,定义 upload_r2.py:286/299)→ 单一事实源不再本地复制;取「去桶名」而非改新名的取舍合理(防下轮再漂移)

## 判据 6 — 零真实外发(双方)→ PASS

- 实施侧:harness `$PY` 假桩(只记 argv)+ `pgrep -f scripts/notify.py` 断言 + 未执行 `backup_claude_self.sh`
- 我方:两复现仅纯函数/exec 字面量/真 rsync(不触 notify);pytest 在 /tmp 快照树(stub 层覆盖 send/send_tiered 全部出口);未跑 update_all.sh / backup_claude_self.sh / 任何 unit;云端全程只读(grep/ls)
- 主仓 `git status --porcelain` = 空(审查未产生任何仓内变更)

## 判据 7 — 回归面 / 一致性(§15/§22)→ PASS

- update_all.sh 执行式调用方:`scripts/self_heal.sh:75`(`update_all.sh force`)+ 云上 `trade-update-all.service` + 手动;新代码不新增退出路径 → 调用方感知零变化
- `_ESCALATE_CHANNELS` 消费点:notify.py 内部唯一解包(L2295-2301);dry-run 分支行为不变;全仓 grep 无第三方消费者
- schedule_monitor.sh 键改名影响面 → 判据 4(无历史键、不在任务清单)
- 前端零改动(diff 无 app.js/lab.js/index.html)→ §24 版本串/机制 C 不适用;§21 算法公示不涉(纯运维脚本)
- 分支未 merge 前云上仍跑 main 版;merge 后由 deploy 推送 → 数据产物无变化

## 判据 8 — git 纪律 → PASS

- 4 commit **线性**(父链 7a3d21dcb→43b0bae53、822480c9f→7a3d21dcb、b20e99598→822480c9f、0ca10754a→b20e99598;无 merge commit、无 rebase/force 痕迹)
- `merge-base(origin/main, branch) == origin/main tip == 43b0bae53`(base-fresh)✓
- 变更 5 文件=4 脚本+1 报告(`git diff --stat`:update_all.sh +22 / notify.py +11 / schedule_monitor.sh +6 / backup_claude_self.sh +10 / 报告 173 行)无夹带;未含 data/、无前端、无版本串
- `origin/main` 未污染(43b0bae53);本地 main=8d7000ae5(领先 4 个主控文档 commit,与本分支无文件交集,merge 预期 clean)

## 未覆盖项 / 上报

1. **[P2·新发现]「云上单仓(REPO==GIT_REPO)→no-op」注释与云上实况不符**
   - 证据:云上 `/etc/systemd/system/trade-update-all.service`:`Environment=REPO=/home/ubuntu/code/trade-data` + `Environment=GIT_REPO=/home/ubuntu/code/trade-data-signal`;`.env` 未定义 REPO/GIT_REPO(EnvironmentFile 不覆盖这两键);两目录均为真实目录(非 symlink)→ **云上三条 rsync 实际真跑**
   - 出处:表述 pre-existing(origin/main 已有 2 处,本次 #200 新增注释 update_all.sh:312 复述 + 实施报告 §1 + commit message)
   - 影响:**零行为影响**(rsync 成功→变量不设→`${..:-0}`=0,「不误报」结论仍成立;真失败上报=修复目的本身);纯注释事实性偏差
   - 建议:随 #195 批1(lib 迁移)顺手订正 3 处注释;不改代码,不阻断本 merge
2. **[已登记 #204]** update_all.sh:205 upload-etf-score 仅 echo → 独立证实(见判据 1),归 #193/#201 R2 家族正确
3. **[已登记 #205]** 老桶名文案残留面(4 个 shell:verify_backup.sh L6/68/76/88、restore-r2-backup.sh L2/8/33、restore-large-json.sh L2/5/12/44、staticdata_backup_async.sh L30/32/169/183):独立复核=**文本/注释层**(运行时经 `upload_r2.BACKUP_BUCKET` 路由正确);「逐处判 legacy 语义禁一把梭」处置要求成立
   - **本次扫描补充**:docs 侧同症状另有 3 处(0 处新桶名并存):docs/site-deployment.md(10/0)、docs/backup-restore.md(10/0)、docs/ops/r2-archive-upload-20261004.md(7/0)→ 建议并入 #205 口径一起扫,不阻断本 merge
4. [低分观察,建议不做] fund-nav 异步触发失败(L134)仅 echo(真上传失败有兜底、触发失败罕见);export_alert/analyze(L177/183)echo-only 为 pre-existing 设计
5. [低分备注] #202 旧键 in_progress-hold 语义差异(云上无旧键,影响=0)

## 复现段(全部命令落在 /tmp,仓内零改动)

1. 分支快照:`git archive feat/silence-family-tails-20261006 scripts docs | tar -x -C /tmp/rev-silence/snapshot` + 导入探针 pytest → `39 passed`(证明加载分支版代码)
2. #200 独立复现:`bash /tmp/rev-silence/t200_repro2.sh` → 失败场景 nav rc=12/list rc=23/fund rc=23 → SEVERE=1 + ISSUE 三条目;ok/single → unset/SEVERE=0
3. #202 AST 等价:`python3 /tmp/rev-silence/t202_repro.py` → 4 元组结构 + identity 断言 + 30 组 mismatch=0
4. #199:`git show feat/...:scripts/backup_claude_self.sh | grep -n 'signal-backup'` → 空;`git diff 43b0bae53..feat/... -- scripts/backup_claude_self.sh` → 去注释后仅 echo 行
5. harness 核真:md5 对照(17d5…/e346…)见判据 3
6. 云上只读:unit Environment/`.env`/双目录 ls -ld/27 日志 rsync 失败计数=0/alert_state.json 键数 154/140 无旧键
7. git 纪律:`git merge-base / rev-list --count / log --format='%h %p'`(见判据 8)

---
*报告完。审查者未改动任何仓内文件、未 commit/push;发现问题未自行修复,均列「未覆盖项」供主控决策。*

## 落档补记(主控,2026-10-06)

复现脚本已入仓(§23.5 四件套,原 `/tmp/rev-silence/` 会话结束即失):
- `docs/scripts/rev200_t200_repro_20261006.sh`(← `t200_repro.sh`,harness 核真用)
- `docs/scripts/rev200_t200_repro2_20261006.sh`(← `t200_repro2.sh`,判据 2 的独立最小复现,**committed 证据用这个**)
- `docs/scripts/rev202_t202_repro_20261006.py`(← `t202_repro.py`,判据 4 AST 等价)

跑法同「复现段」第 2/3 条,只把路径换成上表;快照树仍按第 1 条现取(不落仓,太大)。
