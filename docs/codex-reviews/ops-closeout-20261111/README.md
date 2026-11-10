# 运维告警完整收尾交付 · 2026-11-11

本包继承 `codex/ops-alert-recovery-20261110` 的全部实现，新增备份恢复实测、016989补缺与公开验收、历史逐键对账、汇率问题复现、平台计数和完整22项任务状态。**没有把“交付”写成“全部上线/全部根治”。**

集成分支：`codex/ops-closeout-20261111`。生产基线仍是 `f35437a699d199076b5654dcde58780be89ee6b4`；继承代码最后受测点 `b5a7483374d252c0622284f17560fd601eb55e3d`；前轮含文档head为 `2eb5f7abd03ff0cc86c025d6a95be8cb7addb895`。本轮其后只新增本目录审计产物。完整最终head及报告SHA以native交接包为准，避免自指哈希。

## Findings

### [P1] HC18：`usdcnh` 把两种报价尺度混入同一信号序列

- **origin=pre-existing，scope=in-scope。** 位置：`config/indicators.yaml:96`、`app/collector/intraday_snapshot.py:1668`、`app/compute/signals.py:840`。不是本轮修复引入。
- **Impact：** Nov10告警阈值、RSI和MA60受到百倍尺度断点污染，不能当正常技术指标解释。尚未证明卖出方向或资金结果错误。
- **Why：** 固定生产备份的888条非空记录，887条`akshare`约百美元报价、1条`intraday`为6.6724；盘中原值直接覆盖同一metric。生产纯函数原样复现“高672.1→阈374.7，当前6.672，RSI=0，MA60=662.8”。
- **Fix：** 先明确品种、单位及来源合同，阻断不兼容数据进入同一序列；展示实时外汇与历史信号输入分离。历史修复独立做版本化迁移，不能一条SQL将全表除100，更不能改冻结或直接调阈值。细则见 [REMAINING.md](REMAINING.md)。
- **trace：** 固定`f35437…`上述文件；关联用户“根治、避免覆盖、所有能做的交付”。
- **verifier：** `replay_cnh.py`抽出同一提交纯函数，读取本包888行原始切片。观察：原告警reason逐字匹配；仅把百美元值除100的诊断反事实变为阈6.7004/RSI11，**仍触发sell**。预期修复：同序列必须同品种同单位；异常明确data_quality状态，不用反事实证明交易方向已修。

中行官方注明牌价单位为100外币换人民币；中行折算价并不等同离岸即期价。代码注释对`fx_susdcny`名称有自相矛盾的解释，不能靠注释认定其就是CNH。[中国银行牌价说明](https://www.boc.cn/sourcedb/whpj/)

### HC13补证：覆盖保护可行，但尚未接入生产

此前33个离线测试单元证明备份失败仍覆盖、备份到覆盖之间竞态、固定备份键覆盖和部分通道源摘要错位风险；这是既有#237策略，不是新回归，也不是已经证明生产丢数据。本轮补查官方文档：`CompleteMultipartUpload`支持条件头，必须在最终Complete请求传递；仅Create传递不生效。固定生产`upload_r2.py:1120`最终Complete没有这些头。**旧报告“平台最终提交能力未证”的问题已由文档补齐；真实受控平台集成仍未执行。** [Cloudflare条件写文档](https://developers.cloudflare.com/r2/api/s3/conditional-operations/)

## 已完成的实操与证据

| 项目 | 本轮实际结果 | 边界 |
|---|---|---|
| 四库异地恢复 | 从R2独立GET/HEAD下载Nov10同run四个库；压缩/原文件SHA、长度、SQLite完整性、全部登记表行数4/4通过 | 含3.09GB public_fund；不导入生产，不替代Nov1/2历史原件；自然任务的公募SKIP仍保留 |
| 016989补缺 | 06:36现有定向采集补Nov9的unit_nav/acc_nav=1.1527及pct=-0.11；只改3个NULL，原非空和全局游标不变 | 使用现有源和锁，未修改线上源码；Nov10未公布的值仍NULL |
| NAV发布 | 原合并刷新函数只更新5c桶中的目标基金，保留另外106只；原上传器增量1/256、备份1成功、52秒exit0 | 避免全量`--codes`导出覆盖整桶；06:39公网完整hash及107代码集合核验通过 |
| 两ETF及另两QDII公网 | 159501/159513 Nov9值1.7541/1.5546已匹配；513080/513650亦核完整hash，4/4 | Nov10上游未出；不能宣称10条交易诊断已修复 |
| 换手/计划公开内容 | 11个完整响应与云端源长度/SHA一致：6个换手范围、overview、nextday、auto_trade_steps、day_snapshot、旧5c桶 | 旧桶后由本轮新桶验证替代；其它是采样时点，不是永久保证 |
| 自然任务 | 换手22:14:33 exit0、次日计划22:30:11 exit0；五换手指标日期Nov10 | 股票原始5195成功/5失败，聚合有效5188行；邮件应用回执sent不等于独立收件证明 |
| 历史冻结 | Nov10白天→Nov11清晨136键集合完全相同，无新增/移除 | 当前两运行树及Nov7预部署副本都缺7精确键及date/index候选；有限搜索不能证明所有历史副本绝不存在 |
| D1 | 平台API真实rowsRead/rowsWritten及两表自然同步count已取得 | Nov10 UTC统计日到Nov11 08:00 CST结束，且可能有平台延迟；不拿行变化比例冒充费用收益 |
| 监控未知 | 41未知拆成2定时器、34数据、4备份、1发布；逐项凭证/owner/过期规则已列 | 没有将未知批量清绿；监控还未消费本轮新增证明 |
| 本机与协作 | 49分支中33为main祖先；35工作树中22为main祖先；3个dirty文件和锁树明确保留 | 祖先不等于可删除，ignored文件及owner仍要核；仅清理本轮自产生的大型恢复临时副本 |

详细数字与采样时间见 [facts.json](facts.json)；完整任务不遗漏见 [TASKS.md](TASKS.md)；未知逐项映射见 [unknown-map.json](unknown-map.json)；工作树清单见 [worktree-inventory.json](worktree-inventory.json)。

## Open Questions / 未完成边界

1. **前轮机制修复仍待Claude独立复核、合并和部署。** 当前生产2严重/2警告仍是公募、过拟合原unit及对应调度；手动恢复数据不改原unit失败历史。未执行reset-failed消红。新源码未上线，不能承诺后续自然轮不会再报。
2. HC07增量/旧NULL、HC08逐attempt回执、HC10/11凭证接线、HC12阶段耗时、HC13覆盖保护、HC18数据口径及HC22样式优化仍有实施工作；本包已细化方案与验收，**不是全部代码已写完**。按共享文件/业务合同串行认领，见 [REMAINING.md](REMAINING.md)。
3. 10条近期交易诊断中7条缺历史冻结、3条待Nov10NAV；诊断本身`historical_should_trade=unknown`，缺原T0/当时评级输入时不生成历史交易。
4. 06:30监控132 OK/2 critical/2 warning/41 unknown；夜间新流水含00:00停摆和overfit、02:15相同136键告警。本轮没有独立登录收件箱确认送达，凭的是云端投递台账。不能把台账channels=true写成用户已读。
5. CF504有路径/Ray证据，平台内部原因未证；已有三次瞬态尝试，不再叠一层无限重试。
6. D1收益还缺完整同口径窗口与阶段计数。暂不把36,152对341,593的半日差异宣称89%节省或因果收益。

## Checks

前轮固定代码`b5a748…`的Linux CI为4543 tests、0 failures、0 errors、7 skipped，两个job成功；浏览器102项和生产渲染器7项另列，不重复累加。见 [前轮验证](../ops-alert-recovery-20261110/verification.json)及[CI](https://github.com/xp13465/trade-data-signal/actions/runs/42849179943)。这些不冒充本轮新head的独立审查。

本轮执行四库独立恢复、11公网全字节比对、4累计净值比对、补缺后新桶核验、888行纯函数复现和证据校验负控；具体新测试结果以`checks.json`为准。子代理额度耗尽，父会话核验不称独立reviewer PASS。

```sh
python3 docs/codex-reviews/ops-closeout-20261111/verify_evidence.py
python3 -m unittest discover -s docs/codex-reviews/ops-closeout-20261111 -p 'test_*.py'
.venv/bin/python docs/codex-reviews/ops-closeout-20261111/replay_cnh.py --repo .
```

脚本只校验归档证据或重放纯函数，不访问生产、不恢复数据库、不发通知。详细原始证据、带来源的恢复脚本及云端回滚前快照保留在本机私有审计归档；公开仓库只放脱敏结果。

## Verdict / 统一交接

**可独立完成的本轮取证、恢复与交付整理已完成；项目仍有待审发布和待实施事项。** 只审核这一条继承分支，不重复cherry-pick HC01–04及子分支，不整文件覆盖pending-index。先审已有修复，再给新增HC18及HC13定合同和owner。

本包承接前轮`ops-current-alerts-final-20261110-v1`，以及healthcheck-evening、healthcheck-next-evidence、healthcheck-wave1、alert-takeover等历史未回执内容，全文入口见 [handoff.txt](handoff.txt)。native queued/context-emitted不等于Claude已收到并接受。用户无需逐条贴旧消息。
