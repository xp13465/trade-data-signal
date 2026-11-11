# 双账验收工具

## 实施 brief（2026-11-11，实施前固定）

基线 `49fe9bea75d6b2106445a8686a36fc3d51005abc`；独立分支
`codex/ops-quiet-accounting-20261111`。用户明确授权本次业务工具实施，交 Claude 审合部署。
共同合同 `/tmp/codex-reports/ops-quiet-20261111/acceptance-contract.md` 已纳入。

已读根治方案 plan/baseline/evidence。已有入口核查结论：

- `alert_noise_count.py` 有旧 alert 单群尺子与 `--all-groups --extra-ledger`，后者目前仅统计飞书投递；复用分类和文件覆盖，不改旧默认判据。
- `ops_business_evidence.py` 生成/评估最新单次 `trade-delivery-receipt-v1`，不是窗口/槽位分母工具；复用其原始回执字段及 `delivery_evidence._validate`，不改生产者。
- 未找到预先固定应跑槽位、按观察截止汇总的现成验收入口。因此新增薄 CLI `ops_stability_acceptance.py`，不增加服务、数据库、后台任务或新平台。

实施顺序：先用真实字段形态的合成台账证明旧视图缺 email/TG 与事件/attempt 账，
再补渠道统计；用显式计划及 SHA256 固定观察窗口、部署身份、槽位、截止与覆盖集，
逐槽汇总显式离线观察，不能把重复 attempt 当新的成功分母。读取现有格式回执，
再核对同 run/日期/部署/覆盖集合hash/输出hash/公网读取证据。人工补救、上游故障、
缺日志、漏启动、身份错误均留在原分母；窗口未满 pending，已证失败优先 fail。

通知账分开台账消息、明确事件ID、attemptID、各渠道声明受理与独立收件证据；
缺字段为 unknown，不能由 dedup key/subject 猜事件，也不能用 report 路由换收益。
旧全失败未入通知台账的局限必须暴露，可显式提供离线 attempt 记录补足。
业务/订阅另列；未知类别不丢弃。日志覆盖声明不冒充独立证明。

测试只用临时目录与合成/错误样本，先验证网络、子进程及越界写入拦截，保留基线失败；
覆盖缺输入、坏JSON、错run/日期/head/hash、迟到、人工补救、上游故障、重试/重复与渠道失败。
14自然日、至少7交易日、周频2自然轮、30日复核均仅输出建议，不声称已有生产实证。
默认只读且输出stdout；不启动业务、不通知、不新增定时器。

唯一写集：两个上述脚本、专属测试、本文件。最终自验、commit+push本分支，
准确记录测试末行和限制；不改前批交付/main/notify/schedule/Worker/采集。

## 实现及兼容合同

`alert_noise_count.py` 默认输出、阈值、分类、退出码不变。`--all-groups` 下新增
`outbound_account`，原 `groups/days` 仍是既有飞书补充视图，不能拿它代替严格全渠道账。
新账统计 email/feishu/telegram，及在 `attempted_channels` 中明确声明的额外渠道。
原始行数、distinct attempt、事件 ID 三者分别输出；不同物理台账中的同 attempt
原始重复行保留，但 distinct attempt 和事件重复首报不重复算。

复用已有 JSONL 字段 `ts/tree/tier/key/subject/channels/source/group`，采用已定追加字段：

```json
{
  "attempt_id": "actual-sender-attempt-id",
  "attempted_channels": ["email", "feishu", "telegram"],
  "ops_event_refs": [{
    "key": "task|condition", "event_id": "stable-event-id",
    "phase": "active", "source_run": null
  }]
}
```

- phase 仅 `active/escalation/recovery`；陌生值、缺 event_id/attempt_id 均 unknown。
- source_run 合法 nullable：保留已知 event，只报告 `source_run_unknown`；不会补 now。
- `channels[c] is True` 仅发送侧声明完整受理。false、未选择、尝试失败、缺结果分别列账。
  `status=sent`、`info_logged`、`deferred`、`tier` 不算外发，也不证明收件。
- 同 event/同 channel/不同 attempt 的 active 重复首次受理计 excess，并使验收工具 FAIL；
  同 attempt 的重复 ledger 不算真实重复，独立新 event 不误算。recovery 重复也单列。
  窗口前原生 state 有明确不同 active attempt 时，额外计算跨窗口重复；身份不足 unknown。
- 明确 ops refs 优先于宽泛业务标题。仅新严格账识别固定49fe9的
  `update_all.sh:424` 精确主题 `[完成] update_all <整数>min MM-DD HH:MM`，
  source=notify.py/update_all.sh 且 notice/info 才列 routine；来源不符保留 unknown。
  开发完成/业务日报仍保留，未全局改 `[完成]`。
- 可选 `root_cause_id` 标签只计同标签不同 event 数减一；无标签明确 unknown，不从 key
  或同故障域猜根因，也不声称“已评估0复发”。同 key 新 event 另列。
- 旧成功账本漏全失败 attempt、未配置 TG 可缺字段、无 refs 的旧摘要不可解析出真实事件。
  保留这些缺口；不按标题猜已恢复，不将 merged_count 当事故或发送次数。

## 离线窗口工具

没有采集/写生产/通知/定时器能力。CLI 必须显式提供：
`--manifest`、`--manifest-sha256`、`--observations`、`--legacy-ledger`、一个或多个
`--ledger source_id=path`、带时区 `--as-of`。仅向 stdout 输出 JSON。
每文件最大32MiB，窗口最多366天，最多4096槽、16384运行观察；自然日用原账本上海时间。

manifest 使用 `ops-stability-plan-v1`，这是离线分母计划，不是通知的新输入协议：

| 字段 | 内容与限制 |
|---|---|
| dataset | synthetic/replay/production/unknown；须与 observations 一致；未知不能转成生产 |
| status/generated_at/frozen_at | draft/frozen、生成时间、冻结时间；draft 可未冻结；观察后临时编制不得当预先分母 |
| window_start/window_end | +08:00 自然日边界，左闭右开；观察未满不能验收 |
| deployment | code_ref、config_sha256、evidence_sha256、verified_at；还须读取 observations 引用的原始部署采样文件核 hash；draft 未确认填 null |
| slots | 唯一 slot_id/task_id/object_id/business_date/scheduled_at/deadline/frequency；任务同一时间重复槽拒绝 |
| deadline_basis | kind/source/approved_at；仅预窗口声明批准的 business_contract 可评业务deadline；process_limit/draft 不当SLA |
| coverage/coverage_sha256 | 预先集合及排序后紧凑JSON的SHA256；实际 coverage 文件逐项集合比对；缺集合不补成功 |
| public_targets | 精确 object_id→HTTPS URL 数组；公网投递逐目标核 body hash/size、日期、同 publication run、HTTP状态与时间 |
| trading_dates | 显式交易日期；不自行猜交易日历，draft 可空；日期/周频门槛只是建议 |
| notification_sources | 预先声明账本 source ID 与渠道，不按观察后出现的文件重建分母 |

observations 引用文件路径相对该 JSON 所在目录，也可为显式绝对路径：

- `runs[]` 以 slot_id 关联现有 `trade-delivery-receipt-v1` 原件路径（receipt），不是
  `success=True`。读取原 schema、stage、ops_business/object/日期/code/config/rule、
  attempt、invocation、producer_time、有效期、输入/输出/confirmed hash及覆盖数量。
  journal 是保留的 systemctl-show 文本（InvocationID/ActiveState/Result/ExecMainStatus）；
  只读文本，不调用 systemctl。unit exit0 单独不能成功。
- 每 run 还引用 coverage 文件、public_reads（object_id/url/body/run_id/business_date/
  checked_at/http_status），声明 origin(timer/retry/manual)、manual_intervention、
  upstream_failure、journal_complete。overfit 的 publication_run_id 与 attempt_id
  分别核对，不强行同名。缺日志/来源/公开读取原件保持 unknown。
- 复用原生6对象注册表：overfit、turnover、4个 backup。backup 只核原 restore 回执，
  不当 NAV 成功。**public_fund_daily/FOF 完整业务回执尚无生产接口，保持 UNKNOWN**；
  没有为“通过”伪造可采集接口或从其他表补证。
- 同 run 多次 poll 只取最新状态；不同 attempt 不增加分母；跨槽复用同 object/run 拒绝。
  上游失败原观察保留；预算内完整重试可解除可恢复 attempt 失败，缺证不能解除失败。
  人工补救、错公开字节/覆盖、已错过业务deadline 即使后续成功也保留 FAIL。
- `notification_coverage[source]` 引用读取范围 start/end、渠道列表、台账 sha256，
  complete/includes_failed_attempts 是待复核的覆盖声明，绝不认证其真实完整性。
  旧成功台账不能诚实声明 includes_failed_attempts=true；缺全失败证据须 unknown。
- `event_states.before/after` 各引用现有 alert_state.json 映射原件的 path、sha256、
  captured_at；没有第二个状态库。恢复按同 event/channel 的既有 notified 回执或
  更早 active/escalation 受理配对。缺窗口前状态、未配对恢复、未见受理的行动事件均
  unknown。**仅边界快照不能证明中途完整性或恢复健康，missed_alerts_status 始终 unknown**，
  缺 schedule→state→refs 全链不能宣称0漏报。ACK不作为健康/收件证据。

输出同时包含旧 `legacy_alert_account`、新 `notification_account`、
`notification_lifecycle` 和固定分母 `business_account`。不合并旧 alert 0~3 与新例行0口径。
原分母包括人工、缺运行/日志、上游失败；缺实际运行不输出0故障PASS。

判定优先级：已证 FAIL → UNKNOWN → 未成熟 PENDING → 合成/回放 REPLAY_OK 或
生产标签输入 INPUTS_CONSISTENT。后两者仅表示输入契约/引用hash/统计一致，**从不输出
生产稳定PASS**；`production_stability=NOT_CERTIFIED`、独立收件 unknown 始终保留。
dataset/evidence_scope 显式输出；单独严格账没有外部声明时均 unknown。
所有来源/采样时间/预冻结/批准声明仍可伪造，本离线工具不能认证真实性。

14自然日、至少7交易日、周频两个不同自然周、30日趋势复核是建议规则；
未到月/季任务不代表验收完成。不能用本报告关闭生产严重告警。

## 可审阅证据与未激活模板

根目录 `/tmp/codex-reports/ops-quiet-20261111/accounting/`：

- `baseline-red.{json,log}`：原49fe9无 email/TG/event/attempt 严格账的原始红证据。
- `contract-before.json` / `before-parent-review-alert_noise_count.py`：父复核指出的
  active/null source_run/旧 update_all 漏计三反例；修前原件保留，不覆写。
- `synthetic-example/`：完整14槽 **合成** 原格式样例，含实际现有 record_result 生成的
  一份私有临时回执（内容仍合成），`synthetic-example-result.json` 为 REPLAY_OK。
- `missing-receipt-result.json`：同分母缺一回执，UNKNOWN，不能手填success救绿。
- `draft/manifest.json` / `draft-result.json`：42个候选槽的 **未激活/未认证** 模板，
  frozen_at、部署证明、覆盖、公网目标均未补造；trading_dates待批准。
  公募35min/FOF15min/overfit32min仅 execution-gap.md 记录的进程算术边界，非业务SLA。
  candidate_code_ref 不是生产部署身份；模板输出 UNKNOWN。
- `examples.json`：样例manifest hash与固定 as_of，可复跑CLI；新窗口/新部署须另存manifest，
  不改旧分母后声称预冻结。父原 baseline-notify-results.json 与 execution-gap 原件未修改。

专属测试直接运行 `scripts/tests/test_ops_quiet_accounting_20261111.py`，
无全库conftest；子进程运行前6项网络/DNS/进程/shell/.env/越界写guard正控，
REPO/HOME/临时数据根隔离，各CLI子进程12秒上限，输入全树hash不变断言。
原测试保留；原pytest首次默认 /dev/null 日志写被guard拒绝的日志保留，第二次仅指定临时
log_file，未放宽guard或改原断言。最终原始末行、源码hash与commit见证据 report.json。

固定源码自验原始末行：专属 `Ran 33 tests in 8.305s` / `OK`；
旧 allgroups `Ran 12 tests in 0.926s` / `OK`；旧 pytest `25 passed in 0.05s`。
另15组基线逐字节比较通过（默认JSON/文本与退出码相同；旧allgroups JSON仅去掉新增账后相同）。
日志 `verification-{accounting,allgroups,legacy-pytest}.log`，hash固定于 `verification.json`。
`native-baseline-adapter.json` 对父原通知沙箱真实格式账本只读适配，原件hash前后不变；
Telegram未记入旧账、refs及全失败attempt缺失均unknown，未拿标题猜恢复。
父指出的三个合同反例由 `contract-after.json` 同输入复验闭环，修前文件不改。

范围限制：未运行生产collector、未部署、未发通知；未认证公网请求真发生或用户收件；
未替代通知组的真实schedule→state→refs链测试或父集成full CI。原无refs通知两反例、
全失败缺台账、公募/FOF凭证缺口与自然14/30天验收仍保持原证据状态。
