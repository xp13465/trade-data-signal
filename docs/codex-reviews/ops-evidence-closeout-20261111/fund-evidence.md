# 公募 / FOF 当前轮次凭证实施交接

基线 `30df57e6bc20d15c7ec82c14c60626476ab7d622`。独立分支 `codex/fund-evidence-20261111`，worktree `/Users/linhuichen/code/trade/.claude/worktrees/codex-fund-evidence-20261111`。本任务只实施并离线验证；由父任务独立复核，Claude 审合部署。未改 root/main，未部署、运行生产采集或真实外发。

## 真实闭环范围

新增 `scripts/ops_fund_evidence.py`，复用 `delivery_evidence` 的不可变私有 receipt、`ops_business_evidence.record_result` 和有界 index。由既有 `OPS_DELIVERY_EVIDENCE_ENABLED=1` 开关控制，默认关闭。目录 0700、文件 0600；每轮开始/结束写入，无逐基金 fsync。

- **普通公募**：真实 `fetch_daily_nav` 的内存源表/待写行形成摘要；区分源异常、无数据但原因未分类、缺日期列、全部未公布、选择前一源日期、当日部分基金未公布。仅在 `conn.commit()` 返回后记录提交事实。`committed_rows` 是已提交输入中 unit_nav 非空的行数；`committed_statements` 是提交的 UPSERT 行数，包含 NULL 行，不是新增/修改行数。保留派生 prev/pct 前的源摘要和实际提交参数摘要。
- **日期**：receipt `session_date` 是轮次 `started_at` 按 Asia/Shanghai 推导的业务日期；`consumer_witness.fund_evidence.scope.selected_date` 是东财实际选中的 NAV 日期（YYYYMMDD）。`source_dates` 保留源日期列，`latest_column_unpublished` 表示回退。两种日期允许不同，不能把 T−1 源日期改标成今日净值。FOF 保留真实查询窗口和范围摘要，不把最近返回值标作今日。
- **FOF**：沿用 HC07 的分页、轮转、事务和冲突防护。保留所选基金完整列表、pool/selected/attempted/committed 计数、所选批次及池内未尝试数。定向复查的 pool 明示为 target_only，不冒充全池分母。逐基金 `outcomes` 保留源 published/legal_empty/error/not_observed 和持久化状态。计划 ranges、实际发起 range、完成返回 range 分别记账；前 8 个范围样本加全量有序摘要，未提供逐范围全量明文。合法空仅说明所查源窗口无可用值，不判定封闭或源应发布日。
- **失败/部分批次**：不改变原 collect 返回值、LAST_BATCH_FAILED 或 shell rc 语义。原来部分成功 rc0 时，凭证仍可记录真实异常；单基金回滚不抹掉先前已提交基金。新轮次、锁跳过和 shell 的当前 run ID 不沿用旧轮次完成事实。
- **持久化边界**：证明 UPSERT 参数在事务中提交，不是新增行计数、独立 DB readback 或完整 DB 快照。FOF 的 COALESCE 保留旧非空值，输入摘要也不冒充完整存量字段快照。单只已尝试/已提交、全局 MAX、游标和 backup-public_fund 都不证明 NAV 业务全量完成。

业务对象独立注册为 `public-fund`（trade-public-fund-daily.service）与 `fof-nav`（trade-fof-nav-collect.service）。`backup-public_fund` 仍是独立备份对象。监控仅投影 6 个额外标量：collection_state、publication_state、pool_not_attempted、selected_not_attempted、published_rows、committed_rows；测试实际调用 `ops_monitor.validate_snapshot` 且检查 evidence <=20 keys。完整批次私有事实由 offline `inspect_run` 保留；本次对该文件仅改 inspect_run，未改 plan/coverage。

## 预算与真实性

没有新增采集 API、DB SELECT、全库扫描、导出或 R2 网络请求。观察已有内存数据；内存摘要总计最多 0.5 秒，超预算/元数据异常标记 unknown，原业务返回和异常保留。FOF 的证据初始化时间扣入既有 290 秒绝对预算，采集过程中的摘要也消耗同一预算。公募原有 290 秒 pipeline、300 秒 shell 硬保护不变。复用私有回执的有限本地写入和 0.25 秒 index 锁等待，未增加网络或业务超时上限；不声称任意磁盘故障下本地 fsync 有硬实时保证。dry-run 不产凭证、不改生产数据。

## 发布层与父任务后续接线

**本实现没有 NAV publication success 路径**。采集全部提交也仍是整体 unknown；真实采集失败仍可为 failure。`assess` 和 `inspect_run` 不因伪造 success 标志、rc0 或备份回执而判公募/FOF full-success。

现有 R2 summary 类 JSON proof 不足以证明本轮逐基金 NAV 已进对应 NAV bucket 并已公开；FOF 独立入口本身也不发布。本任务没有扩大到 deploy/upload_r2。

父任务可协调后续范围：

1. 在 NAV exporter 使用已加载的基金/日期/值建立本轮 collection run 与实际 NAV bucket 输出字节的关联，保留业务范围分母与字段边界。
2. 从已有 exact-byte R2 proof / public readback 回执接续同轮/同代文件；明确 FOF 后续哪个正常 exporter 消费这些提交。不得以别轮成功覆盖当前未知或失败。
3. 消费公开确认时必须核对 run、输出集合、SHA256、size、业务日期及采集范围；处理 pending、部分确认和跨日关系。届时再增加 publication 成功判据，不能只把本模块的 unknown 改成 success。

普通公募“通常 T−1”、FOF T+1/T+2 与旧方案上线次日 ≥90% 预期按 existing-contracts.md 保留。本次不计算源保证完整率，不自造每日 SLA、历史完成日或 90% 上游保证。缺少逐基金发布/分母规则及自然轮实证的层仍 unknown。

## loaded identity 与运行接入依赖

父任务发现 canonical FOF service 不读取 .env；仅设置 .env 不会使该 producer 开启凭证。启用接线由父任务在 canonical 两个 service 显式配置 `Environment=OPS_DELIVERY_EVIDENCE_ENABLED=1` 并交 Claude 复核部署，本分支不改 canonical。部署后须核对实际 service 开关与 InvocationID；脚本仍默认 opt-in，dry-run 不写回执。开关与 manifest 是两个独立条件，启用开关不等于代码身份已验证或公开业务已完成。

`producer_identity(fn, root)` 使用现有 `delivery_evidence.loaded_code_identity`，把真实 producer 的函数全局、fund helper 函数和 `Round` 类方法纳入同一个 loaded module 摘要。helper-only 改动须改变摘要（有回归测试）。函数对象仅用于 introspection，不执行额外 producer；不读取 HEAD 冒充已加载代码。

Claude 复核部署后，须按真实运行入口/导入命名空间核验这些摘要并配置既有私有 `data/ops_delivery/producer-identity.json`：schema 为 `trade-producer-identity-v1`、reviewed=true、code_sha 为真实已审核的完整提交、loaded_module_sha256 包含经过复核的实际加载摘要。Python `-m` / `__main__` 和导入入口可能产生不同摘要，不能把另一个入口的摘要直接套用。可在隔离审核环境调用 `producer_identity(fetch_daily_nav.__wrapped__, root)` / `producer_identity(collect.__wrapped__, root)` 校核，再与自然轮回执的 code_identity.module_sha256 对照；仍须证明实际运行入口属于被审核的代码版本，不能仅复制任意 receipt 中的摘要作为授权。

缺失 manifest、摘要不匹配、代码未复核时 code_identity.sha 保持 unknown；监控不会接受 code_ref_mismatch。日更 shell 收尾保留 collector 的 code_identity，不替换成 CLI helper 的身份。InvocationID 也须与实际 service 匹配。即使身份齐全，publication 仍 unknown。26h 仅沿用证据有效期，不是新增业务 SLA。

## 离线验证记录

所有 producer 测试仅临时 SQLite / stub 源；启动 pytest 前禁止 socket.connect/DNS。网络测试仍默认 skip。shell 测试运行复制到临时目录的真实 public_fund_daily.sh，所有业务子命令为 inert stub，只调用真实元数据 CLI；未运行生产命令。

主要覆盖：日期回退和 NULL、源异常与合法空、commit 失败、非空冲突回滚、500/501 部分批次、超时已提交前缀、锁跳过与新轮次、dry-run/disabled、元数据预算与写失败、shell collect/deploy rc 和 NAV skip、伪 success 拒绝、私有权限、loaded identity helper 变更、独立脚本导入、实际监控 snapshot schema。原有公募/FOF/HC07 用例一并回归，保留已有退出码和游标行为。

原始 stdout/stderr 保存在 `/tmp/codex-reports/fund-evidence-tests-*.log`。首次回归的唯一失败是旧测试把业务对象数量写死为6，注册两个新对象后已更新为8，并验证公募/FOF/backup分别存在且 unknown。所有运行的原始末行在实施报告中列出，不隐去这次已修正的失败。`bash -n`、`py_compile`、`git diff --check` 另行执行。

原始测试末行（按执行顺序，保留复跑）：

```text
17 passed in 4.78s
1 failed, 191 passed, 1 skipped in 36.38s
194 passed, 1 skipped in 36.17s
195 passed, 1 skipped in 36.19s
54 passed in 2.94s
197 passed, 1 skipped in 36.19s
276 passed, 1 skipped in 69.19s (0:01:09)
3 passed in 0.77s
```

全部 fund/fof 回归范围为 `rg --files` 找到的全部 15 个同名测试模块，含 `test_fund_incremental_hc07.py`、原 AST 抽取用例及本次新测试；没有 decorator 导致的 globals 兼容失败。最后 3 项单独复核业务日与源日期不同、snapshot 实际校验及 <=20 keys 显式断言。跳过项为既有 network 用例，未启用真实外网。
