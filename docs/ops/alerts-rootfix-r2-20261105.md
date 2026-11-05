# R2 写门禁、通知占窗与自动摘要回退（2026-11-05）

本次只在独立开发分支实现，未提交、未推送、未部署，main 与生产未改。全量 `scripts/tests` 由主会话在三个 worker 完成后统一执行；这里的结论仅覆盖定向回归。

## 问题与改动

1. `verify-r2` 发现差异后会自动补传，原先却被列为只读，显式 REPO 的非生产进程可绕过公共 R2 写门禁。本次仅将它移出只读集合，复用现有 guard；云上显式 REPO 的自动 repair 契约不变，缺省 REPO 的既有拒绝语义不变。
2. verify 的 mass mismatch、独立链 stale、台账 gap 三处告警原来不看 `notify.send` 返回值就占 24 小时窗。本次共用严格结果判据：三个渠道字段必须完整且为 bool，任一渠道 `is True` 或 `digested is True` 才能占窗。三 False 且未入摘要、异常、缺字段、错误类型均不占窗，下一轮仍可重试。
3. `send` 的 severe budget、domain 自动聚合以及恢复发送后留痕统一复用 `_digest_chain_available`。链不可用时，自动聚合沿原渠道路径尝试发送；不新增状态、队列、cron 挂载检测或通知旁路。

复用现有 guard/helper 是写码前阶梯的第二层；只新增一个三处共用的结果判据，不增接口或重试状态机。告警主题、默认 notice 级别、86400 秒去重窗、既有 r2_deploy 聚合域、首报策略均未另行调整。首次发送失败不占窗是本次修复目标。

## 保留的契约与结论边界

- `_absorb_to_digest` 等显式存储 writer 保留；没有机械禁止所有摘要写入。
- `--defer-digest` 在 digest-disable 下仍可显式入队，在 master budget-disable 下仍为 noop。
- 手动 flush 的执行语义不变，`ALERT_DIGEST_DISABLE=1` 仍停止 flush；对应说明文字同步。
- 没有改 pending/stat/chmod helper；notify 中除 `send` 和 `flush_digest` 的说明文字外，其余 93 个完整函数逐字不变。flush 执行体 AST 不变。
- 正常链路的 `digested=True` 只证明可靠入盘或已有同键持久条目，可以占本次 R2 通知窗，**不等于最终送达保证**。
- caller 与独立 consumer 可有不同环境。测试在禁用 caller 环境显式入队，再用未禁用 consumer 环境运行真实 flush 主体，替身渠道成功后实际清空临时 buffer。因此只确认“禁用上下文仍自动入队”不符合本轮要求，不断言真实曾漏信或必定漏信。
- 现有 helper 只检查两个环境开关，未检测实际 cron 挂载。未挂载用 helper 返回 False 注入，仅验证被告知不可用后的路由行为。
- pending 索引中的告警/摘要、去重并发、R2 锁项已查阅。本次沿用既有接口，不改并发去重、锁域、pending 权限或既有 Claude P2 内容；这些模块的实施权不从本改动推导。

## 可移植定向验证

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
python3 -B -m pytest -q --noconftest -p no:cacheprovider \
scripts/tests/test_codex_r2_alert_delivery.py
```

取证外层 `subprocess.run(..., timeout=25)`，单次命令上限不超过 30 秒。最终原样末行：

```text
219 passed in 9.20s
```

测试仅从当前文件编译明确列出的完整生产函数，不导入模块顶层，不依赖研究目录、固定工作树、旧 Git SHA 或本机命令存在性。`ROOT` 从测试文件位置推导；时钟在被测命名空间冻结。S3 对象是内存字节库，渠道与规则台账是依赖边界替身，完整 verify/send/摘要锁与原子文件路径实际执行。guard 使用完整函数验证；未声称执行了原业务 CLI 模块顶层。

每例在生产函数执行前先验证网络、SMTP、子进程、shell、仓库写、rename、`.env`/变体读取八个陷阱；正控结束后任何额外触达都失败。网络/SMTP 与凭据读取均未执行。补丁由 fixture 局部恢复，fake notify 的 `sys.modules` 项也自动恢复；env（排除 pytest 自管阶段变量）与 sys.path 收尾核对一致，不输出环境值。

覆盖：非生产 guard、真正只读分类、云上 weekday/Sunday 自动 repair、上传失败 exit1、三个告警点的全部 16 种 bool 组合、错误结果/异常、失败后可重试且成功后抑制、九种自动摘要路径、健康/两种禁用/不可用注入状态、三处实际 caller 与真实 send 串联、摘要写失败回退、显式 writer/CLI/手动 flush、独立 caller/consumer 环境反例。

七轴边界：输入域与类型（测）、状态组合（测）、时序重试（测）、上下游依赖失败（测）、阈值 51 个差异对象（测）、回退路径（测）、真实跨进程去重竞争（未测，未改该机制且全量由主会话统一执行）。没有新增生产调度或数据产物，不涉及前端算法、版本串或数据上线。

## 判别力与未执行项

在临时副本上撤销单项修复，使用同一份当前回归测试，不改仓库、不依赖旧 SHA：

```text
negative_guard: 3 failed, 21 passed, 195 deselected in 1.46s
negative_dedup: 3 failed, 45 passed, 171 deselected in 2.42s
negative_digest: 12 failed, 60 passed, 147 deselected in 2.55s
```

上述负控是期望失败。首轮 fixture 曾把 `PYTEST_CURRENT_TEST` 的 setup→teardown 变化误判成环境泄漏，原样末行 `216 passed, 216 errors in 9.89s`；已修正并保留初轮日志，没有删错误计数冒充通过。之后补入既定失败重试验收项，形成最终 219 例，现已冻结。

未执行真实 R2/SMTP/飞书/Telegram、SSH、cron/systemd、生产部署、最终送达检查或全量 pytest。源码与测试冻结 SHA-256 交主会话报告；review、全量测试、提交/推送、合入及上线由主会话与 Claude 后续协调。
