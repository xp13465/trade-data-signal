# 工作模式经验资产盘点:「通用版避坑手册」蒸馏事实依据(只读调研)

- 日期:2026-10-14 | 角色:researcher(只读;本报告为唯一新建产物,未改动任何既有文件、未 commit)
- 用途:为「把本项目积累的坑与经验蒸馏成通用版避坑手册、供其他项目参考」提供事实依据 + 候选清单
- 口径:所有数字为命令实测(见附录 A);条目引用给 锚点 id(L/E)/ memory 文件名 / docs 路径

## 〇、三处资产与盘点方法

| # | 资产 | 位置 | 规模(实测) |
|---|---|---|---|
| 1 | §18 防重犯索引表(滚动窗口) | `/Users/linhuichen/code/trade/CLAUDE.md` L127-161 | 表内 L36-L50(15 条)+ E21-E30(10 条)= 25 条 |
| 1b | 防重犯原文归档 | `/Users/linhuichen/code/trade/docs/archive/CLAUDE-errors-2026-08.md` | 200 行/66KB;锚点块 L01-L50(50 条)+ E01-E30(30 条)= 80 条;另含 5 段 token 浪费 + 08-08 每日归纳 13 条 + 多段"追加"叙事(含未编入 L 号的散条) |
| 2 | memory 经验库 | `/Users/linhuichen/.claude/projects/-Users-linhuichen-code-trade/memory/` | 245 条 memory(246 个 *.md 含索引);索引 MEMORY.md 147 行/230 链接;另有 `_archive-20260927/`(15 个归档文件)+ 4 个 `.bak-*` 历史备份 |
| 3 | 散落经验型文档 | `docs/*.md`(95)、`docs/ops/*.md`(426)、docs 递归 948 个 md | 标题关键词扫描候选 ≈ 50 个(清单见 §三 文档行) |

方法:①批量抽 memory frontmatter(name/description/type)一次看全 245 条(落 /tmp/workmode-memory-fm.txt);②archive 全文通读(200 行);③docs 标题关键词扫描(教训/经验/根因/防再犯/复盘/反思/沉淀/方法论/lesson/postmortem)筛候选;④逐条按 §二 判据定 通用/半通用/项目特定。

## 一、总量统计(含对账说明)

### 1.1 memory
- 文件数:245 条 memory + 1 索引 = 246 个 *.md;子目录 `_archive-20260927/` 15 个(归档区,不计入)。
- 索引:MEMORY.md 147 行、230 个链接;死链 0;孤儿 15(= 245 − 230)。
- **对账说明(对不上处)**:15 个孤儿为刻意设计——"甲类:已升格为 CLAUDE.md 正文/共享核心的指针型 memory"(如 version-feature-freeze-contract→§23.7、data-consistency-iron-rule→§22、reply-colloquial-chinese→§6、perf-opt-model-params-first→§5.2、optimization-core-preservation→§5.3、reduce-token-waste-behaviors→§5.5、production-stability-p0→§14、research-archive-immediately-categorize→§23.5、complex-table-explanation-style→§23.9、asset-version-cache-busting→§24、main-controller-no-edit→§0.1、tasks-state-log-unmanaged-gap、export-output-path-sync、appjs-em-dash-edit、self-growth-mechanism),与 `memory-orphan-audit-20260927.md`、`memory-weekly-review-20260927.md`("孤儿15=甲类设计")口径一致 → 非缺陷,无需补链。
- 类型分布(frontmatter `metadata.type`):feedback 138 / project 78 / reference 25 / user 1 / 无标准 frontmatter 3(`email-resend-switch`、`memory-orphan-audit-20260927`、`zcode-standin-handoff`,按实际内容归项目类)。总计 245。
- 规模口径:以 245 条为总数;3 条非标准 frontmatter 已单独标注,逐条盘点未漏。

### 1.2 §18 防重犯索引表 + 归档
- CLAUDE.md §18 表:`grep -c "^| L"` = 15、`grep -c "^| E"` = 10 → 25 条滚动窗口(L36-L50 + E21-E30)。
- 归档锚点:实测 `grep -c "^L[0-9]"` = **50**、`grep -c "^E[0-9]"` = **30** → 80 条。
- **对账说明**:archive 头部自述"L01-L49/49 条、零丢失校验 ==49"是 2026-08-12 归档时的旧口径;L43-L50 系 08-18 之后陆续追加,块内实为 50 条,以实测为准(旧等式锚已过时,建议日后更新或注明)。
- 归档另含:5 段 token 浪费(位于 L28/L53/L63/L76/L85 附近)、"2026-08-08 全天 13 条过错每日归纳"(L29-38)、多段追加叙事(如 08-08 量子科技第4层方案未落档、board_etf_map 三步遗漏、08-11 三条用户新规范)。

### 1.3 docs 经验型文档候选
- `docs/*.md` = 95 个;`docs/ops/*.md` = 426 个(盘点期间 425→426,该仓为活跃工作仓,±1 漂移属正常);docs 递归 = 948 个;`docs/archive/` = 83 个。
- `docs/ops` 标题关键词扫描命中 25 个(根因/复盘型);文件名另含 rootcause 类 17 个;实测根因/复盘候选合计 ≈ 29 个(去重后)。
- 候选文档总计 ≈ 50 个(散见 §三 各域"文档"行)。

## 二、通用性判据(可执行)

三分定义:
- **【通】通用**:脱开本仓语境(删掉项目名词)结论仍成立,换任何项目照样会踩。
- **【半】半通用**:骨架/方法论通用,例子是本项目的 → 抽象成占位符后可进通用版。
- **【项】项目特定**:只对本仓业务(交易/行情/站点)成立,通用版必须剔除。

**判据(机械可查;命中即倾向【项】;命中但结论骨架不依赖它 → 判【半】)**:
1. 域名/站点:`ss.fx8.store` / `sss.sugas.site` / `s.sugas.site` / `ssd.fx8.store` / `h.sugas.site` / sugas / fx8
2. 项目编号:形如 `#NNN`(#195/#196/#252 等)、`L##/E##`(本仓编号体系)、版本串 `a2xx`(v20260822-a377)
3. 库/表/数据产物名:`sentiment.db` / `etf_national_team.db` / `public_fund.db` / `stock_daily.db` / `daily_metric` / `board_etf_map` / `overview.json` / `concepts.json` / `signal_kelly_*` / `nav_bucket` / `index-all.json`
4. 业务信号词:凯利/kelly / 降亏 / toggle / AI宏 / NEW14 / S06 / 四档 / K档 / P档 / 象限 / ETF 评分 / 信号灯 / 备买 / 汪汪队 / 分时图 / 买卖点 / 情绪分
5. 项目脚本名:`deploy.sh` / `export.py` / `update_all.sh` / `main-merge.sh` / `check_signals.py` / `notify.py` / `gen_daily_brief.py` / `build_min.py` / `upload_r2.py`
6. 基础设施(**半通用标志**):R2 / Cloudflare Workers / systemd / launchd / 云上 122.51.111.173 / 飞书 / Resend / tdsignal.pem
7. Claude Code 平台机制(**半通用标志**,视目标读者是否用同类 agent 工具):worktree / subagent / hooks / memory / CLAUDE.md / skill / transcript / SendMessage / TaskStop / 内置 Explore
8. 具体日期+事故编号(2026-xx-xx #N)——只作来源标注,不进通用正文。

判定汇总(按本报告 §三 逐条标注统计,约数;含少量跨域重叠归属):§18/archive 80 条:通 37 / 半 40 / 项 3;memory 245 条:通 ≈87 / 半 ≈75 / 项 ≈83;docs 候选 ≈50:通骨架 ≈8 / 半 ≈32 / 项 ≈10。

## 三、分类盘点(全部条目按主题域)

> 标注:【通】通用 /【半】半通用(骨架通用,例是项目的)/【项】项目特定。
> 来源缩写:L##/E## = archive 锚点(docs/archive/CLAUDE-errors-2026-08.md);`mem:文件名` = memory 文件;`doc:路径` = docs 文档。

### A. 多 agent 协作与角色纪律(约 42 条)
- L01 通知丢失不设cron傻等(异步通知在架构上不可靠,兜底轮询是最优残余)【半】
- L06 cherry-pick 撞冲突+干扰后台 agent(切分支前先查后台任务)【半】
- L15 追加小改漏做(追加任务不靠异步消息通道,等 commit 后新派)【半】
- L21 reviewer 卡死无进度文件(prompt 必须要求每步 echo 进度文件)【半】
- L27 hooks 把子 agent 输入也当用户输入(项目级 hook 区分子会话)【半】
- L28 主控在 reviewer 前重复验代码(验收去重+角色分工)【半】
- L29 主控亲自 Edit 业务代码(角色红线:只调度不实施)【半】
- L33 子 agent 定时器自唤醒不可靠(带时点动作主控侧兜底)【半】
- L35 只读任务误用内置 Explore(白名单外模型绕道计费,计费泄漏)【半】
- L36 汇报在跑 agent 数错误(汇报前逐 agent 核对完成通知)【通】
- L43 主控抢跑亲手验证/数据生成(子 agent 卡住时派接手而非自己干)【半】
- E18 TaskCompleted hook(平台新通知机制,待验证)【半】
- E19 子 agent 中间层轮询不可行(先算模型回合数再定架构)【半】
- mem:agent-dispatch-verify-started 派单返回≠启动成功,须验转录增长【通】
- mem:agent-status-verify-before-report 只数真收到通知的【通】
- mem:agent-test-prod-write-guard 派集成测试前先查生产隔离钩子【通】
- mem:agent-silent-death-pgrep-unreliable 判死活用转录增长,不靠 pgrep【半】
- mem:agent-sandbox-blocks-compound-commands 破坏 .git 的操作会被拦成永久卡住【半】
- mem:agent-sendmessage-to-main-notify 无完美主动通知,兜底轮询是残余最优【半】
- mem:agent-zombie-parked-background-child 子 agent Bash>120s 转后台成僵尸停放【半】
- mem:concurrent-implementers-worktree-isolation 并发 agent 必须 worktree 隔离【半】
- mem:resume-agent-worktree-collision / resume-same-task-reuse-branch 续跑隔离与分支延续【半】
- mem:worktree-implementer-commit-verification / worktree-isolation-sendmessage-not-delivered【半】
- mem:dispatch-cron-backstop-rootcause 巡检兜底缺失根因=hook 未接线【半】
- mem:midflight-pivot-stop-old-agent 中途改口径=停旧派新,不续用旧 agent【通】
- mem:user-takeover-stop-inflight-agent 用户接管先停在场 agent【通】
- mem:small-fix-no-agent-shell 小修复不套 agent 壳(流程成本>收益)【通】
- mem:main-controller-dispatch-loop-discipline / main-controller-no-edit / main-controller-ran-verification-hands-on 主控只调度三条【半】
- mem:non-isolated-agent-switches-main-branch 非隔离 agent 会切走主仓分支【半】
- mem:no-explore-agent-use-researcher / poll-jsonl-use-stat-l / pre-remove-image-residuals-before-agent / subagent-sendmessage-rejection / subagent-timer-not-reliable 平台操作五条【半】
- mem:codex-worktree-isolation / codex-ref-channel-status-atomic / codex-review-mandatory-post-v116 / zcode-standin-handoff 外部协作者通道四条【半】
- doc:role-based-context-research.md 按角色分上下文(每角色只注入其规范)【半】
- doc:main-governance.md / doc:agent-quickstart.md 治理与速查【半】
- doc:parallel-cost-benefit-2026-08-18.md 多 agent 并行收益/成本量化【半】
- doc:docs/ops/agent-zombie-pattern-20261007.md 僵尸停放根因;doc:docs/ops/0.2-hook-timeout-3-20261007.md 派单机检【半】

### B. 通知与告警(约 18 条)
- L46 告警排查单通道盲区(事件驱动全量扫描;单一登记点沉默≠无告警;severe 统一镜像)【通】
- L48 通知类脚本自测打出真告警(自测前必须打桩+证沙箱生效)【通】
- L37/L38 非交易日补发/触发(定时与补发必带业务日历判断)【半】
- E17 0 token 抄送方案(hooks 层实时转发,不经过 LLM)【半】
- E20 外部消息 listener 自动落盘+回执(消除轮询噪音)【半】
- mem:alert-triage-event-driven-scan 事件驱动扫描(与 L46 同源)【通】
- mem:alert-dedup-mechanism 告警去重+恢复通知【通】
- mem:alert-denoise-keep-fault-discriminator 降噪必须保留真故障判别维度+反例实测【通】
- mem:notify-script-selftest-must-stub 能真发通知的脚本自测先打桩【通】
- mem:monitor-blindspot-exit0-syntax-error exit=0 不可信+时效阈值【通】
- mem:notify-instant-over-resource 通知即时性优先于资源【半】
- mem:mac-notify-debug 浏览器通知排查 4 要点【半】
- mem:feishu-hooks-zero-cost 0 成本抄送+子 agent 误触发坑【半】
- mem:backup-strategy-redundant-runs 多时点重复跑=兜底非冗余【通】
- mem:notify-mobile-panel-design【项】/ mem:email-resend-switch【项】
- doc:alert-design.md / doc:alert-perf-investigation-20260907.md / doc:feishu-aggregate-spam-rootcause-20260826.md / doc:72h-monitor-plan.md【半】
- doc:docs/ops/alert-night-triage-20261012.md(夜告警复盘)/ 182-feishu-heartbeat / 184-notify-dryrun-gate-impl【半】

### C. 测试·自测·验证(约 35 条)
- L05 agent 关键结论 §0 验(路径/文件数类)【半】
- L09 下结论前验数据产物层(新旧版字段值差异)【通】
- L17 §0 证伪前先确认实际读的文件(grep 渲染逻辑)【半】
- L19 前端重算必须逐字段对齐后端【半】
- L20 §0 grep 字面量漏常量(值可能被封装成常量)【通】
- L42 UI 三次修不好=假设整个错了(验证的验证+自验口径=用户感知口径)【通】
- L44 语义类改动全链第三方锚点(报告↔代码互证≠正确;多说法不一致必上报)【通】
- L49 假样本养绿(断言输入必须真实生产样本;守卫上线须生产实跑非空转)【通】
- L50 审查/测试探针绝不执行生产脚本(static-only+正白名单门控+事故独立取证)【通】
- E03 数据完整性校验+一致性审计脚本【通】;E07 reviewer FAIL 后 §0 验点合规【半】;E16 "该有的数据在不在"类校验【通】
- mem:benchmark-pathlist-representativeness 性能基准必须用生产真实清单【通】
- mem:ci-sim-reverify-dispatch-discipline 本地绿≠CI 绿;CI 触发范围要核实【通】
- mem:push-main-then-check-ci push 后自查 CI 结论,不等人发现【通】
- mem:gate-mount-decision-ci-only / gate-position-blast-radius / gate-self-blocking-staged-deletion / gate-verify-in-prod-tree-not-clean-worktree 守卫闸门四设计【通】
- mem:probe-harness-must-not-exec-prod-scripts【通】/ mechanism-scope-verify-in-code 作用范围读代码确认【通】
- mem:prod-fact-must-use-cloud-authoritative-db 生产事实用权威源,本地镜像会陈旧【通】
- mem:repro-script-second-implementation-drift 第二份实现必对账+页面实测锚点【通】
- mem:selftest-window-two-x-period 自验窗口≥机制周期2倍【通】
- mem:frontend-replay-align-backend【半】/ test-baseline-v112-anchor 测试基准锚点(骨架通用)【半】
- mem:verify-feature-live-not-code-in-main 验到功能生效层【通】/ verify-grep-constant-not-literal【通】/ verify-minjs-use-string-not-varname【半】
- mem:playwright-verify-facts-not-aesthetics 机械断言事实层不替代观感拍板【通】
- mem:refactor-delete-keep-callers-synced 删定义必查调用方【通】
- mem:regression-smoke-check 新功能不影响老功能三层验证【通】
- mem:resident-dashboard-memory-audit-method 常驻页面内存审计法【半】
- doc:smoke-checklist.md / test-suite-spec.md 回归清单骨架【半】
- doc:bug-pattern-site-audit-20260823.md 补丁式审计【半】;doc:pre-release-quality-flow.md 6 道关流程【通】;doc:lite-svg-corner-vertex-a320-final.md 从零验证案例【半】
- doc:docs/ops/1009-real-faults-rootcause-design / sw801030-universe-conflict / 0-verify-* 系列【半】

### D. git·分支·合并·发布(约 20 条)
- L34 报告索引有但本体未提交(报告四件套+提交前核 tracked)【通】
- L40 打 tag 只做点名处(版本链全量核对+疏漏上报)【通】
- E05 GH Actions deploy ~90s,验上线要等够【半】;E27 核心功能改动发中间版本+全站键集对齐【半】
- mem:conflict-never-silent 冲突/覆盖/倒退绝不静默【通】
- mem:git-three-dot-diff-false-novelty 判分支独有内容用 blob hash 比,别信三点 diff【通】
- mem:git-output-needs-quotepath-false 拿 git 输出当清单要 quotepath=false/-z【通】
- mem:git-add-a-large-file-incident 精准 add,禁 git add -A 误带大文件【通】
- mem:git-reflog-expire-all-kills-stash reflog expire --all 连带清 stash【通】
- mem:git-batch-delete-branches 批量删分支避 shell 展开误报【通】
- mem:force-push-avoid-new-ref 改已推 commit 用同串推新 ref,零 force【通】
- mem:merge-report-branch-carries-code 合报告分支前核只含文档【通】
- mem:main-merge-stale-local-ref-drop-commits merge 前 fetch 防本地 ref 过期静默丢【通】
- mem:main-merge-fail-leaves-half-merged-main merge 后 FAIL 留半完成态,汇报必须说清分支/commit 状态【半】
- mem:commit-timestamp-not-trigger commit 时间戳≠任务触发时点【通】
- mem:feat-branch-deploy-pushes-func-commits 定时 deploy 会把 feat 代码带上线【半】
- doc:conflict-overwrite-rootcause-2026-08-18.md + conflict-overwrite-triggers-2026-08-18.md 冲突覆盖频发根因+触发器【通骨架】

### E. 数据产物与一致性(约 22 条)
- L16 新数据类别上线链路三步(清单+定时+上传),列全依赖产物逐个确认【半】
- L45 状态型功能数据供给四件(生成→定时→机检→过期告警)缺一不算 done【半】
- E02 持有天数用交易日口径【半】;E14 同源字段语义(静态vs动态/快照vs增量)先确认【通】;E25 口径/基准切换先影响面审计(会反转/数值变化/自愈三类)【通】
- mem:data-consistency-iron-rule N 展示位必须统一,策略只决定更新时机【通】
- mem:atomic-write-data-artifacts 数据产物必须原子写(防半截 JSON)【通】
- mem:lazy-load-partial-cache-anti-pattern 部分缓存当全量返回是反模式【通】
- mem:export-output-path-sync 生成路径≠消费路径,须显式同步【半】
- mem:export-syspath-rootcause 读镜像非主库,DB 双写【半】
- mem:etf-index-map-source-switch-failure 依赖未生成文件=静默全空【半】
- mem:fetchjson-skip-gz 统一 .json+边缘压缩,绕缓存污染【半】
- mem:filter-count-vs-list-baseline 计数与列表基线分离【半】
- mem:s06-static-snapshot-missing-daily-regen 静态快照捷径=方向分叉必上报【半】
- mem:poscap-keptmap-key-not-ref 状态判断用 key 字符串非对象引用【半】
- mem:freeze-key-signal-type-drift 冻结键含类型,类型漂移致缺键【项】
- doc:docs/ops/trades-wipe-rootcause-20261014.md 历史行被重算抹除根治(历史行审计+source 标记)【半】
- doc:docs/ops/nextday-plan-empty-rootcause-20260924 / stale-navbucket-rootcause-20261013【半】
- doc:r2-track-score-consistency-audit-20260822.md / data-deploy-quickstart.md【半】

### F. 成本与 token(约 14 条)
- E29 token 优化 6 条零成本行为层(输出简洁/命令静默/派单只回结论/@文件直引/小任务不spawn/失败方向rewind)【通】
- E17(见 B)0 token 抄送【半】
- mem:reduce-token-waste-behaviors / cache-hit-rate-optimization / perf-opt-model-params-first【通】
- mem:persist-before-clear-compact 省 token 的 clear 以完整落档为前提【通】
- mem:compact-recovery-checklist【半】
- mem:claude-self-daily-backup【半】
- mem:deepseek-thinking-perrole-proxy / opencode-cache-think-findings 代理与缓存实测【半】
- doc:thinking-off-optimization.md 关 thinking 分角色(社区调研+实测 3.8x 提速)【通】
- doc:context-optimization-research.md / context-optimization-20260906.md【半】
- doc:docs/ops/v4-pro-leak-rootcause-20260815.md 模型计费泄漏根因【半】
- archive token 浪费 5 段(重复调研/试错返工/超时重派/追加漏做/轮询噪音)【通骨架】

### G. 派单·任务治理·调度时序(约 16 条)
- L31 派单基准过时(派单前核当前真值,不沿用旧报告)【通】
- L41 同步任务验收做窄(先拆完整构成;验收=该有的都有了+结构对齐)【通】
- E11 兜底槽按槽差异化(env 通道注入槽标识)【半】;E26 发现基准过时立即同步在跑 agent【通】
- mem:pending-index-drift-verify-before-recommend 索引会漂移,派单前核实物【通】
- mem:task-status-realtime-update / task-wrapup-summary-report 状态实时+收尾三块总结【通】
- mem:tasks-md-only-active / tasks-state-log-unmanaged-gap 任务 4 态治理与状态日志根因【半】
- mem:archive-dispatch-by-block-type 归档派单按块类型区分【半】
- mem:cronlist-loop-incident-prevention 状态查询死循环预防(查一次即终局)【半】
- doc:pending-features-index.md + tasks-*.md(5 个)任务治理文件族【半】

### H. 调研·结论纪律·防误判(约 28 条)
- L02 关键决策前复述理解确认【通】;L03 "全量"不擅自 exclude【通】;L04 断定前验证,记忆可能过时【通】
- L07 方案先调研再实施,不边试边改【通】
- L08 归属/分类前复述口径【通】;L11 不擅自扩展需求【通】
- L12 调研先对准用户可见的 UI 位置,再查生成层【通】
- L13 "无/0/不可改善"结论换方法/换数据源/多关联维度【通】
- L14 指定口径前验算典型值合理性【通】
- L23 期望值先核实来源【通】;L24 核心需求先拆解清单+复述【通】
- L26 判断"生效"先查运行证据【通】;L30 改口径先复述删除粒度+删前 git show【通】
- L32 收益率实操性判据=峰值持仓/本金倍数(≤20 倍)【半】
- L39 回测第一件事=确认基线落在当前基准,非基准口径必须显式声明【半】
- L47 外部系统/厂商/API 未知行为第一动作上网查社区+官方文档【通】
- mem:research-multi-channel【通】/ external-unknown-first-research-community【通】/ requirement-research-bias-verify-first【通】
- mem:divergence-triage-before-reporting 报"不一致"前先归因三查(别把刻意设计误报漂移)【通】
- mem:stats-caliber-vs-implementation-caliber 统计口径≠实施口径【通】
- mem:user-usage-memory-beats-my-inference 用户使用记忆优先于我的推断【通】
- mem:date-weekday-verify-first 日期/星期先核对日历【通】
- mem:has-track-caliber-p0-reflection 语义类全链第三方锚点(报告↔代码互证≠正确)【半】
- mem:open-source-eval-cross-role-sweep 评估开源/方法论必须跨角色穷举【通】
- mem:lite-svg-four-attempts-rootcause(亦见 I)三次修不好=停方向换人【通】
- doc:lab-out-of-sample-normalization-bias.md 样本外归一化偏置(回测陷阱)【半】
- doc:ab-refactor-bug-reflection.md 提速方案为何没预见 bug 的反思【半】
- researcher skill §3.2b 建模前四问(量化影响+别过度建模)【通】(规范,非文档)

### I. 前端·部署·缓存(约 35 条)
- L10 改灯/样式体系要遍历所有 return/分支(不只主路径)【通】
- L18/L25 算法/数值改动须同步全站公示文案(两处复发,已强化为 prompt 显式 grep 动作)【半】
- L42(亦见 C)UI 观感问题口径=用户视角【通】
- E01 批量 purge 分批避网关超时(批量操作按批+批间 sleep)【半】;E06 特殊字符行编辑失败用行号替换【半】;E09 定时轮询前端自愈 5 阶段(超时/去重/降频/心跳/前台清理)【半】
- mem:deploy-cdn-stale-snapshot-blue-screen 版本串=内容哈希+CDN 孤儿快照+SW 裸崩(全白事故根治)【半】
- mem:bump-sw-version-with-appjs / asset-version-cache-busting 改码同 bump【半】
- mem:build-min-dirty-worktree-rootfix 构建产物从 HEAD 读源,防脏工作区覆盖【通】
- mem:deploy-pull-main-touches-source-mtime 源 mtime 被 pull 刷新致误报【半】
- mem:edge-cache-ttl-stretch-no-cache / cf-workers-large-json-404-r2-fallback / cf-workers-static-assets-ignore-cache-control 边缘缓存行为三条【半】
- mem:min-verify-root-path / live-index-curl-307-use-browser-ua 线上验证路径与 UA 两坑【半】
- mem:curl-large-file-truncation-false-mismatch 大文件传输先比字节数再比 md5【通】
- mem:new-feature-isolated-tab-first 新功能先单开 tab 验证再融合【通】
- mem:ui-refactor-dispatch-blindspots 派 UI 改造必钉落点+浏览器实操验证【通】
- mem:ios-safe-area-fix / mobile-a11y-font-touch-live 移动端适配【半】
- mem:industry-all-cloudflare-25mb-split 大文件超平台限制按域拆分【项】
- doc:site-deployment.md / home-svg-fix-review.md / home-svg-fix2-review.md / home-svg-lite-fidelity-check.md / lite-svg-grad-calibration.md / lite-svg-grad-id-collision.md / rootcause-marquee-min-missing-20260819.md / cache-config-snapshot-design-20260919.md / intraday-self-heal-plan.md / industry-grid-lazy-20260822.md【半,均为「哈希断链/缓存/懒加载/自愈」案例】

### J. 删除与备份安全(约 10 条)
- §25 删除前必备份·可逆安全铁律(备份先于删除+实测可恢复+验过直接删/验不过停)【通】
- L30(亦见 H)删前 git show 原实现+删除/保留清单【通】
- mem:backup-before-delete-reversible【通】(§25 的 memory 版)
- mem:staticdata-old-mirror-keep-decision 有备份≠可以删,保留决定优先【通】
- mem:backup-architecture-4-layers 灾备分层(代码/差异日志/私有桶快照/公开分发)【半】
- mem:r2-large-json-backup-never-complete 灾备从未完整+key 按天翻滚【半】
- mem:kill-residual-verify-ppid-chain 清残留进程先核实 PPID 属主链【通】(亦 K)
- doc:backup-restore.md / restore-db.md / decommissioned-backups.md【半】
- doc:docs/ops/export-guard-implementation-20261003.md 防误传 7 层防护【半】;doc:docs/ops/237-r2-overwrite-backup-guard-design-20261009.md 覆盖前备份护栏【半】;doc:docs/ops/backup-pileup-rootcause-20260930.md 备份堆积根因【半】

### K. 生产运维·稳定性·平台环境(约 30 条)
- §14 生产稳定性 P0(定时任务时点/冲突检查/安全窗口)【半】
- L37/L38(亦见 B)【半】
- E11(亦见 G);E30 落地后定期巡检机制【通】
- mem:emergency-heal-respect-schedule-window 应急止血同样守时点窗口,不豁免【通】
- mem:local-dev-cloud-prod-split 本机开发/云上生产分离,判停摆去对的地方查【半】
- mem:production-stability-p0【半】
- mem:watchdog-inner-timeout-no-gradient 外层看门狗超时须>内层留梯度【通】
- mem:optimization-followup-inspection 优化落地后巡检【通】
- mem:cloud-ssh-full-readwrite-not-readonly 临时授权≠普遍约束(授权口径别写死)【半】
- mem:cloud-tracked-rewrite-blocks-pull / trade-data-code-dirs-are-symlinks(核验前 readlink -f 追真路径)【半】
- mem:unreleased-feature-isolation 未排定功能不得影响生产/污染生产数据【通】
- mem:r2-arch-by-category-not-size / r2-backup-bucket-second-account / r2-lifecycle-age-based-existing-objects【半】
- mem:mac-403-ipv6-direct-egress(403 查出口 IP)/ bash32-multibyte-var-swallow / magick-png-no-alpha-whiteedge / qrcode-in-framework-python 本机工具坑四条【半】
- mem:ssh-cloud-uses-tdsignal-pem【半】
- mem:r2-migration-complete【项】/ r2-upload-from-trade【项】/ weekend-no-trading-deploy【项】
- doc:docs/ops 根因族(实测 25 个标题命中+17 个 rootcause 名):task-slow-20260923(慢任务退化)/ 149-deploy-lock-queue-20261001(锁队列积压)/ 218-uploadchain / 219-verify-r2-backfill / 220-slowday / fapi-daily-oom / r2-export-guard-backup-timeout(串行备份超时死循环)/ stale-navbucket / watchdog-tradesim-slowkill(低速 kill)/ cloud-dual-tree-dataroot-audit / etf-hist-forcefull-stall / r2-slim-exit144 / kelly-intraday-rerun-exit5 / gapcheck-failed-unit-rc / local-state-audit-20260903 / update-all-20260817-88min-analysis【半,均为「看门狗/超时/锁/积压/资源」的工程案例】

### L. 数据源与外部依赖(约 15 条)
- L47(亦见 H)外部未知行为先查社区【通】
- E28 免费异源自动切换多重兜底(任一源必须有其他源兜底,fallback 不走同源)【通】
- mem:source-reliability-needs-stress-test 数据源可靠性需压测找边界【通】
- mem:data-source-switch-field-filter-blindspot 换源时"按字段值过滤"必静默失效,判据锚稳定标识【通】
- mem:index-backfill-multi-source / index-data-source-publish-time 多源补采与发布时点【半】
- mem:dns-hijack-hosts-rootfix DNS 劫持用 hosts 固定 IP 根治【通】
- mem:handle-api-errors-without-stalling 遇 API 错误别卡死重试,换方案【通】
- mem:batch-upload-arch-industry-refs 批量传输/调度架构业界权威参照(超时按停滞不按总耗时;retry storm 反模式)【通】
- mem:external-product-info-security 对外发布带主站入口,禁内部路径与密钥【通】
- mem:etf-index-map-source-switch-failure(亦见 E)【半】
- doc:data-sources.md / global-ticker-free-source-research.md / chart-p2p3-data-source-research.md【半】
- doc:docs/ops/data-source-outage-diagnosis-20260827.md(三线故障全链路诊断)/ baostock-socket-fix-review / turnover-backfill-stuck-rootcause【半】

### M. 回测·口径·数据科学方法论(约 25 条)
- L14(亦见 H)口径前验算典型值【通】;L32 实操性判据【半】;L39 基准口径声明【半】
- E02 交易日口径【半】;E10 决策树/子群挖掘(手写 CART+beam search+关联规则)【半】;E12 挖掘盲区=字段覆盖对比【半】;E13 新 toggle 评估用叠加边际【半】;E21 拆分调试视图+结果视图双视图【半】;E23 名义金额口径放大=虚假杠杆,先验边界(K=1 逐位相等)【半】;E24 最优组合依模式分裂,不一套配置打天下【半】;E25(亦见 E)口径切换影响面审计【通】
- mem:kelly-backtest-caliber-authority 基准=单一权威源+复刻必先复现锚点±0.1%【半】
- mem:kelly-return-caliber-peak-holding 收益率口径=峰值资金占用(权威口径单一)【半】
- mem:kelly-operability-20x-principal 峰值持仓/本金倍数≤20 可操作【半】
- mem:kelly-etf-freeze-lookahead 历史成交按成交日冻结(防前视)【半】
- mem:filter-backtest-position-fill-caliber 回测必须用可操作补位口径(与实盘链路一致)【半】
- mem:idle-position-is-valid-strategy 空仓也是正当策略【半】
- mem:sell-for-risk-control-not-trend 卖为降风险非趋势放弃【半】
- mem:param-opt-test-driven 参数优化测试驱动,多方案数据让用户选【通】
- mem:ability-first-then-score 先建能力再评分【通】
- mem:prediction-difficulty-over-hitrate 预测难度优先于命中率【半】
- mem:overfit-monitor-design 过拟合监控设计【半】
- mem:user-risk-preference-stability-first 用户宗旨=平稳优先【半】
- mem:kelly-loss-toggle-ratio-standard / kelly-ai-macro-431-must-visible / ghi-main-h-wins-both-dims / a-to-h-rollover-operable-541 / backtest-sell-price-source-residual / sim-loss-mining-combo-race-20260822【项】
- doc:docs/kelly/*、docs/market-state/*、docs/analysis/*(业务回测报告族)【项】

### N. LLM 平台与工具链操作(约 25 条)
- L22 curl 带认证头禁 -v/-i(token 泄漏)【通】
- L27(亦见 A)hooks 子 agent 场景【半】;L35(亦见 A)内置 agent 计费【半】
- E06(亦见 I);E17(亦见 B);E18(亦见 A);E20(亦见 B)
- mem:claude-code-output-config-effort-400 400 排查先 DUMP 请求体(新版本参数挪位)【半】
- mem:proxy-switch-not-by-proxied-agent 切代理不能派跑在代理链路上的 agent【半】
- mem:thinking-proxy-config-sop 代理配置 6 步 SOP+key 禁进 git【半】
- mem:sensenova-rpm-rate-limit / sensenova-linear-cool-cooldown-overkill 限流与冷却(按厂商实际恢复周期)【半】
- mem:openrouter-config-websearch-effort-keychain / deepseek-thinking-perrole-proxy / opencode-cache-think-findings【半】
- mem:outputstyle-not-applies-to-subagents 平台设置作用范围【半】
- mem:codex-openrouter-402-credit-check 402=服务端预检,客户端压不动【半】
- mem:codegraph-eval-conclusions 工具评估结论【半】
- mem:brain-repos-public-vs-vhua 知识仓分区【半】
- mem:curl-v-leaks-auth-token【通】(与 L22 同源)
- doc:k3-vs-v4flash-eval-20260905/ / claude-code-version-migration-20260906.md / kimi-k3-proxy-20260903.md / docs/sensenova/* / docs/codex-*【半】

### O. 沟通·工作方式·文档治理(约 25 条)
- §5.3 优化核心保障/§5.5 token 六条/§5.7 方案三件套/§6 中文口语化/§23.5 落档归类/§23.7 冻结契约/§23.9 三档互证/§23.12 任务 4 态【通】(均为活规范,已吸收为正文)
- E15 开源双仓分工(代码/数据分仓)【半】;E27(亦见 D)
- mem:reply-brief-and-colloquial / reply-colloquial-chinese 回复言简意赅+口语化【通】
- mem:decide-with-pros-cons-first 拍板前先说清优缺点(缺点优先)【通】
- mem:no-open-ended-questions-offer-options 不给开放性问题,必须给方案集【通】
- mem:proposal-default-criteria-no-compromise 方案默认准则不妥协【通】
- mem:persist-everything-by-default 任何事默认持久化【通】
- mem:self-growth-mechanism 每日过错总结自我成长机制【通】
- mem:complex-table-explanation-style 三档互证教学法【通】
- mem:research-archive-immediately-categorize 新产物当场落档【通】
- mem:version-feature-freeze-contract 已发布功能冻结契约【通】
- mem:weekly-review-sink-stable-rules 周 review 把稳定规范下沉【半】
- mem:memory-index-compression-20260927 / memory-orphan-audit-20260927 / memory-weekly-review-20260927 知识库索引维护三件【半】
- mem:skills-inventory-maintenance 规范与 skill 同步维护【半】
- mem:open-source-dual-repos【半】;mem:kanban-board-design【项】
- doc:claude-md-slim-audit-20260912.md / claude-md-slim-refactor-runbook-20260912.md / claude-md-slim-a1-5point4-plan.md 规范瘦身方法论【半】
- doc:session-review-20260906.md / explain-1to1-inventory.md / active-rules-archive.md【半】

### P. 项目业务特定(剔除,不逐条列)
- 约 83 条 memory:accuracy-monitor / ai-predict / amount-forecast / badge-t0 / daily-brief* / daily-metric / default-theme / etf-score-popup / etf-since-return / homepage-*(5)/ news-* / night-data / config-email / fund-nav / pf-* / public-fund / intraday-*(4)/ industry-* / rzhb / session-intraday-trade90 / sigkelly-batch2 / trade-sentiment-dashboard / trade-sim-chip / site-slogan / kanban / card-hover / list-candidates(半,归 O 亦可)/ kelly 业务子项(见 M)等
- archive:E04(卡间水印 UI)/ E08(intraday 走 R2)/ E22(并发实验引用)/ L37-L38 业务日历(已按半通用归 B/K)
- docs 业务族:docs/kelly、market-state、ai-predict、auto-trade、fapi、trade-sim、qvix-rv、uumit、lab、monitor、healthcheck 等子目录(≈190 个 md)

## 四、通用版避坑手册候选清单(终版)

> 组织原则:只收【通】与【半】;每题一句话结论 + 为什么通用 + 来源 id;【半】条目须把项目例子改成占位符(改写示例见本节末)。

### A. 多 agent 协作与角色纪律(14 条)
1. 派单返回≠启动成功:派发后必须验证 agent 真在跑(转录/进度文件在增长)才算派出。—— 任何异步并行 agent 系统都适用。来源:mem:agent-dispatch-verify-started
2. 汇报"在跑 N 个"前逐 agent 核对完成通知,不凭印象。—— 并行任务管理通用。来源:L36、mem:agent-status-verify-before-report
3. 判 agent 死活看转录是否持续增长;pgrep/进程名判死不可靠。—— 任何后台任务判活通用。来源:mem:agent-silent-death-pgrep-unreliable
4. 异步通知在架构上不可靠(会丢),必须配轮询/兜底巡检。—— 分布式/多进程协作通用。来源:L01、mem:agent-sendmessage-to-main-notify、mem:dispatch-cron-backstop-rootcause
5. 角色分离:调度者不亲手实施/验证;调度者派完即交还控制权。—— 管理者/执行者分离通用。来源:L29/L43、mem:main-controller-*
6. 小修复不套重流程(冷启动成本>收益),拿不准才升级流程。—— 通用工程权衡。来源:mem:small-fix-no-agent-shell
7. 中途改口径/方向=停旧派新,不让旧执行者带旧规格继续。—— 需求变更管理通用。来源:mem:midflight-pivot-stop-old-agent、L15
8. 用户接管任务时,第一件事停掉在跑的同任务执行者,不留撞车。—— 通用。来源:mem:user-takeover-stop-inflight-agent
9. 并发执行者改同一仓库必须工作树隔离(git 分支/HEAD 是全局的)。—— git worktree 级通用。来源:mem:concurrent-implementers-worktree-isolation
10. 续跑同一任务必须延续原分支,不新开分支 cherry-pick(防分支身份漂移)。—— git 工作流通用。来源:mem:resume-same-task-reuse-branch
11. 派单 prompt 必须要求"每步写进度文件",否则卡死无法被发现。—— 长任务监控通用。来源:L21
12. 子任务自设"等定时器自唤醒"不可靠(会话结束即失效),时点动作由调度方兜底。—— 通用。来源:L33、mem:subagent-timer-not-reliable
13. 破坏版本控制目录的操作会被工具层拦截并表现为"永久卡住",不要派执行者做这类注入测试。—— 通用(agent 沙箱)。来源:mem:agent-sandbox-blocks-compound-commands
14. 并行收益要量化(结算/协调成本随时间增长),不默认"人多快"。—— 通用。来源:doc:parallel-cost-benefit-2026-08-18.md

### B. 通知与告警(9 条)
1. 排查告警必须事件驱动全量扫描(按时间找新鲜日志逐个看),关键词 grep 只是补充。—— 通用运维。来源:L46、mem:alert-triage-event-driven-scan
2. 任何单一登记点的沉默≠无告警;多出口架构先盘点"这条链有几个出口"。—— 通用。来源:L46
3. 能真实外发通知的脚本(邮件/短信/群),自测前必须先打桩,并先证明沙箱判定生效。—— 通用安全纪律。来源:L48、mem:notify-script-selftest-must-stub
4. 告警降噪/降级的验收核心=保留"真故障 vs 良性缺失"判别维度,且必须用反例实测。—— 通用。来源:mem:alert-denoise-keep-fault-discriminator
5. 告警去重+恢复通知(持续异常不重发,恢复发解除)。—— 通用。来源:mem:alert-dedup-mechanism
6. 监控脚本 exit=0 不可信(子进程失败可能被吞),要有独立成功判据+时效阈值。—— 通用。来源:mem:monitor-blindspot-exit0-syntax-error
7. severe 级告警统一镜像登记,禁止旁路出口(防单点排查盲区)。—— 通用。来源:L46
8. 定时任务与补发必须带业务日历判断(非交易日/节假日不触发)。—— 通用(有业务日历的系统)。来源:L37/L38
9. 重复跑(多时点)是兜底不是冗余,任务幂等决定复写/跳过。—— 通用。来源:mem:backup-strategy-redundant-runs

### C. 测试·自测·验证(16 条)
1. 断言输入必须取真实生产实测样本,禁用人工构造样本(假样本养绿)。—— 通用测试。来源:L49
2. 新增"守卫/可见性"机制上线前必须在生产实跑确认真产生了输出(非空转)。—— 通用。来源:L49
3. 自验窗口必须≥被验机制周期的 2 倍,否则结论必然错。—— 通用。来源:mem:selftest-window-two-x-period
4. 复刻逻辑的脚本=第二份实现,漂移是必然;发布前必须同构对账+以真实页面/真实输出为锚点。—— 通用。来源:mem:repro-script-second-implementation-drift
5. "验证的验证":复用旧自验脚本前先核对脚本判定逻辑本身是否正确。—— 通用。来源:L42
6. 自验口径必须产出"用户描述的同一视角"的证据;拿不出=没修到用户看到的。—— 通用。来源:L42
7. 生产事实必须用权威源(本地副本/镜像会陈旧),证据必须标注取自哪一侧。—— 通用。来源:mem:prod-fact-must-use-cloud-authoritative-db
8. 性能基准必须用生产真实清单;同 N 不同样本可差 30 倍。—— 通用。来源:mem:benchmark-pathlist-representativeness
9. 本地绿≠CI 绿;跨环境测试必须核实 CI 的真实触发范围与依赖集。—— 通用。来源:mem:push-main-then-check-ci、mem:ci-sim-reverify-dispatch-discipline
10. 守卫闸门设计四则:位置决定爆炸半径/必须在生产目录验证/变更集判定要排除"已暂存删除"(防自锁)/挂载点要核实真的在跑。—— 通用。来源:mem:gate-*
11. 对生产做审查/验证的探针一律只读,绝不执行生产脚本;门控用正白名单,禁用"环境变量齐不齐"这类可被真实形态绕过的条件。—— 通用。来源:L50
12. 事故后必须独立取证,不采信事故方自述;判不了就写"无法判定"。—— 通用。来源:L50
13. 语义类改动的验收必须有第三方锚点(文案/产品文档),警惕"实现↔报告"互证闭环(一致≠正确)。—— 通用。来源:L44
14. 改/删函数定义必须同步调用方(删 def 忘删调用=静默失败)。—— 通用。来源:mem:refactor-delete-keep-callers-synced
15. 新功能上线必须跑回归(老功能)+数据校验;大阶段必行回归。—— 通用。来源:mem:regression-smoke-check
16. 判"某机制会不会影响 X"必须读代码确认调用链,不从命名/直觉推断。—— 通用。来源:mem:mechanism-scope-verify-in-code

### D. git·分支·合并·发布(12 条)
1. 冲突/覆盖/版本倒退绝不静默——宁可卡住上报,也不能吞掉后变大 bug。—— 通用最高原则。来源:§23.11、mem:conflict-never-silent
2. 判"分支独有内容/main 是否已有"用 blob hash 逐位比,别信三点 diff(有假新增)。—— 通用。来源:mem:git-three-dot-diff-false-novelty
3. 拿 git 输出当文件清单给程序解析,必须 quotepath=false 或 -z(中文名会被静默漏扫)。—— 通用。来源:mem:git-output-needs-quotepath-false
4. 精准 add,禁 git add -A(误带大文件 push 被拒)。—— 通用。来源:mem:git-add-a-large-file-incident
5. 跑 reflog expire/gc 前先检查 stash("不删任何 ref"声明会失真)。—— 通用。来源:mem:git-reflog-expire-all-kills-stash
6. 改已推送 commit 需要 force 时,把同串推到新 ref 名即可(零 force)。—— 通用技巧。来源:mem:force-push-avoid-new-ref
7. 合"报告/审查分支"前必须核 diff 只含文档(分支自带代码 commit 会被一起带入)。—— 通用。来源:mem:merge-report-branch-carries-code
8. merge 前先 fetch 核实本地 ref 新鲜(过期 ref 会静默丢 commit)。—— 通用。来源:mem:main-merge-stale-local-ref-drop-commits
9. merge 流程在中途失败会留"半完成态",汇报现状必须说清每个改动在哪个分支/commit。—— 通用。来源:mem:main-merge-fail-leaves-half-merged-main
10. 打 tag/发版本第一件事=全量核对版本链,历史疏漏必须上报不默默补。—— 通用。来源:L40
11. 报告类交付=四件套(本体+生成脚本+复现段+提交),提交前核本体真的 tracked。—— 通用。来源:L34
12. 提交时间戳≠任务触发时点,判断任务是否跑要看运行日志。—— 通用。来源:mem:commit-timestamp-not-trigger

### E. 数据产物与一致性(10 条)
1. N 个展示位的数据必须统一:策略只决定何时更新/如何排序,一旦更新必须 N 文件+N 缓存同步。—— 通用(多端/多缓存)。来源:§22、mem:data-consistency-iron-rule
2. 数据产物必须原子写(临时文件+rename),防进程被杀留半截 JSON。—— 通用。来源:mem:atomic-write-data-artifacts
3. 生成路径≠消费路径是经典静默陷阱,产物改动必须列全依赖清单逐个确认"重跑+同步+上传"。—— 通用。来源:L16、mem:export-output-path-sync
4. 部分缓存当全量返回是反模式(懒加载优化最容易踩)。—— 通用。来源:mem:lazy-load-partial-cache-anti-pattern
5. 同源字段先确认语义(静态 vs 动态 / 快照 vs 增量),矛盾先查字段选错。—— 通用。来源:E14
6. 依赖"上游已生成文件"的代码在文件缺失时会静默全空,必须有存在性校验。—— 通用。来源:mem:etf-index-map-source-switch-failure
7. 状态型/动态功能的数据供给=四件套(生成→定时→机检→过期告警),缺一不算完成;静态快照这类降级形态必须作为方向分叉上报。—— 通用。来源:L45、mem:s06-static-snapshot-missing-daily-regen
8. 口径/基准切换前先做影响面审计(会反转/数值变化/自愈三类),并行修根因。—— 通用。来源:E25
9. 状态判断用稳定 key 而非对象引用(引用在重建后失效)。—— 通用前端/后端。来源:mem:poscap-keptmap-key-not-ref
10. 计数与列表可以用不同基线(计数宽松、列表完整),两者分开设计。—— 通用 UI。来源:mem:filter-count-vs-list-baseline

### F. 成本与 token(8 条)
1. token 优化 6 条零成本行为层:答案优先/命令静默/汇报只回结论/@文件直引/小任务不套重流程/失败方向回退不压缩。—— 通用(LLM 工作流)。来源:E29、mem:reduce-token-waste-behaviors
2. 遇"慢/贵"先查模型参数层(thinking/模型档/token 缓存),再查任务层。—— 通用。来源:§5.2、doc:thinking-off-optimization.md
3. 缓存命中率优化:同主题续跑不新开会话/派单只给差异信息/一批独立任务并行启动;换模型/档位=全缓存失效。—— 通用。来源:mem:cache-hit-rate-optimization
4. clear/compact 省 token 必须以"完整落档"为前提,否则丢状态得不偿失。—— 通用。来源:mem:persist-before-clear-compact
5. 重复调研与试错返工是最大浪费;"不可改善"类结论一次查到位(换方法/数据源/多维度)。—— 通用。来源:archive token 浪费段、L13
6. 大文件/重复内容走外部通道(脚本层处理),不经模型回合=0 token。—— 通用。来源:E17
7. 模型计费异常要主动审计(白名单外模型/绕道调用会造成泄漏)。—— 通用(多模型平台)。来源:L35
8. 上下文加载分层(按需读,不全量注入),别让每轮都重发全历史。—— 通用。来源:doc:context-optimization-research.md

### G. 派单·任务治理·调度时序(8 条)
1. 派单必带定位锚点(文件:行号/符号),不让执行者从第一行搜大文件。—— 通用。来源:§8.1
2. 派单前先核"基准/默认值"的当前真值,不沿用旧报告/旧索引。—— 通用。来源:L31、mem:pending-index-drift-verify-before-recommend
3. 索引/清单会漂移(已完成未销号),按它办事前先核实物。—— 通用。来源:mem:pending-index-drift-verify-before-recommend
4. 任务状态实时更新(不等收尾);收尾=三块总结(改了什么/效果/下一步)+落档+进提交信息。—— 通用。来源:mem:task-status-realtime-update、mem:task-wrapup-summary-report
5. 任务治理 4 态流转(活跃/远期/完成/归档)+状态单一事实源+机检兜底。—— 通用(项目管理)。来源:§23.12、mem:tasks-*
6. 定时任务要管时点冲突:派任务/设定时前先查现有任务清单,避开彼此窗口。—— 通用。来源:§14、mem:production-stability-p0
7. 应急止血同样守时点窗口,不豁免;确需例外先拍板+事后留痕。—— 通用。来源:mem:emergency-heal-respect-schedule-window
8. 看门狗外层超时必须>内层,否则误伤内层重试(exit=124 根因)。—— 通用。来源:mem:watchdog-inner-timeout-no-gradient

### H. 调研·结论纪律·防误判(16 条)
1. 调研先对准用户实际看到的位置(先查展示层,再查生成层)。—— 通用。来源:L12
2. 下"没铺到/无数据/老逻辑"类结论前,必须验证数据产物层(新旧版本字段值对照),不只看代码分支。—— 通用。来源:L09
3. "无/0/不可改善"类结论必须换方法/换数据源/多关联维度验证后再下;报告里列"已验证了哪些方法"。—— 通用。来源:L13
4. 归属/分类/口径类决策前先复述口径让人确认,不靠语义猜测。—— 通用。来源:L02/L08/L11
5. 指定计算口径前先验算典型值合理性(异常值如年化>100% 立即警觉)。—— 通用。来源:L14
6. 外部系统/厂商/网关/API 的未知行为,第一动作上网查社区+官方文档,不闭门实验。—— 通用。来源:L47、mem:external-unknown-first-research-community
7. 凭记忆(笔记/文档)断定前先验证——记录可能过时。—— 通用。来源:L04
8. 判断"功能是否生效"看运行证据(日志/指纹/实际输出),不凭配置推断。—— 通用。来源:L26
9. 验收"值"类结论时 grep 字面量无果,先怀疑值被封装成常量/变量/env,改查符号名。—— 通用。来源:L20
10. 报"A 与 B 不一致"前先归因三查(谁在生效/是否历史遗留/是否刻意设计),别把刻意设计误报成漂移。—— 通用。来源:mem:divergence-triage-before-reporting
11. 需求理解:先复述确认、不擅自扩展、叫停功能时复述"删到什么粒度";不擅自把"全量"需求做裁剪。—— 通用。来源:L02/L03/L11/L24/L30
12. 期望值/断言值先核实来源,不盲信任务描述里的数字。—— 通用。来源:L23
13. 用户给出的"使用记忆/体验"与你的推断冲突时,先通读实现全路径再下结论,用户记忆优先。—— 通用。来源:mem:user-usage-memory-beats-my-inference
14. 日期/星期/交易日必须先核对日历——强时序依赖系统里日期错会全错。—— 通用。来源:mem:date-weekday-verify-first
15. 统计口径≠实施口径:调研数字不能直接当实施规格抄,派单必须钉"与现状数值一致"验证约束。—— 通用。来源:mem:stats-caliber-vs-implementation-caliber
16. 评估开源项目/方法论必须跨角色穷举(对每个使用角色逐个问"有什么增量")才下结论。—— 通用。来源:mem:open-source-eval-cross-role-sweep

### I. 前端·部署·缓存(11 条)
1. 前端静态资源版本串=内容哈希;部署后必须校验"线上文件内容哈希==页面引用版本串"。—— 通用(SPA/CDN)。来源:§24、mem:deploy-cdn-stale-snapshot-blue-screen
2. Service Worker 更新接管必须"壳芯配套+失败回退",改资源必须同步 bump 缓存版本。—— 通用 PWA。来源:§24
3. 构建产物必须从版本库 HEAD 读源(脏工作区会覆盖正确产物)。—— 通用。来源:mem:build-min-dirty-worktree-rootfix
4. 大文件下载校验先比字节数再比哈希(curl 走慢 CDN 会静默截断致误报)。—— 通用。来源:mem:curl-large-file-truncation-false-mismatch
5. 验证线上资源要确认真实路径与访问条件(根路径 vs 前缀、UA 门槛、307)。—— 通用。来源:mem:min-verify-root-path、mem:live-index-curl-307-use-browser-ua
6. "功能 done"三查:代码进主线+数据层生效+前端展示层上线,缺一不可。—— 通用。来源:§8、mem:verify-feature-live-not-code-in-main
7. 压缩产物(min)验证用字符串字面量(class 名/中文),不用变量名(会被混淆重命名)。—— 通用。来源:mem:verify-minjs-use-string-not-varname
8. UI 视觉问题"多次修不好"=假设整个错了:停方向、从零验证、换独立验证者,主控不转达"修好"直到用户确认。—— 通用。来源:L42、mem:lite-svg-four-attempts-rootcause
9. 派 UI 改造必须钉 UI 落点+旧控件替代清单+真实浏览器实操验证(代码层验证不保交互层)。—— 通用。来源:mem:ui-refactor-dispatch-blindspots
10. 新功能先隔离验证(单开环境/tab)再融合。—— 通用。来源:mem:new-feature-isolated-tab-first
11. 算法/数值改动必须同步全部对外说明文案(同一数值全站所有出现处一起改)。—— 通用。来源:§21、L18/L25

### J. 删除与备份安全(6 条)
1. 删除前必备份:备份先于删除、实测可恢复、验过直接删/验不过停;恢复路径必须写得出。—— 通用最高安全准则。来源:§25、mem:backup-before-delete-reversible
2. 有备份≠可以删:既有保留决定优先,别把"保险"当垃圾清。—— 通用。来源:mem:staticdata-old-mirror-keep-decision
3. 删除/重构前先看原实现,列"删除清单+保留清单"逐项确认。—— 通用。来源:L30
4. 杀进程前核实进程属主链(按名字匹配会误杀同名生产进程)。—— 通用。来源:mem:kill-residual-verify-ppid-chain
5. 跨天翻滚的备份 key/无覆盖参数的灾备=形同虚设,必须验证"能重建完整快照"。—— 通用。来源:mem:r2-large-json-backup-never-complete
6. 覆盖写入前先备份护栏;防误操作要多层防线(闸门/路径白名单/审计)。—— 通用。来源:doc:docs/ops/237-r2-overwrite-backup-guard-design-20261009.md、doc:docs/ops/export-guard-implementation-20261003.md

### K. 生产运维·稳定性·平台环境(12 条)
1. 生产稳定性优先级最高:任务上生产前先查定时任务清单/时点窗口。—— 通用。来源:§14
2. 优化/修复落地后要设定期巡检(指标+判定标准+严重止损回滚),防负向漂移。—— 通用。来源:E30、mem:optimization-followup-inspection
3. "该有的数据在不在"类完整性校验(防静默缺失)。—— 通用。来源:E16
4. 开发与生产环境分离;判断任务停摆要去"真正跑任务的那台机器"查。—— 通用。来源:mem:local-dev-cloud-prod-split
5. 未排定上线的功能必须与生产隔离(不写生产数据/不影响线上)。—— 通用。来源:mem:unreleased-feature-isolation
6. 慢任务排查:逐段计时找"越来越慢"的真因(锁/积压/资源),不归咎"网络慢"。—— 通用。来源:doc:docs/ops/task-slow-rootcause-20260923.md
7. 锁队列积压、串行备份超时、看门狗低速 kill 这三类案例=超时设计必须按停滞(而非总耗时)判、并给梯度。—— 通用。来源:mem:batch-upload-arch-industry-refs、doc:docs/ops/149/218/220 系列
8. 环境临时授权≠普遍约束;别把某轮动作的临时限制写死成规范。—— 通用。来源:mem:cloud-ssh-full-readwrite-not-readonly、mem:divergence-triage-before-reporting
9. 双树/符号链接目录:核验前先追真实路径(readlink -f),否则核验的是镜像。—— 通用。来源:mem:trade-data-code-dirs-are-symlinks
10. 本机工具坑要记录(mac bash 3.2 多字节变量吞噬、图像工具 alpha 通道、库不在 venv)。—— 通用(平台)。来源:mem:bash32-multibyte-var-swallow 等
11. 云上/服务器上被定时任务重写的 tracked 文件会挡住 git pull,处置要赶在下次定时前。—— 通用。来源:mem:cloud-tracked-rewrite-blocks-pull
12. 对象存储生命周期按"对象自身年龄"算,存量对象同样受管。—— 通用(对象存储)。来源:mem:r2-lifecycle-age-based-existing-objects

### L. 数据源与外部依赖(7 条)
1. 数据源可靠性必须压测找边界;多源互备,fallback 不走同源。—— 通用。来源:E28、mem:source-reliability-needs-stress-test
2. 换/加/降级数据源时,"按字段值过滤"的判据会静默失效——判据必须锚在稳定标识(ID 规则/代码前缀)。—— 通用。来源:mem:data-source-switch-field-filter-blindspot
3. 外部 API 报 400/不支持错误别卡死重试,立即换方案或暂存任务。—— 通用。来源:mem:handle-api-errors-without-stalling
4. 批量传输/调度架构有业界权威参照:超时按停滞不按总耗时;retry storm 是具名反模式。—— 通用。来源:mem:batch-upload-arch-industry-refs
5. DNS 劫持类问题用 hosts 固定 IP 根治(前提:先确认是 DNS 层还是连接层)。—— 通用。来源:mem:dns-hijack-hosts-rootfix
6. 对外发布内容:主动带主站入口,禁内部路径与密钥。—— 通用。来源:mem:external-product-info-security
7. 限流冷却时间要按厂商实际恢复周期定,固定大冷却会锁死可用凭据。—— 通用。来源:mem:sensenova-linear-cool-cooldown-overkill

### M. 回测·口径·数据科学方法论(10 条)
1. 基准锚点:一切回测/测试默认前提=当前基准;测非基准口径必须显式声明+说明原因。—— 通用(数据科学)。来源:§5.4、mem:test-baseline-v112-anchor
2. 防前视:任何择时/状态信号在 t 只能用 t 之前的数据;分位数阈值必须 expanding/滚动窗口;做时点穿越测试。—— 通用(时序建模)。来源:§5.1⑥、mem:kelly-etf-freeze-lookahead
3. 口径真实性:名义金额×笔数的口径会放大收益(虚假杠杆);先验边界情形(K=1 逐位相等)。—— 通用。来源:E23
4. 收益率实操性判据=峰值资金占用/单次本金倍数(倍数过大=理论不可操作)。—— 通用。来源:L32、mem:kelly-operability-20x-principal
5. 回测必须用可操作补位口径(与实盘执行链路一致),删笔口径只作对照。—— 通用。来源:mem:filter-backtest-position-fill-caliber
6. 多因子/多开关:新候选必须算"叠加现有配置的边际贡献",不被 standalone 指标误导;最优组合可能依场景分裂。—— 通用。来源:E13、E24
7. 多轮数据挖掘前先核对字段覆盖:未覆盖字段=最大机会(盲区发现法)。—— 通用。来源:E12
8. 先建能力再评分:先做出来,再看是否过拟合/稳定。—— 通用(研发心态)。来源:mem:ability-first-then-score
9. 参数优化走测试驱动:多方案+数据报告让人选,不问"怎么定"。—— 通用。来源:mem:param-opt-test-driven
10. 宏观/回测报告要一次给全维度(基线/按年/稳定性/回撤/极端窗口/参数变体/诚实标注),不等人点名补。—— 通用(报告规范)。来源:§5.1⑤

### N. LLM 平台与工具链操作(8 条)
1. 凭据安全:带认证头的调试命令禁用 -v/-i;token 从环境读、不硬编码、不 echo;泄漏立即吊销。—— 通用。来源:L22、mem:curl-v-leaks-auth-token
2. API 参数报错(400)先抓原始请求体对照文档/官方 issue,再改;新版本 SDK 会把参数挪位置。—— 通用。来源:mem:claude-code-output-config-effort-400
3. 切换代理/网关配置不能由"跑在该链路上的会话"执行(自己会死),先给方案确认再一次性做对。—— 通用。来源:mem:proxy-switch-not-by-proxied-agent
4. 密钥永不进版本库(会被平台密钥扫描拦截)。—— 通用。来源:mem:thinking-proxy-config-sop
5. 平台设置(输出风格等)不一定作用于子会话,要按实际作用范围设计。—— 通用(agent 平台)。来源:mem:outputstyle-not-applies-to-subagents
6. 供应商 402/余额类错误=服务端预检,客户端压不动,解=充值或换模型。—— 通用。来源:mem:codex-openrouter-402-credit-check
7. 外部协作者(第二个 AI/人)共用 git 仓库也要隔离工作区+状态字段+原子写入。—— 通用。来源:mem:codex-worktree-isolation、mem:codex-ref-channel-status-atomic
8. 工具评估要走"实测+落档结论"(别凭宣传),并注明已知坑与适用边界。—— 通用。来源:mem:codegraph-eval-conclusions

### O. 沟通·工作方式·文档治理(11 条)
1. 面向用户输出:言简意赅+口语化,不堆细节不刷屏。—— 通用。来源:§6、mem:reply-brief-and-colloquial
2. 要人拍板前先说清优缺点(缺点/风险优先),不问"要不要",给 2-4 个具体方案+建议。—— 通用。来源:mem:decide-with-pros-cons-first、mem:no-open-ended-questions-offer-options
3. 方案=可证伪的承诺:可修正依据+可观测预期+证据用例,三件齐;写不出=建议不是方案。—— 通用。来源:§5.7
4. 方案默认准则:尽可能完整正确、一步到位、不因工作量大偷懒。—— 通用。来源:mem:proposal-default-criteria-no-compromise
5. 任何事默认持久化(定时任务 durable/进度落盘/状态写档),会话与记忆都不可靠。—— 通用。来源:mem:persist-everything-by-default
6. 新产物当场落档+归类一次到位+索引同步;报告四件套缺一不可。—— 通用。来源:§23.5、mem:research-archive-immediately-categorize
7. 已发布功能=冻结资产,默认只新增不改旧;动旧功能必须确认。—— 通用(产品纪律)。来源:§23.7、mem:version-feature-freeze-contract
8. 规则文档要防膨胀:定期 review 把稳定条款下沉、根文件留摘要;精简=保核心+可逆+复查。—— 通用。来源:§5.3、mem:weekly-review-sink-stable-rules、doc:claude-md-slim-*
9. 知识库索引要定期做孤儿/死链审计(双向机检)。—— 通用。来源:mem:memory-orphan-audit-20260927、mem:memory-index-compression-20260927
10. 复杂数值表用"白话+场景+1:1 举例"三档互证教学,举例数字必须核实。—— 通用。来源:§23.9、mem:complex-table-explanation-style
11. 过错要归档+编锚点+防重犯条款(每次犯错追加),形成可反查的经验库——本办法的元方法。—— 通用。来源:§18、mem:self-growth-mechanism

**半通用 → 通用版改写示例(占位符化)**:
- 例 1(来源 L50):「审查 `fapi_daily_syn.sh` 的 harness 门控写成依赖环境变量,被真执行 2 分钟」→ 通用版:「对生产脚本做审查/验证时,任何"可能执行到脚本本体"的脚手架都必须用**正白名单**门控(只许执行显式声明为安全的文件),禁止用"环境变量是否设置"这类**可被真实运行形态绕过**的条件做拦截,并先证明拦截生效(试跑一次被拦路径)。」
- 例 2(来源 mem:deploy-cdn-stale-snapshot-blue-screen):「版本串断链+CDN 孤儿快照致三站白屏」→ 通用版:「前端资源缓存指纹必须与内容强绑定(内容变→指纹必变);发布后自动校验"线上文件哈希==页面引用指纹";Service Worker 更新须壳芯配套,且失败可回退,防"更新后白屏"。」
- 例 3(来源 E23):「K=1 时每笔 1 万 ≡ 每日资金池;K>1 每笔 1 万=虚假杠杆」→ 通用版:「回测口径里"每笔名义金额×笔数"会系统性放大收益(实际资金占用不变)。判口径真实性:①先验边界情形(两口径在退化参数下应逐位相等)②收益率分母用**峰值实际占用资金**,不用名义本金累加。」

## 五、形态建议(通用版目录怎么组织)

**推荐:两层式 = 索引 README + 按域正文多文件**(与本仓验证过的模式同构:根索引 + 归档原文 + memory 指针)。
- `README.md`:入口 + 使用方法 + 按域一行的总目录(每条:`编号 | 一句话 | 域 | 来源标注`);
- `pitfalls/<域>.md`:约 10 个域文件(A 协作 / B 告警 / C 测试 / D git / E 数据 / F 成本 / G 调度 / H 调研 / I 前端 / J 删除备份 / K 运维 / L 外部依赖 / M 数据科学 / N 平台工具 / O 工作方式),每条固定字段:**现象 → 根因 → 防再犯(正向动作)→ 反例/代价 → 来源 id**;
- 每条带来源标注(如 `trade:L50`、`trade:mem-xxx`),便于溯源与后续更新。
- 取舍:条目 100+ 且要长期追加,单文件会过长难维护;分层是本仓两类资产(CLAUDE.md 索引 / docs 归档)都验证过的结构;缺点=文件多,靠 README 索引导航解决。

**备选 1:单文件分节**(`PITFALLS.md`,按域 §1-§15 分节)。
- 适用:分发场景要单文件拷贝、条目 < 120;缺点:引用与更新粒度粗,长了以后 grep 慢。

**备选 2:纯清单版**(一行一条,只有"结论+来源",无正文)。
- 适用:v1 先发布速查卡,后续再展开;缺点:缺 Why/反例,教学价值低。

**建议落地路径**:先出备选 2 作为 v0 速查清单(从本报告 §四 直接生成,约 120 行),再按推荐结构展开 v1;正文中的项目名一律占位符化(参考 §四 改写示例)。

## 附录 A:证据命令与关键输出

| 证据 | 命令 | 关键输出 |
|---|---|---|
| memory 文件数 | `ls -1 <memory>/*.md \| wc -l` | 246(含 MEMORY.md);目录总条目 251 |
| 索引链接数 | `grep -o '](' MEMORY.md \| wc -l` | 230;MEMORY.md 147 行 |
| 死链/孤儿 | `comm` 对比链接集与文件名集 | 死链 0;孤儿 15(甲类设计)+ MEMORY.md 自身 |
| type 分布 | `awk -F'\|'` 抽 frontmatter | feedback 138 / project 78 / reference 25 / user 1 / 非标准 3 |
| §18 表条数 | `grep -c "^| L" CLAUDE.md` / `"^| E"` | 15 / 10 |
| archive 锚点 | `grep -c "^L[0-9]"` / `"^E[0-9]"` archive 文件 | 50 / 30(头部自述 49 为旧口径) |
| docs 规模 | `ls docs/*.md \| wc -l`、`ls docs/ops/*.md \| wc -l`、`find docs -name "*.md" \| wc -l` | 95 / 426 / 948 |
| docs/ops 经验型 | 标题关键词 case 扫描 | 命中 25;rootcause 文件名 17 |

## 附录 B:对账与漂移说明
1. **archive "49" vs 实测 50**:头部零丢失等式锚(==49)为 2026-08-12 归档时口径;L43-L50 系此后追加,块内实为 50 条 → 建议日后把头部注释更新为 50(或注明"随时间追加")。
2. **memory 245 vs 索引 230**:差 15 = 甲类孤儿(已升格为 CLAUDE.md 正文的指针型 memory,设计上不补索引),与 09-27 审计与周 review 结论一致。
3. **docs/ops 425 → 426**:盘点期间该仓被并行工作写入(活跃工作仓),±1 漂移属正常;本报告口径=盘点时点实测。
4. **3 条 memory 无标准 frontmatter**(email-resend-switch / memory-orphan-audit-20260927 / zcode-standin-handoff):按实际内容归项目类,已计入 245;建议后续统一为 frontmatter 格式。
5. 本报告为只读盘点,**未改动任何既有文件**;唯一新建产物=本文件(未 commit,是否需要提交由主控决定)。
