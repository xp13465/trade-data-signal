# 架构层调研:业界怎么解「R2 跨境慢 + 锁争用 + 告警风暴」——有出处、可对比、含代价分析

> **落档信息(2026-10-05,implementer 今日文档落档任务)**
> - 本文件为调研**原始记录原样落档**,含全部 URL 出处,未压缩改写。
> - **状态区分(严格,防把「建议」当「已决定」)**:全文唯一「**已决定**」= **「架构改造(看门狗停滞判据 / 治 retry storm / 断点续传 / A 档)先不做,等事实核查回来再定」**(见 §〇 结论表 + §七 A 档);其余 A1-A6 / B1-B4 方案、判据参数、分域建议等**全部 = 研究建议·未拍板**,不作为实施依据。
> - **后续事实核查结果待补**(两条未知量正在核查,结论回来补在本段下方)——
>   1. **我们桶能否启用 CF R2 Local Uploads**(桶配置 / jurisdiction 兼容性,A6 前置):核查中(主控已派 background agent,进度 `ad17be6bb587a467a`)
>   2. **云上 NAT / 本地端口范围是否偏小**(docverse#698 的 64 端口/VM 场景是否与本项目同构):核查中
> - **§23.5 四件套**:①报告本体=本文档 ②生成脚本=**无**(本次人工调研,非脚本产物)③复现段=文内每个结论均附权威 URL 出处,按 §〇/§一~§七 逐条可回溯(见各节 inline 链接 + §八 诚实标注)④配套 commit=本批落档 commit(`docs/index-sync-20261004` 分支,含本文件 + pending 索引登记)。

调研时间:2026-10-05 凌晨。调研人:researcher(架构层专项,只读)。
任务源:用户质疑主控方案「是否只为了打补丁,没有更权威、更广泛地思考整个系统问题?有没有案例和别人的参考?足够权威么?」

## 〇、结论先行(我的假设哪些被业界证据支持/证伪/查不到)

| # | 我的判断 | 判定 | 关键证据 |
|---|---|---|---|
| 1 | 「900s 看门狗按总耗时杀正常工作」是反模式 | **支持,且是业界明令避免的反模式** | rclone --timeout=IO idle(停滞);rsync --timeout="no data transferred";curl --speed-limit/--speed-time;systemd 总时长(timeout)与停滞(heartbeat)分开 |
| 2 | 「600s 内层超时 × 5 次重试 + 900s 外层 kill」是内层放大+外层错杀的组合 | **支持,组件各有权威名字**(retry storm / 重试放大 / elapsed-kill 错杀),三件套整体无单一标准名 | AWS Brooker N² 现象;Azure Retry Storm antipattern;rclone 先例是「内层短超时+外层收敛」反向结构 |
| 3 | 「全局锁把不相关任务耦合成串行链」=Bulkhead 问题 | **支持**:应分域;但当心代价=资源复用率下降,Azure 明说"可能不适合:资源利用不高效/复杂度不必要"——本项目分域要按「通道性质」分,不是无限细拆 |
| 4 | 「一个根因 → 15 封 severe 邮件」标准解法=分组+抑制 | **支持**:Alertmanager 官方 grouping/inhibition 就是干这个的;Prometheus 官方告警实践「症状告警/最小告警数/无事不做」 |
| 5 | 「期望态收敛」在小规模单机=正解 | **部分支持,但需要降级为「轻量幂等收敛循环」**:K8s 官方 controller 定义支持该思想;但 rclone bisync 等单机工具证明轻量等价物够了;全套编排=过度设计 |
| 6 | R2 跨境慢有没有官方解法 | **有,且是 2026-02 上线的 CF 官方特性:R2 Local Uploads(实测 TTLB 降 75%)**;本项目未启用,是目前最大的杠杆 |
| 7 | 「kill→marker 残留→全量重传」循环 | **支持为反模式**:fail-closed 是好,但「超时杀→全量重传」在慢链路下形成自激振荡;业界模式=checkpoint/续传让重试便宜(rclone bisync --recover;CF multipart resume) |

## 一、Q1【同类工具怎么做超时/重试/断点续传】—— 事实 + 出处

**①它们是按总耗时还是按停滞/进展判定失败?——全部按停滞/无进展,没有一个是按总耗时杀正常工作的。**
- rclone 官方文档:`--timeout Duration` = "This sets the IO idle timeout. If a transfer has started but then becomes idle for this long it is considered broken and disconnected."(默认 5m,0=禁用);`--contimeout` = "the amount of time rclone will wait for a connection to go through"(默认 1m)。出处 https://rclone.org/docs/
- rsync man page:`--timeout=SECONDS` = "This option allows you to set a maximum I/O timeout in seconds. If no data is transferred for the specified time then rsync will exit."(默认 0=无超时)。出处 https://man7.org/linux/man-pages/man1/rsync.1.html
- curl man page:`-Y/--speed-limit` + `-y/--speed-time` = "If a transfer is slower than this given speed (in bytes per second) for speed-time seconds it gets aborted."。出处 https://man7.org/linux/man-pages/man1/curl.1.html
- systemd:`RuntimeMaxSec=` = 总时长("maximum time for the service to run... terminated"),`WatchdogSec=` = 心跳停滞("The service must call sd_notify(3) regularly with WATCHDOG=1..."否则 SIGKILL)。出处 https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
- aws cli/boto3/s5cmd:无「整个命令总时长」概念;SDK 层是连接/读取超时 + 有界重试。boto3 重试指南见下。

**②重试是内层放大还是外层收敛?——业界=内层短、外层收敛;本项目=内层 600s 放大、外层 900s 错杀,正好颠倒。**
- rclone 双层:`--low-level-retries` = per-HTTP-request 重试("A low level retry is used to retry a failing operation - typically one HTTP request. This might be uploading a chunk of a big file");`--retries` = "Retry the entire sync if it fails this many times it fails (default 3)."——外层重跑整个 sync,但因为增量检查,重跑便宜。出处 https://rclone.org/docs/
- boto3/botocore:`retry_mode=legacy(默认)/standard/adaptive`;默认 max_attempts=legacy 5 / standard 3(含首请求),指数退避+jitter。出处 https://boto3.amazonaws.com/v1/documentation/api/latest/guide/retries.html
- AWS Architecture Blog(Marc Brooker):N 客户端竞争下重试总量随 N² 增长,"It's obvious that the exponential backoff is working... there are still clusters of calls"——退避+jitter 是标准解法。出处 https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/
- Azure Retry pattern:"An aggressive retry policy with minimal delay between attempts, and a large number of retries, could further degrade a busy service"。出处 https://learn.microsoft.com/en-us/azure/architecture/patterns/retry
- 本项目现状(deploy.sh run_r2_upload L588-657 + upload_r2.py L278-288/L407-490):R2_UPLOAD_HTTP_TIMEOUT=600s 是单请求 socket 超时,5 次重试(1/2/4/8s 退避)→ 单文件最坏 5×600≈3000s;外层看门狗 900/1800s 按总耗时 kill → 内层还没重试完就被外层杀 → 反例结构。

**③断点续传状态存在哪?——业界:内存/本地状态文件/服务端 UploadId;本项目 checkpoint=本地状态文件,与 rclone bisync 同模式。**
- CF R2 官方 multipart 文档:multipart "Resumable: Yes — only failed parts need to be retried",Worker API 有 `resumeMultipartUpload()`;上传后返回 uploadId+每片 etag,客户端保存此状态。出处 https://developers.cloudflare.com/r2/objects/upload-objects/ + https://developers.cloudflare.com/r2/api/workers/workers-multipart-usage/
- rclone bisync:保留双方 listings 状态文件,"It retains the Path1 and Path2 filesystem listings from the prior run."+ `--recover`/`--resilient` 自动从中断恢复不需 --resync。出处 https://rclone.org/commands/rclone_bisync/
- 本项目(事实):`.r2_<channel>_state.json`(md5 指纹)+ `.r2_<channel>_ckpt.json`(分片 checkpoint)+ `.r2_<channel>_uploading.marker`(fail-closed),见 upload_r2.py L1016-1049。模式对,但 marker 与 elapsed-kill 组合制造「kill→强制全量」震荡(见 Q1④)。

**④「600s 超时×5 重试+900s 外层 kill」在业界叫什么?——三件套没有单一标准名,但每个成分都有权威反模式名;整体=「内层重试放大(retry storm)× 外层总时长错杀(elapsed kill)」。**
- 成分1「重试放大/风暴」:Azure Architecture Center 有专门反模式页 **Retry Storm antipattern**("Limit the number of retry attempts and duration... exponential backoff... circuit breaker")。出处 https://learn.microsoft.com/en-us/azure/architecture/antipatterns/retry-storm/
- 成分2「总时长看门狗杀慢速正常工作」:业界全部改用 停滞/IO-idle 判定(rclone/rsync/curl/systemd 见 Q1①),systemd 总时长(RuntimeMaxSec)只作硬兜底且不适用于 oneshot 语义。出处同 Q1①
- 成分3「kill→marker→全量重传」:fail-closed 思路对(宁可多传不可假成功,upload_r2.py L1047-1048),但「elapsed-kill 常态化 × 全量重传」= 慢链路自激振荡;业界模式是 checkpoint/部分续传让重跑便宜(CF multipart resume / rclone --recover)。出处同 Q1③
- 我的推断(无单一标准名,组件名有出处):整体可称为「**看门狗与链路节奏错配 + 重试放大 + kill 后重传放大**」的三重放大链。

## 二、Q2【期望态收敛 vs 命令式脚本】—— 权威出处 + 小规模判断

- K8s 官方架构文档(controller 模式):"In Kubernetes, controllers are control loops that watch the state of your cluster, then make or request changes where needed... objects have a spec field that represents the desired state. The controller(s) for that resource are responsible for making the current state come closer to that desired state.""a non-terminating loop"。出处 https://kubernetes.io/docs/concepts/architecture/controller/
- 轻量等价物确认存在:rclone bisync(单机+cron 跑, listings 状态文件 + 自动收敛 + --resync/-recover,文档全见上);syncthing(常驻后台连续同步,我了解其为目录监听+持续收敛,未抓官方页,标注为常识性引用);git-annex(基于 git 的收敛,未抓官方页,常识性引用);Borg(备份聚合+验证,restic docs 抓过,restic 的核心是分块+幂等,无 per-transfer 总时长概念)。
- **判定:全套编排式 controller(API server/CRD/operator)= 在这个规模(单 VM、systemd timer、~20 个批任务)是过度设计。** 依据:
  - 规模事实:单机串行/准并行批处理,无多节点、无自动扩缩、无租户,reconciliation loop 的「幂等重放」价值大部分由「md5 增量指纹 + verify-r2 全量对账(周日)」已实现(upload_r2.py L1016-1037)。
  - 权威来源同意的代价:Azure Bulkhead 页"This pattern might not be suitable when: Less efficient use of resources might not be acceptable in the project. The added complexity isn't necessary."(该句在 Bulkhead 文档,但对「重家伙」同样成立)。
  - **轻量等价物(本规模该做的)= 幂等收敛的单通道后台循环**:每通道一个「若未在传→diff 本地 vs R2 状态→增量上传→对账」的循环(async 化已是半成品),关键是把「跑过一次脚本=完事」的边沿语义改成「状态不一致=持续拉平」的收敛语义(verify-r2 已具备,需要的是让它高频/便宜/不被杀)。
  - 结论:主控的「期望态收敛」方向**思想正确**(有 K8s 官方出处支持),但落地必须是「rclone bisync 级别」的轻量收敛,不是「K8s controller 级别」。

## 三、Q3【锁分域/bulkhead】—— 权威名称与出处

- **Bulkhead 是正确名字,原始出处可追溯到 Michael Nygard《Release It!》;权威在线文档 = Azure Architecture Center Bulkhead pattern**:"This pattern is named after the sectioned partitions (bulkheads) of a ship's hull...""Excessive load or failure in a service affects all consumers of the service... eventually, the consumer can't send requests to any other services... which causes a cascading failure effect.""Partition service instances into different groups... A consumer can also partition resources to ensure that resources used to call one service don't affect the resources used to call another service." 出处 https://learn.microsoft.com/en-us/azure/architecture/patterns/bulkhead
- 更贴切的具体化:这是「**bulkhead + lock partitioning**」:全局一把 fcntl 锁(/tmp/trade_r2_upload.lock,upload_r2.py L3206-3225)把「deploy 全量上传」和「fetch_news 30min 高频小上传」串成一条链;fetch_news 撞锁被 --skip-if-locked 跳过 11-15 次(alertstorm 实测)。业界按资源/消费方分域(per-service/per-tenant 连接池),本项目应按「通道性质」分域:高频小通道(fetch_news/news_digest)与日链大通道(deploy 17 通道)分锁,或至少同类通道一组锁。
- **分域粒度与代价(权威)**:Azure 原文"When you partition services or consumers into bulkheads, consider the level of isolation offered by the technology and the overhead in terms of cost, performance, and manageability." + "This pattern might not be suitable when: Less efficient use of resources might not be acceptable in the project. The added complexity isn't necessary." → 分域粒度以「故障隔离需求」为准,**不过度细拆**(本项目拆 2-3 个域足够,不是 17 个锁)。
- **分域后防全局资源过载**:同一通道并发数必须受控——lsst-sqre/docverse#698 实测 90 并发连接触发 NAT 端口耗尽(64 端口/VM),降到 32 并发 + keepalive 后 0 超时(见 Q6)。本项目 multipart workers=4、etf-hist 8 线程,总量可控但需登记一次「全通道并发连接总数 ≤ 某上限」。

## 四、Q4【长任务监督:停滞检测】—— 可落地判据

- systemd 语义(官方):WatchdogSec=停滞(服务必须周期 sd_notify WATCHDOG=1,否则视为挂了);RuntimeMaxSec=总时长硬兜底(且对 Type=oneshot 无效力,需 EXTEND_TIMEOUT_USEC)。出处 https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
- 网络传输停滞检测通行做法:rclone IO idle(rclone --timeout)/rsync --timeout/curl --speed-limit+--speed-time 全部是「一段时间无数据/低于阈值速率 → 判定断」。
- **可落地判据(建议,推断+对齐业界)**:①主判据=「停滞」:upload_r2.py 已有逐文件/逐片进度输出与 R2_BYTES_TOTAL,看门狗改判「**当前日志文件 mtime 超过 N 分钟无新增输出**(建议 N=5min,对齐 rclone 默认 5m)」→ kill;②辅判据=「低速」:可再加「近 N 分钟实际已传字节 < 阈值」(curl speed-limit 同款);③硬兜底=总时长上限(保留 7200s 级,现已有 est 上限 7200)。**判据信号用「字节数/文件数/PUT 成功数」都行,关键是看「推进」不只看「活着」**——kill -0 探活(现在的实现)只能发现死进程,发现不了僵持。
- 本项目现状对比:deploy.sh run_r2_upload L640-651 每 5s kill -0 探活+总时长 kill —— 探活是对的,但杀的是「活着但慢」的正常工作。

## 五、Q5【告警:症状 vs 原因,去噪】—— 权威实践 + 单机轻量落地

- Prometheus 官方 alerting 实践(引 Rob Ewaschuk 在 Google 的观察):"To summarize: keep alerting simple, alert on symptoms, have good consoles to allow pinpointing causes, and avoid having pages where there is nothing to do.""Aim to have as few alerts as possible, by alerting on symptoms that are associated with end-user pain rather than trying to catch every possible way that pain could be caused.""Only page on latency at one point in a stack. If a lower-level component is slower than it should be, but the overall user latency is fine, then there is no need to page." **批任务判据**:"For batch jobs it makes sense to page if the batch job has not succeeded recently enough, and this will cause user-visible problems. This should generally be at least enough time for 2 full runs of the batch job." 出处 https://www.prometheus.io/docs/practices/alerting/
- Alertmanager(官方机制,是个根因→一封的标准解法):"Grouping categorizes alerts of similar nature into a single notification. This is especially useful during larger outages when many systems fail at once and hundreds to thousands of alerts may be firing simultaneously.""Inhibition is a concept of suppressing notifications for certain alerts if certain other alerts are already firing... This prevents notifications for hundreds or thousands of firing alerts that are unrelated to the actual issue."(另有 dedup/silence)。出处 https://www.prometheus.io/docs/alerting/latest/alertmanager/
- 今晚一例(alertstorm 实测):1 个根因(21:00 backfill deploy R2 慢)→ 15 封 severe(schedule_monitor 症状×轮次)+ 1 封 280min 误报(登记表漂移 schedule_monitor.sh L90-92 vs 云上 timer)。标准解法=抑制依赖告警(latest.md 已有 dedup 21600s,但按「症状 key」去重,跨症状不聚合;缺「根因 key」聚合与抑制)。
- **单机 shell 监控的最轻落地形态(推断,基于上述官方机制)**:给 alert 加「root_cause 字段」+ 分组缓冲:同一 root_cause 首封即发,后续只更新 latest.md 不重发邮件(现 6h dedup 近似),不同 root_cause 分别发;fetch_news 连续 skip 类「自愈性/有兜底」降为 warning 批报(同业实践=azure 建议非关键操作 fail-fast 或低噪声记录,见 Azure Retry pattern)。

## 六、Q6【跨境上传 R2 社区经验(L47)】—— 有同源案例,有官方特性

- **CF 官方特性(2026-02-03 上线,open beta)→ 当前最对症的官方解法:R2 Local Uploads**:"With Local Uploads enabled, object data is automatically written to a storage location close to the client first, then asynchronously copied to where the bucket lives."官方基准:"we saw up to 75% reduction in Time to Last Byte (TTLB) when upload requests are made in a different region than the bucket."官方承认问题:"If the client and the bucket are in separate regions, more variability can be introduced... This could result in slower or less reliable uploads." 出处 https://blog.cloudflare.com/r2-local-uploads/ + https://developers.cloudflare.com/r2/buckets/local-uploads/。注意:文档有「读延迟」与「合规区域」限制(数据先落客户端附近,再异步复制到桶区;受 jurisdiction 限制桶不支持)。**本项目云上 VM 在华东、桶在 APAC → 正是官方声称 75% 收益的目标场景,目前似乎未启用(需主控/实施核实桶配置)。**
- **同源踩坑案例(症状与我们几乎一致,根因+修复全记录)**:
  - lsst-sqre/docverse#698(2026-09-24):30 分钟 6806 次 "Retrying presigned upload after transport error",全部 error_type=ConnectTimeout(connect budget 10s);并发≈90 时触发,**根因=Cloud NAT 端口耗尽(64 端口/VM,120s TIME_WAIT)+ 连接抖动(超过 max_keepalive_connections 后每次 PUT 重拨)**;单人重放(≤8 并发)0 超时 → "load-shaped, not a Cloudflare outage"(与我们判断一致);修复=①worker 级并发上限(keeper_sync_upload_concurrency=32)②连接全部 keep-alive ③NAT 端口 min_ports_per_vm=4096;验证:同 26 产品 10 并发项目 1240 jobs,0 ConnectTimeout。出处 https://github.com/lsst-sqre/docverse/issues/698
  - cloudflare/cf#73(2026-09-29,CF 自家 CLI):`cf r2 objects put` 264MB 文件 30s 后报 "timeout"(50MB 成功)——大文件单请求超时,与文件大小不匹配的超时,与本项目「600s 固定 socket 超时遇上大文件慢链路」同类。出处 https://github.com/cloudflare/cf/issues/73
  - wdl-dev/wdl#23(2026-09-30):给 R2/S3 操作"one 60-second S3 deadline spanning signing, transport, retry waits, response reads"——业界的新趋势是把「传输+重试等待」整体纳入一个预算,而非内层无限放大。出处 https://github.com/wdl-dev/wdl/pull/23
- **有没有共性、被反复验证的建议?** 有,三条反复出现:①**并发上限**(不是越大越快,NAT/连接都是有限资源,docverse 32 vs 90 实测)②**连接复用 / keep-alive**(跨境握手 ~1s/次,本项目 09-21 已在 verify-r2 与 09-22 主上传通道接 keep-alive,upload_r2.py L467-471/L837 已验)③**重试要便宜、有界、与外层总预算一致**(docverse 10s connect budget×6 次 / wdl 60s 总预算 / rclone 内层短+外层收敛;本项目 600s×5 + 900s kill 与三者都相反)。
- 我的推断(基于上述):跨境慢是「链路特性 + 连接抖动 + 并发」的合力,本地再调参只能缓解(项目已经做了 multipart/keepalive/错峰),结构性解法优先考虑 CF Local Uploads(配置级)+ 并发上限登记(一行配置)。

## 七、Q7【本项目适配:A 档最小可用集 vs B 档结构性方案】

### A 档「最小可用集」(单机 shell/systemd 架构内,无新组件) —— 逐条给改法/代价/风险/可回退

| # | 症状 | 改法 | 代价 | 风险/可能带出的新问题 | 可回退性 |
|---|---|---|---|---|---|
| A1 | 900s 看门狗杀正常工作 | run_r2_upload 判据改「停滞」:循环里加 `find $tmp_log -mmin +5` 判断输出卡住即 kill + TERM;总时长上限保留 7200s 只作硬兜底(不杀正常慢,只杀僵持) | 改 1 个函数(deploy.sh + r2_upload_async.sh 两份副本同步);需 upload_r2.py 保证「有进展必有输出」(需核对大文件单 PUT 600s 内无输出的情况——见 A2) | 真死锁(无输出)仍会被 7200s 兜底杀,不会无限挂;若某命令静默期>5min 属正常(如 multipart create 后长等待),会误杀——需把「最低输出频率」做成约定 | 高:回滚=恢复总时长判据一行 |
| A2 | 600s×5 重试放大 | R2_UPLOAD_HTTP_TIMEOUT 云上 600→120s 级(connect 短、read 放行),重试 5→3,multipart 已无单 PUT 大块(>100MB 走片 64MiB),单片耗时 << 超时 | 改 env 一处 + 重试上限常量;需复测大文件通道耗时分布 | 若链路高峰抖动>120s 读超时频率上升——可用重试+checkpoint兜;风险低于现状(现状=一次卡 600s×5=3000s) | 高:env 一键回退 |
| A3 | 全局锁耦合 | 拆 2-3 把锁:高频小通道(fetch_news/news_digest)独立锁;deploy 大通道保留原锁;跨锁总并发受控(登记上限) | with_lock.py 无需改,调用方换锁路径 + lock 名登记;fetch_news 改锁路径一行 | 若并发上限估计错,可能两链同时走同段拥塞链路(实际是同一链路,并发收益有限,主要是「不被别链阻塞」);需一次并发登记 | 高:切回原锁路径 |
| A4 | kill→marker→全量重传振荡 | marker 语义保留(fail-closed 不能丢),但把「全量重传」降为「从 checkpoint 续传 + 对账缺失」:读 .r2_<ch>_ckpt.json 续传,残余再全量 | 改 upload_r2.py marker 分支(一行条件,重试面=增量补缺) | checkpoint 若损坏→仍退化全量(fail-closed 不变);续传引入了「部分成功态」需 verify 兜底(已有 verify-r2 周日全量) | 中:改的是内部分支,回滚=marker 分支恢复 |
| A5 | 15 封 severe | 告警加「根因聚合」:同一根因(key=根因)首封发、后续只更新 latest.md;fetch_news 连续 skip 走 warning 批报;280min 误报=登记表同步 timer(必修,一行) | 改 schedule_monitor.sh 聚合段(小而集中)+ notify 支持 root_cause | 聚合过头=真缺口被吞——保留「缺口的失败通道」字段在首封内 | 高:聚合开关 |
| A6 | 跨境慢本身 | 启用 CF R2 Local Uploads 桶级配置(官方特性,配置级零代码)+ 并发登记 | 0 代码;需验证桶 jurisdiction 兼容;需观察 TTLB | 官方读延迟注意点:写后立读若在远端区可能读到旧(本项目静态 JSON 上传后立即 verify——需把 verify 放在复制完成后或接受短暂不一致;官方文档明示 data stays strongly consistent 且立即可读,复制期间两端可读——风险低) | 高:桶配置可关 |

### B 档「结构性方案」(若要做对,该长什么样)+ 是否过度设计判定

- **B1 发布队列 / 后台收敛循环(期望态)**:每通道「状态文件(md5 清单)→ 后台循环拉平 → 对账」,与任务生成完全解耦(生成方只写 local static-site;上传方=收敛器,与 rclone bisync 同构)。轻量实现=现有 async + A1-A4 的收敛化;重量实现(引入队列服务/DB/编排)=**对本规模过度设计**。
- **B2 度量先行**:先给每通道登记「字节吞吐/重试次数/锁等待时间/被 kill 次数」4 个指标(现有日志已能提取,加个统计段成本低),用一周数据再定 A1-A4 的参数(150KB/s 估算值 09-23 定过,现在链路变了需重标定)。**这是 B 档里成本最低、价值最高的一项,建议并入 A 档**。
- **B3 分域锁**(Bulkhead):见 Q3,2-3 域即可,17 锁=过度设计。
- **B4 告警聚合**:见 Q5。
- **过度设计明确清单(判断依据)**:K8s/编排/CRD(无多节点无扩缩,controller 租户收益=0);独立队列服务+Broker(mqtt/rabbit,单机 shell 级可用文件队列解决);per-file 级别锁(锁粒度=资源粒度即可)。

### 对主控当前四个补丁的评价
| 补丁 | 判定 | 依据 |
|---|---|---|
| ① async 主链有界化(r2_upload_async.sh) | **保留,但只是位移**——reviewer F2 已认定根因未修、900s 回退每周日可达;#174 挂着。必须由 A1-A2 承接,否则是「把病灶搬到后台 + 换一批告警」 | 本地代码 r2_upload_async.sh L52-97 与原 deploy.sh run_r2_upload 逐通道同值;alertstorm 实测主链 10055s→async 后主链不再等锁=真改善 |
| ② --on-skip 留痕 | **保留**(成本 1 行,防 F1 静默跳过) | rev2 实测三处留痕正确 |
| ③ 周日 timer 错峰 22:30 | **保留且必须**——配 09-21 方案;但必须同时修 schedule_monitor 登记表,否则每周日固定 280min 误报(今晚已发生) | alertstorm §一 |
| ④ 看门狗数值微调(900→更大 / #174) | **应被 A1 停滞判据替代**——加数值是给慢链路继续烧时间的打补丁;改判据是治本 | Q1① 全部工具语义 |

## 八、诚实标注
- **查到(有出处)**:Q1①③④、Q2(K8s/bisync)、Q3(Azure Bulkhead)、Q4(systemd/curl)、Q5(Prometheus/Alertmanager)、Q6(CF Local Uploads 官方+三个 GitHub 案例)全部有 URL。
- **只有二手/常识引用**:syncthing、git-annex 的机制描述(未抓其官方文档,仅概念引用,不构成结论依据);「Bulkhead 原始出处=Release It!」为业界共识(我未抓到 Nygard 原书文本,在线权威版=Azure Architecture Center)。
- **我的推断(无直接出处,已基于有出处原理)**:Q1④ 三件套整体命名;Q4 落地判据的具体参数(N=5min 对齐 rclone 默认);A 档各改法的具体实施形式;「分 2-3 把锁」的域划分(依据=Azure 粒度代价原则 + docverse 并发实测)。
- **未能验证**:本项目桶是否已启用 Local Uploads(需云上配置只读核实,本调研未查,列为待验证);600s 的实际占用分布(云上分批重试耗时未实测,基于代码最坏值推算);当前真实跨境吞吐与 150KB/s 估算差的漂移幅度(需度量先行)。
- **用户原质疑的回应**:主控方案确实有「打补丁」成分——四个补丁里只有①③是真问题方向,②是小保障,④(数值微调)是补丁;「结构性」的答案不是上编排,而是 A1-A4+A6(+B2 度量)。拆开讲:方向对(解耦/错峰/收敛),手段需要升级(停滞判据/分域/聚合/官方特性)。
