# #263 审查关报告(reviewer 独立审,2026-10-15)

> 审查对象:`feat/263-workmode-spec` @ `4cf4c84e3`(路1,14 文件)+ `feat/263-workmode-pitfalls` @ `4fef789b8`(路2,16 文件),包根 `work-mode-standard/`。
> 全程只读(`git show` / `git archive` 到临时目录),零真实外发,未执行任何业务脚本(§18 L50 static-only)。
> 证据留档 `/tmp/wms-review/merged/`;进度文件 `/tmp/agent-progress-workmode-review.md`(已写 `ALLDONE`)。

## ① 结论

- **无阻断项,两分支可合 main;但必须同批合,不可只合一路。** 实测两分支文件交集 = 0;若只合路1,`README.md:123` 指向的 `pitfalls/` 与 `lessons-index.md` 全部不存在(断链);只合路2 则索引无正文归属说明。
- **merge 零冲突**:两分支 merge-base 同为 `3c9023d5b`;main 自该基线起未改动这 30 个文件。
- 有 **3 处一行级必修项**(见 ④1-3,均为"用户读到的断链/不一致"),建议合并前修;不修也安全,但会作为已知残留进通用包。

## ② §10.8 边界完整性独立复核(先推清单、后对账)

reviewer 于 09:50 **未读两份实施报告前**自行推出 **14 条**(B1-B14)并落档(独立性证据),再与实施方清单对账:

| 分类 | 条目 | 结果 |
|---|---|---|
| 两边都有 | B3 README 接口逐字 / B5 十月增量落点 / B6 索引↔正文 / 残留扫描 | 一致,**无差集** |
| 差集(10 条) | B1 包内跨文件引用可达(结构变更后 `.claude` 自引用残留);B2 `skills:` 字段↔目录名;B4 结构变更连带(安装命令可用性);B7 孤立项目统计数字;B8 旧包/原目录是否误伤;B9 跨平台可移植(绝对路径/平台专属命令);B10 部分合并残缺;B11 语义空心(字段齐但读不通);B12 frontmatter 可解析;B13 节号引用漂移;B14 验收口径句弱化 | 逐条处置见下 |

差集处置:
- **B1/B2/B4/B12 补测 PASS** —— 全量解析包内 `docs|skills|agents|templates` 引用:要么真实存在、要么 `<占位符>`、要么指向目标项目路径;4 个 agent 的 `skills:` 字段 **4/4** 命中存在目录;8 个 frontmatter YAML 全部解析成功;README 安装命令声明的源路径全部存在。
- **B7/B9 补测 PASS** —— 项目统计量(20.6KB / 8.3G / 2232 行等)= **0**;`/Users/` 绝对路径 = **0**;平台专属命令 = **0**(唯一 `anthropic.com` 是 Claude 平台名,判通用实体)。
- **B8 补测 PASS** —— 两分支 diff 仅 `collab-standard-{claude,codex}/README.md` 各 +1 行;`claude-work-mode/` **空 diff,原样未动**。
- **B10 → 升级为合并硬要求**:"必须同批合"(见 ①)。
- **B13 → 发现 2 处断链(新增,路1 未自报)** —— 见 ④2 / ④3。
- **B11 抽测 PASS** —— 15 域各抽 1 条 + J 域全 6 条全读:五字段齐(现象/根因/防再犯/反例·代价/来源),叙述可脱离本项目语境读,无空心。
- **B14 抽测 PASS** —— 「自验须含…/缺=验收不过」类口径句大量在位(如 `role-tester:87` 两条配套硬约束、`quality-flow` 每关"出口条件")。

## ③ 必查 8 项逐条

**1. 去化干净 — CONFIRMED(1 处例外,判漏剥离)**
照 recon §5.1 命令集在合并包(30 文件)扫描:域名(仅 anthropic.com)✓通用;`#NNN`=0;memory 引号=0;`HH:MM`=0;`/Users/`=0;`.json/.db/.parquet`=0;业务词仅 2 处(`m-backtest-caliber.md:23,39` 来源字段)已显式标注「仅供溯源」= 合规白名单。
**命中 1 处漏剥离:`CLAUDE.md:86` 仍写「核心推荐 / 降亏过滤」**(recon §3.2 规则 4 已给定改写,且同文件 `:80` 已用通用版「核心推荐/过滤」= 自相矛盾)。判轻量必修,不构成阻断。

**2. 核心未丢 — CONFIRMED**
对照 recon §1 资产清单与 §3.3 保留清单:红线(§0.1 只调度 / §0.2 派单三件套)、铁律(§6/§22/§23 全条)、角色方法论、验收口径全在;15 域各抽 ≥1 条避坑核三要素齐。

**3. 十月增量 8 条逐条落点 — CONFIRMED(8/8)**
§5.7 → `CLAUDE.md:100-111` 全文 + `quality-flow.md` ②关 + `role-researcher/SKILL.md §2` + `role-reviewer` §10.7;§5.8 六关 → `CLAUDE.md:113-120` + `quality-flow.md:6`;§25 → `CLAUDE.md:242-252` 六条全文;CI 真绿 → `CLAUDE.md:119,138` + `main-governance.md:84` + `role-implementer:51-52` + `role-tester:87`;§10.8 边界独立复核 → `role-reviewer:137` + `quality-flow` 审查关;边界维度穷举 → `role-tester:77`;续跑延用原分支 → `role-implementer:55`(+ 索引/避坑 a 域);应急不豁免时点 → `CLAUDE.md:169` + `role-implementer:62` + 避坑 g 域。
**无缺条;但续跑条归属层级问题见第 8 项①。**

**4. 避坑库口径 — CONFIRMED,以 158 为准**
`lessons-index.md` `grep -c '^- '` = **158**;15 域标题括号数合计 A14+B9+C16+D12+E10+F8+G8+H16+I11+J6+K12+L7+M10+N8+O11 = **158**;索引↔正文 158==158 且 `comm -3` 双向空;五字段各 158。
**差 1 成因:"157" 只出现在 plan 文档 4 处,recon 与 experience 均无此数,experience §四逐条实测就是 158 ⇒ plan 是方案关出口时的笔误。** 来源字段可溯源(保留原编号/记忆名并标注"仅供溯源",与 recon §3.5.3 锚点声明要求一致)。

**5. README 接口一致性 — CONFIRMED(1 处措辞不统一,非阻断)**
`README.md:123` 逐字核对:15 个域 slug(a-o)与 `pitfalls/*.md` 实际文件名 **15/15** 对得上、「158 条」与实际一致、「一行一条的索引」= `lessons-index.md` 属实。差异点:README 用中文短名(如「k 生产运维平台」),索引/正文用域全名(如「K 生产运维·稳定性·平台环境」)——同域两种叫法(路2 报告已自报),建议统一(④6)。

**6. README 安装命令可用性 — CONFIRMED(静态接线)**
五件套命令源路径全部存在、`mkdir`/`cp` 语义成立;等价安装模拟(拷入 `/tmp/wms-review/fakeproj/`,得 `agents=4` / `skills=4`,4 个 `skills:` 指向全部解析成功)。
⚠️ **刻意未在 `/tmp` 真建字面 `.claude/` 目录**(依 plan §7 的 `.claude` 写入挂点取证 + §18 L50 探针 static-only),以路径解析替代 —— **本次唯一"未逐字实测"项,已声明**。

**7. 旧包冻结留痕 — CONFIRMED**
`collab-standard-claude/README.md` 与 `collab-standard-codex/README.md` 各 +1 行「已被 work-mode-standard/ 取代(2026-10 起),仅留档不再维护」;`claude-work-mode/` 两分支 diff 均空 = 原样未动;无其他业务文件误伤。

**8. 路1 自报 3 项待处置 — 判定**
- **①「续跑延用原分支只在 role-implementer skill」:成立,但不算"核心未丢"缺口** —— 内容确在包内(`role-implementer:55` + 避坑 a 域,字面满足方案实现预期);但**归属层级错位**:该动作的执行者是主控(派续跑单、清残留 worktree),主控只读 `main-governance`,而包内 governance 与 CLAUDE §0.2 **均无此条(实测 grep 0 命中)** ⇒ **该看到的人看不到,建议合并前补 1 行指针**(④4,非阻断)。
- **② `CLAUDE.md:86`「降亏过滤」:成立,须修**(理由见必查 1)。
- **③ 角色 skill 教训蒸馏段去掉锚点 id:可接受** —— 新项目无原归档,留 id = 悬空引用;现写法改为指路本包 `lessons-index` + 相关域,反而多出可操作性。

## ④ 建议项(非阻断,均一行级)

1. `work-mode-standard/CLAUDE.md:86`「核心推荐 / 降亏过滤」→「核心推荐 / 过滤」(同文件 `:80` 已统一,recon 有指定改写示例)。
2. `work-mode-standard/docs/quality-flow.md:64`「具体时点见 PROJECT-SPECIFIC.md §5」→ 应指 **§2**(模板 §5=公示位清单,§2=定时任务时点表)—— **断链**,新用户按图索骥会找错。
3. `work-mode-standard/CLAUDE.md:82`「以 PROJECT-SPECIFIC.md 的『测试基准锚点』节为准」→ 模板无此节名(实际内容在模板 §3「权威数据源」的「回测/测试基准定义」行)—— **断链**,两处对齐即可。
4. `main-governance` §11(或 CLAUDE §0.2)补 1 行「续跑同一任务延续原分支」指针。
5. 30 个文件末尾全缺换行符(EOF no newline),顺手补,免得每次 diff 出现 `\ No newline` 噪音。
6. README §4 维护约定开头「本仓(被蒸馏项目)」对"拿走去用"的读者有歧义,建议改「来源项目」;README 域短名与索引域全名统一(二选一或加一行注明)。
7. `role-tester` 教训蒸馏段缺"本角色相关域"列表(其余 3 个 skill 都有),可补 1 行对齐。
8. plan 文档 4 处「157」更正为「158」并加一行注记(防下次引用再漂)。

## ⑤ 待主控/用户拍板项

1. **④1-3 是否合并前修** —— reviewer 建议修完再合(每处 1 行、零风险);若选"原样合并",需把 3 处登记为已知残留。
2. **续跑条落层**:补进共享核心 §0.2(全角色可见)还是 `main-governance` §11(主控可见)—— reviewer 建议后者(使用者是主控),§0.2 也行;请主控定。
3. **plan 的 157→158 更正**:建议顺手改,避免与包内 158 长期并存。
4. **README §4「改动即同步」维护约定**:recon 附 4 写「最终由用户拍板」,README 已写死该承诺 —— 若用户尚未点头,这是对用户的隐含承诺(今后本仓每改一次规范需同步一次包),请确认。

## ⑥ 主控处置(2026-10-15)

- ⑤1 采纳 reviewer 建议:**3 处必修项合并前修**(另连同 ④4/5/6/7 一并修)。
- ⑤2 采纳 reviewer 建议:续跑条补进 **`main-governance`(主控可见层)**。
- ⑤3 采纳:plan 157→158 由主控更正。
- ⑤4 **已上报用户拍板**(README 维护约定 = 对用户的未来同步承诺)。

## ⑦ ⑤测试关(独立 tester 跑方案 §4 证据用例,两轮,2026-10-15)

**第一轮**(对象 `b117a5517`):**4 PASS + 1 FAIL**
- **FAIL = ① 拿走能用实证**:README 安装命令**逐字照抄跑不通** —— 第 ②⑤ 步要往 `<项目>/docs/` 拷文件,却**没有任何一步建这个目录**(只有 ③ 建了 `.claude/{agents,skills}`);且 README **未声明命令的执行目录假设**。实测 `cp: <项目>/docs is not a directory` / `directory does not exist`,exit=1。
  - 注:核心接线本身没问题(`.claude/agents` = 4 文件 / `.claude/skills` = 4 目录 / 4 份 agent 的 `skills:` 4/4 命中 / 拷入副本 `diff -r` 无差异)。
- **PASS**:② 旧包冻结留痕(`claude-work-mode/` diff 空;两 collab README 各 +1 行取代声明)③ 增量落点 8/8 全定位 ④ 核心不丢(15 域各抽 1 条,五字段齐、脱项目语境可读)⑤ 条目数 158 == 正文 158 == 索引 158。
- 另揪小瑕疵:158 条里 **2 条字段标记写法跑偏**(`- **防再犯:**` 冒号跑进加粗内)—— `docs/pitfalls/m-backtest-caliber.md:69`、`docs/pitfalls/o-communication-docs.md:45`。

**修复** `a210a462c`(续原分支,未新开):README 安装块补 `<项目>/docs` 前置 + 补「在**存放本包的上一级目录**执行」的目录假设 + 2 处字段标记对齐。

**第二轮复验**(独立重跑,**未采信实施方自述**;新 HEAD `a210a462c`、全新目录):
- ① **PASS**:命令块用 awk 从**新版 README 原文**抽出(只替换 `<项目>` 占位符)逐行执行,**7/7 exit=0**;`agents` 4 文件 / `skills` 4 目录 / `skills:` 4/4 / `diff -r` 无差异。
- **目录假设自洽性实测**(不是看它自称):包内执行 → exit=1(与 README 警告吻合);`cd ..` 后 → exit=0。
- ② **PASS**:严格口径 `grep '^- \*\*防再犯\*\*:'` = **158**(异形 0);README §7 两行接口措辞 md5 **与修订前完全一致** = 未被动。
- ③ 边界自查:**无新引入的照抄失败**;全包 diff 仅 3 文件。
- 已知残留(非阻断,留档):a) README 一句「否则下面每条命令都会报找不到」略夸大(两条 `mkdir` 实际不依赖包路径);b) 若使用者**改包目录名**,命令里的 `work-mode-standard/` 字面量会失配 —— README 已声明前提,再加一句提示更稳。

**结论**:④ 审查关(含本复验)+ ⑤ 测试关**两关均过** ⇒ 进入 ⑥ 上线关(merge 由主控走 `scripts/main-merge.sh`)。