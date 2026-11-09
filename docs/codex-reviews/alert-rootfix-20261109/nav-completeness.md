# FOF/QDII 净值补采：窗口完整性与公平续跑

日期：2026-11-09。用户特批 Codex 在独立树实施，Claude 独立审查、合并、部署。
基线：`e353220e4b400941ae8134d35105b242de1a13bd`；分支：`codex/ops-fof-nav-completeness-20261109`。本轮只处理 NAV，不动 overfit、共享索引、策略、前端或调度。暂不 push。

## 实测依据与预期

只读诊断证明 016989 在库内 Nov2=1.1404、Nov3–6=NULL，前端实际读 `nav_bucket/5c.json`，最后只有 Nov2。采集器用「窗口内任意非空」把整只基金列为已填。Nov9 21:10 自然任务确实跳过这类基金；不是上游没有发布。

现有同一路径 `https://api.fund.eastmoney.com/f10/lsjz?fundCode=016989&pageIndex=1&pageSize=20&startDate=2026-11-02&endDate=2026-11-09` 的只读响应 ErrCode=0，包含 Nov3=1.1298、Nov4=1.1631、Nov5=1.1713、Nov6=1.1540。原始响应 SHA-256：`b62cb46a4810e799ff0f91d17d4aadfa966c81468ce7074656048a7ad628cff4`。完整小响应嵌入新测试，已与原始 JSON 逐字段对账；测试运行不请求该网址。

预期：旧非空值不改，NULL/缺行按真实 API 值补入；空响应正常；即使前500只一直空或异常，后批也能触达，进程重启仍可续跑。不能用库中零星值断言上游整窗完整。

## 实现与边界

删除错误的 `filled` 推断，按基金代码轮转复查全部 FOF/QDII；一轮硬上限500。跨日保留位置，不因7日窗口移动重头开始。`--limit` 保持调试取前N只且不读写轮转位置，同样最多500；非正 batch/limit、负 days 在访问库前拒绝。

进度为实际 SQLite 文件旁的 `public_fund.fof-nav-progress.json`，仅 `version=1,last_code` 两项；通过 `PRAGMA database_list` 绑定真实连接路径。复用 `scripts/util_atomic.py:atomic_write_json`，不建状态框架或新数据库表。原 `public_fund` 锁覆盖选批、单只写入、进度。每只提交 NAV 后才原子记尝试位置；合法空和错误也推进。断在提交与记位置之间只会安全重放该只。游标不代表成功，更不代表窗口完整。

缺文件从头开始；损坏格式明确告警后保守重查；游标基金被移出池时仍能按代码继续。写进度失败非零退出，旧原子文件保留；可恢复上一份同名完整进度，或在停采持锁时备份后移走该文件让下一轮从头检查，不删业务数据。无需假造历史进度。

只复用原 `UPSERT_SQL` 的库值优先 COALESCE。单只写失败照旧 rollback，不污染下一只。API 的未发布净值跳过，不制造 NULL 占位。合法空/混合成功/全异常的 F01 `error_count` 与退出判据不改；只更新不再成立的“已填”日志措辞。dry-run 不初始化、建库、迁移或取得写连接，使用 mode=ro + query_only，且不读写真实进度。

这保证有界尝试公平性，不保证一次采满窗口；长期上游异常、份额类清理、定开识别与旧7日窗以外历史仍是 #333 批2/3剩余项。没有借此改变披露规则或扩大历史补采范围。

## 实际验证

命令前缀：仓库根执行 `/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q`；每个调用有40秒硬上限，子进程重启测试有15秒上限，所有测试会话均已退出。

- 修前，仅新测试 `test_real_016989_null_and_missing_rows_are_repaired`：`1 failed in 1.95s`；原逻辑日志已填跳过=1，NULL没有补。
- 修后授权范围：`-m 'not network' scripts/tests/test_fof_nav_completeness_20261109.py scripts/tests/test_collect_fof_nav_333.py scripts/tests/test_fof_nav_p2c_rollback.py`：`33 passed, 1 deselected in 1.72s`。deselected为原有真实网络用例，未执行。
- 扩展加入 `scripts/tests/test_collect_fof_nav_366_batch_signal.py`：`2 failed, 45 passed, 1 deselected in 1.64s`。不是全绿，失败未删计数。
- 两个隔离变异反证：去掉非空保护，`1 failed in 0.11s`；去掉进度持久化，`1 failed in 0.68s`。均仅修改测试进程中的函数/SQL，源码未临时改坏，证明两类守卫测试可判别。

两个扩展失败属于未授权写入的既有 F01 测试文件：

1. `test_legitimate_empty_no_false_alarm` 在一日非空后断言绝不请求 API，本身编码了本次已证实的错误。需改为真正“目标池为空”的退出守卫；部分窗口重查已在333测试覆盖。
2. `test_dry_run_all_fail_no_signal` 的 fixture 只替换 `get_conn`，新 dry-run 故意不用写连接；需把同一个临时库赋给 `mod.DB_PATH`。当前在不存在的开发树路径只读打开失败，没有建库或生产写。新增测试已独立验证真实只读连接、全异常正常/探测契约。

初次提交按当时写范围保留该366文件原样，原始失败证据保留。父随后核工作树归属并明确放行：本次只增加 DB_PATH 临时库隔离，把无待采样本改为真正非FOF/QDII池；保留skip用例、called/n/LAST_BATCH_FAILED断言，以及其他合法空响应、真异常和exit核心断言。未改rollback测试或共享conftest。

## 同类面与七轴

复用与范围核对：#333 索引已明确登记“全填才跳”差集，#366的error_count修复已发布；本轮不覆盖份额清理/定开识别/历史回填。`run_fof_nav_collect.sh` 为单一自然入口；库下游仍是既有导出桶/评分/风险消费者，无字段和算法变动。共享索引与其它作者文件均不写。先复用现有连接、锁、UPSERT、原子助手；不新增抽象层。

| 轴 | 本轮验证 |
|---|---|
| 输入域 | 真响应、NULL与缺行、未发布占位、合法空、异常 |
| 状态组合 | 非空不覆盖、无目标、锁忙、损坏进度、原子写失败、幂等 |
| 时序 | 1001只三批、跨独立进程重启、日期窗口移动、游标基金移除 |
| 上下游 | 真API解析到临时SQLite；原F01 main 0/2；生产导出/上传未执行 |
| 极端值 | 默认500、batch/limit超500硬限、零/负参数拒绝 |
| 回退路径 | 缺/坏进度重查，单只rollback，进度失败后重放 |
| 并发与重入 | 复用现有public_fund锁；锁忙无初始化/进度写；真实双进程锁竞争未新增实测 |

## 未执行与合并条件

未采集真实数据、未执行生产脚本/云写/通知/导出/上传/重算，无GB下载。本次网络入口在测试中打桩，新增沙箱测试还禁止TCP连接；独立子进程也只操作同一临时库。生产016989尚未由本轮修复。

标准 pre-commit 不绕过；实际结果见最终 JSON 与提交日志。暂不 push，未合并部署。全量 `scripts/tests/` 与 Linux 整合由父在独立审查后执行，未在本轮冒充完成。父还需核新的进度文件写权限与后续自然轮次，按 DB→桶→公开值验证真实生效；两个旧F01测试已在父授权后同步，本地受影响回归通过仍不替代父独立review和Linux整合。


## 父授权续改与受控恢复入口

追加提交保留 `5253511a2711f1dc4a62f41125c14031dcf4310d` 为祖先；本次组合回归原末行：`59 passed, 1 deselected in 1.81s`。测试包含真实016989响应、1001候选的前批空/错误与独立Python进程重启、跨日轮转、定向入口和F01原退出契约。真实网络用例仍未执行。

已核现有CLI：`collect_fof_nav.main` 原有 `--days`/`--limit`/`--batch`/`--dry-run`，支持回看14自然日，原先没有定向参数；`run_fof_nav_collect.sh` 只运行 `-m scripts.collect_fof_nav`，不转发参数，不能向该包装脚本随意追加参数。另一个 `app.collector.public_fund backfill-nav` 会先刷新三指数再采头部基金，不是这次单只只补空恢复入口。

新增兼容参数 `--fund-code`：严格6位ASCII数字，仅查询既有 `SELECT_SQL` 的FOF/QDII宇宙。先用 mode=ro/query_only 核目标，再取写连接；非目标直接跳过，无初始化/写连接/API请求；非法输入在锁和库前拒绝。只有目标存在才使用原COALESCE写入。定向操作不读写全局游标，不影响默认轮转；无参数时行为保持525版本。`--days 14`沿用原“today减14日到today，两端包含”的语义；固定Nov9测试实际请求Oct26至Nov9且仅016989一次API。

以下是**部署此追加版本后由Claude执行的入口**，本轮未在云上执行。依据是现有包装脚本的Python路径与本次真实argparse/只读连接/真响应沙箱回放，不是伪造一个未实现的命令。工作目录必须为DATA树，因为 public_fund.DB_PATH 根据导入模块的绝对路径选库，不能仅在CODE树设置REPO就假定读到实时库。

在 `/home/ubuntu/code/trade-data` 工作目录，先预览：

```bash
REPO=/home/ubuntu/code/trade-data GIT_REPO=/home/ubuntu/code/trade-data-signal timeout 45s /home/ubuntu/code/trade-data/.venv/bin/python -m scripts.collect_fof_nav --fund-code 016989 --days 14 --dry-run
```

核输出日期窗口仍包含2026-11-03至2026-11-06、目标只有016989，再于现有安全时段/同库任务空闲时执行同一入口去掉dry-run：

```bash
REPO=/home/ubuntu/code/trade-data GIT_REPO=/home/ubuntu/code/trade-data-signal timeout 45s /home/ubuntu/code/trade-data/.venv/bin/python -m scripts.collect_fof_nav --fund-code 016989 --days 14
```

dry-run的written是本次API有效行计数，不表示已落库；正常写入重放也可能返回同样计数，不能用它证明新增数量。该命令只补当次窗口内API真值，不承诺仅修改四个日期；已有非空值永不覆盖，也不伪造API尚未返回的日值。如果日历窗口已移出已知缺口，停止使用此固定命令，先重新核日期与API分页边界，不凭空补日期参数。

只读复核真实DB的已知小窗口：

```bash
timeout 15s sqlite3 'file:/home/ubuntu/code/trade-data/data/public_fund.db?mode=ro' "PRAGMA query_only=ON; SELECT date,unit_nav,acc_nav FROM fund_daily_nav WHERE fund_code='016989' AND date BETWEEN '20261102' AND '20261106' ORDER BY date LIMIT 5;"
```

在本轮已取得的真实响应下，Nov2应仍为原值1.1404，Nov3–6应分别为1.1298、1.1631、1.1713、1.1540；若上游随后真值有修订，记录新响应与差异，不能用本报告旧数覆盖已有非空。还须等既有导出/上传自然链更新 `nav_bucket/5c.json` 后复核公开内容；本定向入口不导出/上传、不通知、不刷新指数。锁忙的跳过或exit0不能替代DB逐值验收。


## Kepler固定24d发现P2：锁文件非截断修复候选

Kepler独立review在固定 `24d05c2d2b39ab4cde3e7a65423edad0725e777d` 指出：NAV dry-run调用共享 `app/collector/public_fund.py:_acquire_lock`，该函数先 `open(lock_path, "w")`，后尝试flock；因此即使锁忙失败，真实锁文件已有内容也已截断。此前数据库/游标不变的测试把锁helper打桩，不能证明锁文件不变。本节保留此发现，不改写旧报告结论或将其提前关单；待Kepler固定24d完整报告及后续复核。

按本轮授权，仅在共享helper把打开模式改为 `"a"`，竞争失败显式关闭新句柄。保持原 `data/<lock_name>.lock` 路径、public_fund/public_fund_stage0两个既有锁域、LOCK_EX、非阻塞LOCK_NB/阻塞参数、锁忙返回False、成功句柄留在_LOCK_FILE持有至进程退出的合同。没有新增锁实现、锁文件、参数或锁域，也没有让预览绕过生产互斥。此单点修复同时使既有正常采集入口保留协调文件内容。

**dry-run的准确边界**：数据库内容和游标只读；仍取得既有排他协调锁。已有锁文件非截断打开，不改其内容或inode；不存在时允许在原路径创建一个空的协调文件。因此不是“整个文件系统完全只读”，仍需要既有锁路径可打开/创建的权限。该创建只是协调元数据，不是NAV写入、游标推进或完成证明。

新测试 `scripts/tests/test_fof_nav_lock_nontruncate_20261109.py` 使用真实共享helper，临时库/目录和真实独立子进程flock，绝不在生产目录创建或改锁：

- 已有sentinel的预览：内容/inode、数据库和游标逐字节不变；预览持锁时正常竞争者失败，释放后可取同一个锁。
- 独立进程持锁时，dry-run和正常调用都非阻塞跳过，不截断sentinel，不初始化/读写业务库/请求API，F01状态正常复位；子进程全部有界回收。
- 锁不存在的预览只创建空协调锁；业务库/游标内容不变；持锁期间同域竞争仍失败。
- stage0既有锁域同样保留sentinel，未混入public_fund锁域。

修前新测试原末行：`4 failed, 1 passed in 1.04s`。修后锁专项加完整NAV/F01受影响组合原末行：`64 passed, 1 deselected in 2.62s`。真实响应预览、1001候选公平续跑/独立进程重启、NULL/缺行、非空守卫和原F01退出合同都包含在该组合，真实网络用例未执行。命令均受40秒上限，子进程竞争/释放受5秒上限。

旧 `nav-implementation.json` 与已被review引用的红日志均保持原字节；本次另写 `nav-implementation-v2.json`、`nav-v2-lock-before.txt`、`nav-v2-lock-after.txt` 和新提交日志。通过开始时记录的SHA-256复核旧NAV报告/日志未变，不覆盖Kepler发现。完整全量/Linux、真实云上锁文件/恢复命令未执行；本轮仍未push或部署。
