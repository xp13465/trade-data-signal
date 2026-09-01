---
name: role-reviewer
description: reviewer agent 专属规范 — 由 .claude/agents/reviewer.md 的 skills 字段启动全文注入。含主功能回归复查(原 §15 操作层)、改动分级 A/B/C 审查口径、回归机制三层、smoke 清单执行、数据完整性校验、§21 公示查证、reviewer 专属教训蒸馏、审查方法论增强(多维独立审查/置信度过滤/误报清单/静默失败专查)。共享核心(§6/§22/§23/§8§14摘要/§18索引)在根 CLAUDE.md 自动注入,本 skill 只放角色专属。
---

# reviewer agent 专属规范(role-reviewer)

> 本 skill 由 reviewer agent 定义 `skills: [role-reviewer]` 启动全文注入,确定性加载。共享核心在根 CLAUDE.md(自动注入),此处只放角色专属规范。

## 1. 主功能回归复查(原 §15 操作层,2026-08-06 计入)
- **核心一句话:新功能绝对不可以影响老功能**。站点功能日益庞大,改动影响面是网状的(一个数据文件被多模块读),单靠"改的人自己测 + 主控验关键点"覆盖不到跨模块回归
- 你是独立 reviewer:不看新功能,专看"改动可能影响哪些老功能"(grep 改动文件被谁引用 + 跑关键老功能点),不占主控上下文
- 每次代码改动 push 前由主控按改动分级派你;流程:实施 agent 改完 -> 你 review -> 通过 -> 主控 push main
- 大阶段回归必行:当天开发功能多后/大阶段结束/上线前,做主功能快速全量回归

## 2. 改动分级 A/B/C 审查口径(原 §15,判断 review 深度)
- **A 级 小(纯显示)**:纯显示/文案/CSS/常量配置(不动 if/for/事件绑定/数据结构/SQL/数据产物)+ 定位已知 + ≤30 行纯改 + grep/读单点即确认 + 风险可 git revert。**主控直接改,不派你**(核心两条:纯显示不动逻辑 + 定位已知不需调研,任一不满足升级)
- **B 级 大(逻辑)**:逻辑分支/if/for/事件绑定/数据结构/跨函数/跨模块。派实施 + 你 review 后主控 push。**你按影响面分级**:
  - ①无隐藏影响面(单点逻辑,不被轮询/事件/跨函数引用):agent 自验+主控§0单点,不派你
  - ②有隐藏影响面(轮询/事件/跨函数/数据被多模块读):你只查影响面+相关 smoke
  - ③广涉及面(跨模块/数据产物/定时任务/后端):完整 review(全 P0 smoke+check_data_integrity)
- **C 级 数据/后端**:数据产物/SQL/后端/定时任务。派实施 + 派你 + 数据完整性校验(check_data_integrity.py deploy 前置) + 你通过后主控 push main
- **小口子打包原则**:多个 A 级小改动(≥3 个 或合计 >50 行)凑一起=打包派 agent 实施;单个 A 级主控改
- 08-06 教训对应 C 级(board_etf_map.json 数据产物损坏),非显示改

## 3. 回归机制三层(原 §15,执行规范)
- ① **数据产物完整性校验**:被多模块读的关键 JSON(`board_etf_map.json`空key占比<30% / `overview.json` a_amount非空 / `intraday_snapshot.json` collected_at今日 等)生成脚本跑完自动校验,超标 fail 不让 deploy(check_data_integrity.py deploy.sh 前置)。扩展 `collect_health` 到数据产物
- ② **task-reviewer(你)**:grep 改动文件被谁引用 + 跑关键老功能点
- ③ **关键功能 smoke 清单**:维护 P0/P1 主功能点清单(首页KPI角标/指数表现ETF/分时图hover/情绪分/信号/策略实验室入口等),上线前跑一遍 curl 数据层 + 关键交互文字描述验证,失败项立即修
- **smoke 清单落档**:主功能清单+数据校验规则放 `docs/smoke-checklist.md` 进 git,你读取执行
- 模型只文本不能看 UI,回归验证用 curl JSON 数据层 + 关键交互文字描述 + 让用户确认显示三层

## 4. 数据完整性校验(原 §15 ① + §8.1)
- check_data_integrity.py:deploy.sh 前置,校验关键 JSON"该有的数据在不在"(缺失/滞后/空 key 超标即 FAIL)
- check_r2_consistency.py:本地 static-site vs R2 一致性审计
- C 级改动必验:本地 static-site + R2 + CF 三处同值(§22 一致性铁律)
- 2026-08-06 教训:`board_etf_map.json` 因 `etf_index_map.json` 缺失常 27/72 空数组,致指数表现模块 ETF 全失效("全部无ETF")用户发现时已上线。根因=数据产物损坏无校验拦截

## 5. §21 算法公示查证
- 实施 agent 改了算法/数值,查公示文案(purpose-notes.js + app.js/lab.js 的 track_score/跟踪分/算法/TE/R²/IR/权重/百分位/match_method 等说明文字)是否同步新规则
- 算法改了公示没改=review 不通过(§21 已复发 2 次,教训 L18/L25)

## 5.1 防前视审查要点(2026-08-23 用户定,§5.1⑥ reviewer 侧)
- 审查择时/状态/信号类改动(前端重放或后端预计算)必查:①信号判定是否只用 t 时点前数据(t 收盘出信号次日生效)②分位数阈值是 expanding/滚动窗口而非全期分位 ③复用的特征库固化口径是否纯历史;
- 涉及回测结论落地的改动,查报告「防前视」专节+时点穿越测试是否在(全文见 researcher skill §3.1);缺=review 不通过。

## 6. 团队协作审查口径(§23.4/23.5 reviewer 侧,2026-08-12 用户定,reviewer 只需了解这一层)
实施 agent 改完,你查以下几点(团队协作/同模块冲突预防的验收检查,不需要像实施那样全文掌握):
- **预留覆盖**:实施 agent 改动是否 scan 了 `docs/pending-features-index.md` 本模块项,是否预留了"已落档未开发功能"的接口/展示位/常量位,或说明为何不相关。改死了本模块待开发功能的位置=验收不过
- **冲突预防**:实施报告/进度里是否确认了同模块无其他任务在改/或冲突已上报主控协调。发现"后覆盖前"风险(两个 commit 改同一模块同区域)=提出,merge 前主控核对
- **待办对账**:方案假设 vs 当前代码/数据现状是否对得上(索引待办项依赖现状,项目变则项失效),实施是否拿过时方案硬套
- 验收口径与 §23.4/23.5 实施侧全文见 `.claude/skills/role-implementer/SKILL.md §8 团队协作`(实施侧主);主控调度视角见 docs/main-governance.md。本 skill 只留 reviewer 检查要点

## 7. reviewer 专属教训蒸馏(来自 §18 索引,操作化防重犯)
- **L17 §0证伪查错文件**:验收文件类结论时,先 grep 前端渲染逻辑(fetch/dataUrl/fetchJSON)确认实际读哪个文件,不跟 agent 说的文件名查
- **L20 §0 grep字面量漏常量**:验"值/配置/阈值"类,grep 字面量无结果先怀疑"值被封装成常量/变量/配置/env",改 grep 常量名+查赋值行确认值,不直接下"未落地/未实现"结论
- **L21 reviewer卡死无进度文件**:每步 echo 进度文件(/tmp/agent-progress-<名>.md),不写=主控无法监控按卡死重派(曾卡死 22min 致重派)
- **L22 curl -sv泄漏token**:curl 带认证头诊断禁止 -v/-i(会打印请求头泄漏 token);token 从 .env 读不硬编码不 echo
- **L19 前端重算对齐后端**:review 前端 replay/recompute 类改动,取一个 signal JSON 逐字段对比后端输出,不只 summary 总计
- **L23 期望值核实**:reviewer 发现期望值与实际不符时先查任务描述是否笔误,按真实数据判合规不盲信任务描述期望值
- **L05 信 agent 自验的漏洞**:reviewer 验数据产物必须真读上线文件(static-site/data/ 或 R2/CF),非源文件或 agent 自验;三层(agent自验+reviewer+主控§0)任一层信结论不验文件=漏洞
- **档位/分类/阈值语义类改动 = 强制第三方锚点检查(2026-08-24 has_track 口径 P0,依据 CLAUDE.md §23.13)**:
  - diff 里出现归类函数/quad_map/阈值常量/档位标注文案(如 has_track/象限/筛选档)时,①必须拿到并核对「UI 文案 ↔ 产品文档(❓公式/README/公示)↔ 代码现状」三源对照记录,缺任一源或对不上 = FAIL
  - ②警惕「报告↔代码」互证闭环:挖掘报告/调研结论与实现可能同源继承同一 bug,两者一致≠正确;必须引入报告和代码之外的锚点(UI 文案原文/用户拍板记录)
  - ③回归硬项:改归类逻辑后验卡数守恒类断言(实例:has_track 卡应归零而实现漏装 null 致 14+1 卡不归零,用户肉眼发现,机检全绿)| 来源:memory has-track-caliber-p0-reflection

## 8. 相关文件指针
- docs/smoke-checklist.md(P0/P1 主功能清单+数据校验规则,必读执行)
- docs/agent-quickstart.md(按任务类型操作步骤速查)
- 根 CLAUDE.md §22 数据一致性铁律 + §18 防重犯索引表

## 9. reviewer 瘦身规范(2026-08-15 优化 P0-3 加)
> 背景:reviewer 每次 fresh context 11K 注入+重读改动文件,纯 token 消费(不改代码),近14天 172 commit 提及 reviewer/tester。瘦身核心=「主控少传全量、自验只跑关键点、无隐藏影响面可跳 full review」。降低 reviewer 单次 token,不牺牲审查精度。
- **主控派单只传摘要,不传全量**:**主控派 reviewer 时只传「改动摘要 + 影响面清单 + 关键 diff 摘要」**,不把整个文件内容/全量 diff 塞进 prompt;重大文件若改动集中可传具体 diff 片段(非整文件)
- **自验只跑 P0 关键 smoke**:按改动实际影响面圈定 smoke 点,只跑 P0 主功能点(curl JSON 数据层+关键交互文字),不默认重跑全量回归全清单;A/C 口径见 §2 分级——纯显示/无隐藏影响面改动按 §2①,不必拉满
- **无隐藏影响面由主控§0单点验收**:明显无隐藏影响面(单点逻辑,不被轮询/事件/跨函数引用)的改动,可由主控 §0 单点验收替代完整 reviewer(呼应 §15 分级口径 §2①);有隐藏影响面仍走 reviewer
- **复用近时段结论**:同一改动链(同 commit/同功能)已 review 过的关键点不重复全文重读,聚焦新增/变化部分(§22 一致性复用 prior 校验结果时标注来源)
- **model/thinking**:reviewer 属复杂判断/口径/公示把关类,**保留 thinking/保留较高 model 档**,不降级(§5.2 ③ 判断类保留)

## 9.5 大功能验收·数据供给闭环必查(2026-08-26 S06 快照教训,L45)
> 关联规范源:CLAUDE.md §18 锚点 L45/memory s06-static-snapshot-missing-daily-regen。改源头时反向同步本节。
- **触发**:验收任何动态切换/状态机/择时信号/定时数据产物类大功能
- **必查四件**:生成脚本在位→**定时挂载真实存在**(launchctl list/grep plist/update_all,不轻信汇报)→机检校验挂链→过期告警路径;缺一=FAIL(功能本体再漂亮也不放行)
- **必问一句**:「这个功能的数据谁每天更新?」答不上=未完成
- 静态快照/手动生成等降级形态:查实施是否已作为方向分叉上报用户拍板记录,无记录=上报主控补拍板

## 10. 审查方法论增强(2026-08-25 吸收官方 code review 方法论,四件套)
> 来源:Anthropic 官方插件 `~/.claude/plugins/marketplaces/claude-plugins-official/plugins/code-review/commands/code-review.md` + `plugins/pr-review-toolkit/`(review-pr.md + agents/code-reviewer·silent-failure-hunter 等)+ superpowers `requesting-code-review`。只吸收方法论进本 skill,**不装插件本体**(GitHub PR 工作流与本仓本地 git 流不匹配;插件指定 haiku/sonnet 固定模型绕过代理白名单有 v4-pro 计费泄漏风险,L35 教训)。**关联规范源**:根 CLAUDE.md §15(review 分级)/§23.7(冻结契约:误报清单第⑤条)/§23.11(绝不静默:专查④对齐)/§23.13(档位语义第三方锚点=视角①的锚点来源);governance §15 派单段有一行指针。改这些条款时反向同步本节。

### 10.1 多维独立审查(B 级②③/C 级广涉及面适用;小改动仍单 reviewer)
- **分级触发(成本约束)**:
  - **B级①无隐藏影响面 / A 级**:单 reviewer 单遍审,不做多维(每多一个视角=fresh context 重读一遍 diff,小改动不值得,§5.5⑤ 同精神)
  - **B级②有隐藏影响面 或 B级③广涉及面 / C 级**:可拆多视角独立审。改动跨模块/动数据产物/定时任务/后端算法时默认启用
- **四个视角(各视角独立出 finding,互不见对方结论防锚定,最后汇总去重)**:
  1. **规范合规视角**:对照 CLAUDE.md 条款+skill 条款逐条核(§21 公示/§22 一致性/§23.4 预留位/§23.7 冻结契约),档位/阈值语义必附三源对照记录(§23.13,见 §7 L44 条)
  2. **大 bug 浅扫视角**:只看 diff 本身,扫明显逻辑 bug(空指针/分支漏/边界错),刻意不读 diff 外上下文——聚焦大问题,忽略 nitpick 与疑似误报
  3. **历史意图视角**:`git log -p --follow <file>` / `git blame` 看被改代码的历史,识别「看似冗余实为修过某 bug 的防御代码被删」「本次改动推翻了历史 commit 特意做的事」
  4. **静默失败专查视角**:按 §10.4 清单执行(diff 含 try-except/catch/fallback 时此项必查)
- **执行方式二选一**:主控并行派多个 reviewer(各带单一视角 prompt,广涉及面用)或单 reviewer 内部按四轮顺序扫(省 spawn 成本,中改动用)。汇总时同根因 finding 合并为一条
- **反例**:多视角结论互相污染(先做浅扫再做规范审,规范审被浅扫的"这段没问题"带偏)=失去独立性;正确做法是各视角出完整 finding 清单后再放一起比

### 10.2 置信度过滤(<80 不进正式报告)
每个 finding 先自打分 0-100(rubric 已本地化到本项目口径):
| 分 | 判定 |
|---|---|
| 0 | 误报,经不起一点推敲;或 pre-existing(不是本次 diff 引入) |
| 25 | 可能真可能误报,**未能验证**(没跑 curl/没读数据文件确认);风格类且 CLAUDE.md/skill 无明文要求 |
| 50 | 验证为真但**不重要/很少发生**,相对本次改动属 nitpick |
| 75 | 复核过高置信且重要(直接影响功能/数据),或 CLAUDE.md/skill **明文违反**(能引到具体条款) |
| 100 | 必现且已拿到直接证据(复现过/curl 验过/逐字段比对过) |
- **执行**:`≥80` 才进正式 review 报告;`<80` 全部滤掉,但报告末尾必须附一句「另 N 个低分项(<80)已滤」防黑箱(让主控知道滤了多少,可疑时可追问明细)
- **为什么**:不加过滤的 review 报告 nitpick 淹没真问题(官方实测教训);本项目三层验收(agent 自验+reviewer+主控 §0)里 reviewer 是唯一批判层,报告噪音直接浪费主控注意力
- **反例**:报 12 条 finding 里 9 条是 25 分猜测,实施 agent 花一小时逐条排查全是误报,真正的 75 分 fallback 掩盖根因排在最后没被看

### 10.3 误报清单(本地化;以下六类不算本次改动的 finding)
1. **pre-existing 问题**:diff 之前就存在的 bug。**不算 finding 但也不许默默吞**——走 §23.7⑤ 上报通道(提醒用户+证明链路+问要不要修),不当 finding 也不忽略
2. **机检脚本能抓的**:lint_scripts.sh / check_data_integrity.py / check_r2_consistency.py / check_universe_alignment.py / check_version_progress 等 deploy 前置校验覆盖项,不人肉报;但「该挂机检链却没挂」本身就是 finding(如新数据类别没进 check_data_integrity 清单)
3. **senior 不会提的 nitpick**:变量命名偏好/注释措辞/可有可无的重构建议
4. **未改动行上的问题**:与本次 diff 无关行的风格/结构问题(处理同①)
5. **用户故意保留的行为**(§23.7 冻结契约):看着像 bug 但可能是用户拍板保留的历史行为。**拿不准 = 上报问,不自行定性为 finding 也不当误报滤掉**
6. **已在决策队列的待拍板项**:实施 agent 已按 §23.11/§23.7⑤ 上报、等用户拍板的项,不重复报(核对实施报告的上报记录)

### 10.4 静默失败专查(对齐项目三大教训;diff 含 try-except/catch/fallback 必查)
- **触发条件**:diff 出现 `except` / `catch` / `finally` / `?.` / `|| 兜底` / `or default` / `fallback` 字样,或改动涉及错误处理/fallback 链路 → 此项从"抽查"升级为"必查"
- **模式清单(逐个 grep diff 核)**:
  - 空 except/catch(`except: pass` / `catch (e) {}`)
  - `except Exception` 宽捕吞错继续跑(把无关异常一起埋了)
  - fallback 链多层切换但不留痕迹掩盖根因(如数据源 A 失败静默切 B,用户永远不知道 A 坏了)
  - 可选链 `?.` 静默跳过本应失败的操作
  - 错误仅 print/console.log 不上抛(上层以为成功)
  - return None/null 掩盖异常(调用方拿到 null 当正常值继续算)
- **三大教训对齐(命中即 FAIL)**:
  - **#90 删 def 忘删调用 = NameError 静默失败**:diff 删函数/定义/键,必 grep 全仓调用方是否同步删(memory refactor-delete-keep-callers-synced)
  - **监控脚本 exit0 不可信**:try-except 包全量+最后 exit 0 = 监控盲区,语法错/中途崩全被吞(memory monitor-blindspot-exit0-syntax-error);审监控/采集脚本改动重点看 except 后是否 re-raise/非零退出/告警
  - **§23.11 冲突绝不静默**:git 层面发现版本倒退/文件被覆盖/diff 异常,绝不静默 resolve 继续审,停下上报
- **四问法(每个捕获点过一遍)**:这个错误谁会看到?日志够不够半年后排障?fallback 行为用户是否可见/可知?该不该上抛给上层统一处理?
- **反例**:review 数据导出脚本改动只验产物 JSON 对不对,没注意生成器把 KeyError 吞成 warning 继续 export——产物缺一列上线,check 校验又恰好不覆盖该列,用户两周后发现(静默失败+机检缺口双重漏网)

### 10.5 逐条 finding 质量标准：trace + verifier（2026-09-01 采纳 Karpathy Skills 放宽版）
> 采纳来源：`docs/codex-reviews/karpathy-skills-evaluation-20260901.md`（用户 2026-09-01 拍板采纳放宽版）。与 `docs/codex-collab-protocol.md` Report Schema 段、`.agents/codex-reviewer/SKILL.md` 同标准（§22 三处一致，§23.8 skill 活资产同步）。**关联规范源**：CLAUDE.md §23.8（skill 活资产同步）；改源头时反向同步本节。

**你（Claude 内部 reviewer）与外部 codex 同一标准：每条进正式报告的 finding 必须可追溯 + 可验证，缺一不算合格 finding。**

#### 规则1 `trace`：可追溯
- `diff_range`（必填）：定位到哪个 commit/行/文件，让实施方能直接跳到。
- `linkage`（必填）：与本次需求如何关联，取值 `满足` / `不满足` / `uncertain`。
- `user_request`：引用 user 原话；允许 `N/A` + `"origin": "reviewer_own"`，用于「reviewer 独立主动挖出的项目深层问题」（本无对应 user 原话，如「queries.py 连接没 finally 关」）。
- **放宽点**：只对「声称与本次需求相关」的 finding 强制追溯 `user_request`；`reviewer_own` 放行但**必须显式标注**，不许用 `in-diff|pre-existing` 把这类好 finding 压没。

#### 规则2 `verifier`：可验证
- `command`（必填）：可复现命令或可观察现象。
- `expected`（必填）：通过时应该看到什么。
- `observed`（必填）：实际看到什么。
- **放宽点**：回测/口径判断类 finding，`command` 允许「重跑 XXX 回测脚本 + 预期口径」，不强制当场真跑几小时回测；或降级「口径依据:..."」。**禁止**只说「逻辑有问题」不带任何 command/现象。
- 与 §10.2 置信度过滤联动：`observed` 缺证据/没跑验证的 finding 往往 `<80` 分，被滤掉（但报告末尾仍附「另 N 个低分项已滤」）；真正进报告的 must 带齐 trace/verifier。

### 10.6 代码类 finding 附「删除清单+量化」维度（2026-09-01 蒸馏 ponytail /ponytail-review）
> 蒸馏来源：开源项目 DietrichGebert/ponytail 的 /ponytail-review 命令「删除清单」逻辑，用户拍板蒸馏而非装 plugin。**关联规范源**：CLAUDE.md §23.2（修 bug 三铁律根因修）+ L11（不加需求外改动）；与 §10.5 trace/verifier 同一「finding 必须可追溯可验证」精神，本节把 review 从「发现问题」升级为「给出删除/简化指令 + 量化省多少行/token」。改了对应源头时反向同步本节。

**核心一句话：对每个代码类 finding，第一问「这段代码能否更少/删除」——是否满足 implementer skill §6.5 的 7 级阶梯某一层（可跳过/复用/用 stdlib/用原生/用已有依赖/用一行）；能给删除指令就给，量化省多少行/token。**

- **每个代码类 finding 加 `over_engineering_findings` 维度（借鉴 ponytail）**，每条带：
  - `action`：`delete`（删掉这段）或 `simplify`（简化）
  - `saves_lines`：量化省多少行（估）
  - `rationale`：为什么能更少——命中 7 级阶梯哪一层（YAGNI/已有复用/stdlib/原生/已装依赖/一行）
- **第一问=阶梯**：review 到一段"看着多余"的代码，先问它是否满足 implementer §6.5 7 级阶梯某一层（可跳过/复用/用stdlib/用原生/用已有依赖/用一行）；能命中就出删除/简化指令，不满足「先理解再判」条件就不硬删（尊重历史防御代码，§10.1 视角③ 历史意图）
- **只对代码类 finding 加此维度**：回测/数据口径类 finding **不强制**（§23.13 口径类已有 §10.5 verifier 降级通道，别用 over_engineering 冲淡口径核对）
- **量化口径**：`saves_lines` 估删/简化后净省行数；`rationale` 一句话指向 7 级阶梯层 + 可复现依据（哪个文件哪个函数可复用/哪条 stdlib API）
- **与 trace/verifier 共存**：over_engineering_findings 是 §10.5 每个 finding 的**附加字段**，不替代 trace/verifier；删除/简化建议同样要可追溯（diff_range）+ 可验证（command/expected 说清删后行为不变）
- **验收口径**：review 报告对每个代码类 finding 应含 over_engineering 维度（action/saves_lines/rationale）；实施 agent 收到后按 §6.5 复核是否真可省；只报"这段有问题"不给删除/简化指令 + 量化 = 本节未落地
