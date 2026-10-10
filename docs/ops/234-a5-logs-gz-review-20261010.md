# #234 甲5 独立审查报告 —— 监控容忍 .gz + 旧大日志压缩清理

> 审查者:reviewer agent(独立 fresh context,独立复算,未采信实施报告自述)
> 审查对象:feat 分支 `feat/234-a5-log-gz`,worktree HEAD `65d5c5784`,baseline main `64946a079`
> 改动范围(5 文件,+607/-28):`scripts/gen_schedule_stats.py`(+73)、`scripts/schedule_monitor.sh`(+42)、`scripts/check_data_gap_alerts.py`(+18)、新增 `scripts/tests/test_log_gz_compat_20261010.py`(306 行)、实施报告 `docs/ops/234-a5-logs-gz-20261010.md`
> 纪律声明:全程只读(未 commit/未 push/未改业务代码);零真实外发(自建 AST 沙箱 + ZeroOutboundTrap + 阳性对照,未运行任何通知/告警/邮件链路);无残留后台任务(两次 pytest 后台均轮询至终态退出);token 未进 argv;无 curl -v/-i。
> **总结论:FAIL —— 不通过 merge。** 代码改造本体(3 脚本)质量高,九要点 8 项 PASS;唯一 BLOCKER = 新增自测文件在 HEAD 下必崩,CI 必红。

## 一、九要点逐点结论

| # | 要点 | 结论 |
|---|---|---|
| 1 | 未压缩场景零行为变化 + 遗漏读路径穷举 | PASS |
| 2 | 坏样本方法有效性(.log 删只剩 .gz 场景独立重跑) | PASS |
| 3 | 独立零外发核查(含阳性对照) | PASS(测试内断言缺阳性对照 → 低分项) |
| 4 | §25 备份可恢复(独立抽样) | PASS |
| 5 | 被删文件真无引用 | PASS |
| 6 | 保留集判定(fd 属主/排除正确性) | PASS(带 note) |
| 7 | "路径未 gz 化纯文案"判定 | PASS(枚举不全 → 低分项) |
| 8 | 独立 pytest(CI 后果) | **FAIL → BLOCKER-1** |
| 9 | B 级分级/影响面复核(§15/§21/§22) | PASS |

### 1. PASS — 未压缩场景零行为变化 + 读路径穷举

**方法**:AST 静态抽取目标 def(§18 L50 static-only,不跑脚本主体)到 /tmp 沙箱;fixtures 采用 17 份**真实生产样本**(13 份现网 .log + 4 份由现网 .gz 解压;§18 L49 禁合成样本);沙箱自带 REPO 缺失显式校验(null_count 断言)防"空沙箱假绿"。

**证据(A-E 硬对账)**:
- [A] 未压缩场景:旧代码 vs 新代码 `gen_schedule_stats` 全量输出**逐位一致**,md5 `74314f1bc04ca20b24b0b8b734c3e0e8`;19 任务 dict 逐字段相等。
- [B] .log 删除只剩 .gz:新代码输出 == 未压缩新代码输出(逐位+逐字段);旧代码同场景 6 处 last_run=null vs 新代码 2 处(2 处为既有无数据任务)→ 缺陷真实、修复有效。
- [C] .log 与 .gz 均缺:旧==新逐位一致(不新增行为差异)。
- [D] `parse_last_run`(6 份真实 gz):plain_old==plain_new;gz_new==plain_new;gz_old==None;缺文件两版均 None。
- [E] `_read_tail_lines`/`_iter_lines`/`_scan_cap_giveup_log`:gz==plain(6 真实文件 + 空/小/缺文件 + >512KB 尾部合成边界)。

**读路径穷举(§23.3)**:scripts/、.claude/、LaunchAgents 全查,无漏网读方。两个带 note:
- `nextday_plan_generator._load_authoritative_log`(L583)按名读 `nextday_plan_launchd.log`(缺→静默 `{}`);该文件不在压缩集,零影响;报告 §1.3 行 7 称其"不读日志行"**描述不准**(低分项 L-2)。
- `check_data_gap_alerts.py` C1/C2 `deploy_*.log` glob(生产函数,非自测夹具):独立复核——压缩集唯一 deploy 文件 `deploy_20260825_0639.log` 非 succ 候选(现网 mtime 降序链上 10/06、9/22、9/19、9/18 均无「退出码=0」锚点,最近命中=9/13 两份有锚点,先于 8/25 被遍历到)→ 压缩前后 C1 判定 succ 完全不变。报告"无需改"成立。

### 2. PASS — 坏样本方法有效性
独立重跑引导场景:旧代码在 gz-only 场景确实产出缺陷输出(last_run null 6 处),新代码与未压缩场景逐位一致;反向(.gz 缺、.log 在)旧==新。缺陷与修复的真实性均经反向对照,引导场景非假样本。

### 3. PASS — 零外发独立核查(含阳性对照)
自建陷阱(urlopen/smtplib 打桩)ZERO_HITS=[] 且**阳性对照可触发**(伪调用被拦 "blocked")、子进程白名单外 0 次调用。与实施报告声明相互印证(其用共享 `scripts/tests/_zero_outbound.py`:仅 patch urllib/smtplib,docstring 诚实标注 subprocess 不覆盖)。
**低分项 L-3**:CI 收集的测试断言只查 hits==[],**无阳性对照**——陷阱若自身失效将假绿(§18 L48"先证判定生效"未完全落地)。

### 4. PASS — §25 备份可恢复(独立抽样)
备份 `/Users/linhuichen/.claude/backups/cleanup-234-a5-logs-20261010/`:14/14 文件在;抽样原地解压 md5 == manifest md5、gz 文件 md5 == manifest.gz_md5;MISSING=0;size/mtime 逐条精确;现网目录零 .log 残留。恢复命令书面可写(helper + manifest)。压缩账 85,221,456 B → 7,691,424 B(净 73.94 MiB)。

### 5. PASS — 被删文件真无引用
`lsof +D` 无 deleted-fd 条目;全仓读路径 grep 仅 3 个已改 reader + 写入方(thinking_proxy.py append / self_heal.sh tee -a / main-merge.sh 注释引用历史日志名,注释非代码路径)。

### 6. PASS(带 note)— 保留集判定
fd 持有着逐字对上两 plist:`com.trade.agent-inbox-watcher.plist` StandardOut/ErrPath(agent_inbox_watcher_launchd.err,pid 4161)、`com.trade.feishu-listener.plist`(feishu_listener.log/.err,pid 76212)。现余 ≥1MiB 仅 7 个,全部有正当理由(rotate 家族 ×2、fd 持有 ×3、已压 .gz ×2),未多压未漏压。
- note 1(低分项 L-5):sensenova-rotate 排除**结论正确且保守**,但报告理由("rotate shim 带 > 重定向")与实际不符(实为 `scripts/com.trade.thinking-proxy.plist` L33/L35 StandardOut/ErrPath + 活跃写入方)。
- note 2(低分项 L-4):`trade/data/logs/agent_inbox_watcher.log`(7.34 MB)是**活跃追加**文件(三次采样 7,333,902→7,334,855→7,337,714 B;写入方 `agent_inbox_watcher.py`,REPO=trade,open-per-write 故 lsof 无持久 fd)——报告"无进程持 fd"快照属实但易误导;排除决策正确(理由比报告更强)。

### 7. PASS — "路径未 gz 化纯文案"判定
`_LOG_MAP`(L2791)仅喂 `_format_alert_item` 展示文本;check_data_gap C1/C2 用 mtime 排序而非路径文本;无下游正则/判定依赖路径形态。判定成立。
- 低分项 L-6:枚举不全——`check_data_gap_alerts.py` L240/273/366/759 告警文案同样内嵌旧 `.log` 路径(同类纯文案,报告未列;不影响判定)。

### 8. FAIL — 独立 pytest(见 BLOCKER-1)
`/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/`(pytest 9.1.1;与 CI ci.yml L123 命令同构):
- 全量 = **`1 failed, 639 passed, 2 skipped in 90.79s`**(复跑两轮,另一轮 92.50s 同果);唯一 fail = 新增 `test_log_gz_compat_20261010.py::test_log_gz_compat_20261010`。
- 单文件 = 1 failed;脚本式直跑 = traceback,**exit=1**。
- 报告称"247 passed, 1 skipped"(13 文件)与"1 passed"在 HEAD **不可复现**(机理见 BLOCKER-1)。
- 后果:CI L123 为 FAIL 阻断且收集本文件 → **merge 即红**。

### 9. PASS — B 级分级/影响面复核
- §21 算法公示:无算法/评分/权重/口径变更 → N/A。
- §22 一致性:数据产物 `schedule_stats.json` 生产路径(未压缩)逐位不变(证据 A);gz 容忍为纯增量读取能力;无多展示位同步需求。实施报告 §五.4"第二个 logs 目录 trade/data/logs"独立复核属实(两目录 inode 不同:237343185 vs 243386726,内容集合不同)。
- §15 回归:证据 A-E 全量对账;改动 3 脚本接口零变化(caller 不感知:deploy/update_all/self_heal/监控链引用面全 grep,无参数/输出协议变化)。
- §24 前端/版本串:未动 → N/A。§23.7 冻结契约:老函数签名/行为保持([C] 验证缺文件分支语义等价)。
- 备查(pre-existing,§10.3①):smoke-checklist C21/C22 断言 `schedule_stats.json` len==9 已过时(现网 19 任务),非本次引入。

## 二、Findings(正式区,≥80)

### BLOCKER-1(评分 100)——新增自测 `test_log_gz_compat_20261010.py` 在 HEAD 下必崩,CI 必红
- trace:`diff_range` = `2be501578` 新增文件 `scripts/tests/test_log_gz_compat_20261010.py:137-145`(及同机制 ③ 段);`linkage` = 不满足;`user_request` = origin: reviewer_own(实施报告"新增自测"目标不可达)。
- 根因(机理):测试用 `_git_show("HEAD:scripts/schedule_monitor.sh")` 抽取"改造前"对照版;**该改造已 commit,`HEAD:` 返回的就是改造后源码** → ① schedule_monitor 对照版抽取面 {parse_last_run, START_RE, ETF_START_RE} 缺 `resolve_log_path` → exec 后 `parse_last_run` 调 `resolve_log_path` 报 `NameError`(直跑实测 traceback:`<extracted> line 188, in parse_last_run`);② gen_schedule_stats 对照沙箱同机制退化为"改造后 vs 改造后"(该段不崩但对照空转)。commit 前(HEAD=baseline)该文件跑绿、commit 后同一命令必红 = 典型"commit 前假绿";报告"1 passed"与之吻合但 HEAD 下不可复现(实测事实)。
- verifier:`command` = `cd <worktree> && /Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/`;`expected` = 0 failed;`observed` = `1 failed, 639 passed, 2 skipped in 90.79s`(唯一 fail 即本文件;脚本直跑 exit=1)。
- 修复方向(§10.6):`action`=simplify;最小修复 = 对照源码改从固定 baseline 取(如 `git show 64946a079:scripts/...` 写死 sha)或把改造前行为以"真实输入→期望输出"固化为断言,彻底弃用 `HEAD:` 自引用对照。`saves_lines` ≈ 0(替换非删除,消除假绿);rationale = 阶梯层「用固定事实(固定 sha/期望值)替代动态自引用」,防再次 commit-后漂移。**复验口径:在 HEAD(含 commit)下重跑全量 pytest 须 0 failed。**
- over_engineering_findings:无(缺陷修,不加抽象)。

## 三、低分项(<80)已滤清单(不进正式报告;供主控追问)

另 5 个低分项(<80)已滤:
- L-2(60)报告 §1.3 行 7 描述不准:`nextday_plan_generator._load_authoritative_log` 按名读 `nextday_plan_launchd.log`(缺→静默 {});该文件未压,零影响。
- L-3(45)测试的零外发断言无阳性对照(§18 L48 口径)。
- L-6(35)旧路径文案枚举不全(check_data_gap 告警文本 4 处同类未提;判定本身成立)。
- L-5(30)sensenova-rotate 排除理由措辞与实际不符(结论正确保守)。
- L-4(25)报告"agent_inbox_watcher.log 无 fd"快照属实但文件活跃增长;另 `schedule_monitor.sh` L58"两 logs 目录同 inode"注释不实(pre-existing:两目录 inode 不同;非本次 diff 引入,备查)。

## 四、独立复算数字汇总

- gen_schedule_stats 未压缩场景对账 md5:`74314f1bc04ca20b24b0b8b734c3e0e8`(17 份真实样本)
- gz-only 场景:旧代码缺陷 null_count 6 vs 新代码 2(2 为既有无数据任务)
- pytest 全量:1 failed, 639 passed, 2 skipped(90.79s;复跑 92.50s 同果)
- 压缩账:14 文件 85,221,456 B → 7,691,424 B;备份抽样 14/14 md5 全对,MISSING=0
- check_data_gap C1/C2:压缩前后 succ 不变(最近含锚点=9/13;10/06、9/22、9/19、9/18 四连无锚点)
- 现余 ≥1MiB 文件 = 7,全部覆盖正当理由

## 五、未覆盖范围声明

- 未审查云上机器(pull 后)运行态;本次改动主体在本地 repo + 本地 logs 目录,云上 timer/日志未动(压缩仅本地)。
- 未重跑耗时性生产链路(update_all/deploy 全链);以静态抽取 + 真实样本逐位对账替代。
- 实施 agent 执行期进程级证据无法回溯,其"残留后台任务:无"按报告口径采信。
- CI 红色为推演 + 本地实证:本地运行的命令与 CI L123 收集面同构(scripts/tests/ 全目录),收集语义一致,推演依据充分但未实跑云 CI(Ubuntu 环境)。
- check_data_gap_alerts.py 云上真实运行日志未抽查(本地无运行记录)。

---

## 六、复验段(2026-10-10,BLOCKER-1 修复后独立复验)

> 复验者:reviewer agent(独立复跑,未采信实施自述)
> 复验对象:feat/234-a5-log-gz 修复态(本地==远端==`a40d09130`;修 commit `296e3e0d7` + doc 补数 `a40d09130`);worktree `/Users/linhuichen/code/trade/.claude/worktrees/agent-a7d4bc8707ee0028d`
> **复验结论:BLOCKER-1 关闭(通过,可 merge)。** 0 新阻断;2 项低分项见 6.5。

### 6.1 全量 pytest(本人实跑,最终 HEAD)

- `.venv/bin/python -m pytest -q scripts/tests/` → **`640 passed, 2 skipped in 92.33s`(0 failed)**。实施报告自称 640/2/94.17s,数字一致(时间差=机器负载)。
- 单文件 `test_log_gz_compat_20261010.py` → `1 passed in 0.17s`;脚本式直跑 → exit=0,**19 PASS/0 FAIL**,`RESULT: ALL PASS`。
- 对比首版 BLOCKER-1 观测(1 failed/639 passed/2 skipped):缺陷已消,收集面 +1 用例。

### 6.2 固化值真伪独立核(核心项;用 baseline 旧源码实地复算,防"拍脑袋数字固化")

方法:独立脚本 AST 抽取测试常量(防抄写偏差)+ `git show 64946a079:scripts/<旧源码>` 取改造前版本 + 与测试同款 3 日志沙箱(INTRA/ETF/UPDATE_ALL)实跑,ZeroOutboundTrap 全程包裹。

| 固化值 | 测试期望 | 独立复算(baseline 旧源码实跑) | 判定 |
|---|---|---|---|
| FROZEN_OLD_PARSE_LAST_RUN_PLAIN | `2026-10-10 09:35:02` | 旧代码同输入 = `2026-10-10 09:35:02` | MATCH |
| FROZEN_OLD_E2E_MD5 | `0cf8f13b12d9b710b055e11531792454` | 旧代码沙箱输出 md5 同值(新代码亦同值) | MATCH |
| FROZEN_OLD_GZ_ONLY_NULL_COUNT | `17` | 旧代码 gz-only(INTRA 仅 .gz)null=17 | MATCH |

- 语义等价(④ 真 gzip 化后仍成立):新代码 gz-only null=16 == 新代码 plain null=16(差分 1 = INTRA 恰被找回);gz 场景 intraday `last_run` == plain。直跑输出实测:`gz_null=16 plain_null=16`、`gz=2026-10-10 09:35 mod=2026-10-10 09:35`。
- md5 可移植:换第二个不同长路径沙箱重跑 md5 不变(路径不敏感,CI 换 workspace 路径不漂移);输出字段无"生成时刻/今日日期"类敏感项(仅 task/name/schedule/est_text/last_run/last_exit/last_duration_sec/log_anomaly*/r2_skip_count)→ 无跨日漂移。
- 全部沙箱跑 `ZERO_HITS=[]`(零真实外发,同首版口径)。
- 口径注:首版 §四 L95 的 6 vs 2 为**真实 17 样本场景**数字,本轮 17 vs 16 为**测试同款 3 日志沙箱**数字,两者场景不同不矛盾,方向一致(旧代码丢任务 → 新代码修好)。

### 6.3 修复无新脆弱性

- **无 git 依赖**:`_git_show`/`_firstdiff`/SKIP 降级分支已全删;全文件 grep 残留仅 2 处**注释文字**(L22/L58,解释 BLOCKER-1 背景),无代码调用 → 浅克隆/无 git 环境成立。
- **CI 可移植**:`PY = sys.executable`(不写死 venv 路径);子进程目标 `gen_schedule_stats.py` 依赖仅标准库(gzip/json/os/re/subprocess/sys/datetime/pathlib)→ CI 依赖面无新增。
- **阳性对照设计安全**:`installed` 仅当陷阱安装成功才发伪 `urlopen('http://selftest.invalid/')`(必被拦);installed=False 时不发调用 → 无真实网络风险。直跑实证 `POSITIVE=True` 且 `ZERO_HITS=[]`。
- 3 处 `subprocess.run` 用途复核:均为沙箱管道(跑沙箱副本脚本/伪调用),timeout 180/180/60s 硬限,不碰生产树。

### 6.4 顺手项验证(②③④ + 低分项处置)

- ② 自发现「④ gz-only 未真 gzip」假绿:已修(真 gzip 写入 + unlink),断言 `gz_null=16 == plain_null=16` 为真检查(直跑输出佐证)。
- ③ 阳性对照:真输出 `POSITIVE=True`(陷阱生效已证)。
- ④ 报告措辞:`234-a5-logs-gz-20261010.md` 修复 diff 覆盖 §1.1/§1.3/§2.2/§2.4/§2.5/§五 六处 —— 假绿更正段、固化值说明、§1.3 行 7 重写(nextday_plan 按名读)、§五 保留集证据重写(plist 行号 + agent_inbox 三次采样递增实证)、同类枚举补充。与首版低分项逐条对应(L-2/L-3/L-5/L-6/L-4 全处置),复核无新失真。
- `schedule_monitor.sh` L58 注释已更正为"trade-data/data/logs 独立真实目录(非 symlink、非 hard link,inode 与 trade/data/logs 不同)"(L55-59,5 行纯注释 diff)。

### 6.5 新发现低分项(不阻断 merge,供主控追问;已滤不进正式 Findings)

- R-1(30)`test_log_gz_compat_20261010.py` L71-82 `heredoc_src` **重复定义两次**(内容完全相同;第二次覆盖第一次,功能无影响;修复 diff 引入的冗余,删一份省 6 行)。
- R-2(20)实施报告 §2.5 写直跑"18 项",实测 **19 项 PASS**(19 项全 PASS;文档口径小偏差)。

### 6.6 复验未覆盖声明

- 同 §五:CI 未实跑(本地命令与 CI L123 收集面同构,推演依据充分);本轮未重跑耗时生产链路;云上机器运行态未审。
- 本轮全程只读(未 commit/未 push/未改业务代码);零真实外发;无残留后台任务(全量 pytest 已轮询至终态退出)。
