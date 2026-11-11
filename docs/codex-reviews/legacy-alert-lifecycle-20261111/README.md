# S06 / monitor-heartbeat 生命周期迁移

用户授权 Codex 独立分支实施；父任务整合，Claude 复核/合并/部署。
基线：`30df57e6bc20d15c7ec82c14c60626476ab7d622`。
父任务随后明确扩大授权，本分支已补齐 schedule 接口和旧测试迁移，待固定 head 独立复验。

## 实现

- S06 不再以 `s06_fresh_alert_state.json` 的「曾入队」签名作为投递凭证。
  相同输入对象的一次持续过期对应一个事件；重复轮重交现有 notify，队列自身按 refs
  去重，回执按渠道保存。真实健康观察在共享锁内更新 `requires_action=false`；
  warning/digest 在发送前用既有 gate 作废旧事件。仍不发恢复邮件。
- heartbeat 保留停摆首报；同一持续故障不再每 1h/3h 重复全渠道直发，只补未受理渠道。
  ACK 不是恢复，也不是未送达渠道的回执。恢复后再故障建立新 ID，不继承旧 ACK/回执。
  部分失败/未知返回 2，不把任一渠道成功误当所有渠道完成。
- `ops_legacy_events` 仅适配两个 producer 的健康事实和现有 notify CLI：复用
  `_ops_state_lock/_ops_read_state/_ops_write_state`，不另设队列/发送器/回执状态机。
  读取判断在同锁内完成，避免慢的旧观察覆盖新观察；同事件保留 ACK/receipt/claim。
  专用 module 实例只用于 state API 的运行根绑定，不修改共享 notify 模块的全局变量。
- 通知显式传运行根 `REPO` 与来源，结果只读 `--result-file`；返回码/输出文本不作为送达证明。
- 共享文件损坏不覆盖。实际故障在状态未知时走立即 critical（不建无 refs warning）且
  返回未知/失败，允许重复，优先不漏真故障；不能宣称这种降级具备事件去重。
- dry run 不写状态/队列；未来心跳、乱序/重复/超前快照不能证明恢复。

## 已配套的 schedule_monitor.sh 接口

1. 导入 `ops_legacy_events.owns_event_key`，通用恢复检测跳过其所属 key。
   前缀为 `producer_s06|` / `producer_heartbeat|`；不要借用 `72h_` 等别人的保留命名空间。
2. `save_alert_state` 在已持 `.alert_state.lock` 后，对这些 key 使用磁盘**完整最新值**。
   不仅保存 ACK：producer 的 `status/requires_action/event_id/observation` 也不能被旧快照覆盖。
   如果磁盘上已不存在该 key，不得从旧 schedule 快照复活；并保留并发新增的独立 key。
3. schedule 的通用告警/恢复/升级路由不应代发这些 producer 自己负责的通知。
4. 用整段 schedule 执行验证：未观察不等于恢复；慢 schedule 保存不能覆盖 producer 的
   恢复→新故障；并行 ACK/逐渠道回执不能被丢失。仅验证 helper 或 grep 不够。

真实 schedule 源码函数的临时隔离复现证明：当前基线会把未扫描 key 误恢复，并且会把
新事件写回成旧事件。复现与日志保存在交付证据目录 `legacy-lifecycle/`。
随后已修改 schedule 并补真实跨模块测试；notify.py 未改。原失败证据保留，当前修复结果见下。

## 历史迁移边界（不得静默清空）

旧无 refs warning/digest 只有标题、正文和时间等，不能可靠证明对象、事件代次或健康观察。
即便出现“S06”相同标题，也不允许当成同事件删除、补造 refs 或补造送达回执。本次不改它们；
测试明确验证旧无 refs 内容仍走原有外发路径，故历史存量可能继续发出过时提醒。
`data/s06_fresh_alert_state.json` 与旧 heartbeat 去重记录不再作为新事件静音依据，不自动删除。

上线前父任务可以在短暂停止相关 flusher、持其原生锁的窗口内备份具体队列和 pending_delivery；
逐条核对完整来源/原字节 hash/对象/故障时间/真实健康证据后另做精确迁移方案。
无法建立唯一映射的条目保持 unknown；不得按标题或时间批删，也不得改写已部分发送批次的
渠道回执。没有这些证据，本次不提供“安全自动清空历史”的承诺。

## 验证

真实 producer → 原 notify.main → 原 warning/digest/ledger/state → 替身 SMTP/TG/飞书受理。
网络/进程/凭据 trap 有正控。无生产调度、网络、真实通知或生产路径写入。

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 python3 -m pytest --noconftest -q \
  scripts/tests/test_legacy_ops_lifecycle_20261111.py \
  scripts/tests/test_notify_ops_quiet_20261111.py
```

基线两原始反例：`2 failed in 0.18s`；producer 初版组合：`69 passed in 3.59s`。
最终五文件组合（另含原 #241、schedule 和 schedule→notify 接口）：`134 passed in 2.58s`。
覆盖新故障/恢复/队列丢失/部分渠道失败/同事件ACK/旧ACK/腐损状态/并发观察/真实发送中恢复。
发送中恢复导致 claim 失效时保留 `unknown`，不宣称成功或接收者一定收到。

旧合约迁移前：`test_241_s06_fresh_sent_criterion_20261009.py` 得到
`7 failed, 12 passed in 0.09s`，原始失败日志保留。扩大授权后已迁移文本判据/本地签名
断言为真实 producer→notify 的失败重试、队列丢失、恢复和新故障；保留通用解析用例。
没有删除失败语义或整文件 skip。上面的最终组合已包含迁移后的旧文件。

另执行完整 schedule Python heredoc（非剪裁函数）+真实 S06/heartbeat/notify：
5 次入口运行、每次 5 个网络/进程/凭据正控；停摆首报仅 3 个渠道受理，后续轮次无新增
外发，S06 恢复如实写入共享事件。systemd、资源、云端查询与其它不相关 producer 是明确
替身；不等于整段生产 shell 或线上自然链。首次 harness 出现重复 argv 参数 TypeError，
修正测试构造后独立 v2 重跑通过，原日志保留 `whole.log`，不覆盖失败证据。

未执行：全仓完整回归、远端 CI、部署、真实告警收件/自然链稳定验收。
原外审 `independent/report.md`、`reproduce.py`、`results.json` 未覆盖修改。

仓内 evidence 文本副本仅去除 pytest 尾随空白以通过 diff 检查；原始字节日志仍在交付证据目录。

最终扩大影响面后的组合执行末行：`490 passed, 4 skipped in 17.43s`。
四个 skip 是已有 CFU 套件的条件性用例，不计为通过；未声称全仓测试全绿。
AST 测试夹具补齐新归属函数，并将其必备依赖分别校验；最后仅强化测试收集守卫后单跑
`test_309_conclusion_email_20261026.py`，详见 evidence/harness-guard-final.log。

schedule 影响面首轮缺 PYTHONPATH 收集失败，第二轮 29 fail 中有新归属函数未载入及
CFU 子进程因 HOME 隔离导致 pytest 不可导入。修正只涉及两处 AST fixture，以及
CFU fixture 自身 PYTHONPATH 显式加入当前 pytest 的 site-packages；没有为测试修改
生产逻辑。之后该组 `356 passed, 4 skipped in 14.68s`，并纳入上述 490 组合。
所有原失败均保留在 /tmp/codex-reports/ops-evidence-closeout-20261111/legacy-lifecycle/。
