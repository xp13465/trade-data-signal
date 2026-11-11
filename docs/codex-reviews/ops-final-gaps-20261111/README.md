# 告警剩余接线与 NAV 发布证明交付

本批接续 `20f669d25fc44056f207b15b606e2da7f7a70770`，用户已授权 Codex 实施，Claude 复核、合并和部署。工作分支为 `codex/ops-final-gaps-20261111`；不修改主工作树、旧交付分支、pending-index 或此前不可变报告。最终 head、CI 和独立复核结论在本批私有总报告中固定；本文不自称已上线或根因全部关闭。

## 本批实现及复验入口

1. [NAV 发布对应链](nav-publication.md)：真实提交输入 → 真实 exporter 数值/字节 → 限额 canonical 公共 GET；fd 文件代次和原生索引锁防旧回调覆盖，错日期、未来凭证、迟到回读及最后一桶超预算均不确认。基金整体健康仍 unknown；手机/桌面详情区区分已观察阶段与全池健康。
2. [其他告警 producer 接线](../legacy-producers-followup-20261111.md)：nextday 生成/校验、update_all、日报失败复用原生事件、共享状态锁、ACK 和逐渠道回执；Python/包装层同运行令牌，旧完成不能覆盖新运行。真实日期补跑失败仍通知，诊断/历史范围不能关闭当前故障；保留异常正文。nextday 和 update_all 缺业务恢复证明时仍 unknown。
3. CI 触发范围补齐本次六个入口，避免未来只改 exporter、异步回读或 nextday wrapper 时漏跑完整运维回归。

```bash
PYTHONPATH=scripts:. .venv/bin/python -m pytest -q scripts/tests/test_ops_nav_publication.py scripts/tests/test_ops_nav_readback_shell.py scripts/tests/test_ops_fund_evidence.py scripts/tests/test_ops_publication_concurrency.py scripts/tests/test_legacy_operation_producers_20261111.py scripts/tests/test_legacy_operation_shell_20261111.py scripts/tests/test_ops_quiet_producers_20261111.py --tb=short
OPS_UI_EVIDENCE_DIR=/tmp/ops-final-ui .venv/bin/python ops/monitoring/tests/smoke_business_evidence_ui.py
```

全部本地执行仅使用临时 SQLite、隔离状态树、拦截网络和通知叶节点；未运行生产采集、上传、部署或真实告警。测试期间发现的失败、WIP 反例和旧固定提交 FAIL 保留。NAV 独立复核对 `e8ac073d34d130b6233be4e76e70c02f4b2f698d` 为 Ready；其他部分和最终组合以总报告记录为准，不借用子分支结论冒充合并点验收。

## 仍须明确分开的剩余事项

- **发布接力**：Claude 审核固定最终 head，经现行主控合并入口合入；验 main 合并点 CI、真实云上代码/unit、Worker/D1 policy、管理员页面。上一批的 policy 2、真实 InvocationID、PrivateTmp 只读挂载、loaded identity 审核要求全部继续有效，详见[上一批说明](../ops-evidence-closeout-20261111/README.md)。
- **NAV 激活**：collector/exporter/异步 uploader 的证据根必须一致；两个开关和经审核的实际 loaded-code manifest 分别核对。默认回读60s/64MiB，可能只能完成部分桶。无更大出口预算决定，不擅自增加流量；同有效轮次允许显式续验，未覆盖部分保留 unknown。
- **真实业务恢复**：nextday_plan、nextday_gap、update_all 仍缺本轮完整公开发布及原故障日期/资产范围的恢复证明。接入事件账解决重复首报、漏补失败渠道及并发覆盖，并不意味着它们的业务数据根因已闭合。缺合同或证据的状态不能强制标绿。
- **历史资产/队列**：没有 refs 的旧通知不按标题迁移或删除；历史缺口不能拿今天的新目标证明已修。需要可核对原件、范围和备份后另行处置。
- **自然验收**：以部署后的实际日期、计划槽位、生产日志/回执和公开内容取证。离线通过、通知安静、任务rc0、人工ACK都不是根因关闭。

本批总报告同时引用上一批不可变 master（SHA256 `eef4dce21dafa1df600751c10b11d43cd9415977cba1864e79c4d3692509e338`）及其既有26份历史报告链；Claude 无需逐条复制旧聊天。新 packet 只有 queued/context-emitted 时，不算 received/claimed/completed。
