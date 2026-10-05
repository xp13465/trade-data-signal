# #191 独立审查报告(云上 systemd unit 直连巡检)—— reviewer agent-fa4fe6312d2e5672

> 审查对象:`feat/191-cloud-unit-patrol-20261005` @ `b94c32eff34495f18c711654f94f80797bf4f090`(远端已 push、未入 main;merge-base = `9b98d12b1` = main HEAD)。
> 审查方式:只读(唯一交互动作 = 任务书授权的 `systemctl start trade-cloud-unit-patrol.service` 一次真跑,因 `ConditionPathExists=no` 实为条件短路,零副作用);ssh 云上独立核验 + 本地/云上双跑;不改任何代码。
> 日期:2026-10-05。测试基准口径:N/A(非回测类改动)。

## 0. 结论

**PASS(不阻塞 merge)**。P0=0,P1=0;**P2=2**(均为「建议登记后续、不阻塞本次」级),P3/低分滤除 6 条(见 §5)。

三源闭合**实证成立**,且证据强于实施者自述:云上 dump 与 191 版仓库快照 **1137 行逐字 diff 为空**(比"逐字段"更强);doc §2(生成源)vs 快照 82 unit rc=0;云上直连生产等价链路实跑 rc=0。负样本检测能力独立复测 PASS。「mock 未碰生产 unit」证据成立。§23.11 无冲突(191 是 main 直接子提交,可 merge)。

## 1. 九项独立复核矩阵(任务书逐条)

| # | 任务点 | 方法 | 证据(独立复取,非照抄) | 结论 |
|---|---|---|---|---|
| 1 | 云上独立核验 | ssh 直查 + 真跑 | `is-enabled=enabled` `is-active=active`;`list-timers` NEXT=`Tue 2026-10-06 08:27:00 CST`;**与邻居不撞**:08 点档仅 `trade-rzhb-backfill` 08:00(差 27min)、心跳 `:26/:41` 实测单轮 1s(20:41:01→20:41:02);`systemctl cat` service/timer 与 doc §2.38/快照逐字一致;真跑 `systemctl start` → `ConditionResult=no` `Result=success` `ExecMainStatus=0` rc=0,rc 全对 | ✅ |
| 2 | ConditionPathExists 跳过盲区(重点挑刺) | 实测 + 读代码 + 查兜底 | 见 §2 F1:跳过确认**无告警**、唯一痕迹=journal 一行「being skipped」(`trade-...service` 全量 journal = 3 条 skip,20:40:13/20:43:55 = 实施者验证、20:48:28 = 本次复核);但「merge 前跳过」为设计内过渡态且 **main-merge.sh 机制 10(push main 后自动 ssh 云上 pull,失败 [!!]+exit 6)** 使窗口≈0;残余路径(脚本被删/回退)仍静默 → 定性见 F1 | ✅ 已给结论 |
| 3 | 三源闭合是否真闭合 | 名单集合 diff + 逐字段 + 逐字 | ①云上 41 timer+41 service=82 名单 vs 191 快照 82 名单 **diff 空**;②本地跑 `--check-snapshot`(云上 dump vs 191 快照)**rc=0,82 unit**;③**原始文本逐字 diff 为空(1137 行)**——强于"逐字段";④抽样人工对 3 个 unit(`update-all.timer`/`r2-consistency.service`/`s06-snapshot.service`)逐字一致;⑤doc §2 vs 快照(7.8 命令)rc=0;⑥`gen_systemd_units.py --check`=82 rc=0。**不是只比条数**:全字段(含 [Unit]/[Timer]/[Service] 全部 key=value)多重集 order-insensitive 比对 | ✅ |
| 4 | 负样本证据真伪 | 云上文件系统核对 + 名单/内容双对 | 备份目录 `/home/ubuntu/backup/191-cloud-unit-patrol/` 存在可读:`units-after.txt` 82 行(名单与云上现况 **diff 全等**)、`timers-after.txt` 59 行(list-timers 输出含 patrol 行);**零字段残留变更**由两条独立证据坐实:①云上现状 vs 191 快照逐字 diff 空 ②main 快照 vs 191 快照 = **纯新增 27 行、0 删除**(仅 patrol service 17 行 + timer 10 行)。云上 mtime 交叉:今日被改 unit 仅 patrol 两件(20:38)+ #160 r2-consistency(14:31)+ s06-snapshot.service(15:10)(后两者内容亦与快照逐字一致,属 #160/#189 云上落地时刻,非 #191 行为)。注:备份目录是「变更后清单」非内容备份——但 #191 只新增无覆盖,「变更前内容」完整保留在 main 版快照里,恢复依据充分 | ✅ |
| 5 | §22 登记点同步 | 全仓 grep + 逐处核 + 跑机检 | `check_doc_staleness.py:326` 40→41:main 真值=40(实测今日该行)→ 191=41 → **与云上实测 41 一致,基线正确**;全仓 grep 同类计数串(`40 个 .timer`/`39 周期`/`80 unit`/`37 个`)**无漏改**——doc §0 表「40 个 .timer + 40 个 .service」= 周期任务(必迁)40 对的正确分区值(非过时);残留 40/39/80 均历史语境(历史链注解/历史报告)正确保留;`r2-deployment.md` 37→41 = 补 #188 计数清单漏点(原文 37 为陈旧值)。改动内容 = **纯计数**(README/PARAMS/data-sources/site-deployment/scripts/README 均为 40→41,r2-deployment 37→41),与事实相符。机检:`check_doc_staleness`(229 文件)PASS、lint_scripts PASS、6 unit 抽样/82 生成 rc=0 | ✅ |
| 6 | §23.11 跨分支冲突 | git 层面核对 | **冲突不存在**:main 该行已含 #188 的 40(已入 main),191 = 40→41 单行改;191 commit 的 parent/merge-base = `9b98d12b1` = main HEAD → **无并行落后,merge 可直进**;远端分支仅 `feat/191` 一支,无其他在跑分支改同行。**merge 顺序建议**:①先 merge 191(过 7.8 后由 main-merge.sh 机制 10 自动 pull 云上 → 巡检即刻生效)②主控再销账 `pending-features-index.md` #191 行(销账改同一行,须基于含 191 的新 main 落笔,避免覆盖)。时机:避开 §14 盘后时点(15:35/16:00/17:50/20:35/22:00;本次审查时点 20:53 → 建议 22:00 后或 23:00 安全窗口)。 | ✅ |
| 7 | §15 回归/影响面 | diff 核 + 语义核 + 消费者核 | **`scripts/main-merge.sh` 零 diff**(改动不含它);7.8 仍以「doc §2 vs 仓库快照」为对象(`--dump 快照 --check-doc`),语义未被混入云上直连;`--check-snapshot` 为**新增**参数,旧行为(gradient 审计/`--check-doc`/`--align-doc`)代码路径未动(diff 只增不减);快照消费方(main-merge 7.8 + 新巡检)口径一致;`check_doc_staleness.py` 改动仅提示文案字符串,无消费逻辑依赖,`scripts/tests` 无断言该文案;无前端/算法/数据产物改动 → §21/§24/§5.1 均 N/A。**7.8 无新增误报源**(它不读云上,云上变化不会让它误报) | ✅ |
| 8 | §25 回滚/恢复实测 | 逐条核 + 恢复路径实跑 | 回滚 4 条命令语法合规、目标文件存在(`/etc/systemd/system/trade-cloud-unit-patrol.{service,timer}` 已在);**恢复路径实证**:`gen_systemd_units.py /tmp/out` 生成 82 unit 含 patrol 两件,**生成结果与云上现状逐字一致**(重装无漂移)。无覆盖型删除→无 .bak 需求(论证成立) | ✅ |
| 9 | 报告四件套(§23.5) | 逐件核 | ①本体 `docs/ops/191-cloud-unit-patrol-20261005.md`(254 行,含 §2 方案取舍/§4 自验/§9 复现/§10 回滚/§11 交接)✅ ②巡检脚本 `scripts/cloud_unit_patrol.sh` + `systemd_timeout_gradient_audit.py --check-snapshot` ✅ ③「## 9. 复现(命令全集)」在 ✅ ④配套 commit = `b94c32eff`(报告与脚本同一 commit,推送链完整)✅。报告正文未写自身 hash → 低分项(§5-c,与 #190 merge 后补填先例一致) | ✅ |

## 2. 正式 findings(≥80 分,均不阻塞 merge)

### F1 [P2] ConditionPathExists 跳过确认「无告警」:监控自身失效的残余盲区(部分被机制 10 兜底,非本次引入)

- **trace**:`diff_range` = `b94c32eff` 新增 `scripts/cloud_unit_patrol.sh` + 云上 unit `ConditionPathExists=/home/ubuntu/code/trade-data/scripts/cloud_unit_patrol.sh`;`linkage` = 不满足(消除「静默盲区」是本任务目标,此为其残余边界,建议主控知情登记);`user_request` = N/A,`origin` = reviewer_own(任务书 #2 点名的挑刺点,本题给出结论)。
- **结论(回答任务书「设计缺陷还是已有兜底」)**:
  1. **跳过=静默确认**:skip 时 `Result=success`、`ExecMainStatus=0`、rc=0,**无 notify、无告警**;唯一痕迹 = journal 一行「Condition check resulted in ... being skipped」+ `ConditionResult=no`(需人工 `systemctl show` 才见)。**一个永久跳过的巡检 = 没有巡检且更糟(有"已部署"假象)**。
  2. **但「merge 前跳过」是设计内过渡态,且窗口被既有机制压到≈0**:`main-merge.sh` 机制 10(2026-09-19 起)在 push main 成功后**自动 ssh 云上 `git pull origin main`**,失败打印醒目 `[!!]` 并 `exit 6`(不静默)。⇒ merge→脚本到位自动完成,无需人工提醒;pull 失败则 fail-loud 在主控眼前。
  3. **残余盲区(真)**:merge 后若云上 `trade-data-signal/scripts/cloud_unit_patrol.sh` 被删(未来清理/回退/误操作),service 转回每日 skip 且**无人知**——巡检死亡无自检。**兜底现状核查**:`schedule_monitor.sh` TASKS、`gen_schedule_stats.py` TASKS、`self_heal.sh` LABELS(8 项)均**不含 patrol**;patrol 不在任何漏跑/心跳监控内。
  4. **定性**:**非本次引入的新病**——同模式先例 `trade-check-monitor-heartbeat`(#P0-1)与 `trade-r2-consistency`(#160)在 main 上同构且已被接受(#191 属家族第 3 例);但 #191 也未加兜底。**建议(不阻塞)**:登记一条后续小项(二选一即可):① schedule_monitor/self_heal 增加「patrol 最近 skip 检测」② patrol 脚本自己写心跳文件 + 既有心跳消费方覆盖。另建议主控 merge 后**首个定点**(10-06 08:27 或首个工作日)人工核一次 `systemctl show trade-cloud-unit-patrol.service -p ConditionResult` = `yes`(报告 §11 已自列 P3 观察项,方向一致)。
- **verifier**:`command` = 云上 `systemctl start trade-cloud-unit-patrol.service; systemctl show trade-cloud-unit-patrol.service -p ConditionResult -p Result -p ExecMainStatus; journalctl -u trade-cloud-unit-patrol.service --no-pager | tail -3`;`expected` = 脚本在位时 `ConditionResult=yes` 且 rc 取决审计;`observed` = 当前 `ConditionResult=no / Result=success / ExecMainStatus=0`,journal 仅一条「being skipped」,**零告警**。
- **置信度:90**(直接实测)。

### F2 [P2] patrol 告警无「连续 N 天升级」档,与融合先例 r2-consistency 不对称(建议登记/待拍板)

- **trace**:`diff_range` = `b94c32eff` 包装脚本 notify 调用(`--severe --dedup-key cloud_unit_patrol_drift --dedup-window 21600`);`linkage` = 不满足;`origin` = reviewer_own。
- **事实**:同族先例 `check_r2_consistency.sh`(本巡检明示的照抄对象)有配套升级机制 **R7①**(`scripts/alert_denoise_rules.py:341 r7_r2_consistency_escalate`,#160 用户拍板:连续 2 天 FAIL 由 severe 升 critical、独立 dedup key 必达);**patrol 无对应条目**(`grep cloud_unit_patrol alert_denoise_rules.py` 空)。漂移若持续数日(云上有人改了 unit 又不修),每天仅一封 6h-dedup 内的 severe,无升级穿透 —— 与 R7 出台时的动机(「连续失败被当噪音忽略」)同构。
- **判断**:不阻塞(severe 本身已邮件+飞书 alert 群,单天也必达;且「持续漂移」= 人工事件,人被通知到的概率高)。**建议**:用户拍板是否给 patrol 加 R7 同款升级;若不加,主控在 §0 观察一次即可。
- **verifier**:`command` = `grep -n "cloud_unit_patrol" scripts/alert_denoise_rules.py`;`expected` = 若有意对齐先例应有三处登记(升级阈值/key/判据);`observed` = 0 命中。
- **置信度:80**。

## 3. 其余逐项确认(任务书要求核、确无问题)

- **「82 = 41+41 与 doc §2 的 82 逐 unit 逐字段对齐」**:成立且强于要求——①名单集合全等 ②字段级 rc=0 ③原始文本逐字 diff 空(1137 行)④3 unit 人工抽。
- **patrol 脚本「只报警不改生产」**:读码确认无任何 `systemctl`/写文件到生产路径/git push 动作;唯一写 = `$REPO/data/logs/cloud_unit_patrol_launchd.log`(日志);notify 带 `--dry-run` 桩位(P 生产不设)。回滚四件命令语法/文件核过(§1-#8)。
- **对老功能影响面**:`cloud_unit_patrol` 全仓引用面 8 文件(均在本次 diff 内);`systemd-units-cloud-snapshot.txt` 消费者(main-merge 7.8 / 新巡检 / `--check-doc`)三口径一致;无其他运行链路引用。新增 timer 不进入任何「任务面板」数据链路(schedule_stats TASKS 显式表,patrol 不在其中 → 前端无变化)。
- **时点(#14)**:08:27 在盘前闲时;邻居实测:08:00 rzhb(差 27min;rzhb 写 DB/patrol 只读 unit,即使并行亦无资源共享)、心跳 08:26/08:41 实测单轮 1s。`Persistent=true` + 每日(含周末)与 doc §2.38 一致。
- **§23.2/§23.3/§23.13**:非 bug 修复(是补盲区);同模式面穷举见报告 §6-§7(云上全部手动 unit 均被覆盖、快照消费方三方核对、同类窗口另有 check_r2_consistency/check_universe_alignment 已有直连巡检不重复);无档位/阈值语义改动,三源锚点 N/A。

## 4. 独立复测档案(本次新建,可复跑)

1. **云上真 unit dump vs 191 快照逐字**:`ssh ... 'cd /etc/systemd/system; for f in trade-*.service trade-*.timer; do echo "@@@FILE:$f"; cat "$f"; done' > dump.txt` → `diff dump.txt docs/deploy/systemd-units-cloud-snapshot.txt` = **空**(1137 行)。
2. **逐字段**:`python3 scripts/systemd_timeout_gradient_audit.py --dump dump.txt --check-snapshot --snapshot docs/deploy/systemd-units-cloud-snapshot.txt` → `✓ 82 unit` rc=0。
3. **负样本(独立注入)**:改 `trade-update-all.service` 的 `TimeoutStartSec=0→9999` → rc=1,输出 `trade-update-all.service | TimeoutStartSec | ['9999'] | ['0']`;包装层 stub 复测 rc=1、notify 参数齐(`--severe --from-prefix [告警] --dedup-key cloud_unit_patrol_drift --dedup-window 21600 --dry-run`);快照缺失 → rc=2 同样告警;一致 → rc=0 静默。notify CLI 参数真实性:`notify.py:2134/2136` 有 `--dedup-key/--dedup-window` 定义(PASS,非静默 argparse 崩)。
4. **云上生产等价真跑**:191 版脚本 scp 至云上 `/tmp/review191-cr`(隔离目录)→ 直连 `/etc/systemd/system` 真 unit 跑包装 → `rc=0` + 日志「一致(82 unit)」。
5. **机检链**:7.8 命令 rc=0 / `gen_systemd_units.py --check`=82 rc=0 / `check_doc_staleness.py`=PASS(229 文件)/ `lint_scripts.sh`=全通过 / `bash -n` OK / 生成器重跑 `gen_systemd_units.py /tmp/out` 的 patrol 两件与云上**逐字一致**。

## 5. 低分项(<80,已滤,防黑箱列出明细)

- a) [75] 报告 §8 未提 `main-merge.sh` 机制 10(2026-09-19 起 push main 后**自动** ssh 云上 pull,失败 exit 6):报告写「请提醒云上执行 git pull」略冗余(机制 10 已自动;失败会 fail-loud)。不构成风险,建议顺手订正一句。
- b) [75] `--check-doc` 与 `--check-snapshot` **同时传参**时,`main()` 先命中 check_doc 分支 return,`--check-snapshot` 被**静默忽略**(无互斥断言)。当前无任何调用方这么用(7.8 只传 --check-doc、patrol 只传 --check-snapshot),修法一行(互斥/组合提示),建议随下次顺手。
- c) [70] 报告正文未含自身配套 commit hash(`b94c32eff`);与 #190 先例一致(merge 后补填),可选项。
- d) [50] wrapper 在 `PY` 缺失时 rc=127 也走「漂移」告警分支且 notify 同用该 PY(措辞误+链断);前提 `.venv` 缺失会使 40+ 任务同挂,概率极低;与先例同构。
- e) [25] `scripts/cloud_unit_patrol.sh` 文件尾无换行符(git 提示 `\ No newline at end of file`);lint 通过、零功能影响。
- f) [25] site-deployment/r2-deployment 沿用的「41 个 `.timer`/`.service`」句式(41 为 timer 数;加 service 为 82)措辞含糊——沿用原文句式,与 README「41 个 `.timer` 单元」口径一致,不算不一致。

## 6. 给主控的 merge 备忘(§0 用)

1. **merge 顺序**:本分支直进(merge-base = main HEAD,`git merge-tree` 预期无冲突;过 7.8 后机制 10 自动 pull 云上 → patrol 立即在位,无需人工提醒云上)。
2. **时机**:避开盘后时点(审查时 20:53,建议 22:00 后或 23:00 安全窗口;main-merge.sh 内置 §14 检查会自动拦截)。
3. **merge 后 §0 首验点**:①线上无需验(无前端/数据产物);②云上核一项:`10-06 08:27` 首跑后 `systemctl show trade-cloud-unit-patrol.service -p ConditionResult -p ExecMainStatus` = `yes/0`(或首跑前核 `ls .../scripts/cloud_unit_patrol.sh` 已 pull 到位)。③销账 pending-index #191 行(在 merge 后基于新 main 改)。

## 7. 复现命令(审查层,可复跑)

```bash
# 分支
git fetch origin && git show origin/feat/191-cloud-unit-patrol-20261005 --stat

# 本地(worktree 隔离)
git worktree add /tmp/wt-191 origin/feat/191-cloud-unit-patrol-20261005 --detach && cd /tmp/wt-191
python3 scripts/systemd_timeout_gradient_audit.py --dump docs/deploy/systemd-units-cloud-snapshot.txt --check-doc   # rc=0,82
python3 scripts/gen_systemd_units.py --check        # 82, rc=0
python3 scripts/check_doc_staleness.py              # PASS(229 文件)
bash scripts/lint_scripts.sh                        # 全通过
bash -n scripts/cloud_unit_patrol.sh

# 云上(只读 + 任务书授权的一次条件短路 start)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173
  systemctl is-enabled trade-cloud-unit-patrol.timer; systemctl is-active trade-cloud-unit-patrol.timer
  systemctl list-timers --all | grep patrol
  systemctl cat trade-cloud-unit-patrol.service trade-cloud-unit-patrol.timer
  systemctl show trade-cloud-unit-patrol.service -p ConditionResult -p Result -p ExecMainStatus
  # 真 unit dump → 拉回本地与快照逐字 diff / 逐字段 --check-snapshot
  cd /etc/systemd/system && for f in trade-*.service trade-*.timer; do echo "@@@FILE:$f"; cat "$f"; done > /tmp/dump-191.txt
```

## 8. §22 一致性/机检/私钥安全声明

- 全程只读(除任务书授权的 1 次 `systemctl start`——`ConditionPathExists=no` 条件短路,ExecStart 未执行,零副作用);未改任何云上文件、未 push main、未动 data/。
- curl/ssh 未使用 `-v/-i`;私钥路径 `~/tdsignal.pem` 未打印内容(L22)。
- 报告落档 = 本文件;分支 `review-191-20261005`(从 origin/main 开,只含本报告)。
