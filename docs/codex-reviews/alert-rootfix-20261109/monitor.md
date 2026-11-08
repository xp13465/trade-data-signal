# 监控投递可靠性与安全诊断（本地候选，未部署）

用户明确授权先三验再修复；Claude 最终审核、合并与部署。本次独占 scope 的业务修改由 Codex 实施。隔离目录 `.claude/worktrees/codex-reviewer`、分支 `codex/reviewer`；起始 head `d42a026a7aedf012f782defbce2ff7284acc2bcf`，父合并 nextday 后实施基线 `ad78a7adbc68d263e3ae13e70540a3c959e3d944`，业务 base `8118feef3`。没有 main、生产、push 或 migration 操作。

## 三验与结论边界

实施前证据原子写入 `/tmp/codex-reports/alert-rootfix-20261109/monitor-root-cause.json`。

1. **问题真实**：父当前生产取证显示 25 次采样中 4 次失败（2 次 TimeoutError、2 次 HTTP503）；独立读取当前主键查询产物，HTTP200、D1 success=true、查询结果为空，不能把失败当成已入库。生产随后自然成功不构成根治证据。证据：同目录 `collector-failed-ids-current.private.json`，不复制私有快照到仓库。
2. **可定位的应用缺口**：`scripts/ops_monitor.py` 的 `request_http` socket5s，`network_bounded` 上传总预算8s，`run_once` 默认20s、只调用一次网络投递；`worker/ops.js` 的 ingest catch 和总 catch 把异常压成通用503，诊断丢失。旧行为真实故障注入红测：503→200在首次503退出；服务端提交后丢回执退出；真实5s socket timeout 在5.075s退出。
3. **修复机制可达**：修改前已有真实 SQLite 和 Miniflare D1 验证同 ID/同哈希幂等、冲突409、事务/INSERT触发器约束（`monitor-mechanism-before.log`、`monitor-d1-before.log`）。修改后继续以同一 handler、全部迁移、真实 SQLite/本地D1验证，未放宽幂等。

**已证实并修复的是单次失败没有恢复机会，以及存储异常安全诊断断点。历史间歇性网络/D1的底层原因仍 unknown；没有证据声称平台故障已根治。** 实时 tail 尚未提供对应失败事件，不把连接成功当根因证据。

## 候选实现

- 一个 `--once` 只采集一次、验证一次、缓存一个快照；在同一个受限网络子进程中重用同一个不可变 payload、ID。最多3次尝试，退避0.15/0.30s，socket每次最多5s，启动/读写/退避/进程清理仍在原有最多8s上传总预算内；原20s once及采集预留不增加。没有后台队列或跨轮补采。
- 只对 timeout、连接中断/部分网络错误、HTTP502/503/504重试。HTTP400/401/403/409/500、未知或错误成功回执、协议错误、响应超限、TLS验证/配置错误不重试。HEAD保持一次。
- 新 Worker 返回 `error_kind` 白名单：`storage_transient`、`storage_quota`、`storage_configuration`、`storage_constraint`、`storage_overloaded`、`storage_resource_limit`、`configuration`、`unknown`。已知配额、配置、约束、资源/过载类别不触发采集器自动重试。旧Worker/边缘层无类别503保持unknown语义，仅在既定预算内重试，不能据此归因D1瞬态。
- Worker失败API与结构化日志只包含固定error码/类别、服务端生成的request UUID、已通过完整校验的snapshot UUID（未验证的不记录）。不打印异常原文、cause、SQL、token、headers、Cookie、env、stack。诊断主键读也失败时保留原batch错误类别。
- 采集器响应读取上限4096字节；仅提取白名单error/error_kind。未知值、任意字段/正文不进report或stdout；有效成功仍必须 `accepted=true` 且snapshot ID匹配。重复JSON字段、错ID、非JSON和超长成功响应拒绝。网络错误也只投影固定类别。
- 不改检查阈值、告警策略、通知渠道或数据库模式。测试禁止真实通知。既有可选benefits事务和outbox策略原样保留；业务通知仍归原告警链。

## 验证证据

红测 `/tmp/alert-monitor-red.log`：2 failed；真实5s红测 `/tmp/alert-monitor-timeout-red.log`：1 failed（旧行为TimeoutError）。Worker诊断红测 `monitor-diagnostic-red.log`：缺少error_kind。上述红测均在业务源码改动前运行；5s补充红测通过独立临时模块加载固定起始blob运行，没有覆盖worktree源码。

最终定向命令（全量scripts/tests按用户要求留父整合后统一跑）：

```sh
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q -s scripts/tests/test_ops_monitor.py scripts/tests/test_ops_monitor_delivery.py scripts/tests/test_ops_monitor_registry.py ops/monitoring/tests/test_benefits.py
node --test ops/monitoring/tests/worker*.test.mjs
```

本地Miniflare复用已装依赖的临时node_modules链接，无裸npx下载、无生产凭据。链接不提交并在收尾移除。类型核查使用当前 `@cloudflare/workers-types@5.20261108.1` 的 D1Database/D1DatabaseSession、prepare/batch/first及first-primary；没有添加不支持的D1 timeout/AbortSignal或Promise.race写重试。

原始测试末行与日志：

- `/tmp/alert-monitor-final-python.log`：`64 passed, 66 subtests passed in 31.15s`。
- 随后只增加客户端约束/过载/资源类别拒重试子场景，复验 `/tmp/alert-monitor-final-delivery.log`：`6 passed, 25 subtests passed in 28.85s`（这6项是上述64项的子集）。
- `/tmp/alert-monitor-final-worker.log`：`ℹ tests 80` / `ℹ pass 80` / `ℹ fail 0` / `ℹ duration_ms 15578.944667`。包含真实SQLite和Miniflare D1，无跳过。
- 真实8s上传场景实测：首503→200约0.24s、同字节/同ID；真实socket首次5s超时→200约5.23s；永久慢503及超时约7.86s失败；0.5s剩余预算约0.365s失败。永久快速503最多3次后约0.54s失败。提交后丢回执/提交后head读取失败均安全重放，最终各仅1 run、1 event、1 outbox。
- `git diff --check` 通过。没有执行全量scripts/tests；父整合后统一跑。

| 边界轴 | 覆盖与观察 |
|---|---|
| 输入域 | 同payload/ID散列相等；400/401/403/409/500不重试；恶意error/error_kind被丢弃；错误/重复字段/非JSON/超长成功回执拒绝 |
| 状态组合 | 首503再200；提交后丢回执；提交后head查询失败503；502/504恢复；已知quota/config不重试；未知503仍失败而不伪成功 |
| 时序 | 真实socket5s首次超时后恢复；永久超时/慢503/永久503；剩余预算0.5s；原8s不放宽 |
| 上下游依赖 | 真实handler + SQLite事务/迁移/触发器；真实Miniflare D1；可选benefits相关回归；诊断主键读失败仍保留原错误分类 |
| 极端值 | 响应4096上限；4097拒绝；恶意异常原文/SQL不进API和日志；白名单类别不携带原文 |
| 回退路径 | 失败exit2；成功需匹配ack；collect-only零网络；HEAD仍一次；一次采样重用而不二次采集 |
| 并发与重入 | Miniflare同ID同内容并发200/200、事件不重复；冲突内容409；回执丢失安全重放；预算耗尽杀子进程且active_children为空 |

## 03:45 后分类边界补验（仅应用层，未部署）

父已区分新tail记录：03:45:15.778是ingest POST200/outcome=ok，03:45:18.796是无path/method的exception、异常名Error，疑自然cron。后一事件不能归为此前四次ingest失败的底层cause。本分支不重复平台调查；cron类型及原message的安全分类由父负责。

对 `6bfce521e` 做独立故障注入，证实原资源正则会把“Worker exceeded its CPU time limit”误标成D1存储资源限制。这是可复现的分类边界缺口，不是03:45事件的原因证据。已将资源分支收紧为官方明确D1身份的CPU/内存/查询结果上限消息；通用Worker资源、CPU、内存或EOF内存文本均保持unknown。客户端重试策略不变，不修改tail或平台配置。

补充三验：`/tmp/codex-reports/alert-rootfix-20261109/monitor-root-cause-followup.json`；红测 `monitor-resource-classification-red.log` 为1 failed；绿测 `monitor-resource-classification-green.log` 为真实SQLite/Miniflare相关29项全过（tests29/pass29/fail0）。新增7个白名单边界子场景，确认明确D1资源消息可分类、通用Worker消息不冒充D1；恶意原文仍不进API或日志。没有重跑无关全量测试。

参考：[Workers错误与异常](https://developers.cloudflare.com/workers/observability/errors/)、[Workers运行限制与outcome](https://developers.cloudflare.com/workers/platform/limits/)。平台终止可能绕过应用catch，本补丁不能替代父的tail取证，也不把unknown转成已定位。

## 交接与限制

没有部署，故没有生产修复验收；main不包含本候选改动。未来部署应先由Claude审核Worker类别与采集器重试的配套性，再观察真实失败率、上传时长和安全分类元数据；不把自然成功或单次分类当底层根治。

`ops/monitoring/contract.md:14`仍有历史“single-attempt delivery ... unchanged”说明，文件不在本次授权写scope；父最终合并时须同步这一处说明。本文件记录本候选实际行为。pending-features-index已定点检查，无ops_monitor/ops/monitoring同模块待实施项；父已明确独占范围。复用现有stdlib、多进程预算、handler/D1事务，不加新依赖或通用重试框架。

参考当前官方文档：[D1调试与幂等重试](https://developers.cloudflare.com/d1/observability/debug-d1/)、[D1数据库方法与原子batch](https://developers.cloudflare.com/d1/worker-api/d1-database/)、[Workers最佳实践](https://developers.cloudflare.com/workers/best-practices/workers-best-practices/)。D1写操作没有自动重试，客户端重试安全性来自本项目ID+内容哈希事务；本地测试不能证明生产间歇故障的来源。
