# C4 成套捕获与隔离恢复

默认关闭，入口仅在 `OPS_DELIVERY_EVIDENCE_ENABLED=1` 时运行。无需新服务、bucket、权限或网络；不读取 `.env`，不调用交易、生成器或通知。生产启用、归档接线及恢复验收交 Claude 审核部署。

## 已有链路与新增边界

`scripts/backup_db.sh` 现有热备和 `upload_r2.py upload-db` 保持原样。新增挂接在本地热备后，按显式 policy 与资源预算取独立的配套快照，导出至 `$BACKUP_DIR/capture-sets/<capture_set_id>/`。这个目录包含 DB 一致副本、freeze、map、必要 config 和最后原子发布的 `manifest.json`。原单库备份/上传对象与此集合不是同一身份。freeze/map 的 id 不能生成保留文件名 `manifest.json`；配置的 `manifest.config` 等无冲突名称仍可用。

`upload_r2.py` 的 `_sqlite_snapshot_to_gz` 已用 SQLite backup API；large-json manifest 记录逐对象完整 key/字节/hash，不能证明本集合已异地备份。现有 `verify_backup.sh` 的逐库 integrity/行数/新鲜度演练，以及 `docs/scripts/restore_r2_db_backup.py` 的参考副本比对，均不能替代配套业务验收。新增挂接没有调用这些恢复脚本的默认生产目标。

本轮没有新增上传通道。`remote_coverage=unknown` 固定保留；即使原 DB 上传成功也不升级。本地 capture 不是生产恢复，`restore_status=not_verified`。新增步骤失败只记录诊断和 receipt，不改变原备份/verify 的退出码或告警路径。

## 显式 required-set policy

`OPS_BENEFIT_CAPTURE_POLICY` 指向本机非敏感 JSON 配置；不自动扫描 config 或凭据。路径须绝对，文件须已存在。下面仅是格式例子，路径、时间和 pins 必须由实际 producer/export-proof 审核接线，不能照抄成生产证据：

```json
{
  "schema": "trade-benefit-capture-v1",
  "session_date": "2026-11-06",
  "generation_id": "existing-export-run-identity",
  "artifacts": [
    {
      "id": "sentiment", "kind": "db", "path": "/isolated-fixture/data/sentiment.db",
      "generation_id": "existing-export-run-identity", "as_of": "2026-11-06T16:05:00+08:00",
      "tables": {
        "signal_daily": {
          "min_rows": 1, "date_column": "date", "max_date": "20261106",
          "rows_sha256": "<producer-pinned-table-row-digest>"
        }
      }
    },
    {
      "id": "freeze", "kind": "freeze", "path": "/isolated-fixture/data/signal_kelly_etf_freeze.json",
      "generation_id": "existing-export-run-identity", "as_of": "2026-11-06T16:05:00+08:00",
      "sha256": "<actual-producer-byte-digest>"
    },
    {
      "id": "mapping", "kind": "map", "path": "/isolated-fixture/data/board_etf_map.json",
      "generation_id": "existing-export-run-identity", "as_of": "2026-11-06T16:05:00+08:00",
      "sha256": "<actual-producer-byte-digest>"
    },
    {
      "id": "universe", "kind": "config", "path": "/isolated-fixture/config/universe_rules.yaml",
      "generation_id": "existing-export-run-identity", "as_of": "2026-11-06T16:05:00+08:00",
      "sha256": "<actual-config-byte-digest>"
    }
  ],
  "business": {
    "db_id": "sentiment", "table": "signal_daily", "indexes": ["explicit_required_index"],
    "signals": ["buy_backup", "buy", "buy_aux", "buy_special"],
    "start_date": "20261101", "cutoff_date": "20261106",
    "expected_selections": {"20261106|explicit_required_index|buy": "<historically-frozen-code>"}
  }
}
```

至少一个 DB、一个 freeze、一个 map、一个 config；可有多 DB/config，每库必须事前列出关键表与正数行数门槛。日期范围及 index/signal 范围是明确的验收边界，不宣称覆盖未列的库、表、市场或历史区间。按实际读入 config 的范围补齐必要文件；当前示例只说明一个 config，不能当作生产所需配置全清单。

每项 `generation_id` 必须一致，`as_of` 须有时区且不晚于捕获开始。该时间来自 producer 对实际输入的观察，不能以文件 mtime 或今日时间代替历史 as-of。元数据声明本身不是跨文件事务证明：DB 用显式只读事务和 backup API 取包含已提交 WAL 的副本，关闭后才 hash；JSON/config 在所有 DB 捕获前读入，在所有 DB 完成后复读，并核对设备/inode/size/mtime/ctime 和完整 hash。JSON 拒绝重复 key、截断与非有限数值。

`rows_sha256` 算法：对声明表的所有列按列顺序 `ORDER BY`，每行以 UTF-8、`ensure_ascii=False`、`separators=(',',':')`、`allow_nan=False` 序列化 JSON 数组，末加 LF，依次送入 SHA-256。BLOB 编码为 `{"sqlite_blob_hex":"..."}`。manifest 另存 schema digest、行数和声明的最大业务日期。不 hash 活库主文件冒充事务身份。pins 必须有独立 producer 上下文；从捕获结果反填 pins 仅能做本地合成测试，不能证明生产历史。

非 DB 的 byte pin 或 DB 的逐表 row pin 缺失时可导出，但本地 assessment 为 `unknown`。缺文件、错 pin、错代、空关键表、错 cutoff、缺必须 freeze 键或错误选择拒绝整组发布。没有配置 policy 时只记录 unknown，不会复用上次集合冒充本轮成功。

本地业务 validator 读取隔离 DB 的 `date,index_id,signal`，按声明范围逐键消费 native freeze/map。读取侧复用已有语义：精确 freeze 键优先；类型漂移只允许相同 date/index 的冻结键按 buy_backup/buy/buy_aux/buy_special 排序兜底，不增删/补造 freeze。必须存在 map 对应指数及有分候选；历史 ETF 可以与当前 map 的 best 不同。`expected_selections` 可固定审核过的历史选择。本 validator 不导入生产回测引擎，不解释全部 universe 配置，也不证明收益计算/计划消费者兼容；生产 consumer witness 始终 unknown。

## 仅隔离演练

不执行生产 backup 主入口即可用临时假数据跑单元测试：

```sh
python3 -m pytest -q ops/monitoring/tests/test_benefit_capture_restore.py
```

显式本地调用形式（须替换为临时夹具路径）：

```sh
OPS_DELIVERY_EVIDENCE_ENABLED=1 python3 ops/monitoring/benefit_capture.py \
  --data-root /tmp/c4-fixture --policy /tmp/c4-fixture/policy.json \
  --export-root /tmp/c4-fixture/backups/capture-sets --max-bytes 33554432 --max-sets 8

OPS_DELIVERY_EVIDENCE_ENABLED=1 python3 ops/monitoring/benefit_restore.py \
  --data-root /tmp/c4-fixture \
  --manifest /tmp/c4-fixture/backups/capture-sets/SET_ID/manifest.json \
  --manifest-sha256 TRUSTED_OUT_OF_BAND_SHA256 --target /tmp/c4-new-isolated-target --max-bytes 33554432
```

省略 target 只验证集合，恢复状态始终 `not_verified`。target 必须位于真实 `/tmp`（macOS `/private/tmp`）下且尚不存在，父目录须存在；源文件目录、源集合或它们的子目录不能作目标。只写新建隔离目录；复制/校验失败清理自己创建的目录。所有声明文件、size、digest、同集合身份和业务关系均再次校验；没有可信的外部 manifest digest 仍为 unknown，不称完整验证。原 freeze/map/DB 不会覆盖。

`verify_backup.sh` 从 `OPS_BENEFIT_RESTORE_MANIFEST` 和 `OPS_BENEFIT_RESTORE_MANIFEST_SHA256` 获取明确集合，目标为本轮新建 `/tmp/verify-backup-*/benefit-restore`，结束由原 trap 清理。不默认选择“最新”集合。只有 DB 下载成功不产生 C4 成功。未配置集合时为 unknown/not_verified。即使隔离检查通过，也仅 `restore_status=validated`、整链 `status=unknown`；没有远端获取证明和真实兼容消费者见证，不 emit 链成功。

CLI 的可见结果：默认关闭打印 `status=disabled`；启用但缺 policy/manifest 打印 `capture_policy_unconfigured` / `capture_manifest_unconfigured` 并写 unknown receipt，CLI rc=0；显式路径不可读、配置格式错误、内容校验拒绝时 CLI rc=1，stderr 有本地诊断，stdout/receipt 标 failure，恢复保持 not_verified；缺必填参数由 argparse 输出用法及 required 参数，rc=2。receipt 写入失败打印 metadata_failure 且 CLI rc=1。shell 挂接块统一记录失败并保留调用前原 RC。单测实际执行了原 verify 挂接块、真实本地 CLI 和 helper，用临时配置验证其 `$TMPDIR/benefit-restore` 目标可用，不调用生产 verify/backup 主入口。

## 成套副本容量与全操作时限（IBR-01 修订）

只配置 policy 不足以启动捕获。必须显式给正整数 `--max-bytes` / `OPS_BENEFIT_CAPTURE_MAX_BYTES`（export root 已用加本轮新增的总字节上限），以及 `--max-sets` / `OPS_BENEFIT_CAPTURE_MAX_SETS`（集合数上限）。恢复必须给 `--max-bytes` / `OPS_BENEFIT_RESTORE_MAX_BYTES`（完整恢复集合字节上限）。缺失、零、负值、非法预算均拒绝，不发 validated 结果。示例的 32MiB/8 仅用于临时夹具，不是生产容量建议；生产预算由静态配置结合真实可用空间审核。Python API 同样必须提供 `limits=benefit_capture.Limits(max_bytes=...,max_sets=...)`。

公共有限默认值和显式覆盖：`--max-file-bytes` / `OPS_BENEFIT_MAX_FILE_BYTES` 默认 256MiB；`--max-json-bytes` / `OPS_BENEFIT_MAX_JSON_BYTES` 默认 8MiB（policy、JSON/config 读入、manifest 和单行编码/业务键集合预算）；`--min-free-bytes` / `OPS_BENEFIT_MIN_FREE_BYTES` 默认 128MiB；`--timeout-seconds` / `OPS_BENEFIT_TIMEOUT_SECONDS` 默认 30 秒，允许 `(0,300]` 的有限值。最小剩余空间不能为零。原 shell 已通过环境继承这些选项，无需修改上传器、bucket 或通知。

capture 根目录以零字节普通 `.capture.lock` 的非阻塞排他锁串行 admission 和整个捕获；非零、非普通文件、多硬链接锁拒绝。只对 UUID 命名、schema/id 匹配、完整平铺 required inventory、无 symlink 的已发布集合记账，包含 manifest 的实际所有文件字节。未知文件/目录、遗留 pending 或损坏集合直接拒绝，不免费忽略。**不自动删除任何历史、未知或 active 集合**，不以 mtime 过期为由清理；因此原 `RETAIN_DAYS` 仍只作用旧单库备份，而 C4 达到显式容量/数量预算后停止增长并可见报错。需要释放容量时由授权的既有归档/留存流程处理。

预留金额为已用字节加源文件实际大小、存在的 DB WAL 大小、policy 字节和 64KiB manifest 余量；不够或剩余空间低于预留加安全余量时，在 DB 复制前拒绝。SQLite pinned transaction 的 page_count/page_size 再核单库上限，backup 进度和每个写入阶段核实际 pending 大小及剩余空间，覆盖预留后 WAL 增长。full ORDER BY 前预检临时盘空间（两倍副本大小），SQLite 缓存限 4MiB并使用文件临时存储。超过源/目标单文件、JSON、行编码或业务键预算同样拒绝，不扩充原生产消费查询来制造新身份。

两个 CLI 均由父进程以配置的总时限包住完整 worker：policy/JSON 读取、SQLite backup、integrity/全表 ORDER BY/hash、业务复核、隔离分块复制和 receipt 工作都在此范围。SQLite 另有 progress handler，读/hash/copy 分块检查内部 deadline；文件类型/字节和剩余空间先检。超时杀掉并回收 worker，输出 `optional_worker_total_timeout`、unknown/not_verified，CLI rc=1；外层原 backup/verify RC/通知分支保持。普通失败清理本次临时输出。强制超时可能留下本次 private pending/隔离临时目录，绝不当已发布或已恢复；下一次 capture 遇遗留 pending 会拒绝增长，verify 的原 trap 清自己的隔离目录，显式 CLI 目标由人工核查。没有递归清除未知/active/source 的 watchdog GC。此时限验证来自临时阻塞注入，不宣称实际生产大库能在该时限内完成。

## Receipt 与剩余接线

调用 producer 的 `scripts/delivery_evidence.py:emit_receipt`，不另实现 receipt 存储。stage=backup/restore、chain=`backup_isolated_restore`、object=`backup_db_freeze_map_restore`。`batch_id=chain:session_date` 是稳定逻辑槽，`attempt_id` 是每次执行 UUID，`receipt_id` 由 helper 为阶段事实生成。capture_set_id 只标识本组文件。backup outputs 与 restore inputs 带实际文件/manifest digest；restore outputs 带隔离实际读取的选择 digest。未知日期 batch 为 unknown；同日不可合成兼容链。`producer_time` 保存实际执行时间，normalizer 的 `source_at` 不以每次采集时间冒充新证据。receipt `events` 单列 local_capture_status / isolated_restore_status / offsite_status / production_consumer_status，因此已做本地隔离验证不会与异地未接混淆。细节和路径保留在私有本地文件，远端仅 collector 的既有安全摘要。当前不提供完整链谓词 counts、批准的 code_sha40 或生产 consumer witness，正常归一化为 unknown；不能宣称三链闭环已可自动取得强证据。parent 统一 source commit、build、CI、控制文件和部署，不在运行时猜已批准版本。

待原归档链/Claude 审核接线：从已有 export-run/proof 提供独立 required-set、loaded config、generation/as-of 和内容 pins；将完整导出目录交既有授权归档扩展点（本轮仅提供导出物，无新 uploader）；保存并核对每个对象的远端 key/version/ETag/content digest、捕获 manifest 的可信 digest 与同组关系；将实际下载的同组目录交隔离 validator，再接生产兼容消费者的只读隔离验收。缺其中任意证据维持 unknown。不把测试数量、单库 R2 成功或本地验证耗时当业务 ROI/RPO；完整生产恢复时间与成套 RPO 本轮未测量。

转换器代码已由独立 `benefit_policy.py` 提供（`--help` 有 profile/context 格式），无需 Claude 重写转换器：只从显式 SHA 固定的 immutable receipts 和静态 required profile 生成全或无的 policy，未知不写。Hooke 确认目前 native `loaded_object`/`scoped_loaded_object`/ordered 查询摘要与 C4 byte/全表行算法不等价，且没有共同 generation/as-of；这些输入仍为 unknown。typed 全表行流仅作为明确兼容契约及真实临时 WAL 源事务正控，不新增生产全表扫描来伪造原消费者身份。真实 source arrival、成套异地获取和生产消费者证明仍未取证，不能凭转换器 ready 宣称闭环。
