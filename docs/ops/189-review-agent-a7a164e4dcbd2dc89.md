# #189 独立审查报告(生成源超时值对齐 + merge 7.8 闸门)

- **审查者**:reviewer agent `agent-a7a164e4dcbd2dc89`(独立复核,不采信实施方自证;本报告所有数字均为 reviewer 独立复跑产出)
- **审查对象**:分支 `feat/systemd-units-doc-sync-20261005` @ tip `70444c4c8`;base main `85790a6ce`
- 分支构成 = 2 commit(`41be6e592` 主改动 + `70444c4c8` 报告订正),5 文件 `+1550 / -33`(doc 主文件 66 行变更 / 快照新增 1110 行 / 报告新增 234 行 / main-merge +17 / 审计脚本 +156-1)
- **审查分支**:`review-189-a7a164e4dcbd2dc89`(本报告所在)
- **日期**:2026-10-05
- **结论**:**PASS**(P0=0,P1=0;P2=1,P3=6,均不阻断 merge)
- 附注:审查期间 `origin/main` 前进 1 个 docs commit(`85790a6ce` -> `7c3f7714e`),与本改动无关,不影响判定

**一句话结论**:8 个怀疑点逐项独立复核全过——云上第三源三方比对(快照 vs 云上逐行全等 0 差异;doc 生成物 vs 云上仅 2 行既有注释差)、闸门 fail-closed 且注入实测非空转、举一反三全字段穷举属实(80 unit 逐字段仅 TimeoutStartSec 漂移)、30 处变动全部对齐云上真值、计数改前=改后自洽、全仓 grep 无第三处陈旧值。唯一 P2 = 闸门设计边界「doc==快照 != 快照==云上当前」(实施报告已诚实标注,但配套巡检建议未登记待办,建议 merge 时补登记)。

## 0 八个怀疑点判定总表

| # | 怀疑点 | 判定 | 最强证据(一行) |
|---|---|---|---|
| 1 | 自证循环(ssh 云上取第三源) | PASS | diff 云上 dump vs 仓库快照 -> 0 行差异(1110 行逐行全等);见 1 节 |
| 2 | 闸门安全性(三 memory + 主仓实跑 + fail-open) | PASS | 主仓目录实跑 PASS;fail-closed 五连实测;无自锁;只读 2 个显式文件、无目录遍历;见 2 节 |
| 3 | 举一反三真穷举 | PASS | gen-dump vs 云上 dump 全 1110 行字节级 diff -> 仅 2 行注释差,其余字段 0 差异;见 4 节 |
| 4 | 3 处 doc<云上 逐条方向 | PASS | kelly-intraday-rerun 200->600 / public-fund-estimation 120->600 / brief-push 300->600,云上均 600(往真值);见 1(c) |
| 5 | 闸门非空转(注入实测) | PASS | 快照侧注入 -> [600] vs [10800] exit=1;文档侧注入 -> [9999] vs [600] exit=1;base doc -> 30 处 exit=1;还原 -> exit=0;见 3 节 |
| 6 | 23.7 冻结契约 + 计数自洽 | PASS | git diff 仅 5 文件无顺手改;计数四组改前=改后;见 5 节 |
| 7 | 23.5 报告四件套 | PASS | 报告+脚本+## 复现段+commit 41be6e592(5 文件全 tracked);复现段实跑可复现;见 7 节 |
| 8 | 22 全仓第三处旧值 | PASS | schedule_monitor.sh:162/166=960=云上;无第三处陈旧现值;见 6 节 |

## 1 三方比对(自证循环破除,怀疑点 1/4)

**第三源(云上 live)**:ssh 到云上(122.51.111.173)直取 /etc/systemd/system/trade-*.{service,timer}(云上手管文件,git pull 不更新),dump 到 /tmp/189-cloud/cloud-dump.txt(80 unit / 1110 行)。

**(a) 仓库快照 vs 云上 = 逐行全等**

    diff /tmp/189-cloud/cloud-dump.txt <worktree>/docs/deploy/systemd-units-cloud-snapshot.txt
    -> (无输出,0 差异)

仓库快照真实反映云上当前实值,快照本身可信。

**(b) doc 第 2 节生成物 vs 云上 = 仅 2 行注释差**

    diff /tmp/189-cloud/gen-dump.txt /tmp/189-cloud/cloud-dump.txt
    -> 552,553d551
    < # 外层 960 > 内层 run_to 900(留梯度,防 systemd SIGKILL 打断 wrapper 的「结束」日志行
    < #   -> schedule_monitor 漏跑检查误判 runaway;memory watchdog-inner-timeout-no-gradient)

为 trade-r2-consistency.service 的两行注释,base 版 doc 已有(=#160 遗留),**非本次 diff 引入**;闸门按设计只比字段键值行(unit_field_map 只认 ^key=),注释/空行/段落头不在比对范围——不触发 FAIL,且回装到云上也不改变任何行为。

**(c) 40 service 全量三方复核(base doc / 新 doc / 云上)**

逐 unit 独立重算(不引用实施报告数字),统计输出:

    TimeoutStartSec 变动: 30 | now>base(旧 doc 更严、修复=放宽): 3 | now<base(旧 doc 更宽、修复=收紧): 27 | 总 service: 40
    MISMATCH(now!=cloud): 0

30 处变动**全部满足「新 doc == 云上」**;其余 10 service 三值本就一致;全程 0 个 MISMATCH。

关键三行(旧 doc 比云上更严格,重跑生成器会把云上收紧——任务点名的 3 处):

| unit | base doc | 新 doc | 云上 |
|---|---|---|---|
| trade-kelly-intraday-rerun.service | 200 | 600 | 600 |
| trade-public-fund-estimation.service | 120 | 600 | 600 |
| trade-brief-push.service | 300 | 600 | 600 |

反向 27 处(旧 doc 比云上更宽松,重跑会把云上放宽)典型:trade-update-all 10800->0、trade-etf-national-team 7200->0、trade-self-heal 10800->600、trade-public-fund-daily 1800->900——全部对齐云上。云上超时分布(0 秒 x21 / 600 x16 / 3300 x1 / 900 x1 / 960 x1 = 40)与 #36 收口历史自洽。

## 2 闸门安全性(怀疑点 2)

闸门实现 = scripts/main-merge.sh 7.8 节(L359-374),插在 7.6 后、7.7 前(merge 后、push main 前);DRY_RUN=1 时跳过,与 7/7.5/7.6/7.7 同款式;check 失败即 exit 1 阻断 push main。

**三条 memory 逐条核**:

1. gate-position-blast-radius(位置决定爆炸半径):位置在 merge 之后、push main 之前 -> FAIL 即阻断 push main,不产生线上影响;失败仅留「本地 main 半完成态」(既知/接受模式,重跑 main-merge.sh 即恢复,与既有 7.x 同性质)。DRY_RUN 跳过避免本地试跑误拦。编号 7.8 排在 7.7 前(快速本地检查先于联网哨兵)仅 cosmetic,报告已说明。
2. gate-verify-in-prod-tree-not-clean-worktree(必须在生产目录验证):**主仓目录实跑通过**——在 /Users/linhuichen/code/trade 原目录实跑同一命令 -> PASS;干净树(git archive 70444c4c8 -> /tmp/189-tree)实跑同样 PASS。该闸门只读 2 个**显式文件路径**(--dump 指定的快照 + G.default_md_path() 的 doc),check-doc 路径上无任何目录遍历/glob(read_all_units -> parse_dump(args.dump) 直接 open;glob 只在 --units-dir 分支)-> 结构上不存在 7.6 类「扫进 .claude/worktrees 副本」隐患。
3. gate-self-blocking-staged-deletion(守卫自锁):闸门判据 = 读两文件**内容**比对,不读「待提交变更集」-> 无「守卫把将提交的删除判为违规」死锁;删快照场景最多多 FAIL 一次(提示补快照),符合已档「第一次 FAIL 正常」模式。

**fail-open 检查(五连实测,全部 fail-closed)**:

| 场景 | 行为 |
|---|---|
| 注入错值(快照侧) | exit=1(精确到 unit+字段+双侧值) |
| 注入错值(文档侧) | exit=1 |
| dump 文件缺失 | Python traceback,**exit=1**(非零=仍阻断;输出不友好见 P3-2) |
| dump 为空(/dev/null) | 友好报错「未读到任何 trade-*.service / trade-*.timer」,exit=2 |
| dump 只含子集(15 unit) | 「仅 doc 79 unit」,exit=1 |

无任何「读不到/读错 -> 静默 exit 0」路径。

## 3 非空转 + 边界实测(怀疑点 5)

在审查分支(tip 70444c4c8)实跑:

1. **快照侧注入**(副本 trade-self-heal.service 一节 600->10800)->
   trade-self-heal.service  TimeoutStartSec  doc=['600']  authoritative=['10800'],RC=1。
2. **文档侧注入**(doc 副本 600->9999)-> doc=['9999'] / auth=['600'],RC=1。
3. **旧版 doc 回归**(git show 85790a6ce:docs/deploy/systemd-units-20260912.md)->
   「不一致:差异字段 30 处」(30 行全部为 TimeoutStartSec 字段,如 trade-update-all ['10800'] vs ['0']),RC=1。
4. **正向还原**(真文件原样)-> 「生成源(doc 第 2 节)与权威 unit 源一致(80 unit,逐字段全量比对通过)」,RC=0。

「能拦住错误、正确态放行」双向成立,非空转。

## 4 全字段穷举复核(怀疑点 3)

方法(比实施报告口径更强):gen_systemd_units 从新 doc 第 2 节生成的 dump(/tmp/189-cloud/gen-dump.txt)vs 云上 dump 全 1110 行**逐行字节级 diff** -> 仅 1(b) 的 2 行注释差,其余**连非 key= 行都比**且全等。

字段分布(快照 15 类,reviewer 独立计数):Environment 160 / OnCalendar 82 / Description 80 / WorkingDirectory/WantedBy/User/Type/TimeoutStartSec/Persistent/ExecStart 各 40 / EnvironmentFile 39 / StandardOutput/StandardError 各 33 / ConditionPathExists 2 / KillMode 1。

抽验非 TimeoutStartSec >=3 类(Environment / OnCalendar / Description)0 差异 -> 「仅 TimeoutStartSec 漂移、其余字段 0 差异」属实且更强。

## 5 冻结契约 + 计数自洽(怀疑点 6)

**diff 逐文件通读**:仅 5 文件,无顺手改/超范围改动。doc 非 TimeoutStartSec 变更 = 第 2 节头口径说明 2 行 + 2.1/2.13 prose 2 行(过滤 TimeoutStartSec 后仅剩 1 行 markdown > 引用符,全部为配套说明文字)。快照 1110 行为纯数据固化,无明文密钥(secret/token/key grep=0;Environment 全为路径类)。云上无本次期间的新写入(云上最新 mtime 为既有 s06 15:10 / r2-consistency 14:31)-> 「本次未改云上」成立。

**计数自洽(改前=改后,防 22 口径打架)**:报告第 5 节四组数逐项复核——0 节周期任务 39(改前=39)+ 1 backup_db = 40;1.4 节 = 6+2+32=40;1.7 节 = 40;第 2 节标题「39 个周期任务完整对照表」= 39(改前=39)。reviewer 独立计数:doc 标题 80(40 service + 40 timer)/ doc ini 块解析 80(40+40)/ 云上 dump 80(40+40),三方一致;40 service 全在原位无删减;--check-doc 正向 PASS。

## 6 全仓 grep 复核(怀疑点 8)

全仓核 TimeoutStartSec 相关值有无第三处陈旧现值:

- scripts/schedule_monitor.sh:162/166 = 960,**等于云上**(r2-consistency)-> 无需动。
- scripts/with_lock.py / gen_schedule_stats.py 中出现的是**语义说明**文字(非 unit 超时现值)。
- docs/ops/160-*.md 960 = 云上;alertchain 文档 check-monitor-heartbeat 600 对。
- docs/deploy/timeout-caliber-20260916.md:带日期的历史快照(public-fund-daily 表内 600 系 9-16 史值;云上 9-21 已改 900)-> 属历史记录非现值;新 doc/快照/报告均 900,不构成不一致。
- **无第三处陈旧现值**。

## 7 报告四件套(怀疑点 7)

- 报告本体:docs/ops/189-systemd-units-timeout-doc-sync-20261005.md(tracked)对。
- 生成/校验脚本:scripts/systemd_timeout_gradient_audit.py 的 --dump/--check-doc/--align-doc(本次 +156/-1);生成源本体 scripts/gen_systemd_units.py 既有。
- 「## 复现」段:存在,reviewer 按其步骤实跑可复现。
- 配套 commit:41be6e592(5 文件齐全)+ 70444c4c8(报告订正);git ls-files 验三产物均 tracked。

## 8 问题清单

**P0:0 条。P1:0 条。**

**P2-1(残差风险,建议 merge 时顺手处理,不阻断)**——闸门设计边界「doc==快照 != 快照==云上当前」

- 现象:7.8 比对(doc 第 2 节)vs(仓库快照),快照靠人工刷新;若有人手改云上 unit(先例:9-21 public-fund-daily 600->900 即云上手改)而快照未刷,闸门仍 PASS,之后重跑生成器会把 doc 旧值装回云上——#36 病根保留了「快照陈旧」窗口。
- 证据:scripts/main-merge.sh L359-374 只读 --dump docs/deploy/systemd-units-cloud-snapshot.txt 与 doc 第 2 节,无云上直连;实施报告第 6 节 #6 已诚实标注并建议「云上直连 unit 巡检」。
- 影响:纵深防御缺口(设计内,非本次引入);依赖人工记得刷快照。
- 修法:主控 merge 时把「云上 unit 巡检(定期 ssh dump + diff 快照,不一致告警/提示刷新)」登记进 docs/pending-features-index.md(#189 后续项或新编号),避免「已标注但无行动」漂移。

**P3(建议但不必须)**:

- P3-1:7.8 失败消息未提「本地 main 已半完成态、重跑 main-merge.sh 即恢复」(memory main-merge-fail-leaves-half-merged-main 的恢复知识未在闸门出口给操作者),也未给「刷新快照」命令出处。
- P3-2:dump 文件缺失时报 Python traceback(仍 fail-closed,exit=1),建议 catch 后友好报错。
- P3-3:systemd_timeout_gradient_audit.py docstring 末行「只读:不写任何文件」在新增 --align-doc(会写 doc)后略失真;usage 段已写明,建议改「除 --align-doc 外只读」。
- P3-4:7.8 编号排在 7.7 前(位置合理但编号与顺序错位)——cosmetic,报告已说明,可不改。
- P3-5:7.8 成功路径无对勾 echo 行(7/7.5/7.6/7.7 均有),补一行便于日志确认「跑过且过」。
- P3-6:_doc_block_ranges 与 gen_systemd_units.parse_units 的扫描 walk 逻辑重复(标题正则已复用 G.TITLE_RE,仅约 25 行 walk 重复);可选重构复用。

**另需主控知晓(非本 diff 缺陷)**:docs/pending-features-index.md 的 #189 行仍为「待办(未实施)」——按 23.12-1,预计 merge 时随任务销账更新状态列。

**最担心的一点**:快照陈旧窗口(P2-1)——闸门绿 != 云上未被手改;该边界已诚实标注,但配套巡检建议尚未登记待办,「已标注但无行动」容易在后续几周静默漂移,建议 merge 同时落登记。

## 复现(命令清单,reviewer 实跑;WT = 审查 worktree 绝对路径)

    WT=/Users/linhuichen/code/trade/.claude/worktrees/agent-a7a164e4dcbd2dc89

    # 1) 正向:doc 第 2 节 vs 仓库快照 -> exit 0
    python3 $WT/scripts/systemd_timeout_gradient_audit.py --dump $WT/docs/deploy/systemd-units-cloud-snapshot.txt --check-doc

    # 2) 反向:base 版 doc(85790a6ce)-> 必 FAIL(差异字段 30 处,exit 1)
    git show 85790a6ce:docs/deploy/systemd-units-20260912.md > /tmp/189-cloud/base-doc.md
    python3 $WT/scripts/systemd_timeout_gradient_audit.py --dump $WT/docs/deploy/systemd-units-cloud-snapshot.txt --md /tmp/189-cloud/base-doc.md --check-doc

    # 3) 第三源:云上直取 dump,与仓库快照逐行 diff -> 全等(0 差异)
    ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cd /etc/systemd/system && for f in $(ls trade-*.service trade-*.timer | sort); do echo "@@@FILE:$f"; cat $f; done' > /tmp/189-cloud/cloud-dump.txt
    diff /tmp/189-cloud/cloud-dump.txt $WT/docs/deploy/systemd-units-cloud-snapshot.txt

    # 4) 非空转:快照副本注入(单点或整段 sed 皆可,关键=exit 1 阻断)
    python3 $WT/scripts/systemd_timeout_gradient_audit.py --dump /tmp/189-cloud/snap_bad.txt --check-doc   # -> trade-self-heal doc=[600] auth=[10800],RC=1

    # 5) 边界:空 dump -> exit 2;缺失文件 -> exit 1(见第 2 节表)

---
本报告为 #189 的 merge 前置独立审查产物;结论 PASS,可进入主控 scripts/main-merge.sh 流程(P2 建议随 merge 处理,P3 可选)。
