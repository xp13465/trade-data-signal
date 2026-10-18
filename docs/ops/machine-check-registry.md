# 机检闸门保险登记表(闸门 → 生命周期,单一事实源)

- 建立:2026-10-18(评鉴 P5 / 设计报告 §B4;批3 落地)。
- **本表是什么**:体系里每个「自动拦闸门」(CI step / merge 前置步 / hook / 检查脚本)一行,写清
  它防什么、什么情况下**不再保护**、什么正常操作会被**误伤**、坏了**谁接手**、怎么自检。
- **与教训台账的分工(不许混成一套)**:教训台账(CLAUDE.md §18 + 归档锚点块)的
  `机检=是(闸门:X)` 字段表达的是**某条教训的现状**(83 行,历史冻结,不追改);
  本表表达的是**闸门的生命周期**(随闸门演进)。两者**只靠一个键连接:闸门名**——
  「教训 → 闸门名」只写在台账,「闸门 → 生命周期」只写在本表,由 `scripts/check_gate_registry.py`
  ③ 双向对账兜底(§22 同一事实多处副本必须机检)。
- **机检**:`python3 scripts/check_gate_registry.py`(rc=0 PASS);接线
  `scripts/tests/test_gate_registry_pytest.py`(进 CI ⑧ pytest)。
- 说明(说人话):「失效条件」= 这条保护在什么世界变化后就不成立了(例:挂具类条款补的是平台缺陷,
  平台修好即失值);「误伤条件」= 什么正常操作会被它拦下(拦错了也是成本);「谁接手」= 它坏了/跳过了,
  下一步谁补。

## 一、在运闸门

| 闸门名 | 挂点 | 防什么 | 失效条件 | 误伤条件 | 失效时谁接手 + 动作 | 自检方式 |
|---|---|---|---|---|---|---|
| scripts/agent_dispatch_cron_reminder.py 机检派单 prompt 含进度文件路径 | scripts/agent_dispatch_cron_reminder.py(PostToolUse(Agent) hook,脚本 docstring 记机检三项) | L01(裸派三件套)+ L21(派单无进度文件) | 挂具类:补偿 Agent 平台缺陷(通知不可达 / 参数不转发),平台修好即失值 ⇒ 6 个月复审(§5.3.1) | prompt 用了别的进度文件写法(非 /tmp/agent-progress-)会漏判;只在"该补的没补"时发声(exit 2),不阻断派单 | 主控(派单方):看到 exit 2 当场补三件套;脚本改名必须同步台账 L21 行与本表 | 无自动自测(诚实登记,防被当遗漏);脚本内置两条参数级判定,改判定逻辑须重跑真实派单参数样例 |
| CI 全量 pytest + scripts/tests/ 源码形状守卫 | `.github/workflows/ci.yml` step 名 `⑧ 算法核心 pytest(P0-1, FAIL 阻断)`;守卫本体 scripts/tests/ | L52(改 scripts/ 源码后未跑全量 pytest ⇒ 形状守卫次日在 main 上红) | 只要 pytest 套件与源码形状守卫还在就有效;守卫改写成不读源码字面量时保护面收窄 | 新增测试若依赖本机独有环境(命令/路径)会让本机绿、CI 红(§5.8 上线关已写死"CI 必须真绿") | 主控/implementer:CI 红即修(形状守卫与源同批改);本机绿 ≠ CI 绿 | 无独立自测;变异 = 改坏一条形状守卫断言看是否真红(role-tester skill §5.3.1 判别力关) |
| scripts/gen_governance_size_report.py --check | `.github/workflows/ci.yml` step 名 `⑪ 治理体量月报对账(P3, 账不平才 FAIL)`;数据源 docs/ops/governance-budget-history.json | P3 体量棘轮(无锚点:评鉴项,非教训) | 月报 JSON 还在、rev 仍可由 git 解析即有效;若 git 历史被重写(rev 不可达)则对账锚失效 | 只在"账不平"(schema 错 / 记录字节 ≠ git 实测)时 FAIL;字节超阈值与季净增超 3 只 WARN,不阻断(防误伤) | 主控:账不平 ⇒ 先查是 JSON 写错还是历史被改;月报每月按 §5.3.1 补一行 | --selftest(负对照 + rev/字节变异必须 FAIL)+ scripts/tests/test_governance_size_report_pytest.py |
| scripts/check_gate_registry.py | scripts/check_gate_registry.py;本表 docs/ops/machine-check-registry.md;接线 scripts/tests/test_gate_registry_pytest.py | P5 保险面(无锚点:本表自身的登记与覆盖) | 本表与 check_*.py 扫描面存在即有效;扫描规则改成不认 check_*.py 命名时保护面收窄 | 只判格式与覆盖,不判内容对错(失效/误伤栏写错也 PASS,由 reviewer 抽样核对) | 主控:新增守卫没登记 ⇒ 本表补行;删闸门 ⇒ 台账侧"机检=是"会立刻报无对应行 | --selftest(删闸门行 / 删存量豁免行必须 FAIL)+ 纳入 CI ⑧ pytest |
| scripts/check_ledger.py(A–G 七维) | `.github/workflows/ci.yml` step 名 `⑩ 错误台账对账(评鉴 P1, FAIL 阻断)` | 台账漂移(无锚点:评鉴 P1;含 L44 类"口径/计数对不上"同族) | 归档锚点块结构或 CLAUDE.md §18 表结构被改写时解析器失效(现由"恒在自检"直接 FAIL 兜住) | 只判结构与计数,不判锚点内容真假;正文历史悬空引用只报 INFO(§6④ 历史不追改) | 主控/implementer:FAIL 即按输出行定位改声称或改归档;结构改写须同批改解析器 | --selftest(六向变异:计数/连续性/机检字段/归属等式/标题计数必须真响) |
| scripts/check_version_progress.py | `.github/workflows/ci.yml` step 名 `② 版本串倒退哨兵 + merge 净回退校验` | §23.11 git 冲突/覆盖绝不静默(无锚点) | 前端版本串机制(asset 版本串)换代即失效 | 分支基点太旧时的净回退会真报(设计如此,须 rebase 后重来) | 主控:按提示 rebase origin/main 后重跑;机制换代须重写判据 | 无独立自测(诚实登记);变更判据须构造"版本串倒退"样本手跑 |
| scripts/check_version_consistency.py | `.github/workflows/ci.yml` step 名 `③a 部署版本一致性·校验1/2(§24⑤ 纯静态必跑, FAIL 阻断)` | §24 前端部署/缓存防撕裂(无锚点) | 前端单版部署链与 sw.js 缓存机制换代即失效 | 校验3(min 重建)依赖 npx terser 联网,故单独放 continue-on-error 步,不在此列 | 主控/implementer:index 引用与实际文件不一致即修 bump/BUILD | 无独立自测;变更须在 static-site 真目录上跑(不在干净副本上验) |
| scripts/check_fade_keys_alignment.py | `.github/workflows/ci.yml` step 名 `① AI降亏默认档键集跨端一致性机检` | §22 同一事实多处登记点必须一致(无锚点;v1.1.5 切 NEW14 漏邮件白名单即此病灶) | 键集机制(前后端 + 邮件链路)换代即失值 | 新增键只登记在一处时会真报(设计如此,须补全登记点) | 主控/implementer:按报告 docs/kelly/analysis/v115-new14-baseline-alignment-audit.md 的 18 处登记点清单补齐 | 无独立自测(诚实登记) |
| scripts/check_task_state.py | `.github/workflows/ci.yml` step 名 `⑤ 任务状态一致性对账(§23.12-1, CI 跳过僵尸 cron 维度)` | §23.12-1 任务状态单一事实源(无锚点) | 待办索引/状态列机制换代即失效 | CI 跳过僵尸 cron 维度(本机维度才查),故 CI 绿≠本机全绿 | 主控:状态列与实物不符即改 pending-index 编号 + 状态列 | 无独立自测(诚实登记) |
| scripts/check_data_gap_alerts.py --self-test | `.github/workflows/ci.yml` step 名 `⑨ 采集缺口/停更告警器 two-way 自测(--self-test, #250-P4)` | L49(假样本养绿:机制必须证明"真能响",不能只证"能跑")+ 采集停更(无锚点) | 采集缺口判据换代即失值(样本/阈值随之变) | 自测全在临时库里跑,不碰生产 DB/R2;判据放宽后"正常态零命中"可能掩盖真停更 | 主控/implementer:two-way 自测红即修判据;放宽判据须同步降噪原则(memory alert-denoise-keep-fault-discriminator) | 脚本自带 --self-test(正常态零命中 + 注入态必命中,两级断言) |
| scripts/main-merge.sh 7.9 步(L52 pre-merge 全量 pytest) | scripts/main-merge.sh:7.9(feat 改了 scripts/ 任何源码时;约 150s) | L52(同上;把红从 merge 后的 main 前移到 merge 前的 feat) | main-merge 不再是 push main 唯一入口时失效(那时须把本步挂到新的入口) | 解释器无 pytest 时会**阻断**(判为"未验证");MAIN_MERGE_SKIP_PYTEST=1 可显式跳过(醒目日志) | 主控:merge 被阻断即在本机跑全量 pytest 修好再 merge;跳过须在报告里留痕 | 无自动自测;逃生门分支由 --dry-run 检出串 + 代码路径审查核对(真实 merge 低频,不强造自测) |
| L51 运行日平移复验(CI step) | `.github/workflows/ci.yml` step 名 `⑫ L51 运行日平移复验(测试文件变更时; 首期只报不拦)`;豁免清单 scripts/tests/time-shift-allowlist.txt | L51(时敏用例写死日期 ⇒ 当天绿、次日红) | **首期 continue-on-error:只报不拦**;判别力确认后转阻断。faketime 在 runner 装不上即整步失效(日志可见) | 取时合法的用例(已冻结时间)不会红;allowlist 里的已核实假红被 --deselect 跳过 | 主控/implementer:观察期人工核首跑日志(设计报告 §B2 三项待实测);转阻断后按红修用例 | 无自动自测(本机 mac 有 SIP 限制,测不了 faketime);验收证据 = CI 首跑日志 |
| scripts/check_universe_alignment.py --deploy-mode | scripts/deploy.sh:383(FAIL 阻断部署 + 发 severe 告警;仅 deploy-mode 分支) | §23.6 入样宇宙规则(无锚点;对称校验) | 入样宇宙规则/board_etf_map 收录口径换代即失效 | 只在 deploy 链上跑,本机跑 pytest 不会碰它 ⇒ 改了宇宙规则只跑本机测试会漏(须走一次 deploy 或手跑) | 主控/implementer:部署被阻断即按输出改宇宙规则或登记点;改规则须同步 §23.6 五条 | 无独立自测;改判定须构造"收录规则与首页不一致"样本手跑 --deploy-mode |
| scripts/check_repo_paths_ratchet.py(#195 路径守卫棘轮) | `.github/workflows/ci.yml` step 名 `⑧ 算法核心 pytest(P0-1, FAIL 阻断)`(经 scripts/tests/test_repo_paths_ratchet_pytest.py 调用;本体**不挂** deploy 链/cron,见脚本 docstring §7.2 待拍板#2) | #195 全仓 shell 写死 mac 路径回潮(无锚点:批1 迁移守卫)+ L49 空转根治(恒在自检 + --selftest) | 迁移批次收口后 PENDING_BASELINE 清空仍有效;若 resolve_repo 机制换代(不再用 scripts/lib)则判据整体作废 | R1 只收紧不放松 ⇒ 新增含 mac 路径默认值的脚本会被真报(设计如此);R4 只认双引号形态,无引号写法暂不命中(已知盲区,仓内 0 实例) | 主控/implementer:按输出批次推进(迁移完的文件从 PENDING_BASELINE 删、加进 MIGRATED);机制换代须重写判据 | 脚本自带 --selftest(变异回 mac 路径必须 FAIL + 负对照 PASS)+ 恒在自检(正则自己失效直接 FAIL) |

## 二、存量豁免 legacy-frozen(显式豁免 + 理由,防首日全红)

> 依据设计报告 §B1「存量冻结原则」:一次性要求全部 20 个存量检查脚本都拿出真实样本证据
> = 首日 20 红不可行,且多数根本不在 CI/merge 链上跑。故**显式冻结**:只登记、不追溯证据要求;
> 门(④ 覆盖检查)只保证「**新增**守卫一定被登记」这一半,**不假装**存量已达标。
> 重建条件:某脚本若被挂进 CI/merge 链,必须从本表**移出**、补进上面闸门表(带样本证据方式)。

| 脚本 | 豁免理由(legacy-frozen) |
|---|---|
| scripts/check-dual-src/check_dual_src_sync.py | 双树代码同步核对,临时/手动跑,未挂链 |
| scripts/check_data_integrity.py | 数据完整性抽查,手动跑,未挂链 |
| scripts/check_doc_staleness.py | 文档陈旧度抽查,手动跑,未挂链 |
| scripts/check_ds_resilience.py | 数据源韧性排查,手动跑,未挂链 |
| scripts/check_failed_units.py | 失败单元可见性(#196 机制),未挂链(生产实跑实证见 #203) |
| scripts/check_file_owners.py | 文件归属登记核对,手动跑,未挂链 |
| scripts/check_kelly_unique_parts_restore.py | 凯利唯一化片段恢复核对,一次性/手动跑,未挂链 |
| scripts/check_kelly_unique_restore.py | 凯利唯一化恢复核对,一次性/手动跑,未挂链 |
| scripts/check_large_json_excluded.py | 大 JSON 出仓核对,手动跑,未挂链 |
| scripts/check_loss_rules_vs_mining.py | 降亏规则 vs 挖掘权威对照,手动跑,未挂链 |
| scripts/check_monitor_heartbeat.py | 监控心跳核对,手动跑,未挂链 |
| scripts/check_north_gap_backfill.py | 北向数据回填缺口核对,手动跑,未挂链 |
| scripts/check_nt_signals.py | 国家队信号核对,手动跑,未挂链 |
| scripts/check_overfit_split_parity.py | 过拟合分半对照,手动跑,未挂链 |
| scripts/check_preupload_backup.py | 上传前备份核验,手动跑,未挂链 |
| scripts/check_r2_channel_coverage.py | R2 通道覆盖核对,手动跑,未挂链 |
| scripts/check_r2_consistency.py | R2 一致性核对(批1 迁移产物),手动跑,未挂链 |
| scripts/check_s06_freshness.py | S06 快照新鲜度核对,手动跑,未挂链 |
| scripts/check_s06_state.py | S06 状态核对,手动跑,未挂链 |
| scripts/check_sentiment_r2_upload.py | 情绪数据 R2 上传核对,手动跑,未挂链 |
| scripts/check_signals.py | 邮件/飞书信号推送脚本(update_all.sh 调它发通知),**不是守门员**;键集一致性由 ① 门(check_fade_keys_alignment.py)兜 |

## 三、明确不建(诚实条目,防日后被当遗漏补造)

- **新增测试的 red-first 判别力自动检查(评鉴例②)——不建**。理由(带外部依据):要做实须上变异测试
  (mutmut / cosmic-ray),成本 = mutant 数 × 套件时长;本仓套件约 150s,冷启动全量变异=小时级,
  挂在每笔测试变更上 CI 不可承受。保留:判别力关仍由 reviewer 手工变异 1 例(role-tester skill §5.3.1
  第三条硬约束),L51 平移复验天然覆盖时敏类判别力。
- **守卫映射脚本(B3-b:改动文件 → 受影响形状守卫)——不建**。理由:解析"读源码的断言"是启发式,
  易漏(漏了比没有更危险);main-merge 7.9 步已用"全量跑"覆盖,粗但可靠。真嫌粗再议。
- **本机"只跑相关用例就交"——机检不了,诚实登记**。本机在 agent 手里,仓内无版本化 pre-commit hook
  体系(强装=新增机制且可被绕)。替代:CLAUDE.md §18 L52 行 + implementer skill 纪律 + 上面
  main-merge 7.9 把"全量"变成 merge 时的机器动作(人承担面缩小到"一天内本机漏跑",由 merge 门补齐)。
- **闸门"真在跑"不在本表能力内**。本表只保证登记与覆盖无遗漏;每个闸门是否真被 CI/merge 调用,
  由 `check_gate_registry.py` ② 的挂点存在性 + reviewer 抽样核对共同兜(不假装机检)。

## 四、维护约定

- **新增/改动机检脚本**:同批在本表登记一行(7 栏全填),否则 `check_gate_registry.py` ④ 会红(未登记)。
- **闸门改名**:必须同批改台账(若该闸门挂在某条锚点的 `机检=是(闸门:…)` 上)+ 本表,③ 双向覆盖会红。
- **复审**:本表整体随治理体系换代 / CI 架构变更复审(§5.3.1「项目类」档);每条闸门的"失效条件"栏
  写的就是它自己的到期信号。