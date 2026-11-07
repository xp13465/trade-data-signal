# 本次盘点的数据合同（维护者说明）

此目录是运行架构知识库入口；既有具体运维规范继续作为其专题权威，本目录链接它们，不整文件复制或替代。

- 基线代码：d4238f5b24aa1aa5632dd5fed1098ce9fbdb3620。盘点日期：2026-11-07，展示时间统一Asia/Shanghai并保留证据时间。
- 每份inventory JSON统一schema_version=1、baseline_code_ref、observed_at、scope、coverage、records。
- 每个records元素至少id/name/kind/evidence_status/evidence；evidence为含kind/location/note的对象数组。健康无依据时health=unknown。
- evidence_status取runtime_observed/code_confirmed/documented_only/inferred/unknown/planned，分别代表实际运行观察/源码确认/仅旧文档/推断/未知/拟议。不得将后四项当当前在线证明。
- kind可取host/repository/service/task/data/monitor/alert_rule/surface/external/edge/incident。id用稳定ASCII前缀，如task:update-all，禁止用序号充当长期身份。
- depends_on存已确认id；尚未解析的依赖用dependency_candidates（标签+证据），不编造已核实连接。图上推断/计划边须虚线并标注。
- 每任务描述入口/执行位置/调度器/时区/日历门控/预期频次/输入/输出/锁/超时/重试/失败与恢复判据/监控/运行手册；没核实时明确unknown。
- 记录来源层级（repo声明、部署配置、运行观察），运行证据必须带observed_at。服务active不等于业务healthy，任务exit0不等于数据正确，通知成功不等于故障恢复。
- 只读盘点；不采集.env、密钥、邮件账户、webhook或连接令牌。展示脚本入口/模块及安全参数，不记录带敏感参数完整命令。
- 设计项要标planned，与实际清单分离；本次面板默认私有运维用途，公开健康页另案。

公共id优先复用：host:cloud, host:local-mac, repo:code, repo:runtime-data, repo:static-data, data:sentiment-db, data:etf-db, data:stock-db, data:board-etf-map, data:etf-freeze, data:signal-daily, data:kelly-trades, data:schedule-stats, data:notify-ledger, external:upstream-market-data, external:r2, external:cdn, external:feishu, external:email。

维护规则：架构变更与入口/任务/数据产物变更应同步更新受影响记录及证据；保留已移除项的去向。代码ref、部署ref、观察时间分别记录，避免一项更新时间冒充整套最新。

## 近期问题台账扩展

incident记录使用原工单或finding稳定id。修复状态、部署状态、验收范围、根因措施、观察窗口及关闭条件分别记录；局部PASS、ACK completed和告警不再出现均不能自动推导根治。历史不可回放单列，不把审计结论写成数据已恢复；正常业务风险与故障分类分开。
