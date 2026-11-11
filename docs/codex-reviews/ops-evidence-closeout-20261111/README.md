# 告警与业务证据续作交付

日期：2026-11-11。用户授权 Codex 在独立分支实施待办，Claude 复核、合并和部署。
集成分支：`codex/ops-evidence-closeout-20261111`。
基线 `30df57e6bc20d15c7ec82c14c60626476ab7d622` 已合并上一轮 `af07a4b` 与 Claude 的 `d8c1aef3`，没有覆盖主工作树。
最终完整 SHA、测试末行、独立复核和报告散列在本轮私有总交付 JSON 中固定；本文件不使用自身尚未生成的 commit 作为证据。

## 本轮可直接审查的实现

1. **R2 请求检查与面板**：只读检查既有请求、owned proof 和 done/superseded 墓碑；显示待处理数、尚未进入批次的数量、等待秒数与凭证错误。目录、文件和并发校验失败、扫描截断、预算不足均保留 unknown。未见待处理记录只说明本地队列，不证明当前线上文件。没有改 enqueue/snapshot/finish/retire-source，也没有新增 worker。详见 [R2 文档](r2-request-inspect.md)。
2. **公募/FOF 采集凭证**：沿用真实 producer 的内存数据和事务提交结果，区分源日期、空响应、异常、所选批次与未尝试部分。沿用 HC07 预算和游标，不增加采集网络请求或数据库扫描。备份与 NAV 交付分开记。详见 [公募凭证](fund-evidence.md)。
3. **日程分母对账**：复用 canonical unit parser 和完整 registry，以固定日历、源文件散列、显式业务规则核验缺槽、重复、错日期与截止。只代表 repository-declared，带条件任务和未提供的合同继续 unknown，不证明云上安装或自然轮完整。详见 [日程合同](schedule-contract.md)。
4. **业务模型通知分类**：严格全渠道账仅对真实 overfit 来源、五个明确模型规则 key、对应主题和实际 notice/critical 类型排除为业务通知；运维 refs 和冲突标签优先。保留所有业务预警外发及历史 alert 群统计尺子，不按标题泛化静音。

## 为什么没有把公募整体标绿

当前采集凭证证明已执行的 SQL 输入提交，不是独立 DB 回读，也不是完整基金池或 NAV 上线证明。
还需把本轮基金/日期/值与 exporter 实际 NAV bucket 字节绑定，再接既有 R2 exact-byte/公开回读确认；FOF 还需明确后续哪一正常 exporter 消费该轮提交。
本轮不修改 deploy/upload_r2 的授权与发布判据，不用 summary JSON 上传、全局 MAX、rc0 或备份成功替代这个缺口。
因此 `public-fund` / `fof-nav` 没有整体 publication success 路径；这项后续工作仍保留在待办中。

原有“通常 T−1”、FOF T+1/T+2、旧方案上线次日 ≥90% 的限定口径仍适用。
本轮没有擅自制定逐基金公布 SLA 或逐请求超时阈值；详见上一轮 [已有合同核查](../ops-quiet-20261111/existing-contracts.md)。

## Claude 发布接力

请以本轮总交付固定 head 复核，勿拿分支旧 PASS 代替合并点验证；上一轮不可变总报告一并作为输入，不必逐条复制历史消息。

1. 确认生产 OPS_DB 的备份与 policy 2 已落实，保留实际查询/迁移证据。若仍为旧 policy，必须先处理，再执行可能触发自动 Worker 发布的 main push。已登记的旧迁移不原地改写，必要时新增前向迁移。
2. 经复核合并后核对合并 commit CI、站点 build/Worker 与云上实际代码版本。GitHub 部署任务成功不能证明 systemd、D1 policy 或业务恢复。
3. 通过唯一 canonical 文档生成并安装两个基金 service，保留现有调度和 timeout。新增 `Environment=OPS_DELIVERY_EVIDENCE_ENABLED=1` 只启用阶段凭证；核对 EnvironmentFile/drop-in 是否覆盖，以及真实运行的 InvocationID。FOF 原 unit 不读取 `.env`，不能只改 `.env` 就认为已启用。
4. 在审核后的实际 Python 运行入口核对 loaded module digest，配置既有私有 `data/ops_delivery/producer-identity.json`。不要仅复制任意 receipt 的 digest 作为批准；helper/入口导入命名空间变化须重新核对。详见公募文档的身份步骤。
5. 采集器配置新增 `r2_pending_flag`，必须与生产 uploader 的真实值一致；示例为 `/tmp/trade_r2_upload_async.pending`。未配置保留 unknown，不会悄悄读取另一套默认队列。核验管理员面板中的两项基金证据和 R2 队列详情。
6. 在发布身份固定后预先冻结自然观察计划与真实交易日历，再记录每个应跑轮次、原始失败和补跑。单次离线回放、测试全绿、采集新鲜或“没有新邮件”都不证明根因关闭；14/30 日窗口也不能跳过周/月/季频所需轮次。

Codex 本轮没有执行生产任务、上传/部署、迁移 D1、改主工作树或发送测试运维通知。
原生 handoff 的 queued/context-emitted 与 Claude 明确 ACK 分开报告；没有 ACK 不写成“已接单”。
