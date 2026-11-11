# 稳定执行与例行静默

本轮承接用户“系统稳定执行、不要同类例行告警”的要求。用户授权 Codex 实施，Claude 复核、合并与部署。实现基线为 `49fe9bea75d6b2106445a8686a36fc3d51005abc`，前批不可变交付和原始失败证据保持不变。

## 范围

前批已经实现公募增量分页、缺口续跑与截止约束，过拟合保留计算结果后仅补传，以及监控同轮恢复证明。本轮复用这些修复，集中核对通知出口、同事件重复观测、全渠道统计和自然运行验收。不会以减少消息代替业务正确交付，也不会将正常消息移到 report 群后宣称零打扰。

原方案：`/tmp/codex-reports/cloud-alert-rootfix-20261111-plan.md`，SHA256 `c25c76581da64da7a980f8be6af211bdf9a411e076cd2e3a7995ab73e9fa7354`。它基于旧 main `2987bd337`；本轮对照新实现，不能把旧方案所述缺口照抄成当前缺陷。详细要求见 [验收合同](acceptance.md)。

代码、部署、业务恢复和长期稳定分别判定。最终交付报告必须列固定提交、原始测试结果、实际生产采样时间及尚未覆盖的自然轮次；源码提交不能关闭生产故障。

## 研究依据与边界

- [Google SRE：值班](https://sre.google/workbook/on-call/)支持告警与用户影响、人工行动相关。
- [Google SRE：数据流水线](https://sre.google/workbook/data-processing/)支持按数据正确性、新鲜度和及时交付衡量业务。
- [Prometheus：埋点实践](https://prometheus.io/docs/practices/instrumentation/)支持批任务记录最近成功、阶段耗时与处理量。
- [Alertmanager](https://prometheus.io/docs/alerting/latest/alertmanager/)提供分组、去重和抑制的设计参考；本轮复用项目现有机制，不引入该平台。

这些资料支持方法，不能证明本项目已根治。14 个自然日、至少 7 个交易日、周频 2 个自然轮和 30 日复核是本轮建议验收窗口，非已取得的生产数据或通用可靠性保证。
