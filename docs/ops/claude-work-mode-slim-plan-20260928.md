# claude-work-mode 包瘦身同步 · 影响面方案(researcher 产出,2026-09-28)

> 结论带证据点;只出方案不改任何文件。落档本文件,回报告只回结论+证据点。

## 〇、现状核实(6 个关键事实)

| # | 事实 | 证据 |
|---|---|---|
| F1 | claude-work-mode/CLAUDE.md = 513 行 / 66.7KB,节号 §0~§24 全在(缺 §2/§3/§4/§7/§20,历史段引用 §10/§12/§13/§17) | 实读 L1-513;`grep -n '^## '` 32 节 |
| F2 | 包内 4 skill = 295 行(impl 118/res 58/rev 70/tst 49)。**并非"零承接"**:已承接 2026-08-16 当时的原 §9/§21/§8/§14/§23.2/§23.3/§23.4/§23.5/§15 全文。缺的是**主仓 08-16 后新增**:impl §1.1(§24 下沉)/§4.1(§23.15)/§6.5(7级阶梯)/§9(token行为层);res §3.1(防前视)/§3.2(同构对账)/§3.2b(量化影响);rev §5.1/§5.2/§9.5/§9.6/§10(审查方法论四件套);tst §2.1(Playwright)/§5(验证门三件) | impl skill L1-118 vs 主仓 L1-191(章节 grep 对比);collab-standard-claude 4 skill 合计 484 行(已瘦身正确形态,实测 wc -l) |
| F3 | 主仓已瘦身根 CLAUDE.md = 242 行,共享核心节 = §0/§0.1/§0.2/§1/§6/§5/§18/§22/§8/§8.1/§14/§21/§23/§24/历史归档/验收;**§9-§19 下沉节号已从根消失**(§9→impl§1、§11→governance§11、§15→governance§15+rev§1、§12/§13/§17→archive、§16→governance§16、§10→archive、§19 作废) | 主仓根 CLAUDE.md `grep -n '^## '` 全列;docs/ops/claude-md-section-map-20260928.md 第二节对照表 |
| F4 | **三仓定位不同**(已核实):collab-standard-claude/codex = **去业务化模板仓**("纯新增标准,不是任何项目的备份包",README L5/L3);claude-work-mode = **本项目可移植备份包**(含业务 PROJECT-SPECIFIC.md 233 行 + 命中率日志,README L27/L44)。collab-standard-claude 已瘦身(根 22.5KB + 4 skill 484 行 + docs/ 三层 + templates/),**自包含**;claude-work-mode **无 docs/ 目录**(ls 确认),非自包含 | 三仓 README L1-130 实读;`ls claude-work-mode/` 无 docs/ |
| F5 | **token-cache-stats 自动任务属实**:launchd `com.trade.token-cache-stats` 本机运行,每日 23:30(非云上;plist StartCalendarInterval Hour=23;README L195 "每日 23:30 由 launchd 任务...自动追加");脚本 token_cache_stats.py `--append-daily` 只改 README 4 个标记区块(L200-249 trend / L253-303 ascii / L311-354 changelog / L360-402 cfglog)+ config-snapshots/YYYY-MM-DD.json,写完自动 git add README+当天快照 → commit → **push origin main**(脚本 L537-611,绕开 main-merge.sh) | plist 实读;脚本 L100-114 标记/L646-706 写区块/L537-611 commit+push;README L195 |
| F6 | 包内 §N 引用 ~513 处(README 199/CLAUDE.md 112/PROJECT-SPECIFIC 68/skill 96/agent 48);下沉节号 §9/§10/§11/§12/§13/§15/§16/§17/§19 的字面引用中,大部分是"原 §N 溯源标注"(skill 标题)或 README 历史日志(豁免),真正需重核的 = agents description(~2 处)+ README 清单/映射表(~15 处)+ PROJECT-SPECIFIC 专项标题(~5 处) | grep 分布统计;`原 §` 标注 impl 9 处/rev 5 处 |

## 一、逐节分拣表(claude-work-mode/CLAUDE.md,逐节)

> 判定代号:①留根 ②下沉 skill/governance ③归档(历史/作废/本仓已移 memory 或 archive) ④删除(与该包现状冗余)。目标形态=主仓 242 行形态 + collab-standard-claude 去业务化参考。

| 节(行号) | 内容一句话 | 判定 | 去向/动作 |
|---|---|---|---|
| 头部 L1-9 | 备份包定位+拓扑 | ① | 压缩到 4-6 行(保留"通用备份包"定位+占位符提示) |
| §0 L11-23 | 5 角色上下文来源表 | ① | 保留;`<docs/role-based-context-research.md>` 占位符化 |
| §0.1 L25-31 | 主控只调度不实施 | ① | 保留(主仓根同款) |
| §1 L33-35 | 开工先读 | ① | 保留 |
| §5 L37-45 | 方案默认准则 | ① | 升级:补"外部系统先查社区/开源评估跨角色穷举"(主仓 §5 已加) |
| §5.1 L47-56 | 穷举最大化铁律 | ①摘要+②res§3 | 根补 ⑤全局维度/⑥防前视摘要(researcher skill §3 操作层;参考 collab-res §3 26-66 行含防前视/同构对账/量化影响) |
| §5.2 L58-63 | 模型参数层优先 | ① | 保留 |
| §5.3 L65-72 | 精简核心保障 | ① | 保留 |
| §5.4 L74-83 | 测试基准锚点 | ① | 基准定义=状态型,指针到 PROJECT-SPECIFIC §4.2(不改动;备份包状态型内容留文档不进 skill) |
| §5.5 L85-93 | token 优化 6 条 | ① | 保留 |
| §5.6 L95-102 | DeepSeek 峰谷定价 | ① | 保留(主仓根 §5.6 同款 L91-98);脚本路径可占位符化 |
| §6 L104-107 | 中文+口语化 | ① | 保留 |
| §8 L109-115 | 推送+三查 | ①摘要 | 压缩为触发词+三查一句话;操作层已 impl skill §3(L38-46) |
| §8.1 L117-122 | 派单锚点 | ① | 保留 |
| §9 L124-130 | 新功能先隔离 | ③归档 | 本仓正文已无留存(grep 仅 NOTES.md/archive 历史陈述;等价 memory new-feature-isolated-tab-first)→ 归档+历史引用一行 |
| §10 L132-140 | 破缓存/SW/min验证 | ③归档 | 已被 impl skill §1(L21-28)+§24 承接 → 归档+历史引用一行 |
| §11 L142-153 | 子agent生命周期/通知兜底 | ②governance | 主仓=docs/main-governance.md §11 同名节;备份包需**新建 docs/main-governance.md**(对齐 collab-standard-claude 形态)或根留指针 |
| §12 L155-162 | 遇API错误不卡死 | ③归档 | 本仓=memory handle-api-errors-without-stalling(无正文留存)→ 归档+历史引用一行 |
| §13 L164-169 | 模型能力约束 | ③归档 | 本仓=archive/CLAUDE-history.md §13(2026-09-28 d2fb77c0e 补档);历史归档引用段已有摘要 |
| §14 L171-178 | 生产稳定性 P0 | ①摘要 | 压缩为摘要;操作层已 impl skill §4(L59-64) |
| §15 L180-201 | 回归复查+改动分级 | ②rev skill+gov | 操作层已 rev skill §1-§4(L10-37);主控侧进 governance §15;根留一行指针 |
| §16 L203-237 | agent角色画像+prompt写作 | ②governance | 主仓=governance §16 同名节;备份包新建 governance 承接 |
| §17 L239-247 | superpowers 融合 | ③归档 | 本仓已作废(archive CLAUDE-history.md §17);历史归档引用段已有 |
| §18 L249-367 | 防重犯索引(39过错+30经验) | ①滚动窗口 | 压缩为最近15过错+10经验(主仓 §18 L99-135 同款),全量指针到 `<docs/archive/CLAUDE-errors-<月份>.md>` 锚点索引块;备份包需新建 docs/archive 或指针指向主仓 |
| §19 L369-376 | 高峰省token | ③归档 | 本仓已作废(§17 火山方舟高峰取消,archive);归档+历史引用一行 |
| §21 L378-380 | 算法公示指针 | ①指针 | 保留指针;全文已 impl skill §2(L30-36) |
| §22 L382-388 | 数据一致性 | ① | 保留+补"代码内常量登记点"增强(主仓 §22 L145-150 已加) |
| §23.1 L394-400 | README 维护 | ①摘要 | 压缩为 1-3 行摘要(参考 collab-standard-claude 根 §23.1 L150-151 形态) |
| §23.2 L402-410 | 修bug三铁律 | ①指针 | 全文已 impl skill §5(L66-71);根留指针 |
| §23.3 L412-418 | 举一反三 | ①指针 | 全文已 impl skill §6(L73-76);根留指针 |
| §23.4 L420-426 | 团队协作查已落档 | ①指针 | 全文已 impl skill §8(L105-112);根留指针 |
| §23.5 L428-435 | 新产物落档 | ①摘要 | 压缩为摘要+四件套一句话 |
| §23.6 L437-447 | 入样宇宙规则 | ①摘要+③业务泛化 | 业务特定(config/universe_rules.yaml/BUY_SIGNALS/board_etf_map)→ 泛化占位符或摘要;项目化已在本包 PROJECT-SPECIFIC §9.5 |
| §23.7 L449-459 | 版本冻结契约 | ①摘要 | 压缩为摘要 |
| §23.8 L461-469 | skill 维护同步 | ①摘要 | 压缩为摘要 |
| §23.9 L471-479 | 三档互证教学法 | ①摘要 | 压缩为摘要 |
| 历史归档引用 L481-486 | §10/§12/§13/§17 索引 | ① | 更新为现址(与下沉节号对照表一致) |
| §24 L488-498 | 前端防撕裂 | ①摘要+②impl 新增 §1.1 | 根留触发词+核心一句话+验收口径;impl skill **需新增 §1.1 承接全文**(当前缺,对齐主仓 impl §1.1 L42-52)+ rev skill 补 §5.2 |
| 验收铁律 L500-502 | 逐字验证 | ① | 保留 |
| 工作流总则 L506-513 | 6 条总则 | ① | 保留(可精简为 4-5 条) |

目标:513 → ~250-280 行。

## 二、节号是否变化 + 引用影响清单

### 2.1 推荐策略:节号全保留(内容压缩),主仓对照表方式
- 理由:①该包是**备份包非实际加载文件**(README L44),包内 §N 引用 ~513 处(README 199/PROJECT-SPECIFIC 68/skill 96/agent 48,F6),节号保留=引用零破坏;②§5.3 核心保障:节号体系是引用锚点;③collab-standard-claude 已瘦身根文件保留连续节号(§0~§26 无跳跃),是"节号保留"成功先例;④对齐本仓认知"下沉不是编号全变,而是去哪找"(ops-map 第一节)。
- 实施:§9-§19 内容从根移走(下沉/归档),但**节号保留为一行"已下沉→现址"对照行**(等效扩展"历史/约束归档引用"段),包内引用全部继续有效。

### 2.2 若走"节号消失"路线(严格镜像主仓),受影响引用清单(文件:行号 → 现指向 → 应改为)
> 仅列真正引用下沉节号且非"原§N溯源/历史日志"的处:

| 文件:行号 | 现指向 | 应改为 |
|---|---|---|
| `.claude/agents/implementer.md` L3(description) | §9 前端铁律 | `原 §9(impl skill §1)` |
| `.claude/agents/implementer.md` L29 | §9 全文 | `原 §9(impl skill §1)` |
| `.claude/agents/reviewer.md` L3/L27 | §15 回归 | `原 §15(rev skill §1-§4)` |
| `README.md` L92 | §11/§13/§15 边界章节 | 按对照表改"原 §N" |
| `README.md` L129 | §9-§19 编号继承注 | 更新为"下沉节见对照表" |
| `README.md` L161-173(章节映射表) | §9/§10/§11/§12/§13/§15/§16/§17 | 按对照表更新 |
| `PROJECT-SPECIFIC.md` L62/L92/L141/L209 | §9/§10/§15/§11 专项标题 | 标注"原 §N 专项"(历史溯源性质) |
| `CLAUDE.md` L256/L367/L388/L456 | §11/§15 互引 | 按对照表指向现址 |

- **豁免(不改)**:skill 全部"原 §N"溯源标注(impl 9 处/rev 5 处,F6,语义=来自旧版根节号,历史溯源);README 命中率日志区全部 §N(历史 commit message 引述,B 类历史陈述);config-snapshots/(状态快照)。

## 三、三仓是否同批:建议 = 结构对齐、不逐节镜像

| 仓 | 实测定位 | 已瘦身状态 |
|---|---|---|
| collab-standard-claude | 去业务化模板仓(README L3/L5 "纯新增标准,不是任何项目的备份包") | 已瘦身(根 22.5KB + skill 484 行 + docs/main-governance 27KB + templates/) |
| collab-standard-codex | Codex 版对等模板仓(README L3/L5) | 已瘦身(根 22.9KB + .codex/skills 547 行) |
| claude-work-mode | **本仓可移植备份包**(README L27/L44,含业务 PROJECT-SPECIFIC.md + 命中率日志) | 未瘦身(根 66.7KB + skill 295 行,停更 08-16) |

- **结论**:三者同源(方法论同源)但**定位不同**——collab-standard-* 是泛化模板(去业务化),claude-work-mode 是含业务备份。**不建议逐节镜像**(claude-work-mode 去业务化会丢其备份意义),**建议对齐到同形态**(A/B/C 三层:根共享核心 + skill 角色层 + governance/archive 主控层)。
- **具体动作**:①claude-work-mode 的通用 CLAUDE.md + 4 skill 可直接以 collab-standard-claude 已瘦身版本为基座(同源去业务化已完成,只需保留 claude-work-mode 特有的 PROJECT-SPECIFIC 引用);②claude-work-mode 缺 docs/ 层(governance/archive)→ 二选一:新建 docs/main-governance.md(对齐 collab,自包含)或保持非自包含(指针指向 trade 根 docs/)。推荐前者(自包含=可移植闭环)。
- **顺序建议**:先瘦 claude-work-mode(本任务),collab-standard-claude 已是正确形态不须回改;若采纳"以 collab 为基座"则实际是一次对齐,风险更低。

## 四、迁移手法 A/B/C + 占位符

### A/B/C 分类
- **A 该改**:根 CLAUDE.md 压缩/下沉;4 skill 增厚(impl 补 §1.1/§4.1/§6.5/§9,res 补 §3.1/§3.2/§3.2b/新增教训,rev 补 §5.1/§5.2/§9.5/§9.6/§10,补教训新增段);agents description 微调;README 通用规范清单(L96-129)+章节映射表(L149-175);PROJECT-SPECIFIC 专项标题标"原 §N";历史归档引用段更新。
- **B 历史陈述不改**:README 命中率日志区 4 区块(L200-402,历史 commit 引述,含大量 §N);config-snapshots/ 9 个 json(每日状态快照);README"版本/改动日志"(L307-354);PROJECT-SPECIFIC §11 子agent教训(历史 agent id)。
- **C 不能碰**:README 4 个 `<!-- token-cache-*-begin/end -->` 标记区块本身(自动任务每 23:30 整块重写,脚本 L528-534 `_replace_block`);config-snapshots/ 目录(每日 23:30 新增文件);根 `data/`(本项目规则);worktrees 镜像(不在包内,若有)。

### 项目特定值:泛化 vs 原文保留
- **已占位符化(保留原样)**:全文大量 `<docs/main-governance.md>`/`<deploy脚本>`/`<主域名>`/`<备站1>`/`<备站2>`/`<模型名>`/`<定时任务时点>`/`<DB名>`/`<数据产物A>`/`<数据校验脚本>`/`<docs/smoke-checklist.md>`/`<skill库名及版本>`/`<高峰时段>`/`<任务调度器>`/`<社区A>`/`<社区B>` 等——**原文保留不动**。
- **需泛化为 `<占位符>` 的项目特定值**:
  - §5.6(L95-102):`DeepSeek`/`api.deepseek.com`/`火山方舟`/`scripts/thinking-proxy-rollback.sh` → 可泛化(主仓根 §5.6 保留原文是对外事实名,备份包可选泛化脚本路径)
  - §23.6(L437-447):`config/universe_rules.yaml`/`BUY_SIGNALS`/`board_etf_map`/回测脚本名 → **项目特定业务强,建议泛化摘要**或下沉 PROJECT-SPECIFIC(其 §9.5 已有项目化)
  - §23.2(L404):`<模块A>` 等已占位符化,保留
- **必须原文保留(不能动)**:
  - §18 锚点 id 体系(L01-L39/E01-E30)与归档指针(锚点反查链)
  - §5.4 的"基准定义=状态型"指针(指向 PROJECT-SPECIFIC §4.2,不固化具体版本号)
  - §22 的用户原话引述(L385,"用户 2026-08-09 原话")
  - 各节的用户原话引述(§5.1 L49/§5.3 L67/§23.2 L404/§23.3 L414/§23.7 L451 等)——用户原话是规范权威依据,不可改写

## 五、风险点 + 验收口径(机检"核心没丢")

### 风险
1. **23:30 自动任务撞车**(已核实 F5):施工 push main 避开 23:20-23:40;施工不动 README 4 区块与 config-snapshots/;若施工改了 README 非日志段,提交放 23:40 后或确保 23:30 任务先读到施工版(任务 `_get_day_changes` 会把施工当天 commit 记入"当日改动"列,正常机制非冲突)。
2. **丢核心**(§5.3):压缩时误删规范锚点/用户原话/锚点 id 链。
3. **引用悬空**(§23.13/§18 索引 L41 同病):根瘦身后读者按老节号翻不到。
4. **skill 承接不完整**:根删了 skill 没承接(如 §24 全文 impl 无 §1.1 承接)。
5. **token_cache 竞态**:23:30 任务读 README 时与施工写 README 竞态(只发生在同一分钟窗口,规避=错时)。

### 验收口径(机检清单)
1. **核心保留 grep 机检**(§5.3①):瘦身后根文件必须存在以下锚点,逐条 grep 断言非空——`§0`/`§0.1`/`§1`/`§5`(含 5.1~5.6)/`§6`/`§8`(含三查一句话)/`§8.1`/`§14`/`§18`(滚动窗口+锚点指针)/`§21`/`§22`/`§23`(23.1-23.9 摘要)/`§24`/验收铁律/历史归档引用。
2. **可逆性**(§5.3②):瘦身前后各 commit 独立可 revert;下沉内容承接位置逐条可 grep(如 §24 全文在 impl §1.1、§15 在 rev §1-§4)。
3. **引用可达性机检**(ops-map 复现段同法):`grep -rhoE "CLAUDE\.md §[0-9]+(\.[0-9]+)*" claude-work-mode/ | sort | uniq -c`;对每个 §N 断言"根文件有 或 对照表有 或 原§N溯源 或 历史日志",四者皆无=悬空 FAIL。
4. **skill 承接完整度机检**:与 collab-standard-claude 4 skill 章节对照(impl §1.1/§4.1/§6.5/§9、res §3.1/§3.2/§3.2b、rev §5.1/§5.2/§9.5/§9.6/§10、tst §2.1/§5)——缺=FAIL。
5. **token_cache 保护机检**:`git diff` 不含 `token-cache-` 区块内容变更;`config-snapshots/` 未被 add(`git status --porcelain claude-work-mode/config-snapshots/` 为空)。
6. **双源对照**(§23.13):README 章节映射表与根文件实际节号逐行比对一致。
7. **结构对齐机检**:瘦身后 `wc -l` 目标 ~250-280(根)/~480(skill 合计),与主仓 242/602、collab 484 同量级。

## 六、工作量与拆阶段建议

### 拆 4 阶段(理由:skill 承接先于根瘦身=下沉才有去处;引用重核在节号定稿后;每阶段可独立验收可回滚)
- **阶段 0 方案冻结**(本方案,主控验收)
- **阶段 1 skill 增厚**:impl 补 §1.1(§24 全文)/§4.1(§23.15)/§6.5(7级阶梯)/§9(token 行为层)+关联规范源段;res 补 §3.1(防前视)/§3.2(同构对账)/§3.2b(量化影响)+新增教训;rev 补 §5.1/§5.2/§9.5/§9.6/§10(审查四件套);tst 补 §2.1(Playwright)/§5(验证门三件)。参考基座=collab-standard-claude 4 skill(484 行,同源已去业务化,逐节对齐搬运)。目标:295→~480 行。
- **阶段 2 根 CLAUDE.md 瘦身**:513→~250-280 行;§9-§19 下沉/归档,节号保留为对照行;历史归档引用段更新;补 §0.2(派单三件套,主仓 08-25 新增,claude-work-mode 缺)与 §5.1⑤⑥/§22 增强。
- **阶段 3 引用重核**:agents description(2 处)+ README 清单/映射表(~15 处)+ PROJECT-SPECIFIC 专项标题(~5 处);grep 悬空机检;与 collab-standard-claude 结构对齐比对。
- **阶段 4 验收**:机检清单(五.2 全项)+ 23:30 避撞验证。

### 工作量估算
- 阶段 1:skill 增厚 ~185 行(搬运 collab 已去业务化文本,机械工作量低)
- 阶段 2:根压缩 ~260 行(删/下沉,含对照表 ~30 行)
- 阶段 3:引用重核 ~22 处
- 阶段 4:机检 ~6 项
- 建议 1-2 个 implementer agent 执行(阶段 1+2 可合一 agent,阶段 3 单独)+ reviewer 按五.2 验收;每阶段独立 commit,可回滚。

## 七、复现段(本方案全部结论可复核)
```bash
cd /Users/linhuichen/code/trade
wc -l claude-work-mode/CLAUDE.md claude-work-mode/.claude/skills/*/SKILL.md
grep -n '^## ' claude-work-mode/CLAUDE.md
grep -n '^## ' .claude/skills/role-implementer/SKILL.md   # 主仓对照
ls claude-work-mode/                                       # 无 docs/
launchctl list | grep token-cache                          # F5
cat ~/Library/LaunchAgents/com.trade.token-cache-stats.plist  # F5 时点
grep -n "token-cache-" scripts/token_cache_stats.py | head # F5 区块标记
grep -rnoE "§[0-9]+(\.[0-9]+)*" claude-work-mode/ --include="*.md" | grep -v token-cache | awk -F: '{print $1}' | sort | uniq -c  # F6
```
