# HC07 公募增量与长期 NULL 补采

本组基于 `0ad543ef41758be9d7102b42471489b24d0cb989`，在 `codex/ops-fund-incremental-20261111` 实施。依据本轮用户业务实施授权；未修改角色规范、协调 README、pending-index、原交接 packet。待父任务整合、Claude 独立复核和部署，本文不是生产恢复声明。

## 已复现与实际改动

基线隔离反例：45 条源历史只得到 20 条；运行日固定为 2026-11-09，2026-09-01 的真实 NULL 行即使源有值也未被近7日窗口请求。实施前原始末行 `2 failed in 2.33s`，日志 `/tmp/codex-reports/ops-backlog-20261111/fund/before.log`。已有 016989 回放只用来验证兼容，不用它证明7日窗外问题。

- `scripts/collect_fof_nav.py:fetch_lsjz` 完整分页，校验总数、页号、每页应有行数、日期降序/去重/范围。任何缺页、重复页、分页期间总数漂移、缺覆盖元数据都拒绝整只基金。prevNAV 在拼齐页面后取紧邻前条，不能在页边界掉失。
- 正常 FOF 轮转复用原 `version=1,last_code` 文件，不重造轮转。首次历史每只每轮向前核实366日，直到1990-01-01；历史覆盖未完成时保留明确 `history_before`，不会把一年的数据称全史完成。日常从最后有效日回看原有7日；该7日是沿用值，未声称已用生产修订延迟统计调优。独立 NULL 队列使旧 NULL 不依赖回看窗。
- `public_fund_gap.py` 用三个兼容新表保存历史覆盖、按目标/日期/字段的 NULL 待办、冲突 before/after/来源/观测时间。每目标最多发现64个 NULL 日期、处理64个字段任务，持久扫描位置轮转；纯空重试增加尝试数，不标为修好。上游未公布的日期不制造行或净值。历史空段只代表源查询完整，不表示每天都有值。
- FOF NAV、覆盖进度与缺口队列在同一个基金事务内提交。写前检查本基金所有响应中的非空冲突；有冲突则所有业务字段和新日期一起拒绝，只另存冲突审计。真实异常也回滚；已尝试基金即使超时也推进尝试轮转，成功覆盖状态仍回滚。尝试游标不证明采集成功，前面完成的基金保留。
- `public_fund.py:fetch_index_daily` 保留 HC06 隔离 SDK 查询、重连、父死亡回收及统一 monotonic deadline。默认首次完整读取400日；之后按最后有效日、上下文和旧 NULL 集合选范围。历史下界包含既有更早数据，不删旧数据来凑对照。多个范围在提交前统一检查冲突并原子写入；显式起止日期的旧调用仍支持，新增参数为可选 keyword。
- 日更 `fetch_daily_nav` 的快照选择/NULL保护、`fetch_nav_history` 的显式历史回填及 stage0 原调度不变。本次增量入口是 FOF 与基准指数，未改变评分或前端算法。

## 预算、索引与只读边界

FOF 一轮默认/上限290秒，分页和单次 HTTP 共用绝对截止；HTTP另限15秒，慢滴流也受墙钟限制。SQLite busy_timeout/进度回调继承剩余时间。没有扩大日更外层300秒，没有修改 runner、timer、信号、通知、D1、R2 或部署脚本。历史初始化会跨轮推进，不能承诺每轮仍完成500只；500是原尝试数上限。

发现 NULL 强制使用既有 `idx_daily_nav_code` / `idx_fund_index_daily_id`，缺索引即失败；不在采集轮内构建大表新索引。隔离测试向其他基金添加20,000行后，目标查询的 SQLite 指令工作量不增加，EXPLAIN明确走目标索引。仍会检查本轮目标自身历史，未声称 SQL、HTTP 数和费用均按日期跨度同比下降。

严格 dry-run 不创建 DB、状态、游标或锁文件。已有锁以只读打开，继续互斥且不截断。数据库使用 immutable 静态快照，并检查前后身份/大小/时间；存在未合并 WAL 则明确失败，不能悄悄忽略 WAL。此模式要求已checkpoint的静态副本，不负责对活库执行 checkpoint。负控证明原 `mode=ro` 会创建 WAL/SHM；现已测试整个目标目录逐文件字节不变和 WAL拒绝。

## 测试与兼容失败对账

所有新增数据在临时 SQLite；网络请求、SDK、锁竞争进程均为隔离替身。真实016989固定响应沿用已有回放。没有真实 collector、生产DB访问、真实通知或生产源全量运行。最终组合回归额外封锁 Python socket.connect，REPO指向 `/tmp`。

原始日志全部保留，不覆写失败计数：

- `compat-first.log`：`44 failed, 107 passed, 1 skipped in 66.35s (0:01:06)`。包括旧 fetch 桩不接受新增 deadline keyword、旧假连接 `execute()` 返回 None；也包含真实集成问题，不能统称“测试过时”。
- `compat-second.log`：`7 failed, 158 passed, 1 skipped in 73.67s (0:01:13)`。修复迁移错误依赖 NAV 表、辅助模块提前导入影响隔离父进程退出；取消大表索引 DDL。新迁移重复执行且不提交调用者业务事务由真实 SQLite 验证。
- `compat-third.log`：`165 passed, 1 skipped in 55.03s`。
- `targeted-final.log`：`4 failed, 205 passed, 1 skipped in 59.58s`。新增查询测试错误地只种 unit_nav 却声称无NULL，已补齐其余字段；真正抓出的 dry-run 辅助文件写入已修。旧锁“缺文件创建空元数据”与本次严格零写要求冲突，明确改为不创建；已有锁互斥与内容不变断言保留。

旧测试调整仅分三类：mock接收真实新增keyword；假连接改为真实SQLite；本次用户授权的冲突整基金拒绝/严格dry-run语义。原“005827=1.5、源=1.2”冲突种子保留，现强断言整只拒绝、其余字段不填且审计存在。原 SQL中途失败/截止回滚测试改用与源相同的旧行以实际到达注入点；冲突本身另有独立 before/after 与零半写断言，未放宽回滚要求。

最终组合回归原始末行：`214 passed, 1 skipped in 63.13s (0:01:03)`，见 `final-regression.log`；唯一skip为原有真实联网测试。完整 head 见父任务收到的本组报告。复现：`python3 -m pytest -q scripts/tests/test_fund_incremental_hc07.py`；兼容组合同时包含 `test_collect_fof_nav_333.py`、`test_collect_fof_nav_366_batch_signal.py`、`test_fof_nav_completeness_20261109.py`、`test_fof_nav_p2c_rollback.py`、`test_fof_nav_lock_nontruncate_20261109.py`、`test_fund_index_reconnect_20261109.py`、`test_codex_nav_stage0_retry.py`、`test_codex_fundnav_failed_targets.py`、`test_251_fundnav_col_bugfix.py`、`test_252_fund_nav_pct_20261028.py`。执行应设置临时 REPO、禁真实网络，整体timeout150秒。

## 边界与交接

整合独立复核 `ALPHA-HC07-01` 实际用本地HTTP复现了原版本的超时饥饿：每轮同一基金三页、整目标回滚，下一基金永远不被访问。原FAIL报告保留。整合修复将尝试轮转放到finally；同时沿原version=1进度文件添加可选work_limits，不另造成功游标。发生整轮超时的目标按最近数据/历史/缺口三阶段轮转，完整日期段及缺字段批量逐次减半（下限1），失败业务状态不推进。上下文最多向前7日，远处旧行不会把小片段重新扩成数年；缺前条时仍留NULL。历史初始化与NULL队列持续推进，不保存半页响应。

新回归保留原始首次夹具失败（假时钟缺time属性）；修正夹具后 `71 passed, 1 skipped in 2.52s`。确定性慢分页证明两基金都被尝试，24轮内两者各45条历史逐字段正确；64个稀疏NULL在预算内分段复查，合法空值仍是NULL，失败轮覆盖/队列不假推进。待独立复验和整合全量结果，不用这组定向测试代替上线自然轮。

七轴均有隔离用例：输入域（空、错误、缺元数据、重复/缺页）、状态（首次/有游标/历史完成/NULL/冲突）、时序（>7日迟报/重启/半批截止）、上下游（跨页prevNAV/真实SDK接口替身）、极值（>20行/500上限/预算耗尽）、回退（合法空exit0、真异常exit2、损坏游标复查）、并发重入（SQLite回滚、同锁排斥、重复运行、池增删）。全量/增量比较覆盖三指数全部字段及FOF全部存储字段，包含旧NULL恢复和原历史保留。

生产完整初始化、真实修订延迟分布、自然轮耗时与吞吐、上游未公布日期仍须部署后验证。这里只保证离线实现和所列用例，不虚报线上完成。全量 scripts/tests、合并点 CI、Claude审查、合并部署由父任务统一负责；本组不运行全项目测试或改其他组文件。回滚代码可回到base；新增三表与旧表兼容，可保留审计/进度，不能靠删除报告抹去冲突。
