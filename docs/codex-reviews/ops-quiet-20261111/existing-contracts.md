# 已有业务期限与 skip 接手口径：有界补查

日期：2026-11-11。范围限于公募/FOF、overfit，以及 update_all、turnover、R2 async 三类锁跳过。本文件整理已有约定及其证据边界，不新增 SLA、阈值或业务行为，也不证明生产已部署或自然运行已达标。

## 结论：收窄原 execution-gap

原私有 `execution-gap.md` 将“源预计发布日期/允许空范围及业务截止未具体化”“需要补定业务合同”概括得过宽。**本次补查收窄这些表述：先复用已有产品、验收、监测和接力合同，只对确实未查到或相互冲突的边界继续核对。** 原报告及失败证据保留，不覆盖历史记录。

| 主题 | 已有口径 | 仍未查到或不能据此推出的边界 |
|---|---|---|
| 普通公募 | 产品“通常 T-1”；全局最新非空净值落后 ≥2 交易日 severe；今日晚间全 NULL 与历史全 NULL 分级 | 每只基金每天确定的源公布钟点；指定全集、全部字段每日 100% 完整的截止 |
| FOF/QDII | T+1/T+2 公布特性；21:10 采集槽；上线次日、最近两交易日 `unit_nav` 非空率 ≥90% 的方案预期 | 上游保证 ≥90%；长期每日同一比例承诺；历史全覆盖完成日；次日预期与多轮分批的协调口径 |
| overfit | 每日打点；交易日 21:40 启动；同日同代主/ext和公开核验；旧日产物不得跨日补传 | 固定 HH:MM 前必须成功交付；不能由 1920 秒硬墙推导 22:12 SLA |
| 三类 skip | 既有首报原则；R2 逐请求 proof 与完成判据；任务级连续 skip 监测 | 逐请求创建后多久超期、接手实例失效后多久升级、下一正常 worker 最迟何时出现 |

“未查到”只限下述固定版本和检索范围，不代表所有私人历史对话均无约定。文档里已有口径，也不等于它的自然验收已经完成。

## 固定身份与复核方式

| 身份 | 完整 commit / 摘要 | 含义 |
|---|---|---|
| 原有界补查树 | `22bfb45171bf128a2cacf1cba017c9baa470f0b8`，`codex/ops-quiet-20261111` | 用 git archive / 同 head 的 git show 读取，没有依据后续工作树 |
| 补查开始时 main | `2987bd337490e7ed400903bca182b524d94955ee` | 当时本地 main、origin/main 与 `git ls-remote --heads origin refs/heads/main` 一致；不是当前生产身份声明 |
| 本文落档父提交 | `bd7feda6530387ef4c0978be0c3922803976298c`，`codex/ops-quiet-unit-20261111` | 本文唯一新增于该独立分支；未更新集成树或业务源码 |
| 原补查报告 SHA-256 | `643ba57aef4661f5976f5a8e335fa46fd6a58d84317e3c521cbb2abfd0e76076` | 私有 `deadline-contract-search.md` 的完整原报告身份；本文是可移植整理，原报告不变 |

本次落档再次核对以下 17 个主要来源：README、#333 计划及 unit 模板、#251 复审、10/09 降噪记录、overfit 设计及 11/10 两份交接文档、R2 shared-export handoff、alert-checker registry、repository_tasks，以及 `check_data_gap_alerts.py`、`schedule_monitor.sh`、三类 skip hook、`r2_pending_context.py`。它们在原补查树、上述 main 和本文父提交中逐 blob 一致。

以下链接均为仓内相对路径。定位采用章节、任务 ID、函数和常量，不把旧行号移植到新 head。以后来源变化时，可先取固定内容，再搜索同名符号，例如：

```sh
git show 22bfb45171bf128a2cacf1cba017c9baa470f0b8:docs/ops/333-fix-plan.md
git grep -n -e FUND_NAV_FRESH_LAG_SEVERE -e check_fund_nav_freshness \
  22bfb45171bf128a2cacf1cba017c9baa470f0b8 -- scripts/check_data_gap_alerts.py
git grep -n -e R2_SKIP_CONTINUOUS_THRESHOLD -e r2_round_id \
  22bfb45171bf128a2cacf1cba017c9baa470f0b8 -- scripts/schedule_monitor.sh
```

### 已查范围

原补查归档 1776 个文件，覆盖全部 tracked `docs/`、`config/`，根 README/TASKS/CLAUDE/AGENTS，以及相关 registry 和一跳运行消费者。先按公募/FOF/QDII、overfit、skip/pending/handoff 和公布/覆盖/完整/截止/超期/接手/拍板/验收/SLA/deadline/expiry/TTL 筛选，再读取命中条款及上下文；不是逐字通读全部归档。

重点包括 [PRD](../../PRD.md)、[README](../../../README.md)、[TASKS](../../../TASKS.md)、[功能台账](../../pending-features-index.md)，#251/#333 文档，Kelly overfit 设计、11/10 恢复交接，运维告警 registry、架构 schedules/runtime/inventory，systemd 生成源和版本快照，以及 R2 接力、skip 分诊、降噪记录。11 个 tracked config/示例包括 daily_brief、site、indicators、universe_rules、订阅/通知示例及 Kelly 接受清单，未找到本题的业务截止或 skip 请求租期。

没有读取生产密钥、全搜私人聊天/未归档 memory、运行云端任务或重跑 full/R2/手机测试。本文件中的“未知”不外推到未搜索范围。

## 公募：已有产品新鲜度与监测容忍范围

[README](../../../README.md) 的产品原文：

> 每日 update_all 盘后链自动刷新；当日净值晚间公布，入图最新通常 T-1。

“通常”是产品公示中的限定词。[#251 复审](../../ops/251-fundnav-fix-review-20261012.md) 的“必查-2 「1 天延迟」是否被引入”及其中“站点承诺新鲜度”段解释了窗口日回退前一日真值、次日补回正确日期，并提到 16:00–17:00 的源发布节奏。这是复审解释，不是外部数据源每日确定钟点的 SLA；不能把它与 README 的“晚间”、告警的 20:00 容忍窗合并成一个保证公布时间。

[check_data_gap_alerts.py](../../../scripts/check_data_gap_alerts.py) 已有下列规则，对应 [10/09 降噪记录](../../ops/alert-denoise-batch2-20261009.md) 中公募全 NULL 首日时滞条款：

- `check_fund_nav_freshness` / `FUND_NAV_FRESH_LAG_SEVERE = 2`：`MAX(date) WHERE unit_nav IS NOT NULL` 落后最近交易日 ≥2 交易日为 severe。它检查全局是否前进，不验每只基金、每个字段的完整率。
- `check_fund_nav_allnull` / `FUND_NAV_PUBLISH_WINDOW_HOUR = 20`：今日全 NULL 且已进入晚间发布窗口记 info；早于今日的全 NULL 为 severe。另有 `FUND_ALLNULL_MIN_TOTAL = 1000` 的行数门槛，不能省掉适用条件。

所以不能再报告“没有新鲜度标准”，也不能由全局 MAX 正常推断全池齐全。未查到逐基金的源公布保证、每日完整字段全集及成功截止。

## FOF/QDII：已有用户拍板方案和量化预期

[#333 计划](../../ops/333-fix-plan.md) 的身份原文：

> 立项:用户 2026-11-01 拍板,走方案 A(独立采集器走历史 API,止漏核心)。批1 只做止漏,不碰批2/批3(份额类清理/定开识别/历史回填)。

该文件最后修改于 `4671b3d9cfaf1fbe33f4b79b4518864cb98e2bb9`（2026-11-02）。这是仓库记录的用户拍板方案；本次未另查原始私人对话。“二、实现预期”的原文为：

> 批1 上线(21:10 timer)次日,`fund_daily_nav` 中 FOF/QDII(类型 LIKE 'FOF%'/'QDII%')在最近 2 个交易日的 `unit_nav` 非空率从 ~0% → ≥90%(上游发布率,调研 20 只样本 13/20 有值=65%,但 FOF 占绝对多数且 FOF 上游几乎全有,预期 ≥90%)。

这是已有上线验收预期，不能漏列，也不能把有限样本的“预期”写成上游保证。该计划“可修正的依据”明确描述 FOF/QDII T+1/T+2 跨日公布；近 7 自然日查询用于覆盖 T-1/T-2 与周末；“时点与部署”及 [unit 模板](../../ops/333-systemd-unit-template.md) 的 21:10 是采集启动槽。

同计划“采集器设计”又写“每轮最多采 BATCH_SIZE=500 只,剩余下轮续(配合跳过已填几轮覆盖 1796)”。预算用 50 只样本平均 0.51 秒/只估算 500 只正常约 255 秒，内层 600 秒、外层 900 秒。这些是当时的规模、样本和技术预算，不是当前全集大小或最忙尾部时限证明。“上线次日 ≥90%”与“几轮分批覆盖”仍须按真实上线轮次和分母核对，未找到把二者协调成每日一轮全池完整的补充条款。

“六、批2/批3 待办”的历史阶段划分，不等于现行历史回填实现缺失。HC07 已合入的分页、事务、预算、尝试轮转和 recent 空窗推进应复用；可从 [collect_fof_nav.py](../../../scripts/collect_fof_nav.py) 的 `work_limits`、`recent_through` 追踪状态。尝试游标与业务覆盖状态不能互相代替。[功能台账](../../pending-features-index.md) 的 `#333` 也明确写“旧21:10 rc0不代表本键已恢复”。

真正未查到的是：历史全覆盖完成日、完整字段集合的每日成功截止，以及封闭/未发布基金如何进入上述 ≥90% 分母的完整规则。应先使用已有预期验收，不把全部业务口径重新交用户从零决定。

## overfit：每日需求、启动时刻与当日有效期

[overfit 设计](../../kelly/analysis/kelly-overfit-monitor-design.md) 的“需求一句话”要求“每日打点”；时点原文为“建议 21:40”，后续定时记录为交易日 21:40。它们明确每日需求和启动时间，没有声明成功交付的固定钟点。

[同日发布恢复说明](../ops-overfit-retry-20261110.md) 写明：

> 预期：短暂占锁在同一任务中恢复，仅重试发布；计算/模型预警只执行一次。持续失败非零、当日过期产物不可补传。

其“实现边界”还限定北京时间午夜、主/ext同日同代、跨日失败可见。该说明要求后续集成以 [最终恢复交接](../ops-alert-recovery-20261110/README.md) 为准；后者“尚须发布验收”仍明确：

> 过拟合跨日不重发旧日文件，应等待下一当日有效产物/自然轮，不绕过新日期门禁。

这是已有的产物有效期与失败可见性约束，不是“保证午夜前成功”的 SLA。主/ext同代和四个公开 URL 的长度/SHA256 核验属于既有成功条件，不能以本地文件或单独退出码替代。运行入口为 [overfit_monitor.py](../../../scripts/overfit_monitor.py) 的 `publish_overfit`。

1920 秒 systemd 硬墙、通常 960 秒发布预算、最多 8 次退出 75 重试/退避 30 秒、schedule 的 1500 秒耗时告警，均是执行/运维预算，不能推导 22:12 或其它业务成功截止。22:35 gap checker 的“晚链后检测”说明同样不能倒推出交付 SLA。

旧设计“小于 1MB 走 CF 静态而非 R2”和 [9/24 skip 分诊](../../ops/r2skip-alert-triage-20260924.md) 中“次日 deploy 兜底”的历史描述，不能覆盖后来的 R2 双文件公开验证和同日门禁；“可选加次日判据”也不是已经承诺的新截止。

## 三类 skip：已有首报、接力和持续故障监测

### 首报与接手不是一件事

[alert-checker registry](../../ops/alert-checker-registry-20261015.md) 对三个脚本均登记“首报必达”：`on_skip_notify.sh`、`turnover_backfill_skip_notify.sh` 为 severe/collect；`r2_upload_skip_notify.sh` 为普通出口、r2、21600 去重窗口。去重窗口不是允许请求积压 6 小时的业务时限。

[update_all hook](../../../scripts/on_skip_notify.sh) 的 `BODY` 明确“本次跳过未执行采集”；[turnover hook](../../../scripts/turnover_backfill_skip_notify.sh) 的 `BODY` 还写“当日 a_turnover_* 可能缺”。后者有意写正常开始/结束 exit0，避免调度器误报漏跑，因此正常结束记录不能证明请求已接手或业务已完成。

### R2 已有逐请求完成合同

[Shared export 与 pending proof 接力](../../ops/r2-shared-export-handoff-20261106.md) 的“现有 pending 的逐请求接力”，最后修改于 `e6f1c421c7718e24ab4f44ab9cac925c7dcaa1a3`（2026-11-06）。条款包括：进入 async 外锁前登记 run ID、canonical root、不可变 proof SHA256 及 queue-owned exact-byte proof；同 run/hash 幂等，不同 run 分别保留。

> 结果绑定本批 batch ID、请求 ID/hash 和实际确认 payload。全部所需文件已确认，或由同批另一个真实 proof 的 current bytes 取代，才可标 done/superseded。其他数据通道失败、缺 proof、hash 不符或中途 bytes 改变都保留未消费记录。

> 最终 snapshot 之后到达的请求允许由下一次正常 worker 消费：其 ID/hash、owned proof 和 pending flag 必须保留，remaining 显式写日志；不能把它报告为本轮已成功。

正常 worker 初次加至多一次 catch-up，snapshot 最多 32 条，按 `offered_at` 公平轮转，预算不扩大。[r2_pending_context.py](../../../scripts/r2_pending_context.py) 的 `enqueue`、`snapshot`、`finish` 是对应入口；`created_at`/`offered_at` 留痕和排序不等于超期租期。不能再报告 R2 完全没有接手与完成依据，也不能将仍 pending 的请求计作成功。

### 任务级持续 skip 监测已存在

[schedule_monitor.sh](../../../scripts/schedule_monitor.sh) 的 `R2_SKIP_CONTINUOUS_THRESHOLD = 3`、`R2_SKIP_ESCALATE_ROUNDS = 6`、`R2_SKIP_OBS_WINDOW = timedelta(minutes=30)` 是既有口径。6 轮升级仅针对 `R2_SKIP_TRANSIENT_TASKS` 指定的 `gen_daily_brief`/`fetch_news`；计数按 `r2_round_id`，缺失回退 `last_run`，防止同轮重复计数。

这是 task/stats 中 `SKIPPED_LOCKED` 的不同运行轮监测，不是 R2 async `.contexts` 每条请求的年龄检测。不能按旧注释“15min/轮”直接换算请求 SLA。#181/#181race 注释记录计数语义修改曾获用户拍板，不能把它列作缺失机制。overfit 原始 skip 保留，只有 `r2_skip_recovered` 且最终 exit0 的已核验同轮恢复才结束未上传链。

### 冲突和真正缺失的边界

[r2_upload_skip_notify.sh](../../../scripts/r2_upload_skip_notify.sh) 的旧“并发跳过标记(2026-10-04 ③)”注释声称“保证同日内数据上 R2”“不拖到下一趟 deploy”。同文件较新的通知正文和 11/06 接力文档却允许晚到请求留给下一正常 worker。旧“单文件/同日保证”应标为文档冲突，不能当成现行严格交付承诺，也不能仅凭冲突宣称复现了业务故障。

在本次已查范围内，没有找到三类 skip 逐请求的超期年龄、下一正常 worker 的最迟时间、合法接手实例退出/失效后的升级时限及与请求 ID/proof 一一对应的超期监控合同。前两类也未查到与 R2 同等的逐请求接力合同。现有首报和任务级持续告警不应因未来可能接手而凭空静音；本条不授权另设阈值。

## registry、config 与验收边界

[repository_tasks.json](../../ops/architecture/inventory/repository_tasks.json) 用以下稳定 `id` 定位：`task:fof-nav-collect`、`task:overfit-monitor`、`task:public-fund-daily`、`task:turnover-backfill`、`task:r2-upload-async`。这些记录的业务正确性/恢复标准和 `runtime_observed_at` 为 `unknown`，属于仓库声明，不是当前生产观测。FOF900、公募2100、overfit1920、turnover0 等 `TimeoutStartSec` 不补出业务 SLA；R2 async 是条件触发链，也不能从 registry 得出下一 worker 的时间上界。

[ops_business_evidence.py](../../../scripts/ops_business_evidence.py) 的 `valid_until` 默认 started+26h，是证据新鲜度 TTL，不能改称 overfit 成功截止或 skip 请求租期。config 中未找到相应业务时限，亦不代表可自行从技术预算补设。

后续整合应复用 HC07、overfit 同日补传、R2 proof 接力和现有监测；分别证明源已发布集合、完整率/字段、历史缺口、公开交付与实际耗时。全局 MAX、rc0、轮转进度、平均耗时、任务结束、通知去重窗均不能替代这些业务事实。已有 ≥90% 预期、最忙尾部可达性和自然交付是否达标，本文件未重新验收；未查到的边界及文档冲突须另核依据，不能整体回退为“所有合同都待用户决定”。
