# 接续修复上线验收（2026-11-10）

本文件承接原[六组验收](acceptance.md)及[接续记录](continued-implementation-20261109.md)。范围为用户本次特批的独立分支实施；Claude 最终复核、合 main、部署与受控生产恢复。没有改变日常角色规范。最终提交与 CI 证据在不可变 master report 固定；各任务旧 FAIL 和后续复验均保留，不能沿用旧分支 PASS 代替整合验收。

## 合并与发布

1. 候选来自 `codex/ops-alert-rootfix-ci-20261109`，保留旧六组、Claude 冻结并发修复、同源 baseline 和三项接续业务修复的提交图。不整文件替换 `public_fund.py`；其中 `_acquire_lock` 来自 NAV，指数函数来自指数修复，整合逐节点核验。
2. 核候选完整 SHA 的真实 Linux CI。`Operations monitoring checks` 两个 job 都需成功，检查完整 scripts/tests + ops/monitoring/tests JUnit 汇总；定向测试不能相加冒充一次全量通过。旧 `314e94e67aba19f9e7cf5aaa299553118b3a2f5b` 运行 `42648725977` 的一条跨进程测试失败，以及 `21c2780d547b1d7e4961a3945a413fc5233379ce` 运行 `42654876589` 的两条机检登记失败均保留，不属于发布依据。新增守卫必须在现有 machine-check-registry 在运表登记，不能改豁免或削弱原自检。
3. 主分支同一 SHA 的质量检查与适用的运维检查通过后再发布；新增部署守卫的具体规则另见 release-ci-gate 文档。门禁本身不替代业务检查；变更后的 main SHA 应重新核验，不能只看分支点。该守卫只控制仓库内 GitHub Actions 发布，Cloudflare 原生 Git integration 若仍开启，须由 Claude 核实其同等门禁或停用重复自动发布；本轮不擅自改生产平台配置。
4. 云端 CODE 与 DATA 路径都有脚本镜像，不能仅用 CODE 的 `git HEAD` 证明实际执行版本。按既有部署入口同步，核服务 `ExecStart`、模块 `__file__`、实际脚本 hash 和 Worker active version。不要服务器手改补丁。当前只读核对的八个脚本/模块在 CODE 与 DATA 镜像均逐字节一致；这次未发现镜像漂移，但之后部署仍需核新 hash。

## 接续三项的受控恢复

| 项目 | 操作前提与动作 | 验收通过依据 |
| --- | --- | --- |
| NAV 窗口缺失 | 新代码实际就位、源库与锁路径正确，先对 016989 做定向 dry-run；核上游真实净值再由 Claude 决定执行同命令去掉 `--dry-run` | Nov3–6 缺值/缺行被真实值填充；已有非空值未覆盖；定向任务不推进全局轮转；下一批普通采集仍有界且能轮到尾部 |
| 过拟合公开交付 | 新代码实际就位，核当前 canonical 主/ext 同代，执行原包装层的 `publish-only` | 不重算、不重发模型预警；原锁与原预算生效；两个公开站主/ext 四处哈希与本次本地文件一致；锁忙/超时/半成功明确非零 |
| 基金指数同源恢复 | 新代码实际就位，按既有基金采集链跑自然轮次，或由 Claude 使用现行受控入口恢复 | 三指数 Nov9 最终日线确实入库、输出产物对齐；仍为原 BaoStock 日线 close/pct 口径，非主库日内快照替代；失败/中断不写半批，无孤儿查询进程 |

NAV 原生产路径示例（本轮未执行；若延后到窗口不含 Nov3–6，必须先复核范围）：

```sh
cd /home/ubuntu/code/trade-data
REPO=/home/ubuntu/code/trade-data GIT_REPO=/home/ubuntu/code/trade-data-signal timeout 45s /home/ubuntu/code/trade-data/.venv/bin/python -m scripts.collect_fof_nav --fund-code 016989 --days 14 --dry-run
```

预览可能创建空协调锁文件，不能截断已有锁，不改数据库和轮转游标；dry-run 的“written”打印是拟补量。通过预览后仍需实际写入与公开 NAV bucket/5c 产物核对，不能将预览量当已补回。

## 已有生产事实与待验边界

2026-11-10 00:11 只读快照：云端 CODE 为 `6e3b2ea06299d664cc67e676a0b73614d32f6634`；00:00 监控原生 rc0，日志 snapshot `0c59e8cf-da8d-4059-9f92-da2d120b0f04` 显示 delivery_ok=true、HTTP200；00:13 只读 OPS_DB 主库查询返回同 ID，rows_written=0。该轮有日志与实际入库相互对应，证明一次自然投递成功；不证明全部监控、完整 UTC 日或追加三项代码已上线。

Nov9 备份、换手率和 nextday 原生 rc0 均已只读记录；前两项为旧版本轮次，nextday 执行时实际脚本版本尚未逐件核验。各项仍按原验收表核 run_id、产物、来源与公开内容。D1 下一安装自然链是 Nov10 16:00，配额完整 UTC 日以北京时间08:00为界，不能提前销账。

`6e` 两套 CI 实际通过，Pages 发布成功；Cloudflare 发布运行 `42649615746` 在部署步骤 exit1。公共 API 未给出具体 stderr，故不归因为代码、权限或网络。Claude 需在有权限的 Actions 日志核原因与实际 Worker active version，保留此失败，不以云端 HEAD 或 Pages 成功替代 Worker 发布成功。

## 继续保留的故障

- 136 条历史缺冻本轮恢复 0，5 条交易缺口仍 OPEN；缺可信 T0 原件，不用今天映射造历史。
- #373 的 Nov1/2 public_fund 原备份未找到；附近 Nov3 备份只有元数据核验，不能冒充目标原件。
- Nov3 指标候选已完整取回并复算两份，但指纹不匹配目标生产快照；需配对的生产运行身份/输入哈希才能权威归因。第三件精确 key 当时 HEAD404，不推断永久丢失原因。
- 当前 74/red 按既有权重成立，保留真实风险预警。没有修改阈值、策略、订阅、告警渠道，也没有证明物理网络所有超时已消失。

## Claude 回执

请回固定最终 main SHA、两套适用 CI 结果、云端实际脚本 hash、Worker active version、各项自然轮次/受控恢复的产物证据及仍待观察项。共享 pending-index 由主控按现有条目维护；本目录是证据与验收资料，不另造第二份任务状态台账。显式 handoff 的 queued/context-emitted 只是桥接状态，不能写成已 received/claimed/completed。
