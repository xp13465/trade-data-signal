# Producer delivery receipts 与本地消费者接线

`scripts/delivery_evidence.py` 是 stdlib 元数据 helper。现有业务引擎、历史重算、冻结拒冻、上传和通知契约仍由原入口执行。本文件是持久使用说明；私有 review report 不是运行依赖。

## 开关、目录和预算

`OPS_DELIVERY_EVIDENCE_ENABLED` 默认 `0`，只有精确字符串 `1` 开启。关闭时 decorator 直接调用原业务函数，CLI 输出 `{"status":"disabled"}`、rc=0，不读证据或写 receipt。CLI 仍要求完整、显式的参数；`--help` 可直接运行。

`data_root` 指实际项目数据根，即包含 `data/` 的目录。固定位置：

```text
<data_root>/data/ops_delivery/
  producer-identity.json                    # 本机审核后的 loaded-code binding
  benefits-control.json                     # collector 审核后的交付合同
  receipts/<YYYY-MM-DD>/<chain_id>/<receipt_id>.json
```

`ops_delivery` 及 receipt 分区目录均须是真实的 `0700` 目录，receipt 为 `0600` 常规文件。helper 不替业务文件 chmod；既存目录过宽会产生可见 `metadata_failure`。receipt 采用同目录唯一临时文件、fsync、hardlink 独占发布、目录 fsync；同 ID 同内容幂等，不同内容拒绝，绝不覆盖原事实。reader 使用 `NOFOLLOW|NONBLOCK`、文件类型/权限/大小检查，FIFO 和 symlink 不能阻塞或充当证据。

单 receipt 上限 64 KiB；单 capture 最多 64 inputs、64 outputs、32 events、256 次 record、32 MiB hash 工作量；每逻辑对象最多 200000 节点，累计元数据工作时间预算 0.75s。预算不包含业务自身等待时间。超限停止后续采集并保留 unknown/metadata failure，不改变原业务结果或异常；stderr 已关闭也不能覆盖原结果。一个正在处理的对象另受节点/字节上限约束，时间预算在采集调用之间检查，不是抢占式执行 deadline。

collector 只读审核声明的近会话/链分区，每槽最多 128 facts、总计最多 256 facts/2 MiB；超过预算必须 `inventory_complete=false`，不能拿任意“最新若干条”证明完整。历史 immutable receipts 不删；20 会话比较使用既有持久化 observation 及审核窗口，不靠扫描全生命周期目录。详见 [benefits-contract.md](benefits-contract.md)。

## API 和身份语义

```python
emit_receipt(*, data_root, stage, chain_id, object_id,
    session_date="unknown", attempt_id="unknown", batch_id="unknown",
    stage_status="unknown", reason="unknown", inputs=(), outputs=(), counts=None,
    consumer_witness=None, code_identity=None, config_identity=None,
    producer_time=None, receipt_id=None, evaluated_at=None,
    evidence_quality="unknown", enabled=None, events=()) -> dict
```

返回 `status=disabled|written|idempotent|metadata_failure`，成功发布另有 `receipt_id`、`receipt_sha256`。`enabled` 只供受信本地配置/测试，不取远端输入。`read_receipt(path)` 仅验证 schema/文件，不批准业务成功。`iter_receipts(data_root, session_dates=None, chain_ids=None)` 可供指定分区读取；不指定条件的全档枚举仅用于离线审计，在线 collector 使用自己的有界 reader。

schema 为 `trade-delivery-receipt-v1`，必填字段：`receipt_id, chain_id, object_id, session_date, attempt_id, batch_id, evaluated_at, stage_status, reason, code_identity, config_identity, inputs, outputs, counts, consumer_witness`；另含 `stage, evidence_quality, producer_time, events`。

| 身份 | 含义 |
| --- | --- |
| `batch_id` | 稳定逻辑交付槽，默认 `chain_id:YYYY-MM-DD`；session 未知则 unknown |
| `attempt_id` | 实际进程/执行尝试，默认进程 UUID；已有 export run ID 可复用，嵌套阶段复用 |
| `receipt_id` | 每个阶段不可变事实，默认唯一 UUID；不能当批次或代际身份 |
| `session_date` | 明确交付会话；默认本次 Asia/Shanghai 日期仅是观测槽，不证明该日是交易日或每个市场输入已到齐 |
| `producer_time` | 实际 UTC started/completed；各 identity 的 observed_at 是本次观察时间 |

同日、同 batch、同 attempt 都不能代替输入输出代际证明。跨阶段必须核对真实 digest edges、required-set、时间与消费 scope。`arrival_at`、`first_visible_at` 缺观测就是 unknown；不能从当前文件、mtime 或今日 map 反造历史首次到达。七键不补冻、不恢复，不把次日 changed→appeared 当作原 arrival 或具体 backfill 因果。

## Typed pins：哪些 digest 可以比较

每个 identity 至少含 `object_id, sha256, size, identity_kind, quality, observed_at`，capture 会补 `session_date`。已知路径时附 `resolved_path`，SQL 附 `query_scope`/`snapshot_scope`。

| `identity_kind` | 实际内容 | 可否当源文件/DB pin |
| --- | --- | --- |
| `bytes` | 原 writer 成功序列化的字节，或显式 reader 此次实际读取的字节，SHA256 | 只限该字节域；不是所有同名源文件的证明 |
| `loaded_object` | 已读逻辑对象的规范摘要；dict 用排序 pairs，序列按序，SQLite Row 按列名映射 | 不能冒充原 JSON bytes 或 C4 表行流 |
| `scoped_loaded_object` | `sha256(canonical [query_scope, content_sha256])`；另留逻辑内容 `content_sha256` | 不能冒充整个事务或源文件 |
| `ordered_loaded_observations` | 同 object 不同读取的有序组合摘要，降为 weak | 不是单事务快照，不能生成强 pins |

数据库 hooks 记录业务已经 fetch 的行，另仅 `PRAGMA database_list` 确认实际连接来源，不再全扫业务表。signal store 的 committed write payload 是 weak，明确不等于已观察表快照；不 hash 活 `live.db` 冒充包含 WAL 的事务身份。decoded calendar text 也是逻辑内容，不冒充原始文件 bytes。

C4 转换器 `benefit_policy.py` 不把上述逻辑摘要转换为 byte pin。其未来 typed 事务流协议是：`identity_kind=bytes, digest_domain=sqlite_table_rows, digest_algorithm=trade-c4-table-rows-v1`，且 `source_context` 明确 `method=sqlite_read_transaction, transaction_id, table, columns, order_by=全部列, row_count, date_column, max_date, includes_committed_wal=true, scope=full_table`。字节域是按声明全列排序、每行 canonical JSON 数组加 LF 的实际事务行流，BLOB 特殊编码见 [benefit-restore.md](benefit-restore.md)。

sidecar bytes 和 DB 行流还必须有 producer 自身的 `generation_id`、带时区 `as_of`、真实观察时间和明确来源。当前市场 hooks 没有共同 generation/as_of/C4 全表行流，转换结果应为 unknown。context/profile 只能引用 SHA 固定的 immutable receipts；静态 required profile、刚捕获的备份副本、当前源文件都不能反填历史 pins。

## 从真实 loaded-code receipt 建立审核 binding

`code_identity.module_sha256` 来自进程实际加载的 Python code 语义：bytecode、递归常量、名称/参数/闭包信息和异常表；包含该模块函数、直接导入函数及 evidence helper 的函数/方法。不拿磁盘文件后读 hash 或 `git HEAD` 推定进程实际加载版本。路径/行号不作代码语义。runtime 常量由实际 `config_identity` 另行记录；传递依赖没有全量 attestation，coverage 字段明确此边界。

没有审核 binding，receipt 仍可记录实际模块摘要，但 `code_identity.sha=unknown`。配置摘要来自实际 loaded 配置，不能填一个共同占位 hash；collector 支持 `required[].code_sha/config_sha` 分阶段绑定，pipeline 总配置版本由审核 policy 另定。

建立流程：

1. Claude 审合并安装确定版本，核实该版本实际部署来源/配置/依赖。开启 evidence 后，由正常已授权业务运行产生本版本 receipts；这里不额外运行生产生成器。CLI consumer 也可先运行一次，产生 code 未绑定的 unknown receipt，获取其实际模块摘要。
2. 从这些明确的 receipt 发布结果/可信交接记录取得**精确路径和 SHA**。现在 hash receipt 只能验证其内容未变，不能反证旧执行代码身份。不要选 latest，也不要把测试夹具摘要当生产摘要。
3. 下面只读命令提取实际摘要并输出 `reviewed:false` 候选。`REVIEWED_CODE_SHA` 是外部审核确认的 40hex commit，工具不会验证该 commit 已部署，更不会自动改为 reviewed。候选可在私有目录用 `umask 077` 保存：

```sh
OPS_DELIVERY_EVIDENCE_ENABLED=1 python3 scripts/delivery_evidence.py binding-candidate \
  --data-root "$DATA_ROOT" --code-sha "$REVIEWED_CODE_SHA" \
  --receipt "$PRODUCER_RECEIPT" "$PRODUCER_RECEIPT_SHA256" \
  --receipt "$PUBLICATION_RECEIPT" "$PUBLICATION_RECEIPT_SHA256" \
  --receipt "$CONSUMER_RECEIPT" "$CONSUMER_RECEIPT_SHA256"
```

4. 审核人将 source_receipts 的实际来源、module digest、声明 commit、实际 loaded 配置和依赖范围一起核对。不能仅因候选里写了某 commit 就批准。审核后才将 `reviewed:true` 的配置以同目录临时文件加原子 rename 安装为 `<data_root>/data/ops_delivery/producer-identity.json`，文件 `0600`，父目录 `0700`。这是可更新本机配置；receipt 本体始终不可变。
5. 后续自然运行必须重新匹配 binding；旧 unknown receipt 不回写、不自动晋级。源码/helper/直接函数依赖或实际加载命名空间变化会改变摘要，需要新审核；缺 binding、摘要不匹配或未覆盖的依赖仍不能批准为完整部署证明。

binding 格式（最多 128 个模块摘要，64 KiB；示意值不能用于生产）：

```json
{
  "schema": "trade-producer-identity-v1",
  "reviewed": false,
  "code_sha": "<审核部署版本40hex>",
  "loaded_module_sha256": ["<真实receipt中的64hex>"]
}
```

## 直接调用现成本地消费者

CLI 不需要另写 Python wrapper。`python3 -m scripts.delivery_evidence` 与下面脚本形式使用相同 canonical helper 命名空间；不同业务模块的实际摘要仍应分别审核。

以下变量必须由调用者明确指定：`DATA_ROOT` 为绝对数据根，`SESSION_DATE` 为该槽 ISO 日期，两个 receipt 路径及其可信 SHA 为对应 backtest/publish 的**指定事实**，`STATS_JSON`/`TRADES_JSON` 为欲实际消费的两份文件的绝对路径。没有变量默认值、glob 或 latest 回退：

```sh
OPS_DELIVERY_EVIDENCE_ENABLED=1 python3 scripts/delivery_evidence.py verify-local-backtest \
  --data-root "$DATA_ROOT" --session-date "$SESSION_DATE" \
  --producer-receipt "$PRODUCER_RECEIPT" --producer-sha256 "$PRODUCER_RECEIPT_SHA256" \
  --publication-receipt "$PUBLICATION_RECEIPT" --publication-sha256 "$PUBLICATION_RECEIPT_SHA256" \
  --stats "$STATS_JSON" --trades "$TRADES_JSON"
```

两文件 basename 固定为 `signal_kelly_backtest.json`、`signal_kelly_trades.json`，只支持 NDO `next_day_open`。SDC/parts/gzip 不会被冒充成这两件。reader 校验指定 receipt 的内容 SHA、私有分区、stage/chain/session/batch，再实际读取两文件，核对 producer/proof byte digest、列宽、buy basis 和逐 mode 全周期 n，发布新的 immutable consumer receipt。

| CLI 结果 | rc | 含义 |
| --- | --- | --- |
| `status=disabled` | 0 | 未开启，不读取/写入证据，不表示交付成功 |
| written/idempotent，`stage_status=success,evidence_quality=strong` | 0 | 本地 consumer 验证通过，scope 仅 `isolated_local_reader` |
| `stage_status=failure` | 1 | 已证实的内容/局部业务谓词冲突；不改变任何原业务文件或通知 |
| unknown / metadata failure / 身份未审核 / 缺输入 | 2 | 不足以证明，不能变绿 |
| 参数错误、相对路径 | 2 | argparse 拒绝，不自动寻找替代件 |

每次显式验证产生新事实；不要删除旧 receipt 来消除重试歧义。多个候选无法唯一兼容时 collector 保留 unknown，不能按 mtime 挑一条绿记录。

## Stage 与 chain 的边界

`stage_status=success` 只描述该局部阶段。helper 不输出 `chain_success`。归一化 success 必须有完整事前 required-set/会话/日历/deadline/code/config，同代 digest edges、足量业务 predicate 计数和最后真实 consumer witness。HTTP 200、exit0、旧文件存在、guard skip 或通知沉默均不构成交付成功。

当前可执行强局部路径是 backtest 原生输出校验 → 原 `write_run_proof` 当前 run 字节证明 → 显式 `isolated_local_reader`。collector policy 最后 requirement 的 `consumer_scope` 必须精确为 `isolated_local_reader`；写 `production_browser` 或 R2 scope 应保持 unknown。这个 reader 不做 HTTP，不证明公网 CF/R2/前端消费或完整上游可用性。

市场 signal/freeze/plan 采到真实输入/提交 payload/冻结状态/写字节，也可能只有 stage_only；backup/restore 的本地 validated 与异地覆盖/生产消费分开，缺同代来源仍 unknown。真实上线时间、交易所日历和前后各 10 完整会话窗口、人工工时/收益，均不能用合成测试数补齐。

远端仅沿现有 checks evidence 传有界安全摘要（`record_kind=delivery_v1`，≤20 scalars）；路径、receipt 详情和局部调试数据留本机。collector 的默认开关与部署接线见 [benefits-contract.md](benefits-contract.md)，C4 converter/恢复见 [benefit-restore.md](benefit-restore.md)。

## 隔离回归

以下命令仅使用临时合成数据、原函数 AST、真实本地 writer/proof/reader，不运行生产生成、交易、上传、通知或凭据读取：

```sh
python3 -m unittest scripts.tests.test_delivery_evidence_20261107 \
  scripts.tests.test_delivery_evidence_cli_20261107 ops.monitoring.tests.test_benefits
```

CLI 测试实际启动脚本及 `-m` 两种入口，覆盖默认关闭、实际本地成功、错误 SHA、相对路径、缺 proof、未审核 loaded code、内容冲突、SDC 拒绝、latest 垫片不被扫描、FIFO 拒绝及 `reviewed:false` 候选。合成日历/统计 stub 只验证接线，不当作真实交易日或生产收益。
