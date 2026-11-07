# Trade 运行架构知识库

本目录把当前系统整理为可对账的运行基线：**同一套对象编号，连接架构图、服务与任务、数据资产、告警、运行手册和监控面板规格。**

代码基线：`d4238f5b24aa1aa5632dd5fed1098ce9fbdb3620`；盘点日期：2026-11-07。仓库声明、云端观察、本机观察与设计项分别标注，各自时点及覆盖以专题和JSON为准。它不是实时监控，也不是“所有服务已验收通过”的声明。

## 从这里进入

| 内容 | 入口 | 主要问题 |
| --- | --- | --- |
| 可直接打开的SVG图集 | [diagrams/README.md](diagrams/README.md) | 与专题Mermaid源对应的实际渲染图像 |
| 架构总图与协作闭环 | [00-system-overview.md](00-system-overview.md) | 系统如何连接，事实来自哪一层 |
| 服务与任务声明总账 | [01-services-and-schedules.md](01-services-and-schedules.md) | 应该跑什么、由谁触发、读写什么 |
| 云端实际运行观察 | [02-cloud-runtime.md](02-cloud-runtime.md) | 云上安装/注册/触发了什么，观察有什么边界 |
| 数据资产与依赖 | [03-data-lineage-and-contracts.md](03-data-lineage-and-contracts.md) | 哪份数据权威、谁写谁读、何时可用 |
| 监控与告警规则 | [04-monitoring-and-alerts.md](04-monitoring-and-alerts.md) | 何时告警、升级和恢复依据是什么 |
| 排障与恢复手册 | [05-operations-runbooks.md](05-operations-runbooks.md) | 从症状如何安全检查、修复与验收 |
| 部署与用户入口 | [06-deployment-and-surfaces.md](06-deployment-and-surfaces.md) | 数据如何上线、页面读什么、缓存和回退在哪里 |
| 本机运行与协作 | [07-local-runtime-and-collaboration.md](07-local-runtime-and-collaboration.md) | 本机仍运行什么、主控/外审如何交接 |
| 私有监控面板规格 | [08-dashboard-spec.md](08-dashboard-spec.md) | 面板看哪些事实，如何避免假绿灯 |
| 维护和验收 | [09-maintenance-and-acceptance.md](09-maintenance-and-acceptance.md) | 哪些变更必须同步知识库、谁负责 |
| 对账和未覆盖项 | [10-reconciliation-and-gaps.md](10-reconciliation-and-gaps.md) | 声明、部署、运行哪些一致，哪些待核 |
| 近期问题、故障与跟进 | [11-incidents-and-followups.md](11-incidents-and-followups.md) | 哪些在修、待验、观察中、已关闭或历史不可回放 |
| 在线运维工作台实现 | [12-online-operations.md](12-online-operations.md) | 私有API、持续采集、历史、问题修订及部署边界 |
| 离线盘点预览 | [dashboard-preview.html](dashboard-preview.html) | 搜索、筛选和下钻同一结构化清单；非实时 |
| 机器可读目录 | [inventory/](inventory/) | 后续面板、校验与差异对账复用的数据源 |

## 数量口径

本次目录包含72条仓库声明、44组云端service/timer及外围cron、本机运行/模板观察、数据与依赖边、监控/界面和18条近期问题。catalog条目总数包含不同对象层级与关联边，不能作为独立服务数或故障数；同一任务的声明、timer和service通过对账链接。完整表达式/时区与观察时间见01、02和10。

## 如何使用

看故障：从告警关联对象进入05手册，再对照01任务、03数据和06发布；保留原事件键、输入身份与验证范围。
看计划任务：先看源码声明，再看02/07的实际注册和触发；名称一致不等于配置无漂移。
做优化：先查10的证据缺口和依赖边界，区分当前故障、历史不可回放与拟议改造；避免重复修改已经验收的项。

## 本次交付与后续实施边界

资料盘点、结构化清单、10张架构图、对账、运维手册和离线预览构成取证基线。用户后续特批Codex实现完整在线采集、私有API、历史存储及面板，见12专题；Claude负责审核、合并和生产部署。实现与上线状态分开记录，本分支不直接部署或修改生产配置。

所有`unknown`、`inferred`、`documented_only`和`planned`都必须可见；运行单元active、任务exit0或没有告警不能单独亮业务绿灯。详见[_inventory-contract.md](_inventory-contract.md)及[结构schema](inventory/schema.json)。

现有专题规范仍在原路径作为权威，本目录负责统一导航与证据索引。原始取证材料保存在私有/tmp报告目录；仓库仅保留脱敏结论和必要来源，不存.env、密钥、通知账户或webhook。
