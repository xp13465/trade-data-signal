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

现在先固定原始输入hash，再structuredClone规范化。原两服务的恢复条件在新增 `0005_ops_recovery_invocation.sql` 内执行：同一ops_runs插入事务读取当前故障锚点，所有OK都必须有32位hex invocation、completed/success、JSON整数exit_code=0及带时区完整起止；已有失败锚点时，还须新invocation且开始晚于最新warning/critical失败；结束不晚于观察时间；无效恢复显示unknown并保留problem_open。时间先按毫秒四舍五入，避免julianday浮点误差让“相同开始时间”过关。其它检查正常更新，ACK/history计数取原子选出状态。没有修改已部署0001—0004，也没有把策略扩大到所有业务。

上线顺序：备份现有OPS_DB并确认已有0001—0004后，先应用0005（新增故障锚点、替换insert trigger、最后写policy版本2），核对policy=2和原两严重问题仍开放；再发布Worker；再启用producer/collector并登记原代码身份manifest。新Worker遇旧schema明确返回503 `ops_recovery_migration_required` / `storage_configuration`，collector不会无界重试；读取API可继续使用。

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

后续独立复核修正后的Worker及兼容回归122项通过，包含丢失ACK后并发同snapshot、首次接收时间、过期、两个原严重服务的16个恢复负控、成功恢复包重复与关闭后重放、受控batch交错、前向迁移升级与旧schema明确拒绝。首次临时Miniflare 4.20260730.0只能适配旧日期，该历史日志保留。后续从锁文件在独立/tmp目录npm ci得到Wrangler4.158.0 / Miniflare5.20261104.0-beta / workerd1.20261104.1，并另取Wrangler4.160.0 / Miniflare5.20261110.0-beta / workerd1.20261110.1；两套均使用原生convertV4MiniflareOptions且保持2026-11-07，无日期降级。实际Worker源码打包后在workerd内运行，各31项通过，包括旧Worker/新Worker、warning并发交错与本次三个反例。真实本地Wrangler CLI另4项验证0005原子失败回滚、重试、已登记跳过与故障锚点保留。项目依赖、生产配置、线上库均未改。

已抓当前[Workers最佳实践](https://developers.cloudflare.com/workers/best-practices/workers-best-practices/)与[D1事务API](https://developers.cloudflare.com/d1/worker-api/d1-database/)，临时workers-types=5.20261110.1。没有项目依赖更新；认证保持独立ingest/admin、bounded body、no-store、无敏感异常输出。

## 独立复核后的修正与兼容边界

独立报告OPS-001/002/003均自行复现后修复；`review-counterexamples-before.log`为12例中10失败、2个warning-only对照已通过。warning和critical推进最新失败锚点，unknown/running不推进；原两个服务即使首次出现或问题已关闭，OK也必须有完整执行证据；SQLite `json_type(exit_code)='integer'` 排除false冒充0。缺证据变unknown，不凭空创建事故。新增受控warning并发、类型/日期负控和有效整数0/显式UTC偏移正控。

本次0005尚未生产部署，按明确授权修订此新增迁移；不改0001—0004。新Worker要求 `ops_recovery_policy.version=2`，旧schema或被否决dd7的policy1明确503。若某库已登记旧候选0005，工具会按文件名跳过；不要把修改文件当该库已升级。临时测试库可重建，任何已部署库则应另加前向迁移，不回写已部署migration。

回滚目标须固定到已审核旧版本。本次实际测试旧Worker为基线0ad543ef41758be9d7102b42471489b24d0cb989：保留修订0005时，原两服务仍受数据库完整执行证据和新失败锚点保护。dd7是被否决的中间候选，其gate只接受policy1，不适合作为policy2库的回滚目标。

**旧Worker不是全部新语义等价回滚**：它缺少业务 `valid_until` 读取时保护，实际已复现一份原本有效的业务回执到期后，新Worker为unknown、旧Worker仍显示OK，直到下一份unknown采集包或30分钟观察过期；旧ACK也不返回received_at/ack_state。若需要这些新语义持续有效，应保留修订Worker并前向修复，不能宣布完整功能兼容回滚。没有部署、迁移线上或关闭生产问题。

兼容报告另存 `/tmp/codex-reports/ops-backlog-20261111/ops/production-compatibility.json`；原dd7测试归档 `/tmp/ops-production-compat-20261111/dd7-compatibility/`，续修最终测试见report中的具体版本与迁移hash。生产目标日期采用父任务指定2026-11-07，未远程核对线上实际配置；本独立树根配置仍是2026-07-07，不擅自修改。

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

## 并行 publication 回调的索引锁

真实R2 `cmd_upload_turnover` small/large并行回调原 `record_publication` 已自行复现：同run不同对象争用原全局LOCK_NB，上传成功但部分确认索引丢失。现按object_id的SHA256分锁；同对象保留原子比较/替换，最多等250ms，超时返回 `metadata_failure/TimeoutError`，ENOSPC返回 `metadata_failure/OSError`，均不改变上传业务返回码。业务索引也沿用此有界锁；旧成功仍不能覆盖较新unknown/失败。该期限约束锁争用，不承诺阻塞文件系统I/O的总时限。

独立复现末行 `1 failed, 9 deselected in 0.17s`；在R2 fixed6505归档仅覆盖本组helper、实际writer/reader不替换、网络和上传外部边界全stub后，末行 `12 passed in 2.29s`，包括small 6/6、全量9/9、后续unknown、持锁超时和ENOSPC业务rc不变。另定向回归末行 `161 passed in 37.18s`。未修改upload_r2，也不将此结果当作R2 recover路径的验收。

## Claude：代码身份绑定的最短操作

以下命令只读取证，未在生产执行。部署顺序沿父任务DELIVERY.md。默认路径来自现有DEPLOY文档，Claude先核对unit/drop-in；commit填写已审核的最终整合版本，不能据本示例自动批准HEAD。

```bash
export OPS_CODE=/home/ubuntu/code/trade-data-signal
export OPS_DATA=/home/ubuntu/code/trade-data
export OPS_PY="$OPS_DATA/.venv/bin/python"
export OPS_REVIEWED_SHA='<Claude审核的40位commit>'
```

首次自然producer缺绑定时，receipt含实际loaded digest，但code_identity.sha=unknown，collector继续unknown。校对自然invocation、业务日、run后，从以下六个固定索引的session_date/receipt_id定位所需不可变回执：`$OPS_DATA/data/ops_delivery/receipts/<session_date>/ops_business/<receipt_id>.json`。不以export proof/publication索引替代receipt，不手工运行生产任务取身份。

| 固定索引（相对 `$OPS_DATA/data/ops_delivery/index/`） | 回执object_id / stage |
|---|---|
| turnover.json | turnover / publish |
| overfit.json | overfit / publish |
| backup-sentiment.json | backup-sentiment / restore |
| backup-etf_national_team.json | backup-etf_national_team / restore |
| backup-stock_daily.json | backup-stock_daily / restore |
| backup-public_fund.json | backup-public_fund / restore |

用现有binding-candidate读取这六份回执；每份最多64KiB，CLI复核哈希、schema、私有权限和分区路径。输出同一种trade-producer-identity-v1候选、reviewed=false，不安装manifest，也不认证传入commit与运行代码对应关系：

```bash
timeout 15s env PYTHONDONTWRITEBYTECODE=1 OPS_DELIVERY_EVIDENCE_ENABLED=1 "$OPS_PY" - <<'PY' > /tmp/ops-producer-identity-candidate.json
import hashlib, os, subprocess, sys
from pathlib import Path
code, root = Path(os.environ['OPS_CODE']), Path(os.environ['OPS_DATA'])
sys.path.insert(0, str(code / 'scripts'))
from ops_business_evidence import bounded_json, OBJECTS
from delivery_evidence import receipt_root
base = receipt_root(root)
args = [sys.executable, str(code / 'scripts/delivery_evidence.py'), 'binding-candidate',
        '--data-root', str(root), '--code-sha', os.environ['OPS_REVIEWED_SHA']]
for name in OBJECTS:
    record = bounded_json(base / 'index' / (name + '.json'))
    path = base / 'receipts' / record['session_date'] / 'ops_business' / (record['receipt_id'] + '.json')
    assert path.resolve().is_relative_to((base / 'receipts').resolve())
    bounded_json(path)
    with path.open('rb') as stream:
        raw = stream.read(65537)
    assert len(raw) <= 65536
    args += ['--receipt', str(path), hashlib.sha256(raw).hexdigest()]
subprocess.run(args, timeout=10, check=True)
PY
```

新helper身份来自 `ops_business_evidence.record_result → loaded_code_identity(record_result, root)`：摘要包含模块已加载函数、直接导入函数及delivery_evidence自身函数/类方法，不是文件SHA或HEAD；coverage不证明传递依赖，运行常量另记config。Python字节码版本和模块命名空间影响摘要，backup/overfit import与turnover CLI的__main__不能假定相同，以上实际回执覆盖各入口。

上线前安全只读import探针如下，不调用producer；用临时空根防止借用旧批准manifest。沿用现有manifest格式、reviewed=false、source_receipts=[]，只作审核输入，不能替代自然回执或证明turnover CLI身份：

```bash
timeout 10s env PYTHONDONTWRITEBYTECODE=1 OPS_DELIVERY_EVIDENCE_ENABLED=0 "$OPS_PY" - <<'PY' > /tmp/ops-loaded-import-unreviewed.json
import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(os.environ['OPS_CODE']) / 'scripts'))
import ops_business_evidence as ops
with tempfile.TemporaryDirectory(prefix='ops-identity-probe-') as empty:
    identity = ops.loaded_code_identity(ops.record_result, Path(empty))
print(json.dumps({'schema': 'trade-producer-identity-v1', 'reviewed': False,
                  'code_sha': os.environ['OPS_REVIEWED_SHA'],
                  'loaded_module_sha256': [identity['module_sha256']], 'source_receipts': []}))
PY
```

Claude审核代码、运行版本及候选source_receipts/digests后，按现有机制安装 `$OPS_DATA/data/ops_delivery/producer-identity.json`（trade-producer-identity-v1、reviewed=true、准确code_sha、审核后的loaded_module_sha256；文件0600/目录0700，运行用户原子替换）。保留同commit其它仍需的已审核producer摘要，不盲目用本组列表覆盖；本组没有代为批准或安装。

**安装binding不回写旧receipt，也不让旧索引自动变绿。须等下一次自然producer重新加载已审核版本并生成新receipt，才可能取得已审核code_ref；其它run/hash/coverage/有效期仍须通过。** 真实CLI隔离测试已验证：安装模拟批准manifest后旧receipt逐字节不变且仍unknown，下一自然run才通过；helper或Python变化需重新审核。
