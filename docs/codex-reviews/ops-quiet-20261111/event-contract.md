# 现有通知出口的事件引用合同

本合同用于本轮实施与集成核对，不代表所有历史调用方已接入。没有接入的旧运维出口必须在最终报告列明，不能因新接口存在就宣布全渠道已静默。

沿用 `data/alert_state.json` 与 `data/.alert_state.lock`。CLI 可选参数为 `--ops-event-refs`，Python 参数为 `ops_event_refs`。一个源消息只带一个事件引用与其完整正文，数组形态为兼容账本保留：

```json
[{"key":"task|condition","event_id":"stable-incident-id","phase":"active","source_run":"actual-run-id"}]
```

`phase` 仅为 `active`、`escalation`、`recovery`；`source_run` 必填但可为 null 表示未知，不能把轮询时间造作任务运行。持续同事件不随日期或轮询重新编号，真正新事件不继承旧 ACK/通知回执。通知出口不根据标题猜测故障身份或恢复。

调度侧持有健康/故障事实，显式写 `requires_action`。通知侧发送前核对当前事件；已自愈且无需行动的条目完整退出外发，正文不能残留在混合摘要中。当前 key 已换成新 event 时，旧 payload 留替代记录，不再发送旧正文；这不等于宣布业务健康。状态不可读或缺失与明确被替代分别处理，缺证据不能推断恢复。

发送侧依据实际渠道结果记录 `notified_event_id`、`notified_at`、`notified_channels`、`last_recovery_notified_event_id`、`last_recovery_notified`、`last_escalation_notified_event_id`、`last_escalation_notified`、`last_notification_attempt`。仅至少一个渠道完整受理该事件才记实际已通知；部分分段、失败、未知不可伪装完整发送。恢复仅配对该事件原本确认受理的渠道。

异步 warning/digest 的实际发送进程负责写回，不依赖原 schedule 进程仍存活。网络期间不持状态文件锁；落回执时重读、核对 key/event_id、同锁合并并原子替换。schedule 保存状态须保留该事件并发通知字段和 ACK 字段，通知侧不得覆盖业务健康/计数。迟到旧回执不得覆盖新事件。

现有外发账本追加 `ops_event_refs`、实际尝试的唯一 `attempt_id` 和 `attempted_channels`，既有 `channels` 布尔含义保持。多个渠道的同一次逻辑发送共用 attempt ID，重试另记；事件数不等于消息数。缺字段、失败覆盖不完整和无法独立核实收件均保留未知。新接口不能以 `status=sent` 单字段掩盖 `deferred=true`、零渠道受理或内部 info 记录。

旧无引用业务订阅、模型提示和日报保留原行为。旧无引用运维项也不能靠标题一刀切静音；按调用点逐项接线、验证。实际发出但回包或本地回执持久化失败的边界仍可能重复，报告必须保留，不以“严格一次送达”包装。
