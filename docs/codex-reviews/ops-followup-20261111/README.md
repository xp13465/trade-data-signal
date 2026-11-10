# 运维修复统一交接补充 · 2026-11-11

本包承接 [前轮完整交付](../ops-closeout-20261111/README.md)，**仍有待发布的修复和未实施事项，不是全项目已修完**。本轮只读核查生产；只在独立 `codex/ops-followup-20261111` 分支新增本目录的审计文件及只读计数工具。没有修改业务源码、生产数据、systemd、调度或旧交接包，没有替 Claude ACK。

## 固定入口与分工

- 本次 native ID：`ops-followup-final-20261111-v1`。最终完整 head、报告 SHA256 和私有归档索引见该 packet。
- 继承业务交付：`ops-all-doable-final-20261111-v1`，head `0ad6556b58fabff4bce06ed291904f88b573c0f6`，报告 SHA256 `1e60a5d474a10c64a040eaabb0573da7f482a48089d50b5245ec0fb514cd07e0`。原包及其承接的 22 个历史 packet 保持原样。
- 本分支继承 0ad 全部内容；与 0ad 的差异仅为本审计目录。若原交付尚未合入，可按继承链一次审合；若原交付已合，只补本次资料提交，勿重复 cherry-pick 业务子分支。
- 既有业务测试 head 为 `b5a7483374d252c0622284f17560fd601eb55e3d`：Linux 4543 tests / 0 failures / 0 errors / 7 skipped，另有 browser 102 assertions、renderer 7。这些是原始测试范围，不是新 head 独立 review PASS。
- 观察到的 main/生产基线仍为 `f35437a699d199076b5654dcde58780be89ee6b4`。本轮资料发布不等于业务已上线。
- Claude 复核结论、认领业务修复、解决集成冲突、审合部署，并回报合并点与自然运行验收。Codex 的结论允许有异议，异议须绑定固定源码及可复现证据。同文件一个 owner，不整文件覆盖 pending-index。

完整 22 项状态及实施边界仍见 [TASKS](../ops-closeout-20261111/TASKS.md) / [REMAINING](../ops-closeout-20261111/REMAINING.md)。这份补充只更新下列已取得新证据的项目；历史盘点数量和历史监控快照不冒充当前值。

## 先处理的两类风险

### HC18：币种与价格字段，不能只修单位

[独立核查和父任务复核](fx-identity/report.md)确认：供应商将 `fx_susdcny` 绑定到在岸 CNY，`fx_susdcnh` 才是离岸产品；现源码把前者写入名为 `usdcnh` 的指标。依据是供应商产品页、代码绑定与响应名称，不是价格接近。[新浪 CNY](https://finance.sina.com.cn/money/forex/hq/USDCNY.shtml) · [新浪 CNH](https://finance.sina.com.cn/money/forex/hq/USDCNH.shtml)

解析器还与供应商页面的最新价/昨收映射相反。3 个纯函数反例复现：CNY 被接受、CNH 被旧前缀拒绝、区分两个价字段的样本解析次序相反。当前 CNY 快照两个价恰好相同，不能据此断言这次产生了数值损失。

只改 `FX_CODE` 不够；只改 YAML `enabled=false` 也不够：盘中写入不检查该开关，信号计算的固定 `GLOBAL_METRIC_IDS` 仍包含 usdcnh。须分别处理写入口、计算入口、已有结果的消费路径，并说明“不可用/待核查”，不能直接当中性或编造替代价。保留原 DB、冻结和已发历史；不全表除 100，不把现价拼入另一品种历史。前轮单位归一后的纯函数反事实**仍然 sell**，本轮没有推翻它，也没有证明买卖损失。

### HC21：发布重试改变最终树，必须重新验

[待合快检分支审计](fastcheck/report.md)：固定 `61a56ce7fc037e0a9f8ce8aad018ee1c173edd95` 的 7.10 正常错误拦截和 set-e 行为符合所测语义，但既有 push 重试在快检后执行 rebase，再直接 push。两侧分别三检通过的隔离文档变更，rebase 后出现重复编号，第二次模拟 push 仍执行。最小修法为 push 失败即停止，由主控更新基线后重新走完整入口；若保留自动 rebase，必须重验新树。这个缺口在当前 main 已存在，不能归因为 7.10 新引入。

该待合分支与 main/0ad 均在 `NOTES.md` 和 `docs/pending-features-index.md` 出现文本冲突。保留双方记录后产生新 head 再验，不选整文件 theirs。24/24 有界断言包含缺陷成功复现，**不是完整发布链 PASS**；未执行真实 main-merge、网络 push 或生产部署。完整脚本 `--dry-run` 也不是只读入口。

## 生产复查的限时结论

证据及时间见 [facts.json](facts.json)。07:15 CST 监控快照为 129 OK / 2 严重 / 2 警告 / 44 未知；原公募日更和过拟合失败仍在，不靠 reset-failed 消红。

相比 06:30，新增 3 个未知是公募季报 timer、季报 schedule 和监控自身 schedule。07:18 的独立 systemd 观察显示：季报 07:00 开始、尚在运行；监控 07:15:04 已正常 exit 0。因此这三项不等于新增三起故障，也不能写季报已完成。运行中的异步发布仍需该自然轮结果证明。

07:17 上游五只基金最新仍是 Nov9；016989 已补的 Nov9 unit/acc=1.1527、pct=-0.11 保持有效，Nov10 仍缺源值。前轮补数、桶合并、公网 hash 和四库恢复证明保留；本轮没有再次写数据。

## D1 可立即复用的只读工具

[capture_d1_metrics.py](capture_d1_metrics.py) 只读 GraphQL 日计数，不执行 D1 SQL、不建定时器、不发通知。它在 UTC 日未结束时先返回 `awaiting_window_close`，不读取凭据、不请求平台；缺数据、身份不匹配和响应错误不冒充 0；已闭合时间窗仍明确 `platform_finality_verified=false`。每份回执原子创建为私有文件，同名拒绝覆盖。

```sh
python3 docs/codex-reviews/ops-followup-20261111/capture_d1_metrics.py \
  --repo /Users/linhuichen/code/trade \
  --day 2026-11-10 \
  --output /tmp/codex-reports/d1-20261110-after-close-unique.json
```

Nov10 UTC 日到 Nov11 08:00 CST 才闭合；闭合后仍须考虑平台延迟。退出码 0=观察到已闭合窗口的合法计数，1=无法取得完整计数，2=窗口尚未闭合。实际 Nov9 读取成功：rowsRead 514080 / rowsWritten 341593；Nov10 提前调用被拒，符合预期。10 项契约测试通过（含时间边界、缺失/错身份、错误 JSON 形状、失败回执和同名原子拒绝覆盖）。日计数不等于逐阶段收益，不能由 changed 比例推导费用降幅。[官方指标边界](https://developers.cloudflare.com/d1/observability/metrics-analytics/)

### HC09 订正：平台已保留部分阶段证据

[逐查询补查](d1-insights/report.md)只用了 4 次只读 GraphQL 请求，未补跑同步或执行 SQL。Nov10 16:02–16:09 CST 的 score 哈希预读/COUNT 各读 28,456 行，screener 各读 28,476 行，合计 113,864 行；17 条查询明细与非分组汇总一致。两个数据库导入时点另外读 60,310 行、写 36,152 行，与窗口总计 174,174/36,152 对齐。日快照仅比该窗口多 8 次行读取。

因此，“没有持久化记录，所以完全无法追溯阶段消耗”过宽，现补充为：平台能恢复表级 SELECT 消耗，阶段名称由查询形态与代码推断；两个导入包只能按时间关联，不能精确拆到主表/索引/metadata，查询明细缺少这些写入的原因仍未知。数据来自 adaptive analytics，不是账单或收益对照。保留每次自然调用的原始 meta 建议仍成立：在解析/覆盖临时输出之前记录 call/bundle/attempt 与计数，缺字段留 null，不把整包写入全归给主表。[完整脱敏字段](d1-insights/report.json)

## 后续接力顺序

1. Claude 固定此次继承链审核既有业务修复；快检分支单独处置，发布路径不得自动 rebase 后沿用旧检查。构建/min/版本串、合并点 CI、云与站点部署、原 unit 自然运行都要留证据。
2. HC18 先明确品种/单位/价类型/源时间合同并控制不可信结果传播；历史重建与阈值重校另立迁移，不静默改历史。
3. HC13 关键 R2 覆盖保护仍未实施。旧版本可恢复证明、所有写者的条件写、multipart 最终提交、超时未知与持久 purge 顺序按原 REMAINING 落地；33 个离线测试不能写成生产 CAS 已开启。
4. HC07 缺口队列与增量、HC08/10/11 回执和 unknown 原因、HC09 阶段消耗、HC12 分段计时、HC22 手机局部可视度均有实施说明，未实施不能伪装为仅等外部依赖。
5. 真硬依赖包括：上游未公布的日期净值、历史冻结真实 T0 原件、D1 闭合窗口及平台数据、其他工作树 owner、部署后的真机验收。保护其他人的 dirty/locked worktree，不以当前评级制造历史。

Claude 回执至少包含：接收 packet ID + 完整 head + 报告 SHA256，逐项认可/异议和证据，owner/文件边界，审查结论、合并与部署点、自然轮验收结果。queued/context-emitted 均不代表已经接受。
