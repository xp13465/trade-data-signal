# HC08/10/11：业务证据与投递接线

本组按用户本次业务实施授权，在 `codex/ops-business-evidence-20261111` 独立树开发。基线 `0ad543ef41758be9d7102b42471489b24d0cb989`。不修改主树/main、协调README、pending-index、原packet或upload_r2；未部署、未访问生产数据库/R2、未发真实通知。全量 scripts/tests、整合R2 producer、最终Claude交接由父任务负责。

## 已实现

- 沿用 `trade-delivery-receipt-v1` 与原 emit_receipt/loaded_code_identity，不引入另一套R2证明格式。ops_business_evidence只增加固定对象的私有索引和判据，collector每轮最多读6份64KiB索引，不读业务数据库、对象或凭据。
- 回执字段映射：run=attempt_id/batch_id，业务日=session_date，code_ref=code_identity.sha，输入/输出哈希=inputs/outputs，覆盖率=counts.expected/validated，起止=producer_time，规则/有效期/原invocation/远端确认/生成轮次=consumer_witness。索引按started_at/evaluated_at保留最新轮次，旧成功不能覆盖新失败。
- 备份：复用source proof里的run/key/gzip/raw/table集合；只有原HEAD元信息、gzip/raw SHA、恢复库完整性与全部表计数通过后记成功；业务日来自源key。所属unit为真实 `trade-backup-db.service`，verify_backup只是其子步骤。手工样本不能代替当前自然invocation。
- 换手：原shell在独立run内生成原export proof，根必须是 `DATA_DIR.parent=REPO/static-site`。producer只查询固定日期5个指标，并核overview/boot/6个序列文件日期和值、首屏拆分一致性和精确bytes哈希，再与同run每件R2确认对账。部分/错日/错值/错hash/缺表仍未知或失败。
- 过拟合：原主/ext生成点写共同 `publication_run_id`，每次实际build_output新生成一次uuid4.hex，主/ext共用；即使OPS_BUSINESS_RUN/INVOCATION_ID环境相同，两次计算仍不同。分钟级generated_at只保留显示语义。发布前要求同token、同日、原结构校验；复用现有两站4次GET精确hash验证后记成功。receipt分别保存生成token与发布attempt；publish-only不把新发布run冒充旧生成run。
- Collector将健康status与execution_state/source_reason分开：正在运行是unknown，active timer缺next不等于停摆。原两个严重service需本unit新的成功完成invocation才自动恢复，失败身份穿过unknown/running观察仍保留。
- 投递沿原3次/5秒单次/总预算，payload与snapshot_id不变；开始前与结束后各原子写一次每attempt记录。HTTP、error_kind、ack_state及四种时间语义分开；回包丢失为unknown，未伪称PUT失败。Worker幂等ACK返回首次received_at，collector确认后才写delivered_at；旧API无时间字段仍兼容且保留null。
- UI沿用严重优先和紧凑入口，新增执行状态、未知原因、下份证据、业务/采集/接收/送达/有效期说明；没有补造时间，没有把旧metadata解释为内容健康。

## R2唯一接入接口（父任务整合）

```python
from delivery_evidence import record_publication
record_publication(data_root=REPO, run_id=run_id, object_name=name,
                   sha256=actual_sha256, size=actual_size, confirmed=True)
```

全部为关键字参数。data_root是明确运行数据根绝对路径，非GIT_REPO或static目录；object_name是data/下的文件名，不带data/前缀，与现有export outputs键完全相同。run_id必须对应本轮export proof；只有实际远端bytes/hash确认才可True，命令rc=0不够。未知调用False，不生成成功。函数不开网络，不读业务内容；写失败返回metadata_failure，不抛业务异常。small/large必须共享run。

本组turnover通过 `OPS_BUSINESS_RUN` / `OPS_TURNOVER_PROOF` 传上下文，后者由现有write_run_proof生成。R2组或父任务将这两项接入其既有上传确认路径；不修改本组receipt schema。collector不获得上传权限。

过拟合incoming的 `publication_run_id` 必须为相同非空安全ASCII token：`[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}`。旧远端pair缺token时可按逐字节已验证的可恢复备份保留，但只记generation_verified=false；不能伪补token，不以旧备份无token一律阻断首轮升级。正常首轮重新计算产出带token的新pair。token与发布attempt分开，publish-only保留原生成token；完整原build_output在临时REPO连续两次执行并使用原atomic_write_json验证，计算输入/通知边界替身，绝不触碰真实业务数据。旧本地pair的publish-only需正常重算，不能据分钟时间声称同轮。R2旧版本保护/首次升级策略属于R2组文件边界。

## 恢复保护迁移与上线顺序（父任务执行）

父审两个反例均先在实际Worker API复现，原始日志 `worker-before-atomic.log`。第一例恢复包被浅复制引用污染，受DB问题状态影响而重放409；第二例批次外prior读取存在先读后写竞争，新失败可被旧恢复覆盖。

现在先固定原始输入hash，再structuredClone规范化。原两服务的恢复条件在新增 `0005_ops_recovery_invocation.sql` 内执行：同一ops_runs插入事务读取当前故障锚点，必须新32位hex invocation、completed/success/exit0、开始晚于原失败、结束不晚于观察时间；无效恢复显示unknown并保留problem_open。时间先按毫秒四舍五入，避免julianday浮点误差让“相同开始时间”过关。其它检查正常更新，ACK/history计数取原子选出状态。没有修改已部署0001—0004，也没有把策略扩大到所有业务。

上线顺序：备份现有OPS_DB并确认已有0001—0004后，先应用0005（新增故障锚点、替换insert trigger、最后写policy版本），核对policy=1和原两严重问题仍开放；再发布Worker；再启用producer/collector并登记原代码身份manifest。新Worker遇旧schema明确返回503 `ops_recovery_migration_required` / `storage_configuration`，collector不会无界重试；读取API可继续使用。

回滚顺序：先回退Worker/collector代码，保留0005及故障锚点，不删除policy或回写旧trigger。旧Worker配新schema仍由数据库保护恢复；旧collector不含自然invocation证明时保持unknown，不自动关闭两严重。若迁移本身中断或校验失败，由父任务按备份恢复、核对migration登记后重试；不要在部分DDL状态上盲重跑。生产迁移、发布、自然下一轮验收本组均未执行。

## 启用与限制

原 `OPS_DELIVERY_EVIDENCE_ENABLED=1` 开关控制落盘。生产需沿原 `data/ops_delivery/producer-identity.json` 已审核模块指纹绑定机制登记新模块；缺绑定、代码不匹配仍unknown，不从读HEAD猜执行代码版本。此manifest本次未写生产。规则 `ops-business-v1` 的有效期上限26小时且业务日必须为当前北京时间日期；这是保守的本日证明，跨日/周末/公募周频未恢复样本不会自动保绿。

backup子步骤证明精确源对象恢复，不证明其它JSON资产整套恢复。overfit证明pair生成/公开字节同代，不证明模型评估有足够样本。通用34项资产没有各自完整业务规则时继续未知，不能因6个新业务检查通过就全站变绿。未经上线与自然运行，本组不宣布生产两严重已恢复。

每snapshot/attempt记录留在既有私有output_dir，定期保留清理由运维原策略安排；采集不扫描这些历史。未改版本串/min，由父任务统一构建。

## 核验

原始测试末行：`final-verified-worker.log` 为 `ℹ tests 98 / ℹ pass 98 / ℹ fail 0`；`atomic-d1-v2.log` 为 `ℹ tests 12 / ℹ pass 12 / ℹ fail 0`。`final-verified-browser.log` 含 `PASS: actual ops HTML/JS/CSS; collector indices; desktop/mobile; unknown timestamps; XSS; zero external requests`，原调度另20项通过。`final-verified-python.log` 原始末行为 `345 passed, 69 subtests passed in 90.60s (0:01:30)`。随后资产采集预算耗尽路径也补齐逐项unknown_reason/next_evidence，并定向重跑相关用例，原始末行 `61 passed, 44 subtests passed in 2.55s`，见asset-budget-final.log。

先保留反例：旧active service被标OK、34资产缺unknown_reason/next_evidence，`before.log`原始末行 `2 failed in 0.06s`。后续严格token需求触发旧fixture缺字段的中间失败也保留，最终以固定树重新回归为准。

测试覆盖输入域、状态组合、时间、上下游、边界、回退、并发七轴：缺字段/错run/错日/过期/错code/同长错hash/缺表/部分确认/运行中/exit124/历史成功回放/响应丢失与并发重试/旧API/private认证/XSS/证据落盘失败。生产timer形状取已提交runtime_cloud真实样本；运行恢复另复用真实脱敏journal fixture。

真实turnover shell在临时REPO执行，预先确认pipeline/upload/notify均为OFFLINE_STUB，sitecustomize封锁网络connect；原proof writer/loader与实际receipt函数不替换。真实backup shell在临时SQLite+本地S3替身验证新索引；overfit原发布函数四次GET替身逐哈希验证。

浏览器使用实际static-site/admin/ops.html、ops.js、ops.css及真实本地collector产出，在390/1280渲染；没有伪造DOM。原调度浏览器回归1440/390另20断言，所有请求route封锁外发。截图与原始日志位于 `/tmp/codex-reports/ops-backlog-20261111/ops/`。

Worker及兼容回归98项通过，包含丢失ACK后并发同snapshot、首次接收时间、过期、两个原严重服务的16个恢复负控、成功恢复包重复与关闭后重放、受控batch交错、前向迁移升级与旧schema明确拒绝。临时npm取得Miniflare 4.20260730.0，没有convertV4MiniflareOptions且最大支持2026-08-06；仅/tmp测试副本移除converter并改兼容日期后真实本地D1事务及原benefits兼容测试通过12项（包含真实D1受控batch交错与恢复包并发重放）。**该结果不是生产2026-11-07兼容日期验收**；生产配置未改。第一次缺包/不兼容失败日志保留。

已抓当前[Workers最佳实践](https://developers.cloudflare.com/workers/best-practices/workers-best-practices/)与[D1事务API](https://developers.cloudflare.com/d1/worker-api/d1-database/)，临时workers-types=5.20261110.1。没有项目依赖更新；认证保持独立ingest/admin、bounded body、no-store、无敏感异常输出。

## 34项资产的下一份证据

以下不是34起事故；先保留metadata_only/fixed_source_not_configured。每项都需要本轮run、业务日、已审核代码、输入输出hash、覆盖数、规则及有效期，具体对象范围如下。

| 对象 | 当前依据 | 下一份业务证据 |
|---|---|---|
| data:alert-buffers | 仅文件元信息 | alert-buffers 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:alert-state | 仅文件元信息 | alert-state 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:board-etf-map | 仅文件元信息 | board-etf-map 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:code-mirror | 未配置可验证固定源/轻量采集范围外 | code-mirror 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:etf-db | 仅文件元信息 | etf-db 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:etf-freeze | 仅文件元信息 | etf-freeze 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:export-manifest | 仅文件元信息 | export-manifest 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:export-proof | 未配置可验证固定源/轻量采集范围外 | export-proof 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:freeze-registries | 未配置可验证固定源/轻量采集范围外 | freeze-registries 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:frozen-missing-audit | 未配置可验证固定源/轻量采集范围外 | frozen-missing-audit 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:history-overwrite-audit | 未配置可验证固定源/轻量采集范围外 | history-overwrite-audit 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:index-daily | 未配置可验证固定源/轻量采集范围外 | index-daily 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:kelly-snapshots | 仅文件元信息 | kelly-snapshots 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:kelly-summary | 仅文件元信息 | kelly-summary 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:kelly-trades | 仅文件元信息 | kelly-trades 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:kelly-trades-sdc | 仅文件元信息 | kelly-trades-sdc 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:local-db-backups | 仅文件元信息 | local-db-backups 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:map-inputs | 仅文件元信息 | map-inputs 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:notify-ledger | 仅文件元信息 | notify-ledger 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:preupload-backups | 未配置可验证固定源/轻量采集范围外 | preupload-backups 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:public-fund-db | 仅文件元信息 | public-fund-db 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:published-data | 未配置可验证固定源/轻量采集范围外 | published-data 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:r2-db-backups | 未配置可验证固定源/轻量采集范围外 | r2-db-backups 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:restore-drill | 未配置可验证固定源/轻量采集范围外 | restore-drill 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:runtime-logs | 仅文件元信息 | runtime-logs 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:schedule-stats | 仅文件元信息 | schedule-stats 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:score-daily | 未配置可验证固定源/轻量采集范围外 | score-daily 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:sentiment-db | 仅文件元信息 | sentiment-db 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:signal-daily | 未配置可验证固定源/轻量采集范围外 | signal-daily 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:signal-stats | 仅文件元信息 | signal-stats 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:signal-stats-work | 仅文件元信息 | signal-stats-work 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:staticdata-backups | 未配置可验证固定源/轻量采集范围外 | staticdata-backups 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:stock-db | 仅文件元信息 | stock-db 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
| data:upload-state | 仅文件元信息 | upload-state 的完整业务范围与上述本轮回执；局部恢复样本不替代全资产 |
