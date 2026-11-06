# 全群运维通知补充视图（2026-11-06）

`scripts/alert_noise_count.py --all-groups` 只读现有通知台账，补看落在
alert、report、follow、agent_done 四群的运维通知。旧命令不加新 flag 时，
仍按 alert 单群机制噪音每天 0~3 条判定，旧 JSON 与退出码不变。
补充视图不设新阈值、不作健康或 PASS 判定，也不写 `alert_daily.json`。

## 最小数据合同

来源沿用 `notify.py:_record_ledger`、`alert_meter.py` 和旧尺子的 JSONL：

| 字段 | 读取语义 |
| --- | --- |
| `ts` | 本地无时区的 `YYYY-MM-DD HH:MM:SS` 或旧尺子支持的日期；不转换时区 |
| `group` | 目标/声明群；仅 `channels.feishu=true` 能证明成功投递。缺失或陌生群进入 unknown 桶 |
| `subject/tier/noise_class/source` | 识别通知类型；subject 缺失/非法、未知标签、无法识别的组合显式列为未知 |
| `channels.feishu` | 严格布尔 true=成功；false=未成功，不能区分未选/未配置/发送失败；缺失、非布尔=未知 |
| `merged_count` | 非负整数（不接受 bool 或数字字符串），只累加为 **declared merged 槽位**；缺失/非法行另列 |
| `tree/key` | 不用于跨文件消息消重。相同 key/主题/时间并不足以证明同一发送 |

台账写点只在至少一个渠道成功后登记；**全渠道失败通常不入账**。
本视图不读发送 result-file、摘要 buffer、正文或实时故障状态，不能覆盖未入账失败。
恢复/摘要/升级都是窗口内历史通知，不代表当前仍未恢复。消息数和声明槽位都不能称为独立事故数；
`current_unresolved_incidents` 固定为 null，不能从通知流水推断该值。

## 识别顺序与边界

1. 校验 subject；未知非空 `noise_class` 进入 unknown，保留原值和来源行号。
2. 现行业务/开发主题前缀（如 `[买卖点信号]`、`[盘中…]`、`[每日速递]`、
   `[情绪速递…]`、`[完成]`、`[codex]`、`🤖 agent …`）及
   `codex_notify_bridge.py` 的完成转发算业务。正文/尾部提到“告警/恢复”不改变归类；
   若同时带运维标签或 critical/warning/digest 档位，则显式列为冲突未知。
3. 已知标签映射复用旧尺子。否则依次识别摘要、warning 聚合、升级、恢复
   （含 `[72h恢复]`）、方括号内告警/监控前缀、`[状态说明]` 和既有常态提示主题。
4. critical/warning 档位或明确巡检来源 `schedule_monitor.sh`、`monitor_72h.sh`、
   `check_failed_units.py` 识别为一般运维通知。
5. subscribe/agent_done 档位，或 `brief_push.py`、`daily_summary_email.py` 的普通输出
   算业务；其余保留 unknown。普通 `notify.py` 来源、所在群名本身均不足以判别。

补充视图复用已有标签/主题事实，不运行旧 repeat 归一化来推断新事故。
所有规则是有限识别，未来新增主题可能落 unknown；不会把未知当“健康零故障”。
未知/缺失 tier、未知 group、投递字段缺失、非法 merged_count 亦列入 `uncertainties`。
已识别的运维通知即使有这些不完整字段仍保留其记录计数。

## 用法与覆盖范围

以下路径是调用形式示例，需由调用者提供真实台账；此实现未读取生产数据：

```bash
python3 scripts/alert_noise_count.py --all-groups --date 2026-11-06 --days 2 \
  --ledger /tmp/example/run/alert_ledger.jsonl \
  --extra-ledger /tmp/example/signal/alert_ledger.jsonl --json
```

`--ledger` 默认仍是 `$REPO/data/alerts/alert_ledger.jsonl`。`--extra-ledger` 可重复，
必须与 `--all-groups` 同用。默认不搜索兄弟树、不继承 `ALERT_METER_TREES`；需要多树时显式列出
每个文件。这避免一个文件存在就声称全树覆盖，不调用 `alert_meter --recount`。

同路径、符号链接和硬链接以设备号/inode 去重，重复项在 coverage 中指明 `duplicate_of`。
不同物理文件中的相同内容照常分别计数；复制或跨树重放可能重复，不能无依据扣除。
每个非重复文件列出读取状态、解析记录数、坏行数、文件观察日期范围和窗口内行数。
空文件、缺文件、不可读、坏 JSON/非对象行及无法归日行均保留状态/计数。
文件日期范围的两端不证明中间日期完整。`coverage.all_trees_verified=false` 始终明确这一边界。

## 输出与退出码

人读输出和 JSON 都有逐日及窗口合计。JSON 的 `groups` 与每个 `days[].groups`
包含四个已知群加 unknown 桶，每群结构一致：

- `ledger_rows/no_data/business_rows/unknown_rows`：窗口内台账记录及可观察数据状态。
- `operations`：运维记录 `rows`、飞书成功 `feishu_sent`、未成功
  `feishu_not_successful`、未知 `feishu_unknown`，以及 `declared_merged_slots`、
  `merged_count_missing_rows`、`merged_count_invalid_rows`。
- `by_kind`：operations、recovery、digest、warning_batch、escalation、routine、repeat
  各自同样的记录/投递/槽位计数，零值也保留。三种投递结果之和等于该类型 rows。
- `uncertainties` 位于顶层，含实际文件、原始行号、主题/标签/来源与原因；无法归日的记录
  在这里和 coverage 中保留，不混入窗口内计数。

`data_status=observed` 表示所列文件可读且窗口内记录均可解释，退出 0，
**只表示视图生成成功**，即使飞书存在未成功记录也不会宣称健康。
`partial`（缺文件/空文件/坏行/未知等）或 `no_data` 退出 2。
本模式不使用退出 1 作噪音 FAIL。旧模式仍保持 0=PASS、1=FAIL、2=测不了。
某群无台账数据标 `no_data=true`，零运维记录不证明无故障；未声明槽位的数字总和仅是已知部分。

## 定向验证与撤回

可移植的 stdlib 测试直接运行，避免仓库共享 conftest 的环境垫片：

```bash
python3 -B scripts/tests/test_codex_alert_all_groups_20261106.py
```

测试先正控验证临时 audit 陷阱拦截 socket、DNS、子进程、shell、`.env` 访问及临时目录外写入，
再经真实脚本 CLI/临时 JSONL 验证旧默认三态、四群运维/业务区分、历史跨日、未知、缺失、
坏行、投递失败及路径/硬链接去重。全部输入是合成数据，不代表生产验收。
该组不触碰 FAPI、门限或 skip；原 FAPI 内存测试的已知 NOT_ALL_GREEN 不在本轮范围。
全量 scripts/tests、统一 lint、真实网络/SSH/通知/上传/采集/回测及部署均未执行，交父任务统筹。

使用层面停止传入 `--all-groups/--extra-ledger` 即回到旧命令。
源码撤回时只删除本次补充视图、CLI 两个参数与分支，并将 load_records 恢复为旧签名/原循环，
以及撤下本任务新增测试和本文；共享工作树应逐块撤回，不整文件覆盖其他作者改动。
