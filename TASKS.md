# TASKS.md - 情绪看板迭代任务清单（监管 + loop 工作模式）

> 这是「监管 + loop」工作模式的唯一共享任务文件。子进程开工前**必读本文件** + `REQUIREMENTS.md`（需求真实来源）+ `NOTES.md`（调研笔记）。监管（主进程）不直接干活，派子进程领任务循环。

> **历史已完成/关闭/远期项已按 2026-08-20 任务治理归档(4 态/4 文件流转,非删)**:①真完成 → [docs/tasks-done-list.md](docs/tasks-done-list.md)(**完成文件**,53 条标注完成态 = 43 TASKS治理 + 10 费率改造;呆满 7 天自动归档到 docs/archive/TASKS-done.md)②用户关闭 → [docs/archive/TASKS-done.md](docs/archive/TASKS-done.md)「2026-08-20 任务治理归档段」留关闭记录;③早期历史交接/旧需求 → [docs/archive/TASKS-history-archive-20260820.md](docs/archive/TASKS-history-archive-20260820.md);④远期/搁置待办(场外方案C/性能P2/管理端看板/场外阶段) + 8 项被归档的活跃需求(留言箱/ETF485扩采/公募筛选器/板块轮动/真pin/PWA/订阅推送/overlap delta) → [docs/pending-features-index.md](docs/pending-features-index.md) **模块十六 #79-90**,用户要远期明说再捞回。**本文件只留活跃待办 + 大纲 + 工作约定 + 最新交接**。治理报告:docs/tasks-active-only-clean-20260820.md。前序瘦身归档指针见 [docs/archive/TASKS-done.md](docs/archive/TASKS-done.md)。

## 📍 当前会话状态（compact 恢复用,每次状态变化后 Edit 更新）

> compact 后第一动作:读本小节恢复 transient 状态(活跃 agent/cron/commit 链/正在等什么)。详见 memory `compact-recovery-checklist`。

**最后更新(2026-10-05 12:05 周一·国庆休市)——新会话开工:并行派 4 agent 清交接待办**

> **权威任务状态以 [docs/pending-features-index.md](docs/pending-features-index.md) 为准**(§23.12-1),本节只写 transient 指针。
> **新会话(2026-10-05 12:05 起)已接手**;上一会话两个 agent(r2fix-review / bkt-audit)均已收工且产物归档,无遗留。

**在跑 agent:2 个(background + 进度文件;巡检 cron 兜底 `4f138d8e` 在位;另一次性 cron `fe6d3357`(10-06 08:07 新桶+unit配置)与 `c65cc824`(10-08 21:12 s06 真验证))**
- 🔴 `#160 收口重修(P0)` = implementer(续跑原 agent `aa9bc6dd712a6558f`,分支 `feat/160-consistency-gate-20261005`,进度 `/tmp/agent-progress-160followup.md`)。**审查 FAIL 1 P0**:`check_r2_consistency.sh:81` 的 `systemctl is-active --quiet trade-update-all.service && return 0` 对 **oneshot 运行中(activating)返回 rc=3** ⇒ `update_all_running()` 恒返 1 ⇒ **跳过分支是死代码,10-11 周日假 SEVERE 照发**。**主控已亲自复核代码实锤**:该行确为 `is-active --quiet`;`scripts/self_heal.sh:111` 注释「oneshot 运行中 is-active=activating(非 active)」+ 按 stdout 文本判 running 自证。修法=`systemctl show -p ActiveState --value` ∈{active,activating} 或解析 `is-active` stdout;要求**非 stub 真实运行态复验**。其余全过(降噪三反例/升级档位逐位等价/188+23 测试独立复跑)。
- 🔄 `s06-unit + #159 两支合并审查` = reviewer(进度 `/tmp/agent-progress-rev-s06meta.md`)。范围 A=`d6ce93405`(云上 TimeoutStartUSec=3300 实测 ✓ / 六段串行 3000 推导复核 / doc 计数 40 三源 ✓ / 审计脚本真能报倒挂 ✓ / #189 生成源风险),范围 B=`9960e027f`(§25 全链:R2 两对象 + 抽样回读 sha256 逐位 + 云上 12 文件已删 df≈20G + 恢复路径可执行 + git 卫生)。**已回报进度**:范围A 的 1/3/4 项自报 PASS(3300 实测、40 三源相符、倒挂样例注入双控制通过)。
0. ✅ `老账号 R2 清理评估 + #178 云上环境核查` 已收工(报告 `docs/ops/r2-old-account-cleanup-assessment-20261005.md`,已合 main);**#178 已合 main `5e014d9e3`**(详见下)。
1. ✅ `#164 监控资源维度 + #162 s06 状态残留 hold` = **已合 main `31d26421c`,云上已同步**(feat `feat/164-162-monitor-20261005` commit `06e8c6d66`;reviewer PASS 有保留,P0/P1=0)。**主控 §0 已实测**:云上 `trade-data/scripts` 是**指向 git 仓的 symlink** ⇒ main-merge 的 git pull 已把新 `schedule_monitor.sh` 带上线(云上/本机 md5 逐位一致 `bef01f246e30fb77e2a2718fd5db62b7`,新常量在位)——**原报告"需手动同步云上"不成立,已证伪**。**swap 阈值 80→85 用户 2026-10-05 已拍板接受**(四指标同款 85/90)。**独立根因(unit 超时无梯度)已转 1.5 号 agent**。
2. ✅ `#160 三站一致性校验器接线` = **已合 main `9d0ba2cec`,云上已同步**(feat `feat/160-consistency-gate-20261005` commit `6b3a9341e`;reviewer PASS **可干净合并**,`git merge-tree` 实测无冲突)。云上 `trade-r2-consistency.timer` **今晚 23:20 首跑真生效**(`ConditionPathExists` 守卫已满足)。**遗留转 #187,已派 implementer 续跑原分支**(进度 `/tmp/agent-progress-160followup.md`):①**P1 周日假 FAIL**(update-all 有 `Sun 22:30` 档跑 112-121min,与 23:20 采样点重叠,首暴露 **2026-10-11**,修法推荐 preflight `is-active` 即跳过)②P2 双告警通道加抑制(照 #123 R3)③**连续 2 天 FAIL 升 critical(用户拍板)**④doc §1.4 清单 5→6。
2.5 ✅ `s06 快照断供影响面核查` = **已完成(researcher 独立实测,证据链闭环)**。**结论**:①**断供证真但口径要准** —— 断的是**同步/传播段**,不是内容生成:gen 段每日成功(coverage 到 20260930、`current={'date':'20260930','mode':'new14'}` **零缺行**),R2/CDN(用户可见副本)停在 09-24 版;**R2 侧已治愈**,治愈者=10-04 周日错峰 deploy 的全量 verify-r2 「自动补传 1 个」(`deploy_20261004_2230.log:774`)。实质=R2 副本滞后最多 6 自然日/3 交易日。②**#162 任务描述的「09-29/09-30 已恢复」已证伪**(那两段日志同样无结束行)。③**影响面**:前端可见但**不静默**(common.js L1038-1063 超覆盖期→NEW14 兜底+轻标注;且真实基座同期也是 new14 ⇒ **本次过滤结果与真值等价,仅多轻标注**);后端脚本读本地不受影响;**静默的是检查侧**(详见 **#188** 三层盲区,最狠一条=**被杀时脚本走不到 `s06_snapshot.sh:138` notify ⇒ 告警与链路同亡**)。④**定性=L45 同族新变种**(非原病)。⑤**回填无需**(R2=09-30 版=最新交易日)。
2.6 ✅ `s06 unit 超时梯度修复 + systemd units 计数重算` = **已完工(researcher 独立实测 + implementer 落地,待合 main)**。分支 `feat/s06-timeout-grad-20261005` @ `d6ce93405`(只推 feat,未碰 main)。**⚠️ 值不是我原说的 1200,是 3300 —— 主控已读 `scripts/s06_snapshot.sh:84-128` 逐段核过并采纳**:`run_to` 是**逐段**上限、六段**串行**(gen300+check300+R2上传900+posrating300×2+R2快照900 = **3000**),要让脚本走完到 `:138` 的 notify 必须**外层 > 各段之和 3000**;取 1200 会在 ④b 中途被系统杀,**恰在最需告警的 R2 障场景丢 notify = 等于没修**(我原先的 1200 基于"单段 900+缓冲"的错误模型,已纠正)。云上 `trade-s06-snapshot.service` `TimeoutStartSec` **600→3300 已应用 + daemon-reload**、`OnCalendar` 未动、备份件 `.bak-20261005-pre-timeout`(含 600)可回滚。**根因三条独立证据**:①日志「开始」12/「结束」9,缺的正是 09-28/29/30 三个交易日(均止于 R2 段)②内层六段串行合计 3000 > 外层 600 ③`scripts/schedule_monitor.sh:427-431` 第三方注释同根因。**同类错误面全 40 service 审计:倒挂 0 个**;有 shell 内层看门狗且留余量者 5 个(s06 3300>3000 余 300;`r2-consistency` 960>900 **余 60 已到边**;`check-data-gap` 600>300;`kelly-intraday-rerun` 600>180;`turnover-backfill` 外层 0=无限)。顺带纠正旧说法:`nextday_gap_check.sh` **无** shell 内层看门狗(旧口径"余量≈0"不成立)。**🔴 新发现已登记 #189**(doc §2 ini 块 30 个 service 的 `TimeoutStartSec` 仍是迁移批旧值 ⇒ 重跑生成器会静默回退 #36 收口,生产事故级;agent 未动,超范围)。**⚠️ 真行为验证点 = 2026-10-08 20:35**(今晚 10-05 休市走「非交易日跳过」不碰 R2 段;已设一次性 cron `c65cc824` 21:12 复核)。产物:`scripts/systemd_timeout_gradient_audit.py` + `docs/ops/s06-timeout-gradient-20261005.md` + doc 计数重算。
2.7 ✅ `#159 public_fund.db.bak(10G)异地备份 Batch B`(§25 先备份后删)= **已完工(待合 main)**。分支 `feat/159-pfdb-bak-offsite-20261005` @ `9960e027f`(只推 feat,origin/main 未动)。§25 三步走通:①备份到 R2 新桶 `signal-backup2/decommissioned/` 2 对象(zstd -12)②**全量 key 比对 MISSING/BAD=0 + 抽样回读逐位**(GET→zst sha256→`zstd -d`→解压 sha256 == 源 .bak sha256,两文件 PASS)③验过即删云上 12 文件(~10G,双仓镜像 sha256 逐位一致=纯冗余),云盘 **11G→20G**(83%→65%)。**⚠️ 诚实标注**:上传中途撞并发 #178 agent 14:10 改云上 `upload_r2.py`(`BACKUP_BUCKET`→signal-backup2),致 file1 落老桶/file2 落新桶;已重传 file1 到新桶 + DELETE 老桶 stray(仅删本人产物),**终态两文件同居新桶零丢失**。产物:`docs/ops/159-pfdb-bak-offsite-20261005.md` + `docs/scripts/{pfdb_bak_offsite_upload,restore_pfdb_bak_r2}.py`。**#159 销账 + 待合 main**。

**📌 本轮拍板(2026-10-05 用户「按你建议的走吧」,逐项落地)**
- ✅ **swap 阈值 80→85 接受**(四指标同款 85/90,不再单独调回)。
- ✅ **#160 闸门位置认可**(独立每日 timer + 仅告警,不放 deploy 链);**追加增强**:连续 2 天 FAIL 升 critical ⇒ 待 #160 合并后**续跑同一分支**补。
- ✅ **systemd units 计数按实测 40 重算**(已派给 2.6 号 agent)。
- ✅ **s06 病根今天就修**(unit `TimeoutStartSec` 600→≥内层+余量,已派 2.6 号 agent);**另派 2.5 号 researcher 核 s06 快照断供影响面**(疑似断 10 天,可能真数据缺口)。
- ✅ **R2 老账号清理:只做 A 档(163.9MiB)+ C 档(老桶 legacy 补刀,10-07 后)**;~~B 档 fund_nav~~ / ~~D 档 flat~~ **不做,交给 lifecycle 自然回收**(10-26 前后 ~5.0GiB 达标,不为 0.5–0.9GiB 冒动唯一副本的风险)。**A+C 与 #186 一起在 10-07 窗口后派单**。
- ❌ **GitHub CI 失败告警不并入监控链路**(CI 失败≠生产故障,邮件已直达;真问题是闸门子串匹配,今日已修根因)。
- 🔄 **保留 3 支分支处置**:`feat/r2-slim-20261003` 与 `feat/ledger-20261001b` **建议删**(草稿/活文档旧分叉,bundle 可恢复);`zcode/standin-charter` **保留**并比对 `.agents/zcode-standin/SKILL.md` 里 main 没有的纪律段,有用则并入 main(待派 researcher)。

**✅ 已收工(2026-10-05 下午)**
- ✅ `Git 分支大扫除`(用户点名「branch 100 多个了」):**本地 162→7 / 远端 125→7,删 275 支**(本地 155 / 远端 120),零失败。报告 `docs/ops/git-branch-cleanup-20261005.md`(已合 main)。§25 bundle 备份+**实测可恢复**(硬链裸克隆 → 清 reflog → fetch,25/25 ref hash 逐位一致),已传新桶 `signal-backup2/git-branch-bundles/20261005/`(不在 lifecycle 前缀内)。判定口径=三硬证据(ancestor / `git cherry` patch-id / blob 逐位),**没用 `--merged`、没信三点 diff**。**保留 3 支(有独有内容)**:`zcode/standin-charter`(SKILL.md 含 main 没有的纪律段 ⇒ 建议比对后并入 main)、`feat/r2-slim-20261003`(草稿 vs main 定稿 ⇒ 建议删)、`feat/ledger-20261001b`(活文档旧分叉 ⇒ 建议删)。**主控补验**:GitHub API `open PRs=0` ⇒ 删远端 head **未关闭任何 PR**;已修坏 ref `origin/HEAD`;回收 2 个已合 worktree + 1 个废弃 detached review worktree。

**本轮已完成(2026-10-05 下午)**
- ✅ `告警系统性排查`(用户点名):报告 **`docs/ops/alert-systematic-review-20261005.md`**(206 行)。在册告警**全部四态分类、无未分类遗留**(已修闭环 / 已优化降噪 / 仍待办 / 误报);新登记 **#181-184**(fetch_news 降噪拍板 · 飞书心跳盲区 · utf-8 截断升级评估 · dry-run 写 latest.md),盲区 6 项。关键实证:R2 kill 链**数据无缺口**(md5 三方逐位一致)、#174+#177 新旧行为对照生效、CSP #133 线上已无头。
- ✅ `#165 回滚预案文档`:报告 **`docs/ops/rollback-playbook-20261005.md`**(237 行),含三步回滚命令+耗时+风险点+验证法。
- ✅ **CI 网关止血**:GitHub `ci.yml` 步骤⑤ `check_task_state.py` FAIL 根因 = **#178 状态格子串误判**(`CLOSED_STATUSES` 含「已合 main」,而格子内描述 #180 时写了该词)。修法=改措辞去字面量;本地复跑 `--deploy-mode --skip-zombie-crons` **2 ok / 0 fail**,已推 main `e3f130031`。
- ✅ **`#178 备份桶迁账号` 合并上线**:主控 §0 核闸门(云上 `.env` `R2_BACKUP2_*` 四键全在、**无** `R2_BACKUP_BUCKET` 覆盖 ⇒ 写新桶路由正确) → `main-merge.sh` → **main `5e014d9e3`,云上已同步**。合后收尾转 **#185**;老账号手动清理执行转 **#186**(评估报告 `docs/ops/r2-old-account-cleanup-assessment-20261005.md`,6 项待拍板见报告 §7.9)。
- 📌 **注意(branch cleanup agent 用)**:`feat/178-r2-backup2-route-20261005` **已合入 main,内容全部在册**,其 worktree 可回收;但**回收动作归主控**,branch cleanup agent 仍按原禁区不碰在册 worktree 分支。**该支与其 worktree 已于 2026-10-05 下午由主控回收(另含 #164 的 worktree/分支)**。
- ✅ **`#178 备份桶迁账号` = 已完成(2026-10-05 下午)** —— 主控已核云上 `.env` 四键全在 + **无** `R2_BACKUP_BUCKET` 覆盖 → `bash scripts/main-merge.sh feat/178-r2-backup2-route-20261005` → **已合 main `5e014d9e3`,云上已同步**(feat tip `ebd46ce3e`)。**合后收尾三件已转 #185**(①空闲窗口首轮全量回填 ≈450MB 灌新桶 ②新桶完整性验证 MISSING=0+抽样 md5 ③老桶 large-json legacy ≈0.27GiB —— 🔴 新发现:合并后 `_prune_large_json` 目标桶变成新桶,老桶 legacy 断链成孤儿,别再等自动清)。**主控实测**:切换时新桶近乎空(2 对象/0.52GiB)⇒ 回填前异地备份实际未闭环,**今晚 17:50 `update-all` 是首轮回填触发点,已设一次性 cron `d83fc803`（10-06 08:07)复核**。
- ✅ `#163 断档回填` = 已实施并上线 + 已合 main `90537c538` + reviewer 独立复核 PASS + **用户已拍板「保留订正」**(不再回滚;订正=09-29/30 的 `a_width_*` 显示值按公示口径去北交所)。**已闭环**。

> ⏳ **待用户拍板(#163 两点)**:①回填口径取 **5211/5212**(排除 348 只 920 北交所,依 #101 公示口径 + `bj_width.py` + `width_history.py:code NOT LIKE '920%'` 三源一致),非派单写的 5559/5560(含 920);②09-29/09-30 的 `a_width_*` **显示值被订正**(up 3471→3249 / down 1932→1819 / zt 57→53·52→56,其余 62 天逐位不变),因原 intraday 值含北交所、违反公示口径;**不拍则维持现状(已上线)**;回滚法见 pending-index #163 行。
> 🔎 **#163 顺带发现(待排 follow-up)**:`cmd_upload_all_data`/`purge-low-freq` 的 purge 只清 `/data/` 不清 `/r2/data/`,致 `/r2/data/a-stock-*.json` 边缘缓存残留(已手动 purge 修当前);根治=照 data-large 双前缀做法,**等 #178 收工后一起改 `upload_r2.py`**。另:`upload-etf-hist` 被看门狗 kill(severe 告警,05:10 同款,非本次引入,无数据缺口,force_full 未完成即被杀)。
> ✅ 本会话已完成:`#180 三项必改`(implementer + **reviewer PASS** → **已合 main `7d5f17b38`**,云上已同步)· `#163 断档回填`(implementer,补 9/29-9/30,已合 main `90537c538`,云上已同步)· `large-json 可配性核实`(researcher → **#179 定案不配**)· `陈旧 worktree 清理`(删 48 留 2,零丢失)。
> ✅ `陈旧 worktree 清理` **已完成**(2026-10-05 12:1x,general-purpose):删 **48 个**、留 2 个本会话 implementer、**零内容丢失**;§25 可逆性验证 6 个有改动项均无抢救价值(两份报告 md5 与 main 版逐位一致);`git worktree list` 现剩 4 项;残留空目录 `.claude/worktrees/refreeze` 已清。

> 上一会话已收工留档:✅ `r2fix-review` 有保留 PASS 已合 main(`4b88a1251`,9 项全审无 P0);✅ `bkt-audit` 报告已合 main(`docs/ops/r2-backup-prefix-lifecycle-audit-20261005.md`)。reviewer 报告 `/tmp/r2fix-review-report.md`(建议落 docs/ops/,已并入 #180 落档)。

**本会话已完成**
- R2 死循环**根因报告已合 main**(`9af15ec58`,`docs/ops/r2-export-guard-backup-timeout-rootcause-20261005.md`)。
- **备份桶新账号凭据双端落 `.env` 并实测通过**(本机 + 云上各 LIST/PUT/GET/DELETE/复查 五动作全过;云上须走 Python 通路,curl 7.81 的 `--aws-sigv4` 不可用)。
- pending-index:新增 **#178**(备份桶迁独立 CF 账号);**#174 / #176 / #177 / #163** 状态列全部更新(修复已实施·待审 / #163 方案已定案)。

**关键决定(2026-10-05)**
- 老桶存量**不搬**(用户拍板):只切今后新写,存量靠 lifecycle 自然回收。
- 备份桶走**独立 CF 账号**(独立免费额度),非本账号第二个桶。

**git 状态**:main `9af15ec58` 干净;`worktree-agent-a32eca2ef3e40884f` 已推 origin **未合 main**;本交接文档走分支 `docs/session-handoff-20261005`。

**下一步(按序,硬期限 2026-10-08 开市前 —— 10-05~10-07 假期窗口是唯一机会)**
1. ✅ **已完成** —— `r2fix-review` 有保留 PASS → 已合 main `4b88a1251` → 云上已同步。**遗留 = pending-index #180 三项必改项**(优先 ㈡ 大文件低速误杀回归)
2. 派 implementer 实施 **#178**:`upload_r2.py` 引入第二套 endpoint+凭据并按目标桶路由(**#176 已合 main;须等本批 #180 收尾再派 —— 同改 `upload_r2.py`,不可并发**)
3. 派 implementer 实施 **#163** 断档回填(首选 = `fapi_daily_raw` 库内搬移,分钟级;详见 pending-index #163)
4. ✅ **普查已完成,报告已归档**:`docs/ops/r2-backup-prefix-lifecycle-audit-20261005.md`(合 main)。**下一步 = 用户 dashboard 配规则**(我方 key 查 lifecycle 返回 403,配不了)。用户已拍板「**新老桶都补**」,定稿规则见 **pending-index #179**:`pre-upload/` 补 **7 天(最高优先,5,540 个 3.13 GiB、日增 ~1.08 GiB)** / `weekly/` 28 / `monthly/` 365 / `large-json/` legacy 补 7 天(**flat 31,673 严禁配删除规则,唯一副本**) / `claude-backup/` 30 / `backup/` 14 已配 / `decommissioned/` 与 `mac-backups/archive/` **不配**。**新桶 `signal-backup2` 已复核存在且为空,直接在它上面照配同一套。** **⚠️ 仍未解决的一处记录打架**:老桶 `backup/` 规则是 **14 天**(用户 10-05 dashboard)还是 **30 天**(本文件 #169 记的 10-04 dashboard)——直接影响存量回收速率,请用户下次开面板时顺手再核一眼
5. 清理 `.claude/worktrees/` 下 **~48 个陈旧 worktree** —— 🔴 **动手前必读(2026-10-05 主控逐个数过)**:里面 **6 个有未提交改动,全是 2026-10-03 的历史遗留**。~~其中两份是 untracked、从未进过 git 的 review 报告,删掉就永久找不回~~ **【2026-10-05 12:xx 主控核实更正:这两份报告早已在 main,且与 worktree 内那份 diff 逐位一致(IDENTICAL)→ 无"永久丢失"风险,无需抢救】**:
   - `.claude/worktrees/agent-a4769bc9343c0828a/.../docs/ops/help-dblclick-review-20261003.md`
   - `.claude/worktrees/agent-ab46344df19b9c206/.../docs/ops/futures-pos-replace-review-20261003.md`
   另 4 个:`a1129d3a97dfbb24c`(改 `static-site/app.min.js`=构建产物,低风险)、`a82d3e09efe0d0523`(改 3 个 `scripts/tests/test_132_*`)、`a0b7e692af78b2ef3`(删 `docs/ops/worktree-cleanup-verify-20261003.md`)、`a54d78abfef6c90f5`(untracked 同名文件,疑与前者重复)。**处置顺序:先把上面两份 review 报告捞出来落 `docs/ops/` 并 commit,再按 §25 验过可恢复性,最后才 `git worktree remove --force`。** 本会话新开的 5 个 `docs/*-20261005` 分支已确认全部进 main,可安全删。原始任务描述:(多为已完成 agent 残留,其中 3 个 `locked`)。**危害**:占着分支会让续跑同一任务的 agent `checkout` 报 `fatal: already checked out` → 只能 cherry-pick → 分支身份漂移(见 memory `resume-same-task-reuse-branch`)。**处置**:先确认对应分支已推 origin(worktree 删掉不影响 origin 上的分支),再 `git worktree remove --force <路径>`;**按 §25 先把备份/可恢复性验证做掉再删**。

**未决/待用户拍板**:fetch_news 周日夜 SEVERE 噪音是否接受;是否启用 CF R2 Local Uploads;`rzhb_backfill` 登记漂移(云上 timer 有 19:15 槽但 `schedule_monitor.sh` 只登记 08:00)。
**✅ 已拍板并执行(2026-10-05 用户)**:老桶 `backup/` = **14 天**(定案);**用户已在「新老两桶」配好 5 条 lifecycle**:`pre-upload` 7 / `weekly` 28 / `monthly` 365 / `claude-backup` 30 / `backup` 14;`decommissioned`、`mac-backups`、`large-json` **不配**(large-json **已定案**:CF prefix 无通配符,配 `large-json/` 必误删 flat 31,673 唯一副本)。老桶 `pre-upload` 3.13 GiB 存量预计 24h 内开始被 lifecycle 清。

**最后更新**(2026-09-15 周一 16:1x):✅ **外审 review 门禁链路恢复并端到端验证通过**。背景:v1.1.17/v1.1.18 外审被跳过(门禁 retry 风暴 + claude 回传静默断链)。本轮 fix 全在 main(main==origin/main==`c457a8b09`):①`07de081ff` 外审模型钉深(deepseek-v4-pro-0813)+重试风暴根治 +`fc18cc3be` 终态 request 的 git ref 泄漏清理 ②`c7077c37f` **PIPE 满死锁根治**(spawn stdout/stderr=PIPE 却只在退出后排水,子进程写满 64KB 永久卡死→改文件重定向)③`6e2c9dc20` **claude 回传静默断链 P1**(is_already_processed 误短路 claude 队列,消费者永不 spawn→短路仅对 codex 队列)④`a56be8e04` plist 单一事实源归位 launchd/(删 scripts/ 重复 + 补齐 CLAUDE_BIN/CODEX_REVIEWER_MODEL/PYTHONUNBUFFERED)⑤`c457a8b09` claude 消费者预算 0.50→5.00(deepseek 下不够烧,exit=1)。**mini test(2 commit)全链路验证全绿**:watcher 接单→codex 外审(deepseek)→报告落盘→claude 回传 spawn→**claude 消费者回执 exit=0**→ref 清理;外审 FAIL 的 4 findings(P1/P2x2/P3)经 claude 消费者逐条复核已全部修复。
**✅ codex 缓存命中修复(2026-09-15 实测)**:根因=非默认 `disable_response_storage=true`(关服务器 response storage,炸掉 Responses API 多轮前缀缓存);改回默认 `false` 后同 2-commit 外审 token **143,207→97,995(−32%)**、无接口报错、verdict/回传/ref 链路正常,已保留(bak: `~/.codex/config.toml.bak-cachetest-20260915-162351`)。进一步候选(未做):codex base_url 改走 thinking_proxy 127.0.0.1:8899 借 cache_control,可能再提命中,但需验 bailian 兼容性。
**前序**(2026-09-12,详见 docs/archive/TASKS-handoff-20260912.md):✅ 8 项 reviewer 非阻断小项打包上线(main-merge 20260912-a585)+README 角标 2.5 语义同步 + #91 次日开盘口径核销。
**待办指针**:#108 四档升级判定源 hs300→cyb 待拍板;#174/#175 + 模块十九登记项(rzhb_backfill 登记漂移 / notify.py --dry-run 写 latest.md 瑕疵 / 架构改造 A-B 档 待事实核查)均见 docs/pending-features-index.md 模块十九(2026-10-05);v1.1.16..v1.1.18 外审补审(263 commits)待定预算/范围;codex 缓存命中优化(上);`feat/lof-path-absolute-align` 分支 ahead of origin by 2(重复 commit)待 main-merge 收尾。

## 📋 待办（2026-08-20 治理后:全移 todolist,本文件无活跃 checkbox）

> **TASKS.md 已清空活跃待办**(2026-08-20 用户「task 只留交接/大纲/必要指针,无活跃 checkbox;待办全判远期移 todolist,等有真正在做再放」)。
> - 真完成 53 条 → [docs/tasks-done-list.md](docs/tasks-done-list.md)(完成文件:43 TASKS治理 + 10 费率;待 7 天自动归档)
> - 用户关闭 3 条 → [docs/archive/TASKS-done.md](docs/archive/TASKS-done.md) 关闭记录
> - **待办/远期全在 [docs/pending-features-index.md](docs/pending-features-index.md) 模块十六**:#79 场外方案C(8步)/#80 性能P2(含 P2-11 大盘 tab SVG/**#82-89 八项归档活跃需求**/#90 场外阶段/**#91 次日开盘口径** 已核销完成(2026-09-12,详见 pending-index #91)(#101 北交所宽度/#102 FAPI转正 已 2026-09-06 完成上线,从远期移除;#81 管理端看板已于 2026-08-20 用户拍板关闭,勿再列为远期;详情 TASKS-done.md 关闭记录)
> - 待安排指针(近期):excludeSpecialBearCyb 实测,见 pending-index 对应节。**#91 次日开盘口径已核销完成(2026-09-12),勿再列待安排**。#73 8宽基四档 / #74 邮件广播hit白名单 已完成 done-list 登记(2026-08-21 同步)。
> - 后续新增真实待办(有活在做)再写回本节。

### 🆕 信号凯利全信号卡「快照+每日演进+异常告警」(2026-09-04 用户新增,源自今日 P0 异常演进事故)

> **用户需求原文**:「补一个待办,内容就是信号凯利回测全信号卡的快照,并且可以从快照看出每日演进以及告警,像今天这个问题,就属于异常演进,一定是坏了」。
> **背景/判定标准(用户给的关键认知)**:H 档收益率正常演进曲线 = **230→226→224**(前几天下跌→昨天弄好最新 224%),渐进微调=正常;**今天一下子掉几十 pp(224.92→182.25,A 163→142.68,无隔日)= 异常演进=一定是 bug**。用户并指出:维护修了那么多条、且有 230→226→224 的正常演进过程,故**「数据一直坏」不成立,今天这次一定是 bug**,不是"一天演进/数据陈旧"能解释。
> **要做的事**:①给信号凯利全信号卡(A/H 等档位收益率等关键数字)加**每日快照存档**(历史留痕)②从快照可**看出每日演进**趋势③**异常演进告警**(突变量级超阈值,如单日掉 N pp 即告警,参考 §5.1 防前视/告警门控)——像今天 224.92→182.25 这种量级必须被自动抓到并告警,不等用户发现。
> **状态**:✅ **已完成(2026-09-04 当天实施上线)**——见 docs/kelly/analysis/kelly-sigkelly-advance-20260904.md「实施」段:F 快照+演进+告警全落地(signal_kelly_snapshot.py 每日快照+index+滚动窗突变/停滞告警+lab「📈演进」入口+check_signal_accum_nav_lag 监控补盲)。09-17 做过一次演进快照断更排查(历史文件迁云未带,已补齐14点),结论=快照链正常非断更。
> **关联**:本次 P0(信号凯利全信号卡收益骤变,排查链 docs/kelly/ 待落档)。

### 🔄 AI 降亏交互重构:单开关+模式下拉7种(2026-08-23 用户拍板,前期工作,校验后再谈 NEW 设默认)

> 构想(用户确认):AI 降亏保留 **1 个总开关**,模式改**下拉 7 种**(8键[默认]/9键/A/B/C/14键/18键 全封装);**四消费点接入且互相独立**(①首页近期技术分析参考点 ②首页模拟回测弹窗·全历史真实过滤 ③分析参考点 AI 监控 ④📊 信号凯利回测 lab);顺手做**3+1 处补漏**;**方法池 57→最新全量**(新键默认关+勾选联动,交互同现有 37 小标签);新增**「AI 降亏组成对比」展示区**(7 方案各由哪些逻辑条件叠加)。默认逻辑不动,用户手动切下拉对比明细校验。
> 短标语(已核报告):8键=现役地基·稳定参照(「长线友好」已被 mine25 可操作口径证伪)|9键=8+候选1·牛市辅备买拦截|A on9=进攻王·近端牛市吃满|B on9=均衡卡·K档最钝感(**双正王名头因 g2 bug 作废**)|C on9=保守防守·熊市少亏|NEW 14键=新防守王·全史第一+回撤最浅|NEW2 18键=NEW 影子·入选差31笔。⚠️ A/B/C=叠9键口径、14/18键=重构换基座,下拉项须标口径差异。
> 版本:发 v1.1.3/v1.1.4(默认组合不动但功能面大改,§5.4⑥ 精神);v1.1.5 留给将来 NEW 设默认。

- [x] **T0/T1/T2/T3-1 已完成上 main,已登记 [docs/tasks-done-list.md](docs/tasks-done-list.md)「2026-08-28 AI 降亏交互重构完成段」**(八连 commit c54eb89a6/5a299d243/69b1a88c5/c3f214a99/e1b4440c6/c7a9bdf82/40ed3d5d9/241a89d08 核实均在 origin/main)。综述:20 键规格单源 scripts/loss_rules.py+特征 JSON+双端谓词+37 标签链+§21 公示;lab 凯利区「AI 降亏组成对比」折叠区;sim 弹窗/首页 7 模式下拉重放(默认 p8≡现网)。细节见 done-list 段。
- [x] T3-2 完成待 merge(2026-08-23,feat/t3-2-home-monitor 四连 dd27520c5→cff2fb41f→e4d49d5ab→d4622bdec):首页参考点 7 模式下拉(tds_home_fade_mode)+AI 监控卡模式下拉+**「+1」开关**(tds_overfit_fade_mode/tds_overfit_bull_stop,_ovAggregateRecent 组集+banker's rounding,老 json 无 recent 回退 bank)+第三份谓词迁移(_isBullStopHit→_tdsFadeSpecHit);playwright 冒烟 12/12 抓出绑定 bug 已修(cff2fb41f);终审揪 new18 缺键(RECENT_KEYS 漏 n2NorthOutConcept)+实施上报 FIELD 错位历史 bug(FIELD 21 列 vs schema 24 列致 by_grade 恒空,**用户拍板修**)→收尾 d4622bdec 两单点:FIELD 21→24(by_grade 三桶出数 n=3/24/222,评级类回测键 janMidRating 从静默失效转生效,连带影响已如实报用户)/n2NorthOutConcept 补打标 707 行+H 断言根治未来漏同步;reviewer 复核 **PASS**(parity 18/18+fade_predicate 115 键 diff=0);⚠️ merge 后需重跑 overfit.json 上线(监控卡过滤视图/评级维度数字会变=预期修复非回归,§22 三步跟上)
- [x] ~~UI 修复批(P0 卡死+用户四连抓)已完成待 reviewer 终审~~(2026-09-01 销账:代码已 100% 完成并并 main,P0 根修 `7ea4f8272`+批本体 merge `1cd137e70`/`839b5d283`;reviewer 终审已实质完成;common.js 组件 `_tdsFadeModeSelectHTML` 冲突经 T3-2 收尾 `44d383620` 覆盖,无待处理冲突;见 done-list「2026-09-01 遗留对账销账」段)
- [x] ~~双 merge 收尾链~~(2026-09-01 销账:①② merge 全落地——T3-2 `673ebe2ef`+适配 `44d383620`/`8811295d6` 均在 main;③overfit.json 正式重跑上线已核实——`overfit_monitor.json` generated_at 2026-08-31 21:40 含 n2NorthOutConcept/janMidRating 新键,线上 ss.fx8.store 已到新版,deploy 链 check_overfit_split_parity/recent_parity 已挂;④T4 公示+README 属常规发版收尾;⑤T5 用户手动校验为用户侧动作;见 done-list「2026-09-01 遗留对账销账」段)

### 「3+1 处补漏」定案(2026-08-23 用户拍板,并入 T3/T4)
> 用户原话:「3处已有的 +1 就是这个ai监控量化里 现在还停留在ai降亏过滤开关 没有同步前面的+1多选 这次直接对齐其他3处做 一样的交互」+ 全选三项附加。
> ① **AI 监控卡补齐**(核心 +1):分析参考点 AI 监控卡现在只有 AI 降亏过滤总开关,缺「+1」(候选1/牛市辅备买全停)开关,这次对齐其他三处做一样的交互(新模式下同步支持下拉)
> ② 三处独立化模式复用到新下拉(lab/sim弹窗/首页各自独立 key)
> ③ 公示三处+README:purpose-notes/lab tooltip/首页 badge 同步 §21/§23.6 + README 功能描述
> ④ 谓词同源债清理:同一套过滤谓词现存三份拷贝(lab/_sim/sim_core)+后端两份硬编码(queries/overfit),收敛单一来源防口径漂移
- [x] ~~T4 公示 §21 同步(purpose-notes/lab tooltip)+README §23.1+版本号 bump+reviewer 审查(依赖 T1-T3)~~ **2026-09-27 销账**:随 v1.1.5 发版完成(2026-09-01 已定性「属常规发版收尾,归常规发版」,见上方销账段)
- [x] **2026-09-27 销账:目标全达成** —— NEW14 设默认 + v1.1.5 tag(@04144b269,08-24)+ 基准锚点 memory 升级(已升至 v1.1.5 再至 v1.1.7)+ 前端默认值/§21 公示/README 四件套均已随发版联动;AUTO 择时调研结论=**不成立**,故按「不成立则 NEW14 设默认」执行。以下为原始任务描述:T5 主控验收 merge 上线 → 用户手动切换校验 → **用户验收数据通过且 NEW 14键确实如预期**才走 NEW 设默认任务:届时打 **v1.1.5 tag**(2026-08-23 用户定)+ 同步把测试基准锚点 memory(`test-baseline-v112-anchor`)升级为 v1.1.5(未来一切回测/挖掘以 v1.1.5 为前提)+ 前端默认值 + §21 公示 + README 四件套联动。**⚠️ 2026-08-23 用户新定调:AUTO 择时切换模式调研(regime-mode-rotation-research,#94 已完成,见 pending-index ★)= v1.1.5 定稿「平台主推 AI 算法基座」的最后一次努力**——成立(样本外+平稳优先效用)则 v1.1.5 基座=AUTO 方向,不成立则 NEW14 设默认;调研结论出来前 NEW 设默认暂缓执行

### 📚 本轮降亏挖掘战役 README 总结导航(2026-08-23 用户点名,收尾必做)
> 背景:mine22/23/24 全员竞赛+mine25 可操作长线+g2 门审计修正+速查卡等扩容产物多,`docs/kelly/analysis/README.md` 只有平铺逐行索引,缺总览入口。
> 做法(等长线补录+T0 报告落定后一次做全):①README 顶部加「2026-08 降亏挖掘战役总结」段:总标语+七方案(8键/9键/A/B/C/NEW14/NEW2 18键)一句话定位+权威数字源(mine24_compare.json/mine25 json)+g2 失真修正说明;②每方案给索引链:速查卡→主报告章节锚点→数据 json→复现脚本;③toggle 目录(ai-filter-mode-dropdown 调研报告)入索引。验收=从一个入口能跳到任一方案的数字/论证/脚本三层。

## 总体大纲

A 股 / 港股 / 全球盘后复盘看板。Python 3.11 + FastAPI + SQLite + ECharts，Mac 本地。当前 27 个指标、13 指数、运行在 http://localhost:8000（`--reload`，改文件自动生效，**不要杀进程**）。本轮迭代目标：修回归问题 + 补国债 / 原油白银 / 红利 / A 股十年回溯 / 买卖点优化 / 行业看板 / 概览美化。

相关文件：`REQUIREMENTS.md`（需求 + 实现状态 + §9 变更史）、`NOTES.md`（调研 + 修复史）、`05-回归测试报告.md`（本轮回归）、`01-问题清单.md`（上轮 bug）、`config/indicators.yaml`（指标注册表）、`app/`（采集 + 计算 + API）、`web/`（前端）。

> ⚠ 开工先看 `data/alerts/latest.md` 是否有未处理严重告警，有则优先排查。

## 工作约定（子进程必读）

1. **领任务**：读本文件，找第一个 `状态: pending` 且 `依赖` 已满足的任务，把状态改 `in_progress`、填 `负责人`（你的标识）。
2. **干活**：按 `描述` 做，达到 `验收标准`。改动前先读相关源码。技术细节自己定；**碰到方向性分叉不要猜——停下、在 `结果备注` 写明、汇报给监管**。
3. **写结果**：做完（或失败）后在 `结果备注` 写：改了哪些文件、做了什么、成功 / 失败、遗留问题。状态改 `done` / `failed` / `blocked`。
4. **汇报**：你的最终消息就是汇报。说清：做了什么、改了哪些文件、验收标准是否达成、有无遗留、下一步建议。
5. **环境约束**（踩过的坑）：
   - pypi / github 用清华镜像；Clash 代理 `127.0.0.1:7890` 拦截东财 → 全局 `trust_env=False`。
   - 东财 push2 / clist / 板块端点反爬封 → 用 sina 源或直爬 + `em_get` 防封（1s 节流 + 0.1-0.5s jitter + HTTPAdapter Retry 429/5xx）。
   - 手动值保护：upsert 的 `ON CONFLICT DO UPDATE` 末尾必须 `WHERE daily_metric.source != 'manual'`（防日采集覆盖手动补录）。
   - NaN 过滤：`collect_series` 里 `if v != v: continue`（`float(NaN)` 不抛异常，必须显式判）。
   - 不要 `cd` 进 compound 命令（用绝对路径）；不要 commit / push（用户没让）。
6. **验收（2026-07-06 调整）**：监管**不自己跑命令验收**（curl/grep/DB 在监管上下文费 token）。改派**验收子进程**（fresh context）跑抽查（DB/curl/复跑/语法），结论写进任务条目「验收备注」+ 向监管汇报。监管读干活汇报 + 验收汇报决定放行。review gate 任务必派验收子进程；非 review gate 可省（信任干活子进程自验）。不暂停等用户，全部完成或卡住才通知。最终用户 + 外部测试整体验收。详见记忆 `supervisor-loop-mode`。
7. **测试**：API 改动用 `curl localhost:8000/...` 验；采集改动跑 `python -m app.collector.runner`；计算改动跑 `python -m app.compute.runner`；前端改动浏览器看。

---

## 归档/远期指针（4 态/4 文件流转,不占活跃区）

> 4 态 ↔ 文件(2026-08-20 用户定):①活跃→TASKS.md ②待办/远期→docs/pending-features-index.md ③**完成→docs/tasks-done-list.md** ④归档→docs/archive/(完成态呆满 7 天自动归档)。

- **真完成(完成态,待 7 天自动归档)**：43 条 → [docs/tasks-done-list.md](docs/tasks-done-list.md)「2026-08-20 任务治理移入」段(含飞书群处理/全球指数/accum_nav 前复权/费率前端/全站性能 P0-P1/降亏组合全信号表等逐条,呆满 7 天自动移入 docs/archive/TASKS-done.md)。
- **用户关闭(移除留记录)**：3 条(NIFTY50 / 159536 track_score / avg_dev)→ [docs/archive/TASKS-done.md](docs/archive/TASKS-done.md)「2026-08-20 任务治理归档段」。
- **远期/搁置(移 pending-index 模块十六)**：场外方案C 全量化（#79,step1-8 逐条）→ 性能 P2-10/11/15（#80）→ 场外阶段2/3（#90）。（管理端看板 #81 已于 2026-08-20 用户拍板关闭,勿再列远期;旧 memory kanban-board-design 待同步为已关闭）
- **8 项被归档活跃需求(pending-index #82-89)**：留言箱完整方案 → ETF485 扩采+OHLC → 公募基金筛选器实战版 → 板块轮动 → 真pin 复盘 → PWA 体验增强 → 订阅推送 → overlap delta 可比口径。
- **早期历史归档(留反查)**：[docs/archive/TASKS-history-archive-20260820.md](docs/archive/TASKS-history-archive-20260820.md)（07-21~08-16 旧交接/旧需求章节）+ [docs/archive/TASKS-done.md](docs/archive/TASKS-done.md)（07-06~07-20 交接 + 22 任务全 done + 综合AI风险预警）。

---
## 2026-09-03 Codex Watcher 修复（by Codex）

**问题**：7x24 自动外审链路断，原因两层：
1. `codex exec` 在 launchd 子进程中被 macOS 沙盒 App Sandbox 阻止（exit=127: `env: node: No such file or directory`）
2. `report_is_fresh()` 用错误的 mtime 方向检查（报告 mtime 永远 ≤ signaled_at，正确性必然误判）
3. claim 类型没有 review schema 的 `issues`/`impact_surface` 字段，但代码对所有类型强校验这两个字段

**修复**（已部署生效）：
- `call_openrouter_codex()` 直调 OpenRouter HTTP API，绕过 `codex exec`
- `report_is_fresh()` 去掉 mtime 检查，改为 `request_id` + `verdict` schema 验证
- `HEARTBEAT_PATH` → `/tmp/agent_inbox_watcher.heartbeat`
- plist log 路径 → `/tmp/codex-reports/agent-inbox-launchd.log`
- plist 重命名 `com.trade.codex-watcher`，替换旧的 `com.trade.agent-inbox-watcher`
- launchd PID 31774 已在运行（21:20 重启）

**git commit 准备**（沙盒写锁无法完成，待 Claude Code 用 merge 流程处理）：
- `scripts/agent_inbox_watcher.py` (141+ 行修改)
- `scripts/com.trade.codex-watcher.plist` (新 plist)
- `scripts/install-codex-watcher-launchd.sh` (日志路径修正)
- `scripts/com.trade.agent-inbox.plist` (删除)

**pending 外审信号**（CLAUDE 回消费）:
- `rev-20260903-001.done` → v1.1.14 review, PASS，schema 已补全 issues+impact_surface
- `claim-20260903-001.done` → 孤儿文件认领 PASS，所有文件确认归属或不存在
