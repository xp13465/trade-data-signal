# 私有交付收益测量 API v1

仅既有 OPS_DB；与原 snapshot schema 无新增顶层键。默认 `OPS_BENEFITS_ENABLED` 缺省或非字符串 `true` 时关闭；先由主控审核应用 `0004_benefits.sql`，再决定启用。缺迁移返回 `configured:false,status:not_configured`；旧 ingest/cron/API 继续工作。新模块准备或写入异常时，原 ops 原子事务单独重试；收益写入失败不代表业务成功。不要以启用功能、ack、退出码、原运行通知数量或测试数量声称生产收益。

## 权限与路由

全部经过原 admin/session allowlist；ingest bearer 不可读、不可人工修改 study，普通用户禁止。GET 继承 no-store、安全响应头。POST 必须 `Origin` 精确等于请求 origin（包括 bootstrap admin）、`Content-Type: application/json`、`X-Ops-Intent: update`。原 256 KiB 限制、JSON 校验和安全字符串规则适用；不支持 URL 抓取、文件读取、任意路径或文件上传。

- `GET /api/ops/benefits`：最多5 studies/页（按study_id，`next_study_after` → `?study_after=...`继续）、每 study 最近10前/10后（排除上海时区上线当日）的已保存生产证据汇总、缺项、已知覆盖和未知逻辑区间、版本和混杂因素、最近200个逻辑槽。`records_truncated` 显示截断。
- `GET /api/ops/benefits/records?limit=50&after=...`：所有保留 current 记录的 keyset 分页，limit 1..200；用返回的 `next_after` URL encode 后继续。
- `GET /api/ops/benefits/audit?limit=50&after=...`：原始归一化记录，含 snapshot、收到时间、内容 hash 和 source clock。分页不承诺事务一致性。
- `POST /api/ops/benefits/studies`：inline JSON 字段 `expected_revision`、`study_id`（安全ID）、`chain_id`、`before`、`after`、`first_sample_proof_sha`。首次 revision=0；现有登记只允许 expected_revision 等于已存版本且完全相同的幂等重放，否则409。新 policy/version/calendar/rollout 使用新 study_id。限50项。
- `POST /api/ops/benefits/import`：`expected_revision`、`study_id`、`import_id`、`before`、`after`；必须匹配 study revision。before/after 除 days 外须与登记完全一致，days 最多10。import_id 与内容 hash 不可变，重放幂等、冲突409，每 study 最多20份。保存为 attested 原始历史声明，GET study.imports/私有导出可审；**不升级为 collector 生产证明，不填补缺失分母或自动进入真实比较**。
- 既有 `GET /api/ops/export` 启用并迁移后流式包含 benefit_audit/current/studies/imports。关闭或未迁移时保持原导出表集。仍是分页保留态导出，不是 D1 原生一致性备份。

## 登记格式

before/after 对象使用 `ops/monitoring/compare_benefits.py` 的 `delivery-benefits-v1` period schema。登记时 `days:[]`；固定 contract_id、metric_id、caliber_id、population_id、schedule_id、exclusion_policy_id、normalizer_sha、code_sha、config_sha256、rollout、calendar、measurement_kind、as_of、confounders。COMPARABLE 七字段两边须相同；code/config 与 rollout 的 before/after 配对。calendar 必须是完整有序去重的真实会话列表、上海时区、来源安全ID及紧凑 JSON 列表的 SHA256。最多400会话。不按周一至周五补造日历。

rollout 包含 effective_at、evidence_ref、before_code_sha、after_code_sha、before_config_sha256、after_config_sha256。`first_sample_proof_sha` 是上线后首份自然 collector 证据的摘要（获得后登记，不能填测试或人工ack）。登记标 `registration_strength:attested`；只有持久化自然样本、版本/配置/日历/contract 匹配，截止窗口关闭且首样匹配时才有 `verified_consistency_only`。这只是证据一致性，不能独立证明人工登记的生产启用时间；`trust_boundary` 明示此限制，始终 `real_benefit_claim:false,attribution:not_established`。

配置错误/未闭合窗口/未知 inventory/缺证据/20日不足/混版/合成默认拒绝均 `not_ready`；不能以旧30天 ops history 摘要代替。线上比较使用保存的 collector current，按逻辑批次求和（sum_success/sum_eligible_batches），不平均每天比例。成功变化用未知上下界相减，非置信区间。不自动计算手填人工分钟或相对ROI；线下比较器的测得分钟功能独立保留。

## Wire、时钟和保留

固定20个 scalar evidence 键见 `contracts/benefits-v1.json`；`record_kind` 统一为 `delivery_v1`。v2 接口更正：移除 aggregate `attempt_id`，增加 `measurement_kind:real|synthetic|unknown`，不是第21键。真实 attempt_id 仅留本地/private阶段不可变 receipt。`check.id=benefit:<chain>:<session>`，batch_id 是稳定逻辑交付槽；proof_sha 覆盖 kind、真实 input/output 摘要、parent/consumer witness 与各阶段 deadline。后端不按同日拼接阶段。

kind 同时进入后端不可变内容 hash 与 receipt identity；audit/current 主键与容量按 `(chain,session,batch,kind)` 隔离，存储 JSON 显式保留 kind。缺失/无效 kind 统一 unknown，旧记录不能被隐式升级为 real。GET current/audit/私有导出均保留 kind，keyset export key 包含 kind。

study 查询必须同时匹配数据库 kind 与保存 JSON 的 kind：real study 只接 real，synthetic 只接 synthetic；unknown 或未配置 study kind 不挑样、永不 real-ready。synthetic study 即使20日齐全，仍由默认比较器返回 synthetic_refused_default；前端显式标“合成/不计真实收益”。修改 study 的 kind 违反既有 immutable 身份，会409；重新登记 real study 仍不能借用 synthetic 样本，attested import 也不能升级它们。

原 ops 中非 real wire 一律降 unknown；启用收益持久化后，投影只采用该槽已有 real current，fresh synthetic/unknown 不覆盖 real failure、不制造恢复。synthetic/unknown 的失败也不会污染 real current 的 conflict。默认 flag off、未迁移或可选模块故障时原业务采集路径继续；不能依赖 reason、record_kind 变体或 real_benefit_claim 常量代替 kind 护栏。

`check.observed_at`/`evaluated_at` 是本次验证时间；`source_at` 是已验证 receipt 不可变 producer completed_at 的最大值，仅 verified 有值。current 使用 source_at 前进；无源时钟仅允许 unknown→partial / partial新增明确failure 的单向信息提升，仍不可比较。同 proof_sha 幂等（重采 evaluated_at 不推进）。源时钟相等冲突不替换；历史已验证证据不被新 unknown、缺原文件、旧 source 或不同 code/config/calendar/contract/deadline 自动撤销或恢复。partial明确失败与已保存verified success并存时，以及同源时钟/更新源时钟出现已验证冲突失败时，保留原成功事实并持久保存conflict_json，API显式evidence_conflict与conflict_evidence，比较not_ready，原ops严重；缺因果时钟不自动解冲突，audit有界轮转也不会丢失此冲突。unknown inventory 的 expected/success/failure/unknown 全null，不补0。未知的 attempt/contract/deadline/proof 可null，保留不可比较记录。

收益事件和 counts 留在原 ops；`benefit:` 域的 outbox 一律 suppressed，last_error 为 `measurement_not_paging_owner`（包括 OPS_ALERT_SCOPE=all）。不新增业务通知。启用后在同一 D1 batch 先选择 benefit current，再把 status/evidence 原子投影到原 ops_runs，原触发器也不会从旧成功重采制造恢复；原 observed_at 仍是本次观察时钟，事实源时钟在 evidence.source_at。原实时 state 的采样 freshness 与保留交付结果分开；后者不因15分钟或原30天摘要清理而过期。

每链每kind至少60个完整会话（大于完整20会话）及所有已登记日历会话保留；其它超400天会话才清理，当前/最后证据不删。每会话每kind最多100逻辑槽，每槽每kind最多64个不可变原始归一化观测，保护 current；同 proof 重采不增加audit。studies≤50、每 study imports≤20，固定日历≤400。生产启用前应由主控结合实际频率确认容量；需要长期完整研究导出时使用私有分页导出/D1原生备份。保留上限从不转换为成功证据。

## 本地验证

`node --test ops/monitoring/tests/worker-benefits*.test.mjs` 使用真实 Miniflare D1、临时本地数据与假凭据。测试不得调用真实生成、交易、部署、通知或远端 binding。默认原 `wrangler.local.jsonc` 的 bindings 全部 remote:false，禁止改用 stock config 连真实资源。

## 最终快照计数与 D1 批次边界

正常 ingest 在同一原子 D1 batch 中先选保留证据，再用 CTE 构造最终 `snapshot_json`，从该 JSON 的 `checks.status` 聚合 `counts_json`，最后触发既有 ops INSERT triggers。fallback 也从降级后的最终 checks 重算 counts，保留其它检查。ingest 回执读取实际保存计数；history 使用同一摘要，state 按同源当前检查计算。重复 snapshot 不改原历史摘要，冲突仍原子409，不先触发错误事件再回写计数。

依据[当前官方 D1 limits](https://developers.cloudflare.com/d1/platform/limits/)，db.batch 整体按一次查询计入 invocation 限额；每条 SQL 仍受100绑定参数/100000字节限制，整个 batch 受30秒及结果50MB限制。未额外添加≤6或canonical-chain ingest限制；保留原250checks/256KiB输入上限。`worker-benefits.test.mjs` 用真实Miniflare对常态6 marker及有界最大250 marker验证全部保存、最终计数一致、每条SQL/结果/本地耗时，且区分 prepare/批次statement数与实际调用数。这是本地fixture测量，不是云端时延承诺。
