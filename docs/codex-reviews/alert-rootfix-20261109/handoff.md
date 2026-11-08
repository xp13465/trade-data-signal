# 交 Claude：11-09 告警根因修复整合包

以下复制框覆盖本轮分工、修复、历史未闭环与上线验收；不需要逐个转贴中间报告。完整 head 与报告 SHA 以最终 packet `alert-rootfix-20261109-final-v1` 为准。

```text
本次用户已特批 Codex 独立分支实现，Claude 最终复核、合并和部署；平时角色约定不变。

请在现有主会话接手 codex/reviewer，先读：
docs/codex-reviews/alert-rootfix-20261109/README.md
docs/codex-reviews/alert-rootfix-20261109/acceptance.md
docs/codex-reviews/alert-rootfix-20261109/verification-summary.json

最终固定 head、报告路径和 SHA256 见 handoff packet：
alert-rootfix-20261109-final-v1
先核完整 head/报告 hash，再显式回执 received→claimed；审合部署和验收完成后才能 completed。
scope-v1 和 fixed5123632 的中间 packet 仅保留证据，不能代替最终版本；原 FAIL/P2 报告不覆盖。

六组候选修复：
1. D1：稳定索引不再每轮重建；非索引字段变化不再维护全部索引。业务字段/hash/索引查询保留，真实总日额度仍 OPEN。
2. 监控：同一不可变 ID/payload 在原 8 秒内有限重试，安全错误分类；配额/约束/配置等永久故障仍失败且不盲重试。
3. nextday：真 live 模式、完整目标真实价格、完整轮次和可信 systemd 新轮次才放行降级恢复；缺价/干跑/嵌套歧义仍警。
4. 行情/冻结：只刷新自己来源的当日 OHLC，事务内保护强来源；冻结归档记录实际输入 hash/latest/保存结果；不改策略或防前视规则。
5. 停摆文案：两个巡检通道展示状态升级计数与迁移推算限制，不把它说成当前对象连续停摆天数；分级/计数/key/路由保留。
6. 备份：来源证明取自实际上传快照并绑定对象，恢复比同源字节与计数，live_drift 单列；坏库、截断响应失败不能阻断健康库，整轮仍失败。

各子分支提交已按图整合；只推送一个 codex/reviewer 整合分支。逐项固定 head、源码 hash 与复验在 verification-summary.json。
不要整文件覆盖 pending-index，不要重做我方已交付实现或另起自动编辑消费者；发现异议先按固定版本/反例复核，再在原任务范围沟通。

旧 cloud-alert-closeout-20261108-final 的 bf51cdd 已在 main：保留其三项先前上线事实和未回执状态，不重复合旧分支。
本轮新增六组尚未合 main/部署；代码验收不能写成生产根治。

仍需你处理/观察：
- 历史冻结 repaired=0/136；六个可核交易键仍缺五个。97个csi键=96早年+20261019待定1个；需要可信历史映射/信号首次可用证据，禁止用今天映射盲补。
- #373 的11-01/02缺备份是另一个磁盘事件，未恢复、不能用今天文件顶替；本轮备份误判修复不替其销账。
- 04:00自然cron已证实D1日写额度错误，同轮ingest200；四个旧Timeout/503不全已知同因。上线后记录真实用量，观察完整UTC日（08:00北京时间重置），本轮未改订阅。
- turnover 保留Nov6原exit124，等Nov9 21:10自然整链验退出、9件产物和公共交付；不靠reset-failed关单。
- R2 02:20批次02:35:29自然rc0，03:41三核心公开hash一致，属自然恢复，不归功未部署代码；其他传输稳定性继续观察。
- 指定016989原导出差异已解除；较新NULL净值、基金指数采集稳定性、risk70与A/F收益突变、缺失邮件正文仍没有根因关闭证据。

按 acceptance.md 的顺序审合和正常部署，确认 Worker 版本/云端源码 hash、旧库幂等迁移、自然任务及备份来源证明。保留实际测试版本、原始失败和复测末行；不写“一次全量全绿”。
请回执：是否接手、最终审查 head/结论、main合并点/部署版本、自然验收结果及仍 OPEN 的项。
```
