# 运维只读分诊与关闭要求

基线 `d4238f5b24aa1aa5632dd5fed1098ce9fbdb3620`；2026-11-07，Asia/Shanghai。本文是现状知识库索引，复用既有专题权威。本轮没有运行恢复命令或业务入口，现场健康均unknown。以下“检查”是后续获授权人员的取证清单，不是本轮已执行记录；业务脚本即使带dry-run也不在本轮授权内。

## 通用处理链

1. **安全只读取证**：先确认环境/代码ref/运行树/时区和事件时间，读取指定任务状态字段、脱敏日志片段与既有产物元数据；不读凭据或聊天、不扫全盘、不运行生产入口。不把旧文档事件当本次故障。
2. **确定影响面**：记录任务/实例/交易日、数据家族、冻结/交易依赖、发布源/展示位、备份恢复点和通知路径。区分源缺失、计算漏算、发布落后、显示缓存与未完成投递。
3. **交 Claude 开发修复入口**：提供最小可复现输入、源函数、实际/预期、依赖和回退材料。业务修复、重跑、重启、锁处理、purge、恢复DB、清状态或改ACK由主控另案授权和执行。本页不提供含连接参数的完整敏感命令。
4. **验收**：先用隔离样本证明修复，再由授权人员核验同一业务日的源数据→中间产物→发布→显示和通知结果；保留基线/部署ref、前后证据与测试结果。发送成功只验收通知层。
5. **关闭**：原故障条件消失、有新鲜业务覆盖与发布证据、依赖无隐藏failed/unknown、必要时连续观察至少一轮相应任务及下一调度窗；明确记录未覆盖项与owner。ACK/静默/进程active/exit0/队列已接受不能单独关闭。关闭结论需 Claude 复核。

## 专项运行手册

| 场景 | 安全只读检查 → 影响面 | Claude开发修复入口 | 验收与关闭要求 | 专题权威/来源 |
| --- | --- | --- | --- | --- |
| R2超时、锁竞争、purge/缓存 | 核对实例时间、上传轮次、锁等待日志与持锁证据；分全局锁/小锁/网络传输/备份耗时/缓存传播；查看本地与三源的业务时间、版本、摘要 | `upload_r2.py` 锁路由/上传、`r2_upload_async.sh`、`deploy.sh`；由Claude决定重跑/锁处置/精准purge；不据锁文件存在就删锁 | 稳定态对象上传完成、三源一致且足够新、消费者读到同版本；preflight-skip和HTTP200不是验收；不以手动purge成功代替源对象正确 | [锁竞争专题](../r2-lock-contention-20261023.md)、[方案状态订正](../r2-lock-contention-308-summary-20261101.md)、[多展示位发布核验](../160-r2-consistency-gate-wiring-20261005.md) |
| failed unit/漏跑/巡检失效 | 查看LoadState/Result/ExecMain与InvocationID、timer最后/下次触发和同实例日志；区分未加载、从未跑、正在跑、完成失败与ledger补位；核对注册分母 | `unit_truth.py`、`gen_schedule_stats.py`、`check_failed_units.py`、`schedule_monitor.sh`；部署配置由Claude另案处理 | 新实例正确执行且目标数据更新；旧failed清除或reset-failed不是业务恢复；check_failed_units未送达不得占成功窗，巡检者自身也需验证 | [假OK根因与口径](../monitor-fake-ok-fix-plan-20261025.md)、[failed-units专题](../failed-units-rca-20261022.md)、[监控现状](04-monitoring-and-alerts.md) |
| 行情缺行/基金名称/净值占位 | 按代码和交易日核对真实行情行、名称来源、NAV/accum_nav、占位标记与上游发布窗；区分无信号、缺价格、名称未回填和休市；不直接改库 | `check_data_gap_alerts.py`、采集写入者的名称解析与upsert、`check_data_integrity.py`；缺口修复/历史回填由Claude评估 | 覆盖全部受影响代码日期；有效名称/价格和真实/占位行闭合；反向验证非受影响行未改；后续一个采集窗无新增缺口；未获生产数据授权前只报告待修 | [名称写入契约](../signal-gap-name-contract-20261107.md)、[数据缺口家族](../data-gap-alert-batch-20260827.md) |
| 信号存在但冻结/交易缺失 | 对同一信号日逐层比signal_daily→ETF冻结→价格/名称→交易产物；核对四象限、生产模式、snapshot覆盖与交易产物mtime；记录空输入和异常输入区别 | gap的`check_kelly_coverage/check_kelly_stale`、冻结生成/回测导出入口；由Claude决定重算/冻结修复，禁止直接编辑冻结绕门 | 逐日逐行交叉对账，所有展示位一致；既有冻结不应事后漂移，修复范围与来源可追溯；coverage_end与实际输入推进，不能只看JSON新mtime | [冻结孤儿专题](../252-freeze-orphan-backfill-20261016.md)、[冻结清理边界](../124-freeze-orphan-cleanup-20261001.md)、`check_s06_freshness.py` |
| 备份存在但可恢复性未证 | 分别核对本地/异地/覆盖前备份的对象日期、库名、大小、失败/跳过记录、最近演练报告；LIST失败不能记无对象；空间与大库流式恢复能力另核 | `backup_db.sh`、`staticdata_backup_async.sh`、`verify_backup.sh` 与恢复工具；恢复演练/下载/解压亦须另案授权，不在本轮执行 | 在隔离路径完成实际恢复、DB完整性与表/数量/日期检查、恢复点满足RPO、清理临时空间；下载成功、skip_oversize、NO_RUN不能宣布可恢复 | [备份演练](../backup-drill-20261028.md)、[大库备份](../pfdb-r2-backup-20261025.md)、[覆盖前护栏](../237-r2-overwrite-backup-guard-design-20261009.md) |
| 站点过期/三源不一致 | 核对overview/intraday及对应页面实际加载路径、业务日期、collected_at/coverage_end、源版本、缓存层与交易/午休门控；分共同陈旧与跨源不一致 | 导出→异步上传→缓存传播→前端消费者各入口交Claude定位；是否补跑/部署/purge另案 | 三源同一稳定新版本且关键字段/覆盖一致；前端真正读取预期文件；同源一致不抵消共同过期；下一轮自动更新能持续推进 | [云恢复验收索引](../cloud-recovery-runbook-20261008.md)、[发布一致性接线](../160-r2-consistency-gate-wiring-20261005.md) |
| 告警不响/摘要不全/部分发送 | 对账检测finding→ACK/抑制→buffer→pending段回执→ledger；只用渠道类别，不展示账户/URL；区分没配置、明确禁用、配置坏、失败、待清理 | `notify.py`、`alert_digest_delivery.py`、调用方结构化结果消费、监控自身心跳；由Claude修复，禁止为“验收”直接真实发信 | 隔离失败注入覆盖段失败/状态写失败/重启/路由变更/新增行；生产侧另案确认必需段接受与journal清理；远端接受不等于已读或业务恢复 | [长摘要契约](../digest-delivery-20261106.md)、[告警分层](../alert-denoise-spec-20261027.md)、[多群对账](../alert-all-groups-20261106.md) |
| 过拟合风险升高/样本不足 | 核对生成代码版本、训练/实盘区间、象限、窗口、K/模式、缺失维度与风险分；分数据问题与真实统计退化，不因分数低自动健康 | `overfit_monitor.py`、前后端parity校验及展示模块；研究结论与业务调整另案，不由运维直接改阈值 | 同口径重算和前端对账，覆盖/缺维度显式；象限预留项未实际触发，不能宣称已有自动防线；若输入未证完整保持unknown | `overfit_monitor.py::compute_risk/evaluate_alerts`、[监控现状](04-monitoring-and-alerts.md) |

## 事件记录最小字段（planned模板，不新增执行系统）

记录事件ID、首次/最近观察时间与时区、运行位置/代码及部署ref、证据层级、期望覆盖、实际输入/输出、原始状态与业务状态、最后成功实例、抑制/ACK原因、通知接受/失败、影响对象、Claude修复入口、隔离验证、生产验收授权与证据、关闭人/时间/未覆盖项。不要复制凭据、邮箱账户、webhook、完整认证或连接命令，也不要记录私人聊天。

unknown应保留到取得对应证据；旧专题文档是历史依据，不自动覆盖2026-11-07现场。planned面板建议见 [04](04-monitoring-and-alerts.md)，由parent整合，不在本页宣称已实现。
