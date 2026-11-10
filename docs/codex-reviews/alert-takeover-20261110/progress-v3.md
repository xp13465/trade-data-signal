# 第三版收口：95be发布、精确恢复与#382兼容验收；历史/自然轮仍OPEN

本版完成本轮单次接管的文档收口，默认Codex只读外审角色不永久改变。v1/v2原文、固定审计、真实红与反例均保留；不把尚未全部根治改成全部正常。文档分支先快进ec307，后按父授权仅快进到已发布95be33a52edd1d29ba0a0588b9e20e153e618785，12个dirty材料先备份并逐字节核对保留，无冲突。#382为独立兼容缺陷，唯一实施状态在索引382；374仅D1原历史和观察。当前源代码、精确恢复、适用main三CI与真实纯GET证据齐，文档单commit交父，不push/merge main、不改业务源码、不重跑源码全量。完整960秒publish自然链、历史和其它未知项继续按边界观察。

## Claude恢复入口：ACTIVE checkpoint（未签收）

父已原子发布 **`alert-takeover-active-20261110-v1`**；报告 `active-takeover-checkpoint-v1.json` 的SHA-256为 `f0a5ee549c65f3f07e846f893f0b1a234961fadd948a8b82b4dc6c3152e8ffe1`，本次仅核该报告hash。父报告交接状态 **integrity verified / queued / ACK null**，并确认home同字节持久副本已有；**queued不等于Claude收到或复核**。

恢复时先读此ACTIVE入口，避免重复merge4d或并发修改当前docs工作区。终版将以新id supersede；本归档不改ACTIVE报告、不生成或伪造ACK、不复制13旧packet原文。[入口元数据](active-checkpoint-entry.json)仅保留上述定位和状态，报告request_id与发布packet_id分开记录。

## 已发布代码、CI 与 selfcheck 的区别

父已通过标准 `scripts/main-merge.sh` 合入 ec307，并确认云 CODE 同 SHA；本归档消费证据，没有执行部署。

| 证据 | 结果与边界 |
|---|---|
| `final-code-readiness.json` | 固定 ec307 **代码审查 PASS**，报告当时未解决 P0/P1/P2 均为0；返修中的 preupload 未知日期污染和 R2 锁事件镜像重复 P2 已解除。该报告生成时仍待最终 CI，不改其历史门禁字段；后验 #382 另记 |
| 最终 ec Linux run **42755379533** | 总数 **4243 = 4236通过 + 7跳过**，失败0、错误0。父提供同 SHA 完整结果；7e47 的旧4208总数/4201通过仍只属于旧 SHA |
| main Quality **42756830475** | ec307，completed/success |
| main Ops **42756830390** | ec307，completed/success |
| 自动 Worker **42756830500** | ec307，completed/success |
| Pages **42756830665** | ec307，completed/success |
| 本地全量替代 | 父显式设 `MAIN_MERGE_SKIP_PYTEST=1`，用**同 ec307 完整 Linux 回归**替代本地重复全量，其余门禁启用；没有把旧 SHA 绿移贴到最终 SHA |
| 标准 selfcheck | **480秒超时 WARN**，不是 PASS；父随后实际补核上述四个 main run 全成功。补核成功与 selfcheck 超时是两条事实 |

四个 main run 的原始快照为 `main-ec307-runs-latest.private.json`。归一化字段、源文件 hash 与生成器见本目录 v3 三件套；私有响应中的无关字段不复制入库。

## 原三个P2、R2回执和本机镜像

#379 的 preupload 返修 `684ec75d4e25925b2bacf9b82f3fb1a1349f2e17` 纠正“旧无日期纯成功污染后续可靠新 run”，作者定向129通过；历史/未知日期真错仍保留。#380 测试隔离修复与 #381 R2 显式结果回执、实际锁持有/释放观测、async 镜像和安全收口均已进入 ec307；正式代码审查及上述 CI/发布事实不因 v1/v2 当时的未完成状态而被抹掉。

**独立 cache 锁已被并发先后反证否决，最终保留 global 屏障**；不得写成“已实施拆锁”。镜像重复的后续 P2 由 `e995a5bd95df573103b956cc566f714fe5db3ef3` 解除，映射见 readiness。加入观测代码不等于已经确认过去长等待的实际持有者；#353/#354 的历史排队/失败清单和后续自然轮继续按证据判断。

`local-mirror-quarantine.json` 正式记录：**45条假条目隔离，50条真实 severe、29,777字节的受保护正文保持一致**。六份 before 备份均验证 SHA/0600；真实同一锁 inode 保留，头部及受保护字节相等。六份恢复控制均在 `/tmp` 复原精确 before、并验证当前字节漂移时拒绝恢复；没有在真实镜像上做恢复。发送账本、邮件/飞书原件与原审计 raw 镜像不改，不把本机隔离当作实际渠道重发或历史缺口恢复。

## Rawls正式执行与Turing独立postcheck

`recovery-execution.json` 已正式完成，`recovery-postcheck.json` 给 **PASS**。13:15–13:17 四个独立、有45秒上限的 mode 均业务/SSH exit0、`verified=true`、`commit_confirmed=true`，全部回执齐，无剩余 child/session。Turing 只核本地固定证据，**24/24 receipt hash一致**，没有新增云/源查询或数据库写入。

| mode | 实际恢复 | 保护与边界 |
|---|---|---|
| nav | 016989 Nov3–6 四日，unit_nav/acc_nav/nav_change_pct 共 **12个 NULL 格补值**；4行操作 | 窗口键集不变，原51个非空字段、prev_unit_nav/fund_name不变 |
| hs300 | Nov9 新增1行 | 只写精确白名单键 |
| csi500 | Nov9 新增1行 | 只写精确白名单键 |
| gem | Nov9 新增1行 | 只写精确白名单键 |

三指数总计3新行，旧15行逐字段不变；总业务行操作 **4+1+1+1=7**。freeze、进度/游标 hash（不存在项仍不存在）、锁文件 inode/内容控制保留。精确 cell/key before/after、脚本 SHA 和保护 hash 在 v3 JSON；原始 source/before/after/verified 回执留私有目录，manifest hash 保留，不把正文或远端命令复制进仓库。

**非目标基金正样本状态为 `UNKNOWN_NOT_SAMPLED`**：所取控样 before/after 都是0行，不能说“非空基金正样本验证不变”。整体无非目标写路径的依据是固定 SQL/参数限定4个既有 NAV 键及3个指数键、实际7行操作、目标表无 trigger，配合精确差异对账；不是全库扫描，也没有事后伪造 before。

这证明受控 **DB精确恢复**及窄 postcheck，不代表 public 页面、自然 export/重算/公开交付链已全部恢复。两 ETF `159501/159513` 的现有可信源仍只到 Nov6、Nov9 accum_nav为NULL；**ETF零写、OPEN待上游发布**，不以旧值/OHLC/当前映射造数。七个无可信T0的历史交易键和136历史冻结缺口未动。

## 正式runtime：对象恢复不等于投递机制最终PASS

`runtime-verification-result.json` 的只读实证：13:22:45–13:23:00，canonical 主/ext 在 ss/ssd **四URL由curl得到HTTP200、SHA与未变的源文件对一致**，当前对象已上线；真实业务风险仍 **74/red**，不降阈值关告警。

但正式 `_delivery_worker` 在 `scripts/overfit_monitor.py:2076–2090` 默认使用 urllib，请求没有自定义 UA 或 curl fallback。云部署 venv 等价请求的**四个原URL均HTTP403**；正式异常契约进入 `R2_PUBLIC_UNCONFIRMED`/exit76。本轮未执行完整 publisher/worker、未 PUT/purge/重生成，也未取得 publisher 写入 GO。首个探针的 stdout.reconfigure 异常发生于 HTTP 之前，属于探针执行失败，不算业务请求失败。

因此为该发现登记 **#382 `OVERFIT-SELFVERIFY-CLIENT403-P2`，独立兼容缺陷**，不重复使用 #381 的 purge 结果契约号。**当前实施状态只在 pending-index #382 一处维护**；#374保持D1原题义、历史和自然轮观察。原因差异仍 UNKNOWN，不猜为站点宕机、WAF 或凭证问题。修复范围为**有界、同URL、TLS与hash校验不降**。源码 ec307 已部署、对象已追平和旧 readiness PASS 均不代替新验 P2 的最终通过。

编号登记前核本地38分支/7种索引blob及现存worktree，最大381、未见382；父要求统一路由后再次核39分支/7种索引blob及全部worktree，只有本未提交草稿有382，无跨worktree或已提交ref占号冲突。后续合入仍须核并发占号。本次不自行修代码，不重复下载或扩大取证。

### 编号订正与#382固定插入位

父已确认先前把374当overfit是记错编号，撤销该母子路由；授权不能改变事实。本轮v3草稿、生成器和指定索引两行已纠正，v1/v2和#374原D1历史不改，不猜其它既有overfit号。作者原报告中的错误编号通过独立 [编号订正addendum](numbering-correction-addendum.json) 更正，原报告字节与代码commit保留，不为编号amend代码。旧错误路由私有记录不再作为v3生成输入。

作者提交 `e2e9095ef4bd8148f664c5ff1ec3e0e8a88aec2e` 已固定，`overfit-public-verifier-implementation.json` 记录 **156 passed in 6.43s**；旧版负控实际 worker 返回76而变异断言真红，作者交付时未push。这只是作者实施证据，不能写成独立审查、LinuxOps、发布或云验收PASS。

[独立#382证据插入位](overfit-382-closeout-slot.json)保留完整修复链：e2e909独立code PASS、0未解P0/P1/P2，25新测试+5CI相关+9独立fake通过；随后真实Linux42763898317仍失败（总4273/15失败/0错误/7跳过），旧code PASS不替代CI。首次报告时根因待证，后经缺certifi隔离15失败10通过复现为两CI pip清单漏依赖，见r2。该红head当时未合/未部署，main/云当时仍ec307。此前作者branch未匹配Ops命名过滤而未生成run，是另一件“未执行”事实，不用于淡化本次真实红；父仅将已有ops整合branch快进到同SHA触发CI，未扩大workflow或另造问题号。

正式r2固定95be33a52edd1d29ba0a0588b9e20e153e618785，仅补Ops/Quality各一pip安装行和2声明守卫，transport与e2e909同blob。作者原样158 passed in6.44s，原15实点转15通过；Hegel正式r2独立PASS、0未解P0/P1/P2，15实点+2guard绿、4删依赖/顺序负控真红，既有public_verifier_*.py订阅已覆盖新增guard。精确头完整Linux42765507696正式success：总4275=4268通过+7跳过、0失败/错误。父标准main-merge已push main/云CODE同95be并真正exit0，显式MAIN_MERGE_SKIP_PYTEST=1以同头完整Linux替代本地重复全量，其余门禁启用；第二次selfcheck Quality run#1065/42766606335是真success，与首次ec307的480s WARN分开保留。

生产依赖单点 `overfit-verifier-runtime-dependency-addendum.json` 已正式PASS：固定requirements的标准入口有 `akshare==1.18.64 -> requests -> certifi` 传递依赖链。本机distribution元数据证明依赖声明，不证明云实际版本相同；当前云可import是既有真实前证，本归档未新增云请求，也不拿CI绿冒称云依赖已核。无需扩第三处源码修或新增等待项，终版只等本次完整Linux、标准发布和真实纯GET。

纯GET验收封套的 `overfit-verifier-runtime-envelope-review.json` 已正式独审PASS，结论只绑定报告所列的两个脚本SHA；本归档仅登记SHA，不重新核脚本。实际 released main SHA须由父执行时固定；封套PASS不代表已经执行或云验收通过。两脚本hash与报告hash只补在#382插入位。r2报告提供transport同blob、封套未改，父确认既有封套review映射可复用；本归档不重核脚本，实际95be新函数现已取得正式只读PASS；最初LinuxOps42763898317的真实15失败仍按同一插入位保留，后续95be完整Linux成功及依赖声明返修另列，不抹掉原红。

**实际生产纯GET验收已正式PASS，#382兼容缺陷可关闭。** `overfit-verifier-production-readonly-result.json` 固定actual cloudHEAD95be，rawexit0、27.001秒、单次无retry，实际新函数 `_verify_overfit_public_pair -> _read_overfit_public` 对四个原`/data` URL均先urllib403，再由正常TLS curl200完成完整长度/SHA比对，全部等于未变源对。pair字节/inode/mtime/size断言前后不变，Nov9 21:40与74/red保持；报告before/after表示封套已断言的公共身份，未新增第二轮云采集。无PUT/purge/DB/artifact/source写、无完整publish，completion无child。

这只关闭客户端兼容P2，完整960秒publish自然链仍待观察，不把纯GET当完整publisher执行。GET-specific CODEhold父已解除；95be标准main-merge完成，main三条适用流程真实success；Worker本轮不适用，依据下节。本文档只做文档分支单commit，后续docs发布交父。

## 95be最终适用main流程：三条全绿，Worker不适用

`main-95be33-runs-latest.private.json`逐一固定相同95be SHA、completed/success：

| 流程 | 实际run |
|---|---|
| CI Quality Gate | 42766606335 |
| Operations monitoring checks | 42766606020 |
| GitHub Pages | 42766606019 |

Worker **NOT_APPLICABLE**，无需为该增量重新部署，也不造95be的Worker绿。现行 `deploy-cf.yml:7–16` 仅由main push命中 `static-site/**`、`worker/**`、`wrangler.jsonc`、`app/**`、该workflow自身，或手动触发；没有Quality完成触发事件。`ec307..95be`七个变更仅涉及两CI workflow和scripts/tests，零命中；上述Worker/入口/config及workflow blob完全不变。沿用ec307已成功Worker run42756830500及父12:58既有active-version证明，本次未重查或触发部署。精确变更与blob证明见 [Worker适用性](worker95-trigger-applicability.json)。

## #375最终r4与后续用户完整上下文（不回写历史）

只引用最终 `worker375-diagnostic-result-r4.json`：固定 `22a558a6ec884c16dd5eb800e3c3d58ea5df0bb8`、独立审PASS，实际诊断 run **42761618507 success**；该 run 是只读诊断，不是产品部署。

r4当时实际记录仅有 `error_type=MALFORMED_API_RESPONSE`、`wrangler_log_path_present=true`。`http_status/api_host/api_method/api_path/html_title` **在该报告中均为 NOT_RECORDED**；该截断上下文的历史结果不回写。

用户随后新增更完整的关键错误，独立落档 `worker375-user-evidence-addendum.json`：Wrangler **4.158.0** 对 `/accounts/{account}/workers/scripts/{script}/versions` 的 **POST返回504 Gateway Timeout**，HTML响应截断为6503字符，Ray `a57e01ddacc4a6ca-SEA`，进程exit1。由此可把旧症状定为**Cloudflare版本创建API网关504，HTML非JSON响应被Wrangler报告为malformed**。仓库仅保留归一化事实与hash，不复制完整HTML或真实账号/脚本标识。

这不证明Cloudflare内部哪一步超时、版本对象未创建、鉴权故障、所有旧失败均同因或永久根治。当前ec307自动Worker成功，内部根因/是否复发仍 **OPEN/观察**。不再追旧日志、不把机制brief当实际原因。临时诊断分支已push但不进产品main，不阻本轮产品代码。

`worker375-504-resilience-plan.json` 与父正式 `worker375-504-controller-decision.json` 已结稿，处置为 **DISPOSITION_COMPLETE_OBSERVE_PROVIDER**。父已按官方4.158.0版本POST源码与versions/deployments文档原文核验：版本创建POST原生最多**总3次**transient尝试，不能把此上限外推为整个job或deployments POST的相同重试。父裁定本轮**不叠外层retry、不改权限/secret**；原生耗尽后504真实FAIL/告警保留，避免重试放大与版本是否已创建的歧义。当前新main部署成功不承诺网关永不再故障。#375这部分已完成处置、观察态，**无需再等实施或审查**。

继续保留 OPEN：136历史冻结缺口/七历史键、#373原Nov1/2备份及Nov3权威来源、#374 D1自然轮及完整UTC周期、真实74/red模型风险、#353/#354长等待实际持有者与具体失败清单。历史项不拿当前快照/备份回造；局部DB恢复、curl对象追平或总链rc0不代替这些项销账。

父另已取消后续临时日志诊断，Harvey确认wt22a558a6干净、该新增任务无修改/commit/push/外发；这不回写旧r4诊断分支曾push的历史。#375无额外临时诊断等待项。

## 冻结审计私有持久化

原 `alert-recheck-20261110` 已归档至用户私有 `/Users/linhuichen/.local/share/trade-audit/20261110/alert-recheck-evidence.tar.gz`：**481文件，原始540,149,771B，压缩137,831,742B**；SHA-256 `d353dfb27eb70da0d5884db9988d38696804fa1a100ea88614291ead927b5d60`。逐成员完整读取 SHA/size 对账差异0，独立恢复器 verify-only再次481/481通过。目录0700，包/清单/报告/恢复脚本0600；原/tmp不删，不上传、不入git，不含运行中的 takeover 工作目录。

逐文件清单与可执行的有界恢复命令见同私有目录 `private-evidence-archive.json`，canonical副本位于 `/tmp/codex-reports/alert-takeover-20261110/private-evidence-archive.json`。仓库只留位置、计数、权限和hash，不复制原始邮件/飞书正文、私密群ID、凭证或tar包。

另有独立的固定 takeover 证据目录 `/Users/linhuichen/.local/share/trade-audit/20261110/takeover-evidence-v1`，`takeover-evidence-persistence-v1.json` 正式记录 **56文件/2,176,784字节**逐SHA/字节核验，目录0700、文件0600，含24份receipt及恢复/审查/主CI/发布日志/真实runtime/P2固定证据。它与旧481件压缩包分开；当前仍在进行的verifier后续及终版不在这56件内，父完成后再补，不把固定快照冒称最终材料全集。

`prior-handoff-status.private.json` 仅取聚合元数据：**13旧packet完整性verified、ACK全部null、状态仅context-emitted**。这不能称Claude已经收到或复核。最终master将统一覆盖本轮相关历史；不伪造ACK，不把13packet原文复制入仓库。

## 复现与本次提交门槛

[progress-v3.json](progress-v3.json) 为归一化本体，[generate_progress_v3.py](generate_progress_v3.py) 为生成器，本段为复现说明；输入文件名/字节/hash及恢复 manifest 见 [progress-v3-evidence.json](progress-v3-evidence.json)。默认私有输入目录为 `/tmp/codex-reports/alert-takeover-20261110/docs-source-snapshot/progress-v3-prepared/`。

```bash
python3 -c 'import subprocess; subprocess.run(["python3","-B","docs/codex-reviews/alert-takeover-20261110/generate_progress_v3.py","--check"], timeout=30, check=True)'
python3 -c 'import subprocess; subprocess.run(["python3","scripts/check_task_state.py","--skip-zombie-crons"], timeout=30, check=True)'
```

生成器逐个验证已冻结输入并按允许字段重建ec307基线；后续95be闭环证据在#382插入位及专用manifest，不重扫历史或重跑业务。Rawls/Turing/Boyle的业务验证与本归档文档校验分层。本次95be三条适用main流程实际成功，Worker不适用；提交后精确检查95be33..docsHEAD仅允许文档范围。若registry或其它文件冲突即报，不整文件覆盖。本分支不push/mainmerge，父后续标准docs-only发布。
