# Repository-declared 日程与显式 slots 对账

本子任务基于 `30df57e6bc20d15c7ec82c14c60626476ab7d622`，仅实施离线日程合同与验收覆盖输出。
父任务 README、公募适配器、`inspect_run`、生产数据、部署与真实通知不在本次修改范围。

## 入口和范围

新增 `scripts/ops_schedule_contract.py`。日程只取
`gen_systemd_units.parse_units` 解析的 `docs/deploy/systemd-units-20260912.md`；
任务身份只取 `gen_schedule_stats.UNIT_REGISTRY`（包括 `include=False` 的自监控任务）。
未创建固定时刻副本，也不从 `TASKS.schedule` 展示文案或脚本名推断频率。

当前仓库为 45 service / 45 timer。检查 registry/service/timer 集合相等、标题重复/未解析、
显式 `Unit=` 目标、相同任务和触发时刻的重复 slot，以及重复 slot_id。
周/月/季频任务即使窗口内没有名义触发，也保留在全集中，不能靠漏登记变成完整覆盖。

输出永远限定 `scope=repository-declared`，`actual_systemd_deployment=NOT_VERIFIED`，
`execution_coverage_satisfied=null`。它不读取 systemd，不证明线上 drop-in/启停/时区、
持久化补跑、随机延迟、实际跳过或发布凭证。重复的 OnCalendar 表达式按 systemd 日历并集去重，
重复的实际 slots 则作为错误保留。

## 固定输入合同

在预冻结的 `ops-stability-plan-v1` manifest 内增加 `schedule_contract`。
CLI 必须另传 manifest **原始文件字节**的 SHA-256。
示意结构如下（`<...>` 必须由证据提供方替换，不能直接作为有效生产输入）：

```json
{
  "schema": "ops-schedule-contract-v1",
  "scope": "repository-declared",
  "timezone": "Asia/Shanghai",
  "source": {
    "path": "docs/deploy/systemd-units-20260912.md",
    "sha256": "<该文件原始字节SHA-256>"
  },
  "registry": {
    "path": "scripts/gen_schedule_stats.py",
    "sha256": "<该文件原始字节SHA-256>",
    "entries_sha256": "<canonical(UNIT_REGISTRY)的SHA-256>"
  },
  "calendar": {"path": "calendar.json", "sha256": "<文件原始字节SHA-256>"},
  "tasks": {
    "<registry.task>": {"eligibility": "unknown", "business_date_rule": "unknown"}
  }
}
```

`source`/`registry` 路径固定为本工具所在 worktree 的上述路径，不能替换成调用者挑选的小清单。
registry 同时核文件 hash、实际导入的完整 rows hash，并拒绝导入后源码变动。
`entries_sha256` 用本模块 `sha(canonical(registry.UNIT_REGISTRY))` 生成；不手抄 registry。
calendar/deadlines 的相对路径从 `--evidence-root` 解析；验收入口则相对 observations 所在目录。
工具记录 `contract_sha256`、读入文件的 `input_hashes`，并在结束前重读核 hash，普通并发变动保留 unknown。

`tasks` 必须覆盖全部 registry.task，不接受改成 unit 别名或只列有凭证的任务。
每个 task 的业务规则是调用者明确声明、随 manifest 固定的合同：

| 字段 | 支持值 | 含义 |
|---|---|---|
| eligibility | calendar | 保留日历表达式的全部名义时点；这只是显式声明，不证明脚本每次都交付 |
| eligibility | trading | 用固定交易日文件筛选名义时点；不把 Mon..Fri 当作交易日历 |
| eligibility | conditional / unknown / 缺失 | 任务保持 unknown，无法声称全集完整 |
| business_date_rule | scheduled_date | 业务日期等于名义触发的上海日期 |
| business_date_rule | previous_trading_date | 使用日历中严格早于触发日的最近交易日，跨窗口时须有覆盖该日期的日历 |
| business_date_rule | 其他 / 缺失 | 保持 unknown，不猜 T/T+1 或夜盘归属 |

日历文件格式（coverage_end 为开区间）：

```json
{
  "schema": "ops-trading-calendar-v1",
  "source": "<日历来源/版本说明>",
  "timezone": "Asia/Shanghai",
  "coverage_start": "2026-10-30",
  "coverage_end": "2026-11-16",
  "trading_dates": ["<由该来源确认的YYYY-MM-DD交易日期>"]
}
```

日历必须完整覆盖观察窗；不得缺失、hash 漂移、日期重复或越界。
plan.trading_dates 必须与日历在观察窗中的集合严格相等（重复亦不通过）。
空交易日集合只表示该来源声明窗口内无交易日，不能用周一到周五兜底；日历声明是否真实完整仍需外部审核。
若 previous_trading_date 缺少前置日期，任务保持 unknown。

## SLA 单独提供，不能用 timeout 补齐

可选 `schedule_contract.deadlines={"path":"deadlines.json","sha256":"<原始字节hash>"}`，
其文件必须明确给出业务合同及窗口开始前的批准时间：

```json
{
  "schema": "ops-business-deadlines-v1",
  "kind": "business_contract",
  "source": "<业务SLA合同来源/版本>",
  "approved_at": "<带+08:00时区的批准时间>",
  "after_seconds_by_task": {"<registry.task>": 3600}
}
```

上例的 3600 **仅解释字段单位，不是任何真实任务 SLA**。没有该文件、批准时间不合规、
任务规则缺失或 hash 错误时，对应 deadline 为 null / unknown。
`TimeoutStartSec=600` 不生成“触发后 600 秒”的业务截止时刻。
有显式合同才按 `scheduled_at + after_seconds` 计算并严格核 slots.deadline。
本版只支持明确的相对秒数合同；绝对交易日收盘、跨交易日预算等其他 SLA 需继续 unknown，不能自行转换。
批准来源及日历来源都是固定的外部声明，不独立认证审批真实性。

## 对账结果与验收接入

`denominator_completeness`：

- `complete`：来源/日历/任务规则均已固定且可解析，slot 的任务、时点、业务日期、显式 SLA（若有）逐项匹配。
- `incomplete`：上述全集已知，但有漏槽、多槽、重复时点或字段不匹配。
- `unknown`：缺少合同/日历、格式或 hash 不合规、条件任务或未知语义；同时保留已知部分的缺槽/多槽差异。

独立的 `business_deadline_coverage` 只有完整对账且全部任务有有效显式 SLA 才为 complete。
日程分母 complete 不会把缺少业务 SLA 或发布凭证的部分变绿。
当前真实源码中的 heartbeat、r2-consistency、cloud-unit-patrol 有 ConditionPathExists，
本版无法证明运行条件，保留这 3 项 unknown；不能在 tasks 中改成 calendar 强行消除。

`ops_stability_acceptance.py` 仅接入 plan 校验上限及覆盖输出/输入问题：

- 完整 14 天名义时点会超过原 4096 上限，调整为共用的 250000 上限，窗口仍限制 1..366 整日、上海时区。
- 旧 manifest 无 schedule_contract 时保留原逐凭证 verdict（合成可 REPLAY_OK），但分母继续 unknown。
- 显式请求 schedule_contract 时，任何分母或 SLA 不完整都进入 input_problems，不能 REPLAY_OK/INPUTS_CONSISTENT；已有证实失败仍优先 FAIL。
- schedule 的文件 hash 并入验收 input_hashes；执行覆盖和生产稳定认证仍保持未知/NOT_CERTIFIED。
- `inspect_run` 未改；父任务负责公募适配器及其业务凭证。

## 离线命令与支持边界

```sh
python3 -B scripts/ops_schedule_contract.py \
  --manifest /tmp/offline-plan.json \
  --manifest-sha256 <manifest原始字节SHA-256> \
  --evidence-root /tmp/offline-evidence
```

命令仅向 stdout 输出 JSON；退出码 0 只表示日程分母 complete，不是 SLA、执行或部署认证；其余返回 2。
验收脚本仍按其原 verdict 规则返回退出码，并额外阻止显式日程/SLA 合同缺口通过。

支持当前仓库使用的 OnCalendar 子集：固定上海时区；星期名称、列表和正序范围；
`年-月-日 时:分:秒`（省略日期时为每日）；数字、通配符、列表、正序范围、正整数步长。
日期按真实月份长度迭代，跨月/跨年/闰年不复制固定日程。未支持的表达式、相对启动计时器、
条件/断言/ExecCondition 一律 unknown。只统计名义日历时点，不模拟完整 systemd 运行时行为。

## 验证记录

所有测试使用临时目录/离线输入，未运行生产 CLI、部署、通知或采集器。
测试用的交易日与 SLA 均标为 synthetic，不写入任何生产合同。

- 初版日程行为测试：`68 passed in 0.87s`
- 补充 registry 导入漂移/并发变动/验收接入/大于4096槽验证后：`72 passed in 0.96s`
- 最终相关回归及独立静态核对见本文件末尾。

最终相关回归命令：

```sh
python3 -m pytest -q \
  scripts/tests/test_ops_schedule_contract_20261111.py \
  scripts/tests/test_ops_quiet_accounting_20261111.py \
  scripts/tests/test_ops_monitor_registry.py \
  scripts/tests/test_ops_business_evidence.py \
  scripts/tests/test_ops_quiet_schedule_20261111.py
```

原始末行：`181 passed, 22 subtests passed in 10.39s`。
原始日志保存于 `/tmp/codex-reports/ops-schedule-contract-20261111-pytest.log`。

独立算术复核未调用 `expand()`，直接读取当前 OnCalendar 表达式，按每日日历和小时/分钟项计数。
2026-11-02 至 2026-11-16（右开）45 个 timer 共 7045 个名义时点，逐 timer 与本工具一致。
在**所有 task 人工声明 calendar 的合成探针**中，3 个条件任务仍保持 unknown，
其余 42 项计 5673 槽；这不是生产业务应跑次数，也不证明真实交易日过滤或运行条件成立。
分母与 SLA 均为 unknown。
独立 AST 定位后源码片段逐字比较确认 `inspect_run` 与基线一致。
原始末行：`INDEPENDENT_CHECK: PASS (45 timer counts; inspect_run unchanged)`。

剩余边界：未提供真实完整交易日历、逐任务业务日期/eligibility 合同、明确业务 SLA、
条件任务运行事实、实际部署证据或业务发布凭证。月季频零槽仅表示该窗口无名义触发，
不表示完成过自然验证。上述缺口交父任务/Claude 审核，不能用本次离线测试补成生产证明。

## 独立复核 P2 修复：末日槽位的跨窗 SLA

Tesla 独立复核发现真实 P2：名义槽位 `fetch_news / 2026-11-15T23:45:00+08:00`
加显式合成 3600 秒业务合同，日程对账接受次日 `2026-11-16T00:45:00+08:00` deadline，
但旧 `validate_plan` 要求 deadline <= window_end（`2026-11-16T00:00:00+08:00`），
导致同一份固定计划在验收入口被拒绝。这是保守拒绝错误，不能靠漏掉末日槽位、
裁剪 SLA 或反复扩展日程窗修复。

原始 P2 报告逐字归档于本目录 `schedule-independent-p2-original.json`，其 verdict/历史结论原样保留。
原 `/tmp/codex-reports/ops-evidence-closeout-20261111/schedule-independent/` 下的 report.json、
independent_probe.py、probe-results.json、probe.log、fixtures/cross-midnight-plan.json 均未修改。
五份 SHA-256 和修前复现保存于 `/tmp/codex-reports/ops-schedule-cross-window-20261111/`。

本次修正只影响 plan 校验/覆盖输出及其测试文档；`inspect_run` 不变，
不覆盖父任务在 `940dc2d4d` 集成的公募适配器。具体语义如下：

| 边界 | 修后语义 |
|---|---|
| 槽位归属窗口 | 仅要求 `window_start <= scheduled_at < window_end`；窗外触发仍拒绝 |
| 业务 deadline | 保留完整 `scheduled_at + 显式SLA`，可跨出日程窗；正预算上限与日程合同共用 366 天 |
| `as_of` | 业务凭证可在日程窗后产生，但 evaluated_at 必须不晚于 as_of；不能用未来凭证 |
| 未收到凭证，as_of < deadline | pending；窗口时间跨度已足够也不能通过 |
| 未收到凭证，as_of >= deadline | unknown；缺证据不能凭空当作实证迟到 |
| 有有效凭证，实际 completed_at <= deadline | 依原证据链核验；不强迫已完成任务等到 SLA 到期 |
| 有有效凭证，实际 completed_at > 已批准deadline | fail；晚 1 秒亦失败，不能用晚轮询时间替代实际完成时间 |
| 缺少明确业务 SLA | unknown；不会因扩大可观察时间而把 timeout 当成 SLA |

新增 `observation_windows` 覆盖元数据：
`slot_membership` 明列 `[start,end)`；`business_evidence` 明列 as_of、latest_slot_deadline、
deadline_horizon_elapsed、post_window_deadline_slots；`notification_account` 明列原有统计窗与有效截止。
`elapsed_window_mature` 仍只表示日历跨度/周频条件，既不表示所有 SLA 到期，也不认证业务覆盖。
通知统计没有随跨窗 SLA 暗中扩大；不能把原窗口的静默统计说成覆盖了窗口后的业务完成阶段。

上述 3600 秒只来自复核的合成合同，不是生产业务 SLA。
repository-declared / NOT_VERIFIED / 条件任务 unknown 的边界保持不变。

针对性回归：`python3 -m pytest -q scripts/tests/test_ops_schedule_window_20261111.py`。
原始末行：`19 passed in 2.46s`。

独立探针复验在新的 `ops-schedule-cross-window-20261111/recheck/` 目录中执行：
保留原脚本副本，只将跨窗反例从“必须拒绝”改为“必须接受且保留完整 deadline”的断言，
其余检查继续执行；原始复核目录及其 source 快照不动。
原始末行：`INDEPENDENT_PROBES: 16 checks; cross-window P2 fixed with full deadline preserved; zero production calls`。

最终相关回归：前述五个测试文件，加 `scripts/tests/test_ops_schedule_window_20261111.py`。
原始末行：`200 passed, 22 subtests passed in 12.21s`。
日志：`/tmp/codex-reports/ops-schedule-cross-window-20261111/pytest.log`。
原 P2 报告归档 SHA-256：`50664e0c87acdf47e4214f74e0cb5994f900f3deb5f2c3ad280aecb8af881627`。
