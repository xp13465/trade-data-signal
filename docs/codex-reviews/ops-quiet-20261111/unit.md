# CFU 两条核心链共享首报（2026-11-11）

用户明确授权独立分支 `codex/ops-quiet-unit-20261111`，基线 `49fe9bea75d6b2106445a8686a36fc3d51005abc`。本组仅改 `scripts/check_failed_units.py`、专属 `scripts/tests/test_ops_quiet_unit_20261111.py` 和本文；不改 schedule、notify、cloud_unit_patrol，不部署，不运行生产任务或通知。

## 问题与实现

CORE-DUP-01：同一真实失败 invocation 同时进入 CFU 集合告警和 schedule 事件告警，两条入口独立去重，导致各渠道两次首报。新增可选参数：

```text
--ops-unit-event-refs '{"trade-public-fund-daily.service":{"key":"public_fund_daily|unit_exit!=0|124","event_id":"schedule:...","phase":"active","source_run":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","exit_code":124}}'
```

只接 `trade-public-fund-daily.service`/`public_fund_daily` 与 `trade-overfit-monitor.service`/`overfit_monitor`。采用 Mendel 定稿合同：schedule 负责健康事实、事件身份和成功保存；CFU 核验当前 systemctl 原属性中的真实 32hex InvocationID、failed 状态及退出码，并核验磁盘 `alert_state.json` 中同 key/event/source_run 的 active + requires_action。退出码复用 `unit_truth.derive_exit_code`，包含 timeout→124、signal→128+signal；不读 ledger，不用 last_run 或当前时间补身份，不接受缺原退出码时的推测默认值。

核验通过后删除映射中的 `exit_code`，逐事件将精确 `{key,event_id,phase,source_run}` 四字段传给 notify 的 `--ops-event-refs`。notify 在原 `.alert_state.lock` 下领取 `notification_claim` 并记录实际 receipt；CFU 不写健康、receipt、claim 或 ACK。notify 再核验事件，处理读取与发送之间的交错。

原 `CHECK_FAILED_UNITS_FAIL` 输出、unit 名、故障状态和非零退出仍保留。已接入核心项仅从 legacy 通知正文、候选和集合签名中同步移除，其他 failed unit / watchman / D1 路径仍保留。坏映射、缺 InvocationID、退出码不符、缺失或损坏 state 均记录诊断并回退原集合路径，受原有每日签名规则约束。无新参数的独立 CLI 行为保持。

## 结果与时限

- 匹配事件至少一真实渠道完整受理，且原磁盘 receipt 已持久化：rc1；保留 partial 的各渠道状态，不声称全渠道受理。已有匹配正面 receipt 的 suppressed 也 rc1，NOTIFY_SENT=0。
- 匹配且未过期、剩余租约不超过 180s 的 active claim：rc1（暂缓等待），NOTIFY_SENT=0，不写 CFU 每日签名；下一轮重新核验，不宣称已送达或健康。
- failed/unknown/缺结果/假受理/回执未落盘/被替代或恢复后不匹配原 active 故障：rc4，保留观测，不在同轮补发另一份 legacy 正文。真正传输已受理但 receipt 落盘失败仍计本次 NOTIFY_SENT，退出保持 rc4。
- 新事件通知调用超时 30s/事件，与 schedule 的单事件发送约束一致；最多两个新事件。不改变既有 systemctl/legacy 调用时限，整体仍受父 schedule 的 120s 子进程上限。超时不能解释为未外发，notify 原 claim/未知结果仍需后续核对。
- dry-run 不调用 notify、不写 state/signature；生产自然运行和部署验收由父负责。

## 独立验证

专属测试运行完整 CFU CLI 子进程（未替换 CFU 函数），经实际 notify CLI、原共享 state/claim/receipt 到 SMTP/Telegram/飞书低层传输桩。真实 schedule 内嵌 Python 仅 AST 提取实际 `_quiet_core_unit_refs`、保存合并和实际发送/路由函数执行，不运行业务 shell 主体。systemctl 样本注入外，另有本地假 systemctl 可执行文件验证实际 Key=Value 解析路径。每个子进程启动前拒绝真实网络、生产凭证和无关子进程，正控证明防线生效。

固定 49fe9 原 CFU + 原 schedule 调用 + 原 notify 基线：公募、overfit 各自每渠道 2 次模拟受理。新 schedule 映射 → 新 CFU CLI → 新 notify → schedule 发送入口，再次 CFU poll：每渠道各 1 次，原业务仍 active。不是只测试一个伪 CFU 发送函数。

覆盖两个目标/同批两个事件/同 key 新事件/持续事件新 invocation、完整混合正文与签名、真实退出码缺失、旧 notify 不支持新参数、独立 CLI、dryrun、全渠道失败后重试、部分受理、回执写坏、state 交错缺失/替换/恢复、实际 CFU 与 schedule 并发 claim、错误结果与假 receipt/claim。

本地证据根：`/tmp/codex-reports/ops-quiet-20261111/unit/`。

- `test-final.log`：**42 passed in 12.25s**。
- `regression.log`：**200 passed in 3.67s**（原 CFU、allowlist、unit_truth 及发送判据相关选集；非 full）。
- `dependencies/provenance.json`：独立冻结 Mendel/Kant 工作中源码 SHA256，未改他们源码。两个依赖仍需父整合，CFU 分支单独配旧 notify 的负控为 rc4，不假报成功。
- `entry-chain-results.json`：基线/新链/混合/并发的逐渠道受理数及原始 CLI、wire 文件路径。

复跑：在整合包含新 schedule/notify 的树直接运行专属 pytest；独立本分支可用 `OPS_QUIET_NOTIFY_SOURCE`、`OPS_QUIET_SCHEDULE_SOURCE` 指向冻结源码，`OPS_QUIET_BASELINE_ROOT` 指向 49fe9 archive。使用 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest --noconftest -q scripts/tests/test_ops_quiet_unit_20261111.py`。未提供尚未合入的依赖会明确 skip 集成用例，不能把 skip 当通过。

## 未消除的边界

缺身份/缺 state 或未传参数时保留 legacy，可继续重复；这是不凭空吞故障的兼容退路。partial 仅表示部分渠道完整受理，未受理渠道的重试政策仍归 notify。有效 claim 的拥有者崩溃需要后续 poll 和租约到期再处理；外部受理后回包丢失、回执损坏或过期 claim 重试无法保证严格 exactly-once。本组只修两条链的明确共同入口，不治理所有历史业务任务，也不声称已获得生产自然最忙尾部或期限验收。
