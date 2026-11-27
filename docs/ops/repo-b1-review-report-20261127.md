> 归档自 /tmp/repo-b1-review-report-20261127.md,2026-11-27;原始路径为临时文件,本副本为持久归档

# #384 批1 独立审查报告(REPO 数据根单源)

> 审查人:reviewer agent(2026-11-27;本会话文件写入工具被禁用,由主控代落盘,正文为 agent 交付原文)
> 审查对象:`feat/repo-unify-b1-20261127` @ `7c8a3d52c`(base `192691ab3`,3 文件 +237/−22)。只审不改;未推 main;云上只读。

## 0. 结论
PASS(可 merge,附 1 项报告订正):阻断 0 / 必改 1 / 建议 6。

## 1. 尺子先验(§10.0,尺子验证行)
- 被审模块真实性: `git archive 7c8a3d52c scripts` 解到隔离目录,md5 与 git blob 一致(`57ad19b73bf2289768084ac7c5d9669f`)。
- 打桩生效证明:双树错配 smoke 中桩先打印 `STUBBED: ✗ 写部署源树目标错误...` 才 SystemExit;用例内 `assert fired` 证明确经桩函数。
- 样本真实性:云上布局/unit env/日志/库 mtime 全部只读实测(`readlink -f`、`systemctl show -p Environment`、日志锚点),非按设计转述。
- 零外发:告警台账 `防再犯E守卫` 计数全程恒为 1(仅 2026-11-27 14:05:43 设计阶段已登记事故),实施自测 + 本次 14 用例 + 8 组变异 + 6 组 smoke 前后零新增。
- 变异在 `/tmp/mut_*` 隔离副本跑,未碰 repo/生产数据。

## 2. 冻结核对(§3 / 重点 2)
`candidate_repos()`/`pick_repo()`/`guard_deploy_source_tree()`/`_is_single_repo()`/`force_env()`/`main()`/`_alert_guard_blocked()`/`_read_overview_date()` 与 main 逐函数 AST 一致(`pick_git_repo()` 仅委托 `code_root()`,语义等价;`sentiment_db()` 仅默认根换 `data_root()`,显式 repo 分支逐字未变)= 冻结面零破;`GIT_REPO_DEFAULT` 值等价(`CODE_ROOT` 同一表达式),`candidate_repos()` 仍消费旧名;`pick_git_repo()` fallback `CODE_ROOT.resolve()` 与旧值语义逐位等价。其它文件零改动。

## 3. 五场景逐项对账(§2.1)
| # | 场景 | 独立验证 | 结果 |
|---|---|---|---|
| 1 | Linux 形态无 env(D/scripts→C/scripts) | 自建云上形态布局 smoke | 绿:MAIN_REPO/data_root/sentiment_db/pick_repo 全 = D |
| 2 | REPO=C + 独立 D | 同上 + 打桩 | 绿:桩触发后 SystemExit,文案含「解析到 git 仓」「而非部署源树」 |
| 3 | REPO=D(现网) | 本地 smoke + 云上只读 45 service | 绿:全 D;fof 仅 REPO 无 GIT_REPO 守卫早退;sim-trade@ 不导 pick_repo;ops-monitor 走自有解析;日志锚点 db=D |
| 4 | MAIN_REPO 默认派生 | 双树/单仓/标准检出/worktree | 绿(措辞订正 F1):兄弟树=D、单仓=C、标准 mac=D、worktree=工作树根 |
| 5 | `sentiment_db()` 5 处读者 | 全仓 grep + 逐处判入参 | 绿:仅 `brief_ledger.py:111` 用默认;其余 5 处全部显式 Path,拼接不变 |

## 4. L48 打桩核查(重点 3)
3 个能触达守卫的用例全部 `_stub_alert`(monkeypatch `pick_repo._alert_guard_blocked`):`test_env_repo_data_tree_wins`(断言 `fired==[]`)、`test_env_repo_code_repo_two_tree_raises`(断言 `fired`)、`test_single_repo_repo_equals_code_root_ok`(`fired==[]`);其余 7 个用例与 test_383 四用例均不触达外发。未打桩触发面 = 0;台账实证见 §1。

## 5. 变异判别力(重点 5)
M1 关候选 A → 14 passed(未判红,测试缺口 F2);M2 去 `is_symlink` 前提 → 未判红(等价变异,第二前提在 `__file__` 同源下无差);M3 去守卫、M4 `sentiment_db` 回落旧根、M5 MAIN_REPO 回 mac 字面量、M6 去兄弟候选、M7 `code_root` 忽略 GIT_REPO、M8 去 env 分支 → 全部判红。

## 6. 边界独立复核(§10.8)
自己先推一份边界清单,与实施方对账,差集 10 条(D1-D10),逐条已处置,无静默吞:
- D1 `data_root()` 无 env 端到端单测(审查方 smoke 已覆盖,建议补)
- D2 env REPO 相对·非目录·空白走派生(继承语义,显式不测)
- D3 MAIN_REPO 指向不存在路径可旁路守卫(pre-existing,上报)
- D4 `data_root()` 不认 MAIN_REPO(今日生产零触发,批3/4 收口)
- D5 返回归一化不一致(env 分支 resolved、派生分支 unresolved,实测 `/private/tmp` vs `/tmp`,批2 conformance 隐患)
- D6 worktree/非标准布局(必改 F1)
- D7 迁移期双实现并存(`app/db.py` 等,确认批2/4 排期)
- D8 CI 独立断言面(已核 `ci.yml:189` 与 `ops-monitoring-checks:201` 均跑全量,`smoke_local.py` 无硬编码断言,无差)
- D9 时敏用例(新用例零日期逻辑、faketime +45d 双跑无依赖,无差)
- D10 读侧复用写侧告警文案且无 dedup key(pre-existing,批2/3 顺带)

## 7. Findings(≥80;每条带 trace/verifier)
**F1 [必改,90] 行为变化标注不准确**
- trace: `scripts/pick_repo.py:71-76`;实施报告 §4.3 与设计 §3 称「mac 上取值完全相同」;linkage=不满足(§23.7 行为变化须如实标注)。
- 证据:实施报告自己的 smoke W 打印 `MAIN_REPO=/Users/linhuichen/code/trade/.claude/worktrees/agent-aad343...`(≠ 旧 `/Users/linhuichen/code/trade-data`);机制=worktree 的 `code.parent` 无兄弟 `trade-data` → 回退代码根(设计 §4.1-2 已知限制,与报告措辞矛盾)。
- 影响:仅开发侧;生产 45 service 显式 REPO 不受影响;worktree 裸跑读者读工作树(响亮报错非静默),写侧 `static-site/data` 已 gitignore 不脏 git。
- verifier: worktree 内 `env -u REPO -u GIT_REPO -u MAIN_REPO python3 -c "import pick_repo as p;print(p.MAIN_REPO,p.sentiment_db())"` 期望=工作树根;标准检出期望=`/Users/linhuichen/code/trade-data`。

**F2 [建议,100] 候选 A 用例不可判别**:`test_384_data_root_contract.py:46-49` 布局里 D 名就是 `trade-data`,A/B 同解;变异关 A 仍绿。修法:把 A 用例数据根改名(非 `trade-data`),改坏 A 分支应变红。

**F3 [建议,90] `data_root()` 归一化不一致**:`pick_repo.py:139-144`;env 分支经守卫必 resolve,派生分支未 resolve;mac `/tmp` 实测同一目录 `pick=/private/tmp..` vs `data=/tmp..`;批2 跨实现 Path 相等会假红/假绿。修法:派生返回值统一 `.resolve()`(A 前提判定仍用未 resolve 路径)。

**F4 [建议,85] `data_root()` 忽略 `MAIN_REPO`**:`pick_repo.py:127-144`;设计与旧代码把 MAIN_REPO 当数据根别名,读者入口不认;今日生产零触发(45/45 有 REPO)。处置:设计登记 + 批3/4 收口,或加 MAIN_REPO 兜底(须同一守卫)。

**F5 [建议,85] 读侧守卫文案+无 dedup key**:`pick_repo.py:167-182,201-228`(冻结面,本批未动);读路径触发时报「写部署源树目标错误」误导排障;`notify.py` dedup 窗仅在传 key 时生效,同一错配每次触发新发 critical;今日零触发。批2/3 顺带。

**F6 [建议,100] `test_383` 文档字符串陈旧**:`test_383_sentiment_single_root.py:7,11` 仍写 `(repo or pick_repo())`/「跟随 pick_repo()」,契约已改 `data_root()`;随批订正。

**F7 [建议,流程] pending 索引状态未同步**:`docs/pending-features-index.md:557` #384 仍「待办(远期;待用户拍板)」,批1 已实施待审;按 §23.12-1 更新状态列。

另 3 个低分项(<80)已滤:断言绑实现细节(`"_DERIVED_DATA_ROOT" in src`,50)/ M2 等价变异(50)/ env REPO 异常取值未单测(继承语义,50,转 tester 边界穷举)。

## 8. 全量回归(诚实标注,按 L56)
- feat 首跑: **1 failed, 5600 passed, 6 skipped, 176 subtests, 742.32s**;失败=`test_codex_handoff.py::test_real_multiprocess_publish_ack_races_do_not_reset_receipts`(8 并发子进程中 1 个 `codex_handoff: FileNotFoundError`)。
- feat 复跑: **5601 passed, 6 skipped, 176 subtests, 728.01s(全绿)**。
- main 基线全量: **5591 passed, 6 skipped, 176 subtests, 741.63s(全绿)**;feat 比基线多 10 个 = 新增用例。
- 判别:`test_codex_handoff.py` 整文件单跑 53 passed、与新用例同一次调用 67 passed;该文件与 `codex_handoff.py` 在本 diff 中零改动且不 import `pick_repo`。据此判定=无关子系统的并发竞态(源码未变、行为不确定),**不是批1 引入的缺陷**;按 §10.3 误报清单第 1 类走上报通道:建议单开任务加固该多进程用例(不复用"flaky"话术放过,计数原样保留如上四组数字)。

## 9. 其他规范面
- §21 算法公示:不适用(路径基础设施,无算法口径;前端零改动)。
- §22 多展示位一致:不适用(不产用户可见数据);数据校验(check_data_integrity/check_r2_consistency)按职责切割归 tester,本报告未重复跑。
- §24 前端防撕裂:不适用(无前端/SW/版本串)。
- §14:本批无定时任务改动;建议 merge 放 23:00 后安全窗口;上线后观察锚点=一个完整交易日后 `daily_brief.log` 的 `[brief_ledger] repo=` 仍 D 且 journalctl 无 SystemExit(§9.7 第二数据点)。
- §23.2/§23.3 同类面:`app/db.py`、`check_data_integrity._db_candidates`、`check_s06_freshness`、`simtrade_export_publish.sh` 由设计批2/3/4 承接(D7 上报)。

## 10. 诚实标注
- 云上 unit 首轮「文件 grep」误判 43 个 REPO=C,已用 `systemctl show -p Environment` 复核纠正(自纠记录保留)。
- 未做云上部署/上线验证、未跑 curl 数据层三查(tester 职责)。
- 临时 worktree `/tmp/review384wt`、`/tmp/base384wt` 及全部 `/tmp/mut_*`/smoke 副本已删除并 `git worktree prune`;主仓工作区干净、仍在 `main`,零代码改动、零推送。
- 全程无残留后台任务(两轮全量 pytest 均已结束,pid 已核无)。
