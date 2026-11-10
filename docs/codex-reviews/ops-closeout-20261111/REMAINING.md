# 未实施项的落地细则、依赖和验收

以下是可直接认领的实施说明，**不是已完成代码**。已有集成修复先审；同文件只交一个owner，避免互相覆盖。当前状态仍以 [TASKS.md](TASKS.md) 对账，不改pending-index权威记录。

## 1. 发布已有修复：先完成这条闭环

1. 固定最终交接head审查，确认包含HC01–04、公募deadline、过拟合有界补发、同轮恢复展示和监控投递预算。源码比对`b5a748…`之后只有本目录审计文件。
2. Claude按现有main-merge执行构建/min/版本串，复验**main合并点**CI，不拿子分支PASS替代；云端发布窗口避开既有采集/发布锁。
3. 公募原unit正常完成后核业务日期、NAV字段覆盖、三指数、导出、公网完整hash。过拟合只验当日主/ext及原四个URL，不能跨日补发绕过日期门禁。
4. 下一监控轮对同一invocation采集，核完成状态与业务凭证。原失败历史保留；不执行reset-failed或删除告警来达标。
5. 验HC01无效后有效报价仍能告警、HC02多条正文完整、HC03严重警告可见、HC04手机异常入口可点。真机验收补在部署后。

## 2. HC18：汇率数据合同先修，历史迁移另跑

**已证：** Nov10 888行原序列精确复现尺度污染。**未证：** 全历史错误范围、当时真实同口径CNH值、交易方向损失。

建议最小止错边界：实时行情展示继续读取独立快照；在`_backfill_fx_metric`将来源/品种/单位未匹配历史metric的写入拒绝，明确记录`instrument_mismatch`或`unit_mismatch`。不要把6.x临时乘100后伪装成同一中行折算价。计算层再校验同一窗口元数据，防其他入口绕过。

复核时必须先选清合同：

- 若保留“离岸人民币”含义，日频历史和实时都用经确认的USD/CNH同口径源，原中行折算价另存独立metric；补同品种历史达到60日预热后才出对应信号。
- 若产品实际要“中行美元折算价”，名称/单位/公示解释同步，实时即期另列；不借CNH名称沿用现有回测收益。
- 来源元数据应含`instrument_id`、`quote_currency`、`base_amount`、`source_id`、`as_of`、`contract_version`。当前`source=akshare`过粗，迁移不能只凭数值>100决定历史单位。
- 原始888行保留，迁移新版本离线重放对账日期、缺口、阈值和信号差异，形成批准清单后才换读；冻结、历史成交及已发通知不静默覆盖。

验收：同一品种同单位正例；100美元/1美元混入拒绝；CNY/CNH虽数值接近仍拒绝；来源缺失返回unknown；真实价格跳变不被误当单位转换；90/60/20日窗口迁移与冷启动；重复导入幂等；变更前后公示处一致。生产纯函数反事实仍sell这一点必须保留，不能写“修单位后错误卖点消失”。

## 3. HC07：复用游标，补有限窗口之外的真实缺口

当前FOF已有持久轮转，Nov10尝试500/1810、490正常有值、10正常空、error=0，剩1310是未尝试数，不能等同缺值数。016989 Nov9本轮已补，不用它证明“7日窗外”的机制。

先将首次历史初始化、日常回看和已知缺口分开：首次保完整，日常窗口由真实修订延迟统计决定，已知NULL按`fund_code/date/field`排入有界队列。继续复用已有轮转状态，另记缺口进度，失败不推进为已修。现接口每页20条，长历史必须分页/按日期切段并核页覆盖，不能只把days从7改400。

指数默认400日重复读取可按“最后有效日+必要上下文+缺口集合”优化；同源对照逐字段一致后才能切换。窗口内非空冲突不覆盖，先保全before/after与源日期，整只目标提交前决定是否拒绝；不要把“保非空但其他格已写”称冲突整批回滚。与已做HC06预算统一，由同一owner串行处理`public_fund.py`。

验收包含首次无游标、池增删、半批超时、晚于7日才发布、长缺口>20行、分页重复/丢页、前一日NAV依赖、源修订冲突、只读dry-run，以及同窗口全量/增量结果一致。日期工作量下降不等于HTTP请求量或最终费用下降。

## 4. HC08/10/11：让41个未知有依据，而非统一变绿

逐项字段已在 [unknown-map.json](unknown-map.json)。数据34项=21项stat-only+13项未配置固定源；另4备份、1发布、2timer。本轮恢复证明可以作为验收样本，但还没接入采集器。

最小回执合同：`schema_version, chain_id, object_id, run_id, code_ref, business_date, started_at, finished_at, status, input_hashes, output_hashes, coverage, rule_version, valid_until`。生产者落原子文件，采集器只读取脱敏索引；不扫描全库、不获业务写权限。规则版本或hash不符、过期、部分成功都保留unknown/warning，不能把目录存在或bytes=0判断为内容健康。

投递回执按`snapshot_id/attempt`记录开始、结束、HTTP状态、`error_kind`、`ack_state`，区分：未到达、已入库但回包超时、确认入库。`event_at`用业务发生时间，`collected_at`用采集时间，`received_at/delivered_at`分别由接收端/投递端产生；缺一个显示未知，不用当前时间补。重试沿既有预算与幂等键，不能再套无限循环。

UI保留`status`健康结论，另列`execution_state`（running/completed/not_observed）和`source_reason`。timer没有next点只解释采集时状态，既不冒充成功，也不直接报停摆。业务完成凭证要绑定invocation/run，不能复用上次好结果掩盖新失败。

接线顺序：备份源run→对象版本→恢复回执；换手完整数据及公开hash；过拟合主/ext同代发布。三条打通后再扩其它对象。过期凭证、错run、同长度错hash、部分表缺失、跨业务日、正在运行和exit124均做负控。`ops_monitor.py / worker/ops.js / static-site/admin/ops.js`同一owner统一审合。

## 5. HC09：D1收益账要对同窗口，逐阶段保留计数

实际平台计数：UTC Nov8读399,994/写455,314；Nov9读514,080/写341,593；Nov10截至06:34 CST读174,182/写36,152。后者仍是未结束日，不计算最终降幅。

两表自然轮都成功：score changed2003/28456、screener changed28148/28476，D1 COUNT一致。`execute.out`目前临时清理，无法从现存日志拆每阶段实际rows read/written；代码树10月旧failure receipt不能冒充11月当次失败。

在已有`d1_execute_sql_file`成功/失败结果消费处提取官方返回的rows_read/rows_written，记录`table/stage/attempt/run_id/query_id`与单位；只留数字和分类，不留SQL数据、凭据或完整输出。哈希读、upsert、count验证分别计数；重试实际消耗不能遗漏，也不能将累计值重复相加。响应缺meta写unknown，不写0。

08:00之后待平台数据收敛再读Nov10整日，并按数据库/UTC日期对账。收益评估需对同一输入/相同语义基线：单列索引维护、变化字段家族和数据量增长；score_date/nav_date变化可能是必要更新，不能为省写删除业务字段。平台费用不能只用changed比例估。[D1指标说明](https://developers.cloudflare.com/d1/observability/metrics-analytics/)

## 6. HC12/13：覆盖安全优先于缩锁

锁证据：自然换手等待240.013秒后释放；本轮fund_nav只有1桶变化，域EX+全局SH持有52.003秒后释放；此前全256桶恢复耗时1829.65秒含备份。这是不同工作集，不能把1829→52当优化收益。先记录prepare/hash、旧对象读取、备份写入/回读、上传、state、purge各阶段，继续受同一绝对deadline约束。

**建议关键键合同（候选，尚未开启#237的C级阻断）：**

| 组 | 候选键/资产 | 保护要求 |
|---|---|---|
| 当日计划 | `data/nextday_plan.json`、`data/auto_trade_steps.json`、`data/signal_kelly_day_snapshot.json` | 各自已验旧版本、日期/run绑定；多键没有原子性，部分成功必须显式告知 |
| 过拟合 | `data/overfit_monitor.json`、`data/overfit_monitor_ext.json` | 主/ext同代，保上一可恢复配对；仅逐键CAS不等于两键事务 |
| 净值 | `nav_bucket/*.json`中本轮待变更键 | 全桶代码集合保真、只更新目标、逐键备份许可和CAS |
| 冻结事实 | 生产`data/signal_kelly_etf_freeze.json`及原T0审计 | 本地事实资产，不捏造它已有R2公开键；沿现有冻结持久化锁/版本备份链保护 |

所有同键写者一起纳入：增量`_incremental_upload`、直传`_upload_glob`、raw `cmd_upload`、verify修复及独立data-files通道。锁只约束参与者，不能阻止未改造远端客户端；先扫描并固定完整入口清单再开启关键键规则。

提交顺序：冻结待传bytes+SHA → 读旧bytes和同响应ETag → 按内容hash保留不可变备份 → 回读校验 → 生成逐键permit → 提交时`If-Match`（真新对象`If-None-Match:*`）→ 记录confirmed/failed/unknown → 持久pending-purge → 准确state → purge回执。412拒绝、超时未知不得降级无条件写或推进成功。ETag是版本比较令牌，不当完整性SHA。

分片也必须在最终`CompleteMultipartUpload`传条件，当前代码只在Create带headers，需补最终传递。平台文档说明失败412会终止upload；409桶锁与412语义不同；超时后的404不证明原写失败。用write-id辨认自己的写，保留有界确认与人工恢复入口。[官方条件写语义](https://developers.cloudflare.com/r2/api/s3/conditional-operations/)

关键键更新可能因备份网络失败而延迟，保留旧可恢复值；非关键独立键不被全桶阻断。留存期与桶lifecycle必须共同保留当前恢复锚点。多对象若要求一致切换，另设计不可变版本+最后切manifest并改消费者，不能宣称CAS已提供跨对象事务。

此前基线11/候选15/传输2/分片路由1/隔离4（共33测试单元）是离线模型及固定函数，不是生产集成。下一验收必须补真实隔离前缀的两写者、multipart最终提交、响应丢失、同长错hash、崩溃/ENOSPC恢复、purge失败重入，以及所有同键写者；不触碰生产关键键做故障注入。

## 7. HC16/19/20/21：历史与协作保真

历史7键在当前两运行树和Nov7预部署副本均不存在，date/index备用键也未找到。staticdata云仓是shallow且当前树无冻结JSON，本机两个staticdata当前树也无该文件；这不是“全历史原件绝不存在”。后续查原T0审计/离线版本清单，必须绑定hash和生成时间，不能用现评级制造历史。Nov1/2有残留WAL/SHM并不等于有可恢复原主库。

测试镜像3条位于`agent-ae637b217439bb921`工作树，来自`test_f03r1_digest_atomic_write.py`的`h_existing/h_new`种子，时间Nov10 09:18。该树未合main，由其owner备份整个latest.md后精确隔离3个block；真实severe、前言和原始ledger均保留。本轮不跨树改文件。

worktree盘点列明所有49分支/35工作树，不能只按祖先关系删除；`codex-freeze-persistence-rootfix-20261109`仍有3个dirty文件，锁树也保留。清理次序：本轮自产恢复大文件→已确认不再使用的本会话临时文件→owner认可且ignored备份完成的已合树。保留最终交接分支、旧head及审计归档；git历史瘦身另立迁移，不混入运维修复。

Claude只认领一个最终head；前轮packet全部由本包索引承接，不代ACK，不将context-emitted认作接受。`feat/fix/merge-fastcheck-gate-20261110`已有实现，勿重复派工；先查兼容性和当前owner再处理。

## 8. HC22：手机样式继续遵守原限制

本轮没有再改lab代码。后续以当前紧凑按钮为基线，只在≤760px局部选择器内改善可视度，不加全站button最小高度，不强制32/36/44px覆盖原尺寸。桌面、市场全景的每日速递/更多及参考点按钮都要做对照。

说明默认一行并可展开；参数展开须保留收起入口和内部滚动，不把结果区域推到不可达；操作计划不能隐藏，通知保持可见可点。风险说明逐文核对后去重，lab专属内容保留可展开。读屏名称、键盘焦点和触控实际命中一起验，不能只看元素height。

验收矩阵：320/375/390/430宽度、760/761边界、1280桌面；参数开/关、长基金名、多个筛选、横竖屏、系统放大字体。各态无页面横向溢出、按钮不意外换行、主要数据可到达；iOS Safari/Android Chrome各一次人工验收。复用现有`accept_market_overview_buttons.mjs`与旧移动验收脚本，更新失效选择器前保留旧对照结果，不拿伪造UI fixture替代线上实机。
